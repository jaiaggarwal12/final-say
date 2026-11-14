const app = document.querySelector('#app');
const fmt = (x, digits = 3) => Number(x).toFixed(digits);
const pct = (x, digits = 1) => `${(Number(x) * 100).toFixed(digits)}%`;
const esc = (s = '') => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const get = async path => { const r = await fetch(path); if (!r.ok) throw new Error(`Request failed (${r.status})`); return r.json(); };

function nav(path) {
  const active = path.split('/')[1] || 'home';
  return `<header class="shell topbar">
    <a class="brand" href="/" data-link><span class="brand-mark">V</span><span>VulnGNN<small>Research project</small></span></a>
    <button class="menu-toggle" aria-label="Toggle navigation" aria-expanded="false">☰</button>
    <nav class="nav"><a class="${active==='home'?'active':''}" href="/" data-link>Overview</a><a class="${active==='research'?'active':''}" href="/research" data-link>Research</a><a class="${active==='graph'?'active':''}" href="/graph" data-link>Graph explorer</a><a class="${active==='analyze'?'active':''}" href="/analyze" data-link>Analyze code</a></nav>
    <div class="nav-actions"><a class="button button-primary" href="/analyze" data-link>Analyze code <span aria-hidden="true">↗</span></a></div>
  </header>`;
}
const footer = `<footer class="footer"><div class="shell footer-inner"><a class="brand" href="/" data-link><span class="brand-mark">V</span><span>VulnGNN<small>Research project</small></span></a><span class="footer-note">Graph-based vulnerability research · Results are labeled with their evaluation scope.</span><span>© 2026 VulnGNN</span></div></footer>`;

function heroGraph() {
  const nodes = [[75,68,'#705685'],[167,42,'#c4b2d0'],[255,75,'#e4b9a8'],[352,42,'#79907f'],[111,150,'#c4b2d0'],[205,133,'#705685'],[296,151,'#c4b2d0'],[392,133,'#e4b9a8'],[72,235,'#e4b9a8'],[165,214,'#79907f'],[264,235,'#705685'],[364,218,'#c4b2d0']];
  const links = [[0,1],[1,2],[2,3],[0,4],[1,5],[2,6],[3,7],[4,5],[5,6],[6,7],[4,8],[5,9],[6,10],[7,11],[8,9],[9,10],[10,11],[0,5],[2,5],[2,7],[5,10],[6,11]];
  return `<svg viewBox="0 0 450 285" role="img" aria-label="Illustrative code graph with linked nodes">
    <g>${links.map(([a,b])=>`<line class="edge" x1="${nodes[a][0]}" y1="${nodes[a][1]}" x2="${nodes[b][0]}" y2="${nodes[b][1]}"/>`).join('')}</g>
    <g>${nodes.map(([x,y,c],i)=>`<g class="node"><circle cx="${x}" cy="${y}" r="${i%3===0?13:10}" fill="${c}"/><circle cx="${x}" cy="${y}" r="${i%3===0?5:3}" fill="#fff" opacity=".8"/></g>`).join('')}</g>
    <g fill="#8d7c97" font-size="9" font-family="DM Mono,monospace"><text x="53" y="45">METHOD</text><text x="269" y="50">CALL</text><text x="127" y="193">BRANCH</text><text x="321" y="251">DATA FLOW</text></g>
  </svg>`;
}

