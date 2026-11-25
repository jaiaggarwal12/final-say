# Upload-analysis demo files

Upload these one at a time at `http://127.0.0.1:8000/analyze`. They are deliberately vulnerable teaching examples; do not copy their unsafe patterns into real code. Findings are review prompts, not proof that a real application is exploitable.

## What each file demonstrates

| File | Intended issue | Observed result in the current local app |
|---|---|---|
| `01_unbounded_strcpy.c` | Unbounded copy into a fixed buffer | Built-in CWE-120 review prompt at line 6 |
| `02_unbounded_scanf.c` | Unbounded `%s` input | Built-in CWE-120 at line 6; Cppcheck `invalidscanf` (CWE-119) at line 6 |
| `03_shell_command_injection.c` | Untrusted text passed through a shell | Built-in CWE-78 review prompt at line 8 |
| `04_gets_no_length_limit.c` | `gets` cannot enforce destination capacity | Built-in CWE-242 and Cppcheck `getsCalled` (CWE-477), both at line 6 |
| `05_out_of_bounds_array.c` | Read beyond a fixed array | Cppcheck `arrayIndexOutOfBounds` (CWE-788) at line 4 |

## Honest demo framing

These examples show specific checks catching specific risky patterns. The experimental R-GCN said “not flagged” on all five in the verification run; its displayed scores are uncalibrated and may vary with runtime artifacts. Say that the demo combines narrow static checks with a research model, and that it is not a reliable or complete security scanner. A “no findings” result never proves code is safe.
