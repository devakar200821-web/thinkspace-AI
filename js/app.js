/* ThinkSpace AI — workspace: sources, local generation, projects, history */
const TYPES=[
  {id:'summary',icon:'▤',name:'Summary',desc:'Detailed notes and key themes'},
  {id:'mindmap',icon:'⌘',name:'Mind Map',desc:'Visual themes with source notes'},
  {id:'report',icon:'▧',name:'Report',desc:'In-depth findings from your sources'},
  {id:'presentation',icon:'▥',name:'Presentation',desc:'Detailed slides with key information'}];
const TEMPLATES=[
  {name:'Literature Review',type:'report',desc:'Structured overview of papers and findings.'},
  {name:'Study Guide',type:'summary',desc:'Build detailed revision notes from your sources.'},
  {name:'Concept Map',type:'mindmap',desc:'Show how ideas connect, with supporting notes.'},
  {name:'Pitch Deck',type:'presentation',desc:'Turn research into a detailed slide story.'}];
const VIEWS={projects:['Welcome to ThinkSpace AI','Your ideas start with the sources you bring.'],upload:['Upload Sources','Add files or paste text to work with.'],templates:['Templates','Start from a ready-made output style.'],history:['History','Everything you have generated.'],settings:['Settings','Manage your profile and data.']};
const state={sources:[],output:'summary',view:'projects'};
const K=n=>`ts_${n}_${Auth.session()}`;
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
function toast(t){const el=$('#toast');el.textContent=t;el.classList.remove('hidden');clearTimeout(toast.t);toast.t=setTimeout(()=>el.classList.add('hidden'),2600)}
function openModal(html){$('#modalBox').innerHTML=html;$('#modal').classList.remove('hidden')}
function closeModal(){$('#modal').classList.add('hidden')}
$('#modal').onclick=e=>{if(e.target.id==='modal')closeModal()};

/* ---------- session / navigation ---------- */
function enterApp(){
  const u=Auth.user();if(!u)return;
  $('#auth').classList.add('hidden');$('#dashboard').classList.remove('hidden');
  $('#userName').textContent=u.name||'User';$('#avatar').textContent=(u.name||'U').charAt(0).toUpperCase();
  state.sources=[];go('projects');
}
$('#logout').onclick=()=>{Auth.end();$('#dashboard').classList.add('hidden');$('#auth').classList.remove('hidden');showForm('signin')};
$$('.nav-item[data-view]').forEach(n=>n.onclick=()=>go(n.dataset.view));
function go(v){
  state.view=v;
  $$('.nav-item[data-view]').forEach(n=>{
    const active=n.dataset.view===v;
    n.classList.toggle('active',active);
    if(active)n.setAttribute('aria-current','page');else n.removeAttribute('aria-current');
  });
  const [t,s]=VIEWS[v];$('#viewTitle').textContent=t;$('#viewSub').textContent=s;
  ({projects:viewWorkspace,upload:viewWorkspace,templates:viewTemplates,history:viewHistory,settings:viewSettings})[v]();
}

