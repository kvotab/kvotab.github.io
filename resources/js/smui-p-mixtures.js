/* ==========================================================================
   SMUI.HTML: ANALYZE > CLUSTERING > NORMAL MIXTURES

   The rows as a mixture of multivariate normal distributions, fitted by EM
   (scikit-learn's GaussianMixture), laid out as JMP lays out the platform:

     Iterative Clustering    the number of clusters and an optional range,
                             tours, the covariance structure, the outlier
                             cluster, Go
     Cluster Comparison      -2LogLikelihood, the number of parameters, AICc
                             and BIC of each number of clusters, the best
                             marked; a click opens that fit
     Normal Mixtures NCluster=k   Cluster Summary (counts, proportions),
                             Cluster Means and Standard Deviations, the
                             clusters' correlations, a scatterplot matrix of
                             the rows coloured by their most likely cluster
                             with each cluster's normal ellipse, a biplot on
                             principal components, the profiler of the
                             cluster probabilities, Save Mixture
                             Probabilities, Save Clusters

   Points are rows (linked). Color Clusters and Mark Clusters give the rows
   the colour and marker of their most likely cluster. The numbers are
   resources/py/smui/mixtures.py's.
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM;
  const { el, fmt, PALETTE } = SM.util;
  const T = (v) => SM.report.plotlyText(v);
  const MORE = { label: 'Normal Mixtures', id: 'help-p-mixtures' };
  const COVS = [['full', 'Full'], ['diag', 'Diagonal'], ['tied', 'Tied'], ['spherical', 'Spherical']];
  const COV_LABEL = Object.fromEntries(COVS);
  const COV_WORDS = { full: 'a covariance matrix for each cluster', diag: 'a variance for each column and cluster, no correlations', tied: 'one covariance matrix shared by the clusters', spherical: 'one variance for each cluster, the same in every column' };
  const LEVELS = [0.5, 0.9, 0.95, 0.99];
  const MAX_SPLOM = 8;

  /* ---- clusters: colours and names -------------------------------------------------
     The palette's grey (9) is the outlier cluster's; the normal clusters take
     the other colours in order. */
  const colorIndex = (c, k, outlier) => (outlier && c === k ? 9 : (c < 9 ? c : c + 1) % PALETTE.length);
  const colorOf = (c, k, outlier) => PALETTE[colorIndex(c, k, outlier)];
  const nameOf = (c, k, outlier) => (outlier && c === k ? 'Outlier' : String(c + 1));
  const plural = (n, one, many = `${one}s`) => `${fmt(n)} ${n === 1 ? one : many}`;
  const fmt4 = (x) => fmt(x, { sig: 4 });

  function roomOf(ctx, dflt = 760) {
    const b = ctx.report && ctx.report.body;
    const w = b && b.clientWidth ? b.clientWidth - 70 : dflt;
    return Math.max(280, Math.min(w, 1100));
  }

  /* A wide table in its own sideways scroller (a phone scrolls it, not the report). */
  const wide = (node) => el('div', { class: 'sm-mix-scroll' }, node);

  /* ---- the graphs as matplotlib code --------------------------------------------------
     Under each graph, Python that draws it with matplotlib from a CSV export of
     the table, as the notebook runs it: the fit's own lines from the backend
     (f.fit_head: the report's rows, the fit, each row's cluster, the means and
     covariances in the columns' units; res.pca_lines for the biplot), then the
     drawing with the page's choices (the columns shown, the ellipses' coverage,
     the bins), the light theme's colours and the graph's size at 100 pixels an
     inch. The Cluster Criteria graph's code is the backend's whole
     (res.criteria_code). The profiler is interactive and has no code. */
  const J = JSON.stringify;
  const pyList = (a) => `[${a.map((v) => J(v)).join(', ')}]`;   // a list as Python writes it
  const pyNum = (v) => (Number.isFinite(v) ? String(v) : Number.isNaN(v) ? 'float("nan")' : v > 0 ? 'float("inf")' : '-float("inf")');
  const inches = (px) => String(Math.round(px) / 100);
  const area = (px) => Math.round(100 * (px * 0.72) ** 2) / 100;   // a marker's diameter in pixels as matplotlib's area in points²
  const INK = '#352921', MUTED_INK = '#786b5d', ZERO = '#e0d7ce';
  const withCode = (graph, code) => (code ? el('div', { class: 'sm-mix-plotcode' }, graph, code) : graph);
  const paletteLines = (f, out) => [`palette = ${pyList(Array.from({ length: f.k + (out ? 1 : 0) }, (_, c) => colorOf(c, f.k, out)))}   # each cluster's colour${out ? ' (grey: the outlier cluster, last)' : ''}`,
    'color = [palette[c] for c in cluster]   # each row in its most likely cluster\'s colour'];
  const ellipseLines = (level) => [`level = ${pyNum(level)}   # Ellipse Coverage`,
    'r = np.sqrt(-2 * np.log(1 - level))   # the normal ellipse that holds this share of its cluster',
    'ang = 2 * np.pi * np.arange(73) / 72', '', '',
    'def ellipse(mx, my, sxx, sxy, syy):',
    '    """The points of the ellipse about (mx, my) of a 2 x 2 covariance [[sxx, sxy], [sxy, syy]], by its Cholesky factor."""',
    '    a = np.sqrt(max(sxx, 0))', '    b = sxy / a if a > 0 else 0', '    c = np.sqrt(max(syy - b * b, 0))',
    '    return mx + r * a * np.cos(ang), my + r * (b * np.cos(ang) + c * np.sin(ang))', '', ''];

  function splomCode(S, f, { use, level, showEll, W, H, msize, title }) {
    const out = S.res.outlier, q = use.length;
    const L = [f.fit_head, '', ...paletteLines(f, out),
      `shown = ${pyList(use.map((c) => S.cols.indexOf(c)))}   # the columns shown (of X)${q < S.cols.length ? `: the first ${q}` : ''}`, `names = ${pyList(use.map((c) => c.name))}`];
    if (showEll) L.push(...ellipseLines(level));
    if (q === 2) L.push(`fig, ax = plt.subplots(figsize=(${inches(W)}, ${inches(H)}), layout="constrained")`, 'cells = [(ax, 1, 0)]');
    else {
      L.push(`g = ${q - 1}`, `fig, axs = plt.subplots(g, g, figsize=(${inches(W)}, ${inches(H)}), sharex="col", sharey="row", squeeze=False, layout="constrained")`,
        'cells = []', 'for i in range(1, g + 1):   # below the diagonal: each column against each one before it', '    for j in range(g):',
        '        if j < i:', '            cells.append((axs[i - 1][j], i, j))', '        else:', '            axs[i - 1][j].set_axis_off()');
    }
    L.push('for ax, i, j in cells:', '    xj, yi = shown[j], shown[i]', `    ax.scatter(X[:, xj], X[:, yi], s=${area(msize)}, color=color, linewidths=0)`);
    if (showEll) {
      L.push(`    for k_ in range(${f.k}):   # each normal cluster's ellipse, from its mean and covariance for the pair`,
        '        ex, ey = ellipse(means[k_, xj], means[k_, yi], covs[k_, xj, xj], covs[k_, xj, yi], covs[k_, yi, yi])',
        '        ax.plot(ex, ey, color=palette[k_], linewidth=1)');
    }
    if (q === 2) L.push('    ax.set_xlabel(names[j])', '    ax.set_ylabel(names[i])', `ax.set_title(${J(title)})`);
    else L.push('    if i == g:', '        ax.set_xlabel(names[j])', '    if j == 0:', '        ax.set_ylabel(names[i])', `fig.suptitle(${J(title)}, fontsize=10)`);
    L.push('plt.show()');
    return L.join('\n');
  }

  function densityCode(S, f, { col, bins, nb, W }) {
    const out = S.res.outlier;
    const L = [f.fit_head, '', paletteLines(f, out)[0], 'x = X[:, 0]',
      `start, size, nb = ${pyNum(bins.start)}, ${pyNum(bins.size)}, ${nb}   # the page's bins`,
      'b = np.clip(np.floor((x - start) / size + 1e-9), 0, nb - 1).astype(int)   # each row\'s bin, as the page counts',
      `counts = np.bincount(b, weights=${S.base.freq ? 'f' : 'None'}, minlength=nb)${S.base.freq ? '   # each row counted its Freq times' : ''}`,
      `grid = start + (${pyNum(bins.end)} - start) * np.arange(201) / 200   # the curves' points, over the bins`,
      'scale = N * size   # the densities scaled to counts',
      `fig, ax = plt.subplots(figsize=(${inches(W)}, 3.2), layout="constrained")`,
      `bars = ax.bar(start + (np.arange(nb) + 0.5) * size, counts, width=size, color="${SM.report.BAR}", edgecolor="#fcf7f2", linewidth=0.58, label=${J(col.name)})`,
      'total, curves = np.zeros(len(grid)), []',
      `for k_ in range(${f.k}):   # each normal cluster: its proportion times its normal density`,
      '    sd = np.sqrt(covs[k_, 0, 0])',
      '    y = w[k_] * np.exp(-0.5 * ((grid - means[k_, 0]) / sd) ** 2) / (sd * np.sqrt(2 * np.pi)) * scale',
      '    total += y',
      '    curves += ax.plot(grid, y, color=palette[k_], linewidth=1.15, label=f"Cluster {k_ + 1}")'];
    if (out) {
      L.push('a, z = x.min(), x.max()   # the outlier cluster: uniform over the rows\' range', `yy = w[${f.k}] * box_density * scale`,
        'total += np.where((grid >= a) & (grid <= z), yy, 0)', `curves += ax.plot([a, a, z, z], [0, yy, yy, 0], color=palette[${f.k}], linewidth=1, linestyle=":", label="Outlier")`);
    }
    L.push(`curves += ax.plot(grid, total, color="${INK}", linewidth=0.86, linestyle="--", label="Mixture")   # their sum`,
      'ax.set_ylim(bottom=0)', `ax.set_xlabel(${J(col.name)})`, 'ax.set_ylabel("Count")',
      'ax.legend(handles=[bars, *curves], frameon=False, fontsize=7.5)', `ax.set_title(${J(`${col.name} with the mixture, ${f.k} clusters`)})`, 'plt.show()');
    return L.join('\n');
  }

  function biplotCode(S, f, { level, showEll, rays, W, msize, legendRight, title }) {
    const out = S.res.outlier;
    const L = [f.fit_head, S.res.pca_lines, '', ...paletteLines(f, out)];
    if (showEll) L.push(...ellipseLines(level));
    L.push(`fig, ax = plt.subplots(figsize=(${inches(W)}, 4.4), layout="constrained")`,
      `ax.axhline(0, color="${ZERO}", linewidth=0.72, zorder=0)`, `ax.axvline(0, color="${ZERO}", linewidth=0.72, zorder=0)`,
      `ax.scatter(scores[:, 0], scores[:, 1], s=${area(msize)}, color=color, linewidths=0)`,
      `for k_ in range(${f.k}):`);
    if (showEll) {
      L.push('    ex, ey = ellipse(pc_means[k_, 0], pc_means[k_, 1], pc_covs[k_, 0, 0], pc_covs[k_, 0, 1], pc_covs[k_, 1, 1])',
        '    ax.fill(ex, ey, color=palette[k_], alpha=31 / 255, linewidth=0)', '    ax.plot(ex, ey, color=palette[k_], linewidth=0.86)');
    }
    L.push('    ax.scatter([pc_means[k_, 0]], [pc_means[k_, 1]], s=(0.72 * (11 + 20 * np.sqrt(w[k_]))) ** 2, facecolors="none", edgecolors=palette[k_], linewidths=1.44,',
      '               label=f"Cluster {k_ + 1}")   # its centre: the circle grows with its proportion',
      `    ax.text(pc_means[k_, 0], pc_means[k_, 1], str(k_ + 1), ha="center", va="center", fontsize=7.2, color="${INK}")`);
    if (out) L.push(`ax.scatter([], [], s=${area(8)}, color=palette[${f.k}], label="Outlier")`);
    if (rays) {
      L.push('smax, lmax = np.abs(scores).max(), np.abs(E2).max()', 'sc = 0.8 * smax / lmax if lmax > 0 else 1   # the longest ray reaches 80% of the farthest row',
        `for j, name in enumerate(${pyList(S.cols.map((c) => c.name))}):   # a ray for each column: its loadings`,
        `    ax.plot([0, sc * E2[j, 0]], [0, sc * E2[j, 1]], color="${MUTED_INK}", linewidth=0.72)`,
        `    ax.text(sc * E2[j, 0], sc * E2[j, 1], name, ha="center", va="center", fontsize=7.2, color="${INK}")`);
    }
    L.push('tot = np.maximum(evals, 0).sum()', 'ax.set_xlabel(f"Prin1 ({100 * evals[0] / tot:.1f}%)")', 'ax.set_ylabel(f"Prin2 ({100 * evals[1] / tot:.1f}%)")',
      legendRight ? 'ax.legend(loc="upper left", bbox_to_anchor=(1.02, 1), frameon=False, fontsize=7.5)' : 'fig.legend(loc="outside lower center", ncols=4, frameon=False, fontsize=7.5)',
      `ax.set_title(${J(title)})`, 'plt.show()');
    return L.join('\n');
  }

  function rowLabels(ctx, rows) {
    const lab = ctx.table ? ctx.table.labelColumn() : null;
    return rows.map((r) => (lab && !SM.table.isMissing(lab.values[r]) ? `${T(SM.grid.cellText(lab, lab.values[r]))} (row ${r + 1})` : `row ${r + 1}`));
  }

  /* Points of the ellipse (x − μ)ᵀ Σ⁻¹ (x − μ) = χ²₂(level) from a 2 × 2
     covariance [[a, b], [b, c]]: μ + r L (cos t, sin t), L its Cholesky factor. */
  function ellipse(mx, my, sxx, sxy, syy, level, m = 72) {
    const r = Math.sqrt(-2 * Math.log(1 - level));
    const a = Math.sqrt(Math.max(sxx, 0));
    const b = a > 0 ? sxy / a : 0;
    const c = Math.sqrt(Math.max(syy - b * b, 0));
    const x = [], y = [];
    for (let t = 0; t <= m; t++) {
      const u = Math.cos((2 * Math.PI * t) / m), v = Math.sin((2 * Math.PI * t) / m);
      x.push(mx + r * a * u);
      y.push(my + r * (b * u + c * v));
    }
    return { x, y };
  }

  /* ---- the payload: every option that changes the fits ------------------------------ */
  function payloadOf(ctx) {
    const o = (k, d) => ctx.opt(k, d);
    const kmin = Math.max(1, Math.round(Number(o('k', 3)) || 3));
    const kr = o('kRange', null);
    return {
      columns: ctx.names('y'), freq: ctx.name('freq'), k_min: kmin, k_max: kr && kr > kmin ? Math.min(Math.round(kr), kmin + 19) : kmin,
      covariance: o('covariance', 'full'), tours: Math.round(Number(o('tours', 10)) || 10), outlier: !!o('outlier', false), standardize: !!o('scaled', true),
      seed: SM.predict.seed(ctx), max_iter: Math.round(Number(o('maxIter', 500)) || 500), tol: Number(o('tol', 1e-6)) || 1e-6, choose: o('choose', 'bic'),
    };
  }

  /* ======================================================================
     RENDER
     ====================================================================== */
  async function render(ctx) {
    const cols = ctx.roles('y');
    const o = (k, d) => ctx.opt(k, d);
    const base = payloadOf(ctx);
    if (o('control', true)) controlOutline(ctx, base);
    const nFits = base.k_max - base.k_min + 1;
    const status = el('p', { class: 'sm-ob-note sm-mix-progress', role: 'status', text: nFits > 1 ? `Normal Mixtures: fitting ${nFits} numbers of clusters…` : 'Normal Mixtures: fitting…' });
    if (!ctx.headless) ctx.container.append(status);
    const off = ctx.headless ? () => {} : SM.engine.on('progress', (p) => {
      if (!p || p.what !== 'mixtures') return;
      const text = `Normal Mixtures${ctx.byLabel ? ` (${ctx.byLabel})` : ''}: ${p.done} of ${p.total} fits…`;
      status.textContent = text;
      ctx.report.noteEl.textContent = text;
    });
    let res;
    try { res = await ctx.call('mixtures.fit', { ...base, where: ctx.where || [] }); } finally { off(); status.remove(); }
    if (res.error) { ctx.container.append(ctx.warn(res.error)); return; }
    const S = { res, cols, base, open: null };
    const ok = res.fits.filter((f) => !f.error);
    const want = o('open', null);
    S.open = ok.find((f) => f.k === want) || ok.find((f) => f.k === res.best) || ok[0] || null;
    const lines = [`${plural(res.n, 'observation')}${res.n !== res.n_rows ? ` (${plural(res.n_rows, 'row')}, each counted by ${ctx.name('freq')})` : ''}`,
      res.standardize ? 'each column scaled to standard deviation 1 for the fit (the results are in the columns\' units)' : 'the columns as they are',
      `${COV_LABEL[res.covariance].toLowerCase()} covariances (${COV_WORDS[res.covariance]})`,
      `${res.tours} tour${res.tours === 1 ? '' : 's'} from the seed ${res.seed}${res.outlier ? '; with an outlier cluster' : ''}`];
    ctx.container.append(ctx.note(`${lines.join('; ')}.${res.notes.length ? ` ${res.notes.join(' ')}` : ''}`));
    if (S.open && (o('colorClusters', false) || o('markClusters', false))) rowStates(ctx, S);
    if (o('comparison', true) || res.fits.length > 1) comparisonOutline(ctx, S);
    for (const f of res.fits) {
      if (f.error) continue;
      await fitOutline(ctx, S, f, S.open && f.k === S.open.k);
    }
    const bad = res.fits.filter((f) => f.error);
    if (bad.length) ctx.container.append(ctx.warn(bad.map((f) => `${f.k} clusters: ${f.error}`).join('; ')));
  }

  /* Color Clusters, Mark Clusters: the rows take their cluster's colour and
     marker when the clusters change (not when the report is only drawn again,
     and never for the other theme). */
  function rowStates(ctx, S) {
    if (ctx.reason === 'theme' || ctx.headless) return;
    const f = S.open;
    const out = S.res.outlier;
    const stamp = `${f.k}|${JSON.stringify(S.base)}`;
    const done = ctx.report._mixStamps || (ctx.report._mixStamps = {});
    const groups = groupsOf(S.res, f);
    for (const [opt, fn] of [['colorClusters', (rs, c) => ctx.table.setColor(rs, colorIndex(c, f.k, out))], ['markClusters', (rs, c) => ctx.table.setMarker(rs, c % 12)]]) {
      const key = `${opt}\u0001${ctx.path}`;
      if (!ctx.opt(opt, false)) { delete done[key]; continue; }
      if (done[key] !== stamp) { groups.forEach((rs, c) => { if (rs.length) fn(rs, c); }); done[key] = stamp; }
    }
  }

  /* The rows of each cluster (the outlier cluster last). */
  function groupsOf(res, f) {
    const m = f.k + (res.outlier ? 1 : 0);
    const g = Array.from({ length: m }, () => []);
    f.labels.forEach((c, i) => g[c].push(res.rows[i]));
    return g;
  }

  /* ---- the control panel ------------------------------------------------------------ */
  function controlOutline(ctx, base) {
    const o = (k, d) => ctx.opt(k, d);
    const d = { k: o('k', 3), kRange: o('kRange', null), tours: o('tours', 10), maxIter: o('maxIter', 500), tol: o('tol', 1e-6), seed: o('seed', '') };
    const num = (value, set, size, aria) => {
      const i = el('input', { type: 'text', inputmode: 'decimal', size, 'aria-label': aria, class: 'sm-mix-num' });
      i.value = value == null ? '' : String(value);
      const read = () => { const t = i.value.trim().replace(',', '.').replace('−', '-'); set(t === '' ? null : Number(t)); };
      i.addEventListener('change', read);
      i.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') { ev.preventDefault(); read(); go(); } });
      return i;
    };
    const check = (on, aria) => { const c = el('input', { type: 'checkbox', 'aria-label': aria }); c.checked = !!on; return c; };
    const cov = el('select', { 'aria-label': 'Covariance structure' }, ...COVS.map(([v, l]) => el('option', { value: v, text: l })));
    cov.value = o('covariance', 'full');
    const outl = check(o('outlier', false), 'Outlier cluster');
    const scaled = check(o('scaled', true), 'Columns scaled individually');
    const seedIn = el('input', { type: 'text', size: 10, 'aria-label': 'Random seed', class: 'sm-mix-num', placeholder: String(base.seed) });
    seedIn.value = d.seed == null ? '' : String(d.seed);
    const lab = (text, input) => el('label', { class: 'sm-mix-control' }, el('span', { text }), input);
    const go = () => {
      const k = Math.max(1, Math.round(d.k || 3));
      const bad = [];
      if (d.kRange != null && !(Number.isFinite(d.kRange))) bad.push('Range of Clusters');
      if (!(Number.isFinite(d.tours) && d.tours >= 1 && d.tours <= 100)) bad.push('Tours (1 to 100)');
      if (!(Number.isFinite(d.maxIter) && d.maxIter >= 1 && d.maxIter <= 10000)) bad.push('Maximum Iterations (1 to 10000)');
      if (!(Number.isFinite(d.tol) && d.tol > 0)) bad.push('Converge Criteria (a positive number)');
      const s = seedIn.value.trim();
      if (s !== '' && !Number.isFinite(Number(s))) bad.push('Random Seed (a whole number)');
      if (bad.length) { SM.ui.toast(`Check ${bad.join(', ')}`, { error: true }); return; }
      ctx.set('kRange', d.kRange && d.kRange > k ? Math.min(Math.round(d.kRange), k + 19) : null, null, { rerun: false });
      ctx.set('tours', Math.round(d.tours), null, { rerun: false });
      ctx.set('maxIter', Math.round(d.maxIter), null, { rerun: false });
      ctx.set('tol', d.tol, null, { rerun: false });
      ctx.set('covariance', cov.value, null, { rerun: false });
      ctx.set('outlier', outl.checked, null, { rerun: false });
      ctx.set('scaled', scaled.checked, null, { rerun: false });
      ctx.set('seed', s === '' ? '' : Math.trunc(Number(s)), null, { rerun: false });
      ctx.set('open', null, null, { rerun: false });
      ctx.set('k', k);
    };
    const btn = el('button', { type: 'button', class: 'sm-btn small primary', text: 'Go' });
    btn.addEventListener('click', go);
    const ob = ctx.outline('Iterative Clustering', { key: 'control', info: 'mix:control' });
    ob.add(el('div', { class: 'sm-mix-controls' },
      lab('Number of Clusters', num(d.k, (v) => { d.k = v; }, 3, 'Number of clusters')),
      lab('Range of Clusters (Optional)', num(d.kRange, (v) => { d.kRange = v; }, 3, 'Range of clusters')),
      lab('Tours', num(d.tours, (v) => { d.tours = v; }, 3, 'Tours')),
      lab('Covariance', cov),
      lab('Outlier Cluster', outl),
      lab('Columns Scaled Individually', scaled),
      lab('Maximum Iterations', num(d.maxIter, (v) => { d.maxIter = v; }, 5, 'Maximum iterations')),
      lab('Converge Criteria', num(d.tol, (v) => { d.tol = v; }, 7, 'Converge criteria')),
      lab('Random Seed', seedIn),
      btn));
  }

  /* ---- Cluster Comparison ----------------------------------------------------------- */
  function comparisonOutline(ctx, S) {
    const { res } = S;
    const ok = res.fits.filter((f) => !f.error);
    const crit = res.choose === 'aicc' ? 'AICc' : 'BIC';
    const ob = ctx.outline('Cluster Comparison', { key: 'comparison', info: 'mix:comparison', menu: () => [
      { label: 'Best By', submenu: () => [['bic', 'BIC'], ['aicc', 'AICc']].map(([v, l]) => ({ label: l, checked: ctx.opt('choose', 'bic') === v, action: () => { ctx.set('open', null, null, { rerun: false }); ctx.set('choose', v); } })) },
    ] });
    // NCluster is the rows' text (Bootstrap finds the rows by their text
    // columns); Best and Converged are words in columns that are not text.
    const rows = ok.map((f) => ({ method: res.outlier ? 'Normal Mixtures, Outlier Cluster' : 'Normal Mixtures', k: String(f.k), _k: f.k, m2ll: f.m2ll, q: f.n_params, aicc: f.aicc, bic: f.bic, best: f.k === res.best ? `Optimal ${crit}` : '', aic: f.aic, it: f.n_iter, conv: f.converged ? 'Yes' : 'No' }));
    ob.add(wide(ctx.rt({
      columns: [{ key: 'method', label: 'Method', fmt: 'text' }, { key: 'k', label: 'NCluster', fmt: 'text' }, { key: 'm2ll', label: '-2LogLikelihood' }, { key: 'q', label: 'Number of Parameters', fmt: 'int' },
        { key: 'aicc', label: 'AICc' }, { key: 'bic', label: 'BIC' }, { key: 'best', label: 'Best', left: true }, { key: 'aic', label: 'AIC', hidden: true }, { key: 'it', label: 'Iterations', fmt: 'int', hidden: true }, { key: 'conv', label: 'Converged', left: true, hidden: true }],
      rows,
    }, { key: 'comparison', onRow: (r) => ctx.set('open', r._k), cellClass: (r, c) => [S.open && r._k === S.open.k ? 'sm-mix-open' : '', c.key === 'k' ? 'sm-mix-right' : ''].filter(Boolean).join(' ') })));
    if (ok.length >= 3) {
      const tc = SM.util.themeColors();
      const ks = ok.map((f) => f.k);
      ob.add(withCode(ctx.plot([
        { type: 'scatter', mode: 'lines+markers', x: ks, y: ok.map((f) => f.bic), name: 'BIC', line: { color: SM.report.BASE, width: 1.6 }, marker: { size: 6 }, hovertemplate: '%{x} clusters: BIC %{y:.1f}<extra></extra>' },
        { type: 'scatter', mode: 'lines+markers', x: ks, y: ok.map((f) => f.aicc), name: 'AICc', line: { color: tc.dark ? '#e8904f' : '#b0413e', width: 1.4, dash: 'dot' }, marker: { size: 5, symbol: 'square' }, hovertemplate: '%{x} clusters: AICc %{y:.1f}<extra></extra>' },
      ], { showlegend: true, legend: { orientation: 'h', x: 0, y: 1.02, yanchor: 'bottom' }, xaxis: { title: { text: 'NCluster' }, dtick: 1 }, yaxis: { title: { text: 'Criterion' } }, margin: { l: 60, r: 12, t: 26, b: 42 } },
      { width: Math.min(460, roomOf(ctx)), height: 250, title: 'Cluster criteria', select: false }), ctx.code(res.criteria_code)));
    }
    ob.add(ctx.note(`-2LogLikelihood of the fitted mixture in the columns' units; AICc = −2 log L + 2q + 2q(q + 1)/(N − q − 1) and BIC = −2 log L + q ln N, q the number of parameters (means, covariances${res.outlier ? ', the proportions and the outlier cluster\'s' : ' and proportions'}), N ${fmt(res.n)}. Smaller is better: the best by ${crit} is marked. Click a line to open its report.`),
      ctx.code(res.code));
  }

  /* ---- one fit ----------------------------------------------------------------------- */
  async function fitOutline(ctx, S, f, open) {
    const { res, cols } = S;
    const sc = `k${f.k}`;
    const o = (key, d) => ctx.opt(key, d, sc);
    const out = res.outlier;
    const m = f.k + (out ? 1 : 0);
    const groups = groupsOf(res, f);
    const ob = ctx.outline(`Normal Mixtures NCluster=${f.k}`, { key: `mix:${f.k}`, closed: !open, info: 'mix:fit', menu: () => fitMenu(ctx, S, f) });
    const props = f.weights.concat(out ? [f.outlier_weight] : []);
    const summary = ctx.rt({
      caption: 'Cluster Summary',
      columns: [{ key: 'c', label: 'Cluster', fmt: 'text' }, { key: 'n', label: 'Count' }, { key: 'prop', label: 'Proportion', digits: 4 }, { key: 'share', label: 'Share of Rows', digits: 4, hidden: true }],
      rows: Array.from({ length: m }, (_, c) => ({ c: nameOf(c, f.k, out), n: f.counts[c], prop: props[c], share: f.counts[c] / res.n, _c: c })),
    }, { key: 'summary', sortable: false, onRow: (r, ev) => ctx.table.select(groups[r._c], ev.shiftKey ? 'add' : 'replace') });
    const fitKv = ctx.kv([['-2LogLikelihood', f.m2ll], ['Number of Parameters', f.n_params, 'int'], ['AICc', f.aicc], ['BIC', f.bic], ['Iterations', f.n_iter, 'int'], ['Converged', f.converged ? 'Yes' : 'No', 'text']]);
    ob.add(ctx.row(summary, fitKv));
    if (!f.converged) ob.add(ctx.warn(`The EM stopped after ${f.n_iter} iterations without meeting the convergence criterion: raise Maximum Iterations or loosen Converge Criteria (Iterative Clustering).`));
    const colsT = [{ key: 'c', label: 'Cluster', fmt: 'text' }, ...cols.map((c, j) => ({ key: `v${j}`, label: c.name }))];
    const rowsT = (M) => M.map((row, c) => Object.assign({ c: nameOf(c, f.k, out) }, ...cols.map((_, j) => ({ [`v${j}`]: row[j] }))));
    ob.add(wide(ctx.rt({ columns: colsT, rows: rowsT(f.means), caption: 'Cluster Means' }, { key: 'means', sortable: false })),
      wide(ctx.rt({ columns: colsT, rows: rowsT(f.sds), caption: 'Cluster Standard Deviations' }, { key: 'sds', sortable: false })));
    if (out) ob.add(ctx.note(`The outlier cluster is uniform over the box that holds the rows (${cols.map((c, j) => `${c.name} ${fmt4(res.box.lo[j])} to ${fmt4(res.box.hi[j])}`).join(', ')}): density ${fmt(f.outlier_density, { sig: 4 })} there, proportion ${fmt(f.outlier_weight, { digits: 4 })}.`));
    ob.add(el('div', { class: 'sm-mix-legend' }, ...groups.map((rs, c) => {
      const b = el('button', { type: 'button', title: `Select the rows of cluster ${nameOf(c, f.k, out)}` }, el('span', { class: 'sm-mix-swatch', style: { background: colorOf(c, f.k, out) } }), `${out && c === f.k ? 'Outlier' : `Cluster ${c + 1}`}: ${fmt(f.counts[c])}`);
      b.addEventListener('click', (ev) => ctx.table.select(rs, ev.shiftKey ? 'add' : 'replace'));
      return b;
    })));
    // The graphs are built when the outline is (or gets) open: a range of
    // clusters would otherwise draw every fit's matrix.
    let built = false;
    const build = async () => {
      if (built) return;
      built = true;
      if (o('corrs', false)) correlations(ctx, S, f, ob);
      if (cols.length === 1) densityOutline(ctx, S, f, ob);
      else if (o('splom', true)) splomOutline(ctx, S, f, ob);
      if (cols.length > 2 && o('biplot', true)) biplotOutline(ctx, S, f, ob);
      const code = ctx.code(f.code);
      if (o('profiler', false)) {
        await SM.profiler.render(ctx, ob, { sources: [{ fn: 'mixtures.profile', payload: { ...S.base, k: f.k } }], scope: sc, option: 'profiler', key: `profiler:${f.k}`,
          note: 'Each cluster\'s probability as one column changes, the others held at their current values.' });
      }
      ob.add(code);
    };
    if (ob.isOpen) await build();
    else {
      const later = async () => { if (ob.isOpen && !built) { await build(); requestAnimationFrame(() => { SM.report.kickPlots(ob.body); if (typeof KvotInfo !== 'undefined') KvotInfo.mount(ob.el); }); } };
      ob.toggleBtn.addEventListener('click', later);
      ob.titleEl.addEventListener('dblclick', later);
    }
  }

  function fitMenu(ctx, S, f) {
    const sc = `k${f.k}`;
    const p = S.cols.length;
    const items = [];
    if (p >= 2) items.push(ctx.check('Scatterplot Matrix', 'splom', sc, true));
    if (p > 2) items.push(ctx.check('Biplot', 'biplot', sc, true), ctx.check('Biplot Rays', 'rays', sc, true));
    items.push(ctx.check('Density Ellipses', 'ellipses', sc, true));
    items.push({ label: 'Ellipse Coverage', submenu: () => LEVELS.map((a) => ({ label: String(a), checked: ctx.opt('level', 0.9, sc) === a, action: () => ctx.set('level', a, sc) })) });
    if (p >= 2) items.push(ctx.check('Cluster Correlations', 'corrs', sc, false));
    items.push(ctx.check('Profiler', 'profiler', sc, false));
    items.push({ separator: true },
      { label: 'Save Colors to Table', action: () => groupsOf(S.res, f).forEach((rs, c) => { if (rs.length) ctx.table.setColor(rs, colorIndex(c, f.k, S.res.outlier)); }) },
      { label: 'Save Markers to Table', action: () => groupsOf(S.res, f).forEach((rs, c) => { if (rs.length) ctx.table.setMarker(rs, c % 12); }) },
      { label: 'Save Clusters', action: () => saveClusters(ctx, S, f) },
      { label: 'Save Mixture Probabilities', action: () => saveProbabilities(ctx, S, f) },
      { label: 'Save Mixture Formulas', action: () => saveFormulas(ctx, S, f) });
    return items;
  }

  /* ---- saved columns -----------------------------------------------------------------
     Every row of the By group whose columns are present gets its cluster and
     probabilities from the report's fit: the rows the report leaves out
     (excluded, filtered, a Freq below 1) too. Save Mixture Formulas makes
     them live formula columns, as JMP's. */
  async function saveClusters(ctx, S, f) {
    const out = S.res.outlier;
    try {
      const r = await ctx.call('mixtures.save', { ...S.base, k: f.k, where: ctx.where || [] });
      ctx.saveColumn('Cluster', { rows: r.rows, values: r.cluster }, {
        modelingType: 'nominal',
        notes: `the most likely cluster of a normal mixture of ${f.k} clusters (${COV_LABEL[S.res.covariance].toLowerCase()} covariances${out ? `; ${f.k + 1} is the outlier cluster` : ''}), from ${ctx.report.title}${ctx.byLabel ? ` ${ctx.byLabel}` : ''}`,
      });
    } catch (e) { SM.ui.toast(e.message || String(e), { error: true }); }
  }

  async function saveProbabilities(ctx, S, f) {
    try {
      const r = await ctx.call('mixtures.save', { ...S.base, k: f.k, where: ctx.where || [] });
      r.names.forEach((nm, j) => ctx.saveColumn(nm, { rows: r.rows, values: r.prob.map((row) => row[j]) }, {
        notes: `the probability of ${j < r.k ? `cluster ${j + 1}` : 'the outlier cluster'} in a normal mixture of ${f.k} clusters, from ${ctx.report.title}${ctx.byLabel ? ` ${ctx.byLabel}` : ''}`,
      }));
    } catch (e) { SM.ui.toast(e.message || String(e), { error: true }); }
  }

  async function saveFormulas(ctx, S, f) {
    try {
      const r = await ctx.call('mixtures.formulas', { ...S.base, k: f.k, where: ctx.where || [] });
      if (SM.multivariate) SM.multivariate.saveBatch(ctx, r);
      else SM.ui.toast('Save Mixture Formulas needs the Multivariate platforms', { error: true });
    } catch (e) { SM.ui.toast(e.message || String(e), { error: true }); }
  }

  /* ---- the clusters' correlations ------------------------------------------------------ */
  function correlations(ctx, S, f, parent) {
    const { cols, res } = S;
    const sub = ctx.outline('Cluster Correlations', { parent, key: `corrs:${f.k}`, menu: () => [{ label: 'Remove', action: () => ctx.set('corrs', false, `k${f.k}`) }] });
    if (res.covariance === 'diag' || res.covariance === 'spherical') { sub.add(ctx.note(`With ${COV_LABEL[res.covariance].toLowerCase()} covariances the columns are uncorrelated within every cluster.`)); return; }
    const names = cols.map((c) => c.name);
    const tables = f.corrs.slice(0, res.covariance === 'tied' ? 1 : f.k).map((R, c) => ctx.rt({
      caption: res.covariance === 'tied' ? 'Every cluster' : `Cluster ${c + 1}`,
      columns: [{ key: '_v', label: '', fmt: 'text' }, ...names.map((nm, j) => ({ key: `c${j}`, label: nm, digits: 4 }))],
      rows: names.map((nm, i) => Object.assign({ _v: nm }, ...names.map((_, j) => ({ [`c${j}`]: R[i][j] })))),
    }, { key: `corr${c}`, sortable: false }));
    sub.add(el('div', { class: 'sm-mix-corrs' }, ...tables.map((t) => wide(t))), ctx.note('The correlations of the columns within each cluster: its covariance matrix scaled to a unit diagonal.'));
  }

  /* ---- the scatterplot matrix ---------------------------------------------------------- */
  function splomOutline(ctx, S, f, parent) {
    const { res, cols } = S;
    const sc = `k${f.k}`;
    const p = cols.length;
    const title = p === 2 ? 'Scatterplot' : 'Scatterplot Matrix';
    const sub = ctx.outline(title, { parent, key: `splom:${f.k}`, info: 'mix:splom' });
    const use = p > MAX_SPLOM ? cols.slice(0, MAX_SPLOM) : cols;
    const q = use.length;
    const g = q - 1;
    const out = res.outlier;
    const level = ctx.opt('level', 0.9, sc);
    const showEll = ctx.opt('ellipses', true, sc);
    const room = roomOf(ctx);
    const size = q === 2 ? Math.min(440, room) : Math.max(70, Math.min(180, Math.floor((Math.min(room, 900) - 70) / g)));
    const W = q === 2 ? size : size * g + 70, H = q === 2 ? Math.round(size * 0.9) : size * g + 56;
    const vals = use.map((c) => res.rows.map((r) => c.values[r]));
    const colors = f.labels.map((c) => colorOf(c, f.k, out));
    const hover = rowLabels(ctx, res.rows).map((t, i) => `${t}<br>cluster ${nameOf(f.labels[i], f.k, out)}, p = ${f.pmax[i].toFixed(3)}`);
    const n = res.rows.length;
    const type = n * (q * (q - 1)) / 2 > 20000 && SM.report.hasWebGL() ? 'scattergl' : 'scatter';
    const msize = n > 2000 ? 3 : n > 500 ? 4 : 5.5;
    const traces = [];
    const layout = { margin: { l: 58, r: 8, t: 6, b: 50 }, dragmode: 'select', showlegend: false };
    const gap = q === 2 ? 0 : 0.014;
    let a = 0;
    for (let i = 1; i < q; i++) {
      for (let j = 0; j < i; j++) {
        a++;
        const xa = a === 1 ? 'x' : `x${a}`, ya = a === 1 ? 'y' : `y${a}`;
        const gi = i - 1, gj = j;
        const bottom = gi === g - 1, left = gj === 0;
        layout[`xaxis${a === 1 ? '' : a}`] = { domain: [gj / g + gap, (gj + 1) / g - gap], anchor: ya, showticklabels: bottom, zeroline: false, showgrid: false, ticks: bottom ? 'outside' : '', title: bottom ? { text: T(use[j].name), standoff: 4, font: { size: 10.5 } } : undefined, tickfont: { size: 9 }, nticks: 4, mirror: true };
        layout[`yaxis${a === 1 ? '' : a}`] = { domain: [1 - (gi + 1) / g + gap, 1 - gi / g - gap], anchor: xa, showticklabels: left, zeroline: false, showgrid: false, ticks: left ? 'outside' : '', title: left ? { text: T(use[i].name), standoff: 4, font: { size: 10.5 } } : undefined, tickfont: { size: 9 }, nticks: 4, mirror: true };
        traces.push({ type, mode: 'markers', x: vals[j], y: vals[i], rows: res.rows, marker: { size: msize, color: colors }, xaxis: xa, yaxis: ya, hovertext: hover, hovertemplate: `%{hovertext}<br>${T(use[j].name)}: %{x}<br>${T(use[i].name)}: %{y}<extra></extra>`, name: `${use[i].name} by ${use[j].name}` });
        if (showEll) {
          const jj = cols.indexOf(use[j]), ii = cols.indexOf(use[i]);
          for (let c = 0; c < f.k; c++) {
            const C = f.covs[c];
            const e = ellipse(f.means[c][jj], f.means[c][ii], C[jj][jj], C[jj][ii], C[ii][ii], level);
            traces.push({ type: 'scatter', mode: 'lines', x: e.x, y: e.y, xaxis: xa, yaxis: ya, line: { color: colorOf(c, f.k, out), width: 1.4 }, hoverinfo: 'skip', name: `cluster ${c + 1} ellipse` });
          }
        }
      }
    }
    sub.add(ctx.row(withCode(ctx.plot(traces, layout, { width: W, height: H, title: `${title}, ${f.k} clusters`, rowColors: false }),
      ctx.code(splomCode(S, f, { use, level, showEll, W, H, msize, title: `${title}, ${f.k} clusters` })))),
      ctx.note(`Each row in the colour of its most likely cluster${out ? ' (grey: the outlier cluster)' : ''}${showEll ? `; each cluster's ${fmt(100 * level)}% normal ellipse, from its fitted mean and covariance` : ''}.${p > MAX_SPLOM ? ` The first ${MAX_SPLOM} of the ${p} columns.` : ''} Drag over points to select rows.`));
  }

  /* ---- one column: the histogram with the fitted densities --------------------------------- */
  function densityOutline(ctx, S, f, parent) {
    const { res, cols } = S;
    const out = res.outlier;
    const col = cols[0];
    const sub = ctx.outline('Mixture Density', { parent, key: `density:${f.k}`, info: 'mix:splom' });
    const vals = res.rows.map((r) => col.values[r]);
    const wts = res.rows.map((r) => { const fr = ctx.role('freq'); return fr ? Math.floor(fr.values[r]) : 1; });
    const b = SM.report.niceBins(vals);
    const nb = Math.max(1, Math.round((b.end - b.start) / b.size));
    const counts = new Array(nb).fill(0), members = Array.from({ length: nb }, () => []);
    vals.forEach((v, i) => { const h = Math.min(nb - 1, Math.max(0, Math.floor((v - b.start) / b.size + 1e-9))); counts[h] += wts[i]; members[h].push(res.rows[i]); });
    const tc = SM.util.themeColors();
    const traces = [{ type: 'bar', x: counts.map((_, h) => b.start + (h + 0.5) * b.size), y: counts, width: b.size, rows: members, marker: { color: SM.report.BAR, line: { color: tc.surface, width: 0.8 } }, hovertemplate: '%{x}: %{y}<extra></extra>', name: col.name }];
    const lo = b.start, hi = b.end;
    const xs = Array.from({ length: 201 }, (_, t) => lo + ((hi - lo) * t) / 200);
    const scale = res.n * b.size;
    const tot = xs.map(() => 0);
    for (let c = 0; c < f.k; c++) {
      const mu = f.means[c][0], sd = f.sds[c][0], w = f.weights[c];
      const ys = xs.map((x) => (w * Math.exp(-0.5 * ((x - mu) / sd) ** 2)) / (sd * Math.sqrt(2 * Math.PI)) * scale);
      ys.forEach((y, t) => { tot[t] += y; });
      traces.push({ type: 'scatter', mode: 'lines', x: xs, y: ys, line: { color: colorOf(c, f.k, out), width: 1.6 }, hovertemplate: `cluster ${c + 1}: %{y:.1f}<extra></extra>`, name: `Cluster ${c + 1}` });
    }
    if (out) {
      const [a, z] = [res.box.lo[0], res.box.hi[0]];
      const yy = f.outlier_weight * f.outlier_density * scale;
      xs.forEach((x, t) => { if (x >= a && x <= z) tot[t] += yy; });
      traces.push({ type: 'scatter', mode: 'lines', x: [a, a, z, z], y: [0, yy, yy, 0], line: { color: colorOf(f.k, f.k, true), width: 1.4, dash: 'dot' }, hoverinfo: 'skip', name: 'Outlier' });
    }
    traces.push({ type: 'scatter', mode: 'lines', x: xs, y: tot, line: { color: tc.text, width: 1.2, dash: 'dash' }, hovertemplate: 'mixture: %{y:.1f}<extra></extra>', name: 'Mixture' });
    const W = Math.min(560, roomOf(ctx));
    sub.add(ctx.row(withCode(ctx.plot(traces, { showlegend: true, legend: { orientation: 'h', x: 0, y: 1.02, yanchor: 'bottom' }, xaxis: { title: { text: T(col.name) } }, yaxis: { title: { text: 'Count' }, rangemode: 'tozero' }, bargap: 0.02, margin: { l: 56, r: 12, t: 28, b: 42 } },
      { width: W, height: 320, title: `${col.name} with the mixture, ${f.k} clusters` }), ctx.code(densityCode(S, f, { col, bins: b, nb, W })))),
    ctx.note('The histogram of the rows (click a bar to select them) with each cluster\'s normal density times its proportion, and their sum, scaled to counts.'));
  }

  /* ---- the biplot on principal components -------------------------------------------------- */
  function biplotOutline(ctx, S, f, parent) {
    const { res, cols } = S;
    const sc = `k${f.k}`;
    const out = res.outlier;
    const P = res.pca;
    const level = ctx.opt('level', 0.9, sc);
    const tc = SM.util.themeColors();
    const sub = ctx.outline('Biplot', { parent, key: `biplot:${f.k}`, info: 'mix:biplot' });
    const x = P.scores.map((s) => s[0]), y = P.scores.map((s) => s[1]);
    const n = x.length;
    const colors = f.labels.map((c) => colorOf(c, f.k, out));
    const hover = rowLabels(ctx, res.rows).map((t, i) => `${t}<br>cluster ${nameOf(f.labels[i], f.k, out)}, p = ${f.pmax[i].toFixed(3)}`);
    const traces = [{ type: n > 5000 && SM.report.hasWebGL() ? 'scattergl' : 'scatter', mode: 'markers', x, y, rows: res.rows, marker: { size: n > 2000 ? 3.5 : 5, color: colors }, hovertext: hover, hovertemplate: '%{hovertext}<extra></extra>', showlegend: false, name: 'rows' }];
    for (let c = 0; c < f.k; c++) {
      const mu = f.pc_means[c], C = f.pc_covs[c];
      if (ctx.opt('ellipses', true, sc)) {
        const e = ellipse(mu[0], mu[1], C[0][0], C[0][1], C[1][1], level);
        traces.push({ type: 'scatter', mode: 'lines', x: e.x, y: e.y, line: { color: colorOf(c, f.k, out), width: 1.2 }, fill: 'toself', fillcolor: `${colorOf(c, f.k, out)}1f`, hoverinfo: 'skip', showlegend: false });
      }
      traces.push({ type: 'scatter', mode: 'markers+text', x: [mu[0]], y: [mu[1]], text: [String(c + 1)], textposition: 'middle center', textfont: { size: 10, color: tc.text },
        marker: { size: 11 + 20 * Math.sqrt(f.weights[c]), color: 'rgba(0,0,0,0)', line: { color: colorOf(c, f.k, out), width: 2 } }, name: `Cluster ${c + 1}`, hovertemplate: `cluster ${c + 1}: proportion ${f.weights[c].toFixed(3)}<extra></extra>`, showlegend: true });
    }
    if (out) traces.push({ type: 'scatter', mode: 'markers', x: [null], y: [null], marker: { size: 8, color: colorOf(f.k, f.k, true) }, name: 'Outlier', showlegend: true, hoverinfo: 'skip' });
    if (ctx.opt('rays', true, sc)) {
      let smax = 0;
      for (let i = 0; i < n; i++) smax = Math.max(smax, Math.abs(x[i]), Math.abs(y[i]));
      const V = P.vectors;
      let lmax = 0;
      cols.forEach((_, j) => { lmax = Math.max(lmax, Math.abs(V[j][0]), Math.abs(V[j][1])); });
      const s = lmax > 0 ? (0.8 * smax) / lmax : 1;
      const rx = [], ry = [];
      cols.forEach((_, j) => { rx.push(0, s * V[j][0], null); ry.push(0, s * V[j][1], null); });
      traces.push({ type: 'scatter', mode: 'lines', x: rx, y: ry, line: { color: tc.muted, width: 1 }, hoverinfo: 'skip', showlegend: false });
      traces.push({ type: 'scatter', mode: 'text', x: cols.map((_, j) => s * V[j][0]), y: cols.map((_, j) => s * V[j][1]), text: cols.map((c) => T(c.name)), textfont: { size: 10, color: tc.text }, hoverinfo: 'skip', showlegend: false });
    }
    const ev = P.eigenvalues;
    const tot = ev.reduce((acc, v) => acc + Math.max(v, 0), 0) || 1;
    const room = roomOf(ctx);
    const W = Math.min(600, room);
    sub.add(ctx.row(withCode(ctx.plot(traces, { showlegend: true, legend: room < 520 ? { orientation: 'h', x: 0, y: 1.02, yanchor: 'bottom' } : { orientation: 'v', x: 1.02, y: 1 }, xaxis: { title: { text: `Prin1 (${(100 * ev[0] / tot).toFixed(1)}%)` }, zeroline: true }, yaxis: { title: { text: `Prin2 (${(100 * ev[1] / tot).toFixed(1)}%)` }, zeroline: true }, margin: { l: 56, r: room < 520 ? 12 : 110, t: room < 520 ? 30 : 8, b: 42 } },
      { width: W, height: 440, title: `Biplot, ${f.k} clusters`, rowColors: false }),
    ctx.code(biplotCode(S, f, { level, showEll: ctx.opt('ellipses', true, sc), rays: ctx.opt('rays', true, sc), W, msize: n > 2000 ? 3.5 : 5, legendRight: room >= 520, title: `Biplot, ${f.k} clusters` })))),
    ctx.note(`The rows on the first two principal components of the ${res.standardize ? 'standardized columns (their correlations)' : 'columns (their covariances)'}, in the colour of their most likely cluster; each cluster's ${fmt(100 * level)}% normal ellipse is its fitted mean and covariance carried onto the same two components, and its centre's circle grows with its proportion. The rays are the columns' loadings.`));
  }

  /* ======================================================================
     THE TOP RED TRIANGLE
     ====================================================================== */
  function topMenu(ctx) {
    return [
      ctx.check('Iterative Clustering', 'control', null, true),
      ctx.check('Cluster Comparison', 'comparison', null, true),
      { separator: true },
      ctx.check('Color Clusters', 'colorClusters', null, false),
      ctx.check('Mark Clusters', 'markClusters', null, false),
      { separator: true },
      { label: 'Covariance Structure', submenu: () => COVS.map(([v, l]) => ({ label: l, checked: ctx.opt('covariance', 'full') === v, action: () => { ctx.set('open', null, null, { rerun: false }); ctx.set('covariance', v); } })) },
      ctx.check('Outlier Cluster', 'outlier', null, false),
      ctx.check('Columns Scaled Individually', 'scaled', null, true),
      { label: 'Best By', submenu: () => [['bic', 'BIC'], ['aicc', 'AICc']].map(([v, l]) => ({ label: l, checked: ctx.opt('choose', 'bic') === v, action: () => { ctx.set('open', null, null, { rerun: false }); ctx.set('choose', v); } })) },
    ];
  }

  /* ======================================================================
     THE LAUNCH'S ROLES AND OPTIONS, with what each is for (the (i))
     ====================================================================== */
  const HELP = {
    k: 'How many normal clusters to fit, from 1 to 50 (3); with a Range of Clusters, the smallest number fitted.',
    kRange: 'Fits every number of clusters from Number of Clusters up to this one (at most 19 more) and compares them in Cluster Comparison by BIC (or AICc), the best one opened. Empty: Number of Clusters only.',
    tours: 'How many times EM starts, each from the labels of its own k-means run, from 1 to 100 (10); the tour with the largest likelihood is kept. More tours are safer against a poor local fit, and take longer.',
    covariance: 'The shape the clusters may take. Full (the default, JMP\'s normal mixtures): a covariance matrix for each cluster, so clusters may differ in size, shape and orientation. Diagonal: a variance for each column in each cluster and no correlations (JMP\'s Diagonal Variance, as far as its documentation says). Tied: one covariance matrix shared by every cluster. Spherical: one variance for each cluster, the same in every column (on the scaled columns when they are scaled). Tied and Spherical are scikit-learn\'s, not JMP options; fewer parameters need fewer rows.',
    outlier: 'Adds JMP\'s outlier cluster: one more cluster, uniform over the box that holds the rows, which takes the rows that no normal cluster explains, so that they do not pull the normal clusters toward them. Off by default.',
    scaled: 'On (the default): the fit is on each column scaled to standard deviation 1, so that no column dominates by its units; the means, standard deviations and log likelihoods are reported in the columns\' own units. Off: the columns as they are.',
    seed: 'The seed of the k-means starts of the tours. Empty: a seed drawn at the first run and kept with the report, so that Redo, a project and the Python code give the same clusters.',
  };
  const OPTIONS = [
    { key: 'k', label: 'Number of Clusters', type: 'number', value: 3, help: HELP.k },
    { key: 'kRange', label: 'Range of Clusters (optional)', type: 'number', value: null, hint: 'fit every number from Number of Clusters up to this one (at most 19 more)', help: HELP.kRange },
    { key: 'tours', label: 'Tours', type: 'number', value: 10, hint: 'starts of the EM, each from its own k-means run', help: HELP.tours },
    { key: 'covariance', label: 'Covariance Structure', type: 'select', value: 'full', choices: COVS, help: HELP.covariance },
    { key: 'outlier', label: 'Outlier Cluster', type: 'check', value: false, help: HELP.outlier },
    { key: 'scaled', label: 'Columns Scaled Individually', type: 'check', value: true, help: HELP.scaled },
    { key: 'seed', label: 'Random Seed', type: 'text', value: '', hint: 'empty: a seed drawn now and kept with the report', help: HELP.seed },
  ];

  /* ======================================================================
     TOPICS: the (i) panels
     ====================================================================== */
  const TOPICS = {
    'p:mixtures': {
      kicker: 'Analyze > Clustering', title: 'Normal Mixtures',
      lead: 'Clusters as a mixture of multivariate normal distributions: each cluster has a mean, a covariance and a proportion, and every row a probability of belonging to each cluster, from which it goes to its most likely one. Clusters may overlap and differ in size, shape and orientation, which k-means does not allow. Fitted by EM with scikit-learn\'s GaussianMixture.',
      sections: [
        { heading: 'Roles', choices: [['Y, Columns', 'The continuous columns to cluster the rows by; rows with a missing value are left out.'], ['Freq', 'A count per row: the row stands for that many observations (fractions are rounded down).'], ['By', 'A separate analysis for each level.']] },
        // the launch's options, as the Iterative Clustering panel and the red triangle have them too
        { heading: 'Options', choices: OPTIONS.map((o) => [o.label, o.help]) },
        { heading: 'How the outlier cluster is fitted', text: 'scikit-learn has no uniform component, so with the Outlier Cluster the EM is the page\'s own (numpy, shown in the Python code): the normal clusters start from the same k-means labels as GaussianMixture, the uniform one with 5% of the rows. Without the uniform cluster that EM gives scikit-learn\'s fit (the tests check it).' },
        { heading: 'Starts and seeds', text: 'Each tour starts EM from the labels of one k-means run (scikit-learn\'s init_params="kmeans"); all tours draw from one random state seeded by Random Seed, and the tour with the largest likelihood is kept. The seed is kept with the report, so Redo and the Python code give the same fit. JMP chooses its starts its own way, so its clusters can differ.' },
        { heading: 'Saved columns', text: 'Save Clusters and Save Mixture Probabilities give every row of the group whose columns are present its most likely cluster and its probabilities, from the report\'s fit: the rows the fit left out (excluded, filtered, a Freq below 1) too. Save Mixture Formulas makes JMP\'s live formula columns: Dist Formula <k> (the share times the normal density of cluster k), Dist Total (their sum), Prob Formula <k> (the one over the other) and, beyond JMP, Cluster Formula, the most likely cluster; a row whose densities all underflow (far from every cluster) gets missing probabilities from the formulas, as in JMP, but its Cluster Formula still has a value.' },
        { heading: 'Differences from JMP', text: 'JMP\'s defaults for Tours, iterations and the convergence criterion are not known here; this page uses 10 tours, at most 500 iterations and a change below 1e-6 in the mean log likelihood of a row. The number of parameters counts the means, the covariance parameters of the structure and the proportions, as scikit-learn does; JMP may count them otherwise. Johnson transforms, Robust Normal Mixtures, Save Density Formula and Simulate Clusters are not here.' },
      ],
      more: MORE,
    },
    'mix:control': {
      kicker: 'Normal Mixtures', title: 'Iterative Clustering',
      lead: 'The settings of the fit, as JMP\'s Iterative Clustering panel has them; Go fits again with them (Enter in a number box does too), and the report keeps them.',
      sections: [{ choices: [
        ['Number of Clusters', HELP.k],
        ['Range of Clusters (Optional)', HELP.kRange],
        ['Tours', HELP.tours],
        ['Covariance', HELP.covariance],
        ['Outlier Cluster', HELP.outlier],
        ['Columns Scaled Individually', HELP.scaled],
        ['Maximum Iterations', 'The most EM iterations of each tour, from 1 to 10000 (500). A fit that reaches it without meeting the Converge Criteria is marked not converged.'],
        ['Converge Criteria', 'EM stops when the mean log likelihood of a row improves by less than this, a positive number (1e-6, scikit-learn\'s tol); a larger value stops sooner, with a rougher fit.'],
        ['Random Seed', 'The seed of the k-means starts of the tours, a whole number; empty: the report\'s own, shown in grey.'],
        ['Go', 'Fits the mixture again with these settings and opens the best fit.'],
      ] }],
      more: MORE,
    },
    'mix:comparison': {
      kicker: 'Normal Mixtures', title: 'Cluster Comparison',
      lead: 'Each number of clusters with −2 log likelihood (of the fitted mixture, in the columns\' units), the number of parameters q, AICc = −2 log L + 2q + 2q(q + 1)/(N − q − 1) and BIC = −2 log L + q ln N. The smallest BIC (or AICc: Best By, red triangle) is marked; a click on a line opens that fit.',
      sections: [
        { heading: 'Which criterion', text: 'BIC penalises parameters more and is the usual choice for mixtures; AICc tends to take more clusters. With overlapping or non-normal clusters both can ask for more clusters than there are groups.' },
        { heading: 'Clicking', choices: [['A line', 'Opens that number of clusters\' report below and closes the others; Color Clusters and Mark Clusters then follow it.']] },
      ],
      more: MORE,
    },
    'mix:fit': {
      kicker: 'Normal Mixtures', title: 'One fit',
      lead: 'The fit for one number of clusters. Cluster Summary: the rows most likely in each cluster (Count, counted by Freq) and the mixing proportion, the model\'s share of the rows. Cluster Means and Cluster Standard Deviations: each cluster\'s fitted normal distribution, in the columns\' units. Click a line of the summary, or a cluster below it, to select its rows.',
      sections: [
        { heading: 'Clicking', choices: [['A line of Cluster Summary', 'Selects the rows most likely in that cluster; Shift adds them to the selection.'], ['A cluster under the tables', 'The same: each button is a cluster\'s colour and count.']] },
        { heading: 'The red triangle', text: 'The graphs, the clusters\' correlations and the profiler of the cluster probabilities; Save Clusters (the most likely cluster of each row), Save Mixture Probabilities (a column for each cluster), Save Mixture Formulas (the densities and probabilities as live formulas), Save Colors and Markers to Table.' },
      ],
      more: MORE,
    },
    'mix:splom': { kicker: 'Normal Mixtures', title: 'Scatterplot Matrix', lead: 'Every pair of columns with the rows in the colour of their most likely cluster, and each cluster\'s normal ellipse (its fitted mean and covariance for the pair) holding 90% of it (Ellipse Coverage, red triangle). With one column, the histogram with each cluster\'s density. Drag over points to select rows; rows selected elsewhere are highlighted.', more: MORE },
    'mix:biplot': { kicker: 'Normal Mixtures', title: 'Biplot', lead: 'For three or more columns: the rows on the first two principal components (of the correlations when the columns are scaled), each cluster\'s fitted normal distribution carried onto them as an ellipse, circles at the centres growing with the proportions, and rays for the columns.', more: MORE },
  };

  /* ======================================================================
     THE PLATFORM
     ====================================================================== */
  SM.platforms.register({
    id: 'mixtures', label: 'Normal Mixtures', menu: 'Analyze/Clustering', order: 30, info: 'p:mixtures', topics: TOPICS,
    about: 'Clusters as a mixture of multivariate normal distributions fitted by EM, for one number of clusters or a range compared by −2 log likelihood, AICc and BIC; full, diagonal, tied or spherical covariances, tours from seeded k-means starts, JMP\'s outlier cluster (a uniform component); cluster summaries, means, standard deviations and correlations, a scatterplot matrix with each cluster\'s ellipses, a biplot, the profiler of the cluster probabilities, saved clusters and mixture probabilities for every row, JMP\'s mixture formulas (densities and probabilities as live formula columns) and a cluster formula, cluster colours and markers.',
    uses: ['sklearn.mixture.GaussianMixture', 'sklearn.cluster.KMeans (the starts of the outlier cluster\'s EM)', 'numpy, scipy.linalg, scipy.special.logsumexp (the EM with the outlier cluster)'],
    launch: {
      lead: 'Choose the continuous columns to cluster the rows by. Number of Clusters and an optional range choose what is fitted; the report\'s Iterative Clustering panel changes them.',
      roles: [
        { key: 'y', label: 'Y, Columns', min: 1, numeric: true, types: ['continuous'], hint: 'required: continuous',
          help: 'The continuous columns the rows are clustered by: each cluster is a multivariate normal distribution over them. Rows with a missing value in any of them are left out, and a column with one value cannot cluster.' },
        { key: 'freq', label: 'Freq', max: 1, numeric: true, types: ['continuous'], hint: 'optional: row counts',
          help: 'Optional: a count per row, which then stands for that many observations in the fit, the counts and the criteria. Fractions are rounded down; rows with a count below 1 are left out.' },
        { key: 'by', label: 'By', hint: 'optional', help: 'A separate clustering and report for each level of the By column (each combination of levels, with several). Rows with a missing By value are left out.' },
      ],
      options: OPTIONS,
      validate: (spec) => {
        const o = spec.options || {};
        if (o.k != null && !(o.k >= 1 && o.k <= 50)) return 'Number of Clusters: from 1 to 50';
        if (o.tours != null && !(o.tours >= 1 && o.tours <= 100)) return 'Tours: from 1 to 100';
        if (o.seed != null && String(o.seed).trim() !== '' && !Number.isFinite(Number(o.seed))) return 'Random Seed: a whole number, or empty';
        return null;
      },
    },
    title: () => 'Normal Mixtures',
    triangle: topMenu,
    render,
  });

  /* ---- the example: fish of three ages, simulated -------------------------------------------- */
  SM.io.addExample('fishages', {
    label: 'Fish ages (540 rows): length, girth, weight',
    about: 'Simulated: 540 fish caught in two lakes, measured for length (cm), girth (cm) and weight (g). They are of three ages, in the shares 0.5, 0.3 and 0.2: length normal with mean 12, 19 and 26 cm and standard deviation 1.5, 2 and 2.5; girth 0.55 × length plus normal noise (sd 0.6 cm); weight 0.011 × length³ times a lognormal factor (sd 0.08 on the log scale). Age (true) holds the age each fish was drawn from. Twelve rows are recording errors, drawn uniformly over the ranges of the three measurements. For Normal Mixtures (Analyze > Clustering), with or without the Outlier Cluster.',
    make() {
      const r = SM.util.rng('normal-mixtures-fish');
      const c = { lake: [], age: [], length: [], girth: [], weight: [] };
      const ages = [[12, 1.5], [19, 2], [26, 2.5]];
      const n = 528;
      for (let i = 0; i < n; i++) {
        const u = r.u();
        const a = u < 0.5 ? 0 : u < 0.8 ? 1 : 2;
        const len = ages[a][0] + ages[a][1] * r.normal();
        c.lake.push(r.u() < 0.55 ? 'North' : 'South');
        c.age.push(a + 1);
        c.length.push(+len.toFixed(1));
        c.girth.push(+(0.55 * len + 0.6 * r.normal()).toFixed(1));
        c.weight.push(+(0.011 * len ** 3 * Math.exp(0.08 * r.normal())).toFixed(1));
      }
      let [l0, l1, g0, g1, w0, w1] = [Infinity, -Infinity, Infinity, -Infinity, Infinity, -Infinity];
      for (let i = 0; i < n; i++) { l0 = Math.min(l0, c.length[i]); l1 = Math.max(l1, c.length[i]); g0 = Math.min(g0, c.girth[i]); g1 = Math.max(g1, c.girth[i]); w0 = Math.min(w0, c.weight[i]); w1 = Math.max(w1, c.weight[i]); }
      for (let i = 0; i < 12; i++) {
        c.lake.push(r.u() < 0.55 ? 'North' : 'South');
        c.age.push(NaN);
        c.length.push(+(l0 + (l1 - l0) * r.u()).toFixed(1));
        c.girth.push(+(g0 + (g1 - g0) * r.u()).toFixed(1));
        c.weight.push(+(w0 + (w1 - w0) * r.u()).toFixed(1));
      }
      // the errors among the others, not all at the end
      const order = Array.from({ length: n + 12 }, (_, i) => i);
      for (let i = order.length - 1; i > 0; i--) { const j = Math.floor(r.u() * (i + 1)); [order[i], order[j]] = [order[j], order[i]]; }
      const pick = (a) => order.map((i) => a[i]);
      return new SM.Table({ name: 'Fish ages', source: 'simulated', columns: [
        { name: 'lake', dataType: 'character', values: pick(c.lake) },
        { name: 'length (cm)', dataType: 'numeric', values: pick(c.length) },
        { name: 'girth (cm)', dataType: 'numeric', values: pick(c.girth) },
        { name: 'weight (g)', dataType: 'numeric', values: pick(c.weight) },
        { name: 'age (true)', dataType: 'numeric', modelingType: 'nominal', values: pick(c.age) },
      ] });
    },
  });
}(typeof self !== 'undefined' ? self : this));
