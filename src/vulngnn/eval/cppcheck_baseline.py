"""Per-function Cppcheck baseline for the fixed BigVul test splits.

Each snippet is scanned in its own process so a bad translation unit cannot
hold up the rest of the split. Completed rows are cached in JSONL and checked
against source hashes before reuse.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd

from vulngnn.eval.metrics import prf_at

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "data/processed/bigvul_clean.parquet"
OUT = ROOT / "results/cppcheck"
SPLITS = {"within": "split_within", "cross": "split_cross"}
CPP_HINT = re.compile(r"\w::\w|\bclass\s+\w|\btemplate\s*<|\bnamespace\b|\bnullptr\b")
TIMEOUT_SECONDS = 2.0
SAMPLE_SEED = 42


def source_ext(code: str, lang: str) -> str:
    return ".cpp" if lang in ("CPP", "C++") or CPP_HINT.search(code) else ".c"


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_cache(path: Path) -> dict[str, dict]:
    cache = {}
    if not path.exists():
        return cache
    with path.open() as stream:
        for line in stream:
            try:
                item = json.loads(line)
                if item.get("uid") and item.get("source_sha256"):
                    cache[item["uid"]] = item
            except json.JSONDecodeError:
                # Ignore a partial final record after an interrupted write.
                continue
    return cache


def cppcheck_one(binary: str, code: str, ext: str, timeout: float) -> dict:
    with tempfile.TemporaryDirectory(prefix="vulngnn-cppcheck-") as tmp:
        source = Path(tmp) / f"snippet{ext}"
        source.write_text(code.rstrip() + "\n")
        cmd = [binary, "--quiet", "--enable=warning", "--xml", "--xml-version=2",
               "--error-exitcode=2", str(source)]
        started = time.perf_counter()
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            return {"status": "timeout", "flag": 0,
                    "elapsed_seconds": timeout, "findings": [], "message": "timeout"}
        elapsed = time.perf_counter() - started
        xml_text = proc.stderr or ""
        findings = []
        parse_failure = False
        try:
            root = ET.fromstring(xml_text)
            for item in root.findall(".//error"):
                severity = item.attrib.get("severity", "")
                error_id = item.attrib.get("id", "")
                findings.append({"id": error_id, "severity": severity,
                                 "message": item.attrib.get("msg", "")})
                if severity == "error" and error_id.lower() in {
                        "syntaxerror", "syntaxerror:<", "internalerror"}:
                    parse_failure = True
        except ET.ParseError:
            root = None
        flag = int(any(f["severity"] in {"warning", "error"} for f in findings))
        if parse_failure or root is None:
            status = "parse_failure"
        elif proc.returncode < 0 or proc.returncode > 2 or proc.returncode == 1:
            status = "crash"
        elif root is None and proc.returncode not in (0, 2):
            status = "parse_failure"
        else:
            status = "ok"
        return {"status": status, "flag": flag, "elapsed_seconds": elapsed,
                "findings": findings, "returncode": proc.returncode,
                "message": "" if root is not None else xml_text[:1000]}


def test_rows(data: pd.DataFrame, split: str) -> pd.DataFrame:
    rows = data[data[SPLITS[split]].eq("test")].copy()
    if split == "cross":
        rows = rows[~rows["near_dup_cross"].astype(bool)].copy()
    rows["uid"] = "f_" + rows["norm_hash"].astype(str)
    rows["ext"] = [source_ext(code, lang)
                   for code, lang in zip(rows["func_before"], rows["lang"])]
    if rows["uid"].duplicated().any():
        raise ValueError(f"{split}: duplicate test UIDs")
    return rows.reset_index(drop=True)


def summarize(split: str, rows: pd.DataFrame) -> dict:
    y = rows["vul"].to_numpy(dtype=int)
    scores = rows["flag"].to_numpy(dtype=float)
    precision, recall, f1 = prf_at(y, scores, 0.5)
    return {"split": split, "model": "cppcheck", "variant": "warning_or_error",
            "n": len(rows), "positives": int(y.sum()),
            "prevalence": float(y.mean()), "precision": precision,
            "recall": recall, "f1": f1,
            "scanned_files": int(rows["status"].isin(["ok", "parse_failure"]).sum()),
            "timeout_files": int(rows["status"].eq("timeout").sum()),
            "crashed_files": int(rows["status"].eq("crash").sum()),
            "parse_failure_files": int(rows["status"].eq("parse_failure").sum()),
            "flagged_files": int(scores.sum())}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DATA)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--binary", default="cppcheck")
    parser.add_argument("--timeout", type=float, default=TIMEOUT_SECONDS)
    parser.add_argument("--sample-per-cell", type=int, default=0,
                        help="pilot only: sample this many rows per split x label x extension")
    parser.add_argument("--seed", type=int, default=SAMPLE_SEED)
    args = parser.parse_args()
    if args.timeout <= 0 or args.sample_per_cell < 0:
        parser.error("timeout must be positive and sample-per-cell nonnegative")

    version = subprocess.run([args.binary, "--version"], capture_output=True,
                             text=True, check=True).stdout.strip()
    version_hash = hashlib.sha256(version.encode()).hexdigest()[:12]
    run_tag = (f"pilot{args.sample_per_cell}_seed{args.seed}" if args.sample_per_cell
               else "full")
    run_dir = args.out / run_tag
    run_dir.mkdir(parents=True, exist_ok=True)
    print(f"Cppcheck: {version}; per-file timeout={args.timeout}s; "
          "operating point: any warning or error finding", flush=True)
    data = pd.read_parquet(args.data).reset_index(drop=True)
    summaries = []
    for split in SPLITS:
        rows = test_rows(data, split)
        if args.sample_per_cell:
            sampled = [group.sample(n=min(args.sample_per_cell, len(group)),
                                    random_state=args.seed)
                       for _, group in rows.groupby(["vul", "ext"], observed=True)]
            rows = pd.concat(sampled, ignore_index=True).sort_values("uid").reset_index(drop=True)
        cache_path = run_dir / f"{split}_records.jsonl"
        cache = load_cache(cache_path)
        records = []
        with cache_path.open("a") as stream:
            for row in rows.itertuples(index=False):
                source_hash = sha256(row.func_before)
                old = cache.get(row.uid)
                if old and old.get("source_sha256") == source_hash \
                        and old.get("timeout") == args.timeout \
                        and old.get("cppcheck_version") == version:
                    record = old
                else:
                    result = cppcheck_one(args.binary, row.func_before, row.ext, args.timeout)
                    record = {"uid": row.uid, "source_sha256": source_hash,
                              "cppcheck_version": version, "timeout": args.timeout,
                              "vul": int(row.vul), "project_g": str(row.project_g),
                              "group": str(row.group), "ext": row.ext, **result}
                    stream.write(json.dumps(record, separators=(",", ":")) + "\n")
                    stream.flush()
                records.append(record)
        pred = rows[["uid", "norm_hash", "project_g", "group", "vul", "ext"]].copy()
        record_by_uid = {item["uid"]: item for item in records}
        pred["status"] = pred["uid"].map(lambda uid: record_by_uid[uid]["status"])
        pred["flag"] = pred["uid"].map(lambda uid: int(record_by_uid[uid]["flag"]))
        pred["elapsed_seconds"] = pred["uid"].map(
            lambda uid: record_by_uid[uid]["elapsed_seconds"])
        pred["findings"] = pred["uid"].map(
            lambda uid: json.dumps(record_by_uid[uid]["findings"], separators=(",", ":")))
        pred.to_csv(run_dir / f"{split}_predictions.csv", index=False)
        summaries.append(summarize(split, pred))
        print(f"{split}: n={len(pred)} positives={int(pred.vul.sum())} "
              f"flags={int(pred.flag.sum())} statuses={pred.status.value_counts().to_dict()}",
              flush=True)

    pd.DataFrame(summaries).to_csv(run_dir / "metrics.csv", index=False)
    metadata = {"cppcheck_version": version, "cppcheck_version_hash": version_hash,
                "timeout_seconds": args.timeout, "seed": args.seed,
                "sample_per_cell": args.sample_per_cell,
                "operating_point": "flag if any finding severity is warning or error",
                "timeout_or_crash_rows_are_unflagged": True,
                "parse_error_findings_are_scored_by_severity": True,
                "source_extension_rule": "same C/C++ heuristic as frozen Semgrep baseline"}
    (run_dir / "run_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(pd.DataFrame(summaries).to_string(index=False), flush=True)
    print(f"Saved outputs to {run_dir}", flush=True)


if __name__ == "__main__":
    main()
