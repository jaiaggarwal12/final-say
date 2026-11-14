"""Prepare, extract, audit, and optionally bundle the full Joern graph workset.

This is the single entry point for a Kaggle run. It delegates selection and
extraction to the project modules so their settings remain explicit and
reproducible. A limited run is useful for a smoke check; only a complete run
can pass the default full-workset audit.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], *, env: dict[str, str] | None = None) -> None:
    print("$ " + " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, env=env, check=True)


def make_archive(workset: Path, destination: Path) -> None:
    """Bundle only compact graph outputs and audit metadata for download."""
    members = [workset / "manifest.csv", workset / "coverage_by_project.csv"]
    graph_dir = workset / "graphs"
    members.extend(sorted(graph_dir.glob("*.jsonl")))
    members.extend(sorted(graph_dir.glob("*_stats.csv")))
    members.extend(path for path in (
        graph_dir / "coverage.csv",
        graph_dir / "coverage_by_project.csv",
        graph_dir / "audit_coverage_by_project.csv",
        graph_dir / "audit_summary.json",
    ) if path.exists())
    missing = [str(path) for path in members if not path.is_file()]
    if missing:
        raise FileNotFoundError("Cannot archive; required outputs are missing: " + ", ".join(missing))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(destination, "w:gz") as archive:
        for path in members:
            archive.add(path, arcname=path.relative_to(workset))
    print(f"Graph bundle: {destination} ({destination.stat().st_size:,} bytes)", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "data/processed/bigvul_clean.parquet")
    parser.add_argument("--workset", type=Path, default=ROOT / "data/graph_workset")
    parser.add_argument("--joern-dir", type=Path, default=ROOT / "tools/joern/joern-cli")
    parser.add_argument("--java-home", type=Path, default=None)
    parser.add_argument("--negative-ratio", type=float, default=5.0)
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--max-nodes", type=int, default=500)
    parser.add_argument("--limit-batches", type=int, default=None,
                        help="run only the first N batches; audits as a partial run")
    parser.add_argument("--no-resume", action="store_true",
                        help="rerun batches even when complete outputs already exist")
    parser.add_argument("--archive", type=Path, default=None,
                        help="optional .tar.gz destination containing compact outputs")
    args = parser.parse_args()

    if not args.data.is_file():
        parser.error(f"Processed BigVul parquet not found: {args.data}")
    if args.negative_ratio < 0 or args.batch_size < 1 or args.max_nodes < 1:
        parser.error("negative ratio must be nonnegative; batch size and node cap must be positive")
    if args.limit_batches is not None and args.limit_batches < 1:
        parser.error("--limit-batches must be positive")

    joern_dir = args.joern_dir.resolve()
    missing_tools = [name for name in ("joern-parse", "joern-export")
                     if not (joern_dir / name).is_file()]
    if missing_tools:
        parser.error(f"Joern executables missing under {joern_dir}: {', '.join(missing_tools)}")

    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    if args.java_home:
        java_home = args.java_home.resolve()
        if not (java_home / "bin/java").is_file():
            parser.error(f"Java executable not found under {java_home}")
        env["JAVA_HOME"] = str(java_home)
        env["PATH"] = str(java_home / "bin") + os.pathsep + env.get("PATH", "")
    java_executable = (Path(env["JAVA_HOME"]) / "bin/java" if env.get("JAVA_HOME")
                       else Path(shutil.which("java") or ""))
    if not java_executable.is_file():
        parser.error("Java 21 not found; set JAVA_HOME or pass --java-home")
    java_result = subprocess.run([str(java_executable), "-version"],
                                 capture_output=True, text=True, check=False)
    java_version = re.search(r'version "(?:1\.)?(\d+)',
                              java_result.stdout + java_result.stderr)
    if java_result.returncode != 0 or not java_version or java_version.group(1) != "21":
        found = java_version.group(1) if java_version else "unknown"
        parser.error(f"Joern requires Java 21; found Java {found}")

    manifest = args.workset / "manifest.csv"
    if not manifest.exists():
        command = [sys.executable, "-m", "vulngnn.graphs.prepare_graph_workset",
                   "--data", str(args.data.resolve()), "--out", str(args.workset.resolve()),
                   "--negative-ratio", str(args.negative_ratio),
                   "--batch-size", str(args.batch_size)]
        run(command, env=env)
    else:
        print(f"Reusing existing workset manifest: {manifest}", flush=True)

    command = [sys.executable, "-m", "vulngnn.graphs.run_cpg_batches",
               "--workset", str(args.workset.resolve()),
               "--joern-dir", str(joern_dir), "--max-nodes", str(args.max_nodes)]
    if args.java_home:
        command.extend(["--java-home", str(args.java_home.resolve())])
    if args.limit_batches is not None:
        command.extend(["--limit-batches", str(args.limit_batches)])
    if not args.no_resume:
        command.append("--resume")
    run(command, env=env)

    audit = [sys.executable, "-m", "vulngnn.graphs.audit_cpg_outputs",
             "--workset", str(args.workset.resolve())]
    if args.limit_batches is not None:
        audit.append("--allow-partial")
    run(audit, env=env)

    if args.archive:
        make_archive(args.workset.resolve(), args.archive.resolve())


if __name__ == "__main__":
    main()
