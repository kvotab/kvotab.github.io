/* ==========================================================================
   RTM.HTML: THE REACTIVE-TRANSPORT COMPILER

   Turns a model text into something FacsimileODE.runModel can integrate: a
   right-hand side, an analytic Jacobian over a fixed sparsity pattern, and an
   initial state. The solvers are the page's own -- the built-in NDF/BDF and the
   ode_julia ports -- and they are given exactly the interface they already
   expect from facsimile-model.js, so nothing in them had to change.

   WHAT IT SOLVES

     dC_s,i/dt = (production - consumption by the reactions in cell i)
               + (diffusion between cell i and its neighbours)
               + (advection into cell i from upwind)

   With one cell and no transport that is a batch reactor; the mode switch
   simply stops building the transport part.

   HOW THE JACOBIAN IS BUILT, AND WHY IT IS EXACT

   Every rate law is parsed to an expression tree and differentiated
   symbolically with respect to each species it mentions -- no differencing,
   no tolerance to choose. The derivatives and the rates are emitted together
   as one JavaScript function that is compiled once and then run per cell, so
   a hundred cells cost a hundred calls to compiled code rather than a hundred
   interpretations of a tree.

   The chemistry is identical in every cell, so the Jacobian is block-diagonal
   with one block per cell, plus the transport terms. Those couple a species
   only to ITSELF in the neighbouring cells, which is why the state is ordered
   CELL-MAJOR: index = cell * nspecies + species. Transport then lands at
   offsets of +/- nspecies from the diagonal and the matrix is banded, where
   species-major ordering would spread the chemistry across the whole width.

   ONE GLOBAL: RtmModel. Runs in a page, a Worker and Node.
   ========================================================================== */
