"""Pick a small seeded sample of cleaned BigVul functions; write each as its own .c file."""
import shutil
from pathlib import Path

import pandas as pd

SRC = "data/processed/bigvul_clean.parquet"
PILOT = Path("data/pilot")
N_PER_CLASS = 30
MIN_CHARS, MAX_CHARS = 250, 1200
SEED = 42

df = pd.read_parquet(SRC).reset_index(drop=True)
df["chars"] = df["func_before"].str.len()
pool = df[df["chars"].between(MIN_CHARS, MAX_CHARS)]

parts = []
for label in (1, 0):
    sub = pool[pool["vul"] == label].sample(frac=1, random_state=SEED)
    parts.append(sub.drop_duplicates("project_g").head(N_PER_CLASS))  # spread over projects
sample = pd.concat(parts).reset_index(drop=True)
sample["uid"] = "f_" + sample["norm_hash"].str[:12]
assert sample["uid"].is_unique

shutil.rmtree(PILOT, ignore_errors=True)  # re-running wipes earlier pilot outputs
(PILOT / "src").mkdir(parents=True)
for uid, code in zip(sample["uid"], sample["func_before"]):
    (PILOT / "src" / f"{uid}.c").write_text(code.rstrip() + "\n")

cols = ["uid", "vul", "project_g", "commit_id", "CVE ID", "CWE ID", "chars", "norm_hash"]
sample[cols].to_csv(PILOT / "manifest.csv", index=False)
Path("results/pilot").mkdir(parents=True, exist_ok=True)
sample[cols].to_csv("results/pilot/manifest.csv", index=False)
print(f"wrote {len(sample)} functions ({int(sample.vul.sum())} vulnerable) to {PILOT / 'src'}")
print(sample.groupby("vul")["chars"].describe().round(0))