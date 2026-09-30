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

   Column properties, as JMP's (each kept in Save Table, projects and Undo):

     missingCodes   [values]: stored values every analysis treats as
                    missing (999, "refused"). A column holds two views, as
                    JMP's Get Values and Get Stored Values: values, what the
                    analyses, formulas, graphs and the engine see (a code is
                    missing there), and coded, the stored code of each coded
                    cell (sparse and row-aligned; null when there is none),
                    which the grid shows and the files keep. storedOf(c, r)
                    gives the stored value of a cell.
     valueLabels    { value: label }: text shown for a value in the grid and
                    wherever the page writes a level (SM.grid.cellText); the
                    value is what is stored, compared and sent to the engine.
                    Keys are the values as text (String(1) for 1); labelOf(c, v)
                    looks one up.
     profitMatrix   { levels, decisions, matrix }: for a categorical
                    response, the profit of deciding decisions[j] when the
                    actual level is levels[i] is matrix[i][j]. decisions are
                    the levels, and "Undecided" after them when it is used
                    (decisions[levels.length]). profitAligned(t, c) gives it
                    for the column's levels now.
     preselectRole  'Y', 'X', 'Weight' or 'Freq' (JMP's Preselect Role): the
                    role a launch dialog puts the column in when it opens.
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

  /* A column's or a table's name on one line, wherever it comes from (a
     file, a paste, a rename): every line break and control character (C0
     and C1, tab and NEL among them, DEL, and U+2028 and U+2029) becomes one
     space, the spaces around it go into that one, and the ends are trimmed.
     A name then cannot end the comment of the Python code it is written in.
     Empty: '' (the caller has its fallback, Column 3 or Untitled). */
  const NAME_BREAKS = /[ ]*[\u0000-\u001f\u007f-\u009f\u2028\u2029]+[ ]*/g;
  function cleanName(s) {
    return String(s == null ? '' : s).replace(NAME_BREAKS, ' ').trim();
  }

  /* ---- column properties: their normal forms ------------------------------ */
  const hasOwn = (o, k) => Object.prototype.hasOwnProperty.call(o, k);
  const ROLES = ['Y', 'X', 'Weight', 'Freq'];
  const UNDECIDED = 'Undecided';

  // Missing Value Codes: numbers for a numeric column, texts for a character one.
  function normCodes(list, numeric) {
    if (list == null || list === '') return null;
    const out = [];
    for (const x of Array.isArray(list) ? list : [list]) {
      const v = numeric ? toNumber(x) : (x == null ? '' : String(x));
      if (numeric ? Number.isNaN(v) : v === '') continue;
      if (!out.includes(v)) out.push(v);
      if (out.length >= 1000) break;
    }
    return out.length ? out : null;
  }

  // Value Labels: an object without a prototype (a value named __proto__ is
  // an ordinary key), keys the values as text, labels text.
  function normLabels(obj, numeric) {
    if (!obj || typeof obj !== 'object') return null;
    const pairs = Array.isArray(obj) ? obj : Object.keys(obj).map((k) => [k, obj[k]]);
    const out = Object.create(null);
    let n = 0;
    for (const p of pairs) {
      if (!Array.isArray(p) || p.length < 2 || p[1] == null) continue;
      const label = String(p[1]);
      let key = p[0];
      if (numeric) { const x = toNumber(key); if (Number.isNaN(x)) continue; key = String(x); } else { key = key == null ? '' : String(key); if (key === '') continue; }
      if (label === '') continue;
      out[key] = label;
      if (++n >= 10000) break;
    }
    return n ? out : null;
  }

  // The label of a value, or null.
  function labelOf(c, v) {
    const L = c && c.valueLabels;
    if (!L || isMissing(v)) return null;
    // (a level that comes back from the engine as text, "1.0", is the number 1)
    const k = c.isNumeric && typeof v === 'string' ? String(toNumber(v)) : String(v);
    return hasOwn(L, k) && typeof L[k] === 'string' ? L[k] : null;
  }

  // Value Labels as [value, label] pairs, values typed as the column's.
  function labelPairs(c) {
    const L = c && c.valueLabels;
    if (!L) return [];
    return Object.keys(L).map((k) => [c.isNumeric ? toNumber(k) : k, L[k]]);
  }

  const copyLabels = (L) => (L ? normLabels(Object.keys(L).map((k) => [k, L[k]]), false) : null);

  // Profit Matrix: numbers everywhere (anything else is 0), the matrix the
  // size of the levels by the decisions.
  function normProfit(pm) {
    if (!pm || typeof pm !== 'object' || !Array.isArray(pm.levels) || !pm.levels.length) return null;
    const levels = pm.levels.slice(0, 500).map((v) => (typeof v === 'number' ? v : String(v)));
    const undecided = Array.isArray(pm.decisions) && pm.decisions.length > levels.length;
    const decisions = undecided ? levels.concat([UNDECIDED]) : levels.slice();
    const M = Array.isArray(pm.matrix) ? pm.matrix : [];
    const matrix = levels.map((_, i) => decisions.map((_, j) => { const x = Array.isArray(M[i]) ? Number(M[i][j]) : NaN; return Number.isFinite(x) ? x : 0; }));
    return { levels, decisions, matrix };
  }

  const copyProfit = (pm) => (pm ? { levels: pm.levels.slice(), decisions: pm.decisions.slice(), matrix: pm.matrix.map((r) => r.slice()) } : null);

  /* A profit matrix for these levels: 1 for a correct decision, −1 for a
     wrong one, 0 for Undecided; from a stored one where it has the level. */
  function profitFor(levels, stored = null, undecided = false) {
    const key = (v) => (typeof v === 'number' ? `n${v}` : `s${v}`);
    const at = new Map((stored ? stored.levels : []).map((v, i) => [key(v), i]));
    const und = stored && stored.decisions.length > stored.levels.length ? stored.levels.length : -1;
    const decisions = undecided ? levels.concat([UNDECIDED]) : levels.slice();
    const matrix = levels.map((a, i) => decisions.map((d, j) => {
      const ia = at.get(key(a));
      const jd = j < levels.length ? at.get(key(d)) : und;
      if (stored && ia != null && jd != null && jd >= 0 && Number.isFinite(stored.matrix[ia][jd])) return stored.matrix[ia][jd];
      return j >= levels.length ? 0 : i === j ? 1 : -1;
    }));
    return { levels: levels.slice(), decisions, matrix };
  }

  /* A column's Profit Matrix for its levels now (the stored one re-aligned:
     a level it lacks gets the defaults), or null when it has none. */
  function profitAligned(t, key) {
    const c = t.col(key);
    if (!c || !c.profitMatrix) return null;
    const pm = c.profitMatrix;
    return profitFor(t.levels(c), pm, pm.decisions.length > pm.levels.length);
  }

  const normRole = (r) => (ROLES.includes(r) ? r : null);

  /* ---- table scripts (JMP's): [{ name, platform, kind, spec, idNames }] ------
       kind 'launch'  spec by column names, the shape SM.launch.last keeps:
                      { roles: { key: [names] }, options, extra: { … } }
                      (a design's Model): running it opens the launch dialog
                      filled in
       kind 'report'  a report's own spec (column ids, as the report keeps
                      them in its roles, options and filters) and idNames,
                      { id: name } of the ids it uses: running it maps the ids
                      through the names to the table's columns now (as a
                      project does) and opens the report
     A table from a file is hostile input: normScripts keeps what it can
     trust and drops the rest. */
  // 'jsl': a script read from a JMP table (.jmp), its JSL text as JMP keeps it
  const SCRIPT_KINDS = ['launch', 'report', 'jsl'];
  const BAD_KEYS = new Set(['__proto__', 'constructor', 'prototype']);
  const MAX_SCRIPTS = 100, MAX_SCRIPT_JSON = 400000;

  // A plain copy through JSON, without the keys that reach an object's prototype.
  function plainCopy(v, depth = 0) {
    if (depth > 40) return undefined;
    if (v == null || typeof v === 'number' || typeof v === 'string' || typeof v === 'boolean') return typeof v === 'number' && !Number.isFinite(v) ? null : v;
    if (Array.isArray(v)) return v.map((x) => { const y = plainCopy(x, depth + 1); return y === undefined ? null : y; });
    if (typeof v !== 'object') return undefined;
    const out = {};
    for (const k of Object.keys(v)) {
      if (BAD_KEYS.has(k)) continue;
      const y = plainCopy(v[k], depth + 1);
      if (y !== undefined) out[k] = y;
    }
    return out;
  }

  function normScripts(list, platformOk = null) {
    if (!Array.isArray(list)) return [];
    const ok = platformOk || ((id) => (root.SM && root.SM.platforms ? !!root.SM.platforms.get(id) : /^[\w.-]{1,80}$/.test(id)));
    const out = [];
    for (const x of list) {
      if (out.length >= MAX_SCRIPTS) break;
      if (!x || typeof x !== 'object' || Array.isArray(x)) continue;
      const name = typeof x.name === 'string' ? cleanName(x.name).slice(0, 200).trim() : '';
      if (!name || out.some((y) => y.name === name)) continue;
      if (x.kind === 'jsl') {
        // JSL text only: it is never run as code, only read by the JSL converter
        if (typeof x.jsl === 'string' && x.jsl.trim() && x.jsl.length <= MAX_SCRIPT_JSON) out.push({ name, kind: 'jsl', jsl: x.jsl });
        continue;
      }
      if (typeof x.platform !== 'string' || !ok(x.platform)) continue;
      if (!x.spec || typeof x.spec !== 'object' || Array.isArray(x.spec)) continue;
      let text;
      try { text = JSON.stringify(x.spec); } catch (e) { continue; }
      if (!text || text.length > MAX_SCRIPT_JSON) continue;
      const spec = plainCopy(JSON.parse(text));
      if (!spec) continue;
      const kind = SCRIPT_KINDS.includes(x.kind) ? x.kind : 'launch';
      const script = { name, platform: x.platform, kind, spec };
      if (kind === 'report') {
        const idNames = {};
        if (x.idNames && typeof x.idNames === 'object') for (const k of Object.keys(x.idNames)) if (/^[\w-]{1,60}$/.test(k) && !BAD_KEYS.has(k) && typeof x.idNames[k] === 'string') idNames[k] = cleanName(x.idNames[k]);
        script.idNames = idNames;
      }
      out.push(script);
    }
    return out;
  }

  const copyScripts = (list) => (list || []).map((x) => JSON.parse(JSON.stringify(x)));

  /* A renamed column in the scripts: their names are structured (roles,
     Fit Model's effects), unlike JMP's JSL text. */
  function renameInScript(sc, oldName, newName) {
    if (sc.kind === 'jsl') return;      // JSL text, as JMP keeps it: JMP does not rewrite scripts either
    const swap = (arr) => (Array.isArray(arr) ? arr.map((v) => (v === oldName ? newName : v)) : arr);
    if (sc.kind === 'report') {
      for (const k of Object.keys(sc.idNames || {})) if (sc.idNames[k] === oldName) sc.idNames[k] = newName;
      const rn = sc.spec && sc.spec.roleNames;
      if (rn && typeof rn === 'object') for (const k of Object.keys(rn)) rn[k] = swap(rn[k]);
      return;
    }
    const sp = sc.spec || {};
    if (sp.roles && typeof sp.roles === 'object') for (const k of Object.keys(sp.roles)) sp.roles[k] = swap(sp.roles[k]);
    // the names a platform's own part keeps (Fit Model's effects: names, nestNames),
    // in extra or beside roles and options (the DOE platforms' { roles, options, effects })
    const walk = (v, depth) => {
      if (!v || typeof v !== 'object' || depth > 12) return;
      if (Array.isArray(v)) { v.forEach((x) => walk(x, depth + 1)); return; }
      for (const k of Object.keys(v)) {
        if (/names$/i.test(k) && Array.isArray(v[k])) v[k] = swap(v[k]);
        else walk(v[k], depth + 1);
      }
    };
    for (const k of Object.keys(sp)) if (k !== 'roles' && k !== 'options') walk(sp[k], 0);
  }

  // A cell's stored value: its missing value code, or its value.
  const storedOf = (c, r) => (c.coded && c.coded[r] !== undefined ? c.coded[r] : c.values[r]);

  class Column {
    constructor(spec) {
      this.id = spec.id || uid('c');
      this.name = cleanName(spec.name) || 'Column';
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
      const num = this.dataType === 'numeric';
      this.missingCodes = normCodes(spec.missingCodes, num);    // see the head of the file
      this.valueLabels = normLabels(spec.valueLabels, num);
      this.profitMatrix = normProfit(spec.profitMatrix);
      this.preselectRole = normRole(spec.preselectRole);
      this.coded = null;                          // the stored codes of the coded cells (the table fills it)
    }
    // the column's own properties, for the Columns panel and Column Info
    get properties() {
      return [this.missingCodes && 'Missing Value Codes', this.valueLabels && 'Value Labels', this.profitMatrix && 'Profit Matrix', this.specLimits && 'Spec Limits', this.valueOrder && 'Value Order', this.preselectRole && `Preselect Role ${this.preselectRole}`].filter(Boolean);
    }
    get isNumeric() { return this.dataType === 'numeric'; }
    get isCategorical() { return this.modelingType !== 'continuous'; }
  }

  class Table extends Emitter {
    constructor(spec = {}) {
      super();
      this.id = spec.id || uid('t');
      this.name = spec.name;           // (the setter below keeps it on one line)
      this.columns = [];
      this.nrows = 0;
      this.state = new Uint8Array(0);
      this.color = new Int16Array(0);
      this.marker = new Int8Array(0);
      this.version = 1;         // every change: the engine sends the table again
      this.dataVersion = 1;     // changes to what analyses already use; a new column is not one
      this.notes = spec.notes || '';
      this.source = spec.source || '';
      this.scripts = normScripts(spec.scripts);    // JMP's table scripts (see normScripts)
      const cols = spec.columns || [];
      const n = cols.length ? Math.max(...cols.map((c) => (c.values || []).length)) : (spec.nrows || 0);
      this._resizeStates(n);
      this.nrows = n;
      // names on one line (a name emptied by that is Column 3, by its place)
      // and each once, as addColumn keeps them: a second x is x 2
      cols.forEach((c, i) => {
        const col = new Column({ ...c, name: cleanName(c.name) || `Column ${i + 1}` });
        col.name = this.uniqueName(col.name);
        this._pushColumn(col);
      });
    }

    get name() { return this._name; }
    set name(v) { this._name = cleanName(v) || 'Untitled'; }

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
      this._splitCodes(c);
      if (at == null || at < 0 || at > this.columns.length) this.columns.push(c); else this.columns.splice(at, 0, c);
      return c;
    }

    /* ---- Missing Value Codes: the two views of a column ------------------ */
    // The cells holding a code: their values become missing and their
    // stored codes go to c.coded (what was coded before goes back first).
    _splitCodes(c) {
      this._mergeCodes(c);
      const codes = c.missingCodes;
      if (!codes || !codes.length) return;
      const set = new Set(codes);
      const miss = c.isNumeric ? NaN : null;
      let coded = null;
      for (let i = 0; i < c.values.length; i++) {
        const v = c.values[i];
        if (v != null && set.has(v)) { if (!coded) coded = new Array(c.values.length); coded[i] = v; c.values[i] = miss; }
      }
      c.coded = coded;
    }

    // The stored codes back into the values.
    _mergeCodes(c) {
      if (!c.coded) return;
      const n = Math.min(c.coded.length, c.values.length);
      for (let i = 0; i < n; i++) if (c.coded[i] !== undefined) c.values[i] = c.coded[i];
      c.coded = null;
    }

    /* A cell's stored value (its code, when it holds one) and a column's
       stored values: what the grid shows and the files keep. */
    stored(row, key) { const c = this.col(key); return c ? storedOf(c, row) : undefined; }
    storedValues(key) { const c = this.col(key); return c ? (c.coded ? c.values.map((v, i) => (c.coded[i] !== undefined ? c.coded[i] : v)) : c.values.slice()) : []; }

    /* ---- the properties ----------------------------------------------------
       Each emits 'schema' (Column Info, the panels); a change of the missing
       value codes changes values, so it is a 'data' change too. */
    setMissingCodes(key, codes) {
      const c = this.col(key);
      if (!c) return;
      this._mergeCodes(c);
      c.missingCodes = normCodes(codes, c.isNumeric);
      this._splitCodes(c);
      this._changed('data', { column: c.id, codes: true });
      this.emit('schema', { info: c.id });
    }

    setValueLabels(key, labels) {
      const c = this.col(key);
      if (!c) return;
      c.valueLabels = normLabels(labels, c.isNumeric);
      this._changed('schema', { info: c.id });
    }

    setProfitMatrix(key, pm) {
      const c = this.col(key);
      if (!c) return;
      c.profitMatrix = normProfit(pm);
      this._changed('schema', { info: c.id });
    }

    setPreselectRole(key, role) {
      const c = this.col(key);
      if (!c) return;
      c.preselectRole = normRole(role);
      this._changed('schema', { info: c.id });
    }

    addColumn(spec, at) {
      const c = this._pushColumn(new Column({ ...spec, name: this.uniqueName(cleanName(spec.name) || 'Column') }), at);
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
      const nm = cleanName(name);
      if (!c || !nm || nm === c.name) return;
      const was = c.name;
      c.name = this.uniqueName(nm);
      for (const sc of this.scripts || []) renameInScript(sc, was, c.name);
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
        // the stored codes change type with the values (999 and "999")
        this._mergeCodes(c);
        if (dataType === 'character') c.values = c.values.map((v) => (Number.isNaN(v) ? null : String(v)));
        else c.values = c.values.map(toNumber);
        c.dataType = dataType;
        c.valueOrder = null;
        if (dataType === 'character' && c.modelingType === 'continuous') c.modelingType = 'nominal';
        const num = dataType === 'numeric';
        c.missingCodes = normCodes(c.missingCodes, num);
        c.valueLabels = normLabels(labelPairs({ valueLabels: c.valueLabels, isNumeric: false }), num);
        if (c.profitMatrix) c.profitMatrix = null;       // its levels were the other type's
        this._splitCodes(c);
      }
      if (modelingType && MODELING.includes(modelingType)) {
        if (!(c.dataType === 'character' && modelingType === 'continuous')) c.modelingType = modelingType;
      }
      this._changed('schema', { retyped: c.id });
    }

    /* ---- cells ------------------------------------------------------------ */
    value(row, key) { const c = this.col(key); return c ? c.values[row] : undefined; }

    /* A cell's new stored value: a missing value code is kept as the code
       and is missing to the analyses. */
    setCell(row, key, value, { silent = false } = {}) {
      const c = this.col(key);
      if (!c || row < 0 || row >= this.nrows) return;
      let v = c.isNumeric ? toNumber(value) : (isMissing(value) ? null : String(value));
      if (c.coded) c.coded[row] = undefined;
      if (v != null && c.missingCodes && c.missingCodes.includes(v)) {
        if (!c.coded) c.coded = new Array(this.nrows);
        c.coded[row] = v;
        v = c.isNumeric ? NaN : null;
      }
      c.values[row] = v;
      if (!silent) this._changed('data', { cells: [[row, c.id]] });
    }

    setValues(key, values) {
      const c = this.col(key);
      if (!c) return;
      c.values = c.isNumeric ? Array.from(values, toNumber) : Array.from(values, (v) => (isMissing(v) ? null : String(v)));
      if (c.values.length !== this.nrows) c.values.length = this.nrows;
      c.coded = null;
      this._splitCodes(c);
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
      for (const c of this.columns) {
        c.values.splice(at, 0, ...new Array(count).fill(c.isNumeric ? NaN : null));
        if (c.coded) c.coded = [...c.coded.slice(0, at), ...new Array(count), ...c.coded.slice(at)];
      }
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
      for (const c of this.columns) {
        c.values = order.map((i) => c.values[i]);
        if (c.coded) { const k = order.map((i) => c.coded[i]); c.coded = k.some((v) => v !== undefined) ? k : null; }
      }
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
        columns: this.columns.map((c) => ({ id: c.id, name: c.name, dataType: c.dataType, modelingType: c.modelingType, format: c.format ? { ...c.format } : null, valueOrder: c.valueOrder ? c.valueOrder.slice() : null, formula: c.formula ? JSON.parse(JSON.stringify(c.formula)) : null, notes: c.notes, role: c.role, specLimits: c.specLimits ? { ...c.specLimits } : null,
          missingCodes: c.missingCodes ? c.missingCodes.slice() : null, valueLabels: copyLabels(c.valueLabels), profitMatrix: copyProfit(c.profitMatrix), preselectRole: c.preselectRole || null,
          values: c.values.slice(), coded: c.coded ? c.coded.slice() : null })),
        state: this.state.slice(), color: this.color.slice(), marker: this.marker.slice(),
        scripts: copyScripts(this.scripts),
      };
    }

    restore(s) {
      const byId = new Map(this.columns.map((c) => [c.id, c]));
      this.columns = s.columns.map((spec) => {
        // Keep the Column objects that still exist, so that references to them stay good.
        const c = byId.get(spec.id) || new Column(spec);
        Object.assign(c, { ...spec, values: spec.values.slice(), coded: spec.coded ? spec.coded.slice() : null, valueLabels: copyLabels(spec.valueLabels), profitMatrix: copyProfit(spec.profitMatrix), missingCodes: spec.missingCodes ? spec.missingCodes.slice() : null });
        return c;
      });
      this.nrows = s.nrows;
      this.name = s.name;
      if (s.scripts) this.scripts = copyScripts(s.scripts);
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
        columns: cols.map((c) => ({ ...c, id: undefined, values: rows.map((r) => storedOf(c, r)), valueOrder: c.valueOrder, preselectRole: c.preselectRole })),
      });
      for (let k = 0; k < rows.length; k++) { t.color[k] = this.color[rows[k]]; t.marker[k] = this.marker[rows[k]]; }
      return t;
    }

    toJSON() {
      return {
        format: 'smui-table', version: 1, name: this.name, notes: this.notes, source: this.source,
        columns: this.columns.map((c) => {
          const out = {
            name: c.name, dataType: c.dataType, modelingType: c.modelingType, format: c.format,
            valueOrder: c.valueOrder, formula: c.formula, notes: c.notes, role: c.role, specLimits: c.specLimits,
            // the stored values: a missing value code as the code
            values: c.isNumeric ? c.values.map((v, i) => { const s = c.coded && c.coded[i] !== undefined ? c.coded[i] : v; return Number.isNaN(s) ? null : s; }) : (c.coded ? c.values.map((v, i) => storedOf(c, i)) : c.values),
          };
          if (c.missingCodes) out.missingCodes = c.missingCodes.slice();
          if (c.valueLabels) out.valueLabels = Object.fromEntries(Object.keys(c.valueLabels).map((k) => [k, c.valueLabels[k]]));
          if (c.profitMatrix) out.profitMatrix = copyProfit(c.profitMatrix);
          if (c.preselectRole) out.preselectRole = c.preselectRole;
          return out;
        }),
        rowStates: Array.from(this.state), colors: Array.from(this.color), markers: Array.from(this.marker),
        ...(this.scripts && this.scripts.length ? { scripts: copyScripts(this.scripts) } : {}),
      };
    }

    /* The scripts changed (saved, renamed, deleted): the Table panel shows
       them; no analysis uses them, so no data event. */
    setScripts(list) {
      this.scripts = normScripts(list);
      this.version++;
      this.emit('schema', { scripts: true });
    }

    static fromJSON(j) {
      if (!j || j.format !== 'smui-table' || !Array.isArray(j.columns)) throw new Error('not a table saved by this page');
      const t = new Table({
        name: j.name, notes: j.notes, source: j.source, scripts: j.scripts,
        // (a file's columns get ids of this page: one from a file is not trusted, and none is saved)
        columns: j.columns.map((c) => ({ ...c, id: undefined, values: (c.values || []).map((v) => (v == null && c.dataType !== 'character' ? NaN : v)) })),
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

  /* ---- Missing Value Codes in the code a report shows ---------------------
     The code reads the table's CSV, which keeps a code as it is stored (999),
     as File > Export CSV writes it; the analyses took it for missing. So
     after the line that reads the CSV (and the lines that turn dates back
     into numbers) the code gets a line per coded column it uses:
       df["x"] = df["x"].mask(df["x"].isin([999]))   # 999 is a missing value code of x
     codedResult() does it to every snippet of an engine result, in place. */
  const PY_READ = /^df = pd\.read_csv\(/;
  const PY_DATE = /^df\[.*\] = \(pd\.to_datetime\(/;
  const pyNum = (v) => (Number.isFinite(v) ? String(v) : v > 0 ? 'float("inf")' : '-float("inf")');
  const pyLit = (v) => (typeof v === 'number' ? pyNum(v) : JSON.stringify(String(v)));
  const codeText = (c, v) => (typeof v === 'number' ? String(v) : JSON.stringify(v));

  // (a name in a comment: its line breaks would end the comment, and a name comes from a file)
  const inComment = (x) => String(x).replace(/[\r\n]+/g, ' ');

  function codedLine(c) {
    const q = JSON.stringify(c.name);
    const codes = c.missingCodes;
    const say = codes.map((v) => codeText(c, v)).join(', ');
    return `df[${q}] = df[${q}].mask(df[${q}].isin([${codes.map(pyLit).join(', ')}]))   # ${inComment(say)} ${codes.length > 1 ? 'are missing value codes' : 'is a missing value code'} of ${inComment(c.name)} (Column Info): missing here, as in the page`;
  }

  // a name as Python's json.dumps writes it (non-ASCII escaped), and as JSON.stringify does
  const asciiJson = (s) => JSON.stringify(s).replace(/[\u007f-￿]/g, (ch) => `\\u${ch.charCodeAt(0).toString(16).padStart(4, '0')}`);
  const nameForms = (name) => [...new Set([JSON.stringify(name), asciiJson(name)])];

  function codedCode(text, table) {
    if (typeof text !== 'string' || !table || !Array.isArray(table.columns) || !text.includes('pd.read_csv(')) return text;
    const need = table.columns.filter((c) => {
      if (!c.missingCodes || !c.missingCodes.length) return false;
      const forms = nameForms(c.name);
      if (!forms.some((f) => text.includes(f)) && !text.includes(`'${c.name}'`)) return false;
      return !forms.some((f) => text.includes(`df[${f}] = df[${f}].mask(`));
    });
    if (!need.length) return text;
    const lines = text.split('\n');
    const out = [];
    for (let i = 0; i < lines.length; i++) {
      out.push(lines[i]);
      if (!PY_READ.test(lines[i])) continue;
      while (i + 1 < lines.length && PY_DATE.test(lines[i + 1])) out.push(lines[++i]);
      for (const c of need) out.push(codedLine(c));
    }
    return out.join('\n');
  }

  function codedResult(obj, table, depth = 0) {
    if (!table || depth > 6 || !table.columns.some((c) => c.missingCodes)) return obj;
    if (Array.isArray(obj)) { for (let i = 0; i < obj.length; i++) { const v = obj[i]; if (typeof v === 'string') { if (v.includes('pd.read_csv(')) obj[i] = codedCode(v, table); } else if (v && typeof v === 'object') codedResult(v, table, depth + 1); } }
    else if (obj && typeof obj === 'object') { for (const k of Object.keys(obj)) { const v = obj[k]; if (typeof v === 'string') { if (v.includes('pd.read_csv(')) obj[k] = codedCode(v, table); } else if (v && typeof v === 'object') codedResult(v, table, depth + 1); } }
    return obj;
  }

  SM.Table = Table;
  SM.Column = Column;
  SM.table = Object.freeze({
    isMissing, toNumber, sortLevels, MODELING, STATE_BIT, collator,
    // column properties (see the head of the file)
    storedOf, labelOf, labelPairs, normCodes, normLabels, normProfit, profitFor, profitAligned, ROLES, UNDECIDED, codedCode, codedResult, cleanName,
    normScripts, SCRIPT_KINDS,
  });
}(typeof self !== 'undefined' ? self : this));
