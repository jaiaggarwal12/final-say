# GNN-Based Source Code Vulnerability Detection with Localization

**Progress report — 14 November 2026.** This is a measured project update, not the final model report: full-scale Joern extraction, GNN training, and localization have not run.

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

The 60-function Joern pilot produced 57 graphs (95%); the three failures had no matching method. The pilot graph and manifest CSVs record the sample and graph statistics. The repository contains prepared workset, Joern-runner, audit, PyG-feature, R-GCN training, comparison, and localization code, but full-scale graph extraction, CodeBERT feature generation, GNN training, and localization have not produced results.

## Next work

1. Run the Joern workset and audit coverage by class, split, and project, plus graph consistency and truncation counts.
2. Build raw-identifier and identifier-masked CodeBERT feature shards.
3. Tune on validation, then report both split settings over at least three seeds with project-cluster confidence intervals.
4. Compare on the exact rows with successful graphs and report Semgrep at its fixed operating point.
5. Measure top-1/3/5 changed-line localization against the random-lines baseline, then replace this progress report with the final results and limitations.
