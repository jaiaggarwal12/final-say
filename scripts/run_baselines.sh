#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"
source .venv/bin/activate
export PYTHONPATH="$PROJECT_ROOT/src"
export MPLCONFIGDIR="${TMPDIR:-/tmp}/gnn-vulnerability-detection-mplconfig"
export XDG_CACHE_HOME="${TMPDIR:-/tmp}/gnn-vulnerability-detection-xdg-cache"
export MPLBACKEND=Agg
mkdir -p "$MPLCONFIGDIR" "$XDG_CACHE_HOME"

echo "=== Semgrep frozen-rule baseline ==="
python -m vulngnn.eval.semgrep_baseline_v2

if ! command -v cppcheck >/dev/null 2>&1; then
  echo "cppcheck is required for the complete baseline suite (install cppcheck 2.22.0 or newer)." >&2
  exit 2
fi
echo "=== Cppcheck warning/error baseline ==="
python -m vulngnn.eval.cppcheck_baseline

echo "=== Text baselines and final Phase 2A artifacts ==="
python -m vulngnn.train.baseline_tfidf_v2
