"""Train/evaluate an R-GCN on one saved BigVul split setting."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import math
import platform
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from sklearn.metrics import average_precision_score
from torch import nn
from torch.optim import AdamW
from torch.utils.data import Sampler
from torch_geometric.loader import DataLoader

from vulngnn.eval.metrics import (best_f1_threshold, precision_at_recall,
                                  prf_at, summarize)
from vulngnn.graphs.build_pyg_dataset import GraphShardDataset
from vulngnn.models import RGCNClassifier
from vulngnn.utils import set_seed

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATA = ROOT / "data/graph_dataset/codebert_raw"
DEFAULT_OUTPUT = ROOT / "results/gnn"
BIGVUL_METADATA = ROOT / "data/processed/bigvul_clean.parquet"


class ShardBatchSampler(Sampler[list[int]]):
    """Shuffle examples within each file so the lazy dataset loads each shard once."""

    def __init__(self, indices: list[int], index: pd.DataFrame, batch_size: int,
                 shuffle: bool, seed: int):
        self.indices = indices
        self.batch_size = batch_size
        self.shuffle = shuffle
        self.seed = seed
        self.epoch = 0
        self.by_shard = {}
        for idx in indices:
            shard = index.iloc[idx]["shard"]
            self.by_shard.setdefault(shard, []).append(idx)

    def __iter__(self):
        rng = np.random.default_rng(self.seed + self.epoch)
        self.epoch += 1
        batches = []
        shard_names = list(self.by_shard)
        if self.shuffle:
            rng.shuffle(shard_names)
        for shard in shard_names:
            ids = self.by_shard[shard].copy()
            if self.shuffle:
                rng.shuffle(ids)
            batches.extend(ids[i:i + self.batch_size]
                           for i in range(0, len(ids), self.batch_size))
        yield from batches

    def __len__(self):
        return sum(math.ceil(len(ids) / self.batch_size)
                   for ids in self.by_shard.values())


def loader(dataset, indices: list[int], batch_size: int, shuffle: bool, seed: int):
    sampler = ShardBatchSampler(indices, dataset.index, batch_size, shuffle, seed)
    return DataLoader(dataset, batch_sampler=sampler, num_workers=0)


def predict(model, data_loader, device):
    model.eval()
    labels, scores, hashes, projects = [], [], [], []
    with torch.inference_mode():
        for batch in data_loader:
            batch = batch.to(device)
            logits = model(batch)
            labels.extend(batch.y.detach().cpu().view(-1).tolist())
            scores.extend(torch.sigmoid(logits).detach().cpu().view(-1).tolist())
            hashes.extend(batch.norm_hash)
            projects.extend(batch.project_g)
    return np.asarray(labels, dtype=int), np.asarray(scores, dtype=float), hashes, projects


def schedule_lambda(current_step: int, total_steps: int, warmup_steps: int):
    if warmup_steps and current_step < warmup_steps:
        return max(current_step, 1) / warmup_steps
    progress = (current_step - warmup_steps) / max(total_steps - warmup_steps, 1)
    return max(0.0, 0.5 * (1.0 + math.cos(math.pi * min(progress, 1.0))))


def fit(model, train_loader, val_loader, device, pos_weight, lr,
        weight_decay, epochs, patience, seed, save_best=False):
    set_seed(seed)
    optimizer = AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)
    steps_per_epoch = len(train_loader)
    total_steps = max(steps_per_epoch * epochs, 1)
    warmup_steps = max(1, int(total_steps * 0.05))
    scheduler = torch.optim.lr_scheduler.LambdaLR(
        optimizer, lambda step: schedule_lambda(step, total_steps, warmup_steps))
    criterion = nn.BCEWithLogitsLoss(
        pos_weight=torch.tensor([pos_weight], dtype=torch.float32, device=device))
    best_ap, best_epoch, stale, best_state = -1.0, 0, 0, None
    for epoch in range(1, epochs + 1):
        model.train()
        loss_sum, n_graphs = 0.0, 0
        for batch in train_loader:
            batch = batch.to(device)
            optimizer.zero_grad(set_to_none=True)
            logits = model(batch)
            loss = criterion(logits, batch.y.float().view(-1))
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()
            scheduler.step()
            count = int(batch.num_graphs)
            loss_sum += float(loss.detach()) * count
            n_graphs += count
        labels, scores, _, _ = predict(model, val_loader, device)
        ap = float(average_precision_score(labels, scores))
        print(f"epoch={epoch:03d} train_loss={loss_sum / max(n_graphs, 1):.5f} "
              f"val_ap={ap:.5f}", flush=True)
        if ap > best_ap:
            best_ap, best_epoch, stale = ap, epoch, 0
            if save_best:
                best_state = {key: value.detach().cpu().clone()
                              for key, value in model.state_dict().items()}
        else:
            stale += 1
            if stale >= patience:
                break
    if save_best and best_state is not None:
        model.load_state_dict(best_state)
    return best_ap, best_epoch


def per_project_rows(y, scores, projects, threshold):
    rows = []
    y = np.asarray(y)
    scores = np.asarray(scores)
    for project in sorted(set(projects)):
        idx = np.asarray([i for i, item in enumerate(projects) if item == project])
        project_y, project_scores = y[idx], scores[idx]
        positives = int(project_y.sum())
        if positives < 30:
            continue
        precision, recall, f1 = prf_at(project_y, project_scores, threshold)
        row = {"project_g": project, "n": len(idx), "positives": positives,
               "prevalence": float(project_y.mean()),
               "ap": float(average_precision_score(project_y, project_scores)),
               "p_at_r30": precision_at_recall(project_y, project_scores, 0.3),
               "p_at_r50": precision_at_recall(project_y, project_scores, 0.5),
               "precision": precision, "recall": recall, "f1": f1}
        if len(np.unique(project_y)) == 2:
            from sklearn.metrics import roc_auc_score
            row["roc_auc"] = float(roc_auc_score(project_y, project_scores))
        else:
            row["roc_auc"] = float("nan")
        rows.append(row)
    return rows


def trial_params(trial):
    return {
        "hidden_dim": trial.suggest_categorical("hidden_dim", [128, 256, 384]),
        "num_layers": trial.suggest_int("num_layers", 3, 5),
        "dropout": trial.suggest_float("dropout", 0.1, 0.5),
        "lr": trial.suggest_float("lr", 1e-4, 3e-3, log=True),
        "weight_decay": trial.suggest_float("weight_decay", 1e-6, 1e-3, log=True),
        "pos_weight_scale": trial.suggest_float("pos_weight_scale", 0.5, 2.0),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--setting", choices=["within", "cross"], required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--patience", type=int, default=6)
    parser.add_argument("--hidden-dim", type=int, default=256)
    parser.add_argument("--layers", type=int, default=3)
    parser.add_argument("--dropout", type=float, default=0.3)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--pos-weight-scale", type=float, default=1.0)
    parser.add_argument("--edge-ablation", choices=["none", "AST", "CFG", "REACHING_DEF", "CDG"],
                        default="none", help="drop one relation type for the edge ablation")
    parser.add_argument("--tune-trials", type=int, default=0,
                        help="Optuna trials; each trial uses train/validation only")
    parser.add_argument("--config-json", type=Path, default=None,
                        help="reuse validation-selected hyperparameters for another seed")
    args = parser.parse_args()
    if args.batch_size < 1 or args.epochs < 1 or args.patience < 1 or args.tune_trials < 0:
        parser.error("batch-size, epochs and patience must be positive; tune-trials cannot be negative")

    set_seed(args.seed)
    if args.device == "auto":
        device = torch.device("cuda" if torch.cuda.is_available() else
                              "mps" if hasattr(torch.backends, "mps") and
                              torch.backends.mps.is_available() else "cpu")
    else:
        device = torch.device(args.device)
    dataset = GraphShardDataset(args.data)
    index = dataset.index
    dataset_metadata_path = args.data / "metadata.json"
    if not dataset_metadata_path.exists():
        raise SystemExit(f"Missing feature metadata: {dataset_metadata_path}; rebuild feature shards")
    dataset_metadata = json.loads(dataset_metadata_path.read_text())
    if int(dataset_metadata.get("graphs", -1)) != len(dataset):
        raise SystemExit("Feature metadata graph count does not match graph_index.csv")
    variant = dataset_metadata.get("feature_variant", args.data.name)
    if bool(dataset_metadata.get("masked_identifiers")) != (variant == "codebert_masked"):
        raise SystemExit("Feature metadata variant and identifier-mask flag disagree")
    required = ["label", "project_g", "shard", "use_train_" + args.setting,
                "use_eval_" + args.setting, "split_" + args.setting]
    missing = [col for col in required if col not in index]
    if missing:
        raise SystemExit(f"Graph index lacks required columns: {missing}; rebuild feature shards")
    if args.setting == "cross" and "near_dup_cross" not in index:
        raise SystemExit("Graph index lacks near_dup_cross; rebuild feature shards")
    split_col = "split_" + args.setting
    train_col, eval_col = "use_train_" + args.setting, "use_eval_" + args.setting
    train_mask = index[train_col].astype(bool)
    val_mask = index[eval_col].astype(bool) & index[split_col].eq("val")
    test_mask = index[eval_col].astype(bool) & index[split_col].eq("test")
    if args.setting == "cross":
        no_near_dup = ~index["near_dup_cross"].astype(bool)
        val_mask &= no_near_dup
        test_mask &= no_near_dup
    train_idx = np.flatnonzero(train_mask).tolist()
    val_idx = np.flatnonzero(val_mask).tolist()
    test_idx = np.flatnonzero(test_mask).tolist()
    if not train_idx or not val_idx or not test_idx:
        raise SystemExit("Train, validation and test graphs must all be nonempty")

    y_train = index.loc[train_idx, "label"].to_numpy(dtype=int)
    if y_train.sum() == 0 or y_train.sum() == len(y_train):
        raise SystemExit("Training split must contain both classes")
    raw_pos_weight = (len(y_train) - int(y_train.sum())) / int(y_train.sum())
    val_loader = loader(dataset, val_idx, args.batch_size, False, args.seed)
    test_loader = loader(dataset, test_idx, args.batch_size, False, args.seed)
    first = dataset[train_idx[0]]
    input_dim = int(first.x.shape[1])
    edge_variant = "all_edges" if args.edge_ablation == "none" else f"without_{args.edge_ablation.lower()}"
    run_dir = args.output / variant / args.setting / edge_variant
    run_dir.mkdir(parents=True, exist_ok=True)
    config_path = args.config_json or (run_dir / "best_hparams.json")

    if args.config_json:
        params = json.loads(args.config_json.read_text())
    elif args.tune_trials:
        import optuna

        def objective(trial):
            params_trial = trial_params(trial)
            set_seed(args.seed)
            trial_train_loader = loader(dataset, train_idx, args.batch_size, True, args.seed)
            model = RGCNClassifier(input_dim=input_dim,
                                   hidden_dim=params_trial["hidden_dim"],
                                   num_layers=params_trial["num_layers"], dropout=params_trial["dropout"],
                                   edge_ablation=args.edge_ablation).to(device)
            val_ap, _ = fit(
                model, trial_train_loader, val_loader, device,
                raw_pos_weight * params_trial["pos_weight_scale"],
                params_trial["lr"], params_trial["weight_decay"],
                args.epochs, args.patience, args.seed, save_best=False)
            return val_ap

        study = optuna.create_study(direction="maximize",
                                    sampler=optuna.samplers.TPESampler(seed=args.seed))
        study.optimize(objective, n_trials=args.tune_trials)
        params = dict(study.best_params)
        params["pos_weight_scale"] = study.best_params["pos_weight_scale"]
        config_path.write_text(json.dumps(params, indent=2) + "\n")
        (run_dir / "optuna_summary.json").write_text(json.dumps({
            "best_validation_ap": float(study.best_value),
            "trials": int(len(study.trials)),
            "seed": int(args.seed),
            "best_params": params,
        }, indent=2) + "\n")
        print(f"best validation AP={study.best_value:.5f}; saved {config_path}", flush=True)
    else:
        params = {"hidden_dim": args.hidden_dim, "num_layers": args.layers,
                  "dropout": args.dropout, "lr": args.lr,
                  "weight_decay": args.weight_decay,
                  "pos_weight_scale": args.pos_weight_scale}

    set_seed(args.seed)
    model = RGCNClassifier(input_dim=input_dim, hidden_dim=int(params["hidden_dim"]),
                           num_layers=int(params["num_layers"]),
                           dropout=float(params["dropout"]),
                           edge_ablation=args.edge_ablation).to(device)
    train_loader = loader(dataset, train_idx, args.batch_size, True, args.seed)
    best_val_ap, best_epoch = fit(
        model, train_loader, val_loader, device,
        raw_pos_weight * float(params["pos_weight_scale"]), float(params["lr"]),
        float(params["weight_decay"]), args.epochs, args.patience,
        args.seed, save_best=True)
    val_y, val_scores, _, _ = predict(model, val_loader, device)
    threshold = best_f1_threshold(val_y, val_scores)
    test_y, test_scores, test_hashes, test_projects = predict(model, test_loader, device)
    if args.setting == "cross":
        test_clusters = np.asarray(test_projects).astype(str)
    else:
        function_groups = pd.read_parquet(BIGVUL_METADATA, columns=["norm_hash", "group"])
        group_by_hash = function_groups.set_index("norm_hash")["group"]
        mapped_groups = [group_by_hash.get(str(h)) for h in test_hashes]
        if any(group is None or pd.isna(group) for group in mapped_groups):
            raise ValueError("Within-project test graphs lack function-group metadata")
        test_clusters = np.asarray(mapped_groups).astype(str)
    metrics = summarize(test_y, test_scores, threshold, clusters=test_clusters,
                        seed=args.seed)
    metrics["threshold_from_validation"] = float(threshold)
    metrics["best_validation_ap"] = float(best_val_ap)
    metrics["best_epoch"] = int(best_epoch)
    metrics["seed"] = int(args.seed)
    metrics["setting"] = args.setting
    metrics["feature_variant"] = variant
    metrics["edge_ablation"] = args.edge_ablation
    metrics["n_train_graphs"] = int(len(train_idx))
    metrics["n_train_positives"] = int(y_train.sum())
    metrics["n_validation_graphs"] = int(len(val_idx))
    metrics["n_validation_positives"] = int(index.loc[val_idx, "label"].sum())
    metrics["n_test_graphs"] = int(len(test_idx))
    metrics["environment"] = {
        "python": platform.python_version(),
        "torch": torch.__version__,
        "torch_geometric": importlib.metadata.version("torch-geometric"),
        "device": str(device),
        "cuda_runtime": torch.version.cuda,
        "cuda_device_name": (torch.cuda.get_device_name(device)
                             if device.type == "cuda" else None),
    }
    metrics["feature_metadata"] = dataset_metadata
    metrics["hyperparameters"] = params
    project_rows = per_project_rows(test_y, test_scores, test_projects, threshold)

    pred_df = pd.DataFrame({"norm_hash": test_hashes, "project_g": test_projects,
                            "y": test_y, "score": test_scores,
                            "threshold": threshold,
                            "predicted": (test_scores >= threshold).astype(int),
                            "setting": args.setting, "feature_variant": variant,
                            "edge_ablation": args.edge_ablation, "seed": args.seed})
    pred_df.to_parquet(run_dir / f"test_scores_seed{args.seed}.parquet", index=False)
    pd.DataFrame(project_rows).to_csv(run_dir / f"per_project_seed{args.seed}.csv", index=False)
    result_path = run_dir / f"metrics_seed{args.seed}.json"
    result_path.write_text(json.dumps(metrics, indent=2) + "\n")
    checkpoint = {"model_state_dict": model.state_dict(), "input_dim": input_dim,
                  "hyperparameters": params, "setting": args.setting,
                  "feature_variant": variant, "edge_ablation": args.edge_ablation,
                  "seed": args.seed,
                  "threshold_from_validation": threshold}
    torch.save(checkpoint, run_dir / f"model_seed{args.seed}.pt")
    metric_names = ["ap", "roc_auc", "p_at_r30", "p_at_r50", "precision", "recall",
                    "f1", "prevalence", "ap_ci_low", "ap_ci_high", "best_validation_ap"]
    seed_results = [json.loads(path.read_text())
                    for path in sorted(run_dir.glob("metrics_seed*.json"))]
    summary_rows = []
    for name in metric_names:
        values = [result[name] for result in seed_results
                  if name in result and np.isfinite(result[name])]
        summary_rows.append({"metric": name, "seeds": len(values),
                             "mean": float(np.mean(values)) if values else float("nan"),
                             "std": float(np.std(values, ddof=1)) if len(values) > 1 else 0.0})
    pd.DataFrame(summary_rows).to_csv(run_dir / "seed_summary.csv", index=False)
    print(json.dumps(metrics, indent=2), flush=True)
    print(f"Saved scores, per-project metrics and model under {run_dir}", flush=True)


if __name__ == "__main__":
    main()