function landing(path) {
  return `${nav(path)}
  <main>
    <section class="shell hero"><div><span class="eyebrow">Security through structure</span><h1>See the code<br>behind the <em>risk.</em></h1><p class="hero-copy">VulnGNN studies whether code property graphs can reveal vulnerability patterns that hold up on software projects the model has never seen.</p><div class="hero-ctas"><a class="button button-primary" href="/analyze" data-link>Analyze code <span>↗</span></a><a class="button button-soft" href="/research" data-link>Explore the research</a></div><div class="hero-note">Research prototype · C and C++ · Graph inference is not yet available</div></div>
      <div class="hero-visual"><div class="orbit"></div><div class="visual-card"><div class="visual-head"><strong>STRUCTURAL SIGNAL</strong><span class="window-dots"><i></i><i></i><i></i></span></div><div class="graph-art">${heroGraph()}</div></div><div class="floating-pill pill-top"><b></b>AST · CFG · DATA FLOW</div><div class="floating-pill pill-bottom"><b></b>Illustrative graph</div></div>
    </section>
    <section class="problem section"><div class="shell problem-grid"><div class="problem-art"><div class="code-window"><div class="window-dots"><i></i><i></i><i></i></div><div class="code-row"><span>01</span><span>char *<b>copy_input</b>(char *src) {</span></div><div class="code-row"><span>02</span><span>  char buf[<mark>64</mark>];</span></div><div class="code-row"><span>03</span><span>  <mark>strcpy</mark>(buf, src);</span></div><div class="code-row"><span>04</span><span>  return buf;</span></div><div class="code-row"><span>05</span><span>}</span></div></div><div class="side-note">Illustrative code · not a VulnGNN prediction</div></div><div><span class="eyebrow">The generalization problem</span><h2 class="page-title">A familiar name can hide an unfamiliar risk.</h2><p class="page-lede">Text models can learn project-specific vocabulary alongside code behavior. When a project is new, those familiar signals disappear. This research asks whether the structure of code offers a more transferable view.</p><div class="insight"><span class="insight-num">01</span><div><strong>Vocabulary shifts</strong><p>Identifiers and conventions change between repositories, even when the underlying behavior does not.</p></div></div><div class="insight"><span class="insight-num">02</span><div><strong>Structure can travel</strong><p>Control, syntax and data dependencies describe how code behaves, not just what it is called.</p></div></div></div></div></section>
    <section class="workflow section"><div class="shell"><div class="section-heading"><span class="eyebrow">From source to structure</span><h2>How the research pipeline works</h2><p>Each stage preserves a link back to the original function and its source lines.</p></div><div class="steps">${[['01','↥','Add source','Provide a C or C++ function for analysis.'],['02','⌘','Build the graph','Joern extracts syntax, control flow and data dependencies.'],['03','◈','Read structure','A graph model learns from connected code behavior.'],['04','⌕','Assess risk','The model scores a function for vulnerability signals.'],['05','↗','Inspect evidence','Review source lines and graph context behind a result.']].map(x=>`<article class="step-card"><span class="step-count">STEP ${x[0]}</span><div class="step-icon">${x[1]}</div><h3>${x[2]}</h3><p>${x[3]}</p></article>`).join('')}</div></div></section>
    <section class="section"><div class="shell"><div class="section-heading"><span class="eyebrow">A graph with context</span><h2>Different edges tell different stories.</h2><p>The graph representation combines complementary views of a function. The current model and full-scale graph dataset remain in development.</p></div><div class="tech-grid">${[['Structure','AST','Abstract syntax tree','Captures how expressions and statements are nested.'],['Control','CFG','Control-flow graph','Connects possible execution paths through branches and loops.'],['Data','REACHING_DEF','Data dependencies','Tracks where values originate and how they move.'],['Influence','CDG','Control dependence','Shows which decisions govern a statement.'],['Model','GGNN','Gated graph neural network','A planned architecture for learning across graph neighborhoods.'],['Model','R-GCN','Relational graph convolution','The implemented research model distinguishes edge relations.']].map((x,i)=>`<article class="tech-card"><span class="type">${x[0]}</span><div class="tech-symbol"><i></i><i></i><i></i><i></i><i></i></div><h3>${x[1]}</h3><p><b>${x[2]}.</b> ${x[3]}</p></article>`).join('')}</div></div></section>
    <section class="research-band section"><div class="shell"><div class="section-heading"><span class="eyebrow">Measured so far</span><h2>Text baselines show the generalization gap.</h2><p>Phase 2A evaluation uses held-out projects and within-project splits. The GNN has not yet been evaluated.</p></div><div class="metric-row" id="landing-metrics"><div class="loading-shimmer"></div><div class="loading-shimmer"></div><div class="loading-shimmer"></div></div><div class="section-cta"><p>See confidence intervals, model variants, per-project results and the evaluation protocol.</p><a class="button button-soft" href="/research" data-link>View research results <span>↗</span></a></div></div></section>
    <section class="closing section"><div class="shell closing-inner"><div><span class="eyebrow">Built for careful research</span><h2>Explore the evidence. Follow the graph.</h2><p class="page-lede">Browse the measured baselines or inspect one of the real Joern pilot graphs.</p></div><div class="hero-ctas"><a class="button button-primary" href="/research" data-link>Explore research</a><a class="button button-soft" href="/graph" data-link>Open graph explorer</a></div></div></section>
  </main>${footer}`;
}

