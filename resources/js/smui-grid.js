/* ==========================================================================
   SMUI.HTML: THE DATA GRID

   The table as JMP's data grid shows it: row numbers with the row states
   (excluded ⊘, hidden, labeled, a colour dot) on the left, one column per
   table column with its modeling type, and only the rows in view are
   drawn, so a hundred thousand rows scroll as fast as a hundred.

   Mouse: a row number selects its row (shift for a range, ctrl/⌘ to
   toggle), a header selects its column, a cell takes the cursor; double
   click or typing edits. Keys: arrows, Enter, Tab, Delete, ctrl/⌘+C copies
   the selected rows (or the cell) as tab-separated text, ctrl/⌘+V pastes
   at the cursor. Right click a header or a row number for their menus, a
   cell for Fill (to a row, to the end, a sequence repeated or continued).

   Header Graphs (the button in the bar, off at the start, as JMP's): a small
   histogram of each continuous column and a bar chart of each nominal or
   ordinal one under its heading, from every row, the selected rows' share
   drawn darker; hovering one says what it shows.
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM || (root.SM = {});
  const { el, svg, typeIcon, fmt } = SM.util;
  const { isMissing } = SM.table;

  const ROW_H = 22;
  const HEAD_H = 26;
  const GRAPH_H = 46;         // a header graph under a heading
  const RHEAD_W = 74;
  const MAX_BARS = 30;        // a categorical column's bars; more levels: the largest, and a note

  function stateIcon(kind) {
    const s = svg('svg', { viewBox: '0 0 10 10', width: 10, height: 10, 'aria-hidden': 'true' });
    if (kind === 'excluded') {
      s.append(svg('circle', { cx: 5, cy: 5, r: 4, fill: 'none', stroke: '#c0392b', 'stroke-width': 1.3 }), svg('path', { d: 'M2.2 7.8 L7.8 2.2', stroke: '#c0392b', 'stroke-width': 1.3 }));
    } else if (kind === 'hidden') {
      s.append(svg('path', { d: 'M1 5 Q5 1 9 5 Q5 9 1 5 Z', fill: 'none', stroke: 'currentColor', 'stroke-width': 1 }), svg('path', { d: 'M1.5 8.5 L8.5 1.5', stroke: 'currentColor', 'stroke-width': 1 }));
    } else if (kind === 'labeled') {
      s.append(svg('path', { d: 'M1 1 H5.5 L9 4.5 L4.5 9 L1 5.5 Z', fill: 'none', stroke: 'currentColor', 'stroke-width': 1 }), svg('circle', { cx: 3.2, cy: 3.2, r: 0.9, fill: 'currentColor' }));
    }
    return s;
  }

  class Grid {
    constructor(host, app) {
      this.app = app;
      this.table = null;
      this.widths = new Map();
      this.colSel = new Set();
      this.cursor = { row: 0, col: 0 };
      this.anchorRow = null;
      this.editing = null;
      this.host = host;
      this.bar = el('div', { class: 'sm-gridbar' });
      this.cellRef = el('span', { class: 'sm-cellref' });
      let graphsOn = false;
      try { graphsOn = localStorage.getItem('smui.headerGraphs') === '1'; } catch (e) { /* storage unavailable */ }
      this.graphs = graphsOn;
      this.graphBtn = el('button', { type: 'button', class: 'sm-btn small sm-graphbtn', text: 'Header Graphs', 'aria-pressed': String(graphsOn), title: 'Small graphs of each column under its heading: a histogram, or a bar per level' });
      this.graphBtn.addEventListener('click', () => this.setGraphs(!this.graphs));
      this.bar.append(
        el('button', { type: 'button', class: 'sm-btn small', text: '+ Row', onclick: () => this._addRow() }),
        el('button', { type: 'button', class: 'sm-btn small', text: '+ Column', onclick: () => app.newColumn() }),
        this.graphBtn, typeof KvotInfo !== 'undefined' ? KvotInfo.slot('grid:headergraphs') : null,
        this.cellRef, el('span', { class: 'sm-spacer' }));
      this.scroller = el('div', { class: 'sm-grid', tabindex: '0', role: 'grid', 'aria-label': 'Data table' });
      this.inner = el('div', { class: 'sm-grid-inner' });
      this.head = el('div', { class: 'sm-grid-head' });
      this.rows = el('div', { class: 'sm-grid-rows' });
      this.inner.append(this.head, this.rows);
      this.scroller.append(this.inner);
      this.empty = el('div', { class: 'sm-grid-empty' });
      host.append(el('div', { class: 'sm-gridwrap' }, this.bar, this.scroller));
      this.scroller.addEventListener('scroll', () => this._schedule());
      new ResizeObserver(() => this._schedule()).observe(this.scroller);
      this.scroller.addEventListener('keydown', (ev) => this._key(ev));
      this.scroller.addEventListener('copy', (ev) => this._copy(ev));
      this.scroller.addEventListener('paste', (ev) => this._paste(ev));
      this.scroller.addEventListener('mousedown', (ev) => this._mouse(ev));
      this.scroller.addEventListener('dblclick', (ev) => this._dbl(ev));
      this.scroller.addEventListener('contextmenu', (ev) => this._context(ev));
    }

    setTable(table) {
      if (this.off) this.off.forEach((f) => f());
      this.table = table;
      this.colSel.clear();
      this.cursor = { row: 0, col: 0 };
      this.cancelEdit();
      if (table) {
        this.off = [
          table.on('data', () => { this._graphCache = null; this._layout(); this._schedule(); }),
          // the header graphs show the selected rows' share
          table.on('rowstate', (e) => { if (this.graphs && (!e || e.kind === 'selected' || e.kind === 'all')) this._layout(); this._schedule(); }),
        ];
      } else this.off = null;
      this._layout();
      this.scroller.scrollTop = 0;
      this._schedule();
    }

    width(c) {
      if (!this.widths.has(c.id)) this.widths.set(c.id, Math.max(72, Math.min(240, 30 + c.name.length * 7.6 + (c.formula ? 12 : 0) + (c.role === 'label' ? 32 : 0))));
      return this.widths.get(c.id);
    }

    // the height of the headings: taller with the header graphs
    get headH() { return this.graphs ? HEAD_H + GRAPH_H : HEAD_H; }

    /* Header Graphs on or off (kept for the next visit in this browser). */
    setGraphs(on) {
      this.graphs = !!on;
      this.graphBtn.setAttribute('aria-pressed', String(this.graphs));
      try { localStorage.setItem('smui.headerGraphs', this.graphs ? '1' : '0'); } catch (e) { /* storage unavailable */ }
      this.refresh();
    }

    _layout() {
      const t = this.table;
      this.head.replaceChildren();
      this.head.classList.toggle('with-graphs', !!(t && this.graphs));
      this.rows.style.top = `${this.headH}px`;
      if (!t) { this.inner.style.width = '0px'; this.inner.style.height = '0px'; return; }
      const corner = el('div', { class: 'sm-grid-corner', style: { width: `${RHEAD_W}px` }, title: null });
      corner.addEventListener('click', () => { t.select(t.nrows ? Array.from({ length: t.nrows }, (_, i) => i) : []); });
      this.head.append(corner);
      let total = RHEAD_W;
      t.columns.forEach((c, j) => {
        const w = this.width(c);
        total += w;
        const flags = [c.formula ? 'ƒ' : '', c.role === 'label' ? 'label' : ''].filter(Boolean).join(' ');
        const parts = [typeIcon(c.modelingType), el('span', { class: 'sm-hname', text: c.name }), flags ? el('span', { class: 'sm-hflag', text: flags }) : null];
        const h = this.graphs
          ? el('div', { class: `sm-hcell with-graph${this.colSel.has(c.id) ? ' is-selected' : ''}`, style: { width: `${w}px`, height: `${this.headH}px` }, dataset: { col: String(j) }, role: 'columnheader' },
            el('div', { class: 'sm-hline' }, ...parts), this._headerGraph(c, w), el('span', { class: 'sm-resizer', dataset: { resize: String(j) } }))
          : el('div', { class: `sm-hcell${this.colSel.has(c.id) ? ' is-selected' : ''}`, style: { width: `${w}px` }, dataset: { col: String(j) }, role: 'columnheader' },
            ...parts, el('span', { class: 'sm-resizer', dataset: { resize: String(j) } }));
        h.setAttribute('aria-label', `${c.name}, ${SM.util.TYPE_LABEL[c.modelingType]}`);
        this.head.append(h);
      });
      this.inner.style.width = `${total}px`;
      this.inner.style.height = `${this.headH + t.nrows * ROW_H}px`;
      this.head.style.width = `${total}px`;
    }

    /* A column's header graph: its bins (or levels) and their counts, over
       every row, with the selected rows' counts. */
    graphData(c) {
      const t = this.table;
      if (!this._graphCache || this._graphCache.version !== t.version) this._graphCache = { version: t.version, cols: new Map() };
      let d = this._graphCache.cols.get(c.id);
      if (!d) {
        const vals = c.values;
        if (c.isNumeric && !c.isCategorical) {
          const xs = [];
          let lo = Infinity, hi = -Infinity;
          for (const v of vals) if (Number.isFinite(v)) { xs.push(v); if (v < lo) lo = v; if (v > hi) hi = v; }
          if (!xs.length) d = { kind: 'none', n: 0 };
          else {
            const b = SM.report.niceBins(xs, Math.min(14, Math.max(4, Math.ceil(Math.log2(xs.length) + 1))));
            const k = Math.max(1, Math.round((b.end - b.start) / b.size));
            const bin = (v) => Math.min(k - 1, Math.max(0, Math.floor((v - b.start) / b.size)));
            d = { kind: 'hist', start: b.start, size: b.size, k, bin, n: xs.length, lo, hi };
          }
        } else {
          const lv = t.levels(c);
          const at = new Map(lv.map((v, i) => [v, i]));
          d = { kind: 'bars', levels: lv, at, n: vals.filter((v) => !isMissing(v)).length };
        }
        this._graphCache.cols.set(c.id, d);
      }
      // counts: of every row, and of the selected ones (drawn over them)
      const m = d.kind === 'hist' ? d.k : d.kind === 'bars' ? d.levels.length : 0;
      const all = new Array(m).fill(0), sel = new Array(m).fill(0);
      const vals = c.values;
      for (let i = 0; i < vals.length; i++) {
        const v = vals[i];
        let j = -1;
        if (d.kind === 'hist') { if (Number.isFinite(v)) j = d.bin(v); } else if (d.kind === 'bars') { const k = d.at.get(v); if (k != null) j = k; }
        if (j < 0) continue;
        all[j]++;
        if (t.state[i] & 1) sel[j]++;
      }
      return { ...d, all, sel };
    }

    _headerGraph(c, w) {
      const d = this.graphData(c);
      const W = Math.max(20, w - 10), H = GRAPH_H - 8;
      const box = SM.util.svg('svg', { class: 'sm-hgraph', width: W, height: H, viewBox: `0 0 ${W} ${H}`, role: 'img' });
      let title;
      if (d.kind === 'none' || !d.all.length || !d.n) {
        title = `${c.name}: no values`;
        box.append(SM.util.svg('line', { x1: 0, y1: H - 0.5, x2: W, y2: H - 0.5, class: 'sm-hgraph-axis' }));
      } else {
        // the largest bars of a column with many levels
        let idx = d.all.map((_, i) => i);
        if (d.kind === 'bars' && idx.length > MAX_BARS) idx = idx.sort((a, b) => d.all[b] - d.all[a]).slice(0, MAX_BARS).sort((a, b) => a - b);
        const top = Math.max(1, ...idx.map((i) => d.all[i]));
        const bw = W / idx.length;
        const gap = d.kind === 'bars' ? Math.min(2, bw * 0.2) : Math.min(1, bw * 0.08);
        idx.forEach((i, k) => {
          const h = (d.all[i] / top) * (H - 2), hs = (d.sel[i] / top) * (H - 2);
          const x = k * bw + gap / 2, ww = Math.max(0.5, bw - gap);
          if (h > 0) box.append(SM.util.svg('rect', { x: x.toFixed(2), y: (H - h).toFixed(2), width: ww.toFixed(2), height: h.toFixed(2), class: 'sm-hgraph-bar' }));
          if (hs > 0) box.append(SM.util.svg('rect', { x: x.toFixed(2), y: (H - hs).toFixed(2), width: ww.toFixed(2), height: hs.toFixed(2), class: 'sm-hgraph-sel' }));
        });
        box.append(SM.util.svg('line', { x1: 0, y1: H - 0.5, x2: W, y2: H - 0.5, class: 'sm-hgraph-axis' }));
        const nsel = d.sel.reduce((a, b) => a + b, 0);
        if (d.kind === 'hist') title = `${c.name}: a histogram of ${d.n} values, ${valueText(c, d.lo)} to ${valueText(c, d.hi)}, bins of ${fmt(d.size)}${nsel ? `; ${nsel} selected (darker)` : ''}`;
        else title = `${c.name}: ${d.levels.length} levels, ${d.n} values${idx.length < d.levels.length ? `; the ${idx.length} largest drawn` : ''}: ${idx.slice(0, 6).map((i) => `${cellText(c, d.levels[i])} ${d.all[i]}`).join(', ')}${idx.length > 6 ? ', …' : ''}${nsel ? `; ${nsel} selected (darker)` : ''}`;
      }
      box.setAttribute('aria-label', title);
      box.append(SM.util.svg('title', {}, document.createTextNode(title)));
      return box;
    }

    _schedule() {
      if (this._raf) return;
      this._raf = requestAnimationFrame(() => { this._raf = null; this._render(); });
    }

    refresh() { this._layout(); this._render(); }

    _render() {
      const t = this.table;
      if (!t) { this.rows.replaceChildren(); return; }
      const top = this.scroller.scrollTop;
      const h = this.scroller.clientHeight || 600;
      const first = Math.max(0, Math.floor(top / ROW_H) - 4);
      const last = Math.min(t.nrows, Math.ceil((top + h) / ROW_H) + 4);
      const frag = document.createDocumentFragment();
      const cols = t.columns;
      const widths = cols.map((c) => this.width(c));
      const label = t.labelColumn();
      for (let i = first; i < last; i++) {
        const st = t.state[i];
        const row = el('div', { class: 'sm-grow', style: { top: `${i * ROW_H}px` }, dataset: { row: String(i) }, role: 'row' });
        if (st & 1) row.classList.add('is-selected');
        if (st & 2) row.classList.add('is-excluded');
        if (st & 4) row.classList.add('is-hidden');
        const marks = el('span', { class: 'sm-rstate' });
        if (t.color[i] >= 0) marks.append(el('span', { class: 'sm-rdot', style: { background: SM.util.colorOf(t.color[i]) } }));
        if (st & 2) marks.append(stateIcon('excluded'));
        if (st & 4) marks.append(stateIcon('hidden'));
        if (st & 8) marks.append(stateIcon('labeled'));
        row.append(el('div', { class: 'sm-rhead', style: { width: `${RHEAD_W}px` }, dataset: { rh: String(i) }, title: label ? String(label.values[i] ?? '') : null },
          marks, el('span', { class: 'sm-rnum', text: String(i + 1) })));
        for (let j = 0; j < cols.length; j++) {
          const c = cols[j];
          const v = c.values[i];
          // a missing value code shows as it is stored, drawn as missing
          const code = c.coded && c.coded[i] !== undefined ? c.coded[i] : undefined;
          const miss = code === undefined && isMissing(v);
          const cell = el('div', { class: `sm-cell${c.isNumeric ? ' num' : ''}${miss ? ' miss' : ''}${code !== undefined ? ' miss coded' : ''}${this.colSel.has(c.id) ? ' is-colsel' : ''}${this.cursor.row === i && this.cursor.col === j ? ' is-cursor' : ''}`, style: { width: `${widths[j]}px` }, dataset: { c: String(j) }, role: 'gridcell' });
          if (code !== undefined) { cell.textContent = cellText(c, code); cell.title = `${valueText(c, code)}: a missing value code of ${c.name}`; }
          else if (miss) cell.textContent = c.isNumeric ? '•' : '';
          else {
            cell.textContent = cellText(c, v);
            if (c.valueLabels && SM.table.labelOf(c, v) != null) { cell.classList.add('labeled'); cell.title = `${valueText(c, v)}: ${SM.table.labelOf(c, v)}`; }
          }
          row.append(cell);
        }
        frag.append(row);
      }
      this.rows.replaceChildren(frag);
      this._updateRef();
      if (this.editing) this._placeEditor();
    }

    _updateRef() {
      const t = this.table;
      if (!t || !t.columns.length || !t.nrows) { this.cellRef.textContent = t ? `${t.nrows} rows × ${t.columns.length} columns` : ''; return; }
      const c = t.columns[this.cursor.col];
      if (!c) return;
      const s = SM.table.storedOf(c, this.cursor.row);
      const lab = SM.table.labelOf(c, s);
      const coded = c.coded && c.coded[this.cursor.row] !== undefined;
      this.cellRef.textContent = `row ${this.cursor.row + 1}, ${c.name}: ${isMissing(s) ? '(missing)' : `${valueText(c, s)}${lab != null ? ` (${lab})` : ''}${coded ? ', a missing value code' : ''}`}`;
    }

    /* ---- mouse -------------------------------------------------------- */
    _hit(ev) {
      const cell = ev.target.closest('.sm-cell');
      const rh = ev.target.closest('.sm-rhead');
      const hc = ev.target.closest('.sm-hcell');
      const row = ev.target.closest('.sm-grow');
      return { cell, rh, hc, row: row ? +row.dataset.row : null, col: cell ? +cell.dataset.c : hc ? +hc.dataset.col : null };
    }

    _mouse(ev) {
      if (ev.button !== 0) return;
      const t = this.table;
      if (!t) return;
      const rz = ev.target.closest('.sm-resizer');
      if (rz) { this._startResize(ev, +rz.dataset.resize); return; }
      const h = this._hit(ev);
      if (h.hc) {
        const c = t.columns[h.col];
        if (ev.shiftKey && this.colSel.size) {
          const idx = t.columns.map((x, k) => (this.colSel.has(x.id) ? k : -1)).filter((k) => k >= 0);
          const a = Math.min(...idx, h.col), b = Math.max(...idx, h.col);
          for (let k = a; k <= b; k++) this.colSel.add(t.columns[k].id);
        } else if (ev.metaKey || ev.ctrlKey) {
          if (this.colSel.has(c.id)) this.colSel.delete(c.id); else this.colSel.add(c.id);
        } else {
          const only = this.colSel.size === 1 && this.colSel.has(c.id);
          this.colSel.clear();
          if (!only) this.colSel.add(c.id);
        }
        this.cursor.col = h.col;
        this._layout();
        this._render();
        this.app.emit('columnselection', this.selectedColumns());
        return;
      }
      if (h.rh && h.row != null) {
        ev.preventDefault();
        this.cancelEdit();
        const r = h.row;
        if (ev.shiftKey && this.anchorRow != null) {
          const a = Math.min(this.anchorRow, r), b = Math.max(this.anchorRow, r);
          t.select(Array.from({ length: b - a + 1 }, (_, k) => a + k), ev.metaKey || ev.ctrlKey ? 'add' : 'replace');
        } else if (ev.metaKey || ev.ctrlKey) {
          t.select([r], 'toggle');
          this.anchorRow = r;
        } else {
          t.select(t.has(r, 'selected') && t.counts().selected === 1 ? [] : [r]);
          this.anchorRow = r;
        }
        // Drag down the row numbers to select a range.
        const move = (e2) => {
          const hit = document.elementFromPoint(e2.clientX, e2.clientY)?.closest?.('.sm-grow');
          if (!hit) return;
          const r2 = +hit.dataset.row;
          const a = Math.min(r, r2), b = Math.max(r, r2);
          t.select(Array.from({ length: b - a + 1 }, (_, k) => a + k));
        };
        const up = () => { removeEventListener('mousemove', move); removeEventListener('mouseup', up); };
        addEventListener('mousemove', move);
        addEventListener('mouseup', up);
        return;
      }
      if (h.cell && h.row != null) {
        if (this.editing && (this.editing.row !== h.row || this.editing.col !== h.col)) this.commitEdit();
        this.cursor = { row: h.row, col: h.col };
        this.scroller.focus({ preventScroll: true });
        this._render();
      }
    }

    _dbl(ev) {
      const h = this._hit(ev);
      if (h.cell && h.row != null) this.startEdit(h.row, h.col);
      else if (h.hc) this.app.columnInfo(this.table.columns[h.col]);
    }

    _context(ev) {
      const t = this.table;
      if (!t) return;
      const h = this._hit(ev);
      if (h.hc) {
        ev.preventDefault();
        const c = t.columns[h.col];
        if (!this.colSel.has(c.id)) { this.colSel.clear(); this.colSel.add(c.id); this._layout(); this._render(); }
        SM.ui.menu(this.app.columnMenu(c), { x: ev.clientX, y: ev.clientY });
      } else if (h.rh || h.cell) {
        ev.preventDefault();
        if (h.row != null && !t.has(h.row, 'selected')) t.select([h.row]);
        const items = this.app.rowMenu();
        // a cell: Fill, from the cells of its column in the selected rows
        if (h.cell && h.row != null && h.col != null && t.columns[h.col]) {
          this.cursor = { row: h.row, col: h.col };
          this._render();
          items.unshift({ label: 'Fill', submenu: () => this.fillItems(h.col) }, { separator: true });
        }
        SM.ui.menu(items, { x: ev.clientX, y: ev.clientY });
      }
    }

    /* ---- Fill (a cell's right click) -----------------------------------------
       The source is the column's cells in the selected rows (the cell's own
       row is selected by the right click), taken in row order; the rows after
       the last of them are filled:
         Fill to Row…            with the last source value, to the row given
         Fill to End of Table    with the last source value, to the last row
         Repeat Sequence…        the source values over and over
         Continue Sequence…      numbers (dates too) along the straight line
                                 through the source values (1, 2 -> 3, 4, …)
       A formula column fills itself; Edit > Undo takes a fill back. */
    fillItems(col) {
      const t = this.table;
      const c = t && t.columns[col];
      if (!c) return [];
      const src = t.selectedRows();
      const last = src.length ? src[src.length - 1] : this.cursor.row;
      const none = c.formula ? `${c.name} is a formula column` : last >= t.nrows - 1 ? 'no rows after the selection' : null;
      const vals = (src.length ? src : [last]).map((r) => SM.table.storedOf(c, r));
      const numbers = c.isNumeric && vals.every((v) => Number.isFinite(v));
      return [
        { label: 'Fill to Row…', disabled: !!none, title: none, action: () => this.fillToRow(c) },
        { label: 'Fill to End of Table', disabled: !!none, title: none, action: () => this.fill(c, 'value', t.nrows - 1) },
        { label: 'Repeat Sequence to End of Table', disabled: !!none || vals.length < 2, title: none || (vals.length < 2 ? 'select two or more rows: their values repeat' : null), action: () => this.fill(c, 'repeat', t.nrows - 1) },
        { label: 'Continue Sequence to End of Table', disabled: !!none || vals.length < 2 || !numbers, title: none || (vals.length < 2 ? 'select two or more rows: their sequence goes on' : !numbers ? 'a sequence of numbers (or dates) goes on' : null), action: () => this.fill(c, 'continue', t.nrows - 1) },
      ];
    }

    async fillToRow(c) {
      const t = this.table;
      const src = t.selectedRows();
      const last = src.length ? src[src.length - 1] : this.cursor.row;
      const v = await SM.ui.form({ title: 'Fill to Row', info: 'grid:fill', fields: [{ key: 'row', label: 'Fill down to row', type: 'number', value: t.nrows, help: `The last row to fill, after row ${last + 1} (the last selected row), up to ${t.nrows}: the rows between take the last selected row's value of ${c.name}.` }],
        validate: (x) => (!(x.row > last + 1) ? `A row after ${last + 1}` : null) });
      if (!v) return null;
      return this.fill(c, 'value', Math.min(t.nrows, Math.round(v.row)) - 1);
    }

    /* Fill column c after the selected rows, to row index `to`: kind
       'value', 'repeat' or 'continue'. Returns how many cells changed. */
    fill(c, kind, to) {
      const t = this.table;
      if (c.formula) { SM.ui.toast(`${c.name} is a formula column: its formula fills it`); return 0; }
      const src = t.selectedRows();
      const rows = src.length ? src : [this.cursor.row];
      const last = rows[rows.length - 1];
      to = Math.min(t.nrows - 1, to);
      if (to <= last) { SM.ui.toast('No rows to fill after the selected ones'); return 0; }
      const vals = rows.map((r) => SM.table.storedOf(c, r));
      const next = t.storedValues(c);
      let line = null;
      if (kind === 'continue') {
        // the least squares line through (position, value): exact for 1, 2, 3 or dates a week apart
        const n = vals.length, mx = (n - 1) / 2;
        const my = vals.reduce((a, b) => a + b, 0) / n;
        let sxy = 0, sxx = 0;
        vals.forEach((y, i) => { sxy += (i - mx) * (y - my); sxx += (i - mx) * (i - mx); });
        const b = sxx ? sxy / sxx : 0;
        line = (i) => { const y = my + b * (i - mx); return Number.isFinite(y) ? +y.toPrecision(14) : NaN; };
      }
      for (let r = last + 1, k = 0; r <= to; r++, k++) {
        next[r] = kind === 'repeat' ? vals[k % vals.length] : kind === 'continue' ? line(vals.length + k) : vals[vals.length - 1];
      }
      this.app.record(t, kind === 'repeat' ? 'Repeat Sequence' : kind === 'continue' ? 'Continue Sequence' : 'Fill');
      t.setValues(c.id, next);
      const n = to - last;
      SM.ui.toast(`Filled ${n} cell${n === 1 ? '' : 's'} of ${c.name}, rows ${last + 2} to ${to + 1}`);
      return n;
    }

    _startResize(ev, j) {
      ev.preventDefault();
      ev.stopPropagation();
      const c = this.table.columns[j];
      const x0 = ev.clientX, w0 = this.width(c);
      const move = (e2) => { this.widths.set(c.id, Math.max(40, w0 + e2.clientX - x0)); this._layout(); this._render(); };
      const up = () => { removeEventListener('mousemove', move); removeEventListener('mouseup', up); };
      addEventListener('mousemove', move);
      addEventListener('mouseup', up);
    }

    selectedColumns() {
      return this.table ? this.table.columns.filter((c) => this.colSel.has(c.id)) : [];
    }

    /* ---- editing -------------------------------------------------------- */
    startEdit(row, col, initial = null) {
      const t = this.table;
      if (!t || row < 0 || row >= t.nrows || col < 0 || col >= t.columns.length) return;
      const c = t.columns[col];
      if (c.formula) { SM.ui.toast(`${c.name} is a formula column; edit its formula in Column Info`); return; }
      this.cancelEdit();
      this.cursor = { row, col };
      const input = el('input', { class: 'sm-cell-edit', type: 'text', 'aria-label': `Edit ${c.name}, row ${row + 1}` });
      // the stored value, not its label: what is typed is stored
      const v = SM.table.storedOf(c, row);
      input.value = initial != null ? initial : (isMissing(v) ? '' : valueText(c, v));
      this.editing = { row, col, input };
      this.inner.append(input);
      this._placeEditor();
      input.focus();
      if (initial != null) input.setSelectionRange(input.value.length, input.value.length); else input.select();
      input.addEventListener('keydown', (ev) => {
        if (ev.key === 'Enter') { ev.preventDefault(); this.commitEdit(); this._move(1, 0); this.scroller.focus({ preventScroll: true }); }
        else if (ev.key === 'Tab') { ev.preventDefault(); this.commitEdit(); this._move(0, ev.shiftKey ? -1 : 1); this.scroller.focus({ preventScroll: true }); }
        else if (ev.key === 'Escape') { ev.preventDefault(); ev.stopPropagation(); this.cancelEdit(); this.scroller.focus({ preventScroll: true }); }
      });
      input.addEventListener('blur', () => { if (this.editing && this.editing.input === input) this.commitEdit(); });
    }

    _placeEditor() {
      const e = this.editing;
      if (!e) return;
      const t = this.table;
      let x = RHEAD_W;
      for (let j = 0; j < e.col; j++) x += this.width(t.columns[j]);
      Object.assign(e.input.style, { left: `${x}px`, top: `${this.headH + e.row * ROW_H}px`, width: `${this.width(t.columns[e.col])}px`, height: `${ROW_H}px` });
    }

    commitEdit() {
      const e = this.editing;
      if (!e) return;
      this.editing = null;
      const t = this.table;
      const c = t.columns[e.col];
      const text = e.input.value.trim();
      e.input.remove();
      let v = text;
      if (c.isNumeric && c.format && /date/.test(c.format.kind || '')) v = text === '' ? NaN : SM.io.parseDate(text);
      else if (c.isNumeric) v = SM.table.toNumber(text.replace(',', '.'));
      const old = SM.table.storedOf(c, e.row);
      const same = c.isNumeric ? (Number.isNaN(old) && Number.isNaN(v)) || old === v : (old ?? '') === (v ?? '');
      if (same) { this._render(); return; }
      this.recordEdit(t, 'Edit Cell', [[e.row, c.id]]);
      t.setCell(e.row, c.id, v);
    }

    /* Undo for a few cells: their old values, or a copy of the table when a
       column has missing value codes (the old values would not keep them). */
    recordEdit(t, label, cells) {
      if (cells.some(([, id]) => { const c = t.col(id); return c && c.missingCodes; })) this.app.record(t, label);
      else this.app.recordCells(t, label, cells);
    }

    cancelEdit() {
      if (!this.editing) return;
      this.editing.input.remove();
      this.editing = null;
    }

    _addRow() {
      const t = this.table;
      if (!t) return;
      t.addRows(1);
      this.cursor = { row: t.nrows - 1, col: 0 };
      this.scroller.scrollTop = this.scroller.scrollHeight;
      this.startEdit(t.nrows - 1, 0);
    }

    /* ---- keys ------------------------------------------------------------- */
    _move(dr, dc) {
      const t = this.table;
      if (!t) return;
      this.cursor.row = Math.max(0, Math.min(t.nrows - 1, this.cursor.row + dr));
      this.cursor.col = Math.max(0, Math.min(t.columns.length - 1, this.cursor.col + dc));
      this._reveal();
      this._render();
    }

    _reveal() {
      const s = this.scroller;
      const hh = this.headH;
      const y = hh + this.cursor.row * ROW_H;
      if (y < s.scrollTop + hh) s.scrollTop = y - hh;
      else if (y + ROW_H > s.scrollTop + s.clientHeight) s.scrollTop = y + ROW_H - s.clientHeight;
      let x = RHEAD_W;
      for (let j = 0; j < this.cursor.col; j++) x += this.width(this.table.columns[j]);
      const w = this.width(this.table.columns[this.cursor.col] || { id: '', name: '' });
      if (x < s.scrollLeft + RHEAD_W) s.scrollLeft = x - RHEAD_W;
      else if (x + w > s.scrollLeft + s.clientWidth) s.scrollLeft = x + w - s.clientWidth;
    }

    _key(ev) {
      if (this.editing || !this.table) return;
      const t = this.table;
      const mod = ev.metaKey || ev.ctrlKey;
      const k = ev.key;
      if (k === 'ArrowDown') { ev.preventDefault(); this._move(mod ? t.nrows : 1, 0); }
      else if (k === 'ArrowUp') { ev.preventDefault(); this._move(mod ? -t.nrows : -1, 0); }
      else if (k === 'ArrowRight' || (k === 'Tab' && !ev.shiftKey)) { ev.preventDefault(); this._move(0, 1); }
      else if (k === 'ArrowLeft' || (k === 'Tab' && ev.shiftKey)) { ev.preventDefault(); this._move(0, -1); }
      else if (k === 'PageDown') { ev.preventDefault(); this._move(Math.floor(this.scroller.clientHeight / ROW_H) - 1, 0); }
      else if (k === 'PageUp') { ev.preventDefault(); this._move(-Math.floor(this.scroller.clientHeight / ROW_H) + 1, 0); }
      else if (k === 'Enter' || k === 'F2') { ev.preventDefault(); this.startEdit(this.cursor.row, this.cursor.col); }
      else if (k === 'Delete' || k === 'Backspace') {
        ev.preventDefault();
        const c = t.columns[this.cursor.col];
        if (c && !c.formula) { this.recordEdit(t, 'Clear Cell', [[this.cursor.row, c.id]]); t.setCell(this.cursor.row, c.id, c.isNumeric ? NaN : null); }
      } else if (mod && (k === 'z' || k === 'Z')) { ev.preventDefault(); if (ev.shiftKey) this.app.redo(); else this.app.undo(); }
      else if (mod && (k === 'y' || k === 'Y')) { ev.preventDefault(); this.app.redo(); }
      else if (mod && (k === 'a' || k === 'A')) { ev.preventDefault(); t.select(Array.from({ length: t.nrows }, (_, i) => i)); }
      else if (k.length === 1 && !mod && !ev.altKey) { ev.preventDefault(); this.startEdit(this.cursor.row, this.cursor.col, k); }
    }

    /* ---- clipboard -------------------------------------------------------- */
    _copy(ev) {
      const t = this.table;
      if (!t || this.editing) return;
      const rows = t.selectedRows();
      const cols = this.selectedColumns().length ? this.selectedColumns() : (rows.length ? t.columns : [t.columns[this.cursor.col]]);
      const list = rows.length ? rows : [this.cursor.row];
      const lines = [];
      if (rows.length || this.selectedColumns().length) lines.push(cols.map((c) => c.name).join('\t'));
      // the stored values (a code as the code, a labelled value as the value), so that a paste gives them back
      for (const r of list) lines.push(cols.map((c) => { const v = SM.table.storedOf(c, r); return isMissing(v) ? '' : valueText(c, v); }).join('\t'));
      ev.clipboardData.setData('text/plain', lines.join('\n'));
      ev.preventDefault();
      SM.ui.toast(`Copied ${list.length} row${list.length === 1 ? '' : 's'} × ${cols.length} column${cols.length === 1 ? '' : 's'}`);
    }

    _paste(ev) {
      const t = this.table;
      if (!t || this.editing) return;
      const text = ev.clipboardData.getData('text/plain');
      if (!text) return;
      ev.preventDefault();
      const lines = text.replace(/\r\n?/g, '\n').replace(/\n$/, '').split('\n').map((l) => l.split('\t'));
      const r0 = this.cursor.row, c0 = this.cursor.col;
      const need = r0 + lines.length - t.nrows;
      if (need > 0) this.app.record(t, 'Paste');
      else {
        const cells = [];
        for (let i = 0; i < lines.length; i++) for (let j = 0; j < lines[i].length; j++) { const c = t.columns[c0 + j]; if (c && !c.formula) cells.push([r0 + i, c.id]); }
        this.recordEdit(t, 'Paste', cells);
      }
      if (need > 0) t.addRows(need);
      for (let i = 0; i < lines.length; i++) for (let j = 0; j < lines[i].length; j++) {
        const c = t.columns[c0 + j];
        if (!c || c.formula) continue;
        let v = lines[i][j];
        if (c.isNumeric && c.format && /date/.test(c.format.kind || '')) v = String(v).trim() === '' ? NaN : SM.io.parseDate(String(v).trim());
        else if (c.isNumeric) v = SM.table.toNumber(String(v).replace(',', '.'));
        t.setCell(r0 + i, c.id, v, { silent: true });
      }
      t._changed('data', { pasted: true });      // (the data version too: results computed before are stale)
      SM.ui.toast(`Pasted ${lines.length} × ${Math.max(...lines.map((l) => l.length))} cells at row ${r0 + 1}`);
    }
  }

  /* A value as the page shows it: its value label (Column Info) when it has
     one, otherwise in the column's format. For display only; valueText()
     is the value itself, as it is typed, copied and stored. */
  function cellText(c, v) {
    if (!c) return String(v);
    if (c.valueLabels) { const lab = SM.table.labelOf(c, v); if (lab != null) return lab; }
    return valueText(c, v);
  }

  function valueText(c, v) {
    if (c.isNumeric) {
      const f = c.format;
      if (f && (f.kind === 'date' || f.kind === 'datetime')) return SM.io.formatDate(v, f.kind);
      if (f && f.kind === 'fixed' && f.digits != null) return fmt(v, { digits: f.digits });
      if (f && f.kind === 'percent') return `${fmt(100 * v, { sig: 6 })}%`;
      return fmt(v, { sig: 10 });
    }
    return String(v);
  }

  SM.grid = Object.freeze({ Grid, cellText, valueText, ROW_H });
}(typeof self !== 'undefined' ? self : this));
