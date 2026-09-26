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
   at the cursor. Right click a header or a row number for their menus.
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM || (root.SM = {});
  const { el, svg, typeIcon, fmt } = SM.util;
  const { isMissing } = SM.table;

  const ROW_H = 22;
  const HEAD_H = 26;
  const RHEAD_W = 74;

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
      this.bar.append(
        el('button', { type: 'button', class: 'sm-btn small', text: '+ Row', onclick: () => this._addRow() }),
        el('button', { type: 'button', class: 'sm-btn small', text: '+ Column', onclick: () => app.newColumn() }),
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
          table.on('data', () => { this._layout(); this._schedule(); }),
          table.on('rowstate', () => this._schedule()),
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

    _layout() {
      const t = this.table;
      this.head.replaceChildren();
      if (!t) { this.inner.style.width = '0px'; this.inner.style.height = '0px'; return; }
      const corner = el('div', { class: 'sm-grid-corner', style: { width: `${RHEAD_W}px` }, title: null });
      corner.addEventListener('click', () => { t.select(t.nrows ? Array.from({ length: t.nrows }, (_, i) => i) : []); });
      this.head.append(corner);
      let total = RHEAD_W;
      t.columns.forEach((c, j) => {
        const w = this.width(c);
        total += w;
        const flags = [c.formula ? 'ƒ' : '', c.role === 'label' ? 'label' : ''].filter(Boolean).join(' ');
        const h = el('div', { class: `sm-hcell${this.colSel.has(c.id) ? ' is-selected' : ''}`, style: { width: `${w}px` }, dataset: { col: String(j) }, role: 'columnheader' },
          typeIcon(c.modelingType), el('span', { class: 'sm-hname', text: c.name }), flags ? el('span', { class: 'sm-hflag', text: flags }) : null,
          el('span', { class: 'sm-resizer', dataset: { resize: String(j) } }));
        h.setAttribute('aria-label', `${c.name}, ${SM.util.TYPE_LABEL[c.modelingType]}`);
        this.head.append(h);
      });
      this.inner.style.width = `${total}px`;
      this.inner.style.height = `${HEAD_H + t.nrows * ROW_H}px`;
      this.head.style.width = `${total}px`;
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
          const miss = isMissing(v);
          const cell = el('div', { class: `sm-cell${c.isNumeric ? ' num' : ''}${miss ? ' miss' : ''}${this.colSel.has(c.id) ? ' is-colsel' : ''}${this.cursor.row === i && this.cursor.col === j ? ' is-cursor' : ''}`, style: { width: `${widths[j]}px` }, dataset: { c: String(j) }, role: 'gridcell' });
          cell.textContent = miss ? (c.isNumeric ? '•' : '') : cellText(c, v);
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
      const v = c.values[this.cursor.row];
      this.cellRef.textContent = `row ${this.cursor.row + 1}, ${c.name}: ${isMissing(v) ? '(missing)' : cellText(c, v)}`;
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
        SM.ui.menu(this.app.rowMenu(), { x: ev.clientX, y: ev.clientY });
      }
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
      const v = c.values[row];
      input.value = initial != null ? initial : (isMissing(v) ? '' : cellText(c, v));
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
      Object.assign(e.input.style, { left: `${x}px`, top: `${HEAD_H + e.row * ROW_H}px`, width: `${this.width(t.columns[e.col])}px`, height: `${ROW_H}px` });
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
      const old = c.values[e.row];
      const same = c.isNumeric ? (Number.isNaN(old) && Number.isNaN(v)) || old === v : (old ?? '') === (v ?? '');
      if (same) { this._render(); return; }
      this.app.recordCells(t, 'Edit Cell', [[e.row, c.id]]);
      t.setCell(e.row, c.id, v);
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
      const y = HEAD_H + this.cursor.row * ROW_H;
      if (y < s.scrollTop + HEAD_H) s.scrollTop = y - HEAD_H;
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
        if (c && !c.formula) { this.app.recordCells(t, 'Clear Cell', [[this.cursor.row, c.id]]); t.setCell(this.cursor.row, c.id, c.isNumeric ? NaN : null); }
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
      for (const r of list) lines.push(cols.map((c) => { const v = c.values[r]; return isMissing(v) ? '' : cellText(c, v); }).join('\t'));
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
        this.app.recordCells(t, 'Paste', cells);
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
      t.version++;
      t.emit('data', { pasted: true });
      SM.ui.toast(`Pasted ${lines.length} × ${Math.max(...lines.map((l) => l.length))} cells at row ${r0 + 1}`);
    }
  }

  function cellText(c, v) {
    if (c.isNumeric) {
      const f = c.format;
      if (f && (f.kind === 'date' || f.kind === 'datetime')) return SM.io.formatDate(v, f.kind);
      if (f && f.kind === 'fixed' && f.digits != null) return fmt(v, { digits: f.digits });
      if (f && f.kind === 'percent') return `${fmt(100 * v, { sig: 6 })}%`;
      return fmt(v, { sig: 10 });
    }
    return String(v);
  }

  SM.grid = Object.freeze({ Grid, cellText, ROW_H });
}(typeof self !== 'undefined' ? self : this));
