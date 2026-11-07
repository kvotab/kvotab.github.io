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

  // Characters of generated rate code in one function, 17 to 24 KB of
  // bytecode: well inside what V8 optimises (see compile, "the rates").
  const RATE_PART_CHARS = 24000;

  /* ======================================================================
     1. The model text
     ====================================================================== */

  const SECTIONS = ['SETTINGS', 'SPECIES', 'REACTIONS', 'INITIAL', 'PARAMETERS', 'EQUILIBRIUM', 'PHASES'];

  /** Settings, their defaults and how each is read. */
  const SETTINGS = {
    MODE: { def: 'batch', kind: 'word', of: ['batch', 'transport'] },
    CELLS: { def: 20, kind: 'int' },
    LENGTH: { def: 1, kind: 'number' },
    /*
      How the cells are laid out. linear: equal widths. log: widths growing
      geometrically, the last GRID_RATIO times the first. powerlaw: faces at
      LENGTH*(i/CELLS)^GRID_POWER, fine at the left for a power above 1.
      faces: FACES gives the face positions outright -- a list, or an
      expression in i for i = 0..CELLS. Whatever the kind, SURFACE_LAYER > 0
      makes the first cell exactly that thick and lays the rest out over what
      is left, so the cell a surface lives in does not change when the grid
      does.
    */
    GRID: { def: 'linear', kind: 'word', of: ['linear', 'log', 'powerlaw', 'faces'] },
    GRID_RATIO: { def: 1000, kind: 'number' },
    GRID_POWER: { def: 3, kind: 'number' },
    FACES: { def: '', kind: 'text' },
    SURFACE_LAYER: { def: 0, kind: 'number' },
    /*
      1 is each species diffusing at its own D; nernst-planck couples the ions
      so that no current flows: a fast ion drags its slow partner along and
      waits for it, and the water stays neutral. See npFaces.
    */
    DIFFUSION: { def: 1, kind: 'flag', words: { 'nernst-planck': 2 } },
    ADVECTION: { def: 0, kind: 'flag' },
    /*
      How advection is differenced: upwind, first order, stable at any step and
      spreading a front by v*dz/2; or limited, which adds to each face the slope
      of the cell upwind of it, limited (van Albada) so that no new peak or
      trough appears: second order where the profile is smooth, upwind where it
      turns. See limitedFaces.
    */
    ADVECTION_SCHEME: { def: 'upwind', kind: 'word', of: ['upwind', 'limited'] },
    VELOCITY: { def: 0, kind: 'number' },
    POROSITY: { def: 1, kind: 'number' },
    /*
      The kinds a face can be, under the names the transport literature gives
      them. `cauchy` and `robin` are the same third-type condition and
      `outflow` is `free` by another name; the aliases are folded in below so
      that only the plain words reach the assembly. `semi-infinite` is an
      outlet only: the column goes on past its right-hand end, as FARF31's
      stream tube does, and EXTRA_CELLS of it stand for the rock beyond.
    */
    LEFT: { def: 'dirichlet', kind: 'word',
      of: ['dirichlet', 'neumann', 'robin', 'cauchy', 'free', 'outflow', 'semi-infinite'] },
    RIGHT: { def: 'neumann', kind: 'word',
      of: ['dirichlet', 'neumann', 'robin', 'cauchy', 'free', 'outflow', 'semi-infinite'] },
    // How many cells past a semi-infinite right-hand end; worked out unless given.
    EXTRA_CELLS: { def: 0, kind: 'int' },
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
    /*
      1 (or start) puts the starting state on the <EQUILIBRIUM> relations;
      always also holds those relations exactly while the run goes on, as
      algebraic equations (see holdEquilibria). A relation given a kf is a
      fast reversible pair either way.
    */
    EQUILIBRATE: { def: 0, kind: 'flag', words: { start: 1, always: 2 } },
    /*
      ACTIVITY: the relations of <EQUILIBRIUM> hold between activities, each
      species' concentration times its activity coefficient, and those follow
      the ionic strength of the cell as the run goes on: davies, or
      debye-huckel, which is the WATEQ form for a species given a= and Davies
      for any other ion, PHREEQC's rule. none, the default, holds them between
      concentrations. TEMPERATURE, in degrees C, sets the Debye-Hueckel A and
      B and nothing else. See activityModel.
    */
    ACTIVITY: { def: 'none', kind: 'word', of: ['none', 'davies', 'debye-huckel', 'debye-hückel'] },
    TEMPERATURE: { def: 25, kind: 'number' },
    /*
      DUAL POROSITY: a rock matrix beside the column.

      Every cell of the column -- the fracture, the flowing water -- has a
      chain of MATRIX_CELLS stagnant cells behind it, reaching MATRIX_DEPTH
      into the rock, into which species diffuse and in which they react and
      sorb. Twelve of them, as Kompartment's far-field path has, once the text
      says anything about the rock; MATRIX_CELLS = 0 is none. The layers grow
      geometrically with depth from MATRIX_FIRST (worked out when left at
      zero), because the gradient is steepest at the wall, and MATRIX_GRID
      says how: `matched`, Kompartment's layers, or `reference`, FARFCOMP's.
      WETTED_SURFACE is the rock surface in contact with a unit volume of
      flowing water, m2/m3; APERTURE (2b) and TRANSPORT_RESISTANCE (F) are the
      other ways of saying it, aw = 2/(2b) and aw = F/t_w. MATRIX_DENSITY
      turns a species' Kd into its capacity in the rock. PECLET, when set,
      gives every mobile species the same longitudinal dispersion v*L/Pe along
      the fracture, less the v*dz/2 the upwind scheme already puts in.
      TRAVEL_TIME gives the flow as the time the water takes to cross the
      column, which is how a far-field path is described.
    */
    MATRIX_CELLS: { def: 0, kind: 'number' },
    MATRIX_DEPTH: { def: 0, kind: 'number' },
    MATRIX_FIRST: { def: 0, kind: 'number' },
    MATRIX_GRID: { def: 'matched', kind: 'word', of: ['matched', 'reference'] },
    MATRIX_POROSITY: { def: 0, kind: 'number' },
    MATRIX_DENSITY: { def: 2700, kind: 'number' },
    WETTED_SURFACE: { def: 0, kind: 'number' },
    APERTURE: { def: 0, kind: 'number' },
    TRANSPORT_RESISTANCE: { def: 0, kind: 'number' },
    TRAVEL_TIME: { def: 0, kind: 'number' },
    PECLET: { def: 0, kind: 'number' },
  };

  /** How many matrix layers a rock matrix has when the text does not say: Kompartment's far-field default. */
  const DEFAULT_MATRIX_CELLS = 12;

  /** The settings that describe a rock matrix: any of them, and there is one. */
  const MATRIX_KEYS = ['MATRIX_DEPTH', 'MATRIX_FIRST', 'MATRIX_GRID', 'MATRIX_POROSITY', 'MATRIX_DENSITY'];

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
    // <TABLE name> may appear any number of times, one named table each.
    out.TABLES = [];
    let current = null;
    let table = null;
    String(text).split(/\r?\n/).forEach((raw, i) => {
      const line = raw.replace(/(^|\s)#.*$/, '').trim();
      if (!line) return;
      const header = /^<\s*([A-Za-z]+)((?:\s+[^\s<>]+)*)\s*>$/.exec(line);
      if (header) {
        const name = header[1].toUpperCase();
        const args = header[2].trim().split(/\s+/).filter(Boolean);
        if (name === 'TABLE') {
          if (!args.length || !/^[A-Za-z_][A-Za-z0-9_]*$/.test(args[0])) {
            throw new RtmError('<TABLE name> needs a name, for example <TABLE dose_alpha>, '
              + 'and "log" or "loglog" after it to interpolate the logarithm of the values.', i + 1);
          }
          const how = (args[1] || 'linear').toLowerCase();
          if (!TABLE_MODES.includes(how) || args.length > 2) {
            throw new RtmError(`<TABLE ${args.join(' ')}>: after the name comes "linear", "log" or `
              + '"loglog", or nothing.', i + 1);
          }
          if (out.TABLES.some((t) => t.name === args[0])) {
            throw new RtmError(`There are two tables called ${args[0]}.`, i + 1);
          }
          table = { name: args[0], mode: how, rows: [], line: i + 1 };
          out.TABLES.push(table);
          current = 'TABLE';
          return;
        }
        if (!SECTIONS.includes(name)) {
          throw new RtmError(`"${name}" is not a section. Use ${SECTIONS.map((s) => `<${s}>`).join(', ')}, `
            + 'or <TABLE name>.', i + 1);
        }
        if (args.length) throw new RtmError(`<${name}> takes no name; only <TABLE name> does.`, i + 1);
        current = name;
        table = null;
        return;
      }
      if (!current) throw new RtmError('Text before the first section; start with <SETTINGS>.', i + 1);
      if (current === 'TABLE') table.rows.push({ text: line, line: i + 1 });
      else out[current].push({ text: line, line: i + 1 });
    });
    return out;
  }

  /**
   * A number that may be written as arithmetic: 1.33*10**12, 365*86400, 2/3.
   * A plain number is the common case and never reaches the parser. `lookup`
   * says what else a value may name; by default it may name nothing, so that
   * a misspelt constant is an error rather than a silent zero.
   */
  function constValue(raw, line, what, lookup = () => undefined) {
    const s = String(raw).trim();
    const plain = Number(s);
    if (s !== '' && Number.isFinite(plain)) return plain;
    let v;
    try {
      v = FacsimileModel.evalAst(FacsimileModel.parseExpression(s, line), lookup, {}, line);
    } catch (e) {
      throw new RtmError(`${what} = "${s}" is not a number, or arithmetic on numbers `
        + `(${e.message.replace(/^Line \d+: /, '')}).`, line);
    }
    if (!Number.isFinite(v)) throw new RtmError(`${what} = "${s}" does not come to a finite number.`, line);
    return v;
  }

  /** `NAME = value` lines, read against the table above. */
  function readSettings(lines) {
    const out = {};
    for (const [name, spec] of Object.entries(SETTINGS)) out[name] = spec.def;
    // Which settings the text gave, as against the defaults: FACES decides
    // CELLS and LENGTH, and only a CELLS the text wrote can disagree with it.
    const given = new Set();
    Object.defineProperty(out, 'given', { value: given, enumerable: false });
    for (const { text, line } of lines) {
      const m = /^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$/.exec(text);
      if (!m) throw new RtmError(`"${text}" is not NAME = value.`, line);
      const name = m[1].toUpperCase();
      const spec = SETTINGS[name];
      if (!spec) {
        throw new RtmError(`"${name}" is not a setting. Known: ${Object.keys(SETTINGS).join(', ')}.`, line);
      }
      const raw = m[2].trim();
      given.add(name);
      if (spec.kind === 'word') {
        const word = raw.toLowerCase();
        if (!spec.of.includes(word)) {
          throw new RtmError(`${name} must be one of ${spec.of.join(', ')}, not "${raw}".`, line);
        }
        out[name] = { cauchy: 'robin', outflow: 'free', 'debye-hückel': 'debye-huckel' }[word] || word;
        if (name === 'TIME_UNIT') out[name] = TIME_UNITS[out[name]].name;
      } else if (spec.kind === 'flag') {
        const word = raw.toLowerCase();
        if (spec.words && Object.prototype.hasOwnProperty.call(spec.words, word)) {
          out[name] = spec.words[word];
        } else if (spec.words && !/^(1|yes|true|on|0|no|false|off)$/.test(word)) {
          // A setting with words of its own says so rather than reading an
          // unknown one as "no": EQUILIBRATE = alway would otherwise be 0.
          throw new RtmError(`${name} is 0, 1, ${Object.keys(spec.words).join(' or ')}, not "${raw}".`, line);
        } else {
          out[name] = /^(1|yes|true|on)$/i.test(raw) ? 1 : 0;
        }
      } else if (spec.kind === 'text') {
        out[name] = raw;
        Object.defineProperty(out, `${name}_line`, { value: line, enumerable: false });
      } else {
        const v = constValue(raw, line, name);
        out[name] = spec.kind === 'int' ? Math.round(v) : v;
      }
    }
    // FACES implies the grid it describes, whatever GRID says.
    if (out.FACES && !given.has('GRID')) out.GRID = 'faces';
    if (out.GRID === 'faces' && !out.FACES) {
      throw new RtmError('GRID = faces needs FACES = ..., the face positions in metres: a list, '
        + 'or an expression in i for i = 0 to CELLS.');
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
    left alone. A formula may group atoms in round brackets -- Fe(OH)3,
    UO2(CO3)3-4 -- one level deep; square brackets are what a rate law puts
    round a name, so a name cannot contain them.
  */
  const SPECIES_NAME = /^[A-Za-z](?:[A-Za-z0-9_]|\([A-Za-z0-9_]+\))*(?:[+-][0-9]*)?$/;
  const NAME_RULE = 'Letters, digits and _ , groups in round brackets such as (OH)3, and '
    + 'optionally a charge at the end such as + , - , +2 or -2.';

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
        throw new RtmError(`"${name}" is not a species name. ${NAME_RULE}`, line);
      }
      if (seen.has(name)) throw new RtmError(`Species "${name}" is given twice.`, line);
      const entry = { name, initial: 0, fixed: false, D: 0, left: null, right: null,
        mass: null, Dm: 0, Rm: null, Kd: null, Kdf: null, z: null, dha: null, dhb: null, pe: null,
        mineral: false, immobile: false, exchange: false, exchanger: false, electron: false, line };
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
          const value = constValue(kv[2], line, kv[1]);
          if (key === 'd') entry.D = value;
          // De is what the SKB reports call the matrix diffusivity, and
          // Kompartment's far-field path: the same property as Dm.
          else if (key === 'dm' || key === 'de') entry.Dm = value;
          // The two sorption coefficients a far-field path is given, which
          // become R and Rm once the wetted surface and the rock are known.
          else if (key === 'kd') entry.Kd = value;
          else if (key === 'kdf') entry.Kdf = value;
          else if (key === 'left') entry.left = value;
          else if (key === 'right') entry.right = value;
          // The activity model's: the charge, where the name does not give
          // it, and the WATEQ Debye-Hueckel a (angstrom) and b (kg/mol).
          else if (key === 'z') {
            if (!Number.isInteger(value)) throw new RtmError(`z = ${value} for ${name}: a charge is a whole number.`, line);
            entry.z = value;
          } else if (key === 'a') {
            if (!(value >= 0)) throw new RtmError(`a = ${value} for ${name}: an ion size is zero or more.`, line);
            entry.dha = value;
          } else if (key === 'b') entry.dhb = value;
          // The electron's: the pe its activity starts at, 10^-pe.
          else if (key === 'pe') entry.pe = value;
          else throw new RtmError(`"${kv[1]}" is not a species property. Use D, left, right, `
            + 'mass or R; with a rock matrix Dm (or De), Rm, Kd or Kdf; for ACTIVITY z, a and b; and for '
            + 'the electron pe.', line);
          continue;
        }
        if (/^fixed$/i.test(part)) { entry.fixed = true; continue; }
        // Never carried or diffused, whatever the column does: a surface site.
        if (/^immobile$/i.test(part)) { entry.immobile = true; continue; }
        // A pure phase: immobile, its activity 1, its amount free to reach zero.
        if (/^mineral$/i.test(part)) { entry.mineral = true; entry.immobile = true; continue; }
        // An ion exchanger's sites, X- of PHREEQC: what is given is its
        // capacity, and the species is no amount -- its activity is solved.
        if (/^exchanger$/i.test(part)) { entry.exchanger = true; entry.immobile = true; continue; }
        // A species on an exchanger, NaX: its activity is its equivalent fraction.
        if (/^exchange$/i.test(part)) { entry.exchange = true; entry.immobile = true; continue; }
        // PHREEQC's electron: no amount, its activity 10^-pe solved for.
        if (/^electron$/i.test(part)) { entry.electron = true; entry.immobile = true; continue; }
        if (first) {
          entry.initial = constValue(part, line, `the concentration of ${name}`);
          first = false;
          continue;
        }
        throw new RtmError(`"${part}" is not understood on a species line.`, line);
      }
      const kinds = ['mineral', 'exchange', 'exchanger', 'electron'].filter((k) => entry[k]);
      if (kinds.length > 1) throw new RtmError(`${name} is given as ${kinds.join(' and ')}: it is one of them.`, line);
      if (entry.pe !== null && !entry.electron) {
        throw new RtmError(`pe = ${entry.pe} for ${name}: pe is the electron's, e- electron pe=4.`, line);
      }
      if (entry.electron) {
        /*
          The electron is no amount and never moves: what it is given is its
          activity, 10^-pe, which the start is speciated at. It may be fixed:
          the pe held from outside, a redox buffer.
        */
        const moves = [['D', entry.D > 0], ['Dm', entry.Dm > 0], ['R', entry.mass !== null], ['Rm', entry.Rm !== null],
          ['Kd', entry.Kd !== null], ['Kdf', entry.Kdf !== null], ['left', entry.left !== null],
          ['right', entry.right !== null]].filter(([, given]) => given).map(([k]) => k);
        if (moves.length) {
          throw new RtmError(`${name} is the electron, which is no amount and never moves: it takes no `
            + `${moves.join(', ')}.`, line);
        }
        if (entry.z !== null || entry.dha !== null || entry.dhb !== null) {
          throw new RtmError(`${name} is the electron, whose activity is solved for and which carries no charge `
            + 'into the ionic strength: it takes no z, a or b.', line);
        }
        if (entry.pe !== null) {
          if (entry.initial !== 0) {
            throw new RtmError(`${name} is given both an activity and a pe: they say the same thing, `
              + 'the activity being 10^-pe. Give one.', line);
          }
          entry.initial = 10 ** -entry.pe;
          if (!(entry.initial > 0 && Number.isFinite(entry.initial))) {
            throw new RtmError(`pe = ${entry.pe} for ${name} puts its activity out of reach of a number.`, line);
          }
        } else if (!(entry.initial >= 0)) {
          throw new RtmError(`${name} is the electron, and its activity is above zero: pe=4 is 1e-4.`, line);
        }
      } else if (kinds.length) {
        const kind = kinds[0];
        const what = { mineral: 'a mineral', exchange: 'on an exchanger', exchanger: 'an exchanger' }[kind];
        const moves = [['D', entry.D > 0], ['Dm', entry.Dm > 0], ['R', entry.mass !== null], ['Rm', entry.Rm !== null],
          ['Kd', entry.Kd !== null], ['Kdf', entry.Kdf !== null], ['left', entry.left !== null],
          ['right', entry.right !== null], ['fixed', entry.fixed]].filter(([, given]) => given).map(([k]) => k);
        if (moves.length) {
          throw new RtmError(`${name} is ${what}, which stays where it is and is never held: it takes no `
            + `${moves.join(', ')}.`, line);
        }
        if (!(entry.initial >= 0)) {
          throw new RtmError(`${name} is ${what}, and its ${kind === 'exchanger' ? 'capacity' : 'amount'} is zero or more.`,
            line);
        }
        if (kind !== 'mineral' && entry.z !== null) {
          throw new RtmError(`${name} is ${what}: ${kind === 'exchanger' ? 'its sites are counted, not charged'
            : 'it carries no charge into the ionic strength, and its coefficient is its ion\'s, from its relation'}, so `
            + 'it takes no z.', line);
        }
        if (kind === 'exchanger' && (entry.dha !== null || entry.dhb !== null)) {
          throw new RtmError(`${name} is an exchanger, whose activity is solved for: it takes no a or b.`, line);
        }
        if (kind === 'exchange' && (entry.dha === null) !== (entry.dhb === null)) {
          throw new RtmError(`${name} is on an exchanger: it takes a and b together, as PHREEQC's -gamma a b, `
            + 'or neither.', line);
        }
      }
      // Each pair says one thing two ways, and two answers to it cannot both stand.
      if (entry.Kd !== null && entry.Rm !== null) {
        throw new RtmError(`${name} has both Kd and Rm: Rm is the capacity Kd gives, `
          + 'MATRIX_POROSITY + MATRIX_DENSITY*Kd. Give one of them.', line);
      }
      if (entry.Kdf !== null && entry.mass !== null) {
        throw new RtmError(`${name} has both Kdf and R: R is the retardation Kdf gives, `
          + '1 + Kdf*aw with aw the wetted surface. Give one of them.', line);
      }
      for (const [key, v] of [['Kd', entry.Kd], ['Kdf', entry.Kdf], ['Dm', entry.Dm]]) {
        if (v !== null && v < 0) {
          throw new RtmError(`${key} = ${v} for ${name}: a sorption coefficient or a diffusivity `
            + 'is zero or more.', line);
        }
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
   *   X       0-9    1.0            the first ten cells
   *   O2      all    2.1e-4         every cell, the same as writing it in <SPECIES>
   *   Fe      20     0.5            one cell
   *   U_site  0      2.1e-4/w/1000  per m2 of surface: w is the cell's width
   *   U_site  1-9    0  fixed       held there: nothing may change it in those cells
   *
   * <SPECIES> gives a concentration the whole domain starts at, which is all a
   * batch run can have; a front, a plume or a layer needs this. The value may
   * be an expression in what <PARAMETERS> can use -- x, i, w, the parameters,
   * the tables -- worked out once per cell. After it may come "fixed", which
   * holds the species at that value in those cells and nowhere else, and
   * "matrix", which aims the line at the rock behind those cells.
   */
  function readInitial(lines, index, cells) {
    const out = [];
    for (const { text, line } of lines) {
      // Commas and semicolons outside brackets separate as spaces do, so that
      // "X, 0-9, 1.0" still reads and max(a, b) in a value is left whole.
      let depth = 0;
      let flat = '';
      for (const c of text) {
        if (c === '(' || c === '[') depth++;
        else if (c === ')' || c === ']') depth--;
        flat += depth === 0 && (c === ',' || c === ';') ? ' ' : c;
      }
      const parts = flat.trim().split(/\s+/).filter(Boolean);
      let matrix = false;
      let fixed = false;
      while (parts.length > 2 && /^(matrix|fixed)$/i.test(parts[parts.length - 1])) {
        if (/^matrix$/i.test(parts.pop())) matrix = true; else fixed = true;
      }
      // "U_site 1-9 fixed" holds it where it already is, and needs no value.
      const keep = parts.length === 2 && fixed;
      if (parts.length < 3 && !keep) {
        throw new RtmError(`"${text}" is not "species cells value" -- for example "X 0-9 1.0"; `
          + 'then "fixed" to hold it there, "matrix" for the rock behind those cells.', line);
      }
      const [name, where] = parts;
      const raw = parts.slice(2).join(' ');
      if (!index.has(name)) throw new RtmError(`"${name}" is not in <SPECIES>.`, line);
      // A plain number is kept as one; anything else is parsed now, so that a
      // typing error is reported by line, and worked out per cell later.
      let value = keep ? null : Number(raw);
      let ast = null;
      if (!keep && !Number.isFinite(value)) {
        value = null;
        try {
          ast = FacsimileModel.parseExpression(raw, line);
        } catch (e) {
          throw new RtmError(`"${raw}" is not a concentration or an expression for one `
            + `(${e.message.replace(/^Line \d+: /, '')}).`, line);
        }
      }
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
      out.push({ si: index.get(name), from, to, value, ast, src: raw, matrix, fixed, line });
    }
    return out;
  }

  /** How a table may be interpolated: see readTables. */
  const TABLE_MODES = ['linear', 'log', 'loglog'];

  /**
   * <TABLE name> sections: x and a value per row, x increasing -- or x and
   * several values, a column each. A table is used in <PARAMETERS> or
   * <INITIAL> as name(x), or interp(name, x) as FACSIMILE writes it, and in a
   * rate law as name(t), read at the clock; a table of several columns says
   * which, name(x, U238) or name(x, 2). It is interpolated linearly between
   * its rows and held at its end values beyond them.
   *
   *   linear   the values, linearly in x: the default.
   *   log      the logarithm of the values, linearly in x, which follows a
   *            profile that dies away exponentially -- a dose rate -- far
   *            better between sparse rows.
   *   loglog   the logarithm of the values in the logarithm of x: a power law
   *            between rows, which is how FARF31 reads a release history and
   *            what follows one over decades of time from a few rows.
   *
   * The logarithm needs the values above zero, and loglog its x as well; below
   * its first x it holds the first value, as every table does, so a time of
   * zero is read as the first row. A first row whose first word starts with a
   * letter names the columns -- "t  U238  U234" -- the first of them x's.
   */
  function readTables(tables) {
    const out = new Map();
    for (const t of tables) {
      const xs = [];
      let cols = null;
      let names = null;
      const logY = t.mode !== 'linear';
      const logX = t.mode === 'loglog';
      t.rows.forEach(({ text, line }, r) => {
        const parts = text.split(/[\s,;]+/).filter(Boolean);
        if (r === 0 && /^[A-Za-z_]/.test(parts[0])) {
          if (parts.length < 2) {
            throw new RtmError(`"${text}" in <TABLE ${t.name}> names the columns, and there have to be two `
              + 'at least: x and a value.', line);
          }
          const bad = parts.slice(1).find((p) => !/^[A-Za-z_][A-Za-z0-9_]*$/.test(p));
          if (bad) {
            throw new RtmError(`"${bad}" in the first row of <TABLE ${t.name}> names a column, and a name is `
              + 'letters, digits and _ , starting with a letter: it is read in an expression.', line);
          }
          names = parts.slice(1);
          return;
        }
        const width = names ? names.length + 1 : (cols ? cols.length + 1 : parts.length);
        if (parts.length < 2 || parts.length !== width) {
          throw new RtmError(`"${text}" in <TABLE ${t.name}> is not ${width < 2 ? 'two numbers, x and a value'
            : `${width} numbers, x and ${width - 1} value${width === 2 ? '' : 's'}`}.`, line);
        }
        if (!cols) cols = Array.from({ length: width - 1 }, () => []);
        const x = constValue(parts[0], line, 'x');
        if (xs.length && !(x > xs[xs.length - 1])) {
          throw new RtmError(`In <TABLE ${t.name}> x must increase from row to row; ${x} does not.`, line);
        }
        if (logX && !(x > 0)) {
          throw new RtmError(`<TABLE ${t.name} loglog> interpolates in the logarithm of x, so every x must `
            + `be above zero; ${x} is not. Below the first x the first value is held, so a time of `
            + 'zero is read as the first row anyway.', line);
        }
        xs.push(logX ? Math.log(x) : x);
        for (let c = 1; c < width; c++) {
          const y = constValue(parts[c], line, `${t.name}(${parts[0]})`);
          if (logY && !(y > 0)) {
            throw new RtmError(`<TABLE ${t.name} ${t.mode}> interpolates the logarithm, so every value must `
              + `be above zero; ${y} is not.`, line);
          }
          cols[c - 1].push(logY ? Math.log(y) : y);
        }
      });
      if (!xs.length) throw new RtmError(`<TABLE ${t.name}> has no rows.`, t.line);
      const x = Float64Array.from(xs);
      // One view per column, in the shape the shared interpolation reads.
      const views = cols.map((c) => ({ x, y: Float64Array.from(c) }));
      out.set(t.name, {
        name: t.name, mode: t.mode, log: logY, x, y: views[0].y, views, names, line: t.line,
        // The x of every row, as written: where the table turns.
        corners: logX ? Array.from(x, Math.exp) : Array.from(x),
      });
    }
    return out;
  }

  /** A table at one point, in one of its columns: linear between rows, flat beyond them. */
  function tableAt(tab, x, col = 0) {
    const at = tab.mode === 'loglog' ? (x > 0 ? Math.log(x) : -Infinity) : x;
    const v = FacsimileModel.interpTable(tab.views[col], at);
    return tab.log ? Math.exp(v) : v;
  }

  /**
   * Which column of `tab` a call reads: the only one, or the one its last
   * argument names -- a column's name from the header, or its number from 1.
   */
  function tableColumn(tab, node, extra, line) {
    const ncol = tab.views.length;
    if (!extra) {
      if (ncol > 1) {
        throw new RtmError(`The table ${tab.name} has ${ncol} columns of values: say which, `
          + `${tab.name}(x, ${tab.names ? tab.names[0] : 1})${tab.names ? ` or ${tab.name}(x, 1)` : ''}.`, line);
      }
      return 0;
    }
    if (extra.type === 'num' && Number.isInteger(extra.v) && extra.v >= 1 && extra.v <= ncol) return extra.v - 1;
    if (extra.type === 'id' && tab.names && tab.names.includes(extra.name)) return tab.names.indexOf(extra.name);
    throw new RtmError(`The table ${tab.name} has no column ${extra.type === 'id' ? `"${extra.name}"`
      : (extra.type === 'num' ? extra.v : 'like that')}: its columns are `
      + `${tab.names ? tab.names.join(', ') : `1 to ${ncol}`}${tab.names ? `, or 1 to ${ncol}` : ''}.`, line);
  }

  /**
   * A table call, taken apart: name(x), name(x, column), interp(name, x) or
   * interp(name, x, column). Null for anything else.
   */
  function tableCall(node, tables, line) {
    if (node.type !== 'call') return null;
    if (tables.has(node.name)) {
      if (node.args.length < 1 || node.args.length > 2) {
        throw new RtmError(`The table ${node.name} takes x, and a column when it has several: `
          + `${node.name}(x) or ${node.name}(x, column).`, line);
      }
      const tab = tables.get(node.name);
      return { tab, arg: node.args[0], col: tableColumn(tab, node, node.args[1], line) };
    }
    if (node.name.toLowerCase() === 'interp') {
      const first = node.args[0];
      if (!first || first.type !== 'id' || !tables.has(first.name) || node.args.length < 2 || node.args.length > 3) {
        throw new RtmError('interp(name, x) needs the name of a <TABLE> and one more argument, and a '
          + 'column after that when the table has several.', line);
      }
      const tab = tables.get(first.name);
      return { tab, arg: node.args[1], col: tableColumn(tab, node, node.args[2], line) };
    }
    return null;
  }

  /**
   * An expression that may call tables, ready to be worked out cell by cell.
   * Each call -- name(arg) or interp(name, arg) -- becomes a placeholder the
   * lookup answers by working out arg and reading the table there, so the
   * shared evaluator never has to know what a table is.
   */
  function bindTables(ast, tables, line) {
    const calls = [];
    const walk = (node) => {
      if (!node || typeof node !== 'object') return node;
      if (node.type === 'call') {
        const call = tableCall(node, tables, line);
        if (call) {
          const id = `__table${calls.length}__`;
          calls.push({ id, tab: call.tab, col: call.col, arg: walk(call.arg) });
          return { type: 'id', name: id };
        }
        return { ...node, args: node.args.map(walk) };
      }
      if (node.type === 'bin') return { ...node, l: walk(node.l), r: walk(node.r) };
      if (node.type === 'neg') return { ...node, a: walk(node.a) };
      return node;
    };
    const bound = walk(ast);
    return {
      ast: bound,
      // Wraps a lookup so that it answers the placeholders too.
      lookup(base) {
        const self = (id) => {
          const call = calls.find((c) => c.id === id);
          if (call) return tableAt(call.tab, FacsimileModel.evalAst(call.arg, self, {}, line), call.col);
          return base(id);
        };
        return self;
      },
    };
  }

  /**
   * The argument of a table read at the clock as a line in t, a*t + b, or
   * null when it is not one -- for where the table turns in time. The tree
   * has been folded, so a constant is a number by now.
   */
  function lineInTime(node) {
    switch (node.type) {
      case 'num': return { a: 0, b: node.v };
      case 'id': return node.name === 't' ? { a: 1, b: 0 } : null;
      case 'neg': {
        const r = lineInTime(node.a);
        return r && { a: -r.a, b: -r.b };
      }
      case 'bin': {
        const l = lineInTime(node.l);
        const r = l && lineInTime(node.r);
        if (!l || !r) return null;
        if (node.op === '+') return { a: l.a + r.a, b: l.b + r.b };
        if (node.op === '-') return { a: l.a - r.a, b: l.b - r.b };
        if (node.op === '*' && l.a === 0) return { a: l.b * r.a, b: l.b * r.b };
        if (node.op === '*' && r.a === 0) return { a: l.a * r.b, b: l.b * r.b };
        if (node.op === '/' && r.a === 0 && r.b !== 0) return { a: l.a / r.b, b: l.b / r.b };
        return null;
      }
      default: return null;
    }
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
    if (d0 === null) d0 = eRatioFirst(depth, nm, aw);
    if (d0 * nm > depth * (1 + 1e-12)) throw tooThick(nm, d0, depth);
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
   * FARFCOMP's first layer: the one that makes nm layers growing by e reach
   * the depth, bracketed between a micrometre and the fracture's own aperture
   * 2/aw. The sum is linear in it, so there is one answer.
   */
  function eRatioFirst(depth, nm, aw) {
    const geo = (x) => {
      let sum = 0;
      for (let k = 1; k <= nm; k++) sum += x * Math.exp(k);
      return sum - depth;
    };
    return zeroin(geo, 1e-12 / Math.E, 2 / aw / Math.E) * Math.E;
  }

  /** The refusal for a first layer the depth cannot hold. */
  function tooThick(nm, d0, depth) {
    return new RtmError(`${nm} matrix layers starting at ${d0} m cannot add up to MATRIX_DEPTH `
      + `${depth} m: the layers grow with depth, so the first must be smaller than `
      + `${depth / nm} m. Use a thinner MATRIX_FIRST, fewer layers, a greater depth, or leave `
      + 'MATRIX_FIRST at zero to have it worked out.');
  }

  /*
    THE MATCHED LAYERS: Kompartment's far-field layers, kept step for step
    with kompartment/src/domain/farfield.js so that a path here and a path
    there are laid out to the same doubles.

    What the rock does to the fracture is a boundary flux: it takes up
    Y(s)*c per unit wall area at frequency s, with

        Y(s) = sqrt(De Rm s) * tanh(x0 * sqrt(Rm s / De)),

    and that admittance is all the fracture ever sees of it. The layers are a
    ladder of capacities Rm*d_j joined by conductances De/h_j, and how well its
    admittance agrees with Y over the frequencies a release is made of is the
    whole accuracy of the matrix. Nodes at the layers' centres -- FARFCOMP's,
    h_j = (d_j-1 + d_j)/2 -- understate Y by a constant fraction on a
    geometric grid: 0.4 % at a ratio of 1.3, 5.8 % at e, which is the ratio
    FARFCOMP's automatic first layer gives. Nodes spaced by the geometric mean
    of the two layers they join, h_j = sqrt(d_j-1 d_j), with the first at
    d_0/(1 + sqrt q) from the wall, remove that bias outright (Ingerman,
    Druskin and Knizhnerman's optimal grids, CPAM 53, 2000).

    That leaves where the ladder starts: thin enough to resolve the fastest
    frequency that still matters, which is the frequency at which the path's
    transfer function has fallen to e^-ATTENUATION, and a tenth of the depth
    diffusion reaches at it.
  */
  const ATTENUATION = 25;
  const RESOLVE = 10;

  /**
   * The depth diffusion reaches into the rock at the fastest frequency the
   * path lets through, for one species, in m: Kompartment's penetrationScale.
   * With u = sqrt(s + lam) the fracture sees g = rf*u^2 + aw*sqrt(De Rm)*u,
   * and the path's transfer function exp((Pe/2)(1 - sqrt(1 + 4 tw g/Pe))) is
   * down to e^-A where tw*g = A(1 + A/Pe). A species that decays faster than
   * that is resolved at its decay constant instead. Infinity for one that does
   * not enter the rock, or a path with no time scale at all.
   */
  function penetrationScale({ de, rm, lam = 0, rf = 1 }, { aw, tw, pe }) {
    if (!(de > 0) || !(rm > 0) || !(aw > 0) || !Number.isFinite(aw)) return Infinity;
    if (!(tw > 0) || !(pe > 0)) return Infinity;
    const G = (ATTENUATION * (1 + ATTENUATION / pe)) / tw;
    const A = aw * Math.sqrt(de * rm);
    // The positive root of rf*u^2 + A*u - G = 0, in the form that does not
    // cancel when A dominates.
    const u = (2 * G) / (A + Math.sqrt(A * A + 4 * rf * G));
    const u2 = Math.max(u * u, Number.isFinite(lam) && lam > 0 ? lam : 0);
    if (!(u2 > 0) || !Number.isFinite(u2)) return Infinity;
    return Math.sqrt(de / rm / u2);
  }

  /**
   * The matched layers: a geometric series from the first thickness d0 to
   * exactly the depth, and the node spacings that make its exchange with the
   * fracture match diffusion into the rock. The ratio comes from the same
   * root-finder as the reference layers, over a sum built by repeated
   * multiplication rather than by powers.
   */
  function matchedGrid(depth, nm, d0) {
    if (d0 * nm > depth * (1 + 1e-12)) throw tooThick(nm, d0, depth);
    const d = new Float64Array(nm);
    const h = new Float64Array(nm);
    let q = 1;
    if (nm === 1 || d0 * nm >= depth * (1 - 1e-12)) {
      // An even split: the series has nothing left to grow into.
      d.fill(depth / nm);
    } else {
      const total = (r) => {
        let s = 0;
        let t = d0;
        for (let j = 0; j < nm; j++) { s += t; t *= r; }
        return s - depth;
      };
      let hi = 2;
      while (total(hi) < 0 && hi < 1e300) hi *= 2;
      q = zeroin(total, 1, hi);
      d[0] = d0;
      for (let j = 1; j < nm; j++) d[j] = d[j - 1] * q;
    }
    h[0] = d[0] / (1 + Math.sqrt(q));
    for (let j = 1; j < nm; j++) h[j] = Math.sqrt(d[j - 1] * d[j]);
    return { d, h, q };
  }

  /**
   * The flow-wetted surface per unit volume of flowing water, aw in m2/m3,
   * from whichever way the text gives it -- WETTED_SURFACE itself, 2/APERTURE
   * for a fracture of two walls, or TRANSPORT_RESISTANCE/t_w -- or 0 when it
   * gives none. Two of them given must agree. `tw` is the water's travel time
   * along the column, which F is divided by: TRAVEL_TIME when given, else the
   * length over the pore-water speed.
   */
  function wettedSurface(settings, grid) {
    const u = settings.ADVECTION ? Math.abs(settings.VELOCITY) / (settings.POROSITY > 0 ? settings.POROSITY : 1) : 0;
    const tw = settings.TRAVEL_TIME > 0 ? settings.TRAVEL_TIME : (u > 0 ? grid.L / u : Infinity);
    const said = [];
    if (settings.WETTED_SURFACE > 0) said.push(['WETTED_SURFACE', settings.WETTED_SURFACE]);
    if (settings.APERTURE > 0) said.push(['APERTURE', 2 / settings.APERTURE]);
    if (settings.TRANSPORT_RESISTANCE > 0) {
      if (!(tw < Infinity)) {
        throw new RtmError('TRANSPORT_RESISTANCE is F, the wetted surface times the travel time, and '
          + 'needs a travel time to be divided by: give TRAVEL_TIME, or ADVECTION and a VELOCITY.');
      }
      said.push(['TRANSPORT_RESISTANCE', settings.TRANSPORT_RESISTANCE / tw]);
    }
    for (const key of ['WETTED_SURFACE', 'APERTURE', 'TRANSPORT_RESISTANCE']) {
      if (settings[key] < 0) throw new RtmError(`${key} = ${settings[key]} must be above zero.`);
    }
    const aw = said.length ? said[0][1] : 0;
    for (const [key, v] of said.slice(1)) {
      if (Math.abs(v - aw) > 1e-9 * aw) {
        throw new RtmError(`${said[0][0]} and ${key} disagree: the wetted surface is aw = 2/aperture `
          + `= F/t_w, and they give ${aw} and ${v} m2/m3. Give one of them.`);
      }
    }
    return { aw, tw };
  }

  /**
   * TRAVEL_TIME gives the flow as the time the water takes to cross the
   * column, t_w, which is how a far-field path is described: the pore-water
   * speed is LENGTH/t_w, and VELOCITY, a Darcy flux, is that times the
   * POROSITY. It turns ADVECTION on. A VELOCITY given as well has to say the
   * same thing.
   */
  function flowFromTravelTime(settings, grid) {
    const given = settings.given || new Set();
    if (!given.has('TRAVEL_TIME')) return;
    const tw = settings.TRAVEL_TIME;
    if (!(tw > 0)) throw new RtmError(`TRAVEL_TIME = ${tw} must be above zero.`);
    if (settings.MODE !== 'transport') {
      throw new RtmError('TRAVEL_TIME is the time the water takes to cross the column, and needs '
        + 'MODE = transport.');
    }
    if (given.has('ADVECTION') && !settings.ADVECTION) {
      throw new RtmError('TRAVEL_TIME says the water flows and ADVECTION = 0 says it does not. '
        + 'Leave ADVECTION out: TRAVEL_TIME turns it on.');
    }
    const por = settings.POROSITY > 0 ? settings.POROSITY : 1;
    const v = (por * grid.L) / tw;
    if (given.has('VELOCITY')) {
      if (!(Math.abs(settings.VELOCITY - v) <= 1e-9 * v)) {
        throw new RtmError(`VELOCITY = ${settings.VELOCITY} and TRAVEL_TIME = ${tw} disagree: water `
          + `crossing ${grid.L} m in ${tw} is a VELOCITY of POROSITY*LENGTH/TRAVEL_TIME = ${v}. `
          + 'Give one of them.');
      }
    } else settings.VELOCITY = v;
    settings.ADVECTION = 1;
  }

  /**
   * Kd and Kdf, the two sorption coefficients a far-field path is given,
   * turned into the capacities the equations are written with: Rm =
   * MATRIX_POROSITY + MATRIX_DENSITY*Kd in the rock, and R = 1 + Kdf*aw in
   * the fracture -- Kompartment's r_M and 1/f_df, worked out the same way so
   * that they are the same doubles.
   */
  function sorptionCapacities(species, settings, matrix, aw, warnings) {
    const unused = [];
    for (const s of species) {
      if (s.Kdf !== null) {
        if (!(aw > 0)) {
          throw new RtmError(`Kdf for ${s.name} is sorption per m2 of fracture wall, and needs the wall `
            + 'area a unit volume of water touches: WETTED_SURFACE, APERTURE or '
            + 'TRANSPORT_RESISTANCE.', s.line);
        }
        s.mass = String(1 + s.Kdf * aw);
      }
      if (!matrix && (s.Kd !== null || s.Rm !== null || s.Dm > 0)) unused.push(s.name);
      else if (s.Kd !== null) s.Rm = String(matrix.porosity + matrix.density * s.Kd);
    }
    if (unused.length) {
      const names = unused.length > 1
        ? `${unused.slice(0, -1).join(', ')} and ${unused[unused.length - 1]}` : unused[0];
      warnings.push(`There is no rock matrix, so what the species line${unused.length > 1 ? 's' : ''} `
        + `of ${names} ${unused.length > 1 ? 'say' : 'says'} about the rock (Dm, Rm, Kd) is not used.`);
    }
  }

  /**
   * The rock matrix, or null: how many layers, how deep, and the numbers
   * that turn a layer into a rate -- the wetted surface per unit water volume
   * and the matrix porosity. The layers themselves are laid out by
   * layOutMatrix, once what diffuses into them is known.
   *
   * A text that says anything about the rock has one, of twelve layers unless
   * it says how many; MATRIX_CELLS = 0 has none.
   */
  function makeMatrix(settings, aw, warnings) {
    const given = settings.given || new Set();
    const described = MATRIX_KEYS.filter((k) => given.has(k));
    let nm = settings.MATRIX_CELLS;
    if (!given.has('MATRIX_CELLS') && described.length) nm = DEFAULT_MATRIX_CELLS;
    if (!(nm > 0)) {
      if (given.has('MATRIX_CELLS') && described.length) {
        warnings.push(`MATRIX_CELLS = 0: there is no rock matrix, so ${described.join(', ')} `
          + `${described.length === 1 ? 'is' : 'are'} not used.`);
      }
      return null;
    }
    if (!Number.isInteger(nm)) throw new RtmError(`MATRIX_CELLS must be a whole number, not ${nm}.`);
    // What the model compiled with, said where the settings are read back.
    settings.MATRIX_CELLS = nm;
    if (settings.MODE !== 'transport') {
      throw new RtmError('A rock matrix needs MODE = transport: it sits beside a column, and a batch '
        + 'has none.');
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
    if (!(settings.MATRIX_DENSITY >= 0)) {
      throw new RtmError(`MATRIX_DENSITY = ${settings.MATRIX_DENSITY} must be zero or more.`);
    }
    if (!(settings.MATRIX_FIRST >= 0)) {
      throw new RtmError(`MATRIX_FIRST = ${settings.MATRIX_FIRST} must be a thickness, or 0 to have `
        + 'it worked out.');
    }
    if (!(aw > 0)) {
      throw new RtmError('A rock matrix needs the fracture surface a unit volume of water is in '
        + 'contact with: WETTED_SURFACE in m2/m3, APERTURE (2b) in m, from which it is 2/aperture, '
        + 'or TRANSPORT_RESISTANCE, the F of the SKB parameterisation, from which it is F divided '
        + 'by the travel time.');
    }
    return { n: nm, depth: settings.MATRIX_DEPTH, porosity: settings.MATRIX_POROSITY,
      density: settings.MATRIX_DENSITY, aw, grid: settings.MATRIX_GRID,
      given: settings.MATRIX_FIRST > 0 ? settings.MATRIX_FIRST : null,
      d: null, h: null, centre: null, q: NaN, first: NaN, rule: null };
  }

  /**
   * Lays out the matrix's layers, into `matrix` itself.
   *
   *   reference  FARFCOMP's: a first layer that makes the ratio e, or
   *              MATRIX_FIRST, and nodes at the layers' centres. Exactly as
   *              this page always had them.
   *   matched    Kompartment's: MATRIX_FIRST, or the shallowest of every
   *              species' penetrationScale over RESOLVE, never thicker than
   *              an even split -- one grid for all of them, because a
   *              daughter grows in cell by cell from its parent and the two
   *              must share the cells -- with the nodes interlaced. Where
   *              nothing gives a time scale (no flow and no decay, or
   *              nothing entering the rock) the first layer is FARFCOMP's.
   *
   * `nucs` are the species that enter the rock, with what penetrationScale
   * reads of them -- de, rm, lam, rf and their own Peclet number -- and `tw`
   * the water's travel time.
   */
  function layOutMatrix(matrix, nucs, tw) {
    const { n: nm, depth, aw } = matrix;
    if (matrix.grid === 'reference') {
      matrix.d = layerDepths(depth, nm, aw, matrix.given || 0);
      matrix.h = null;
      matrix.rule = matrix.given ? 'given' : 'e';
    } else {
      let d0 = matrix.given;
      matrix.rule = 'given';
      if (d0 === null) {
        let L = Infinity;
        for (const nuc of nucs) {
          const l = penetrationScale(nuc, { aw, tw, pe: nuc.pe });
          if (l < L) L = l;
        }
        const even = depth / nm;
        if (L < Infinity) {
          d0 = L / RESOLVE;
          if (!(d0 < even)) d0 = even;
          matrix.rule = 'matched';
        } else {
          d0 = nm === 1 ? depth : eRatioFirst(depth, nm, aw);
          matrix.rule = 'e';
        }
      }
      const g = matchedGrid(depth, nm, d0);
      matrix.d = g.d;
      matrix.h = g.h;
    }
    matrix.first = matrix.d[0];
    matrix.q = nm > 1 ? matrix.d[1] / matrix.d[0] : 1;
    matrix.centre = new Float64Array(nm);
    let x = 0;
    for (let j = 0; j < nm; j++) { matrix.centre[j] = x + matrix.d[j] / 2; x += matrix.d[j]; }
    return matrix;
  }

  /**
   * How many cells past a semi-infinite right-hand end stand for the column
   * going on beyond it: EXTRA_CELLS when the text gives it, else
   * Kompartment's count -- the fewest cells that bring rho^n under a tenth.
   *
   * What those cells are for is the one thing a finite grid cannot say: how
   * the water beyond the end pushes back on it. That push is dispersion
   * running upstream, and on this grid it dies away by
   *
   *     rho = D / (D + u*dz)
   *
   * per cell, D the dispersion a cell has and u*dz what advection carries
   * past it -- which, for a Peclet number and no D of the species' own, is
   * Kompartment's (2*N - Pe)/(2*N + Pe). The far end of the last cell is
   * closed by linear extrapolation, itself a second-order guess at what lies
   * beyond, and a tenth of its error is what is left. The most dispersive
   * species decides, since the cells are shared.
   */
  function extraCellCount(settings, grid, species, mobile, peclet) {
    const given = settings.given || new Set();
    if (given.has('EXTRA_CELLS')) {
      const nb = settings.EXTRA_CELLS;
      if (!(nb >= 0) || !Number.isInteger(nb)) {
        throw new RtmError(`EXTRA_CELLS = ${nb} must be a whole number, 0 or more.`);
      }
      return nb;
    }
    const u = Math.abs(settings.VELOCITY) / (settings.POROSITY > 0 ? settings.POROSITY : 1);
    const w = grid.width[grid.n - 1];
    let rho = 0;
    species.forEach((s, si) => {
      if (!mobile[si]) return;
      const D = (settings.DIFFUSION ? s.D : 0)
        + (peclet > 0 ? Math.max(0, (u * grid.L) / peclet - (u * w) / 2) : 0);
      if (D > 0) rho = Math.max(rho, D / (D + u * w));
    });
    if (!(rho > 0)) return 0;
    let k = 0;
    let left = 1;
    while (left > 0.1 && k < 10000) { left *= rho; k++; }
    if (left > 0.1) {
      throw new RtmError(`The dispersion reaches so far upstream that more than ${k} cells past the `
        + 'right-hand end would be needed for RIGHT = semi-infinite: give EXTRA_CELLS, or check D '
        + 'and PECLET against the VELOCITY.');
    }
    return k;
  }

  /**
   * The column with its cells past a semi-infinite end, each as wide as the
   * last cell of the column: centres, widths and faces run on past LENGTH.
   * `n` stays the column's own count -- what a line of the text may name.
   */
  function withExtraCells(grid, nb) {
    if (!nb) return grid;
    const nf = grid.n;
    const w = grid.width[nf - 1];
    const centres = new Float64Array(nf + nb);
    const width = new Float64Array(nf + nb);
    const faces = new Float64Array(nf + nb + 1);
    centres.set(grid.centres);
    width.set(grid.width);
    faces.set(grid.faces);
    for (let k = 0; k < nb; k++) {
      centres[nf + k] = grid.L + (k + 0.5) * w;
      width[nf + k] = w;
      faces[nf + k + 1] = grid.L + (k + 1) * w;
    }
    return { ...grid, centres, width, faces };
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
  /**
   * What a cell is, by the names a per-cell expression may use: x its centre,
   * w its width, xl and xr its faces, i its index -- all of the column cell,
   * in a matrix layer too -- and j and xm the layer and its depth.
   */
  function placeValue(id, grid, g) {
    const i = g.i;
    switch (id) {
      case 'x': return grid.centres[i];
      case 'w': return grid.width[i];
      case 'xl': return grid.faces[i];
      case 'xr': return grid.faces[i + 1];
      case 'i': return i;
      case 'j': return g.j;
      case 'xm': return g.xm;
      default: return undefined;
    }
  }

  function readParameters(lines, grid, geom, tables = new Map()) {
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
      if (name === 't') {
        throw new RtmError('"t" is the time in a rate law, and cannot be a parameter too: give the '
          + 'parameter another name.', line);
      }
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

      let parsed;
      try {
        parsed = FacsimileModel.parseExpression(src, line);
      } catch (e) {
        throw new RtmError(`In "${src}": ${e.message.replace(/^Line \d+: /, '')}`, line);
      }
      const bound = bindTables(parsed, tables, line);
      const ast = bound.ast;
      if (!index.has(name)) {
        index.set(name, values.length);
        order.push(name);
        values.push(new Float64Array(total));
      }
      const into = values[index.get(name)];
      // The cells past a semi-infinite end are the column going on, so a line
      // that reaches the last cell reaches them too.
      const reach = to === cells - 1 ? Infinity : to;
      // A line names cells of the column; the value is worked out for each of
      // them and for every matrix layer behind it, with `j` the layer (0 in
      // the fracture) and `xm` the depth to the layer's centre in metres.
      for (let c = 0; c < total; c++) {
        const g = geom[c];
        if (g.i < from || g.i > reach) continue;
        if (scope === 'fracture' && g.j > 0) continue;
        if (scope === 'matrix' && g.j === 0) continue;
        const own = index.get(name);
        const lookup = bound.lookup((id) => {
          const where2 = placeValue(id, grid, g);
          if (where2 !== undefined) return where2;
          if (index.has(id) && index.get(id) !== own) return values[index.get(id)][c];
          return undefined;
        });
        let v;
        try {
          v = FacsimileModel.evalAst(ast, lookup, {}, line);
        } catch (e) {
          throw new RtmError(`In "${src}": ${e.message.replace(/^Line \d+: /, '')}. A parameter may `
            + 'use x (the cell centre, m), w (its width), xl and xr (its faces), i (its index), '
            + 'the tables and the parameters named above it.', line);
        }
        if (!Number.isFinite(v)) throw new RtmError(`"${src}" is not a number in cell ${g.i}.`, line);
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
      throw new RtmError(`"${name}" is not a species name. ${NAME_RULE}`, line);
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
    /*
      A constant may be arithmetic -- kr = 1.33*10**12 -- and may use the
      constants named before it on the line, so kb = kf/K reads as meant.
      c = [Fe+2] is an ALIAS: in the rate law, c stands for that
      concentration. Both are how skbrtm writes its databases.
    */
    const aliases = new Map();
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
      const alias = /^\[\s*([^\]]+?)\s*\]$/.exec(value);
      if (alias) {
        if (!SPECIES_NAME.test(alias[1])) {
          throw new RtmError(`"${key} = [${alias[1]}]": "${alias[1]}" is not a species name.`, line);
        }
        aliases.set(key, alias[1]);
        continue;
      }
      const v = constValue(value, line, `Parameter ${key}`, (id) => params.get(id));
      params.set(key, v);
    }

    const reversible = arrow === '<=>';
    if (reversible && !(rates.kf || rates.r) ) {
      throw new RtmError('A reversible reaction needs kf (and kb), or r (and rb).', line);
    }
    if (!reversible && !(rates.k || rates.r || rates.kf)) {
      throw new RtmError('A reaction needs k = ... (mass action) or r = ... (a rate law of your own).', line);
    }
    return { reactants, products, params, aliases, rates, reversible, whole, line, text };
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
     2a. Activity: the ionic strength, and what it does to the equilibria
     ====================================================================== */

  /**
   * A species' charge as its name gives it: the sign at the end and the
   * number after it -- H+ 1, SO4-2 -2, UO2+2 2, e- -1 -- and 0 for a name
   * that ends in neither. `z=` on the species line says it where the name
   * does not, or should not: a surface site is no ion in the water.
   */
  function chargeOf(name) {
    const m = /([+-])([0-9]*)$/.exec(name);
    if (!m) return 0;
    return (m[1] === '+' ? 1 : -1) * (m[2] ? Number(m[2]) : 1);
  }

  /**
   * The Debye-Hueckel A, in (kg/mol)^1/2, and B, in (kg/mol)^1/2 per
   * angstrom, of water at tc degrees C and one atmosphere, worked out as
   * PHREEQC 3 works them out: the relative dielectric constant from Bradley
   * and Pitzer (1979, J. Phys. Chem. 83, 1599), the density on the saturation
   * line from Wagner and Pruss (2002, J. Phys. Chem. Ref. Data 31, 387, eq.
   * 2.6) with PHREEQC's fit in pressure on top. At 25 C, 0.5100 and 0.3285.
   */
  function debyeHuckelAB(tc) {
    const T = tc + 273.15;
    const th = 1 - T / 647.096;
    const rhoSat = 322.0 * (1 + 1.99274064 * th ** (1 / 3) + 1.09965342 * th ** (2 / 3)
      - 0.510839303 * th ** (5 / 3) - 1.75493479 * th ** (16 / 3) - 45.5170352 * th ** (43 / 3)
      - 6.7469445e5 * th ** (110 / 3));
    const p0 = 5.1880000e-02 + tc * (-4.1885519e-04 + tc * (6.6780748e-06 + tc * (-3.6648699e-08 + tc * 8.3501912e-11)));
    const p1 = -6.0251348e-06 + tc * (3.6696407e-07 + tc * (-9.2056269e-09 + tc * (6.7024182e-11 + tc * -1.5947241e-13)));
    const p2 = -2.2983596e-09 + tc * (-4.0133819e-10 + tc * (1.2619821e-11 + tc * (-9.8952363e-14 + tc * 2.3363281e-16)));
    const p3 = 7.0517647e-11 + tc * (6.8566831e-12 + tc * (-2.2829750e-13 + tc * (1.8113313e-15 + tc * -4.2475324e-18)));
    // One atmosphere, or the vapour pressure where that is higher.
    const pSat = Math.exp(11.6702 - 3816.44 / (T - 46.13));
    const atm = Math.max(1, pSat);
    const pa = atm - (pSat - 1e-6);
    const rho = (rhoSat + pa * (p0 + pa * (p1 + pa * (p2 + Math.sqrt(pa) * p3)))) / 1e3; // g/cm3
    const d1000 = 3.4279e2 * Math.exp(T * (-5.0866e-3 + T * 9.469e-7));
    const c = -2.0525 + 3.1159e3 / (-1.8289e2 + T);
    const b = -8.0325e3 + 4.2142e6 / T + 2.1417 * T;
    const eps = d1000 + c * Math.log((b + atm * 1.01325) / (b + 1e3));
    const e2 = 1.671008e-3 / (eps * T); // e^2/(eps k T), cm
    const kappa = Math.sqrt(8 * 3.14159265358979 * 6.02252e23 * e2 * rho / 1e3); // 1/cm (mol/kg)^-1/2
    return { A: kappa * e2 / (2 * Math.LN10), B: kappa / 1e8 };
  }

  /**
   * The activity model a text asks for, or null for ACTIVITY = none. Per
   * species, its charge and how its activity coefficient goes with the ionic
   * strength I of its cell:
   *
   *   0  the water itself, a species named H2O: gamma = 1
   *   1  a neutral species: log gamma = b I, with b = 0.1 unless b= is given
   *   2  an ion, Davies: log gamma = -A z^2 (sqrt(I)/(1 + sqrt(I)) - 0.3 I)
   *   3  an ion given a= under debye-huckel, the WATEQ form:
   *      log gamma = -A z^2 sqrt(I)/(1 + B a sqrt(I)) + b I
   *
   * which is PHREEQC's rule, a= and b= being a database's -gamma. I is half
   * the sum of z^2 C over the cell, and the water's activity 1 - 0.017 times
   * the sum of C, both PHREEQC's, with the concentrations read as molalities.
   */
  function activityModel(settings, species, warnings) {
    if (settings.ACTIVITY === 'none') {
      if (settings.given && settings.given.has('TEMPERATURE')) {
        warnings.push('TEMPERATURE sets the activity model\'s A and B and nothing else, and ACTIVITY is none: '
          + 'it does nothing here.');
      }
      return null;
    }
    const tc = settings.TEMPERATURE;
    if (!(tc >= 0 && tc <= 350)) {
      throw new RtmError(`TEMPERATURE = ${tc}: the activity model's A and B are worked out for 0 to 350 C.`);
    }
    const ns = species.length;
    const { A, B } = debyeHuckelAB(tc);
    const z = new Float64Array(ns);
    const form = new Uint8Array(ns);
    const a = new Float64Array(ns);
    const b = new Float64Array(ns);
    const solute = new Uint8Array(ns).fill(1);
    species.forEach((sp, s) => {
      // The water itself, and a pure phase: activity 1, and no solute. An
      // exchanger and the species on it are no solutes either, and carry no
      // charge into I: their coefficients are set with the exchange (exchangeSetup).
      // Nor is the electron, whose coefficient is 1: its activity is solved for.
      if (sp.name === 'H2O' || sp.mineral || sp.exchange || sp.exchanger || sp.electron) { solute[s] = 0; return; }
      z[s] = sp.z !== null ? sp.z : chargeOf(sp.name);
      if (!z[s]) { form[s] = 1; b[s] = sp.dhb !== null ? sp.dhb : 0.1; return; }
      if (settings.ACTIVITY === 'debye-huckel' && sp.dha !== null) {
        form[s] = 3;
        a[s] = sp.dha;
        b[s] = sp.dhb !== null ? sp.dhb : 0;
        return;
      }
      form[s] = 2;
      if (sp.dha !== null || sp.dhb !== null) {
        warnings.push(`Line ${sp.line}: ${sp.name} is an ion and ACTIVITY = ${settings.ACTIVITY}: `
          + (settings.ACTIVITY === 'davies' ? 'Davies takes no a or b, and they are not used.'
            : 'b without a is not used; give a as well for the WATEQ form.'));
      }
    });
    return { kind: settings.ACTIVITY, temperature: tc, A, B, ns, z, zg: Float64Array.from(z), form, a, b, solute,
      ex: null };
  }

  /**
   * One cell's activity coefficients, from the concentrations C[off ..
   * off + ns): ln gamma into lnG and d(ln gamma)/dI into dG, species by
   * species. Returns the ionic strength and the water's ln a and its
   * derivative in any one solute's concentration. Below an ionic strength of
   * 1e-10 the strength is taken as that, as PHREEQC takes it, and its
   * derivatives as zero.
   */
  function activityAt(act, C, off, lnG, dG, cell) {
    const ns = act.ns;
    let I = 0;
    let sum = 0;
    for (let s = 0; s < ns; s++) {
      const c = C[off + s];
      const z = act.z[s];
      if (z) I += z * z * c;
      if (act.solute[s]) sum += c;
    }
    I *= 0.5;
    const low = !(I > 1e-10);
    if (low) I = 1e-10;
    const sq = Math.sqrt(I);
    const A = act.A * Math.LN10;
    for (let s = 0; s < ns; s++) {
      // The charge in the coefficient: the species' own, or on an exchanger its ion's.
      const z2 = act.zg[s] * act.zg[s];
      switch (act.form[s]) {
        case 1:
          lnG[s] = Math.LN10 * act.b[s] * I;
          dG[s] = Math.LN10 * act.b[s];
          break;
        case 2: {
          const one = 1 + sq;
          lnG[s] = -A * z2 * (sq / one - 0.3 * I);
          dG[s] = -A * z2 * (0.5 / (sq * one * one) - 0.3);
          break;
        }
        case 3: {
          const den = 1 + act.B * act.a[s] * sq;
          lnG[s] = -A * z2 * sq / den + Math.LN10 * act.b[s] * I;
          dG[s] = -A * z2 * 0.5 / (sq * den * den) + Math.LN10 * act.b[s];
          break;
        }
        default:
          lnG[s] = 0;
          dG[s] = 0;
      }
      if (low) dG[s] = 0;
    }
    /*
      On an exchanger, PHREEQC's Gaines-Thomas: the activity is the
      equivalent fraction, n C over the capacity of the cell, n the sites the
      species takes, times its ion's coefficient to the ion's power in the
      relation. ln(n/capacity) is the cell's, set when the capacity is known.
    */
    const ex = act.ex;
    if (ex) {
      const at = (cell === undefined ? Math.round(off / ns) : cell) * ns;
      for (const s of ex.list) {
        lnG[s] = ex.pw[s] * lnG[s] + ex.shift[at + s];
        dG[s] *= ex.pw[s];
      }
    }
    let aw = 1 - 0.017 * sum;
    const dry = !(aw > 1e-6);
    if (dry) aw = 1e-6;
    return { I, lnAw: Math.log(aw), dAw: dry ? 0 : -0.017 / aw };
  }

  /**
   * Activities without ACTIVITY: every coefficient 1, the water's activity 1,
   * and the charges the names give, which I() in a rate law reads.
   */
  function noActivity(species) {
    const ns = species.length;
    const z = Float64Array.from(species, (sp) => (sp.mineral || sp.exchange || sp.exchanger || sp.electron
      || sp.name === 'H2O' ? 0 : (sp.z !== null ? sp.z : chargeOf(sp.name))));
    return { kind: 'none', A: 0, B: 0, ns, z, zg: new Float64Array(ns), form: new Uint8Array(ns),
      a: new Float64Array(ns), b: new Float64Array(ns), solute: new Uint8Array(ns), ex: null };
  }

  /**
   * ION EXCHANGE, as PHREEQC has it: Gaines-Thomas.
   *
   *   X-     exchanger  0.0011            the sites, and the capacity of every cell
   *   NaX    exchange   a=4.08 b=0.082    a species on them
   *   Na+ + X- <=> NaX, logK = 0
   *   Ca+2 + 2 X- <=> CaX2, logK = 0.8
   *
   * The exchanger is no amount: PHREEQC's master species X-, whose activity
   * is solved for and which counts in no total. A species on it has for its
   * activity its equivalent fraction, n C over the capacity of its cell, n
   * the sites it takes -- read off the relations, an exchanger taking one and
   * an ion none, so that each relation keeps the sites -- and, given a and b,
   * times its ion's activity coefficient to the ion's power in the relation
   * that forms it from the exchanger: the WATEQ form under debye-huckel, or
   * Davies where a and b are both 0 or under davies. PHREEQC's rule for
   * EXCHANGE_SPECIES, -gamma a b. Without ACTIVITY the fraction stands alone,
   * so that the exchange is Gaines-Thomas whatever the water does.
   *
   * Returns the activity model with the exchange in it (one made for it when
   * ACTIVITY is none), or `act` itself when there is no exchanger.
   */
  function exchangeSetup(species, equilibria, act, settings, warnings) {
    const ns = species.length;
    const exchangers = [];
    const onSites = [];
    species.forEach((sp, k) => { if (sp.exchanger) exchangers.push(k); if (sp.exchange) onSites.push(k); });
    if (!exchangers.length && !onSites.length) return act;
    const names = (ks) => ks.map((k) => species[k].name).join(', ');
    if (!exchangers.length) {
      throw new RtmError(`${names(onSites)} ${onSites.length > 1 ? 'are' : 'is'} on an exchanger, and no species is `
        + 'one: give its sites a line of their own, X- exchanger 0.001.', species[onSites[0]].line);
    }
    // The sites each species takes, and whose: an exchanger 1, an ion 0, a
    // species on an exchanger what its relations make it.
    const n = new Float64Array(ns);
    const of = new Int32Array(ns).fill(-1);
    exchangers.forEach((k, x) => { n[k] = 1; of[k] = x; });
    for (const k of onSites) n[k] = NaN;
    const carries = (k) => species[k].exchange || species[k].exchanger;
    for (let changed = true; changed;) {
      changed = false;
      for (const eq of equilibria) {
        const open = eq.net.filter(([k]) => Number.isNaN(n[k]));
        if (open.length !== 1) continue;
        const [j, nu] = open[0];
        let sum = 0;
        let owner = -1;
        for (const [k, c] of eq.net) {
          if (k === j) continue;
          sum += c * n[k];
          if (carries(k)) owner = of[k];
        }
        const v = -sum / nu;
        if (owner < 0 || !(v > 0)) {
          throw new RtmError(`"${eq.text}" gives ${species[j].name} no sites: a species on an exchanger is formed `
            + 'from its exchanger, Na+ + X- <=> NaX, or from another species on it.', eq.line);
        }
        n[j] = v;
        of[j] = owner;
        changed = true;
      }
    }
    const lost = onSites.filter((k) => Number.isNaN(n[k]));
    if (lost.length) {
      throw new RtmError(`${names(lost)} ${lost.length > 1 ? 'are' : 'is'} on an exchanger, and no relation in `
        + '<EQUILIBRIUM> forms it from one: Na+ + X- <=> NaX, logK = 0.', species[lost[0]].line);
    }
    for (const eq of equilibria) {
      const owners = new Set(eq.net.filter(([k]) => carries(k)).map(([k]) => of[k]));
      if (!owners.size) continue;
      if (owners.size > 1) {
        throw new RtmError(`"${eq.text}" joins two exchangers, ${names([...owners].map((x) => exchangers[x]))}: a `
          + 'relation is on one.', eq.line);
      }
      let sum = 0;
      let scale = 0;
      for (const [k, c] of eq.net) { sum += c * n[k]; scale += Math.abs(c * n[k]); }
      if (Math.abs(sum) > 1e-9 * scale) {
        const side = (sg) => eq.net.filter(([, c]) => c * sg > 0).reduce((t, [k, c]) => t + Math.abs(c) * n[k], 0);
        throw new RtmError(`"${eq.text}" does not keep the exchanger's sites: ${fmtSites(side(-1))} on the left and `
          + `${fmtSites(side(1))} on the right.`, eq.line);
      }
      if (eq.kf !== null && eq.net.some(([k]) => species[k].exchanger)) {
        throw new RtmError(`"${eq.text}" has the exchanger in it, which is no amount and cannot react at a rate: `
          + 'it is held (EQUILIBRATE). Exchange at a rate is written between species on the exchanger, '
          + 'Ca+2 + 2 NaX <=> CaX2 + 2 Na+, with its kf.', eq.line);
      }
      if (eq.mineral >= 0) {
        throw new RtmError(`"${eq.text}" has a mineral and an exchanger in it: a relation is one or the other.`, eq.line);
      }
    }
    for (const k of exchangers) {
      if (!equilibria.some((eq) => eq.net.some(([s]) => s === k))) {
        throw new RtmError(`${species[k].name} is an exchanger and in no relation: Na+ + ${species[k].name} <=> NaX, `
          + 'logK = 0, puts a species on it.', species[k].line);
      }
    }

    const out = act || noActivity(species);
    out.form = Uint8Array.from(out.form);
    const pw = new Float64Array(ns);
    const ion = new Int32Array(ns).fill(-1);
    let unused = false;
    for (const k of onSites) {
      const sp = species[k];
      pw[k] = 1;
      // The ion: the one other species of a relation that forms this one from its exchanger.
      for (const eq of equilibria) {
        if (!eq.net.some(([s]) => s === k) || !eq.net.some(([s]) => s === exchangers[of[k]])) continue;
        const others = eq.net.filter(([s]) => s !== k && s !== exchangers[of[k]]);
        if (others.length !== 1 || eq.water) continue;
        ion[k] = others[0][0];
        pw[k] = Math.abs(others[0][1] / eq.net.find(([s]) => s === k)[1]);
        break;
      }
      if (sp.dha === null) continue;
      if (!act) { unused = true; continue; }
      if (ion[k] < 0) {
        throw new RtmError(`${sp.name} is given a and b, which give it its ion's activity coefficient, and no relation `
          + `forms it from ${species[exchangers[of[k]]].name} and one ion: Ca+2 + 2 X- <=> CaX2.`, sp.line);
      }
      const isp = species[ion[k]];
      out.zg[k] = isp.z !== null ? isp.z : chargeOf(isp.name);
      if (settings.ACTIVITY === 'debye-huckel' && !(sp.dha === 0 && sp.dhb === 0)) {
        out.form[k] = 3;
        out.a[k] = sp.dha;
        out.b[k] = sp.dhb;
      } else out.form[k] = 2;
      if (!out.zg[k]) out.form[k] = 0;
    }
    if (unused) {
      warnings.push('ACTIVITY is none: a species on an exchanger has its equivalent fraction for its activity, and '
        + 'the a and b given to one are not used.');
    }
    const site = Int8Array.from(species, (sp) => (sp.exchange ? 1 : sp.exchanger ? 2 : 0));
    out.ex = { list: onSites, exchangers, n, of, pw, ion, site, shift: null, capacity: null };
    return out;
  }

  /** A number of sites as a reader would write it. */
  function fmtSites(v) { return String(+v.toPrecision(6)); }

  /**
   * REDOX, as PHREEQC has it: the electron.
   *
   *   e-     electron  pe=4             the electron, and the pe a start is speciated at
   *   Fe+2 <=> Fe+3 + e-, logK = -13.02
   *   SO4-2 + 9 H+ + 8 e- <=> HS- + 4 H2O, logK = 33.65
   *
   * The electron is no amount: PHREEQC's e-, whose activity, 10^-pe, is
   * solved for in every cell and which counts in no total. A couple tied to
   * it is in equilibrium at that pe, and every couple tied to it with every
   * other: the totals the relations conserve then hold the electrons the
   * couples have between them, and a reaction at a rate that moves some
   * moves that total. A couple left out keeps its valence states apart, as
   * PHREEQC's decoupled elements do. One electron to a model, in at least one
   * relation, and in no fast pair: what holds it is EQUILIBRATE.
   *
   * Returns the electron's index, or -1.
   */
  function electronSetup(species, equilibria) {
    const ks = [];
    species.forEach((sp, k) => { if (sp.electron) ks.push(k); });
    if (!ks.length) return -1;
    if (ks.length > 1) {
      throw new RtmError(`${ks.map((k) => species[k].name).join(' and ')} are each given as the electron: a model `
        + 'has one, whose activity is the pe of each cell.', species[ks[1]].line);
    }
    const [e] = ks;
    const name = species[e].name;
    if (!equilibria.some((eq) => eq.net.some(([s]) => s === e))) {
      throw new RtmError(`${name} is the electron and in no relation: Fe+2 <=> Fe+3 + ${name}, logK = -13.02, `
        + 'ties a couple to it.', species[e].line);
    }
    for (const eq of equilibria) {
      if (eq.kf !== null && eq.net.some(([s]) => s === e)) {
        throw new RtmError(`"${eq.text}" has the electron in it, which is no amount and cannot react at a rate: it `
          + 'is held (EQUILIBRATE). Redox at a rate is a reaction in <REACTIONS> between species, '
          + 'Fe+2 + 0.25 O2 + H+ => Fe+3 + 0.5 H2O.', eq.line);
      }
    }
    return e;
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
        const v = constValue(m[2], line, m[1]);
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
      /*
        H2O, when it is not one of the species, is the water itself: its
        activity enters the relation, 1 unless ACTIVITY says otherwise, and it
        is never a concentration. So a relation can be written as a database
        writes it, CO2 + H2O <=> H+ + HCO3-, and means what it meant without.
      */
      const solvent = !index.has('H2O');
      let water = 0;
      const bump = (name, c) => {
        if (solvent && name === 'H2O') { water += c; return; }
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
      const species = (side) => (solvent ? side.filter(([, name]) => name !== 'H2O') : side);
      return { net, lnK, kf, line, text, reactants: species(reactants), products: species(products), water };
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
  /** Each species' largest concentration over the cells of a state. */
  function abundanceOf(y, ns, nc) {
    const out = new Float64Array(ns);
    for (let c = 0; c < nc; c++) for (let s = 0; s < ns; s++) out[s] = Math.max(out[s], Math.abs(y[c * ns + s]));
    return out;
  }

  function equilibriumSpecies(equilibria) {
    const seen = new Set();
    for (const eq of equilibria) for (const [si] of eq.net) seen.add(si);
    return [...seen].sort((a, b) => a - b);
  }

  function conservationBasis(equilibria, ns, fixed, abundance, site) {
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

    /*
      Row-reduce, remembering which column each pivot landed in -- the
      columns taken least abundant first, when the abundances are known.
      Each column a pivot lands in is a species the relations work out from
      the others; each one left free makes a total, 1 at itself and 0 at every
      other free one. Left free, a trace species makes a total that is mostly
      the major ones -- the other free species stand for theirs only in
      combination -- and in it a trace species is a part in 1e10 of the
      total, which arithmetic resolves to a part in a million: a speciation
      off by that, and a held run whose Newton iteration cannot settle it.
      Free, the most abundant species of each element make the totals that
      element by element, so every species counts in a total of its own size.
    */
    const order = [...Array(ns).keys()];
    if (abundance) {
      order.sort((a, b) => (Math.abs(abundance[a]) - Math.abs(abundance[b])) || a - b);
    }
    /*
      With an exchanger, the species on it first and the exchanger last,
      whatever their sizes: the totals are then PHREEQC's, the exchanger's
      the capacity -- the sites the species on it take -- and each ion's
      itself and its species on the exchanger. The exchanger is no amount and
      counts in no total, and taken otherwise its total would be the sites
      less some ion, a difference of two large numbers. The electron, no
      amount either, goes last for the same reason: its total is then the
      electrons the couples hold, made of the species that hold them.
    */
    if (site) {
      const rank = (k) => (site[k] === 1 ? 0 : site[k] === 2 ? 2 : 1);
      order.sort((a, b) => rank(a) - rank(b));
    }
    const pivotOf = [];
    let row = 0;
    for (let oi = 0; oi < ns && row < ne; oi++) {
      const col = order[oi];
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
    // The free column each total was made from: its own species, where it is 1
    // and every other total 0. holdEquilibria puts the total's equation there.
    const free = [];
    for (let col = 0; col < ns; col++) {
      if (isPivot.has(col) || !active.has(col)) continue;
      const u = new Float64Array(ns);
      u[col] = 1;
      pivotOf.forEach((pc, r) => { u[pc] = -A[r][col]; });
      basis.push(u);
      free.push(col);
    }
    basis.free = free;
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
   * Converged when every equilibrium is met to `tol` in ln K and every total
   * to `tol` of its size -- relative, so that a trace total of 1e-9 is held as
   * closely as one of 1e-3 -- and then given one more Newton step, which from
   * there takes the residual to rounding: a run that holds the equilibria
   * starts from this, and conserves to rounding what it starts with.
   *
   * @param {object} model   from compile()
   * @param {Float64Array} [y]  the state to equilibrate; the initial one by default
   * @param {object} [opts]  { tol, maxIter, floor }
   * @returns {{y: Float64Array, cells: object[]}}
   */
  function speciate(model, y, opts = {}) {
    // opts.equilibria: some of the relations only, and the species they take;
    // opts.fixed: the species held where they stand, in place of the model's
    // fixed ones -- the electron, at the pe a start is given.
    const eqs = opts.equilibria || model.equilibria;
    if (!eqs || !eqs.length) return { y: Float64Array.from(y || model.initialState()), cells: [] };
    const ns = model.speciesNames.length;
    const out = Float64Array.from(y || model.initialState());
    // Species on an exchanger first, and last what counts in no total.
    const site = model.rank || null;
    // The species that take part, and where each sits in the small system. A
    // fixed one is held: it appears in the equilibrium rows as a known number,
    // never as an unknown.
    const held = opts.fixed || model.fixed || [];
    const basis = opts.equilibria || opts.fixed
      ? conservationBasis(eqs, ns, held, abundanceOf(out, ns, model.cells), site) : model.conservation;
    const ne = eqs.length;
    const nb = basis.length;
    const cells = [];
    const part = equilibriumSpecies(eqs).filter((si) => !held[si]);
    const na = part.length;
    if (ne + nb !== na) {
      const nheld = equilibriumSpecies(eqs).length - na;
      throw new RtmError(`The equilibria give ${ne} equations and ${nb} conserved totals, which is `
        + `${ne + nb} for the ${na} species they are free to move`
        + (nheld ? ` (${nheld} more of them are fixed)` : '')
        + '. Fixing one species of an equilibrium leaves it solvable; fixing two of the same one '
        + 'usually does not, and an equilibrium that repeats another has the same effect.');
    }
    const sys = cellSystem(eqs, part, basis.map((v) => Float64Array.from(part, (si) => v[si])), model.mineral,
      model.act || null, ns, site);
    // An exchanger, or the electron, counts in no total: it is no amount.
    const w = Float64Array.from(part, (si) => (site && site[si] === 2 ? 0 : 1));
    for (let cell = 0; cell < model.cells; cell++) {
      const b = cell * ns;
      // The totals to hold, taken from the state as it stands; a mineral
      // there at the start is taken to be present until it proves otherwise.
      const totals = sys.U.map((row) => {
        let t = 0;
        for (let k = 0; k < na; k++) t += row[k] * w[k] * out[b + part[k]];
        return t;
      });
      const present = Uint8Array.from(eqs, (eq, j) => (sys.minOf[j] < 0 || out[b + part[sys.minOf[j]]] > 0 ? 1 : 0));
      const res = speciateCell(sys, out, b, totals, w, present,
        { tol: opts.tol, maxIter: opts.maxIter, floor: opts.floor, activeSet: true, cell });
      if (res.why === 'singular') throw new RtmError(`The speciation matrix is singular in cell ${cell}.`);
      cells.push({ cell, converged: res.converged, iterations: res.iterations, residual: res.residual,
        minerals: sys.minOf.reduce((n, k, j) => n + (k >= 0 && present[j] ? 1 : 0), 0) });
    }
    return { y: out, cells };
  }

  /**
   * Loads each exchanger given a capacity from the water of its cell: the
   * species on it in equilibrium with that water, which is left as it is,
   * their sites the capacity. PHREEQC's EXCHANGE with -equilibrate.
   *
   * With the water fixed, each species on the exchanger follows from its
   * relation and what it is formed from, in the order the relations form
   * them: ln C = c + n u, u the exchanger's ln a and n its sites. What is
   * left is one equation in u, ln(sum n e^(c + n u)) = ln(capacity), which
   * is convex and rises with u, and Newton settles it from anywhere. An ion
   * the water has none of puts none of its species on the exchanger.
   */
  function loadExchangers(model, y) {
    const ex = model.act.ex;
    const act = model.act;
    const ns = model.speciesNames.length;
    const nx = ex.exchangers.length;
    const lnG = new Float64Array(ns);
    const dG = new Float64Array(ns);
    const lnA = new Float64Array(ns);
    const slope = new Float64Array(ns);
    ex.exchangers.forEach((k, x) => {
      const name = model.speciesNames[k];
      const mine = (si) => ex.site[si] && ex.of[si] === x;
      const eqs = model.equilibria.filter((eq) => eq.net.some(([si]) => mine(si)));
      const on = ex.list.filter((j) => ex.of[j] === x);
      if (eqs.length !== on.length) {
        throw new RtmError(`${name} has ${on.length} species on it and ${eqs.length} relations for them: each `
          + 'species on an exchanger is formed in one relation of its own, and then the load a water gives it '
          + 'is settled.');
      }
      // The order the relations form the species in, from the exchanger out.
      const known = new Set([k]);
      const order = [];
      for (let grew = true; grew;) {
        grew = false;
        for (const eq of eqs) {
          if (order.some((o) => o.eq === eq)) continue;
          const open = eq.net.filter(([si]) => mine(si) && !known.has(si));
          if (open.length !== 1) continue;
          order.push({ eq, j: open[0][0], nu: open[0][1] });
          known.add(open[0][0]);
          grew = true;
        }
      }
      for (const q of ex.load) {
        if (q % nx !== x) continue;
        const c = (q - x) / nx;
        const b = c * ns;
        const cap = ex.capacity[q];
        const water = activityAt(act, y, b, lnG, dG, c);
        // Each species' ln a at u = 0, and how it goes with u.
        lnA[k] = 0;
        slope[k] = 1;
        for (const { eq, j, nu } of order) {
          let r = eq.lnK - (eq.water ? eq.water * water.lnAw : 0);
          let d = 0;
          for (const [si, v] of eq.net) {
            if (si === j) continue;
            if (mine(si)) { r -= v * lnA[si]; d -= v * slope[si]; } else r -= v * (Math.log(y[b + si]) + lnG[si]);
          }
          lnA[j] = r / nu;
          slope[j] = d / nu;
        }
        const g = (u) => {
          let m = -Infinity;
          for (const j of on) m = Math.max(m, lnA[j] - lnG[j] + slope[j] * u);
          let sum = 0;
          let dsum = 0;
          for (const j of on) {
            const e = ex.n[j] * Math.exp(lnA[j] - lnG[j] + slope[j] * u - m);
            sum += e;
            dsum += e * slope[j];
          }
          return [m + Math.log(sum) - Math.log(cap), dsum / sum];
        };
        let u = 0;
        let ok = false;
        for (let it = 0; it < 200; it++) {
          const [v, dv] = g(u);
          if (!Number.isFinite(v)) break;
          const step = v / dv;
          u -= step;
          if (Math.abs(step) < 1e-14 * Math.max(1, Math.abs(u))) { ok = true; break; }
        }
        if (!ok) {
          throw new RtmError(`${name} could not be loaded from the water${model.cells > 1 ? ` of cell ${c}` : ''}: `
            + 'it has none of the ions that go on it.');
        }
        for (const j of on) y[b + j] = Math.exp(lnA[j] - lnG[j] + slope[j] * u);
        y[b + k] = Math.exp(u);
      }
    });
  }

  /**
   * The small system a cell is speciated in, set up once for a set of
   * relations: who takes part and how each is solved for, and what each
   * total counts.
   *
   *   part     the species taking part: in a relation, and not fixed
   *   at       a species' place in part, or -1
   *   lin      1 where the unknown is the amount itself -- a mineral, which
   *            may reach zero -- and 0 where it is ln C
   *   U        the totals, one row each, over part
   *   minOf    a relation's mineral, as its place in part, or -1
   *   minNu    that mineral's coefficient: which way its saturation runs
   *   exch     1 where the unknown is no amount -- an exchanger, the
   *            electron -- whose ln a it is and which no total counts
   *   rank     the model's: 1 on an exchanger, 2 no amount (see conservationBasis)
   */
  function cellSystem(eqs, part, U, mineral, act, ns, rank) {
    const at = new Int32Array(ns).fill(-1);
    part.forEach((si, k) => { at[si] = k; });
    const isMin = Uint8Array.from({ length: ns }, (_, si) => (mineral && mineral[si] ? 1 : 0));
    const exch = rank ? Uint8Array.from(part, (si) => (rank[si] === 2 ? 1 : 0)) : null;
    return {
      eqs, ne: eqs.length, nb: U.length, na: part.length, part, at, U, act, ns, isMin,
      lin: Uint8Array.from(part, (si) => isMin[si]),
      minOf: Int32Array.from(eqs, (eq) => (eq.mineral >= 0 && at[eq.mineral] >= 0 ? at[eq.mineral] : -1)),
      minNu: Float64Array.from(eqs, (eq) => eq.mineralNu || 0),
      lnG: act ? new Float64Array(ns) : null,
      dG: act ? new Float64Array(ns) : null,
      cellC: new Float64Array(ns),
      exch: exch && exch.some((v) => v) ? exch : null,
      rank: rank || null,
    };
  }

  /**
   * One cell's speciation: the unknowns of sys.part such that every relation
   * holds -- a mineral's saturation only while `present` says there is some
   * of it, and its amount zero while there is none -- and every total is
   * `totals`. C holds the cell's concentrations from `off`: read for the
   * species not taking part, written back for those that do. `w` weighs each
   * species in the totals (its capacity R), or null for 1.
   *
   * Converged when every relation is met to `tol` in ln K and every total to
   * `tol` of its size -- relative, so that a trace total of 1e-9 is held as
   * closely as one of 1e-3 -- and then given one more Newton step, which from
   * there takes the residual to rounding.
   *
   * With opts.activeSet it also finds which minerals are there, as PHREEQC
   * does: one that would have to be less than none of dissolves away, one the
   * water is supersaturated in and has none of precipitates, one change at a
   * time until neither is left. `present` is updated in place.
   *
   * @returns {{converged, iterations, residual, x, why}}  x the unknowns:
   *   ln C, or a mineral's amount
   */
  function speciateCell(sys, C, off, totals, w, present, opts = {}) {
    const { eqs, ne, nb, na, part, at, U, act, lin, minOf, minNu, isMin } = sys;
    const tol = opts.tol || 1e-10;
    const maxIter = opts.maxIter || 100;
    const floor = opts.floor || 1e-300;
    const x = new Float64Array(na);
    for (let k = 0; k < na; k++) {
      const c = C[off + part[k]];
      x[k] = lin[k] ? c : Math.log(Math.max(c, floor));
    }
    const cell = opts.cell !== undefined ? opts.cell : Math.round(off / sys.ns);
    let big = 0;
    for (let q = 0; q < nb; q++) big = Math.max(big, Math.abs(totals[q]));
    // The system's own scratch, refilled at every iteration: a held run
    // speciates every cell at every evaluation, and allocating these each time
    // was most of what that cost.
    if (!sys.scratch) {
      sys.scratch = { J: Array.from({ length: na }, () => new Float64Array(na)), F: new Float64Array(na),
        val: new Float64Array(na) };
    }
    const { J, F, val } = sys.scratch;
    let iterations = 0;
    let residual = Infinity;
    let why = '';

    // The values, and with ACTIVITY the coefficients, at x.
    const evaluate = () => {
      for (let k = 0; k < na; k++) val[k] = lin[k] ? x[k] : Math.exp(x[k]);
      if (!act) return null;
      const cc = sys.cellC;
      for (let s = 0; s < sys.ns; s++) cc[s] = C[off + s];
      for (let k = 0; k < na; k++) cc[part[k]] = val[k];
      return activityAt(act, cc, 0, sys.lnG, sys.dG, cell);
    };
    // Relation j as a residual, sum of nu ln a - ln K, a mineral adding
    // nothing; with `row`, its derivatives in x as well.
    const relation = (j, water, row) => {
      const eq = eqs[j];
      let r = -eq.lnK;
      let G = 0;
      for (const [si, nu] of eq.net) {
        if (isMin[si]) continue;
        if (act) { r += nu * sys.lnG[si]; G += nu * sys.dG[si]; }
        const k = at[si];
        // A fixed species contributes a constant, and no column.
        if (k < 0) { r += nu * Math.log(Math.max(C[off + si], floor)); continue; }
        r += nu * x[k];
        if (row) row[k] += nu;
      }
      if (act) {
        const wv = eq.water || 0;
        if (wv) r += wv * water.lnAw;
        if (row) {
          for (let k = 0; k < na; k++) {
            if (lin[k]) continue;
            const si = part[k];
            let d = G * 0.5 * act.z[si] * act.z[si];
            if (wv && act.solute[si]) d += wv * water.dAw;
            if (d) row[k] += d * val[k];
          }
        }
      }
      return r;
    };
    // A mineral's saturation index, ln(IAP/K), whichever side it is written on.
    const saturation = (j, water) => (minNu[j] < 0 ? 1 : -1) * relation(j, water, null);

    // None of a mineral is exactly none: its amount is set, not iterated
    // towards -- a damped step would only halve it, and leave 1e-30 of a
    // mineral the water is far from saturated in.
    const pin = () => {
      for (let j = 0; j < ne; j++) if (minOf[j] >= 0 && !present[j]) x[minOf[j]] = 0;
    };
    const solve = () => {
      let converged = false;
      pin();
      for (let it = 0; it < maxIter; it++) {
        iterations++;
        const water = evaluate();
        let norm = 0;
        for (let j = 0; j < ne; j++) {
          J[j].fill(0);
          const km = minOf[j];
          if (km >= 0 && !present[j]) {
            // None of the mineral: its amount is zero, and the relation waits.
            F[j] = x[km];
            J[j][km] = 1;
            norm = Math.max(norm, Math.abs(x[km]) / Math.max(big, 1e-300));
            continue;
          }
          F[j] = relation(j, water, J[j]);
          norm = Math.max(norm, Math.abs(F[j]));
        }
        // The totals: d(sum U w C)/du = U w C, and U w for an amount.
        for (let q = 0; q < nb; q++) {
          const row = ne + q;
          J[row].fill(0);
          let r = -totals[q];
          let scale = Math.abs(totals[q]);
          for (let k = 0; k < na; k++) {
            const u = U[q][k];
            // An exchanger is no amount: it counts in no total.
            if (!u || (sys.exch && sys.exch[k])) continue;
            const uw = w ? u * w[k] : u;
            const v = uw * val[k];
            r += v;
            scale += Math.abs(v);
            J[row][k] = lin[k] ? uw : v;
          }
          F[row] = r;
          norm = Math.max(norm, Math.abs(r) / Math.max(scale, 1e-300));
        }
        residual = norm;
        if (norm < tol) converged = true;
        // Settled where it started, and asked for no more than that: a held
        // run's projection, at an iterate that is already its speciation.
        if (converged && it === 0 && opts.asStarted) break;
        // J and F are made afresh at every iteration, so the elimination may use them up.
        const step = solveInPlace(J, F, na);
        if (!step) {
          if (converged) break;
          why = 'singular';
          return false;
        }
        // Damped, and capped: an undamped step in log space can move a
        // concentration by e^40 and leave the iteration nowhere near where it
        // started. Two is the usual cap and behaves well here; an amount is
        // not in log space and sets no cap of its own.
        let damp = 1;
        for (let k = 0; k < na; k++) if (!lin[k]) damp = Math.min(damp, 2 / Math.max(Math.abs(step[k]), 2));
        let largest = 0;
        for (let k = 0; k < na; k++) {
          x[k] -= damp * step[k];
          if (!lin[k]) largest = Math.max(largest, Math.abs(damp * step[k]));
        }
        pin();
        // Converged, and that was the step that takes it to rounding; or a
        // step that moves no concentration by more than a part in 1e12 at a
        // residual already small: as far as the arithmetic goes.
        if (converged || (largest < 1e-12 && norm < 1e-8 && opts.roundOff)) { converged = true; break; }
      }
      return converged;
    };

    /*
      WHERE A SPECIES AT NONE STARTS. An exchanger or the electron with no
      activity yet -- a state written by hand, its species given -- starts
      where its relations put it, the species around it as they stand: least
      squares in its one unknown over the relations whose other species are
      all there. Any other species that starts at none -- a valence state
      the water is given none of, at a pe -- starts where a relation puts it
      once the rest are there, and no higher than the largest total; one no
      relation can place, at a part in 1e12 of that total. From ln C =
      ln(1e-300) the damped iteration would take hundreds of steps to arrive,
      and stop before it did.
    */
    {
      const have = new Set();
      for (let k = 0; k < na; k++) if (lin[k] || C[off + part[k]] > 0) have.add(part[k]);
      const there = (j, skip) => eqs[j].net.every(([si]) => si === skip || have.has(si) || at[si] < 0 && C[off + si] > 0);
      const guess = [];
      for (let k = 0; k < na; k++) if (sys.exch && sys.exch[k] && !have.has(part[k])) { x[k] = 0; guess.push(k); }
      const zero = [];
      for (let k = 0; k < na; k++) if (!(sys.exch && sys.exch[k]) && !have.has(part[k])) zero.push(k);
      const top = Math.log(Math.max(big, floor));
      if (guess.length || zero.length) {
        const water = evaluate();
        for (const k of guess) {
          let num = 0;
          let den = 0;
          for (let j = 0; j < ne; j++) {
            const mine = eqs[j].net.find(([si]) => si === part[k]);
            if (!mine || !there(j, part[k])) continue;
            num += mine[1] * relation(j, water, null);
            den += mine[1] * mine[1];
          }
          x[k] = den ? -num / den : 0;
          have.add(part[k]);
        }
        for (let grew = true; grew;) {
          grew = false;
          for (const k of zero) {
            if (have.has(part[k])) continue;
            for (let j = 0; j < ne; j++) {
              const mine = eqs[j].net.find(([si]) => si === part[k]);
              if (!mine || !there(j, part[k])) continue;
              x[k] = 0;
              x[k] = Math.min(-relation(j, water, null) / mine[1], top);
              have.add(part[k]);
              grew = true;
              break;
            }
          }
        }
        for (const k of zero) if (!have.has(part[k])) x[k] = Math.max(top - 12 * Math.LN10, Math.log(floor));
      }
    }

    let ok = solve();
    if (opts.activeSet && ok) {
      const mins = [];
      for (let j = 0; j < ne; j++) if (minOf[j] >= 0) mins.push(j);
      let settled = !mins.length;
      for (let round = 0; round < 4 * mins.length + 4 && !settled && ok; round++) {
        // A mineral that would have to be less than none of: it dissolves away.
        let pick = -1;
        let by = 0;
        for (const j of mins) {
          const m = x[minOf[j]];
          if (present[j] && m < -1e-12 * big && -m > by) { by = -m; pick = j; }
        }
        if (pick >= 0) {
          present[pick] = 0;
          x[minOf[pick]] = 0;
          ok = solve();
          continue;
        }
        // One the water is supersaturated in, and none of it: it precipitates.
        const water = evaluate();
        for (const j of mins) {
          if (present[j]) continue;
          const si = saturation(j, water);
          if (si > 1e-9 && si > by) { by = si; pick = j; }
        }
        if (pick >= 0) {
          present[pick] = 1;
          ok = solve();
          continue;
        }
        settled = true;
      }
      if (ok && !settled) {
        ok = false;
        why = 'which minerals are there could not be settled';
      }
    }
    for (let k = 0; k < na; k++) C[off + part[k]] = lin[k] ? x[k] : Math.exp(x[k]);
    return { converged: ok, iterations, residual, x, why };
  }

  /**
   * The Jacobian of a cell's speciation (speciateCell) at the unknowns in C
   * from `off`: its relations and its totals, rows in that order, in the
   * unknowns of sys.part -- ln C, or an amount -- as speciateCell iterates
   * with it. Also, in `outside`, d(relation)/dC of each species that is not
   * an unknown and that the relations read through the ionic strength or the
   * water's activity, a column each.
   */
  function cellJacobian(sys, C, off, w, present, cell, outside) {
    const { eqs, ne, nb, na, part, at, U, act, lin, minOf, isMin } = sys;
    const J = Array.from({ length: na }, () => new Float64Array(na));
    const O = outside ? Array.from({ length: na }, () => new Float64Array(outside.length)) : null;
    let water = null;
    if (act) water = activityAt(act, C, off, sys.lnG, sys.dG, cell);
    for (let j = 0; j < ne; j++) {
      const km = minOf[j];
      if (km >= 0 && !present[j]) { J[j][km] = 1; continue; }
      const eq = eqs[j];
      let G = 0;
      for (const [si, nu] of eq.net) {
        if (isMin[si]) continue;
        if (act) G += nu * sys.dG[si];
        const k = at[si];
        if (k >= 0) J[j][k] += nu;
      }
      if (!act) continue;
      const wv = eq.water || 0;
      const d = (si) => G * 0.5 * act.z[si] * act.z[si] + (wv && act.solute[si] ? wv * water.dAw : 0);
      for (let k = 0; k < na; k++) {
        if (lin[k]) continue;
        const v = d(part[k]);
        if (v) J[j][k] += v * C[off + part[k]];
      }
      if (O) outside.forEach((si, i) => { O[j][i] = d(si); });
    }
    for (let q = 0; q < nb; q++) {
      const row = ne + q;
      for (let k = 0; k < na; k++) {
        const u = U[q][k];
        if (!u || (sys.exch && sys.exch[k])) continue;
        const uw = w ? u * w[k] : u;
        J[row][k] = lin[k] ? uw : uw * C[off + part[k]];
      }
    }
    return { J, O };
  }

  /** LU with partial pivoting, in place; null when singular. */
  function luFactor(A, n) {
    const piv = new Int32Array(n);
    for (let k = 0; k < n; k++) {
      let p = k;
      let big = Math.abs(A[k][k]);
      for (let i = k + 1; i < n; i++) if (Math.abs(A[i][k]) > big) { big = Math.abs(A[i][k]); p = i; }
      if (!(big > 0)) return null;
      piv[k] = p;
      if (p !== k) { const t = A[p]; A[p] = A[k]; A[k] = t; }
      const rk = A[k];
      for (let i = k + 1; i < n; i++) {
        const ri = A[i];
        const f = ri[k] / rk[k];
        if (!f) continue;
        ri[k] = f;
        for (let j = k + 1; j < n; j++) ri[j] -= f * rk[j];
      }
    }
    return piv;
  }

  /**
   * Solves with luFactor's result, b overwritten by x. The factorization
   * swapped whole rows, multipliers and all, so its L is in the final order:
   * every interchange goes on b first, then L and U, as LAPACK's getrs does.
   */
  function luSolve(A, piv, b, n) {
    for (let k = 0; k < n; k++) {
      const p = piv[k];
      if (p !== k) { const t = b[p]; b[p] = b[k]; b[k] = t; }
    }
    for (let i = 1; i < n; i++) {
      const r = A[i];
      let s = b[i];
      for (let k = 0; k < i; k++) s -= r[k] * b[k];
      b[i] = s;
    }
    for (let k = n - 1; k >= 0; k--) {
      let s = b[k];
      for (let j = k + 1; j < n; j++) s -= A[k][j] * b[j];
      b[k] = s / A[k][k];
    }
    return b;
  }

  /** solveDense on A and rhs themselves, both spoilt; the solution is rhs. */
  function solveInPlace(M, x, n) {
    for (let col = 0; col < n; col++) {
      let best = col;
      for (let r = col + 1; r < n; r++) if (Math.abs(M[r][col]) > Math.abs(M[best][col])) best = r;
      if (Math.abs(M[best][col]) < 1e-300) return null;
      if (best !== col) {
        const t = M[col]; M[col] = M[best]; M[best] = t;
        const tv = x[col]; x[col] = x[best]; x[best] = tv;
      }
      const pr = M[col];
      const p = pr[col];
      for (let r = col + 1; r < n; r++) {
        const mr = M[r];
        const f = mr[col] / p;
        if (!f) continue;
        for (let c = col; c < n; c++) mr[c] -= f * pr[c];
        x[r] -= f * x[col];
      }
    }
    for (let r = n - 1; r >= 0; r--) {
      let sum = x[r];
      const mr = M[r];
      for (let c = r + 1; c < n; c++) sum -= mr[c] * x[c];
      x[r] = sum / mr[r];
    }
    return x;
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
        throw new RtmError(`"[${inner}]" is not a species name. ${NAME_RULE}`, line);
      }
      const id = `S_${names.size}__`;
      names.set(id, name);
      return id;
    });
    return { masked, names };
  }

  /**
   * A rate law's text with everything that is not plain arithmetic masked:
   * SI(name) and SR(name), a phase's saturation index and ratio (the name may
   * hold brackets of its own, CO2(g)); {name}, a species' activity; and
   * [name], its concentration (maskSpecies). Each becomes an identifier the
   * expression parser takes as a variable.
   */
  function maskRate(src, line) {
    const text = String(src);
    const sats = new Map();
    const acts = new Map();
    let out = '';
    for (let i = 0; i < text.length;) {
      const m = /^(SI|SR)\s*\(/.exec(text.slice(i));
      if (m && (i === 0 || !/[A-Za-z0-9_]/.test(text[i - 1]))) {
        let depth = 0;
        let j = i + m[0].length - 1;
        for (; j < text.length; j++) {
          if (text[j] === '(') depth++;
          else if (text[j] === ')' && --depth === 0) break;
        }
        if (depth !== 0) throw new RtmError(`"${text.slice(i)}": ${m[1]}( is never closed.`, line);
        const name = text.slice(i + m[0].length, j).trim();
        if (!name) throw new RtmError(`${m[1]}() needs the name of a phase, as ${m[1]}(Calcite).`, line);
        const id = `${m[1]}_${sats.size}__`;
        sats.set(id, { kind: m[1], name });
        out += id;
        i = j + 1;
        continue;
      }
      out += text[i];
      i++;
    }
    out = out.replace(/\{([^}]*)\}/g, (_, inner) => {
      const name = inner.trim();
      if (!SPECIES_NAME.test(name)) throw new RtmError(`"{${inner}}" is not a species name. ${NAME_RULE}`, line);
      const id = `A_${acts.size}__`;
      acts.set(id, name);
      return id;
    });
    const { masked, names } = maskSpecies(out, line);
    return { masked, names, acts, sats };
  }

  /**
   * <PHASES>: phases a rate law can ask the saturation of, held by nothing --
   * PHREEQC's PHASES. Each line is its dissolution, the phase first on the
   * left: "Calcite <=> Ca+2 + CO3-2, logK = -8.48". The phase need not be a
   * species; the rest must be, or H2O for the water.
   */
  function readPhases(lines, index) {
    const out = new Map();
    for (const { text, line } of lines) {
      const parts = splitTop(text).map((x) => x.trim()).filter(Boolean);
      const equation = parts.shift() || '';
      const arrow = equation.includes('<=>') ? '<=>' : (equation.includes('=') ? '=' : null);
      if (!arrow) throw new RtmError(`"${text}" needs a dissolution, the phase first: Calcite <=> Ca+2 + CO3-2.`, line);
      const [lhs, rhs] = equation.split(arrow).map((x) => x.trim());
      const left = parseSide(lhs, line);
      const right = parseSide(rhs, line);
      if (!left.length) throw new RtmError(`"${text}": the phase comes first on the left.`, line);
      const [c0, name] = left[0];
      let lnK = null;
      for (const part of parts) {
        const m = /^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$/.exec(part);
        if (!m) throw new RtmError(`"${part}" is not NAME = value.`, line);
        const v = constValue(m[2], line, m[1]);
        if (m[1] === 'logK') lnK = v * Math.LN10;
        else if (m[1] === 'K') {
          if (!(v > 0)) throw new RtmError('K must be greater than zero; use logK for a small one.', line);
          lnK = Math.log(v);
        } else throw new RtmError(`"${m[1]}" is not K or logK: a phase is held by nothing, so it has no kf.`, line);
      }
      if (lnK === null) throw new RtmError('A phase needs K = ... or logK = ... .', line);
      if (out.has(name)) throw new RtmError(`The phase ${name} is given twice.`, line);
      const net = new Map();
      let water = 0;
      const solvent = !index.has('H2O');
      const bump = (n, c) => {
        if (solvent && n === 'H2O') { water += c; return; }
        if (!index.has(n)) throw new RtmError(`"${n}" is in the phase ${name} but is not in <SPECIES>.`, line);
        net.set(index.get(n), (net.get(index.get(n)) || 0) + c);
      };
      for (const [c, n] of left.slice(1)) bump(n, -c);
      for (const [c, n] of right) bump(n, c);
      out.set(name, { name, c0, net: [...net].filter(([, c]) => c !== 0), water, lnK, sign: 1, line, text });
    }
    return out;
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
   * The constant pieces of a tree, worked out once: (2/3) becomes a number,
   * 10**-3 becomes 0.001, and a constant of the reaction's own line becomes
   * its value. The operations are the ones the generated code would have done,
   * in the same order, so nothing changes but where they happen -- and an
   * exponent written as arithmetic is then one the derivative can read.
   */
  function fold(node, consts) {
    switch (node.type) {
      case 'num': return node;
      case 'id': return consts && consts.has(node.name) ? NUM(consts.get(node.name)) : node;
      case 'neg': {
        const a = fold(node.a, consts);
        return a.type === 'num' ? NUM(-a.v) : { type: 'neg', a };
      }
      case 'bin': {
        const l = fold(node.l, consts);
        const r = fold(node.r, consts);
        if (l.type === 'num' && r.type === 'num') {
          let v;
          switch (node.op) {
            case '+': v = l.v + r.v; break;
            case '-': v = l.v - r.v; break;
            case '*': v = l.v * r.v; break;
            case '/': v = l.v / r.v; break;
            case '**': v = Math.pow(l.v, r.v); break;
            default: v = undefined;
          }
          if (Number.isFinite(v)) return NUM(v);
        }
        return { type: 'bin', op: node.op, l, r };
      }
      case 'call': return { ...node, args: node.args.map((a) => fold(a, consts)) };
      default: return node;
    }
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
          // The exponent may be anything that does not depend on a
          // concentration -- a number, arithmetic on numbers, a constant of
          // the line, a parameter. One that does would need log(base) in the
          // derivative, undefined at a zero concentration, which is exactly
          // where these are evaluated.
          if (!isNum(dr, 0)) {
            throw new RtmError('The exponent of a power in a rate law may not depend on a '
              + 'concentration: write [A]^2, [A]^(2/3) or [A]^n with n a constant or a parameter.', line);
          }
          if (isNum(dl, 0)) return NUM(0);
          return mul(mul(r, pow(l, r.type === 'num' ? NUM(r.v - 1) : sub(r, NUM(1)))), dl);
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
    const transport = settings.MODE === 'transport';
    if (!transport) {
      const L = settings.LENGTH;
      return { n: 1, centres: Float64Array.of(0), width: Float64Array.of(L || 1),
        faces: Float64Array.of(0, L || 1), L, surface: 0 };
    }
    if (settings.GRID === 'faces') {
      if (settings.SURFACE_LAYER > 0) {
        throw new RtmError('SURFACE_LAYER cannot be combined with FACES: the faces already say how '
          + 'thick the first cell is.');
      }
      return facesGrid(settings);
    }
    const n = settings.CELLS;
    const L = settings.LENGTH;
    if (!(settings.GRID_RATIO > 0)) throw new RtmError(`GRID_RATIO = ${settings.GRID_RATIO} must be above zero.`);
    if (!(settings.GRID_POWER > 0)) throw new RtmError(`GRID_POWER = ${settings.GRID_POWER} must be above zero.`);
    /*
      A SURFACE LAYER of fixed thickness. A surface -- sites, a coating, a
      reacting film -- lives in the first cell, and when that cell's
      thickness comes from the grid, refining the grid thins the surface and
      moves the answer: in skbrtm's fuel-dissolution example the dissolved
      uranium per m2 halves every time the cells are halved. Pinning the
      first cell makes its thickness a property of the model; the other
      CELLS - 1 cells are laid out over what is left, by the same GRID.
    */
    const s = settings.SURFACE_LAYER;
    if (s > 0) {
      if (!(s < L)) throw new RtmError(`SURFACE_LAYER = ${s} m must be less than LENGTH = ${L} m.`);
      const rest = widthsFor(settings.GRID, n - 1, L - s, settings);
      return fromWidths([s, ...rest], L, s);
    }
    if (settings.GRID === 'powerlaw') return fromFaces(powerFaces(n, L, settings.GRID_POWER), s);
    const centres = new Float64Array(n);
    if (settings.GRID === 'log') {
      // Geometric widths, normalised to the length. The first face is at zero.
      const ratio = Math.pow(settings.GRID_RATIO, 1 / (n - 1));
      const w = new Float64Array(n);
      let total = 0;
      for (let i = 0; i < n; i++) { w[i] = Math.pow(ratio, i); total += w[i]; }
      let x = 0;
      const faces = new Float64Array(n + 1);
      for (let i = 0; i < n; i++) {
        w[i] *= L / total;
        centres[i] = x + w[i] / 2;
        x += w[i];
        faces[i + 1] = x;
      }
      faces[n] = L;
      return { n, centres, width: w, faces, L, surface: 0 };
    }
    const dx = L / n;
    const w = new Float64Array(n).fill(dx);
    const faces = new Float64Array(n + 1);
    for (let i = 0; i < n; i++) { centres[i] = (i + 0.5) * dx; faces[i] = i * dx; }
    faces[n] = L;
    return { n, centres, width: w, faces, L, surface: 0 };
  }

  /** Faces at L*(i/n)^p: fine at the left for p above 1, as skbrtm's powerlaw is. */
  function powerFaces(n, L, p) {
    const f = new Float64Array(n + 1);
    for (let i = 0; i <= n; i++) f[i] = L * Math.pow(i / n, p);
    f[n] = L;
    return f;
  }

  /** The widths of m cells over a span, by one of the GRID kinds. */
  function widthsFor(kind, m, span, settings) {
    if (m < 1) return [];
    if (kind === 'powerlaw') {
      const f = powerFaces(m, span, settings.GRID_POWER);
      return Array.from({ length: m }, (_, i) => f[i + 1] - f[i]);
    }
    if (kind === 'log' && m > 1) {
      const ratio = Math.pow(settings.GRID_RATIO, 1 / (m - 1));
      const w = Array.from({ length: m }, (_, i) => Math.pow(ratio, i));
      const total = w.reduce((a, b) => a + b, 0);
      return w.map((v) => (v * span) / total);
    }
    return new Array(m).fill(span / m);
  }

  function fromWidths(widths, L, surface) {
    const n = widths.length;
    const faces = new Float64Array(n + 1);
    for (let i = 0; i < n; i++) faces[i + 1] = faces[i] + widths[i];
    faces[n] = L;
    return fromFaces(faces, surface);
  }

  function fromFaces(faces, surface) {
    const n = faces.length - 1;
    const centres = new Float64Array(n);
    const width = new Float64Array(n);
    for (let i = 0; i < n; i++) {
      centres[i] = (faces[i] + faces[i + 1]) / 2;
      width[i] = faces[i + 1] - faces[i];
    }
    return { n, centres, width, faces: Float64Array.from(faces), L: faces[n], surface };
  }

  /**
   * FACES = the face positions outright, in metres from the left end: a list
   * -- 0, 1e-7, 8e-7, ... -- or an expression in i, worked out for i = 0 to
   * CELLS -- 1e-4*(i/10)^3. The list decides CELLS and LENGTH; a CELLS or a
   * LENGTH the text also gives has to agree with it.
   */
  function facesGrid(settings) {
    const raw = settings.FACES;
    const line = settings.FACES_line;
    const parts = splitTop(raw).map((p) => p.trim()).filter(Boolean);
    const words = raw.trim().split(/\s+/);
    let faces;
    if (parts.length > 1 || (words.length > 1 && words.every((w) => Number.isFinite(Number(w))))) {
      const items = parts.length > 1 ? parts : words;
      faces = items.map((p, i) => constValue(p, line, `face ${i}`));
    } else {
      let ast;
      try {
        ast = FacsimileModel.parseExpression(raw, line);
      } catch (e) {
        throw new RtmError(`FACES = "${raw}" is neither a list of positions nor an expression in i `
          + `(${e.message.replace(/^Line \d+: /, '')}).`, line);
      }
      const n = settings.CELLS;
      faces = [];
      for (let i = 0; i <= n; i++) {
        let v;
        try {
          v = FacsimileModel.evalAst(ast, (id) => (id === 'i' ? i : (id === 'n' ? n : undefined)), {}, line);
        } catch (e) {
          throw new RtmError(`FACES = "${raw}": ${e.message.replace(/^Line \d+: /, '')}. An expression `
            + 'for the faces may use i, the face number from 0 to CELLS, and n, which is CELLS.', line);
        }
        faces.push(v);
      }
    }
    if (faces.length < 3) throw new RtmError('FACES needs three positions at least: two cells.', line);
    if (faces[0] !== 0) {
      throw new RtmError(`The first of the FACES is the left end of the column and must be 0, not ${faces[0]}.`, line);
    }
    for (let i = 1; i < faces.length; i++) {
      if (!(Number.isFinite(faces[i]) && faces[i] > faces[i - 1])) {
        throw new RtmError(`FACES must increase from one to the next; face ${i} (${faces[i]}) does not.`, line);
      }
    }
    const given = settings.given || new Set();
    const n = faces.length - 1;
    if (given.has('CELLS') && settings.CELLS !== n) {
      throw new RtmError(`CELLS = ${settings.CELLS}, but FACES describes ${n} cells.`, line);
    }
    const L = faces[n];
    if (given.has('LENGTH') && Math.abs(settings.LENGTH - L) > 1e-12 * L) {
      throw new RtmError(`LENGTH = ${settings.LENGTH} m, but the last of the FACES is at ${L} m.`, line);
    }
    return fromFaces(faces, 0);
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
    const warnings = [];
    // Null unless ACTIVITY asks for one (activityModel), or there is an
    // exchanger (exchangeSetup, once the relations are read).
    let act = activityModel(settings, species, warnings);
    const transport = settings.MODE === 'transport';
    flowFromTravelTime(settings, grid);
    const surface = wettedSurface(settings, grid);
    const matrix = makeMatrix(settings, surface.aw, warnings);
    sorptionCapacities(species, settings, matrix, surface.aw, warnings);

    /* ---- what moves ---------------------------------------------------- */
    const peclet = transport && settings.ADVECTION && settings.PECLET > 0 ? settings.PECLET : 0;
    const mobile = species.map((s) => (transport && !s.fixed && !s.immobile
      && ((settings.DIFFUSION && (s.D > 0 || peclet > 0))
        || (settings.ADVECTION && settings.VELOCITY !== 0))));
    // Which species cross into the rock: those with a matrix diffusivity.
    const enters = species.map((s) => !!matrix && !s.fixed && !s.immobile && s.Dm > 0);
    // The ions Nernst-Planck couples: mobile, charged, and diffusing.
    const npIons = transport && settings.DIFFUSION === 2
      ? species.map((sp, k) => ({ s: k, z: sp.z !== null ? sp.z : chargeOf(sp.name), D: sp.D }))
        .filter((x) => mobile[x.s] && x.z !== 0 && x.D > 0)
      : [];

    /*
      THE OUTLET. A semi-infinite right-hand end is the column going on past
      LENGTH, as the analytical far-field models have it: what leaves is the
      whole flux, advection and dispersion, across the plane at LENGTH, and
      the concentration falls to zero only infinitely far downstream. A grid
      cannot hold that, so it holds EXTRA_CELLS of it past the end and closes
      the last by linear extrapolation -- Kompartment's outlet for a far-field
      path, the one it gives a new path. It is where the water leaves, so the
      flow must run to the right.
    */
    const nf = grid.n;
    if (transport && settings.LEFT === 'semi-infinite') {
      throw new RtmError('LEFT = semi-infinite: a semi-infinite end is an outlet, the column going on '
        + 'past the point the water leaves, and is for the right-hand face. Use robin for water '
        + 'arriving at the left.');
    }
    const semi = transport && settings.RIGHT === 'semi-infinite';
    if (semi && !(settings.ADVECTION && settings.VELOCITY > 0)) {
      throw new RtmError('RIGHT = semi-infinite is the column going on past the point the water '
        + 'leaves: it needs ADVECTION and a VELOCITY to the right, above zero.');
    }
    if (!semi && (settings.given || new Set()).has('EXTRA_CELLS')) {
      throw new RtmError('EXTRA_CELLS is how many cells stand for the column past a semi-infinite '
        + 'right-hand end, and needs RIGHT = semi-infinite.');
    }
    const nb = semi ? extraCellCount(settings, grid, species, mobile, peclet) : 0;
    if (semi) settings.EXTRA_CELLS = nb;
    const ncol = nf + nb;
    const last = ncol - 1;          // the column's last cell, past the end or not
    const col = withExtraCells(grid, nb);
    /*
      THE CELLS. A plain column has grid.n of them, and a semi-infinite one
      its extra cells after those. With a rock matrix each of them -- a
      fracture cell, the flowing water -- is followed in the state by the nm
      stagnant layers behind it, so cell (i, j) sits at i*(1+nm) + j, j = 0
      being the fracture. That keeps a fracture cell and its own matrix chain
      contiguous, which is where nearly all the coupling is, and it is the
      numbering SKB's FARFCOMP uses, so an inventory can be compared position
      by position.

      The matched layers are sized by what diffuses into them, which the
      parameters can say -- a capacity Rm that names one -- so the layers are
      laid out once the species are read, and until then every layer is put
      at the wall: what is read at that stage is read where the rock begins.
    */
    const nm = matrix ? matrix.n : 0;
    const stride = 1 + nm;
    const cellOf = (i, j) => i * stride + j;
    const placeCells = (centre) => {
      const out = [];
      for (let i = 0; i < ncol; i++) {
        out.push({ i, j: 0, x: col.centres[i], xm: 0 });
        for (let j = 1; j <= nm; j++) out.push({ i, j, x: col.centres[i], xm: centre ? centre[j - 1] : 0 });
      }
      return out;
    };
    let geom = placeCells(null);
    const tables = readTables(sections.TABLES);
    let params = readParameters(sections.PARAMETERS, col, geom, tables);
    const ns = species.length;
    const index = new Map(species.map((s, i) => [s.name, i]));
    const nameOf = species.map((s) => s.name);
    // Read now, applied at the end: a line may hold a species in some cells,
    // and the transport and the pattern below have to know which.
    const patches = readInitial(sections.INITIAL, index, nf);

    const needSpecies = (name, line) => {
      if (!index.has(name)) {
        throw new RtmError(`"${name}" is used by a reaction but is not in <SPECIES>.`, line);
      }
      return index.get(name);
    };

    // The tables the rate laws read at the clock, one slot per distinct read
    // (table, column, argument): see readAtTheClock below.
    const clockReads = new Map();

    /* ---- the rate laws, as trees ------------------------------------- */
    // Each reaction becomes one or two "channels": a forward one, and a
    // backward one when it is reversible. A channel has a rate and the net
    // change it makes to each species.
    const channels = [];
    /*
      WHAT A RATE LAW READS BESIDES CONCENTRATIONS, each worked out once a cell
      before the rates are: an activity {X}, the water's {H2O}, the ionic
      strength I, a phase's saturation index SI(name) or ratio SR(name). The
      generated code reads them from AQ and is differentiated in them; the
      Jacobian then follows each through the species it is made of (aqAt).
    */
    const aqList = [];
    const aqKeys = new Map();
    const registerAQ = (desc, line) => {
      const key = `${desc.kind}:${desc.s !== undefined ? desc.s : (desc.name || '')}`;
      if (!aqKeys.has(key)) { aqKeys.set(key, aqList.length); aqList.push({ ...desc, line }); }
      return aqKeys.get(key);
    };
    for (const rx of reactions) {
      const stoich = new Map();
      const bump = (i, c) => stoich.set(i, (stoich.get(i) || 0) + c);
      for (const [c, name] of rx.reactants) bump(needSpecies(name, rx.line), -c);
      for (const [c, name] of rx.products) bump(needSpecies(name, rx.line), +c);
      const net = [...stoich.entries()].filter(([, c]) => c !== 0);
      if (!net.length) warnings.push(`Line ${rx.line}: the reaction changes nothing.`);
      // What is no amount cannot be made or used up at a rate.
      const none = net.find(([i]) => species[i].electron || species[i].exchanger);
      if (none) {
        const sp = species[none[0]];
        throw new RtmError(sp.electron
          ? `${sp.name} is the electron, which is no amount and cannot react at a rate: a redox reaction in `
            + '<REACTIONS> is written between species, Fe+2 + 0.25 O2 + H+ => Fe+3 + 0.5 H2O, and the couples '
            + 'tied to the electron in <EQUILIBRIUM> share out what it moves. A rate law may read it, as [e-].'
          : `${sp.name} is an exchanger, which is no amount and cannot react at a rate: exchange at a rate is a `
            + 'relation between species on it with a kf, Ca+2 + 2 NaX <=> CaX2 + 2 Na+.', rx.line);
      }

      const build = (spec, side, sign) => {
        // Mass action: the rate is k times each reactant to its coefficient.
        let src;
        if (spec.kind === 'k') {
          const terms = side.map(([c, name]) => (c === 1 ? `[${name}]` : `[${name}]**${c}`));
          src = terms.length ? `(${spec.src}) * ${terms.join(' * ')}` : `(${spec.src})`;
        } else {
          src = spec.src;
        }
        const { masked, names, acts, sats } = maskRate(src, rx.line);
        let ast;
        try {
          ast = FacsimileModel.parseExpression(masked, rx.line);
        } catch (e) {
          throw new RtmError(`In the rate "${src}": ${e.message.replace(/^Line \d+: /, '')}`, rx.line);
        }
        // An alias on the line -- c = [Fe+2] -- is that species wherever the
        // law names it, exactly as if [Fe+2] had been written there.
        if (rx.aliases && rx.aliases.size) {
          const aliasId = new Map();
          for (const [key, sp] of rx.aliases) {
            const id = `S_${names.size}__`;
            names.set(id, sp);
            aliasId.set(key, id);
          }
          const swap = (node) => {
            if (!node || typeof node !== 'object') return node;
            if (node.type === 'id' && aliasId.has(node.name)) return { type: 'id', name: aliasId.get(node.name) };
            if (node.type === 'bin') return { ...node, l: swap(node.l), r: swap(node.r) };
            if (node.type === 'neg') return { ...node, a: swap(node.a) };
            if (node.type === 'call') return { ...node, args: node.args.map(swap) };
            return node;
          };
          ast = swap(ast);
        }
        /*
          A TABLE IN A RATE LAW is read at the clock: name(t), name(t - 1000),
          name(t, U238) of a table of several columns -- a release history, a
          dose rate that falls with time. Its argument may use t and the
          line's constants and nothing else: a concentration would make the
          table's slope part of the Jacobian, and a parameter would make it a
          table of place, which <PARAMETERS> is for. Each such read is a slot
          of TV, worked out once per evaluation at the time it is made for,
          and differentiates to nothing.
        */
        ast = (function readAtTheClock(node) {
          if (!node || typeof node !== 'object') return node;
          const call = node.type === 'call' ? tableCall(node, tables, rx.line) : null;
          if (call) {
            const arg = fold(call.arg, rx.params);
            for (const id of mentioned(arg)) {
              if (id === 't') continue;
              throw new RtmError(`"${node.name}(...)" in a rate law is read at a time: its argument may `
                + `use t and the constants of the line, and ${names.has(id) ? `[${names.get(id)}] is a concentration`
                  : `"${id}" is not one of them`}. A table of place is read in <PARAMETERS> -- NAME all `
                + `${call.tab.name}(x) -- and NAME used here.`, rx.line);
            }
            const key = `${call.tab.name}#${call.col}#${JSON.stringify(arg)}`;
            if (!clockReads.has(key)) clockReads.set(key, { k: clockReads.size, tab: call.tab, col: call.col, arg });
            return { type: 'id', name: `__tv${clockReads.get(key).k}__` };
          }
          if (node.type === 'call') return { ...node, args: node.args.map(readAtTheClock) };
          if (node.type === 'bin') return { ...node, l: readAtTheClock(node.l), r: readAtTheClock(node.r) };
          if (node.type === 'neg') return { ...node, a: readAtTheClock(node.a) };
          return node;
        }(ast));
        // The constant parts worked out once, the line's own constants among them.
        ast = fold(ast, rx.params);
        // Every identifier is a masked species, a constant of this line, a
        // parameter, the clock t, or a table read at it.
        const deps = [];
        const aq = [];
        const seen = new Set();
        for (const id of mentioned(ast)) {
          if (names.has(id)) {
            const si = needSpecies(names.get(id), rx.line);
            if (!seen.has(id)) { seen.add(id); deps.push({ id, si }); }
          } else if (acts.has(id)) {
            // {H2O}, H2O being no species, is the water's activity.
            const nm = acts.get(id);
            aq.push({ id, q: nm === 'H2O' && !index.has('H2O') ? registerAQ({ kind: 'aw' }, rx.line)
              : registerAQ({ kind: 'a', s: needSpecies(nm, rx.line) }, rx.line) });
          } else if (sats.has(id)) {
            aq.push({ id, q: registerAQ({ kind: sats.get(id).kind, name: sats.get(id).name }, rx.line) });
          } else if (id === 'I' && !params.index.has('I')) {
            // The ionic strength, unless the text has a parameter of that name.
            aq.push({ id, q: registerAQ({ kind: 'I' }, rx.line) });
          } else if (!rx.params.has(id) && !params.index.has(id) && id !== 't' && !/^__tv\d+__$/.test(id)) {
            throw new RtmError(`"${id}" in a rate law is not a parameter of this reaction, a `
              + 'parameter in <PARAMETERS>, the time t, a species in brackets, an activity in braces, '
              + 'I, or SI(phase) or SR(phase). Write a concentration as [name].', rx.line);
          }
        }
        deps.sort((a, b) => a.si - b.si);
        /*
          ON = INVENTORY: a share of the whole of what the cell holds of the
          species on the left -- decay -- so the reaction goes at the rate law
          times that species' capacity, R or Rm, and every species it changes
          changes by that much of its own inventory. A daughter born of a
          parent that sorbs hard is born as many atoms as the parent lost, and
          then takes up its own share between water and rock, as Kompartment
          and FARF31 have it. One species on the left, or none: a source on
          the inventory makes its rate of change of each concentration.
        */
        let capOf = -1;
        if (rx.whole) {
          const left = [...new Set(side.map(([, name]) => needSpecies(name, rx.line)))];
          if (left.length > 1) {
            throw new RtmError('on = inventory is a share of what a cell holds of one species -- '
              + 'radioactive decay -- and this side of the reaction has more than one. Write it '
              + 'on = water, the default.', rx.line);
          }
          if (left.length) [capOf] = left;
        }
        return {
          ast,
          deps,
          aq,
          params: rx.params,
          line: rx.line,
          whole: !!rx.whole, capOf, net: net.map(([i, c]) => [i, c * sign]),
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
    /*
      Under ACTIVITY a pair relaxes to its K in activities, so its backward
      constant follows the ionic strength: kb = kf*Gamma/K, Gamma the product
      of the activity coefficients (and the water's activity) to their
      coefficients in the relation, products positive. No rate law here can
      say that, so those pairs are worked out beside the generated code: see
      pairInfo below.
    */
    /*
      A MINERAL in a relation is its pure phase: activity 1, so it adds
      nothing to the relation, which is its saturation; it counts in the
      totals as everything else does. One mineral to a relation and one
      relation to a mineral, and none of them a fast pair: what holds a
      mineral is EQUILIBRATE, and while there is none of it, nothing does.
    */
    const inRelation = new Map();
    for (const eq of equilibria) {
      const mins = eq.net.filter(([si]) => species[si].mineral);
      if (mins.length > 1) {
        throw new RtmError(`"${eq.text}" has ${mins.map(([si]) => species[si].name).join(' and ')} in it, `
          + 'two minerals: a relation is the saturation of one mineral.', eq.line);
      }
      eq.mineral = mins.length ? mins[0][0] : -1;
      eq.mineralNu = mins.length ? mins[0][1] : 0;
      if (!mins.length) continue;
      const name = species[eq.mineral].name;
      if (eq.kf !== null) {
        throw new RtmError(`"${eq.text}" is the saturation of ${name}, a mineral, and a mineral is not a fast `
          + 'pair: it is held at equilibrium (EQUILIBRATE), or it dissolves by a rate law of your own in '
          + '<REACTIONS>.', eq.line);
      }
      if (inRelation.has(eq.mineral)) {
        throw new RtmError(`${name} is in two relations, lines ${inRelation.get(eq.mineral)} and ${eq.line}: a `
          + 'mineral has one saturation.', eq.line);
      }
      inRelation.set(eq.mineral, eq.line);
    }
    act = exchangeSetup(species, equilibria, act, settings, warnings);
    const ex = act ? act.ex : null;
    const electron = electronSetup(species, equilibria);
    // The order the conserved totals are made in (conservationBasis): species
    // on an exchanger first, and last what is no amount, an exchanger or the
    // electron, which counts in no total.
    const rank = ex || electron >= 0
      ? Int8Array.from(species, (sp) => (sp.exchange ? 1 : sp.exchanger || sp.electron ? 2 : 0)) : null;
    const apairs = [];
    for (const eq of equilibria) {
      if (eq.kf === null) continue;
      if (act) { apairs.push(eq); continue; }
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

    /* ---- what the rate laws read besides concentrations ---------------- */
    const phases = readPhases(sections.PHASES, index);
    // Where the activities come from: ACTIVITY's model, or without it
    // activity coefficients of 1 and the charges the names give, for I.
    const aqAct = act || (aqList.length ? noActivity(species) : null);
    const aqIons = [];
    const aqSolutes = [];
    if (aqAct) for (let k = 0; k < ns; k++) { if (aqAct.z[k]) aqIons.push(k); if (aqAct.solute[k]) aqSolutes.push(k); }
    for (const e of aqList) {
      if (e.kind !== 'SI' && e.kind !== 'SR') continue;
      // A phase of <PHASES>, or a mineral's relation in <EQUILIBRIUM>.
      let ph = phases.get(e.name) || null;
      if (!ph) {
        const eq = equilibria.find((x) => x.mineral >= 0 && species[x.mineral].name === e.name);
        if (eq) {
          ph = { name: e.name, net: eq.net.filter(([k]) => k !== eq.mineral), water: eq.water || 0, lnK: eq.lnK,
            sign: eq.mineralNu < 0 ? 1 : -1 };
        }
      }
      if (!ph) {
        throw new RtmError(`${e.kind}(${e.name}): "${e.name}" is no phase. Give its dissolution in <PHASES> -- `
          + 'Calcite <=> Ca+2 + CO3-2, logK = -8.48 -- or make it a mineral with its relation in <EQUILIBRIUM>.',
        e.line);
      }
      e.phase = ph;
    }
    // The species each is made of, which its derivatives run over: with
    // ACTIVITY every ion, through the ionic strength, and every solute where
    // the water's activity comes in.
    for (const e of aqList) {
      const set = new Set();
      if (e.kind === 'a') { set.add(e.s); if (act) aqIons.forEach((k) => set.add(k)); }
      else if (e.kind === 'aw') { if (act) aqSolutes.forEach((k) => set.add(k)); }
      else if (e.kind === 'I') aqIons.forEach((k) => set.add(k));
      else {
        e.phase.net.forEach(([k]) => set.add(k));
        if (act) aqIons.forEach((k) => set.add(k));
        if (act && e.phase.water) aqSolutes.forEach((k) => set.add(k));
      }
      e.cols = [...set].sort((x, y) => x - y);
    }
    for (const ch of channels) {
      if (!ch.aq || !ch.aq.length) continue;
      const set = new Set();
      for (const d of ch.aq) for (const k of aqList[d.q].cols) set.add(k);
      ch.aqCols = [...set].sort((x, y) => x - y);
    }
    const nq = aqList.length;
    const AQ = new Float64Array(Math.max(nq, 1));
    const dAQ = Array.from({ length: nq }, () => new Float64Array(ns));
    const lnGq = aqAct ? new Float64Array(ns) : null;
    const dGq = aqAct ? new Float64Array(ns) : null;
    /** The cell at b's activities, I and saturations into AQ; with derivs, their derivatives into dAQ. */
    const aqAt = (y, b, derivs) => {
      const w = activityAt(aqAct, y, b, lnGq, dGq);
      const z = aqAct.z;
      for (let q = 0; q < nq; q++) {
        const e = aqList[q];
        const d = derivs ? dAQ[q] : null;
        if (d) d.fill(0);
        if (e.kind === 'a') {
          const g = Math.exp(lnGq[e.s]);
          const a = y[b + e.s] * g;
          AQ[q] = a;
          if (d) {
            d[e.s] += g;
            if (dGq[e.s]) for (const k of aqIons) d[k] += a * dGq[e.s] * 0.5 * z[k] * z[k];
          }
        } else if (e.kind === 'aw') {
          const aw = Math.exp(w.lnAw);
          AQ[q] = aw;
          if (d && w.dAw) for (const k of aqSolutes) d[k] += aw * w.dAw;
        } else if (e.kind === 'I') {
          AQ[q] = w.I;
          if (d && w.I > 1e-10) for (const k of aqIons) d[k] += 0.5 * z[k] * z[k];
        } else {
          const ph = e.phase;
          let lnIAP = ph.water ? ph.water * w.lnAw : 0;
          let G = 0;
          for (const [k, nu] of ph.net) {
            lnIAP += nu * (Math.log(Math.max(y[b + k], 1e-300)) + lnGq[k]);
            G += nu * dGq[k];
          }
          const x = ph.sign * (lnIAP - ph.lnK);
          const val = e.kind === 'SI' ? x / Math.LN10 : Math.exp(x);
          AQ[q] = val;
          if (d) {
            const f = ph.sign * (e.kind === 'SI' ? 1 / Math.LN10 : val);
            for (const [k, nu] of ph.net) if (y[b + k] > 0) d[k] += (f * nu) / y[b + k];
            if (G) for (const k of aqIons) d[k] += f * G * 0.5 * z[k] * z[k];
            if (ph.water && w.dAw) for (const k of aqSolutes) d[k] += f * ph.water * w.dAw;
          }
        }
      }
    };

    /* ---- generated code: the rates and their derivatives -------------- */
    // Two functions, compiled once, run per cell: the rates, which the
    // derivative reads, and their derivatives, which only the Jacobian does.
    // They were one, and every evaluation of the derivative -- several a step
    // -- worked out the whole gradient of every rate law in every cell to
    // throw it away; Kompartment's derivative stopped working out what only
    // the Jacobian or the results read for the same reason. `y` is the whole
    // state and `b` the first index of this cell, so no slicing or copying
    // happens.
    const rateBody = [];
    const derivBody = [];
    // Whether the Jacobian can change during a run. Transport is linear, the
    // parameters and capacities are fixed when the model compiles, and nothing
    // here reads the clock: so it can only move through a rate law whose
    // derivative reads a concentration. A model with none -- decay chains,
    // first-order sorption, a tracer -- has one matrix for the whole run.
    let jacobianMoves = false;
    const derivIndex = [];      // where each channel's derivatives start in D
    let nd = 0;
    channels.forEach((ch, j) => {
      const resolve = (id, line) => {
        const dep = ch.deps.find((d) => d.id === id);
        if (dep) return `y[b + ${dep.si}]`;
        const aqd = ch.aq ? ch.aq.find((d) => d.id === id) : null;
        if (aqd) return `AQ[${aqd.q}]`;
        // A constant of this line beats a global of the same name: it is the
        // more local thing to have written, and the one being looked at.
        if (ch.params.has(id)) return numberLiteral(ch.params.get(id));
        if (params.index.has(id)) return `P[pb + ${params.index.get(id)}]`;
        if (id === 't') return 't';
        const tv = /^__tv(\d+)__$/.exec(id);
        if (tv) return `TV[${tv[1]}]`;
        throw new RtmError(`"${id}" is not known here.`, line);
      };
      rateBody.push(`  R[${j}] = ${emit(ch.ast, resolve, ch.line)};`);
      derivIndex.push(nd);
      ch.derivCode = [];
      for (const dep of ch.deps) {
        const d = derivative(ch.ast, dep.id, ch.line);
        const code = emit(d, resolve, ch.line);
        // A derivative that reads no concentration, and not the clock either,
        // is a number for the run.
        if (/\by\[|\bTV\[|\bt\b/.test(code)) jacobianMoves = true;
        derivBody.push(`  D[${nd}] = ${code};`);
        ch.derivCode.push(code);
        nd++;
      }
      // ...and in what it reads besides concentrations, carried to the
      // species through aqAt's derivatives.
      ch.aqD = [];
      for (const aqd of ch.aq || []) {
        derivBody.push(`  D[${nd}] = ${emit(derivative(ch.ast, aqd.id, ch.line), resolve, ch.line)};`);
        ch.aqD.push(nd);
        jacobianMoves = true;
        nd++;
      }
    });
    /*
      Cut into parts when it is long, for the reason facsimile-model.js gives
      at layOut: V8 will not optimise a function of more than 60 KB of
      bytecode, and this one grows with the chemistry. Whole, a synthetic
      network of 600 reactions (76,000 characters) ran 95 times slower per
      call than in parts. The largest network shipped or imported so far is
      a fifth of that size, and stays in one piece. The lines are independent
      assignments, so a part needs nothing from another. The parts are called
      in the order of the lines.
    */
    const compileRates = (body) => {
      const chunks = [[]];
      let size = 0;
      for (const line of body) {
        if (size > RATE_PART_CHARS) { chunks.push([]); size = 0; }
        chunks[chunks.length - 1].push(line);
        size += line.length + 1;
      }
      // eslint-disable-next-line no-new-func
      const parts = chunks.map((c) => new Function('y', 'b', 'P', 'pb', 'R', 'D', 't', 'TV', 'AQ', c.join('\n')));
      return parts.length === 1 ? parts[0]
        // eslint-disable-next-line no-new-func
        : new Function('parts', `"use strict";\nreturn function (y, b, P, pb, R, D, t, TV, AQ) {\n${
          parts.map((_, k) => `  parts[${k}](y, b, P, pb, R, D, t, TV, AQ);`).join('\n')}\n};`)(parts);
    };
    let rates;
    let derivs;
    try {
      rates = compileRates(rateBody);
      derivs = compileRates(derivBody);
    } catch (e) {
      throw new RtmError(`The generated rate code did not compile: ${e.message}`);
    }

    /* ---- the rock's layers, and the cells for good ---------------------- */
    if (matrix) {
      layOutMatrix(matrix, rockSpecies(), surface.tw);
      geom = placeCells(matrix.centre);
      params = readParameters(sections.PARAMETERS, col, geom, tables);
      /*
        Layers that grow fast are coarse at depth, where a long-lived species
        spends most of a long run. A short-lived member of a chain sizes the
        first layer by its own decay, and twelve layers from a few micrometres
        to metres of rock then grow by three or more: on the U-238 chain of
        TR-19-06 (Po-210, 0.38 a, puts the first at 4.7 um) twelve grow by 3.4
        and the releases are 4 % out, twenty grow by 2.0 and they are 0.2 %
        out. Said, with the count that keeps the growth to 2.
      */
      if (matrix.grid === 'matched' && matrix.q > 2.5) {
        const need = Math.ceil(Math.log2(matrix.depth / matrix.first + 1));
        warnings.push(`The ${matrix.n} matrix layers grow by ${matrix.q.toFixed(2)} from ${matrix.first.toExponential(2)} m `
          + `${matrix.rule === 'matched' ? '(the first sized by the fastest change the rock has to follow) ' : ''}`
          + `to reach ${matrix.depth} m, which is coarse at depth: MATRIX_CELLS = ${need} would keep the growth to 2.`);
      }
    }

    /*
      What the matched layers are sized by, for each species that enters the
      rock and each cell of the column: its De, its capacities in the rock
      and in the fracture, its decay constant and its own Peclet number --
      Kompartment's de, rm, rf, lam and pe. Read off the parameters as they
      stand before the layers are laid out, which is at the wall.

      The decay constant is what a first-order reaction on the whole
      inventory -- on = inventory, radioactive decay -- takes of the species
      per unit time, the largest anywhere. Chemistry on the water is left
      out: a fast reversible pair is an exchange, not a loss, and sizing the
      layers by its rate constant would make them absurdly thin.
    */
    function rockSpecies() {
      const valueAt = (spec, c, fallback) => {
        if (spec === null) return fallback;
        const asNumber = Number(spec);
        if (Number.isFinite(asNumber)) return asNumber;
        if (params.index.has(spec)) return params.values[params.index.get(spec)][c];
        return NaN;     // named nothing: the mass matrix below says so
      };
      const np0 = params.order.length;
      const P0 = new Float64Array(Math.max(np0, 1));
      const loads = [];
      for (const ch of channels) {
        if (!ch.whole || ch.deps.length !== 1) continue;
        const dep = ch.deps[0];
        const own = ch.net.find(([p]) => p === dep.si);
        if (!own || !(own[1] < 0) || /\by\[|\bTV\[|\bt\b/.test(ch.derivCode[0])) continue;
        // eslint-disable-next-line no-new-func
        loads.push({ si: dep.si, c: -own[1], at: new Function('P', 'pb', `return ${ch.derivCode[0]};`) });
      }
      const lam = new Float64Array(ns);
      for (let i = 0; i < nf; i++) {
        for (const c of [cellOf(i, 0), cellOf(i, 1)]) {
          for (let k = 0; k < np0; k++) P0[k] = params.values[k][c];
          const here = new Float64Array(ns);
          for (const l of loads) here[l.si] += l.c * l.at(P0, 0);
          for (let s = 0; s < ns; s++) if (here[s] > lam[s]) lam[s] = here[s];
        }
      }
      const uPore = settings.ADVECTION ? Math.abs(settings.VELOCITY) / (settings.POROSITY > 0 ? settings.POROSITY : 1) : 0;
      // Each species' own Peclet number: the Peclet setting when it has no D
      // of its own, which is Kompartment's path exactly. Without flow there
      // is no travel time for one to be a share of.
      const peOf = (s) => {
        const Ds = settings.DIFFUSION ? species[s].D : 0;
        if (!(uPore > 0)) return Infinity;
        if (peclet > 0) return Ds > 0 ? (uPore * grid.L) / (Ds + (uPore * grid.L) / peclet) : peclet;
        return Ds > 0 ? (uPore * grid.L) / Ds : Infinity;
      };
      const out = [];
      for (let s = 0; s < ns; s++) {
        if (!enters[s]) continue;
        const pe = peOf(s);
        for (let i = 0; i < nf; i++) {
          out.push({ de: species[s].Dm, rm: valueAt(species[s].Rm, cellOf(i, 1), matrix.porosity),
            rf: valueAt(species[s].mass, cellOf(i, 0), 1), lam: lam[s], pe });
        }
      }
      return out;
    }

    /* ---- the grid and what moves --------------------------------------- */
    const nc = ncol * stride;       // every cell, matrix layers and extra cells included
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
    // The limited scheme spreads a front by far less than v*dz/2: what follows
    // is about upwinding, and only about it.
    const limited = transport && !!settings.ADVECTION && settings.VELOCITY !== 0
      && settings.ADVECTION_SCHEME === 'limited';
    if (settings.ADVECTION_SCHEME === 'limited' && !limited && settings.given && settings.given.has('ADVECTION_SCHEME')) {
      warnings.push('ADVECTION_SCHEME = limited, and nothing is advected here: it does nothing.');
    }
    if (!limited && peclet > 0 && 2 * nf < peclet) {
      warnings.push(`${nf} cells disperse as a Peclet number of ${2 * nf} would, and PECLET = ${peclet} `
        + 'was asked for: the upwind scheme spreads a front by v*dz/2 on its own, more than the '
        + `setting wants, and the correction that would sharpen it cannot be negative. ${Math.ceil(peclet / 2)} `
        + 'cells (Pe/2) is the fewest that reaches it.');
    }
    if (!limited && transport && !peclet && settings.ADVECTION && settings.VELOCITY !== 0 && settings.DIFFUSION) {
      const u = Math.abs(settings.VELOCITY) / (settings.POROSITY > 0 ? settings.POROSITY : 1);
      // The coarsest cell is where the scheme disperses most; on an even grid
      // that is every cell.
      const dz = Math.max(...grid.width);
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
      HELD, STATE BY STATE. `fixed` on a species line holds it in every cell;
      "fixed" at the end of an <INITIAL> line holds it in those cells only --
      a reservoir cell at the end of a column, a surface species that must
      not appear in the water. Either way the state's row is zero: nothing
      moves it, and it still drives its neighbours and its reactions.
    */
    const fixedAt = new Uint8Array(n);
    for (let c = 0; c < nc; c++) for (let s = 0; s < ns; s++) if (fixed[s]) fixedAt[c * ns + s] = 1;
    const patchCells = (p) => {
      const out = [];
      // A line that reaches the last cell reaches the cells past a
      // semi-infinite end too: they are the column going on.
      const to = p.to === nf - 1 ? last : p.to;
      for (let i = p.from; i <= to; i++) {
        if (!p.matrix) { out.push(cellOf(i, 0)); continue; }
        if (!matrix) throw new RtmError('"matrix" in <INITIAL> needs a rock matrix: MATRIX_DEPTH and the rest.', p.line);
        for (let j = 1; j <= nm; j++) out.push(cellOf(i, j));
      }
      return out;
    };
    for (const p of patches) {
      if (p.fixed && species[p.si].mineral) {
        throw new RtmError(`${species[p.si].name} is a mineral, and a mineral is never held: its amount is what `
          + 'the water leaves of it.', p.line);
      }
      if (p.fixed) for (const c of patchCells(p)) fixedAt[c * ns + p.si] = 1;
    }
    // Held somewhere but not everywhere, by species: what the panel reports.
    const held = [];
    for (let s = 0; s < ns; s++) {
      if (fixed[s]) continue;
      const cellsHeld = [];
      for (let c = 0; c < nc; c++) if (fixedAt[c * ns + s]) cellsHeld.push(c);
      if (cellsHeld.length) held.push({ species: nameOf[s], si: s, cells: cellsHeld });
    }

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
    // term is multiplied by the capacity of the species it is a share of, so
    // that the division by invMass at the end leaves the parent's own rate
    // on its concentration, R dC/dt = -lambda*R*C, and a daughter's gain the
    // parent's inventory over its own capacity.
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
    // The pairs under ACTIVITY: each side's species with their powers, and
    // the columns a pair's rate reads -- its own species, every ion through
    // the ionic strength, and with water in it every solute through a(H2O).
    const ions = act ? species.map((_, k) => k).filter((k) => act.z[k] !== 0) : [];
    const solutes = act ? species.map((_, k) => k).filter((k) => act.solute[k]) : [];
    const pairInfo = apairs.map((eq) => {
      const side = (terms) => {
        const m = new Map();
        for (const [c, name] of terms) { const k = index.get(name); m.set(k, (m.get(k) || 0) + c); }
        return [...m.entries()];
      };
      const reac = side(eq.reactants);
      const prod = side(eq.products);
      const colsOf = [...new Set([...reac.map(([k]) => k), ...prod.map(([k]) => k), ...ions,
        ...(eq.water ? solutes : [])])].sort((x, y) => x - y);
      return { eq, reac, prod, cols: colsOf, at: new Map(colsOf.map((k, q) => [k, q])), net: eq.net,
        kf: eq.kf, kb: eq.kf / Math.exp(eq.lnK), water: eq.water || 0, d: new Float64Array(colsOf.length) };
    });
    for (let i = 0; i < nc; i++) {
      const b = i * ns;
      for (const ch of channels) {
        for (const [p] of ch.net) {
          if (fixedAt[b + p]) continue;
          for (const dep of ch.deps) touch(b + p, b + dep.si);
        }
      }
      for (const pr of pairInfo) {
        for (const [p] of pr.net) {
          if (fixedAt[b + p]) continue;
          for (const k of pr.cols) touch(b + p, b + k);
        }
      }
      // A rate law that reads activities, I or a saturation: every species they read.
      for (const ch of channels) {
        if (!ch.aqCols) continue;
        for (const [p] of ch.net) {
          if (fixedAt[b + p]) continue;
          for (const k of ch.aqCols) touch(b + p, b + k);
        }
      }
      for (let s = 0; s < ns; s++) {
        // Every state gets a diagonal: a fixed species has a zero row and the
        // iteration matrix I - hJ still needs the 1 on its diagonal, and a
        // solver may ask for the entry whatever its value.
        touch(b + s, b + s);
        const g = geom[i];
        if (g.j === 0) {
          // Along the fracture, to the neighbouring fracture cells -- two
          // either way when advection is limited, the slope of the cell
          // upwind of a face reading the cell beyond it.
          if (mobile[s]) {
            if (g.i > 0) touch(b + s, cellOf(g.i - 1, 0) * ns + s);
            if (g.i < ncol - 1) touch(b + s, cellOf(g.i + 1, 0) * ns + s);
            if (limited && g.i > 1) touch(b + s, cellOf(g.i - 2, 0) * ns + s);
            if (limited && g.i < ncol - 2) touch(b + s, cellOf(g.i + 2, 0) * ns + s);
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
    // Nernst-Planck: every coupled ion on either side of a face reads every
    // other on either side.
    for (let i = 0; npIons.length && i < last; i++) {
      const A = cellOf(i, 0) * ns;
      const B = cellOf(i + 1, 0) * ns;
      const closedB = semi && i + 1 === last;
      for (const { s: k } of npIons) {
        for (const { s: mm } of npIons) {
          touch(A + k, A + mm);
          touch(A + k, B + mm);
          if (!closedB) { touch(B + k, A + mm); touch(B + k, B + mm); }
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
    // Where the derivatives through AQ go, cell by cell and channel by channel.
    const aqSlots = nq ? Array.from({ length: nc }, (_, i) => channels.map((ch) => {
      if (!ch.aqCols || !ch.aqCols.length) return null;
      const b = i * ns;
      const at = new Int32Array(ch.net.length * ch.aqCols.length).fill(-1);
      ch.net.forEach(([p], m) => {
        if (fixedAt[b + p]) return;
        ch.aqCols.forEach((k, u) => { at[m * ch.aqCols.length + u] = slot(b + p, b + k); });
      });
      return at;
    })) : null;
    // Where each pair's derivatives go, cell by cell: row (each species it
    // changes) by column, -1 where the row is held.
    const pairSlots = pairInfo.length ? Array.from({ length: nc }, (_, i) => pairInfo.map((pr) => {
      const b = i * ns;
      const at = new Int32Array(pr.net.length * pr.cols.length).fill(-1);
      pr.net.forEach(([p], m) => {
        if (fixedAt[b + p]) return;
        pr.cols.forEach((k, q) => { at[m * pr.cols.length + q] = slot(b + p, b + k); });
      });
      return at;
    })) : null;

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

      semi-      the column goes on past the face, and the face is a plane
      infinite   inside it: the flow and the dispersion both cross it, into
                 the extra cells beyond, which are the same column. The last
                 of those is closed by linear extrapolation, which continues
                 the gradient through its far face, so that the dispersion
                 into it from upstream leaves it again and its own row has
                 none: Kompartment's outlet 4, which is its OB 2 at the end of
                 its extra cells. A Danckwerts outlet (free) instead lets out
                 4a/(1+a)^2 of what the semi-infinite column does at a
                 frequency where a = sqrt(1 + 4 tw g/Pe): about 3 % short at
                 the peak of Kompartment's far-field example.

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
    // put it beside SKB's and Kompartment's own numbers term for term.
    const dual = matrix ? { aw: matrix.aw, porosity: matrix.porosity, d: Array.from(matrix.d),
      h: matrix.h ? Array.from(matrix.h) : null, grid: matrix.grid,
      advF: null, dF: null, species: [] } : null;
    // The dispersion of species s in column cell i: its own D, and with a
    // Peclet number the hydrodynamic dispersion the cell is short of.
    const v = transport && settings.ADVECTION ? settings.VELOCITY : 0;
    const u = v / (settings.POROSITY > 0 ? settings.POROSITY : 1);
    // With the limited scheme nothing is taken back: it does not spread a
    // front by u*dz/2 for the dispersion to make up.
    const dispersionAt = (s, i) => (settings.DIFFUSION ? species[s].D : 0)
      + (peclet > 0 ? Math.max(0, (Math.abs(u) * grid.L) / peclet - (limited ? 0 : (Math.abs(u) * col.width[i]) / 2)) : 0);
    if (transport) {
      for (let s = 0; s < ns; s++) {
        if (!mobile[s]) continue;
        const Dspecies = settings.DIFFUSION ? species[s].D : 0;
        for (let i = 0; i < ncol; i++) {
          const row = cellOf(i, 0) * ns + s;
          const w = col.width[i];
          /*
            The dispersion. A Peclet number gives every species the same
            hydrodynamic dispersion u*L/Pe along the fracture, on top of its
            own D. The upwind scheme already spreads a front by u*dz/2 -- as
            if Pe were 2*N -- so that much is taken back, and never below
            zero: SKB's rule, adv*(N/Pe - 1/2), in coefficients rather than
            rates. Without a Peclet number the species' own D stands, and the
            numerical part is simply there, as it is on every upwind grid.
          */
          const disp = peclet > 0 ? Math.max(0, (Math.abs(u) * grid.L) / peclet - (limited ? 0 : (Math.abs(u) * w) / 2)) : 0;
          const D = Dspecies + disp;
          if (dual && dual.advF === null && u !== 0) { dual.advF = Math.abs(u) / w; dual.dF = disp / (w * w); }
          // The last cell past a semi-infinite end is closed by linear
          // extrapolation: what disperses into it leaves through its far
          // face, and its own row has no dispersion at all.
          const closed = semi && i === last;
          // --- the face to the left ---
          if (closed) {
            // nothing: see above
          } else if (i > 0) {
            const d = col.centres[i] - col.centres[i - 1];
            const g = D / (d * w);
            if (g) { flowIn.push({ row, col: cellOf(i - 1, 0) * ns + s, value: g }); flowIn.push({ row, col: row, value: -g }); }
          } else if (settings.LEFT === 'dirichlet') {
            // robin and free put no diffusive flux through the face at all:
            // the first prescribes the total flux, the second the gradient.
            const d = col.centres[0] - 0;
            const g = D / (d * w);
            const cb = species[s].left == null ? species[s].initial : species[s].left;
            if (g) { flowIn.push({ row, col: row, value: -g }); boundary.push({ row, value: g * cb }); }
          }
          // --- the face to the right ---
          if (i < last) {
            const d = col.centres[i + 1] - col.centres[i];
            const g = D / (d * w);
            if (g) { flowIn.push({ row, col: cellOf(i + 1, 0) * ns + s, value: g }); flowIn.push({ row, col: row, value: -g }); }
          } else if (settings.RIGHT === 'dirichlet') {
            const d = grid.L - col.centres[nf - 1];
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
              if (i < last) flowIn.push({ row, col: cellOf(i + 1, 0) * ns + s, value: -a });
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

        The matched layers are the same ladder with its nodes interlaced
        rather than at the centres: De/h_0 from the wall to the first node,
        De/h_j+1 between nodes j and j+1 -- Kompartment's rates, term for
        term, in the same way.
      */
      if (matrix) {
        const d = matrix.d;
        const h = matrix.h;
        const aw = matrix.aw;
        for (let s = 0; s < ns; s++) {
          if (!enters[s]) continue;
          const De = species[s].Dm;
          const rates = h
            ? { name: species[s].name, diffFM1: (aw * De) / h[0], diffM1F: De / (d[0] * h[0]),
              diffMMF: [], diffMMB: [] }
            : { name: species[s].name, diffFM1: (aw * 2 * De) / d[0],
              diffM1F: (2 * De) / (d[0] * d[0]), diffMMF: [], diffMMB: [] };
          for (let j = 0; j < nm - 1; j++) {
            if (h) {
              rates.diffMMF.push(De / (d[j] * h[j + 1]));
              rates.diffMMB.push(De / (d[j + 1] * h[j + 1]));
            } else {
              rates.diffMMF.push((2 * De) / (d[j] * (d[j] + d[j + 1])));
              rates.diffMMB.push((2 * De) / (d[j + 1] * (d[j + 1] + d[j])));
            }
          }
          dual.species.push(rates);
          for (let i = 0; i < ncol; i++) {
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
    /*
      THE FLUX THROUGH EACH END, per species: what crosses the plane at x = 0
      and the plane at x = LENGTH, positive to the right, per m2 of the
      water's cross-section -- concentration times metres per unit of time.
      At an outlet that is the release, which is what a far-field path is
      read for; at a semi-infinite end it is advection and dispersion both,
      across the plane between the column and its extra cells, and with no
      extra cells across the far face of the last cell, the gradient carried
      on through it as the closure does. Each is a sum over states plus a
      constant (a face held at a concentration), so the page works it out
      from the stored run. Exactly what the assembly above puts through those
      faces, written out apart.
    */
    const faces = transport ? { left: [], right: [] } : null;
    if (transport) {
      const at = (i, s) => cellOf(i, 0) * ns + s;
      const N = nf - 1;
      for (let s = 0; s < ns; s++) {
        const left = { terms: [], constant: 0 };
        const right = { terms: [], constant: 0 };
        faces.left.push(left);
        faces.right.push(right);
        if (!mobile[s]) continue;
        const cbLeft = species[s].left == null ? species[s].initial : species[s].left;
        const cbRight = species[s].right == null ? species[s].initial : species[s].right;
        // The left face, x = 0.
        if (v > 0) {
          if (settings.LEFT === 'dirichlet' || settings.LEFT === 'robin') left.constant += u * cbLeft;
        } else if (v < 0) left.terms.push([at(0, s), u]);
        if (settings.LEFT === 'dirichlet') {
          const g = dispersionAt(s, 0) / col.centres[0];
          if (g) { left.terms.push([at(0, s), -g]); left.constant += g * cbLeft; }
        }
        // The right face, x = LENGTH.
        if (v > 0) right.terms.push([at(N, s), u]);
        else if (v < 0 && (settings.RIGHT === 'dirichlet' || settings.RIGHT === 'robin')) right.constant += u * cbRight;
        if (settings.RIGHT === 'dirichlet') {
          const g = dispersionAt(s, N) / (grid.L - col.centres[N]);
          if (g) { right.terms.push([at(N, s), g]); right.constant -= g * cbRight; }
        } else if (semi) {
          const D = dispersionAt(s, N);
          if (nb > 0) {
            const g = D / (col.centres[N + 1] - col.centres[N]);
            if (g) right.terms.push([at(N, s), g], [at(N + 1, s), -g]);
          } else {
            const g = D / (col.centres[N] - col.centres[N - 1]);
            if (g) right.terms.push([at(N - 1, s), g], [at(N, s), -g]);
          }
        }
      }
    }

    // Pre-resolved slots, so neither rhs nor jac searches the pattern per step.
    // A held state takes nothing from its neighbours or its faces: its row
    // is zero. It still gives -- the terms in its neighbours' rows stay --
    // which is what makes a held cell a reservoir.
    for (let k = flowIn.length - 1; k >= 0; k--) if (fixedAt[flowIn[k].row]) flowIn.splice(k, 1);
    for (let k = boundary.length - 1; k >= 0; k--) if (fixedAt[boundary[k].row]) boundary.splice(k, 1);
    const flowSlot = flowIn.map((f) => slot(f.row, f.col));
    /*
      The same terms as flat typed arrays, row by row, for the derivative's
      loop: an array of objects is a property load and a pointer chase per
      term, and on a column of four thousand states this loop was half of
      every evaluation of the derivative. The rows are walked in order and
      each is summed in a register; within a row the terms keep the order
      they were made in, and nothing else touches a row between its terms,
      so the derivative is the same to the last bit.
    */
    const nflow = flowIn.length;
    const byRow = Array.from(flowIn, (_, k) => k).sort((p, q) => flowIn[p].row - flowIn[q].row || p - q);
    const flowCol = Int32Array.from(byRow, (k) => flowIn[k].col);
    const flowValue = Float64Array.from(byRow, (k) => flowIn[k].value);
    const flowAt = Int32Array.from(byRow, (k) => flowSlot[k]);
    const rowsFlowing = [];
    const flowStarts = [0];
    for (let k = 0; k < nflow; k++) {
      const row = flowIn[byRow[k]].row;
      if (!rowsFlowing.length || rowsFlowing[rowsFlowing.length - 1] !== row) {
        if (rowsFlowing.length) flowStarts.push(k);
        rowsFlowing.push(row);
      }
    }
    flowStarts.push(nflow);
    const flowRows = Int32Array.from(rowsFlowing);
    const flowStart = Int32Array.from(flowStarts);
    const nbound = boundary.length;
    const boundRow = Int32Array.from(boundary, (f) => f.row);
    const boundValue = Float64Array.from(boundary, (f) => f.value);
    const heldStates = [];
    for (let k = 0; k < fixedAt.length; k++) if (fixedAt[k]) heldStates.push(k);
    const heldList = Int32Array.from(heldStates);
    // Each channel's products and coefficients, likewise.
    const chanSpecies = channels.map((ch) => Int32Array.from(ch.net, (e) => e[0]));
    const chanCoef = channels.map((ch) => Float64Array.from(ch.net, (e) => e[1]));
    const chanWhole = Uint8Array.from(channels, (ch) => (ch.whole ? 1 : 0));
    // Whose capacity a rate on the inventory is a share of; -1 for each its own.
    const chanCap = Int32Array.from(channels, (ch) => (ch.whole && ch.capOf >= 0 ? ch.capOf : -1));
    const nchan = channels.length;

    /*
      ADVECTION, LIMITED (ADVECTION_SCHEME = limited). Upwinding takes a face
      at the value of the cell upwind of it; this adds the slope of that cell
      times the distance to the face, so the face is read where the profile
      would have it. The slope is an average of the gradients on either side,
      2 a^2 b^2 (a + b)/((a^2 + b^2)^2 + E^2), and none at all where they
      differ in sign, so no new peak or trough is made and nothing goes below
      zero: second order where the profile is smooth (a = b gives a), upwind
      where it turns. As a limiter it is phi(r) = 2r^2(1 + r)/(1 + r^2)^2,
      inside the TVD region (0 <= phi <= min(2r, 2), phi(1) = 1); unlike van
      Albada's it starts from zero with zero slope, so the slope and its
      derivatives are continuous where a gradient changes sign, and the
      Jacobian is one a difference of the state can check. On
      cell k upwind of the face, and m on the other side of it, that is
      -u s/2 in k and +u s w_k/(2 w_m) in m. The first cell and the last stay
      upwind -- each needs a neighbour it does not have -- so the faces at the
      ends, and what crosses them, are as upwinding has them.

      E = (1e-3 Cs)^2/(h h'), with Cs the species' scale (its largest start or
      face value): where a profile is flat to a part in a thousand of the
      scale over a cell -- rounding behind a front -- the slope fades to
      upwind, smoothly, rather than taking a slope of either sign from the
      rounding that a difference of the state cannot follow.
    */
    const limitedFaces = [];
    if (limited) {
      for (let s2 = 0; s2 < ns; s2++) {
        if (!mobile[s2]) continue;
        const at = (i) => cellOf(i, 0) * ns + s2;
        let scale = Math.abs(species[s2].initial);
        for (const bc of [species[s2].left, species[s2].right]) if (bc != null) scale = Math.max(scale, Math.abs(bc));
        for (const pt of patches) if (pt.si === s2 && pt.value != null) scale = Math.max(scale, Math.abs(pt.value));
        if (!(scale > 0)) scale = 1e-30;
        for (let k = 1; k < last; k++) {
          const m = v > 0 ? k + 1 : k - 1;
          const f = {
            prev: at(k - 1), here: at(k), next: at(k + 1), down: at(m),
            hUp: col.centres[k] - col.centres[k - 1], hDn: col.centres[k + 1] - col.centres[k],
            E: (1e-6 * scale * scale) / ((col.centres[k] - col.centres[k - 1]) * (col.centres[k + 1] - col.centres[k])),
            // Nothing into a cell where the species is held.
            inHere: fixedAt[at(k)] ? 0 : -u / 2,
            inDown: fixedAt[at(m)] ? 0 : (u * col.width[k]) / (2 * col.width[m]),
          };
          // Where its derivatives go: rows k and m, columns k-1, k, k+1.
          f.slots = Int32Array.from([f.prev, f.here, f.next].flatMap((c) => [slot(f.here, c), slot(f.down, c)]));
          limitedFaces.push(f);
        }
      }
    }
    const nlim = limitedFaces.length;
    /** The limited slope and its derivatives in a and b, into lim. */
    const lim = new Float64Array(3);
    const slopeOf = (a, b, E) => {
      if (!(a * b > 0)) { lim[0] = 0; lim[1] = 0; lim[2] = 0; return; }
      const q = a * a + b * b;
      const D = q * q + E * E;
      const N = 2 * a * a * b * b * (a + b);
      lim[0] = N / D;
      lim[1] = ((6 * a * a * b * b + 4 * a * b * b * b) * D - N * 4 * a * q) / (D * D);
      lim[2] = ((4 * a * a * a * b + 6 * a * a * b * b) * D - N * 4 * b * q) / (D * D);
    };
    // The correction into out, or its derivatives into V.
    const limitedFlux = (y, out, V) => {
      for (let q = 0; q < nlim; q++) {
        const f = limitedFaces[q];
        const a = (y[f.next] - y[f.here]) / f.hDn;
        const b = (y[f.here] - y[f.prev]) / f.hUp;
        slopeOf(a, b, f.E);
        if (out) {
          if (lim[0] === 0) continue;
          out[f.here] += f.inHere * lim[0];
          out[f.down] += f.inDown * lim[0];
          continue;
        }
        if (lim[1] === 0 && lim[2] === 0) continue;
        // ds/dC for C_prev, C_here, C_next.
        const dPrev = -lim[2] / f.hUp;
        const dHere = -lim[1] / f.hDn + lim[2] / f.hUp;
        const dNext = lim[1] / f.hDn;
        const sl = f.slots;
        V[sl[0]] += f.inHere * dPrev; V[sl[1]] += f.inDown * dPrev;
        V[sl[2]] += f.inHere * dHere; V[sl[3]] += f.inDown * dHere;
        V[sl[4]] += f.inHere * dNext; V[sl[5]] += f.inDown * dNext;
      }
    };

    /*
      DIFFUSION = nernst-planck. With no current flowing, a face carries each
      ion at J_k = -D_k g_k + D_k z_k C_k (sum z_j D_j g_j)/(sum z_j^2 D_j C_j),
      g the gradient across the face and C its mean: the first term is the
      diffusion every species already has, the second the pull of the
      diffusion potential, which makes the charges' fluxes cancel. Where every
      D is the same it is nothing in a neutral water. Between column cells; a
      Dirichlet end and the rock matrix stay each species on its own, and the
      gradients are of concentrations, the activity coefficients' left out.
    */
    const npFaces = [];
    for (let i = 0; npIons.length && i < last; i++) {
      const A = cellOf(i, 0) * ns;
      const B = cellOf(i + 1, 0) * ns;
      const closedB = semi && i + 1 === last;
      const f = { A, B, d: col.centres[i + 1] - col.centres[i], wA: col.width[i], wB: col.width[i + 1], closedB,
        slots: new Int32Array(4 * npIons.length * npIons.length).fill(-1) };
      npIons.forEach(({ s: k }, a) => {
        npIons.forEach(({ s: mm }, c) => {
          const o = 4 * (a * npIons.length + c);
          if (!fixedAt[A + k]) { f.slots[o] = slot(A + k, A + mm); f.slots[o + 1] = slot(A + k, B + mm); }
          if (!closedB && !fixedAt[B + k]) { f.slots[o + 2] = slot(B + k, A + mm); f.slots[o + 3] = slot(B + k, B + mm); }
        });
      });
      npFaces.push(f);
    }
    const npJ = new Float64Array(npIons.length);
    /** The coupling's fluxes into out, or their derivatives into V. */
    const npFlux = (y, out, V) => {
      const ni = npIons.length;
      for (const f of npFaces) {
        let N = 0;
        let Den = 0;
        for (const { s: k, z, D } of npIons) {
          N += (z * D * (y[f.B + k] - y[f.A + k])) / f.d;
          Den += z * z * D * 0.5 * (y[f.A + k] + y[f.B + k]);
        }
        if (!(Den > 0)) continue;
        const pull = N / Den;
        if (out) {
          npIons.forEach(({ s: k, z, D }) => {
            const J = D * z * 0.5 * (y[f.A + k] + y[f.B + k]) * pull;
            if (!fixedAt[f.A + k]) out[f.A + k] -= J / f.wA;
            if (!f.closedB && !fixedAt[f.B + k]) out[f.B + k] += J / f.wB;
          });
          continue;
        }
        // dJ_k/dC_m on each side: D_k z_k (delta_km pull/2 + Cbar_k (dN Den - N dDen)/Den^2).
        npIons.forEach(({ s: k, z, D }, a) => {
          const Ck = 0.5 * (y[f.A + k] + y[f.B + k]);
          npIons.forEach(({ z: zm, D: Dm }, c) => {
            const dDen = zm * zm * Dm * 0.5;
            const dNA = -(zm * Dm) / f.d;
            const dNB = (zm * Dm) / f.d;
            const self = a === c ? 0.5 * pull : 0;
            const dA = D * z * (self + Ck * (dNA * Den - N * dDen) / (Den * Den));
            const dB = D * z * (self + Ck * (dNB * Den - N * dDen) / (Den * Den));
            const o = 4 * (a * ni + c);
            if (f.slots[o] >= 0) { V[f.slots[o]] -= dA / f.wA; V[f.slots[o + 1]] -= dB / f.wA; }
            if (f.slots[o + 2] >= 0) { V[f.slots[o + 2]] += dA / f.wB; V[f.slots[o + 3]] += dB / f.wB; }
          });
        });
      }
    };

    /* ---- the model ------------------------------------------------------ */
    const R = new Float64Array(channels.length);
    const D = new Float64Array(Math.max(nd, 1));

    /*
      THE TABLES READ AT THE CLOCK, worked out once per evaluation -- they are
      the same in every cell -- into TV, which the rate code reads. Each
      argument was folded when the rate law was, so all that is left of it is
      t and arithmetic. Where the argument is a straight line in t the table
      turns at known times, and those are where the run is started again
      (`breaks`): a pulse in a release history cannot be stepped over.
    */
    const reads = [...clockReads.values()];
    const ntv = reads.length;
    const TV = new Float64Array(Math.max(ntv, 1));
    const readArg = reads.map((rd) => {
      const code = emit(rd.arg, (id) => {
        if (id === 't') return 't';
        throw new RtmError(`"${id}" cannot be read at the clock.`);
      });
      // eslint-disable-next-line no-new-func
      return new Function('t', `return ${code};`);
    });
    let tvAt = NaN;
    const atTheClock = (t) => {
      if (t === tvAt) return;
      for (let k = 0; k < ntv; k++) TV[k] = tableAt(reads[k].tab, readArg[k](t), reads[k].col);
      tvAt = t;
    };
    // Where each read turns, in time: (x - b)/a for every row x of its table.
    const turns = [];
    for (const rd of reads) {
      const ln = lineInTime(rd.arg);
      if (!ln || !(ln.a !== 0) || !Number.isFinite(ln.a)) continue;
      for (const x of rd.tab.corners) turns.push((x - ln.b) / ln.a);
    }
    turns.sort((a, b2) => a - b2);

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
          if (fixedAt[b + p]) { perNet.push([]); continue; }
          perNet.push(ch.deps.map((dep) => slot(b + p, b + dep.si)));
        }
        perChannel.push(perNet);
      }
      slotCache.push(perChannel);
    }

    /*
      THE PAIRS UNDER ACTIVITY, beside the generated code: forward kf times
      the reactants, backward kb*Gamma times the products, Gamma following the
      ionic strength of the cell. One activity evaluation a cell serves them
      all.
    */
    const lnG = act ? new Float64Array(ns) : null;
    const dG = act ? new Float64Array(ns) : null;
    /**
     * One pair's rate in the cell at b; kb*Gamma kept in pr.kg and the
     * backward rate in pr.back, for the Jacobian.
     */
    const pairRate = (pr, y, b, water) => {
      let fwd = pr.kf;
      for (const [k, e] of pr.reac) fwd *= e === 1 ? y[b + k] : y[b + k] ** e;
      let lnGamma = pr.water * water.lnAw;
      for (const [k, c] of pr.net) lnGamma += c * lnG[k];
      pr.kg = pr.kb * Math.exp(lnGamma);
      let back = pr.kg;
      for (const [k, e] of pr.prod) back *= e === 1 ? y[b + k] : y[b + k] ** e;
      pr.back = back;
      return fwd - back;
    };
    /** d(prod of y^e over a side)/dy_k, the side's own species only. */
    const sideDerivative = (terms, y, b, k) => {
      let d = 0;
      for (const [s1, e1] of terms) {
        if (s1 !== k) continue;
        d = e1 === 1 ? 1 : e1 * y[b + s1] ** (e1 - 1);
        for (const [s2, e2] of terms) if (s2 !== k) d *= e2 === 1 ? y[b + s2] : y[b + s2] ** e2;
      }
      return d;
    };

    function rhs(t, y, out) {
      out.fill(0);
      if (ntv) atTheClock(t);
      if (pairInfo.length) {
        for (let i = 0; i < nc; i++) {
          const b = i * ns;
          const water = activityAt(act, y, b, lnG, dG);
          const sc = reactScale[i];
          for (const pr of pairInfo) {
            const r = pairRate(pr, y, b, water) * sc;
            if (r === 0) continue;
            for (const [p, c] of pr.net) if (!fixedAt[b + p]) out[b + p] += c * r;
          }
        }
      }
      if (nchan) {
        for (let i = 0; i < nc; i++) {
          const b = i * ns;
          if (nq) aqAt(y, b, false);
          rates(y, b, P, i * np, R, D, t, TV, AQ);
          const sc = reactScale[i];
          for (let j = 0; j < nchan; j++) {
            const r = R[j];
            if (r === 0) continue;
            const sp = chanSpecies[j];
            const coef = chanCoef[j];
            const whole = chanWhole[j];
            const cap = chanCap[j];
            for (let m = 0; m < sp.length; m++) {
              const p = sp[m];
              if (fixedAt[b + p]) continue;
              out[b + p] += coef[m] * r * (whole ? massOf[b + (cap >= 0 ? cap : p)] : sc);
            }
          }
        }
      }
      for (let q = 0; q < flowRows.length; q++) {
        const row = flowRows[q];
        let acc = out[row];
        for (let k = flowStart[q], end = flowStart[q + 1]; k < end; k++) acc += flowValue[k] * y[flowCol[k]];
        out[row] = acc;
      }
      for (let k = 0; k < nbound; k++) out[boundRow[k]] += boundValue[k];
      if (nlim) limitedFlux(y, out, null);
      if (npFaces.length) npFlux(y, out, null);
      for (let k = 0; k < heldList.length; k++) out[heldList[k]] = 0;
      // M dC/dt = f, so every term on the right -- reaction, transport and
      // boundary alike -- is divided by the coefficient of that row.
      if (anyMass) for (let k = 0; k < n; k++) out[k] *= invMass[k];
      return out;
    }

    function jac(t, y, V) {
      V.fill(0);
      if (ntv) atTheClock(t);
      for (let i = 0; i < nc; i++) {
        const b = i * ns;
        if (nq) aqAt(y, b, true);
        derivs(y, b, P, i * np, R, D, t, TV, AQ);
        const sc = reactScale[i];
        for (let j = 0; j < channels.length; j++) {
          const ch = channels[j];
          const d0 = derivIndex[j];
          for (let m = 0; m < ch.net.length; m++) {
            const p = ch.net[m][0];
            if (fixedAt[b + p]) continue;
            const c = ch.net[m][1] * (ch.whole ? massOf[b + (chanCap[j] >= 0 ? chanCap[j] : p)] : sc);
            for (let q = 0; q < ch.deps.length; q++) {
              const dv = D[d0 + q];
              if (dv === 0) continue;
              V[slotCache[i][j][m][q]] += c * dv;
            }
            // What it reads besides: d(rate)/d(AQ) times d(AQ)/dC.
            const cols = ch.aqCols;
            if (!cols || !cols.length) continue;
            const at = aqSlots[i][j];
            for (let u = 0; u < cols.length; u++) {
              let dv = 0;
              for (let e = 0; e < ch.aq.length; e++) {
                const dR = D[ch.aqD[e]];
                if (dR !== 0) dv += dR * dAQ[ch.aq[e].q][cols[u]];
              }
              if (dv !== 0) V[at[m * cols.length + u]] += c * dv;
            }
          }
        }
      }
      if (pairInfo.length) {
        for (let i = 0; i < nc; i++) {
          const b = i * ns;
          const water = activityAt(act, y, b, lnG, dG);
          const sc = reactScale[i];
          pairInfo.forEach((pr, j) => {
            pairRate(pr, y, b, water);
            const d = pr.d;
            d.fill(0);
            // The mass action of each side...
            for (const [k] of pr.reac) d[pr.at.get(k)] += pr.kf * sideDerivative(pr.reac, y, b, k);
            for (const [k] of pr.prod) d[pr.at.get(k)] -= pr.kg * sideDerivative(pr.prod, y, b, k);
            // ...and Gamma through the ionic strength and the water.
            let G = 0;
            for (const [k, c] of pr.net) G += c * dG[k];
            if (pr.back !== 0) {
              pr.cols.forEach((k, q) => {
                let g = G * 0.5 * act.z[k] * act.z[k];
                if (pr.water && act.solute[k]) g += pr.water * water.dAw;
                if (g) d[q] -= pr.back * g;
              });
            }
            const at = pairSlots[i][j];
            const ncol = pr.cols.length;
            pr.net.forEach(([, c], m) => {
              if (at[m * ncol] < 0) return;
              for (let q = 0; q < ncol; q++) if (d[q]) V[at[m * ncol + q]] += c * sc * d[q];
            });
          });
        }
      }
      for (let k = 0; k < nflow; k++) V[flowAt[k]] += flowValue[k];
      if (nlim) limitedFlux(y, null, V);
      if (npFaces.length) npFlux(y, null, V);
      if (anyMass) for (let k = 0; k < nnz; k++) V[k] *= invMass[rowOfSlot[k]];
      return V;
    }

    const initial = new Float64Array(n);
    for (let i = 0; i < nc; i++) {
      for (let s = 0; s < ns; s++) initial[i * ns + s] = species[s].initial;
    }
    /*
      A Dirichlet face does NOT set the cell that touches it. It used to start
      that cell at the face value, to spare the solver a jump on its first
      step, and that silently replaced the starting state the text gives: the
      Crank benchmark, which starts at zero everywhere, was three times less
      accurate at one day for it. The face is a boundary condition; what the
      cells hold at t = 0 is <SPECIES> and <INITIAL>, and nothing else.
    */
    // Last, so that it overrides the <SPECIES> line: it is the most specific
    // thing the reader can have said. A line names fracture cells; with
    // "matrix" it means the rock behind them instead. A value that is an
    // expression is worked out in each cell, with what a parameter may use.
    for (const patch of patches) {
      const bound = patch.ast ? bindTables(patch.ast, tables, patch.line) : null;
      for (const c of patchCells(patch)) {
        if (patch.value === null && !bound) continue;       // "fixed" alone: held where it is
        let v = patch.value;
        if (bound) {
          const g = geom[c];
          const lookup = bound.lookup((id) => {
            const at = placeValue(id, col, g);
            if (at !== undefined) return at;
            if (params.index.has(id)) return params.values[params.index.get(id)][c];
            return undefined;
          });
          try {
            v = FacsimileModel.evalAst(bound.ast, lookup, {}, patch.line);
          } catch (e) {
            throw new RtmError(`In "${patch.src}": ${e.message.replace(/^Line \d+: /, '')}. A starting `
              + 'value may use x, w, xl, xr, i, the parameters and the tables.', patch.line);
          }
          if (!Number.isFinite(v)) {
            throw new RtmError(`"${patch.src}" is not a number in cell ${g.i}.`, patch.line);
          }
        }
        initial[c * ns + patch.si] = v;
      }
    }
    /*
      A species held in some cells and not others cannot be put on the
      equilibria: the speciation holds a species everywhere or nowhere, and
      would move it in the very cells it was meant to stay put in.
    */
    if (settings.EQUILIBRATE && held.length) {
      const inEq = new Set(equilibriumSpecies(equilibria));
      const bad = held.filter((h) => inEq.has(h.si));
      if (bad.length) {
        throw new RtmError(`${bad.map((h) => h.species).join(', ')} ${bad.length > 1 ? 'are' : 'is'} held in `
          + `some cells only and takes part in an <EQUILIBRIUM>; EQUILIBRATE = ${settings.EQUILIBRATE === 2 ? 'always' : 1} `
          + 'cannot speciate that. '
          + 'Hold it everywhere (fixed on its species line) or equilibrate without it.');
      }
    }

    /*
      THE EXCHANGERS' CAPACITIES, cell by cell: the sites the species on each
      take there, or what its own line gives -- which the cell's water loads
      at the start, as PHREEQC's EXCHANGE with -equilibrate does (see
      loadExchangers). A cell with no capacity has no exchanger, and its
      relations nothing to hold.
    */
    if (ex) {
      const nx = ex.exchangers.length;
      ex.capacity = new Float64Array(nc * nx);
      ex.shift = new Float64Array(nc * ns);
      ex.load = [];
      const where = (c) => (nc === 1 ? '' : ` in cell ${geom[c].i}${geom[c].j > 0 ? `, layer ${geom[c].j} of the rock` : ''}`);
      for (let c = 0; c < nc; c++) {
        const b = c * ns;
        ex.exchangers.forEach((k, x) => {
          const cap = initial[b + k];
          let on = 0;
          for (const j of ex.list) if (ex.of[j] === x) on += ex.n[j] * initial[b + j];
          if (cap > 0 && on > 0) {
            throw new RtmError(`${nameOf[k]} is given a capacity${where(c)}, and the species on it amounts there as `
              + 'well: give the capacity, which the water there loads at the start, or what is on it, not both.',
            species[k].line);
          }
          const total = cap + on;
          if (!(total > 0)) {
            throw new RtmError(`${nameOf[k]} has no capacity${where(c)}: give it one on its line, or amounts to the `
              + 'species on it, in every cell its relations are to hold in.', species[k].line);
          }
          ex.capacity[c * nx + x] = total;
          for (const j of ex.list) if (ex.of[j] === x) ex.shift[b + j] = Math.log(ex.n[j] / total);
          if (cap > 0) ex.load.push(c * nx + x);
        });
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
      // The Jacobian is the same at every state and time: see jacobianMoves.
      // A pair under ACTIVITY is mass action with a constant that moves.
      jacobianConstant: !jacobianMoves && !pairInfo.length && !nlim && !npFaces.length,
      /**
       * The times in (t0, t1) at which a table a rate law reads at the clock
       * turns, ascending, near-duplicates merged: where the run is started
       * again. See runModel in facsimile-solver.js.
       */
      breaks(t0, t1) {
        const out = [];
        for (const x of turns) {
          if (!(x > t0 && x < t1)) continue;
          if (!out.length || x - out[out.length - 1] > 1e-12 * Math.abs(x)) out.push(x);
        }
        return out;
      },
      // The tables read at the clock, by name, and how many rows each has.
      clockTables: [...new Set(reads.map((rd) => rd.tab.name))]
        .map((name) => ({ name, rows: tables.get(name).corners.length })),
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
      cells: nc,               // every cell, matrix layers and extra cells included
      fracture: nf,            // the cells along the column
      // The cells past a semi-infinite right-hand end, after the column's own
      // in the state: how many, and where. Null for any other end.
      extra: nb ? { n: nb, centres: col.centres.slice(nf), width: col.width.slice(nf) } : null,
      // The flow-wetted surface and the travel time it was worked out with,
      // when the text gives a surface; aw 0 when it gives none.
      surface,
      // null, or { n, d, h, centre, depth, porosity, density, aw, grid, q,
      // first, rule }: h the node spacings of matched layers (null for the
      // reference layers' centres), rule how the first layer was chosen.
      matrix,
      stride,                  // cells per fracture cell, 1 + matrix layers
      // The flux through each end, per species: { terms: [[state, weight]],
      // constant }, so that sum(weight * y[state]) + constant is it.
      faces,
      cellOf,
      geom,
      enters,
      dual,
      speciesList: species,
      speciesNames: nameOf,
      mobile,
      fixed,
      // The minerals: pure phases, activity 1, amounts that may reach zero.
      mineral: Uint8Array.from(species, (sp) => (sp.mineral ? 1 : 0)),
      // Held state by state, and the species held in some cells only.
      fixedAt,
      held: held.map((h) => ({ species: h.species, cells: h.cells })),
      tables: [...tables.keys()],
      reactions: reactions.map((rx) => ({ line: rx.line, text: rx.text })),
      nreactions: reactions.length,
      equilibria,
      nequilibria: equilibria.length,
      conservation: equilibria.length
        ? conservationBasis(equilibria, ns, fixed, abundanceOf(initial, ns, nc), rank) : [],
      // Where the totals are made from (see conservationBasis), or null.
      rank,
      // PHREEQC's electron, its index, or -1: no amount, its activity 10^-pe.
      electron,
      parameters: params.order.slice(),
      anyMass,
      // The coefficient on the left of each state's equation, R dC/dt = f.
      massOf,
      // What a reaction in each cell is scaled by: the porosity in the rock.
      reactScale,
      // The activity model (activityModel), or null; and what of it to show.
      act,
      activity: act && act.kind !== 'none' ? { kind: act.kind, temperature: act.temperature, A: act.A, B: act.B,
        ions: ions.length, pairs: pairInfo.length } : null,
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
    if (act && act.kind !== 'none' && !(equilibria.length && (settings.EQUILIBRATE || apairs.length))) {
      warnings.push(equilibria.length
        ? `ACTIVITY = ${act.kind} acts on the <EQUILIBRIUM> relations through EQUILIBRATE or a kf, and `
          + 'here there is neither: nothing uses it.'
        : `ACTIVITY = ${act.kind} acts on the <EQUILIBRIUM> relations, and there are none: nothing uses it.`);
    }
    // In a column the exchanger is only an exchanger while its relations hold.
    if (ex && transport && settings.EQUILIBRATE !== 2
      && !equilibria.some((eq) => eq.kf !== null && eq.net.some(([k]) => ex.site[k]))) {
      warnings.push(`What is on the exchanger is put on its relations ${settings.EQUILIBRATE ? 'at the start only' : 'never'}`
        + ', and then stays as it is while the water moves past: EQUILIBRATE = always holds it all through the run.');
    }
    /*
      THE ELECTRON'S START. Given an activity -- pe= -- in every cell, the
      water is first speciated at that pe, the electron held there, as
      PHREEQC's SOLUTION is: its couples share each element out between
      their valence states as that pe has it, and what the electrons the
      couples hold come to is then whatever that makes it. Given none, the
      pe is the water's own, from the valence states as written, which
      needs EQUILIBRATE. Fixed, it is held there all through the run.
    */
    let peStart = false;
    if (electron >= 0) {
      const eName = nameOf[electron];
      let given = 0;
      for (let c = 0; c < nc; c++) if (initial[c * ns + electron] > 0) given++;
      if (given && given < nc) {
        throw new RtmError(`${eName}, the electron, is given an activity in ${given} of the ${nc} cells: give it `
          + 'in every cell, or in none and let the water there set it.', species[electron].line);
      }
      if (!given && !settings.EQUILIBRATE) {
        throw new RtmError(`${eName} is the electron and has nothing to start from: give it a pe, ${eName} electron `
          + 'pe=4, or speciate the start (EQUILIBRATE), and the valence states there set it.', species[electron].line);
      }
      if (fixed[electron] && !given) {
        throw new RtmError(`${eName}, the electron, is fixed: give it the pe it is held at, pe=4.`, species[electron].line);
      }
      peStart = given > 0 && !fixed[electron];
      if (settings.EQUILIBRATE !== 2 && !fixed[electron]) {
        warnings.push(`The relations with the electron are put on ${settings.EQUILIBRATE ? 'at the start only' : 'nothing'}`
          + `: the pe then stays as it ${settings.EQUILIBRATE ? 'was' : 'is given'} while the run goes on, whatever `
          + 'it does to the couples. EQUILIBRATE = always holds them all through the run.');
      }
    }
    if (peStart && settings.EQUILIBRATE) {
      const fx = Uint8Array.from(fixed, (v) => (v ? 1 : 0));
      fx[electron] = 1;
      // Without what goes on an exchanger loaded from this water: that comes next.
      const rel = ex && ex.load.length ? equilibria.filter((eq) => !eq.net.some(([k]) => ex.site[k])) : equilibria;
      if (rel.length) {
        const done = speciate(model, initial, { equilibria: rel, fixed: fx });
        initial.set(done.y);
        const stuck = done.cells.filter((c) => !c.converged);
        if (stuck.length) {
          warnings.push(`The speciation of the initial state at its pe did not converge in ${stuck.length} `
            + `cell${stuck.length > 1 ? 's' : ''} (worst residual `
            + `${Math.max(...stuck.map((c) => c.residual)).toExponential(2)}).`);
        }
      }
    }
    /*
      An exchanger given a capacity takes its load from the water of its
      cell, which stays as it is: after that water's own speciation, under
      EQUILIBRATE, and from the water as written without.
    */
    if (ex && ex.load.length) {
      const water = equilibria.filter((eq) => !eq.net.some(([k]) => ex.site[k]));
      if (settings.EQUILIBRATE && water.length && !peStart) {
        initial.set(speciate(model, initial, { equilibria: water }).y);
      }
      loadExchangers(model, initial);
    }
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

    if (settings.EQUILIBRATE === 2 && equilibria.length) {
      const heldEqs = equilibria.filter((eq) => eq.kf === null);
      if (heldEqs.length) return holdEquilibria(model, heldEqs);
      warnings.push('EQUILIBRATE = always holds the equilibria given no kf, and every one here has a kf: '
        + 'they stay the fast reversible pairs they were.');
    }
    return model;
  }

  /* ======================================================================
     2c. Equilibria held throughout the run
     ====================================================================== */

  /**
   * Which species row each equation goes on: one of its candidates -- for a
   * relation a species that takes part in it -- every equation a different
   * one, by augmenting paths (Kuhn). The iteration matrix then has a
   * non-zero diagonal wherever one can be had; an equation left over takes
   * any of the slots still free, and the LU pivots.
   */
  function matchRows(can, slots) {
    const owner = new Map();
    const choice = new Array(can.length).fill(-1);
    function claim(r, seen) {
      for (const s of can[r]) {
        if (seen.has(s)) continue;
        seen.add(s);
        if (!owner.has(s) || claim(owner.get(s), seen)) {
          owner.set(s, r);
          choice[r] = s;
          return true;
        }
      }
      return false;
    }
    for (let r = 0; r < can.length; r++) claim(r, new Set());
    const left = slots.filter((s) => !owner.has(s));
    for (let r = 0; r < can.length; r++) if (choice[r] < 0) choice[r] = left.shift();
    return choice;
  }

  /**
   * The model with its equilibria held exactly while it runs, as algebraic
   * equations: EQUILIBRATE = always.
   *
   * A relation held exactly is not a rate and cannot be integrated as one. In
   * every cell the conserved totals of the held relations (conservationBasis)
   * become state variables of their own, with the equation transport and the
   * kinetic reactions give them -- each species' rate times its coefficient
   * in the total, summed; an equilibrium adds nothing to a total, which is
   * what makes it one -- and every species that takes part becomes an
   * algebraic variable, fixed at each instant by the relations and the
   * totals. That is M y' = f with M diagonal, ones and zeros, which the NDF
   * integrates as it stands.
   *
   * The algebraic variables are the LOGARITHMS of the concentrations, u = ln C.
   * In u every relation is linear, sum of nu*u = ln K, and no step can drive
   * a concentration negative, which one falling by orders of magnitude in a
   * step would otherwise be extrapolated to. The species stay in the error
   * test, in u, beside the totals: left out, the step grew on the smooth
   * totals alone to where the predictor missed a species by a factor of 1.5
   * and the Newton iteration failed instead -- 49 failed steps in 51 on a
   * groundwater taking acid, 7 with them in.
   *
   * Everything else is the compiled model's own: its rhs and jac are taken at
   * the concentrations and composed with the change of variables. A species'
   * coefficient R (mass) weighs it in the totals, so what is conserved is the
   * inventory. The state is the compiled model's, the logarithms where the
   * held species are, then the totals, cell by cell; toConcentrations gives
   * back what the page shows.
   */
  function holdEquilibria(base, eqs) {
    const ns = base.speciesNames.length;
    const nc = base.cells;
    const nBase = base.nspecies;
    const fixed = base.fixed;
    // An exchanger, or the electron, is no amount: it counts in no total, whatever its R.
    const site = base.rank || null;
    const massless = (s) => !!site && site[s] === 2;
    const massOf = site ? Float64Array.from(base.massOf, (m, i) => (site[i % ns] === 2 ? 0 : m)) : base.massOf;
    const start = base.initialState();
    const basis = conservationBasis(eqs, ns, fixed, abundanceOf(start, ns, nc), site);
    const ne = eqs.length;
    const nb = basis.length;
    const active = equilibriumSpecies(eqs).filter((si) => !fixed[si]);
    const na = active.length;
    if (ne + nb !== na) {
      throw new RtmError(`The equilibria held give ${ne} equations and ${nb} conserved totals, which is `
        + `${ne + nb} for the ${na} species they are free to move: one of them repeats another, or a `
        + 'species fixed in it leaves it without a free one.');
    }
    for (const eq of eqs) {
      for (const [s] of eq.net) {
        if (!fixed[s]) continue;
        for (let c = 0; c < nc; c++) {
          if (!(start[c * ns + s] > 0)) {
            throw new RtmError(`${base.speciesNames[s]} is fixed and takes part in "${eq.text}", so it has to `
              + 'be above zero everywhere for the relation to be held.', eq.line);
          }
        }
      }
    }

    const free = basis.free;
    const pos = new Int32Array(ns).fill(-1);
    active.forEach((s, k) => { pos[s] = k; });
    const U = basis.map((u) => active.map((s) => u[s]));
    /*
      Which row each equation goes on. A total's definition goes on the
      species it was made from, where it is 1 and every other total 0; each
      relation on a species of its own among the rest (matchRows). An
      exchanger counts in no total, so a total made from one is defined on
      a species that does count in it, and the exchanger's row takes one of
      its relations instead.
    */
    const defAt = free.slice();
    const open = active.filter((s) => !free.includes(s) || massless(s));
    const lostTotals = [];
    free.forEach((s, j) => { if (massless(s)) lostTotals.push(j); });
    const choice = matchRows(eqs.map((eq) => eq.net.map(([s]) => s).filter((s) => open.includes(s)))
      .concat(lostTotals.map((j) => open.filter((s) => !massless(s) && U[j][pos[s]] !== 0))), open);
    const relRow = choice.slice(0, ne);
    lostTotals.forEach((j, q) => { defAt[j] = choice[ne + q]; });
    // Under ACTIVITY a relation also reads every ion, through the ionic
    // strength, and with water in it every solute, through a(H2O).
    const act = base.act || null;
    const lnG = act ? new Float64Array(ns) : null;
    const dG = act ? new Float64Array(ns) : null;
    const actCols = eqs.map((eq) => (act ? [...Array(ns).keys()].filter((k) => act.z[k] !== 0
      || (eq.water && act.solute[k])) : []));
    const n = nBase + nc * nb;
    const tIndex = (c, j) => nBase + c * nb + j;
    const held = new Uint8Array(n);
    for (let c = 0; c < nc; c++) for (const s of active) held[c * ns + s] = 1;
    // A mineral is held as its amount, which may reach zero, and not as ln C.
    const isMin = base.mineral || new Uint8Array(ns);
    const lin = new Uint8Array(n);
    for (let c = 0; c < nc; c++) for (const s of active) if (isMin[s]) lin[c * ns + s] = 1;
    // The relations that are a mineral's saturation, and in each cell whether
    // there is any of it: while there is, the relation holds; while there is
    // none, the amount is zero and the water may be undersaturated. Which it
    // is changes at events (see eventValues), and a run starts from the state.
    const mins = [];
    eqs.forEach((eq, r) => { if (eq.mineral >= 0) mins.push(r); });
    const nmin = mins.length;
    const present = new Uint8Array(nc * ne).fill(1);
    const minAt = eqs.map((eq) => eq.net.findIndex(([sp]) => sp === eq.mineral));
    /*
      THE PROJECTED FORM, for a model with the electron in it. A redox front
      passes through a moment no couple buffers: the last of a reductant has
      gone and the oxidant coming in has not yet built up, and the pe jumps
      by ten or more while what is conserved moves by nothing the arithmetic
      can see. Held as relations and definitions, each step's Newton
      iteration would have to make that jump undamped, and does not. So each
      held species' row says instead that it is the speciation of its cell's
      totals -- the cell solved by speciateCell, damped, from where the state
      stands -- and its derivatives are the speciation's own, by the implicit
      function theorem (cellJacobian). The totals are integrated as before
      and only they, with what is not held, are held to the tolerance: the
      species are what the totals make them, at every step.
    */
    const projected = base.electron >= 0;
    // What else the relations read: each ion and solute not held, through I and a(H2O).
    const outside = projected && act
      ? [...Array(ns).keys()].filter((k) => pos[k] < 0 && (act.z[k] !== 0 || act.solute[k])) : [];

    /* ---- the pattern: the compiled model's, composed, and the held rows ---- */
    const bp = base.pattern;
    const cols = Array.from({ length: n }, () => new Set());
    const touch = (row, col) => cols[col].add(row);
    // Projected: where a value of the compiled Jacobian lands. Its row is a
    // held species' -- then the totals it counts in -- or its own; its column
    // a held species' -- then its cell's totals, and what else its cell's
    // relations read, through the speciation -- or its own.
    const rowsOf = (row) => {
      if (!held[row]) return [row];
      const c = Math.floor(row / ns);
      const kk = pos[row - c * ns];
      const out = [];
      for (let j = 0; j < nb; j++) if (U[j][kk]) out.push(tIndex(c, j));
      return out;
    };
    const cellCols = (c) => Array.from({ length: nb }, (_, j) => tIndex(c, j)).concat(outside.map((i) => c * ns + i));
    for (let col = 0; col < nBase; col++) {
      for (let k = bp.colPtr[col]; k < bp.colPtr[col + 1]; k++) {
        const row = bp.rowIdx[k];
        if (projected) {
          const colsTo = held[col] ? cellCols(Math.floor(col / ns)) : [col];
          for (const r of rowsOf(row)) for (const q of colsTo) touch(r, q);
          continue;
        }
        if (!held[row]) { touch(row, col); continue; }
        const c = Math.floor(row / ns);
        const kk = pos[row - c * ns];
        for (let j = 0; j < nb; j++) if (U[j][kk]) touch(tIndex(c, j), col);
      }
    }
    for (let c = 0; c < nc; c++) {
      const b = c * ns;
      if (projected) {
        // A held species: itself, its cell's totals, and what else its relations read.
        for (const s of active) {
          for (let j = 0; j < nb; j++) touch(b + s, tIndex(c, j));
          for (const i of outside) touch(b + s, b + i);
        }
        continue;
      }
      for (let j = 0; j < nb; j++) {
        touch(b + defAt[j], tIndex(c, j));
        for (let k = 0; k < na; k++) if (U[j][k]) touch(b + defAt[j], b + active[k]);
      }
      eqs.forEach((eq, r) => {
        for (const [s] of eq.net) touch(b + relRow[r], b + s);
        for (const k of actCols[r]) touch(b + relRow[r], b + k);
      });
    }
    for (let i = 0; i < n; i++) touch(i, i);
    const colPtr = new Int32Array(n + 1);
    for (let c = 0; c < n; c++) colPtr[c + 1] = colPtr[c] + cols[c].size;
    const nnz = colPtr[n];
    const rowIdx = new Int32Array(nnz);
    for (let c = 0; c < n; c++) {
      [...cols[c]].sort((a, b2) => a - b2).forEach((r, k) => { rowIdx[colPtr[c] + k] = r; });
    }
    const slot = (row, col) => {
      let lo = colPtr[col];
      let hi = colPtr[col + 1] - 1;
      while (lo <= hi) {
        const mid = (lo + hi) >> 1;
        if (rowIdx[mid] === row) return mid;
        if (rowIdx[mid] < row) lo = mid + 1; else hi = mid - 1;
      }
      return -1;
    };

    // Where each value of the compiled Jacobian goes: to its own place when
    // its row is not held, else into the rows of the totals it counts in.
    const aSlot = new Int32Array(bp.nnz).fill(-1);
    const tStart = new Int32Array(bp.nnz + 1);
    const tAt = [];
    const tUc = [];
    const tRow = [];
    for (let col = 0; col < nBase; col++) {
      for (let k = bp.colPtr[col]; k < bp.colPtr[col + 1]; k++) {
        const row = bp.rowIdx[k];
        tStart[k] = tAt.length;
        if (!held[row]) { aSlot[k] = slot(row, col); continue; }
        const c = Math.floor(row / ns);
        const kk = pos[row - c * ns];
        for (let j = 0; j < nb; j++) {
          if (!U[j][kk]) continue;
          tAt.push(slot(tIndex(c, j), col));
          tUc.push(U[j][kk]);
          tRow.push(row);
        }
      }
    }
    tStart[bp.nnz] = tAt.length;
    // The held rows' own entries, per cell.
    const defT = [];
    const defC = [];
    const relC = [];
    const relA = [];
    for (let c = 0; c < nc; c++) {
      const b = c * ns;
      defT.push(Int32Array.from({ length: nb }, (_, j) => slot(b + defAt[j], tIndex(c, j))));
      defC.push(U.map((uj, j) => Int32Array.from(active, (s, k) => (uj[k] ? slot(b + defAt[j], b + s) : -1))));
      relC.push(eqs.map((eq, r) => Int32Array.from(eq.net, ([s]) => slot(b + relRow[r], b + s))));
      relA.push(eqs.map((eq, r) => Int32Array.from(actCols[r], (k) => slot(b + relRow[r], b + k))));
    }
    // The projected rows' entries, per cell: each held species on itself, on
    // its cell's totals, and on what its cell's relations read besides.
    const projDiag = [];
    const projT = [];
    const projO = [];
    if (projected) {
      for (let c = 0; c < nc; c++) {
        const b = c * ns;
        projDiag.push(Int32Array.from(active, (s) => slot(b + s, b + s)));
        projT.push(active.map((s) => Int32Array.from({ length: nb }, (_, j) => slot(b + s, tIndex(c, j)))));
        projO.push(active.map((s) => Int32Array.from(outside, (i) => slot(b + s, b + i))));
      }
    }
    /*
      Projected, each value of the compiled Jacobian, in turn: the rows it
      goes to, each with its weight -- U times the species' R for a total, 1
      for its own row -- and either the one slot on its own column, or, for a
      held column, a slot for each of the column's cell's totals and of what
      else that cell's relations read (cellCols), which the speciation's
      derivatives are spread over.
    */
    const pRow0 = new Int32Array(bp.nnz + 1);
    const pW = [];
    const pMass = [];
    const pSlot = [];
    if (projected) {
      const width = nb + outside.length;
      for (let col = 0; col < nBase; col++) {
        const colsTo = held[col] ? cellCols(Math.floor(col / ns)) : [col];
        for (let k = bp.colPtr[col]; k < bp.colPtr[col + 1]; k++) {
          const row = bp.rowIdx[k];
          pRow0[k] = pW.length;
          const c = Math.floor(row / ns);
          for (const r of rowsOf(row)) {
            pW.push(held[row] ? U[r - tIndex(c, 0)][pos[row - c * ns]] : 1);
            pMass.push(held[row] ? row : -1);
            for (const q of colsTo) pSlot.push(slot(r, q));
            if (!held[col]) for (let e = 1; e < width; e++) pSlot.push(-1);
          }
        }
      }
      pRow0[bp.nnz] = pW.length;
    }
    const pWidth = nb + outside.length;

    /* ---- concentrations, and back ---- */
    const C = new Float64Array(nBase);
    const f = new Float64Array(nBase);
    const Vb = new Float64Array(base.nnz);
    const concentrations = (y) => {
      for (let k = 0; k < nBase; k++) C[k] = held[k] ? (lin[k] ? y[k] : Math.exp(y[k])) : y[k];
      return C;
    };
    // Relation r in the cell at b, as a residual: sum of nu ln a - ln K, a
    // mineral adding nothing; C the concentrations, `water` the activity
    // evaluation of the cell when there is ACTIVITY.
    const relationAt = (b, r, y, water) => {
      const eq = eqs[r];
      let g = -eq.lnK;
      for (const [sp, nu] of eq.net) {
        if (isMin[sp]) continue;
        g += nu * (held[b + sp] ? y[b + sp] : Math.log(C[b + sp]));
        if (act) g += nu * lnG[sp];
      }
      if (act && eq.water) g += eq.water * water.lnAw;
      return g;
    };
    const totalOf = (cIn, c, j) => {
      const b = c * ns;
      let t = 0;
      for (let k = 0; k < na; k++) if (U[j][k]) t += U[j][k] * massOf[b + active[k]] * cIn[b + active[k]];
      return t;
    };

    // The projected state: y's concentrations with every held species put at
    // the speciation of its cell's totals, and those speciations' unknowns.
    const Cstar = projected ? new Float64Array(nBase) : null;
    const xs = projected ? Array.from({ length: nc }, () => null) : null;
    function projectAll(y) {
      concentrations(y);
      Cstar.set(C);
      let ok = true;
      for (let c = 0; c < nc; c++) {
        const x = project(c, y);
        xs[c] = x;
        if (!x) { ok = false; continue; }
        const b = c * ns;
        for (const s of active) Cstar[b + s] = Cs[s];
        // Kept a cell at a time: the next projection reuses Cs.
        sens[c] = null;
      }
      return ok;
    }
    // Each cell's speciation's derivatives, du/dT and du/dC of what else its
    // relations read, at the projection: na rows of nb, and of outside.length.
    const sens = projected ? Array.from({ length: nc }, () => null) : null;
    function sensitivities(c, y) {
      const b = c * ns;
      for (let s = 0; s < ns; s++) Cs[s] = Cstar[b + s];
      for (let k = 0; k < na; k++) wP[k] = massOf[b + active[k]];
      const { J, O } = cellJacobian(sys, Cs, 0, wP, present.subarray(c * ne, (c + 1) * ne), c,
        outside.length ? outside : null);
      const piv = luFactor(J, na);
      if (!piv) return null;
      const dT = Array.from({ length: na }, () => new Float64Array(nb));
      const dO = Array.from({ length: na }, () => new Float64Array(outside.length));
      for (let q = 0; q < nb; q++) {
        rhsP.fill(0);
        rhsP[ne + q] = 1;
        luSolve(J, piv, rhsP, na);
        for (let k = 0; k < na; k++) dT[k][q] = rhsP[k];
      }
      outside.forEach((si, i) => {
        for (let r = 0; r < na; r++) rhsP[r] = O[r][i] ? -O[r][i] : 0;
        luSolve(J, piv, rhsP, na);
        for (let k = 0; k < na; k++) dO[k][i] = rhsP[k];
      });
      return { dT, dO };
    }

    function rhs(t, y, out) {
      if (projected) return rhsProjected(t, y, out);
      concentrations(y);
      base.rhs(t, C, f);
      for (let k = 0; k < nBase; k++) out[k] = held[k] ? 0 : f[k];
      for (let c = 0; c < nc; c++) {
        const b = c * ns;
        for (let j = 0; j < nb; j++) {
          let rate = 0;
          for (let k = 0; k < na; k++) {
            if (!U[j][k]) continue;
            const at = b + active[k];
            rate += U[j][k] * massOf[at] * f[at];
          }
          out[tIndex(c, j)] = rate;
          // The total, as its species make it up, is the total.
          out[b + defAt[j]] = y[tIndex(c, j)] - totalOf(C, c, j);
        }
        const water = act ? activityAt(act, C, b, lnG, dG) : null;
        for (let r = 0; r < ne; r++) {
          // None of the mineral: its amount is zero, and the relation waits.
          const m = eqs[r].mineral;
          out[b + relRow[r]] = m >= 0 && !present[c * ne + r] ? y[b + m] : relationAt(b, r, y, water);
        }
      }
      return out;
    }

    /*
      Projected: the rates are the compiled model's at the projected state,
      so a Newton iterate however far its held species stray reads none of
      them; each held species' row is it less its projection.
    */
    function rhsProjected(t, y, out) {
      const ok = projectAll(y);
      base.rhs(t, Cstar, f);
      for (let k = 0; k < nBase; k++) out[k] = held[k] ? 0 : f[k];
      for (let c = 0; c < nc; c++) {
        const b = c * ns;
        for (let j = 0; j < nb; j++) {
          let rate = 0;
          for (let k = 0; k < na; k++) {
            if (!U[j][k]) continue;
            const at = b + active[k];
            rate += U[j][k] * massOf[at] * f[at];
          }
          out[tIndex(c, j)] = ok ? rate : NaN;
        }
        const x = xs[c];
        for (let k = 0; k < na; k++) {
          const s = b + active[k];
          out[s] = x ? y[s] - x[k] : NaN;
        }
      }
      return out;
    }

    // Its Jacobian: the totals' rows through the speciation's derivatives, and
    // each held species' row 1 on itself and minus those derivatives.
    function jacProjected(t, y, V) {
      projectAll(y);
      for (let c = 0; c < nc; c++) sens[c] = xs[c] ? sensitivities(c, y) : null;
      base.jac(t, Cstar, Vb);
      V.fill(0);
      for (let col = 0; col < nBase; col++) {
        const heldCol = held[col];
        const cc = Math.floor(col / ns);
        const kq = heldCol ? pos[col - cc * ns] : -1;
        const sc = heldCol ? sens[cc] : null;
        if (heldCol && !sc) continue;
        const fac = heldCol && !lin[col] ? Cstar[col] : 1;
        for (let k = bp.colPtr[col]; k < bp.colPtr[col + 1]; k++) {
          const v = Vb[k];
          if (v === 0) continue;
          for (let t2 = pRow0[k]; t2 < pRow0[k + 1]; t2++) {
            const w = pW[t2] * (pMass[t2] >= 0 ? massOf[pMass[t2]] : 1) * v;
            const at = t2 * pWidth;
            if (!heldCol) { V[pSlot[at]] += w; continue; }
            const dTk = sc.dT[kq];
            for (let q = 0; q < nb; q++) if (dTk[q]) V[pSlot[at + q]] += w * fac * dTk[q];
            const dOk = sc.dO[kq];
            for (let i = 0; i < outside.length; i++) if (dOk[i]) V[pSlot[at + nb + i]] += w * fac * dOk[i];
          }
        }
      }
      for (let c = 0; c < nc; c++) {
        for (let k = 0; k < na; k++) V[projDiag[c][k]] += 1;
        const sc = sens[c];
        if (!sc) continue;
        for (let k = 0; k < na; k++) {
          for (let q = 0; q < nb; q++) if (sc.dT[k][q]) V[projT[c][k][q]] -= sc.dT[k][q];
          for (let i = 0; i < outside.length; i++) if (sc.dO[k][i]) V[projO[c][k][i]] -= sc.dO[k][i];
        }
      }
      return V;
    }

    function jac(t, y, V) {
      if (projected) return jacProjected(t, y, V);
      concentrations(y);
      base.jac(t, C, Vb);
      V.fill(0);
      for (let col = 0; col < nBase; col++) {
        // d/du of anything taken at C = e^u is C times d/dC; an amount is itself.
        const sc = held[col] && !lin[col] ? C[col] : 1;
        for (let k = bp.colPtr[col]; k < bp.colPtr[col + 1]; k++) {
          const v = Vb[k];
          if (v === 0) continue;
          if (aSlot[k] >= 0) V[aSlot[k]] += v * sc;
          for (let q = tStart[k]; q < tStart[k + 1]; q++) V[tAt[q]] += tUc[q] * massOf[tRow[q]] * v * sc;
        }
      }
      for (let c = 0; c < nc; c++) {
        const b = c * ns;
        for (let j = 0; j < nb; j++) {
          V[defT[c][j]] += 1;
          for (let k = 0; k < na; k++) {
            const at = defC[c][j][k];
            if (at < 0) continue;
            const s = b + active[k];
            V[at] -= U[j][k] * massOf[s] * (lin[s] ? 1 : C[s]);
          }
        }
        const water = act ? activityAt(act, C, b, lnG, dG) : null;
        for (let r = 0; r < ne; r++) {
          if (eqs[r].mineral >= 0 && !present[c * ne + r]) {
            V[relC[c][r][minAt[r]]] += 1;
            continue;
          }
          eqs[r].net.forEach(([s, nu], m) => {
            if (isMin[s]) return;
            V[relC[c][r][m]] += held[b + s] ? nu : nu / C[b + s];
          });
          if (!act) continue;
          // The coefficients through the ionic strength, and the water: in
          // a held species' column times C, as everything in ln C is.
          let G = 0;
          for (const [s, nu] of eqs[r].net) G += nu * dG[s];
          const w = eqs[r].water || 0;
          actCols[r].forEach((k, q) => {
            let d = G * 0.5 * act.z[k] * act.z[k];
            if (w && act.solute[k]) d += w * water.dAw;
            if (d) V[relA[c][r][q]] += held[b + k] ? d * C[b + k] : d;
          });
        }
      }
      return V;
    }

    /**
     * Puts every cell's held species on its relations and its totals, the
     * totals and everything else held where they are: the speciation of each
     * cell's totals, one small system a cell (speciateCell), with the
     * minerals present as the run has them -- or, opts.fromState, as the
     * state itself has them, found again: which is how a stored point is
     * read back, whatever the run went on to.
     */
    const sys = cellSystem(eqs, active, U.map((row) => Float64Array.from(row)), isMin, act, ns, site);
    const wCell = new Float64Array(na);
    const totalsCell = new Float64Array(nb);
    // The projection (see projected): cell c's held species as the speciation
    // of the totals y carries there, started from where y stands -- C must
    // hold y's concentrations -- into Cs, the cell's concentrations. Null
    // where it does not settle.
    const Cs = new Float64Array(ns);
    const wP = new Float64Array(na);
    const totalsP = new Float64Array(nb);
    const rhsP = new Float64Array(na);
    // Each cell's last settled speciation, where a projection starts again
    // when the Newton iterate it is handed is too wild to start from: oxygen
    // at e^50 spoils even the ionic strength.
    const settled = projected ? Array.from({ length: nc }, () => null) : null;
    function project(c, y) {
      const b = c * ns;
      for (let j = 0; j < nb; j++) totalsP[j] = y[tIndex(c, j)];
      for (let k = 0; k < na; k++) wP[k] = massOf[b + active[k]];
      const pres = present.subarray(c * ne, (c + 1) * ne);
      const opts = { tol: 1e-12, roundOff: true, cell: c, maxIter: 200, asStarted: true };
      for (let s = 0; s < ns; s++) Cs[s] = C[b + s];
      let res = speciateCell(sys, Cs, 0, totalsP, wP, pres, opts);
      if (!res.converged && settled[c]) {
        for (let s = 0; s < ns; s++) Cs[s] = C[b + s];
        for (let k = 0; k < na; k++) Cs[active[k]] = settled[c][k];
        res = speciateCell(sys, Cs, 0, totalsP, wP, pres, opts);
      }
      if (!res.converged) return null;
      if (!settled[c]) settled[c] = new Float64Array(na);
      for (let k = 0; k < na; k++) settled[c][k] = Cs[active[k]];
      return res.x;
    }
    function consistentInitial(t, y, opts = {}) {
      // Not below 1e-13: a relation is ln K of 30 or 50 in size, and rounding
      // there is a few times 1e-15 whatever is asked.
      const tol = Math.max(Math.min(1e-10, (opts.rtol || 1e-6) * 1e-4), 1e-13);
      let worstRes = 0;
      let moved = 0;
      let iterations = 0;
      let why = '';
      concentrations(y);
      // Every cell, whatever one of them does: they are separate systems, and
      // one that does not settle says so without leaving the rest unsettled.
      for (let c = 0; c < nc; c++) {
        const b = c * ns;
        for (let j = 0; j < nb; j++) totalsCell[j] = y[tIndex(c, j)];
        for (let k = 0; k < na; k++) wCell[k] = massOf[b + active[k]];
        const pres = opts.fromState
          ? Uint8Array.from(eqs, (eq) => (eq.mineral < 0 || y[b + eq.mineral] > 0 ? 1 : 0))
          : present.subarray(c * ne, (c + 1) * ne);
        const res = speciateCell(sys, C, b, totalsCell, wCell, pres,
          { tol, roundOff: true, activeSet: !!opts.fromState, cell: c });
        iterations = Math.max(iterations, res.iterations);
        worstRes = Math.max(worstRes, res.residual);
        if (!res.converged && !why) {
          why = res.why === 'singular' ? `the relations do not determine the held species in cell ${c}`
            : res.why ? `${res.why} in cell ${c}`
              : `the held equilibria did not settle in cell ${c} (residual ${res.residual.toExponential(2)})`;
        }
        for (let k = 0; k < na; k++) {
          const st = b + active[k];
          moved = Math.max(moved, Math.abs(res.x[k] - y[st]));
          y[st] = res.x[k];
        }
      }
      return { solved: !why, iterations, residual: worstRes, moved, why };
    }

    // What the page shows of a state: its held species put exactly on the
    // relations and the totals the state carries, then out of the logarithm.
    // The solver leaves a step once its Newton correction is under the
    // tolerance, which on the totals' rows is a part in 1e9 at rtol 1e-8; the
    // totals themselves are integrated, and what is conserved is conserved to
    // rounding there. So every point shown is the speciation of its totals.
    const toConcentrations = (y) => {
      const z = Float64Array.from(y);
      consistentInitial(0, z, { rtol: 1e-12, fromState: true });
      const out = new Float64Array(nBase);
      for (let k = 0; k < nBase; k++) out[k] = held[k] && !lin[k] ? Math.exp(z[k]) : z[k];
      return out;
    };
    const fromConcentrations = (cIn) => {
      const y = new Float64Array(n);
      for (let k = 0; k < nBase; k++) y[k] = held[k] && !lin[k] ? Math.log(Math.max(cIn[k], 1e-300)) : cIn[k];
      for (let c = 0; c < nc; c++) for (let j = 0; j < nb; j++) y[tIndex(c, j)] = totalOf(cIn, c, j);
      return y;
    };

    const mass = new Float64Array(n).fill(1);
    const nonNegativeMask = new Uint8Array(n);
    // The logarithms, which the solver weighs as they stand: see atolFor.
    const absoluteMask = new Uint8Array(n);
    for (let k = 0; k < nBase; k++) {
      if (held[k]) { mass[k] = 0; absoluteMask[k] = lin[k] ? 0 : 1; } else nonNegativeMask[k] = 1;
    }
    const names = base.species.concat(Array.from({ length: nc * nb }, (_, q) => {
      const c = Math.floor(q / nb);
      return `total ${q - c * nb + 1}${nc === 1 ? '' : `@${c}`}`;
    }));
    const initial = fromConcentrations(start);

    /*
      THE MINERALS' EVENTS, one for each mineral in each cell. While there is
      some of it, the event is minus its amount, which reaches zero from below
      when the last of it dissolves; while there is none, it is the
      saturation index, which reaches zero from below when the water becomes
      supersaturated. Either way it is crossed upwards, the run stops there,
      the mineral is switched, and the run starts again from the state put
      back on its constraints (runModel in facsimile-solver.js).
    */
    const where = (c) => (nc > 1 ? ` in cell ${c}` : '');
    const events = Array.from({ length: nc * nmin }, (_, q) => ({
      expr: `${base.speciesNames[eqs[mins[q % nmin]].mineral]}${where(Math.floor(q / nmin))}`,
      shown: '', assigns: ['present'], once: false, stop: false,
    }));
    function eventValues(t, y, out) {
      concentrations(y);
      for (let c = 0; c < nc; c++) {
        const b = c * ns;
        let water = null;
        let ready = !act;
        for (let q = 0; q < nmin; q++) {
          const r = mins[q];
          const m = eqs[r].mineral;
          if (present[c * ne + r]) { out[c * nmin + q] = -y[b + m]; continue; }
          if (!ready) { water = activityAt(act, C, b, lnG, dG); ready = true; }
          out[c * nmin + q] = (eqs[r].mineralNu < 0 ? 1 : -1) * relationAt(b, r, y, water);
        }
      }
      return out;
    }
    function applyEvent(which) {
      const c = Math.floor(which / nmin);
      const r = mins[which % nmin];
      const at = c * ne + r;
      present[at] = present[at] ? 0 : 1;
      const name = base.speciesNames[eqs[r].mineral];
      events[which].shown = present[at] ? `${name} precipitates${where(c)}` : `${name} has dissolved away${where(c)}`;
      return [name];
    }
    // Each run starts from the state: some of a mineral is there or none is.
    const resetModes = (y) => {
      for (let c = 0; c < nc; c++) {
        for (const r of mins) present[c * ne + r] = y[c * ns + eqs[r].mineral] > 0 ? 1 : 0;
      }
    };
    // The scale an amount is measured against: the largest total its cell starts with.
    const amountScale = new Float64Array(nc);
    for (let c = 0; c < nc; c++) for (let j = 0; j < nb; j++) amountScale[c] = Math.max(amountScale[c], Math.abs(initial[tIndex(c, j)]));

    /*
      Projected, a held species is what its cell's totals make it, and its
      error is theirs: the totals are held to the tolerance, and the species
      not at all (the NDF's weightScale). Held to rtol of itself, a species
      that is 1e-150 of everything it counts in -- sulfide's complexes where
      oxygen has arrived, whose logarithms follow the electron's eight times
      over and more -- stalled the Newton iteration where a redox front
      passes, at every step size.
    */
    function weightScale(y, ynew, inv) {
      for (let c = 0; c < nc; c++) for (let k = 0; k < na; k++) inv[c * ns + active[k]] = 0;
    }

    return {
      ...base,
      nspecies: n,
      nnz,
      pattern: { n, nnz, colPtr, rowIdx },
      species: names,
      initialState: () => { resetModes(initial); return Float64Array.from(initial); },
      ...(nmin ? {
        nevents: nc * nmin,
        eventDirections: new Int8Array(nc * nmin).fill(1),
        events,
        eventValues,
        applyEvent,
      } : {}),
      rhs,
      jac,
      jacobianConstant: false,
      mass,
      nalgebraic: nc * na,
      algebraicNames: names.filter((_, k) => k < nBase && held[k]),
      consistentInitial,
      nonNegativeMask,
      absoluteMask,
      ...(projected ? { weightScale } : {}),
      // A species held is ln C, and an error of rtol in it is an error of rtol
      // in C, relative, which is what rtol asks of every species: so its atol
      // is rtol and the solver weighs it against that alone (absoluteMask),
      // whatever rtol and atol say of C and however large |ln C| is.
      // A mineral's amount is held to rtol of the totals of its cell, which is
      // what it is made of, rather than of itself: it is on its way to zero.
      atolFor(atol, rtol) {
        const out = new Float64Array(n);
        const r = rtol > 0 ? rtol : 1e-6;
        for (let k = 0; k < n; k++) {
          const given = typeof atol === 'number' ? atol : (atol && k < atol.length ? atol[k] : 1e-20);
          if (k < nBase && held[k]) out[k] = lin[k] ? Math.max(given, r * amountScale[Math.floor(k / ns)]) : r;
          else out[k] = given;
        }
        return out;
      },
      stateWidth: nBase,
      toConcentrations,
      fromConcentrations,
      heldEquilibria: { relations: ne, totals: nb, species: na, minerals: nmin },
      density: nnz / (n * n),
    };
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
    const fp2 = new Float64Array(n);
    const fm2 = new Float64Array(n);
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
    // A held model's logarithms (absoluteMask) are no concentrations: they
    // set no floor for the others -- ln C of -30 would step a species at 1e-4
    // by 2 % of itself -- and are stepped by an absolute amount, a relative
    // change of that size in C.
    const logs = model.absoluteMask && model.absoluteMask.length === n ? model.absoluteMask : null;
    let typ = 0;
    for (let i = 0; i < n; i++) if (!(logs && logs[i])) typ = Math.max(typ, Math.abs(y[i]));
    if (!(typ > 0)) typ = 1;
    const cbrtEps = Math.cbrt(2 ** -52);

    for (let c = 0; c < n; c++) {
      const h = logs && logs[c] ? cbrtEps : cbrtEps * Math.max(Math.abs(y[c]), typ * 1e-2);
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
      let halved = false;
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
        /*
          And an entry whose term is under 1e-7 of its row's terms: it moves
          nothing the Newton iteration does, and it is where a difference is
          least to be trusted -- the step moves this state by 6e-6 of the
          largest, and a slope that varies on a finer scale than that, as a
          limited advection does in a stretch flat to rounding, cannot be
          followed across it. Counted apart, as those below rounding are.
        */
        if (Math.max(Math.abs(analytic), Math.abs(numeric)) * Math.max(Math.abs(y[c]), h) < 1e-7 * rowScale[r]) {
          unresolvable++;
          continue;
        }
        checked++;
        const tol = Math.max(rtol * Math.max(Math.abs(analytic), Math.abs(numeric)), floor);
        if (Math.abs(analytic - numeric) <= tol) continue;
        /*
          A disagreement is looked at again before it is reported: the
          difference taken at half the step as well, and the two extrapolated,
          (4 D(h/2) - D(h))/3, which takes away the h^2 that a central
          difference carries. Where the entry's function varies on a scale
          not far above the step -- a limited advection's slope where the
          gradients are a few times what the step moves them by -- that h^2 is
          the disagreement; a Jacobian that is wrong stays wrong.
        */
        if (step === 2 * h) {
          if (!halved) {
            yp[c] = y[c] + h / 2;
            model.rhs(t, yp, fp2);
            yp[c] = y[c] - h / 2;
            model.rhs(t, yp, fm2);
            yp[c] = y[c];
            halved = true;
          }
          const half = (fp2[r] - fm2[r]) / h;
          const extrapolated = (4 * half - numeric) / 3;
          const tol2 = Math.max(rtol * Math.max(Math.abs(analytic), Math.abs(extrapolated)), floor);
          if (Math.abs(analytic - extrapolated) <= tol2) continue;
        }
        discrepancies.push({ row: r, col: c, analytic, numeric });
      }
    }
    return { checked, unresolvable, discrepancies, outsidePattern: outside };
  }

  return { compile, verifyJacobian, speciate, conservationBasis, RtmError, parseReaction,
    chargeOf, debyeHuckelAB, activityModel, activityAt,
    readSections, derivative,
    // The vocabulary, for the editor's syntax colouring: what is coloured as
    // meaning something is exactly what means something here.
    SECTIONS, SETTINGS };
}));
