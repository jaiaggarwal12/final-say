# Remaining transfer items

Already synchronized locally:
- GitHub source through d540a8ed40952df279ec5e7dd0a7f44f12280994.
- Raw BigVul ZIP downloaded from the README Hugging Face mirror and SHA-256 verified.
- Extracted 10.8 GB BigVul CSV in data/raw/.

Still missing or pending:
- Rebuild interim/processed Parquet using an allowed runtime; Windows App Control blocked NumPy's native DLL and WSL access was denied.
- Joern (3.5 GiB on Mac) can be reinstalled from its GitHub releases with the platform appropriate package.
- Remaining 159 MiB Mac result artifacts await a read-only safety audit. Public upload was rejected by automatic review pending proof/authorization.
- The 64 MB prefix-10 Kaggle checkpoint was not found locally or in the current Kaggle output panel. The 12 MB batch-00000 checkpoint remains in the Mac-only handoff bundle at /private/tmp/vulngnn-handoff-context-2026-11-16.tar; it is not yet on this laptop.
- The Mac .venv is not copied; recreate after resolving the Windows runtime policy.

Avoid committing credentials, local environments, or large redundant datasets to the public repository.
