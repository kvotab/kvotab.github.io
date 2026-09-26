/* ==========================================================================
   FARF31.HTML: THE PAGE

   Wiring only. The calculation is farf31-model.js (run in
   farf31-worker.js, or here where a worker cannot be started, as under
   file://), FARF31's files farf31-io.js, the presets and examples
   farf31-data.js.

   One global: F31Page, a read-only window on the state for the browser test.
   Everything else is inside the IIFE and reached through the data-on-*
   actions registered at the bottom.
   ========================================================================== */
(function () {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const esc = (s) => (typeof kvotEscapeHtml === 'function' ? kvotEscapeHtml(s) : String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])));
  const STORAGE_KEY = 'kvot-farf31-v1';
  const DEFAULT_WIDTH = 340;
  const BUILD = '2026-09-26';
  const WORKER_URL = './resources/js/farf31-worker.js?v=20260926d';
  const PALETTE = ['#bb6c5d', '#4e79a7', '#e0a458', '#59a14f', '#8e6c8a', '#76b7b2', '#d37295', '#9c755f'];
  const DEFAULT_SERIES = [[0, 1e-3], [1e5, 1e-3]];
  const M = window.Farf31Model, IO = window.Farf31IO, DATA = window.Farf31Data;

  /* ---------------------------------------------------------------------
     State
     --------------------------------------------------------------------- */
  const DEFAULT_SETTINGS = { method: 'parabola', check: true, allResponses: true, tStart: null, tEnd: null, perDecade: null, relint: null, npMax: null, npMin: null, bqMin: null };
  const DEFAULT_VIEW = { units: 'mol', logX: true, logY: true, showInput: false, showRef: true, rLogX: true, rLogY: true, tableUnits: 'both', inLogX: false };

  const state = {
    kase: null,
    view: { ...DEFAULT_VIEW },
    hiddenPairs: {},
    tab: 'release',
    sideWidth: null,
    sections: {},
    srcSel: null,
    files: [],
    reference: null,       // { name, data: {NAME: [[t, mol, bq]]}, comparison }
    result: null,          // the last run, with .series (normalised) and .input
    running: null,
    tableLimit: 400,
  };

  function exampleCase(id) {
    const ex = DATA.EXAMPLES.find((e) => e.id === id) || DATA.EXAMPLES[0];
    return sanitizeCase(JSON.parse(JSON.stringify(ex, (k, v) => (v === Infinity ? 'inf' : v))));
  }

  /** A case from anything (a stored or opened JSON): every field checked. */
  function sanitizeCase(o) {
    if (!o || typeof o !== 'object') return null;
    const num = (v, def) => { if (v === 'inf' || v === Infinity) return Infinity; const x = Number(v); return Number.isFinite(x) ? x : def; };
    const p = o.params || {};
    const k = {
      casename: typeof o.casename === 'string' && o.casename.trim() ? o.casename.trim() : 'farf',
      print: ['ON', 'OFF', 'DEBUG'].includes(o.print) ? o.print : 'DEBUG',
      diffusivity: o.diffusivity === 'ELEMENT_SPECIFIC' ? 'ELEMENT_SPECIFIC' : 'SINGLE',
      params: {
        tw: num(p.tw, 100), Pe: num(p.Pe, 10), aw: num(p.aw, 1000), F: num(p.F, NaN), awMode: p.awMode === 'F' ? 'F' : 'aw',
        eps: num(p.eps, 0.005), de: num(p.de, 3e-6), x0: num(p.x0, 1), rho: num(p.rho, 2700),
      },
      nuclides: [],
      series: {},
      settings: { ...DEFAULT_SETTINGS },
    };
    if (!Number.isFinite(k.params.F)) k.params.F = k.params.tw * k.params.aw;
    for (const n of Array.isArray(o.nuclides) ? o.nuclides : []) {
      if (!n || typeof n.name !== 'string' || !n.name.trim()) continue;
      const ka = num(n.ka, 0);
      k.nuclides.push({ name: n.name.trim(), thalf: num(n.thalf, 1e4), kd: num(n.kd, 0), ka: ka >= 0 && ka !== Infinity ? ka : 0, de: num(n.de, k.params.de), daughter: !!n.daughter, source: !!n.source });
    }
    if (k.nuclides.length) k.nuclides[k.nuclides.length - 1].daughter = false;
    const s = o.series && typeof o.series === 'object' ? o.series : {};
    for (const n of k.nuclides) {
      const pts = s[n.name];
      if (Array.isArray(pts)) {
        const clean = pts.filter((q) => Array.isArray(q) && q.length >= 2 && Number.isFinite(Number(q[0])) && Number.isFinite(Number(q[1]))).map((q) => [Number(q[0]), Number(q[1])]);
        if (clean.length) k.series[n.name] = clean;
      }
    }
    const st = o.settings && typeof o.settings === 'object' ? o.settings : {};
    if (['parabola', 'talbot', 'dehoog'].includes(st.method)) k.settings.method = st.method;
    for (const key of ['check', 'allResponses']) if (typeof st[key] === 'boolean') k.settings[key] = st[key];
    for (const key of ['tStart', 'tEnd', 'perDecade', 'relint', 'npMax', 'npMin', 'bqMin']) {
      const x = Number(st[key]);
      k.settings[key] = st[key] != null && st[key] !== '' && Number.isFinite(x) && x >= 0 ? x : null;
    }
    return k;
  }

  const forJson = (k) => JSON.parse(JSON.stringify(k, (key, v) => (v === Infinity ? 'inf' : v)));

  function saveState() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({
        kase: forJson(state.kase), view: state.view, hiddenPairs: state.hiddenPairs, tab: state.tab,
        sideWidth: state.sideWidth, sections: state.sections, srcSel: state.srcSel,
      }));
    } catch (e) { /* storage unavailable or full */ }
  }

  function loadState() {
    let s;
    try { s = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null'); } catch (e) { s = null; }
    if (!s || typeof s !== 'object') return false;
    const k = sanitizeCase(s.kase);
    if (k && k.nuclides.length) state.kase = k;
    if (s.view && typeof s.view === 'object') for (const key of Object.keys(DEFAULT_VIEW)) if (typeof s.view[key] === typeof DEFAULT_VIEW[key]) state.view[key] = s.view[key];
    if (s.hiddenPairs && typeof s.hiddenPairs === 'object') state.hiddenPairs = s.hiddenPairs;
    if (typeof s.tab === 'string') state.tab = s.tab;
    if (Number.isFinite(s.sideWidth)) state.sideWidth = s.sideWidth;
    if (s.sections && typeof s.sections === 'object') state.sections = s.sections;
    if (typeof s.srcSel === 'string') state.srcSel = s.srcSel;
    return !!state.kase;
  }

  /* ---------------------------------------------------------------------
     Formatting and parsing
     --------------------------------------------------------------------- */
  const trimZeros = (s) => s.replace(/(\.\d*?[1-9])0+$/, '$1').replace(/\.0+$/, '');
  const trimExp = (s) => s.replace(/(\.\d*?[1-9])0+e/, '$1e').replace(/\.0+e/, 'e');
  function fmt(x, sig = 4) {
    if (x === null || x === undefined || Number.isNaN(x)) return '–';
    if (typeof x !== 'number') return String(x);
    if (!Number.isFinite(x)) return x > 0 ? '∞' : '−∞';
    if (x === 0) return '0';
    const a = Math.abs(x);
    if (a >= 1e5 || a < 1e-3) return trimExp(x.toExponential(sig - 1)).replace('-', '−');
    return trimZeros(x.toPrecision(sig)).replace('-', '−');
  }
  const numberText = (v) => {
    if (v === Infinity) return 'inf';
    if (typeof v !== 'number' || !Number.isFinite(v)) return '';
    return Math.abs(v) >= 1e5 || (Math.abs(v) < 1e-3 && v !== 0) ? trimExp(v.toExponential(10)) : trimZeros(v.toPrecision(12));
  };
  /** A number typed by a person: comma decimals, a Unicode minus, 'inf'. */
  function parseNum(text, allowInf) {
    const t = String(text).trim().replace(/−/g, '-').replace(/\s+/g, '');
    if (allowInf && /^\+?(inf|infinity|∞)$/i.test(t)) return Infinity;
    const u = /^[-+]?\d+,\d+([eE][-+]?\d+)?$/.test(t) ? t.replace(',', '.') : t;
    if (!/^[-+]?(\d+\.?\d*|\.\d+)([eEdD][-+]?\d+)?$/.test(u)) return NaN;
    return Number(u.replace(/[dD]/, 'e'));
  }

  function download(name, content, type = 'text/plain') {
    const blob = content instanceof Blob ? content : new Blob([content], { type: `${type};charset=utf-8` });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 1500);
  }

  function setStatus(text, tone) {
    const el = $('f31Status');
    el.textContent = text;
    el.className = `f31-status${tone ? ` ${tone}` : ''}`;
  }

  /* ---------------------------------------------------------------------
     The (i) and its panel: the Kompartment pattern, as on
     SimpleFunctions.html. One panel at a time over the right-hand side,
     built from text nodes, closed by the ×, the same (i) or Escape.
     --------------------------------------------------------------------- */
  const info = { panel: null, key: null };

  function infoGlyph() {
    const ns = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(ns, 'svg');
    svg.setAttribute('viewBox', '0 0 16 16');
    svg.setAttribute('width', '13');
    svg.setAttribute('height', '13');
    svg.setAttribute('aria-hidden', 'true');
    svg.innerHTML = '<circle cx="8" cy="8" r="6.9" fill="none" stroke="currentColor" stroke-width="1.3"/><circle cx="8" cy="4.7" r="1" fill="currentColor"/><rect x="7.25" y="6.8" width="1.5" height="5.2" rx="0.75" fill="currentColor"/>';
    return svg;
  }

  function mountInfoButtons(root = document) {
    root.querySelectorAll('.f31-info-slot[data-info-key]').forEach((slot) => {
      const key = slot.dataset.infoKey;
      if (!TOPICS[key] || slot.firstChild) return;
      const t = resolveTopic(key);
      const b = document.createElement('button');
      b.type = 'button';
      b.className = `info-btn${info.key === key ? ' is-open' : ''}`;
      b.dataset.info = key;
      b.setAttribute('aria-label', `About ${t ? t.title : 'this setting'}`);
      b.setAttribute('aria-expanded', String(info.key === key));
      b.setAttribute('aria-controls', 'f31-info-panel');
      b.append(infoGlyph());
      b.addEventListener('click', (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        if (info.key === key) closeInfo(); else openInfo(key);
      });
      slot.append(b);
    });
  }

  function resolveTopic(key) {
    const t = TOPICS[key];
    try { return typeof t === 'function' ? t() : t; } catch (e) { return null; }
  }

  function inlineNodes(text) {
    const nodes = [];
    const re = /`([^`]+)`|\*\*([^*]+)\*\*/g;
    let at = 0;
    for (let m = re.exec(text); m; m = re.exec(text)) {
      if (m.index > at) nodes.push(document.createTextNode(text.slice(at, m.index)));
      const el = document.createElement(m[1] != null ? 'code' : 'b');
      el.textContent = m[1] != null ? m[1] : m[2];
      nodes.push(el);
      at = re.lastIndex;
    }
    if (at < text.length) nodes.push(document.createTextNode(text.slice(at)));
    return nodes;
  }

  function mk(tag, cls, ...children) {
    const el = document.createElement(tag);
    if (cls) el.className = cls;
    for (const c of children) if (c != null) el.append(c);
    return el;
  }

  function openInfo(key) {
    const t = resolveTopic(key);
    if (!t) return;
    info.key = key;
    if (!info.panel || !info.panel.isConnected) {
      const close = mk('button', 'info-panel-close', '×');
      close.type = 'button';
      close.setAttribute('aria-label', 'Close');
      close.addEventListener('click', closeInfo);
      const panel = mk('aside', 'info-panel',
        mk('div', 'info-panel-head', mk('div', 'info-panel-heading', mk('div', 'info-panel-kicker'), mk('h2', 'info-panel-title')), close),
        mk('div', 'info-panel-body'));
      panel.id = 'f31-info-panel';
      panel.setAttribute('role', 'complementary');
      panel.querySelector('.info-panel-body').tabIndex = -1;
      panel.addEventListener('keydown', (ev) => { if (ev.key === 'Escape') { ev.preventDefault(); ev.stopPropagation(); closeInfo(); } });
      document.body.append(panel);
      info.panel = panel;
    }
    const p = info.panel;
    p.querySelector('.info-panel-kicker').textContent = t.kicker || '';
    p.querySelector('.info-panel-title').textContent = t.title || '';
    const body = p.querySelector('.info-panel-body');
    const out = [];
    for (const para of [].concat(t.lead || [])) out.push(mk('p', 'info-lead', ...inlineNodes(para)));
    if (t.facts && t.facts.length) {
      const dl = mk('dl', 'info-facts');
      for (const [label, value] of t.facts) { if (value == null || value === '') continue; dl.append(mk('dt', '', label), mk('dd', '', ...inlineNodes(String(value)))); }
      out.push(dl);
    }
    for (const s of t.sections || []) {
      if (s.heading) out.push(mk('h3', '', s.heading));
      for (const para of [].concat(s.text || [])) out.push(mk('p', '', ...inlineNodes(para)));
      if (s.list) out.push(mk('ul', '', ...s.list.map((li) => mk('li', '', ...inlineNodes(li)))));
      if (s.choices) {
        const dl = mk('dl', 'info-choices');
        for (const [name, what, on] of s.choices) { dl.append(mk('dt', on ? 'is-current' : '', ...inlineNodes(name)), mk('dd', '', ...inlineNodes(what || ''))); }
        out.push(dl);
      }
    }
    if (t.more) {
      const b = mk('button', 'info-panel-more', 'Read more in Help: ', mk('b', '', t.more.label), ' →');
      b.type = 'button';
      b.addEventListener('click', () => { closeInfo(); showTab('help'); const h = document.getElementById(t.more.id); if (h) h.scrollIntoView({ block: 'start' }); });
      out.push(mk('p', 'info-panel-more-line', b));
    }
    body.replaceChildren(...out);
    body.scrollTop = 0;
    placeInfo();
    markInfoButtons();
    body.focus({ preventScroll: true });
  }

  function closeInfo() {
    const key = info.key;
    info.key = null;
    if (info.panel) info.panel.remove();
    info.panel = null;
    markInfoButtons();
    const back = document.querySelector(`[data-info="${CSS.escape(key || '')}"]`);
    if (back) back.focus({ preventScroll: true });
  }

  function markInfoButtons() {
    document.querySelectorAll('[data-info]').forEach((b) => {
      const on = info.key === b.dataset.info;
      b.classList.toggle('is-open', on);
      b.setAttribute('aria-expanded', String(on));
    });
  }

  function placeInfo() {
    if (!info.panel) return;
    const top = document.querySelector('header')?.getBoundingClientRect().bottom ?? 0;
    const foot = document.querySelector('footer')?.getBoundingClientRect().top ?? window.innerHeight;
    info.panel.style.top = `${Math.max(0, Math.round(top))}px`;
    info.panel.style.bottom = `${Math.max(0, Math.round(window.innerHeight - foot))}px`;
  }

  const more = (label, id) => ({ label, id });
  const cur = () => state.kase;
  const TOPICS = {
    'sec:case': {
      kicker: 'Section', title: 'Case and files',
      lead: 'Everything the calculation needs: the stream tube, the rock, the nuclides and what enters the tube. Start from an example, from FARF31’s own input files, or from a case saved here.',
      sections: [
        { heading: 'Dropping files', list: ['`in.dat` — the nuclides: names, half-lives, which decays into which, which have a release', '`in.par` — the parameters, and Kd (and De) per element', '`in.ts` — the release series', '`casename31.prm` — numerical settings', 'a case `.json` saved by this page', 'an `out.ts` — drawn over the result to compare'] },
        { text: 'Several at once is fine: in.dat is read first, then in.par and in.ts. When the case is complete the model runs. The files stay in the browser.' },
      ],
      more: more('Files', 'help-files'),
    },
    'set:example': {
      kicker: 'Case', title: 'Built-in examples',
      lead: 'Made-up cases to try the page with. Their parameters are plausible, not taken from any safety assessment.',
      sections: [{ choices: DATA.EXAMPLES.map((e) => [e.label, '', false]) }],
    },
    'set:casename': { kicker: 'Case', title: 'Case name', lead: 'CASENAME in in.dat: one word, used to name the files the page writes (the case file, the CSV, the .prm).' },
    'pane:table': { kicker: 'Table', title: 'The release table', lead: 'Every output time with the release of every nuclide, in mol/a, Bq/a or both. The CSV has all the times; out.ts has FARF31’s layout and leaves out, per nuclide, the times below BQMIN Bq/a.' },
    'set:write': {
      kicker: 'Case', title: 'Write FARF31’s files',
      lead: 'The case as FARF31’s standalone input: in.dat, in.par and in.ts, and the numerical settings as casename31.prm.',
      sections: [{ text: 'With the F-factor given, in.par gets ASPEC = F/tw. An infinitely deep matrix is written as PENDEP 1.0E+20, and plug flow as PECLET 1.0E+20, which the original program takes as numbers. Nuclides sharing the first two characters of their names share one KDR_XX.' }, { text: 'Sorption on the fracture surfaces is written as KA_XX lines, the page’s own keyword, only when some Ka is not zero: such an in.par goes beyond FARF31’s format.' }],
      more: more('Files', 'help-files'),
    },
    'sec:tube': {
      kicker: 'Section', title: 'Stream tube',
      lead: 'The flow path, described by the water’s travel time and a Peclet number instead of lengths and velocities, by how much rock surface the water sees, and, as an option, by sorption on that surface.',
      more: more('The model', 'help-model'),
    },
    'set:ka': () => ({
      kicker: 'Stream tube', title: 'Sorption on the fracture surfaces',
      lead: 'Linear, instantaneous sorption on the fracture walls, per element: Ka is the amount sorbed per m² of wall over the concentration in the water. The nuclide then moves through the flowing water retarded by Rf = 1 + Ka·aw, and decays in both phases; its daughters take up their own equilibrium.',
      facts: [['Unit', 'm (m³ of water per m² of surface)'], ['Set', 'per element, in the nuclide table (Input tab)'], ['In in.par', '`KA_XX`, the page’s own keyword'], ['Now', kaSummary()]],
      sections: [{ text: 'FARF31 has no sorption on the fracture surfaces: Ka = 0 (Rf = 1) is its model. An in.par with KA_ lines goes beyond FARF31’s format, so the page writes them only when some Ka is not zero.' }, { text: 'With plug flow (Pe = ∞) every member of a chain must have the same Rf: the chain then arrives, at the earliest, after Rf·tw.' }],
      more: more('The model', 'help-model'),
    }),
    'set:tw': { kicker: 'Stream tube', title: 'Travel time tw', lead: 'The groundwater travel time along the whole tube, in years (TW in in.par).', sections: [{ text: 'A negative value gives an empty output, as in FARF31: in a probabilistic calculation it marks a tube that does not reach the surface.' }] },
    'set:pe': { kicker: 'Stream tube', title: 'Peclet number', lead: 'vL/DL: advection over dispersion along the tube. The dispersion term is (tw/Pe) ∂²c/∂ζ². PECLET in in.par.', facts: [['Typical', '2 to 50'], ['Plug flow', '`inf`, when every nuclide exchanges with the matrix']], sections: [{ text: 'At high Peclet numbers the response to a pulse is a narrow peak at tw; the page’s saddle-point inversion stays accurate there, its alternative fixed Talbot contour does not above about 100.' }] },
    'set:aw': () => ({
      kicker: 'Stream tube', title: 'Flow-wetted surface',
      lead: 'The area of rock the flowing water touches, per volume of flowing water (ASPEC, 1/m). Its product with the travel time, the F-factor, governs how much the rock matrix holds back.',
      sections: [{ choices: [
        ['a_w', 'Give the surface; F = tw·aw follows.', cur().params.awMode === 'aw'],
        ['F-factor', 'Give F (a/m), as flow calculations usually deliver it; aw = F/tw follows, and in.par gets that.', cur().params.awMode === 'F'],
      ] }],
      more: more('What the inputs mean', 'help-inputs'),
    }),
    'sec:matrix': {
      kicker: 'Section', title: 'Rock matrix',
      lead: 'The stagnant pore water beside the flowing water, reached by diffusion, where the nuclides sorb. R = ε + Kd·ρ is its capacity per volume, relative to water.',
      more: more('The model', 'help-model'),
    },
    'set:eps': { kicker: 'Rock matrix', title: 'Porosity ε', lead: 'The matrix porosity (EPS): the whole capacity of the rock for a nuclide that does not sorb.' },
    'set:rho': { kicker: 'Rock matrix', title: 'Rock density ρ', lead: 'Bulk density of the rock, kg/m³, which turns Kd into a retardation. FARF31 uses 2700 unless its casename31.prm sets RHOP.' },
    'set:de': () => ({
      kicker: 'Rock matrix', title: 'Effective diffusivity De',
      lead: 'The effective diffusivity of the matrix, in m²/a — per year, as FARF31 has it (1e-13 m²/s is 3.16e-6 m²/a).',
      sections: [{ choices: [
        ['SINGLE', 'One value for every nuclide (DE in in.par).', cur().diffusivity === 'SINGLE'],
        ['ELEMENT_SPECIFIC', 'One value per element (DE_XX), set in the nuclide table on the Input tab; the SR 97 extension of FARF31.', cur().diffusivity === 'ELEMENT_SPECIFIC'],
      ] }],
    }),
    'set:x0': { kicker: 'Rock matrix', title: 'Penetration depth x0', lead: 'How deep the nuclides can diffuse into the matrix (PENDEP, m): half the distance to the next flowing fracture, or the thickness of an altered layer. Beyond x0 there is no flux.', sections: [{ text: 'A thin matrix fills up: after a time of order x0²R/De it holds the nuclides in equilibrium with the water, and the matrix then acts as a plain retardation, Rf + aw·x0·R in all, on the travel time (Rf = 1 without fracture sorption). Tick “infinitely deep” for the classical unbounded matrix.' }] },
    'sec:chain': () => ({
      kicker: 'Section', title: 'Nuclides',
      lead: 'The nuclides and their decay chains, with Kd, Ka (and De) per element and which of them enter the tube. Edited on the Input tab.',
      facts: [['Nuclides', String(cur().nuclides.length)], ['Sources', String(cur().nuclides.filter((n) => n.source).length)]],
      more: more('What the inputs mean', 'help-inputs'),
    }),
    'sec:num': {
      kicker: 'Section', title: 'Numerics and output',
      lead: 'How the transforms are inverted and where the output is given. The defaults need no attention.',
      more: more('Numerical inversion', 'help-inversion'),
    },
    'set:method': () => ({
      kicker: 'Numerics', title: 'Laplace inversion',
      lead: 'How the unit responses are brought back from the Laplace domain.',
      sections: [{ choices: [
        ['saddle-point contour', 'A parabola through the saddle point of e^(st)T(s), trapezoidal rule with step halving. Ten or more digits, also on rising edges and at high Peclet numbers.', cur().settings.method === 'parabola'],
        ['Talbot’s fixed contour', 'The fixed-Talbot contour with 28 nodes, scaled out before fronts. Six or seven digits in ordinary cases, fewer above Pe = 100.', cur().settings.method === 'talbot'],
        ['de Hoog', 'The Bromwich line with the quotient-difference acceleration: a check more than a method; slower and less accurate far below a peak.', cur().settings.method === 'dehoog'],
      ] }, { text: 'FARF31 offers Talbot, BROMEX and the steamroller; a casename31.prm naming one of them sets the nearest here.' }],
      more: more('Numerical inversion', 'help-inversion'),
    }),
    'set:check': { kicker: 'Numerics', title: 'Check against a second method', lead: 'Recomputes a spread of samples of every unit response by another inversion method (de Hoog on the Bromwich line, or the saddle-point method when de Hoog is chosen) and reports the largest relative difference over values above 1e-6 of each peak on the Summary.' },
    'set:allResponses': { kicker: 'Numerics', title: 'Unit responses of every pair', lead: 'Also compute the responses the release does not need — the own response of a nuclide that has no release, for instance — as FARF31’s out.response lists them. Off, only pairs with a source are computed.' },
    'set:range': { kicker: 'Output', title: 'Output times', lead: 'Leave empty for the automatic range: from where the first response reaches 1e-10 of its peak after its release starts, to where the last has fallen below 1e-9 of its peak after its release ends, as far as 1e12 a; when that limit cuts a release short, the Summary says so.' },
    'set:grid': { kicker: 'Output', title: 'Output grid', lead: 'A logarithmic grid with this many points per decade, plus the release’s breakpoints, refined until linear interpolation between neighbouring points is within RELINT of every midpoint, up to the maximum number of points.', facts: [['Defaults', '20 per decade, RELINT 1e-3, 2500 points'], ['FARF31’s defaults', 'NPMIN 32, NPMAX 128, RELINT 1e-2']] },
    'set:bqmin': { kicker: 'Output', title: 'out.ts from BQMIN', lead: 'When writing out.ts, each nuclide’s block starts where its release first reaches this many Bq/a and ends where it last does, as FARF31 lays out its output. The table and the CSV keep every time.', facts: [['Default', '1e-3 Bq/a (FARF31’s)']] },
    'pane:release': { kicker: 'Release', title: 'Release from the stream tube', lead: 'The rate at which each nuclide leaves the tube, in mol/a or Bq/a. The daughters include what their parents produce on the way and their own release into the tube.', sections: [{ text: 'Releases into the tube can be drawn as dashed lines, and an out.ts dropped on the page as markers; the differences at its times are listed below the chart.' }], more: more('Responses, convolution and the output', 'help-convolution') },
    'pane:responses': { kicker: 'Unit responses', title: 'Unit response functions', lead: 'The release of nuclide i after a unit pulse (1 mol at t = 0) of nuclide j enters the tube, in 1/a. “U233 ← Am241” is the U-233 that leaves the tube after one mole of Am-241 entered it.', sections: [{ text: 'The integral of a response is the fraction that leaves the tube; for i = j without decay and a finite matrix it is 1. Every run checks each integral against T(0) from the Laplace domain (or the part of it that has left by the response’s last time), and the status line and the Summary say so when one misses.' }] },
    'pane:nuclides': () => ({
      kicker: 'Input', title: 'Nuclides',
      lead: 'One row per nuclide. “→” means the next row is its daughter (IDAUGH); “Source” means a release series enters the tube (ISOURC). Rows without a daughter link start a new chain.',
      sections: [{ text: 'Kd, Ka and De are per element, keyed by the first two characters of the name as FARF31 does (U238 and U234 are both U2): editing one row changes the others with the same key.' }, { text: 'Ka (m) is the sorption on the fracture surfaces, an option of the page (FARF31 has none); leave it 0 for FARF31’s model.' }, { text: 'A half-life of `inf` makes a nuclide stable (the last member of a chain only).' }],
      more: more('What the inputs mean', 'help-inputs'),
    }),
    'pane:series': { kicker: 'Input', title: 'Release into the stream tube', lead: 'Per source, a series of time (a) and rate (mol/a). Linear between the points, zero before the first and after the last; a time given twice makes a step.', sections: [{ text: 'Type or paste pairs, one per line (spaces, commas or tabs between them); open FARF31’s in.ts or a CSV with a header row naming the nuclides; or build the series from a shape.' }] },
    'set:shape': { kicker: 'Input', title: 'Shapes', lead: 'A quick series: a constant rate between two times, a rectangular pulse of a given amount (mol) and duration, or an exponential decline with a half-time. “Add to it” sums the shape with the series already there.', sections: [{ text: 'The exponential is written as a piecewise-linear series fine enough to be within 1e-4 of the curve.' }] },
  };

  /* ---------------------------------------------------------------------
     The settings column
     --------------------------------------------------------------------- */
  function writeControls() {
    const k = cur(), p = k.params, s = k.settings;
    $('f31Casename').value = k.casename;
    $('f31CaseName').textContent = k.casename;
    $('f31Tw').value = numberText(p.tw);
    $('f31Pe').value = numberText(p.Pe);
    $('f31AwMode').value = p.awMode;
    $('f31Aw').value = numberText(p.aw);
    $('f31F').value = numberText(p.F);
    $('f31AwRow').hidden = p.awMode !== 'aw';
    $('f31FRow').hidden = p.awMode !== 'F';
    $('f31Eps').value = numberText(p.eps);
    $('f31Rho').value = numberText(p.rho);
    $('f31DeMode').value = k.diffusivity;
    $('f31De').value = numberText(p.de);
    $('f31DeRow').hidden = k.diffusivity !== 'SINGLE';
    $('f31X0').value = p.x0 === Infinity ? '' : numberText(p.x0);
    $('f31X0').disabled = p.x0 === Infinity;
    $('f31X0').placeholder = p.x0 === Infinity ? 'infinite' : '';
    $('f31X0Inf').checked = p.x0 === Infinity;
    $('f31Method').value = s.method;
    $('f31Check').checked = s.check;
    $('f31AllResp').checked = s.allResponses;
    for (const [id, key] of [['f31TStart', 'tStart'], ['f31TEnd', 'tEnd'], ['f31PerDecade', 'perDecade'], ['f31Relint', 'relint'], ['f31NpMax', 'npMax'], ['f31BqMin', 'bqMin']]) {
      $(id).value = s[key] == null ? '' : numberText(s[key]);
    }
    writeDerived();
    renderChainChips();
  }

  function writeDerived() {
    const p = cur().params;
    const aw = effectiveAw();
    $('f31AwNote').textContent = Number.isFinite(p.tw * aw) && p.tw > 0 ? `F = ${fmt(p.tw * aw)} a/m` : '';
    $('f31FNote').textContent = p.tw > 0 && Number.isFinite(p.F / p.tw) ? `aw = ${fmt(p.F / p.tw)} 1/m` : '';
    $('f31DeNote').textContent = p.de > 0 ? `${fmt(p.de / (365.25 * 86400))} m²/s` : '';
    $('f31KaNote').textContent = kaSummary();
  }

  /** Rf = 1 + Ka aw per element key, or that there is no fracture sorption. */
  function kaSummary() {
    const k = cur(), aw = effectiveAw();
    const seen = new Map();
    for (const n of k.nuclides) if (n.ka > 0 && !seen.has(keyOf(n.name))) seen.set(keyOf(n.name), n);
    if (!seen.size) return 'none: Ka = 0 for every element (Rf = 1), as in FARF31';
    return `Rf = 1 + Ka·aw: ${[...seen.values()].map((n) => `${n.name} ${fmt(1 + n.ka * aw)}`).join(', ')}`;
  }

  const effectiveAw = () => { const p = cur().params; return p.awMode === 'F' ? p.F / p.tw : p.aw; };

  function renderChainChips() {
    const k = cur();
    $('f31NucCount').textContent = String(k.nuclides.length);
    const parts = [];
    k.nuclides.forEach((n, i) => {
      const arrow = i > 0 && k.nuclides[i - 1].daughter ? '→ ' : (i > 0 ? '· ' : '');
      parts.push(`${arrow}<span class="f31-chip${n.source ? ' src' : ''}" title="${n.source ? 'has a release' : 'no release of its own'}">${esc(n.name)}</span>`);
    });
    $('f31ChainChips').innerHTML = parts.join(' ');
  }

  function markStale(why) {
    if (state.result && !state.result.stale) {
      state.result.stale = true;
      setStatus(`${why} The results shown are from the previous run; press Run.`, 'warn');
    }
  }

  function paramChanged(el) {
    const k = cur(), p = k.params, key = el.dataset.key;
    if (key === 'awMode') { p.awMode = el.value; if (p.awMode === 'F') p.F = p.tw * p.aw; else p.aw = p.F / p.tw; }
    else if (key === 'diffusivity') {
      k.diffusivity = el.value;
      if (el.value === 'ELEMENT_SPECIFIC') for (const n of k.nuclides) if (!(n.de > 0)) n.de = p.de;
      renderNucTable();
    } else if (key === 'x0Inf') {
      if (el.checked) { p.x0Finite = p.x0 === Infinity ? 1 : p.x0; p.x0 = Infinity; }
      else p.x0 = p.x0Finite > 0 ? p.x0Finite : 1;
    } else {
      const allowInf = key === 'Pe' || key === 'x0';
      const x = parseNum(el.value, allowInf);
      const bad = (msg) => { el.setCustomValidity(msg); el.reportValidity(); };
      if (Number.isNaN(x)) return bad('A number');
      if (key === 'tw' && x === 0) return bad('Not zero: a positive travel time, or negative for an empty output');
      if (key === 'Pe' && !(x > 0)) return bad('A positive number, or inf');
      if (['aw', 'F', 'eps', 'de', 'rho'].includes(key) && !(x >= 0)) return bad('Zero or positive');
      if (key === 'x0' && !(x > 0)) return bad('A positive depth');
      el.setCustomValidity('');
      if (key === 'tw' && p.awMode === 'F') { /* keep F; aw follows */ }
      p[key] = x;
      if (key === 'aw') p.F = p.tw * p.aw;
      if (key === 'F') p.aw = p.tw > 0 ? p.F / p.tw : p.aw;
      if (key === 'tw' && p.awMode === 'aw') p.F = p.tw * p.aw;
      if (key === 'de' && k.diffusivity === 'SINGLE') for (const n of k.nuclides) n.de = x;
    }
    writeControls();
    saveState();
    markStale('A parameter changed.');
  }

  function settingChanged(el) {
    const s = cur().settings, key = el.dataset.key;
    if (key === 'method') s.method = el.value;
    else if (key === 'check' || key === 'allResponses') s[key] = el.checked;
    else {
      const t = String(el.value).trim();
      if (!t) { s[key] = null; el.setCustomValidity(''); }
      else {
        const x = parseNum(t);
        if (!(x > 0)) { el.setCustomValidity('A positive number, or empty for auto'); el.reportValidity(); return; }
        el.setCustomValidity('');
        s[key] = ['perDecade', 'npMax', 'npMin'].includes(key) ? Math.round(x) : x;
      }
    }
    saveState();
    if (key !== 'bqMin') markStale('A numerical setting changed.');
  }

  /* ---------------------------------------------------------------------
     The nuclide table (Input tab)
     --------------------------------------------------------------------- */
  const keyOf = (name) => IO.elementKey(name);

  function renderNucTable() {
    const k = cur();
    const perEl = k.diffusivity === 'ELEMENT_SPECIFIC';
    const names = k.nuclides.map((n) => n.name.toUpperCase());
    const rows = k.nuclides.map((n, i) => {
      const dup = names.indexOf(n.name.toUpperCase()) !== i;
      const chainInfo = i > 0 && k.nuclides[i - 1].daughter ? `daughter of ${esc(k.nuclides[i - 1].name)}` : 'starts a chain';
      return `<tr class="${dup ? 'bad' : ''}">
        <td><input type="text" class="name" value="${esc(n.name)}" data-on-change="f31:nucEdit" data-i="${i}" data-field="name" aria-label="Name of nuclide ${i + 1}"></td>
        <td><input type="text" class="num" value="${esc(numberText(n.thalf))}" data-on-change="f31:nucEdit" data-i="${i}" data-field="thalf" aria-label="Half-life of ${esc(n.name)}"></td>
        <td class="key">${esc(keyOf(n.name))}</td>
        <td><input type="text" class="num" value="${esc(numberText(n.kd))}" data-on-change="f31:nucEdit" data-i="${i}" data-field="kd" aria-label="Kd of ${esc(n.name)}"></td>
        <td><input type="text" class="num" value="${esc(numberText(n.ka || 0))}" data-on-change="f31:nucEdit" data-i="${i}" data-field="ka" aria-label="Ka of ${esc(n.name)}"></td>
        ${perEl ? `<td><input type="text" class="num" value="${esc(numberText(n.de))}" data-on-change="f31:nucEdit" data-i="${i}" data-field="de" aria-label="De of ${esc(n.name)}"></td>` : ''}
        <td class="center"><input type="checkbox" ${n.daughter ? 'checked' : ''} ${i === k.nuclides.length - 1 ? 'disabled' : ''} data-on-change="f31:nucEdit" data-i="${i}" data-field="daughter" aria-label="${esc(n.name)} decays into the next row"></td>
        <td class="center"><input type="checkbox" ${n.source ? 'checked' : ''} data-on-change="f31:nucEdit" data-i="${i}" data-field="source" aria-label="${esc(n.name)} has a release"></td>
        <td class="chain">${chainInfo}</td>
        <td><button type="button" class="icon" title="Move up" data-on-click="f31:nucMove" data-i="${i}" data-d="-1" ${i === 0 ? 'disabled' : ''}>↑</button><button type="button" class="icon" title="Move down" data-on-click="f31:nucMove" data-i="${i}" data-d="1" ${i === k.nuclides.length - 1 ? 'disabled' : ''}>↓</button><button type="button" class="icon" title="Remove" data-on-click="f31:nucDelete" data-i="${i}">×</button></td>
      </tr>`;
    }).join('');
    $('f31NucTable').innerHTML = `<table class="f31-table f31-nuc-table"><thead><tr>
      <th class="text">Name</th><th>T½ (a)</th><th class="text">key</th><th title="Sorption in the matrix">Kd (m³/kg)</th><th title="Sorption on the fracture surfaces (not in FARF31; 0 gives its model)">Ka (m)</th>${perEl ? '<th>De (m²/a)</th>' : ''}<th class="center" title="The next row is its daughter (IDAUGH)">→</th><th class="center" title="A release enters the tube (ISOURC)">Source</th><th class="text">chain</th><th></th>
      </tr></thead><tbody>${rows}</tbody></table>`;
    const notes = [];
    if (names.some((n, i) => names.indexOf(n) !== i)) notes.push('Two rows have the same name.');
    const aw = effectiveAw();
    const r = k.nuclides.map((n) => `${n.name}: R = ${fmt(k.params.eps + n.kd * k.params.rho)}${n.ka > 0 ? `, Rf = ${fmt(1 + n.ka * aw)}` : ''}`);
    notes.push(r.join('; '));
    $('f31NucNote').textContent = notes.join(' ');
    renderChainChips();
  }

  function nucEdit(el) {
    const k = cur(), i = Number(el.dataset.i), n = k.nuclides[i], f = el.dataset.field;
    if (!n) return;
    if (f === 'name') {
      const v = el.value.trim();
      if (!v || /^[-+.\d]/.test(v) || /\s/.test(v)) { el.setCustomValidity('A name: letters then digits, no spaces (U238, Am241)'); el.reportValidity(); return; }
      el.setCustomValidity('');
      if (k.series[n.name]) { k.series[v] = k.series[n.name]; delete k.series[n.name]; }
      if (state.srcSel === n.name) state.srcSel = v;
      // a known name brings its half-life, unless the row had one of its own
      const own = DATA.halfLife(n.name);
      const untouched = own ? n.thalf === own : /^N\d+$/.test(n.name) && n.thalf === 1e4;
      n.name = v;
      const same = k.nuclides.find((m) => m !== n && keyOf(m.name) === keyOf(v));
      if (same) { n.kd = same.kd; n.ka = same.ka; n.de = same.de; }
      if (DATA.halfLife(v) && untouched) n.thalf = DATA.halfLife(v);
    } else if (f === 'daughter' || f === 'source') {
      n[f] = el.checked;
      if (f === 'source' && el.checked && !k.series[n.name]) k.series[n.name] = DEFAULT_SERIES.map((q) => q.slice());
      if (f === 'source' && el.checked) state.srcSel = n.name;
    } else {
      const x = parseNum(el.value, f === 'thalf');
      if (Number.isNaN(x) || (f === 'thalf' ? !(x > 0) : !(x >= 0))) { el.setCustomValidity(f === 'thalf' ? 'A positive number of years, or inf' : 'Zero or positive'); el.reportValidity(); return; }
      el.setCustomValidity('');
      n[f] = x;
      if (f === 'kd' || f === 'ka' || f === 'de') for (const m of k.nuclides) if (keyOf(m.name) === keyOf(n.name)) m[f] = x;
    }
    renderNucTable();
    renderSeries();
    writeDerived();
    saveState();
    markStale('The nuclides changed.');
  }

  function addNuclide() {
    const k = cur();
    let q = k.nuclides.length + 1, name = `N${q}`;
    while (k.nuclides.some((n) => n.name.toUpperCase() === name.toUpperCase())) name = `N${++q}`;
    k.nuclides.push({ name, thalf: 1e4, kd: 0, ka: 0, de: k.params.de, daughter: false, source: false });
    renderNucTable();
    renderSeries();
    saveState();
    markStale('A nuclide was added.');
  }

  function loadPreset(id) {
    const pr = DATA.PRESETS.find((p) => p.id === id);
    if (!pr) return;
    const k = cur();
    const old = new Map(k.nuclides.map((n) => [keyOf(n.name), n]));
    const make = (name, daughter, source) => {
      const o = old.get(keyOf(name));
      return { name, thalf: DATA.halfLife(name), kd: o ? o.kd : 0, ka: o ? o.ka || 0 : 0, de: o ? o.de : k.params.de, daughter, source };
    };
    if (pr.chain) k.nuclides = pr.chain.map((name, i) => make(name, i < pr.chain.length - 1, i === 0));
    else k.nuclides = pr.singles.map((name) => make(name, false, true));
    const series = {};
    for (const n of k.nuclides) if (n.source) series[n.name] = k.series[n.name] || DEFAULT_SERIES.map((q) => q.slice());
    k.series = series;
    state.srcSel = k.nuclides.find((n) => n.source)?.name || null;
    renderNucTable();
    renderSeries();
    saveState();
    markStale('A chain was loaded.');
    setStatus(`${pr.label.split(':')[0]} loaded. Kd is 0 where the element was not in the case before: set it on the Input tab.`, 'warn');
  }

  /* ---------------------------------------------------------------------
     The release series (Input tab)
     --------------------------------------------------------------------- */
  const sources = () => cur().nuclides.filter((n) => n.source);

  function renderSeries() {
    const src = sources();
    if (!src.some((n) => n.name === state.srcSel)) state.srcSel = src.length ? src[0].name : null;
    $('f31SrcPick').innerHTML = src.map((n) => `<button type="button" class="${n.name === state.srcSel ? 'active' : ''}" data-on-click="f31:pickSource" data-name="${esc(n.name)}">${esc(n.name)}</button>`).join('') || '<span class="f31-muted">Tick “Source” for a nuclide in the table above to give it a release.</span>';
    $('f31SeriesBox').hidden = !src.length;
    const s = state.srcSel ? cur().series[state.srcSel] || [] : [];
    const ta = $('f31SeriesText');
    if (document.activeElement !== ta) ta.value = s.map(([t, v]) => `${numberText(t)}\t${numberText(v)}`).join('\n');
    ta.classList.remove('bad');
    let mass = 0;
    for (let q = 0; q + 1 < s.length; q++) mass += 0.5 * (s[q + 1][0] - s[q][0]) * (s[q][1] + s[q + 1][1]);
    $('f31SeriesNote').textContent = s.length ? `${s.length} points, ${fmt(mass)} mol in all` : '';
    renderInputChart();
  }

  function parseSeriesText(text) {
    const pts = [];
    const lines = String(text).split(/\r\n|\r|\n/);
    for (let k = 0; k < lines.length; k++) {
      const s = lines[k].replace(/#.*$/, '').trim();
      if (!s) continue;
      const w = s.split(/[\s,;]+/).filter(Boolean);
      if (w.length < 2) throw new Error(`line ${k + 1}: two numbers, time and rate`);
      const a = parseNum(w[0]), b = parseNum(w[1]);
      if (!Number.isFinite(a) || !Number.isFinite(b)) throw new Error(`line ${k + 1}: “${s}” is not two numbers`);
      if (pts.length && a < pts[pts.length - 1][0]) throw new Error(`line ${k + 1}: the time ${a} comes before ${pts[pts.length - 1][0]}`);
      pts.push([a, b]);
    }
    if (pts.length < 2) throw new Error('at least two points are needed');
    return pts;
  }

  function seriesText(el) {
    if (!state.srcSel) return;
    try {
      cur().series[state.srcSel] = parseSeriesText(el.value);
      el.classList.remove('bad');
      saveState();
      markStale(`The release of ${state.srcSel} changed.`);
      renderSeries();
    } catch (e) {
      el.classList.add('bad');
      $('f31SeriesNote').textContent = `Not applied: ${e.message}.`;
    }
  }

  /** The value of a piecewise-linear series (steps allowed, zero outside)
      just left (side < 0) or right (side > 0) of t. */
  function seriesValue(pts, t, side) {
    const n = pts.length;
    if (side < 0) {
      let k = -1;
      for (let q = 0; q < n; q++) if (pts[q][0] < t) k = q;
      if (k < 0 || k === n - 1) return 0;
      const [t0, v0] = pts[k], [t1, v1] = pts[k + 1];
      return t1 === t0 ? v1 : v0 + (v1 - v0) * (t - t0) / (t1 - t0);
    }
    let k = n;
    for (let q = n - 1; q >= 0; q--) if (pts[q][0] > t) k = q;
    if (k === 0 || k === n) return 0;
    const [t0, v0] = pts[k - 1], [t1, v1] = pts[k];
    return t1 === t0 ? v0 : v0 + (v1 - v0) * (t - t0) / (t1 - t0);
  }

  function sumSeries(a, b) {
    const times = Array.from(new Set([...a.map((p) => p[0]), ...b.map((p) => p[0])])).sort((x, y) => x - y);
    const out = [];
    for (const t of times) {
      const l = seriesValue(a, t, -1) + seriesValue(b, t, -1), r = seriesValue(a, t, 1) + seriesValue(b, t, 1);
      if (l !== r) out.push([t, l], [t, r]); else out.push([t, r]);
    }
    return out;
  }

  function shapeKind() {
    const kind = $('f31ShapeKind').value;
    const lab = { constant: ['from (a)', 'to (a)', 'rate (mol/a)', ''], pulse: ['start (a)', 'duration (a)', 'amount (mol)', ''], exponential: ['from (a)', 'to (a)', 'initial rate (mol/a)', 'half-time (a)'] }[kind];
    $('f31ShapeALabel').textContent = lab[0];
    $('f31ShapeBLabel').textContent = lab[1];
    $('f31ShapeCLabel').textContent = lab[2];
    $('f31ShapeDBox').hidden = kind !== 'exponential';
  }

  function shapeApply(mode) {
    if (!state.srcSel) return;
    const kind = $('f31ShapeKind').value;
    const a = parseNum($('f31ShapeA').value), b = parseNum($('f31ShapeB').value), c = parseNum($('f31ShapeC').value), d = parseNum($('f31ShapeD').value);
    let shape;
    if (kind === 'constant') {
      if (!(b > a) || !Number.isFinite(c)) { setStatus('A constant needs “to” after “from” and a rate.', 'error'); return; }
      shape = { kind, t1: a, t2: b, rate: c };
    } else if (kind === 'pulse') {
      if (!(b > 0) || !Number.isFinite(a) || !Number.isFinite(c)) { setStatus('A pulse needs a start, a positive duration and an amount.', 'error'); return; }
      shape = { kind, t1: a, duration: b, amount: c };
    } else {
      if (!(b > a) || !Number.isFinite(c) || !(d > 0)) { setStatus('An exponential decline needs “to” after “from”, an initial rate and a positive half-time.', 'error'); return; }
      shape = { kind, t1: a, t2: b, rate: c, halfTime: d };
    }
    const pts = M.seriesFromShapes([shape]);
    const k = cur();
    k.series[state.srcSel] = mode === 'add' && k.series[state.srcSel] ? sumSeries(k.series[state.srcSel], pts) : pts;
    saveState();
    markStale(`The release of ${state.srcSel} changed.`);
    renderSeries();
    setStatus(`The release of ${state.srcSel} ${mode === 'add' ? 'has the shape added' : 'is now the shape'}: ${k.series[state.srcSel].length} points.`, 'ok');
  }

  /* ---------------------------------------------------------------------
     Running
     --------------------------------------------------------------------- */
  let worker = null;
  let workerBroken = false;
  let runSeq = 0;

  /** The case as Farf31Model.run takes it, or a message saying what is wrong. */
  function modelInput() {
    const k = cur(), p = k.params;
    const names = k.nuclides.map((n) => n.name.toUpperCase());
    if (!k.nuclides.length) return { error: 'There are no nuclides: add one on the Input tab, or load an example.' };
    const dup = names.find((n, i) => names.indexOf(n) !== i);
    if (dup) return { error: `Two nuclides are called ${dup}.` };
    const src = k.nuclides.filter((n) => n.source);
    if (!src.length) return { error: 'No nuclide has a release: tick “Source” for one on the Input tab.' };
    for (const n of src) {
      const s = k.series[n.name];
      if (!s || s.length < 2) return { error: `${n.name} is a source but has no release series (Input tab).` };
    }
    const aw = effectiveAw();
    if (p.tw > 0 && !(aw >= 0)) return { error: 'The flow-wetted surface is not a number.' };
    const settings = { method: k.settings.method, check: k.settings.check, allResponses: k.settings.allResponses };
    for (const key of ['tStart', 'tEnd', 'perDecade', 'relint', 'npMax', 'npMin']) if (k.settings[key] != null) settings[key] = k.settings[key];
    const series = {};
    for (const n of src) series[n.name] = k.series[n.name];
    return {
      input: {
        params: { tw: p.tw, Pe: p.Pe, aw, eps: p.eps, x0: p.x0, rho: p.rho },
        nuclides: k.nuclides.map((n, i) => ({ name: n.name, thalf: n.thalf, kd: n.kd, ka: n.ka || 0, de: k.diffusivity === 'SINGLE' ? p.de : n.de, daughter: i < k.nuclides.length - 1 && n.daughter, source: n.source })),
        series,
        settings,
      },
    };
  }

  function getWorker() {
    if (workerBroken) return null;
    if (worker) return worker;
    try {
      worker = new Worker(WORKER_URL);
      worker.onmessage = onWorkerMessage;
      worker.onerror = (ev) => {
        // A worker that cannot load its script (file://, a blocked URL) fails
        // here; the run is redone on the page.
        ev.preventDefault();
        const job = state.running;
        worker = null;
        workerBroken = true;
        if (job && job.viaWorker) { job.viaWorker = false; runInline(job); }
      };
      return worker;
    } catch (e) {
      workerBroken = true;
      return null;
    }
  }

  function onWorkerMessage(ev) {
    const msg = ev.data || {};
    const job = state.running;
    if (!job || msg.id !== job.id) return;
    if (msg.type === 'progress') showProgress(msg.done, msg.n, msg.what);
    else if (msg.type === 'done') finishRun(msg.result);
    else if (msg.type === 'error') failRun(msg.message);
  }

  function showProgress(done, n, what) {
    $('f31Progress').hidden = false;
    $('f31ProgressBar').style.width = `${(100 * done / Math.max(1, n)).toFixed(1)}%`;
    if (what && state.running) setStatus(`Running: ${what}…`);
  }

  function run() {
    if (state.running) return;
    const mi = modelInput();
    if (mi.error) { setStatus(mi.error, 'error'); return; }
    const job = { id: ++runSeq, t0: performance.now(), input: mi.input, viaWorker: false };
    state.running = job;
    $('f31Run').disabled = true;
    $('f31Cancel').hidden = false;
    showProgress(0, 1);
    setStatus('Running…');
    const w = getWorker();
    if (w) { job.viaWorker = true; w.postMessage({ id: job.id, input: job.input }); }
    else runInline(job);
  }

  function runInline(job) {
    setTimeout(() => {
      if (state.running !== job) return;
      try { finishRun(M.run(job.input)); } catch (e) { failRun(e.message); }
    }, 0);
  }

  function endRun() {
    state.running = null;
    $('f31Run').disabled = false;
    $('f31Cancel').hidden = true;
    $('f31Progress').hidden = true;
  }

  function finishRun(result) {
    const job = state.running;
    if (!job) return;
    endRun();
    result.input = job.input;
    result.series = {};
    for (const [name, pts] of Object.entries(job.input.series)) result.series[name] = M.normaliseSeries(pts, name);
    result.wall = performance.now() - job.t0;
    state.result = result;
    compareReference();
    const bits = [`Done in ${(result.wall / 1000).toFixed(2)} s: ${result.times.length} output times, ${result.responses.length} unit response${result.responses.length === 1 ? '' : 's'}`];
    if (result.check) bits.push(`against ${result.check.method === 'dehoog' ? 'de Hoog' : 'the saddle-point method'}, the largest relative difference is ${fmt(result.check.worst, 2)}`);
    if (result.empty) bits.splice(0, 1, 'The travel time is negative: the output is empty, as in FARF31');
    const failed = result.balance ? result.balance.failed.length : 0;
    if (failed) bits.push(`${failed === 1 ? 'one response does' : `${failed} responses do`} not carry what leaves the tube, and the release is not reliable (see Summary)`);
    const warn = failed > 0 || (result.check && result.check.worst > 1e-4);
    setStatus(`${bits.join('; ')}.`, warn ? 'warn' : 'ok');
    renderTab();
  }

  function failRun(message) {
    endRun();
    setStatus(`The run failed: ${message}`, 'error');
  }

  function cancelRun() {
    if (!state.running) return;
    if (worker) { worker.terminate(); worker = null; }
    endRun();
    setStatus('Stopped.', 'warn');
  }

  /* ---------------------------------------------------------------------
     Output at arbitrary times (for a reference out.ts)
     --------------------------------------------------------------------- */
  function outputAt(R, i, t) {
    let s = 0;
    for (const r of R.responses) {
      if (r.i !== i || !r.source || r.t.length < 2) continue;
      const ser = R.series[R.names[r.j]];
      if (ser) s += M.convolveAt(r, ser, t);
    }
    return Math.max(0, s);
  }

  function compareReference() {
    const R = state.result, ref = state.reference;
    if (!R || !ref) { if (ref) ref.comparison = null; return; }
    const rows = [];
    R.names.forEach((name, i) => {
      const pts = ref.data[name.toUpperCase()];
      if (!pts || !pts.length) return;
      let pk = 0;
      for (const p of pts) pk = Math.max(pk, p[1]);
      let w6 = 0, w3 = 0, t6 = NaN, n = 0;
      for (const [t, v] of pts) {
        const ours = outputAt(R, i, t);
        if (v > 1e-6 * pk) { const d = Math.abs(ours - v) / v; n++; if (d > w6) { w6 = d; t6 = t; } if (v > 1e-3 * pk) w3 = Math.max(w3, d); }
      }
      rows.push({ name, points: pts.length, used: n, w6, w3, t6 });
    });
    ref.comparison = rows;
  }

  /* ---------------------------------------------------------------------
     Charts
     --------------------------------------------------------------------- */
  const PLOT_CONFIG = { displaylogo: false, responsive: true, modeBarButtonsToRemove: ['select2d', 'lasso2d', 'autoScale2d'] };
  function themeColors() {
    const cs = getComputedStyle(document.documentElement);
    return {
      text: cs.getPropertyValue('--text-primary').trim() || '#333',
      grid: cs.getPropertyValue('--border-color').trim() || '#ddd',
      surface: cs.getPropertyValue('--bg-surface').trim() || '#fff',
      muted: cs.getPropertyValue('--text-muted').trim() || '#888',
      accent: cs.getPropertyValue('--color-kvot-accent').trim() || '#bb6c5d',
    };
  }
  function baseLayout(extra = {}) {
    const c = themeColors();
    return Object.assign({
      margin: { l: 70, r: 24, t: 20, b: 56 },
      paper_bgcolor: 'rgba(0,0,0,0)',
      plot_bgcolor: 'rgba(0,0,0,0)',
      font: { color: c.text, size: 11, family: 'verdana, sans-serif' },
      legend: { orientation: 'h', y: -0.2, font: { size: 10 } },
      xaxis: { gridcolor: c.grid, zeroline: false, linecolor: c.grid },
      yaxis: { gridcolor: c.grid, zeroline: false, linecolor: c.grid },
      hovermode: 'closest',
      hoverlabel: { bgcolor: c.surface, bordercolor: c.grid, font: { color: c.text, size: 11 } },
    }, extra);
  }
  const havePlotly = () => typeof Plotly !== 'undefined';
  const plain = (s) => String(s).replace(/[<>&"]/g, '');
  function resizePlots() {
    if (!havePlotly()) return;
    ['f31ChartRelease', 'f31ChartResp', 'f31ChartInput'].forEach((id) => { const el = $(id); if (el && !el.hidden && el.data) Plotly.Plots.resize(el); });
  }
  const colorOf = (i) => PALETTE[i % PALETTE.length];

  /** A log axis range from the data: a decade above the top, at most 12 down. */
  function logRange(vals) {
    let hi = -Infinity;
    for (const v of vals) if (v > 0 && v > hi) hi = v;
    if (!Number.isFinite(hi)) return undefined;
    const top = Math.ceil(Math.log10(hi) + 0.3);
    return [top - 12, top];
  }

  function showPlot(plotId, emptyId, ok, emptyText) {
    $(plotId).hidden = !ok;
    $(emptyId).hidden = ok;
    if (!ok && emptyText) $(emptyId).textContent = emptyText;
  }

  function renderRelease() {
    const R = state.result;
    const ref = state.reference;
    $('f31RefToggle').hidden = !ref;
    if (ref) { $('f31RefName').textContent = ref.name; $('f31ShowRef').checked = state.view.showRef; }
    $('f31Units').value = state.view.units;
    $('f31LogX').checked = state.view.logX;
    $('f31LogY').checked = state.view.logY;
    $('f31ShowIn').checked = state.view.showInput;
    renderRefNote();
    if (!havePlotly()) { showPlot('f31ChartRelease', 'f31ReleaseEmpty', false, 'The chart library (Plotly) did not load; the Table tab has the numbers.'); return; }
    if (!R || R.empty || !R.times.length) { showPlot('f31ChartRelease', 'f31ReleaseEmpty', false, R && R.empty ? 'The output is empty: the travel time is negative.' : 'Run the model to draw the release from the stream tube.'); return; }
    const bq = state.view.units === 'bq';
    const traces = [], all = [];
    R.names.forEach((name, i) => {
      const y = bq ? R.bq[i] : R.out[i];
      const xs = [], ys = [];
      for (let k = 0; k < R.times.length; k++) if (!state.view.logY || y[k] > 0) { xs.push(R.times[k]); ys.push(y[k]); }
      if (!ys.length) return;
      ys.forEach((v) => all.push(v));
      traces.push({ x: xs, y: ys, type: 'scatter', mode: 'lines', name: plain(name), line: { color: colorOf(i), width: 2 }, hovertemplate: `${plain(name)}<br>t = %{x:.4g} a<br>%{y:.4g} ${bq ? 'Bq/a' : 'mol/a'}<extra></extra>` });
    });
    if (state.view.showInput) {
      R.names.forEach((name, i) => {
        const s = R.input.series[name];
        if (!s) return;
        const f = bq ? M.bqPerMol(R.thalf[i]) : 1;
        const xs = [], ys = [];
        for (const [t, v] of s) if ((!state.view.logX || t > 0) && (!state.view.logY || v > 0)) { xs.push(t); ys.push(v * f); }
        if (xs.length) traces.push({ x: xs, y: ys, type: 'scatter', mode: 'lines', name: `${plain(name)} into the tube`, line: { color: colorOf(i), width: 1.2, dash: 'dash' }, hovertemplate: `${plain(name)} in<br>t = %{x:.4g} a<br>%{y:.4g}<extra></extra>` });
      });
    }
    if (ref && state.view.showRef) {
      R.names.forEach((name, i) => {
        const pts = ref.data[name.toUpperCase()];
        if (!pts) return;
        const xs = [], ys = [];
        for (const p of pts) { const v = bq ? p[2] : p[1]; if ((!state.view.logY || v > 0) && (!state.view.logX || p[0] > 0)) { xs.push(p[0]); ys.push(v); } }
        if (xs.length) traces.push({ x: xs, y: ys, type: 'scatter', mode: 'markers', name: `${plain(name)} (${plain(ref.name)})`, marker: { color: colorOf(i), size: 5, symbol: 'circle-open' }, hovertemplate: `${plain(ref.name)} ${plain(name)}<br>t = %{x:.4g} a<br>%{y:.4g}<extra></extra>` });
      });
    }
    if (!traces.length) {
      // in Bq/a a stable nuclide has no activity: say so rather than 'zero'
      const stable = bq && R.thalf.some((th) => !isFinite(th)) && R.out.some((o) => o.some((v) => v > 0));
      showPlot('f31ChartRelease', 'f31ReleaseEmpty', false, stable ? 'Every release is zero in Bq/a: a stable nuclide has no activity. Choose mol/a to see it.' : 'Every release is zero.');
      return;
    }
    showPlot('f31ChartRelease', 'f31ReleaseEmpty', true);
    const c = themeColors();
    const layout = baseLayout({
      xaxis: { title: 'time (a)', type: state.view.logX ? 'log' : 'linear', exponentformat: 'power', gridcolor: c.grid, linecolor: c.grid, zeroline: false },
      yaxis: { title: `release (${bq ? 'Bq/a' : 'mol/a'})`, type: state.view.logY ? 'log' : 'linear', exponentformat: 'power', gridcolor: c.grid, linecolor: c.grid, zeroline: false },
    });
    if (state.view.logY) { const r = logRange(all); if (r) layout.yaxis.range = r; }
    Plotly.react($('f31ChartRelease'), traces, layout, PLOT_CONFIG);
  }

  function renderRefNote() {
    const ref = state.reference, el = $('f31RefNote');
    if (!ref || !ref.comparison) { el.innerHTML = ''; return; }
    const rows = ref.comparison;
    if (!rows.length) { el.innerHTML = `<li>${esc(ref.name)} has no nuclide of this case.</li>`; return; }
    el.innerHTML = rows.map((r) => (r.used
      ? `<li>${esc(ref.name)}, ${esc(r.name)}: at its ${r.points} times the largest relative difference is ${fmt(r.w6, 3)} over values above 1e-6 of its peak (at t = ${fmt(r.t6)} a) and ${fmt(r.w3, 3)} above 1e-3.</li>`
      : `<li>${esc(ref.name)}, ${esc(r.name)}: nothing above zero to compare.</li>`)).join('');
  }

  function pairLabel(r) { return r.i === r.j ? `${r.nameI} (own)` : `${r.nameI} ← ${r.nameJ}`; }

  function renderResponses() {
    const R = state.result;
    $('f31RLogX').checked = state.view.rLogX;
    $('f31RLogY').checked = state.view.rLogY;
    if (!R || !R.responses.length) {
      $('f31Pairs').innerHTML = '';
      showPlot('f31ChartResp', 'f31RespEmpty', false, 'Run the model to draw the unit response functions.');
      return;
    }
    $('f31Pairs').innerHTML = R.responses.map((r) => {
      const key = `${r.nameI}<${r.nameJ}`;
      return `<label><input type="checkbox" ${state.hiddenPairs[key] ? '' : 'checked'} data-on-change="f31:pairToggle" data-key="${esc(key)}"><span class="f31-legend-dot" style="background:${colorOf(r.i)}"></span>${esc(pairLabel(r))}</label>`;
    }).join('');
    if (!havePlotly()) { showPlot('f31ChartResp', 'f31RespEmpty', false, 'The chart library (Plotly) did not load.'); return; }
    const traces = [], all = [];
    const DASH = ['solid', 'dash', 'dot', 'dashdot', 'longdash', 'longdashdot'];
    R.responses.forEach((r) => {
      if (state.hiddenPairs[`${r.nameI}<${r.nameJ}`]) return;
      const xs = [], ys = [];
      for (let k = 0; k < r.t.length; k++) if (!state.view.rLogY || r.h[k] > 0) { xs.push(r.t[k]); ys.push(r.h[k]); }
      if (!xs.length) return;
      ys.forEach((v) => all.push(v));
      traces.push({ x: xs, y: ys, type: 'scatter', mode: 'lines', name: plain(pairLabel(r)), line: { color: colorOf(r.i), width: 1.8, dash: DASH[Math.min(DASH.length - 1, r.i - r.j)] }, hovertemplate: `${plain(pairLabel(r))}<br>t = %{x:.4g} a<br>%{y:.4g} 1/a<extra></extra>` });
    });
    if (!traces.length) { showPlot('f31ChartResp', 'f31RespEmpty', false, 'The responses shown are all zero, or none is ticked.'); return; }
    showPlot('f31ChartResp', 'f31RespEmpty', true);
    const c = themeColors();
    const layout = baseLayout({
      xaxis: { title: 'time since the pulse entered (a)', type: state.view.rLogX ? 'log' : 'linear', exponentformat: 'power', gridcolor: c.grid, linecolor: c.grid, zeroline: false },
      yaxis: { title: 'unit response (1/a)', type: state.view.rLogY ? 'log' : 'linear', exponentformat: 'power', gridcolor: c.grid, linecolor: c.grid, zeroline: false },
    });
    if (state.view.rLogY) { const rg = logRange(all); if (rg) layout.yaxis.range = rg; }
    Plotly.react($('f31ChartResp'), traces, layout, PLOT_CONFIG);
  }

  function renderInputChart() {
    const k = cur(), src = sources();
    if (!src.length || !havePlotly()) { showPlot('f31ChartInput', 'f31InputEmpty', false, src.length ? 'The chart library (Plotly) did not load.' : 'No nuclide is marked as a source.'); return; }
    if (state.tab !== 'input') return;
    const traces = [];
    const logX = state.view.inLogX;
    $('f31InLogX').checked = logX;
    k.nuclides.forEach((n, i) => {
      if (!n.source || !k.series[n.name]) return;
      const s = k.series[n.name].filter((p) => !logX || p[0] > 0);
      traces.push({ x: s.map((p) => p[0]), y: s.map((p) => p[1]), type: 'scatter', mode: 'lines+markers', name: plain(n.name), line: { color: colorOf(i), width: n.name === state.srcSel ? 2.4 : 1.2 }, marker: { size: 4 }, hovertemplate: `${plain(n.name)}<br>t = %{x:.4g} a<br>%{y:.4g} mol/a<extra></extra>` });
    });
    showPlot('f31ChartInput', 'f31InputEmpty', true);
    const c = themeColors();
    Plotly.react($('f31ChartInput'), traces, baseLayout({
      margin: { l: 64, r: 12, t: 10, b: 44 },
      xaxis: { title: logX ? 'time (a), points at t > 0' : 'time (a)', type: logX ? 'log' : 'linear', gridcolor: c.grid, linecolor: c.grid, zeroline: false, exponentformat: 'power' },
      yaxis: { title: 'into the tube (mol/a)', gridcolor: c.grid, linecolor: c.grid, zeroline: false, exponentformat: 'power', rangemode: 'tozero' },
      legend: { orientation: 'h', y: -0.28, font: { size: 10 } },
    }), PLOT_CONFIG);
  }

  /* ---------------------------------------------------------------------
     Table and summary
     --------------------------------------------------------------------- */
  function renderTable() {
    const R = state.result;
    $('f31TableUnits').value = state.view.tableUnits;
    if (!R || !R.times.length) { $('f31Table').innerHTML = ''; $('f31TableEmpty').hidden = false; $('f31TableNote').textContent = ''; return; }
    $('f31TableEmpty').hidden = true;
    const u = state.view.tableUnits;
    const cols = [];
    R.names.forEach((n, i) => {
      if (u !== 'bq') cols.push({ head: `${n} (mol/a)`, arr: R.out[i] });
      if (u !== 'mol') cols.push({ head: `${n} (Bq/a)`, arr: R.bq[i] });
    });
    const nshow = Math.min(R.times.length, state.tableLimit);
    let body = '';
    for (let k = 0; k < nshow; k++) {
      body += `<tr><td>${esc(R.times[k].toPrecision(7))}</td>${cols.map((c) => `<td>${esc(c.arr[k].toExponential(6))}</td>`).join('')}</tr>`;
    }
    $('f31Table').innerHTML = `<table class="f31-table"><thead><tr><th>time (a)</th>${cols.map((c) => `<th>${esc(c.head)}</th>`).join('')}</tr></thead><tbody>${body}</tbody></table>${nshow < R.times.length ? `<p class="f31-more"><button type="button" class="f31-btn secondary small" data-on-click="f31:tableMore">Show ${Math.min(1000, R.times.length - nshow)} more</button></p>` : ''}`;
    $('f31TableNote').textContent = `${R.times.length} times${nshow < R.times.length ? `, ${nshow} shown` : ''}${R.stale ? ' — from the previous run' : ''}`;
  }

  function renderSummary() {
    const R = state.result, k = cur(), p = k.params;
    const parts = [];
    const aw = effectiveAw();
    parts.push('<h3>The case</h3>');
    const kv = [
      ['Case', esc(k.casename)], ['Travel time tw', `${fmt(p.tw)} a`], ['Peclet number', fmt(p.Pe)],
      ['a_w', `${fmt(aw)} 1/m`], ['F-factor tw·aw', `${fmt(p.tw * aw)} a/m`], ['Porosity', fmt(p.eps)],
      ['Penetration depth', p.x0 === Infinity ? 'infinite' : `${fmt(p.x0)} m`], ['Rock density', `${fmt(p.rho)} kg/m³`],
      ['Diffusivity', k.diffusivity === 'SINGLE' ? `${fmt(p.de)} m²/a for all` : 'per element'],
    ];
    parts.push(`<div class="f31-kv">${kv.map(([a, b]) => `<div><b>${a}</b><span>${b}</span></div>`).join('')}</div>`);
    const nrows = k.nuclides.map((n, i) => {
      const R_ = p.eps + n.kd * p.rho, de = k.diffusivity === 'SINGLE' ? p.de : n.de, Rf = 1 + (n.ka || 0) * aw;
      const tsat = p.x0 === Infinity || !(de > 0) ? Infinity : p.x0 * p.x0 * R_ / de;
      const req = p.x0 === Infinity ? Infinity : Rf + aw * p.x0 * R_;
      return `<tr><td class="name"><span class="f31-legend-dot" style="background:${colorOf(i)}"></span>${esc(n.name)}</td><td>${fmt(n.thalf)}</td><td>${fmt(n.kd)}</td><td>${fmt(R_)}</td><td>${fmt(n.ka || 0)}</td><td>${fmt(Rf)}</td><td>${fmt(de)}</td><td>${fmt(tsat)}</td><td>${fmt(req)}</td><td class="text">${[i > 0 && k.nuclides[i - 1].daughter ? `← ${esc(k.nuclides[i - 1].name)}` : '', n.source ? 'source' : ''].filter(Boolean).join(' · ')}</td></tr>`;
    }).join('');
    parts.push(`<div class="f31-table-wrap"><table class="f31-table"><thead><tr><th class="text">Nuclide</th><th>T½ (a)</th><th title="Sorption in the matrix">Kd (m³/kg)</th><th title="ε + Kd·ρ, the matrix's capacity relative to water">R</th><th title="Sorption on the fracture surfaces">Ka (m)</th><th title="1 + Ka·aw, the retardation in the flowing water">Rf</th><th>De (m²/a)</th><th title="x0²R/De">matrix fills in (a)</th><th title="Rf + aw·x0·R: the retardation of a filled matrix">retardation when filled</th><th class="text"></th></tr></thead><tbody>${nrows}</tbody></table></div>`);
    if (!R) { parts.push('<p class="f31-muted">Press <b>Run</b> for the results.</p>'); $('f31Summary').innerHTML = parts.join(''); return; }
    const warn = [];
    if (R.stale) warn.push('<li>The results are from the previous run: the case has changed since.</li>');
    for (const n of R.notes || []) warn.push(`<li>${esc(n)}</li>`);
    if (R.check) {
      const ok = R.check.worst < 1e-6;
      warn.push(`<li class="${ok ? 'ok' : ''}">Check: ${R.check.count} samples recomputed by ${R.check.method === 'dehoog' ? 'de Hoog’s method' : 'the saddle-point method'}; the largest relative difference over values above 1e-6 of each peak is ${fmt(R.check.worst, 2)}${R.check.where ? ` (${esc(R.names[R.check.where.i])} ← ${esc(R.names[R.check.where.j])} at ${fmt(R.check.where.t)} a)` : ''}.</li>`);
    }
    if (R.infPe) warn.push(`<li>Plug flow (Pe = ∞): each response starts at t = Rf·tw exactly${R.rf && R.rf.some((x) => x !== 1) ? ', Rf the retardation by fracture sorption' : ''}.</li>`);
    parts.push('<h3>Results</h3>');
    if (warn.length) parts.push(`<ul class="f31-warnings">${warn.join('')}</ul>`);
    if (!R.empty) {
      const prow = R.peaks.map((pk, i) => {
        let tot = 0;
        for (let q = 0; q + 1 < R.times.length; q++) tot += 0.5 * (R.times[q + 1] - R.times[q]) * (R.out[i][q] + R.out[i][q + 1]);
        const inp = R.series[R.names[i]];
        return `<tr><td class="name"><span class="f31-legend-dot" style="background:${colorOf(i)}"></span>${esc(pk.name)}</td><td>${fmt(pk.t, 5)}</td><td>${fmt(pk.rate, 5)}</td><td>${fmt(pk.bq, 5)}</td><td>${fmt(tot)}</td><td>${inp ? fmt(inp.mass) : '–'}</td></tr>`;
      }).join('');
      parts.push(`<div class="f31-table-wrap"><table class="f31-table"><thead><tr><th class="text">Nuclide</th><th>peak at (a)</th><th>peak (mol/a)</th><th>peak (Bq/a)</th><th title="The integral of the release over the output times">released (mol)</th><th>entered (mol)</th></tr></thead><tbody>${prow}</tbody></table></div>`);
      const rrow = R.responses.map((r) => `<tr${r.balanced === false ? ' class="f31-bad"' : ''}><td class="name">${esc(pairLabel(r))}</td><td>${fmt(r.T0, 6)}</td><td>${r.expected == null ? '–' : fmt(r.expected, 6)}</td><td>${fmt(r.integral, 6)}</td><td>${r.t.length ? fmt(r.tPeak) : '–'}</td><td>${fmt(r.peak)}</td><td>${r.t.length}</td></tr>`).join('');
      parts.push('<h3>Unit responses</h3>');
      parts.push(`<p class="f31-muted" style="max-width:60rem">T(0) is the fraction of a pulse that leaves the tube, from the Laplace domain; “by the last time” is the part of it that has left by the last time of the response, the same unless the response has a tail beyond the output times (an infinite matrix without decay). The integral of the computed response must equal it: a response that does not is marked here and named in the notes above, and the release computed from it is not reliable.</p>`);
      parts.push(`<div class="f31-table-wrap"><table class="f31-table"><thead><tr><th class="text">Response</th><th>T(0)</th><th title="What leaves the tube by the response's last time">by the last time</th><th>integral</th><th>peak at (a)</th><th>peak (1/a)</th><th>points</th></tr></thead><tbody>${rrow}</tbody></table></div>`);
    }
    if (state.reference && state.reference.comparison) {
      parts.push(`<h3>Against ${esc(state.reference.name)}</h3><ul class="f31-warnings">${state.reference.comparison.map((r) => (r.used ? `<li>${esc(r.name)}: ${r.points} times; largest relative difference ${fmt(r.w6, 3)} above 1e-6 of its peak, ${fmt(r.w3, 3)} above 1e-3.</li>` : `<li>${esc(r.name)}: nothing above zero to compare.</li>`)).join('')}</ul>`);
    }
    const tm = R.timing || {};
    parts.push(`<p class="f31-muted">Method: ${esc({ parabola: 'saddle-point contour', talbot: 'Talbot’s fixed contour', dehoog: 'de Hoog' }[R.input.settings.method] || '')}. Time: ${fmt(tm.responses / 1000, 3)} s for the responses, ${fmt(tm.output / 1000, 3)} s for the output, ${fmt(tm.check / 1000, 3)} s for the check; ${(tm.evaluations || 0).toLocaleString('en')} evaluations of the transfer matrix. Output from ${fmt(R.tStart)} to ${fmt(R.tEnd)} a.</p>`);
    $('f31Summary').innerHTML = parts.join('');
  }

  /* ---------------------------------------------------------------------
     Files
     --------------------------------------------------------------------- */
  function kindOf(name, text) {
    const n = name.toLowerCase();
    if (/\.json$/.test(n)) return 'case';
    if (/\.prm$/.test(n)) return 'prm';
    if (/\.par$/.test(n)) return 'par';
    if (/\.dat$/.test(n)) return /^\s*(#.*\n\s*)*(print|casename|diffusivity)\b/im.test(text) || /^\s*[A-Za-z][A-Za-z]?\d+[A-Za-z]*\s+[-+.\dEeDd]+\s+[01]\s+[01]\s*$/m.test(text) ? 'dat' : 'table';
    if (/\.response$/.test(n) || /NPRESP\(MPRES=/.test(text)) return 'outresponse';
    if (/^\s*Run made on/.test(text) || /Output migration rate/.test(text)) return 'outts';
    if (/\.ts$/.test(n)) return 'ts';
    return 'table';
  }
  const ORDER = ['case', 'dat', 'par', 'ts', 'table', 'prm', 'outts', 'outresponse'];

  async function routeFiles(files) {
    const items = [];
    for (const f of files) {
      const size = typeof kvotFileTooLarge === 'function' ? kvotFileTooLarge(f) : null;
      if (size && size.tooLarge) { setStatus(size.reason, 'error'); continue; }
      let text;
      try { text = await f.text(); } catch (e) { setStatus(`${f.name}: could not be read (${e.message}).`, 'error'); continue; }
      items.push({ name: f.name, text, kind: kindOf(f.name, text) });
    }
    items.sort((a, b) => ORDER.indexOf(a.kind) - ORDER.indexOf(b.kind));
    const msgs = [], warns = [];
    let changed = false, failed = false;
    for (const it of items) {
      try {
        const r = applyFile(it);
        if (r.changed) changed = true;
        msgs.push(`${it.name}: ${r.what}`);
        warns.push(...(r.warnings || []));
        if (it.kind !== 'outts') state.files.push({ name: it.name, what: r.what });   // a compared out.ts has its own line
      } catch (e) {
        failed = true;
        msgs.push(`${e.message}`);
      }
    }
    if (state.files.length > 12) state.files.splice(0, state.files.length - 12);
    renderFileList();
    writeControls();
    renderNucTable();
    renderSeries();
    saveState();
    const text = msgs.concat(warns).join(' ');
    if (failed) { setStatus(text, 'error'); renderTab(); return; }
    if (changed) {
      if (state.result) state.result.stale = true;
      const mi = modelInput();
      if (!mi.error) { setStatus(`${text} Running…`); run(); return; }
      setStatus(`${text} ${mi.error}`, 'warn');
    } else {
      setStatus(text, warns.length ? 'warn' : 'ok');
    }
    renderTab();
  }

  function applyFile(it) {
    const k = cur();
    switch (it.kind) {
      case 'case': {
        const doc = JSON.parse(it.text);
        if (doc && doc.app && doc.app !== 'kvot-farf31') throw new Error(`${it.name} is a case of another page (${doc.app}).`);
        const c = sanitizeCase(doc && doc.kase ? doc.kase : doc);
        if (!c || !c.nuclides.length) throw new Error(`${it.name} is not a FARF31 case.`);
        state.kase = c;
        state.srcSel = null;
        return { changed: true, what: `case “${c.casename}”, ${c.nuclides.length} nuclide${c.nuclides.length === 1 ? '' : 's'}` };
      }
      case 'dat': {
        const d = IO.readDat(it.text, it.name);
        const old = new Map(k.nuclides.map((n) => [n.name.toUpperCase(), n]));
        const oldKey = new Map(k.nuclides.map((n) => [keyOf(n.name), n]));
        k.nuclides = d.nuclides.map((n) => {
          const o = old.get(n.name.toUpperCase()) || oldKey.get(keyOf(n.name));
          return { name: n.name, thalf: n.thalf, kd: o ? o.kd : 0, ka: o ? o.ka || 0 : 0, de: o ? o.de : k.params.de, daughter: n.daughter, source: n.source };
        });
        k.casename = d.casename; k.print = d.print; k.diffusivity = d.diffusivity;
        const series = {};
        for (const n of k.nuclides) if (k.series[n.name]) series[n.name] = k.series[n.name];
        k.series = series;
        return { changed: true, what: `${k.nuclides.length} nuclide${k.nuclides.length === 1 ? '' : 's'} (${k.nuclides.filter((n) => n.source).length} with a release)`, warnings: d.warnings };
      }
      case 'par': {
        const par = IO.readPar(it.text, it.name);
        const p = k.params, w = [...par.warnings];
        if (par.TW != null) p.tw = par.TW;
        if (par.PECLET != null) p.Pe = par.PECLET >= 1e15 ? Infinity : par.PECLET;
        if (par.ASPEC != null) { p.aw = par.ASPEC; p.F = p.tw * p.aw; p.awMode = 'aw'; }
        if (par.EPS != null) p.eps = par.EPS;
        if (par.DE != null) p.de = par.DE;
        if (par.PENDEP != null) p.x0 = par.PENDEP >= 1e15 ? Infinity : par.PENDEP;
        if (par.extra.DENSITY != null || par.extra.RHO != null) p.rho = par.extra.DENSITY != null ? par.extra.DENSITY : par.extra.RHO;
        for (const n of k.nuclides) {
          const key = keyOf(n.name);
          if (par.kd[key] != null) n.kd = par.kd[key]; else w.push(`in.par has no KDR_${key} for ${n.name}.`);
          n.ka = par.ka[key] != null ? par.ka[key] : 0;   // FARF31's own in.par has no KA_: Ka 0
          if (par.de[key] != null) n.de = par.de[key];
          else if (k.diffusivity === 'SINGLE' && par.DE != null) n.de = par.DE;
          else if (k.diffusivity === 'ELEMENT_SPECIFIC') w.push(`in.par has no DE_${key} for ${n.name}.`);
        }
        const missing = ['TW', 'PECLET', 'ASPEC', 'EPS', 'PENDEP'].filter((x) => par[x] == null);
        if (missing.length) w.push(`in.par lacks ${missing.join(', ')}; the page keeps its values.`);
        return { changed: true, what: 'parameters', warnings: w };
      }
      case 'ts':
      case 'table': {
        const sel = state.srcSel || (sources()[0] && sources()[0].name);
        const r = it.kind === 'ts' ? IO.readTs(it.text, it.name) : IO.readTable(it.text, it.name, sel);
        const got = [], w = [];
        for (const name of r.order) {
          const n = k.nuclides.find((m) => m.name.toUpperCase() === name.toUpperCase());
          if (!n) { w.push(`${it.name}: ${name} is not among the nuclides; skipped.`); continue; }
          k.series[n.name] = r.series[name];
          if (!n.source) n.source = true;
          got.push(n.name);
        }
        for (const n of k.nuclides) if (n.source && !k.series[n.name]) w.push(`${n.name} is a source but ${it.name} has no series for it.`);
        if (got.length) state.srcSel = got[0];
        return { changed: got.length > 0, what: got.length ? `release series of ${got.join(', ')}` : 'no series used', warnings: w };
      }
      case 'prm': {
        const r = IO.readPrm(it.text, it.name);
        const s = k.settings;
        for (const key of ['method', 'npMin', 'npMax', 'relint', 'bqMin', 'tStart', 'tEnd']) if (r.settings[key] != null) s[key] = r.settings[key];
        if (r.settings.rho != null) k.params.rho = r.settings.rho;
        const w = [...r.notes];
        if (r.unused.length) w.push(`Not used here: ${r.unused.join(', ')}.`);
        return { changed: true, what: 'numerical settings', warnings: w };
      }
      case 'outts': {
        const data = IO.readOutTs(it.text, it.name);
        state.reference = { name: it.name, data, comparison: null };
        state.view.showRef = true;
        compareReference();
        return { changed: false, what: `${Object.keys(data).length} nuclide${Object.keys(data).length === 1 ? '' : 's'} to compare with, drawn as markers` };
      }
      case 'outresponse': {
        const blocks = IO.readOutResponse(it.text);
        return { changed: false, what: `${blocks.length} unit responses read; the page draws its own (compare on the Unit responses tab by eye)` };
      }
      default: throw new Error(`${it.name}: not a file the page reads.`);
    }
  }

  function renderFileList() {
    const items = state.files.slice(-6).map((f) => `<li><span class="f31-file-name">${esc(f.name)}</span><span class="f31-file-meta">${esc(f.what)}</span></li>`);
    if (state.reference) items.push(`<li><span class="f31-file-name">${esc(state.reference.name)} (compared)</span><button type="button" title="Stop comparing" data-on-click="f31:clearRef">×</button></li>`);
    $('f31FileList').innerHTML = items.join('');
  }

  function loadExample(id, silent) {
    state.kase = exampleCase(id);
    state.srcSel = null;
    state.result = null;
    $('f31Example').value = id;
    writeControls();
    renderNucTable();
    renderSeries();
    saveState();
    if (!silent) setStatus(`Example “${(DATA.EXAMPLES.find((e) => e.id === id) || {}).label}” loaded.`, 'ok');
    run();
  }

  function saveCase() {
    const doc = { app: 'kvot-farf31', kind: 'case', version: 1, saved: new Date().toISOString(), build: BUILD, kase: forJson(state.kase) };
    download(`${state.kase.casename || 'farf'}_case.json`, JSON.stringify(doc, null, 1), 'application/json');
  }

  function writeFile(kind) {
    const k = cur(), p = k.params;
    const c = {
      print: k.print, casename: k.casename, diffusivity: k.diffusivity,
      params: { tw: p.tw, Pe: p.Pe, aw: effectiveAw(), eps: p.eps, de: p.de, x0: p.x0, rho: p.rho },
      nuclides: k.nuclides.map((n) => ({ ...n, de: k.diffusivity === 'SINGLE' ? p.de : n.de })), series: k.series, settings: k.settings,
    };
    if (kind === 'dat') download('in.dat', IO.writeDat(c));
    else if (kind === 'par') download('in.par', IO.writePar(c));
    else if (kind === 'ts') download('in.ts', IO.writeTs(c));
    else if (kind === 'prm') download(`${k.casename || 'farf'}31.prm`, IO.writePrm(c));
  }

  function downloadResult(kind) {
    const R = state.result;
    if (!R) { setStatus('Run the model first.', 'warn'); return; }
    const k = cur();
    if (kind === 'csv') download(`${k.casename}_release.csv`, IO.resultsCsv(R, BUILD, k.casename), 'text/csv');
    else if (kind === 'respcsv') download(`${k.casename}_responses.csv`, IO.responsesCsv(R, BUILD, k.casename), 'text/csv');
    else if (kind === 'outts') download('out.ts', IO.writeOutTs(R, { bqMin: k.settings.bqMin == null ? 1e-3 : k.settings.bqMin }));
    else if (kind === 'outresponse') download('out.response', IO.writeOutResponse(R));
  }

  /* ---------------------------------------------------------------------
     Tabs, panel, drag handle, drops
     --------------------------------------------------------------------- */
  const TABS = ['release', 'responses', 'table', 'summary', 'input', 'help'];

  function showTab(name) {
    state.tab = name;
    document.querySelectorAll('.f31-tabs button').forEach((b) => b.classList.toggle('active', b.dataset.tab === name));
    document.querySelectorAll('.f31-pane').forEach((p) => { p.hidden = p.dataset.pane !== name; });
    saveState();
    renderTab();
  }

  function renderTab() {
    try {
      switch (state.tab) {
        case 'release': renderRelease(); break;
        case 'responses': renderResponses(); break;
        case 'table': renderTable(); break;
        case 'summary': renderSummary(); break;
        case 'input': renderNucTable(); renderSeries(); break;
        default: break;
      }
    } catch (e) {
      if (typeof reportFailure === 'function') reportFailure(`f31:render:${state.tab}`, e);
      setStatus(`Drawing the ${state.tab} tab failed: ${e.message}`, 'error');
    }
    mountInfoButtons();
    requestAnimationFrame(resizePlots);
  }

  function initSideResize() {
    const handle = $('f31Resize');
    const root = document.querySelector('.f31');
    if (state.sideWidth) root.style.setProperty('--f31-side-width', `${state.sideWidth}px`);
    let dragging = false;
    handle.addEventListener('pointerdown', (ev) => { dragging = true; handle.classList.add('active'); handle.setPointerCapture(ev.pointerId); });
    handle.addEventListener('pointermove', (ev) => {
      if (!dragging) return;
      const left = root.getBoundingClientRect().left;
      state.sideWidth = Math.round(Math.max(260, Math.min(640, ev.clientX - left)));
      root.style.setProperty('--f31-side-width', `${state.sideWidth}px`);
      resizePlots();
    });
    const end = () => { if (!dragging) return; dragging = false; handle.classList.remove('active'); saveState(); resizePlots(); };
    handle.addEventListener('pointerup', end);
    handle.addEventListener('pointercancel', end);
    // data-on-dblclick is not delegated by kvot-actions.js: bind it here
    handle.addEventListener('dblclick', () => { state.sideWidth = DEFAULT_WIDTH; root.style.setProperty('--f31-side-width', `${DEFAULT_WIDTH}px`); saveState(); resizePlots(); });
  }

  function initSections() {
    document.querySelectorAll('details.f31-sec').forEach((sec) => {
      if (Object.prototype.hasOwnProperty.call(state.sections, sec.id)) sec.open = !!state.sections[sec.id];
      sec.addEventListener('toggle', () => { state.sections[sec.id] = sec.open; saveState(); });
    });
  }

  function initDrop() {
    const zone = $('f31Drop');
    const root = document.querySelector('.f31');
    let depth = 0;
    const hasFiles = (ev) => ev.dataTransfer && Array.from(ev.dataTransfer.types || []).includes('Files');
    root.addEventListener('dragenter', (ev) => { if (!hasFiles(ev)) return; ev.preventDefault(); depth++; zone.classList.add('over'); });
    root.addEventListener('dragover', (ev) => { if (!hasFiles(ev)) return; ev.preventDefault(); });
    root.addEventListener('dragleave', () => { depth = Math.max(0, depth - 1); if (!depth) zone.classList.remove('over'); });
    root.addEventListener('drop', (ev) => {
      if (!hasFiles(ev)) return;
      ev.preventDefault();
      depth = 0;
      zone.classList.remove('over');
      const files = ev.dataTransfer && ev.dataTransfer.files ? Array.from(ev.dataTransfer.files) : [];
      if (files.length) routeFiles(files);
    });
    // A drop that lands outside the page's area must not open the file in the tab.
    document.addEventListener('dragover', (ev) => { if (hasFiles(ev)) ev.preventDefault(); });
    document.addEventListener('drop', (ev) => { if (hasFiles(ev) && !root.contains(ev.target)) { ev.preventDefault(); const f = Array.from(ev.dataTransfer.files || []); if (f.length) routeFiles(f); } });
  }

  /* ---------------------------------------------------------------------
     Actions
     --------------------------------------------------------------------- */
  registerActions({
    'f31:tab': (ev, el) => showTab(el.dataset.tab),
    'f31:run': () => run(),
    'f31:cancel': () => cancelRun(),
    'f31:openFiles': () => $('f31Files').click(),
    'f31:filesChosen': (ev, el) => { const f = el.files ? Array.from(el.files) : []; el.value = ''; if (f.length) routeFiles(f); },
    'f31:chooseExample': (ev, el) => { if (el.value) loadExample(el.value); },
    'f31:caseField': (ev, el) => { const v = el.value.trim(); if (!v || /\s/.test(v)) { el.setCustomValidity('One word'); el.reportValidity(); return; } el.setCustomValidity(''); cur().casename = v; writeControls(); saveState(); },
    'f31:param': (ev, el) => paramChanged(el),
    'f31:setting': (ev, el) => settingChanged(el),
    'f31:writeFile': (ev, el) => writeFile(el.dataset.kind),
    'f31:saveCase': () => saveCase(),
    'f31:download': (ev, el) => downloadResult(el.dataset.kind),
    'f31:view': (ev, el) => {
      const key = el.dataset.key;
      state.view[key] = el.type === 'checkbox' ? el.checked : el.value;
      saveState();
      renderTab();
    },
    'f31:pairToggle': (ev, el) => { if (el.checked) delete state.hiddenPairs[el.dataset.key]; else state.hiddenPairs[el.dataset.key] = true; saveState(); renderResponses(); },
    'f31:tableMore': () => { state.tableLimit += 1000; renderTable(); },
    'f31:clearRef': () => { state.reference = null; renderFileList(); renderTab(); },
    'f31:addNuclide': () => addNuclide(),
    'f31:preset': (ev, el) => { if (el.value) { loadPreset(el.value); el.value = ''; } },
    'f31:nucEdit': (ev, el) => nucEdit(el),
    'f31:nucMove': (ev, el) => {
      const k = cur(), i = Number(el.dataset.i), j = i + Number(el.dataset.d);
      if (j < 0 || j >= k.nuclides.length) return;
      [k.nuclides[i], k.nuclides[j]] = [k.nuclides[j], k.nuclides[i]];
      k.nuclides[k.nuclides.length - 1].daughter = false;
      renderNucTable(); renderSeries(); saveState(); markStale('The order of the nuclides changed.');
    },
    'f31:nucDelete': (ev, el) => {
      const k = cur(), i = Number(el.dataset.i);
      const n = k.nuclides[i];
      if (!n) return;
      k.nuclides.splice(i, 1);
      delete k.series[n.name];
      if (k.nuclides.length) k.nuclides[k.nuclides.length - 1].daughter = false;
      renderNucTable(); renderSeries(); saveState(); markStale(`${n.name} was removed.`);
    },
    'f31:pickSource': (ev, el) => { state.srcSel = el.dataset.name; saveState(); renderSeries(); },
    'f31:seriesText': (ev, el) => seriesText(el),
    'f31:openSeries': () => $('f31SeriesFile').click(),
    'f31:seriesFileChosen': (ev, el) => { const f = el.files ? Array.from(el.files) : []; el.value = ''; if (f.length) routeFiles(f); },
    'f31:shapeKind': () => shapeKind(),
    'f31:shapeApply': (ev, el) => shapeApply(el.dataset.mode),
  });

  /* ---------------------------------------------------------------------
     Boot
     --------------------------------------------------------------------- */
  $('f31Example').innerHTML = `<option value="">— choose —</option>${DATA.EXAMPLES.map((e) => `<option value="${esc(e.id)}">${esc(e.label)}</option>`).join('')}`;
  $('f31Preset').innerHTML = `<option value="">— choose —</option>${DATA.PRESETS.map((p) => `<option value="${esc(p.id)}">${esc(p.label)}</option>`).join('')}`;
  const hadState = loadState();
  if (!state.kase) state.kase = exampleCase('np');
  writeControls();
  renderNucTable();
  renderSeries();
  renderFileList();
  shapeKind();
  initSideResize();
  initSections();
  initDrop();
  mountInfoButtons();
  $('f31Build').textContent = `Build ${BUILD}. The calculation runs in your browser; nothing is sent anywhere.`;
  document.addEventListener('keydown', (ev) => { if (ev.key === 'Escape' && info.key && !ev.defaultPrevented) { const at = document.activeElement; if (!at || at === document.body || info.panel?.contains(at) || at.closest?.('[data-info]')) closeInfo(); } });
  window.addEventListener('resize', () => { resizePlots(); placeInfo(); });
  document.documentElement.addEventListener('kvot-theme-change', () => renderTab());
  showTab(TABS.includes(state.tab) ? state.tab : 'release');
  if (!hadState) setStatus('An example is loaded: press Run, or open your own case.');
  run();

  window.F31Page = Object.freeze({
    getState: () => state,
    run,
    showTab,
    loadExample,
    outputAt: (i, t) => (state.result ? outputAt(state.result, i, t) : NaN),
    fmt,
    build: BUILD,
  });
}());
