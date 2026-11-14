"""Create a Kaggle-uploadable archive of the cleaned data and Joern CLI."""
from __future__ import annotations

import argparse
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path,
                        default=ROOT / "data/processed/bigvul_clean.parquet")
    parser.add_argument("--joern-dir", type=Path,
                        default=ROOT / "tools/joern/joern-cli")
    parser.add_argument("--output", type=Path,
                        default=Path("/private/tmp/gnn-vulnerability-kaggle-inputs.tar.gz"))
    parser.add_argument("--force", action="store_true",
                        help="replace an archive already at --output")
    args = parser.parse_args()

    data = args.data.resolve()
    joern = args.joern_dir.resolve()
    output = args.output.resolve()
    if not data.is_file():
        parser.error(f"Processed parquet not found: {data}")
    missing = [name for name in ("joern-parse", "joern-export")
               if not (joern / name).is_file()]
    if missing:
        parser.error(f"Joern executables missing under {joern}: {', '.join(missing)}")
    if output.exists() and not args.force:
        parser.error(f"Archive already exists: {output}; remove it or pass --force")
    if output == data or data in output.parents or output == joern or joern in output.parents:
        parser.error("Archive destination cannot be inside an input path")

    output.parent.mkdir(parents=True, exist_ok=True)
    print(f"Writing inputs archive: {output}", flush=True)
    with tarfile.open(output, mode="w:gz", compresslevel=1) as archive:
        archive.add(data, arcname="data/processed/bigvul_clean.parquet")
        archive.add(joern, arcname="tools/joern/joern-cli")
    print(f"Done: {output.stat().st_size:,} bytes", flush=True)
    print("Upload this archive as a private Kaggle Dataset, then extract it under /kaggle/working.")


if __name__ == "__main__":
    main()
