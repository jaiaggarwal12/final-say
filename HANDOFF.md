# VulnGNN handoff — 17 November 2026 (updated during R-GCN run)

## Project and local environment

- Repository: `D:\GNN_Project_Ragini`
- Remote: `https://github.com/raginikalra21/gnn-vulnerability-detection`
- Branch: `main`, tracking `origin/main`; source commit before this local work: `d540a8ed40952df279ec5e7dd0a7f44f12280994`.
- GPU: NVIDIA RTX 4060 Laptop, 8 GiB VRAM; driver 566.07.
- Local environment: `.venv-gpu`; portable Java 21 at `tools/temurin-21-jre/jdk-21.0.13+9-jre`.
- PyTorch 2.13.0+cu126 now imports and `torch.cuda.is_available()` is true for the RTX 4060. The feature builder then stopped because App Control blocked Transformers' native regex extension. Code Integrity event 3077 at 17 November 2026 01:33:20 reports `regex\\_regex.cp313-win_amd64.pyd` under policy `{0283ac0f-fff1-49ae-ada1-8a933130cad6}`. Its SHA-256 is `ba577158c33beb9807d7f9a22b6881a1a4fa701a135cea6f99f655ebd8404105` (unsigned). See `docs/APP_CONTROL_RUNTIME.md`. Do not bypass/change policy; request an approved deployment/allowance for the needed native dependencies.

## Completed locally

- BigVul raw ZIP checksum verified; 10.8 GB CSV is present.
- Streaming CSV-to-Parquet preparation was added in `src/vulngnn/data/prepare_bigvul.py`; cleaned data contains 182,100 functions and 8,609 vulnerable functions.
- Leakage-safe splits and MinHash near-duplicate audit generated. Reports: `results/split_report.txt` and processed Parquet in `data/processed/`.
- Deterministic full workset manifest generated at `data/graph_workset/manifest.csv` (117,673 selected functions; 59 batches).
- Full Joern 4.0.683 extraction completed with Java 21.0.13. Independent audit: 117,673 planned and audited, 107,461 graphs (91.32%), 0 batch errors, 0 audit errors, 1,682 truncated graphs. Coverage and audit files are under `data/graph_workset/graphs/`.
- Verified checkpoint archive: `results/graphs_full_2026-11-16.tar.gz` (334,855,059 bytes). SHA-256: `4bb0e844452389cab0625be664305abdedbcc8e53727a9fa95cc3a82aaf27766`; sidecar is alongside it.
- Java/Joern Windows support and UTF-8 snippet/log handling were added to `scripts/run_graph_pipeline.py` and `src/vulngnn/graphs/run_cpg_batches.py`.
- README and progress report were updated to distinguish completed graph extraction from pending model work.
- The Analyze page and `/api/analysis/status` report audited graph/checkpoint state dynamically. The prior API refused predictions while no checkpoint existed; the new local prediction route is available once training saves a compatible checkpoint.
- All 59 `joern_type_only` feature shards are present (107,461 graphs; 21 node types). `CodeBERT` import remains blocked by the same App Control policy; a fresh import attempt failed on `regex._regex`.
- Cross-project R-GCN training and seed-42 held-out test evaluation completed on CUDA using the full type-only feature set. Test N=20,957, positives=917, prevalence=0.04376, AP=0.10752 (whole-project cluster bootstrap 95% CI 0.07591–0.13710), ROC-AUC=0.70998, threshold=0.79920 selected on validation, best epoch=9, validation AP=0.12190. This is one seed and node-type-only; it is not a CodeBERT result.
- Saved artifacts: `results/gnn/joern_type_only/cross/all_edges/metrics_seed42.json`, `model_seed42.pt`, `test_scores_seed42.parquet`, `per_project_seed42.csv`, and `seed_summary.csv`.
- Added `src/vulngnn/inference.py` for type-only R-GCN inference; `scripts/serve_web.py` supports localhost C/C++ upload → bundled Joern extraction → checkpoint prediction. End-to-end API inference on a fresh C function returned an uncalibrated score and graph counts (11 nodes, 32 edges) in 5.56 seconds.
- The Analyze UI reports the active model and offers local inference; the Research UI displays measured graph test rows and their cohort/feature limitations. Updated localhost app is running at `http://127.0.0.1:8004`.
- A split-overlap audit found 833 UIDs in `within` test also occur in `cross` validation. The first within run reused cross-selected hyperparameters, so it is retained only as `exploratory_crossval_tuned_within_seed42.json` and excluded from the research API. A fresh five-trial within-only tuning and final seed-42 test run is complete. Within test N=16,631, positives=776, AP=0.12994 (function-group cluster-bootstrap 95% CI 0.10937–0.15867), ROC-AUC=0.72685, threshold=0.76933, best validation AP=0.13365 at epoch 14. Hyperparameters were selected using only within train/validation data.
- A refreshed server on `http://127.0.0.1:8005` filters metrics until a fresh test run uses its own split's saved validation-selected parameters.

## Remaining work

1. Add cross-project seeds and edge-relation ablations.
2. Resolve the App Control block through an approved deployment/allowance before building raw-identifier and masked CodeBERT feature shards. Do not bypass policy.
3. Extend inference verification across representative C and C++ inputs; keep scores labeled uncalibrated and avoid unsupported severity/localization claims.
4. Update README and short report with measured GNN results and limitations. The project is not complete yet.

## Working-tree notes

Local edits are uncommitted. The full data, tools, virtual environments, graph checkpoint, and training outputs are gitignored or intentionally local; do not push the 335 MB archive or private/unreviewed result artifacts to the public repository. Cross-project training is active; the model-backed inference path has not yet been verified.
