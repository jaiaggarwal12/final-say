"""Evaluate a gradient-times-input line-ranking proxy on held-out vulnerable graphs.

Thresholds and model weights are fixed before this analysis. BigVul fix-changed
lines are a proxy for vulnerable locations, not authoritative line-level labels.
"""
from __future__ import annotations

import argparse
import difflib
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import hypergeom
import pyarrow.parquet as pq
import torch

from vulngnn.graphs.build_pyg_dataset import GraphShardDataset
from vulngnn.models import RGCNClassifier

ROOT = Path(__file__).resolve().parents[2]
FEATURES = ROOT / "data/graph_dataset/joern_type_only"
WORKSET_GRAPHS = ROOT / "data/graph_workset/graphs"
CHECKPOINT = ROOT / "results/gnn/joern_type_only/cross/all_edges/model_seed42.pt"
BIGVUL = ROOT / "data/processed/bigvul_clean.parquet"


def changed_before_lines(before: str, after: str) -> set[int]:
    old = before.splitlines()
    new = after.splitlines()
    targets: set[int] = set()
    for tag, i1, i2, _j1, _j2 in difflib.SequenceMatcher(
            a=old, b=new, autojunk=False).get_opcodes():
        if tag in {"replace", "delete"}:
            targets.update(range(i1 + 1, i2 + 1))
        elif tag == "insert" and old:
            targets.add(min(max(i1, 1), len(old)))
    return {line for line in targets if 1 <= line <= len(old)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=FEATURES)
    parser.add_argument("--workset-graphs", type=Path, default=WORKSET_GRAPHS)
    parser.add_argument("--checkpoint", type=Path, default=CHECKPOINT)
    parser.add_argument("--source-data", type=Path, default=BIGVUL)
    parser.add_argument("--output", type=Path, default=ROOT / "results/line_localization")
    parser.add_argument("--device", default="auto")
    parser.add_argument("--bootstrap", type=int, default=500)
    args = parser.parse_args()

    device = torch.device("cuda" if args.device == "auto" and torch.cuda.is_available()
                          else "cpu" if args.device == "auto" else args.device)
    dataset = GraphShardDataset(args.data)
    idx = dataset.index.reset_index(drop=True)
    mask = (idx["use_eval_cross"].astype(bool)
            & idx["split_cross"].eq("test")
            & ~idx["near_dup_cross"].astype(bool)
            & idx["label"].astype(int).eq(1))
    target_rows = idx.loc[mask].copy()
    needed_hashes = set(target_rows["norm_hash"].astype(str))
    needed_uids = set(target_rows["uid"].astype(str))
    needed_shards = {Path(name).stem for name in target_rows["shard"].astype(str)}
    print(f"held-out vulnerable graphs={len(target_rows)} shards={len(needed_shards)}", flush=True)

    sources = {}
    parquet = pq.ParquetFile(args.source_data)
    for batch in parquet.iter_batches(columns=["norm_hash", "func_before", "func_after"],
                                     batch_size=4096):
        table = batch.to_pydict()
        for h, before, after in zip(table["norm_hash"], table["func_before"], table["func_after"]):
            key = str(h)
            if key in needed_hashes and before is not None and after is not None:
                sources[key] = (str(before), str(after))
    print(f"source pairs found={len(sources)}", flush=True)

    raw_graphs = {}
    for shard in sorted(needed_shards):
        path = args.workset_graphs / f"{shard}.jsonl"
        if not path.is_file():
            continue
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                item = json.loads(line)
                uid = str(item.get("uid", ""))
                if uid in needed_uids:
                    raw_graphs[uid] = item
    print(f"line-numbered graphs found={len(raw_graphs)}", flush=True)

    checkpoint = torch.load(args.checkpoint, map_location="cpu", weights_only=False)
    hp = checkpoint["hyperparameters"]
    metadata = json.loads((args.data / "metadata.json").read_text(encoding="utf-8"))
    model = RGCNClassifier(
        input_dim=int(checkpoint["input_dim"]),
        hidden_dim=int(hp["hidden_dim"]),
        num_layers=int(hp.get("num_layers", hp.get("layers", 3))),
        num_relations=len(metadata["edge_types"]),
        dropout=float(hp["dropout"]),
        edge_ablation=checkpoint.get("edge_ablation", "none"),
    ).to(device)
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()

    rows = []
    for position, (dataset_idx, row) in enumerate(target_rows.iterrows(), start=1):
        uid, norm_hash = str(row["uid"]), str(row["norm_hash"])
        graph = raw_graphs.get(uid)
        source = sources.get(norm_hash)
        if graph is None or source is None:
            continue
        before, after = source
        targets = changed_before_lines(before, after)
        if not targets:
            continue
        data = dataset[int(dataset_idx)].to(device)
        x = data.x.detach().clone().requires_grad_(True)
        data.x = x
        model.zero_grad(set_to_none=True)
        logit = model(data)
        grad = torch.autograd.grad(logit, x, retain_graph=False)[0]
        contributions = (grad * x).sum(dim=1).abs().detach().cpu().numpy()
        line_scores = defaultdict(float)
        for node, score in zip(graph.get("nodes", []), contributions):
            line = node.get("line")
            if line is None:
                continue
            try:
                line = int(line)
            except (ValueError, TypeError):
                continue
            if 1 <= line <= len(before.splitlines()):
                line_scores[line] += float(score)
        if not line_scores:
            continue
        ranked = [line for line, _score in sorted(
            line_scores.items(), key=lambda pair: (-pair[1], pair[0]))]
        n_lines = max(len(before.splitlines()), 1)
        row_out = {"uid": uid, "norm_hash": norm_hash,
                   "project_g": str(row["project_g"]),
                   "n_lines": n_lines, "n_changed_lines": len(targets),
                   "n_attributed_lines": len(line_scores)}
        for k in (1, 3, 5):
            hit = bool(targets.intersection(ranked[:k]))
            row_out[f"hit_at_{k}"] = int(hit)
            row_out[f"random_expected_at_{k}"] = float(hypergeom.sf(0, n_lines, len(targets), min(k, n_lines)))
        rows.append(row_out)
        if position % 100 == 0:
            print(f"processed {position}/{len(target_rows)}", flush=True)

    frame = pd.DataFrame(rows)
    args.output.mkdir(parents=True, exist_ok=True)
    frame.to_csv(args.output / "cross_seed42_line_localization.csv", index=False)
    summary = {"method": "absolute gradient-times-input summed by Joern source line",
               "target": "changed lines from BigVul func_before/func_after diff",
               "interpretation": "patch-overlap proxy; changed lines are not authoritative vulnerable-line labels",
               "split": "cross-project test; near duplicates excluded; vulnerable functions only",
               "checkpoint": str(args.checkpoint.relative_to(ROOT)),
               "evaluated_functions": int(len(frame)),
               "candidate_functions": int(len(target_rows)),
               "line_mapping_coverage": float(len(frame) / max(len(target_rows), 1)),
               "results": {}}
    rng = np.random.default_rng(42)
    projects = frame["project_g"].astype(str).to_numpy() if len(frame) else np.array([])
    unique = np.unique(projects)
    project_members = {p: np.flatnonzero(projects == p) for p in unique}
    for k in (1, 3, 5):
        col = f"hit_at_{k}"
        values = frame[col].to_numpy(dtype=float) if len(frame) else np.array([])
        random_expected = frame[f"random_expected_at_{k}"].mean() if len(frame) else float("nan")
        boot = []
        for _ in range(args.bootstrap):
            if not len(unique):
                break
            sampled = rng.choice(unique, size=len(unique), replace=True)
            sample_idx = np.concatenate([project_members[p] for p in sampled])
            boot.append(float(values[sample_idx].mean()))
        summary["results"][col] = {
            "hit_rate": float(values.mean()) if len(values) else None,
            "project_cluster_95_ci": [float(x) for x in np.percentile(boot, [2.5, 97.5])] if boot else None,
            "random_line_expected_hit_rate": float(random_expected) if np.isfinite(random_expected) else None,
        }
    (args.output / "cross_seed42_line_localization.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
