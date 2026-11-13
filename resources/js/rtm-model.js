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

  const SECTIONS = ['SETTINGS', 'SPECIES', 'REACTIONS', 'INITIAL', 'PARAMETERS', 'EQUILIBRIUM', 'PHASES', 'SIT',
    'GAS_PAIRS', 'SOLID_SOLUTIONS', 'PITZER', 'LLNL', 'VOLUMES', 'CONDUCTANCE', 'OUTPUT', 'DATA'];

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
    /*
      What a species diffuses down: its concentration, or with activity its
      activity, as PHREEQC's multicomponent diffusion has it -- across each
      face the difference in concentration times 1 + d ln gamma/d ln C, taken
      between the two cells and held between 0.2 and 2.25 (find_J; PHREEQC
      drops it beyond them). Needs ACTIVITY. See npFaces.
    */
    DIFFUSION_GRADIENT: { def: 'concentration', kind: 'word', of: ['concentration', 'activity'] },
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
      `reservoir` is a dirichlet face whose water reacts: a well-mixed cell
      outside the column, which the column does not drain and the chemistry
      does change (see THE RESERVOIRS).
    */
    LEFT: { def: 'dirichlet', kind: 'word',
      of: ['dirichlet', 'neumann', 'robin', 'cauchy', 'free', 'outflow', 'semi-infinite', 'reservoir'] },
    RIGHT: { def: 'neumann', kind: 'word',
      of: ['dirichlet', 'neumann', 'robin', 'cauchy', 'free', 'outflow', 'semi-infinite', 'reservoir'] },
    // How many cells past a semi-infinite right-hand end; worked out unless given.
    EXTRA_CELLS: { def: 0, kind: 'int' },
    // How long to run. Like MAX_STEP and TRAVEL_TIME, a time that may carry a unit of its own: TEND = 1890 days.
    TEND: { def: 1, kind: 'time' },
    /*
      The longest step the solver takes, in the model's time unit, where the
      panel's Maximum step is 0: a chart draws the steps a run takes, and a
      run whose answer goes straight between the turns of its chemistry -- a
      reactant added at a steady rate, each oxidant used up in its turn -- is
      otherwise drawn from steps a tenth of the run long, across its turns.
      0, the default, leaves it to the solver.
    */
    MAX_STEP: { def: 0, kind: 'time' },
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
      The unit the concentrations are in, for the page to say: mol/L (also
      mol/dm3, molar) or mol/kgw (also mol/kg, molal). It converts nothing,
      as TIME_UNIT converts nothing: it names what the text's numbers are.
      Under ACTIVITY the concentrations are molalities, mol/kgw, and mol/L is
      refused. Left out, they are as the model has them.
    */
    CONC_UNIT: { def: '', kind: 'word', of: ['mol/l', 'mol/dm3', 'molar', 'mol/kgw', 'mol/kg', 'molal'],
      said: 'mol/L (or mol/dm3, molar) or mol/kgw (or mol/kg, molal)' },
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
      for any other ion, PHREEQC's rule; or sit, the specific ion interaction
      theory, each species' coefficient reading the species it is paired with
      in <SIT> as well. none, the default, holds them between concentrations.
      See activityModel.

      TEMPERATURE, in degrees C: a number, or an expression of the parameters
      and the clock -- a parameter of <PARAMETERS> for a temperature that
      differs from cell to cell, a table read at the clock, name(t), for one
      that goes with time, or both. Each cell's sets its relations' log K
      (logKAt), the Debye-Hueckel A and B, a gas's R T and a double layer's
      F/RT and dielectric constant, and a rate law reads it as TK, kelvin,
      and TC. See the temperature in compile.
    */
    ACTIVITY: { def: 'none', kind: 'word', of: ['none', 'davies', 'debye-huckel', 'debye-hückel', 'sit', 'pitzer', 'llnl'] },
    TEMPERATURE: { def: 25, kind: 'temperature' },
    /*
      A gas phase, PHREEQC's GAS_PHASE: the species given `gas`, each with its
      partial pressure in atm for its activity. GAS_VOLUME holds the gas in a
      fixed volume, litres to each kilogram of water, and a gas's pressure is
      n R T/V; GAS_PRESSURE holds the gas at a fixed total pressure, atm, as a
      bubble that is there only while the gases dissolved in the water would
      add up to that pressure, a gas's pressure its share of the total. One or
      the other. See gasSetup.
    */
    GAS_VOLUME: { def: 0, kind: 'number' },
    GAS_PRESSURE: { def: 0, kind: 'number' },
    /*
      PRESSURE: the water's pressure in atm, 1 unless given, which the
      Debye-Hueckel A and B and a double layer's dielectric constant are
      worked out at (a logK is taken as written). A bubble at a fixed
      pressure puts the water at its own, as PHREEQC does.
    */
    PRESSURE: { def: 1, kind: 'number' },
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
    TRAVEL_TIME: { def: 0, kind: 'time' },
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
      const header = /^<\s*([A-Za-z_]+)((?:\s+[^\s<>]+)*)\s*>$/.exec(line);
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

  /*
    A TIME THAT MAY CARRY A UNIT OF ITS OWN -- 1890 days, 5 a, 2.5h -- any
    word TIME_UNIT takes, after the number, which may be arithmetic. The unit
    converts this one number and nothing else: the rate constants are in the
    model's unit whatever is written here. { text, seconds }: the number's
    text, and the unit's length in seconds, null where none is written.
  */
  function splitTime(raw, what, line) {
    const s = String(raw).trim();
    const u = /^(.*?[0-9.)\s])\s*([A-Za-z]+)\s*$/.exec(s);
    if (!u) return { text: s, seconds: null };
    const unit = TIME_UNITS[u[2].toLowerCase()];
    if (!unit) {
      throw new RtmError(`${what} = "${s}": "${u[2]}" is not a unit of time. After the number may come s, min, h, d or a, `
        + 'or second(s), minute(s), hour(s), day(s) or year(s).', line);
    }
    return { text: u[1].trim(), seconds: unit.seconds };
  }

  /** A time typed with or without a unit, in the unit a model counts in -- its TIME_UNIT -- as the page's Simulated time is. */
  function readTime(raw, own = 'second', what = 'The time') {
    const { text, seconds } = splitTime(raw, what);
    const v = constValue(text, undefined, what);
    const ownSeconds = (TIME_UNITS[String(own).toLowerCase()] || TIME_UNITS.second).seconds;
    return seconds === null ? v : (v * seconds) / ownSeconds;
  }

  /** `NAME = value` lines, read against the table above. */
  function readSettings(lines) {
    const out = {};
    for (const [name, spec] of Object.entries(SETTINGS)) out[name] = spec.def;
    // Which settings the text gave, as against the defaults: FACES decides
    // CELLS and LENGTH, and only a CELLS the text wrote can disagree with it.
    const given = new Set();
    Object.defineProperty(out, 'given', { value: given, enumerable: false });
    // Times written with a unit of their own, put into the model's once TIME_UNIT, which may come after them, is known.
    const inUnits = [];
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
          throw new RtmError(`${name} must be ${spec.said || `one of ${spec.of.join(', ')}`}, not "${raw}".`, line);
        }
        out[name] = { cauchy: 'robin', outflow: 'free', 'debye-hückel': 'debye-huckel' }[word] || word;
        if (name === 'TIME_UNIT') out[name] = TIME_UNITS[out[name]].name;
        if (name === 'CONC_UNIT') out[name] = /kg|molal/.test(word) ? 'mol/kgw' : 'mol/L';
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
      } else if (spec.kind === 'temperature') {
        // A number, or the text of an expression the cells and the clock work out (compile).
        let v = null;
        try { v = constValue(raw, line, name); } catch (e) { v = null; }
        out[name] = v !== null ? v : raw;
        Object.defineProperty(out, `${name}_line`, { value: line, enumerable: false });
      } else if (spec.kind === 'time') {
        const { text: num, seconds } = splitTime(raw, name, line);
        out[name] = constValue(num, line, name);
        if (seconds !== null) inUnits.push([name, seconds]);
      } else {
        const v = constValue(raw, line, name);
        out[name] = spec.kind === 'int' ? Math.round(v) : v;
      }
    }
    const ownSeconds = (TIME_UNITS[String(out.TIME_UNIT)] || TIME_UNITS.second).seconds;
    for (const [name, seconds] of inUnits) out[name] = (out[name] * seconds) / ownSeconds;
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
        mass: null, Dm: 0, Rm: null, Kd: null, Kdf: null, z: null, dha: null, dhb: null, pe: null, sites: null,
        area: null, grams: null, per: null, dz: null, c0: null, c1: null, tc: null, pc: null, omega: null,
        mineral: false, immobile: false, exchange: false, exchanger: false, electron: false, surface: false,
        potential: false, gas: false, drummond: false, line };
      let first = true;
      for (const part of parts) {
        const kv = /^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$/.exec(part);
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
          // A surface's sites, or its potential's area, to each mole of a mineral (surfaceSetup, potentialSetup).
          if (key === 'per') { entry.per = kv[2].trim(); continue; }
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
            // A whole number, but on a surface any: CD-MUSIC's sites carry halves (Goe_uniOH-0.5).
            if (!Number.isFinite(value)) throw new RtmError(`z = ${value} for ${name}: a charge is a number.`, line);
            entry.z = value;
          } else if (key === 'a') {
            if (!(value >= 0)) throw new RtmError(`a = ${value} for ${name}: an ion size is zero or more.`, line);
            entry.dha = value;
          } else if (key === 'b') entry.dhb = value;
          // The electron's: the pe its activity starts at, 10^-pe.
          else if (key === 'pe') entry.pe = value;
          // A surface's: the sites of its type in every cell, loaded from the water.
          else if (key === 'sites') {
            if (!(value > 0)) throw new RtmError(`sites = ${value} for ${name}: a number of sites is above zero.`, line);
            entry.sites = value;
          }
          // CD-MUSIC: the charge a species on a surface puts on each of its three planes, against its bare site.
          else if (key === 'dz0' || key === 'dz1' || key === 'dz2') {
            if (!entry.dz) entry.dz = [0, 0, 0];
            entry.dz[Number(key[2])] = value;
          }
          // CD-MUSIC: the capacitances between planes 0 and 1, and 1 and 2, F/m2, on a surface's first potential.
          else if (key === 'c0' || key === 'c1') {
            if (!(value > 0)) throw new RtmError(`${kv[1]} = ${value} for ${name}: a capacitance is above zero.`, line);
            entry[key] = value;
          }
          // A surface's potential's: the specific area of the solid, m2/g, and
          // the grams of it to each kilogram of water.
          else if (key === 'area' || key === 'grams') {
            if (!(value > 0)) throw new RtmError(`${kv[1]} = ${value} for ${name}: it is above zero.`, line);
            entry[key] = value;
          }
          // A real gas's: its critical temperature (K) and pressure (atm), and its acentric factor.
          else if (key === 'tc' || key === 'pc') {
            if (!(value > 0)) throw new RtmError(`${kv[1]} = ${value} for ${name}: a critical ${key === 'tc' ? 'temperature' : 'pressure'} is above zero.`, line);
            entry[key] = value;
          } else if (key === 'omega') entry.omega = value;
          else throw new RtmError(`"${kv[1]}" is not a species property. Use D, left, right, `
            + 'mass or R; with a rock matrix Dm (or De), Rm, Kd or Kdf; for ACTIVITY z, a and b; for '
            + 'the electron pe; for a surface sites, per and, under CD-MUSIC, dz0, dz1 and dz2; for its potential area, '
            + 'grams, per, c0 and c1; and for a real gas Tc, Pc and omega.', line);
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
        // A species on a surface, Hfo_wOH: its activity is its fraction of the sites.
        if (/^surface$/i.test(part)) { entry.surface = true; entry.immobile = true; continue; }
        // A surface's potential, Hfo_psi: no amount, its activity exp(-F psi/RT) solved for.
        if (/^potential$/i.test(part)) { entry.potential = true; entry.immobile = true; continue; }
        // A gas, CO2(g): its amount in the gas phase, its activity its partial pressure.
        if (/^gas$/i.test(part)) { entry.gas = true; entry.immobile = true; continue; }
        // Under ACTIVITY = llnl, Drummond's coefficient of CO2: PHREEQC's -co2_llnl_gamma.
        if (/^drummond$/i.test(part)) { entry.drummond = true; continue; }
        /*
          A mineral held at saturation that only dissolves -- it never grows
          past what its cell starts with -- or only precipitates -- it never
          goes below that -- or whose saturation is held whatever its amount
          comes to, below none too: PHREEQC's dissolve_only, precipitate_only
          and -force_equality.
        */
        if (/^(dissolve_only|precipitate_only)$/i.test(part)) {
          if (entry.only !== undefined) throw new RtmError(`${name} is given dissolve_only and precipitate_only: one of them.`, line);
          entry.only = part.toLowerCase().startsWith('d') ? 'dissolve' : 'precipitate';
          continue;
        }
        if (/^force_equality$/i.test(part)) { entry.forced = true; continue; }
        if (first) {
          entry.initial = constValue(part, line, `the concentration of ${name}`);
          first = false;
          continue;
        }
        throw new RtmError(`"${part}" is not understood on a species line.`, line);
      }
      const kinds = ['mineral', 'exchange', 'exchanger', 'electron', 'surface', 'potential', 'gas'].filter((k) => entry[k]);
      if (kinds.length > 1) throw new RtmError(`${name} is given as ${kinds.join(' and ')}: it is one of them.`, line);
      if ((entry.only !== undefined || entry.forced) && !entry.mineral) {
        throw new RtmError(`${name} is given ${entry.forced ? 'force_equality' : `${entry.only}_only`}, which is a mineral's held `
          + 'at saturation: Calcite 0.01 mineral dissolve_only.', line);
      }
      if (entry.pe !== null && !entry.electron) {
        throw new RtmError(`pe = ${entry.pe} for ${name}: pe is the electron's, e- electron pe=4.`, line);
      }
      if (entry.sites !== null && entry.exchange && entry.per === null) {
        throw new RtmError(`sites = ${entry.sites} for ${name}, which is on an exchanger: there sites go with per=, the sites `
          + 'that go with a mineral in that species\' form, CaX2 exchange sites=0.33 per=Montmorillonite. An exchanger\'s '
          + 'own capacity is on its line, X- exchanger 0.1.', line);
      }
      if (entry.sites !== null && !entry.surface && !entry.exchange) {
        throw new RtmError(`sites = ${entry.sites} for ${name}: sites are a surface's, Hfo_wOH surface sites=2e-4, or `
          + 'go with a mineral on an exchanger, CaX2 exchange sites=0.33 per=Montmorillonite.', line);
      }
      if ((entry.tc !== null || entry.pc !== null || entry.omega !== null) && !entry.gas) {
        throw new RtmError(`${name} is given a critical temperature, pressure or acentric factor, which are a real gas's: `
          + 'CO2(g) gas Tc=304.2 Pc=72.86 omega=0.225.', line);
      }
      if (entry.gas && (entry.tc === null) !== (entry.pc === null)) {
        throw new RtmError(`${name} is given ${entry.tc === null ? 'Pc without Tc' : 'Tc without Pc'}: a real gas takes both, `
          + 'its critical temperature in K and pressure in atm.', line);
      }
      if (entry.per !== null) {
        if (!((entry.surface || entry.exchange) && entry.sites !== null) && !(entry.potential && entry.area !== null)) {
          throw new RtmError(`per=${entry.per} for ${name}: per names the mineral a surface's sites, its potential's `
            + 'area, or an exchanger\'s sites, go with, a mole of it at a time: Hfo_wOH surface sites=0.2 '
            + 'per=Ferrihydrite, Hfo_psi potential area=5.34e4 per=Ferrihydrite, CaX2 exchange sites=0.33 '
            + 'per=Montmorillonite.', line);
        }
        if (entry.grams !== null) {
          throw new RtmError(`${name} is given grams and per=${entry.per}: its area is per mole of ${entry.per}, which the `
            + 'cell has, and takes no grams.', line);
        }
      }
      if (entry.z !== null && !Number.isInteger(entry.z) && !entry.surface) {
        throw new RtmError(`z = ${entry.z} for ${name}: a charge is a whole number, but on a surface.`, line);
      }
      if (entry.dz && !entry.surface) {
        throw new RtmError(`dz0, dz1 and dz2 are given to ${name}: they are a species on a surface's, the charge it puts on `
          + 'each plane of a CD-MUSIC surface.', line);
      }
      if ((entry.c0 !== null || entry.c1 !== null) && !entry.potential) {
        throw new RtmError(`c0 and c1 are given to ${name}: they are a CD-MUSIC surface's capacitances, on its potential `
          + 'Hfo_psi.', line);
      }
      if ((entry.area !== null || entry.grams !== null) && !entry.potential) {
        throw new RtmError(`${entry.area !== null ? 'area' : 'grams'} is given to ${name}: area and grams are a surface's `
          + 'potential\'s, Hfo_psi potential area=600 grams=0.09.', line);
      }
      if (entry.sites !== null && entry.initial !== 0 && entry.per === null) {
        throw new RtmError(`${name} is given both an amount and the sites of its surface: the sites are loaded from the `
          + 'water, which puts every species on the surface where it has to be. Give one.', line);
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
      } else if (entry.potential) {
        /*
          A surface's potential is no amount and never moves either: what it
          is given is its activity, exp(-F psi/RT), where the start's
          speciation begins, 1 -- no potential -- if nothing is given.
        */
        const moves = [['D', entry.D > 0], ['Dm', entry.Dm > 0], ['R', entry.mass !== null], ['Rm', entry.Rm !== null],
          ['Kd', entry.Kd !== null], ['Kdf', entry.Kdf !== null], ['left', entry.left !== null],
          ['right', entry.right !== null], ['fixed', entry.fixed]].filter(([, given]) => given).map(([k]) => k);
        if (moves.length) {
          throw new RtmError(`${name} is a surface's potential, which is no amount, never moves and is solved for: it `
            + `takes no ${moves.join(', ')}.`, line);
        }
        if (entry.z !== null || entry.dha !== null || entry.dhb !== null) {
          throw new RtmError(`${name} is a surface's potential, whose activity is solved for and which carries no charge `
            + 'into the ionic strength: it takes no z, a or b.', line);
        }
        // A CD-MUSIC surface's planes 1 and 2, Hfo_psib and Hfo_psid: what the surface is given is on its first, Hfo_psi.
        if (/_psi[bd]$/.test(name)) {
          if (entry.area !== null || entry.grams !== null || entry.per !== null || entry.c0 !== null || entry.c1 !== null) {
            throw new RtmError(`${name} is plane ${name.endsWith('b') ? 1 : 2} of a CD-MUSIC surface: its area, grams and `
              + `capacitances are given on its first potential, ${name.slice(0, -1)}.`, line);
          }
        } else if (entry.area === null || (entry.grams === null && entry.per === null)) {
          throw new RtmError(`${name} is a surface's potential and needs the surface's area, in m2/g, and grams of the `
            + `solid to each kilogram of water: ${name} potential area=600 grams=0.09.`, line);
        }
        if (!(entry.initial >= 0)) throw new RtmError(`${name} is a surface's potential, and its activity is above zero.`, line);
        if (entry.initial === 0) entry.initial = 1;
      } else if (kinds.length) {
        const kind = kinds[0];
        const what = { mineral: 'a mineral', exchange: 'on an exchanger', exchanger: 'an exchanger',
          surface: 'on a surface', gas: 'a gas' }[kind];
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
        if (kind !== 'mineral' && kind !== 'surface' && kind !== 'gas' && entry.z !== null) {
          throw new RtmError(`${name} is ${what}: ${kind === 'exchanger' ? 'its sites are counted, not charged'
            : 'it carries no charge into the ionic strength, and its coefficient is its ion\'s, from its relation'}, so `
            + 'it takes no z.', line);
        }
        if (kind === 'exchanger' && (entry.dha !== null || entry.dhb !== null)) {
          throw new RtmError(`${name} is an exchanger, whose activity is solved for: it takes no a or b.`, line);
        }
        if (kind === 'surface' && (entry.dha !== null || entry.dhb !== null)) {
          throw new RtmError(`${name} is on a surface, whose activity is its fraction of the sites: it takes no a or b.`,
            line);
        }
        if (kind === 'gas' && (entry.z !== null || entry.dha !== null || entry.dhb !== null)) {
          throw new RtmError(`${name} is a gas, whose activity is its partial pressure: it takes no z, a or b.`, line);
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
   *   Red     left   1e-3  fixed    the reservoir at a reservoir end (LEFT = reservoir)
   *
   * <SPECIES> gives a concentration the whole domain starts at, which is all a
   * batch run can have; a front, a plume or a layer needs this. The value may
   * be an expression in what <PARAMETERS> can use -- x, i, w, the parameters,
   * the tables -- worked out once per cell. After it may come "fixed", which
   * holds the species at that value in those cells and nowhere else, and
   * "matrix", which aims the line at the rock behind those cells. `left` or
   * `right` in place of the cells names the reservoir at that end, which an
   * expression reads as the cell beside it.
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
      // The reservoir at an end, which is no cell of the column: see patchCells.
      if (/^(left|right)$/i.test(where)) {
        if (matrix) {
          throw new RtmError(`"matrix" and ${where.toLowerCase()}: a reservoir has no rock behind it.`, line);
        }
        out.push({ si: index.get(name), from: -1, to: -1, reservoir: where.toLowerCase(), value, ast, src: raw,
          matrix: false, fixed, line });
        continue;
      }
      let from;
      let to;
      if (/^all$/i.test(where)) { from = 0; to = cells - 1; } else {
        const m = /^(\d+)(?:\s*-\s*(\d+))?$/.exec(where);
        if (!m) {
          throw new RtmError(`"${where}" is not a cell or a range such as 0-9, "all", or left or right for the `
            + 'reservoir at that end.', line);
        }
        from = Number(m[1]);
        to = m[2] === undefined ? from : Number(m[2]);
      }
      if (from > to) { const t = from; from = to; to = t; }
      if (to >= cells) throw new RtmError(`Cell ${to} is past the last one (${cells - 1}).`, line);
      out.push({ si: index.get(name), from, to, reservoir: null, value, ast, src: raw, matrix, fixed, line });
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
    /*
      A name given an expression that reads the water -- a concentration, an
      activity, SI() or SR(), I, TK, TC, t, or a name of this kind before it
      on the line -- stands for that expression wherever the law (or a later
      such name) uses it, as if written there in brackets: si = SI(Calcite),
      area = A0*(m/m0)^0.6, m = [Calcite]. So a rate PHREEQC writes as a
      program reads as one here, step by step (compile, expandNames).
    */
    const exprs = new Map();
    const readsWater = (value) => /[[{]/.test(value) || /\b(SI|SR)\s*\(/.test(value) || /\b(I|TK|TC|t)\b/.test(value)
      || [...exprs.keys(), ...aliases.keys()].some((k) => new RegExp(`(^|[^A-Za-z0-9_])${k}([^A-Za-z0-9_(]|$)`).test(value));
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
      if (params.has(key) || aliases.has(key) || exprs.has(key)) {
        throw new RtmError(`${key} is given twice on the line.`, line);
      }
      const alias = /^\[\s*([^\]]+?)\s*\]$/.exec(value);
      // An alias or an expression may not take the name of what a rate law reads (a constant may: TK = 298).
      if ((alias || readsWater(value)) && RATE_WORDS.has(key)) {
        throw new RtmError(`"${key}" names something a rate law reads already; give it another name.`, line);
      }
      if (alias) {
        if (!SPECIES_NAME.test(alias[1])) {
          throw new RtmError(`"${key} = [${alias[1]}]": "${alias[1]}" is not a species name.`, line);
        }
        aliases.set(key, alias[1]);
        continue;
      }
      if (readsWater(value)) {
        exprs.set(key, value);
        continue;
      }
      // A name that is given only further on: a constant may use those before it, and so may an expression.
      const later = assigned.slice(assigned.findIndex(([k]) => k === key) + 1).map(([k]) => k)
        .find((k) => new RegExp(`(^|[^A-Za-z0-9_])${k}([^A-Za-z0-9_(]|$)`).test(value));
      if (later) {
        throw new RtmError(`${key} = "${value}" uses ${later}, which is given after it on the line: a name may use `
          + 'the names given before it.', line);
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
    return { reactants, products, params, aliases, exprs, rates, reversible, whole, line, text };
  }

  // What a rate law reads by name, and its functions: no name on a line may be one of them.
  const RATE_WORDS = new Set(['I', 'TK', 'TC', 't', 'SI', 'SR', 'exp', 'log', 'ln', 'log10', 'sqrt', 'abs', 'sign',
    'step', 'ramp', 'min', 'max', 'pow']);

  /**
   * A rate law with the names its line gives expressions (parseReaction's
   * exprs) put in, each in brackets: each expression first with those before
   * it in, then the law. A name is a whole word outside [...], {...} and the
   * phase of SI() and SR(), and not a function's name before its bracket.
   */
  function expandNames(src, exprs) {
    if (!exprs || !exprs.size) return src;
    const swap = (text, done) => {
      let out = '';
      for (let i = 0; i < text.length;) {
        const ch = text[i];
        // [A] and {A}, whole.
        if (ch === '[' || ch === '{') {
          const close = text.indexOf(ch === '[' ? ']' : '}', i);
          const end = close < 0 ? text.length : close + 1;
          out += text.slice(i, end);
          i = end;
          continue;
        }
        const m = /^[A-Za-z_][A-Za-z0-9_]*/.exec(text.slice(i));
        if (m && (i === 0 || !/[A-Za-z0-9_.]/.test(text[i - 1]))) {
          const word = m[0];
          let j = i + word.length;
          while (j < text.length && /\s/.test(text[j])) j++;
          // SI(phase) and SR(phase): the phase as written.
          if ((word === 'SI' || word === 'SR') && text[j] === '(') {
            const close = text.indexOf(')', j);
            const end = close < 0 ? text.length : close + 1;
            out += text.slice(i, end);
            i = end;
            continue;
          }
          out += done.has(word) && text[j] !== '(' ? `(${done.get(word)})` : word;
          i += word.length;
          continue;
        }
        out += ch;
        i++;
      }
      return out;
    };
    const done = new Map();
    for (const [key, value] of exprs) done.set(key, swap(value, done));
    return swap(String(src), done);
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
     2. (continued) Where a name is used
     ====================================================================== */
  /*
    WHERE A NAME IS USED, for the line the page shows under the model text:
    every line that names a species, a parameter or a table, and what the
    line does with it -- a species listed, started, made, used up, read by a
    rate. It is read from the text as it stands, which need not compile, and
    as the compiler reads it: a # starts a comment where readSections says it
    does, an equation is the line up to its first comma outside brackets, and
    its sides are split on " + " with the spaces.

    A species is a name only whole, where the compiler would take it for one:
    first on its <SPECIES> or <INITIAL> line, a term of an equation with or
    without a coefficient (2 H2O, 2H2O), in a rate's [ ] or { }, the phase of
    SI( ) and SR( ), a column of <DATA>. CO2 is not in CO2-, nor O2 in H2O2:
    a charge written against a name is part of it. A parameter or a table is
    a word -- a letter or _, then letters, digits and _ -- and never one in
    the brackets a species stands in.
  */
  const WORD_NAME = /^[A-Za-z_][A-Za-z0-9_]*$/;

  /** The text a line at a time: { line, section, header (a heading's words after its name, else null), code }. */
  function textLines(text) {
    const out = [];
    let section = '';
    String(text).split('\n').forEach((raw0, i) => {
      const raw = raw0.endsWith('\r') ? raw0.slice(0, -1) : raw0;
      const at = /(^|\s)#/.exec(raw);
      const code = at ? raw.slice(0, at.index + at[1].length) : raw;
      const head = /^<\s*([A-Za-z_]+)((?:\s+[^\s<>]+)*)\s*>$/.exec(code.trim());
      if (head) section = head[1].toUpperCase();
      out.push({ line: i + 1, section, header: head ? head[2].trim().split(/\s+/).filter(Boolean) : null, code });
    });
    return out;
  }

  /** The names a text gives: its species, from <SPECIES>; its parameters, from <PARAMETERS>; its tables. */
  function namesOf(text) {
    const species = new Set();
    const parameters = new Set();
    const tables = new Set();
    for (const l of textLines(text)) {
      if (l.header) {
        if (l.section === 'TABLE' && l.header.length) tables.add(l.header[0]);
        continue;
      }
      const first = l.code.trim().split(/[\s,;]+/)[0];
      if (!first) continue;
      if (l.section === 'SPECIES' && SPECIES_NAME.test(first)) species.add(first);
      else if (l.section === 'PARAMETERS' && WORD_NAME.test(first)) parameters.add(first);
    }
    return { species, parameters, tables };
  }

  /**
   * Whether a species can begin at code[i]: after a space, a bracket, a comma or an arrow; in SI( ), SR( ) and
   * the other keys that take a species; or after a coefficient written against it, 2H2O, the number standing
   * where a term begins.
   */
  function speciesStarts(code, i) {
    if (i === 0) return true;
    const c = code[i - 1];
    if (/[\s[{,;=>]/.test(c)) return true;
    if (c === '(') return /(?:^|[^A-Za-z0-9_])(?:SI|SR|la|share|p|a|sd)\s*\($/.test(code.slice(0, i));
    if (!/[0-9.]/.test(c)) return false;
    let k = i - 1;
    while (k > 0 && /[0-9.]/.test(code[k - 1])) k -= 1;
    return /^(?:\d+\.?\d*|\.\d+)$/.test(code.slice(k, i)) && (k === 0 || /[\s=>]/.test(code[k - 1]));
  }

  /** Where a species stands in a line's code, whole: [[start, end], ...]. */
  function speciesPlaces(code, name) {
    const out = [];
    if (!name) return out;
    for (let i = code.indexOf(name); i >= 0; i = code.indexOf(name, i + 1)) {
      const end = i + name.length;
      // A letter, a digit or a charge against its end makes it another name: CO2-, H2O2, UO2+2.
      if (end < code.length && /[A-Za-z0-9_(+-]/.test(code[end])) continue;
      if (speciesStarts(code, i)) out.push([i, end]);
    }
    return out;
  }

  /** Where a word -- a parameter, a table -- stands in a line's code, whole and outside [ ] and { }. */
  function wordPlaces(code, name) {
    const out = [];
    if (!name) return out;
    for (let i = code.indexOf(name); i >= 0; i = code.indexOf(name, i + 1)) {
      const end = i + name.length;
      if (end < code.length && /[A-Za-z0-9_]/.test(code[end])) continue;
      if (i > 0 && /[A-Za-z0-9_.]/.test(code[i - 1])) continue;
      let square = 0;
      let curly = 0;
      for (let k = 0; k < i; k += 1) {
        const ch = code[k];
        if (ch === '[') square += 1;
        else if (ch === ']') square -= 1;
        else if (ch === '{') curly += 1;
        else if (ch === '}') curly -= 1;
      }
      if (square <= 0 && curly <= 0) out.push([i, end]);
    }
    return out;
  }

  /** Where a reaction line's equation ends: its first comma outside brackets, or the end of the line. */
  function equationEnd(code) {
    let depth = 0;
    for (let k = 0; k < code.length; k += 1) {
      const ch = code[k];
      if (ch === '(' || ch === '[' || ch === '{') depth += 1;
      else if (ch === ')' || ch === ']' || ch === '}') depth -= 1;
      else if (ch === ',' && depth === 0) return k;
    }
    return code.length;
  }

  /** An equation's two sides, as parseReaction finds its arrow: { arrow, lhs, rhs }, <= turned round; or null. */
  function sidesOf(eq) {
    for (const arrow of ['<=>', '=>', '<=', '=']) {
      const at = eq.indexOf(arrow);
      if (at < 0) continue;
      const a = eq.slice(0, at);
      const b = eq.slice(at + arrow.length);
      return arrow === '<=' ? { arrow, lhs: b, rhs: a } : { arrow, lhs: a, rhs: b };
    }
    return null;
  }

  /** A side's terms as [coefficient, name], read as parseSide reads them, nothing refused. */
  function termsOf(side) {
    const text = side.trim();
    if (!text) return [];
    return text.split(/\s\+\s/).map((t) => {
      const m = /^(\d+(?:\.\d+)?)?\s*(.+)$/.exec(t.trim());
      return m ? [m[1] ? Number(m[1]) : 1, m[2].trim()] : [0, ''];
    });
  }

  /**
   * Every line of a text that names a species, a parameter or a table (kind), and what it does there:
   * { name, kind, places: [{ line, start, end }], roles: { role: [line, ...] } }, the places in the order of the
   * text, a role's lines rising. A species' roles: listed (first on its <SPECIES> line), start (first on an
   * <INITIAL> line), added (by a source, => X), made, usedUp, removed (by a sink, X =>), both (as many on either
   * side), twoWay (in a reaction <=>), read (by the line's rate, past its equation), equilibrium, phase, output,
   * data (a column of <DATA>) and other. A parameter's: set (first on a <PARAMETERS> line) and used. A table's:
   * table (its heading) and used.
   */
  function usesOf(text, name, kind) {
    const places = [];
    const roles = {};
    const add = (role, line) => {
      const list = roles[role] || (roles[role] = []);
      if (list[list.length - 1] !== line) list.push(line);
    };
    for (const { line, section, header, code } of textLines(text)) {
      if (header && !(kind === 'table' && section === 'TABLE')) continue;
      const found = kind === 'species' ? speciesPlaces(code, name) : wordPlaces(code, name);
      if (!found.length) continue;
      for (const [start, end] of found) places.push({ line, start, end });
      if (kind === 'table') { add(header ? 'table' : 'used', line); continue; }
      const lead = code.length - code.trimStart().length;
      const first = found[0][0] === lead && code.slice(lead).split(/[\s,;]+/)[0] === name;
      if (kind === 'parameter') { add(section === 'PARAMETERS' && first ? 'set' : 'used', line); continue; }
      if (section === 'SPECIES') add(first ? 'listed' : 'other', line);
      else if (section === 'INITIAL') add(first ? 'start' : 'other', line);
      else if (section === 'REACTIONS') {
        const cut = equationEnd(code);
        const sides = sidesOf(code.slice(0, cut));
        let term = false;
        if (sides) {
          const sum = (side) => termsOf(side).reduce((a, [c, n]) => (n === name ? a + c : a), 0);
          const left = sum(sides.lhs);
          const right = sum(sides.rhs);
          if (left || right) {
            term = true;
            if (sides.arrow === '<=>') add('twoWay', line);
            else if (!sides.lhs.trim()) add('added', line);
            else if (!sides.rhs.trim()) add('removed', line);
            else add(right > left ? 'made' : left > right ? 'usedUp' : 'both', line);
          }
        }
        if (found.some(([s]) => s >= cut)) add('read', line);
        if (!term && found.some(([s]) => s < cut)) add('other', line);
      } else {
        add({ EQUILIBRIUM: 'equilibrium', PHASES: 'phase', OUTPUT: 'output', DATA: 'data' }[section] || 'other', line);
      }
    }
    return { name, kind, places, roles };
  }

  /**
   * The name at a place in the text: the caret (start === end) on it or just after it, or a selection that is
   * the name exactly, given the text's names (namesOf). A species before a parameter before a table, the longest
   * where two would do. { name, kind } or null: on no name, in a comment, a selection over more than one line.
   */
  function nameAt(text, start, end, names) {
    const s = String(text);
    if (!(start >= 0) || !(end >= start)) return null;
    const from = s.lastIndexOf('\n', start - 1) + 1;
    let to = s.indexOf('\n', start);
    if (to < 0) to = s.length;
    if (end > to) return null;
    let raw = s.slice(from, to);
    if (raw.endsWith('\r')) raw = raw.slice(0, -1);
    const at = /(^|\s)#/.exec(raw);
    const code = at ? raw.slice(0, at.index + at[1].length) : raw;
    const a = start - from;
    const b = end - from;
    if (b > code.length) return null;
    const kinds = /^<.*>$/.test(code.trim()) ? [['table', names.tables]]
      : [['species', names.species], ['parameter', names.parameters], ['table', names.tables]];
    let best = null;
    for (const [kind, set] of kinds) {
      for (const name of set) {
        if (!code.includes(name)) continue;
        const found = kind === 'species' ? speciesPlaces(code, name) : wordPlaces(code, name);
        for (const [p, q] of found) {
          const hit = a === b ? p <= a && a <= q : p === a && q === b;
          if (hit && (!best || q - p > best.len)) best = { name, kind, len: q - p };
        }
      }
    }
    return best ? { name: best.name, kind: best.kind } : null;
  }

  /*
    WHAT HAS CHANGED in a text since it was opened: its lines against the
    text as opened, by the shortest edit -- Myers' O(ND) difference, the lines
    the two begin and end with set aside first, so that a few lines changed in
    a long text cost a few steps. Past CHANGES_MAX steps the texts are taken
    to differ throughout the part between, which is then one change.
  */
  const CHANGES_MAX = 2000;

  /**
   * The changes from one text to another, in order: [{ from, was, at, now }], `was` the lines of the first from
   * its line `from` and `now` those of the second from its line `at` (1-based); a line put in has `was` empty, a
   * line taken out `now` empty, `at` then the line it would have been.
   */
  function lineChanges(before, after) {
    const a = String(before).split('\n');
    const b = String(after).split('\n');
    let head = 0;
    while (head < a.length && head < b.length && a[head] === b[head]) head += 1;
    let tail = 0;
    while (tail < a.length - head && tail < b.length - head && a[a.length - 1 - tail] === b[b.length - 1 - tail]) tail += 1;
    const A = a.slice(head, a.length - tail);
    const B = b.slice(head, b.length - tail);
    const n = A.length;
    const m = B.length;
    if (!n && !m) return [];
    const whole = [{ from: head + 1, was: A, at: head + 1, now: B }];
    if (!n || !m) return whole;
    // Forward: v[k] the furthest x on diagonal k = x - y, each step's v kept (k from -d-1 to d+1) for the way back.
    const max = Math.min(n + m, CHANGES_MAX);
    const off = max + 1;
    const v = new Int32Array(2 * max + 3);
    const trace = [];
    let done = false;
    for (let d = 0; d <= max && !done; d += 1) {
      trace.push(v.slice(off - d - 1, off + d + 2));
      for (let k = -d; k <= d; k += 2) {
        let x = k === -d || (k !== d && v[off + k - 1] < v[off + k + 1]) ? v[off + k + 1] : v[off + k - 1] + 1;
        let y = x - k;
        while (x < n && y < m && A[x] === B[y]) { x += 1; y += 1; }
        v[off + k] = x;
        if (x >= n && y >= m) { done = true; break; }
      }
    }
    if (!done) return whole;
    // Back from the end: each step a line taken out or put in, and the lines the two share before it.
    const ops = [];
    let x = n;
    let y = m;
    for (let d = trace.length - 1; d >= 0; d -= 1) {
      const t = trace[d];
      const at = (k) => t[k + d + 1];
      const k = x - y;
      const prev = k === -d || (k !== d && at(k - 1) < at(k + 1)) ? k + 1 : k - 1;
      const px = at(prev);
      const py = px - prev;
      while (x > px && y > py) { ops.push('='); x -= 1; y -= 1; }
      if (d > 0) ops.push(x === px ? '+' : '-');
      x = px;
      y = py;
    }
    ops.reverse();
    const out = [];
    let cur = null;
    let i = 0;
    let j = 0;
    for (const op of ops) {
      if (op === '=') { cur = null; i += 1; j += 1; continue; }
      if (!cur) { cur = { from: head + i + 1, was: [], at: head + j + 1, now: [] }; out.push(cur); }
      if (op === '-') { cur.was.push(A[i]); i += 1; } else { cur.now.push(B[j]); j += 1; }
    }
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

  // The chemical elements, by symbol: what a species' name is counted in for a total.
  const ELEMENT_SYMBOLS = new Set(('H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn '
    + 'Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er '
    + 'Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf Db Sg '
    + 'Bh Hs Mt Ds Rg Cn Nh Fl Mc Lv Ts Og').split(' '));

  /*
    THE STANDARD ATOMIC WEIGHTS, IUPAC's abridged to five figures (2021),
    and for an element that has none the mass number of its longest-lived
    isotope: a species' formula mass from its name (the Durov diagram's
    total dissolved solids), and what tells a nuclide's mass number from a
    formula's count (elementsOf).
  */
  const ATOMIC_WEIGHTS = {
    H: 1.0080, He: 4.0026, Li: 6.94, Be: 9.0122, B: 10.81, C: 12.011, N: 14.007, O: 15.999, F: 18.998, Ne: 20.180,
    Na: 22.990, Mg: 24.305, Al: 26.982, Si: 28.085, P: 30.974, S: 32.06, Cl: 35.45, Ar: 39.95, K: 39.098, Ca: 40.078,
    Sc: 44.956, Ti: 47.867, V: 50.942, Cr: 51.996, Mn: 54.938, Fe: 55.845, Co: 58.933, Ni: 58.693, Cu: 63.546, Zn: 65.38,
    Ga: 69.723, Ge: 72.630, As: 74.922, Se: 78.971, Br: 79.904, Kr: 83.798, Rb: 85.468, Sr: 87.62, Y: 88.906, Zr: 91.224,
    Nb: 92.906, Mo: 95.95, Tc: 98, Ru: 101.07, Rh: 102.91, Pd: 106.42, Ag: 107.87, Cd: 112.41, In: 114.82, Sn: 118.71,
    Sb: 121.76, Te: 127.60, I: 126.90, Xe: 131.29, Cs: 132.91, Ba: 137.33, La: 138.91, Ce: 140.12, Pr: 140.91, Nd: 144.24,
    Pm: 145, Sm: 150.36, Eu: 151.96, Gd: 157.25, Tb: 158.93, Dy: 162.50, Ho: 164.93, Er: 167.26, Tm: 168.93, Yb: 173.05,
    Lu: 174.97, Hf: 178.49, Ta: 180.95, W: 183.84, Re: 186.21, Os: 190.23, Ir: 192.22, Pt: 195.08, Au: 196.97, Hg: 200.59,
    Tl: 204.38, Pb: 207.2, Bi: 208.98, Po: 209, At: 210, Rn: 222, Fr: 223, Ra: 226, Ac: 227, Th: 232.04,
    Pa: 231.04, U: 238.03, Np: 237, Pu: 244, Am: 243, Cm: 247, Bk: 247, Cf: 251, Es: 252, Fm: 257, Md: 258, No: 259,
    Lr: 266, Rf: 267, Db: 268, Sg: 269, Bh: 270, Hs: 269, Mt: 278, Ds: 281, Rg: 282, Cn: 285, Nh: 286, Fl: 289, Mc: 290,
    Lv: 293, Ts: 294, Og: 294,
  };

  /**
   * What a species' name is made of, PHREEQC's way of writing a formula, its
   * charge left off: Ca+2 one Ca; CaHCO3+ one each of Ca, H and C and three
   * O; (UO2)2(OH)2+2 -- UO2_2(OH)2+2 as From PHREEQC renames it -- two U and
   * six O; Ca0.5X half a Ca and an X; CaSO4:2H2O the water too; Hfo_wOH one
   * Hfo_w, a surface's sites, as PHREEQC counts it. A Map of symbol to
   * count, or null where the name cannot be read as one -- e-, (Ca. A
   * symbol that is no element (X, Hfo_w, Tracer) is kept: what it counts in
   * is for the caller to say.
   *
   * A nuclide's name, an element and its mass number -- U238, Ra226+2, C14
   * -- is one atom of it, not that many: a number between 0.75 and 1.35
   * times the element's atomic weight is a mass number, where a formula's
   * count is far from it (O2, H2, S8, C60). Tritium, H3, is one of its own.
   */
  function elementsOf(name) {
    let s = String(name).replace(/\(g\)$/, '').replace(/(?:[+-]+[0-9]*)$/, '');
    if (!s || !/^[A-Z(]/.test(s)) return null;
    const nuclide = nuclideOf(name);
    if (nuclide) return new Map([[nuclide[0], 1]]);
    const total = new Map();
    const addTo = (m, el, n) => m.set(el, (m.get(el) || 0) + n);
    for (const piece of s.split(':')) {
      let i = 0;
      const num = () => {
        const m = /^(\d+(?:\.\d*)?|\.\d+)/.exec(piece.slice(i));
        if (!m) return 1;
        i += m[0].length;
        return Number(m[1]);
      };
      // A hydrate's water, :2H2O, has its count in front.
      const lead = /^\d/.test(piece) ? num() : 1;
      const stack = [new Map()];
      while (i < piece.length) {
        const ch = piece[i];
        if (ch === '(') { stack.push(new Map()); i++; continue; }
        if (ch === ')') {
          if (stack.length < 2) return null;
          i++;
          const g = stack.pop();
          const k = num();
          for (const [el, n] of g) addTo(stack[stack.length - 1], el, n * k);
          continue;
        }
        // UO2_2: what came before it, twice -- From PHREEQC's (UO2)2.
        if (ch === '_' && /\d/.test(piece[i + 1] || '')) {
          i++;
          const k = num();
          const top = stack[stack.length - 1];
          for (const [el, n] of [...top]) top.set(el, n * k);
          continue;
        }
        const m = /^[A-Z][a-z]*(?:_[a-z][a-z]*)?/.exec(piece.slice(i));
        if (!m) return null;
        i += m[0].length;
        addTo(stack[stack.length - 1], m[0], num());
      }
      if (stack.length !== 1) return null;
      for (const [el, n] of stack[0]) addTo(total, el, n * lead);
    }
    return total.size ? total : null;
  }

  /**
   * A nuclide's name, an element and its mass number, as elementsOf reads
   * it -- U238, Ra226+2, C14, tritium's H3 -- as [symbol, mass number]; null
   * for any other name, O2 and S8 among them.
   */
  function nuclideOf(name) {
    const s = String(name).replace(/\(g\)$/, '').replace(/(?:[+-]+[0-9]*)$/, '');
    const m = /^([A-Z][a-z]?)(\d+)$/.exec(s);
    if (!m || !ELEMENT_SYMBOLS.has(m[1])) return null;
    const w = ATOMIC_WEIGHTS[m[1]];
    const A = Number(m[2]);
    return (w && A >= 0.75 * w && A <= 1.35 * w) || s === 'H3' ? [m[1], A] : null;
  }

  /**
   * A species' formula mass, g/mol, from its name: what it is made of
   * (elementsOf) by the standard atomic weights -- CaHCO3+ 101.10, CO2(g)
   * 44.01 -- and a nuclide by its mass number, U238 238 and C14 14, within
   * about 0.1 % of its atomic mass (tritium's, 3.016, within 0.6 %). Null
   * where the name is no formula, or has a symbol that is no element: X-,
   * CaX2, Hfo_wOH, Tracer.
   */
  function formulaMass(name) {
    const nuclide = nuclideOf(name);
    if (nuclide) return nuclide[1];
    const made = elementsOf(name);
    if (!made) return null;
    let m = 0;
    for (const [el, n] of made) {
      const w = ATOMIC_WEIGHTS[el];
      if (!w) return null;
      m += n * w;
    }
    return m;
  }

  /**
   * Each species' formula mass, g/mol, or null: what a concentration in
   * mol/kgw is weighed by to show it in mg/kgw. A species by its name
   * (formulaMass); a mineral by what a relation it is in makes of it, as
   * compositionOf reads what it is made of, the water's mass among the rest
   * -- Ferrihydrite + 3 H+ <=> Fe+3 + 3 H2O weighs it as Fe(OH)3, 106.87 --
   * and by its name where no relation weighs it. Null for the electron and a
   * surface's potential, which are no amounts, and where a name, or a part
   * of the relation, is no formula.
   */
  function formulaMassesOf(species, nameOf, index, equilibria, reactions) {
    const out = species.map((sp, k) => (sp.electron || sp.potential || sp.mineral ? null : formulaMass(nameOf[k])));
    const water = formulaMass('H2O');
    const relations = [
      ...equilibria.map((eq) => ({ terms: eq.net, water: eq.water || 0 })),
      ...reactions.map((rx) => ({ terms: [...rx.reactants.map(([c, nm]) => [index.get(nm), -c]),
        ...rx.products.map(([c, nm]) => [index.get(nm), c])].filter(([k]) => k !== undefined), water: 0 })),
    ];
    // -(sum nu M + water M(H2O))/nu over the rest, the electron weighing nothing; null where one of the rest has no mass.
    const fromRelation = (m, { terms, water: w }) => {
      let nuM = 0;
      let sum = w * water;
      for (const [k, nu] of terms) {
        if (k === m) { nuM += nu; continue; }
        if (species[k].electron) continue;
        if (!(out[k] > 0)) return null;
        sum += nu * out[k];
      }
      const M = nuM ? -sum / nuM : NaN;
      return M > 0 ? M : null;
    };
    // Twice over: a mineral made from another mineral is weighed once that one is.
    for (let pass = 0; pass < 2; pass++) {
      for (let m = 0; m < species.length; m++) {
        if (!species[m].mineral || out[m] !== null) continue;
        for (const rel of relations) {
          if (!rel.terms.some(([k]) => k === m)) continue;
          out[m] = fromRelation(m, rel);
          if (out[m] !== null) break;
        }
      }
    }
    for (let m = 0; m < species.length; m++) if (species[m].mineral && out[m] === null) out[m] = formulaMass(nameOf[m]);
    return out;
  }

  /**
   * <DATA>: what was measured, drawn as points beside what the run gives.
   * Tables one after another, each begun by a line naming its columns: the
   * first time or distance, the rest species or the names the page gives its
   * quantities -- pH, SI(Calcite), tot(Ca), an <OUTPUT> -- with where the
   * table belongs on the same line: cell = 19 for one in time (the column's
   * cell, from 0; the first unless said), layer = 2 for the rock behind it,
   * at = 3600 for one in distance (in the model's time unit; the end of the
   * run unless said). A table whose first column is pH, pe or Eh is of a
   * water held there rather than of a run -- a sorption edge -- the water
   * of cell = 0 unless said, as the model starts it, speciated at each value
   * as the Diagrams tab speciates it: kind 'speciation', its axis that
   * first column. Then a row of numbers per point, a dash for one not
   * measured. A column sd(Ca+2) beside Ca+2 is the standard deviation of
   * each value of it, which a fit weighs it by. A table against pH, pe or
   * Eh may start its water with species of its own, Zn+2 = 1e-4 on its line
   * (no spaces in the number): the model with those species started there,
   * a water of its own -- a sorption edge at another loading. A table whose
   * first column is sys(Zn) is of the water with that much of the element
   * in the cell, dissolved, sorbed, exchanged or a mineral, as PHREEQC's
   * SYS("Zn") counts it -- a sorption isotherm -- axis 'tot' and species
   * the element, as the Diagrams tab varies a total; pH = 6.5 on the line
   * of any table of a water holds that water's pH there, as the Diagrams
   * tab holds one (without it, against sys(), the pH stays where the water
   * has it).
   * Returns [{ kind, axis, species, pH, columns, water: [[name, value]], cell, layer, at, rows, line }].
   */
  function readData(lines) {
    const tables = [];
    let cur = null;
    for (const { text, line } of lines) {
      const tokens = text.split(/\s+/).filter(Boolean);
      const first = tokens[0].toLowerCase();
      // An element in the system, sys(Zn): all of it in the cell, as PHREEQC's SYS("Zn").
      const sys = /^sys\(([^()\s]+)\)$/i.exec(tokens[0]);
      if (['time', 't', 'distance', 'x', 'ph', 'pe', 'eh'].includes(first) || sys) {
        const quals = {};
        const water = [];
        const rest = text.slice(text.indexOf(tokens[0]) + tokens[0].length)
          .replace(/(^|\s)(cell|layer|at)\s*=\s*(\S+)/gi, (_, sp, k, v) => { quals[k.toLowerCase()] = v; return ' '; })
          // Any other name = number: a species started there in the table's own water.
          .replace(/(^|\s)([^\s=]+)\s*=\s*(\S+)/g, (_, sp, name, v) => { water.push([name, v]); return ' '; });
        const columns = rest.split(/\s+/).filter(Boolean);
        const kind = first === 'time' || first === 't' ? 'time' : first === 'distance' || first === 'x' ? 'distance' : 'speciation';
        const axis = kind === 'speciation' ? (sys ? 'tot' : { ph: 'pH', pe: 'pe', eh: 'Eh' }[first]) : null;
        if (!columns.length) {
          throw new RtmError(`"${text}": a table in <DATA> names its columns after ${tokens[0]}: time  Ca+2  pH  cell = 19.`, line);
        }
        if (kind !== 'speciation' && water.length) {
          throw new RtmError(`"${text}": ${water[0][0]} = sets a water of the table's own, which a table against pH, pe, Eh `
            + 'or an element in the system, sys(Zn), has; one in time or in distance is the run\'s, of the model\'s own water.', line);
        }
        if (kind === 'speciation' && (quals.at !== undefined || quals.layer !== undefined)) {
          throw new RtmError(`"${text}": a table against ${tokens[0]} is of the water of a cell held there, cell = 0; `
            + 'at = and layer = are for tables in time and in distance.', line);
        }
        // pH = 6.5: the pH the table's water is held at, not a species started.
        const held = water.filter(([name]) => name.toLowerCase() === 'ph');
        if (held.length && axis === 'pH') {
          throw new RtmError(`"${text}": pH = holds the water at a pH, and this table's pH is what it varies.`, line);
        }
        if (held.length > 1) throw new RtmError(`"${text}": pH = is given ${held.length} times; once is enough.`, line);
        const whole = (key) => {
          const v = Number(quals[key]);
          if (!Number.isInteger(v) || v < 0) throw new RtmError(`"${text}": ${key} = is a whole number, from 0.`, line);
          return v;
        };
        if (kind === 'time' && quals.at !== undefined) {
          throw new RtmError(`"${text}": a table in time is at a cell, cell = 19; at = is for one in distance.`, line);
        }
        if (kind === 'distance' && quals.cell !== undefined) {
          throw new RtmError(`"${text}": a table in distance is at a time, at = 3600; cell = is for one in time.`, line);
        }
        cur = { kind, axis, species: sys ? sys[1] : null, pH: held.length ? constValue(held[0][1], line, 'pH') : null, columns,
          water: water.filter(([name]) => name.toLowerCase() !== 'ph').map(([name, v]) => [name, constValue(v, line, name)]),
          cell: quals.cell !== undefined ? whole('cell') : null,
          layer: quals.layer !== undefined ? whole('layer') : 0,
          at: quals.at !== undefined ? constValue(quals.at, line, 'at') : null, rows: [], line };
        tables.push(cur);
        continue;
      }
      if (!cur) {
        throw new RtmError('<DATA> begins with a line naming the columns of a table: time  Ca+2  pH  cell = 19, '
          + 'distance  Ca+2  at = 3600, or pH  Zn_sorbed  cell = 0 for a water held at each pH.', line);
      }
      const xName = cur.axis === 'tot' ? `sys(${cur.species})` : cur.axis || cur.kind;
      if (tokens.length !== cur.columns.length + 1) {
        throw new RtmError(`"${text}": the table on line ${cur.line} has ${cur.columns.length + 1} columns, `
          + `${xName} and ${cur.columns.join(', ')}; a dash for a value not measured.`, line);
      }
      const row = tokens.map((v) => (v === '-' ? null : Number(v)));
      if (row[0] === null || row.some((v) => v !== null && !Number.isFinite(v))) {
        throw new RtmError(`"${text}": every value is a number, or a dash where nothing was measured; the ${xName} always.`, line);
      }
      if (cur.axis === 'tot' && !(row[0] > 0)) {
        throw new RtmError(`"${text}": ${xName} is the ${cur.species} in the cell, in mol/kgw, and above nought.`, line);
      }
      cur.rows.push(row);
    }
    return tables;
  }

  /** A relation's or a reaction's equation as a sweep or a fit names it: what comes before its first comma, spaces collapsed. */
  const equationOf = (code) => splitTop(code)[0].trim().replace(/\s+/g, ' ');

  /**
   * What a sweep or a fit can change besides a setting, a parameter and a
   * species' numbers: each relation's and each phase's logK, and each number
   * a reaction's line names -- k, kf, kb, or a constant of its own rate law,
   * vmax = 2e-5 -- that is a number rather than an expression. Each is
   * { kind: 'logK' | 'rate', name, value }: name the equation as written,
   * spaces collapsed, and for a reaction's number its name after a bar,
   * 'S => P | vmax'. In the order of the text.
   */
  function tunables(text) {
    const out = [];
    let current = null;
    for (const raw of String(text).split(/\r?\n/)) {
      const cm = /(^|\s)#.*$/.exec(raw);
      const body = (cm ? raw.slice(0, cm.index + cm[1].length) : raw).trim();
      if (!body) continue;
      const header = /^<\s*([A-Za-z_]+)((?:\s+[^\s<>]+)*)\s*>$/.exec(body);
      if (header) { current = header[1].toUpperCase(); continue; }
      if (current !== 'EQUILIBRIUM' && current !== 'PHASES' && current !== 'REACTIONS') continue;
      const parts = splitTop(body).map((p) => p.trim());
      const eq = parts[0].replace(/\s+/g, ' ');
      for (const part of parts.slice(1)) {
        const m = /^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$/.exec(part);
        if (!m || !/^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$/.test(m[2].trim())) continue;
        const value = Number(m[2]);
        if (current !== 'REACTIONS') {
          if (m[1] === 'logK') out.push({ kind: 'logK', name: eq, value });
        } else if (!['r', 'rb', 'on'].includes(m[1])) out.push({ kind: 'rate', name: `${eq} | ${m[1]}`, value });
      }
    }
    return out;
  }

  // The words a species line may carry besides its numbers and key=value pairs (readSpecies).
  const SPECIES_WORDS = new Set(['fixed', 'immobile', 'mineral', 'exchanger', 'exchange', 'electron', 'surface', 'potential',
    'gas', 'drummond', 'dissolve_only', 'precipitate_only', 'force_equality']);

  /**
   * The model text with one number changed, as a sweep varies it: a
   * setting's value, its line added to <SETTINGS> where the text has none;
   * every value a parameter of <PARAMETERS> is given, its cells and scope
   * kept; a species' starting concentration on its line; or what flows in
   * at the left, its left=. The rest of the text is as it was, comments and
   * spacing too. vary is { kind: 'setting' | 'parameter' | 'initial' |
   * 'left', name }.
   */
  function withValue(text, vary, value) {
    const v = String(Number(value));
    const lines = String(text).split(/\r?\n/);
    let current = null;
    let settingsAt = -1;
    let hit = 0;
    const out = lines.map((raw, i) => {
      const cm = /(^|\s)#.*$/.exec(raw);
      const code = cm ? raw.slice(0, cm.index + cm[1].length) : raw;
      const comment = cm ? raw.slice(cm.index + cm[1].length) : '';
      const body = code.trim();
      if (!body) return raw;
      const header = /^<\s*([A-Za-z_]+)((?:\s+[^\s<>]+)*)\s*>$/.exec(body);
      if (header) {
        current = header[1].toUpperCase();
        if (current === 'SETTINGS' && settingsAt < 0) settingsAt = i;
        return raw;
      }
      if (vary.kind === 'setting' && current === 'SETTINGS') {
        const m = /^(\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*=\s*)(.*?)(\s*)$/.exec(code);
        if (m && m[2].toUpperCase() === vary.name) { hit++; return `${m[1]}${m[2]}${m[3]}${v}${m[5]}${comment}`; }
      }
      if (vary.kind === 'parameter' && current === 'PARAMETERS') {
        const m = /^(\s*)([A-Za-z_][A-Za-z0-9_]*)(\s+)(\S+)(\s+)(.+?)(\s+(?:fracture|matrix))?(\s*)$/i.exec(code);
        if (m && m[2] === vary.name) { hit++; return `${m[1]}${m[2]}${m[3]}${m[4]}${m[5]}${v}${m[7] || ''}${m[8]}${comment}`; }
      }
      // A relation's or a phase's logK, the line found by its equation; a number a reaction's line names, by its
      // equation and the name: 'S => P | vmax'.
      if (vary.kind === 'logK' && (current === 'EQUILIBRIUM' || current === 'PHASES')
        && equationOf(code) === vary.name && /(^|,)\s*logK\s*=/.test(code)) {
        hit++;
        return `${code.replace(/((?:^|,)\s*logK\s*=\s*)([^,]*?)(\s*(?=,|$))/, `$1${v}$3`)}${comment}`;
      }
      if (vary.kind === 'rate' && current === 'REACTIONS') {
        const bar = vary.name.lastIndexOf(' | ');
        const key = vary.name.slice(bar + 3);
        if (bar > 0 && equationOf(code) === vary.name.slice(0, bar) && new RegExp(`,\\s*${key}\\s*=`).test(code)) {
          hit++;
          return `${code.replace(new RegExp(`(,\\s*${key}\\s*=\\s*)([^,]*?)(\\s*(?=,|$))`), `$1${v}$3`)}${comment}`;
        }
      }
      if ((vary.kind === 'initial' || vary.kind === 'left') && current === 'SPECIES') {
        const toks = [...code.matchAll(/[^\s,;]+/g)];
        if (!toks.length || toks[0][0] !== vary.name) return raw;
        hit++;
        const put = (tok, word) => `${code.slice(0, tok.index)}${word}${code.slice(tok.index + tok[0].length)}${comment}`;
        if (vary.kind === 'left') {
          const tok = toks.find((x) => /^left\s*=/i.test(x[0]));
          return tok ? put(tok, `left=${v}`) : `${code.replace(/\s*$/, '')}  left=${v}${comment ? ` ${comment}` : ''}`;
        }
        const tok = toks.slice(1).find((x) => !x[0].includes('=') && !SPECIES_WORDS.has(x[0].toLowerCase()));
        if (tok) return put(tok, v);
        const after = toks[0].index + toks[0][0].length;
        return `${code.slice(0, after)}  ${v}${code.slice(after)}${comment}`;
      }
      return raw;
    });
    if (!hit) {
      if (vary.kind === 'setting') {
        if (settingsAt >= 0) out.splice(settingsAt + 1, 0, `${vary.name} = ${v}`);
        else out.unshift('<SETTINGS>', `${vary.name} = ${v}`, '');
      } else {
        throw new RtmError(vary.kind === 'parameter' ? `There is no parameter ${vary.name} in <PARAMETERS> to vary.`
          : vary.kind === 'logK' ? `There is no relation or phase ${vary.name} with a logK = to vary.`
            : vary.kind === 'rate' ? `There is no reaction ${vary.name.replace(' | ', ' with ')} = to vary.`
              : `There is no species ${vary.name} in <SPECIES> to vary.`);
      }
    }
    return out.join('\n');
  }

  /**
   * The number a sweep would change (withValue), as the text gives it: a
   * setting's, a parameter's on its first line, a species' start on its line
   * (0 where the line has none), or its left=. Null where the text gives no
   * number there -- an expression, or nothing.
   */
  function valueIn(text, vary) {
    let current = null;
    let found = null;
    for (const raw of String(text).split(/\r?\n/)) {
      const cm = /(^|\s)#.*$/.exec(raw);
      const body = (cm ? raw.slice(0, cm.index + cm[1].length) : raw).trim();
      if (!body) continue;
      const header = /^<\s*([A-Za-z_]+)((?:\s+[^\s<>]+)*)\s*>$/.exec(body);
      if (header) { current = header[1].toUpperCase(); continue; }
      if (vary.kind === 'setting' && current === 'SETTINGS') {
        const m = /^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)$/.exec(body);
        if (m && m[1].toUpperCase() === vary.name) found = m[2];
      } else if (vary.kind === 'parameter' && current === 'PARAMETERS') {
        const m = /^([A-Za-z_][A-Za-z0-9_]*)\s+(\S+)\s+(.+?)(\s+(?:fracture|matrix))?$/i.exec(body);
        if (m && m[1] === vary.name && found === null) found = m[3];
      } else if (vary.kind === 'logK' && (current === 'EQUILIBRIUM' || current === 'PHASES')) {
        const m = /(?:^|,)\s*logK\s*=\s*([^,]*?)\s*(?=,|$)/.exec(body);
        if (m && found === null && equationOf(body) === vary.name) found = m[1];
      } else if (vary.kind === 'rate' && current === 'REACTIONS') {
        const bar = vary.name.lastIndexOf(' | ');
        if (bar < 0 || equationOf(body) !== vary.name.slice(0, bar)) continue;
        const m = new RegExp(`,\\s*${vary.name.slice(bar + 3)}\\s*=\\s*([^,]*?)\\s*(?=,|$)`).exec(body);
        if (m && found === null) found = m[1];
      } else if ((vary.kind === 'initial' || vary.kind === 'left') && current === 'SPECIES') {
        const toks = body.split(/[\s,;]+/).filter(Boolean);
        if (toks[0] !== vary.name) continue;
        if (vary.kind === 'left') {
          const tok = toks.find((x) => /^left\s*=/i.test(x));
          found = tok ? tok.replace(/^left\s*=\s*/i, '') : null;
        } else found = toks.slice(1).find((x) => !x.includes('=') && !SPECIES_WORDS.has(x.toLowerCase())) || '0';
      }
    }
    const v = found === null ? NaN : Number(found);
    return Number.isFinite(v) ? v : null;
  }

  /**
   * What each species is made of, for the views of where an element is and
   * of the water's major ions. For each element but H and O, each species
   * with any of it, [k, how many, where], where being 'water', 'exchange',
   * 'surface', 'mineral' or 'gas'. A name says what a species is made of
   * (elementsOf); a mineral's is what its relation, in <EQUILIBRIUM> or
   * <REACTIONS>, makes of the rest: Calcite <=> Ca+2 + CO3-2, one Ca and
   * one C. Then, of what is dissolved, the sulfate's sulfur -- in a species
   * with four O to each S or more: SO4-2, HSO4-, CaSO4, not HS- -- and the
   * carbonate's equivalents, in a species with three O to each C or more,
   * two to each C less one to each H: CO3-2 and CaCO3 two, HCO3- and
   * CaHCO3+ one, H2CO3 none, and CO2, with two O, none.
   * Returns { elements: [{ el, terms }], sulfate: [[k, S]], carbonate: [[k, eq]] }.
   */
  function compositionOf(species, nameOf, index, equilibria, reactions, isSolute) {
    const ns = species.length;
    const where = species.map((sp, k) => (sp.mineral ? 'mineral' : sp.exchange ? 'exchange' : sp.surface ? 'surface'
      : sp.gas ? 'gas' : isSolute(k) && !sp.electron && sp.name !== 'H2O' ? 'water' : null));
    const made = species.map((sp, k) => (where[k] && where[k] !== 'mineral' ? elementsOf(nameOf[k]) : null));
    // A mineral's, from a relation it is in: -sum(nu E)/nu over the rest; none where one of the rest has no formula.
    const fromRelation = (m, terms) => {
      let nuM = 0;
      const sum = new Map();
      for (const [k, nu] of terms) {
        if (k === m) { nuM += nu; continue; }
        if (species[k].electron || nameOf[k] === 'H2O') continue;
        if (!made[k]) return null;
        for (const [el, n] of made[k]) sum.set(el, (sum.get(el) || 0) + nu * n);
      }
      if (!nuM) return null;
      const out = new Map();
      for (const [el, n] of sum) if (Math.abs(n / nuM) > 1e-12) out.set(el, -n / nuM);
      return out.size ? out : null;
    };
    const relations = [
      ...equilibria.map((eq) => eq.net),
      ...reactions.map((rx) => [...rx.reactants.map(([c, nm]) => [index.get(nm), -c]),
        ...rx.products.map(([c, nm]) => [index.get(nm), c])].filter(([k]) => k !== undefined)),
    ];
    // Twice over: a mineral made from another mineral is read once that one is.
    for (let pass = 0; pass < 2; pass++) {
      for (let m = 0; m < ns; m++) {
        if (where[m] !== 'mineral' || made[m]) continue;
        for (const terms of relations) {
          if (!terms.some(([k]) => k === m)) continue;
          made[m] = fromRelation(m, terms);
          if (made[m]) break;
        }
      }
    }
    const states = valenceStatesOf(species, nameOf, made, where, relations);
    const byElement = new Map();
    for (let k = 0; k < ns; k++) {
      if (!made[k]) continue;
      for (const [el, n] of made[k]) {
        if (el === 'H' || el === 'O' || !ELEMENT_SYMBOLS.has(el) || !(n > 0)) continue;
        if (!byElement.has(el)) byElement.set(el, []);
        const s = states[k] && states[k].get(el);
        byElement.get(el).push([k, n, where[k], s === undefined ? null : s]);
      }
    }
    /*
      THE COUPLES: each relation with the electron in it between two valence
      states of an element, the database's half-reactions as PHREEQC writes
      them -- SO4-2 + 9 H+ + 8 e- <=> HS- + 4 H2O, S(6) and S(-2) -- named by
      the species of each state the relation has, the oxidised first. Not the
      water's own, O and H: where it gives way is drawn as itself. The first
      relation between two states names them.
    */
    const couples = [];
    for (const eq of equilibria) {
      if (!eq.net.some(([k]) => species[k].electron)) continue;
      const byState = new Map();
      for (const [k] of eq.net) {
        if (!made[k] || species[k].electron) continue;
        for (const [el, n] of made[k]) {
          if (el === 'H' || el === 'O' || !ELEMENT_SYMBOLS.has(el) || !(n > 0)) continue;
          const s = states[k] && states[k].get(el);
          if (s === undefined) continue;
          if (!byState.has(el)) byState.set(el, new Map());
          const m = byState.get(el);
          if (!m.has(s)) m.set(s, []);
          if (!m.get(s).includes(nameOf[k])) m.get(s).push(nameOf[k]);
        }
      }
      for (const [el, m] of byState) {
        if (m.size !== 2) continue;
        const [hi, lo] = [...m.keys()].sort((a, b) => b - a);
        if (couples.some((c) => c.el === el && c.hi === hi && c.lo === lo)) continue;
        couples.push({ el, hi, lo, ox: m.get(hi), red: m.get(lo), line: eq.line });
      }
    }
    const sulfate = [];
    const carbonate = [];
    for (let k = 0; k < ns; k++) {
      if (where[k] !== 'water' || !made[k]) continue;
      const S = made[k].get('S') || 0;
      const C = made[k].get('C') || 0;
      const O = made[k].get('O') || 0;
      const H = made[k].get('H') || 0;
      if (S > 0 && O >= 4 * S) sulfate.push([k, S]);
      if (C > 0 && O >= 3 * C) {
        const eq = C * Math.min(2, Math.max(0, 2 - H / C));
        if (eq > 0) carbonate.push([k, eq]);
      }
    }
    return { elements: [...byElement].sort(([a], [b]) => a.localeCompare(b)).map(([el, terms]) => ({ el, terms })),
      sulfate, carbonate, couples };
  }

  // The elements that are one valence state in every water: the alkalis, the alkaline earths and fluorine.
  const FIXED_VALENCE = { Li: 1, Na: 1, K: 1, Rb: 1, Cs: 1, Be: 2, Mg: 2, Ca: 2, Sr: 2, Ba: 2, Ra: 2, F: -1 };

  /**
   * Each species' valence state of each element in it but H and O, as
   * PHREEQC's Fe(2) and Fe(3) are: a Map of symbol to state for each
   * species, a state missing where nothing tells it.
   *
   * From the name, where it is a formula with one element left over once H
   * is +1, O -2 -- but nought in H2 and O2 -- and the alkalis, the alkaline
   * earths and fluorine what they always are: that one is what the charge
   * leaves it. Fe(OH)2+ Fe(3), HS- S(-2), NH4+ N(-3), CH4 C(-4); a mean
   * where it is one, S2O3-2 S(2). Then from the relations, again and again
   * while that tells more: a species whose element the others of a relation
   * all have takes what balances them -- a complex its ions' states, Fe+2 +
   * SO4-2 <=> FeSO4 Fe(2) and S(6); a mineral or a species on an exchanger,
   * whose name tells nothing, its ions' -- and where the relation has the
   * electron in it, the electrons it moves are that element's when every
   * other element of the relation is known and balances: Pyrolusite + 4 H+ +
   * 2 e- <=> Mn+2 + 2 H2O, Mn(4). Not a relation with O2 or H2 in it, whose
   * electrons go through the water's own oxygen or hydrogen.
   */
  function valenceStatesOf(species, nameOf, made, where, relations) {
    const ns = species.length;
    const states = species.map(() => null);
    const isEl = (el) => el !== 'H' && el !== 'O' && ELEMENT_SYMBOLS.has(el);
    for (let k = 0; k < ns; k++) {
      if (!made[k] || where[k] === 'mineral') continue;
      const els = [...made[k]];
      const m = new Map();
      states[k] = m;
      // A site's species, CaX2 or Hfo_wOZn+: what it holds is told by its relation.
      if (els.some(([el]) => !ELEMENT_SYMBOLS.has(el))) continue;
      const sp = species[k];
      let rest = sp.z !== null && sp.z !== undefined ? sp.z : chargeOf(nameOf[k]);
      const alone = els.length === 1;
      const unknown = [];
      for (const [el, n] of els) {
        if (el === 'H') rest -= alone ? 0 : n;
        else if (el === 'O') rest += alone ? 0 : 2 * n;
        else if (FIXED_VALENCE[el] !== undefined) { m.set(el, FIXED_VALENCE[el]); rest -= n * FIXED_VALENCE[el]; }
        else unknown.push([el, n]);
      }
      if (unknown.length === 1 && unknown[0][1] > 0) m.set(unknown[0][0], Math.round((rest / unknown[0][1]) * 1e9) / 1e9);
    }
    const stateOf = (k, el) => (states[k] ? states[k].get(el) : undefined);
    // O2 and H2: a relation with either moves electrons through the water's own O or H, which no balance here sees.
    const waterRedox = (k) => {
      const els = made[k] ? [...made[k].keys()] : [];
      return els.length === 1 && (els[0] === 'O' || (els[0] === 'H' && !chargeOf(nameOf[k])));
    };
    for (let pass = 0, moved = true; moved && pass < 20; pass++) {
      moved = false;
      for (const terms of relations) {
        if (terms.some(([k]) => waterRedox(k))) continue;
        const electrons = terms.reduce((s, [k, nu]) => s + (species[k].electron ? nu : 0), 0);
        // How far each element's states balance in the relation, where every species with it is known.
        const balance = (el) => {
          let r = 0;
          for (const [k, nu] of terms) {
            if (!made[k] || !made[k].has(el)) continue;
            const s = stateOf(k, el);
            if (s === undefined) return undefined;
            r += nu * made[k].get(el) * s;
          }
          return r;
        };
        for (const [u, nuU] of terms) {
          if (!made[u] || species[u].electron || !nuU) continue;
          for (const [el, nU] of made[u]) {
            if (!isEl(el) || !(nU > 0) || stateOf(u, el) !== undefined) continue;
            let b = 0;
            let others = 0;
            for (const [k, nu] of terms) {
              if (k === u || !made[k] || !made[k].has(el)) continue;
              const s = stateOf(k, el);
              if (s === undefined) { others = -1; break; }
              b += nu * made[k].get(el) * s;
              others++;
            }
            if (!(others > 0)) continue;
            // The electrons are this element's where every other element of the relation balances on its own.
            let mine = 0;
            if (electrons) {
              let rest = 0;
              const seen = new Set();
              for (const [k] of terms) for (const [e2] of (made[k] || [])) if (isEl(e2) && e2 !== el) seen.add(e2);
              for (const e2 of seen) {
                const r = balance(e2);
                if (r === undefined) { rest = NaN; break; }
                rest += r;
              }
              if (!Number.isFinite(rest)) continue;
              mine = electrons - rest;
            }
            const v = (mine - b) / (nuU * nU);
            if (!Number.isFinite(v)) continue;
            if (!states[u]) states[u] = new Map();
            states[u].set(el, Math.round(v * 1e9) / 1e9);
            moved = true;
          }
        }
      }
    }
    return states;
  }

  /**
   * TEMPERATURE for what is set up before the cells are: the number given,
   * or 25 C where it is an expression, each cell's own then put in place of
   * what depends on it (the temperature in compile).
   */
  function setupTemperature(settings) {
    return typeof settings.TEMPERATURE === 'number' ? settings.TEMPERATURE : 25;
  }

  /**
   * The Debye-Hueckel A, in (kg/mol)^1/2, and B, in (kg/mol)^1/2 per
   * angstrom, of water at tc degrees C and one atmosphere, worked out as
   * PHREEQC 3 works them out: the relative dielectric constant from Bradley
   * and Pitzer (1979, J. Phys. Chem. 83, 1599), the density on the saturation
   * line from Wagner and Pruss (2002, J. Phys. Chem. Ref. Data 31, 387, eq.
   * 2.6) with PHREEQC's fit in pressure on top. At 25 C, 0.5100 and 0.3285.
   * `atm`, the water's pressure, is 1 unless a gas phase at a fixed pressure
   * gives another: PHREEQC then works the water out at that pressure. `aw`,
   * the water's activity, takes the vapour pressure down by Raoult's law, as
   * PHREEQC's calc_rho_0 does with the water it has: 1 unless given (Pitzer
   * gives it, pitzerAt).
   */
  function debyeHuckelAB(tc, atmGiven = 1, aw = 1) {
    return waterAt(waterAtT(tc, atmGiven), aw);
  }

  /**
   * Volts of Eh to one pe at tk kelvin: ln 10 RT/F, with the gas constant
   * and the Faraday constant PHREEQC 3 turns a pe into an Eh with where it
   * prints one, its redox couples' (print.cpp: R_KJ_DEG_MOL 0.00831470,
   * F_KJ_V_EQ 96.4935 in global_structures.h), at the water's own
   * temperature. 0.059156 V at 25 C.
   */
  function ehPerPe(tk) {
    return (Math.LN10 * 0.00831470 * tk) / 96.4935;
  }

  /** What of debyeHuckelAB goes with the temperature and the pressure given alone, kept for waterAt. */
  function waterAtT(tc, atmGiven) {
    const T = tc + 273.15;
    const th = 1 - T / 647.096;
    const rhoSat = 322.0 * (1 + 1.99274064 * th ** (1 / 3) + 1.09965342 * th ** (2 / 3)
      - 0.510839303 * th ** (5 / 3) - 1.75493479 * th ** (16 / 3) - 45.5170352 * th ** (43 / 3)
      - 6.7469445e5 * th ** (110 / 3));
    const p0 = 5.1880000e-02 + tc * (-4.1885519e-04 + tc * (6.6780748e-06 + tc * (-3.6648699e-08 + tc * 8.3501912e-11)));
    const p1 = -6.0251348e-06 + tc * (3.6696407e-07 + tc * (-9.2056269e-09 + tc * (6.7024182e-11 + tc * -1.5947241e-13)));
    const p2 = -2.2983596e-09 + tc * (-4.0133819e-10 + tc * (1.2619821e-11 + tc * (-9.8952363e-14 + tc * 2.3363281e-16)));
    const p3 = 7.0517647e-11 + tc * (6.8566831e-12 + tc * (-2.2829750e-13 + tc * (1.8113313e-15 + tc * -4.2475324e-18)));
    const pSat = Math.exp(11.6702 - 3816.44 / (T - 46.13));
    const d1000 = 3.4279e2 * Math.exp(T * (-5.0866e-3 + T * 9.469e-7));
    const c = -2.0525 + 3.1159e3 / (-1.8289e2 + T);
    const b = -8.0325e3 + 4.2142e6 / T + 2.1417 * T;
    // The dielectric constant at the pressure given, and e^2/(eps k T), as waterAt has them where the water is at it.
    const epsGiven = d1000 + c * Math.log((b + atmGiven * 1.01325) / (b + 1e3));
    return { T, atmGiven, rhoSat, p0, p1, p2, p3, pSat, d1000, c, b, lnSat: Math.log(pSat), lnGiven: Math.log(atmGiven),
      epsGiven, e2Given: 1.671008e-3 / (epsGiven * T) };
  }

  /**
   * debyeHuckelAB from waterAtT's part and the water's activity aw: a few
   * operations. `gasAtm`, a fixed volume of gas's pressure, is the water's,
   * as PHREEQC's patm_x is with a gas phase: its density then at that or
   * the vapour pressure times a(H2O), whichever is higher, its dielectric
   * constant at that pressure (calc_rho_0, calc_dielectrics). With `out`,
   * the result goes into it, the same object each time (sitAt's and
   * pitzerAt's, called at every evaluation).
   */
  function waterAt(w, aw, gasAtm, out) {
    // One atmosphere, or the pressure given, or the vapour pressure (times a(H2O)) where that is higher.
    const pSat = w.pSat * (aw <= 1.0 ? aw : 1);
    const atmRho = Math.max(gasAtm === undefined ? w.atmGiven : gasAtm, pSat);
    const atm = gasAtm === undefined ? atmRho : gasAtm;
    const pa = atmRho - (pSat - 1e-6);
    const spa = Math.sqrt(pa);
    const rho = (w.rhoSat + pa * (w.p0 + pa * (w.p1 + pa * (w.p2 + spa * w.p3)))) / 1e3; // g/cm3
    const given = atm === w.atmGiven;
    const eps = given ? w.epsGiven : w.d1000 + w.c * Math.log((w.b + atm * 1.01325) / (w.b + 1e3));
    const e2 = given ? w.e2Given : 1.671008e-3 / (eps * w.T); // e^2/(eps k T), cm
    const kappa = Math.sqrt(8 * 3.14159265358979 * 6.02252e23 * e2 * rho / 1e3); // 1/cm (mol/kg)^-1/2
    /*
      How A and B go with ln a(H2O): the density through the vapour
      pressure below the pressure it is at, and on the vapour pressure the
      dielectric constant through the pressure. A goes as rho^1/2 eps^-3/2,
      B as rho^1/2 eps^-1/2.
    */
    let dlnRho = 0;
    let dlnEps = 0;
    let dAtm = 0;
    if (aw <= 1) {
      if (atmRho > pSat) {
        dlnRho = (-pSat * (w.p0 + pa * (2 * w.p1 + pa * (3 * w.p2 + spa * 3.5 * w.p3)))) / 1e3 / rho;
      }
      if (gasAtm === undefined && atm === pSat && pSat > w.atmGiven) {
        dlnEps = (w.c * 1.01325 * pSat) / (w.b + atm * 1.01325) / eps;
        dAtm = atm;
      }
    }
    // A0: Pitzer's A_phi, PHREEQC's DH_B e2_DkT/6; atm the pressure the water is then at.
    const r = out || {};
    r.A = kappa * e2 / (2 * Math.LN10);
    r.B = kappa / 1e8;
    r.eps = eps;
    r.A0 = (kappa * e2) / 6.0;
    r.atm = atm;
    r.rho = rho;
    r.pa = pa;
    r.e2 = e2;
    r.kappa = kappa;
    r.dlnA = 0.5 * dlnRho - 1.5 * dlnEps;
    r.dlnB = 0.5 * dlnRho - 0.5 * dlnEps;
    r.dlnRho = dlnRho;
    r.pSat = pSat;
    // d atm/d ln a(H2O): on the vapour pressure, the pressure itself.
    r.dAtm = dAtm;
    return r;
  }

  /**
   * Which of waterAt's pieces (no gas phase) the water is on at ln a(H2O) =
   * L: a(H2O) above 1 or not, and the pressure given above the vapour
   * pressure times a(H2O), below it or on it -- in logarithms, which can
   * put a water within a rounding of a corner on its other side. Between
   * two a(H2O) on the same piece A and B are smooth.
   */
  function waterSide(w, L) {
    const lnSat = w.lnSat + (L <= 0 ? L : 0);
    return (L <= 0 ? 0 : 3) + (w.lnGiven > lnSat ? 1 : w.lnGiven < lnSat ? 2 : 0);
  }

  /**
   * What the molar volumes read of the water at waterAt's state `ws`
   * (calc_rho_0 and calc_dielectrics): its compressibility kappa_0, 1/atm;
   * the Debye-Hueckel slope of the volume, Av, cm3/mol (mol/kg)^-1/2; the
   * Born function's QBrn; and the water's own molar volume, cm3/mol.
   */
  function waterVolume(w, ws) {
    const pa = ws.pa;
    const kappa0 = (w.p0 + pa * (2 * w.p1 + pa * (3 * w.p2 + Math.sqrt(pa) * 3.5 * w.p3))) / (ws.rho * 1e3);
    const pb = ws.atm * 1.01325;
    const Av = ws.kappa * ws.e2 * R_LITER_ATM * 1e3 * w.T * (((w.c / (w.b + pb)) * 1.01325) / ws.eps - kappa0 / 3);
    const QBrn = (w.c / (w.b + pb) / ws.eps / ws.eps) * 41.84004;
    const Vw = 18.016 / ws.rho;
    // Their derivatives in ln a(H2O) through the density, where the water is above its vapour pressure (waterAt).
    let dAv = 0;
    let dVw = 0;
    if (ws.dlnRho) {
      const gp = 2 * w.p1 + pa * (6 * w.p2 + 8.75 * Math.sqrt(pa) * w.p3);
      const dk0 = (gp * -ws.pSat) / (ws.rho * 1e3) - kappa0 * ws.dlnRho;
      dAv = Av * 0.5 * ws.dlnRho - (ws.kappa * ws.e2 * R_LITER_ATM * 1e3 * w.T * dk0) / 3;
      dVw = -Vw * ws.dlnRho;
    }
    return { Av, QBrn, Vw, pbS: 2600 + ws.atm * 1.01325, TKs: w.T - 273.15 + 45.15, dAv, dVw };
  }

  /**
   * <CONDUCTANCE>: what PHREEQC works a water's specific conductance, its
   * density and its viscosity out from, a solute to a line:
   *
   *   Na+   gfw 22.9898  dw 1.33e-9 75 3.627 0 0.7037  viscosity 0.1387 -8.66e-2 1.25e-2 1.45e-2 7.5e-3 1.062
   *   H2O   gfw 18.016
   *   Cl-   vm 4.465 4.801 4.325 -2.847 1.748 0 -0.331 20.16 0 1
   *
   * gfw, the gram formula weight, every solute's (and H2O's, 18.016 unless
   * given); dw, PHREEQC's -dw -- Dw, dw_t, dw_a, dw_a2, dw_a_visc, dw_a3,
   * dw_a_v_dif; viscosity, its -viscosity -- the Jones-Dole b0 to b2, d1 to
   * d3, the anion's factor and the B and D at 25 C. Cl-'s vm, its -Vm, only
   * where Cl- is no species: the viscosity takes the other anions' volumes
   * against Cl-'s (calc_vm_Cl). Read with ACTIVITY, the ionic strength's.
   */
  function readConductance(lines, species, act) {
    if (!lines.length) return null;
    const head = lines[0].line;
    if (!act || act.kind === 'none') {
      throw new RtmError('<CONDUCTANCE> works the conductance, the density and the viscosity out at the water\'s ionic strength '
        + 'and its activity coefficients: it is read with ACTIVITY.', head);
    }
    if (act.llnl) {
      throw new RtmError('<CONDUCTANCE> is not read under ACTIVITY = llnl: PHREEQC works out no molar volumes under LLNL\'s '
        + 'activity model, which the density needs.', head);
    }
    const ns = species.length;
    const index = new Map(species.map((sp, k) => [sp.name, k]));
    const out = { gfw: new Float64Array(ns), dw: new Array(ns).fill(null), jd: new Array(ns).fill(null), gfwW: 18.016,
      clVm: null, falk: false, anyVisc: false };
    const seen = new Map();
    const LEN = { gfw: [1, 1], dw: [1, 7], viscosity: [1, 10], vm: [1, 10] };
    for (const { text, line } of lines) {
      const tokens = text.split(/\s+/).filter(Boolean);
      const name = tokens.shift();
      if (seen.has(name)) throw new RtmError(`${name} is given twice in <CONDUCTANCE>, on lines ${seen.get(name)} and ${line}.`, line);
      seen.set(name, line);
      const groups = {};
      let cur = null;
      for (const tok of tokens) {
        const key = tok.toLowerCase();
        if (LEN[key]) {
          if (groups[key]) throw new RtmError(`${name} in <CONDUCTANCE> gives ${key} twice.`, line);
          groups[key] = [];
          cur = key;
          continue;
        }
        const v = Number(tok);
        if (!cur || !Number.isFinite(v)) {
          throw new RtmError(`"${text}" in <CONDUCTANCE>: a solute, then gfw, dw and viscosity, each with its numbers -- `
            + `"${tok}" is ${cur ? 'no number' : 'not one of them'}.`, line);
        }
        groups[cur].push(v);
      }
      for (const [key, v] of Object.entries(groups)) {
        const [lo, hi] = LEN[key];
        if (v.length < lo || v.length > hi) {
          throw new RtmError(`${name} in <CONDUCTANCE>: ${key} takes ${lo === hi ? lo : `${lo} to ${hi}`} number`
            + `${hi === 1 ? '' : 's'}, not ${v.length}.`, line);
        }
      }
      if (name === 'H2O') {
        if (Object.keys(groups).some((g) => g !== 'gfw')) throw new RtmError('H2O in <CONDUCTANCE> takes its gfw alone.', line);
        if (groups.gfw) out.gfwW = groups.gfw[0];
        continue;
      }
      const k = index.has(name) ? index.get(name) : -1;
      if (k < 0) {
        if (name === 'Cl-' && groups.vm && Object.keys(groups).length === 1) {
          // In PHREEQC's units, as <VOLUMES> reads a -Vm: a1..a4 and W to cm3/mol, i4 1 unless given.
          const q = Float64Array.from({ length: 10 }, (_, i) => groups.vm[i] || 0);
          if (groups.vm.length < 10) q[9] = 1;
          q[0] *= 41.84004e-1;
          q[1] *= 41.84004e2;
          q[2] *= 41.84004;
          q[3] *= 41.84004e4;
          q[4] *= 1e5;
          out.clVm = q;
          continue;
        }
        throw new RtmError(`${name} in <CONDUCTANCE> is no species; only Cl- may be given without being one, with its vm.`, line);
      }
      if (!act.solute[k]) {
        throw new RtmError(`${name} in <CONDUCTANCE> is not dissolved in the water: the conductance is the solutes'.`, line);
      }
      if (groups.vm) throw new RtmError(`${name} in <CONDUCTANCE>: a solute's molar volume is in <VOLUMES>.`, line);
      if (groups.gfw) {
        if (!(groups.gfw[0] > 0)) throw new RtmError(`${name} in <CONDUCTANCE>: gfw is above zero.`, line);
        out.gfw[k] = groups.gfw[0];
      }
      if (groups.dw) out.dw[k] = Float64Array.from({ length: 7 }, (_, i) => groups.dw[i] || 0);
      if (groups.viscosity) {
        out.jd[k] = Float64Array.from({ length: 10 }, (_, i) => groups.viscosity[i] || 0);
        out.anyVisc = true;
      }
    }
    const missing = species.map((sp, k) => (act.solute[k] && sp.name !== 'H2O' && !sp.electron && !(out.gfw[k] > 0) ? sp.name : null))
      .filter(Boolean);
    if (missing.length) {
      throw new RtmError(`<CONDUCTANCE> gives no gfw for ${missing.slice(0, 5).join(', ')}${missing.length > 5 ? ` and ${missing.length - 5} `
        + 'more' : ''}: the density is every solute's mass.`, head);
    }
    // PHREEQC's choice of how: Falkenhagen and Debye-Onsager where H+'s dw_a3 is above 24, its older equation else.
    const h = index.has('H+') ? out.dw[index.get('H+')] : null;
    out.falk = !!(h && h[5] > 24);
    return out;
  }

  // Pure water's viscosity at 25 C, mPa s (viscosity(), Huber et al. 2009), and constants PHREEQC uses (global_structures.h).
  const VISC0_25 = 0.8900239182946;
  const F_C_MOL = 96493.5;
  const AVOGADRO = 6.02252e23;

  /** Pure water's viscosity, mPa s, at T kelvin and density rho g/cm3: Huber et al. (2009), as PHREEQC's viscosity() has it. */
  function waterViscosity(T, rho) {
    const H = [1.67752, 2.20462, 0.6366564, -0.241605];
    const Tb = T / 647.096;
    let denom = H[0];
    for (let i = 1; i < 4; i++) denom += H[i] / Tb ** i;
    const mu0 = (100 * Math.sqrt(Tb)) / denom;
    const H2 = [5.20094e-1, 2.22531e-1, -2.81378e-1, 1.61913e-1, -3.25372e-2, 0, 0,
      8.50895e-2, 9.99115e-1, -9.06851e-1, 2.57399e-1, 0, 0, 0,
      -1.08374, 1.88797, -7.72479e-1, 0, 0, 0, 0,
      -2.89555e-1, 1.26613, -4.89837e-1, 0, 6.98452e-2, 0, -4.35673e-3,
      0, 0, -2.57040e-1, 0, 0, 8.72102e-3, 0,
      0, 1.20573e-1, 0, 0, 0, 0, -5.93264e-4];
    const Rb = rho / 0.322;
    const Tb1 = 1 / Tb - 1;
    const Rb1 = Rb - 1;
    let S1 = 0;
    for (let i = 0; i < 6; i++) {
      let S2 = 0;
      for (let j = 0; j < 7; j++) {
        const h = H2[7 * i + j];
        if (!h) continue;
        S2 += j ? h * Rb1 ** j : h;
      }
      S1 += i ? S2 * Tb1 ** i : S2;
    }
    return (mu0 * Math.exp(Rb * S1)) / 1e3;
  }

  /**
   * A water's density, viscosity and specific conductance, as PHREEQC works
   * them out (calc_dens, viscosity, calc_SC): c the molalities from `b`,
   * `cond` <CONDUCTANCE>, I the ionic strength, `ws` the water (waterAt),
   * `wv` its volumes' constants (waterVolume), vm each solute's molar
   * volume at I (molarVolumesAt; 0 for one <VOLUMES> does not give), `q`
   * <VOLUMES>' numbers for calc_vm0, solutes and their charges, `names`.
   * Returns { rho (kg/L), visc and visc0 (mPa s), SC (uS/cm), vol (L to a kg of water) }.
   */
  function waterProperties({ c, b, cond, I, T, ws, wv, vm, vol, solutes, z, names, iCl }) {
    const sqrtMu = Math.sqrt(I);
    const visc0 = waterViscosity(T, ws.rho);
    const tc = T - 273.15;
    const lmOf = (k) => (c[b + k] > 0 ? Math.log10(c[b + k]) : -Infinity);
    // The volume at no ionic strength and one atmosphere, but the water's Born and Av: PHREEQC's calc_vm0.
    const vm0 = (k) => {
      if (!vol || vol.kind[k] !== 0 || !wv) return 0;
      const q = vol.q[k];
      if (!q[0]) return 0;
      const pb = 2600 + 1.01325;
      let g = q[0] + q[1] / pb + (q[2] + q[3] / pb) / wv.TKs - q[4] * wv.QBrn;
      if (z[k] && (q[6] !== 0 || q[7] !== 0 || q[8] !== 0)) {
        const bi = q[6] + q[7] / wv.TKs + q[8] * wv.TKs;
        g += q[9] === 1 ? 0 : bi * 0 ** q[9];
      }
      return g;
    };
    // Cl-'s molar volume where it is not among the solutes the viscosity counts: PHREEQC's calc_vm_Cl.
    const vmCl = () => {
      if (iCl >= 0) return vm[iCl];
      const q = cond.clVm;
      if (!q || !wv || !q[0]) return 0;
      let v = q[0] + q[1] / wv.pbS + (q[2] + q[3] / wv.pbS) / wv.TKs - q[4] * wv.QBrn;
      v += q[5] < 1e-5 ? 0.5 * wv.Av * sqrtMu : (0.5 * wv.Av * sqrtMu) / (1 + q[5] * ws.B * sqrtMu);
      if (q[6] !== 0 || q[7] !== 0 || q[8] !== 0) {
        const bi = q[6] + q[7] / wv.TKs + q[8] * wv.TKs;
        v += q[9] === 1 ? bi * I : bi * I ** q[9];
      }
      return v;
    };
    // THE VISCOSITY: Jones and Dole, A from Falkenhagen and Dole, the anions against Cl- (viscosity(), no surface).
    let visc = visc0;
    if (cond.anyVisc) {
      const tcv = tc > 200 ? 200 : tc;
      let Bc = 0;
      let Dc = 0;
      let mPlus = 0;
      let mMin = 0;
      let eqPlus = 0;
      let eqMin = 0;
      let eqDwPlus = 0;
      let eqDwMin = 0;
      let Van = 0;
      let mAn = 0;
      let VCl = 0;
      for (const k of solutes) {
        if (lmOf(k) < -9) continue;
        const m = c[b + k];
        const jd = cond.jd[k];
        // As PHREEQC asks it, of b0, b1 and d1 as given; below 1e-9 mol/kgw a species counts in nothing here.
        if (jd && (jd[0] || jd[1] || jd[3])) {
          if (m < 1e-9) continue;
          const lz = Math.abs(z[k]);
          const fz = lz ? (lz * lz + lz) / 2 : I / m;
          // The 25 C B and D put in, as PHREEQC puts them into b0 and d1.
          const b0 = jd[7] || jd[8] ? jd[7] - jd[1] * Math.exp(-jd[2] * 25) : jd[0];
          const d1 = jd[7] || jd[8] ? jd[8] / Math.exp(-jd[4] * 25) : jd[3];
          Bc += (b0 + jd[1] * Math.exp(-jd[2] * tcv)) * m;
          const t2 = jd[5] >= 1 ? I / 3 / jd[5] : jd[5] > 0.4 ? -0.8 / jd[5] : -1;
          let t3 = d1 * Math.exp(-jd[4] * tcv) * m * ((I ** jd[5]) * (1 + t2) + (m * fz) ** jd[5]) / (2 + t2);
          if (t3 < -1e-5) t3 = 0;
          Dc += t3;
        }
        if (!z[k]) {
          if (jd && jd[6]) { Van += vm[k] * jd[6] * m; mAn += m; }
          continue;
        }
        const dw = cond.dw[k];
        let Dw = dw ? dw[0] : 0;
        if (!Dw) continue;
        Dw *= VISC0_25 / visc0;
        if (dw[1]) Dw *= Math.exp(dw[1] / T - dw[1] / 298.15);
        if (z[k] < 0) {
          if (names[k] === 'Cl-') { VCl = vm[k]; Van += VCl * m; mAn += m; } else if (jd && jd[6]) { Van += vm[k] * jd[6] * m; mAn += m; }
          mMin += m;
          eqMin -= m * z[k];
          eqDwMin -= (m * z[k]) / Dw;
        } else {
          mPlus += m;
          eqPlus += m * z[k];
          eqDwPlus += (m * z[k]) / Dw;
        }
      }
      let A = 0;
      if (mPlus && mMin && eqDwPlus && eqDwMin) {
        const z1 = eqPlus / mPlus;
        const z2 = eqMin / mMin;
        const D1 = eqPlus / eqDwPlus;
        const D2 = eqMin / eqDwMin;
        const t1 = (D1 - D2) / (Math.sqrt(D1 * z1 + D2 * z2) + Math.sqrt((D1 + D2) * (z1 + z2)));
        const psi = (D1 * z2 + D2 * z1) / 4 - z1 * z2 * t1 * t1;
        A = ((4.3787e-14 * T ** 1.5) / (Math.sqrt((ws.eps * (z1 + z2)) / Math.max(z1, z2)) * (D1 * D2))) * psi;
      }
      visc = visc0 + A * Math.sqrt((eqPlus + eqMin) / 2);
      if (mAn) Van /= mAn;
      if (!VCl) VCl = vmCl();
      const fan = Van && VCl ? 2 - Van / VCl : 1;
      visc += visc0 * fan * (Bc + (Dc < 0 ? 0 : Dc));
      if (visc < 0) visc = visc0;
    }
    // THE DENSITY, and the volume of a kilogram of water's solution, L (calc_dens).
    let MT = 0;
    let Vs = 0;
    for (const k of solutes) { MT += c[b + k] * cond.gfw[k]; Vs += c[b + k] * vm[k]; }
    const rho0 = ws.rho;
    const rho = MT > 0 ? (rho0 * (1e3 + MT)) / (rho0 * Vs + 1e3) : rho0;
    const volume = (1 + 1e-3 * MT) / rho;
    // THE SPECIFIC CONDUCTANCE, uS/cm (calc_SC).
    let SC = 0;
    const dwOf = (k) => {
      const dw = cond.dw[k];
      let Dw = dw ? dw[0] : 0;
      if (!Dw) return 0;
      if (T !== 298.15 && dw[1]) Dw *= Math.exp(dw[1] / T - dw[1] / 298.15);
      return (Dw * VISC0_25) / visc0;
    };
    if (!cond.falk) {
      for (const k of solutes) {
        if (lmOf(k) < -30) continue;
        let Dw = dwOf(k);
        const lz = Math.abs(z[k]);
        if (!Dw || !lz) continue;
        const dw = cond.dw[k];
        const a = dw[2] || 1.6;
        const a2 = dw[3] || 4.73;
        const av = cond.anyVisc ? (dw[4] ? (visc0 / visc) ** dw[4] : 1) : 1;
        const a3 = cond.anyVisc ? (dw[5] ? I ** dw[5] : dw[4] ? 1 : I ** 0.75) : (dw[5] ? I ** dw[5] : I ** 0.75);
        const ka = (ws.B * a2 * sqrtMu) / (1 + a3);
        Dw *= av * Math.exp((-a * ws.A * lz * sqrtMu) / (1 + ka));
        SC += c[b + k] * lz * lz * Dw;
      }
      SC *= (1e7 * F_C_MOL * F_C_MOL) / (R_KJ * 298150.0);
      return { rho, visc, visc0, SC, vol: volume };
    }
    let mPlus = 0;
    let mMin = 0;
    let eqPlus = 0;
    let eqMin = 0;
    let eqDwPlus = 0;
    let eqDwMin = 0;
    const dwc = new Float64Array(z.length);
    for (const k of solutes) {
      if (lmOf(k) < -30) continue;
      const Dw = dwOf(k);
      if (!Dw) continue;
      dwc[k] = Dw;
      if (!z[k]) continue;
      const m = c[b + k];
      if (z[k] > 0) { mPlus += m; eqPlus += m * z[k]; eqDwPlus += m * z[k] * Dw; } else {
        mMin += m;
        eqMin -= m * z[k];
        eqDwMin -= m * z[k] * Dw;
      }
    }
    if (!(mPlus > 0 && mMin > 0)) return { rho, visc, visc0, SC: 0, vol: volume };
    const zPlus = eqPlus / mPlus;
    const zMin = eqMin / mMin;
    const tr = (eqDwPlus / mPlus) / (eqDwPlus / mPlus + eqDwMin / mMin);
    const q = 1 / ((tr / zPlus + (1 - tr) / zMin) * (zMin + zPlus));
    const sqrtQ = Math.sqrt(q);
    const e2 = (1.60218e-19 * 1.60218e-19) / (6 * Math.PI);
    const B1 = ((e2 / (2 * 8.8542e-12 * ws.eps * 1.38066e-23 * T)) * q) / (1 + sqrtQ) * ws.B * 1e10 * zPlus * zMin;
    const B2 = ((e2 * AVOGADRO) / visc0) * ws.B * 1e17;
    const muMin = 3 * mMin * (zMin - 1) + mMin;
    const muPlus = 3 * mPlus * (zPlus - 1) + mPlus;
    const DwSC = (1e4 * F_C_MOL * F_C_MOL) / (R_KJ * 298.15e3);
    const llSC = ((0.5e3 * (eqPlus + eqMin)) / volume) / volume;
    for (const k of solutes) {
      const zk = z[k];
      if (!zk || lmOf(k) < -30) continue;
      let Dw = dwc[k];
      if (!Dw) continue;
      const lz = Math.abs(zk);
      const dw = cond.dw[k];
      let a3 = dw[5];
      const m = c[b + k];
      if (a3 !== 0 && a3 > -5.01 && a3 < 4.99) {
        const a = dw[2] || 1.6;
        const a2 = dw[3] || 4.73;
        const av = cond.anyVisc ? (dw[4] ? (visc0 / visc) ** dw[4] : 1) : 1;
        const ka = (ws.B * a2 * sqrtMu) / (1 + I ** a3);
        Dw *= av * Math.exp((-a * ws.A * lz * sqrtMu) / (1 + ka));
        SC += m * lz * lz * Dw * 1e3 * DwSC;
        continue;
      }
      if (!a3) a3 = 10;
      let a = dw[2] || 3.5;
      let a2 = dw[3];
      const av = dw[4];
      if (zk < -0.5) {
        const t = zPlus - 1;
        a -= 0.126 * lz * t;
        a2 += 0.126 * lz * t;
      }
      Dw *= DwSC * lz;
      let t1;
      if (!a2) t1 = 1;
      else if (names[k] === 'H+') t1 = (1 + I) ** a2;
      else {
        t1 = 1 + (vm[k] - vm0(k));
        if (t1 > 0) t1 **= a2;
        if (t1 < 1) t1 = 1;
      }
      const ka = a3 >= 5 ? ws.B * a * t1 * sqrtMu : ws.B * a * I ** a2;
      let ll = (Dw - (B2 * lz * sqrtMu) / (1 + ka)) * (1 - (B1 * sqrtMu) / ((1 + ka) * (1 + ka)));
      if (av) ll *= (visc0 / visc) ** av;
      const half = 2 / (eqPlus + eqMin);
      const share = zk > 0 ? muPlus / (eqPlus * half) : muMin / (eqMin * half);
      SC += ((ll * m * lz * lz) / share) * llSC;
    }
    return { rho, visc, visc0, SC, vol: volume };
  }

  /**
   * <VOLUMES>: the molar volumes PHREEQC corrects each log K for the
   * pressure with, a species to a line, in cm3/mol:
   *
   *   Na+      1.403  -2.285  4.419  -2.726  -5.125e-5  4  0.162  47.67  -3.09e-3  0.725
   *   Mg+2     millero  -1.41  0.0213  0  0.85  0  0
   *   Calcite  36.9
   *
   * A solute takes PHREEQC's -Vm, up to ten numbers, a1 to a4, W, b and i1
   * to i4, in its units (calc_vm):
   *
   *   V = 41.84 (0.1 a1 + 100 a2/(2600 + p) + (a3 + 1e4 a4/(2600 + p))/(T - 228))
   *       - 1e5 W QBrn + z^2 Av/2 sqrt(I)/(1 + b B sqrt(I))
   *       + (i1 + i2/(T - 228) + i3 (T - 228)) I^i4,
   *
   * p the pressure in bar, T in kelvin, Av and QBrn the water's, the I terms
   * an ion's alone and i4 1 unless given; or `millero` and PHREEQC's -Millero,
   * up to six numbers: V = m1 + m2 t + m3 t^2 and, for an ion, z^2 Av/2
   * sqrt(I) + (m4 + m5 t + m6 t^2) I, t in C. A mineral, a gas or a phase of
   * <PHASES> takes one number, its molar volume. The water's own is 18.016/rho.
   * Returns { vol: species index -> its entry, phases: name -> volume, for
   * <PHASES> (compile) }, or null without the section.
   */
  function readVolumes(lines, species, act, settings) {
    if (!lines.length) return null;
    const head = lines[0].line;
    if (!act) {
      throw new RtmError('<VOLUMES> corrects each log K for the pressure with the molar volumes, which go with the ionic '
        + 'strength and the water: it is read with ACTIVITY.', head);
    }
    if (act.llnl) {
      throw new RtmError('<VOLUMES> is not read under ACTIVITY = llnl: PHREEQC works out no molar volumes under LLNL\'s '
        + 'activity model, and its log K go with the temperature alone.', head);
    }
    const index = new Map(species.map((sp, s) => [sp.name, s]));
    const vol = new Map();
    const phases = new Map();
    const seen = new Map();
    for (const { text, line } of lines) {
      const parts = text.split(/\s+/).filter(Boolean);
      const name = parts.shift();
      if (seen.has(name)) throw new RtmError(`${name} is given twice in <VOLUMES>, on lines ${seen.get(name)} and ${line}.`, line);
      seen.set(name, line);
      const millero = parts.length && parts[0].toLowerCase() === 'millero';
      if (millero) parts.shift();
      const v = parts.map(Number);
      const bad = parts.find((x, i) => !Number.isFinite(v[i]));
      if (bad !== undefined || !v.length) {
        throw new RtmError(`"${text}" in <VOLUMES>: ${bad !== undefined ? `"${bad}" is no number` : 'a species and its '
          + 'molar volume, or the numbers it is worked out from'}.`, line);
      }
      if (name === 'H2O') {
        throw new RtmError('H2O in <VOLUMES>: the water\'s molar volume is its own, 18.016 g/mol over its density at the '
          + 'temperature and pressure.', line);
      }
      const s = index.has(name) ? index.get(name) : -1;
      const sp = s >= 0 ? species[s] : null;
      if (!sp || sp.mineral || sp.gas) {
        // A mineral, a gas, or a phase of <PHASES>: its molar volume, cm3/mol.
        if (millero || v.length > 1) {
          throw new RtmError(`${name} in <VOLUMES> is ${sp ? (sp.mineral ? 'a mineral' : 'a gas') : 'no species'}: `
            + `${sp ? 'it takes one number, its molar volume in cm3/mol' : 'a phase of <PHASES> takes one number, its '
              + 'molar volume in cm3/mol, and a solute is in <SPECIES>'}.`, line);
        }
        if (sp) vol.set(s, { kind: 2, v: v[0] }); else phases.set(name, { v: v[0], line });
        continue;
      }
      if (sp.electron || sp.exchange || sp.exchanger || sp.surface || sp.potential || !act.solute[s]) {
        throw new RtmError(`${name} in <VOLUMES> is ${sp.electron ? 'the electron' : 'on an exchanger or a surface, or one'}: `
          + 'PHREEQC works out a molar volume for a solute, a mineral and a gas, and no other.', line);
      }
      if (v.length > (millero ? 6 : 10)) {
        throw new RtmError(`${name} in <VOLUMES> has ${v.length} numbers: ${millero ? 'millero takes up to six, PHREEQC\'s '
          + '-Millero' : 'up to ten, PHREEQC\'s -Vm: a1 to a4, W, b and i1 to i4; or millero and up to six'}.`, line);
      }
      if (millero) {
        const m = new Float64Array(6);
        v.forEach((x, i) => { m[i] = x; });
        if (!m[0]) {
          throw new RtmError(`${name} in <VOLUMES>: PHREEQC reads a Millero volume whose first number is not 0, and none `
            + 'that is.', line);
        }
        vol.set(s, { kind: 1, m });
        continue;
      }
      // PHREEQC's units (read_aq_species_vm_parms): a1..a4 and W to cm3/mol; i4 1 unless given.
      const q = new Float64Array(10);
      v.forEach((x, i) => { q[i] = x; });
      if (v.length < 10) q[9] = 1;
      if (!q[0]) {
        throw new RtmError(`${name} in <VOLUMES>: PHREEQC works a volume out from a1, the first number, where it is not 0, and `
          + 'reads none where it is.', line);
      }
      q[0] *= 41.84004e-1;
      q[1] *= 41.84004e2;
      q[2] *= 41.84004;
      q[3] *= 41.84004e4;
      q[4] *= 1e5;
      vol.set(s, { kind: 0, q });
    }
    const ns = species.length;
    const out = { kind: new Int8Array(ns).fill(-1), q: [], m: [], vm0: new Float64Array(ns), list: [], phases,
      h2o: index.has('H2O') ? index.get('H2O') : -1, pv: new Float64Array(ns), pvI: new Float64Array(ns),
      pvA: new Float64Array(ns), V: new Float64Array(ns), VI: new Float64Array(ns), VA: new Float64Array(ns) };
    for (const [s, e] of vol) {
      out.kind[s] = e.kind;
      if (e.kind === 0) out.q[s] = e.q; else if (e.kind === 1) out.m[s] = e.m; else out.vm0[s] = e.v;
      out.list.push(s);
    }
    out.list.sort((x, y) => x - y);
    // Where nothing takes the water above one atmosphere, the volumes correct nothing: PHREEQC's rule.
    const P = act.wt ? act.wt.atmGiven : 1;
    if (!(P > 1) && typeof settings.TEMPERATURE === 'number' && settings.TEMPERATURE < 99.6) {
      out.idle = true;
    }
    return out;
  }

  /**
   * The molar volumes of a cell at ionic strength I and water activity aw,
   * into `water` (an activityAt result): pv[s] = f V_s and pvI[s] its
   * derivative in I, pvW the water's f V, f = (P - 1 atm)/(R T) in mol/cm3
   * with P the water's pressure (waterAt: the pressure given, or the vapour
   * pressure times a(H2O) where that is higher), and pvL, d ln f/d ln a(H2O)
   * where the vapour pressure is the water's. Each relation's ln K is then
   * less sum nu f V, PHREEQC's k_calc; at or below one atmosphere nothing.
   */
  function volumesAt(act, water, I, low, cell) {
    const vo = act.vol;
    const wt = act.wtc ? act.wtc[cell] : act.wt;
    const aw = Math.exp(water.lnAw);
    const ws = waterAt(wt, aw);
    const P = ws.atm;
    if (!(P > 1)) { water.pv = null; return; }
    const f = (1e-9 * (P * 101325 - 101325)) / (R_KJ * wt.T);
    const wv = molarVolumesAt(act, I, low, wt, ws);
    const { pv, pvI, pvA, V, VI, VA } = vo;
    // Where the water is at its vapour pressure times a(H2O), f goes with a(H2O): d ln f/d ln a = P/(P - 1).
    const L = P > wt.atmGiven && aw <= 1 ? P / (P - 1) : 0;
    for (const s of vo.list) {
      pv[s] = f * V[s];
      pvI[s] = f * VI[s];
      pvA[s] = f * (VA[s] + L * V[s]);
    }
    if (vo.h2o >= 0) { pv[vo.h2o] = f * wv.Vw; pvI[vo.h2o] = 0; pvA[vo.h2o] = f * (wv.dVw + L * wv.Vw); }
    water.pv = pv;
    water.pvI = pvI;
    water.pvA = pvA;
    water.pvW = f * wv.Vw;
    water.pvWA = f * (wv.dVw + L * wv.Vw);
    water.pf = f;
    water.pvL = L;
  }

  /**
   * Each species' molar volume, cm3/mol, into act.vol.V, and its derivative
   * in I into VI, at ionic strength I and the water `ws` (waterAt of the
   * cell's `wt`), PHREEQC's calc_vm; returns the water's own, 18.016/rho.
   */
  function molarVolumesAt(act, I, low, wt, ws) {
    const vo = act.vol;
    const wv = waterVolume(wt, ws);
    const { V, VI, VA } = vo;
    const sq = Math.sqrt(I);
    const tc = wt.T - 273.15;
    for (const s of vo.list) {
      const kind = vo.kind[s];
      VA[s] = 0;
      if (kind === 2) { V[s] = vo.vm0[s]; VI[s] = 0; continue; }
      const z = act.z[s];
      let v;
      let dv = 0;
      if (kind === 0) {
        const q = vo.q[s];
        v = q[0] + q[1] / wv.pbS + (q[2] + q[3] / wv.pbS) / wv.TKs - q[4] * wv.QBrn;
        if (z) {
          const h = z * z * 0.5 * wv.Av;
          if (q[5] < 1e-5) {
            v += h * sq;
            dv += (h * 0.5) / sq;
            VA[s] = z * z * 0.5 * wv.dAv * sq;
          } else {
            const den = 1 + q[5] * ws.B * sq;
            v += (h * sq) / den;
            dv += (h * 0.5) / (sq * den * den);
            // Av and B through the density: d ln B = d ln rho/2 there.
            VA[s] = (z * z * 0.5 * wv.dAv * sq) / den - ((h * sq) / den) * ((q[5] * ws.B * sq) / den) * 0.5 * ws.dlnRho;
          }
          if (q[6] !== 0 || q[7] !== 0 || q[8] !== 0) {
            const bi = q[6] + q[7] / wv.TKs + q[8] * wv.TKs;
            if (q[9] === 1) { v += bi * I; dv += bi; } else {
              v += bi * I ** q[9];
              dv += bi * q[9] * I ** (q[9] - 1);
            }
          }
        }
      } else {
        const m = vo.m[s];
        v = m[0] + tc * (m[1] + tc * m[2]);
        if (z) {
          const h = z * z * 0.5 * wv.Av;
          const bi = m[3] + tc * (m[4] + tc * m[5]);
          v += h * sq + bi * I;
          dv += (h * 0.5) / sq + bi;
          VA[s] = z * z * 0.5 * wv.dAv * sq;
        }
      }
      V[s] = v;
      // Below I = 1e-10, where I is held there, nothing goes with it.
      VI[s] = low ? 0 : dv;
    }
    return wv;
  }

  /**
   * Each species' molar volume in the cell at `off` of C, cm3/mol (0 for one
   * <VOLUMES> does not give), the water's, its pressure in atm and the
   * activityAt evaluation they are at: what PHREEQC's VM() gives.
   */
  function molarVolumes(act, C, off = 0, cell = 0) {
    const ns = act.ns;
    const w = activityAt(act, C, off, new Float64Array(ns), new Float64Array(ns), cell);
    const wt = act.wtc ? act.wtc[cell] : act.wt;
    const ws = waterAt(wt, Math.exp(w.lnAw));
    act.vol.V.fill(0);
    const wv = molarVolumesAt(act, w.I, !(w.I > 1e-10), wt, ws);
    return { V: Float64Array.from(act.vol.V), VI: Float64Array.from(act.vol.VI), Vw: wv.Vw, P: ws.atm, water: w };
  }

  /** d(pressureTerm)/dI of a relation, through its ions' volumes. */
  function pressureTermI(eq, water) {
    if (!water || !water.pv) return 0;
    const pvI = water.pvI;
    let t = 0;
    for (const [s, nu] of eq.net) t += nu * pvI[s];
    return t;
  }

  /**
   * ln K at the pressure of a relation or a phase in a cell, from its own
   * there (lnKIn) and an activityAt evaluation `water` of the cell.
   */
  function lnKAtP(eq, cell, water) {
    const k = eq.lnKc ? eq.lnKc[cell] : eq.lnK;
    return water && water.pv ? k - pressureTerm(eq, water) : k;
  }

  /**
   * A relation's coefficient on ln a(H2O) in its Jacobian row: its water's,
   * and where the water is at its vapour pressure, its pressure term's.
   */
  function waterCoef(eq, water) {
    let w = eq.water || 0;
    if (!water) return w;
    // The volumes' correction for the pressure: through the density, and on the vapour pressure through f.
    if (water.pv) {
      const pvA = water.pvA;
      let t = eq.water ? eq.water * water.pvWA : 0;
      for (const [s, nu] of eq.net) t += nu * pvA[s];
      if (eq.vm0) t -= eq.c0 * eq.vm0 * water.pf * water.pvL;
      w += t;
    }
    // The coefficients' own, through A and B (coefficientsAt).
    const g = water.dGw;
    if (g) for (const [s, nu] of eq.net) w += nu * g[s];
    return w;
  }

  /**
   * A relation's (or a phase's) correction for the pressure, sum nu f V over
   * its species and the water, which comes off its ln K; 0 without volumes
   * or at one atmosphere. A phase of <PHASES> adds its own, c0 f V.
   */
  function pressureTerm(eq, water) {
    if (!water || !water.pv) return 0;
    const pv = water.pv;
    let t = eq.water ? eq.water * water.pvW : 0;
    for (const [s, nu] of eq.net) t += nu * pv[s];
    if (eq.vm0) t -= eq.c0 * eq.vm0 * water.pf;
    return t;
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
   *
   *   4  any solute under sit: log gamma = -A z^2 sqrt(I)/(1 + 1.5 sqrt(I))
   *      + sum over the species j it is paired with in <SIT> of
   *      (eps + eps1 I) m_j, PHREEQC's SIT (sit.cpp); a neutral species has
   *      the sum alone. The water's activity is SIT's own (sitWater).
   *
   * `sitLines` is the <SIT> section: two species and eps on each line, and
   * eps1= where the pair's coefficient goes with I as well (PHREEQC's
   * -epsilon1).
   */
  function activityModel(settings, species, warnings, sitLines = [], pzLines = [], llnlLines = []) {
    const isSit = settings.ACTIVITY === 'sit';
    const isPz = settings.ACTIVITY === 'pitzer';
    const isLlnl = settings.ACTIVITY === 'llnl';
    if (llnlLines.length && !isLlnl) {
      throw new RtmError(`<LLNL> holds the tables of LLNL's activity model, and is read under ACTIVITY = llnl`
        + `${settings.ACTIVITY === 'none' ? '' : `, not ${settings.ACTIVITY}`}.`, llnlLines[0].line);
    }
    const drummond = species.filter((sp) => sp.drummond);
    if (drummond.length && !isLlnl) {
      throw new RtmError(`${drummond[0].name} is given drummond, Drummond's coefficient of CO2 in LLNL's activity model: it is `
        + 'read under ACTIVITY = llnl.', drummond[0].line);
    }
    if (sitLines.length && !isSit) {
      throw new RtmError(`<SIT> holds the interaction coefficients of the specific ion interaction theory, and is read `
        + `under ACTIVITY = sit${settings.ACTIVITY === 'none' ? '' : `, not ${settings.ACTIVITY}`}.`, sitLines[0].line);
    }
    if (pzLines.length && !isPz) {
      throw new RtmError(`<PITZER> holds the parameters of Pitzer's equations, and is read under ACTIVITY = pitzer`
        + `${settings.ACTIVITY === 'none' ? '' : `, not ${settings.ACTIVITY}`}.`, pzLines[0].line);
    }
    // Whether anything reads TEMPERATURE is said once the model is put together (compile).
    if (settings.ACTIVITY === 'none') return null;
    const tc = setupTemperature(settings);
    if (!(tc >= 0 && tc <= 350)) {
      throw new RtmError(`TEMPERATURE = ${tc}: the activity model's A and B are worked out for 0 to 350 C.`);
    }
    const ns = species.length;
    /*
      The water at TEMPERATURE: A and B at a(H2O) = 1, and what goes with the
      temperature alone, for waterAt. Under LLNL's model A, B and B-dot are
      its tables' at the temperature (llnlAt), and the water's density and
      dielectric constant are not read at all, as in PHREEQC.
    */
    const llnl = isLlnl ? readLlnl(llnlLines, species) : null;
    const wt = llnl ? null : waterAtT(tc, waterPressure(settings, species));
    const { A, B } = llnl ? llnlAt(llnl, tc) : waterAt(wt, 1);
    const z = new Float64Array(ns);
    const form = new Uint8Array(ns);
    const a = new Float64Array(ns);
    const b = new Float64Array(ns);
    const solute = new Uint8Array(ns).fill(1);
    const ignored = [];
    species.forEach((sp, s) => {
      // The water itself, and a pure phase: activity 1, and no solute. An
      // exchanger and the species on it are no solutes either, and carry no
      // charge into I: their coefficients are set with the exchange (exchangeSetup).
      // Nor is the electron, whose coefficient is 1: its activity is solved for; nor a
      // species on a surface, whose activity is its fraction of the sites (surfaceSetup).
      if (sp.name === 'H2O' || sp.mineral || sp.exchange || sp.exchanger || sp.electron || sp.surface || sp.potential
        || sp.gas) {
        solute[s] = 0;
        return;
      }
      z[s] = sp.z !== null ? sp.z : chargeOf(sp.name);
      if (isSit || isPz) {
        form[s] = isSit ? 4 : 6;
        if (sp.dha !== null || sp.dhb !== null) ignored.push(sp.name);
        return;
      }
      /*
        LLNL's: an ion given a= (PHREEQC's -llnl_gamma) its B-dot form, and a
        neutral species given it gamma = 1; drummond CO2's; a neutral species
        given neither b I, b 0.1 unless given, as PHREEQC's default. An ion
        given no a has no coefficient PHREEQC works out (its A is not read
        under LLNL's model), and is refused.
      */
      if (isLlnl) {
        if (sp.drummond) {
          if (sp.dha !== null || sp.dhb !== null) {
            throw new RtmError(`${sp.name} is given drummond and a or b: Drummond's coefficient takes neither.`, sp.line);
          }
          form[s] = 8;
          return;
        }
        if (sp.dha !== null) {
          form[s] = 7;
          a[s] = sp.dha;
          if (sp.dhb !== null) ignored.push(sp.name);
          return;
        }
        if (!z[s]) { form[s] = 1; b[s] = sp.dhb !== null ? sp.dhb : 0.1; return; }
        throw new RtmError(`${sp.name} is an ion and ACTIVITY = llnl: it takes a=, its ion-size parameter, the database's `
          + '-llnl_gamma.', sp.line);
      }
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
    if (ignored.length) {
      const who = ignored.length === 1 ? ignored[0] : `${ignored.length} species (${ignored.slice(0, 4).join(', ')}`
        + `${ignored.length > 4 ? ', ...' : ''})`;
      warnings.push(isLlnl ? `ACTIVITY = llnl takes a and B-dot from <LLNL>, and the b given to ${who} is not used.`
        : `ACTIVITY = ${isSit ? 'sit' : 'pitzer'} takes no a or b: ${isSit ? 'SIT\'s coefficients come from '
          + 'the charge and <SIT>' : 'the coefficients come from the charges and <PITZER>'}, and the a and b `
          + `given to ${who} are not used.`);
    }
    const pz = isPz ? readPitzer(pzLines, species, solute, z, warnings) : null;
    if (pz) {
      pz.patm = waterPressure(settings, species);
      pz.tk = tc + 273.15;
      pz.A0 = pitzerValues(pz, tc, pz.patm, pz.val);
    }
    /*
      Where the water can be above 100 C, A and B's derivative in ln a(H2O),
      species by species, for the Jacobian (coefficientsAt): the water is
      then on its vapour pressure, or the density goes with it, enough to see.
      Under SIT and Pitzer at any temperature, as the water already reads
      every solute; under Pitzer A_phi's and the pressure's (pitzerAt).
    */
    const hot = !llnl && (isSit || isPz || !(typeof settings.TEMPERATURE === 'number' && settings.TEMPERATURE < 99.6));
    return { kind: settings.ACTIVITY, temperature: tc, A, B, wt, wtc: null, ns, z, zg: Float64Array.from(z), form, a, b,
      dGw: hot ? new Float64Array(ns) : null,
      solute, ex: null, sf: null, pt: null, gas: null, sit: isSit ? readSit(sitLines, species, solute) : null, pz,
      llnl, bdot: llnl ? llnlAt(llnl, tc).bdot : 0, bdotc: null };
  }

  /**
   * The <LLNL> section, PHREEQC's LLNL_AQUEOUS_MODEL_PARAMETERS a line each:
   *
   *   TEMPERATURES  0.01  25  60  100
   *   DH_A          0.4939  0.5114  0.5465  0.5995
   *   DH_B          0.3253  0.3288  0.3346  0.3421
   *   BDOT          0.0374  0.041  0.0438  0.046
   *   CO2           -1.0312  0.0012806  255.9  0.4445  -0.001606
   *
   * the Debye-Hueckel A and B and B-dot at each temperature (C), rising, and
   * the five coefficients of Drummond's (1981) CO2, which a species given
   * drummond reads.
   */
  function readLlnl(lines, species) {
    const out = { temps: null, adh: null, bdh: null, bdot: null, co2: null };
    const keys = { TEMPERATURES: 'temps', DH_A: 'adh', DH_B: 'bdh', BDOT: 'bdot', CO2: 'co2' };
    for (const { text, line } of lines) {
      const parts = text.split(/\s+/).filter(Boolean);
      const k = keys[parts[0].toUpperCase()];
      if (!k) {
        throw new RtmError(`"${parts[0]}" in <LLNL>: TEMPERATURES, DH_A, DH_B and BDOT, a value at each temperature, and CO2, `
          + 'Drummond\'s five coefficients.', line);
      }
      if (out[k]) throw new RtmError(`${parts[0].toUpperCase()} is given twice in <LLNL>.`, line);
      out[k] = Float64Array.from(parts.slice(1), (v) => constValue(v, line, `${parts[0]} in <LLNL>`));
      out[`${k}Line`] = line;
    }
    const line0 = lines.length ? lines[0].line : undefined;
    for (const k of ['temps', 'adh', 'bdh', 'bdot']) {
      if (!out[k] || !out[k].length) {
        throw new RtmError('ACTIVITY = llnl takes its tables in <LLNL>: TEMPERATURES, DH_A, DH_B and BDOT, a value at each '
          + 'temperature, as the database\'s LLNL_AQUEOUS_MODEL_PARAMETERS gives them.', line0);
      }
    }
    const n = out.temps.length;
    for (const k of ['adh', 'bdh', 'bdot']) {
      if (out[k].length !== n) {
        throw new RtmError(`${k === 'adh' ? 'DH_A' : k === 'bdh' ? 'DH_B' : 'BDOT'} has ${out[k].length} values and TEMPERATURES `
          + `${n}: one at each temperature.`, out[`${k}Line`]);
      }
    }
    for (let i = 1; i < n; i++) {
      if (!(out.temps[i] > out.temps[i - 1])) throw new RtmError('TEMPERATURES in <LLNL> rise, one after another.', out.tempsLine);
    }
    if (species.some((sp) => sp.drummond) && !(out.co2 && out.co2.length === 5)) {
      throw new RtmError('A species is given drummond, and <LLNL> needs CO2 with Drummond\'s five coefficients.', out.co2Line || line0);
    }
    return out;
  }

  /**
   * LLNL's A, B and B-dot at tc degrees C, as PHREEQC takes them: straight
   * between the two temperatures of the tables on either side, a table
   * temperature's own at it; outside the tables it is refused, as PHREEQC
   * stops.
   */
  function llnlAt(t, tc, where = '') {
    const T = t.temps;
    const n = T.length;
    if (tc < T[0] || tc > T[n - 1]) {
      throw new RtmError(`The temperature, ${tc} C${where}, is outside LLNL's tables in <LLNL>, ${T[0]} to ${T[n - 1]} C.`);
    }
    let first = 0;
    let lastI = n;
    for (let i = 0; i < n; i++) {
      if (tc >= T[i]) first = i;
      if (tc <= T[i]) { lastI = i; break; }
    }
    const f = lastI === first ? 1 : (tc - T[first]) / (T[lastI] - T[first]);
    return { A: (1 - f) * t.adh[first] + f * t.adh[lastI], B: (1 - f) * t.bdh[first] + f * t.bdh[lastI],
      bdot: (1 - f) * t.bdot[first] + f * t.bdot[lastI] };
  }

  /**
   * The <SIT> section: each line two species and their interaction
   * coefficient eps, in kg/mol for log10 gamma as PHREEQC's SIT -epsilon has
   * it, and eps1= for one that goes with I as well, eps + eps1 I (its
   * -epsilon1). Both species are solutes; a pair is given once, either way
   * round, and a species may be paired with itself.
   *
   * Returns the pairs, and for each species the species its coefficient
   * reads (rows: k, eps, eps1 -- a pair with itself counted twice, as
   * PHREEQC's sum counts it), with the scratch the derivatives use.
   */
  function readSit(lines, species, solute) {
    const ns = species.length;
    const index = new Map(species.map((sp, s) => [sp.name, s]));
    const pairs = [];
    const seen = new Map();
    for (const { text, line } of lines) {
      const parts = text.split(/\s+/);
      const opts = parts.filter((p) => /^[A-Za-z0-9_]+=/.test(p));
      const plain = parts.filter((p) => !/^[A-Za-z0-9_]+=/.test(p));
      if (plain.length !== 3) {
        throw new RtmError(`"${text}" is not two species and their coefficient: Na+  Cl-  0.03, and eps1= after it for `
          + 'one that goes with the ionic strength as well.', line);
      }
      const [n1, n2, raw] = plain;
      const ks = [n1, n2].map((name) => {
        if (!index.has(name)) throw new RtmError(`"${name}" in <SIT> is not in <SPECIES>.`, line);
        const k = index.get(name);
        if (!solute[k]) {
          throw new RtmError(`${name} is no solute -- the water, a mineral, an exchanger or what is on one, a surface, `
            + 'its potential or the electron -- and SIT pairs solutes.', line);
        }
        return k;
      });
      const eps = constValue(raw, line, `The coefficient of ${n1} and ${n2}`);
      let eps1 = 0;
      for (const o of opts) {
        const [key, val] = o.split('=');
        if (key.toLowerCase() !== 'eps1') {
          throw new RtmError(`"${o}": a pair in <SIT> takes eps1= (its coefficient's slope in the ionic strength) and `
            + 'nothing else.', line);
        }
        eps1 = constValue(val, line, `eps1 of ${n1} and ${n2}`);
      }
      const key = ks[0] < ks[1] ? `${ks[0]}:${ks[1]}` : `${ks[1]}:${ks[0]}`;
      if (seen.has(key)) {
        throw new RtmError(`${n1} and ${n2} are paired twice in <SIT>, on lines ${seen.get(key)} and ${line}.`, line);
      }
      seen.set(key, line);
      // PHREEQC halves a pair of two neutral species in the osmotic coefficient.
      const neutral = !(species[ks[0]].z !== null ? species[ks[0]].z : chargeOf(n1))
        && !(species[ks[1]].z !== null ? species[ks[1]].z : chargeOf(n2));
      pairs.push({ i: ks[0], j: ks[1], e: eps, e1: eps1, c: neutral ? 0.5 : 1 });
    }
    const lists = Array.from({ length: ns }, () => []);
    for (const p of pairs) {
      lists[p.i].push([p.j, p.e, p.e1]);
      lists[p.j].push([p.i, p.e, p.e1]);
    }
    const rows = lists.map((l) => (l.length ? { k: Int32Array.from(l, (x) => x[0]), e: Float64Array.from(l, (x) => x[1]),
      e1: Float64Array.from(l, (x) => x[2]) } : null));
    return { pairs, rows, d: new Float64Array(ns), dAwv: new Float64Array(ns), any1: pairs.some((p) => p.e1 !== 0) };
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
    const at = cell === undefined ? Math.round(off / ns) : cell;
    let res;
    if (act.sit) res = sitAt(act, C, off, I, low, sum, lnG, dG, at);
    else if (act.pz) res = pitzerAt(act, C, off, I, low, sum, lnG, dG, at);
    else {
      let aw = 1 - 0.017 * sum;
      const dry = !(aw > 1e-6);
      if (dry) aw = 1e-6;
      // A and B at the water's activity, as PHREEQC has them (coefficientsAt).
      coefficientsAt(act, I, low, lnG, dG, at, aw);
      if (act.gas && act.gas.dln) prVolumeCoefficients(act, C, off, lnG, at);
      res = { I, lnAw: Math.log(aw), dAw: dry ? 0 : -0.017 / aw, dGw: act.dGw };
    }
    // An exchanger whose sites go with a mineral: each species' fraction of what is on it now.
    if (act.ex && act.ex.perAny) res.exSum = exchangeFractions(act, C, off, lnG, at);
    // The molar volumes, for each relation's ln K at the pressure (volumesAt).
    if (act.vol && !act.vol.idle) volumesAt(act, res, I, low, at);
    return res;
  }

  /**
   * activityAt under SIT, PHREEQC's (sit.cpp): each solute's coefficient
   * (activityModel's form 4), with d(ln gamma)/dI into dG -- what it reads of
   * the species paired with it is sitPartners' -- a species on an exchanger
   * its ion's (form 5, as PHREEQC's -pitzer_exchange_gammas has it), and the
   * water's activity from SIT's osmotic coefficient,
   *
   *   ln a(H2O) = -(sum m + ln10 S) / 55.50837,
   *   S = -2A/1.5^3 (T - 2 ln T - 1/T) + sum over the pairs of m_i m_j eps
   *       (half of it for two neutral species), T = 1 + 1.5 sqrt(I),
   *
   * with its derivative in each species' concentration, dAwv. A is the
   * Debye-Hueckel A of the other forms: 3 A_phi/ln 10 in PHREEQC is the same
   * number. It is the water's own, at the density of water at the vapour
   * pressure times a(H2O) (calc_rho_0), and so at the a(H2O) it gives: a
   * fixed point, which one Newton step from the pure water's A reaches to
   * round-off, as A moves a part in 1e6 as far as ln a(H2O) at 25 C and a
   * part in 1e3 or so at 150 C. PHREEQC's sit.cpp takes it at the a(H2O) a
   * calculation starts from: 1 for an initial solution, and for a reaction
   * step or a shift that of the water it starts from. A's derivative in ln
   * a(H2O) goes into dGw (coefficientsAt) and into dAwv.
   */
  function sitAt(act, C, off, I, low, osum, lnG, dG, cell) {
    const ns = act.ns;
    const st = act.sit;
    const sq = Math.sqrt(I);
    const T = 1 + 1.5 * sq;
    // The pairs' part of the osmotic coefficient, which A does not touch.
    let osPairs = 0;
    let osI = 0;
    for (const p of st.pairs) {
      const mi = C[off + p.i];
      const mj = C[off + p.j];
      osPairs += mi * mj * (p.e * p.c + p.e1 * (1 + p.c * I));
      if (!low) osI += mi * mj * p.e1 * p.c;
    }
    const shape = T - 2 * Math.log(T) - 1 / T;
    let A = act.Ac ? act.Ac[cell] : act.A;
    let dlnA = 0;
    if (act.wt) {
      /*
        ln a(H2O) = a + b A, b A the Debye-Hueckel part, with A at that
        a(H2O). b A dlnA is a part in 1e5 or less, so from a(H2O) at the pure
        water's A one Newton step on A's slope there lands on it to round-off
        -- unless the step crosses one of A's corners (waterSide), where A is
        taken afresh at each a(H2O) until it settles.
      */
      const wt = act.wtc ? act.wtc[cell] : act.wt;
      const a = -(osum + Math.LN10 * osPairs) / SIT_WATER;
      const b = (2 * Math.LN10 * shape) / (3.375 * SIT_WATER);
      const L0 = a + b * A;
      const ws = st.ws || (st.ws = {});
      const w0 = waterAt(wt, Math.exp(L0), undefined, ws);
      dlnA = w0.dlnA;
      let L = (a + b * w0.A * (1 - dlnA * L0)) / (1 - b * w0.A * dlnA);
      A = w0.A * (1 + dlnA * (L - L0));
      if (waterSide(wt, L) !== waterSide(wt, L0)) {
        for (let it = 0; it < 8; it++) {
          const w = waterAt(wt, Math.exp(L), undefined, ws);
          A = w.A;
          dlnA = w.dlnA;
          const next = a + b * A;
          const step = Math.abs(next - L);
          L = next;
          if (step <= 1e-16 * Math.max(1, Math.abs(L))) break;
        }
      }
    }
    const F = (-A * sq) / T;
    const dF = low ? 0 : -A / (2 * sq * T * T);
    const dGw = act.dGw;
    for (let s = 0; s < ns; s++) {
      if (act.form[s] !== 4) { lnG[s] = 0; dG[s] = 0; if (dGw) dGw[s] = 0; continue; }
      const z2 = act.z[s] * act.z[s];
      let lg = z2 * F;
      let dg = z2 * dF;
      if (dGw) dGw[s] = Math.LN10 * z2 * F * dlnA;
      const r = st.rows[s];
      if (r) {
        for (let q = 0; q < r.k.length; q++) {
          const m = C[off + r.k[q]];
          lg += (r.e[q] + I * r.e1[q]) * m;
          dg += r.e1[q] * m;
        }
      }
      lnG[s] = Math.LN10 * lg;
      dG[s] = low ? 0 : Math.LN10 * dg;
    }
    const ex = act.ex;
    if (ex) {
      for (const s of ex.list) {
        if (act.form[s] !== 5) continue;
        lnG[s] = lnG[ex.ion[s]];
        dG[s] = dG[ex.ion[s]];
        if (dGw) dGw[s] = dGw[ex.ion[s]];
      }
    }
    onSites(act, lnG, dG, cell);
    if (act.gas && act.gas.dln) prVolumeCoefficients(act, C, off, lnG, cell);
    // The water.
    const os = (-2 * A / 3.375) * shape + osPairs;
    if (!low) osI += (-A * sq) / (T * T);
    const dAwv = st.dAwv;
    for (let k = 0; k < ns; k++) dAwv[k] = act.solute[k] ? 1 + Math.LN10 * osI * 0.5 * act.z[k] * act.z[k] : 0;
    for (const p of st.pairs) {
      const f = Math.LN10 * (p.e * p.c + p.e1 * (1 + p.c * I));
      dAwv[p.i] += f * C[off + p.j];
      dAwv[p.j] += f * C[off + p.i];
    }
    // ...and through A, which goes with the a(H2O) it gives: d ln a = (that at a fixed A) - b A dlnA d ln a.
    const fix = -SIT_WATER - Math.LN10 * (-2 * A / 3.375) * shape * dlnA;
    for (let k = 0; k < ns; k++) dAwv[k] /= fix;
    return { I, lnAw: -(osum + Math.LN10 * os) / SIT_WATER, dAw: 0, dAwv, dGw };
  }

  /** Moles of water in a kilogram, as PHREEQC's SIT has it. */
  const SIT_WATER = 55.50837;

  /** d(ln a(H2O))/dC of species k, from an activityAt evaluation. */
  function awOf(act, water, k) {
    return water.dAwv ? water.dAwv[k] : (act.solute[k] ? water.dAw : 0);
  }

  /**
   * Under SIT, what the coefficients of a relation's species read besides
   * the ionic strength: d(sum nu ln gamma)/dC_k for each species k paired
   * with one of them in <SIT>, added into act.sit.d, which is zero elsewhere
   * and is returned (null without SIT). Under Pitzer the same from pz.D, the
   * evaluation `water` is (pitzerAt): every solute's. sitDone(act, net) puts
   * the zeros back. `net` is [species, nu] pairs; `water` activityAt's
   * result for the cell.
   */
  function sitPartners(act, net, water) {
    const st = act && act.sit;
    const pz = act && act.pz;
    const gas = act && act.gas && act.gas.dln ? act.gas : null;
    const xp = act && act.ex && act.ex.perAny && water.exSum ? act.ex : null;
    if (!st && !pz && !gas && !xp) return null;
    const I = water.I;
    const d = st ? st.d : pz ? pz.d : gas ? gas.d : xp.d;
    if (st) {
      for (const [s, nu] of net) {
        const r = st.rows[s];
        if (!r) continue;
        for (let q = 0; q < r.k.length; q++) d[r.k[q]] += nu * Math.LN10 * (r.e[q] + I * r.e1[q]);
      }
    }
    if (pz) {
      // The rows are the last evaluation's: it must be this one.
      if (water.pz !== pz.stamp) throw new Error('Pitzer: a coefficient\'s partners read from another evaluation.');
      const { n, D, sysOf, modelOf } = pz;
      for (const [s, nu] of net) {
        let src = s;
        let f = nu;
        if (act.form[s] === 5) { src = act.ex.ion[s]; f = nu * act.ex.pw[s]; } else if (act.form[s] !== 6) continue;
        const at = sysOf[src] * n;
        for (let k = 0; k < n; k++) {
          const m = modelOf[k];
          if (m >= 0 && D[at + k]) d[m] += f * D[at + k];
        }
      }
    }
    // A real gas in a fixed volume reads every gas of its phase (prVolumeCoefficients).
    if (gas) {
      const K = gas.list.length;
      for (const [s, nu] of net) {
        const q = gas.qOf[s];
        if (q < 0) continue;
        for (let j = 0; j < K; j++) d[gas.list[j]] += nu * gas.dln[q * K + j];
      }
    }
    // On an exchanger whose sites go with a mineral, a species' fraction reads all that is on it (exchangeFractions).
    if (xp) {
      for (const [s, nu] of net) {
        if (xp.site[s] !== 1) continue;
        const x = xp.of[s];
        const sum = water.exSum[x];
        if (!xp.per[x] || !(sum > 0)) continue;
        for (const j of xp.members[x]) d[j] -= (nu * xp.n[j]) / sum;
      }
    }
    return d;
  }
  function sitDone(act, net) {
    const st = act.sit;
    const pz = act.pz;
    const gas = act.gas && act.gas.dln ? act.gas : null;
    const xp = act.ex && act.ex.perAny ? act.ex : null;
    const d = st ? st.d : pz ? pz.d : gas ? gas.d : xp.d;
    if (xp) {
      for (const [s] of net) if (xp.site[s] === 1 && xp.per[xp.of[s]]) for (const j of xp.members[xp.of[s]]) d[j] = 0;
    }
    if (st) {
      for (const [s] of net) {
        const r = st.rows[s];
        if (r) for (let q = 0; q < r.k.length; q++) d[r.k[q]] = 0;
      }
    }
    if (pz) for (const m of pz.modelOf) if (m >= 0) d[m] = 0;
    if (gas) for (const [s] of net) if (gas.qOf[s] >= 0) for (const k of gas.list) d[k] = 0;
  }

  /* ======================================================================
     2a'. Pitzer's equations, as PHREEQC has them (pitzer.cpp)
     ====================================================================== */

  /*
    THE <PITZER> SECTION, PHREEQC's PITZER keyword a line at a time: the
    parameter's type, its species, and its value at 25 C followed by up to
    five terms of its temperature dependence, PHREEQC's six (calc_pitz_param):

      p(T) = a0 + a1 (1/T - 1/Tr) + a2 ln(T/Tr) + a3 (T - Tr)
             + a4 (T^2 - Tr^2) + a5 (1/T^2 - 1/Tr^2),   Tr = 298.15 K

      B0     Na+   Cl-    0.0765   -777.03  -4.4706  0.008946  -3.3158e-6
      THETA  K+    Na+   -0.012
      PSI    K+    Na+   Cl-   -0.0018
      LAMBDA CO2   Na+    0.1
      ALPHAS Ca+2  SO4-2  1.4  12      the pair's alpha1 and alpha2, its B1 and B2 lines in that order
      APHI   0.39147                   A_phi, where it is not the water's own
      MACINNES  no                     the MacInnes scaling off
      ETHETA    no                     E-theta off

    B0, B1, B2 and C0 pair a cation and an anion; THETA two ions of one sign;
    PSI two of one sign and one of the other; LAMBDA a neutral species and
    any; ZETA a neutral species, a cation and an anion; MU three with two
    neutral; ETA three with one neutral.
  */
  const PZ_TYPES = { B0: 2, B1: 2, B2: 2, C0: 2, THETA: 2, LAMDA: 2, LAMBDA: 2, ZETA: 3, PSI: 3, MU: 3, ETA: 3,
    ALPHAS: 2, APHI: 0 };
  /** Moles of water in a kilogram, as PHREEQC's Pitzer and SIT have it. */
  const PZ_WATER = 55.50837;

  /**
   * The <PITZER> section read: the parameters among the model's solutes (and
   * K+ and Cl-, which the MacInnes scaling reads whether or not they are
   * species of the model: a water with no chloride is scaled by the ln gamma
   * Cl- would have in it, as PHREEQC scales it), each with PHREEQC's alpha,
   * ln_coef and os_coef (pitzer_tidy), the pairs of ions of one sign whose
   * E-theta is not zero, and the scratch pitzerAt works in.
   */
  function readPitzer(lines, species, solute, zOf, warnings) {
    const ns = species.length;
    const index = new Map(species.map((sp, s) => [sp.name, s]));
    // The system: every solute of the model, then K+ and Cl- where named and not species.
    const modelOf = [];
    const sysOf = new Int32Array(ns).fill(-1);
    for (let s = 0; s < ns; s++) if (solute[s]) { sysOf[s] = modelOf.length; modelOf.push(s); }
    const z = [];
    for (const s of modelOf) z.push(zOf[s]);
    const virtual = new Map();
    const sysIndex = (name, line) => {
      if (index.has(name)) {
        const s = index.get(name);
        if (!solute[s]) {
          throw new RtmError(`${name} is no solute -- the water, a mineral, an exchanger or what is on one, a surface, `
            + 'its potential, the electron or a gas -- and Pitzer\'s parameters are between solutes.', line);
        }
        return sysOf[s];
      }
      if (name === 'K+' || name === 'Cl-') {
        if (!virtual.has(name)) { virtual.set(name, modelOf.length); modelOf.push(-1); z.push(name === 'K+' ? 1 : -1); }
        return virtual.get(name);
      }
      throw new RtmError(`"${name}" in <PITZER> is not in <SPECIES> (only K+ and Cl-, which the MacInnes scaling reads, `
        + 'may be named without being species).', line);
    };
    const params = [];
    const seen = new Map();
    let aphi = null;
    let macinnes = null;
    let etheta = true;
    const alphas = [];
    for (const { text, line } of lines) {
      const parts = text.split(/\s+/).filter(Boolean);
      const kw = parts[0].toUpperCase();
      if (kw === 'MACINNES' || kw === 'ETHETA') {
        const v = (parts[1] || '').toLowerCase();
        if (parts.length !== 2 || !['yes', 'no', 'true', 'false'].includes(v)) {
          throw new RtmError(`"${text}": ${kw} yes or ${kw} no.`, line);
        }
        if (kw === 'MACINNES') macinnes = v === 'yes' || v === 'true'; else etheta = v === 'yes' || v === 'true';
        continue;
      }
      if (!(kw in PZ_TYPES)) {
        throw new RtmError(`"${parts[0]}" is no Pitzer parameter: B0, B1, B2, C0, THETA, LAMBDA, ZETA, PSI, MU, ETA, `
          + 'ALPHAS or APHI, or MACINNES or ETHETA and yes or no.', line);
      }
      const nsp = PZ_TYPES[kw];
      const names = parts.slice(1, 1 + nsp);
      const nums = parts.slice(1 + nsp);
      if (names.length !== nsp || nums.length < 1 || nums.length > 6) {
        throw new RtmError(`"${text}": ${kw} takes ${nsp ? `${nsp === 2 ? 'two' : 'three'} species and ` : ''}its value `
          + 'at 25 C, and up to five more terms in the temperature, as PHREEQC writes them.', line);
      }
      const a = new Float64Array(6);
      nums.forEach((v, i) => { a[i] = constValue(v, line, `${kw}${names.length ? ` of ${names.join(' ')}` : ''}`); });
      if (kw === 'APHI') {
        if (aphi) throw new RtmError(`APHI is given twice, on lines ${aphi.line} and ${line}.`, line);
        aphi = { a, line };
        continue;
      }
      const q = names.map((nm) => sysIndex(nm, line));
      const type = kw === 'LAMDA' ? 'LAMBDA' : kw;
      if (type === 'ALPHAS') {
        if (nums.length > 2) throw new RtmError(`"${text}": ALPHAS takes the pair's alpha1 and alpha2.`, line);
        alphas.push({ q, a, line, n: nums.length });
        continue;
      }
      const zs = q.map((i) => z[i]);
      const nPos = zs.filter((v) => v > 0).length;
      const nNeg = zs.filter((v) => v < 0).length;
      const nNeu = zs.filter((v) => v === 0).length;
      const distinct = new Set(q).size;
      let why = '';
      if (['B0', 'B1', 'B2', 'C0'].includes(type) && !(nPos === 1 && nNeg === 1)) why = 'a cation and an anion';
      else if (type === 'THETA' && !(distinct === 2 && (nPos === 2 || nNeg === 2))) why = 'two ions of one sign';
      else if (type === 'PSI' && !(distinct === 3 && ((nPos === 2 && nNeg === 1) || (nNeg === 2 && nPos === 1)))) {
        why = 'two ions of one sign and one of the other';
      } else if (type === 'LAMBDA' && nNeu < 1) why = 'a neutral species and any other';
      else if (type === 'ZETA' && !(nNeu === 1 && nPos === 1 && nNeg === 1)) why = 'a neutral species, a cation and an anion';
      else if (type === 'MU' && nNeu < 2) why = 'three species, two of them neutral';
      else if (type === 'ETA' && nNeu < 1) why = 'three species, one of them neutral';
      if (why) throw new RtmError(`"${text}": ${type} is between ${why}.`, line);
      const key = `${type} ${[...new Set(names)].sort().join(' ')}`;
      if (seen.has(key)) throw new RtmError(`${type} ${names.join(' ')} is given twice, on lines ${seen.get(key)} and ${line}.`, line);
      seen.set(key, line);
      params.push({ type, q, a, line, alpha: 0, lc: [0, 0, 0], os: 0 });
    }
    const n = modelOf.length;
    // PHREEQC's alpha for B1 and B2 by the pair's charges (pitzer_tidy), then ALPHAS for the pair in that order.
    for (const p of params) {
      if (p.type !== 'B1' && p.type !== 'B2') continue;
      const z0 = Math.abs(z[p.q[0]]);
      const z1 = Math.abs(z[p.q[1]]);
      const order = z0 === 1 || z1 === 1 ? 1 : z0 === 2 && z1 === 2 ? 2 : 3;
      p.alpha = p.type === 'B1' ? (order === 2 ? 1.4 : 2.0) : (order === 3 ? 50.0 : 12.0);
    }
    for (const al of alphas) {
      let used = false;
      for (const [t, i] of [['B1', 0], ['B2', 1]]) {
        const p = params.find((pp) => pp.type === t && pp.q[0] === al.q[0] && pp.q[1] === al.q[1]);
        if (p) { p.alpha = al.a[i]; used = true; }
      }
      if (!used) {
        warnings.push(`Line ${al.line}: ALPHAS reads the B1 and B2 of its pair named in the same order, as PHREEQC's `
          + 'does, and there are none: it is not used.');
      }
    }
    // PHREEQC's coefficients of LAMBDA and MU in ln gamma and in the osmotic coefficient (pitzer_tidy).
    for (const p of params) {
      if (p.type === 'LAMBDA') {
        if (p.q[0] === p.q[1]) { p.os = 0.5; p.lc = [1, 1, 0]; } else { p.os = 1; p.lc = [2, 2, 0]; }
      } else if (p.type === 'MU') {
        const [i0, i1, i2] = p.q;
        const neutral = p.q.filter((i) => z[i] === 0).length;
        if (neutral === 3) p.os = i0 === i1 && i1 === i2 ? 1 : i0 === i1 || i1 === i2 || i0 === i2 ? 3 : 6;
        else p.os = i0 === i1 || i1 === i2 || i0 === i2 ? 3 : 6;
        const count = p.q.map((i) => p.q.filter((k) => k === i).length);
        for (let j = 0; j < 3; j++) {
          if (z[p.q[j]] !== 0) p.lc[j] = count[0] > 1 || count[1] > 1 ? 3 : 6;
          else if (count[j] === 3) p.lc[j] = 1;
          else if (count[j] === 2) p.lc[j] = 3;
          else p.lc[j] = count[0] > 1 || count[1] > 1 ? 3 : 6;
        }
      }
    }
    // The MacInnes scaling: on unless said otherwise, and off without K+ and Cl-'s B0, B1 or C0, as in PHREEQC.
    const kcl = (t) => params.findIndex((p) => p.type === t && new Set(p.q).size === 2
      && p.q.some((i) => (modelOf[i] >= 0 ? species[modelOf[i]].name : [...virtual].find(([, v]) => v === i)[0]) === 'K+')
      && p.q.some((i) => (modelOf[i] >= 0 ? species[modelOf[i]].name : [...virtual].find(([, v]) => v === i)[0]) === 'Cl-'));
    const mc = { b0: kcl('B0'), b1: kcl('B1'), c0: kcl('C0') };
    let icon = macinnes !== false;
    if (icon && mc.b0 < 0 && mc.b1 < 0 && mc.c0 < 0) {
      if (macinnes === true) {
        throw new RtmError('MACINNES yes needs the B0, B1 or C0 of K+ and Cl-, which the scaling reads.', lines[0].line);
      }
      icon = false;
      warnings.push('<PITZER> gives no B0, B1 or C0 of K+ and Cl-: the MacInnes scaling is off, as PHREEQC turns it off.');
    }
    const nameOf = (i) => (modelOf[i] >= 0 ? species[modelOf[i]].name : [...virtual].find(([, v]) => v === i)[0]);
    let cl = -1;
    if (icon) {
      for (let i = 0; i < n; i++) if (nameOf(i) === 'Cl-') cl = i;
      if (cl < 0) { cl = modelOf.length; modelOf.push(-1); z.push(-1); virtual.set('Cl-', cl); }
    }
    const N = modelOf.length;
    // E-theta between every two ions of one sign whose charges differ: zero where they are the same.
    const ethetaPairs = [];
    if (etheta) {
      for (let i = 0; i < N; i++) {
        for (let j = i + 1; j < N; j++) {
          if (z[i] * z[j] > 0 && z[i] !== z[j]) ethetaPairs.push([i, j]);
        }
      }
    }
    const zz = Float64Array.from(z);
    return {
      n: N, modelOf: Int32Array.from(modelOf), sysOf, z: zz, names: Array.from({ length: N }, (_, i) => nameOf(i)),
      params, np: params.length, aphi, icon, mc, cl, etheta, ethetaPairs,
      // The values at the temperature (pitzerValues): one set, or one a cell where the temperature goes with it.
      val: new Float64Array(params.length), A0: 0, tk: 298.15, patm: 1, valc: null, A0c: null,
      // Scratch: molalities, ln gamma, d ln gamma/dI, d ln gamma_i/d m_k at fixed I (D, n x n), and the sums' gradients.
      M: new Float64Array(N), LG: new Float64Array(N), LI: new Float64Array(N), D: new Float64Array(N * N),
      dF: new Float64Array(N), dCS: new Float64Array(N), zc: new Float64Array(N), dOS: new Float64Array(N),
      row: new Float64Array(N), J: new Float64Array(5), stamp: 0,
      // ln gamma's derivatives in A_phi (times A_phi) and in the pressure, for its derivative in ln a(H2O); waterAt's out.
      LA: new Float64Array(N), LP: new Float64Array(N), osA: 0, ws: {},
      d: new Float64Array(ns), dAwv: new Float64Array(ns),
    };
  }

  /** PHREEQC's calc_pitz_param: a parameter's value at tk kelvin from its six terms. */
  function pitzerParam(a, tk) {
    const TR = 298.15;
    if (Math.abs(tk - TR) < 0.001) return a[0];
    return (a[0] + a[1] * (1 / tk - 1 / TR) + a[2] * Math.log(tk / TR) + a[3] * (tk - TR) + a[4] * (tk * tk - TR * TR))
      + a[5] * (1 / (tk * tk) - 1 / (TR * TR));
  }

  /**
   * Every parameter's value at tc degrees C into out, and A_phi: APHI's where
   * given, else the water's, PHREEQC's DH_B e^2/(eps k T)/6 (calc_dielectrics).
   */
  function pitzerValues(pz, tc, atm, out) {
    const tk = tc + 273.15;
    for (let i = 0; i < pz.np; i++) out[i] = pitzerParam(pz.params[i].a, tk);
    return pz.aphi ? pitzerParam(pz.aphi.a, Math.min(tc, 350) + 273.15) : debyeHuckelAB(tc, atm).A0;
  }

  /*
    E-THETA, the higher-order electrostatic terms of two ions of one sign,
    as PHREEQC works them out (ETHETAS, with Harvie's Chebyshev approximation
    of J in ETHETA_PARAMS): x = 6 z_i z_j A_phi sqrt(I), and

      E-theta  = z_j z_k (J(x_jk) - J(x_jj)/2 - J(x_kk)/2) / (4 I)
      E-theta' = z_j z_k (x J'(x) ...) / (8 I^2) - E-theta / I

    and its second derivative in I, which the Jacobian reads, from the
    series' second derivative.
  */
  const PZ_AK = Float64Array.from([
    1.925154014814667e0, -.060076477753119e0, -.029779077456514e0,
    -.007299499690937e0, 0.000388260636404e0, 0.000636874599598e0,
    0.000036583601823e0, -.000045036975204e0, -.000004537895710e0,
    0.000002937706971e0, 0.000000396566462e0, -.000000202099617e0,
    -.000000025267769e0, 0.000000013522610e0, 0.000000001229405e0,
    -.000000000821969e0, -.000000000050847e0, 0.000000000046333e0,
    0.000000000001943e0, -.000000000002563e0, -.000000000010991e0,
    0.628023320520852e0, 0.462762985338493e0, 0.150044637187895e0,
    -.028796057604906e0, -.036552745910311e0, -.001668087945272e0,
    0.006519840398744e0, 0.001130378079086e0, -.000887171310131e0,
    -.000242107641309e0, 0.000087294451594e0, 0.000034682122751e0,
    -.000004583768938e0, -.000003548684306e0, -.000000250453880e0,
    0.000000216991779e0, 0.000000080779570e0, 0.000000004558555e0,
    -.000000006944757e0, -.000000002849257e0, 0.000000000237816e0,
  ]);
  const pzBK = new Float64Array(23);
  const pzDK = new Float64Array(23);
  const pzEK = new Float64Array(23);
  /** J(x) into out[0], PHREEQC's x J'(x) into out[1], J'(x) into out[2] and J''(x) into out[3]. */
  function pzJ(X, out) {
    let L_Z;
    let L_DZ;
    let dz;
    let ddz;
    let o;
    if (X <= 1.0) {
      const p = Math.pow(X, 0.2);
      L_Z = 4.0 * p - 2.0;
      L_DZ = (0.8 * p) / 2.0;
      dz = (0.8 * p) / X;
      ddz = (-0.64 * p) / (X * X);
      o = 0;
    } else {
      const p = Math.pow(X, -0.1);
      L_Z = (40.0 * p - 22.0) / 9.0;
      L_DZ = (-4.0 * p) / 18.0;
      dz = (-4.0 * p) / (9.0 * X);
      ddz = (4.4 * p) / (9.0 * X * X);
      o = 21;
    }
    const BK = pzBK;
    const DK = pzDK;
    const EK = pzEK;
    BK[20] = PZ_AK[o + 20];
    BK[19] = L_Z * PZ_AK[o + 20] + PZ_AK[o + 19];
    DK[20] = 0;
    DK[19] = PZ_AK[o + 20];
    EK[20] = 0;
    EK[19] = 0;
    for (let i = 18; i >= 0; i--) {
      BK[i] = L_Z * BK[i + 1] - BK[i + 2] + PZ_AK[o + i];
      DK[i] = BK[i + 1] + L_Z * DK[i + 1] - DK[i + 2];
      EK[i] = 2 * DK[i + 1] + L_Z * EK[i + 1] - EK[i + 2];
    }
    out[0] = X / 4.0 - 1.0 + 0.5 * (BK[0] - BK[2]);
    out[1] = X * 0.25 + L_DZ * (DK[0] - DK[2]);
    const Sz = 0.5 * (DK[0] - DK[2]);
    out[2] = 0.25 + Sz * dz;
    out[3] = 0.5 * (EK[0] - EK[2]) * dz * dz + Sz * ddz;
  }
  const pzJjk = new Float64Array(4);
  const pzJjj = new Float64Array(4);
  const pzJkk = new Float64Array(4);
  /**
   * E-theta of charges zj and zk at I, and its first and second derivatives
   * in I, into out[0..2]; and A_phi times E-theta's and E-theta''s
   * derivatives in A_phi into out[3] and out[4], x going as A_phi as it goes
   * as sqrt(I).
   */
  function pzEtheta(ZJ, ZK, I, A0, out) {
    out[0] = 0; out[1] = 0; out[2] = 0; out[3] = 0; out[4] = 0;
    if (ZJ === ZK) return;
    const XCON = 6.0 * A0 * Math.sqrt(I);
    const ZZ = ZJ * ZK;
    const XJK = XCON * ZZ;
    const XJJ = XCON * ZJ * ZJ;
    const XKK = XCON * ZK * ZK;
    pzJ(XJK, pzJjk);
    pzJ(XJJ, pzJjj);
    pzJ(XKK, pzJkk);
    const et = (ZZ * (pzJjk[0] - pzJjj[0] / 2.0 - pzJkk[0] / 2.0)) / (4.0 * I);
    const L = pzJjk[1] - pzJjj[1] / 2.0 - pzJkk[1] / 2.0;
    const etp = (ZZ * L) / (8.0 * I * I) - et / I;
    // dL/dI: each x J'(x) term's (J' + x J'') x/(2I).
    const dL = ((pzJjk[2] + XJK * pzJjk[3]) * XJK - ((pzJjj[2] + XJJ * pzJjj[3]) * XJJ) / 2
      - ((pzJkk[2] + XKK * pzJkk[3]) * XKK) / 2) / (2 * I);
    out[0] = et;
    out[1] = etp;
    out[2] = (ZZ * dL) / (8 * I * I) - (ZZ * L) / (4 * I * I * I) - etp / I + et / (I * I);
    // In A_phi: each J(x) by x J'(x), and L by its derivative in I times 2I.
    out[3] = (ZZ * L) / (4.0 * I);
    out[4] = (ZZ * dL) / (4 * I) - (ZZ * L) / (4 * I * I);
  }

  /** PHREEQC's G and GP of Pitzer's B and B' (pitzer.cpp), and their derivatives in y. */
  function pzG(y) { return y !== 0 ? (2.0 * (1.0 - (1.0 + y) * Math.exp(-y))) / (y * y) : 0; }
  function pzGP(y) { return y !== 0 ? (-2.0 * (1.0 - (1.0 + y + (y * y) / 2.0) * Math.exp(-y))) / (y * y) : 0; }
  /** d GP/dy: GP = -2Q/y^2 with dQ/dy = y^2 e^-y / 2. */
  function pzGPy(y) {
    if (y === 0) return 0;
    const Q = 1.0 - (1.0 + y + (y * y) / 2.0) * Math.exp(-y);
    return -Math.exp(-y) + (4 * Q) / (y * y * y);
  }

  /**
   * PHREEQC's OSMOT alone (pitzer()), the sum the osmotic coefficient is 1 +
   * 2/sum m of: the first pass of pitzerAt, for the water's activity. A_phi
   * times OSMOT's derivative in it, its Debye-Hueckel term's and E-theta's,
   * into pz.osA.
   */
  function pitzerOsmotic(pz, val, M, I, BIGZ, A0) {
    const { z, params } = pz;
    const DI = Math.sqrt(I);
    let OSMOT = (-A0 * Math.pow(I, 1.5)) / (1.0 + 1.2 * DI);
    let osA = OSMOT;
    const present3 = (q) => M[q] > 1e-25 || (pz.icon && q === pz.cl);
    for (let j = 0; j < params.length; j++) {
      const p = params[j];
      const [i0, i1, i2] = p.q;
      const param = val[j];
      const mm = M[i0] * M[i1];
      switch (p.type) {
        case 'B0':
        case 'THETA': OSMOT += mm * param; break;
        case 'B1':
        case 'B2': if (param !== 0.0) OSMOT += mm * param * Math.exp(-p.alpha * DI); break;
        case 'C0': OSMOT += (mm * BIGZ * param) / (2.0 * Math.sqrt(Math.abs(z[i0] * z[i1]))); break;
        case 'PSI':
        case 'ZETA':
        case 'ETA': if (present3(i2)) OSMOT += mm * M[i2] * param; break;
        case 'LAMBDA': OSMOT += mm * param * p.os; break;
        case 'MU': if (present3(i2)) OSMOT += mm * M[i2] * param * p.os; break;
        default: break;
      }
    }
    const et = pz.J;
    for (const [i0, i1] of pz.ethetaPairs) {
      pzEtheta(z[i0], z[i1], I, A0, et);
      OSMOT += M[i0] * M[i1] * (et[0] + I * et[1]);
      osA += M[i0] * M[i1] * (et[3] + I * et[4]);
    }
    pz.osA = osA;
    return OSMOT;
  }

  /**
   * activityAt under Pitzer, PHREEQC's (pitzer.cpp, pitzer()): each solute's
   * ln gamma into lnG and d(ln gamma)/dI at fixed molalities into dG, the
   * water's ln a from the osmotic coefficient, and with them what sitPartners
   * reads: d(ln gamma_i)/d(m_k) at fixed I, in pz.D over the system's species
   * (n x n), and d(ln a(H2O))/dC_k in dAwv. A species on an exchanger takes its
   * ion's coefficient (activityModel's form 5), as PHREEQC's
   * -pitzer_exchange_gammas has it.
   *
   * PHREEQC's rules, kept: nothing below 1e-40 mol/kg (its under()); a term
   * of three species is left out where the third is at 1e-25 or less, Cl-
   * excepted under the MacInnes scaling; B = 1.2, with PHREEQC's pressure
   * corrections of F for ions of charge 1 and 2 above one atmosphere; ln
   * gamma of every ion moved by its charge times ln gamma(Cl-) less that of
   * KCl at the ionic strength, the MacInnes scaling.
   *
   * And A_phi, which PHREEQC works out afresh at every iteration from the
   * water at the vapour pressure times the a(H2O) it has (k_temp, with
   * calc_rho_0 and calc_dielectrics), so that where it settles A_phi is the
   * one of the water's own a(H2O), the a(H2O) OSMOT gives with that A_phi.
   * OSMOT goes with A_phi as its Debye-Hueckel term and E-theta do, A_phi
   * with ln a(H2O) as waterAt has it; from a first pass at the pure water's
   * A_phi, one Newton step on that line reaches it to round-off, and where
   * the step crosses one of A_phi's corners it is taken afresh until it
   * settles. The corrections of F for charges 1 and 2 above one atmosphere
   * read the pressure the water is at there, the vapour pressure times
   * a(H2O) where that is the higher (PHREEQC's patm_x). Both go into the
   * derivatives: each ln gamma's in ln a(H2O) into dGw, and A_phi's part in
   * a(H2O)'s own gradient into dAwv. APHI, where given, is PHREEQC's A_phi
   * whatever the water, and the pressure still the water's.
   */
  function pitzerAt(act, C, off, I, low, osum, lnG, dG, cell) {
    const ns = act.ns;
    const pz = act.pz;
    const n = pz.n;
    const { M, LG, LI, D, dF, dCS, zc, dOS, LA, LP, z, modelOf, params } = pz;
    const val = pz.valc ? pz.valc.subarray(cell * pz.np, (cell + 1) * pz.np) : pz.val;
    const TK = pz.tkc ? pz.tkc[cell] : pz.tk;
    for (let q = 0; q < n; q++) {
      const s = modelOf[q];
      const c = s >= 0 ? C[off + s] : 0;
      M[q] = c < 1e-40 ? 0 : c;
      LG[q] = 0; LI[q] = 0; dF[q] = 0; dCS[q] = 0; zc[q] = 0; dOS[q] = 0; LA[q] = 0; LP[q] = 0;
    }
    D.fill(0);
    let BIGZ = 0;
    for (let q = 0; q < n; q++) BIGZ += M[q] * Math.abs(z[q]);
    let A0 = pz.A0c ? pz.A0c[cell] : pz.A0;
    const wt = act.wtc ? act.wtc[cell] : act.wt;
    let patm = pz.patm;
    // d ln A_phi/d ln a(H2O), and d patm/d ln a(H2O).
    let dlnA0 = 0;
    let dAtm = 0;
    if (wt && (!pz.aphi || wt.pSat > wt.atmGiven)) {
      // ln a(H2O) = -(sum m + 2 OSMOT)/55.50837, OSMOT = os1 + osA (A_phi/A1 - 1) on the line through the first pass.
      const A1 = A0;
      const os1 = pitzerOsmotic(pz, val, M, I, BIGZ, A1);
      const L0 = -(osum + 2.0 * os1) / PZ_WATER;
      const ws = waterAt(wt, Math.exp(L0), undefined, pz.ws);
      if (!pz.aphi) {
        const c = (2.0 * pz.osA) / PZ_WATER;
        const r0 = ws.A0 / A1;
        let L = L0 - (c * (r0 - 1)) / (1 + c * r0 * ws.dlnA);
        if (waterSide(wt, L) !== waterSide(wt, L0)) {
          for (let it = 0; it < 8; it++) {
            const next = L0 - c * (waterAt(wt, Math.exp(L), undefined, ws).A0 / A1 - 1);
            const step = Math.abs(next - L);
            L = next;
            if (step <= 1e-16 * Math.max(1, Math.abs(L))) break;
          }
        }
        waterAt(wt, Math.exp(L), undefined, ws);
        A0 = ws.A0;
        dlnA0 = ws.dlnA;
      }
      patm = ws.atm;
      dAtm = ws.dAtm;
    }
    const DI = Math.sqrt(I);
    const B = 1.2;
    // F, and F1 and F2 for ions of charge 1 and 2 above one atmosphere, with their derivatives in I.
    const fDH = (b) => -A0 * (DI / (1.0 + b * DI) + (2.0 * Math.log(1.0 + b * DI)) / b);
    const fDHI = (b) => (-A0 * (3 + 2 * b * DI)) / (2 * DI * (1 + b * DI) * (1 + b * DI));
    const fDHb = (b) => {
      const u = 1.0 + b * DI;
      return -A0 * (-(DI * DI) / (u * u) + (2.0 * DI) / (b * u) - (2.0 * Math.log(u)) / (b * b));
    };
    let F = fDH(B);
    let F1 = F;
    let F2 = F;
    let FI = fDHI(B);
    let F1I = FI;
    let F2I = FI;
    // A_phi times their derivatives in it (the Debye-Hueckel terms' are themselves), and F1's and F2's in the pressure.
    let FA = F;
    let F1A = F;
    let F2A = F;
    let F1P = 0;
    let F2P = 0;
    if (patm > 1.0) {
      const k1 = 7e-5 + 1.93e-9 * Math.pow(TK - 250.0, 2.0);
      let pap = k1 * patm;
      const B1 = B - (pap > 0.2 ? 0.2 : pap);
      const dB1 = pap > 0.2 ? 0 : -k1;
      let dpap = k1;
      if (TK > 263.0) {
        pap = 9.65e-10 * Math.pow(TK - 263.0, 2.773) * Math.pow(patm, 0.623);
        dpap = (0.623 * pap) / patm;
      }
      const B2 = B - (pap > 0.2 ? 0.2 : pap);
      const dB2 = pap > 0.2 ? 0 : -dpap;
      if (B1 !== 0) { F1 = fDH(B1); F1I = fDHI(B1); F1A = F1; F1P = fDHb(B1) * dB1; }
      if (B2 !== 0) { F2 = fDH(B2); F2I = fDHI(B2); F2A = F2; F2P = fDHb(B2) * dB2; }
    }
    // ln gamma of KCl at I, the MacInnes scaling's reference, and its derivative.
    let XXX = 2.0 * DI;
    const y = XXX;
    XXX = (1.0 - (1.0 + XXX - XXX * XXX * 0.5) * Math.exp(-XXX)) / (XXX * XXX);
    const XXXy = ((2 * y - (y * y) / 2) * Math.exp(-y)) / (y * y) - (2 * XXX) / y;
    let GAMCLM = F1;
    let GAMCLMI = F1I;
    const GAMCLMA = F1A;
    const GAMCLMP = F1P;
    const { mc } = pz;
    if (mc.b0 >= 0) { GAMCLM += I * 2.0 * val[mc.b0]; GAMCLMI += 2.0 * val[mc.b0]; }
    if (mc.b1 >= 0) {
      GAMCLM += I * 2.0 * val[mc.b1] * XXX;
      GAMCLMI += 2.0 * val[mc.b1] * (XXX + (I * XXXy) / DI);
    }
    if (mc.c0 >= 0) { GAMCLM += 1.5 * val[mc.c0] * I * I; GAMCLMI += 3.0 * val[mc.c0] * I; }
    let CSUM = 0;
    let OSMOT = (-A0 * Math.pow(I, 1.5)) / (1.0 + B * DI);
    let OSI = -A0 * ((1.5 * DI) / (1 + B * DI) - (B * I) / (2 * (1 + B * DI) * (1 + B * DI)));
    let osA = OSMOT;
    let osZ = 0;
    const present3 = (q) => M[q] > 1e-25 || (pz.icon && q === pz.cl);
    const Dat = (i, k, v) => { D[i * n + k] += v; };
    for (let j = 0; j < params.length; j++) {
      const p = params[j];
      const [i0, i1, i2] = p.q;
      const param = val[j];
      const M0 = M[i0];
      const M1 = M[i1];
      switch (p.type) {
        case 'B0':
          LG[i0] += M1 * 2.0 * param;
          LG[i1] += M0 * 2.0 * param;
          OSMOT += M0 * M1 * param;
          Dat(i0, i1, 2.0 * param); Dat(i1, i0, 2.0 * param);
          dOS[i0] += M1 * param; dOS[i1] += M0 * param;
          break;
        case 'B1':
        case 'B2': {
          if (param === 0.0) break;
          const x = p.alpha * DI;
          const g = pzG(x);
          const gp = pzGP(x);
          const e = Math.exp(-x);
          const Fvar = (M0 * M1 * param * gp) / I;
          F += Fvar; F1 += Fvar; F2 += Fvar;
          const FvarI = M0 * M1 * param * ((pzGPy(x) * p.alpha) / (2 * DI * I) - gp / (I * I));
          FI += FvarI; F1I += FvarI; F2I += FvarI;
          dF[i0] += (M1 * param * gp) / I; dF[i1] += (M0 * param * gp) / I;
          LG[i0] += M1 * 2.0 * param * g;
          LG[i1] += M0 * 2.0 * param * g;
          LI[i0] += (M1 * 2.0 * param * gp) / I;
          LI[i1] += (M0 * 2.0 * param * gp) / I;
          Dat(i0, i1, 2.0 * param * g); Dat(i1, i0, 2.0 * param * g);
          OSMOT += M0 * M1 * param * e;
          OSI += (-M0 * M1 * param * p.alpha * e) / (2 * DI);
          dOS[i0] += M1 * param * e; dOS[i1] += M0 * param * e;
          break;
        }
        case 'C0': {
          const c = param / (2.0 * Math.sqrt(Math.abs(z[i0] * z[i1])));
          CSUM += M0 * M1 * c;
          dCS[i0] += M1 * c; dCS[i1] += M0 * c;
          LG[i0] += M1 * BIGZ * c;
          LG[i1] += M0 * BIGZ * c;
          Dat(i0, i1, BIGZ * c); Dat(i1, i0, BIGZ * c);
          zc[i0] += M1 * c; zc[i1] += M0 * c;
          OSMOT += M0 * M1 * BIGZ * c;
          dOS[i0] += M1 * BIGZ * c; dOS[i1] += M0 * BIGZ * c;
          osZ += M0 * M1 * c;
          break;
        }
        case 'THETA':
          LG[i0] += 2.0 * M1 * param;
          LG[i1] += 2.0 * M0 * param;
          OSMOT += M0 * M1 * param;
          Dat(i0, i1, 2.0 * param); Dat(i1, i0, 2.0 * param);
          dOS[i0] += M1 * param; dOS[i1] += M0 * param;
          break;
        case 'PSI':
        case 'ZETA':
        case 'ETA': {
          if (!present3(i2)) break;
          const M2 = M[i2];
          LG[i0] += M1 * M2 * param;
          LG[i1] += M0 * M2 * param;
          LG[i2] += M0 * M1 * param;
          OSMOT += M0 * M1 * M2 * param;
          Dat(i0, i1, M2 * param); Dat(i0, i2, M1 * param);
          Dat(i1, i0, M2 * param); Dat(i1, i2, M0 * param);
          Dat(i2, i0, M1 * param); Dat(i2, i1, M0 * param);
          dOS[i0] += M1 * M2 * param; dOS[i1] += M0 * M2 * param; dOS[i2] += M0 * M1 * param;
          break;
        }
        case 'LAMBDA':
          LG[i0] += M1 * param * p.lc[0];
          LG[i1] += M0 * param * p.lc[1];
          OSMOT += M0 * M1 * param * p.os;
          Dat(i0, i1, param * p.lc[0]); Dat(i1, i0, param * p.lc[1]);
          dOS[i0] += M1 * param * p.os; dOS[i1] += M0 * param * p.os;
          break;
        case 'MU': {
          if (!present3(i2)) break;
          const M2 = M[i2];
          LG[i0] += M1 * M2 * param * p.lc[0];
          LG[i1] += M0 * M2 * param * p.lc[1];
          LG[i2] += M0 * M1 * param * p.lc[2];
          OSMOT += M0 * M1 * M2 * param * p.os;
          Dat(i0, i1, M2 * param * p.lc[0]); Dat(i0, i2, M1 * param * p.lc[0]);
          Dat(i1, i0, M2 * param * p.lc[1]); Dat(i1, i2, M0 * param * p.lc[1]);
          Dat(i2, i0, M1 * param * p.lc[2]); Dat(i2, i1, M0 * param * p.lc[2]);
          dOS[i0] += M1 * M2 * param * p.os; dOS[i1] += M0 * M2 * param * p.os; dOS[i2] += M0 * M1 * param * p.os;
          break;
        }
        default:
          break;
      }
    }
    // E-theta, a pair at a time, from the tables of the charges at I.
    if (pz.ethetaPairs.length) {
      const et = pz.J;
      for (const [i0, i1] of pz.ethetaPairs) {
        const M0 = M[i0];
        const M1 = M[i1];
        pzEtheta(z[i0], z[i1], I, A0, et);
        const Fvar = M0 * M1 * et[1];
        F += Fvar; F1 += Fvar; F2 += Fvar;
        const FvarI = M0 * M1 * et[2];
        FI += FvarI; F1I += FvarI; F2I += FvarI;
        const FvarA = M0 * M1 * et[4];
        FA += FvarA; F1A += FvarA; F2A += FvarA;
        dF[i0] += M1 * et[1]; dF[i1] += M0 * et[1];
        LG[i0] += 2.0 * M1 * et[0];
        LG[i1] += 2.0 * M0 * et[0];
        LA[i0] += 2.0 * M1 * et[3];
        LA[i1] += 2.0 * M0 * et[3];
        LI[i0] += 2.0 * M1 * et[1];
        LI[i1] += 2.0 * M0 * et[1];
        Dat(i0, i1, 2.0 * et[0]); Dat(i1, i0, 2.0 * et[0]);
        OSMOT += M0 * M1 * (et[0] + I * et[1]);
        OSI += M0 * M1 * (2 * et[1] + I * et[2]);
        osA += M0 * M1 * (et[3] + I * et[4]);
        dOS[i0] += M1 * (et[0] + I * et[1]); dOS[i1] += M0 * (et[0] + I * et[1]);
      }
    }
    // F and CSUM into every ion's, the charge's F; C's Z into every row it is in.
    for (let q = 0; q < n; q++) {
      const zq = z[q];
      if (zq !== 0) {
        const z0 = Math.abs(zq);
        const Fv = z0 === 1 ? F1 : z0 === 2.0 ? F2 : F;
        const FvI = z0 === 1 ? F1I : z0 === 2.0 ? F2I : FI;
        LG[q] += z0 * z0 * Fv + z0 * CSUM;
        LI[q] += z0 * z0 * FvI;
        LA[q] += z0 * z0 * (z0 === 1 ? F1A : z0 === 2.0 ? F2A : FA);
        LP[q] += z0 * z0 * (z0 === 1 ? F1P : z0 === 2.0 ? F2P : 0);
        const z2 = z0 * z0;
        const at = q * n;
        for (let k = 0; k < n; k++) D[at + k] += z2 * dF[k] + z0 * dCS[k];
      }
      if (zc[q] !== 0) {
        const at = q * n;
        for (let k = 0; k < n; k++) D[at + k] += zc[q] * Math.abs(z[k]);
      }
    }
    // The MacInnes scaling.
    if (pz.icon) {
      const cl = pz.cl;
      const PHIMAC = LG[cl] - GAMCLM;
      const PHII = LI[cl] - GAMCLMI;
      const PHIA = LA[cl] - GAMCLMA;
      const PHIP = LP[cl] - GAMCLMP;
      const row = pz.row;
      for (let k = 0; k < n; k++) row[k] = D[cl * n + k];
      for (let q = 0; q < n; q++) {
        const zq = z[q];
        if (!zq) continue;
        LG[q] += zq * PHIMAC;
        LI[q] += zq * PHII;
        LA[q] += zq * PHIA;
        LP[q] += zq * PHIP;
        const at = q * n;
        for (let k = 0; k < n; k++) D[at + k] += zq * row[k];
      }
    }
    // The species of the model, and how each ln gamma goes with ln a(H2O): through A_phi and the pressure.
    const dGw = act.dGw;
    for (let s = 0; s < ns; s++) {
      if (act.form[s] !== 6) { lnG[s] = 0; dG[s] = 0; if (dGw) dGw[s] = 0; continue; }
      const q = pz.sysOf[s];
      lnG[s] = LG[q];
      dG[s] = low ? 0 : LI[q];
      if (dGw) dGw[s] = LA[q] * dlnA0 + LP[q] * dAtm;
    }
    const ex = act.ex;
    if (ex) {
      for (const s of ex.list) {
        if (act.form[s] !== 5) continue;
        lnG[s] = lnG[ex.ion[s]];
        dG[s] = dG[ex.ion[s]];
        if (dGw) dGw[s] = dGw[ex.ion[s]];
      }
    }
    onSites(act, lnG, dG, cell);
    if (act.gas && act.gas.dln) prVolumeCoefficients(act, C, off, lnG, cell);
    /*
      The water: ln a = -(sum m) COSMOT/55.50837, COSMOT = 1 + 2 OSMOT/sum m,
      and its gradient, OSMOT's at A_phi as it is, over 1 + 2 A_phi
      dOSMOT/dA_phi dln A_phi/dln a(H2O)/55.50837 for A_phi going with it.
    */
    for (let k = 0; k < n; k++) dOS[k] += osZ * Math.abs(z[k]);
    const dAwv = pz.dAwv;
    const osIe = low ? 0 : OSI;
    const fix = PZ_WATER + 2.0 * osA * dlnA0;
    for (let s = 0; s < ns; s++) {
      if (!act.solute[s]) { dAwv[s] = 0; continue; }
      const q = pz.sysOf[s];
      dAwv[s] = -(1 + 2 * (dOS[q] + osIe * 0.5 * z[q] * z[q])) / fix;
    }
    const lnAw = osum > 0 ? (-osum * (1.0 + (2.0 * OSMOT) / osum)) / PZ_WATER : (-2.0 * OSMOT) / PZ_WATER;
    pz.stamp++;
    return { I, lnAw, dAw: 0, dAwv, dGw, pz: pz.stamp };
  }

  /**
   * Every species' ln gamma and d(ln gamma)/dI at the ionic strength I of
   * cell `cell` (activityAt, which works I out first; the reduced
   * speciation, which solves for it). `low`: I is the floor, and the
   * derivatives are zero.
   */
  function coefficientsAt(act, I, low, lnG, dG, cell, aw = 1) {
    const ns = act.ns;
    const sq = Math.sqrt(I);
    /*
      A and B at the cell's temperature where it differs between cells or
      goes with time, and at the water's activity: PHREEQC works the density
      of water out at the vapour pressure times a(H2O) (calc_rho_0), afresh
      at each iteration, and A and B go as its square root; above 100 C the
      water's pressure, and with it the dielectric constant, is that vapour
      pressure. At a(H2O) = 1 they are the ones kept. Their derivative in
      ln a(H2O) goes into dGw where the water can be above 100 C, on its
      vapour pressure or near it (act.dGw); below, it is a part in 1e5 of a
      coefficient's at most, and is left out of the Jacobian.
    */
    let A;
    let B;
    let dlnA = 0;
    let dlnB = 0;
    const dGw = act.dGw;
    if (aw !== 1 && act.wt) {
      const w = waterAt(act.wtc ? act.wtc[cell] : act.wt, aw);
      A = w.A * Math.LN10;
      B = w.B;
      dlnA = w.dlnA;
      dlnB = w.dlnB;
    } else {
      A = (act.Ac ? act.Ac[cell] : act.A) * Math.LN10;
      B = act.Bc ? act.Bc[cell] : act.B;
    }
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
          if (dGw) dGw[s] = lnG[s] * dlnA;
          break;
        }
        case 3: {
          const den = 1 + B * act.a[s] * sq;
          const dh = -A * z2 * sq / den;
          lnG[s] = dh + Math.LN10 * act.b[s] * I;
          dG[s] = -A * z2 * 0.5 / (sq * den * den) + Math.LN10 * act.b[s];
          if (dGw) dGw[s] = dh * (dlnA - ((B * act.a[s] * sq) / den) * dlnB);
          break;
        }
        case 7: {
          // LLNL's B-dot: -A z^2 sqrt(I)/(1 + a B sqrt(I)) + B-dot I, its tables' A, B and B-dot; 1 for a neutral species.
          if (!z2) { lnG[s] = 0; dG[s] = 0; break; }
          const bdot = act.bdotc ? act.bdotc[cell] : act.bdot;
          const den = 1 + act.a[s] * B * sq;
          lnG[s] = -A * z2 * sq / den + Math.LN10 * bdot * I;
          dG[s] = -A * z2 * 0.5 / (sq * den * den) + Math.LN10 * bdot;
          break;
        }
        case 8: {
          // Drummond's CO2, ln gamma = (c1 + c2 T + c3/T) I - (c4 + c5 T) I/(I + 1), T in kelvin.
          const c = act.llnl.co2;
          const tk = act.tk ? act.tk[cell] : act.temperature + 273.15;
          const k1 = c[0] + c[1] * tk + c[2] / tk;
          const k2 = c[3] + c[4] * tk;
          lnG[s] = k1 * I - k2 * (I / (I + 1));
          dG[s] = k1 - k2 / ((I + 1) * (I + 1));
          break;
        }
        default:
          lnG[s] = 0;
          dG[s] = 0;
      }
      if (low) dG[s] = 0;
      if (dGw && act.form[s] !== 2 && act.form[s] !== 3) dGw[s] = 0;
    }
    onSites(act, lnG, dG, cell);
  }

  /**
   * The coefficients of what is on an exchanger or a surface, once the rest
   * are known (coefficientsAt, sitAt).
   */
  function onSites(act, lnG, dG, cell) {
    const ns = act.ns;
    /*
      On an exchanger, PHREEQC's Gaines-Thomas: the activity is the
      equivalent fraction, n C over the capacity of the cell, n the sites the
      species takes, times its ion's coefficient to the ion's power in the
      relation. ln(n/capacity) is the cell's, set when the capacity is known.
    */
    const ex = act.ex;
    if (ex) {
      const at = cell * ns;
      for (const s of ex.list) {
        lnG[s] = ex.pw[s] * lnG[s] + ex.shift[at + s];
        dG[s] *= ex.pw[s];
        if (act.dGw) act.dGw[s] *= ex.pw[s];
      }
    }
    // On a surface, the fraction of its type's sites in the cell: n/sites, set when they are known.
    const sf = act.sf;
    if (sf) {
      const at = cell * ns;
      for (const s of sf.list) {
        lnG[s] = sf.shift[at + s];
        dG[s] = 0;
        if (act.dGw) act.dGw[s] = 0;
      }
    }
    // A gas in a fixed volume: its partial pressure n R T/V.
    const gas = act.gas;
    if (gas && gas.fixed === 'volume') {
      const g = gas.lnGc ? gas.lnGc[cell] : gas.lnG;
      for (const s of gas.list) {
        lnG[s] = g;
        dG[s] = 0;
        if (act.dGw) act.dGw[s] = 0;
      }
    }
    // Real gases: Peng and Robinson's a alpha and R T at the cell's temperature, for what follows.
    if (gas && gas.pr && act.tk) prAt(gas.pr, act.tk[cell]);
  }

  /**
   * Activities without ACTIVITY: every coefficient 1, the water's activity 1,
   * and the charges the names give, which I() in a rate law reads.
   */
  function noActivity(species) {
    const ns = species.length;
    const z = Float64Array.from(species, (sp) => (sp.mineral || sp.exchange || sp.exchanger || sp.electron || sp.surface
      || sp.potential || sp.gas || sp.name === 'H2O' ? 0 : (sp.z !== null ? sp.z : chargeOf(sp.name))));
    return { kind: 'none', A: 0, B: 0, ns, z, zg: new Float64Array(ns), form: new Uint8Array(ns),
      a: new Float64Array(ns), b: new Float64Array(ns), solute: new Uint8Array(ns), ex: null, sf: null, pt: null,
      gas: null };
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
    /*
      SITES THAT GO WITH A MINERAL: a species on an exchanger given sites=
      per=, CaX2 exchange sites=0.33 per=Montmorillonite -- PHREEQC's
      `CaX2 Montmorillonite equilibrium_phase 0.165`, the exchange formula
      charge-balanced with its ion, so many of it to each mole. The
      exchanger's capacity is then `sites` times the mineral's amount in the
      cell at every moment, the mineral carrying sites/n of that species to
      each mole of it: held at saturation, its relation carries it for the
      totals alone (eq.carry, conservationBasis); made and used at a rate,
      every reaction that changes it does (compile). As the mineral
      dissolves the sites go, in that species' form, and what was on them
      comes off; and a species on the exchanger has for its activity n C over
      what is on it now (exchangeFractions), its equivalent fraction at the
      capacity the totals keep.
    */
    const per = exchangers.map(() => null);
    for (const k of onSites) {
      const sp = species[k];
      if (sp.per === null) continue;
      const x = of[k];
      const xn = species[exchangers[x]].name;
      const m = species.findIndex((y) => y.name === sp.per);
      if (m < 0 || !species[m].mineral) {
        throw new RtmError(`${sp.name} has the sites of ${xn} go with ${sp.per}, which is no mineral in <SPECIES>: per `
          + 'names the mineral the sites go with, a mole of it at a time.', sp.line);
      }
      if (per[x]) {
        throw new RtmError(`The sites of ${xn} go with ${species[per[x].mineral].name} in the form of `
          + `${species[per[x].species].name}, and ${sp.name} is given sites= per= as well: one species on an exchanger `
          + 'is the form its sites go in.', sp.line);
      }
      if (settings.EQUILIBRATE !== 2) {
        throw new RtmError(`The sites of ${xn} go with ${sp.per}, and its relations are to follow them all through the `
          + 'run: EQUILIBRATE = always.', sp.line);
      }
      const rel = equilibria.filter((eq) => eq.net.some(([si]) => si === m));
      if (rel.length > 1) {
        throw new RtmError(`${sp.name} has the sites of ${xn} go with ${sp.per}: they go with the amount of a mineral held `
          + `at saturation by its relation, or made and used at a rate, and ${sp.per} has more than one relation in `
          + '<EQUILIBRIUM>.', sp.line);
      }
      for (const eq of equilibria) {
        if (eq.kf !== null && eq.net.some(([s]) => carries(s) && of[s] === x)) {
          throw new RtmError(`"${eq.text}" is on ${xn}, whose sites go with ${sp.per}, and has a rate, kf: the species on `
            + 'such an exchanger have the fraction of what is on it now for their activity, and are held (EQUILIBRATE).',
          eq.line);
        }
      }
      if (rel.length === 1) {
        const nuM = rel[0].net.find(([si]) => si === m)[1];
        rel[0].carry = (rel[0].carry || []).concat([[k, (sp.sites * nuM) / n[k]]]);
      }
      per[x] = { species: k, mineral: m, ratio: sp.sites, eq: rel.length ? rel[0] : null };
    }

    const out = act || noActivity(species);
    out.form = Uint8Array.from(out.form);
    const pw = new Float64Array(ns);
    const ion = new Int32Array(ns).fill(-1);
    let unused = false;
    const sitAlone = [];
    const sitAB = [];
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
      /*
        Under SIT every species on an exchanger takes its ion's coefficient to
        the ion's power, a and b or not: PHREEQC's EXCHANGE does, unless told
        -pitzer_exchange_gammas false. Its coefficient reads what the ion's
        does, so its row of partners is the ion's, times the power.
      */
      if (out.sit || out.pz) {
        if (ion[k] >= 0 && out.form[ion[k]] === (out.sit ? 4 : 6)) {
          out.form[k] = 5;
          const r = out.sit ? out.sit.rows[ion[k]] : null;
          if (r) out.sit.rows[k] = { k: r.k, e: r.e.map((v) => v * pw[k]), e1: r.e1.map((v) => v * pw[k]) };
        } else sitAlone.push(sp.name);
        if (sp.dha !== null) sitAB.push(sp.name);
        continue;
      }
      if (sp.dha === null && sp.dhb === null) continue;
      // a and b together, as PHREEQC's -gamma a b; under LLNL's model a alone, its -llnl_gamma.
      if (settings.ACTIVITY === 'llnl' ? sp.dha === null || sp.dhb !== null : (sp.dha === null) !== (sp.dhb === null)) {
        throw new RtmError(settings.ACTIVITY === 'llnl'
          ? `${sp.name} is on an exchanger and ACTIVITY = llnl: it takes a alone, as PHREEQC's -llnl_gamma a, or nothing.`
          : `${sp.name} is on an exchanger: it takes a and b together, as PHREEQC's -gamma a b, or neither.`, sp.line);
      }
      if (!act) { unused = true; continue; }
      if (ion[k] < 0) {
        throw new RtmError(`${sp.name} is given a and b, which give it its ion's activity coefficient, and no relation `
          + `forms it from ${species[exchangers[of[k]]].name} and one ion: Ca+2 + 2 X- <=> CaX2.`, sp.line);
      }
      const isp = species[ion[k]];
      out.zg[k] = isp.z !== null ? isp.z : chargeOf(isp.name);
      // Under LLNL's model, its ion's B-dot form with its own a (PHREEQC's -llnl_gamma on the exchange species).
      if (settings.ACTIVITY === 'llnl') {
        out.form[k] = 7;
        out.a[k] = sp.dha;
        if (!out.zg[k]) out.form[k] = 0;
        continue;
      }
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
    const kindName = out.pz ? 'pitzer' : 'sit';
    if (sitAB.length) {
      warnings.push(`ACTIVITY = ${kindName}: a species on an exchanger takes its ion's ${out.pz ? 'Pitzer' : 'SIT'} `
        + `coefficient, and the a and b given to ${sitAB.join(', ')} are not used.`);
    }
    if (sitAlone.length) {
      warnings.push(`ACTIVITY = ${kindName}: no relation forms ${sitAlone.join(', ')} from its exchanger and one ion in the `
        + 'water, so its activity is its equivalent fraction alone, with no ion\'s coefficient.');
    }
    const site = Int8Array.from(species, (sp) => (sp.exchange ? 1 : sp.exchanger ? 2 : 0));
    // Each exchanger's species, and where its sites go with a mineral, the derivatives' scratch (sitPartners).
    const members = exchangers.map((k, x) => onSites.filter((j) => of[j] === x));
    const perAny = per.some(Boolean);
    out.ex = { list: onSites, exchangers, n, of, pw, ion, site, shift: null, capacity: null, per, perAny, members,
      d: perAny ? new Float64Array(ns) : null };
    return out;
  }

  /**
   * An exchanger whose sites go with a mineral (exchangeSetup's per): each
   * species on it has for its activity n C over what is on it now, its
   * equivalent fraction, where onSites took the capacity the cell started
   * with -- ln gamma moved by ln(start/now). Returns what is on each such
   * exchanger, the sum of n C, for the derivatives (sitPartners): d ln gamma
   * / dC_j = -n_j/sum for every species j on it. Nothing moves where nothing
   * is on it yet, before it is loaded.
   */
  function exchangeFractions(act, C, off, lnG, cell) {
    const ex = act.ex;
    const nx = ex.exchangers.length;
    const sums = new Float64Array(nx);
    for (let x = 0; x < nx; x++) {
      if (!ex.per[x]) continue;
      let sum = 0;
      for (const j of ex.members[x]) sum += ex.n[j] * C[off + j];
      sums[x] = sum;
      if (!(sum > 0)) continue;
      const move = Math.log(ex.capacity[cell * nx + x] / sum);
      for (const j of ex.members[x]) lnG[j] += move;
    }
    return sums;
  }

  /** A number of sites as a reader would write it. */
  function fmtSites(v) { return String(+v.toPrecision(6)); }

  /**
   * SURFACE COMPLEXATION, as PHREEQC's SURFACE has it without electrostatics
   * (its -no_edl).
   *
   *   Hfo_wOH    surface  sites=2e-4     a site, and the sites of its type, loaded from the water
   *   Hfo_wOH2+  surface
   *   Hfo_wOZn+  surface
   *   Hfo_wOH + H+ <=> Hfo_wOH2+,         logK = 7.29
   *   Hfo_wOH + Zn+2 <=> Hfo_wOZn+ + H+,  logK = -1.99
   *
   * A species on a surface stays where it is, counts in no ionic strength
   * and no water, and has for its activity its fraction of the sites of its
   * type, n C over the sites in its cell: n the sites it takes, read off the
   * relations as an exchanger's are, the least of a type taking one -- as
   * PHREEQC has it, a species on two sites counting twice. A type is the
   * species the relations join, and its sites a total of their own, which
   * the relations keep. Unlike an exchanger's, a surface's master species is
   * an amount like the rest.
   *
   * Returns the activity model with the surface in it (one made for it when
   * ACTIVITY is none), or `act` itself when there is no surface.
   */
  function surfaceSetup(species, equilibria, act) {
    const ns = species.length;
    const on = [];
    species.forEach((sp, k) => { if (sp.surface) on.push(k); });
    if (!on.length) return act;
    const name = (k) => species[k].name;
    // The types: the species the relations join.
    const parent = Int32Array.from({ length: ns }, (_, i) => i);
    const find = (i) => { let r = i; while (parent[r] !== r) r = parent[r]; return r; };
    for (const eq of equilibria) {
      const sfs = eq.net.filter(([k]) => species[k].surface).map(([k]) => k);
      if (sfs.length && eq.net.some(([k]) => species[k].exchange || species[k].exchanger)) {
        throw new RtmError(`"${eq.text}" has a surface and an exchanger in it: a relation is on one.`, eq.line);
      }
      if (sfs.length && eq.mineral >= 0) {
        throw new RtmError(`"${eq.text}" has a mineral and a surface in it: a relation is one or the other.`, eq.line);
      }
      for (let i = 1; i < sfs.length; i++) {
        const a = find(sfs[0]);
        const b = find(sfs[i]);
        if (a !== b) parent[b] = a;
      }
    }
    const typeOf = new Int32Array(ns).fill(-1);
    const types = [];
    const rootType = new Map();
    for (const k of on) {
      const r = find(k);
      if (!rootType.has(r)) { rootType.set(r, types.length); types.push({ members: [] }); }
      typeOf[k] = rootType.get(r);
      types[typeOf[k]].members.push(k);
    }
    // The sites each takes: one for the first of a type, then through the relations.
    const n = new Float64Array(ns).fill(NaN);
    for (const t of types) n[t.members[0]] = 1;
    for (let changed = true; changed;) {
      changed = false;
      for (const eq of equilibria) {
        const sfs = eq.net.filter(([k]) => species[k].surface);
        const open = sfs.filter(([k]) => Number.isNaN(n[k]));
        if (open.length !== 1 || sfs.length < 2) continue;
        const [j, nu] = open[0];
        let sum = 0;
        for (const [k, c] of sfs) if (k !== j) sum += c * n[k];
        const v = -sum / nu;
        if (!(v > 0)) {
          throw new RtmError(`"${eq.text}" gives ${name(j)} no sites: a species on a surface is formed from another `
            + 'on it, Hfo_wOH + Zn+2 <=> Hfo_wOZn+ + H+.', eq.line);
        }
        n[j] = v;
        changed = true;
      }
    }
    const lost = on.filter((k) => Number.isNaN(n[k]));
    if (lost.length) {
      throw new RtmError(`The relations do not say how many sites ${lost.map(name).join(', ')} ${lost.length > 1 ? 'take'
        : 'takes'}: form each from one other species on its surface.`, species[lost[0]].line);
    }
    for (const t of types) {
      const least = Math.min(...t.members.map((k) => n[k]));
      for (const k of t.members) n[k] /= least;
    }
    for (const eq of equilibria) {
      const sfs = eq.net.filter(([k]) => species[k].surface);
      if (!sfs.length) continue;
      let sum = 0;
      let scale = 0;
      for (const [k, c] of sfs) { sum += c * n[k]; scale += Math.abs(c * n[k]); }
      if (Math.abs(sum) > 1e-9 * scale) {
        const side = (sg) => sfs.filter(([, c]) => c * sg > 0).reduce((acc, [k, c]) => acc + Math.abs(c) * n[k], 0);
        throw new RtmError(`"${eq.text}" does not keep the surface's sites: ${fmtSites(side(-1))} on the left and `
          + `${fmtSites(side(1))} on the right.`, eq.line);
      }
    }
    types.forEach((t) => {
      const given = t.members.filter((k) => species[k].sites !== null);
      if (given.length > 1) {
        throw new RtmError(`${given.map(name).join(' and ')} are on one surface and each given its sites: give them once.`,
          species[given[1]].line);
      }
      t.sitesFrom = given.length ? given[0] : -1;
    });
    /*
      SITES THAT GO WITH A MINERAL, PHREEQC's equilibrium_phase: sites= per
      mole of the mineral per= names, held at saturation by its relation. The
      type's sites are then that many times the mineral's amount in the cell
      at every moment: the mineral's relation carries them for the totals
      alone (eq.carry, conservationBasis), sites less ratio times the mineral
      a total of its own, so that as it dissolves its sites go, in its master
      species' form, and what was on them comes off; its saturation reads none
      of them. Each relation on such a surface takes as many of its species
      as it makes, so that the sites, n C over their number, come out of it.
    */
    types.forEach((t) => {
      t.per = null;
      if (t.sitesFrom < 0 || species[t.sitesFrom].per === null) return;
      const sp = species[t.sitesFrom];
      const m = species.findIndex((x) => x.name === sp.per);
      if (m < 0 || !species[m].mineral) {
        throw new RtmError(`${sp.name} has its sites per ${sp.per}, which is no mineral in <SPECIES>: per names the mineral `
          + 'the sites go with, a mole of it at a time.', sp.line);
      }
      const rel = equilibria.filter((eq) => eq.net.some(([si]) => si === m));
      if (rel.length > 1) {
        throw new RtmError(`${sp.name} has its sites per ${sp.per}: they go with the amount of a mineral held at saturation `
          + `by its relation, or made and used at a rate, and ${sp.per} has more than one relation in <EQUILIBRIUM>.`, sp.line);
      }
      for (const eq of equilibria) {
        let count = 0;
        let touches = false;
        for (const [si, c] of eq.net) if (typeOf[si] === typeOf[t.sitesFrom]) { count += c; touches = true; }
        if (touches && Math.abs(count) > 1e-12) {
          throw new RtmError(`"${eq.text}" takes ${count < 0 ? 'more' : 'fewer'} species of the surface of ${sp.name} than it `
            + `makes, and its sites go with ${sp.per}: on such a surface each relation takes as many of its species as it `
            + 'makes.', eq.line);
        }
      }
      /*
        Held at saturation, its relation carries the sites. Made and used at
        a rate -- a kinetic reactant, PHREEQC's kinetic_reactant -- every
        reaction that changes it carries them instead (compile): as it
        dissolves its sites go, and what was on them comes off.
      */
      if (rel.length === 1) {
        const nuM = rel[0].net.find(([si]) => si === m)[1];
        rel[0].carry = (rel[0].carry || []).concat([[t.sitesFrom, (sp.sites * nuM) / n[t.sitesFrom]]]);
      }
      t.per = { mineral: m, ratio: sp.sites, eq: rel.length ? rel[0] : null };
    });
    const out = act || noActivity(species);
    out.sf = { list: on, n, typeOf, types, shift: null, sites: null, load: [] };
    return out;
  }

  /*
    PHREEQC's constants for the double layer, its own and older than CODATA's:
    Faraday's 96493.5 C/mol, the gas constant 8.31470 J/(mol K), the
    permittivity of vacuum 8.854e-12 F/m. Its surfaces are worked out with
    these, and its potentials reported in volts with them; CODATA's would
    put a zinc water's molalities 5e-5 from PHREEQC's.
  */
  const FARADAY = 96493.5;
  const GAS_R = 8.31470;
  const EPSILON0 = 8.854e-12;

  /**
   * THE DIFFUSE DOUBLE LAYER, as PHREEQC's SURFACE has it unless told
   * -no_edl: Dzombak and Morel's model.
   *
   *   Hfo_psi    potential  area=600  grams=0.09     the potential of the surface Hfo
   *
   * A potential is a surface's: the species on a surface whose names begin
   * as its own does, up to and with the first underscore -- Hfo_psi is the
   * potential of Hfo_wOH, Hfo_sOZn+ and every other Hfo_ species, PHREEQC's
   * surface Hfo. It is no amount: its activity, exp(-F psi/RT), is solved for
   * in every cell. Each relation on its surface takes it as a reactant to
   * the charge the relation puts on the surface, dz, so that it holds with
   * K exp(-dz F psi/RT), as PHREEQC's do; and with each potential goes an
   * equation of its own, Gouy and Chapman's:
   *
   *   F Q/(A M) = sqrt(8000 R T eps eps0 I) sinh(F psi/2RT)
   *
   * Q the charge of the species on the surface, A its area in m2/g, M the
   * grams of the solid to each kilogram of water, I the ionic strength and
   * eps the dielectric constant of water at the TEMPERATURE (Bradley and
   * Pitzer, as PHREEQC has it). The potential counts in no total and is in
   * no ionic strength; a relation written with it is refused, the page
   * putting it in.
   *
   * Returns the activity model with the potentials in it (act.pt).
   */
  function potentialSetup(species, equilibria, act, settings) {
    const ns = species.length;
    const pots = [];
    species.forEach((sp, k) => { if (sp.potential) pots.push(k); });
    if (!pots.length) return act;
    const name = (k) => species[k].name;
    const sf = act ? act.sf : null;
    if (!sf) {
      throw new RtmError(`${name(pots[0])} is a surface's potential, and no species is on a surface: Hfo_wOH surface `
        + 'sites=2e-4 is one.', species[pots[0]].line);
    }
    /*
      CD-MUSIC, PHREEQC's SURFACE with -cd_music: a surface with three
      potentials, its planes 0, 1 and 2, Hfo_psi, Hfo_psib and Hfo_psid, the
      first given the capacitances between them, c0 and c1 (F/m2). Each
      species on it puts the charges dz0, dz1 and dz2 on them, against its
      bare site, and the plane-0 charge of the site itself, z less dz1 and
      dz2; a relation takes each plane's potential to the charge it puts
      there. Its equations, PHREEQC's: sigma0 = c0 (psi0 - psi1), sigma0 +
      sigma1 = c1 (psi1 - psi2), and sigma0 + sigma1 + sigma2 + sigmad = 0,
      sigmad the diffuse layer's charge at psi2 from every ion of the water
      (potentialRow).
    */
    const planeOf = (k) => (/_psib$/.test(name(k)) ? 1 : /_psid$/.test(name(k)) ? 2 : 0);
    const qOf = new Map(pots.map((k, q) => [name(k), q]));
    const np = pots.length;
    const kind = new Array(np).fill('gc');
    const next = new Int32Array(np).fill(-1);
    const cap = new Float64Array(np);
    const first = new Int32Array(np).fill(-1);
    pots.forEach((k, q) => {
      if (planeOf(k)) {
        if (!qOf.has(name(k).slice(0, -1))) {
          throw new RtmError(`${name(k)} is plane ${planeOf(k)} of a CD-MUSIC surface, whose first potential, `
            + `${name(k).slice(0, -1)}, is not in <SPECIES>.`, species[k].line);
        }
        return;
      }
      first[q] = q;
      const qb = qOf.get(`${name(k)}b`);
      const qd = qOf.get(`${name(k)}d`);
      const sp = species[k];
      if (qb === undefined && qd === undefined) {
        if (sp.c0 !== null || sp.c1 !== null) {
          throw new RtmError(`${name(k)} is given c0 and c1, a CD-MUSIC surface's capacitances, and has no planes 1 and 2: `
            + `${name(k)}b and ${name(k)}d, potentials of their own.`, sp.line);
        }
        return;
      }
      if (qb === undefined || qd === undefined) {
        throw new RtmError(`A CD-MUSIC surface has three potentials, ${name(k)}, ${name(k)}b and ${name(k)}d: ${qb === undefined
          ? `${name(k)}b` : `${name(k)}d`} is not in <SPECIES>.`, sp.line);
      }
      if (sp.c0 === null || sp.c1 === null) {
        throw new RtmError(`${name(k)} is the first potential of a CD-MUSIC surface and takes its capacitances, c0 between `
          + `planes 0 and 1 and c1 between 1 and 2, F/m2: ${name(k)} potential area=600 grams=1 c0=1.1 c1=5.`, sp.line);
      }
      kind[q] = 'c0';
      next[q] = qb;
      cap[q] = sp.c0;
      kind[qb] = 'c1';
      next[qb] = qd;
      cap[qb] = sp.c1;
      kind[qd] = 'cd';
      first[qb] = q;
      first[qd] = q;
    });
    // Each species on a surface: the first potential of its surface, by the name's prefix up to the underscore.
    const of = new Int32Array(ns).fill(-1);
    pots.forEach((k, q) => {
      if (first[q] !== q) return;
      const n = name(k);
      const cut = n.indexOf('_');
      if (cut < 1) {
        throw new RtmError(`${n} is a potential, and a potential is named for its surface, up to an underscore: `
          + 'Hfo_psi is the potential of Hfo_wOH and the other Hfo_ species.', species[k].line);
      }
      const prefix = n.slice(0, cut + 1);
      let any = false;
      for (const j of sf.list) {
        if (!name(j).startsWith(prefix)) continue;
        if (of[j] >= 0) {
          throw new RtmError(`${name(pots[of[j]])} and ${n} are each the potential of ${name(j)}: a surface has one.`,
            species[k].line);
        }
        // Sites that go with a mineral have their double layer's area go with it too, as PHREEQC has it, and the other way.
        const t = sf.types[sf.typeOf[j]];
        const mineral = t && t.per ? name(t.per.mineral) : null;
        if (mineral !== species[k].per) {
          throw new RtmError(mineral ? `${n} is the potential of a surface whose sites go with ${mineral}, and its area goes `
            + `with it too: ${n} potential area=5.34e4 per=${mineral}, m2 to each mole of it.`
            : `${n} has its area per mole of ${species[k].per}, and the sites of ${name(j)} on its surface are not: give `
              + `them per mole of it as well, sites= per=${species[k].per}.`, species[k].line);
        }
        of[j] = q;
        any = true;
      }
      if (!any) {
        throw new RtmError(`${n} is the potential of the surface ${prefix.slice(0, -1)}, and no species on a surface is `
          + `named ${prefix}...: Hfo_psi is the potential of Hfo_wOH.`, species[k].line);
      }
    });
    // The charge each species on a surface carries onto it, and under CD-MUSIC onto each plane.
    const zs = Float64Array.from(species, (sp) => (sp.surface ? (sp.z !== null ? sp.z : chargeOf(sp.name)) : 0));
    const dzOf = (j) => species[j].dz || [0, 0, 0];
    for (const j of sf.list) {
      if (species[j].dz && (of[j] < 0 || kind[of[j]] !== 'c0')) {
        throw new RtmError(`${name(j)} is given dz0, dz1 and dz2, the charges a species puts on the planes of a CD-MUSIC `
          + 'surface, and its surface is none.', species[j].line);
      }
    }
    // Each potential's weights on the species of its surface: plane 0 the site's charge less what goes to planes 1
    // and 2, plane 1 less what goes to 2, plane 2 and a double layer the whole charge.
    const w = pots.map((k, q) => Float64Array.from(species, (sp, j) => {
      if (of[j] < 0 || of[j] !== first[q]) return 0;
      const d = dzOf(j);
      return kind[q] === 'c0' ? zs[j] - d[1] - d[2] : kind[q] === 'c1' ? zs[j] - d[2] : zs[j];
    }));
    const isPot = (k) => species[k].potential;
    for (const eq of equilibria) {
      const p = eq.net.find(([k]) => isPot(k));
      if (p) {
        throw new RtmError(`"${eq.text}" has ${name(p[0])} in it, a surface's potential: the page puts the potential in `
          + 'each relation on its surface itself, by the charge the relation puts on the surface.', eq.line);
      }
      const on = eq.net.filter(([k]) => of[k] >= 0);
      if (!on.length) continue;
      const qs = new Set(on.map(([k]) => of[k]));
      if (qs.size > 1) {
        throw new RtmError(`"${eq.text}" is on two surfaces, each with its potential: a relation is on one.`, eq.line);
      }
      const q = of[on[0][0]];
      let dz = 0;
      for (const [k, c] of on) dz += c * zs[k];
      // CD-MUSIC: the charge the relation puts on each plane, which together are what it puts on the surface.
      const planes = [0, 0, 0];
      if (kind[q] === 'c0') {
        let scale = 0;
        for (const [k, c] of on) {
          const d = dzOf(k);
          for (let i = 0; i < 3; i++) planes[i] += c * d[i];
          scale += Math.abs(c * zs[k]);
        }
        if (Math.abs(planes[0] + planes[1] + planes[2] - dz) > 1e-9 * Math.max(scale, 1)) {
          throw new RtmError(`"${eq.text}" puts ${fmtSites(dz)} of charge on its CD-MUSIC surface and ${fmtSites(planes[0])}, `
            + `${fmtSites(planes[1])} and ${fmtSites(planes[2])} on its planes, by dz0, dz1 and dz2: they add up to the charge.`,
          eq.line);
        }
      }
      if (Math.abs(dz) < 1e-12 && !planes.some((v) => Math.abs(v) > 1e-12)) continue;
      if (eq.kf !== null) {
        throw new RtmError(`"${eq.text}" puts a charge on a surface with a potential, which is solved for and cannot be `
          + 'moved at a rate: the relation is held (EQUILIBRATE), and takes no kf.', eq.line);
      }
      // A reactant to the charge the relation puts on the surface, or on each plane: K exp(-dz F psi/RT).
      if (kind[q] === 'gc') eq.net.push([pots[q], -dz]);
      else {
        const qq = [q, next[q], next[next[q]]];
        for (let i = 0; i < 3; i++) if (Math.abs(planes[i]) > 1e-12) eq.net.push([pots[qq[i]], -planes[i]]);
        eq.cdPots = qq.map((x) => pots[x]);
      }
      eq.potential = { at: pots[q], dz };
    }
    for (const k of pots) {
      if (planeOf(k)) continue;
      if (!equilibria.some((eq) => eq.potential && eq.potential.at === k)) {
        throw new RtmError(`No relation puts a charge on the surface of ${name(k)}, and a potential acts through them: `
          + 'Hfo_wOH + H+ <=> Hfo_wOH2+ is one.', species[k].line);
      }
    }
    if (!settings.EQUILIBRATE) {
      throw new RtmError(`${name(pots[0])} is a surface's potential, which is worked out with the relations of its `
        + 'surface: it needs EQUILIBRATE, always to follow the run.', species[pots[0]].line);
    }
    const tc = setupTemperature(settings);
    if (!(tc >= 0 && tc <= 350)) {
      throw new RtmError(`TEMPERATURE = ${tc}: the double layer's dielectric constant is worked out for 0 to 350 C.`);
    }
    const T = tc + 273.15;
    const { eps } = debyeHuckelAB(tc, waterPressure(settings, species));
    const firstSp = (q) => species[pots[first[q]]];
    act.pt = {
      list: pots,
      of,
      zs,
      // Each potential's weights on the species of its surface (see above); its kind -- 'gc' a double layer's Gouy and
      // Chapman, 'c0' and 'c1' CD-MUSIC's planes 0 and 1 with their capacitance to the next plane, 'cd' its plane 2 and
      // diffuse layer -- the next plane's potential, and the first potential of its surface.
      w,
      kind,
      next,
      cap,
      first,
      cd: kind.includes('cd'),
      // F/(A M), C/m2 for each mol/kgw of charge, the surface's -- with per=, F/A, to be divided by the mineral's amount
      // in the cell (perM, potentialRow); and sqrt(8000 R T eps eps0), C/m2 at I = 1.
      cQ: Float64Array.from(pots, (k, q) => FARADAY / (firstSp(q).area * (firstSp(q).per === null ? firstSp(q).grams : 1))),
      perM: Int32Array.from(pots, (k, q) => (firstSp(q).per === null ? -1
        : species.findIndex((x) => x.name === firstSp(q).per))),
      kS: Math.sqrt(8000 * GAS_R * T * eps * EPSILON0),
      // F/RT: psi = -ln(a)/fRT, in volts.
      fRT: FARADAY / (GAS_R * T),
      temperature: tc,
      eps,
    };
    return act;
  }

  /**
   * One potential's Gouy-Chapman residual at the charge Q of its surface,
   * the ionic strength I (low: at its floor) and u = ln a = -F psi/RT, in
   * C/m2, with its derivatives in Q, I and u.
   */
  function gouyChapman(pt, q, Q, I, low, u, cell, M) {
    const sq = Math.sqrt(I);
    const sh = Math.sinh(u / 2);
    // sqrt(8000 R T eps eps0) at the cell's temperature where it differs between cells or goes with time.
    const kS = pt.kSc ? pt.kSc[cell] : pt.kS;
    const S = kS * sq;
    // An area per mole of a mineral: the cell's amount of it, M, takes the grams' place, and dM is its derivative.
    const per = pt.perM[q] >= 0;
    const cq = per ? pt.cQ[q] / M : pt.cQ[q];
    return {
      r: cq * Q + S * sh,
      dQ: cq,
      dI: low ? 0 : (kS / (2 * sq)) * sh,
      du: S * Math.cosh(u / 2) / 2,
      dM: per ? (-cq * Q) / M : 0,
    };
  }

  /**
   * One potential's row in the speciation and the run, of any kind (act.pt):
   * its surface's charge on its plane, Q in mol/kgw by its weights, as a
   * charge density cQ Q, and what balances it -- a double layer's Gouy and
   * Chapman (gouyChapman); CD-MUSIC's planes 0 and 1, c (u - uNext) RT/F,
   * the capacitance to the next plane; its plane 2, the diffuse layer's
   * charge from every ion of the water, PHREEQC's
   *
   *   sigmad = sign(u) sqrt(8000 R T eps eps0)/2 sqrt(D),
   *   D = sum m (e^(z u) - 1) + |n| (e^(-s u) - 1),
   *
   * n = sum m z, the water's own charge, balanced by a fictitious ion of
   * charge -s, s its sign; at no potential its limit, sqrt(D) -> |u|
   * sqrt(K), K = (sum m z^2 + |n|)/2. u = ln a = -F psi/RT. With the
   * derivatives in Q, u, the next plane's u, I, the mineral's amount M where
   * the area is per mole of it, and each ion's molality (ions.dm).
   */
  function potentialRow(pt, q, Q, I, low, u, cell, M, uNext, ions) {
    const kind = pt.kind[q];
    if (kind === 'gc') {
      const g = gouyChapman(pt, q, Q, I, low, u, cell, M);
      g.duNext = 0;
      return g;
    }
    const per = pt.perM[q] >= 0;
    const cq = per ? pt.cQ[q] / M : pt.cQ[q];
    const out = { r: cq * Q, dQ: cq, du: 0, duNext: 0, dI: 0, dM: per ? (-cq * Q) / M : 0, dm: null };
    if (kind === 'c0' || kind === 'c1') {
      const fRT = pt.fRTc ? pt.fRTc[cell] : pt.fRT;
      const g = pt.cap[q] / fRT;
      out.r += g * (u - uNext);
      out.du = g;
      out.duNext = -g;
      return out;
    }
    const kS = pt.kSc ? pt.kSc[cell] : pt.kS;
    const { z, m, dm } = ions;
    const n = z.length;
    let D = 0;
    let Dp = 0;
    let net = 0;
    for (let i = 0; i < n; i++) {
      const e = Math.exp(z[i] * u);
      D += m[i] * (e - 1);
      Dp += m[i] * z[i] * e;
      net += m[i] * z[i];
    }
    const sg = net >= 0 ? 1 : -1;
    const ef = Math.exp(-sg * u);
    D += Math.abs(net) * (ef - 1);
    Dp -= sg * Math.abs(net) * ef;
    /*
      A water in charge balance has n at nothing, where |n| has its corner:
      the fictitious ion's derivative in each molality is then the mean of
      its two sides, -z sinh(u), as a difference across it finds it. Its
      value there is nothing either way.
    */
    let scale = 0;
    for (let i = 0; i < n; i++) scale += m[i] * Math.abs(z[i]);
    const balanced = Math.abs(net) <= 1e-12 * scale;
    const fict = (zi) => (balanced ? -zi * Math.sinh(u) : sg * zi * (ef - 1));
    if (Math.abs(u) < 1e-8 || !(D > 0)) {
      let K = Math.abs(net);
      for (let i = 0; i < n; i++) K += m[i] * z[i] * z[i];
      K *= 0.5;
      const rk = Math.sqrt(K);
      out.r += 0.5 * kS * u * rk;
      out.du = 0.5 * kS * rk;
      for (let i = 0; i < n; i++) dm[i] = rk > 0 ? (0.5 * kS * u * (z[i] * z[i] + (balanced ? 0 : sg * z[i]))) / (4 * rk) : 0;
    } else {
      const su = u < 0 ? -1 : 1;
      const rD = Math.sqrt(D);
      out.r += su * 0.5 * kS * rD;
      out.du = (su * 0.5 * kS * Dp) / (2 * rD);
      for (let i = 0; i < n; i++) dm[i] = (su * 0.5 * kS * (Math.exp(z[i] * u) - 1 + fict(z[i]))) / (2 * rD);
    }
    out.dm = dm;
    return out;
  }

  /** PHREEQC's gas constant, L atm/(K mol) (global_structures.h). */
  const R_LITER_ATM = 0.0820597;

  /**
   * PENG AND ROBINSON'S equation of state for a gas mixture, as PHREEQC's
   * calc_PR has it (prep.cpp), term for term: each gas's a alpha (aa) and b
   * at the model's temperature, the binary factors f = 1 - k, R T. x the
   * composition; given P, a fixed pressure, the molar volume is the root of
   * the cubic PHREEQC takes, and given Vm, a fixed volume, the pressure
   * follows. ln phi of each gas into pr.lnPhi, 0 for a gas with no share as
   * PHREEQC has it, and ln phi held between -4.6 and 4.44 as there. Not
   * carried: the search PHREEQC makes past the turning point of P(V) where
   * the cubic has three roots, a gas dense enough to condense.
   */
  function prState(pr, x, P, Vm) {
    const K = pr.b.length;
    const RT = pr.RT;
    let b = 0;
    let A = 0;
    const S = pr.S;
    for (let i = 0; i < K; i++) {
      b += x[i] * pr.b[i];
      let s2 = 0;
      for (let j = 0; j < K; j++) {
        if (x[j] === 0) continue;
        const aij = Math.sqrt(pr.aa[i] * pr.aa[j]) * pr.f[i * K + j];
        A += x[i] * x[j] * aij;
        s2 += x[j] * aij;
      }
      S[i] = s2;
    }
    const b2 = b * b;
    if (Vm) {
      P = RT / (Vm - b) - A / (Vm * (Vm + 2 * b) - b2);
      if (P <= 0) P = 1;
    } else {
      if (P < 1e-10) P = 1e-10;
      const r1 = b - RT / P;
      const r12 = r1 * r1;
      const r2 = -3.0 * b2 + (A - RT * 2.0 * b) / P;
      const r3 = b2 * b + (RT * b2 - b * A) / P;
      const rp = r2 - r12 / 3;
      const rp3 = rp * rp * rp;
      const rq = (2.0 * r12 * r1 - 9.0 * r1 * r2) / 27 + r3;
      const rz = (rq * rq) / 4 + rp3 / 27;
      if (rz >= 0) {
        let ri = Math.sqrt(rz);
        if (ri + rq / 2 <= 0) Vm = Math.pow(ri - rq / 2, ONE_3) + Math.pow(-ri - rq / 2, ONE_3) - r1 / 3;
        else {
          ri = -Math.pow(ri + rq / 2, ONE_3);
          Vm = ri - rp / (3.0 * ri) - r1 / 3;
        }
      } else {
        const ri = Math.sqrt(-rp3 / 27);
        const ri1 = Math.acos(-rq / 2 / ri);
        Vm = 2.0 * Math.pow(ri, ONE_3) * Math.cos(ri1 / 3) - r1 / 3;
      }
    }
    const lnPhi = pr.lnPhi;
    const Z = (P * Vm) / RT;
    const Aa = (A * P) / (RT * RT);
    const Bb = (b * P) / RT;
    for (let i = 0; i < K; i++) {
      if (x[i] === 0) { lnPhi[i] = 0; continue; }
      const Br = pr.b[i] / b;
      let phi = -4.6;
      if (Z > Bb) {
        phi = Br * (Z - 1) - Math.log(Z - Bb) + (Aa / (2.828427 * Bb)) * (Br - (2.0 * S[i]) / A)
          * Math.log((Z + 2.41421356 * Bb) / (Z - 0.41421356 * Bb));
        phi = phi > 4.44 ? 4.44 : (phi < -4.6 ? -4.6 : phi);
      }
      lnPhi[i] = phi;
    }
    return { P, Vm };
  }
  const ONE_3 = 0.33333333333333333;

  /**
   * Peng and Robinson's a alpha of each gas and R T at tk kelvin, into pr
   * (gasSetup), where they are not for tk already: a cell's temperature
   * (onSites) where it differs between cells or goes with time.
   */
  function prAt(pr, tk) {
    if (pr.tk === tk) return;
    const R = R_LITER_ATM;
    for (let i = 0; i < pr.aa.length; i++) {
      pr.aa[i] = ((0.457235 * R * R * pr.tc[i] * pr.tc[i]) / pr.pc[i])
        * Math.pow(1 + pr.kk[i] * (1 - Math.sqrt(tk / pr.tc[i])), 2);
    }
    pr.RT = R * tk;
    pr.tk = tk;
  }

  /**
   * A real gas in a fixed volume (gasSetup): each gas's coefficient ln(phi P
   * /N), its activity -- its fugacity -- phi n P/N, P from the equation at
   * V/N; and d(ln gamma_i)/dC_j between the gases into gas.dln, by
   * differences, for the relations' derivatives (sitPartners). With no gas
   * at all, the ideal coefficient R T/V.
   */
  function prVolumeCoefficients(act, C, off, lnG, cell) {
    const gas = act.gas;
    const pr = gas.pr;
    const K = gas.list.length;
    const n = pr.n;
    const ideal = gas.lnGc ? gas.lnGc[cell] : gas.lnG;
    for (let q = 0; q < K; q++) n[q] = Math.max(C[off + gas.list[q]], 0);
    const value = (nn, out) => {
      let N = 0;
      for (let q = 0; q < K; q++) N += nn[q];
      if (!(N > 0)) { for (let q = 0; q < K; q++) out[q] = ideal; return; }
      for (let q = 0; q < K; q++) pr.x[q] = nn[q] / N;
      const st = prState(pr, pr.x, 0, gas.volume / N);
      for (let q = 0; q < K; q++) out[q] = pr.lnPhi[q] + Math.log(st.P / N);
    };
    value(n, pr.g0);
    for (let q = 0; q < K; q++) lnG[gas.list[q]] = pr.g0[q];
    let N = 0;
    for (let q = 0; q < K; q++) N += n[q];
    const dln = gas.dln;
    for (let j = 0; j < K; j++) {
      const h = 1e-6 * Math.max(n[j], 1e-6 * N, 1e-300);
      const nj = n[j];
      n[j] = nj + h;
      value(n, pr.g1);
      n[j] = nj - h;
      value(n, pr.g2);
      n[j] = nj;
      for (let i = 0; i < K; i++) dln[i * K + j] = (pr.g1[i] - pr.g2[i]) / (2 * h);
    }
  }

  /**
   * A group's members' coefficients worked into its rows, in place, before
   * bubbleRows: real gases' phi (bubbleReal), a binary solid solution's
   * lambda (binaryReal); nothing for ideal members. Returns the factored
   * matrix the rows were solved through, for a caller's other columns, or
   * null.
   */
  function groupReal(G, nUnknowns, withRows, cell) {
    if (G.def.coef === 'pr') return bubbleReal(G, G.def.gas, nUnknowns, withRows);
    if (G.def.coef === 'binary') return binaryReal(G, nUnknowns, withRows, cell);
    return null;
  }

  /**
   * A bubble of real gases (gasSetup): the pressures the water holds its
   * gases at are their fugacities over phi, and phi is the bubble's, whose
   * composition is those pressures' shares -- so, from G.lnE = ln f and
   * G.rows its gradient, y = ln f - ln phi(w(y)), w = e^y/sum e^y, solved by
   * Newton; and the rows (I + d ln phi/dy)^-1 times the gradient of ln f.
   * In place, before bubbleRows. Nothing for ideal gases.
   */
  function bubbleReal(G, gas, nUnknowns, withRows) {
    if (!gas || !gas.pr) return;
    const pr = gas.pr;
    const K = G.rel.length;
    const lnf = Float64Array.from(G.lnE);
    const y = Float64Array.from(lnf);
    const x = pr.x;
    const phiAt = (yy, out) => {
      x.fill(0);
      let top = -Infinity;
      for (let q = 0; q < K; q++) top = Math.max(top, yy[q]);
      let s = 0;
      for (let q = 0; q < K; q++) { x[G.prIdx[q]] = Math.exp(yy[q] - top); s += x[G.prIdx[q]]; }
      for (let q = 0; q < K; q++) x[G.prIdx[q]] /= s;
      prState(pr, x, gas.pressure, 0);
      for (let q = 0; q < K; q++) out[q] = pr.lnPhi[G.prIdx[q]];
    };
    const ph = new Float64Array(K);
    const p1 = new Float64Array(K);
    const p2 = new Float64Array(K);
    const Jm = Array.from({ length: K }, () => new Float64Array(K));
    const dphi = () => {
      for (let j = 0; j < K; j++) {
        const yj = y[j];
        y[j] = yj + 1e-6;
        phiAt(y, p1);
        y[j] = yj - 1e-6;
        phiAt(y, p2);
        y[j] = yj;
        for (let i = 0; i < K; i++) Jm[i][j] = (i === j ? 1 : 0) + (p1[i] - p2[i]) / 2e-6;
      }
    };
    for (let it = 0; it < 60; it++) {
      phiAt(y, ph);
      const F = new Float64Array(K);
      let big = 0;
      for (let q = 0; q < K; q++) { F[q] = y[q] + ph[q] - lnf[q]; big = Math.max(big, Math.abs(F[q])); }
      if (big < 1e-14) break;
      dphi();
      const step = solveInPlace(Jm, F, K);
      if (!step) break;
      for (let q = 0; q < K; q++) y[q] -= step[q];
    }
    for (let q = 0; q < K; q++) G.lnE[q] = y[q];
    if (!withRows) return null;
    dphi();
    // rows <- (I + Phi)^-1 rows, column by column of the unknowns.
    const piv = luFactor(Jm, K);
    if (!piv) return null;
    const col = new Float64Array(K);
    for (let c = 0; c < nUnknowns; c++) {
      let any = false;
      for (let q = 0; q < K; q++) { col[q] = G.rows[q][c]; if (col[q]) any = true; }
      if (!any) continue;
      luSolve(Jm, piv, col, K);
      for (let q = 0; q < K; q++) G.rows[q][c] = col[q];
    }
    // For a caller's other columns: (I + Phi) factored.
    return { Jm, piv, K };
  }

  /**
   * The water's pressure, atm: a bubble's at a fixed pressure, which PHREEQC
   * puts the water at too (its A, B and dielectric constant); else 1.
   */
  function waterPressure(settings, species) {
    const given = settings.given || new Set();
    const bubble = given.has('GAS_PRESSURE') && settings.GAS_PRESSURE > 0 && species.some((sp) => sp.gas);
    if (given.has('PRESSURE')) {
      if (!(settings.PRESSURE > 0)) throw new RtmError(`PRESSURE = ${settings.PRESSURE}: the water's pressure is above zero.`);
      if (bubble && settings.PRESSURE !== settings.GAS_PRESSURE) {
        throw new RtmError(`PRESSURE = ${settings.PRESSURE} and GAS_PRESSURE = ${settings.GAS_PRESSURE}: a bubble at a fixed `
          + 'pressure puts the water at its own pressure.');
      }
      return settings.PRESSURE;
    }
    return bubble ? settings.GAS_PRESSURE : 1;
  }

  /**
   * A GAS PHASE, as PHREEQC's GAS_PHASE has it.
   *
   *   GAS_VOLUME = 0.1                    litres of gas to each kilogram of water
   *   CO2(g)   1e-6   gas                 its amount in the gas, mol/kg of water
   *   CO2(g) <=> CO2, logK = -1.468       its dissolution, as PHREEQC's PHASES write it
   *
   * A gas's activity is its partial pressure in atm, ideal. In a fixed volume
   * that is n R T/V, R PHREEQC's 0.0820597 L atm/(K mol) and T TEMPERATURE:
   * a coefficient R T/V that is the same in every cell, so that a relation
   * with a gas in it holds as any other does and the gas phase is simply
   * there, however little of a gas is in it. At a fixed total pressure,
   * GAS_PRESSURE, it is the gas's share of the bubble times the total. The
   * gas stays in its cell, as PHREEQC's TRANSPORT leaves a cell's gas phase,
   * and counts in the totals as anything else does.
   *
   * Returns the activity model with the gas in it (one made for it when
   * ACTIVITY is none), or `act` itself when there is no gas.
   */
  function gasSetup(species, equilibria, act, settings, warnings, pairLines = []) {
    const gases = [];
    species.forEach((sp, k) => { if (sp.gas) gases.push(k); });
    const given = settings.given || new Set();
    const V = settings.GAS_VOLUME;
    const P = settings.GAS_PRESSURE;
    if (!gases.length) {
      for (const key of ['GAS_VOLUME', 'GAS_PRESSURE']) {
        if (given.has(key)) warnings.push(`${key} is a gas phase's, and no species is a gas: it does nothing here.`);
      }
      if (pairLines.length) {
        throw new RtmError('<GAS_PAIRS> holds the binary parameters of real gases in a gas phase, and no species is a gas.',
          pairLines[0].line);
      }
      return act;
    }
    const names = gases.map((k) => species[k].name);
    const hasV = given.has('GAS_VOLUME');
    const hasP = given.has('GAS_PRESSURE');
    if (hasV === hasP) {
      throw new RtmError(hasV
        ? 'GAS_VOLUME and GAS_PRESSURE are both given: a gas phase is held at a fixed volume or at a fixed total '
          + 'pressure, not both.'
        : `${names.join(', ')} ${names.length === 1 ? 'is a gas' : 'are gases'}: give the gas phase GAS_VOLUME, `
          + 'litres to each kilogram of water, or GAS_PRESSURE, its total pressure in atm.');
    }
    if (hasV && !(V > 0)) throw new RtmError(`GAS_VOLUME = ${V}: a gas phase's volume is above zero.`);
    if (hasP && !(P > 0)) throw new RtmError(`GAS_PRESSURE = ${P}: a gas phase's pressure is above zero.`);
    waterPressure(settings, species);
    const tc = setupTemperature(settings);
    if (!(tc >= 0 && tc <= 350)) {
      throw new RtmError(`TEMPERATURE = ${tc}: a gas phase is worked out for 0 to 350 C, as the activity model is.`);
    }
    for (const k of gases) {
      if (!equilibria.some((eq) => eq.net.some(([s]) => s === k))) {
        throw new RtmError(`${species[k].name} is a gas and in no relation: ${species[k].name} <=> ..., its `
          + 'dissolution with its log K, puts it in equilibrium with the water.', species[k].line);
      }
    }
    for (const eq of equilibria) {
      const inGas = eq.net.filter(([s]) => species[s].gas);
      if (!inGas.length) continue;
      if (inGas.length > 1) {
        throw new RtmError(`"${eq.text}" has two gases in it: a relation is one gas's dissolution.`, eq.line);
      }
      if (eq.net.some(([s]) => species[s].mineral || species[s].exchange || species[s].exchanger || species[s].surface)) {
        throw new RtmError(`"${eq.text}" has a gas and a mineral, an exchanger or a surface in it: a gas dissolves into `
          + 'the water.', eq.line);
      }
      if (hasP && eq.kf !== null) {
        throw new RtmError(`"${eq.text}" puts a gas into a bubble at a fixed pressure, which comes and goes: it is held `
          + '(EQUILIBRATE), and takes no kf.', eq.line);
      }
    }
    /*
      At a fixed pressure each gas is in one relation, its dissolution, and
      that relation is the bubble's: while there is a bubble the relations
      together say that the pressures the water holds its gases at add up to
      the total, and that each gas's share of the bubble is its share of
      them; while there is none, each gas's amount is zero. So, like a
      mineral's, each relation marks its gas (eq.mineral), which is an amount
      that may reach zero rather than ln C.
    */
    if (hasP) {
      for (const k of gases) {
        const eqs = equilibria.filter((eq) => eq.net.some(([s]) => s === k));
        if (eqs.length > 1) {
          throw new RtmError(`${species[k].name} is in two relations, lines ${eqs[0].line} and ${eqs[1].line}: in a bubble at a `
            + 'fixed pressure a gas has one, its dissolution.', eqs[1].line);
        }
        const eq = eqs[0];
        eq.mineral = k;
        eq.mineralNu = eq.net.find(([s]) => s === k)[1];
        eq.gas = true;
      }
    }
    const out = act || noActivity(species);
    out.form = Uint8Array.from(out.form);
    for (const k of gases) out.form[k] = 6;
    const tk = tc + 273.15;
    const isGas = new Uint8Array(species.length);
    for (const k of gases) isGas[k] = 1;
    const qOf = new Int32Array(species.length).fill(-1);
    gases.forEach((k, q) => { qOf[k] = q; });
    /*
      REAL GASES: given each a critical temperature and pressure, every gas
      of the phase is held by Peng and Robinson's equation (prState), as
      PHREEQC holds a gas the database gives them; a gas's activity is then
      its fugacity, phi times its partial pressure. All or none: PHREEQC does
      not mix ideal and real gases. <GAS_PAIRS> gives a pair of gases k, the
      cross term of the equation's a taken 1 - k times, PHREEQC's
      GAS_BINARY_PARAMETERS.
    */
    const real = gases.filter((k) => species[k].tc !== null);
    if (real.length && real.length !== gases.length) {
      throw new RtmError(`${real.map((k) => species[k].name).join(', ')} ${real.length === 1 ? 'is a real gas' : 'are real gases'} `
        + `(Tc and Pc) and ${gases.filter((k) => species[k].tc === null).map((k) => species[k].name).join(', ')} not: a gas `
        + 'phase is all real gases, held by Peng and Robinson\'s equation, or all ideal, as in PHREEQC.', species[gases[0]].line);
    }
    let pr = null;
    if (real.length) {
      const K = gases.length;
      const R = R_LITER_ATM;
      const kk = Float64Array.from(gases, (k) => {
        const om = species[k].omega || 0;
        return 0.37464 + om * (1.54226 - 0.26992 * om);
      });
      const bb = Float64Array.from(gases, (k) => (0.077796 * R * species[k].tc) / species[k].pc);
      const f = new Float64Array(K * K).fill(1);
      const seen = new Map();
      for (const { text, line } of pairLines) {
        const parts = text.split(/\s+/);
        if (parts.length !== 3) {
          throw new RtmError(`"${text}" is not two gases and their binary parameter: H2O(g)  CO2(g)  0.19.`, line);
        }
        const qs = parts.slice(0, 2).map((nm) => {
          const k = species.findIndex((sp) => sp.name === nm);
          if (k < 0 || !species[k].gas) throw new RtmError(`"${nm}" in <GAS_PAIRS> is not a gas of <SPECIES>.`, line);
          return qOf[k];
        });
        const key = qs[0] < qs[1] ? `${qs[0]}:${qs[1]}` : `${qs[1]}:${qs[0]}`;
        if (seen.has(key)) throw new RtmError(`${parts[0]} and ${parts[1]} are paired twice in <GAS_PAIRS>, on lines ${seen.get(key)} and ${line}.`, line);
        seen.set(key, line);
        const k = constValue(parts[2], line, `the binary parameter of ${parts[0]} and ${parts[1]}`);
        f[qs[0] * K + qs[1]] = 1 - k;
        f[qs[1] * K + qs[0]] = 1 - k;
      }
      pr = { aa: new Float64Array(K), b: bb, f, RT: 0, tk: NaN, kk, tc: Float64Array.from(gases, (k) => species[k].tc),
        pc: Float64Array.from(gases, (k) => species[k].pc), S: new Float64Array(K), lnPhi: new Float64Array(K),
        x: new Float64Array(K), n: new Float64Array(K), g0: new Float64Array(K), g1: new Float64Array(K),
        g2: new Float64Array(K) };
      prAt(pr, tk);
    } else if (pairLines.length) {
      throw new RtmError('<GAS_PAIRS> holds the binary parameters of real gases, and no gas is given Tc and Pc.', pairLines[0].line);
    }
    out.gas = { list: gases, isGas, qOf, fixed: hasV ? 'volume' : 'pressure', volume: hasV ? V : 0, pressure: hasP ? P : 0,
      temperature: tc, RT: R_LITER_ATM * tk,
      // In a fixed volume of ideal gases, ln(R T/V): every gas's coefficient, in every cell.
      lnG: hasV ? Math.log((R_LITER_ATM * tk) / V) : 0,
      pr,
      // A real gas in a fixed volume: d(ln gamma_i)/dC_j between the gases, and the scratch their sums go into.
      dln: pr && hasV ? new Float64Array(gases.length * gases.length) : null,
      d: pr && hasV ? (out.sit ? out.sit.d : out.pz ? out.pz.d : new Float64Array(species.length)) : null };
    // A bubble is a group (groupSystems): its relations come and go together, their total the pressure.
    if (hasP) {
      const def = { kind: 'gas', name: 'the bubble', lnP: Math.log(P), coef: pr ? 'pr' : null, gas: out.gas };
      out.gas.group = def;
      for (const eq of equilibria) if (eq.gas) eq.grp = def;
    }
    return out;
  }

  /**
   * SOLID SOLUTIONS, as PHREEQC's SOLID_SOLUTIONS has them.
   *
   *   <SOLID_SOLUTIONS>
   *   CaSrCO3   Aragonite  Strontianite   a0=3.43  a1=-1.82
   *   BaRaSO4   Barite  RaSO4
   *
   * Each line a solid solution: its name, its end members -- species given
   * `mineral`, each in the one relation that dissolves it, with the pure
   * phase's log K -- and for two members, Guggenheim's a0 and a1,
   * dimensionless, or g0 and g1 in kJ/mol, at tc= degrees C (25 unless
   * given), where PHREEQC keeps them to 0.01 K. An end member's activity is its mole fraction in its solid
   * solution times lambda: 1 for an ideal one, and for a binary one
   *
   *   ln lambda_1 = x2^2 (a0 - a1 (3 - 4 x2)),   ln lambda_2 = x1^2 (a0 + a1 (4 x2 - 1))
   *
   * as PHREEQC writes Guggenheim's expansion, x2 the second member's mole
   * fraction; a0 and a1 go as 1/T from the temperature they are given at,
   * PHREEQC's energies g = a R T held (binaryAt). A solid solution is there
   * or not as a whole: there while the water holds it at saturation -- each
   * member's IAP/K over its lambda, at the composition the water gives it,
   * adding up to 1 -- each member's amount its share of the solid solution
   * at that composition; not there while that sum is below 1, and then each
   * member's amount is zero. It is a group (groupSystems), as a bubble is,
   * its total 1. Where Guggenheim's parameters give a miscibility gap at the
   * cell's temperature, a composition inside it is two solids of the gap's
   * compositions, and the water is held at the activities the gap's edge
   * gives each member, as PHREEQC holds it.
   *
   * Returns the solid solutions' definitions.
   */
  function solidSolutionSetup(species, equilibria, lines, settings) {
    const index = new Map(species.map((sp, k) => [sp.name, k]));
    const out = [];
    const taken = new Map();
    for (const { text, line } of lines) {
      const parts = text.split(/\s+/).filter(Boolean);
      const name = parts.shift();
      const members = parts.filter((p) => !p.includes('='));
      const opts = parts.filter((p) => p.includes('='));
      if (out.some((d) => d.name === name)) throw new RtmError(`The solid solution ${name} is given twice.`, line);
      if (members.length < 2) {
        throw new RtmError(`"${text}" is a solid solution's name and its end members, two or more: CaSrCO3  Aragonite  `
          + 'Strontianite.', line);
      }
      const ks = members.map((m) => {
        if (!index.has(m)) throw new RtmError(`"${m}" in <SOLID_SOLUTIONS> is not in <SPECIES>.`, line);
        const k = index.get(m);
        if (!species[k].mineral) {
          throw new RtmError(`${m} is an end member of the solid solution ${name}, and an end member is a mineral: `
            + `${m}  0  mineral.`, line);
        }
        if (taken.has(k)) {
          throw new RtmError(`${m} is an end member of two solid solutions, ${taken.get(k)} and ${name}: of one only.`, line);
        }
        taken.set(k, name);
        return k;
      });
      const rels = ks.map((k) => {
        const eqs = equilibria.filter((eq) => eq.mineral === k);
        if (!eqs.length) {
          throw new RtmError(`${species[k].name} is an end member of the solid solution ${name}, and in no relation: `
            + `${species[k].name} <=> ..., its dissolution with the pure phase's log K.`, line);
        }
        return eqs[0];
      });
      const prm = {};
      for (const o of opts) {
        const [key, raw] = o.split('=');
        const k = key.toLowerCase();
        if (!['a0', 'a1', 'g0', 'g1', 'tc'].includes(k)) {
          throw new RtmError(`"${o}": a solid solution takes a0= and a1= (Guggenheim's, dimensionless), with tc= the `
            + 'temperature they are given at, or g0= and g1= (kJ/mol), and nothing else.', line);
        }
        prm[k] = constValue(raw, line, `${k} of ${name}`);
      }
      const hasA = prm.a0 !== undefined || prm.a1 !== undefined;
      const hasG = prm.g0 !== undefined || prm.g1 !== undefined;
      if (hasA && hasG) throw new RtmError(`${name} is given a0/a1 and g0/g1: one or the other.`, line);
      if ((hasA || hasG) && ks.length !== 2) {
        throw new RtmError(`${name} has ${ks.length} end members, and Guggenheim's a0 and a1 are for two: a solid solution of `
          + 'more is ideal, as in PHREEQC.', line);
      }
      if (prm.tc !== undefined && !hasA && !hasG) {
        throw new RtmError(`tc= is the temperature a0 and a1, or g0 and g1, are given at: ${name} has none.`, line);
      }
      if (prm.tc !== undefined && !(prm.tc >= 0 && prm.tc <= 350)) throw new RtmError(`tc = ${prm.tc}: 0 to 350 C.`, line);
      if (!settings.EQUILIBRATE) {
        throw new RtmError(`The solid solution ${name} is held at equilibrium with the water: it needs EQUILIBRATE, and `
          + 'always to follow the run.', line);
      }
      // PHREEQC's ss_calc_a0_a1 and ss_prep: the energies at the temperature given, a0 = g0/RT at any other.
      const tk0 = prm.tc !== undefined ? prm.tc + 273.15 : 298.15;
      const rt0 = tk0 * R_KJ;
      const a0 = hasA ? (prm.a0 || 0) : (prm.g0 || 0) / rt0;
      const a1 = hasA ? (prm.a1 || 0) : (prm.g1 || 0) / rt0;
      const binary = a0 !== 0 || a1 !== 0;
      const def = { kind: 'ss', name, line, lnP: 0, coef: binary ? 'binary' : null, members: ks,
        ag0: a0 * rt0, ag1: a1 * rt0, tk0, tk: null, cache: new Map() };
      for (const eq of rels) {
        if (eq.grp) throw new RtmError(`"${eq.text}" is a gas's and an end member's: one or the other.`, eq.line);
        eq.grp = def;
      }
      out.push(def);
    }
    return out;
  }

  /*
    PHREEQC's root finders for a binary solid solution (tidy.cpp), step for
    step: scan for a sign change on a grid of 1, 10 and 100 divisions (the
    start not reset between them, as there), and halve the interval to tol.
  */
  function ssScan(f, xx0, xx1) {
    let x0 = xx0;
    let x1 = xx1;
    const diff = x1 - x0;
    for (let j = 0; j < 3; j++) {
      let fx0 = f(x0);
      const divisions = Math.trunc(Math.pow(10, j));
      for (let i = 1; i < divisions; i++) {
        x1 = xx0 + (diff * i) / divisions;
        const fx1 = f(x1);
        if (fx0 * fx1 <= 0) return [x0, x1];
        x0 = x1;
        fx0 = fx1;
      }
    }
    return null;
  }
  function ssHalve(f, x0in, x1, tol) {
    let x0 = x0in;
    let y0 = f(x0);
    let dx = x1 - x0;
    for (let i = 0; i < 100; i++) {
      dx *= 0.5;
      const x = x0 + dx;
      const y = f(x);
      if (dx < tol || y === 0) break;
      if (y0 * y >= 0) { x0 = x; y0 = y; }
    }
    return x0 + dx;
  }

  /*
    solve_misc's equations at xc1 and xc2: the two members' activities the
    same at both compositions, as the augmented 2 x 3 matrix, the residuals
    in a[2] and a[5] and their gradient beside them.
  */
  function ssMiscSystem(a0, a1, xc1, xc2) {
    const xb1 = 1 - xc1;
    const xb2 = 1 - xc2;
    const xc12 = xc1 * xc1;
    const xc13 = xc12 * xc1;
    const xc22 = xc2 * xc2;
    const xc23 = xc22 * xc2;
    const lc1 = Math.exp(xb1 * xb1 * (a0 - a1 * (3 - 4 * xb1)));
    const lb1 = Math.exp(xc1 * xc1 * (a0 + a1 * (4 * xb1 - 1)));
    const lc2 = Math.exp(xb2 * xb2 * (a0 - a1 * (3 - 4 * xb2)));
    const lb2 = Math.exp(xc2 * xc2 * (a0 + a1 * (4 * xb2 - 1)));
    const a = new Float64Array(6);
    a[2] = -(xb1 * lb1 - xb2 * lb2);
    a[5] = -(xc1 * lc1 - xc2 * lc2);
    let t = Math.exp(a0 * xc12 - 4 * a1 * xc13 + 3 * a1 * xc12);
    a[0] = (2 * a0 * xc1 + 6 * a1 * xc1 - 2 * a0 * xc12 + 12 * a1 * xc13 - 18 * a1 * xc12 - 1) * t;
    t = Math.exp(a0 * xc22 - 4 * a1 * xc23 + 3 * a1 * xc22);
    a[1] = (2 * a0 * xc22 - 12 * a1 * xc23 - 2 * a0 * xc2 + 18 * a1 * xc22 - 6 * a1 * xc2 + 1) * t;
    t = Math.exp(a0 * xc12 - 2 * a0 * xc1 + a0 - 4 * a1 * xc13 + 9 * a1 * xc12 - 6 * a1 * xc1 + a1);
    a[3] = (2 * a0 * xc12 - 2 * a0 * xc1 - 12 * a1 * xc13 + 18 * a1 * xc12 - 6 * a1 * xc1 + 1) * t;
    t = Math.exp(a0 * xc22 - 2 * a0 * xc2 + a0 - 4 * a1 * xc23 + 9 * a1 * xc22 - 6 * a1 * xc2 + a1);
    a[4] = (-2 * a0 * xc22 + 2 * a0 * xc2 + 12 * a1 * xc23 - 18 * a1 * xc22 + 6 * a1 * xc2 - 1) * t;
    return a;
  }

  /** PHREEQC's solve_misc: the two compositions of a miscibility gap, xc1 and xc2, by Newton from the start given. */
  function ssSolveMisc(a0, a1, xc1in, xc2in, tol) {
    let xc1 = xc1in;
    let xc2 = xc2in;
    let converged = true;
    const maxIter = 25;
    let i;
    for (i = 0; i < maxIter; i++) {
      const a = ssMiscSystem(a0, a1, xc1, xc2);
      if (Math.abs(a[2]) < tol && Math.abs(a[5]) < tol) break;
      const d = ssSlnq2(a);
      for (;;) {
        const x1 = xc1 + d[0];
        const x2 = xc2 + d[1];
        if (x1 > 1 || x1 < 0 || x2 > 1 || x2 < 0) { d[0] *= 0.5; d[1] *= 0.5; } else { xc1 = x1; xc2 = x2; break; }
      }
      if (Math.abs(xc1 - xc2) < 0.01) { converged = false; break; }
    }
    if (i === maxIter) converged = false;
    return { xc1, xc2, converged };
  }

  /*
    THE GAP TO ROUND-OFF. PHREEQC's solve_misc stops where the activities
    agree to 1e-6, and where it stops moves in jumps as the temperature
    does: by 2e-6 in a composition within a thousandth of a kelvin. A run
    whose temperature goes with time holds the water at the gap's edge, and
    a jump there is one the integrator cannot step across. So there Newton
    goes on from where PHREEQC's stops, on the same equations, until the
    residual stops falling: the same gap, its compositions a smooth function
    of the temperature, and the activities at both the same to round-off.
    At a temperature that stays as it is, the gap is PHREEQC's own, where its
    search leaves it, and a water starts on PHREEQC's to 1e-10 where the
    round-off one would be up to 1e-6 from it.
  */
  function ssPolish(a0, a1, xc1in, xc2in) {
    let xc1 = xc1in;
    let xc2 = xc2in;
    let keep = [xc1, xc2];
    let best = Infinity;
    for (let i = 0; i < 30; i++) {
      const a = ssMiscSystem(a0, a1, xc1, xc2);
      const norm = Math.max(Math.abs(a[2]), Math.abs(a[5]));
      if (!(norm < best)) break;
      best = norm;
      keep = [xc1, xc2];
      if (norm === 0) break;
      const d = ssSlnq2(a);
      xc1 += d[0];
      xc2 += d[1];
      if (!(xc1 > 0 && xc1 < 1 && xc2 > 0 && xc2 < 1)) break;
    }
    return keep;
  }

  /** PHREEQC's slnq for two unknowns, a the 2 x 3 augmented matrix row by row: the solution, [0, 0] where singular. */
  function ssSlnq2(a) {
    const n = 2;
    const ncols = 3;
    const d = [0, 0];
    for (let i = 0; i < n - 1; i++) {
      let b = Math.abs(a[i * ncols + i]);
      let m = i;
      for (let j = i + 1; j < n; j++) if (Math.abs(a[j * ncols + i]) > b) { b = Math.abs(a[j * ncols + i]); m = j; }
      if (b < 1e-30) return d;
      if (m !== i) {
        for (let j = i; j <= n; j++) { b = a[i * ncols + j]; a[i * ncols + j] = a[m * ncols + j]; a[m * ncols + j] = b; }
      }
      for (let j = n; j >= i; j--) a[i * ncols + j] /= a[i * ncols + i];
      for (let j = i + 1; j < n; j++) {
        if (a[j * ncols + i] === 0) continue;
        b = -a[j * ncols + i];
        for (let k = i + 1; k <= n; k++) a[j * ncols + k] += b * a[i * ncols + k];
      }
    }
    if (!(Math.abs(a[(n - 1) * ncols + n - 1]) > 1e-30)) return d;
    d[n - 1] = a[(n - 1) * ncols + n] / a[(n - 1) * ncols + n - 1];
    for (let i = n - 2; i >= 0; i--) {
      d[i] = a[i * ncols + n];
      for (let j = i + 1; j < n; j++) d[i] -= a[i * ncols + j] * d[j];
    }
    return d;
  }

  /**
   * A binary solid solution's a0 and a1 at tk kelvin, and its miscibility
   * gap there, as PHREEQC's ss_prep finds it: none, or the spinodal xsm1 and
   * xsm2 and the gap's xb1 and xb2 (the second member's mole fractions), and
   * ln of each member's activity at xb1, where PHREEQC holds the water while
   * the solid's composition is inside the gap. Kept by temperature.
   */
  function binaryAt(def, tk) {
    let p = def.cache.get(tk);
    if (p) return p;
    // PHREEQC keeps the parameters of the solid solution's own temperature within 0.01 K of it.
    const t = Math.abs(tk - def.tk0) > 0.01 ? tk : def.tk0;
    const r = R_KJ;
    const rt = r * t;
    const a0 = def.ag0 / rt;
    const a1 = def.ag1 / rt;
    const tol = 1e-6;
    let gap = null;
    if (Math.abs(a0) + Math.abs(a1) >= tol) {
      const ag0 = a0 * rt;
      const ag1 = a1 * rt;
      let xc;
      let tc;
      if (Math.abs(a1) < tol) {
        xc = 0.5;
        tc = ag0 / (2 * r);
      } else {
        xc = 0.5 + (Math.pow(ag0 * ag0 + 27 * ag1 * ag1, 0.5) - ag0) / (18 * ag1);
        tc = ((12 * ag1 * xc - 6 * ag1 + 2 * ag0) * (xc - xc * xc)) / r;
      }
      const fsp = (x) => -12 * a1 * x * x * x + (18 * a1 - 2 * a0) * x * x + (2 * a0 - 6 * a1) * x - 1.0;
      const s1 = tc >= t ? ssScan(fsp, 0, 1) : null;
      if (s1) {
        const xsm1 = ssHalve(fsp, s1[0], s1[1], tol);
        const s2 = ssScan(fsp, s1[1], 1);
        if (!s2) throw new RtmError(`The solid solution ${def.name}: PHREEQC's second spinodal point is not found.`, def.line);
        const xsm2 = ssHalve(fsp, s2[0], s2[1], tol);
        let res = null;
        for (let i = 1; i < 3 && !(res && res.converged); i++) {
          const divisions = Math.trunc(Math.pow(10, i));
          for (let j = 0; j < divisions && !(res && res.converged); j++) {
            for (let k = divisions; k > 0; k--) {
              res = ssSolveMisc(a0, a1, j / divisions + 0.001, k / divisions, tol);
              if (res.converged) break;
            }
          }
        }
        if (!res || !res.converged) throw new RtmError(`The solid solution ${def.name}: its miscibility gap is not found.`, def.line);
        const [pc1, pc2] = def.smooth ? ssPolish(a0, a1, res.xc1, res.xc2) : [res.xc1, res.xc2];
        let xb1;
        let xb2;
        if (pc1 < pc2) { xb1 = 1 - pc2; xb2 = 1 - pc1; } else { xb1 = 1 - pc1; xb2 = 1 - pc2; }
        const xc1 = 1 - xb1;
        gap = { xb1, xb2, xsm1, xsm2,
          lnAc: Math.log(xc1) + xb1 * xb1 * (a0 - a1 * (3 - 4 * xb1)),
          lnAb: Math.log(xb1) + xc1 * xc1 * (a0 + a1 * (4 * xb1 - 1)) };
      }
    }
    p = { a0, a1, gap };
    if (def.cache.size > 4096) def.cache.clear();
    def.cache.set(tk, p);
    return p;
  }

  /**
   * A binary solid solution's composition from the water, worked into its
   * rows in place before bubbleRows (groupReal): G.lnE holds each member's ln
   * IAP/K, and the second member's mole fraction x is the one at which
   * ln(x/(1 - x)) + ln lambda_2 - ln lambda_1 is ln(IAP2 K1/(IAP1 K2)) --
   * on the branch below a miscibility gap (G.mode 1), above it (3), or where
   * the water puts it (not there, 0) -- by Newton in ln(x/(1 - x)), held in
   * its bracket. Then lnE less ln lambda, whose shares are x and whose sum
   * is the saturation, and with rows, the rows through x: each less d ln
   * lambda/dx dx/dL times the gradient of L. Returns the 2 x 2 map the rows
   * went through, factored, for a caller's other columns.
   */
  function binaryReal(G, nUnknowns, withRows, cell) {
    const def = G.def;
    const tk = def.tk ? def.tk[cell] : def.tk0;
    const { a0, a1, gap } = binaryAt(def, tk);
    const L = G.lnE[1] - G.lnE[0];
    let lo = -800;
    let hi = 800;
    const logit = (x) => Math.log(x / (1 - x));
    if (gap) {
      const upper = G.mode === 3 || (G.mode !== 1 && L > gap.lnAb - gap.lnAc);
      if (upper) lo = logit(gap.xsm2); else hi = logit(gap.xsm1);
    }
    const D = (x) => (1 - x) * (1 - x) * (a0 + a1 * (4 * x - 1)) - x * x * (a0 - a1 * (3 - 4 * x));
    const dD = (x) => -2 * (1 - x) * (a0 + a1 * (4 * x - 1)) + 4 * a1 * (1 - x) * (1 - x)
      - (2 * a0 * x - 6 * a1 * x + 12 * a1 * x * x);
    const xOf = (u) => (u >= 0 ? 1 / (1 + Math.exp(-u)) : Math.exp(u) / (1 + Math.exp(u)));
    const h = (u) => u + D(xOf(u)) - L;
    let ulo = lo;
    let uhi = hi;
    let u = Math.min(Math.max(L - D(0.5), lo), hi);
    if (!(h(lo) < 0)) u = lo;
    else if (!(h(hi) > 0)) u = hi;
    else {
      for (let it = 0; it < 200; it++) {
        const x = xOf(u);
        const f = u + D(x) - L;
        if (f === 0) break;
        if (f < 0) ulo = u; else uhi = u;
        const dh = 1 + dD(x) * x * (1 - x);
        let next = dh > 0 ? u - f / dh : NaN;
        if (!(next > ulo && next < uhi)) next = 0.5 * (ulo + uhi);
        if (Math.abs(next - u) <= 1e-15 * Math.max(1, Math.abs(u)) || uhi - ulo <= 1e-15 * Math.max(1, Math.abs(u))) {
          u = next;
          break;
        }
        u = next;
      }
    }
    const x = xOf(u);
    const lnLc = x * x * (a0 - a1 * (3 - 4 * x));
    const lnLb = (1 - x) * (1 - x) * (a0 + a1 * (4 * x - 1));
    G.lnE[0] -= lnLc;
    G.lnE[1] -= lnLb;
    G.x = x;
    if (!withRows) return null;
    const dh = 1 + dD(x) * x * (1 - x);
    const dxdL = dh > 0 ? (x * (1 - x)) / dh : 0;
    const s0 = (2 * a0 * x - 6 * a1 * x + 12 * a1 * x * x) * dxdL;
    const s1 = (-2 * (1 - x) * (a0 + a1 * (4 * x - 1)) + 4 * a1 * (1 - x) * (1 - x)) * dxdL;
    const r0 = G.rows[0];
    const r1 = G.rows[1];
    for (let c = 0; c < nUnknowns; c++) {
      const d = r1[c] - r0[c];
      if (!d) continue;
      r0[c] -= s0 * d;
      r1[c] -= s1 * d;
    }
    // The rows went through T = I - s (-1 1); a caller's other columns go through it too: T^-1, factored, solves to T.
    const det = 1 + s0 - s1;
    const Jm = [Float64Array.from([(1 - s1) / det, s0 / det]), Float64Array.from([-s1 / det, (1 + s0) / det])];
    const piv = luFactor(Jm, 2);
    return piv ? { Jm, piv, K: 2 } : null;
  }

  /**
   * A binary solid solution inside its miscibility gap (mode 2): each
   * member's relation holds at the activity the gap's edge gives it, as
   * PHREEQC holds it, its amounts free -- the totals settle them. Rows into F
   * and J from G.lnE and G.rows; returns the convergence measure.
   */
  function gapRows(G, nUnknowns, F, J, cell) {
    const def = G.def;
    const { gap } = binaryAt(def, def.tk ? def.tk[cell] : def.tk0);
    const lnA = gap ? [gap.lnAc, gap.lnAb] : [0, 0];
    let norm = 0;
    for (let q = 0; q < 2; q++) {
      const j = G.rel[q];
      F[j] = G.lnE[q] - lnA[q];
      norm = Math.max(norm, Math.abs(F[j]));
      if (!J) continue;
      const Jr = J[j];
      const row = G.rows[q];
      for (let c = 0; c < nUnknowns; c++) Jr[c] = row[c];
    }
    return norm;
  }

  /**
   * A group's rows while it is there, whatever it is: inside a miscibility
   * gap (mode 2) gapRows; otherwise its coefficients (groupReal) and then
   * bubbleRows. Returns bubbleRows' result with lu, groupReal's.
   */
  /**
   * Where a group that is there stands, from its members' amounts (amount(q)):
   * 1, or for a binary solid solution with a miscibility gap at the cell's
   * temperature, 2 with its composition inside the gap and 3 above it; 0
   * where there is none of it, or no more than `tiny`.
   */
  function groupMode(G, amount, cell, tiny = 0) {
    let N = 0;
    for (let q = 0; q < G.rel.length; q++) N += amount(q);
    if (!(N > tiny)) return 0;
    if (G.def.coef !== 'binary') return 1;
    const { gap } = binaryAt(G.def, G.def.tk ? G.def.tk[cell] : G.def.tk0);
    if (!gap) return 1;
    const xb = amount(1) / N;
    return xb >= gap.xb2 ? 3 : xb > gap.xb1 ? 2 : 1;
  }

  /**
   * Where a group that forms goes: a binary solid solution with a gap above
   * it (3) where the water's ratio of its members is past the gap's, below it
   * (1) otherwise. G.lnE the members' ln IAP/K.
   */
  function groupFormsAt(G, cell) {
    if (G.def.coef !== 'binary') return 1;
    const { gap } = binaryAt(G.def, G.def.tk ? G.def.tk[cell] : G.def.tk0);
    return gap && G.lnE[1] - G.lnE[0] > gap.lnAb - gap.lnAc ? 3 : 1;
  }

  function groupRowsAt(G, mode, cell, n, nUnknowns, F, J, big) {
    if (mode === 2) return { norm: gapRows(G, nUnknowns, F, J, cell), lnS: 0, N: 0, lu: null, gap: true };
    G.mode = mode;
    const lu = groupReal(G, nUnknowns, !!J, cell);
    const res = bubbleRows(G, n, nUnknowns, F, J, big);
    res.lu = lu;
    return res;
  }

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
   * database gives it and how anyone writing one by hand will have it; dH,
   * kJ/mol, and analytic = A1 ... A6 say how it goes with temperature, as a
   * PHREEQC database's delta_h and -analytic do (logKAt).
   *
   * Given `kf` as well, the equilibrium is ALSO enforced while the run goes
   * on, as a fast reversible pair with kb = kf/K. Without it the equilibrium
   * is used for the speciation of the initial state and nothing else, because
   * these solvers integrate y' = f and an equilibrium held exactly throughout
   * is an algebraic constraint, which is a different kind of problem.
   */
  /*
    A RELATION'S LOG K AT A TEMPERATURE, as PHREEQC's k_calc works it out
    (prep.cpp), T in kelvin:

      log K = logK - dH (298.15 - T)/(ln10 R T 298.15)
              + A1 + A2 T + A3/T + A4 log10 T + A5/T^2 + A6 T^2

    logK the relation's log K at 25 C, dH its enthalpy of reaction in kJ/mol,
    taken through van 't Hoff's equation as constant, and A1 to A6 its
    analytic expression, R PHREEQC's 0.00831470 kJ/(mol K). An analytic
    expression with any term not zero replaces logK and dH, as PHREEQC's
    select_log_k_expression has it. No pressure term: PHREEQC's comes in
    above one atmosphere, from molar volumes the page does not carry.
  */
  const R_KJ = 0.00831470;
  /** log10 K at tk kelvin of a relation's temperature terms th ({logK, dH, a}). */
  function logKAt(th, tk) {
    const a = th.a;
    const me = tk * R_KJ;
    return th.logK - th.dH * (298.15 - tk) / (Math.LN10 * me * 298.15)
      + a[0] + a[1] * tk + a[2] / tk + a[3] * Math.log10(tk) + a[4] / (tk * tk) + a[5] * tk * tk;
  }

  /**
   * ln K of a relation or a phase in a cell: its own there (lnKc) where the
   * temperature differs between cells or goes with time, else the one ln K.
   */
  const lnKIn = (eq, cell) => (eq.lnKc ? eq.lnKc[cell] : eq.lnK);
  /** Bumped whenever a model works its cells' ln K out afresh (thermoAt): what a reduced system keeps is then stale. */
  let thermoStamp = 0;

  /**
   * A relation's NAME = value parts: logK or K, dH, analytic = A1 ... A6
   * (up to six numbers, the rest zero), and kf where `kfToo`. Returns ln K
   * at 25 C, kf or null, and th, the temperature terms logKAt reads, or null
   * where log K does not go with temperature.
   */
  function readLogK(parts, line, what, kfToo) {
    let lnK = null;
    let logK = null;
    let dH = null;
    let a = null;
    let kf = null;
    for (const part of parts) {
      const m = /^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$/.exec(part);
      if (!m) throw new RtmError(`"${part}" is not NAME = value.`, line);
      if (m[1] === 'analytic') {
        const terms = m[2].trim().split(/\s+/);
        if (terms.length > 6) {
          throw new RtmError(`analytic = ${m[2].trim()} has ${terms.length} terms, and an analytic expression has at most six: `
            + 'A1 + A2 T + A3/T + A4 log10 T + A5/T^2 + A6 T^2, T in kelvin.', line);
        }
        a = new Float64Array(6);
        terms.forEach((s, i) => { a[i] = constValue(s, line, `Term A${i + 1} of analytic`); });
        continue;
      }
      const v = constValue(m[2], line, m[1]);
      if (m[1] === 'logK') { lnK = v * Math.LN10; logK = v; }
      else if (m[1] === 'K') {
        if (!(v > 0)) throw new RtmError('K must be greater than zero; use logK for a small one.', line);
        lnK = Math.log(v);
        logK = Math.log10(v);
      } else if (m[1] === 'dH') dH = v;
      else if (m[1] === 'kf' && kfToo) {
        if (!(v > 0)) throw new RtmError('kf must be greater than zero.', line);
        kf = v;
      } else {
        throw new RtmError(kfToo ? `"${m[1]}" is not K, logK, dH, analytic or kf.`
          : `"${m[1]}" is not K, logK, dH or analytic: a phase is held by nothing, so it has no kf.`, line);
      }
    }
    // PHREEQC's rule: an expression is there where one of its terms is not zero, and then it is log K.
    if (a && a.every((x) => x === 0)) a = null;
    if (a) {
      const th = { logK: 0, dH: 0, a };
      return { lnK: logKAt(th, 298.15) * Math.LN10, kf, th };
    }
    if (lnK === null) {
      throw new RtmError(dH !== null ? `dH is how ${what}'s log K goes with temperature from its value at 25 C: give `
        + 'logK = ... as well.' : `${what === 'an equilibrium' ? 'An equilibrium' : 'A phase'} needs K = ..., logK = ... `
        + 'or analytic = ... .', line);
    }
    return { lnK, kf, th: dH ? { logK, dH, a: new Float64Array(6) } : null };
  }

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
      /*
        SI(Fix_H+) = -7: a mineral dissolving, or precipitating, as much as
        holds another phase's saturation index at a target -- PHREEQC's
        alternative reaction (compile). Its log K is that phase's.
      */
      let siOf = null;
      for (let i = parts.length - 1; i >= 0; i--) {
        const m = /^SI\s*\(\s*([^()]+?)\s*\)\s*=\s*(.+)$/i.exec(parts[i]);
        if (!m) continue;
        if (siOf) throw new RtmError(`"${text}" is given SI( ) twice: a mineral holds one phase at its target.`, line);
        siOf = { phase: m[1], target: constValue(m[2], line, `SI(${m[1]})`) };
        parts.splice(i, 1);
      }
      if (siOf && parts.length) {
        throw new RtmError(`"${text}" holds SI(${siOf.phase}) at ${siOf.target}, and takes its log K from that phase: it `
          + 'is given no logK, K, dH, analytic or kf.', line);
      }
      const { lnK, kf, th } = siOf ? { lnK: 0, kf: null, th: null } : readLogK(parts, line, 'an equilibrium', true);

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
      // lnKc: ln K cell by cell, where the temperature differs between cells or goes with time (compile).
      return { net, lnK, kf, th, lnKc: null, line, text, reactants: species(reactants), products: species(products), water,
        siOf };
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
    for (const eq of equilibria) {
      for (const [si] of eq.net) seen.add(si);
      // A CD-MUSIC surface's three potentials, each with its equation, whatever charge the relation puts on its plane.
      if (eq.cdPots) for (const si of eq.cdPots) seen.add(si);
      // What a mineral held at another phase's saturation dissolves into, read by its relation or not (eq.moves).
      if (eq.moves) for (const [si] of eq.moves) seen.add(si);
    }
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
    /*
      Nor does a surface's potential (site 3): it is no amount, and a total
      with it in would be the surface's charge, which the relations move and
      Gouy and Chapman's equation decides. It is an unknown of its own.
    */
    const out = (si) => (fixed && fixed[si]) || (site && site[si] === 3);
    const active = new Set(equilibriumSpecies(equilibria).filter((si) => !out(si)));
    const ne = equilibria.length;
    // A = S transpose: one row per equilibrium, one column per species. A mineral's relation that carries the sites of a
    // surface that goes with it (surfaceSetup) has them in its column, for the totals alone.
    const A = Array.from({ length: ne }, () => new Float64Array(ns));
    equilibria.forEach((eq, j) => {
      for (const [si, c] of eq.net) if (!out(si)) A[j][si] = c;
      // Only where the surface's own relations are in the system too: a water speciated alone has no sites.
      if (eq.carry) for (const [si, c] of eq.carry) if (!out(si) && active.has(si)) A[j][si] += c;
      // What a mineral held at another phase's saturation dissolves into, beyond that phase's own (eq.moves).
      if (eq.moves) for (const [si, c] of eq.moves) if (!out(si)) A[j][si] += c;
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
   * The alpha that makes sum(alpha_q U_q) nearest w, U's rows the totals a
   * speciation holds: from the normal equations, (U U^T) alpha = U w, by
   * Gaussian elimination with partial pivoting. The rows are independent
   * (conservationBasis), so the matrix is not singular.
   */
  function leastSquaresRows(U, wv) {
    const nb = U.length;
    const na = wv.length;
    const A = Array.from({ length: nb }, (_, p) => {
      const row = new Float64Array(nb + 1);
      for (let q = 0; q < nb; q++) { let v = 0; for (let k = 0; k < na; k++) v += U[p][k] * U[q][k]; row[q] = v; }
      let r = 0;
      for (let k = 0; k < na; k++) r += U[p][k] * wv[k];
      row[nb] = r;
      return row;
    });
    for (let col = 0; col < nb; col++) {
      let best = col;
      for (let r = col + 1; r < nb; r++) if (Math.abs(A[r][col]) > Math.abs(A[best][col])) best = r;
      const tmp = A[col]; A[col] = A[best]; A[best] = tmp;
      const piv = A[col][col];
      if (!piv) continue;
      for (let r = 0; r < nb; r++) {
        if (r === col) continue;
        const f = A[r][col] / piv;
        if (!f) continue;
        for (let c = col; c <= nb; c++) A[r][c] -= f * A[col][c];
      }
    }
    return Float64Array.from(A, (row, q) => (row[q] ? row[nb] / row[q] : 0));
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
   * @param {object} [opts]  { tol, maxIter, floor, equilibria, fixed, t, cells, total: { weights, value, name, via } }
   * @returns {{y: Float64Array, cells: object[]}}
   */
  function speciate(model, y, opts = {}) {
    // opts.equilibria: some of the relations only, and the species they take;
    // opts.fixed: the species held where they stand, in place of the model's
    // fixed ones -- the electron, at the pe a start is given.
    const eqs = opts.equilibria || model.equilibria;
    if (!eqs || !eqs.length) return { y: Float64Array.from(y || model.initialState()), cells: [] };
    // At the temperature of time opts.t, 0 unless given, where it goes with time.
    if (model.thermoAt) model.thermoAt(opts.t || 0);
    const ns = model.speciesNames.length;
    const out = Float64Array.from(y || model.initialState());
    // Species on an exchanger first, and last what counts in no total.
    const site = model.rank || null;
    // The species that take part, and where each sits in the small system. A
    // fixed one is held: it appears in the equilibrium rows as a known number,
    // never as an unknown.
    const held = opts.fixed || model.fixed || [];
    const basis = opts.equilibria || opts.fixed
      ? conservationBasis(eqs, ns, held, abundanceOf(out, ns, model.allCells || model.cells), site) : model.conservation;
    const ne = eqs.length;
    const nb = basis.length;
    const cells = [];
    const part = equilibriumSpecies(eqs).filter((si) => !held[si]);
    const na = part.length;
    // A surface's potential has Gouy and Chapman's equation for its own.
    const npot = part.filter((si) => site && site[si] === 3).length;
    if (ne + nb + npot !== na) {
      const nheld = equilibriumSpecies(eqs).length - na;
      throw new RtmError(`The equilibria give ${ne} equations and ${nb} conserved totals, which is `
        + `${ne + nb} for the ${na} species they are free to move`
        + (nheld ? ` (${nheld} more of them are fixed)` : '')
        + '. Fixing one species of an equilibrium leaves it solvable; fixing two of the same one '
        + 'usually does not, and an equilibrium that repeats another has the same effect.');
    }
    const sys = cellSystem(eqs, part, basis.map((v) => Float64Array.from(part, (si) => v[si])), model.mineral,
      model.act || null, ns, site);
    // An exchanger, the electron or a potential counts in no total: it is no amount.
    const w = Float64Array.from(part, (si) => (site && site[si] >= 2 ? 0 : 1));
    /*
      opts.total: { weights, value, name, via }, an element's total in the
      cell set to value -- sum(weights[k] C_k), the element's count in each
      species -- as a diagram sweeps it. The relations conserve the element,
      so its total is a sum of the totals they hold, sum(alpha_q T_q). It is
      added, or taken away, as one species of via -- the element's own
      dissolved species, Zn+2 and ZnOH+, the most of them in the water --
      every total moving only as that species carries it, so that what else
      holds the element keeps its own: a surface's sites stay as many with
      zinc on them or not, and the chloride of ZnCl+ stays. Without via, the
      total with the largest alpha is moved and the others are left as they
      are. The species that hold the element start scaled to the new total,
      a start nearer the answer than the old one.
    */
    let alpha = null;
    let moved = -1;
    let via = null;
    let wEl = null;
    if (opts.total) {
      wEl = Float64Array.from(part, (si, k) => (w[k] ? opts.total.weights[si] || 0 : 0));
      alpha = leastSquaresRows(sys.U, wEl);
      let worst = 0;
      let size = 0;
      for (let k = 0; k < na; k++) {
        let v = 0;
        for (let q = 0; q < nb; q++) v += alpha[q] * sys.U[q][k];
        worst = Math.max(worst, Math.abs(v - wEl[k]));
        size = Math.max(size, Math.abs(wEl[k]));
      }
      if (!(size > 0)) {
        throw new RtmError(`No species the relations hold has any ${opts.total.name || 'of the element'}: its total is not theirs to set.`);
      }
      if (worst > 1e-9 * size) {
        throw new RtmError(`The relations do not keep the ${opts.total.name || 'element'}: its total is no sum of the totals `
          + 'they hold, and cannot be set through them.');
      }
      for (let q = 0; q < nb; q++) if (moved < 0 || Math.abs(alpha[q]) > Math.abs(alpha[moved])) moved = q;
      // Of the species to add it as, those free to move here.
      via = (opts.total.via || []).map((si) => part.indexOf(si)).filter((k) => k >= 0 && w[k] > 0 && wEl[k] > 0);
    }
    // opts.cells: these cells only, the rest left as they are -- one water of a column, as a diagram asks.
    // Every cell the state has, a reservoir's included: its water is speciated as a cell's is.
    for (const cell of opts.cells || Array.from({ length: model.allCells || model.cells }, (_, c) => c)) {
      const b = cell * ns;
      // The totals to hold, taken from the state as it stands; a mineral
      // there at the start is taken to be present until it proves otherwise.
      const totals = sys.U.map((row) => {
        let t = 0;
        for (let k = 0; k < na; k++) t += row[k] * w[k] * out[b + part[k]];
        return t;
      });
      if (alpha) {
        let now = 0;
        for (let q = 0; q < nb; q++) now += alpha[q] * totals[q];
        if (via.length) {
          let kv = via[0];
          for (const k of via) if (out[b + part[k]] > out[b + part[kv]]) kv = k;
          const d = (opts.total.value - now) / wEl[kv];
          for (let q = 0; q < nb; q++) totals[q] += sys.U[q][kv] * w[kv] * d;
        } else totals[moved] += (opts.total.value - now) / alpha[moved];
        if (now > 0) {
          const f = opts.total.value / now;
          for (let k = 0; k < na; k++) if (opts.total.weights[part[k]]) out[b + part[k]] *= f;
        }
      }
      // (One held whatever its amount, force_equality, is never at none.)
      const present = Uint8Array.from(eqs, (eq, j) => (sys.minOf[j] < 0 || out[b + part[sys.minOf[j]]] > 0
        || (eq.bounds && eq.bounds.lo[cell] === -Infinity) ? 1 : 0));
      // A group is there where its members have any amount between them; a binary solid solution where
      // its composition has it, inside its miscibility gap or either side.
      for (const G of sys.groups) {
        const mode = groupMode(G, (q) => out[b + part[G.k[q]]], cell);
        for (const j of G.rel) present[j] = mode;
      }
      const res = speciateCell(sys, out, b, totals, w, present,
        { tol: opts.tol, maxIter: opts.maxIter, floor: opts.floor, activeSet: true, cell });
      if (res.why === 'singular') throw new RtmError(`The speciation matrix is singular in cell ${cell}.`);
      if (res.why === 'unsettled') {
        throw new RtmError(`The speciation does not settle in cell ${cell}, neither with the minerals it starts with nor with any `
          + `one of them gone (residual ${res.residual.toExponential(2)}).`);
      }
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
          let r = lnKAtP(eq, c, water) - (eq.water ? eq.water * water.lnAw : 0);
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
   * Loads each surface type given its sites from the water of its cell: the
   * species on it in equilibrium with that water, which is left as it is,
   * their sites the given ones. PHREEQC's SURFACE with -equilibrate.
   *
   * With the water fixed, each species of the type follows from the one
   * given the sites, through the relations that form it: ln a = c + (n/n0) u,
   * u that species' ln a. Their activities are their fractions of the sites,
   * so what is left is ln(sum of e^(c + (n/n0) u)) = 0, convex and rising in
   * u, which Newton settles from anywhere.
   */
  function loadSurfaces(model, y) {
    const sf = model.act.sf;
    const pt = model.act.pt;
    const act = model.act;
    const ns = model.speciesNames.length;
    const nt = sf.types.length;
    const lnG = new Float64Array(ns);
    const dG = new Float64Array(ns);
    // Each loaded type: the order its relations form its species in, from the
    // one given the sites, and the potential it is on, or -1.
    const plan = sf.types.map((t) => {
      if (t.sitesFrom < 0) return null;
      const mine = new Set(t.members);
      const eqs = model.equilibria.filter((eq) => eq.net.some(([si]) => mine.has(si)));
      const k0 = t.sitesFrom;
      if (eqs.length !== t.members.length - 1) {
        throw new RtmError(`The surface of ${model.speciesNames[k0]} has ${t.members.length} species and ${eqs.length} `
          + 'relations for them: each species on it but one is formed in one relation of its own, and then the load a '
          + 'water gives it is settled.');
      }
      const known = new Set([k0]);
      const order = [];
      for (let grew = true; grew;) {
        grew = false;
        for (const eq of eqs) {
          if (order.some((o) => o.eq === eq)) continue;
          const open = eq.net.filter(([si]) => mine.has(si) && !known.has(si));
          if (open.length !== 1) continue;
          order.push({ eq, j: open[0][0], nu: open[0][1] });
          known.add(open[0][0]);
          grew = true;
        }
      }
      const on = pt ? t.members.find((j) => pt.of[j] >= 0) : undefined;
      return { t, mine, k0, order, q: on !== undefined ? pt.of[on] : -1,
        lnA: new Float64Array(ns), slope: new Float64Array(ns), pslope: new Float64Array(ns) };
    });
    const cells = new Set(sf.load.map((q) => Math.floor(q / nt)));
    for (const c of cells) {
      const b = c * ns;
      const water = activityAt(act, y, b, lnG, dG, c);
      const here = plan.filter((pl, ti) => pl && sf.load.includes(c * nt + ti));
      // ln a of each species of a type: lnA + slope u + pslope psi, u the ln a
      // of the one given the sites and psi its potential's ln a.
      for (const pl of here) {
        const { lnA, slope, pslope, mine, k0 } = pl;
        lnA[k0] = 0;
        slope[k0] = 1;
        pslope[k0] = 0;
        for (const { eq, j, nu } of pl.order) {
          let r = lnKAtP(eq, c, water) - (eq.water ? eq.water * water.lnAw : 0);
          let d = 0;
          let pd = 0;
          for (const [si, v] of eq.net) {
            if (si === j) continue;
            if (mine.has(si)) { r -= v * lnA[si]; d -= v * slope[si]; pd -= v * pslope[si]; } else if (pt && model.speciesList[si].potential) {
              pd -= v;
            } else r -= v * (Math.log(y[b + si]) + lnG[si]);
          }
          lnA[j] = r / nu;
          slope[j] = d / nu;
          pslope[j] = pd / nu;
        }
      }
      // The types on no potential, one at a time; those on one with it, together.
      const groups = [];
      for (const pl of here) {
        if (pl.q < 0) { groups.push({ q: -1, pls: [pl] }); continue; }
        const g = groups.find((gg) => gg.q === pl.q);
        if (g) g.pls.push(pl); else groups.push({ q: pl.q, pls: [pl] });
      }
      for (const { q, pls } of groups) {
        const m = pls.length;
        const n = m + (q >= 0 ? 1 : 0);
        const u = new Float64Array(n);
        const psiAt = q >= 0 ? pt.list[q] : -1;
        if (q >= 0) u[m] = Math.log(Math.max(y[b + psiAt], 1e-300));
        // The charge of what is on the surface and not loaded here, as it stands.
        let Qfixed = 0;
        if (q >= 0) {
          const loaded = new Set(pls.flatMap((pl) => pl.t.members));
          for (let j = 0; j < ns; j++) if (pt.of[j] === q && pt.zs[j] && !loaded.has(j)) Qfixed += pt.zs[j] * y[b + j];
        }
        const la = (pl, j) => pl.lnA[j] + pl.slope[j] * u[pls.indexOf(pl)] + (q >= 0 ? pl.pslope[j] * u[m] : 0);
        const F = new Float64Array(n);
        const J = Array.from({ length: n }, () => new Float64Array(n));
        let ok = false;
        for (let it = 0; it < 200; it++) {
          for (const row of J) row.fill(0);
          let Q = Qfixed;
          pls.forEach((pl, a) => {
            let top = -Infinity;
            for (const j of pl.t.members) top = Math.max(top, la(pl, j));
            let sum = 0;
            let ds = 0;
            let dp = 0;
            for (const j of pl.t.members) {
              const e = Math.exp(la(pl, j) - top);
              sum += e;
              ds += e * pl.slope[j];
              dp += e * pl.pslope[j];
              if (q >= 0 && pt.zs[j]) {
                const cj = Math.exp(la(pl, j) - sf.shift[b + j]);
                Q += pt.zs[j] * cj;
                // F/(A M), or with an area per mole of a mineral F/A over the cell's amount of it, which loading leaves.
                const cq = pt.perM[q] >= 0 ? pt.cQ[q] / y[b + pt.perM[q]] : pt.cQ[q];
                J[m][a] += cq * pt.zs[j] * cj * pl.slope[j];
                J[m][m] += cq * pt.zs[j] * cj * pl.pslope[j];
              }
            }
            // The fractions of the type's sites add up to one.
            F[a] = top + Math.log(sum);
            J[a][a] = ds / sum;
            if (q >= 0) J[a][m] = dp / sum;
          });
          if (q >= 0) {
            const gc = gouyChapman(pt, q, Q, water.I, !(water.I > 1e-10), u[m], c, pt.perM[q] >= 0 ? y[b + pt.perM[q]] : 1);
            F[m] = gc.r;
            J[m][m] += gc.du;
          }
          if (!F.every(Number.isFinite)) break;
          const step = solveInPlace(J, F, n);
          if (!step) break;
          let damp = 1;
          for (let a = 0; a < n; a++) if (Math.abs(step[a]) * damp > 20) damp = 20 / Math.abs(step[a]);
          let done = true;
          for (let a = 0; a < n; a++) {
            u[a] -= damp * step[a];
            if (Math.abs(step[a]) >= 1e-14 * Math.max(1, Math.abs(u[a]))) done = false;
          }
          if (done && damp === 1) { ok = true; break; }
        }
        if (!ok) {
          throw new RtmError(`The surface of ${model.speciesNames[pls[0].k0]} could not be loaded from the water`
            + `${model.cells > 1 ? ` of cell ${c}` : ''}.`);
        }
        // Its activity is its fraction, n C/sites: C = e^(ln a - shift).
        for (const pl of pls) for (const j of pl.t.members) y[b + j] = Math.exp(la(pl, j) - sf.shift[b + j]);
        if (q >= 0) y[b + psiAt] = Math.exp(u[m]);
      }
    }
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
   *   rank     the model's: 1 on an exchanger, 2 no amount, 3 a potential (see conservationBasis)
   *   pots     each surface's potential taking part: its place in part k,
   *            which of act.pt's it is q, and the species on its surface,
   *            [place, charge] where they take part and [species, charge]
   *            where they do not; rows ne + nb + p hold Gouy and Chapman
   */
  function cellSystem(eqs, part, U, mineral, act, ns, rank) {
    const at = new Int32Array(ns).fill(-1);
    part.forEach((si, k) => { at[si] = k; });
    const isMin = Uint8Array.from({ length: ns }, (_, si) => (mineral && mineral[si] ? 1 : 0));
    const exch = rank ? Uint8Array.from(part, (si) => (rank[si] >= 2 ? 1 : 0)) : null;
    const pt = act && act.pt ? act.pt : null;
    const pots = [];
    if (pt) {
      pt.list.forEach((si, q) => {
        if (at[si] < 0) return;
        const members = [];
        const fixedQ = [];
        const w = pt.w[q];
        for (let j = 0; j < ns; j++) {
          if (!w[j]) continue;
          if (at[j] >= 0) members.push([at[j], w[j]]); else fixedQ.push([j, w[j]]);
        }
        // CD-MUSIC: the next plane's potential (planes 0 and 1), and every ion of the water (plane 2).
        const nsi = pt.next[q] >= 0 ? pt.list[pt.next[q]] : -1;
        let ions = null;
        if (pt.kind[q] === 'cd') {
          const list = [];
          // The water's ions: act.z is 0 on a surface, an exchanger, a mineral, a gas and the rest that are no ion.
          for (let j = 0; j < ns; j++) if (act.z[j]) list.push(j);
          ions = { si: Int32Array.from(list), k: Int32Array.from(list, (j) => at[j]), z: Float64Array.from(list, (j) => act.z[j]),
            m: new Float64Array(list.length), dm: new Float64Array(list.length) };
        }
        pots.push({ k: at[si], q, si, members, fixedQ, nsi, next: nsi >= 0 ? at[nsi] : -1, ions });
      });
    }
    return {
      pots, np: pots.length, pt,
      eqs, ne: eqs.length, nb: U.length, na: part.length, part, at, U, act, ns, isMin,
      lin: Uint8Array.from(part, (si) => isMin[si]),
      minOf: Int32Array.from(eqs, (eq) => (eq.mineral >= 0 && at[eq.mineral] >= 0 ? at[eq.mineral] : -1)),
      minNu: Float64Array.from(eqs, (eq) => eq.mineralNu || 0),
      lnG: act ? new Float64Array(ns) : null,
      dG: act ? new Float64Array(ns) : null,
      cellC: new Float64Array(ns),
      exch: exch && exch.some((v) => v) ? exch : null,
      rank: rank || null,
      // The groups -- a bubble, solid solutions -- and each relation's (groupSystems).
      ...groupSystems(eqs, part, at),
    };
  }

  /*
    GROUPS: relations whose amounts come and go together, each a member's --
    a bubble at a fixed pressure (gasSetup), whose members are its gases, and
    a solid solution (solidSolutionSetup), whose members are its end members.
    Each relation of one has eq.grp, the group's definition: kind ('gas' or
    'ss'), name, lnP, ln of the total the members' shares of the water add up
    to while it is there (the bubble's pressure; 1 for a solid solution), and
    coef, how a member's activity departs from its share: null for ideal,
    'pr' for real gases (Peng and Robinson's phi), 'binary' for a binary solid
    solution (Guggenheim's lambda, binaryAt). While a group is there its rows
    are bubbleRows' -- the first says the shares add up to the total, each
    other that its member's amount is its share of the group -- and while it
    is not, each member's amount is zero.
  */

  /**
   * The groups of a cell system: for each, its relations, each member's
   * place in part and coefficient, and the scratch its rows are made in
   * (bubbleRows); and inGroup, each relation's group or -1.
   */
  function groupSystems(eqs, part, at) {
    const inGroup = new Int32Array(eqs.length).fill(-1);
    const groups = [];
    const defs = [];
    eqs.forEach((eq, j) => {
      if (!eq.grp || at[eq.mineral] < 0) return;
      let g = defs.indexOf(eq.grp);
      if (g < 0) { g = defs.length; defs.push(eq.grp); groups.push([]); }
      groups[g].push(j);
      inGroup[j] = g;
    });
    return {
      inGroup,
      groups: groups.map((rel, g) => ({
        def: defs[g], rel: Int32Array.from(rel), k: Int32Array.from(rel, (j) => at[eqs[j].mineral]),
        prIdx: defs[g].coef === 'pr' ? Int32Array.from(rel, (j) => defs[g].gas.qOf[eqs[j].mineral]) : null,
        nu: Float64Array.from(rel, (j) => eqs[j].mineralNu), lnP: defs[g].lnP,
        lnE: new Float64Array(rel.length), w: new Float64Array(rel.length),
        rows: rel.map(() => new Float64Array(part.length)), mean: new Float64Array(part.length) })),
    };
  }

  /**
   * A bubble's rows while it is there. lnE[q] is the ln of the pressure the
   * water holds gas q at, -(its relation without the gas)/nu, and rows[q]
   * its gradient in the n unknowns; n(q) is gas q's amount. The first
   * relation's row says the pressures add up to the total, ln sum e^lnE - ln
   * P; each other's that its gas's amount is its share of the bubble, n_q -
   * N w_q, N the gases' amounts together and w_q = e^lnE_q / sum e^lnE. Into
   * F and, with J, J; returns the convergence measure, the first in ln and
   * the rest against `big`, the largest total.
   */
  function bubbleRows(G, n, nUnknowns, F, J, big) {
    const K = G.rel.length;
    let top = -Infinity;
    for (let q = 0; q < K; q++) top = Math.max(top, G.lnE[q]);
    let S = 0;
    for (let q = 0; q < K; q++) { G.w[q] = Math.exp(G.lnE[q] - top); S += G.w[q]; }
    for (let q = 0; q < K; q++) G.w[q] /= S;
    const lnS = top + Math.log(S);
    let N = 0;
    for (let q = 0; q < K; q++) N += n(q);
    const j0 = G.rel[0];
    F[j0] = lnS - G.lnP;
    let norm = Math.abs(F[j0]);
    if (J) {
      const mean = G.mean;
      mean.fill(0);
      for (let q = 0; q < K; q++) {
        const row = G.rows[q];
        const w = G.w[q];
        for (let c = 0; c < nUnknowns; c++) if (row[c]) mean[c] += w * row[c];
      }
      J[j0].fill(0);
      for (let c = 0; c < nUnknowns; c++) J[j0][c] = mean[c];
    }
    for (let q = 1; q < K; q++) {
      const j = G.rel[q];
      F[j] = n(q) - N * G.w[q];
      norm = Math.max(norm, Math.abs(F[j]) / Math.max(big, 1e-300));
      if (!J) continue;
      const Jr = J[j];
      Jr.fill(0);
      const row = G.rows[q];
      const f = N * G.w[q];
      for (let c = 0; c < nUnknowns; c++) {
        const d = row[c] - G.mean[c];
        if (d) Jr[c] = -f * d;
      }
      for (let h = 0; h < K; h++) Jr[G.k[h]] -= G.w[q];
      Jr[G.k[q]] += 1;
    }
    return { norm, lnS, N };
  }

  /** A reduced system's bubble's gradient rows, `width` long. */
  function bubbleScratch(G, width) {
    if (G.width === width) return;
    G.rows = Array.from(G.ps, () => new Float64Array(width));
    G.mean = new Float64Array(width);
    G.width = width;
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
    /*
      A mineral's bounds in this cell (eq.bounds): none below 0 and none
      above, unless it is given its own. present[j] is 1 while it is held at
      saturation between them, 0 while it is at the lower and 4 at the upper,
      the water past saturation the way it cannot follow.
    */
    const loOf = (j) => (eqs[j].bounds ? eqs[j].bounds.lo[cell] : 0);
    const hiOf = (j) => (eqs[j].bounds ? eqs[j].bounds.hi[cell] : Infinity);
    const boundOf = (j) => { if (present[j] === 4) return hiOf(j); const lo = loOf(j); return Number.isFinite(lo) ? lo : 0; };
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
      let r = -lnKAtP(eq, cell, water);
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
          // Under SIT a coefficient also reads the species it is paired with; the volumes go with I and the water.
          const sd = sitPartners(act, eq.net, water);
          G += pressureTermI(eq, water);
          const wd = waterCoef(eq, water);
          for (let k = 0; k < na; k++) {
            if (lin[k]) continue;
            const si = part[k];
            let d = G * 0.5 * act.z[si] * act.z[si];
            if (wd) d += wd * awOf(act, water, si);
            if (sd) d += sd[si];
            if (d) row[k] += d * val[k];
          }
          if (sd) sitDone(act, eq.net);
        }
      }
      return r;
    };
    // A mineral's saturation index, ln(IAP/K), whichever side it is written on.
    const saturation = (j, water) => (minNu[j] < 0 ? 1 : -1) * relation(j, water, null);
    // Each of a group's members' ln of its share of the water -- the pressure the water holds a gas at, a
    // solid solution's member's saturation ratio -- and with rows its gradient.
    const bubbleLnE = (G, water, rows) => {
      for (let q = 0; q < G.rel.length; q++) {
        const row = rows ? G.rows[q] : null;
        if (row) row.fill(0);
        const f = -1 / G.nu[q];
        G.lnE[q] = f * relation(G.rel[q], water, row);
        if (row) for (let c = 0; c < na; c++) if (row[c]) row[c] *= f;
      }
    };
    // A group's ln of its members' shares of the water, together, less ln of their total.
    const bubbleExcess = (G, water) => {
      bubbleLnE(G, water, false);
      // Where it would go if it formed: a binary solid solution's side of its gap.
      G.formMode = groupFormsAt(G, cell);
      G.mode = 0;
      groupReal(G, na, false, cell);
      let top = -Infinity;
      for (let q = 0; q < G.rel.length; q++) top = Math.max(top, G.lnE[q]);
      let S = 0;
      for (let q = 0; q < G.rel.length; q++) S += Math.exp(G.lnE[q] - top);
      return top + Math.log(S) - G.lnP;
    };

    // None of a mineral is exactly none: its amount is set, not iterated
    // towards -- a damped step would only halve it, and leave 1e-30 of a
    // mineral the water is far from saturated in.
    const pin = () => {
      for (let j = 0; j < ne; j++) if (minOf[j] >= 0 && (!present[j] || present[j] === 4)) x[minOf[j]] = boundOf(j);
    };
    /*
      A STEP THAT MAKES IT WORSE IS HALVED, where a binary solid solution is
      in the cell: near the composition where its members mix most readily
      the composition the water gives it moves steeply with the water, and
      the capped steps went back and forth between two points without end.
      Only there: every other cell takes its steps as they come.
    */
    const backtrack = sys.groups.some((G) => G.def.coef === 'binary');
    const xPrev = backtrack ? new Float64Array(na) : null;
    const taken = backtrack ? new Float64Array(na) : null;
    const solve = () => {
      let converged = false;
      let normPrev = Infinity;
      let halvings = 0;
      pin();
      for (let it = 0; it < maxIter; it++) {
        iterations++;
        const water = evaluate();
        let norm = 0;
        for (let j = 0; j < ne; j++) {
          J[j].fill(0);
          const km = minOf[j];
          if (km >= 0 && (!present[j] || present[j] === 4)) {
            // None of the mineral, or as much as its bounds let it have: its amount is that, and the relation waits.
            F[j] = x[km] - boundOf(j);
            J[j][km] = 1;
            norm = Math.max(norm, Math.abs(F[j]) / Math.max(big, 1e-300));
            continue;
          }
          // A group's relations, while it is there, are its rows together (below).
          if (sys.inGroup[j] >= 0) continue;
          F[j] = relation(j, water, J[j]);
          norm = Math.max(norm, Math.abs(F[j]));
        }
        for (const G of sys.groups) {
          if (!present[G.rel[0]]) continue;
          bubbleLnE(G, water, true);
          norm = Math.max(norm, groupRowsAt(G, present[G.rel[0]], cell, (q) => x[G.k[q]], na, F, J, big).norm);
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
        // Each surface's potential: Gouy and Chapman, its error measured as one in ln a.
        for (let p = 0; p < sys.np; p++) {
          const row = ne + nb + p;
          const pot = sys.pots[p];
          J[row].fill(0);
          let Q = 0;
          for (const [k, zq] of pot.members) Q += zq * val[k];
          for (const [si, zq] of pot.fixedQ) Q += zq * C[off + si];
          // An area per mole of a mineral: its amount, an unknown where it is there, and its column.
          const pm = sys.pt.perM[pot.q];
          const km = pm >= 0 ? at[pm] : -1;
          const M = pm < 0 ? 1 : km >= 0 ? val[km] : C[off + pm];
          // CD-MUSIC: the next plane's potential, and plane 2's ions.
          const uNext = pot.nsi < 0 ? 0 : pot.next >= 0 ? x[pot.next] : Math.log(C[off + pot.nsi]);
          if (pot.ions) {
            const io = pot.ions;
            for (let i = 0; i < io.si.length; i++) io.m[i] = io.k[i] >= 0 ? val[io.k[i]] : C[off + io.si[i]];
          }
          const gc = potentialRow(sys.pt, pot.q, Q, water.I, !(water.I > 1e-10), x[pot.k], cell, M, uNext, pot.ions);
          F[row] = gc.r;
          J[row][pot.k] += gc.du;
          if (pot.next >= 0) J[row][pot.next] += gc.duNext;
          if (gc.dm) for (let i = 0; i < gc.dm.length; i++) if (pot.ions.k[i] >= 0) J[row][pot.ions.k[i]] += gc.dm[i] * pot.ions.m[i];
          if (km >= 0) J[row][km] += gc.dM;
          for (const [k, zq] of pot.members) J[row][k] += gc.dQ * zq * val[k];
          if (gc.dI) {
            for (let k = 0; k < na; k++) {
              const zz = lin[k] ? 0 : act.z[part[k]];
              if (zz) J[row][k] += gc.dI * 0.5 * zz * zz * val[k];
            }
          }
          norm = Math.max(norm, Math.abs(gc.r) / Math.max(gc.du, 1e-300));
        }
        residual = norm;
        if (backtrack && norm > normPrev && halvings < 12) {
          halvings++;
          for (let k = 0; k < na; k++) { taken[k] *= 0.5; x[k] = xPrev[k] - taken[k]; }
          pin();
          continue;
        }
        halvings = 0;
        normPrev = norm;
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
        if (backtrack) for (let k = 0; k < na; k++) { xPrev[k] = x[k]; taken[k] = damp * step[k]; }
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

      Only a relation that holds places a species: a mineral's while it is
      held at saturation, not one at none or at its upper bound, which says
      nothing of the water. FeS(ppt) at none in an oxic water, its sulfide
      at e^-326, put Fe+2 at e^302, capped at the largest total, and every
      iron species after it: the capped steps took 95 iterations a cell to
      bring them down at 5e-3 mol/kgw of calcite, and with 1e-2 did not in
      a hundred.
    */
    {
      const have = new Set();
      for (let k = 0; k < na; k++) if (lin[k] || C[off + part[k]] > 0) have.add(part[k]);
      const there = (j, skip) => (minOf[j] < 0 || present[j] === 1)
        && eqs[j].net.every(([si]) => si === skip || have.has(si) || at[si] < 0 && C[off + si] > 0);
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

    /*
      TWO MINERALS THAT CANNOT BOTH BE THERE -- gypsum and anhydrite, the same
      calcium sulfate: present together their amounts are not determined and
      the matrix is singular, and only at the one temperature where they are
      equally soluble could both relations hold. Where a set of minerals
      comes to that, one goes: the one the water is then undersaturated in,
      the others held, as a phase no longer stable goes over to the one that
      is. attempt() tries a set, from x0, the state before the set that
      failed; `drop` leaves it, `add` (or -1) comes in.
    */
    const x0 = Float64Array.from(x);
    const mins = [];
    for (let j = 0; j < ne; j++) if (minOf[j] >= 0 && sys.inGroup[j] < 0) mins.push(j);
    const attempt = (drop, add) => {
      x.set(x0);
      present[drop] = 0;
      x[minOf[drop]] = boundOf(drop);
      if (add >= 0) present[add] = 1;
      why = '';
      if (solve() && saturation(drop, evaluate()) <= 1e-9) return true;
      present[drop] = 1;
      if (add >= 0) present[add] = 0;
      why = 'singular';
      return false;
    };
    /*
      Where no set settles, the reason is the first one's: the matrix
      singular, or the iteration not settled ('unsettled') -- not every
      failure called singular, as each attempt's was.
    */
    let ok = solve();
    if (opts.activeSet && !ok) {
      // A start, or an event, that has two such minerals there at once; not the one an event brought in (opts.enter).
      const failed = why || 'unsettled';
      let tried = 0;
      for (const j of mins) {
        if (!present[j] || j === opts.enter) continue;
        tried++;
        if (attempt(j, -1)) { ok = true; break; }
      }
      if (!ok && tried) why = failed;
    }
    if (opts.activeSet && ok) {
      const groups = sys.groups;
      // A group comes and goes whole: its relations' present together.
      const setGroup = (G, v) => { for (const j of G.rel) { present[j] = v; if (!v) x[minOf[j]] = 0; } };
      let settled = !mins.length && !groups.length;
      for (let round = 0; round < 4 * mins.length + 8 * groups.length + 4 && !settled && ok; round++) {
        // A mineral that would have to be less than none of: it dissolves away; and so does a group.
        let pick = -1;
        let pickG = null;
        let by = 0;
        let cap = false;
        for (const j of mins) {
          if (present[j] !== 1) continue;
          const m = x[minOf[j]];
          const below = loOf(j) - m;
          const above = m - hiOf(j);
          if (below > 1e-12 * big && below > by) { by = below; pick = j; cap = false; }
          if (above > 1e-12 * big && above > by) { by = above; pick = j; cap = true; }
        }
        for (const G of groups) {
          if (!present[G.rel[0]]) continue;
          let N = 0;
          for (const j of G.rel) N += x[minOf[j]];
          if (N < -1e-12 * big && -N > by) { by = -N; pickG = G; }
        }
        if (pickG) {
          setGroup(pickG, 0);
          ok = solve();
          continue;
        }
        if (pick >= 0) {
          // Less than its lower bound, none under the usual one: it dissolves away to it; more than its upper: it is there.
          present[pick] = cap ? 4 : 0;
          x[minOf[pick]] = boundOf(pick);
          ok = solve();
          continue;
        }
        // One the water is supersaturated in, and none of it: it precipitates. Gases the water holds at more
        // than the total pressure between them: a bubble forms; and so does a solid solution the water is
        // supersaturated in.
        const water = evaluate();
        for (const j of mins) {
          if (present[j] === 1) continue;
          // At the lower bound and the water supersaturated: it precipitates; at the upper and undersaturated: it dissolves.
          const si = (present[j] === 4 ? -1 : 1) * saturation(j, water);
          if (si > 1e-9 && si > by) { by = si; pick = j; }
        }
        for (const G of groups) {
          if (present[G.rel[0]]) continue;
          const ex = bubbleExcess(G, water);
          if (ex > 1e-9 && ex > by) { by = ex; pickG = G; }
        }
        if (pickG) {
          setGroup(pickG, pickG.formMode || 1);
          ok = solve();
          continue;
        }
        if (pick >= 0) {
          x0.set(x);
          present[pick] = 1;
          ok = solve();
          // It cannot be there beside one that is: that one goes over to it.
          if (!ok) {
            const failed = why || 'unsettled';
            let tried = 0;
            for (const j of mins) {
              if (j === pick || !present[j]) continue;
              tried++;
              if (attempt(j, pick)) { ok = true; break; }
            }
            if (!ok && tried) why = failed;
          }
          continue;
        }
        // A binary solid solution whose composition has crossed into its miscibility gap, or out of it.
        let moved = false;
        for (const G of groups) {
          const mode = present[G.rel[0]];
          if (!mode || G.def.coef !== 'binary') continue;
          const { gap } = binaryAt(G.def, G.def.tk ? G.def.tk[cell] : G.def.tk0);
          let next = mode;
          if (!gap) next = 1;
          else if (mode === 2) {
            let N = 0;
            for (const k of G.k) N += x[k];
            const xb = x[G.k[1]] / N;
            next = xb > gap.xb2 + 1e-9 ? 3 : xb < gap.xb1 - 1e-9 ? 1 : 2;
          } else {
            bubbleLnE(G, evaluate(), false);
            const over = G.lnE[1] - G.lnE[0] - (gap.lnAb - gap.lnAc);
            if ((mode === 1 && over > 1e-9) || (mode === 3 && over < -1e-9)) next = 2;
          }
          if (next !== mode) { for (const j of G.rel) present[j] = next; moved = true; break; }
        }
        if (moved) {
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

  /* ----------------------------------------------------------------------
     THE REDUCED SPECIATION. A cell's relations hold the ln a of most of its
     species as linear combinations of a few -- as many as there are totals,
     its components -- so a cell can be speciated in those alone, as PHREEQC
     speciates a water in its master species: the components' ln a, the
     minerals' amounts, and under ACTIVITY the ionic strength and the
     water's ln a as unknowns with equations of their own. Every other
     species follows from them exactly, the relations holding by
     construction. A held run with the electron speciates every cell at
     every evaluation (the projected form), and 54 unknowns a cell became 16.
     ---------------------------------------------------------------------- */

  /**
   * Sets a cell system (cellSystem) up for reducedSpeciate: which aqueous
   * unknowns the relations work out from the rest (D) and which are the
   * components (K), D taken as `prefer` (part positions) orders them, and
   * the elimination that gives alpha_D = M rhs - E alpha_K, alpha = ln a and
   * rhs each relation's lnK less its water and fixed species. Null where the
   * system is not of that shape: the full one is used.
   */
  function reducedSystem(sys, prefer) {
    const { eqs, ne, nb, na, at, lin, minOf, isMin, act } = sys;
    // A real gas in a fixed volume reads every gas of its phase, and under Pitzer a coefficient every solute:
    // the full speciation.
    // So does an exchanger whose sites go with a mineral, each species' fraction reading all that is on it; and a
    // mineral with bounds of its own (eq.bounds).
    if (act && ((act.gas && act.gas.dln) || act.pz || (act.vol && !act.vol.idle)
      || (act.pt && (act.pt.cd || act.pt.perM.some((m) => m >= 0))) || (act.ex && act.ex.perAny))) return null;
    if (eqs.some((eq) => eq.bounds)) return null;
    // A surface's potential is no component and worked out from none: an
    // unknown of its own, as the ionic strength is, with Gouy and Chapman.
    const potOf = new Int32Array(na).fill(-1);
    sys.pots.forEach((pot, p) => { potOf[pot.k] = p; });
    const np = sys.np;
    const aq = [];
    for (let k = 0; k < na; k++) if (!lin[k] && potOf[k] < 0) aq.push(k);
    const naq = aq.length;
    const aqOf = new Int32Array(na).fill(-1);
    aq.forEach((k, i) => { aqOf[k] = i; });
    const aqRel = [];
    const minRel = [];
    for (let j = 0; j < ne; j++) (minOf[j] >= 0 ? minRel : aqRel).push(j);
    const nr = aqRel.length;
    if (naq - nr !== nb) return null;
    // [R | 1]: a row for each aqueous relation, R over the aqueous unknowns.
    const A = aqRel.map((j, r) => {
      const row = new Float64Array(naq + nr);
      for (const [si, nu] of eqs[j].net) {
        if (isMin[si]) continue;
        const k = at[si];
        if (k >= 0 && potOf[k] < 0) row[aqOf[k]] += nu;
      }
      row[naq + r] = 1;
      return row;
    });
    // Reduced row echelon, each row's pivot in the column `prefer` puts first.
    const pivotOf = [];
    let row = 0;
    for (const k of prefer) {
      const col = aqOf[k];
      if (col < 0 || row >= nr) continue;
      let best = -1;
      let mag = 1e-12;
      for (let r = row; r < nr; r++) if (Math.abs(A[r][col]) > mag) { mag = Math.abs(A[r][col]); best = r; }
      if (best < 0) continue;
      const t = A[row]; A[row] = A[best]; A[best] = t;
      const p = A[row][col];
      for (let c = 0; c < naq + nr; c++) A[row][c] /= p;
      for (let r = 0; r < nr; r++) {
        if (r === row) continue;
        const f = A[r][col];
        if (!f) continue;
        for (let c = 0; c < naq + nr; c++) A[r][c] -= f * A[row][c];
      }
      pivotOf.push(col);
      row++;
    }
    if (row !== nr) return null;
    const isPivot = new Uint8Array(naq);
    for (const c of pivotOf) isPivot[c] = 1;
    const K = [];
    for (let i = 0; i < naq; i++) if (!isPivot[i]) K.push(i);
    const constants = (j) => ({ lnK: eqs[j].lnK, eq: eqs[j], water: eqs[j].water || 0,
      fixed: eqs[j].net.filter(([si]) => at[si] < 0 && !isMin[si]),
      pot: eqs[j].net.filter(([si]) => at[si] >= 0 && potOf[at[si]] >= 0).map(([si, nu]) => [potOf[at[si]], nu]) });
    const mins = minRel.map((j) => {
      const nu = new Float64Array(naq);
      for (const [si, v] of eqs[j].net) {
        if (isMin[si]) continue;
        const k = at[si];
        if (k >= 0 && potOf[k] < 0) nu[aqOf[k]] += v;
      }
      return { j, k: minOf[j], nu, ...constants(j) };
    });
    // The ionic strength is an unknown wherever a coefficient or a potential reads it.
    const useI = !!act && ([...act.form].some((f) => (f >= 1 && f <= 5) || f === 7 || f === 8) || np > 0);
    // ...and the water's ln a where a relation has the water in it, or a Debye-Hueckel A and B read it (coefficientsAt).
    const useL = !!act && act.kind !== 'none'
      && (aqRel.some((j) => eqs[j].water) || minRel.some((j) => eqs[j].water)
        || [...act.form].some((f) => f === 2 || f === 3 || f === 4));
    const nK = K.length;
    const nm = mins.length;
    const M = A.map((rw) => rw.slice(naq));
    const rel = aqRel.map(constants);
    const sit = act && act.sit ? reducedSitSetup(sys, aq, rel, mins) : null;
    const iS = nK + nm + (useI ? 1 : 0) + (useL ? 1 : 0);
    const iP = iS + (sit ? sit.V.length : 0);
    if (sit) sit.iS = iS;
    // The groups -- a bubble, solid solutions: their relations among the minerals' rows, their members among
    // their amounts (bubbleRows); and each mineral's group, or -1, and place in it.
    const groupOfMin = new Int32Array(nm).fill(-1);
    const qOfMin = new Int32Array(nm).fill(-1);
    const groups = sys.groups.map((Gs, g) => {
      const ps = [];
      mins.forEach((mn, p) => { if (sys.inGroup[mn.j] === g) ps.push(p); });
      ps.forEach((p, q) => { groupOfMin[p] = g; qOfMin[p] = q; });
      const def = Gs.def;
      return { def, ps: Int32Array.from(ps), rel: Int32Array.from(ps, (p) => nb + p), k: Int32Array.from(ps, (p) => nK + p),
        prIdx: def.coef === 'pr' ? Int32Array.from(ps, (p) => def.gas.qOf[eqs[mins[p].j].mineral]) : null,
        nu: Float64Array.from(ps, (p) => eqs[mins[p].j].mineralNu), lnP: def.lnP,
        lnE: new Float64Array(ps.length), w: new Float64Array(ps.length), rows: null, mean: null, width: 0, out: [] };
    });
    return {
      sit,
      groups, groupOfMin, qOfMin,
      sys, aq, naq, aqOf, D: pivotOf, K, nK, nm, nr,
      E: A.map((rw) => Float64Array.from(K, (i) => rw[i])),
      M,
      rel,
      // The potentials: alpha_D less mPot u, u each potential's ln a; and
      // the potential each aqueous unknown is on, with its charge, or -1.
      np, iP, potOf,
      onPot: Int32Array.from(aq, (k) => {
        const s = sys.part[k];
        return np && sys.pt.of[s] >= 0 && sys.pt.zs[s] ? sys.pots.findIndex((pot) => pot.q === sys.pt.of[s]) : -1;
      }),
      mPot: M.map((Mr) => {
        const out = new Float64Array(np);
        rel.forEach((r, c) => { for (const [p, nu] of r.pot) out[p] += Mr[c] * nu; });
        return out;
      }),
      // M times the relations' ln K and water, made once: alpha_D = mLnK - L mWater
      // - M (the fixed species' terms, a few relations have any) - E alpha_K.
      mLnK: Float64Array.from(M, (Mr) => rel.reduce((acc, r, c) => acc + Mr[c] * r.lnK, 0)),
      // ...and cell by cell where a relation's ln K is its cell's (reducedLnK).
      thermo: rel.some((r) => r.eq.lnKc), mLnKc: new Float64Array(M.length),
      mCell: -1, mStamp: -1,
      mWater: Float64Array.from(M, (Mr) => rel.reduce((acc, r, c) => acc + Mr[c] * r.water, 0)),
      withFixed: rel.map((r, c) => (r.fixed.length ? c : -1)).filter((c) => c >= 0),
      mins, useI, useL,
      iI: nK + nm, iL: nK + nm + (useI ? 1 : 0), nz: iP + np,
      // Where each aqueous unknown is a component, or -1.
      kOf: Int32Array.from({ length: naq }, (_, i) => K.indexOf(i)),
      dOf: Int32Array.from({ length: naq }, (_, i) => pivotOf.indexOf(i)),
      // The totals each part position counts in, with its coefficient.
      inTotals: Array.from({ length: na }, (_, k) => {
        const out = [];
        if (sys.exch && sys.exch[k]) return out;
        for (let q = 0; q < nb; q++) if (sys.U[q][k]) out.push([q, sys.U[q][k]]);
        return out;
      }),
    };
  }

  /**
   * M times the relations' ln K in cell `cell` (reducedSystem's mLnK): the
   * one where no relation's ln K is its cell's, and otherwise made for the
   * cell and kept until the next cell, or until the cells' ln K are worked
   * out afresh (thermoStamp).
   */
  function reducedLnK(rs, cell) {
    if (!rs.thermo) return rs.mLnK;
    if (rs.mCell === cell && rs.mStamp === thermoStamp) return rs.mLnKc;
    const { M, rel } = rs;
    for (let r = 0; r < M.length; r++) {
      const Mr = M[r];
      let acc = 0;
      for (let c = 0; c < rel.length; c++) acc += Mr[c] * lnKIn(rel[c].eq, cell);
      rs.mLnKc[r] = acc;
    }
    rs.mCell = cell;
    rs.mStamp = thermoStamp;
    return rs.mLnKc;
  }

  /*
    THE REDUCED SPECIATION UNDER SIT. A coefficient reads the species it is
    paired with as well as the ionic strength, so the ln a of the components
    no longer make every species explicit: a species' concentration needs
    its coefficient, which needs its partners' concentrations. So V, a set of
    the cell's species that touches every pair between two of its aqueous
    unknowns, each get their SIT sum Q = sum (eps + eps1 I) m as an unknown
    with an equation of its own, as the ionic strength has; every other
    species' partners are then in V or known, and its coefficient follows.
    The pairs of a water mostly run through its own few ions, Na+ and Cl-
    say, so V is small: found greedily, the species in most pairs first.
  */

  /**
   * V for a reduced system under SIT, and the maps the evaluation needs. A
   * species paired with itself is in V, and so is a fixed species paired at
   * all (its coefficient goes into the relations' constants, which every
   * other species reads), and a species on an exchanger that is fixed has
   * its ion in V where the ion is paired.
   */
  function reducedSitSetup(sys, aq, rel, mins) {
    const { part, act, ns } = sys;
    const rows = act.sit.rows;
    const ex = act.ex;
    const spOfAq = Int32Array.from(aq, (k) => part[k]);
    const aqOfSp = new Int32Array(ns).fill(-1);
    spOfAq.forEach((s, i) => { aqOfSp[s] = i; });
    const fixedSp = [...new Set([...rel.flatMap((r) => r.fixed.map(([s]) => s)),
      ...mins.flatMap((mn) => mn.fixed.map(([s]) => s))])];
    const inV = new Uint8Array(ns);
    const paired = (s) => act.form[s] === 4 && !!rows[s];
    for (const s of fixedSp) {
      if (paired(s)) inV[s] = 1;
      if (act.form[s] === 5 && paired(ex.ion[s])) inV[ex.ion[s]] = 1;
    }
    for (const s of spOfAq) if (paired(s) && rows[s].k.includes(s)) inV[s] = 1;
    const edges = act.sit.pairs.filter((p) => p.i !== p.j && aqOfSp[p.i] >= 0 && aqOfSp[p.j] >= 0).map((p) => [p.i, p.j]);
    for (;;) {
      const open = edges.filter(([i, j]) => !inV[i] && !inV[j]);
      if (!open.length) break;
      const deg = new Map();
      for (const [i, j] of open) { deg.set(i, (deg.get(i) || 0) + 1); deg.set(j, (deg.get(j) || 0) + 1); }
      let best = -1;
      let most = 0;
      for (const [s, d] of deg) if (d > most || (d === most && s < best)) { best = s; most = d; }
      inV[best] = 1;
    }
    const V = [];
    for (let s = 0; s < ns; s++) if (inV[s]) V.push(s);
    const vOf = new Int32Array(ns).fill(-1);
    V.forEach((s, v) => { vOf[s] = v; });
    // On an exchanger (its share of the sites, and its ion's coefficient), and on a surface (its share).
    const onEx = new Uint8Array(ns);
    if (ex) for (const s of ex.list) onEx[s] = 1;
    const onSf = new Uint8Array(ns);
    if (act.sf) for (const s of act.sf.list) onSf[s] = 1;
    return { V, vOf, spOfAq, aqOfSp, fixedSp, onEx, onSf, iS: -1 };
  }

  /**
   * One state of a reduced cell under SIT, as reducedState: every aqueous
   * unknown's ln a (alpha), concentration (val) and coefficient (lnG), V's
   * coefficients from their sums at rs.sit.iS. With `grad`, the gradients
   * of each aqueous unknown's ln a (Ga) and ln C (Gr), and of each fixed or
   * aqueous species' ln gamma (Gl), over the unknowns and then over the
   * concentrations of `outside`: nz + outside.length columns.
   */
  function reducedStateSit(rs, z, C, off, cell, outside, grad) {
    const { sys, aq, naq, D, K, nK, nr, E, M, rel, useI, useL, iI, iL, mWater, withFixed, np, iP, mPot, nz } = rs;
    const mLnK = reducedLnK(rs, cell);
    const { act, ns } = sys;
    const { V, vOf, spOfAq, aqOfSp, fixedSp, onEx, onSf, iS } = rs.sit;
    const rows = act.sit.rows;
    const ex = act.ex;
    const sf = act.sf;
    const nOut = outside.length;
    const nx = nz + nOut;
    let sc = rs.scratch;
    if (!sc || sc.nx !== nx) {
      const outOf = new Int32Array(ns).fill(-1);
      outside.forEach((s, o) => { outOf[s] = o; });
      const Gl = new Array(ns).fill(null);
      for (const s of spOfAq) Gl[s] = new Float64Array(nx);
      for (const s of fixedSp) Gl[s] = new Float64Array(nx);
      sc = rs.scratch = { nx, outOf, Gl, alpha: new Float64Array(naq), val: new Float64Array(naq),
        lnG: new Float64Array(ns), fixedTerm: new Float64Array(nr),
        Gfix: Array.from({ length: nr }, () => new Float64Array(nx)),
        Ga: Array.from({ length: naq }, () => new Float64Array(nx)),
        Gr: Array.from({ length: naq }, () => new Float64Array(nx)) };
    }
    const { outOf, Gl, alpha, val, lnG, fixedTerm, Gfix, Ga, Gr } = sc;
    const LN = Math.LN10;
    const I = useI ? z[iI] : 1e-10;
    const low = !(I > 1e-10);
    const Ie = low ? 1e-10 : I;
    const sq = Math.sqrt(Ie);
    const T = 1 + 1.5 * sq;
    // A at the water's own a(H2O), the unknown ln a, as the full speciation has it (sitAt), with its derivative.
    let Ah = act.Ac ? act.Ac[cell] : act.A;
    let dlnAh = 0;
    if (useL && act.wt) {
      const wA = waterAt(act.wtc ? act.wtc[cell] : act.wt, Math.exp(z[iL]));
      Ah = wA.A;
      dlnAh = wA.dlnA;
    }
    const Fd = (-Ah * sq) / T;
    const dFd = low ? 0 : -Ah / (2 * sq * T * T);
    const at = cell * ns;
    const z2 = (s) => act.z[s] * act.z[s];
    // A coefficient V or the Debye-Hueckel term alone gives (a species paired outside V is done later).
    const base = (s) => {
      if (vOf[s] >= 0) return LN * (z2(s) * Fd + z[iS + vOf[s]]);
      if (act.form[s] === 4) return LN * z2(s) * Fd;
      return 0;
    };
    const baseGrad = (s, g) => {
      g.fill(0);
      if (useI && act.form[s] === 4) g[iI] = LN * z2(s) * dFd;
      if (dlnAh && act.form[s] === 4) g[iL] += LN * z2(s) * Fd * dlnAh;
      if (vOf[s] >= 0) g[iS + vOf[s]] = LN;
    };
    // 1. The fixed species: in V, unpaired, or on an exchanger with an ion that is either.
    for (const f of fixedSp) {
      if (act.form[f] === 5) {
        const ion = ex.ion[f];
        lnG[f] = ex.pw[f] * base(ion) + ex.shift[at + f];
        if (grad) { baseGrad(ion, Gl[f]); for (let c = 0; c < nx; c++) Gl[f][c] *= ex.pw[f]; }
      } else if (onEx[f]) {
        lnG[f] = ex.shift[at + f];
        if (grad) Gl[f].fill(0);
      } else if (onSf[f]) {
        lnG[f] = sf.shift[at + f];
        if (grad) Gl[f].fill(0);
      } else {
        lnG[f] = base(f);
        if (grad) baseGrad(f, Gl[f]);
      }
    }
    // 2. Each relation's fixed species, and the components' and the rest's ln a.
    for (const c of withFixed) {
      let v = 0;
      if (grad) Gfix[c].fill(0);
      for (const [si, nu] of rel[c].fixed) {
        v += nu * (Math.log(Math.max(C[off + si], 1e-300)) + lnG[si]);
        if (grad) { const g = Gl[si]; const gf = Gfix[c]; for (let q = 0; q < nx; q++) if (g[q]) gf[q] += nu * g[q]; }
      }
      fixedTerm[c] = v;
    }
    const L = useL ? z[iL] : 0;
    for (let j = 0; j < nK; j++) {
      alpha[K[j]] = z[j];
      if (grad) { Ga[K[j]].fill(0); Ga[K[j]][j] = 1; }
    }
    for (let r = 0; r < nr; r++) {
      const Mr = M[r];
      const Er = E[r];
      let a = mLnK[r] - L * mWater[r];
      for (const c of withFixed) a -= Mr[c] * fixedTerm[c];
      for (let j = 0; j < nK; j++) a -= Er[j] * z[j];
      for (let p = 0; p < np; p++) a -= mPot[r][p] * z[iP + p];
      alpha[D[r]] = a;
      if (!grad) continue;
      const g = Ga[D[r]];
      g.fill(0);
      for (let j = 0; j < nK; j++) g[j] = -Er[j];
      if (useL) g[iL] = -mWater[r];
      for (let p = 0; p < np; p++) g[iP + p] = -mPot[r][p];
      for (const c of withFixed) {
        const f = Mr[c];
        if (!f) continue;
        const gf = Gfix[c];
        for (let q = 0; q < nx; q++) if (gf[q]) g[q] -= f * gf[q];
      }
    }
    // 3. V's own concentrations, then the coefficients that read them, then everything else's.
    const mOf = (j) => (aqOfSp[j] >= 0 ? val[aqOfSp[j]] : C[off + j]);
    const done = new Uint8Array(naq);
    for (let i = 0; i < naq; i++) {
      const s = spOfAq[i];
      if (vOf[s] < 0) continue;
      lnG[s] = base(s);
      val[i] = Math.exp(alpha[i] - lnG[s]);
      done[i] = 1;
      if (grad) {
        baseGrad(s, Gl[s]);
        const ga = Ga[i];
        const gr = Gr[i];
        const gl = Gl[s];
        for (let q = 0; q < nx; q++) gr[q] = ga[q] - gl[q];
      }
    }
    // 4. The rest: paired ones from V and what is known; on an exchanger its ion's; on a surface its share.
    const lnGrest = (s, i) => {
      if (act.form[s] === 4) {
        let lg = z2(s) * Fd;
        let dI = z2(s) * dFd;
        const r = rows[s];
        const gl = grad ? Gl[s] : null;
        if (gl) gl.fill(0);
        if (r) {
          for (let q = 0; q < r.k.length; q++) {
            const j = r.k[q];
            const e = r.e[q] + Ie * r.e1[q];
            const m = mOf(j);
            lg += e * m;
            dI += r.e1[q] * m;
            if (!gl) continue;
            const ja = aqOfSp[j];
            if (ja >= 0) {
              if (!done[ja] || vOf[j] < 0) throw new RtmError('The SIT pairs were not covered (reducedSitSetup).');
              const gr = Gr[ja];
              const f = LN * e * val[ja];
              for (let c = 0; c < nx; c++) if (gr[c]) gl[c] += f * gr[c];
            } else if (outOf[j] >= 0) gl[nz + outOf[j]] += LN * e;
          }
        }
        if (gl && useI && !low) gl[iI] += LN * dI;
        if (gl && dlnAh) gl[iL] += LN * z2(s) * Fd * dlnAh;
        return LN * lg;
      }
      if (act.form[s] === 5) {
        const ion = ex.ion[s];
        const ia = aqOfSp[ion];
        if (ia >= 0 && !done[ia]) rest(ia);
        if (grad) { const gl = Gl[s]; const gi = Gl[ion]; for (let c = 0; c < nx; c++) gl[c] = ex.pw[s] * gi[c]; }
        return ex.pw[s] * lnG[ion] + ex.shift[at + s];
      }
      if (grad) Gl[s].fill(0);
      if (onEx[s]) return ex.shift[at + s];
      if (onSf[s]) return sf.shift[at + s];
      if (act.form[s] === 6 && act.gas.fixed === 'volume') return act.gas.lnGc ? act.gas.lnGc[cell] : act.gas.lnG;
      return 0;
    };
    function rest(i) {
      const s = spOfAq[i];
      lnG[s] = lnGrest(s, i);
      val[i] = Math.exp(alpha[i] - lnG[s]);
      done[i] = 1;
      if (grad) {
        const ga = Ga[i];
        const gr = Gr[i];
        const gl = Gl[s];
        for (let q = 0; q < nx; q++) gr[q] = ga[q] - gl[q];
      }
    }
    for (let i = 0; i < naq; i++) if (!done[i]) rest(i);
    return { I, low, Ie, L, Fd, dFd, mOf };
  }

  /**
   * reducedResidual under SIT: the same rows, and V's sums, Q - sum (eps +
   * eps1 I) m = 0, after the water's; the water's ln a SIT's. With J, the
   * Jacobian in the unknowns, and with B (rows nz of outside.length) the
   * derivatives in the concentrations of `outside`, for reducedSensitivity.
   */
  function reducedResidualSit(rs, z, C, off, totals, w, present, cell, outside, F, J, B) {
    const { sys, aq, naq, nK, nm, mins, useI, useL, iI, iL, nz, inTotals, np, iP } = rs;
    const { nb, part, act } = sys;
    const { V, spOfAq, aqOfSp, iS } = rs.sit;
    const sit = act.sit;
    const nOut = outside.length;
    const grad = !!(J || B);
    const { Ie, L, low, mOf } = reducedStateSit(rs, z, C, off, cell, outside, grad);
    const sc = rs.scratch;
    const { alpha, val, lnG, Ga, Gr, Gl, outOf } = sc;
    const LN = Math.LN10;
    if (J) for (let r = 0; r < nz; r++) J[r].fill(0);
    if (B) for (let r = 0; r < nz; r++) B[r].fill(0);
    const addG = (row, f, g) => {
      if (!f) return;
      if (J) { const Jr = J[row]; for (let c = 0; c < nz; c++) if (g[c]) Jr[c] += f * g[c]; }
      if (B) { const Br = B[row]; for (let o = 0; o < nOut; o++) if (g[nz + o]) Br[o] += f * g[nz + o]; }
    };
    let norm = 0;
    // The totals, minerals included.
    const scale = sc.scale || (sc.scale = new Float64Array(nb));
    for (let q = 0; q < nb; q++) { F[q] = -totals[q]; scale[q] = Math.abs(totals[q]); }
    for (let i = 0; i < naq; i++) {
      const k = aq[i];
      for (const [q, u] of inTotals[k]) {
        const f = u * (w ? w[k] : 1);
        F[q] += f * val[i];
        scale[q] += Math.abs(f * val[i]);
        if (grad) addG(q, f * val[i], Gr[i]);
      }
    }
    for (let p = 0; p < nm; p++) {
      const k = mins[p].k;
      for (const [q, u] of inTotals[k]) {
        const f = u * (w ? w[k] : 1);
        F[q] += f * z[nK + p];
        scale[q] += Math.abs(f * z[nK + p]);
        if (J) J[q][nK + p] += f;
      }
    }
    for (let q = 0; q < nb; q++) norm = Math.max(norm, Math.abs(F[q]) / Math.max(scale[q], 1e-300));
    // The minerals, and a bubble.
    let big = 0;
    for (let q = 0; q < nb; q++) big = Math.max(big, Math.abs(totals[q]));
    for (const Gq of rs.groups) if (present[mins[Gq.ps[0]].j]) bubbleScratch(Gq, sc.nx);
    for (let p = 0; p < nm; p++) {
      const row = nb + p;
      const mn = mins[p];
      if (!present[mn.j]) {
        F[row] = z[nK + p];
        if (J) J[row][nK + p] = 1;
        norm = Math.max(norm, Math.abs(z[nK + p]) / Math.max(big, 1e-300));
        continue;
      }
      // A member of a group that is there: its share of the water, and its gradient over nx, for bubbleRows.
      const Gb = rs.groupOfMin[p] >= 0 ? rs.groups[rs.groupOfMin[p]] : null;
      const qb = Gb ? rs.qOfMin[p] : -1;
      if (qb >= 0) {
        // A bubble's relation: its gas's ln of pressure in the water, and its gradient over nx, for bubbleRows.
        let r = mn.water * L - lnKIn(mn.eq, cell);
        const g = Gb.rows[qb];
        if (grad) g.fill(0);
        for (const [si, nu] of mn.fixed) {
          r += nu * (Math.log(Math.max(C[off + si], 1e-300)) + lnG[si]);
          if (grad) { const gl = Gl[si]; for (let c = 0; c < sc.nx; c++) if (gl[c]) g[c] += nu * gl[c]; }
        }
        for (let i = 0; i < naq; i++) {
          if (!mn.nu[i]) continue;
          r += mn.nu[i] * alpha[i];
          if (grad) { const ga = Ga[i]; for (let c = 0; c < sc.nx; c++) if (ga[c]) g[c] += mn.nu[i] * ga[c]; }
        }
        if (grad && useL) g[iL] += mn.water;
        const f = -1 / Gb.nu[qb];
        Gb.lnE[qb] = f * r;
        if (grad) for (let c = 0; c < sc.nx; c++) if (g[c]) g[c] *= f;
        continue;
      }
      let r = mn.water * L - lnKIn(mn.eq, cell);
      for (const [si, nu] of mn.fixed) {
        r += nu * (Math.log(Math.max(C[off + si], 1e-300)) + lnG[si]);
        if (grad) addG(row, nu, Gl[si]);
      }
      for (let i = 0; i < naq; i++) {
        if (!mn.nu[i]) continue;
        r += mn.nu[i] * alpha[i];
        if (grad) addG(row, mn.nu[i], Ga[i]);
      }
      if (J && useL) J[row][iL] += mn.water;
      F[row] = r;
      norm = Math.max(norm, Math.abs(r));
    }
    for (const Gb of rs.groups) {
      if (!present[mins[Gb.ps[0]].j]) continue;
      // Its rows over nx, then the unknowns' part into J and the outside species' into B.
      const out = Gb.out;
      for (const row of Gb.rel) if (!out[row] || out[row].length !== sc.nx) out[row] = new Float64Array(sc.nx);
      norm = Math.max(norm, groupRowsAt(Gb, present[mins[Gb.ps[0]].j], cell, (q) => z[Gb.k[q]], sc.nx, F, grad ? out : null,
        big).norm);
      if (grad) {
        for (const row of Gb.rel) {
          const o = out[row];
          if (J) { const Jr = J[row]; for (let c = 0; c < nz; c++) Jr[c] = o[c]; }
          if (B) { const Br = B[row]; for (let q = 0; q < nOut; q++) Br[q] = o[nz + q]; }
        }
      }
    }
    // The ionic strength.
    if (useI) {
      let Isum = 0;
      for (let i = 0; i < naq; i++) {
        const zz = act.z[spOfAq[i]];
        if (!zz) continue;
        Isum += 0.5 * zz * zz * val[i];
        if (grad) addG(iI, -0.5 * zz * zz * val[i], Gr[i]);
      }
      outside.forEach((si, o) => {
        const zz = act.z[si];
        Isum += 0.5 * zz * zz * C[off + si];
        if (B) B[iI][o] -= 0.5 * zz * zz;
      });
      F[iI] = z[iI] - Isum;
      norm = Math.max(norm, Math.abs(F[iI]) / Math.max(Isum, 1e-300));
      if (J) J[iI][iI] += 1;
    }
    // The water: SIT's osmotic coefficient, the ionic strength the unknown.
    if (useL) {
      const sq = Math.sqrt(Ie);
      const T = 1 + 1.5 * sq;
      // A at the water's own a(H2O), its unknown ln a (sitAt, reducedStateSit).
      let Ah = act.Ac ? act.Ac[cell] : act.A;
      let dlnAh = 0;
      if (act.wt) {
        const wA = waterAt(act.wtc ? act.wtc[cell] : act.wt, Math.exp(L));
        Ah = wA.A;
        dlnAh = wA.dlnA;
      }
      let os = (-2 * Ah / 3.375) * (T - 2 * Math.log(T) - 1 / T);
      if (J && dlnAh) J[iL][iL] += (LN * os * dlnAh) / SIT_WATER;
      let osI = low ? 0 : (-Ah * sq) / (T * T);
      let osum = 0;
      const dm = sc.dm || (sc.dm = new Float64Array(sys.ns));
      dm.fill(0);
      for (let i = 0; i < naq; i++) if (act.solute[spOfAq[i]]) osum += val[i];
      for (const si of outside) if (act.solute[si]) osum += C[off + si];
      for (const p of sit.pairs) {
        const mi = mOf(p.i);
        const mj = mOf(p.j);
        const f = p.e * p.c + p.e1 * (1 + p.c * Ie);
        os += mi * mj * f;
        if (!low) osI += mi * mj * p.e1 * p.c;
        dm[p.i] += f * mj;
        dm[p.j] += f * mi;
      }
      F[iL] = L + (osum + LN * os) / SIT_WATER;
      norm = Math.max(norm, Math.abs(F[iL]));
      if (grad) {
        if (J) { J[iL][iL] += 1; if (useI) J[iL][iI] += (LN * osI) / SIT_WATER; }
        for (let i = 0; i < naq; i++) {
          const s = spOfAq[i];
          const d = (act.solute[s] ? 1 : 0) + LN * dm[s];
          if (d) addG(iL, (d * val[i]) / SIT_WATER, Gr[i]);
        }
        if (B) outside.forEach((si, o) => { B[iL][o] += ((act.solute[si] ? 1 : 0) + LN * dm[si]) / SIT_WATER; });
      }
    }
    // V's sums.
    for (let v = 0; v < V.length; v++) {
      const s = V[v];
      const row = iS + v;
      const r = sit.rows[s];
      let sum = 0;
      let dI = 0;
      for (let q = 0; q < r.k.length; q++) {
        const j = r.k[q];
        const e = r.e[q] + Ie * r.e1[q];
        const m = mOf(j);
        sum += e * m;
        dI += r.e1[q] * m;
        if (!grad) continue;
        const ja = aqOfSp[j];
        if (ja >= 0) addG(row, -e * val[ja], Gr[ja]);
        else if (B && outOf[j] >= 0) B[row][outOf[j]] -= e;
      }
      F[row] = z[row] - sum;
      norm = Math.max(norm, Math.abs(F[row]));
      if (J) { J[row][row] += 1; if (useI && !low) J[row][iI] -= dI; }
    }
    // Each surface's potential: Gouy and Chapman.
    const pt = sys.pt;
    for (let p = 0; p < np; p++) {
      const row = iP + p;
      let Q = 0;
      for (const [si, zq] of sys.pots[p].fixedQ) Q += zq * C[off + si];
      const dQ = grad ? (sc.dQ || (sc.dQ = new Float64Array(sc.nx))) : null;
      if (dQ) dQ.fill(0);
      for (let i = 0; i < naq; i++) {
        if (rs.onPot[i] !== p) continue;
        const zq = pt.zs[spOfAq[i]];
        Q += zq * val[i];
        if (dQ) { const g = Gr[i]; for (let c = 0; c < sc.nx; c++) if (g[c]) dQ[c] += zq * val[i] * g[c]; }
      }
      const gc = gouyChapman(pt, sys.pots[p].q, Q, Ie, low, z[row], cell);
      F[row] = gc.r;
      norm = Math.max(norm, Math.abs(gc.r) / Math.max(gc.du, 1e-300));
      if (!grad) continue;
      addG(row, gc.dQ, dQ);
      if (J) { if (useI) J[row][iI] += gc.dI; J[row][row] += gc.du; }
    }
    return norm;
  }

  /**
   * One state of a reduced cell: from the unknowns z, every aqueous
   * unknown's ln a (alpha) and concentration (val), the coefficients, and
   * the derivatives of alpha_D in I and L (hI, hL). The scratch is the
   * system's own.
   */
  function reducedState(rs, z, C, off, cell) {
    const { sys, aq, naq, D, K, nK, nr, E, M, rel, useI, useL, mWater, withFixed, np, iP, mPot } = rs;
    const mLnK = reducedLnK(rs, cell);
    const { part, act, ns } = sys;
    const sc = rs.scratch || (rs.scratch = {
      alpha: new Float64Array(naq), val: new Float64Array(naq), lnG: new Float64Array(ns), dG: new Float64Array(ns),
      fixedTerm: new Float64Array(nr), fixedDI: new Float64Array(nr),
      hI: new Float64Array(nr), hL: new Float64Array(nr),
    });
    const { alpha, val, lnG, dG, fixedTerm, fixedDI, hI, hL } = sc;
    let I = 1e-10;
    let low = true;
    const L = useL ? z[rs.iL] : 0;
    if (act) {
      if (useI) { I = z[rs.iI]; low = !(I > 1e-10); }
      coefficientsAt(act, low ? 1e-10 : I, low, lnG, dG, cell, useL ? Math.exp(L) : 1);
    } else { lnG.fill(0); dG.fill(0); }
    for (const c of withFixed) {
      let v = 0;
      let g = 0;
      for (const [si, nu] of rel[c].fixed) {
        v += nu * (Math.log(Math.max(C[off + si], 1e-300)) + lnG[si]);
        g += nu * dG[si];
      }
      fixedTerm[c] = v;
      fixedDI[c] = g;
    }
    for (let j = 0; j < nK; j++) alpha[K[j]] = z[j];
    for (let r = 0; r < nr; r++) {
      const Mr = M[r];
      const Er = E[r];
      let a = mLnK[r] - L * mWater[r];
      let gi = 0;
      for (const c of withFixed) { a -= Mr[c] * fixedTerm[c]; gi -= Mr[c] * fixedDI[c]; }
      for (let j = 0; j < nK; j++) a -= Er[j] * z[j];
      for (let p = 0; p < np; p++) a -= mPot[r][p] * z[iP + p];
      alpha[D[r]] = a;
      hI[r] = gi;
      hL[r] = -mWater[r];
    }
    for (let i = 0; i < naq; i++) val[i] = Math.exp(alpha[i] - lnG[part[aq[i]]]);
    return { I, low, L, sc };
  }

  /**
   * The residuals of a reduced cell at z, into F, and with J (rows nz of
   * nz) their Jacobian: each total, each mineral's saturation (or its amount,
   * while there is none of it), the ionic strength, the water's ln a. Returns
   * the convergence measure, as speciateCell's: relations in ln K, totals
   * relative to their size.
   */
  function reducedResidual(rs, z, C, off, totals, w, present, cell, outside, F, J) {
    const { sys, aq, naq, K, nK, nm, mins, useI, useL, iI, iL, nz, kOf, dOf, E, inTotals, np, iP, mPot } = rs;
    const { nb, part, act, lin, ns } = sys;
    const { I, low, L, sc } = reducedState(rs, z, C, off, cell);
    const { alpha, val, dG, hI, hL } = sc;
    if (J) for (let r = 0; r < nz; r++) J[r].fill(0);
    let Iout = 0;
    let Sout = 0;
    if (act) {
      for (const si of outside) { const zz = act.z[si]; Iout += zz * zz * C[off + si]; if (act.solute[si]) Sout += C[off + si]; }
      Iout *= 0.5;
    }
    let norm = 0;
    // The totals, minerals included.
    const scale = sc.scale || (sc.scale = new Float64Array(nb));
    for (let q = 0; q < nb; q++) { F[q] = -totals[q]; scale[q] = Math.abs(totals[q]); }
    let Isum = Iout;
    let Ssum = Sout;
    const g = sc.g || (sc.g = new Float64Array(nz));
    // Each potential's surface charge, and its derivatives in z.
    const pt = sys.pt;
    const Qp = sc.Qp || (sc.Qp = new Float64Array(np));
    const dQ = sc.dQ || (sc.dQ = Array.from({ length: np }, () => new Float64Array(nz)));
    for (let p = 0; p < np; p++) {
      let q0 = 0;
      for (const [si, zq] of sys.pots[p].fixedQ) q0 += zq * C[off + si];
      Qp[p] = q0;
      if (J) dQ[p].fill(0);
    }
    for (let i = 0; i < naq; i++) {
      const k = aq[i];
      const s = part[k];
      const v = val[i];
      const zz = act ? act.z[s] : 0;
      if (zz) Isum += 0.5 * zz * zz * v;
      if (act && act.solute[s]) Ssum += v;
      const tl = inTotals[k];
      for (const [q, u] of tl) { const x = u * (w ? w[k] : 1) * v; F[q] += x; scale[q] += Math.abs(x); }
      const p = rs.onPot[i];
      if (p >= 0) Qp[p] += pt.zs[s] * v;
      // A species in no total, neither ion nor solute and on no charged surface adds nothing to the Jacobian.
      if (!J || (!tl.length && !(useI && zz) && p < 0)) continue;
      // d val_i / dz: val (d alpha - dG dI).
      g.fill(0);
      const kk = kOf[i];
      if (kk >= 0) g[kk] = v;
      else {
        const r = dOf[i];
        const Er = E[r];
        for (let j = 0; j < nK; j++) g[j] = -v * Er[j];
        if (useI) g[iI] = v * hI[r];
        if (useL) g[iL] = v * hL[r];
        for (let pp = 0; pp < np; pp++) g[iP + pp] = -v * mPot[r][pp];
      }
      if (useI && !low) g[iI] -= v * dG[s];
      for (const [q, u] of tl) {
        const f = u * (w ? w[k] : 1);
        const Jq = J[q];
        for (let c = 0; c < nz; c++) if (g[c]) Jq[c] += f * g[c];
      }
      if (useI && zz) { const Ji = J[iI]; const f = 0.5 * zz * zz; for (let c = 0; c < nz; c++) if (g[c]) Ji[c] -= f * g[c]; }
      if (p >= 0) { const dq = dQ[p]; const f = pt.zs[s]; for (let c = 0; c < nz; c++) if (g[c]) dq[c] += f * g[c]; }
    }
    for (let p = 0; p < nm; p++) {
      const k = mins[p].k;
      const m = z[nK + p];
      for (const [q, u] of inTotals[k]) {
        const f = u * (w ? w[k] : 1);
        F[q] += f * m;
        scale[q] += Math.abs(f * m);
        if (J) J[q][nK + p] += f;
      }
    }
    for (let q = 0; q < nb; q++) norm = Math.max(norm, Math.abs(F[q]) / Math.max(scale[q], 1e-300));
    // The minerals: saturation while there is some, none while there is none.
    let big = 0;
    for (let q = 0; q < nb; q++) big = Math.max(big, Math.abs(totals[q]));
    if (J) for (const Gq of rs.groups) if (present[mins[Gq.ps[0]].j]) bubbleScratch(Gq, nz);
    for (let p = 0; p < nm; p++) {
      const row = nb + p;
      const mn = mins[p];
      if (!present[mn.j]) {
        F[row] = z[nK + p];
        if (J) J[row][nK + p] = 1;
        norm = Math.max(norm, Math.abs(z[nK + p]) / Math.max(big, 1e-300));
        continue;
      }
      let r = mn.water * L - lnKIn(mn.eq, cell);
      let gI = 0;
      for (const [si, nu] of mn.fixed) { r += nu * (Math.log(Math.max(C[off + si], 1e-300)) + sc.lnG[si]); gI += nu * dG[si]; }
      for (let i = 0; i < naq; i++) if (mn.nu[i]) r += mn.nu[i] * alpha[i];
      // A member of a group that is there: its share of the water, and its gradient, for bubbleRows.
      const G = rs.groupOfMin[p] >= 0 ? rs.groups[rs.groupOfMin[p]] : null;
      const qb = G ? rs.qOfMin[p] : -1;
      if (qb >= 0) G.lnE[qb] = -r / G.nu[qb];
      else {
        F[row] = r;
        norm = Math.max(norm, Math.abs(r));
      }
      if (!J) continue;
      const Jr = qb >= 0 ? G.rows[qb] : J[row];
      if (qb >= 0) Jr.fill(0);
      for (let i = 0; i < naq; i++) {
        const nu = mn.nu[i];
        if (!nu) continue;
        const kk = kOf[i];
        if (kk >= 0) { Jr[kk] += nu; continue; }
        const d = dOf[i];
        const Er = E[d];
        for (let j = 0; j < nK; j++) Jr[j] -= nu * Er[j];
        if (useI) Jr[iI] += nu * hI[d];
        if (useL) Jr[iL] += nu * hL[d];
        for (let p = 0; p < np; p++) Jr[iP + p] -= nu * mPot[d][p];
      }
      if (useI && !low) Jr[iI] += gI;
      if (useL) Jr[iL] += mn.water;
      if (qb >= 0) { const f = -1 / G.nu[qb]; for (let c = 0; c < nz; c++) if (Jr[c]) Jr[c] *= f; }
    }
    for (const G of rs.groups) {
      if (!present[mins[G.ps[0]].j]) continue;
      norm = Math.max(norm, groupRowsAt(G, present[mins[G.ps[0]].j], cell, (q) => z[G.k[q]], nz, F, J, big).norm);
    }
    // The ionic strength, and the water's ln a.
    if (useI) {
      F[iI] = I - Isum;
      norm = Math.max(norm, Math.abs(F[iI]) / Math.max(Isum, 1e-300));
      if (J) J[iI][iI] += 1;
    }
    if (useL) {
      let aw = 1 - 0.017 * Ssum;
      const dry = !(aw > 1e-6);
      if (dry) aw = 1e-6;
      F[iL] = L - Math.log(aw);
      norm = Math.max(norm, Math.abs(F[iL]));
      if (J) {
        J[iL][iL] += 1;
        if (!dry) {
          // d(-ln aw)/d val = 0.017/aw for each solute, through d val/dz.
          const f = 0.017 / aw;
          for (let i = 0; i < naq; i++) {
            const s = part[aq[i]];
            if (!act.solute[s]) continue;
            const v = val[i];
            const kk = kOf[i];
            if (kk >= 0) { J[iL][kk] += f * v; } else {
              const r = dOf[i];
              const Er = E[r];
              for (let j = 0; j < nK; j++) J[iL][j] -= f * v * Er[j];
              if (useI) J[iL][iI] += f * v * hI[r];
              J[iL][iL] += f * v * hL[r];
              for (let p = 0; p < np; p++) J[iL][iP + p] -= f * v * mPot[r][p];
            }
            if (useI && !low) J[iL][iI] -= f * v * dG[s];
          }
        }
      }
    }
    // Each surface's potential: Gouy and Chapman, its error measured as one in ln a.
    for (let p = 0; p < np; p++) {
      const row = iP + p;
      const gc = gouyChapman(pt, sys.pots[p].q, Qp[p], I, low, z[row], cell);
      F[row] = gc.r;
      norm = Math.max(norm, Math.abs(gc.r) / Math.max(gc.du, 1e-300));
      if (!J) continue;
      const Jr = J[row];
      const dq = dQ[p];
      for (let c = 0; c < nz; c++) if (dq[c]) Jr[c] += gc.dQ * dq[c];
      Jr[iI] += gc.dI;
      Jr[row] += gc.du;
    }
    return norm;
  }

  /**
   * A cell's speciation in its components (see reducedSystem), with the
   * contract of speciateCell: C read for the start and written back for the
   * unknowns of sys.part, x the unknowns as speciateCell has them (ln C, or
   * a mineral's amount). Damped as speciateCell is, by the largest change in
   * any species' ln a. No active set: `present` is as given.
   */
  function reducedSpeciate(rs, C, off, totals, w, present, opts = {}) {
    const { sys, aq, naq, K, nK, nm, mins, useI, useL, iI, iL, nz, E, D, np, iP, mPot } = rs;
    const { part, act, ns } = sys;
    const tol = opts.tol || 1e-10;
    const maxIter = opts.maxIter || 100;
    const cell = opts.cell !== undefined ? opts.cell : Math.round(off / ns);
    const outside = rs.outside || [];
    const z = new Float64Array(nz);
    const F = new Float64Array(nz);
    const J = rs.J || (rs.J = Array.from({ length: nz }, () => new Float64Array(nz)));
    const lnG = new Float64Array(ns);
    const dG = new Float64Array(ns);
    let big = 0;
    for (let q = 0; q < totals.length; q++) big = Math.max(big, Math.abs(totals[q]));
    // The start, from C: the components' ln a, the amounts, I and the water.
    let lnAw = 0;
    let I0 = 1e-10;
    if (act) {
      const wt = activityAt(act, C, off, lnG, dG, cell);
      I0 = wt.I;
      lnAw = wt.lnAw;
    }
    for (let j = 0; j < nK; j++) {
      const s = part[aq[K[j]]];
      const c = C[off + s];
      z[j] = (c > 0 ? Math.log(c) : Math.log(Math.max(1e-12 * big, 1e-300))) + lnG[s];
    }
    for (let p = 0; p < nm; p++) z[nK + p] = present[mins[p].j] ? C[off + part[mins[p].k]] : 0;
    if (useI) z[iI] = I0;
    if (useL) z[iL] = lnAw;
    for (let p = 0; p < np; p++) z[iP + p] = Math.log(Math.max(C[off + sys.pots[p].si], 1e-300));
    // Under SIT, V's sums as the start has them.
    const st = rs.sit;
    if (st) {
      st.V.forEach((s, v) => {
        const r = act.sit.rows[s];
        let q = 0;
        for (let u = 0; u < r.k.length; u++) q += (r.e[u] + I0 * r.e1[u]) * C[off + r.k[u]];
        z[st.iS + v] = q;
      });
    }
    const residualAt = st
      ? (FF, JJ) => reducedResidualSit(rs, z, C, off, totals, w, present, cell, outside, FF, JJ, null)
      : (FF, JJ) => reducedResidual(rs, z, C, off, totals, w, present, cell, outside, FF, JJ);
    let iterations = 0;
    let residual = Infinity;
    let converged = false;
    const dAlpha = rs.dAlpha || (rs.dAlpha = new Float64Array(naq));
    for (let it = 0; it < maxIter; it++) {
      iterations++;
      // Where it starts settled, as a projection mostly does, the residual
      // alone says so; the Jacobian is made only for a step.
      const lazy = it === 0 && opts.asStarted;
      const norm = residualAt(F, lazy ? null : J);
      residual = norm;
      if (!(norm === norm)) break;
      if (norm < tol) converged = true;
      if (converged && lazy) break;
      if (lazy) residualAt(F, J);
      const step = solveInPlace(J, F, nz);
      if (!step) { if (converged) break; return { converged: false, iterations, residual, x: null, why: 'singular' }; }
      if (st) {
        // Under SIT, the change each species' ln C would make, from its gradient.
        const { Gr } = rs.scratch;
        for (let i = 0; i < naq; i++) {
          const g = Gr[i];
          let d = 0;
          for (let c = 0; c < nz; c++) if (g[c]) d += g[c] * step[c];
          dAlpha[i] = d;
        }
      } else {
        // The change each species' ln a would make: the components', and the rest through E, hI, hL.
        const { hI, hL } = rs.scratch;
        for (let j = 0; j < nK; j++) dAlpha[K[j]] = step[j];
        for (let r = 0; r < D.length; r++) {
          const Er = E[r];
          let d = 0;
          for (let j = 0; j < nK; j++) d -= Er[j] * step[j];
          if (useI) d += hI[r] * step[iI];
          if (useL) d += hL[r] * step[iL];
          for (let p = 0; p < np; p++) d -= mPot[r][p] * step[iP + p];
          dAlpha[D[r]] = d;
        }
      }
      /*
        Damped by the species that matter: none moves its ln C by more than 2
        where it is, before or after, more than 1e-14 of the largest total,
        and none rises above ten times that total (or 1 mol/kg). A species
        that is 1e-150 of everything moves as it must: capped like the rest,
        sulfide's complexes, whose ln a follows the electron's 24 times
        over, held the pe to 0.08 an iteration where it has to jump by 38.
      */
      const { val } = rs.scratch;
      const lnSig = Math.log(Math.max(1e-14 * big, 1e-300));
      const lnCap = Math.log(Math.max(10 * big, 1));
      let damp = 1;
      for (let i = 0; i < naq; i++) {
        const d = dAlpha[i];
        if (!d || (sys.exch && sys.exch[aq[i]])) continue;
        const lnC = Math.log(Math.max(val[i], 1e-300));
        const lnNew = lnC - d;
        if (Math.max(lnC, lnNew) > lnSig && Math.abs(d) * damp > 2) damp = 2 / Math.abs(d);
        if (lnC - damp * d > lnCap && d < 0) damp = Math.max((lnCap - lnC) / -d, 0);
      }
      if (!(damp > 0)) damp = 2 / Math.max(...Array.from(dAlpha, Math.abs), 2);
      // A potential's ln a moves by no more than 2 either.
      for (let p = 0; p < np; p++) if (Math.abs(step[iP + p]) * damp > 2) damp = 2 / Math.abs(step[iP + p]);
      // The ionic strength stays above a tenth of what it was.
      if (useI && step[iI] > 0 && z[iI] - damp * step[iI] < 0.1 * z[iI]) damp = (0.9 * z[iI]) / step[iI];
      for (let c = 0; c < nz; c++) z[c] -= damp * step[c];
      for (let p = 0; p < nm; p++) if (!present[mins[p].j]) z[nK + p] = 0;
      if (converged) break;
    }
    if (!converged) return { converged: false, iterations, residual, x: null, why: '' };
    // Back into C, and the unknowns as speciateCell has them.
    if (st) reducedStateSit(rs, z, C, off, cell, outside, false); else reducedState(rs, z, C, off, cell);
    const { alpha, val, lnG: lg } = rs.scratch;
    const x = new Float64Array(sys.na);
    for (let i = 0; i < naq; i++) {
      const k = aq[i];
      C[off + part[k]] = val[i];
      x[k] = alpha[i] - lg[part[k]];
    }
    for (let p = 0; p < nm; p++) {
      const k = mins[p].k;
      C[off + part[k]] = z[nK + p];
      x[k] = z[nK + p];
    }
    for (let p = 0; p < np; p++) {
      const pot = sys.pots[p];
      C[off + pot.si] = Math.exp(z[iP + p]);
      x[pot.k] = z[iP + p];
    }
    return { converged: true, iterations, residual, x, why: '', z };
  }

  /**
   * The derivatives of a reduced cell's speciation, at the state C holds
   * (one reducedSpeciate left): of each unknown of sys.part, as
   * speciateCell's x, in each total (dT, na rows of nb) and in each species
   * of `outside` (dO): the implicit function theorem on reducedResidual.
   */
  function reducedSensitivity(rs, C, off, totals, w, present, cell, z, outside) {
    if (rs.sit) return reducedSensitivitySit(rs, C, off, totals, w, present, cell, z, outside);
    const { sys, aq, naq, K, nK, nm, mins, useI, useL, iI, iL, nz, E, kOf, dOf, np, iP, mPot } = rs;
    const { na, nb, part, act } = sys;
    const F = new Float64Array(nz);
    const J = Array.from({ length: nz }, () => new Float64Array(nz));
    reducedResidual(rs, z, C, off, totals, w, present, cell, outside, F, J);
    const { val, dG, hI, hL } = rs.scratch;
    const low = !(useI && z[iI] > 1e-10);
    const piv = luFactor(J, nz);
    if (!piv) return null;
    // dx of every part position from dz.
    const expand = (dz, out, col) => {
      for (let i = 0; i < naq; i++) {
        const k = aq[i];
        const s = part[k];
        let d;
        const kk = kOf[i];
        if (kk >= 0) d = dz[kk];
        else {
          const r = dOf[i];
          const Er = E[r];
          d = 0;
          for (let j = 0; j < nK; j++) d -= Er[j] * dz[j];
          if (useI) d += hI[r] * dz[iI];
          if (useL) d += hL[r] * dz[iL];
          for (let p = 0; p < np; p++) d -= mPot[r][p] * dz[iP + p];
        }
        if (useI && !low) d -= dG[s] * dz[iI];
        out[k][col] = d;
      }
      for (let p = 0; p < nm; p++) out[mins[p].k][col] = dz[nK + p];
      for (let p = 0; p < np; p++) out[sys.pots[p].k][col] = dz[iP + p];
    };
    const dT = Array.from({ length: na }, () => new Float64Array(nb));
    const dO = Array.from({ length: na }, () => new Float64Array(outside.length));
    const b = new Float64Array(nz);
    for (let q = 0; q < nb; q++) {
      b.fill(0);
      b[q] = 1;
      luSolve(J, piv, b, nz);
      expand(b, dT, q);
    }
    if (act && outside.length) {
      let Ssum = 0;
      for (let i = 0; i < naq; i++) if (act.solute[part[aq[i]]]) Ssum += val[i];
      for (const si of outside) if (act.solute[si]) Ssum += C[off + si];
      const aw = 1 - 0.017 * Ssum;
      const dry = !(aw > 1e-6);
      outside.forEach((si, i) => {
        b.fill(0);
        const zz = act.z[si];
        if (useI && !low) b[iI] = 0.5 * zz * zz;
        if (useL && !dry && act.solute[si]) b[iL] = -0.017 / aw;
        luSolve(J, piv, b, nz);
        expand(b, dO, i);
      });
    }
    return { dT, dO };
  }

  /**
   * reducedSensitivity under SIT: the implicit function theorem on
   * reducedResidualSit, whose gradients run over the outside species'
   * concentrations as well -- a coefficient reads them directly where they
   * are paired with its species.
   */
  function reducedSensitivitySit(rs, C, off, totals, w, present, cell, z, outside) {
    const { sys, aq, naq, nK, nm, mins, nz, np, iP } = rs;
    const { na, nb } = sys;
    const nOut = outside.length;
    const F = new Float64Array(nz);
    const J = Array.from({ length: nz }, () => new Float64Array(nz));
    const B = Array.from({ length: nz }, () => new Float64Array(nOut));
    reducedResidualSit(rs, z, C, off, totals, w, present, cell, outside, F, J, B);
    const { Gr } = rs.scratch;
    const piv = luFactor(J, nz);
    if (!piv) return null;
    // dx of every part position from dz, and directly from outside species o where o >= 0.
    const expand = (dz, out, col, o) => {
      for (let i = 0; i < naq; i++) {
        const g = Gr[i];
        let d = o >= 0 ? g[nz + o] : 0;
        for (let c = 0; c < nz; c++) if (g[c]) d += g[c] * dz[c];
        out[aq[i]][col] = d;
      }
      for (let p = 0; p < nm; p++) out[mins[p].k][col] = dz[nK + p];
      for (let p = 0; p < np; p++) out[sys.pots[p].k][col] = dz[iP + p];
    };
    const dT = Array.from({ length: na }, () => new Float64Array(nb));
    const dO = Array.from({ length: na }, () => new Float64Array(nOut));
    const b = new Float64Array(nz);
    for (let q = 0; q < nb; q++) {
      b.fill(0);
      b[q] = 1;
      luSolve(J, piv, b, nz);
      expand(b, dT, q, -1);
    }
    for (let o = 0; o < nOut; o++) {
      for (let r = 0; r < nz; r++) b[r] = -B[r][o];
      luSolve(J, piv, b, nz);
      expand(b, dO, o, o);
    }
    return { dT, dO };
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
      if (km >= 0 && (!present[j] || present[j] === 4)) { J[j][km] = 1; continue; }
      const eq = eqs[j];
      let G = 0;
      for (const [si, nu] of eq.net) {
        if (isMin[si]) continue;
        if (act) G += nu * sys.dG[si];
        const k = at[si];
        if (k >= 0) J[j][k] += nu;
      }
      if (!act) continue;
      G += pressureTermI(eq, water);
      const wv = waterCoef(eq, water);
      const sd = sitPartners(act, eq.net, water);
      const d = (si) => G * 0.5 * act.z[si] * act.z[si] + (wv ? wv * awOf(act, water, si) : 0) + (sd ? sd[si] : 0);
      for (let k = 0; k < na; k++) {
        if (lin[k]) continue;
        const v = d(part[k]);
        if (v) J[j][k] += v * C[off + part[k]];
      }
      if (O) outside.forEach((si, i) => { O[j][i] = d(si); });
      if (sd) sitDone(act, eq.net);
    }
    // Each group while it is there -- a bubble, a solid solution: its relations' rows together (bubbleRows). Inside a
    // miscibility gap (mode 2) each relation holds at a constant activity, and its row is the relation's own, above.
    for (const G of sys.groups) {
      if (!present[G.rel[0]] || present[G.rel[0]] === 2) continue;
      G.mode = present[G.rel[0]];
      const K = G.rel.length;
      const oRows = O ? G.rel.map(() => new Float64Array(outside.length)) : null;
      for (let q = 0; q < K; q++) {
        const j = G.rel[q];
        const eq = eqs[j];
        const f = -1 / G.nu[q];
        let r = -lnKAtP(eq, cell, water);
        for (const [si, nu] of eq.net) {
          if (isMin[si]) continue;
          r += nu * (Math.log(Math.max(C[off + si], 1e-300)) + (act ? sys.lnG[si] : 0));
        }
        if (act && eq.water) r += eq.water * water.lnAw;
        G.lnE[q] = f * r;
        const row = G.rows[q];
        for (let c = 0; c < na; c++) row[c] = f * J[j][c];
        if (O) for (let i = 0; i < outside.length; i++) oRows[q][i] = f * O[j][i];
      }
      const lu = groupReal(G, na, true, cell);
      if (lu && O) {
        const col = new Float64Array(K);
        for (let i = 0; i < outside.length; i++) {
          for (let q = 0; q < K; q++) col[q] = oRows[q][i];
          luSolve(lu.Jm, lu.piv, col, K);
          for (let q = 0; q < K; q++) oRows[q][i] = col[q];
        }
      }
      const res = bubbleRows(G, (q) => C[off + part[G.k[q]]], na, new Float64Array(ne), J, 1);
      if (O) {
        for (let i = 0; i < outside.length; i++) {
          let mean = 0;
          for (let q = 0; q < K; q++) mean += G.w[q] * oRows[q][i];
          O[G.rel[0]][i] = mean;
          for (let q = 1; q < K; q++) O[G.rel[q]][i] = -res.N * G.w[q] * (oRows[q][i] - mean);
        }
      }
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
    // Gouy and Chapman, each potential's: its charge, the ionic strength, itself.
    for (let p = 0; p < sys.np; p++) {
      const row = ne + nb + p;
      const pot = sys.pots[p];
      let Q = 0;
      for (const [k, zq] of pot.members) Q += zq * C[off + part[k]];
      for (const [si, zq] of pot.fixedQ) Q += zq * C[off + si];
      const pm = sys.pt.perM[pot.q];
      const km = pm >= 0 ? sys.at[pm] : -1;
      if (pot.ions) {
        const io = pot.ions;
        for (let i = 0; i < io.si.length; i++) io.m[i] = C[off + io.si[i]];
      }
      const gc = potentialRow(sys.pt, pot.q, Q, water.I, !(water.I > 1e-10), Math.log(C[off + pot.si]), cell,
        pm >= 0 ? C[off + pm] : 1, pot.nsi >= 0 ? Math.log(C[off + pot.nsi]) : 0, pot.ions);
      J[row][pot.k] += gc.du;
      if (pot.next >= 0) J[row][pot.next] += gc.duNext;
      // CD-MUSIC's plane 2: every ion, in its column, or with what is outside where it is not an unknown.
      if (gc.dm) {
        const io = pot.ions;
        for (let i = 0; i < gc.dm.length; i++) {
          if (io.k[i] >= 0) J[row][io.k[i]] += gc.dm[i] * io.m[i];
          else if (O) { const o = outside.indexOf(io.si[i]); if (o >= 0) O[row][o] += gc.dm[i]; }
        }
      }
      // An area per mole of a mineral: in its column, or with what is outside where it is not an unknown.
      if (km >= 0) J[row][km] += gc.dM;
      else if (pm >= 0 && O) { const i = outside.indexOf(pm); if (i >= 0) O[row][i] += gc.dM; }
      for (const [k, zq] of pot.members) J[row][k] += gc.dQ * zq * C[off + part[k]];
      if (gc.dI) {
        for (let k = 0; k < na; k++) {
          const zz = lin[k] ? 0 : act.z[part[k]];
          if (zz) J[row][k] += gc.dI * 0.5 * zz * zz * C[off + part[k]];
        }
        if (O) outside.forEach((si, i) => { O[row][i] = gc.dI * 0.5 * act.z[si] * act.z[si]; });
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
      const { lnK, th } = readLogK(parts, line, 'a phase', false);
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
      out.set(name, { name, c0, net: [...net].filter(([, c]) => c !== 0), water, lnK, th, lnKc: null, sign: 1, line, text });
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
      case 'neg': {
        // Folded, so that an exponent -(n) reads as not depending on what n does not.
        const d = derivative(node.a, id, line);
        return d.type === 'num' ? NUM(-d.v === 0 ? 0 : -d.v) : { type: 'neg', a: d };
      }
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
    // An activity model's concentrations are molalities: a CONC_UNIT of mol/L says otherwise.
    if (settings.CONC_UNIT === 'mol/L' && settings.ACTIVITY !== 'none') {
      const at = sections.SETTINGS.find((l) => /^CONC_UNIT\s*=/i.test(l.text));
      throw new RtmError(`CONC_UNIT = mol/L, but under ACTIVITY = ${settings.ACTIVITY} the concentrations are molalities, `
        + 'mol/kgw: leave CONC_UNIT out, or write mol/kgw.', at ? at.line : undefined);
    }
    const species = readSpecies(sections.SPECIES);
    const reactions = sections.REACTIONS.map(({ text: t, line }) => parseReaction(t, line));

    const grid = makeGrid(settings);
    const warnings = [];
    // A name a warning thinks mistyped, and what it may have meant: { line, name, meant: [names] }, for the page to offer.
    const fixes = [];
    // Null unless ACTIVITY asks for one (activityModel), or there is an
    // exchanger (exchangeSetup, once the relations are read).
    let act = activityModel(settings, species, warnings, sections.SIT, sections.PITZER, sections.LLNL);
    // The molar volumes, for each log K at the water's pressure (readVolumes, volumesAt).
    const vol = readVolumes(sections.VOLUMES, species, act, settings);
    // <CONDUCTANCE>: what the water's conductance, density and viscosity are worked out from (QUANTITIES).
    const cond = readConductance(sections.CONDUCTANCE, species, act);
    if (vol) {
      act.vol = vol;
      // Idle for the log K, but not where the density is made of them (<CONDUCTANCE>).
      if (vol.idle && !cond) {
        warnings.push(`<VOLUMES>: the water is at ${act.wt.atmGiven} atm at ${settings.TEMPERATURE} C, and PHREEQC corrects a `
          + 'log K for the pressure above one atmosphere alone: the volumes change nothing here.');
      }
    }
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
    // Down its activity: every solute that diffuses at a D of its own (DIFFUSION_GRADIENT, npFaces).
    const actGrad = transport && !!settings.DIFFUSION && settings.DIFFUSION_GRADIENT === 'activity';
    if (actGrad && (!act || settings.ACTIVITY === 'none')) {
      throw new RtmError('DIFFUSION_GRADIENT = activity has each species diffuse down its activity, which needs '
        + 'activity coefficients: set ACTIVITY.');
    }
    const agSpecies = actGrad ? species.map((sp, k) => k).filter((k) => mobile[k] && species[k].D > 0 && act.solute[k]) : [];
    // An ion's place in npIons, or -1: the coupling reads its factor there.
    const npAt = new Int32Array(species.length).fill(-1);
    npIons.forEach(({ s: k }, a) => { npAt[k] = a; });

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
    /*
      THE RESERVOIRS. A reservoir end (LEFT or RIGHT = reservoir) is a face
      held, as a dirichlet one is, at the water of a well-mixed reservoir,
      and that water is a cell of its own: outside the column, after every
      cell of it in the state, with the model's whole chemistry -- as a batch
      run of the model would have it -- and no transport at all. The column
      takes from it and gives to it across the face without changing it;
      only its own reactions do. A source whose strength decays, a chain whose
      daughters grow in the water that feeds the column, and skbrtm's
      Dirichlet end, whose held first cell goes on reacting, are each one.

      It is the cell beside it in everything but transport -- the same i, x
      and width to a parameter or a starting value -- so it has that cell's
      parameters, temperature and R, and reacts as that cell would. It starts
      where a dirichlet face is held, each species at its left= or right= or
      else its <SPECIES> value, unless an <INITIAL> line names it. `cells`
      stays the column's, so that nothing the page reads cell by cell meets
      it; `allCells` and `reservoir` say where it is.
    */
    const resSides = transport
      ? ['left', 'right'].filter((side) => settings[side.toUpperCase()] === 'reservoir') : [];
    const resCell = { left: -1, right: -1 };
    resSides.forEach((side, r) => { resCell[side] = ncol * stride + r; });
    const placeCells = (centre) => {
      const out = [];
      for (let i = 0; i < ncol; i++) {
        out.push({ i, j: 0, x: col.centres[i], xm: 0 });
        for (let j = 1; j <= nm; j++) out.push({ i, j, x: col.centres[i], xm: centre ? centre[j - 1] : 0 });
      }
      for (const side of resSides) {
        const i = side === 'left' ? 0 : last;
        out.push({ i, j: 0, x: col.centres[i], xm: 0, reservoir: side });
      }
      return out;
    };
    let geom = placeCells(null);
    // Where a cell is, as a message says it: its index and its layer, or the reservoir it is.
    const whereIs = (c) => (geom[c].reservoir ? ` in the ${geom[c].reservoir} reservoir`
      : ` in cell ${geom[c].i}${geom[c].j > 0 ? `, layer ${geom[c].j} of the rock` : ''}`);
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
      // Which channels are this line's: its forward one first, then a backward one (what each reaction does, QUANTITIES).
      rx.chanFirst = channels.length;
      const stoich = new Map();
      const bump = (i, c) => stoich.set(i, (stoich.get(i) || 0) + c);
      for (const [c, name] of rx.reactants) bump(needSpecies(name, rx.line), -c);
      for (const [c, name] of rx.products) bump(needSpecies(name, rx.line), +c);
      const net = [...stoich.entries()].filter(([, c]) => c !== 0);
      if (!net.length) warnings.push(`Line ${rx.line}: the reaction changes nothing.`);
      // What is no amount cannot be made or used up at a rate.
      const none = net.find(([i]) => species[i].exchanger);
      if (none) {
        throw new RtmError(`${species[none[0]].name} is an exchanger, which is no amount and cannot react at a rate: `
          + 'exchange at a rate is a relation between species on it with a kf, Ca+2 + 2 NaX <=> CaX2 + 2 Na+.', rx.line);
      }
      /*
        The electron is no amount either, but what the couples tied to it
        hold is a total, the electrons, and a reaction that takes or gives
        them -- Pyrite + 2 H+ + 2 e- => Fe+2 + 2 HS-, as PHREEQC's PHASES
        write it -- moves that total, which the couples then share out at
        their one pe (holdEquilibria). So it needs them held all through the
        run; with the pe fixed, the electrons come and go from outside.
      */
      const eIn = net.find(([i]) => species[i].electron);
      if (eIn && settings.EQUILIBRATE !== 2 && !species[eIn[0]].fixed) {
        throw new RtmError(`${species[eIn[0]].name} is the electron: a reaction can take or give electrons only where the `
          + 'relations with it are held all through the run, EQUILIBRATE = always, and the couples tied to it share out '
          + 'what the reaction moves. Or write the reaction between species, Fe+2 + 0.25 O2 + H+ => Fe+3 + 0.5 H2O.',
        rx.line);
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
        // The names the line gives expressions, put in.
        src = expandNames(src, rx.exprs);
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
          } else if ((id === 'TK' || id === 'TC') && !params.index.has(id) && !rx.params.has(id)) {
            // The cell's temperature, in kelvin or C, unless the text has a parameter or constant of that name.
            aq.push({ id, q: registerAQ({ kind: id }, rx.line) });
          } else if (!rx.params.has(id) && !params.index.has(id) && id !== 't' && !/^__tv\d+__$/.test(id)) {
            throw new RtmError(`"${id}" in a rate law is not a parameter of this reaction, a `
              + 'parameter in <PARAMETERS>, the time t, a species in brackets, an activity in braces, '
              + 'I, TK or TC, or SI(phase) or SR(phase). Write a concentration as [name].', rx.line);
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
      rx.chanCount = channels.length - rx.chanFirst;
    }

    /*
      THE TEMPERATURE: a number of degrees C, or an expression of the
      parameters -- a temperature that differs from cell to cell -- and the
      clock, t and the tables read at it as a rate law reads them -- one that
      goes with time. A number is put in at once: each relation's log K and
      all else that reads the temperature are worked out at it, and stay. An
      expression is worked out in each cell, at the start and, where it reads
      the clock, at every time the model is evaluated at (thermoAt, below),
      and what reads it is worked out in each cell at its own.
    */
    const tcFixed = typeof settings.TEMPERATURE === 'number' ? settings.TEMPERATURE : null;
    let tempCode = null;      // TEMPERATURE as code in P, pb, t and TV; null for a number
    let tempCells = false;    // it reads a parameter, and differs from cell to cell
    let tempClock = false;    // it reads the clock
    if (tcFixed === null) {
      const tline = settings.TEMPERATURE_line;
      const src = settings.TEMPERATURE;
      let ast;
      try {
        ast = FacsimileModel.parseExpression(src, tline);
      } catch (e) {
        throw new RtmError(`TEMPERATURE = "${src}": ${e.message.replace(/^Line \d+: /, '')}`, tline);
      }
      ast = (function atTheClock(node) {
        if (!node || typeof node !== 'object') return node;
        const call = node.type === 'call' ? tableCall(node, tables, tline) : null;
        if (call) {
          const arg = fold(call.arg, new Map());
          for (const id of mentioned(arg)) {
            if (id === 't') continue;
            throw new RtmError(`"${node.name}(...)" in TEMPERATURE is read at a time: its argument may use t and nothing `
              + `else, and "${id}" is not t. A temperature that differs from cell to cell is a parameter of `
              + '<PARAMETERS>, which may read a table of place, and its name is used here.', tline);
          }
          const key = `${call.tab.name}#${call.col}#${JSON.stringify(arg)}`;
          if (!clockReads.has(key)) clockReads.set(key, { k: clockReads.size, tab: call.tab, col: call.col, arg });
          return { type: 'id', name: `__tv${clockReads.get(key).k}__` };
        }
        if (node.type === 'call') return { ...node, args: node.args.map(atTheClock) };
        if (node.type === 'bin') return { ...node, l: atTheClock(node.l), r: atTheClock(node.r) };
        if (node.type === 'neg') return { ...node, a: atTheClock(node.a) };
        return node;
      }(ast));
      ast = fold(ast, new Map());
      for (const id of mentioned(ast)) {
        if (params.index.has(id)) tempCells = true;
        else if (id === 't' || /^__tv\d+__$/.test(id)) tempClock = true;
        else {
          throw new RtmError(`"${id}" in TEMPERATURE is not a parameter in <PARAMETERS>, the time t or a table read at `
            + 'it: TEMPERATURE is a number of degrees C, a parameter for one that differs from cell to cell, or '
            + 'name(t), a table read at the clock, for one that goes with time.', tline);
        }
      }
      tempCode = emit(ast, (id) => {
        if (params.index.has(id)) return `P[pb + ${params.index.get(id)}]`;
        if (id === 't') return 't';
        return `TV[${/^__tv(\d+)__$/.exec(id)[1]}]`;
      }, tline);
    }
    // Each cell's temperature, C and kelvin, once the cells are known (thermoAt).
    const thermo = { tc: null, tk: null, t: NaN, varies: tempCode !== null, cells: tempCells, clock: tempClock };
    // A relation's or a phase's log K at a TEMPERATURE that is a number.
    const atFixedTemperature = (list) => {
      if (tcFixed === null) return;
      for (const r of list) if (r.th) r.lnK = logKAt(r.th, tcFixed + 273.15) * Math.LN10;
    };

    /*
      The equilibria. Those given a kf are ALSO enforced while the run goes on,
      as an ordinary reversible pair with kb = kf/K -- fast kinetics, which
      these solvers are built for, rather than a constraint, which they are
      not. Without a kf an equilibrium is used for speciation and nothing else.
    */
    const equilibria = readEquilibria(sections.EQUILIBRIUM, index);
    // Each relation by its equation, as the budget by each reaction names it.
    for (const eq of equilibria) eq.eqn = eq.text ? splitTop(eq.text)[0].trim() : '';
    checkReactionLines(species, index, nameOf, reactions, channels, aqList, equilibria, patches, warnings, fixes);
    atFixedTemperature(equilibria);
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
    /*
      A MINERAL HELD AT ANOTHER PHASE'S SATURATION, PHREEQC's alternative
      reaction (EQUILIBRIUM_PHASES Fix_H+ -7 NaOH): the relation's equation
      is what dissolves -- NaOH_r <=> Na+ + OH- -- and SI(Fix_H+) = -7 the
      phase of <PHASES> whose saturation index it holds there, dissolving or
      precipitating as much as that takes. Held, the relation is the
      phase's, its log K the phase's with the target, oriented as the
      mineral is written; what it moves is what it dissolves into, the
      phase's species taken back out (eq.moves, conservationBasis).
    */
    const siPhases = equilibria.some((eq) => eq.siOf) ? readPhases(sections.PHASES, index) : null;
    for (const eq of equilibria) {
      if (!eq.siOf) continue;
      const { phase, target } = eq.siOf;
      if (eq.mineral < 0) {
        throw new RtmError(`"${eq.text}" holds SI(${phase}) at ${target}, and has no mineral in it: what dissolves to hold `
          + 'it is a mineral, NaOH_r 10 mineral.', eq.line);
      }
      const ph = siPhases.get(phase);
      if (!ph) {
        throw new RtmError(`SI(${phase}): there is no phase ${phase} in <PHASES> -- give its dissolution there, `
          + `${phase} <=> H+, logK = 0.`, eq.line);
      }
      const f = -eq.mineralNu;
      const written = new Map(eq.net);
      eq.net = [[eq.mineral, eq.mineralNu], ...ph.net.map(([k, c]) => [k, f * c])];
      eq.water = f * ph.water;
      eq.lnK = f * (ph.lnK + target * Math.LN10);
      eq.th = ph.th ? { logK: f * (ph.th.logK + target), dH: f * ph.th.dH, a: Float64Array.from(ph.th.a, (x) => f * x) } : null;
      atFixedTemperature([eq]);
      const moves = new Map(written);
      for (const [k, c] of eq.net) moves.set(k, (moves.get(k) || 0) - c);
      eq.moves = [...moves].filter(([, c]) => Math.abs(c) > 1e-12);
    }
    act = exchangeSetup(species, equilibria, act, settings, warnings);
    const ex = act ? act.ex : null;
    act = surfaceSetup(species, equilibria, act);
    const sf = act ? act.sf : null;
    /*
      A mineral that carries a surface's sites: held at saturation, it changes
      by its relation alone, which carries them (a rate law of its own would
      leave them behind); made and used at a rate, each reaction that changes
      it takes or gives its sites with it, so many per mole, as the bare site,
      and the relations on the surface share out what is left.
    */
    if (sf) {
      for (const t of sf.types) {
        if (!t.per) continue;
        const mn = species[t.per.mineral].name;
        if (t.per.eq) {
          const rx = reactions.find((x) => [...x.reactants, ...x.products].some(([, nm]) => nm === mn));
          if (rx) {
            throw new RtmError(`"${rx.text}" changes ${mn}, which carries the sites of ${species[t.sitesFrom].name} and is `
              + 'held at saturation by its relation: it changes by that alone. A mineral whose sites go with it at a rate '
              + 'has no relation.', rx.line);
          }
          continue;
        }
        const perSite = t.per.ratio / sf.n[t.sitesFrom];
        for (const ch of channels) {
          const own = ch.net.find(([p]) => p === t.per.mineral);
          if (!own) continue;
          if (ch.net.some(([p]) => sf.typeOf[p] === sf.typeOf[t.sitesFrom])) {
            throw new RtmError(`A reaction changes ${mn}, which carries the sites of ${species[t.sitesFrom].name}, and the `
              + 'species on them as well: the sites go with it by themselves.', ch.line);
          }
          ch.net.push([t.sitesFrom, own[1] * perSite]);
        }
      }
    }
    // An exchanger's sites the same way, in the form of the species on it given sites= per= (exchangeSetup).
    if (ex && ex.perAny) {
      ex.per.forEach((p, x) => {
        if (!p) return;
        const mn = species[p.mineral].name;
        const xn = species[ex.exchangers[x]].name;
        if (p.eq) {
          const rx = reactions.find((r) => [...r.reactants, ...r.products].some(([, nm]) => nm === mn));
          if (rx) {
            throw new RtmError(`"${rx.text}" changes ${mn}, which carries the sites of ${xn} and is held at saturation by `
              + 'its relation: it changes by that alone. A mineral whose sites go with it at a rate has no relation.', rx.line);
          }
          return;
        }
        const each = p.ratio / ex.n[p.species];
        for (const ch of channels) {
          const own = ch.net.find(([q]) => q === p.mineral);
          if (!own) continue;
          if (ch.net.some(([q]) => ex.site[q] && ex.of[q] === x)) {
            throw new RtmError(`A reaction changes ${mn}, which carries the sites of ${xn}, and what is on them as well: `
              + 'the sites go with it by themselves.', ch.line);
          }
          ch.net.push([p.species, own[1] * each]);
        }
      });
    }
    act = potentialSetup(species, equilibria, act, settings);
    const pt = act ? act.pt : null;
    act = gasSetup(species, equilibria, act, settings, warnings, sections.GAS_PAIRS);
    const solids = solidSolutionSetup(species, equilibria, sections.SOLID_SOLUTIONS, settings);
    const electron = electronSetup(species, equilibria);
    // The order the conserved totals are made in (conservationBasis): species
    // on an exchanger first, and last what is no amount, an exchanger or the
    // electron, which counts in no total. A surface's potential (3) is in
    // no total at all: it has an equation of its own.
    const rank = ex || electron >= 0 || pt
      ? Int8Array.from(species, (sp) => (sp.exchange ? 1 : sp.exchanger || sp.electron ? 2 : sp.potential ? 3 : 0)) : null;
    const apairs = [];
    for (const eq of equilibria) {
      if (eq.kf === null) continue;
      if (act) { apairs.push(eq); continue; }
      const kb = eq.kf / Math.exp(eq.lnK);
      const net = eq.net.map(([i, c]) => [i, c]);
      // A backward constant that goes with the cell's temperature is read from AQ, kf/K there.
      const kbAQ = tempCode !== null && eq.th ? registerAQ({ kind: 'kb', name: `#${eq.line}`, eq }, eq.line) : -1;
      const mk = (side, sign, k) => {
        const terms = side.map(([c, name]) => (c === 1 ? `[${name}]` : `[${name}]**${c}`));
        const src = terms.length ? `(${k}) * ${terms.join(' * ')}` : `(${k})`;
        const { masked, names } = maskSpecies(src, eq.line);
        const ast = FacsimileModel.parseExpression(masked, eq.line);
        const deps = [];
        const aq = [];
        const seen = new Set();
        for (const id of mentioned(ast)) {
          if (id === 'KB_T__') { aq.push({ id, q: kbAQ }); continue; }
          if (!names.has(id)) continue;
          if (seen.has(id)) continue;
          seen.add(id);
          deps.push({ id, si: index.get(names.get(id)) });
        }
        deps.sort((a, b) => a.si - b.si);
        return { ast, deps, aq, params: new Map(), line: eq.line, whole: false, net: net.map(([i, c]) => [i, c * sign]) };
      };
      channels.push(mk(eq.reactants, +1, numberLiteral(eq.kf)));
      channels.push(mk(eq.products, -1, kbAQ >= 0 ? 'KB_T__' : numberLiteral(kb)));
    }

    /* ---- what the rate laws read besides concentrations ---------------- */
    const phases = readPhases(sections.PHASES, index);
    atFixedTemperature(phases.values());
    // A phase's molar volume, from <VOLUMES>, for its log K at the pressure.
    if (act && act.vol) {
      for (const [name, { v, line }] of act.vol.phases) {
        if (!phases.has(name)) {
          throw new RtmError(`"${name}" in <VOLUMES> is not in <SPECIES> or <PHASES>.`, line);
        }
        phases.get(name).vm0 = v;
      }
    }
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
          ph = { name: e.name, net: eq.net.filter(([k]) => k !== eq.mineral), water: eq.water || 0, lnK: eq.lnK, eq,
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
    // the water's activity comes in -- or under SIT, where a coefficient reads
    // the species it is paired with, which may be neutral, every solute.
    const sitAQ = !!(act && (act.sit || act.pz));
    // On an exchanger whose sites go with a mineral, a species' fraction reads all that is on it (exchangeFractions).
    const exPerQ = act && act.ex && act.ex.perAny ? act.ex : null;
    const perOn = (s) => (exPerQ && exPerQ.site[s] === 1 && exPerQ.per[exPerQ.of[s]] ? exPerQ.members[exPerQ.of[s]] : []);
    for (const e of aqList) {
      const set = new Set();
      if (e.kind === 'a') {
        set.add(e.s);
        if (act) (sitAQ || act.dGw ? aqSolutes : aqIons).forEach((k) => set.add(k));
        perOn(e.s).forEach((k) => set.add(k));
      } else if (e.kind === 'aw') { if (act) aqSolutes.forEach((k) => set.add(k)); }
      else if (e.kind === 'I') aqIons.forEach((k) => set.add(k));
      else if (e.kind === 'TK' || e.kind === 'TC' || e.kind === 'kb') {
        // The cell's temperature, and a backward constant that goes with it: no species.
      } else {
        e.phase.net.forEach(([k]) => { set.add(k); perOn(k).forEach((j) => set.add(j)); });
        if (act) (sitAQ ? aqSolutes : aqIons).forEach((k) => set.add(k));
        // The water's activity: in the phase, or in its log K at the vapour pressure (volumesAt).
        if (act && (e.phase.water || act.dGw || (act.vol && !act.vol.idle))) aqSolutes.forEach((k) => set.add(k));
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
      const cell = (b / ns) | 0;
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
            // Through A and B, which go with a(H2O) (coefficientsAt).
            if (w.dGw && w.dGw[e.s]) for (const k of aqSolutes) d[k] += a * w.dGw[e.s] * awOf(aqAct, w, k);
            const r = sitAQ && aqAct.sit ? aqAct.sit.rows[e.s] : null;
            if (r) for (let u = 0; u < r.k.length; u++) d[r.k[u]] += a * Math.LN10 * (r.e[u] + w.I * r.e1[u]);
            // Under Pitzer every solute's, from the evaluation's rows (pitzerAt).
            if (sitAQ && aqAct.pz) {
              const sd = sitPartners(aqAct, [[e.s, 1]], w);
              for (const k of aqSolutes) if (sd[k]) d[k] += a * sd[k];
              sitDone(aqAct, [[e.s, 1]]);
            }
            // On an exchanger whose sites go with a mineral, its fraction of all that is on it now.
            const per = perOn(e.s);
            if (per.length) {
              const x = aqAct.ex.of[e.s];
              const sum = w.exSum ? w.exSum[x] : 0;
              if (sum > 0) for (const j of per) d[j] -= (a * aqAct.ex.n[j]) / sum;
            }
          }
        } else if (e.kind === 'aw') {
          const aw = Math.exp(w.lnAw);
          AQ[q] = aw;
          if (d) for (const k of aqSolutes) d[k] += aw * awOf(aqAct, w, k);
        } else if (e.kind === 'I') {
          AQ[q] = w.I;
          if (d && w.I > 1e-10) for (const k of aqIons) d[k] += 0.5 * z[k] * z[k];
        } else if (e.kind === 'TK') {
          AQ[q] = thermo.tk[cell];
        } else if (e.kind === 'TC') {
          AQ[q] = thermo.tc[cell];
        } else if (e.kind === 'kb') {
          AQ[q] = e.eq.kf / Math.exp(lnKIn(e.eq, cell));
        } else {
          const ph = e.phase;
          let lnIAP = ph.water ? ph.water * w.lnAw : 0;
          let G = 0;
          for (const [k, nu] of ph.net) {
            lnIAP += nu * (Math.log(Math.max(y[b + k], 1e-300)) + lnGq[k]);
            G += nu * dGq[k];
          }
          const x = ph.sign * (lnIAP - lnKAtP(ph.eq || ph, cell, w));
          const val = e.kind === 'SI' ? x / Math.LN10 : Math.exp(x);
          AQ[q] = val;
          if (d) {
            const f = ph.sign * (e.kind === 'SI' ? 1 / Math.LN10 : val);
            for (const [k, nu] of ph.net) if (y[b + k] > 0) d[k] += (f * nu) / y[b + k];
            // The volumes, for the log K at the pressure, go with I and the water too.
            G += pressureTermI(ph.eq || ph, w);
            if (G) for (const k of aqIons) d[k] += f * G * 0.5 * z[k] * z[k];
            const wd = waterCoef(ph.eq || ph, w);
            if (wd) for (const k of aqSolutes) d[k] += f * wd * awOf(aqAct, w, k);
            const sd = sitAQ || exPerQ ? sitPartners(aqAct, ph.net, w) : null;
            if (sd) {
              for (const k of aqSolutes) if (sd[k]) d[k] += f * sd[k];
              // ...and on an exchanger whose sites go with a mineral, what is on it (no solute).
              if (exPerQ) for (const k of e.cols) if (exPerQ.site[k] === 1 && sd[k]) d[k] += f * sd[k];
              sitDone(aqAct, ph.net);
            }
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
        // The cell's temperature reads no species: nothing to carry, and a power may have it in its exponent.
        const kind = aqList[aqd.q].kind;
        if (kind === 'TK' || kind === 'TC') {
          derivBody.push(`  D[${nd}] = 0;`);
          ch.aqD.push(nd);
          nd++;
          continue;
        }
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
    const ncCol = ncol * stride;    // every cell of the column, matrix layers and extra cells included
    const nc = ncCol + resSides.length;   // and the reservoirs after them: see THE RESERVOIRS
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
      // A line naming an end is the reservoir there, and there must be one.
      if (p.reservoir) {
        if (resCell[p.reservoir] < 0) {
          throw new RtmError(`"${p.reservoir}" in <INITIAL> is the reservoir at the ${p.reservoir} end, and that end is `
            + `${transport ? `${settings[p.reservoir.toUpperCase()]}: ${p.reservoir.toUpperCase()} = reservoir makes it one`
              : 'no end at all in a batch run'}.`, p.line);
        }
        out.push(resCell[p.reservoir]);
        return out;
      }
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
    // Held somewhere but not everywhere, by species: what the panel reports,
    // which is of the column's cells.
    const held = [];
    for (let s = 0; s < ns; s++) {
      if (fixed[s]) continue;
      const cellsHeld = [];
      for (let c = 0; c < ncCol; c++) if (fixedAt[c * ns + s]) cellsHeld.push(c);
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
      // Under SIT a coefficient reads the species it is paired with, which may be neutral: every solute.
      const realGas = act && act.gas && act.gas.dln && eq.net.some(([s]) => act.gas.isGas[s]) ? act.gas.list : [];
      const colsOf = [...new Set([...reac.map(([k]) => k), ...prod.map(([k]) => k), ...(act && (act.sit || act.pz) ? solutes : ions),
        ...(eq.water || act.dGw || (act.vol && !act.vol.idle) ? solutes : []), ...realGas])].sort((x, y) => x - y);
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
        // A reservoir has its chemistry and nothing else: what it gives the
        // cell beside it is in that cell's row, below.
        if (g.reservoir) continue;
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
    // A reservoir end: the cell beside it reads the reservoir, as diffusion and the flow across the face do.
    for (const side of resSides) {
      const i = side === 'left' ? 0 : last;
      for (let s = 0; s < ns; s++) if (mobile[s]) touch(cellOf(i, 0) * ns + s, resCell[side] * ns + s);
    }
    /*
      The faces Nernst-Planck and an activity gradient act across (npFaces):
      between column cells, and at a Dirichlet end between the water held
      there and the cell beside it. A is the side to the left, B the one to
      the right; at an end its side is -1, its concentrations held in bA or
      bB, and `cell` is the cell beside it, whose temperature the water held
      there has. At a reservoir end the water is the reservoir's, read from
      the state where it is, and its side is closed (closedA, closedB): the
      flux reaches the cell beside it and leaves the reservoir as it was.
    */
    const diffFaces = [];
    if (npIons.length || agSpecies.length) {
      const heldAt = (side) => Float64Array.from(species, (sp) => (sp[side] == null ? sp.initial : sp[side]));
      if (settings.LEFT === 'dirichlet') {
        diffFaces.push({ A: -1, B: cellOf(0, 0) * ns, iA: -1, iB: 0, cell: cellOf(0, 0), d: col.centres[0], wA: 0,
          wB: col.width[0], closedA: false, closedB: false, bA: heldAt('left'), bB: null, res: false });
      } else if (resCell.left >= 0) {
        diffFaces.push({ A: resCell.left * ns, B: cellOf(0, 0) * ns, iA: -1, iB: 0, cell: resCell.left, d: col.centres[0],
          wA: 0, wB: col.width[0], closedA: true, closedB: false, bA: null, bB: null, res: true });
      }
      for (let i = 0; i < last; i++) {
        diffFaces.push({ A: cellOf(i, 0) * ns, B: cellOf(i + 1, 0) * ns, iA: i, iB: i + 1, cell: -1,
          d: col.centres[i + 1] - col.centres[i], wA: col.width[i], wB: col.width[i + 1], closedA: false,
          closedB: semi && i + 1 === last, bA: null, bB: null, res: false });
      }
      if (settings.RIGHT === 'dirichlet') {
        diffFaces.push({ A: cellOf(last, 0) * ns, B: -1, iA: last, iB: -1, cell: cellOf(last, 0), d: grid.L - col.centres[nf - 1],
          wA: col.width[last], wB: 0, closedA: false, closedB: false, bA: null, bB: heldAt('right'), res: false });
      } else if (resCell.right >= 0) {
        diffFaces.push({ A: cellOf(last, 0) * ns, B: resCell.right * ns, iA: last, iB: -1, cell: resCell.right,
          d: grid.L - col.centres[nf - 1], wA: col.width[last], wB: 0, closedA: false, closedB: true, bA: null, bB: null,
          res: true });
      }
    }
    // Nernst-Planck: every coupled ion on either side of a face reads every
    // other on either side; at a Dirichlet end, those in the cell beside it.
    for (const f of diffFaces) {
      for (const { s: k } of npIons) {
        for (const { s: mm } of npIons) {
          if (f.A >= 0 && !f.closedA) { touch(f.A + k, f.A + mm); if (f.B >= 0) touch(f.A + k, f.B + mm); }
          if (f.B >= 0 && !f.closedB) { touch(f.B + k, f.B + mm); if (f.A >= 0) touch(f.B + k, f.A + mm); }
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
          } else if (resCell.left >= 0) {
            // A reservoir is a dirichlet face whose water is in the state: the
            // same coefficient, on the reservoir's concentration, and nothing in
            // the reservoir's own row -- the column does not drain it.
            const d = col.centres[0] - 0;
            const g = D / (d * w);
            if (g) { flowIn.push({ row, col: row, value: -g }); flowIn.push({ row, col: resCell.left * ns + s, value: g }); }
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
          } else if (resCell.right >= 0) {
            const d = grid.L - col.centres[nf - 1];
            const g = D / (d * w);
            if (g) { flowIn.push({ row, col: row, value: -g }); flowIn.push({ row, col: resCell.right * ns + s, value: g }); }
          }
          // --- advection, upwind ---
          if (v !== 0) {
            const a = u / w;
            if (v > 0) {
              if (i > 0) flowIn.push({ row, col: cellOf(i - 1, 0) * ns + s, value: a });
              // The flow carries the reservoir's water in, as it carries a dirichlet face's.
              else if (resCell.left >= 0) flowIn.push({ row, col: resCell.left * ns + s, value: a });
              else if (settings.LEFT === 'dirichlet' || settings.LEFT === 'robin') {
                const cb = species[s].left == null ? species[s].initial : species[s].left;
                boundary.push({ row, value: a * cb });
              }
              flowIn.push({ row, col: row, value: -a });
            } else {
              if (i < last) flowIn.push({ row, col: cellOf(i + 1, 0) * ns + s, value: -a });
              else if (resCell.right >= 0) flowIn.push({ row, col: resCell.right * ns + s, value: -a });
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
        // A reservoir's water is a state, so what crosses beside it is a term on that state, not a constant.
        const resL = resCell.left >= 0 ? resCell.left * ns + s : -1;
        const resR = resCell.right >= 0 ? resCell.right * ns + s : -1;
        // The left face, x = 0.
        if (v > 0) {
          if (resL >= 0) left.terms.push([resL, u]);
          else if (settings.LEFT === 'dirichlet' || settings.LEFT === 'robin') left.constant += u * cbLeft;
        } else if (v < 0) left.terms.push([at(0, s), u]);
        if (settings.LEFT === 'dirichlet') {
          const g = dispersionAt(s, 0) / col.centres[0];
          if (g) { left.terms.push([at(0, s), -g]); left.constant += g * cbLeft; }
        } else if (resL >= 0) {
          const g = dispersionAt(s, 0) / col.centres[0];
          if (g) left.terms.push([at(0, s), -g], [resL, g]);
        }
        // The right face, x = LENGTH.
        if (v > 0) right.terms.push([at(N, s), u]);
        else if (v < 0 && resR >= 0) right.terms.push([resR, u]);
        else if (v < 0 && (settings.RIGHT === 'dirichlet' || settings.RIGHT === 'robin')) right.constant += u * cbRight;
        if (settings.RIGHT === 'dirichlet') {
          const g = dispersionAt(s, N) / (grid.L - col.centres[N]);
          if (g) { right.terms.push([at(N, s), g]); right.constant -= g * cbRight; }
        } else if (resR >= 0) {
          const g = dispersionAt(s, N) / (grid.L - col.centres[N]);
          if (g) right.terms.push([at(N, s), g], [resR, -g]);
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
      D is the same it is nothing in a neutral water. Between column cells,
      and at a Dirichlet end between the water held there and the cell beside
      it, half a cell away; the rock matrix stays each species on its own.

      DIFFUSION_GRADIENT = activity: each g is the difference in
      concentration times f = 1 + (ln gamma_B - ln gamma_A)/(ln C_B - ln C_A),
      the cells' own activity coefficients, as PHREEQC's multicomponent
      diffusion has it (find_J): C_B - C_A + L (ln gamma_B - ln gamma_A), L
      the logarithmic mean of the two concentrations, and nothing more where
      either side has none. PHREEQC uses f only between 0.2 and 2.25 and
      drops it to 1 beyond, where a species is nearly level and its gamma is
      not; there the flux jumps -- up, below 0.2, as the difference falls --
      which PHREEQC's explicit steps step over and an implicit solver cannot
      (HCl against NaCl, the ends held at pure water, stalled at 54 hours two
      million steps in). Here f is held at 0.2 or 2.25 beyond them: the flux
      goes on without a jump, never up a species' own gradient, and a level
      species stays level, as in PHREEQC; it gets there at 0.2 or 2.25 of
      its D where PHREEQC takes 1. What f adds to a species' own diffusion,
      -D_k (f - 1) dC/d, is added here; the coupling takes the gradients with
      it. The Jacobian has f's derivatives in the two concentrations and
      holds the ln gamma where they are: what they do in the Newton iteration
      is small, and they move with every species through the ionic strength.
    */
    const npFaces = diffFaces.map((f) => {
      const ni = npIons.length;
      const slots = new Int32Array(4 * ni * ni).fill(-1);
      const aslots = new Int32Array(4 * agSpecies.length).fill(-1);
      const onA = (k) => f.A >= 0 && !f.closedA && !fixedAt[f.A + k];
      const onB = (k) => f.B >= 0 && !f.closedB && !fixedAt[f.B + k];
      npIons.forEach(({ s: k }, a) => {
        npIons.forEach(({ s: mm }, c) => {
          const o = 4 * (a * ni + c);
          if (onA(k)) { slots[o] = slot(f.A + k, f.A + mm); if (f.B >= 0) slots[o + 1] = slot(f.A + k, f.B + mm); }
          if (onB(k)) { if (f.A >= 0) slots[o + 2] = slot(f.B + k, f.A + mm); slots[o + 3] = slot(f.B + k, f.B + mm); }
        });
      });
      agSpecies.forEach((k, a) => {
        const o = 4 * a;
        if (onA(k)) { aslots[o] = slot(f.A + k, f.A + k); if (f.B >= 0) aslots[o + 1] = slot(f.A + k, f.B + k); }
        if (onB(k)) { if (f.A >= 0) aslots[o + 2] = slot(f.B + k, f.A + k); aslots[o + 3] = slot(f.B + k, f.B + k); }
      });
      return { ...f, slots, aslots };
    });
    // Each column cell's ln gamma, and each end's water's, read afresh with every call.
    const lnGcol = actGrad ? new Float64Array(ncol * ns) : null;
    const lnGend = actGrad ? npFaces.map((f) => (f.bA || f.bB || f.res ? new Float64Array(ns) : null)) : null;
    const gScratch = actGrad ? new Float64Array(ns) : null;
    const dScratch = actGrad ? new Float64Array(ns) : null;
    /*
      A species one side has none of has no activity gradient across the face
      in PHREEQC; the waters the page is given carry a trace of what they
      lack (From PHREEQC writes 1e-12 of it), so what f adds fades out as one
      side falls from a millionth of the other to 1e-10 of it, and is gone
      below: ln of the ratio from 13.8 to 23.0.
    */
    const TRACE_FADE = Math.log(1e6);
    const TRACE_GONE = Math.log(1e10);
    // Across the face in hand, what the activity adds to each species' difference, and its derivatives in C_A and C_B.
    const actD = new Float64Array(ns);
    const actDA = new Float64Array(ns);
    const actDB = new Float64Array(ns);
    /**
     * (f - 1)(cb - ca) into actD[k], f = 1 + (gb - ga)/ln(cb/ca) held between
     * 0.2 and 2.25 -- L (gb - ga) between them, L the logarithmic mean -- and
     * nothing where either side has none; its derivatives in ca and cb, the
     * ln gamma held, into actDA[k] and actDB[k].
     */
    const activityPart = (k, ca, cb, ga, gb) => {
      const dg = gb - ga;
      actD[k] = 0;
      actDA[k] = 0;
      actDB[k] = 0;
      if (!(ca > 0) || !(cb > 0) || dg === 0) return;
      const x = cb / ca - 1;
      const u = Math.log1p(x);
      const au = Math.abs(u);
      if (au >= TRACE_GONE) return;
      const fr = u === 0 ? (dg > 0 ? Infinity : -Infinity) : 1 + dg / u;
      if (!(fr > 0.2 && fr < 2.25)) {
        const e = (fr >= 2.25 ? 2.25 : 0.2) - 1;
        actD[k] = e * (cb - ca);
        actDA[k] = -e;
        actDB[k] = e;
      } else if (Math.abs(x) < 1e-4) {
        // cb = ca (1 + x): L = ca (1 + x/2 - x^2/12 + ...), dL/dca = 1/2 + x/6 + ..., dL/dcb = 1/2 - x/6 + ...
        actD[k] = ca * (1 + x / 2 - (x * x) / 12) * dg;
        actDA[k] = (0.5 + x / 6) * dg;
        actDB[k] = (0.5 - x / 6) * dg;
      } else {
        const L = (cb - ca) / u;
        actD[k] = L * dg;
        actDA[k] = ((L / ca - 1) / u) * dg;
        actDB[k] = ((1 - L / cb) / u) * dg;
      }
      if (au > TRACE_FADE) {
        // Fading out as one side falls from a millionth of the other to 1e-10, smoothly: w = t^2 (3 - 2t).
        const t = (TRACE_GONE - au) / (TRACE_GONE - TRACE_FADE);
        const w = t * t * (3 - 2 * t);
        const dw = ((-6 * t * (1 - t)) / (TRACE_GONE - TRACE_FADE)) * Math.sign(u);
        actDA[k] = w * actDA[k] - (actD[k] * dw) / ca;
        actDB[k] = w * actDB[k] + (actD[k] * dw) / cb;
        actD[k] *= w;
      }
    };
    /** The coupling's fluxes and the activity gradient's into out, or their derivatives into V. */
    const npFlux = (y, out, V) => {
      const ni = npIons.length;
      if (actGrad) {
        for (let i = 0; i < ncol; i++) {
          const c = cellOf(i, 0);
          activityAt(act, y, c * ns, gScratch, dScratch, c);
          lnGcol.set(gScratch, i * ns);
        }
        npFaces.forEach((f, q) => {
          if (!lnGend[q]) return;
          // A reservoir's water is in the state, where it is now; a dirichlet end's is held.
          if (f.res) activityAt(act, y, f.closedA ? f.A : f.B, lnGend[q], dScratch, f.cell);
          else activityAt(act, f.bA || f.bB, 0, lnGend[q], dScratch, f.cell);
        });
      }
      for (let q = 0; q < npFaces.length; q++) {
        const f = npFaces[q];
        // Each side's concentrations, and its ln gamma, as an array and where in it the face's cell starts.
        const cA = f.bA || y;
        const oA = f.bA ? 0 : f.A;
        const cB = f.bB || y;
        const oB = f.bB ? 0 : f.B;
        if (actGrad) {
          const endA = f.bA || (f.res && f.closedA);
          const endB = f.bB || (f.res && f.closedB);
          const gA = endA ? lnGend[q] : lnGcol;
          const ogA = endA ? 0 : f.iA * ns;
          const gB = endB ? lnGend[q] : lnGcol;
          const ogB = endB ? 0 : f.iB * ns;
          for (const k of agSpecies) activityPart(k, cA[oA + k], cB[oB + k], gA[ogA + k], gB[ogB + k]);
        }
        let N = 0;
        let Den = 0;
        for (const { s: k, z, D } of npIons) {
          N += (z * D * (cB[oB + k] - cA[oA + k] + actD[k])) / f.d;
          Den += z * z * D * 0.5 * (cA[oA + k] + cB[oB + k]);
        }
        const coupled = ni > 0 && Den > 0;
        const pull = coupled ? N / Den : 0;
        if (out) {
          if (coupled) {
            for (const { s: k, z, D } of npIons) {
              const J = D * z * 0.5 * (cA[oA + k] + cB[oB + k]) * pull;
              if (f.A >= 0 && !f.closedA && !fixedAt[f.A + k]) out[f.A + k] -= J / f.wA;
              if (f.B >= 0 && !f.closedB && !fixedAt[f.B + k]) out[f.B + k] += J / f.wB;
            }
          }
          for (const k of agSpecies) {
            if (actD[k] === 0) continue;
            const J = (-species[k].D * actD[k]) / f.d;
            if (f.A >= 0 && !f.closedA && !fixedAt[f.A + k]) out[f.A + k] -= J / f.wA;
            if (f.B >= 0 && !f.closedB && !fixedAt[f.B + k]) out[f.B + k] += J / f.wB;
          }
          continue;
        }
        // dJ_k/dC_m on each side: D_k z_k (delta_km pull/2 + Cbar_k (dN Den - N dDen)/Den^2).
        if (coupled) {
          npIons.forEach(({ s: k, z, D }, a) => {
            const Ck = 0.5 * (cA[oA + k] + cB[oB + k]);
            npIons.forEach(({ s: mm, z: zm, D: Dm }, c) => {
              const dDen = zm * zm * Dm * 0.5;
              const dNA = (zm * Dm * (actDA[mm] - 1)) / f.d;
              const dNB = (zm * Dm * (1 + actDB[mm])) / f.d;
              const self = a === c ? 0.5 * pull : 0;
              const dA = D * z * (self + Ck * (dNA * Den - N * dDen) / (Den * Den));
              const dB = D * z * (self + Ck * (dNB * Den - N * dDen) / (Den * Den));
              const o = 4 * (a * ni + c);
              if (f.slots[o] >= 0) V[f.slots[o]] -= dA / f.wA;
              if (f.slots[o + 1] >= 0) V[f.slots[o + 1]] -= dB / f.wA;
              if (f.slots[o + 2] >= 0) V[f.slots[o + 2]] += dA / f.wB;
              if (f.slots[o + 3] >= 0) V[f.slots[o + 3]] += dB / f.wB;
            });
          });
        }
        // The activity's part, the ln gamma held: dJ/dC_A = -D dL/dC_A dlnG/d, dJ/dC_B = -D dL/dC_B dlnG/d.
        agSpecies.forEach((k, a) => {
          if (actD[k] === 0) return;
          const dA = (-species[k].D * actDA[k]) / f.d;
          const dB = (-species[k].D * actDB[k]) / f.d;
          const o = 4 * a;
          if (f.aslots[o] >= 0) V[f.aslots[o]] -= dA / f.wA;
          if (f.aslots[o + 1] >= 0) V[f.aslots[o + 1]] -= dB / f.wA;
          if (f.aslots[o + 2] >= 0) V[f.aslots[o + 2]] += dA / f.wB;
          if (f.aslots[o + 3] >= 0) V[f.aslots[o + 3]] += dB / f.wB;
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

    /*
      THE TEMPERATURE CELL BY CELL (see the temperature above): thermo.tc and
      thermo.tk, each cell's in C and in kelvin, and where TEMPERATURE is an
      expression, from them in each cell what reads it: each relation's and
      phase's ln K that goes with temperature (lnKc), which a fast pair's
      backward constant follows, the Debye-Hueckel A and B (Ac, Bc), a gas's
      ln(R T/V) in a fixed volume, and a double layer's sqrt(8000 R T eps
      eps0) and F/RT; Peng and Robinson's terms are worked out from tk where
      they are read (onSites). All of it at the start, and where TEMPERATURE
      reads the clock, again at each time the model is evaluated at.
    */
    thermo.tc = new Float64Array(nc).fill(tcFixed === null ? 25 : tcFixed);
    thermo.tk = Float64Array.from(thermo.tc, (v) => v + 273.15);
    // A binary solid solution's a0, a1 and miscibility gap are its cell's temperature's (binaryAt), its gap to
    // round-off where that goes with time.
    for (const d of solids) { d.tk = thermo.tk; d.smooth = !!tempClock; d.cache.clear(); }
    const relT = equilibria.filter((eq) => eq.th);
    const phT = [...phases.values()].filter((ph) => ph.th);
    const gasT = act && act.gas && (act.gas.fixed === 'volume' || act.gas.pr) ? act.gas : null;
    const readsT = (act && act.kind !== 'none') || !!pt || !!gasT || relT.length > 0 || phT.length > 0
      || aqList.some((e) => e.kind === 'TK' || e.kind === 'TC') || solids.some((d) => d.coef === 'binary');
    if (tcFixed !== null && readsT && !(tcFixed >= 0 && tcFixed <= 350)) {
      throw new RtmError(`TEMPERATURE = ${tcFixed}: the water and its relations are worked out for 0 to 350 C.`,
        settings.TEMPERATURE_line);
    }
    if (!readsT && settings.given && settings.given.has('TEMPERATURE')) {
      warnings.push('TEMPERATURE sets the relations\' log K given a dH or an analytic expression, the activity model\'s '
        + 'A and B, a gas\'s R T and a double layer\'s, and a rate law reads it as TK and TC: nothing here does.');
    }
    const tempAt = tempCode === null ? null
      // eslint-disable-next-line no-new-func
      : new Function('P', 'pb', 't', 'TV', `return ${tempCode};`);
    const atmT = act || pt ? waterPressure(settings, species) : 1;
    if (thermo.varies) {
      for (const r of relT) r.lnKc = new Float64Array(nc);
      for (const r of phT) r.lnKc = new Float64Array(nc);
      if (act && act.kind !== 'none') { act.Ac = new Float64Array(nc); act.Bc = new Float64Array(nc); act.wtc = new Array(nc); }
      if (act && act.llnl) act.bdotc = new Float64Array(nc);
      if (act) act.tk = thermo.tk;
      // Pitzer's parameters and A_phi at each cell's temperature (pitzerValues).
      if (act && act.pz) { act.pz.valc = new Float64Array(nc * act.pz.np); act.pz.A0c = new Float64Array(nc); act.pz.tkc = thermo.tk; }
      if (pt) { pt.kSc = new Float64Array(nc); pt.fRTc = new Float64Array(nc); }
      if (gasT && gasT.fixed === 'volume') gasT.lnGc = new Float64Array(nc);
    }
    const cellName = (c) => (nc === 1 ? '' : whereIs(c));
    /** Each cell's temperature at time t, and what reads it there; nothing where it is a number. */
    function thermoAt(t) {
      if (!thermo.varies || (thermo.clock ? t === thermo.t : thermo.ready)) return;
      if (ntv) atTheClock(t);
      const { tc, tk } = thermo;
      if (tempCells) for (let c = 0; c < nc; c++) tc[c] = tempAt(P, c * np, t, TV);
      else tc.fill(tempAt(P, 0, t, TV));
      for (let c = 0; c < nc; c++) {
        if (!(tc[c] >= 0 && tc[c] <= 350)) {
          throw new RtmError(`TEMPERATURE comes to ${tc[c]} C${cellName(c)}${thermo.clock ? ` at t = ${t}` : ''}: the water `
            + 'and its relations are worked out for 0 to 350 C.', settings.TEMPERATURE_line);
        }
        tk[c] = tc[c] + 273.15;
      }
      // Cell by cell; once, and then copied, where every cell has the same.
      const n1 = tempCells ? nc : 1;
      for (let c = 0; c < n1; c++) {
        for (const r of relT) r.lnKc[c] = logKAt(r.th, tk[c]) * Math.LN10;
        for (const r of phT) r.lnKc[c] = logKAt(r.th, tk[c]) * Math.LN10;
        if ((act && act.Ac) || pt) {
          const wt = waterAtT(tc[c], atmT);
          const ab = waterAt(wt, 1);
          if (act && act.Ac && act.llnl) {
            // LLNL's tables, and no water: its A, B and B-dot at the cell's temperature.
            const ll = llnlAt(act.llnl, tc[c], `${cellName(c)}${thermo.clock ? ` at t = ${t}` : ''}`);
            act.Ac[c] = ll.A;
            act.Bc[c] = ll.B;
            act.bdotc[c] = ll.bdot;
            act.wtc[c] = null;
          } else if (act && act.Ac) { act.Ac[c] = ab.A; act.Bc[c] = ab.B; act.wtc[c] = wt; }
          if (act && act.pz) {
            const pz = act.pz;
            pz.A0c[c] = pitzerValues(pz, tc[c], atmT, pz.valc.subarray(c * pz.np, (c + 1) * pz.np));
          }
          if (pt) {
            pt.kSc[c] = Math.sqrt(8000 * GAS_R * tk[c] * ab.eps * EPSILON0);
            pt.fRTc[c] = FARADAY / (GAS_R * tk[c]);
          }
        }
        if (gasT && gasT.lnGc) gasT.lnGc[c] = Math.log((R_LITER_ATM * tk[c]) / gasT.volume);
      }
      if (n1 < nc) {
        for (const r of relT) r.lnKc.fill(r.lnKc[0]);
        for (const r of phT) r.lnKc.fill(r.lnKc[0]);
        if (act && act.Ac) { act.Ac.fill(act.Ac[0]); act.Bc.fill(act.Bc[0]); act.wtc.fill(act.wtc[0]); }
        if (act && act.bdotc) act.bdotc.fill(act.bdotc[0]);
        if (act && act.pz) {
          const pz = act.pz;
          pz.A0c.fill(pz.A0c[0]);
          for (let c = 1; c < nc; c++) pz.valc.copyWithin(c * pz.np, 0, pz.np);
        }
        if (pt) { pt.kSc.fill(pt.kSc[0]); pt.fRTc.fill(pt.fRTc[0]); }
        if (gasT && gasT.lnGc) gasT.lnGc.fill(gasT.lnGc[0]);
      }
      thermo.t = t;
      thermo.ready = true;
      thermoStamp++;
    }
    thermoAt(0);

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
    const pairRate = (pr, y, b, water, cell) => {
      let fwd = pr.kf;
      for (const [k, e] of pr.reac) fwd *= e === 1 ? y[b + k] : y[b + k] ** e;
      // The volumes' correction for the pressure, off ln K, is on the backward constant.
      let lnGamma = pr.water * water.lnAw + pressureTerm(pr.eq, water);
      for (const [k, c] of pr.net) lnGamma += c * lnG[k];
      pr.kg = (pr.eq.lnKc ? pr.kf / Math.exp(pr.eq.lnKc[cell]) : pr.kb) * Math.exp(lnGamma);
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
      if (thermo.clock) thermoAt(t);
      if (ntv) atTheClock(t);
      if (pairInfo.length) {
        for (let i = 0; i < nc; i++) {
          const b = i * ns;
          const water = activityAt(act, y, b, lnG, dG);
          const sc = reactScale[i];
          for (const pr of pairInfo) {
            const r = pairRate(pr, y, b, water, i) * sc;
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
      if (thermo.clock) thermoAt(t);
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
            pairRate(pr, y, b, water, i);
            const d = pr.d;
            d.fill(0);
            // The mass action of each side...
            for (const [k] of pr.reac) d[pr.at.get(k)] += pr.kf * sideDerivative(pr.reac, y, b, k);
            for (const [k] of pr.prod) d[pr.at.get(k)] -= pr.kg * sideDerivative(pr.prod, y, b, k);
            // ...and Gamma through the ionic strength and the water, and under SIT the partners.
            let G = pressureTermI(pr.eq, water);
            for (const [k, c] of pr.net) G += c * dG[k];
            if (pr.back !== 0) {
              const sd = sitPartners(act, pr.net, water);
              const wd = waterCoef(pr.eq, water);
              pr.cols.forEach((k, q) => {
                let g = G * 0.5 * act.z[k] * act.z[k];
                if (wd) g += wd * awOf(act, water, k);
                if (sd) g += sd[k];
                if (g) d[q] -= pr.back * g;
              });
              if (sd) sitDone(act, pr.net);
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
    // A reservoir starts where a dirichlet face is held, at left= or right= where
    // a species gives one; an <INITIAL> line naming it comes after, and wins.
    for (const side of resSides) {
      const b = resCell[side] * ns;
      for (let s = 0; s < ns; s++) if (species[s][side] != null) initial[b + s] = species[s][side];
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
            throw new RtmError(`"${patch.src}" is not a number${whereIs(c)}.`, patch.line);
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
    // The reservoirs count here too: what is held in one and nowhere else is held in some cells only.
    const heldSomewhere = [];
    for (let s = 0; s < ns; s++) {
      if (fixed[s]) continue;
      for (let c = 0; c < nc; c++) if (fixedAt[c * ns + s]) { heldSomewhere.push({ species: nameOf[s], si: s }); break; }
    }
    if (settings.EQUILIBRATE && heldSomewhere.length) {
      const inEq = new Set(equilibriumSpecies(equilibria));
      const bad = heldSomewhere.filter((h) => inEq.has(h.si));
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
      const where = (c) => (nc === 1 ? '' : whereIs(c));
      for (let c = 0; c < nc; c++) {
        const b = c * ns;
        ex.exchangers.forEach((k, x) => {
          const cap = initial[b + k];
          let on = 0;
          for (const j of ex.list) if (ex.of[j] === x) on += ex.n[j] * initial[b + j];
          /*
            Sites that go with a mineral: so many to each mole of it in the
            cell at the start, which the species on it are given amounts
            to make, or which the water loads (after its own speciation,
            below).
          */
          const p = ex.per[x];
          if (p) {
            const what = `${fmtSites(p.ratio)} per ${nameOf[p.mineral]} as ${nameOf[p.species]}`;
            if (cap > 0) {
              throw new RtmError(`${nameOf[k]} is given a capacity${where(c)}, and its sites go with ${nameOf[p.mineral]}, `
                + `${what}: the mineral gives the capacity, and the exchanger's line none.`, species[k].line);
            }
            const given = p.ratio * initial[b + p.mineral];
            if (!(given > 0)) {
              throw new RtmError(`The sites of ${nameOf[k]} go with ${nameOf[p.mineral]}, and there is none of it${where(c)} `
                + 'to start with: give the mineral an amount in every cell the exchanger\'s relations are to hold in.',
              species[p.species].line);
            }
            if (on > 0 && Math.abs(on - given) > 1e-6 * given) {
              throw new RtmError(`The species on ${nameOf[k]} take ${fmtSites(on)} sites${where(c)}, and ${what} make `
                + `${fmtSites(given)}: give amounts that make them, or none, and the water loads them.`, species[p.species].line);
            }
            const total = on > 0 ? on : given;
            ex.capacity[c * nx + x] = total;
            for (const j of ex.members[x]) ex.shift[b + j] = Math.log(ex.n[j] / total);
            if (!(on > 0)) ex.load.push(c * nx + x);
            return;
          }
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
    /*
      THE SURFACES' SITES, cell by cell, type by type: what its species take
      there, or what one of them is given -- sites= -- which the cell's water
      loads at the start, as PHREEQC's SURFACE with -equilibrate does (see
      loadSurfaces). A species on a surface has for its activity n/sites
      times its amount.
    */
    if (sf) {
      const nt = sf.types.length;
      sf.shift = new Float64Array(nc * ns);
      sf.sites = new Float64Array(nc * nt);
      sf.load = [];
      const where = (c) => (nc === 1 ? '' : whereIs(c));
      for (let c = 0; c < nc; c++) {
        const b = c * ns;
        sf.types.forEach((t, ti) => {
          // Per mole of a mineral: the mineral's amount in the cell at the start times them.
          const given = t.sitesFrom < 0 ? 0 : t.per ? t.per.ratio * initial[b + t.per.mineral] : species[t.sitesFrom].sites;
          if (t.per && !(given > 0)) {
            throw new RtmError(`The sites of ${nameOf[t.sitesFrom]} go with ${nameOf[t.per.mineral]}, and there is none of it${where(c)} `
              + 'to start with: give the mineral an amount in every cell the surface\'s relations are to hold in.',
            species[t.sitesFrom].line);
          }
          let held = 0;
          for (const k of t.members) held += sf.n[k] * initial[b + k];
          // Sites per mole of a mineral and amounts on them as well: the amounts, if they make that many.
          if (t.per && held > 0) {
            if (Math.abs(held - given) > 1e-6 * given) {
              throw new RtmError(`The species on the surface of ${nameOf[t.sitesFrom]} take ${fmtSites(held)} sites${where(c)}, and `
                + `${fmtSites(t.per.ratio)} per ${nameOf[t.per.mineral]} make ${fmtSites(given)}: give amounts that make them, `
                + 'or none, and the water loads them.', species[t.sitesFrom].line);
            }
            sf.sites[c * nt + ti] = held;
            for (const k of t.members) sf.shift[b + k] = Math.log(sf.n[k] / held);
            return;
          }
          if (given > 0 && held > 0) {
            throw new RtmError(`${nameOf[t.sitesFrom]} is given the sites of its surface, and the species on it amounts`
              + `${where(c)} as well: give the sites, which the water there loads at the start, or what is on it, not both.`,
            species[t.sitesFrom].line);
          }
          const total = given > 0 ? given : held;
          if (!(total > 0)) {
            throw new RtmError(`The surface of ${t.members.map((k) => nameOf[k]).join(', ')} has no sites${where(c)}: give `
              + 'one of them sites=, or amounts to the species on it, in every cell its relations are to hold in.',
            species[t.members[0]].line);
          }
          sf.sites[c * nt + ti] = total;
          for (const k of t.members) sf.shift[b + k] = Math.log(sf.n[k] / total);
          if (given > 0) sf.load.push(c * nt + ti);
        });
      }
    }
    /*
      A MINERAL'S BOUNDS, cell by cell (eq.bounds): under dissolve_only never
      above what its cell starts with, and under force_equality held at
      saturation whatever its amount comes to, below none too. speciateCell
      and holdEquilibria keep them: a mineral held is at saturation between
      them, and at one of them while the water would take it past (PHREEQC's
      dissolve_only caps a phase at what it starts a calculation with).
      Under precipitate_only what the cell starts with is set aside, inert,
      as PHREEQC sets it aside: the mineral held is what precipitates beside
      it, from none, and what the page shows of it is the two together
      (model.inert, toConcentrations) -- held in the totals, the amount at
      the start left the water's own part a difference of two large numbers.
    */
    const inert = [];
    species.forEach((sp, k) => {
      if (sp.only === undefined && !sp.forced) return;
      const what = [sp.only ? `${sp.only}_only` : '', sp.forced ? 'force_equality' : ''].filter(Boolean).join(' and ');
      const eq = equilibria.find((e) => e.mineral === k);
      if (!eq) {
        throw new RtmError(`${sp.name} is given ${what}, which is a mineral's held at saturation by its relation in `
          + '<EQUILIBRIUM>, and has none.', sp.line);
      }
      if (settings.EQUILIBRATE !== 2) {
        throw new RtmError(`${sp.name} is given ${what}, which holds while its relation is held all through the run: `
          + 'EQUILIBRATE = always.', sp.line);
      }
      if (eq.grp) {
        throw new RtmError(`${sp.name} is given ${what}, and is a member of ${eq.grp.kind === 'gas' ? 'a gas phase' : 'a solid '
          + 'solution'}, which comes and goes whole.`, sp.line);
      }
      if (sp.only === 'precipitate' && sp.forced) {
        throw new RtmError(`${sp.name} is given precipitate_only and force_equality: what it starts with is set aside and `
          + 'never dissolves, and below none it would.', sp.line);
      }
      if (sp.only === 'precipitate') {
        if (eq.carry || (ex && ex.perAny && ex.per.some((p) => p && p.mineral === k))
          || (sf && sf.types.some((t) => t.per && t.per.mineral === k))) {
          throw new RtmError(`${sp.name} is given precipitate_only and carries sites (per=): they go with the whole of it, `
            + 'and what it starts with is set aside.', sp.line);
        }
        const amounts = new Float64Array(nc);
        for (let c = 0; c < nc; c++) { amounts[c] = initial[c * ns + k]; initial[c * ns + k] = 0; }
        inert.push({ k, amounts });
        return;
      }
      const lo = new Float64Array(nc);
      const hi = new Float64Array(nc);
      for (let c = 0; c < nc; c++) {
        lo[c] = sp.forced ? -Infinity : 0;
        hi[c] = sp.only === 'dissolve' ? initial[c * ns + k] : Infinity;
      }
      eq.bounds = { lo, hi };
    });
    // A rate law reads what is held of a mineral; one set aside in part is refused there.
    for (const { k } of inert) {
      const ch = channels.find((x) => x.deps && x.deps.some((d) => d.si === k));
      if (ch) {
        throw new RtmError(`A rate law reads ${species[k].name}, which is given precipitate_only: what it starts with is set `
          + 'aside, and the law would read the rest.', ch.line);
      }
    }

    /*
      QUANTITIES: what the run can be read as besides its species, each
      worked out at a stored point -- the concentrations, a cell, a time --
      with the model's own activity model: the water's pH, pe and Eh, ionic
      strength, a(H2O), charge balance and temperature; each element's
      dissolved total; the saturation index of each phase of <PHASES> and of
      each mineral; each solute's log activity; a gas's partial pressure;
      what share of an exchanger, or of its sites on a surface, each species
      on it takes; and what <OUTPUT> defines. Each is { key, label, group,
      unit, axis }: key the name <DATA> and the page know it by, axis 'conc'
      for an amount (the left-hand axis, log or not), 'index' for the rest.
    */
    const qAct = act || noActivity(species);
    const qG = new Float64Array(ns);
    const qD = new Float64Array(ns);
    let qW = null;          // the cell's water, as activityAt gives it, while a point is worked out
    const qList = [];
    const qFn = [];
    const addQ = (key, label, group, unit, axis, fn) => { qList.push({ key, label, group, unit, axis }); qFn.push(fn); };
    // A solute: what is dissolved in the water -- the activity model's, or without ACTIVITY (whose activity model marks
    // none, the water's activity being 1) every species that is no mineral, gas, electron or what is on a surface. The
    // model an exchanger or a surface makes for itself without ACTIVITY, kind none, is no ACTIVITY.
    const isSolute = (k) => (act && act.kind !== 'none' ? !!act.solute[k] : !(species[k].mineral || species[k].exchange || species[k].exchanger
      || species[k].electron || species[k].surface || species[k].potential || species[k].gas || species[k].name === 'H2O'));
    const qSolutes = [];
    for (let k = 0; k < ns; k++) if (isSolute(k) && !species[k].electron) qSolutes.push(k);
    // What each species is made of: the composition views', and the carbonate and sulfate below.
    const composition = compositionOf(species, nameOf, index, equilibria, reactions, isSolute);
    // And what each weighs, g/mol: a concentration shown in mg/kgw.
    const masses = formulaMassesOf(species, nameOf, index, equilibria, reactions);
    const qIons = qSolutes.filter((k) => qAct.z[k]);
    const tkOf = (cell) => (thermo.tk ? thermo.tk[cell] : (typeof settings.TEMPERATURE === 'number' ? settings.TEMPERATURE : 25)
      + 273.15);
    const iH = index.has('H+') && isSolute(index.get('H+')) ? index.get('H+') : -1;
    if (iH >= 0) {
      addQ('pH', 'pH', 'water', '', 'index', (c, b) => (c[b + iH] > 0 ? -(Math.log(c[b + iH]) + qG[iH]) / Math.LN10 : NaN));
    }
    if (electron >= 0) {
      addQ('pe', 'pe', 'water', '', 'index', (c, b) => (c[b + electron] > 0 ? -Math.log10(c[b + electron]) : NaN));
      // The same in volts, at the cell's temperature then.
      addQ('Eh', 'Eh', 'water', 'V', 'index', (c, b, cell) => (c[b + electron] > 0
        ? ehPerPe(tkOf(cell)) * -Math.log10(c[b + electron]) : NaN));
    }
    // The unit the totals are in: mol/kgw under ACTIVITY, else the model's CONC_UNIT, else mol/kgw as they always were.
    const qConc = act && act.kind !== 'none' ? 'mol/kgw' : settings.CONC_UNIT || 'mol/kgw';
    const qEq = qConc.replace(/^mol/, 'eq');
    if (qIons.length) addQ('I', 'ionic strength', 'water', qConc, 'conc', () => qW.I);
    if (act && act.kind !== 'none') addQ('a(H2O)', 'a(H2O)', 'water', '', 'index', () => Math.exp(qW.lnAw));
    if (qIons.length) {
      // PHREEQC's percent error: what the ions' charges come to over all of them.
      addQ('charge', 'charge balance', 'water', '%', 'index', (c, b) => {
        let s = 0;
        let a = 0;
        for (const k of qIons) { s += qAct.z[k] * c[b + k]; a += Math.abs(qAct.z[k]) * c[b + k]; }
        return a > 0 ? (100 * s) / a : 0;
      });
    }
    if (thermo.varies) addQ('T', 'temperature', 'water', '°C', 'index', (c, b, cell) => tkOf(cell) - 273.15);
    // Each element's total in the water, from the solutes' names; H and O are the water's own.
    const qElements = new Map();
    for (const k of qSolutes) {
      const made = elementsOf(nameOf[k]);
      if (!made) continue;
      for (const [el, n] of made) {
        if (el === 'H' || el === 'O' || !ELEMENT_SYMBOLS.has(el)) continue;
        if (!qElements.has(el)) qElements.set(el, []);
        qElements.get(el).push([k, n]);
      }
    }
    // Only an element in two species or more: in one, its total is that species, already in the list.
    for (const [el, terms] of [...qElements].filter(([, t]) => t.length > 1).sort(([a], [b2]) => a.localeCompare(b2))) {
      addQ(`tot(${el})`, `${el}, dissolved`, 'totals', qConc, 'conc', (c, b) => {
        let s = 0;
        for (const [k, n] of terms) s += n * c[b + k];
        return s;
      });
    }
    // The carbonate's alkalinity, HCO3- one and CO3-2 two and their complexes as many (compositionOf); and the sulfate,
    // where some of the sulfur dissolved is something else, HS-.
    const sumOf = (terms) => (c, b) => {
      let s = 0;
      for (const [k, n] of terms) s += n * c[b + k];
      return s;
    };
    if (composition.carbonate.length) {
      addQ('alk(CO3)', 'carbonate alkalinity', 'totals', qEq, 'conc', sumOf(composition.carbonate));
    }
    if (composition.sulfate.length && composition.sulfate.length < (qElements.get('S') || []).length) {
      addQ('tot(SO4)', 'sulfate, dissolved', 'totals', qConc, 'conc', sumOf(composition.sulfate));
    }
    /*
      An element's total in each of its valence states, PHREEQC's TOT("Fe(2)"),
      in a model with the electron, whose couples tie the states together as
      PHREEQC's do, where what is dissolved of it is in two states or more and
      the state of every species of it is told (compositionOf): tot(Fe(3)),
      tot(Fe(2)), the oxidised first. A mean state as itself, tot(S(2)) for
      S2O3-2. Not without the electron: a radiolysis model's radicals and
      peroxides, CO3- and C2O6-2, are no state a formula tells, carbon(5).
    */
    if (electron >= 0) for (const e of composition.elements) {
      const water = e.terms.filter((tm) => tm[2] === 'water');
      if (water.some((tm) => tm[3] === null)) continue;
      const states = [...new Set(water.map((tm) => tm[3]))].sort((a, b2) => b2 - a);
      if (states.length < 2) continue;
      for (const v of states) {
        const name = `${e.el}(${Number(v.toFixed(3))})`;
        addQ(`tot(${name})`, `${name}, dissolved`, 'totals', qConc, 'conc',
          sumOf(water.filter((tm) => tm[3] === v).map(([k, n]) => [k, n])));
      }
    }
    // A phase of <PHASES>, or a mineral and its relation, as SI() in a rate law has it.
    const phaseFor = (name) => {
      const ph = phases.get(name);
      if (ph) return ph;
      const eq = equilibria.find((x) => x.mineral >= 0 && species[x.mineral].name === name);
      return eq ? { name, net: eq.net.filter(([k]) => k !== eq.mineral), water: eq.water || 0, lnK: eq.lnK, eq,
        sign: eq.mineralNu < 0 ? 1 : -1 } : null;
    };
    const siOf = (ph, c, b, cell) => {
      let lnIAP = ph.water ? ph.water * qW.lnAw : 0;
      for (const [k, nu] of ph.net) lnIAP += nu * (Math.log(Math.max(c[b + k], 1e-300)) + qG[k]);
      return (ph.sign * (lnIAP - lnKAtP(ph.eq || ph, cell, qW))) / Math.LN10;
    };
    // A mineral held where another phase's SI is (SI() on its relation) has no SI of its own to show.
    const siNames = [...phases.keys(), ...equilibria.filter((x) => x.mineral >= 0 && !x.siOf).map((x) => species[x.mineral].name)];
    /*
      What a phase is made of, per one of it, element by element: a mineral's
      as compositionOf has it, a phase of <PHASES> from the formulas of what
      it dissolves into -- K-feldspar's K, Al and three Si from K+, Al(OH)4-
      and 3 H4SiO4 -- H and O left out, as the water's own. The Diagrams tab
      weighs a phase by it: per mole of aluminium, say.
    */
    const makeupOf = (name, ph) => {
      const out = {};
      const km = index.has(name) ? index.get(name) : -1;
      if (km >= 0 && species[km].mineral) {
        for (const e of composition.elements) for (const [k, n] of e.terms) if (k === km && n > 0) out[e.el] = n;
        return out;
      }
      for (const [k, nu] of ph.net) {
        const made = elementsOf(nameOf[k]);
        if (!made) continue;
        for (const [el, n] of made) {
          if (el !== 'H' && el !== 'O' && ELEMENT_SYMBOLS.has(el)) out[el] = (out[el] || 0) + (ph.sign * nu * n) / (ph.c0 || 1);
        }
      }
      for (const el of Object.keys(out)) {
        const v = Math.round(out[el] * 1e9) / 1e9;
        if (v > 0) out[el] = v; else delete out[el];
      }
      return out;
    };
    for (const name of [...new Set(siNames)]) {
      const ph = phaseFor(name);
      addQ(`SI(${name})`, `SI(${name})`, 'saturation', '', 'index', (c, b, cell) => siOf(ph, c, b, cell));
      qList[qList.length - 1].makeup = makeupOf(name, ph);
    }
    // Each solute's log activity -- under ACTIVITY: without it, the log of its concentration, which the species is.
    for (const k of act && act.kind !== 'none' ? qSolutes : []) {
      if (species[k].name === 'H2O') continue;
      addQ(`la(${nameOf[k]})`, `log a(${nameOf[k]})`, 'activities', '', 'index',
        (c, b) => (c[b + k] > 0 ? (Math.log(c[b + k]) + qG[k]) / Math.LN10 : NaN));
    }
    // A gas: its partial pressure, atm -- n R T/V in a fixed volume, its share of the total in a bubble.
    const qGas = act && act.gas ? act.gas : null;
    if (qGas) {
      for (const k of qGas.list) {
        addQ(`p(${nameOf[k]})`, `p(${nameOf[k]})`, 'gases', 'atm', 'conc', (c, b) => {
          if (qGas.fixed === 'volume') return c[b + k] * Math.exp(qG[k]);
          let sum = 0;
          for (const j of qGas.list) sum += c[b + j];
          return sum > 0 ? (qGas.pressure * c[b + k]) / sum : 0;
        });
      }
    }
    // On an exchanger, each species' equivalent fraction; on a surface, its share of its type's sites.
    const qEx = qAct.ex;
    if (qEx) {
      for (const j of qEx.list) {
        const members = qEx.members[qEx.of[j]];
        addQ(`share(${nameOf[j]})`, `${nameOf[j]}, share of ${nameOf[qEx.exchangers[qEx.of[j]]]}`, 'exchange', '', 'index',
          (c, b) => {
            let s = 0;
            for (const m of members) s += qEx.n[m] * c[b + m];
            return s > 0 ? (qEx.n[j] * c[b + j]) / s : 0;
          });
      }
    }
    const qSf = qAct.sf;
    if (qSf) {
      for (const j of qSf.list) {
        const members = qSf.types[qSf.typeOf[j]].members;
        addQ(`share(${nameOf[j]})`, `${nameOf[j]}, share of its sites`, 'surface', '', 'index', (c, b) => {
          let s = 0;
          for (const m of members) s += qSf.n[m] * c[b + m];
          return s > 0 ? (qSf.n[j] * c[b + j]) / s : 0;
        });
      }
    }
    /*
      <OUTPUT>: quantities of the text's own, as PHREEQC's USER_PUNCH has
      them -- a name and what it is, pH = -log10({H+}), with a unit after a
      comma if it has one: Ca_mg = [Ca+2] * 40078, unit = mg/kgw. What a
      rate law reads it may read -- [X], {X}, {H2O}, SI(phase), SR(phase), I,
      TK, TC, t, the parameters -- and x, the cell's distance along the
      column, and an <OUTPUT> above it by name.
    */
    const outputs = [];
    for (const { text: otext, line } of sections.OUTPUT) {
      const parts = splitTop(otext).map((x) => x.trim()).filter(Boolean);
      const def = /^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$/.exec(parts[0] || '');
      if (!def) {
        throw new RtmError(`"${otext}": a line of <OUTPUT> is a name and what it is, alk = [HCO3-] + 2*[CO3-2], with a unit `
          + 'after a comma if it has one: Ca_mg = [Ca+2] * 40078, unit = mg/kgw.', line);
      }
      const name = def[1];
      let unit = '';
      for (const p of parts.slice(1)) {
        const u = /^unit\s*=\s*(.+)$/i.exec(p);
        if (!u) throw new RtmError(`"${p}": after an <OUTPUT>'s expression comes its unit, unit = mg/kgw, and nothing else.`, line);
        unit = u[1].trim();
      }
      if (index.has(name) || outputs.some((o) => o.name === name) || ['t', 'x', 'I', 'TK', 'TC'].includes(name)
        || params.index.has(name) || qList.some((q) => q.key === name)) {
        throw new RtmError(`<OUTPUT> ${name}: the name is taken -- a species, a parameter, t, x, I, TK, TC, a quantity of the `
          + 'page or another output. Give it one of its own.', line);
      }
      const { masked, names, acts, sats } = maskRate(def[2], line);
      let ast;
      try {
        ast = fold(FacsimileModel.parseExpression(masked, line), null);
      } catch (e) {
        throw new RtmError(`In <OUTPUT> ${name} = ${def[2]}: ${e.message.replace(/^Line \d+: /, '')}`, line);
      }
      const look = new Map();
      for (const id of mentioned(ast)) {
        if (names.has(id) || acts.has(id)) {
          const nm = names.has(id) ? names.get(id) : acts.get(id);
          if (acts.has(id) && nm === 'H2O' && !index.has('H2O')) { look.set(id, () => Math.exp(qW.lnAw)); continue; }
          if (!index.has(nm)) throw new RtmError(`<OUTPUT> ${name}: ${names.has(id) ? `[${nm}]` : `{${nm}}`} is no species.`, line);
          const k = index.get(nm);
          look.set(id, names.has(id) ? (c, b) => c[b + k] : (c, b) => c[b + k] * Math.exp(qG[k]));
        } else if (sats.has(id)) {
          const { kind, name: pn } = sats.get(id);
          const ph = phaseFor(pn);
          if (!ph) {
            throw new RtmError(`<OUTPUT> ${name}: ${kind}(${pn}) -- "${pn}" is no phase. Give its dissolution in <PHASES>, or `
              + 'make it a mineral with its relation in <EQUILIBRIUM>.', line);
          }
          look.set(id, kind === 'SI' ? (c, b, cell) => siOf(ph, c, b, cell) : (c, b, cell) => 10 ** siOf(ph, c, b, cell));
        } else if (id === 'I') look.set(id, () => qW.I);
        else if (id === 'TK') look.set(id, (c, b, cell) => tkOf(cell));
        else if (id === 'TC') look.set(id, (c, b, cell) => tkOf(cell) - 273.15);
        else if (id === 't') look.set(id, (c, b, cell, t) => t);
        else if (id === 'x') look.set(id, (c, b, cell) => geom[cell].x);
        else if (params.index.has(id)) {
          const pk = params.index.get(id);
          look.set(id, (c, b, cell) => params.values[pk][cell]);
        } else if (outputs.some((o) => o.name === id)) {
          const o = outputs.find((x) => x.name === id);
          look.set(id, (c, b, cell, t) => o.at(c, b, cell, t));
        } else {
          throw new RtmError(`<OUTPUT> ${name}: "${id}" is no species in brackets or braces, SI() or SR(), I, TK, TC, t, x, `
            + 'parameter or <OUTPUT> above this one.', line);
        }
      }
      const o = { name, unit, line, text: def[2] };
      o.at = (c, b, cell, t) => FacsimileModel.evalAst(ast, (id) => {
        const f = look.get(id);
        return f ? f(c, b, cell, t) : undefined;
      }, {}, line);
      outputs.push(o);
      addQ(name, unit ? `${name} (${unit})` : name, 'outputs', unit,
        /mol|eq\b|g\/|ppm|ppb|atm/i.test(unit) ? 'conc' : 'index', (c, b, cell, t) => o.at(c, b, cell, t));
    }
    /*
      The water's specific conductance, density and viscosity, as PHREEQC
      works them out from <CONDUCTANCE> (waterProperties), once a point
      whichever of them is asked for; and the sodium adsorption ratio of the
      dissolved Na, Ca and Mg, in meq/kgw. A name an <OUTPUT> took first is
      left to it.
    */
    let qEval = 0;
    let qPropsAt = -1;
    let qProps = null;
    const qVm = new Float64Array(ns);
    const qWaterSolutes = qSolutes.filter((k) => nameOf[k] !== 'H2O');
    const iClQ = index.has('Cl-') && isSolute(index.get('Cl-')) ? index.get('Cl-') : -1;
    const propsOf = (c, b, cell) => {
      if (qPropsAt === qEval) return qProps;
      const wt = act.wtc ? act.wtc[cell] : act.wt;
      const ws = waterAt(wt, Math.exp(qW.lnAw));
      const wv = waterVolume(wt, ws);
      qVm.fill(0);
      if (act.vol) {
        act.vol.V.fill(0);
        molarVolumesAt(act, qW.I, !(qW.I > 1e-10), wt, ws);
        for (const k of act.vol.list) qVm[k] = act.vol.V[k];
      }
      qProps = waterProperties({ c, b, cond, I: qW.I, T: tkOf(cell), ws, wv, vm: qVm, vol: act.vol || null,
        solutes: qWaterSolutes, z: qAct.z, names: nameOf, iCl: iClQ });
      qPropsAt = qEval;
      return qProps;
    };
    const outputNames = new Set(outputs.map((o) => o.name));
    if (cond) {
      if (!outputNames.has('SC')) addQ('SC', 'specific conductance', 'water', 'µS/cm', 'index', (c, b, cell) => propsOf(c, b, cell).SC);
      if (!outputNames.has('rho')) addQ('rho', 'density', 'water', 'kg/L', 'index', (c, b, cell) => propsOf(c, b, cell).rho);
      if (!outputNames.has('viscos')) addQ('viscos', 'viscosity', 'water', 'mPa s', 'index', (c, b, cell) => propsOf(c, b, cell).visc);
    }
    const waterTerms = (el) => ((composition.elements.find((e) => e.el === el) || { terms: [] }).terms)
      .filter((tm) => tm[2] === 'water');
    const sarNa = waterTerms('Na');
    const sarCaMg = [...waterTerms('Ca'), ...waterTerms('Mg')];
    if (sarNa.length && sarCaMg.length && !outputNames.has('SAR')) {
      addQ('SAR', 'sodium adsorption ratio', 'water', '', 'index', (c, b) => {
        let na = 0;
        let camg = 0;
        for (const [k, n] of sarNa) na += n * c[b + k];
        for (const [k, n] of sarCaMg) camg += n * c[b + k];
        return camg > 0 ? (1000 * na) / Math.sqrt(1000 * camg) : NaN;
      });
    }
    /*
      WHAT EACH REACTION DOES: each <REACTIONS> line's rate -- its forward
      channel's less its backward one's, from the very code the derivative
      runs -- in the cell's own terms: times what the cell holds of the
      species for a rate on the inventory, times the porosity in the rock,
      so that times the cell's water it is what the reaction moves there in
      a unit of time, as the derivative and the budget count it. And its
      extent, what it has done since the start: a quantity of the run rather
      than of a point, the rate summed over the stored points, which the
      worker sums (rtmQuantities); `of` names the rate it sums. A held
      equilibrium has no rate of its own and is not among them.
    */
    if (reactions.length) {
      const Rq = new Float64Array(Math.max(nchan, 1));
      const Dq = new Float64Array(1);
      let ratesAt = -1;
      const chanRatesAt = (c, b, cell, t) => {
        if (ratesAt !== qEval) {
          if (ntv) atTheClock(t);
          if (nq) aqAt(c, b, false);
          rates(c, b, P, cell * np, Rq, Dq, t, TV, AQ);
          ratesAt = qEval;
        }
        return Rq;
      };
      const sym = (TIME_UNITS[settings.TIME_UNIT] || TIME_UNITS.second).symbol;
      // In the unit of the concentrations where the model has one: mol/kgw under ACTIVITY, or its CONC_UNIT.
      const molUnit = act && act.kind !== 'none' ? 'mol/kgw' : settings.CONC_UNIT || '';
      const eqs = reactions.map((rx) => splitTop(rx.text)[0].trim());
      reactions.forEach((rx, n) => {
        const j = rx.chanFirst;
        const jb = rx.chanCount > 1 ? j + 1 : -1;
        const ch = channels[j];
        // Whose capacity a rate on the inventory is a share of, as the derivative has it.
        const cap = ch.whole ? (ch.capOf >= 0 ? ch.capOf : (ch.net.length ? ch.net[0][0] : -1)) : -1;
        const name = eqs.indexOf(eqs[n]) !== eqs.lastIndexOf(eqs[n]) ? `${eqs[n]} (line ${rx.line})` : eqs[n];
        rx.name = name;
        rx.eq = eqs[n];
        addQ(`rate(${n + 1})`, `${name}, rate`, 'reactions', molUnit ? `${molUnit}/${sym}` : `/${sym}`, 'index', (c, b, cell, t) => {
          const R = chanRatesAt(c, b, cell, t);
          const net = R[j] - (jb >= 0 ? R[jb] : 0);
          return net * (ch.whole ? (cap >= 0 ? massOf[b + cap] : 1) : reactScale[cell]);
        });
        addQ(`extent(${n + 1})`, `${name}, extent`, 'reactions', molUnit, 'conc', () => NaN);
        qList[qList.length - 1].of = `rate(${n + 1})`;
      });
    }
    /**
     * The quantities at indices `which` (into the list) in cell `cell` of the
     * concentrations c at time t, into out.
     */
    function quantitiesAt(c, t, cell, which, out) {
      thermoAt(t);
      const b = cell * ns;
      qW = activityAt(qAct, c, b, qG, qD, cell);
      qEval++;
      for (let q = 0; q < which.length; q++) out[q] = qFn[which[q]](c, b, cell, t);
      return out;
    }
    /*
      WHAT EACH LINE MOVES of a sum of species -- each weighed by w, its
      count of an element, or 1 for the one species a budget is of, 0 for the
      rest -- in model cell `cell` of the concentrations c at time t: each
      <REACTIONS> line's part of the rate of change the derivative gives that
      sum there, worked out as the derivative works it out: each of the
      line's channels' rates from the very code it runs, times their net
      coefficients, times what the cell holds for a rate on the inventory or
      the porosity in the rock, a species held fixed not moved -- unless
      `held` asks for what the line would move of it too, which is what the
      holding makes up for. An amount a unit of the cell's water and of time:
      times the cell's water, what the line moves of it there. Into out, one a
      line. A line that moves the sum's parts into each other -- an element
      from one of its species to another -- moves none of it, its terms
      cancelling: to the rounding, none.
    */
    const lineR = new Float64Array(Math.max(nchan, 1));
    const lineD = new Float64Array(1);
    function lineTermsAt(c, t, cell, w, out, held = false) {
      out.fill(0);
      if (!reactions.length) return out;
      thermoAt(t);
      if (ntv) atTheClock(t);
      const b = cell * ns;
      if (nq) aqAt(c, b, false);
      rates(c, b, P, cell * np, lineR, lineD, t, TV, AQ);
      const sc = reactScale[cell];
      for (let n = 0; n < reactions.length; n++) {
        const rx = reactions[n];
        let v = 0;
        let a = 0;
        for (let j = rx.chanFirst; j < rx.chanFirst + rx.chanCount; j++) {
          const r = lineR[j];
          if (r === 0) continue;
          const sp = chanSpecies[j];
          const coef = chanCoef[j];
          const whole = chanWhole[j];
          const cap = chanCap[j];
          for (let m = 0; m < sp.length; m++) {
            const p = sp[m];
            if (!w[p] || (fixedAt[b + p] && !held)) continue;
            const term = w[p] * coef[m] * r * (whole ? massOf[b + (cap >= 0 ? cap : p)] : sc);
            v += term;
            a += Math.abs(term);
          }
        }
        out[n] = Math.abs(v) > 1e-13 * a ? v : 0;
      }
      return out;
    }
    /*
      WHAT THE LINES MOVE OF EACH SPECIES in model cell `cell` of the
      concentrations c at time t: every <REACTIONS> line's part of the
      derivative together, species by species, as the derivative works it
      out -- an amount a unit of the cell's water and of time. Into out, one
      a species. What the relations moved of each is what the budget counts
      the reactions as having made less this, summed over the stored points.
      A species held fixed in the cell is not moved, unless `held` asks for
      what the lines would move of it: what the holding makes up for.
    */
    function linesBySpeciesAt(c, t, cell, out, held = false) {
      out.fill(0);
      if (!reactions.length) return out;
      thermoAt(t);
      if (ntv) atTheClock(t);
      const b = cell * ns;
      if (nq) aqAt(c, b, false);
      rates(c, b, P, cell * np, lineR, lineD, t, TV, AQ);
      const sc = reactScale[cell];
      for (const rx of reactions) {
        for (let j = rx.chanFirst; j < rx.chanFirst + rx.chanCount; j++) {
          const r = lineR[j];
          if (r === 0) continue;
          const sp = chanSpecies[j];
          const coef = chanCoef[j];
          const whole = chanWhole[j];
          const cap = chanCap[j];
          for (let m = 0; m < sp.length; m++) {
            const p = sp[m];
            if (fixedAt[b + p] && !held) continue;
            out[p] += coef[m] * r * (whole ? massOf[b + (cap >= 0 ? cap : p)] : sc);
          }
        }
      }
      return out;
    }
    /**
     * A water as PHREEQC lists it, cell `cell` of the concentrations c at
     * time t: each species' ln of its activity coefficient (none without
     * ACTIVITY), and each phase's log IAP and log K of its dissolution at the
     * cell's temperature and pressure, its SI their difference; with every
     * quantity, the description of the water (quantitiesAt).
     * @returns {{lnG: Float64Array, values: Float64Array, phases: {name, logIAP, logK}[], tc: number}}
     */
    function listingAt(c, t, cell) {
      const values = quantitiesAt(c, t, cell, Int32Array.from(qList, (_, q) => q), new Float64Array(qList.length));
      const b = cell * ns;
      qW = activityAt(qAct, c, b, qG, qD, cell);
      qEval++;
      const phasesOut = [...new Set(siNames)].map((name) => {
        const ph = phaseFor(name);
        let lnIAP = ph.water ? ph.water * qW.lnAw : 0;
        for (const [k, nu] of ph.net) lnIAP += nu * (Math.log(Math.max(c[b + k], 1e-300)) + qG[k]);
        return { name, logIAP: (ph.sign * lnIAP) / Math.LN10, logK: (ph.sign * lnKAtP(ph.eq || ph, cell, qW)) / Math.LN10 };
      });
      return { lnG: Float64Array.from(qG), values, phases: phasesOut, tc: tkOf(cell) - 273.15 };
    }
    // <DATA>: measured tables, each column a species or one of the quantities above.
    const data = readData(sections.DATA);
    for (const tab of data) {
      for (const colName of tab.columns) {
        // A standard deviation, sd(Ca+2): of a column of the same table, and above zero where it is given.
        const sdOf = /^sd\((.+)\)$/.exec(colName);
        if (sdOf) {
          if (!tab.columns.includes(sdOf[1])) {
            throw new RtmError(`<DATA>, the table on line ${tab.line}: "${colName}" is the standard deviation of a column the `
              + `table has not: ${sdOf[1]}.`, tab.line);
          }
          const j = tab.columns.indexOf(colName) + 1;
          const bad = tab.rows.find((row) => row[j] !== null && !(row[j] > 0));
          if (bad) {
            throw new RtmError(`<DATA>, the table on line ${tab.line}: ${colName} is ${bad[j]} at ${bad[0]}; a standard deviation `
              + 'is above zero, or a dash where none is given.', tab.line);
          }
          continue;
        }
        if (index.has(colName) || qList.some((q) => q.key === colName)) continue;
        throw new RtmError(`<DATA>, the table on line ${tab.line}: "${colName}" is no species and none of the page's `
          + `quantities${qList.length ? ` (${qList.slice(0, 6).map((q) => q.key).join(', ')}${qList.length > 6 ? ' and more' : ''})` : ''}.`,
        tab.line);
      }
      if (tab.axis === 'tot' && !composition.elements.some((e) => e.el === tab.species)) {
        throw new RtmError(`<DATA>, the table on line ${tab.line}: sys(${tab.species}) is the ${tab.species} in the cell, and no `
          + `species of the model has any${composition.elements.length ? ` (it has ${composition.elements.map((e) => e.el).join(', ')})` : ''}.`,
        tab.line);
      }
      if (tab.pH !== null && tab.pH !== undefined && !index.has('H+')) {
        throw new RtmError(`<DATA>, the table on line ${tab.line}: pH = ${tab.pH} holds the water's H+, and the model has none.`, tab.line);
      }
      for (const [name, v] of tab.water || []) {
        if (!index.has(name)) {
          throw new RtmError(`<DATA>, the table on line ${tab.line}: "${name} = " starts a species the model has not.`, tab.line);
        }
        if (!(v >= 0)) {
          throw new RtmError(`<DATA>, the table on line ${tab.line}: ${name} = ${v}; a species starts at a number of nought or more.`,
            tab.line);
        }
      }
      if ((tab.kind === 'time' || tab.kind === 'speciation') && tab.cell !== null && tab.cell >= nf) {
        throw new RtmError(`<DATA>, the table on line ${tab.line}: cell = ${tab.cell}, where the column has ${nf} (0 to ${nf - 1}).`,
          tab.line);
      }
    }

    const stateNames = [];
    for (let c = 0; c < nc; c++) {
      const g = geom[c];
      for (let s = 0; s < ns; s++) {
        stateNames.push(nc === 1 ? nameOf[s] : g.reservoir ? `${nameOf[s]}@${g.reservoir}`
          : g.j === 0 ? `${nameOf[s]}@${g.i}` : `${nameOf[s]}@${g.i}.${g.j}`);
      }
    }

    const model = {
      // What the solvers ask for.
      nspecies: n,
      nnz,
      pattern: { n, nnz, colPtr, rowIdx },
      species: stateNames,
      initialState: () => Float64Array.from(initial),
      // What a mineral under precipitate_only starts with, set aside: shown with what is held of it (toConcentrations).
      inert,
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
      cells: ncCol,            // every cell of the column, matrix layers and extra cells included
      // ...and the reservoirs after them, which only the solver and the model's own code meet:
      // where each is in the state, -1 for an end that is no reservoir (THE RESERVOIRS).
      allCells: nc,
      reservoir: { left: resCell.left, right: resCell.right },
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
      // What is an amount that may reach zero rather than ln C: a mineral, and a gas in a bubble at a fixed pressure.
      mineral: Uint8Array.from(species, (sp) => (sp.mineral || (sp.gas && act && act.gas && act.gas.fixed === 'pressure')
        ? 1 : 0)),
      // Held state by state, and the species held in some cells only.
      fixedAt,
      held: held.map((h) => ({ species: h.species, cells: h.cells })),
      tables: [...tables.keys()],
      // Each <REACTIONS> line: where it is, its equation and its name, and what its forward channel moves -- for the budget
      // by each reaction, which counts a line and one written apart that undoes it as one pair.
      reactions: reactions.map((rx) => ({ line: rx.line, text: rx.text, name: rx.name, eq: rx.eq,
        net: channels[rx.chanFirst] ? channels[rx.chanFirst].net.map(([k, c]) => [k, c]) : [],
        whole: !!(channels[rx.chanFirst] && channels[rx.chanFirst].whole), both: rx.chanCount > 1 })),
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
      // A and B are at TEMPERATURE where it is a number; where it is an expression, at each cell's (Ac, Bc), and null here.
      activity: act && act.kind !== 'none' ? { kind: act.kind, temperature: tcFixed !== null ? tcFixed : settings.TEMPERATURE,
        A: thermo.varies ? null : act.A, B: thermo.varies ? null : act.B,
        ions: ions.length, pairs: pairInfo.length, sit: act.sit ? act.sit.pairs.length : 0,
        pitzer: act.pz ? { params: act.pz.np, macinnes: act.pz.icon, etheta: act.pz.etheta } : null,
        // <VOLUMES>: how many species and phases have a molar volume, at what pressure, and whether it corrects anything.
        volumes: act.vol ? { given: act.vol.list.length + act.vol.phases.size, pressure: act.wt ? act.wt.atmGiven : 1,
          idle: !!act.vol.idle } : null,
        // <CONDUCTANCE>: the conductance, the density and the viscosity, and by which of PHREEQC's equations.
        conductance: cond ? { falk: cond.falk } : null } : null,
      /*
        THE TEMPERATURE: the number, or the expression, TEMPERATURE gives;
        whether it differs from cell to cell and goes with time; how many
        relations' and phases' log K go with it; and each cell's, in C, at a
        time t (temperatures), which is where the model is then evaluated at.
      */
      // The solid solutions: each one's name, end members and, for a binary one, a0 and a1 at 25 C (binaryAt).
      solidSolutions: solids.map((d) => ({ name: d.name, members: d.members.map((k) => nameOf[k]),
        binary: d.coef === 'binary' ? { a0: d.ag0 / (R_KJ * 298.15), a1: d.ag1 / (R_KJ * 298.15),
          gap: !!binaryAt(d, 298.15).gap } : null })),
      temperature: { given: tcFixed !== null ? tcFixed : settings.TEMPERATURE, varies: thermo.varies, cells: tempCells,
        clock: tempClock, relations: relT.length, phases: phT.length, reads: readsT },
      thermoAt,
      // The column's cells' temperatures: a reservoir's is the cell's beside it.
      temperatures(t) { thermoAt(t); return Float64Array.from(thermo.tc.subarray(0, ncCol)); },
      // What the run can be read as besides its species (QUANTITIES), and what <DATA> measured.
      quantities: qList,
      quantitiesAt,
      lineTermsAt,
      linesBySpeciesAt,
      listingAt,
      data,
      // What each species is made of, for the views of where an element is and of the water's major ions.
      composition,
      // Each species' formula mass, g/mol, or null where it has none (formulaMassesOf).
      masses,
      nchannels: channels.length,
      warnings,
      fixes,
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
    // ...and a surface only a surface while its relations hold.
    if (sf && transport && settings.EQUILIBRATE !== 2
      && !equilibria.some((eq) => eq.kf !== null && eq.net.some(([k]) => species[k].surface))) {
      warnings.push(`What is on the surface is put on its relations ${settings.EQUILIBRATE ? 'at the start only' : 'never'}`
        + ', and then stays as it is while the water moves past: EQUILIBRATE = always holds it all through the run.');
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
          + 'in every cell, or in none and let the water there set it.'
          + (resSides.length ? ` A reservoir is one of the ${nc}: an <INITIAL> line naming ${resSides.join(' or ')} gives it its own.`
            : ''), species[electron].line);
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
    // The relations of the water alone: none with an exchanger or a surface in it.
    const loading = !!((ex && ex.load.length) || (sf && sf.load.length));
    const waterOnly = equilibria.filter((eq) => !eq.net.some(([k]) => (ex && ex.site[k]) || species[k].surface));
    if (peStart && settings.EQUILIBRATE) {
      const fx = Uint8Array.from(fixed, (v) => (v ? 1 : 0));
      fx[electron] = 1;
      // Without what goes on an exchanger or a surface loaded from this water: that comes next.
      const rel = loading ? waterOnly : equilibria;
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
    if (loading) {
      if (settings.EQUILIBRATE && waterOnly.length && !peStart) {
        initial.set(speciate(model, initial, { equilibria: waterOnly }).y);
      }
      // Sites per mole of a mineral: at what the water's own speciation has left of it, which they then go with.
      if (ex && ex.load.length && ex.perAny) {
        const nx = ex.exchangers.length;
        for (const q of ex.load) {
          const x = q % nx;
          const p = ex.per[x];
          if (!p) continue;
          const b = Math.floor(q / nx) * ns;
          const total = p.ratio * initial[b + p.mineral];
          if (!(total > 0)) {
            throw new RtmError(`The sites of ${nameOf[ex.exchangers[x]]} go with ${nameOf[p.mineral]}, and the water's own `
              + `speciation leaves none of it${nc === 1 ? '' : whereIs(Math.floor(q / nx))}.`,
            species[p.species].line);
          }
          ex.capacity[q] = total;
          for (const j of ex.members[x]) ex.shift[b + j] = Math.log(ex.n[j] / total);
        }
      }
      if (ex && ex.load.length) loadExchangers(model, initial);
      // A CD-MUSIC surface is not loaded from the water: its species are given their amounts.
      if (sf && sf.load.length && act.pt && act.pt.cd) {
        const nt = sf.types.length;
        for (const q of sf.load) {
          const t = sf.types[q % nt];
          const k = t.members.find((j) => act.pt.of[j] >= 0 && act.pt.kind[act.pt.of[j]] === 'c0');
          if (k !== undefined) {
            throw new RtmError(`${nameOf[t.sitesFrom]} is given its sites to be loaded from the water, on a CD-MUSIC surface, `
              + 'which is not loaded so: give its species their amounts, the bare site all of them if need be, and the '
              + 'start puts them on the relations.', species[t.sitesFrom].line);
          }
        }
      }
      // Sites per mole of a mineral: at what the water's own speciation has left of it, which they then go with.
      if (sf && sf.load.length) {
        const nt = sf.types.length;
        for (const q of sf.load) {
          const t = sf.types[q % nt];
          if (!t.per) continue;
          const b = Math.floor(q / nt) * ns;
          const total = t.per.ratio * initial[b + t.per.mineral];
          if (!(total > 0)) {
            throw new RtmError(`The sites of ${nameOf[t.sitesFrom]} go with ${nameOf[t.per.mineral]}, and the water's own `
              + `speciation leaves none of it${nc === 1 ? '' : whereIs(Math.floor(q / nt))}.`, species[t.sitesFrom].line);
          }
          sf.sites[q] = total;
          for (const k of t.members) sf.shift[b + k] = Math.log(sf.n[k] / total);
        }
        loadSurfaces(model, initial);
      }
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
      // The column's cells, as the page reports them: a reservoir's speciation is in the warning above.
      model.speciated = done.cells.slice(0, ncCol);
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
    // Each cell's temperature, and what reads it, at the time asked for (compile's thermoAt).
    const thermoAt = base.thermoAt || (() => {});
    // Every cell the state has: the reservoirs hold their relations as the column's cells do.
    const nc = base.allCells || base.cells;
    const nBase = base.nspecies;
    const fixed = base.fixed;
    // An exchanger, the electron or a potential is no amount: it counts in no total, whatever its R.
    const site = base.rank || null;
    const massless = (s) => !!site && site[s] >= 2;
    const massOf = site ? Float64Array.from(base.massOf, (m, i) => (site[i % ns] >= 2 ? 0 : m)) : base.massOf;
    /*
      What a reaction gives a total: each species' rate weighed as it is in
      the total, and the electron's own as well. Its value, the pe, counts
      in no total, but a reaction that takes or gives electrons moves the
      electrons the couples hold, and its rate on the electron -- nothing
      else moves it, as it neither moves nor is fixed -- is that.
    */
    const eSp = base.electron >= 0 ? base.electron : -1;
    const rateMass = eSp >= 0 ? Float64Array.from(massOf, (m, i) => (i % ns === eSp ? base.massOf[i] : m)) : massOf;
    const start = base.initialState();
    const basis = conservationBasis(eqs, ns, fixed, abundanceOf(start, ns, nc), site);
    const ne = eqs.length;
    const nb = basis.length;
    const active = equilibriumSpecies(eqs).filter((si) => !fixed[si]);
    const na = active.length;
    // Each surface's potential has an equation of its own, Gouy and Chapman's.
    const npot = active.filter((si) => site && site[si] === 3).length;
    if (ne + nb + npot !== na) {
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
    // Under SIT a coefficient reads the species it is paired with as well, which may be neutral: every solute.
    // On an exchanger whose sites go with a mineral, a species' fraction reads all that is on it (exchangeFractions).
    const exPer = act && act.ex && act.ex.perAny ? act.ex : null;
    const onPer = (eq) => new Set(exPer ? eq.net.filter(([s]) => exPer.site[s] === 1 && exPer.per[exPer.of[s]])
      .flatMap(([s]) => exPer.members[exPer.of[s]]) : []);
    const actCols = eqs.map((eq) => {
      if (!act) return [];
      const per = onPer(eq);
      return [...Array(ns).keys()].filter((k) => act.z[k] !== 0
        || ((eq.water || act.sit || act.pz || act.dGw || (act.vol && !act.vol.idle)) && act.solute[k])
        || (act.gas && act.gas.dln && act.gas.isGas[k] && eq.net.some(([s]) => act.gas.isGas[s]))
        || per.has(k));
    });
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
    eqs.forEach((eq, r) => { if (eq.mineral >= 0 && !eq.grp) mins.push(r); });
    const nmin = mins.length;
    const present = new Uint8Array(nc * ne).fill(1);
    const minAt = eqs.map((eq) => eq.net.findIndex(([sp]) => sp === eq.mineral));
    /*
      A mineral that carries a surface's sites (per=) is taken as used up at
      1e-4 of what its cell starts with: its sites go with it, and the
      species on them, held as ln C, cannot follow them to none -- the run
      stops there and says so (applyEvent).
    */
    const usedUp = new Float64Array(nc * ne);
    /*
      A mineral's bounds in a cell (eq.bounds, compile), and its mode: 1
      held at saturation between them, 0 at the lower -- none, usually -- and
      4 at the upper, the water past saturation the way it cannot follow.
    */
    const loAt = (c, r) => (eqs[r].bounds ? eqs[r].bounds.lo[c] : 0);
    const hiAt = (c, r) => (eqs[r].bounds ? eqs[r].bounds.hi[c] : Infinity);
    const boundAt = (c, r) => {
      if (present[c * ne + r] === 4) return hiAt(c, r);
      const lo = loAt(c, r);
      return Number.isFinite(lo) ? lo : 0;
    };
    const atBound = (c, r) => { const p = present[c * ne + r]; return p === 0 || p === 4; };
    // Within `tiny` of a bound, at it.
    const modeOf = (c, r, M, tiny = 0) => (M >= hiAt(c, r) - tiny ? 4 : M > loAt(c, r) + tiny ? 1 : 0);
    // Held, an event watches its amount against its bounds, the lower where it is used up, and which it nears.
    const nearHi = new Uint8Array(nc * ne);
    const heldEvent = (c, r, M) => {
      const lo = loAt(c, r);
      const a = (lo === -Infinity ? -Infinity : Math.max(lo, usedUp[c * ne + r])) - M;
      const d = M - hiAt(c, r);
      nearHi[c * ne + r] = d > a ? 1 : 0;
      const v = Math.max(a, d);
      return Number.isFinite(v) ? v : -1;
    };
    eqs.forEach((eq, r) => {
      if (eq.carry && eq.mineral >= 0) for (let c = 0; c < nc; c++) usedUp[c * ne + r] = 1e-4 * start[c * ns + eq.mineral];
    });
    /*
      THE GROUPS -- a bubble at a fixed pressure (gasSetup), a solid solution
      (solidSolutionSetup): each one's relations come and go together, at one
      event a cell, and while it is there their rows are the group's
      (bubbleRows), each reading every member of the group and every species
      of its relations -- the columns `cols`, a member at `k` among them.
      grpOf: each relation's group, or null.
    */
    const grpDefs = [];
    eqs.forEach((eq) => { if (eq.grp && !grpDefs.includes(eq.grp)) grpDefs.push(eq.grp); });
    const grps = grpDefs.map((def) => {
      const rels = [];
      eqs.forEach((eq, r) => { if (eq.grp === def) rels.push(r); });
      const colSet = new Set();
      for (const r of rels) {
        for (const [s] of eqs[r].net) colSet.add(s);
        for (const k of actCols[r]) colSet.add(k);
      }
      const cols = [...colSet].sort((a, b2) => a - b2);
      const loc = new Map(cols.map((s, i) => [s, i]));
      return { def, rel: Int32Array.from(rels), cols, loc, k: Int32Array.from(rels, (r) => loc.get(eqs[r].mineral)),
        prIdx: def.coef === 'pr' ? Int32Array.from(rels, (r) => def.gas.qOf[eqs[r].mineral]) : null,
        mem: Int32Array.from(rels, (r) => eqs[r].mineral), nu: Float64Array.from(rels, (r) => eqs[r].mineralNu),
        lnP: def.lnP, lnE: new Float64Array(rels.length), w: new Float64Array(rels.length),
        rows: rels.map(() => new Float64Array(cols.length)), mean: new Float64Array(cols.length) };
    });
    const ngrp = grps.length;
    const grpOf = eqs.map((eq) => (eq.grp ? grps[grpDefs.indexOf(eq.grp)] : null));
    const bubF = new Float64Array(ne);
    const bubJ = [];
    for (const G of grps) for (const r of G.rel) bubJ[r] = new Float64Array(G.cols.length);
    // A group's members' amounts together in the cell at b.
    const groupN = (G, yy, b) => { let N = 0; for (const g of G.mem) N += yy[b + g]; return N; };
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
    /*
      And for a model with a surface's potential: its equation is no relation
      and no total, and the speciation of each cell is where it is solved.
    */
    const projected = base.electron >= 0 || npot > 0;
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
        if (grpOf[r]) for (const s of grpOf[r].cols) touch(b + relRow[r], b + s);
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
    const relG = [];
    for (let c = 0; c < nc; c++) {
      const b = c * ns;
      defT.push(Int32Array.from({ length: nb }, (_, j) => slot(b + defAt[j], tIndex(c, j))));
      defC.push(U.map((uj, j) => Int32Array.from(active, (s, k) => (uj[k] ? slot(b + defAt[j], b + s) : -1))));
      relC.push(eqs.map((eq, r) => Int32Array.from(eq.net, ([s]) => slot(b + relRow[r], b + s))));
      relA.push(eqs.map((eq, r) => Int32Array.from(actCols[r], (k) => slot(b + relRow[r], b + k))));
      relG.push(ngrp ? eqs.map((eq, r) => (grpOf[r] ? Int32Array.from(grpOf[r].cols, (s) => slot(b + relRow[r], b + s)) : null))
        : null);
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
      let g = -lnKAtP(eq, (b / ns) | 0, water);
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
      if (zOf[c]) {
        for (let j = 0; j < nb; j++) totalsP[j] = y[tIndex(c, j)];
        return reducedSensitivity(rsys, Cs, 0, totalsP, wP, present.subarray(c * ne, (c + 1) * ne), c, zOf[c], outside);
      }
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
      thermoAt(t);
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
          // None of the mineral, or as much as its bounds let it have (eq.bounds): its amount is that, and the relation waits.
          const m = eqs[r].mineral;
          out[b + relRow[r]] = m >= 0 && atBound(c, r) ? y[b + m] - boundAt(c, r) : relationAt(b, r, y, water);
        }
        // Each group, while it is there: its relations' rows together.
        for (const G of grps) {
          if (!present[c * ne + G.rel[0]]) continue;
          for (let q = 0; q < G.rel.length; q++) G.lnE[q] = -relationAt(b, G.rel[q], y, water) / G.nu[q];
          groupRowsAt(G, present[c * ne + G.rel[0]], c, (q) => y[b + G.mem[q]], G.cols.length, bubF, null, 1);
          for (const r of G.rel) out[b + relRow[r]] = bubF[r];
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
            rate += U[j][k] * rateMass[at] * f[at];
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
            const w = pW[t2] * (pMass[t2] >= 0 ? rateMass[pMass[t2]] : 1) * v;
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
      thermoAt(t);
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
          if (eqs[r].mineral >= 0 && atBound(c, r)) {
            V[relC[c][r][minAt[r]]] += 1;
            continue;
          }
          // A group's relations, while it is there: below.
          if (grpOf[r]) continue;
          eqs[r].net.forEach(([s, nu], m) => {
            if (isMin[s]) return;
            V[relC[c][r][m]] += held[b + s] ? nu : nu / C[b + s];
          });
          if (!act) continue;
          // The coefficients through the ionic strength, and the water: in
          // a held species' column times C, as everything in ln C is.
          let G = pressureTermI(eqs[r], water);
          for (const [s, nu] of eqs[r].net) G += nu * dG[s];
          const w = waterCoef(eqs[r], water);
          const sd = sitPartners(act, eqs[r].net, water);
          actCols[r].forEach((k, q) => {
            let d = G * 0.5 * act.z[k] * act.z[k];
            if (w) d += w * awOf(act, water, k);
            if (sd) d += sd[k];
            if (d) V[relA[c][r][q]] += held[b + k] ? d * C[b + k] : d;
          });
          if (sd) sitDone(act, eqs[r].net);
        }
        for (const bub of grps) {
          if (!present[c * ne + bub.rel[0]]) continue;
          // Each member's ln of its share of the water, and its gradient in the state, over the group's columns.
          for (let q = 0; q < bub.rel.length; q++) {
            const r = bub.rel[q];
            const eq = eqs[r];
            const f = -1 / bub.nu[q];
            const row = bub.rows[q];
            row.fill(0);
            for (const [s, nu] of eq.net) {
              if (isMin[s]) continue;
              row[bub.loc.get(s)] += f * (held[b + s] ? nu : nu / C[b + s]);
            }
            if (act) {
              let Gd = pressureTermI(eq, water);
              for (const [s, nu] of eq.net) Gd += nu * dG[s];
              const w = waterCoef(eq, water);
              const sd = sitPartners(act, eq.net, water);
              for (const k of actCols[r]) {
                let d = Gd * 0.5 * act.z[k] * act.z[k];
                if (w) d += w * awOf(act, water, k);
                if (sd) d += sd[k];
                if (d) row[bub.loc.get(k)] += f * (held[b + k] ? d * C[b + k] : d);
              }
              if (sd) sitDone(act, eq.net);
            }
            bub.lnE[q] = f * relationAt(b, r, y, water);
          }
          groupRowsAt(bub, present[c * ne + bub.rel[0]], c, (q) => y[b + bub.mem[q]], bub.cols.length, bubF, bubJ, 1);
          for (const r of bub.rel) {
            const sl = relG[c][r];
            const Jr = bubJ[r];
            for (let i = 0; i < sl.length; i++) if (Jr[i]) V[sl[i]] += Jr[i];
          }
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
    /*
      The projection is the reduced speciation (reducedSystem), its
      components the species that make up the start, least abundant made
      dependent first, an exchanger or the electron kept a component; the
      full one where there is no reduced system. Each cell's reduced unknowns
      are kept for its derivatives (sensitivities). What neither start
      settles in 60 iterations is a Newton iterate whose totals no water has,
      and the step is cut: on a pyrite column the full speciation settled one
      of 141 such, at 200 iterations each.
    */
    let rsys = null;
    if (projected) {
      const abundance = abundanceOf(start, ns, nc);
      const rankOf = (k) => (site && site[active[k]] === 1 ? 0 : site && site[active[k]] >= 2 ? 2 : 1);
      const prefer = [...Array(na).keys()].sort((a, b2) => (rankOf(a) - rankOf(b2))
        || (Math.abs(abundance[active[a]]) - Math.abs(abundance[active[b2]])) || a - b2);
      rsys = reducedSystem(sys, prefer);
      if (rsys) rsys.outside = outside;
    }
    const zOf = projected ? Array.from({ length: nc }, () => null) : null;
    function project(c, y) {
      const b = c * ns;
      for (let j = 0; j < nb; j++) totalsP[j] = y[tIndex(c, j)];
      for (let k = 0; k < na; k++) wP[k] = massOf[b + active[k]];
      const pres = present.subarray(c * ne, (c + 1) * ne);
      const opts = { tol: 1e-12, roundOff: true, cell: c, maxIter: rsys ? 60 : 200, asStarted: true };
      const fromIterate = () => { for (let s = 0; s < ns; s++) Cs[s] = C[b + s]; };
      const fromSettled = () => {
        fromIterate();
        for (let k = 0; k < na; k++) Cs[active[k]] = settled[c][k];
      };
      let res = null;
      let reduced = false;
      for (const [solve, start2] of rsys ? [['reduced', fromIterate], ['reduced', fromSettled]]
        : [['full', fromIterate], ['full', fromSettled]]) {
        if (start2 === fromSettled && !settled[c]) continue;
        start2();
        res = solve === 'reduced' ? reducedSpeciate(rsys, Cs, 0, totalsP, wP, pres, opts)
          : speciateCell(sys, Cs, 0, totalsP, wP, pres, opts);
        if (res.converged) { reduced = solve === 'reduced'; break; }
      }
      if (!res || !res.converged) return null;
      zOf[c] = reduced ? Float64Array.from(res.z) : null;
      if (!settled[c]) settled[c] = new Float64Array(na);
      for (let k = 0; k < na; k++) settled[c][k] = Cs[active[k]];
      return res.x;
    }
    // The cell of the event just applied, and the mineral it brought in (or -1), for consistentInitial.
    let lastEvent = null;
    function consistentInitial(t, y, opts = {}) {
      thermoAt(t);
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
        /*
          READ BACK FROM A STATE, a mineral within a rounding error of a
          bound is at it -- a rounding error of the cell's largest total --
          and a group with no more than that of it is not there. Projected,
          what the run held at none is none and an error of the arithmetic,
          1e-33 of FeS(ppt) in an oxic cell, and read as some it is held at
          saturation where it cannot be: a hundred iterations that do not
          settle, three hundred more before the one that is not there is
          found, and where a cell never settles the whole state is shown as
          the solver left it -- on a column of a plume's redox zones, 223
          stored points of 303, at 110 ms each. Those errors come to 1e-24 of
          the largest total and less. No more than a rounding error: a solid
          solution a step after it forms holds 7e-13 of it, and read as none
          its composition would be none either.
        */
        let tiny = 0;
        if (opts.fromState) for (let j = 0; j < nb; j++) tiny = Math.max(tiny, Number.EPSILON * Math.abs(totalsCell[j]));
        const pres = opts.fromState
          ? Uint8Array.from(eqs, (eq, r) => (grpOf[r] ? groupMode(grpOf[r], (q) => y[b + grpOf[r].mem[q]], c, tiny)
            : (eq.mineral < 0 ? 1 : modeOf(c, r, y[b + eq.mineral], tiny))))
          : present.subarray(c * ne, (c + 1) * ne);
        /*
          Projected, the held species in the state carry no weight and may
          stand far from what their totals make them: the cell is started
          from its reduced speciation, from there or from where it last
          settled, and only then polished and its minerals settled.
        */
        if (rsys) {
          for (let s = 0; s < ns; s++) Cs[s] = C[b + s];
          let r0 = reducedSpeciate(rsys, Cs, 0, totalsCell, wCell, pres, { tol, cell: c, maxIter: 60 });
          if (!r0.converged && settled[c]) {
            for (let s = 0; s < ns; s++) Cs[s] = C[b + s];
            for (let k = 0; k < na; k++) Cs[active[k]] = settled[c][k];
            r0 = reducedSpeciate(rsys, Cs, 0, totalsCell, wCell, pres, { tol, cell: c, maxIter: 60 });
          }
          if (r0.converged) for (const s of active) C[b + s] = Cs[s];
        }
        // The cell an event has just brought a mineral into, as it was, in case that mineral cannot be there beside another.
        const evHere = !!lastEvent && lastEvent.c === c && !opts.fromState;
        const kept = evHere ? C.slice(b, b + ns) : null;
        let res = speciateCell(sys, C, b, totalsCell, wCell, pres,
          { tol, roundOff: true, activeSet: !!opts.fromState, cell: c });
        if (evHere && !res.converged) {
          // Gypsum where anhydrite comes in: the one it cannot be beside goes (speciateCell).
          C.set(kept, b);
          const before = Uint8Array.from(pres);
          res = speciateCell(sys, C, b, totalsCell, wCell, pres,
            { tol, roundOff: true, activeSet: true, cell: c, enter: lastEvent.r >= 0 ? lastEvent.r : undefined });
          const gone = mins.filter((r) => before[r] && !pres[r]).map((r) => base.speciesNames[eqs[r].mineral]);
          if (res.converged && gone.length) {
            events[lastEvent.which].shown += `, and ${gone.join(' and ')} ${gone.length > 1 ? 'have' : 'has'} dissolved away`;
          }
        }
        iterations = Math.max(iterations, res.iterations);
        worstRes = Math.max(worstRes, res.residual);
        if (!res.converged && !why) {
          why = res.why === 'singular' ? `the relations do not determine the held species in cell ${c}`
            : res.why && res.why !== 'unsettled' ? `${res.why} in cell ${c}`
              : `the held equilibria did not settle in cell ${c} (residual ${res.residual.toExponential(2)})`;
        }
        for (let k = 0; k < na; k++) {
          const st = b + active[k];
          moved = Math.max(moved, Math.abs(res.x[k] - y[st]));
          y[st] = res.x[k];
        }
      }
      lastEvent = null;
      return { solved: !why, iterations, residual: worstRes, moved, why };
    }

    // What the page shows of a state: its held species put exactly on the
    // relations and the totals the state carries, then out of the logarithm.
    // The solver leaves a step once its Newton correction is under the
    // tolerance, which on the totals' rows is a part in 1e9 at rtol 1e-8; the
    // totals themselves are integrated, and what is conserved is conserved to
    // rounding there. So every point shown is the speciation of its totals.
    // t, the time of the state: where the temperature goes with time, the relations are those of that time.
    // A mineral under precipitate_only: what it started with, set aside, is shown with what is held of it.
    const inertOf = base.inert || [];
    const toConcentrations = (y, t = 0) => {
      let z = Float64Array.from(y);
      /*
        Where the speciation of its totals does not settle, the state as the
        solver left it, its held species on the relations to the solver's
        tolerance: what does not settle is no speciation. One stopped at a
        residual of 4e-4 showed a water's ferrihydrite dissolved into it as
        iron(3), and the pe at 8 between points at 5.7 and 4.6.
      */
      if (!consistentInitial(t, z, { rtol: 1e-12, fromState: true }).solved) z = Float64Array.from(y);
      const out = new Float64Array(nBase);
      for (let k = 0; k < nBase; k++) out[k] = held[k] && !lin[k] ? Math.exp(z[k]) : z[k];
      for (const { k, amounts } of inertOf) for (let c = 0; c < nc; c++) out[c * ns + k] += amounts[c];
      return out;
    };
    // A state from concentrations as the state holds them (a mineral's inert part apart), and from what the page shows.
    const stateOf = (cIn) => {
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
    const fromConcentrations = (cShown) => {
      if (!inertOf.length) return stateOf(cShown);
      const cIn = Float64Array.from(cShown);
      for (const { k, amounts } of inertOf) for (let c = 0; c < nc; c++) cIn[c * ns + k] -= amounts[c];
      return stateOf(cIn);
    };
    const initial = stateOf(start);

    /*
      THE MINERALS' EVENTS, one for each mineral in each cell. While there is
      some of it, the event is minus its amount, which reaches zero from below
      when the last of it dissolves; while there is none, it is the
      saturation index, which reaches zero from below when the water becomes
      supersaturated. Either way it is crossed upwards, the run stops there,
      the mineral is switched, and the run starts again from the state put
      back on its constraints (runModel in facsimile-solver.js).
    */
    /*
      And a bubble's, one for each cell after the minerals': while it is
      there, minus its gases' amounts together, which reaches zero from below
      when the last of it dissolves; while there is none, ln of the pressures
      the water holds its gases at, together, over the total, which reaches
      zero from below when they come to the total and a bubble forms.
    */
    const where = (c) => (nc > 1 ? ` in cell ${c}` : '');
    // One event a cell for each group, after the minerals': nc * nmin + c * ngrp + g; and for each binary solid
    // solution its miscibility gap's, after those: nc * nmin + nc * ngrp + c * nbin + i.
    const nbub = nc * ngrp;
    const bins = grps.filter((G) => G.def.coef === 'binary');
    const nbin = bins.length;
    const gapStart = nc * nmin + nbub;
    /*
      A mineral made and used at a rate whose sites go with it (per=, its
      reactions carrying them): used up at 1e-4 of what its cell starts with,
      where the run stops, as for one held at saturation (applyEvent).
    */
    const kinSites = [...new Set([...(act && act.sf ? act.sf.types.filter((t) => t.per && !t.per.eq)
      .map((t) => t.per.mineral) : []), ...(act && act.ex && act.ex.perAny ? act.ex.per.filter((p) => p && !p.eq)
      .map((p) => p.mineral) : [])])];
    // What goes with a mineral that is used up, for the message: a surface's sites, an exchanger's, or both.
    const goneWith = (m) => {
      const surface = !!(act && act.sf && act.sf.types.some((t) => t.per && t.per.mineral === m));
      const exchanger = !!(act && act.ex && act.ex.perAny && act.ex.per.some((p) => p && p.mineral === m));
      const what = surface && exchanger ? 'surface and of the exchanger that go' : surface ? 'surface that goes'
        : 'exchanger that goes';
      const none = surface && exchanger ? 'surface or exchanger' : surface ? 'surface' : 'exchanger';
      return `, and the sites of the ${what} with it, so many per mole of it, with it: the page carries no ${none} with `
        + 'no sites. Give more of it, or end the run before.';
    };
    const nks = kinSites.length;
    const ksStart = gapStart + nc * nbin;
    const ksUsedUp = new Float64Array(nc * nks);
    for (let c = 0; c < nc; c++) kinSites.forEach((m, i) => { ksUsedUp[c * nks + i] = 1e-4 * start[c * ns + m]; });
    const kinSiteValues = (y, out) => {
      for (let c = 0; c < nc; c++) {
        for (let i = 0; i < nks; i++) out[ksStart + c * nks + i] = ksUsedUp[c * nks + i] - y[c * ns + kinSites[i]];
      }
      return out;
    };
    // Where eventValues last found that a group forming would go, and one leaving its gap.
    const formAt = new Uint8Array(nbub);
    const exitAt = new Uint8Array(nc * nbin);
    const events = Array.from({ length: nc * nmin }, (_, q) => ({
      expr: `${base.speciesNames[eqs[mins[q % nmin]].mineral]}${where(Math.floor(q / nmin))}`,
      shown: '', assigns: ['present'], once: false, stop: false,
    })).concat(Array.from({ length: nbub }, (_, q) => ({
      expr: `${grps[q % ngrp].def.name}${where(Math.floor(q / ngrp))}`, shown: '', assigns: ['present'], once: false,
      stop: false,
    }))).concat(Array.from({ length: nc * nbin }, (_, q) => ({
      expr: `${bins[q % nbin].def.name}'s miscibility gap${where(Math.floor(q / nbin))}`, shown: '', assigns: ['present'],
      once: false, stop: false,
    }))).concat(Array.from({ length: nc * nks }, (_, q) => ({
      expr: `${base.speciesNames[kinSites[q % nks]]}${where(Math.floor(q / nks))}`, shown: '', assigns: ['sites'], once: true,
      stop: false,
    })));
    // A relation without its gas, at the concentrations Cc of the cell at b.
    const relationOf = (Cc, b, r, water) => {
      const eq = eqs[r];
      let g = -lnKAtP(eq, (b / ns) | 0, water);
      for (const [sp, nu] of eq.net) {
        if (isMin[sp]) continue;
        g += nu * Math.log(Math.max(Cc[b + sp], 1e-300));
        if (act) g += nu * lnG[sp];
      }
      if (act && eq.water) g += eq.water * water.lnAw;
      return g;
    };
    // ln of a group's members' shares of the water, together, less ln of their total.
    const bubbleExcessAt = (bub, Cc, b, water) => {
      let top = -Infinity;
      for (let q = 0; q < bub.rel.length; q++) bub.lnE[q] = -relationOf(Cc, b, bub.rel[q], water) / bub.nu[q];
      bub.formMode = groupFormsAt(bub, (b / ns) | 0);
      bub.mode = 0;
      groupReal(bub, bub.cols.length, false, (b / ns) | 0);
      for (let q = 0; q < bub.rel.length; q++) top = Math.max(top, bub.lnE[q]);
      let S = 0;
      for (let q = 0; q < bub.rel.length; q++) S += Math.exp(bub.lnE[q] - top);
      return top + Math.log(S) - bub.lnP;
    };
    /*
      A binary solid solution's miscibility gap, as an event: below the gap
      (mode 1) the water's ln(IAP2 K1/(IAP1 K2)) less the gap's, reaching
      zero where the solid comes to the gap; above it (3) the other way; in
      it (2), the second member's amount less xb2 of the whole, or xb1 of the
      whole less it, the larger, reaching zero where the solid's composition
      leaves the gap -- that side noted in exitAt. -1 where there is no
      solid solution or no gap; 1 in a gap that has closed.
    */
    const gapValue = (G, i, c, Cc, b, water, amt) => {
      const mode = present[c * ne + G.rel[0]];
      if (!mode) return -1;
      const { gap } = binaryAt(G.def, G.def.tk[c]);
      if (!gap) { exitAt[c * nbin + i] = 1; return mode === 2 ? 1 : -1; }
      if (mode === 2) {
        const nb2 = amt(1);
        const N = amt(0) + nb2;
        const up = nb2 - gap.xb2 * N;
        const down = gap.xb1 * N - nb2;
        exitAt[c * nbin + i] = up > down ? 3 : 1;
        return Math.max(up, down);
      }
      const L = -relationOf(Cc, b, G.rel[1], water) / G.nu[1] + relationOf(Cc, b, G.rel[0], water) / G.nu[0];
      const Lg = gap.lnAb - gap.lnAc;
      return mode === 1 ? L - Lg : Lg - L;
    };
    function eventValues(t, y, out) {
      thermoAt(t);
      /*
        Projected, a held species in the state is only near its projection
        -- it carries no weight in the error test -- and a mineral's
        saturation read off it fired "precipitates" on noise and stalled a
        redox front: the projection's own amounts and saturations, then.
      */
      if (projected) {
        projectAll(y);
        for (let c = 0; c < nc; c++) {
          const b = c * ns;
          const water = act && xs[c] ? activityAt(act, Cstar, b, lnG, dG) : null;
          for (let q = 0; q < nmin; q++) {
            const r = mins[q];
            const m = eqs[r].mineral;
            if (!xs[c]) { out[c * nmin + q] = present[c * ne + r] === 1 ? heldEvent(c, r, y[b + m]) : -1; continue; }
            if (present[c * ne + r] === 1) { out[c * nmin + q] = heldEvent(c, r, Cstar[b + m]); continue; }
            const eq = eqs[r];
            let g = -lnKAtP(eq, c, water);
            for (const [sp, nu] of eq.net) {
              if (isMin[sp]) continue;
              g += nu * Math.log(Math.max(Cstar[b + sp], 1e-300));
              if (act) g += nu * lnG[sp];
            }
            if (act && eq.water) g += eq.water * water.lnAw;
            // At its lower bound the water's saturation, crossing as it is supersaturated; at its upper the other way.
            out[c * nmin + q] = (present[c * ne + r] === 4 ? -1 : 1) * (eq.mineralNu < 0 ? 1 : -1) * g;
          }
          grps.forEach((bub, g) => {
            const at = nc * nmin + c * ngrp + g;
            if (!xs[c]) out[at] = present[c * ne + bub.rel[0]] ? -groupN(bub, y, b) : -1;
            else if (present[c * ne + bub.rel[0]]) out[at] = -groupN(bub, Cstar, b);
            else { out[at] = bubbleExcessAt(bub, Cstar, b, water); formAt[c * ngrp + g] = bub.formMode; }
          });
          bins.forEach((G, i) => {
            out[gapStart + c * nbin + i] = xs[c] ? gapValue(G, i, c, Cstar, b, water, (q) => Cstar[b + G.mem[q]]) : -1;
          });
        }
        return kinSiteValues(y, out);
      }
      concentrations(y);
      for (let c = 0; c < nc; c++) {
        const b = c * ns;
        let water = null;
        let ready = !act;
        for (let q = 0; q < nmin; q++) {
          const r = mins[q];
          const m = eqs[r].mineral;
          if (present[c * ne + r] === 1) { out[c * nmin + q] = heldEvent(c, r, y[b + m]); continue; }
          if (!ready) { water = activityAt(act, C, b, lnG, dG); ready = true; }
          out[c * nmin + q] = (present[c * ne + r] === 4 ? -1 : 1) * (eqs[r].mineralNu < 0 ? 1 : -1) * relationAt(b, r, y, water);
        }
        grps.forEach((bub, g) => {
          const at = nc * nmin + c * ngrp + g;
          if (present[c * ne + bub.rel[0]]) out[at] = -groupN(bub, y, b);
          else {
            if (!ready) { water = activityAt(act, C, b, lnG, dG); ready = true; }
            out[at] = bubbleExcessAt(bub, C, b, water);
            formAt[c * ngrp + g] = bub.formMode;
          }
        });
        bins.forEach((G, i) => {
          if (!ready) { water = activityAt(act, C, b, lnG, dG); ready = true; }
          out[gapStart + c * nbin + i] = gapValue(G, i, c, C, b, water, (q) => y[b + G.mem[q]]);
        });
      }
      return kinSiteValues(y, out);
    }
    function applyEvent(which) {
      if (which >= ksStart) {
        const c = Math.floor((which - ksStart) / nks);
        const m = kinSites[(which - ksStart) % nks];
        throw new RtmError(`${base.speciesNames[m]} has dissolved away${where(c)}${goneWith(m)}`);
      }
      if (which >= gapStart) {
        const q = which - gapStart;
        const c = Math.floor(q / nbin);
        const G = bins[q % nbin];
        const next = present[c * ne + G.rel[0]] === 2 ? exitAt[q] || 1 : 2;
        for (const r of G.rel) present[c * ne + r] = next;
        lastEvent = { c, r: -1, which };
        events[which].shown = next === 2 ? `${G.def.name} comes to its miscibility gap${where(c)}`
          : `${G.def.name} leaves its miscibility gap${where(c)}`;
        return Array.from(G.mem, (g) => base.speciesNames[g]);
      }
      if (which >= nc * nmin) {
        const c = Math.floor((which - nc * nmin) / ngrp);
        const g = (which - nc * nmin) % ngrp;
        const bub = grps[g];
        lastEvent = { c, r: -1, which };
        const now = present[c * ne + bub.rel[0]] ? 0 : (formAt[c * ngrp + g] || 1);
        for (const r of bub.rel) present[c * ne + r] = now;
        events[which].shown = bub.def.kind === 'gas'
          ? (now ? `a bubble forms${where(c)}` : `the bubble has dissolved${where(c)}`)
          : (now ? `the solid solution ${bub.def.name} precipitates${where(c)}`
            : `the solid solution ${bub.def.name} has dissolved away${where(c)}`);
        return Array.from(bub.mem, (g) => base.speciesNames[g]);
      }
      const c = Math.floor(which / nmin);
      const r = mins[which % nmin];
      const at = c * ne + r;
      const was = present[at];
      // Held, it goes to the bound it came to; at one, it is held again.
      present[at] = was === 1 ? (nearHi[at] ? 4 : 0) : 1;
      lastEvent = { c, r: present[at] === 1 ? r : -1, which };
      const name = base.speciesNames[eqs[r].mineral];
      /*
        A mineral that carries a surface's sites or an exchanger's (per=,
        surfaceSetup, exchangeSetup) takes them with it as it goes: a surface
        or an exchanger with none is none the page carries.
      */
      if (present[at] === 0 && eqs[r].carry) {
        throw new RtmError(`${name} has dissolved away${where(c)}${goneWith(eqs[r].mineral)}`);
      }
      // Under precipitate_only, what precipitated beside what the cell started with gone, that is left (model.inert).
      const setAside = inertOf.some((x) => x.k === eqs[r].mineral && x.amounts[c] > 0);
      events[which].shown = present[at] === 4 ? `${name} is back at what it started with${where(c)}, and precipitates no more`
        + ' (dissolve_only)'
        : present[at] === 0 ? (setAside ? `${name} is back at what it started with${where(c)}, and dissolves no more `
          + '(precipitate_only)' : `${name} has dissolved away${where(c)}`)
          : was === 4 ? `${name} dissolves${where(c)}` : `${name} precipitates${where(c)}`;
      return [name];
    }
    /*
      Each run starts from the state: some of a mineral is there or none is;
      a bubble, or none; a solid solution, and which side of its gap -- at
      the temperatures of t = 0, where a run starts, and not those of the
      end of the run before, which the gap may not be there at.
    */
    const resetModes = (y) => {
      thermoAt(0);
      for (let c = 0; c < nc; c++) {
        for (const r of mins) present[c * ne + r] = modeOf(c, r, y[c * ns + eqs[r].mineral]);
        for (const bub of grps) {
          const v = groupMode(bub, (q) => y[c * ns + bub.mem[q]], c);
          for (const r of bub.rel) present[c * ne + r] = v;
        }
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
      ...(nmin || nbub || nks ? {
        nevents: nc * nmin + nbub + nc * nbin + nc * nks,
        eventDirections: new Int8Array(nc * nmin + nbub + nc * nbin + nc * nks).fill(1),
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
      heldEquilibria: { relations: ne, totals: nb, species: na, minerals: nmin,
        bubble: grps.filter((G) => G.def.kind === 'gas').reduce((acc, G) => acc + G.rel.length, 0),
        solidSolutions: grps.filter((G) => G.def.kind === 'ss').length },
      density: nnz / (n * n),
    };
  }

  /** Levenshtein's distance between two short names: how many letters put in, taken out or changed. */
  function nameDistance(a, b) {
    let prev = Array.from({ length: b.length + 1 }, (_, j) => j);
    for (let i = 1; i <= a.length; i++) {
      const cur = [i];
      for (let j = 1; j <= b.length; j++) {
        cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
      }
      prev = cur;
    }
    return prev[b.length];
  }

  /*
    LIKELY MISTAKES IN THE REACTION LINES, said as warnings, nothing refused.
    A line whose charges do not balance -- a source or a sink, a side with
    nothing on it, aside -- each species' charge its z=, else its name's. A
    line whose elements do not balance: a reaction moves atoms from one
    species to another and makes none, and one that takes an element and
    gives it back nowhere -- UO2CO3 + H2 + E_site => H+ + H+ + E_site, its
    uranium, oxygen and carbon -- has most likely lost a product. Counted by
    the names that are formulas of the elements (elementsOf); a line is left
    alone where it moves one that is not -- a name with a symbol that is no
    element (Hr, OHr, X, E_site), a lone symbol with no count and no charge
    (B for a species B, as the textbook models write them), or a nuclide,
    which a decay turns into another element on purpose -- unless that name
    is on both sides as much, a catalyst; the electron carries no atom. A
    line short only of water, two H to each O, is let be: a model that does
    not count its water writes its lines so. And
    a species a line uses up that nothing starts, brings in at an end, makes
    or forms in a relation, which that line's rate does not read, neither its
    concentration nor its activity: it can only go below nought, and is most
    likely a name mistyped -- UVIO2s+ for the UVIO2s+2 the rate reads. The
    names within two letters of it are offered, those the rate reads first.
  */
  function checkReactionLines(species, index, nameOf, reactions, channels, aqList, equilibria, patches, warnings, fixes = []) {
    // What a line takes of each element on its left and gives on its right, where they differ, in words: '' where they do not,
    // or where the line cannot be judged (see above).
    const elementsOff = (rx) => {
      const net = new Map();
      for (const [c, name] of rx.reactants) net.set(name, (net.get(name) || 0) - c);
      for (const [c, name] of rx.products) net.set(name, (net.get(name) || 0) + c);
      const moves = [...net.values()].filter((c) => Math.abs(c) > 1e-12);
      if (!moves.some((c) => c < 0) || !moves.some((c) => c > 0)) return '';
      const formula = new Map();
      for (const name of net.keys()) {
        const sp = species[index.get(name)];
        if (sp && sp.electron) { formula.set(name, new Map()); continue; }
        const els = /^[A-Z][a-z]?$/.test(String(name).replace(/\(g\)$/, '')) || nuclideOf(name) ? null : elementsOf(name);
        if (els && [...els.keys()].every((el) => ATOMIC_WEIGHTS[el])) formula.set(name, els);
        else if (Math.abs(net.get(name)) > 1e-12) return '';
      }
      const order = [];
      const count = (side) => {
        const out = new Map();
        for (const [c, name] of side) {
          for (const [el, n] of formula.get(name) || []) {
            if (!order.includes(el)) order.push(el);
            out.set(el, (out.get(el) || 0) + c * n);
          }
        }
        return out;
      };
      const take = count(rx.reactants);
      const give = count(rx.products);
      const off = order.filter((el) => {
        const a = take.get(el) || 0;
        const b = give.get(el) || 0;
        return Math.abs(a - b) > 1e-9 * Math.max(1, a, b);
      });
      if (!off.length) return '';
      // Short only of water, two H to each O, as a model that does not count its water writes a line: let be.
      const by = (el) => (take.get(el) || 0) - (give.get(el) || 0);
      if (off.every((el) => el === 'H' || el === 'O') && Math.abs(by('H') - 2 * by('O')) <= 1e-9 * Math.max(1, Math.abs(by('H')))) return '';
      const list = (xs) => (xs.length < 2 ? xs.join('') : `${xs.slice(0, -1).join(', ')} and ${xs[xs.length - 1]}`);
      const says = (side) => {
        const xs = off.filter((el) => side.get(el)).map((el) => `${Number(side.get(el).toPrecision(6))} ${el}`);
        return xs.length ? list(xs) : 'none';
      };
      return `${says(take)} on the left, against ${says(give)} on the right`;
    };
    const zOf = (name) => {
      const sp = species[index.get(name)];
      return sp && sp.z !== null && sp.z !== undefined ? sp.z : chargeOf(name);
    };
    const signed = (z) => `${z > 0 ? '+' : ''}${Number(z.toPrecision(6))}`;
    for (const rx of reactions) {
      if (!rx.reactants.length || !rx.products.length) continue;
      const sum = (side) => side.reduce((acc, [c, name]) => acc + c * zOf(name), 0);
      const left = sum(rx.reactants);
      const right = sum(rx.products);
      if (Math.abs(left - right) > 1e-9 * Math.max(1, Math.abs(left), Math.abs(right))) {
        warnings.push(`Line ${rx.line}: the charges do not balance, ${signed(left)} on the left and ${signed(right)} on the right.`);
      }
      const off = elementsOff(rx);
      if (off) warnings.push(`Line ${rx.line}: the elements do not balance, ${off}.`);
    }
    // What can be there at some time: started, brought in, held, made by a reaction or formed in a relation.
    const there = Uint8Array.from(species, (sp) => (sp.initial !== 0 || (sp.left !== null && sp.left !== 0)
      || (sp.right !== null && sp.right !== 0) || sp.fixed || sp.mineral || sp.surface || sp.exchange || sp.exchanger
      || sp.electron || sp.potential || sp.gas ? 1 : 0));
    for (const p of patches) if (p.si >= 0) there[p.si] = 1;
    for (const eq of equilibria) for (const [k] of eq.net) there[k] = 1;
    for (const ch of channels) for (const [i, c] of ch.net) if (c > 0) there[i] = 1;
    const told = new Set();
    for (const rx of reactions) {
      for (let q = rx.chanFirst; q < rx.chanFirst + rx.chanCount; q++) {
        const ch = channels[q];
        const reads = new Set(ch.deps.map((d) => d.si));
        for (const a of ch.aq) if (aqList[a.q] && aqList[a.q].kind === 'a') reads.add(aqList[a.q].s);
        for (const [i, c] of ch.net) {
          if (c >= 0 || there[i] || reads.has(i) || (ch.whole && ch.capOf === i) || told.has(`${rx.line}|${i}`)) continue;
          told.add(`${rx.line}|${i}`);
          const near = (pool) => pool.filter((k) => k !== i && nameDistance(nameOf[k], nameOf[i]) <= 2)
            .sort((a, b) => nameDistance(nameOf[a], nameOf[i]) - nameDistance(nameOf[b], nameOf[i]));
          const read = near([...reads]);
          const meant = (read.length ? read : near(nameOf.map((_, k) => k))).slice(0, 3).map((k) => nameOf[k]);
          warnings.push(`Line ${rx.line}: ${nameOf[i]} is used up by the reaction, and nothing starts it, brings it in or `
            + `makes it, nor does the rate read it: it can only go below nought.${meant.length
              ? ` Is it ${meant.join(' or ')}${read.length ? ', which the rate reads' : ''}?` : ''}`);
          if (meant.length) fixes.push({ line: rx.line, name: nameOf[i], meant });
        }
      }
    }
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
    /*
      Ridders' method, for a disagreement looked at again: the central
      difference of column c at the step h and at steps shrinking by 1.4 each
      time, RIDDERS_LEVELS of them, and for each row the differences
      extrapolated to a step of nought through a Neville tableau -- taking
      away h^2, h^4 and on as far as they go -- stopping where rounding
      begins to grow faster than the extrapolation gains. { value, err } of
      row r, the column's differences worked out once, when it first has a
      disagreement.
    */
    const RIDDERS_LEVELS = 10;
    const RIDDERS_SHRINK = 1.4;
    let riddersCol = -1;
    let riddersD = null;
    const ridders = (c, h, r) => {
      if (riddersCol !== c) {
        riddersCol = c;
        riddersD = [];
        let hh = h;
        for (let i = 0; i < RIDDERS_LEVELS; i++) {
          yp[c] = y[c] + hh;
          model.rhs(t, yp, fp2);
          yp[c] = y[c] - hh;
          model.rhs(t, yp, fm2);
          yp[c] = y[c];
          const d = new Float64Array(n);
          let finite = true;
          for (let q = 0; q < n; q++) {
            d[q] = (fp2[q] - fm2[q]) / (2 * hh);
            if (!Number.isFinite(d[q])) finite = false;
          }
          if (!finite) break;
          riddersD.push(d);
          hh /= RIDDERS_SHRINK;
        }
      }
      if (!riddersD.length) return null;
      const shrink2 = RIDDERS_SHRINK * RIDDERS_SHRINK;
      let prev = [riddersD[0][r]];
      let value = prev[0];
      let err = Infinity;
      for (let i = 1; i < riddersD.length; i++) {
        const col = [riddersD[i][r]];
        let fac = shrink2;
        for (let j = 1; j <= i; j++) {
          col[j] = (col[j - 1] * fac - prev[j - 1]) / (fac - 1);
          fac *= shrink2;
          const e = Math.max(Math.abs(col[j] - col[j - 1]), Math.abs(col[j] - prev[j - 1]));
          if (e <= err) { err = e; value = col[j]; }
        }
        // Rounding has taken over once the diagonal moves by more than twice the best error.
        if (Math.abs(col[i] - prev[i - 1]) >= 2 * err) break;
        prev = col;
      }
      return { value, err };
    };
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
          A disagreement is looked at again before it is reported, by
          Ridders' method (above): steps shrinking from h, extrapolated to
          nought. Where the entry's function bends on a scale not far above
          the step, the central difference's h^2 and on are the disagreement
          -- a limited advection's slope where the gradients are a few times
          what the step moves them by; a Langmuir-Hinshelwood factor
          8.1e4[H2]/(8.1e4[H2] + 1) at [H2] = 0, which turns over at 1.2e-5
          against a step of 3.4e-6, its difference 8 % out and one halving
          extrapolated still 0.5 %. The tableau reaches the analytic entry; a
          Jacobian that is wrong stays wrong.
        */
        // The difference reported is the tableau's, the nearest to the derivative there is.
        let best = numeric;
        if (step === 2 * h) {
          const est = ridders(c, h, r);
          if (est) {
            best = est.value;
            const tol2 = Math.max(rtol * Math.max(Math.abs(analytic), Math.abs(est.value)), floor);
            if (Math.abs(analytic - est.value) <= tol2) continue;
          }
        }
        discrepancies.push({ row: r, col: c, analytic, numeric: best });
      }
    }
    return { checked, unresolvable, discrepancies, outsidePattern: outside };
  }

  /**
   * The eigenvalues and eigenvectors of a symmetric matrix, by Jacobi's
   * rotations, each turning the matrix so that one pair off the diagonal is
   * zero, swept over every pair until what is left off the diagonal is
   * rounding. Returns { values, vectors }, vectors[k][j] the k-th entry of
   * the j-th vector, in no particular order.
   */
  function symmetricEigen(A) {
    const q = A.length;
    const a = A.map((row) => Float64Array.from(row));
    const v = Array.from({ length: q }, (_, i) => Float64Array.from({ length: q }, (_, j) => (i === j ? 1 : 0)));
    let scale = 0;
    for (let i = 0; i < q; i++) for (let j = 0; j < q; j++) scale = Math.max(scale, Math.abs(a[i][j]));
    for (let sweep = 0; sweep < 100; sweep++) {
      let off = 0;
      for (let i = 0; i < q; i++) for (let j = i + 1; j < q; j++) off = Math.max(off, Math.abs(a[i][j]));
      if (!(off > 1e-17 * scale)) break;
      for (let p = 0; p < q; p++) {
        for (let r = p + 1; r < q; r++) {
          if (!(Math.abs(a[p][r]) > 1e-300)) continue;
          const theta = (a[r][r] - a[p][p]) / (2 * a[p][r]);
          const t = (theta >= 0 ? 1 : -1) / (Math.abs(theta) + Math.sqrt(theta * theta + 1));
          const c = 1 / Math.sqrt(t * t + 1);
          const sn = t * c;
          for (let k = 0; k < q; k++) {
            const kp = a[k][p];
            const kr = a[k][r];
            a[k][p] = c * kp - sn * kr;
            a[k][r] = sn * kp + c * kr;
          }
          for (let k = 0; k < q; k++) {
            const pk = a[p][k];
            const rk = a[r][k];
            a[p][k] = c * pk - sn * rk;
            a[r][k] = sn * pk + c * rk;
          }
          for (let k = 0; k < q; k++) {
            const kp = v[k][p];
            const kr = v[k][r];
            v[k][p] = c * kp - sn * kr;
            v[k][r] = sn * kp + c * kr;
          }
        }
      }
    }
    return { values: a.map((row, i) => row[i]), vectors: v.map((row) => Array.from(row)) };
  }

  /**
   * PRINCIPAL COMPONENTS of a table of waters, as Gibbs Studio gives them:
   * X has a row for each water and a column for each thing measured of it.
   * Each column is standardised -- its mean taken off and the rest divided by
   * its standard deviation (n - 1) -- so that a pH and a total weigh alike,
   * and the components are the eigenvectors of the columns' correlation
   * matrix, largest eigenvalue first, each turned so that its largest entry
   * is positive. A column that does not vary is left out: one whose standard
   * deviation is no more than 1e-12 of its size.
   *
   * Returns { kept: the columns used, mean, sd, values: the eigenvalues,
   * which sum to the number of columns kept; explained: each one's share of
   * that; vectors: q x q, vectors[k][j] column k's loading on component j;
   * scores: n x q, each water's coordinates on the components; project(row):
   * another water's scores, standardised by these columns' means and
   * deviations }.
   */
  function pca(X, opts = {}) {
    const n = X.length;
    const p = n ? X[0].length : 0;
    if (n < 3) throw new RtmError('Principal components need three waters or more.');
    const mean = new Float64Array(p);
    const sd = new Float64Array(p);
    for (let j = 0; j < p; j++) {
      let s = 0;
      for (let i = 0; i < n; i++) s += X[i][j];
      mean[j] = s / n;
      let v = 0;
      for (let i = 0; i < n; i++) v += (X[i][j] - mean[j]) ** 2;
      sd[j] = Math.sqrt(v / (n - 1));
    }
    const kept = [];
    for (let j = 0; j < p; j++) {
      if (!Number.isFinite(mean[j])) throw new RtmError(`${(opts.names && opts.names[j]) || `Column ${j + 1}`} has a value that is no number.`);
      if (sd[j] > 1e-12 * Math.max(Math.abs(mean[j]), 1e-300)) kept.push(j);
    }
    const q = kept.length;
    if (q < 2) throw new RtmError('Principal components need two things that vary from one water to another, and these waters have '
      + `${q === 1 ? 'one' : 'none'}.`);
    const Z = X.map((row) => kept.map((j) => (row[j] - mean[j]) / sd[j]));
    const R = Array.from({ length: q }, () => new Float64Array(q));
    for (let a = 0; a < q; a++) {
      for (let b = a; b < q; b++) {
        let s = 0;
        for (let i = 0; i < n; i++) s += Z[i][a] * Z[i][b];
        R[a][b] = s / (n - 1);
        R[b][a] = R[a][b];
      }
    }
    const eig = symmetricEigen(R);
    const order = eig.values.map((_, j) => j).sort((a, b) => eig.values[b] - eig.values[a]);
    const values = order.map((j) => Math.max(0, eig.values[j]));
    const vectors = Array.from({ length: q }, () => new Array(q));
    order.forEach((j, col) => {
      let big = 0;
      for (let k = 0; k < q; k++) if (Math.abs(eig.vectors[k][j]) > Math.abs(eig.vectors[big][j])) big = k;
      const sign = eig.vectors[big][j] < 0 ? -1 : 1;
      for (let k = 0; k < q; k++) vectors[k][col] = sign * eig.vectors[k][j];
    });
    const scoresOf = (z) => Array.from({ length: q }, (_, col) => {
      let s = 0;
      for (let k = 0; k < q; k++) s += z[k] * vectors[k][col];
      return s;
    });
    return {
      kept, mean: kept.map((j) => mean[j]), sd: kept.map((j) => sd[j]), values, explained: values.map((v) => v / q), vectors,
      scores: Z.map(scoresOf),
      project: (row) => scoresOf(kept.map((j) => (row[j] - mean[j]) / sd[j])),
    };
  }

  return { compile, verifyJacobian, speciate, conservationBasis, RtmError, parseReaction,
    chargeOf, debyeHuckelAB, ehPerPe, activityModel, activityAt, prState, prAt, logKAt, binaryAt,
    pitzerJ: pzJ, pitzerEtheta: pzEtheta, pitzerParam, molarVolumes, lnKAtP, potentialRow,
    readSections, derivative, symmetricEigen, pca,
    // Where a name is used, and what has changed since the text was opened, for the lines under the model text.
    namesOf, nameAt, usesOf, lineChanges,
    // The vocabulary, for the editor's syntax colouring: what is coloured as
    // meaning something is exactly what means something here.
    SECTIONS, SETTINGS, readTime, elementsOf, formulaMass, ATOMIC_WEIGHTS, readData, withValue, valueIn, tunables, waterViscosity };
}));
