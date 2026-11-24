# VulnGNN handoff

Updated 24 November 2026. The source is pushed to the private repository https://github.com/jaiaggarwal12/final-say.git on main. Latest verified project commit is maintained in GitHub.

## Local Windows environment

- Project checkout: D:\GNN_Project_Ragini
- GPU: RTX 4060 Laptop, 8 GiB VRAM; PyTorch 2.13.0+cu126.
- Python environment: .venv-gpu
- Joern and Java 21 are installed under tools/.
- The app was previously run on localhost ports 8005 and 8007. Start a fresh server on port 8000 with the command below.
- Windows App Control blocks Transformers regex native extension. CodeBERT features remain unavailable; no policy was changed.

## Completed research

- Cleaned BigVul: 182,100 functions and 8,609 vulnerable functions.
- Full graph workset: 117,673 planned; 107,461 extracted (91.32%); 1,682 truncated; zero batch or audit errors.
- 59 type-only feature shards with 21 Joern node types.
- Cross-project R-GCN: seeds 7, 21, and 42; mean AP 0.111, sample SD 0.003.
- Within-project R-GCN: seeds 7, 21, and 42 on the same split/configuration; mean AP 0.156, sample SD 0.023. Seed APs are 0.175, 0.164, and 0.130 respectively, each with a function-group cluster interval in its metrics JSON.
- Four cross-project seed-42 relation ablations are in results/gnn/joern_type_only/cross/without_* and summarized in edge_ablation_summary.csv. Their intervals overlap.
- Precision target study: thresholds selected on validation for 50% and 60% precision did not transfer. Held-out precision was 0.000–0.179 with recall 0.000–0.008.
- Held-out line-attribution proxy: top-1/3/5 changed-line hit rates 0.189/0.344/0.435 across all 917 vulnerable test functions; project-cluster intervals and exact random-line expectations are documented in docs/short_report.md. These fix-diff targets are a proxy, not validated vulnerability-line labels.
- Matched-cohort comparison: GNN seed 42 and three legacy v1 text baselines scored on the same 20,957 held-out functions from 109 projects; label/project IDs were checked after joining. AP differences are small and project-bootstrap intervals include zero. Reproduce with scripts/evaluate_matched_baseline_comparison.py.
- Local research UI and source-to-graph-to-model inference route are implemented.
- Progress PDF: output/pdf/VulnGNN_Team_Progress_Report.pdf.
- Mac Codex prompt: RAGINI_REMOTE_CODEX_PROMPT.md.

## Run local demo

From the project root in PowerShell:
$env:PYTHONPATH = (Resolve-Path .\src).Path
.\.venv-gpu\Scripts\python.exe .\scripts\serve_web.py --host 127.0.0.1 --port 8000

The UI can serve cached research pages without re-running training. Live source analysis needs local Joern, type-only metadata, and a compatible checkpoint. It returns an uncalibrated research score; do not present it as a security verdict.

## Local-only files

Datasets (~17 GiB), graph feature shards, Joern, Python environments, model checkpoints, and per-function prediction tables are excluded from GitHub. See LOCAL_ARTIFACTS.md. Ragini must have access to the private GitHub repository before cloning. Keep the Mac checkout intact while comparing or syncing changes.

## Remaining research

1. Resolve CodeBERT runtime access only through an approved deployment or managed package path.
2. Improve line localization against manually reviewed vulnerability-line labels; the current patch-overlap proxy is preliminary.
3. Run more seeds and validation-tuned ablations before making relation-level claims.
4. Revisit the threshold calibration strategy; current validation-selected precision targets do not transfer.
