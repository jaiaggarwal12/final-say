# VulnGNN: C/C++ Vulnerability Research

VulnGNN studies whether code property graphs and an R-GCN can help rank vulnerable C/C++ functions in repositories excluded from training. It includes BigVul cleaning, Joern graph extraction, model training and evaluation, and a local browser interface.

This is a research prototype, not a security verdict. The current checkpoint uses Joern node types only; its scores are uncalibrated. CodeBERT feature generation and training remain incomplete.

## Current evidence

- Cleaned BigVul snapshot: 182,100 functions, including 8,609 vulnerable functions (4.7%).
- Joern extraction: 107,461 graphs from 117,673 planned functions (91.32%).
- Three cross-project R-GCN runs: mean average precision (AP) 0.111, standard deviation 0.003.
- On the same held-out functions, R-GCN AP was 0.108; text baselines ranged from 0.105 to 0.120. The evidence does not establish a graph advantage.
- The demo can miss unsafe code. A “not flagged” result does not mean safe.

## Run the local website

Install dependencies and start the server from the repository root:

```bash
python -m venv .venv
# Activate the environment for your shell, then:
pip install -r requirements.txt
python src/scripts/serve_web.py --port 8000
```

Open `http://127.0.0.1:8000`. The research pages use the compact results kept in `results/`. Live source analysis also requires the local BigVul/graph data, Joern, a compatible checkpoint, and the graph-inference dependencies; those large machine-specific files are not stored in GitHub.

Five small C examples for a presentation demo are in [`docs/demo_samples`](docs/demo_samples). They illustrate narrow, known patterns; they are not an accuracy benchmark.

## Rebuild the data and graph pipeline

The public BigVul archive is downloaded into `data/raw/`. Extract it, then clean and split the functions:

```bash
python src/scripts/download_bigvul.py
python -m zipfile -e data/raw/MSR_data_cleaned.zip data/raw
python src/vulngnn/data/prepare_bigvul.py
python src/vulngnn/data/make_splits.py
python src/vulngnn/data/near_dup_check.py
```

Full graph extraction requires Java 21 and a local Joern installation. Configure `tools/joern/joern-cli`, then run `python src/scripts/run_graph_pipeline.py`. The command processes the full workset, so use `--help` to inspect batch options before starting a new extraction.

## Train the current type-only R-GCN

Create the Joern type-only graph shards first, then install the graph-learning requirements from [`docs/requirements/requirements-gnn.txt`](docs/requirements/requirements-gnn.txt). In PowerShell, from the repository root:

```powershell
$env:PYTHONPATH = (Resolve-Path .\src).Path
.\.venv-gpu\Scripts\python.exe -m vulngnn.train.train_gnn `
  --setting cross `
  --data .\data\graph_dataset\joern_type_only `
  --device cuda --batch-size 128 --epochs 25 --patience 5 `
  --hidden-dim 256 --layers 4 --dropout 0.1624074561769746 `
  --lr 0.00016998978382700775 --weight-decay 0.000001493656855461763 `
  --pos-weight-scale 1.7992642186624028
```

The model and evaluation code is under `src/vulngnn`. The other dependency sets are `docs/requirements/requirements-graph.txt` for graph extraction and `docs/requirements/requirements-semgrep.txt` for the optional Semgrep baseline.

## Course materials

- [Project report](docs/deliverables/VulnGNN_Course_Project_Report.docx)
- [Presentation](docs/deliverables/VulnGNN_Course_Project_Presentation.pptx)

## Repository layout

- `src/`: data preparation, graph extraction, model, training, evaluation, and app server.
- `web/`: browser interface.
- `results/`: only the summary tables and figures used by the app and report.
- `docs/`: course materials, demo samples, and optional dependency files.

The dataset, virtual environments, Joern install, and trained checkpoints stay local because they are large. A fresh GitHub clone needs those runtime assets before source upload analysis is available.