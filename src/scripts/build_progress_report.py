"""Build the current two-page team progress PDF from saved project metrics."""
from __future__ import annotations

import json
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (PageBreak, Paragraph, SimpleDocTemplate, Spacer,
                                Table, TableStyle, KeepTogether)

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/archive/VulnGNN_Team_Progress_Report.pdf"
GREEN = colors.HexColor("#65734d")
DARK = colors.HexColor("#252722")
MUTED = colors.HexColor("#6b7064")
CREAM = colors.HexColor("#f8f6ee")
PALE = colors.HexColor("#e9ecdf")
LINE = colors.HexColor("#d8dbcf")


def para(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(text, style)


def draw_page(canvas, doc):
    canvas.saveState()
    width, height = letter
    canvas.setFillColor(CREAM)
    canvas.rect(0, 0, width, height, fill=1, stroke=0)
    canvas.setFillColor(GREEN)
    canvas.rect(0, height - 0.22 * inch, width, 0.22 * inch, fill=1, stroke=0)
    canvas.setFont("Helvetica-Bold", 8)
    canvas.setFillColor(DARK)
    canvas.drawString(0.58 * inch, height - 0.48 * inch, "VULNGNN  /  TEAM PROGRESS")
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(MUTED)
    canvas.drawRightString(width - 0.58 * inch, height - 0.48 * inch, "24 November 2026  |  Research prototype")
    canvas.setStrokeColor(LINE)
    canvas.line(0.58 * inch, 0.52 * inch, width - 0.58 * inch, 0.52 * inch)
    canvas.setFont("Helvetica", 8)
    canvas.drawString(0.58 * inch, 0.34 * inch, "VulnGNN  |  Uncalibrated research results")
    canvas.drawRightString(width - 0.58 * inch, 0.34 * inch, f"{doc.page} / 2")
    canvas.restoreState()


def main():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Title2", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=25, leading=29, textColor=DARK, alignment=TA_LEFT, spaceAfter=9))
    styles.add(ParagraphStyle(name="Lead", parent=styles["BodyText"], fontName="Helvetica", fontSize=10.5, leading=15, textColor=MUTED, spaceAfter=9))
    styles.add(ParagraphStyle(name="Section2", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=15, leading=19, textColor=DARK, spaceBefore=8, spaceAfter=7))
    styles.add(ParagraphStyle(name="Body2", parent=styles["BodyText"], fontName="Helvetica", fontSize=9, leading=13, textColor=DARK, spaceAfter=6))
    styles.add(ParagraphStyle(name="Small2", parent=styles["BodyText"], fontName="Helvetica", fontSize=7.5, leading=10, textColor=MUTED))
    styles.add(ParagraphStyle(name="Kicker", parent=styles["BodyText"], fontName="Helvetica-Bold", fontSize=8, leading=11, textColor=GREEN, spaceAfter=5))
    doc = SimpleDocTemplate(str(OUT), pagesize=letter, rightMargin=.58*inch, leftMargin=.58*inch, topMargin=.72*inch, bottomMargin=.68*inch, title="VulnGNN Team Progress Report", author="VulnGNN team")
    story = []

    story += [para("PROGRESS REPORT  /  RESEARCH PROTOTYPE", styles["Kicker"]),
              para("Can code graphs spot risk<br/>in projects never seen before?", styles["Title2"]),
              para("VulnGNN turns C/C++ functions into Joern code property graphs, trains a relational graph neural network, and measures ranking on held-out repositories. The current evidence is useful for a demo, while remaining preliminary and not a security verdict.", styles["Lead"])]

    cards = [[para("<b>107,461</b><br/><font size='8'>audited graphs</font>", styles["Body2"]),
              para("<b>3 + 3</b><br/><font size='8'>cross / within seeds</font>", styles["Body2"]),
              para("<b>0.111</b><br/><font size='8'>cross-project mean AP</font>", styles["Body2"]),
              para("<b>0.156</b><br/><font size='8'>within-project mean AP</font>", styles["Body2"])] ]
    card_table = Table(cards, colWidths=[1.78*inch]*4, rowHeights=[.58*inch])
    card_table.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,-1), PALE), ("BOX",(0,0),(-1,-1),.5,LINE), ("INNERGRID",(0,0),(-1,-1),.5,LINE), ("VALIGN",(0,0),(-1,-1),"MIDDLE"), ("LEFTPADDING",(0,0),(-1,-1),9)]))
    story += [card_table, Spacer(1, 7), para("Measured graph-model results", styles["Section2"]),
              para("Node-type-only R-GCN with AST, CFG, reaching-definition and control-dependence relations. Each checkpoint and threshold is selected from validation. Test split stays fixed across seeds.", styles["Body2"])]
    gnn_rows = [["Split", "Seed", "Test N / positives", "AP (cluster 95% CI)", "ROC-AUC"]]
    cross = [(42,.107521,.0759,.1371,.710), (7,.11257,.087,.142,.708), (21,.11296,.082,.140,.715)]
    for seed, ap, low, high, auc in cross:
        gnn_rows.append(["Cross-project", str(seed), "20,957 / 917", f"{ap:.3f} ({low:.3f}-{high:.3f})", f"{auc:.3f}"])
    for seed in (42,7,21):
        m = json.loads((ROOT / f"results/gnn/joern_type_only/within/all_edges/metrics_seed{seed}.json").read_text())
        gnn_rows.append(["Within-project", str(seed), f"{m['n_test_graphs']:,} / {m['positives']:,}", f"{m['ap']:.3f} ({m['ap_ci_low']:.3f}-{m['ap_ci_high']:.3f})", f"{m['roc_auc']:.3f}"])
    gt = Table(gnn_rows, colWidths=[1.18*inch,.45*inch,1.2*inch,2.18*inch,.72*inch], repeatRows=1)
    gt.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),GREEN),("TEXTCOLOR",(0,0),(-1,0),colors.white),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),7.5),("LEADING",(0,0),(-1,-1),10),("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,CREAM]),("GRID",(0,0),(-1,-1),.35,LINE),("VALIGN",(0,0),(-1,-1),"MIDDLE"),("LEFTPADDING",(0,0),(-1,-1),6),("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5)]))
    story += [gt, Spacer(1,5), para("Cross-project mean AP = 0.111 (sample SD 0.003). Within-project mean AP = 0.156 (sample SD 0.023). Seed spread and cluster intervals show uncertainty; within-project scores are from one split and do not establish broad generalization.", styles["Small2"]),
              para("Same-function held-out comparison", styles["Section2"]),
              para("All models below were evaluated on the same 20,957 Joern-covered test functions (917 positives) across 109 held-out projects; normalized IDs, labels and project IDs were checked.", styles["Body2"])]
    comp = [["Legacy text baseline", "GNN AP", "Text AP", "GNN - text AP (project 95% CI)", "ROC-AUC G / T"],
            ["Length only", "0.108", "0.120", "-0.013 (-0.031-0.009)", "0.710 / 0.738"],
            ["Raw TF-IDF logistic", "0.108", "0.105", "+0.002 (-0.010-0.015)", "0.710 / 0.738"],
            ["Masked TF-IDF", "0.108", "0.120", "-0.013 (-0.029-0.003)", "0.710 / 0.741"]]
    ct = Table(comp, colWidths=[1.38*inch,.55*inch,.55*inch,2.25*inch,1.0*inch], repeatRows=1)
    ct.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),DARK),("TEXTCOLOR",(0,0),(-1,0),colors.white),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),7),("LEADING",(0,0),(-1,-1),9),("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,CREAM]),("GRID",(0,0),(-1,-1),.35,LINE),("VALIGN",(0,0),(-1,-1),"MIDDLE"),("LEFTPADDING",(0,0),(-1,-1),5),("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5)]))
    story += [ct, Spacer(1,5), para("The paired AP differences are small and every project-bootstrap interval includes zero. Current evidence does not establish a GNN advantage. Text rows use the legacy v1 score artifact; the full baseline page reports later v2 results.", styles["Small2"]), PageBreak()]

    story += [para("WHAT WORKS  /  WHAT REMAINS", styles["Kicker"]),
              para("A runnable demo, with clear limits", styles["Title2"]),
              para("The local cream-and-olive interface presents the research question, real held-out graphs, saved metrics, and local source analysis when the runtime artifacts are available.", styles["Lead"]),
              para("A short demo path", styles["Section2"])]
    demo = [["1  Overview", "Introduce the unseen-project research question and graph pipeline."],
            ["2  Graph explorer", "Inspect a real held-out function, its node types, and typed edges."],
            ["3  Research", "Show repeat-seed metrics, matched baselines, precision transfer, and the line proxy."],
            ["4  Analysis preview", "Run a small C/C++ example through local Joern and the seed-42 model."]]
    dt = Table([[para(f"<b>{a}</b>", styles["Body2"]), para(b, styles["Body2"])] for a,b in demo], colWidths=[1.5*inch,4.8*inch])
    dt.setStyle(TableStyle([("BACKGROUND",(0,0),(0,-1),PALE),("GRID",(0,0),(-1,-1),.35,LINE),("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),8),("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),2)]))
    story += [dt, Spacer(1,7), para("Additional measurements", styles["Section2"]),
              para("Precision target transfer: validation thresholds intended to reach 50-60% precision produced held-out precision 0.000-0.179 and recall 0.000-0.008. Do not present the target precision as achieved.", styles["Body2"]),
              para("Changed-line proxy: top-1 / top-3 / top-5 overlap rates are 0.189 / 0.344 / 0.435 on 917 vulnerable functions, versus exact random expectations 0.108 / 0.234 / 0.321. The target is the fix-changed region, not a verified vulnerable line.", styles["Body2"]),
              para("What remains", styles["Section2"])]
    remaining = [["Runtime", "CodeBERT imports and the 12-graph CUDA feature smoke test pass. Full raw/masked feature extraction and CodeBERT GNN training remain."],
                 ["Model evidence", "More independently tuned relation ablations and broader external validation are needed. Held-out evaluation has not achieved a reliable 50-60% precision operating point."],
                 ["Localization", "Validate attribution against manually reviewed vulnerability-line annotations before claiming line-level accuracy."],
                 ["Scope", "Private GitHub contains source and compact reports. Full data, graph shards, Joern, environments, checkpoints and per-function score tables remain local and are excluded from Git."]]
    rt = Table([[para(f"<b>{a}</b>", styles["Body2"]), para(b, styles["Body2"])] for a,b in remaining], colWidths=[1.1*inch,5.2*inch])
    rt.setStyle(TableStyle([("BACKGROUND",(0,0),(0,-1),PALE),("GRID",(0,0),(-1,-1),.35,LINE),("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),7),("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),2)]))
    story += [rt, Spacer(1,7), para("Run the local interface", styles["Section2"]),
              para("In PowerShell from D:\\GNN_Project_Ragini:  <font name='Courier'>$env:PYTHONPATH = (Resolve-Path .\\src).Path</font> then <font name='Courier'>.\\.venv-gpu\\Scripts\\python.exe .\\scripts\\serve_web.py --host 127.0.0.1 --port 8000</font>. The current demo is at http://127.0.0.1:8008/ . Source and report: github.com/jaiaggarwal12/final-say, branch main.", styles["Body2"]),
              Spacer(1,3), para("Describe the project as an experimental research prototype. The score is uncalibrated and does not establish vulnerability, severity, exploitability, or source-line cause.", styles["Small2"])]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc.build(story, onFirstPage=draw_page, onLaterPages=draw_page)
    print(OUT)


if __name__ == "__main__":
    main()
