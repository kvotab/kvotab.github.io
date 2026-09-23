/* ==========================================================================
   RTM.HTML: OPENING SKBRTM AND BRUM DATABASES

   skbrtm (and BRUM before it) keeps a model in semicolon-separated database
   files -- reaction.in, solutions.in, diffusion.in, sourceterm*.in, and the
   REGRESSION data of doserate*.in -- and the time span in the Python script
   that runs them. This turns a set of those files into one model text.

   It reads them the way skbrtm's own Parser does: the same blocks, the same
   attribute lines, a SOLUTION setting every species in its cells, a species
   the DIFFUSION block does not list diffusing at 1e-9 m2/s. Where skbrtm's
   reading differs from what the text means, the model follows the text and
   says so at the top:

     * a rate law's arguments are pasted into its text by skbrtm, so
       (kr/kh) with kh = 1.3*10**-3 is read as .../1.3*10**-3 -- every law
       is read both ways here and any that differ are named;
     * skbrtm holds the first CELL at a Dirichlet boundary, here the FACE is
       held -- the boundary is where the column starts;
     * a REGRESSION is a fit to a table; here the table itself is used,
       interpolated, since a fit started badly is what skbrtm's beta and
       gamma dose rates came out as.

   ONE GLOBAL: RtmImport. Runs in a page and in Node; needs FacsimileModel
   for the expression parser.
   ========================================================================== */
