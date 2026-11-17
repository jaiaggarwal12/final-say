# GNN-Based Source Code Vulnerability Detection with Localization

**Progress report — 17 November 2026.** Full-scale Joern extraction is complete, and one seed-42 type-only R-GCN has been trained and tested on the cross-project split using the local RTX 4060. This remains a preliminary result: CodeBERT features, within-project GNN evaluation, multi-seed comparison, edge ablations, and localization are still pending. Windows App Control blocks the Transformers `regex` extension; details are recorded in `docs/APP_CONTROL_RUNTIME.md`.

## Research question

Does code-property-graph structure help vulnerability detection generalize to projects that were not seen during training, especially after function identifiers are abstracted away?

## Data and evaluation

The cleaned BigVul data contains 182,100 C/C++ functions from 295 merged projects, including 8,609 vulnerable functions (4.73%). The dataset's language field is unreliable, so Joern input extensions are selected from code syntax. The within-project split groups by project and function name. The cross-project split holds out entire projects and excludes rows flagged as near duplicates from evaluation. Thresholds and model choices use validation data only.

The cleaning process removes no-op fixes, conflicting-label groups, redundant duplicates, and functions longer than 8,000 characters. This removes a material share of vulnerable examples; labels remain noisy because the data is derived from vulnerability-fix commits.

## Baseline results

All text results below are single-seed test metrics. C and F1 thresholds are selected on validation only. AP intervals use cluster-bootstrap resampling: whole projects for cross-project and whole function groups for within-project. Row-level intervals are optimistic and retained for comparison in `results/bootstrap_ci_comparison.csv`.

| Split | Model | Variant | AP (cluster 95% CI) | Precision at 30% recall | F1 |
|---|---|---|---:|---:|---:|
| Within | Length | chars/lines | 0.114 (0.102–0.131) | 0.132 | 0.179 |
| Within | TF-IDF + logistic regression | Raw tokens | 0.356 (0.317–0.400) | 0.497 | 0.394 |
| Within | TF-IDF + logistic regression | API-preserving mask | 0.147 (0.127–0.168) | 0.173 | 0.220 |
| Within | TF-IDF + logistic regression | Fully masked | 0.143 (0.125–0.164) | 0.168 | 0.221 |
| Cross | Length | chars/lines | 0.117 (0.089–0.143) | 0.144 | 0.201 |
| Cross | TF-IDF + logistic regression | Raw tokens | 0.105 (0.084–0.129) | 0.132 | 0.186 |
| Cross | TF-IDF + logistic regression | API-preserving mask | 0.122 (0.094–0.157) | 0.160 | 0.204 |
| Cross | TF-IDF + logistic regression | Fully masked | 0.124 (0.097–0.158) | 0.161 | 0.209 |

## Preliminary graph-model results: node-type-only R-GCN

Seed-42 R-GCN runs use one-hot Joern node types and AST, CFG, reaching-definition, and control-dependence edges. They contain no code-text embeddings. The within run selected hyperparameters on its own validation set (five Optuna trials); the cross run selected on cross-project validation (one completed trial). Thresholds were selected on each setting's validation data. Test metrics use cluster-bootstrap confidence intervals over projects for cross-project and function groups for within-project.

| Split | Test N | Positives | AP (cluster 95% CI) | ROC-AUC | F1 | Threshold | Best validation AP (epoch) |
|---|---:|---:|---:|---:|---:|---:|---:|
| Within project | 16,631 | 776 | 0.130 (0.109–0.159) | 0.727 | 0.202 | 0.769 | 0.134 (14) |
| Cross project | 20,957 | 917 | 0.108 (0.076–0.137) | 0.710 | 0.196 | 0.799 | 0.122 (9) |

