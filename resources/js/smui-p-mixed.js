/* ==========================================================================
   SMUI.HTML: ANALYZE > FIT MODEL > THE MIXED MODELS

   The reports of Fit Model's mixed models: the Mixed Model personality
   (JMP Pro's Fit Mixed: random effects, correlated random coefficients, a
   repeated structure), Standard Least Squares with random effects (JMP's
   REML fit, its Effect Details) and the Generalized Linear Model with
   random effects (a generalized linear mixed model, binomial or Poisson,
   fitted by residual pseudo-likelihood). The statistics are
   resources/py/smui/mixed.py (fitmodel.mixed, mixed.*); the launch dialog,
   the effects and the other personalities are smui-p-fitmodel.js, which
   shares its parts with this file as SM.fitmodel and hands the mixed models
   to SM.fitmodel.mixed:

     claims(p, M)            does this file draw the report of personality p
                             with the model M
     render(ctx, M, p)       draws it
     validate(spec, table)   the launch's checks of a mixed model (undefined:
                             no opinion; null: fine; text: why not)
     launchPart(api, o0, E)  the dialog's own controls, roles and Attributes
                             items of the mixed models: { el, sync(p),
                             help(p), read(p), recall(o), attributes() }

   Every red-triangle choice is an option of the report (ctx.set), scoped by
   the response column, so Redo and saved projects keep it. The launch's own
   options are mxUnbounded, mxDdfm, mxStructure, mxSptype and mxScale; the
   Repeated role (repeated) is added to Fit Model's roles here, the Subject
   role (subject) is shared with GEE.
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM;
  const { el, fmt } = SM.util;
  const FM = SM.fitmodel;
  if (!FM) throw new Error('smui-p-mixed.js needs smui-p-fitmodel.js before it');

  const STRUCTS = [['residual', 'Residual'], ['uneqvar', 'Unequal Variances'], ['un', 'Unstructured'], ['ar1', 'AR(1)'], ['cs', 'Compound Symmetry'],
    ['antevar', 'Antedependent Equal Variance'], ['toep', 'Toeplitz'], ['csh', 'Compound Symmetry Unequal Variances'], ['ante', 'Antedependent'],
    ['toeph', 'Toeplitz Unequal Variances'], ['arh', 'AR(1) Unequal Variances'], ['sp', 'Spatial'], ['spn', 'Spatial with Nugget']];
  const STRUCT_LABEL = Object.fromEntries(STRUCTS);
  const SPTYPES = [['pow', 'Power'], ['exp', 'Exponential'], ['gau', 'Gaussian'], ['sph', 'Spherical']];
  const NEEDS_SUBJECT = new Set(['un', 'cs', 'antevar', 'toep', 'csh', 'ante', 'toeph']);
  const SPATIAL = new Set(['sp', 'spn']);
  const GLMM_LINKS = { binomial: ['logit', 'probit', 'cloglog'], poisson: ['log'] };
  const LEVELS = [0.01, 0.05, 0.10, 0.20];

  const hasRandom = (effects) => (effects || []).some((e) => e.random);
  const pct = (ctx) => fmt(100 * (1 - ctx.alpha));

  /* ---- the Repeated role (Fit Model's roles are the platform's; this one belongs to the Mixed Model) --------- */
  (function addRoles() {
    const def = SM.platforms.get('fitmodel');
    if (!def || !def.launch || def.launch.roles.some((r) => r.key === 'repeated')) return;
    const roles = def.launch.roles;
    const at = roles.findIndex((r) => r.key === 'by');
    roles.splice(at < 0 ? roles.length : at, 0, {
      key: 'repeated', label: 'Repeated', hint: 'required by a repeated structure',
      help: 'Mixed Model only, with a Repeated Structure other than Residual: the column that orders the measurements within a subject (the time), or the coordinates for a spatial structure (two or more continuous columns). Unstructured, Compound Symmetry, Toeplitz and Antedependent take its levels (a categorical column, or the distinct values of a continuous one); AR(1) takes a continuous time (unequal spacing works) or the levels as equally spaced times.',
    });
    const subj = roles.find((r) => r.key === 'subject');
    if (subj && !/Mixed Model/.test(subj.help || '')) subj.help = `${subj.help} Mixed Model: the subjects of a Repeated Structure (a categorical column); the repeated measurements are correlated within a subject and independent between subjects.`;
  }());

  /* ---- which reports are ours ---------------------------------------------------------------------------- */
  function claims(p, M) {
    return p === 'mixed' || ((p === 'standard' || p === 'glm') && hasRandom(M.effects));
  }

  /* ---- the launch's checks -------------------------------------------------------------------------------- */
  function validate(spec, table) {
    const o = spec.options || {};
    const p = o.personality || 'standard';
    const effects = spec.effects || [];
    const rnd = hasRandom(effects);
    const ys = (spec.roles.y || []).map((id) => table.col(id)).filter(Boolean);
    const cols = (k) => (spec.roles[k] || []).map((id) => table.col(id)).filter(Boolean);
    const rcCheck = () => {
      const groups = new Map();
      for (const e of effects) {
        if (!e.random || !e.rc) continue;
        const cats = [...(e.cols || []), ...(e.nest || [])].map((id) => table.col(id)).filter((c) => c && c.isCategorical).map((c) => c.id).sort().join('|');
        if (!cats) return `A random coefficient needs a subject: nest ${(e.names || []).join('*')} in a categorical column (Attributes > Nest Random Coefficients).`;
        if (groups.has(e.rc) && groups.get(e.rc) !== cats) return `The random coefficients (${e.rc}) are nested in different columns: nest them in one subject.`;
        groups.set(e.rc, cats);
      }
      return null;
    };
    if (p === 'mixed') {
      if (!ys.every((c) => !c.isCategorical)) return `Mixed Model needs continuous Y columns: change the personality (a Generalized Linear Model takes random effects for a binomial or Poisson response), or the modeling type of ${ys.find((c) => c.isCategorical).name}.`;
      const st = o.mxStructure || 'residual';
      if (!rnd && st === 'residual') return 'The mixed model needs a random effect (select an effect and choose Attributes > Random Effect) or a Repeated Structure.';
      if (st !== 'residual') {
        const rep = cols('repeated'), sub = cols('subject');
        const label = STRUCT_LABEL[st];
        if (!rep.length) return `The ${label} structure needs a Repeated column${SPATIAL.has(st) ? ': the coordinates (continuous columns)' : ': the time, or the order within a subject'}.`;
        if (SPATIAL.has(st) && rep.some((c) => c.isCategorical)) return `The spatial structures take continuous Repeated columns (the coordinates): ${rep.find((c) => c.isCategorical).name} is categorical.`;
        if (!SPATIAL.has(st) && rep.length !== 1) return `The ${label} structure takes one Repeated column.`;
        if (NEEDS_SUBJECT.has(st) && !sub.length) return `The ${label} structure needs a Subject column: the rows that belong together.`;
        if (sub.some((c) => !c.isCategorical)) return `Subject columns must be categorical (nominal or ordinal): ${sub.find((c) => !c.isCategorical).name} is continuous.`;
        const yIds = new Set(spec.roles.y || []);
        if ([...rep, ...sub].some((c) => yIds.has(c.id))) return 'A Y column is also a Repeated or Subject column.';
      }
      return rcCheck();
    }
    if (p === 'glm' && rnd) {
      const dist = o.dist || 'normal';
      if (dist === 'normal') return 'A normal response with random effects is a linear mixed model: choose Mixed Model (or Standard Least Squares).';
      if (!GLMM_LINKS[dist]) return 'With random effects the Generalized Linear Model takes the binomial or the Poisson distribution here (a generalized linear mixed model, fitted by pseudo-likelihood).';
      const link = o.link || (dist === 'binomial' ? 'logit' : 'log');
      if (!GLMM_LINKS[dist].includes(link)) return `With random effects the ${dist === 'binomial' ? 'binomial takes the logit, probit or complementary log-log link' : 'Poisson takes the log link'}.`;
      if ((spec.roles.offset || []).length) return 'An Offset is not taken with random effects here.';
      if (effects.some((e) => e.rc)) return 'Correlated random coefficients are for the Mixed Model personality: in a Generalized Linear Model, give the random effects as variance components.';
      return null;
    }
    if (p === 'standard' && rnd) {
      if (effects.some((e) => e.rc)) return 'Correlated random coefficients (Nest Random Coefficients) are for the Mixed Model personality, as in JMP Pro.';
      return undefined;
    }
    return undefined;
  }

  /* ---- the launch dialog's part --------------------------------------------------------------------------- */
  function launchPart(api, o0, E) {
    const mk = (choices, value, label) => { const s = el('select', { 'aria-label': label }, ...choices.map(([v, l]) => el('option', { value: v, text: l }))); s.value = value; return s; };
    const lab = (text, input) => el('label', { class: 'sm-fm-opt' }, el('span', { text }), input);
    const unb = el('input', { type: 'checkbox', 'aria-label': 'Unbounded Variance Components' });
    unb.checked = o0.mxUnbounded !== false;
    const lUnb = el('label', { class: 'sm-fm-opt' }, unb, el('span', { text: 'Unbounded Variance Components' }));
    const ddfm = mk([['kr', 'Kenward-Roger'], ['sat', 'Satterthwaite']], o0.mxDdfm || 'kr', 'Degrees of freedom');
    const lDdfm = lab('DF', ddfm);
    const struct = mk(STRUCTS, o0.mxStructure || 'residual', 'Repeated Structure');
    const lStruct = lab('Repeated Structure', struct);
    const sptype = mk(SPTYPES, o0.mxSptype || 'exp', 'Type');
    const lType = lab('Type', sptype);
    const scale = mk([['fixed', 'Fixed at 1'], ['estimated', 'Estimated']], o0.mxScale || 'fixed', 'Scale');
    const lScale = lab('Scale', scale);
    const box = el('span', { class: 'sm-mx-launch', style: 'display: contents' }, lUnb, lDdfm, lStruct, lType, lScale);
    let lastP = null;
    let hinted = null;          // the Validation hint's text while the dialog shows it
    const rnd = () => (E.all() || []).some((e) => e.random);
    const sync = (p) => {
      lastP = p;
      const r = rnd();
      const on = p === 'mixed' || (r && (p === 'standard' || p === 'glm'));
      // a Validation column with random effects: said in the dialog, not only in the report
      const vIds = (api.state && api.state.validation) || [];
      const vCol = vIds.length ? api.table.col(vIds[0]) : null;
      const want = vCol && on ? `${vCol.name} is in the Validation role: a model with random effects is fitted to every row, the validation and test rows too, and the column is not used.` : null;
      if (want && want !== hinted) { api.message(want, 'info'); hinted = want; }
      else if (!want && hinted) { api.message(''); hinted = null; }
      lUnb.hidden = lDdfm.hidden = !on;
      lStruct.hidden = p !== 'mixed';
      lType.hidden = p !== 'mixed' || !SPATIAL.has(struct.value);
      lScale.hidden = !(p === 'glm' && r);
      const rep = p === 'mixed' && struct.value !== 'residual';
      api.showRole('repeated', rep);
      if (p === 'mixed') api.showRole('subject', rep);
    };
    struct.addEventListener('change', () => sync(lastP));
    // the effects change without a role change: watch the list, so that the options follow the Random attribute
    requestAnimationFrame(() => {
      const list = box.parentElement && box.closest('.sm-fm-construct') ? box.closest('.sm-fm-construct').querySelector('.sm-fm-effects') : null;
      if (list && typeof MutationObserver !== 'undefined') new MutationObserver(() => { if (lastP) sync(lastP); }).observe(list, { childList: true, subtree: true });
    });
    const nestRC = () => {
      const cols = api.selectedColumns();
      const subj = cols.filter((c) => c.isCategorical);
      const selEff = E.selected();
      const slopes = [];
      for (const e of selEff) if (e.cols.length === 1 && !(e.nest || []).length && !e.cols[0].isCategorical && !slopes.includes(e.cols[0])) slopes.push(e.cols[0]);
      for (const c of cols) if (!c.isCategorical && !slopes.includes(c)) slopes.push(c);
      if (!subj.length) { E.msg('Nest Random Coefficients: select the subject (a categorical column whose levels each have their own intercept and slopes) in the list on the left, and the continuous effects in the model list (or the continuous columns on the left).'); return; }
      const k = 1 + Math.max(0, ...(E.all() || []).map((e) => e.rc || 0));
      const same = (e, ids, nest) => e.cols.map((c) => c.id).sort().join() === ids.map((c) => c.id).sort().join() && (e.nest || []).map((c) => c.id).sort().join() === nest.map((c) => c.id).sort().join();
      const want = [{ cols: subj, nest: [] }, ...slopes.map((x) => ({ cols: [x], nest: subj.slice() }))];
      const fresh = [];
      for (const w of want) {
        const old = (E.all() || []).find((e) => same(e, w.cols, w.nest));
        if (old) { old.random = true; old.rc = k; } else fresh.push({ cols: w.cols, nest: w.nest, random: true, rc: k });
      }
      E.msg('');
      if (fresh.length) E.add(fresh); else E.render();
    };
    const help = (p) => {
      const out = [];
      if (!lUnb.hidden) out.push(['Unbounded Variance Components', 'On (JMP\'s default): a variance component may be estimated below zero, as long as the covariance of the rows stays positive definite (a negative covariance within its levels); the tests of the fixed effects keep their size. Off: the components are held at zero or above, and one on the boundary is reported as zero.']);
      if (!lDdfm.hidden) out.push(['DF', 'The fixed effects\' denominator degrees of freedom: Kenward-Roger (JMP\'s, the first-order approximation, with the adjusted covariance of the estimates) or Satterthwaite (with the model-based covariance). Not a JMP option: JMP always uses Kenward-Roger.']);
      if (!lStruct.hidden) out.push(['Repeated Structure', 'The covariance of the errors within a subject (JMP Pro\'s Repeated Structure tab): Residual (independent, the default), Unequal Variances, Unstructured, AR(1), Compound Symmetry, Toeplitz, Antedependent and their unequal-variance forms, and the spatial structures. They need a Repeated column, most of them a Subject too.']);
      if (!lType.hidden) out.push(['Type', 'The spatial correlation as a function of the distance d: Power ρ^d, Exponential exp(−d/ρ), Gaussian exp(−d²/ρ²), Spherical 1 − 1.5 d/ρ + 0.5 (d/ρ)³ below ρ (0 beyond). With Nugget adds a jump at zero distance.']);
      if (!lScale.hidden) out.push(['Scale', 'The generalized linear mixed model\'s residual scale: Fixed at 1 (the binomial\'s and the Poisson\'s own variance, the default) or Estimated (overdispersion beyond what the random effects explain).']);
      if (p === 'mixed') out.push(['Nest Random Coefficients', 'Attributes > Nest Random Coefficients (Mixed Model): select the subject column on the left and the continuous effects in the model list, then choose it: a random intercept and a random slope for each, per subject, correlated (an unstructured covariance). Remove Intercept[subject] for random slopes alone.']);
      return out;
    };
    return {
      el: box, sync, help,
      read(p) { return { mxUnbounded: unb.checked, mxDdfm: ddfm.value, mxStructure: p === 'mixed' ? struct.value : 'residual', mxSptype: sptype.value, mxScale: scale.value }; },
      recall(o) {
        if (o.mxUnbounded != null) unb.checked = o.mxUnbounded !== false;
        if (o.mxDdfm) ddfm.value = o.mxDdfm;
        if (o.mxStructure) struct.value = o.mxStructure;
        if (o.mxSptype) sptype.value = o.mxSptype;
        if (o.mxScale) scale.value = o.mxScale;
      },
      attributes() { return [{ label: 'Nest Random Coefficients', action: nestRC }]; },
    };
  }

  /* ---- the payload of a report ------------------------------------------------------------------------------ */
  function kindOf(p) { return p === 'mixed' ? 'mixed' : p === 'glm' ? 'glmm' : 'sls'; }

  function mixedOf(ctx, M, kind) {
    const st = kind === 'mixed' ? ctx.opt('mxStructure', 'residual') : 'residual';
    const names = (k) => ctx.roles(k).map((c) => c.name);
    const rc = M.effects.filter((e) => e.random && e.rc).map((e) => [FM.labelOf(e.cols.map((c) => c.name), e.nest.map((c) => c.name)), e.rc]);
    const out = { unbounded: ctx.opt('mxUnbounded', true) !== false, ddfm: ctx.opt('mxDdfm', 'kr'), structure: st };
    if (st !== 'residual') Object.assign(out, { repeated: names('repeated'), subject: names('subject'), ...(SPATIAL.has(st) ? { sptype: ctx.opt('mxSptype', 'exp') } : {}) });
    if (rc.length) out.rc = rc;
    if (kind === 'glmm') {
      const dist = ctx.opt('dist', 'binomial');
      out.glmm = { dist, link: ctx.opt('link', null) || (dist === 'binomial' ? 'logit' : 'log'), scale: ctx.opt('mxScale', 'fixed'), target: ctx.opt('target', null) };
    }
    return out;
  }


  /* ---- the report ----------------------------------------------------------------------------------------------
     Three layouts, as JMP's: the Mixed Model personality (Fit Statistics, the
     random and repeated effects' covariance parameters, the fixed effects,
     Actual by Predicted and Actual by Conditional Predicted, Multiple
     Comparisons from the red triangle), Standard Least Squares with random
     effects (Summary of Fit, Parameter Estimates, REML Variance Component
     Estimates, Fixed Effect Tests, Effect Details with the least squares
     means) and the generalized linear mixed model (the Mixed Model's layout,
     the means on the scale of the response). */
  async function render(ctx, M, p) {
    const kind = kindOf(p);
    const ys = ctx.roles('y');
    let groups = ys.map((y) => ({ id: y.id, name: y.name, cols: [y] }));
    if (kind === 'glmm' && ctx.opt('dist', 'binomial') === 'binomial' && ys.length === 2 && ys.every((c) => !c.isCategorical)) {
      groups = [{ id: ys.map((c) => c.id).join('+'), name: ys.map((c) => c.name).join(', '), cols: ys }];
    }
    await FM.perResponse(ctx, groups, (g) => `Response ${g.name}`, (g, parent, st) => mixedY(ctx, M, g, parent, st, kind));
  }

  const TITLES = {
    mixed: { fit: 'Fit Statistics', vc: 'Random Effects Covariance Parameter Estimates', est: 'Fixed Effects Parameter Estimates', tests: 'Fixed Effects Tests', blups: 'Random Effects Predictions' },
    glmm: { fit: 'Fit Statistics', vc: 'Random Effects Covariance Parameter Estimates', est: 'Fixed Effects Parameter Estimates', tests: 'Fixed Effects Tests', blups: 'Random Effects Predictions' },
    sls: { fit: 'Summary of Fit', vc: 'REML Variance Component Estimates', est: 'Parameter Estimates', tests: 'Fixed Effect Tests', blups: 'Random Effect Predictions' },
  };

  /* The fit of a report, with its progress. A second into it (a quick fit shows nothing), the
     report's bar shows the REML iteration and its -2 Residual Log Likelihood (a GLMM's pseudo-likelihood
     iteration too), then the evaluations of the covariance parameters' information, from the fit's
     'smui:progress reml:<tag> ...' lines (the tag is this call's: a report waiting behind another shows
     none of the other's), and a Stop button. A call into Python cannot be interrupted: Stop restarts the
     engine, as the notebook's Stop does, which stops whatever else it runs; the report says it was
     stopped, and Redo runs it again. */
  async function fitCall(ctx, payload, label) {
    const rep = ctx.report;
    if (ctx.headless || !rep || !rep.bar) return ctx.call('fitmodel.mixed', payload);
    const tag = SM.util.uid('mxfit');
    const st = { it: 0, m2: null, info: null, rspl: 0, stopped: false, shown: false };
    const text = el('span', { role: 'status', style: { fontSize: '11.5px', color: 'var(--text-secondary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', minWidth: '0' } });
    const stop = el('button', { type: 'button', class: 'sm-btn small', text: 'Stop',
      title: 'Stop the fit. A calculation in Python cannot be interrupted: this restarts the Python engine, as the notebook\'s Stop does, and stops whatever else it is running.' });
    const box = el('span', { class: 'sm-mx-progress', style: { display: 'inline-flex', alignItems: 'center', gap: '6px', minWidth: '0', maxWidth: '100%' } }, text, stop);
    const say = () => {
      if (st.stopped) { text.textContent = 'Stopping: the Python engine restarts…'; return; }
      const who = label ? `${label}: ` : '';
      const pl = st.rspl ? `pseudo-likelihood iteration ${st.rspl}, ` : '';
      if (st.info) text.textContent = `${who}${pl}the covariance parameters' information, ${st.info[0]} of ${st.info[1]} evaluations…`;
      else if (st.it) text.textContent = `${who}${pl}REML iteration ${st.it}, −2 Residual Log Likelihood ${st.m2 == null ? '…' : fmt(st.m2, { sig: 10 })}…`;
      else text.textContent = `${who}${pl}fitting by REML…`;
    };
    stop.addEventListener('click', () => {
      if (st.stopped) return;
      st.stopped = true;
      rep._mxStopped = ctx.seq;       // the rest of this run (other responses, By groups) is not fitted
      stop.disabled = true;
      say();
      SM.engine.restart();
    });
    const timer = setTimeout(() => { st.shown = true; rep.bar.insertBefore(box, rep.noteEl); say(); }, 1000);
    const off = SM.engine.on('log', (m) => {
      const mm = /^smui:progress\s+(reml|remlinfo|rspl):(\S+)\s+(\d+)\s+(\d+)(?:\s+(\S+))?/.exec((m && m.text) || '');
      if (!mm || mm[2] !== tag) return;
      if (mm[1] === 'reml') { st.it = +mm[3]; st.info = null; st.m2 = mm[5] != null ? Number(mm[5]) : st.m2; }
      else if (mm[1] === 'remlinfo') st.info = [+mm[3], +mm[4]];
      else { st.rspl = +mm[3]; st.it = 0; st.info = null; }
      if (st.shown) say();
    });
    try {
      return await ctx.call('fitmodel.mixed', { ...payload, progress: tag });
    } catch (e) {
      if (!st.stopped) throw e;
      const err = new Error(`Stopped${st.it ? ` at REML iteration ${st.it}${st.m2 != null ? ` (−2 Residual Log Likelihood ${fmt(st.m2, { sig: 10 })})` : ''}` : ''}: Stop restarted the Python engine, and the fit was not finished. Redo runs it again; a Local Data Filter or a simpler structure makes it quicker.`);
      err.stopped = true;
      throw err;
    } finally {
      clearTimeout(timer);
      off();
      box.remove();
    }
  }

  async function mixedY(ctx, M, g, parent, st, kind) {
    const sc = g.id;
    const o = (k, d) => ctx.opt(k, d, sc);
    const y = g.cols[0];
    const payload = { ...M.base, y: g.cols.length === 1 ? y.name : g.cols.map((c) => c.name), mixed: mixedOf(ctx, M, kind) };
    if (ctx.report && ctx.report._mxStopped === ctx.seq) { parent.add(ctx.note('Not fitted: this run of the report was stopped. Redo runs it again.')); return; }
    let res;
    try {
      res = await fitCall(ctx, { ...payload, alpha: ctx.alpha }, [ctx.byLabel, ctx.roles('y').length > 1 ? g.name : ''].filter(Boolean).join(', '));
    } catch (e) {
      if (!e.stopped) throw e;
      parent.add(ctx.warn(e.message));
      return;
    }
    const S = { ctx, M, g, y, sc, o, payload, res, kind, parent, T: TITLES[kind], random: res.random_effects.length > 0,
      structure: res.structure.kind || 'residual', iso: ['ar1', 'sp', 'spn'].includes(res.structure.kind) };
    st.menu = () => menuOf(S);
    register(S);
    if (kind === 'glmm') {
      const f = res.fit.glmm;
      parent.add(el('p', { class: 'sm-fm-modelline' }, ...[['Response', `${g.name}`], ['Distribution', f.dist === 'binomial' ? 'Binomial' : 'Poisson'], ['Link', { logit: 'Logit', probit: 'Probit', cloglog: 'Comp LogLog', log: 'Log' }[f.link]],
        ['Estimation Method', 'Residual Pseudo-Likelihood (RSPL)'], ['Scale', f.scale === 'estimated' ? 'Estimated' : 'Fixed at 1'], ['Observations', fmt(res.fit.sumfreq)]]
        .map(([k, v]) => el('span', null, el('b', { text: `${k}: ` }), v))));
    }
    // (the REML and pseudo-likelihood fits take no validation column: the backend drops it)
    if (M.base.validation) parent.add(ctx.note(`${M.base.validation} (Validation) is not used: with random effects the fit takes every row of the report, the validation and test rows too.`));
    if (o('fitstats', true)) fitStats(S);
    // a spatial range beyond the data (a straight-line semivariogram): say why, and what to try
    if (res.spatial_inf) {
      const si = res.spatial_inf;
      const coords = (res.structure.repeated || []).join(' and ');
      const shape = si.sptype === 'gau' ? 'a parabola' : 'a straight line';
      parent.add(ctx.warn(`The ${si.parameter} range runs off to infinity: ${fmt(si.range, { sig: 4 })}, against a largest distance of ${fmt(si.dmax, { sig: 4 })} between rows that share a subject, where the fitted correlation is still ${fmt(si.corr, { sig: 4 })}. Over the distances in these data the semivariogram rises without levelling off (${shape}), which this structure reaches only with an infinite range and sill: the data fix their ratio, not either one, so the range, the sill and their standard errors mean little${res.fit.converged ? '' : ', and the fit could not converge'}. A trend is the usual reason: add the coordinates${coords ? ` (${coords})` : ''} as fixed effects, and fit again. Or try another type of spatial structure: Compare Structures, in the red triangle, fits them and ranks them by AICc.`));
    }
    if (res.score) parent.add(ctx.warn(`The fit did not converge. Convergence Score Test: ChiSquare ${fmt(res.score.stat, { sig: 4 })}, DF ${res.score.df}, Prob > ChiSq ${fmt(res.score.p, { sig: 4 })}${res.score.p > 0.05 ? ': not significant, so the estimates may be close to the maximum; use them with caution.' : ': the estimates are not at the maximum.'}`));
    if (kind === 'sls') {
      if (o('pe', true)) estimates(S);
      covparms(S);
      if (o('fixedtests', true) && res.tests.length) tests(S);
    } else {
      if (S.random && o('vcomp', true)) covparms(S);
      if (S.structure !== 'residual' && o('repcov', true)) repeatedCov(S);
      if (o('fixedest', true)) estimates(S);
      if (o('fixedtests', true) && res.tests.length) tests(S);
    }
    if (S.structure === 'un' && o('rmdiag', false)) rmDiagnostics(S);
    if (S.random && o('blups', false)) blups(S);
    if (S.random && o('rcoef', kind !== 'sls' && res.coefs.some((c) => c.coefs.length > 1))) randomCoefs(S);
    // the plots
    const plots = [];
    if (o('actMarg', true)) plots.push(scatterOutline(S, 'actmarg', 'Actual by Predicted Plot', 'marginal', 'actual', `${y.name} Predicted`, `${y.name} Actual`, 'actMarg', true, `${y.name} actual by predicted`));
    if (S.random && o('actCond', kind !== 'sls')) plots.push(scatterOutline(S, 'actcond', 'Actual by Conditional Predicted Plot', 'predicted', 'actual', `${y.name} Conditional Predicted`, `${y.name} Actual`, 'actCond', true, `${y.name} actual by conditional predicted`));
    if (o('resMarg', kind === 'sls')) plots.push(scatterOutline(S, 'resmarg', kind === 'sls' ? 'Residual by Predicted Plot' : 'Residual by Predicted Plot (marginal)', 'marginal', 'marg_resid', `${y.name} Predicted`, `${y.name} Residual`, 'resMarg', false, 'marginal residuals'));
    if (S.random && o('resCond', false)) plots.push(scatterOutline(S, 'rescond', 'Conditional Residual by Predicted Plot', 'predicted', 'residual', `${y.name} Conditional Predicted`, 'Conditional Residual', 'resCond', false, 'conditional residuals'));
    if (plots.length > 1) parent.add(ctx.row(...plots.map((ob) => ob.el)));
    if (S.iso && o('variogram', true)) await variogram(S);
    else if (!S.iso && o('variogram', false)) await variogram(S);
    if (kind === 'sls' && o('effdet', true)) await effectDetails(S);
    for (const [i, mc] of (o('mc', []) || []).entries()) await multipleComparison(S, mc, i);
    if (o('covfe', false)) matrixOutline(S, 'covfe', 'Covariance of Fixed Effects', res.covfixed.names, res.covfixed.cov);
    if (o('corfe', false)) { const C = res.covfixed.cov; const sd = C.map((r, i) => Math.sqrt(Math.max(r[i], 0))); matrixOutline(S, 'corfe', 'Correlation of Fixed Effects', res.covfixed.names, C.map((r, i) => r.map((v, j) => v / (sd[i] * sd[j])))); }
    if (o('covcp', false)) matrixOutline(S, 'covcp', 'Covariance of Covariance Parameters', res.covparms.names, res.covparms.cov);
    if (o('indicator', false)) await indicatorOutline(S);
    if (o('iters', false)) iterations(S);
    if (o('skeleton', false)) await skeleton(S);
    if (o('structures', false)) await compareStructures(S);
    if (o('profci', false)) await profileIntervals(S);
    if (o('profiler', false)) await FM.profiler(ctx, parent, { sources: [{ kind: 'mixed', payload }], scope: sc, title: kind === 'sls' ? 'Prediction Profiler' : 'Marginal Model Profiler' });
    if (S.random && o('condprof', false)) await conditionalProfiler(S);
    if (o('contour', false)) await FM.contourProfiler(ctx, parent, { kind: 'mixed', payload, factors: res.factors, scope: sc });
    if (o('interaction', false)) await FM.interactionPlots(ctx, parent, { kind: 'mixed', payload, scope: sc });
    const sim = o('simulate', null);
    if (sim) await simulateReport(S, sim);
    const cmp = o('comparemodels', null);
    if (cmp) compareModels(S, cmp);
    FM.tail(ctx, parent, res);
  }

  /* ---- Fit Statistics / Summary of Fit ----------------------------------------------------------------- */
  function fitStats(S) {
    const { ctx, res, kind, parent, o } = S;
    const f = res.fit;
    const ob = ctx.outline(S.T.fit, { parent, key: 'fitstats', info: 'p:fitmodel:mixed' });
    if (kind === 'sls') {
      const rows = res.summary.map((r) => [r.stat, r.value, r.stat.startsWith('Observations') ? 'num' : undefined]);
      if (o('aicc', false)) rows.push(['-2 Residual Log Likelihood', f.m2rll], ['AICc', f.aicc], ['BIC', f.bic]);
      ob.add(ctx.kv(rows));
      return;
    }
    const pl = kind === 'glmm' ? ' Pseudo' : '';
    const rows = [['Number of Rows', f.rows, 'int'], ['Sum of Frequencies', f.sumfreq, 'int'], [`-2 Residual Log${pl} Likelihood`, f.m2rll], [`-2 Log${pl} Likelihood`, f.m2ll], ['AICc', f.aicc], ['BIC', f.bic]];
    if (kind === 'glmm') rows.push(['Generalized Chi-Square', f.gen_chisq], ['Gener. Chi-Square / DF', f.gen_chisq_df], ['Pseudo-Likelihood Iterations', f.glmm_iter, 'int']);
    ob.add(ctx.kv(rows));
  }

  /* ---- the covariance parameters --------------------------------------------------------------------------- */
  function covparms(S) {
    const { ctx, res, kind, parent, o } = S;
    const p = pct(ctx);
    const vcOnly = res.vc_only;
    const hasSubj = res.varcomp.some((r) => r.subject);
    const cols = kind === 'sls'
      ? [{ key: 'effect', label: 'Random Effect', fmt: 'text' }, { key: 'ratio', label: 'Var Ratio' }, { key: 'var', label: 'Var Component' }, { key: 'se', label: 'Std Error' },
        { key: 'lower', label: `${p}% Lower` }, { key: 'upper', label: `${p}% Upper` }, ...(res.fit.unbounded ? [{ key: 'p', label: 'Wald p-Value', fmt: 'p' }] : []),
        { key: 'sqrt', label: 'Sqrt Variance Component', hidden: true }, { key: 'pct', label: 'Pct of Total', digits: 3 }]
      : [{ key: 'effect', label: vcOnly ? 'Variance Component' : 'Covariance Parameter', fmt: 'text' }, ...(hasSubj ? [{ key: 'subject', label: 'Subject', fmt: 'text' }] : []),
        { key: 'ratio', label: 'Var Ratio' }, { key: 'var', label: 'Estimate' }, { key: 'se', label: 'Std Error' }, { key: 'lower', label: `${p}% Lower` }, { key: 'upper', label: `${p}% Upper` },
        ...(res.fit.unbounded ? [{ key: 'p', label: 'Wald p-Value', fmt: 'p' }] : []), ...(vcOnly ? [{ key: 'sqrt', label: 'Sqrt Variance Component', hidden: true }, { key: 'pct', label: 'Pct of Total', digits: 3 }] : [])];
    const ob = ctx.outline(S.T.vc, { parent, key: 'varcomp', info: 'p:fitmodel:mixed' });
    ob.add(ctx.rt({ columns: cols, rows: res.varcomp }, { sortable: false, key: 'varcomp' }));
    if (vcOnly && res.varcomp.some((r) => !r.total && r.var < 0)) ob.add(ctx.note(`Total is the sum of the positive variance components only; the sum of all of them is ${fmt(res.allsum, { sig: 6 })}.`));
    if (!res.fit.unbounded) ob.add(ctx.note('Unbounded Variance Components is off: the components are held at zero or above, and their intervals are Satterthwaite\'s (bounded at zero).'));
    void o;
  }

  function repeatedCov(S) {
    const { ctx, res, parent } = S;
    const p = pct(ctx);
    const ob = ctx.outline('Repeated Effects Covariance Parameter Estimates', { parent, key: 'repcov', info: 'p:fitmodel:mixed:repeated' });
    const hasSubj = res.repeated.some((r) => r.subject);
    ob.add(ctx.rt({ columns: [{ key: 'param', label: 'Covariance Parameter', fmt: 'text' }, ...(hasSubj ? [{ key: 'subject', label: 'Subject', fmt: 'text' }] : []), { key: 'estimate', label: 'Estimate' },
      { key: 'se', label: 'Std Error' }, { key: 'lower', label: `${p}% Lower` }, { key: 'upper', label: `${p}% Upper` }], rows: res.repeated }, { sortable: false, key: 'repcov' }));
    const s = res.structure;
    ob.add(ctx.note(`${s.label}${s.repeated ? `, Repeated: ${s.repeated.join(', ')}` : ''}${s.subject && s.subject.length ? `, Subject: ${s.subject.join(', ')}` : ''}.${SPATIAL.has(s.kind) ? ' The range is the spatial parameter; Residual is the partial sill; the Nugget is scaled by the Residual (the nugget is their product).' : ''}`));
  }

  /* The Unstructured covariance as a matrix, with the correlations as a heat map (JMP's Repeated Measures
     Covariance Diagnostics). */
  function rmDiagnostics(S) {
    const { ctx, res, parent, y } = S;
    const rm = res.rmatrix;
    if (!rm) return;
    const ob = ctx.outline('Repeated Measures Covariance Diagnostics', { parent, key: 'rmdiag', info: 'p:fitmodel:mixed:repeated', menu: () => [{ label: 'Remove', action: () => ctx.set('rmdiag', false, S.sc) }] });
    ob.add(matrixTable(ctx, rm.levels, rm.cov, 'Covariance Matrix', 'rmcov'), matrixTable(ctx, rm.levels, rm.corr, 'Correlation Matrix', 'rmcorr'));
    const all = rm.corr.flat().filter((v, i) => i % (rm.levels.length + 1) !== 0);
    const lo = all.every((v) => v >= 0) ? 0 : -1;
    const P = FM.pal();
    const trace = { type: 'heatmap', x: rm.levels, y: rm.levels, z: rm.corr, zmin: lo, zmax: 1, colorscale: lo === 0 ? [[0, P.dark ? '#1b2a3a' : '#f3f6fa'], [1, '#2f6690']] : 'RdBu', reversescale: lo !== 0,
      colorbar: { thickness: 10, title: { text: 'Correlation', side: 'right' } }, hovertemplate: '%{y} × %{x}: %{z:.3f}<extra></extra>' };
    ob.add(ctx.plot([trace], { xaxis: { type: 'category', title: { text: res.structure.repeated[0] } }, yaxis: { type: 'category', autorange: 'reversed', title: { text: res.structure.repeated[0] } }, margin: { l: 70, r: 20, t: 8, b: 50 } },
      { width: FM.W(420), height: 360, title: `${y.name} correlation heat map`, select: false }), ctx.code(heatmapCode(res, lo, y.name)));
  }

  function heatmapCode(res, lo, yname) {
    const lines = res.code.split('\n');
    const at = lines.findIndex((l) => l.startsWith('# the covariance of the covariance parameters'));
    const head = (at > 0 ? lines.slice(0, at) : lines).filter((l) => !l.startsWith('print('));
    head.splice(1, 0, 'import matplotlib.pyplot as plt');
    return [...head,
      'S = np.zeros((J, J))',
      'for t, (i, j) in zip(th[nG:], iu): S[i, j] = S[j, i] = t   # the unstructured covariance of the levels',
      'sd = np.sqrt(np.diag(S)); Cr = S / np.outer(sd, sd)',
      'fig, ax = plt.subplots(figsize=(5, 4.2))',
      `im = ax.imshow(Cr, cmap=${lo === 0 ? '"Blues"' : '"RdBu_r"'}, vmin=${lo}, vmax=1)`,
      `labels = ${JSON.stringify(res.rmatrix.levels)}`,
      'ax.set_xticks(range(J)); ax.set_xticklabels(labels); ax.set_yticks(range(J)); ax.set_yticklabels(labels)',
      'fig.colorbar(im, ax=ax, label="Correlation")',
      `ax.set_xlabel(${JSON.stringify(res.structure.repeated[0])}); ax.set_ylabel(${JSON.stringify(res.structure.repeated[0])})`,
      `ax.set_title(${JSON.stringify(`${yname} correlation heat map`)})`,
      'plt.show()'].join('\n');
  }

  function matrixTable(ctx, names, M, caption, key) {
    const cols = [{ key: 'row', label: '', fmt: 'text' }, ...names.map((n, j) => ({ key: `c${j}`, label: n }))];
    const rows = names.map((n, i) => ({ row: n, ...Object.fromEntries(M[i].map((v, j) => [`c${j}`, v])) }));
    return ctx.rt({ columns: cols, rows }, { caption, sortable: false, key });
  }

  function matrixOutline(S, key, title, names, M) {
    const { ctx, parent, sc } = S;
    ctx.outline(title, { parent, key, menu: () => [{ label: 'Remove', action: () => ctx.set(key, false, sc) }] }).add(matrixTable(ctx, names, M, null, `${key}t`));
  }

  /* ---- the fixed effects ------------------------------------------------------------------------------------- */
  function estimates(S) {
    const { ctx, res, parent, o } = S;
    const p = pct(ctx);
    const ci = o('showCI', S.kind !== 'sls');
    ctx.outline(S.T.est, { parent, key: 'estimates', info: 'p:fitmodel:mixed' }).add(
      ctx.rt({ columns: [{ key: 'term', label: 'Term', fmt: 'text' }, { key: 'estimate', label: 'Estimate' }, { key: 'se', label: 'Std Error' }, { key: 'dfden', label: 'DFDen', digits: 2 },
        { key: 't', label: 't Ratio' }, { key: 'p', label: 'Prob>|t|', fmt: 'p' }, { key: 'lower', label: `${p}% Lower`, hidden: !ci }, { key: 'upper', label: `${p}% Upper`, hidden: !ci }], rows: res.estimates }, { key: 'estimates' }));
  }

  function tests(S) {
    const { ctx, res, parent } = S;
    ctx.outline(S.T.tests, { parent, key: 'tests', info: 'p:fitmodel:mixed' }).add(ctx.rt({ columns: [{ key: 'source', label: 'Source', fmt: 'text' }, { key: 'nparm', label: 'Nparm', fmt: 'int' },
      { key: 'dfnum', label: 'DFNum', fmt: 'int' }, { key: 'dfden', label: 'DFDen', digits: 2 }, { key: 'f', label: 'F Ratio' }, { key: 'p', label: 'Prob > F', fmt: 'p' }], rows: res.tests }, { key: 'tests' }));
  }

  /* ---- the random effects' predictions ------------------------------------------------------------------------- */
  function blups(S) {
    const { ctx, res, parent, o } = S;
    const p = pct(ctx);
    const ci = o('showCI', false);
    const ob = ctx.outline(S.T.blups, { parent, key: 'blups', info: 'p:fitmodel:mixed:blups' });
    for (const b of res.blups) {
      ob.add(ctx.rt({ columns: [{ key: 'term', label: 'Term', fmt: 'text' }, { key: 'blup', label: 'BLUP' }, { key: 'se', label: 'Std Error' }, { key: 'dfden', label: 'DFDen', digits: 2 },
        { key: 't', label: 't Ratio' }, { key: 'p', label: 'Prob>|t|', fmt: 'p' }, { key: 'lower', label: `Lower ${p}%`, hidden: !ci }, { key: 'upper', label: `Upper ${p}%`, hidden: !ci }], rows: b.rows },
      { caption: b.effect + (b.subject ? ` (subject ${b.subject})` : ''), key: `blup:${b.effect}` }));
    }
    ob.add(ctx.note('Each prediction\'s standard error is its prediction error (the variance of the prediction minus the random effect), with Satterthwaite\'s degrees of freedom, as JMP computes them (without the Kackar-Harville correction).'));
  }

  function randomCoefs(S) {
    const { ctx, res, parent } = S;
    const ob = ctx.outline('Random Coefficients', { parent, key: 'rcoef', info: 'p:fitmodel:mixed:blups', closed: true });
    for (const c of res.coefs) {
      const cols = [{ key: 'level', label: c.subject || c.effect, fmt: 'text' }, ...c.coefs.map((n, j) => ({ key: `c${j}`, label: n }))];
      ob.add(ctx.rt({ columns: cols, rows: c.levels.map((lv, i) => ({ level: lv, ...Object.fromEntries(c.coefs.map((_, j) => [`c${j}`, c.u[i][j]])) })) }, { caption: c.effect, key: `rcoef:${c.effect}` }));
      if (c.sigma) ob.add(matrixTable(ctx, c.coefs, c.sigma, `${c.effect}: the covariance of the coefficients`, `rcsig:${c.effect}`));
    }
    ob.add(ctx.note('A level\'s coefficients are its departures from the fixed effects: its own intercept and slopes are the fixed estimates plus these.'));
  }

  /* ---- the plots ---------------------------------------------------------------------------------------------- */
  function scatterOutline(S, key, title, xk, yk, xTitle, yTitle, codeKey, diag, figTitle) {
    const { ctx, res, parent } = S;
    const P = FM.pal();
    const d = res.diag;
    const ob = ctx.outline(title, { parent, key, info: 'p:fitmodel:mixed', menu: () => [{ label: 'Remove', action: () => ctx.set(codeKey, false, S.sc) }] });
    const x = d[xk], y = d[yk];
    const lines = [];
    const hl = [];
    if (diag) { const [lo, hi] = FM.extent(x, y); lines.push(FM.lineTrace([lo, hi], [lo, hi], P.fit)); } else hl.push({ y: 0, color: P.mean });
    ob.add(FM.rowPlot(ctx, { x, y, rows: d.rows, xTitle, yTitle, lines, hlines: hl, width: 400, height: 320, title: figTitle }), ctx.code(FM.codeOf(res, codeKey)));
    return ob;
  }

  /* ---- the variogram ---------------------------------------------------------------------------------------------- */
  const VARIO_CURVES = [['ar1', 'AR(1)'], ...SPTYPES.map(([k, l]) => [`sp:${k}`, `Spatial ${l}`]), ...SPTYPES.map(([k, l]) => [`spn:${k}`, `Spatial with Nugget ${l}`])];

  async function variogram(S) {
    const { ctx, parent, sc, payload, y } = S;
    const curves = S.o('vcurves', []) || [];
    const colsOpt = S.o('vcols', null);
    const r = await ctx.call('mixed.variogram', { ...payload, curves, ...(colsOpt ? { columns: colsOpt } : {}) });
    const menu = () => [
      ...VARIO_CURVES.map(([k, l]) => ({ label: l, checked: curves.includes(k), action: () => ctx.set('vcurves', curves.includes(k) ? curves.filter((x) => x !== k) : [...curves, k], sc) })),
      { separator: true },
      ...(S.structure === 'residual' ? [{ label: 'Columns…', action: () => variogramColumns(S) }] : []),
      { label: 'Remove', action: () => ctx.set('variogram', false, sc) }];
    const ob = ctx.outline('Variogram', { parent, key: 'variogram', menu, info: 'p:fitmodel:mixed:variogram' });
    if (r.error) {
      ob.add(ctx.note(S.structure === 'residual' ? `${r.error}. Choose the columns with the Variogram outline's red triangle (Columns…).` : r.error));
      return;
    }
    const P = FM.pal();
    const traces = [{ type: 'scatter', mode: 'markers', x: r.points.map((p) => p.h), y: r.points.map((p) => p.gamma), name: 'Empirical', marker: { size: 8, color: P.point },
      text: r.points.map((p) => `${p.n} pairs`), hovertemplate: 'distance %{x:.4g}: %{y:.5g} (%{text})<extra></extra>' }];
    r.curves.forEach((c, i) => traces.push({ type: 'scatter', mode: 'lines', x: c.h, y: c.gamma, name: c.label, line: { color: c.fit ? P.fit : SM.util.PALETTE[(i + 1) % SM.util.PALETTE.length], width: c.fit ? 1.8 : 1.3, dash: c.fit ? 'solid' : 'dash' }, hoverinfo: 'skip' }));
    ob.add(ctx.plot(traces, { showlegend: r.curves.length > 0, xaxis: { title: { text: `Distance (${r.columns.join(', ')})` }, rangemode: 'tozero' }, yaxis: { title: { text: 'Semivariance' }, rangemode: 'tozero' }, margin: { l: 58, r: 12, t: 8, b: 46 } },
      { width: FM.W(460), height: 320, title: `${y.name} variogram`, select: false }), ctx.code(r.plot_code));
    ob.add(ctx.note('The empirical semivariance of the marginal residuals (Y minus the fixed effects\' prediction) in ten equal distance classes, pairs within a subject; the solid line from the model\'s estimates, dashed lines fitted to the points (the red triangle adds them).'));
  }

  async function variogramColumns(S) {
    const { ctx, sc } = S;
    const cont = ctx.table.columns.filter((c) => c.isNumeric && !c.isCategorical);
    const v = await SM.ui.form({ title: 'Variogram Columns', lead: 'The continuous columns that place the rows in time or space; the distance between two rows is the Euclidean distance of their values.',
      fields: cont.slice(0, 12).map((c, i) => ({ key: `c${i}`, label: c.name, type: 'check', value: (S.o('vcols', []) || []).includes(c.name), helpLabel: 'A column', help: 'Checked columns are the coordinates of the variogram.' })) });
    if (!v) return;
    const chosen = cont.slice(0, 12).filter((c, i) => v[`c${i}`]).map((c) => c.name);
    ctx.set('vcols', chosen, sc, { rerun: false });
    ctx.set('variogram', true, sc);
  }

  /* ---- least squares means ----------------------------------------------------------------------------------------
     Standard Least Squares: Effect Details, an outline per categorical fixed effect with its LS means and
     their red triangle; Mixed Model: the Multiple Comparisons dialog adds a report for an effect. Both use
     mixed.lsmeans/compare/contrast/slices: the mixed covariance of the fixed effects and each mean's own
     degrees of freedom (Kenward-Roger or Satterthwaite). */
  async function effectDetails(S) {
    const { ctx, res, parent } = S;
    if (!res.lsm_effects.length) return;
    const ob = ctx.outline('Effect Details', { parent, key: 'effdet', info: 'p:fitmodel:mixed:lsmeans' });
    for (const label of res.lsm_effects) {
      const scope = S.sc;
      const key = (k) => `${k}:${label}`;
      const two = label.includes('*');
      const eo = ctx.outline(label, { parent: ob, key: `eff:${label}`, menu: () => [
        ctx.check('LSMeans Plot', key('lsplot'), scope, false),
        ctx.check('LSMeans Student\'s t', key('student'), scope, false),
        ctx.check('LSMeans Tukey HSD', key('tukey'), scope, false),
        { label: 'LSMeans Contrast…', action: () => contrastDialog(S, label) },
        ...(two ? [ctx.check('Test Slices', key('slices'), scope, false)] : []),
      ] });
      await lsmeansBlock(S, eo, label, { plot: S.o(key('lsplot'), false), student: S.o(key('student'), false), tukey: S.o(key('tukey'), false),
        slices: two && S.o(key('slices'), false), contrasts: S.o(key('contrast'), []) || [] });
    }
  }

  async function lsmeansBlock(S, parentOb, label, want, mcIndex = null) {
    const { ctx, y } = S;
    const r = await ctx.call('mixed.lsmeans', { ...S.payload, effect: label, alpha: ctx.alpha });
    const lsm = r.lsmeans[label];
    if (!lsm) { parentOb.add(ctx.note(`${label}: least squares means are for effects of categorical factors.`)); return; }
    const p = pct(ctx);
    const multi = lsm.factors.length > 1;
    const fcols = multi ? lsm.factors.map((f, i) => ({ key: `f${i}`, label: f, fmt: 'text' })) : [{ key: 'level', label: 'Level', fmt: 'text' }];
    const glmm = lsm.glmm;
    const cols = [...fcols, { key: 'lsmean', label: 'Least Sq Mean' }, { key: 'se', label: 'Std Error' }, { key: 'dfden', label: 'DFDen', digits: 2 },
      { key: 'lower', label: `Lower ${p}%`, hidden: !S.o('showCI', S.kind !== 'sls') }, { key: 'upper', label: `Upper ${p}%`, hidden: !S.o('showCI', S.kind !== 'sls') },
      ...(glmm ? [{ key: 'mu', label: 'Mean' }, { key: 'mu_se', label: 'Std Error of Mean' }, { key: 'mu_lower', label: `Mean Lower ${p}%` }, { key: 'mu_upper', label: `Mean Upper ${p}%` }] : [{ key: 'mean', label: 'Mean' }])];
    parentOb.add(ctx.rt({ columns: cols, rows: lsm.rows }, { caption: 'Least Squares Means Table', key: `lsm:${label}` }), ctx.code(r.code));
    if (glmm) parentOb.add(ctx.note(`The least squares means are on the ${lsm.link} scale of the linear predictor; Mean is its inverse (${lsm.link === 'log' ? 'a rate' : 'a probability'}), with a delta-method standard error and the interval's ends transformed.`));
    if (want.plot) lsmeansPlot(S, parentOb, label, lsm, r.code, mcIndex);
    if (want.student) await comparisons(S, parentOb, label, 'student', mcIndex);
    if (want.tukey) await comparisons(S, parentOb, label, 'tukey', mcIndex);
    if (want.slices) await slicesReport(S, parentOb, label);
    if (want.contrasts && want.contrasts.length) await contrastsReport(S, parentOb, label, want.contrasts, mcIndex);
    void y;
  }

  /* The LSMeans Plot: one factor, the means with their intervals; an interaction, lines across one factor
     for each level of the overlay (JMP's interaction plot), the intervals on or off. */
  function lsmeansPlot(S, parentOb, label, lsm, code, mcIndex) {
    const { ctx, y, sc } = S;
    const P = FM.pal();
    const okey = mcIndex == null ? `lsov:${label}` : `mcov:${mcIndex}`;
    const ckey = mcIndex == null ? `lsci:${label}` : `mcci:${mcIndex}`;
    const facs = lsm.factors;
    const ov = facs.length > 1 ? Math.min(Math.max(0, Number(S.o(okey, 1))), facs.length - 1) : null;
    const showCI = S.o(ckey, true) !== false;
    const xi = facs.length > 1 ? (ov === 0 ? 1 : 0) : 0;
    const txt = (k, i) => lsm.rows[k][facs.length > 1 ? `f${i}` : 'level'];
    const xs = [...new Set(lsm.rows.map((_, k) => txt(k, xi)))];
    const traces = [];
    const eb = (idx) => ({ type: 'data', symmetric: false, array: idx.map((k) => lsm.upper[k] - lsm.lsmean[k]), arrayminus: idx.map((k) => lsm.lsmean[k] - lsm.lower[k]), visible: showCI, thickness: 1, width: 4 });
    if (ov == null) {
      const idx = lsm.rows.map((_, k) => k);
      traces.push({ type: 'scatter', mode: 'lines+markers', x: idx.map((k) => txt(k, 0)), y: idx.map((k) => lsm.lsmean[k]), line: { color: P.point, width: 1.4 }, marker: { size: 8, color: P.point },
        error_y: { ...eb(idx), color: P.point }, hovertemplate: '%{x}: %{y:.5g}<extra></extra>', showlegend: false });
    } else {
      const groups = [...new Set(lsm.rows.map((_, k) => txt(k, ov)))];
      groups.forEach((gv, gi) => {
        const idx = lsm.rows.map((_, k) => k).filter((k) => txt(k, ov) === gv);
        const c = SM.util.PALETTE[gi % SM.util.PALETTE.length];
        traces.push({ type: 'scatter', mode: 'lines+markers', x: idx.map((k) => txt(k, xi)), y: idx.map((k) => lsm.lsmean[k]), name: gv, line: { color: c, width: 1.6 }, marker: { size: 7, color: c },
          error_y: { ...eb(idx), color: c } });
      });
    }
    const menu = () => [
      { label: 'Show Confidence Limits', checked: showCI, action: () => ctx.set(ckey, !showCI, sc) },
      ...(facs.length > 1 ? [{ label: 'Overlay', submenu: () => facs.map((f, i) => ({ label: f, checked: ov === i, action: () => ctx.set(okey, i, sc) })) }] : []),
      { label: 'Remove', action: () => ctx.set(mcIndex == null ? `lsplot:${label}` : `mc:${mcIndex}:plot`, false, sc) }];
    const ob = ctx.outline('Least Squares Means Plot', { parent: parentOb, key: `lsplot:${label}:${mcIndex ?? ''}`, menu });
    const xTitle = facs[xi];
    ob.add(ctx.plot(traces, { showlegend: ov != null, legend: ov != null ? { title: { text: facs[ov] } } : undefined, xaxis: { type: 'category', categoryorder: 'array', categoryarray: xs, title: { text: xTitle } },
      yaxis: { title: { text: `${y.name} LS Means` } }, margin: { l: 58, r: 12, t: 8, b: 46 } }, { width: FM.W(ov != null ? 440 : 380), height: 300, title: `${label} LS means plot` }),
    ctx.code(lsmeansPlotCode(code, lsm, xi, ov, showCI, label, y.name, ctx.alpha)));
  }

  function lsmeansPlotCode(code, lsm, xi, ov, showCI, label, yname, alpha) {
    if (!code) return null;
    const lines = code.split('\n').filter((l) => !/^\s*print\(/.test(l) && !/^for cell, v, Lr in zip/.test(l) && !/^\s+se = np.sqrt\(Lr @ PhiA @ Lr\); dfd = ddf/.test(l));
    lines.splice(1, 0, 'import matplotlib.pyplot as plt');
    const J = JSON.stringify;
    const out = [...lines,
      'se = np.sqrt(np.einsum("ij,jk,ik->i", Lm, PhiA, Lm)); dfs = [ddf(Lr[None, :])[1] for Lr in Lm]',
      `half = np.array([stats.t.ppf(1 - ${alpha} / 2, v) for v in dfs]) * se   # each mean's interval, its own df`,
      'fig, ax = plt.subplots(figsize=(5.2, 3.6))',
      `xs = sorted({c[${xi}] for c in cells}, key=[c[${xi}] for c in cells].index)`];
    if (ov == null) {
      out.push(`ax.errorbar(range(len(xs)), lsm, yerr=${showCI ? 'half' : 'None'}, marker="o", color="#2f6690", capsize=3)`);
    } else {
      out.push(`for g in sorted({c[${ov}] for c in cells}, key=[c[${ov}] for c in cells].index):   # one line per level of the overlay`,
        `    idx = [i for i, c in enumerate(cells) if c[${ov}] == g]`,
        `    ax.errorbar([xs.index(cells[i][${xi}]) for i in idx], lsm[idx], yerr=${showCI ? 'half[idx]' : 'None'}, marker="o", capsize=3, label=str(g))`,
        `ax.legend(title=${J(lsm.factors[ov])}, fontsize=8, frameon=False)`);
    }
    out.push('ax.set_xticks(range(len(xs))); ax.set_xticklabels([str(v) for v in xs])', `ax.set_xlabel(${J(lsm.factors[xi])}); ax.set_ylabel(${J(`${yname} LS Means`)})`,
      `ax.set_title(${J(`${label} LS means plot`)})`, 'plt.show()');
    return out.join('\n');
  }

  async function comparisons(S, parentOb, label, method, mcIndex) {
    const { ctx, sc } = S;
    const r = await ctx.call('mixed.compare', { ...S.payload, effect: label, method, alpha: ctx.alpha });
    const title = method === 'tukey' ? 'LSMeans Differences Tukey HSD' : 'LSMeans Differences Student\'s t';
    const rmKey = mcIndex == null ? `${method}:${label}` : null;
    const ob = ctx.outline(title, { parent: parentOb, key: `cmp:${method}:${label}:${mcIndex ?? ''}`, info: 'p:fitmodel:mixed:lsmeans',
      menu: () => (rmKey ? [{ label: 'Remove', action: () => ctx.set(rmKey, false, sc) }] : []) });
    if (r.error) { ob.add(ctx.warn(r.error)); return; }
    ob.add(ctx.kv([['α', r.alpha]]));
    const lets = ctx.outline('Connecting Letters Report', { parent: ob, key: `letters:${method}:${label}` });
    lets.add(ctx.rt({ columns: [{ key: 'level', label: 'Level', fmt: 'text' }, { key: 'letters', label: '', fmt: 'text' }, { key: 'lsmean', label: 'Least Sq Mean' }, { key: 'se', label: 'Std Error' },
      ...(r.letters[0] && r.letters[0].mu != null ? [{ key: 'mu', label: 'Mean' }] : [])], rows: r.letters }, { sortable: false, key: 'letters' }),
    ctx.note('Levels not connected by the same letter are significantly different.'));
    const od = ctx.outline('Ordered Differences Report', { parent: ob, key: `ordered:${method}:${label}` });
    od.add(ctx.rt({ columns: [{ key: 'level', label: 'Level', fmt: 'text' }, { key: 'minus', label: '- Level', fmt: 'text' }, { key: 'diff', label: 'Difference' }, { key: 'se', label: 'Std Err Dif' },
      { key: 'dfden', label: 'DFDen', digits: 2 }, { key: 'lower', label: 'Lower CL' }, { key: 'upper', label: 'Upper CL' }, { key: 'p', label: 'p-Value', fmt: 'p' },
      ...(r.ratio ? [{ key: 'ratio', label: r.ratio }, { key: 'ratio_lower', label: `${r.ratio} Lower` }, { key: 'ratio_upper', label: `${r.ratio} Upper` }] : [])], rows: r.ordered }, { key: 'ordered' }));
    if (r.ratio) od.add(ctx.note(`${r.ratio}: the difference on the ${r.ratio === 'Odds Ratio' ? 'logit' : 'log'} scale exponentiated, with its interval.`));
    ob.add(ctx.code(r.code));
  }

  async function contrastDialog(S, label, mcIndex = null) {
    const { ctx, sc } = S;
    const r = await ctx.call('mixed.lsmeans', { ...S.payload, effect: label, alpha: ctx.alpha });
    const lsm = r.lsmeans[label];
    if (!lsm) return;
    const key = mcIndex == null ? `contrast:${label}` : `mc:${mcIndex}:contrast`;
    const v = await SM.ui.form({
      title: `LSMeans Contrast: ${label}`, lead: 'A weight for each level; the weights of a contrast usually sum to zero (1, −1, 0 compares the first two levels). Each OK adds a contrast; the joint test covers all of them.',
      fields: lsm.labels.map((l, i) => ({ key: `c${i}`, label: l, type: 'number', value: i === 0 ? 1 : i === 1 ? -1 : 0, helpLabel: 'The weight of each level',
        help: 'The contrast is the sum of the weights times the least squares means, tested with t against 0 on its own denominator degrees of freedom (Kenward-Roger or Satterthwaite); the joint F test covers every contrast added.' })),
    });
    if (!v) return;
    const coefs = lsm.labels.map((_, i) => v[`c${i}`] || 0);
    if (coefs.every((c) => c === 0)) { SM.ui.toast('Give at least one nonzero weight'); return; }
    ctx.set(key, [...(S.o(key, []) || []), coefs], sc);
  }

  async function contrastsReport(S, parentOb, label, list, mcIndex) {
    const { ctx, sc } = S;
    const r = await ctx.call('mixed.contrast', { ...S.payload, effect: label, coefs: list, alpha: ctx.alpha });
    const key = mcIndex == null ? `contrast:${label}` : `mc:${mcIndex}:contrast`;
    const ob = ctx.outline('Contrast', { parent: parentOb, key: `contrast:${label}:${mcIndex ?? ''}`, menu: () => [{ label: 'Remove Contrasts', action: () => ctx.set(key, [], sc) }] });
    if (r.error) { ob.add(ctx.warn(r.error)); return; }
    const p = pct(ctx);
    const cols = [{ key: 'contrast', label: 'Contrast', fmt: 'int' }, ...r.labels.map((l, i) => ({ key: `w${i}`, label: l })), { key: 'estimate', label: 'Estimate' }, { key: 'se', label: 'Std Error' },
      { key: 'dfden', label: 'DFDen', digits: 2 }, { key: 't', label: 't Ratio' }, { key: 'p', label: 'Prob>|t|', fmt: 'p' }, { key: 'lower', label: `Lower ${p}%` }, { key: 'upper', label: `Upper ${p}%` },
      ...(r.ratio ? [{ key: 'ratio', label: r.ratio }, { key: 'ratio_lower', label: `${r.ratio} Lower` }, { key: 'ratio_upper', label: `${r.ratio} Upper` }] : [])];
    ob.add(ctx.rt({ columns: cols, rows: r.rows.map((x, i) => ({ ...x, ...Object.fromEntries(r.coefs[i].map((w, j) => [`w${j}`, w])) })) }, { sortable: false, key: 'contrast' }));
    if (r.joint) ob.add(ctx.rt({ columns: [{ key: 'numdf', label: 'Num DF', fmt: 'int' }, { key: 'dendf', label: 'Den DF', digits: 2 }, { key: 'f', label: 'F Ratio' }, { key: 'p', label: 'Prob > F', fmt: 'p' }], rows: [r.joint] },
      { caption: 'Joint test of the contrasts', sortable: false, key: 'contrastjoint' }));
    ob.add(ctx.code(r.code));
  }

  async function slicesReport(S, parentOb, label) {
    const { ctx, sc } = S;
    const r = await ctx.call('mixed.slices', { ...S.payload, effect: label, alpha: ctx.alpha });
    const ob = ctx.outline(`Test Slices: ${label}`, { parent: parentOb, key: `slices:${label}`, info: 'p:fitmodel:mixed:lsmeans', menu: () => [{ label: 'Remove', action: () => ctx.set(`slices:${label}`, false, sc) }] });
    if (r.error) { ob.add(ctx.warn(r.error)); return; }
    ob.add(ctx.rt({ columns: [{ key: 'slice', label: 'Slice', fmt: 'text' }, { key: 'dfnum', label: 'DFNum', fmt: 'int' }, { key: 'dfden', label: 'DFDen', digits: 2 }, { key: 'f', label: 'F Ratio' },
      { key: 'p', label: 'Prob > F', fmt: 'p' }], rows: r.rows }, { key: 'slicestab' }));
    for (const s of r.rows) {
      ctx.outline(`Test Detail: ${s.slice}`, { parent: ob, key: `slicedet:${label}:${s.slice}`, closed: true }).add(ctx.rt({ columns: [{ key: 'contrast', label: 'Contrast', fmt: 'text' },
        { key: 'estimate', label: 'Estimate' }, { key: 'se', label: 'Std Error' }, { key: 'dfden', label: 'DFDen', digits: 2 }, { key: 't', label: 't Ratio' }, { key: 'p', label: 'Prob>|t|', fmt: 'p' }], rows: s.detail },
      { sortable: false, key: `slicedet:${s.slice}` }));
    }
    ob.add(ctx.note('Each slice tests the least squares means of the other factors\' combinations at one level of a factor (the simple effects), with the mixed covariance; the slices are not adjusted for multiple comparisons.'), ctx.code(r.code));
  }

  /* ---- Multiple Comparisons (the Mixed Model personality's dialog) ------------------------------------------------ */
  async function multipleComparisonsDialog(S) {
    const { ctx, res, sc } = S;
    if (!res.lsm_effects.length) { SM.ui.toast('Multiple Comparisons need a fixed effect of categorical factors'); return; }
    const v = await SM.ui.form({
      title: 'Multiple Comparisons', lead: 'Least squares means of a fixed effect with the mixed model\'s covariance, and their comparisons.', info: 'p:fitmodel:mixed:lsmeans',
      fields: [
        { key: 'effect', label: 'Choose an Effect', type: 'select', choices: res.lsm_effects, value: res.lsm_effects[0], help: 'An effect of the categorical fixed effects: a main effect or a crossing.' },
        { key: 'method', label: 'Comparisons', type: 'select', choices: [['none', 'None'], ['student', 'All Pairwise Comparisons - Student\'s t'], ['tukey', 'All Pairwise Comparisons - Tukey HSD']], value: 'tukey',
          help: 'Student\'s t: each difference on its own at α; Tukey HSD: adjusted for all the pairs (the studentized range), each difference with its own denominator df.' },
        { key: 'plot', label: 'Show Least Squares Means Plot', type: 'check', value: true, help: 'The means with their intervals; for a crossing, an interaction plot (the overlay chosen in the plot\'s red triangle).' },
        { key: 'slices', label: 'Test Slices (a crossing)', type: 'check', value: false, help: 'The simple effects: at each level of each factor, the test that the other factors\' cells are equal.' },
      ] });
    if (!v) return;
    ctx.set('mc', [...(S.o('mc', []) || []), { effect: v.effect, method: v.method, plot: !!v.plot, slices: !!v.slices }], sc);
  }

  async function multipleComparison(S, mc, i) {
    const { ctx, sc } = S;
    const all = S.o('mc', []) || [];
    const ob = ctx.outline(`Multiple Comparisons for ${mc.effect}`, { parent: S.parent, key: `mc:${i}`, info: 'p:fitmodel:mixed:lsmeans', menu: () => [
      { label: 'LSMeans Contrast…', action: () => contrastDialog(S, mc.effect, i) },
      { label: 'Remove', action: () => ctx.set('mc', all.filter((_, j) => j !== i), sc) }] });
    await lsmeansBlock(S, ob, mc.effect, { plot: mc.plot && S.o(`mc:${i}:plot`, true) !== false, student: mc.method === 'student', tukey: mc.method === 'tukey',
      slices: mc.slices && mc.effect.includes('*'), contrasts: S.o(`mc:${i}:contrast`, []) || [] }, i);
  }

  /* ---- Indicator Parameterization Estimates: the fixed effects in SAS GLM's 0/1 coding --------------------------- */
  async function indicatorOutline(S) {
    const { ctx, parent, sc } = S;
    const r = await ctx.call('mixed.indicator', { ...S.payload, alpha: ctx.alpha });
    const p = pct(ctx);
    const ob = ctx.outline('Indicator Parameterization Estimates', { parent, key: 'indicator', info: 'p:fitmodel:mixed', menu: () => [{ label: 'Remove', action: () => ctx.set('indicator', false, sc) }] });
    if (r.error) { ob.add(ctx.warn(r.error)); return; }
    ob.add(ctx.rt({ columns: [{ key: 'term', label: 'Term', fmt: 'text' }, { key: 'estimate', label: 'Estimate' }, { key: 'se', label: 'Std Error' }, { key: 'dfden', label: 'DFDen', digits: 2 },
      { key: 't', label: 't Ratio' }, { key: 'p', label: 'Prob>|t|', fmt: 'p' }, { key: 'lower', label: `${p}% Lower`, hidden: true }, { key: 'upper', label: `${p}% Upper`, hidden: true }], rows: r.rows }, { key: 'indicator' }),
    ctx.kv([['-2 Residual Log Likelihood', r.m2rll]]),
    ctx.note('The same fit with each nominal effect coded 0/1, its last level the reference (SAS\'s GLM parameterization, as PROC MIXED reports it): other parameters, so other standard errors and t ratios than the effect coding\'s.'), ctx.code(r.code));
  }

  /* ---- Iterations, Skeleton ANOVA, Compare Structures, profile-likelihood intervals ---------------------------- */
  function iterations(S) {
    const { ctx, res, parent, sc } = S;
    const names = res.param_names;
    const cols = [{ key: 'iter', label: 'Iter', fmt: 'int' }, { key: 'm2ll', label: '-2LogLike' }, ...names.map((n, j) => ({ key: `p${j}`, label: n }))];
    ctx.outline('Iterations', { parent, key: 'iters', closed: true, menu: () => [{ label: 'Remove', action: () => ctx.set('iters', false, sc) }] })
      .add(ctx.rt({ columns: cols, rows: res.history.map((h) => ({ iter: h.iter, m2ll: h.m2ll, ...Object.fromEntries(h.params.map((v, j) => [`p${j}`, v])) })) }, { sortable: false, key: 'iters' }),
        ctx.note(`Fisher scoring, then Newton steps near the maximum, each step halved until -2 log L falls (and the covariance of the rows stays positive definite); converged: ${res.fit.converged ? 'yes' : 'no'}.`));
  }

  async function skeleton(S) {
    const { ctx, parent, sc } = S;
    const r = await ctx.call('mixed.skeleton', { ...S.payload });
    const ob = ctx.outline('Skeleton ANOVA', { parent, key: 'skeleton', info: 'p:fitmodel:mixed:skeleton', menu: () => [{ label: 'Remove', action: () => ctx.set('skeleton', false, sc) }] });
    if (r.error) { ob.add(ctx.warn(r.error)); return; }
    ob.add(ctx.rt({ columns: [{ key: 'source', label: 'Source', fmt: 'text' }, { key: 'kind', label: 'Kind', fmt: 'text' }, { key: 'df', label: 'DF', fmt: 'int' }], rows: r.rows }, { sortable: false, key: 'skeleton' }));
    for (const w of r.warnings) ob.add(ctx.warn(w));
    ob.add(ctx.note('The degrees of freedom of each source, taken in the model\'s order (the fixed effects, then the random ones): how much each adds to the rank of the design; what is left is the residual\'s.'), ctx.code(r.code));
  }

  async function compareStructures(S) {
    const { ctx, parent, sc } = S;
    const progress = el('p', { class: 'sm-ob-note', role: 'status', text: 'Fitting the structures…' });
    parent.add(progress);
    const off = SM.engine.on('progress', (m) => { if (m && m.what === 'structures') progress.textContent = `Fitting the structures: ${m.done} of ${m.total}…`; });
    let r;
    try { r = await ctx.call('mixed.structures', { ...S.payload }); } finally { off(); progress.remove(); }
    const ob = ctx.outline('Compare Structures', { parent, key: 'structures', info: 'p:fitmodel:mixed:repeated', menu: () => [{ label: 'Remove', action: () => ctx.set('structures', false, sc) }] });
    if (r.error) { ob.add(ctx.warn(r.error)); return; }
    const rows = r.rows.map((x) => ({ ...x, mark: [x.current ? 'this report' : '', x.best_aicc ? 'best AICc' : '', x.best_bic ? 'best BIC' : ''].filter(Boolean).join(', ') }));
    ob.add(ctx.rt({ columns: [{ key: 'structure', label: 'Structure', fmt: 'text' }, { key: 'params', label: 'Parameters', fmt: 'int' }, { key: 'm2rll', label: '-2 Residual Log Likelihood' },
      { key: 'm2ll', label: '-2 Log Likelihood' }, { key: 'aicc', label: 'AICc' }, { key: 'bic', label: 'BIC' }, { key: 'converged', label: 'Converged', fmt: 'text' }, { key: 'mark', label: '', fmt: 'text' },
      { key: 'error', label: 'Not fitted', fmt: 'text', hidden: !r.rows.some((x) => x.error) }], rows }, { key: 'structures' }));
    ob.add(ctx.note('The model fitted again with each repeated structure its Repeated and Subject columns allow, the fixed and random effects as in the report; smaller AICc and BIC are better. Beyond JMP, which fits one structure per launch.'), ctx.code(r.code));
  }

  async function profileIntervals(S) {
    const { ctx, parent, sc } = S;
    const r = await ctx.call('mixed.profile_ci', { ...S.payload, alpha: ctx.alpha });
    const p = pct(ctx);
    const ob = ctx.outline('Profile Likelihood Intervals', { parent, key: 'profci', info: 'p:fitmodel:mixed', menu: () => [{ label: 'Remove', action: () => ctx.set('profci', false, sc) }] });
    if (r.error) { ob.add(ctx.warn(r.error)); return; }
    ob.add(ctx.rt({ columns: [{ key: 'param', label: 'Covariance Parameter', fmt: 'text' }, { key: 'estimate', label: 'Estimate' }, { key: 'lower', label: `${p}% Lower` }, { key: 'upper', label: `${p}% Upper` },
      { key: 'wald_lower', label: `Wald ${p}% Lower` }, { key: 'wald_upper', label: `Wald ${p}% Upper` }], rows: r.rows }, { sortable: false, key: 'profci' }),
    ctx.note(`Each limit is where −2 Residual Log Likelihood, the other covariance parameters at their best for it, rises by the χ²(1) ${p}% quantile above its minimum; beside it the Wald interval. Beyond JMP.`), ctx.code(r.code));
  }

  /* ---- the Conditional Profiler: the prediction with the random effects' levels as factors --------------------- */
  async function conditionalProfiler(S) {
    const { ctx, parent, sc, payload } = S;
    return SM.profiler.render(ctx, parent, {
      sources: [{ fn: 'mixedcond.profile', payload }], scope: sc, title: 'Conditional Profiler', key: 'condprof', option: 'condprof', info: 'p:fitmodel:profiler',
      stateKey: `condprof:${ctx.byLabel || ''}`,
      note: 'The conditional prediction: the fixed effects and the BLUP of each random effect at the level chosen (a level the fit did not see predicts with its random effect at zero). No interval: the BLUPs are predictions, not parameters.',
    });
  }

  /* ---- Simulate: power and interval coverage from the fitted model -------------------------------------------- */
  async function simulateDialog(S) {
    const { ctx, res, sc } = S;
    if (S.kind === 'glmm') { SM.ui.toast('Simulate is for the linear mixed models here'); return; }
    const prev = S.o('simulate', null);
    const fields = [
      { key: 'n', label: 'Number of Samples', type: 'number', value: prev ? prev.n : 200, help: 'How many data sets to simulate and refit (JMP\'s Number of Samples). The power estimates\' intervals narrow with more.' },
      { key: 'seed', label: 'Random Seed', type: 'number', value: prev ? prev.seed : 1 + Math.floor(Math.random() * 99999), help: 'The seed of the draws: the same seed gives the same samples.' },
      ...res.estimates.map((e, i) => ({ key: `b${i}`, label: e.term, type: 'number', value: prev && prev.beta ? prev.beta[i] : +e.estimate.toPrecision(6), helpLabel: 'A fixed effect',
        help: 'The true value of the fixed-effect parameter in the simulation (the report\'s coding: the effect of a level, the last level the negative sum of the others). Zero for all of an effect\'s parameters checks the test\'s size.' })),
      ...res.param_names.map((nm, i) => ({ key: `t${i}`, label: nm, type: 'number', value: prev && prev.theta ? prev.theta[i] : +res.history[res.history.length - 1].params[i].toPrecision(6), helpLabel: 'A covariance parameter',
        help: 'The true value of the covariance parameter (a variance, a covariance or a correlation, as the reports name them).' })),
    ];
    const v = await SM.ui.form({ title: 'Simulate', lead: 'Responses drawn from the model with these parameters (the fit\'s to start with), each sample refitted as this report fits it: the rejection rates of the tests (power, or the size when the effects are zero) and the coverage of the intervals.', info: 'p:fitmodel:mixed:simulate', fields,
      validate: (x) => (x.n >= 2 && x.n <= 100000 ? null : 'the number of samples: 2 to 100000') });
    if (!v) return;
    const sim = { n: Math.round(v.n), seed: Math.round(v.seed), beta: res.estimates.map((_, i) => v[`b${i}`] ?? 0), theta: res.param_names.map((_, i) => v[`t${i}`] ?? 0) };
    const out = await runSimulation(S, sim);
    if (out) ctx.set('simulate', { ...sim, ...out }, sc);
  }

  /* The samples, 25 to a call, with a progress dialog and Stop (between calls); the Simulate report is made from
     what comes back (kept in the report's options, so Redo, the theme and a project show it without drawing again). */
  async function runSimulation(S, sim) {
    const { ctx, payload } = S;
    const CH = 25;
    const chunks = Math.ceil(sim.n / CH);
    const bar = el('progress', { max: String(sim.n), value: '0' });
    const text = el('p', { class: 'sm-dialog-lead', text: `Sample 0 of ${sim.n}` });
    let stop = false;
    const dlg = SM.ui.dialog({ title: 'Simulate', narrow: true, info: 'p:fitmodel:mixed:simulate', body: el('div', { class: 'sm-mx-progress' }, text, bar),
      buttons: [{ label: 'Stop', action: () => { stop = true; return false; } }], onClose: () => { stop = true; } });
    const acc = { tests: {}, terms: {}, cover: {}, estimates: {}, covparms: {}, cp_cover: {}, failed: 0, true: null };
    const join = (a, b) => { for (const [k, x] of Object.entries(b || {})) a[k] = (a[k] || []).concat(x); };
    let done = 0;
    const t0 = performance.now();
    try {
      for (let c = 0; c < chunks && !stop; c++) {
        const n = Math.min(CH, sim.n - c * CH);
        const r = await ctx.call('mixed.simulate', { ...payload, beta: sim.beta, theta: sim.theta, n, seed: sim.seed, start: c * CH, alpha: ctx.alpha });
        if (r.error) { dlg.close(); SM.ui.toast(r.error, { error: true }); return null; }
        for (const k of ['tests', 'terms', 'cover', 'estimates', 'covparms', 'cp_cover']) join(acc[k], r[k]);
        acc.failed += r.failed;
        acc.true = r.true;
        done += n;
        bar.value = done;
        const rate = (performance.now() - t0) / done;
        text.textContent = `Sample ${done} of ${sim.n}${done < sim.n ? `, about ${Math.max(1, Math.round((sim.n - done) * rate / 1000))} s left` : ''}${acc.failed ? ` (${acc.failed} did not fit)` : ''}`;
      }
      if (!done) { dlg.close(); return null; }
      const pw = await ctx.call('mixed.power', { results: acc, levels: LEVELS, alpha: ctx.alpha });
      dlg.close();
      return { done, stopped: stop && done < sim.n, failed: acc.failed, power: pw.power, coverage: pw.coverage };
    } catch (e) {
      dlg.close();
      SM.ui.toast(e.message || String(e), { error: true });
      return null;
    }
  }

  async function simulateReport(S, sim) {
    const { ctx, parent, sc, payload } = S;
    const ob = ctx.outline('Simulate', { parent, key: 'simulate', info: 'p:fitmodel:mixed:simulate', menu: () => [{ label: 'Simulate Again…', action: () => simulateDialog(S) }, { label: 'Remove', action: () => ctx.set('simulate', null, sc) }] });
    if (!sim.power) { ob.add(ctx.note('Simulate… in the red triangle draws the samples.')); return; }
    ob.add(ctx.kv([['Samples', sim.done, 'int'], ['Random Seed', sim.seed, 'int'], ...(sim.failed ? [['Samples that did not fit', sim.failed, 'int']] : []), ...(sim.stopped ? [['Stopped', 'yes', 'text']] : [])]));
    const tests = sim.power.filter((r) => r.report === 'Fixed Effects Tests');
    const terms = sim.power.filter((r) => r.report !== 'Fixed Effects Tests');
    const pwCols = (first) => [{ key: 'term', label: first, fmt: 'text' }, { key: 'alpha', label: 'Alpha', digits: 2 }, { key: 'rate', label: 'Rejection Rate' }, { key: 'lower', label: 'Lower 95%' }, { key: 'upper', label: 'Upper 95%' }];
    ctx.outline('Simulated Power', { parent: ob, key: 'simpower' }).add(
      ctx.rt({ columns: pwCols('Source'), rows: tests }, { caption: 'Fixed Effects Tests', sortable: false, key: 'simpower' }),
      ctx.rt({ columns: pwCols('Term'), rows: terms }, { caption: 'Fixed Effects Parameter Estimates (Prob>|t|)', sortable: false, key: 'simpowerterms' }),
      ctx.note('The share of samples whose p-value is below each α, with its Wilson 95% interval. With every true effect of a test at zero the rate is the test\'s size.'));
    ctx.outline('Interval Coverage', { parent: ob, key: 'simcover' }).add(ctx.rt({ columns: [{ key: 'param', label: 'Parameter', fmt: 'text' }, { key: 'kind', label: 'Kind', fmt: 'text' }, { key: 'true', label: 'True Value' },
      { key: 'mean', label: 'Mean Estimate' }, { key: 'sd', label: 'Std Dev' }, { key: 'coverage', label: `Coverage of the ${pct(ctx)}% Intervals` }, { key: 'lower', label: 'Lower 95%' }, { key: 'upper', label: 'Upper 95%' }], rows: sim.coverage },
    { sortable: false, key: 'simcover' }), ctx.note('How often each interval of the report (the fixed effects\' Kenward-Roger or Satterthwaite intervals, the covariance parameters\' Wald or Satterthwaite ones) holds the true value.'));
    const code = await ctx.call('mixed.simulate_code', { ...payload, beta: sim.beta, theta: sim.theta, n: sim.done, seed: sim.seed, alpha: ctx.alpha });
    ob.add(ctx.code(code.code));
  }

  /* ---- Compare Models: the likelihood ratio with another open mixed report -----------------------------------------
     Every mixed report puts its fit statistics here (per report, By group and response); a closed report's
     entries are left out (its element is no longer in the page). */
  const REGISTRY = new Map();

  function register(S) {
    const { ctx, res, g } = S;
    REGISTRY.set(`${ctx.report.id}|${ctx.byLabel || ''}|${g.name}`, { report: ctx.report, title: `${ctx.report.title}${ctx.byLabel ? ` ${ctx.byLabel}` : ''}${g.name ? ` (${g.name})` : ''}`,
      y: g.name, m2rll: res.fit.m2rll, m2ll: res.fit.m2ll, q: res.fit.q, p: res.fit.p, n: res.fit.sumfreq, fixed: fixedSignature(S), kind: S.kind });
  }

  function openMixedReports(S) {
    const out = [];
    const me = `${S.ctx.report.id}|${S.ctx.byLabel || ''}|${S.g.name}`;
    for (const [k, v] of REGISTRY) {
      if (!v.report.el || !v.report.el.parentNode) { REGISTRY.delete(k); continue; }
      if (k === me || v.y !== S.g.name || v.n !== S.res.fit.sumfreq) continue;
      out.push(v);
    }
    return out;
  }

  async function compareModelsDialog(S) {
    const { ctx, sc } = S;
    const others = openMixedReports(S);
    if (!others.length) { SM.ui.toast('Open another mixed model report (the same response) to compare with'); return; }
    const v = await SM.ui.form({ title: 'Compare Models', lead: 'A likelihood ratio test of this model against another open mixed model report: nested models of the same rows; the same fixed effects for the residual likelihood.', info: 'p:fitmodel:mixed',
      fields: [{ key: 'other', label: 'The other report', type: 'select', choices: others.map((o, i) => [String(i), o.title]), value: '0', help: 'Another open Fit Model report of a mixed model.' },
        { key: 'boundary', label: 'A variance tested at zero (the 50:50 mixture)', type: 'check', value: true, help: 'When the smaller model sets one variance component to zero, the likelihood ratio\'s null distribution is the 50:50 mixture of χ²(0) and χ²(1) (Self and Liang): half the χ²(1) p-value.' }] });
    if (!v) return;
    const o = others[+v.other];
    ctx.set('comparemodels', { title: o.title, m2rll: o.m2rll, m2ll: o.m2ll, q: o.q, p: o.p, fixed: o.fixed, n: o.n, boundary: !!v.boundary }, sc);
  }

  function compareModels(S, other) {
    const { ctx, parent, res, sc } = S;
    const f = res.fit;
    const sameFixed = other.fixed === fixedSignature(S);
    const useR = sameFixed;
    const a = useR ? f.m2rll : f.m2ll, b = useR ? other.m2rll : other.m2ll;
    const ka = f.q + (useR ? 0 : f.p), kb = other.q + (useR ? 0 : other.p);
    const big = ka >= kb ? { m2: a, k: ka } : { m2: b, k: kb };
    const small = ka >= kb ? { m2: b, k: kb } : { m2: a, k: ka };
    const chi = Math.max(0, small.m2 - big.m2);
    const df = big.k - small.k;
    const ob = ctx.outline('Compare Models', { parent, key: 'comparemodels', info: 'p:fitmodel:mixed', menu: () => [{ label: 'Remove', action: () => ctx.set('comparemodels', null, sc) }] });
    if (df <= 0) { ob.add(ctx.warn('The two models have as many parameters: a likelihood ratio needs one nested in the other.')); return; }
    ob.add(ctx.kv([['This report', `${res.fit.method}, ${ka} parameters`, 'text'], ['The other', `${other.title}, ${kb} parameters`, 'text'],
      [useR ? 'Likelihood' : 'Likelihood (the fixed effects differ)', useR ? '-2 Residual Log Likelihood' : '-2 Log Likelihood', 'text'], ['ChiSquare', chi], ['DF', df, 'int']]));
    compareModelsP(S, ob, chi, df, other.boundary && df === 1);
  }

  async function compareModelsP(S, ob, chi, df, mix) {
    const { ctx } = S;
    const r = await ctx.call('mixed.lrt', { chisq: chi, df, mixture: mix });
    ob.add(ctx.kv([['Prob > ChiSq', r.p, 'p'], ...(mix ? [['Prob > ChiSq, 50:50 mixture of χ²(0) and χ²(1)', r.p_mix, 'p']] : [])]),
      ctx.note(mix ? 'For a variance component tested at zero, the mixture p-value is the one to read (half the χ²(1) one).' : 'The difference of the two models\' −2 log likelihoods, on as many df as they differ in parameters.'),
      ctx.code(r.code));
  }

  const fixedSignature = (S) => JSON.stringify((S.M.base.effects || []).filter((e) => !e.random).map((e) => [e.names, e.nest]));

  /* ---- the red triangle --------------------------------------------------------------------------------------- */
  function menuOf(S) {
    const { ctx, sc, kind, res } = S;
    const c = (label, key, d) => ctx.check(label, key, sc, d);
    const iso = S.iso;
    const save = saveMenu(S);
    const common = [
      { label: 'Compare Models…', action: () => compareModelsDialog(S) },
      c('Profile Likelihood Intervals', 'profci', false),
      { label: 'Simulate…', disabled: kind === 'glmm', action: () => simulateDialog(S) },
    ];
    if (kind === 'sls') {
      return [
        { label: 'Regression Reports', submenu: () => [c('Summary of Fit', 'fitstats', true), c('Parameter Estimates', 'pe', true), c('Show All Confidence Intervals', 'showCI', false), c('AICc', 'aicc', false),
          c('Fixed Effect Tests', 'fixedtests', true)] },
        { label: 'Estimates', submenu: () => [{ label: 'Multiple Comparisons…', action: () => multipleComparisonsDialog(S) }, c('Random Effect Predictions', 'blups', false),
          c('Indicator Parameterization Estimates', 'indicator', false),
          c('Covariance of Fixed Effects', 'covfe', false), c('Correlation of Fixed Effects', 'corfe', false), c('Covariance of Variance Components', 'covcp', false)] },
        c('Effect Details', 'effdet', true),
        { label: 'Factor Profiling', submenu: () => [c('Profiler', 'profiler', false), c('Contour Profiler', 'contour', false), c('Interaction Plots', 'interaction', false), c('Conditional Profiler', 'condprof', false)] },
        { label: 'Row Diagnostics', submenu: () => [c('Plot Actual by Predicted', 'actMarg', true), c('Plot Residual by Predicted', 'resMarg', true), c('Plot Actual by Conditional Predicted', 'actCond', false),
          c('Plot Conditional Residual by Predicted', 'resCond', false)] },
        c('Iterations', 'iters', false),
        c('Skeleton ANOVA', 'skeleton', false),
        ...common,
        { label: 'Save Columns', submenu: () => save },
        { separator: true },
        { label: 'Model Dialog', action: () => ctx.report.relaunch() },
      ];
    }
    return [
      { label: 'Model Reports', submenu: () => [c('Fit Statistics', 'fitstats', true), ...(S.random ? [c('Random Effects Covariance Parameter Estimates', 'vcomp', true)] : []),
        c('Fixed Effects Parameter Estimates', 'fixedest', true), ...(S.structure !== 'residual' ? [c('Repeated Effects Covariance Parameter Estimates', 'repcov', true)] : []),
        ...(S.random ? [c('Random Coefficients', 'rcoef', res.coefs.some((x) => x.coefs.length > 1)), c('Random Effects Predictions', 'blups', false)] : []),
        c('Fixed Effects Tests', 'fixedtests', true), c('Indicator Parameterization Estimates', 'indicator', false), c('Show All Confidence Intervals', 'showCI', true),
        c('Iterations', 'iters', false), c('Skeleton ANOVA', 'skeleton', false)] },
      { label: 'Multiple Comparisons…', action: () => multipleComparisonsDialog(S) },
      { label: 'Marginal Model Inference', submenu: () => [c('Actual by Predicted Plot', 'actMarg', true), c('Residual Plots', 'resMarg', false), c('Profiler', 'profiler', false),
        c('Contour Profiler', 'contour', false), c('Interaction Plots', 'interaction', false), c('Variogram', 'variogram', iso)] },
      ...(S.random ? [{ label: 'Conditional Model Inference', submenu: () => [c('Actual by Conditional Predicted Plot', 'actCond', true), c('Conditional Residual Plots', 'resCond', false),
        c('Conditional Profiler', 'condprof', false)] }] : []),
      { label: 'Covariance and Correlation Matrices', submenu: () => [c('Covariance of Fixed Effects', 'covfe', false), c('Covariance of Covariance Parameters', 'covcp', false),
        c('Correlation of Fixed Effects', 'corfe', false), ...(S.structure === 'un' ? [c('Repeated Measures Covariance Diagnostics', 'rmdiag', false)] : [])] },
      ...(kind === 'mixed' ? [c('Compare Structures', 'structures', false)] : []),
      ...common,
      { label: 'Save Columns', submenu: () => save },
      { separator: true },
      { label: 'Model Dialog', action: () => ctx.report.relaunch() },
    ];
  }

  /* ---- Save Columns: every row of the By group whose predictors are present (mixed.save) ------------------ */
  function saveMenu(S) {
    const { ctx, y, kind, g } = S;
    const nm = g.name;
    const run = (fn) => async () => {
      try {
        const r = await ctx.call('mixed.save', { ...S.payload, where: ctx.where || [], alpha: ctx.alpha });
        if (r.error) { SM.ui.toast(r.error, { error: true }); return; }
        fn(r);
      } catch (e) { SM.ui.toast(e.message || String(e), { error: true }); }
    };
    const col = (key, name) => (r) => { if (r.columns[key]) ctx.saveColumn(name, { rows: r.rows, values: r.columns[key] }); };
    const pair = (a, b, na, nb) => (r) => { col(a, na)(r); col(b, nb)(r); };
    const formula = (i) => (r) => { const f = r.formulas[i]; try { ctx.saveFormula(f.name, f.expr, { notes: `${f.name}: from ${ctx.report.title}` }); } catch (e) { SM.ui.toast(`${f.name} could not be saved as a formula: ${e.message || e}`, { error: true }); } };
    const sim = (r) => {
      try { ctx.saveFormula(r.simulation.name, r.simulation.expr, { notes: `Draws from the fitted model of ${ctx.report.title}; each recomputation draws again from the column's seed.${r.simulation.notes.length ? ` ${r.simulation.notes.join(' ')}` : ''}` }); } catch (e) { SM.ui.toast(e.message || String(e), { error: true }); }
      for (const n of r.simulation.notes) SM.ui.toast(n);
    };
    const p = pct(ctx);
    const items = [
      { label: kind === 'sls' ? 'Predicted Values' : 'Predictions', action: run(col('predicted', kind === 'sls' ? `Predicted ${nm}` : `Predicted ${nm}`)) },
      { label: 'Prediction Formula', action: run(formula(0)) },
      ...(kind !== 'glmm' ? [{ label: 'Standard Error of Predicted', action: run(col('se_pred', `StdErr Pred ${nm}`)) }] : []),
      { label: 'Mean Confidence Interval', action: run(pair('lower_mean', 'upper_mean', `Lower ${p}% Mean ${nm}`, `Upper ${p}% Mean ${nm}`)) },
      ...(kind !== 'glmm' && S.structure === 'residual' && S.random ? [{ label: 'Indiv Confidence Interval', action: run(pair('lower_indiv', 'upper_indiv', `Lower ${p}% Indiv ${nm}`, `Upper ${p}% Indiv ${nm}`)) }] : []),
      { label: 'Residuals', action: run(col('residual', `Residual ${nm}`)) },
      ...(S.random ? [
        { separator: true },
        { label: kind === 'sls' ? 'Conditional Pred Values' : 'Conditional Predictions', action: run(col('cond', kind === 'sls' ? `Cond Pred ${nm}` : `Conditional Predicted ${nm}`)) },
        { label: kind === 'sls' ? 'Conditional Pred Formula' : 'Conditional Prediction Formula', action: run(formula(1)) },
        ...(kind !== 'glmm' ? [{ label: 'Standard Error of Conditional Predicted', action: run(col('se_cond', `StdErr Cond Pred ${nm}`)) }] : []),
        { label: 'Conditional Mean CI', action: run(pair('lower_cond', 'upper_cond', `Lower ${p}% Cond Mean ${nm}`, `Upper ${p}% Cond Mean ${nm}`)) },
        ...(kind === 'sls' && S.structure === 'residual' ? [{ label: 'Conditional Indiv CI', action: run(pair('lower_cond_indiv', 'upper_cond_indiv', `Lower ${p}% Cond Indiv ${nm}`, `Upper ${p}% Cond Indiv ${nm}`)) }] : []),
        { label: 'Conditional Residuals', action: run(col('cond_residual', `Cond Residual ${nm}`)) },
      ] : []),
      ...(kind !== 'glmm' ? [{ separator: true }, { label: 'Save Simulation Formula', action: run(sim) }] : []),
    ];
    void y;
    return items;
  }

  /* ---- the (i) topics -------------------------------------------------------------------------------------------- */
  const MORE = { label: 'Fit Model', id: 'help-p-fitmodel' };
  SM.info.add({
    'p:fitmodel:mixed': {
      kicker: 'Fit Model', title: 'Mixed Model',
      lead: 'Fixed effects, random effects and a covariance structure, fitted by REML (restricted maximum likelihood) as JMP fits them: the Mixed Model personality, Standard Least Squares with random effects, and the Generalized Linear Model with random effects (a generalized linear mixed model). The estimation is this page\'s own (numpy and scipy): statsmodels\' MixedLM bounds the variance components at zero and has none of JMP\'s repeated structures or Kenward-Roger\'s adjustment.',
      sections: [
        { heading: 'Covariance parameters', choices: [['Var Component, Estimate', 'the variance of a random effect (Var Ratio: to the residual variance; Pct of Total: its share of the total, which sums the positive components only)'],
          ['Unbounded Variance Components', 'on by default, as in JMP: a variance component may be below zero as long as the covariance of the rows stays positive definite; its interval is then Wald\'s, with a Wald p-value. Off: held at zero or above, Satterthwaite intervals, and a note for a component on the boundary'],
          ['Std Error', 'from the inverse observed information of the REML log-likelihood (JMP\'s)'], ['Residual', 'always a Satterthwaite interval (bounded at zero)']] },
        { heading: 'Fixed effects', choices: [['DFDen', 'Kenward and Roger\'s denominator degrees of freedom (JMP\'s default, the first-order approximation), or Satterthwaite\'s (the launch\'s DF)'],
          ['Std Error', 'Kenward-Roger: from the adjusted covariance of the estimates (Kackar-Harville), which allows for the estimated covariance parameters; Satterthwaite: the model-based (X\'V⁻¹X)⁻¹'],
          ['F Ratio', 'Kenward-Roger\'s scaled Wald F of the effect\'s parameters']] },
        { heading: 'Fit Statistics', choices: [['-2 Residual Log Likelihood', 'the REML objective; compare models with the same fixed effects with it'], ['-2 Log Likelihood', 'the full likelihood at the REML estimates'],
          ['AICc, BIC', 'JMP\'s: from −2 Log Likelihood, k the fixed and covariance parameters, n the observations; smaller is better']] },
        { heading: 'Predictions', choices: [['Marginal', 'the fixed effects alone (Actual by Predicted, Pred Formula)'], ['Conditional', 'with the random effects\' BLUPs (Actual by Conditional Predicted, Cond Pred Formula)']] },
        { heading: 'A long fit', text: 'A fit that runs longer than a second (a spatial structure over many rows: its covariance is one dense matrix, factored at every step) shows its progress in the report\'s bar: the REML iteration and its −2 Residual Log Likelihood, then the evaluations of the covariance parameters\' information, and a Stop button. A calculation in Python cannot be interrupted, so Stop restarts the Python engine, as the notebook\'s Stop does: whatever else it runs stops too, and the notebook\'s variables are lost. The report says the fit was stopped; Redo runs it again.' },
        { heading: 'A spatial range at infinity', text: 'When the semivariogram rises in a straight line over every distance in the data, a spatial structure\'s maximum is at an infinite range and sill (only their ratio is determined): the report says so and suggests a trend in the coordinates (as fixed effects) or another type of structure (Compare Structures).' },
        { heading: 'Differences from JMP', text: 'The degrees of freedom may be Satterthwaite\'s instead of Kenward-Roger\'s (JMP has Kenward-Roger only). Compare Structures, Profile Likelihood Intervals and the Skeleton ANOVA are beyond JMP. The generalized linear mixed model is fitted by residual pseudo-likelihood (RSPL), binomial or Poisson, as the add-in in Hummel et al.\'s book; JMP Pro 17\'s personality has more distributions. EMS (the expected mean squares method) is not offered: REML gives its estimates in balanced designs. Summary of Fit\'s RSquare Adj uses n − rank(X) error degrees of freedom.' },
      ],
      more: MORE,
    },
    'p:fitmodel:mixed:repeated': {
      kicker: 'Mixed Model', title: 'Repeated Structure',
      lead: 'The covariance of the errors within a subject (R), JMP Pro\'s Repeated Structure: with or without random effects. The Repeated column orders the measurements (the time) or places them (coordinates); the Subject column says which rows belong together; different subjects are independent.',
      sections: [{ choices: [['Residual', 'independent errors, one variance (the default)'], ['Unequal Variances', 'a variance for each level of the Repeated column, no correlation'],
        ['Unstructured', 'a variance for each level and a covariance for each pair: J(J+1)/2 parameters (as MANOVA)'], ['AR(1)', 'one variance, a correlation ρ to the power of the time apart (a continuous time: unequal spacing works)'],
        ['Compound Symmetry', 'one variance and one correlation for every pair (a random subject intercept, but the correlation may be negative)'], ['Toeplitz', 'a correlation for each lag: J parameters'],
        ['Antedependent', 'a correlation between each pair of adjacent times; farther apart, their product'], ['Unequal Variances forms', 'the same correlations, a variance for each level'],
        ['Spatial', 'the correlation a function of the distance (Power, Exponential, Gaussian, Spherical); with Nugget, a jump at zero distance'],
        ['Compare Structures', 'the model fitted with every structure its columns allow, by AICc and BIC (beyond JMP)'],
        ['Repeated Measures Covariance Diagnostics', 'for Unstructured: the covariance and correlation matrices and a heat map of the correlations, to choose a simpler structure']] }],
      more: MORE,
    },
    'p:fitmodel:mixed:blups': {
      kicker: 'Mixed Model', title: 'Random Effects Predictions',
      lead: 'The BLUPs, best linear unbiased predictions of the random effects: G Z\'V⁻¹(y − Xb), each level\'s departure from the fixed effects, shrunk toward zero.',
      sections: [{ choices: [['Std Error', 'the prediction error: the square root of the variance of the prediction minus the random effect (JMP\'s, not Kackar-Harville corrected)'], ['DFDen', 'Satterthwaite\'s degrees of freedom of that variance'],
        ['t Ratio, Prob>|t|', 'the test that the level\'s effect is zero'], ['Random Coefficients', 'a row per level, a column per coefficient (intercept, slopes): the level\'s own line is the fixed line plus these; with the covariance of the coefficients for correlated random coefficients']] }],
      more: MORE,
    },
    'p:fitmodel:mixed:lsmeans': {
      kicker: 'Mixed Model', title: 'Least Squares Means',
      lead: 'The fixed effects\' predictions at each level of a categorical effect, the other categorical factors averaged over their levels and the continuous ones at their means, with the mixed covariance of the estimates: each mean, difference and contrast with its own denominator degrees of freedom (Kenward-Roger or Satterthwaite).',
      sections: [{ choices: [['Student\'s t', 'every pairwise difference at α'], ['Tukey HSD', 'the studentized range over the levels (each difference\'s own df)'], ['Connecting letters', 'levels that share no letter differ'],
        ['LSMeans Contrast', 'weights of the levels, t tests and their joint F'], ['Test Slices', 'for a crossing: at each level of one factor, the test that the other factors\' cells are equal (the simple effects)'],
        ['LSMeans Plot', 'the means with their intervals; for a crossing, an interaction plot with the overlay factor chosen in its red triangle and the intervals on or off'],
        ['Generalized linear mixed model', 'the means on the link\'s scale and, beside them, on the response\'s (a probability or a rate, a delta-method standard error); the differences also as odds or rate ratios']] }],
      more: MORE,
    },
    'p:fitmodel:mixed:variogram': {
      kicker: 'Mixed Model', title: 'Variogram',
      lead: 'The semivariance of the marginal residuals as a function of the distance between rows: half the mean squared difference of the pairs in each of ten equal distance classes (pairs within a subject). Rising and levelling off: spatial or serial correlation; flat: none.',
      sections: [{ choices: [['The solid line', 'the model\'s structure from its estimates (AR(1), a spatial structure)'], ['Nugget', 'the jump at zero distance'], ['Sill', 'the level it reaches: the variance of a row'],
        ['Range', 'the distance at which it is reached (the spherical range; three times the exponential\'s parameter, √3 times the Gaussian\'s, practically)'],
        ['Added curves', 'from the red triangle: AR(1) and the spatial types, with or without a nugget, fitted to the points by weighted least squares, to choose a structure'],
        ['Columns…', 'with the Residual structure: the continuous columns that place the rows']] }],
      more: MORE,
    },
    'p:fitmodel:mixed:skeleton': {
      kicker: 'Mixed Model', title: 'Skeleton ANOVA',
      lead: 'The degrees of freedom of each source of the model, fixed and random, and of the residual: how many independent pieces of information each takes, from the rank the source adds to the design, in the model\'s order. A design table in the spirit of Stroup\'s "What Would Fisher Do?".',
      sections: [{ choices: [['A random effect confounded with the residual', 'it adds as many degrees of freedom as the rows it spans leave: nothing is left to tell it from the residual (a block by treatment interaction without replication)'],
        ['A random effect confounded with a fixed effect', 'it adds nothing: its levels are those of a fixed effect'], ['Beyond JMP', 'JMP has no Skeleton ANOVA report']] }],
      more: MORE,
    },
    'p:fitmodel:mixed:simulate': {
      kicker: 'Mixed Model', title: 'Simulate',
      lead: 'Power and interval coverage by simulation, as JMP Pro\'s Simulate: responses drawn from the model with the parameters given (the fit\'s to start with), y* = X b + e with e from N(0, V), each sample refitted as the report fits it.',
      sections: [{ choices: [['Rejection Rate', 'the share of samples whose p-value is below α (0.01, 0.05, 0.10, 0.20), with the Wilson interval: the power, or the size of the test when the effect is zero'],
        ['Coverage', 'the share of samples whose interval holds the true value'], ['Stop', 'ends the run after the samples done so far'], ['Random Seed', 'each sample draws from its own seed (the run\'s and its number): the same seed gives the same samples, however many are asked for']] }],
      more: MORE,
    },
  });

  FM.mixed = Object.freeze({ claims, render, validate, launchPart });
}(typeof self !== 'undefined' ? self : this));
