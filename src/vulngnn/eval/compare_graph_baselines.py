"""Compare GNN and existing test scores on exactly the same graph-covered rows."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, precision_recall_curve

from vulngnn.eval.metrics import cluster_bootstrap_ap, precision_at_recall, prf_at

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_BASELINES = ROOT / "results/baseline_scores.parquet"
DEFAULT_SEMGREP = ROOT / "results/semgrep"
DEFAULT_OUT = ROOT / "results/gnn/comparison.csv"
BASELINE_MODELS = ["length_only", "tfidf_logreg", "tfidf_masked_logreg"]


def target_precision(y, scores, target):
    precision, recall, _ = precision_recall_curve(y, scores)
    if recall.max() + 1e-12 < target:
        return None
    return precision_at_recall(y, scores, target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gnn-scores", type=Path, nargs="+", required=True)
    parser.add_argument("--baselines", type=Path, default=DEFAULT_BASELINES)
    parser.add_argument("--semgrep-dir", type=Path, default=DEFAULT_SEMGREP)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--bootstrap-samples", type=int, default=500)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if args.bootstrap_samples < 1:
        parser.error("bootstrap-samples must be positive")

    baselines = pd.read_parquet(args.baselines)
    required_baseline_columns = {"setting", "model", "norm_hash", "y", "score"}
    if not required_baseline_columns.issubset(baselines.columns):
        raise ValueError("Baseline scores lack IDs; run vulngnn.eval.align_baseline_scores first")
    if baselines.duplicated(["setting", "model", "norm_hash"]).any():
        raise ValueError("Baseline scores contain duplicate setting/model/function IDs")
    result_rows = []
    for gnn_path in args.gnn_scores:
        gnn = pd.read_parquet(gnn_path)
        if gnn.empty or not {"setting", "norm_hash", "project_g", "y", "score"}.issubset(gnn):
            raise ValueError(f"GNN score file has missing columns or no rows: {gnn_path}")
        setting = str(gnn["setting"].iloc[0])
        variant = str(gnn.get("feature_variant", pd.Series(["unknown"])).iloc[0])
        edge_ablation = str(gnn.get("edge_ablation", pd.Series(["unknown"])).iloc[0])
        seed = int(gnn.get("seed", pd.Series([args.seed])).iloc[0])
        stable_columns = [name for name in ("setting", "feature_variant", "edge_ablation", "seed")
                          if name in gnn]
        if (gnn[stable_columns].nunique().gt(1).any() or
                gnn["norm_hash"].duplicated().any()):
            raise ValueError(f"GNN score file mixes settings or duplicates IDs: {gnn_path}")

        semgrep_path = args.semgrep_dir / f"{setting}_predictions.csv"
        semgrep = pd.read_csv(semgrep_path)
        if not {"norm_hash", "project_g", "vul", "semgrep_alert"}.issubset(semgrep):
            raise ValueError(f"Semgrep predictions missing required columns: {semgrep_path}")
        if semgrep["norm_hash"].duplicated().any() or not semgrep["semgrep_alert"].isin([0, 1]).all():
            raise ValueError(f"Semgrep predictions contain duplicate IDs or nonbinary alerts: {semgrep_path}")
        joined = gnn.merge(semgrep, on="norm_hash", suffixes=("_gnn", "_semgrep"),
                           validate="one_to_one")
        if not (joined["y"].astype(int) == joined["vul"].astype(int)).all():
            raise ValueError(f"GNN and Semgrep labels differ on common IDs: {gnn_path}")
        if not (joined["project_g_gnn"].astype(str) ==
                joined["project_g_semgrep"].astype(str)).all():
            raise ValueError(f"Project labels differ on common IDs: {gnn_path}")
        for model_name in BASELINE_MODELS:
            base = baselines[baselines["setting"].eq(setting) &
                             baselines["model"].eq(model_name)]
            joined = joined.merge(base[["norm_hash", "y", "score"]].rename(
                columns={"y": f"y_{model_name}", "score": f"score_{model_name}"}),
                on="norm_hash", how="inner", validate="one_to_one")
            if not (joined["y"].astype(int) == joined[f"y_{model_name}"].astype(int)).all():
                raise ValueError(f"{model_name} labels differ on common IDs")
        if joined.empty:
            raise ValueError(f"No common rows across models for {gnn_path}")

        y = joined["y"].to_numpy(dtype=int)
        if setting == "cross":
            clusters = joined["project_g_gnn"].astype(str).to_numpy()
        else:
            source_groups = pd.read_parquet(
                ROOT / "data/processed/bigvul_clean.parquet",
                columns=["norm_hash", "group"],
            ).drop_duplicates("norm_hash").set_index("norm_hash")["group"]
            mapped_groups = joined["norm_hash"].astype(str).map(source_groups)
            if mapped_groups.isna().any():
                raise ValueError("Within-project comparison rows lack function-group metadata")
            clusters = mapped_groups.astype(str).to_numpy()
        semgrep_alert = joined["semgrep_alert"].to_numpy(dtype=int)
        semgrep_precision, semgrep_recall, semgrep_f1 = prf_at(
            y, semgrep_alert.astype(float), 0.5)
        rows = []
        for model_name in BASELINE_MODELS:
            scores = joined[f"score_{model_name}"].to_numpy(dtype=float)
            lo, hi = cluster_bootstrap_ap(y, scores, clusters,
                                          args.bootstrap_samples, args.seed)
            rows.append({
                "method": model_name, "n": len(y), "positives": int(y.sum()),
                "prevalence": float(y.mean()), "ap": float(average_precision_score(y, scores)),
                "ap_ci_cluster_low": lo, "ap_ci_cluster_high": hi,
                "p_at_r30": target_precision(y, scores, 0.30),
                "p_at_r50": target_precision(y, scores, 0.50),
                "precision_at_semgrep_recall": None,
                "semgrep_recall_matched": False,
            })
        gnn_scores = joined["score"].to_numpy(dtype=float)
        gnn_lo, gnn_hi = cluster_bootstrap_ap(y, gnn_scores, clusters,
                                              args.bootstrap_samples, args.seed)
        threshold = float(joined["threshold"].iloc[0]) if "threshold" in joined else 0.5
        if "threshold" in joined and not np.allclose(joined["threshold"], threshold):
            raise ValueError(f"GNN score file contains multiple thresholds: {gnn_path}")
        precision, recall, f1 = prf_at(y, gnn_scores, threshold)
        rows.append({
            "method": "gnn", "n": len(y), "positives": int(y.sum()),
            "prevalence": float(y.mean()), "ap": float(average_precision_score(y, gnn_scores)),
            "ap_ci_cluster_low": gnn_lo, "ap_ci_cluster_high": gnn_hi,
            "p_at_r30": target_precision(y, gnn_scores, 0.30),
            "p_at_r50": target_precision(y, gnn_scores, 0.50),
            "precision": precision, "recall": recall, "f1": f1,
            "precision_at_semgrep_recall": (
                target_precision(y, gnn_scores, semgrep_recall) if semgrep_recall > 0 else None),
            "semgrep_recall_matched": bool(semgrep_recall > 0),
        })
        rows.append({
            "method": "semgrep", "n": len(y), "positives": int(y.sum()),
            "prevalence": float(y.mean()), "ap": None,
            "precision": semgrep_precision, "recall": semgrep_recall, "f1": semgrep_f1,
            "alerts": int(semgrep_alert.sum()),
            "precision_at_semgrep_recall": None, "semgrep_recall_matched": None,
        })
        for row in rows:
            row.update(setting=setting, feature_variant=variant,
                       edge_ablation=edge_ablation, seed=seed,
                       gnn_score_file=str(gnn_path),
                       common_rows=len(joined), common_positives=int(y.sum()))
            result_rows.append(row)

    result = pd.DataFrame(result_rows)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output, index=False)
    args.output.with_suffix(".json").write_text(
        json.dumps(result_rows, indent=2, allow_nan=True) + "\n")
    print(result.to_string(index=False), flush=True)
    print(f"Saved comparison to {args.output}", flush=True)


if __name__ == "__main__":
    main()
