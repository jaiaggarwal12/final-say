#!/usr/bin/env python3
"""Serve the VulnGNN research website and read-only local research APIs."""
from __future__ import annotations

import csv
from functools import lru_cache
import hashlib
import json
import math
import os
import re
import subprocess
import shutil
import sys
import tempfile
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
BASELINES = ROOT / "results/baselines_v2.csv"
PROJECTS = ROOT / "results/per_project_baselines_v2.csv"
PILOT_GRAPHS = ROOT / "data/pilot/graphs"
PILOT_SOURCE = ROOT / "data/pilot/src"
WORKSET = ROOT / "data/graph_workset"
WORKSET_MANIFEST = WORKSET / "manifest.csv"
WORKSET_GRAPHS = WORKSET / "graphs"
FIGURES = ROOT / "results/figures"
GRAPH_AUDIT = ROOT / "data/graph_workset/graphs/audit_summary.json"
GNN_RESULTS = ROOT / "results/gnn"
JOERN_DIR = ROOT / "tools/joern/joern-cli"
FEATURE_ROOT = ROOT / "data/graph_dataset/joern_type_only"
GRAPH_ID = re.compile(r"^f_[0-9a-f]{12,32}$")
FIGURE_NAMES = {
    "05_baselines_v2_pr_within.png",
    "05_baselines_v2_pr_cross.png",
    "06_baselines_v2_ap_lift.png",
}


