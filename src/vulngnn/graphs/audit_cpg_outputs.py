"""Independently validate Joern batch stats and compact graph JSONL outputs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_WORKSET = ROOT / "data/graph_workset"
SUCCESS = {"ok", "ok_truncated"}
VALID_STATUSES = SUCCESS | {"no_method", "batch_error"}
EDGE_TYPES = ["AST", "CFG", "REACHING_DEF", "CDG"]
SELECTION_COLUMNS = ["near_dup_cross", "use_train_within", "use_train_cross",
                     "use_eval_within", "use_eval_cross"]
GRAPH_FIELDS = ["norm_hash", "project_g", "split_within", "split_cross",
                *SELECTION_COLUMNS]


def as_bool(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return bool(value)


def same_value(left, right, boolean=False) -> bool:
    if boolean:
        return as_bool(left) == as_bool(right)
    return str(left) == str(right)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workset", type=Path, default=DEFAULT_WORKSET)
    parser.add_argument("--allow-partial", action="store_true",
                        help="audit the recorded subset, e.g. after --limit-batches 1")
    args = parser.parse_args()

    manifest_path = args.workset / "manifest.csv"
    coverage_path = args.workset / "graphs/coverage.csv"
    if not manifest_path.exists() or not coverage_path.exists():
        raise SystemExit("Missing manifest.csv or graphs/coverage.csv")
    manifest = pd.read_csv(manifest_path, dtype={"uid": str, "norm_hash": str},
                           keep_default_na=False)
    coverage = pd.read_csv(coverage_path, dtype={"uid": str, "norm_hash": str},
                           keep_default_na=False)
    required_manifest = {"uid", "norm_hash", "vul", "project_g", "split_within",
                         "split_cross", *SELECTION_COLUMNS}
    required_coverage = {"uid", "norm_hash", "vul", "project_g", "split_within",
                         "split_cross", *SELECTION_COLUMNS, "status", "nodes",
                         "original_nodes", "nodes_dropped", "edges", "max_nodes", "truncated"}
    required_coverage.add("failure_reason")
    if not required_manifest.issubset(manifest.columns):
        raise ValueError(f"Manifest missing columns: {sorted(required_manifest - set(manifest.columns))}")
    if not required_coverage.issubset(coverage.columns):
        raise ValueError(f"Coverage table missing columns: {sorted(required_coverage - set(coverage.columns))}")
    for frame, label in ((manifest, "manifest"), (coverage, "coverage")):
        if frame["uid"].duplicated().any():
            raise ValueError(f"Duplicate function uid in {label}")
    manifest_ids, coverage_ids = set(manifest.uid), set(coverage.uid)
    unknown = coverage_ids - manifest_ids
    missing = manifest_ids - coverage_ids
    if unknown:
        raise ValueError(f"{len(unknown)} coverage rows are absent from the manifest")
    if missing and not args.allow_partial:
        raise ValueError(f"{len(missing)} planned functions lack recorded batch status; "
                         "finish all batches or pass --allow-partial for a smoke audit")

    errors = []
    error_count = 0

    def add_error(message):
        nonlocal error_count
        error_count += 1
        if len(errors) < 100:
            errors.append(message)

    manifest_rows = manifest.set_index("uid").to_dict("index")
    coverage_rows = coverage.set_index("uid").to_dict("index")
    for uid, record in coverage_rows.items():
        planned = manifest_rows[uid]
        if record.get("status") not in VALID_STATUSES:
            add_error(f"{uid}: unknown status {record.get('status')!r}")
        for key in ["norm_hash", "project_g", "split_within", "split_cross", *SELECTION_COLUMNS]:
            is_boolean = key in SELECTION_COLUMNS
            if (key in record and key in planned and
                    not same_value(record[key], planned[key], boolean=is_boolean)):
                add_error(f"{uid}: {key} differs from manifest")
        try:
            label = int(record["vul"])
            if label not in (0, 1):
                add_error(f"{uid}: label is not binary")
            if label != int(planned["vul"]):
                add_error(f"{uid}: label differs from manifest")
            near_dup = as_bool(record["near_dup_cross"])
            for setting, split_col in (("within", "split_within"),
                                       ("cross", "split_cross")):
                role = str(record[split_col])
                use_train = as_bool(record[f"use_train_{setting}"])
                use_eval = as_bool(record[f"use_eval_{setting}"])
                expected_eval = role in {"val", "test"} and not (
                    setting == "cross" and near_dup
                )
                if use_eval != expected_eval:
                    add_error(f"{uid}: {setting} evaluation flag conflicts with split/near-duplicate status")
                if use_train and role != "train":
                    add_error(f"{uid}: {setting} training flag is set outside train split")
                if use_train and use_eval:
                    add_error(f"{uid}: {setting} row is marked for both training and evaluation")
                if role == "train" and label == 1 and not use_train:
                    add_error(f"{uid}: vulnerable {setting} training row was not selected")
            if int(record["nodes"]) < 0 or int(record["edges"]) < 0:
                add_error(f"{uid}: negative node or edge count")
            if record["status"] in SUCCESS:
                if str(record.get("failure_reason", "")):
                    add_error(f"{uid}: successful graph has a failure reason")
                if int(record["nodes"]) < 1:
                    add_error(f"{uid}: successful graph has no nodes")
                if int(record["original_nodes"]) < int(record["nodes"]):
                    add_error(f"{uid}: original node count below retained count")
                if int(record["nodes_dropped"]) != int(record["original_nodes"]) - int(record["nodes"]):
                    add_error(f"{uid}: inconsistent nodes_dropped")
                if as_bool(record["truncated"]) != (int(record["original_nodes"]) > int(record["max_nodes"])):
                    add_error(f"{uid}: inconsistent truncation flag")
            else:
                if not str(record.get("failure_reason", "")).strip():
                    add_error(f"{uid}: failed function has no failure reason")
                if int(record["nodes"]) != 0 or int(record["edges"]) != 0:
                    add_error(f"{uid}: failed graph status has nonzero nodes or edges")
        except (KeyError, TypeError, ValueError) as exc:
            add_error(f"{uid}: malformed coverage row ({exc})")

    graphs_seen = set()
    for path in sorted((args.workset / "graphs").glob("batch_*.jsonl")):
        with path.open() as stream:
            for line_no, line in enumerate(stream, start=1):
                if not line.strip():
                    continue
                try:
                    graph = json.loads(line)
                except json.JSONDecodeError as exc:
                    add_error(f"{path.name}:{line_no}: invalid JSON ({exc})")
                    continue
                uid = graph.get("uid", "")
                if uid not in coverage_rows:
                    add_error(f"{path.name}:{line_no}: graph uid absent from coverage: {uid}")
                    continue
                if uid in graphs_seen:
                    add_error(f"{uid}: duplicate compact graph")
                    continue
                graphs_seen.add(uid)
                required_graph = {"uid", "norm_hash", "label", "project_g",
                                  "split_within", "split_cross", *SELECTION_COLUMNS,
                                  "nodes", "edges", "edge_types", "original_nodes",
                                  "nodes_dropped", "max_nodes", "truncated"}
                missing_fields = required_graph - set(graph)
                if missing_fields:
                    add_error(f"{uid}: graph missing required fields {sorted(missing_fields)}")
                    continue
                row = coverage_rows[uid]
                for field in GRAPH_FIELDS:
                    is_boolean = field in SELECTION_COLUMNS
                    if (field in graph and field in row and
                            not same_value(graph[field], row[field], boolean=is_boolean)):
                        add_error(f"{uid}: graph {field} differs from coverage")
                if int(graph.get("label", -1)) != int(row.get("vul", -2)):
                    add_error(f"{uid}: graph label differs from coverage")
                nodes, edges = graph.get("nodes", []), graph.get("edges", [])
                if len(nodes) != int(row.get("nodes", -1)):
                    add_error(f"{uid}: serialized node count differs from coverage")
                if len(edges) != int(row.get("edges", -1)):
                    add_error(f"{uid}: serialized edge count differs from coverage")
                for field in ("original_nodes", "nodes_dropped", "max_nodes"):
                    if int(graph.get(field, -1)) != int(row.get(field, -2)):
                        add_error(f"{uid}: graph {field} differs from coverage")
                if as_bool(graph.get("truncated")) != as_bool(row.get("truncated")):
                    add_error(f"{uid}: graph truncation flag differs from coverage")
                edge_types = graph.get("edge_types", [])
                if edge_types != EDGE_TYPES:
                    add_error(f"{uid}: unexpected edge type vocabulary")
                for edge in edges:
                    if (not isinstance(edge, list) or len(edge) != 4 or
                            not isinstance(edge[0], int) or not isinstance(edge[1], int) or
                            not isinstance(edge[2], int) or not isinstance(edge[3], str)):
                        add_error(f"{uid}: malformed edge record")
                        break
                    if not (0 <= edge[0] < len(nodes) and 0 <= edge[1] < len(nodes)
                            and 0 <= edge[2] < len(edge_types)):
                        add_error(f"{uid}: edge endpoint or type outside graph bounds")
                        break
                for node in nodes:
                    if (not isinstance(node, dict) or
                            not {"type", "code", "code_truncated", "line"}.issubset(node) or
                            not isinstance(node.get("type"), str) or
                            not isinstance(node.get("code"), str) or
                            not isinstance(node.get("code_truncated"), bool)):
                        add_error(f"{uid}: malformed node record")
                        break
                    line_number = node.get("line")
                    if line_number is not None and (not isinstance(line_number, int) or line_number < 1):
                        add_error(f"{uid}: invalid source line number")
                        break
                if len(nodes) > int(graph.get("max_nodes", -1)):
                    add_error(f"{uid}: retained node count exceeds the cap")
                if graph.get("truncated") and len(nodes) != int(graph.get("max_nodes", -1)):
                    add_error(f"{uid}: truncated graph does not meet node cap")

    expected_graphs = {uid for uid, row in coverage_rows.items() if row["status"] in SUCCESS}
    missing_graphs = expected_graphs - graphs_seen
    unexpected_graphs = graphs_seen - expected_graphs
    if missing_graphs:
        add_error(f"{len(missing_graphs)} successful coverage rows have no JSONL graph")
    if unexpected_graphs:
        add_error(f"{len(unexpected_graphs)} JSONL graphs have a failed/no-method status")
    batch_errors = int(coverage["status"].eq("batch_error").sum())
    if batch_errors:
        add_error(f"{batch_errors} functions have batch_error status")

    joined = coverage.copy()
    joined["success"] = joined["status"].isin(SUCCESS)
    joined["vul"] = joined["vul"].astype(int)
    grouped = []
    for setting, split_col in (("within", "split_within"), ("cross", "split_cross")):
        for role in ("train", "val", "test"):
            selected_col = f"use_train_{setting}" if role == "train" else f"use_eval_{setting}"
            mask = joined[selected_col].map(as_bool)
            if role != "train":
                mask &= joined[split_col].eq(role)
            selected = joined.loc[mask]
            for (project, label), group in selected.groupby(["project_g", "vul"], dropna=False):
                grouped.append({
                    "setting": setting, "role": role, "project_g": project, "vul": int(label),
                    "functions": len(group), "graphs": int(group["success"].sum()),
                    "coverage": float(group["success"].mean()),
                    "truncated": int(group["truncated"].map(as_bool).sum()),
                    "nodes_dropped": int(pd.to_numeric(group["nodes_dropped"]).sum()),
                })
    project_report = pd.DataFrame(grouped)
    project_report.to_csv(args.workset / "graphs/audit_coverage_by_project.csv", index=False)
    status_counts = (coverage.assign(vul=coverage["vul"].astype(int))
                     .groupby(["vul", "status"]).size().unstack(fill_value=0))
    summary = {
        "planned_functions": int(len(manifest)),
        "audited_functions": int(len(coverage)),
        "complete": not missing,
        "successful_graphs": int(len(graphs_seen)),
        "selected_functions_with_batch_error": batch_errors,
        "error_count": error_count,
        "overall_graph_coverage": float(len(graphs_seen) / max(len(coverage), 1)),
        "successful_graphs_truncated": int(coverage["truncated"].map(as_bool).sum()),
        "nodes_dropped_total": int(pd.to_numeric(coverage["nodes_dropped"]).sum()),
        "status_by_label": {str(k): {str(s): int(v) for s, v in row.items()}
                            for k, row in status_counts.to_dict(orient="index").items()},
        "errors": errors,
    }
    summary_path = args.workset / "graphs/audit_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2), flush=True)
    if error_count:
        raise SystemExit(f"Graph audit found {error_count} inconsistencies; see {summary_path}")


if __name__ == "__main__":
    main()
