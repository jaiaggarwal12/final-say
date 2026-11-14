"""Shared evaluation helpers. The GNN will reuse these, so results stay comparable."""
import numpy as np
from sklearn.metrics import average_precision_score, precision_recall_curve, roc_auc_score


def precision_at_recall(y, s, target):
    p, r, _ = precision_recall_curve(y, s)
    ok = r >= target
    return float(p[ok].max()) if ok.any() else 0.0


def best_f1_threshold(y, s):
    p, r, t = precision_recall_curve(y, s)
    f1 = 2 * p[:-1] * r[:-1] / np.clip(p[:-1] + r[:-1], 1e-12, None)
    return float(t[np.argmax(f1)])


def prf_at(y, s, thr):
    pred = s >= thr
    tp = int((pred & (y == 1)).sum())
    fp = int((pred & (y == 0)).sum())
    fn = int((~pred & (y == 1)).sum())
    prec = tp / max(tp + fp, 1)
    rec = tp / max(tp + fn, 1)
    return prec, rec, 2 * prec * rec / max(prec + rec, 1e-12)


def bootstrap_ap(y, s, n=200, seed=42):
    """Row-level bootstrap CI for average precision (optimistic: rows are clustered by project)."""
    rng = np.random.default_rng(seed)
    idx = np.arange(len(y))
    vals = []
    for _ in range(n):
        b = rng.choice(idx, size=len(idx), replace=True)
        if y[b].sum() > 0:
            vals.append(average_precision_score(y[b], s[b]))
    return tuple(np.percentile(vals, [2.5, 97.5]))


def cluster_bootstrap_ap(y, s, clusters, n=200, seed=42):
    """Bootstrap AP by resampling whole clusters, not correlated rows.

    Use project IDs for cross-project evaluation and function-group IDs for
    within-project evaluation. Resamples containing only one label are skipped.
    """
    y = np.asarray(y).astype(int)
    s = np.asarray(s, dtype=float)
    clusters = np.asarray(clusters).astype(str)
    if not (len(y) == len(s) == len(clusters)):
        raise ValueError("y, scores and clusters must have the same length")
    unique = np.unique(clusters)
    if len(unique) < 2:
        return float("nan"), float("nan")
    members = {cluster: np.flatnonzero(clusters == cluster) for cluster in unique}
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(n):
        sampled = rng.choice(unique, size=len(unique), replace=True)
        idx = np.concatenate([members[cluster] for cluster in sampled])
        if 0 < y[idx].sum() < len(idx):
            vals.append(average_precision_score(y[idx], s[idx]))
    if not vals:
        return float("nan"), float("nan")
    return tuple(float(x) for x in np.percentile(vals, [2.5, 97.5]))


def summarize(y, s, thr, clusters, n_boot=200, seed=42):
    y = np.asarray(y).astype(int)
    s = np.asarray(s, dtype=float)
    prec, rec, f1 = prf_at(y, s, thr)
    lo, hi = cluster_bootstrap_ap(y, s, clusters, n=n_boot, seed=seed)
    return {
        "n": int(len(y)), "positives": int(y.sum()), "prevalence": float(y.mean()),
        "ap": float(average_precision_score(y, s)), "ap_ci_low": float(lo),
        "ap_ci_high": float(hi), "roc_auc": float(roc_auc_score(y, s)),
        "ap_ci_method": "cluster_bootstrap",
        "p_at_r30": precision_at_recall(y, s, 0.3),
        "p_at_r50": precision_at_recall(y, s, 0.5),
        "precision": prec, "recall": rec, "f1": f1,
    }