def read_csv(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def json_safe(value: object) -> object:
    """Convert non-finite floats to JSON null (NaN is not valid JSON)."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    return value


def graph_status() -> dict:
    """Return audited graph-workset status without loading the graph corpus."""
    try:
        audit = json.loads(GRAPH_AUDIT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"complete": False, "planned_functions": 0, "successful_graphs": 0}
    return {
        "complete": bool(audit.get("complete")) and int(audit.get("error_count", 0)) == 0,
        "planned_functions": int(audit.get("planned_functions", 0)),
        "successful_graphs": int(audit.get("successful_graphs", 0)),
        "audit_errors": int(audit.get("error_count", 0)),
        "truncated_graphs": int(audit.get("successful_graphs_truncated", 0)),
    }


def available_gnn_checkpoints() -> list[str]:
    if not GNN_RESULTS.is_dir():
        return []
    return [str(path.relative_to(ROOT)).replace("\\", "/")
            for path in sorted(GNN_RESULTS.rglob("model_seed*.pt")) if path.is_file()]


def active_checkpoint() -> Path | None:
    preferred = GNN_RESULTS / "joern_type_only/cross/all_edges/model_seed42.pt"
    if preferred.is_file():
        return preferred
    paths = sorted(GNN_RESULTS.rglob("model_seed*.pt")) if GNN_RESULTS.is_dir() else []
    return paths[0] if paths else None


def gnn_test_metrics() -> list[dict]:
    rows = []
    if not GNN_RESULTS.is_dir():
        return rows
    for path in sorted(GNN_RESULTS.rglob("metrics_seed*.json")):
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        # A split's test rows are publishable only when its own validation
        # tuning selected the saved checkpoint hyperparameters. This avoids
        # exposing exploratory runs whose settings came from another split.
        if item.get("setting") in {"within", "cross"}:
            summary_path = path.parent / "optuna_summary.json"
            if summary_path.is_file():
                try:
                    selected = json.loads(summary_path.read_text(encoding="utf-8"))
                    if path.stat().st_mtime_ns <= summary_path.stat().st_mtime_ns:
                        continue
                    expected = selected.get("best_params", {})
                    actual = item.get("hyperparameters", {})
                    if any(actual.get(key) != value for key, value in expected.items()):
                        continue
                except (OSError, json.JSONDecodeError):
                    continue
            elif item.get("setting") == "within" and (path.parent / "exploratory_crossval_tuned_within_seed42.json").is_file():
                continue
        rows.append({key: item.get(key) for key in (
            "setting", "feature_variant", "edge_ablation", "seed", "ap",
            "ap_ci_low", "ap_ci_high", "roc_auc", "precision", "recall",
            "f1", "prevalence", "n_train_graphs", "n_validation_graphs",
            "n_test_graphs", "n_train_positives", "n_validation_positives",
            "threshold_from_validation", "best_validation_ap", "best_epoch",
            "environment") } | {"checkpoint": path.with_name(f"model_seed{item.get('seed')}.pt").is_file()})
    return rows


@lru_cache(maxsize=4)
def _load_predictor(checkpoint: str, modified_ns: int):
    del modified_ns
    sys.path.insert(0, str(ROOT / "src"))
    from vulngnn.inference import GraphPredictor
    return GraphPredictor(checkpoint, FEATURE_ROOT)


def graph_predictor():
    checkpoint = active_checkpoint()
    if checkpoint is None:
        return None
    try:
        return _load_predictor(str(checkpoint), checkpoint.stat().st_mtime_ns)
    except (OSError, ValueError, KeyError, RuntimeError):
        return None


def graph_from_source(code: str, extension: str) -> dict:
    """Run the bundled Joern CLI on one local source file."""
    sys.path.insert(0, str(ROOT / "src"))
    import pandas as pd
    from vulngnn.graphs.run_cpg_batches import export_graphs

    digest = hashlib.sha256(code.encode("utf-8")).hexdigest()
    uid = "f_" + digest[:32]
    row = {
        "uid": uid, "norm_hash": digest, "ext": extension, "batch_id": 0,
        "vul": 0, "project_g": "local_input", "commit_id": "",
        "cve_id": "", "cwe_id": "", "split_within": "inference",
        "split_cross": "inference", "near_dup_cross": False,
        "use_train_within": False, "use_train_cross": False,
        "use_eval_within": False, "use_eval_cross": False,
    }
    parse = JOERN_DIR / "joern-parse.bat"
    export = JOERN_DIR / "joern-export.bat"
    if not parse.is_file() or not export.is_file():
        raise RuntimeError("Bundled Joern command line tools are unavailable")
    with tempfile.TemporaryDirectory(prefix="vulngnn-local-inference-") as temp:
        work = Path(temp)
        source_dir = work / "src"
        source_dir.mkdir()
        (source_dir / f"{uid}{extension}").write_text(code, encoding="utf-8")

        def run_bat(script: Path, *args: str) -> None:
            command = "call " + subprocess.list2cmdline([str(script), *args])
            env = os.environ.copy()
            bundled_jvm = ROOT / "tools/temurin-21-jre/jdk-21.0.13+9-jre"
            if (bundled_jvm / "bin" / "java.exe").is_file():
                env["BUNDLED_JVM"] = str(bundled_jvm)
            subprocess.run(command, cwd=work, shell=True, check=True, timeout=150,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           text=True, encoding="utf-8", errors="replace", env=env)

        cpp_markers = ("namespace ", "template<", "template <", "class ", "std::", "using namespace ", "nullptr", "::")
        is_cpp = extension in {".cc", ".cpp", ".cxx", ".hpp"} or any(marker in code for marker in cpp_markers)
        graph_jsonl = work / "graph.jsonl"

        def extract_with_frontend(language: str) -> dict:
            cpg_path = work / "cpg.bin"
            export_path = work / "export"
            if cpg_path.exists():
                cpg_path.unlink()
            if export_path.exists():
                shutil.rmtree(export_path)
            graph_jsonl.unlink(missing_ok=True)
            run_bat(parse, "--language", language, "src")
            run_bat(export, "--repr", "all", "--format", "neo4jcsv", "--out", "export")
            export_graphs(export_path, pd.DataFrame([row]), graph_jsonl, 500)
            if not graph_jsonl.is_file() or not graph_jsonl.stat().st_size:
                raise ValueError("Joern could not find a function in this source file")
            return json.loads(graph_jsonl.read_text(encoding="utf-8").splitlines()[0])

        # Try the C frontend first to match training; fall back only when it cannot parse C++ syntax.
        try:
            graph = extract_with_frontend("c")
        except subprocess.CalledProcessError:
            if not is_cpp:
                raise
            graph = extract_with_frontend("newc")
        if graph.get("status") == "no_method" and is_cpp:
            graph = extract_with_frontend("newc")
        if graph.get("status") == "no_method":
            raise ValueError("Joern could not find a C/C++ function to analyze")
        graph["source_file"] = f"{uid}{extension}"
        graph["source"] = code
        return graph


@lru_cache(maxsize=1)
def demo_graphs() -> dict[str, dict]:
    """Load a compact, balanced demo from real cross-project test graphs."""
    manifest = read_csv(WORKSET_MANIFEST)
    eligible = [row for row in manifest
                if row.get("batch_id") == "0" and row.get("split_cross") == "test"
                and row.get("near_dup_cross", "False").lower() == "false"]
    selected: dict[str, dict] = {}
    for label in (0, 1):
        seen_projects: set[str] = set()
        for row in eligible:
            if int(row.get("vul", 0)) != label:
                continue
            project = row.get("project_g", "")
            if label == 0 and project in seen_projects:
                continue
            selected[row["uid"]] = row
            seen_projects.add(project)
            if sum(int(item.get("vul", 0)) == label for item in selected.values()) >= 10:
                break
    if not selected:
        return {}

    graph_path = WORKSET_GRAPHS / "batch_00000.jsonl"
    found: dict[str, dict] = {}
    wanted = set(selected)
    try:
        with graph_path.open(encoding="utf-8") as stream:
            for line in stream:
                graph = json.loads(line)
                uid = graph.get("uid")
                if uid not in wanted:
                    continue
                row = selected[uid]
                graph.update({
                    "project": row.get("project_g"), "cve": row.get("CVE ID"),
                    "cwe": row.get("CWE ID"), "label": int(row.get("vul", 0)),
                    "split": "cross-project test", "source_ext": row.get("ext"),
                })
                for node_index, node in enumerate(graph.get("nodes", [])):
                    node["id"] = node_index
                    node["label"] = node.get("type", "NODE")
                relation_names = graph.get("edge_types", [])
                graph["edges"] = [
                    {"src": edge[0], "dst": edge[1],
                     "type": relation_names[edge[2]] if len(edge) > 2
                     and isinstance(edge[2], int) and 0 <= edge[2] < len(relation_names)
                     else "OTHER"}
                    for edge in graph.get("edges", [])
                    if isinstance(edge, list) and len(edge) >= 2
                ]
                found[uid] = graph
                if len(found) == len(wanted):
                    break
    except (OSError, json.JSONDecodeError):
        return {}
    return found


class Handler(SimpleHTTPRequestHandler):
    server_version = "VulnGNNResearch/1.0"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def send_json(self, data: object, status: int = 200) -> None:
        payload = json.dumps(json_safe(data), ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        path = unquote(urlsplit(self.path).path)
        if path == "/api/health":
            self.send_json({"ok": True, "service": "research-ui",
                            "inference_available": active_checkpoint() is not None,
                            "graph_workset": graph_status()})
            return
        if path == "/api/analysis/status":
            checkpoints = available_gnn_checkpoints()
            checkpoint = active_checkpoint()
            graphs = graph_status()
            available = checkpoint is not None and FEATURE_ROOT.joinpath("metadata.json").is_file()
            self.send_json({
                "available": available,
                "status": "ready" if available else "pending",
                "checkpoint_available": bool(checkpoints),
                "checkpoints": checkpoints,
                "active_checkpoint": (str(checkpoint.relative_to(ROOT)).replace("\\", "/")
                                      if checkpoint else None),
                "feature_variant": "joern_type_only" if available else None,
                "graph_workset": graphs,
                "message": ("A preliminary node-type-only R-GCN checkpoint is ready for local inference. "
                            "Scores are uncalibrated research outputs; CodeBERT features remain pending."
                            if available else
                            "Graph extraction and type-only features are ready; R-GCN training and "
                            "model-backed inference are pending. CodeBERT is blocked by Windows App Control."),
            })
            return
        if path == "/api/research/baselines":
            self.send_json({"results": read_csv(BASELINES), "source": "results/baselines_v2.csv"})
            return
        if path == "/api/research/gnn":
            self.send_json({"results": gnn_test_metrics(), "source": "results/gnn/*/metrics_seed*.json"})
            return
        if path == "/api/research/projects":
            projects = read_csv(PROJECTS)
            eligible = [row for row in projects if int(row.get("positives", 0) or 0) >= 30]
            self.send_json({"results": eligible, "source": "results/per_project_baselines_v2.csv",
                            "minimum_vulnerable_test_functions": 30})
            return
        if path == "/api/graphs":
            graphs = demo_graphs()
            rows = [{key: graph.get(key) for key in
                     ("uid", "project", "method", "label", "cve", "cwe", "split")}
                    | {"nodes": len(graph.get("nodes", [])),
                       "edges": len(graph.get("edges", []))}
                    for graph in graphs.values()]
            self.send_json({"results": rows, "kind": "cross-project test examples",
                            "count": len(rows), "total_graphs": graph_status()["successful_graphs"]})
            return
        if path.startswith("/api/graphs/"):
            uid = path.rsplit("/", 1)[-1]
            if not GRAPH_ID.fullmatch(uid):
                self.send_json({"error": "Invalid graph identifier."}, 400)
                return
            graph = demo_graphs().get(uid)
            if graph is None:
                self.send_json({"error": "Graph is not in the demo sample."}, 404)
                return
            ext = graph.get("source_ext", "")
            source_file = f"{uid}{ext}"
            if ext not in {".c", ".h", ".cc", ".cpp", ".cxx", ".hpp"}:
                graph["source"] = None
            else:
                source_path = WORKSET / "batches" / "batch_00000" / "src" / source_file
                graph["source"] = source_path.read_text(encoding="utf-8", errors="replace") \
                    if source_path.is_file() else None
            self.send_json({"graph": graph,
                            "kind": "cross-project test example with dataset label; not a model prediction"})
            return
        if path.startswith("/research-figures/"):
            name = path.rsplit("/", 1)[-1]
            if name not in FIGURE_NAMES:
                self.send_error(404)
                return
            self.path = "/" + name
            self.directory = str(FIGURES)
        elif path.startswith("/api/"):
            self.send_json({"error": "API route not found."}, 404)
            return
        elif path != "/" and not Path(path.lstrip("/")).suffix:
            # Preserve the requested URL so the client router can select its route.
            payload = (WEB / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        elif path == "/":
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        if path == "/api/analysis":
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 150_000:
                self.send_json({"error": "Request must contain at most 64 KiB of source code."}, 413)
                return
            try:
                request = json.loads(self.rfile.read(length))
            except (json.JSONDecodeError, UnicodeDecodeError):
                self.send_json({"error": "Request body must be valid JSON."}, 400)
                return
            code = request.get("code") if isinstance(request, dict) else None
            filename = request.get("filename", "input.c") if isinstance(request, dict) else "input.c"
            extension = Path(str(filename)).suffix.lower()
            if not isinstance(code, str) or not code.strip() or len(code.encode("utf-8")) > 65_536:
                self.send_json({"error": "Provide nonempty C/C++ source code up to 64 KiB."}, 400)
                return
            if extension not in {".c", ".h", ".cc", ".cpp", ".cxx", ".hpp"}:
                self.send_json({"error": "Use a supported C/C++ filename extension."}, 400)
                return
            predictor = graph_predictor()
            if predictor is None:
                self.send_json({"error": "No compatible trained R-GCN checkpoint is available.",
                                "status": "pending"}, 503)
                return
            started = time.perf_counter()
            try:
                graph = graph_from_source(code, extension)
                result = predictor.predict(graph)
            except ValueError as error:
                self.send_json({"error": str(error)}, 422)
                return
            except subprocess.TimeoutExpired:
                self.send_json({"error": "Joern parsing timed out; try a smaller single-function file."}, 504)
                return
            except (OSError, subprocess.CalledProcessError, RuntimeError) as error:
                self.send_json({"error": f"Local graph extraction or inference failed: {error}"}, 500)
                return
            result["method"] = graph.get("method", "")
            result["elapsed_seconds"] = round(time.perf_counter() - started, 3)
            self.send_json({"result": result})
            return
        self.send_json({"error": "POST route not found."}, 404)

    def log_message(self, fmt: str, *args) -> None:
        print("[%s] %s" % (self.log_date_time_string(), fmt % args))


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if not WEB.is_dir():
        raise SystemExit(f"Missing web assets at {WEB}")
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"VulnGNN website: http://{args.host}:{args.port}")
    print(f"Inference API: {'ready' if active_checkpoint() else 'pending'}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping web server")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
