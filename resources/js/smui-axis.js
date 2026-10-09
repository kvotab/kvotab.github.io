/* ==========================================================================
   SMUI.HTML: AXIS SETTINGS (the plot core's axes)

   JMP's Axis Settings on every report graph: double-click a numeric axis
   (its tick labels), or right-click it for its menu; the red triangle's
   Axis Settings lists the graphs' axes too (for the keyboard and a phone).
   The window sets the scale (linear or log), the minimum, the maximum,
   the increment between ticks, the order (reversed or not) and reference
   lines (at a value, or over a range, with a label, a colour and a
   style). They are drawn through Plotly's axis type, range, tick0/dtick
   and shapes, and kept in the report's spec, options.axisSettings, by
   graph and axis, so a redraw, every By group and a saved project keep
   them. The graph's matplotlib code (the code block right under it) gets
   the same settings before its plt.show().

   A graph is known by the outlines it sits in, its title and its place
   among the graphs of that title there (or by opts.key); an axis by its
   Plotly name, axes that match another taking the settings of that one.

   A graph whose platform keeps its own axis settings passes opts.axes =
   { get(name), set(name, settings), own(name) -> { log, reversed } (the
   axis without settings), menu(name, info) -> more items } (Graph
   Maker, by the columns on its axes): the settings are then the
   platform's to store, to draw and to write into its code; this module
   gives it the window, the menu and the drawing helpers (patch,
   refShapes).

   A right-click in the plot itself shows opts.plotMenu() when a platform
   gives one (the graph's Marker Size and Transparency).

   In the code, the Plotly axes 'xaxis' and 'yaxis' are the figure's first
   axes; opts.axisCode(name) gives the Python of the axes of any axis (or
   null: not in the code). An axis that serves more than one subplot (the
   value axis of Distribution's histogram and its box plot) says so with
   opts.axisAlso(name) -> { plotly: [the other subplots' axes across it],
   code: [the Python of their axes] }: its reference lines cross those
   too (their labels once).

   A settings object: { log, min, max, inc, reverse, refs: [{ value, to,
   label, color, dash }] }, every part optional; min, max and the values
   in the axis's units (a date axis: milliseconds since 1970, as the page
   keeps dates). On a log scale the increment is the ratio between two
   ticks (10: a tick at each power of ten from the minimum).
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM;
  const { el, fmt } = SM.util;

  // Reference line colours: [key, label, light theme, dark theme]. The code
  // under a graph draws in the light theme's, as a document does.
  const COLORS = [['gray', 'Gray', '#786b5d', '#b3a698'], ['red', 'Red', '#b0413e', '#f08a80'], ['blue', 'Blue', '#1f4e79', '#8fb8e8'], ['green', 'Green', '#3a7d44', '#86c98f'], ['orange', 'Orange', '#b8651b', '#f0a860']];
  const DASHES = [['solid', 'Solid', '-'], ['dash', 'Dashed', '--'], ['dot', 'Dotted', ':']];
  const DAY = 86400000;
  const PX = 0.72;         // matplotlib points per page pixel (the figures are drawn at 100 pixels an inch)
  const MOST_TICKS = 500;

  const isDark = () => SM.util.themeColors().dark;
  const colorOf = (key, dark = isDark()) => { const c = COLORS.find((x) => x[0] === key) || COLORS[0]; return dark ? c[3] : c[2]; };
  const rgba = (hex, a) => { const n = parseInt(hex.slice(1), 16); return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`; };
  const axisName = (short) => `${short[0]}axis${short.slice(1)}`;        // 'x2' -> 'xaxis2'
  const shortOf = (name) => `${name[0]}${name.slice(5)}`;                // 'xaxis2' -> 'x2'
  const isAxis = (k) => /^[xy]axis\d*$/.test(k);
  const finite = (v) => typeof v === 'number' && Number.isFinite(v);
  // A position on a date axis as Plotly takes it: the page's dates are UTC milliseconds, and Plotly reads a
  // number given for a range, a tick start or a shape in the browser's local time (an hour or two off in
  // Europe); a date as text it reads as written. UTC, to the millisecond.
  const dateText = (ms) => new Date(ms).toISOString().replace('T', ' ').replace('Z', '');
  // an axis title as the page gave it to Plotly (escaped, perhaps in <b>), as plain text
  const plain = (s) => String(s || '').replace(/<[^>]*>/g, '').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&#37;/g, '%').replace(/&amp;/g, '&');

  /* ---- settings --------------------------------------------------------------- */
  function clean(s) {
    if (!s || typeof s !== 'object') return null;
    const out = {};
    if (typeof s.log === 'boolean') out.log = s.log;
    if (finite(s.min)) out.min = s.min;
    if (finite(s.max)) out.max = s.max;
    if (finite(s.inc) && s.inc > 0) out.inc = s.inc;
    if (typeof s.reverse === 'boolean') out.reverse = s.reverse;
    const refs = (Array.isArray(s.refs) ? s.refs : []).filter((r) => r && finite(r.value)).map((r) => ({
      value: r.value, to: finite(r.to) && r.to !== r.value ? r.to : null, label: r.label ? String(r.label) : '',
      color: COLORS.some((c) => c[0] === r.color) ? r.color : 'gray', dash: DASHES.some((d) => d[0] === r.dash) ? r.dash : 'solid',
    }));
    if (refs.length) out.refs = refs;
    return Object.keys(out).length ? out : null;
  }

  /* An axis of a Plotly layout with the settings applied (a new object): the
     type, the range (an end left empty stays as the report draws it: its
     own end when it fixed its range, else automatic), the ticks (every
     increment from the minimum, or from 0; on a log scale from the minimum
     or 1, the increment the ratio between ticks; on a date axis the
     increment in days), the order. */
  function patch(A0, s) {
    const A = { ...(A0 || {}) };
    s = clean(s);
    if (!s) return A;
    const type0 = (A0 && A0.type) || 'linear';
    const date = type0 === 'date';
    if (s.log != null && !date && type0 !== 'category' && type0 !== 'multicategory') A.type = s.log ? 'log' : 'linear';
    const log = A.type === 'log';
    const same = (A.type || 'linear') === type0;
    const was = A0 && Array.isArray(A0.range) && A0.range.length === 2 && A0.range.every(finite) && !A0.autorange ? A0.range : null;
    const rev0 = !!(A0 && (A0.autorange === 'reversed' || (was && was[0] > was[1])));
    const rev = s.reverse != null ? s.reverse : rev0;
    const unit = (v) => (v == null ? null : log ? Math.log10(v) : v);
    const own = was && same ? [Math.min(...was), Math.max(...was)] : null;
    let lo = unit(s.min ?? null), hi = unit(s.max ?? null);
    if (lo != null && hi == null && own) hi = own[1];
    if (hi != null && lo == null && own) lo = own[0];
    const at = (v) => (v == null || !date ? v : dateText(v));
    if (lo != null && hi != null) { A.range = (rev ? [hi, lo] : [lo, hi]).map(at); A.autorange = false; }
    else if (lo != null) { A.range = (rev ? [null, lo] : [lo, null]).map(at); A.autorange = rev ? 'max reversed' : 'max'; }
    else if (hi != null) { A.range = (rev ? [hi, null] : [null, hi]).map(at); A.autorange = rev ? 'min reversed' : 'min'; }
    else if (rev !== rev0 || (!same && A0 && Array.isArray(A0.range))) {
      // turned round, or the report's own range was in the other scale
      if (was && same) A.range = [was[1], was[0]].map(at);
      else { delete A.range; A.autorange = rev ? 'reversed' : true; }
    }
    if (s.inc > 0) {
      A.tickmode = 'linear';
      delete A.tickvals; delete A.ticktext; delete A.nticks;
      if (log) { A.dtick = Math.log10(s.inc); A.tick0 = Math.log10(s.min ?? 1); }
      else if (date) { A.dtick = s.inc * DAY; A.tick0 = dateText(s.min ?? 0); }
      else { A.dtick = s.inc; A.tick0 = s.min ?? 0; }
    }
    return A;
  }

  /* The reference lines of an axis as Plotly shapes and annotations: axis the
     axis's short name ('x2'), anchor the axis across it ('y2'), which the
     lines span. A label sits inside the plot, by the line's far end. */
  function refShapes(s, letter, axis, anchor, { log = false, dark = isDark(), labels = true, date = false } = {}) {
    const shapes = [], annotations = [];
    s = clean(s);
    const along = !anchor || anchor === 'free' ? 'paper' : `${anchor} domain`;
    const at = (v) => (date ? dateText(v) : v);        // a date axis: the date as text (dateText)
    for (const r of (s && s.refs) || []) {
      const col = colorOf(r.color, dark);
      const a = r.to != null ? Math.min(r.value, r.to) : r.value, b = r.to != null ? Math.max(r.value, r.to) : r.value;
      const span = (u, v) => (letter === 'x' ? { xref: axis, yref: along, x0: at(u), x1: at(v), y0: 0, y1: 1 } : { xref: along, yref: axis, x0: 0, x1: 1, y0: at(u), y1: at(v) });
      if (r.to != null) shapes.push({ type: 'rect', layer: 'below', line: { width: 0 }, fillcolor: rgba(col, 0.16), ...span(a, b) });
      else shapes.push({ type: 'line', layer: 'above', line: { color: col, width: 1.5, dash: r.dash }, ...span(a, a) });
      if (r.label && labels) {
        const mid = r.to != null ? (log ? Math.sqrt(a * b) : (a + b) / 2) : a;
        const pos = log ? Math.log10(mid) : date ? dateText(mid) : mid;      // an annotation on a log axis takes the log
        const text = SM.report.plotlyText(r.label);
        annotations.push(letter === 'x'
          ? { xref: axis, yref: along, x: pos, y: 1, xanchor: 'left', yanchor: 'top', xshift: 3, text, showarrow: false, font: { size: 10, color: col } }
          : { xref: along, yref: axis, x: 1, y: pos, xanchor: 'right', yanchor: 'bottom', text, showarrow: false, font: { size: 10, color: col } });
      }
    }
    return { shapes, annotations };
  }

  /* A layout with every axis's settings of S ({ axisName: settings }) applied:
     each axis, the axes that match it, and their reference lines. */
  function applyAll(L0, S, dark = isDark(), also = null) {
    if (!S) return L0;
    const L = { ...L0 };
    const shapes = [...(L0.shapes || [])], annotations = [...(L0.annotations || [])];
    let any = false;
    for (const [master, s0] of Object.entries(S)) {
      const s = clean(s0);
      if (!s || !isAxis(master)) continue;
      any = true;
      const members = [master, ...Object.keys(L).filter((k) => isAxis(k) && k !== master && k[0] === master[0] && L[k] && L[k].matches === shortOf(master))];
      for (const m of members) {
        L[m] = patch(L[m], s);
        const anchor = L[m].anchor || (m[0] === 'x' ? 'y' : 'x');
        const kind = { log: L[m].type === 'log', date: L[m].type === 'date', dark };
        const r = refShapes(s, m[0], shortOf(m), anchor, kind);
        shapes.push(...r.shapes);
        annotations.push(...r.annotations);
        // the other subplots the axis serves (axisAlso): the lines across them too
        for (const other of (also && (also(m) || {}).plotly) || []) shapes.push(...refShapes(s, m[0], shortOf(m), other, { ...kind, labels: false }).shapes);
      }
    }
    if (!any) return L0;
    L.shapes = shapes;
    L.annotations = annotations;
    return L;
  }

  /* ---- where a graph's settings live --------------------------------------------- */
  /* The graph's key in the report: the outlines it is in (under the report's
     top one, whose title names the By group), its title, and its place
     among the graphs of that title there. */
  function keyOf(p) {
    if (p._axisKey) return p._axisKey;
    if (p.opts.key != null) return (p._axisKey = String(p.opts.key));
    const box = p.box;
    if (!box.isConnected) return null;
    const titles = [];
    for (let ob = box.closest('.sm-ob'); ob; ob = ob.parentElement ? ob.parentElement.closest('.sm-ob') : null) {
      if (ob.classList.contains('level-0')) break;
      const h = ob.querySelector(':scope > .sm-ob-head > h2, :scope > .sm-ob-head > h3, :scope > .sm-ob-head > h4');
      titles.unshift(h ? h.textContent : '');
    }
    const host = box.closest('.sm-ob-body, .sm-reportcontent');
    const t = p.opts.title || '';
    let i = 0;
    if (host) for (const b of host.querySelectorAll('.sm-plot')) { if (b === box) break; if (b._plot && (b._plot.opts.title || '') === t && b.closest('.sm-ob-body, .sm-reportcontent') === host) i++; }
    return (p._axisKey = `${titles.join(' › ')}\u0001${t}\u0001${i}`);
  }

  // The report's settings of a graph ({ axisName: settings }), or null.
  function stored(p) {
    const rep = p.report;
    const all = rep && rep.spec && rep.spec.options && rep.spec.options.axisSettings;
    const k = all ? keyOf(p) : null;
    return (k && all[k]) || null;
  }

  function get(p, master) {
    if (p.opts.axes) return clean(p.opts.axes.get(master));
    const s = stored(p);
    return clean(s && s[master]);
  }

  function put(p, master, s) {
    s = clean(s);
    if (p.opts.axes) { p.opts.axes.set(master, s); return; }
    const rep = p.report;
    if (!rep || !rep.spec) return;
    const o = rep.spec.options || (rep.spec.options = {});
    const all = { ...(o.axisSettings || {}) };
    const k = keyOf(p);
    if (!k) return;
    const mine = { ...(all[k] || {}) };
    if (s) mine[master] = s; else delete mine[master];
    if (Object.keys(mine).length) all[k] = mine; else delete all[k];
    if (Object.keys(all).length) o.axisSettings = all; else delete o.axisSettings;
    rep.run();
  }

  /* The layout a graph is drawn with (smui-report.js calls this in draw()). */
  function layout(p, L) {
    if (p.opts.axes || p.opts.axisSettings === false) return L;
    return applyAll(L, stored(p), isDark(), p.opts.axisAlso || null);
  }

  /* ---- an axis of a drawn graph ----------------------------------------------------- */
  /* The axis under a mouse event: Plotly's drag boxes along an axis (its tick
     labels) are rects in the drag layer, classed ew/w/e (x) or ns/s/n (y),
     in a group named after their subplot ('x2y2'). */
  function axisAt(target) {
    const r = target && target.closest ? target.closest('.draglayer rect') : null;
    if (!r) return null;
    const cls = r.getAttribute('class') || '';
    const letter = /\b(ew|w|e)drag\b/.test(cls) ? 'x' : /\b(ns|s|n)drag\b/.test(cls) ? 'y' : null;
    const m = letter ? /^(x\d*)(y\d*)$/.exec((r.parentNode && r.parentNode.getAttribute('class')) || '') : null;
    if (!m) return null;
    return axisName(letter === 'x' ? m[1] : m[2]);
  }

  /* What the window and the menu need of an axis, from the drawn graph; why
     says why it takes no settings (not shown, categorical). */
  function info(p, name) {
    const gd = p.box;
    const fl = gd && gd._fullLayout && gd._fullLayout[name];
    if (!fl || !fl.range) return null;
    const master = fl.matches ? axisName(fl.matches) : name;
    const type = fl.type;
    let why = null;
    if (fl.visible === false || fl.showticklabels === false) why = 'the axis is not shown';
    else if (type === 'category' || type === 'multicategory' || fl.tickmode === 'array') why = 'a categorical axis has no scale: its levels are its ticks';
    else if (!['linear', 'log', 'date'].includes(type)) why = 'this axis has no scale to set';
    const r = fl.range.map((v) => fl.r2l(v));
    const data = (l) => (type === 'log' ? 10 ** l : l);
    const lo = data(Math.min(...r)), hi = data(Math.max(...r));
    // the axis as the report draws it without settings: the platform's own
    // layout, or what a platform that keeps its own settings says of it
    let ownLog, ownReversed;
    if (p.opts.axes && p.opts.axes.own) ({ log: ownLog, reversed: ownReversed } = p.opts.axes.own(master) || {});
    else {
      const own = ((p.userLayout || {})[master]) || {};
      const ownRange = Array.isArray(own.range) && own.range.every(finite) ? own.range : null;
      ownLog = (own.type || 'linear') === 'log';
      ownReversed = own.autorange === 'reversed' || !!(ownRange && ownRange[0] > ownRange[1]);
    }
    const masterFl = gd._fullLayout[master] || fl;
    return {
      name, master, letter: name[0], type, date: type === 'date', log: type === 'log', lo, hi,
      reversed: r[0] > r[1], title: plain((masterFl.title && masterFl.title.text) || (fl.title && fl.title.text) || ''), why,
      // a second axis on the other side of the plot (a Pareto plot's Cum Percent): named by its side
      side: fl.overlaying && ((name[0] === 'y' && fl.side === 'right') || (name[0] === 'x' && fl.side === 'top')) ? fl.side : null,
      ownLog: !!ownLog, ownReversed: !!ownReversed,
      // a date axis over less than a few days shows times too
      dateKind: type === 'date' && hi - lo < 4 * DAY ? 'datetime' : 'date',
    };
  }

  const axisWord = (I) => `${I.side === 'right' ? 'Right ' : I.side === 'top' ? 'Top ' : ''}${I.letter.toUpperCase()} Axis`;

  /* ---- the Axis Settings window ------------------------------------------------------- */
  function open(p, name, { addRef = false } = {}) {
    const I = info(p, name);
    if (!I) return null;
    if (I.why) { SM.ui.toast(`Axis Settings: ${I.why}.`); return null; }
    const cur = get(p, I.master) || {};
    const uid = SM.util.uid;
    const textIn = (value, placeholder, label, extra = {}) => {
      const i = el('input', { type: 'text', id: uid('ax'), inputmode: I.date ? null : 'decimal', placeholder, 'aria-label': label, autocomplete: 'off', ...extra });
      i.value = value == null ? '' : value;
      return i;
    };
    const shown = (v) => (v == null ? '' : I.date ? SM.io.formatDate(v, I.dateKind === 'datetime' || v % DAY ? 'datetime' : 'date') : String(v));
    const hintOf = (v) => (I.date ? SM.io.formatDate(v, I.dateKind) : fmt(v, { sig: 6 }).replace('−', '-'));
    const scale = el('select', { id: uid('ax'), dataset: { ax: 'scale' }, disabled: I.date || null }, el('option', { value: 'linear', text: 'Linear' }), el('option', { value: 'log', text: 'Log' }));
    scale.value = (cur.log != null ? cur.log : I.ownLog) ? 'log' : 'linear';
    const minIn = textIn(shown(cur.min), hintOf(I.lo), 'Minimum', { dataset: { ax: 'min' } });
    const maxIn = textIn(shown(cur.max), hintOf(I.hi), 'Maximum', { dataset: { ax: 'max' } });
    const incIn = textIn(cur.inc == null ? '' : String(cur.inc), 'automatic', 'Increment', { dataset: { ax: 'inc' }, inputmode: 'decimal' });
    const rev = el('input', { type: 'checkbox', id: uid('ax'), dataset: { ax: 'reverse' } });
    rev.checked = cur.reverse != null ? cur.reverse : I.ownReversed;
    const incHint = el('div', { class: 'full sm-dialog-lead sm-ax-hint' });
    const syncHint = () => {
      incHint.textContent = I.date ? 'Increment: days between two ticks, from the minimum (or from 1970-01-01).'
        : scale.value === 'log' ? 'On a log scale the increment is the ratio between two ticks: 10 puts one at each power of ten from the minimum (or from 1).'
          : 'Increment: the step between two ticks, from the minimum (or from 0). Empty boxes are automatic.';
    };
    scale.addEventListener('change', syncHint);
    syncHint();
    const grid = el('div', { class: 'sm-form sm-ax-form' },
      el('label', { for: scale.id, text: 'Scale' }), scale,
      el('label', { for: minIn.id, text: 'Minimum' }), minIn,
      el('label', { for: maxIn.id, text: 'Maximum' }), maxIn,
      el('label', { for: incIn.id, text: I.date ? 'Increment (days)' : 'Increment' }), incIn, incHint,
      el('label', { for: rev.id, text: 'Reverse Order' }), el('div', null, rev));
    // reference lines: a row each
    const list = el('div', { class: 'sm-ax-refs', role: 'list', 'aria-label': 'Reference lines' });
    const rows = [];
    const addRow = (r = {}) => {
      const value = textIn(shown(r.value), I.date ? 'a date' : 'a value', 'Reference line value', { dataset: { ax: 'ref' } });
      const to = textIn(shown(r.to), 'to (a range)', 'Reference range to', { dataset: { ax: 'refto' } });
      const label = el('input', { type: 'text', id: uid('ax'), placeholder: 'label', 'aria-label': 'Reference line label', dataset: { ax: 'reflabel' }, autocomplete: 'off' });
      label.value = r.label || '';
      const color = el('select', { 'aria-label': 'Reference line colour', dataset: { ax: 'refcolor' } }, ...COLORS.map(([k, l]) => el('option', { value: k, text: l })));
      color.value = r.color || 'gray';
      const dash = el('select', { 'aria-label': 'Reference line style', dataset: { ax: 'refdash' } }, ...DASHES.map(([k, l]) => el('option', { value: k, text: l })));
      dash.value = r.dash || 'solid';
      const rm = el('button', { type: 'button', class: 'sm-btn small', 'aria-label': 'Remove this reference line', title: 'Remove this reference line', text: '×' });
      const row = el('div', { class: 'sm-ax-ref', role: 'listitem' }, value, to, label, color, dash, rm);
      const R = { row, value, to, label, color, dash };
      rm.addEventListener('click', () => { row.remove(); rows.splice(rows.indexOf(R), 1); empty.hidden = rows.length > 0; });
      rows.push(R);
      list.append(row);
      empty.hidden = true;
      return R;
    };
    const empty = el('p', { class: 'sm-ob-note', text: 'None: add one to mark a value (or a range: fill in To) across the graph.' });
    const add = el('button', { type: 'button', class: 'sm-btn small', text: 'Add Reference Line', dataset: { ax: 'addref' } });
    add.addEventListener('click', () => { addRow().value.focus(); });
    for (const r of cur.refs || []) addRow(r);
    empty.hidden = rows.length > 0;
    const msg = el('div', { class: 'sm-launch-msg', role: 'alert' });
    const lead = el('p', { class: 'sm-dialog-lead', text: `${I.title ? `${I.title}: ` : ''}the axis runs from ${hintOf(I.lo)} to ${hintOf(I.hi)} as drawn now. An empty box leaves that part as the report draws it.` });
    const body = el('div', { class: 'sm-ax-dialog' }, lead, grid, el('h3', { class: 'sm-ax-head', text: 'Reference Lines' }), list, empty, el('div', null, add), msg);

    const parse = (i, what) => {
      const t = i.value.trim();
      if (t === '') return null;
      const v = I.date ? SM.io.parseDate(t) : SM.table.toNumber(t.replace(',', '.'));
      if (!Number.isFinite(v)) throw new Error(`${what}: ${I.date ? 'not a date (as 2024-03-01, or 2024-03-01 12:30)' : 'not a number'}`);
      return v;
    };
    const read = () => {
      const log = !I.date && scale.value === 'log';
      const out = {};
      if (!I.date && log !== I.ownLog) out.log = log;
      if (rev.checked !== I.ownReversed) out.reverse = rev.checked;
      const lo = parse(minIn, 'Minimum'), hi = parse(maxIn, 'Maximum');
      const inc = incIn.value.trim() === '' ? null : SM.table.toNumber(incIn.value.trim().replace(',', '.'));
      if (inc != null && !(inc > 0)) throw new Error('Increment: a number above 0');
      if (log && inc != null && !(inc > 1)) throw new Error('Increment: on a log scale, the ratio between two ticks, above 1');
      if (log && ((lo != null && !(lo > 0)) || (hi != null && !(hi > 0)))) throw new Error('On a log scale the minimum and the maximum must be above 0');
      if (lo != null && hi != null && !(lo < hi)) throw new Error('The minimum must be below the maximum');
      if (inc != null) {
        const a = lo ?? I.lo, b = hi ?? I.hi;
        const n = log ? Math.log(b / a) / Math.log(inc) : (b - a) / (I.date ? inc * DAY : inc);
        if (n > MOST_TICKS) throw new Error(`Increment: that is more than ${MOST_TICKS} ticks between ${hintOf(a)} and ${hintOf(b)}`);
      }
      if (lo != null) out.min = lo;
      if (hi != null) out.max = hi;
      if (inc != null) out.inc = inc;
      const refs = [];
      for (const R of rows) {
        const v = parse(R.value, 'Reference line'), to = parse(R.to, 'Reference range, To');
        if (v == null) { if (to != null || R.label.value.trim()) throw new Error('A reference line needs its value'); continue; }
        if (log && (!(v > 0) || (to != null && !(to > 0)))) throw new Error('On a log scale a reference line must be above 0');
        refs.push({ value: v, to, label: R.label.value.trim(), color: R.color.value, dash: R.dash.value });
      }
      if (refs.length) out.refs = refs;
      return out;
    };
    const dlg = SM.ui.dialog({
      title: `${axisWord(I)} Settings`, body, info: 'report:axis', className: 'sm-ax-window',
      buttons: [
        { label: 'Cancel', result: null },
        { label: 'Defaults', action: () => { put(p, I.master, null); return true; } },
        { label: 'OK', primary: true, action: () => {
          let next;
          try { next = read(); } catch (e) { msg.textContent = e.message; return false; }
          put(p, I.master, next);
          return true;
        } },
      ],
    });
    dlg.el.dataset.axis = I.master;
    if (addRef) requestAnimationFrame(() => addRow().value.focus());
    return dlg;
  }

  /* ---- the axis's right-click menu ------------------------------------------------------------ */
  function menuItems(p, I) {
    const cur = get(p, I.master) || {};
    const extra = p.opts.axes && p.opts.axes.menu ? (p.opts.axes.menu(I.master, I) || []).filter(Boolean) : [];
    const items = [{ head: `${axisWord(I)}${I.title ? `: ${I.title}` : ''}` }];
    if (!I.why) {
      const set = (fn) => { const next = { ...cur }; fn(next); put(p, I.master, next); };
      items.push(
        { label: 'Axis Settings…', action: () => open(p, I.name) },
        { label: 'Log Scale', checked: I.log, disabled: I.date, title: I.date ? 'a date axis has no log scale' : null, action: () => set((s) => {
          const log = !I.log;
          if (log === I.ownLog) delete s.log; else s.log = log;
          // the increment means another thing on the other scale; what a log scale cannot show goes
          delete s.inc;
          if (log) { if (!(s.min > 0)) delete s.min; if (!(s.max > 0)) delete s.max; if (s.refs) s.refs = s.refs.filter((r) => r.value > 0 && (r.to == null || r.to > 0)); }
        }) },
        { label: 'Reverse Order', checked: I.reversed, action: () => set((s) => { const r = !I.reversed; if (r === I.ownReversed) delete s.reverse; else s.reverse = r; }) },
        { label: 'Add Reference Line…', action: () => open(p, I.name, { addRef: true }) },
        { label: 'Remove Axis Settings', disabled: !Object.keys(cur).length, action: () => put(p, I.master, null) });
    } else if (!extra.length) items.push({ label: 'Axis Settings…', disabled: true, title: I.why });
    if (extra.length) items.push(...(items.length > 1 ? [{ separator: true }] : []), ...extra);
    return items;
  }

  /* ---- wiring a drawn graph (smui-report.js calls this after it is drawn) ---- */
  /* A double-click on an axis opens the window. Plotly takes a double-click
     on an axis to autorange it and covers the page during a press, so no
     dblclick reaches the graph: the second press on the axis turns Plotly's
     double-click off for that once, and Plotly's plotly_doubleclick opens
     the window. A double-click in the plot itself stays Plotly's (the view
     back as it was). */
  function wire(p) {
    const gd = p.box;
    if (!gd || gd._axisWired || typeof gd.on !== 'function') return;
    gd._axisWired = true;
    gd.addEventListener('mousedown', (ev) => {
      if (ev.button !== 0 || ev.detail < 2) return;
      const name = axisAt(ev.target);
      const I = name ? info(p, name) : null;
      if (!I || I.why) return;
      const c = gd._context;
      if (!c) return;
      const had = c.doubleClick;
      c.doubleClick = false;
      p._axisDbl = { name, at: Date.now() };
      setTimeout(() => { if (gd._context === c && c.doubleClick === false) c.doubleClick = had; }, 800);
    }, true);
    gd.on('plotly_doubleclick', () => {
      const d = p._axisDbl;
      p._axisDbl = null;
      if (d && Date.now() - d.at < 1500) setTimeout(() => open(p, d.name), 0);
    });
    gd.addEventListener('contextmenu', (ev) => {
      const name = axisAt(ev.target);
      const I = name ? info(p, name) : null;
      // in the plot itself: the graph's own settings (opts.plotMenu: Marker Size, Transparency), and its size
      if (!I) {
        const inPlot = ev.target && ev.target.closest && ev.target.closest('.draglayer rect.nsewdrag, .geo .bg rect, .geolayer .bg, .nsewdrag');
        const extra = inPlot && p.opts.plotMenu ? (p.opts.plotMenu() || []).filter(Boolean) : [];
        const size = p.opts.resize !== false && p.opts.fit !== false && !p.opts.sizer && typeof p.setSize === 'function' ? sizeItems(p) : [];
        if (!extra.length && !size.length) return;
        ev.preventDefault();
        ev.stopPropagation();
        SM.ui.menu([{ head: 'Graph' }, ...extra, ...(extra.length && size.length ? [{ separator: true }] : []), ...size], { x: ev.clientX, y: ev.clientY });
        return;
      }
      if (I.why && !(p.opts.axes && p.opts.axes.menu)) return;
      const items = menuItems(p, I);
      if (items.length < 2) return;
      ev.preventDefault();
      ev.stopPropagation();
      SM.ui.menu(items, { x: ev.clientX, y: ev.clientY });
    }, true);
  }

  /* ---- a graph's size (smui-report.js keeps it: Plot.setSize, resetSize) ---- */
  function sizeItems(p) {
    return [
      { label: 'Size…', title: 'The graph\'s width and height in pixels', action: () => sizeDialog(p) },
      { label: 'Default Size', disabled: !p.userSize(), title: 'The size the report draws the graph at', action: () => p.resetSize() },
    ];
  }

  async function sizeDialog(p) {
    const v = await SM.ui.form({
      title: 'Graph Size', info: 'report:size', narrow: true,
      lead: `${p.opts.title || 'The graph'}, in pixels. It is kept with the report; Default Size in the graph's right-click menu, or a double-click on its corner grip, puts the report's size back.`,
      fields: [
        { key: 'w', label: 'Width', type: 'number', value: Math.round(p.width), help: 'At least 240 pixels, and no wider than the report has room for (the graph follows a narrower window, and comes back when there is room).' },
        { key: 'h', label: 'Height', type: 'number', value: Math.round(p.height), help: '140 to 2400 pixels.' },
      ],
      validate: (x) => (!(Number(x.w) > 0) || !(Number(x.h) > 0) ? 'Give a width and a height in pixels' : null),
    });
    if (v) p.setSize(Number(v.w), Number(v.h));
  }

  /* The code's figure at the size the reader gave the graph: its one
     figsize=(w, h), in the proportion of that size to the report's. */
  function sizedCode(p, text) {
    const want = typeof p.userSize === 'function' ? p.userSize() : null;
    if (!want || !p.defaultSize) return text;
    const re = /figsize=\(\s*([0-9]*\.?[0-9]+)\s*,\s*([0-9]*\.?[0-9]+)\s*\)/g;
    if ((text.match(re) || []).length !== 1) return text;
    const r2 = (v) => String(Math.round(v * 100) / 100);
    return text.replace(re, (m, a, b) => `figsize=(${r2(a * want[0] / p.defaultSize[0])}, ${r2(b * want[1] / p.defaultSize[1])})`);
  }

  /* ---- the graph's matplotlib code ------------------------------------------------------------- */
  const py = (v) => (Number.isInteger(v) && Math.abs(v) < 1e15 ? String(v) : String(v).replace('e+', 'e'));
  const pyStr = (s) => JSON.stringify(String(s)).replace(/[\u007f-￿]/g, (c) => `\\u${c.charCodeAt(0).toString(16).padStart(4, '0')}`);

  const TICKS_DEF = [
    'def ticks_every(lo, hi, step, start=0.0, log=False):',
    '    """The ticks from lo to hi as the graph above has them: at start + k·step, or on a log scale at start·step^k."""',
    '    if log:',
    '        k = np.arange(np.ceil(np.log(lo / start) / np.log(step) - 1e-9), np.floor(np.log(hi / start) / np.log(step) + 1e-9) + 1)',
    '        return start * step ** k',
    '    k = np.arange(np.ceil((lo - start) / step - 1e-9), np.floor((hi - start) / step + 1e-9) + 1)',
    '    return start + step * k'];

  /* The Python that gives one matplotlib axes (the Python ax) an axis's
     settings. o: { log (the axis's scale, the settings' or the report's),
     date (a date axis in the page), reversed (the axis as drawn), also (the
     Python of more axes that share it: its reference lines on them too) }.
     Returns { lines, ticks } (ticks: the lines use ticks_every). */
  function pyAxis(s, letter, ax, o) {
    s = clean(s);
    const L = [];
    if (!s) return { lines: L, ticks: false };
    const a = letter, lim = `set_${a}lim`, inv = `${a}axis_inverted()`;
    const ends = a === 'x' ? ['left', 'right'] : ['bottom', 'top'];
    const v = (x) => (o.date ? `at(${py(x)})` : py(x));
    if (o.date) L.push(`at = (lambda ms: ms / 86400000) if "Date" in type(${ax}.${a}axis.get_major_formatter()).__name__ else (lambda ms: ms)   # a date: days since 1970 on matplotlib's date axis, milliseconds (as the page keeps it) on a number axis`);
    if (s.log != null) L.push(`${ax}.set_${a}scale(${s.log ? '"log"' : '"linear"'})   # Scale: ${s.log ? 'Log' : 'Linear'}`);
    if (s.reverse != null) {
      L.push(s.reverse ? `if not ${ax}.${inv}:` : `if ${ax}.${inv}:`, `    ${ax}.invert_${a}axis()   # Reverse Order: ${s.reverse ? 'on' : 'off'}`);
    }
    const rev = o.reversed;
    if (s.min != null && s.max != null) L.push(`${ax}.${lim}(${rev ? `${v(s.max)}, ${v(s.min)}` : `${v(s.min)}, ${v(s.max)}`})   # Minimum and Maximum`);
    else if (s.min != null) L.push(`${ax}.${lim}(${ends[rev ? 1 : 0]}=${v(s.min)})   # Minimum`);
    else if (s.max != null) L.push(`${ax}.${lim}(${ends[rev ? 0 : 1]}=${v(s.max)})   # Maximum`);
    let ticks = false;
    if (s.inc > 0) {
      ticks = true;
      if (o.log) L.push(`${ax}.set_${a}ticks(ticks_every(*sorted(${ax}.get_${a}lim()), ${py(s.inc)}, start=${py(s.min ?? 1)}, log=True))   # Increment: a tick every × ${py(s.inc)}`);
      else if (o.date) L.push(`${ax}.set_${a}ticks(ticks_every(*sorted(${ax}.get_${a}lim()), at(${py(s.inc * DAY)}), start=at(${py(s.min ?? 0)})))   # Increment: a tick every ${py(s.inc)} day${s.inc === 1 ? '' : 's'}`);
      else L.push(`${ax}.set_${a}ticks(ticks_every(*sorted(${ax}.get_${a}lim()), ${py(s.inc)}, start=${py(s.min ?? 0)}))   # Increment: a tick every ${py(s.inc)}`);
    }
    for (const r of s.refs || []) {
      const col = pyStr(colorOf(r.color, false));
      const ls = (DASHES.find((d) => d[0] === r.dash) || DASHES[0])[2];
      const lo = r.to != null ? Math.min(r.value, r.to) : r.value, hi = r.to != null ? Math.max(r.value, r.to) : r.value;
      const on = o.also && o.also.length ? 'a' : ax;
      if (on === 'a') L.push(`for a in (${[ax, ...o.also].join(', ')}):   # the axes that share it`);
      const ind = on === 'a' ? '    ' : '';
      if (r.to != null) L.push(`${ind}${on}.ax${a === 'x' ? 'v' : 'h'}span(${v(lo)}, ${v(hi)}, color=${col}, alpha=0.16, linewidth=0, zorder=0)   # a reference range`);
      else L.push(`${ind}${on}.ax${a === 'x' ? 'v' : 'h'}line(${v(lo)}, color=${col}, linewidth=${py(+(1.5 * PX).toFixed(3))}, linestyle=${pyStr(ls)})   # a reference line`);
      if (r.label) {
        const mid = r.to != null ? (o.log ? Math.sqrt(lo * hi) : (lo + hi) / 2) : lo;
        L.push(a === 'x'
          ? `${ax}.annotate(${pyStr(r.label)}, (${v(mid)}, 1), xycoords=("data", "axes fraction"), xytext=(3, -2), textcoords="offset points", ha="left", va="top", fontsize=8, color=${col})`
          : `${ax}.annotate(${pyStr(r.label)}, (1, ${v(mid)}), xycoords=("axes fraction", "data"), xytext=(-2, 2), textcoords="offset points", ha="right", va="bottom", fontsize=8, color=${col})`);
      }
    }
    return { lines: L, ticks };
  }

  /* The Python of a graph's axis settings for its code block, or null.
     The Plotly axes 'xaxis' and 'yaxis' are the figure's first axes (the
     page's code draws the graph on it: fig, ax = plt.subplots(...)); a
     platform maps other axes with opts.axisCode(name) -> the Python of
     their axes (or null: not in the code). */
  function codeOf(p, S) {
    const gd = p.box, fl = gd && gd._fullLayout;
    if (!S || !fl) return null;
    const expr = (name) => {
      if (p.opts.axisCode) return p.opts.axisCode(name);
      return name === 'xaxis' || name === 'yaxis' ? 'plt.gcf().axes[0]' : null;
    };
    const out = [], left = [];
    let ticks = false, last = null;
    for (const [name, s0] of Object.entries(S)) {
      const s = clean(s0);
      if (!s) continue;
      const ax = expr(name);
      const A = fl[name];
      if (!ax || !A) { left.push(name); continue; }
      const r = A.range ? A.range.map((v) => A.r2l(v)) : [0, 1];
      const also = p.opts.axisAlso ? ((p.opts.axisAlso(name) || {}).code || []) : [];
      const part = pyAxis(s, name[0], 'target', { log: A.type === 'log', date: A.type === 'date', reversed: r[0] > r[1], also });
      if (!part.lines.length) continue;
      const title = plain(A.title && A.title.text);
      if (ax !== last) { out.push(`target = ${ax}   # the graph's ${name === 'xaxis' || name === 'yaxis' ? 'axes' : `${title ? `${title} ` : ''}axis (${shortOf(name)})`}`); last = ax; }
      out.push(...part.lines);
      ticks = ticks || part.ticks;
    }
    if (!out.length) return null;
    return ['# Axis Settings: the axes as set on the graph above (double-click an axis there, or right-click it)', ...(ticks ? [...TICKS_DEF, ''] : []), ...out,
      ...(left.length ? [`# (the settings of ${left.map(shortOf).join(', ')} are not in this code)`] : [])];
  }

  /* The graph's code block (right under it) with the settings put in before
     its plt.show(); without settings, the report's own code. The report's
     Save Python Script follows. */
  function amend(p) {
    if (!p || p.opts.axes || !p.report) return;
    // the <details> of the code box under the graph (the box holds the block's
    // buttons beside its summary: kvot-summary-tools.js)
    const under = p.box.nextElementSibling;
    const block = under && under.matches && under.matches('.sm-code-box') ? under.querySelector(':scope > details.sm-code') : under;
    if (!block || !block.matches || !block.matches('details.sm-code') || !block._code) return;
    if (!keyOf(p)) return;
    // a graph's code (matplotlib, ending in plt.show()), not a result's
    if (!/(^|\n)plt\.show\(\)\s*$/.test(block._code.base)) return;
    const base = sizedCode(p, block._code.base);
    const lines = p.drawn ? codeOf(p, stored(p)) : null;
    if (!p.drawn && stored(p)) return;          // written when it is drawn (the axes' types come from Plotly)
    let next = base;
    if (lines) {
      const L = base.replace(/\s+$/, '').split('\n');
      const at = L.length && L[L.length - 1].trim() === 'plt.show()' ? L.length - 1 : L.length;
      next = [...L.slice(0, at), '', ...lines, ...L.slice(at)].join('\n');
    }
    const prev = block._code.get();
    if (next === prev) return;
    block._code.set(next);
    const code = p.report.pyCode;
    if (Array.isArray(code)) { const i = code.indexOf(prev); if (i >= 0) code[i] = next; }
  }

  /* After a report has run: the graphs' code blocks follow their settings. */
  function settle(rep) {
    for (const p of rep.plots || []) if (p.drawn) amend(p);
  }

  /* ---- the red triangle's Axis Settings: the report's graphs and their axes ---- */
  function reportItem(rep) {
    const plots = (rep.plots || []).filter((p) => p.drawn && p.box.isConnected && p.box._fullLayout);
    const axesOf = (p) => Object.keys(p.box._fullLayout).filter(isAxis).sort().map((n) => info(p, n)).filter((I) => I && !I.why && I.master === I.name);
    const withAxes = plots.map((p) => [p, axesOf(p)]).filter(([, A]) => A.length);
    if (!withAxes.length) return { label: 'Axis Settings', disabled: true, title: 'no graph of this report has a numeric axis on show' };
    const name = (p, i) => p.opts.title || `Graph ${i + 1}`;
    const axisItems = (p, A) => A.map((I) => ({ label: `${axisWord(I)}${I.title ? `: ${I.title}` : ''}${I.master !== 'xaxis' && I.master !== 'yaxis' ? ` (${shortOf(I.master)})` : ''}…`, action: () => open(p, I.name) }));
    return { label: 'Axis Settings', submenu: () => (withAxes.length === 1 ? axisItems(...withAxes[0]) : withAxes.map(([p, A], i) => ({ label: name(p, i), submenu: () => axisItems(p, A) }))) };
  }

  /* A layout for paper (Save Report as HTML or Word, Print from the dark
     theme): the reference lines, ranges and labels in the light theme's
     colours, as the graph's code draws them. */
  function paperLayout(L) {
    const map = new Map();
    for (const [, , light, dk] of COLORS) { map.set(dk.toLowerCase(), light); map.set(rgba(dk, 0.16).replace(/\s/g, ''), rgba(light, 0.16)); }
    const light = (c) => (typeof c === 'string' ? map.get(c.toLowerCase().replace(/\s/g, '')) || map.get(c.toLowerCase()) || c : c);
    for (const s of L.shapes || []) { if (s.line && s.line.color) s.line.color = light(s.line.color); if (s.fillcolor) s.fillcolor = light(s.fillcolor); }
    for (const a of L.annotations || []) if (a.font && a.font.color) a.font.color = light(a.font.color);
    return L;
  }

  if (SM.info) {
    SM.info.add({
      'report:axis': {
        kicker: 'Report', title: 'Axis Settings',
        lead: 'The scale, the range, the ticks and the reference lines of a numeric axis of a graph, as JMP\'s Axis Settings: double-click the axis (on its tick labels), or right-click it for Axis Settings…, Log Scale, Reverse Order and Add Reference Line…; the red triangle\'s Axis Settings lists every graph\'s axes. The graph\'s Python code draws the same axes.',
        sections: [
          { heading: 'Fields', choices: [
            ['Scale', '**Linear**, or **Log** (every value above 0). A date axis stays a date axis.'],
            ['Minimum, Maximum', 'Where the axis starts and ends; an empty box leaves that end as the report draws it (from the data, or the report\'s own). On a date axis, a date: 2024-03-01, or 2024-03-01 12:30.'],
            ['Increment', 'The step between two ticks, starting from the minimum (or from 0). On a log scale, the ratio between two ticks, starting from the minimum (or from 1): 10 gives a tick at each power of ten, 2 at 1, 2, 4, 8 and so on. On a date axis, days. Empty: automatic.'],
            ['Reverse Order', 'The axis runs from its largest value to its smallest.'],
            ['Reference Lines', 'A line across the graph at a value, with an optional label, colour (Gray, Red, Blue, Green, Orange) and style (Solid, Dashed, Dotted). Fill in **To** as well for a shaded range between the two values. × removes a line.'],
            ['Defaults', 'Takes this axis\'s settings away: the axis is drawn as the report draws it.'],
          ] },
          { heading: 'Kept', text: 'The settings belong to the graph in the report: a redraw, Redo and a saved project keep them, and with By they apply to the same graph of every group. Graph Maker keeps them with the column on the axis.' },
          { heading: 'The graph\'s size', text: 'Drag the grip in a graph\'s lower right corner to make it larger or smaller, or right-click the graph for Size…; see Graph Size.' },
          { heading: 'Differences from JMP', list: [
            'The log scale has no base of its own: the increment gives the ratio between ticks.',
            'The number format, minor ticks, grid lines, tick label orientation and the Power and probability scales are not here.',
            'A categorical axis has no Axis Settings; in Graph Maker, right-click it for Order By.',
            'With By, a graph\'s settings apply to the same graph of every group, where in JMP each group\'s report has its own.',
          ] },
        ],
        more: { label: 'Reports', id: 'help-reports' },
      },
      'report:size': {
        kicker: 'Report', title: 'Graph Size',
        lead: 'A graph\'s width and height, as JMP\'s frame size: drag the grip in the graph\'s lower right corner (the mouse, a pen or a finger), or focus the grip and use the arrow keys (shift for bigger steps), or right-click the graph for Size… and type them in pixels.',
        sections: [
          { heading: 'Fields', choices: [['Width', 'At least 240 pixels, and no wider than the report has room for: in a narrower window the graph gets narrower, and it comes back to your width when there is room again.'], ['Height', '140 to 2400 pixels.']] },
          { heading: 'Back to the report\'s size', text: 'A double-click on the grip, or Default Size in the graph\'s right-click menu.' },
          { heading: 'Kept', text: 'The size belongs to the graph in the report: a redraw, Redo and a saved project keep it, and with By it applies to the same graph of every group. The graph\'s Python code draws its figure in the same proportions (its figsize), and Save Report as HTML or Word and Print use the size. Graph Maker keeps its own Graph Size, which its grip sets.' },
        ],
        more: { label: 'Reports', id: 'help-reports' },
      },
    });
  }

  SM.axis = Object.freeze({ layout, wire, amend, settle, open, menuItems, info, axisAt, patch, refShapes, applyAll, clean, keyOf, get, put, pyAxis, codeOf, reportItem, paperLayout, sizeItems, sizeDialog, sizedCode, COLORS, DASHES, colorOf });
}(typeof self !== 'undefined' ? self : this));
