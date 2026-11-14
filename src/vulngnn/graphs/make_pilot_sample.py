"""Pick a small seeded sample of cleaned BigVul functions; write each as its own source file.
BigVul's 'lang' tag is unreliable, so C++ code is detected and written as .cpp."""
import re
from pathlib import Path

import pandas as pd

SRC = "data/processed/bigvul_clean.parquet"
PILOT = Path("data/pilot")
N_PER_CLASS = 30
MIN_CHARS, MAX_CHARS = 250, 1200
SEED = 42
CPP_HINT = re.compile(r"\w::\w|\bclass\s+\w|\btemplate\s*<|\bnamespace\b|\bnullptr\b")


def ext_for(code, lang):
    return ".cpp" if lang in ("CPP", "C++") or CPP_HINT.search(code) else ".c"


def main():
    df = pd.read_parquet(SRC).reset_index(drop=True)
    df["chars"] = df["func_before"].str.len()
    pool = df[df["chars"].between(MIN_CHARS, MAX_CHARS)]

    parts = []
    for label in (1, 0):
        sub = pool[pool["vul"] == label].sample(frac=1, random_state=SEED)
        parts.append(sub.drop_duplicates("project_g").head(N_PER_CLASS))  # spread over projects
    sample = pd.concat(parts).reset_index(drop=True)
    sample["uid"] = "f_" + sample["norm_hash"].str[:12]
    sample["ext"] = [ext_for(c, l) for c, l in zip(sample["func_before"], sample["lang"])]
    assert sample["uid"].is_unique

    result_dir = Path("results/pilot")
    result_manifest = result_dir / "manifest.csv"
    if PILOT.exists() and any(PILOT.iterdir()):
        raise SystemExit(f"Refusing to overwrite nonempty pilot output: {PILOT}")
    if result_manifest.exists():
        raise SystemExit(f"Refusing to overwrite existing pilot manifest: {result_manifest}")
    PILOT.mkdir(parents=True, exist_ok=True)
    (PILOT / "src").mkdir(parents=True, exist_ok=True)
    for uid, code, ext in zip(sample["uid"], sample["func_before"], sample["ext"]):
        (PILOT / "src" / f"{uid}{ext}").write_text(code.rstrip() + "\n")

    cols = ["uid", "ext", "vul", "project_g", "commit_id", "CVE ID", "CWE ID", "chars", "norm_hash"]
    sample[cols].to_csv(PILOT / "manifest.csv", index=False)
    result_dir.mkdir(parents=True, exist_ok=True)
    sample[cols].to_csv(result_manifest, index=False)
    print(f"wrote {len(sample)} functions ({int(sample.vul.sum())} vulnerable), "
          f"{int((sample.ext == '.cpp').sum())} written as C++")


if __name__ == "__main__":
    main()
