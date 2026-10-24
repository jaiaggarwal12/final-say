# Design decisions

- Language scope: C/C++ only (BigVul; Joern's C frontend is the most mature).
- Split by project, not by function, to prevent near-duplicate leakage.
- Hyperparameters tuned only on a validation split that is also project-disjoint from test.
- Dataset is 98.6% C (185,997 of 188,636 functions); claims are about C, not C/C++.
- file_name is mostly missing, so within-project grouping uses (project, function name).
- Normalized-exact duplicates: dropped all groups with conflicting labels; kept one copy of consistent groups (global, so no exact copy crosses splits).
- Dropped vulnerable rows whose fix changes only comments/whitespace; dropped functions over 8,000 chars (loses ~6% of positives).
- Cross-project split: Chrome, linux, Android and hosting-site pseudo-projects are train-only; val/test projects drawn by seeded shuffle (seed 42), not hand-picked.
- Data source: BigVul (Fan et al., MSR 2020), original zip as mirrored at huggingface.co/datasets/starsofchance/MSR_data_cleaned; SHA-256 verified.
- Dataset is 98.6% C (185,997 of 188,636 functions); claims are about C, not C/C++.
- file_name is mostly missing, so within-project grouping uses (project, function name).
- Normalized-exact duplicates: dropped groups with conflicting labels; kept one copy of consistent groups (global, so no exact copy crosses splits).
- Dropped vulnerable rows whose fix changes only comments/whitespace; dropped functions over 8,000 chars.
- Cross-project split: Chrome, linux, Android and hosting-site pseudo-projects are train-only; val/test projects drawn by seeded shuffle (seed 42), not hand-picked.
- Cross-project val/test rows flagged by the near-duplicate check (near_dup_cross) are excluded from evaluation; the flag stays in the parquet.
- Joern pilot: 60 sampled functions parsed as one folder, exported as neo4jcsv (--repr all); a function's graph is the AST subtree of its METHOD node plus all edges inside it; each graph maps back to its .c file via the uid in the file name, which is also stored in the graph JSON.
