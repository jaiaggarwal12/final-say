"""Run Joern on prepared graph-workset batches and save compact JSONL graphs."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from collections import Counter, defaultdict, deque
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
EDGE_TYPES = ["AST", "CFG", "REACHING_DEF", "CDG"]
MAX_NODE_CODE_CHARS = 512
MAX_VARIABLE_CHARS = 128
UID_IN_FILENAME = re.compile(r"f_[0-9a-f]{32}")


def clean_header(value: str) -> str:
    value = value.strip().strip('"')
    return value if value.startswith(":") else value.split(":")[0]


def read_group(export_dir: Path, kind: str) -> pd.DataFrame:
    frames = []
    headers = sorted(export_dir.glob(f"{kind}_*_header.csv"))
    for header in headers:
        data = header.with_name(header.name.replace("_header.csv", "_data.csv"))
        if not data.exists():
            continue
        columns = [clean_header(v) for v in header.read_text().strip().split(",")]
        try:
            frame = pd.read_csv(data, header=None, names=columns, dtype=str,
                                keep_default_na=False, index_col=False)
        except pd.errors.EmptyDataError:
            continue
        frame["_group"] = header.name[len(kind) + 1:-len("_header.csv")]
        frames.append(frame)
    if not frames:
        for path in sorted(export_dir.glob(f"{kind}_*.csv")):
            frame = pd.read_csv(path, dtype=str, keep_default_na=False)
            frame.columns = [clean_header(v) for v in frame.columns]
            frame["_group"] = path.stem[len(kind) + 1:]
            frames.append(frame)
    return pd.concat(frames, ignore_index=True).fillna("") if frames else pd.DataFrame()


def get_column(frame: pd.DataFrame, name: str, default="") -> pd.Series:
    return frame[name] if name in frame else pd.Series(default, index=frame.index)


def ast_order(root: str, children: dict[str, list[str]]) -> list[str]:
    seen = {root}
    order = []
    queue = deque([root])
    while queue:
        node = queue.popleft()
        order.append(node)
        for child in children.get(node, []):
            if child not in seen:
                seen.add(child)
                queue.append(child)
    return order


def parse_line(value: str):
    try:
        line = int(float(value))
        return line if line > 0 else None
    except (TypeError, ValueError):
        return None


def parse_bool(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return bool(value)


def directory_size_bytes(path: Path) -> int:
    return sum(file.stat().st_size for file in path.rglob("*") if file.is_file())


def ensure_batch_sources(batch_dir: Path, batch: pd.DataFrame, data_path: Path) -> None:
    """Restore missing source snippets from the parquet before retrying a batch.

    Compact graph archives intentionally omit Joern's large source/export
    working directories. This lets a resumed Kaggle run reconstruct only
    unfinished or invalid batches from the attached source parquet.
    """
    source_dir = batch_dir / "src"
    missing = [row for row in batch.itertuples(index=False)
               if not (source_dir / f"{row.uid}{row.ext}").is_file()]
    if not missing:
        return
    if not data_path.is_file():
        raise FileNotFoundError(
            f"Cannot restore {len(missing)} missing batch source files; "
            f"processed parquet not found: {data_path}"
        )
    hashes = {str(row.norm_hash) for row in missing}
    source = pd.read_parquet(data_path, columns=["norm_hash", "func_before"])
    source["norm_hash"] = source["norm_hash"].astype(str)
    source = source[source["norm_hash"].isin(hashes)]
    if source["norm_hash"].duplicated().any():
        raise ValueError("Processed parquet has duplicate norm_hash values")
    code_by_hash = source.set_index("norm_hash")["func_before"]
    absent = hashes.difference(code_by_hash.index)
    if absent:
        raise KeyError(f"Missing {len(absent)} function hashes in {data_path}")
    source_dir.mkdir(parents=True, exist_ok=True)
    for row in missing:
        code = code_by_hash.loc[str(row.norm_hash)]
        (source_dir / f"{row.uid}{row.ext}").write_text(str(code).rstrip() + "\n")
    print(f"  restored {len(missing):,} missing source files from parquet", flush=True)


def resumable_batch(stats_path: Path, output_path: Path,
                    manifest: pd.DataFrame, max_nodes: int) -> pd.DataFrame | None:
    """Return prior stats only if they cover this batch and its graph UIDs."""
    try:
        old = pd.read_csv(stats_path, dtype={"uid": str}, keep_default_na=False)
        required = {"uid", "status", "max_nodes", "failure_reason"}
        if not required.issubset(old.columns) or old["uid"].duplicated().any():
            return None
        if set(old["uid"]) != set(manifest["uid"].astype(str)):
            return None
        if not old["max_nodes"].astype(int).eq(max_nodes).all():
            return None
        if old["status"].eq("batch_error").any():
            return None
        expected_graph_uids = set(old.loc[
            old["status"].isin(["ok", "ok_truncated"]), "uid"
        ])
        graph_uids = set()
        with output_path.open() as stream:
            for line in stream:
                if not line.strip():
                    continue
                graph = json.loads(line)
                uid = str(graph.get("uid", ""))
                if not uid or uid in graph_uids:
                    return None
                graph_uids.add(uid)
        if graph_uids != expected_graph_uids:
            return None
        return old
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


def export_graphs(export_dir: Path, manifest: pd.DataFrame, output_jsonl: Path,
                  max_nodes: int) -> list[dict]:
    nodes, edges = read_group(export_dir, "nodes"), read_group(export_dir, "edges")
    if nodes.empty or edges.empty or ":ID" not in nodes or not {
            ":START_ID", ":END_ID"}.issubset(edges.columns):
        raise ValueError(f"Missing or malformed Joern node/edge export in {export_dir}")

    nodes["node_type"] = (nodes[":LABEL"] if ":LABEL" in nodes else nodes["_group"])
    edges["edge_type"] = (edges[":TYPE"] if ":TYPE" in edges else edges["_group"])
    nodes = nodes.rename(columns={":ID": "node_id"}).drop_duplicates("node_id")
    edges = edges.rename(columns={":START_ID": "src", ":END_ID": "dst"})
    rows = nodes.set_index("node_id").to_dict("index")

    ast = edges[edges["edge_type"].eq("AST")]
    children: dict[str, list[str]] = defaultdict(list)
    for src, dst in zip(ast["src"], ast["dst"]):
        children[src].append(dst)

    is_external = get_column(nodes, "IS_EXTERNAL").str.lower().eq("true")
    methods = nodes[nodes["node_type"].eq("METHOD") & ~is_external &
                    get_column(nodes, "NAME").ne("<global>")]
    method_by_uid: dict[str, list[str]] = defaultdict(list)
    for method in methods.itertuples(index=False):
        method_data = method._asdict()
        match = UID_IN_FILENAME.search(method_data.get("FILENAME", ""))
        if match:
            method_by_uid[match.group(0)].append(method_data["node_id"])

    vocab = {name: i for i, name in enumerate(EDGE_TYPES)}
    variable_col = next((col for col in edges.columns if col.lower() == "variable"), None)
    edges_by_src: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for edge in edges[edges["edge_type"].isin(EDGE_TYPES)].itertuples(index=False):
        data = edge._asdict()
        variable = data.get(variable_col, "") if variable_col else ""
        edges_by_src[data["src"]].append((data["dst"], data["edge_type"], variable))
    stats = []
    output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with output_jsonl.open("w") as stream:
        for row in manifest.itertuples(index=False):
            methods_for_file = method_by_uid.get(row.uid, [])
            record = {
                "uid": row.uid, "norm_hash": row.norm_hash, "status": "no_method",
                "nodes": 0, "original_nodes": 0, "nodes_dropped": 0, "edges": 0,
                "max_nodes": max_nodes,
                "truncated": False, "project_g": row.project_g, "vul": int(row.vul),
                "failure_reason": "no non-external METHOD with matching source uid in FILENAME",
                "split_within": row.split_within, "split_cross": row.split_cross,
                "near_dup_cross": parse_bool(row.near_dup_cross),
                "use_train_within": parse_bool(row.use_train_within),
                "use_train_cross": parse_bool(row.use_train_cross),
                "use_eval_within": parse_bool(row.use_eval_within),
                "use_eval_cross": parse_bool(row.use_eval_cross),
            }
            if not methods_for_file:
                stats.append(record)
                continue

            orders = [(len(ast_order(mid, children)), mid) for mid in methods_for_file]
            original_count, root = max(orders)
            full_order = ast_order(root, children)
            selected_ids = full_order[:max_nodes]
            keep = set(selected_ids)
            local = {node_id: index for index, node_id in enumerate(selected_ids)}
            node_records = []
            for node_id in selected_ids:
                node = rows[node_id]
                code = node.get("CODE", "")
                node_records.append({
                    "type": node.get("node_type", ""),
                    "code": code[:MAX_NODE_CODE_CHARS],
                    "code_truncated": len(code) > MAX_NODE_CODE_CHARS,
                    "line": parse_line(node.get("LINE_NUMBER", "")),
                })

            edge_records = []
            for src in selected_ids:
                for dst, edge_type, variable in edges_by_src.get(src, []):
                    if dst in keep:
                        edge_records.append([local[src], local[dst], vocab[edge_type],
                                             variable[:MAX_VARIABLE_CHARS]])

            graph = {
                "norm_hash": row.norm_hash,
                "uid": row.uid,
                "label": int(row.vul),
                "project_g": row.project_g,
                "commit_id": row.commit_id,
                "cve_id": row.cve_id,
                "cwe_id": row.cwe_id,
                "split_within": row.split_within,
                "split_cross": row.split_cross,
                "near_dup_cross": parse_bool(row.near_dup_cross),
                "use_train_within": parse_bool(row.use_train_within),
                "use_train_cross": parse_bool(row.use_train_cross),
                "use_eval_within": parse_bool(row.use_eval_within),
                "use_eval_cross": parse_bool(row.use_eval_cross),
                "source_file": row.uid + row.ext,
                "method": rows[root].get("NAME", ""),
                "max_nodes": max_nodes,
                "original_nodes": original_count,
                "nodes_dropped": max(0, original_count - len(node_records)),
                "truncated": original_count > max_nodes,
                "node_types": sorted({node["type"] for node in node_records}),
                "nodes": node_records,
                "edge_types": EDGE_TYPES,
                "edges": edge_records,
            }
            stream.write(json.dumps(graph, separators=(",", ":")) + "\n")
            record.update(status="ok_truncated" if graph["truncated"] else "ok",
                          failure_reason="",
                          nodes=len(node_records), original_nodes=original_count,
                          nodes_dropped=graph["nodes_dropped"], truncated=graph["truncated"],
                          edges=len(edge_records))
            stats.append(record)
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "data/processed/bigvul_clean.parquet",
                        help="source parquet used to restore missing batch inputs on resume")
    parser.add_argument("--workset", type=Path, default=ROOT / "data/graph_workset")
    parser.add_argument("--joern-dir", type=Path, default=ROOT / "tools/joern/joern-cli")
    parser.add_argument("--java-home", type=Path, default=None)
    parser.add_argument("--max-nodes", type=int, default=500)
    parser.add_argument("--limit-batches", type=int, default=None,
                        help="optional smoke run on the first N batches")
    parser.add_argument("--resume", action="store_true",
                        help="skip batches with complete outputs at the requested node cap")
    args = parser.parse_args()
    if args.max_nodes < 1:
        parser.error("max-nodes must be positive")
    joern_dir = args.joern_dir.resolve()
    parse = joern_dir / "joern-parse"
    export = joern_dir / "joern-export"
    if not parse.exists() or not export.exists():
        raise SystemExit(f"Joern CLI not found under {args.joern_dir}")
    if args.java_home:
        os.environ["JAVA_HOME"] = str(args.java_home)
        os.environ["PATH"] = str(args.java_home / "bin") + os.pathsep + os.environ.get("PATH", "")

    manifest_path = args.workset / "manifest.csv"
    if not manifest_path.exists():
        raise SystemExit(f"Missing workset manifest: {manifest_path}")
    columns = ["uid", "norm_hash", "ext", "batch_id", "vul", "project_g",
               "commit_id", "CVE ID", "CWE ID", "split_within", "split_cross",
               "near_dup_cross", "use_train_within", "use_train_cross",
               "use_eval_within", "use_eval_cross"]
    manifest = pd.read_csv(manifest_path, usecols=columns, dtype={"norm_hash": str},
                           keep_default_na=False)
    manifest = manifest.rename(columns={"CVE ID": "cve_id", "CWE ID": "cwe_id"})
    batches = list(manifest.groupby("batch_id", sort=True))
    if args.limit_batches is not None:
        if args.limit_batches < 1:
            parser.error("limit-batches must be positive")
        batches = batches[:args.limit_batches]
    all_stats = []
    graph_dir = args.workset / "graphs"
    log_dir = args.workset / "logs"
    graph_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    for i, (batch_id, batch_manifest) in enumerate(batches, start=1):
        batch_dir = args.workset / "batches" / f"batch_{int(batch_id):05d}"
        output_path = graph_dir / f"batch_{int(batch_id):05d}.jsonl"
        stats_path = graph_dir / f"batch_{int(batch_id):05d}_stats.csv"
        print(f"[{i}/{len(batches)}] batch {int(batch_id):05d}: "
              f"{len(batch_manifest):,} functions", flush=True)
        prior_valid_stats = None
        if output_path.exists() and stats_path.exists():
            prior_valid_stats = resumable_batch(
                stats_path, output_path, batch_manifest, args.max_nodes
            )
            if args.resume and prior_valid_stats is not None:
                print("  resuming: validated prior outputs", flush=True)
                all_stats.extend(prior_valid_stats.to_dict("records"))
                continue
        attempts_dir = batch_dir / "attempts"
        attempt_no = 1
        while (attempts_dir / f"attempt_{attempt_no:03d}").exists():
            attempt_no += 1
        attempt_dir = attempts_dir / f"attempt_{attempt_no:03d}"
        log_path = log_dir / f"batch_{int(batch_id):05d}_attempt_{attempt_no:03d}.log"
        partial_output = graph_dir / (
            f"batch_{int(batch_id):05d}_attempt_{attempt_no:03d}.partial.jsonl"
        )
        try:
            with log_path.open("w") as log:
                ensure_batch_sources(batch_dir, batch_manifest, args.data.resolve())
                attempts_dir.mkdir(parents=True, exist_ok=True)
                attempt_dir.mkdir()
                (attempt_dir / "src").symlink_to(
                    (batch_dir / "src").resolve(), target_is_directory=True
                )
                for cmd in ([str(parse), "src"],
                            [str(export), "--repr", "all", "--format", "neo4jcsv",
                             "--out", "export"]):
                    log.write("$ " + " ".join(cmd) + "\n")
                    log.flush()
                    subprocess.run(cmd, cwd=attempt_dir, stdout=log,
                                   stderr=subprocess.STDOUT, check=True)
            stats = export_graphs(attempt_dir / "export", batch_manifest,
                                  partial_output, args.max_nodes)
            export_bytes = directory_size_bytes(attempt_dir / "export")
            print(f"  CSV export before cleanup: {export_bytes:,} bytes", flush=True)
            # Replace a prior invalid/stale graph file only after the new
            # conversion has completed successfully.
            os.replace(partial_output, output_path)
            # Keep raw CPG/CSV diagnostics on failed conversion. Only clean this
            # successful attempt after compact graphs have been written.
            shutil.rmtree(attempt_dir / "export", ignore_errors=True)
            try:
                (attempt_dir / "cpg.bin").unlink(missing_ok=True)
                (attempt_dir / "src").unlink(missing_ok=True)
                attempt_dir.rmdir()
                if not any(attempts_dir.iterdir()):
                    attempts_dir.rmdir()
            except OSError:
                # Conversion is already committed; leave any leftover temp
                # files for diagnosis rather than changing the batch status.
                pass
        except Exception as exc:
            print(f"  FAILED: {exc}; see {log_path}", flush=True)
            try:
                with log_path.open("a") as log:
                    log.write(f"\nFAILED: {type(exc).__name__}: {exc}\n")
            except OSError:
                pass
            partial_output.unlink(missing_ok=True)
            if prior_valid_stats is not None:
                # A failed forced retry must not make a previously valid graph
                # contradict its batch coverage status.
                stats = prior_valid_stats.to_dict("records")
            else:
                stats = [{"uid": row.uid, "norm_hash": row.norm_hash,
                      "project_g": row.project_g, "vul": int(row.vul),
                      "split_within": row.split_within, "split_cross": row.split_cross,
                      "near_dup_cross": parse_bool(row.near_dup_cross), "status": "batch_error",
                      "failure_reason": f"{exc}; log={log_path}",
                      "max_nodes": args.max_nodes,
                      "use_train_within": parse_bool(row.use_train_within),
                      "use_train_cross": parse_bool(row.use_train_cross),
                      "use_eval_within": parse_bool(row.use_eval_within),
                      "use_eval_cross": parse_bool(row.use_eval_cross),
                      "nodes": 0, "original_nodes": 0, "nodes_dropped": 0,
                      "truncated": False, "edges": 0, "error": str(exc)}
                         for row in batch_manifest.itertuples(index=False)]
        pd.DataFrame(stats).to_csv(stats_path, index=False)
        all_stats.extend(stats)

    summary = pd.DataFrame(all_stats)
    summary.to_csv(graph_dir / "coverage.csv", index=False)
    coverage_parts = []
    for setting, split_col in (("within", "split_within"), ("cross", "split_cross")):
        for role in ("train", "val", "test"):
            selected_col = f"use_train_{setting}" if role == "train" else f"use_eval_{setting}"
            mask = summary[selected_col].map(parse_bool)
            if role != "train":
                mask &= summary[split_col].eq(role)
            group = summary.loc[mask].groupby(["project_g", "vul"], dropna=False)
            part = group.agg(functions=("uid", "size"),
                             graphs=("status", lambda s: s.isin(["ok", "ok_truncated"]).sum()),
                             truncated=("truncated", "sum"),
                             nodes_dropped=("nodes_dropped", "sum")).reset_index()
            part.insert(0, "role", role)
            part.insert(0, "setting", setting)
            part["coverage"] = (part["graphs"].astype(float) /
                                 part["functions"].astype(float))
            coverage_parts.append(part)
    grouped = pd.concat(coverage_parts, ignore_index=True)
    grouped.to_csv(graph_dir / "coverage_by_project.csv", index=False)
    print("\nparse coverage by class:")
    print(summary.groupby("vul").agg(functions=("uid", "size"),
                                      graphs=("status", lambda s: s.isin(["ok", "ok_truncated"]).sum()),
                                      truncated=("truncated", "sum"))
          .to_string())
    print("\nparse coverage by setting, role, and class:")
    print(grouped.groupby(["setting", "role", "vul"])
          [["functions", "graphs", "truncated", "nodes_dropped"]].sum().to_string())
    print(f"\ncoverage saved to {graph_dir / 'coverage.csv'}")


if __name__ == "__main__":
    main()
