"""Clean BigVul and build two leakage-safe splits.

split_within: grouped by (project, function name); same function never on both sides.
split_cross : whole projects held out for val/test (generalization to unseen projects).
"""
import hashlib
import os
import random
import re

import pandas as pd
from sklearn.model_selection import StratifiedGroupKFold

IN = "data/interim/bigvul_slim.parquet"
OUT = "data/processed/bigvul_clean.parquet"
REPORT = "results/split_report.txt"
SEED = 42
MAX_CHARS = 8000
TEST_POS_FRAC = 0.12  # share of all vulnerable functions held out as cross-project test
VAL_POS_FRAC = 0.06

# Judgment calls from project names; refine later if needed.
ALIASES = {
    "php-src": "php", "ImageMagick6": "ImageMagick", "postgres": "postgresql",
    "varnish-cache": "Varnish-Cache", "libav": "FFmpeg", "polarssl": "mbedtls",
    "mindrot": "openssh-portable", "linux-nfs": "linux", "media-tree": "linux",
    "gst-plugins-ugly": "gstreamer", "Onigmo": "oniguruma",
    "Openswan": "libreswan", "sgminer": "cgminer", "mongoose-os": "mongoose",
    "irssi-proxy": "irssi",
}
# Mega-projects and hosting-site pseudo-projects: always train, never held out.
TRAIN_ONLY = {"Chrome", "linux", "Android", "savannah", "launchpad",
              "infradead", "lysator", "pengutronix", "src", "kde", "drm"}

lines = []


def log(msg=""):
    print(msg)
    lines.append(str(msg))


COMMENTS = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)
NAME = re.compile(r"([A-Za-z_~][A-Za-z0-9_:~]*)\s*\(")


def norm_hash(s: str) -> str:
    s = re.sub(r"\s+", "", COMMENTS.sub("", s))
    return hashlib.md5(s.encode("utf-8", "ignore")).hexdigest()


def func_name(s: str) -> str:
    m = NAME.search(s[:400])
    return m.group(1) if m else "?"


df = pd.read_parquet(IN)
df["project_g"] = df["project"].replace(ALIASES)
log(f"loaded: {len(df):,} rows, {int(df.vul.sum()):,} vulnerable, "
    f"{df.project.nunique()} raw projects -> {df.project_g.nunique()} after merging aliases")

df["norm_hash"] = df["func_before"].map(norm_hash)

# 1. vulnerable rows whose fix changes nothing but comments/whitespace
pos = df["vul"] == 1
same = pd.Series(False, index=df.index)
same[pos] = df.loc[pos, "func_after"].fillna("").map(norm_hash) == df.loc[pos, "norm_hash"]
log(f"drop: vulnerable rows with a no-op fix: {int(same.sum())}")
df = df[~same]

# 2. identical functions carrying both labels
conf = df.groupby("norm_hash")["vul"].transform("nunique") > 1
log(f"drop: rows in label-conflict groups: {int(conf.sum()):,} "
    f"({int(df.loc[conf, 'vul'].sum()):,} labeled vulnerable)")
df = df[~conf]

# 3. keep one copy of each remaining duplicate group (global, so no copy crosses splits)
before = len(df)
df = df.sort_values(["project_g", "commit_id"]).drop_duplicates("norm_hash", keep="first")
log(f"drop: redundant normalized duplicates: {before - len(df):,}")

# 4. length cap
too_long = df["func_before"].str.len() > MAX_CHARS
log(f"drop: functions over {MAX_CHARS} chars: {int(too_long.sum()):,} "
    f"({int(df.loc[too_long, 'vul'].sum()):,} vulnerable)")
df = df[~too_long].reset_index(drop=True)

df["func_name"] = df["func_before"].map(func_name)
df["group"] = df["project_g"] + "::" + df["func_name"]
log(f"\nafter cleaning: {len(df):,} rows, {int(df.vul.sum()):,} vulnerable")
log("largest function-name groups:\n" + df["group"].value_counts().head(8).to_string())

# ---- Cross-project split: whole projects held out ----
rng = random.Random(SEED)
stats = df.groupby("project_g")["vul"].agg(rows="size", pos="sum")
eligible = sorted(p for p in stats.index if p not in TRAIN_ONLY)
rng.shuffle(eligible)
total_pos = int(df["vul"].sum())
assign = {p: "train" for p in stats.index}
test_pos = val_pos = 0
for p in eligible:
    if test_pos < TEST_POS_FRAC * total_pos:
        assign[p] = "test"
        test_pos += int(stats.loc[p, "pos"])
    elif val_pos < VAL_POS_FRAC * total_pos:
        assign[p] = "val"
        val_pos += int(stats.loc[p, "pos"])
df["split_cross"] = df["project_g"].map(assign)

# ---- Within-project split: grouped by (project, function name) ----
sgkf = StratifiedGroupKFold(n_splits=10, shuffle=True, random_state=SEED)
fold = pd.Series(-1, index=df.index)
for k, (_, idx) in enumerate(sgkf.split(df, df["vul"], groups=df["group"])):
    fold.iloc[idx] = k
df["split_within"] = fold.map(lambda k: "test" if k == 0 else "val" if k == 1 else "train")

# ---- Leakage assertions ----
assert (df.groupby("group")["split_within"].nunique() == 1).all(), "function group crosses splits"
assert (df.groupby("project_g")["split_cross"].nunique() == 1).all(), "project crosses splits"
assert df["norm_hash"].is_unique, "duplicate function survived"

# ---- Report ----
for col in ["split_within", "split_cross"]:
    t = df.groupby(col).agg(rows=("vul", "size"), vulnerable=("vul", "sum"),
                            projects=("project_g", "nunique"))
    t["prevalence"] = (t["vulnerable"] / t["rows"]).map("{:.2%}".format)
    log(f"\n== {col} ==\n{t.to_string()}")
for s in ["val", "test"]:
    log(f"\ncross-project {s} projects: "
        + ", ".join(sorted(p for p, v in assign.items() if v == s)))

os.makedirs("data/processed", exist_ok=True)
os.makedirs("results", exist_ok=True)
df.to_parquet(OUT, index=False)
with open(REPORT, "w") as f:
    f.write("\n".join(lines))
log(f"\nsaved {OUT} and {REPORT}")