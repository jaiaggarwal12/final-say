import hashlib
import re

import pandas as pd

COMMENTS = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)


def normalize(s: str) -> str:
    return re.sub(r"\s+", "", COMMENTS.sub("", s))


def main():
    df = pd.read_parquet("data/interim/bigvul_slim.parquet")

    # 1. All project names (look for aliases like php / php-src)
    names = sorted(df["project"].unique(), key=str.lower)
    print(f"{len(names)} projects:")
    print(", ".join(names))

    # 2. Language and file_name format
    print("\nlang counts:")
    print(df["lang"].value_counts(dropna=False))
    print("\nfile_name samples:", df["file_name"].head(5).tolist())
    print("distinct (project, file_name) groups:",
          df.groupby(["project", "file_name"]).ngroups)

    df["norm_hash"] = df["func_before"].map(
        lambda s: hashlib.md5(normalize(s).encode()).hexdigest())
    g = df.groupby("norm_hash").agg(
        size=("vul", "size"), labels=("vul", "nunique"),
        projects=("project", "nunique"))
    print("\nnormalized-duplicate groups (size > 1):", int((g["size"] > 1).sum()))
    print("rows inside those groups:", int(g.loc[g["size"] > 1, "size"].sum()))
    print("groups with conflicting labels (both 0 and 1):",
          int((g["labels"] > 1).sum()))
    print("groups spanning more than one project:", int((g["projects"] > 1).sum()))

    # 4. Length caps: how many functions and positives survive
    lens = df["func_before"].str.len()
    total_pos = int(df["vul"].sum())
    print("\nlength cap -> fraction kept | positives kept")
    for cap in [2000, 4000, 8000]:
        keep = lens <= cap
        print(f"{cap:>5} chars -> {keep.mean():.1%} | "
              f"{int(df.loc[keep, 'vul'].sum())} / {total_pos}")

    # 5. Vulnerable rows: sanity checks for the localization ground truth
    pos = df[df["vul"] == 1]
    print("\nvulnerable rows:", len(pos))
    print("with func_after present:", int(pos["func_after"].notna().sum()))
    print("func_after identical to func_before:",
          int((pos["func_after"] == pos["func_before"]).sum()))
    print("\ntop 10 CWE IDs among vulnerable rows:")
    print(pos["CWE ID"].value_counts().head(10))


if __name__ == "__main__":
    main()
