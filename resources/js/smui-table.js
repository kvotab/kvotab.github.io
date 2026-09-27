/* ==========================================================================
   SMUI.HTML: THE DATA TABLE

   Columns hold one data type, numeric or character, and one modeling type,
   which decides what the analyses make of them:

     continuous   numbers on a scale: means, regressions, densities
     ordinal      ordered levels: ordered categories, ordinal models
     nominal      unordered levels: counts, contingency, dummy coding

   A numeric column may be any of the three; a character column is ordinal
   or nominal. Numeric values are numbers with NaN for missing; character
   values are strings with null for missing.

   Every row carries a row state, as in JMP:

     selected     highlighted in the grid and in every linked graph
     excluded     left out of every analysis (and drawn faded)
     hidden       left out of the graphs, still in the analyses
     labeled      its label column value is written beside its point
     color, marker   how its points are drawn

   The table emits 'data' when values change (and bumps .version, which is
   how the engine knows to send the table again), 'schema' when columns are
   added, removed, renamed or retyped, and 'rowstate' when a row state
   changes.
   ========================================================================== */
(function (root) {
  'use strict';
  const SM = root.SM || (root.SM = {});
  const { Emitter, uid } = SM.util;

  const SELECTED = 1, EXCLUDED = 2, HIDDEN = 4, LABELED = 8;
  const STATE_BIT = { selected: SELECTED, excluded: EXCLUDED, hidden: HIDDEN, labeled: LABELED };
  const MODELING = ['continuous', 'ordinal', 'nominal'];

  const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' });

  function isMissing(v) {
    return v == null || v === '' || (typeof v === 'number' && Number.isNaN(v));
  }

  class Column {
    constructor(spec) {
      this.id = spec.id || uid('c');
      this.name = String(spec.name || 'Column');
      this.dataType = spec.dataType === 'character' ? 'character' : 'numeric';
      this.modelingType = MODELING.includes(spec.modelingType) ? spec.modelingType
        : (this.dataType === 'numeric' ? 'continuous' : 'nominal');
      if (this.dataType === 'character' && this.modelingType === 'continuous') this.modelingType = 'nominal';
      this.values = Array.isArray(spec.values) ? spec.values : [];
      this.format = spec.format || null;          // { kind: 'best'|'fixed'|'date'|'datetime', digits }
      this.valueOrder = Array.isArray(spec.valueOrder) ? spec.valueOrder.slice() : null;
      this.formula = spec.formula || null;        // { expr }
      this.notes = spec.notes || '';
      this.role = spec.role || null;              // 'label' marks the label column
      this.specLimits = spec.specLimits || null;  // { lsl, target, usl }: JMP's Spec Limits property
    }
    get isNumeric() { return this.dataType === 'numeric'; }
    get isCategorical() { return this.modelingType !== 'continuous'; }
  }

  class Table extends Emitter {
    constructor(spec = {}) {
      super();
      this.id = spec.id || uid('t');
      this.name = spec.name || 'Untitled';
      this.columns = [];
      this.nrows = 0;
      this.state = new Uint8Array(0);
      this.color = new Int16Array(0);
      this.marker = new Int8Array(0);
      this.version = 1;         // every change: the engine sends the table again
      this.dataVersion = 1;     // changes to what analyses already use; a new column is not one
      this.notes = spec.notes || '';
      this.source = spec.source || '';
      const cols = spec.columns || [];
      const n = cols.length ? Math.max(...cols.map((c) => (c.values || []).length)) : (spec.nrows || 0);
      this._resizeStates(n);
      this.nrows = n;
      for (const c of cols) this._pushColumn(new Column(c));
    }

    /* ---- columns ------------------------------------------------------- */
    col(key) {
      if (key instanceof Column) return key;
      return this.columns.find((c) => c.id === key) || this.columns.find((c) => c.name === key) || null;
    }
    colIndex(key) { const c = this.col(key); return c ? this.columns.indexOf(c) : -1; }

    uniqueName(base) {
      const names = new Set(this.columns.map((c) => c.name));
      if (!names.has(base)) return base;
      for (let i = 2; ; i++) if (!names.has(`${base} ${i}`)) return `${base} ${i}`;
    }

    _pushColumn(c, at) {
      const fill = c.isNumeric ? NaN : null;
      while (c.values.length < this.nrows) c.values.push(fill);
      if (c.values.length > this.nrows) c.values.length = this.nrows;
      if (c.isNumeric) for (let i = 0; i < c.values.length; i++) { const v = c.values[i]; if (typeof v !== 'number') c.values[i] = toNumber(v); }
      else for (let i = 0; i < c.values.length; i++) { const v = c.values[i]; c.values[i] = isMissing(v) ? null : String(v); }
      if (at == null || at < 0 || at > this.columns.length) this.columns.push(c); else this.columns.splice(at, 0, c);
      return c;
    }

    addColumn(spec, at) {
      const c = this._pushColumn(new Column({ ...spec, name: this.uniqueName(spec.name || 'Column') }), at);
      this._changed('schema', { added: c.id });
      return c;
    }

    removeColumn(key) {
      const i = this.colIndex(key);
      if (i < 0) return;
      const [c] = this.columns.splice(i, 1);
      this._changed('schema', { removed: c.id });
    }

    renameColumn(key, name) {
      const c = this.col(key);
      if (!c || !name || name === c.name) return;
      c.name = this.uniqueName(String(name));
      this._changed('schema', { renamed: c.id });
    }

    moveColumn(key, to) {
      const i = this.colIndex(key);
      if (i < 0) return;
      const [c] = this.columns.splice(i, 1);
      this.columns.splice(Math.max(0, Math.min(to, this.columns.length)), 0, c);
      this._changed('schema', { moved: c.id });
    }

    /* Change a column's data type or modeling type. Numeric to character
       writes the numbers as text; character to numeric reads what parses
       and leaves the rest missing. */
    setType(key, { dataType, modelingType } = {}) {
      const c = this.col(key);
      if (!c) return;
      if (dataType && dataType !== c.dataType) {
        if (dataType === 'character') c.values = c.values.map((v) => (Number.isNaN(v) ? null : String(v)));
        else c.values = c.values.map(toNumber);
        c.dataType = dataType;
        c.valueOrder = null;
        if (dataType === 'character' && c.modelingType === 'continuous') c.modelingType = 'nominal';
      }
      if (modelingType && MODELING.includes(modelingType)) {
        if (!(c.dataType === 'character' && modelingType === 'continuous')) c.modelingType = modelingType;
      }
      this._changed('schema', { retyped: c.id });
    }

    /* ---- cells ------------------------------------------------------------ */
    value(row, key) { const c = this.col(key); return c ? c.values[row] : undefined; }

    setCell(row, key, value, { silent = false } = {}) {
      const c = this.col(key);
      if (!c || row < 0 || row >= this.nrows) return;
      c.values[row] = c.isNumeric ? toNumber(value) : (isMissing(value) ? null : String(value));
      if (!silent) this._changed('data', { cells: [[row, c.id]] });
    }

    setValues(key, values) {
      const c = this.col(key);
      if (!c) return;
      c.values = c.isNumeric ? Array.from(values, toNumber) : Array.from(values, (v) => (isMissing(v) ? null : String(v)));
      if (c.values.length !== this.nrows) c.values.length = this.nrows;
      this._changed('data', { column: c.id });
    }

    /* The distinct non-missing values in display order: the column's value
       order if it has one, else ascending numbers or natural text order. */
    levels(key) {
      const c = this.col(key);
      if (!c) return [];
      const seen = new Set();
      for (const v of c.values) if (!isMissing(v)) seen.add(v);
      let lv = Array.from(seen);
      if (c.valueOrder) {
        const order = c.valueOrder.filter((v) => seen.has(v));
        const rest = lv.filter((v) => !c.valueOrder.includes(v));
        lv = order.concat(sortLevels(rest, c.isNumeric));
      } else lv = sortLevels(lv, c.isNumeric);
      return lv;
    }

    /* ---- rows ------------------------------------------------------------- */
    _resizeStates(n) {
      const grow = (Arr, old, fill) => { const a = new Arr(n); a.set(old.subarray(0, Math.min(n, old.length))); if (fill) a.fill(fill, Math.min(n, old.length)); return a; };
      this.state = grow(Uint8Array, this.state, 0);
      this.color = grow(Int16Array, this.color, -1);
      this.marker = grow(Int8Array, this.marker, -1);
    }

    addRows(count = 1, at = this.nrows) {
      count = Math.max(0, count | 0);
      if (!count) return;
      at = Math.max(0, Math.min(at, this.nrows));
      for (const c of this.columns) c.values.splice(at, 0, ...new Array(count).fill(c.isNumeric ? NaN : null));
      const n = this.nrows + count;
      const move = (Arr, old, fill) => { const a = new Arr(n); a.set(old.subarray(0, at)); a.fill(fill, at, at + count); a.set(old.subarray(at), at + count); return a; };
      this.state = move(Uint8Array, this.state, 0);
      this.color = move(Int16Array, this.color, -1);
      this.marker = move(Int8Array, this.marker, -1);
      this.nrows = n;
      this._changed('data', { rowsAdded: [at, count] });
    }

    deleteRows(rows) {
      const drop = new Uint8Array(this.nrows);
      for (const r of rows) if (r >= 0 && r < this.nrows) drop[r] = 1;
      const keep = [];
      for (let i = 0; i < this.nrows; i++) if (!drop[i]) keep.push(i);
      this._reorder(keep);
      this._changed('data', { rowsDeleted: rows.length });
    }

    /* Rows in a new order (a permutation, or a subset): values and row
       states travel together. */
    _reorder(order) {
      for (const c of this.columns) c.values = order.map((i) => c.values[i]);
      const pick = (Arr, old) => { const a = new Arr(order.length); for (let k = 0; k < order.length; k++) a[k] = old[order[k]]; return a; };
      this.state = pick(Uint8Array, this.state);
      this.color = pick(Int16Array, this.color);
      this.marker = pick(Int8Array, this.marker);
      this.nrows = order.length;
    }

    /* Sort by one or more columns: [{ col, desc }]. Missing values last. */
    sortBy(keys) {
      const cols = keys.map((k) => ({ c: this.col(k.col), desc: !!k.desc })).filter((k) => k.c);
      if (!cols.length) return;
      const rank = cols.map(({ c }) => {
        if (c.isNumeric && !c.isCategorical) return null;
        const lv = this.levels(c);
        const m = new Map(lv.map((v, i) => [v, i]));
        return m;
      });
      const order = Array.from({ length: this.nrows }, (_, i) => i);
      order.sort((a, b) => {
        for (let k = 0; k < cols.length; k++) {
          const { c, desc } = cols[k];
          let x = c.values[a], y = c.values[b];
          const mx = isMissing(x), my = isMissing(y);
          if (mx || my) { if (mx && my) continue; return mx ? 1 : -1; }
          if (rank[k]) { x = rank[k].get(x); y = rank[k].get(y); }
          const d = typeof x === 'number' && typeof y === 'number' ? x - y : collator.compare(String(x), String(y));
          if (d) return desc ? -d : d;
        }
        return a - b;
      });
      this._reorder(order);
      this._changed('data', { sorted: true });
    }

    /* ---- row states ------------------------------------------------------ */
    has(row, flag) { return (this.state[row] & STATE_BIT[flag]) !== 0; }

    setState(rows, flag, on, { exclusive = false } = {}) {
      const bit = STATE_BIT[flag];
      if (exclusive) for (let i = 0; i < this.nrows; i++) this.state[i] &= ~bit;
      for (const r of rows) if (r >= 0 && r < this.nrows) { if (on) this.state[r] |= bit; else this.state[r] &= ~bit; }
      this.emit('rowstate', { kind: flag });
    }

    toggleState(rows, flag) {
      const bit = STATE_BIT[flag];
      for (const r of rows) if (r >= 0 && r < this.nrows) this.state[r] ^= bit;
      this.emit('rowstate', { kind: flag });
    }

    /* Select rows: mode 'replace' (default), 'add', 'toggle' or 'remove'. */
    select(rows, mode = 'replace') {
      if (mode === 'replace') this.setState(rows, 'selected', true, { exclusive: true });
      else if (mode === 'add') this.setState(rows, 'selected', true);
      else if (mode === 'remove') this.setState(rows, 'selected', false);
      else this.toggleState(rows, 'selected');
    }

    rowsWith(flag, on = true) {
      const bit = STATE_BIT[flag];
      const out = [];
      for (let i = 0; i < this.nrows; i++) if (((this.state[i] & bit) !== 0) === on) out.push(i);
      return out;
    }

    selectedRows() { return this.rowsWith('selected'); }

    /* The rows an analysis uses: not excluded. */
    includedRows() { return this.rowsWith('excluded', false); }

    counts() {
      let s = 0, e = 0, h = 0, l = 0;
      for (let i = 0; i < this.nrows; i++) {
        const v = this.state[i];
        if (v & SELECTED) s++;
        if (v & EXCLUDED) e++;
        if (v & HIDDEN) h++;
        if (v & LABELED) l++;
      }
      return { all: this.nrows, selected: s, excluded: e, hidden: h, labeled: l };
    }

    setColor(rows, color) { for (const r of rows) this.color[r] = color; this.emit('rowstate', { kind: 'color' }); }
    setMarker(rows, marker) { for (const r of rows) this.marker[r] = marker; this.emit('rowstate', { kind: 'marker' }); }

    clearRowStates() {
      this.state.fill(0);
      this.color.fill(-1);
      this.marker.fill(-1);
      this.emit('rowstate', { kind: 'all' });
    }

    labelColumn() { return this.columns.find((c) => c.role === 'label') || null; }

    /* ---- undo: a copy of everything, and putting it back ----------------- */
    snapshot() {
      return {
        nrows: this.nrows, name: this.name,
        columns: this.columns.map((c) => ({ id: c.id, name: c.name, dataType: c.dataType, modelingType: c.modelingType, format: c.format ? { ...c.format } : null, valueOrder: c.valueOrder ? c.valueOrder.slice() : null, formula: c.formula ? JSON.parse(JSON.stringify(c.formula)) : null, notes: c.notes, role: c.role, specLimits: c.specLimits ? { ...c.specLimits } : null, values: c.values.slice() })),
        state: this.state.slice(), color: this.color.slice(), marker: this.marker.slice(),
      };
    }

    restore(s) {
      const byId = new Map(this.columns.map((c) => [c.id, c]));
      this.columns = s.columns.map((spec) => {
        // Keep the Column objects that still exist, so that references to them stay good.
        const c = byId.get(spec.id) || new Column(spec);
        Object.assign(c, { ...spec, values: spec.values.slice() });
        return c;
      });
      this.nrows = s.nrows;
      this.name = s.name;
      this.state = s.state.slice();
      this.color = s.color.slice();
      this.marker = s.marker.slice();
      this._changed('schema', { restored: true });
      this.emit('rowstate', { kind: 'all' });
    }

    /* ---- copies, subsets, serialisation --------------------------------- */
    subset(rows, colKeys, name) {
      const cols = (colKeys ? colKeys.map((k) => this.col(k)).filter(Boolean) : this.columns);
      const t = new Table({
        name: name || `${this.name} subset`,
        columns: cols.map((c) => ({ ...c, id: undefined, values: rows.map((r) => c.values[r]), valueOrder: c.valueOrder })),
      });
      for (let k = 0; k < rows.length; k++) { t.color[k] = this.color[rows[k]]; t.marker[k] = this.marker[rows[k]]; }
      return t;
    }

    toJSON() {
      return {
        format: 'smui-table', version: 1, name: this.name, notes: this.notes, source: this.source,
        columns: this.columns.map((c) => ({
          name: c.name, dataType: c.dataType, modelingType: c.modelingType, format: c.format,
          valueOrder: c.valueOrder, formula: c.formula, notes: c.notes, role: c.role, specLimits: c.specLimits,
          values: c.isNumeric ? c.values.map((v) => (Number.isNaN(v) ? null : v)) : c.values,
        })),
        rowStates: Array.from(this.state), colors: Array.from(this.color), markers: Array.from(this.marker),
      };
    }

    static fromJSON(j) {
      if (!j || j.format !== 'smui-table' || !Array.isArray(j.columns)) throw new Error('not a table saved by this page');
      const t = new Table({
        name: j.name, notes: j.notes, source: j.source,
        columns: j.columns.map((c) => ({ ...c, values: (c.values || []).map((v) => (v == null && c.dataType !== 'character' ? NaN : v)) })),
      });
      const copy = (dst, src) => { if (Array.isArray(src)) for (let i = 0; i < Math.min(dst.length, src.length); i++) dst[i] = src[i]; };
      copy(t.state, j.rowStates); copy(t.color, j.colors); copy(t.marker, j.markers);
      return t;
    }

    _changed(kind, detail) {
      this.version++;
      // Saving a column (residuals, a formula) leaves every earlier result
      // valid, so caches keyed by dataVersion survive it.
      if (!(detail && detail.added)) this.dataVersion++;
      this.emit(kind, detail);
      if (kind !== 'data') this.emit('data', { schema: true, ...detail });
    }
  }

  function toNumber(v) {
    if (typeof v === 'number') return v;
    if (v == null) return NaN;
    const s = String(v).trim();
    if (s === '' || s === '.' || /^(na|nan|null|missing)$/i.test(s)) return NaN;
    if (/^[-+]?inf(inity)?$/i.test(s)) return s.startsWith('-') ? -Infinity : Infinity;
    const x = Number(s.replace(/−/g, '-'));
    return Number.isNaN(x) ? NaN : x;
  }

  function sortLevels(lv, numeric) {
    return numeric ? lv.slice().sort((a, b) => a - b) : lv.slice().sort((a, b) => collator.compare(String(a), String(b)));
  }

  SM.Table = Table;
  SM.Column = Column;
  SM.table = Object.freeze({ isMissing, toNumber, sortLevels, MODELING, STATE_BIT, collator });
}(typeof self !== 'undefined' ? self : this));