/* ---------- workspace (upload + outputs) ---------- */
function viewWorkspace(){
  $('#view').innerHTML=`
  <div class="upload" id="drop"><div class="symbol">⇧</div><h3>Upload your research sources</h3>
    <p>TXT, MD and CSV are read in your browser. PDF, DOCX and images are attached and will be processed once a backend is connected.</p>
    <input type="file" id="file" multiple hidden accept=".txt,.md,.csv,.pdf,.docx,.png,.jpg,.jpeg">
    <button class="primary btn-s" id="browse">Browse Files</button>
    <p>or <a href="#" id="paste">Paste Text</a> · or drop files here</p></div>
  <div id="sources"></div>
  <h3 class="h3">Choose your output</h3>
  <div class="tiles" role="group" aria-label="Choose an output type">${TYPES.map(t=>`<button class="tile ${t.id===state.output?'sel':''}" type="button" data-t="${t.id}" aria-pressed="${t.id===state.output}"><span class="tile-icon" aria-hidden="true">${t.icon}</span><b>${t.name}</b><span>${t.desc}</span></button>`).join('')}</div>
  <button class="primary generate" id="gen">Generate Output →</button>
  ${state.view==='projects'?'<h3 class="h3">My projects</h3><div id="plist"></div>':''}`;
  const file=$('#file'),drop=$('#drop');
  $('#browse').onclick=()=>file.click();
  file.onchange=()=>addFiles(file.files);
  ['dragover','dragenter'].forEach(ev=>drop.addEventListener(ev,e=>{e.preventDefault();drop.classList.add('drag')}));
  ['dragleave','drop'].forEach(ev=>drop.addEventListener(ev,e=>{e.preventDefault();drop.classList.remove('drag')}));
  drop.addEventListener('drop',e=>addFiles(e.dataTransfer.files));
  $('#paste').onclick=e=>{e.preventDefault();pasteModal()};
  $$('.tile').forEach(t=>t.onclick=()=>{
    state.output=t.dataset.t;
    $$('.tile').forEach(x=>{
      const selected=x===t;
      x.classList.toggle('sel',selected);
      x.setAttribute('aria-pressed',String(selected));
    });
  });
  $('#gen').onclick=generate;
  renderSources();if($('#plist'))renderProjects();
  if(state.view==='upload'&&!state.sources.length)setTimeout(()=>drop.scrollIntoView({behavior:'smooth'}),0);
}
function addFiles(list){
  [...list].forEach(f=>{
    const ext=f.name.split('.').pop().toLowerCase();
    if(['txt','md','csv'].includes(ext)){const r=new FileReader();r.onload=()=>{state.sources.push({name:f.name,text:String(r.result),size:f.size});renderSources()};r.readAsText(f)}
    else{state.sources.push({name:f.name,text:'',size:f.size,pending:true});renderSources();toast(`${f.name} attached — text extraction needs the backend phase.`)}
  });
}
function pasteModal(){
  openModal(`<div class="modal-head"><h3>Paste text</h3><button class="ghost" onclick="closeModal()">✕</button></div>
  <textarea id="pt" rows="10" placeholder="Paste your notes, article or research text here…"></textarea>
  <div class="modal-actions"><button class="ghost" onclick="closeModal()">Cancel</button><button class="primary" id="ptok">Add as source</button></div>`);
  $('#ptok').onclick=()=>{const t=$('#pt').value.trim();if(!t){toast('Please paste some text first.');return}
    state.sources.push({name:'Pasted text '+(state.sources.length+1),text:t,size:t.length});closeModal();renderSources()};
}
function renderSources(){
  const el=$('#sources');if(!el)return;
  el.innerHTML=state.sources.map((s,i)=>`<div class="src"><div>${s.pending?'📎':'📄'} ${esc(s.name)} <small>· ${s.pending?'attached (not readable yet)':s.text.split(/\s+/).length+' words'}</small></div><button data-i="${i}">Remove</button></div>`).join('');
  $$('#sources button').forEach(b=>b.onclick=()=>{state.sources.splice(+b.dataset.i,1);renderSources()});
}

