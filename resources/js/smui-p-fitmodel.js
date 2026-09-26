/* ==========================================================================
   SMUI.HTML: ANALYZE > FIT MODEL

   JMP's Fit Model. The launch dialog builds the model from effects
   (Construct Model Effects: Add, Cross, Nest, the Macros, the Random Effect
   attribute, No Intercept) and a personality fits it:

     Standard Least Squares    report tables, leverage plots, least squares
                               means, row diagnostics, profilers, Box-Cox
     Stepwise                  forward, backward and mixed steps by p-value,
                               AICc or BIC; Make Model
     Generalized Linear Model  statsmodels' GLM (normal, binomial, Poisson,
                               gamma, inverse Gaussian, negative binomial)
     Nominal, Ordinal Logistic MNLogit (or a binomial GLM) and OrderedModel
     Mixed Model               MixedLM by REML, variance components
     MANOVA                    statsmodels' MANOVA
     Generalized Regression    lasso, elastic net and ridge paths

   The statistics are resources/py/smui/fit_model.py (fitmodel.*); this file
   draws the dialog and the reports. Every red-triangle choice is an option
   of the report (ctx.set), scoped by the response column where it belongs
   to one response, so Redo and saved projects keep it.
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM;
  const { el, fmt, qnorm } = SM.util;

  const PERS = [['standard', 'Standard Least Squares'], ['stepwise', 'Stepwise'], ['glm', 'Generalized Linear Model'],
    ['nominal', 'Nominal Logistic'], ['ordinal', 'Ordinal Logistic'], ['mixed', 'Mixed Model'], ['manova', 'MANOVA'],
    ['genreg', 'Generalized Regression']];
  const PERS_LABEL = Object.fromEntries(PERS);
  const EMPH = [['leverage', 'Effect Leverage'], ['screening', 'Effect Screening'], ['minimal', 'Minimal Report']];
  const DISTS = [['normal', 'Normal'], ['binomial', 'Binomial'], ['poisson', 'Poisson'], ['gamma', 'Gamma'], ['invgauss', 'Inverse Gaussian'], ['negbin', 'Negative Binomial']];
  const GR_DISTS = [['normal', 'Normal'], ['binomial', 'Binomial'], ['poisson', 'Poisson']];
  const LINKS = [['identity', 'Identity'], ['logit', 'Logit'], ['probit', 'Probit'], ['log', 'Log'], ['reciprocal', 'Reciprocal'], ['cloglog', 'Comp LogLog'], ['inverse_squared', 'Inverse Square'], ['sqrt', 'Square Root']];
  const DEFAULT_LINK = { normal: 'identity', binomial: 'logit', poisson: 'log', gamma: 'log', invgauss: 'log', negbin: 'log' };
  const MACROS = [['full', 'Full Factorial'], ['degree', 'Factorial to Degree'], ['sorted', 'Factorial Sorted'], ['rs', 'Response Surface'], ['poly', 'Polynomial to Degree']];

  /* ---- effects ---------------------------------------------------------------
     An effect is { cols: [Column], nest: [Column], random }: a crossing of its
     columns (a column twice is a power), nested in the nest columns. The spec
     keeps ids and names, so a renamed column and a loaded project both find
     their columns again. */
  const labelOf = (names, nest) => `${names.join('*')}${nest && nest.length ? `[${nest.join(',')}]` : ''}`;
  const effectLabel = (e) => labelOf(e.cols.map((c) => c.name), (e.nest || []).map((c) => c.name));
  const effectKey = (e) => `${e.cols.map((c) => c.id).sort().join('|')}#${(e.nest || []).map((c) => c.id).sort().join('|')}`;
  const serialize = (e) => ({ cols: e.cols.map((c) => c.id), names: e.cols.map((c) => c.name), nest: (e.nest || []).map((c) => c.id), nestNames: (e.nest || []).map((c) => c.name), random: !!e.random });

  function findCol(t, id, name) {
    const byId = t.columns.find((c) => c.id === id) || null;
    if (byId && (!name || byId.name === name)) return byId;
    const byName = name ? t.columns.find((c) => c.name === name) : null;
    return byName || byId;
  }

  function effectsFrom(list, t, byName = false) {
    const out = [];
    for (const e of list || []) {
      const names = e.names || [];
      const nestNames = e.nestNames || [];
      const cols = (e.cols || names).map((id, i) => (byName ? t.col(names[i] || id) : findCol(t, id, names[i])));
      const nest = (e.nest || nestNames).map((id, i) => (byName ? t.col(nestNames[i] || id) : findCol(t, id, nestNames[i])));
      if (cols.length && cols.every(Boolean) && nest.every(Boolean)) out.push({ cols, nest, random: !!e.random });
    }
    return out;
  }

  /* The macros of JMP's dialog, over the selected columns. */
  function combos(k, n) {
    const out = [];
    const rec = (start, acc) => { if (acc.length === k) { out.push(acc.slice()); return; } for (let i = start; i < n; i++) { acc.push(i); rec(i + 1, acc); acc.pop(); } };
    rec(0, []);
    return out;
  }
  function multisets(k, n) {
    const out = [];
    const rec = (start, acc) => { if (acc.length === k) { out.push(acc.slice()); return; } for (let i = start; i < n; i++) { acc.push(i); rec(i, acc); acc.pop(); } };
    rec(0, []);
    return out;
  }
  function macro(kind, cols, degree) {
    const n = cols.length;
    const pick = (idx) => ({ cols: idx.map((i) => cols[i]), nest: [], random: false });
    if (kind === 'full') {           // A, B, A*B, C, A*C, B*C, A*B*C: JMP's order
      const out = [];
      for (let i = 0; i < n; i++) { const cur = out.slice(); out.push([i]); for (const e of cur) out.push([...e, i]); }
      return out.map(pick);
    }
    if (kind === 'sorted' || kind === 'degree') {
      const top = kind === 'sorted' ? n : Math.min(n, Math.max(1, degree));
      const out = [];
      for (let k = 1; k <= top; k++) out.push(...combos(k, n));
      return out.map(pick);
    }
    if (kind === 'rs') {             // main effects, then the crossings and the squares of the continuous
      const out = cols.map((_, i) => [i]);
      for (let i = 0; i < n; i++) for (let j = i; j < n; j++) if (i !== j || !cols[i].isCategorical) out.push([i, j]);
      return out.map(pick);
    }
    if (kind === 'poly') {           // every monomial up to the degree
      const out = [];
      for (let k = 1; k <= Math.max(1, degree); k++) for (const m of multisets(k, n)) if (m.every((i) => !cols[i].isCategorical || m.filter((x) => x === i).length === 1)) out.push(m);
      return out.map(pick);
    }
    return [];
  }

  /* ---- the launch dialog's Construct Model Effects part ----------------------- */
  function constructEffects(api, spec) {
    const t = api.table;
    let effects = spec ? effectsFrom(spec.effects, t) : [];
    const sel = new Set();
    const o0 = (spec && spec.options) || {};
    const st = {
      pers: o0.personality || null, userPers: !!o0.personality, emphasis: o0.emphasis || 'leverage', dist: o0.dist || 'normal',
      link: o0.link || '', noIntercept: !!o0.noIntercept, target: o0.target ?? '', distr: o0.distr || 'logit',
    };
    const msg = (s) => api.message(s);
    const list = el('ul', { class: 'sm-role-list sm-fm-effects', role: 'listbox', 'aria-label': 'Model effects', 'aria-multiselectable': 'true', tabindex: '0', dataset: { hint: 'Select columns, then Add, Cross, Nest or a macro' } });
    const renderList = () => {
      list.replaceChildren();
      list.classList.toggle('is-empty', !effects.length);
      effects.forEach((e, i) => {
        const li = el('li', { role: 'option', dataset: { i: String(i) }, 'aria-selected': String(sel.has(i)) },
          el('span', { class: 'sm-colname', text: effectLabel(e) + (e.random ? '&Random' : '') }));
        if (sel.has(i)) li.classList.add('is-selected');
        list.append(li);
      });
    };
    list.addEventListener('click', (ev) => {
      const li = ev.target.closest('li');
      if (!li) return;
      const i = +li.dataset.i;
      if (ev.metaKey || ev.ctrlKey || ev.shiftKey) { if (sel.has(i)) sel.delete(i); else sel.add(i); } else { const had = sel.has(i) && sel.size === 1; sel.clear(); if (!had) sel.add(i); }
      renderList();
    });
    list.addEventListener('dblclick', (ev) => { const li = ev.target.closest('li'); if (!li) return; effects.splice(+li.dataset.i, 1); sel.clear(); renderList(); });
    list.addEventListener('keydown', (ev) => { if ((ev.key === 'Delete' || ev.key === 'Backspace') && sel.size) { ev.preventDefault(); removeSel(); } });
    const add = (list2) => {
      let n = 0;
      for (const e of list2) if (!effects.some((x) => effectKey(x) === effectKey(e))) { effects.push(e); n++; }
      if (!n && list2.length) msg('Those effects are in the model already.');
      sel.clear();
      renderList();
    };
    const picked = () => { const c = api.selectedColumns(); if (!c.length) msg('Select columns in the list on the left first.'); return c; };
    const btn = (label, fn, extra = {}) => { const b = el('button', { type: 'button', class: 'sm-btn', text: label, ...extra }); b.addEventListener('click', fn); return b; };
    const removeSel = () => { effects = effects.filter((_, i) => !sel.has(i)); sel.clear(); renderList(); };
    const degree = el('input', { type: 'text', inputmode: 'numeric', size: 2, value: '2', 'aria-label': 'Degree' });
    const deg = () => Math.max(1, Math.min(6, Math.round(Number(degree.value) || 2)));
    const bAdd = btn('Add', () => { msg(''); add(picked().map((c) => ({ cols: [c], nest: [], random: false }))); });
    const bCross = btn('Cross', () => {
      msg('');
      const c = api.selectedColumns();
      const es = effects.filter((_, i) => sel.has(i));
      if (es.length && c.length) add(es.flatMap((e) => c.map((x) => ({ cols: [...e.cols, x], nest: e.nest.slice(), random: e.random }))));
      else if (c.length > 1) add([{ cols: c, nest: [], random: false }]);
      else if (es.length > 1) add([{ cols: es.flatMap((e) => e.cols), nest: [], random: false }]);
      else msg('Cross: select two or more columns, or columns and effects of the model.');
    });
    const bNest = btn('Nest', () => {
      msg('');
      const c = api.selectedColumns();
      const idx = [...sel];
      if (!c.length || !idx.length) { msg('Nest: select the effect to nest in the model list, and the column to nest it in on the left.'); return; }
      for (const i of idx) { const e = effects[i]; for (const x of c) if (!e.cols.includes(x) && !e.nest.includes(x)) e.nest.push(x); }
      // a nested effect that is now the same as another one of the model goes
      const seen = new Set();
      effects = effects.filter((e) => { const k = effectKey(e); if (seen.has(k)) return false; seen.add(k); return true; });
      sel.clear();
      renderList();
    });
    const bMacros = btn('Macros ▾', () => SM.ui.menu(MACROS.map(([k, label]) => ({ label, action: () => { msg(''); const c = picked(); if (c.length) add(macro(k, c, deg())); } })), bMacros, { returnFocus: bMacros }), { 'aria-haspopup': 'menu' });
    const bAttr = btn('Attributes ▾', () => SM.ui.menu([{ label: 'Random Effect', checked: [...sel].length > 0 && [...sel].every((i) => effects[i].random), action: () => {
      if (!sel.size) { msg('Select effects in the model list first.'); return; }
      const on = ![...sel].every((i) => effects[i].random);
      for (const i of sel) effects[i].random = on;
      renderList();
    } }], bAttr, { returnFocus: bAttr }), { 'aria-haspopup': 'menu' });
    const bRemove = btn('Remove', () => { if (!sel.size) { msg('Select effects in the model list to remove.'); return; } removeSel(); });
    const noInt = el('input', { type: 'checkbox' });
    noInt.checked = st.noIntercept;
    noInt.addEventListener('change', () => { st.noIntercept = noInt.checked; });

    // personality and its options
    const mkSel = (choices, value, label) => { const s = el('select', { 'aria-label': label }, ...choices.map(([v, l]) => el('option', { value: v, text: l }))); s.value = value; return s; };
    const pers = mkSel(PERS, st.pers || 'standard', 'Personality');
    const emph = mkSel(EMPH, st.emphasis, 'Emphasis');
    const dist = mkSel(DISTS, st.dist, 'Distribution');
    const link = mkSel(LINKS, st.link || DEFAULT_LINK[st.dist], 'Link Function');
    const distr = mkSel([['logit', 'Logit'], ['probit', 'Probit']], st.distr, 'Link');
    const target = el('select', { 'aria-label': 'Target Level' });
    const lab = (text, input, cls = '') => el('label', { class: `sm-fm-opt ${cls}` }, el('span', { text }), input);
    const lEmph = lab('Emphasis', emph), lDist = lab('Distribution', dist), lLink = lab('Link Function', link), lDistr = lab('Link', distr), lTarget = lab('Target Level', target);
    const yCols = () => (api.state.y || []).map((id) => t.col(id)).filter(Boolean);
    const defaultPers = () => { const y = yCols()[0]; return !y ? 'standard' : y.modelingType === 'nominal' ? 'nominal' : y.modelingType === 'ordinal' ? 'ordinal' : 'standard'; };
    const fillTarget = () => {
      const y = yCols()[0];
      const lv = y && y.isCategorical ? t.levels(y) : [];
      const was = target.value || String(st.target ?? '');
      target.replaceChildren(el('option', { value: '', text: lv.length ? `${SM.grid.cellText(y, lv[0])} (first level)` : '(first level)' }), ...lv.map((v) => el('option', { value: String(v), text: SM.grid.cellText(y, v) })));
      target.value = lv.some((v) => String(v) === was) ? was : '';
    };
    let dlgEl = null;
    const sync = () => {
      if (!st.userPers) pers.value = defaultPers();
      const p = pers.value;
      const y = yCols()[0];
      lEmph.hidden = p !== 'standard';
      lDist.hidden = !(p === 'glm' || p === 'genreg');
      const gd = p === 'genreg' ? GR_DISTS : DISTS;
      if ([...dist.options].map((x) => x.value).join() !== gd.map((x) => x[0]).join()) { const v = dist.value; dist.replaceChildren(...gd.map(([v2, l]) => el('option', { value: v2, text: l }))); dist.value = gd.some((x) => x[0] === v) ? v : 'normal'; }
      lLink.hidden = p !== 'glm';
      lDistr.hidden = p !== 'ordinal';
      lTarget.hidden = !(y && y.isCategorical && ['nominal', 'glm', 'genreg'].includes(p));
      fillTarget();
      if (dlgEl) {
        const off = [...dlgEl.querySelectorAll('.sm-role')].find((r) => r.querySelector('.sm-btn') && r.querySelector('.sm-btn').textContent === 'Offset');
        if (off) off.hidden = p !== 'glm';
      }
    };
    pers.addEventListener('change', () => { st.userPers = true; sync(); });
    dist.addEventListener('change', () => { link.value = DEFAULT_LINK[dist.value] || 'identity'; });
    requestAnimationFrame(() => {
      dlgEl = rootEl.closest('.sm-dialog');
      if (!dlgEl) return;
      const roles = dlgEl.querySelector('.sm-roles');
      if (roles && typeof MutationObserver !== 'undefined') new MutationObserver(() => sync()).observe(roles, { childList: true, subtree: true });
      sync();
    });

    const tools = el('div', { class: 'sm-fm-tools' }, bAdd, bCross, bNest, bMacros, el('label', { class: 'sm-fm-degree' }, 'Degree', degree), bAttr, bRemove,
      el('label', { class: 'sm-fm-noint' }, noInt, 'No Intercept'));
    const rootEl = el('div', { class: 'sm-fm-construct' },
      el('div', { class: 'sm-fm-pers' }, lab('Personality', pers), lEmph, lDist, lLink, lDistr, lTarget, typeof KvotInfo !== 'undefined' ? KvotInfo.slot('p:fitmodel:personality') : null),
      el('h4', null, 'Construct Model Effects', typeof KvotInfo !== 'undefined' ? KvotInfo.slot('p:fitmodel:effects') : null),
      el('div', { class: 'sm-fm-effbox' }, tools, list));
    renderList();
    sync();
    return {
      el: rootEl,
      read() {
        const p = pers.value;
        return {
          effects: effects.map(serialize),
          options: { personality: p, emphasis: emph.value, dist: dist.value, link: p === 'glm' ? link.value : null, noIntercept: noInt.checked, target: target.value === '' ? null : target.value, distr: distr.value },
        };
      },
      recall(saved) {
        const x = (saved && saved.extra) || {};
        effects = effectsFrom(x.effects, t, true);
        const o = saved.options || {};
        if (o.personality) { pers.value = o.personality; st.userPers = true; }
        if (o.emphasis) emph.value = o.emphasis;
        if (o.dist) dist.value = o.dist;
        if (o.link) link.value = o.link;
        if (o.distr) distr.value = o.distr;
        noInt.checked = !!o.noIntercept;
        st.target = o.target ?? '';
        sel.clear();
        renderList();
        sync();
        target.value = st.target == null ? '' : String(st.target);
      },
    };
  }

  function validate(spec, table) {
    const o = spec.options || {};
    const p = o.personality || 'standard';
    const ys = (spec.roles.y || []).map((id) => table.col(id)).filter(Boolean);
    const effects = spec.effects || [];
    const yIds = new Set(spec.roles.y || []);
    if (effects.some((e) => [...(e.cols || []), ...(e.nest || [])].some((id) => yIds.has(id)))) return 'A Y column is also in a model effect: take it out of the effects.';
    const cont = ys.every((c) => !c.isCategorical);
    if (['standard', 'stepwise', 'mixed', 'manova'].includes(p) && !cont) return `${PERS_LABEL[p]} needs continuous Y columns: change the personality, or the modeling type of ${ys.find((c) => c.isCategorical).name}.`;
    if (p === 'manova' && ys.length < 2) return 'MANOVA needs two or more Y columns.';
    if ((p === 'nominal' || p === 'ordinal') && ys.some((c) => !c.isCategorical)) return `${PERS_LABEL[p]} needs a nominal or ordinal Y.`;
    if (p === 'glm' && o.dist !== 'binomial' && ys.some((c) => c.isCategorical)) return 'A categorical Y takes the binomial distribution (or Nominal Logistic).';
    if (p === 'mixed' && !effects.some((e) => e.random)) return 'The mixed model needs a random effect: select an effect and choose Attributes > Random Effect.';
    if ((p === 'stepwise' || p === 'genreg') && !effects.some((e) => !e.random)) return `${PERS_LABEL[p]} needs model effects.`;
    if ((p === 'stepwise' || p === 'genreg' || p === 'manova') && effects.some((e) => e.random)) return `${PERS_LABEL[p]} takes fixed effects only.`;
    const w = ((spec.roles.weight || []).length || (spec.roles.freq || []).length);
    if ((p === 'mixed' || p === 'manova') && w) return `${PERS_LABEL[p]}: statsmodels takes no weights here; remove Weight and Freq.`;
    return null;
  }

  /* ---- the model of a report --------------------------------------------------- */
  function modelOf(ctx) {
    const t = ctx.table;
    const effects = (ctx.spec.effects || []).map((e) => {
      const cols = (e.cols || []).map((id, i) => findCol(t, id, (e.names || [])[i]));
      const nest = (e.nest || []).map((id, i) => findCol(t, id, (e.nestNames || [])[i]));
      if (cols.some((c) => !c) || nest.some((c) => !c)) throw new Error(`the effect ${labelOf(e.names || [], e.nestNames || [])} uses a column that is no longer in the table: relaunch the analysis (Model Dialog)`);
      return { cols, nest, random: !!e.random };
    });
    const base = {
      effects: effects.map((e) => ({ names: e.cols.map((c) => c.name), nest: e.nest.map((c) => c.name), random: e.random })),
      weight: ctx.name('weight'), freq: ctx.name('freq'), no_intercept: !!ctx.opt('noIntercept', false),
    };
    const byName = new Map(t.columns.map((c) => [c.name, c]));
    return { effects, base, byName };
  }

  /* ---- small parts ----------------------------------------------------------------- */
  function pal() {
    const c = SM.util.themeColors();
    return { point: SM.report.BASE, fit: c.dark ? '#ff7a6b' : '#c0392b', mean: c.dark ? '#8fb6e0' : '#2f6690', muted: c.muted, text: c.text, grid: c.grid, dark: c.dark };
  }
  // A plot's width: as asked, but inside the window with room for the outlines' indentation.
  const W = (w) => Math.max(260, Math.min(w, (root.innerWidth || 1200) - 110));
  function extent(...arrs) {
    let lo = Infinity, hi = -Infinity;
    for (const a of arrs) if (a) for (const v of a) if (v != null && Number.isFinite(v)) { if (v < lo) lo = v; if (v > hi) hi = v; }
    if (!(lo <= hi)) return [0, 1];
    if (lo === hi) return [lo - 0.5, hi + 0.5];
    return [lo, hi];
  }
  const pText = (p) => (p == null || !Number.isFinite(p) ? '=.' : p < 0.0001 ? '<.0001' : `=${p.toFixed(4)}`);
  const levelText = (ctx, M, name, v) => { const c = M.byName.get(name); return c ? SM.grid.cellText(c, v) : String(v); };
  const lineTrace = (x, y, color, dash = 'solid', width = 1.3) => ({ type: 'scatter', mode: 'lines', x, y, line: { color, dash, width }, hoverinfo: 'skip', showlegend: false });

  /* A scatter of rows (linked to the table) with reference lines. */
  function rowPlot(ctx, { x, y, rows, xTitle, yTitle, lines = [], hlines = [], width = 380, height = 300, title }) {
    const P = pal();
    const traces = [{ type: x.length > 4000 ? 'scattergl' : 'scatter', mode: 'markers', x, y, rows, marker: { size: x.length > 500 ? 4 : 6 }, name: 'Rows' }, ...lines];
    const shapes = hlines.map((h) => ({ type: 'line', xref: 'paper', x0: 0, x1: 1, yref: 'y', y0: h.y, y1: h.y, line: { color: h.color || P.muted, width: h.width || 1, dash: h.dash || 'solid' } }));
    return ctx.plot(traces, { xaxis: { title: { text: xTitle } }, yaxis: { title: { text: yTitle } }, shapes, margin: { l: 58, r: 12, t: 8, b: 46 } }, { width: W(width), height, title });
  }

  /* Report notes from Python, and the code. */
  function tail(ctx, parent, res) {
    for (const n of res.notes || []) parent.add(ctx.note(n));
    parent.add(ctx.code(res.code));
  }

  /* One section per response: with one Y the report's top outline is the
     response's (its red triangle is the platform's), with several each gets
     an outline of its own. */
  async function perResponse(ctx, ys, titleOf, fn, groupMenu) {
    const multi = ys.length > 1;
    for (const y of ys) {
      const st = { menu: () => [] };
      const parent = multi ? ctx.outline(titleOf(y), { menu: () => st.menu(), key: `resp:${y.id}` }) : ctx.top;
      await fn(y, parent, st);
      if (!multi) ctx.fm.menu = () => st.menu();
    }
    if (multi) ctx.fm.menu = groupMenu || (() => [{ label: 'Model Dialog', action: () => ctx.report.relaunch() }]);
  }

  /* ---- Effect Summary: LogWorth bars, Remove, Undo, FDR -------------------------------- */
  function effectSummary(ctx, parent, rows, { scope, editable = true }) {
    const fdr = ctx.opt('fdr', false, scope);
    const ob = ctx.outline('Effect Summary', { parent, key: 'effectsummary', info: 'p:fitmodel:summary' });
    const lk = fdr ? 'fdr_logworth' : 'logworth', pk = fdr ? 'fdr_p' : 'p';
    const max = Math.max(2.5, ...rows.map((r) => r[lk] || 0));
    let chosen = null;
    const tbl = el('table', { class: 'sm-rt sm-fm-esum' });
    tbl.append(el('thead', null, el('tr', null, el('th', { class: 'sm-l', text: 'Source' }), el('th', { text: fdr ? 'FDR LogWorth' : 'LogWorth' }), el('th', { class: 'sm-fm-barhead', 'aria-hidden': 'true' }), el('th', { text: fdr ? 'FDR PValue' : 'PValue' }))));
    const body = el('tbody');
    for (const r of rows) {
      const v = r[lk] || 0;
      const bar = el('td', { class: 'sm-fm-barcell' }, el('span', { class: 'sm-fm-bar', style: { width: `${(100 * v) / max}%` } }), el('span', { class: 'sm-fm-ref', style: { left: `${(100 * 2) / max}%` } }));
      const p = r[pk];
      const tdP = el('td', { text: SM.util.fmtP(p, ctx.alpha) });
      if (p != null && p < ctx.alpha) tdP.classList.add('p-sig');
      const tr = el('tr', null, el('td', { class: 'sm-l', text: r.source }), el('td', { text: fmt(v, { digits: 3 }) }), bar, tdP);
      if (editable) {
        tr.style.cursor = 'pointer';
        tr.addEventListener('click', () => { chosen = chosen === r.source ? null : r.source; body.querySelectorAll('tr').forEach((x) => x.classList.toggle('is-selected', x === tr && chosen != null)); });
      }
      body.append(tr);
    }
    tbl.append(body);
    ob.add(tbl);
    if (editable) {
      const b = (label, fn, dis = false) => { const x = el('button', { type: 'button', class: 'sm-btn small', text: label, disabled: dis }); x.addEventListener('click', fn); return x; };
      const undo = ctx.spec.effectsUndo || [];
      const box = el('div', { class: 'sm-fm-esum-btns' },
        b('Remove', () => { if (!chosen) { SM.ui.toast('Click an effect in the Effect Summary first'); return; } removeEffect(ctx, chosen); }),
        b('Edit', () => ctx.report.relaunch()),
        b('Undo', () => { const prev = (ctx.spec.effectsUndo || []).pop(); if (prev) { ctx.spec.effects = prev; ctx.report.app.retitle(ctx.report); ctx.report.run(); } }, !undo.length),
        el('label', { class: 'sm-fm-opt' }, (() => { const c = el('input', { type: 'checkbox' }); c.checked = fdr; c.addEventListener('change', () => ctx.set('fdr', c.checked, scope)); return c; })(), 'FDR'));
      ob.add(box, ctx.note('LogWorth is −log₁₀(p) of the effect test; the line marks p = 0.01. Click an effect and Remove to refit without it.'));
    }
    return ob;
  }

  function removeEffect(ctx, label) {
    const t = ctx.table;
    const effects = effectsFrom(ctx.spec.effects, t);
    const keep = effects.filter((e) => effectLabel(e) !== label);
    if (keep.length === effects.length) return;
    ctx.spec.effectsUndo = [...(ctx.spec.effectsUndo || []), ctx.spec.effects].slice(-20);
    ctx.spec.effects = keep.map(serialize);
    ctx.report.run();
  }

  /* ---- the plots of a least squares fit ----------------------------------------------------- */
  function actualByPredicted(ctx, parent, d, whole, yname, info = 'p:fitmodel:leverage', title = 'Actual by Predicted Plot') {
    const P = pal();
    const ob = ctx.outline(title, { parent, key: 'actpred', info });
    const [lo, hi] = extent(d.predicted, d.actual);
    const lines = [lineTrace([lo, hi], [lo, hi], P.fit, 'solid', 1.4)];
    if (whole && whole.mean != null) lines.push(lineTrace([lo, hi], [whole.mean, whole.mean], P.mean, 'dot', 1.2));
    if (whole && whole.curve) lines.push(lineTrace(whole.curve.x, whole.curve.lower, P.fit, 'dash', 1), lineTrace(whole.curve.x, whole.curve.upper, P.fit, 'dash', 1));
    const sub = whole ? ` P${pText(whole.p)} RSq=${whole.rsq != null ? whole.rsq.toFixed(2) : '.'} RMSE=${fmt(whole.rmse, { sig: 5 })}` : '';
    ob.add(rowPlot(ctx, { x: d.predicted, y: d.actual, rows: d.rows, xTitle: `${yname} Predicted${sub}`, yTitle: `${yname} Actual`, lines, width: 400, height: 320, title: `${yname} actual by predicted` }));
    return ob;
  }

  /* JMP's Regression Plot: with one continuous factor (and at most one
     categorical one) the data and the fitted curve, one per level, with the
     confidence band of the mean. The curves are the profiler's traces. */
  async function regressionPlot(ctx, parent, { kind, payload, factors, d, yname, scope }) {
    const P = pal();
    const cont = factors.filter((f) => f.type === 'continuous');
    const cats = factors.filter((f) => f.type === 'categorical');
    if (cont.length !== 1 || cats.length > 1) return null;
    const f = cont[0], g = cats[0] || null;
    const fi = factors.indexOf(f);
    const levels = g ? g.levels : [null];
    const outs = await Promise.all(levels.map((lv) => ctx.call('fitmodel.profile', { ...payload, kind, current: g ? { [g.name]: lv } : {}, alpha: ctx.alpha, grid: 81 })));
    const traces = [];
    const xcol = ctx.table.col(f.name), gcol = g ? ctx.table.col(g.name) : null;
    const color = (i) => (g ? SM.util.PALETTE[i % SM.util.PALETTE.length] : P.point);
    const lvIndex = new Map(levels.map((lv, i) => [String(lv), i]));
    traces.push({ type: d.rows.length > 4000 ? 'scattergl' : 'scatter', mode: 'markers', x: d.rows.map((r) => xcol.values[r]), y: d.actual, rows: d.rows, name: 'Rows', showlegend: false,
      marker: { size: d.rows.length > 500 ? 4 : 6, color: g ? d.rows.map((r) => color(lvIndex.get(String(gcol.values[r])) ?? 0)) : P.point } });
    outs.forEach((o, i) => {
      const tr = o.responses[0].traces[fi];
      const c = color(i);
      if (tr.lower && !g) traces.push(lineTrace(tr.x, tr.lower, P.fit, 'dot', 1), lineTrace(tr.x, tr.upper, P.fit, 'dot', 1));
      traces.push({ type: 'scatter', mode: 'lines', x: tr.x, y: tr.pred, line: { color: g ? c : P.fit, width: 1.8 }, name: g ? g.labels[i] : 'Fit', hoverinfo: 'skip', showlegend: !!g });
    });
    const ob = ctx.outline('Regression Plot', { parent, key: 'regplot', menu: () => [{ label: 'Remove', action: () => ctx.set('plotRegression', false, scope) }] });
    ob.add(ctx.plot(traces, { showlegend: !!g, legend: g ? { title: { text: g.name } } : undefined, xaxis: { title: { text: f.name } }, yaxis: { title: { text: yname } }, margin: { l: 58, r: 12, t: 8, b: 44 } },
      { width: W(g ? 440 : 400), height: 320, title: `${yname} regression plot` }));
    return ob;
  }

  function leveragePlot(ctx, lev, yname) {
    const P = pal();
    const lines = [lineTrace(lev.line.x, lev.line.y, P.fit, 'solid', 1.4), lineTrace(lev.line.x, [lev.mean, lev.mean], P.mean, 'dot', 1.2)];
    if (lev.curve) lines.push(lineTrace(lev.curve.x, lev.curve.lower, P.fit, 'dash', 1), lineTrace(lev.curve.x, lev.curve.upper, P.fit, 'dash', 1));
    return rowPlot(ctx, { x: lev.x, y: lev.y, rows: lev.rows, xTitle: `${lev.effect} Leverage, P${pText(lev.p)}`, yTitle: `${yname} Leverage Residuals`, lines, width: 340, height: 290, title: `${lev.effect} leverage plot` });
  }

  function residualPlots(ctx, parent, d, yname, o, emph, lim) {
    const P = pal();
    if (o('plotResidPred', emph !== 'minimal')) {
      ctx.outline('Residual by Predicted Plot', { parent, key: 'residpred' }).add(rowPlot(ctx, { x: d.predicted, y: d.residual, rows: d.rows, xTitle: `${yname} Predicted`, yTitle: `${yname} Residual`, hlines: [{ y: 0, color: P.mean }], title: `${yname} residual by predicted` }));
    }
    if (o('plotResidRow', false)) {
      ctx.outline('Residual by Row Plot', { parent, key: 'residrow' }).add(rowPlot(ctx, { x: d.rows.map((r) => r + 1), y: d.residual, rows: d.rows, xTitle: 'Row Number', yTitle: `${yname} Residual`, hlines: [{ y: 0, color: P.mean }], width: 460, title: `${yname} residual by row` }));
    }
    if (o('plotStudent', false) && d.externally) {
      const hl = [{ y: 0, color: P.mean }];
      if (lim && lim.individual) hl.push({ y: lim.individual, color: P.muted, dash: 'dash' }, { y: -lim.individual, color: P.muted, dash: 'dash' });
      if (lim && lim.bonferroni) hl.push({ y: lim.bonferroni, color: P.fit }, { y: -lim.bonferroni, color: P.fit });
      const ob = ctx.outline('Studentized Residuals', { parent, key: 'student' });
      ob.add(rowPlot(ctx, { x: d.rows.map((r) => r + 1), y: d.externally, rows: d.rows, xTitle: 'Row Number', yTitle: 'Externally Studentized Residuals', hlines: hl, width: 460, title: `${yname} studentized residuals` }),
        ctx.note(`Each residual divided by its standard error with the row left out. Dashed: the 95% individual limits (±${fmt(lim.individual, { sig: 4 })}); solid: Bonferroni over the rows (±${fmt(lim.bonferroni, { sig: 4 })}).`));
    }
    if (o('plotResidQQ', false)) {
      const n = d.residual.length;
      const order = d.residual.map((_, k) => k).sort((a, b) => d.residual[a] - d.residual[b]);
      const rk = SM.util.ranks(d.residual);
      const z = order.map((k) => qnorm(rk[k] / (n + 1)));
      const yv = order.map((k) => d.residual[k]);
      const m = yv.reduce((a, b) => a + b, 0) / n;
      const sd = Math.sqrt(yv.reduce((a, b) => a + (b - m) ** 2, 0) / Math.max(1, n - 1));
      const [zl, zh] = extent(z);
      ctx.outline('Residual Normal Quantile Plot', { parent, key: 'residqq' }).add(rowPlot(ctx, { x: z, y: yv, rows: order.map((k) => d.rows[k]), xTitle: 'Normal Quantile', yTitle: `${yname} Residual`, lines: [lineTrace([zl, zh], [m + sd * zl, m + sd * zh], P.fit)], width: 360, title: `${yname} residual normal quantile plot` }));
    }
  }

  /* ---- least squares means ----------------------------------------------------------------- */
  function lsmeansTable(ctx, M, lsm) {
    const cols = lsm.factors.length > 1 ? lsm.factors.map((f, i) => ({ key: `f${i}`, label: f, fmt: 'text' })) : [{ key: 'f0', label: 'Level', fmt: 'text' }];
    const rows = lsm.labels.map((_, k) => {
      const r = { lsmean: lsm.lsmean[k], se: lsm.se[k], mean: lsm.mean[k] };
      lsm.levels[k].forEach((v, i) => { r[`f${i}`] = levelText(ctx, M, lsm.factors[i], v); });
      return r;
    });
    return ctx.rt({ columns: [...cols, { key: 'lsmean', label: 'Least Sq Mean' }, { key: 'se', label: 'Std Error' }, { key: 'mean', label: 'Mean' }], rows }, { caption: 'Least Squares Means Table', key: 'lsmeans' });
  }

  function lsmeansPlot(ctx, M, lsm, tcrit, yname, label) {
    const P = pal();
    const traces = [];
    if (lsm.factors.length === 2) {
      const xs = [...new Set(lsm.levels.map((l) => levelText(ctx, M, lsm.factors[0], l[0])))];
      const groups = [...new Set(lsm.levels.map((l) => levelText(ctx, M, lsm.factors[1], l[1])))];
      groups.forEach((g, gi) => {
        const idx = lsm.levels.map((l, k) => [l, k]).filter(([l]) => levelText(ctx, M, lsm.factors[1], l[1]) === g).map(([, k]) => k);
        traces.push({ type: 'scatter', mode: 'lines+markers', x: idx.map((k) => levelText(ctx, M, lsm.factors[0], lsm.levels[k][0])), y: idx.map((k) => lsm.lsmean[k]), name: g,
          line: { color: SM.util.PALETTE[gi % SM.util.PALETTE.length], width: 1.6 }, marker: { size: 7, color: SM.util.PALETTE[gi % SM.util.PALETTE.length] },
          error_y: { type: 'data', array: idx.map((k) => tcrit * lsm.se[k]), visible: true, thickness: 1, width: 4 } });
      });
      return ctx.plot(traces, { showlegend: true, legend: { title: { text: lsm.factors[1] } }, xaxis: { type: 'category', categoryorder: 'array', categoryarray: xs, title: { text: lsm.factors[0] } }, yaxis: { title: { text: `${yname} LS Means` } } }, { width: W(420), height: 290, title: `${label} LS means plot` });
    }
    traces.push({ type: 'scatter', mode: 'lines+markers', x: lsm.labels, y: lsm.lsmean, line: { color: P.point, width: 1.4 }, marker: { size: 8, color: P.point },
      error_y: { type: 'data', array: lsm.se.map((s) => tcrit * s), visible: true, thickness: 1.2, width: 5, color: P.point }, hovertemplate: '%{x}: %{y:.5g}<extra></extra>' });
    return ctx.plot(traces, { xaxis: { type: 'category', title: { text: label } }, yaxis: { title: { text: `${yname} LS Means` } } }, { width: W(360), height: 280, title: `${label} LS means plot` });
  }

  async function comparisons(ctx, M, parent, payload, label, method, scope) {
    const r = await ctx.call('fitmodel.compare', { ...payload, effect: label, method, alpha: ctx.alpha });
    const title = method === 'tukey' ? 'LSMeans Differences Tukey HSD' : 'LSMeans Differences Student\'s t';
    const ob = ctx.outline(title, { parent, key: `cmp:${method}:${label}`, info: 'p:fitmodel:lsmeans', menu: () => [{ label: 'Remove', action: () => ctx.set(`${method}:${label}`, false, scope) }] });
    if (r.error) { ob.add(ctx.warn(r.error)); return; }
    ob.add(ctx.kv([['α', r.alpha], [method === 'tukey' ? 'Q' : 't', r.critical]]));
    const lets = ctx.outline('Connecting Letters Report', { parent: ob, key: `letters:${method}:${label}` });
    lets.add(ctx.rt({ columns: [{ key: 'level', label: 'Level', fmt: 'text' }, { key: 'letters', label: '', fmt: 'text' }, { key: 'lsmean', label: 'Least Sq Mean' }, { key: 'se', label: 'Std Error' }], rows: r.letters }, { sortable: false, key: 'letters' }),
      ctx.note('Levels not connected by the same letter are significantly different.'));
    const od = ctx.outline('Ordered Differences Report', { parent: ob, key: `ordered:${method}:${label}` });
    od.add(ctx.rt({ columns: [{ key: 'level', label: 'Level', fmt: 'text' }, { key: 'minus', label: '- Level', fmt: 'text' }, { key: 'diff', label: 'Difference' }, { key: 'se', label: 'Std Err Dif' }, { key: 'lower', label: 'Lower CL' }, { key: 'upper', label: 'Upper CL' }, { key: 'p', label: 'p-Value', fmt: 'p' }], rows: r.ordered }, { key: 'ordered' }));
    ob.add(ctx.code(r.code));
  }

  async function contrastDialog(ctx, M, lsm, label, scope) {
    const key = `contrast:${label}`;
    const v = await SM.ui.form({
      title: `LSMeans Contrast: ${label}`, lead: 'A weight for each level; the weights of a contrast usually sum to zero (for example 1, −1, 0 compares the first two levels). Each contrast is added to the report; the joint test covers all of them.',
      fields: lsm.labels.map((l, i) => ({ key: `c${i}`, label: l, type: 'number', value: i === 0 ? 1 : i === 1 ? -1 : 0 })),
    });
    if (!v) return;
    const coefs = lsm.labels.map((_, i) => v[`c${i}`] || 0);
    if (coefs.every((c) => c === 0)) { SM.ui.toast('Give at least one nonzero weight'); return; }
    ctx.set(key, [...(ctx.opt(key, [], scope) || []), coefs], scope);
  }

  async function contrasts(ctx, parent, payload, label, list, scope) {
    const r = await ctx.call('fitmodel.contrast', { ...payload, effect: label, coefs: list, alpha: ctx.alpha });
    const ob = ctx.outline('Contrast', { parent, key: `contrast:${label}`, menu: () => [{ label: 'Remove Contrasts', action: () => ctx.set(`contrast:${label}`, [], scope) }] });
    if (r.error) { ob.add(ctx.warn(r.error)); return; }
    const cols = [{ key: 'contrast', label: 'Contrast', fmt: 'int' }, ...r.labels.map((l, i) => ({ key: `w${i}`, label: l })), { key: 'estimate', label: 'Estimate' }, { key: 'se', label: 'Std Error' }, { key: 't', label: 't Ratio' }, { key: 'p', label: 'Prob>|t|', fmt: 'p' }, { key: 'ss', label: 'SS' }];
    ob.add(ctx.rt({ columns: cols, rows: r.rows.map((x, i) => ({ ...x, ...Object.fromEntries(r.coefs[i].map((w, j) => [`w${j}`, w])) })) }, { sortable: false, key: 'contrast' }));
    if (r.joint) ob.add(ctx.rt({ columns: [{ key: 'ss', label: 'Sum of Squares' }, { key: 'numdf', label: 'Num DF', fmt: 'int' }, { key: 'dendf', label: 'Den DF' }, { key: 'f', label: 'F Ratio' }, { key: 'p', label: 'Prob > F', fmt: 'p' }], rows: [r.joint] }, { caption: 'Joint test of the contrasts', sortable: false, key: 'contrastjoint' }));
  }

  /* ---- the Prediction Profiler -------------------------------------------------------------------
     One small plot per factor and response: the prediction as the factor
     varies with the others at their current values, the confidence band
     dashed, the current value a red dashed line to drag (or click the plot,
     or type in the box below it). The profile is recomputed from the
     remembered fit; the current values are an option of the report. */
  async function profiler(ctx, parent, { sources, scope, title = 'Prediction Profiler', key = 'profiler', option = 'profiler' }) {
    const P = pal();
    // the current values, per By group; the group profiler (several responses) keeps its own
    const stateKey = `${option === 'profiler' ? 'prof' : option}:${ctx.byLabel || ''}`;
    let current = { ...(ctx.opt(stateKey, null, scope) || {}) };
    const ob = ctx.outline(title, { parent, key, info: 'p:fitmodel:profiler', menu: () => [
      { label: 'Reset Factor Settings', action: () => ctx.set(stateKey, null, scope) },
      { label: 'Remove', action: () => ctx.set(option, false, scope) },
    ] });
    const load = async () => {
      const outs = await Promise.all(sources.map((s) => ctx.call('fitmodel.profile', { ...s.payload, kind: s.kind, current, alpha: ctx.alpha })));
      return { factors: outs[0].factors, responses: outs.flatMap((x) => x.responses) };
    };
    let res = await load();
    const F = res.factors;
    if (!F.length) { ob.add(ctx.note('The model has no factors to profile.')); return ob; }
    const nf = F.length;
    const avail = Math.max(320, Math.min(1180, (root.innerWidth || 1200) - 150));
    const pw = Math.max(118, Math.min(215, Math.floor((avail - 130) / nf)));
    const ph = res.responses.length > 2 ? 140 : 175;
    const grid = el('div', { class: 'sm-fm-prof', style: { gridTemplateColumns: `minmax(92px, max-content) repeat(${nf}, max-content)` } });
    const yr = res.responses.map((r) => {
      if (r.bounded) return [0, 1];
      const [lo, hi] = extent(...r.traces.flatMap((t) => [t.pred, t.lower, t.upper]));
      const pad = 0.06 * (hi - lo);
      return [lo - pad, hi + pad];
    });
    const labelOfLevel = (f, v) => { const i = f.levels.findIndex((x) => x === v || String(x) === String(v)); return i >= 0 ? f.labels[i] : String(v); };
    const traces = (ri, fi) => {
      const r = res.responses[ri], tr = r.traces[fi], f = res.factors[fi];
      const cat = f.type === 'categorical';
      const out = [];
      if (tr.lower && tr.upper) {
        for (const b of [tr.upper, tr.lower]) out.push({ type: 'scatter', mode: cat ? 'markers' : 'lines', x: tr.x, y: b, line: { color: P.fit, width: 1, dash: 'dot' }, marker: { symbol: 'line-ew-open', size: 11, color: P.fit, line: { width: 1.2, color: P.fit } }, hoverinfo: 'skip', showlegend: false });
      }
      out.push({ type: 'scatter', mode: cat ? 'lines+markers' : 'lines', x: tr.x, y: tr.pred, line: { color: P.point, width: 1.8 }, marker: { size: 6, color: P.point }, hovertemplate: `${f.name} %{x}<br>${r.name} %{y:.5g}<extra></extra>`, showlegend: false });
      out.push(lineTrace([tr.x[0], tr.x[tr.x.length - 1]], [r.current.pred, r.current.pred], P.fit, 'dash', 1));
      return out;
    };
    const layout = (ri, fi) => {
      const f = res.factors[fi];
      const cat = f.type === 'categorical';
      const cur = cat ? labelOfLevel(f, f.current) : f.current;
      return {
        margin: { l: fi === 0 ? 48 : 6, r: 6, t: 6, b: 24 }, hovermode: 'x', dragmode: false,
        xaxis: cat ? { type: 'category', tickfont: { size: 9 }, fixedrange: true, showgrid: false } : { range: [f.min, f.max], tickfont: { size: 9 }, fixedrange: true, showgrid: false, nticks: 4 },
        yaxis: { range: yr[ri], showticklabels: fi === 0, tickfont: { size: 9 }, fixedrange: true, nticks: 5 },
        shapes: [{ type: 'line', xref: 'x', yref: 'paper', x0: cur, x1: cur, y0: 0, y1: 1, line: { color: P.fit, width: 1.4, dash: 'dash' } }],
      };
    };
    const cells = res.responses.map(() => []);
    const vals = [];
    let busy = false, pending = null;
    const setFactor = async (fi, x) => {
      const f = res.factors[fi];
      let v;
      if (f.type === 'categorical') {
        let i = typeof x === 'number' ? Math.round(x) : f.labels.indexOf(String(x));
        i = Math.max(0, Math.min(f.levels.length - 1, i < 0 ? 0 : i));
        v = f.levels[i];
      } else {
        v = Number(x);
        if (!Number.isFinite(v)) return;
        v = Math.max(f.min, Math.min(f.max, v));
      }
      current = { ...current, [f.name]: v };
      if (busy) { pending = true; return; }
      busy = true;
      try {
        do {
          pending = false;
          ctx.set(stateKey, current, scope, { rerun: false });
          res = await load();
          redraw();
        } while (pending);
      } catch (e) { SM.ui.toast(e.message || String(e), { error: true }); } finally { busy = false; }
    };
    const wire = (fi) => (gd) => {
      gd.on('plotly_relayout', (ev) => { const k = ev && Object.keys(ev).find((q) => /^shapes\[0\]\.x0$/.test(q)); if (k) setFactor(fi, ev[k]); });
      gd.on('plotly_click', (ev) => { const pt = ev && ev.points && ev.points[0]; if (pt) setFactor(fi, pt.x); });
    };
    const valueBox = (ri) => {
      const r = res.responses[ri];
      const c = r.current;
      return [el('span', { class: 'sm-fm-prof-name', text: r.name }), el('span', { class: 'sm-fm-prof-val', text: fmt(c.pred, { sig: 6 }) }),
        c.lower != null ? el('span', { class: 'sm-fm-prof-ci', text: `[${fmt(c.lower, { sig: 5 })}, ${fmt(c.upper, { sig: 5 })}]` }) : null];
    };
    res.responses.forEach((r, ri) => {
      const lab = el('div', { class: 'sm-fm-prof-y' }, ...valueBox(ri));
      vals.push(lab);
      grid.append(lab);
      F.forEach((f, fi) => {
        const box = ctx.plot(traces(ri, fi), layout(ri, fi), { width: pw + (fi === 0 ? 42 : 0), height: ph, select: false, title: `${r.name} profile over ${f.name}`, config: { edits: { shapePosition: true }, displayModeBar: false }, onDraw: wire(fi) });
        cells[ri].push(box);
        grid.append(box);
      });
    });
    grid.append(el('div', { class: 'sm-fm-prof-y sm-fm-prof-corner', text: 'Factors' }));
    const inputs = F.map((f, fi) => {
      let input;
      if (f.type === 'categorical') {
        input = el('select', { 'aria-label': `${f.name} current value` }, ...f.labels.map((l, i) => el('option', { value: String(i), text: l })));
        input.value = String(Math.max(0, f.levels.findIndex((x) => x === f.current)));
        input.addEventListener('change', () => setFactor(fi, Number(input.value)));
      } else {
        input = el('input', { type: 'text', inputmode: 'decimal', size: 8, 'aria-label': `${f.name} current value` });
        input.value = fmt(f.current, { sig: 6 }).replace('−', '-');
        const apply = () => setFactor(fi, SM.table.toNumber(input.value.replace(',', '.')));
        input.addEventListener('change', apply);
        input.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') { ev.preventDefault(); apply(); } });
      }
      const slider = f.type === 'continuous' ? el('input', { type: 'range', min: String(f.min), max: String(f.max), step: String((f.max - f.min) / 200 || 1), value: String(f.current), 'aria-label': `${f.name} slider` }) : null;
      if (slider) slider.addEventListener('change', () => setFactor(fi, Number(slider.value)));
      grid.append(el('div', { class: 'sm-fm-prof-x', style: { width: `${pw + (fi === 0 ? 42 : 0)}px` } }, el('span', { class: 'sm-fm-prof-fname', text: f.name }), input, slider));
      return { input, slider };
    });
    const redraw = () => {
      res.responses.forEach((r, ri) => {
        vals[ri].replaceChildren(...valueBox(ri).filter(Boolean));
        res.factors.forEach((f, fi) => {
          const box = cells[ri][fi];
          const p = box._plot;
          const tr = traces(ri, fi), lay = layout(ri, fi);
          if (p && p.drawn) Plotly.react(box, tr, SM.report.merge(box.layout, { shapes: lay.shapes, yaxis: { range: lay.yaxis.range } }));
          else if (p) { p.traces = tr; p.userLayout = lay; }
        });
      });
      res.factors.forEach((f, fi) => {
        const { input, slider } = inputs[fi];
        if (f.type === 'categorical') input.value = String(Math.max(0, f.levels.findIndex((x) => x === f.current)));
        else { if (document.activeElement !== input) input.value = fmt(f.current, { sig: 6 }).replace('−', '-'); if (slider) slider.value = String(f.current); }
      });
    };
    ob.add(el('div', { class: 'sm-fm-profwrap' }, grid), ctx.note('Drag the red dashed line of a factor, click in its plot, or type its value. Dotted: the confidence interval of the prediction.'));
    return ob;
  }

  /* ---- the Contour Profiler --------------------------------------------------------------------- */
  async function contourProfiler(ctx, parent, { kind, payload, factors, scope }) {
    const cont = factors.filter((f) => f.type === 'continuous');
    const ob = ctx.outline('Contour Profiler', { parent, key: 'contour', info: 'p:fitmodel:profiler', menu: () => [{ label: 'Remove', action: () => ctx.set('contour', false, scope) }] });
    if (cont.length < 2) { ob.add(ctx.note('The Contour Profiler needs two continuous factors.')); return; }
    const key = `contourState:${ctx.byLabel || ''}`;
    const st = { x: cont[0].name, y: cont[1].name, response: 0, current: {}, ...(ctx.opt(key, null, scope) || {}) };
    if (!cont.some((f) => f.name === st.x)) st.x = cont[0].name;
    if (!cont.some((f) => f.name === st.y) || st.y === st.x) st.y = cont.find((f) => f.name !== st.x).name;
    const r = await ctx.call('fitmodel.contour', { ...payload, kind, xfactor: st.x, yfactor: st.y, current: st.current, response: st.response, alpha: ctx.alpha });
    if (r.error) { ob.add(ctx.warn(r.error)); return; }
    const setSt = (patch) => ctx.set(key, { ...st, ...patch }, scope);
    const mkSel = (label, value, choices, fn) => { const s = el('select', { 'aria-label': label }, ...choices.map(([v, l]) => el('option', { value: v, text: l }))); s.value = value; s.addEventListener('change', () => fn(s.value)); return el('label', { class: 'sm-fm-opt' }, el('span', { text: label }), s); };
    const controls = el('div', { class: 'sm-fm-controls' },
      mkSel('Horizontal', st.x, cont.map((f) => [f.name, f.name]), (v) => setSt({ x: v, y: v === st.y ? st.x : st.y })),
      mkSel('Vertical', st.y, cont.map((f) => [f.name, f.name]), (v) => setSt({ y: v, x: v === st.x ? st.y : st.x })),
      r.responses.length > 1 ? mkSel('Response', String(st.response), r.responses.map((n, i) => [String(i), n]), (v) => setSt({ response: Number(v) })) : null);
    for (const f of factors) {
      if (f.name === st.x || f.name === st.y) continue;
      if (f.type === 'categorical') {
        controls.append(mkSel(f.name, String(st.current[f.name] ?? f.levels[0]), f.levels.map((v, i) => [String(v), f.labels[i]]), (v) => { const lv = f.levels.find((x) => String(x) === v); setSt({ current: { ...st.current, [f.name]: lv } }); }));
      } else {
        const i = el('input', { type: 'text', inputmode: 'decimal', size: 8, 'aria-label': `${f.name} value` });
        i.value = fmt(st.current[f.name] ?? f.mean, { sig: 6 }).replace('−', '-');
        i.addEventListener('change', () => { const v = SM.table.toNumber(i.value.replace(',', '.')); if (Number.isFinite(v)) setSt({ current: { ...st.current, [f.name]: v } }); });
        controls.append(el('label', { class: 'sm-fm-opt' }, el('span', { text: f.name }), i));
      }
    }
    const traces = [
      { type: 'contour', x: r.x, y: r.y, z: r.z, colorscale: 'Viridis', reversescale: false, contours: { coloring: 'heatmap', showlabels: true, labelfont: { size: 9, color: '#fff' } }, colorbar: { thickness: 10, len: 0.9, title: { text: r.response, side: 'right' } }, hovertemplate: `${st.x} %{x:.4g}<br>${st.y} %{y:.4g}<br>${r.response} %{z:.5g}<extra></extra>` },
      { type: 'scatter', mode: 'markers', x: r.points.x, y: r.points.y, rows: r.points.rows, marker: { size: 5, color: 'rgba(255,255,255,0.85)', line: { width: 1, color: '#222' } }, name: 'Rows' },
    ];
    ob.add(controls, ctx.plot(traces, { xaxis: { title: { text: st.x } }, yaxis: { title: { text: st.y } }, margin: { l: 58, r: 12, t: 8, b: 46 } }, { width: W(460), height: 380, title: `${r.response} contour profiler` }),
      ctx.note('The prediction over two continuous factors, the other factors at the values above. The points are the rows of the table (linked).'));
  }

  /* ---- Interaction Plots ----------------------------------------------------------------------------- */
  async function interactionPlots(ctx, parent, { kind, payload, scope }) {
    const r = await ctx.call('fitmodel.interaction', { ...payload, kind, alpha: ctx.alpha });
    const ob = ctx.outline('Interaction Plots', { parent, key: 'interaction', info: 'p:fitmodel:profiler', menu: () => [{ label: 'Remove', action: () => ctx.set('interaction', false, scope) }] });
    const k = r.factors.length;
    if (k < 2) { ob.add(ctx.note('Interaction plots need two or more factors.')); return; }
    const c = SM.util.themeColors();
    const traces = [], layout = { margin: { l: 44, r: 40, t: 10, b: 30 }, annotations: [], hovermode: 'closest' };
    const g = 0.045;
    for (let i = 0; i < k; i++) {
      layout.annotations.push({ xref: 'paper', yref: 'paper', x: (i + 0.5) / k, y: 1 - (i + 0.5) / k, text: r.factors[i], showarrow: false, font: { size: 12, color: c.text } });
    }
    for (const cell of r.cells) {
      const idx = cell.row * k + cell.col + 1;
      const ax = idx === 1 ? '' : String(idx);
      layout[`xaxis${ax}`] = { domain: [cell.col / k + g, (cell.col + 1) / k - g], anchor: `y${ax}`, type: r.types[cell.col] === 'categorical' ? 'category' : 'linear', tickfont: { size: 8 }, showgrid: false, fixedrange: true };
      layout[`yaxis${ax}`] = { domain: [1 - (cell.row + 1) / k + g, 1 - cell.row / k - g], anchor: `x${ax}`, tickfont: { size: 8 }, matches: idx === 2 || (k > 1 && idx === 1) ? undefined : 'y2', fixedrange: true, showticklabels: cell.col === (cell.row === 0 ? 1 : 0) };
      cell.lines.forEach((ln, q) => {
        const color = SM.util.PALETTE[q % SM.util.PALETTE.length];
        traces.push({ type: 'scatter', mode: 'lines+markers+text', x: cell.x, y: ln.y, xaxis: `x${ax}`, yaxis: `y${ax}`, line: { color, width: 1.4 }, marker: { size: 4, color },
          text: ln.y.map((_, j) => (j === ln.y.length - 1 ? ln.label : '')), textposition: 'middle right', textfont: { size: 8, color }, cliponaxis: false,
          hovertemplate: `${r.factors[cell.row]} = ${ln.label}<br>${r.factors[cell.col]} = %{x}<br>${r.response} %{y:.5g}<extra></extra>`, showlegend: false });
      });
    }
    const side = Math.max(260, Math.min(620, 140 * k));
    ob.add(ctx.plot(traces, layout, { width: W(side), height: side, title: 'interaction plots', select: false }),
      ctx.note('Each plot shows the prediction across the column factor, one line for each level of the row factor (a continuous one at its minimum and maximum), the other factors averaged. Lines that are not parallel show an interaction.'));
  }

  /* ---- Box-Cox Y Transformation --------------------------------------------------------------------- */
  async function boxCox(ctx, M, parent, payload, y, scope) {
    const P = pal();
    const r = await ctx.call('fitmodel.boxcox', { ...payload, alpha: ctx.alpha });
    const menu = () => [
      { label: 'Save Best Transformation', disabled: !!r.error, action: () => saveBoxCox(ctx, r, y) },
      { label: 'Refit with Transform', disabled: !!r.error, action: () => { const c = saveBoxCox(ctx, r, y); if (c) SM.app.openReport(ctx.report.platform, { ...ctx.spec, roles: { ...ctx.spec.roles, y: [c.id] } }, ctx.table); } },
      { label: 'Remove', action: () => ctx.set('boxcox', false, scope) },
    ];
    const ob = ctx.outline('Box-Cox Transformations', { parent, key: 'boxcox', menu, info: 'p:fitmodel:boxcox' });
    if (r.error) { ob.add(ctx.warn(r.error)); return; }
    const shapes = [];
    for (const v of r.ci) if (v != null) shapes.push({ type: 'line', x0: v, x1: v, yref: 'paper', y0: 0, y1: 1, line: { color: P.muted, dash: 'dash', width: 1 } });
    const traces = [{ type: 'scatter', mode: 'lines', x: r.lambda, y: r.sse, line: { color: P.point, width: 1.6 }, hovertemplate: 'λ %{x:.3g}: SSE %{y:.6g}<extra></extra>' },
      { type: 'scatter', mode: 'markers', x: [r.best], y: [r.sse_best], marker: { color: P.fit, size: 9 }, hovertemplate: `best λ ${fmt(r.best, { sig: 4 })}<extra></extra>` }];
    ob.add(ctx.row(ctx.plot(traces, { xaxis: { title: { text: 'λ' } }, yaxis: { title: { text: 'SSE' } }, shapes }, { width: W(360), height: 260, title: `${y.name} Box-Cox` }),
      ctx.kv([['Best λ', r.best], ['SSE at best λ', r.sse_best], [`Lower ${fmt(100 * (1 - r.alpha))}% λ`, r.ci[0]], [`Upper ${fmt(100 * (1 - r.alpha))}% λ`, r.ci[1]], ['Geometric mean of Y', r.gm]])),
    ctx.note('The error sum of squares of the model fitted to (y^λ − 1)/(λ·ẏ^(λ−1)), ẏ the geometric mean, over λ; the best λ minimises it. Dashed: the likelihood-ratio interval for λ. λ = 1 is no transformation, 0 the logarithm, 0.5 the square root.'), ctx.code(r.code));
  }

  function saveBoxCox(ctx, r, y) {
    return ctx.saveColumn(`${y.name} Box-Cox(${fmt(r.best, { sig: 3 })})`, { rows: r.rows, values: r.values }, { notes: `(y^λ − 1)/(λ ẏ^(λ−1)) with λ = ${fmt(r.best, { sig: 6 })}, ẏ = ${fmt(r.gm, { sig: 8 })}, from ${ctx.report.title}` });
  }

  /* ---- Standard Least Squares -------------------------------------------------------------------------- */
  async function renderStandard(ctx, M) {
    const ys = ctx.roles('y');
    const all = [];
    await perResponse(ctx, ys, (y) => `Response ${y.name}`, async (y, parent, st) => {
      const r = await standardY(ctx, M, y, parent, st);
      if (r) all.push({ y, res: r });
    }, () => [
      ctx.check('Profiler', 'groupProfiler', null, false),
      { label: 'Model Dialog', action: () => ctx.report.relaunch() },
    ]);
    if (ys.length > 1 && ctx.opt('groupProfiler', false) && all.length) {
      await profiler(ctx, ctx.top, { sources: all.map(({ y }) => ({ kind: 'ls', payload: { ...M.base, y: y.name } })), scope: null, title: 'Prediction Profiler', key: 'groupprofiler', option: 'groupProfiler' });
    }
  }

  async function standardY(ctx, M, y, parent, st) {
    const sc = y.id;
    const o = (k, d) => ctx.opt(k, d, sc);
    const emph = ctx.opt('emphasis', 'leverage');
    const payload = { ...M.base, y: y.name };
    const res = await ctx.call('fitmodel.ls', { ...payload, alpha: ctx.alpha, vif: true, leverage: true, dw: o('dw', false), sequential: o('sequential', false), corr: o('corr', false) });
    st.menu = () => lsMenu(ctx, y, res);
    const tc = res.tcrit;
    if (o('effectSummary', true) && res.effect_summary.length) effectSummary(ctx, parent, res.effect_summary, { scope: sc });
    const top = [];
    if (o('plotRegression', emph !== 'minimal')) {
      const rp = await regressionPlot(ctx, parent, { kind: 'ls', payload, factors: res.factors, d: res.diag, yname: y.name, scope: sc });
      if (rp) top.push(rp.el);
    }
    if (o('plotActual', emph !== 'minimal')) top.push(actualByPredicted(ctx, parent, res.diag, res.whole, y.name).el);
    if (o('summaryOfFit', true)) {
      const s = ctx.outline('Summary of Fit', { parent, key: 'sof' });
      const pairs = res.summary.rows.map((r) => [r.stat, r.value]);
      if (o('aicc', false)) pairs.push(['AICc', res.aicc], ['BIC', res.bic]);
      s.add(ctx.kv(pairs));
      top.push(s.el);
    }
    if (top.length > 1) parent.add(ctx.row(...top));
    if (o('anova', true)) ctx.outline('Analysis of Variance', { parent, key: 'anova' }).add(ctx.rt(res.anova, { sortable: false, key: 'anova' }));
    if (res.lof && o('lackOfFit', true)) {
      ctx.outline('Lack Of Fit', { parent, key: 'lof', closed: true }).add(ctx.rt(res.lof, { sortable: false, key: 'lof' }), ctx.kv([['Max RSq', res.lof.max_rsquare]]),
        ctx.note('Pure error is the variation among rows with the same values of every factor; the rest of the error is lack of fit.'));
    }
    if (o('estimates', true)) {
      const showCI = o('showCI', false);
      const cols = res.estimates.columns.map((c) => ({ ...c, hidden: (['lower', 'upper'].includes(c.key) && !showCI) || (c.key === 'vif' && !o('vif', false)) }));
      ctx.outline('Parameter Estimates', { parent, key: 'estimates' }).add(ctx.rt({ columns: cols, rows: res.estimates.rows }, { key: 'estimates' }));
    }
    if (o('effectTests', true) && res.effect_tests.rows.length) ctx.outline('Effect Tests', { parent, key: 'efftests' }).add(ctx.rt(res.effect_tests, { key: 'efftests' }));
    if (o('expression', false)) {
      const terms = res.expression.map((t, i) => `${i === 0 ? '' : (t.estimate < 0 ? ' − ' : ' + ')}${fmt(i === 0 ? t.estimate : Math.abs(t.estimate), { sig: 7 })}${t.term === 'Intercept' ? '' : ` · ${t.term}`}`);
      ctx.outline('Prediction Expression', { parent, key: 'expression' }).add(el('p', { class: 'sm-fm-expr', text: `${y.name} = ${terms.join('')}` }),
        ctx.note('A term name like sex[F] is +1 at that level and −1 at the last level (effect coding); a centred term (x−m) subtracts the mean.'));
    }
    if (o('sortedEst', emph === 'screening')) sortedEstimates(ctx, parent, res, tc);
    if (o('sequential', false) && res.sequential) ctx.outline('Sequential (Type 1) Tests', { parent, key: 'seq' }).add(res.sequential.error ? ctx.warn(res.sequential.error) : ctx.rt(res.sequential, { key: 'seq' }));
    if (o('corr', false) && res.corr) {
      const cols = [{ key: 'term', label: '', fmt: 'text' }, ...res.corr.terms.map((tm, i) => ({ key: `c${i}`, label: tm, digits: 4 }))];
      ctx.outline('Correlation of Estimates', { parent, key: 'corr' }).add(ctx.rt({ columns: cols, rows: res.corr.terms.map((tm, i) => ({ term: tm, ...Object.fromEntries(res.corr.matrix[i].map((v, j) => [`c${j}`, v])) })) }, { sortable: false, key: 'corr' }));
    }
    if (o('effectDetails', true) && res.effects.length) await effectDetails(ctx, M, parent, res, payload, y, o, emph);
    residualPlots(ctx, parent, res.diag, y.name, o, emph, res.diag.limits);
    if (o('press', false)) ctx.outline('Press', { parent, key: 'press' }).add(ctx.kv([['Press', res.press.press], ['Press RMSE', res.press.rmse]]), ctx.note('The sum of squared leave-one-out prediction errors, Σ(eᵢ/(1 − hᵢ))².'));
    if (o('dw', false) && res.dw) {
      ctx.outline('Durbin-Watson', { parent, key: 'dw' }).add(ctx.rt({ columns: [{ key: 'dw', label: 'Durbin-Watson' }, { key: 'n', label: 'Number of Obs.', fmt: 'int' }, { key: 'autocorr', label: 'AutoCorrelation', digits: 4 }, { key: 'p', label: 'Prob<DW', fmt: 'p' }], rows: [res.dw] }, { sortable: false, key: 'dw' }),
        ctx.note('Prob<DW is the exact p-value for positive autocorrelation of the residuals in row order (Imhof\'s method; up to 800 rows).'));
    }
    if (o('boxcox', false)) await boxCox(ctx, M, parent, payload, y, sc);
    if (o('profiler', emph === 'screening')) await profiler(ctx, parent, { sources: [{ kind: 'ls', payload }], scope: sc });
    if (o('contour', false)) await contourProfiler(ctx, parent, { kind: 'ls', payload, factors: res.factors, scope: sc });
    if (o('interaction', false)) await interactionPlots(ctx, parent, { kind: 'ls', payload, scope: sc });
    tail(ctx, parent, res);
    return res;
  }

  function sortedEstimates(ctx, parent, res, tc) {
    const P = pal();
    const rows = res.estimates.rows.filter((r) => r.term !== 'Intercept').slice().sort((a, b) => Math.abs(b.t ?? 0) - Math.abs(a.t ?? 0));
    const ob = ctx.outline('Sorted Parameter Estimates', { parent, key: 'sorted' });
    if (!rows.length) { ob.add(ctx.note('No terms besides the intercept.')); return; }
    const h = Math.max(160, Math.min(560, 40 + 22 * rows.length));
    const tr = [{ type: 'bar', orientation: 'h', y: rows.map((r) => r.term), x: rows.map((r) => r.t), marker: { color: rows.map((r) => (r.p < ctx.alpha ? P.fit : SM.report.BAR)) }, hovertemplate: '%{y}: t = %{x:.4g}<extra></extra>' }];
    const shapes = [tc, -tc].map((v) => ({ type: 'line', x0: v, x1: v, yref: 'paper', y0: 0, y1: 1, line: { color: P.muted, dash: 'dash', width: 1 } }));
    ob.add(ctx.row(ctx.rt({ columns: [{ key: 'term', label: 'Term', fmt: 'text' }, { key: 'estimate', label: 'Estimate' }, { key: 'se', label: 'Std Error' }, { key: 't', label: 't Ratio' }, { key: 'p', label: 'Prob>|t|', fmt: 'p' }], rows }, { sortable: false, key: 'sorted' }),
      ctx.plot(tr, { yaxis: { autorange: 'reversed', type: 'category' }, xaxis: { title: { text: 't Ratio' } }, shapes, margin: { l: 120, r: 12, t: 8, b: 40 } }, { width: W(340), height: h, title: 'sorted t ratios', select: false })));
  }

  async function effectDetails(ctx, M, parent, res, payload, y, o, emph) {
    const sc = y.id;
    const ob = ctx.outline('Effect Details', { parent, key: 'details', closed: emph !== 'leverage', info: 'p:fitmodel:lsmeans' });
    for (const e of res.effects) {
      const lsm = res.lsmeans[e.label];
      const menu = () => [
        ...(lsm ? [
          ctx.check('LSMeans Table', `lsmTable:${e.label}`, sc, true),
          ctx.check('LSMeans Plot', `lsmPlot:${e.label}`, sc, false),
          { label: 'LSMeans Contrast…', action: () => contrastDialog(ctx, M, lsm, e.label, sc) },
          ctx.check('LSMeans Student\'s t', `student:${e.label}`, sc, false),
          ctx.check('LSMeans Tukey HSD', `tukey:${e.label}`, sc, false),
          { separator: true },
        ] : []),
        ctx.check('Leverage Plot', 'plotLeverage', sc, emph === 'leverage'),
      ];
      const eo = ctx.outline(e.label, { parent: ob, key: `eff:${e.label}`, menu });
      const parts = [];
      const lev = (res.leverage || []).find((l) => l.effect === e.label);
      if (lev && o('plotLeverage', emph === 'leverage')) parts.push(leveragePlot(ctx, lev, y.name));
      if (lsm && o(`lsmTable:${e.label}`, true)) parts.push(lsmeansTable(ctx, M, lsm));
      if (parts.length) eo.add(ctx.row(...parts));
      if (lsm && o(`lsmPlot:${e.label}`, false)) eo.add(lsmeansPlot(ctx, M, lsm, res.tcrit, y.name, e.label));
      if (lsm && o(`student:${e.label}`, false)) await comparisons(ctx, M, eo, payload, e.label, 'student', sc);
      if (lsm && o(`tukey:${e.label}`, false)) await comparisons(ctx, M, eo, payload, e.label, 'tukey', sc);
      const cl = o(`contrast:${e.label}`, []);
      if (lsm && cl && cl.length) await contrasts(ctx, eo, payload, e.label, cl, sc);
      if (!parts.length && !lsm) eo.add(ctx.note('Turn on Leverage Plot in this outline\'s red triangle to see the effect\'s leverage plot.'));
    }
  }

  function lsMenu(ctx, y, res) {
    const sc = y.id;
    const c = (label, key, d) => ctx.check(label, key, sc, d);
    const emph = ctx.opt('emphasis', 'leverage');
    return [
      { label: 'Regression Reports', submenu: () => [c('Summary of Fit', 'summaryOfFit', true), c('Analysis of Variance', 'anova', true), c('Parameter Estimates', 'estimates', true),
        c('Effect Tests', 'effectTests', true), c('Effect Details', 'effectDetails', true), c('Lack of Fit', 'lackOfFit', true), { separator: true }, c('Show All Confidence Intervals', 'showCI', false), c('AICc', 'aicc', false)] },
      { label: 'Estimates', submenu: () => [c('Show Prediction Expression', 'expression', false), c('Sorted Estimates', 'sortedEst', emph === 'screening'), c('Sequential Tests', 'sequential', false),
        c('Correlation of Estimates', 'corr', false), c('VIF (in Parameter Estimates)', 'vif', false)] },
      { label: 'Factor Profiling', submenu: () => [c('Profiler', 'profiler', emph === 'screening'), c('Interaction Plots', 'interaction', false), c('Contour Profiler', 'contour', false), c('Box Cox Y Transformation', 'boxcox', false)] },
      { label: 'Row Diagnostics', submenu: () => [c('Plot Regression', 'plotRegression', emph !== 'minimal'), c('Plot Actual by Predicted', 'plotActual', emph !== 'minimal'), c('Plot Effect Leverage', 'plotLeverage', emph === 'leverage'), c('Plot Residual by Predicted', 'plotResidPred', emph !== 'minimal'),
        c('Plot Residual by Row', 'plotResidRow', false), c('Plot Studentized Residuals', 'plotStudent', false), c('Plot Residual by Normal Quantiles', 'plotResidQQ', false), { separator: true }, c('Press', 'press', false), c('Durbin-Watson Test', 'dw', false)] },
      { label: 'Save Columns', submenu: () => saveLS(ctx, res, y) },
      { separator: true },
      c('Effect Summary', 'effectSummary', true),
      { label: 'Model Dialog', action: () => ctx.report.relaunch() },
    ];
  }

  function saveLS(ctx, res, y) {
    const d = res.diag;
    const pct = fmt(100 * (1 - ctx.alpha));
    return [
      { label: 'Predicted Values', action: () => ctx.saveColumn(`Predicted ${y.name}`, { rows: d.rows, values: d.predicted }) },
      { label: 'Residuals', action: () => ctx.saveColumn(`Residual ${y.name}`, { rows: d.rows, values: d.residual }) },
      { label: 'Mean Confidence Interval', action: () => { ctx.saveColumn(`Lower ${pct}% Mean ${y.name}`, { rows: d.rows, values: d.lower_mean }); ctx.saveColumn(`Upper ${pct}% Mean ${y.name}`, { rows: d.rows, values: d.upper_mean }); } },
      { label: 'Indiv Confidence Interval', action: () => { ctx.saveColumn(`Lower ${pct}% Indiv ${y.name}`, { rows: d.rows, values: d.lower_indiv }); ctx.saveColumn(`Upper ${pct}% Indiv ${y.name}`, { rows: d.rows, values: d.upper_indiv }); } },
      { label: 'Studentized Residuals', action: () => ctx.saveColumn(`Studentized Resid ${y.name}`, { rows: d.rows, values: d.studentized }) },
      { label: 'Hats', action: () => ctx.saveColumn(`h ${y.name}`, { rows: d.rows, values: d.hat }) },
      { label: 'Std Error of Predicted', action: () => ctx.saveColumn(`StdErr Pred ${y.name}`, { rows: d.rows, values: d.se_pred }) },
      { label: 'Std Error of Residual', action: () => ctx.saveColumn(`StdErr Resid ${y.name}`, { rows: d.rows, values: d.se_resid }) },
      { label: 'Std Error of Individual', action: () => ctx.saveColumn(`StdErr Indiv ${y.name}`, { rows: d.rows, values: d.se_indiv }) },
      { label: 'Cook\'s D Influence', action: () => ctx.saveColumn(`Cook's D Influence ${y.name}`, { rows: d.rows, values: d.cooks }) },
    ];
  }

  /* ---- Stepwise ---------------------------------------------------------------------------------- */
  async function renderStepwise(ctx, M) {
    const ys = ctx.roles('y');
    await perResponse(ctx, ys, (y) => `Stepwise Fit for ${y.name}`, (y, parent, st) => stepwiseY(ctx, M, y, parent, st));
  }

  async function stepwiseY(ctx, M, y, parent, st) {
    const sc = `${y.id}|${ctx.byLabel || ''}`;
    const o = (k, d) => ctx.opt(k, d, sc);
    const payload = { ...M.base, y: y.name };
    const cfg = { rule: o('sw:rule', 'pvalue'), direction: o('sw:direction', 'forward'), p_enter: o('sw:penter', 0.25), p_leave: o('sw:pleave', 0.1), heredity: o('sw:heredity', M.effects.some((e) => e.cols.length > 1) ? 'combine' : 'none') };
    const state = { entered: o('sw:entered', []), locked: o('sw:locked', []), history: o('sw:history', []), step: o('sw:step', 0) };
    const res = await ctx.call('fitmodel.stepwise', { ...payload, ...cfg, entered: state.entered, locked: state.locked, action: 'show' });
    const act = async (action, extra = {}) => {
      try {
        const r = await ctx.call('fitmodel.stepwise', { ...payload, ...cfg, entered: state.entered, locked: state.locked, action, step0: state.step, ...extra });
        ctx.set('sw:entered', r.entered, sc, { rerun: false });
        ctx.set('sw:history', [...state.history, ...r.history], sc, { rerun: false });
        ctx.set('sw:step', r.step, sc, { rerun: false });
        ctx.report.run();
      } catch (e) { SM.ui.toast(e.message || String(e), { error: true }); }
    };
    const chosenEffects = () => {
      const fixed = (ctx.spec.effects || []).filter((e) => !e.random);
      return res.entered.map((i) => fixed[i]).filter(Boolean);
    };
    const modelSpec = () => ({ ...JSON.parse(JSON.stringify(ctx.spec)), effects: chosenEffects(), options: { ...ctx.spec.options, personality: 'standard' }, roles: { ...ctx.spec.roles, y: [y.id] } });
    const makeModel = () => SM.launch.open({ platform: ctx.report.platform, table: ctx.table, spec: modelSpec(), onOK: (s) => SM.app.openReport(ctx.report.platform, s, ctx.table) });
    const runModel = () => { if (!res.entered.length) { SM.ui.toast('No effects are entered'); return; } SM.app.openReport(ctx.report.platform, modelSpec(), ctx.table); };
    st.menu = () => [
      ctx.check('All Possible Models', 'sw:all', sc, false),
      { label: 'Clear History', action: () => { ctx.set('sw:history', [], sc, { rerun: false }); ctx.set('sw:step', 0, sc); } },
      { separator: true },
      { label: 'Make Model', action: makeModel },
      { label: 'Run Model', action: runModel },
      { label: 'Model Dialog', action: () => ctx.report.relaunch() },
    ];
    const ctl = ctx.outline('Stepwise Regression Control', { parent, key: 'swctl', info: 'p:fitmodel:stepwise' });
    const mkSel = (label, key, value, choices) => { const s = el('select', { 'aria-label': label }, ...choices.map(([v, l]) => el('option', { value: v, text: l }))); s.value = value; s.addEventListener('change', () => ctx.set(key, s.value, sc)); return el('label', { class: 'sm-fm-opt' }, el('span', { text: label }), s); };
    const mkNum = (label, key, value) => { const i = el('input', { type: 'text', inputmode: 'decimal', size: 5, 'aria-label': label }); i.value = String(value); i.addEventListener('change', () => { const v = Number(i.value.replace(',', '.')); if (v > 0 && v < 1) ctx.set(key, v, sc); else i.value = String(value); }); return el('label', { class: 'sm-fm-opt' }, el('span', { text: label }), i); };
    const b = (label, fn) => { const x = el('button', { type: 'button', class: 'sm-btn small', text: label }); x.addEventListener('click', fn); return x; };
    ctl.add(el('div', { class: 'sm-fm-controls' },
      mkSel('Stopping Rule', 'sw:rule', cfg.rule, [['pvalue', 'P-value Threshold'], ['aicc', 'Minimum AICc'], ['bic', 'Minimum BIC']]),
      mkSel('Direction', 'sw:direction', cfg.direction, [['forward', 'Forward'], ['backward', 'Backward'], ['mixed', 'Mixed']]),
      mkSel('Rules', 'sw:heredity', cfg.heredity, [['combine', 'Combine'], ['restrict', 'Restrict'], ['none', 'Whole Effects']]),
      cfg.rule === 'pvalue' ? mkNum('Prob to Enter', 'sw:penter', cfg.p_enter) : null,
      cfg.rule === 'pvalue' ? mkNum('Prob to Leave', 'sw:pleave', cfg.p_leave) : null),
    el('div', { class: 'sm-fm-controls' }, b('Go', () => act('go')), b('Step', () => act('step')), b('Enter All', () => act('enter_all')), b('Remove All', () => act('remove_all')),
      b('Make Model', makeModel), b('Run Model', runModel)),
    ctx.rt({ columns: [{ key: 'sse', label: 'SSE' }, { key: 'dfe', label: 'DFE' }, { key: 'rmse', label: 'RMSE' }, { key: 'rsq', label: 'RSquare' }, { key: 'rsq_adj', label: 'RSquare Adj' }, { key: 'cp', label: 'Cp' }, { key: 'p', label: 'p', fmt: 'int' }, { key: 'aicc', label: 'AICc' }, { key: 'bic', label: 'BIC' }], rows: [res.stats] }, { sortable: false, key: 'swstats' }));
    // Current Estimates: Lock and Entered boxes
    const ce = ctx.outline('Current Estimates', { parent, key: 'swcur' });
    const tbl = el('table', { class: 'sm-rt sm-fm-swtable' });
    tbl.append(el('thead', null, el('tr', null, ...['Lock', 'Entered', 'Parameter', 'Estimate', 'nDF', 'SS', '"F Ratio"', '"Prob>F"'].map((h, i) => el('th', { class: i < 3 ? 'sm-l' : null, text: h })))));
    const body = el('tbody');
    body.append(el('tr', null, el('td'), el('td'), el('td', { class: 'sm-l', text: 'Intercept' }), el('td', { text: fmt(res.intercept) }), el('td', { text: '1' }), el('td', { text: '0' }), el('td', { text: '.' }), el('td', { text: '.' })));
    for (const c of res.current) {
      const lock = el('input', { type: 'checkbox', 'aria-label': `Lock ${c.effect}` });
      lock.checked = c.locked;
      lock.addEventListener('change', () => { const L = new Set(state.locked); if (lock.checked) L.add(c.index); else L.delete(c.index); ctx.set('sw:locked', [...L], sc); });
      const ent = el('input', { type: 'checkbox', 'aria-label': `Entered ${c.effect}`, disabled: c.locked });
      ent.checked = c.entered;
      ent.addEventListener('change', () => act('toggle', { index: c.index }));
      const pTd = el('td', { text: SM.util.fmtP(c.p, 1.01).replace('*', '') });
      body.append(el('tr', { class: c.entered ? 'is-entered' : null }, el('td', null, lock), el('td', null, ent), el('td', { class: 'sm-l', text: c.effect }), el('td', { text: fmt(c.estimate) }), el('td', { text: String(c.ndf) }), el('td', { text: fmt(c.ss) }), el('td', { text: fmt(c.f) }), pTd));
    }
    tbl.append(body);
    ce.add(tbl, ctx.note('For an entered effect: the F test of removing it; for one not entered: of adding it. Check Entered to put an effect in or take it out; Lock keeps it as it is.'));
    const hist = ctx.outline('Step History', { parent, key: 'swhist' });
    if (state.history.length) hist.add(ctx.rt({ columns: [{ key: 'step', label: 'Step', fmt: 'int' }, { key: 'parameter', label: 'Parameter', fmt: 'text' }, { key: 'action', label: 'Action', fmt: 'text' }, { key: 'p', label: '"Sig Prob"', fmt: 'p' }, { key: 'seq_ss', label: 'Seq SS' }, { key: 'rsq', label: 'RSquare' }, { key: 'cp', label: 'Cp' }, { key: 'p_params', label: 'p', fmt: 'int' }, { key: 'aicc', label: 'AICc' }, { key: 'bic', label: 'BIC' }], rows: state.history }, { sortable: false, key: 'swhist' }));
    else hist.add(ctx.note('No steps yet: press Go or Step.'));
    if (o('sw:all', false)) {
      const r = await ctx.call('fitmodel.all_models', { ...payload, per_size: 5 });
      const ob = ctx.outline('All Possible Models', { parent, key: 'swall', menu: () => [{ label: 'Remove', action: () => ctx.set('sw:all', false, sc) }] });
      if (r.error) ob.add(ctx.warn(r.error));
      else {
        ob.add(ctx.rt({ columns: [{ key: 'model', label: 'Model', fmt: 'text' }, { key: 'number', label: 'Number', fmt: 'int' }, { key: 'rsq', label: 'RSquare' }, { key: 'rmse', label: 'RMSE' }, { key: 'aicc', label: 'AICc' }, { key: 'bic', label: 'BIC' }, { key: 'cp', label: 'Cp' }], rows: r.models.map((m) => ({ ...m, model: `${m.model}${m.best ? '  (best of its size)' : ''}${m.min_aicc ? '  (smallest AICc)' : ''}` })) },
          { onRow: (row) => { ctx.set('sw:entered', row.effects, sc); }, key: 'swall' }),
        ctx.note('The five best models of each size by RSquare. Click a line to make it the current model.'));
      }
    }
    tail(ctx, parent, { code: res.code, notes: ['Effects enter and leave whole (all their terms); JMP can also split a nominal effect into its terms. AICc and BIC count the error variance as a parameter.'] });
  }

  /* ---- Generalized Linear Model ----------------------------------------------------------------------- */
  async function renderGLM(ctx, M) {
    const ys = ctx.roles('y');
    const dist = ctx.opt('dist', 'normal');
    const pairs = dist === 'binomial' && ys.length === 2 && ys.every((c) => !c.isCategorical);
    const groups = pairs ? [ys] : ys.map((y) => [y]);
    const fake = groups.map((g) => ({ id: g.map((c) => c.id).join('+'), name: g.map((c) => c.name).join(', '), cols: g }));
    await perResponse(ctx, fake, (g) => `Response ${g.name}`, (g, parent, st) => glmY(ctx, M, g, parent, st, dist));
  }

  async function glmY(ctx, M, g, parent, st, dist) {
    const P = pal();
    const sc = g.id;
    const o = (k, d) => ctx.opt(k, d, sc);
    const payload = { ...M.base, y: g.cols.length === 1 ? g.cols[0].name : g.cols.map((c) => c.name), offset: ctx.name('offset'), dist, link: ctx.opt('link', null) || DEFAULT_LINK[dist], target: ctx.opt('target', null), overdispersion: !!o('overdispersion', false) };
    const res = await ctx.call('fitmodel.glm', { ...payload, alpha: ctx.alpha });
    const m = res.model;
    const wald = o('wald', false);
    st.menu = () => glmMenu(ctx, g, res, sc);
    parent.add(el('p', { class: 'sm-fm-modelline' }, ...[['Response', `${m.response}${m.target ? ` (event: ${m.target})` : ''}`], ['Distribution', m.distribution], ['Link', m.link], ['Estimation Method', 'Maximum Likelihood'], ['Observations (or Sum Wgts)', fmt(m.n)]]
      .map(([k, v]) => el('span', null, el('b', { text: `${k}: ` }), v))));
    if (o('effectSummary', true) && res.effect_tests.length) effectSummary(ctx, parent, res.effect_tests.map((r) => ({ source: r.source, p: wald ? r.p_wald : r.p, logworth: logw(wald ? r.p_wald : r.p) })).sort((a, b) => b.logworth - a.logworth), { scope: sc });
    if (o('wholeModel', true)) {
      ctx.outline('Whole Model Test', { parent, key: 'whole', info: 'p:fitmodel:glm' }).add(
        ctx.rt({ columns: [{ key: 'model', label: 'Model', fmt: 'text' }, { key: 'nll', label: '-LogLikelihood' }, { key: 'lr', label: 'L-R ChiSquare' }, { key: 'df', label: 'DF', fmt: 'int' }, { key: 'p', label: 'Prob>ChiSq', fmt: 'p' }], rows: res.whole }, { sortable: false, key: 'whole' }),
        ctx.kv([['AICc', res.aicc], ['BIC', res.bic]]), res.scaled ? ctx.note(`Scaled by the overdispersion estimate ${fmt(res.overdispersion, { sig: 5 })}.`) : null);
    }
    if (o('gof', true)) {
      const scaleFam = ['normal', 'gamma', 'invgauss'].includes(dist);
      ctx.outline('Goodness Of Fit Statistic', { parent, key: 'gof' }).add(ctx.rt({ columns: [{ key: 'stat', label: 'Statistic', fmt: 'text' }, { key: 'chisq', label: 'ChiSquare' }, { key: 'df', label: 'DF' }, { key: 'p', label: 'Prob>ChiSq', fmt: 'p', hidden: scaleFam }], rows: res.gof }, { sortable: false, key: 'gof' }),
        ctx.kv([['Overdispersion', res.overdispersion]]), scaleFam ? ctx.note('With an estimated dispersion the χ² tests of fit do not apply; Overdispersion is Pearson χ²/DF, the dispersion estimate.') : null);
    }
    if (o('effectTests', true) && res.effect_tests.length) {
      ctx.outline('Effect Tests', { parent, key: 'efftests' }).add(ctx.rt({ columns: [{ key: 'source', label: 'Source', fmt: 'text' }, { key: 'nparm', label: 'Nparm', fmt: 'int' }, { key: 'df', label: 'DF', fmt: 'int' },
        { key: wald ? 'wald' : 'lr', label: wald ? 'Wald ChiSquare' : 'L-R ChiSquare' }, { key: wald ? 'p_wald' : 'p', label: 'Prob>ChiSq', fmt: 'p' }], rows: res.effect_tests }, { key: 'efftests' }));
    }
    if (o('estimates', true)) {
      const ci = o('showCI', true);
      ctx.outline('Parameter Estimates', { parent, key: 'estimates' }).add(ctx.rt({ columns: [{ key: 'term', label: 'Term', fmt: 'text' }, { key: 'estimate', label: 'Estimate' }, { key: 'se', label: 'Std Error' },
        { key: wald ? 'wald' : 'lr', label: wald ? 'Wald ChiSquare' : 'L-R ChiSquare' }, { key: wald ? 'p_wald' : 'p', label: 'Prob>ChiSq', fmt: 'p' }, { key: 'lower', label: `Lower ${fmt(100 * (1 - ctx.alpha))}%`, hidden: !ci }, { key: 'upper', label: `Upper ${fmt(100 * (1 - ctx.alpha))}%`, hidden: !ci }], rows: res.estimates }, { key: 'estimates' }));
    }
    const d = res.diag;
    const yl = res.model.response;
    if (o('studDev', true)) ctx.outline('Studentized Deviance Residual by Predicted', { parent, key: 'studdev' }).add(rowPlot(ctx, { x: d.predicted, y: d.stud_dev, rows: d.rows, xTitle: `${yl} Predicted`, yTitle: 'Studentized Deviance Residual', hlines: [{ y: 0, color: P.mean }], title: 'studentized deviance residuals' }));
    const extraPlots = [['studPearson', 'Studentized Pearson Residual by Predicted', d.stud_pearson, 'Studentized Pearson Residual'], ['devPlot', 'Deviance Residual by Predicted', d.resid_dev, 'Deviance Residual'], ['pearPlot', 'Pearson Residual by Predicted', d.resid_pearson, 'Pearson Residual']];
    for (const [k, title, v, yt] of extraPlots) if (o(k, false)) ctx.outline(title, { parent, key: k }).add(rowPlot(ctx, { x: d.predicted, y: v, rows: d.rows, xTitle: `${yl} Predicted`, yTitle: yt, hlines: [{ y: 0, color: P.mean }], title }));
    if (o('actualPred', false)) actualByPredicted(ctx, parent, { predicted: d.predicted, actual: d.actual, rows: d.rows }, null, yl, 'p:fitmodel:glm');
    if (o('linPlot', false)) {
      const order = d.linpred.map((_, k) => k).sort((a, b) => d.linpred[a] - d.linpred[b]);
      ctx.outline('Linear Predictor Plot', { parent, key: 'linplot' }).add(rowPlot(ctx, { x: d.linpred, y: d.actual, rows: d.rows, xTitle: 'Linear Predictor', yTitle: yl, lines: [lineTrace(order.map((k) => d.linpred[k]), order.map((k) => d.predicted[k]), P.fit)], title: 'linear predictor plot' }),
        ctx.note('The response against the linear predictor; the curve is the fitted mean, the inverse link of the linear predictor.'));
    }
    const kind = 'glm';
    if (o('plotRegression', true) && g.cols.length === 1) await regressionPlot(ctx, parent, { kind, payload, factors: res.factors, d, yname: yl, scope: sc });
    if (o('profiler', false)) await profiler(ctx, parent, { sources: [{ kind, payload }], scope: sc });
    if (o('contour', false)) await contourProfiler(ctx, parent, { kind, payload, factors: res.factors, scope: sc });
    if (o('interaction', false)) await interactionPlots(ctx, parent, { kind, payload, scope: sc });
    tail(ctx, parent, res);
  }
  const logw = (p) => (p == null ? 0 : -Math.log10(Math.max(p, 1e-300)));

  function glmMenu(ctx, g, res, sc) {
    const c = (label, key, d, x) => ctx.check(label, key, sc, d, x);
    const d = res.diag;
    const yl = res.model.response.replace(/, .*/, '');
    const pct = fmt(100 * (1 - ctx.alpha));
    const sv = (name, v) => () => ctx.saveColumn(name, { rows: d.rows, values: v });
    return [
      { label: 'Regression Reports', submenu: () => [c('Whole Model Test', 'wholeModel', true), c('Goodness of Fit', 'gof', true), c('Effect Tests', 'effectTests', true), c('Parameter Estimates', 'estimates', true), c('Confidence Intervals', 'showCI', true), c('Effect Summary', 'effectSummary', true)] },
      c('Overdispersion Tests and Intervals', 'overdispersion', false, { disabled: !['binomial', 'poisson'].includes(ctx.opt('dist', 'normal')) }),
      c('Wald Tests', 'wald', false),
      { label: 'Diagnostic Plots', submenu: () => [c('Regression Plot', 'plotRegression', true), c('Studentized Deviance Residuals by Predicted', 'studDev', true), c('Studentized Pearson Residuals by Predicted', 'studPearson', false), c('Deviance Residuals by Predicted', 'devPlot', false), c('Pearson Residuals by Predicted', 'pearPlot', false), c('Actual by Predicted', 'actualPred', false), c('Linear Predictor Plot', 'linPlot', false)] },
      { label: 'Profilers', submenu: () => [c('Profiler', 'profiler', false), c('Contour Profiler', 'contour', false), c('Interaction Plots', 'interaction', false)] },
      { label: 'Save Columns', submenu: () => [
        { label: 'Predicted Values', action: sv(`Pred ${yl}`, d.predicted) },
        { label: 'Mean Confidence Interval', action: () => { sv(`Lower ${pct}% Mean ${yl}`, d.lower_mean)(); sv(`Upper ${pct}% Mean ${yl}`, d.upper_mean)(); } },
        { label: 'Linear Predictor', action: sv(`Linear Predictor ${yl}`, d.linpred) },
        { label: 'Residuals', action: sv(`Residual ${yl}`, d.residual) },
        { label: 'Deviance Residuals', action: sv(`Deviance Residual ${yl}`, d.resid_dev) },
        { label: 'Pearson Residuals', action: sv(`Pearson Residual ${yl}`, d.resid_pearson) },
        { label: 'Studentized Deviance Residuals', action: sv(`Studentized Deviance Residual ${yl}`, d.stud_dev) },
        { label: 'Studentized Pearson Residuals', action: sv(`Studentized Pearson Residual ${yl}`, d.stud_pearson) },
      ] },
      { separator: true },
      { label: 'Model Dialog', action: () => ctx.report.relaunch() },
    ];
  }

  /* ---- Nominal and Ordinal Logistic ------------------------------------------------------------------------ */
  async function renderLogistic(ctx, M, ordinal) {
    const ys = ctx.roles('y');
    await perResponse(ctx, ys, (y) => `${ordinal ? 'Ordinal' : 'Nominal'} Logistic Fit for ${y.name}`, (y, parent, st) => logisticY(ctx, M, y, parent, st, ordinal));
  }

  async function logisticY(ctx, M, y, parent, st, ordinal) {
    const P = pal();
    const sc = y.id;
    const o = (k, d) => ctx.opt(k, d, sc);
    const payload = { ...M.base, y: y.name, ordinal, distr: ordinal ? ctx.opt('distr', 'logit') : 'logit', target: ordinal ? null : ctx.opt('target', null) };
    const res = await ctx.call('fitmodel.logistic', { ...payload, alpha: ctx.alpha });
    st.menu = () => logisticMenu(ctx, y, res, sc, ordinal);
    if (o('effectSummary', true) && res.effect_tests.length) effectSummary(ctx, parent, res.effect_tests.map((r) => ({ source: r.source, p: r.p, logworth: logw(r.p) })).sort((a, b) => b.logworth - a.logworth), { scope: sc });
    if (res.plot && o('logisticPlot', true)) logisticPlot(ctx, parent, res, y);
    const wm = ctx.outline('Whole Model Test', { parent, key: 'whole', info: 'p:fitmodel:logistic' });
    wm.add(ctx.rt({ columns: [{ key: 'model', label: 'Model', fmt: 'text' }, { key: 'nll', label: '-LogLikelihood' }, { key: 'df', label: 'DF', fmt: 'int' }, { key: 'chisq', label: 'ChiSquare' }, { key: 'p', label: 'Prob>ChiSq', fmt: 'p' }], rows: res.whole }, { sortable: false, key: 'whole' }),
      ctx.kv([['RSquare (U)', res.rsquare_u], ['AICc', res.aicc], ['BIC', res.bic], ['Observations (or Sum Wgts)', res.n]]));
    if (o('fitDetails', true)) {
      const f = res.fit;
      ctx.outline('Fit Details', { parent, key: 'fit' }).add(ctx.kv([['Entropy RSquare', f.entropy_rsq], ['Generalized RSquare', f.generalized_rsq], ['Mean -Log p', f.mean_neg_log_p], ['RMSE', f.rmse], ['Mean Abs Dev', f.mad], ['Misclassification Rate', f.misclass], ['N', f.n]]));
    }
    if (o('estimates', true)) {
      const ci = o('showCI', false);
      const cols = [{ key: 'term', label: 'Term', fmt: 'text' }, { key: 'estimate', label: 'Estimate' }, { key: 'se', label: 'Std Error' }, { key: 'chisq', label: 'ChiSquare' }, { key: 'p', label: 'Prob>ChiSq', fmt: 'p' }, { key: 'lower', label: `Lower ${fmt(100 * (1 - ctx.alpha))}%`, hidden: !ci }, { key: 'upper', label: `Upper ${fmt(100 * (1 - ctx.alpha))}%`, hidden: !ci }];
      if (!ordinal && res.levels.length > 2) cols.unshift({ key: 'logit', label: 'Log Odds of', fmt: 'text' });
      ctx.outline('Parameter Estimates', { parent, key: 'estimates' }).add(ctx.rt({ columns: cols, rows: res.estimates, footer: res.footer }, { sortable: false, key: 'estimates' }));
    }
    if (o('effectTests', true) && res.effect_tests.length) {
      ctx.outline('Effect Likelihood Ratio Tests', { parent, key: 'efftests' }).add(ctx.rt({ columns: [{ key: 'source', label: 'Source', fmt: 'text' }, { key: 'nparm', label: 'Nparm', fmt: 'int' }, { key: 'df', label: 'DF', fmt: 'int' }, { key: 'lr', label: 'L-R ChiSquare' }, { key: 'p', label: 'Prob>ChiSq', fmt: 'p' }], rows: res.effect_tests }, { key: 'efftests' }));
    }
    if (o('odds', false)) {
      const ob = ctx.outline('Odds Ratios', { parent, key: 'odds', info: 'p:fitmodel:logistic' });
      const multi = !ordinal && res.levels.length > 2;
      const lvl = fmt(100 * (1 - ctx.alpha));
      if (res.odds.unit.length) {
        ob.add(ctx.rt({ columns: [...(multi ? [{ key: 'logit', label: 'Log Odds of', fmt: 'text' }] : []), { key: 'term', label: 'Term', fmt: 'text' }, { key: 'unit', label: 'Odds Ratio' }, { key: 'lower', label: `Lower ${lvl}%` }, { key: 'upper', label: `Upper ${lvl}%` }, { key: 'p', label: 'Prob>ChiSq', fmt: 'p' }], rows: res.odds.unit }, { caption: 'Unit Odds Ratios: per unit change in the regressor', key: 'oddsunit' }),
          ctx.rt({ columns: [...(multi ? [{ key: 'logit', label: 'Log Odds of', fmt: 'text' }] : []), { key: 'term', label: 'Term', fmt: 'text' }, { key: 'range', label: 'Odds Ratio' }, { key: 'range_lower', label: `Lower ${lvl}%` }, { key: 'range_upper', label: `Upper ${lvl}%` }, { key: 'span', label: 'Range' }], rows: res.odds.unit }, { caption: 'Range Odds Ratios: over the whole range of the regressor', key: 'oddsrange' }));
      }
      if (res.odds.levels.length) {
        ob.add(ctx.rt({ columns: [...(multi ? [{ key: 'logit', label: 'Log Odds of', fmt: 'text' }] : []), { key: 'term', label: 'Effect', fmt: 'text' }, { key: 'level1', label: 'Level1', fmt: 'text' }, { key: 'level2', label: '/Level2', fmt: 'text' }, { key: 'or', label: 'Odds Ratio' }, { key: 'p', label: 'Prob>ChiSq', fmt: 'p' }, { key: 'lower', label: `Lower ${lvl}%` }, { key: 'upper', label: `Upper ${lvl}%` }], rows: res.odds.levels }, { caption: 'Odds ratios between levels', key: 'oddslevels' }));
      }
      ob.add(ctx.note(ordinal ? 'For the cumulative odds of the lower levels.' : `The odds of ${res.levels.length > 2 ? 'each level against the last' : `${res.target}`} for one level against the other, the other factors averaged; Wald intervals.`));
    }
    if (o('confusion', false)) {
      const cm = res.confusion;
      const rows = cm.levels.map((lv, i) => ({ actual: lv, ...Object.fromEntries(cm.levels.map((_, j) => [`c${j}`, cm.matrix[i][j]])) }));
      const rates = cm.levels.map((lv, i) => { const tot = cm.matrix[i].reduce((a, b) => a + b, 0); return { actual: lv, ...Object.fromEntries(cm.levels.map((_, j) => [`c${j}`, tot ? cm.matrix[i][j] / tot : null])) }; });
      const cols = [{ key: 'actual', label: `Actual ${y.name}`, fmt: 'text' }, ...cm.levels.map((lv, j) => ({ key: `c${j}`, label: lv }))];
      ctx.outline('Confusion Matrix', { parent, key: 'confusion' }).add(ctx.row(ctx.rt({ columns: cols, rows }, { caption: 'Predicted count', sortable: false, key: 'confcount' }), ctx.rt({ columns: cols.map((c2) => (c2.key === 'actual' ? c2 : { ...c2, digits: 4 })), rows: rates }, { caption: 'Predicted rate', sortable: false, key: 'confrate' })),
        ctx.note('Each row is predicted as its most likely level.'));
    }
    if (o('roc', false) && res.roc.length) {
      const traces = res.roc.map((r, i) => ({ type: 'scatter', mode: 'lines', x: r.fpr, y: r.tpr, name: `${r.level} (AUC ${r.auc.toFixed(4)})`, line: { color: SM.util.PALETTE[i % SM.util.PALETTE.length], width: 1.8, shape: 'hv' } }));
      traces.push(lineTrace([0, 1], [0, 1], P.muted, 'dot', 1));
      ctx.outline('Receiver Operating Characteristic', { parent, key: 'roc' }).add(ctx.row(ctx.plot(traces, { showlegend: true, legend: { x: 0.35, y: 0.08 }, xaxis: { title: { text: '1 - Specificity' }, range: [0, 1] }, yaxis: { title: { text: 'Sensitivity' }, range: [0, 1.01] } }, { width: W(360), height: 340, title: 'ROC curve', select: false }),
        ctx.rt({ columns: [{ key: 'level', label: 'Level', fmt: 'text' }, { key: 'auc', label: 'AUC' }], rows: res.roc }, { sortable: false, key: 'auc' })),
      ctx.note(res.roc.length > 1 ? 'Each level against all the others, by its fitted probability.' : `The fitted probability of ${res.roc[0].level} as the score.`));
    }
    if (o('profiler', false)) await profiler(ctx, parent, { sources: [{ kind: 'logistic', payload }], scope: sc });
    if (o('contour', false)) await contourProfiler(ctx, parent, { kind: 'logistic', payload, factors: res.factors, scope: sc });
    if (o('interaction', false)) await interactionPlots(ctx, parent, { kind: 'logistic', payload, scope: sc });
    tail(ctx, parent, res);
  }

  function logisticPlot(ctx, parent, res, y) {
    const p = res.plot;
    const n = res.levels.length;
    const traces = [];
    p.cum.forEach((cv, j) => traces.push({ type: 'scatter', mode: 'lines', x: p.x, y: cv, line: { color: SM.util.PALETTE[j % SM.util.PALETTE.length], width: 1.8 }, hoverinfo: 'skip', showlegend: false }));
    traces.push({ type: 'scatter', mode: 'markers', x: p.points.x, y: p.points.y, rows: p.points.rows, marker: { size: 5 }, name: 'Rows' });
    const end = (j) => (j < 0 ? 0 : j >= n - 1 ? 1 : p.cum[j][p.cum[j].length - 1]);
    const ann = res.levels.map((lv, j) => ({ xref: 'paper', x: 1.01, xanchor: 'left', yref: 'y', y: (end(j - 1) + end(j)) / 2, text: lv, showarrow: false, font: { size: 10, color: SM.util.PALETTE[j % SM.util.PALETTE.length] } }));
    ctx.outline('Logistic Plot', { parent, key: 'logplot', info: 'p:fitmodel:logistic' }).add(ctx.plot(traces, { xaxis: { title: { text: p.factor } }, yaxis: { title: { text: `${y.name} (cumulative probability)` }, range: [0, 1] }, annotations: ann, margin: { l: 58, r: 60, t: 8, b: 44 } }, { width: W(430), height: 320, title: `${y.name} logistic plot` }),
      ctx.note('The curves are the fitted cumulative probabilities of the levels; each row is placed at random between the curves of its level.'));
  }

  function logisticMenu(ctx, y, res, sc, ordinal) {
    const c = (label, key, d) => ctx.check(label, key, sc, d);
    const pr = res.probs;
    return [
      c('Effect Summary', 'effectSummary', true),
      c('Fit Details', 'fitDetails', true),
      c('Parameter Estimates', 'estimates', true), c('Confidence Intervals', 'showCI', false),
      c('Effect Likelihood Ratio Tests', 'effectTests', true),
      c('Odds Ratios', 'odds', false),
      c('Confusion Matrix', 'confusion', false),
      c('ROC Curve', 'roc', false),
      res.plot ? c('Logistic Plot', 'logisticPlot', true) : null,
      { label: 'Profilers', submenu: () => [c('Profiler', 'profiler', false), c('Contour Profiler', 'contour', false), c('Interaction Plots', 'interaction', false)] },
      { label: 'Save Probability Formula', action: () => {
        pr.lin_names.forEach((nm, j) => ctx.saveColumn(nm, { rows: pr.rows, values: pr.lin.map((r) => r[j]) }));
        res.levels.forEach((lv, j) => ctx.saveColumn(`Prob[${lv}]`, { rows: pr.rows, values: pr.prob.map((r) => r[j]) }));
        ctx.saveColumn(`Most Likely ${y.name}`, { rows: pr.rows, values: pr.most_likely }, { dataType: 'character', modelingType: ordinal ? 'ordinal' : 'nominal', valueOrder: res.levels });
      } },
      { separator: true },
      { label: 'Model Dialog', action: () => ctx.report.relaunch() },
    ].filter(Boolean);
  }

  /* ---- Mixed Model ---------------------------------------------------------------------------------------- */
  async function renderMixed(ctx, M, { sls = false } = {}) {
    const ys = ctx.roles('y');
    await perResponse(ctx, ys, (y) => `Response ${y.name}`, (y, parent, st) => mixedY(ctx, M, y, parent, st, sls));
  }

  async function mixedY(ctx, M, y, parent, st, sls) {
    const P = pal();
    const sc = y.id;
    const o = (k, d) => ctx.opt(k, d, sc);
    const payload = { ...M.base, y: y.name };
    const res = await ctx.call('fitmodel.mixed', { ...payload, alpha: ctx.alpha });
    const d = res.diag;
    const pct = fmt(100 * (1 - ctx.alpha));
    st.menu = () => [
      ctx.check('Random Effects Predictions', 'blups', sc, false),
      { label: 'Diagnostic Plots', submenu: () => [ctx.check('Actual by Conditional Predicted', 'actCond', sc, true), ctx.check('Actual by Marginal Predicted', 'actMarg', sc, false), ctx.check('Conditional Residual by Predicted', 'resCond', sc, true)] },
      { label: 'Profilers', submenu: () => [ctx.check('Profiler', 'profiler', sc, false), ctx.check('Interaction Plots', 'interaction', sc, false)] },
      { label: 'Save Columns', submenu: () => [
        { label: 'Conditional Pred Values', action: () => ctx.saveColumn(`Cond Pred ${y.name}`, { rows: d.rows, values: d.predicted }) },
        { label: 'Conditional Residuals', action: () => ctx.saveColumn(`Cond Residual ${y.name}`, { rows: d.rows, values: d.residual }) },
        { label: 'Marginal Pred Values', action: () => ctx.saveColumn(`Pred ${y.name}`, { rows: d.rows, values: d.marginal }) },
        { label: 'Marginal Residuals', action: () => ctx.saveColumn(`Residual ${y.name}`, { rows: d.rows, values: d.marg_resid }) },
      ] },
      { separator: true },
      { label: 'Model Dialog', action: () => ctx.report.relaunch() },
    ];
    const f = res.fit;
    ctx.outline(sls ? 'Summary of Fit' : 'Fit Statistics', { parent, key: 'fitstats', info: 'p:fitmodel:mixed' }).add(ctx.kv([['-2 Residual Log Likelihood', f.m2rll], ['AICc', f.aicc], ['BIC', f.bic], ['Observations', f.n, 'int'], ['Converged', f.converged ? 'yes' : 'no', 'text'], ['Method', f.method, 'text']]));
    ctx.outline(sls ? 'REML Variance Component Estimates' : 'Random Effects Covariance Parameter Estimates', { parent, key: 'varcomp', info: 'p:fitmodel:mixed' }).add(
      ctx.rt({ columns: [{ key: 'effect', label: 'Random Effect', fmt: 'text' }, { key: 'ratio', label: 'Var Ratio' }, { key: 'var', label: 'Var Component' }, { key: 'se', label: 'Std Error' }, { key: 'lower', label: `${pct}% Lower` }, { key: 'upper', label: `${pct}% Upper` }, { key: 'p', label: 'Wald p-Value', fmt: 'p' }, { key: 'pct', label: 'Pct of Total', digits: 3 }], rows: res.varcomp }, { sortable: false, key: 'varcomp' }));
    ctx.outline(sls ? 'Parameter Estimates' : 'Fixed Effects Parameter Estimates', { parent, key: 'estimates' }).add(
      ctx.rt({ columns: [{ key: 'term', label: 'Term', fmt: 'text' }, { key: 'estimate', label: 'Estimate' }, { key: 'se', label: 'Std Error' }, { key: 'dfden', label: 'DFDen', digits: 2 }, { key: 't', label: 't Ratio' }, { key: 'p', label: 'Prob>|t|', fmt: 'p' }, { key: 'lower', label: `${pct}% Lower`, hidden: !o('showCI', false) }, { key: 'upper', label: `${pct}% Upper`, hidden: !o('showCI', false) }], rows: res.estimates }, { key: 'estimates' }));
    if (res.tests.length) ctx.outline(sls ? 'Fixed Effect Tests' : 'Fixed Effects Tests', { parent, key: 'tests' }).add(ctx.rt({ columns: [{ key: 'source', label: 'Source', fmt: 'text' }, { key: 'nparm', label: 'Nparm', fmt: 'int' }, { key: 'dfnum', label: 'DFNum', fmt: 'int' }, { key: 'dfden', label: 'DFDen', digits: 2 }, { key: 'f', label: 'F Ratio' }, { key: 'p', label: 'Prob > F', fmt: 'p' }], rows: res.tests }, { key: 'tests' }));
    if (o('blups', false)) {
      const ob = ctx.outline('Random Effects Predictions', { parent, key: 'blups' });
      for (const b of res.blups) ob.add(ctx.rt({ columns: [{ key: 'level', label: 'Level', fmt: 'text' }, { key: 'blup', label: 'BLUP' }], rows: b.rows }, { caption: b.effect, key: `blup:${b.effect}` }));
      if (!res.blups.length) ob.add(ctx.note('For a model this large (rows times random levels) the predictions are not computed.'));
    }
    const plots = [];
    if (o('actCond', true)) plots.push(actualByPredicted(ctx, parent, { predicted: d.predicted, actual: d.actual, rows: d.rows }, null, y.name, 'p:fitmodel:mixed', 'Actual by Conditional Predicted').el);
    if (o('actMarg', false)) { const ob = ctx.outline('Actual by Marginal Predicted', { parent, key: 'actmarg' }); const [lo, hi] = extent(d.marginal, d.actual); ob.add(rowPlot(ctx, { x: d.marginal, y: d.actual, rows: d.rows, xTitle: `${y.name} Marginal Predicted`, yTitle: `${y.name} Actual`, lines: [lineTrace([lo, hi], [lo, hi], P.fit)], title: 'actual by marginal predicted' })); plots.push(ob.el); }
    if (o('resCond', true)) { const ob = ctx.outline('Conditional Residual by Predicted', { parent, key: 'rescond' }); ob.add(rowPlot(ctx, { x: d.predicted, y: d.residual, rows: d.rows, xTitle: `${y.name} Conditional Predicted`, yTitle: 'Conditional Residual', hlines: [{ y: 0, color: P.mean }], title: 'conditional residuals' })); plots.push(ob.el); }
    if (plots.length > 1) parent.add(ctx.row(...plots));
    if (o('profiler', false)) await profiler(ctx, parent, { sources: [{ kind: 'mixed', payload }], scope: sc });
    if (o('interaction', false)) await interactionPlots(ctx, parent, { kind: 'mixed', payload, scope: sc });
    tail(ctx, parent, res);
  }

  /* ---- MANOVA --------------------------------------------------------------------------------------------- */
  async function renderManova(ctx, M) {
    const ys = ctx.roles('y');
    const sc = 'manova';
    const o = (k, d) => ctx.opt(k, d, sc);
    const response = o('response', 'identity');
    const res = await ctx.call('fitmodel.manova', { ...M.base, y: ys.map((c) => c.name), response, alpha: ctx.alpha });
    ctx.fm.menu = () => [
      ctx.check('Show E and H Matrices', 'matrices', sc, false),
      ctx.check('Partial Correlation', 'partial', sc, false),
      ctx.check('Univariate Tests Also', 'univariate', sc, false),
      { separator: true },
      { label: 'Model Dialog', action: () => ctx.report.relaunch() },
    ];
    if (res.error) { ctx.top.add(ctx.warn(res.error)); return; }
    const spec = ctx.outline('Response Specification', { key: 'mvspec', info: 'p:fitmodel:manova' });
    const s = el('select', { 'aria-label': 'Choose Response' }, ...[['identity', 'Identity'], ['sum', 'Sum'], ['contrast', 'Contrast'], ['polynomial', 'Polynomial'], ['mean', 'Mean']].map(([v, l]) => el('option', { value: v, text: l })));
    s.value = response;
    s.addEventListener('change', () => ctx.set('response', s.value, sc));
    spec.add(el('div', { class: 'sm-fm-controls' }, el('label', { class: 'sm-fm-opt' }, el('span', { text: 'Choose Response' }), s)),
      ctx.note(`Responses: ${res.responses.join(', ')}. Tested: ${res.labels.join(', ')}. Identity tests the responses themselves; Sum their total; Contrast each against the last; Polynomial the trends over them.`));
    for (const t of res.tests) {
      ctx.outline(t.effect, { key: `mv:${t.effect}` }).add(ctx.rt({ columns: [{ key: 'test', label: 'Test', fmt: 'text' }, { key: 'value', label: 'Value' }, { key: 'f', label: 'Approx. F' }, { key: 'numdf', label: 'NumDF' }, { key: 'dendf', label: 'DenDF' }, { key: 'p', label: 'Prob>F', fmt: 'p' }], rows: t.rows }, { sortable: false, key: `mv:${t.effect}` }),
        o('matrices', false) && res.H[t.effect] ? matrixTable(ctx, res.H[t.effect], res.labels, 'H Matrix') : null);
    }
    if (o('matrices', false) && res.E) ctx.outline('E Matrix', { key: 'mvE' }).add(matrixTable(ctx, res.E, res.labels, 'E: the residual sums of squares and cross products'));
    if (o('partial', false) && res.partial_corr) ctx.outline('Partial Correlation', { key: 'mvpc' }).add(matrixTable(ctx, res.partial_corr, res.labels, 'Correlations of the residuals'), ctx.note(`DF = ${fmt(res.dfe)}.`));
    if (o('univariate', false)) {
      const ob = ctx.outline('Univariate Tests', { key: 'mvuni' });
      for (const u of res.univariate) ob.add(ctx.rt({ columns: [{ key: 'source', label: 'Source', fmt: 'text' }, { key: 'df', label: 'DF', fmt: 'int' }, { key: 'ss', label: 'Sum of Squares' }, { key: 'f', label: 'F Ratio' }, { key: 'p', label: 'Prob > F', fmt: 'p' }], rows: u.rows }, { caption: `${u.y}: RSquare ${fmt(u.rsq, { digits: 4 })}, RMSE ${fmt(u.rmse, { sig: 5 })}`, key: `uni:${u.y}` }));
    }
    tail(ctx, ctx.top, res);
  }

  function matrixTable(ctx, Mx, labels, caption) {
    return ctx.rt({ columns: [{ key: 'r', label: '', fmt: 'text' }, ...labels.map((l, j) => ({ key: `c${j}`, label: l }))], rows: Mx.map((row, i) => ({ r: labels[i], ...Object.fromEntries(row.map((v, j) => [`c${j}`, v])) })) }, { caption, sortable: false, key: caption });
  }

  /* ---- Generalized Regression ------------------------------------------------------------------------------ */
  async function renderGenReg(ctx, M) {
    const ys = ctx.roles('y');
    await perResponse(ctx, ys, (y) => `Generalized Regression for ${y.name}`, (y, parent, st) => genregY(ctx, M, y, parent, st));
  }

  async function genregY(ctx, M, y, parent, st) {
    const P = pal();
    const sc = y.id;
    const o = (k, d) => ctx.opt(k, d, sc);
    const cfg = { dist: o('gr:dist', ctx.opt('dist', 'normal')), method: o('gr:method', 'lasso'), enet_alpha: o('gr:enet', 0.9), criterion: o('gr:crit', 'aicc'), n_grid: 40, choose: o(`gr:choose:${ctx.byLabel || ''}`, null), target: ctx.opt('target', null) };
    if (!GR_DISTS.some((x) => x[0] === cfg.dist)) cfg.dist = 'normal';
    const payload = { ...M.base, y: y.name, ...cfg };
    const res = await ctx.call('fitmodel.genreg', payload);
    const m = res.model;
    st.menu = () => [
      { label: 'Profilers', submenu: () => [ctx.check('Profiler', 'profiler', sc, false), ctx.check('Interaction Plots', 'interaction', sc, false)] },
      { label: 'Save Columns', submenu: () => [{ label: 'Predicted Values', action: () => ctx.saveColumn(`Pred ${y.name}`, { rows: res.diag.rows, values: res.diag.predicted }) }, { label: 'Residuals', action: () => ctx.saveColumn(`Residual ${y.name}`, { rows: res.diag.rows, values: res.diag.residual }) }] },
      { separator: true },
      { label: 'Model Dialog', action: () => ctx.report.relaunch() },
    ];
    const launch = ctx.outline('Model Launch', { parent, key: 'grlaunch', info: 'p:fitmodel:genreg' });
    const mkSel = (label, key, value, choices) => { const s = el('select', { 'aria-label': label }, ...choices.map(([v, l]) => el('option', { value: v, text: l }))); s.value = value; s.addEventListener('change', () => { ctx.set(`gr:choose:${ctx.byLabel || ''}`, null, sc, { rerun: false }); ctx.set(key, s.value, sc); }); return el('label', { class: 'sm-fm-opt' }, el('span', { text: label }), s); };
    const enet = el('input', { type: 'text', inputmode: 'decimal', size: 5, 'aria-label': 'Elastic Net Alpha' });
    enet.value = String(cfg.enet_alpha);
    enet.addEventListener('change', () => { const v = Number(enet.value.replace(',', '.')); if (v > 0 && v < 1) ctx.set('gr:enet', v, sc); else enet.value = String(cfg.enet_alpha); });
    launch.add(el('div', { class: 'sm-fm-controls' },
      mkSel('Distribution', 'gr:dist', cfg.dist, GR_DISTS),
      mkSel('Estimation Method', 'gr:method', cfg.method, [['lasso', 'Lasso'], ['enet', 'Elastic Net'], ['ridge', 'Ridge']]),
      mkSel('Validation Method', 'gr:crit', cfg.criterion, [['aicc', 'AICc'], ['bic', 'BIC']]),
      cfg.method === 'enet' ? el('label', { class: 'sm-fm-opt' }, el('span', { text: 'Elastic Net Alpha' }), enet) : null));
    const fitOb = ctx.outline(`${m.method} with ${m.criterion} Validation`, { parent, key: 'grfit' });
    fitOb.add(ctx.kv([['Response', m.response, 'text'], ['Distribution', m.distribution, 'text'], m.target ? ['Target level', m.target, 'text'] : null, ['Number of rows', m.rows, 'int'], ['Sum of Frequencies', m.n], ['-LogLikelihood', m.nll], ['Number of Parameters', m.nparm], ['BIC', m.bic], ['AICc', m.aicc], ['Generalized RSquare', m.grsq], ['Lambda Penalty', m.lambda], m.method === 'Elastic Net' ? ['Elastic Net Alpha', m.enet_alpha] : null], { caption: 'Model Summary' }));
    // the solution path: the scaled estimates and the criterion against the size of the estimates
    const x = res.path.l1;
    const chosenX = x[res.chosen];
    const crit = cfg.criterion === 'bic' ? res.path.bic : res.path.aicc;
    const vline = { type: 'line', x0: chosenX, x1: chosenX, yref: 'paper', y0: 0, y1: 1, line: { color: P.fit, width: 1.4, dash: 'dash' } };
    const coefTr = res.path.coefs.map((c2, i) => ({ type: 'scatter', mode: 'lines', x, y: c2.values, name: c2.term, line: { color: SM.util.PALETTE[i % SM.util.PALETTE.length], width: 1.4 }, hovertemplate: `${c2.term}: %{y:.4g}<extra></extra>` }));
    const critTr = [{ type: 'scatter', mode: 'lines+markers', x, y: crit, marker: { size: 5, color: P.point }, line: { color: P.point, width: 1.2 }, hovertemplate: `step %{pointNumber}: ${m.criterion} %{y:.5g}<extra></extra>` }];
    const choose = (gd) => gd.on('plotly_click', (ev) => { const pt = ev && ev.points && ev.points[0]; if (pt != null && pt.pointNumber != null) ctx.set(`gr:choose:${ctx.byLabel || ''}`, pt.pointNumber, sc); });
    const pathOb = ctx.outline('Solution Path', { parent: fitOb, key: 'grpath', menu: () => [{ label: 'Reset to the Best Model', action: () => ctx.set(`gr:choose:${ctx.byLabel || ''}`, null, sc) }] });
    pathOb.add(ctx.row(
      ctx.plot(coefTr, { xaxis: { title: { text: 'Magnitude of Scaled Parameter Estimates' } }, yaxis: { title: { text: 'Parameter Estimates' } }, shapes: [vline], hovermode: 'x' }, { width: W(390), height: 290, title: 'solution path', select: false, onDraw: choose }),
      ctx.plot(critTr, { xaxis: { title: { text: 'Magnitude of Scaled Parameter Estimates' } }, yaxis: { title: { text: m.criterion } }, shapes: [vline] }, { width: W(330), height: 290, title: `${m.criterion} path`, select: false, onDraw: choose })),
    ctx.note(`Each step of the path is a penalty; the dashed line is the chosen model (${res.chosen === res.best ? `the smallest ${m.criterion}` : 'chosen by a click'}). Click a point of the ${m.criterion} plot, or a line of the path, to choose another.`));
    fitOb.add(ctx.rt({ columns: [{ key: 'term', label: 'Term', fmt: 'text' }, { key: 'estimate', label: 'Estimate' }, { key: 'zeroed', label: '', fmt: 'text' }], rows: res.estimates.map((e) => ({ ...e, zeroed: e.zero ? 'zeroed' : '' })) }, { caption: 'Parameter Estimates for Original Predictors', sortable: false, key: 'grest' }),
      ctx.rt({ columns: [{ key: 'term', label: 'Term', fmt: 'text' }, { key: 'estimate', label: 'Estimate' }], rows: res.scaled }, { caption: 'Parameter Estimates for Centered and Scaled Predictors', sortable: false, key: 'grscaled' }));
    if (o('profiler', false)) await profiler(ctx, parent, { sources: [{ kind: 'genreg', payload }], scope: sc });
    if (o('interaction', false)) await interactionPlots(ctx, parent, { kind: 'genreg', payload, scope: sc });
    tail(ctx, parent, res);
  }

  /* ---- Help ---------------------------------------------------------------------------------------------- */
  const MORE = { label: 'Fit Model', id: 'help-p-fitmodel' };
  const TOPICS = {
    'p:fitmodel': {
      kicker: 'Analyze', title: 'Fit Model',
      lead: 'Linear and generalized models of one or more responses: choose the Y, build the model from effects, pick a personality and press OK. The model is JMP\'s, the numbers are statsmodels\'.',
      sections: [
        { heading: 'Roles', choices: [['Y', 'The response. A continuous Y gets Standard Least Squares by default, a nominal one Nominal Logistic, an ordinal one Ordinal Logistic.'], ['Weight', 'Weights of the rows (least squares: WLS weights; GLM: variance weights).'], ['Freq', 'Each row counts that many times; the degrees of freedom follow.'], ['Offset', 'A known part of the linear predictor (GLM), for example log exposure.'], ['By', 'A separate fit for each level.']] },
        { heading: 'Construct Model Effects', text: 'Select columns on the left and press Add. Cross makes an interaction, a column crossed with itself a power; Nest puts an effect within a column (B[A]). The Macros add whole models; Attributes > Random Effect marks an effect as random (Mixed Model, or REML in Standard Least Squares).' },
        { heading: 'Coding', text: 'Nominal and ordinal factors are effect coded (a level\'s parameter is its difference from the average of the levels, the last level the negative sum); continuous columns in crossings and powers are centred at their means, as JMP\'s Center Polynomials.' },
      ],
      more: MORE,
    },
    'p:fitmodel:effects': {
      kicker: 'Fit Model', title: 'Construct Model Effects',
      lead: 'The effects of the model. Select columns in the list of columns, then:',
      sections: [{ choices: [['Add', 'each selected column as a main effect'], ['Cross', 'the selected columns crossed together, or with the selected effects (a column with itself: its square)'], ['Nest', 'the selected effects nested in the selected columns: B[A]'], ['Macros', 'Full Factorial (every crossing), Factorial to Degree, Factorial Sorted (by degree), Response Surface (main effects, crossings, squares), Polynomial to Degree'], ['Degree', 'the degree of Factorial to Degree and Polynomial to Degree'], ['Attributes', 'Random Effect: the effect\'s levels are a random sample (a variance component)'], ['Remove', 'the selected effects (or double click one)'], ['No Intercept', 'fit without the constant term']] }],
      more: MORE,
    },
    'p:fitmodel:personality': {
      kicker: 'Fit Model', title: 'Personality',
      lead: 'How the model is fitted and reported.',
      sections: [{ choices: [['Standard Least Squares', 'OLS (WLS with a weight): tests, leverage plots, least squares means, profilers. With random effects: REML.'], ['Stepwise', 'Chooses the effects by p-values, AICc or BIC.'], ['Generalized Linear Model', 'statsmodels GLM: normal, binomial, Poisson, gamma, inverse Gaussian, negative binomial, with a link.'], ['Nominal Logistic', 'Multinomial logit: the log odds of each level against the last.'], ['Ordinal Logistic', 'Cumulative logit (or probit) for ordered levels.'], ['Mixed Model', 'MixedLM by REML, random effects from the Random Effect attribute.'], ['MANOVA', 'Several continuous responses tested together.'], ['Generalized Regression', 'Penalized fits: lasso, elastic net, ridge, chosen by AICc or BIC.']] },
        { heading: 'Emphasis', text: 'For Standard Least Squares: Effect Leverage opens the leverage plots and the effect details, Effect Screening the sorted estimates and the profiler, Minimal Report only the tables.' }],
      more: MORE,
    },
    'p:fitmodel:summary': {
      kicker: 'Fit Model', title: 'Effect Summary',
      lead: 'The effects by LogWorth, −log₁₀ of the p-value of their test (the line is at p = 0.01). FDR adjusts the p-values for the number of effects (Benjamini and Hochberg).',
      sections: [{ heading: 'Editing the model', text: 'Click an effect and press Remove to refit without it; Undo brings it back; Edit opens the launch dialog.' }],
      more: MORE,
    },
    'p:fitmodel:leverage': {
      kicker: 'Fit Model', title: 'Leverage plots',
      lead: 'In a leverage plot each point\'s vertical distance to the sloped line is its residual in the model, and its distance to the horizontal line (the mean) its residual in the model without the effect. The dashed confidence curves cross the horizontal line when the effect is significant.',
      sections: [{ heading: 'Actual by Predicted', text: 'The leverage plot of the whole model: the response against its prediction, with the p-value, RSquare and RMSE of the model.' }, { heading: 'Units', text: 'For a continuous regressor the horizontal axis is in the regressor\'s units (an added-variable plot); otherwise in the response\'s.' }],
      more: MORE,
    },
    'p:fitmodel:lsmeans': {
      kicker: 'Fit Model', title: 'Least squares means',
      lead: 'The model\'s prediction at each level of an effect, with the other categorical factors averaged over their levels and continuous ones at their means: means adjusted for the rest of the model.',
      sections: [{ choices: [['LSMeans Student\'s t', 'pairwise t tests, no adjustment for the number of comparisons'], ['LSMeans Tukey HSD', 'pairwise comparisons adjusted by the studentized range (Tukey-Kramer)'], ['Connecting Letters Report', 'levels that share no letter differ significantly'], ['LSMeans Contrast', 'your own weighted comparisons of the levels, with a joint F test']] }],
      more: MORE,
    },
    'p:fitmodel:profiler': {
      kicker: 'Fit Model', title: 'Profilers',
      lead: 'The Prediction Profiler shows how the prediction changes with each factor, the others held at their current values. Drag a red dashed line, click a plot, or type a value; the prediction and its confidence interval are on the left.',
      sections: [{ heading: 'Contour Profiler', text: 'The prediction over two continuous factors as a contour map, the rows of the table on it.' }, { heading: 'Interaction Plots', text: 'The prediction across one factor with a line for each level of another: parallel lines mean no interaction.' }],
      more: MORE,
    },
    'p:fitmodel:boxcox': { kicker: 'Fit Model', title: 'Box-Cox Y Transformation', lead: 'The error sum of squares of the model for the power transformations of Y, scaled by the geometric mean so that they compare. The best λ minimises it; λ near 1 needs no transformation, near 0 a logarithm. Save Best Transformation adds the transformed column; Refit with Transform fits the model to it.', more: MORE },
    'p:fitmodel:stepwise': {
      kicker: 'Fit Model', title: 'Stepwise',
      lead: 'Builds the model one effect at a time. Go runs until the rule stops, Step makes one step, the Entered boxes put effects in and out by hand. Make Model opens the launch dialog with the chosen effects, Run Model fits them at once.',
      sections: [{ choices: [['P-value Threshold', 'forward enters the most significant effect while its p-value is below Prob to Enter; backward removes the least significant while above Prob to Leave; mixed does both'], ['Minimum AICc, BIC', 'goes all the way and keeps the model with the smallest criterion on the path'], ['Rules', 'Combine enters an interaction with its lower effects, Restrict only after them; Whole Effects has no rule']] }],
      more: MORE,
    },
    'p:fitmodel:glm': {
      kicker: 'Fit Model', title: 'Generalized Linear Model',
      lead: 'A distribution for the response and a link from its mean to the linear predictor, fitted by maximum likelihood (statsmodels GLM; the negative binomial by statsmodels\' NB2 model).',
      sections: [{ choices: [['Whole Model Test', 'the likelihood ratio test against the model with only the intercept'], ['Goodness Of Fit', 'Pearson and deviance χ² (for binomial and Poisson); their ratio to DF estimates overdispersion'], ['Effect Tests', 'likelihood ratio tests by refitting without each effect (Wald Tests: Wald χ²)'], ['Overdispersion Tests and Intervals', 'scales the tests and the standard errors by Pearson χ²/DF']] }],
      more: MORE,
    },
    'p:fitmodel:logistic': {
      kicker: 'Fit Model', title: 'Logistic fits',
      lead: 'Nominal Logistic models the log odds of each level against the last (for two levels: of the first, or the Target Level); Ordinal Logistic the cumulative probabilities P(Y ≤ level) = F(intercept + x′b), one intercept per level and one slope per term.',
      sections: [{ choices: [['Whole Model Test', 'twice the log-likelihood gain over the model without effects; RSquare (U) its share'], ['Effect Likelihood Ratio Tests', 'refits without each effect'], ['Odds Ratios', 'per unit and over the range of a regressor; between levels of a factor'], ['Confusion Matrix, ROC', 'how well the most likely level and the probabilities classify']] }],
      more: MORE,
    },
    'p:fitmodel:mixed': {
      kicker: 'Fit Model', title: 'Mixed Model',
      lead: 'Fixed effects and random effects (variance components), fitted by REML with statsmodels\' MixedLM. A random effect that holds a continuous column is a random slope.',
      sections: [{ choices: [['Var Component', 'the variance of the random effect; Var Ratio its ratio to the residual variance, Pct of Total its share'], ['Std Error', 'from the REML information; Wald intervals and p-values'], ['DFDen', 'Satterthwaite\'s degrees of freedom of each test'], ['Conditional', 'predictions with the random effects\' BLUPs; marginal: the fixed effects only']] }],
      more: MORE,
    },
    'p:fitmodel:manova': { kicker: 'Fit Model', title: 'MANOVA', lead: 'Tests each effect on all responses at once: Wilks\' lambda, Pillai\'s trace, the Hotelling-Lawley trace and Roy\'s maximum root, each with an F approximation. Choose Response transforms the responses first (sum, contrasts, polynomial trends).', more: MORE },
    'p:fitmodel:genreg': { kicker: 'Fit Model', title: 'Generalized Regression', lead: 'Penalized fits on centred and scaled predictors: the lasso sets small effects to zero, ridge shrinks them all, the elastic net mixes the two (Elastic Net Alpha is the lasso share). The path runs from the heaviest penalty to almost none; the model with the smallest AICc or BIC is chosen, or the one you click.', more: MORE },
  };

  /* ---- the platform -------------------------------------------------------------------------------------- */
  SM.platforms.register({
    id: 'fitmodel', label: 'Fit Model', menu: 'Analyze', order: 110, info: 'p:fitmodel', topics: TOPICS,
    about: 'Linear and generalized models from JMP\'s Construct Model Effects (crossings, nesting, macros, random effects), fitted by one of the personalities: Standard Least Squares (effect tests, leverage plots, least squares means with Tukey HSD, row diagnostics, Box-Cox, the Prediction and Contour Profilers), Stepwise, Generalized Linear Model, Nominal and Ordinal Logistic, Mixed Model (REML), MANOVA and Generalized Regression (lasso, elastic net, ridge).',
    uses: ['statsmodels.formula.api.ols, wls', 'statsmodels.regression.linear_model.RegressionResults.wald_test_terms', 'statsmodels.stats.anova.anova_lm', 'statsmodels.stats.outliers_influence.variance_inflation_factor', 'statsmodels.stats.multitest.multipletests', 'statsmodels.genmod.generalized_linear_model.GLM', 'statsmodels.discrete.discrete_model.MNLogit, NegativeBinomial', 'statsmodels.miscmodels.ordinal_model.OrderedModel', 'statsmodels.regression.mixed_linear_model.MixedLM', 'statsmodels.multivariate.manova.MANOVA', 'statsmodels.regression.linear_model.OLS.fit_regularized', 'scipy.stats.studentized_range', 'patsy'],
    launch: {
      lead: 'Choose the Y, add the model effects from the selected columns, and pick a personality. Continuous Y: least squares; nominal or ordinal Y: logistic.',
      roles: [
        { key: 'y', label: 'Y', min: 1, hint: 'required' },
        { key: 'weight', label: 'Weight', max: 1, numeric: true, types: ['continuous'], hint: 'optional numeric' },
        { key: 'freq', label: 'Freq', max: 1, numeric: true, types: ['continuous'], hint: 'optional numeric' },
        { key: 'offset', label: 'Offset', max: 1, numeric: true, types: ['continuous'], hint: 'optional (generalized linear model)' },
        { key: 'by', label: 'By', hint: 'optional' },
      ],
      extra: constructEffects,
      validate,
    },
    title(spec, table) {
      const p = (spec.options || {}).personality || 'standard';
      const ys = ((spec.roles || {}).y || []).map((id) => (table ? table.col(id) : null)).filter(Boolean).map((c) => c.name);
      const one = ys.length === 1 ? ys[0] : null;
      switch (p) {
        case 'stepwise': return one ? `Stepwise Fit for ${one}` : 'Fit Stepwise';
        case 'glm': return 'Generalized Linear Model Fit';
        case 'nominal': return one ? `Nominal Logistic Fit for ${one}` : 'Fit Nominal Logistic';
        case 'ordinal': return one ? `Ordinal Logistic Fit for ${one}` : 'Fit Ordinal Logistic';
        case 'mixed': return 'Fit Mixed';
        case 'manova': return 'Manova Fit';
        case 'genreg': return one ? `Generalized Regression for ${one}` : 'Generalized Regression';
        default: return one ? `Response ${one}` : 'Fit Group';
      }
    },
    triangle(ctx) { return ctx.fm && ctx.fm.menu ? ctx.fm.menu() : [{ label: 'Model Dialog', action: () => ctx.report.relaunch() }]; },
    async render(ctx) {
      ctx.fm = { menu: null };
      const M = modelOf(ctx);
      const p = ctx.opt('personality', 'standard');
      if (p === 'stepwise') return renderStepwise(ctx, M);
      if (p === 'glm') return renderGLM(ctx, M);
      if (p === 'nominal' || p === 'ordinal') return renderLogistic(ctx, M, p === 'ordinal');
      if (p === 'mixed') return renderMixed(ctx, M);
      if (p === 'manova') return renderManova(ctx, M);
      if (p === 'genreg') return renderGenReg(ctx, M);
      if (M.effects.some((e) => e.random)) return renderMixed(ctx, M, { sls: true });
      return renderStandard(ctx, M);
    },
  });
}(typeof self !== 'undefined' ? self : this));
