"""Build a reproducible, batched CPG workset without modifying BigVul splits.

The default workset includes every vulnerable function, all eligible val/test
rows from both split definitions, and a configurable uniform sample of safe
training rows. Source files are written once per unique norm_hash.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATA = ROOT / "data/processed/bigvul_clean.parquet"
DEFAULT_OUT = ROOT / "data/graph_workset"
SEED = 42
CPP_HINT = re.compile(
    r"\w\s*::\s*\w"
    r"|\b(?:class|template|namespace|typename|using|nullptr|new|delete|this|"
    r"throw|try|catch|constexpr|consteval|constinit|concept|requires|"
    r"co_await|co_return|co_yield|operator|public|private|protected|virtual|"
    r"override|final|dynamic_cast|static_cast|reinterpret_cast|const_cast)\b"
)
SPLITS = {"within": "split_within", "cross": "split_cross"}


def source_ext(code: str, lang: str) -> str:
    return ".cpp" if lang in ("CPP", "C++") or CPP_HINT.search(code) else ".c"


def plan_workset(df: pd.DataFrame, negative_ratio: float, seed: int):
    if df["norm_hash"].duplicated().any():
        raise ValueError("norm_hash must be unique; refusing to make ambiguous graph IDs")
    df = df.copy().reset_index(drop=True)
    df["near_dup_cross"] = df["near_dup_cross"].astype(bool)

    for name, split_col in SPLITS.items():
        role = df[split_col]
        use_train = role.eq("train") & df["vul"].eq(1)
        safe_train = df.index[role.eq("train") & df["vul"].eq(0)]
        n_negative = min(len(safe_train), int(round(int(use_train.sum()) * negative_ratio)))
        if n_negative:
            sampled = df.loc[safe_train].sample(n=n_negative, random_state=seed).index
            use_train.loc[sampled] = True
        df[f"use_train_{name}"] = use_train
        use_eval = role.isin(["val", "test"])
        if name == "cross":
            use_eval &= ~df["near_dup_cross"]
        df[f"use_eval_{name}"] = use_eval

    # Include all positives globally, even if a row is training-only in both splits.
    required = df["vul"].eq(1)
    for name in SPLITS:
        required |= df[f"use_train_{name}"] | df[f"use_eval_{name}"]
    work = df.loc[required].copy()
    work["uid"] = "f_" + work["norm_hash"].astype(str)
    work["ext"] = [source_ext(code, lang)
                   for code, lang in zip(work["func_before"], work["lang"])]
    work = work.sample(frac=1, random_state=seed).reset_index(drop=True)
    return work


def coverage_table(df: pd.DataFrame, work: pd.DataFrame) -> pd.DataFrame:
    pieces = []
    selected = work.set_index("norm_hash")
    for name, split_col in SPLITS.items():
        for role in ("train", "val", "test"):
            eligible = df[df[split_col].eq(role)].copy()
            if name == "cross" and role != "train":
                eligible = eligible[~eligible["near_dup_cross"].astype(bool)]
            included_hashes = set(
                selected.index[selected[f"use_train_{name}"] if role == "train"
                               else selected[f"use_eval_{name}"]]
            )
            eligible["selected"] = eligible["norm_hash"].isin(included_hashes)
            tab = (eligible.groupby(["project_g", "vul"], observed=True)
                   .agg(total=("norm_hash", "size"), selected=("selected", "sum"))
                   .reset_index())
            tab.insert(0, "role", role)
            tab.insert(0, "setting", name)
            tab["coverage"] = tab["selected"] / tab["total"]
            pieces.append(tab)
    return pd.concat(pieces, ignore_index=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--negative-ratio", type=float, default=5.0,
                        help="safe train rows sampled per vulnerable train row, per split (default: 5)")
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--plan-only", action="store_true",
                        help="print workset size and coverage without writing files")
    args = parser.parse_args()
    if args.negative_ratio < 0 or args.batch_size < 1:
        parser.error("negative ratio must be nonnegative and batch size must be positive")

    df = pd.read_parquet(args.data).reset_index(drop=True)
    work = plan_workset(df, args.negative_ratio, args.seed)
    work["batch_id"] = work.index // args.batch_size
    coverage = coverage_table(df, work)
    print(f"clean rows: {len(df):,} | vulnerable: {int(df['vul'].sum()):,}")
    print(f"workset rows: {len(work):,} | vulnerable: {int(work['vul'].sum()):,} | "
          f"batches: {int(work['batch_id'].max()) + 1:,}")
    print("\nworkset by class:")
    print(work.groupby("vul").size().rename("selected").to_string())
    print("\ncoverage by split and role:")
    print(coverage.groupby(["setting", "role"])[["total", "selected"]]
          .sum().assign(coverage=lambda x: x["selected"] / x["total"])
          .round(3).to_string())
    print(f"\nprojects represented: {work['project_g'].nunique()} / "
          f"{df['project_g'].nunique()}")

    if args.plan_only:
        return
    if args.out.exists():
        if not args.out.is_dir():
            raise SystemExit(f"Output path is not a directory: {args.out}")
        if any(args.out.iterdir()):
            raise SystemExit(
                f"Output directory is not empty: {args.out}; choose a new --out path. "
                "Existing worksets and graph outputs are never removed."
            )

    args.out.mkdir(parents=True, exist_ok=True)
    work.to_csv(args.out / "manifest.csv", index=False)
    coverage.to_csv(args.out / "coverage_by_project.csv", index=False)
    for batch_id, batch in work.groupby("batch_id", sort=True):
        src = args.out / "batches" / f"batch_{int(batch_id):05d}" / "src"
        src.mkdir(parents=True)
        for row in batch.itertuples(index=False):
            (src / f"{row.uid}{row.ext}").write_text(row.func_before.rstrip() + "\n")
    print(f"\nwrote manifest, project coverage, and source batches to {args.out}")


if __name__ == "__main__":
    main()
