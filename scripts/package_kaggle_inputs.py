"""Create a Kaggle-uploadable archive with data, Joern CLI and graph runner."""
from __future__ import annotations

import argparse
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _source_filter(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
    """Keep source files only; avoid shipping local Python bytecode caches."""
    if "__pycache__" in Path(info.name).parts or info.name.endswith(".pyc"):
        return None
    return info


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path,
                        default=ROOT / "data/processed/bigvul_clean.parquet")
    parser.add_argument("--joern-dir", type=Path,
                        default=ROOT / "tools/joern/joern-cli")
    parser.add_argument("--source-dir", type=Path, default=ROOT / "src",
                        help="project Python source needed by the graph runner")
    parser.add_argument("--pipeline-script", type=Path,
                        default=ROOT / "scripts/run_graph_pipeline.py",
                        help="graph pipeline entry point to include")
    parser.add_argument("--output", type=Path,
                        default=Path("/private/tmp/gnn-vulnerability-kaggle-inputs.tar.gz"))
    parser.add_argument("--force", action="store_true",
                        help="replace an archive already at --output")
    args = parser.parse_args()

    data = args.data.resolve()
    joern = args.joern_dir.resolve()
    source = args.source_dir.resolve()
    pipeline_script = args.pipeline_script.resolve()
    output = args.output.resolve()
    if not data.is_file():
        parser.error(f"Processed parquet not found: {data}")
    missing = [name for name in ("joern-parse", "joern-export")
               if not (joern / name).is_file()]
    if missing:
        parser.error(f"Joern executables missing under {joern}: {', '.join(missing)}")
    if not source.is_dir():
        parser.error(f"Project source directory not found: {source}")
    if not pipeline_script.is_file():
        parser.error(f"Graph pipeline script not found: {pipeline_script}")
    if output.exists() and not args.force:
        parser.error(f"Archive already exists: {output}; remove it or pass --force")
    inputs = (data, joern, source, pipeline_script)
    if any(output == item or item in output.parents for item in inputs):
        parser.error("Archive destination cannot be inside an input path")

    output.parent.mkdir(parents=True, exist_ok=True)
    print(f"Writing inputs archive: {output}", flush=True)
    with tarfile.open(output, mode="w:gz", compresslevel=1) as archive:
        archive.add(data, arcname="data/processed/bigvul_clean.parquet")
        archive.add(joern, arcname="tools/joern/joern-cli")
        archive.add(source, arcname="src", filter=_source_filter)
        archive.add(pipeline_script, arcname="scripts/run_graph_pipeline.py")
    print(f"Done: {output.stat().st_size:,} bytes", flush=True)
    print("Archive includes processed data, Joern CLI, src/, and the graph pipeline entry point.")
    print("Upload this archive as a private Kaggle Dataset, then extract it under /kaggle/working.")


if __name__ == "__main__":
    main()
