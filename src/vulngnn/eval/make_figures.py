"""Progress figures. PR curves appear only if baseline scores exist."""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from sklearn.metrics import average_precision_score, precision_recall_curve

os.makedirs("results/figures", exist_ok=True)
cols = ["project_g", "vul", "split_cross", "split_within"]
df = pd.read_parquet("data/processed/bigvul_clean.parquet", columns=cols)
COLORS = {"train": "#4c78a8", "val": "#f58518", "test": "#54a24b"}

# 1. Cleaning funnel for vulnerable functions (numbers from results/split_report.txt)
steps = [("Raw BigVul", 10900), ("- no-op fixes", 10566), ("- label conflicts", 9292),
         ("- duplicates", 9225), ("- over 8,000 chars", 8609)]
fig, ax = plt.subplots(figsize=(8, 3.6))
ax.bar([s[0] for s in steps], [s[1] for s in steps], color="#4c78a8")
for i, (_, v) in enumerate(steps):
    ax.text(i, v + 80, f"{v:,}", ha="center", fontsize=9)
ax.set_ylabel("Vulnerable functions remaining")
ax.set_title("Data cleaning: 21% of vulnerable examples removed")
plt.xticks(rotation=15)
plt.tight_layout()
plt.savefig("results/figures/01_cleaning_funnel.png", dpi=160)
plt.close()

# 2. Largest projects, coloured by cross-project assignment
proj = (df.groupby("project_g")
          .agg(rows=("vul", "size"), pos=("vul", "sum"), split=("split_cross", "first"))
          .sort_values("rows", ascending=False).head(20).iloc[::-1])
fig, ax = plt.subplots(figsize=(8, 6))
ax.barh(proj.index, proj["rows"], color=[COLORS[s] for s in proj["split"]])
ax.set_xscale("log")
ax.set_xlabel("Functions (log scale)")
ax.set_title("20 largest projects, coloured by cross-project split")
ax.legend(handles=[plt.Rectangle((0, 0), 1, 1, color=c) for c in COLORS.values()],
          labels=list(COLORS), loc="lower right")
plt.tight_layout()
plt.savefig("results/figures/02_projects.png", dpi=160)
plt.close()

# 3. Split sizes
fig, ax = plt.subplots(figsize=(9, 2.8))
for i, (name, col) in enumerate([("within-project", "split_within"),
                                 ("cross-project", "split_cross")]):
    counts = df[col].value_counts().reindex(["train", "val", "test"])
    left = 0
    for s in ["train", "val", "test"]:
        ax.barh(i, counts[s], left=left, color=COLORS[s], label=s if i == 0 else None)
        ax.text(left + counts[s] / 2, i, f"{counts[s]:,}", ha="center", va="center",
                color="white", fontsize=8)
        left += counts[s]
ax.set_yticks([0, 1])
ax.set_yticklabels(["within-project", "cross-project"])
ax.set_xlabel("Functions")
ax.set_title("Two leakage-safe splits")
ax.legend(ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.35))
plt.tight_layout()
plt.savefig("results/figures/03_splits.png", dpi=160)
plt.close()

# 4. Precision-recall curves for the baselines
if os.path.exists("results/baseline_scores.parquet"):
    sc = pd.read_parquet("results/baseline_scores.parquet")
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2), sharey=True)
    titles = {"within": "Within-project split", "cross": "Cross-project split (unseen projects)"}
    for ax, setting in zip(axes, ["within", "cross"]):
        d = sc[sc["setting"] == setting]
        prev = d[d["model"] == d["model"].iloc[0]]["y"].mean()
        for model in d["model"].unique():
            m = d[d["model"] == model]
            p, r, _ = precision_recall_curve(m["y"], m["score"])
            ap = average_precision_score(m["y"], m["score"])
            ax.plot(r, p, label=f"{model} (AP={ap:.3f})")
        ax.axhline(prev, ls="--", color="gray", label=f"random (AP={prev:.3f})")
        ax.set_xlabel("Recall")
        ax.set_title(titles[setting])
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.legend(loc="upper right", fontsize=8)
    axes[0].set_ylabel("Precision")
    plt.tight_layout()
    plt.savefig("results/figures/04_baseline_pr_curves.png", dpi=160)
    plt.close()
else:
    print("baseline_scores.parquet not found; skipped PR curves")
print("figures saved in results/figures/")