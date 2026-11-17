"""Model-backed inference for Joern CPG JSON records."""
from __future__ import annotations

import json
from pathlib import Path

import torch
from torch_geometric.data import Data

from vulngnn.models import RGCNClassifier


class GraphPredictor:
    """Load a trained checkpoint and predict from one already extracted graph."""

    def __init__(self, checkpoint_path: str | Path, feature_root: str | Path,
                 device: str = "auto"):
        self.checkpoint_path = Path(checkpoint_path)
        self.feature_root = Path(feature_root)
        self.metadata = json.loads((self.feature_root / "metadata.json").read_text(encoding="utf-8"))
        if self.metadata.get("feature_variant") != "joern_type_only":
            raise ValueError("This local inference adapter currently supports joern_type_only features")
        self.type_vocab = json.loads(
            (self.feature_root / "node_type_vocab.json").read_text(encoding="utf-8"))
        self.edge_vocab = self.metadata["edge_types"]
        self.device = torch.device(
            "cuda" if device == "auto" and torch.cuda.is_available()
            else "cpu" if device == "auto" else device)
        checkpoint = torch.load(self.checkpoint_path, map_location="cpu", weights_only=False)
        params = checkpoint["hyperparameters"]
        self.model = RGCNClassifier(
            input_dim=int(checkpoint["input_dim"]),
            hidden_dim=int(params["hidden_dim"]),
            num_layers=int(params.get("num_layers", params.get("layers", 3))),
            num_relations=len(self.edge_vocab), dropout=float(params["dropout"]),
            edge_ablation=checkpoint.get("edge_ablation", "none"),
        ).to(self.device)
        self.model.load_state_dict(checkpoint["model_state_dict"])
        self.model.eval()
        self.threshold = float(checkpoint["threshold_from_validation"])
        self.setting = str(checkpoint["setting"])
        self.feature_variant = str(checkpoint["feature_variant"])
        self.seed = int(checkpoint["seed"])

    def predict(self, graph: dict) -> dict:
        nodes = graph.get("nodes", [])
        if not nodes:
            raise ValueError("Joern did not produce a function graph with nodes")
        x = torch.zeros((len(nodes), len(self.type_vocab)), dtype=torch.float32)
        for index, node in enumerate(nodes):
            node_type = node.get("type", "")
            x[index, self.type_vocab.get(node_type, self.type_vocab["__UNK__"])] = 1.0

        edge_index_rows, edge_types = [], []
        for edge in graph.get("edges", []):
            if len(edge) < 3:
                continue
            source, target = int(edge[0]), int(edge[1])
            if not (0 <= source < len(nodes) and 0 <= target < len(nodes)):
                continue
            relation_index = int(edge[2])
            if not (0 <= relation_index < len(self.edge_vocab)):
                continue
            edge_index_rows.append((source, target))
            edge_types.append(relation_index)
        if edge_index_rows:
            edge_index = torch.tensor(edge_index_rows, dtype=torch.long).t().contiguous()
            edge_type = torch.tensor(edge_types, dtype=torch.long)
        else:
            edge_index = torch.empty((2, 0), dtype=torch.long)
            edge_type = torch.empty((0,), dtype=torch.long)

        data = Data(x=x, edge_index=edge_index, edge_type=edge_type).to(self.device)
        with torch.inference_mode():
            score = float(torch.sigmoid(self.model(data)).item())
        return {
            "score": score,
            "threshold": self.threshold,
            "prediction": "vulnerable" if score >= self.threshold else "not flagged",
            "feature_variant": self.feature_variant,
            "setting": self.setting,
            "seed": self.seed,
            "checkpoint": self.checkpoint_path.name,
            "nodes": len(nodes),
            "edges": len(edge_index_rows),
            "interpretation": "Uncalibrated model score; research result, not a security verdict.",
        }
