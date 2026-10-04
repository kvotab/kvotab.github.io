/* ==========================================================================
   SMUI.HTML: REPORTS

   A report is one tab: the platform's outline boxes, filled by its
   render(ctx) once per By group. The parts a platform builds with:

     ctx.outline(title, { menu, closed, parent, info })   an outline box
     ctx.rt({ columns, rows }, opts)   a report table (the shape util.table
                                       makes in Python); p-values as <.0001*
     ctx.kv([[label, value, fmt], ...])   a two-column list
     ctx.plot(traces, layout, opts)    a Plotly graph, linked to the table
     ctx.code(text)                    the Python behind a result
     ctx.note(text), ctx.warn(text), ctx.error(e)
     ctx.call(fn, payload)             the engine, with table and rows filled in
     ctx.opt(key, default, scope), ctx.set(key, value, scope)   options that
                                       the red-triangle menus toggle; set()
                                       redraws the report
     ctx.saveColumn(name, { rows, values }, spec)   a new column in the table
     ctx.saveFormula(name, expr, spec)   a live formula column (Save Prediction
                                       Formula): expr in smui-formula.js's language

   Linking. A trace may carry rows, the table row of each point (a number)
   or of each bar (an array of row numbers). Clicking a point or a bar, or
   dragging a rectangle, selects those rows in the table; selecting rows
   anywhere highlights them here. Points take the rows' colours and
   markers, labeled rows show their label, hidden rows are not drawn.
   Histograms show their selected part as a darker bar over the bar.
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM || (root.SM = {});
  const { el, svg, fmt, fmtP, fmtPct, uid } = SM.util;

  const SYMBOLS = ['circle', 'square', 'diamond', 'triangle-up', 'triangle-down', 'cross', 'x', 'star', 'hexagon', 'pentagon', 'circle-open', 'square-open'];
  // The points' colour. #2f6690 is 2.3:1 on the dark theme's panels, so the
  // dark theme takes the lighter blue Graph Builder uses there (5.2:1).
  const LIGHT_BASE = '#2f6690', DARK_BASE = '#6fa3d6';
  const baseColor = () => (document.documentElement.getAttribute('data-theme') === 'dark' ? DARK_BASE : LIGHT_BASE);
  const BAR = '#8fa9c2';
  const SELECTED = '#d9822b';

  // What Edit > Undo leaves alone in a report's spec: what changes without a
  // run and is no analysis (a graph's size, the code shown), and Graph
  // Builder's state, which its own Undo takes back.
  const UNDO_SKIP = ['plotSizes', 'showCode', 'gb'];
  function specKey(spec) {
    const options = { ...((spec && spec.options) || {}) };
    for (const k of UNDO_SKIP) delete options[k];
    return JSON.stringify({ ...spec, options });
  }

  // A run longer than this (ms) shows its progress in the report's bar.
  const PROGRESS_AFTER = 800;
  const RUNNING = new Set();      // the reports with a run going
  // seconds as the bar says them: 7 s, 1 min 05 s
  const elapsed = (s) => (s < 60 ? `${Math.floor(s)} s` : `${Math.floor(s / 60)} min ${String(Math.floor(s % 60)).padStart(2, '0')} s`);

  /* ---- formatting a cell ----------------------------------------------------- */
  function cellText(v, f = 'num', col = {}, alpha = 0.05) {
    if (f === 'text') return v == null ? '' : String(v);
    if (v == null || (typeof v === 'number' && Number.isNaN(v))) return '.';
    if (typeof v === 'string' && v !== 'Infinity' && v !== '-Infinity') return v;
    if (f === 'p') return fmtP(typeof v === 'string' ? Number(v) : v, alpha);
    if (f === 'pct') return fmtPct(v, col.digits ?? 1);
    if (f === 'int') return fmt(Math.round(v));
    if (col.digits != null) return fmt(v, { digits: col.digits });
    return fmt(v, { sig: col.sig || 7 });
  }

  /* ---- outline boxes ------------------------------------------------------------- */
  function triangle() {
    return svg('svg', { viewBox: '0 0 10 10', width: 10, height: 10, 'aria-hidden': 'true' }, svg('path', { d: 'M1 2.5 L9 2.5 L5 8 Z', fill: 'currentColor' }));
  }

  function redTriangle() {
    return svg('svg', { viewBox: '0 0 10 10', width: 11, height: 11, 'aria-hidden': 'true' }, svg('path', { d: 'M1.5 2.5 L8.5 2.5 L5 8.5 Z', fill: 'currentColor' }));
  }

  class Outline {
    constructor(title, { level = 1, menu = null, closed = false, info = null, onToggle = null } = {}) {
      this.el = el('section', { class: `sm-ob level-${level}` });
      this.toggleBtn = el('button', { type: 'button', class: 'sm-ob-toggle', 'aria-expanded': 'true', 'aria-label': `Show or hide ${title}` }, triangle());
      this.titleEl = el(`h${Math.min(4, level + 2)}`, { text: title });
      this.head = el('div', { class: 'sm-ob-head' }, this.toggleBtn);
      if (menu) {
        this.menuBtn = el('button', { type: 'button', class: 'sm-ob-menu', 'aria-label': `Options for ${title}`, 'aria-haspopup': 'menu' }, redTriangle());
        this.menuBtn.addEventListener('click', (ev) => {
          ev.stopPropagation();
          const items = typeof menu === 'function' ? menu() : menu;
          SM.ui.menu(items, this.menuBtn, { returnFocus: this.menuBtn, path: [this.titleEl.textContent] });
        });
        this.head.append(this.menuBtn);
      }
      // the red triangle's items, as its button opens them (Help > Search reads them: smui-search.js)
      this.menuItems = () => (menu ? (typeof menu === 'function' ? menu() : menu) : []);
      this.head.append(this.titleEl);
      if (info && typeof KvotInfo !== 'undefined') this.head.append(KvotInfo.slot(info));
      this.body = el('div', { class: 'sm-ob-body' });
      this.el.append(this.head, this.body);
      this.onToggle = onToggle;
      this.toggleBtn.addEventListener('click', () => this.setOpen(this.el.classList.contains('is-closed')));
      this.titleEl.addEventListener('dblclick', () => this.setOpen(this.el.classList.contains('is-closed')));
      if (closed) this.setOpen(false, true);
      this.el._outline = this;
    }
    setOpen(open, quiet = false) {
      this.el.classList.toggle('is-closed', !open);
      this.toggleBtn.setAttribute('aria-expanded', String(open));
      if (!quiet && this.onToggle) this.onToggle(open);
      if (open) requestAnimationFrame(() => kickPlots(this.body));
    }
    get isOpen() { return !this.el.classList.contains('is-closed'); }
    add(...nodes) { this.body.append(...nodes.flat().filter(Boolean)); return this; }
    setTitle(t) { this.titleEl.textContent = t; }
    remove() { this.el.remove(); }
  }

  /* ---- report tables --------------------------------------------------------------------- */
  /* A report table: t = { columns: [{ key, label, fmt, digits, hidden, title }],
     rows: [{ key: value }] }. Columns marked hidden are optional ones the
     reader can show from the right-click menu, as JMP's Columns submenu.
     A click on a heading sorts.
     A bar column, { key, label, bar: 'count' }, draws a bar in each row
     for the value of the column named by bar (zero or more), from the left,
     its length the value against the largest in the table, the rows not
     shown too (barCell). Its heading is empty, as JMP's bar columns are;
     the label names it in the Columns submenu, where the reader can hide
     it. It is no data: Copy Table, Make into Data Table, Sort by Column and
     tbl._rt leave it out, and Bootstrap on it takes the column it draws. */
  function rt(t, opts = {}) {
    const alpha = opts.alpha ?? 0.05;
    const all = (t.columns || []).map((c) => ({ ...c, ...(c.bar != null ? { _optional: true } : {}) }));
    const rows = (t.rows || []).slice();
    const tbl = el('table', { class: `sm-rt${opts.className ? ` ${opts.className}` : ''}` });
    const caption = opts.caption ?? t.caption;
    if (caption) tbl.append(el('caption', { text: caption }));
    const thead = el('thead');
    const body = el('tbody');
    const foot = t.footer || opts.footer ? el('tfoot') : null;
    let sortKey = null, sortDir = 1;
    const shownCols = () => all.filter((c) => !c.hidden);
    const isData = (c) => c.bar == null;
    const fill = () => {
      const cols = shownCols();
      body.replaceChildren();
      const shown = opts.maxRows && rows.length > opts.maxRows ? rows.slice(0, opts.maxRows) : rows;
      // each bar column's longest bar: the largest value of its column in all the rows
      const tops = new Map();
      for (const c of cols) {
        if (isData(c)) continue;
        let top = 0;
        for (const r of rows) { const v = barValue(r[c.bar]); if (v > top) top = v; }
        tops.set(c, top);
      }
      for (const r of shown) {
        const tr = el('tr');
        for (const c of cols) {
          if (!isData(c)) {
            const td = barCell(barValue(r[c.bar]), tops.get(c));
            if (opts.cellClass) { const k = opts.cellClass(r, c); if (k) td.classList.add(...String(k).split(/\s+/).filter(Boolean)); }
            tr.append(td);
            continue;
          }
          const v = r[c.key];
          const f = c.fmt || 'num';
          const td = el('td', { text: cellText(v, f, c, alpha) });
          if (f === 'text' || c.left) td.className = 'sm-l';
          if (f === 'p' && typeof v === 'number' && v < alpha) td.classList.add('p-sig');
          if (c.title) td.title = c.title;
          // cellClass(row, column) -> class names for one cell (a minimum
          // marked, a colour-map cell); kept when columns are shown or sorted.
          if (opts.cellClass) { const k = opts.cellClass(r, c); if (k) td.classList.add(...String(k).split(/\s+/).filter(Boolean)); }
          tr.append(td);
        }
        if (opts.onRow) { tr.style.cursor = 'pointer'; tr.addEventListener('click', (ev) => opts.onRow(r, ev)); }
        body.append(tr);
      }
      if (opts.maxRows && rows.length > opts.maxRows) {
        body.append(el('tr', null, el('td', { class: 'sm-l', colspan: String(cols.length), text: `… ${rows.length - opts.maxRows} more rows (right click: Make into Data Table)` })));
      }
      if (foot) foot.replaceChildren(el('tr', null, el('td', { colspan: String(cols.length), text: t.footer || opts.footer })));
    };
    const header = () => {
      const head = el('tr');
      for (const c of shownCols()) {
        if (!isData(c)) { head.append(el('th', { class: 'sm-rt-barhead', scope: 'col', 'aria-label': c.label ?? c.key })); continue; }
        const th = el('th', { text: c.label ?? c.key, scope: 'col' });
        if ((c.fmt || 'num') === 'text' || c.left) th.className = 'sm-l';
        if (c.title) th.title = c.title;
        if (sortKey === c.key) th.setAttribute('aria-sort', sortDir > 0 ? 'ascending' : 'descending');
        if (opts.sortable !== false && rows.length > 2) {
          th.addEventListener('click', () => {
            if (sortKey === c.key) sortDir = -sortDir; else { sortKey = c.key; sortDir = 1; }
            rows.sort((a, b) => {
              const x = a[c.key], y = b[c.key];
              if (x == null) return 1;
              if (y == null) return -1;
              return (typeof x === 'number' && typeof y === 'number' ? x - y : SM.table.collator.compare(String(x), String(y))) * sortDir;
            });
            header();
            fill();
          });
        }
        head.append(th);
      }
      thead.replaceChildren(head);
    };
    tbl.append(thead, body);
    if (foot) tbl.append(foot);
    header();
    fill();
    tbl.addEventListener('contextmenu', (ev) => {
      ev.preventDefault();
      const cols = shownCols();
      const data = cols.filter(isData);
      const optional = all.filter((c) => c.hidden || c._optional);
      const combined = tbl.dataset.group != null ? combinedTables(tbl) : null;
      // the column clicked; on a bar, the column it draws
      const at = cols[ev.target.closest('td, th')?.cellIndex ?? -1] || null;
      const clicked = at && !isData(at) ? all.find((c) => isData(c) && c.key === at.bar) || null : at;
      SM.ui.menu([
        optional.length ? { label: 'Columns', submenu: () => optional.map((c) => ({ label: c.label ?? c.key, checked: !c.hidden, action: () => { c._optional = true; c.hidden = !c.hidden; header(); fill(); } })) } : null,
        { label: 'Sort by Column…', submenu: () => data.map((c) => ({ label: c.label ?? c.key, checked: sortKey === c.key, action: () => { thead.querySelectorAll('th')[cols.indexOf(c)]?.click(); } })) },
        { separator: true },
        { label: 'Copy Table', action: () => copyText(rtText({ columns: data, rows }, alpha)) },
        { label: 'Make into Data Table', action: () => SM.app.addTable(tableFromRT({ columns: data, rows }, opts.name || caption || 'Report table')), disabled: !SM.app },
        combined && combined.length > 1 ? { label: `Make Combined Data Table (${combined.length} groups)`, action: () => SM.app.addTable(combineRT(combined, opts.name || caption || 'Report table')) } : null,
        ...(SM.bootstrap ? [{ separator: true }, SM.bootstrap.item(tbl, clicked)] : []),
      ], { x: ev.clientX, y: ev.clientY });
    });
    tbl._rt = { get columns() { return shownCols().filter(isData); }, rows, all: all.filter(isData) };
    return tbl;
  }

  /* A bar column's value: a number of zero or more, else none (0). */
  const barValue = (v) => { const x = typeof v === 'number' ? v : v == null || v === '' ? NaN : Number(v); return Number.isFinite(x) && x > 0 ? x : 0; };

  /* A bar column's cell: a track of fixed width, the bar from its left edge,
     as long as the value against top (a value above zero is a pixel at least).
     data-bar keeps the fraction for Save Report as Word. */
  function barCell(v, top) {
    const frac = top > 0 ? Math.min(1, v / top) : 0;
    const track = el('span', { class: 'sm-rt-bartrack', 'aria-hidden': 'true' });
    if (frac > 0) track.append(el('span', { class: 'sm-rt-bar', style: { width: `${+(100 * frac).toFixed(3)}%` } }));
    return el('td', { class: 'sm-rt-barcell', dataset: { bar: String(+frac.toFixed(6)) } }, track);
  }

  /* The tables of the same kind in the other By groups of the report: the
     same caption or outline title, in the same place. */
  function combinedTables(tbl) {
    const rep = tbl.closest('.sm-reportbody');
    if (!rep) return null;
    const key = tbl.dataset.rtKey;
    return [...rep.querySelectorAll('table.sm-rt')].filter((x) => x.dataset.rtKey === key && x.dataset.group != null && x._rt);
  }

  function combineRT(tables, name) {
    const first = tables[0]._rt;
    const columns = [{ key: '__group', label: 'By', fmt: 'text' }, ...first.columns];
    const rows = [];
    for (const tb of tables) for (const r of tb._rt.rows) rows.push({ __group: tb.dataset.group, ...r });
    return tableFromRT({ columns, rows }, name);
  }

  function rtText(t, alpha = 0.05) {
    const lines = [t.columns.map((c) => c.label ?? c.key).join('\t')];
    for (const r of t.rows) lines.push(t.columns.map((c) => cellText(r[c.key], c.fmt || 'num', c, alpha)).join('\t'));
    return lines.join('\n');
  }

  function tableFromRT(t, name) {
    const columns = t.columns.map((c) => {
      const vals = t.rows.map((r) => r[c.key]);
      const numeric = (c.fmt || 'num') !== 'text' && vals.every((v) => v == null || typeof v === 'number' || v === 'Infinity' || v === '-Infinity');
      return {
        name: String(c.label ?? c.key), dataType: numeric ? 'numeric' : 'character',
        values: numeric ? vals.map((v) => (v == null ? NaN : SM.table.toNumber(v))) : vals.map((v) => (v == null ? null : String(v))),
        format: c.fmt === 'p' ? { kind: 'fixed', digits: 4 } : null,
      };
    });
    return new SM.Table({ name, columns, source: 'made from a report table' });
  }

  function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(() => SM.ui.toast('Copied'), () => fallbackCopy(text));
    } else fallbackCopy(text);
  }

  function fallbackCopy(text) {
    const ta = el('textarea', { style: { position: 'fixed', left: '-9999px' } });
    ta.value = text;
    document.body.append(ta);
    ta.select();
    try { document.execCommand('copy'); SM.ui.toast('Copied'); } catch (e) { SM.ui.toast('Copying was refused by the browser', { error: true }); }
    ta.remove();
  }

  function kv(pairs, opts = {}) {
    const alpha = opts.alpha ?? 0.05;
    const tbl = el('table', { class: 'sm-kv' });
    if (opts.caption) tbl.append(el('caption', { text: opts.caption }));
    const body = el('tbody');
    const rows = [];
    for (const p of pairs) {
      if (!p) continue;
      const [label, v, f = 'num', col = {}] = p;
      const td = el('td', { text: cellText(v, f, col, alpha) });
      if (f === 'p' && typeof v === 'number' && v < alpha) td.classList.add('p-sig');
      body.append(el('tr', null, el('td', { text: label }), td));
      rows.push({ label: String(label), value: f === 'text' ? (v == null ? null : String(v)) : v });
    }
    tbl.append(body);
    // As a report table to the right-click menu: Copy, Make into Data Table, Bootstrap.
    const columns = [{ key: 'label', label: '', fmt: 'text' }, { key: 'value', label: 'Value' }];
    tbl._rt = { columns, rows, all: columns };
    tbl.addEventListener('contextmenu', (ev) => {
      ev.preventDefault();
      const name = opts.caption || tbl.closest('.sm-ob')?.querySelector('.sm-ob-head')?.textContent.trim() || 'Report table';
      SM.ui.menu([
        { label: 'Copy Table', action: () => copyText(rows.map((r) => `${r.label}\t${cellText(r.value, typeof r.value === 'number' ? 'num' : 'text', {}, alpha)}`).join('\n')) },
        { label: 'Make into Data Table', action: () => SM.app.addTable(tableFromRT({ columns: [{ key: 'label', label: 'Statistic', fmt: 'text' }, { key: 'value', label: 'Value' }], rows }, name)), disabled: !SM.app },
        ...(SM.bootstrap ? [{ separator: true }, SM.bootstrap.item(tbl, columns[1])] : []),
      ], { x: ev.clientX, y: ev.clientY });
    });
    return tbl;
  }

  /* A date column is a number in the page (milliseconds since 1970) and text
     in the CSV the code reads (as File > Export CSV writes it): code that
     uses one gets, after its read_csv line, the line that turns it back
     into that number, as the backend's code does (util.dated_code). A
     column the code parses itself (pd.to_datetime(df[...])) is left to it. */
  const pyJson = (s) => JSON.stringify(s).replace(/[\u007f-￿]/g, (c) => `\\u${c.charCodeAt(0).toString(16).padStart(4, '0')}`);
  const escRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  function datedCode(text, table) {
    if (!text || !table || !table.columns || !/pd\.read_csv\(/.test(text)) return text;
    // missing value codes back to missing values after the read (smui-table.js)
    text = SM.table && SM.table.codedCode ? SM.table.codedCode(text, table) : text;
    const need = [];
    for (const c of table.columns) {
      if (!c.isNumeric || !c.format || !/^date/.test(c.format.kind || '')) continue;
      const forms = [JSON.stringify(c.name), pyJson(c.name), `'${c.name}'`];
      if (!forms.some((f) => text.includes(f))) continue;
      if (forms.some((f) => new RegExp(`pd\\.to_datetime\\(\\s*df\\[\\s*${escRe(f)}`).test(text))) continue;
      need.push(c.name);
    }
    if (!need.length) return text;
    const line = (n) => { const q = JSON.stringify(n); return `df[${q}] = (pd.to_datetime(df[${q}]) - pd.Timestamp(0)) / pd.Timedelta(milliseconds=1)   # a date: text in the CSV, milliseconds since 1970 here as in the page`; };
    return text.split('\n').flatMap((l) => (/^df = pd\.read_csv\(/.test(l) ? [l, ...need.map(line)] : [l])).join('\n');
  }

  /* Table text never becomes code. A level, value label or text of the table
     that holds a line break (a table from a file is hostile input), found as
     it is in a report's code, is put on one line there. The code escapes
     every value it puts in a string literal (JSON or repr: no raw line break),
     so a raw one from the table can only be where a platform wrote the text
     as it is, in a comment, whose end it would be, the rest becoming code.
     Column and table names are on one line already (SM.table.cleanName);
     util.one_line and SM.util.oneLine keep the comments that write values on
     one line where they are written; this is the net under them. The values
     are indexed by the text before their first line break, so a table of
     long texts (Text Explorer's) costs a lookup per line of the code. */
  const BREAK = /[\r\n\0]/g;
  const KEY = 12;
  const breakIndexes = new WeakMap();
  function breakIndex(table) {
    const got = breakIndexes.get(table);
    if (got && got.version === table.version) return got.index;
    const index = new Map();
    const seen = new Set();
    const add = (s) => {
      if (typeof s !== 'string' || seen.has(s)) return;
      seen.add(s);
      BREAK.lastIndex = 0;
      const m = BREAK.exec(s);
      if (!m) return;
      const key = s.slice(Math.max(0, m.index - KEY), m.index);
      if (!index.has(key)) index.set(key, []);
      index.get(key).push([m.index, s]);
    };
    for (const c of table.columns || []) {
      if (!c.isNumeric) for (const v of c.values) add(v);
      if (c.valueLabels) for (const v of Object.values(c.valueLabels)) add(v);
    }
    breakIndexes.set(table, { version: table.version, index });
    return index;
  }
  function unbroken(text, table) {
    if (!text || !table || !table.columns || typeof text !== 'string') return text;
    const index = breakIndex(table);
    if (!index.size) return text;
    const hits = [];
    BREAK.lastIndex = 0;
    for (let m = BREAK.exec(text); m; m = BREAK.exec(text)) {
      const i = m.index;
      for (let L = 0; L <= KEY && L <= i; L++) {
        const list = index.get(text.slice(i - L, i));
        if (list) for (const [b, s] of list) if (Math.min(b, KEY) === L && text.startsWith(s, i - b)) hits.push([i - b, s]);
      }
    }
    if (!hits.length) return text;
    // the longest first where two start alike; an overlapped one is left (it is inside the other)
    hits.sort((a, b) => a[0] - b[0] || b[1].length - a[1].length);
    let out = '', at = 0;
    for (const [start, s] of hits) {
      if (start < at) continue;
      out += text.slice(at, start) + SM.util.oneLine(s);
      at = start + s.length;
    }
    return out + text.slice(at);
  }

  /* The head of a code snippet written in the page (a graph's code, when the
     page chose its bins or its lines): the same lines as the backend's
     util.code_head, so that every snippet starts alike and runs on its own. */
  function codeHead(tableName, extraImports = []) {
    return ['import numpy as np', 'import pandas as pd', 'import statsmodels.api as sm', 'import statsmodels.formula.api as smf', ...extraImports,
      '# the table, as File > Export CSV writes it (an empty field is missing)',
      `df = pd.read_csv(${JSON.stringify(`${tableName}.csv`)}, float_precision="round_trip", keep_default_na=False, na_values=[""])`].join('\n');
  }

  /* A result's Python, folded away until the Python code button (or its
     heading) opens it. Copy copies it; Notebook sends it to a notebook as a
     cell; Edit turns it into an editor with Run: the code runs here, on its
     own (a namespace of its own, the table read as the code reads it), and
     its output shows under it. Reset puts the report's code back. An edit
     lasts until the report is drawn again. */
  function code(text, { open = false, title = null, table = null } = {}) {
    if (!text) return null;
    text = unbroken(text, table);
    const d = el('details', { class: 'sm-code' });
    if (open) d.open = true;
    let current = text;
    const btn = (label, hint, fn, cls = '') => {
      const b = el('button', { type: 'button', class: `sm-btn small ${cls}`, text: label, title: hint });
      b.addEventListener('click', (ev) => { ev.preventDefault(); fn(); });
      return b;
    };
    const copy = btn('Copy', 'Copy the code', () => copyText(current));
    const edit = SM.editor && SM.notebook ? btn('Edit', 'Edit the code and run it here: its output shows under it', () => startEdit()) : null;
    const toNb = SM.notebook ? btn('Notebook', 'Send the code to a notebook, as a cell (the one used last, or a new one)', () => SM.notebook.collect(current, { title: title || 'a report', table })) : null;
    const pre = el('pre', null, el('code', { text }));
    const out = el('div', { class: 'sm-nb-out sm-code-out', 'aria-live': 'polite', hidden: true });
    // The buttons are not in the summary but in a bar before the <details>,
    // drawn over the room the summary keeps for them (kvot-summary-tools.js):
    // a button inside a <summary> is out of reach of some keyboards and
    // screen readers, and Chrome reports each one. So what goes into the
    // report is the box holding the two; the block itself is the <details>.
    d.append(el('summary', null, 'Python code', el('span', { class: 'kvot-summary-room sm-code-room', 'aria-hidden': 'true' })), pre, out);
    const frame = el('div', { class: 'kvot-summary-box sm-code-box' }, el('span', { class: 'kvot-summary-tools sm-code-btns' }, copy, edit, toNb), d);
    if (typeof KvotSummaryTools !== 'undefined') KvotSummaryTools.mount(frame);
    // The report's code as given (base), and as shown: set() puts in another (the graph's
    // Axis Settings, smui-axis.js), which Reset then puts back; an edit under way stays.
    d._code = { base: text, get: () => text, set(t) { const edited = current !== text; text = t; if (!edited) current = t; if (!editor) pre.firstChild.textContent = current; } };
    let editor = null, box = null;
    function startEdit() {
      d.open = true;
      if (editor) { editor.focus(); return; }
      const ns = uid('code');
      const status = el('span', { class: 'sm-code-status', role: 'status' });
      let runBtn = null;
      const run = async () => {
        runBtn.disabled = true;
        status.textContent = 'Running…';
        try {
          const res = await SM.notebook.exec(ns, editor.value, { label: 'code', fresh: true });
          SM.notebook.renderOutputs(out, res.outputs);
          status.textContent = res.outputs.some((o) => o.type === 'error') ? 'It stopped at an error: see below.' : res.outputs.length ? '' : 'It ran, and showed nothing.';
        } catch (e) {
          SM.notebook.renderOutputs(out, [{ type: 'error', ename: 'Error', evalue: e.message, traceback: [/^stopped$/.test(e.message) ? 'Stopped: Python was restarted.' : `The engine: ${e.message}`] }]);
          status.textContent = '';
        } finally { runBtn.disabled = false; }
      };
      editor = SM.editor.create({ value: current, language: 'python', label: 'The Python code of this result',
        onKey: (ev) => { if (ev.key === 'Enter' && (ev.shiftKey || ev.ctrlKey || ev.metaKey)) { run(); return true; } return false; } });
      runBtn = btn('▶ Run', 'Run the code (Shift+Enter). It reads the table as it is now, from the file the report\'s code names', run, 'primary');
      const reset = btn('Reset', 'Put back the report\'s own code', () => { editor.value = text; current = text; reset.disabled = true; SM.notebook.renderOutputs(out, []); status.textContent = ''; });
      reset.disabled = current === text;
      editor.on('change', (v) => { current = v; reset.disabled = v === text; });
      const done = btn('Close', 'Back to the code as text (the output stays)', () => {
        pre.firstChild.textContent = current;
        box.replaceWith(pre);
        editor = null; box = null;
        if (edit) edit.hidden = false;
      });
      box = el('div', { class: 'sm-code-edit' }, editor.el, el('div', { class: 'sm-code-bar' }, runBtn, reset, done, status));
      // as wide as the code as text was (its long lines wrap), so that Edit leaves the report's layout as it is
      const w = pre.getBoundingClientRect().width;
      if (w > 0) box.style.width = `${Math.round(w)}px`;
      pre.replaceWith(box);
      if (edit) edit.hidden = true;
      requestAnimationFrame(() => editor && editor.focus());
    }
    return frame;
  }

  const note = (text) => el('p', { class: 'sm-ob-note', text });
  const warn = (text) => el('div', { class: 'sm-ob-warn', role: 'note', text });

  function error(e) {
    const box = el('div', { class: 'sm-ob-error', role: 'alert' });
    box.append(el('strong', { text: e && e.fn ? `${e.fn}: ` : '' }), document.createTextNode((e && e.message) || String(e)));
    if (e && e.traceback) {
      const d = el('details', { class: 'sm-code' }, el('summary', { text: 'Python traceback' }), el('pre', { text: e.traceback }));
      box.append(d);
    }
    return box;
  }

  /* ---- plots --------------------------------------------------------------------------------- */
  const isObj = (v) => v && typeof v === 'object' && !Array.isArray(v);
  function merge(a, b) {
    const out = { ...a };
    for (const [k, v] of Object.entries(b || {})) out[k] = isObj(v) && isObj(out[k]) ? merge(out[k], v) : v;
    return out;
  }

  function themedLayout(user, w, h) {
    const c = SM.util.themeColors();
    const axis = { gridcolor: c.grid, zerolinecolor: c.grid, linecolor: c.muted, tickcolor: c.muted, automargin: true, showline: true, mirror: false, ticks: 'outside', ticklen: 3 };
    let L = merge({
      paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
      font: { family: 'verdana, sans-serif', size: 11, color: c.text },
      margin: { l: 50, r: 12, t: 8, b: 36 },
      showlegend: false, hovermode: 'closest', dragmode: 'zoom',
      legend: { font: { size: 10.5 }, bgcolor: 'rgba(0,0,0,0)' },
      hoverlabel: { font: { family: 'verdana, sans-serif', size: 11 } },
      width: w, height: h, autosize: false,
    }, user);
    for (const k of Object.keys(L)) if (/^[xy]axis\d*$/.test(k)) L[k] = merge(axis, L[k]);
    if (!L.xaxis) L.xaxis = { ...axis };
    if (!L.yaxis) L.yaxis = { ...axis };
    if (L.title && typeof L.title === 'string') L.title = { text: L.title, font: { size: 12 } };
    return L;
  }

  const CONFIG = {
    displaylogo: false, responsive: false, scrollZoom: false,
    modeBarButtonsToRemove: ['sendDataToCloud', 'toggleSpikelines', 'hoverClosestCartesian', 'hoverCompareCartesian', 'autoScale2d'],
    toImageButtonOptions: { format: 'png', scale: 2 },
  };

  let io = null;
  function observer() {
    if (!io && typeof IntersectionObserver !== 'undefined') {
      io = new IntersectionObserver((entries) => {
        for (const e of entries) if (e.isIntersecting && e.target._plot) e.target._plot.draw();
      }, { rootMargin: '300px' });
    }
    return io;
  }

  /* Draw the plots inside an element that has just become visible (an
     outline opened, a tab shown). */
  function kickPlots(node) {
    if (!node) return;
    node.querySelectorAll('.sm-plot').forEach((p) => { if (p._plot && p.offsetParent !== null) p._plot.draw(); });
  }

  /* Plotly reads a little HTML in its text (<b>, <br>, <a href>): a value
     from a table goes in with &, < and > escaped, and shows as typed. */
  // Table text in Plotly: its tags and entities, and a %{ that a hovertemplate
  // would take for a placeholder (&#37; still shows as %).
  const plotlyText = (v) => String(v).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/%\{/g, '&#37;{');

  // scattergl needs WebGL; without it (a headless browser, a locked-down
  // machine) Plotly would draw a notice instead of the graph.
  // The width a plot can take: its parent's content box (clientWidth counts
  // the padding, and an outline body has 21 px of it on the left).
  function roomFor(box) {
    const p = box.parentElement;
    if (!p || !p.clientWidth) return 0;
    const cs = getComputedStyle(p);
    return Math.max(0, Math.floor(p.clientWidth - (parseFloat(cs.paddingLeft) || 0) - (parseFloat(cs.paddingRight) || 0)));
  }

  /* A graph's size as the reader sets it: its corner dragged, its grip's
     arrow keys, or Size… in its right-click menu. Kept in the report's spec,
     options.plotSizes, by the graph's key (SM.axis.keyOf: the outlines it is
     in, its title, its place), so a redraw, Redo, the same graph of every By
     group and a saved project keep it. A graph whose platform keeps its own
     size (Graph Builder's Graph Size) passes opts.sizer = { set(w, h),
     reset() }; one of a grid of small graphs (a profiler's cells, fit:
     false) or with resize: false has no grip. */
  const MIN_W = 240, MIN_H = 140, MAX_H = 2400;
  function sizeOf(p) {
    const all = p.report && p.report.spec && p.report.spec.options && p.report.spec.options.plotSizes;
    const k = all && SM.axis ? SM.axis.keyOf(p) : null;
    const v = k ? all[k] : null;
    return Array.isArray(v) && v.length === 2 && v.every((x) => Number.isFinite(x) && x > 0) ? [Math.round(v[0]), Math.round(v[1])] : null;
  }
  function storeSize(p, wh) {
    const rep = p.report;
    const k = rep && rep.spec && SM.axis ? SM.axis.keyOf(p) : null;
    if (!k) return;
    const o = rep.spec.options || (rep.spec.options = {});
    const all = { ...(o.plotSizes || {}) };
    if (wh) all[k] = wh; else delete all[k];
    if (Object.keys(all).length) o.plotSizes = all; else delete o.plotSizes;
  }
  const resizable = (p) => p.opts.resize !== false && p.opts.fit !== false;
  /* The room around a graph: its parent's content box, or, where the parent
     only hugs the graph (a box of a graph and its code, as Distribution's),
     the first box up that does not: wider (the room it may grow into) or
     narrower (the room it must fit). Measured by the parent alone, a graph
     made narrower by a narrow window never grew back, its hugging parent
     as narrow as it. */
  function roomAround(box) {
    const w = box.offsetWidth;
    for (let p = box.parentElement; p; p = p.parentElement) {
      if (!p.clientWidth) return 0;
      const cs = getComputedStyle(p);
      const inner = p.clientWidth - (parseFloat(cs.paddingLeft) || 0) - (parseFloat(cs.paddingRight) || 0);
      if (Math.abs(inner - w) > 2 || p.matches('.sm-ob-body, .sm-reportcol') || !p.parentElement) return Math.max(0, Math.floor(inner));
    }
    return 0;
  }
  // (a graph whose platform keeps its size, Graph Builder, is measured by its own parent)
  const roomOfPlot = (p) => (p.opts.sizer ? roomFor(p.box) : roomAround(p.box));

  let webgl = null;
  function hasWebGL() {
    if (webgl == null) {
      try { const c = document.createElement('canvas'); webgl = !!(c.getContext('webgl') || c.getContext('experimental-webgl')); } catch (e) { webgl = false; }
    }
    return webgl;
  }

  class Plot {
    constructor(report, traces, layout = {}, opts = {}) {
      if (!hasWebGL()) traces = traces.map((t) => (t && t.type === 'scattergl' ? { ...t, type: 'scatter' } : t));
      this.report = report;
      this.table = opts.table || (report && report.table) || null;
      this.opts = opts;
      // rowColors: false for a graph coloured by a column of its own (Graph
      // Builder's Color zone), where the rows' colours would fight it.
      this.rowColors = opts.rowColors !== false;
      this.width = opts.width || 420;
      this.ownWidth = this.width;
      this.height = opts.height || 280;
      this.defaultSize = [this.width, this.height];     // the platform's size (Default Size goes back to it)
      this.userLayout = layout;
      this.rows = [];
      this.kinds = [];
      this.base = [];
      this.traces = traces.map((t0, i) => {
        const t = { ...t0 };
        const rows = t.rows || null;
        delete t.rows;
        this.scales = this.scales || [];
        this.scales[i] = t.rowsScale || 1;   // a number, or one per bar
        delete t.rowsScale;
        this.rows[i] = rows;
        // points: one row per point; groups: points that stand for groups of
        // rows (subgroup means, cells); bars: an array of rows per bar.
        const first = rows ? rows.find((r) => r != null) : undefined;
        const scatterish = t.type == null || t.type === 'scatter' || t.type === 'scattergl';
        this.kinds[i] = !rows ? null : Array.isArray(first) ? (scatterish ? 'groups' : 'bars') : (t.type === 'histogram' ? 'hist' : (['scatter', 'scattergl', 'box', 'violin', undefined].includes(t.type) ? 'points' : null));
        if (this.kinds[i] === 'groups') {
          t.selected = t.selected || { marker: { color: SELECTED, opacity: 1 } };
          t.unselected = t.unselected || { marker: { opacity: 0.35 } };
        }
        if (this.kinds[i] === 'points' && (t.type === 'scatter' || t.type === 'scattergl' || t.type == null)) {
          this.base[i] = { x: t.x ? t.x.slice() : null, y: t.y ? t.y.slice() : null, color: (t.marker && t.marker.color) || baseColor(), symbol: (t.marker && t.marker.symbol) || 'circle' };
          if (!t.hovertemplate && !t.hovertext) {
            const lab = this.table ? this.table.labelColumn() : null;
            t.hovertext = rows.map((r) => `row ${r + 1}${lab && lab.values[r] != null ? `: ${plotlyText(lab.values[r])}` : ''}`);
            t.hovertemplate = '%{hovertext}<br>(%{x}, %{y})<extra></extra>';
          } else if (t.text && !t.hovertext) {
            t.hovertext = t.text;
            delete t.text;
          }
          t.marker = { color: baseColor(), size: 6, ...t.marker };
          t.selected = t.selected || { marker: { color: SELECTED, opacity: 1 } };
          t.unselected = t.unselected || { marker: { opacity: 0.28 } };
        }
        if (this.kinds[i] === 'hist') this._fixBins(t);
        if (t.type === 'histogram' && !t.marker) t.marker = { color: BAR, line: { color: SM.util.themeColors().surface, width: 0.6 } };
        if (t.type === 'bar' && !t.marker) t.marker = { color: BAR };
        return t;
      });
      // Companion traces: the selected part of histogram bars and count bars.
      this.companions = [];
      const n = this.traces.length;
      for (let i = 0; i < n; i++) {
        if (this.kinds[i] === 'hist' || this.kinds[i] === 'bars') {
          const t = this.traces[i];
          const horiz = this._horizontal(t);
          const comp = { type: 'bar', x: [], y: [], orientation: horiz ? 'h' : 'v', marker: { color: SELECTED }, hoverinfo: 'skip', showlegend: false, xaxis: t.xaxis, yaxis: t.yaxis };
          if (this.kinds[i] === 'hist') comp.width = [];
          else if (t.width != null && !Array.isArray(t.width)) comp.width = t.width;
          if (t.offset != null) comp.offset = t.offset;
          // A bar that starts above zero (a stacked mosaic cell) keeps its base,
          // so that its selected part is drawn inside it.
          if (t.base != null) comp.base = Array.isArray(t.base) ? [] : t.base;
          this.companions.push({ of: i, at: this.traces.length });
          this.traces.push(comp);
        }
      }
      if (this.companions.length) this.userLayout = merge({ barmode: 'overlay', bargap: this.traces.some((t) => t.type === 'histogram') ? 0 : undefined }, this.userLayout);
      if (this.kinds.some((k) => k === 'points' || k === 'groups') && !('dragmode' in layout) && opts.select !== false) this.userLayout = merge({ dragmode: 'select' }, this.userLayout);
      this.box = el('div', { class: 'sm-plot', style: { width: `${this.width}px`, height: `${this.height}px` } });
      if (opts.title) this.box.setAttribute('aria-label', opts.title);
      this.box._plot = this;
      this.drawn = false;
      const o = observer();
      if (o) o.observe(this.box); else requestAnimationFrame(() => this.draw());
    }

    _horizontal(t) {
      if (t.type === 'histogram') return t.y != null && t.x == null;
      return t.orientation === 'h';
    }

    _fixBins(t) {
      const horiz = this._horizontal(t);
      const key = horiz ? 'ybins' : 'xbins';
      const data = (horiz ? t.y : t.x).filter((v) => Number.isFinite(v));
      if (t[key] && t[key].size) return;
      const b = niceBins(data);
      t[key] = b;
      t.autobinx = false;
    }

    async draw() {
      if (this.drawn || this.drawing || typeof Plotly === 'undefined') return;
      if (!this.box.isConnected || this.box.offsetParent === null) return;
      this.drawing = true;
      if (io) io.unobserve(this.box);
      // the size the reader gave this graph, if any (kept with the report)
      const mine = resizable(this) && !this.opts.sizer ? sizeOf(this) : null;
      if (mine) { [this.width, this.height] = mine; this.ownWidth = mine[0]; this.box.style.height = `${this.height}px`; this.box.style.width = `${this.width}px`; }
      // Drawn no wider than the room there is (a phone, a narrow window),
      // unless the platform says fit: false (a forest plot whose text columns
      // must keep their width scrolls instead).
      const room = this.opts.fit !== false ? roomOfPlot(this) : 0;
      if (room && room < this.width) { this.width = Math.max(240, room); this.box.style.width = `${this.width}px`; }
      // the axes as set by Axis Settings (smui-axis.js), on the platform's layout
      const layout = themedLayout(SM.axis ? SM.axis.layout(this, this.userLayout) : this.userLayout, this.width, this.height);
      if (mine) { layout.width = this.width; layout.height = this.height; }
      // the axis types the page gave (category, date, log), before Plotly writes its guesses into the layout: a restyle keeps them
      const types = Object.fromEntries(Object.keys(layout).filter((k) => /^[xy]axis\d*$/.test(k) && layout[k] && layout[k].type && layout[k].type !== '-').map((k) => [k, layout[k].type]));
      try {
        await Plotly.newPlot(this.box, this.traces, layout, { ...CONFIG, ...(this.opts.config || {}), toImageButtonOptions: { ...CONFIG.toImageButtonOptions, filename: (this.opts.title || 'plot').replace(/[^\w.-]+/g, '_') } });
      } catch (e) {
        this.box.replaceChildren(error(e));
        this.drawing = false;
        return;
      }
      this.drawn = true;
      this.drawing = false;
      this.axisTypes = types;
      const gd = this.box;
      gd.on('plotly_click', (ev) => this._click(ev));
      gd.on('plotly_selected', (ev) => { if (ev) this._selected(ev); });
      gd.on('plotly_deselect', () => { if (this.table && !this.quiet) this.own(() => this.table.select([])); });
      this.refreshStates();
      if (this.opts.onDraw) this.opts.onDraw(gd);
      if (SM.axis) { SM.axis.wire(this); SM.axis.amend(this); }
      if (resizable(this)) this._grip();
    }

    /* The size the reader gave the graph ([w, h]), or null. */
    userSize() { return this.opts.sizer ? null : sizeOf(this); }

    /* The graph at a size: no narrower than 240 px nor wider than the room,
       140 to 2400 px tall. keep: stored with the report (at the end of a
       drag, not at each step of it). */
    setSize(w, h, { keep = true } = {}) {
      // (a platform that keeps the size itself, Graph Builder, bounds it itself)
      const room = !this.opts.sizer && this.box.isConnected ? roomAround(this.box) : 0;
      w = Math.round(Math.max(MIN_W, room ? Math.min(w, room) : w));
      h = Math.round(Math.min(MAX_H, Math.max(MIN_H, h)));
      if (keep && this.opts.sizer) { this.opts.sizer.set(w, h); return [w, h]; }
      this.ownWidth = w;
      this.width = w;
      this.height = h;
      this.box.style.width = `${w}px`;
      this.box.style.height = `${h}px`;
      if (this.drawn) { try { Plotly.relayout(this.box, { width: w, height: h }); } catch (e) { /* being drawn again */ } }
      if (keep) { storeSize(this, [w, h]); if (SM.axis) SM.axis.amend(this); }
      return [w, h];
    }

    /* Back to the platform's own size. */
    resetSize() {
      if (this.opts.sizer) { this.opts.sizer.reset(); return; }
      storeSize(this, null);
      const [w, h] = this.defaultSize;
      const room = this.opts.fit !== false && this.box.parentElement ? roomOfPlot(this) : 0;
      this.ownWidth = w;
      this.width = room ? Math.max(MIN_W, Math.min(w, room)) : w;
      this.height = h;
      this.box.style.width = `${this.width}px`;
      this.box.style.height = `${h}px`;
      if (this.drawn) { try { Plotly.relayout(this.box, { width: this.width, height: h }); } catch (e) { /* being drawn again */ } }
      if (SM.axis) SM.axis.amend(this);
    }

    /* The grip in the graph's corner: drag it (mouse, pen or finger), or
       focus it and use the arrow keys (shift: 50 px a step); a double-click
       puts the platform's size back. */
    _grip() {
      const gd = this.box;
      if (gd.querySelector(':scope > .sm-plot-grip')) return;
      const S = SM.util.svg;
      const grip = el('button', { type: 'button', class: 'sm-plot-grip', title: 'Drag to resize the graph; double-click for its own size. The arrow keys resize it too.', 'aria-label': `Resize the graph${this.opts.title ? ` ${this.opts.title}` : ''}` },
        S('svg', { viewBox: '0 0 10 10', width: 10, height: 10, 'aria-hidden': 'true' }, S('path', { d: 'M9 3 L3 9 M9 6 L6 9', stroke: 'currentColor', 'stroke-width': 1.2, fill: 'none', 'stroke-linecap': 'round' })));
      grip.addEventListener('pointerdown', (ev) => {
        if (ev.button !== 0) return;
        ev.preventDefault();
        ev.stopPropagation();
        try { grip.setPointerCapture(ev.pointerId); } catch (e) { /* a synthetic event */ }
        const x0 = ev.clientX, y0 = ev.clientY, w0 = this.width, h0 = this.height;
        let next = null, frame = 0;
        // a platform that keeps the size itself redraws on a change of the graph's layout: an outline of the new size
        // follows the pointer, and the size goes to the platform when it is let go
        const ghost = this.opts.sizer ? el('div', { class: 'sm-plot-ghost', style: { width: `${w0}px`, height: `${h0}px` } }) : null;
        if (ghost) gd.append(ghost);
        const step = () => {
          frame = 0;
          if (!next) return;
          if (ghost) { ghost.style.width = `${Math.max(MIN_W, next[0])}px`; ghost.style.height = `${Math.min(MAX_H, Math.max(MIN_H, next[1]))}px`; } else this.setSize(next[0], next[1], { keep: false });
        };
        const move = (e) => { next = [w0 + e.clientX - x0, h0 + e.clientY - y0]; if (!frame) frame = requestAnimationFrame(step); };
        const up = () => {
          grip.removeEventListener('pointermove', move);
          grip.removeEventListener('pointerup', up);
          grip.removeEventListener('pointercancel', up);
          if (frame) cancelAnimationFrame(frame);
          document.documentElement.classList.remove('sm-resizing');
          if (ghost) ghost.remove();
          if (next) this.setSize(next[0], next[1]);
        };
        grip.addEventListener('pointermove', move);
        grip.addEventListener('pointerup', up);
        grip.addEventListener('pointercancel', up);
        document.documentElement.classList.add('sm-resizing');
      });
      grip.addEventListener('click', (ev) => { ev.preventDefault(); ev.stopPropagation(); });
      grip.addEventListener('dblclick', (ev) => { ev.preventDefault(); ev.stopPropagation(); this.resetSize(); });
      grip.addEventListener('keydown', (ev) => {
        const d = ev.shiftKey ? 50 : 10;
        const by = { ArrowRight: [d, 0], ArrowLeft: [-d, 0], ArrowDown: [0, d], ArrowUp: [0, -d] }[ev.key];
        if (!by) return;
        ev.preventDefault();
        ev.stopPropagation();
        this.setSize(this.width + by[0], this.height + by[1]);
      });
      gd.append(grip);
    }

    rowsOf(pt) {
      const rows = this.rows[pt.curveNumber];
      if (!rows) {
        const comp = this.companions.find((c) => c.at === pt.curveNumber);
        if (!comp) return [];
        return this.rowsOf({ ...pt, curveNumber: comp.of });
      }
      const kind = this.kinds[pt.curveNumber];
      if (kind === 'bars' || kind === 'groups') return rows[pt.pointNumber] || [];
      if (kind === 'hist') {
        const t = this.traces[pt.curveNumber];
        if (Array.isArray(pt.pointNumbers)) return pt.pointNumbers.map((k) => rows[k]);
        // A click on the companion bar: the rows whose values fall in that bin.
        const horiz = this._horizontal(t);
        const b = t[horiz ? 'ybins' : 'xbins'];
        const data = horiz ? t.y : t.x;
        const center = horiz ? pt.y : pt.x;
        const lo = center - b.size / 2, hi = center + b.size / 2;
        return rows.filter((r, k) => data[k] >= lo && data[k] < hi);
      }
      if (Array.isArray(pt.pointNumbers)) return pt.pointNumbers.map((k) => rows[k]);
      return pt.pointNumber != null && rows[pt.pointNumber] != null ? [rows[pt.pointNumber]] : [];
    }

    _click(ev) {
      if (!this.table || !ev || !ev.points || !ev.points.length) return;
      const rows = [...new Set(ev.points.flatMap((p) => this.rowsOf(p)))];
      if (!rows.length) return;
      const e = ev.event || {};
      this.table.select(rows, e.shiftKey ? 'add' : (e.metaKey || e.ctrlKey) ? 'toggle' : 'replace');
    }

    _selected(ev) {
      if (!this.table || !ev.points || this.quiet) return;
      const rows = [...new Set(ev.points.flatMap((p) => this.rowsOf(p)))];
      this.own(() => this.table.select(rows, (ev.event && ev.event.shiftKey) ? 'add' : 'replace'));
    }

    /* A selection made in this graph (fn selects the rows): the redraw it
       causes keeps the graph's selection box, which the user may still
       move or resize. */
    own(fn) {
      this.owning = (this.owning || 0) + 1;
      try { return fn(); } finally { this.owning -= 1; }
    }

    /* Row states onto the graph (applyStates, which a platform may wrap)
       with the graph's selection events held back meanwhile. A full redraw
       makes Plotly announce a kept selection box again (a box stays in
       layout.selections, the more so once an edge has been moved), and
       that taken for a new selection would redraw again, without end: the
       tab hung. A selection made elsewhere (the grid, another graph) takes
       the box away, as it no longer shows what is selected. */
    refreshStates(kind) {
      if (!this.drawn) return;
      this.quiet = (this.quiet || 0) + 1;
      try {
        const gd = this.box;
        const kept = gd.layout && Array.isArray(gd.layout.selections) && gd.layout.selections.length;
        if (kept && !this.owning && (!kind || kind === 'selected' || kind === 'all')) {
          try { Plotly.relayout(gd, { selections: [] }); } catch (e) { console.warn('SM: relayout failed', e); }
        }
        this.applyStates(kind);
      } finally { this.quiet -= 1; }
    }

    /* Row states onto the graph: selection, colours, markers, labels, hidden. */
    applyStates(kind = 'all') {
      if (!this.drawn || !this.table) return;
      const selectionOnly = kind === 'selected';
      const t = this.table;
      const gd = this.box;
      const st = t.state;
      let anySel = false;
      for (let i = 0; i < t.nrows; i++) if (st[i] & 1) { anySel = true; break; }
      const lab = t.labelColumn();
      const pointIdx = [], selpts = [], xs = [], ys = [], colors = [], symbols = [], texts = [], modes = [];
      const skip = new Set();
      for (let i = 0; i < this.kinds.length; i++) {
        if (this.kinds[i] !== 'points') continue;
        const rows = this.rows[i];
        pointIdx.push(i);
        if (anySel) {
          const s = [];
          for (let k = 0; k < rows.length; k++) if (st[rows[k]] & 1) s.push(k);
          selpts.push(s);
        } else selpts.push(null);
        const b = selectionOnly ? null : this.base[i];
        if (b) {
          let anyHidden = false, anyColor = false, anyMarker = false, anyLabel = false;
          for (const r of rows) { if (st[r] & 4) anyHidden = true; if (this.rowColors && t.color[r] >= 0) anyColor = true; if (t.marker[r] >= 0) anyMarker = true; if (st[r] & 8) anyLabel = true; }
          // What was applied last time: a trace that had and has no row
          // states is left alone (restyling x would make Plotly guess the
          // axis type again, and a date axis would turn linear).
          const was = b.applied || {};
          b.applied = { hidden: anyHidden, color: anyColor, marker: anyMarker, label: anyLabel };
          const need = anyHidden || anyColor || anyMarker || anyLabel || was.hidden || was.color || was.marker || was.label;
          if (!need) { skip.add(i); continue; }
          ys.push(anyHidden && b.y ? b.y.map((v, k) => ((st[rows[k]] & 4) ? null : v)) : b.y);
          xs.push(anyHidden && b.x ? b.x.map((v, k) => ((st[rows[k]] & 4) ? null : v)) : b.x);
          colors.push(anyColor ? rows.map((r, k) => (t.color[r] >= 0 ? SM.util.colorOf(t.color[r]) : (Array.isArray(b.color) ? b.color[k] : b.color))) : b.color);
          symbols.push(anyMarker ? rows.map((r) => (t.marker[r] >= 0 ? SYMBOLS[t.marker[r] % SYMBOLS.length] : b.symbol)) : b.symbol);
          texts.push(anyLabel ? rows.map((r) => ((st[r] & 8) ? plotlyText(lab ? (lab.values[r] ?? '') : r + 1) : '')) : null);
          modes.push(anyLabel ? 'markers+text' : (this.traces[i].mode || 'markers'));
        }
      }
      // Groups: a point is selected when any of its rows is.
      const gIdx = [], gSel = [];
      for (let i = 0; i < this.kinds.length; i++) {
        if (this.kinds[i] !== 'groups') continue;
        gIdx.push(i);
        gSel.push(anySel ? this.rows[i].map((rs, k) => ((rs || []).some((r) => st[r] & 1) ? k : -1)).filter((k) => k >= 0) : null);
      }
      if (gIdx.length) { try { Plotly.restyle(gd, { selectedpoints: gSel }, gIdx); } catch (e) { console.warn('SM: restyle failed', e); } }
      if (pointIdx.length) {
        const upd = { selectedpoints: selpts };
        const withBase = selectionOnly ? [] : pointIdx.filter((i) => this.base[i] && !skip.has(i));
        try {
          Plotly.restyle(gd, upd, pointIdx);
          if (withBase.length) {
            restyle(gd, { x: xs, y: ys, 'marker.color': colors, 'marker.symbol': symbols, text: texts, mode: modes, textposition: withBase.map(() => 'top right'), 'textfont.size': withBase.map(() => 10) }, withBase);
          }
        } catch (e) { console.warn('SM: restyle failed', e); }
      }
      // Companions: the selected share of each bar.
      for (const c of this.companions) {
        const i = c.of;
        const tr = this.traces[i];
        const rows = this.rows[i];
        const horiz = this._horizontal(tr);
        let pos = [], val = [], width = null, bases = null;
        if (anySel && this.kinds[i] === 'hist') {
          const b = tr[horiz ? 'ybins' : 'xbins'];
          const data = horiz ? tr.y : tr.x;
          const nb = Math.max(1, Math.round((b.end - b.start) / b.size));
          const counts = new Array(nb).fill(0);
          let total = 0;
          for (let k = 0; k < rows.length; k++) {
            const v = data[k];
            if (!Number.isFinite(v)) continue;
            total++;
            if (!(st[rows[k]] & 1)) continue;
            const j = Math.min(nb - 1, Math.max(0, Math.floor((v - b.start) / b.size)));
            counts[j]++;
          }
          const norm = tr.histnorm || '';
          const scale = norm === 'probability' ? 1 / total : norm === 'percent' ? 100 / total : norm === 'probability density' ? 1 / (total * b.size) : norm === 'density' ? 1 / b.size : 1;
          for (let j = 0; j < nb; j++) if (counts[j]) { pos.push(b.start + (j + 0.5) * b.size); val.push(counts[j] * scale); }
          width = pos.map(() => b.size);
        } else if (anySel && this.kinds[i] === 'bars') {
          const cats = horiz ? tr.y : tr.x;
          const scale = this.scales[i] || 1;
          const widths = Array.isArray(tr.width) ? [] : null;
          bases = Array.isArray(tr.base) ? [] : null;
          rows.forEach((rs, k) => {
            let s = 0;
            for (const r of rs || []) if (st[r] & 1) s++;
            if (s) { pos.push(cats[k]); val.push(s * (Array.isArray(scale) ? scale[k] ?? 1 : scale)); if (widths) widths.push(tr.width[k]); if (bases) bases.push(tr.base[k]); }
          });
          if (widths) width = widths;
        }
        const upd = horiz ? { x: [val], y: [pos] } : { x: [pos], y: [val] };
        if (width) upd.width = [width];
        if (bases) upd.base = [bases];
        try { restyle(gd, upd, [c.at]); } catch (e) { console.warn('SM: restyle failed', e); }
      }
    }

    retheme() {
      if (!this.drawn) return;
      Plotly.relayout(this.box, (() => {
        const L = themedLayout(this.userLayout, this.width, this.height);
        const u = { 'font.color': L.font.color };
        for (const k of Object.keys(L)) if (/^[xy]axis\d*$/.test(k)) { u[`${k}.gridcolor`] = L[k].gridcolor; u[`${k}.linecolor`] = L[k].linecolor; u[`${k}.zerolinecolor`] = L[k].zerolinecolor; u[`${k}.tickcolor`] = L[k].tickcolor; }
        return u;
      })());
    }

    purge() {
      if (io) io.unobserve(this.box);
      if (this.drawn && typeof Plotly !== 'undefined') {
        // After the redraw under way: Plotly ends each one in a promise
        // callback that reads the graph's layout, and a graph purged in the
        // same moment (rows selected, then the report closed) made it throw.
        // The graph's element is on its way out, never drawn in again.
        const gd = this.box;
        setTimeout(() => { try { Plotly.purge(gd); } catch (e) { /* gone already */ } }, 0);
      }
      this.drawn = false;
    }
  }

  /* Plotly.restyle of a graph's data (x, y and the like), keeping the axis
     types it was drawn with. Plotly 2.27 guesses the types again after such
     a restyle (of the first traces' axes, whichever traces changed), so the
     categories of a Pareto plot of ages ("12", "13") became a linear axis,
     its bars in numeric order, and a date axis a number axis. */
  function restyle(gd, upd, idx) {
    const types = gd && gd._plot && gd._plot.axisTypes;
    if (!types || !Object.keys(types).length) return Plotly.restyle(gd, upd, idx);
    // each type given again, with the axis's range as it is now (a type given again resets it; a zoom stays)
    const keep = {};
    for (const [k, type] of Object.entries(types)) {
      keep[`${k}.type`] = type;
      const A = gd.layout && gd.layout[k];
      if (A && Array.isArray(A.range) && A.autorange !== true) keep[`${k}.range`] = A.range.slice();
    }
    return Plotly.update(gd, upd, keep, idx);
  }

  /* Bins at round numbers, about as many as Sturges' rule asks for. */
  function niceBins(data, want = null) {
    const n = data.length;
    if (!n) return { start: 0, end: 1, size: 1 };
    let lo = Infinity, hi = -Infinity;
    for (const v of data) { if (v < lo) lo = v; if (v > hi) hi = v; }
    if (lo === hi) return { start: lo - 0.5, end: hi + 0.5, size: 1 };
    const k = want || Math.max(5, Math.min(40, Math.ceil(Math.log2(n) + 1)));
    const raw = (hi - lo) / k;
    const p = 10 ** Math.floor(Math.log10(raw));
    const size = [1, 2, 2.5, 5, 10].map((m) => m * p).reduce((best, s) => (Math.abs(Math.log(s / raw)) < Math.abs(Math.log(best / raw)) ? s : best));
    const start = Math.floor(lo / size) * size;
    let end = Math.ceil(hi / size) * size;
    if (end <= hi) end += size;
    return { start, end, size };
  }

  /* ---- data filters (a report's Local Data Filter, Rows > Data Filter) ---------------------------
     A filter is a list of { col, levels: [...] } (categorical) or
     { col, lo, hi } (continuous) entries; a row matches when it matches
     every entry that says something. */
  function filterRows(t, f, rows) {
    if (!f || !f.length || !t) return rows;
    const tests = [];
    for (const e of f) {
      const c = t.col(e.col);
      if (!c) continue;
      if (e.levels) {
        if (!e.levels.length) continue;
        const set = new Set(e.levels);
        tests.push((r) => set.has(c.values[r]));
      } else {
        const lo = e.lo, hi = e.hi;
        if (lo == null && hi == null) continue;
        tests.push((r) => { const v = c.values[r]; return Number.isFinite(v) && (lo == null || v >= lo) && (hi == null || v <= hi); });
      }
    }
    return tests.length ? rows.filter((r) => tests.every((fn) => fn(r))) : rows;
  }

  function filterActive(f) {
    return !!f && f.some((e) => (e.levels ? e.levels.length : e.lo != null || e.hi != null));
  }

  /* Draw a filter into host; onChange after every change, onClose for the ×.
     extra: nodes to put under the count (the global filter's modes). */
  // the level clicked last in each filter column, where a shift-click sweep starts
  const FILTER_MARKS = new WeakMap();
  function renderFilter(host, t, f, { title, info, onClose, onChange, extra = null, base = null }) {
    const redraw = () => renderFilter(host, t, f, { title, info, onClose, onChange, extra, base });
    const changed = () => { redraw(); onChange(); };
    host.replaceChildren();
    for (let i = f.length - 1; i >= 0; i--) if (!t.col(f[i].col)) f.splice(i, 1);
    const pool = base ? base() : t.includedRows();
    const matching = filterRows(t, f, pool).length;
    const head = el('div', { class: 'sm-filter-head' }, el('strong', { text: title }), info && typeof KvotInfo !== 'undefined' ? KvotInfo.slot(info) : null, el('span', { class: 'sm-spacer' }));
    if (onClose) {
      const close = el('button', { type: 'button', class: 'sm-dialog-x', 'aria-label': `Close the ${title}`, text: '×' });
      close.addEventListener('click', onClose);
      head.append(close);
    }
    const add = el('button', { type: 'button', class: 'sm-btn small', text: 'Add Filter Columns ▾', 'aria-haspopup': 'menu' });
    add.addEventListener('click', () => {
      const used = new Set(f.map((e) => e.col));
      SM.ui.menu(t.columns.filter((c) => !used.has(c.id)).map((c) => ({
        label: c.name, mark: c.isCategorical ? '▦' : '◢',
        action: () => { f.push(c.isCategorical || !c.isNumeric ? { col: c.id, levels: [] } : { col: c.id, lo: null, hi: null }); redraw(); },
      })), add, { returnFocus: add });
    });
    const clearAll = el('button', { type: 'button', class: 'sm-btn small', text: 'Clear' });
    clearAll.addEventListener('click', () => { for (const e of f) { if (e.levels) e.levels = []; else { e.lo = null; e.hi = null; } } changed(); });
    host.append(head, el('div', { class: 'sm-filter-count', text: `${matching} matching rows of ${pool.length}` }));
    if (extra) host.append(extra);
    host.append(el('div', { class: 'sm-filter-actions' }, add, clearAll));
    if (!f.length) host.append(el('p', { class: 'sm-ob-note', text: 'Add columns to filter by. A row matches when it matches every filter column.' }));
    for (const e of f) {
      const c = t.col(e.col);
      const remove = el('button', { type: 'button', class: 'sm-linkbtn', text: 'remove', 'aria-label': `Remove the ${c.name} filter` });
      remove.addEventListener('click', () => { f.splice(f.indexOf(e), 1); changed(); });
      const box = el('div', { class: 'sm-filter-col' }, el('div', { class: 'sm-filter-colhead' }, SM.util.typeIcon(c.modelingType), el('span', { class: 'sm-colname', text: c.name }), el('span', { class: 'sm-spacer' }), remove));
      if (e.levels) {
        const counts = new Map();
        for (const r of pool) { const v = c.values[r]; if (!SM.table.isMissing(v)) counts.set(v, (counts.get(v) || 0) + 1); }
        const lv = t.levels(c).filter((v) => counts.has(v));
        const list = el('div', { class: 'sm-filter-levels', role: 'group', 'aria-label': `${c.name} levels` });
        const set = new Set(e.levels);
        for (const v of lv.slice(0, 200)) {
          const b = el('button', { type: 'button', class: `sm-filter-level${set.has(v) ? ' is-on' : ''}`, 'aria-pressed': String(set.has(v)) },
            el('span', { text: SM.grid.cellText(c, v) }), el('span', { class: 'sm-count', text: String(counts.get(v)) }));
          b.addEventListener('click', (ev) => {
            const on = new Set(e.levels);
            // a click, ctrl/⌘ for one more level, shift for a sweep of levels
            if (!FILTER_MARKS.has(e)) FILTER_MARKS.set(e, { anchor: null });
            SM.util.listClick(ev, v, lv, on, FILTER_MARKS.get(e));
            e.levels = lv.filter((x) => on.has(x));
            changed();
          });
          list.append(b);
        }
        if (lv.length > 200) list.append(el('span', { class: 'sm-ob-note', text: `… ${lv.length - 200} more levels` }));
        box.append(list, el('div', { class: 'sm-ob-note', text: 'Click a level; ctrl/⌘ adds one more, shift a range.' }));
      } else {
        let lo = Infinity, hi = -Infinity;
        for (const r of pool) { const v = c.values[r]; if (Number.isFinite(v)) { if (v < lo) lo = v; if (v > hi) hi = v; } }
        const mk = (key, value, label) => {
          const i = el('input', { type: 'text', inputmode: 'decimal', size: 9, 'aria-label': `${c.name} ${label}`, placeholder: SM.util.fmt(value) });
          if (e[key] != null) i.value = SM.util.fmt(e[key]).replace('−', '-');
          const apply = () => { const x = i.value.trim() === '' ? null : SM.table.toNumber(i.value.replace(',', '.')); e[key] = Number.isFinite(x) ? x : null; changed(); };
          i.addEventListener('change', apply);
          i.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') { ev.preventDefault(); apply(); } });
          return i;
        };
        box.append(el('div', { class: 'sm-filter-range' }, mk('lo', lo, 'from'), el('span', { text: 'to' }), mk('hi', hi, 'to')),
          el('div', { class: 'sm-ob-note', text: `The data run from ${SM.util.fmt(lo)} to ${SM.util.fmt(hi)}; empty means no limit.` }));
      }
      host.append(box);
    }
    if (typeof KvotInfo !== 'undefined') KvotInfo.mount(host);
  }

  /* ---- a report ------------------------------------------------------------------------------ */
  const deepCopy = (x) => JSON.parse(JSON.stringify(x));

  class Report extends SM.util.Emitter {
    constructor(app, platform, spec, table) {
      super();
      this.id = uid('r');
      this.app = app;
      this.platform = platform;
      this.table = table;
      this.spec = deepCopy({ roles: {}, options: {}, ...spec, platform: platform.id });
      this.spec.options = this.spec.options || {};
      this.closed = new Map(Object.entries(this.spec.closed || {}));
      this.cache = new Map();
      this.plots = [];
      this.seq = 0;
      this.stale = false;
      this.el = el('div', { class: 'sm-report', dataset: { platform: platform.id } });
      this.bar = el('div', { class: 'sm-reportbar' });
      this.body = el('div', { class: 'sm-reportbody', tabindex: '-1' });
      // The Local Data Filter lives beside the content and survives redraws.
      this.filterHost = el('aside', { class: 'sm-filter', hidden: true, 'aria-label': 'Local data filter' });
      this.switchHost = el('div', { class: 'sm-switcher', hidden: true, role: 'group', 'aria-label': 'Column switcher' });
      this.content = el('div', { class: 'sm-reportmain' });
      this.main = el('div', { class: 'sm-reportcol' }, this.switchHost, this.content);
      this.body.append(this.filterHost, this.main);
      this.el.append(this.bar, this.body);
      this._buildBar();
      // a code block opened or closed by its own heading: the button follows
      this.body.addEventListener('toggle', (ev) => { if (ev.target.matches && ev.target.matches('details.sm-code')) this._codeState(); }, true);
      this._refilter = SM.util.debounce(() => this.run(), 160);
      // When the window (or the side panel) changes the room, the graphs are
      // made narrower, never wider than they were drawn.
      if (typeof ResizeObserver !== 'undefined') {
        const fit = SM.util.debounce(() => this.fitPlots(), 120);
        this._ro = new ResizeObserver(fit);
        this._ro.observe(this.body);
      }
      if (this.spec.filter) requestAnimationFrame(() => this._renderFilter());
      if (this.spec.switcher) requestAnimationFrame(() => this._renderSwitcher());
      // A report may have no table (DOE > Sample Size and Power). Not
      // this.off: that is the Emitter's own method.
      this._unsub = table ? [
        table.on('rowstate', (e) => this._rowstate(e)),
        table.on('data', (e) => this._data(e)),
      ] : [];
    }

    get title() {
      const p = this.platform;
      return (p.title ? p.title(this.spec, this.table) : p.label) || p.label;
    }

    _buildBar() {
      const redo = el('button', { type: 'button', class: 'sm-btn small', text: 'Redo ▾', 'aria-haspopup': 'menu' });
      redo.addEventListener('click', () => SM.ui.menu(this.redoMenu(), redo, { returnFocus: redo }));
      const codeBtn = this.codeBtn = el('button', { type: 'button', class: 'sm-btn small', text: 'Python code', 'aria-pressed': 'false' });
      codeBtn.addEventListener('click', () => this.toggleCode());
      const exp = el('button', { type: 'button', class: 'sm-btn small', text: 'Save ▾', 'aria-haspopup': 'menu' });
      exp.addEventListener('click', () => SM.ui.menu(this.saveMenu(), exp, { returnFocus: exp }));
      this.noteEl = el('span', { class: 'sm-reportnote' });
      this.staleEl = el('button', { type: 'button', class: 'sm-btn small', text: 'Data changed: Redo', hidden: true });
      this.staleEl.addEventListener('click', () => this.run());
      this.progressEl = el('div', { class: 'sm-progress', hidden: true });
      this.bar.append(redo, codeBtn, exp, this.staleEl, this.progressEl, el('span', { class: 'sm-spacer' }), this.noteEl);
    }

    /* ---- a run that takes a while ------------------------------------------------
       PROGRESS_AFTER into a run, the bar shows a bar that moves, what Python
       is doing, the time gone and Stop. What it is doing comes from the
       'smui:progress' lines of this report's own calls (Fit All: the
       distribution, and how many of them); without them the bar only moves
       and says whether Python is on this report or still on another's. Stop
       restarts the engine, the only way to interrupt a call into Python, so
       it stops whatever else Python runs too (another report, a notebook
       cell); the reports say they were stopped. A platform that shows its
       own progress in the bar (mixed models, with their Stop) marks it
       data-progress, and this one steps aside. */
    _progressBegin(seq) {
      if (this._prog) this._prog.end();
      const st = { seq, t0: performance.now(), last: null, stopped: false, shown: false, timers: [], off: null };
      this._prog = st;
      RUNNING.add(this);
      const box = this.progressEl;
      const bar = el('progress', { class: 'sm-progress-bar', 'aria-label': 'Progress of the analysis' });
      const text = el('span', { class: 'sm-progress-text', role: 'status' });
      const time = el('span', { class: 'sm-progress-time', 'aria-hidden': 'true' });
      const stop = el('button', { type: 'button', class: 'sm-btn small', text: 'Stop' });
      stop.addEventListener('click', () => {
        if (st.stopped) return;
        st.stopped = true;
        this._stopped = { seq, secs: (performance.now() - st.t0) / 1000 };
        stop.disabled = true;
        say();
        SM.engine.restart();
      });
      const say = () => {
        const own = this.bar.querySelector('[data-progress]');
        box.hidden = !!own;
        if (own) return;
        const secs = (performance.now() - st.t0) / 1000;
        time.textContent = secs >= 1 ? elapsed(secs) : '';
        const p = st.last;
        if (p && p.total > 0) { bar.max = p.total; bar.value = Math.min(p.done, p.total); } else bar.removeAttribute('value');
        let words;
        if (st.stopped) words = 'Stopping: the Python engine restarts…';
        else if (p && p.text) words = p.done < p.total ? `${p.text} (${fmt(p.done + 1)} of ${fmt(p.total)})` : p.text;
        else if (p && p.total > 0) words = `${fmt(p.done)} of ${fmt(p.total)}`;
        else if (SM.engine.state !== 'ready') words = 'Waiting for the Python engine to load…';
        else if (SM.engine.running && SM.engine.running.owner && SM.engine.running.owner !== this) words = 'Waiting for Python: it is on another analysis…';
        else if (SM.engine.loading) words = SM.engine.loading;   // a package the call needs, on its first use (scikit-learn)
        else words = `Python is working on ${this.platform.label}…`;
        if (text.textContent !== words) text.textContent = words;
      };
      st.off = SM.engine.on('progress', (p) => {
        // this report's calls; an unclaimed line when no other report runs
        if (p.owner === this || (p.owner == null && RUNNING.size === 1)) { st.last = p; if (st.shown) say(); }
      });
      st.timers.push(setTimeout(() => {
        st.shown = true;
        box.replaceChildren(bar, text, time, stop, typeof KvotInfo !== 'undefined' ? KvotInfo.slot('report:progress') : null);
        if (typeof KvotInfo !== 'undefined') KvotInfo.mount(box);
        say();
        st.timers.push(setInterval(say, 1000));
      }, PROGRESS_AFTER));
      // once: at the run's end, or when a newer run of the report takes over
      st.end = () => {
        if (st.ended) return;
        st.ended = true;
        for (const t of st.timers) { clearTimeout(t); clearInterval(t); }
        if (st.off) st.off();
        if (this._prog === st) { this._prog = null; RUNNING.delete(this); box.hidden = true; box.replaceChildren(); }
      };
      return st;
    }

    redoMenu() {
      return [
        { label: 'Redo Analysis', action: () => this.run() },
        this.platform.launch ? { label: 'Relaunch Analysis…', action: () => this.relaunch() } : null,
        { label: 'Automatic Recalc', checked: !!this.spec.autoRecalc, action: () => { this.spec.autoRecalc = !this.spec.autoRecalc; if (this.spec.autoRecalc && this.stale) this.run(); } },
        { separator: true },
        { label: 'Close Report', action: () => this.app.closeReport(this) },
      ];
    }

    saveMenu() {
      return [
        { label: 'Save Python Script (.py)', action: () => SM.util.download(`${slug(this.title)}.py`, this.pythonScript(), 'text/x-python') },
        { label: 'Copy Python Script', action: () => copyText(this.pythonScript()) },
        { label: 'Open Script in Notebook', action: () => SM.notebook.fromReport(this), disabled: !SM.notebook, title: 'The report\'s Python as the cells of a new notebook, to run and change' },
        // JMP's Save Script > To Data Table: the report as a script of its table (smui-scripts.js)
        { label: 'Save Script to Data Table…', action: () => SM.scripts.saveFromReport(this), disabled: !SM.scripts || !this.table, title: 'The report kept with its data table, in the Table panel\'s scripts: a click there runs it again' },
        { label: 'Save Report as HTML', action: () => this.exportHtml() },
        { label: 'Save Report as Word', action: () => this.exportDocx(), disabled: !SM.docx },
        { label: 'Print…', action: () => this.printReport() },
      ];
    }

    // The code blocks of the results (an error's traceback is not one).
    codeBlocks() { return [...this.body.querySelectorAll('details.sm-code')].filter((d) => !d.closest('.sm-ob-error')); }
    // Shown when every block is open; with none, as the report is set.
    codeShown() { const b = this.codeBlocks(); return b.length ? b.every((d) => d.open) : !!this.spec.options.showCode; }
    _codeState() { if (this.codeBtn) this.codeBtn.setAttribute('aria-pressed', String(this.codeShown())); }

    /* Every code block open or closed, and the report set to show (or not)
       the code of the results still to come. */
    setCode(open) {
      this.spec.options.showCode = open;
      const blocks = this.codeBlocks();
      for (const d of blocks) d.open = open;
      this._codeState();
      return blocks;
    }

    /* The Python code button and the red triangle's Show Python Code. They
       go by what is open, not by the setting, so a click never does nothing
       after a block was closed by its own heading. The code shows where it
       can be seen: when all of it is in closed outlines the first one's
       open, when none is in view the report scrolls to the nearest, and a
       report with no code says so. */
    toggleCode() {
      const blocks = this.setCode(!this.codeShown());
      if (!this.spec.options.showCode) return;
      if (!blocks.length) {
        SM.ui.toast(this.pyCode && this.pyCode.length
          ? 'This report shows none of its Python code: Save ▾ > Save Python Script (.py) has it.'
          : 'This report ran no Python, so it has no code to show. Results computed in Python, such as a fit or a test, show their code under them.', { ms: 6000 });
        return;
      }
      let seen = blocks.filter((d) => d.getClientRects().length);
      if (!seen.length) {
        for (let ob = blocks[0].closest('.sm-ob.is-closed'); ob; ob = ob.parentElement && ob.parentElement.closest('.sm-ob.is-closed')) if (ob._outline) ob._outline.setOpen(true);
        seen = blocks.filter((d) => d.getClientRects().length);
      }
      if (!seen.length) return;
      const box = this.body.getBoundingClientRect();
      // how far a block is out of the report's view (0: enough of it is in it)
      const off = (d) => {
        const r = d.getBoundingClientRect();
        if (Math.min(r.bottom, box.bottom) - Math.max(r.top, box.top) >= Math.min(r.height, 60)) return 0;
        return r.top < box.top ? r.top - box.top - 12 : Math.min(r.top - box.top - 12, r.bottom - box.bottom + 12);
      };
      if (seen.every((d) => off(d) !== 0)) {
        const dy = seen.map(off).reduce((a, b) => (Math.abs(b) < Math.abs(a) ? b : a));
        this.body.scrollBy({ top: dy, behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
      }
      for (const d of seen) {
        d.classList.remove('is-new');
        void d.offsetWidth;          // the flash starts again on a second click
        d.classList.add('is-new');
        d.addEventListener('animationend', () => d.classList.remove('is-new'), { once: true });
      }
    }

    relaunch() {
      SM.launch.open({ platform: this.platform, table: this.table, spec: this.spec, onOK: (spec) => { this.spec = { ...this.spec, ...deepCopy(spec), options: { ...this.spec.options, ...(spec.options || {}) } }; this.cache.clear(); this.app.retitle(this); this.run(); } });
    }

    _rowstate(e) {
      for (const p of this.plots) p.refreshStates(e && e.kind);
      if (e && e.kind === 'excluded' || e && e.kind === 'all') this._data();
    }

    _data(e) {
      // A new column (Save Residuals, a formula) changes no analysis already made.
      if (e && e.added) return;
      if (this.spec.filter) this._renderFilter();
      if (this.spec.autoRecalc) { clearTimeout(this._auto); this._auto = setTimeout(() => this.run(), 250); }
      else { this.stale = true; this.staleEl.hidden = false; }
    }

    /* ---- the Local Data Filter -------------------------------------------
       spec.filter: null (off) or a list of { col, levels: [...] } for
       categorical columns and { col, lo, hi } for continuous ones. The rows
       that do not match are left out of this report only. */
    toggleFilter(on) {
      const want = on != null ? on : !this.spec.filter;
      this.spec.filter = want ? (this.spec.filter || []) : null;
      this._renderFilter();
      this.run();
    }

    filterRows(rows) { return filterRows(this.table, this.spec.filter, rows); }

    /* ---- the Column Switcher ------------------------------------------------
       spec.switcher = { role, index, list: [column ids] }: one column of a
       role is swapped for another from the list, and the report redrawn. */
    async columnSwitcher() {
      const t = this.table;
      if (!t) return;
      if (this.spec.switcher) { this.spec.switcher = null; this._renderSwitcher(); return; }
      const cast = [];
      for (const [role, ids] of Object.entries(this.spec.roles || {})) (ids || []).forEach((id, i) => { const c = t.col(id); if (c) cast.push([`${role}:${i}`, `${c.name} (${role})`]); });
      if (!cast.length) { SM.ui.toast('This report has no columns to switch'); return; }
      const v = await SM.ui.form({
        title: 'Column Switcher', info: 'report:switcher',
        fields: [
          { key: 'which', label: 'Switch the column', type: 'select', value: cast[0][0], choices: cast, help: 'The column of the analysis, with its role, that the switcher replaces. Each column in the switcher\'s list then takes its place in that role, with every other setting of the report kept.' },
          { key: 'types', label: 'Offer columns of the same modeling type only', type: 'check', value: true, helpLabel: 'Same modeling type only', help: 'On: the list offers the columns of the same modeling type (any nominal or ordinal column for a categorical one), which the analysis can take. Off: every column of the table.' },
        ],
      });
      if (!v) return;
      const [role, idx] = v.which.split(':');
      const cur = t.col(this.spec.roles[role][+idx]);
      const list = t.columns.filter((c) => !v.types || c.modelingType === cur.modelingType || (cur.isCategorical && c.isCategorical)).map((c) => c.id);
      this.spec.switcher = { role, index: +idx, list };
      this._renderSwitcher();
    }

    _renderSwitcher() {
      const sw = this.spec.switcher;
      const host = this.switchHost;
      host.hidden = !sw;
      host.replaceChildren();
      if (!sw || !this.table) return;
      const t = this.table;
      const cur = (this.spec.roles[sw.role] || [])[sw.index];
      const close = el('button', { type: 'button', class: 'sm-dialog-x', 'aria-label': 'Close the column switcher', text: '×' });
      close.addEventListener('click', () => { this.spec.switcher = null; this._renderSwitcher(); });
      const list = el('div', { class: 'sm-switch-list' });
      for (const id of sw.list) {
        const c = t.col(id);
        if (!c) continue;
        const b = el('button', { type: 'button', class: `sm-filter-level${id === cur ? ' is-on' : ''}`, 'aria-pressed': String(id === cur) }, SM.util.typeIcon(c.modelingType), el('span', { text: c.name }));
        b.addEventListener('click', () => {
          this.spec.roles[sw.role][sw.index] = id;
          if (this.spec.roleNames && this.spec.roleNames[sw.role]) this.spec.roleNames[sw.role][sw.index] = c.name;
          this._renderSwitcher();
          this.app.retitle(this);
          this.run();
        });
        list.append(b);
      }
      host.append(el('div', { class: 'sm-filter-head' }, el('strong', { text: 'Column Switcher' }), typeof KvotInfo !== 'undefined' ? KvotInfo.slot('report:switcher') : null, el('span', { class: 'sm-spacer' }), close), list);
      if (typeof KvotInfo !== 'undefined') KvotInfo.mount(host);
    }

    _renderFilter() {
      const f = this.spec.filter;
      this.filterHost.hidden = !f;
      this.body.classList.toggle('has-filter', !!f);
      if (!f || !this.table) { this.filterHost.replaceChildren(); return; }
      renderFilter(this.filterHost, this.table, f, {
        title: 'Local Data Filter', info: 'report:filter',
        onClose: () => this.toggleFilter(false),
        onChange: () => this._refilter(),
      });
    }

    /* The rows of each By group: the included rows, split by the By columns. */
    groups() {
      const t = this.table;
      if (!t) return [{ label: null, rows: [], where: [] }];
      const rows = this.filterRows(t.includedRows());
      const byIds = (this.spec.roles && this.spec.roles.by) || [];
      const by = byIds.map((id) => t.col(id)).filter(Boolean);
      if (!by.length) return [{ label: null, rows, where: [] }];
      const levelMaps = by.map((c) => { const lv = t.levels(c); return new Map(lv.map((v, i) => [v, i])); });
      const groups = new Map();
      for (const r of rows) {
        const key = [];
        let skip = false;
        for (let k = 0; k < by.length; k++) {
          const v = by[k].values[r];
          if (SM.table.isMissing(v)) { skip = true; break; }
          key.push(levelMaps[k].get(v));
        }
        if (skip) continue;
        const s = key.join('\u0001');
        if (!groups.has(s)) groups.set(s, { key, rows: [] });
        groups.get(s).rows.push(r);
      }
      const list = [...groups.values()].sort((a, b) => { for (let k = 0; k < a.key.length; k++) if (a.key[k] !== b.key[k]) return a.key[k] - b.key[k]; return 0; });
      return list.map((g) => {
        const where = by.map((c, k) => ({ column: c.name, value: t.levels(c)[g.key[k]] }));
        return { label: where.map((w) => `${w.column}=${SM.grid.cellText(t.col(w.column), w.value)}`).join(', '), rows: g.rows, where };
      });
    }

    /* reason: 'redo' (the default), 'theme' (the theme changed: the same
       results drawn again), or what a caller passes. A platform that changes
       the table while rendering (Color Clusters) can skip it on 'theme'. */
    async run(reason = 'redo') {
      const seq = ++this.seq;
      this._noteChange(reason);
      const prog = this._progressBegin(seq);
      try { await this._run(seq, reason); } finally {
        prog.end();
        // what the run itself wrote in the spec (a platform's own bookkeeping) is no change of the reader's
        if (seq === this.seq) this._specSeen = specKey(this.spec);
      }
    }

    /* ---- undo of a report's changes ---------------------------------------------
       A run that starts from another spec than the last run's follows a change
       of the report: a red-triangle option, Remove, Axis Settings, a filter, a
       relaunch. Edit > Undo can put the spec back (app.recordReport), named by
       the menu item that was chosen since the last run, if one was. A run for
       the theme, or one an undo starts, records nothing. specKey leaves out
       what is no analysis (UNDO_SKIP). */
    _noteChange(reason) {
      const now = specKey(this.spec);
      const before = this._specSeen, since = this._specSeenAt || 0;
      this._specSeen = now;
      this._specSeenAt = performance.now();
      if (before == null || before === now || reason === 'undo' || reason === 'theme' || !this.app || !this.app.recordReport) return;
      const p = SM.ui.picked && SM.ui.picked();
      this.app.recordReport(this, p && p.at > since ? p.path[p.path.length - 1] : `Change in ${this.title}`, before);
    }

    /* A spec from Edit > Undo or Redo (specKey's text) put back and run; what
       undo leaves alone (a graph's size, the code shown) stays as it is. */
    restoreSpec(key) {
      const spec = JSON.parse(key);
      spec.options = spec.options || {};
      for (const k of UNDO_SKIP) if (this.spec.options && k in this.spec.options) spec.options[k] = this.spec.options[k];
      this.spec = spec;
      this._renderFilter();
      this._renderSwitcher();
      if (this.app && this.app.retitle) this.app.retitle(this);
      return this.run('undo');
    }

    get undoKey() { return specKey(this.spec); }

    async _run(seq, reason) {
      this.reason = reason;
      this.stale = false;
      this.staleEl.hidden = true;
      const scroll = this.body.scrollTop;
      const fresh = el('div', { class: 'sm-reportcontent' });
      const oldPlots = this.plots;
      this.plots = [];
      this.pyCode = [];
      this.body.classList.add('is-running');
      const first = !this.content.firstChild;
      if (first) { this.content.append(fresh); this.content.append(el('p', { class: 'sm-ob-note sm-waiting', text: SM.engine.state === 'ready' ? 'Running…' : 'Waiting for the Python engine to load…' })); }
      let groups;
      try { groups = this.groups(); } catch (e) { groups = []; fresh.append(error(e)); }
      if (!groups.length) fresh.append(warn('No rows to analyse: every row is excluded, or every By value is missing.'));
      let used = 0;
      // What this run draws. A newer run (a Redo, a theme change, an option)
      // may start while this one waits on Python: from then on this run adds
      // nothing to the report's graphs and code, and at its end it purges
      // only its own graphs, not the newer run's.
      const made = [];
      for (const g of groups) {
        used += g.rows.length;
        const title = g.label ? `${this.title} ${g.label}` : this.title;
        const path = g.label || '';
        const ctx = new Ctx(this, g, fresh, path);
        ctx.seq = seq;
        ctx.made = made;
        const top = ctx.outline(title, { level: 0, menu: () => ctx.topMenu() });
        ctx.container = top.body;
        ctx.top = top;
        // after a Stop the rest of the run (the other By groups) is not analysed
        if (this._stopped && this._stopped.seq === seq) { top.body.append(warn('Not analysed: Stop restarted the Python engine. Redo runs the analysis again.')); continue; }
        try {
          const missing = ctx.missingColumns();
          if (missing.length) throw new Error(`the column${missing.length > 1 ? 's' : ''} ${missing.join(', ')} ${missing.length > 1 ? 'are' : 'is'} no longer in the table; relaunch the analysis`);
          await this.platform.render(ctx);
        } catch (e) {
          // Stop (this report's or another's) restarted the engine under the run
          if (e && e.message === 'stopped') {
            const s = this._stopped && this._stopped.seq === seq ? this._stopped : null;
            top.body.append(warn(s ? `Stopped after ${elapsed(s.secs)}: Stop restarted the Python engine before the analysis was finished. Redo runs it again.`
              : 'Stopped: the Python engine was restarted (by Stop, here, in another report or in a notebook) before this analysis was finished. Redo runs it again.'));
          } else {
            console.error(e);
            top.body.append(error(e));
          }
        }
        if (ctx.warnings.length) {
          const w = ctx.outline('Messages from statsmodels', { closed: false, level: 1 });
          w.add(...ctx.warnings.map((m) => warn(m)));
        }
        if (seq !== this.seq) { for (const p of made) p.purge(); this.plots = this.plots.filter((p) => !made.includes(p)); return; }
      }
      if (seq !== this.seq) { for (const p of made) p.purge(); this.plots = this.plots.filter((p) => !made.includes(p)); return; }
      this.content.querySelector('.sm-waiting')?.remove();
      if (!first) this.content.replaceChildren(fresh);
      if (this.spec.filter) this._renderFilter();
      for (const p of oldPlots) p.purge();
      this.body.classList.remove('is-running');
      this.body.scrollTop = scroll;
      if (this.spec.options.showCode) this.setCode(true); else this._codeState();
      if (this.table) {
        const c = this.table.counts();
        const filtered = this.spec.filter && this.spec.filter.length ? ', filtered' : '';
        this.noteEl.textContent = `${this.table.name}: ${used} of ${c.all} rows${c.excluded ? `, ${c.excluded} excluded` : ''}${filtered}${groups.length > 1 ? `, ${groups.length} groups` : ''}`;
      } else this.noteEl.textContent = '';
      if (typeof KvotInfo !== 'undefined') KvotInfo.mount(this.body);
      if (SM.axis) SM.axis.settle(this);
      requestAnimationFrame(() => kickPlots(this.body));
      this.emit('done', this);
    }

    pythonScript() {
      const parts = [`# ${SM.util.oneLine(this.title)}`, this.table ? `# Made by the User Interface for statsmodels (kvotab.se/smui.html) from the table "${SM.util.oneLine(this.table.name)}" (export it with File > Export > CSV).` : '# Made by the User Interface for statsmodels (kvotab.se/smui.html).', ''];
      const seen = new Set();
      for (const c of this.pyCode) if (!seen.has(c)) { seen.add(c); parts.push(c, ''); }
      if (!this.pyCode.length) parts.push('# (this report ran no Python)');
      return parts.join('\n');
    }

    /* A graph as an image for a document: drawn in the light theme (paper is
       white), at its size on the page. */
    async plotImage(p, format = 'svg', scale = 1) {
      if (!p.drawn) { const closed = p.box.closest('.sm-ob.is-closed'); if (!closed) await p.draw(); }
      if (!p.drawn) return null;
      const gd = p.box;
      let fig = gd;
      if (SM.util.themeColors().dark) {
        const layout = JSON.parse(JSON.stringify(gd.layout || {}));
        layout.font = { ...(layout.font || {}), color: PAPER.text };
        for (const k of Object.keys(layout)) if (/^[xy]axis\d*$/.test(k)) Object.assign(layout[k], { gridcolor: PAPER.grid, zerolinecolor: PAPER.grid, linecolor: PAPER.muted, tickcolor: PAPER.muted });
        if (layout.legend) layout.legend = { ...layout.legend, font: { ...(layout.legend.font || {}), color: PAPER.text } };
        // the points and lines drawn in the dark theme's blue take the light one's
        const paper = (v) => {
          if (typeof v === 'string') return v.toLowerCase() === DARK_BASE ? LIGHT_BASE : v;
          if (Array.isArray(v)) return v.map(paper);
          if (v && Object.getPrototypeOf(v) === Object.prototype) return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, paper(x)]));
          return v;      // numbers, typed arrays
        };
        fig = { data: gd.data.map((t) => { const o = { ...t }; for (const k of ['marker', 'line', 'fillcolor']) if (t[k] != null) o[k] = paper(t[k]); return o; }), layout };
        // Axis Settings' reference lines and their labels in the light theme's colours (smui-axis.js)
        if (SM.axis && SM.axis.paperLayout) SM.axis.paperLayout(layout);
      }
      try {
        const data = await Plotly.toImage(fig, { format, width: p.width, height: p.height, scale });
        return { data, w: p.width, h: p.height, alt: p.opts.title || 'graph' };
      } catch (e) { return null; }
    }

    /* The report as a document (Save Report as HTML, Print): the open parts,
       the graphs as images, without the page's buttons and inputs. */
    async documentHtml() {
      const clone = this.content.cloneNode(true);
      // diagrams drawn as SVG (a tree, a network) with their paint written in:
      // the document has none of the page's style sheets
      const own = (root) => [...root.querySelectorAll('svg')].filter((s) => !s.closest('.sm-plot') && !s.ownerSVGElement);
      const liveSvg = own(this.content), copySvg = own(clone);
      liveSvg.forEach((s, i) => { if (copySvg[i]) copySvg[i].replaceWith(paintedSvg(s)); });
      const live = [...this.content.querySelectorAll('.sm-plot')];
      const copies = [...clone.querySelectorAll('.sm-plot')];
      for (let i = 0; i < live.length; i++) {
        const p = live[i]._plot;
        const img = p ? await this.plotImage(p, 'svg') : null;
        copies[i].replaceChildren(img ? el('img', { src: img.data, alt: img.alt, width: img.w, height: img.h }) : el('em', { text: '(graph not drawn)' }));
      }
      // (a code block's buttons go with their bar, and the room its summary kept for them)
      clone.querySelectorAll('button, .kvot-info-slot, .kvot-summary-tools, .kvot-summary-room, [data-noexport], input, select, textarea').forEach((b) => b.remove());
      // The Python goes along when the report shows it (the Python code button) or its block is open; a traceback always.
      if (!this.spec.options.showCode) clone.querySelectorAll('details.sm-code').forEach((d) => { if (!d.closest('.sm-ob-error') && !d.open) d.remove(); });
      clone.querySelectorAll('details').forEach((d) => d.setAttribute('open', ''));
      const css = `body{font-family:verdana,sans-serif;font-size:12.5px;color:#352921;background:#fff;margin:20px}h2,h3,h4{font-size:13px;margin:10px 0 4px}.sm-ob-body{padding-left:18px}.sm-ob.is-closed>.sm-ob-body{display:none}table{border-collapse:collapse;margin:2px 0 8px}th,td{padding:2px 9px;border-bottom:1px solid #e0d7ce;text-align:right;white-space:nowrap}th{background:#f5eee7}.sm-l{text-align:left}.p-sig{color:#c8322b;font-weight:600}caption{text-align:left;font-weight:600;color:#6b5d50;padding-bottom:3px}.sm-ob-row{display:flex;flex-wrap:wrap;gap:16px 22px}td.sm-rt-barcell{vertical-align:middle}.sm-rt-bartrack{display:block;width:100px;height:10px}.sm-rt-bar{display:block;height:100%;min-width:1px;background:#8fa9c2;border-radius:0 4px 4px 0;-webkit-print-color-adjust:exact;print-color-adjust:exact}pre{background:#f7f2ec;padding:8px;border:1px solid #e0d7ce;font-size:11.5px;overflow-x:auto;white-space:pre-wrap}.sm-ob-note{color:#6b5d50;font-size:11.5px}.sm-ob-warn{border-left:3px solid #f3b87b;padding:4px 8px;background:#fdf4e9}.sm-ob-error{border-left:3px solid #c0392b;padding:4px 8px}img{max-width:100%;height:auto}`
        + '@page{margin:15mm}@media print{body{margin:0}table,img,.sm-plot,caption{break-inside:avoid}h2,h3,h4{break-after:avoid}summary{list-style:none}}';
      return `<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>${escapeHtml(this.title)}</title><style>${css}</style></head><body><h1 style="font-size:16px">${escapeHtml(this.title)}</h1><p style="color:#786b5d">${this.table ? `Table: ${escapeHtml(this.table.name)}. ` : ''} Made with the User Interface for statsmodels (kvotab.se/smui.html), statsmodels ${escapeHtml(SM.engine.versions ? SM.engine.versions.statsmodels : '')}, ${new Date().toISOString().slice(0, 10)}.</p>${clone.innerHTML}</body></html>`;
    }

    async exportHtml() {
      SM.util.download(`${slug(this.title)}.html`, await this.documentHtml(), 'text/html');
    }

    /* Print: the document above in a hidden frame, printed from there, so the
       paper has the report and not the page around it. */
    async printReport() {
      const html = await this.documentHtml();
      const frame = el('iframe', { class: 'sm-print-frame', title: `Print ${this.title}`, 'aria-hidden': 'true', tabindex: '-1' });
      document.body.append(frame);
      await new Promise((res) => { frame.addEventListener('load', res, { once: true }); frame.srcdoc = html; });
      const doc = frame.contentDocument;
      await Promise.all([...doc.images].map((im) => (im.complete ? null : new Promise((r) => { im.onload = r; im.onerror = r; }))));
      this._printFrame = frame;
      const done = () => { frame.remove(); if (this._printFrame === frame) this._printFrame = null; };
      frame.contentWindow.addEventListener('afterprint', () => setTimeout(done, 0), { once: true });
      setTimeout(done, 10 * 60 * 1000);
      frame.contentWindow.focus();
      frame.contentWindow.print();
      return frame;
    }

    /* Save Report as Word: smui-docx.js, with the graphs as PNG pictures. */
    async exportDocx() {
      const blob = await SM.docx.report(this, { plotImage: (p) => this.plotImage(p, 'png', 2) });
      SM.util.download(`${slug(this.title)}.docx`, blob, 'application/vnd.openxmlformats-officedocument.wordprocessingml.document');
      return blob;
    }

    retheme() { for (const p of this.plots) p.retheme(); }

    fitPlots() {
      for (const p of this.plots) {
        if (!p.drawn || !p.box.isConnected || p.opts.fit === false) continue;
        const room = p.box.parentElement ? roomOfPlot(p) : p.ownWidth;
        if (!room) continue;
        const w = Math.max(240, Math.min(p.ownWidth, room));
        if (Math.abs(w - p.width) < 4) continue;
        p.width = w;
        p.box.style.width = `${w}px`;
        try { Plotly.relayout(p.box, { width: w }); } catch (e) { /* a graph being replaced */ }
      }
    }

    close() {
      this.seq++;
      if (this._ro) this._ro.disconnect();
      for (const f of this._unsub) f();
      for (const p of this.plots) p.purge();
      this.plots = [];
      this.el.remove();
    }

    toJSON() {
      // idNames: every column's name by id, so that a project opened again
      // (where the columns get new ids) finds every column the report refers
      // to — in its roles, options, filters and closed outlines.
      const idNames = this.table ? Object.fromEntries(this.table.columns.map((c) => [c.id, c.name])) : {};
      return { platform: this.platform.id, table: this.table ? this.table.id : null, idNames, spec: { ...this.spec, closed: Object.fromEntries(this.closed) } };
    }
  }

  // A graph's colours on paper (and in a document) are the light theme's.
  const PAPER = { text: '#352921', muted: '#786b5d', grid: '#e0d7ce' };

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  const slug = (s) => String(s).replace(/[^\w.-]+/g, '_').replace(/^_+|_+$/g, '').slice(0, 80) || 'report';

  /* ---- what a platform's render(ctx) gets --------------------------------------------------------- */
  class Ctx {
    constructor(report, group, container, path) {
      this.report = report;
      this.table = report.table;
      this.spec = report.spec;
      this.rows = group.rows;
      this.byLabel = group.label;
      this.reason = report.reason || 'redo';
      this.where = group.where;
      this.container = container;
      this.path = path;
      this.warnings = [];
      this.top = null;
    }

    get alpha() { return Number(this.opt('alpha', 0.05)) || 0.05; }

    col(id) { return this.table ? this.table.col(id) : null; }

    /* The columns cast into a role, as Column objects. */
    roles(key) { return this.table ? ((this.spec.roles && this.spec.roles[key]) || []).map((id) => this.table.col(id)).filter(Boolean) : []; }
    role(key) { return this.roles(key)[0] || null; }
    names(key) { return this.roles(key).map((c) => c.name); }
    name(key) { const c = this.role(key); return c ? c.name : null; }

    missingColumns() {
      const out = [];
      if (!this.table) return out;
      for (const [k, ids] of Object.entries(this.spec.roles || {})) for (const id of ids || []) if (!this.table.col(id)) out.push(`${id} (${k})`);
      return out;
    }

    /* Options: a scoped value (one column's) wins over the report's. */
    opt(key, dflt, scope) {
      const o = this.spec.options || {};
      if (scope != null && `${scope}|${key}` in o) return o[`${scope}|${key}`];
      if (key in o) return o[key];
      return dflt;
    }

    set(key, value, scope, { rerun = true } = {}) {
      if (this.headless) return;
      const o = this.spec.options;
      if (scope != null) o[`${scope}|${key}`] = value; else {
        o[key] = value;
        for (const k of Object.keys(o)) if (k.endsWith(`|${key}`)) delete o[k];
      }
      if (rerun) this.report.run();
    }

    toggle(key, scope, dflt = false) { this.set(key, !this.opt(key, dflt, scope), scope); }

    /* A menu item that toggles an option. */
    check(label, key, scope, dflt = false, extra = {}) {
      return { label, checked: !!this.opt(key, dflt, scope), action: () => this.toggle(key, scope, dflt), ...extra };
    }

    async call(fn, payload = {}) {
      // Every row, in order, goes as no row list at all: the same to Python,
      // and a long list is slow to send. A resample (Bootstrap) may have as
      // many rows as the table and still not be every row.
      const all = !this.resampled && this.table && this.rows.length === this.table.nrows;
      const body = { rows: all ? null : this.rows, ...payload };
      const { rows, ...rest } = body;
      const key = `${fn}\u0001${this.table ? (this.table.dataVersion ?? this.table.version) : 0}\u0001${hashRows(rows)}\u0001${JSON.stringify(rest)}`;
      let r = this.headless ? null : this.report.cache.get(key);
      if (!r) {
        // the report owns the call: its progress lines go to its bar
        r = SM.engine.call(fn, this.table ? body : rest, this.table, { owner: this.report });
        if (!this.headless) {
          this.report.cache.set(key, r);
          r.catch(() => this.report.cache.delete(key));
          if (this.report.cache.size > 400) this.report.cache.delete(this.report.cache.keys().next().value);
        }
      }
      const out = await r;
      if (out && Array.isArray(out.warnings)) for (const w of out.warnings) if (!this.warnings.includes(w)) this.warnings.push(w);
      if (out && out.code && !this.headless && this.current) this.report.pyCode.push(unbroken(out.code, this.table));
      return out;
    }

    // false once a newer run of the report has started (a headless Ctx has no run: always true)
    get current() { return this.seq == null || this.seq === this.report.seq; }

    outline(title, opts = {}) {
      const parent = opts.parent ? (opts.parent.body || opts.parent) : this.container;
      const level = opts.level != null ? opts.level : (opts.parent && opts.parent.el ? levelOf(opts.parent) + 1 : 1);
      const pathKey = `${this.path}\u0001${opts.key || title}`;
      const remembered = this.report.closed.get(pathKey);
      const o = new Outline(title, {
        level, menu: opts.menu || null, info: opts.info || null,
        closed: remembered != null ? remembered : !!opts.closed,
        onToggle: (open) => this.report.closed.set(pathKey, !open),
      });
      parent.append(o.el);
      return o;
    }

    row(...nodes) { return el('div', { class: 'sm-ob-row' }, ...nodes); }

    plot(traces, layout, opts = {}) {
      // A headless run (Bootstrap reruns a report on resamples) draws nothing.
      if (this.headless) return el('div', { class: 'sm-plot' });
      const p = new Plot(this.report, traces, layout, opts);
      if (this.made) this.made.push(p);
      if (this.current) this.report.plots.push(p);
      return p.box;
    }

    rt(t, opts = {}) {
      const tbl = rt(t, { alpha: this.alpha, ...opts });
      if (this.byLabel != null) {
        tbl.dataset.group = this.byLabel;
        tbl.dataset.rtKey = opts.key || opts.caption || t.caption || '';
        // Without a caption, the outline the table ends up in names it.
        if (!tbl.dataset.rtKey) requestAnimationFrame(() => { const h = tbl.closest('.sm-ob')?.querySelector(':scope > .sm-ob-head h3, :scope > .sm-ob-head h4'); tbl.dataset.rtKey = h ? h.textContent : ''; });
      }
      return tbl;
    }
    kv(pairs, opts = {}) { return kv(pairs, { alpha: this.alpha, ...opts }); }
    // Code a platform shows that no call returned (worked out in the page)
    // goes into Save Python Script too; the calls' own code is there already.
    code(text) {
      text = unbroken(datedCode(text, this.report.table), this.report.table);
      if (text && !this.headless && this.current) for (const part of String(text).split('\n\n# ----\n')) if (!this.report.pyCode.includes(part)) this.report.pyCode.push(part);
      return code(text, { open: !!this.spec.options.showCode, title: this.report.title, table: this.report.table });
    }
    note(text) { return note(text); }
    warn(text) { return warn(text); }
    error(e) { return error(e); }

    /* A new column in the table from values for some rows (the rest
       missing): Save Residuals, Save Predicteds, Save Principal Components. */
    saveColumn(name, { rows, values }, spec = {}) {
      if (this.headless) return null;
      const t = this.table;
      // JSON has no infinities: util.clean sends them as 'Infinity' and '-Infinity'.
      const INF = { Infinity: Infinity, '-Infinity': -Infinity, NaN: NaN };
      if (spec.dataType !== 'character' && values.some((v) => typeof v === 'string') && values.every((v) => v == null || typeof v === 'number' || v in INF)) values = values.map((v) => (typeof v === 'string' ? INF[v] : v));
      const numeric = spec.dataType !== 'character' && values.every((v) => v == null || typeof v === 'number');
      const full = new Array(t.nrows).fill(numeric ? NaN : null);
      rows.forEach((r, k) => { full[r] = values[k] == null ? (numeric ? NaN : null) : values[k]; });
      const c = t.addColumn({ name, dataType: numeric ? 'numeric' : 'character', values: full, notes: spec.notes || `saved from ${this.report.title}`, ...spec });
      SM.ui.toast(`Saved the column ${c.name} to ${t.name}`);
      return c;
    }

    /* A live formula column in the table (Save Prediction Formula and the
       like): expr is in the page's formula language (smui-formula.js), so
       the column is worked out again for rows added or edited later and goes
       with the table to a file. spec as saveColumn's (modelingType,
       valueOrder, notes, format). A formula that does not compile throws,
       and nothing is added. */
    saveFormula(name, expr, spec = {}) {
      if (this.headless) return null;
      const t = this.table;
      const { modelingType, valueOrder, ...rest } = spec;
      const c = t.addColumn({ name, dataType: 'numeric', values: [], notes: spec.notes || `saved from ${this.report.title}`, ...rest });
      try {
        SM.formula.apply(t, c, expr);
      } catch (e) {
        t.removeColumn(c.id);
        throw e;
      }
      if (valueOrder) c.valueOrder = valueOrder;
      if (modelingType && !(modelingType === 'continuous' && !c.isNumeric)) c.modelingType = modelingType;
      if (valueOrder || modelingType) t._changed('schema', { info: c.id });
      SM.ui.toast(`Saved the formula column ${c.name} to ${t.name}`);
      return c;
    }

    /* The red triangle of the top outline: the platform's items, then the
       ones every report has. */
    topMenu() {
      const items = this.report.platform.triangle ? (this.report.platform.triangle(this) || []) : [];
      return [
        ...items,
        items.length ? { separator: true } : null,
        { label: 'Set α Level', submenu: () => [0.01, 0.05, 0.1].map((a) => ({ label: String(a), checked: this.alpha === a, action: () => this.set('alpha', a) })).concat([{ label: 'Other…', action: async () => { const v = await SM.ui.form({ title: 'Set α Level', fields: [{ key: 'a', label: 'α (between 0 and 1)', type: 'number', value: this.alpha, help: 'The significance level of this report: its confidence intervals are 100(1 − α)% intervals and p-values below α are marked. The report is computed again with it.' }], validate: (x) => (x.a > 0 && x.a < 1 ? null : 'α must be between 0 and 1') }); if (v) this.set('alpha', v.a); } }]) },
        { label: 'Local Data Filter', checked: !!this.spec.filter, disabled: !this.table, action: () => this.report.toggleFilter() },
        { label: 'Column Switcher', checked: !!this.spec.switcher, disabled: !this.table, action: () => this.report.columnSwitcher() },
        { label: 'Redo', submenu: () => this.report.redoMenu() },
        { label: 'Save Script', submenu: () => this.report.saveMenu() },
        { label: 'Show Python Code', checked: this.report.codeShown(), action: () => this.report.toggleCode() },
        SM.axis ? SM.axis.reportItem(this.report) : null,
      ];
    }
  }

  /* An inline SVG (a tree, a network, a word cloud) for a document: a copy
     with the computed paint of each shape written in, so that it needs no
     style sheet, and without its buttons. In the dark theme the theme's
     colours become the light theme's, as paper is white. */
  const PAINT = ['fill', 'stroke', 'stroke-width', 'stroke-dasharray', 'opacity', 'fill-opacity', 'stroke-opacity', 'font-size', 'font-family', 'font-weight', 'font-style', 'text-anchor', 'dominant-baseline', 'display', 'visibility'];
  function paintedSvg(svg) {
    const copy = svg.cloneNode(true);
    const a = [svg, ...svg.querySelectorAll('*')], b = [copy, ...copy.querySelectorAll('*')];
    const light = SM.util.themeColors().dark ? lightColors() : null;
    for (let i = 0; i < a.length && i < b.length; i++) {
      const cs = getComputedStyle(a[i]);
      b[i].setAttribute('style', PAINT.map((p) => {
        let v = cs.getPropertyValue(p);
        if (light && (p === 'fill' || p === 'stroke') && light.has(v)) v = light.get(v);
        return `${p}:${v}`;
      }).join(';'));
    }
    copy.querySelectorAll('[role="button"]').forEach((e) => e.remove());     // a node's red triangle
    const r = svg.getBoundingClientRect();
    copy.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
    if (r.width > 0 && r.height > 0) { copy.setAttribute('width', String(Math.round(r.width))); copy.setAttribute('height', String(Math.round(r.height))); }
    return copy;
  }

  /* The dark theme's colours (as computed, rgb()) mapped to the light
     theme's: the tokens of the style sheets' :root rules (the light ones;
     the dark ones sit under [data-theme] and prefers-color-scheme). */
  function lightColors() {
    const lightVars = {};
    for (const sheet of document.styleSheets) {
      let rules;
      try { rules = sheet.cssRules; } catch (e) { continue; }
      for (const r of rules) {
        if (r.selectorText !== ':root' || !r.style) continue;
        for (let i = 0; i < r.style.length; i++) { const k = r.style[i]; if (k.startsWith('--')) lightVars[k] = r.style.getPropertyValue(k).trim(); }
      }
    }
    const probe = document.createElement('span');
    document.body.append(probe);
    const rgb = (v) => { if (!v || /var\(/.test(v)) return null; probe.style.color = ''; probe.style.color = v; return probe.style.color ? getComputedStyle(probe).color : null; };
    const root = getComputedStyle(document.documentElement);
    const map = new Map();
    for (const [k, lv] of Object.entries(lightVars)) {
      const d = rgb(root.getPropertyValue(k).trim()), l = rgb(lv);
      if (d && l && d !== l && !map.has(d)) map.set(d, l);
    }
    probe.remove();
    return map;
  }

  /* FNV-1a over the row numbers: a short cache key for a long row list. */
  function hashRows(rows) {
    if (!Array.isArray(rows)) return String(rows);
    let h = 2166136261;
    for (let i = 0; i < rows.length; i++) { h ^= rows[i]; h = Math.imul(h, 16777619); }
    return `${rows.length}:${(h >>> 0).toString(36)}`;
  }

  function levelOf(o) {
    const m = /level-(\d+)/.exec(o.el.className);
    return m ? +m[1] : 1;
  }

  // Redraw the reports in the other theme: axes, and traces that took the
  // theme's colours when they were made. The results come from the cache.
  if (typeof MutationObserver !== 'undefined') {
    const redraw = SM.util.debounce(() => { if (SM.app && SM.app.reports) for (const r of SM.app.reports) r.run('theme'); }, 60);
    // Only a change of theme: setting the theme that is already on redraws nothing.
    new MutationObserver((muts) => { if (muts.some((m) => m.oldValue !== document.documentElement.getAttribute('data-theme'))) redraw(); })
      .observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'], attributeOldValue: true });
  }

  /* The browser's own Print prints the report in view (smui.css, @media
     print). Graphs and tables have a size in pixels, so for the print what
     is wider than the paper is scaled to fit it, and boxes that scroll show
     all they hold; both only on paper (classes that the print rules use). */
  const PRINT_WIDTH = 700;     // A4 or Letter within the page margins, in CSS pixels
  let printFitted = [];
  function unfitForPrint() {
    for (const e of printFitted) { e.classList.remove('sm-print-flow', 'sm-print-zoom'); e.style.removeProperty('--sm-print-zoom'); }
    printFitted = [];
  }
  function fitForPrint() {
    unfitForPrint();
    // the report in front of the group in use (smui-dock.js), the one printed
    const body = document.querySelector('.sm-group.is-focused > .sm-views > .sm-view:not([hidden]) .sm-reportbody');
    if (!body) return;
    const all = [...body.querySelectorAll('div, table, pre, section, aside')].filter((e) => !e.closest('.js-plotly-plot') || e.classList.contains('js-plotly-plot'));
    for (const e of all) {
      const cs = getComputedStyle(e);
      if (/auto|scroll/.test(cs.overflowX + cs.overflowY)) { e.classList.add('sm-print-flow'); printFitted.push(e); }
    }
    const left0 = body.getBoundingClientRect().left + parseFloat(getComputedStyle(body).paddingLeft || 0);
    const zoomed = [];
    for (const e of body.querySelectorAll('.sm-plot, table.sm-rt, table.sm-kv, .sm-prof, svg, canvas')) {
      if (zoomed.some((z) => z.contains(e)) || (e.tagName.toLowerCase() !== 'div' && e.closest('.sm-plot, .js-plotly-plot')) || (e.ownerSVGElement)) continue;
      const w = Math.max(e.scrollWidth || 0, e.getBoundingClientRect().width);
      // the outline's indent: where the element starts once its row wraps
      const ob = e.closest('.sm-ob-body');
      const indent = ob ? Math.max(0, ob.getBoundingClientRect().left + parseFloat(getComputedStyle(ob).paddingLeft || 0) - left0) : 0;
      if (w > 0 && indent + w > PRINT_WIDTH) {
        e.style.setProperty('--sm-print-zoom', String(Math.max(0.25, (PRINT_WIDTH - indent) / w)));
        e.classList.add('sm-print-zoom');
        zoomed.push(e);
        if (!printFitted.includes(e)) printFitted.push(e);
      }
    }
  }
  if (typeof window !== 'undefined' && window.addEventListener) {
    window.addEventListener('beforeprint', fitForPrint);
    window.addEventListener('afterprint', unfitForPrint);
  }

  // Plotly loads on its own (async in smui.html), so the workbench can start
  // without waiting for it: graphs that were to be drawn before it came are
  // drawn when it does.
  if (typeof document !== 'undefined') {
    const tag = document.querySelector('script[src*="plotly"]');
    if (tag) tag.addEventListener('load', () => { if (document.body) kickPlots(document.body); });
  }

  SM.report = Object.freeze({ Report, Outline, Plot, Ctx, rt, combineRT, hasWebGL, plotlyText, paintedSvg, kv, code, codeHead, datedCode, unbroken, note, warn, error, cellText, rtText, tableFromRT, copyText, niceBins, kickPlots, filterRows, filterActive, renderFilter, restyle, SYMBOLS, SELECTED, get BASE() { return baseColor(); }, BAR, merge });
}(typeof self !== 'undefined' ? self : this));
