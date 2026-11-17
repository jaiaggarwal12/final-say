"""Stream the huge raw BigVul CSV; keep only the columns we need."""
import os
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
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

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp_out = Path(OUT).with_suffix(".parquet.tmp")
    string_columns = [c for c in WANTED if c != "vul"]
    writer = None
    rows_written = 0
    try:
        chunks = pd.read_csv(
            RAW, usecols=WANTED, chunksize=CHUNK,
            dtype={column: "string" for column in string_columns},
        )
        for chunk in tqdm(chunks, desc="chunks"):
            chunk = chunk.dropna(subset=["func_before", "vul"])
            chunk["vul"] = chunk["vul"].astype(int)
            chunk = chunk[chunk["func_before"].str.strip().str.len() > 0]
            # func_after is only needed for vulnerable rows (localization ground truth)
            chunk["func_after"] = chunk["func_after"].where(chunk["vul"] == 1)
            if chunk.empty:
                continue
            table = pa.Table.from_pandas(chunk, preserve_index=False)
            if writer is None:
                writer = pq.ParquetWriter(tmp_out, table.schema, compression="snappy")
            writer.write_table(table, row_group_size=CHUNK)
            rows_written += len(chunk)
    finally:
        if writer is not None:
            writer.close()

    if rows_written == 0:
        raise RuntimeError("No usable rows found in the raw BigVul CSV")
    os.replace(tmp_out, OUT)
    print(f"Saved {rows_written:,} rows to {OUT}")


if __name__ == "__main__":
    main()
