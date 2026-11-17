# Request for an approved PyTorch runtime

PyTorch now imports successfully and CUDA sees the RTX 4060. The first CodeBERT feature build stopped while Transformers imported an unsigned native dependency. Windows Code Integrity recorded an enforced App Control block for:

- Event: Code Integrity Operational, ID 3077, 17 November 2026 01:33:20
- Policy ID: `{0283ac0f-fff1-49ae-ada1-8a933130cad6}`
- Python: `C:\Users\jaiag\AppData\Local\Programs\Python\Python313\python.exe`
- Blocked file: `D:\GNN_Project_Ragini\.venv-gpu\Lib\site-packages\regex\_regex.cp313-win_amd64.pyd`
- File SHA-256: `ba577158c33beb9807d7f9a22b6881a1a4fa701a135cea6f99f655ebd8404105`
- Package: `regex`, required by `transformers 5.23.0`
- Authenticode: the individual extension is unsigned

An earlier PyTorch block (event 3077, 16 November 2026 17:40:47) named `torch\\lib\\caffe2_nvrtc.dll`, SHA-256 `0cf443f6d00c9a763f5aa324ee431c0892800237027b832173cbeb52925aff15`. PyTorch subsequently began loading and CUDA initialization succeeded; this earlier file is no longer the current blocker.

Please review the Code Integrity event and decide whether to approve this exact dependency under the device's managed policy, use an approved managed deployment, or provide another approved GPU runtime. Keep the existing policy enforced; do not disable App Control or create a broad path-based exception. Other native Python extensions may also be evaluated; review each block event rather than allowing an entire Python site-packages tree.

This is the current known local barrier to CodeBERT feature generation and R-GCN training. Microsoft documents event 3077 and the admin review process in the [App Control troubleshooting guide](https://learn.microsoft.com/windows/security/application-security/application-control/app-control-for-business/operations/appcontrol-debugging-and-troubleshooting).
