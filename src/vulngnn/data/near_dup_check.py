"""Flag val/test functions that have a near-copy (Jaccard >= 0.8 on token 5-grams) in train."""
import re

import pandas as pd
from datasketch import MinHash, MinHashLSH
from tqdm import tqdm

PATH = "data/processed/bigvul_clean.parquet"
THRESH, NUM_PERM, K = 0.8, 64, 5

COMMENTS = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)
TOKEN = re.compile(r"[A-Za-z_]\w*|\d+|[^\s\w]")


def signature(code: str) -> MinHash:
    toks = TOKEN.findall(COMMENTS.sub(" ", code))
    grams = {" ".join(toks[i:i + K]) for i in range(max(1, len(toks) - K + 1))}
    m = MinHash(num_perm=NUM_PERM)
    for g in grams:
        m.update(g.encode("utf-8", "ignore"))
    return m


df = pd.read_parquet(PATH).reset_index(drop=True)
sigs = [signature(s) for s in tqdm(df["func_before"], desc="minhash")]


def flag(split_col: str, target: str) -> pd.Series:
    lsh = MinHashLSH(threshold=THRESH, num_perm=NUM_PERM)
    for i in df.index[df[split_col] == "train"]:
        lsh.insert(str(i), sigs[i])
    idx = df.index[df[split_col] == target]
    return pd.Series([len(lsh.query(sigs[i])) > 0 for i in idx], index=idx)


for col, out in [("split_cross", "near_dup_cross"), ("split_within", "near_dup_within")]:
    df[out] = False
    for target in ["val", "test"]:
        f = flag(col, target)
        df.loc[f.index, out] = f.values

print("\nsplit        set   rows  near-dup rows (%)  vulnerable  near-dup vulnerable (%)")
for col, out in [("split_cross", "near_dup_cross"), ("split_within", "near_dup_within")]:
    for target in ["val", "test"]:
        m = df[col] == target
        mp = m & (df["vul"] == 1)
        print(f"{col:<12} {target:<5} {int(m.sum()):>6} {int(df.loc[m, out].sum()):>7} "
              f"({df.loc[m, out].mean():.1%})  {int(mp.sum()):>6} "
              f"{int(df.loc[mp, out].sum()):>7} ({df.loc[mp, out].mean():.1%})")

t = df[df["split_cross"] == "test"]
print("\nlargest cross-project test projects:")
print(t.groupby("project_g")["vul"].agg(rows="size", vulnerable="sum")
      .sort_values("rows", ascending=False).head(10))
print("\ncross-project test projects with most near-dup rows:")
print(t.groupby("project_g")["near_dup_cross"].agg(rows="size", near_dup="sum")
      .sort_values("near_dup", ascending=False).head(10))

df.to_parquet(PATH, index=False)
print("\nsaved flags to", PATH)