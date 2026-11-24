"""Evaluate validation-selected precision operating points on held-out projects.

Thresholds are chosen on validation only; the held-out test is evaluated once.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from sklearn.metrics import precision_recall_curve

from vulngnn.eval.metrics import summarize
from vulngnn.graphs.build_pyg_dataset import GraphShardDataset
from vulngnn.models import RGCNClassifier
from vulngnn.train.train_gnn import loader, predict

ROOT = Path(__file__).resolve().parents[1]


def choose_threshold(y, scores, target):
    precision, recall, thresholds = precision_recall_curve(y, scores)
    p = precision[:-1]
    r = recall[:-1]
    feasible = np.flatnonzero(p >= target)
    if feasible.size:
        candidates = feasible
        achieved = True
    else:
        best_p = float(p.max())
        candidates = np.flatnonzero(p == best_p)
        achieved = False
    # Among thresholds meeting the requested validation precision, maximize recall.
    # Ties choose the higher threshold for fewer false positives.
    best_recall = r[candidates].max()
    tied = candidates[r[candidates] == best_recall]
    idx = tied[np.argmax(thresholds[tied])]
    return float(thresholds[idx]), bool(achieved), float(p[idx]), float(r[idx])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "data/graph_dataset/joern_type_only")
    parser.add_argument("--models", type=Path, default=ROOT / "results/gnn/joern_type_only/cross/all_edges")
    parser.add_argument("--output", type=Path, default=ROOT / "results/precision_operating_points")
    parser.add_argument("--seeds", type=int, nargs="+", default=[7, 21, 42])
    parser.add_argument("--targets", type=float, nargs="+", default=[0.5, 0.6])
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--device", default="auto")
    args = parser.parse_args()

    device = torch.device("cuda" if args.device == "auto" and torch.cuda.is_available()
                          else "cpu" if args.device == "auto" else args.device)
    dataset = GraphShardDataset(args.data)
    metadata = json.loads((args.data / "metadata.json").read_text(encoding="utf-8"))
    index = dataset.index
    split_col = "split_cross"
    eval_mask = index["use_eval_cross"].astype(bool)
    safe = ~index["near_dup_cross"].astype(bool)
    val_idx = np.flatnonzero(eval_mask & safe & index[split_col].eq("val")).tolist()
    test_idx = np.flatnonzero(eval_mask & safe & index[split_col].eq("test")).tolist()
    val_loader = loader(dataset, val_idx, args.batch_size, False, 42)
    test_loader = loader(dataset, test_idx, args.batch_size, False, 42)
    first = dataset[int(index.index[index["use_train_cross"].astype(bool)][0])]
    input_dim = int(first.x.shape[1])
    all_rows = []

    for seed in args.seeds:
        checkpoint_path = args.models / f"model_seed{seed}.pt"
        checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
        hp = checkpoint["hyperparameters"]
        model = RGCNClassifier(
            input_dim=int(checkpoint["input_dim"]), hidden_dim=int(hp["hidden_dim"]),
            num_layers=int(hp.get("num_layers", hp.get("layers", 3))),
            num_relations=len(metadata["edge_types"]), dropout=float(hp["dropout"]),
            edge_ablation=checkpoint.get("edge_ablation", "none"),
        ).to(device)
        model.load_state_dict(checkpoint["model_state_dict"])
        val_y, val_scores, _, _ = predict(model, val_loader, device)
        test_y, test_scores, _, test_projects = predict(model, test_loader, device)
        clusters = np.asarray(test_projects).astype(str)
        for target in args.targets:
            threshold, achieved, val_precision, val_recall = choose_threshold(val_y, val_scores, target)
            metrics = summarize(test_y, test_scores, threshold, clusters=clusters, seed=seed)
            all_rows.append({
                "seed": seed, "target_validation_precision": target,
                "validation_target_met": achieved, "threshold": threshold,
                "validation_precision": val_precision, "validation_recall": val_recall,
                "test_precision": metrics["precision"], "test_recall": metrics["recall"],
                "test_f1": metrics["f1"], "test_ap": metrics["ap"],
                "test_ap_ci_low": metrics["ap_ci_low"], "test_ap_ci_high": metrics["ap_ci_high"],
                "test_roc_auc": metrics["roc_auc"], "test_n": metrics["n"],
                "test_positives": metrics["positives"],
            })
            print(json.dumps(all_rows[-1]), flush=True)
        del model
        if device.type == "cuda":
            torch.cuda.empty_cache()

    args.output.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(all_rows)
    frame.to_csv(args.output / "cross_precision_operating_points.csv", index=False)
    (args.output / "cross_precision_operating_points.json").write_text(
        json.dumps(all_rows, indent=2) + "\n", encoding="utf-8")
    print(f"Saved validation-selected operating points under {args.output}", flush=True)


if __name__ == "__main__":
    main()




