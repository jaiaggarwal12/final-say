# Design decisions

- Language scope: C/C++ only (BigVul; Joern's C frontend is the most mature).
- Split by project, not by function, to prevent near-duplicate leakage.
- Hyperparameters tuned only on a validation split that is also project-disjoint from test.
