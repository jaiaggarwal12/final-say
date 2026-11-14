"""Build text, Semgrep and Cppcheck baselines for Phase 2A."""
from __future__ import annotations

import re
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, precision_recall_curve
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from vulngnn.eval.metrics import (best_f1_threshold, bootstrap_ap,
                                  cluster_bootstrap_ap, precision_at_recall,
                                  prf_at, summarize)
from vulngnn.utils import set_seed

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "data/processed/bigvul_clean.parquet"
OUT = ROOT / "results"
SEMGREP = OUT / "semgrep_v2"
SPLITS = {"within": "split_within", "cross": "split_cross"}
C_GRID = [0.01, 0.03, 0.1, 0.3, 1.0, 3.0, 10.0, 30.0]
COMMENTS = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)
RAW_TOKEN = re.compile(r"[A-Za-z_]\w*|\d+|[^\s\w]")
LEX = re.compile(
    r"//[^\n]*|/\*.*?\*/"
    r"|(?:u8|u|U|L)?\"(?:\\.|[^\"\\])*\""
    r"|(?:u|U|L)?'(?:\\.|[^'\\])*'"
    r"|(?:0[xX][0-9A-Fa-f']+(?:\.[0-9A-Fa-f']*)?(?:[pP][+-]?\d[\d']*)?"
    r"|0[bB][01']+|(?:\d[\d']*\.?\d*[eE]?[+-]?\d*[fFlLuU]*)|\.\d+(?:[eE][+-]?\d+)?[fFlL]*)"
    r"|[A-Za-z_]\w*|::|->|\.\.\.|<<=?|>>=?|\+\+|--|&&|\|\||<=|>=|==|!=|\+=|-=|\*=|/=|%=|&=|\|=|\^=|[^\s]",
    re.S,
)
KEYWORDS = set("""
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
API_NAMES = set("""
abort abs access atoi atol atoll bcmp bcopy bzero calloc chdir close closedir
fclose fdopen feof fflush fgetc fgets fileno fopen fprintf fputc fputs fread free
fscanf fseek fstat fwrite getc getchar getenv gets lseek malloc memccpy memchr memcmp
memcpy memmove memset mkdir open opendir perror printf putc puts qsort read realloc
remove rename rewind rmdir scanf snprintf sprintf strcat strchr strcmp strcpy strcspn
strdup strlen strncat strncmp strncpy strnlen strpbrk strrchr strspn strstr strtok
strtol strtoul system unlink vfprintf vsnprintf write
""".split())
IDENT = re.compile(r"^[A-Za-z_]\w*$")


def tokenized_raw(code: str) -> str:
    return " ".join(RAW_TOKEN.findall(COMMENTS.sub(" ", code)))


def tokenized_masked(code: str, keep_apis: bool) -> str:
    mapping: dict[str, str] = {}
    tokens = []
    for match in LEX.finditer(code):
        token = match.group(0)
        if token.startswith("//") or token.startswith("/*"):
            continue
        if token.startswith(('"', "'", 'u"', 'U"', 'L"', 'u8"', "u'", "U'", "L'")):
            tokens.append("STR")
        elif token[0].isdigit() or token.startswith(".") and len(token) > 1 and token[1].isdigit():
            tokens.append("NUM")
        elif IDENT.fullmatch(token):
            if token in KEYWORDS or (keep_apis and token in API_NAMES):
                tokens.append(token)
            else:
                if token not in mapping:
                    mapping[token] = f"ID_{len(mapping) + 1}"
                tokens.append(mapping[token])
        else:
            tokens.append(token)
    return " ".join(tokens)


def fit_text_variant(train, val, test, y_train, y_val, variant):
    if variant == "raw_tokens":
        tokenize = tokenized_raw
    elif variant == "masked_api_kept":
        tokenize = lambda code: tokenized_masked(code, keep_apis=True)
    elif variant == "fully_masked":
        tokenize = lambda code: tokenized_masked(code, keep_apis=False)
    else:
        raise ValueError(f"Unknown text variant: {variant}")
    train_text = [tokenize(code) for code in train["func_before"]]
    val_text = [tokenize(code) for code in val["func_before"]]
    test_text = [tokenize(code) for code in test["func_before"]]
    vectorizer = TfidfVectorizer(token_pattern=r"\S+", lowercase=False,
                                 ngram_range=(1, 2), min_df=5,
                                 max_features=100_000, sublinear_tf=True,
                                 dtype=np.float32)
    x_train = vectorizer.fit_transform(train_text)
    x_val = vectorizer.transform(val_text)
    best = None
    for C in C_GRID:
        clf = LogisticRegression(C=C, class_weight="balanced", solver="liblinear",
                                 max_iter=200, random_state=42)
        clf.fit(x_train, y_train)
        val_scores = clf.predict_proba(x_val)[:, 1]
        val_ap = average_precision_score(y_val, val_scores)
        print(f"  {variant} C={C}: validation AP={val_ap:.4f}", flush=True)
        if best is None or val_ap > best[0]:
            best = (val_ap, C, clf, val_scores)
    test_scores = best[2].predict_proba(vectorizer.transform(test_text))[:, 1]
    return best[1], best[3], test_scores


def save_figures(predictions: pd.DataFrame, result_table: pd.DataFrame) -> None:
    fig_dir = OUT / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    for split in SPLITS:
        fig, ax = plt.subplots(figsize=(8, 6))
        subset = predictions[predictions["split"].eq(split)]
        y = subset["y"].to_numpy(dtype=int)
        prevalence = float(y.mean())
        ax.axhline(prevalence, linestyle="--", color="black",
                   label=f"random (prevalence {prevalence:.3f})")
        for (model, variant), group in subset.groupby(["model", "variant"], sort=True):
            precision, recall, _ = precision_recall_curve(
                group["y"].to_numpy(dtype=int), group["score"].to_numpy(dtype=float))
            ax.plot(recall, precision, label=f"{model}: {variant}")
        ax.set(xlabel="Recall", ylabel="Precision", title=f"{split.title()}-project PR curves")
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.legend(fontsize=7, loc="best")
        fig.tight_layout()
        fig.savefig(fig_dir / f"05_baselines_v2_pr_{split}.png", dpi=160)
        plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 5))
    table = result_table.copy()
    table["ap_over_prevalence"] = table["ap"] / table["prevalence"]
    table["label"] = table["split"] + " | " + table["model"] + " | " + table["variant"]
    ax.barh(table["label"], table["ap_over_prevalence"])
    ax.set_xlabel("Average precision / split prevalence")
    ax.set_title("Lift over random ranking")
    fig.tight_layout()
    fig.savefig(fig_dir / "06_baselines_v2_ap_lift.png", dpi=160)
    plt.close(fig)


def write_conclusion(table: pd.DataFrame) -> None:
    def ap(split, model, variant):
        row = table[(table["split"] == split) & (table["model"] == model) &
                    (table["variant"] == variant)]
        return float(row.iloc[0]["ap"]) if not row.empty else float("nan")

    raw_within = ap("within", "tfidf_logreg", "raw_tokens")
    raw_cross = ap("cross", "tfidf_logreg", "raw_tokens")
    api_cross = ap("cross", "tfidf_logreg", "masked_api_kept")
    full_cross = ap("cross", "tfidf_logreg", "fully_masked")
    cpp_rows = table[table["model"] == "cppcheck"].set_index("split")
    if {"within", "cross"}.issubset(cpp_rows.index):
        cpp_line = (f"- Semgrep produced zero alerts; Cppcheck warning/error recall was "
                    f"{cpp_rows.loc['within', 'recall']:.1%} within and "
                    f"{cpp_rows.loc['cross', 'recall']:.1%} cross at "
                    f"{cpp_rows.loc['within', 'precision']:.1%}/"
                    f"{cpp_rows.loc['cross', 'precision']:.1%} precision, with parser "
                    "failures reported separately.")
    else:
        cpp_line = "- Semgrep findings are narrow ruleset evidence; Cppcheck results are not present in this run."
    prevalence = table[(table["split"] == "cross") &
                       (table["model"] == "tfidf_logreg") &
                       (table["variant"] == "raw_tokens")].iloc[0]["prevalence"]
    lines = [
        "**Supported by these measurements**",
        f"- Raw TF-IDF AP is {raw_within:.3f} within projects and {raw_cross:.3f} across projects (cross prevalence {prevalence:.3f}).",
        f"- Cross-project AP is {raw_cross / prevalence:.1f}x prevalence for raw tokens; identifier masking changes it to {api_cross:.3f} with API names kept and {full_cross:.3f} when all identifiers are masked.",
        cpp_line,
        "**Not established by these measurements**",
        "- The masking comparison does not prove project-vocabulary memorization is the cause; tokenization changes multiple correlated signals and this is one seed.",
        "- These text and static-analysis results do not establish that graph structure generalizes better; that requires held-out-project GNN results.",
    ]
    (OUT / "baselines_v2_conclusion.md").write_text("\n".join(lines) + "\n")


def main() -> None:
    set_seed(42)
    data = pd.read_parquet(DATA).reset_index(drop=True)
    data["near_dup_cross"] = data["near_dup_cross"].astype(bool)
    rows, score_frames, comparison_rows, project_rows, tuning_rows = [], [], [], [], []

    for split, split_col in SPLITS.items():
        train, val, test = (data[data[split_col].eq(part)].copy()
                            for part in ("train", "val", "test"))
        if split == "cross":
            val = val[~val["near_dup_cross"]].copy()
            test = test[~test["near_dup_cross"]].copy()
        y_train = train["vul"].to_numpy(dtype=int)
        y_val = val["vul"].to_numpy(dtype=int)
        y_test = test["vul"].to_numpy(dtype=int)
        cluster_col = "project_g" if split == "cross" else "group"
        test_clusters = test[cluster_col].astype(str).to_numpy()
        print(f"\n=== {split}: train={len(train):,}, val={len(val):,}, test={len(test):,}; "
              f"test prevalence={y_test.mean():.4f}", flush=True)

        length_model = make_pipeline(
            StandardScaler(), LogisticRegression(class_weight="balanced", max_iter=1000,
                                                 random_state=42))
        def length_features(frame):
            chars = frame["func_before"].str.len().to_numpy()
            lines = frame["func_before"].str.count("\n").to_numpy() + 1
            return np.log1p(np.column_stack([chars, lines]))
        length_model.fit(length_features(train), y_train)
        val_scores = length_model.predict_proba(length_features(val))[:, 1]
        test_scores = length_model.predict_proba(length_features(test))[:, 1]
        scored_models = [("length_only", "log_chars_lines", None, val_scores, test_scores)]

        for variant in ("raw_tokens", "masked_api_kept", "fully_masked"):
            chosen_c, val_scores, test_scores = fit_text_variant(
                train, val, test, y_train, y_val, variant)
            scored_models.append(("tfidf_logreg", variant, chosen_c, val_scores, test_scores))

        for model, variant, chosen_c, val_s, test_s in scored_models:
            threshold = best_f1_threshold(y_val, val_s)
            tuning_rows.append({
                "split": split, "model": model, "variant": variant,
                "chosen_C": chosen_c,
                "validation_ap": float(average_precision_score(y_val, val_s)),
                "threshold": float(threshold), "threshold_source": "validation_best_f1",
                "validation_n": int(len(y_val)),
                "validation_positives": int(y_val.sum()),
                "validation_prevalence": float(y_val.mean()),
            })
            result = summarize(y_test, test_s, threshold, clusters=test_clusters, seed=42)
            row = {"split": split, "model": model, "variant": variant,
                   "chosen_C": chosen_c, "threshold_from_validation": threshold,
                   **result}
            rows.append(row)
            pred_frame = pd.DataFrame({
                "split": split, "model": model, "variant": variant,
                "norm_hash": test["norm_hash"].astype(str).to_numpy(),
                "project_g": test["project_g"].astype(str).to_numpy(),
                "group": test["group"].astype(str).to_numpy(),
                "y": y_test, "score": test_s, "threshold": threshold,
                "predicted": test_s >= threshold,
            })
            score_frames.append(pred_frame)
            row_lo, row_hi = bootstrap_ap(y_test, test_s, n=200, seed=42)
            comparison_rows.append({"split": split, "model": model, "variant": variant,
                                    "row_ap_ci_low_optimistic": row_lo,
                                    "row_ap_ci_high_optimistic": row_hi,
                                    "cluster_ap_ci_low": result["ap_ci_low"],
                                    "cluster_ap_ci_high": result["ap_ci_high"]})

        minimum_positive_count = 30
        project_test = test.groupby("project_g", sort=True)
        for project, project_data in project_test:
            pos = int(project_data["vul"].sum())
            if pos < minimum_positive_count:
                continue
            indices = test.index.get_indexer(project_data.index)
            for frame in score_frames:
                if frame["split"].iloc[0] != split:
                    continue
                model, variant = frame["model"].iloc[0], frame["variant"].iloc[0]
                scores = frame.iloc[indices]["score"].to_numpy(dtype=float)
                y = frame.iloc[indices]["y"].to_numpy(dtype=int)
                thr = float(frame["threshold"].iloc[0])
                p, r, f = prf_at(y, scores, thr)
                project_rows.append({"split": split, "project_g": project,
                                     "model": model, "variant": variant,
                                     "n": len(y), "positives": pos,
                                     "prevalence": float(y.mean()),
                                     "ap": float(average_precision_score(y, scores)),
                                     "precision": p, "recall": r, "f1": f})

    predictions = pd.concat(score_frames, ignore_index=True)
    prediction_path = OUT / "baseline_scores_v2.parquet"
    predictions.to_parquet(prediction_path, index=False)

    # Add the fixed Semgrep operating points generated by semgrep_baseline_v2.py.
    semgrep_path = SEMGREP / "predictions.csv"
    if semgrep_path.exists():
        semgrep_predictions = pd.read_csv(semgrep_path)
        for split in SPLITS:
            part = semgrep_predictions[semgrep_predictions["split"].eq(split)]
            if part.empty:
                continue
            cluster_col = "project_g" if split == "cross" else "group"
            clusters = part[cluster_col].astype(str).to_numpy()
            for variant, score_col in (("any_finding", "any_finding"),
                                       ("security_severity", "security_severity_finding")):
                y = part["y"].to_numpy(dtype=int)
                scores = part[score_col].to_numpy(dtype=float)
                threshold = 0.5
                result = summarize(y, scores, threshold, clusters=clusters, seed=42)
                tuning_rows.append({
                    "split": split, "model": "semgrep", "variant": variant,
                    "chosen_C": None, "validation_ap": None,
                    "threshold": threshold, "threshold_source": "fixed_alert_point",
                    "validation_n": None, "validation_positives": None,
                    "validation_prevalence": None,
                })
                rows.append({"split": split, "model": "semgrep", "variant": variant,
                             "chosen_C": None, "threshold_from_validation": threshold,
                             **result})
                pred_frame = pd.DataFrame({
                    "split": split, "model": "semgrep", "variant": variant,
                    "norm_hash": part["norm_hash"].astype(str).to_numpy(),
                    "project_g": part["project_g"].astype(str).to_numpy(),
                    "group": part["group"].astype(str).to_numpy(), "y": y,
                    "score": scores, "threshold": threshold,
                    "predicted": scores >= threshold,
                })
                predictions = pd.concat([predictions, pred_frame], ignore_index=True)
                row_lo, row_hi = bootstrap_ap(y, scores, n=200, seed=42)
                comparison_rows.append({"split": split, "model": "semgrep", "variant": variant,
                                        "row_ap_ci_low_optimistic": row_lo,
                                        "row_ap_ci_high_optimistic": row_hi,
                                        "cluster_ap_ci_low": result["ap_ci_low"],
                                        "cluster_ap_ci_high": result["ap_ci_high"]})
                for project, pgroup in part.groupby("project_g", sort=True):
                    pos = int(pgroup["y"].sum())
                    if pos < 30:
                        continue
                    scores_g = pgroup[score_col].to_numpy(dtype=float)
                    y_g = pgroup["y"].to_numpy(dtype=int)
                    p, r, f = prf_at(y_g, scores_g, threshold)
                    project_rows.append({"split": split, "project_g": project,
                                         "model": "semgrep", "variant": variant,
                                         "n": len(y_g), "positives": pos,
                                         "prevalence": float(y_g.mean()),
                                         "ap": float(average_precision_score(y_g, scores_g)),
                                         "precision": p, "recall": r, "f1": f})
        predictions.to_parquet(prediction_path, index=False)

    # Add the fixed Cppcheck warning/error operating point when its complete
    # test-set run is available. The dedicated runner produces per-file caches.
    cppcheck_dir = OUT / "cppcheck" / "full"
    for split in SPLITS:
        cppcheck_path = cppcheck_dir / f"{split}_predictions.csv"
        if not cppcheck_path.exists():
            continue
        part = pd.read_csv(cppcheck_path)
        expected = 18211 if split == "within" else 23867
        if len(part) != expected:
            raise ValueError(f"Cppcheck {split}: expected {expected} fixed test rows, got {len(part)}")
        part = part.rename(columns={"vul": "y", "flag": "score"})
        if part["norm_hash"].duplicated().any() or not part["score"].isin([0, 1]).all():
            raise ValueError(f"Cppcheck {split}: duplicate IDs or nonbinary scores")
        cluster_col = "project_g" if split == "cross" else "group"
        y = part["y"].to_numpy(dtype=int)
        scores = part["score"].to_numpy(dtype=float)
        clusters = part[cluster_col].astype(str).to_numpy()
        threshold = 0.5
        result = summarize(y, scores, threshold, clusters=clusters, seed=42)
        tuning_rows.append({
            "split": split, "model": "cppcheck", "variant": "warning_or_error",
            "chosen_C": None, "validation_ap": None,
            "threshold": threshold, "threshold_source": "fixed_warning_or_error_point",
            "validation_n": None, "validation_positives": None,
            "validation_prevalence": None,
        })
        rows.append({"split": split, "model": "cppcheck", "variant": "warning_or_error",
                     "chosen_C": None, "threshold_from_validation": threshold, **result})
        pred_frame = pd.DataFrame({
            "split": split, "model": "cppcheck", "variant": "warning_or_error",
            "norm_hash": part["norm_hash"].astype(str).to_numpy(),
            "project_g": part["project_g"].astype(str).to_numpy(),
            "group": part["group"].astype(str).to_numpy(), "y": y,
            "score": scores, "threshold": threshold, "predicted": scores >= threshold,
        })
        predictions = pd.concat([predictions, pred_frame], ignore_index=True)
        row_lo, row_hi = bootstrap_ap(y, scores, n=200, seed=42)
        comparison_rows.append({"split": split, "model": "cppcheck",
                                "variant": "warning_or_error",
                                "row_ap_ci_low_optimistic": row_lo,
                                "row_ap_ci_high_optimistic": row_hi,
                                "cluster_ap_ci_low": result["ap_ci_low"],
                                "cluster_ap_ci_high": result["ap_ci_high"]})
        for project, pgroup in part.groupby("project_g", sort=True):
            pos = int(pgroup["y"].sum())
            if pos < 30:
                continue
            score_g = pgroup["score"].to_numpy(dtype=float)
            y_g = pgroup["y"].to_numpy(dtype=int)
            p, r, f = prf_at(y_g, score_g, threshold)
            project_rows.append({"split": split, "project_g": project,
                                 "model": "cppcheck", "variant": "warning_or_error",
                                 "n": len(y_g), "positives": pos,
                                 "prevalence": float(y_g.mean()),
                                 "ap": float(average_precision_score(y_g, score_g)),
                                 "precision": p, "recall": r, "f1": f})
    predictions.to_parquet(prediction_path, index=False)

    table = pd.DataFrame(rows)
    required_columns = ["split", "model", "variant", "n", "positives", "prevalence",
                        "ap", "ap_ci_low", "ap_ci_high", "p_at_r30", "p_at_r50",
                        "precision", "recall", "f1"]
    table[required_columns].to_csv(OUT / "baselines_v2.csv", index=False)
    predictions.to_parquet(prediction_path, index=False)
    pd.DataFrame(comparison_rows).to_csv(OUT / "bootstrap_ci_comparison.csv", index=False)
    pd.DataFrame(project_rows).to_csv(OUT / "per_project_baselines_v2.csv", index=False)
    pd.DataFrame(tuning_rows).to_csv(OUT / "baseline_tuning_v2.csv", index=False)
    save_figures(predictions, table)
    write_conclusion(table)
    print("\n" + table[required_columns].round(3).to_string(index=False), flush=True)
    print(f"Saved {OUT / 'baselines_v2.csv'} and related v2 artifacts", flush=True)


if __name__ == "__main__":
    main()
