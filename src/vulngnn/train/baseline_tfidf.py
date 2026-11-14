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
IDENTIFIER = re.compile(r"^[A-Za-z_]\w*$")
SETTINGS = {"within": "split_within", "cross": "split_cross"}
C_GRID = [0.01, 0.03, 0.1, 0.3, 1.0, 3.0, 10.0, 30.0]
C_KEYWORDS = set("""
alignas alignof and and_eq asm atomic_cancel atomic_commit atomic_noexcept auto
bitand bitor bool break case catch char char8_t char16_t char32_t class compl
concept const consteval constexpr constinit const_cast continue co_await co_return
co_yield decltype default delete do double dynamic_cast else enum explicit export
extern false float for friend goto if inline int long mutable namespace new noexcept
not not_eq nullptr operator or or_eq private protected public register reinterpret_cast
requires return short signed sizeof static static_assert static_cast struct switch
template this thread_local throw true try typedef typeid typename union unsigned using
restrict virtual void volatile wchar_t while xor xor_eq _Alignas _Alignof _Atomic _Bool
_BitInt _Complex _Generic _Imaginary _Noreturn _Pragma _Static_assert _Thread_local
typeof typeof_unqual
""".split())


def length_features(d):
    chars = d["func_before"].str.len().to_numpy()
    lines = d["func_before"].str.count("\n").to_numpy() + 1
    return np.log1p(np.column_stack([chars, lines]))


def tokenized(code, mask_identifiers=False):
    tokens = TOKEN.findall(COMMENTS.sub(" ", code))
    if mask_identifiers:
        tokens = ["IDENT" if IDENTIFIER.fullmatch(t) and t not in C_KEYWORDS else t
                  for t in tokens]
    return " ".join(tokens)


def fit_tfidf(tr, va, te, ytr, yva, model_name, mask_identifiers=False):
    train_text = [tokenized(s, mask_identifiers) for s in tr["func_before"]]
    val_text = [tokenized(s, mask_identifiers) for s in va["func_before"]]
    test_text = [tokenized(s, mask_identifiers) for s in te["func_before"]]
    vec = TfidfVectorizer(token_pattern=r"\S+", lowercase=False, ngram_range=(1, 2),
                          min_df=5, max_features=100_000, sublinear_tf=True, dtype=np.float32)
    Xtr = vec.fit_transform(train_text)  # vocabulary learned from train only
    Xva = vec.transform(val_text)
    best = None
    for C in C_GRID:
        clf = LogisticRegression(C=C, class_weight="balanced", solver="liblinear", max_iter=200)
        clf.fit(Xtr, ytr)
        sva = clf.predict_proba(Xva)[:, 1]
        ap = average_precision_score(yva, sva)
        print(f"  {model_name} C={C}: val AP = {ap:.4f}", flush=True)
        if best is None or ap > best[0]:
            best = (ap, C, sva, clf)
    Xte = vec.transform(test_text)
    ste = best[3].predict_proba(Xte)[:, 1]
    return best[2], ste, best[1]


def main():
    set_seed(42)
    df = pd.read_parquet(PATH).reset_index(drop=True)
    df["near_dup_cross"] = df["near_dup_cross"].astype(bool)
    print("tokenizing...", flush=True)

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

        scored["tfidf_logreg"] = fit_tfidf(
            tr, va, te, ytr, yva, "tfidf_logreg", mask_identifiers=False)
        scored["tfidf_masked_logreg"] = fit_tfidf(
            tr, va, te, ytr, yva, "tfidf_masked_logreg", mask_identifiers=True)

        for name, (sva, ste, C) in scored.items():
            thr = best_f1_threshold(yva, sva)
            cluster_col = "project_g" if setting == "cross" else "group"
            res = summarize(yte, ste, thr,
                            clusters=te[cluster_col].astype(str).to_numpy(), seed=42)
            results.append({"setting": setting, "model": name, "chosen_C": C, **res})
            score_frames.append(pd.DataFrame({
                "setting": setting, "model": name,
                "norm_hash": te["norm_hash"].astype(str).to_numpy(),
                "project_g": te["project_g"].astype(str).to_numpy(),
                "y": yte, "score": ste,
            }))

    tab = pd.DataFrame(results)
    cols = ["setting", "model", "n", "positives", "prevalence", "ap", "ap_ci_low", "ap_ci_high",
            "roc_auc", "p_at_r30", "p_at_r50", "precision", "recall", "f1"]
    print("\n" + tab[cols].round(3).to_string(index=False))
    tab.to_csv("results/baseline_results.csv", index=False)
    with open("results/baseline_results.json", "w") as f:
        json.dump(results, f, indent=2)
    pd.concat(score_frames).to_parquet("results/baseline_scores.parquet", index=False)
    print("\nsaved results/baseline_results.csv, .json and baseline_scores.parquet")


if __name__ == "__main__":
    main()
