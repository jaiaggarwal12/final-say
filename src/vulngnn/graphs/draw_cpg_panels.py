"""Draw one function's graph as three readable panels: syntax, control flow, data flow."""
import json
import re
import subprocess
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.image as mpimg
import matplotlib.pyplot as plt

def main():
    UID = sys.argv[1] if len(sys.argv) > 1 else "f_27e220ebcb5a"
    RES = Path("results/pilot")
    g = json.loads(Path(f"data/pilot/graphs/{UID}.json").read_text())
    nd = {n["id"]: n for n in g["nodes"]}
    kind = "vulnerable" if g["label"] == 1 else "safe"
    NOISY = {"METHOD_RETURN", "METHOD_PARAMETER_OUT", "METHOD_PARAMETER_IN"}
    SIMPLE = re.compile(r"^[A-Za-z_]\w*$")


    def short(s, n=30):
        s = " ".join(s.split())
        return s if len(s) <= n else s[: n - 3] + "..."


    def esc(s):
        return s.replace("\\", "\\\\").replace('"', '\\"')


    def edges_of(t):
        seen, out = set(), []
        for e in g["edges"]:
            key = (e["src"], e["dst"], e["variable"])
            if e["type"] == t and e["src"] != e["dst"] and key not in seen:
                seen.add(key)
                out.append(e)
        return out


    def clean(e):
        return nd[e["src"]]["label"] not in NOISY and nd[e["dst"]]["label"] not in NOISY


    ast, cfg = edges_of("AST"), edges_of("CFG")
    flow = [e for e in edges_of("REACHING_DEF") if clean(e) and SIMPLE.match(e["variable"])]
    if not flow:  # fallback: keep every data-flow edge between ordinary nodes
        flow = [e for e in edges_of("REACHING_DEF") if clean(e)]


    def render(name, title, edge_list, color, extra, labels):
        used = sorted({x for e in edge_list for x in (e["src"], e["dst"])})
        lines = ["digraph G {", f'  labelloc=t; fontsize=20; label="{esc(title)}";',
                 "  rankdir=TB; nodesep=0.3; ranksep=0.45;",
                 '  node [shape=box, style="rounded,filled", fillcolor="#f1f3f4", '
                 'fontname="Helvetica", fontsize=11];',
                 '  edge [fontname="Helvetica", fontsize=9];']
        for i in used:
            n = nd[i]
            lines.append(f'  n{i} [label="{esc(n["label"])}\\nL{n["line"]}: {esc(short(n["code"]))}"];')
        for e in edge_list:
            lab = f', label="{esc(e["variable"])}", fontcolor="{color}"' if labels else ""
            lines.append(f'  n{e["src"]} -> n{e["dst"]} [color="{color}"{extra}{lab}];')
        lines.append("}")
        dot, png = RES / f"cpg_{name}.dot", RES / f"cpg_{name}.png"
        dot.write_text("\n".join(lines))
        subprocess.run(["dot", "-Tpng", "-Gdpi=110", str(dot), "-o", str(png)], check=True)
        print(f"{name}: {len(used)} nodes, {len(edge_list)} edges")
        return png


    pngs = [
        render("ast", "Syntax: AST (parent to child)", ast, "#5f6368", "", False),
        render("cfg", "Control flow: CFG (runs before)", cfg, "#1a73e8", ", penwidth=1.6", False),
        render("dataflow", "Data flow: REACHING_DEF (variable on edge)", flow, "#d93025",
               ", style=dashed", True),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(24, 9))
    for ax, png in zip(axes, pngs):
        ax.imshow(mpimg.imread(png))
        ax.axis("off")
    fig.suptitle(f"{UID} ({kind}, {g['project']}, {g['cve']}): one function, three views "
                 "of its code property graph", fontsize=16)
    plt.tight_layout()
    plt.savefig(RES / "cpg_panels.png", dpi=150)
    print("saved results/pilot/cpg_panels.png")


if __name__ == "__main__":
    main()
