/* ==========================================================================
   SIMPLEFUNCTIONS.HTML: THE PAGE

   Wiring only. The arithmetic is sf-model.js, the dataset sf-data.js, the
   file readers and writers sf-io.js, and the Monte Carlo runs in
   sf-worker.js (or here, in slices, where a worker cannot be started, as
   under file://).

   One global: SFPage, a read-only window on the state for the browser test.
   Everything else is inside the IIFE and reached through the data-on-*
   actions registered at the bottom.
   ========================================================================== */
(function () {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const esc = (s) => (typeof kvotEscapeHtml === 'function' ? kvotEscapeHtml(s) : String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])));
  const STORAGE_KEY = 'kvot-sf-v1';
  const DEFAULT_WIDTH = 330;
  const BUILD = '2026-09-25';
  const WORKER_URL = './resources/js/sf-worker.js?v=20260925';
  const PALETTE = ['#bb6c5d', '#4e79a7', '#e0a458', '#59a14f', '#8e6c8a', '#76b7b2', '#d37295', '#9c755f'];
  const LOG_KSIDERITE = -10.89;   // FeCO3(s) = Fe+2 + CO3-2; a diagnostic, not part of the tool
  const MAX_N = 1000000;

  /* ---------------------------------------------------------------------
     State
     --------------------------------------------------------------------- */
  const DEFAULT_OPTIONS = { version: 'B', reactionTerms: false, polyStoichiometry: false, singleRaOH: false, ehExact: false, analogueDraws: false, limit: 0.01 };
  const DEFAULT_RUN = { n: 6916, seed: 1, lhs: true, draw: 'randrep', fixedWater: 0, varyTD: true };

  const state = {
    data: SFData.clone(SFData.SRSITE),
    options: { ...DEFAULT_OPTIONS },
    run: { ...DEFAULT_RUN },
    units: 'molkg',
    addMg: true,
    table: null,       // {name, rawWaters, headers, sheet, skipped, source, hasMg, hasEh, hasFe}
    example: '',
    tab: 'summary',
    sideWidth: null,
    sections: {},
    water: { row: 1, custom: false, edits: {} },
    waterEl: 'U',
    dist: { el: 'U', kind: 'hist', phase: false, fit: false, ref: true },
    sens: { el: 'U', top: 12 },
    sweep: { el: 'U', v: 'pH', from: '', to: '' },
    dataEl: 'U',
    ref: null,
    refUnits: 'molkg',
    plan: null,
    planError: null,
    result: null,
    running: null,
  };

  function saveState() {
    try {
      const edited = dataEdits().count > 0;
      localStorage.setItem(STORAGE_KEY, JSON.stringify({
        options: state.options, run: state.run, units: state.units, addMg: state.addMg, example: state.example,
        tab: state.tab, sideWidth: state.sideWidth, sections: state.sections, water: state.water, waterEl: state.waterEl,
        dist: state.dist, sens: state.sens, sweep: state.sweep, dataEl: state.dataEl, refUnits: state.refUnits,
        data: edited ? state.data : null,
      }));
    } catch (e) { /* storage unavailable or full */ }
  }

  function loadState() {
    let s;
    try { s = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null'); } catch (e) { s = null; }
    if (!s || typeof s !== 'object') return false;
    const pick = (obj, def) => { const out = { ...def }; if (obj && typeof obj === 'object') for (const k of Object.keys(def)) if (typeof obj[k] === typeof def[k]) out[k] = obj[k]; return out; };
    state.options = pick(s.options, DEFAULT_OPTIONS);
    state.run = pick(s.run, DEFAULT_RUN);
    if (['molkg', 'molm3'].includes(s.units)) state.units = s.units;
    if (typeof s.addMg === 'boolean') state.addMg = s.addMg;
    if (typeof s.example === 'string') state.example = s.example;
    if (typeof s.tab === 'string') state.tab = s.tab;
    if (Number.isFinite(s.sideWidth)) state.sideWidth = s.sideWidth;
    if (s.sections && typeof s.sections === 'object') state.sections = s.sections;
    if (s.water && typeof s.water === 'object') state.water = { row: Number(s.water.row) || 1, custom: !!s.water.custom, edits: s.water.edits && typeof s.water.edits === 'object' ? s.water.edits : {} };
    if (typeof s.waterEl === 'string') state.waterEl = s.waterEl;
    state.dist = pick(s.dist, state.dist);
    state.sens = pick(s.sens, state.sens);
    state.sweep = pick(s.sweep, state.sweep);
    if (typeof s.dataEl === 'string') state.dataEl = s.dataEl;
    if (['molkg', 'molm3'].includes(s.refUnits)) state.refUnits = s.refUnits;
    if (s.data) { const d = sanitizeData(s.data); if (d) state.data = d; }
    return true;
  }

  /* ---------------------------------------------------------------------
     Formatting
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
  const fmtLog = (x) => (Number.isFinite(x) ? x.toFixed(2).replace('-', '−') : '–');
  const pct = (x) => (x >= 0.995 ? '100' : x < 0.001 && x > 0 ? '<0.1' : (100 * x).toFixed(x < 0.1 ? 1 : 0));
  const unitOffset = () => (state.units === 'molm3' ? 3 : 0);
  const unitLabel = () => (state.units === 'molm3' ? 'mol/m³' : 'mol/kg');
  const numberText = (v) => (typeof v === 'number' && Number.isFinite(v) ? (Math.abs(v) >= 1e5 || (Math.abs(v) < 1e-3 && v !== 0) ? trimExp(v.toExponential(10)) : trimZeros(v.toPrecision(12))) : '');

  function download(name, content, type = 'text/csv') {
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
    const el = $('sfStatus');
    el.textContent = text;
    el.className = `sf-status${tone ? ` ${tone}` : ''}`;
  }

  /* ---------------------------------------------------------------------
     The (i) and its panel. The same behaviour as Kompartment's
     src/ui/infopanel.js: one panel at a time over the right-hand side,
     built from text nodes, closed by the × , the same (i) or Escape.
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
    root.querySelectorAll('.sf-info-slot[data-info-key]').forEach((slot) => {
      const key = slot.dataset.infoKey;
      if (!TOPICS[key] || slot.firstChild) return;
      const t = resolveTopic(key);
      const b = document.createElement('button');
      b.type = 'button';
      b.className = `info-btn${info.key === key ? ' is-open' : ''}`;
      b.dataset.info = key;
      b.setAttribute('aria-label', `About ${t ? t.title : 'this setting'}`);
      b.setAttribute('aria-expanded', String(info.key === key));
      b.setAttribute('aria-controls', 'sf-info-panel');
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
      panel.id = 'sf-info-panel';
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
  const TOPICS = {
    'sec:water': {
      kicker: 'Section', title: 'Groundwater',
      lead: 'The compositions the realisations draw from. One row is one water; every realisation takes one row, and every element of that realisation sees the same water.',
      sections: [
        { heading: 'Columns', list: ['`pH` — taken as −log[H+]', '`[Ca]tot`, `[Cl]tot`, `[Na]tot`, `[SO4-2]tot`, `[Si]tot` — totals, mol/kg', '`IS` — the ionic strength, mol/kg, used as given for the activity corrections', '`[HCO3-]` — the FREE hydrogen carbonate, not total carbon', '`Eh (mV)` and `[Fe]tot` — only for Version A', '`Mg` — optional, added to Ca'] },
        { heading: 'Files', text: 'CSV or text with a header row, or an Excel workbook: the sheet named Groundwater if there is one, otherwise the first with these columns. The PSAR parameter workbook (SFKParameters.xlsx) can be dropped as it is. The file stays in the browser and is not kept after the visit.' },
      ],
      more: more('Groundwater tables', 'help-water'),
    },
    'set:example': {
      kicker: 'Groundwater', title: 'Built-in examples',
      lead: 'Published waters to try the page with, from TR-10-61 (public).',
      sections: [{ choices: [
        ['TR-10-61 reference waters', 'The 12 waters of table A-1 (from TR-06-09): Forsmark, Laxemar, Äspö, Finnsjön, Gideå, Grimsel, the most saline waters of Laxemar and Olkiluoto, cement pore water, Baltic and ocean water, and the most saline glacial upconing. Mg apart, the more reducing Eh where two are given, Si 1e-20 (not in the table). Four have I above 0.2 m, which the Summary counts.'],
        ['TR-10-61 example water', 'The INPUT DATA example of table 3-1: pH 6, Eh −143 mV, I = 0.19. With Version A it gives the solubilities and controlling solids of table 3-2.'],
      ] }],
      more: more('Groundwater tables', 'help-water'),
    },
    'set:version': () => ({
      kicker: 'Groundwater', title: 'Redox and iron',
      lead: 'How the redox state and the free Fe(II) of the water are set.',
      sections: [{ choices: [
        ['Version B: magnetite/goethite', 'The water has reacted with the corrosion products of the insert: pO2 at the magnetite/goethite boundary at the pH of the water (about 10^−83 bar), Eh from it, and [Fe+2] from goethite. The SR-Site and PSAR setting. Eh and Fe in the table are ignored.', state.options.version === 'B'],
        ['Version A: Eh and [Fe]tot from the table', 'The water as given: pO2 from its Eh, and [Fe+2] from its total iron over the iron species of the major-ion table. Needs Eh (mV) and [Fe]tot columns.', state.options.version === 'A'],
      ] }, { heading: 'Keep in mind', text: 'In Version B, [Fe+2] goes roughly as 10^(12 − 2 pH): 0.01 mol/kg at pH 7 and 0.1 at pH 6.5. Such a water would precipitate siderite, and iron sulphate complexes lower its free sulphate. The One water tab shows [Fe+2] and the siderite saturation.' }],
      more: more('The water: free ligands and the redox state', 'help-how'),
    }),
    'sec:sampling': {
      kicker: 'Section', title: 'Sampling',
      lead: 'The Monte Carlo: how many realisations, which water each one draws, and whether the equilibrium constants are sampled.',
      sections: [{ text: 'Every constant with an uncertainty is drawn from N(logK, ΔlogK/2), independently, from a stream of its own keyed on its name and the seed: the same seed gives the same numbers, and editing one constant leaves the draws of all the others as they were.' }],
      more: more('Uncertainty', 'help-uncertainty'),
    },
    'set:n': { kicker: 'Sampling', title: 'Realisations', lead: 'How many times the whole calculation is done, each with its own water and its own set of constants.', facts: [['SR-Site and PSAR', '6916'], ['Largest here', MAX_N.toLocaleString('en')]], sections: [{ text: 'About 7000 realisations take a fraction of a second; a million take about half a minute and keep only the first part of the sampled constants for the sensitivity analysis.' }] },
    'set:seed': { kicker: 'Sampling', title: 'Seed', lead: 'Any whole number. The same seed, data and settings give the same realisations, here and in any other browser.', sections: [{ text: 'The random numbers are this page’s own (sfc32 seeded per constant), so they are not those of @Risk: the distributions agree with SR-Site and the PSAR, the individual realisations do not.' }] },
    'set:draw': () => ({
      kicker: 'Sampling', title: 'Groundwater draw', lead: 'Which row of the table each realisation takes.',
      sections: [{ choices: [
        ['at random, with replacement', 'Any row, any number of times, as @Risk’s RiskIntUniform(1, N) in the SR-Site workbooks; stratified with the Latin hypercube.', state.run.draw === 'randrep'],
        ['at random, without replacement', 'Each row at most once, in random order; needs at least as many rows as realisations.', state.run.draw === 'randnorep'],
        ['in table order', 'Row 1, 2, 3, … and round again.', state.run.draw === 'inorder'],
        ['one water only', 'The same water throughout: the spread is then that of the constants alone (SR-Site’s “fix GW, variable TD”).', state.run.draw === 'fixed'],
      ] }],
    }),
    'set:lhs': { kicker: 'Sampling', title: 'Latin hypercube', lead: 'Each constant’s draws are spread over N equally likely strata, one draw in each, in random order — as @Risk samples. Off: plain random draws.', sections: [{ text: 'The strata are per constant; the constants are independent of each other either way.' }] },
    'set:varyTD': { kicker: 'Sampling', title: 'Sample the equilibrium constants', lead: 'Off, every constant is at its nominal value and the spread comes from the groundwater alone (SR-Site’s “variable GW, fix TD”). Together with “one water only” the two halves of the variability can be compared.' },
    'sec:data': () => {
      const d = dataEdits();
      return {
        kicker: 'Section', title: 'Thermodynamic data',
        lead: 'The reactions, constants and uncertainties, and the candidate solids of each element. The SR-Site dataset unless edited on the Data tab.',
        facts: [['Elements', String(state.data.elements.length)], ['Constants sampled', state.plan ? String(state.plan.params.filter((p, i) => state.plan.sigma[i] > 0).length) : '–'], ['Edited', d.count ? `${d.count} entr${d.count === 1 ? 'y' : 'ies'}` : 'no']],
        sections: [{ text: 'Save data writes the dataset (with your edits) as JSON; Open data reads such a file back. The four options below reproduce the SR-Site workbooks as they calculated when all are off.' }],
        more: more('The thermodynamic data', 'help-data'),
      };
    },
    'set:reactionTerms': { kicker: 'Thermodynamic data', title: 'Every term from the reactions', lead: 'The workbooks wrote every activity correction and ligand dependence by hand. Four of them disagree with their own reaction; ticked, all four are taken from the reactions instead.', sections: [{ list: ['SmOHCO3(s): the H+ left out of the activity term (0.10 log units at I = 0.1)', 'NiCO3·5.5H2O(s): the 5.5 H2O left out', 'PaO2OH(aq): +2 q0 where the reaction gives 0', '(UO2)2CO3(OH)3−: [CO3-2]^3 for one carbonate'] }], more: more('Where the SR-Site workbooks differ', 'help-srsite') },
    'set:poly': { kicker: 'Thermodynamic data', title: 'Count a polynuclear complex by its metal atoms', lead: 'The workbooks add P²·Eq2 and P³·Eq3 to the total uranium, which counts a dimer or a trimer once. Ticked, they count 2 and 3 times over. Negligible under reducing conditions.' },
    'set:raoh': { kicker: 'Thermodynamic data', title: 'Sample Ra(OH)+ once', lead: 'The workbooks draw Ra(OH)+ as RiskNormal(RiskNormal(RiskNormal(logK, σ), σ), σ): a normal with √3 times the spread. Ticked, it is drawn once like the rest. Ra(OH)+ never matters for the solubility.' },
    'set:analogue': { kicker: 'Thermodynamic data', title: 'Cm drawn with the Am numbers', lead: 'The curium constants of SR-Site are the americium constants, taken over by chemical analogy — the same values and the same ΔlogK. The workbooks sample them independently, so a realisation can have a high americium and a low curium constant for what is one uncertain number. Ticked, each curium constant takes the random numbers of the americium constant of the same reaction, and the two elements move together.', sections: [{ text: 'It makes no difference to either element’s own distribution, only to how the two go together — which matters when their solubilities are used side by side, as in a transport calculation that samples both.' }] },
    'set:eh': { kicker: 'Thermodynamic data', title: 'Eh with 0.05916 V', lead: 'The workbooks compute the magnetite/goethite Eh with 0.059 V for RT ln10/F and turn it back into pe with 59.16 mV, which puts pO2 about 0.08 log units off. Ticked, 0.05916 is used in both places. Version B only.' },
    'sec:output': { kicker: 'Section', title: 'Output', lead: 'How the solubilities are shown. The calculation itself is in mol/kg water throughout.' },
    'set:limit': { kicker: 'Output', title: '“Not solubility limited” above', lead: 'The workbooks labelled an element “No solubility limited” when its solubility came out above 0.01 mol/kg: the concentration would then be set by the inventory, not by a solid. The value itself was kept in the results, and is here; the Summary gives the share of realisations above the threshold.', facts: [['Workbooks', '0.01 mol/kg']] },
    'pane:water': () => ({
      kicker: 'One water', title: 'One groundwater, nominal constants',
      lead: 'Everything the calculation does for one composition: the free ligands and the redox state, and for each element every candidate solid, the aqueous speciation at the controlling one, and a linearised uncertainty.',
      sections: [
        { heading: 'The ±', text: '2σ of log S from σ² = Σ(∂log S/∂log Ki · ΔlogKi/2)², the derivatives by central differences through the whole calculation, the controlling solid held. It is the same confidence as the ΔlogK. TR-10-61 quotes ±values 2.3 times smaller (its workbooks take ΔK = K·ΔlogK).' },
        { heading: 'Next solid', text: 'How much higher, in log units, the next-lowest candidate solid lies: how far the constants or the water must move before the controlling solid changes.' },
        { heading: 'Editing', text: 'Tick “edit the composition” to change the numbers; they start from the chosen row. Eh and Fe are used in Version A only.' },
      ],
      more: more('One water', 'help-uncertainty'),
    }),
    'pane:dist': { kicker: 'Distributions', title: 'Distributions of the solubility', lead: 'The realisations of one element, or of all twenty. Histograms are the fraction of realisations per bin of 0.1 log units.', sections: [{ heading: 'Fitted distribution', text: 'A normal and a skew-normal distribution fitted to log10 S by maximum likelihood; the skew-normal is kept when its Akaike criterion is lower by more than 2. For an element controlled by two solids far apart (U, sometimes Sr) neither describes the modes; split the histogram by controlling solid to see them.' }, { heading: 'Reference', text: 'Loaded on the Compare tab, drawn as a line over the same bins.' }] },
    'pane:sens': { kicker: 'Sensitivity', title: 'What the solubility follows', lead: 'The Spearman rank correlation of log S with every sampled constant (of the element and of the major ions) and with the properties of the water drawn. ±1: the solubility goes up or down with that input and nothing else; 0: no monotone relation.', sections: [{ text: 'The squares of the constants’ correlations roughly share out the variance between them when the water is fixed. The water’s properties are correlated with each other (a saline water has more of everything), so their correlations cannot be added.' }] },
    'pane:sweep': { kicker: 'Sweep', title: 'The solubility against one property', lead: 'Every candidate solid of the element, and their minimum (the solubility), as one property of the water varies and the rest stay at the composition of the One water tab, at the nominal constants.', sections: [{ text: 'A solid drawn dotted is left out of the minimum (Zr(OH)4(am,fresh) in the SR-Site data). The vertical line is the value of the water itself.' }] },
    'pane:compare': { kicker: 'Compare', title: 'Against reference solubilities', lead: 'The run beside solubilities from another source, element by element: P5, P50 and P95, their differences, and the two-sample Kolmogorov–Smirnov distance D with its p-value.', sections: [{ heading: 'Files', list: ['MATLAB level 5: SR-Site’s and the PSAR’s CSOL struct array (CSOL(i).U …), or a struct of vectors, or vectors named after the elements', 'HDF5: one dataset per element; the reader is fetched from the CDN the first time', 'CSV or Excel: one column per element'] }, { heading: 'Reading D', text: 'With 7000 realisations on each side, D below about 0.02 is what two samples of the same distribution give (p above 0.05).' }] },
    'pane:data': { kicker: 'Data', title: 'The thermodynamic dataset', lead: 'Every reaction of the chosen element (or of the major ions), its constant log K° at I = 0 and 25 °C, and its uncertainty ΔlogK. The activity term and the ligand dependence are derived from the reaction as written, and the reaction is checked for balance.', sections: [{ heading: 'Writing a reaction', list: ['A species: the master species on the left with basis species; the species alone on the right with basis species.', 'A solid: the solid on the left with basis species; the master species on the right with basis species.', 'Basis: H+, H2O, O2(g), CO3-2, SO4-2, Cl-, Ca+2, Na+, Fe+2, H4SiO4.', 'Charges sign first: `Th+4`, `SO4-2`, `Fe(OH)4-`. Terms separated by “ + ” with spaces; coefficients before the formula, `0.25 O2(g)`.'] }, { heading: 'Marked', text: 'An orange border marks a value that differs from the SR-Site dataset. “SR-Site term” marks an activity term or ligand dependence the workbooks wrote by hand and that differs from the reaction; it is used unless “every term from the reactions” is ticked.' }], more: more('The thermodynamic data', 'help-data') },
    'pane:samples': { kicker: 'Samples', title: 'The realisations', lead: 'The first 200 rows here; the files have them all.', sections: [{ list: ['CSV and Excel: realisation, the row of the water drawn, then the solubility of every element (mol/kg) and its controlling solid.', 'MATLAB (CSOL): a struct array CSOL(1×N) with one scalar field per element in mol/kg — the layout of SR-Site’s and the PSAR’s CSOL files, which also carried 1e17 for the elements without a limit (Ac, C, Ca, Cd, Cl, Cs, Eu, H, I, Mo); add those in the transport set-up if it expects them.', 'Sampled constants: every sampled log K° per realisation, for your own sensitivity analysis.'] }] },
  };

  /* ---------------------------------------------------------------------
     The dataset and the plan
     --------------------------------------------------------------------- */
  function modelOptions() {
    const o = state.options;
    return { version: o.version, reactionTerms: o.reactionTerms, polyStoichiometry: o.polyStoichiometry, singleRaOH: o.singleRaOH, ehFactor: o.ehExact ? 0.05916 : 0.059, analogueDraws: o.analogueDraws, limit: o.limit };
  }

  function compilePlan() {
    try {
      state.plan = SFModel.compile(state.data, modelOptions());
      state.planError = null;
    } catch (e) {
      state.plan = null;
      state.planError = e.message;
    }
    const errors = state.plan ? state.plan.issues.filter((i) => i.severity === 'error') : [];
    if (errors.length) state.planError = `${errors[0].where}: ${errors[0].message}`;
  }

  /**
   * A dataset from a file or from storage, checked entry by entry: text
   * names and reactions, numeric constants, a non-negative ΔlogK. Returns
   * null when it is not a dataset at all.
   */
  function sanitizeData(d) {
    if (!d || typeof d !== 'object' || !Array.isArray(d.major) || !Array.isArray(d.elements)) return null;
    const entry = (s) => {
      if (!s || typeof s !== 'object' || typeof s.id !== 'string' || typeof s.rx !== 'string' || !Number.isFinite(Number(s.logK))) return null;
      const o = { id: s.id.slice(0, 80), rx: s.rx.slice(0, 400), logK: Number(s.logK), dlogK: Math.max(0, Number(s.dlogK) || 0) };
      if (s.use === false) o.use = false;
      if (s.fixed) o.fixed = true;
      if (s.off) o.off = true;
      if (Number.isInteger(s.depth) && s.depth > 0 && s.depth < 10) o.depth = s.depth;
      if (Array.isArray(s.qSRSite) && s.qSRSite.length === 7 && s.qSRSite.every(Number.isFinite)) o.qSRSite = s.qSRSite.map(Number);
      if (s.ligSRSite && typeof s.ligSRSite === 'object') {
        const l = {};
        for (const [k, x] of Object.entries(s.ligSRSite)) if (SFModel.LIGANDS.includes(k) && Number.isFinite(x)) l[k] = x;
        if (Object.keys(l).length) o.ligSRSite = l;
      }
      return o;
    };
    const major = d.major.map(entry).filter(Boolean);
    const ids = new Set(major.map((s) => s.id));
    if (!SFModel.MAJOR_IDS.every((id) => ids.has(id))) return null;
    const elements = d.elements.map((E) => {
      if (!E || typeof E.el !== 'string' || typeof E.master !== 'string') return null;
      const o = { el: E.el.slice(0, 8), name: String(E.name || E.el).slice(0, 40), master: E.master.slice(0, 40),
        species: (E.species || []).map(entry).filter(Boolean), solids: (E.solids || []).map(entry).filter(Boolean) };
      if (typeof E.analogue === 'string') o.analogue = E.analogue.slice(0, 8);
      return o;
    }).filter(Boolean);
    if (!elements.length) return null;
    return { id: String(d.id || 'edited').slice(0, 40), label: String(d.label || '').slice(0, 200), major, elements };
  }

  const ORIGINAL = SFData.SRSITE;
  function originalEntry(el, kind, id) {
    if (el === 'major') return ORIGINAL.major.find((s) => s.id === id) || null;
    const E = ORIGINAL.elements.find((x) => x.el === el);
    if (!E) return null;
    return (kind === 'solid' ? E.solids : E.species).find((s) => s.id === id) || null;
  }
  function entryChanged(el, kind, s) {
    const o = originalEntry(el, kind, s.id);
    if (!o) return true;
    return o.rx !== s.rx || o.logK !== s.logK || (o.dlogK || 0) !== (s.dlogK || 0) || (o.use !== false) !== (s.use !== false);
  }
  /** How many entries differ from the SR-Site dataset (added, removed or changed). */
  function dataEdits() {
    let count = 0;
    for (const s of state.data.major) if (entryChanged('major', 'species', s)) count++;
    for (const E of state.data.elements) {
      const O = ORIGINAL.elements.find((x) => x.el === E.el);
      for (const s of E.species) if (entryChanged(E.el, 'species', s)) count++;
      for (const s of E.solids) if (entryChanged(E.el, 'solid', s)) count++;
      if (O) {
        count += O.species.filter((o) => !E.species.some((s) => s.id === o.id)).length;
        count += O.solids.filter((o) => !E.solids.some((s) => s.id === o.id)).length;
      }
    }
    return { count };
  }

  function renderDataSummary() {
    const d = dataEdits();
    $('sfDataLabel').textContent = d.count ? `SR-Site dataset with ${d.count} edited entr${d.count === 1 ? 'y' : 'ies'}.` : SFData.SRSITE.label + '.';
    $('sfDataCount').textContent = d.count ? `${d.count} edited` : '';
  }

  /* ---------------------------------------------------------------------
     Groundwater
     --------------------------------------------------------------------- */
  function waters() {
    if (!state.table) return [];
    return state.table.rawWaters.map((w) => {
      const x = { ...w };
      if (state.addMg && Number.isFinite(w.Mg)) x.Ca = w.Ca + w.Mg;
      return x;
    });
  }

  function waterLabel(i) {
    const w = state.table && state.table.rawWaters[i];
    if (!w) return `row ${i + 1}`;
    return w.id ? `${w.id}` : `row ${i + 1}`;
  }

  function setTable(t) {
    const w = t.rawWaters;
    t.hasMg = w.some((x) => Number.isFinite(x.Mg));
    t.hasEh = w.some((x) => Number.isFinite(x.Eh));
    t.hasFe = w.some((x) => Number.isFinite(x.Fe));
    state.table = t;
    if (state.water.row > w.length) state.water.row = 1;
    if (state.run.fixedWater >= w.length) state.run.fixedWater = 0;
    renderTableInfo();
    writeRunControls();
    markStale('The groundwater changed.');
  }

  function renderTableInfo() {
    const ul = $('sfTableInfo');
    const t = state.table;
    $('sfAddMgRow').hidden = !(t && t.hasMg);
    $('sfAddMg').checked = state.addMg;
    if (!t) { ul.innerHTML = ''; $('sfWaterCount').textContent = ''; return; }
    const ws = t.rawWaters;
    const overI = ws.filter((w) => w.I > 0.2).length;
    const pH = ws.map((w) => w.pH).sort((a, b) => a - b);
    const meta = [`${ws.length.toLocaleString('en')} water${ws.length === 1 ? '' : 's'}`, `pH ${fmtLog(pH[0])}–${fmtLog(pH[pH.length - 1])}`];
    if (t.sheet) meta.push(`sheet “${t.sheet}”`);
    const warns = [];
    if (t.skipped && t.skipped.length) warns.push(`${t.skipped.length} row${t.skipped.length > 1 ? 's' : ''} left out for a missing value (first: row ${t.skipped[0].row}, ${t.skipped[0].missing.join(', ')}).`);
    if (overI) warns.push(`${overI} with I above 0.2 mol/kg, beyond the range of the activity corrections.`);
    if (state.options.version === 'A' && !(t.hasEh && t.hasFe)) warns.push('Version A needs Eh (mV) and [Fe]tot columns, which this table does not have.');
    ul.innerHTML = `<li><span class="sf-file-name">${esc(t.name)}</span>`
      + `<button type="button" aria-label="Remove the groundwater table" data-on-click="sf:clearWater">×</button>`
      + `<span class="sf-file-meta">${esc(meta.join(' · '))}</span>`
      + warns.map((w) => `<span class="sf-file-warn">${esc(w)}</span>`).join('') + '</li>';
    $('sfWaterCount').textContent = `${ws.length.toLocaleString('en')}`;
  }

  async function loadWaterFile(file) {
    const size = typeof kvotFileTooLarge === 'function' ? kvotFileTooLarge(file) : null;
    if (size && size.tooLarge) { setStatus(size.reason, 'error'); return; }
    setStatus(`Reading ${file.name}…`);
    try {
      const res = await SFIO.readGroundwater(file, { SFModel });
      setTable({ name: file.name, rawWaters: res.waters, headers: res.headers, sheet: res.sheet, skipped: res.skipped, source: 'file' });
      state.example = '';
      $('sfExample').value = '';
      saveState();
      setStatus(`${file.name}: ${res.waters.length.toLocaleString('en')} waters${res.sheet ? ` from sheet “${res.sheet}”` : ''}. Press Run.`, 'ok');
      renderTab();
    } catch (e) {
      setStatus(`${file.name}: ${e.message}`, 'error');
    }
  }

  function loadExample(key, quiet) {
    let t;
    if (key === 'tr1061') t = { name: 'TR-10-61 table A-1 (12 reference waters)', rawWaters: SFData.TR1061_WATERS.map((w) => ({ ...w })), headers: [], sheet: '', skipped: [], source: 'example' };
    else if (key === 'tr1061range') t = { name: 'TR-10-61 table A-1, the 6 waters in the range of the tool', rawWaters: SFData.TR1061_WATERS.filter((w) => w.I <= 0.2 && w.pH > 6 && w.pH < 11).map((w) => ({ ...w })), headers: [], sheet: '', skipped: [], source: 'example' };
    else if (key === 'tr1061ex') t = { name: 'TR-10-61 table 3-1 (example water)', rawWaters: [{ ...SFData.TR1061_EXAMPLE }], headers: [], sheet: '', skipped: [], source: 'example' };
    else return;
    state.example = key;
    $('sfExample').value = key;
    setTable(t);
    saveState();
    if (!quiet) setStatus(`${t.name} loaded. Press Run.`, 'ok');
    renderTab();
  }

  /* ---------------------------------------------------------------------
     Controls
     --------------------------------------------------------------------- */
  function writeRunControls() {
    $('sfN').value = String(state.run.n);
    $('sfSeed').value = String(state.run.seed);
    $('sfDraw').value = state.run.draw;
    $('sfLhs').checked = state.run.lhs;
    $('sfVaryTD').checked = state.run.varyTD;
    $('sfFixedRow').hidden = state.run.draw !== 'fixed';
    const sel = $('sfFixedWater');
    const n = state.table ? state.table.rawWaters.length : 0;
    const shown = Math.min(n, 2000);
    let html = '';
    for (let i = 0; i < shown; i++) html += `<option value="${i}">${esc(`${i + 1}. ${waterLabel(i)}`)}</option>`;
    sel.innerHTML = html;
    sel.value = String(Math.min(state.run.fixedWater, Math.max(0, shown - 1)));
  }

  function writeOptionControls() {
    const o = state.options;
    $('sfVersion').value = o.version;
    $('sfReactionTerms').checked = o.reactionTerms;
    $('sfPoly').checked = o.polyStoichiometry;
    $('sfRaOH').checked = o.singleRaOH;
    $('sfEh').checked = o.ehExact;
    $('sfAnalogue').checked = o.analogueDraws;
    $('sfLimit').value = String(o.limit);
    $('sfUnits').value = state.units;
  }

  function readInt(el, min, max) {
    const x = Math.round(Number(String(el.value).trim().replace(/[\s_,]/g, '')));
    if (!Number.isFinite(x) || x < min || x > max) { el.setCustomValidity(`A whole number from ${min} to ${max}`); el.reportValidity(); return null; }
    el.setCustomValidity('');
    return x;
  }

  function markStale(why) {
    if (state.result && !state.result.stale) {
      state.result.stale = true;
      setStatus(`${why} The results shown are from the previous run; press Run.`, 'warn');
    }
  }

  /* ---------------------------------------------------------------------
     Running
     --------------------------------------------------------------------- */
  let worker = null;
  let workerBroken = false;
  let runSeq = 0;

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
    if (msg.type === 'progress') showProgress(msg.done, msg.n);
    else if (msg.type === 'done') finishRun(msg.result);
    else if (msg.type === 'error') failRun(msg.message);
  }

  function run() {
    if (state.running || state.splitting) return;
    compilePlan();
    if (!state.plan || state.planError) { setStatus(`The dataset has an error: ${state.planError}. Fix it on the Data tab.`, 'error'); showTab('data'); return; }
    const ws = waters();
    if (!ws.length) { setStatus('Load a groundwater table first: open or drop a file, or choose a built-in example.', 'warn'); return; }
    if (state.options.version === 'A') {
      const bad = ws.findIndex((w) => !Number.isFinite(w.Eh) || !(w.Fe > 0));
      if (bad >= 0) { setStatus(`Version A needs Eh (mV) and [Fe]tot for every water; ${waterLabel(bad)} has none. Choose Version B, or a table with those columns.`, 'error'); return; }
    }
    const cfg = { ...state.run, keepInputs: true, maxKeptValues: 6e6 };
    if (cfg.draw === 'randnorep' && cfg.n > ws.length) { setStatus(`Without replacement, ${cfg.n.toLocaleString('en')} realisations need at least as many waters; the table has ${ws.length.toLocaleString('en')}.`, 'error'); return; }
    const job = { id: ++runSeq, t0: performance.now(), cfg, options: modelOptions(), waters: ws, plan: state.plan, data: SFData.clone(state.data), viaWorker: false };
    state.running = job;
    $('sfRun').disabled = true;
    $('sfCancel').hidden = false;
    showProgress(0, cfg.n);
    setStatus(`Running ${cfg.n.toLocaleString('en')} realisations…`);
    const w = getWorker();
    if (w) {
      job.viaWorker = true;
      w.postMessage({ id: job.id, data: job.data, options: job.options, waters: ws, runCfg: cfg });
    } else {
      runInline(job);
    }
  }

  function runInline(job) {
    let runner;
    try { runner = SFModel.createRunner(job.plan, job.waters, job.cfg); } catch (e) { failRun(e.message); return; }
    const slice = () => {
      if (state.running !== job) return;
      const t = performance.now();
      while (runner.done < runner.n && performance.now() - t < 40) runner.step(250);
      showProgress(runner.done, runner.n);
      if (runner.done < runner.n) setTimeout(slice, 0);
      else finishRun(runner.result());
    };
    setTimeout(slice, 0);
  }

  /**
   * One more run, beside the main one, for the variability split: its own
   * worker (or the page), a promise of the result, the main result untouched.
   */
  function runOnce(cfg, onProgress) {
    const ws = waters();
    const data = SFData.clone(state.data);
    const options = modelOptions();
    const inline = () => new Promise((resolve, reject) => setTimeout(() => {
      try { resolve(SFModel.run(SFModel.compile(data, options), ws, cfg)); } catch (e) { reject(e); }
    }, 0));
    if (workerBroken) return inline();
    return new Promise((resolve, reject) => {
      let w;
      try { w = new Worker(WORKER_URL); } catch (e) { workerBroken = true; inline().then(resolve, reject); return; }
      w.onmessage = (ev) => {
        const m = ev.data || {};
        if (m.type === 'progress' && onProgress) onProgress(m.done, m.n);
        else if (m.type === 'done') { w.terminate(); resolve(m.result); }
        else if (m.type === 'error') { w.terminate(); reject(new Error(m.message)); }
      };
      w.onerror = (ev) => { ev.preventDefault(); w.terminate(); workerBroken = true; inline().then(resolve, reject); };
      w.postMessage({ id: 1, data, options, waters: ws, runCfg: cfg });
    });
  }

  async function splitVariability() {
    const R = state.result;
    if (!R || state.running || state.splitting) return;
    if (R.stale) { setStatus('Run the calculation again first: the settings have changed since.', 'warn'); return; }
    const row = Math.max(1, Math.min(R.waters.length, state.water.row)) - 1;
    const base = { ...R.cfg, keepInputs: false };
    state.splitting = true;
    $('sfProgress').hidden = false;
    try {
      setStatus('Splitting the variability: the groundwater alone (constants at their nominal values)…');
      const gw = await runOnce({ ...base, varyTD: false }, (d, n) => { $('sfProgressBar').style.width = `${(50 * d / n).toFixed(1)}%`; });
      setStatus(`…and the constants alone, for ${waterLabel(row)}…`);
      const td = await runOnce({ ...base, varyTD: true, draw: 'fixed', fixedWater: row }, (d, n) => { $('sfProgressBar').style.width = `${(50 + 50 * d / n).toFixed(1)}%`; });
      const st = (res) => R.plan.elements.map((E, e) => SFModel.describe(res.S[e]));
      R.split = { row, name: waterLabel(row), gw: st(gw), td: st(td) };
      setStatus(`Variability split: groundwater alone and constants alone (${waterLabel(row)}), ${R.res.n.toLocaleString('en')} realisations each.`, 'ok');
    } catch (e) {
      setStatus(`The split failed: ${e.message}`, 'error');
    } finally {
      state.splitting = false;
      $('sfProgress').hidden = true;
      $('sfProgressBar').style.width = '0';
    }
    renderTab();
  }

  function showProgress(done, n) {
    $('sfProgress').hidden = false;
    $('sfProgressBar').style.width = `${n ? (100 * done / n).toFixed(1) : 0}%`;
    if (state.running && done) setStatus(`Running: ${done.toLocaleString('en')} of ${n.toLocaleString('en')} realisations…`);
  }

  function endRunUi() {
    $('sfRun').disabled = false;
    $('sfCancel').hidden = true;
    $('sfProgress').hidden = true;
  }

  function finishRun(res) {
    const job = state.running;
    state.running = null;
    endRunUi();
    const ms = performance.now() - job.t0;
    state.result = {
      res, plan: job.plan, waters: job.waters, cfg: job.cfg, options: job.options, ms, stale: false,
      stats: job.plan.elements.map((E, e) => ({ el: E.el, d: SFModel.describe(res.S[e]) })),
      tableName: state.table ? state.table.name : '', fits: {}, sens: {},
    };
    const d = res.diag;
    let msg = `${res.n.toLocaleString('en')} realisations in ${(ms / 1000).toFixed(ms < 10000 ? 2 : 1)} s.`;
    let tone = 'ok';
    if (d.failed) { msg += ` ${d.failed} failed (${d.firstError}).`; tone = 'warn'; }
    setStatus(msg, tone);
    renderTab();
  }

  function failRun(message) {
    state.running = null;
    endRunUi();
    setStatus(`The run failed: ${message}`, 'error');
  }

  function cancelRun() {
    if (!state.running) return;
    if (state.running.viaWorker && worker) { worker.terminate(); worker = null; }
    state.running = null;
    endRunUi();
    setStatus('Stopped.', 'warn');
  }

  /* ---------------------------------------------------------------------
     Charts
     --------------------------------------------------------------------- */
  /** For Plotly, which reads a few tags in trace names: file- or data-derived text without any. */
  const plain = (s) => String(s ?? '').replace(/[<>&"]/g, '');
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
      margin: { l: 64, r: 24, t: 24, b: 56 },
      paper_bgcolor: 'rgba(0,0,0,0)',
      plot_bgcolor: 'rgba(0,0,0,0)',
      font: { color: c.text, size: 11, family: 'verdana, sans-serif' },
      legend: { orientation: 'h', y: -0.18, font: { size: 10 } },
      xaxis: { gridcolor: c.grid, zeroline: false, linecolor: c.grid },
      yaxis: { gridcolor: c.grid, zeroline: false, linecolor: c.grid },
      hovermode: 'closest',
      hoverlabel: { bgcolor: c.surface, bordercolor: c.grid, font: { color: c.text, size: 11 } },
    }, extra);
  }
  const havePlotly = () => typeof Plotly !== 'undefined';
  function resizePlots() {
    if (!havePlotly()) return;
    ['sfChartDist', 'sfChartSens', 'sfChartSweep', 'sfChartCompare', 'sfChartBox'].forEach((id) => { const el = $(id); if (el && !el.hidden && el.data) Plotly.Plots.resize(el); });
  }

  /* ---------------------------------------------------------------------
     Summary
     --------------------------------------------------------------------- */
  function introHtml() {
    const t = state.table;
    return `<h3>Solubility limits by the Simple Functions</h3>
      <p class="sf-muted" style="max-width:60rem;font-size:12px">The SR-Site and PSAR calculation of the solubility of 20 radionuclides in the water of a failed canister: a groundwater drawn from a table, the equilibrium constants sampled within their uncertainties, and for each element the lowest solubility of its candidate solids. ${t ? `The table <b>${esc(t.name)}</b> is loaded: press <b>Run</b>.` : 'Load a groundwater table — drop a CSV or Excel file on the panel, or choose a built-in example — and press <b>Run</b>.'} The <b>One water</b> tab needs no run: it calculates one composition at once.</p>`;
  }

  function renderSummary() {
    const host = $('sfSummary');
    const R = state.result;
    if (!R) { host.innerHTML = introHtml(); return; }
    const off = unitOffset();
    const { res, plan } = R;
    const lim = state.options.limit;
    const d = res.diag;
    const distinct = new Set(res.waterIndex).size;
    const cards = [
      [res.n.toLocaleString('en'), 'realisations'],
      [distinct.toLocaleString('en'), `waters drawn, of ${R.waters.length.toLocaleString('en')} in ${esc(R.tableName || 'the table')}`],
      [R.options.version === 'A' ? 'A' : 'B', R.options.version === 'A' ? 'Eh and [Fe]tot from the table' : 'magnetite/goethite redox'],
      [R.cfg.varyTD ? String(plan.params.filter((p, i) => plan.sigma[i] > 0).length) : 'none', 'equilibrium constants sampled'],
    ];
    const warns = [];
    if (R.stale) warns.push('Settings have changed since this run; press Run to bring it up to date.');
    if (d.overI) warns.push(`${d.overI.toLocaleString('en')} realisation${d.overI > 1 ? 's' : ''} (${pct(d.overI / res.n)} %) drew a water with I above 0.2 mol/kg: “your calculations will not be completely correct”, as the workbook put it.`);
    if (d.calciteOver) warns.push(`Calcite is oversaturated in ${d.calciteOver.toLocaleString('en')} realisation${d.calciteOver > 1 ? 's' : ''} (${pct(d.calciteOver / res.n)} %; SI up to ${fmtLog(d.maxSIcalcite)}). It is not allowed to precipitate.`);
    if (R.options.version !== 'A') {
      const fe = SFModel.describe(d.Fe);
      const high = Array.from(d.Fe).filter((x) => x > 0.01).length;
      warns.push(`[Fe+2] from goethite at the magnetite/goethite pO2 and the pH of the water: median ${fmt(Math.pow(10, fe.p50), 2)} mol/kg, P95 ${fmt(Math.pow(10, fe.p95), 2)}, above 0.01 mol/kg in ${pct(high / res.n)} % of the realisations. See the One water tab for the siderite saturation such a water implies.`);
    }
    if (d.failed) warns.push(`${d.failed} realisation${d.failed > 1 ? 's' : ''} could not be calculated: ${esc(d.firstError)}.`);
    const rows = plan.elements.map((E, e) => {
      const st = R.stats[e].d;
      const counts = new Array(E.solids.length).fill(0);
      let over = 0;
      const S = res.S[e], C = res.control[e];
      for (let i = 0; i < res.n; i++) { const c = C[i]; if (c < 255) counts[c]++; if (S[i] > lim) over++; }
      const tot = counts.reduce((a, b) => a + b, 0) || 1;
      const order = counts.map((c, k) => k).filter((k) => counts[k] > 0).sort((a, b) => counts[b] - counts[a]);
      const bar = `<div class="sf-phasebar">${order.map((k) => `<span style="width:${(100 * counts[k] / tot).toFixed(2)}%;background:${PALETTE[k % PALETTE.length]}"></span>`).join('')}</div>`;
      const names = order.slice(0, 3).map((k) => `<span class="sf-legend-dot" style="background:${PALETTE[k % PALETTE.length]}"></span>${esc(E.solids[k].id)} ${pct(counts[k] / tot)} %`).join(' &nbsp; ') + (order.length > 3 ? ` &nbsp; +${order.length - 3}` : '');
      const v = (x) => fmtLog(x + off);
      return `<tr class="clickable" data-on-click="sf:summaryRow" data-el="${esc(E.el)}"><td class="el">${esc(E.el)}</td><td class="phase">${names}${bar}</td>`
        + `<td>${v(st.min)}</td><td>${v(st.p5)}</td><td>${v(st.p25)}</td><td><b>${v(st.p50)}</b></td><td>${v(st.p75)}</td><td><b>${v(st.p95)}</b></td><td>${v(st.max)}</td>`
        + `<td class="${over ? 'flag' : 'dim'}">${over ? pct(over / res.n) : '0'}</td></tr>`;
    }).join('');
    host.innerHTML = `
      <div class="sf-cards">${cards.map(([v, l]) => `<div class="sf-card"><div class="sf-card-value">${v}</div><div class="sf-card-label">${l}</div></div>`).join('')}</div>
      ${warns.length ? `<ul class="sf-warnings">${warns.map((w) => `<li>${w}</li>`).join('')}</ul>` : ''}
      <h3>log<sub>10</sub> solubility, ${unitLabel()}</h3>
      <div class="sf-table-wrap"><table class="sf-table sf-el-table">
        <thead><tr><th class="text">Element</th><th class="text">Controlling solid</th><th>min</th><th>P5</th><th>P25</th><th>P50</th><th>P75</th><th>P95</th><th>max</th><th>% &gt; ${fmt(lim, 2)} m</th></tr></thead>
        <tbody>${rows}</tbody></table></div>
      <p class="sf-muted">Click an element for its distribution. P5–P95 is the whisker and P25–P75 the box below; the percentiles are over all realisations.</p>
      <div class="plot short" id="sfChartBox"></div>
      <div class="sf-toolbar"><button type="button" class="sf-btn secondary small" data-on-click="sf:split"${R.stale ? ' disabled' : ''}>Split the variability</button>
        <span class="sf-muted">${R.split ? `Groundwater alone, and the constants alone for ${esc(R.split.name)}${/^row /.test(R.split.name) ? '' : ` (row ${R.split.row + 1})`}; choose another water on the One water tab.` : 'Two more runs: the groundwater alone (constants nominal), and the constants alone for the water of the One water tab.'}</span></div>
      ${R.split ? splitTable(R) : ''}`;
    if (!havePlotly()) return;
    const c = themeColors();
    const els = plan.elements.map((E) => E.el);
    const pick = (k) => R.stats.map((s) => s.d[k] + off);
    const trace = {
      type: 'box', x: els, q1: pick('p25'), median: pick('p50'), q3: pick('p75'), lowerfence: pick('p5'), upperfence: pick('p95'),
      marker: { color: c.accent }, line: { color: c.accent, width: 1.2 }, fillcolor: 'rgba(187,108,93,0.18)', name: 'P5–P25–P50–P75–P95', hoverinfo: 'x+y',
    };
    const mins = { type: 'scatter', mode: 'markers', x: els, y: pick('min'), marker: { symbol: 'line-ew-open', size: 10, color: c.muted }, name: 'min, max', hoverinfo: 'y' };
    const maxs = { ...mins, y: pick('max'), showlegend: false };
    const traces = [trace, mins, maxs];
    const layout = baseLayout({ yaxis: { title: `log₁₀ S (${unitLabel()})`, gridcolor: c.grid, zeroline: false }, xaxis: { gridcolor: c.grid }, showlegend: true, margin: { l: 64, r: 16, t: 10, b: 60 } });
    if (R.split) {
      trace.name = 'both'; trace.offsetgroup = 'a';
      mins.showlegend = false; mins.visible = false; maxs.visible = false;
      const box = (st, name, color, fill, group) => ({
        type: 'box', x: els, q1: st.map((d) => d.p25 + off), median: st.map((d) => d.p50 + off), q3: st.map((d) => d.p75 + off),
        lowerfence: st.map((d) => d.p5 + off), upperfence: st.map((d) => d.p95 + off), name, offsetgroup: group,
        marker: { color }, line: { color, width: 1.2 }, fillcolor: fill, hoverinfo: 'x+y',
      });
      traces.push(box(R.split.gw, 'groundwater alone', '#4e79a7', 'rgba(78,121,167,0.18)', 'b'), box(R.split.td, 'constants alone', '#59a14f', 'rgba(89,161,79,0.18)', 'c'));
      layout.boxmode = 'group';
    }
    Plotly.react($('sfChartBox'), traces, layout, PLOT_CONFIG);
  }

  function splitTable(R) {
    const rows = R.plan.elements.map((E, e) => {
      const w = (d) => d.p95 - d.p5;
      const all = w(R.stats[e].d), g = w(R.split.gw[e]), t = w(R.split.td[e]);
      const ratio = t > 1e-9 ? g / t : Infinity;
      return `<tr><td class="el">${esc(E.el)}</td><td>${all.toFixed(2)}</td><td>${g.toFixed(2)}</td><td>${t.toFixed(2)}</td><td>${Number.isFinite(ratio) ? ratio.toFixed(2) : '∞'}</td><td class="text">${ratio > 2 ? 'the groundwater' : ratio < 0.5 ? 'the constants' : 'both'}</td></tr>`;
    }).join('');
    return `<table class="sf-table" style="margin-top:6px"><thead><tr><th class="text">El.</th><th>P95 − P5, both</th><th>groundwater alone</th><th>constants alone</th><th>ratio</th><th class="text">spread mostly from</th></tr></thead><tbody>${rows}</tbody></table>
      <p class="sf-muted">Widths of the central 90 % in log units. The constants alone are for one water; another water can give another width.</p>`;
  }

  /* ---------------------------------------------------------------------
     One water
     --------------------------------------------------------------------- */
  const WATER_FIELDS = [
    ['pH', 'pH', ''], ['I', 'I', 'mol/kg'], ['HCO3', '[HCO3-] free', 'm'], ['SO4', '[SO4]tot', 'm'], ['Cl', '[Cl]tot', 'm'],
    ['Ca', '[Ca]tot', 'm'], ['Na', '[Na]tot', 'm'], ['Si', '[Si]tot', 'm'], ['Eh', 'Eh (A)', 'mV'], ['Fe', '[Fe]tot (A)', 'm'],
  ];

  function baseWater() {
    const ws = waters();
    if (ws.length) {
      const i = Math.max(1, Math.min(ws.length, state.water.row)) - 1;
      return { ...ws[i] };
    }
    return { ...SFData.TR1061_EXAMPLE };
  }

  function currentWater() {
    const w = baseWater();
    if (state.water.custom) for (const [k, v] of Object.entries(state.water.edits)) if (Number.isFinite(v)) w[k] = v;
    return w;
  }

  function renderWaterForm() {
    const ws = waters();
    const rowIn = $('sfWaterRow');
    rowIn.max = String(Math.max(1, ws.length));
    rowIn.value = String(Math.max(1, Math.min(ws.length || 1, state.water.row)));
    rowIn.disabled = !ws.length;
    $('sfWaterRowNote').textContent = ws.length ? `of ${ws.length.toLocaleString('en')}: ${waterLabel(Math.max(0, Math.min(ws.length, state.water.row) - 1))}` : 'no table: the TR-10-61 example water';
    $('sfWaterCustom').checked = state.water.custom;
    const w = currentWater();
    const base = baseWater();
    $('sfWaterForm').innerHTML = WATER_FIELDS.map(([k, label, unit]) => {
      const changed = state.water.custom && Number.isFinite(state.water.edits[k]) && state.water.edits[k] !== base[k];
      const dis = !state.water.custom || ((k === 'Eh' || k === 'Fe') && state.options.version !== 'A');
      return `<div><label for="sfW_${k}">${esc(label)}${unit ? ` <span class="sf-unit">${unit}</span>` : ''}</label><input id="sfW_${k}" type="text" inputmode="decimal" data-key="${k}" data-on-change="sf:waterFieldChanged" value="${esc(numberText(w[k]))}"${dis ? ' disabled' : ''}${changed ? ' class="changed"' : ''}></div>`;
    }).join('');
  }

  function renderWater() {
    renderWaterForm();
    const out = $('sfWaterOut');
    compilePlan();
    if (!state.plan || state.planError) { out.innerHTML = `<p class="sf-empty">The dataset has an error: ${esc(state.planError || '')}</p>`; return; }
    const w = currentWater();
    let A;
    try { A = SFModel.analyse(state.plan, w); } catch (e) { out.innerHTML = `<p class="sf-empty">${esc(e.message)}</p>`; return; }
    state.lastAnalysis = { water: w, A };
    const gw = A.gw;
    const L = gw.lig;
    const I = SFModel.LIG;
    const off = unitOffset();
    const siSid = Math.log10(L[I.Fe] * L[I.CO3]) + 2 * gw.q[2] - LOG_KSIDERITE;
    const lig = [
      ['pH', fmt(w.pH, 4)], ['I (input)', `${fmt(w.I, 4)} mol/kg${w.I > 0.2 ? ' — above 0.2' : ''}`],
      ['log γ, z = 1, 2, 3, 4', `${gw.q[1].toFixed(3)}, ${gw.q[2].toFixed(3)}, ${gw.q[3].toFixed(3)}, ${gw.q[4].toFixed(3)}`],
      ['[CO3-2]', fmt(L[I.CO3], 4)], ['[SO4-2] free', `${fmt(L[I.SO4], 4)} (${pct(L[I.SO4] / w.SO4)} % of total)`],
      ['[Cl-]', fmt(L[I.Cl], 4)], ['[Ca+2]', fmt(L[I.Ca], 4)], ['[Na+]', fmt(L[I.Na], 4)], ['[Fe+2]', fmt(L[I.Fe], 4)],
      ['Eh', `${gw.Eh.toFixed(1)} mV, pe ${gw.pe.toFixed(2)}`], ['log pO2(g)', gw.logPO2.toFixed(2)],
      ['SI calcite', `${gw.siCalcite.toFixed(2)}${gw.siCalcite > 0 ? ' — oversaturated' : ''}`],
      ['SI siderite', `${siSid.toFixed(2)}${siSid > 0 ? ' — oversaturated' : ''} (not in the tool; log K = −10.89)`],
    ];
    const sel = state.waterEl;
    const rows = A.elements.map((r, e) => {
      const E = state.plan.elements[e];
      const used = r.solids.map((s, k) => ({ s, k })).filter((x) => E.solids[x.k].use && Number.isFinite(x.s)).sort((a, b) => a.s - b.s);
      const next = used.length > 1 ? Math.log10(used[1].s) - Math.log10(used[0].s) : NaN;
      const main = (r.speciation || []).slice().sort((a, b) => b.frac - a.frac)[0];
      const top = r.terms.slice(0, 2).map((t) => `${esc(t.id)} ${t.fZ.toFixed(0)} %`).join(', ');
      const flag = r.S > state.options.limit;
      return `<tr class="clickable${E.el === sel ? ' selected' : ''}" data-on-click="sf:waterEl" data-el="${esc(E.el)}"><td class="el">${esc(E.el)}</td>`
        + `<td class="${flag ? 'flag' : ''}">${fmtLog(r.logS + off)}</td><td>±${(2 * r.sigma).toFixed(2)}</td>`
        + `<td class="text">${esc(r.control >= 0 ? E.solids[r.control].id : '–')}${flag ? ' <span class="sf-muted">(n.s.l.)</span>' : ''}</td>`
        + `<td class="text">${used.length > 1 ? `${esc(E.solids[used[1].k].id)} +${next.toFixed(2)}` : '–'}</td>`
        + `<td class="text">${main ? `${esc(main.id)} ${pct(main.frac)} %` : '–'}</td><td class="text">${top}</td></tr>`;
    }).join('');
    out.innerHTML = `<div class="sf-kv">${lig.map(([k, v]) => `<div><b>${esc(k)}</b><span>${esc(v)}</span></div>`).join('')}</div>
      <p class="sf-muted" style="margin:-4px 0 10px">${state.options.version === 'A' ? 'Version A: pO2 from the Eh of the water, [Fe+2] from its total iron.' : 'Version B: pO2 at the magnetite/goethite boundary, [Fe+2] from goethite.'}</p>
      <h4 class="sf-h4">Solubility at the nominal constants, log<sub>10</sub> ${unitLabel()}</h4>
      <div class="sf-table-wrap"><table class="sf-table sf-water-table"><thead><tr><th class="text">El.</th><th>log S</th><th>±2σ</th><th class="text">Controlling solid</th><th class="text">Next solid, log units above</th><th class="text">Main aqueous species</th><th class="text">Uncertainty carried by (f<sub>Z</sub>)</th></tr></thead><tbody>${rows}</tbody></table></div>
      <p class="sf-muted">Click an element for its solids, speciation and constants. n.s.l.: above ${fmt(state.options.limit, 2)} mol/kg, “not solubility limited”.</p>
      <div id="sfWaterDetail" class="sf-detail-grid"></div>`;
    renderWaterDetail();
  }

  function renderWaterDetail() {
    const host = $('sfWaterDetail');
    if (!host || !state.lastAnalysis) return;
    const { A } = state.lastAnalysis;
    const e = state.plan.elements.findIndex((E) => E.el === state.waterEl);
    if (e < 0) { host.innerHTML = ''; return; }
    const E = state.plan.elements[e];
    const r = A.elements[e];
    const off = unitOffset();
    const minLog = Math.log10(r.S);
    const solids = E.solids.map((so, k) => ({ id: so.id, use: so.use, log: Math.log10(r.solids[k]) })).sort((a, b) => a.log - b.log);
    const specs = (r.speciation || []).slice().sort((a, b) => b.frac - a.frac).filter((s) => s.frac >= 0.001);
    const terms = r.terms.filter((t) => t.fZ >= 0.1).slice(0, 6);
    host.innerHTML = `<div class="sf-detail"><h4>${esc(E.name)} (${esc(E.el)}): candidate solids</h4>
      <table class="sf-table"><thead><tr><th class="text">Candidate solid</th><th>log S</th><th>above the lowest</th></tr></thead><tbody>
        ${solids.map((s) => `<tr><td class="text">${esc(s.id)}${s.use ? '' : ' <span class="sf-muted">(not in the minimum)</span>'}</td><td>${fmtLog(s.log + off)}</td><td>${s.log - minLog > 1e-9 ? `+${(s.log - minLog).toFixed(2)}` : (s.use ? 'controls' : '')}</td></tr>`).join('')}
      </tbody></table></div>
      <div class="sf-detail"><h4>Aqueous species at the controlling solid</h4>
      <table class="sf-table"><thead><tr><th class="text">Species</th><th>% of dissolved</th><th class="text"></th></tr></thead><tbody>
        ${specs.map((s) => `<tr><td class="text">${esc(s.id)}${s.n > 1 ? ` <span class="sf-muted">(${s.n}-mer)</span>` : ''}</td><td>${pct(s.frac)}</td><td class="text"><span class="sf-bar" style="width:${Math.max(1, Math.round(120 * s.frac))}px"></span></td></tr>`).join('')}
      </tbody></table></div>
      <div class="sf-detail"><h4>What carries the uncertainty</h4>
      <table class="sf-table"><thead><tr><th class="text">Constant</th><th>∂log S/∂log K</th><th>ΔlogK</th><th>f<sub>Z</sub> %</th></tr></thead><tbody>
        ${terms.map((t) => `<tr><td class="text">${esc(t.group === 'Major ions' ? `${t.id} (major ions)` : t.id)}</td><td>${t.dlogS.toFixed(3)}</td><td>${fmt(state.plan.params[t.param].dlogK, 3)}</td><td>${t.fZ.toFixed(1)}</td></tr>`).join('')}
      </tbody></table>
      <p class="sf-muted">2σ of log S = ${(2 * r.sigma).toFixed(2)}; in TR-10-61’s convention ${(2 * r.sigma / Math.LN10).toFixed(2)}.</p></div>`;
  }

  function waterCsv() {
    if (!state.lastAnalysis) return;
    const { water, A } = state.lastAnalysis;
    const rows = [['Element', 'log10 S (mol/kg)', 'S (mol/kg)', '2 sigma log S', 'Controlling solid', ...Array.from({ length: 6 }, (_, k) => `Solid ${k + 1} log10 S`)]];
    A.elements.forEach((r, e) => {
      const E = state.plan.elements[e];
      rows.push([E.el, r.logS, r.S, 2 * r.sigma, r.control >= 0 ? E.solids[r.control].id : '', ...E.solids.map((so, k) => `${so.id}=${Math.log10(r.solids[k])}`)]);
    });
    rows.push([]);
    rows.push(['Water', ...Object.entries(water).map(([k, v]) => `${k}=${v}`)]);
    download('simplefunctions_one_water.csv', SFIO.toCsv(rows));
  }

  /* ---------------------------------------------------------------------
     Distributions
     --------------------------------------------------------------------- */
  function elementOptions(selId, value, withAll) {
    const sel = $(selId);
    const els = (state.plan || state.result?.plan || { elements: [] }).elements.map((E) => E.el);
    sel.innerHTML = (withAll ? '<option value="all">all twenty</option>' : '') + els.map((el) => `<option value="${esc(el)}">${esc(el)}</option>`).join('');
    sel.value = els.includes(value) || (withAll && value === 'all') ? value : (els[0] || '');
    return sel.value;
  }

  /** [min, max] of one or more arrays, without spreading them into arguments. */
  function extent(...arrays) {
    let lo = Infinity, hi = -Infinity;
    for (const a of arrays) { if (!a) continue; for (let i = 0; i < a.length; i++) { const v = a[i]; if (v < lo) lo = v; if (v > hi) hi = v; } }
    return [lo, hi];
  }

  function logValues(arr, off, cond) {
    const out = [];
    for (let i = 0; i < arr.length; i++) { const v = arr[i]; if (v > 0 && (!cond || cond(i))) out.push(Math.log10(v) + off); }
    return out;
  }

  function binEdges(lo, hi, width = 0.1) {
    const a = Math.floor(lo / width) * width, b = Math.ceil(hi / width) * width + width * 0.5;
    const edges = [];
    for (let x = a; x <= b + 1e-9; x += width) edges.push(Math.round(x * 1e6) / 1e6);
    return edges;
  }

  function histogram(values, edges) {
    const counts = new Array(edges.length - 1).fill(0);
    const w = edges[1] - edges[0];
    for (const v of values) {
      let k = Math.floor((v - edges[0]) / w);
      if (k < 0) k = 0; if (k >= counts.length) k = counts.length - 1;
      counts[k]++;
    }
    return counts;
  }

  function refValues(el) {
    if (!state.ref || !state.ref.data[el]) return null;
    const scale = state.refUnits === 'molm3' ? 1e-3 : 1;
    return Array.from(state.ref.data[el], (x) => x * scale);
  }

  function getFit(e) {
    const R = state.result;
    if (!R.fits[e]) R.fits[e] = SFModel.fitDistribution(R.res.S[e]);
    return R.fits[e];
  }

  function renderDist() {
    const R = state.result;
    const plot = $('sfChartDist');
    const empty = $('sfDistEmpty');
    $('sfDistRefRow').hidden = !state.ref;
    $('sfDistKind').value = state.dist.kind;
    $('sfDistPhase').checked = state.dist.phase;
    $('sfDistFit').checked = state.dist.fit;
    $('sfDistRef').checked = state.dist.ref;
    if (!R || !havePlotly()) { plot.hidden = true; empty.hidden = false; empty.textContent = !havePlotly() ? 'The chart library (Plotly) did not load.' : 'Run the calculation to see the distributions.'; $('sfDistNote').innerHTML = ''; return; }
    const el = elementOptions('sfDistEl', state.dist.el, true);
    state.dist.el = el;
    plot.hidden = false; empty.hidden = true;
    const off = unitOffset();
    const c = themeColors();
    const kind = state.dist.kind;
    const ytitle = kind === 'hist' ? 'fraction of realisations' : (kind === 'cdf' ? 'P(S ≤ x)' : 'P(S > x)');
    if (el === 'all') {
      plot.classList.add('tall');
      const traces = [];
      const annotations = [];
      R.plan.elements.forEach((E, e) => {
        const ax = e === 0 ? '' : String(e + 1);
        const v = logValues(R.res.S[e], off);
        const ref = state.dist.ref ? refValues(E.el) : null;
        const rv = ref ? logValues(ref, off) : null;
        traces.push(...distTraces(v, rv, kind, `x${ax}`, `y${ax}`, c, false));
        annotations.push({ text: `<b>${E.el}</b>`, xref: `x${ax} domain`, yref: `y${ax} domain`, x: 0.02, y: 0.98, showarrow: false, xanchor: 'left', yanchor: 'top', font: { size: 11 } });
      });
      const layout = baseLayout({ grid: { rows: 5, columns: 4, pattern: 'independent', xgap: 0.08, ygap: 0.12 }, showlegend: false, annotations, margin: { l: 40, r: 10, t: 10, b: 36 } });
      for (let e = 0; e < R.plan.elements.length; e++) {
        const ax = e === 0 ? '' : String(e + 1);
        layout[`xaxis${ax}`] = { gridcolor: c.grid, zeroline: false, tickfont: { size: 9 } };
        layout[`yaxis${ax}`] = { gridcolor: c.grid, zeroline: false, tickfont: { size: 9 }, rangemode: 'tozero', ...(kind !== 'hist' ? { range: [0, 1] } : {}) };
      }
      Plotly.react(plot, traces, layout, PLOT_CONFIG);
      $('sfDistNote').innerHTML = `<p class="sf-muted">log<sub>10</sub> S in ${unitLabel()}${state.ref && state.dist.ref ? `; the line is the reference, ${esc(state.ref.name)}` : ''}.</p>`;
      return;
    }
    plot.classList.remove('tall');
    const e = R.plan.elements.findIndex((E) => E.el === el);
    const E = R.plan.elements[e];
    const S = R.res.S[e], C = R.res.control[e];
    const all = logValues(S, off);
    const ref = state.dist.ref ? refValues(el) : null;
    const rv = ref ? logValues(ref, off) : null;
    let traces;
    if (kind === 'hist' && state.dist.phase) {
      const [lo, hi] = extent(all, rv);
      const edges = binEdges(lo, hi);
      const mids = edges.slice(0, -1).map((x, k) => (x + edges[k + 1]) / 2);
      traces = E.solids.map((so, k) => {
        const v = logValues(S, off, (i) => C[i] === k);
        if (!v.length) return null;
        const h = histogram(v, edges).map((x) => x / all.length);
        return { type: 'bar', x: mids, y: h, width: edges[1] - edges[0], name: `${plain(so.id)} (${pct(v.length / all.length)} %)`, marker: { color: PALETTE[k % PALETTE.length] }, hovertemplate: `${plain(so.id)}<br>%{x:.2f}: %{y:.4f}<extra></extra>` };
      }).filter(Boolean);
      if (rv) traces.push(refStep(rv, edges, c));
    } else {
      traces = distTraces(all, rv, kind, 'x', 'y', c, true);
    }
    let note = '';
    if (state.dist.fit) {
      const f = getFit(e);
      if (f) {
        const [lo, hi] = extent(all);
        const xs = []; for (let k = 0; k <= 200; k++) xs.push(lo + (hi - lo) * k / 200);
        const pdf = (x) => (f.best === 'skew-normal' ? SFModel.skewNormalPdf(x - off, f.skew.xi, f.skew.omega, f.skew.alpha) : Math.exp(-0.5 * Math.pow((x - off - f.normal.mu) / f.normal.sigma, 2)) / (f.normal.sigma * Math.sqrt(2 * Math.PI)));
        let ys;
        if (kind === 'hist') ys = xs.map((x) => pdf(x) * 0.1);
        else {
          ys = []; let acc = 0; const dx = (hi - lo) / 200;
          const p0 = pdf(lo);
          ys.push(0);
          for (let k = 1; k <= 200; k++) { acc += 0.5 * (pdf(xs[k - 1]) + pdf(xs[k])) * dx; ys.push(acc); }
          const tailLo = f.best === 'skew-normal' ? 0 : SFModel.normCdf((lo - off - f.normal.mu) / f.normal.sigma);
          ys = ys.map((y) => y + tailLo);
          void p0;
          if (kind === 'ccdf') ys = ys.map((y) => 1 - y);
        }
        traces.push({ type: 'scatter', mode: 'lines', x: xs, y: ys, name: `fitted ${f.best}`, line: { color: c.text, width: 1.6, dash: 'dash' } });
        note = `<table class="sf-key"><thead><tr><th>Fit to log<sub>10</sub> S (mol/kg)</th><th>μ or ξ</th><th>σ or ω</th><th>α</th><th>AIC</th></tr></thead><tbody>
          <tr${f.best === 'normal' ? ' class="total"' : ''}><th>normal</th><td>${f.normal.mu.toFixed(3)}</td><td>${f.normal.sigma.toFixed(3)}</td><td>0</td><td>${f.normal.aic.toFixed(1)}</td></tr>
          <tr${f.best === 'skew-normal' ? ' class="total"' : ''}><th>skew-normal</th><td>${f.skew.xi.toFixed(3)}</td><td>${f.skew.omega.toFixed(3)}</td><td>${f.skew.alpha.toFixed(2)}</td><td>${f.skew.aic.toFixed(1)}</td></tr></tbody></table>
          <p class="sf-muted">The one in bold is kept (skew-normal when its AIC is lower by more than 2). f(x) = (2/ω) φ((x−ξ)/ω) Φ(α(x−ξ)/ω).</p>`;
      }
    }
    const st = R.stats[e].d;
    const layout = baseLayout({
      barmode: 'stack', bargap: 0,
      xaxis: { title: `log₁₀ S, ${E.el} (${unitLabel()})`, gridcolor: c.grid, zeroline: false },
      yaxis: { title: ytitle, gridcolor: c.grid, zeroline: false, rangemode: 'tozero', ...(kind !== 'hist' ? { range: [0, 1] } : {}) },
      shapes: [st.p5, st.p50, st.p95].map((p, k) => ({ type: 'line', xref: 'x', yref: 'paper', x0: p + off, x1: p + off, y0: 0, y1: 1, line: { color: c.muted, width: 1, dash: k === 1 ? 'solid' : 'dot' } })),
    });
    Plotly.react(plot, traces, layout, PLOT_CONFIG);
    $('sfDistNote').innerHTML = `<p class="sf-muted">Lines at P5, P50 and P95: ${fmtLog(st.p5 + off)}, ${fmtLog(st.p50 + off)}, ${fmtLog(st.p95 + off)}.</p>${note}`;
  }

  function refStep(rv, edges, c) {
    const h = histogram(rv, edges).map((x) => x / rv.length);
    const xs = [], ys = [];
    h.forEach((y, k) => { xs.push(edges[k], edges[k + 1]); ys.push(y, y); });
    return { type: 'scatter', mode: 'lines', x: xs, y: ys, name: `reference (${plain(state.ref.name)})`, line: { color: c.text, width: 1.3 }, hoverinfo: 'skip' };
  }

  function distTraces(v, rv, kind, xa, ya, c, legend) {
    const out = [];
    if (!v.length) return out;
    if (kind === 'hist') {
      const [lo, hi] = extent(v, rv);
      const edges = binEdges(lo, hi);
      const mids = edges.slice(0, -1).map((x, k) => (x + edges[k + 1]) / 2);
      const h = histogram(v, edges).map((x) => x / v.length);
      out.push({ type: 'bar', x: mids, y: h, width: edges[1] - edges[0], xaxis: xa, yaxis: ya, marker: { color: c.accent, opacity: 0.75 }, name: 'this run', showlegend: legend, hovertemplate: '%{x:.2f}: %{y:.4f}<extra></extra>' });
      if (rv) { const t = refStep(rv, edges, c); t.xaxis = xa; t.yaxis = ya; t.showlegend = legend; out.push(t); }
    } else {
      const cdf = (arr) => { const s = arr.slice().sort((a, b) => a - b); const n = s.length; const step = Math.max(1, Math.floor(n / 1500)); const xs = [], ys = []; for (let i = 0; i < n; i += step) { xs.push(s[i]); ys.push(kind === 'cdf' ? (i + 1) / n : 1 - (i + 1) / n); } xs.push(s[n - 1]); ys.push(kind === 'cdf' ? 1 : 0); return { xs, ys }; };
      const a = cdf(v);
      out.push({ type: 'scatter', mode: 'lines', x: a.xs, y: a.ys, xaxis: xa, yaxis: ya, line: { color: c.accent, width: 2, shape: 'hv' }, name: 'this run', showlegend: legend });
      if (rv) { const b = cdf(rv); out.push({ type: 'scatter', mode: 'lines', x: b.xs, y: b.ys, xaxis: xa, yaxis: ya, line: { color: c.text, width: 1.3, dash: 'dash', shape: 'hv' }, name: `reference (${plain(state.ref.name)})`, showlegend: legend }); }
    }
    return out;
  }

  /* ---------------------------------------------------------------------
     Sensitivity
     --------------------------------------------------------------------- */
  function sensitivity(e) {
    const R = state.result;
    if (R.sens[e]) return R.sens[e];
    const { res, plan } = R;
    const n = res.inputs ? res.inputs.n : res.n;
    const S = res.S[e];
    const keep = [];
    for (let i = 0; i < n; i++) if (S[i] > 0) keep.push(i);
    const y = keep.map((i) => Math.log10(S[i]));
    const cols = [];
    const E = plan.elements[e];
    if (res.inputs) {
      res.inputs.index.forEach((p, j) => {
        const par = plan.params[p];
        if (par.group !== 'Major ions' && par.group !== E.el) return;
        const src = res.inputs.values[j];
        cols.push({ label: par.group === 'Major ions' ? `${par.id} (major)` : par.id, kind: 'constant', param: p, values: keep.map((i) => src[i]) });
      });
    }
    const ws = R.waters;
    const gwCols = [['pH', (w) => w.pH], ['log [HCO3-]', (w) => Math.log10(w.HCO3)], ['log [SO4]tot', (w) => Math.log10(w.SO4)], ['log [Cl]tot', (w) => Math.log10(w.Cl)], ['log [Ca]tot', (w) => Math.log10(w.Ca)], ['log [Na]tot', (w) => Math.log10(w.Na)], ['log [Si]tot', (w) => Math.log10(w.Si)], ['I', (w) => w.I]];
    if (R.options.version === 'A') gwCols.push(['Eh', (w) => w.Eh], ['log [Fe]tot', (w) => Math.log10(w.Fe)]);
    for (const [label, f] of gwCols) cols.push({ label, kind: 'water', values: keep.map((i) => f(ws[res.waterIndex[i]])) });
    const rhos = SFModel.spearman(cols.map((c) => c.values), y);
    const out = cols.map((c, k) => ({ label: c.label, kind: c.kind, param: c.param, rho: Number.isFinite(rhos[k]) ? rhos[k] : 0 }))
      .filter((c) => c.rho !== 0).sort((a, b) => Math.abs(b.rho) - Math.abs(a.rho));
    R.sens[e] = { rows: out, n: keep.length };
    return R.sens[e];
  }

  function renderSens() {
    const R = state.result;
    const plot = $('sfChartSens');
    const empty = $('sfSensEmpty');
    if (!R || !havePlotly()) { plot.hidden = true; empty.hidden = false; $('sfSensTable').innerHTML = ''; return; }
    const el = elementOptions('sfSensEl', state.sens.el, false);
    state.sens.el = el;
    $('sfSensTop').value = String(state.sens.top);
    const e = R.plan.elements.findIndex((E) => E.el === el);
    const s = sensitivity(e);
    empty.hidden = s.rows.length > 0;
    if (!s.rows.length) { plot.hidden = true; $('sfSensTable').innerHTML = ''; empty.textContent = 'Nothing varied in this run.'; return; }
    plot.hidden = false;
    const top = state.sens.top ? s.rows.slice(0, state.sens.top) : s.rows;
    const c = themeColors();
    const shown = top.slice().reverse();
    Plotly.react(plot, [{
      type: 'bar', orientation: 'h', y: shown.map((r) => plain(r.label)), x: shown.map((r) => r.rho),
      marker: { color: shown.map((r) => (r.kind === 'water' ? '#4e79a7' : c.accent)) },
      hovertemplate: '%{y}: ρ = %{x:.3f}<extra></extra>',
    }], baseLayout({ margin: { l: 170, r: 20, t: 10, b: 50 }, xaxis: { title: `Spearman ρ with log S, ${el}`, range: [-1, 1], gridcolor: c.grid, zeroline: true, zerolinecolor: c.muted }, yaxis: { automargin: true, gridcolor: c.grid }, showlegend: false }), PLOT_CONFIG);
    plot.style.height = `${Math.max(260, 26 * shown.length + 80)}px`;
    Plotly.Plots.resize(plot);
    const P = R.plan;
    $('sfSensTable').innerHTML = `<p class="sf-muted">Red: an equilibrium constant; blue: a property of the water drawn. Over ${s.n.toLocaleString('en')} realisations${R.res.inputs && R.res.inputs.n < R.res.n ? ` (the first ${R.res.inputs.n.toLocaleString('en')}, the sampled constants kept)` : ''}.</p>
      <table class="sf-table"><thead><tr><th class="text">Input</th><th>ρ</th><th>ρ²</th><th>log K°</th><th>ΔlogK</th></tr></thead><tbody>
      ${top.map((r) => `<tr><td class="text">${esc(r.label)}</td><td>${r.rho.toFixed(3)}</td><td>${(r.rho * r.rho).toFixed(3)}</td><td>${r.param != null ? fmt(P.params[r.param].logK, 5) : ''}</td><td>${r.param != null ? fmt(P.params[r.param].dlogK, 3) : ''}</td></tr>`).join('')}
      </tbody></table>`;
  }

  /* ---------------------------------------------------------------------
     Sweep
     --------------------------------------------------------------------- */
  function sweepVars() {
    const v = Object.entries(SFModel.SWEEP_VARS).filter(([k]) => state.options.version === 'A' || (k !== 'Eh' && k !== 'Fe'));
    return v;
  }

  function sweepRange(v, w) {
    const meta = SFModel.SWEEP_VARS[v];
    const x0 = meta.log ? Math.log10(w[v]) : w[v];
    if (v === 'pH') return [Math.max(4, x0 - 2.5), Math.min(13, x0 + 2.5)];
    if (v === 'I') return [0.001, 0.5];
    if (v === 'Eh') return [-500, 300];
    return [x0 - 2.5, x0 + 2.5];
  }

  function renderSweep() {
    compilePlan();
    const plot = $('sfChartSweep');
    const note = $('sfSweepNote');
    if (!havePlotly()) { note.textContent = 'The chart library (Plotly) did not load.'; return; }
    if (!state.plan || state.planError) { note.textContent = `The dataset has an error: ${state.planError}`; return; }
    const el = elementOptions('sfSweepEl', state.sweep.el, false);
    state.sweep.el = el;
    const vs = sweepVars();
    const vsel = $('sfSweepVar');
    vsel.innerHTML = vs.map(([k, m]) => `<option value="${k}">${esc(m.label)}</option>`).join('');
    if (!vs.some(([k]) => k === state.sweep.v)) state.sweep.v = 'pH';
    vsel.value = state.sweep.v;
    const w = currentWater();
    const [d0, d1] = sweepRange(state.sweep.v, w);
    const from = Number.isFinite(parseFloat(state.sweep.from)) ? parseFloat(state.sweep.from) : d0;
    const to = Number.isFinite(parseFloat(state.sweep.to)) ? parseFloat(state.sweep.to) : d1;
    $('sfSweepFrom').value = state.sweep.from; $('sfSweepFrom').placeholder = d0.toFixed(2);
    $('sfSweepTo').value = state.sweep.to; $('sfSweepTo').placeholder = d1.toFixed(2);
    const e = state.plan.elements.findIndex((E) => E.el === el);
    const E = state.plan.elements[e];
    const sw = SFModel.sweep(state.plan, w, e, state.sweep.v, from, to, 161);
    const off = unitOffset();
    const c = themeColors();
    const traces = E.solids.map((so, k) => ({ type: 'scatter', mode: 'lines', x: sw.x, y: sw.solids[k].map((y) => y + off), name: plain(so.id) + (so.use ? '' : ' (not in min)'), line: { color: PALETTE[k % PALETTE.length], width: 1.4, dash: so.use ? 'dash' : 'dot' } }));
    traces.push({ type: 'scatter', mode: 'lines', x: sw.x, y: sw.total.map((y) => y + off), name: 'solubility (the minimum)', line: { color: c.text, width: 3 } });
    const meta = SFModel.SWEEP_VARS[state.sweep.v];
    const x0 = meta.log ? Math.log10(w[state.sweep.v]) : w[state.sweep.v];
    const fin = sw.total.filter(Number.isFinite);
    const [flo, fhi] = extent(fin);
    // The solids that matter lie within a few log units of the minimum; the
    // rest (uranophane 40 units up) would squash the plot flat.
    const [, allHi] = extent(...sw.solids.map((a) => a.filter(Number.isFinite)));
    const yl = fin.length ? [flo + off - 1.5, Math.min(allHi, fhi + 10) + off + 0.5] : undefined;
    Plotly.react(plot, traces, baseLayout({
      xaxis: { title: meta.label, gridcolor: c.grid, zeroline: false },
      yaxis: { title: `log₁₀ S, ${el} (${unitLabel()})`, gridcolor: c.grid, zeroline: false, range: yl },
      shapes: [{ type: 'line', xref: 'x', yref: 'paper', x0, x1: x0, y0: 0, y1: 1, line: { color: c.muted, width: 1, dash: 'dot' } }],
    }), PLOT_CONFIG);
    note.textContent = `${E.name} against ${meta.label.replace(/^log /, 'log ')}, the rest of the water at the composition of the One water tab (${state.water.custom ? 'edited' : waterLabel(Math.max(0, state.water.row - 1))}), nominal constants, ${state.options.version === 'A' ? 'Version A' : 'Version B'}.`;
  }

  /* ---------------------------------------------------------------------
     Compare
     --------------------------------------------------------------------- */
  async function loadReference(file) {
    const size = typeof kvotFileTooLarge === 'function' ? kvotFileTooLarge(file, 512 * 1024 * 1024) : null;
    if (size && size.tooLarge) { setStatus(size.reason, 'error'); return; }
    setStatus(`Reading ${file.name}…`);
    try {
      state.ref = await SFIO.readReference(file);
      $('sfRefNote').textContent = `${state.ref.name}: ${state.ref.format}, ${state.ref.elements.length} elements, ${state.ref.data[state.ref.elements[0]].length.toLocaleString('en')} values each.`;
      setStatus(`${file.name}: reference loaded.`, 'ok');
      renderTab();
    } catch (e) {
      setStatus(`${file.name}: ${e.message}`, 'error');
    }
  }

  function renderCompare() {
    const host = $('sfCompareTable');
    const plot = $('sfChartCompare');
    const empty = $('sfCompareEmpty');
    $('sfRefUnits').value = state.refUnits;
    const R = state.result;
    if (!state.ref || !R) { host.innerHTML = ''; plot.hidden = true; empty.hidden = false; return; }
    empty.hidden = true;
    const off = unitOffset();
    const rows = [];
    const traces = [];
    const annotations = [];
    const c = themeColors();
    R.plan.elements.forEach((E, e) => {
      const ref = refValues(E.el);
      if (!ref) return;
      const a = SFModel.describe(R.res.S[e]);
      const b = SFModel.describe(ref);
      const ks = SFModel.ks2(logValues(R.res.S[e], 0), logValues(ref, 0));
      const d50 = a.p50 - b.p50, d95 = a.p95 - b.p95;
      rows.push(`<tr><td class="el">${esc(E.el)}</td><td>${fmtLog(a.p5 + off)}</td><td>${fmtLog(a.p50 + off)}</td><td>${fmtLog(a.p95 + off)}</td><td>${fmtLog(b.p5 + off)}</td><td>${fmtLog(b.p50 + off)}</td><td>${fmtLog(b.p95 + off)}</td>`
        + `<td class="${Math.abs(d50) > 0.5 ? 'flag' : ''}">${d50 >= 0 ? '+' : ''}${d50.toFixed(2)}</td><td class="${Math.abs(d95) > 0.5 ? 'flag' : ''}">${d95 >= 0 ? '+' : ''}${d95.toFixed(2)}</td>`
        + `<td>${ks.D.toFixed(4)}</td><td class="${ks.p < 0.05 ? 'flag' : ''}">${ks.p < 0.001 ? '<0.001' : ks.p.toFixed(3)}</td><td>${a.n.toLocaleString('en')} / ${b.n.toLocaleString('en')}</td></tr>`);
      const k = traces.length / 2;
      const ax = k === 0 ? '' : String(k + 1);
      traces.push(...distTraces(logValues(R.res.S[e], off), logValues(ref, off), 'cdf', `x${ax}`, `y${ax}`, c, k === 0));
      annotations.push({ text: `<b>${E.el}</b>`, xref: `x${ax} domain`, yref: `y${ax} domain`, x: 0.02, y: 0.98, showarrow: false, xanchor: 'left', yanchor: 'top', font: { size: 11 } });
    });
    host.innerHTML = rows.length ? `<table class="sf-table"><thead><tr><th class="text">El.</th><th>P5</th><th>P50</th><th>P95</th><th>ref P5</th><th>ref P50</th><th>ref P95</th><th>ΔP50</th><th>ΔP95</th><th>KS D</th><th>p</th><th>n / n ref</th></tr></thead><tbody>${rows.join('')}</tbody></table>
      <p class="sf-muted">log<sub>10</sub> ${unitLabel()}; Δ = this run − reference. Red: a difference above 0.5 log units, or p below 0.05.</p>` : '<p class="sf-empty">The reference has none of the elements of this run.</p>';
    if (!havePlotly() || !rows.length) { plot.hidden = true; return; }
    plot.hidden = false;
    const nPlots = traces.length / 2;
    const cols = 4, rowsN = Math.ceil(nPlots / cols);
    const layout = baseLayout({ grid: { rows: rowsN, columns: cols, pattern: 'independent', xgap: 0.08, ygap: 0.12 }, annotations, margin: { l: 40, r: 10, t: 10, b: 60 }, legend: { orientation: 'h', y: -0.04 } });
    for (let k = 0; k < nPlots; k++) { const ax = k === 0 ? '' : String(k + 1); layout[`xaxis${ax}`] = { gridcolor: c.grid, zeroline: false, tickfont: { size: 9 } }; layout[`yaxis${ax}`] = { gridcolor: c.grid, range: [0, 1], tickfont: { size: 9 } }; }
    plot.style.height = `${Math.max(300, 150 * rowsN + 60)}px`;
    Plotly.react(plot, traces, layout, PLOT_CONFIG);
  }

  /* ---------------------------------------------------------------------
     Data
     --------------------------------------------------------------------- */
  function dataGroups() {
    return [['major', 'Major ions (the water)'], ...state.data.elements.map((E) => [E.el, `${E.el} — ${E.name}`])];
  }

  function renderData() {
    const sel = $('sfDataEl');
    const groups = dataGroups();
    sel.innerHTML = groups.map(([k, l]) => `<option value="${esc(k)}">${esc(l)}</option>`).join('');
    if (!groups.some(([k]) => k === state.dataEl)) state.dataEl = 'U';
    sel.value = state.dataEl;
    const isMajor = state.dataEl === 'major';
    $('sfAddSpecies').hidden = isMajor;
    $('sfAddSolid').hidden = isMajor;
    compilePlan();
    const issues = state.plan ? state.plan.issues : [];
    const issueList = [];
    if (state.planError && !state.plan) issueList.push({ where: '', message: state.planError, severity: 'error' });
    issueList.push(...issues);
    $('sfDataIssues').innerHTML = issueList.length ? `<ul class="sf-issues">${issueList.map((i) => `<li class="${i.severity === 'error' ? '' : 'warn'}">${esc(i.where)}: ${esc(i.message)}</li>`).join('')}</ul>` : '';
    const opt = modelOptions();
    const row = (kind, s, i, master) => {
      let derived = '', ligs = '', flag = '', bal = '';
      try {
        const c = kind === 'solid' ? SFModel.compileSolid(s, master) : (kind === 'major' ? null : SFModel.compileSpecies(s, master));
        const rx = SFModel.parseReaction(s.rx);
        const b = SFModel.balanceIssues(rx);
        bal = b.length ? `<span class="flagged">${esc(b.join('; '))}</span>` : '✓';
        if (c) {
          const override = !opt.reactionTerms && (s.qSRSite || s.ligSRSite);
          derived = esc(SFModel.qText(c.q));
          let lig = c.lig;
          if (s.ligSRSite && !opt.reactionTerms) { lig = lig.slice(); for (const [k, v] of Object.entries(s.ligSRSite)) lig[SFModel.LIG[k]] = v; }
          ligs = esc(SFModel.ligandText(lig)) + (kind === 'solid' && c.m !== 1 ? ` <span class="sf-muted">(1/${c.m})</span>` : '') + (kind === 'species' && c.n > 1 ? ` <span class="sf-muted">(${c.n}-mer)</span>` : '');
          if (s.qSRSite && !opt.reactionTerms) { derived = `${esc(SFModel.qText(s.qSRSite))} <span class="flagged">SR-Site term</span><br><span class="sf-muted">reaction: ${esc(SFModel.qText(c.q))}</span>`; }
          if (s.ligSRSite && !opt.reactionTerms) ligs += ' <span class="flagged">SR-Site term</span>';
          void override;
        } else {
          const q = SFModel.activityTerm(rx, (f) => /\(s\)$/.test(f));
          derived = esc(SFModel.qText(s.qSRSite && !opt.reactionTerms ? s.qSRSite : q)) + (s.qSRSite && !opt.reactionTerms ? ' <span class="flagged">SR-Site term</span>' : '');
        }
      } catch (e) {
        flag = `<span class="flagged">${esc(e.message)}</span>`;
      }
      const orig = originalEntry(isMajor ? 'major' : state.dataEl, kind === 'solid' ? 'solid' : 'species', s.id);
      const ch = (f) => (!orig || (f === 'use' ? (orig.use !== false) !== (s.use !== false) : (orig[f] ?? 0) !== (s[f] ?? 0)) ? ' changed' : '');
      const attrs = `data-kind="${kind}" data-i="${i}"`;
      return `<tr><td class="kind">${kind === 'solid' ? 'solid' : kind === 'major' ? (s.fixed ? 'fixed' : '') : 'species'}</td>`
        + `<td class="text"><input type="text" class="name${ch('id')}" size="${Math.max(8, Math.min(28, s.id.length + 1))}" value="${esc(s.id)}" ${attrs} data-field="id" data-on-change="sf:dataEdit" aria-label="Name"${isMajor ? ' readonly' : ''}></td>`
        + `<td class="text"><input type="text" class="rx${ch('rx')}" size="${Math.max(24, Math.min(90, s.rx.length + 2))}" value="${esc(s.rx)}" ${attrs} data-field="rx" data-on-change="sf:dataEdit" aria-label="Reaction" spellcheck="false"></td>`
        + `<td><input type="text" class="num${ch('logK')}" value="${esc(numberText(s.logK))}" ${attrs} data-field="logK" data-on-change="sf:dataEdit" aria-label="log K"></td>`
        + `<td><input type="text" class="num${ch('dlogK')}" value="${esc(numberText(s.dlogK || 0))}" ${attrs} data-field="dlogK" data-on-change="sf:dataEdit" aria-label="Delta log K"${s.fixed ? ' disabled' : ''}></td>`
        + `<td class="derived text">${derived}${flag}</td><td class="derived text">${ligs}</td>`
        + `<td>${kind === 'solid' ? `<input type="checkbox" ${attrs} data-field="use" data-on-change="sf:dataEdit"${s.use !== false ? ' checked' : ''} aria-label="Used in the minimum">` : ''}</td>`
        + `<td class="derived text">${bal}</td>`
        + `<td>${isMajor ? '' : `<button type="button" class="del" ${attrs} data-on-click="sf:deleteRow" aria-label="Delete ${esc(s.id)}">×</button>`}</td></tr>`;
    };
    let body = '';
    if (isMajor) {
      body += state.data.major.map((s, i) => row('major', s, i, '')).join('');
    } else {
      const E = state.data.elements.find((x) => x.el === state.dataEl);
      body += `<tr class="group"><td colspan="10">Aqueous species of ${esc(E.name)}; master species <code>${esc(E.master)}</code></td></tr>`;
      body += E.species.map((s, i) => row('species', s, i, E.master)).join('');
      body += `<tr class="group"><td colspan="10">Candidate solids</td></tr>`;
      body += E.solids.map((s, i) => row('solid', s, i, E.master)).join('');
    }
    $('sfDataTable').innerHTML = `<table class="sf-table sf-data-table"><thead><tr><th class="text"></th><th class="text">Name</th><th class="text">Reaction</th><th>log K°</th><th>ΔlogK</th><th class="text">Activity term</th><th class="text">Depends on</th><th>Use</th><th class="text">Balance</th><th></th></tr></thead><tbody>${body}</tbody></table>
      <p class="sf-muted">q<sub>z</sub> = log γ of a species of charge z. The activity term is added to log K° to give the constant at the ionic strength of the water. “Depends on”: what the species concentration (per free master ion) or the free master ion (for a solid) is proportional to.</p>`;
    renderDataSummary();
  }

  function dataEdit(el) {
    const kind = el.dataset.kind;
    const i = Number(el.dataset.i);
    const f = el.dataset.field;
    let list;
    if (kind === 'major') list = state.data.major;
    else {
      const E = state.data.elements.find((x) => x.el === state.dataEl);
      list = kind === 'solid' ? E.solids : E.species;
    }
    const s = list[i];
    if (!s) return;
    if (f === 'use') s.use = el.checked;
    else if (f === 'logK' || f === 'dlogK') {
      const x = parseFloat(String(el.value).trim().replace(',', '.').replace('−', '-'));
      if (!Number.isFinite(x) || (f === 'dlogK' && x < 0)) { el.setCustomValidity(f === 'dlogK' ? 'A number, zero or more' : 'A number'); el.reportValidity(); return; }
      el.setCustomValidity('');
      s[f] = x;
    } else if (f === 'id') {
      const v = el.value.trim();
      if (!v) return;
      s.id = v;
    } else if (f === 'rx') s.rx = el.value.trim();
    afterDataChange(false);
    // Redrawn once the focus has moved on (a Tab fires the change first),
    // and the focus put back on the same field of the new table.
    setTimeout(() => {
      const a = document.activeElement;
      const key = a && a.closest && a.closest('#sfDataTable') && a.dataset.field ? [a.dataset.kind, a.dataset.i, a.dataset.field] : null;
      renderData();
      if (key) {
        const again = document.querySelector(`#sfDataTable [data-kind="${key[0]}"][data-i="${key[1]}"][data-field="${key[2]}"]`);
        if (again) again.focus();
      }
    }, 0);
  }

  function afterDataChange(render = true) {
    compilePlan();
    markStale('The thermodynamic data changed.');
    saveState();
    if (render) renderData(); else renderDataSummary();
    if (!state.result) setStatus(state.planError ? `The dataset has an error: ${state.planError}` : 'Data changed.', state.planError ? 'error' : '');
  }

  /* ---------------------------------------------------------------------
     Samples and export
     --------------------------------------------------------------------- */
  function renderSamples() {
    const R = state.result;
    const host = $('sfSamplesTable');
    const empty = $('sfSamplesEmpty');
    if (!R) { host.innerHTML = ''; empty.hidden = false; return; }
    empty.hidden = true;
    const { res, plan } = R;
    const scale = state.units === 'molm3' ? 1000 : 1;
    const n = Math.min(res.n, 200);
    const head = `<tr><th>#</th><th class="text">Water</th><th>pH</th>${plan.elements.map((E) => `<th>${esc(E.el)}</th>`).join('')}</tr>`;
    let body = '';
    for (let i = 0; i < n; i++) {
      const wi = res.waterIndex[i];
      body += `<tr><td>${i + 1}</td><td class="text">${esc(waterLabel(wi))}</td><td>${fmt(R.waters[wi].pH, 3)}</td>${plan.elements.map((E, e) => `<td>${fmt(res.S[e][i] * scale, 3)}</td>`).join('')}</tr>`;
    }
    host.innerHTML = `<table class="sf-table"><thead>${head}</thead><tbody>${body}</tbody></table>`;
    $('sfSamplesNote').textContent = `The first ${n} of ${res.n.toLocaleString('en')} realisations, S in ${unitLabel()}.`;
  }

  function samplesRows(withControl) {
    const R = state.result;
    const { res, plan } = R;
    const head = ['realisation', 'water_row', 'water_id', ...plan.elements.map((E) => `${E.el} (mol/kg)`)];
    if (withControl) head.push(...plan.elements.map((E) => `${E.el} solid`));
    const rows = [head];
    for (let i = 0; i < res.n; i++) {
      const wi = res.waterIndex[i];
      const r = [i + 1, wi + 1, R.waters[wi].id || ''];
      for (let e = 0; e < plan.elements.length; e++) r.push(res.S[e][i]);
      if (withControl) for (let e = 0; e < plan.elements.length; e++) { const c = res.control[e][i]; r.push(c < 255 ? plan.elements[e].solids[c].id : ''); }
      rows.push(r);
    }
    return rows;
  }

  function settingsRows() {
    const R = state.result;
    return [
      ['Setting', 'Value'],
      ['Page', `kvotab.se/SimpleFunctions.html, build ${BUILD}`],
      ['Written', new Date().toISOString()],
      ['Groundwater', R.tableName],
      ['Waters', R.waters.length],
      ['Version', R.options.version],
      ['Every term from the reactions', R.options.reactionTerms ? 'yes' : 'no'],
      ['Polynuclear by metal atoms', R.options.polyStoichiometry ? 'yes' : 'no'],
      ['Ra(OH)+ sampled once', R.options.singleRaOH ? 'yes' : 'no'],
      ['Eh factor (V)', R.options.ehFactor],
      ['Cm drawn with the Am numbers', R.options.analogueDraws ? 'yes' : 'no'],
      ['Realisations', R.res.n],
      ['Seed', R.cfg.seed],
      ['Latin hypercube', R.cfg.lhs ? 'yes' : 'no'],
      ['Groundwater draw', R.cfg.draw],
      ['Constants sampled', R.cfg.varyTD ? 'yes' : 'no'],
      ['Dataset', dataEdits().count ? `SR-Site with ${dataEdits().count} edited entries` : SFData.SRSITE.label],
    ];
  }

  function summaryRows() {
    const R = state.result;
    const rows = [['Element', 'min', 'P1', 'P5', 'P25', 'P50', 'P75', 'P95', 'P99', 'max', 'mean', 'sd', 'n', '(log10 mol/kg)']];
    R.stats.forEach((s) => { const d = s.d; rows.push([s.el, d.min, d.p1, d.p5, d.p25, d.p50, d.p75, d.p95, d.p99, d.max, d.mean, d.sd, d.n]); });
    return rows;
  }

  async function samplesExcel() {
    if (!state.result) return;
    if (typeof XlsxWriter === 'undefined' || typeof JSZip === 'undefined') { setStatus('The Excel writer did not load; the CSV button still works.', 'error'); return; }
    const x = new XlsxWriter('simplefunctions.xlsx');
    x.writeData(settingsRows(), 'Settings');
    x.writeData(summaryRows(), 'Percentiles');
    x.writeData(samplesRows(true), 'CSOL');
    await x.saveAs('simplefunctions.xlsx');
    setStatus('Excel workbook written.', 'ok');
  }

  function samplesMat() {
    const R = state.result;
    if (!R) return;
    const bytes = SFIO.writeMatStructArray('CSOL', R.plan.elements.map((E) => E.el), R.res.S, R.res.n);
    download('CSOL_simplefunctions.mat', new Blob([bytes], { type: 'application/octet-stream' }));
    setStatus('MATLAB file written: CSOL(1×N), one field per element, mol/kg.', 'ok');
  }

  function samplesJson() {
    const R = state.result;
    if (!R) return;
    const doc = {
      app: 'kvot-simplefunctions', kind: 'results', build: BUILD, settings: Object.fromEntries(settingsRows().slice(1)),
      units: 'mol/kg', n: R.res.n, waterRow: Array.from(R.res.waterIndex, (i) => i + 1),
      S: Object.fromEntries(R.plan.elements.map((E, e) => [E.el, Array.from(R.res.S[e])])),
      controllingSolid: Object.fromEntries(R.plan.elements.map((E, e) => [E.el, Array.from(R.res.control[e], (c) => (c < 255 ? E.solids[c].id : null))])),
    };
    download('simplefunctions_results.json', JSON.stringify(doc), 'application/json');
  }

  function inputsCsv() {
    const R = state.result;
    if (!R) return;
    if (!R.res.inputs || !R.res.inputs.index.length) { setStatus('No constants were sampled in this run.', 'warn'); return; }
    const inp = R.res.inputs;
    const rows = [['realisation', 'water_row', ...inp.index.map((p) => R.plan.params[p].key)]];
    for (let i = 0; i < inp.n; i++) rows.push([i + 1, R.res.waterIndex[i] + 1, ...inp.values.map((col) => col[i])]);
    download('simplefunctions_sampled_constants.csv', SFIO.toCsv(rows));
  }

  function dataCsv() {
    const rows = [['group', 'kind', 'name', 'reaction', 'logK', 'dlogK', 'use', 'qSRSite', 'ligSRSite']];
    for (const s of state.data.major) rows.push(['major ions', s.fixed ? 'fixed' : 'species', s.id, s.rx, s.logK, s.dlogK || 0, '', s.qSRSite ? s.qSRSite.join(' ') : '', '']);
    for (const E of state.data.elements) {
      for (const s of E.species) rows.push([E.el, 'species', s.id, s.rx, s.logK, s.dlogK || 0, '', s.qSRSite ? s.qSRSite.join(' ') : '', s.ligSRSite ? JSON.stringify(s.ligSRSite) : '']);
      for (const s of E.solids) rows.push([E.el, 'solid', s.id, s.rx, s.logK, s.dlogK || 0, s.use === false ? 'no' : 'yes', s.qSRSite ? s.qSRSite.join(' ') : '', s.ligSRSite ? JSON.stringify(s.ligSRSite) : '']);
    }
    download('simplefunctions_data.csv', SFIO.toCsv(rows));
  }

  function saveData() {
    download('simplefunctions_data.json', JSON.stringify({ app: 'kvot-simplefunctions', kind: 'data', saved: new Date().toISOString(), data: state.data }, null, 1), 'application/json');
  }

  function saveCase() {
    download('simplefunctions_case.json', JSON.stringify({
      app: 'kvot-simplefunctions', kind: 'case', version: 1, saved: new Date().toISOString(),
      options: state.options, run: state.run, units: state.units, addMg: state.addMg, example: state.example,
      groundwater: state.table ? state.table.name : null, data: dataEdits().count ? state.data : null,
    }, null, 1), 'application/json');
  }

  async function openJson(file) {
    let doc;
    try { doc = JSON.parse(await file.text()); } catch (e) { setStatus(`${file.name}: not JSON.`, 'error'); return; }
    if (!doc || doc.app !== 'kvot-simplefunctions') { setStatus(`${file.name}: not a file written by this page.`, 'error'); return; }
    if (doc.kind === 'results') { await loadReference(file); showTab('compare'); return; }
    if (doc.kind === 'data' || (doc.kind === 'case' && doc.data)) {
      const d = sanitizeData(doc.data);
      if (!d) { setStatus(`${file.name}: no usable dataset in it.`, 'error'); return; }
      state.data = d;
    }
    if (doc.kind === 'case') {
      const pick = (obj, def) => { const out = { ...def }; if (obj) for (const k of Object.keys(def)) if (typeof obj[k] === typeof def[k]) out[k] = obj[k]; return out; };
      state.options = pick(doc.options, DEFAULT_OPTIONS);
      state.run = pick(doc.run, DEFAULT_RUN);
      if (['molkg', 'molm3'].includes(doc.units)) state.units = doc.units;
      if (typeof doc.addMg === 'boolean') state.addMg = doc.addMg;
      if (doc.example && !state.table) loadExample(doc.example, true);
      writeOptionControls();
      writeRunControls();
    }
    compilePlan();
    markStale('A case or dataset was opened.');
    saveState();
    renderDataSummary();
    renderTab();
    let msg = `${file.name} applied.`;
    if (doc.kind === 'case' && doc.groundwater && (!state.table || state.table.name !== doc.groundwater)) msg += ` It was made with the groundwater “${doc.groundwater}”, which is not loaded.`;
    setStatus(msg, 'ok');
  }

  /* ---------------------------------------------------------------------
     Tabs, panel, drag handle, drops
     --------------------------------------------------------------------- */
  function showTab(name) {
    state.tab = name;
    document.querySelectorAll('.sf-tabs button').forEach((b) => b.classList.toggle('active', b.dataset.tab === name));
    document.querySelectorAll('.sf-pane').forEach((p) => { p.hidden = p.dataset.pane !== name; });
    saveState();
    renderTab();
  }

  function renderTab() {
    try {
      switch (state.tab) {
        case 'summary': renderSummary(); break;
        case 'water': renderWater(); break;
        case 'dist': renderDist(); break;
        case 'sens': renderSens(); break;
        case 'sweep': renderSweep(); break;
        case 'compare': renderCompare(); break;
        case 'data': renderData(); break;
        case 'samples': renderSamples(); break;
        default: break;
      }
    } catch (e) {
      if (typeof reportFailure === 'function') reportFailure(`sf:render:${state.tab}`, e);
      setStatus(`Drawing the ${state.tab} tab failed: ${e.message}`, 'error');
    }
    mountInfoButtons();
    requestAnimationFrame(resizePlots);
  }

  function initSideResize() {
    const handle = $('sfResize');
    const root = document.querySelector('.sf');
    if (state.sideWidth) root.style.setProperty('--sf-side-width', `${state.sideWidth}px`);
    let dragging = false;
    handle.addEventListener('pointerdown', (ev) => { dragging = true; handle.classList.add('active'); handle.setPointerCapture(ev.pointerId); });
    handle.addEventListener('pointermove', (ev) => {
      if (!dragging) return;
      const left = root.getBoundingClientRect().left;
      state.sideWidth = Math.round(Math.max(260, Math.min(640, ev.clientX - left)));
      root.style.setProperty('--sf-side-width', `${state.sideWidth}px`);
      resizePlots();
    });
    const end = () => { if (!dragging) return; dragging = false; handle.classList.remove('active'); saveState(); resizePlots(); };
    handle.addEventListener('pointerup', end);
    handle.addEventListener('pointercancel', end);
    handle.addEventListener('dblclick', () => { state.sideWidth = DEFAULT_WIDTH; root.style.setProperty('--sf-side-width', `${DEFAULT_WIDTH}px`); saveState(); resizePlots(); });
  }

  function initSections() {
    document.querySelectorAll('details.sf-sec').forEach((sec) => {
      if (Object.prototype.hasOwnProperty.call(state.sections, sec.id)) sec.open = !!state.sections[sec.id];
      sec.addEventListener('toggle', () => { state.sections[sec.id] = sec.open; saveState(); });
    });
  }

  async function routeFile(file) {
    const n = file.name || '';
    if (/\.json$/i.test(n)) return openJson(file);
    if (/\.(mat|h5|hdf5|hdf)$/i.test(n)) { await loadReference(file); if (state.tab !== 'dist') showTab('compare'); return undefined; }
    // A table: groundwater if it has the columns, otherwise perhaps a reference.
    try {
      const res = await SFIO.readGroundwater(file, { SFModel });
      setTable({ name: file.name, rawWaters: res.waters, headers: res.headers, sheet: res.sheet, skipped: res.skipped, source: 'file' });
      state.example = '';
      $('sfExample').value = '';
      saveState();
      setStatus(`${file.name}: ${res.waters.length.toLocaleString('en')} waters${res.sheet ? ` from sheet “${res.sheet}”` : ''}. Press Run.`, 'ok');
      renderTab();
    } catch (e) {
      try { await loadReference(file); showTab('compare'); } catch (e2) { setStatus(`${file.name}: ${e.message}`, 'error'); }
    }
    return undefined;
  }

  function initDrop() {
    const zone = $('sfDrop');
    const root = document.querySelector('.sf');
    let depth = 0;
    root.addEventListener('dragenter', (ev) => { ev.preventDefault(); depth++; zone.classList.add('over'); });
    root.addEventListener('dragover', (ev) => { ev.preventDefault(); });
    root.addEventListener('dragleave', () => { depth = Math.max(0, depth - 1); if (!depth) zone.classList.remove('over'); });
    root.addEventListener('drop', (ev) => {
      ev.preventDefault();
      depth = 0;
      zone.classList.remove('over');
      const files = ev.dataTransfer && ev.dataTransfer.files ? Array.from(ev.dataTransfer.files) : [];
      (async () => { for (const f of files) await routeFile(f); })();
    });
  }

  /* ---------------------------------------------------------------------
     Actions
     --------------------------------------------------------------------- */
  registerActions({
    'sf:tab': (ev, el) => showTab(el.dataset.tab),
    'sf:run': () => run(),
    'sf:cancel': () => cancelRun(),
    'sf:openWater': () => $('sfWaterFile').click(),
    'sf:waterChosen': (ev, el) => { const f = el.files && el.files[0]; el.value = ''; if (f) routeFile(f); },
    'sf:chooseExample': (ev, el) => { if (el.value) loadExample(el.value); },
    'sf:clearWater': () => { state.table = null; state.example = ''; $('sfExample').value = ''; renderTableInfo(); writeRunControls(); saveState(); markStale('The groundwater was removed.'); renderTab(); },
    'sf:addMgChanged': (ev, el) => { state.addMg = el.checked; saveState(); markStale('Mg is now ' + (el.checked ? 'added to' : 'kept apart from') + ' Ca.'); renderTab(); },
    'sf:optionChanged': (ev, el) => {
      const k = el.dataset.key;
      if (k === 'limit') {
        const x = parseFloat(String(el.value).replace(',', '.'));
        if (!(x > 0)) { el.setCustomValidity('A positive number'); el.reportValidity(); return; }
        el.setCustomValidity('');
        state.options.limit = x;
        saveState();
        renderTab();
        return;
      }
      if (k === 'version') state.options.version = el.value;
      else state.options[k] = el.checked;
      compilePlan();
      renderTableInfo();
      saveState();
      markStale('The settings changed.');
      renderTab();
    },
    'sf:runSettingChanged': (ev, el) => {
      const k = el.dataset.key;
      if (k === 'n') { const x = readInt(el, 1, MAX_N); if (x == null) return; state.run.n = x; }
      else if (k === 'seed') { const x = readInt(el, 0, 2 ** 31 - 1); if (x == null) return; state.run.seed = x; }
      else if (k === 'draw') state.run.draw = el.value;
      else if (k === 'fixedWater') state.run.fixedWater = Number(el.value) || 0;
      else state.run[k] = el.checked;
      $('sfFixedRow').hidden = state.run.draw !== 'fixed';
      saveState();
      markStale('The sampling changed.');
    },
    'sf:unitsChanged': (ev, el) => { state.units = el.value; saveState(); renderTab(); },
    'sf:resetData': () => { state.data = SFData.clone(SFData.SRSITE); afterDataChange(); renderTab(); setStatus('Thermodynamic data reset to the SR-Site dataset.', 'ok'); },
    'sf:saveData': () => saveData(),
    'sf:openData': () => $('sfDataFile').click(),
    'sf:dataChosen': (ev, el) => { const f = el.files && el.files[0]; el.value = ''; if (f) openJson(f); },
    'sf:saveCase': () => saveCase(),
    'sf:openCase': () => $('sfCaseFile').click(),
    'sf:caseChosen': (ev, el) => { const f = el.files && el.files[0]; el.value = ''; if (f) openJson(f); },
    'sf:summaryRow': (ev, el) => { state.dist.el = el.dataset.el; showTab('dist'); },
    'sf:split': () => splitVariability(),
    'sf:waterPicked': (ev, el) => { const n = waters().length; const x = Math.round(Number(el.value)); if (!(x >= 1 && x <= n)) { el.setCustomValidity(`1 to ${n}`); el.reportValidity(); return; } el.setCustomValidity(''); state.water.row = x; state.water.edits = {}; saveState(); renderTab(); },
    'sf:waterCustomChanged': (ev, el) => { state.water.custom = el.checked; if (!el.checked) state.water.edits = {}; saveState(); renderTab(); },
    'sf:waterFieldChanged': (ev, el) => {
      const x = parseFloat(String(el.value).trim().replace(',', '.').replace('−', '-'));
      if (!Number.isFinite(x)) { el.setCustomValidity('A number'); el.reportValidity(); return; }
      el.setCustomValidity('');
      state.water.edits[el.dataset.key] = x;
      saveState();
      renderTab();
    },
    'sf:waterEl': (ev, el) => { state.waterEl = el.dataset.el; saveState(); document.querySelectorAll('#sfWaterOut tr.clickable').forEach((tr) => tr.classList.toggle('selected', tr.dataset.el === state.waterEl)); renderWaterDetail(); },
    'sf:waterCsv': () => waterCsv(),
    'sf:distChanged': (ev, el) => {
      if (el.id === 'sfDistEl') state.dist.el = el.value;
      if (el.id === 'sfDistKind') state.dist.kind = el.value;
      if (el.id === 'sfDistPhase') state.dist.phase = el.checked;
      if (el.id === 'sfDistFit') state.dist.fit = el.checked;
      if (el.id === 'sfDistRef') state.dist.ref = el.checked;
      saveState();
      renderDist();
    },
    'sf:sensChanged': (ev, el) => { if (el.id === 'sfSensEl') state.sens.el = el.value; if (el.id === 'sfSensTop') state.sens.top = Number(el.value); saveState(); renderSens(); },
    'sf:sweepChanged': (ev, el) => {
      if (el.id === 'sfSweepEl') state.sweep.el = el.value;
      if (el.id === 'sfSweepFrom') state.sweep.from = el.value.trim();
      if (el.id === 'sfSweepTo') state.sweep.to = el.value.trim();
      saveState();
      renderSweep();
    },
    'sf:sweepVarChanged': (ev, el) => { state.sweep.v = el.value; state.sweep.from = ''; state.sweep.to = ''; saveState(); renderSweep(); },
    'sf:openRef': () => $('sfRefFile').click(),
    'sf:refChosen': (ev, el) => { const f = el.files && el.files[0]; el.value = ''; if (f) loadReference(f); },
    'sf:clearRef': () => { state.ref = null; $('sfRefNote').textContent = ''; renderTab(); },
    'sf:compareChanged': (ev, el) => { state.refUnits = el.value; saveState(); renderTab(); },
    'sf:dataElChanged': (ev, el) => { state.dataEl = el.value; saveState(); renderData(); },
    'sf:dataEdit': (ev, el) => dataEdit(el),
    'sf:addRow': (ev, el) => {
      const E = state.data.elements.find((x) => x.el === state.dataEl);
      if (!E) return;
      if (el.dataset.kind === 'solid') E.solids.push({ id: `new solid ${E.solids.length + 1}`, rx: `X(s) + 2 H+ = ${E.master} + H2O`, logK: 0, dlogK: 0 });
      else E.species.push({ id: `new species ${E.species.length + 1}`, rx: `${E.master} + H2O = X + H+`, logK: 0, dlogK: 0 });
      afterDataChange();
      setStatus('A row was added: write its reaction and constant (it shows an error until then).', 'warn');
    },
    'sf:deleteRow': (ev, el) => {
      const E = state.data.elements.find((x) => x.el === state.dataEl);
      if (!E) return;
      const list = el.dataset.kind === 'solid' ? E.solids : E.species;
      list.splice(Number(el.dataset.i), 1);
      afterDataChange();
    },
    'sf:resetElement': () => {
      if (state.dataEl === 'major') state.data.major = SFData.clone(SFData.SRSITE).major;
      else {
        const i = state.data.elements.findIndex((x) => x.el === state.dataEl);
        const orig = SFData.clone(SFData.SRSITE).elements.find((x) => x.el === state.dataEl);
        if (i >= 0 && orig) state.data.elements[i] = orig;
      }
      afterDataChange();
    },
    'sf:dataCsv': () => dataCsv(),
    'sf:samplesCsv': () => { if (state.result) download('simplefunctions_csol.csv', SFIO.toCsv(samplesRows(true))); },
    'sf:samplesExcel': () => samplesExcel(),
    'sf:samplesMat': () => samplesMat(),
    'sf:samplesJson': () => samplesJson(),
    'sf:inputsCsv': () => inputsCsv(),
  });

  /* ---------------------------------------------------------------------
     Boot
     --------------------------------------------------------------------- */
  const hadState = loadState();
  compilePlan();
  writeOptionControls();
  writeRunControls();
  renderTableInfo();
  renderDataSummary();
  initSideResize();
  initSections();
  initDrop();
  mountInfoButtons();
  $('sfBuild').textContent = `Build ${BUILD}. The calculation runs in your browser; nothing is sent anywhere.`;
  document.addEventListener('keydown', (ev) => { if (ev.key === 'Escape' && info.key && !ev.defaultPrevented) { const at = document.activeElement; if (!at || at === document.body || info.panel?.contains(at) || at.closest?.('[data-info]')) closeInfo(); } });
  window.addEventListener('resize', () => { resizePlots(); placeInfo(); });
  document.documentElement.addEventListener('kvot-theme-change', () => renderTab());
  showTab(['summary', 'water', 'dist', 'sens', 'sweep', 'compare', 'data', 'samples', 'help'].includes(state.tab) ? state.tab : 'summary');
  // A first visit gets the TR-10-61 waters and a run, so there is something to see.
  if (state.example) loadExample(state.example, true);
  else if (!hadState) loadExample('tr1061range', true);
  if (state.table && !state.result) run();
  else setStatus('Load a groundwater table, or choose a built-in example.');

  window.SFPage = Object.freeze({
    getState: () => state,
    run,
    loadExample,
    showTab,
    fmt,
  });
}());
