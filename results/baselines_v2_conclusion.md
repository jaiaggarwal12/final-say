**Supported by these measurements**
- Raw TF-IDF AP is 0.356 within projects and 0.105 across projects (cross prevalence 0.044).
- Cross-project AP is 2.4x prevalence for raw tokens; identifier masking changes it to 0.122 with API names kept and 0.124 when all identifiers are masked.
- Semgrep produced zero alerts; Cppcheck warning/error recall was 10.3% within and 16.1% cross at 8.0%/8.3% precision, with parser failures reported separately.
**Not established by these measurements**
- The masking comparison does not prove project-vocabulary memorization is the cause; tokenization changes multiple correlated signals and this is one seed.
- These text and static-analysis results do not establish that graph structure generalizes better; that requires held-out-project GNN results.