function analyzePage(path) {
  return `${nav(path)}<main class="shell page-wrap"><div class="page-top"><div><span class="eyebrow">Code analysis</span><h1 class="page-title">Inspect a function</h1><p class="page-lede">A focused workspace for C/C++ source and future model evidence.</p></div><span class="status-badge pending"><i class="dot"></i> Inference pending</span></div>
    <div class="analysis-grid"><section class="panel upload-panel"><h2 class="panel-title">Source function</h2><p class="panel-copy">Choose one C or C++ source file. Your selection stays in this browser; it is not uploaded.</p><label class="dropzone" id="dropzone"><input id="source-file" type="file" accept=".c,.h,.cc,.cpp,.cxx,.hpp"><span class="drop-icon">↥</span><strong>Drop a source file here</strong><p>or select a file · .c, .h, .cc, .cpp, .cxx, .hpp</p><span class="button button-soft">Choose file</span></label><div id="file-preview" class="file-preview"></div><button class="button button-primary disabled-submit" disabled title="No inference service is available">Run vulnerability analysis <span>↗</span></button></section>
    <aside><section class="panel status-card"><h2 class="panel-title">Service status</h2><div id="analysis-status"><div class="loading-shimmer"></div></div><div class="api-note">The interface is ready for a model API. Analysis results, confidence, severity, source highlights and explanations will appear here only when the backend returns them.</div></section><section class="notice" style="margin-top:16px"><strong>Research prototype</strong><p>No trained GNN checkpoint or inference endpoint is present in this repository. File selection previews code locally; no prediction is generated.</p></section></aside></div></main>${footer}`;
}

function researchPage(path) {
  return `${nav(path)}<main class="shell page-wrap"><div class="page-top"><div><span class="eyebrow">Evaluation & methodology</span><h1 class="page-title">Evidence before claims.</h1><p class="page-lede">Measured Phase 2A baselines on held-out functions. No GNN performance is available yet.</p></div><span class="status-badge"><i class="dot"></i> Seed 42 · test results</span></div><div class="research-tabs"><button class="tab-button active" data-split="within">Within project</button><button class="tab-button" data-split="cross">Cross project</button></div>
    <div class="research-layout"><section class="panel research-main"><div class="project-toolbar"><div><h2 class="panel-title">Baseline comparison</h2><p class="panel-copy" id="split-subtitle">Functions are split by project and function-name groups.</p></div><span class="tag">AP + cluster 95% CI</span></div><div id="baseline-table" class="table-wrap"><div class="loading-shimmer"></div></div><div class="research-footnote">Average precision is reported with a cluster bootstrap: whole function groups for within-project and whole projects for cross-project. Hyperparameters and thresholds were selected on validation only. Row-level intervals are optimistic and are not shown here.</div></section><aside><article class="panel chart-card"><h3>Precision–recall curve</h3><img id="pr-chart" alt="Measured precision recall curves for selected baselines"><p class="chart-caption">Source: checked-in Phase 2A evaluation figure.</p></article><article class="panel chart-card"><h3>Average precision ÷ prevalence</h3><img src="/research-figures/06_baselines_v2_ap_lift.png" alt="Measured baseline average precision divided by class prevalence"><p class="chart-caption">Lift is calculated from each split's measured prevalence.</p></article></aside></div>
    <section class="panel project-panel"><div class="project-toolbar"><div><h2 class="panel-title">Per-project test results</h2><p class="panel-copy">Only projects with at least 30 vulnerable test functions are included.</p></div><select id="project-model"><option value="tfidf_logreg">TF-IDF + logistic regression</option><option value="length_only">Length only</option></select></div><div id="project-table" class="table-wrap"><div class="loading-shimmer"></div></div></section>
    <section class="panel project-panel"><div class="project-toolbar"><div><h2 class="panel-title">What these numbers say</h2><p class="panel-copy">The masking ablation probes how identifier tokens affect text-model performance.</p></div><a class="button button-soft" href="/graph" data-link>Inspect pilot graphs ↗</a></div><div class="tech-grid"><article class="tech-card"><span class="type">Supported by these runs</span><h3>Raw-token AP falls from 0.356 to 0.105</h3><p>Within-project to cross-project, consistent with a substantial generalization gap for this TF-IDF model.</p></article><article class="tech-card"><span class="type">Supported by this ablation</span><h3>Masking changes the ranking</h3><p>API-preserving and fully masked variants score higher than raw tokens cross-project, but the effect is one-seed and not proof of a cause.</p></article><article class="tech-card"><span class="type">Still pending</span><h3>No GNN comparison yet</h3><p>Full graph extraction, trained-model evaluation, multi-seed uncertainty and localization results are not available.</p></article></div></section></main>${footer}`;
}

