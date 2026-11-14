"""Attach stable function IDs to legacy baseline scores after strict row checks."""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "data/processed/bigvul_clean.parquet"
SCORES = ROOT / "results/baseline_scores.parquet"
SETTINGS = {"within": "split_within", "cross": "split_cross"}
MODELS = ["length_only", "tfidf_logreg", "tfidf_masked_logreg"]


def main():
    data = pd.read_parquet(DATA, columns=["norm_hash", "project_g", "vul",
                                         "near_dup_cross", *SETTINGS.values()])
    data["near_dup_cross"] = data["near_dup_cross"].astype(bool)
    scores = pd.read_parquet(SCORES)
    aligned = []
    for setting, split_col in SETTINGS.items():
        test = data[data[split_col].eq("test")].copy()
        if setting == "cross":
            test = test[~test["near_dup_cross"]]
        test = test.reset_index(drop=True)
        for model in MODELS:
            group = scores[scores["setting"].eq(setting) & scores["model"].eq(model)].copy()
            group = group.reset_index(drop=True)
            if len(group) != len(test):
                raise ValueError(f"{setting}/{model}: {len(group)} scores for {len(test)} test rows")
            if not group["y"].astype(int).equals(test["vul"].astype(int).reset_index(drop=True)):
                raise ValueError(f"{setting}/{model}: baseline label order differs from saved test rows")
            group["norm_hash"] = test["norm_hash"].astype(str)
            group["project_g"] = test["project_g"].astype(str)
            aligned.append(group)
    result = pd.concat(aligned, ignore_index=True)
    if result.duplicated(["setting", "model", "norm_hash"]).any():
        raise ValueError("Aligned baseline scores contain duplicate function IDs")
    result.to_parquet(SCORES, index=False)
    print(f"Aligned {len(result):,} scores across {len(SETTINGS)} splits and "
          f"{len(MODELS)} baselines; IDs verified against saved labels.")


if __name__ == "__main__":
    main()
