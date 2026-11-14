"""Turn Joern's neo4jcsv export into one graph per function, map each back to its
dataset row and label, and draw one example."""
import json
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

PILOT = Path("data/pilot")
EXPORT = PILOT / "export"
GRAPHS = PILOT / "graphs"
RES = Path("results/pilot")


def clean(c):
    c = c.strip().strip('"')
    return c if c.startswith(":") else c.split(":")[0]


def read_group(kind):
    frames = []
    for h in sorted(EXPORT.glob(f"{kind}_*_header.csv")):
        d = h.with_name(h.name.replace("_header.csv", "_data.csv"))
        if not d.exists():
            continue
        cols = [clean(c) for c in h.read_text().strip().split(",")]
        try:
            df = pd.read_csv(d, header=None, names=cols, index_col=False,
                             dtype=str, keep_default_na=False)
        except pd.errors.EmptyDataError:
            continue
        df["_group"] = h.name[len(kind) + 1:-len("_header.csv")]
        frames.append(df)
    if not frames:  # fallback: one CSV per group with an inline header
        for f in sorted(EXPORT.glob(f"{kind}_*.csv")):
            df = pd.read_csv(f, dtype=str, keep_default_na=False)
            df.columns = [clean(c) for c in df.columns]
            df["_group"] = f.stem[len(kind) + 1:]
            frames.append(df)
    return pd.concat(frames, ignore_index=True).fillna("") if frames else pd.DataFrame()


def col(df, name):
    return df[name] if name in df else pd.Series("", index=df.index)


def pick(df, name):
    return df[name].where(df[name] != "", df["_group"]) if name in df else df["_group"]