function graphPage(path) {
  const id = path.split('/')[2] || '';
  return `${nav(path)}<main class="shell page-wrap"><div class="page-top"><div><span class="eyebrow">Graph explorer</span><h1 class="page-title">Follow code relationships.</h1><p class="page-lede">Explore actual Joern pilot CPGs. These examples are not predictions from a trained model.</p></div><span class="status-badge"><i class="dot"></i> Pilot graphs</span></div><div class="graph-controls"><select id="graph-picker" aria-label="Select pilot graph"><option>Loading pilot graphs…</option></select><select id="edge-filter" aria-label="Filter graph edge types"><option value="all">All edge types</option><option value="AST">AST</option><option value="CFG">CFG</option><option value="REACHING_DEF">REACHING_DEF</option><option value="CDG">CDG</option></select><span class="tag" id="graph-count">Loading pilot inventory…</span></div><div class="graph-layout"><section class="graph-stage" id="graph-stage"><div class="graph-tools"><button data-zoom="in" aria-label="Zoom in">＋</button><button data-zoom="out" aria-label="Zoom out">−</button><button data-zoom="reset">Reset view</button></div><div id="graph-canvas" class="loading-shimmer"></div></section><aside class="panel graph-info" id="graph-info"><div class="loading-shimmer"></div></aside></div></main>${footer}`;
}

function resultsPage(path) {
  const id = path.split('/')[2] || '';
  return `${nav(path)}<main class="shell page-wrap"><div class="page-top"><div><span class="eyebrow">Analysis results</span><h1 class="page-title">No saved analysis</h1><p class="page-lede">${id ? `Result “${esc(id)}” is not available in this research prototype.` : 'No analysis results have been generated yet.'}</p></div></div><section class="panel empty-panel"><div class="drop-icon">⌕</div><h2>Inference is not connected yet</h2><p>There is no trained GNN checkpoint or analysis API available. This page will show source highlights, confidence and explanations after a real backend result is returned.</p><a class="button button-primary" href="/research" data-link>Review measured research</a></section></main>${footer}`;
}

function render() {
  const path = decodeURI(location.pathname).replace(/\/$/, '') || '/';
  if (path === '/') app.innerHTML = landing(path);
  else if (path === '/analyze') app.innerHTML = analyzePage(path);
  else if (path === '/research') app.innerHTML = researchPage(path);
  else if (path === '/graph' || path.startsWith('/graph/')) app.innerHTML = graphPage(path);
  else if (path === '/results' || path.startsWith('/results/')) app.innerHTML = resultsPage(path);
  else app.innerHTML = `${nav(path)}<main class="shell page-wrap"><section class="panel empty-panel"><div class="drop-icon">404</div><h2>Page not found</h2><p>That route is not part of the VulnGNN research site.</p><a class="button button-primary" href="/" data-link>Return home</a></section></main>${footer}`;
  bindCommon();
  if (path === '/') loadLandingMetrics();
  if (path === '/analyze') loadAnalysisStatus();
  if (path === '/research') loadResearch();
  if (path === '/graph' || path.startsWith('/graph/')) loadGraph(path.split('/')[2] || '');
}

function bindCommon() {
  document.querySelectorAll('[data-link]').forEach(a => a.addEventListener('click', e => {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault(); history.pushState({}, '', a.getAttribute('href')); render(); window.scrollTo(0,0);
  }));
  const menu = document.querySelector('.menu-toggle');
  menu?.addEventListener('click', () => { const navEl=document.querySelector('.nav'); const open=navEl.classList.toggle('open'); menu.setAttribute('aria-expanded',String(open)); });
  const reveal = new IntersectionObserver(entries => entries.forEach(x => { if(x.isIntersecting){x.target.classList.add('in');reveal.unobserve(x.target);} }),{threshold:.08});
  document.querySelectorAll('.section,.tech-card,.step-card').forEach(el=>{el.classList.add('reveal');reveal.observe(el);});
}
window.addEventListener('popstate', render);

