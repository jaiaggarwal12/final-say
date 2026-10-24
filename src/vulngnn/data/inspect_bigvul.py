import pandas as pd

df = pd.read_parquet("data/interim/bigvul_slim.parquet")
print("rows:", len(df))
print("vulnerable:", int(df["vul"].sum()), f"({df['vul'].mean():.2%})")
print("projects:", df["project"].nunique())

by_proj = df.groupby("project")["vul"].agg(rows="size", vulnerable="sum")
print("\nTop 15 projects by rows:")
print(by_proj.sort_values("rows", ascending=False).head(15))
print("\nTop 15 projects by vulnerable count:")
print(by_proj.sort_values("vulnerable", ascending=False).head(15))

dups = df.duplicated(subset="func_before").sum()
print(f"\nexact duplicate func_before rows: {dups:,}")
print("\nfunction length (chars) percentiles:")
print(df["func_before"].str.len().describe(percentiles=[.5, .9, .99]).round(0))