These are uncalibrated, single-seed estimates; they are not CodeBERT results or a claim of superiority over text baselines. A split-overlap audit found 833 within-test UIDs also appeared in cross-validation. The first within run used cross-selected hyperparameters and is retained as an exploratory artifact only; the reported within result is a fresh fit after five-trial within-validation tuning. The graph test cohorts contain only successful Joern parses and differ from the text-baseline cohort; the two split settings also share some test functions and should not be compared as paired estimates. Detailed metrics, score files, and per-project rows are under `results/gnn/joern_type_only/`.

For raw tokens, validation selected C=10.0 within-project and C=0.03 cross-project. The earlier single-mask run in `results/baseline_results.csv` gives 0.356 to 0.141 AP within-project and 0.105 to 0.121 cross-project. Its cross-project row-level intervals overlap for raw text (0.097–0.117), the masked model (0.111–0.136), and length-only (0.106–0.131); those intervals are optimistic. The newer masked variants above use cluster intervals. These results are consistent with identifier sensitivity but do not prove that project-vocabulary memorization causes the cross-project collapse.

## Semgrep baseline

Semgrep Community Edition 1.185.0 ran the frozen `p/c` snapshot with two upstream C rules and two derived C++ copies (effective ruleset SHA-256 `a936fb1c81084c67f6b0a988fd61f26824e3b3ffd7df6ec369b246300a985660`). It scanned all 18,211 within-project and 23,867 eligible cross-project test snippets and produced zero alerts. There were 68 and 167 parse warnings, respectively, and no timeouts or crashes. This four-rule baseline has narrow coverage. With zero recall, a matched-recall comparison to a nonzero-recall model is not possible.

## Cppcheck baseline

Cppcheck 2.22.0 scanned the same eligible test rows, one snippet per process, with a two-second per-file timeout. The fixed operating point flags any warning- or error-severity finding; syntax-error diagnostics have error severity and therefore count as flags as well as parse failures. Timed-out and crashed files would be unflagged; there were none. Results are in `results/cppcheck/full/metrics.csv` and `results/baselines_v2.csv`.

| Split | Test functions | AP (cluster 95% CI) | Flagged | Parse failures | Timeouts | Crashes | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Within-project | 18,211 | 0.051 (0.047–0.055) | 1,113 | 359 | 0 | 0 | 0.0800 | 0.1034 | 0.0902 |
| Cross-project | 23,867 | 0.051 (0.041–0.062) | 2,053 | 213 | 0 | 0 | 0.0828 | 0.1605 | 0.1093 |

Precision is low at this fixed operating point, and parser diagnostics may contribute false alerts. Treat this as a narrow snippet-based static-analysis result, not a complete security audit.

## Graph pipeline status

The 60-function Joern pilot produced 57 graphs (95%); the three failures had no matching method. The full deterministic workset contained 117,673 functions. Joern produced 107,461 graphs (91.32%): 99,739 of 109,064 safe functions and 7,722 of 8,609 vulnerable functions. The independent audit accounted for every planned function and reported zero errors or batch errors. There were 1,682 truncated graphs. The complete checkpoint archive is `results/graphs_full_2026-11-16.tar.gz` (334,855,059 bytes), with a SHA-256 sidecar. Full extraction was performed locally on Windows using Joern 4.0.683 and Java 21.0.13.

The type-only PyTorch Geometric shards and one trained cross-project R-GCN checkpoint now exist. PyTorch/CUDA and the RTX 4060 work. CodeBERT feature generation remains blocked because Windows App Control denies `regex._regex.cp313-win_amd64.pyd`; no policy was changed. The local API now extracts a source graph with Joern and returns a model score from the type-only checkpoint. Localization results have not been measured.

## Next work

1. Run the type-only within-project split, then cross-project additional seeds and edge-relation ablations; report confidence intervals without tuning on test data.
2. Obtain an approved deployment/allowance for the blocked Transformers native extension, then build raw-token and identifier-masked CodeBERT shards.
3. Evaluate text-plus-graph R-GCNs on identical successful-graph cohorts and compare with the TF-IDF baselines.
4. Measure top-1/3/5 changed-line localization against a random-lines baseline, then replace this progress report with final results and limitations.
