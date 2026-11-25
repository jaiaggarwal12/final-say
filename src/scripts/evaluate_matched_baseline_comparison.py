"""Compare a saved cross-project GNN to saved text baselines on shared test rows.

The baseline score artifact is the legacy v1 TF-IDF run. Rows are joined by
norm_hash and labels/project IDs are verified before any metric is computed.
Project-cluster bootstrap intervals describe the paired AP difference.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gnn-scores", type=Path, default=ROOT / "results/gnn/joern_type_only/cross/all_edges/test_scores_seed42.parquet")
    parser.add_argument("--baseline-scores", type=Path, default=ROOT / "results/baseline_scores.parquet")
    parser.add_argument("--output", type=Path, default=ROOT / "results/gnn/joern_type_only/cross/matched_baseline_comparison_seed42.csv")
    parser.add_argument("--bootstrap", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if args.bootstrap < 1:
        parser.error("--bootstrap must be positive")

    gnn = pd.read_parquet(args.gnn_scores)
    baselines = pd.read_parquet(args.baseline_scores)
    if "setting" in baselines:
        baselines = baselines[baselines.setting == "cross"]
    required = {"norm_hash", "project_g", "y", "score"}
    if not required.issubset(gnn.columns) or not required.issubset(baselines.columns):
        raise ValueError(f"Both inputs must contain {sorted(required)}")
    if gnn.norm_hash.duplicated().any():
        raise ValueError("GNN test scores contain duplicate norm_hash values")
    if baselines.duplicated(["model", "norm_hash"]).any():
        raise ValueError("Baseline scores contain duplicate model/norm_hash rows")

    rng = np.random.default_rng(args.seed)
    rows = []
    for model, baseline in baselines.groupby("model", sort=True):
        paired = gnn.merge(baseline[["norm_hash", "project_g", "y", "score"]], on="norm_hash", suffixes=("_gnn", "_baseline"), validate="one_to_one")
        if paired.empty:
            continue
        if not (paired.y_gnn == paired.y_baseline).all():
            raise ValueError(f"Labels disagree after joining baseline {model}")
        if not (paired.project_g_gnn == paired.project_g_baseline).all():
            raise ValueError(f"Project IDs disagree after joining baseline {model}")
        y = paired.y_gnn.to_numpy(dtype=int)
        project = paired.project_g_gnn.to_numpy()
        graph_score = paired.score_gnn.to_numpy(dtype=float)
        base_score = paired.score_baseline.to_numpy(dtype=float)
        projects = np.unique(project)
        deltas = []
        indices = {value: np.flatnonzero(project == value) for value in projects}
        for _ in range(args.bootstrap):
            sampled = rng.choice(projects, size=len(projects), replace=True)
            idx = np.concatenate([indices[value] for value in sampled])
            labels = y[idx]
            if labels.min() != labels.max():
                deltas.append(average_precision_score(labels, graph_score[idx]) - average_precision_score(labels, base_score[idx]))
        delta = average_precision_score(y, graph_score) - average_precision_score(y, base_score)
        low, high = np.quantile(deltas, [0.025, 0.975]) if deltas else (np.nan, np.nan)
        rows.append({
            "setting": "cross", "gnn_seed": int(gnn.seed.iloc[0]) if "seed" in gnn else args.seed,
            "baseline_artifact": str(args.baseline_scores.relative_to(ROOT)) if args.baseline_scores.is_relative_to(ROOT) else str(args.baseline_scores),
            "baseline_model": model, "n_shared_test_functions": len(paired),
            "n_positive": int(y.sum()), "n_test_projects": len(projects),
            "gnn_ap": average_precision_score(y, graph_score), "gnn_roc_auc": roc_auc_score(y, graph_score),
            "baseline_ap": average_precision_score(y, base_score), "baseline_roc_auc": roc_auc_score(y, base_score),
            "gnn_minus_baseline_ap": delta, "delta_project_bootstrap_95_low": low,
            "delta_project_bootstrap_95_high": high, "bootstrap_replicates": len(deltas),
        })
    if not rows:
        raise ValueError("No baseline rows matched the GNN test cohort")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(args.output, index=False)
    print(pd.DataFrame(rows).to_string(index=False))
    print(f"Saved: {args.output}")


if __name__ == "__main__":
    main()