(function (root, factory) {
  const fac = root.FacsimileModel
    || (typeof require === 'function' ? require('./facsimile-model.js') : null);
  const api = factory(fac);
  root.RtmImport = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
}(typeof self !== 'undefined' ? self : this, function (FacsimileModel) {
  'use strict';

  /* ======================================================================
     skbrtm's database reader, with the spelling of every name kept
     ====================================================================== */
  const KEYS = ['diffusion', 'solution', 'reaction', 'regression', 'sourceterm'];
  const ATTRS = {
    reaction: ['species', 'expression', 'arguments', 'stoichiometry', 'parameters', 'initialize', 'source', 'cells'],
    sourceterm: ['species', 'expression', 'arguments', 'parameters', 'initialize', 'cells', 'source'],
    solution: ['species', 'concentration', 'constant', 'cell_id', 'units', 'parameters', 'source'],
    diffusion: ['species', 'diffusion_coefficient', 'cells', 'grid_type', 'min_length', 'max_length',
      'boundary_conditions', 'boundary_values', 'parameters', 'source'],
    regression: ['predictor', 'response', 'initial_guess', 'bounds', 'function', 'plot', 'plot_format',
      'plot_save', 'maxfev', 'name_predictor', 'name_response', 'parameters', 'source'],
  };

  /** True when a text is one of skbrtm's databases rather than a model text. */
  function isDatabase(text) {
    return /^\s*(REACTION|SOLUTION|DIFFUSION|SOURCETERM|REGRESSION)\s*;/im.test(String(text));
  }

  /** skbrtm.parser.Parser.reader, line for line, without the lower-casing. */
  function readBlocks(file, text) {
    const blocks = [];
    const dropped = [];
    let cur = null;
    let indices = [];
    let seen = {};
    for (const raw of String(text).split(/\r?\n/)) {
      let line = raw.trim();
      if (line.includes('#')) line = line.split('#')[0].trim();
      if (!line) continue;
      const low = line.toLowerCase();
      const parts = line.split(';').map((x) => x.trim());
      if (KEYS.some((k) => low.startsWith(k))) {
        cur = { kind: parts[0].toLowerCase(), name: parts[1] || '', values: {}, file };
        blocks.push(cur);
        seen = {};
        continue;
      }
      if (!cur) continue;
      const attrs = ATTRS[cur.kind];
      if (!attrs) continue;
      if (attrs.some((a) => low.startsWith(a))) {
        indices = parts.filter((x) => attrs.includes(x.toLowerCase())).map((x) => attrs.indexOf(x.toLowerCase()));
        // "units: mol/L", with a colon for the separator, names no attribute:
        // skbrtm reads nothing from it, and so does this, but it is said.
        if (!indices.length) dropped.push(`${file}: "${raw.trim()}"`);
      }
      const value = parts.filter((x) => !attrs.includes(x.toLowerCase()));
      if (!value.length) continue;
      indices.forEach((ai, k) => {
        if (k >= value.length) return;
        const a = attrs[ai];
        if (!(a in seen)) { cur.values[a] = value[k]; seen[a] = true; } else {
          const v = cur.values[a];
          cur.values[a] = (Array.isArray(v) ? v : [v]).concat([value[k]]);
        }
      });
    }
    return { blocks, dropped };
  }

  const list = (v) => (v === undefined || v === null ? [] : (Array.isArray(v) ? v : [v]));

  /** A decimal comma is a point, as skbrtm's preprocess_value makes it. */
  const decimal = (s) => String(s).replace(/(^|[^\[(\d])(-?\d+),(\d+)(?![\])])/g, '$1$2.$3');

  /** A Python literal: numbers, strings, None/True/False, tuples, lists, dicts. */
  function pyLiteral(src) {
    const s = decimal(String(src).trim());
    let i = 0;
    const ws = () => { while (i < s.length && /\s/.test(s[i])) i++; };
    const fail = () => { throw new Error(`"${src}" is not a Python literal`); };
    function value() {
      ws();
      const c = s[i];
      if (c === '(' || c === '[') {
        const close = c === '(' ? ')' : ']';
        i++;
        const out = [];
        for (;;) {
          ws();
          if (s[i] === close) { i++; return out; }
          out.push(value());
          ws();
          if (s[i] === ',') { i++; continue; }
          if (s[i] === close) { i++; return out; }
          fail();
        }
      }
      if (c === '{') {
        i++;
        const out = {};
        for (;;) {
          ws();
          if (s[i] === '}') { i++; return out; }
          const k = value();
          ws();
          if (s[i] !== ':') fail();
          i++;
          out[k] = value();
          ws();
          if (s[i] === ',') { i++; continue; }
          if (s[i] === '}') { i++; return out; }
          fail();
        }
      }
      if (c === "'" || c === '"') {
        i++;
        let out = '';
        while (i < s.length && s[i] !== c) { if (s[i] === '\\') i++; out += s[i++]; }
        i++;
        return out;
      }
      const m = /^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?/.exec(s.slice(i));
      if (m) { i += m[0].length; return Number(m[0]); }
      const w = /^(None|True|False)\b/i.exec(s.slice(i));
      if (w) { i += w[0].length; return { none: null, true: true, false: false }[w[0].toLowerCase()]; }
      return fail();
    }
    const v = value();
    ws();
    if (i !== s.length) fail();
    return v;
  }

  /** A value that may be a literal, or text when it is not one. */
  const maybe = (v, fallback) => {
    if (v === undefined) return fallback;
    try { return pyLiteral(v); } catch (e) { return String(v).trim(); }
  };

  /* ======================================================================
     The script: which files, in which order, and the time span
     ====================================================================== */
  const SECONDS = { seconds: 1, minutes: 60, hours: 3600, days: 86400, years: 365.25 * 86400 };

  function readScript(text) {
    const src = String(text);
    const vars = {};
    for (const m of src.matchAll(/^\s*(\w+)\s*=\s*\w+\s*\+\s*['"]([^'"]+\.in)['"]/gm)) vars[m[1]] = m[2];
    let order = null;
    const pm = /^\s*paths\s*=\s*\[([^\]]*)\]/m.exec(src);
    if (pm) order = pm[1].split(',').map((v) => v.trim()).filter(Boolean).map((v) => vars[v]).filter(Boolean);
    // The Solver(...) call, brackets balanced, and what it is given.
    const at = src.search(/\bSolver\s*\(/);
    let call = '';
    if (at >= 0) {
      let depth = 0;
      for (let i = src.indexOf('(', at); i < src.length; i++) {
        if (src[i] === '(') depth++;
        else if (src[i] === ')' && --depth === 0) { call = src.slice(src.indexOf('(', at) + 1, i); break; }
      }
    }
    const out = { order, tend: null, unit: null, rtol: null, atol: null, method: null, tEval: null };
    const ts = /t_span\s*=\s*(\([^)]*\))/.exec(call);
    if (ts) {
      try {
        const [a, b, unit] = pyLiteral(ts[1]);
        if (SECONDS[unit] && Number.isFinite(a) && Number.isFinite(b)) {
          out.tend = (b - a) * SECONDS[unit];
          out.unit = unit;
          out.span = [a, b];
        }
      } catch (e) { /* left unset: said below */ }
    }
    for (const key of ['rtol', 'atol']) {
      const m = new RegExp(`\\b${key}\\s*=\\s*([0-9.eE+-]+)`).exec(call);
      if (m) out[key] = Number(m[1]);
    }
    const me = /\bmethod\s*=\s*['"](\w+)['"]/.exec(call);
    if (me) out.method = me[1];
    const te = /t_eval\s*=\s*\(\s*\[([^\]]*)\]\s*,\s*['"](\w+)['"]\s*\)/.exec(call);
    if (te && SECONDS[te[2]]) out.tEval = te[1].split(',').map(Number).filter(Number.isFinite).map((v) => v * SECONDS[te[2]]);
    return out;
  }

  /* ======================================================================
     Names, laws and the way skbrtm reads them
     ====================================================================== */
  const NAME_OK = /^[A-Za-z](?:[A-Za-z0-9_]|\([A-Za-z0-9_]+\))*(?:[+-][0-9]*)?$/;
  const TERM = /^\s*((?:\d*\.\d+|\d+\.?\d*)?)\s*(.*?)\s*$/;

  function splitTop(text, sep = ',') {
    const out = [];
    let depth = 0;
    let start = 0;
    for (let i = 0; i < text.length; i++) {
      const c = text[i];
      if (c === '(' || c === '[' || c === '{') depth++;
      else if (c === ')' || c === ']' || c === '}') depth--;
      else if (c === sep && depth === 0) { out.push(text.slice(start, i)); start = i + 1; }
    }
    out.push(text.slice(start));
    return out;
  }

  /** The two sides of a stoichiometry, as skbrtm splits them. */
  function sides(st) {
    if (st.includes('=>')) return st.split('=>');
    if (st.includes('<=')) { const [l, r] = st.split('<='); return [r, l]; }
    return st.split('=');
  }

  const terms = (side) => side.trim().split(' + ').map((t) => TERM.exec(t)).filter((m) => m && m[2]);

  /** Ten significant figures at most, and 1e-6 rather than 0.000001. */
  function fmt(x) {
    if (x === 0) return '0';
    const a = Math.abs(x);
    if (a < 1e-3 || a >= 1e6) {
      const [m, e] = x.toExponential(9).split('e');
      return `${Number(m)}e${Number(e)}`;
    }
    return String(Number(x.toPrecision(10)));
  }

  /** Evaluate an expression the shared parser can read, or null. */
  function evalText(text, lookup) {
    try {
      return FacsimileModel.evalAst(FacsimileModel.parseExpression(text, 0), lookup, {}, 0);
    } catch (e) {
      return null;
    }
  }

  /* ======================================================================
     The conversion
     ====================================================================== */
  /**
   * @param {{name: string, text: string}[]} files  databases, and the script if there is one
   * @returns {{text: string, notes: string[], warnings: string[]}}
   */
  function convert(files) {
    const notes = [];
    const warnings = [];
    const scripts = files.filter((f) => /\.py$/i.test(f.name));
    let dbs = files.filter((f) => !/\.py$/i.test(f.name) && isDatabase(f.text));
    const script = scripts.length ? readScript(scripts[0].text) : null;
    if (scripts.length > 1) warnings.push(`Only the first script, ${scripts[0].name}, was read.`);
    if (script && script.order && script.order.length) {
      const byName = new Map(dbs.map((f) => [f.name.replace(/^.*[\\/]/, ''), f]));
      const missing = script.order.filter((n) => !byName.has(n));
      const unused = dbs.filter((f) => !script.order.includes(f.name.replace(/^.*[\\/]/, ''))).map((f) => f.name);
      if (missing.length) warnings.push(`${scripts[0].name} reads ${missing.join(', ')}, which ${missing.length > 1 ? 'were' : 'was'} not opened.`);
      if (unused.length) notes.push(`Not read, because ${scripts[0].name} does not: ${unused.join(', ')}.`);
      dbs = script.order.filter((n) => byName.has(n)).map((n) => byName.get(n));
    }
    if (!dbs.length) throw new Error('None of these is an skbrtm database: no REACTION, SOLUTION, DIFFUSION, SOURCETERM or REGRESSION block.');

    const blocks = [];
    for (const f of dbs) {
      const r = readBlocks(f.name.replace(/^.*[\\/]/, ''), f.text);
      blocks.push(...r.blocks);
      for (const d of r.dropped) warnings.push(`skbrtm reads nothing from ${d}: a colon where the separator is a semicolon.`);
    }
    const of = (kind) => blocks.filter((b) => b.kind === kind);

    // ---- every species, identified as skbrtm does -- in lower case -- and
    //      spelt as it was first written ----
    const spell = new Map();
    const meet = (name) => {
      const key = String(name).trim().toLowerCase();
      if (key && !spell.has(key)) spell.set(key, String(name).trim());
      return key;
    };
    const rxRows = [];
    for (const b of of('reaction')) {
      const st = list(b.values.stoichiometry);
      const ex = list(b.values.expression);
      const ar = list(b.values.arguments);
      st.forEach((s, k) => {
        rxRows.push({ st: s, ex: ex[k] || '', ar: ar[k] || '', file: b.file });
        for (const side of sides(s)) for (const m of terms(side)) meet(m[2]);
      });
    }
    const srcRows = [];
    for (const b of of('sourceterm')) {
      const sp = list(b.values.species);
      const ex = list(b.values.expression);
      const ar = list(b.values.arguments);
      sp.forEach((s, k) => { meet(s); srcRows.push({ sp: s, ex: ex[k] || '', ar: ar[k] || '', file: b.file }); });
    }
    for (const b of [...of('solution'), ...of('diffusion')]) for (const s of list(b.values.species)) meet(s);
    const order = [...spell.keys()].sort();
    // rtm.html's names: the spelling, unless it is not one of its names.
    const names = new Map();
    for (const key of order) {
      let n = spell.get(key);
      if (!NAME_OK.test(n)) {
        const fixed = `S_${n.replace(/[^A-Za-z0-9_()+-]/g, '_')}`.replace(/^S_(?=[A-Za-z])/, '');
        notes.push(`${n} is written ${fixed}: rtm.html names take letters, digits, _, groups in round brackets and a charge.`);
        n = fixed;
      }
      names.set(key, n);
    }
    const nameOf = (raw) => names.get(String(raw).trim().toLowerCase()) || String(raw).trim();

    // ---- the global parameters: skbrtm merges every block's dict, in order ----
    const params = new Map();
    for (const b of blocks) {
      const d = maybe(b.values.parameters, {});
      if (d && typeof d === 'object' && !Array.isArray(d)) for (const [k, v] of Object.entries(d)) params.set(String(k), v);
    }
    const paramOf = (id) => {
      for (const [k, v] of params) if (k.toLowerCase() === id.toLowerCase()) return [k, v];
      return null;
    };

    // ---- the column ----
    const diff = of('diffusion');
    if (diff.length > 1) warnings.push(`There are ${diff.length} DIFFUSION blocks; skbrtm keeps the largest cell count across them. Only the first was read.`);
    const transport = diff.length > 0;
    const settings = [];
    let cells = 1;
    let lo = 0;
    let bcs = ['neumann', 'neumann'];
    const D = new Map();
    const faceValue = { left: new Map(), right: new Map() };
    if (transport) {
      const v = diff[0].values;
      cells = Math.round(Number(maybe(v.cells, 10)));
      const gridType = String(maybe(v.grid_type, 'linear')).toLowerCase();
      lo = Number(maybe(v.min_length, 0));
      const hi = Number(maybe(v.max_length, 0.1));
      bcs = list(maybe(v.boundary_conditions, ['dirichlet', 'neumann'])).map((x) => String(x).toLowerCase());
      settings.push('MODE = transport', `CELLS = ${cells}`, `LENGTH = ${fmt(hi - lo)}`);
      if (gridType === 'powerlaw') {
        settings.push('GRID = powerlaw', 'GRID_POWER = 3');
        notes.push('skbrtm\'s power-law grid puts its edges at L*(i/N)^3 and its cell faces midway between the '
          + 'centres; here the faces ARE L*(i/N)^3, which is the same layout made consistent.');
      } else if (gridType === 'logarithmic') {
        // skbrtm: edges geometric from min_length to max_length. The same
        // edges, measured from the first, are a log grid with this ratio.
        const q = Math.pow(hi / lo, 1 / cells);
        settings.push('GRID = log', `GRID_RATIO = ${fmt(Math.pow(q, cells - 1))}`);
      } else settings.push('GRID = linear');
      settings.push('DIFFUSION = 1', `LEFT = ${bcs[0] || 'neumann'}`, `RIGHT = ${bcs[1] || 'neumann'}`);
      if (lo !== 0) notes.push(`min_length is ${lo} m; x here is measured from there, so a profile read at x is read at x + ${lo}.`);
      const listed = new Map();
      list(v.species).forEach((s, k) => listed.set(meet(s), Number(maybe(list(v.diffusion_coefficient)[k], 1e-9))));
      for (const key of order) D.set(key, listed.has(key) ? listed.get(key) : 1e-9);
      const unlisted = order.filter((k) => !listed.has(k)).map(nameOf);
      if (unlisted.length) {
        notes.push(`DIFFUSION lists only the species that do not move; the other ${unlisted.length} diffuse at `
          + 'skbrtm\'s default D = 1e-9 m2/s.');
      }
      const bv = maybe(v.boundary_values, {});
      if (bv && typeof bv === 'object' && Object.keys(bv).length) {
        warnings.push('skbrtm ignores boundary_values -- its Diffusion never builds the masks it describes. They are '
          + 'used here as the face concentrations they were meant to be.');
        for (const side of ['left', 'right']) {
          for (const [s, val] of Object.entries(bv[side] || {})) faceValue[side].set(meet(s), Number(val));
        }
      }
      for (const side of [0, 1]) {
        if (bcs[side] === 'dirichlet') {
          notes.push(`The ${side ? 'right' : 'left'} end is dirichlet. skbrtm holds the ${side ? 'last' : 'first'} CELL at its `
            + 'starting value; here the FACE is held at that value and the cell starts where the column does. '
            + `To hold the cell instead, as skbrtm does: ${side ? 'RIGHT' : 'LEFT'} = neumann, and "fixed" on that cell in <INITIAL>.`);
        }
      }
    } else settings.push('MODE = batch');
    if (script && script.tend) {
      settings.push(`TEND = ${fmt(script.tend)}`);
    } else {
      settings.push('TEND = 1');
      warnings.push(script ? 'The script\'s t_span could not be read; TEND is 1 s.' : 'No script was opened, so TEND is 1 s: set it, in seconds.');
    }
    settings.push('TIME_UNIT = second');

    // ---- the starting state, SOLUTION by SOLUTION; each sets every species in its cells ----
    const start = new Map(order.map((k) => [k, Array.from({ length: cells }, () => ({ v: '0', held: false }))]));
    const covered = new Array(cells).fill(false);
    const usedParams = new Set();
    const perWidth = new Set();
    for (const b of of('solution')) {
      const v = b.values;
      const units = String(maybe(v.units, 'mol/L')).toLowerCase();
      if (units !== 'mol/l') warnings.push(`SOLUTION "${b.name}" is in ${units}; skbrtm refuses anything but mol/L.`);
      let from = 0;
      let to = 1;
      if (v.cell_id !== undefined) {
        const s = String(v.cell_id).trim();
        const r = /^(\d+)\s*-\s*(\d+)$/.exec(s);
        if (r) { from = Number(r[1]); to = Number(r[2]); } else if (/^\d+$/.test(s)) {
          from = Number(s);
          to = from + 1;
          if (from !== 0) {
            warnings.push(`SOLUTION "${b.name}" is for cell ${from}. skbrtm puts a single cell_id other than 0 in cell 0 `
              + '(a lone integer becomes range(0, 1)); here it goes where it says.');
          }
        } else warnings.push(`SOLUTION "${b.name}": cell_id "${s}" is not understood; cell 0 was used.`);
      }
      if (to > cells) {
        notes.push(`SOLUTION "${b.name}" names cells ${from}-${to - 1} of ${cells}; ${to - cells} of them do not exist `
          + '(skbrtm\'s ranges stop one short, 1-100 being 1 to 99).');
      }
      const conc = new Map();
      list(v.species).forEach((s, k) => conc.set(meet(s), decimal(String(list(v.concentration)[k] ?? '0').trim())));
      const consts = v.constant ? String(v.constant).split(/\s*,\s*/).filter(Boolean).map(meet) : [];
      for (let c = from; c < Math.min(to, cells); c++) {
        covered[c] = true;
        for (const key of order) {
          let val = conc.has(key) ? conc.get(key) : '0';
          // The width of the cell, and the dict's parameters, by the names this page uses.
          if (/\bcell_width\b/.test(val)) perWidth.add(nameOf(key));
          val = val.replace(/\bcell_width\b/g, 'w');
          for (const id of val.match(/[A-Za-z_][A-Za-z0-9_]*/g) || []) if (paramOf(id)) usedParams.add(paramOf(id)[0]);
          start.get(key)[c] = { v: val, held: consts.includes(key) };
        }
      }
    }
    if (perWidth.size && transport) {
      notes.push(`${[...perWidth].join(' and ')} ${perWidth.size > 1 ? 'are' : 'is'} given per cell width, a surface `
        + 'amount spread through the cell it sits in. The chemistry there then depends on how thick that cell is, '
        + 'which the grid decides: SURFACE_LAYER = (a thickness in m) in <SETTINGS> makes it a property of the model.');
    }
    const uncovered = covered.map((c, i) => (c ? -1 : i)).filter((i) => i >= 0);
    if (uncovered.length && of('solution').length) {
      notes.push(`${uncovered.length === cells ? 'No cell is' : `Cells ${uncovered[0]}-${uncovered[uncovered.length - 1]} are`} `
        + 'in any SOLUTION, and start with every species at zero, as in skbrtm.');
    }

    // A dirichlet face takes the value skbrtm held its cell at; the cell next
    // to it starts where the column behind it does.
    const faces = [];
    for (const [side, cell, next] of [['left', 0, 1], ['right', cells - 1, cells - 2]]) {
      if (!transport || bcs[side === 'left' ? 0 : 1] !== 'dirichlet') continue;
      for (const key of order) {
        if (!(D.get(key) > 0)) continue;
        const col = start.get(key);
        let face = faceValue[side].has(key) ? faceValue[side].get(key) : Number(col[cell].v);
        if (!Number.isFinite(face)) {
          face = evalText(col[cell].v, (id) => (paramOf(id) ? Number(paramOf(id)[1]) : undefined));
          if (face === null) { warnings.push(`${nameOf(key)}: the ${side} face value "${col[cell].v}" is not a number; 0 was used.`); face = 0; }
        }
        faces.push({ key, side, value: face });
        // A species skbrtm also holds in that cell (constant there) stays as
        // it is: a held cell is a reservoir, and the face beside it is moot.
        if (next >= 0 && next < cells && !col[cell].held) col[cell] = { v: col[next].v, held: false };
      }
    }

    // ---- the dose-rate tables: the data, not a fit ----
    const tables = [];
    for (const b of of('regression')) {
      const v = b.values;
      const xs = list(v.predictor).map((s) => Number(decimal(s)));
      const ys = list(v.response).map((s) => Number(decimal(s)));
      const bounds = list(maybe(v.bounds, [null, null, null, null])).map((x) => (x === null ? null : Number(x)));
      const [bx0, bx1, by0, by1] = bounds;
      const rows = [];
      xs.forEach((x, k) => {
        const y = ys[k];
        if (!Number.isFinite(x) || !Number.isFinite(y)) return;
        if ((bx0 !== null && x < bx0) || (bx1 !== null && x > bx1)) return;
        if ((by0 !== null && y < by0) || (by1 !== null && y > by1)) return;
        rows.push([x, y]);
      });
      rows.sort((a, c) => a[0] - c[0]);
      const unique = rows.filter((r, k) => k === 0 || r[0] > rows[k - 1][0]);
      const name = b.name.replace(/[^A-Za-z0-9_]/g, '_');
      const log = unique.length > 1 && unique.every(([, y]) => y > 0);
      tables.push({ name, key: b.name.toLowerCase(), log, rows: unique, fn: String(maybe(v.function, 'linear')),
        xname: String(maybe(v.name_predictor, 'x')), yname: String(maybe(v.name_response, 'value')) });
      notes.push(`REGRESSION ${b.name}: skbrtm fits ${String(maybe(v.function, 'linear'))} to its ${unique.length} rows `
        + `and uses the fit; here the rows themselves are interpolated${log ? ' (in the logarithm)' : ''}, and held at `
        + 'the end values beyond them.');
    }
    const tableByCall = new Map(tables.map((t) => [t.key, t]));

    // ---- a law, rewritten for rtm.html and read both ways ----
    const symbol = new Map(order.map((k, i) => [k, `s${i}_0`]));
    const extraParams = new Map();           // <PARAMETERS> a law turned out to need
    function law(expr, args, where) {
      let text = String(expr).trim();
      if (text.includes('=')) text = text.split('=').pop().trim();
      // A fitted function of the place is the parameter made from its table.
      text = text.replace(/\b([A-Za-z_][A-Za-z0-9_]*)\s*\(\s*coordinates\s*\)/g, (m0, fn) => {
        const t = tableByCall.get(fn.toLowerCase());
        return t ? t.name : m0;
      });
      text = text.replace(/\bcoordinates\b/g, () => { extraParams.set('coordinates', `x${lo ? ` + ${lo}` : ''}`); return 'coordinates'; });
      text = text.replace(/\bcell_width\b/g, () => { extraParams.set('cell_width', 'w'); return 'cell_width'; });
      text = text.replace(/\[([^\]]+)\]/g, (_, n) => `[${nameOf(n)}]`);
      const argParts = splitTop(String(args || '')).map((a) => a.trim()).filter(Boolean)
        .map((a) => a.replace(/\[([^\]]+)\]/g, (_, n) => `[${nameOf(n)}]`));
      const defined = new Set(argParts.map((a) => a.split('=')[0].trim()));
      // Names the law uses that its line does not define: skbrtm looks them
      // up in its merged parameter dict.
      const masked = text.replace(/\[[^\]]+\]/g, 'S__');
      const extra = [];
      // The names in the law, read by the parser -- a regex would take the
      // e4 of 8.1e4 for one.
      const ids = new Set();
      try {
        (function walk(node) {
          if (!node || typeof node !== 'object') return;
          if (node.type === 'id') ids.add(node.name);
          [node.l, node.r, node.a, ...(node.args || [])].forEach(walk);
        }(FacsimileModel.parseExpression(masked, 0)));
      } catch (e) {
        warnings.push(`${where}: the law "${text}" does not parse (${e.message}).`);
      }
      for (const id of ids) {
        if (id === 'S__' || defined.has(id) || tables.some((t) => t.name === id) || extraParams.has(id)) continue;
        const p = paramOf(id);
        if (p) extra.push(`${id} = ${p[1]}`);
        else warnings.push(`${where}: "${id}" is neither an argument, a species nor a parameter.`);
      }
      const all = [...argParts, ...extra];
      // skbrtm's own reading of the same text, side by side with this one.
      const skb = skbrtmReads(expr, args, symbol);
      const ours = oursReads(text, all);
      if (skb !== null && ours !== null) {
        const conc = order.map((_, i) => 10 ** (-1 - (i % 5)) * (1 + i / order.length));
        const probe = 0.37;
        const aVal = ours((name) => conc[order.indexOf(String(name).toLowerCase())], probe);
        const bVal = skb((i) => conc[i], probe);
        if (aVal !== null && bVal !== null && Number.isFinite(aVal) && Number.isFinite(bVal)
            && Math.abs(aVal - bVal) > 1e-9 * Math.max(Math.abs(aVal), Math.abs(bVal))) {
          const ratio = aVal === 0 ? Infinity : bVal / aVal;
          const times = Math.abs(ratio) >= 1e-3 && Math.abs(ratio) < 1e4 ? ratio.toPrecision(4) : ratio.toExponential(3);
          warnings.push(`${where}: skbrtm pastes the arguments into the law as text and integrates ${times} `
            + 'times this rate. This model uses the law as written.');
          return { text, args: all, note: `skbrtm integrates ${times} times this rate (its arguments are pasted in as text)` };
        }
      }
      return { text, args: all, note: null };
    }

    /** What skbrtm integrates: its parse_expression, string for string. */
    function skbrtmReads(expr, args, sym) {
      let e = String(expr).toLowerCase();
      const a = String(args || '').toLowerCase();
      const sub = (s) => s.replace(/\[([^\]]+)\]/g, (_, n) => sym.get(n.trim()) || `[${n}]`);
      e = sub(e);
      if (a) {
        for (let part of a.split(',')) {
          part = sub(part);
          const kv = part.includes('=') ? part.split('=').map((x) => x.trim()) : [part.trim(), part.trim()];
          if (kv.length !== 2) return null;
          e = e.split(kv[0]).join(kv[1]);
        }
      }
      if (e.includes('=')) e = e.split('=').pop().trim();
      e = e.replace(/\b([a-z_][a-z0-9_]*)\s*\(\s*coordinates\s*\)/g, 'PROBE__');
      let ast;
      try { ast = FacsimileModel.parseExpression(e, 0); } catch (err) { return null; }
      return (conc, probe) => {
        try {
          return FacsimileModel.evalAst(ast, (id) => {
            const m = /^s(\d+)_0$/.exec(id);
            if (m) return conc(Number(m[1]));
            if (id === 'PROBE__') return probe;
            const p = paramOf(id);
            return p ? Number(p[1]) : undefined;
          }, {}, 0);
        } catch (err) { return null; }
      };
    }

    /** What this model integrates, for the same comparison. */
    function oursReads(text, argParts) {
      const consts = new Map();
      const alias = new Map();
      for (const a of argParts) {
        const [k, ...rest] = a.split('=');
        const v = rest.join('=').trim();
        const m = /^\[([^\]]+)\]$/.exec(v);
        if (m) alias.set(k.trim(), m[1]);
        else {
          const n = evalText(v, (id) => consts.get(id));
          if (n === null) return null;
          consts.set(k.trim(), n);
        }
      }
      const ids = [];
      const masked = text.replace(/\[([^\]]+)\]/g, (_, n) => { ids.push(n); return `SP${ids.length - 1}__`; });
      let ast;
      try { ast = FacsimileModel.parseExpression(masked, 0); } catch (err) { return null; }
      return (conc, probe) => {
        try {
          return FacsimileModel.evalAst(ast, (id) => {
            const m = /^SP(\d+)__$/.exec(id);
            if (m) return conc(ids[Number(m[1])]);
            if (alias.has(id)) return conc(alias.get(id));
            if (consts.has(id)) return consts.get(id);
            if (tables.some((t) => t.name === id)) return probe;
            const p = paramOf(id);
            return p ? Number(p[1]) : undefined;
          }, {}, 0);
        } catch (err) { return null; }
      };
    }

    // ---- the reactions and the sources ----
    const rxLines = [];
    for (const row of rxRows) {
      const [l, r] = sides(row.st);
      const lhs = terms(l || '').map((m) => `${m[1] ? `${m[1]} ` : ''}${nameOf(m[2])}`).join(' + ');
      const rhs = terms(r || '').map((m) => `${m[1] ? `${m[1]} ` : ''}${nameOf(m[2])}`).join(' + ');
      // A line that changes nothing -- OH- = OH- -- is how skbrtm is told a
      // species exists. Here the species list says that.
      const net = new Map();
      for (const [sgn, side] of [[-1, l || ''], [1, r || '']]) {
        for (const m of terms(side)) {
          const k = String(m[2]).toLowerCase();
          net.set(k, (net.get(k) || 0) + sgn * Number(m[1] || 1));
        }
      }
      if ([...net.values()].every((c) => Math.abs(c) < 1e-15)) {
        rxLines.push(`# ${row.st.trim()} ; ${row.ex.trim()} ; ${row.ar.trim()}   (changes nothing; it only lists the species)`);
        continue;
      }
      const L = law(row.ex, row.ar, `"${row.st.trim()}"`);
      if (L.note) rxLines.push(`# NOTE ${L.note}.`);
      rxLines.push(`${lhs} => ${rhs}, r = ${L.text}${L.args.length ? `, ${L.args.join(', ')}` : ''}`);
    }
    const srcLines = [];
    for (const row of srcRows) {
      const L = law(row.ex, row.ar, `the source of ${row.sp}`);
      if (L.note) srcLines.push(`# NOTE ${L.note}.`);
      srcLines.push(`=> ${nameOf(row.sp)}, r = ${L.text}${L.args.length ? `, ${L.args.join(', ')}` : ''}`);
    }

    // ---- the text ----
    const out = [];
    out.push('# Opened from skbrtm databases: ' + dbs.map((f) => f.name.replace(/^.*[\\/]/, '')).join(', ') + '.');
    if (script) {
      out.push(`# Settings from ${scripts[0].name}: t_span ${script.span ? `(${script.span.join(', ')}, '${script.unit}')` : 'unread'}`
        + `${script.rtol ? `, rtol ${script.rtol}` : ', rtol 1e-3 (skbrtm\'s default)'}`
        + `${script.atol ? `, atol ${script.atol}` : ''}${script.method ? `, method ${script.method}` : ''}.`);
    }
    out.push('# Rate constants are per second, as skbrtm integrates in seconds.');
    if (notes.length || warnings.length) {
      out.push('#');
      for (const s of [...warnings.map((w) => `NOTE ${w}`), ...notes]) {
        const words = s.split(/\s+/);
        let lineText = '#';
        for (const w of words) {
          if (lineText.length + w.length > 90 && lineText !== '#') { out.push(lineText); lineText = '#  '; }
          lineText += ` ${w}`;
        }
        out.push(lineText);
      }
    }
    out.push('', '<SETTINGS>', ...settings, '', '<SPECIES>');
    const initial = [];
    for (const key of order) {
      const col = start.get(key);
      const counts = new Map();
      for (const c of col) counts.set(c.v, (counts.get(c.v) || 0) + 1);
      const common = [...counts.entries()].sort((a, c) => c[1] - a[1])[0][0];
      const allHeld = col.every((c) => c.held);
      const flags = [];
      if (allHeld) flags.push('fixed');
      if (transport && D.get(key) > 0 && !allHeld) flags.push(`D=${fmt(D.get(key))}`);
      for (const f of faces.filter((x) => x.key === key)) flags.push(`${f.side}=${fmt(f.value)}`);
      // A value that is an expression goes in <INITIAL>: the species line takes numbers.
      const plain = Number.isFinite(Number(common));
      out.push(`${nameOf(key).padEnd(10)} ${(plain ? common : '0').padEnd(10)} ${flags.join(' ')}`.trimEnd());
      // Runs of cells that differ from the species line, or are held there alone.
      let c = 0;
      while (c < cells) {
        const here = col[c];
        const differs = here.v !== (plain ? common : '0') || (here.held && !allHeld);
        if (!differs) { c++; continue; }
        let e = c;
        while (e + 1 < cells && col[e + 1].v === here.v && col[e + 1].held === here.held) e++;
        const range = c === e ? `${c}` : (c === 0 && e === cells - 1 ? 'all' : `${c}-${e}`);
        initial.push(`${nameOf(key).padEnd(10)} ${range.padEnd(6)} ${here.v}${here.held && !allHeld ? '  fixed' : ''}`);
        c = e + 1;
      }
    }
    if (initial.length) out.push('', '<INITIAL>', ...initial);
    for (const t of tables) {
      out.push('', `<TABLE ${t.name}${t.log ? ' log' : ''}>`, `# ${t.xname} -> ${t.yname}`);
      for (const [x, y] of t.rows) out.push(`${fmt(x)}  ${fmt(y)}`);
    }
    const plines = [];
    for (const key of usedParams) {
      const v = params.get(key);
      if (Number.isFinite(Number(v))) plines.push(`${key} all ${fmt(Number(v))}`);
    }
    for (const t of tables) plines.push(`${t.name} all ${t.name}(x${lo ? ` + ${lo}` : ''})`);
    for (const [k, v] of extraParams) plines.push(`${k} all ${v}`);
    if (plines.length) out.push('', '<PARAMETERS>', ...plines);
    out.push('', '<REACTIONS>', ...rxLines);
    if (srcLines.length) out.push('', '# Sources: skbrtm\'s SOURCETERM blocks', ...srcLines);
    return { text: `${out.join('\n')}\n`, notes, warnings };
  }

  return { convert, isDatabase, readBlocks, readScript, pyLiteral };
}));