async function loadLandingMetrics() {
  const el = document.querySelector('#landing-metrics');
  try {
    const {results} = await get('/api/research/baselines');
    const within=results.find(r=>r.split==='within'&&r.variant==='raw_tokens');
    const cross=results.find(r=>r.split==='cross'&&r.variant==='raw_tokens');
    if(!within||!cross) throw new Error('Raw-token baseline results are unavailable.');
    el.innerHTML = `<article class="metric-tile"><span>Within-project · TF-IDF raw tokens</span><strong>${fmt(within.ap,3)}</strong><small>Average precision · prevalence ${pct(within.prevalence,2)}</small></article><article class="metric-tile"><span>Cross-project · TF-IDF raw tokens</span><strong>${fmt(cross.ap,3)}</strong><small>Average precision · prevalence ${pct(cross.prevalence,2)}</small></article><article class="metric-tile"><span>GNN evaluation</span><strong>Pending</strong><small>No trained model results are available</small></article>`;
  } catch(e){el.innerHTML=`<div class="page-error">Measured results could not be loaded: ${esc(e.message)}</div>`;}
}

async function loadAnalysisStatus(){
  const holder=document.querySelector('#analysis-status');
  try{const data=await get('/api/analysis/status'); holder.innerHTML=`<div class="status-line"><span>Inference service</span><b>${data.available?'READY':'PENDING'}</b></div><div class="status-line"><span>GNN checkpoint</span><b>NOT FOUND</b></div><div class="status-line"><span>Response</span><b>NO PREDICTION</b></div>`;
    const input=document.querySelector('#source-file'), zone=document.querySelector('#dropzone'), preview=document.querySelector('#file-preview');
    const show=file=>{if(!file)return; const ext=file.name.split('.').pop().toLowerCase(); if(!['c','h','cc','cpp','cxx','hpp'].includes(ext)){preview.classList.add('visible');preview.innerHTML='<div class="page-error">Unsupported file type. Choose a C or C++ source file.</div>';return;} const reader=new FileReader(); reader.onload=()=>{const code=String(reader.result||''); preview.classList.add('visible');preview.innerHTML=`<div class="mono" style="font-size:10px;color:#8b7d93;margin-bottom:8px">${esc(file.name)} · ${file.size.toLocaleString()} bytes · local preview only</div><pre>${esc(code.slice(0,12000))}${code.length>12000?'\n… preview truncated':''}</pre>`;}; reader.onerror=()=>{preview.classList.add('visible');preview.textContent='The selected file could not be read.';}; reader.readAsText(file);};
    input.addEventListener('change',()=>show(input.files[0])); zone.addEventListener('dragover',e=>{e.preventDefault();zone.classList.add('drag');}); zone.addEventListener('dragleave',()=>zone.classList.remove('drag')); zone.addEventListener('drop',e=>{e.preventDefault();zone.classList.remove('drag');show(e.dataTransfer.files[0]);});
  }catch(e){holder.innerHTML=`<div class="page-error">Could not reach the analysis status API: ${esc(e.message)}</div>`;}
}