/* ---------- local "AI" generation (extractive). Swap analyze() for a real API later ---------- */
const STOP=new Set('the a an and or but of to in on for with is are was were be been it this that as at by from not have has had will can which their they them his her its our we you than then so if into about more also such these those other over just there what when who how all any may most some one two would could should while where being very much many each between during'.split(' '));
function analyze(text){
  const clean=text.replace(/\s+/g,' ').trim();
  const sents=(clean.match(/[^.!?]+(?:[.!?]+|$)/g)||[]).map(s=>s.trim()).filter(Boolean);
  const freq={};(clean.toLowerCase().match(/[a-z']{3,}/g)||[]).forEach(w=>{if(!STOP.has(w))freq[w]=(freq[w]||0)+1});
  const score=s=>{const w=s.toLowerCase().match(/[a-z']{3,}/g)||[];return w.reduce((a,x)=>a+(freq[x]||0),0)/Math.sqrt(w.length||1)};
  const ranked=sents.map((s,i)=>({s,i,sc:score(s)})).sort((a,b)=>b.sc-a.sc);
  const keywords=Object.entries(freq).sort((a,b)=>b[1]-a[1]).slice(0,8).map(e=>e[0]);
  return{sents,ranked,keywords,top:n=>ranked.slice(0,n).sort((a,b)=>a.i-b.i).map(x=>x.s)};
}
function build(type,a,title,names){
  const details=a.top(a.sents.length);
  if(type==='summary')return{points:details,keywords:a.keywords,sources:names};
  if(type==='report')return{title,overview:a.top(3),points:details,keywords:a.keywords,sources:names};
  if(type==='mindmap')return{
    center:title,
    nodes:a.keywords.slice(0,10).map(k=>({k,tip:a.sents.filter(s=>s.toLowerCase().includes(k)).slice(0,3).join(' ')})),
    details
  };
  const slides=[{t:title,b:['Detailed presentation generated from your sources.',`${names.length} source(s) included`]}];
  slides.push({t:'Overview',b:a.top(3)});
  for(let i=0;i<details.length;i+=3)slides.push({t:'Detailed findings '+(Math.floor(i/3)+1),b:details.slice(i,i+3)});
  const themes=a.keywords.slice(0,8).map(k=>`${k}: ${a.sents.find(s=>s.toLowerCase().includes(k))||'Identified as a recurring theme in the sources.'}`);
  for(let i=0;i<themes.length;i+=3)slides.push({t:'Themes and context '+(Math.floor(i/3)+1),b:themes.slice(i,i+3)});
  return{slides};
}
function generate(){
  const text=state.sources.map(s=>s.text).join('\n\n').trim();
  if(!text){toast('Add a TXT/MD/CSV file or paste text first.');return}
  const a=analyze(text);
  if(!a.sents.length){toast('Not enough text to analyse — try a longer source.');return}
  const names=state.sources.map(s=>s.name),title=(names[0]||'Untitled').replace(/\.\w+$/,'');
  const rec={id:Date.now(),title,type:state.output,created:Date.now(),payload:build(state.output,a,title,names)};
  const h=store.get(K('history'),[]);h.unshift(rec);store.set(K('history'),h.slice(0,50));
  showRecord(rec,true);
}

/* ---------- output rendering ---------- */
const li=a=>a.map(x=>`<li>${esc(x)}</li>`).join('');
function showRecord(rec,unsaved,idx=0){
  const p=rec.payload,T=TYPES.find(t=>t.id===rec.type);let body='';
  if(rec.type==='summary')body=`<div class="out"><h4>Detailed summary</h4><ul>${li(p.points)}</ul><h4>Main themes</h4>${p.keywords.map(k=>`<span class="chip">${esc(k)}</span>`).join('')}<h4>Sources reviewed</h4><ul>${li(p.sources||[])}</ul></div>`;
  if(rec.type==='report')body=`<div class="out"><h2>${esc(p.title)}</h2><h4>Overview</h4><ul>${li(p.overview)}</ul><h4>Detailed findings</h4><ul>${li(p.points)}</ul><h4>Main themes</h4>${p.keywords.map(k=>`<span class="chip">${esc(k)}</span>`).join('')}<h4>Sources</h4><ul>${li(p.sources)}</ul></div>`;
  if(rec.type==='mindmap')body=mindmap(p);
  if(rec.type==='presentation'){const s=p.slides[idx];body=`<div class="slide"><h3>${esc(s.t)}</h3><ul>${li(s.b)}</ul></div><div class="slidenav"><button class="ghost" id="prev" ${idx?'':'disabled'}>← Prev</button><span>${idx+1} / ${p.slides.length}</span><button class="ghost" id="next" ${idx<p.slides.length-1?'':'disabled'}>Next →</button></div>`}
  openModal(`<div class="modal-head"><h3>${T.icon} ${T.name}: ${esc(rec.title)}</h3><button class="ghost" onclick="closeModal()">✕</button></div>${body}
  <div class="modal-actions"><button class="ghost" id="copy">Copy text</button>${unsaved?'<button class="primary" id="save">Save to My Projects</button>':'<button class="ghost danger" id="del">Delete</button>'}</div>`);
  if($('#prev')){$('#prev').onclick=()=>showRecord(rec,unsaved,idx-1);$('#next').onclick=()=>showRecord(rec,unsaved,idx+1)}
  $('#copy').onclick=()=>{const text=$$('#modalBox .out,#modalBox .slide,#modalBox .mm,#modalBox .mindmap-notes').map(el=>el.textContent).join('\n');navigator.clipboard.writeText(text).then(()=>toast('Copied to clipboard'))};
  if($('#save'))$('#save').onclick=()=>{const l=store.get(K('projects'),[]);l.unshift(rec);store.set(K('projects'),l);closeModal();toast('Saved to My Projects');if(state.view==='projects')renderProjects()};
  if($('#del'))$('#del').onclick=()=>{store.set(K('projects'),store.get(K('projects'),[]).filter(x=>x.id!==rec.id));closeModal();go(state.view)};
}
function mindmap(p){
  const W=680,H=440,cx=W/2,cy=H/2,n=p.nodes.length||1;
  let s=`<svg class="mm" viewBox="0 0 ${W} ${H}">`;
  p.nodes.forEach((o,i)=>{const a=i/n*2*Math.PI-Math.PI/2,x=cx+Math.cos(a)*250,y=cy+Math.sin(a)*165;
    s+=`<line x1="${cx}" y1="${cy}" x2="${x}" y2="${y}" stroke="#29435D" stroke-width="2"/><g><title>${esc(o.tip)}</title><rect x="${x-52}" y="${y-17}" width="104" height="34" rx="17" fill="#173b58" stroke="#55C1D9"/><text x="${x}" y="${y+5}" text-anchor="middle" fill="#A5E8F2" font-size="13">${esc(o.k)}</text></g>`});
  const t=p.center.length>22?p.center.slice(0,20)+'…':p.center;
  return s+`<circle cx="${cx}" cy="${cy}" r="52" fill="#55C1D9"/><text x="${cx}" y="${cy+5}" text-anchor="middle" fill="#071729" font-weight="800" font-size="14">${esc(t)}</text></svg><p class="empty">The notes below expand each topic with details from your sources.</p><div class="mindmap-notes"><h4>Detailed source notes</h4><ul>${li(p.details||p.nodes.map(o=>o.tip).filter(Boolean))}</ul></div>`;
}

/* ---------- lists ---------- */
function recCard(r,label){const T=TYPES.find(t=>t.id===r.type);return`<div class="pcard"><b>${T.icon} ${esc(r.title)}</b><small>${T.name} · ${new Date(r.created).toLocaleDateString()}</small><div class="acts"><button class="ghost" data-open="${r.id}">${label}</button></div></div>`}
function renderProjects(){
  const l=store.get(K('projects'),[]),el=$('#plist');if(!el)return;
  el.innerHTML=l.length?`<div class="cards">${l.map(r=>recCard(r,'Open')).join('')}</div>`:'<div class="empty">No saved projects yet. Generate an output and save it.</div>';
  $$('[data-open]').forEach(b=>b.onclick=()=>showRecord(l.find(r=>r.id==b.dataset.open)));
}
function viewHistory(){
  const h=store.get(K('history'),[]);
  $('#view').innerHTML=h.length?`<div class="cards" style="margin-top:24px">${h.map(r=>recCard(r,'View')).join('')}</div><button class="ghost" id="clr" style="margin-top:18px">Clear history</button>`:'<div class="empty" style="margin-top:24px">Nothing generated yet.</div>';
  $$('[data-open]').forEach(b=>b.onclick=()=>showRecord(h.find(r=>r.id==b.dataset.open),true));
  if($('#clr'))$('#clr').onclick=()=>{store.set(K('history'),[]);viewHistory()};
}
function viewTemplates(){
  $('#view').innerHTML=`<div class="cards" style="margin-top:24px">${TEMPLATES.map((t,i)=>`<div class="pcard"><b>${t.name}</b><small>${t.desc}</small><div class="acts"><button class="ghost" data-tpl="${i}">Use template</button></div></div>`).join('')}</div>`;
  $$('[data-tpl]').forEach(b=>b.onclick=()=>{state.output=TEMPLATES[b.dataset.tpl].type;toast('Template selected — add your sources.');go('upload')});
}
function viewSettings(){
  const u=Auth.user();
  $('#view').innerHTML=`<div class="set-row"><div class="field"><label for="nm">Display name</label><input id="nm" value="${esc(u.name)}"></div><button class="primary" id="sv">Save</button></div>
  <h3 class="h3">Data</h3><p class="empty">Everything is stored in this browser only.</p><button class="ghost danger" id="wipe">Delete my projects &amp; history</button>`;
  $('#sv').onclick=()=>{const n=$('#nm').value.trim();if(!n)return;const us=store.get('ts_users',{});us[u.email].name=n;store.set('ts_users',us);$('#userName').textContent=n;$('#avatar').textContent=n[0].toUpperCase();toast('Saved')};
  $('#wipe').onclick=()=>{if(confirm('Delete all saved projects and history?')){store.set(K('projects'),[]);store.set(K('history'),[]);toast('Data deleted')}};
}

/* ---------- boot ---------- */
if(Auth.user())enterApp();
