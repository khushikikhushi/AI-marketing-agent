/* Studio — AI Creative Agency front end (plain JavaScript, no build step). */
const $ = (s, el = document) => el.querySelector(s);
const main = $('#main');
const modal = $('#modal');
let cfg = null;
let project = null;
let pollTimer = null;
let insp = null; // inspector state {cid, vi, si, tab, sig}

const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const nl = s => esc(s).replace(/\n/g, '<br>');

async function api(path, opts = {}) {
  const o = { ...opts, headers: { 'X-Studio': '1', ...(opts.headers || {}) }, credentials: 'same-origin' };
  if (o.json !== undefined) { o.body = JSON.stringify(o.json); o.headers['Content-Type'] = 'application/json'; delete o.json; }
  const r = await fetch(path, o);
  let data = null;
  try { data = await r.json(); } catch (e) { /* not json */ }
  if (r.status === 401 && data && data.login && !path.startsWith('/api/auth/')) { showAuth(); throw new Error('Please sign in.'); }
  if (!r.ok) throw new Error((data && data.error) || `Request failed (${r.status})`);
  return data;
}

function toast(msg) {
  const t = $('#toast');
  t.textContent = msg; t.classList.remove('hidden');
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.add('hidden'), 2200);
}

async function copy(text) {
  try { await navigator.clipboard.writeText(text); }
  catch (e) { const ta = document.createElement('textarea'); ta.value = text; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); ta.remove(); }
  toast('Copied');
}

const brandName = slug => (cfg.brands.find(b => b.slug === slug) || {}).name || slug;
const fmtLabel = f => (cfg.formats[f] || {}).label || f;
const ratio = f => { const x = cfg.formats[f] || { w: 4, h: 5 }; return `${x.w}/${x.h}`; };
const verOf = c => (c.versions && c.versions.length) ? c.versions[Math.min(c.current ?? c.versions.length - 1, c.versions.length - 1)] : null;
const busy = c => c.status === 'pending' || c.status === 'working';
const png = (pid, rel) => `/files/${pid}/${rel}`;

/* ------------------------------------------------------------------ routing */
function go(hash) { location.hash = hash; }
window.addEventListener('hashchange', route);
document.addEventListener('click', e => {
  const n = e.target.closest('[data-nav]');
  if (n) { e.preventDefault(); go('#/' + n.dataset.nav); }
});

function setNav(name) {
  document.querySelectorAll('.side nav a').forEach(a => a.classList.toggle('on', a.dataset.nav === name));
}

