"""Saliency localization against fix-diff lines for vulnerable test functions."""
from __future__ import annotations

import argparse
import difflib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch_geometric.loader import DataLoader

from vulngnn.graphs.build_pyg_dataset import GraphShardDataset
from vulngnn.models import RGCNClassifier

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SOURCE = ROOT / "data/processed/bigvul_clean.parquet"


def changed_lines(before: str, after: str) -> set[int]:
    """Return 1-based vulnerable-source lines changed by the fix.

    Replacements/deletions map to their old lines. Insert-only fixes map to the
    adjacent old line, since there is no inserted line in func_before to score.
    """
    old_lines, new_lines = before.splitlines(), after.splitlines()
    if not old_lines:
        return set()
    changed = set()
    matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
    for tag, i1, i2, _, _ in matcher.get_opcodes():
        if tag in {"replace", "delete"}:
            changed.update(range(i1 + 1, i2 + 1))
        elif tag == "insert":
            changed.add(min(max(i1, 1), len(old_lines)))
    return changed


def line_scores(line_numbers: torch.Tensor, node_scores: torch.Tensor) -> dict[int, float]:
    scores: dict[int, float] = {}
    for line, score in zip(line_numbers.tolist(), node_scores.tolist()):
        if line > 0:
            scores[line] = scores.get(line, 0.0) + float(score)
    return scores


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True,
                        help="PyG feature directory, e.g. codebert_raw")
    parser.add_argument("--predictions", type=Path, required=True,
                        help="test_scores_seedN.parquet produced by train_gnn")
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--source-parquet", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--random-repeats", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if args.batch_size < 1 or args.random_repeats < 1:
        parser.error("batch-size and random-repeats must be positive")

    if args.device == "auto":
        device = torch.device("cuda" if torch.cuda.is_available() else
                              "mps" if hasattr(torch.backends, "mps") and
                              torch.backends.mps.is_available() else "cpu")
    else:
        device = torch.device(args.device)
    dataset = GraphShardDataset(args.data)
    predictions = pd.read_parquet(args.predictions)
    positives = predictions[predictions["y"].astype(int).eq(1)].copy()
    if positives.empty:
        raise SystemExit("No vulnerable test graphs found in prediction file")
    index = dataset.index.reset_index(drop=True)
    index_lookup = {str(value): idx for idx, value in enumerate(index["norm_hash"])}
    positives["dataset_idx"] = positives["norm_hash"].astype(str).map(index_lookup)
    positives = positives.dropna(subset=["dataset_idx"])
    positives["dataset_idx"] = positives["dataset_idx"].astype(int)
    if positives.empty:
        raise SystemExit("Prediction hashes do not match the PyG dataset index")

    hashes = positives["norm_hash"].astype(str).tolist()
    source = pd.read_parquet(
        args.source_parquet,
        columns=["norm_hash", "func_before", "func_after"],
        filters=[("norm_hash", "in", hashes)],
    ).drop_duplicates("norm_hash").fillna("")
    source_by_hash = {str(row.norm_hash): (str(row.func_before), str(row.func_after))
                      for row in source.itertuples(index=False)}

    checkpoint = torch.load(args.checkpoint, map_location=device, weights_only=False)
    if checkpoint.get("feature_variant") != args.data.name:
        raise SystemExit(
            f"Feature variant mismatch: checkpoint uses {checkpoint.get('feature_variant')}, "
            f"dataset path is named {args.data.name}")
    for column, expected in (("setting", checkpoint.get("setting")),
                             ("feature_variant", checkpoint.get("feature_variant")),
                             ("edge_ablation", checkpoint.get("edge_ablation", "none")),
                             ("seed", checkpoint.get("seed"))):
        if column in predictions and not predictions[column].eq(expected).all():
            raise SystemExit(f"Prediction file {column} does not match the checkpoint")
    params = checkpoint["hyperparameters"]
    model = RGCNClassifier(
        input_dim=int(checkpoint["input_dim"]),
        hidden_dim=int(params["hidden_dim"]),
        num_layers=int(params["num_layers"]),
        dropout=float(params["dropout"]),
        edge_ablation=checkpoint.get("edge_ablation", "none"),
    ).to(device)
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()

    selected = sorted(positives["dataset_idx"].tolist())
    data_loader = DataLoader(dataset, batch_size=args.batch_size,
                             sampler=selected, num_workers=0)
    ranked_by_hash = {}
    with torch.enable_grad():
        for batch in data_loader:
            batch = batch.to(device)
            batch.x = batch.x.detach().float().requires_grad_(True)
            logits = model(batch)
            gradients = torch.autograd.grad(logits.sum(), batch.x)[0]
            node_importance = gradients.abs().sum(dim=1)
            for graph_idx, norm_hash in enumerate(batch.norm_hash):
                node_mask = batch.batch.eq(graph_idx)
                ranked_by_hash[str(norm_hash)] = line_scores(
                    batch.line_numbers[node_mask].detach().cpu(),
                    node_importance[node_mask].detach().cpu())

    rng = np.random.default_rng(args.seed)
    per_function = []
    hits = {k: 0 for k in (1, 3, 5)}
    random_hits = {k: 0 for k in (1, 3, 5)}
    n_with_diff, n_localizable = 0, 0
    for row in positives.itertuples(index=False):
        norm_hash = str(row.norm_hash)
        if norm_hash not in source_by_hash or norm_hash not in ranked_by_hash:
            continue
        before, after = source_by_hash[norm_hash]
        all_changed = changed_lines(before, after)
        if not all_changed:
            continue
        n_with_diff += 1
        scores = ranked_by_hash[norm_hash]
        candidates = sorted(scores)
        truth = all_changed.intersection(candidates)
        if not truth:
            continue
        n_localizable += 1
        ranked = sorted(scores, key=lambda line: (-scores[line], line))
        row_result = {"norm_hash": norm_hash, "project_g": row.project_g,
                      "score": float(row.score),
                      "changed_lines": sorted(all_changed),
                      "localizable_changed_lines": sorted(truth),
                      "ranked_lines_top5": ranked[:5],
                      "n_candidate_lines": len(candidates)}
        row_random_hits = {k: 0 for k in (1, 3, 5)}
        for k in (1, 3, 5):
            hit = bool(set(ranked[:k]) & truth)
            hits[k] += int(hit)
            row_result[f"top{k}_hit"] = int(hit)
        if candidates:
            for _ in range(args.random_repeats):
                random_order = rng.permutation(candidates)
                for k in (1, 3, 5):
                    hit = int(bool(set(random_order[:k]) & truth))
                    random_hits[k] += hit
                    row_random_hits[k] += hit
            for k in (1, 3, 5):
                row_result[f"random_top{k}_hit_rate"] = float(
                    row_random_hits[k] / args.random_repeats)
        per_function.append(row_result)

    if not n_localizable:
        raise SystemExit("No vulnerable test graph had both changed lines and line-mapped nodes")
    summary = {
        "n_vulnerable_test_graphs": int(len(positives)),
        "n_with_changed_lines": int(n_with_diff),
        "n_localizable": int(n_localizable),
        "coverage_changed_lines": float(n_with_diff / len(positives)),
        "coverage_localizable": float(n_localizable / len(positives)),
        "random_repeats": int(args.random_repeats),
        "seed": int(args.seed),
        "setting": checkpoint.get("setting"),
        "feature_variant": checkpoint.get("feature_variant"),
        "edge_ablation": checkpoint.get("edge_ablation", "none"),
        "top1_line_hit_rate": float(hits[1] / n_localizable),
        "top3_line_hit_rate": float(hits[3] / n_localizable),
        "top5_line_hit_rate": float(hits[5] / n_localizable),
        "random_top1_line_hit_rate": float(random_hits[1] /
                                            (n_localizable * args.random_repeats)),
        "random_top3_line_hit_rate": float(random_hits[3] /
                                            (n_localizable * args.random_repeats)),
        "random_top5_line_hit_rate": float(random_hits[5] /
                                            (n_localizable * args.random_repeats)),
        "checkpoint": str(args.checkpoint),
        "predictions": str(args.predictions),
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "localization_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n")
    pd.DataFrame(per_function).to_csv(args.output / "localization_per_function.csv", index=False)
    print(json.dumps(summary, indent=2), flush=True)
    print(f"Saved localization outputs under {args.output}", flush=True)


if __name__ == "__main__":
    main()
