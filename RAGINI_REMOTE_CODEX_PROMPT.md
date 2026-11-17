# Ragini: Mac project handoff (paste into Codex)

You are continuing the VulnGNN research project on Ragini's Mac. The authoritative new source repository should be the user's newly created **private GitHub repository**. The clone URL is not yet known; replace `https://github.com/jaiaggarwal12/final-say.git` with the URL the user provides. Do not use or push to `https://github.com/raginikalra21/gnn-vulnerability-detection.git` unless the user explicitly says that is the intended repository.

## Goal

Bring the Mac checkout up to date with the Windows work, preserve any Mac-only source changes and local research data, get the website and inference demo running, then report exactly what works and what remains.

## Rules for preserving Ragini's Mac work

1. Start by inspecting the Mac: `pwd`, `git status --short --branch`, `git remote -v`, `git log -5 --oneline`, disk space, available Python/Joern versions, and whether the GPU backend is Apple Silicon/MPS or CPU. Do not print tokens, `.env` values, or credential files.
2. Do not overwrite, reset, clean, delete, or reinitialize Ragini's existing checkout. Do not run `git reset --hard`, `git clean`, or destructive `rsync --delete`.
3. Clone the private repo into a new sibling folder first. Authenticate with the Mac user's existing Git credential helper; never ask them to paste a password/token into chat.
4. Compare the cloned repository with the old Mac checkout. Preserve uncommitted changes and any Mac-only commits by saving a patch/branch or copying only after reviewing the diff. Keep the original checkout intact as a backup.
5. Preserve local data and ignored artifacts. Do not upload datasets, virtual environments, private keys, `.env` files, cached downloads, or model checkpoints unless they are explicitly tracked and the user specifically approves. Check `.gitignore`, `git status --ignored`, and `git ls-files` before copying.
6. Never claim the model is a production vulnerability detector. This is a research prototype; scores are ranking signals and are not calibrated findings.

## Set up the clean clone

Use terminal Git:

```bash
git clone https://github.com/jaiaggarwal12/final-say.git vulngnn-handoff
cd vulngnn-handoff
git status --short --branch
git log -1 --oneline
```

Read `README.md`, `HANDOFF.md`, `TRANSFER_FROM_MAC.md`, `docs/short_report.md`, `docs/APP_CONTROL_RUNTIME.md`, and the repo's dependency files before changing anything. Check all scripts and paths for Windows-only assumptions (`D:\...`, PowerShell, `.venv-gpu`, Joern executable paths). Keep Mac changes in a branch named `ragini/mac-handoff` and commit only after showing the diff.

## Data and environment

- First check whether the project data / graph cache already exists on the Mac and whether its manifest/checksums match the repo documentation. Reuse it if valid.
- If large data is absent, identify the exact dataset files and their original source and size before downloading. Do not start a multi-gigabyte download without confirming free disk space and expected storage.
- Create a project-local Python environment using the version supported by the dependency files. Install documented requirements; do not install or bypass OS security controls or Gatekeeper. If a package is blocked, record the exact error and use an approved package source.
- Detect Apple Silicon and use a compatible PyTorch MPS build if available; otherwise use CPU. Do not assume CUDA works on a Mac.
- Locate the installed Joern distribution using documented install paths or `PATH`. Do not silently switch CPG frontend/parser semantics; make a clear note if the Mac uses a different frontend.

## Run the app

Follow the documented entry point in `README.md` / `HANDOFF.md`. Start the web server on localhost only, then verify:

- overview page loads;
- graph explorer loads a real stored graph;
- research metrics show the documented completed runs;
- analysis preview accepts a small C/C++ example and returns a score plus graph details;
- terminal logs contain no hidden dependency or model-loading failure.

Use a harmless toy function for the live inference demonstration. Report the returned score as an uncalibrated research score, not as a confirmed vulnerability. If any component cannot run, capture the precise command and error and leave the source/data intact.

## Validate and sync

Run only the validation commands documented by the repository. Check `git diff --check`, inspect `git status --short`, and summarize changes before committing. Do not rewrite research results or claim that Windows GPU metrics were reproduced on Mac.

If Mac-specific fixes are needed, commit them on `ragini/mac-handoff`, then push that branch to the private repo only after showing the diff and confirming no dataset, checkpoint, secret, or environment directory is included. Keep the Mac's original checkout untouched until the user confirms the new clone is fully usable.

## Expected final report to the user

Provide: (1) clone path and branch/commit, (2) environment and hardware backend, (3) data reused/downloaded and storage used, (4) exact local URL and the pages/features verified, (5) demo inference result and its limitations, (6) files changed and commits pushed, (7) remaining blockers with exact errors, and (8) whether the old Mac checkout remains preserved.

Do not contact anyone or send messages. Work only on the Mac and repository state the user has authorized.