(function (root, factory) {
  const fac = root.FacsimileModel
    || (typeof require === 'function' ? require('./facsimile-model.js') : null);
  const api = factory(fac);
  root.RtmModel = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
}(typeof self !== 'undefined' ? self : this, function (FacsimileModel) {
  'use strict';

  class RtmError extends Error {
    constructor(message, line) {
      super(line ? `Line ${line}: ${message}` : message);
      this.name = 'RtmError';
      this.line = line;
    }
  }

  /* ======================================================================
     1. The model text
     ====================================================================== */

  const SECTIONS = ['SETTINGS', 'SPECIES', 'REACTIONS', 'INITIAL', 'PARAMETERS', 'EQUILIBRIUM'];

  /** Settings, their defaults and how each is read. */
  const SETTINGS = {
    MODE: { def: 'batch', kind: 'word', of: ['batch', 'transport'] },
    CELLS: { def: 20, kind: 'int' },
    LENGTH: { def: 1, kind: 'number' },
    GRID: { def: 'linear', kind: 'word', of: ['linear', 'log'] },
    DIFFUSION: { def: 1, kind: 'flag' },
    ADVECTION: { def: 0, kind: 'flag' },
    VELOCITY: { def: 0, kind: 'number' },
    POROSITY: { def: 1, kind: 'number' },
    /*
      The four kinds a face can be, under the names the transport literature
      gives them. `cauchy` and `robin` are the same third-type condition and
      `outflow` is `free` by another name; the aliases are folded in below so
      that only two words reach the assembly.
    */
    LEFT: { def: 'dirichlet', kind: 'word',
      of: ['dirichlet', 'neumann', 'robin', 'cauchy', 'free', 'outflow'] },
    RIGHT: { def: 'neumann', kind: 'word',
      of: ['dirichlet', 'neumann', 'robin', 'cauchy', 'free', 'outflow'] },
    TEND: { def: 1, kind: 'number' },
    /*
      The unit every time in the model is written in. It converts NOTHING: the
      solver integrates whatever numbers it is given, so a model in years has
      its rate constants per year, its diffusivities in m2/a and its TEND in
      years, all of a piece. What the setting does is let the page say so --
      label an axis, read "500 y" in a box, print a travel time -- instead of
      calling everything seconds. Mixing units inside one model is the one
      thing this cannot rescue, and never could.
    */
    TIME_UNIT: { def: 'second', kind: 'word',
      of: ['s', 'sec', 'second', 'seconds', 'min', 'minute', 'minutes',
        'h', 'hour', 'hours', 'd', 'day', 'days', 'a', 'y', 'yr', 'year', 'years'] },
    EQUILIBRATE: { def: 0, kind: 'flag' },
    /*
      DUAL POROSITY: a rock matrix beside the column.

      With MATRIX_CELLS above zero every cell of the column -- the fracture,
      the flowing water -- has a chain of that many stagnant cells behind it,
      reaching MATRIX_DEPTH into the rock, into which species diffuse and in
      which they react and sorb. The layers grow geometrically with depth from
      MATRIX_FIRST (worked out when left at zero), because the gradient is
      steepest at the wall. WETTED_SURFACE is the rock surface in contact with
      a unit volume of flowing water, m2/m3; APERTURE (2b) is the other way of
      saying it, aw = 2/(2b) = 1/b. In the SKB parameterisation aw = F/t_w.
      PECLET, when set, gives every mobile species the same longitudinal
      dispersion v*L/Pe along the fracture, less the v*dz/2 the upwind scheme
      already puts in.
    */
    MATRIX_CELLS: { def: 0, kind: 'number' },
    MATRIX_DEPTH: { def: 0, kind: 'number' },
    MATRIX_FIRST: { def: 0, kind: 'number' },
    MATRIX_POROSITY: { def: 0, kind: 'number' },
    WETTED_SURFACE: { def: 0, kind: 'number' },
    APERTURE: { def: 0, kind: 'number' },
    PECLET: { def: 0, kind: 'number' },
  };

  /**
   * Split the text into its sections, dropping comments and blank lines but
   * keeping the line number of everything so that an error can point at it.
   */
  /**
   * The time units a model may be written in: the name to print, and how many
   * seconds one of them is, for the page's own formatting. A year is the
   * Julian year of 365.25 days, which is what a and yr mean in the reports
   * these models come from.
   */
  const TIME_UNITS = (() => {
    const table = [
      [['s', 'sec', 'second', 'seconds'], 'second', 's', 1],
      [['min', 'minute', 'minutes'], 'minute', 'min', 60],
      [['h', 'hour', 'hours'], 'hour', 'h', 3600],
      [['d', 'day', 'days'], 'day', 'd', 86400],
      [['a', 'y', 'yr', 'year', 'years'], 'year', 'a', 365.25 * 86400],
    ];
    const out = {};
    for (const [words, name, symbol, seconds] of table) {
      for (const w of words) out[w] = { name, symbol, seconds };
    }
    return out;
  })();

  function readSections(text) {
    const out = {};
    for (const name of SECTIONS) out[name] = [];
    let current = null;
    String(text).split(/\r?\n/).forEach((raw, i) => {
      const line = raw.replace(/(^|\s)#.*$/, '').trim();
      if (!line) return;
      const header = /^<\s*([A-Za-z]+)\s*>$/.exec(line);
      if (header) {
        const name = header[1].toUpperCase();
        if (!SECTIONS.includes(name)) {
          throw new RtmError(`"${name}" is not a section. Use ${SECTIONS.map((s) => `<${s}>`).join(', ')}.`, i + 1);
        }
        current = name;
        return;
      }
      if (!current) throw new RtmError('Text before the first section; start with <SETTINGS>.', i + 1);
      out[current].push({ text: line, line: i + 1 });
    });
    return out;
  }

  /** `NAME = value` lines, read against the table above. */
  function readSettings(lines) {
    const out = {};
    for (const [name, spec] of Object.entries(SETTINGS)) out[name] = spec.def;
    for (const { text, line } of lines) {
      const m = /^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$/.exec(text);
      if (!m) throw new RtmError(`"${text}" is not NAME = value.`, line);
      const name = m[1].toUpperCase();
      const spec = SETTINGS[name];
      if (!spec) {
        throw new RtmError(`"${name}" is not a setting. Known: ${Object.keys(SETTINGS).join(', ')}.`, line);
      }
      const raw = m[2].trim();
      if (spec.kind === 'word') {
        const word = raw.toLowerCase();
        if (!spec.of.includes(word)) {
          throw new RtmError(`${name} must be one of ${spec.of.join(', ')}, not "${raw}".`, line);
        }
        out[name] = { cauchy: 'robin', outflow: 'free' }[word] || word;
        if (name === 'TIME_UNIT') out[name] = TIME_UNITS[out[name]].name;
      } else if (spec.kind === 'flag') {
        out[name] = /^(1|yes|true|on)$/i.test(raw) ? 1 : 0;
      } else {
        const v = Number(raw);
        if (!Number.isFinite(v)) throw new RtmError(`${name} = "${raw}" is not a number.`, line);
        out[name] = spec.kind === 'int' ? Math.round(v) : v;
      }
    }
    if (out.MODE === 'transport' && !(out.CELLS >= 2)) {
      throw new RtmError('Transport needs CELLS of at least 2.');
    }
    if (out.MODE === 'transport' && !(out.LENGTH > 0)) {
      throw new RtmError('Transport needs a LENGTH greater than zero.');
    }
    return out;
  }

  /*
    A species name is a chemical formula, not a programming identifier: e-, H+,
    OH-, C2O4-2, UO2+2, U_site. It must therefore never be read as arithmetic,
    which is why a rate law writes concentrations in brackets -- [e-] -- and why
    a stoichiometry is split on " + " with the spaces, so the + inside H+ is
    left alone.
  */
  const SPECIES_NAME = /^[A-Za-z][A-Za-z0-9_]*(?:[+-][0-9]*)?$/;

  /**
   * One line of <SPECIES>: a name, a concentration, then any of the flags.
   *
   *   H2O   55.56  fixed
   *   H+    1e-7   D=9.3e-9  left=1e-7
   */
  function readSpecies(lines) {
    const list = [];
    const seen = new Map();
    for (const { text, line } of lines) {
      const parts = text.split(/[\s,;]+/).filter(Boolean);
      const name = parts.shift();
      if (!SPECIES_NAME.test(name)) {
        throw new RtmError(`"${name}" is not a species name. Letters, digits and _ , optionally `
          + 'ending in a charge such as + , - , +2 or -2.', line);
      }
      if (seen.has(name)) throw new RtmError(`Species "${name}" is given twice.`, line);
      const entry = { name, initial: 0, fixed: false, D: 0, left: null, right: null,
        mass: null, Dm: 0, Rm: null, line };
      let first = true;
      for (const part of parts) {
        const kv = /^([A-Za-z_]+)\s*=\s*(.+)$/.exec(part);
        if (kv) {
          const key = kv[1].toLowerCase();
          /*
            mass (or R, its name in the transport literature) is the coefficient
            on the left of M dC/dt = f: a retardation factor, a porosity, a
            water content. It may be a plain number or the name of a parameter,
            so that it can vary down a column. The others must be numbers.
          */
          if (key === 'mass' || key === 'r') { entry.mass = kv[2].trim(); continue; }
          // Rm is the matrix's capacity for the species, eps_m + rho*Kd in the
          // SKB reports -- the coefficient on the left of the matrix equation
          // -- and like R it may name a parameter.
          if (key === 'rm') { entry.Rm = kv[2].trim(); continue; }
          const value = Number(kv[2]);
          if (!Number.isFinite(value)) throw new RtmError(`"${part}" is not a number.`, line);
          if (key === 'd') entry.D = value;
          else if (key === 'dm') entry.Dm = value;
          else if (key === 'left') entry.left = value;
          else if (key === 'right') entry.right = value;
          else throw new RtmError(`"${kv[1]}" is not a species property. Use D, left, right, `
            + 'mass or R, and with a rock matrix Dm or Rm.', line);
          continue;
        }
        if (/^fixed$/i.test(part)) { entry.fixed = true; continue; }
        if (first) {
          const v = Number(part);
          if (!Number.isFinite(v)) throw new RtmError(`"${part}" is not a concentration.`, line);
          entry.initial = v;
          first = false;
          continue;
        }
        throw new RtmError(`"${part}" is not understood on a species line.`, line);
      }
      seen.set(name, list.length);
      list.push(entry);
    }
    if (!list.length) throw new RtmError('No species: the <SPECIES> section is empty.');
    return list;
  }

  /**
   * One line of the optional <INITIAL> section: a species, which cells, and
   * what to put there.
   *
   *   X   0-9    1.0        the first ten cells
   *   O2  all    2.1e-4     every cell, the same as writing it in <SPECIES>
   *   Fe  20     0.5        one cell
   *
   * <SPECIES> gives a concentration the whole domain starts at, which is all a
   * batch run can have; a front, a plume or a layer needs this.
   */
  function readInitial(lines, index, cells) {
    const out = [];
    for (const { text, line } of lines) {
      const parts = text.split(/[\s,;]+/).filter(Boolean);
      // A fourth word, "matrix", aims the line at the rock behind those cells
      // rather than at the cells themselves.
      let matrix = false;
      if (parts.length === 4 && /^matrix$/i.test(parts[3])) { matrix = true; parts.pop(); }
      if (parts.length !== 3) {
        throw new RtmError(`"${text}" is not "species cells value" -- for example "X 0-9 1.0", `
          + 'or "X 0-9 1.0 matrix" for the rock behind those cells.', line);
      }
      const [name, where, raw] = parts;
      if (!index.has(name)) throw new RtmError(`"${name}" is not in <SPECIES>.`, line);
      const value = Number(raw);
      if (!Number.isFinite(value)) throw new RtmError(`"${raw}" is not a concentration.`, line);
      let from;
      let to;
      if (/^all$/i.test(where)) { from = 0; to = cells - 1; } else {
        const m = /^(\d+)(?:\s*-\s*(\d+))?$/.exec(where);
        if (!m) throw new RtmError(`"${where}" is not a cell or a range such as 0-9, or "all".`, line);
        from = Number(m[1]);
        to = m[2] === undefined ? from : Number(m[2]);
      }
      if (from > to) { const t = from; from = to; to = t; }
      if (to >= cells) throw new RtmError(`Cell ${to} is past the last one (${cells - 1}).`, line);
      out.push({ si: index.get(name), from, to, value, matrix });
    }
    return out;
  }

  /* ======================================================================
     The rock matrix's layers
     ====================================================================== */

  /**
   * Dekker's zeroin (1969), in the form SKB's FARFCOMP uses to lay out its
   * matrix layers -- kept step for step so that the thicknesses come out bit
   * for bit the same as the reference implementation's, which is what lets
   * a model here be checked against it to fourteen digits. It converges to
   * the last representable step, so there is no tolerance to agree on.
   */
  function zeroin(fn, a, b) {
    let fa = fn(a);
    let fc = fa;
    let c = a;
    let fb;
    for (let guard = 0; guard < 1000; guard++) {
      fb = fn(b);
      if (Math.sign(fb) === Math.sign(fc)) { c = a; fc = fa; }
      if (Math.abs(fc) < Math.abs(fb)) {
        [a, b, c] = [b, c, b];
        [fa, fb, fc] = [fb, fc, fb];
      }
      const m = (b + c) / 2;
      if (Math.abs(m - b) <= spacing(Math.abs(b))) return b;
      let p = (b - a) * fb;
      let q = fa - fb;
      if (p < 0) { q = -q; p = -p; }
      a = b;
      fa = fb;
      if (p <= spacing(q)) b += Math.sign(c - b) * spacing(b);
      else if (p <= (m - b) * q) b += p / q;
      else b = m;
    }
    return b;
  }

  const SPACING_VIEW = new DataView(new ArrayBuffer(8));

  /** numpy's spacing: the distance to the next double away from zero. */
  function spacing(x) {
    const a = Math.abs(x);
    if (a === 0) return Number.MIN_VALUE;
    if (!Number.isFinite(a)) return NaN;
    SPACING_VIEW.setFloat64(0, a);
    let hi = SPACING_VIEW.getUint32(0);
    let lo = SPACING_VIEW.getUint32(4);
    lo = (lo + 1) >>> 0;
    if (lo === 0) hi = (hi + 1) >>> 0;
    SPACING_VIEW.setUint32(0, hi);
    SPACING_VIEW.setUint32(4, lo);
    const up = SPACING_VIEW.getFloat64(0) - a;
    return x < 0 ? -up : up;
  }

  /**
   * The matrix layer thicknesses: a geometric series d[j] = d0 * q^j whose
   * nm terms add up to exactly the depth, because the gradient is steepest
   * at the fracture wall and all but flat at depth.
   *
   * With `first` given, q follows from it. With it left out the first layer
   * is the one that makes the ratio come out at e, bracketed between a
   * micrometre and the fracture's own aperture 2/aw -- SKB's FARFCOMP rule,
   * reproduced exactly. One layer is simply the whole depth.
   */
  function layerDepths(depth, nm, aw, first) {
    if (nm === 1) return Float64Array.of(depth);
    let d0 = first > 0 ? first : null;
    if (d0 === null) {
      const geo = (x) => {
        let sum = 0;
        for (let k = 1; k <= nm; k++) sum += x * Math.exp(k);
        return sum - depth;
      };
      d0 = zeroin(geo, 1e-12 / Math.E, 2 / aw / Math.E) * Math.E;
    }
    if (d0 * nm > depth * (1 + 1e-12)) {
      throw new RtmError(`${nm} matrix layers starting at ${d0} m cannot add up to MATRIX_DEPTH `
        + `${depth} m: the layers grow with depth, so the first must be smaller than `
        + `${depth / nm} m. Use a thinner MATRIX_FIRST, fewer layers, a greater depth, or leave `
        + 'MATRIX_FIRST at zero to have it worked out.');
    }
    const total = (q) => {
      let sum = 0;
      for (let j = 0; j < nm; j++) sum += d0 * q ** j;
      return sum - depth;
    };
    let hi = 100;
    while (total(hi) < 0 && hi < 1e300) hi *= 100;
    const q = zeroin(total, 1, hi);
    const d = new Float64Array(nm);
    for (let j = 0; j < nm; j++) d[j] = d0 * q ** j;
    return d;
  }

  /**
   * The rock matrix, or null: how many layers, how thick, how deep their
   * centres sit, and the two numbers that turn a layer into a rate -- the
   * wetted surface per unit water volume and the matrix porosity.
   */
  function makeMatrix(settings, line) {
    const nm = settings.MATRIX_CELLS;
    if (!(nm > 0)) return null;
    if (!Number.isInteger(nm)) throw new RtmError(`MATRIX_CELLS must be a whole number, not ${nm}.`);
    if (settings.MODE !== 'transport') {
      throw new RtmError('MATRIX_CELLS needs MODE = transport: a rock matrix sits beside a column, '
        + 'and a batch has none.');
    }
    if (!(settings.MATRIX_DEPTH > 0)) {
      throw new RtmError('A rock matrix needs MATRIX_DEPTH: how far into the rock, in metres, the '
        + 'layers reach.');
    }
    if (!(settings.MATRIX_POROSITY > 0)) {
      throw new RtmError('A rock matrix needs MATRIX_POROSITY: the pore-water fraction of the rock, '
        + 'which scales what the reactions do there and is the capacity Rm of a species that '
        + 'does not sorb.');
    }
    let aw = settings.WETTED_SURFACE;
    if (settings.APERTURE > 0) {
      if (aw > 0 && Math.abs(aw - 2 / settings.APERTURE) > 1e-9 * aw) {
        throw new RtmError('WETTED_SURFACE and APERTURE disagree: aw = 2/aperture. Give one of them.');
      }
      aw = 2 / settings.APERTURE;
    }
    if (!(aw > 0)) {
      throw new RtmError('A rock matrix needs the fracture surface a unit volume of water is in '
        + 'contact with: WETTED_SURFACE in m2/m3, or APERTURE (2b) in m, from which it is '
        + '2/aperture. In the SKB parameterisation it is F divided by the travel time.');
    }
    const d = layerDepths(settings.MATRIX_DEPTH, nm, aw, settings.MATRIX_FIRST);
    const centre = new Float64Array(nm);
    let x = 0;
    for (let j = 0; j < nm; j++) { centre[j] = x + d[j] / 2; x += d[j]; }
    return { n: nm, d, centre, depth: settings.MATRIX_DEPTH, porosity: settings.MATRIX_POROSITY, aw };
  }

  /**
   * The optional <PARAMETERS> section: a named number that any rate law may
   * use, and that may differ from cell to cell.
   *
   *   DOSE  all  0.64                     the same everywhere
   *   DOSE  all  0.64*exp(-x/3.0e-5)      x is the cell centre, in metres
   *   DOSE  0-4  1.2                      and a later line overrides an earlier
   *
   * The expression is worked out once per cell when the model is compiled, so
   * a parameter is constant in time; `x` is the distance to the cell centre
   * and `i` its index. This is how a dose rate that dies away from a surface,
   * a porosity that varies down a column, or a rate constant that follows the
   * temperature is written -- none of which a single number can say.
   */
  function readParameters(lines, grid, geom) {
    const order = [];
    const index = new Map();
    const values = [];              // one Float64Array(cells) per parameter
    const cells = grid.n;           // the cells a line may name: those of the column
    const total = geom.length;      // the cells a value is held for: matrix included
    for (const { text, line } of lines) {
      /*
        A trailing "fracture" or "matrix" confines the line to the flowing
        water or to the rock behind it. Without either it applies to both,
        which is right for a property of the place -- a temperature, a dose
        rate -- and wrong for a source into the water, which would otherwise
        also feed every layer of rock behind that cell: with 500 m2 of rock
        per m3 of water and five metres of it, that made a unit source into a
        column deliver 5.5 units.
      */
      let scope = 'both';
      let body = text;
      const sm = /^(.*\S)\s+(fracture|matrix)$/i.exec(text);
      if (sm) { body = sm[1]; scope = sm[2].toLowerCase(); }
      const m = /^([A-Za-z_][A-Za-z0-9_]*)\s+(\S+)\s+(.+)$/.exec(body);
      if (!m) {
        throw new RtmError(`"${text}" is not "name cells value" -- for example "DOSE all 0.64", `
          + 'with "fracture" or "matrix" after it to confine it to one or the other.', line);
      }
      const [, name, where, src] = m;
      let from;
      let to;
      if (/^all$/i.test(where)) { from = 0; to = cells - 1; } else {
        const r = /^(\d+)(?:\s*-\s*(\d+))?$/.exec(where);
        if (!r) throw new RtmError(`"${where}" is not a cell, a range such as 0-9, or "all".`, line);
        from = Number(r[1]);
        to = r[2] === undefined ? from : Number(r[2]);
      }
      if (from > to) { const t = from; from = to; to = t; }
      if (to >= cells) throw new RtmError(`Cell ${to} is past the last one (${cells - 1}).`, line);

      let ast;
      try {
        ast = FacsimileModel.parseExpression(src, line);
      } catch (e) {
        throw new RtmError(`In "${src}": ${e.message.replace(/^Line \d+: /, '')}`, line);
      }
      if (!index.has(name)) {
        index.set(name, values.length);
        order.push(name);
        values.push(new Float64Array(total));
      }
      const into = values[index.get(name)];
      // A line names cells of the column; the value is worked out for each of
      // them and for every matrix layer behind it, with `j` the layer (0 in
      // the fracture) and `xm` the depth to the layer's centre in metres.
      for (let c = 0; c < total; c++) {
        const g = geom[c];
        if (g.i < from || g.i > to) continue;
        if (scope === 'fracture' && g.j > 0) continue;
        if (scope === 'matrix' && g.j === 0) continue;
        const i = g.i;
        const lookup = (id) => {
          if (id === 'x') return grid.centres[i];
          if (id === 'i') return i;
          if (id === 'j') return g.j;
          if (id === 'xm') return g.xm;
          if (index.has(id) && index.get(id) !== index.get(name)) return values[index.get(id)][c];
          return undefined;
        };
        let v;
        try {
          v = FacsimileModel.evalAst(ast, lookup, {}, line);
        } catch (e) {
          throw new RtmError(`In "${src}": ${e.message.replace(/^Line \d+: /, '')}. A parameter may `
            + 'use x (the cell centre, m), i (the cell index) and parameters named above it.', line);
        }
        if (!Number.isFinite(v)) throw new RtmError(`"${src}" is not a number in cell ${i}.`, line);
        into[c] = v;
      }
    }
    return { order, index, values };
  }

  /* ======================================================================
     2. Reactions
     ====================================================================== */

  /** `2 H2O` or `2H2O` or `H2O` -> [coefficient, name]. */
  function parseTerm(term, line) {
    const m = /^(\d+(?:\.\d+)?)?\s*(.+)$/.exec(term.trim());
    if (!m) throw new RtmError(`"${term}" is not a species with an optional coefficient.`, line);
    const name = m[2].trim();
    if (!SPECIES_NAME.test(name)) {
      throw new RtmError(`"${name}" is not a species name.`, line);
    }
    return [m[1] ? Number(m[1]) : 1, name];
  }

  /** One side of an equation: `A + 2 B`, or empty for a sink or a source. */
  function parseSide(side, line) {
    const text = side.trim();
    if (!text) return [];
    return text.split(/\s\+\s/).map((t) => parseTerm(t, line));
  }

  /**
   * One line of <REACTIONS>.
   *
   *   A + 2 B => C, k = 1.4e11                mass action, rate = k[A][B]^2
   *   A <=> B, kf = 1, kb = 0.5               both ways
   *   S => P, r = vmax*[S]/(km + [S]), vmax = 2, km = 0.1   a rate law of your own
   *
   * The commas separate the equation, the rate and any named parameters; a
   * parameter may be used by the rate law of its own line only.
   */
  function parseReaction(text, line) {
    const parts = splitTop(text).map((p) => p.trim()).filter(Boolean);
    if (!parts.length) throw new RtmError('Empty reaction.', line);
    const equation = parts.shift();

    let arrow = null;
    for (const a of ['<=>', '=>', '<=', '=']) {
      if (equation.includes(a)) { arrow = a; break; }
    }
    if (!arrow) throw new RtmError(`"${equation}" has no =>, <=> or = in it.`, line);
    let [lhs, rhs] = equation.split(arrow).map((s) => s.trim());
    if (arrow === '<=') { const t = lhs; lhs = rhs; rhs = t; }

    const reactants = parseSide(lhs, line);
    const products = parseSide(rhs, line);
    if (!reactants.length && !products.length) {
      throw new RtmError('A reaction needs a species on one side at least.', line);
    }

    const assigned = [];
    for (const part of parts) {
      const m = /^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$/.exec(part);
      if (!m) throw new RtmError(`"${part}" is not NAME = value.`, line);
      assigned.push([m[1], m[2].trim()]);
    }
    /*
      Which names are the rate and which are its parameters depends on whether
      a rate law was written at all. "r = k*[A]*[B], k = 1.9" is a law and its
      own constant -- the k there is a PARAMETER of the law, not a competing
      mass-action rate -- while "A + B => C, k = 1.9" has no law and the k is
      the mass-action constant. Deciding this the other way round is what the
      first version did, and every reaction in the example set said
      "k is neither a parameter nor a species".
    */
    const explicit = assigned.some(([key]) => key === 'r' || key === 'rb');
    const rateKeys = explicit ? ['r', 'rb'] : ['k', 'kf', 'kb'];
    const params = new Map();
    const rates = {};
    /*
      What the rate acts on. `on = water`, the default, is a rate per unit of
      pore water, which is what a rate law written in concentrations is; in a
      rock matrix only the water fraction of a cell is water, so the cell's
      inventory changes by eps_m times the rate. `on = inventory` is a rate
      that removes or makes a share of EVERYTHING in the cell, sorbed and
      dissolved alike -- radioactive decay, which does not ask where an atom
      sits. Without the distinction, decay in a sorbing matrix would run at
      eps_m/Rm of its real rate.
    */
    let whole = false;
    for (const [key, value] of assigned) {
      if (key === 'on') {
        if (/^inventory$/i.test(value)) whole = true;
        else if (!/^water$/i.test(value)) {
          throw new RtmError(`on = "${value}" is not understood: on = water (the default) or on = inventory.`, line);
        }
        continue;
      }
      if (rateKeys.includes(key)) {
        rates[key] = { src: value, line };
        continue;
      }
      const v = Number(value);
      if (!Number.isFinite(v)) {
        throw new RtmError(`Parameter ${key} = "${value}" is not a number. A rate law goes in `
          + 'r = ... ; everything else on the line is one of its constants.', line);
      }
      params.set(key, v);
    }

    const reversible = arrow === '<=>';
    if (reversible && !(rates.kf || rates.r) ) {
      throw new RtmError('A reversible reaction needs kf (and kb), or r (and rb).', line);
    }
    if (!reversible && !(rates.k || rates.r || rates.kf)) {
      throw new RtmError('A reaction needs k = ... (mass action) or r = ... (a rate law of your own).', line);
    }
    return { reactants, products, params, rates, reversible, whole, line, text };
  }

  /** Split on commas that are not inside brackets or parentheses. */
  function splitTop(text) {
    const out = [];
    let depth = 0;
    let start = 0;
    for (let i = 0; i < text.length; i++) {
      const c = text[i];
      if (c === '(' || c === '[') depth++;
      else if (c === ')' || c === ']') depth--;
      else if (c === ',' && depth === 0) { out.push(text.slice(start, i)); start = i + 1; }
    }
    out.push(text.slice(start));
    return out;
  }

  /* ======================================================================
     2b. Equilibria, and the speciation that solves them
     ====================================================================== */

  /**
   * One line of the optional <EQUILIBRIUM> section.
   *
   *   H+ + OH- <=> H2O, logK = 14
   *   CO2 + H2O <=> H2CO3, K = 1.7e-3
   *   H+ + OH- <=> H2O, logK = 14, kf = 1.4e11
   *
   * K is the constant for the reaction as written -- products over reactants,
   * each to its coefficient. `logK` is its base-ten logarithm, which is how a
   * database gives it and how anyone writing one by hand will have it.
   *
   * Given `kf` as well, the equilibrium is ALSO enforced while the run goes
   * on, as a fast reversible pair with kb = kf/K. Without it the equilibrium
   * is used for the speciation of the initial state and nothing else, because
   * these solvers integrate y' = f and an equilibrium held exactly throughout
   * is an algebraic constraint, which is a different kind of problem.
   */
  function readEquilibria(lines, index) {
    return lines.map(({ text, line }) => {
      const parts = splitTop(text).map((p) => p.trim()).filter(Boolean);
      const equation = parts.shift();
      if (!equation || !/<=>|=>|=/.test(equation)) {
        throw new RtmError(`"${text}" needs an equation with <=> in it.`, line);
      }
      const arrow = equation.includes('<=>') ? '<=>' : (equation.includes('=>') ? '=>' : '=');
      const [lhs, rhs] = equation.split(arrow).map((x) => x.trim());
      const reactants = parseSide(lhs, line);
      const products = parseSide(rhs, line);

      let lnK = null;
      let kf = null;
      for (const part of parts) {
        const m = /^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$/.exec(part);
        if (!m) throw new RtmError(`"${part}" is not NAME = value.`, line);
        const v = Number(m[2]);
        if (!Number.isFinite(v)) throw new RtmError(`${m[1]} = "${m[2]}" is not a number.`, line);
        if (m[1] === 'logK') lnK = v * Math.LN10;
        else if (m[1] === 'K') {
          if (!(v > 0)) throw new RtmError('K must be greater than zero; use logK for a small one.', line);
          lnK = Math.log(v);
        } else if (m[1] === 'kf') {
          if (!(v > 0)) throw new RtmError('kf must be greater than zero.', line);
          kf = v;
        } else throw new RtmError(`"${m[1]}" is not K, logK or kf.`, line);
      }
      if (lnK === null) throw new RtmError('An equilibrium needs K = ... or logK = ... .', line);

      const stoich = new Map();
      const bump = (name, c) => {
        if (!index.has(name)) {
          throw new RtmError(`"${name}" is used by an equilibrium but is not in <SPECIES>.`, line);
        }
        const si = index.get(name);
        stoich.set(si, (stoich.get(si) || 0) + c);
      };
      for (const [c, name] of reactants) bump(name, -c);
      for (const [c, name] of products) bump(name, +c);
      const net = [...stoich.entries()].filter(([, c]) => c !== 0);
      if (!net.length) throw new RtmError('The equilibrium changes nothing.', line);
      return { net, lnK, kf, line, text, reactants, products };
    });
  }

  /**
   * What the equilibria cannot change: a basis of the left null space of the
   * stoichiometric matrix.
   *
   * Every vector u with u.S = 0 gives a total u.C that the equilibria hold
   * fixed however they shuffle the species about -- the "components" of the
   * system. Taking them from the reactions themselves rather than from a table
   * of elements means the page needs no formula parser and no periodic table,
   * and it is right for a set that conserves something chemistry has no name
   * for, such as a surface site.
   *
   * Found by row-reducing S transpose and reading the null space off the
   * reduced form. The matrices here are small -- one row per equilibrium --
   * and their entries are little integers, so plain elimination is enough.
   *
   * @param {Array} equilibria
   * @param {number} ns
   * @returns {number[][]} one row per conserved total
   */
  function equilibriumSpecies(equilibria) {
    const seen = new Set();
    for (const eq of equilibria) for (const [si] of eq.net) seen.add(si);
    return [...seen].sort((a, b) => a - b);
  }

  function conservationBasis(equilibria, ns, fixed) {
    /*
      Only the species an equilibrium actually touches take part. Every other
      one is conserved trivially -- it is its own total -- and including it
      would put a row of the identity into the speciation, which is harmless
      until that species starts at zero: ln 0 is where the matrix goes
      singular. The rest of the chemistry is simply left where it was.

      A `fixed` species takes no part either, and for a different reason: it is
      held from outside, so a total that contains it is NOT conserved -- the
      outside is free to supply as much of it as the equilibria call for. Fix
      the H+ of a water equilibrium and charge stops being a conserved
      quantity; what is left is one relation in one unknown, which is exactly
      what a buffered pH means. So the null space is taken over the free
      species alone.
    */
    const active = new Set(equilibriumSpecies(equilibria)
      .filter((si) => !(fixed && fixed[si])));
    const ne = equilibria.length;
    // A = S transpose: one row per equilibrium, one column per species.
    const A = Array.from({ length: ne }, () => new Float64Array(ns));
    equilibria.forEach((eq, j) => {
      for (const [si, c] of eq.net) if (!(fixed && fixed[si])) A[j][si] = c;
    });

    // Row-reduce, remembering which column each pivot landed in.
    const pivotOf = [];
    let row = 0;
    for (let col = 0; col < ns && row < ne; col++) {
      let best = -1;
      let mag = 1e-12;
      for (let r = row; r < ne; r++) if (Math.abs(A[r][col]) > mag) { mag = Math.abs(A[r][col]); best = r; }
      if (best < 0) continue;
      const t = A[row]; A[row] = A[best]; A[best] = t;
      const p = A[row][col];
      for (let c = 0; c < ns; c++) A[row][c] /= p;
      for (let r = 0; r < ne; r++) {
        if (r === row) continue;
        const f = A[r][col];
        if (!f) continue;
        for (let c = 0; c < ns; c++) A[r][c] -= f * A[row][c];
      }
      pivotOf.push(col);
      row++;
    }

    // One null-space vector per free column that takes part: 1 there, and
    // minus the reduced entries at the pivot columns. A pivot column always
    // takes part, since a pivot needs a non-zero entry to land on.
    const isPivot = new Set(pivotOf);
    const basis = [];
    for (let col = 0; col < ns; col++) {
      if (isPivot.has(col) || !active.has(col)) continue;
      const u = new Float64Array(ns);
      u[col] = 1;
      pivotOf.forEach((pc, r) => { u[pc] = -A[r][col]; });
      basis.push(u);
    }
    return basis;
  }

  /**
   * Equilibrate a state: the concentrations that satisfy every equilibrium
   * while conserving every total the equilibria leave alone.
   *
   * Newton in u = ln C, which is what makes this tractable. In those variables
   * each equilibrium is LINEAR -- sum of nu*u = ln K -- and only the mass
   * balances are not, so the iteration is well conditioned over the many
   * orders of magnitude a real speciation spans, and no concentration can be
   * driven negative on the way.
   *
   * @param {object} model   from compile()
   * @param {Float64Array} [y]  the state to equilibrate; the initial one by default
   * @param {object} [opts]  { tol, maxIter, floor }
   * @returns {{y: Float64Array, cells: object[]}}
   */
  function speciate(model, y, opts = {}) {
    const eqs = model.equilibria;
    if (!eqs || !eqs.length) return { y: Float64Array.from(y || model.initialState()), cells: [] };
    const tol = opts.tol || 1e-10;
    const maxIter = opts.maxIter || 100;
    const floor = opts.floor || 1e-300;
    const ns = model.speciesNames.length;
    const out = Float64Array.from(y || model.initialState());
    const basis = model.conservation;
    const ne = eqs.length;
    const nb = basis.length;
    const cells = [];
    // The species that take part, and where each sits in the small system. A
    // fixed one is held: it appears in the equilibrium rows as a known number,
    // never as an unknown.
    const held = model.fixed || [];
    const part = equilibriumSpecies(eqs).filter((si) => !held[si]);
    const na = part.length;
    const at = new Int32Array(ns).fill(-1);
    part.forEach((si, k) => { at[si] = k; });
    if (ne + nb !== na) {
      const nheld = equilibriumSpecies(eqs).length - na;
      throw new RtmError(`The equilibria give ${ne} equations and ${nb} conserved totals, which is `
        + `${ne + nb} for the ${na} species they are free to move`
        + (nheld ? ` (${nheld} more of them are fixed)` : '')
        + '. Fixing one species of an equilibrium leaves it solvable; fixing two of the same one '
        + 'usually does not, and an equilibrium that repeats another has the same effect.');
    }

    for (let cell = 0; cell < model.cells; cell++) {
      const b = cell * ns;
      const u = new Float64Array(na);
      for (let k = 0; k < na; k++) u[k] = Math.log(Math.max(out[b + part[k]], floor));
      // The totals to hold, taken from the state as it stands.
      const totals = basis.map((v) => {
        let t = 0;
        for (let k = 0; k < na; k++) t += v[part[k]] * out[b + part[k]];
        return t;
      });

      const J = Array.from({ length: na }, () => new Float64Array(na));
      const F = new Float64Array(na);
      let converged = false;
      let iter = 0;
      let norm = Infinity;
      for (; iter < maxIter; iter++) {
        const C = new Float64Array(na);
        for (let k = 0; k < na; k++) C[k] = Math.exp(u[k]);
        // Equilibrium rows: linear in u, so the Jacobian is the stoichiometry.
        for (let j = 0; j < ne; j++) {
          let r = -eqs[j].lnK;
          J[j].fill(0);
          for (const [si, c] of eqs[j].net) {
            // A held species contributes a constant, and no column.
            if (at[si] < 0) { r += c * Math.log(Math.max(out[b + si], floor)); continue; }
            r += c * u[at[si]];
            J[j][at[si]] = c;
          }
          F[j] = r;
        }
        // Mass-balance rows: d(sum v C)/du_i = v_i C_i.
        for (let k = 0; k < nb; k++) {
          const rowI = ne + k;
          let r = -totals[k];
          J[rowI].fill(0);
          for (let i = 0; i < na; i++) {
            r += basis[k][part[i]] * C[i];
            J[rowI][i] = basis[k][part[i]] * C[i];
          }
          F[rowI] = r;
        }
        norm = 0;
        for (let i = 0; i < na; i++) norm = Math.max(norm, Math.abs(F[i]));
        if (norm < tol) { converged = true; break; }
        const step = solveDense(J, F, na);
        if (!step) throw new RtmError(`The speciation matrix is singular in cell ${cell}.`);
        // Damped, and capped: an undamped step in log space can move a
        // concentration by e^40 and leave the iteration nowhere near where it
        // started. Two is the usual cap and behaves well here.
        let damp = 1;
        for (let i = 0; i < na; i++) damp = Math.min(damp, 2 / Math.max(Math.abs(step[i]), 2));
        for (let i = 0; i < na; i++) u[i] -= damp * step[i];
      }
      for (let k = 0; k < na; k++) out[b + part[k]] = Math.exp(u[k]);
      cells.push({ cell, converged, iterations: iter, residual: norm });
    }
    return { y: out, cells };
  }

  /** Gaussian elimination with partial pivoting; null when singular. */
  function solveDense(A, rhs, n) {
    const M = A.map((row) => Float64Array.from(row));
    const x = Float64Array.from(rhs);
    for (let col = 0; col < n; col++) {
      let best = col;
      for (let r = col + 1; r < n; r++) if (Math.abs(M[r][col]) > Math.abs(M[best][col])) best = r;
      if (Math.abs(M[best][col]) < 1e-300) return null;
      if (best !== col) {
        const t = M[col]; M[col] = M[best]; M[best] = t;
        const tv = x[col]; x[col] = x[best]; x[best] = tv;
      }
      const p = M[col][col];
      for (let r = col + 1; r < n; r++) {
        const f = M[r][col] / p;
        if (!f) continue;
        for (let c = col; c < n; c++) M[r][c] -= f * M[col][c];
        x[r] -= f * x[col];
      }
    }
    for (let r = n - 1; r >= 0; r--) {
      let sum = x[r];
      for (let c = r + 1; c < n; c++) sum -= M[r][c] * x[c];
      x[r] = sum / M[r][r];
    }
    return x;
  }

  /* ======================================================================
     3. Rate laws: parsing, and differentiating them
     ====================================================================== */

  /*
    A rate law mentions species in brackets. The brackets are swapped for a
    plain identifier before parsing, because the expression parser borrowed
    from facsimile-model.js reads programming identifiers -- and a chemical
    name is not one. `names` maps the identifier back to the species.
  */
  function maskSpecies(src, line) {
    const names = new Map();
    const masked = String(src).replace(/\[([^\]]*)\]/g, (_, inner) => {
      const name = inner.trim();
      if (!SPECIES_NAME.test(name)) {
        throw new RtmError(`"[${inner}]" is not a species name.`, line);
      }
      const id = `S_${names.size}__`;
      names.set(id, name);
      return id;
    });
    return { masked, names };
  }

  const NUM = (v) => ({ type: 'num', v });
  const isNum = (n, v) => n.type === 'num' && n.v === v;

  /** a + b, a * b and so on, folded when both sides are known. */
  function add(a, b) {
    if (isNum(a, 0)) return b;
    if (isNum(b, 0)) return a;
    if (a.type === 'num' && b.type === 'num') return NUM(a.v + b.v);
    return { type: 'bin', op: '+', l: a, r: b };
  }
  function sub(a, b) {
    if (isNum(b, 0)) return a;
    if (a.type === 'num' && b.type === 'num') return NUM(a.v - b.v);
    return { type: 'bin', op: '-', l: a, r: b };
  }
  function mul(a, b) {
    if (isNum(a, 0) || isNum(b, 0)) return NUM(0);
    if (isNum(a, 1)) return b;
    if (isNum(b, 1)) return a;
    if (a.type === 'num' && b.type === 'num') return NUM(a.v * b.v);
    return { type: 'bin', op: '*', l: a, r: b };
  }
  function div(a, b) {
    if (isNum(a, 0)) return NUM(0);
    if (isNum(b, 1)) return a;
    if (a.type === 'num' && b.type === 'num') return NUM(a.v / b.v);
    return { type: 'bin', op: '/', l: a, r: b };
  }
  function pow(a, b) {
    if (isNum(b, 1)) return a;
    if (isNum(b, 0)) return NUM(1);
    return { type: 'bin', op: '**', l: a, r: b };
  }

  /**
   * d(node)/d(id), symbolically.
   *
   * Only the operators a rate law uses. An unknown function is an error rather
   * than a silent zero: a Jacobian that is quietly wrong costs far more to find
   * than one that refuses to compile.
   */
  function derivative(node, id, line) {
    switch (node.type) {
      case 'num': return NUM(0);
      case 'id': return NUM(node.name === id ? 1 : 0);
      case 'neg': return { type: 'neg', a: derivative(node.a, id, line) };
      case 'bin': {
        const { l, r, op } = node;
        const dl = derivative(l, id, line);
        const dr = derivative(r, id, line);
        if (op === '+') return add(dl, dr);
        if (op === '-') return sub(dl, dr);
        if (op === '*') return add(mul(dl, r), mul(l, dr));
        if (op === '/') return div(sub(mul(dl, r), mul(l, dr)), pow(r, NUM(2)));
        if (op === '**') {
          // A constant exponent is the only case a rate law needs, and the
          // general one would need log(base) -- undefined at a zero
          // concentration, which is exactly where these are evaluated.
          if (r.type !== 'num') {
            throw new RtmError('A power in a rate law needs a plain number as its exponent.', line);
          }
          if (isNum(dl, 0)) return NUM(0);
          return mul(mul(NUM(r.v), pow(l, NUM(r.v - 1))), dl);
        }
        throw new RtmError(`Cannot differentiate "${op}".`, line);
      }
      case 'call': {
        const a = node.args[0];
        const da = a ? derivative(a, id, line) : NUM(0);
        switch (node.name) {
          case 'exp': return mul(node, da);
          case 'log': case 'ln': return div(da, a);
          case 'log10': return div(da, mul(a, NUM(Math.LN10)));
          case 'sqrt': return div(da, mul(NUM(2), { type: 'call', name: 'sqrt', args: [a] }));
          case 'abs': return mul({ type: 'call', name: 'sign', args: [a] }, da);
          // A step, a ramp and a sign are flat wherever they are
          // differentiable; the kink contributes nothing, which is what the
          // solvers are told.
          case 'step': case 'sign': return NUM(0);
          case 'ramp': return mul({ type: 'call', name: 'step', args: [a] }, da);
          // These three have honest derivatives; it is this use of them that
          // does not. Both may still be written in <PARAMETERS>, which is
          // worked out once when the model compiles and never differentiated.
          case 'min': case 'max':
            throw new RtmError(`"${node.name}" cannot be used in a rate law: its derivative jumps `
              + 'where the two arguments cross, so the Jacobian would be wrong on one side of '
              + 'the crossing. Use it in <PARAMETERS> instead, or write the rate as two '
              + 'reactions.', line);
          case 'pow':
            throw new RtmError('"pow" cannot be used in a rate law: differentiating it needs the '
              + 'logarithm of the base, which is undefined at a zero concentration -- exactly '
              + 'where a rate law is evaluated. Write [A]^2, with a plain number as the '
              + 'exponent.', line);
          default:
            throw new RtmError(`"${node.name}" is not a function this page knows.`, line);
        }
      }
      default:
        throw new RtmError(`Cannot differentiate a ${node.type}.`, line);
    }
  }

  /** The species identifiers an expression actually mentions. */
  function mentioned(node, into = new Set()) {
    if (!node || typeof node !== 'object') return into;
    if (node.type === 'id') into.add(node.name);
    if (node.l) mentioned(node.l, into);
    if (node.r) mentioned(node.r, into);
    if (node.a) mentioned(node.a, into);
    if (node.args) node.args.forEach((x) => mentioned(x, into));
    return into;
  }

  /** JavaScript for an expression tree. `resolve` names each identifier. */
  function emit(node, resolve, line) {
    switch (node.type) {
      case 'num': return numberLiteral(node.v);
      case 'id': return resolve(node.name, line);
      case 'neg': return `(-${emit(node.a, resolve, line)})`;
      case 'bin': {
        const l = emit(node.l, resolve, line);
        const r = emit(node.r, resolve, line);
        if (node.op === '**') return `Math.pow(${l}, ${r})`;
        return `(${l} ${node.op} ${r})`;
      }
      case 'call': {
        const args = node.args.map((a) => emit(a, resolve, line)).join(', ');
        const fn = { ln: 'Math.log', log: 'Math.log', log10: 'Math.log10', exp: 'Math.exp',
          sqrt: 'Math.sqrt', abs: 'Math.abs', sign: 'Math.sign' }[node.name];
        if (fn) return `${fn}(${args})`;
        if (node.name === 'step') return `(${args} > 0 ? 1 : 0)`;
        if (node.name === 'ramp') return `Math.max(${args}, 0)`;
        // Emittable but not differentiable: derivative() is what refuses
        // these, and it can say why and where they do work.
        const two = { min: 'Math.min', max: 'Math.max', pow: 'Math.pow' }[node.name];
        if (two) return `${two}(${args})`;
        throw new RtmError(`"${node.name}" is not a function this page knows.`, line);
      }
      default:
        throw new RtmError(`Cannot emit a ${node.type}.`, line);
    }
  }

  /** A literal that reads back as exactly this double. */
  function numberLiteral(v) {
    if (!Number.isFinite(v)) throw new RtmError(`${v} is not a finite number.`);
    const s = String(v);
    return Number(s) === v ? (v < 0 ? `(${s})` : s) : `${v.toExponential(17)}`;
  }

  /* ======================================================================
     4. The grid, and the transport stencil
     ====================================================================== */

  /**
   * Cell centres and widths.
   *
   * A log grid puts the cells close together at the left-hand boundary, which
   * is where a dissolving surface puts all of the interesting chemistry; a
   * linear one spaces them evenly. Either way the transport below is written
   * for an uneven grid, so neither is a special case.
   */
  function makeGrid(settings) {
    const n = settings.MODE === 'transport' ? settings.CELLS : 1;
    const L = settings.LENGTH;
    const centres = new Float64Array(n);
    if (n === 1) { centres[0] = 0; return { n, centres, width: Float64Array.of(L || 1), L }; }
    if (settings.GRID === 'log') {
      // Geometric widths, normalised to the length. The first face is at zero.
      const ratio = Math.pow(1000, 1 / (n - 1));
      const w = new Float64Array(n);
      let total = 0;
      for (let i = 0; i < n; i++) { w[i] = Math.pow(ratio, i); total += w[i]; }
      let x = 0;
      for (let i = 0; i < n; i++) { w[i] *= L / total; centres[i] = x + w[i] / 2; x += w[i]; }
      return { n, centres, width: w, L };
    }
    const dx = L / n;
    const w = new Float64Array(n).fill(dx);
    for (let i = 0; i < n; i++) centres[i] = (i + 0.5) * dx;
    return { n, centres, width: w, L };
  }

  /* ======================================================================
     5. Compiling
     ====================================================================== */

  /**
   * Compile a model text.
   *
   * @param {string} text
   * @returns {object} a model FacsimileODE.runModel can integrate
   */
  function compile(text) {
    if (!FacsimileModel) throw new RtmError('facsimile-model.js is not loaded; it provides the expression parser.');
    const sections = readSections(text);
    const settings = readSettings(sections.SETTINGS);
    const species = readSpecies(sections.SPECIES);
    const reactions = sections.REACTIONS.map(({ text: t, line }) => parseReaction(t, line));

    const grid = makeGrid(settings);
    const matrix = makeMatrix(settings);
    /*
      THE CELLS. A plain column has grid.n of them. With a rock matrix each
      of those -- a fracture cell, the flowing water -- is followed in the
      state by the nm stagnant layers behind it, so cell (i, j) sits at
      i*(1+nm) + j, j = 0 being the fracture. That keeps a fracture cell and
      its own matrix chain contiguous, which is where nearly all the coupling
      is, and it is the numbering SKB's FARFCOMP uses, so an inventory can be
      compared position by position.
    */
    const nf = grid.n;
    const nm = matrix ? matrix.n : 0;
    const stride = 1 + nm;
    const cellOf = (i, j) => i * stride + j;
    const geom = [];
    for (let i = 0; i < nf; i++) {
      geom.push({ i, j: 0, x: grid.centres[i], xm: 0 });
      for (let j = 1; j <= nm; j++) geom.push({ i, j, x: grid.centres[i], xm: matrix.centre[j - 1] });
    }
    const params = readParameters(sections.PARAMETERS, grid, geom);
    const ns = species.length;
    const index = new Map(species.map((s, i) => [s.name, i]));
    const nameOf = species.map((s) => s.name);
    const warnings = [];

    const needSpecies = (name, line) => {
      if (!index.has(name)) {
        throw new RtmError(`"${name}" is used by a reaction but is not in <SPECIES>.`, line);
      }
      return index.get(name);
    };

    /* ---- the rate laws, as trees ------------------------------------- */
    // Each reaction becomes one or two "channels": a forward one, and a
    // backward one when it is reversible. A channel has a rate and the net
    // change it makes to each species.
    const channels = [];
    for (const rx of reactions) {
      const stoich = new Map();
      const bump = (i, c) => stoich.set(i, (stoich.get(i) || 0) + c);
      for (const [c, name] of rx.reactants) bump(needSpecies(name, rx.line), -c);
      for (const [c, name] of rx.products) bump(needSpecies(name, rx.line), +c);
      const net = [...stoich.entries()].filter(([, c]) => c !== 0);
      if (!net.length) warnings.push(`Line ${rx.line}: the reaction changes nothing.`);

      const build = (spec, side, sign) => {
        // Mass action: the rate is k times each reactant to its coefficient.
        let src;
        if (spec.kind === 'k') {
          const terms = side.map(([c, name]) => (c === 1 ? `[${name}]` : `[${name}]**${c}`));
          src = terms.length ? `(${spec.src}) * ${terms.join(' * ')}` : `(${spec.src})`;
        } else {
          src = spec.src;
        }
        const { masked, names } = maskSpecies(src, rx.line);
        let ast;
        try {
          ast = FacsimileModel.parseExpression(masked, rx.line);
        } catch (e) {
          throw new RtmError(`In the rate "${src}": ${e.message.replace(/^Line \d+: /, '')}`, rx.line);
        }
        // Every identifier is either a masked species or a parameter of this line.
        const deps = [];
        const seen = new Set();
        for (const id of mentioned(ast)) {
          if (names.has(id)) {
            const si = needSpecies(names.get(id), rx.line);
            if (!seen.has(id)) { seen.add(id); deps.push({ id, si }); }
          } else if (!rx.params.has(id) && !params.index.has(id)) {
            throw new RtmError(`"${id}" in a rate law is not a parameter of this reaction, a `
              + 'parameter in <PARAMETERS>, or a species in brackets. Write a concentration '
              + 'as [name].', rx.line);
          }
        }
        deps.sort((a, b) => a.si - b.si);
        return {
          ast,
          deps,
          params: rx.params,
          line: rx.line,
          whole: !!rx.whole, net: net.map(([i, c]) => [i, c * sign]),
        };
      };

      if (rx.reversible) {
        const f = rx.rates.kf ? { kind: 'k', src: rx.rates.kf.src } : { kind: 'r', src: rx.rates.r.src };
        channels.push(build(f, rx.reactants, +1));
        const bspec = rx.rates.kb ? { kind: 'k', src: rx.rates.kb.src }
          : (rx.rates.rb ? { kind: 'r', src: rx.rates.rb.src } : null);
        if (bspec) channels.push(build(bspec, rx.products, -1));
        else warnings.push(`Line ${rx.line}: <=> with no backward rate runs forwards only.`);
      } else if (rx.rates.r) {
        channels.push(build({ kind: 'r', src: rx.rates.r.src }, rx.reactants, +1));
      } else {
        const spec = rx.rates.k || rx.rates.kf;
        channels.push(build({ kind: 'k', src: spec.src }, rx.reactants, +1));
      }
    }

    /*
      The equilibria. Those given a kf are ALSO enforced while the run goes on,
      as an ordinary reversible pair with kb = kf/K -- fast kinetics, which
      these solvers are built for, rather than a constraint, which they are
      not. Without a kf an equilibrium is used for speciation and nothing else.
    */
    const equilibria = readEquilibria(sections.EQUILIBRIUM, index);
    for (const eq of equilibria) {
      if (eq.kf === null) continue;
      const kb = eq.kf / Math.exp(eq.lnK);
      const net = eq.net.map(([i, c]) => [i, c]);
      const mk = (side, sign, k) => {
        const terms = side.map(([c, name]) => (c === 1 ? `[${name}]` : `[${name}]**${c}`));
        const src = terms.length ? `(${k}) * ${terms.join(' * ')}` : `(${k})`;
        const { masked, names } = maskSpecies(src, eq.line);
        const ast = FacsimileModel.parseExpression(masked, eq.line);
        const deps = [];
        const seen = new Set();
        for (const id of mentioned(ast)) {
          if (!names.has(id)) continue;
          if (seen.has(id)) continue;
          seen.add(id);
          deps.push({ id, si: index.get(names.get(id)) });
        }
        deps.sort((a, b) => a.si - b.si);
        return { ast, deps, params: new Map(), line: eq.line, whole: false, net: net.map(([i, c]) => [i, c * sign]) };
      };
      channels.push(mk(eq.reactants, +1, numberLiteral(eq.kf)));
      channels.push(mk(eq.products, -1, numberLiteral(kb)));
    }

    /* ---- generated code: the rates and their derivatives -------------- */
    // One function, compiled once, run per cell. `y` is the whole state and
    // `b` the first index of this cell, so no slicing or copying happens.
    const body = [];
    const derivIndex = [];      // where each channel's derivatives start in D
    let nd = 0;
    channels.forEach((ch, j) => {
      const resolve = (id, line) => {
        const dep = ch.deps.find((d) => d.id === id);
        if (dep) return `y[b + ${dep.si}]`;
        // A constant of this line beats a global of the same name: it is the
        // more local thing to have written, and the one being looked at.
        if (ch.params.has(id)) return numberLiteral(ch.params.get(id));
        if (params.index.has(id)) return `P[pb + ${params.index.get(id)}]`;
        throw new RtmError(`"${id}" is not known here.`, line);
      };
      body.push(`  R[${j}] = ${emit(ch.ast, resolve, ch.line)};`);
      derivIndex.push(nd);
      for (const dep of ch.deps) {
        const d = derivative(ch.ast, dep.id, ch.line);
        body.push(`  D[${nd}] = ${emit(d, resolve, ch.line)};`);
        nd++;
      }
    });
    let rates;
    try {
      // eslint-disable-next-line no-new-func
      rates = new Function('y', 'b', 'P', 'pb', 'R', 'D', body.join('\n'));
    } catch (e) {
      throw new RtmError(`The generated rate code did not compile: ${e.message}`);
    }

    /* ---- the grid and what moves --------------------------------------- */
    const nc = nf * stride;         // every cell, matrix layers included
    const transport = settings.MODE === 'transport';
    const peclet = transport && settings.ADVECTION && settings.PECLET > 0 ? settings.PECLET : 0;
    const mobile = species.map((s) => (transport && !s.fixed
      && ((settings.DIFFUSION && (s.D > 0 || peclet > 0))
        || (settings.ADVECTION && settings.VELOCITY !== 0))));
    // Which species cross into the rock: those with a matrix diffusivity.
    const enters = species.map((s) => !!matrix && !s.fixed && s.Dm > 0);
    if (transport && !mobile.some(Boolean)) {
      warnings.push('Transport is on but nothing moves: give a species D = ... , or set a VELOCITY.');
    }
    if (matrix && !enters.some(Boolean)) {
      warnings.push('There is a rock matrix but nothing diffuses into it: give a species Dm = ..., '
        + 'its effective diffusivity in the rock, in m2/s.');
    }
    /*
      NUMERICAL DISPERSION AGAINST THE REAL THING.

      First-order upwinding spreads a front by u*dz/2 whether or not it is
      asked to, which over a column of nf equal cells is the same as a Peclet
      number of 2*nf. Two ways that can be more than the model wants, and both
      are worth saying, because neither shows up as anything but a front that
      is too smooth:

        with PECLET   the correction u*L/Pe - u*dz/2 would have to be negative
                      to sharpen the front back up, and it is floored at zero,
                      so the column disperses as 2*nf rather than as Pe.

        without it    each species has its own D, and the same u*dz/2 is added
                      to it by the scheme. Where that is an appreciable part
                      of D -- a grid Peclet number u*dz/D above about 2 -- the
                      answer is more dispersive than the D says, and the fix
                      is the same: more cells.
    */
    if (peclet > 0 && 2 * nf < peclet) {
      warnings.push(`${nf} cells disperse as a Peclet number of ${2 * nf} would, and PECLET = ${peclet} `
        + 'was asked for: the upwind scheme spreads a front by v*dz/2 on its own, more than the '
        + `setting wants, and the correction that would sharpen it cannot be negative. ${Math.ceil(peclet / 2)} `
        + 'cells (Pe/2) is the fewest that reaches it.');
    }
    if (transport && !peclet && settings.ADVECTION && settings.VELOCITY !== 0 && settings.DIFFUSION) {
      const u = Math.abs(settings.VELOCITY) / (settings.POROSITY > 0 ? settings.POROSITY : 1);
      const dz = grid.L / nf;
      const added = (u * dz) / 2;
      // The worst offender: the mobile species whose own D is smallest beside
      // what the grid adds. One line however many species are in that state.
      let worst = null;
      for (let si = 0; si < ns; si++) {
        if (!mobile[si] || !(species[si].D > 0)) continue;
        if (!worst || species[si].D < worst.D) worst = species[si];
      }
      if (worst && added > worst.D) {
        const need = Math.ceil((u * grid.L) / (2 * worst.D));
        warnings.push(`The grid disperses more than ${worst.name} does: upwinding adds v*dz/2 = `
          + `${added.toExponential(2)} where its D is ${worst.D.toExponential(2)}, so the front is `
          + `spread by the discretisation rather than by the model. ${need} cells would bring the `
          + 'numerical part below D; a coarser grid is more dispersive, not less.');
      }
    }
    const fixed = species.map((s) => !!s.fixed);
    const n = ns * nc;

    /*
      THE MASS MATRIX, M dC/dt = f.

      Diagonal, which is what reactive transport uses it for: a retardation
      factor for a sorbing species, a porosity, a water content. Held as its
      reciprocal per (cell, species), so the right-hand side and the Jacobian
      rows are scaled by a multiply rather than a divide.

      A zero or negative entry is refused. Zero would make that equation
      algebraic -- a differential-algebraic system -- and the solvers here
      integrate y' = f and nothing else; pretending otherwise would give an
      answer that looked fine and was not. Equilibrium, which is the reason
      anyone wants a singular M, has its own section instead.
    */
    const invMass = new Float64Array(n).fill(1);
    let anyMass = false;
    for (let si = 0; si < ns; si++) {
      // In the fracture the coefficient is R (mass); in the rock it is Rm, the
      // matrix capacity eps_m + rho*Kd, and a species that says nothing about
      // its Rm has the porosity alone -- the capacity of one that does not
      // sorb. Both may name a parameter, so either can vary from cell to cell.
      const specF = species[si].mass;
      const specM = species[si].Rm !== null ? species[si].Rm : (matrix ? String(matrix.porosity) : null);
      if (specF === null && specM === null) continue;
      anyMass = true;
      for (let c = 0; c < nc; c++) {
        const inRock = geom[c].j > 0;
        const spec = inRock ? specM : specF;
        if (spec === null) continue;
        const asNumber = Number(spec);
        let v;
        if (Number.isFinite(asNumber)) v = asNumber;
        else if (params.index.has(spec)) v = params.values[params.index.get(spec)][c];
        else {
          throw new RtmError(`${inRock ? 'Rm' : 'mass'} = "${spec}" for ${species[si].name} is neither `
            + 'a number nor a parameter in <PARAMETERS>.', species[si].line);
        }
        if (!(v > 0)) {
          throw new RtmError(`${inRock ? 'Rm' : 'mass'} = ${v} for ${species[si].name}`
            + (nc > 1 ? ` in cell ${geom[c].i}${inRock ? `, layer ${geom[c].j}` : ''}` : '')
            + ' must be greater than zero. A zero would make that equation algebraic, which these '
            + 'solvers do not integrate; use <EQUILIBRIUM> for that.', species[si].line);
        }
        invMass[c * ns + si] = 1 / v;
      }
    }
    /*
      WHAT A REACTION DOES IN THE ROCK. Concentrations are per unit pore water
      everywhere, and so are the rate laws. A unit volume of rock holds only
      eps_m of water, so a rate r per unit water changes the rock's inventory
      by eps_m*r -- and it is the inventory, Rm*C, that the matrix equation is
      written for. Hence the porosity on the chemistry of a matrix cell:
      Rm dC/dt = eps_m * r + diffusion. The fracture is all water, factor one.
    */
    const reactScale = new Float64Array(nc).fill(1);
    if (matrix) for (let c = 0; c < nc; c++) if (geom[c].j > 0) reactScale[c] = matrix.porosity;
    // The capacity itself, for a rate that acts on the whole inventory: its
    // term is multiplied by this so that the division by invMass at the end
    // leaves it as a rate on the concentration, R dC/dt = -lambda*R*C.
    const massOf = Float64Array.from(invMass, (v) => 1 / v);

    // Cell-major, like the state, so one base index serves both.
    const np = params.order.length;
    const P = new Float64Array(Math.max(np * nc, 1));
    for (let i = 0; i < nc; i++) {
      for (let k = 0; k < np; k++) P[i * np + k] = params.values[k][i];
    }

    /* ---- the sparsity pattern ------------------------------------------ */
    // Built as a set of (row, col) per column, then compressed. The chemistry
    // contributes within a cell; transport contributes the same species in the
    // neighbouring cells.
    const cols = Array.from({ length: n }, () => new Set());
    const touch = (row, col) => cols[col].add(row);
    for (let i = 0; i < nc; i++) {
      const b = i * ns;
      for (const ch of channels) {
        for (const [p] of ch.net) {
          if (fixed[p]) continue;
          for (const dep of ch.deps) touch(b + p, b + dep.si);
        }
      }
      for (let s = 0; s < ns; s++) {
        // Every state gets a diagonal: a fixed species has a zero row and the
        // iteration matrix I - hJ still needs the 1 on its diagonal, and a
        // solver may ask for the entry whatever its value.
        touch(b + s, b + s);
        const g = geom[i];
        if (g.j === 0) {
          // Along the fracture, to the neighbouring fracture cells.
          if (mobile[s]) {
            if (g.i > 0) touch(b + s, cellOf(g.i - 1, 0) * ns + s);
            if (g.i < nf - 1) touch(b + s, cellOf(g.i + 1, 0) * ns + s);
          }
          // ...and into the first layer of rock behind it.
          if (enters[s]) touch(b + s, cellOf(g.i, 1) * ns + s);
        } else if (enters[s]) {
          // A layer sees the one in front of it (the fracture when j = 1) and
          // the one behind, and nothing else: no diffusion between the rock
          // behind one fracture cell and the rock behind the next.
          touch(b + s, cellOf(g.i, g.j - 1) * ns + s);
          if (g.j < nm) touch(b + s, cellOf(g.i, g.j + 1) * ns + s);
        }
      }
    }
    const colPtr = new Int32Array(n + 1);
    for (let c = 0; c < n; c++) colPtr[c + 1] = colPtr[c] + cols[c].size;
    const nnz = colPtr[n];
    const rowIdx = new Int32Array(nnz);
    for (let c = 0; c < n; c++) {
      const rows = [...cols[c]].sort((a, b2) => a - b2);
      rows.forEach((r, k) => { rowIdx[colPtr[c] + k] = r; });
    }
    // Which row each value in the pattern belongs to, for scaling by the mass
    // matrix: the pattern is stored by column, so the row is not implicit.
    const rowOfSlot = rowIdx;

    /** Where (row, col) sits in the value array. */
    const slot = (row, col) => {
      let lo = colPtr[col];
      let hi = colPtr[col + 1] - 1;
      while (lo <= hi) {
        const mid = (lo + hi) >> 1;
        if (rowIdx[mid] === row) return mid;
        if (rowIdx[mid] < row) lo = mid + 1; else hi = mid - 1;
      }
      throw new RtmError(`No room in the pattern for (${row}, ${col}).`);
    };

    /* ---- the transport coefficients, worked out once ------------------- */
    // Finite volume: the flux between two cells over the distance between
    // their centres, divided by the width of the cell it lands in. On an even
    // grid this is the textbook D/dx^2 [1, -2, 1]; on an uneven one it stays
    // conservative, which the textbook form does not.
    const flowIn = [];    // {row, col, value} for the Jacobian and the rhs
    const boundary = [];  // {row, value} a face feeding a cell at a stated rate
    /*
      WHAT EACH KIND OF FACE DOES, as a flux through it.

      dirichlet  the face is held at a stated concentration. Diffusion sees
                 that concentration half a cell away, D*(cb - C)/d, and the
                 flow, if there is any, carries cb in. It is the first-type
                 condition, and it puts in more than the flow alone: the
                 diffusive term is there whether or not the water is moving.

      neumann    nothing crosses the face. The second-type condition, with a
                 gradient of zero.

      robin      the flow carries cb in and NOTHING ELSE crosses: the total
      (cauchy)   flux through the face is u*cb, prescribed. That is the
                 third-type condition of the transport literature, and
                 Danckwerts' inlet -- the dispersive flux on the inside of the
                 face is what makes the concentration just inside the column
                 lower than cb, rather than something added on top of it. It
                 is the one that conserves mass at an inlet, and the one to
                 use where the boundary is water arriving at a stated
                 concentration rather than a reservoir held at one.

      free       zero gradient: no diffusion across the face, and the flow
      (outflow)  takes what it takes. Danckwerts' outlet, and the companion of
                 robin at the other end of a column. It asks for nothing to be
                 known about what is beyond the face, which is the point of
                 it -- at an outlet there is nothing to know.

      As fluxes, `free` and `neumann` come to the same arithmetic: the
      advective outflow below is applied at every cell whatever the face is,
      so a Neumann outlet already lets the flow leave. They are kept apart
      because they say different things and are wrong in different ways, and
      the warnings below can only be written if the page knows which was
      meant.
    */
    const inflowSide = (side) => (side === 'LEFT'
      ? settings.ADVECTION && settings.VELOCITY > 0
      : settings.ADVECTION && settings.VELOCITY < 0);
    for (const side of ['LEFT', 'RIGHT']) {
      const kind = settings[side];
      const face = side.toLowerCase();
      if (!transport) continue;
      if (kind === 'robin' && !inflowSide(side)) {
        warnings.push(`The ${face} face is robin, which is the flow carrying a concentration in, `
          + 'but nothing flows in there: set ADVECTION and a VELOCITY pointing inwards, or the '
          + 'face behaves as neumann.');
      }
      if (kind === 'free' && inflowSide(side)) {
        warnings.push(`The ${face} face is free, which lets whatever reaches it leave, but the `
          + 'flow points into the model there. Nothing will come in through it.');
      }
      if (kind === 'free' && !settings.ADVECTION) {
        warnings.push(`The ${face} face is free, but with no advection there is nothing to carry `
          + 'anything out of it: it holds everything in, as neumann does.');
      }
    }
    // What the rock does, per species that enters it, kept so that a test can
    // put it beside SKB's own numbers term for term.
    const dual = matrix ? { aw: matrix.aw, porosity: matrix.porosity, d: Array.from(matrix.d),
      advF: null, dF: null, species: [] } : null;
    if (transport) {
      const v = settings.ADVECTION ? settings.VELOCITY : 0;
      const por = settings.POROSITY > 0 ? settings.POROSITY : 1;
      const u = v / por;
      for (let s = 0; s < ns; s++) {
        if (!mobile[s]) continue;
        const Dspecies = settings.DIFFUSION ? species[s].D : 0;
        for (let i = 0; i < nf; i++) {
          const row = cellOf(i, 0) * ns + s;
          const w = grid.width[i];
          /*
            The dispersion. A Peclet number gives every species the same
            hydrodynamic dispersion u*L/Pe along the fracture, on top of its
            own D. The upwind scheme already spreads a front by u*dz/2 -- as
            if Pe were 2*N -- so that much is taken back, and never below
            zero: SKB's rule, adv*(N/Pe - 1/2), in coefficients rather than
            rates. Without a Peclet number the species' own D stands, and the
            numerical part is simply there, as it is on every upwind grid.
          */
          const disp = peclet > 0 ? Math.max(0, (Math.abs(u) * grid.L) / peclet - (Math.abs(u) * w) / 2) : 0;
          const D = Dspecies + disp;
          if (dual && dual.advF === null && u !== 0) { dual.advF = Math.abs(u) / w; dual.dF = disp / (w * w); }
          // --- the face to the left ---
          if (i > 0) {
            const d = grid.centres[i] - grid.centres[i - 1];
            const g = D / (d * w);
            if (g) { flowIn.push({ row, col: cellOf(i - 1, 0) * ns + s, value: g }); flowIn.push({ row, col: row, value: -g }); }
          } else if (settings.LEFT === 'dirichlet') {
            // robin and free put no diffusive flux through the face at all:
            // the first prescribes the total flux, the second the gradient.
            const d = grid.centres[0] - 0;
            const g = D / (d * w);
            const cb = species[s].left == null ? species[s].initial : species[s].left;
            if (g) { flowIn.push({ row, col: row, value: -g }); boundary.push({ row, value: g * cb }); }
          }
          // --- the face to the right ---
          if (i < nf - 1) {
            const d = grid.centres[i + 1] - grid.centres[i];
            const g = D / (d * w);
            if (g) { flowIn.push({ row, col: cellOf(i + 1, 0) * ns + s, value: g }); flowIn.push({ row, col: row, value: -g }); }
          } else if (settings.RIGHT === 'dirichlet') {
            const d = grid.L - grid.centres[nf - 1];
            const g = D / (d * w);
            const cb = species[s].right == null ? species[s].initial : species[s].right;
            if (g) { flowIn.push({ row, col: row, value: -g }); boundary.push({ row, value: g * cb }); }
          }
          // --- advection, upwind ---
          if (v !== 0) {
            const a = u / w;
            if (v > 0) {
              if (i > 0) flowIn.push({ row, col: cellOf(i - 1, 0) * ns + s, value: a });
              else if (settings.LEFT === 'dirichlet' || settings.LEFT === 'robin') {
                const cb = species[s].left == null ? species[s].initial : species[s].left;
                boundary.push({ row, value: a * cb });
              }
              flowIn.push({ row, col: row, value: -a });
            } else {
              if (i < nf - 1) flowIn.push({ row, col: cellOf(i + 1, 0) * ns + s, value: -a });
              else if (settings.RIGHT === 'dirichlet' || settings.RIGHT === 'robin') {
                const cb = species[s].right == null ? species[s].initial : species[s].right;
                boundary.push({ row, value: -a * cb });
              }
              flowIn.push({ row, col: row, value: a });
            }
          }
        }
      }

      /*
        INTO THE ROCK. Finite volume again, per unit area of fracture wall.

        The fracture loses to the first layer at 2*De/d1 per unit wall area
        -- the layer's centre is half its thickness from the wall -- and per
        unit of its own water that is aw times as much, aw being the wall
        area a unit volume of water touches. The layer gains the same flux
        per unit area; per unit of rock that is divided by its own thickness.
        Layer to layer, the conductance is 2*De over the distance between
        centres, d_j + d_j+1, divided by the losing layer's thickness. The
        far face of the last layer is closed: the depth is a depth, not a
        boundary. Every one of these rows is then divided by its cell's
        capacity -- R in the fracture, Rm in the rock -- by invMass, which is
        what turns these coefficients into SKB's rates term for term.
      */
      if (matrix) {
        const d = matrix.d;
        const aw = matrix.aw;
        for (let s = 0; s < ns; s++) {
          if (!enters[s]) continue;
          const De = species[s].Dm;
          const rates = { name: species[s].name, diffFM1: (aw * 2 * De) / d[0],
            diffM1F: (2 * De) / (d[0] * d[0]), diffMMF: [], diffMMB: [] };
          for (let j = 0; j < nm - 1; j++) {
            rates.diffMMF.push((2 * De) / (d[j] * (d[j] + d[j + 1])));
            rates.diffMMB.push((2 * De) / (d[j + 1] * (d[j + 1] + d[j])));
          }
          dual.species.push(rates);
          for (let i = 0; i < nf; i++) {
            const frac = cellOf(i, 0) * ns + s;
            const m1 = cellOf(i, 1) * ns + s;
            flowIn.push({ row: frac, col: m1, value: rates.diffFM1 });
            flowIn.push({ row: frac, col: frac, value: -rates.diffFM1 });
            flowIn.push({ row: m1, col: frac, value: rates.diffM1F });
            flowIn.push({ row: m1, col: m1, value: -rates.diffM1F });
            for (let j = 0; j < nm - 1; j++) {
              const here = cellOf(i, j + 1) * ns + s;
              const deeper = cellOf(i, j + 2) * ns + s;
              flowIn.push({ row: here, col: deeper, value: rates.diffMMF[j] });
              flowIn.push({ row: here, col: here, value: -rates.diffMMF[j] });
              flowIn.push({ row: deeper, col: here, value: rates.diffMMB[j] });
              flowIn.push({ row: deeper, col: deeper, value: -rates.diffMMB[j] });
            }
          }
        }
      }
    }
    // Pre-resolved slots, so neither rhs nor jac searches the pattern per step.
    const flowSlot = flowIn.map((f) => slot(f.row, f.col));

    /* ---- the model ------------------------------------------------------ */
    const R = new Float64Array(channels.length);
    const D = new Float64Array(Math.max(nd, 1));

    // The chemistry slots, resolved once. Three levels of small arrays rather
    // than a search per entry per step: on a hundred cells this is the
    // difference between a Jacobian that costs nothing and one that dominates.
    const slotCache = [];
    for (let i = 0; i < nc; i++) {
      const b = i * ns;
      const perChannel = [];
      for (const ch of channels) {
        const perNet = [];
        for (const [p] of ch.net) {
          if (fixed[p]) { perNet.push([]); continue; }
          perNet.push(ch.deps.map((dep) => slot(b + p, b + dep.si)));
        }
        perChannel.push(perNet);
      }
      slotCache.push(perChannel);
    }

    function rhs(t, y, out) {
      out.fill(0);
      for (let i = 0; i < nc; i++) {
        const b = i * ns;
        rates(y, b, P, i * np, R, D);
        const sc = reactScale[i];
        for (let j = 0; j < channels.length; j++) {
          const r = R[j];
          if (r === 0) continue;
          const ch = channels[j];
          const net = ch.net;
          for (let m = 0; m < net.length; m++) {
            const p = net[m][0];
            if (fixed[p]) continue;
            out[b + p] += net[m][1] * r * (ch.whole ? massOf[b + p] : sc);
          }
        }
      }
      for (let k = 0; k < flowIn.length; k++) {
        const f = flowIn[k];
        out[f.row] += f.value * y[f.col];
      }
      for (let k = 0; k < boundary.length; k++) out[boundary[k].row] += boundary[k].value;
      for (let i = 0; i < nc; i++) {
        const b = i * ns;
        for (let s = 0; s < ns; s++) if (fixed[s]) out[b + s] = 0;
      }
      // M dC/dt = f, so every term on the right -- reaction, transport and
      // boundary alike -- is divided by the coefficient of that row.
      if (anyMass) for (let k = 0; k < n; k++) out[k] *= invMass[k];
      return out;
    }

    function jac(t, y, V) {
      V.fill(0);
      for (let i = 0; i < nc; i++) {
        const b = i * ns;
        rates(y, b, P, i * np, R, D);
        const sc = reactScale[i];
        for (let j = 0; j < channels.length; j++) {
          const ch = channels[j];
          const d0 = derivIndex[j];
          for (let m = 0; m < ch.net.length; m++) {
            const p = ch.net[m][0];
            if (fixed[p]) continue;
            const c = ch.net[m][1] * (ch.whole ? massOf[b + p] : sc);
            for (let q = 0; q < ch.deps.length; q++) {
              const dv = D[d0 + q];
              if (dv === 0) continue;
              V[slotCache[i][j][m][q]] += c * dv;
            }
          }
        }
      }
      for (let k = 0; k < flowSlot.length; k++) V[flowSlot[k]] += flowIn[k].value;
      if (anyMass) for (let k = 0; k < nnz; k++) V[k] *= invMass[rowOfSlot[k]];
      return V;
    }

    const initial = new Float64Array(n);
    for (let i = 0; i < nc; i++) {
      for (let s = 0; s < ns; s++) initial[i * ns + s] = species[s].initial;
    }
    // A Dirichlet face is a stated concentration; starting the touching cell
    // there too saves the solver a jump on its very first step. Not for robin:
    // there the first cell is not at the face value and never becomes it.
    if (transport && settings.LEFT === 'dirichlet') {
      for (let s = 0; s < ns; s++) if (mobile[s] && species[s].left != null) initial[s] = species[s].left;
    }
    // Last, so that it overrides both of the above: it is the most specific
    // thing the reader can have said. A line names fracture cells; with
    // "matrix" it means the rock behind them instead.
    for (const patch of readInitial(sections.INITIAL, index, nf)) {
      for (let i = patch.from; i <= patch.to; i++) {
        if (!patch.matrix) { initial[cellOf(i, 0) * ns + patch.si] = patch.value; continue; }
        if (!matrix) throw new RtmError('"matrix" in <INITIAL> needs MATRIX_CELLS above zero.');
        for (let j = 1; j <= nm; j++) initial[cellOf(i, j) * ns + patch.si] = patch.value;
      }
    }

    const stateNames = [];
    for (let c = 0; c < nc; c++) {
      const g = geom[c];
      for (let s = 0; s < ns; s++) {
        stateNames.push(nc === 1 ? nameOf[s] : g.j === 0 ? `${nameOf[s]}@${g.i}` : `${nameOf[s]}@${g.i}.${g.j}`);
      }
    }

    const model = {
      // What the solvers ask for.
      nspecies: n,
      nnz,
      pattern: { n, nnz, colPtr, rowIdx },
      species: stateNames,
      initialState: () => Float64Array.from(initial),
      rhs,
      jac,
      nevents: 0,
      events: [],
      eventValues: () => {},
      applyEvent: () => [],

      // What the page asks for.
      settings,
      // The unit, resolved: what to print and how many seconds one is. The
      // model's own numbers are in it; nothing here is scaled by it.
      timeUnit: TIME_UNITS[settings.TIME_UNIT],
      grid,
      transport,
      cells: nc,               // every cell, matrix layers included
      fracture: nf,            // the cells along the column
      matrix,                  // null, or { n, d, centre, depth, porosity, aw }
      stride,                  // cells per fracture cell, 1 + matrix layers
      cellOf,
      geom,
      enters,
      dual,
      speciesList: species,
      speciesNames: nameOf,
      mobile,
      fixed,
      reactions: reactions.map((rx) => ({ line: rx.line, text: rx.text })),
      nreactions: reactions.length,
      equilibria,
      nequilibria: equilibria.length,
      conservation: equilibria.length ? conservationBasis(equilibria, ns, fixed) : [],
      parameters: params.order.slice(),
      anyMass,
      nchannels: channels.length,
      warnings,
      density: nnz / (n * n),
    };

    /*
      EQUILIBRATE = 1 puts the initial state on the equilibria before anything
      is integrated. A state written by hand almost never satisfies them -- the
      example above starts with H+ and OH- both at 1e-3, which is eight orders
      from the pair that multiply to Kw -- and starting off them means the
      first moments of the run are the solver discovering that, at whatever the
      fastest rate in the set happens to be.
    */
    if (settings.EQUILIBRATE && equilibria.length) {
      const done = speciate(model, initial);
      initial.set(done.y);
      const stuck = done.cells.filter((c) => !c.converged);
      if (stuck.length) {
        warnings.push(`The speciation of the initial state did not converge in ${stuck.length} `
          + `cell${stuck.length > 1 ? 's' : ''} (worst residual `
          + `${Math.max(...stuck.map((c) => c.residual)).toExponential(2)}).`);
      }
      model.speciated = done.cells;
    }

    return model;
  }

  /**
   * Check the analytic Jacobian against a differenced one.
   *
   * The Jacobian is the one thing here that can be wrong without the answer
   * looking wrong -- a stiff solver with a poor Jacobian takes more steps and
   * still arrives -- so it is worth being able to ask.
   */
  function verifyJacobian(model, t, y, rtol = 1e-4) {
    const n = model.nspecies;
    const V = new Float64Array(model.nnz);
    model.jac(t, y, V);
    const { colPtr, rowIdx } = model.pattern;
    const fp = new Float64Array(n);
    const fm = new Float64Array(n);
    // The rhs where it stands, for the noise floor below.
    const f0 = new Float64Array(n);
    model.rhs(t, y, f0);
    const EPS = 2 ** -52;
    const yp = Float64Array.from(y);
    const discrepancies = [];
    let checked = 0;
    let unresolvable = 0;
    let outside = null;
    /*
      The scale of each row, for the noise floor below: the sum of |J_rc*y_c|
      over the row, which is the size of the terms the two evaluations of f_r
      are made of. |f_r| itself will not do -- it is their DIFFERENCE, and a
      row in balance can be small while its terms are enormous. A rock matrix
      whose first layer is 4e-8 m thick has a wall exchange of 2e6/s beside an
      advection of 3e-2/s in the same row; judged against |f_r| the small
      entry looked resolvable and came back 2 % off, judged against the row
      it is rightly below what differencing can see.
    */
    const Vrow = new Float64Array(model.nnz);
    model.jac(t, y, Vrow);
    const rowScale = new Float64Array(n);
    {
      const pat = model.pattern;
      for (let c2 = 0; c2 < pat.n; c2++) {
        for (let k = pat.colPtr[c2]; k < pat.colPtr[c2 + 1]; k++) {
          rowScale[pat.rowIdx[k]] += Math.abs(Vrow[k] * y[c2]);
        }
      }
    }

    /*
      CENTRAL differences, and a step scaled to the component being nudged.

      Forward differences are not good enough to judge this Jacobian. A rate
      that is quadratic in a species -- k[e-]^2, and the radiolysis set is full
      of them -- has a true derivative of zero where that species is zero,
      while a forward difference returns k*h: not an error in the Jacobian but
      an error in the question. A central difference gives exactly zero there,
      because the two sides cancel. It also drops the error from O(h) to
      O(h^2), which the forty orders of magnitude between a bulk species and a
      radical make necessary.

      A component at zero still needs some step, and gets one scaled to the
      largest concentration present. The floor is a hundredth of that rather
      than something tiny: measured on the built-in model, a step near 1e-6
      reproduces the analytic entries to nine figures, and shrinking it below
      1e-8 makes the agreement WORSE, not better -- past that the difference is
      round-off in a row whose own rates are enormous. A tiny floor is why an
      earlier version of this function reported hundreds of discrepancies
      against a Jacobian that turned out to be exact.
    */
    let typ = 0;
    for (let i = 0; i < n; i++) typ = Math.max(typ, Math.abs(y[i]));
    if (!(typ > 0)) typ = 1;
    const cbrtEps = Math.cbrt(2 ** -52);

    for (let c = 0; c < n; c++) {
      const h = cbrtEps * Math.max(Math.abs(y[c]), typ * 1e-2);
      yp[c] = y[c] + h;
      model.rhs(t, yp, fp);
      yp[c] = y[c] - h;
      model.rhs(t, yp, fm);
      yp[c] = y[c];
      // A rate with a fractional power is undefined below zero, and the minus
      // side of a species sitting at zero is below zero. One-sided there.
      let step = 2 * h;
      let ok = true;
      for (let r = 0; r < n; r++) if (!Number.isFinite(fm[r])) { ok = false; break; }
      if (!ok) { model.rhs(t, y, fm); step = h; }
      const inColumn = new Map();
      for (let k = colPtr[c]; k < colPtr[c + 1]; k++) inColumn.set(rowIdx[k], V[k]);
      let scale = 0;
      for (let r = 0; r < n; r++) scale = Math.max(scale, Math.abs((fp[r] - fm[r]) / step));
      for (let r = 0; r < n; r++) {
        const numeric = (fp[r] - fm[r]) / step;
        if (!inColumn.has(r)) {
          if (Math.abs(numeric) > 1e-6 * Math.max(scale, 1) && !outside) {
            outside = { row: r, col: c, numeric };
          }
          continue;
        }
        const analytic = inColumn.get(r);
        /*
          What a difference can see in this row at all.

          The two evaluations agree to about a few ulps of the row's own value,
          so the smallest derivative the quotient can resolve is roughly
          eps*|f_r|/h -- and a row whose rates are 1e10 cannot show a
          derivative of 1e-7 however carefully it is asked. Those are counted
          apart rather than reported as failures: calling something wrong that
          the method cannot see would make this check worth ignoring, which is
          worse than not having it. The floor is derived rather than guessed,
          which an earlier version's "a hundred-thousandth of the column" was
          not -- it let through entries whose difference came back as an exact
          zero and called them disagreements.
        */
        const floor = 16 * EPS * Math.max(Math.abs(f0[r]), rowScale[r]) / h;
        if (Math.max(Math.abs(analytic), Math.abs(numeric)) < floor) {
          unresolvable++;
          continue;
        }
        checked++;
        const tol = Math.max(rtol * Math.max(Math.abs(analytic), Math.abs(numeric)), floor);
        if (Math.abs(analytic - numeric) > tol) {
          discrepancies.push({ row: r, col: c, analytic, numeric });
        }
      }
    }
    return { checked, unresolvable, discrepancies, outsidePattern: outside };
  }

  return { compile, verifyJacobian, speciate, conservationBasis, RtmError, parseReaction,
    readSections, derivative };
}));
