# Local artifacts excluded from Git

This repository tracks source, configuration, project documentation, the course report and presentation, and compact result summaries. Large or machine-specific artifacts remain local:

- `data/` (about 17 GiB on the Windows machine): dataset and extracted graph data. See the dataset acquisition and graph extraction instructions in `README.md` and `HANDOFF.md`.
- `.venv/`, `.venv-gpu/`, `tools/`, and Joern installation files: environment and tool installations; recreate from the documented dependency files and install instructions.
- `results/graphs_full_2026-11-16.tar.gz` (about 335 MB): generated graph archive. Its adjacent SHA-256 file is retained locally; rebuild using the graph pipeline if needed.
- `results/gnn/**/model_*.pt`: trained checkpoints, about 5.6 MiB each. Regenerate by running the documented training commands.
- `results/gnn/**/test_scores_seed*.parquet`: per-function prediction tables, reproducible from a checkpoint and test data.

The tracked `results/gnn/**/metrics_*.json`, `per_project_*.csv`, and `seed_summary.csv` files contain the compact summaries used in the report. No dataset, checkpoint, or virtual environment is included in the GitHub push.
