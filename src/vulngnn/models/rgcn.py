"""Relational graph convolutional network for function-level vulnerability labels."""
from __future__ import annotations

import torch
from torch import nn
from torch.nn import functional as F
from torch_geometric.nn import RGCNConv, global_max_pool, global_mean_pool

EDGE_VOCAB = {"AST": 0, "CFG": 1, "REACHING_DEF": 2, "CDG": 3}


class RGCNClassifier(nn.Module):
    """R-GCN with residual updates and mean/max graph-level readout."""

    def __init__(self, input_dim: int, hidden_dim: int = 256, num_layers: int = 3,
                 num_relations: int = 4, num_bases: int | None = None,
                 dropout: float = 0.3, edge_ablation: str = "none"):
        super().__init__()
        if input_dim < 1 or hidden_dim < 1 or num_layers < 1 or num_relations < 1:
            raise ValueError("input_dim, hidden_dim, num_layers and num_relations must be positive")
        if not 0.0 <= dropout < 1.0:
            raise ValueError("dropout must be in [0, 1)")
        if num_bases is not None and num_bases < 1:
            raise ValueError("num_bases must be positive")
        if edge_ablation != "none" and edge_ablation not in EDGE_VOCAB:
            raise ValueError(f"edge_ablation must be one of {['none', *EDGE_VOCAB]}")
        bases = min(num_bases or num_relations, num_relations)
        self.input_proj = nn.Linear(input_dim, hidden_dim)
        self.rel_layers = nn.ModuleList([
            RGCNConv(hidden_dim, hidden_dim, num_relations=num_relations,
                     num_bases=bases, root_weight=False)
            for _ in range(num_layers)
        ])
        self.self_layers = nn.ModuleList([
            nn.Linear(hidden_dim, hidden_dim) for _ in range(num_layers)
        ])
        self.norms = nn.ModuleList([nn.LayerNorm(hidden_dim) for _ in range(num_layers)])
        self.dropout = float(dropout)
        self.edge_ablation = edge_ablation
        self.classifier = nn.Sequential(
            nn.Linear(hidden_dim * 2, hidden_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, 1),
        )

    def forward(self, data) -> torch.Tensor:
        x = data.x.float()
        edge_index = data.edge_index
        edge_type = data.edge_type
        if self.edge_ablation != "none":
            keep = edge_type.ne(EDGE_VOCAB[self.edge_ablation])
            edge_index = edge_index[:, keep]
            edge_type = edge_type[keep]
        batch = getattr(data, "batch", None)
        if batch is None:
            batch = torch.zeros(x.shape[0], dtype=torch.long, device=x.device)

        x = self.input_proj(x)
        for rel_layer, self_layer, norm in zip(self.rel_layers, self.self_layers, self.norms):
            messages = rel_layer(x, edge_index, edge_type)
            update = F.gelu(self_layer(x) + messages)
            x = norm(x + F.dropout(update, p=self.dropout, training=self.training))

        mean = global_mean_pool(x, batch)
        maximum = global_max_pool(x, batch)
        return self.classifier(torch.cat((mean, maximum), dim=-1)).squeeze(-1)