let researchRows=[], projectRows=[], selectedSplit='within';
async function loadResearch(){
  try{const [base,proj]=await Promise.all([get('/api/research/baselines'),get('/api/research/projects')]);researchRows=base.results;projectRows=proj.results;drawResearch();
    document.querySelectorAll('[data-split]').forEach(btn=>btn.addEventListener('click',()=>{selectedSplit=btn.dataset.split;document.querySelectorAll('[data-split]').forEach(b=>b.classList.toggle('active',b===btn));drawResearch();}));
    document.querySelector('#project-model').addEventListener('change',drawProjects);drawProjects();
  }catch(e){document.querySelector('#baseline-table').innerHTML=`<div class="page-error">Research results could not be loaded: ${esc(e.message)}</div>`;}
}
function drawResearch(){
  const rows=researchRows.filter(r=>r.split===selectedSplit);
  document.querySelector('#split-subtitle').textContent=selectedSplit==='within'?'Grouped by project and function-name to keep related functions together.':'Entire projects are held out from training and validation.';
  document.querySelector('#pr-chart').src=`/research-figures/05_baselines_v2_pr_${selectedSplit}.png`;
  document.querySelector('#baseline-table').innerHTML=`<table class="results-table"><thead><tr><th>Model / variant</th><th>N</th><th>Positives</th><th>AP (95% CI)</th><th>P @ R30</th><th>Precision</th><th>Recall</th><th>F1</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${esc(modelName(r.model))}<br><span style="color:#918997;font-size:10px">${esc(variantName(r.variant))}</span></td><td>${Number(r.n).toLocaleString()}</td><td>${Number(r.positives).toLocaleString()}</td><td class="score">${fmt(r.ap,3)} <span style="color:#8e8593">(${fmt(r.ap_ci_low,3)}–${fmt(r.ap_ci_high,3)})</span></td><td>${fmt(r.p_at_r30,3)}</td><td>${fmt(r.precision,3)}</td><td>${fmt(r.recall,3)}</td><td>${fmt(r.f1,3)}</td></tr>`).join('')}</tbody></table>`;
  if(projectRows.length) drawProjects();
}
function modelName(x){return x==='tfidf_logreg'?'TF-IDF + logistic regression':x==='length_only'?'Length only':x;}
function variantName(x){return ({raw_tokens:'Raw tokens',masked_api_kept:'Masked · APIs kept',fully_masked:'Fully masked',log_chars_lines:'Log chars + lines'})[x]||x;}
function drawProjects(){
  const model=document.querySelector('#project-model').value;
  const rows=projectRows.filter(r=>r.split===selectedSplit&&r.model===model).sort((a,b)=>Number(b.positives)-Number(a.positives));
  document.querySelector('#project-table').innerHTML=rows.length?`<table class="results-table"><thead><tr><th>Project</th><th>Variant</th><th>N</th><th>Vulnerable</th><th>Prevalence</th><th>AP</th><th>Precision</th><th>Recall</th><th>F1</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${esc(r.project_g)}</td><td>${esc(variantName(r.variant))}</td><td>${Number(r.n).toLocaleString()}</td><td>${Number(r.positives).toLocaleString()}</td><td>${pct(r.prevalence,1)}</td><td class="score">${fmt(r.ap,3)}</td><td>${fmt(r.precision,3)}</td><td>${fmt(r.recall,3)}</td><td>${fmt(r.f1,3)}</td></tr>`).join('')}</tbody></table>`:'<p class="page-copy">No eligible project rows in this result set.</p>';
}