def main():
    GRAPHS.mkdir(parents=True, exist_ok=True)
    RES.mkdir(parents=True, exist_ok=True)
    nodes, edges = read_group("nodes"), read_group("edges")
    if nodes.empty or edges.empty:
        print(f"Could not read the Joern export in {EXPORT}. Files found:")
        for p in sorted(EXPORT.iterdir())[:40]:
            print("  ", p.name)
        sys.exit(1)
    print("node columns:", list(nodes.columns)[:14])
    print("edge columns:", list(edges.columns))
    if ":ID" not in nodes or not {":START_ID", ":END_ID"} <= set(edges.columns):
        print("Unexpected column names; send me the two lines printed above.")
        sys.exit(1)

    nodes["label"] = pick(nodes, ":LABEL")
    edges["etype"] = pick(edges, ":TYPE")
    nodes = nodes.rename(columns={":ID": "id"}).drop_duplicates("id")
    edges = edges.rename(columns={":START_ID": "s", ":END_ID": "e"})
    rows = nodes.set_index("id").to_dict("index")
    var_col = next((c for c in edges.columns if c.lower() == "variable"), None)

    counts = Counter(edges["etype"])
    print("\nedge types in the whole export:", dict(counts.most_common(12)))
    if counts.get("REACHING_DEF", 0) == 0:
        print("WARNING: no REACHING_DEF (data-flow) edges found. Tell me; there is a fallback.")

    children = defaultdict(list)
    for s, e in zip(edges.loc[edges["etype"] == "AST", "s"], edges.loc[edges["etype"] == "AST", "e"]):
        children[s].append(e)


    def subtree(root):
        seen, stack = {root}, [root]
        while stack:
            for c in children.get(stack.pop(), []):
                if c not in seen:
                    seen.add(c)
                    stack.append(c)
        return seen


    is_ext = col(nodes, "IS_EXTERNAL").str.lower() == "true"
    methods = nodes[(nodes["label"] == "METHOD") & ~is_ext & (col(nodes, "NAME") != "<global>")]

    man = pd.read_csv(PILOT / "manifest.csv")
    records, graphs = [], {}
    for _, m in man.iterrows():
        uid = m["uid"]
        rec = {"uid": uid, "ext": m["ext"], "label": int(m["vul"]), "project": m["project_g"], "cve": m["CVE ID"],
               "cwe": m["CWE ID"], "chars": int(m["chars"]), "status": "no_method", "method": "",
               "nodes": 0, "edges": 0, "AST": 0, "CFG": 0, "REACHING_DEF": 0, "CDG": 0}
        cand = methods[col(methods, "FILENAME").str.contains(uid, regex=False)]
        if len(cand):
            best = max(cand["id"], key=lambda i: len(subtree(i)))
            S = subtree(best)
            sub = edges[edges["s"].isin(S) & edges["e"].isin(S)]
            node_list = [{"id": i, "label": rows[i]["label"], "code": rows[i].get("CODE", "")[:200],
                          "line": rows[i].get("LINE_NUMBER", ""), "name": rows[i].get("NAME", "")}
                         for i in S if i in rows]
            ids = {n["id"] for n in node_list}
            edge_list = [{"src": s, "dst": e, "type": t, "variable": (v if var_col else "")}
                         for s, e, t, v in zip(sub["s"], sub["e"], sub["etype"],
                                               sub[var_col] if var_col else [""] * len(sub))
                         if s in ids and e in ids]
            by_type = Counter(e["type"] for e in edge_list)
            rec.update(status="ok", method=rows[best].get("NAME", ""), nodes=len(node_list),
                       edges=len(edge_list), AST=by_type["AST"], CFG=by_type["CFG"],
                       REACHING_DEF=by_type["REACHING_DEF"], CDG=by_type["CDG"])
            graphs[uid] = {"uid": uid, "source_file": f"{uid}{m['ext']}", "label": rec["label"],
                           "project": rec["project"], "commit_id": m["commit_id"], "cve": rec["cve"],
                           "cwe": rec["cwe"], "norm_hash": m["norm_hash"], "method": rec["method"],
                           "nodes": node_list, "edges": edge_list}
            (GRAPHS / f"{uid}.json").write_text(json.dumps(graphs[uid]))
        records.append(rec)

    stats = pd.DataFrame(records)
    stats.to_csv(RES / "pilot_graph_stats.csv", index=False)
    ok = stats[stats["status"] == "ok"]
    print(f"\nfunctions in manifest: {len(stats)} | graphs extracted: {len(ok)} ({len(ok) / len(stats):.0%})")
    if len(ok) == 0:
        print("No graphs extracted; send me the output above.")
        sys.exit(1)
    print("\nper-class graph size (label 1 = vulnerable):")
    print(ok.groupby("label")[["nodes", "edges", "AST", "CFG", "REACHING_DEF", "CDG"]]
          .agg(["mean", "median"]).round(1).T)
    failed = stats.loc[stats["status"] != "ok", "uid"].tolist()
    print("failed to map to a method:", failed if failed else "none")

    print("\nmapping evidence (graph -> source file -> label):")
    for _, r in ok.sample(min(3, len(ok)), random_state=1).iterrows():
        print(f"  {r.uid}.json <- {r.uid}{r.ext} | label={r.label} | {r.project} | {r.cve} | "
              f"method={r.method} | {r.nodes} nodes, {r.edges} edges")

    # ---- one worked example: examples of each relationship type, plus a picture ----
    cand = ok[(ok["label"] == 1) & (ok["REACHING_DEF"] > 0) & ok["nodes"].between(20, 80)]
    if cand.empty:
        cand = ok[ok["nodes"].between(10, 100)]
    if cand.empty:
        cand = ok
    ex = cand.iloc[(cand["nodes"] - 40).abs().argsort().iloc[0]]
    g = graphs[ex["uid"]]
    nd = {n["id"]: n for n in g["nodes"]}
    kind = "vulnerable" if ex["label"] == 1 else "safe"


    def short(s, n=38):
        s = " ".join(s.split())
        return s if len(s) <= n else s[: n - 3] + "..."


    def esc(s):
        return s.replace("\\", "\\\\").replace('"', '\\"')


    def desc(i):
        n = nd[i]
        return "L{} {} `{}`".format(n["line"], n["label"], short(n["code"], 60))


    out = [f"Example graph {ex['uid']} ({kind}, project={ex['project']}, {ex['cve']})",
           f"nodes={ex['nodes']} edges={ex['edges']}", ""]
    for t, title in [("AST", "SYNTAX (AST: parent -> child)"),
                     ("CFG", "CONTROL FLOW (CFG: runs before)"),
                     ("REACHING_DEF", "DATA FLOW (REACHING_DEF: a definition reaches a use)")]:
        out.append(title)
        for e in [e for e in g["edges"] if e["type"] == t][:8]:
            v = f"   [variable: {e['variable']}]" if e["variable"] else ""
            out.append(f"  {desc(e['src'])}  ->  {desc(e['dst'])}{v}")
        out.append("")
    (RES / "example_edges.txt").write_text("\n".join(out))
    print("\n".join(out))

    COLORS = {"AST": "#9aa0a6", "CFG": "#1a73e8", "REACHING_DEF": "#d93025"}
    title = (f"{ex['uid']} ({kind}, {ex['project']}): grey = syntax (AST), "
             "blue = control flow (CFG), red dashed = data flow")
    dot = ["digraph CPG {", f'  labelloc=t; fontsize=16; label="{esc(title)}";',
           "  rankdir=TB; nodesep=0.25; ranksep=0.5;",
           '  node [shape=box, style="rounded,filled", fillcolor="#f1f3f4", '
           'fontname="Helvetica", fontsize=10];',
           '  edge [fontname="Helvetica", fontsize=8];']
    for n in g["nodes"]:
        lab = esc(n["label"]) + "\\n" + esc(short(n["code"]))
        dot.append(f'  n{n["id"]} [label="{lab}"];')
    seen = set()
    for e in g["edges"]:
        key = (e["src"], e["dst"], e["type"], e["variable"])
        if e["type"] not in COLORS or key in seen or e["src"] == e["dst"]:
            continue
        seen.add(key)
        c = COLORS[e["type"]]
        if e["type"] == "AST":
            dot.append(f'  n{e["src"]} -> n{e["dst"]} [color="{c}", arrowsize=0.6];')
        elif e["type"] == "CFG":
            dot.append(f'  n{e["src"]} -> n{e["dst"]} [color="{c}", penwidth=1.6, constraint=false];')
        else:
            dot.append(f'  n{e["src"]} -> n{e["dst"]} [color="{c}", style=dashed, '
                       f'constraint=false, fontcolor="{c}", label="{esc(e["variable"])}"];')
    dot.append("}")
    (RES / "cpg_example.dot").write_text("\n".join(dot))
    try:
        subprocess.run(["dot", "-Tpng", "-Gdpi=130", str(RES / "cpg_example.dot"),
                        "-o", str(RES / "cpg_example.png")], check=True)
        print("\nsaved results/pilot/cpg_example.png")
    except FileNotFoundError:
        print("\nGraphviz 'dot' not found; run: brew install graphviz")


if __name__ == "__main__":
    main()
