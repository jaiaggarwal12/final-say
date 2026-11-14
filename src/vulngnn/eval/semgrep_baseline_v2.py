"""Batched, resumable Semgrep baseline for BigVul test functions.

Scratch source files are written under the system temporary directory. This
runner only reads the protected data tree and stores durable outputs in results/.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import certifi
import pandas as pd
import yaml

from vulngnn.eval.metrics import prf_at

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "data/processed/bigvul_clean.parquet"
RULES = ROOT / "configs/semgrep_c.yml"
OUT = ROOT / "results/semgrep_v2"
SPLITS = {"within": "split_within", "cross": "split_cross"}
CPP_HINT = re.compile(r"\w::\w|\bclass\s+\w|\btemplate\s*<|\bnamespace\b|\bnullptr\b")
UID_RE = re.compile(r"f_[0-9a-f]{12,64}")
BATCH_SIZE = 1000
FILE_TIMEOUT_SECONDS = 2
FILE_TIMEOUT_THRESHOLD = 1
MAX_MEMORY_MIB = 512
BATCH_WALL_TIMEOUT_SECONDS = 300


def source_ext(code: str, lang: str) -> str:
    return ".cpp" if lang in ("CPP", "C++") or CPP_HINT.search(code) else ".c"


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def atomic_json(path: Path, value: object) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2) + "\n")
    tmp.replace(path)


def uid_from_text(value: object) -> set[str]:
    return set(UID_RE.findall(json.dumps(value, ensure_ascii=False)))


def empty_report() -> dict:
    return {"results": [], "errors": [], "scanned_uids": [], "crashed_uids": [],
            "batch_timeouts": [], "batch_failures": [], "stdout": [], "stderr": []}


def merge_reports(parts: list[dict]) -> dict:
    merged = empty_report()
    for part in parts:
        for key in ("results", "errors", "scanned_uids", "crashed_uids",
                    "batch_timeouts", "batch_failures", "stdout", "stderr"):
            merged[key].extend(part.get(key, []))
    for key in ("scanned_uids", "crashed_uids", "batch_timeouts"):
        merged[key] = sorted(set(merged[key]))
    return merged


def invoke_semgrep(rows: pd.DataFrame, configs: list[Path], semgrep: str,
                   env: dict[str, str], log_tag: str) -> dict:
    """Run one bounded batch and fail fast if the CLI process fails."""
    with tempfile.TemporaryDirectory(prefix="vulngnn-semgrep-") as scratch:
        scratch_path = Path(scratch)
        source = scratch_path / "src"
        source.mkdir()
        for row in rows.itertuples(index=False):
            ext = source_ext(row.func_before, row.lang)
            (source / f"{row.uid}{ext}").write_text(row.func_before.rstrip() + "\n")
        output = scratch_path / "report.json"
        cmd = [semgrep, "scan"]
        for config in configs:
            cmd.extend(["--config", str(config)])
        cmd.extend([
            "--metrics=off", "--disable-version-check", "--no-git-ignore",
            "--json", "--output", str(output),
            f"--timeout={FILE_TIMEOUT_SECONDS}",
            f"--timeout-threshold={FILE_TIMEOUT_THRESHOLD}",
            f"--max-memory={MAX_MEMORY_MIB}", "--jobs=1", str(source),
        ])
        try:
            proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True,
                                  env=env, timeout=BATCH_WALL_TIMEOUT_SECONDS)
            stdout, stderr = proc.stdout, proc.stderr
            if proc.returncode == 0 and output.exists():
                report = json.loads(output.read_text())
                scanned = set()
                for p in report.get("paths", {}).get("scanned", []):
                    scanned.update(uid_from_text(p))
                return {
                    "results": report.get("results", []),
                    "errors": report.get("errors", []),
                    "scanned_uids": sorted(scanned), "crashed_uids": [],
                    "batch_timeouts": [], "batch_failures": [],
                    "stdout": [stdout] if stdout else [],
                    "stderr": [stderr] if stderr else [],
                }
            failure = {"tag": log_tag, "uids": rows["uid"].astype(str).tolist(),
                       "returncode": proc.returncode,
                       "stdout": stdout[-4000:], "stderr": stderr[-4000:]}
        except subprocess.TimeoutExpired as exc:
            failure = {"tag": log_tag, "uids": rows["uid"].astype(str).tolist(),
                       "returncode": None,
                       "stdout": str(exc.stdout or "")[-4000:],
                       "stderr": str(exc.stderr or "")[-4000:],
                       "reason": "batch_wall_timeout"}

    failure_path = OUT / "batch_failures.jsonl"
    with failure_path.open("a") as stream:
        stream.write(json.dumps(failure) + "\n")
    print(f"Semgrep batch attempt failed: {failure['tag']}; "
          f"reason={failure.get('reason', 'nonzero_exit')}; "
          f"returncode={failure.get('returncode')}\n{failure.get('stderr', '')[-1200:]}",
          flush=True)
    raise RuntimeError(
        f"Semgrep batch {log_tag} failed. Completed batch JSON remains resumable; "
        "diagnose the saved failure before retrying with changed settings."
    )


def valid_cached(path: Path, fingerprint: str) -> dict | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return payload if payload.get("fingerprint") == fingerprint and payload.get("complete") else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=tuple(SPLITS), action="append",
                        help="run only this split; repeatable")
    parser.add_argument("--limit-batches", type=int,
                        help="process only the first N batches per selected split")
    args = parser.parse_args()
    if args.limit_batches is not None and args.limit_batches < 1:
        parser.error("--limit-batches must be positive")
    semgrep = shutil.which("semgrep")
    if semgrep is None:
        raise SystemExit("Semgrep is missing from PATH. Install the pinned package in the project venv.")
    try:
        version = importlib.metadata.version("semgrep")
    except importlib.metadata.PackageNotFoundError as exc:
        raise SystemExit("Semgrep CLI is present, but the project venv package version is unknown") from exc
    if not DATA.exists() or not RULES.exists():
        raise SystemExit(f"Missing required input: {DATA if not DATA.exists() else RULES}")

    rules_payload = yaml.safe_load(RULES.read_text())
    rules = rules_payload.get("rules", [])
    cpp_rules = []
    for rule in rules:
        if "c" not in rule.get("languages", []):
            continue
        clone = json.loads(json.dumps(rule))
        clone["id"] = f"{rule['id']}.cpp"
        clone["languages"] = ["cpp"]
        clone.setdefault("metadata", {})["derived_from"] = rule["id"]
        cpp_rules.append(clone)

    OUT.mkdir(parents=True, exist_ok=True)
    state = OUT / "state"
    state.mkdir(parents=True, exist_ok=True)
    overlay = state / "semgrep_cpp_overlay.yml"
    overlay.write_text(yaml.safe_dump({"rules": cpp_rules}, sort_keys=False))
    configs = [RULES, overlay]
    rule_ids = {r["id"]: r for r in rules + cpp_rules}
    env = os.environ.copy()
    env["SSL_CERT_FILE"] = certifi.where()
    env["SEMGREP_LOG_FILE"] = str(state / "semgrep.log")
    env["SEMGREP_SETTINGS_FILE"] = str(state / "settings.yml")
    env["SEMGREP_VERSION_CACHE_PATH"] = str(state / "version-cache")
    env["SEMGREP_ENABLE_VERSION_CHECK"] = "0"
    env["SEMGREP_VERSION"] = version
    rules_hash = sha256_bytes(RULES.read_bytes())
    print(f"Semgrep version: {version}", flush=True)
    print(f"Rule source: frozen local p/c snapshot ({RULES.relative_to(ROOT)}; "
          f"SHA-256 {rules_hash}); derived C++ rules: {len(cpp_rules)}", flush=True)
    print(f"Operating points: any finding; security category or WARNING/ERROR. "
          f"Batch={BATCH_SIZE}, per-rule timeout={FILE_TIMEOUT_SECONDS}s, "
          f"max-memory={MAX_MEMORY_MIB}MiB, jobs=1", flush=True)

    data = pd.read_parquet(DATA).reset_index(drop=True)
    data["near_dup_cross"] = data["near_dup_cross"].astype(bool)
    summary_rows, prediction_frames, batch_rows = [], [], []
    selected_splits = args.split or list(SPLITS)
    for split in selected_splits:
        split_col = SPLITS[split]
        test = data[data[split_col].eq("test")].copy()
        if split == "cross":
            test = test[~test["near_dup_cross"]].copy()
        test["uid"] = "f_" + test["norm_hash"].astype(str)
        test = test.reset_index(drop=True)
        if test["uid"].duplicated().any():
            raise ValueError(f"{split}: duplicate function IDs in test rows")
        all_parts = []
        split_cache = OUT / "batches" / split
        split_cache.mkdir(parents=True, exist_ok=True)
        total_batches = (len(test) + BATCH_SIZE - 1) // BATCH_SIZE
        batch_count = min(total_batches, args.limit_batches or total_batches)
        for start in range(0, batch_count * BATCH_SIZE, BATCH_SIZE):
            batch = test.iloc[start:start + BATCH_SIZE].copy()
            batch_id = start // BATCH_SIZE
            content_keys = [
                f"{row.uid}:{sha256_bytes(row.func_before.encode('utf-8'))}"
                for row in batch.itertuples(index=False)
            ]
            fingerprint_source = "\n".join([
                version,
                sha256_bytes(RULES.read_bytes()),
                sha256_bytes(overlay.read_bytes()),
                str(FILE_TIMEOUT_SECONDS), str(FILE_TIMEOUT_THRESHOLD),
                str(MAX_MEMORY_MIB), str(BATCH_SIZE), *content_keys,
            ])
            fingerprint = sha256_bytes(fingerprint_source.encode())
            cache_path = split_cache / f"batch-{batch_id:04d}.json"
            cached = valid_cached(cache_path, fingerprint)
            if cached is None:
                part = invoke_semgrep(batch, configs, semgrep, env, f"{split}:{batch_id}")
                cached = {"complete": True, "fingerprint": fingerprint, **part}
                atomic_json(cache_path, cached)
            else:
                print(f"{split}: resume batch {batch_id + 1} from saved JSON", flush=True)
            all_parts.append(cached)
            batch_rows.append({"split": split, "batch": batch_id, "n": len(batch),
                               "fingerprint": fingerprint,
                               "crashed_files": len(cached.get("crashed_uids", [])),
                               "timed_out_files": len(cached.get("batch_timeouts", [])),
                               "batch_failures": len(cached.get("batch_failures", []))})
            print(f"{split}: batch {batch_id + 1}/{batch_count} "
                  f"processed ({len(batch)} functions)", flush=True)

        merged = merge_reports(all_parts)
        scanned = set(merged["scanned_uids"])
        crashed = set(merged["crashed_uids"])
        timed_out = set(merged["batch_timeouts"])
        parse_errors = set()
        for err in merged["errors"]:
            matched = uid_from_text(err)
            error_type = err.get("type", "")
            if isinstance(error_type, list) and error_type:
                error_type = error_type[0]
            if "timeout" in str(error_type).lower():
                timed_out.update(matched)
            else:
                parse_errors.update(matched)

        result_uids: dict[str, list[dict]] = {}
        for finding in merged["results"]:
            matched = uid_from_text(finding.get("path", ""))
            for uid in matched:
                result_uids.setdefault(uid, []).append(finding)
        pred = test[["uid", "norm_hash", "project_g", "group", "vul"]].copy()
        pred = pred.rename(columns={"vul": "y"})
        pred["scanned"] = pred["uid"].isin(scanned)
        pred["parse_error"] = pred["uid"].isin(parse_errors)
        pred["timeout"] = pred["uid"].isin(timed_out)
        pred["crash"] = pred["uid"].isin(crashed)
        pred["any_finding"] = pred["uid"].map(lambda uid: int(uid in result_uids))
        pred["security_severity_finding"] = pred["uid"].map(
            lambda uid: int(any(
                rule_ids.get(item.get("check_id", ""), {}).get("metadata", {}).get("category") == "security"
                or item.get("extra", {}).get("severity") in {"WARNING", "ERROR"}
                for item in result_uids.get(uid, []))))
        pred.to_csv(OUT / f"{split}_predictions.csv", index=False)
        prediction_frames.append(pred.assign(split=split))

        clusters = pred["project_g" if split == "cross" else "group"].astype(str).to_numpy()
        y = pred["y"].to_numpy(dtype=int)
        for variant, score_col in (("semgrep_any_finding", "any_finding"),
                                   ("semgrep_security_severity", "security_severity_finding")):
            scores = pred[score_col].to_numpy(dtype=float)
            p, r, f = prf_at(y, scores, 0.5)
            # This row is retained as an operating point. AP and its interval
            # are filled by the shared baseline aggregation step.
            summary_rows.append({
                "split": split, "model": "semgrep", "variant": variant,
                "n": len(pred), "positives": int(y.sum()), "prevalence": float(y.mean()),
                "precision": p, "recall": r, "f1": f,
                "scanned_files": int(pred["scanned"].sum()),
                "parse_error_files": int(pred["parse_error"].sum()),
                "timeout_files": int(pred["timeout"].sum()),
                "crashed_files": int(pred["crash"].sum()),
                "unscanned_files": int((~pred["scanned"]).sum()),
            })
        print(f"{split}: {len(pred)} files; scanned={pred.scanned.sum()}; "
              f"parse_errors={pred.parse_error.sum()}; timeouts={pred.timeout.sum()}; "
              f"crashes={pred.crash.sum()}; findings={pred.any_finding.sum()}", flush=True)

    pd.DataFrame(batch_rows).to_csv(OUT / "batch_manifest.csv", index=False)
    pd.concat(prediction_frames, ignore_index=True).to_csv(OUT / "predictions.csv", index=False)
    pd.DataFrame(summary_rows).to_csv(OUT / "operating_points.csv", index=False)
    metadata = {
        "version": version, "rules_source": "frozen local snapshot of Semgrep p/c",
        "rules_path": str(RULES.relative_to(ROOT)),
        "rules_sha256": rules_hash,
        "rule_count": len(rules), "cpp_derived_rule_count": len(cpp_rules),
        "batch_size": BATCH_SIZE, "file_timeout_seconds_per_rule": FILE_TIMEOUT_SECONDS,
        "file_timeout_threshold": FILE_TIMEOUT_THRESHOLD, "max_memory_mib": MAX_MEMORY_MIB,
        "jobs": 1, "batch_wall_timeout_seconds": BATCH_WALL_TIMEOUT_SECONDS,
        "error_scoring": "keep every eligible function; if no finding is emitted, score it unflagged even when parser errors or rule timeouts are recorded",
        "selected_splits": selected_splits,
        "limit_batches": args.limit_batches,
        "complete": args.limit_batches is None and set(selected_splits) == set(SPLITS),
        "operating_points": summary_rows,
    }
    atomic_json(OUT / "run_metadata.json", metadata)
    print(f"saved {OUT.relative_to(ROOT)}", flush=True)


if __name__ == "__main__":
    main()
