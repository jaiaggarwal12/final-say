"""Encode Joern JSONL graphs as sharded PyTorch Geometric Data objects.

The CodeBERT encoder is frozen. By default each node feature concatenates a
one-hot Joern node type with a CLS embedding of the node's code. Use
--mask-identifiers for the identifier-ablation dataset.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import re
from pathlib import Path

import torch
from torch_geometric.data import Data
from torch.utils.data import Dataset as TorchDataset

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUT = ROOT / "data/graph_workset/graphs"
DEFAULT_OUTPUT = ROOT / "data/graph_dataset"
MODEL_NAME = "microsoft/codebert-base"
DATASET_SCHEMA_VERSION = 4
UNKNOWN_NODE_TYPE = "__UNK__"
TOKEN = re.compile(r"[A-Za-z_]\w*|\d+|[^\s\w]")
IDENTIFIER = re.compile(r"^[A-Za-z_]\w*$")
COMMENTS = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)
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


def mask_identifiers(code: str) -> str:
    tokens = TOKEN.findall(COMMENTS.sub(" ", code))
    return " ".join("IDENT" if IDENTIFIER.fullmatch(token) and token not in KEYWORDS
                     else token for token in tokens)


def choose_device(requested: str) -> torch.device:
    if requested != "auto":
        return torch.device(requested)
    if torch.cuda.is_available():
        return torch.device("cuda")
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def read_records(path: Path):
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def node_type_vocab(paths: list[Path]) -> list[str]:
    """Learn the vocabulary only from rows train in both split definitions."""
    types = {UNKNOWN_NODE_TYPE}
    n_training_graphs = 0
    for path in paths:
        for graph in read_records(path):
            if (graph.get("split_within") != "train"
                    or graph.get("split_cross") != "train"):
                continue
            n_training_graphs += 1
            types.update(node.get("type", "") for node in graph.get("nodes", []))
    types.discard("")
    if n_training_graphs == 0 or len(types) == 1:
        raise ValueError("No training graph node types found in graph JSONL inputs")
    return sorted(types)


def code_text(node: dict, masked: bool) -> str:
    code = node.get("code", "") or ""
    return mask_identifiers(code) if masked else code


def embed_texts(texts: list[str], tokenizer, model, device: torch.device,
                batch_size: int, max_length: int) -> torch.Tensor:
    if not texts:
        return torch.empty((0, model.config.hidden_size), dtype=torch.float16)
    chunks = []
    for start in range(0, len(texts), batch_size):
        tokens = tokenizer(texts[start:start + batch_size], padding=True,
                           truncation=True, max_length=max_length,
                           return_tensors="pt")
        tokens = {key: value.to(device) for key, value in tokens.items()}
        with torch.inference_mode():
            hidden = model(**tokens).last_hidden_state[:, 0, :]
        chunks.append(hidden.to(device="cpu", dtype=torch.float16))
    return torch.cat(chunks, dim=0)


def graph_to_data(graph: dict, embeddings: torch.Tensor,
                  type_vocab: dict[str, int], edge_vocab: dict[str, int]) -> Data:
    nodes = graph["nodes"]
    n_types = len(type_vocab)
    type_features = torch.zeros((len(nodes), n_types), dtype=torch.float16)
    for idx, node in enumerate(nodes):
        node_type = node.get("type", "")
        if node_type not in type_vocab:
            node_type = UNKNOWN_NODE_TYPE
        type_features[idx, type_vocab[node_type]] = 1
    x = torch.cat((type_features, embeddings), dim=1)

    edges = graph.get("edges", [])
    if edges:
        edge_index = torch.tensor([[edge[0] for edge in edges],
                                   [edge[1] for edge in edges]], dtype=torch.long)
        edge_type = torch.tensor([int(edge[2]) for edge in edges], dtype=torch.long)
    else:
        edge_index = torch.empty((2, 0), dtype=torch.long)
        edge_type = torch.empty((0,), dtype=torch.long)
    declared_edges = graph.get("edge_types", [])
    if declared_edges and declared_edges != list(edge_vocab):
        raise ValueError(f"Unexpected edge vocabulary in graph {graph.get('uid')}")

    return Data(
        x=x, edge_index=edge_index, edge_type=edge_type,
        line_numbers=torch.tensor([int(node["line"]) if node.get("line") is not None else -1
                                   for node in nodes], dtype=torch.long),
        y=torch.tensor([int(graph["label"])], dtype=torch.long),
        uid=str(graph.get("uid", "")), norm_hash=str(graph["norm_hash"]),
        project_g=str(graph.get("project_g", "")),
        commit_id=str(graph.get("commit_id", "")),
        cve_id=str(graph.get("cve_id", "")), cwe_id=str(graph.get("cwe_id", "")),
        split_within=str(graph.get("split_within", "")),
        split_cross=str(graph.get("split_cross", "")),
        near_dup_cross=bool(graph.get("near_dup_cross", False)),
        use_train_within=bool(graph.get("use_train_within", False)),
        use_train_cross=bool(graph.get("use_train_cross", False)),
        use_eval_within=bool(graph.get("use_eval_within", False)),
        use_eval_cross=bool(graph.get("use_eval_cross", False)),
        original_nodes=int(graph.get("original_nodes", len(nodes))),
        nodes_dropped=int(graph.get("nodes_dropped", 0)),
        truncated=bool(graph.get("truncated", False)),
    )


def version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "not-installed"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--model", default=MODEL_NAME)
    parser.add_argument("--revision", default=None,
                        help="optional Hugging Face model revision for reproducibility")
    parser.add_argument("--device", default="auto",
                        help="auto, cpu, mps, cuda, or a CUDA device such as cuda:0")
    parser.add_argument("--batch-size", type=int, default=64,
                        help="node texts per CodeBERT forward pass")
    parser.add_argument("--max-length", type=int, default=128,
                        help="maximum CodeBERT subword tokens per node")
    parser.add_argument("--mask-identifiers", action="store_true",
                        help="replace non-keyword identifiers with IDENT before encoding")
    parser.add_argument("--type-only", action="store_true",
                        help="build a Joern structure-only ablation without CodeBERT")
    parser.add_argument("--resume", action="store_true",
                        help="skip input shards with valid existing output files")
    args = parser.parse_args()
    if args.batch_size < 1 or args.max_length < 2:
        parser.error("batch-size must be positive and max-length must be at least 2")

    paths = sorted(args.input.glob("batch_*.jsonl"))
    if not paths:
        raise SystemExit(f"No batch_*.jsonl files found under {args.input}")
    if args.type_only and args.mask_identifiers:
        parser.error("--type-only cannot be combined with --mask-identifiers")
    variant = ("joern_type_only" if args.type_only else
               "codebert_masked" if args.mask_identifiers else "codebert_raw")
    output = args.out / variant
    output.mkdir(parents=True, exist_ok=True)

    print("Building deterministic node-type vocabulary from rows that are train "
          "in both split definitions...", flush=True)
    types = node_type_vocab(paths)
    type_vocab = {name: index for index, name in enumerate(types)}
    type_path = output / "node_type_vocab.json"
    type_path.write_text(json.dumps(type_vocab, indent=2, sort_keys=True) + "\n")
    type_hash = hashlib.sha256(type_path.read_bytes()).hexdigest()

    device = choose_device(args.device)
    if args.type_only:
        print(f"Device: {device}; encoder: none (Joern node types only); "
              f"node types: {len(types)}", flush=True)
        tokenizer = model = None
        resolved_revision = None
    else:
        from transformers import AutoModel, AutoTokenizer

        print(f"Device: {device}; encoder: {args.model}; node types: {len(types)}", flush=True)
        tokenizer = AutoTokenizer.from_pretrained(args.model, revision=args.revision)
        model = AutoModel.from_pretrained(args.model, revision=args.revision).to(device).eval()
        resolved_revision = (getattr(model.config, "_commit_hash", None) or
                             tokenizer.init_kwargs.get("_commit_hash"))
    edge_vocab = {name: index for index, name in enumerate(
        ("AST", "CFG", "REACHING_DEF", "CDG"))}
    index_rows = []

    for shard_no, path in enumerate(paths):
        output_path = output / path.name.replace(".jsonl", ".pt")
        metadata_path = output_path.with_suffix(".json")
        source_hash = sha256_file(path)
        if args.resume and output_path.exists() and metadata_path.exists():
            try:
                metadata = json.loads(metadata_path.read_text())
            except (OSError, json.JSONDecodeError):
                metadata = {}
            if (metadata.get("source_sha256") == source_hash
                    and metadata.get("schema_version") == DATASET_SCHEMA_VERSION
                    and metadata.get("type_vocab_sha256") == type_hash
                    and metadata.get("model") == (None if args.type_only else args.model)
                    and metadata.get("resolved_revision") == resolved_revision
                    and metadata.get("max_length") == (None if args.type_only else args.max_length)
                    and metadata.get("masked_identifiers") == args.mask_identifiers):
                print(f"[{shard_no + 1}/{len(paths)}] {path.name}: resume", flush=True)
                index_rows.extend(metadata["index_rows"])
                continue

        graphs = list(read_records(path))
        data_items = []
        for start in range(0, len(graphs), 32):
            chunk = graphs[start:start + 32]
            texts, lengths = [], []
            for graph in chunk:
                nodes = graph.get("nodes", [])
                lengths.append(len(nodes))
                if not args.type_only:
                    texts.extend(code_text(node, args.mask_identifiers) for node in nodes)
            embeddings = (torch.empty((sum(lengths), 0), dtype=torch.float16)
                          if args.type_only else
                          embed_texts(texts, tokenizer, model, device,
                                      args.batch_size, args.max_length))
            cursor = 0
            for graph, count in zip(chunk, lengths):
                data_items.append(graph_to_data(
                    graph, embeddings[cursor:cursor + count], type_vocab, edge_vocab))
                cursor += count
        tmp = output_path.with_suffix(".pt.tmp")
        torch.save(data_items, tmp)
        tmp.replace(output_path)
        shard_index = [{"uid": data.uid, "norm_hash": data.norm_hash,
                        "shard": output_path.name, "local_index": i,
                        "label": int(data.y.item()),
                        "split_within": data.split_within,
                        "split_cross": data.split_cross,
                        "near_dup_cross": data.near_dup_cross,
                        "use_train_within": data.use_train_within,
                        "use_train_cross": data.use_train_cross,
                        "use_eval_within": data.use_eval_within,
                        "use_eval_cross": data.use_eval_cross,
                        "project_g": data.project_g}
                       for i, data in enumerate(data_items)]
        metadata = {
            "schema_version": DATASET_SCHEMA_VERSION,
            "source": str(path),
            "source_sha256": source_hash,
            "type_vocab_sha256": type_hash,
            "model": None if args.type_only else args.model,
            "revision": None if args.type_only else args.revision,
            "resolved_revision": resolved_revision,
            "max_length": None if args.type_only else args.max_length,
            "masked_identifiers": args.mask_identifiers,
            "feature_variant": variant,
            "graphs": len(data_items), "index_rows": shard_index,
        }
        metadata_path.write_text(json.dumps(metadata, separators=(",", ":")) + "\n")
        index_rows.extend(shard_index)
        print(f"[{shard_no + 1}/{len(paths)}] {path.name}: "
              f"saved {len(data_items):,} graphs", flush=True)

    index_path = output / "graph_index.csv"
    import pandas as pd
    pd.DataFrame(index_rows).to_csv(index_path, index=False)
    environment = {
        "python_torch": version("torch"), "torch_geometric": version("torch-geometric"),
        "transformers": version("transformers"), "model": args.model,
        "model": None if args.type_only else args.model,
        "revision": None if args.type_only else args.revision,
        "resolved_revision": resolved_revision,
        "device": str(device), "masked_identifiers": args.mask_identifiers,
        "feature_variant": variant,
        "max_length": None if args.type_only else args.max_length,
        "node_type_vocab_sha256": type_hash,
        "node_type_vocab_source": "split_within=train AND split_cross=train; labels not read",
        "unknown_node_type": UNKNOWN_NODE_TYPE,
        "graphs": len(index_rows), "node_types": type_vocab,
        "edge_types": edge_vocab,
    }
    (output / "metadata.json").write_text(json.dumps(environment, indent=2) + "\n")
    print(f"Saved {len(index_rows):,} graphs to {output}", flush=True)


class GraphShardDataset(TorchDataset):
    """Lazy map-style reader for the sharded PyG output."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.index = __import__("pandas").read_csv(self.root / "graph_index.csv")
        self._cached_shard = None
        self._cached_items = None
        super().__init__()

    def __len__(self) -> int:
        return len(self.index)

    def __getitem__(self, idx: int) -> Data:
        row = self.index.iloc[idx]
        shard = row["shard"]
        if shard != self._cached_shard:
            self._cached_items = torch.load(self.root / shard, map_location="cpu",
                                            weights_only=False)
            self._cached_shard = shard
        return self._cached_items[int(row["local_index"])]


if __name__ == "__main__":
    main()
