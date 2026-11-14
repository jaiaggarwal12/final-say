"""Stream the huge raw BigVul CSV; keep only the columns we need."""
import os

import pandas as pd
from tqdm import tqdm

RAW = "data/raw/MSR_data_cleaned.csv"
OUT = "data/interim/bigvul_slim.parquet"
WANTED = ["project", "commit_id", "file_name", "lang", "CVE ID", "CWE ID",
          "vul", "func_before", "func_after"]
CHUNK = 20_000

def main():
    header = pd.read_csv(RAW, nrows=0).columns.tolist()
    missing = [c for c in WANTED if c not in header]
    assert not missing, f"Columns not found: {missing}. Actual columns: {header}"

    parts = []
    for chunk in tqdm(pd.read_csv(RAW, usecols=WANTED, chunksize=CHUNK),
                      desc="chunks"):
        chunk = chunk.dropna(subset=["func_before", "vul"])
        chunk["vul"] = chunk["vul"].astype(int)
        chunk = chunk[chunk["func_before"].str.strip().str.len() > 0]
        # func_after is only needed for vulnerable rows (localization ground truth)
        chunk["func_after"] = chunk["func_after"].where(chunk["vul"] == 1)
        parts.append(chunk)

    df = pd.concat(parts, ignore_index=True)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    df.to_parquet(OUT, index=False)
    print(f"Saved {len(df):,} rows to {OUT}")


if __name__ == "__main__":
    main()
