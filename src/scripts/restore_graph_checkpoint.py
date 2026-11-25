"""Verify and restore a versioned Kaggle graph checkpoint archive."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tarfile
from pathlib import Path, PurePosixPath


def sha256_stream(stream) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return sha256_stream(stream)


def verify_checkpoint(archive_path: Path, workset: Path) -> tuple[tarfile.TarFile, dict]:
    sidecar = archive_path.with_name(archive_path.name + ".sha256")
    if not sidecar.is_file():
        raise FileNotFoundError(f"Missing archive checksum sidecar: {sidecar}")
    expected_archive_hash = sidecar.read_text().split()[0]
    if sha256_file(archive_path) != expected_archive_hash:
        raise ValueError("Checkpoint archive SHA-256 does not match its sidecar")

    tar = tarfile.open(archive_path, "r:gz")
    members = tar.getmembers()
    by_name = {member.name: member for member in members}
    if len(by_name) != len(members):
        tar.close()
        raise ValueError("Checkpoint contains duplicate member paths")
    for member in members:
        path = PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts or not member.isfile():
            tar.close()
            raise ValueError(f"Unsafe checkpoint member: {member.name}")
    required = {"manifest.csv", "workset_metadata.json", "checkpoint_manifest.json"}
    if not required.issubset(by_name):
        tar.close()
        raise ValueError(f"Checkpoint missing members: {sorted(required - set(by_name))}")
    manifest_bytes = tar.extractfile(by_name["checkpoint_manifest.json"]).read()
    manifest = json.loads(manifest_bytes)
    if manifest.get("schema_version") != 1:
        tar.close()
        raise ValueError("Unsupported checkpoint manifest schema")
    if manifest.get("workset_manifest_sha256") != sha256_file(workset / "manifest.csv"):
        tar.close()
        raise ValueError("Checkpoint was made for a different workset manifest")
    metadata_path = workset / "workset_metadata.json"
    if not metadata_path.is_file():
        tar.close()
        raise FileNotFoundError(f"Missing workset metadata required for restore: {metadata_path}")
    if manifest.get("workset_metadata_sha256") != sha256_file(metadata_path):
        tar.close()
        raise ValueError("Checkpoint was made for different workset metadata")
    coverage_path = workset / "coverage_by_project.csv"
    if coverage_path.is_file() and "coverage_by_project.csv" in manifest.get("files", {}):
        if manifest["files"]["coverage_by_project.csv"]["sha256"] != sha256_file(coverage_path):
            tar.close()
            raise ValueError("Checkpoint was made for different project coverage metadata")

    expected_files = manifest.get("files", {})
    if "manifest.csv" not in expected_files or "workset_metadata.json" not in expected_files:
        tar.close()
        raise ValueError("Checkpoint integrity manifest does not cover workset identity files")
    for name, details in expected_files.items():
        member = by_name.get(name)
        if member is None or member.size != details.get("size"):
            tar.close()
            raise ValueError(f"Checkpoint member missing or size mismatch: {name}")
        stream = tar.extractfile(member)
        if sha256_stream(stream) != details.get("sha256"):
            tar.close()
            raise ValueError(f"Checkpoint member checksum mismatch: {name}")
    if set(expected_files) != set(by_name) - {"checkpoint_manifest.json"}:
        tar.close()
        raise ValueError("Checkpoint has untracked or unlisted members")
    return tar, manifest


def restore_checkpoint(archive_path: Path, workset: Path) -> None:
    tar, manifest = verify_checkpoint(archive_path, workset)
    try:
        # A Kaggle session can contain outputs from a different or newer
        # checkpoint. Never leave those batch files beside the restored state:
        # the runner could otherwise consider them for resume.
        graph_dir = workset / "graphs"
        conflicts = []
        if graph_dir.is_dir():
            for existing in graph_dir.glob("batch_*"):
                if not existing.is_file() or not re.fullmatch(
                        r"batch_\d{5}(?:\.jsonl|_stats\.csv|\.complete\.json)",
                        existing.name):
                    continue
                relative = existing.relative_to(workset).as_posix()
                expected = manifest["files"].get(relative)
                if (expected is None or existing.stat().st_size != expected["size"] or
                        sha256_file(existing) != expected["sha256"]):
                    conflicts.append(relative)
        if conflicts:
            raise ValueError(
                "Workset contains batch outputs that conflict with this checkpoint: "
                + ", ".join(sorted(conflicts))
                + "; restore into a fresh workset or remove the conflicting batch files"
            )
        for name in manifest["files"]:
            if name in {"manifest.csv", "workset_metadata.json", "coverage_by_project.csv"}:
                continue
            member = tar.getmember(name)
            destination = workset / Path(*PurePosixPath(name).parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name(destination.name + ".restore.partial")
            with tar.extractfile(member) as source, temporary.open("wb") as target:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    target.write(chunk)
            os.replace(temporary, destination)
    finally:
        tar.close()
    print(f"Verified and restored {len(manifest['files']) - 3} checkpoint files from {archive_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--workset", type=Path, required=True,
                        help="prepared workset with the unchanged manifest and metadata")
    parser.add_argument("--verify-only", action="store_true",
                        help="verify the archive without restoring files")
    args = parser.parse_args()
    tar, manifest = verify_checkpoint(args.archive, args.workset)
    tar.close()
    print(f"Checkpoint verified: {len(manifest['files'])} files; workset identity matches")
    if not args.verify_only:
        restore_checkpoint(args.archive, args.workset)


if __name__ == "__main__":
    main()
