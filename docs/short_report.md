# VulnGNN research status

**Updated 24 November 2026.** This is a working research prototype with a polished local UI, audited code graphs, cross-project and within-project R-GCN results, and a validation-to-test precision-transfer study. It is not a production vulnerability detector.

## Research goal

Test whether code-property-graph structure (syntax, control flow, data dependencies, and control dependence) can rank vulnerable C/C++ functions in repositories excluded from training.

## Data and graph pipeline

- Cleaned BigVul set: 182,100 functions, 8,609 vulnerable functions, 295 merged projects.
- Deterministic graph workset: 117,673 functions.
- Joern extraction: 107,461 graphs (91.32%); 1,682 truncated; no batch or audit errors.
- Type-only feature shards: 59 shards, 21 node types.
- Held-out graph test cohort: 20,957 functions, 917 positives (4.38%); evaluation excludes near duplicates.
- Full source data, graph shards, Joern installation, environments, checkpoints, and prediction tables remain local. The repo documents these exclusions in LOCAL_ARTIFACTS.md.

## Baseline graph model

R-GCN with one-hot Joern node types and AST, CFG, reaching-definition, and control-dependence relations. Threshold selected on validation; test evaluated once. Confidence intervals resample whole projects.

| Cross-project seed | AP (project-cluster 95% CI) | ROC-AUC | Test precision | Test recall |
|---:|---:|---:|---:|---:|
| 42 | 0.108 (0.076–0.137) | 0.710 | 0.136 | 0.356 |
| 7 | 0.113 (0.087–0.142) | 0.708 | 0.130 | 0.366 |
| 21 | 0.113 (0.082–0.140) | 0.715 | 0.122 | 0.366 |

Mean cross-project AP is 0.111 (sample SD 0.003 across three seeds). This is a preliminary node-type-only result and is not a CodeBERT comparison.

The clean within-project seed-42 run has N=16,631, 776 positives, AP 0.130 (function-group 95% CI 0.109–0.159), and ROC-AUC 0.727. Its split is not directly paired with the cross-project cohort.

## Matched-cohort comparison

To compare the graph model fairly with existing text scores, we joined the seed-42 GNN predictions to legacy v1 baseline predictions by normalized function hash and verified that every joined row had the same label and project ID. This yields the same 20,957 held-out functions (917 positives) across 109 projects for every model. Project-cluster bootstrap intervals describe the paired AP difference (GNN minus text), with 1,000 replicates.

| Text baseline | GNN AP | Text AP | Paired AP difference (project-cluster 95% CI) | GNN ROC-AUC | Text ROC-AUC |
|---|---:|---:|---:|---:|---:|
| Length only | 0.108 | 0.120 | −0.013 (−0.031–0.009) | 0.710 | 0.738 |
| TF-IDF logistic regression | 0.108 | 0.105 | +0.002 (−0.010–0.015) | 0.710 | 0.738 |
| Identifier-masked TF-IDF | 0.108 | 0.120 | −0.013 (−0.029–0.003) | 0.710 | 0.741 |

The AP differences are small and each interval includes zero; the saved result does not establish a graph-model advantage. ROC-AUC is higher for the legacy text baselines. These text scores come from the older baseline artifact, not the later validation-tuned v2 suite in the main baseline table. Reproduce with `python scripts/evaluate_matched_baseline_comparison.py`; output: `results/gnn/joern_type_only/cross/matched_baseline_comparison_seed42.csv`. The Research page displays this same-cohort comparison separately from the full-cohort v2 baseline table.

## Relation ablations

One seed (42), same cross-project split and baseline hyperparameters, with each edge relation removed in turn. Intervals overlap; this single-seed study does not establish that one relation is better.

| Condition | Test AP (project-cluster 95% CI) | ROC-AUC | Precision | Recall | Best validation AP (epoch) |
|---|---:|---:|---:|---:|---:|
| All relations | 0.108 (0.076–0.137) | 0.710 | 0.136 | 0.356 | 0.122 (9) |
| Without AST | 0.118 (0.081–0.158) | 0.708 | 0.128 | 0.351 | 0.127 (8) |
| Without CFG | 0.109 (0.081–0.139) | 0.717 | 0.137 | 0.318 | 0.111 (1) |
| Without reaching definition | 0.105 (0.077–0.133) | 0.719 | 0.136 | 0.287 | 0.114 (1) |
| Without CDG | 0.113 (0.080–0.143) | 0.709 | 0.125 | 0.387 | 0.130 (17) |

Saved summary: results/gnn/joern_type_only/cross/edge_ablation_summary.csv. Each run selected its best epoch on validation and evaluated the same held-out test cohort.

## Precision target transfer

For each of three cross-project checkpoints, thresholds targeting 50% and 60% precision were chosen using validation only. On held-out projects, test precision ranged from 0.000 to 0.179 and recall from 0.000 to 0.008. A high validation precision threshold did not transfer to new projects and produced almost no test coverage. The current model does not meet a 50–60% test precision goal.

Saved per-seed values: results/precision_operating_points/cross_precision_operating_points.csv. The Research page displays validation and held-out values side by side.

## Changed-line localization proxy

For the 917 vulnerable functions in the held-out cross-project test, absolute gradient×input scores from the seed-42 all-edge R-GCN were summed by Joern source line and ranked. The target set is the changed-line region from each BigVul func_before/func_after diff. This is a patch-overlap proxy, not ground-truth vulnerability line annotation.

| Ranked lines | Hit rate | Project-cluster 95% CI | Exact random-line expected |
|---:|---:|---:|---:|
| Top 1 | 0.189 | 0.157–0.235 | 0.108 |
| Top 3 | 0.344 | 0.294–0.391 | 0.234 |
| Top 5 | 0.435 | 0.389–0.506 | 0.321 |

Line mapping coverage was 100% for these 917 graphs. Results are preliminary; they show overlap with fix edits, not verified localization of the vulnerability itself. Reproduction: scripts/evaluate_line_localization.py. Results: results/line_localization/cross_seed42_line_localization.json and .csv.

## Local demo

The cream-and-olive website provides Overview, Research, Graph explorer, and Analysis preview pages. The Research API reads saved baseline, GNN, matched-cohort, precision-transfer, and localization results. Local C/C++ analysis uses Joern and the type-only R-GCN checkpoint when those local artifacts are present. Output scores are uncalibrated research signals, not security verdicts.

Start from the repo root with the Windows GPU environment:
powershell
$env:PYTHONPATH = (Resolve-Path .\src).Path
.\.venv-gpu\Scripts\python.exe .\scripts\serve_web.py --host 127.0.0.1 --port 8000

## Remaining work

- CodeBERT feature generation is blocked by Windows App Control denying the Transformers regex native extension. No security policy was changed.
- A gradient-based patch-overlap localization proxy is measured; it does not validate vulnerability-line accuracy. Compare against manually verified line labels before making stronger localization claims.
- More seeds and independently tuned ablations are needed before drawing conclusions about edge relations.
- The GitHub clone excludes local data, Joern binaries, environments, checkpoints, and prediction tables; see LOCAL_ARTIFACTS.md. Ragini needs GitHub access to the private repository and local runtime artifacts for the source-analysis route.
