"""Baselines on both splits. C is tuned on val only; the threshold is chosen on val too."""
import json
import re

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from vulngnn.eval.metrics import best_f1_threshold, summarize
from vulngnn.utils import set_seed

PATH = "data/processed/bigvul_clean.parquet"
COMMENTS = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)
TOKEN = re.compile(r"[A-Za-z_]\w*|\d+|[^\s\w]")
SETTINGS = {"within": "split_within", "cross": "split_cross"}


def length_features(d):
    chars = d["func_before"].str.len().to_numpy()
    lines = d["func_before"].str.count("\n").to_numpy() + 1
    return np.log1p(np.column_stack([chars, lines]))


set_seed(42)
df = pd.read_parquet(PATH).reset_index(drop=True)
df["near_dup_cross"] = df["near_dup_cross"].astype(bool)
print("tokenizing...", flush=True)
df["toks"] = [" ".join(TOKEN.findall(COMMENTS.sub(" ", s))) for s in df["func_before"]]

results, score_frames = [], []
for setting, col in SETTINGS.items():
    tr, va, te = (df[df[col] == k] for k in ("train", "val", "test"))
    if setting == "cross":  # decision: drop near-duplicate rows from cross-project eval
        va, te = va[~va["near_dup_cross"]], te[~te["near_dup_cross"]]
    ytr, yva, yte = (d["vul"].to_numpy() for d in (tr, va, te))
    print(f"\n=== {setting}: train {len(tr):,} | val {len(va):,} | test {len(te):,}", flush=True)

    scored = {}  # model -> (val scores, test scores, chosen C)

    lm = make_pipeline(StandardScaler(), LogisticRegression(class_weight="balanced", max_iter=1000))
    lm.fit(length_features(tr), ytr)
    scored["length_only"] = (lm.predict_proba(length_features(va))[:, 1],
                             lm.predict_proba(length_features(te))[:, 1], None)

    vec = TfidfVectorizer(token_pattern=r"\S+", lowercase=False, ngram_range=(1, 2),
                          min_df=5, max_features=100_000, sublinear_tf=True, dtype=np.float32)
    Xtr = vec.fit_transform(tr["toks"])  # vocabulary learned from train only
    Xva, Xte = vec.transform(va["toks"]), vec.transform(te["toks"])
    best = None
    for C in [0.1, 1.0, 5.0]:
        clf = LogisticRegression(C=C, class_weight="balanced", solver="liblinear", max_iter=200)
        clf.fit(Xtr, ytr)
        sva = clf.predict_proba(Xva)[:, 1]
        ap = average_precision_score(yva, sva)
        print(f"  tfidf_logreg C={C}: val AP = {ap:.4f}", flush=True)
        if best is None or ap > best[0]:
            best = (ap, C, sva, clf.predict_proba(Xte)[:, 1])
    scored["tfidf_logreg"] = (best[2], best[3], best[1])

    for name, (sva, ste, C) in scored.items():
        thr = best_f1_threshold(yva, sva)
        res = summarize(yte, ste, thr)
        results.append({"setting": setting, "model": name, "chosen_C": C, **res})
        score_frames.append(pd.DataFrame({"setting": setting, "model": name, "y": yte, "score": ste}))

tab = pd.DataFrame(results)
cols = ["setting", "model", "n", "positives", "prevalence", "ap", "ap_ci_low", "ap_ci_high",
        "roc_auc", "p_at_r30", "p_at_r50", "precision", "recall", "f1"]
print("\n" + tab[cols].round(3).to_string(index=False))
tab.to_csv("results/baseline_results.csv", index=False)
with open("results/baseline_results.json", "w") as f:
    json.dump(results, f, indent=2)
pd.concat(score_frames).to_parquet("results/baseline_scores.parquet", index=False)
print("\nsaved results/baseline_results.csv, .json and baseline_scores.parquet")