/* ==========================================================================
   SMUI.HTML: THE TABLES MENU, TABULATE, THE COLS UTILITIES,
   EXPLORE MISSING VALUES AND THE PYTHON SCRIPT WINDOW

   Tables (each makes a new table, as JMP's do, unless it says otherwise):
     Summary          group statistics; the summary is linked: selecting a
                      summary row selects its rows in the source table
     Subset           selected rows, a random sample (seeded, stratified) or
                      all rows; some columns; one table per level of Subset By
     Sort             by several columns, each ascending or descending; a new
                      table or the same one
     Stack, Split, Transpose, Concatenate, Join, Update
     Missing Data Pattern   the patterns of missing values, linked
   Analyze > Tabulate          JMP's interactive table builder
   Cols > Formula…             the formula editor (smui-formula.js)
   Cols > New Formula Column   transforms as formula columns (also in a
                               column's right-click menu)
   Cols > Recode…              new values for the distinct values
   Cols > Columns Viewer       every column's summary, and Distribution
   Cols > Utilities            Make Indicator Columns, Make Binning Column,
                               Standardize
   Analyze > Screening > Explore Missing Values   reports, snapshot, imputation
   File > Python Script…       Python against the table as a DataFrame

   The statistics are pandas and numpy in the engine (smui/tables.py);
   Subset, Sort, Concatenate, Recode and the formula transforms are done
   here. Everything is built with SM.util.el: text nodes only.
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM;
  const { el, fmt, typeIcon, TYPE_LABEL } = SM.util;
  const { isMissing } = SM.table;

  /* ---- shared pieces --------------------------------------------------------------- */
  const cellText = (c, v) => (isMissing(v) ? (c && c.isNumeric ? '.' : '') : SM.grid.cellText(c, v));
  const refOf = (name) => (SM.formula ? SM.formula.refText(name) : `:"${name}"`);
  const quote = (s) => `"${String(s).replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`;
  const numLit = (v) => (Number.isFinite(v) ? String(v) : '.');
  const uniqueTable = (base) => (SM.app ? SM.app.uniqueTableName(base) : base);
  const record = (t, label) => { if (SM.app && SM.app.record) SM.app.record(t, label); };
  const toast = (text, opts) => SM.ui.toast(text, opts);
  const infoSlot = (key) => (typeof KvotInfo !== 'undefined' ? KvotInfo.slot(key) : null);

  let pointer = { x: 160, y: 120 };
  if (typeof document !== 'undefined') {
    const keep = (ev) => { pointer = { x: ev.clientX, y: ev.clientY }; };
    document.addEventListener('pointerdown', keep, true);
    document.addEventListener('contextmenu', keep, true);
  }

  /* A column's properties, for a copy of it in another table. */
  function specOf(c, values, { formula = null } = {}) {
    return {
      name: c.name, dataType: c.dataType, modelingType: c.modelingType, format: c.format ? { ...c.format } : null,
      valueOrder: c.valueOrder ? c.valueOrder.slice() : null, formula, notes: c.notes, role: c.role,
      specLimits: c.specLimits ? { ...c.specLimits } : null, values,
    };
  }

  /* Some rows and columns of a table as a new table; formulas come along
     when every column they use does, and row states when asked for. */
  function copyTable(t, rows, cols, { name, keepStates = true, formulas = true } = {}) {
    const ids = new Set(cols.map((c) => c.id));
    const specs = cols.map((c) => {
      let formula = null;
      if (formulas && c.formula && (c.formula.refs || []).every((id) => ids.has(id))) formula = JSON.parse(JSON.stringify(c.formula));
      return specOf(c, rows.map((r) => c.values[r]), { formula });
    });
    const nt = new SM.Table({ name, columns: specs, notes: t.notes, source: `from ${t.name}` });
    if (keepStates) for (let k = 0; k < rows.length; k++) { nt.state[k] = t.state[rows[k]]; nt.color[k] = t.color[rows[k]]; nt.marker[k] = t.marker[rows[k]]; }
    return nt;
  }

  /* The engine's columns as a new table. A column that names a source keeps
     that column's modeling type, value order and format. */
  function fromBackend(res, { name, sources = [], source = '', notes = '' }) {
    const columns = res.columns.map((c) => {
      const numeric = c.dataType === 'numeric';
      const values = numeric ? c.values.map((v) => (v == null ? NaN : v)) : c.values.map((v) => (v == null ? null : String(v)));
      const spec = { name: c.name, dataType: c.dataType, values };
      const from = c.side === 'right' ? sources[1] : sources[0];
      const src = c.source && from ? from.col(c.source) : null;
      if (src && src.dataType === c.dataType) {
        if (c.role === 'stat') { if (src.format && /date/.test(src.format.kind || '')) spec.format = { ...src.format }; }
        else Object.assign(spec, specOf(src, values), { name: c.name, formula: null, role: null });
      }
      if (c.levels && !numeric) { spec.valueOrder = c.levels.map(String); spec.modelingType = spec.modelingType && spec.modelingType !== 'continuous' ? spec.modelingType : (c.modelingType || 'nominal'); }
      if (c.modelingType && !spec.modelingType) spec.modelingType = c.modelingType;
      if (c.format && !spec.format) spec.format = c.format;
      return spec;
    });
    return new SM.Table({ name, columns, source, notes });
  }

  async function engine(fn, payload, table, others = []) {
    if (SM.engine.state !== 'ready') toast('Waiting for the Python engine to load…');
    for (const o of others) await SM.engine.call('data.status', {}, o);
    return SM.engine.call(fn, payload, table);
  }

  const fail = (what) => (e) => { console.error(e); toast(`${what}: ${e.message || e}`, { error: true }); };

  /* A launch dialog (the core's), for a Tables command. */
  function cast(t, { id, title, info, lead, roles, options = [], extra = null, validate = null }, onOK) {
    const platform = { id: `tables-${id}`, label: title, info, launch: { lead, roles, options, extra, validate } };
    const dlg = SM.launch.open({ platform, table: t, onOK });
    if (dlg && dlg.el) dlg.el.classList.add('smt-cast');   // room for the longer role names
    return dlg;
  }

  const idsOf = (t, list) => (list || []).map((id) => t.col(id)).filter(Boolean);
  const namesOf = (t, list) => idsOf(t, list).map((c) => c.name);

  /* Selecting rows of a derived table selects the source rows with the same
     key: summary rows and their groups, patterns and their rows. The keys are
     worked out when needed, so sorting either table keeps the link. */
  function linkRows(derived, source, keyOfDerived, keyOfSource) {
    let index = null;
    const reset = () => { index = null; };
    source.on('data', reset);
    derived.on('data', reset);
    derived.on('rowstate', (e) => {
      if (!e || e.kind !== 'selected') return;
      if (!SM.app || !SM.app.tables.includes(source)) return;
      if (!index) {
        index = new Map();
        for (let i = 0; i < source.nrows; i++) {
          const k = keyOfSource(i);
          if (k == null) continue;
          let list = index.get(k);
          if (!list) index.set(k, (list = []));
          list.push(i);
        }
      }
      const rows = [];
      for (const r of derived.selectedRows()) { const k = keyOfDerived(r); if (k != null) for (const i of index.get(k) || []) rows.push(i); }
      source.select(rows.sort((a, b) => a - b));
    });
  }

  const keyPart = (v) => (typeof v === 'number' ? (Number.isNaN(v) ? 'm' : `n${v}`) : v == null || v === '' ? 'm' : `s${v}`);

  function show(t, code = null) {
    if (code) t.notes = `${t.notes ? `${t.notes}\n\n` : ''}The same with pandas, from a CSV export of the source table:\n${code}`;
    SM.app.addTable(t);
    return t;
  }

  /* ---- Tables > Summary ------------------------------------------------------------- */
  const SUMMARY_STATS = ['N', 'Mean', 'Std Dev', 'Min', 'Max', 'Range', 'Sum', 'Median', 'Quantiles', 'N Missing', 'N Categories', '% of Total', 'CV', 'Std Err', 'Variance', 'Geometric Mean', 'Interquartile Range', 'Mode'];
  // What each statistic is, for the (i) of Summary's dialog (tables.py computes them).
  const SUMMARY_STAT_HELP = [
    ['N', 'The number of values that are not missing (with Freq, the sum of the counts).'],
    ['Mean', 'The average; with Weight or Freq, the weighted average.'],
    ['Std Dev', 'The standard deviation, with n − 1 in the denominator (weighted as statsmodels\' DescrStatsW weights it).'],
    ['Min, Max', 'The smallest and the largest value.'],
    ['Range', 'The largest value minus the smallest (Max − Min).'],
    ['Sum', 'The total of the values (with Weight or Freq, each times them).'],
    ['Median', 'The middle value, by JMP\'s quantile definition (the (n + 1)p-th value in order, interpolated); with Weight, DescrStatsW\'s weighted median.'],
    ['Quantiles', 'The quantiles at the percents in Quantiles (%), JMP\'s definition: a column for each percent.'],
    ['N Missing', 'The number of rows where the column is missing.'],
    ['N Categories', 'The number of distinct values.'],
    ['% of Total', 'The group\'s share of the column\'s sum over the whole table (for a character column, of its count), in percent.'],
    ['CV', 'The coefficient of variation: 100 × Std Dev / Mean.'],
    ['Std Err', 'The standard error of the mean: Std Dev / √N.'],
    ['Variance', 'The standard deviation squared.'],
    ['Geometric Mean', 'The exponential of the mean log; missing unless every value is positive.'],
    ['Interquartile Range', 'The third quartile minus the first.'],
    ['Mode', 'The most common value (of values tied, the smallest, or the first in alphabetical order); Weight and Freq do not count here.'],
  ];

  function statsPicker(defaults, title = 'Statistics') {
    const chosen = new Set(defaults);
    const boxes = new Map();
    const grid = el('div', { class: 'smt-statgrid', role: 'group', 'aria-label': title });
    for (const s of SUMMARY_STATS) {
      const cb = el('input', { type: 'checkbox' });
      cb.checked = chosen.has(s);
      cb.addEventListener('change', () => { if (cb.checked) chosen.add(s); else chosen.delete(s); });
      boxes.set(s, cb);
      grid.append(el('label', { class: 'smt-stat' }, cb, s));
    }
    return {
      el: el('div', { class: 'smt-extra' }, el('h4', { text: title }), grid),
      get: () => SUMMARY_STATS.filter((s) => chosen.has(s)),
      set: (list) => { chosen.clear(); for (const s of list || []) chosen.add(s); for (const [s, cb] of boxes) cb.checked = chosen.has(s); },
    };
  }

  function summaryCommand(app) {
    const t = app.requireTable();
    if (!t) return;
    cast(t, {
      id: 'summary', title: 'Summary', info: 'cmd:summary',
      lead: 'A new table with a row for each group: N Rows and the statistics of the Statistics Columns. Selecting a summary row selects its rows in this table.',
      roles: [
        { key: 'cols', label: 'Statistics Columns', hint: 'the columns to summarize', help: 'The columns to summarize: the new table has a column for each ticked statistic of each of them. Character columns take only N, N Missing, N Categories, % of Total and Mode.' },
        { key: 'group', label: 'Group', hint: 'optional: a row per level', help: 'A row of the new table for each level of these columns (each combination of levels with several), in value order; a missing value makes a group of its own. Without Group, one row for the whole table.' },
        { key: 'subgroup', label: 'Subgroup', hint: 'optional: side by side', help: 'Columns whose levels go side by side instead of down: each statistic gets a column for each level, Mean(height, F) and Mean(height, M).' },
        { key: 'weight', label: 'Weight', max: 1, numeric: true, types: ['continuous'], hint: 'optional numeric', help: 'Weights the Mean, Sum, % of Total, Std Dev, Variance, Std Err, CV, Geometric Mean and the quantiles, as statsmodels\' DescrStatsW does (the same as Distribution); rows with a missing, zero or negative weight are left out.' },
        { key: 'freq', label: 'Freq', max: 1, numeric: true, types: ['continuous'], hint: 'optional numeric', help: 'A count for each row: N adds them up and the row counts that many times in the statistics; rows with a missing, zero or negative count are left out. N Rows still counts the rows themselves.' },
      ],
      options: [
        { key: 'quantiles', label: 'Quantiles (%)', type: 'text', value: '25, 75', size: 10, help: 'The percents for the Quantiles statistic, separated by commas (default 25, 75): a column Quantiles25(x) and so on for each. Numbers outside 0 to 100 are dropped.' },
        { key: 'format', label: 'Statistics column names', type: 'select', value: 'stat(column)', choices: [['stat(column)', 'stat(column)'], ['column', 'column'], ['stat of column', 'stat of column'], ['column stat', 'column stat']], help: 'How the new columns are named: stat(column) gives Mean(height) (the default), column just height (best with one statistic, as the names would repeat), stat of column Mean of height, column stat height Mean. A Subgroup level is added after a comma.' },
        { key: 'link', label: 'Link to original data table', type: 'check', value: true, help: 'On (the default): selecting rows of the summary selects their groups\' rows in this table. Off: the two tables are not linked.' },
        { key: 'included', label: 'Leave out excluded rows', type: 'check', value: false, help: 'Summarizes the included rows only. Off (the default): every row counts, excluded or not.' },
        { key: 'name', label: 'Output table name', type: 'text', value: '', size: 18, help: 'The new table\'s name; empty: this table\'s name and By (the Group columns), or Summary without Group.' },
      ],
      extra: (api, spec) => {
        const p = statsPicker(['Mean']);
        return { el: p.el, read: () => ({ options: { stats: p.get() } }), recall: (s) => p.set((s && s.options && s.options.stats) || ['Mean']), helpHeading: 'Each statistic', help: SUMMARY_STAT_HELP };
      },
      validate: (s) => (!s.roles.group.length && !s.roles.cols.length ? 'Choose Group columns, Statistics Columns, or both' : (s.roles.cols.length && !(s.options.stats || []).length ? 'Tick at least one statistic' : null)),
    }, (s) => runSummary(app, t, s).catch(fail('Summary')));
  }

  async function runSummary(app, t, s) {
    const group = idsOf(t, s.roles.group), cols = idsOf(t, s.roles.cols);
    const quantiles = String(s.options.quantiles || '').split(/[,;\s]+/).map(Number).filter((p) => p >= 0 && p <= 100);
    const rows = s.options.included ? t.includedRows() : null;
    const res = await engine('tables.summary', {
      group: group.map((c) => c.name), columns: cols.map((c) => c.name), stats: s.options.stats || [], subgroup: namesOf(t, s.roles.subgroup),
      weight: namesOf(t, s.roles.weight)[0] || null, freq: namesOf(t, s.roles.freq)[0] || null, quantiles: quantiles.length ? quantiles : [25, 75],
      name_format: s.options.format || 'stat(column)', rows,
    }, t);
    const name = (s.options.name || '').trim() || uniqueTable(group.length ? `${t.name} By (${group.map((c) => c.name).join(', ')})` : `${t.name} Summary`);
    const nt = fromBackend(res, { name, sources: [t], source: `Tables > Summary of ${t.name}` });
    nt.notes = `Summary of ${t.name}${group.length ? ` by ${group.map((c) => c.name).join(', ')}` : ''}. Quantiles as JMP computes them (numpy's weibull).`;
    if (s.options.link !== false) {
      const pairs = res.columns.map((c, k) => [c, k]).filter(([c]) => c.role === 'group').map(([c, k]) => [nt.columns[k], t.col(c.source)]);
      const included = !!s.options.included;
      linkRows(nt, t, (r) => pairs.map(([a]) => keyPart(a.values[r])).join('\u0001'),
        (i) => (included && t.has(i, 'excluded') ? null : pairs.map(([, b]) => keyPart(b ? b.values[i] : null)).join('\u0001')));
    }
    show(nt, res.code);
    SM.ui.toast(`${nt.name}: ${nt.nrows} rows${s.options.link !== false ? '; select a row to select its rows in ' + t.name : ''}`);
  }

  /* ---- Tables > Subset -------------------------------------------------------------- */
  function sample(rows, k, rng) {
    const a = rows.slice();
    for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(rng.u() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; }
    return a.slice(0, Math.max(0, Math.min(a.length, k))).sort((x, y) => x - y);
  }

  function subsetCommand(app) {
    const t = app.requireTable();
    if (!t) return;
    const nsel = t.counts().selected;
    cast(t, {
      id: 'subset', title: 'Subset', info: 'cmd:subset',
      lead: 'A new table of some rows and columns. Random samples are drawn from the seed, so the same seed gives the same rows.',
      roles: [
        { key: 'cols', label: 'Columns', hint: 'optional: all columns', help: 'The columns of the new table, in the order listed here; empty takes every column.' },
        { key: 'strata', label: 'Stratify', hint: 'optional: sample within each level', help: 'With a random sample: the rows are drawn within each level of these columns (each combination of levels), the rate or the size applying to each, so that every level is in the sample.' },
        { key: 'by', label: 'Subset By', hint: 'optional: a table per level', help: 'A separate new table for each level of these columns (each combination), named after it, with that level\'s rows of the subset.' },
      ],
      options: [
        { key: 'rows', label: 'Rows', type: 'select', value: nsel ? 'selected' : 'all', choices: [['all', 'All rows'], ['selected', `Selected rows (${nsel})`], ['rate', 'Random: sampling rate'], ['size', 'Random: sample size']], help: 'Which rows go into the new table: **All rows**; **Selected rows** (the default when rows are selected); **Random: sampling rate**, a share of the rows drawn at random; **Random: sample size**, a number of them. Random rows are drawn from every row, excluded ones too, and keep the table\'s order.' },
        { key: 'rate', label: 'Sampling rate', type: 'number', value: 0.5, help: 'With Random: sampling rate, the share of the rows to draw, above 0 and at most 1, rounded to whole rows (default 0.5, half of them); with Stratify, that share of each level.' },
        { key: 'size', label: 'Sample size', type: 'number', value: Math.min(10, t.nrows), help: 'With Random: sample size, how many rows to draw (every row when there are fewer); with Stratify, that many from each level.' },
        { key: 'seed', label: 'Seed', type: 'text', value: String(Math.floor(Math.random() * 1e6)), size: 8, help: 'Any number or text: the random rows are drawn from it, so the same seed on the same table and settings draws the same rows again. A new random seed is filled in each time the dialog opens.' },
        { key: 'states', label: 'Keep row states', type: 'check', value: true, help: 'On (the default): each row takes its state along, selected, excluded, hidden or labeled, with its colour and marker.' },
        { key: 'formula', label: 'Copy formula', type: 'check', value: true, help: 'On (the default): a formula column stays a formula when every column it uses comes along too (its Col functions then work over the subset\'s rows); otherwise, and when off, its values are copied as plain values.' },
        { key: 'suppress', label: 'Suppress formula evaluation', type: 'check', value: false, help: 'With Copy formula: the formula columns keep the values they have in this table, instead of being worked out again over the subset.' },
        { key: 'name', label: 'Output table name', type: 'text', value: '', size: 18, help: 'The new table\'s name; empty: Subset of and this table\'s name. With Subset By each table adds its level, (sex=F).' },
      ],
      validate: (s) => {
        if (s.options.rows === 'selected' && !t.counts().selected) return 'No rows are selected: choose All rows or a random sample';
        if (s.options.rows === 'rate' && !(s.options.rate > 0 && s.options.rate <= 1)) return 'The sampling rate is a number above 0 and at most 1';
        if (s.options.rows === 'size' && !(s.options.size >= 1)) return 'The sample size is at least 1';
        return null;
      },
    }, (s) => {
      try { runSubset(app, t, s); } catch (e) { fail('Subset')(e); }
    });
  }

  function groupRows(t, cols, rows) {
    if (!cols.length) return [{ key: null, rows }];
    const m = new Map();
    for (const r of rows) {
      const k = cols.map((c) => keyPart(c.values[r])).join('\u0001');
      if (!m.has(k)) m.set(k, { values: cols.map((c) => c.values[r]), rows: [] });
      m.get(k).rows.push(r);
    }
    // groups in the page's order: value order, missing last
    const order = cols.map((c) => { const lv = t.levels(c); return new Map(lv.map((v, i) => [v, i])); });
    return [...m.values()].sort((a, b) => {
      for (let k = 0; k < cols.length; k++) {
        const x = a.values[k], y = b.values[k];
        const ix = isMissing(x) ? Infinity : order[k].get(x), iy = isMissing(y) ? Infinity : order[k].get(y);
        if (ix !== iy) return ix < iy ? -1 : 1;
      }
      return 0;
    });
  }

  function runSubset(app, t, s) {
    const all = Array.from({ length: t.nrows }, (_, i) => i);
    let rows;
    const mode = s.options.rows;
    if (mode === 'selected') rows = t.selectedRows();
    else if (mode === 'rate' || mode === 'size') {
      const rng = SM.util.rng(`subset:${s.options.seed}`);
      const strata = idsOf(t, s.roles.strata);
      rows = [];
      for (const g of groupRows(t, strata, all)) {
        const k = mode === 'rate' ? Math.round(s.options.rate * g.rows.length) : Math.round(s.options.size);
        rows.push(...sample(g.rows, k, rng));
      }
      rows.sort((a, b) => a - b);
    } else rows = all;
    const cols = s.roles.cols.length ? idsOf(t, s.roles.cols) : t.columns.slice();
    const by = idsOf(t, s.roles.by);
    const base = (s.options.name || '').trim() || `Subset of ${t.name}`;
    const parts = by.length ? groupRows(t, by, rows) : [{ values: null, rows }];
    for (const g of parts) {
      const name = uniqueTable(g.values ? `${base} (${by.map((c, k) => `${c.name}=${cellText(c, g.values[k]) || '.'}`).join(', ')})` : base);
      const nt = copyTable(t, g.rows, cols, { name, keepStates: !!s.options.states, formulas: s.options.formula !== false });
      nt.source = `Tables > Subset of ${t.name}${mode === 'rate' || mode === 'size' ? `, seed ${s.options.seed}` : ''}`;
      if (s.options.suppress && SM.formula) SM.formula.suppressNextEvaluation(nt);
      show(nt);
    }
    toast(`${parts.length > 1 ? `${parts.length} tables` : 'A table'} of ${rows.length} rows`);
  }

  /* ---- Tables > Sort ----------------------------------------------------------------- */
  function sortCommand(app) {
    const t = app.requireTable();
    if (!t) return;
    cast(t, {
      id: 'sort', title: 'Sort', info: 'cmd:sort',
      lead: 'Sort by the By columns, the first one first. Click ▲ beside a By column to sort it descending (▼). Categorical columns sort in their value order; missing values go last.',
      roles: [{ key: 'by', label: 'By', min: 1, hint: 'required', help: 'The columns to sort by: the first sorts the rows, each next one breaks the ties of those before it, and rows tied on all of them keep their order. Numbers sort by value, nominal, ordinal and text columns in their value order; missing values go last.' }],
      options: [
        { key: 'replace', label: 'Replace table', type: 'check', value: false, help: 'Sorts this table itself instead of making a new one; Edit > Undo takes it back.' },
        { key: 'name', label: 'Output table name', type: 'text', value: '', size: 18, help: 'The new table\'s name; empty: this table\'s name and Sorted. Not used with Replace table.' },
      ],
      extra: (api) => {
        const desc = new Set();
        const box = el('p', { class: 'sm-ob-note smt-sortnote', text: '▲ ascending, ▼ descending: click the arrow of a By column to turn it.' });
        const decorate = (ul) => {
          for (const li of ul.querySelectorAll('li')) {
            if (li.querySelector('.smt-dir')) continue;
            const id = li.dataset.id;
            const b = el('button', { type: 'button', class: 'smt-dir', 'aria-pressed': String(desc.has(id)), 'aria-label': `Sort ${(t.col(id) || {}).name} descending`, text: desc.has(id) ? '▼' : '▲' });
            b.addEventListener('click', (ev) => { ev.stopPropagation(); if (desc.has(id)) desc.delete(id); else desc.add(id); b.textContent = desc.has(id) ? '▼' : '▲'; b.setAttribute('aria-pressed', String(desc.has(id))); });
            b.addEventListener('dblclick', (ev) => ev.stopPropagation());
            li.append(b);
          }
        };
        requestAnimationFrame(() => {
          const ul = box.closest('.sm-dialog') && box.closest('.sm-dialog').querySelector('.sm-role-list');
          if (!ul) return;
          new MutationObserver(() => decorate(ul)).observe(ul, { childList: true });
          decorate(ul);
        });
        return { el: box, read: () => ({ options: { desc: [...desc] } }), help: [['▲ ▼ beside a By column', 'The direction of that column: ▲ ascending (the default), ▼ descending; click the arrow to turn it. Missing values stay last either way.']] };
      },
    }, (s) => {
      const keys = s.roles.by.map((id) => ({ col: id, desc: (s.options.desc || []).includes(id) }));
      const label = `Sort by ${idsOf(t, s.roles.by).map((c) => c.name).join(', ')}`;
      if (s.options.replace) {
        record(t, label);
        t.sortBy(keys);
        app.showTab(app.tabOf(t));
        return;
      }
      const all = Array.from({ length: t.nrows }, (_, i) => i);
      const nt = copyTable(t, all, t.columns, { name: (s.options.name || '').trim() || uniqueTable(`${t.name} Sorted`), keepStates: true });
      nt.sortBy(keys.map((k) => ({ col: nt.columns[t.colIndex(k.col)].id, desc: k.desc })));
      nt.source = `Tables > Sort of ${t.name}`;
      show(nt);
    });
  }

  /* ---- Tables > Stack, Split, Transpose --------------------------------------------------- */
  function stackCommand(app) {
    const t = app.requireTable();
    if (!t) return;
    cast(t, {
      id: 'stack', title: 'Stack', info: 'cmd:stack',
      lead: 'Columns into rows: a Label column with the column names and a Data column with their values, one row per value; the other columns are repeated.',
      roles: [{ key: 'cols', label: 'Stack Columns', min: 1, hint: 'required', help: 'The columns whose values go into one column, a row for each value. When they are all numeric the Data column is numeric; otherwise it is text.' }, { key: 'keep', label: 'Keep Columns', hint: 'with Select only', help: 'With Non-stacked columns set to Select: the other columns to repeat on every row of the new table.' }],
      options: [
        { key: 'data', label: 'Stacked Data Column', type: 'text', value: 'Data', size: 10, help: 'The name of the new column of values (default Data).' },
        { key: 'label', label: 'Source Label Column', type: 'text', value: 'Label', size: 10, help: 'The name of the new column that says which column each value came from (default Label); it is nominal, its levels in the order of the Stack Columns.' },
        { key: 'id', label: 'ID column (row numbers; empty for none)', type: 'text', value: 'ID', size: 8, help: 'The name of a new column of the source row numbers (default ID), which Split needs to put the table back; empty leaves it out.' },
        { key: 'others', label: 'Non-stacked columns', type: 'select', value: 'all', choices: [['all', 'Keep All'], ['none', 'Drop All'], ['select', 'Select (Keep Columns)']], help: '**Keep All** (the default) repeats every other column on the rows of its row\'s values; **Drop All** leaves them out; **Select (Keep Columns)** keeps the columns in Keep Columns.' },
        { key: 'byRow', label: 'Stack by Row', type: 'check', value: true, help: 'On (the default): each row\'s values stay together, row 1\'s first, then row 2\'s; off: column by column, every value of the first column, then of the second.' },
        { key: 'dropMissing', label: 'Eliminate missing rows', type: 'check', value: false, help: 'Leaves out the new rows whose stacked value is missing.' },
        { key: 'name', label: 'Output table name', type: 'text', value: '', size: 18, help: 'The new table\'s name; empty: this table\'s name and Stacked.' },
      ],
    }, async (s) => {
      try {
        const cols = idsOf(t, s.roles.cols);
        const stacked = new Set(cols.map((c) => c.id));
        const keep = s.options.others === 'none' ? [] : s.options.others === 'select' ? idsOf(t, s.roles.keep) : t.columns.filter((c) => !stacked.has(c.id));
        const res = await engine('tables.stack', { columns: cols.map((c) => c.name), keep: keep.map((c) => c.name), data_name: s.options.data || 'Data', label_name: s.options.label || 'Label', id_name: (s.options.id || '').trim() || null, by_row: s.options.byRow !== false, drop_missing: !!s.options.dropMissing }, t);
        show(fromBackend(res, { name: (s.options.name || '').trim() || uniqueTable(`${t.name} Stacked`), sources: [t], source: `Tables > Stack of ${t.name}` }), res.code);
      } catch (e) { fail('Stack')(e); }
    });
  }

  function splitCommand(app) {
    const t = app.requireTable();
    if (!t) return;
    cast(t, {
      id: 'split', title: 'Split', info: 'cmd:split',
      lead: 'Rows into columns: a column for each level of Split By, holding the Split Columns\' values, one row per level of the Group columns (a level that repeats within a group starts another row).',
      roles: [{ key: 'cols', label: 'Split Columns', min: 1, hint: 'required', help: 'The columns whose values are spread out: each gets a new column for each level of Split By, named after the level (with several Split Columns, the column\'s name and the level).' }, { key: 'by', label: 'Split By', min: 1, max: 1, hint: 'required', help: 'The column whose levels become the new columns, in value order; rows where it is missing are left out.' }, { key: 'group', label: 'Group', hint: 'optional', help: 'A row of the new table for each level of these columns (each combination); a level of Split By that comes twice in a group starts a second row. Without Group, the first row of each level goes into row 1, the second into row 2, and so on.' }],
      options: [
        { key: 'others', label: 'Remaining columns', type: 'select', value: 'drop', choices: [['drop', 'Drop All'], ['keep', 'Keep All (first value of each row)']], help: '**Drop All** (the default) leaves the other columns out; **Keep All** keeps them, with the value of the first source row of each new row.' },
        { key: 'name', label: 'Output table name', type: 'text', value: '', size: 18, help: 'The new table\'s name; empty: this table\'s name and Split.' },
      ],
    }, async (s) => {
      try {
        const cols = idsOf(t, s.roles.cols), by = idsOf(t, s.roles.by)[0], group = idsOf(t, s.roles.group);
        const used = new Set([...cols, by, ...group].map((c) => c.id));
        const keep = s.options.others === 'keep' ? t.columns.filter((c) => !used.has(c.id)) : [];
        const res = await engine('tables.split', { split_by: by.name, columns: cols.map((c) => c.name), group: group.map((c) => c.name), keep: keep.map((c) => c.name) }, t);
        // Split By levels as the grid shows them (dates as dates)
        for (const c of res.columns) if (c.role === 'split' && c.level != null && by.isNumeric && by.format) {
          const lv = cellText(by, c.level);
          c.name = cols.length === 1 ? lv : `${c.split_column} ${lv}`;
        }
        const nt = fromBackend(res, { name: (s.options.name || '').trim() || uniqueTable(`${t.name} Split`), sources: [t], source: `Tables > Split of ${t.name} by ${by.name}` });
        show(nt, res.code);
      } catch (e) { fail('Split')(e); }
    });
  }

  function transposeCommand(app) {
    const t = app.requireTable();
    if (!t) return;
    const nsel = t.counts().selected;
    cast(t, {
      id: 'transpose', title: 'Transpose', info: 'cmd:transpose',
      lead: 'Columns become rows and rows columns. The Label column\'s values name the new columns (otherwise Row 1, Row 2, …); By transposes each level separately.',
      roles: [{ key: 'cols', label: 'Transpose Columns', min: 1, hint: 'required', help: 'The columns that become rows: a row for each, named in the Label column, holding its value in each source row. When some are numeric and some text, every value is text.' }, { key: 'label', label: 'Label', max: 1, hint: 'optional', help: 'A column whose values name the new columns (a repeated name gets 2, 3, …); without it they are Row 1, Row 2, ….' }, { key: 'by', label: 'By', hint: 'optional', help: 'Transposes the rows of each level separately: the new table starts with the By columns, the rows of each level one after another.' }],
      options: [
        { key: 'selected', label: `Transpose selected rows only (${nsel})`, type: 'check', value: false, help: 'Only the selected rows become columns (with none selected, every row); off (the default), every row.' },
        { key: 'labelName', label: 'Label column name', type: 'text', value: 'Label', size: 10, help: 'The name of the new column that holds the transposed columns\' names (default Label).' },
        { key: 'name', label: 'Output table name', type: 'text', value: '', size: 18, help: 'The new table\'s name; empty: Transpose of and this table\'s name.' },
      ],
    }, async (s) => {
      try {
        const res = await engine('tables.transpose', { columns: namesOf(t, s.roles.cols), label: namesOf(t, s.roles.label)[0] || null, by: namesOf(t, s.roles.by), rows: s.options.selected && nsel ? t.selectedRows() : null, label_name: s.options.labelName || 'Label' }, t);
        show(fromBackend(res, { name: (s.options.name || '').trim() || uniqueTable(`Transpose of ${t.name}`), sources: [t], source: `Tables > Transpose of ${t.name}` }), res.code);
      } catch (e) { fail('Transpose')(e); }
    });
  }

  /* ---- a dialog of form rows (for Concatenate, Join and Update) -------------------------------- */
  function field(label, input, note) {
    return el('div', { class: 'smt-field' }, el('label', null, el('span', { class: 'smt-flabel', text: label }), input), note ? el('span', { class: 'sm-ob-note', text: note }) : null);
  }
  const check = (label, on = false) => { const cb = el('input', { type: 'checkbox' }); cb.checked = on; return { cb, el: el('label', { class: 'smt-check' }, cb, label) }; };
  const select = (choices, value) => { const s = el('select', null, ...choices.map(([v, l]) => el('option', { value: v, text: l }))); if (value != null) s.value = value; return s; };

  /* ---- Tables > Concatenate ----------------------------------------------------------------- */
  function concatCommand(app) {
    const t = app.requireTable();
    if (!t) return;
    if (app.tables.length < 2) { toast('Concatenate needs two or more open tables'); return; }
    const order = [t, ...app.tables.filter((x) => x !== t)];
    const boxes = order.map((x, i) => ({ t: x, ...check(`${x.name} (${x.nrows} rows)`, i < 2) }));
    const src = check('Create source column', false);
    const append = check('Append to first table', false);
    const nameIn = el('input', { type: 'text', value: '', placeholder: 'Concatenated' });
    const msg = el('div', { class: 'sm-launch-msg' });
    const body = el('div', { class: 'smt-form' },
      el('p', { class: 'sm-dialog-lead', text: 'The rows of the tables one after another, their columns matched by name; a column that a table lacks is missing there. A column that is numeric in one table and text in another becomes text.' }),
      el('h4', { text: 'Data tables to be concatenated, in this order' }), el('div', { class: 'smt-tablelist' }, ...boxes.map((b) => b.el)),
      src.el, append.el, field('Output table name', nameIn), msg);
    SM.ui.dialog({
      title: 'Concatenate', body, info: 'cmd:concatenate', narrow: true,
      buttons: [{ label: 'Cancel' }, { label: 'OK', primary: true, action: () => {
        const list = boxes.filter((b) => b.cb.checked).map((b) => b.t);
        if (list.length < 2) { msg.textContent = 'Tick two or more tables'; return false; }
        try { concatenate(app, list, { source: src.cb.checked, append: append.cb.checked, name: nameIn.value.trim() }); } catch (e) { msg.textContent = e.message; return false; }
        return true;
      } }],
    });
  }

  function concatenate(app, list, { source = false, append = false, name = '' } = {}) {
    const names = [];
    const numeric = new Map(), meta = new Map();
    for (const x of list) for (const c of x.columns) {
      if (!meta.has(c.name)) { names.push(c.name); meta.set(c.name, c); numeric.set(c.name, c.isNumeric); } else if (!c.isNumeric) numeric.set(c.name, false);
    }
    const asText = (c, v) => (isMissing(v) ? null : c.isNumeric ? (SM.formula ? SM.formula.charOf(v) : String(v)) : v);
    const valuesOf = (x, nm) => {
      const c = x.columns.find((y) => y.name === nm);
      if (!c) return new Array(x.nrows).fill(numeric.get(nm) ? NaN : null);
      return numeric.get(nm) ? c.values.slice() : c.values.map((v) => asText(c, v));
    };
    if (append) {
      const first = list[0];
      record(first, 'Concatenate');
      const n0 = first.nrows;
      const add = list.slice(1);
      const total = add.reduce((a, x) => a + x.nrows, 0);
      for (const nm of names) if (!first.columns.some((c) => c.name === nm)) { const m = meta.get(nm); first.addColumn({ ...specOf(m, []), formula: null, dataType: numeric.get(nm) ? 'numeric' : 'character', modelingType: numeric.get(nm) ? m.modelingType : (m.modelingType === 'continuous' ? 'nominal' : m.modelingType) }); }
      for (const c of first.columns) if (c.isNumeric && numeric.get(c.name) === false) first.setType(c.id, { dataType: 'character' });
      if (source && !first.columns.some((c) => c.name === 'Source Table')) first.addColumn({ name: 'Source Table', dataType: 'character', values: new Array(n0).fill(first.name) });
      first.addRows(total);
      let at = n0;
      for (const x of add) {
        for (const c of first.columns) {
          if (c.formula) continue;
          const v = c.name === 'Source Table' && source && !x.columns.some((y) => y.name === 'Source Table') ? new Array(x.nrows).fill(x.name) : valuesOf(x, c.name);
          for (let k = 0; k < x.nrows; k++) c.values[at + k] = c.isNumeric ? (typeof v[k] === 'number' ? v[k] : SM.table.toNumber(v[k])) : (isMissing(v[k]) ? null : String(v[k]));
        }
        at += x.nrows;
      }
      first._changed('data', { concatenated: true });
      app.showTab(app.tabOf(first));
      toast(`Appended ${total} rows to ${first.name}`);
      return first;
    }
    const columns = names.map((nm) => {
      const m = meta.get(nm);
      let values = [];
      for (const x of list) values = values.concat(valuesOf(x, nm));
      const num = numeric.get(nm);
      return { ...specOf(m, values), formula: null, dataType: num ? 'numeric' : 'character', modelingType: num ? m.modelingType : (m.modelingType === 'continuous' ? 'nominal' : m.modelingType), valueOrder: num === m.isNumeric ? (m.valueOrder ? m.valueOrder.slice() : null) : null };
    });
    if (source) columns.push({ name: 'Source Table', dataType: 'character', values: list.flatMap((x) => new Array(x.nrows).fill(x.name)), valueOrder: list.map((x) => x.name) });
    const nt = new SM.Table({ name: name || uniqueTable('Concatenated'), columns, source: `Tables > Concatenate of ${list.map((x) => x.name).join(', ')}` });
    return show(nt);
  }

  /* ---- Tables > Join and Update --------------------------------------------------------------- */
  function pairPicker(t, getOther) {
    const pairs = [];
    const leftSel = el('select', { 'aria-label': 'Matching column of the main table' });
    const rightSel = el('select', { 'aria-label': 'Matching column of the other table' });
    const list = el('ul', { class: 'smt-pairs', 'aria-label': 'Matching columns' });
    const fill = () => {
      leftSel.replaceChildren(...t.columns.map((c) => el('option', { value: c.name, text: c.name })));
      const o = getOther();
      rightSel.replaceChildren(...(o ? o.columns : []).map((c) => el('option', { value: c.name, text: c.name })));
      pairs.length = 0;
      const common = o ? t.columns.find((c) => o.columns.some((d) => d.name === c.name)) : null;
      if (common) { pairs.push([common.name, common.name]); leftSel.value = common.name; rightSel.value = common.name; }
      render();
    };
    const render = () => {
      list.replaceChildren(...pairs.map((p, i) => {
        const x = el('button', { type: 'button', class: 'sm-linkbtn', text: 'remove', 'aria-label': `Remove the pair ${p[0]} = ${p[1]}` });
        x.addEventListener('click', () => { pairs.splice(i, 1); render(); });
        return el('li', null, el('span', { text: `${p[0]} = ${p[1]}` }), x);
      }));
      if (!pairs.length) list.append(el('li', { class: 'sm-ob-note', text: 'No pairs yet: choose a column on each side and press Match.' }));
    };
    const addBtn = el('button', { type: 'button', class: 'sm-btn small', text: 'Match' });
    addBtn.addEventListener('click', () => { const p = [leftSel.value, rightSel.value]; if (p[0] && p[1] && !pairs.some((q) => q[0] === p[0] && q[1] === p[1])) pairs.push(p); render(); });
    fill();
    return { el: el('div', { class: 'smt-pairbox' }, el('div', { class: 'sm-inline' }, leftSel, el('span', { text: '=' }), rightSel, addBtn), list), pairs, refill: fill };
  }

  function joinCommand(app) {
    const t = app.requireTable();
    if (!t) return;
    const others = app.tables.filter((x) => x !== t);
    if (!others.length) { toast('Join needs a second open table'); return; }
    const withSel = select(others.map((o) => [o.id, o.name]));
    const other = () => app.tables.find((x) => x.id === withSel.value);
    const method = select([['match', 'By Matching Columns'], ['row', 'By Row Number'], ['cartesian', 'Cartesian Join']], 'match');
    const pp = pairPicker(t, other);
    withSel.addEventListener('change', () => pp.refill());
    const incMain = check(`Main table (${t.name})`), incWith = check('With table');
    const dropMain = check('Main table'), dropWith = check('With table');
    const flag = check('Match flag', true), merge = check('Merge same name columns', true);
    const nameIn = el('input', { type: 'text', placeholder: 'Joined table' });
    const msg = el('div', { class: 'sm-launch-msg' });
    const pairRow = field('Matching columns', pp.el);
    method.addEventListener('change', () => { pairRow.hidden = method.value !== 'match'; });
    const body = el('div', { class: 'smt-form' },
      el('p', { class: 'sm-dialog-lead', text: `The rows of ${t.name} with the matching rows of another table, side by side. A missing value matches nothing.` }),
      field('Join with', withSel), field('Matching', method), pairRow,
      el('h4', { text: 'Include non-matches' }), el('div', { class: 'sm-inline' }, incMain.el, incWith.el),
      el('h4', { text: 'Drop multiples (keep the first row of each key)' }), el('div', { class: 'sm-inline' }, dropMain.el, dropWith.el),
      el('div', { class: 'sm-inline' }, flag.el, merge.el), field('Output table name', nameIn), msg);
    SM.ui.dialog({
      title: 'Join', body, info: 'cmd:join', narrow: true,
      buttons: [{ label: 'Cancel' }, { label: 'OK', primary: true, action: async () => {
        const o = other();
        if (!o) { msg.textContent = 'Choose the table to join with'; return false; }
        if (method.value === 'match' && !pp.pairs.length) { msg.textContent = 'Match at least one pair of columns'; return false; }
        const how = incMain.cb.checked && incWith.cb.checked ? 'outer' : incMain.cb.checked ? 'left' : incWith.cb.checked ? 'right' : 'inner';
        try {
          const res = await engine('tables.join', { with_table: o.id, match: method.value === 'match' ? pp.pairs : [], how, by_row: method.value === 'row', cartesian: method.value === 'cartesian', drop_left: dropMain.cb.checked, drop_right: dropWith.cb.checked, match_flag: flag.cb.checked, merge_keys: merge.cb.checked, left_name: t.name, right_name: o.name }, t, [o]);
          const nt = fromBackend(res, { name: nameIn.value.trim() || uniqueTable(`Join of ${t.name} with ${o.name}`), sources: [t, o], source: `Tables > Join of ${t.name} with ${o.name}` });
          show(nt, res.code);
          toast(`${nt.name}: ${nt.nrows} rows, ${res.matched} matched`);
        } catch (e) { msg.textContent = e.message; return false; }
        return true;
      } }],
    });
  }

  function updateCommand(app) {
    const t = app.requireTable();
    if (!t) return;
    const others = app.tables.filter((x) => x !== t);
    if (!others.length) { toast('Update needs a second open table'); return; }
    const withSel = select(others.map((o) => [o.id, o.name]));
    const other = () => app.tables.find((x) => x.id === withSel.value);
    const method = select([['match', 'By Matching Columns'], ['row', 'By Row Number']], 'match');
    const pp = pairPicker(t, other);
    withSel.addEventListener('change', () => pp.refill());
    const ignore = check('Ignore missing (a missing value does not overwrite)', true);
    const rep = select([['all', 'All'], ['none', 'None']], 'all'), add = select([['all', 'All'], ['none', 'None']], 'all');
    const msg = el('div', { class: 'sm-launch-msg' });
    const pairRow = field('Matching columns', pp.el);
    method.addEventListener('change', () => { pairRow.hidden = method.value !== 'match'; });
    const body = el('div', { class: 'smt-form' },
      el('p', { class: 'sm-dialog-lead', text: `Changes ${t.name} itself: values of the columns both tables have are replaced by those of the matching row of the other table (the first match), and its other columns are added. Edit > Undo takes it back.` }),
      field('Update with data from', withSel), field('Matching', method), pairRow, ignore.el,
      field('Replace columns in main table', rep), field('Add columns from update table', add), msg);
    SM.ui.dialog({
      title: 'Update', body, info: 'cmd:update', narrow: true,
      buttons: [{ label: 'Cancel' }, { label: 'OK', primary: true, action: async () => {
        const o = other();
        if (method.value === 'match' && !pp.pairs.length) { msg.textContent = 'Match at least one pair of columns'; return false; }
        try {
          const res = await engine('tables.update', { with_table: o.id, match: method.value === 'match' ? pp.pairs : [], by_row: method.value === 'row', replace: rep.value === 'all' ? null : [], add: add.value === 'all' ? null : [], ignore_missing: ignore.cb.checked }, t, [o]);
          applyUpdate(t, o, res);
          SM.app.showTab(SM.app.tabOf(t));
          toast(`Updated ${t.name}: ${res.matched} rows matched, ${res.update.reduce((a, u) => a + u.changed, 0)} values changed, ${res.add.length} columns added`);
        } catch (e) { msg.textContent = e.message; return false; }
        return true;
      } }],
    });
  }

  function applyUpdate(t, o, res) {
    record(t, 'Update');
    for (const u of res.update) {
      const c = t.col(u.name);
      if (!c || c.formula) continue;
      c.values = c.isNumeric ? u.values.map((v) => (v == null ? NaN : +v)) : u.values.map((v) => (v == null ? null : String(v)));
    }
    t._changed('data', { updated: res.update.map((u) => u.name) });
    for (const a of res.add) {
      const src = o.col(a.name);
      const values = a.dataType === 'numeric' ? a.values.map((v) => (v == null ? NaN : v)) : a.values.map((v) => (v == null ? null : String(v)));
      t.addColumn(src ? { ...specOf(src, values), formula: null } : { name: a.name, dataType: a.dataType, values });
    }
  }

  /* ---- Tables > Missing Data Pattern ------------------------------------------------------------- */
  function patternOf(cols, i) {
    let s = '';
    for (const c of cols) s += isMissing(c.values[i]) ? '1' : '0';
    return s;
  }

  function missingPatternCommand(app) {
    const t = app.requireTable();
    if (!t) return;
    cast(t, {
      id: 'missingpattern', title: 'Missing Data Pattern', info: 'cmd:missingpattern',
      lead: 'A table with a row for each pattern of missing values in the columns: how many rows have it, and which columns are missing (1) in it. Selecting a pattern selects its rows.',
      roles: [{ key: 'cols', label: 'Add Columns', min: 1, hint: 'required', help: 'The columns whose missing values make the patterns: a pattern is a 1 (missing) or 0 for each of them, in this order, and each gets a 0/1 column in the new table.' }],
      options: [{ key: 'name', label: 'Output table name', type: 'text', value: '', size: 18, help: 'The new table\'s name; empty: Missing Data Pattern of and this table\'s name.' }],
    }, async (s) => {
      try {
        const cols = idsOf(t, s.roles.cols);
        const res = await engine('tables.missing_pattern', { columns: cols.map((c) => c.name) }, t);
        const nt = fromBackend(res, { name: (s.options.name || '').trim() || uniqueTable(`Missing Data Pattern of ${t.name}`), sources: [t], source: `Tables > Missing Data Pattern of ${t.name}` });
        for (const c of nt.columns) if (res.columns.find((x) => x.name === c.name && x.role === 'indicator')) c.modelingType = 'nominal';
        const pat = nt.col('Patterns');
        linkRows(nt, t, (r) => (pat ? pat.values[r] : null), (i) => patternOf(cols, i));
        show(nt, res.code);
      } catch (e) { fail('Missing Data Pattern')(e); }
    });
  }

  /* ---- Cols > Formula… and New Formula Column ------------------------------------------------------ */
  function targetColumn(app, col) {
    if (col) return col;
    const sel = app.selectedColumns();
    return sel.length === 1 ? sel[0] : null;
  }

  async function newFormulaColumn(app, t, name, expr, at, { modelingType = null, valueOrder = null, label = 'New Formula Column', quiet = false } = {}) {
    record(t, label);
    const c = t.addColumn({ name, dataType: 'numeric', values: [] }, at);
    try {
      SM.formula.apply(t, c, expr);
    } catch (e) {
      t.removeColumn(c.id);
      throw e;
    }
    if (modelingType || valueOrder) {
      if (valueOrder) c.valueOrder = valueOrder;
      if (modelingType && !(modelingType === 'continuous' && !c.isNumeric)) c.modelingType = modelingType;
      t._changed('schema', { info: c.id });
    }
    if (!quiet) toast(`${c.name} = ${expr}`);
    return c;
  }

  const TRANSFORMS = [
    { group: 'Transform', label: 'Log', name: 'Log', num: true, f: (x) => `Log(${x})` },
    { group: 'Transform', label: 'Log10', name: 'Log10', num: true, f: (x) => `Log10(${x})` },
    { group: 'Transform', label: 'Square Root', name: 'Sqrt', num: true, f: (x) => `Sqrt(${x})` },
    { group: 'Transform', label: 'Square', name: 'Square', num: true, f: (x) => `${x}^2` },
    { group: 'Transform', label: 'Reciprocal', name: 'Reciprocal', num: true, f: (x) => `1 / ${x}` },
    { group: 'Transform', label: 'Exp', name: 'Exp', num: true, f: (x) => `Exp(${x})` },
    { group: 'Transform', label: 'Standardize', name: 'Standardize', num: true, f: (x) => `Col Standardize(${x})` },
    { group: 'Transform', label: 'Center', name: 'Center', num: true, f: (x) => `${x} - Col Mean(${x})` },
    { group: 'Transform', label: 'Absolute Value', name: 'Abs', num: true, f: (x) => `Abs(${x})` },
    { group: 'Row', label: 'Lag', name: 'Lag', f: (x) => `Lag(${x}, 1)` },
    { group: 'Row', label: 'Difference', name: 'Difference', num: true, f: (x) => `Dif(${x}, 1)` },
    { group: 'Row', label: 'Cumulative Sum', name: 'Cumulative Sum', num: true, f: (x) => `Col Cumulative Sum(${x})` },
    { group: 'Row', label: 'Row Number', name: 'Row Number', none: true, f: () => 'Row()' },
    { group: 'Distributional', label: 'Rank', name: 'Rank', f: (x) => `Col Rank(${x})` },
    { group: 'Distributional', label: 'Rank Fraction', name: 'Rank Fraction', num: true, f: (x) => `Col Rank(${x}, <<Tie("average")) / (Col Number(${x}) + 1)` },
    { group: 'Distributional', label: 'Normal Quantile', name: 'Normal Quantile', num: true, f: (x) => `Normal Quantile(Col Rank(${x}, <<Tie("average")) / (Col Number(${x}) + 1))` },
  ];
  const COMBINE = [
    { label: 'Sum', name: 'Sum', min: 2, f: (xs) => `Sum(${xs.join(', ')})` },
    { label: 'Mean', name: 'Mean', min: 2, f: (xs) => `Mean(${xs.join(', ')})` },
    { label: 'Difference', name: 'Difference', min: 2, max: 2, f: (xs) => `${xs[0]} - ${xs[1]}` },
    { label: 'Ratio', name: 'Ratio', min: 2, max: 2, f: (xs) => `${xs[0]} / ${xs[1]}` },
  ];

  /* The items of New Formula Column ▸, for the columns picked. */
  function nfcItems(app, cols) {
    const t = app.current;
    const one = cols.length === 1 ? cols[0] : null;
    const run = async (name, expr, at) => { try { await newFormulaColumn(app, t, t.uniqueName(name), expr, at); } catch (e) { toast(`${name}: ${e.message}`, { error: true }); } };
    const make = (tr) => ({
      label: tr.label, disabled: !t || (!tr.none && !cols.length) || (tr.num && cols.some((c) => !c.isNumeric)),
      action: async () => {
        if (tr.none) { await run(tr.name, tr.f(), cols.length ? t.colIndex(cols[cols.length - 1]) + 1 : null); return; }
        for (const c of cols.slice().reverse()) await run(`${tr.name}[${c.name}]`, tr.f(refOf(c.name)), t.colIndex(c) + 1);
      },
    });
    const group = (g) => TRANSFORMS.filter((x) => x.group === g).map(make);
    return [
      { label: 'Transform', submenu: () => group('Transform') },
      { label: 'Row', submenu: () => group('Row') },
      { label: 'Distributional', submenu: () => group('Distributional') },
      { label: 'Combine', disabled: cols.length < 2, submenu: () => COMBINE.map((cb) => ({
        label: cb.label, disabled: cols.length < cb.min || (cb.max && cols.length > cb.max) || cols.some((c) => !c.isNumeric),
        action: () => run(`${cb.name}[${cols.map((c) => c.name).join(', ')}]`, cb.f(cols.map((c) => refOf(c.name))), t.colIndex(cols[cols.length - 1]) + 1),
      })) },
      { separator: true },
      { label: 'Formula…', disabled: !t, action: () => SM.formula.edit(t, null, { at: one ? t.colIndex(one) + 1 : null, expr: one ? refOf(one.name) : '' }) },
    ];
  }

  /* ---- Cols > Recode… ------------------------------------------------------------------------------ */
  const titleCase = (s) => s.toLowerCase().replace(/(^|[^\p{L}\p{N}'’])(\p{L})/gu, (m, a, b) => a + b.toUpperCase());
  const similarKey = (s) => s.toLowerCase().normalize('NFKD').replace(/[̀-ͯ]/g, '').replace(/[^\p{L}\p{N}]+/gu, ' ').trim();
  const MISS = Symbol('missing');

  function recodeCommand(app, col) {
    const t = app.requireTable();
    if (!t) return;
    const c = targetColumn(app, col);
    if (!c) { toast('Select one column to recode (click its heading)'); return; }
    if (c.formula) { toast(`${c.name} is a formula column: recode makes a new column from it`); }
    const counts = new Map();
    let nmiss = 0;
    for (const v of c.values) { if (isMissing(v)) nmiss++; else counts.set(v, (counts.get(v) || 0) + 1); }
    const levels = t.levels(c);
    if (levels.length > 3000) { toast(`${c.name} has ${levels.length} distinct values; Recode takes at most 3000 (a binning column may be what you want: Cols > Utilities)`, { error: true }); return; }
    const items = levels.map((v) => ({ old: v, text: cellText(c, v), count: counts.get(v) || 0 }));
    if (nmiss) items.push({ old: MISS, text: '', count: nmiss });
    for (const it of items) it.input = el('input', { type: 'text', class: 'smr-new', value: it.text, 'aria-label': `New value for ${it.old === MISS ? 'missing' : it.text}` });
    const filter = el('input', { type: 'search', placeholder: 'Filter values', 'aria-label': 'Filter values' });
    const tbody = el('tbody');
    const draw = () => {
      const f = filter.value.trim().toLowerCase();
      tbody.replaceChildren(...items.filter((it) => !f || it.text.toLowerCase().includes(f) || it.input.value.toLowerCase().includes(f)).map((it) => el('tr', { class: it.input.value !== it.text ? 'is-changed' : '' },
        el('td', { class: 'sm-l', text: it.old === MISS ? 'Missing' : it.text }), el('td', { text: String(it.count) }), el('td', null, it.input))));
    };
    tbody.addEventListener('input', (ev) => { const tr = ev.target.closest('tr'); const it = items.find((x) => x.input === ev.target); if (tr && it) tr.classList.toggle('is-changed', it.input.value !== it.text); });
    filter.addEventListener('input', draw);
    draw();
    const act = (label, fn) => { const b = el('button', { type: 'button', class: 'sm-btn small', text: label }); b.addEventListener('click', () => { for (const it of items) it.input.value = fn(it.input.value, it); draw(); }); return b; };
    const groupSimilar = el('button', { type: 'button', class: 'sm-btn small', text: 'Group Similar Values' });
    groupSimilar.addEventListener('click', () => {
      const groups = new Map();
      for (const it of items) { if (it.old === MISS) continue; const k = similarKey(it.input.value); if (!groups.has(k)) groups.set(k, []); groups.get(k).push(it); }
      let n = 0;
      for (const g of groups.values()) {
        if (g.length < 2) continue;
        const best = g.slice().sort((a, b) => b.count - a.count)[0].input.value;
        for (const it of g) if (it.input.value !== best) { it.input.value = best; n++; }
      }
      draw();
      toast(n ? `${n} values grouped with a similar one (the same letters and digits, ignoring case, accents, spaces and signs)` : 'No similar values found');
    });
    const mode = select([['new', 'New Column'], ['inplace', 'In Place'], ['formula', 'Formula Column']], 'new');
    const nameIn = el('input', { type: 'text', value: t.uniqueName(`${c.name} 2`), 'aria-label': 'New column name' });
    mode.addEventListener('change', () => { nameIn.disabled = mode.value === 'inplace'; });
    const msg = el('div', { class: 'sm-launch-msg' });
    const body = el('div', { class: 'smr' },
      el('p', { class: 'sm-dialog-lead', text: `The ${items.length} distinct values of ${c.name}, with how many rows have each. Type a new value beside the old one; several old values given the same new value become one. An empty new value is missing.` }),
      el('div', { class: 'smr-actions' }, act('Trim Whitespace', (v) => v.trim()), act('Collapse Whitespace', (v) => v.trim().replace(/\s+/g, ' ')), act('Title Case', titleCase), act('Lower Case', (v) => v.toLowerCase()), act('Upper Case', (v) => v.toUpperCase()), groupSimilar, act('Reset', (v, it) => it.text)),
      filter,
      el('div', { class: 'smr-scroll' }, el('table', { class: 'sm-rt smr-table' }, el('thead', null, el('tr', null, el('th', { class: 'sm-l', text: 'Old Values' }), el('th', { text: 'Count' }), el('th', { class: 'sm-l', text: 'New Values' }))), tbody)),
      el('div', { class: 'sm-inline smr-out' }, el('span', { text: 'Done:' }), mode, el('span', { text: 'Name' }), nameIn), msg);
    SM.ui.dialog({
      title: `Recode: ${c.name}`, body, info: 'cmd:recode', className: 'smr-dialog',
      buttons: [{ label: 'Cancel' }, { label: 'Recode', primary: true, action: () => {
        try { applyRecode(t, c, items, mode.value, nameIn.value.trim()); } catch (e) { msg.textContent = e.message; return false; }
        return true;
      } }],
    });
  }

  function applyRecode(t, c, items, mode, name) {
    const newText = new Map(items.map((it) => [it.old, it.input.value.trim()]));
    const nonEmpty = [...newText.values()].filter((s) => s !== '');
    const numeric = c.isNumeric && nonEmpty.every((s) => !Number.isNaN(SM.table.toNumber(s)));
    const conv = (s) => (s === '' ? (numeric ? NaN : null) : numeric ? SM.table.toNumber(s) : s);
    const map = new Map([...newText].map(([k, s]) => [k, conv(s)]));
    const old = c.values.slice();
    const values = old.map((v) => (isMissing(v) ? (map.has(MISS) ? map.get(MISS) : (numeric ? NaN : null)) : map.get(v)));
    // value order: the new values in the order of the old ones
    const order = [];
    for (const it of items) { const v = map.get(it.old); if (!isMissing(v) && !order.includes(v)) order.push(v); }
    const mtype = numeric ? c.modelingType : (c.modelingType === 'continuous' ? 'nominal' : c.modelingType);
    if (mode === 'inplace') {
      if (c.formula) throw new Error(`${c.name} is a formula column: recode it into a new column`);
      record(t, `Recode ${c.name}`);
      if (!numeric && c.isNumeric) t.setType(c.id, { dataType: 'character' });
      t.setValues(c.id, values);
      if (!numeric || c.isCategorical) { c.valueOrder = order.slice(); t._changed('schema', { info: c.id }); }
      return c;
    }
    const nm = t.uniqueName(name || `${c.name} 2`);
    if (mode === 'formula') {
      const lit = (v) => (numeric ? numLit(v) : isMissing(v) ? '""' : quote(v));
      const parts = [];
      for (const it of items) {
        const nv = map.get(it.old);
        const same = it.old === MISS ? isMissing(nv) : (numeric ? nv === it.old : String(nv) === (c.isNumeric ? SM.formula.charOf(it.old) : it.old));
        if (same) continue;
        parts.push(it.old === MISS ? '.' : (c.isNumeric ? numLit(it.old) : quote(it.old)), lit(nv));
      }
      const x = refOf(c.name);
      const els = numeric || !c.isNumeric ? x : `If(Is Missing(${x}), "", Char(${x}))`;
      const expr = parts.length ? `Match(${x}, ${parts.join(', ')}, ${els})` : els;
      return newFormulaColumn(SM.app, t, nm, expr, t.colIndex(c) + 1, { modelingType: mtype, valueOrder: !numeric || c.isCategorical ? order : null, label: `Recode ${c.name}`, quiet: true });
    }
    record(t, `Recode ${c.name}`);
    return t.addColumn({ name: nm, dataType: numeric ? 'numeric' : 'character', modelingType: mtype, values, valueOrder: !numeric || c.isCategorical ? order : null, notes: `recoded from ${c.name}` }, t.colIndex(c) + 1);
  }

  /* ---- Cols > Utilities ---------------------------------------------------------------------------------- */
  async function indicatorCommand(app, col) {
    const t = app.requireTable();
    if (!t) return;
    const cols = col ? [col] : app.selectedColumns();
    const cats = cols.filter((c) => c.isCategorical);
    if (!cats.length) { toast('Select a nominal or ordinal column (click its heading)'); return; }
    const v = await SM.ui.form({
      title: 'Make Indicator Columns', info: 'cmd:indicator',
      lead: `A 0/1 column for each level of ${cats.map((c) => c.name).join(', ')}: 1 in the rows with that level. Missing rows are missing.`,
      fields: [{ key: 'append', label: 'Append column name (sex[F] rather than F)', type: 'check', value: true, help: 'On (the default): each new column is named after the column and the level, sex[F]; off, after the level alone, F.' }, { key: 'formula', label: 'As formula columns', type: 'check', value: false, help: 'Each new column is a formula, If(Is Missing(:x), ., :x == level), that follows the column when it changes; off (the default), plain 0/1 values.' }],
    });
    if (!v) return;
    record(t, 'Make Indicator Columns');
    let made = 0;
    for (const c of cats) {
      const lv = t.levels(c);
      if (lv.length > 200) { toast(`${c.name} has ${lv.length} levels; at most 200 indicator columns are made`, { error: true }); continue; }
      let at = t.colIndex(c) + 1;
      for (const L of lv) {
        const name = t.uniqueName(v.append ? `${c.name}[${cellText(c, L)}]` : cellText(c, L));
        if (v.formula) {
          const x = refOf(c.name);
          const nc = t.addColumn({ name, dataType: 'numeric', values: [] }, at);
          SM.formula.apply(t, nc, `If(Is Missing(${x}), ., ${x} == ${c.isNumeric ? numLit(L) : quote(L)})`);
        } else {
          t.addColumn({ name, dataType: 'numeric', values: c.values.map((x) => (isMissing(x) ? NaN : x === L ? 1 : 0)), notes: `indicator of ${c.name} = ${cellText(c, L)}` }, at);
        }
        at++;
        made++;
      }
    }
    toast(`Made ${made} indicator columns`);
  }

  async function binningCommand(app, col) {
    const t = app.requireTable();
    if (!t) return;
    const nums = t.columns.filter((c) => c.isNumeric);
    if (!nums.length) { toast('Binning needs a numeric column'); return; }
    const pre = (col && col.isNumeric ? col : null) || app.selectedColumns().find((c) => c.isNumeric) || nums.find((c) => !c.isCategorical) || nums[0];
    const v = await SM.ui.form({
      title: 'Make Binning Column', info: 'cmd:binning',
      lead: 'A new ordinal column of the bin each value falls in, labelled by its range. A bin holds its lower limit and not its upper one, except the last.',
      fields: [
        { key: 'col', label: 'Column', type: 'select', value: pre.id, choices: nums.map((c) => [c.id, c.name]), help: 'The numeric column to cut into bins; the new column goes right after it.' },
        { key: 'method', label: 'Bins', type: 'select', value: 'width', choices: [['width', 'Equal width'], ['quantile', 'Quantiles (equal counts)'], ['custom', 'Custom cut points']], help: '**Equal width** (the default): bins of one width; **Quantiles (equal counts)**: cut at the column\'s quantiles (JMP\'s definition), so that each bin holds about as many rows; **Custom cut points**: cut at the values you list.' },
        { key: 'k', label: 'Number of bins', type: 'number', value: 5, help: 'With Equal width and no Bin width, about how many bins (the width is rounded); with Quantiles, how many (fewer when quantiles tie). Default 5.' },
        { key: 'width', label: 'Bin width (equal width; empty: rounded automatically)', type: 'number', value: null, help: 'With Equal width: the width of every bin, in the column\'s units; empty lets the Number of bins choose a round width.' },
        { key: 'start', label: 'First cut point (equal width; optional)', type: 'number', value: null, help: 'With Equal width: where the bins start, their first boundary; values below it make a first bin of their own. Empty: the whole multiple of the width at or below the smallest value.' },
        { key: 'cuts', label: 'Cut points (custom), e.g. 150, 160, 170', value: '', help: 'With Custom cut points: the boundaries between the bins, separated by commas; a value equal to a cut point goes into the bin above it. Cut points outside the column\'s range are dropped.' },
        { key: 'style', label: 'Labels', type: 'select', value: 'range', choices: [['range', 'Range: 150 - 160'], ['interval', 'Interval: [150, 160)'], ['lower', 'Lower limit: 150'], ['mid', 'Midpoint: 155']], help: 'How the bins are named: by **Range** (the default), **Interval** (the last bin closed, with ]), **Lower limit** or **Midpoint**. The first bin starts at the smallest value and the last ends at the largest.' },
        { key: 'formula', label: 'As a formula column', type: 'check', value: true, help: 'On (the default): a formula column, If(:x < cut, label, …), that follows the column when it changes; off: plain text values.' },
        { key: 'name', label: 'New column name (empty: column Binned)', value: '', help: 'The new column\'s name; empty: the column\'s name and Binned. It is ordinal, its levels in the order of the bins.' },
      ],
      validate: (x) => (x.method === 'custom' && !String(x.cuts).split(/[,;\s]+/).some((s) => s !== '' && Number.isFinite(Number(s))) ? 'Give one or more cut points' : (x.method !== 'custom' && !(x.k >= 2 || x.width > 0) ? 'Two or more bins, or a bin width' : null)),
    });
    if (!v) return;
    const c = t.col(v.col);
    try { makeBinning(t, c, v); } catch (e) { toast(`Make Binning Column: ${e.message}`, { error: true }); }
  }

  function binCuts(values, v) {
    const xs = values.filter((x) => Number.isFinite(x)).sort((a, b) => a - b);
    if (!xs.length) throw new Error('the column has no values');
    const lo = xs[0], hi = xs[xs.length - 1];
    let cuts;
    if (v.method === 'custom') cuts = String(v.cuts).split(/[,;\s]+/).filter((s) => s !== '').map(Number).filter(Number.isFinite);
    else if (v.method === 'quantile') { const k = Math.max(2, Math.round(v.k || 5)); cuts = []; for (let i = 1; i < k; i++) cuts.push(SM.formula.quantile(xs, i / k)); }
    else {
      let start, size;
      if (v.width > 0) { size = v.width; start = v.start != null && Number.isFinite(v.start) ? v.start : Math.floor(lo / size) * size; }
      else { const b = SM.report.niceBins(xs, Math.max(2, Math.round(v.k || 5))); size = b.size; start = v.start != null && Number.isFinite(v.start) ? v.start : b.start; }
      cuts = [];
      for (let x = start + (start <= lo ? size : 0); x <= hi && cuts.length < 1000; x += size) cuts.push(+x.toPrecision(12));
      if (start > lo) cuts.unshift(start);
    }
    cuts = [...new Set(cuts.map((x) => +x.toPrecision(12)))].sort((a, b) => a - b).filter((x) => x > lo && x <= hi);
    if (cuts.length && cuts[cuts.length - 1] === hi) cuts.pop();
    return { cuts, lo, hi };
  }

  function makeBinning(t, c, v) {
    const { cuts, lo, hi } = binCuts(c.values, v);
    const edges = [lo, ...cuts, hi];
    const f = (x) => fmt(x).replace(/−/g, '-');
    const labels = [];
    for (let i = 0; i + 1 < edges.length; i++) {
      const a = edges[i], b = edges[i + 1], last = i + 2 === edges.length;
      labels.push(v.style === 'interval' ? `[${f(a)}, ${f(b)}${last ? ']' : ')'}` : v.style === 'lower' ? f(a) : v.style === 'mid' ? f((a + b) / 2) : `${f(a)} - ${f(b)}`);
    }
    const name = t.uniqueName(v.name || `${c.name} Binned`);
    const at = t.colIndex(c) + 1;
    if (v.formula) {
      const x = refOf(c.name);
      const parts = cuts.map((cut, i) => `${x} < ${numLit(cut)}, ${quote(labels[i])}`);
      const expr = parts.length ? `If(${parts.join(', ')}, ${quote(labels[labels.length - 1])})` : `If(Is Missing(${x}), "", ${quote(labels[0])})`;
      return newFormulaColumn(SM.app, t, name, expr, at, { modelingType: 'ordinal', valueOrder: labels, label: 'Make Binning Column' });
    }
    record(t, 'Make Binning Column');
    const values = c.values.map((x) => { if (!Number.isFinite(x)) return null; let i = 0; while (i < cuts.length && x >= cuts[i]) i++; return labels[i]; });
    return t.addColumn({ name, dataType: 'character', modelingType: 'ordinal', values, valueOrder: labels, notes: `bins of ${c.name}` }, at);
  }

  async function standardizeCommand(app, col) {
    const t = app.requireTable();
    if (!t) return;
    const cols = (col ? [col] : app.selectedColumns()).filter((c) => c.isNumeric);
    if (!cols.length) { toast('Select numeric columns to standardize (click their headings)'); return; }
    for (const c of cols.slice().reverse()) {
      try { await newFormulaColumn(app, t, t.uniqueName(`Standardize[${c.name}]`), `Col Standardize(${refOf(c.name)})`, t.colIndex(c) + 1, { label: 'Standardize', quiet: true }); } catch (e) { toast(e.message, { error: true }); }
    }
    toast(`Standardized ${cols.map((c) => c.name).join(', ')}: (x − mean)/std dev, as formula columns`);
  }

  /* ---- Analyze > Tabulate ---------------------------------------------------------------------------------- */
  const TAB_STATS = ['N', 'Mean', 'Std Dev', 'Min', 'Max', 'Range', 'Sum', 'Median', 'Quantiles', '% of Total', 'Column %', 'Row %', 'N Missing', 'Mode', 'Variance', 'Std Err', 'CV', 'Interquartile Range'];
  const COUNT_STATS = new Set(['N', '% of Total', 'Column %', 'Row %']);
  const emptyTab = () => ({ rows: [], cols: [], analysis: [], stats: ['N'], quantiles: [25, 75], allRows: false, allCols: false, missing: false });

  function tabState(ctx) {
    const s = ctx.opt('tab', null);
    return s ? JSON.parse(JSON.stringify(s)) : emptyTab();
  }

  function resolveRef(t, r) { return r ? t.col(r.id) || t.col(r.name) : null; }

  function tabBuilder(ctx, state) {
    const t = ctx.table;
    const set = (next) => ctx.set('tab', next);
    const ref = (c) => ({ id: c.id, name: c.name });
    const addTo = (kind, ids, chain = null) => {
      const s = tabState(ctx);
      for (const id of ids) {
        const c = t.col(id);
        if (!c) continue;
        // continuous columns, wherever they are dropped, are analysis columns
        if (kind === 'analysis' || !c.isCategorical) { if (!s.analysis.some((r) => resolveRef(t, r) === c)) s.analysis.push(ref(c)); continue; }
        const dim = kind === 'cols' ? s.cols : s.rows;
        if (chain != null && dim[chain]) { if (!dim[chain].some((r) => resolveRef(t, r) === c)) dim[chain].push(ref(c)); }
        else if (kind === 'nest' && s.rows.length) { const last = s.rows[s.rows.length - 1]; if (!last.some((r) => resolveRef(t, r) === c)) last.push(ref(c)); }
        else dim.push([ref(c)]);
      }
      if (s.analysis.length && s.stats.every((x) => COUNT_STATS.has(x)) && !s.stats.includes('Mean')) s.stats = s.stats.includes('N') ? ['N', 'Mean'] : ['Mean'];
      set(s);
    };
    let picked = null;
    const list = el('ul', { class: 'smt-cols', role: 'listbox', 'aria-label': 'Columns' });
    const mark = () => list.querySelectorAll('li').forEach((li) => { const on = li.dataset.id === picked; li.classList.toggle('is-selected', on); li.setAttribute('aria-selected', String(on)); });
    for (const c of t.columns) {
      const li = el('li', { role: 'option', tabindex: '0', draggable: 'true', dataset: { id: c.id }, 'aria-selected': 'false', title: `${c.name}: ${TYPE_LABEL[c.modelingType]}. Drag it to a zone, or select it and use the buttons.` }, typeIcon(c.modelingType), el('span', { class: 'sm-colname', text: c.name }));
      li.addEventListener('dragstart', (ev) => { ev.dataTransfer.setData(SM.launch.MIME, JSON.stringify([c.id])); ev.dataTransfer.setData('text/plain', c.name); ev.dataTransfer.effectAllowed = 'copy'; });
      li.addEventListener('click', () => { picked = c.id; mark(); });
      li.addEventListener('dblclick', () => addTo(c.isCategorical ? 'rows' : 'analysis', [c.id]));
      li.addEventListener('keydown', (ev) => {
        if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); picked = c.id; mark(); if (ev.key === 'Enter') addTo(c.isCategorical ? 'rows' : 'analysis', [c.id]); }
        else if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp') { ev.preventDefault(); const sib = ev.key === 'ArrowDown' ? li.nextElementSibling : li.previousElementSibling; if (sib) sib.focus(); }
      });
      list.append(li);
    }
    const btn = (label, fn, cls = 'sm-btn small') => { const b = el('button', { type: 'button', class: cls, text: label }); b.addEventListener('click', fn); return b; };
    const needPick = (fn) => () => { if (!picked) { toast('Select a column in the list first'); return; } fn(picked); };
    const adders = el('div', { class: 'smt-adders', role: 'group', 'aria-label': 'Add the selected column' },
      btn('Add to Rows', needPick((id) => addTo('rows', [id]))), btn('Nest in Rows', needPick((id) => addTo('nest', [id]))),
      btn('Add to Columns', needPick((id) => addTo('cols', [id]))), btn('Analysis Column', needPick((id) => addTo('analysis', [id]))));
    const zone = (kind, label, chains) => {
      const z = el('div', { class: `smt-zone smt-zone-${kind}`, dataset: { zone: kind }, role: 'group', 'aria-label': label });
      const items = [];
      if (kind === 'analysis') {
        for (const r of chains) {
          const c = resolveRef(t, r);
          items.push(chip(c ? c.name : `${r.name} (gone)`, c, () => { const s = tabState(ctx); s.analysis = s.analysis.filter((x) => !(x.id === r.id && x.name === r.name)); set(s); }, null));
        }
      } else {
        chains.forEach((chain, ci) => {
          const g = el('span', { class: 'smt-chain', dataset: { chain: String(ci) } });
          chain.forEach((r, k) => {
            if (k) g.append(el('span', { class: 'smt-nest', text: '▸', 'aria-hidden': 'true' }));
            const c = resolveRef(t, r);
            g.append(chip(c ? c.name : `${r.name} (gone)`, c, () => {
              const s = tabState(ctx);
              const dim = kind === 'cols' ? s.cols : s.rows;
              dim[ci].splice(k, 1);
              if (!dim[ci].length) dim.splice(ci, 1);
              set(s);
            }, ci));
          });
          items.push(g);
        });
      }
      z.append(el('span', { class: 'smt-zonelabel', text: label }), ...items);
      if (!items.length) z.append(el('span', { class: 'smt-zonehint', text: kind === 'analysis' ? 'drop continuous columns here' : `drop ${kind === 'rows' ? 'a column' : 'a column'} here; on a column to nest it` }));
      z.addEventListener('dragover', (ev) => { if ([...ev.dataTransfer.types].includes(SM.launch.MIME)) { ev.preventDefault(); ev.dataTransfer.dropEffect = 'copy'; z.classList.add('drop'); } });
      z.addEventListener('dragleave', (ev) => { if (!z.contains(ev.relatedTarget)) z.classList.remove('drop'); });
      z.addEventListener('drop', (ev) => {
        z.classList.remove('drop');
        const d = ev.dataTransfer.getData(SM.launch.MIME);
        if (!d) return;
        ev.preventDefault();
        let ids;
        try { ids = JSON.parse(d); } catch (e) { return; }
        if (!Array.isArray(ids)) return;
        const onChain = ev.target.closest && ev.target.closest('.smt-chain');
        addTo(kind, ids.map(String), onChain ? +onChain.dataset.chain : null);
      });
      return z;
    };
    const chip = (text, c, remove, chain) => {
      const x = el('button', { type: 'button', class: 'smt-x', 'aria-label': `Remove ${text}`, text: '×' });
      x.addEventListener('click', (ev) => { ev.stopPropagation(); remove(); });
      return el('span', { class: 'smt-chip', dataset: chain != null ? { chain: String(chain) } : null }, c ? typeIcon(c.modelingType, 10) : null, el('span', { text }), x);
    };
    const statBar = el('div', { class: 'smt-statbar', role: 'group', 'aria-label': 'Statistics' }, el('span', { class: 'smt-zonelabel', text: 'Statistics' }));
    for (const s of TAB_STATS) {
      const on = state.stats.includes(s);
      const off = !state.analysis.length && !COUNT_STATS.has(s);
      const b = el('button', { type: 'button', class: `smt-statbtn${on ? ' is-on' : ''}`, 'aria-pressed': String(on), disabled: off, title: off ? 'needs an analysis column' : null, text: s });
      b.addEventListener('click', () => { const st = tabState(ctx); st.stats = st.stats.includes(s) ? st.stats.filter((x) => x !== s) : TAB_STATS.filter((x) => x === s || st.stats.includes(x)); if (!st.stats.length) st.stats = ['N']; set(st); });
      statBar.append(b);
    }
    const q = el('input', { type: 'text', size: 8, value: (state.quantiles || [25, 75]).join(', '), 'aria-label': 'Quantiles in percent' });
    q.addEventListener('change', () => { const st = tabState(ctx); st.quantiles = q.value.split(/[,;\s]+/).map(Number).filter((p) => p >= 0 && p <= 100); set(st); });
    const toggle = (label, key) => { const cb = el('input', { type: 'checkbox' }); cb.checked = !!state[key]; cb.addEventListener('change', () => { const st = tabState(ctx); st[key] = cb.checked; set(st); }); return el('label', { class: 'smt-check' }, cb, label); };
    const freq = el('select', { 'aria-label': 'Freq column' }, el('option', { value: '', text: '(none)' }), ...t.columns.filter((c) => c.isNumeric).map((c) => el('option', { value: c.id, text: c.name })));
    const fcol = resolveRef(t, state.freq);
    freq.value = fcol ? fcol.id : '';
    freq.addEventListener('change', () => { const st = tabState(ctx); const c = t.col(freq.value); st.freq = c ? ref(c) : null; set(st); });
    const opts = el('div', { class: 'smt-opts' }, toggle('All row (totals)', 'allRows'), toggle('All column (totals)', 'allCols'), toggle('Include missing for grouping columns', 'missing'),
      el('label', { class: 'smt-check' }, 'Freq', freq),
      state.stats.includes('Quantiles') ? el('label', { class: 'smt-check' }, 'Quantiles (%)', q) : null,
      el('span', { class: 'sm-spacer' }), btn('Clear', () => set(emptyTab())), btn('Done', () => ctx.set('panel', false), 'sm-btn small primary'));
    return el('div', { class: 'smt-builder' },
      el('div', { class: 'smt-left' }, el('h4', null, 'Columns', infoSlot('p:tabulate')), list, adders),
      el('div', { class: 'smt-right' }, zone('cols', 'Drop zone for columns', state.cols), zone('rows', 'Drop zone for rows', state.rows), zone('analysis', 'Analysis columns', state.analysis), statBar, opts));
  }

  function levelText(t, name, v) {
    const c = t.col(name);
    if (v == null || (typeof v === 'number' && Number.isNaN(v))) return '.';
    return c ? cellText(c, v) : String(v);
  }

  function tabResult(ctx, res) {
    const t = ctx.table;
    const rv = res.row_vars;
    const cols = rv.map((v, k) => ({ key: `r${k}`, label: v, fmt: 'text' }));
    const anyAnalysis = res.cols.some((h) => h.analysis);
    res.cols.forEach((h, j) => {
      const parts = h.levels.map(([v, x]) => `${v}=${levelText(t, v, x)}`).concat(h.all ? ['All'] : []);
      const label = h.analysis ? `${h.label}(${[h.analysis, ...parts].join(', ')})` : parts.length ? `${h.label}(${parts.join(', ')})` : h.label;
      cols.push({ key: `c${j}`, label, fmt: h.stat === 'N' || h.stat === 'N Missing' ? 'int' : 'num', digits: /%/.test(h.stat) ? 2 : undefined });
    });
    const rows = res.rows.map((r, i) => {
      const o = {};
      rv.forEach((v, k) => { const lv = r.levels.find(([n]) => n === v); o[`r${k}`] = r.all ? (k === 0 ? 'All' : '') : lv ? levelText(t, v, lv[1]) : ''; });
      if (!rv.length) o._label = 'All';
      res.values[i].forEach((x, j) => { o[`c${j}`] = x; });
      return o;
    });
    if (!rv.length) cols.unshift({ key: '_label', label: '', fmt: 'text' });
    const tbl = ctx.rt({ columns: cols, rows }, { sortable: false, name: 'Tabulate', className: 'smt-table' });
    // The header in levels, as JMP draws it: column, level, analysis column, statistic.
    const lead = cols.length - res.cols.length;
    const paths = res.cols.map((h) => {
      const p = [];
      for (const [v, x] of h.levels) p.push(v, levelText(t, v, x));
      if (h.all) p.push('All');
      return p;
    });
    const depth = Math.max(0, ...paths.map((p) => p.length));
    const full = paths.map((p, j) => [...new Array(depth - p.length).fill(''), ...p, ...(anyAnalysis ? [res.cols[j].analysis || ''] : [])]);
    const head = tbl.querySelector('thead');
    const base = head.querySelector('tr');
    base.querySelectorAll('th').forEach((th, j) => { if (j >= lead) th.textContent = res.cols[j - lead].label; });
    const levels = full.length ? full[0].length : 0;
    for (let lev = levels - 1; lev >= 0; lev--) {
      const tr = el('tr', { class: 'smt-headrow' });
      for (let k = 0; k < lead; k++) tr.append(el('th', { class: 'sm-l', text: '' }));
      for (let j = 0; j < full.length;) {
        let span = 1;
        while (j + span < full.length && full[j + span].slice(0, lev + 1).join('\u0001') === full[j].slice(0, lev + 1).join('\u0001')) span++;
        tr.append(el('th', { class: 'smt-group', colspan: String(span), text: full[j][lev], scope: 'colgroup' }));
        j += span;
      }
      head.insertBefore(tr, head.firstChild);
    }
    // repeated outer row labels are left out, as in JMP's nesting
    const trs = [...tbl.querySelectorAll('tbody tr')];
    for (let i = 1; i < trs.length; i++) {
      if (res.rows[i].block !== res.rows[i - 1].block) continue;
      for (let k = 0; k < rv.length - 1; k++) {
        const same = rv.slice(0, k + 1).every((_, m) => rows[i][`r${m}`] === rows[i - 1][`r${m}`]);
        if (same && rows[i][`r${k}`] !== '') trs[i].children[k].classList.add('smt-rep');
        else break;
      }
    }
    return tbl;
  }

  SM.platforms.register({
    id: 'tabulate', label: 'Tabulate', menu: 'Analyze', order: 30, launch: null, info: 'p:tabulate',
    about: 'Builds a table of statistics by dragging columns: categorical columns into the rows and columns (side by side for blocks one after another, onto one another to nest them; the rows cross the columns), continuous columns as analysis columns, and statistics from the palette; All adds totals. pandas and numpy compute the cells.',
    uses: ['pandas (grouping)', 'numpy.quantile(method="weibull")', 'statsmodels.stats.weightstats.DescrStatsW'],
    topics: {
      'p:tabulate': {
        kicker: 'Analyze', title: 'Tabulate',
        lead: 'An interactive table: drag columns into the drop zones and statistics onto them, and the table is computed as you build it.',
        sections: [
          { heading: 'Building the table', list: ['Drag a nominal or ordinal column into the drop zone for rows or for columns. Another dropped beside it adds a second block after the first (its levels listed after the first\'s); dropped onto its name, it is nested in it, a row for each combination of their levels. A column in the rows and one in the columns cross: a cell holds the rows of both its levels.', 'Drag continuous columns to Analysis columns (or into either zone): their statistics fill the cells.', 'Click statistics in the palette to add or remove them: N, Mean, Std Dev, Min, Max, Range, Sum, Median, Quantiles, % of Total, Column %, Row %, N Missing, Mode, Variance, Std Err, CV, Interquartile Range.', 'Without the mouse: select a column in the list, then Add to Rows, Nest in Rows, Add to Columns or Analysis Column; Enter adds it to the rows (categorical) or as an analysis column.'] },
          { heading: 'The control panel', choices: [
            ['Columns', 'The table\'s columns. Drag one to a drop zone, or click it and press a button under the list; double-click (or Enter) adds a categorical column to the rows and a continuous one as an analysis column.'],
            ['Add to Rows', 'The selected column becomes a new block of rows, after those there.'],
            ['Nest in Rows', 'The selected column is nested in the last block of rows: a row for each combination of their levels.'],
            ['Add to Columns', 'The selected column becomes a new block of columns: a column of cells for each of its levels.'],
            ['Analysis Column', 'The selected column\'s statistics fill the cells; a continuous column goes here wherever it is dropped, and several stand side by side.'],
            ['Drop zones', 'The drop zones for columns and for rows take nominal and ordinal columns (dropped on a column already there, nested in it); Analysis columns takes continuous ones. × on a column takes it out.'],
            ['Statistics', 'Click a statistic to add it or take it away; each gives a column of cells. N counts the rows (with an analysis column, its values that are not missing); % of Total, Column % and Row % are a cell\'s share of the whole table, of its column or of its row (of the rows, or of the analysis column\'s sum). The others need an analysis column: Mean, Std Dev, Min, Max, Range, Sum, Median, Quantiles (JMP\'s definition), N Missing, Mode, Variance, Std Err, CV and Interquartile Range.'],
            ['All row (totals)', 'Adds a row for all the rows together, after the others.'],
            ['All column (totals)', 'Adds a column of cells for all the rows together, after the others.'],
            ['Include missing for grouping columns', 'A missing value in a row or column grouping becomes a level of its own. Off (the default, as in JMP): a row with a missing grouping value is left out of the whole table.'],
            ['Freq', 'A numeric column of counts: each row counts that many times; rows with a missing, zero or negative count are left out.'],
            ['Quantiles (%)', 'Shown with the Quantiles statistic: the percents, separated by commas (default 25, 75).'],
            ['Clear', 'Starts again: every zone emptied, Freq and the totals off, the statistics back to N.'],
            ['Done', 'Hides the control panel and keeps the table.'],
          ] },
          { heading: 'Totals and missing values', text: 'All row and All column add the totals. A row with a missing value in a grouping column is left out of the whole table unless Include missing for grouping columns is on; excluded rows are left out too. Freq counts each row that many times.' },
          { heading: 'Done', text: 'Done hides the control panel, as in JMP; the red triangle\'s Show Control Panel brings it back. Right click the table to copy it or make it into a data table.' },
          { heading: 'The red triangle', choices: [
            ['Show Control Panel', 'Shows the control panel again, or hides it as Done does.'],
            ['Add All Row, Add All Column', 'The totals, as the boxes in the panel.'],
            ['Include missing for grouping columns', 'As the box in the panel.'],
            ['Make Into Data Table', 'The table as a new data table, its row levels and its cells as columns.'],
          ] },
        ],
        more: { label: 'Tabulate', id: 'help-p-tabulate' },
      },
    },
    title: () => 'Tabulate',
    triangle(ctx) {
      return [
        ctx.check('Show Control Panel', 'panel', null, true),
        { label: 'Add All Row', checked: !!tabState(ctx).allRows, action: () => { const s = tabState(ctx); s.allRows = !s.allRows; ctx.set('tab', s); } },
        { label: 'Add All Column', checked: !!tabState(ctx).allCols, action: () => { const s = tabState(ctx); s.allCols = !s.allCols; ctx.set('tab', s); } },
        { label: 'Include missing for grouping columns', checked: !!tabState(ctx).missing, action: () => { const s = tabState(ctx); s.missing = !s.missing; ctx.set('tab', s); } },
        { label: 'Make Into Data Table', action: () => { const tbl = ctx.report.body.querySelector('table.smt-table'); if (tbl && tbl._rt) SM.app.addTable(SM.report.tableFromRT(tbl._rt, uniqueTable(`Tabulate of ${ctx.table.name}`))); else toast('Build a table first'); } },
      ];
    },
    async render(ctx) {
      const t = ctx.table;
      if (ctx.opt('tab', null) == null) {
        // Start from the columns selected in the table: categorical ones as rows, continuous ones as analysis columns.
        const s = emptyTab();
        for (const c of SM.app ? SM.app.selectedColumns() : []) {
          if (c.isCategorical) s.rows.push([{ id: c.id, name: c.name }]); else s.analysis.push({ id: c.id, name: c.name });
        }
        if (s.analysis.length) s.stats = ['N', 'Mean'];
        ctx.set('tab', s, null, { rerun: false });
      }
      const state = tabState(ctx);
      if (ctx.opt('panel', true)) ctx.container.append(tabBuilder(ctx, state));
      const chains = (list) => list.map((ch) => ch.map((r) => resolveRef(t, r)).filter(Boolean).map((c) => c.name)).filter((ch) => ch.length);
      const rows = chains(state.rows), cols = chains(state.cols);
      const analysis = state.analysis.map((r) => resolveRef(t, r)).filter(Boolean).map((c) => c.name);
      const out = el('div', { class: 'smt-result' });
      ctx.container.append(out);
      if (!rows.length && !cols.length && !analysis.length) {
        out.append(ctx.note(ctx.opt('panel', true) ? 'Drag columns into the drop zones: a nominal or ordinal column into the rows or the columns, continuous columns as analysis columns. The table grows as you build it.' : 'The table is empty: turn on Show Control Panel in the red triangle.'));
        return;
      }
      const fc = resolveRef(t, state.freq);
      const res = await ctx.call('tables.tabulate', { row_chains: rows, col_chains: cols, analysis, stats: state.stats, all_rows: !!state.allRows, all_cols: !!state.allCols, include_missing: !!state.missing, quantiles: state.quantiles && state.quantiles.length ? state.quantiles : [25, 75], freq: fc ? fc.name : null, where: ctx.where || [] });
      out.append(tabResult(ctx, res));
      if (!res.n) out.append(ctx.warn('No rows to tabulate: every row is excluded or has a missing grouping value.'));
      out.append(ctx.note(`${res.n} rows${fc ? `, each counted ${fc.name} times` : ''}.${state.missing ? '' : ' Rows with a missing grouping value are left out.'}`), ctx.code(res.code));
    },
  });

  /* ---- Cols > Columns Viewer ---------------------------------------------------------------------------------- */
  SM.platforms.register({
    id: 'colviewer', label: 'Columns Viewer', menu: 'Cols', order: 210, launch: null, info: 'p:colviewer',
    about: 'A summary of every column: N, N Missing, N Categories, Min, Max, Mean, Std Dev, Median and the quartiles (JMP\'s definition); select columns and press Distribution to describe them.',
    uses: ['numpy.quantile(method="weibull")', 'pandas'],
    topics: {
      'p:colviewer': {
        kicker: 'Cols', title: 'Columns Viewer',
        lead: 'One line per column with its counts and, for continuous columns, the mean, standard deviation, median and quartiles. Excluded rows are left out.',
        sections: [
          { heading: 'Using it', list: ['Click lines to select columns (they are selected in the data table too).', 'Distribution opens Analyze > Distribution with the selected columns, or all of them.', 'The quartiles are JMP\'s: numpy\'s weibull method, the (n+1)p-th value.'] },
          { heading: 'In the report', choices: [
            ['A line of the table', 'Click it to select that column, and again to unselect it; the columns are selected in the data table too.'],
            ['Distribution', 'Opens Analyze > Distribution with the selected columns (every column when none is selected).'],
            ['Clear Select', 'Unselects every column.'],
            ['Select All', 'Selects every column.'],
          ] },
          { heading: 'The table', choices: [
            ['N, N Missing', 'How many values of the column are there and how many are missing, in the included rows.'],
            ['N Categories', 'The number of distinct values.'],
            ['Min, Max', 'The smallest and the largest value of a numeric column.'],
            ['Mean, Std Dev, Median, Lower Quartile, Upper Quartile', 'For continuous columns: the mean, the standard deviation (n − 1), the median and the quartiles.'],
          ] },
          { heading: 'The red triangle', text: 'Distribution of Selected does what the Distribution button does; Clear Select unselects every column.' },
        ],
        more: { label: 'Columns Viewer', id: 'help-p-colviewer' },
      },
    },
    title: () => 'Columns Viewer',
    triangle(ctx) { return [{ label: 'Distribution of Selected', action: () => colviewerDistribution(ctx) }, { label: 'Clear Select', action: () => ctx.set('sel', []) }]; },
    async render(ctx) {
      const t = ctx.table;
      const res = await ctx.call('tables.colviewer', { columns: t.columns.map((c) => c.name) });
      const sel = new Set(ctx.opt('sel', []));
      const rows = res.rows.map((r) => {
        const c = t.col(r.column);
        const o = { ...r };
        if (c && c.isNumeric && c.format && /date/.test(c.format.kind || '')) for (const k of ['min', 'max', 'mean', 'median', 'lq', 'uq']) if (typeof o[k] === 'number') o[k] = cellText(c, o[k]);
        if (c && c.isNumeric && c.format && /date/.test(c.format.kind || '') && typeof o.sd === 'number') o.sd = `${fmt(o.sd / 86400000)} days`;
        return o;
      });
      const bar = el('div', { class: 'smt-cvbar' });
      const b = (label, fn, primary) => { const x = el('button', { type: 'button', class: `sm-btn small${primary ? ' primary' : ''}`, text: label }); x.addEventListener('click', fn); return x; };
      const count = el('span', { class: 'sm-ob-note' });
      const syncGrid = () => {
        count.textContent = sel.size ? `${sel.size} selected` : 'Click lines to select columns';
        const g = SM.app && SM.app.grids.get(t.id);
        if (g) { g.colSel.clear(); for (const nm of sel) { const c = t.col(nm); if (c) g.colSel.add(c.id); } g.refresh(); SM.app.emit('columnselection', g.selectedColumns()); }
      };
      bar.append(b('Distribution', () => colviewerDistribution(ctx), true), b('Clear Select', () => { sel.clear(); ctx.set('sel', [], null, { rerun: false }); mark(); syncGrid(); }), b('Select All', () => { for (const r of rows) sel.add(r.column); ctx.set('sel', [...sel], null, { rerun: false }); mark(); syncGrid(); }), count);
      const tbl = ctx.rt({ columns: res.table.columns, rows }, {
        name: 'Columns Viewer', className: 'smt-cv',
        onRow: (r) => { if (sel.has(r.column)) sel.delete(r.column); else sel.add(r.column); ctx.set('sel', [...sel], null, { rerun: false }); mark(); syncGrid(); },
      });
      const mark = () => tbl.querySelectorAll('tbody tr').forEach((tr) => { const name = tr.firstChild && tr.firstChild.textContent; tr.classList.toggle('is-picked', sel.has(name)); tr.setAttribute('aria-selected', String(sel.has(name))); });
      new MutationObserver(mark).observe(tbl.querySelector('tbody'), { childList: true });
      mark();
      count.textContent = sel.size ? `${sel.size} selected` : 'Click lines to select columns';
      const o = ctx.outline('Summary Statistics', { key: 'cv', info: 'p:colviewer' });
      o.add(bar, tbl, ctx.note(`${ctx.rows.length} rows (excluded rows left out). Mean, Std Dev and the quartiles for continuous columns; N Categories counts the distinct values.`), ctx.code(res.code));
    },
  });

  function colviewerDistribution(ctx) {
    const t = ctx.table;
    const names = ctx.opt('sel', []);
    const cols = (names.length ? names.map((n) => t.col(n)) : t.columns).filter(Boolean);
    const p = SM.platforms.get('distribution');
    if (!p) { toast('Distribution is not loaded'); return; }
    SM.app.openReport(p, { roles: { y: cols.map((c) => c.id) }, options: {} }, t);
  }

  /* ---- Analyze > Screening > Explore Missing Values ------------------------------------------------------------ */
  /* The snapshot as matplotlib code under it: from a CSV export of the table,
     as the notebook runs it, the report's rows (the By group's where lines, the
     rows left out dropped), a mark for each missing cell, the light theme's
     colours and the graph's size at 100 pixels an inch; the mark size is the
     page's choice. */
  const J = JSON.stringify;
  const pyNum = (v) => (Number.isFinite(v) ? String(v) : Number.isNaN(v) ? 'float("nan")' : v > 0 ? 'float("inf")' : '-float("inf")');
  const pyLit = (v) => (typeof v === 'number' ? pyNum(v) : J(String(v)));
  function keepLines(ctx) {
    const t = ctx.table, where = ctx.where || [];
    const L = where.map((w) => `df = df[df[${J(w.column)}] == ${pyLit(w.value)}]   # only the rows where ${w.column} is ${SM.grid.cellText(t.col(w.column), w.value)}`);
    const wc = where.map((w) => t.col(w.column));
    const keep = new Set(ctx.rows), drop = [];
    for (let r = 0; r < t.nrows; r++) if (!keep.has(r) && where.every((w, k) => wc[k] && wc[k].values[r] === w.value)) drop.push(r);
    if (!drop.length) return L;
    if (!where.length && ctx.rows.length <= t.nrows / 2) return [`df = df.loc[[${ctx.rows.join(', ')}]]   # the rows of the report`];
    return [...L, `df = df.drop(index=[${drop.join(', ')}])   # the rows the report leaves out`];
  }
  function snapshotCode(ctx, cols, { width, height, size, color }) {
    return [SM.report.codeHead(ctx.table.name, ['import matplotlib.pyplot as plt']), ...keepLines(ctx),
      `cols = ${J(cols.map((c) => c.name))}`,
      'r, j = np.nonzero(df[cols].isna().to_numpy())   # each missing cell: its row and column, row by row as the page draws them',
      `fig, ax = plt.subplots(figsize=(${Math.round(width) / 100}, ${Math.round(height) / 100}), layout="constrained")`,
      `ax.scatter(j, df.index[r] + 1, marker="s", s=${Math.round(100 * (size * 0.72) ** 2) / 100}, color="${color}", linewidths=0)   # a mark at the row number (1, 2, ...) and the column`,
      'ax.set_xticks(range(len(cols)), cols)', 'ax.set_xlim(-0.6, len(cols) - 0.4)', 'ax.invert_yaxis()   # the first row at the top',
      'ax.set_ylabel("Row")', 'ax.set_title("Missing value snapshot")', 'plt.show()'].join('\n');
  }

  function missingRows(ctx, cols, fn) {
    const out = [];
    for (const r of ctx.rows) if (fn(cols.map((c) => isMissing(c.values[r])))) out.push(r);
    return out;
  }

  async function imputeFrom(ctx, method) {
    const t = ctx.table;
    const cols = ctx.roles('y').filter((c) => c.isNumeric);
    if (!cols.length) { toast('Imputation takes numeric columns'); return; }
    if ((method === 'mvn' || method === 'mice') && cols.length < 2) { toast('This imputation needs two or more numeric columns'); return; }
    const labels = { mean: 'Mean', median: 'Median', mvn: 'Multivariate Normal (EM)', mice: 'Chained Equations (MICE)' };
    const v = await SM.ui.form({
      title: `Impute: ${labels[method]}`, info: 'p:missing',
      lead: method === 'mvn' ? 'Each missing value becomes its expected value given the row\'s other values, under a multivariate normal whose mean and covariance are estimated by EM from all the rows (maximum likelihood).'
        : method === 'mice' ? 'statsmodels\' MICEData: each column in turn is fitted on the others and its missing values drawn by predictive mean matching; the seed makes it repeatable.'
          : `Each missing value becomes the column's ${method} over the rows of the report.`,
      fields: [
        { key: 'where', label: 'Save', type: 'select', value: 'new', choices: [['new', 'as new columns (Imputed[x])'], ['inplace', 'in place, in the columns themselves']], help: '**As new columns** (the default): a column Imputed[x] beside each column, with its missing values filled and the original kept; **in place**: the missing cells of the columns themselves are filled (a formula column\'s go to a new column). Edit > Undo takes either back.' },
        ...(method === 'mice' ? [{ key: 'seed', label: 'Seed', type: 'number', value: 1, help: 'numpy\'s random seed, set before MICEData runs, so the same seed gives the same imputed values: a whole number, 0 or more (anything else is taken as 1).' }, { key: 'iter', label: 'Cycles', type: 'number', value: 10, help: 'How many times MICEData goes round all the columns (its update_all), 1 to 100 (default 10): each time, every column with missing values is fitted on the others and its missing values drawn again by predictive mean matching.' }] : []),
      ],
    });
    if (!v) return;
    try {
      const res = await SM.engine.call('tables.impute', { columns: cols.map((c) => c.name), method, rows: ctx.rows, seed: Number.isInteger(v.seed) && v.seed >= 0 ? v.seed : 1, n_iter: Math.max(1, Math.min(100, v.iter || 10)) }, t);
      record(t, `Impute (${labels[method]})`);
      const rows = res.rows;
      let n = 0;
      for (const r of res.columns) {
        const c = t.col(r.name);
        n += r.imputed;
        if (v.where === 'inplace') {
          if (c.formula) { toast(`${c.name} is a formula column; its imputed values go to a new column`); }
          else { rows.forEach((row, k) => { if (isMissing(c.values[row])) c.values[row] = r.values[k]; }); continue; }
        }
        const vals = new Array(t.nrows).fill(NaN);
        for (let i = 0; i < t.nrows; i++) vals[i] = c.values[i];
        rows.forEach((row, k) => { vals[row] = r.values[k]; });
        t.addColumn({ ...specOf(c, vals), name: t.uniqueName(`Imputed[${c.name}]`), formula: null, role: null, notes: `${c.name} with its ${r.imputed} missing values imputed (${labels[method]})` }, t.colIndex(c) + 1);
      }
      if (v.where === 'inplace') t._changed('data', { imputed: true });
      toast(`Imputed ${n} values (${labels[method]})`);
    } catch (e) { fail('Impute')(e); }
  }

  SM.platforms.register({
    id: 'missing', label: 'Explore Missing Values', menu: 'Analyze/Screening', order: 20, info: 'p:missing',
    about: 'Where the missing values are: counts by column and by pattern, a snapshot of every row, selection and exclusion of the rows with missing values, and imputation by the mean, the median, a multivariate normal (EM) or chained equations (statsmodels MICEData).',
    uses: ['statsmodels.imputation.mice.MICEData', 'numpy (EM for the multivariate normal)', 'pandas'],
    topics: {
      'p:missing': {
        kicker: 'Analyze > Screening', title: 'Explore Missing Values',
        lead: 'How many values are missing in each column, which combinations of columns are missing together, and ways to fill them in.',
        sections: [
          { heading: 'Reports', choices: [['Missing Columns Report', 'Each column\'s number and percent of missing values; click a line to select those rows.'], ['Missing Value Report', 'Each pattern of missing columns and how many rows have it; click a line to select its rows.'], ['Missing Value Snapshot', 'A cell plot: a mark for each missing cell, row by row; drag over it to select rows.']] },
          { heading: 'Imputation', choices: [['Mean, Median', 'The column\'s mean or median over the report\'s rows.'], ['Multivariate Normal', 'The conditional expectation of the missing values given the observed ones, with the mean and covariance estimated by EM (maximum likelihood) from all rows.'], ['Chained Equations', 'statsmodels\' MICEData: predictive mean matching, column by column, for the cycles asked for, from a seed.']] },
          { heading: 'In place or new', text: 'Imputed values go to new columns Imputed[x], or into the columns themselves; Edit > Undo takes them back.' },
          { heading: 'Buttons', choices: [
            ['Select Rows with Missing', 'Selects the report\'s rows that have a missing value in any of its columns.'],
            ['Exclude Rows with Missing', 'Excludes those rows in the table, so that analyses leave them out (Edit > Undo takes it back).'],
            ['Impute ▾', 'Fills the missing values of the numeric columns: Mean, Median, Multivariate Normal Imputation or Chained Equations (MICE); a dialog asks where the values go.'],
          ] },
          { heading: 'The red triangle', text: 'Shows or hides each of the three reports, and has the same Select, Exclude and Impute as the buttons.' },
        ],
        more: { label: 'Explore Missing Values', id: 'help-p-missing' },
      },
    },
    launch: {
      lead: 'Choose the columns to look at. Imputation works on the numeric ones.',
      roles: [{ key: 'y', label: 'Y, Columns', min: 1, hint: 'required', help: 'The columns to look at: their missing values are counted by column and by pattern, and drawn row by row. Imputation fills the numeric ones among them.' }, { key: 'by', label: 'By', hint: 'optional', help: 'A separate report for each level of the By columns; an imputation from a report then uses that group\'s rows.' }],
    },
    title: () => 'Explore Missing Values',
    triangle(ctx) {
      const cols = ctx.roles('y');
      return [
        ctx.check('Missing Columns Report', 'colsReport', null, true),
        ctx.check('Missing Value Report', 'patReport', null, true),
        ctx.check('Missing Value Snapshot', 'snapshot', null, true),
        { separator: true },
        { label: 'Select Rows with Missing', action: () => ctx.table.select(missingRows(ctx, cols, (m) => m.some(Boolean))) },
        { label: 'Exclude Rows with Missing', action: () => { const r = missingRows(ctx, cols, (m) => m.some(Boolean)); record(ctx.table, 'Exclude Rows with Missing'); ctx.table.setState(r, 'excluded', true); toast(`Excluded ${r.length} rows`); } },
        { separator: true },
        { label: 'Impute', submenu: () => [
          { label: 'Mean', action: () => imputeFrom(ctx, 'mean') }, { label: 'Median', action: () => imputeFrom(ctx, 'median') },
          { label: 'Multivariate Normal Imputation', action: () => imputeFrom(ctx, 'mvn') }, { label: 'Chained Equations (MICE)', action: () => imputeFrom(ctx, 'mice') },
        ] },
      ];
    },
    async render(ctx) {
      const t = ctx.table;
      const cols = ctx.roles('y');
      const res = await ctx.call('tables.missing_report', { columns: cols.map((c) => c.name), where: ctx.where || [] });
      const b = (label, fn) => { const x = el('button', { type: 'button', class: 'sm-btn small', text: label }); x.addEventListener('click', fn); return x; };
      const menu = (label, items) => { const x = el('button', { type: 'button', class: 'sm-btn small', text: `${label} ▾`, 'aria-haspopup': 'menu' }); x.addEventListener('click', () => SM.ui.menu(items(), x, { returnFocus: x })); return x; };
      ctx.container.append(el('div', { class: 'smt-mvbar' },
        b('Select Rows with Missing', () => t.select(missingRows(ctx, cols, (m) => m.some(Boolean)))),
        b('Exclude Rows with Missing', () => { const r = missingRows(ctx, cols, (m) => m.some(Boolean)); record(t, 'Exclude Rows with Missing'); t.setState(r, 'excluded', true); toast(`Excluded ${r.length} rows`); }),
        menu('Impute', () => [{ label: 'Mean', action: () => imputeFrom(ctx, 'mean') }, { label: 'Median', action: () => imputeFrom(ctx, 'median') }, { label: 'Multivariate Normal Imputation', action: () => imputeFrom(ctx, 'mvn') }, { label: 'Chained Equations (MICE)', action: () => imputeFrom(ctx, 'mice') }]), infoSlot('p:missing')));
      ctx.container.append(ctx.kv([['Rows', res.n, 'int'], ['Rows with a missing value', res.rows_with_missing, 'int'], ['Missing cells', res.cells_missing, 'int'], ['Percent of cells', res.n && cols.length ? 100 * res.cells_missing / (res.n * cols.length) : null]]));
      if (ctx.opt('colsReport', true)) {
        const o = ctx.outline('Missing Columns Report', { key: 'cols' });
        o.add(ctx.rt({ columns: [{ key: 'column', label: 'Column', fmt: 'text' }, { key: 'n_missing', label: 'Number Missing', fmt: 'int' }, { key: 'pct', label: 'Percent Missing', digits: 2 }], rows: res.columns },
          { onRow: (r) => { const c = t.col(r.column); if (c) t.select(ctx.rows.filter((i) => isMissing(c.values[i]))); } }), ctx.note('Click a line to select the rows where that column is missing.'));
      }
      if (ctx.opt('patReport', true)) {
        const o = ctx.outline('Missing Value Report', { key: 'patterns' });
        o.add(ctx.rt({ columns: [{ key: 'count', label: 'Count', fmt: 'int' }, { key: 'n_missing', label: 'Number of Columns Missing', fmt: 'int' }, { key: 'pattern', label: 'Pattern', fmt: 'text' }, { key: 'names', label: 'Columns Missing', fmt: 'text' }], rows: res.patterns.map((p) => ({ ...p, names: p.columns.join(', ') || '(none)' })) },
          { onRow: (r) => t.select(missingRows(ctx, cols, (m) => m.map((x) => (x ? '1' : '0')).join('') === r.pattern)) }),
        ctx.note(`A pattern has a 1 for each missing column, in the order ${cols.map((c) => c.name).join(', ')}. Click a line to select its rows.`), ctx.code(res.code));
      }
      if (ctx.opt('snapshot', true)) {
        const o = ctx.outline('Missing Value Snapshot', { key: 'snapshot' });
        const xs = [], ys = [], rows = [];
        for (const r of ctx.rows) cols.forEach((c, j) => { if (isMissing(c.values[r])) { xs.push(j); ys.push(r + 1); rows.push(r); } });
        if (!xs.length) o.add(ctx.note('No missing values in these columns.'));
        else if (xs.length > 60000) o.add(ctx.note(`${xs.length} missing cells: too many to draw one by one. Use the reports above.`));
        else {
          const h = Math.max(220, Math.min(560, 90 + Math.min(ctx.rows.length, 900) * 0.5));
          const w = Math.max(300, Math.min(760, 120 + 70 * cols.length));
          const size = Math.max(3, Math.min(9, 420 / Math.max(10, ctx.rows.length ** 0.5 * 3)));
          o.add(ctx.plot([{ type: xs.length > 4000 ? 'scattergl' : 'scatter', mode: 'markers', x: xs, y: ys, rows, marker: { symbol: 'square', size, color: SM.util.themeColors().text }, hovertemplate: '%{text}<extra></extra>', text: xs.map((j, k) => `row ${ys[k]}: ${cols[j].name} missing`), name: 'missing' }],
            { xaxis: { tickvals: cols.map((_, j) => j), ticktext: cols.map((c) => c.name), range: [-0.6, cols.length - 0.4], showgrid: false, zeroline: false }, yaxis: { autorange: 'reversed', title: { text: 'Row' }, zeroline: false } },
            { width: w, height: h, title: 'Missing value snapshot' }),
          ctx.code(snapshotCode(ctx, cols, { width: w, height: h, size, color: '#352921' })),
          ctx.note('A mark for each missing cell. Drag over marks to select their rows; selected rows show in the accent colour.'));
        }
      }
    },
  });

  /* ---- File > Python Script… --------------------------------------------------------------------------------- */
  const SCRIPT_EXAMPLES = [
    ['Describe the table', 'print(df.describe(include="all"))'],
    ['Group means', 'result = df.groupby(df.columns[1], observed=True).mean(numeric_only=True).reset_index()\nprint(result)'],
    ['A regression (statsmodels formula)', '# Q("...") quotes a column name with spaces or signs\ny, x = df.columns[-1], df.columns[-2]\nfit = smf.ols(f\'Q("{y}") ~ Q("{x}")\', data=df).fit()\nprint(fit.summary())\nresult = pd.DataFrame({"term": fit.params.index, "estimate": fit.params.values, "p": fit.pvalues.values})'],
    ['A t test (scipy)', 'x = df.select_dtypes("number").iloc[:, 0].dropna()\nprint(stats.ttest_1samp(x, popmean=0))'],
  ];
  const DEFAULT_SCRIPT = '# df is the table: its included rows, columns by their names\nprint(df.shape)\nprint(df.head())\n';
  const outputs = new WeakMap();   // report -> the last run's output
  const typed = new WeakSet();     // reports whose code was typed or opened in this session
  let opening = false;             // set while File > Python Script opens its report

  function lastScript() { try { return localStorage.getItem('smui.pyscript') || DEFAULT_SCRIPT; } catch (e) { return DEFAULT_SCRIPT; } }

  function openScript(app) {
    const t = app.requireTable();
    if (!t) return;
    const p = SM.platforms.get('pyscript');
    opening = true;
    try {
      const r = app.openReport(p, { roles: {}, options: { code: lastScript() } }, t);
      typed.add(r);
      return r;
    } finally { opening = false; }
  }

  function renderOutput(box, out) {
    box.replaceChildren();
    if (!out) { box.append(el('p', { class: 'sm-ob-note', text: 'Nothing has run yet: press Run (or ctrl/⌘+Enter).' })); return; }
    if (out.running) { box.append(el('p', { class: 'sm-ob-note', text: 'Running…' })); return; }
    box.append(el('p', { class: 'sm-ob-note', text: `Ran at ${out.at} on ${out.rows} rows${out.error ? '' : ', without an error'}.` }));
    if (out.stdout) box.append(el('pre', { class: 'smp-stdout', text: out.stdout }));
    if (out.warnings && out.warnings.length) for (const w of out.warnings) box.append(el('div', { class: 'sm-ob-warn', text: w }));
    if (out.error) {
      const e = el('div', { class: 'sm-ob-error', role: 'alert' }, el('strong', { text: out.error }));
      if (out.traceback) e.append(el('pre', { class: 'smp-tb', text: out.traceback }));
      box.append(e);
    }
    if (out.result) {
      const btn = el('button', { type: 'button', class: 'sm-btn small primary', text: 'Make into Data Table' });
      btn.addEventListener('click', () => {
        const nt = fromBackend(out.result, { name: uniqueTable('Python result'), source: 'File > Python Script: result' });
        SM.app.addTable(nt);
      });
      box.append(el('div', { class: 'smp-result' }, el('span', { text: `result is a ${out.result_type} of ${out.result.nrows} rows × ${out.result.columns.length} columns. ` }), btn));
      if (out.result_repr) box.append(el('pre', { class: 'smp-stdout', text: out.result_repr }));
    } else if (out.result_type) box.append(el('p', { class: 'sm-ob-note', text: `result is a ${out.result_type}: ${out.result_repr || ''}. A DataFrame (or Series) could be made into a data table.` }));
  }

  SM.platforms.register({
    id: 'pyscript', label: 'Python Script', hidden: true, launch: null,
    about: 'Python run against the table as a pandas DataFrame, with numpy, pandas, statsmodels and scipy.stats imported; prints are shown, and a DataFrame left in result can become a data table.',
    uses: ['exec, io.StringIO, contextlib.redirect_stdout'],
    title: () => 'Python Script',
    triangle(ctx) {
      return [{ label: 'Insert Example', submenu: () => SCRIPT_EXAMPLES.map(([label, code]) => ({ label, action: () => { ctx.set('code', code); } })) }, { label: 'Clear Output', action: () => { outputs.delete(ctx.report); ctx.report.run(); } }];
    },
    async render(ctx) {
      const t = ctx.table;
      const rep = ctx.report;
      if (opening) typed.add(rep);
      const code = String(ctx.opt('code', DEFAULT_SCRIPT));
      const ed = el('textarea', { class: 'smp-code', rows: 14, spellcheck: 'false', autocapitalize: 'off', autocomplete: 'off', 'aria-label': 'Python code', wrap: 'off' });
      ed.value = code;
      const save = SM.util.debounce(() => { ctx.set('code', ed.value, null, { rerun: false }); try { localStorage.setItem('smui.pyscript', ed.value); } catch (e) { /* private window */ } }, 250);
      ed.addEventListener('input', () => { typed.add(rep); save(); });
      ed.addEventListener('keydown', (ev) => {
        if (ev.key === 'Tab' && !ev.altKey && !ev.ctrlKey && !ev.metaKey) {
          ev.preventDefault();
          const s = ed.selectionStart, e = ed.selectionEnd;
          const v = ed.value;
          if (!ev.shiftKey && s === e) ed.setRangeText('    ', s, e, 'end');
          else {
            // indent or dedent the lines of the selection
            const a = v.lastIndexOf('\n', s - 1) + 1;
            const b = e > s && v[e - 1] === '\n' ? e - 1 : e;
            const lines = v.slice(a, b).split('\n');
            const next = lines.map((l) => (ev.shiftKey ? l.replace(/^ {1,4}/, '') : `    ${l}`)).join('\n');
            ed.setRangeText(next, a, b, 'select');
          }
          typed.add(rep);
          save();
        } else if (ev.key === 'Enter' && (ev.metaKey || ev.ctrlKey)) { ev.preventDefault(); runBtn.click(); }
      });
      const outBox = el('div', { class: 'smp-out', 'aria-live': 'polite' });
      const runBtn = el('button', { type: 'button', class: 'sm-btn primary', text: 'Run' });
      runBtn.addEventListener('click', async () => {
        ctx.set('code', ed.value, null, { rerun: false });
        try { localStorage.setItem('smui.pyscript', ed.value); } catch (e) { /* private window */ }
        typed.add(rep);
        const rows = ctx.rows.length === t.nrows ? null : ctx.rows;
        outputs.set(rep, { running: true });
        renderOutput(outBox, outputs.get(rep));
        runBtn.disabled = true;
        try {
          const r = await SM.engine.call('tables.run_script', { code: ed.value, rows }, t);
          outputs.set(rep, { ...r, rows: rows ? rows.length : t.nrows, at: new Date().toLocaleTimeString() });
        } catch (e) {
          outputs.set(rep, { error: e.message, traceback: e.traceback || null, rows: ctx.rows.length, at: new Date().toLocaleTimeString() });
        } finally {
          runBtn.disabled = false;
        }
        renderOutput(outBox, outputs.get(rep));
        warnBox.hidden = true;
      });
      const ex = el('button', { type: 'button', class: 'sm-btn', text: 'Examples ▾', 'aria-haspopup': 'menu' });
      ex.addEventListener('click', () => SM.ui.menu(SCRIPT_EXAMPLES.map(([label, c]) => ({ label, action: () => { ed.value = c; typed.add(rep); save(); ed.focus(); } })), ex, { returnFocus: ex }));
      const warnBox = el('div', { class: 'sm-ob-warn', text: 'This code came with a saved project or file. Read it before you run it: Python here can do whatever this page can do in the browser.', hidden: typed.has(rep) });
      const o = ctx.outline('Script', { key: 'editor', info: 'cmd:pyscript' });
      o.add(ctx.note(`df is ${t.name}: ${ctx.rows.length} rows (excluded rows left out), the columns by their names, nominal and ordinal columns as pandas Categoricals, dates as milliseconds since 1970. np, pd, sm (statsmodels.api), smf (statsmodels.formula.api) and stats (scipy.stats) are imported. Set result to a DataFrame to make it a data table. The code runs only when you press Run, each time in a fresh namespace.`),
        warnBox, ed, el('div', { class: 'smp-bar' }, runBtn, ex, el('span', { class: 'sm-ob-note', text: 'Tab indents; ctrl/⌘+Enter runs.' })));
      const out = ctx.outline('Output', { key: 'output' });
      out.add(outBox);
      renderOutput(outBox, outputs.get(rep));
      rep.pyCode.push(`# The script, run against df (the table's rows)\n${ed.value}`);
    },
  });

  /* ---- the commands, in the menus --------------------------------------------------------------------------------- */
  const hasTable = (app) => !!app.current;
  const TOPICS = {
    'cmd:summary': { kicker: 'Tables', title: 'Summary', lead: 'A new table with one row per group (the levels of the Group columns, in their value order; a missing value makes its own group): N Rows and the statistics you tick for each Statistics Column.', sections: [
      { heading: 'Statistics', text: 'N, Mean, Std Dev, Min, Max, Range, Sum, Median, Quantiles (JMP\'s definition, numpy\'s weibull; give the percents), N Missing, N Categories, % of Total (the group\'s share of the column\'s sum), CV, Std Err, Variance, Geometric Mean, Interquartile Range, Mode. Character columns get N, N Missing, N Categories, % of Total and Mode.' },
      { heading: 'Subgroup, Weight, Freq', text: 'Subgroup puts a column per level side by side. Freq repeats a row; Weight weights the mean and the spread as statsmodels\' DescrStatsW does, as Distribution does.' },
      { heading: 'Linked', text: 'Selecting rows of the summary selects their rows in the source table.' }] },
    'cmd:subset': { kicker: 'Tables', title: 'Subset', lead: 'A new table from the selected rows, all rows or a random sample (a rate or a count, within each level of the Stratify columns), with all columns or some. Subset By makes one table per level.', sections: [{ heading: 'Formulas and row states', text: 'Copy formula keeps formula columns whose columns come along (their Col functions are then over the subset); Suppress formula evaluation keeps the values as they were. Keep row states copies selection, exclusion, colours and markers.' }] },
    'cmd:sort': { kicker: 'Tables', title: 'Sort', lead: 'Sort by one or more columns, the first one first; the arrow beside each turns it descending. Nominal and ordinal columns sort in their value order; missing values go last. A new table, or Replace table to sort this one (Edit > Undo takes it back).' },
    'cmd:stack': { kicker: 'Tables', title: 'Stack', lead: 'Columns into rows: the Label column says which column a value came from, the Data column holds it; the non-stacked columns are repeated (Keep All), left out (Drop All) or those in Keep Columns. Stack by Row keeps each row\'s values together; the ID column numbers the source rows.' },
    'cmd:split': { kicker: 'Tables', title: 'Split', lead: 'Rows into columns, the opposite of Stack: a new column for each level of Split By, holding the values of the Split Columns, one row for each level of the Group columns. A level that appears twice in a group starts a second row; without Group, rows are matched by their order.' },
    'cmd:transpose': { kicker: 'Tables', title: 'Transpose', lead: 'Rows become columns: a row for each transposed column (its name in the Label column) and a column for each row, named by the Label column\'s values or Row 1, Row 2… By transposes each level separately. Mixed numeric and text columns give text.' },
    'cmd:concatenate': { kicker: 'Tables', title: 'Concatenate', lead: 'The rows of several tables one after another, their columns matched by name; a column a table lacks is missing in its rows. Create source column adds the table each row came from; Append to first table adds the rows to the first table instead of making a new one (Edit > Undo takes it back). Formulas are not copied.', sections: [
      { heading: 'Fields', choices: [
        ['Data tables to be concatenated', 'Tick the tables whose rows go in, two or more (the first two are ticked at the start); their rows follow one another in the order listed, the current table first.'],
        ['Create source column', 'Adds a Source Table column holding the name of the table each row came from.'],
        ['Append to first table', 'Adds the other tables\' rows to the first table itself, with the columns it lacks, instead of making a new table; Edit > Undo takes it back.'],
        ['Output table name', 'The new table\'s name; empty: Concatenated. Not used with Append to first table.'],
      ] }] },
    'cmd:join': { kicker: 'Tables', title: 'Join', lead: 'Rows of two tables side by side: by matching columns (pairs of columns whose values must be equal; a missing value matches nothing), by row number, or every row with every row (Cartesian).', sections: [
      { heading: 'Fields', choices: [
        ['Join with', 'The other table; its columns come after this table\'s.'],
        ['Matching', '**By Matching Columns** (the default): rows whose values are equal in every pair of matching columns; **By Row Number**: row 1 with row 1, row 2 with row 2; **Cartesian Join**: every row of this table with every row of the other.'],
        ['Matching columns', 'Choose a column of each table and press Match to add the pair; a row matches when every pair is equal (compared as text when either column is text), and a missing value matches nothing. A column name both tables share is paired at the start; remove takes a pair away.'],
        ['Include non-matches', '**Main table**: keep this table\'s rows that match nothing (a left join); **With table**: the other table\'s (a right join); both: a full join. Neither (the default): matched rows only, an inner join. By Row Number, they keep the longer table\'s extra rows.'],
        ['Drop multiples', 'By Matching Columns: keep only the first row of each key in that table (as pandas\' drop_duplicates), so that a key matches at most one of its rows.'],
        ['Match flag', 'On (the default): a Match Flag column, 1 for a row from this table only, 2 from the other only, 3 from both.'],
        ['Merge same name columns', 'By Matching Columns, on (the default): one column for each pair of matching columns, the other table\'s value filling the rows only it has; off: both tables\' matching columns are kept. Other columns with the same name in both tables are both kept, each named after its table (x of Students, x of Other).'],
        ['Output table name', 'The new table\'s name; empty: Join of this table with the other.'],
      ] }] },
    'cmd:update': { kicker: 'Tables', title: 'Update', lead: 'Changes the current table: for each row, the first matching row of the other table replaces the values of the columns both have (with Ignore missing, a missing value leaves the old one), and the other table\'s other columns are added. Edit > Undo takes it back.', sections: [
      { heading: 'Fields', choices: [
        ['Update with data from', 'The other table, whose values go into this one.'],
        ['Matching', '**By Matching Columns** (the default): each row takes the values of the first row of the other table that is equal in every pair of matching columns; **By Row Number**: row 1 from row 1, row 2 from row 2.'],
        ['Matching columns', 'Choose a column of each table and press Match to add the pair; a missing value matches nothing. A column name both tables share is paired at the start; remove takes a pair away.'],
        ['Ignore missing', 'On (the default): a missing value in the other table leaves this table\'s value as it is; off, it makes the value missing.'],
        ['Replace columns in main table', '**All** (the default): the columns both tables have, other than the matching ones, take the other table\'s values in the matched rows; **None**: they are left as they are.'],
        ['Add columns from update table', '**All** (the default): the other table\'s columns that this one lacks are added, filled in the matched rows; **None**: no column is added.'],
      ] }] },
    'cmd:missingpattern': { kicker: 'Tables', title: 'Missing Data Pattern', lead: 'A table with one row per pattern of missing values in the chosen columns: Count, the number of columns missing, the pattern (1 for missing, in the columns\' order) and a 0/1 column per column. Selecting a pattern selects its rows in the source table.' },
    'cmd:recode': { kicker: 'Cols', title: 'Recode', lead: 'Give distinct values new values: type them, or use Trim, Collapse Whitespace, Title Case, Lower Case, Upper Case, and Group Similar Values (the same letters and digits ignoring case, accents, spaces and signs; the commonest spelling wins). Old values given one new value merge.', sections: [
      { heading: 'The dialog', choices: [
        ['Old Values, Count', 'Each distinct value of the column in its value order (and Missing, when some rows are), with how many rows have it.'],
        ['New Values', 'Type the new value beside the old one. Old values given the same new value become one; an empty new value makes those rows missing. A numeric column stays numeric when every new value is a number; otherwise the result is text.'],
        ['Filter values', 'Shows only the values whose old or new text holds what you type.'],
        ['Trim Whitespace, Collapse Whitespace', 'Take the spaces off the ends of every new value; Collapse also makes each run of spaces inside one space.'],
        ['Title Case, Lower Case, Upper Case', 'Change the case of the letters of every new value.'],
        ['Group Similar Values', 'Gives values that differ only in case, accents, spaces and signs one new value: the spelling with the most rows.'],
        ['Reset', 'Puts every new value back to its old value.'],
        ['Name', 'The new column\'s name (the column\'s name and 2 at the start); not used In Place.'],
      ] },
      { heading: 'Done', choices: [['New Column', 'A new column beside this one.'], ['In Place', 'This column changes (Edit > Undo takes it back).'], ['Formula Column', 'A new formula column, Match(:x, old, new, …, :x), that follows the column when it changes.']] }] },
    'cmd:newformula': { kicker: 'Cols', title: 'New Formula Column', lead: 'A new formula column next to the column: Transform (Log, Log10, Square Root, Square, Reciprocal, Exp, Standardize, Center, Absolute Value), Row (Lag, Difference, Cumulative Sum, Row Number), Distributional (Rank, Rank Fraction, Normal Quantile), or Combine the selected columns (Sum, Mean, Difference, Ratio). Each is a formula you can open and edit.' },
    'cmd:indicator': { kicker: 'Cols > Utilities', title: 'Make Indicator Columns', lead: 'For a nominal or ordinal column, a 0/1 column per level: 1 where the row has the level, 0 elsewhere, missing where the column is missing. As formula columns, they follow the column.' },
    'cmd:binning': { kicker: 'Cols > Utilities', title: 'Make Binning Column', lead: 'Cut a numeric column into bins: of equal width (rounded widths, or the width you give), of equal counts (quantiles, JMP\'s definition) or at your cut points. The new column is ordinal, labelled by the ranges, in their order; as a formula column it follows the column.' },
    'cmd:standardize': { kicker: 'Cols > Utilities', title: 'Standardize', lead: 'For each selected numeric column a formula column Col Standardize(:x): (x − mean)/standard deviation over all rows.' },
    'cmd:pyscript': { kicker: 'File', title: 'Python Script', lead: 'A report tab with a Python editor. The code runs in the page\'s Python engine only when you press Run, in a fresh namespace, with df the table (included rows, the real column names, nominal and ordinal columns as Categoricals) and np, pd, sm, smf and stats imported.', sections: [
      { heading: 'In the report', choices: [
        ['The editor', 'Your Python. Tab indents (every selected line, when several are), shift+Tab takes an indent back, ctrl/⌘+Enter runs. The code is kept with the report, and in this browser as the start of the next script.'],
        ['Run', 'Runs the code on the table\'s included rows, each time in a fresh namespace; nothing runs before you press it.'],
        ['Examples ▾', 'Puts an example in the editor in place of what is there: describe the table, group means, a regression with statsmodels\' formulas, a t test.'],
        ['Make into Data Table', 'Shown when the code left a DataFrame (or Series) in result: opens it as a new data table.'],
        ['Insert Example, Clear Output (red triangle)', 'The same examples, and clearing what the last run printed.'],
      ] },
      { heading: 'Output', text: 'What the code prints is shown, and its error with the line. Leave a DataFrame (or Series) in result and Make into Data Table opens it as a table.' }, { heading: 'Saved projects', text: 'A project keeps the code of its script tabs but never runs it: a script from someone else shows a warning until you run it yourself.' }] },
  };

  const reg = (d) => SM.commands.register(d);
  reg({ menu: 'Tables', label: 'Summary…', order: 10, enabled: hasTable, action: summaryCommand, topics: TOPICS, about: 'Group statistics as a new, linked table' });
  reg({ menu: 'Tables', label: 'Subset…', order: 20, enabled: hasTable, action: subsetCommand, about: 'Some rows and columns as a new table' });
  reg({ menu: 'Tables', label: 'Sort…', order: 30, enabled: hasTable, action: sortCommand, about: 'Sort by several columns' });
  reg({ menu: 'Tables', label: 'Stack…', order: 40, enabled: hasTable, action: stackCommand, about: 'Columns into rows' });
  reg({ menu: 'Tables', label: 'Split…', order: 50, enabled: hasTable, action: splitCommand, about: 'Rows into columns' });
  reg({ menu: 'Tables', label: 'Transpose…', order: 60, enabled: hasTable, action: transposeCommand, about: 'Rows become columns' });
  reg({ menu: 'Tables', label: 'Concatenate…', order: 70, enabled: (app) => app.tables.length > 1, action: concatCommand, about: 'Tables one after another' });
  reg({ menu: 'Tables', label: 'Join…', order: 80, enabled: (app) => app.tables.length > 1, action: joinCommand, about: 'Two tables side by side, by matching columns' });
  reg({ menu: 'Tables', label: 'Update…', order: 90, enabled: (app) => app.tables.length > 1, action: updateCommand, about: 'Values from another table' });
  reg({ menu: 'Tables', label: 'Missing Data Pattern…', order: 110, enabled: hasTable, action: missingPatternCommand, about: 'The patterns of missing values, as a linked table' });

  const NFC = 'New Formula Column';
  reg({ menu: 'Cols', label: 'Formula…', order: 110, context: 'column', enabled: hasTable, action: (app, col) => { const t = app.requireTable(); if (t) SM.formula.edit(t, targetColumn(app, col)); }, about: 'The formula editor for the selected column, or a new formula column' });
  reg({ menu: 'Cols', label: NFC, order: 115, context: 'column', enabled: hasTable, submenu: (app, col) => nfcItems(app, col ? (app.selectedColumns().includes(col) ? app.selectedColumns() : [col]) : app.selectedColumns()), about: 'Transforms of the selected columns as formula columns' });
  reg({ menu: 'Cols', label: 'Recode…', order: 120, context: 'column', enabled: hasTable, action: recodeCommand, about: 'New values for the distinct values of a column' });
  reg({ menu: 'Cols/Utilities', label: 'Make Indicator Columns…', order: 10, enabled: hasTable, action: (app) => indicatorCommand(app) });
  reg({ menu: 'Cols/Utilities', label: 'Make Binning Column…', order: 20, enabled: hasTable, action: (app) => binningCommand(app) });
  reg({ menu: 'Cols/Utilities', label: 'Standardize', order: 30, enabled: hasTable, action: (app) => standardizeCommand(app) });
  reg({ menu: 'File', label: 'Python Script…', order: 150, enabled: hasTable, action: openScript, about: 'Python against the table, in a report tab' });

  SM.tables = Object.freeze({ copyTable, fromBackend, concatenate, applyUpdate, applyRecode, makeBinning, nfcItems, linkRows, binCuts, TRANSFORMS });
}(typeof self !== 'undefined' ? self : this));
