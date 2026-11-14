#!/usr/bin/env python3
"""Serve the VulnGNN research website and read-only local research APIs."""
from __future__ import annotations

import csv
import json
import math
import mimetypes
import re
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
BASELINES = ROOT / "results/baselines_v2.csv"
PROJECTS = ROOT / "results/per_project_baselines_v2.csv"
PILOT_GRAPHS = ROOT / "data/pilot/graphs"
PILOT_SOURCE = ROOT / "data/pilot/src"
FIGURES = ROOT / "results/figures"
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
            self.send_json({"ok": True, "service": "research-ui", "inference_available": False})
            return
        if path == "/api/analysis/status":
            self.send_json({
                "available": False,
                "status": "pending",
                "message": "No trained GNN checkpoint or inference API is available in this repository yet.",
            })
            return
        if path == "/api/research/baselines":
            self.send_json({"results": read_csv(BASELINES), "source": "results/baselines_v2.csv"})
            return
        if path == "/api/research/projects":
            projects = read_csv(PROJECTS)
            eligible = [row for row in projects if int(row.get("positives", 0) or 0) >= 30]
            self.send_json({"results": eligible, "source": "results/per_project_baselines_v2.csv",
                            "minimum_vulnerable_test_functions": 30})
            return
        if path == "/api/graphs":
            rows = []
            for graph_path in sorted(PILOT_GRAPHS.glob("f_*.json")):
                try:
                    graph = json.loads(graph_path.read_text(encoding="utf-8"))
                    rows.append({key: graph.get(key) for key in
                                 ("uid", "project", "method", "label", "cve", "cwe")}
                                | {"nodes": len(graph.get("nodes", [])),
                                   "edges": len(graph.get("edges", []))})
                except (OSError, json.JSONDecodeError):
                    continue
            self.send_json({"results": rows, "kind": "Joern pilot graphs", "count": len(rows)})
            return
        if path.startswith("/api/graphs/"):
            uid = path.rsplit("/", 1)[-1]
            if not GRAPH_ID.fullmatch(uid):
                self.send_json({"error": "Invalid graph identifier."}, 400)
                return
            graph_path = PILOT_GRAPHS / f"{uid}.json"
            if not graph_path.is_file():
                self.send_json({"error": "Pilot graph not found."}, 404)
                return
            try:
                graph = json.loads(graph_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                self.send_json({"error": "Pilot graph could not be read."}, 500)
                return
            source_file = str(graph.get("source_file", ""))
            if Path(source_file).name != source_file or not source_file.startswith(uid + "."):
                graph["source"] = None
            else:
                source_path = PILOT_SOURCE / source_file
                graph["source"] = source_path.read_text(encoding="utf-8", errors="replace") \
                    if source_path.is_file() else None
            self.send_json({"graph": graph, "kind": "Joern pilot graph; not a model prediction"})
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
            self.send_json({
                "error": "Analysis is unavailable: this repository has no trained GNN checkpoint or inference service.",
                "status": "pending",
            }, 503)
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
    print("Inference API: pending (no trained checkpoint/API is present)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping web server")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
