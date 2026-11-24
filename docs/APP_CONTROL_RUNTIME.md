# CodeBERT runtime status

## Current status (24 November 2026)

The historical block below is not present in the current Code Integrity Operational log. In the project GPU environment, `regex` 2026.11.15 and `transformers` 5.23.0 now import, including the native `_regex.cp313-win_amd64.pyd` extension. A raw CodeBERT smoke run loaded `microsoft/codebert-base` on CUDA and converted 12 train/train graphs (834 nodes) to `torch.float16` features of shape `(10, 784)` for the first graph: 16 node-type features plus 768 CodeBERT dimensions. No App Control policy was changed during this run.

Full raw and masked feature extraction, CodeBERT R-GCN tuning/training, and UI wiring have not been performed. Check free disk space before building the full corpus.

## Historical App Control event (17 November 2026)

The initial CodeBERT feature build stopped while Transformers imported an unsigned native dependency. Windows Code Integrity recorded an enforced App Control block for:

- Event: Code Integrity Operational, ID 3077, 17 November 2026 01:33:20
- Policy ID: `{0283ac0f-fff1-49ae-ada1-8a933130cad6}`
- Python: `C:\Users\jaiag\AppData\Local\Programs\Python\Python313\python.exe`
- Blocked file: `D:\GNN_Project_Ragini\.venv-gpu\Lib\site-packages\regex\_regex.cp313-win_amd64.pyd`
- File SHA-256: `ba577158c33beb9807d7f9a22b6881a1a4fa701a135cea6f99f655ebd8404105`
- Package: `regex`, required by `transformers 5.23.0`
- Authenticode: the individual extension is unsigned

An earlier PyTorch block (event 3077, 16 November 2026 17:40:47) named `torch\\lib\\caffe2_nvrtc.dll`, SHA-256 `0cf443f6d00c9a763f5aa324ee431c0892800237027b832173cbeb52925aff15`. PyTorch subsequently began loading and CUDA initialization succeeded; this earlier file is no longer the current blocker.

At the time, the recommended next step was to review the exact event and decide whether to create a narrow approval. The current import and smoke test pass, so do not add a policy rule unless a fresh block event occurs. Other native extensions may still be evaluated; review each new event rather than adding a broad path exception.

This is the current known local barrier to CodeBERT feature generation and R-GCN training. Microsoft documents event 3077 and the admin review process in the [App Control troubleshooting guide](https://learn.microsoft.com/windows/security/application-security/application-control/app-control-for-business/operations/appcontrol-debugging-and-troubleshooting).
