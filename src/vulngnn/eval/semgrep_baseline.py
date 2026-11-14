"""Evaluate a frozen Semgrep C/C++ rule snapshot on BigVul test functions.

The rule snapshot is fetched once from Semgrep's ``p/c`` ruleset and committed
as ``configs/semgrep_c.yml``. The scan records its SHA-256 and Semgrep CLI
version so later runs can identify the exact detector configuration.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path

import pandas as pd
import certifi
import yaml

from vulngnn.eval.metrics import prf_at

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "data/processed/bigvul_clean.parquet"
RULES = ROOT / "configs/semgrep_c.yml"
OUT = ROOT / "results/semgrep"
WORK = ROOT / "data/semgrep"
RAW = WORK / "raw"
SOURCE_RULESET = "https://semgrep.dev/c/p/c"
SPLITS = {"within": "split_within", "cross": "split_cross"}
CPP_HINT = re.compile(r"\w::\w|\bclass\s+\w|\btemplate\s*<|\bnamespace\b|\bnullptr\b")


def source_ext(code: str, lang: str) -> str:
    return ".cpp" if lang in ("CPP", "C++") or CPP_HINT.search(code) else ".c"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run_scan(semgrep: str, configs: list[Path], source_dir: Path, json_path: Path,
             env: dict[str, str]) -> dict:
    cmd = [semgrep, "scan"]
    for config in configs:
        cmd.extend(["--config", str(config)])
    cmd.extend(["--metrics=off", "--disable-version-check", "--no-git-ignore",
           "--json", "--output", str(json_path), str(source_dir)]
    )
    proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, env=env)
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="")
    if proc.returncode != 0:
        raise RuntimeError(f"Semgrep failed ({proc.returncode}); see stderr above")
    with json_path.open() as stream:
        return json.load(stream)


def main() -> None:
    semgrep = shutil.which("semgrep")
    if semgrep is None:
        raise SystemExit("Semgrep is missing. Install the pinned version in the project venv.")
    if not DATA.exists():
        raise SystemExit(f"Missing processed dataset: {DATA}")
    if not RULES.exists():
        raise SystemExit(
            f"Missing frozen ruleset: {RULES}\n"
            f"Fetch it once with: curl -fsSL {SOURCE_RULESET} -o {RULES}"
        )

    rule_count = len(yaml.safe_load(RULES.read_text()).get("rules", []))
    df = pd.read_parquet(DATA).reset_index(drop=True)
    df["near_dup_cross"] = df["near_dup_cross"].astype(bool)
    OUT.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    state_dir = WORK / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    upstream_rules = yaml.safe_load(RULES.read_text())
    cpp_rules = []
    for rule in upstream_rules.get("rules", []):
        if "c" not in rule.get("languages", []):
            continue
        clone = deepcopy(rule)
        clone["id"] = f"{rule['id']}.cpp"
        clone["languages"] = ["cpp"]
        clone.setdefault("metadata", {})["derived_from"] = rule["id"]
        cpp_rules.append(clone)
    cpp_rule_path = state_dir / "semgrep_cpp_overlay.yml"
    cpp_rule_path.write_text(yaml.safe_dump({"rules": cpp_rules}, sort_keys=False))
    upstream_hash = sha256(RULES)
    cpp_overlay_hash = sha256(cpp_rule_path)
    effective_rules_hash = hashlib.sha256(
        (upstream_hash + "\0" + cpp_overlay_hash).encode("ascii")
    ).hexdigest()
    semgrep_env = os.environ.copy()
    semgrep_env["SSL_CERT_FILE"] = certifi.where()
    semgrep_env["SEMGREP_LOG_FILE"] = str(state_dir / "semgrep.log")
    semgrep_env["SEMGREP_SETTINGS_FILE"] = str(state_dir / "settings.yml")
    semgrep_env["SEMGREP_VERSION_CACHE_PATH"] = str(state_dir / "version-cache")
    semgrep_env["SEMGREP_ENABLE_VERSION_CHECK"] = "0"
    version = subprocess.run([semgrep, "--version"], check=True, text=True,
                             capture_output=True, env=semgrep_env).stdout.strip()
    rows = []

    for name, split_col in SPLITS.items():
        test = df[df[split_col] == "test"].copy()
        if name == "cross":
            test = test[~test["near_dup_cross"]].copy()
        test["uid"] = "f_" + test["norm_hash"].astype(str)
        if test["uid"].duplicated().any():
            raise ValueError(f"{name}: norm_hash is not unique in the test split")

        src = WORK / name / "src"
        shutil.rmtree(src.parent, ignore_errors=True)
        src.mkdir(parents=True)
        written_extensions = {".c": 0, ".cpp": 0}
        for uid, code, lang in zip(test["uid"], test["func_before"], test["lang"]):
            ext = source_ext(code, lang)
            written_extensions[ext] += 1
            (src / f"{uid}{ext}").write_text(code.rstrip() + "\n")

        manifest = test[["uid", "norm_hash", "project_g", "vul"]].copy()
        report = run_scan(semgrep, [RULES, cpp_rule_path], src,
                          RAW / f"{name}_raw.json", semgrep_env)
        scanned_paths = report.get("paths", {}).get("scanned", [])
        alert_uids = {
            Path(finding["path"]).name.rsplit(".", 1)[0]
            for finding in report.get("results", [])
        }
        test["semgrep_alert"] = test["uid"].isin(alert_uids).astype(int)
        manifest["semgrep_alert"] = test["semgrep_alert"].to_numpy()
        manifest.to_csv(OUT / f"{name}_predictions.csv", index=False)
        y = test["vul"].to_numpy(dtype=int)
        pred = test["semgrep_alert"].to_numpy(dtype=int)
        precision, recall, f1 = prf_at(y, pred.astype(float), 0.5)
        rows.append({
            "setting": name,
            "ruleset": "p/c snapshot + derived C++ copies",
            "semgrep_version": version,
            "ruleset_sha256": effective_rules_hash,
            "upstream_ruleset_sha256": upstream_hash,
            "cpp_overlay_sha256": cpp_overlay_hash,
            "ruleset_rule_count": rule_count + len(cpp_rules),
            "upstream_rule_count": rule_count,
            "cpp_overlay_rule_count": len(cpp_rules),
            "n": int(len(test)),
            "positives": int(y.sum()),
            "prevalence": float(y.mean()),
            "c_files_written": written_extensions[".c"],
            "cpp_files_written": written_extensions[".cpp"],
            "scanned_targets": len(scanned_paths),
            "scan_coverage": float(len(scanned_paths) / max(len(test), 1)),
            "parse_error_count": int(len(report.get("errors", []))),
            "alerted_functions": int(pred.sum()),
            "finding_count": int(len(report.get("results", []))),
            "precision": precision,
            "recall": recall,
            "f1": f1,
        })

    result = {
        "source_ruleset": SOURCE_RULESET,
        "ruleset_sha256": effective_rules_hash,
        "upstream_ruleset_sha256": upstream_hash,
        "cpp_overlay_sha256": cpp_overlay_hash,
        "ruleset_rule_count": rule_count + len(cpp_rules),
        "upstream_rule_count": rule_count,
        "cpp_overlay_rule_count": len(cpp_rules),
        "semgrep_version": version,
        "results": rows,
    }
    (OUT / "baseline.json").write_text(json.dumps(result, indent=2) + "\n")
    pd.DataFrame(rows).to_csv(OUT / "baseline.csv", index=False)
    print("\n" + pd.DataFrame(rows).to_string(index=False))
    print(f"\nsaved {OUT / 'baseline.csv'} and {OUT / 'baseline.json'}")


if __name__ == "__main__":
    main()
