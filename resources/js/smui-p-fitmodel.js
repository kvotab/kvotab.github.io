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
     Generalized Estimating    statsmodels' GEE: a Subject, Time and Subgroup,
       Equations               working correlations, robust / naive / bias-
                               reduced errors, QIC, Compare Working Correlations
     Nominal, Ordinal Logistic MNLogit (or a binomial GLM) and OrderedModel
     Mixed Model               MixedLM by REML, variance components
     MANOVA                    statsmodels' MANOVA; Repeated Measures: between and
                               within subjects, sphericity, G-G and H-F epsilons
     Generalized Regression    lasso, elastic net, ridge (and adaptive) paths, forward
                               selection; AICc, BIC, KFold, holdback, leave-one-out or a
                               Validation column (the launch's Validation role)
     Instrumental Variables    two-stage least squares (IV2SLS): Endogenous
                               and Instruments roles, first stages, weak-
                               instrument statistics, Durbin-Wu-Hausman and
                               Sargan / Hansen J tests, OLS beside it
     Quantile Regression       QuantReg at a quantile, the quantile process
                               beside least squares, quantile lines

   Beyond JMP, Standard Least Squares has Robust Standard Errors (HC0-HC3,
   Newey-West, cluster; the GLM the sandwich, HAC and cluster), Regression
   Diagnostics (statsmodels' specification and residual tests, an Influence
   Plot, Component + Residual plots) and Recursive and Rolling Regression
   (RecursiveLS's recursive estimates, CUSUM and CUSUM of squares; RollingOLS).
   The example tables 'longitudinal' and 'schooling' are made here.

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
    ['gee', 'Generalized Estimating Equations'], ['nominal', 'Nominal Logistic'], ['ordinal', 'Ordinal Logistic'], ['mixed', 'Mixed Model'],
    ['manova', 'MANOVA'], ['genreg', 'Generalized Regression'], ['iv', 'Instrumental Variables'], ['quantreg', 'Quantile Regression']];
  const PERS_LABEL = Object.fromEntries(PERS);
  // Quantile Regression: statsmodels' covariances, kernels and bandwidths, the default quantile process
  const QR_COVS = [['robust', 'Robust (statsmodels)'], ['iid', 'IID'], ['powell', 'Powell sandwich']];
  const QR_KERNELS = [['epa', 'Epanechnikov'], ['gau', 'Gaussian'], ['cos', 'Cosine'], ['par', 'Parzen'], ['biw', 'Biweight']];
  const QR_BWS = [['hsheather', 'Hall–Sheather'], ['bofinger', 'Bofinger'], ['chamberlain', 'Chamberlain']];
  const QR_TAUS = '0.05 to 0.95 by 0.05';
  // Recursive and Rolling Regression (Standard Least Squares): the parts, each an option of the report
  const RR = [['rr:recursive', 'Recursive Estimates'], ['rr:cusum', 'CUSUM Test'], ['rr:cusumsq', 'CUSUM of Squares Test'], ['rr:rolling', 'Rolling Regression']];
  const EMPH = [['leverage', 'Effect Leverage'], ['screening', 'Effect Screening'], ['minimal', 'Minimal Report']];
  const DISTS = [['normal', 'Normal'], ['binomial', 'Binomial'], ['poisson', 'Poisson'], ['gamma', 'Gamma'], ['invgauss', 'Inverse Gaussian'], ['negbin', 'Negative Binomial']];
  const GR_DISTS = [['normal', 'Normal'], ['binomial', 'Binomial'], ['poisson', 'Poisson']];
  const GEE_DISTS = [...DISTS, ['tweedie', 'Tweedie']];
  const LINKS = [['identity', 'Identity'], ['logit', 'Logit'], ['probit', 'Probit'], ['log', 'Log'], ['reciprocal', 'Reciprocal'], ['cloglog', 'Comp LogLog'], ['inverse_squared', 'Inverse Square'], ['sqrt', 'Square Root']];
  const DEFAULT_LINK = { normal: 'identity', binomial: 'logit', poisson: 'log', gamma: 'log', invgauss: 'log', negbin: 'log', tweedie: 'log' };
  // Generalized Estimating Equations: the working correlations, the covariances,
  // the families whose scale is 1 unless it is estimated
  const CORRS = [['independence', 'Independence'], ['exchangeable', 'Exchangeable'], ['ar1', 'Autoregressive AR(1)'], ['nested', 'Nested'], ['unstructured', 'Unstructured']];
  const CORR_LABEL = Object.fromEntries(CORRS);
  const COVS = [['robust', 'Robust (sandwich)'], ['naive', 'Naive (model-based)'], ['bias_reduced', 'Bias-reduced (Mancl–DeRouen)']];
  const UNIT_SCALE = new Set(['binomial', 'poisson', 'negbin']);
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
      corr: o0.workCorr || 'exchangeable', cov: o0.geeCov || 'robust', scale: o0.geeScale || (UNIT_SCALE.has(o0.dist || 'normal') ? 'fixed' : 'estimated'),
      scaleValue: o0.geeScaleValue ?? 1, nbAlpha: o0.nbAlpha ?? 1, varPower: o0.varPower ?? 1.5, tau: o0.qrTau ?? 0.5,
    };
    const msg = (s) => api.message(s);
    const list = el('ul', { class: 'sm-role-list sm-fm-effects', role: 'listbox', 'aria-label': 'Model effects', 'aria-multiselectable': 'true', tabindex: '0', dataset: { hint: 'Select columns, then Add, Cross, Nest or a macro; or drag columns here' } });
    const renderList = () => {
      list.replaceChildren();
      list.classList.toggle('is-empty', !effects.length);
      effects.forEach((e, i) => {
        // draggable: along the list to reorder it, out of the dialog's places to take it out, a main effect onto a role
        const li = el('li', { role: 'option', draggable: 'true', dataset: { i: String(i) }, 'aria-selected': String(sel.has(i)) },
          el('span', { class: 'sm-colname', text: effectLabel(e) + (e.random ? '&Random' : '') }));
        if (sel.has(i)) li.classList.add('is-selected');
        list.append(li);
      });
    };
    const mark = { anchor: null };
    list.addEventListener('click', (ev) => {
      const li = ev.target.closest('li');
      if (!li) return;
      // a click, ctrl/⌘ for one more, shift for a sweep (the list's order)
      SM.util.listClick(ev, +li.dataset.i, effects.map((_, k) => k), sel, mark);
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
    // columns dragged here from the list on the left go in as main effects, as Add puts them
    SM.launch.acceptColumns(list, t, (cols) => { msg(''); add(cols.map((c) => ({ cols: [c], nest: [], random: false }))); });
    // An effect dragged along the list goes to the position of the effect it
    // is dropped on (the end, dropped beside them); dragged anywhere else in
    // the dialog it is taken out, and a main effect dropped on a role moves
    // there as its column. A column dragged here from a role leaves the role
    // and comes in as a main effect, in place of the effect it is dropped on.
    SM.launch.place(list, {
      label: 'Model Effects',
      item: (n) => n.closest('li[data-i]'),
      key: (li) => li.dataset.i,
      take: (li) => {
        const e = effects[+li.dataset.i];
        if (!e) return null;
        const main = e.cols.length === 1 && !(e.nest && e.nest.length);
        return { cols: main ? [e.cols[0]] : [], text: effectLabel(e) + (e.random ? '&Random' : ''), effect: e,
          remove: () => { effects = effects.filter((x) => x !== e); sel.clear(); renderList(); } };
      },
      refuses: (m) => (m.cols.length === 1 ? null : 'not a column'),
      drop: ({ m, at, same }) => {
        msg('');
        if (same) {
          const from = effects.indexOf(m.effect), to = at == null ? effects.length - 1 : +at;
          if (from < 0 || to < 0 || to >= effects.length || from === to) return;
          effects.splice(from, 1);
          effects.splice(to, 0, m.effect);
          sel.clear();
          renderList();
          return;
        }
        const e = { cols: [m.cols[0]], nest: [], random: false };
        const target = at == null ? null : effects[+at] || null;
        m.remove();
        const k = effectKey(e);
        const dup = effects.find((x) => effectKey(x) === k);
        if (dup && (!target || target === dup)) { if (!target) msg('Those effects are in the model already.'); sel.clear(); renderList(); return; }
        if (dup) effects = effects.filter((x) => x !== dup);
        if (target && effects.includes(target)) effects.splice(effects.indexOf(target), 1, e);
        else effects.push(e);
        sel.clear();
        renderList();
      },
    });
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
    const dist = mkSel(st.pers === 'gee' ? GEE_DISTS : st.pers === 'genreg' ? GR_DISTS : DISTS, st.dist, 'Distribution');
    const link = mkSel(LINKS, st.link || DEFAULT_LINK[st.dist], 'Link Function');
    const distr = mkSel([['logit', 'Logit'], ['probit', 'Probit']], st.distr, 'Link');
    const target = el('select', { 'aria-label': 'Target Level' });
    const lab = (text, input, cls = '') => el('label', { class: `sm-fm-opt ${cls}` }, el('span', { text }), input);
    const lEmph = lab('Emphasis', emph), lDist = lab('Distribution', dist), lLink = lab('Link Function', link), lDistr = lab('Link', distr), lTarget = lab('Target Level', target);
    // Generalized Estimating Equations
    const numIn = (label, value) => { const i = el('input', { type: 'text', inputmode: 'decimal', size: 4, 'aria-label': label, class: 'sm-fm-num' }); i.value = String(value); return i; };
    const corrSel = mkSel(CORRS, st.corr, 'Working Correlation');
    const covSel = mkSel(COVS, st.cov, 'Covariance');
    const scaleSel = mkSel([['estimated', 'Estimated'], ['fixed', 'Fixed at']], st.scale, 'Scale');
    const scaleVal = numIn('Fixed scale', st.scaleValue);
    const nbAlpha = numIn('Negative binomial alpha', st.nbAlpha);
    const varPower = numIn('Tweedie power', st.varPower);
    const lCorr = lab('Working Correlation', corrSel), lCov = lab('Covariance', covSel);
    const lScale = el('label', { class: 'sm-fm-opt' }, el('span', { text: 'Scale' }), scaleSel, scaleVal);
    const lAlpha = lab('α', nbAlpha), lPower = lab('Power', varPower);
    // Quantile Regression: the quantile τ (the rest of its options are in the report's Model Launch)
    const tauIn = numIn('Quantile', st.tau);
    const lTau = lab('Quantile τ', tauIn);
    const num = (i, dflt) => { const v = Number(String(i.value).replace(',', '.')); return Number.isFinite(v) ? v : dflt; };
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
      lDist.hidden = !(p === 'glm' || p === 'genreg' || p === 'gee');
      const gd = p === 'genreg' ? GR_DISTS : p === 'gee' ? GEE_DISTS : DISTS;
      if ([...dist.options].map((x) => x.value).join() !== gd.map((x) => x[0]).join()) { const v = dist.value; dist.replaceChildren(...gd.map(([v2, l]) => el('option', { value: v2, text: l }))); dist.value = gd.some((x) => x[0] === v) ? v : 'normal'; }
      lLink.hidden = !(p === 'glm' || p === 'gee');
      lDistr.hidden = p !== 'ordinal';
      lTarget.hidden = !(y && y.isCategorical && ['nominal', 'glm', 'genreg', 'gee'].includes(p));
      const gee = p === 'gee';
      lCorr.hidden = lCov.hidden = lScale.hidden = !gee;
      scaleVal.hidden = scaleSel.value !== 'fixed';
      lAlpha.hidden = !(gee && dist.value === 'negbin');
      lPower.hidden = !(gee && dist.value === 'tweedie');
      lTau.hidden = p !== 'quantreg';
      fillTarget();
      // the roles of a personality: Offset for the GLM and GEE, Subject, Time and Subgroup for GEE,
      // Endogenous and Instruments for Instrumental Variables (validate() says when one is empty)
      api.showRole('offset', p === 'glm' || gee);
      for (const k of ['subject', 'time', 'subgroup']) api.showRole(k, gee);
      for (const k of ['endog', 'instruments']) api.showRole(k, p === 'iv');
    };
    pers.addEventListener('change', () => { st.userPers = true; sync(); });
    dist.addEventListener('change', () => { link.value = DEFAULT_LINK[dist.value] || 'identity'; scaleSel.value = UNIT_SCALE.has(dist.value) ? 'fixed' : 'estimated'; sync(); });
    scaleSel.addEventListener('change', () => sync());
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
      el('div', { class: 'sm-fm-pers' }, lab('Personality', pers), lEmph, lDist, lAlpha, lPower, lLink, lDistr, lTarget, lCorr, lCov, lScale, lTau,
        typeof KvotInfo !== 'undefined' ? KvotInfo.slot('p:fitmodel:personality') : null),
      el('h4', null, 'Construct Model Effects', typeof KvotInfo !== 'undefined' ? KvotInfo.slot('p:fitmodel:effects') : null),
      el('div', { class: 'sm-fm-effbox' }, tools, list));
    renderList();
    sync();
    // What the part's fields do: the personality's options as they show now, then the model effects.
    const help = () => {
      const p = pers.value;
      const on = (l) => !l.hidden;
      const out = [['Personality', 'How the model is fitted and reported. It follows the Y until you choose one: Standard Least Squares for a continuous Y, Nominal or Ordinal Logistic for a nominal or ordinal one. The (i) beside it describes each.']];
      if (on(lEmph)) out.push(['Emphasis', 'Which outlines open at first: Effect Leverage (the leverage plots and Effect Details, the default), Effect Screening (Sorted Parameter Estimates and the Prediction Profiler, Effect Details closed) or Minimal Report (the tables, without the plots). The red triangle turns each part on or off later.']);
      if (on(lDist)) {
        out.push(['Distribution', p === 'genreg' ? 'Normal, Binomial (a proportion, or a two-level Y, which is always binomial) or Poisson (counts); Model Launch in the report changes it.'
          : `The distribution of the response: Normal; Binomial (a two-level Y or a proportion${p === 'glm' ? ', or events and trials as two Y columns' : ''}); Poisson for counts; Gamma and Inverse Gaussian for positive values; Negative Binomial for counts that vary more than a Poisson's (${p === 'gee' ? 'its α fixed below' : 'its α estimated, statsmodels\' NB2 model, with the log link and no Weight or Freq'})${p === 'gee' ? '; Tweedie, for values of 0 or more with exact zeros' : ''}.`]);
      }
      if (on(lAlpha)) out.push(['α', 'The negative binomial\'s dispersion, fixed: the variance is μ + αμ². Above 0, 1 by default; GEE does not estimate it.']);
      if (on(lPower)) out.push(['Power', 'The Tweedie variance power p, the variance proportional to μ^p: from 1 (Poisson) to 3 (inverse Gaussian); between 1 and 2 the compound Poisson-gamma, for values of 0 or more with exact zeros. 1.5 by default.']);
      if (on(lLink)) out.push(['Link Function', 'The function of the mean that is linear in the effects. A change of distribution picks its usual link: Identity for the normal, Logit for the binomial, Log for the others. A log link makes the effects multiplicative (rate or mean ratios).']);
      if (on(lDistr)) out.push(['Link', 'The link of the cumulative probabilities P(Y ≤ level): Logit, the proportional odds model (the default, as JMP), or Probit (statsmodels\' OrderedModel).']);
      if (on(lTarget)) out.push(['Target Level', `For a two-level Y, the level whose probability is modeled (the event); the first level by default.${p === 'nominal' ? ' With more levels Nominal Logistic models each level against the last and does not use it.' : ''}`]);
      if (on(lCorr)) out.push(['Working Correlation', 'The correlation GEE assumes among a subject\'s rows: Independence; Exchangeable (one correlation for every pair, the default); AR(1) (α to the power of the distance; needs Time); Nested (needs Subgroup); Unstructured (one for each pair of times; needs Time). The estimates stay consistent when it is wrong, and the robust standard errors allow for that; a closer one gives more precise estimates.']);
      if (on(lCov)) out.push(['Covariance', 'The standard errors: Robust, the sandwich, right even when the working correlation is not (the default); Naive, from the model, right only when the working correlation is; Bias-reduced, Mancl and DeRouen\'s correction of the sandwich, which is too small with few subjects.']);
      if (on(lScale)) out.push(['Scale', 'The scale φ of the variance: Estimated, Pearson χ²/(N − p), or Fixed at the value beside it (1 by default). A change of distribution picks Fixed for the binomial, Poisson and negative binomial, Estimated for the others.']);
      if (on(lTau)) out.push(['Quantile τ', 'The quantile of Y to fit, strictly between 0 and 1: 0.5 is the median, 0.9 the upper tenth. Model Launch in the report changes it.']);
      out.push(
        ['Model effects', 'The list of the model\'s effects: columns dragged onto it from the list on the left go in as main effects, as Add puts them, and so do columns dragged from a role (they leave it; dropped on an effect, one takes its place); click one to select it (ctrl/⌘ adds or takes away one, shift selects a range), for Cross, Nest, Attributes and Remove; a double click removes it. Drag an effect up or down the list to change the order, a main effect onto a role to move its column there, or an effect anywhere else in the dialog to take it out. A crossing is A*B, a nested effect B[A], a random one ends in &Random.'],
        ['Add', 'Each selected column (in the list on the left) as a main effect.'],
        ['Cross', 'The selected columns crossed into one interaction, A*B; each selected effect of the list crossed with the selected columns; or two or more selected effects crossed together. A continuous column crossed with itself is its square. Continuous columns in crossings are centred at their means, as JMP\'s Center Polynomials.'],
        ['Nest', 'Nests the selected effects within the selected columns: B[A], the levels of B within each level of A.'],
        ['Macros', 'A whole model from the selected columns: Full Factorial (every crossing), Factorial to Degree (the crossings up to Degree), Factorial Sorted (every crossing, by degree), Response Surface (the main effects, the two-way crossings and the squares of the continuous columns), Polynomial to Degree (every power and crossing up to Degree).'],
        ['Degree', 'The degree of Factorial to Degree and Polynomial to Degree, 1 to 6; 2 by default.'],
        ['Attributes', 'Random Effect: marks the selected effects random, their levels a sample from a larger population, estimated as a variance component. Standard Least Squares then fits by REML, as Mixed Model (which needs one); the other personalities take fixed effects only and say so.'],
        ['Remove', 'Takes the selected effects out of the model (so do Delete and a double click).'],
        ['No Intercept', 'Fits the model without its constant term, so that the prediction is 0 where every effect is 0. Generalized Regression keeps its intercept, which is never penalized.'],
      );
      return out;
    };
    return {
      el: rootEl,
      help,
      helpHeading: 'Personality and model effects',
      read() {
        const p = pers.value;
        const gee = p === 'gee' ? { workCorr: corrSel.value, geeCov: covSel.value, geeScale: scaleSel.value, geeScaleValue: num(scaleVal, 1), nbAlpha: num(nbAlpha, 1), varPower: num(varPower, 1.5) } : {};
        const qr = p === 'quantreg' ? { qrTau: num(tauIn, NaN) } : {};
        return {
          effects: effects.map(serialize),
          options: { personality: p, emphasis: emph.value, dist: dist.value, link: p === 'glm' || p === 'gee' ? link.value : null, noIntercept: noInt.checked, target: target.value === '' ? null : target.value, distr: distr.value, ...gee, ...qr },
        };
      },
      recall(saved) {
        const x = (saved && saved.extra) || {};
        effects = effectsFrom(x.effects, t, true);
        const o = saved.options || {};
        if (o.personality) { pers.value = o.personality; st.userPers = true; }
        if (o.emphasis) emph.value = o.emphasis;
        sync();   // the distributions of the personality, before the saved one is chosen
        if (o.dist) dist.value = o.dist;
        if (o.link) link.value = o.link;
        if (o.distr) distr.value = o.distr;
        if (o.workCorr) corrSel.value = o.workCorr;
        if (o.geeCov) covSel.value = o.geeCov;
        if (o.geeScale) scaleSel.value = o.geeScale;
        if (o.geeScaleValue != null) scaleVal.value = String(o.geeScaleValue);
        if (o.nbAlpha != null) nbAlpha.value = String(o.nbAlpha);
        if (o.varPower != null) varPower.value = String(o.varPower);
        if (o.qrTau != null) tauIn.value = String(o.qrTau);
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
    if (['standard', 'stepwise', 'mixed', 'manova', 'iv', 'quantreg'].includes(p) && !cont) return `${PERS_LABEL[p]} needs continuous Y columns: change the personality, or the modeling type of ${ys.find((c) => c.isCategorical).name}.`;
    if (p === 'iv' || p === 'quantreg') {
      if (!effects.length) return `${PERS_LABEL[p]} needs model effects: select columns and press Add.`;
      if (effects.some((e) => e.random)) return `${PERS_LABEL[p]} takes fixed effects only: take the Random Effect attribute off.`;
      if ((spec.roles.weight || []).length || (spec.roles.freq || []).length) return `${PERS_LABEL[p]}: statsmodels' ${p === 'iv' ? 'IV2SLS' : 'QuantReg'} takes no weights; remove Weight and Freq.`;
    }
    if (p === 'quantreg' && !(Number(o.qrTau ?? 0.5) > 0 && Number(o.qrTau ?? 0.5) < 1)) return 'The quantile τ must lie strictly between 0 and 1 (0.5 is the median).';
    if (p === 'iv') {
      const en = spec.roles.endog || [], ins = spec.roles.instruments || [];
      const name = (id) => (table.col(id) || { name: id }).name;
      if (!en.length) return 'Instrumental Variables need Endogenous columns: the model effects that are correlated with the error.';
      if (!ins.length) return 'Instrumental Variables need Instruments: columns that move the endogenous ones but have no effect of their own on Y.';
      const inModel = new Set(effects.flatMap((e) => [...(e.cols || []), ...(e.nest || [])]));
      for (const id of en) {
        if (yIds.has(id)) return `${name(id)} is the Y: it cannot also be Endogenous.`;
        if (!inModel.has(id)) return `${name(id)} is Endogenous but not in the model effects: add it to the model, or take it out of Endogenous.`;
      }
      for (const id of ins) {
        if (yIds.has(id) || en.includes(id)) return `${name(id)} is the Y or Endogenous: it cannot also be an Instrument.`;
        if (inModel.has(id)) return `${name(id)} is an Instrument and a model effect: an instrument stays out of the model (the exogenous effects instrument themselves).`;
      }
      // the order condition for main effects (Python checks the crossings): a categorical column is one less than its levels
      const width = (id) => { const c = table.col(id); return c && c.isCategorical ? Math.max(1, table.levels(c).length - 1) : 1; };
      const need = en.reduce((a, id) => a + width(id), 0), have = ins.reduce((a, id) => a + width(id), 0);
      if (have < need) return `The model is not identified: the endogenous columns need at least ${need} instrument column${need > 1 ? 's' : ''}, and the instruments give ${have}.`;
    }
    if (p === 'manova' && ys.length < 2) return 'MANOVA needs two or more Y columns.';
    if ((p === 'nominal' || p === 'ordinal') && ys.some((c) => !c.isCategorical)) return `${PERS_LABEL[p]} needs a nominal or ordinal Y.`;
    if (p === 'glm' && o.dist !== 'binomial' && ys.some((c) => c.isCategorical)) return 'A categorical Y takes the binomial distribution (or Nominal Logistic).';
    if (p === 'mixed' && !effects.some((e) => e.random)) return 'The mixed model needs a random effect: select an effect and choose Attributes > Random Effect.';
    if ((p === 'stepwise' || p === 'genreg') && !effects.some((e) => !e.random)) return `${PERS_LABEL[p]} needs model effects.`;
    if ((p === 'stepwise' || p === 'genreg' || p === 'manova') && effects.some((e) => e.random)) return `${PERS_LABEL[p]} takes fixed effects only.`;
    // (these fitted the fixed effects alone, leaving the random ones out without a word)
    if ((p === 'glm' || p === 'nominal' || p === 'ordinal') && effects.some((e) => e.random)) return `${PERS_LABEL[p]} takes fixed effects only: take the Random Effect attribute off, or fit random effects with Standard Least Squares or Mixed Model.`;
    const w = ((spec.roles.weight || []).length || (spec.roles.freq || []).length);
    if ((p === 'mixed' || p === 'manova') && w) return `${PERS_LABEL[p]}: statsmodels takes no weights here; remove Weight and Freq.`;
    if (p === 'gee') {
      const one = (k) => (spec.roles[k] || [])[0] || null;
      if (!one('subject')) return 'Generalized Estimating Equations need a Subject: the column that says which rows belong together (the subjects, or clusters).';
      if (o.dist !== 'binomial' && ys.some((c) => c.isCategorical)) return 'A categorical Y takes the binomial distribution (two levels).';
      if (effects.some((e) => e.random)) return 'Generalized Estimating Equations model the correlation within a subject by the working correlation: take the Random Effect attribute off the effects.';
      if (w) return 'Generalized Estimating Equations: statsmodels\' GEE weights are case weights that several working correlations ignore; remove Weight and Freq.';
      const roleIds = ['subject', 'time', 'subgroup'].map(one).filter(Boolean);
      if (new Set(roleIds).size < roleIds.length) return 'Subject, Time and Subgroup must be different columns.';
      if (ys.some((c) => roleIds.includes(c.id))) return 'A Y column is also the Subject, Time or Subgroup.';
      if ((o.workCorr === 'ar1' || o.workCorr === 'unstructured') && !one('time')) return `The ${CORR_LABEL[o.workCorr]} working correlation needs a Time column: the order of the rows within a subject.`;
      if (o.workCorr === 'nested' && !one('subgroup')) return 'The Nested working correlation needs a Subgroup column: a grouping within the subjects.';
      if (o.geeScale === 'fixed' && !(o.geeScaleValue > 0)) return 'A fixed scale must be above zero.';
      if (o.dist === 'negbin' && !(o.nbAlpha > 0)) return 'The negative binomial α must be above zero.';
      if (o.dist === 'tweedie' && !(o.varPower >= 1 && o.varPower <= 3)) return 'The Tweedie power must lie between 1 and 3.';
    }
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

  // A graph with its Python code under it, as one item of a row. The code of
  // each graph (plot_code) comes from the function that fits the model: the
  // model fitted as the report's code fits it, then the graph drawn with
  // matplotlib from the rows.
  const withCode = (graph, code) => (code ? el('div', { class: 'sm-fm-plotcode' }, graph, code) : graph);
  const codeOf = (res, key) => (res && res.plot_code ? res.plot_code[key] : null);

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
  function actualByPredicted(ctx, parent, d, whole, yname, info = 'p:fitmodel:leverage', title = 'Actual by Predicted Plot', code = null) {
    const P = pal();
    const ob = ctx.outline(title, { parent, key: 'actpred', info });
    const [lo, hi] = extent(d.predicted, d.actual);
    const lines = [lineTrace([lo, hi], [lo, hi], P.fit, 'solid', 1.4)];
    if (whole && whole.mean != null) lines.push(lineTrace([lo, hi], [whole.mean, whole.mean], P.mean, 'dot', 1.2));
    if (whole && whole.curve) lines.push(lineTrace(whole.curve.x, whole.curve.lower, P.fit, 'dash', 1), lineTrace(whole.curve.x, whole.curve.upper, P.fit, 'dash', 1));
    const sub = whole ? ` P${pText(whole.p)} RSq=${whole.rsq != null ? whole.rsq.toFixed(2) : '.'} RMSE=${fmt(whole.rmse, { sig: 5 })}` : '';
    ob.add(rowPlot(ctx, { x: d.predicted, y: d.actual, rows: d.rows, xTitle: `${yname} Predicted${sub}`, yTitle: `${yname} Actual`, lines, width: 400, height: 320, title: `${yname} actual by predicted` }), ctx.code(code));
    return ob;
  }

  /* JMP's Regression Plot: with one continuous factor (and at most one
     categorical one) the data and the fitted curve, one per level, with the
     confidence band of the mean. The curves are the profiler's traces. */
  async function regressionPlot(ctx, parent, { kind, payload, factors, d, yname, scope, code = null }) {
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
      { width: W(g ? 440 : 400), height: 320, title: `${yname} regression plot` }), ctx.code(code));
    return ob;
  }

  function leveragePlot(ctx, lev, yname, robust = false) {
    const P = pal();
    const lines = [lineTrace(lev.line.x, lev.line.y, P.fit, 'solid', 1.4), lineTrace(lev.line.x, [lev.mean, lev.mean], P.mean, 'dot', 1.2)];
    if (lev.curve) lines.push(lineTrace(lev.curve.x, lev.curve.lower, P.fit, 'dash', 1), lineTrace(lev.curve.x, lev.curve.upper, P.fit, 'dash', 1));
    return rowPlot(ctx, { x: lev.x, y: lev.y, rows: lev.rows, xTitle: `${lev.effect} Leverage, P${pText(lev.p)}${robust ? ' (usual F test)' : ''}`, yTitle: `${yname} Leverage Residuals`, lines, width: 340, height: 290, title: `${lev.effect} leverage plot` });
  }

  function residualPlots(ctx, parent, d, yname, o, emph, lim, codes = {}) {
    const P = pal();
    if (o('plotResidPred', emph !== 'minimal')) {
      ctx.outline('Residual by Predicted Plot', { parent, key: 'residpred' }).add(rowPlot(ctx, { x: d.predicted, y: d.residual, rows: d.rows, xTitle: `${yname} Predicted`, yTitle: `${yname} Residual`, hlines: [{ y: 0, color: P.mean }], title: `${yname} residual by predicted` }), ctx.code(codes.residpred));
    }
    if (o('plotResidRow', false)) {
      ctx.outline('Residual by Row Plot', { parent, key: 'residrow' }).add(rowPlot(ctx, { x: d.rows.map((r) => r + 1), y: d.residual, rows: d.rows, xTitle: 'Row Number', yTitle: `${yname} Residual`, hlines: [{ y: 0, color: P.mean }], width: 460, title: `${yname} residual by row` }), ctx.code(codes.residrow));
    }
    if (o('plotStudent', false) && d.externally) {
      const hl = [{ y: 0, color: P.mean }];
      if (lim && lim.individual) hl.push({ y: lim.individual, color: P.muted, dash: 'dash' }, { y: -lim.individual, color: P.muted, dash: 'dash' });
      if (lim && lim.bonferroni) hl.push({ y: lim.bonferroni, color: P.fit }, { y: -lim.bonferroni, color: P.fit });
      const ob = ctx.outline('Studentized Residuals', { parent, key: 'student' });
      ob.add(rowPlot(ctx, { x: d.rows.map((r) => r + 1), y: d.externally, rows: d.rows, xTitle: 'Row Number', yTitle: 'Externally Studentized Residuals', hlines: hl, width: 460, title: `${yname} studentized residuals` }), ctx.code(codes.student),
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
      ctx.outline('Residual Normal Quantile Plot', { parent, key: 'residqq' }).add(rowPlot(ctx, { x: z, y: yv, rows: order.map((k) => d.rows[k]), xTitle: 'Normal Quantile', yTitle: `${yname} Residual`, lines: [lineTrace([zl, zh], [m + sd * zl, m + sd * zh], P.fit)], width: 360, title: `${yname} residual normal quantile plot` }), ctx.code(codes.residqq));
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
      fields: lsm.labels.map((l, i) => ({ key: `c${i}`, label: l, type: 'number', value: i === 0 ? 1 : i === 1 ? -1 : 0, helpLabel: 'The weight of each level',
        help: 'The contrast is the sum of the weights times the least squares means, tested with t against 0. Weights that sum to zero compare levels: 1, −1, 0 the first two levels, 1, 1, −2 the first two against the third; empty is 0. Each OK adds a contrast; the joint F test covers all of them.' })),
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
     The shared profiler (SM.profiler, fitmodel.profile from profile.expose):
     one small plot per factor and response, the prediction with its
     confidence interval as the factor varies and the others stay at their
     current values; desirability, Maximize Desirability and variable
     importance in its red triangle. Several sources (the responses of a
     Standard Least Squares report) go as one, so that desirability can
     weigh them together. The current values keep their earlier option. */
  async function profiler(ctx, parent, { sources, scope, title = 'Prediction Profiler', key = 'profiler', option = 'profiler' }) {
    const first = sources[0];
    const payload = sources.length > 1
      ? { ...first.payload, kind: first.kind, ys: sources.map((s) => ({ y: s.payload.y, robust: s.payload.robust || null })) }
      : { ...first.payload, kind: first.kind };
    return SM.profiler.render(ctx, parent, {
      sources: [{ fn: 'fitmodel.profile', payload }], scope, title, key, option, info: 'p:fitmodel:profiler',
      stateKey: `${option === 'profiler' ? 'prof' : option}:${ctx.byLabel || ''}`,
      note: 'Drag the red dashed line of a factor, click in its plot, or type its value. Dotted: the confidence interval of the prediction.',
    });
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
    ob.add(withCode(ctx.plot(traces, layout, { width: W(side), height: side, title: 'interaction plots', select: false }), ctx.code(r.plot_code)),
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
    ob.add(ctx.row(withCode(ctx.plot(traces, { xaxis: { title: { text: 'λ' } }, yaxis: { title: { text: 'SSE' } }, shapes }, { width: W(360), height: 260, title: `${y.name} Box-Cox` }), ctx.code(r.plot_code)),
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
      await profiler(ctx, ctx.top, { sources: all.map(({ y }) => { const rob = robustOf(ctx, y.id); return { kind: 'ls', payload: { ...M.base, y: y.name, ...(rob ? { robust: rob } : {}) } }; }), scope: null, title: 'Prediction Profiler', key: 'groupprofiler', option: 'groupProfiler' });
    }
  }

  async function standardY(ctx, M, y, parent, st) {
    const sc = y.id;
    const o = (k, d) => ctx.opt(k, d, sc);
    const emph = ctx.opt('emphasis', 'leverage');
    const payload = { ...M.base, y: y.name };
    const rob = robustOf(ctx, sc);
    const rpay = rob ? { ...payload, robust: rob } : payload;   // the profilers' intervals follow Robust Standard Errors
    const res = await ctx.call('fitmodel.ls', { ...rpay, alpha: ctx.alpha, vif: true, leverage: true, dw: o('dw', false), sequential: o('sequential', false), corr: o('corr', false), ccpr: !!o('ccpr', false) });
    st.menu = () => lsMenu(ctx, y, res);
    const tc = res.tcrit;
    if (o('effectSummary', true) && res.effect_summary.length) effectSummary(ctx, parent, res.effect_summary, { scope: sc });
    const top = [];
    if (o('plotRegression', emph !== 'minimal')) {
      const rp = await regressionPlot(ctx, parent, { kind: 'ls', payload: rpay, factors: res.factors, d: res.diag, yname: y.name, scope: sc, code: codeOf(res, 'regression') });
      if (rp) top.push(rp.el);
    }
    if (o('plotActual', emph !== 'minimal')) top.push(actualByPredicted(ctx, parent, res.diag, res.whole, y.name, undefined, undefined, codeOf(res, 'actpred')).el);
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
      ctx.outline('Parameter Estimates', { parent, key: 'estimates', info: res.robust ? 'p:fitmodel:robust' : null }).add(ctx.rt({ columns: cols, rows: res.estimates.rows },
        { key: 'estimates', caption: res.robust ? `Robust standard errors: ${res.robust.label}; t tests on ${fmt(res.robust.df)} DF` : undefined }));
    }
    if (o('effectTests', true) && res.effect_tests.rows.length) {
      const tbl = ctx.rt(res.effect_tests, { key: 'efftests', caption: res.robust ? `Wald F tests with the robust covariance (${res.robust.label})` : undefined });
      ctx.outline('Effect Tests', { parent, key: 'efftests', info: 'p:fitmodel:efftests' }).add(tbl, effectSizeNote(ctx, tbl, res.effect_tests),
        res.robust && res.robust.wald_f != null ? ctx.note(`Whole model, robust Wald test: F = ${fmt(res.robust.wald_f, { sig: 5 })} on ${fmt(res.robust.wald_df)} and ${fmt(res.robust.df)} DF, p${pText(res.robust.wald_p)}. (Analysis of Variance above is the usual F test.)`) : null);
    }
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
    residualPlots(ctx, parent, res.diag, y.name, o, emph, res.diag.limits, res.plot_code || {});
    if (o('press', false)) ctx.outline('Press', { parent, key: 'press' }).add(ctx.kv([['Press', res.press.press], ['Press RMSE', res.press.rmse]]), ctx.note('The sum of squared leave-one-out prediction errors, Σ(eᵢ/(1 − hᵢ))².'));
    if (o('dw', false) && res.dw) {
      ctx.outline('Durbin-Watson', { parent, key: 'dw' }).add(ctx.rt({ columns: [{ key: 'dw', label: 'Durbin-Watson' }, { key: 'n', label: 'Number of Obs.', fmt: 'int' }, { key: 'autocorr', label: 'AutoCorrelation', digits: 4 }, { key: 'p', label: 'Prob<DW', fmt: 'p' }], rows: [res.dw] }, { sortable: false, key: 'dw' }),
        ctx.note('Prob<DW is the exact p-value for positive autocorrelation of the residuals in row order (Imhof\'s method; up to 800 rows).'));
    }
    if (RD.some(([k]) => o(`rd:${k}`, false))) await regDiagnostics(ctx, parent, payload, res, sc);
    if (RR.some(([k]) => o(k, false))) await recursiveReport(ctx, parent, payload, y, sc);
    if (o('influence', false)) influencePlot(ctx, parent, res, y, sc);
    if (o('ccpr', false) && res.ccpr) ccprPlots(ctx, parent, res, y, sc);
    if (o('boxcox', false)) await boxCox(ctx, M, parent, payload, y, sc);
    if (o('profiler', emph === 'screening')) await profiler(ctx, parent, { sources: [{ kind: 'ls', payload: rpay }], scope: sc });
    if (o('contour', false)) await contourProfiler(ctx, parent, { kind: 'ls', payload, factors: res.factors, scope: sc });
    if (o('interaction', false)) await interactionPlots(ctx, parent, { kind: 'ls', payload, scope: sc });
    tail(ctx, parent, res);
    return res;
  }

  /* The definitions of the Effect Tests' optional effect-size columns (right click, Columns),
     shown while one of them is. */
  function effectSizeNote(ctx, tbl, et) {
    if (!(et.columns || []).some((c) => c.key === 'pes')) return null;
    const note = ctx.note(`Partial η² = SS/(SS + SSE), the effect's share of the variation the other effects leave (Cohen 1973). Partial ω² = (SS − DF·MSE)/(SS + (N − DF)·MSE), the same share estimated with less bias (Keren and Lewis 1979; Olejnik and Algina 2003); it is negative when F < 1. SS is the effect's sum of squares above, N = ${fmt(et.n)} the observations. JMP's Effect Tests have neither.`);
    const sync = () => { note.hidden = !tbl._rt.columns.some((c) => c.key === 'pes' || c.key === 'pos'); };
    sync();
    if (typeof MutationObserver !== 'undefined' && tbl.tHead) new MutationObserver(sync).observe(tbl.tHead, { childList: true });
    return note;
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
      withCode(ctx.plot(tr, { yaxis: { autorange: 'reversed', type: 'category' }, xaxis: { title: { text: 't Ratio' } }, shapes, margin: { l: 120, r: 12, t: 8, b: 40 } }, { width: W(340), height: h, title: 'sorted t ratios', select: false }), ctx.code(codeOf(res, 'sorted')))));
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
      if (lev && o('plotLeverage', emph === 'leverage')) parts.push(withCode(leveragePlot(ctx, lev, y.name, !!res.robust), ctx.code((codeOf(res, 'leverage') || {})[e.label])));
      if (lsm && o(`lsmTable:${e.label}`, true)) parts.push(lsmeansTable(ctx, M, lsm));
      if (parts.length) eo.add(ctx.row(...parts));
      if (lsm && o(`lsmPlot:${e.label}`, false)) eo.add(lsmeansPlot(ctx, M, lsm, res.tcrit, y.name, e.label), ctx.code((codeOf(res, 'lsmeans') || {})[e.label]));
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
      { label: 'Robust Standard Errors', submenu: () => robustMenu(ctx, y, 'ls') },
      { label: 'Factor Profiling', submenu: () => [c('Profiler', 'profiler', emph === 'screening'), c('Interaction Plots', 'interaction', false), c('Contour Profiler', 'contour', false), c('Box Cox Y Transformation', 'boxcox', false)] },
      { label: 'Row Diagnostics', submenu: () => [c('Plot Regression', 'plotRegression', emph !== 'minimal'), c('Plot Actual by Predicted', 'plotActual', emph !== 'minimal'), c('Plot Effect Leverage', 'plotLeverage', emph === 'leverage'), c('Plot Residual by Predicted', 'plotResidPred', emph !== 'minimal'),
        c('Plot Residual by Row', 'plotResidRow', false), c('Plot Studentized Residuals', 'plotStudent', false), c('Plot Residual by Normal Quantiles', 'plotResidQQ', false), { separator: true }, c('Press', 'press', false), c('Durbin-Watson Test', 'dw', false)] },
      { label: 'Regression Diagnostics', submenu: () => regDiagMenu(ctx, sc) },
      { label: 'Recursive and Rolling Regression', submenu: () => rrMenu(ctx, sc) },
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

  /* ---- Robust Standard Errors ---------------------------------------------------------------------
     The option (scoped by the response) is { type: 'HC0'..'HC3' }, { type:
     'HAC', maxlags } or { type: 'cluster', col: column id }; Python gets the
     cluster column by name. */
  function robustOf(ctx, sc) {
    const r = ctx.opt('robust', null, sc);
    if (!r || !r.type) return null;
    if (r.type === 'cluster') { const c = ctx.table.col(r.col); return c ? { type: 'cluster', cluster: c.name } : null; }
    if (r.type === 'HAC') return { type: 'HAC', maxlags: r.maxlags ?? null };
    return { type: r.type };
  }

  function robustMenu(ctx, y, kind) {
    const sc = y.id;
    const cur = ctx.opt('robust', null, sc);
    const t = cur && cur.type ? cur.type : 'none';
    const set = (v) => ctx.set('robust', v, sc);
    const hc = kind === 'glm' ? [['HC0', 'Sandwich (HC0)']] : [['HC0', 'HC0 (White)'], ['HC1', 'HC1'], ['HC2', 'HC2'], ['HC3', 'HC3']];
    const n = ctx.rows.length;
    return [
      { label: 'None', checked: t === 'none', action: () => set(null) },
      ...hc.map(([k, l]) => ({ label: l, checked: t === k, action: () => set({ type: k }) })),
      { label: 'Newey–West HAC…', checked: t === 'HAC', action: async () => {
        const v = await SM.ui.form({ title: 'Newey–West HAC', info: 'p:fitmodel:robust', lead: 'Heteroscedasticity- and autocorrelation-consistent standard errors, the rows taken in the order of the table (sort it by time first).',
          fields: [{ key: 'maxlags', label: 'Maximum lag', type: 'number', value: cur && cur.type === 'HAC' && cur.maxlags != null ? cur.maxlags : Math.floor(4 * (n / 100) ** (2 / 9)), hint: 'Newey and West\'s rule: 4 (n/100)^(2/9)',
            help: 'The largest lag of the autocorrelation the standard errors allow for, a whole number from 0 to n − 2, with Bartlett weights that fall with the lag (statsmodels\' HAC, no small-sample correction); 0 gives White\'s HC0. It starts at Newey and West\'s rule, 4(n/100)^(2/9) rounded down.' }],
          validate: (x) => (Number.isInteger(x.maxlags) && x.maxlags >= 0 && x.maxlags < n - 1 ? null : 'the lag must be a whole number from 0 to n − 2') });
        if (v) set({ type: 'HAC', maxlags: v.maxlags });
      } },
      { label: 'Cluster…', checked: t === 'cluster', action: async () => {
        const cols = ctx.table.columns.filter((c) => c.id !== y.id);
        if (!cols.length) { SM.ui.toast('The table has no other column to cluster by'); return; }
        const pick = cur && cur.type === 'cluster' && cols.some((c) => c.id === cur.col) ? cur.col : (cols.find((c) => c.isCategorical) || cols[0]).id;
        const v = await SM.ui.form({ title: 'Cluster-Robust Standard Errors', info: 'p:fitmodel:robust', lead: 'Rows with the same value of the column form a cluster: their errors may be correlated, the clusters are independent.',
          fields: [{ key: 'col', label: 'Cluster by', type: 'select', value: pick, choices: cols.map((c) => [c.id, c.name]),
            help: 'The column whose values make the clusters (a school, a firm, a subject): rows of one cluster may have correlated errors, the clusters are independent. The t tests use the clusters less one as their degrees of freedom, with the small-sample factor G/(G − 1)·(n − 1)/(n − p); a few clusters give unreliable standard errors.' }] });
        if (v) set({ type: 'cluster', col: v.col });
      } },
    ];
  }

  /* ---- Regression Diagnostics ---------------------------------------------------------------------- */
  const RD = [['bp', 'Breusch–Pagan Test'], ['white', 'White Test'], ['gq', 'Goldfeld–Quandt Test'], ['reset', 'Ramsey RESET Test'], ['hc', 'Harvey–Collier Test'],
    ['rainbow', 'Rainbow Test'], ['bg', 'Breusch–Godfrey Test'], ['jb', 'Jarque–Bera Test'], ['omni', 'Omnibus Normality Test']];

  function regDiagMenu(ctx, sc) {
    const c = (label, key) => ctx.check(label, key, sc, false);
    const t = (k) => c(RD.find((x) => x[0] === k)[1], `rd:${k}`);
    const allOn = RD.every(([k]) => ctx.opt(`rd:${k}`, false, sc));
    return [t('bp'), t('white'), t('gq'), { separator: true }, t('reset'), t('hc'), t('rainbow'), { separator: true }, t('bg'), { separator: true }, t('jb'), t('omni'),
      { separator: true },
      { label: allOn ? 'Remove All Tests' : 'All Tests', action: () => { for (const [k] of RD) ctx.set(`rd:${k}`, !allOn, sc, { rerun: false }); ctx.report.run(); } },
      { separator: true },
      c('Influence Plot', 'influence'), c('Component + Residual Plots', 'ccpr')];
  }

  async function regDiagnostics(ctx, parent, payload, res, sc) {
    const o = (k, d) => ctx.opt(k, d, sc);
    const on = RD.filter(([k]) => o(`rd:${k}`, false)).map(([k]) => k);
    const cfg = { reset_power: o('rd:resetPower', 3), bg_lags: o('rd:bgLags', null), gq_sort: o('rd:gqSort', 'predicted'), gq_drop: o('rd:gqDrop', 0),
      gq_alt: o('rd:gqAlt', 'increasing'), rainbow_frac: o('rd:rainbowFrac', 0.5), rainbow_order: o('rd:rainbowOrder', 'leverage'), hc_order: o('rd:hcOrder', 'row') };
    const r = await ctx.call('fitmodel.regdiag', { ...payload, tests: on, ...cfg });
    const ob = ctx.outline('Regression Diagnostics', { parent, key: 'regdiag', info: 'p:fitmodel:regdiag', menu: () => regDiagMenu(ctx, sc).slice(0, -3) });   // the tests, not the plots
    const conts = r.continuous || [];
    const sortChoices = (extra) => [...extra, ['row', 'Row order'], ['predicted', 'Predicted'], ...conts.map((n) => [n, n])].filter((x, i, a) => a.findIndex((y) => y[0] === x[0]) === i);
    const mkSel = (label, key, value, choices) => {
      const s = el('select', { 'aria-label': label }, ...choices.map(([v, l]) => el('option', { value: String(v), text: l })));
      s.value = String(value);
      s.addEventListener('change', () => { const v = s.value; ctx.set(key, /^-?\d+(\.\d+)?$/.test(v) && key !== 'rd:gqSort' && key !== 'rd:hcOrder' && key !== 'rd:rainbowOrder' ? Number(v) : v, sc); });
      return el('label', { class: 'sm-fm-opt' }, el('span', { text: label }), s);
    };
    const mkNum = (label, key, value, ok, placeholder) => {
      const i = el('input', { type: 'text', inputmode: 'decimal', size: 5, 'aria-label': label, class: 'sm-fm-num', placeholder: placeholder || null });
      i.value = value == null ? '' : String(value);
      i.addEventListener('change', () => { const t = i.value.trim(); if (t === '') { ctx.set(key, null, sc); return; } const v = Number(t.replace(',', '.')); if (ok(v)) ctx.set(key, v, sc); else i.value = value == null ? '' : String(value); });
      return el('label', { class: 'sm-fm-opt' }, el('span', { text: label }), i);
    };
    const controls = {
      gq: () => [mkSel('Sort by', 'rd:gqSort', cfg.gq_sort, sortChoices([])), mkSel('Leave out the middle', 'rd:gqDrop', cfg.gq_drop, [[0, 'nothing'], [0.1, '10%'], [0.2, '20%'], [0.25, '25%'], [0.33, 'a third']]),
        mkSel('Alternative', 'rd:gqAlt', cfg.gq_alt, [['increasing', 'Variance increasing'], ['decreasing', 'Variance decreasing'], ['two-sided', 'Two-sided']])],
      reset: () => [mkSel('Powers of the predicted', 'rd:resetPower', cfg.reset_power, [[2, '2'], [3, '2 and 3']])],
      hc: () => [mkSel('Order', 'rd:hcOrder', cfg.hc_order, sortChoices([]))],
      rainbow: () => [mkSel('Central rows by', 'rd:rainbowOrder', cfg.rainbow_order, sortChoices([['leverage', 'Leverage (Utts)']])),
        mkNum('Central fraction', 'rd:rainbowFrac', cfg.rainbow_frac, (v) => v >= 0.1 && v <= 0.9)],
      bg: () => [mkNum('Lags', 'rd:bgLags', cfg.bg_lags, (v) => Number.isInteger(v) && v >= 1, String(Math.min(10, Math.floor(r.n / 5))))],
    };
    for (const k of on) {
      const t = r.tests[k];
      if (!t) continue;
      const to = ctx.outline(t.title, { parent: ob, key: `rd:${k}`, menu: () => [{ label: 'Remove', action: () => ctx.set(`rd:${k}`, false, sc) }] });
      if (controls[k]) to.add(el('div', { class: 'sm-fm-controls', dataset: { noexport: '' } }, ...controls[k]()));
      if (t.error) to.add(ctx.warn(t.error));
      else to.add(ctx.rt(t.table, { sortable: false, key: `rd:${k}` }));
      if (t.note) to.add(ctx.note(t.note));
    }
    for (const n of r.notes || []) ob.add(ctx.note(n));
    ob.add(ctx.code(r.code));
  }

  /* The Influence Plot: each row's externally studentized residual against
     its leverage, the area of its bubble Cook's D; lines at ±2 and at 2p/n
     and 3p/n. */
  function influencePlot(ctx, parent, res, y, sc) {
    const P = pal();
    const d = res.diag;
    const n = d.rows.length, p = res.rank;
    const h2 = (2 * p) / n, h3 = (3 * p) / n;
    const cd = d.cooks.map((v) => (v != null && Number.isFinite(v) ? v : 0));
    const cmax = Math.max(1e-12, ...cd);
    const lab = ctx.table.labelColumn();
    const hover = d.rows.map((r, k) => `row ${r + 1}${lab && lab.values[r] != null ? `: ${SM.report.plotlyText(lab.values[r])}` : ''}<br>Cook's D ${fmt(cd[k], { sig: 4 })}`);
    const flagged = d.rows.filter((r, k) => Math.abs(d.externally[k] ?? 0) > 2 || d.hat[k] > h2);
    const ob = ctx.outline('Influence Plot', { parent, key: 'influence', info: 'p:fitmodel:influence', menu: () => [
      { label: `Select Influential Rows (${flagged.length})`, disabled: !flagged.length, action: () => ctx.table.select(flagged, 'replace') },
      { label: 'Remove', action: () => ctx.set('influence', false, sc) },
    ] });
    const [xl, xh] = extent(d.hat, [h3 * 1.05]);
    const trace = { type: 'scatter', mode: 'markers', x: d.hat, y: d.externally, rows: d.rows, hovertext: hover, hovertemplate: '%{hovertext}<br>leverage %{x:.4g}, studentized %{y:.4g}<extra></extra>',
      marker: { size: cd, sizemode: 'area', sizeref: (2 * cmax) / (34 ** 2), sizemin: 3.5, opacity: 0.8, line: { width: 0.6, color: P.dark ? '#1a1410' : '#ffffff' } }, name: 'Rows' };
    const vline = (x, dash) => ({ type: 'line', xref: 'x', x0: x, x1: x, yref: 'paper', y0: 0, y1: 1, line: { color: P.muted, width: 1, dash } });
    const hline = (v, dash, color = P.muted) => ({ type: 'line', xref: 'paper', x0: 0, x1: 1, yref: 'y', y0: v, y1: v, line: { color, width: 1, dash } });
    ob.add(ctx.plot([trace], { xaxis: { title: { text: 'Leverage (hat)' }, range: [Math.max(0, xl - 0.02 * (xh - xl)), xh + 0.04 * (xh - xl)] }, yaxis: { title: { text: 'Externally Studentized Residual' } },
      shapes: [hline(0, 'solid', P.mean), hline(2, 'dash'), hline(-2, 'dash'), vline(h2, 'dot'), vline(h3, 'dash')], margin: { l: 58, r: 12, t: 8, b: 46 } }, { width: W(460), height: 340, title: `${y.name} influence plot` }), ctx.code(codeOf(res, 'influence')),
    ctx.note(`The area of a bubble is the row's Cook's D (the largest ${fmt(cmax, { sig: 3 })}). Dashed: studentized residuals of ±2 and the leverage 3p/n = ${fmt(h3, { sig: 3 })}; dotted: 2p/n = ${fmt(h2, { sig: 3 })} (p = ${p}, n = ${n}). ${flagged.length} row${flagged.length === 1 ? '' : 's'} beyond ±2 or 2p/n: the red triangle selects them. statsmodels' influence_plot draws the same (resid_studentized_external, hat_matrix_diag, cooks_distance).`));
  }

  /* Component + Residual (partial residual) plots of the continuous terms. */
  function ccprPlots(ctx, parent, res, y, sc) {
    const P = pal();
    const ob = ctx.outline('Component + Residual Plots', { parent, key: 'ccpr', info: 'p:fitmodel:influence', menu: () => [{ label: 'Remove', action: () => ctx.set('ccpr', false, sc) }] });
    if (!res.ccpr.length) { ob.add(ctx.note('The model has no continuous terms.')); return; }
    const plots = res.ccpr.map((c, i) => withCode(rowPlot(ctx, { x: c.x, y: c.partial, rows: c.rows, xTitle: c.term, yTitle: `Component + Residual`, lines: [lineTrace(c.line.x, c.line.y, P.fit, 'solid', 1.5)], width: 330, height: 270, title: `${c.term} component plus residual` }), ctx.code((codeOf(res, 'ccpr') || [])[i])));
    ob.add(ctx.row(...plots), ctx.note('For each continuous term the residual plus the term\'s part of the fit, b·x, against x (statsmodels\' plot_ccpr); the line is b·x. A curve in the points asks for a transformation or a power of the term.'));
  }

  /* ---- Recursive and Rolling Regression -----------------------------------------------------------
     statsmodels' RecursiveLS on the least squares model with the rows taken
     one at a time, in the table's order or sorted by a column (the option
     rr:order), the CUSUM and CUSUM of squares with their bounds (rr:conf),
     RollingOLS over windows of rr:window rows. A recursive point stands for
     the row it adds and is linked to it; a rolling point for its window's
     rows. */
  const rgba = (hex, a) => {
    const h = String(hex).replace('#', '');
    const v = parseInt(h.length === 3 ? h.split('').map((c) => c + c).join('') : h, 16);
    return Number.isFinite(v) ? `rgba(${(v >> 16) & 255}, ${(v >> 8) & 255}, ${v & 255}, ${a})` : hex;
  };

  /* A series with its band (lower, upper), a dashed reference line and band, a dotted vertical line. */
  function bandPlot(ctx, { x, est, lower, upper, rows = null, hover = null, ref = null, refBand = null, vline = null, xTitle, yTitle, title, width = 330, height = 240, xaxis = {}, yfrom = 0 }) {
    const P = pal();
    const traces = [
      { type: 'scatter', mode: 'lines', x, y: lower, line: { width: 0, color: P.point }, hoverinfo: 'skip', showlegend: false },
      { type: 'scatter', mode: 'lines', x, y: upper, fill: 'tonexty', fillcolor: rgba(P.point, P.dark ? 0.32 : 0.18), line: { width: 0, color: P.point }, hoverinfo: 'skip', showlegend: false },
    ];
    const main = { type: 'scatter', mode: 'lines+markers', x, y: est, line: { color: P.point, width: 1.5 }, marker: { size: x.length > 300 ? 3 : 5, color: P.point }, name: 'Estimate' };
    if (rows) main.rows = rows;
    if (hover) { main.hovertext = hover; main.hovertemplate = '%{hovertext}<br>%{y:.5g}<extra></extra>'; }
    traces.push(main);
    const shapes = [];
    if (refBand) shapes.push({ type: 'rect', xref: 'paper', x0: 0, x1: 1, yref: 'y', y0: refBand[0], y1: refBand[1], fillcolor: rgba(P.fit, P.dark ? 0.2 : 0.1), line: { width: 0 }, layer: 'below' });
    if (ref != null) shapes.push({ type: 'line', xref: 'paper', x0: 0, x1: 1, yref: 'y', y0: ref, y1: ref, line: { color: P.fit, width: 1.2, dash: 'dash' } });
    if (vline != null) shapes.push({ type: 'line', xref: 'x', x0: vline, x1: vline, yref: 'paper', y0: 0, y1: 1, line: { color: P.muted, width: 1, dash: 'dot' } });
    // yfrom: the first point the y range is made for (the recursive estimates of the first rows are wild; zoom out for them)
    const txt = SM.report.plotlyText;   // the titles hold column names and levels
    let yaxis = { title: { text: txt(yTitle) } };
    if (yfrom > 0) {
      const [lo, hi] = extent(est.slice(yfrom), lower.slice(yfrom), upper.slice(yfrom), ref != null ? [ref] : null);
      const pad = 0.08 * (hi - lo);
      yaxis = { ...yaxis, range: [lo - pad, hi + pad] };
    }
    return ctx.plot(traces, { xaxis: { title: { text: txt(xTitle) }, ...xaxis }, yaxis, shapes, margin: { l: 58, r: 10, t: 8, b: 44 } }, { width: W(width), height, title });
  }

  function rrMenu(ctx, sc) {
    const allOn = RR.every(([k]) => ctx.opt(k, false, sc));
    return [...RR.map(([k, l]) => ctx.check(l, k, sc, false)),
      { label: allOn ? 'Remove All' : 'All Four', action: () => { for (const [k] of RR) ctx.set(k, !allOn, sc, { rerun: false }); ctx.report.run(); } },
      { separator: true },
      { label: 'Order Rows By…', action: () => rrOrderDialog(ctx, sc) },
      { label: 'Rolling Window…', action: () => rrWindowDialog(ctx, sc) }];
  }

  async function rrOrderDialog(ctx, sc) {
    const t = ctx.table;
    const cur = ctx.opt('rr:order', null, sc);
    const v = await SM.ui.form({ title: 'Order Rows By', info: 'p:fitmodel:recursive',
      lead: 'The recursive and rolling fits take the rows in this order: the table\'s, or sorted by a column (a time, a date, an index; a nominal column by its value order). Rows without a value of the column are left out.',
      fields: [{ key: 'col', label: 'Order by', type: 'select', value: cur && t.col(cur) ? cur : '', choices: [['', 'Row order (the table\'s)'], ...t.columns.map((c) => [c.id, c.name])],
        help: 'The column the rows are sorted by for the recursive estimates, the CUSUM tests and the rolling windows: a time, a date, an index (a nominal column by its value order; ties keep the table\'s order). Rows without a value of it are left out. Row order takes the table as it is.' }] });
    if (v) ctx.set('rr:order', v.col || null, sc);
  }

  async function rrWindowDialog(ctx, sc) {
    const n = ctx.rows.length;
    const cur = ctx.opt('rr:window', null, sc);
    const v = await SM.ui.form({ title: 'Rolling Window', info: 'p:fitmodel:recursive',
      lead: 'The number of consecutive rows in each window of the rolling regression. Empty: a tenth of the rows, at least three times the parameters.',
      fields: [{ key: 'w', label: 'Rows in a window', type: 'number', value: cur ?? '',
        help: 'The number of consecutive rows (in the order above) in each window of the rolling regression; it must be more than the number of parameters. Empty: a tenth of the rows, but at least three times the parameters. OK also turns Rolling Regression on.' }],
      validate: (x) => (x.w == null || (Number.isInteger(x.w) && x.w >= 3 && x.w <= n) ? null : `the window: a whole number from 3 to ${n}`) });
    if (v) { ctx.set('rr:window', v.w ?? null, sc, { rerun: false }); ctx.set('rr:rolling', true, sc); }
  }

  async function recursiveReport(ctx, parent, payload, y, sc) {
    const P = pal();
    const o = (k, d) => ctx.opt(k, d, sc);
    const t = ctx.table;
    const oc = o('rr:order', null) ? t.col(o('rr:order', null)) : null;
    const on = Object.fromEntries(RR.map(([k]) => [k, !!o(k, false)]));
    const conf = Number(o('rr:conf', 0.05));
    const r = await ctx.call('fitmodel.recursive', { ...payload, order_by: oc ? oc.name : null, alpha: ctx.alpha, conf, rolling: on['rr:rolling'], window: o('rr:window', null) });
    const ob = ctx.outline('Recursive and Rolling Regression', { parent, key: 'rr', info: 'p:fitmodel:recursive', menu: () => rrMenu(ctx, sc) });
    const mkSel = (label, value, choices, fn) => {
      const s = el('select', { 'aria-label': label }, ...choices.map(([v, l]) => el('option', { value: String(v), text: l })));
      s.value = String(value);
      s.addEventListener('change', () => fn(s.value));
      return el('label', { class: 'sm-fm-opt' }, el('span', { text: label }), s);
    };
    const win = el('input', { type: 'text', inputmode: 'numeric', size: 5, 'aria-label': 'Rolling window', class: 'sm-fm-num', placeholder: r.rolling ? String(r.rolling.window) : null });
    win.value = o('rr:window', null) != null ? String(o('rr:window', null)) : '';
    win.addEventListener('change', () => {
      const s = win.value.trim();
      if (s === '') { ctx.set('rr:window', null, sc); return; }
      const v = Number(s);
      if (Number.isInteger(v) && v > r.k && v <= r.n) ctx.set('rr:window', v, sc);
      else { SM.ui.toast(`The window: a whole number from ${r.k + 1} to ${r.n}`); win.value = o('rr:window', null) != null ? String(o('rr:window', null)) : ''; }
    });
    ob.add(el('div', { class: 'sm-fm-controls', dataset: { noexport: '' } },
      mkSel('Order by', oc ? oc.id : '', [['', 'Row order'], ...t.columns.filter((c) => c.id !== y.id).map((c) => [c.id, c.name])], (v) => ctx.set('rr:order', v || null, sc)),
      mkSel('Significance', conf, [[0.01, '1%'], [0.05, '5%'], [0.1, '10%']], (v) => ctx.set('rr:conf', Number(v), sc)),
      on['rr:rolling'] ? el('label', { class: 'sm-fm-opt' }, el('span', { text: 'Window' }), win) : null));
    const rowsO = r.order.rows;
    const vals = r.order.values;
    const lab = t.labelColumn();
    const txt = SM.report.plotlyText;
    const hoverOf = (k) => `row ${rowsO[k] + 1}${vals ? `, ${txt(oc.name)} ${txt(vals[k] ?? '')}` : ''}${lab && lab.values[rowsO[k]] != null ? `: ${txt(lab.values[rowsO[k]])}` : ''}`;
    const xTitle = `Observation (${oc ? `sorted by ${oc.name}` : 'in row order'})`;
    const start = r.start;
    const recRows = rowsO.slice(start);
    const recHover = recRows.map((_, j) => hoverOf(start + j));
    const zero = { type: 'line', xref: 'paper', x0: 0, x1: 1, yref: 'y', y0: 0, y1: 0, line: { color: P.muted, width: 1 } };
    const margin = { l: 58, r: 12, t: 8, b: 46 };
    if (on['rr:recursive']) {
      const ro = ctx.outline('Recursive Estimates', { parent: ob, key: 'rr:rec', menu: () => [{ label: 'Remove', action: () => ctx.set('rr:recursive', false, sc) }] });
      const npts = r.cusum.x.length;
      const yfrom = Math.min(npts - 1, Math.max(2 * r.k, Math.round(0.05 * npts)));
      ro.add(ctx.row(...r.recursive.map((c, i) => withCode(bandPlot(ctx, { x: r.cusum.x, est: c.estimate, lower: c.lower, upper: c.upper, rows: recRows, hover: recHover, ref: c.full, xTitle, yTitle: c.term, title: `${c.term} recursive estimate`, width: 340, height: 230, yfrom }), ctx.code((codeOf(r, 'recursive') || [])[i])))),
        ctx.note(`Each point is the least squares estimate from the rows up to it in the order (from observation ${start + 1} on, where every parameter is estimable); the band is ±${fmt(qnorm(1 - ctx.alpha / 2), { sig: 3 })} standard errors, the dashed line the estimate from all the rows. The vertical axis is scaled to the estimates from observation ${start + yfrom + 1} on (the first ones swing widely: drag to zoom, double click to come back). A stable coefficient settles inside its band; a drift away shows where it changes.`));
    }
    if (on['rr:cusum']) {
      const c = r.cusum;
      const co = ctx.outline('CUSUM', { parent: ob, key: 'rr:cusum', info: 'p:fitmodel:recursive', menu: () => [{ label: 'Remove', action: () => ctx.set('rr:cusum', false, sc) }] });
      const traces = [lineTrace(c.x, c.upper, P.fit, 'dash', 1.2), lineTrace(c.x, c.lower, P.fit, 'dash', 1.2),
        { type: 'scatter', mode: 'lines+markers', x: c.x, y: c.y, rows: recRows, hovertext: recHover, hovertemplate: '%{hovertext}<br>CUSUM %{y:.4g}<extra></extra>', line: { color: P.point, width: 1.4 }, marker: { size: c.x.length > 300 ? 3 : 5, color: P.point }, name: 'CUSUM' }];
      co.add(ctx.row(withCode(ctx.plot(traces, { xaxis: { title: { text: txt(xTitle) } }, yaxis: { title: { text: 'CUSUM' } }, shapes: [zero], margin }, { width: W(520), height: 300, title: `${y.name} CUSUM` }), ctx.code(codeOf(r, 'cusum'))),
        ctx.kv([['Significance level', r.conf], ['Crosses the bounds', c.crossed ? 'Yes' : 'No', 'text'], c.crossed ? ['First crossing, observation', c.first, 'int'] : null,
          c.crossed ? ['First crossing, row', c.first_row + 1, 'int'] : null, ['Largest |CUSUM| / bound', c.ratio], ['a (Brown, Durbin and Evans)', c.constant], ['Recursive residuals', c.x.length, 'int']])),
      ctx.note(`The cumulative sum of the recursive residuals over their standard deviation, with the ${fmt(100 * r.conf)}% bounds (dashed). Inside them the coefficients look stable along the order; a path that leaves them (here ${c.crossed ? `first at observation ${c.first}, row ${c.first_row + 1}` : 'it does not'}) says the relation shifts: the recursive estimates show which coefficient moves.`));
    }
    if (on['rr:cusumsq']) {
      const c = r.cusumsq;
      const co = ctx.outline('CUSUM of Squares', { parent: ob, key: 'rr:cusumsq', info: 'p:fitmodel:recursive', menu: () => [{ label: 'Remove', action: () => ctx.set('rr:cusumsq', false, sc) }] });
      const traces = [lineTrace(c.x, c.line, P.muted, 'dot', 1), lineTrace(c.x, c.upper, P.fit, 'dash', 1.2), lineTrace(c.x, c.lower, P.fit, 'dash', 1.2),
        { type: 'scatter', mode: 'lines+markers', x: c.x, y: c.y, rows: recRows, hovertext: recHover, hovertemplate: '%{hovertext}<br>CUSUM of squares %{y:.4g}<extra></extra>', line: { color: P.point, width: 1.4 }, marker: { size: c.x.length > 300 ? 3 : 5, color: P.point }, name: 'CUSUM of squares' }];
      co.add(ctx.row(withCode(ctx.plot(traces, { xaxis: { title: { text: txt(xTitle) } }, yaxis: { title: { text: 'CUSUM of Squares' } }, margin }, { width: W(520), height: 300, title: `${y.name} CUSUM of squares` }), ctx.code(codeOf(r, 'cusumsq'))),
        ctx.kv([['Significance level', r.conf], ['Crosses the bounds', c.crossed ? 'Yes' : 'No', 'text'], c.crossed ? ['First crossing, observation', c.first, 'int'] : null,
          c.crossed ? ['First crossing, row', c.first_row + 1, 'int'] : null, ['Largest distance from the diagonal', c.dev], ['At observation', c.at, 'int'], ['At row', c.at_row + 1, 'int'], ['Critical distance', c.crit]])),
      ctx.note(`The share of the sum of squared recursive residuals reached at each observation. With stable coefficients and variance it follows the dotted diagonal; leaving the ${fmt(100 * r.conf)}% bounds (dashed) says the variance or the slopes change along the order. The largest distance from the diagonal is near the change; the path may cross the bounds before it, since each share is of a total that the later rows inflate.`));
    }
    if (on['rr:rolling'] && r.rolling) {
      const R = r.rolling;
      const w = R.window;
      const groups = R.x.map((end) => rowsO.slice(end - w, end));
      const hov = R.x.map((end) => `observations ${end - w + 1}–${end}: rows ${rowsO[end - w] + 1} to ${rowsO[end - 1] + 1}`);
      const ro = ctx.outline(`Rolling Regression, Window ${w}`, { parent: ob, key: 'rr:roll', menu: () => [{ label: 'Rolling Window…', action: () => rrWindowDialog(ctx, sc) }, { label: 'Remove', action: () => ctx.set('rr:rolling', false, sc) }] });
      ro.add(ctx.row(...R.terms.map((c, i) => withCode(bandPlot(ctx, { x: R.x, est: c.estimate, lower: c.lower, upper: c.upper, rows: groups, hover: hov, ref: c.full, xTitle: `Last observation of the window (${oc ? `sorted by ${oc.name}` : 'row order'})`, yTitle: c.term, title: `${c.term} rolling estimate`, width: 340, height: 230 }), ctx.code((codeOf(r, 'rolling') || [])[i])))),
        ctx.note(`Least squares on each window of ${w} consecutive rows, plotted at its last row, with the ${fmt(100 * (1 - ctx.alpha))}% band; the dashed line is the estimate from all the rows. A point stands for its window: clicking it selects the window's rows, and selecting rows lights up every window that holds them.`));
    }
    for (const n of r.notes || []) ob.add(ctx.note(n));
    ob.add(ctx.code(r.code));
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
    const ce = ctx.outline('Current Estimates', { parent, key: 'swcur', info: 'p:fitmodel:stepwise' });
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
      const ob = ctx.outline('All Possible Models', { parent, key: 'swall', info: 'p:fitmodel:stepwise', menu: () => [{ label: 'Remove', action: () => ctx.set('sw:all', false, sc) }] });
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
    const rob = robustOf(ctx, sc);
    const payload = { ...M.base, y: g.cols.length === 1 ? g.cols[0].name : g.cols.map((c) => c.name), offset: ctx.name('offset'), dist, link: ctx.opt('link', null) || DEFAULT_LINK[dist], target: ctx.opt('target', null), overdispersion: !!o('overdispersion', false), ...(rob ? { robust: rob } : {}) };
    const res = await ctx.call('fitmodel.glm', { ...payload, alpha: ctx.alpha });
    const m = res.model;
    const wald = o('wald', false) || !!res.robust;   // robust standard errors: Wald tests (the L-R tests assume the model's variance)
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
    const robCap = res.robust ? `Robust standard errors: ${res.robust.label}` : undefined;
    if (o('effectTests', true) && res.effect_tests.length) {
      ctx.outline('Effect Tests', { parent, key: 'efftests' }).add(ctx.rt({ columns: [{ key: 'source', label: 'Source', fmt: 'text' }, { key: 'nparm', label: 'Nparm', fmt: 'int' }, { key: 'df', label: 'DF', fmt: 'int' },
        { key: wald ? 'wald' : 'lr', label: wald ? 'Wald ChiSquare' : 'L-R ChiSquare' }, { key: wald ? 'p_wald' : 'p', label: 'Prob>ChiSq', fmt: 'p' }], rows: res.effect_tests }, { key: 'efftests', caption: robCap }));
    }
    if (o('estimates', true)) {
      const ci = o('showCI', true);
      ctx.outline('Parameter Estimates', { parent, key: 'estimates', info: res.robust ? 'p:fitmodel:robust' : null }).add(ctx.rt({ columns: [{ key: 'term', label: 'Term', fmt: 'text' }, { key: 'estimate', label: 'Estimate' }, { key: 'se', label: 'Std Error' },
        { key: wald ? 'wald' : 'lr', label: wald ? 'Wald ChiSquare' : 'L-R ChiSquare' }, { key: wald ? 'p_wald' : 'p', label: 'Prob>ChiSq', fmt: 'p' }, { key: 'lower', label: `Lower ${fmt(100 * (1 - ctx.alpha))}%`, hidden: !ci }, { key: 'upper', label: `Upper ${fmt(100 * (1 - ctx.alpha))}%`, hidden: !ci }], rows: res.estimates }, { key: 'estimates', caption: robCap }));
    }
    const d = res.diag;
    const yl = res.model.response;
    if (o('studDev', true)) ctx.outline('Studentized Deviance Residual by Predicted', { parent, key: 'studdev' }).add(rowPlot(ctx, { x: d.predicted, y: d.stud_dev, rows: d.rows, xTitle: `${yl} Predicted`, yTitle: 'Studentized Deviance Residual', hlines: [{ y: 0, color: P.mean }], title: 'studentized deviance residuals' }), ctx.code(codeOf(res, 'studDev')));
    const extraPlots = [['studPearson', 'Studentized Pearson Residual by Predicted', d.stud_pearson, 'Studentized Pearson Residual'], ['devPlot', 'Deviance Residual by Predicted', d.resid_dev, 'Deviance Residual'], ['pearPlot', 'Pearson Residual by Predicted', d.resid_pearson, 'Pearson Residual']];
    for (const [k, title, v, yt] of extraPlots) if (o(k, false)) ctx.outline(title, { parent, key: k }).add(rowPlot(ctx, { x: d.predicted, y: v, rows: d.rows, xTitle: `${yl} Predicted`, yTitle: yt, hlines: [{ y: 0, color: P.mean }], title }), ctx.code(codeOf(res, k)));
    if (o('actualPred', false)) actualByPredicted(ctx, parent, { predicted: d.predicted, actual: d.actual, rows: d.rows }, null, yl, 'p:fitmodel:glm', undefined, codeOf(res, 'actualPred'));
    if (o('linPlot', false)) {
      const order = d.linpred.map((_, k) => k).sort((a, b) => d.linpred[a] - d.linpred[b]);
      ctx.outline('Linear Predictor Plot', { parent, key: 'linplot' }).add(rowPlot(ctx, { x: d.linpred, y: d.actual, rows: d.rows, xTitle: 'Linear Predictor', yTitle: yl, lines: [lineTrace(order.map((k) => d.linpred[k]), order.map((k) => d.predicted[k]), P.fit)], title: 'linear predictor plot' }),
        ctx.code(codeOf(res, 'linPlot')), ctx.note('The response against the linear predictor; the curve is the fitted mean, the inverse link of the linear predictor.'));
    }
    const kind = 'glm';
    if (o('plotRegression', true) && g.cols.length === 1) await regressionPlot(ctx, parent, { kind, payload, factors: res.factors, d, yname: yl, scope: sc, code: codeOf(res, 'regression') });
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
      c('Wald Tests', 'wald', false, res.robust ? { checked: true, disabled: true } : {}),
      { label: 'Robust Standard Errors', submenu: () => robustMenu(ctx, { id: sc }, 'glm') },
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

  /* ---- Generalized Estimating Equations ----------------------------------------------------------------------
     statsmodels' GEE: the Subject role groups the rows, Time orders them
     (AR(1), Unstructured), Subgroup nests within the subjects (Nested). The
     dialog's options are dist, link, target and workCorr, geeCov, geeScale,
     geeScaleValue, nbAlpha, varPower. */
  function geePayload(ctx, M, y) {
    const dist = ctx.opt('dist', 'normal');
    return { ...M.base, y: y.name, subject: ctx.name('subject'), time: ctx.name('time'), subgroup: ctx.name('subgroup'), offset: ctx.name('offset'),
      dist, link: ctx.opt('link', null) || DEFAULT_LINK[dist], target: ctx.opt('target', null), corr: ctx.opt('workCorr', 'exchangeable'),
      cov: ctx.opt('geeCov', 'robust'), scale: ctx.opt('geeScale', null), scale_value: ctx.opt('geeScaleValue', null), nb_alpha: ctx.opt('nbAlpha', null),
      var_power: ctx.opt('varPower', null) };
  }

  async function renderGEE(ctx, M) {
    const ys = ctx.roles('y');
    await perResponse(ctx, ys, (y) => `Response ${y.name}`, (y, parent, st) => geeY(ctx, M, y, parent, st));
  }

  async function geeY(ctx, M, y, parent, st) {
    const P = pal();
    const sc = y.id;
    const o = (k, d) => ctx.opt(k, d, sc);
    const payload = geePayload(ctx, M, y);
    const res = await ctx.call('fitmodel.gee', { ...payload, alpha: ctx.alpha });
    const m = res.model;
    st.menu = () => geeMenu(ctx, y, res, sc);
    const yl = m.target ? `${m.response} (event: ${m.target})` : m.response;
    parent.add(el('p', { class: 'sm-fm-modelline' }, ...[['Response', yl], ['Distribution', m.distribution], ['Link', m.link], ['Working Correlation', m.corr], ['Covariance', m.cov], ['Subject', m.subject]]
      .map(([k, v]) => el('span', null, el('b', { text: `${k}: ` }), v))));
    if (o('effectSummary', true) && res.effect_tests.length) effectSummary(ctx, parent, res.effect_tests.map((r) => ({ source: r.source, p: r.p, logworth: logw(r.p) })).sort((a, b) => b.logworth - a.logworth), { scope: sc });
    if (o('modelSummary', true)) {
      ctx.outline('Model Summary', { parent, key: 'geesummary', info: 'p:fitmodel:gee' }).add(ctx.kv([
        ['Response', yl, 'text'], ['Distribution', m.distribution, 'text'], ['Link', m.link, 'text'], ['Working Correlation', m.corr, 'text'], ['Covariance', m.cov, 'text'],
        ['Scale (φ)', `${fmt(m.scale, { sig: 6 })} (${m.scale_kind})`, 'text'], ['Subject', m.subject, 'text'], m.time ? ['Time', m.time, 'text'] : null, m.subgroup ? ['Subgroup', m.subgroup, 'text'] : null,
        ['Number of Rows', m.n, 'int'], ['Number of Subjects', m.subjects, 'int'], ['Rows per Subject, Min', m.size_min, 'int'], ['Rows per Subject, Mean', m.size_mean], ['Rows per Subject, Max', m.size_max, 'int'],
        ['Iterations', m.iterations, 'int'], ['Converged', m.converged ? 'Yes' : 'No', 'text']]));
    }
    const pct = fmt(100 * (1 - ctx.alpha));
    if (o('estimates', true)) {
      const cols = [{ key: 'term', label: 'Term', fmt: 'text' }, { key: 'estimate', label: 'Estimate' }, { key: 'se', label: 'Std Error' },
        { key: 'se_robust', label: 'Robust Std Error', hidden: true }, { key: 'se_naive', label: 'Naive Std Error', hidden: true },
        { key: 'z', label: 'z Ratio' }, { key: 'p', label: 'Prob>|z|', fmt: 'p' }, { key: 'lower', label: `Lower ${pct}%` }, { key: 'upper', label: `Upper ${pct}%` }]
        .filter((c) => !(c.key === 'se_robust' && m.cov_key === 'robust') && !(c.key === 'se_naive' && m.cov_key === 'naive'));
      ctx.outline('Parameter Estimates', { parent, key: 'estimates', info: 'p:fitmodel:gee' }).add(ctx.rt({ columns: cols, rows: res.estimates }, { key: 'estimates', caption: `Standard errors: ${m.cov.toLowerCase()}` }));
    }
    if (res.ratios && o('ratios', false)) geeRatios(ctx, parent, res.ratios, pct);
    if (o('effectTests', true) && res.effect_tests.length) {
      ctx.outline('Effect Tests', { parent, key: 'efftests' }).add(ctx.rt({ columns: [{ key: 'source', label: 'Source', fmt: 'text' }, { key: 'nparm', label: 'Nparm', fmt: 'int' }, { key: 'df', label: 'DF', fmt: 'int' },
        { key: 'wald', label: 'Wald ChiSquare' }, { key: 'p', label: 'Prob>ChiSq', fmt: 'p' }], rows: res.effect_tests }, { key: 'efftests', caption: `Wald tests with the ${m.cov.toLowerCase()} covariance` }));
    }
    if (o('qic', true)) {
      const q = res.qic;
      ctx.outline('QIC', { parent, key: 'qic', info: 'p:fitmodel:qic' }).add(ctx.kv([['QIC', q.qic], ['QICu', q.qicu], ['QIC (statsmodels qic())', q.qic_sm], ['Quasi-Likelihood', q.ql], ['Penalty trace(Ω_I V_R)', q.trace], ['Parameters (p)', q.p, 'int'], ['Scale for QIC (φ)', q.scale]]),
        ctx.note(`QIC = −2Q + 2 trace(Ω_I V_R), QICu = −2Q + 2p (Pan 2001), at φ = ${fmt(q.scale, { sig: 6 })} (${q.source === 'fixed' ? 'the fixed scale' : 'the independence fit\'s estimate'}) for every working correlation. Smaller is better: QIC compares working correlations (the red triangle's Compare Working Correlations), QICu mean models.`));
    }
    if (o('workcorr', true)) workingCorrelation(ctx, parent, res);
    const d = res.diag;
    const plots = [];
    if (o('residPred', true)) plots.push(ctx.outline('Residual by Predicted', { parent, key: 'residpred' }).add(rowPlot(ctx, { x: d.predicted, y: d.residual, rows: d.rows, xTitle: `${m.response} Predicted (marginal)`, yTitle: `${m.response} Residual`, hlines: [{ y: 0, color: P.mean }], title: `${y.name} residual by predicted` }), ctx.code(codeOf(res, 'residPred'))).el);
    if (o('actualPred', true)) plots.push(actualByPredicted(ctx, parent, { predicted: d.predicted, actual: d.actual, rows: d.rows }, null, m.response, 'p:fitmodel:gee', undefined, codeOf(res, 'actualPred')).el);
    if (plots.length > 1) parent.add(ctx.row(...plots));
    if (o('residSubject', true)) residualsBySubject(ctx, parent, res, y, sc);
    if (o('compareCorr', false)) await compareCorrelations(ctx, parent, payload, sc);
    if (o('profiler', false)) await profiler(ctx, parent, { sources: [{ kind: 'gee', payload }], scope: sc });
    if (o('contour', false)) await contourProfiler(ctx, parent, { kind: 'gee', payload, factors: res.factors, scope: sc });
    if (o('interaction', false)) await interactionPlots(ctx, parent, { kind: 'gee', payload, scope: sc });
    tail(ctx, parent, res);
  }

  function geeRatios(ctx, parent, R, pct) {
    const one = R.kind.replace(/s$/, '');
    const ob = ctx.outline(R.kind, { parent, key: 'ratios', info: 'p:fitmodel:gee' });
    if (R.unit.length) {
      ob.add(ctx.rt({ columns: [{ key: 'term', label: 'Term', fmt: 'text' }, { key: 'ratio', label: one }, { key: 'lower', label: `Lower ${pct}%` }, { key: 'upper', label: `Upper ${pct}%` }, { key: 'p', label: 'Prob>ChiSq', fmt: 'p' }], rows: R.unit },
        { caption: `Unit ${R.kind}: per unit change in the regressor`, key: 'ratiounit' }),
      ctx.rt({ columns: [{ key: 'term', label: 'Term', fmt: 'text' }, { key: 'range', label: one }, { key: 'range_lower', label: `Lower ${pct}%` }, { key: 'range_upper', label: `Upper ${pct}%` }, { key: 'span', label: 'Range' }], rows: R.unit },
        { caption: `Range ${R.kind}: over the whole range of the regressor`, key: 'ratiorange' }));
    }
    if (R.levels.length) {
      ob.add(ctx.rt({ columns: [{ key: 'term', label: 'Effect', fmt: 'text' }, { key: 'level1', label: 'Level1', fmt: 'text' }, { key: 'level2', label: '/Level2', fmt: 'text' }, { key: 'ratio', label: one }, { key: 'p', label: 'Prob>ChiSq', fmt: 'p' }, { key: 'lower', label: `Lower ${pct}%` }, { key: 'upper', label: `Upper ${pct}%` }], rows: R.levels },
        { caption: `${R.kind} between levels`, key: 'ratiolevels' }));
    }
    ob.add(ctx.note(`exp of the marginal model's coefficients: for a level pair the other factors are averaged. Wald intervals with the report's covariance.`));
  }

  function workingCorrelation(ctx, parent, res) {
    const ob = ctx.outline('Working Correlation', { parent, key: 'workcorr', info: 'p:fitmodel:workcorr' });
    const dp = res.dep;
    if (dp.rows.length) ob.add(ctx.rt({ columns: [{ key: 'param', label: 'Dependence Parameter', fmt: 'text' }, { key: 'value', label: 'Estimate' }], rows: dp.rows }, { sortable: false, key: 'depparams' }));
    else ob.add(ctx.note('Independence: the rows of a subject are taken as uncorrelated; the robust standard errors allow for their correlation.'));
    const Mx = dp.matrix;
    const k = Mx.labels.length;
    const seen = new Map();
    const labels = Mx.labels.map((l) => { const n = (seen.get(l) || 0) + 1; seen.set(l, n); return SM.report.plotlyText(n > 1 ? `${l} (${n})` : l); });
    const tc = SM.util.themeColors();
    const scale = tc.dark ? [[0, '#5b9cf0'], [0.5, '#3a3431'], [1, '#e8604f']] : [[0, '#2f6ec7'], [0.5, '#f6f3f0'], [1, '#c0392b']];
    const txt = Mx.values.map((row) => row.map((v) => (v == null ? '' : v.toFixed(2).replace('-', '−'))));
    const side = Math.max(230, Math.min(560, 70 + 42 * k));
    // the values on the cells, in a colour that reads on each: the strong colours are dark in the light theme and light in the dark one
    // placed by the categories' serial numbers: a label such as '2' would be read as the index 2
    const annotations = k > 12 ? [] : Mx.values.flatMap((row, i) => row.map((v, j) => ({ x: j, y: i, xref: 'x', yref: 'y', text: txt[i][j], showarrow: false,
      font: { size: 10.5, color: v != null && Math.abs(v) > 0.5 ? (tc.dark ? '#1a1410' : '#ffffff') : tc.text } })));
    ob.add(ctx.plot([{ type: 'heatmap', z: Mx.values, x: labels, y: labels, zmin: -1, zmax: 1, colorscale: scale, text: txt, hovertemplate: '%{y} and %{x}: %{text}<extra></extra>', xgap: 1, ygap: 1, colorbar: { thickness: 10, len: 0.85 } }],
      { xaxis: { type: 'category', title: { text: res.model.time || 'Row of the subject' }, showgrid: false, showline: false, ticks: '' }, yaxis: { type: 'category', autorange: 'reversed', showgrid: false, showline: false, ticks: '' }, annotations, margin: { l: 70, r: 10, t: 8, b: 40 } },
      { width: W(side + 80), height: side, title: 'working correlation', select: false }), ctx.code(codeOf(res, 'workcorr')),
    ctx.note(`The working correlation of the rows of subject ${Mx.subject} (${Mx.size} rows; the first of the largest subjects), as statsmodels' cov_struct gives it.`));
  }

  function residualsBySubject(ctx, parent, res, y, sc) {
    const P = pal();
    const d = res.diag;
    const subjects = d.subjects.map((s) => SM.report.plotlyText(s));
    const xs = d.subject.map((s) => SM.report.plotlyText(s));
    const traces = [];
    if (ctx.opt('subjectBoxes', false, sc)) traces.push({ type: 'box', x: xs, y: d.residual, boxpoints: false, fillcolor: 'rgba(0,0,0,0)', line: { color: P.muted, width: 1 }, hoverinfo: 'skip', showlegend: false, name: 'Boxes' });
    traces.push({ type: d.rows.length > 4000 ? 'scattergl' : 'scatter', mode: 'markers', x: xs, y: d.residual, rows: d.rows, marker: { size: d.rows.length > 500 ? 4 : 5.5 }, name: 'Rows' });
    const ob = ctx.outline('Residuals by Subject', { parent, key: 'residsubj', menu: () => [ctx.check('Boxes per Subject', 'subjectBoxes', sc, false)] });
    ob.add(ctx.plot(traces, { xaxis: { type: 'category', categoryorder: 'array', categoryarray: subjects, title: { text: res.model.subject }, tickfont: { size: subjects.length > 40 ? 8 : 10 } }, yaxis: { title: { text: `${y.name} Residual` } },
      shapes: [{ type: 'line', xref: 'paper', x0: 0, x1: 1, yref: 'y', y0: 0, y1: 0, line: { color: P.mean, width: 1 } }], margin: { l: 58, r: 12, t: 8, b: 60 } },
    { width: W(Math.max(420, Math.min(900, 14 * subjects.length + 120))), height: 300, title: `${y.name} residuals by subject` }),
    ctx.code(codeOf(res, ctx.opt('subjectBoxes', false, sc) ? 'residSubjectBoxes' : 'residSubject')));
  }

  async function compareCorrelations(ctx, parent, payload, sc) {
    const r = await ctx.call('fitmodel.gee_compare', payload);
    const ob = ctx.outline('Compare Working Correlations', { parent, key: 'geecompare', info: 'p:fitmodel:qic', menu: () => [{ label: 'Remove', action: () => ctx.set('compareCorr', false, sc) }] });
    const rows = r.rows.map((x) => ({ ...x, label: `${x.corr}${x.best ? '  (smallest QIC)' : ''}${x.current ? '  (current)' : ''}`, conv: x.error ? '' : (x.converged ? 'Yes' : 'No') }));
    const failed = r.rows.some((x) => x.error);
    ob.add(ctx.rt({ columns: [{ key: 'label', label: 'Working Correlation', fmt: 'text' }, { key: 'qic', label: 'QIC' }, { key: 'qicu', label: 'QICu' }, { key: 'qic_sm', label: 'QIC (statsmodels)', hidden: true },
      { key: 'ql', label: 'Quasi-Likelihood', hidden: true }, { key: 'trace', label: 'trace(Ω_I V_R)' }, { key: 'dep', label: 'α' }, { key: 'iterations', label: 'Iterations', fmt: 'int' },
      { key: 'conv', label: 'Converged', fmt: 'text' }, { key: 'error', label: 'Not fitted', fmt: 'text', hidden: !failed }], rows },
    { key: 'geecompare', onRow: (row) => { if (!row.error && !row.current) ctx.set('workCorr', row.key); } }));
    for (const n of r.notes || []) ob.add(ctx.note(n));
    ob.add(ctx.note('Click a line to refit the report with that working correlation.'), ctx.code(r.code));
  }

  function geeMenu(ctx, y, res, sc) {
    const c = (label, key, dflt, x) => ctx.check(label, key, sc, dflt, x);
    const m = res.model;
    const d = res.diag;
    const sv = (name, v) => () => ctx.saveColumn(name, { rows: d.rows, values: v });
    return [
      { label: 'Regression Reports', submenu: () => [c('Model Summary', 'modelSummary', true), c('Parameter Estimates', 'estimates', true), c('Effect Tests', 'effectTests', true), c('QIC', 'qic', true),
        c('Working Correlation', 'workcorr', true), c('Effect Summary', 'effectSummary', true)] },
      c(res.ratios ? res.ratios.kind : 'Odds Ratios', 'ratios', false, { disabled: !res.ratios }),
      { label: 'Correlation Structure', submenu: () => CORRS.map(([k, l]) => ({ label: l, checked: m.corr_key === k, disabled: ((k === 'ar1' || k === 'unstructured') && !m.time) || (k === 'nested' && !m.subgroup), action: () => ctx.set('workCorr', k) })) },
      { label: 'Covariance', submenu: () => COVS.map(([k, l]) => ({ label: l, checked: m.cov_key === k, action: () => ctx.set('geeCov', k) })) },
      c('Compare Working Correlations', 'compareCorr', false),
      { label: 'Diagnostic Plots', submenu: () => [c('Residual by Predicted', 'residPred', true), c('Actual by Predicted', 'actualPred', true), c('Residuals by Subject', 'residSubject', true), c('Boxes per Subject', 'subjectBoxes', false)] },
      { label: 'Profilers', submenu: () => [c('Profiler', 'profiler', false), c('Contour Profiler', 'contour', false), c('Interaction Plots', 'interaction', false)] },
      { label: 'Save Columns', submenu: () => [
        { label: 'Predicted Values (marginal)', action: sv(`Pred ${y.name}`, d.predicted) },
        { label: 'Residuals', action: sv(`Residual ${y.name}`, d.residual) },
        { label: 'Pearson Residuals', action: sv(`Pearson Residual ${y.name}`, d.pearson) },
        { label: 'Linear Predictor', action: sv(`Linear Predictor ${y.name}`, d.linpred) },
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
      ctx.outline('Receiver Operating Characteristic', { parent, key: 'roc' }).add(ctx.row(withCode(ctx.plot(traces, { showlegend: true, legend: { x: 0.35, y: 0.08 }, xaxis: { title: { text: '1 - Specificity' }, range: [0, 1] }, yaxis: { title: { text: 'Sensitivity' }, range: [0, 1.01] } }, { width: W(360), height: 340, title: 'ROC curve', select: false }), ctx.code(codeOf(res, 'roc'))),
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
      ctx.code(codeOf(res, 'logistic')),
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
    if (o('actCond', true)) plots.push(actualByPredicted(ctx, parent, { predicted: d.predicted, actual: d.actual, rows: d.rows }, null, y.name, 'p:fitmodel:mixed', 'Actual by Conditional Predicted', codeOf(res, 'actCond')).el);
    if (o('actMarg', false)) { const ob = ctx.outline('Actual by Marginal Predicted', { parent, key: 'actmarg' }); const [lo, hi] = extent(d.marginal, d.actual); ob.add(rowPlot(ctx, { x: d.marginal, y: d.actual, rows: d.rows, xTitle: `${y.name} Marginal Predicted`, yTitle: `${y.name} Actual`, lines: [lineTrace([lo, hi], [lo, hi], P.fit)], title: 'actual by marginal predicted' }), ctx.code(codeOf(res, 'actMarg'))); plots.push(ob.el); }
    if (o('resCond', true)) { const ob = ctx.outline('Conditional Residual by Predicted', { parent, key: 'rescond' }); ob.add(rowPlot(ctx, { x: d.predicted, y: d.residual, rows: d.rows, xTitle: `${y.name} Conditional Predicted`, yTitle: 'Conditional Residual', hlines: [{ y: 0, color: P.mean }], title: 'conditional residuals' }), ctx.code(codeOf(res, 'resCond'))); plots.push(ob.el); }
    if (plots.length > 1) parent.add(ctx.row(...plots));
    if (o('profiler', false)) await profiler(ctx, parent, { sources: [{ kind: 'mixed', payload }], scope: sc });
    if (o('interaction', false)) await interactionPlots(ctx, parent, { kind: 'mixed', payload, scope: sc });
    tail(ctx, parent, res);
  }

  /* ---- MANOVA ---------------------------------------------------------------------------------------------
     Choose Response picks the response design. Repeated Measures (JMP's) asks
     for the name of the within-subject factor across the Y columns (Y Name,
     Time) and Univariate Tests Also, then reports Between Subjects (the
     effects on the sum of the responses) and Within Subjects (the factor and
     its crossings with the effects, on their contrasts), with the sphericity
     test and the epsilon-adjusted univariate tests when asked. */
  const RESPONSES = [['repeated', 'Repeated Measures'], ['sum', 'Sum'], ['identity', 'Identity'], ['contrast', 'Contrast'], ['polynomial', 'Polynomial'], ['mean', 'Mean']];

  async function repeatedDialog(ctx, sc) {
    return SM.ui.form({
      title: 'Repeated Measures', info: 'p:fitmodel:repeated', okLabel: 'OK',
      lead: 'The Y columns are the levels of a within-subject factor, in their order: give the factor a name. The report tests the model effects on the sum of the responses (Between Subjects) and on their contrasts, as crossings with the named factor (Within Subjects).',
      fields: [{ key: 'name', label: 'Y Name', type: 'text', value: ctx.opt('rmName', 'Time', sc),
        help: 'The name of the within-subject factor whose levels the Y columns are, in their order (Time by default): the Within Subjects tests are named after it (Time, Time*drug).' },
        { key: 'univariate', label: 'Univariate Tests Also', type: 'check', value: !!ctx.opt('univariate', false, sc),
          help: 'Adds Mauchly\'s sphericity test and the univariate within tests, unadjusted and with the degrees of freedom times the Greenhouse–Geisser and Huynh–Feldt epsilons, beside the multivariate tests.' }],
      validate: (v) => (String(v.name || '').trim() ? null : 'Give the within-subject factor a name (Time, for example).'),
    });
  }

  async function renderManova(ctx, M) {
    const ys = ctx.roles('y');
    const sc = 'manova';
    const o = (k, d) => ctx.opt(k, d, sc);
    const response = o('response', 'identity');
    const rm = response === 'repeated';
    const within = String(o('rmName', 'Time') || 'Time').trim() || 'Time';
    const res = await ctx.call('fitmodel.manova', { ...M.base, y: ys.map((c) => c.name), response, alpha: ctx.alpha, ...(rm ? { within } : {}) });
    ctx.fm.menu = () => [
      ctx.check('Show E and H Matrices', 'matrices', sc, false),
      ctx.check('Partial Correlation', 'partial', sc, false),
      ctx.check('Univariate Tests Also', 'univariate', sc, false),
      { separator: true },
      { label: 'Model Dialog', action: () => ctx.report.relaunch() },
    ];
    if (res.error) { ctx.top.add(ctx.warn(res.error)); return; }
    const spec = ctx.outline('Response Specification', { key: 'mvspec', info: 'p:fitmodel:manova' });
    const s = el('select', { 'aria-label': 'Choose Response' }, ...RESPONSES.map(([v, l]) => el('option', { value: v, text: l })));
    s.value = response;
    s.addEventListener('change', async () => {
      if (s.value !== 'repeated') { ctx.set('response', s.value, sc); return; }
      const v = await repeatedDialog(ctx, sc);
      if (!v) { s.value = response; return; }
      ctx.set('rmName', String(v.name).trim(), sc, { rerun: false });
      ctx.set('univariate', !!v.univariate, sc, { rerun: false });
      ctx.set('response', 'repeated', sc);
    });
    const controls = el('div', { class: 'sm-fm-controls' }, el('label', { class: 'sm-fm-opt' }, el('span', { text: 'Choose Response' }), s));
    if (rm) {
      const nameIn = el('input', { type: 'text', size: 10, 'aria-label': 'Y Name', class: 'sm-fm-name' });
      nameIn.value = within;
      nameIn.addEventListener('change', () => { const v = nameIn.value.trim(); if (v && v !== within) ctx.set('rmName', v, sc); else nameIn.value = within; });
      const uni = el('input', { type: 'checkbox', 'aria-label': 'Univariate Tests Also' });
      uni.checked = !!o('univariate', false);
      uni.addEventListener('change', () => ctx.set('univariate', uni.checked, sc));
      controls.append(el('label', { class: 'sm-fm-opt' }, el('span', { text: 'Y Name' }), nameIn), el('label', { class: 'sm-fm-opt' }, uni, el('span', { text: 'Univariate Tests Also' })));
      spec.add(controls, ctx.note(`Responses: ${res.responses.join(', ')}, the ${res.k} levels of ${res.within}, on ${res.n} rows with every response (${fmt(res.dfe)} error DF). Between Subjects tests the effects on the sum of the responses; Within Subjects tests ${res.within} and its crossings with the effects on their contrasts (each response minus the first).`));
      repeatedReport(ctx, res, o);
      tail(ctx, ctx.top, res);
      return;
    }
    spec.add(controls,
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

  /* A multivariate test table as JMP's: one exact F Test row when the hypothesis has one DF or the
     design one response, else the four statistics with approximate F. */
  const MV_COLS = (exact) => [{ key: 'test', label: 'Test', fmt: 'text' }, { key: 'value', label: 'Value' }, { key: 'f', label: exact ? 'Exact F' : 'Approx. F' },
    { key: 'numdf', label: 'NumDF' }, { key: 'dendf', label: 'DenDF' }, { key: 'p', label: 'Prob>F', fmt: 'p' }];

  function repeatedReport(ctx, res, o) {
    const uni = !!o('univariate', false);
    const bs = ctx.outline('Between Subjects', { key: 'rm:between', info: 'p:fitmodel:repeated' });
    for (const t of res.between) {
      ctx.outline(t.effect, { parent: bs, key: `rmb:${t.effect}` }).add(ctx.rt({ columns: MV_COLS(t.exact), rows: t.rows }, { sortable: false, key: `rmb:${t.effect}` }));
    }
    const ws = ctx.outline('Within Subjects', { key: 'rm:within', info: 'p:fitmodel:repeated' });
    if (uni) {
      const so = ctx.outline('Sphericity Test', { parent: ws, key: 'rm:sphericity', info: 'p:fitmodel:repeated' });
      const s = res.sphericity;
      if (s) so.add(ctx.kv([['Mauchly Criterion', s.w], ['ChiSquare', s.chi2], ['DF', s.df, 'int'], ['Prob > Chisq', s.p, 'p']]));
      else so.add(ctx.note(res.sphericity_note));
    }
    for (const t of res.within_tests) {
      const rows = uni ? [...t.rows, ...t.univariate] : t.rows;
      const ob = ctx.outline(t.effect, { parent: ws, key: `rmw:${t.effect}` });
      if (rows.length) ob.add(ctx.rt({ columns: MV_COLS(t.exact), rows }, { sortable: false, key: `rmw:${t.effect}` }));
      else ob.add(ctx.note('No multivariate test here (see the note below); Univariate Tests Also gives the univariate one.'));
    }
    if (uni) {
      const e = res.epsilon;
      ws.add(ctx.note(`Univariate tests: the within effects as if the responses were stacked in one column, on the orthonormalized contrasts; F is the same in the three rows, Value is the epsilon that multiplies both degrees of freedom. G-G: Greenhouse and Geisser's ε = ${fmt(e.gg, { digits: 4 })}; H-F: Huynh and Feldt's (1976) ε = ${fmt(e.hf, { digits: 4 })} (capped at 1). Lecoutre's (1991) correction of H-F, which SAS reports as Huynh-Feldt-Lecoutre, is ${fmt(e.hf_lecoutre, { digits: 4 })} here (the same with one group of subjects); the lower bound is 1/${res.p} = ${fmt(e.lower, { digits: 4 })}.`));
    }
    if (o('matrices', false) && res.E) {
      ctx.outline('E Matrix', { key: 'mvE' }).add(matrixTable(ctx, res.E, res.labels, 'E: the residual sums of squares and cross products of the responses'),
        ctx.note('The tests use M′EM and M′HM, M the sum of the responses (Between Subjects) or their orthonormalized contrasts (Within Subjects).'));
    }
    if (o('partial', false) && res.partial_corr) ctx.outline('Partial Correlation', { key: 'mvpc' }).add(matrixTable(ctx, res.partial_corr, res.labels, 'Correlations of the residuals'), ctx.note(`DF = ${fmt(res.dfe)}.`));
  }

  function matrixTable(ctx, Mx, labels, caption) {
    return ctx.rt({ columns: [{ key: 'r', label: '', fmt: 'text' }, ...labels.map((l, j) => ({ key: `c${j}`, label: l }))], rows: Mx.map((row, i) => ({ r: labels[i], ...Object.fromEntries(row.map((v, j) => [`c${j}`, v])) })) }, { caption, sortable: false, key: caption });
  }

  /* ---- Generalized Regression ------------------------------------------------------------------------------
     JMP Pro's. The Model Launch: the Distribution, the Estimation Method (Lasso, Elastic Net, Ridge, with
     Adaptive for the first two; Forward and Pruned Forward Selection) and the Validation Method (AICc, BIC,
     KFold, Holdback, Leave-One-Out, or the launch's Validation column) with its settings. The fit's outline:
     the Model Summary per set, the Solution Path (the estimates and the validation curve against the size of
     the scaled estimates, or the step; the red line is the model shown: drag it or click a point) and the
     estimates on both scales. KFold and Holdback draw their rows from the report's seed (SM.predict.seed),
     a holdback and a Validation column follow predictive.prepare's rules, so the page's platforms agree. */
  const GR_METHODS = [['lasso', 'Lasso'], ['enet', 'Elastic Net'], ['ridge', 'Ridge'], ['forward', 'Forward Selection'], ['pruned', 'Pruned Forward Selection']];
  const GR_VALID = [['aicc', 'AICc'], ['bic', 'BIC'], ['kfold', 'KFold'], ['holdback', 'Holdback'], ['loo', 'Leave-One-Out'], ['validation', 'Validation Column']];
  const GR_LINK = { Normal: 'Identity', Binomial: 'Logit', Poisson: 'Log' };

  async function renderGenReg(ctx, M) {
    const ys = ctx.roles('y');
    await perResponse(ctx, ys, (y) => `Generalized Regression for ${y.name}`, (y, parent, st) => genregY(ctx, M, y, parent, st));
  }

  /* The fit's settings from the report's options (scoped by the response), and the payload. */
  function genregCfg(ctx, M, y) {
    const sc = y.id;
    const o = (k, d) => ctx.opt(k, d, sc);
    const vcol = ctx.name('validation');
    const valids = GR_VALID.filter(([k]) => (vcol ? ['validation', 'aicc', 'bic'] : ['aicc', 'bic', 'kfold', 'holdback', 'loo']).includes(k));
    let crit = o('gr:crit', vcol ? 'validation' : 'aicc');
    if (!valids.some((v) => v[0] === crit)) crit = valids[0][0];
    const method = GR_METHODS.some((x) => x[0] === o('gr:method', 'lasso')) ? o('gr:method', 'lasso') : 'lasso';
    const cfg = { dist: o('gr:dist', ctx.opt('dist', 'normal')), method, enet_alpha: o('gr:enet', 0.9), criterion: crit, n_grid: 40, choose: o(`gr:choose:${ctx.byLabel || ''}`, null), target: ctx.opt('target', null) };
    if (!GR_DISTS.some((x) => x[0] === cfg.dist)) cfg.dist = 'normal';
    if ((method === 'lasso' || method === 'enet') && o('gr:adaptive', false)) cfg.adaptive = true;
    if (crit === 'kfold') cfg.folds = o('gr:folds', 5);
    if (crit === 'holdback') cfg.portion = o('gr:holdback', 0.3);
    if (crit === 'kfold' || crit === 'holdback') cfg.seed = SM.predict.payload(ctx).seed;
    if (vcol) cfg.validation = vcol;
    return { cfg, valids, vcol, payload: { ...M.base, y: y.name, ...cfg } };
  }

  async function genregY(ctx, M, y, parent, st) {
    const P = pal();
    const sc = y.id;
    const o = (k, d) => ctx.opt(k, d, sc);
    const chooseKey = `gr:choose:${ctx.byLabel || ''}`;
    const { cfg, valids, payload } = genregCfg(ctx, M, y);
    // KFold and Leave-One-Out fit the path once per fold: say how far they are
    let res;
    const status = cfg.criterion === 'kfold' || cfg.criterion === 'loo' ? el('p', { class: 'sm-ob-note', role: 'status', text: `${cfg.criterion === 'loo' ? 'Leave-One-Out' : 'KFold'}: fitting the path of every fold…` }) : null;
    const off = status ? SM.engine.on('log', (ev) => { const k = /^smui:progress genreg (\d+) (\d+)/.exec((ev && ev.text) || ''); if (k) status.textContent = `${cfg.criterion === 'loo' ? 'Leave-One-Out' : 'KFold'}${ctx.byLabel ? ` (${ctx.byLabel})` : ''}: ${k[1]} of ${k[2]} fits…`; }) : null;
    if (status) (parent.body || parent.el || ctx.container).append(status);
    try { res = await ctx.call('fitmodel.genreg', payload); } finally { if (off) off(); if (status) status.remove(); }
    const m = res.model;
    const d = res.diag;
    const resampled = cfg.criterion === 'kfold' || cfg.criterion === 'holdback';
    st.menu = () => [
      ctx.check('Diagnostic Plots', 'gr:diag', sc, false, { disabled: m.distribution === 'Binomial' }),
      { label: 'Profilers', submenu: () => [ctx.check('Profiler', 'profiler', sc, false), ctx.check('Interaction Plots', 'interaction', sc, false)] },
      { label: 'Save Columns', submenu: () => [
        { label: 'Predicted Values', action: () => ctx.saveColumn(`Pred ${y.name}`, { rows: d.rows, values: d.predicted }) },
        { label: 'Residuals', action: () => ctx.saveColumn(`Residual ${y.name}`, { rows: d.rows, values: d.residual }) },
        resampled ? { label: 'Validation Column', action: () => ctx.saveColumn('Validation', { rows: d.rows, values: d.set }, { notes: `0 training, 1 validation: the rows of ${m.title} in ${ctx.report.title}`, modelingType: 'nominal' }) } : null,
      ].filter(Boolean) },
      { separator: true },
      { label: 'Model Dialog', action: () => ctx.report.relaunch() },
    ];
    // Model Launch: every change refits (and shows the best model again)
    const launch = ctx.outline('Model Launch', { parent, key: 'grlaunch', info: 'p:fitmodel:genreg' });
    const reset = () => ctx.set(chooseKey, null, sc, { rerun: false });
    const field = (label, input) => el('label', { class: 'sm-fm-opt' }, el('span', { text: label }), input);
    const mkSel = (label, key, value, choices) => { const s = el('select', { 'aria-label': label }, ...choices.map(([v, l]) => el('option', { value: v, text: l }))); s.value = value; s.addEventListener('change', () => { reset(); ctx.set(key, s.value, sc); }); return field(label, s); };
    const numIn = (label, key, value, ok) => {
      const i = el('input', { type: 'text', inputmode: 'decimal', size: 5, 'aria-label': label, class: 'sm-fm-num' });
      i.value = String(value);
      i.addEventListener('change', () => { const v = Number(String(i.value).replace(',', '.')); if (ok(v)) { reset(); ctx.set(key, v, sc); } else i.value = String(value); });
      return field(label, i);
    };
    const adaptive = el('input', { type: 'checkbox', 'aria-label': 'Adaptive' });
    adaptive.checked = !!cfg.adaptive;
    adaptive.addEventListener('change', () => { reset(); ctx.set('gr:adaptive', adaptive.checked, sc); });
    const seed = el('input', { type: 'text', inputmode: 'numeric', size: 8, 'aria-label': 'Random Seed', class: 'sm-fm-seed', placeholder: cfg.seed != null ? String(cfg.seed) : '' });
    seed.value = String(ctx.opt('seed', '') ?? '');
    seed.addEventListener('change', () => { const v = seed.value.trim(); if (v === '' || /^\d+$/.test(v)) { reset(); ctx.set('seed', v); } else seed.value = String(ctx.opt('seed', '') ?? ''); });
    launch.add(el('div', { class: 'sm-fm-controls' },
      mkSel('Distribution', 'gr:dist', cfg.dist, GR_DISTS),
      mkSel('Estimation Method', 'gr:method', cfg.method, GR_METHODS),
      cfg.method === 'lasso' || cfg.method === 'enet' ? el('label', { class: 'sm-fm-opt' }, adaptive, el('span', { text: 'Adaptive' })) : null,
      mkSel('Validation Method', 'gr:crit', cfg.criterion, valids),
      cfg.method === 'enet' ? numIn('Elastic Net Alpha', 'gr:enet', cfg.enet_alpha, (v) => v > 0 && v < 1) : null,
      cfg.criterion === 'kfold' ? numIn('Number of Folds', 'gr:folds', cfg.folds, (v) => Number.isInteger(v) && v >= 2 && v <= d.rows.length) : null,
      cfg.criterion === 'holdback' ? numIn('Holdback Proportion', 'gr:holdback', cfg.portion, (v) => v > 0 && v < 1) : null,
      resampled ? field('Random Seed', seed) : null));
    // the fit
    const fitOb = ctx.outline(m.title, { parent, key: 'grfit' });
    const sumOb = ctx.outline('Model Summary', { parent: fitOb, key: 'grsummary', info: 'p:fitmodel:grsummary' });
    sumOb.add(ctx.row(
      ctx.kv([['Response', m.response, 'text'], ['Distribution', m.distribution, 'text'], ['Estimation Method', m.method, 'text'], ['Validation Method', m.validation, 'text'],
        [m.distribution === 'Binomial' ? 'Probability Model Link' : 'Mean Model Link', GR_LINK[m.distribution], 'text'], m.target ? ['Target level', m.target, 'text'] : null,
        m.validation_column ? ['Validation column', m.validation_column, 'text'] : null, m.seed != null ? ['Random Seed', String(m.seed), 'text'] : null]),
      ctx.rt(res.summary, { key: 'grsummary', sortable: false })));
    genregPath(ctx, fitOb, res, { P, sc, chooseKey });
    ctx.outline('Parameter Estimates for Centered and Scaled Predictors', { parent: fitOb, key: 'grscaled' }).add(
      ctx.rt({ columns: [{ key: 'term', label: 'Term', fmt: 'text' }, { key: 'estimate', label: 'Estimate' }], rows: res.scaled }, { sortable: false, key: 'grscaled' }));
    // zeroed terms in grey (not a text column: Bootstrap finds the rows again by their text)
    const zeroed = res.estimates.filter((e) => e.zero).length;
    ctx.outline('Parameter Estimates for Original Predictors', { parent: fitOb, key: 'grest' }).add(
      ctx.rt({ columns: [{ key: 'term', label: 'Term', fmt: 'text' }, { key: 'estimate', label: 'Estimate' }], rows: res.estimates }, { sortable: false, key: 'grest', cellClass: (r) => (r.zero ? 'sm-fm-zeroed' : null) }),
      zeroed ? ctx.note(`${zeroed} term${zeroed > 1 ? 's' : ''} zeroed (in grey): the ${res.path.xlabel === 'Step' ? 'selection' : 'penalty'} leaves ${zeroed > 1 ? 'them' : 'it'} out.`) : null);
    if (o('gr:diag', false) && m.distribution !== 'Binomial') {
      const sets = ['Training', 'Validation', 'Test'].filter((_, k) => d.set.some((v) => v === k));
      SM.predict.actualByPredicted(ctx, fitOb, { kind: 'continuous', sets, residuals: { rows: d.rows, actual: d.actual, predicted: d.predicted, set: d.set } }, { key: 'gractual' });
    }
    if (o('profiler', false)) await profiler(ctx, parent, { sources: [{ kind: 'genreg', payload }], scope: sc });
    if (o('interaction', false)) await interactionPlots(ctx, parent, { kind: 'genreg', payload, scope: sc });
    tail(ctx, parent, res);
  }

  /* The Solution Path: the estimates on the scaled predictors (left) and the validation curve (right)
     against the magnitude of the scaled estimates or the step; the red line is the model shown. Drag it
     (in either plot) or click a point to show another; Reset to the Best Model goes back. */
  function genregPath(ctx, fitOb, res, { P, sc, chooseKey }) {
    const x = res.path.x;
    const at = (i) => x[Math.max(0, Math.min(x.length - 1, i))];
    const choose = (i) => { if (i !== res.chosen) ctx.set(chooseKey, i === res.best ? null : i, sc); };
    const nearest = (v) => { let k = 0; for (let i = 1; i < x.length; i++) if (Math.abs(x[i] - v) < Math.abs(x[k] - v)) k = i; return k; };
    const shapes = [{ type: 'line', x0: at(res.chosen), x1: at(res.chosen), yref: 'paper', y0: 0, y1: 1, line: { color: P.fit, width: 2 } }];
    if (res.best !== res.chosen) shapes.push({ type: 'line', x0: at(res.best), x1: at(res.best), yref: 'paper', y0: 0, y1: 1, line: { color: P.muted, width: 1, dash: 'dot' } });
    const step = res.path.xlabel === 'Step';
    const coefTr = res.path.coefs.map((c, i) => ({ type: 'scatter', mode: step ? 'lines+markers' : 'lines', x, y: c.values, name: SM.report.plotlyText(c.term), marker: { size: 4 }, line: { color: SM.util.PALETTE[i % SM.util.PALETTE.length], width: 1.4, shape: step ? 'hv' : 'linear' }, hovertemplate: `${SM.report.plotlyText(c.term)}: %{y:.4g}<extra></extra>` }));
    const lab = res.path.label;
    const critTr = [{ type: 'scatter', mode: 'lines+markers', x, y: res.path.curve, marker: { size: 5, color: P.point }, line: { color: P.point, width: 1.2 }, hovertemplate: `${step ? 'step' : 'point'} %{pointNumber}: ${lab} %{y:.5g}<extra></extra>` },
      { type: 'scatter', mode: 'markers', x: [at(res.chosen)], y: [res.path.curve[res.chosen]], marker: { size: 10, color: P.fit, symbol: 'diamond' }, hoverinfo: 'skip', showlegend: false }];
    const wire = (gd) => {
      gd.on('plotly_click', (ev) => { const pt = ev && ev.points && ev.points[0]; if (pt && pt.pointNumber != null && pt.curveNumber != null && (pt.data || {}).hoverinfo !== 'skip') choose(pt.pointNumber); });
      gd.on('plotly_relayout', (ev) => {
        const k0 = ev && Object.keys(ev).find((q) => /^shapes\[0\]\.x0$/.test(q));
        if (!k0) return;
        const k1 = Object.keys(ev).find((q) => /^shapes\[0\]\.x1$/.test(q));
        choose(nearest(k1 ? (ev[k0] + ev[k1]) / 2 : ev[k0]));
      });
    };
    const xaxis = { title: { text: res.path.xlabel }, ...(step ? { dtick: x.length > 12 ? undefined : 1 } : {}) };
    const pathOb = ctx.outline('Solution Path', { parent: fitOb, key: 'grpath', info: 'p:fitmodel:grpath', menu: () => [{ label: 'Reset to the Best Model', action: () => ctx.set(chooseKey, null, sc), disabled: res.chosen === res.best }] });
    const config = { edits: { shapePosition: true } };
    pathOb.add(ctx.row(
      withCode(ctx.plot(coefTr, { xaxis, yaxis: { title: { text: 'Parameter Estimates' } }, shapes, hovermode: 'x', showlegend: false }, { width: W(400), height: 300, title: 'solution path', select: false, config, onDraw: wire }), ctx.code(codeOf(res, 'path'))),
      withCode(ctx.plot(critTr, { xaxis, yaxis: { title: { text: lab } }, shapes, showlegend: false }, { width: W(340), height: 300, title: `${lab} path`, select: false, config, onDraw: wire }), ctx.code(codeOf(res, 'curve')))),
    ctx.note(`${step ? 'Each step enters (or, pruned, removes) a term' : 'Each point is a penalty λ, from the one that keeps every term out'}; the red line is the model shown (${res.chosen === res.best ? `the smallest ${lab}` : 'chosen on the plot; the dotted line is the best'}). Drag it, or click a point, to show another.`));
    return pathOb;
  }

  /* ---- Instrumental Variables ---------------------------------------------------------------------------
     statsmodels' IV2SLS. The roles Endogenous (columns of the model effects:
     every effect that holds one is endogenous) and Instruments (the excluded
     instruments; the exogenous effects instrument themselves). Robust
     Standard Errors are the Standard Least Squares choices (option 'robust',
     scoped by the response). */
  async function renderIV(ctx, M) {
    const ys = ctx.roles('y');
    await perResponse(ctx, ys, (y) => `Instrumental Variables Fit for ${y.name}`, (y, parent, st) => ivY(ctx, M, y, parent, st));
  }

  function ivPayload(ctx, M, y) {
    const rob = robustOf(ctx, y.id);
    return { ...M.base, y: y.name, endog: ctx.names('endog'), instruments: ctx.names('instruments'), ...(rob ? { robust: rob } : {}) };
  }

  const TEST_COLS = [{ key: 'test', label: 'Test', fmt: 'text' }, { key: 'stat', label: 'Statistic' }, { key: 'df', label: 'DF' }, { key: 'dfden', label: 'DF Den' }, { key: 'p', label: 'p-Value', fmt: 'p' }];

  async function ivY(ctx, M, y, parent, st) {
    const P = pal();
    const sc = y.id;
    const o = (k, d) => ctx.opt(k, d, sc);
    const payload = ivPayload(ctx, M, y);
    const res = await ctx.call('fitmodel.iv', { ...payload, alpha: ctx.alpha, ols: !!o('iv:ols', false) });
    const m = res.model;
    const d = res.diag;
    st.menu = () => ivMenu(ctx, y, res, sc);
    parent.add(el('p', { class: 'sm-fm-modelline' }, ...[['Response', m.response], ['Endogenous', m.endogenous.join(', ')], ['Instruments', m.instruments.join(', ')],
      ['Estimation', 'Two-Stage Least Squares'], ['Standard Errors', m.cov], ['Observations', fmt(m.n)]].map(([k, v]) => el('span', null, el('b', { text: `${k}: ` }), v))));
    const top = [];
    if (o('iv:actual', true)) top.push(actualByPredicted(ctx, parent, d, null, y.name, 'p:fitmodel:iv', undefined, codeOf(res, 'actual')).el);
    if (o('summaryOfFit', true)) {
      const s = ctx.outline('Summary of Fit', { parent, key: 'sof', info: 'p:fitmodel:iv' });
      s.add(ctx.kv([...res.summary.rows.map((r) => [r.stat, r.value, r.stat === 'Observations' ? 'int' : 'num']),
        res.whole ? [`Wald F (${fmt(res.whole.df_num)}, ${fmt(res.whole.df_den)} DF)`, res.whole.f] : null, res.whole ? ['Prob > F', res.whole.p, 'p'] : null]));
      top.push(s.el);
    }
    if (top.length > 1) parent.add(ctx.row(...top));
    if (o('iv:first', true)) ivFirstStage(ctx, parent, res, sc);
    if (o('estimates', true)) {
      const showCI = o('showCI', false);
      const cols = res.estimates.columns.map((c) => ({ ...c, hidden: ['lower', 'upper'].includes(c.key) && !showCI }));
      ctx.outline('Second Stage Parameter Estimates', { parent, key: 'estimates', info: res.robust ? 'p:fitmodel:robust' : 'p:fitmodel:iv' }).add(ctx.rt({ columns: cols, rows: res.estimates.rows },
        { key: 'estimates', caption: res.robust ? `Robust standard errors: ${res.robust.label}; t tests on ${fmt(res.robust.df)} DF` : undefined }));
    }
    if (o('effectTests', true) && res.effect_tests.rows.length) {
      ctx.outline('Effect Tests', { parent, key: 'efftests' }).add(ctx.rt(res.effect_tests, { key: 'efftests', caption: `Wald F tests${res.robust ? ` with the robust covariance (${res.robust.label})` : ''}` }));
    }
    if (o('iv:tests', true)) ivTests(ctx, parent, res);
    if (o('iv:ols', false) && res.ols) {
      ctx.outline('OLS and 2SLS', { parent, key: 'ivols', info: 'p:fitmodel:iv', menu: () => [{ label: 'Remove', action: () => ctx.set('iv:ols', false, sc) }] }).add(
        ctx.rt(res.ols, { key: 'ivols' }),
        ctx.note(`Least squares (RSquare ${fmt(res.ols_rsq, { digits: 4 })}) beside two-stage least squares, with the same standard errors (${m.cov.toLowerCase()}). OLS is biased when an endogenous column is correlated with the error; 2SLS is consistent but less precise: the ratio of the standard errors is the price of the instruments.`));
    }
    if (o('iv:resid', true)) {
      const yn = SM.report.plotlyText(y.name);
      ctx.outline('Residual by Predicted Plot', { parent, key: 'residpred' }).add(rowPlot(ctx, { x: d.predicted, y: d.residual, rows: d.rows, xTitle: `${yn} Predicted`, yTitle: `${yn} Residual`, hlines: [{ y: 0, color: P.mean }], title: `${y.name} residual by predicted` }),
        ctx.code(codeOf(res, 'resid')), ctx.note('The residuals of the model itself, y − Xb (not of the second stage), against its predictions Xb.'));
    }
    if (o('plotResidRow', false)) {
      ctx.outline('Residual by Row Plot', { parent, key: 'residrow' }).add(rowPlot(ctx, { x: d.rows.map((r) => r + 1), y: d.residual, rows: d.rows, xTitle: 'Row Number', yTitle: `${SM.report.plotlyText(y.name)} Residual`, hlines: [{ y: 0, color: P.mean }], width: 460, title: `${y.name} residual by row` }), ctx.code(codeOf(res, 'residRow')));
    }
    if (o('profiler', false)) await profiler(ctx, parent, { sources: [{ kind: 'iv', payload }], scope: sc });
    tail(ctx, parent, res);
  }

  function ivFirstStage(ctx, parent, res, sc) {
    const ob = ctx.outline('First Stage', { parent, key: 'ivfirst', info: 'p:fitmodel:ivfirst' });
    const multi = res.first.length > 1;
    const rows = res.first.map((f) => ({ endog: f.label, rsq: f.rsq, partial: f.partial_rsq, shea: f.shea_rsq, f: f.f, df: f.df_num, dfden: f.df_den, p: f.p, weak: f.weak ? 'weak: F < 10' : '', _weak: f.weak }));
    const cols = [{ key: 'endog', label: 'Endogenous', fmt: 'text' }, { key: 'rsq', label: 'RSquare' }, { key: 'partial', label: 'Partial RSquare' },
      { key: 'shea', label: 'Shea Partial RSquare', hidden: !multi }, { key: 'f', label: 'F Ratio' }, { key: 'df', label: 'Num DF', fmt: 'int' }, { key: 'dfden', label: 'Den DF' },
      { key: 'p', label: 'Prob > F', fmt: 'p' }, { key: 'weak', label: '', fmt: 'text' }];
    ob.add(ctx.rt({ columns: cols, rows }, { key: 'ivfirst', sortable: false, caption: `The excluded instruments in each first stage${res.robust ? `: robust Wald F tests (${res.robust.label})` : ''}`,
      cellClass: (r, c) => ((c.key === 'f' || c.key === 'weak') && r._weak ? 'sm-fm-weak' : null) }));
    const weak = res.first.filter((f) => f.weak);
    if (weak.length) ob.add(ctx.warn(`Weak instruments: the first-stage F of ${weak.map((f) => f.label).join(', ')} is below 10, Staiger and Stock's rule of thumb. 2SLS is then biased toward least squares and its tests and intervals are unreliable; look for stronger instruments.`));
    ob.add(ctx.kv([['Cragg–Donald Wald F', res.weak.cragg_donald], ['Endogenous columns', res.weak.k_endog, 'int'], ['Excluded instrument columns', res.weak.excluded, 'int']], { caption: 'Weak identification' }),
      ctx.note(`The F ratio tests the excluded instruments in the regression of each endogenous column on all the instruments; the partial RSquare is their share of what the exogenous effects leave unexplained${multi ? ', and Shea\'s partial RSquare the same after the other endogenous columns are accounted for' : ''}. Cragg and Donald's statistic is the smallest eigenvalue of the first stages' joint F (with one endogenous column, its first-stage F). Stock and Yogo (2005) give its critical values by the number of endogenous columns and instruments, for a largest tolerable bias of 2SLS relative to least squares or size distortion of its 5% Wald test (with one endogenous column and one instrument, 16.38 for a 10% maximal size); they assume homoscedastic errors${res.robust ? ', while the F ratios above are robust Wald tests' : ''}.`));
    for (const f of res.first) {
      const fo = ctx.outline(`First Stage for ${f.label}`, { parent: ob, key: `ivfs:${f.label}`, closed: true });
      fo.add(ctx.rt({ columns: f.estimates.columns.map((c) => ({ ...c, hidden: ['lower', 'upper'].includes(c.key) })), rows: f.estimates.rows }, { key: `ivfs:${f.label}`, caption: `${f.label} on the instruments: RSquare ${fmt(f.rsq, { digits: 4 })}` }));
    }
  }

  function ivTests(ctx, parent, res) {
    const T = res.tests;
    const e = T.endog;
    const rows = [{ test: res.robust ? 'Wu–Hausman F (robust regression F)' : 'Wu–Hausman F', stat: e.f, df: e.df_num, dfden: e.df_den, p: e.p }];
    if (e.durbin != null) rows.push({ test: 'Durbin χ² (score)', stat: e.durbin, df: e.durbin_df, dfden: null, p: e.durbin_p });
    ctx.outline('Endogeneity Test', { parent, key: 'ivendog', info: 'p:fitmodel:ivtests' }).add(ctx.rt({ columns: TEST_COLS, rows }, { key: 'ivendog', sortable: false }),
      ctx.note(`Durbin–Wu–Hausman, regression-based: the first-stage residuals of ${res.model.endogenous_columns.join(', ')} added to the least squares fit. H0: the endogenous columns are in fact exogenous, least squares is consistent (and efficient). A small p-value says they are endogenous and 2SLS is needed.${res.robust ? ' With robust standard errors the F test uses them (Stata\'s robust regression F); Durbin\'s χ² assumes homoscedastic errors and is left out.' : ' Durbin\'s χ² is n(SSR_OLS − SSR_augmented)/SSR_OLS, ivendog\'s Durbin–Wu–Hausman χ².'}`));
    const ov = ctx.outline('Overidentification Test', { parent, key: 'ivoverid', info: 'p:fitmodel:ivtests' });
    const O = T.overid;
    if (!O) { ov.add(ctx.note('Exactly identified: as many excluded instrument columns as endogenous columns, so there are no overidentifying restrictions to test.')); return; }
    ov.add(ctx.rt({ columns: TEST_COLS, rows: [{ test: O.test === 'Sargan' ? 'Sargan χ²' : 'Hansen J χ²', stat: O.stat, df: O.df, dfden: null, p: O.p }] }, { key: 'ivoverid', sortable: false }),
      ctx.note(O.test === 'Sargan' ? `Sargan's test: n times the RSquare of the 2SLS residuals on all the instruments, χ² on the ${O.df} overidentifying restriction${O.df > 1 ? 's' : ''}. H0: every instrument is uncorrelated with the error. A small p-value says some instrument is invalid, or the model is misspecified; it cannot tell which.`
        : `Hansen's J: the minimised criterion of the efficient two-step GMM estimate, with the weight matrix of the robust covariance (${res.robust.label}); χ² on the ${O.df} overidentifying restriction${O.df > 1 ? 's' : ''}. H0: every instrument is uncorrelated with the error.`));
  }

  function ivMenu(ctx, y, res, sc) {
    const c = (label, key, d) => ctx.check(label, key, sc, d);
    const d = res.diag;
    const sv = (name, values) => () => ctx.saveColumn(name, { rows: d.rows, values });
    return [
      { label: 'Regression Reports', submenu: () => [c('Summary of Fit', 'summaryOfFit', true), c('First Stage', 'iv:first', true), c('Second Stage Parameter Estimates', 'estimates', true),
        c('Effect Tests', 'effectTests', true), c('Endogeneity and Overidentification Tests', 'iv:tests', true), { separator: true }, c('Show All Confidence Intervals', 'showCI', false)] },
      c('OLS Beside 2SLS', 'iv:ols', false),
      { label: 'Robust Standard Errors', submenu: () => robustMenu(ctx, y, 'iv') },
      { label: 'Row Diagnostics', submenu: () => [c('Plot Actual by Predicted', 'iv:actual', true), c('Plot Residual by Predicted', 'iv:resid', true), c('Plot Residual by Row', 'plotResidRow', false)] },
      { label: 'Factor Profiling', submenu: () => [c('Profiler', 'profiler', false)] },
      { label: 'Save Columns', submenu: () => [
        { label: 'Predicted Values', action: sv(`Predicted ${y.name}`, d.predicted) },
        { label: 'Residuals', action: sv(`Residual ${y.name}`, d.residual) },
        ...d.first.flatMap((f) => [{ label: `First Stage Predicted ${f.label}`, action: sv(`First Stage Pred ${f.label}`, f.fitted) }, { label: `First Stage Residual ${f.label}`, action: sv(`First Stage Resid ${f.label}`, f.resid) }]),
      ] },
      { separator: true },
      { label: 'Model Dialog', action: () => ctx.report.relaunch() },
    ];
  }

  /* ---- Quantile Regression ----------------------------------------------------------------------------------
     statsmodels' QuantReg. The quantile (qrTau, from the launch dialog or
     Model Launch), the standard errors (qrCov), kernel (qrKernel), bandwidth
     (qrBw) and the process quantiles (qrTaus, text such as '0.05 to 0.95 by
     0.05' or '0.1, 0.5, 0.9') are options of the whole report. */
  function parseTaus(text) {
    const s = String(text || '').trim().toLowerCase();
    const m = /^([0-9.]+)\s*to\s*([0-9.]+)\s*by\s*([0-9.]+)$/.exec(s);
    let out = [];
    if (m) {
      const a = Number(m[1]), b = Number(m[2]), h = Number(m[3]);
      if (!(a > 0 && b < 1 && a <= b && h > 0) || (b - a) / h > 98) return null;
      for (let i = 0; a + i * h <= b + 1e-9; i++) out.push(Math.round((a + i * h) * 1e6) / 1e6);
    } else {
      out = s.split(/[\s,;]+/).filter(Boolean).map(Number);
      if (!out.length || out.some((v) => !(v > 0 && v < 1))) return null;
    }
    out = [...new Set(out)].sort((u, v) => u - v);
    return out.length && out.length <= 99 ? out : null;
  }

  async function renderQR(ctx, M) {
    const ys = ctx.roles('y');
    await perResponse(ctx, ys, (y) => `Quantile Regression Fit for ${y.name}`, (y, parent, st) => qrY(ctx, M, y, parent, st));
  }

  function qrPayload(ctx, M, y) {
    return { ...M.base, y: y.name, tau: Number(ctx.opt('qrTau', 0.5)), qr_cov: ctx.opt('qrCov', 'robust'), kernel: ctx.opt('qrKernel', 'epa'), bandwidth: ctx.opt('qrBw', 'hsheather') };
  }

  async function qrY(ctx, M, y, parent, st) {
    const P = pal();
    const sc = y.id;
    const o = (k, d) => ctx.opt(k, d, sc);
    const payload = qrPayload(ctx, M, y);
    const tausText = ctx.opt('qrTaus', QR_TAUS);
    const taus = parseTaus(tausText) || parseTaus(QR_TAUS);
    const process = !!o('qr:process', true);
    const res = await ctx.call('fitmodel.quantreg', { ...payload, taus, process, alpha: ctx.alpha });
    const m = res.model;
    const d = res.diag;
    st.menu = () => qrMenu(ctx, y, res, sc);
    parent.add(el('p', { class: 'sm-fm-modelline' }, ...[['Response', m.response], ['Quantile', fmt(m.tau)], ['Standard Errors', m.cov_label], ['Kernel', m.kernel_label], ['Bandwidth', m.bandwidth_label], ['Observations', fmt(m.n)]]
      .map(([k, v]) => el('span', null, el('b', { text: `${k}: ` }), v))));
    // Model Launch: the options of the fit
    const launch = ctx.outline('Model Launch', { parent, key: 'qrlaunch', info: 'p:fitmodel:quantreg' });
    const mkSel = (label, key, value, choices) => { const s = el('select', { 'aria-label': label }, ...choices.map(([v, l]) => el('option', { value: v, text: l }))); s.value = value; s.addEventListener('change', () => ctx.set(key, s.value)); return el('label', { class: 'sm-fm-opt' }, el('span', { text: label }), s); };
    const tauIn = el('input', { type: 'text', inputmode: 'decimal', size: 5, 'aria-label': 'Quantile', class: 'sm-fm-num' });
    tauIn.value = String(m.tau);
    tauIn.addEventListener('change', () => { const v = Number(tauIn.value.replace(',', '.')); if (v > 0 && v < 1) ctx.set('qrTau', v); else { SM.ui.toast('The quantile must lie strictly between 0 and 1'); tauIn.value = String(m.tau); } });
    const procIn = el('input', { type: 'text', size: 24, 'aria-label': 'Quantile process' });
    procIn.value = tausText;
    procIn.addEventListener('change', () => { if (parseTaus(procIn.value)) ctx.set('qrTaus', procIn.value.trim()); else { SM.ui.toast('Quantiles between 0 and 1: a list (0.1, 0.5, 0.9) or a range (0.05 to 0.95 by 0.05)'); procIn.value = tausText; } });
    launch.add(el('div', { class: 'sm-fm-controls', dataset: { noexport: '' } },
      el('label', { class: 'sm-fm-opt' }, el('span', { text: 'Quantile τ' }), tauIn),
      mkSel('Standard Errors', 'qrCov', m.cov, QR_COVS), mkSel('Kernel', 'qrKernel', m.kernel, QR_KERNELS), mkSel('Bandwidth', 'qrBw', m.bandwidth, QR_BWS),
      el('label', { class: 'sm-fm-opt' }, el('span', { text: 'Quantile Process' }), procIn)));
    const top = [];
    if (o('qr:actual', true)) {
      const ob = ctx.outline('Actual by Predicted Plot', { parent, key: 'actpred', info: 'p:fitmodel:quantreg' });
      const [lo, hi] = extent(d.predicted, d.actual);
      ob.add(rowPlot(ctx, { x: d.predicted, y: d.actual, rows: d.rows, xTitle: `${SM.report.plotlyText(y.name)} Predicted ${fmt(m.tau)} quantile`, yTitle: `${SM.report.plotlyText(y.name)} Actual`, lines: [lineTrace([lo, hi], [lo, hi], P.fit, 'solid', 1.4)], width: 400, height: 320, title: `${y.name} actual by predicted quantile` }),
        ctx.code(codeOf(res, 'actual')), ctx.note(`About ${fmt(100 * (1 - m.tau))}% of the rows should lie above the line (here ${fmt(100 * (1 - res.stats.below), { digits: 1 })}%).`));
      top.push(ob.el);
    }
    if (o('summaryOfFit', true)) {
      const s = ctx.outline('Summary of Fit', { parent, key: 'sof', info: 'p:fitmodel:quantreg' });
      s.add(ctx.kv(res.summary.rows.map((r) => [r.stat, r.value, ['Iterations', 'Observations'].includes(r.stat) ? 'int' : 'num'])));
      top.push(s.el);
    }
    if (top.length > 1) parent.add(ctx.row(...top));
    if (o('estimates', true)) {
      const showCI = o('showCI', true);
      const cols = res.estimates.columns.map((c) => ({ ...c, hidden: ['lower', 'upper'].includes(c.key) && !showCI }));
      ctx.outline('Parameter Estimates', { parent, key: 'estimates', info: 'p:fitmodel:quantreg' }).add(ctx.rt({ columns: cols, rows: res.estimates.rows },
        { key: 'estimates', caption: `The ${fmt(m.tau)} quantile; standard errors: ${m.cov_label.toLowerCase()}, t tests on ${fmt(m.n - res.estimates.rows.length)} DF` }));
    }
    if (process && res.process) qrProcess(ctx, parent, res, sc);
    if (res.lines && o('qr:lines', true)) qrLines(ctx, parent, res, y);
    if (o('qr:resid', false)) {
      ctx.outline('Residual by Predicted Plot', { parent, key: 'residpred' }).add(rowPlot(ctx, { x: d.predicted, y: d.residual, rows: d.rows, xTitle: `${SM.report.plotlyText(y.name)} Predicted ${fmt(m.tau)} quantile`, yTitle: `${SM.report.plotlyText(y.name)} Residual`, hlines: [{ y: 0, color: P.mean }], title: `${y.name} quantile residual by predicted` }), ctx.code(codeOf(res, 'resid')));
    }
    if (o('profiler', false)) await profiler(ctx, parent, { sources: [{ kind: 'qr', payload }], scope: sc });
    tail(ctx, parent, res);
  }

  function qrProcess(ctx, parent, res, sc) {
    const pr = res.process;
    const ols = res.ols;
    const ob = ctx.outline('Quantile Process', { parent, key: 'qrprocess', info: 'p:fitmodel:qrprocess', menu: () => [ctx.check('Quantile Process Estimates', 'qr:procTable', sc, false), { label: 'Remove', action: () => ctx.set('qr:process', false, sc) }] });
    const plots = pr.terms.map((term, i) => withCode(bandPlot(ctx, { x: pr.taus, est: pr.estimate[i], lower: pr.lower[i], upper: pr.upper[i], ref: ols.estimate[i], refBand: [ols.lower[i], ols.upper[i]], vline: res.tau,
      hover: pr.taus.map((t) => `τ = ${t}`), xTitle: 'Quantile τ', yTitle: term, title: `${term} quantile process`, width: 300, height: 230, xaxis: { range: [0, 1] } }), ctx.code((codeOf(res, 'process') || [])[i])));
    ob.add(ctx.row(...plots), ctx.note(`Each coefficient at the ${pr.taus.length} quantiles of the process, with its pointwise ${fmt(100 * (1 - ctx.alpha))}% band; the dashed line and the pale band are the least squares estimate and its interval, the dotted line the report's quantile. A coefficient whose curve leaves the least squares band acts differently in the tails than at the mean.`));
    if (ctx.opt('qr:procTable', false, sc)) {
      const cols = [{ key: 'tau', label: 'Quantile' }, { key: 'r1', label: 'Pseudo RSquare', digits: 4 }, ...pr.terms.flatMap((t, i) => [{ key: `b${i}`, label: t }, { key: `s${i}`, label: `${t} Std Error`, hidden: true }])];
      const rows = pr.taus.map((t, j) => ({ tau: t, r1: pr.r1[j], ...Object.fromEntries(pr.terms.flatMap((_, i) => [[`b${i}`, pr.estimate[i][j]], [`s${i}`, pr.se[i][j]]])) }));
      ctx.outline('Quantile Process Estimates', { parent: ob, key: 'qrproctable' }).add(ctx.rt({ columns: cols, rows }, { key: 'qrproctable', sortable: false, caption: 'The estimates at each quantile (right click: Columns adds the standard errors)' }));
    }
  }

  function qrLines(ctx, parent, res, y) {
    const P = pal();
    const L = res.lines;
    const traces = [{ type: L.points.x.length > 4000 ? 'scattergl' : 'scatter', mode: 'markers', x: L.points.x, y: L.points.y, rows: L.points.rows, marker: { size: L.points.x.length > 500 ? 4 : 6, color: P.point }, name: 'Rows', showlegend: false }];
    const taus = L.lines.map((l) => l.tau);
    const lo = Math.min(...taus), hi = Math.max(...taus);
    for (const l of L.lines) {
      const c = SM.util.ramp(hi > lo ? (l.tau - lo) / (hi - lo) : 0.5);
      traces.push({ type: 'scatter', mode: 'lines', x: L.x, y: l.y, line: { color: c, width: l.current ? 2.6 : 1.6 }, name: `τ = ${l.tau}`, hovertemplate: `τ = ${l.tau}: %{y:.5g}<extra></extra>` });
    }
    traces.push({ type: 'scatter', mode: 'lines', x: L.x, y: L.ols, line: { color: P.text, width: 1.3, dash: 'dash' }, name: 'Least squares', hoverinfo: 'skip' });
    ctx.outline('Quantile Regression Plot', { parent, key: 'qrlines', info: 'p:fitmodel:quantreg', menu: () => [{ label: 'Remove', action: () => ctx.set('qr:lines', false, y.id) }] }).add(
      ctx.plot(traces, { showlegend: true, legend: { title: { text: 'Quantile' } }, xaxis: { title: { text: SM.report.plotlyText(L.factor) } }, yaxis: { title: { text: SM.report.plotlyText(y.name) } }, margin: { l: 58, r: 12, t: 8, b: 44 } }, { width: W(520), height: 340, title: `${y.name} quantile lines` }),
      ctx.code(codeOf(res, 'lines')),
      ctx.note(`The fitted quantiles of ${y.name} over ${L.factor} (the report's quantile drawn thicker) and the least squares line (dashed). Lines that fan out mean the spread of ${y.name} changes with ${L.factor}.`));
  }

  function qrMenu(ctx, y, res, sc) {
    const c = (label, key, d) => ctx.check(label, key, sc, d);
    const d = res.diag;
    const cov = res.model.cov;
    return [
      { label: 'Regression Reports', submenu: () => [c('Summary of Fit', 'summaryOfFit', true), c('Parameter Estimates', 'estimates', true), c('Show All Confidence Intervals', 'showCI', true)] },
      c('Quantile Process', 'qr:process', true),
      c('Quantile Process Estimates', 'qr:procTable', false),
      { label: 'Standard Errors', submenu: () => QR_COVS.map(([k, l]) => ({ label: l, checked: cov === k, action: () => ctx.set('qrCov', k) })) },
      { label: 'Row Diagnostics', submenu: () => [c('Plot Actual by Predicted', 'qr:actual', true), c('Plot Residual by Predicted', 'qr:resid', false), ctx.check('Quantile Regression Plot', 'qr:lines', sc, true, { disabled: !res.lines })] },
      { label: 'Factor Profiling', submenu: () => [c('Profiler', 'profiler', false)] },
      { label: 'Save Columns', submenu: () => [
        { label: 'Predicted Quantile', action: () => ctx.saveColumn(`Pred Quantile(${res.tau}) ${y.name}`, { rows: d.rows, values: d.predicted }, { notes: `the fitted ${res.tau} quantile of ${y.name}, from ${ctx.report.title}` }) },
        { label: 'Residuals', action: () => ctx.saveColumn(`Quantile(${res.tau}) Residual ${y.name}`, { rows: d.rows, values: d.residual }) },
      ] },
      { separator: true },
      { label: 'Model Dialog', action: () => ctx.report.relaunch() },
    ];
  }

  /* ---- Help ---------------------------------------------------------------------------------------------- */
  const MORE = { label: 'Fit Model', id: 'help-p-fitmodel' };
  const TOPICS = {
    'p:fitmodel': {
      kicker: 'Analyze', title: 'Fit Model',
      lead: 'Linear and generalized models of one or more responses: choose the Y, build the model from effects, pick a personality and press OK. The model is JMP\'s, the numbers are statsmodels\'.',
      sections: [
        { heading: 'Roles', choices: [['Y', 'The response. A continuous Y gets Standard Least Squares by default, a nominal one Nominal Logistic, an ordinal one Ordinal Logistic.'], ['Weight', 'Weights of the rows (least squares: WLS weights; GLM: variance weights).'], ['Freq', 'Each row counts that many times; the degrees of freedom follow.'], ['Validation', 'Generalized Regression: a column with 0 (Training), 1 (Validation) and 2 (Test), or those words; the other personalities ignore it.'], ['Endogenous', 'Instrumental Variables: the columns of the model effects that are correlated with the error; every effect that holds one is endogenous.'], ['Instruments', 'Instrumental Variables: the excluded instruments, columns that move the endogenous ones but have no effect of their own on Y (they stay out of the model effects).'], ['Offset', 'A known part of the linear predictor (GLM, GEE), for example log exposure.'], ['Subject', 'Generalized Estimating Equations: the rows with the same value belong together (a subject, a cluster).'], ['Time', 'GEE: the order of a subject\'s rows, for the AR(1) and Unstructured working correlations.'], ['Subgroup', 'GEE: a grouping within the subjects, for the Nested working correlation.'], ['By', 'A separate fit for each level.']] },
        { heading: 'Construct Model Effects', text: 'Select columns on the left and press Add. Cross makes an interaction, a column crossed with itself a power; Nest puts an effect within a column (B[A]). The Macros add whole models; Attributes > Random Effect marks an effect as random (Mixed Model, or REML in Standard Least Squares).' },
        { heading: 'Coding', text: 'Nominal and ordinal factors are effect coded (a level\'s parameter is its difference from the average of the levels, the last level the negative sum); continuous columns in crossings and powers are centred at their means, as JMP\'s Center Polynomials.' },
      ],
      more: MORE,
    },
    'p:fitmodel:effects': {
      kicker: 'Fit Model', title: 'Construct Model Effects',
      lead: 'The effects of the model. Select columns in the list of columns, then:',
      sections: [{ choices: [['Add', 'each selected column as a main effect'], ['Cross', 'the selected columns crossed together, or with the selected effects (a column with itself: its square)'], ['Nest', 'the selected effects nested in the selected columns: B[A]'], ['Macros', 'Full Factorial (every crossing), Factorial to Degree, Factorial Sorted (by degree), Response Surface (main effects, crossings, squares), Polynomial to Degree'], ['Degree', 'the degree of Factorial to Degree and Polynomial to Degree'], ['Attributes', 'Random Effect: the effect\'s levels are a random sample (a variance component)'], ['Remove', 'the selected effects (or double click one)'], ['No Intercept', 'fit without the constant term']] },
        { heading: 'Dragging', text: 'Columns dragged onto the list of effects, from the list of columns or from a role, go in as main effects (from a role they leave it; dropped on an effect, one takes that effect\'s place). An effect in the list can be dragged too: up or down the list to change the order, a main effect onto a role to move its column there, and anywhere else in the dialog, such as the list of columns, to take it out of the model. A drag cancelled with Escape changes nothing.' }],
      more: MORE,
    },
    'p:fitmodel:personality': {
      kicker: 'Fit Model', title: 'Personality',
      lead: 'How the model is fitted and reported.',
      sections: [{ choices: [['Standard Least Squares', 'OLS (WLS with a weight): tests, leverage plots, least squares means, profilers. With random effects: REML.'], ['Stepwise', 'Chooses the effects by p-values, AICc or BIC.'], ['Generalized Linear Model', 'statsmodels GLM: normal, binomial, Poisson, gamma, inverse Gaussian, negative binomial, with a link.'], ['Nominal Logistic', 'Multinomial logit: the log odds of each level against the last.'], ['Ordinal Logistic', 'Cumulative logit (or probit) for ordered levels.'], ['Generalized Estimating Equations', 'statsmodels GEE: a marginal generalized linear model of rows grouped by a Subject, with a working correlation and robust standard errors.'], ['Mixed Model', 'MixedLM by REML, random effects from the Random Effect attribute.'], ['MANOVA', 'Several continuous responses tested together.'], ['Generalized Regression', 'Penalized and stepwise fits (lasso, elastic net, ridge, their adaptive forms, forward selection), the model picked by AICc, BIC, KFold, holdback, leave-one-out or a Validation column.'], ['Instrumental Variables', 'Two-stage least squares (statsmodels IV2SLS) for effects that are correlated with the error: cast them into Endogenous and the excluded instruments into Instruments.'], ['Quantile Regression', 'statsmodels QuantReg: a quantile of Y (the Quantile τ; 0.5 is the median) rather than its mean, with the quantile process.']] },
        { heading: 'Emphasis', text: 'For Standard Least Squares: Effect Leverage opens the leverage plots and the effect details, Effect Screening the sorted estimates and the profiler, Minimal Report only the tables.' }],
      more: MORE,
    },
    'p:fitmodel:summary': {
      kicker: 'Fit Model', title: 'Effect Summary',
      lead: 'The effects by LogWorth, −log₁₀ of the p-value of their test (the line is at p = 0.01). FDR adjusts the p-values for the number of effects (Benjamini and Hochberg).',
      sections: [{ heading: 'Editing the model', choices: [
        ['An effect\'s line', 'Click it to choose the effect for Remove; click it again to let it go.'],
        ['Remove', 'Refits the model without the chosen effect, in this report.'],
        ['Edit', 'Opens the launch dialog with the model (the red triangle\'s Model Dialog), to change it and fit again.'],
        ['Undo', 'Puts back the model as it was before the last Remove, up to 20 steps back.'],
        ['FDR', 'Shows LogWorth and p-values adjusted for the number of effects by Benjamini and Hochberg\'s false discovery rate, so that a few small p-values among many effects are not taken at face value.'],
      ] }],
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
    // The shared profiler's red triangle (smui-profiler.js) is explained after the controls.
    'p:fitmodel:profiler': () => {
      const shared = (SM.info && SM.info.get('p:profiler')) || null;
      return {
        kicker: 'Fit Model', title: 'Profilers',
        lead: 'The Prediction Profiler shows how the prediction changes with each factor, the others held at their current values. Drag a red dashed line, click a plot, or type a value; the prediction and its confidence interval are on the left.',
        sections: [
          { heading: 'Prediction Profiler', choices: [
            ['The red dashed line', 'Drag it along a factor\'s plot to set that factor: every response\'s prediction and interval follow, and so do the curves of the other factors.'],
            ['A click in a plot', 'Sets the factor to the value clicked.'],
            ['The value box', 'Under each plot: type a continuous factor\'s value and press Enter, or pick a categorical factor\'s level.'],
            ['The slider', 'Under a continuous factor: moves it over its range.'],
            ['The desirability plots', 'With Desirability Functions on, at the right of each response: click one to set that response\'s desirability.'],
          ] },
          ...((shared && shared.sections) || []).map((x) => ({ ...x, heading: x.heading || 'Its red triangle' })),
          { heading: 'Contour Profiler', text: 'The prediction over two continuous factors as a contour map, the rows of the table on it.', choices: [
            ['Horizontal, Vertical', 'The two continuous factors of the map; choosing one that is the other\'s swaps them.'],
            ['Response', 'With several responses: the one mapped.'],
            ['The other factors', 'The values at which the factors off the map are held: type a continuous one\'s value (it starts at its mean), pick a categorical one\'s level (its first).'],
          ] },
          { heading: 'Interaction Plots', text: 'The prediction across one factor with a line for each level of another: parallel lines mean no interaction.' },
        ],
        more: MORE,
      };
    },
    'p:fitmodel:boxcox': { kicker: 'Fit Model', title: 'Box-Cox Y Transformation', lead: 'The error sum of squares of the model for the power transformations of Y, scaled by the geometric mean so that they compare. The best λ minimises it; λ near 1 needs no transformation, near 0 a logarithm. Save Best Transformation adds the transformed column; Refit with Transform fits the model to it.', more: MORE },
    'p:fitmodel:stepwise': {
      kicker: 'Fit Model', title: 'Stepwise',
      lead: 'Builds the model one effect at a time. Go runs until the rule stops, Step makes one step, the Entered boxes put effects in and out by hand. Make Model opens the launch dialog with the chosen effects, Run Model fits them at once.',
      sections: [
        { heading: 'Stepwise Regression Control', choices: [
          ['Stopping Rule', 'P-value Threshold (the default): the steps go on while the best move passes Prob to Enter or Prob to Leave. Minimum AICc or Minimum BIC: the steps go all the way in the direction and the model with the smallest criterion on the path is kept (Mixed makes the move that lowers it most, while one does).'],
          ['Direction', 'Forward (the default) enters the most significant effect at each step; Backward removes the least significant, and Go starts from every effect when none is entered; Mixed does both, a step in and then out while an effect leaves.'],
          ['Rules', 'How crossings go with their parts: Combine enters an effect together with the effects it contains (A and B with A*B) and removes them together; Restrict lets an effect enter only after the effects it contains, and leave only before them; Whole Effects has no rule. Combine is the default when the model has crossings.'],
          ['Prob to Enter', 'P-value Threshold: an effect enters while its p-value is below it, strictly between 0 and 1 (0.25 by default, as JMP).'],
          ['Prob to Leave', 'An entered effect leaves while its p-value is above it (0.1 by default).'],
          ['Go', 'Steps until the rule stops, each step a line of the Step History.'],
          ['Step', 'Makes one step.'],
          ['Enter All', 'Enters every effect.'],
          ['Remove All', 'Takes out every effect that is not locked.'],
          ['Make Model', 'Opens the launch dialog with the entered effects and Standard Least Squares, to change them or press OK.'],
          ['Run Model', 'Fits the entered effects with Standard Least Squares, in a new report.'],
        ] },
        { heading: 'Current Estimates', choices: [
          ['Lock', 'Keeps the effect as it is, in the model or out of it, whatever the steps and Remove All do.'],
          ['Entered', 'Puts the effect in the model or takes it out by hand; the move is a line of the Step History. A locked effect\'s box cannot change.'],
          ['F Ratio, Prob>F', 'For an entered effect the F test of taking it out; for one not entered, of putting it in.'],
        ] },
        { heading: 'All Possible Models', text: 'From the red triangle: the five best models of each size by RSquare. Click a line to make it the current model.' },
      ],
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
    'p:fitmodel:manova': {
      kicker: 'Fit Model', title: 'MANOVA',
      lead: 'Tests each effect on all responses at once: Wilks\' lambda, Pillai\'s trace, the Hotelling-Lawley trace and Roy\'s maximum root, each with an F approximation. Choose Response transforms the responses first (sum, contrasts, polynomial trends); Repeated Measures takes the responses for the levels of a within-subject factor.',
      sections: [{ heading: 'Response Specification', choices: [
        ['Choose Response', 'What the tests are made on: Identity, the responses themselves (the default); Sum, their total; Mean, their average; Contrast, each response against the last; Polynomial, their orthogonal linear, quadratic and higher trends in the order of the columns; Repeated Measures, JMP\'s design for a within-subject factor (it asks for its name).'],
        ['Y Name', 'Repeated Measures: the name of the within-subject factor (Time by default); the Within Subjects tests are named after it.'],
        ['Univariate Tests Also', 'Repeated Measures: adds Mauchly\'s sphericity test and the univariate within tests, unadjusted and with the Greenhouse–Geisser and Huynh–Feldt epsilons. Without Repeated Measures: a univariate test of each response.'],
      ] }],
      more: MORE,
    },
    'p:fitmodel:repeated': {
      kicker: 'Fit Model', title: 'Repeated Measures',
      lead: 'Each row is a subject and the Y columns are its measurements at the levels of a within-subject factor (Y Name, Time by default), in the order of the columns; rows missing a measurement are left out. The model effects are the between-subject factors. As in JMP, this is a sum and a contrast response design at once.',
      sections: [
        { choices: [['Between Subjects', 'each effect on the sum of the responses (All Between: every effect together); one response, so each test is an exact F'], ['Within Subjects', 'the intercept on the contrasts of the responses is the within factor (Time), each effect on them its crossing with it (Time*drug); All Within Interactions tests every crossing together. The multivariate tests need no assumption on the covariance of the measurements'], ['F Test, Exact F', 'a hypothesis of one DF (or one response): the four statistics are one exact test; Value is the eigenvalue of E⁻¹H'], ['Approx. F', 'Wilks\' lambda (Rao), Pillai\'s trace, Hotelling-Lawley (McKeon) and Roy\'s maximum root (an upper bound), statsmodels\' MANOVA']] },
        { heading: 'Univariate Tests Also', choices: [['Sphericity Test', 'Mauchly\'s (1940) criterion W = det(S)/(tr S/p)^p of the covariance S of the orthonormalized contrasts, p = levels − 1, with −(ν − (2p² + p + 2)/(6p)) ln W against χ² on p(p + 1)/2 − 1 DF, ν the error DF (the plain χ² p-value, as JMP; R and pingouin add a second-order term)'], ['Univar unadj Epsilon', 'the within effect as if the responses were stacked in one column: F = (tr H/(q p))/(tr E/(ν p)), valid under sphericity'], ['Univar G-G Epsilon', 'Greenhouse and Geisser (1959): both DF times ε = (tr S)²/(p tr S²), between 1/p and 1'], ['Univar H-F Epsilon', 'Huynh and Feldt (1976): ε = (N p ε_GG − 2)/(p (ν − p ε_GG)), N the subjects, capped at 1. The note gives Lecoutre\'s (1991) correction, ν + 1 in place of N, which SAS uses; they agree with one group of subjects']] },
        { heading: 'Reading them', text: 'If the sphericity test is not significant the unadjusted univariate tests serve; if it is, use the multivariate tests or the adjusted univariate ones (Greenhouse–Geisser is the safer, Huynh–Feldt the less conservative). The main within effect of an unbalanced design is the Type III one: the unweighted mean profile of the groups.' },
      ],
      more: MORE,
    },
    'p:fitmodel:efftests': {
      kicker: 'Fit Model', title: 'Effect Tests',
      lead: 'The F test of each effect with every other effect in the model (Type III, with effect coding): its sum of squares, its DF and the F ratio against the error mean square.',
      sections: [
        { heading: 'Effect sizes', text: 'Right click the table, Columns, for Partial η² and Partial ω² (JMP\'s Effect Tests have neither; they follow the standard references). Partial η² = SS/(SS + SSE) (Cohen 1973): the effect\'s share of the variation left once the other effects are taken out. Partial ω² = (SS − DF·MSE)/(SS + (N − DF)·MSE), equivalently DF(F − 1)/(DF(F − 1) + N) (Keren and Lewis 1979; Olejnik and Algina 2003): the same share in the population, estimated with less upward bias; negative when F < 1, read as 0. N is the number of observations (the sum of Freq). With Robust Standard Errors the tests are Wald tests without sums of squares, and the columns are not offered.' },
      ],
      more: MORE,
    },
    'p:fitmodel:genreg': {
      kicker: 'Fit Model', title: 'Generalized Regression',
      lead: 'JMP Pro\'s penalized and stepwise fits of a normal, binomial or Poisson response, with a validation that picks the model on the path. The predictors are centred and scaled first, by the rows that train the model; the intercept is not penalized. The fits minimise the objective of statsmodels\' fit_regularized, solved as glmnet does (coordinate descent inside Newton steps).',
      sections: [
        { heading: 'Model Launch', choices: [
          ['Distribution', 'Normal, Binomial or Poisson (from the launch dialog; a two-level Y is binomial whichever is chosen). Every change in Model Launch fits the path again and shows its best model.'],
          ['Estimation Method', 'The penalty, or the selection, that makes the path (below).'],
          ['Adaptive', 'Lasso and Elastic Net: each term\'s penalty is divided by the size of its unpenalized estimate, so large effects are shrunk less.'],
          ['Validation Method', 'How the model on the path is chosen (below). With a column in the launch dialog\'s Validation role: Validation Column (the default), AICc or BIC.'],
          ['Elastic Net Alpha', 'Elastic Net: the lasso\'s share of the penalty, above 0 and below 1 (0.9 by default); near 0 the fit is nearly ridge.'],
          ['Number of Folds', 'KFold: the folds the rows are split into at random, from 2 to the number of rows (5 by default).'],
          ['Holdback Proportion', 'Holdback: the share of the rows held back to validate, between 0 and 1 (0.3 by default).'],
          ['Random Seed', 'KFold and Holdback: the seed of the random split. Empty: a seed drawn at the first run and kept with the report (it shows greyed in the box); type a whole number for another split.'],
        ] },
        { heading: 'Estimation Method', choices: [['Lasso', 'an l1 penalty: small effects are set to zero'], ['Elastic Net', 'the lasso and ridge penalties mixed; Elastic Net Alpha is the lasso share'], ['Ridge', 'an l2 penalty: every effect shrinks, none is zero'], ['Adaptive', 'for the lasso and the elastic net: each term\'s penalty is divided by |b| of the maximum likelihood fit (of a ridge fit when that does not exist), so large effects are penalized less'], ['Forward Selection', 'terms enter one at a time, the one with the largest score statistic (for the normal the largest drop in the error sum of squares); each step is a maximum likelihood fit'], ['Pruned Forward Selection', 'after each entry a term leaves while the model without it fits better than every model of its size before (a floating search)']] },
        { heading: 'Validation Method', choices: [['AICc, BIC', 'the model on the path with the smallest criterion of the training fit'], ['KFold', 'the rows split at random into folds (Number of Folds); each fold is predicted by a fit to the others; the curve is the mean of the folds\' Scaled −LogLikelihood. As in JMP, the model shown is the fold model that validates best at the chosen penalty'], ['Holdback', 'a random share of the rows (Holdback Proportion) held back to validate, drawn as the page draws a Validation Portion'], ['Leave-One-Out', 'KFold with a fold per row: slow, and taken up to 1000 rows (300 for the binomial, the Poisson and the forward methods)'], ['Validation Column', 'the launch\'s Validation role: 0 Training, 1 Validation, 2 Test (kept out of both)']] },
        { heading: 'Validation rows of a normal response', text: 'Their −LogLikelihood takes the variance of the training residuals (SSE/N).' },
      ],
      more: MORE,
    },
    'p:fitmodel:grpath': {
      kicker: 'Fit Model', title: 'Solution Path',
      lead: 'The estimates on the centred and scaled predictors (left) and the validation curve (right: AICc, BIC, or the Scaled −LogLikelihood of the validation rows) along the path: against the magnitude of the scaled estimates (the sum of their absolute values) for the penalized methods, against the step for forward selection. The red line is the model the report shows; drag it in either plot, or click a point, to show another. Reset to the Best Model goes back to the smallest value of the curve.',
      sections: [{ heading: 'Choosing a model', choices: [
        ['The red line', 'Drag it along either plot: the report shows the model at the point of the path nearest to where it is let go (its Model Summary and estimates follow).'],
        ['A point', 'Click a point of either plot to show that model.'],
        ['The dotted line', 'The best model by the validation curve, when another one is shown.'],
        ['Reset to the Best Model', 'The red triangle: back to the model with the smallest value of the curve.'],
      ] }],
      more: MORE,
    },
    'p:fitmodel:grsummary': { kicker: 'Fit Model', title: 'Model Summary', lead: 'The fit\'s measures for each set of rows: Training (the rows the model learns from), Validation (the rows that chose it) and Test (a Validation column\'s 2s, kept out of both). −LogLikelihood of the set under the fitted model (the normal\'s variance from the training residuals, SSE/N); Scaled −LogLikelihood, that per unit of weight (the validation curve); Generalized RSquare against the training mean (Nagelkerke\'s; for the normal 1 − exp(2(LL0 − LL)/N)); RASE, the root mean squared error. Number of Parameters, BIC and AICc are the training fit\'s: the nonzero terms and the intercept (for the elastic net and ridge the trace of the ridge hat matrix on the nonzero terms); for the normal AICc and BIC count the variance too.', more: MORE },
    'p:fitmodel:gee': {
      kicker: 'Fit Model', title: 'Generalized Estimating Equations',
      lead: 'A generalized linear model for rows that are not independent: repeated measures of a subject, members of a cluster. GEE (statsmodels\' GEE, Liang and Zeger 1986) estimates the marginal mean, the average over the subjects, with a working correlation for the rows of a subject and standard errors that stay right when that correlation is wrong.',
      sections: [
        { heading: 'Launch', choices: [['Subject', 'the column whose values group the rows (required)'], ['Time', 'the order within a subject (AR(1), Unstructured); the rows are sorted by it'], ['Subgroup', 'a grouping within the subjects (Nested)'], ['Distribution, Link', 'as the Generalized Linear Model; the negative binomial with a fixed α, the Tweedie with its power'], ['Working Correlation', 'Independence, Exchangeable (one correlation), AR(1) (α to the power of the distance), Nested (variance components), Unstructured (one per pair of times)'], ['Covariance', 'Robust (sandwich), Naive (model-based: right only when the working correlation is), Bias-reduced (Mancl and DeRouen, for few subjects)'], ['Scale', 'estimated (Pearson χ²/(N − p)) or fixed (1 for binomial and Poisson)']] },
        { heading: 'Report', choices: [['Model Summary', 'the rows, the subjects and their sizes, the iterations'], ['Parameter Estimates', 'z tests; the right-click Columns menu adds the other standard errors'], ['Effect Tests', 'Wald χ² of each effect'], ['QIC', 'for choosing the working correlation'], ['Working Correlation', 'its parameters and the matrix of a typical subject'], ['Odds Ratios, Rate Ratios', 'for the logit and log links']] },
      ],
      more: MORE,
    },
    'p:fitmodel:qic': {
      kicker: 'Fit Model', title: 'QIC',
      lead: 'Pan\'s quasi-likelihood information criterion: QIC = −2Q + 2 trace(Ω_I V_R), Q the quasi-likelihood under independence, Ω_I its information and V_R the robust covariance; QICu = −2Q + 2p. Smaller is better. QIC chooses among working correlations, QICu among mean models. Every structure is scored at one scale, so the values compare.',
      sections: [
        { heading: 'Compare Working Correlations', text: 'Fits the model with each working correlation the roles allow and lists their QIC; click a line to refit the report with it.' },
        { heading: 'statsmodels\' qic()', text: 'statsmodels 0.14 computes Ω_I without the variance function, which is Pan\'s only for the normal family. The report\'s QIC uses Pan\'s penalty and shows statsmodels\' value beside it.' },
      ],
      more: MORE,
    },
    'p:fitmodel:workcorr': { kicker: 'Fit Model', title: 'Working Correlation', lead: 'The correlation GEE assumes among the rows of a subject, with its estimated parameters: one correlation (exchangeable), the lag-1 correlation (AR(1)), variance components (nested), a correlation for each pair of times (unstructured). The heat map is the working matrix of one subject, blue negative, red positive. statsmodels\' AR(1) counts the positions of a subject\'s rows (sorted by Time).', more: MORE },
    'p:fitmodel:robust': {
      kicker: 'Fit Model', title: 'Robust Standard Errors',
      lead: 'Standard errors that do not rest on constant variance (HC), or on independent rows (HAC, Cluster). Parameter Estimates, Effect Tests, the Effect Summary and the profiler\'s intervals use them; the fit itself is unchanged.',
      sections: [{ choices: [['HC0', 'White\'s sandwich'], ['HC1', 'HC0 times n/(n − p) (Stata\'s robust)'], ['HC2', 'each squared residual divided by 1 − h'], ['HC3', 'divided by (1 − h)²: the safest in small samples'], ['Newey–West HAC', 'also for autocorrelation up to a lag, in the order of the rows'], ['Cluster', 'rows of the same cluster may be correlated; t tests on the clusters less one']] },
        { heading: 'Generalized Linear Model', text: 'The sandwich (HC0), HAC and Cluster; the report then shows Wald tests, since the likelihood ratio tests assume the model\'s variance.' }],
      more: MORE,
    },
    'p:fitmodel:regdiag': {
      kicker: 'Fit Model', title: 'Regression Diagnostics',
      lead: 'Tests of a least squares fit\'s assumptions, from statsmodels.stats.diagnostic. A small p-value speaks against the assumption.',
      sections: [
        { choices: [['Breusch–Pagan, White', 'constant variance, against a variance that depends on the regressors'], ['Goldfeld–Quandt', 'the variances of two halves of the rows, sorted'], ['Ramsey RESET', 'powers of the prediction added: is the form linear?'], ['Harvey–Collier', 'the mean of the recursive residuals, in an order'], ['Rainbow', 'the fit of the central rows against all of them'], ['Breusch–Godfrey', 'autocorrelation of the residuals up to a lag, in the row order'], ['Jarque–Bera, Omnibus', 'normal residuals, from their skewness and kurtosis']] },
        { heading: 'The settings above a test', choices: [
          ['Sort by (Goldfeld–Quandt)', 'The order in which the rows are cut into two halves: by the predicted values (the default), by a continuous factor of the model, or in row order.'],
          ['Leave out the middle', 'The share of the middle rows left out between the halves: nothing (the default), 10%, 20%, 25% or a third. Leaving some out sharpens the contrast between the halves.'],
          ['Alternative', 'Variance increasing along the order (the second half\'s larger, the default), decreasing, or two-sided.'],
          ['Powers of the predicted (RESET)', '2: the squares of the predicted values added to the model; 2 and 3: the squares and the cubes (the default).'],
          ['Order (Harvey–Collier)', 'The order of the recursive residuals: row order (the default), the predicted values or a continuous factor.'],
          ['Central rows by (Rainbow)', 'Which rows make the central fit: those of smallest leverage (Utts, the default), or the middle of the row order, of the predicted values or of a continuous factor.'],
          ['Central fraction', 'The share of the rows in the central fit, 0.1 to 0.9 (0.5 by default).'],
          ['Lags (Breusch–Godfrey)', 'The number of lagged residuals tested, a whole number from 1; empty: 10, or a fifth of the rows when that is fewer.'],
        ] },
        { text: 'A change runs the test again. A weighted fit is tested as least squares on the data times √w.' },
      ],
      more: MORE,
    },
    'p:fitmodel:influence': { kicker: 'Fit Model', title: 'Influence and partial residuals', lead: 'The Influence Plot puts each row\'s externally studentized residual against its leverage; the area of the bubble is Cook\'s D, the lines mark residuals of ±2 and leverages of 2p/n and 3p/n. Component + Residual Plots show, for each continuous term, the residual plus the term\'s part of the fit against the term: a curve asks for a transformation.', more: MORE },
    'p:fitmodel:recursive': {
      kicker: 'Fit Model', title: 'Recursive and Rolling Regression',
      lead: 'The least squares model fitted with the rows taken one at a time, in the order of the table or sorted by a column (a time, a date): do the coefficients stay put along that order? statsmodels\' RecursiveLS and RollingOLS; JMP has no such tests.',
      sections: [
        { choices: [['Recursive Estimates', 'each coefficient from the first rows up to each row, with its band; the last are the report\'s estimates'], ['CUSUM Test', 'the cumulative sum of the recursive residuals (each row\'s prediction error from the rows before it, standardised): a path that leaves the bounds says the relation shifts'], ['CUSUM of Squares Test', 'the cumulative share of the squared recursive residuals against the diagonal: leaving the bounds says the variance or the slopes change'], ['Rolling Regression', 'least squares on each window of consecutive rows (Rolling Window… sets its size), plotted at the window\'s last row']] },
        { heading: 'Reading them', text: 'Sort the rows by time first (Order Rows By…). The CUSUM reacts to shifts in the level of Y, the CUSUM of squares to changes in the spread or the slopes; the recursive and rolling estimates show which coefficient moves, and where. The bounds are for the 1%, 5% or 10% level (Brown, Durbin and Evans 1975; Edgerton and Wells 1994).' },
        { heading: 'Linking', text: 'A recursive point stands for the row it adds: clicking it selects that row. A rolling point stands for its window: clicking it selects the window\'s rows.' },
        { heading: 'The settings above the plots', choices: [
          ['Order by', 'The order the rows are taken in: the table\'s row order, or sorted by a column (a nominal or ordinal one by its value order); rows without a value of it are left out.'],
          ['Significance', 'The level of the CUSUM and CUSUM of squares bounds: 1%, 5% (the default) or 10%. The bands of the estimates are at the report\'s α.'],
          ['Window', 'Rolling Regression: the rows in each window, more than the parameters and at most every row; empty, a tenth of the rows but at least three times the parameters.'],
        ] },
      ],
      more: MORE,
    },
    'p:fitmodel:iv': {
      kicker: 'Fit Model', title: 'Instrumental Variables',
      lead: 'When an effect is correlated with the error (an omitted cause of both, reverse causation, measurement error), least squares is biased. Instruments move the endogenous columns but have no effect of their own on Y; two-stage least squares (statsmodels\' IV2SLS) uses only the part of the endogenous columns they explain. JMP has no such personality.',
      sections: [
        { heading: 'Launch', choices: [['Endogenous', 'the columns of the model effects that are endogenous; a crossing or power that holds one is endogenous too, and is instrumented by the same crossing or power of the instruments'], ['Instruments', 'the excluded instruments, not in the model; the exogenous effects instrument themselves. At least as many instrument columns as endogenous columns']] },
        { heading: 'Report', choices: [['First Stage', 'each endogenous column on the instruments: RSquare, partial RSquare and the F test of the excluded instruments (weak below 10); Cragg and Donald\'s statistic'], ['Second Stage Parameter Estimates', 'the 2SLS estimates; standard errors from the model\'s own residuals y − Xb, classical or robust'], ['Endogeneity Test', 'Durbin–Wu–Hausman: are the endogenous columns in fact exogenous?'], ['Overidentification Test', 'Sargan (Hansen\'s J with robust errors): are the extra instruments valid?'], ['OLS Beside 2SLS', 'least squares and 2SLS side by side']] },
      ],
      more: MORE,
    },
    'p:fitmodel:ivfirst': { kicker: 'Fit Model', title: 'First stage and weak instruments', lead: 'The first stage regresses each endogenous column on all the instruments. The F ratio tests the excluded instruments: below 10 (Staiger and Stock\'s rule of thumb) they are weak, 2SLS leans toward least squares and its intervals are too narrow. The partial RSquare is their share of what the exogenous effects leave unexplained; Shea\'s partial RSquare, with several endogenous columns, what they explain of each one beyond the others. Cragg and Donald\'s statistic (the smallest eigenvalue of the joint F) is what Stock and Yogo (2005) tabulate critical values for.', more: MORE },
    'p:fitmodel:ivtests': { kicker: 'Fit Model', title: 'Endogeneity and overidentification', lead: 'Durbin–Wu–Hausman: the first-stage residuals are added to the least squares fit; if they add nothing (a large p-value), the endogenous columns behave as exogenous and least squares is fine. Sargan\'s test (Hansen\'s J with robust standard errors) asks, when there are more instruments than endogenous columns, whether the instruments agree with each other: a small p-value says at least one is not valid, without saying which.', more: MORE },
    'p:fitmodel:quantreg': {
      kicker: 'Fit Model', title: 'Quantile Regression',
      lead: 'A quantile of Y given the effects (0.5 the median, 0.9 the upper tenth) instead of its mean: statsmodels\' QuantReg minimises the sum of check losses. It needs no normal errors, resists outliers in Y, and shows how the effects differ across the distribution. JMP Pro has it in Generalized Regression, without the quantile process.',
      sections: [
        { heading: 'Model Launch', choices: [
          ['Quantile τ', 'The quantile of the report, strictly between 0 and 1 (from the launch dialog; 0.5, the median, by default).'],
          ['Standard Errors', 'Robust (statsmodels\' default: one density estimate for every row, each squared score by the sign of its residual), IID (τ(1 − τ)/f̂(0)² (X′X)⁻¹, Stata\'s qreg default: the same error distribution in every row), or Powell\'s kernel sandwich (a density per row: for a spread that changes with X, as R\'s quantreg se = "ker").'],
          ['Kernel', 'The kernel of the estimate of the residuals\' density at the quantile, which every standard error needs: Epanechnikov (the default), Gaussian, Cosine, Parzen or Biweight.'],
          ['Bandwidth', 'Its bandwidth rule: Hall–Sheather (the default), Bofinger or Chamberlain.'],
          ['Quantile Process', 'The quantiles of the process: a list (0.1, 0.5, 0.9) or a range (0.05 to 0.95 by 0.05, the default); at most 99, each strictly between 0 and 1.'],
        ] },
        { heading: 'Report', choices: [['Summary of Fit', 'Koenker and Machado\'s pseudo RSquare, 1 − the check loss over that of the intercept alone; the share of rows below the fit, which should be near τ'], ['Parameter Estimates', 'at the quantile τ, with t tests'], ['Quantile Process', 'each coefficient against τ, beside the least squares estimate'], ['Quantile Regression Plot', 'with one continuous factor: the fitted lines of several quantiles']] },
      ],
      more: MORE,
    },
    'p:fitmodel:qrprocess': { kicker: 'Fit Model', title: 'Quantile process', lead: 'Each coefficient fitted at every quantile of the list, with its pointwise band (the band is not simultaneous over the quantiles). The dashed line and the pale band are the least squares estimate and its interval. A curve that stays in the band: the effect is the same across the distribution (a location shift); one that rises or falls: the term changes the spread of Y too.', more: MORE },
  };

  /* ---- an example table: repeated measures, for Generalized Estimating Equations ---------------------------------
     Simulated with a seed (nothing that is not ours): 60 subjects in 10
     clinics, 3 of the 6 of each clinic on the active drug, seen at 4 visits.
     Each subject has its own propensity to improve (a random intercept on
     the logit scale), its own symptom rate (on the log scale) and AR(1)
     errors in its score, so a subject's rows are correlated. */
  function makeLongitudinal() {
    const r = SM.util.rng('longitudinal');
    const c = { subject: [], clinic: [], treatment: [], visit: [], baseline: [], improved: [], symptoms: [], score: [] };
    const poisson = (lambda) => { let k = 0, p = Math.exp(-lambda), s = p; const u = r.u(); while (u > s && k < 400) { k++; p *= lambda / k; s += p; } return k; };
    for (let cl = 0; cl < 10; cl++) {
      const arms = ['placebo', 'placebo', 'placebo', 'active', 'active', 'active'];
      for (let i = arms.length - 1; i > 0; i--) { const j = Math.floor(r.u() * (i + 1)); [arms[i], arms[j]] = [arms[j], arms[i]]; }
      for (let k = 0; k < 6; k++) {
        const s = cl * 6 + k;
        const act = arms[k] === 'active' ? 1 : 0;
        const base = r.normal(20, 5);
        const b = r.normal(0, 1.3), u = r.normal(0, 0.45);
        let e = r.normal(0, 4);
        for (let v = 1; v <= 4; v++) {
          if (v > 1) e = 0.6 * e + r.normal(0, 4 * Math.sqrt(1 - 0.36));
          const eta = -1.1 + 0.25 * v + 0.55 * act * (v - 1) + 0.08 * (base - 20) + b;
          c.subject.push(`S${String(s + 1).padStart(2, '0')}`); c.clinic.push(`C${String(cl + 1).padStart(2, '0')}`); c.treatment.push(arms[k]); c.visit.push(v);
          c.baseline.push(+base.toFixed(1));
          c.improved.push(r.u() < 1 / (1 + Math.exp(-eta)) ? 'yes' : 'no');
          c.symptoms.push(poisson(Math.exp(1.7 - 0.08 * v - 0.18 * act * (v - 1) + 0.035 * (base - 20) + u)));
          c.score.push(+(40 + 0.6 * (base - 20) - 1.2 * v - 2.2 * act * (v - 1) + e).toFixed(1));
        }
      }
    }
    return new SM.Table({ name: 'Longitudinal trial', source: 'simulated', columns: [
      { name: 'subject', dataType: 'character', values: c.subject, role: 'label' },
      { name: 'clinic', dataType: 'character', values: c.clinic },
      { name: 'treatment', dataType: 'character', values: c.treatment, valueOrder: ['placebo', 'active'] },
      { name: 'visit', dataType: 'numeric', values: c.visit },
      { name: 'baseline', dataType: 'numeric', values: c.baseline },
      { name: 'improved', dataType: 'character', values: c.improved, valueOrder: ['yes', 'no'] },
      { name: 'symptoms', dataType: 'numeric', values: c.symptoms },
      { name: 'score', dataType: 'numeric', values: c.score },
    ] });
  }
  if (SM.io && SM.io.addExample) {
    SM.io.addExample('longitudinal', {
      label: 'Longitudinal trial (60 subjects × 4 visits): treatment, a binary and a count outcome',
      about: 'Simulated repeated measures: 60 subjects in 10 clinics, placebo or active, 4 visits and a baseline severity. Improved (yes/no), symptoms (a count) and score (AR(1) errors) are correlated within a subject. For Fit Model > Generalized Estimating Equations.',
      make: makeLongitudinal,
    });
  }

  /* ---- an example table: returns to schooling ---------------------------------------------------------------
     Simulated with a seed (nothing that is not ours): 1500 people
     interviewed from 1995 to 2024, 50 a year, the rows in interview order.
     An unobserved ability (not in the table) raises both education and the
     log wage, so least squares overstates the return to education; the
     distance to a college and a scholarship lottery move education and
     nothing else (the instruments), the birth quarter hardly at all (a weak
     instrument); the spread of the log wage grows with experience (quantile
     regression); the return to experience halves from 2008 on (a structural
     break along the interview order, for the recursive tests). */
  function makeSchooling() {
    const r = SM.util.rng('schooling-5');
    const regions = ['north', 'south', 'east', 'west'];
    const regionEffect = { north: 0, south: -0.08, east: 0.04, west: 0.06 };
    const c = { person: [], year: [], region: [], sex: [], quarter: [], experience: [], distance: [], lottery: [], education: [], lwage: [] };
    for (let i = 0; i < 1500; i++) {
      const year = 1995 + Math.floor(i / 50);
      const ability = r.normal(0, 1);
      const female = r.u() < 0.5;
      const region = regions[Math.floor(r.u() * 4)];
      const quarter = 1 + Math.floor(r.u() * 4);
      const experience = Math.round((1 + 34 * r.u()) * 10) / 10;
      const distance = Math.round(Math.min(120, 2 - 18 * Math.log(1 - r.u())) * 10) / 10;
      const won = r.u() < 0.3;
      const latent = 12.4 + 1.2 * ability - 0.035 * (distance - 20) + 1.1 * won + 0.25 * female + 0.12 * (quarter === 4) + r.normal(0, 1.4);
      const education = Math.max(8, Math.min(20, Math.round(latent)));
      const bExperience = year < 2008 ? 0.030 : 0.015;
      const lwage = 1.2 + 0.080 * education + bExperience * experience - 0.120 * female + regionEffect[region] + 0.15 * ability + (0.20 + 0.010 * experience) * r.normal(0, 1);
      c.person.push(`P${String(i + 1).padStart(4, '0')}`); c.year.push(year); c.region.push(region); c.sex.push(female ? 'female' : 'male'); c.quarter.push(`Q${quarter}`);
      c.experience.push(experience); c.distance.push(distance); c.lottery.push(won ? 'won' : 'lost'); c.education.push(education); c.lwage.push(+lwage.toFixed(4));
    }
    return new SM.Table({ name: 'Schooling', source: 'simulated', columns: [
      { name: 'person', dataType: 'character', values: c.person, role: 'label' },
      { name: 'year', dataType: 'numeric', values: c.year },
      { name: 'region', dataType: 'character', values: c.region, valueOrder: regions },
      { name: 'sex', dataType: 'character', values: c.sex, valueOrder: ['female', 'male'] },
      { name: 'birth quarter', dataType: 'character', values: c.quarter, valueOrder: ['Q1', 'Q2', 'Q3', 'Q4'] },
      { name: 'experience', dataType: 'numeric', values: c.experience },
      { name: 'distance (km)', dataType: 'numeric', values: c.distance },
      { name: 'lottery', dataType: 'character', values: c.lottery, valueOrder: ['won', 'lost'] },
      { name: 'education', dataType: 'numeric', values: c.education },
      { name: 'log wage', dataType: 'numeric', values: c.lwage },
    ] });
  }
  if (SM.io && SM.io.addExample) {
    SM.io.addExample('schooling', {
      label: 'Schooling (1500 people): returns to education with instruments, a widening spread and a break',
      about: 'Simulated (seeded; not real data): 1500 people interviewed from 1995 to 2024, 50 a year, the rows in interview order. The truth: log wage = 1.2 + 0.080 education + 0.030 experience (0.015 from 2008 on) − 0.120 female + region (north 0, south −0.08, east +0.04, west +0.06) + 0.15 ability + (0.20 + 0.010 experience) × a standard normal error. Ability is not in the table and also raises education by 1.2 years per standard deviation, so least squares overstates the return to education. distance (km) (−0.035 years of education per km) and lottery (a scholarship won: +1.1 years) move education and have no effect of their own on the wage: Fit Model > Instrumental Variables with education Endogenous and these two as Instruments recovers about 0.080. birth quarter moves education by 0.12 years in Q4 only: a weak instrument. The spread grows with experience: Quantile Regression finds the slope of experience rising with the quantile (0.010 × the normal quantile above and below the median). The return to experience halves in 2008: Standard Least Squares > Recursive and Rolling Regression (rows in table order, or sorted by year). In JMP\'s effect coding sex[female] is half the female–male gap, −0.060, and region[south] is −0.08 minus the average of the four region effects.',
      make: makeSchooling,
    });
  }

  /* ---- the platform -------------------------------------------------------------------------------------- */
  SM.platforms.register({
    id: 'fitmodel', label: 'Fit Model', menu: 'Analyze', order: 110, info: 'p:fitmodel', topics: TOPICS,
    about: 'Linear and generalized models from JMP\'s Construct Model Effects (crossings, nesting, macros, random effects), fitted by one of the personalities: Standard Least Squares (effect tests with partial η² and ω² as optional columns, leverage plots, least squares means with Tukey HSD, row diagnostics, Box-Cox, the Prediction and Contour Profilers, and beyond JMP robust standard errors HC0–HC3, Newey–West and cluster, the Breusch–Pagan, White, Goldfeld–Quandt, RESET, Harvey–Collier, Rainbow, Breusch–Godfrey, Jarque–Bera and omnibus tests, an influence plot and component-plus-residual plots), Stepwise, Generalized Linear Model (with robust standard errors), Generalized Estimating Equations (statsmodels\' GEE: independence, exchangeable, AR(1), nested and unstructured working correlations, robust, naive and bias-reduced standard errors, QIC and a comparison of working correlations), Nominal and Ordinal Logistic, Mixed Model (REML), MANOVA (with JMP\'s Repeated Measures: the between- and within-subject tests, Mauchly\'s sphericity test, the Greenhouse–Geisser and Huynh–Feldt adjusted univariate tests), Generalized Regression (lasso, elastic net, ridge, adaptive lasso and elastic net, forward and pruned forward selection, validated by AICc, BIC, KFold, holdback, leave-one-out or a Validation column), and beyond JMP Instrumental Variables (two-stage least squares with first stages, weak-instrument statistics, the Durbin–Wu–Hausman and Sargan / Hansen J tests, robust standard errors), Quantile Regression (statsmodels\' QuantReg at a quantile with the Koenker–Machado pseudo RSquare, the quantile process beside least squares, quantile lines) and, in Standard Least Squares, Recursive and Rolling Regression (recursive estimates, the CUSUM and CUSUM of squares tests of parameter stability, rolling windows).',
    uses: ['statsmodels.formula.api.ols, wls', 'statsmodels.regression.linear_model.RegressionResults.wald_test_terms, get_robustcov_results', 'statsmodels.stats.anova.anova_lm', 'statsmodels.stats.outliers_influence.variance_inflation_factor', 'statsmodels.stats.multitest.multipletests', 'statsmodels.genmod.generalized_linear_model.GLM', 'statsmodels.genmod.generalized_estimating_equations.GEE (qic, cov_struct)', 'statsmodels.genmod.cov_struct.Independence, Exchangeable, Autoregressive, Nested, Unstructured', 'statsmodels.stats.diagnostic.het_breuschpagan, het_white, het_goldfeldquandt, linear_reset, linear_rainbow, recursive_olsresiduals, acorr_breusch_godfrey', 'statsmodels.stats.stattools.jarque_bera, omni_normtest', 'statsmodels.discrete.discrete_model.MNLogit, NegativeBinomial', 'statsmodels.miscmodels.ordinal_model.OrderedModel', 'statsmodels.regression.mixed_linear_model.MixedLM', 'statsmodels.multivariate.manova.MANOVA', 'statsmodels.regression.linear_model.OLS.fit_regularized', 'statsmodels.genmod.generalized_linear_model.GLM.fit_regularized', 'statsmodels.sandbox.regression.gmm.IV2SLS', 'statsmodels.stats.sandwich_covariance.S_white_simple, S_hac_simple, S_crosssection', 'statsmodels.regression.quantile_regression.QuantReg', 'statsmodels.regression.recursive_ls.RecursiveLS (cusum, cusum_squares and their bounds)', 'statsmodels.regression.rolling.RollingOLS', 'scipy.stats.studentized_range', 'patsy'],
    launch: {
      lead: 'Choose the Y, add the model effects from the selected columns, and pick a personality. Continuous Y: least squares; nominal or ordinal Y: logistic.',
      roles: [
        { key: 'y', label: 'Y', min: 1, hint: 'required',
          help: 'The response. Its modeling type picks the personality until you choose one: continuous Standard Least Squares, nominal Nominal Logistic, ordinal Ordinal Logistic. Several Y columns are fitted one at a time with the same model; MANOVA takes them together, and a binomial Generalized Linear Model takes two as events and trials.' },
        { key: 'weight', label: 'Weight', max: 1, numeric: true, types: ['continuous'], hint: 'optional numeric',
          help: 'A weight per row, multiplied with Freq: least squares becomes weighted least squares (Stepwise too), the Generalized Linear Model takes it as variance weights, the logistic fits and Generalized Regression as frequencies (the ordinal and multinomial logistic fits repeat each row, so they need whole numbers). Mixed Model, MANOVA, GEE, Instrumental Variables and Quantile Regression take none, nor the negative binomial. Rows with a missing, zero or negative weight are left out.' },
        { key: 'freq', label: 'Freq', max: 1, numeric: true, types: ['continuous'], hint: 'optional numeric',
          help: 'How many observations each row stands for: least squares counts the error degrees of freedom from their sum, as JMP; the Generalized Linear Model and the logistic fits take them as frequency weights (or repeated rows). It multiplies the Weight; Mixed Model, MANOVA, GEE, Instrumental Variables and Quantile Regression take none. With a Freq, Robust Standard Errors are not computed.' },
        { ...SM.predict.roles({ weight: false, freq: false, by: false })[0], hint: 'optional (Generalized Regression): 0/1/2 or Training/Validation/Test',
          help: 'Generalized Regression only: rows with 0 or Training fit the path, 1 or Validation choose the model on it (Validation Method: Validation Column), 2 or Test are kept out of both and only measured; rows with no value are left out. With this column KFold, Holdback and Leave-One-Out are not offered. The other personalities take every row and say so.' },
        { key: 'endog', label: 'Endogenous', hint: 'required: the model effects\' columns that are endogenous',
          help: 'Instrumental Variables only (required there): the columns of the model effects that are correlated with the error. Every effect that holds one is endogenous; a crossing or power of one is instrumented by the same crossing or power of the instruments.' },
        { key: 'instruments', label: 'Instruments', hint: 'required: the excluded instruments',
          help: 'Instrumental Variables only (required there): the excluded instruments, columns that move the endogenous ones but have no effect of their own on Y. They stay out of the model effects (the exogenous effects instrument themselves); at least as many instrument columns as endogenous ones.' },
        { key: 'offset', label: 'Offset', max: 1, numeric: true, types: ['continuous'], hint: 'optional (generalized linear model, GEE)',
          help: 'Generalized Linear Model and GEE: a known part of the linear predictor, added with a coefficient of 1; for example the log of the exposure, with a log link, to model a rate of counts.' },
        { key: 'subject', label: 'Subject', max: 1, hint: 'required: the rows that belong together',
          help: 'GEE only (required there): rows with the same value belong together, a subject or a cluster. The working correlation applies within a subject; the subjects are independent.' },
        { key: 'time', label: 'Time', max: 1, numeric: true, hint: 'optional: the order within a subject',
          help: 'GEE: the order of a subject\'s rows, numeric; the rows are sorted by it. The AR(1) working correlation needs it (the correlation falls with the distance in that order), and the Unstructured one (a correlation for each pair of its values: at most 15 values, each at most once per subject).' },
        { key: 'subgroup', label: 'Subgroup', max: 1, hint: 'optional: a grouping within the subjects',
          help: 'GEE: a grouping within the subjects, for the Nested working correlation (a variance component for the subject and one for the subgroups within it).' },
        { key: 'by', label: 'By', hint: 'optional',
          help: 'A separate fit and report for each level of the By column (each combination of levels, with several By columns). Rows with a missing By value are left out.' },
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
        case 'gee': return one ? `Generalized Estimating Equations for ${one}` : 'Generalized Estimating Equations';
        case 'nominal': return one ? `Nominal Logistic Fit for ${one}` : 'Fit Nominal Logistic';
        case 'ordinal': return one ? `Ordinal Logistic Fit for ${one}` : 'Fit Ordinal Logistic';
        case 'mixed': return 'Fit Mixed';
        case 'manova': return 'Manova Fit';
        case 'genreg': return one ? `Generalized Regression for ${one}` : 'Generalized Regression';
        case 'iv': return one ? `Instrumental Variables Fit for ${one}` : 'Fit Instrumental Variables';
        case 'quantreg': return one ? `Quantile Regression Fit for ${one}` : 'Fit Quantile Regression';
        default: return one ? `Response ${one}` : 'Fit Group';
      }
    },
    triangle(ctx) { return ctx.fm && ctx.fm.menu ? ctx.fm.menu() : [{ label: 'Model Dialog', action: () => ctx.report.relaunch() }]; },
    async render(ctx) {
      ctx.fm = { menu: null };
      const M = modelOf(ctx);
      const p = ctx.opt('personality', 'standard');
      const vc = ctx.name('validation');
      if (vc && p !== 'genreg') ctx.top.add(ctx.note(`${vc} is in the Validation role, which only Generalized Regression uses: this fit takes every row, whatever its set.`));
      if (p === 'stepwise') return renderStepwise(ctx, M);
      if (p === 'glm') return renderGLM(ctx, M);
      if (p === 'gee') return renderGEE(ctx, M);
      if (p === 'nominal' || p === 'ordinal') return renderLogistic(ctx, M, p === 'ordinal');
      if (p === 'mixed') return renderMixed(ctx, M);
      if (p === 'manova') return renderManova(ctx, M);
      if (p === 'genreg') return renderGenReg(ctx, M);
      if (p === 'iv') return renderIV(ctx, M);
      if (p === 'quantreg') return renderQR(ctx, M);
      if (M.effects.some((e) => e.random)) return renderMixed(ctx, M, { sls: true });
      return renderStandard(ctx, M);
    },
  });
}(typeof self !== 'undefined' ? self : this));