async function route() {
  stopPoll(); closeModal();
  const parts = location.hash.replace(/^#\/?/, '').split('?')[0].split('/');
  const view = parts[0] || 'projects';
  setNav(view);
  try {
    if (view === 'new') return wizard.start();
    if (view === 'p' && parts[1]) return openProject(parts[1], parts[2]);
    if (view === 'favourites') return libraryView('favourites');
    if (view === 'approved') return libraryView('approved');
    if (view === 'brands') return brandsView();
    if (view === 'drafts') return draftsView();
    if (view === 'usage') return usageView();
    if (view === 'setup') return setupView();
    if (view === 'settings') return settingsView();
    return projectsView();
  } catch (e) { main.innerHTML = `<div class="banner">${esc(e.message)}</div>`; }
}

function keyBanner() {
  if (cfg.has_key) return '';
  if (cfg.user && cfg.user.role === 'admin')
    return `<div class="banner"><b>The AI isn't connected yet.</b> Go to <a href="#/settings">Settings → Connections</a> and add your OpenAI API key. It takes a minute.</div>`;
  return `<div class="banner"><b>The AI isn't connected yet.</b> Ask your studio admin to add the OpenAI API key in Settings.</div>`;
}

/* ------------------------------------------------------------------ campaigns list */
async function projectsView() {
  const list = await api('/api/projects');
  main.innerHTML = `${keyBanner()}
    <div class="phead"><div><h1>Campaigns</h1><p class="sub" style="margin:0">Every brief you've given the studio, with its concepts and designs.</p></div>
    <div class="spacer"></div><button class="btn primary" data-nav="new">+ New creative campaign</button></div>
    ${list.length ? `<div class="libgrid">${list.map(p => `
      <div class="card" style="cursor:pointer" onclick="go('#/p/${p.id}')">
        ${p.thumb ? `<div class="shot"><img src="${p.thumb}" loading="lazy"></div>` : `<div class="loading" style="--ar:4/5">${p.status === 'error' ? 'Needs a retry' : 'In progress…'}</div>`}
        <div class="body"><div class="num">${esc(brandName(p.brand))} · ${esc(p.created || '')}</div>
        <div class="name" style="font-size:18px">${esc(p.title)}</div>
        <div class="dir">${p.count} designs ${p.selected ? '· <span style="color:var(--ok)">approved</span>' : ''}</div></div>
      </div>`).join('')}</div>`
      : `<div class="empty">No campaigns yet. Start one with <b>New creative campaign</b>.</div>`}`;
}

/* ------------------------------------------------------------------ the brief wizard */
const wizard = {
  step: 0, files: [], b: null,
  start() {
    this.step = 0; this.files = [];
    this.b = { brand: '', tones: [], tone_custom: '', idea_mode: '', idea: '', objectives: [], format: '', slides: 5, count: 5, review: true, notes: '', title: '' };
    this.render();
  },
  steps: ['Brand', 'Tone', 'Promotion', 'Assets', 'Objective', 'Details'],
  valid() {
    const b = this.b;
    switch (this.step) {
      case 0: return !!b.brand;
      case 1: return b.tones.length > 0 || b.tone_custom.trim().length > 0;
      case 2: return !!b.idea_mode && (!['specific', 'topic'].includes(b.idea_mode) || b.idea.trim().length > 3);
      case 4: return b.objectives.length > 0;
      default: return true;
    }
  },
  next() { if (!this.valid()) return; if (this.step < 5) { this.step++; this.render(); } else this.submit(); },
  back() { if (this.step > 0) { this.step--; this.render(); } },
  toggle(list, v) { const a = this.b[list]; const i = a.indexOf(v); i >= 0 ? a.splice(i, 1) : a.push(v); this.render(); },
  set(k, v, rerender = true) { this.b[k] = v; if (rerender) this.render(); else this.updateNav(); },
  updateNav() { const n = $('#wizNext'); if (n) n.disabled = !this.valid(); },
  addFiles(fl) {
    for (const f of fl) if (/\.(jpe?g|png|webp)$/i.test(f.name)) this.files.push({ f, url: URL.createObjectURL(f) });
    this.render();
  },
  removeFile(i) { this.files.splice(i, 1); this.render(); },
  render() {
    const b = this.b, s = this.step;
    let body = '';
    if (s === 0) {
      body = `<div class="q-label">01 — Brand</div><p class="q">Which brand are we creating content for?</p>
      <p class="q-help">Each brand has its own profile built from its official guidelines. The studio never mixes their identities.</p>
      <div class="cards">${cfg.brands.map(br => `<button class="choice ${b.brand === br.slug ? 'on' : ''}" onclick="wizard.pickBrand('${br.slug}')">
        <div class="brandlogo"><img src="/brand-assets/${br.slug}/${br.logo}" onerror="this.remove()"></div>
        <b>${esc(br.full_name)}${br.draft ? ' <small class="pill">draft profile</small>' : ''}</b><span>${esc(br.summary)}</span></button>`).join('')}</div>`;
    } else if (s === 1) {
      body = `<div class="q-label">02 — Tone</div><p class="q">What tone and seriousness are we going for?</p>
      <p class="q-help">Pick one or combine a few. These are creative directions, not templates.</p>
      <div class="chips">${cfg.tones.map(t => `<button class="chip ${b.tones.includes(t) ? 'on' : ''}" onclick="wizard.toggle('tones', ${esc(JSON.stringify(t))})">${esc(t)}</button>`).join('')}</div>
      <label class="field">Or describe it in your own words (optional)</label>
      <input type="text" value="${esc(b.tone_custom)}" placeholder="e.g. confident and warm, like a premium sports brand — but for maths" oninput="wizard.set('tone_custom', this.value, false)">`;
    } else if (s === 2) {
      const modes = [['specific', 'I have a specific idea', 'Tell the studio exactly what you want promoted.'],
        ['topic', 'I have a general topic', 'You know the subject; the studio develops the creative.'],
        ['original', 'Come up with something entirely on your own', 'The studio decides what to promote from the brand and its audience.'],
        ['concepts', 'Develop several campaign concepts to choose from', 'Broad exploration across very different strategies.']];
      body = `<div class="q-label">03 — Promotion</div><p class="q">Do you already have an idea, or should I develop something original?</p>
      <p class="q-help">Give as much or as little as you like. Facts you type here (dates, names, numbers) are used exactly.</p>
      <div class="cards">${modes.map(m => `<button class="choice ${b.idea_mode === m[0] ? 'on' : ''}" onclick="wizard.set('idea_mode','${m[0]}')"><b>${m[1]}</b><span>${m[2]}</span></button>`).join('')}</div>
      ${b.idea_mode ? `<label class="field">${b.idea_mode === 'specific' ? 'Explain your idea' : b.idea_mode === 'topic' ? 'What is the topic?' : 'Anything the studio should know? (optional)'}</label>
      <textarea placeholder="e.g. Registrations for the GEC Grand Final in Bahrain are open until 30 November. We want parents to register their Mathletes." oninput="wizard.set('idea', this.value, false)">${esc(b.idea)}</textarea>` : ''}`;
    } else if (s === 3) {
      body = `<div class="q-label">04 — Assets</div><p class="q">Upload your photographs or assets.</p>
      <p class="q-help">Product shots, people, events, existing posters or reference designs. They're treated as creative assets: people and logos are never redrawn or distorted. The brand's logos are added automatically. Optional; without photos the studio designs with type and graphics.</p>
      <div class="drop" id="drop" onclick="$('#fileIn').click()">Drop images here or click to browse<br><small>JPG, PNG or WEBP · several at once is fine</small></div>
      <input type="file" id="fileIn" accept=".jpg,.jpeg,.png,.webp" multiple class="hidden" onchange="wizard.addFiles(this.files)">
      <div class="thumbs">${this.files.map((x, i) => `<div><img src="${x.url}"><button onclick="wizard.removeFile(${i})">✕</button></div>`).join('')}</div>`;
    } else if (s === 4) {
      body = `<div class="q-label">05 — Objective</div><p class="q">What should the post achieve?</p>
      <p class="q-help">Choose all that apply.</p>
      <div class="chips">${cfg.objectives.map(t => `<button class="chip ${b.objectives.includes(t) ? 'on' : ''}" onclick="wizard.toggle('objectives', ${esc(JSON.stringify(t))})">${esc(t)}</button>`).join('')}</div>`;
    } else {
      const br = cfg.brands.find(x => x.slug === b.brand);
      if (!b.format) b.format = br ? br.default_format : 'portrait';
      body = `<div class="q-label">06 — Details</div><p class="q">Any additional instructions?</p>
      <p class="q-help">Important text, dates, website links, hashtags, preferred colours (within the brand), or things to avoid. All optional.</p>
      <textarea placeholder="e.g. Must include: 'Registrations close 30 Nov'. Link: gec.example.com. Avoid: trophies, clip-art numbers." oninput="wizard.set('notes', this.value, false)">${esc(b.notes)}</textarea>
      <div class="grid2">
        <div><label class="field">Format ${br ? `<small>(${esc(br.name)} guidelines default: ${esc(fmtLabel(br.default_format))})</small>` : ''}</label>
        <select onchange="wizard.set('format', this.value)">${Object.entries(cfg.formats).map(([k, f]) => `<option value="${k}" ${b.format === k ? 'selected' : ''}>${f.label} — ${f.w}×${f.h}</option>`).join('')}</select></div>
        ${b.format === 'carousel' ? `<div><label class="field">Slides per carousel</label><input type="number" min="2" max="10" value="${b.slides}" oninput="wizard.set('slides', +this.value, false)"></div>` : '<div></div>'}
        <div><label class="field">How many different designs?</label>
        <select onchange="wizard.set('count', +this.value, false)">${[5, 6, 7, 8].map(n => `<option ${b.count === n ? 'selected' : ''}>${n}</option>`).join('')}</select></div>
        <div><label class="field">Campaign name (optional)</label><input type="text" value="${esc(b.title)}" placeholder="e.g. Grand Final registrations" oninput="wizard.set('title', this.value, false)"></div>
      </div>
      <label class="toggle"><input type="checkbox" ${b.review ? 'checked' : ''} onchange="wizard.set('review', this.checked, false)">
      <span><b style="color:var(--text)">Creative director review</b> — after rendering, Claude looks at each finished image, scores it on 8 criteria and fixes anything weak before showing you. Recommended; costs roughly double and takes longer.</span></label>`;
    }
    main.innerHTML = `${keyBanner()}<div class="wizard">
      <div class="progress">${this.steps.map((_, i) => `<i class="${i <= s ? 'on' : ''}"></i>`).join('')}</div>
      ${body}
      <div class="wiz-nav">${s > 0 ? `<button class="btn ghost" onclick="wizard.back()">← Back</button>` : ''}<div class="spacer"></div>
      <button class="btn primary" id="wizNext" ${this.valid() ? '' : 'disabled'} onclick="wizard.next()">${s === 5 ? 'Brief the studio →' : s === 3 && !this.files.length ? 'Skip — no photos →' : 'Continue →'}</button></div></div>`;
    if (s === 3) {
      const d = $('#drop');
      d.addEventListener('dragover', e => { e.preventDefault(); d.classList.add('over'); });
      d.addEventListener('dragleave', () => d.classList.remove('over'));
      d.addEventListener('drop', e => { e.preventDefault(); d.classList.remove('over'); this.addFiles(e.dataTransfer.files); });
    }
  },
  pickBrand(slug) {
    const br = cfg.brands.find(x => x.slug === slug);
    this.b.brand = slug; this.b.format = br.default_format; this.render();
  },
  async submit() {
    if (!cfg.has_key) { toast('Add your Claude API key first (see the note at the top)'); return; }
    const btn = $('#wizNext'); btn.disabled = true; btn.textContent = 'Sending brief…';
    const fd = new FormData();
    fd.append('brief', JSON.stringify(this.b));
    this.files.forEach(x => fd.append('files', x.f));
    try { const r = await api('/api/projects', { method: 'POST', body: fd }); go('#/p/' + r.id); }
    catch (e) { toast(e.message); btn.disabled = false; btn.textContent = 'Brief the studio →'; }
  },
};

/* ------------------------------------------------------------------ project / gallery */
async function openProject(pid, openCid) {
  project = await api('/api/projects/' + pid);
  if (project.selected && project.selected.approval) await loadAccount();
  renderProject();
  if (openCid) openInspector(openCid);
  schedulePoll();
}

function active(p) {
  return ['concepting', 'designing'].includes(p.status) || (p.concepts || []).some(busy) || (p.approvals || []).some(a => a.state === 'publishing');
}
function schedulePoll() {
  stopPoll();
  if (project && active(project)) pollTimer = setTimeout(async () => {
    try {
      project = await api('/api/projects/' + project.id);
      renderProject(); if (insp) renderInspector(false);
    } catch (e) { /* keep trying */ }
    schedulePoll();
  }, 2500);
}
function stopPoll() { clearTimeout(pollTimer); pollTimer = null; }

async function refresh() {
  project = await api('/api/projects/' + project.id);
  renderProject(); if (insp) renderInspector(true); schedulePoll();
}

function renderProject() {
  const p = project, b = p.brief;
  const statusTxt = { concepting: 'Developing concepts', designing: 'Designing', ready: 'Ready', error: 'Needs attention' }[p.status] || p.status;
  let content = '';
  if (!p.concepts.length) {
    content = p.status === 'error'
      ? `<div class="err" style="--ar:3/1;border-radius:16px">${esc(p.error)}<button class="btn" onclick="retryProject()">Retry</button></div>`
      : `<div class="bigload"><div class="spin"></div>Your creative director is reading the brief, studying ${p.uploads.length ? 'your photos and ' : ''}the ${esc(brandName(b.brand))} guidelines, and developing ${b.count} different concepts…<small>${esc(p.stage || 'It explores twice as many ideas as it shows you, then keeps the strongest.')}</small></div>`;
  } else {
    content = `${finalPanel()}
      ${p.director_note ? `<div class="note"><b>Creative director's note</b>${nl(p.director_note)}
        ${(p.explored || []).length ? `<details class="explored"><summary>${p.explored.length} ideas explored, ${p.explored.filter(x => /kept/i.test(x)).length} kept</summary><ul>${p.explored.map(x => `<li class="${/rejected/i.test(x) ? 'rej' : ''}">${esc(x)}</li>`).join('')}</ul></details>` : ''}</div>` : ''}
      ${p.error ? `<div class="banner">${esc(p.error)}</div>` : ''}
      ${p.status === 'concepting' ? `<div class="note"><b>Working</b>Developing more concepts…</div>` : ''}
      <div class="gallery">${p.concepts.map((c, i) => cardHTML(c, i)).join('')}</div>
      ${chatPanel()}`;
  }
  main.innerHTML = `${keyBanner()}
    <div class="phead"><div><div class="meta"><span>${esc(brandName(b.brand))}</span><span>${esc(fmtLabel(b.format))}</span><span>${esc(p.created)}</span></div>
      <h1>${esc(p.title)}</h1>
      <div class="row"><span class="pill ${active(p) ? 'live' : ''}">${statusTxt}</span>
      ${(b.tones || []).map(t => `<span class="pill">${esc(t)}</span>`).join('')}</div></div>
      <div class="spacer"></div>
      ${p.concepts.length ? `<button class="btn" onclick="moreConcepts()" ${p.status === 'concepting' ? 'disabled' : ''}>+ More concepts</button>` : ''}
      ${p.concepts.some(c => c.status === 'error') ? `<button class="btn" onclick="retryProject()">Retry failed</button>` : ''}
      <button class="btn ghost small" onclick="deleteProject()">Delete</button></div>
    ${p.uploads.length ? `<h3>Uploaded assets</h3><div class="assets">${p.uploads.map(u => `<img src="${png(p.id, 'uploads/' + u.file)}" title="${esc(u.name)}">`).join('')}</div>` : ''}
    ${content}`;
}

function cardHTML(c, i) {
  const p = project, v = verOf(c);
  const ar = ratio(v ? v.format : p.brief.format);
  const sel = p.selected && p.selected.cid === c.id;
  let shot;
  if (busy(c)) shot = `<div class="loading" style="--ar:${ar}"><div class="spin"></div>${esc(c.step || 'Working…')}</div>`;
  else if (c.status === 'error' && !v) shot = `<div class="err" style="--ar:${ar}">${esc(c.error)}<button class="btn small" onclick="act('${c.id}',{action:'regenerate'})">Retry</button></div>`;
  else if (v) shot = `<img src="${png(p.id, v.pngs[0])}" loading="lazy">`;
  else shot = `<div class="loading" style="--ar:${ar}">Queued…</div>`;
  const score = v && v.review ? `<span class="badge">★ ${v.review.average}/10</span>` : '';
  const slides = v && v.pngs.length > 1 ? `<span class="badge">${v.pngs.length} slides</span>` : '';
  return `<div class="card ${sel ? 'sel' : ''}">
    <div class="shot" onclick="openInspector('${c.id}')">${shot}
      <div class="badges">${sel ? '<span class="badge ok">Selected</span>' : ''}${score}${slides}
      <button class="star ${c.favourite ? 'on' : ''}" title="Save to Saved designs" onclick="event.stopPropagation();fav('${c.id}')">${c.favourite ? '★' : '☆'}</button></div></div>
    <div class="body"><div class="num">CONCEPT ${String(i + 1).padStart(2, '0')}</div>
      <div class="name">${esc((v && v.concept ? v.concept.name : c.name))}</div>
      <div class="dir">${esc((v && v.concept ? v.concept.direction : c.direction))}</div>
      <div class="hl">“${esc(v ? v.headline : c.headline)}”</div>
      ${c.status === 'error' && v ? `<div class="issues">Last change failed: ${esc(c.error)}</div>` : ''}
      <div class="act"><button class="btn small" onclick="openInspector('${c.id}')">Open</button>
      ${v && !busy(c) ? `<button class="btn small ghost" onclick="selectDesign('${c.id}', ${c.current ?? 0})">${sel ? 'Selected ✓' : 'Select'}</button>` : ''}</div>
    </div></div>`;
}

let igAccount = null, igAccountBrand = null;
async function loadAccount() {
  const brand = project && project.brief.brand;
  if (igAccount && igAccountBrand === brand) return igAccount;
  try { igAccount = await api('/api/instagram/account?brand=' + encodeURIComponent(brand || '')); } catch (e) { igAccount = { connected: false }; }
  igAccountBrand = brand;
  return igAccount;
}
const STATE = { draft: 'Draft — editing', approved: 'Approved — ready to publish', publishing: 'Publishing…', published: 'Published on Instagram',
  tested: 'Test run complete — nothing posted', failed: 'Publishing failed — nothing posted', unknown: 'Result unknown — check Instagram', cancelled: 'Cancelled' };

function finalPanel() {
  const p = project, s = p.selected;
  if (!s || !s.approval) return '';
  const a = (p.approvals || []).find(x => x.id === s.approval);
  if (!a || a.state === 'cancelled') return '';
  const acc = igAccount && igAccount.account;
  const handle = acc ? '@' + acc.username : (igAccount && igAccount.connected === false ? `No ${brandName(p.brief.brand)} Instagram account connected${cfg.user && cfg.user.role === 'admin' ? ' (Settings → Connections)' : ' — ask your admin'}` : '…');
  const slides = a.pngs.length > 1 ? `<div class="mini-slides">${a.pngs.map((x, i) => `<img src="${png(p.id, x)}" title="Slide ${i + 1}">`).join('')}</div>` : '';
  const tags = (a.hashtags || []).join(' ');
  const full = (a.caption || '') + (tags ? '\n\n' + tags : '');
  const editable = ['draft', 'failed', 'tested'].includes(a.state);
  const test = cfg.ig_test_mode;
  let body = '';
  if (editable) {
    body = `<label class="field">Caption <small id="capCount">${full.length}/2200</small></label>
      <textarea id="apCaption" style="min-height:170px" oninput="capCount()">${esc(a.caption)}</textarea>
      <label class="field">Hashtags <small>(${(a.hashtags || []).length}/30)</small></label>
      <input type="text" id="apTags" value="${esc(tags)}" oninput="capCount()">
      <div class="row" style="margin-top:16px">
        <button class="btn primary" onclick="approvalStep('approve')">Approve final version →</button>
        <button class="btn" onclick="approvalStep('draft')">Save as draft</button>
        <button class="btn" onclick="openInspector('${a.cid}')">Edit design</button>
        <button class="btn ghost" onclick="approvalStep('cancel')">Cancel publishing</button></div>`;
  } else if (a.state === 'approved') {
    body = `<div class="igprev"><div class="ighead"><span class="igav">${acc && acc.picture ? `<img src="${esc(acc.picture)}">` : ''}</span><b>${esc(handle)}</b></div>
        <img src="${png(p.id, a.pngs[0])}"><div class="igcap"><b>${esc(acc ? acc.username : '')}</b> ${nl(full)}</div></div>
      <label class="toggle"><input type="checkbox" id="apReviewed" onchange="$('#pubBtn').disabled=!this.checked${a.already_published ? "||!$('#apAgain').checked" : ''}">
        <span>I've reviewed the final image and caption, and I want to publish this ${test ? '<b>(test run — nothing will be posted)</b>' : `to <b>${esc(handle)}</b>`}.</span></label>
      ${a.already_published ? `<label class="toggle"><input type="checkbox" id="apAgain" onchange="$('#pubBtn').disabled=!(this.checked&&$('#apReviewed').checked)"><span>This exact design was already published once. Publish it again.</span></label>` : ''}
      <div class="row" style="margin-top:16px">
        <button class="btn publish" id="pubBtn" disabled onclick="publishNow()">${test ? 'APPROVE & PUBLISH (TEST)' : 'APPROVE & PUBLISH'}</button>
        <button class="btn" onclick="approvalStep('draft')">Edit caption</button>
        <button class="btn" onclick="openInspector('${a.cid}')">Edit design</button>
        <button class="btn ghost" onclick="approvalStep('cancel')">Cancel publishing</button></div>`;
  } else if (a.state === 'publishing') {
    body = `<div class="bigload" style="padding:30px 0"><div class="spin"></div>${esc(a.progress || 'Publishing…')}<small>Don't close the black window.</small></div>`;
  } else if (a.state === 'published') {
    body = `<div class="ok-box"><b>Published — Instagram confirmed it.</b><br>${a.ig && a.ig.permalink ? `<a href="${esc(a.ig.permalink)}" target="_blank" rel="noopener">${esc(a.ig.permalink)}</a><br>` : ''}
      <small>Media ID ${esc(a.ig && a.ig.media_id)} · ${esc(a.ig && a.ig.published_at)}</small></div><div class="capbox" style="margin-top:12px">${esc(full)}</div>`;
  } else if (a.state === 'unknown') {
    body = `<div class="banner">Instagram didn't confirm the result. The post <b>may</b> have gone through. Open Instagram and check before doing anything else.</div>
      <button class="btn" onclick="approvalStep('checked')">I checked: it is NOT on Instagram — let me try again</button>`;
  }
  const last = (a.history || []).slice(-1)[0];
  return `<div class="final st-${a.state}"><div><img src="${png(p.id, a.pngs[0])}">${slides}</div>
    <div><div class="k">Final approval · ${esc(STATE[a.state] || a.state)}</div><h2 style="margin-bottom:6px">${esc(a.name)}</h2>
    <dl class="facts"><dt>Account</dt><dd>${esc(handle)} ${test ? '<span class="pill live">test mode</span>' : '<span class="pill" style="color:var(--ok)">live</span>'}</dd>
    <dt>Brand</dt><dd>${esc(brandName(p.brief.brand))}</dd><dt>Format</dt><dd>${esc(fmtLabel(a.format))}${a.pngs.length > 1 ? ` · ${a.pngs.length} slides` : ''}</dd>
    <dt>Publishing</dt><dd>Only when you click APPROVE &amp; PUBLISH. Nothing is ever posted automatically.</dd></dl>
    ${last && ['failed', 'tested'].includes(a.state) ? `<div class="${a.state === 'failed' ? 'issues' : 'note'}" style="margin-bottom:12px">${esc(last.event)}${last.detail ? ': ' + esc(last.detail) : ''}</div>` : ''}
    ${body}
    <div class="row" style="margin-top:14px"><a class="btn small" href="/files/${p.id}/${a.pngs[0]}" download>Download image</a>
      <button class="btn small ghost" onclick='copy(${esc(JSON.stringify(full))})'>Copy caption + hashtags</button></div>
    <details class="explored"><summary>History (${(a.history || []).length})</summary><ul>${(a.history || []).map(h => `<li>${esc(h.at)} — ${esc(h.event)}${h.detail ? ': ' + esc(h.detail) : ''}</li>`).join('')}</ul></details>
    </div></div>`;
}
function capCount() {
  const t = $('#apCaption').value, h = $('#apTags').value.trim();
  $('#capCount').textContent = (t.length + (h ? h.length + 2 : 0)) + '/2200';
}
const curApproval = () => project.selected && project.selected.approval;
async function approvalStep(step) {
  const aid = curApproval();
  try {
    if ($('#apCaption') && ['approve', 'draft'].includes(step))
      project = await api(`/api/projects/${project.id}/approvals/${aid}`, { method: 'PUT', json: { caption: $('#apCaption').value, hashtags: $('#apTags').value } });
    if (step === 'cancel' && !(await confirmBox('Cancel publishing this design? You can select it again later.'))) return;
    project = await api(`/api/projects/${project.id}/approvals/${aid}/${step}`, { method: 'POST', json: {} });
    toast({ approve: 'Approved. Review the final preview', draft: 'Saved as draft', cancel: 'Publishing cancelled', checked: 'OK. You can try again' }[step] || 'Done');
    renderProject(); schedulePoll();
  } catch (e) { toast(e.message); }
}
async function publishNow() {
  const btn = $('#pubBtn'); btn.disabled = true; btn.textContent = 'Starting…';
  try {
    project = await api(`/api/projects/${project.id}/approvals/${curApproval()}/publish`, { method: 'POST',
      json: { confirm: 'APPROVE & PUBLISH', reviewed: $('#apReviewed').checked, publish_again: !!($('#apAgain') && $('#apAgain').checked) } });
    renderProject(); schedulePoll();
  } catch (e) { toast(e.message); btn.disabled = false; btn.textContent = 'APPROVE & PUBLISH'; }
}
function confirmBox(msg) {
  return new Promise(res => {
    const d = document.createElement('div'); d.className = 'modal';
    d.innerHTML = `<div class="dialog"><p>${esc(msg)}</p><div class="row"><div class="spacer"></div><button class="btn ghost" data-v="0">No</button><button class="btn primary" data-v="1">Yes</button></div></div>`;
    d.addEventListener('click', e => { const b = e.target.closest('[data-v]'); if (b || e.target === d) { d.remove(); res(b && b.dataset.v === '1'); } });
    document.body.appendChild(d);
  });
}

async function act(cid, body) {
  try { await api(`/api/projects/${project.id}/concepts/${cid}/action`, { method: 'POST', json: body }); toast('On it…'); await refresh(); }
  catch (e) { toast(e.message); }
}
async function fav(cid) { project = await api(`/api/projects/${project.id}/concepts/${cid}/favourite`, { method: 'POST' }); renderProject(); if (insp) renderInspector(true); }
async function selectDesign(cid, index, caption) {
  try {
    project = await api(`/api/projects/${project.id}/approvals`, { method: 'POST', json: { cid, index, caption } });
    closeModal(); await loadAccount(); renderProject();
    toast('Selected. Edit the caption, then approve');
    main.scrollTo({ top: 0, behavior: 'smooth' });
  } catch (e) { toast(e.message); }
}
async function retryProject() { await api(`/api/projects/${project.id}/retry`, { method: 'POST' }); await refresh(); }
async function moreConcepts() { await api(`/api/projects/${project.id}/more`, { method: 'POST', json: { count: 3 } }); toast('Developing 3 more concepts'); await refresh(); }
async function deleteProject() {
  if (!(await confirmBox('Delete this campaign and all its designs? This cannot be undone.'))) return;
  await api('/api/projects/' + project.id, { method: 'DELETE' }); go('#/projects');
}

/* ------------------------------------------------------------------ inspector */
function openInspector(cid) {
  const c = project.concepts.find(x => x.id === cid); if (!c) return;
  insp = { cid, vi: c.current ?? 0, si: 0, tab: 'primary', sig: '' };
  renderInspector(true);
}
function closeModal() { insp = null; modal.classList.add('hidden'); modal.innerHTML = ''; }
modal.addEventListener('click', e => { if (e.target === modal) closeModal(); });
document.addEventListener('keydown', e => {
  if (!insp) return;
  if (e.key === 'Escape') closeModal();
  if (['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName)) return;
  if (e.key === 'ArrowRight') slide(1); if (e.key === 'ArrowLeft') slide(-1);
});
function slide(d) {
  const c = project.concepts.find(x => x.id === insp.cid); const v = c.versions[insp.vi]; if (!v) return;
  insp.si = (insp.si + d + v.pngs.length) % v.pngs.length; renderInspector(true);
}

function renderInspector(force) {
  const p = project, c = p.concepts.find(x => x.id === insp.cid);
  if (!c) return closeModal();
  const sig = [c.status, c.step, (c.versions || []).length, c.current, c.favourite, JSON.stringify(p.selected)].join('|');
  if (!force && sig === insp.sig) return;
  // A new version finished while open: jump to it.
  if (insp.sig && (c.versions || []).length !== Number(insp.sig.split('|')[2])) { insp.vi = c.current; insp.si = 0; }
  insp.sig = sig;
  if (insp.vi >= (c.versions || []).length) insp.vi = Math.max(0, (c.versions || []).length - 1);
  const v = (c.versions || [])[insp.vi];
  const k = v && v.concept ? v.concept : c;
  const sel = p.selected && p.selected.cid === c.id && p.selected.index === insp.vi;
  const others = p.concepts.filter(x => x.id !== c.id && verOf(x));
  let stage;
  if (busy(c)) stage = `<div class="loading" style="--ar:${ratio(v ? v.format : p.brief.format)}"><div class="spin"></div>${esc(c.step || 'Working…')}<small>Other designs stay as they are.</small></div>`;
  else if (!v) stage = `<div class="err" style="--ar:${ratio(p.brief.format)}">${esc(c.error || 'No design yet')}<button class="btn small" onclick="act('${c.id}',{action:'regenerate'})">Retry</button></div>`;
  else stage = `<img src="${png(p.id, v.pngs[insp.si] || v.pngs[0])}">${v.pngs.length > 1 ? `
      <button class="slidenav l" onclick="slide(-1)">‹</button><button class="slidenav r" onclick="slide(1)">›</button>
      <div class="dots">Slide ${insp.si + 1} of ${v.pngs.length}</div>` : ''}`;

  const rv = v && v.review;
  const RL = { creative_direction: 'Creative direction', visual_design: 'Visual design', typography: 'Typography', brand_identity: 'Brand identity', marketing: 'Marketing effectiveness', technical: 'Technical quality' };
  const scoreRows = rv ? Object.entries(rv.scores).map(([n, s]) => `<div class="rv" title="${esc((rv.notes || {})[n] || '')}"><span>${esc(RL[n] || n.replace(/_/g, ' '))}</span><b>${s}</b><div class="bar"><i style="width:${s * 10}%"></i></div></div>`).join('') : '';
  const roundsTxt = rv && rv.rounds && rv.rounds.length > 1 ? `<p class="rounds">${rv.rounds.length} review rounds: ${rv.rounds.map(r => `${r.average}${r.verdict === 'rethink' ? ' (rethought)' : ''}`).join(' → ')}</p>` : '';
  const notesHTML = rv && rv.notes ? `<details class="rnotes"><summary>Reviewer notes</summary>${Object.entries(rv.notes).map(([k, t]) => `<p><b>${esc(RL[k] || k)}:</b> ${esc(t)}</p>`).join('')}</details>` : '';
  const pl = v && v.plan;
  const planHTML = pl ? `<div class="lbl">Composition plan</div><dl class="facts plan">${[['Focal point', pl.focal_point], ['Read order', pl.read_order], ['Grid', pl.grid], ['Type scale', pl.type_scale], ['Image', pl.image_treatment], ['Space', pl.negative_space], ['Colour', pl.colour]].filter(x => x[1]).map(([a, b]) => `<dt>${a}</dt><dd>${esc(b)}</dd>`).join('')}</dl>` : '';
  const caps = v ? v.captions || {} : {};
  const cap = caps[insp.tab] || '';
  const tags = v ? (v.hashtags || []).join(' ') : '';
  const dis = busy(c) || !v ? 'disabled' : '';

  modal.innerHTML = `<div class="inspector">
    <div class="stage"><div class="stage-img">${stage}</div>
      ${(c.versions || []).length ? `<div class="versions"><small>Versions</small>${c.versions.map((x, i) => `
        <div class="vt ${i === insp.vi ? 'on' : ''}" title="v${x.v}: ${esc(x.instruction)}" onclick="insp.vi=${i};insp.si=0;renderInspector(true)"><img src="${png(p.id, x.pngs[0])}"></div>`).join('')}</div>` : ''}
    </div>
    <div class="info">
      <button class="btn small ghost close" onclick="closeModal()">✕ Close</button>
      <div class="q-label">${esc(k.direction)}${k.layout ? ' · ' + esc(k.layout) : ''}</div>
      <h2>${esc(k.name)}</h2>
      ${v ? `<p style="font-size:18px;color:var(--accent2)">“${esc(v.headline)}”</p>` : ''}
      ${c.status === 'error' && v ? `<p class="issues">Last change failed: ${esc(c.error)}</p>` : ''}
      ${v ? `<div class="row" style="margin:14px 0 4px">
        <button class="btn primary" onclick="selectDesign('${c.id}', ${insp.vi}, insp.tab)" ${dis}>${sel ? 'Selected ✓' : 'Select this design'}</button>
        ${insp.vi !== c.current ? `<button class="btn" onclick="useVersion()">Make this the current version</button>` : ''}
        <button class="btn" onclick="fav('${c.id}')">${c.favourite ? '★ Saved' : '☆ Save'}</button>
        <a class="btn" href="/api/projects/${p.id}/download/${c.id}/${insp.vi}">Download</a>
        <a class="btn ghost" href="/api/projects/${p.id}/download/${c.id}/${insp.vi}?scale=2">@2x</a></div>` : ''}

      <div class="lbl">Change this design <span style="text-transform:none;letter-spacing:0">(the other designs are kept)</span></div>
      <div class="actions">
        <button class="btn small" ${busy(c) ? 'disabled' : ''} onclick="act('${c.id}',{action:'regenerate'})">Regenerate this concept</button>
        <button class="btn small" ${dis} onclick="act('${c.id}',{action:'variation'})">Create a variation</button>
        <button class="btn small" ${dis} onclick="act('${c.id}',{action:'typography'})">Improve the typography</button>
        <button class="btn small" ${dis} onclick="headline('${c.id}')">Change the headline</button>
        <button class="btn small" ${dis} onclick="act('${c.id}',{action:'professional'})">More professional</button>
        <button class="btn small" ${dis} onclick="act('${c.id}',{action:'funnier'})">Funnier</button>
        <button class="btn small" ${dis} onclick="act('${c.id}',{action:'premium'})">More premium</button>
        <button class="btn small" ${busy(c) ? 'disabled' : ''} onclick="confirmBox('Replace this concept with a completely different direction? Its old versions stay in the version strip.').then(y=>y&&act('${c.id}',{action:'new_direction'}))">Completely different direction</button>
      </div>
      <div class="row" style="margin-top:10px">
        ${others.length ? `<select id="combineSel" style="width:auto;flex:1" ${dis}><option value="">Combine with another concept…</option>${others.map(o => `<option value="${o.id}">${esc(o.name)}</option>`).join('')}</select>
        <button class="btn small" ${dis} onclick="combine('${c.id}')">Combine</button>` : ''}
      </div>
      <div class="row" style="margin-top:10px">
        <select id="fmtSel" style="width:auto;flex:1" ${dis}><option value="">Recompose for another format…</option>${Object.entries(cfg.formats).filter(([f]) => !v || f !== v.format).map(([f, x]) => `<option value="${f}">${x.label} — ${x.w}×${x.h}</option>`).join('')}</select>
        <button class="btn small" ${dis} onclick="reformat('${c.id}')">Recompose</button>
      </div>
      <textarea id="customIn" style="margin-top:10px;min-height:70px" placeholder="Or describe any change… e.g. 'Make the photo larger and move the logo bottom-left'" ${dis}></textarea>
      <button class="btn small" style="margin-top:8px" ${dis} onclick="custom('${c.id}')">Apply change</button>

      ${v ? `<div class="lbl">Instagram caption</div>
      <div class="tabs">${['primary', 'alternative', 'short'].map(t => `<button class="${insp.tab === t ? 'on' : ''}" onclick="insp.tab='${t}';renderInspector(true)">${t[0].toUpperCase() + t.slice(1)}</button>`).join('')}</div>
      <div class="capbox">${esc(cap)}</div><div class="tags">${esc(tags)}</div>
      <div class="row" style="margin-top:10px"><button class="btn small" onclick='copy(${esc(JSON.stringify(cap))})'>Copy caption</button>
      <button class="btn small" onclick='copy(${esc(JSON.stringify(cap + "\n\n" + tags))})'>Copy caption + hashtags</button></div>` : ''}

      ${rv ? `<div class="lbl">Six-part creative review — ${rv.average}/10</div>
      <div class="scores">${scoreRows}</div>${roundsTxt}<p style="margin-top:10px">${nl(rv.critique)}</p>${notesHTML}` : ''}
      ${v && v.issues && v.issues.flat().length ? `<p class="issues">Layout check: ${v.issues.flat().map(esc).join(' · ')}</p>` : ''}

      ${k.central_idea ? `<div class="lbl">Central idea</div><p>${nl(k.central_idea)}</p>` : ''}
      ${k.unexpected_element ? `<div class="lbl">The unexpected element</div><p>${nl(k.unexpected_element)}</p>` : ''}
      <div class="lbl">Why this concept works</div><p>${nl(k.why_it_works)}</p>
      <div class="lbl">Intended audience response</div><p>${nl(k.audience_response)}</p>
      <div class="lbl">Visual idea</div><p>${nl(k.visual_idea)}</p>
      <div class="lbl">Emotion · Objective</div><p>${nl(k.emotion)}<br>${nl(k.objective)}</p>
      ${v && v.design_notes ? `<div class="lbl">Art direction notes</div><p>${nl(v.design_notes)}</p>` : ''}
      ${planHTML}
      ${v ? `<div class="lbl">This version</div><p>v${v.v} · ${esc(fmtLabel(v.format))} · ${esc(v.instruction)} · ${esc(v.created)}</p>` : ''}
    </div></div>`;
  modal.classList.remove('hidden');
}

async function useVersion() {
  project = await api(`/api/projects/${project.id}/concepts/${insp.cid}/current`, { method: 'POST', json: { index: insp.vi } });
  renderProject(); renderInspector(true); toast('Current version updated');
}
function headline(cid) {
  const t = prompt('Type the exact new headline, or leave empty and the studio will write a stronger one:');
  if (t === null) return;
  act(cid, { action: 'headline', instruction: t });
}
function combine(cid) { const w = $('#combineSel').value; if (!w) return toast('Choose a concept to combine with'); act(cid, { action: 'combine', with_cid: w }); }
function reformat(cid) { const f = $('#fmtSel').value; if (!f) return toast('Choose a format'); act(cid, { action: 'format', format: f }); }
function custom(cid) { const t = $('#customIn').value.trim(); if (!t) return toast('Describe the change first'); act(cid, { action: 'revise', instruction: t }); }

/* ------------------------------------------------------------------ saved & approved */
async function libraryView(kind) {
  const lib = await api('/api/library');
  const items = lib[kind];
  main.innerHTML = `<h1>${kind === 'favourites' ? 'Saved designs' : 'Approved designs'}</h1>
    <p class="sub">${kind === 'favourites' ? 'Designs you starred, across all campaigns.' : 'The design you selected for final approval in each campaign.'}</p>
    ${items.length ? `<div class="libgrid">${items.map(x => `<div class="card" style="cursor:pointer" onclick="go('#/p/${x.pid}/${x.cid}')">
      <div class="shot"><img src="${x.thumb}" loading="lazy"></div>
      <div class="body"><div class="num">${esc(brandName(x.brand))}</div><div class="name" style="font-size:18px">${esc(x.name)}</div>
      <div class="dir">${esc(x.title)}</div></div></div>`).join('')}</div>`
      : `<div class="empty">Nothing here yet.</div>`}`;
}

/* ------------------------------------------------------------------ brand library */
async function brandsView() {
  const brands = await api('/api/brands');
  main.innerHTML = `<h1>Brand guidelines library</h1>
    <p class="sub">The studio follows these profiles exactly and never mixes brands. Edit the guidelines text or add logo files (for example a transparent GEC logo) and every new design uses them.</p>
    ${brands.map(b => `<div class="brandpanel">
      <h2>${esc(b.full_name)} ${b.draft ? '<span class="pill live">draft profile, built from your campaign posters</span>' : ''}</h2><p class="sub" style="margin-bottom:10px">${esc(b.summary)}</p>
      <p style="color:var(--mute);font-size:13.5px">Default format: <b style="color:var(--text)">${esc(fmtLabel(b.default_format))}</b> · Typography: ${esc(b.fonts)}</p>
      <h3>Logos</h3><div class="logos">${b.logos.map(l => `<div class="logo-tile"><div class="im"><img src="/brand-assets/${b.slug}/${l.file}?t=${Date.now()}"></div>
        <b style="color:var(--text)">${esc(l.id)}</b><br>${esc(l.note)}
        ${b.logos.length > 1 ? `<br><button class="btn small ghost" style="margin-top:8px" onclick="delLogo('${b.slug}','${l.id}')">Remove</button>` : ''}</div>`).join('')}
        <form class="logo-tile" onsubmit="addLogo(event,'${b.slug}')"><b style="color:var(--text)">Add or replace a logo</b>
          <input type="file" name="file" accept=".png,.jpg,.jpeg,.webp" required style="margin:8px 0;padding:6px">
          <input type="text" name="id" placeholder="Name, e.g. gec-white" required style="padding:8px;margin-bottom:6px">
          <input type="text" name="note" placeholder="When to use it" style="padding:8px;margin-bottom:8px">
          <button class="btn small primary">Upload</button><br><small>Same name replaces an existing logo.</small></form></div>
      <h3>Reference library <small style="text-transform:none;letter-spacing:0">(${(b.references || []).length}) · past work the director studies for principles, never copies</small></h3>
      <div class="refs">${(b.references || []).map(r => `<div class="ref"><img src="/brand-assets/${b.slug}/${r.file}" title="${esc(r.note)}" loading="lazy"><button onclick="delRef('${b.slug}','${esc(r.file)}')">✕</button></div>`).join('')}
        <form class="ref add" onsubmit="addRefs(event,'${b.slug}')"><input type="file" name="files" accept=".jpg,.jpeg,.png,.webp" multiple required><input type="text" name="note" placeholder="What's good about it (optional)"><button class="btn small primary">Add</button></form></div>
      <h3>Colours</h3><div class="swatches">${b.colours.map(c => `<div class="sw"><i style="background:${esc(c.hex)}"></i><b style="color:var(--text)">${esc(c.name)}</b> ${esc(c.hex)}<br>${esc(c.use)}</div>`).join('')}</div>
      <h3>Non-negotiable rules</h3><ul class="rules">${b.hard_rules.map(r => `<li>${esc(r)}</li>`).join('')}</ul>
      <h3>Full guidelines text (sent to Claude with every request)</h3>
      <textarea id="g-${b.slug}" style="min-height:260px;font-size:13px">${esc(b.guidelines)}</textarea>
      <button class="btn small" style="margin-top:10px" onclick="saveGuidelines('${b.slug}')">Save guidelines</button>
    </div>`).join('')}`;
}
async function addRefs(e, slug) { e.preventDefault(); try { await api(`/api/brands/${slug}/references`, { method: 'POST', body: new FormData(e.target) }); toast('References added'); brandsView(); } catch (err) { toast(err.message); } }
async function delRef(slug, file) { if (!(await confirmBox('Remove this reference?'))) return; await api(`/api/brands/${slug}/references`, { method: 'DELETE', json: { file } }); brandsView(); }
async function saveGuidelines(slug) { await api(`/api/brands/${slug}/guidelines`, { method: 'PUT', json: { text: $('#g-' + slug).value } }); toast('Guidelines saved'); }
async function addLogo(e, slug) {
  e.preventDefault();
  try { await api(`/api/brands/${slug}/logos`, { method: 'POST', body: new FormData(e.target) }); toast('Logo saved'); brandsView(); }
  catch (err) { toast(err.message); }
}
async function delLogo(slug, id) {
  if (!(await confirmBox('Remove this logo from the brand profile?'))) return;
  try { await api(`/api/brands/${slug}/logos/${id}`, { method: 'DELETE' }); brandsView(); } catch (err) { toast(err.message); }
}

/* ------------------------------------------------------------------ campaign conversation */
let chatBusy = false;
function chatPanel() {
  const msgs = project.chat || [];
  return `<div class="chat"><h3>Talk to your creative director</h3>
    <div class="msgs" id="msgs">${msgs.map(m => `<div class="msg ${m.role}"><div>${nl(m.text)}</div>
      ${(m.actions || []).length ? `<div class="row" style="margin-top:8px">${m.actions.map(x => `<button class="btn small" onclick='runChatAction(${esc(JSON.stringify(x))})'>${esc(x.label || 'Apply')}</button>`).join('')}</div>` : ''}</div>`).join('')
      || '<p class="empty" style="padding:10px 0">Ask for an opinion, push back on a concept, or describe a change. Suggested changes appear as buttons, and nothing runs until you click.</p>'}
      ${chatBusy ? '<div class="msg director"><div class="spin" style="width:18px;height:18px"></div></div>' : ''}</div>
    <div class="row"><input type="text" id="chatIn" placeholder="e.g. Concept 3 feels too corporate for parents. Ideas?" onkeydown="if(event.key==='Enter')sendChat()" ${chatBusy ? 'disabled' : ''}>
    <button class="btn primary" onclick="sendChat()" ${chatBusy ? 'disabled' : ''}>Send</button></div></div>`;
}
async function sendChat() {
  const t = $('#chatIn').value.trim(); if (!t || chatBusy) return;
  chatBusy = true; project.chat = [...(project.chat || []), { role: 'client', text: t }]; renderProject();
  try { project = await api(`/api/projects/${project.id}/chat`, { method: 'POST', json: { message: t } }); }
  catch (e) { toast(e.message); }
  chatBusy = false; renderProject(); const m = $('#msgs'); if (m) m.scrollTop = m.scrollHeight;
}
function runChatAction(x) {
  if (x.kind === 'more_concepts') return moreConcepts();
  if (x.kind === 'revise' && x.concept_id) return act(x.concept_id, { action: 'revise', instruction: x.instruction || x.label });
}

/* ------------------------------------------------------------------ drafts & publishing */
async function draftsView() {
  const list = await api('/api/drafts');
  main.innerHTML = `<h1>Drafts &amp; publishing</h1><p class="sub">Every design you've taken to final approval, with its status. Nothing here is ever posted without your APPROVE &amp; PUBLISH click.</p>
    ${list.length ? `<div class="libgrid">${list.map(x => `<div class="card" style="cursor:pointer" onclick="go('#/p/${x.pid}')">
      <div class="shot"><img src="${x.thumb}" loading="lazy"><div class="badges"><span class="badge st st-${x.state}">${esc(STATE[x.state] || x.state)}</span></div></div>
      <div class="body"><div class="num">${esc(brandName(x.brand))} · ${esc(fmtLabel(x.format))}</div><div class="name" style="font-size:18px">${esc(x.name)}</div>
      <div class="dir">${esc(x.title)}</div>${x.ig && x.ig.permalink ? `<a class="dir" href="${esc(x.ig.permalink)}" target="_blank" rel="noopener" onclick="event.stopPropagation()">View on Instagram ↗</a>` : ''}
      <div class="dir">${esc(x.updated || x.created)}</div></div></div>`).join('')}</div>` : '<div class="empty">No drafts yet. Select a design in a campaign to start one.</div>'}`;
}

/* ------------------------------------------------------------------ usage */
async function usageView() {
  const u = await api('/api/usage'), t = u.totals;
  const n = x => Number(x || 0).toLocaleString();
  main.innerHTML = `<h1>Usage</h1><p class="sub">Every AI call is recorded here. Text tokens and image generation are tracked separately. For costs, add your current prices to <code>.env</code> (PRICE_TEXT_INPUT_PER_1M, PRICE_TEXT_OUTPUT_PER_1M, PRICE_PER_IMAGE). Exact billing is always at platform.openai.com → Usage.</p>
    <div class="stats"><div><small>Text calls</small><b>${n(t.text_calls)}</b></div><div><small>Input tokens</small><b>${n(t.input_tokens)}</b></div>
    <div><small>Output tokens</small><b>${n(t.output_tokens)}</b></div><div><small>Images generated / edited</small><b>${n(t.images)}</b></div>
    ${u.cost.text !== undefined ? `<div><small>Text cost (est.)</small><b>$${u.cost.text}</b></div>` : ''}${u.cost.images !== undefined ? `<div><small>Image cost (est.)</small><b>$${u.cost.images}</b></div>` : ''}</div>
    <h3>By model</h3><table class="tbl"><tr><th>Model</th><th>Kind</th><th>Calls</th><th>Input tokens</th><th>Output tokens</th><th>Images</th></tr>
    ${Object.entries(u.by_model).map(([k, m]) => `<tr><td>${esc(k)}</td><td>${m.kind}</td><td>${n(m.calls)}</td><td>${n(m.input_tokens)}</td><td>${n(m.output_tokens)}</td><td>${n(m.images)}</td></tr>`).join('')}</table>
    <h3>Recent calls</h3><table class="tbl"><tr><th>Time</th><th>Purpose</th><th>Model</th><th>Tokens in/out</th><th>Images</th></tr>
    ${u.recent.map(e => `<tr><td>${esc(e.t)}</td><td>${esc(e.purpose)}</td><td>${esc(e.model)}</td><td>${n(e.input_tokens)} / ${n(e.output_tokens)}</td><td>${e.images ? e.images + ' (' + esc(e.quality) + ', ' + esc(e.size) + ')' : ''}</td></tr>`).join('')}</table>`;
}

/* ------------------------------------------------------------------ setup & tests */
async function setupView() {
  const d = await api('/api/diagnostics');
  const ok = (b, yes, no) => `<span class="${b ? 'okc' : 'bad'}">${b ? '✓ ' + yes : '✗ ' + no}</span>`;
  const tests = [['text', 'Text AI', 'Sends one tiny request to check your key, model and brand guidelines. Costs a fraction of a cent.'],
    ['image', 'Image generation', 'Generates one low-quality test image. Costs a few cents.'], ['edit', 'Image editing', 'Edits the test image (run the generation test first).'],
    ['brands', 'Brand profiles', 'Renders each brand\'s logo, colours and typeface locally. Free.'], ['instagram', 'Instagram connection', 'Read-only account check. Posts nothing.'],
    ['tunnel', 'Public link (for publishing)', 'Opens the temporary link, checks only the image is reachable and the app is blocked, then closes it. Free.']];
  main.innerHTML = `<h1>Setup &amp; tests</h1><p class="sub">Run these after adding your keys to <code>.env</code>. Each test makes a real call with your accounts and tells you exactly what works. Instagram stays in <b>test mode</b> until you turn it off yourself.</p>
    <div class="brandpanel"><dl class="facts">
      <dt>Text AI</dt><dd>${d.provider === 'claude' ? 'Claude' : 'OpenAI'} · ${esc(d.text_model)} — ${ok(d.provider === 'claude' ? d.claude_key : d.openai_key, 'key found', 'no key in .env')}</dd>
      <dt>Images</dt><dd>${esc(d.image_model)} (${esc(d.image_quality)} quality) — ${ok(d.image_generation, 'on', 'off (needs OPENAI_API_KEY, or IMAGE_GENERATION=off)')}</dd>
      <dt>Renderer</dt><dd>${ok(d.renderer, 'installed', 'missing — run setup.bat')}</dd>
      <dt>Photo cut-outs</dt><dd>${ok(d.cutouts, 'installed', 'not installed (optional)')}</dd>
      <dt>Public link</dt><dd>${ok(d.cloudflared, 'ready', 'cloudflared missing — run setup.bat')}</dd>
      <dt>Instagram</dt><dd>${ok(d.instagram, 'token found', 'no IG_ACCESS_TOKEN in .env')} · ${d.ig_test_mode ? '<b style="color:var(--accent)">TEST MODE</b> (nothing is ever posted)' : '<b style="color:var(--ok)">LIVE</b>'}</dd>
      <dt>Quality control</dt><dd>up to ${d.review_rounds} review rounds per design</dd>
      <dt>Brands</dt><dd>${d.brands.map(b => `${esc(b.name)}: ${b.logos} logo(s), ${b.references} references, ${b.fonts || 'brand-default'} font files, ${b.guidelines_chars.toLocaleString()} characters of guidelines`).join('<br>')}</dd></dl></div>
    ${tests.map(([k, t, desc]) => `<div class="testrow"><div><b>${t}</b><br><small>${desc}</small><div id="tr-${k}" class="tres"></div></div><button class="btn" onclick="runTest('${k}', this)">Run test</button></div>`).join('')}`;
}
async function runTest(k, btn) {
  btn.disabled = true; const out = $('#tr-' + k); out.innerHTML = '<span class="spin" style="display:inline-block;width:16px;height:16px;vertical-align:middle"></span> Running…';
  try {
    const r = await api('/api/diagnostics/' + k, { method: 'POST' });
    out.innerHTML = `<span class="${r.ok ? 'okc' : 'bad'}">${r.ok ? '✓' : '✗'} ${esc(r.detail)}</span> <small>(${r.seconds}s)</small>
      ${r.image ? `<br><img src="${r.image}?t=${Date.now()}" class="timg">` : ''}${(r.images || []).map(i => `<img src="${i}?t=${Date.now()}" class="timg">`).join('')}`;
  } catch (e) { out.innerHTML = `<span class="bad">✗ ${esc(e.message)}</span>`; }
  btn.disabled = false;
}

/* ------------------------------------------------------------------ sign in */
function authShell(inner) {
  document.body.classList.add('authmode');
  main.innerHTML = `<div class="authbox"><div class="mark" style="margin-bottom:26px"><span class="mark-dot"></span>Studio<small>AI creative agency</small></div>${inner}</div>`;
}
async function showAuth() {
  const st = await api('/api/auth/state');
  if (!st.has_users) {
    authShell(`<h2>Create the admin account</h2><p class="sub">You're the first person here, so you'll be the studio admin: you connect OpenAI and Instagram and invite your team.</p>
      <form onsubmit="authSubmit(event,'setup-admin')"><label class="field">Your name</label><input type="text" name="name" required>
      <label class="field">Email</label><input type="text" name="email" required autocomplete="username">
      <label class="field">Password (at least 10 characters)</label><input type="password" name="password" required minlength="10" autocomplete="new-password">
      <button class="btn primary wide" style="margin-top:22px">Create admin account</button><p class="issues" id="authErr"></p></form>`);
  } else if (!st.user) {
    authShell(`<h2>Sign in</h2><form onsubmit="authSubmit(event,'login')"><label class="field">Email</label><input type="text" name="email" required autocomplete="username">
      <label class="field">Password</label><input type="password" name="password" required autocomplete="current-password">
      <button class="btn primary wide" style="margin-top:22px">Sign in</button><p class="issues" id="authErr"></p>
      <p class="sub" style="font-size:13px;margin-top:14px">No account? Ask your studio admin to add you.</p></form>`);
  } else if (st.user.must_change) {
    authShell(`<h2>Choose your own password</h2><p class="sub">You signed in with a temporary password. Set your own to continue.</p>
      <form onsubmit="pwSubmit(event)"><label class="field">Temporary password</label><input type="password" name="current" required>
      <label class="field">New password (at least 10 characters)</label><input type="password" name="new" required minlength="10" autocomplete="new-password">
      <button class="btn primary wide" style="margin-top:22px">Save and continue</button><p class="issues" id="authErr"></p></form>`);
  } else { return enter(st); }
}
async function authSubmit(e, kind) {
  e.preventDefault();
  const f = Object.fromEntries(new FormData(e.target));
  try { await api('/api/auth/' + kind, { method: 'POST', json: f }); showAuth(); }
  catch (err) { $('#authErr').textContent = err.message; }
}
async function pwSubmit(e) {
  e.preventDefault();
  try { await api('/api/auth/password', { method: 'POST', json: Object.fromEntries(new FormData(e.target)) }); showAuth(); }
  catch (err) { $('#authErr').textContent = err.message; }
}
async function logout() { await api('/api/auth/logout', { method: 'POST' }); location.hash = ''; location.reload(); }

async function enter(st) {
  document.body.classList.remove('authmode');
  cfg = await api('/api/config');
  const admin = cfg.user && cfg.user.role === 'admin';
  document.querySelectorAll('[data-admin]').forEach(el => el.classList.toggle('hidden', !admin));
  $('#modelInfo').innerHTML = `<b style="color:var(--text)">${esc(cfg.user.name)}</b> · ${esc(cfg.user.role)}<br>
    ${cfg.provider === 'claude' ? 'Claude' : 'OpenAI'} · ${esc(cfg.model)} · images ${cfg.image_generation ? 'on' : 'off'}<br>
    Instagram: ${Object.keys(cfg.ig_accounts || {}).length ? Object.values(cfg.ig_accounts).map(u => '@' + esc(u)).join(', ') : 'not connected'}
    · ${cfg.ig_test_mode ? '<b style="color:var(--accent)">test mode</b>' : '<b style="color:var(--ok)">live</b>'}<br>
    <a href="#" onclick="event.preventDefault();logout()">Sign out</a>`;
  if (st && st.needs_setup && !location.hash.startsWith('#/settings')) { location.hash = '#/settings'; return; }
  route();
}

/* ------------------------------------------------------------------ settings & connections */
async function settingsView() {
  const admin = cfg.user.role === 'admin';
  const q = new URLSearchParams(location.hash.split('?')[1] || '');
  const msg = { connected: ['ok', 'Instagram account connected.'], cancelled: ['bad', 'Instagram login was cancelled.'], expired: ['bad', 'That login took too long. Try again.'], failed: ['bad', 'Instagram login failed. See the details below.'] }[q.get('ig')];
  let html = `<h1>Settings</h1>`;
  if (!admin) {
    main.innerHTML = html + `<p class="sub">Your studio admin manages connections. You can change your password here.</p>${pwCard()}`;
    return;
  }
  const st = await api('/api/settings'), users = await api('/api/users');
  const step = (n, done, title, body) => `<div class="brandpanel setstep ${done ? 'done' : ''}"><div class="stepnum">${done ? '✓' : n}</div><div style="flex:1;min-width:0"><h2>${title}</h2>${body}</div></div>`;
  const brands = Object.entries(st.instagram);
  const anyIg = brands.some(([, a]) => a.connected);
  html += `<p class="sub">Connect the studio once. Your team then just signs in and creates. Keys are stored encrypted on the server and never shown again.</p>
    ${msg ? `<div class="banner ${msg[0] === 'ok' ? 'okb' : ''}">${msg[1]}</div>` : ''}
    ${step(1, !!st.openai, 'Connect OpenAI', st.openai
      ? `<p>Connected with key <code>${esc(st.openai)}</code>${st.openai_from_env ? ' (from the server environment)' : ''}. Image generation is ${st.image_generation ? 'on' : 'off'}.</p>
         <div class="row"><button class="btn small" onclick="$('#okey').classList.toggle('hidden')">Replace key</button>${st.openai_from_env ? '' : '<button class="btn small ghost" onclick="delKey()">Remove</button>'}
         <label class="toggle" style="margin:0"><input type="checkbox" ${st.image_generation ? 'checked' : ''} onchange="setFlag('image_generation', this.checked)"><span>Image generation</span></label></div>`
      : `<p>Get a key at <a href="https://platform.openai.com/api-keys" target="_blank" rel="noopener">platform.openai.com → API keys</a>. Add billing credit first: the API is paid separately from ChatGPT.</p>`)
      .replace('</div></div>', `<form id="okey" class="row ${st.openai ? 'hidden' : ''}" style="margin-top:12px" onsubmit="saveKey(event)"><input type="password" name="key" placeholder="sk-…" autocomplete="off" style="flex:1"><button class="btn primary">Save &amp; test</button></form><p class="issues" id="keyErr"></p></div></div>`)}
    ${step(2, !!(st.meta_app_id && st.meta_secret) || (!st.hosted && anyIg), st.hosted ? 'Connect your Instagram app (one time)' : 'Your Instagram app (only needed for the online version)', `
      <p>Instagram only lets apps publish through an app registered with Meta. Create it once (see the guide in the README), then paste its details here.</p>
      <ol class="steps"><li>In your Meta app, open <b>Instagram → API setup with Instagram login → Set up Instagram business login</b>.</li>
      <li>Under <b>OAuth redirect URIs</b>, add exactly: <code id="ruri">${esc(st.redirect_uri)}</code> <button class="btn small ghost" onclick="copy($('#ruri').textContent)">Copy</button>${st.hosted ? '' : '<br><small class="issues">This is your local address: Instagram login needs the hosted (https) version on Render.</small>'}</li>
      <li>Copy the <b>Instagram app ID</b> and <b>Instagram app secret</b> into the boxes below.</li></ol>
      <form class="row" onsubmit="saveMeta(event)"><input type="text" name="app_id" placeholder="Instagram app ID" value="${esc(st.meta_app_id || '')}" style="flex:1">
      <input type="password" name="app_secret" placeholder="${st.meta_secret ? 'Instagram app secret (saved)' : 'Instagram app secret'}" style="flex:1" autocomplete="off"><button class="btn primary">Save</button></form>`)}
    ${step(3, anyIg, 'Log in to each brand\'s Instagram', `
      <p>Each brand publishes to its own account. The account must be a <b>Professional</b> account (Business or Creator) and added to your Meta app as a tester. Connections renew automatically.</p>
      ${st.hosted ? '' : `<p class="note" style="margin:10px 0"><b>Running on your own computer</b>Instagram's login button needs an online (https) address, so here you paste a token instead:
        in your Meta app open <b>Instagram → API setup with Instagram login → Generate access tokens</b>, click <b>Add account</b>, log in to the brand's Instagram, then <b>Generate token</b> and copy it.
        Tokens last about 60 days; the app renews them automatically while it's running.</p>`}
      ${brands.map(([slug, a]) => `<div class="igrow"><b>${esc(a.brand)}</b>
        ${a.connected ? `<span class="okc">✓ @${esc(a.username)}</span><small>${esc(a.account_type || '')} · renews automatically · ${a.days_left} days left · connected by ${esc(a.connected_by || '')}</small>
          <span class="spacer"></span>${st.hosted ? `<a class="btn small" href="/auth/instagram/start?brand=${slug}">Reconnect</a>` : ''}<button class="btn small ghost" onclick="igDisconnect('${slug}')">Disconnect</button>`
        : st.hosted ? `<span class="spacer"></span>${st.meta_app_id && st.meta_secret ? `<a class="btn small primary" href="/auth/instagram/start?brand=${slug}">Log in with Instagram</a>` : '<small>Finish step 2 first</small>'}`
        : `<form class="row" style="flex:1" onsubmit="pasteToken(event,'${slug}')"><input type="password" name="token" placeholder="Paste access token" autocomplete="off" style="flex:1"><button class="btn small primary">Connect</button></form>`}</div>`).join('')}
      ${q.get('ig') === 'failed' ? `<p class="issues" id="igErr"></p>` : ''}`)}
    ${step(4, !st.ig_test_mode, 'Publishing mode', `
      <p>${st.ig_test_mode ? '<b style="color:var(--accent)">Test mode is ON.</b> APPROVE &amp; PUBLISH runs every check but posts nothing. Turn it off only after all tests in <a href="#/setup">Setup &amp; tests</a> pass.'
        : '<b style="color:var(--ok)">Live.</b> APPROVE &amp; PUBLISH posts to Instagram. It still always needs a person to click it.'}</p>
      ${st.ig_test_mode ? `<button class="btn" onclick="goLive()">Turn off test mode…</button>` : `<button class="btn" onclick="setFlag('ig_test_mode', true)">Switch back to test mode</button>`}`)}
    <div class="row" style="margin:6px 0 34px"><a class="btn primary" href="#/new">Start a campaign →</a><a class="btn" href="#/setup">Run tests</a></div>
    <h2>Team</h2><div class="brandpanel"><table class="tbl"><tr><th>Name</th><th>Email</th><th>Role</th><th>Last sign-in</th><th></th></tr>
      ${users.map(u => `<tr><td>${esc(u.name)}</td><td>${esc(u.email)}</td><td>${esc(u.role)}</td><td>${esc(u.last_login || '—')}</td>
        <td style="text-align:right">${u.id === cfg.user.id ? '<small>you</small>' : `<button class="btn small ghost" onclick="resetUser('${u.id}')">Reset password</button><button class="btn small ghost" onclick="removeUser('${u.id}')">Remove</button>`}</td></tr>`).join('')}</table>
      <form class="row" onsubmit="addUser(event)" style="margin-top:12px"><input type="text" name="name" placeholder="Name" style="flex:1"><input type="text" name="email" placeholder="Email" required style="flex:1.4">
      <select name="role" style="width:auto"><option value="member">Member</option><option value="admin">Admin</option></select><button class="btn primary">Add person</button></form>
      <div id="tempPw"></div><small style="color:var(--mute)">Members create campaigns, edit and approve designs, and press APPROVE &amp; PUBLISH. Admins also manage connections, brands, tests and the team.</small></div>
    ${pwCard()}`;
  main.innerHTML = html;
  if (q.get('ig') === 'failed') { const d = await api('/api/settings/last-error').catch(() => null); if (d && $('#igErr')) $('#igErr').textContent = d.error || ''; }
}
function pwCard() {
  return `<h2>Your password</h2><form class="brandpanel row" onsubmit="changePw(event)"><input type="password" name="current" placeholder="Current password" required style="flex:1">
    <input type="password" name="new" placeholder="New password (10+ characters)" required minlength="10" style="flex:1"><button class="btn">Change</button></form>`;
}
async function saveKey(e) {
  e.preventDefault(); const k = e.target.key.value.trim(); $('#keyErr').textContent = 'Testing the key…';
  try { await api('/api/settings/openai', { method: 'PUT', json: { key: k } }); toast('OpenAI connected'); cfg = await api('/api/config'); settingsView(); }
  catch (err) { $('#keyErr').textContent = err.message; }
}
async function delKey() { if (await confirmBox('Remove the OpenAI key? The studio will stop working until a new one is added.')) { await api('/api/settings/openai', { method: 'DELETE' }); settingsView(); } }
async function saveMeta(e) { e.preventDefault(); try { await api('/api/settings/meta', { method: 'PUT', json: Object.fromEntries(new FormData(e.target)) }); toast('Saved'); settingsView(); } catch (err) { toast(err.message); } }
async function pasteToken(e, slug) {
  e.preventDefault();
  try { const r = await api(`/api/settings/instagram/${slug}/token`, { method: 'PUT', json: { token: e.target.token.value } }); toast('Connected @' + r.username); settingsView(); }
  catch (err) { toast(err.message); }
}
async function igDisconnect(slug) { if (await confirmBox('Disconnect this Instagram account? Nothing can be published for this brand until it is reconnected.')) { await api('/api/settings/instagram/' + slug, { method: 'DELETE' }); settingsView(); } }
async function setFlag(k, v) { try { await api('/api/settings/flags', { method: 'PUT', json: { [k]: v } }); cfg = await api('/api/config'); enter(); } catch (e) { toast(e.message); } }
function goLive() {
  const d = document.createElement('div'); d.className = 'modal';
  d.innerHTML = `<div class="dialog"><h2>Go live?</h2><p>After this, APPROVE &amp; PUBLISH posts to the connected Instagram accounts for real. A person still has to approve and click it every time.</p>
    <p>Type <b>GO LIVE</b> to confirm.</p><input type="text" id="liveIn" autocomplete="off"><div class="row" style="margin-top:14px"><div class="spacer"></div>
    <button class="btn ghost" data-x>Cancel</button><button class="btn publish" id="liveBtn">Turn off test mode</button></div><p class="issues" id="liveErr"></p></div>`;
  d.addEventListener('click', ev => { if (ev.target === d || ev.target.hasAttribute('data-x')) d.remove(); });
  document.body.appendChild(d);
  $('#liveBtn').onclick = async () => {
    try { await api('/api/settings/flags', { method: 'PUT', json: { ig_test_mode: false, confirm: $('#liveIn').value.trim() } }); d.remove(); toast('Live publishing is on'); cfg = await api('/api/config'); enter(); }
    catch (e) { $('#liveErr').textContent = e.message; }
  };
}
async function addUser(e) {
  e.preventDefault();
  try {
    const r = await api('/api/users', { method: 'POST', json: Object.fromEntries(new FormData(e.target)) });
    await settingsView();
    $('#tempPw').innerHTML = `<div class="banner okb">Added <b>${esc(r.user.email)}</b>. Temporary password: <code>${esc(r.temp_password)}</code> <button class="btn small" onclick='copy(${esc(JSON.stringify(r.temp_password))})'>Copy</button><br>Send it to them privately along with the studio link. They'll choose their own password when they first sign in. This is shown only once.</div>`;
  } catch (err) { toast(err.message); }
}
async function resetUser(id) {
  if (!(await confirmBox('Give this person a new temporary password?'))) return;
  const r = await api(`/api/users/${id}/reset`, { method: 'POST' }); await settingsView();
  $('#tempPw').innerHTML = `<div class="banner okb">New temporary password: <code>${esc(r.temp_password)}</code> <button class="btn small" onclick='copy(${esc(JSON.stringify(r.temp_password))})'>Copy</button> (shown once)</div>`;
}
async function removeUser(id) { if (await confirmBox('Remove this person from the studio?')) { try { await api('/api/users/' + id, { method: 'DELETE' }); settingsView(); } catch (e) { toast(e.message); } } }
async function changePw(e) { e.preventDefault(); try { await api('/api/auth/password', { method: 'POST', json: Object.fromEntries(new FormData(e.target)) }); toast('Password changed'); e.target.reset(); } catch (err) { toast(err.message); } }

/* ------------------------------------------------------------------ boot */
(async function boot() {
  try { await showAuth(); }
  catch (e) { document.body.classList.add('authmode'); main.innerHTML = `<div class="authbox"><h2>The studio can't open right now</h2><p class="sub">${esc(e.message)}</p><button class="btn primary" onclick="location.reload()">Try again</button></div>`; }
})();