let graphRows=[], currentGraph=null, transform={x:0,y:0,k:1}, selectedNode=null, dragState=null;
async function loadGraph(pathId){
  const picker=document.querySelector('#graph-picker'); let stage='fetching graph list';
  try{const {results,count}=await get('/api/graphs');graphRows=results;stage='populating graph list';document.querySelector('#graph-count').textContent=`${count} pilot graphs · real Joern output`;
    picker.innerHTML=graphRows.map(g=>`<option value="${esc(g.uid)}">${esc(g.project||'Unknown project')} · ${esc(g.method||g.uid)} · ${g.nodes} nodes</option>`).join('');
    stage='selecting graph'; let selected=graphRows.find(g=>g.uid===pathId)||graphRows.find(g=>g.nodes>0)||graphRows[0]; if(!selected) throw new Error('No pilot graph artifacts were found.'); picker.value=selected.uid; picker.addEventListener('change',()=>{history.pushState({},'',`/graph/${picker.value}`);loadOneGraph(picker.value);});
    stage='binding graph controls';document.querySelector('#edge-filter').addEventListener('change',()=>drawGraph()); document.querySelectorAll('[data-zoom]').forEach(b=>b.addEventListener('click',()=>zoom(b.dataset.zoom)));
    bindPan();stage='loading selected graph'; await loadOneGraph(selected.uid);
  }catch(e){console.error(e);document.querySelector('#graph-canvas').outerHTML=`<div class="page-error">Pilot graph could not be loaded (${esc(stage)}): ${esc(e.message)}</div>`;}
}
async function loadOneGraph(uid){
  document.querySelector('#graph-canvas').className='loading-shimmer';
  try{const data=await get(`/api/graphs/${encodeURIComponent(uid)}`);currentGraph=data.graph;selectedNode=null;transform={x:0,y:0,k:1};drawGraph();drawGraphInfo();}
  catch(e){document.querySelector('#graph-canvas').innerHTML=`<div class="page-error">${esc(e.message)}</div>`;}
}
function nodeColor(label){if(/METHOD|BLOCK|RETURN|CONTROL_STRUCTURE/.test(label))return '#735b87';if(/CALL/.test(label))return '#d7a98f';if(/IDENTIFIER|FIELD_IDENTIFIER|LOCAL/.test(label))return '#9eaf9e';if(/LITERAL|TYPE/.test(label))return '#b9a7c7';return '#8b91a5';}
function pointLayout(nodes,edges){
  const w=900,h=560,n=nodes.length; const pos=nodes.map((_,i)=>{const a=2*Math.PI*i/n; const r=Math.min(w,h)*(.25+.06*((i*37)%5)/4);return{x:w/2+r*Math.cos(a),y:h/2+r*Math.sin(a)};});
  const idx=new Map(nodes.map((x,i)=>[String(x.id),i])); const usable=edges.filter(e=>idx.has(String(e.src))&&idx.has(String(e.dst))).slice(0,1000);
  for(let iter=0;iter<90;iter++){
    const force=pos.map(()=>({x:0,y:0}));
    for(let i=0;i<n;i++)for(let j=i+1;j<n;j++){let dx=pos[i].x-pos[j].x,dy=pos[i].y-pos[j].y,d2=dx*dx+dy*dy+1,d=Math.sqrt(d2),f=2100/d2;force[i].x+=dx/d*f;force[i].y+=dy/d*f;force[j].x-=dx/d*f;force[j].y-=dy/d*f;}
    for(const e of usable){const a=idx.get(String(e.src)),b=idx.get(String(e.dst));if(a===b)continue;let dx=pos[b].x-pos[a].x,dy=pos[b].y-pos[a].y,d=Math.sqrt(dx*dx+dy*dy)+.1,f=(d-82)*.006;force[a].x+=dx*f;force[a].y+=dy*f;force[b].x-=dx*f;force[b].y-=dy*f;}
    const cooling=1-iter/110; for(let i=0;i<n;i++){pos[i].x=Math.max(35,Math.min(w-35,pos[i].x+Math.max(-8,Math.min(8,force[i].x))*cooling));pos[i].y=Math.max(35,Math.min(h-35,pos[i].y+Math.max(-8,Math.min(8,force[i].y))*cooling));}
  }
  return {pos,idx};
}
function drawGraph(){
  if(!currentGraph)return;const host=document.querySelector('#graph-canvas');host.className=''; const nodes=currentGraph.nodes||[],allEdges=currentGraph.edges||[];const type=document.querySelector('#edge-filter').value;const edges=allEdges.filter(e=>type==='all'||e.type===type);const {pos,idx}=pointLayout(nodes,edges);const selected=selectedNode!==null?String(nodes[selectedNode]?.id):'';
  const edgeSvg=edges.map(e=>{const a=idx.get(String(e.src)),b=idx.get(String(e.dst));if(a===undefined||b===undefined)return'';const rel=e.type||'OTHER';return `<line x1="${pos[a].x}" y1="${pos[a].y}" x2="${pos[b].x}" y2="${pos[b].y}" stroke="${edgeColor(rel)}" stroke-opacity=".34" stroke-width="${selected&&(String(nodes[a].id)===selected||String(nodes[b].id)===selected)?2.1:1.05}"/>`;}).join('');
  const nodeSvg=nodes.map((node,i)=>`<g class="graph-node" data-node="${i}" tabindex="0" role="button" aria-label="${esc(node.label)} at line ${esc(node.line||'?')}"><circle cx="${pos[i].x}" cy="${pos[i].y}" r="${selected&&String(node.id)===selected?11:7}" fill="${nodeColor(node.label)}" stroke="${selected&&String(node.id)===selected?'#33283d':'#fff'}" stroke-width="${selected&&String(node.id)===selected?3:1.5}"/><title>${esc(node.label)} · ${esc(node.code||node.name||'')} · line ${esc(node.line||'—')}</title></g>`).join('');
  host.innerHTML=`<svg viewBox="0 0 900 560" role="img" aria-label="Interactive pilot code property graph"><g id="graph-world" transform="translate(${transform.x} ${transform.y}) scale(${transform.k})">${edgeSvg}${nodeSvg}</g></svg>`;
  host.querySelectorAll('.graph-node').forEach(g=>{g.addEventListener('click',()=>{selectedNode=Number(g.dataset.node);drawGraph();drawGraphInfo();});g.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){selectedNode=Number(g.dataset.node);drawGraph();drawGraphInfo();}});});
}
function edgeColor(type){return ({AST:'#806a92',CFG:'#5e7b79',REACHING_DEF:'#ca987c',CDG:'#8f779f'})[type]||'#a4a0a9';}
function drawGraphInfo(){
  if(!currentGraph)return;const g=currentGraph;const n=selectedNode===null?null:g.nodes[selectedNode];const holder=document.querySelector('#graph-info');
  const edgeTypes=[...new Set((g.edges||[]).map(e=>e.type))];
  holder.innerHTML=`<span class="tag">JOERN PILOT · NOT A PREDICTION</span><h3 style="margin-top:17px">${esc(g.method||'Unnamed function')}</h3><div class="meta">${esc(g.project||'Unknown project')} · ${esc(g.source_file||'source unavailable')}</div><div class="graph-legend">${[['AST','#806a92'],['CFG','#5e7b79'],['REACHING_DEF','#ca987c'],['CDG','#8f779f']].map(([t,c])=>`<div class="legend-row"><span class="legend-swatch" style="background:${c}"></span>${t}</div>`).join('')}</div><div class="status-line"><span>Graph nodes</span><b>${(g.nodes||[]).length}</b></div><div class="status-line"><span>Graph edges</span><b>${(g.edges||[]).length}</b></div><div class="status-line"><span>Recorded label</span><b>${Number(g.label)===1?'VULNERABLE':'SAFE'}</b></div><div class="graph-property"><span>Relations present</span><strong>${esc(edgeTypes.join(' · ')||'None')}</strong></div>${g.cve?`<div class="graph-property"><span>Associated CVE in pilot data</span><strong>${esc(g.cve)}</strong></div>`:''}${n?`<div class="graph-property"><span>Selected node</span><strong>${esc(n.label)} · line ${esc(n.line||'—')}</strong><p style="margin:8px 0 0;color:#716879">${esc(n.code||n.name||'No node code recorded')}</p></div>`:`<div class="graph-property"><span>Node inspection</span><strong>Select a node to inspect it</strong></div>`}${g.source?`<div class="code-pane"><pre>${esc(g.source)}</pre></div>`:'<p class="chart-caption">Pilot source text is not present for this graph artifact.</p>'}`;
}
function zoom(direction){transform.k=Math.max(.5,Math.min(2.5,transform.k*(direction==='in'?1.2:direction==='out'?.83:1)));if(direction==='reset')transform={x:0,y:0,k:1};drawGraph();}
function bindPan(){
  const stage=document.querySelector('#graph-stage');let active=false,last=null;
  stage.addEventListener('pointerdown',e=>{if(e.target.closest('.graph-tools')||e.target.closest('.graph-node'))return;active=true;last={x:e.clientX,y:e.clientY};stage.setPointerCapture(e.pointerId);});
  stage.addEventListener('pointermove',e=>{if(!active)return;const rect=stage.getBoundingClientRect();transform.x+=(e.clientX-last.x)*900/rect.width;transform.y+=(e.clientY-last.y)*560/rect.height;last={x:e.clientX,y:e.clientY};const world=document.querySelector('#graph-world');if(world)world.setAttribute('transform',`translate(${transform.x} ${transform.y}) scale(${transform.k})`);});
  stage.addEventListener('pointerup',()=>{active=false;});
  stage.addEventListener('wheel',e=>{e.preventDefault();transform.k=Math.max(.5,Math.min(2.5,transform.k*(e.deltaY<0?1.08:.92)));const world=document.querySelector('#graph-world');if(world)world.setAttribute('transform',`translate(${transform.x} ${transform.y}) scale(${transform.k})`);},{passive:false});
}

render();
