#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export JAVA_HOME="$(brew --prefix openjdk@21)/libexec/openjdk.jdk/Contents/Home"
export PATH="$JAVA_HOME/bin:$PATH"
JOERN="$PWD/tools/joern/joern-cli"

echo "[1/5] sampling functions"
python src/vulngnn/graphs/make_pilot_sample.py
echo "[2/5] joern-parse"
( cd data/pilot && "$JOERN/joern-parse" src )
echo "[3/5] joern-export"
( cd data/pilot && rm -rf export && "$JOERN/joern-export" --repr all --format neo4jcsv --out export )
echo "[4/5] extracting graphs"
python src/vulngnn/graphs/extract_cpg_pilot.py | tee results/pilot/extract_log.txt
echo "[5/5] drawing figure"
python src/vulngnn/graphs/draw_cpg_panels.py
echo "ALL DONE"
