/* ==========================================================================
   RTM.HTML AND PHREEQC: A WATER INTO A MODEL, AND A RUN BACK OUT

   PHREEQC (Parkhurst and Appelo, USGS) does what rtm.html does not: a
   thermodynamic database, activity coefficients, ion pairs, saturation. This
   passes waters between the two, both ways:

     waterToModel  PHREEQC speciates a water -- from its analysis, or after
                   whatever else its input does to it -- and the water as
                   PHREEQC leaves it becomes the <SPECIES> and <EQUILIBRIUM>
                   of a model: every aqueous species at PHREEQC's molality,
                   every complexation and acid-base reaction as the database
                   writes it, and, held exactly, each species written with
                   electrons tied to the electron by its reaction, so that
                   the couples share one pe as in PHREEQC -- the water then
                   PHREEQC's next step, where it was given as an analysis --
                   or else no redox relation, each valence state keeping its
                   own total. An exchanger in the input comes too, with the
                   species PHREEQC put on it. The
                   relations hold between activities that follow the ionic
                   strength (ACTIVITY, the database's own log K and -gamma),
                   or each has a CONDITIONAL log K (the activity
                   coefficients at this ionic strength and the activity of
                   water folded in).

     viewRun       every stored water of a run goes back to PHREEQC: the
                   species its database has are counted into the element
                   totals PHREEQC takes, the pH is walked until PHREEQC's
                   molality of H+ is the run's [H+], and out come the pH as
                   an activity, the ionic strength, the charge balance, the
                   saturation index of every phase, and how far the activity
                   coefficients of the model's own equilibria drifted from
                   where its conditional constants were made -- or, for a
                   model with ACTIVITY, how closely its own follow PHREEQC's
                   -- and how closely its exchanger holds what PHREEQC
                   would load from the same water.

   PHREEQC itself is an ENGINE handed in: { run(text) } returning the rows of
   selected output 99, header first, or throwing PHREEQC's error. In the page
   it is IPhreeqc compiled to WebAssembly (vendors/phreeqc); in a test it can
   be any PHREEQC.

   The database is read here as well, but only for what PHREEQC's BASIC
   cannot hand back: each species' reaction as written, the master species of
   each element and valence state, the tracer diffusion coefficients, and
   which species have -gamma (DH_A0 and DH_BDOT give a and b, but not whether
   a species is Davies or WATEQ).

   ONE GLOBAL: RtmPhreeqc. Runs in a page, a Worker and Node.
   ========================================================================== */
(function (root, factory) {
  const api = factory();
  root.RtmPhreeqc = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  /* ======================================================================
     Reading a PHREEQC database
     ====================================================================== */

  /** Words that start a keyword block in a database or an input file. */
  const KEYWORDS = new Set([
    'SOLUTION_MASTER_SPECIES', 'SOLUTION_SPECIES', 'PHASES', 'EXCHANGE_MASTER_SPECIES',
    'EXCHANGE_SPECIES', 'SURFACE_MASTER_SPECIES', 'SURFACE_SPECIES', 'RATES', 'END',
    'LLNL_AQUEOUS_MODEL_PARAMETERS', 'NAMED_EXPRESSIONS', 'ISOTOPES', 'ISOTOPE_RATIOS',
    'ISOTOPE_ALPHAS', 'CALCULATE_VALUES', 'PITZER', 'SIT', 'SOLUTION', 'SOLUTION_SPREAD',
    'EQUILIBRIUM_PHASES', 'KINETICS', 'REACTION', 'REACTION_TEMPERATURE', 'REACTION_PRESSURE',
    'SELECTED_OUTPUT', 'USER_PUNCH', 'USER_PRINT', 'USER_GRAPH', 'TITLE', 'DATABASE', 'KNOBS',
    'MIX', 'GAS_PHASE', 'SOLID_SOLUTIONS', 'SURFACE', 'EXCHANGE', 'SAVE', 'USE', 'GAS_BINARY_PARAMETERS',
    'INCREMENTAL_REACTIONS', 'TRANSPORT', 'ADVECTION', 'PRINT', 'INVERSE_MODELING', 'COPY',
    'DELETE', 'RUN_CELLS', 'DUMP', 'MEAN_GAMMAS', 'SOLUTION_MODIFY', 'EQUILIBRIUM_PHASES_MODIFY',
    'EXCHANGE_MODIFY', 'SURFACE_MODIFY', 'KINETICS_MODIFY', 'GAS_PHASE_MODIFY',
    'SOLID_SOLUTIONS_MODIFY', 'REACTION_MODIFY', 'SOLUTION_RAW', 'EQUILIBRIUM_PHASES_RAW',
    'EXCHANGE_RAW', 'SURFACE_RAW', 'KINETICS_RAW', 'GAS_PHASE_RAW', 'SOLID_SOLUTIONS_RAW',
    'REACTION_RAW', 'MIX_RAW', 'REACTION_TEMPERATURE_RAW', 'REACTION_PRESSURE_RAW',
    'INCLUDE$', 'SOLUTION_MIX', 'EXCHANGE_MIX', 'GAS_PHASE_MIX', 'KINETICS_MIX',
    'PPASSEMBLAGE_MIX', 'SSASSEMBLAGE_MIX', 'SURFACE_MIX', 'POLYMER', 'RATE_PARAMETERS_PK',
    'RATE_PARAMETERS_SVD', 'RATE_PARAMETERS_HERMANSKA',
  ]);

  /** Never a species of the water: water itself, and PHREEQC's electron. */
  const NOT_A_SPECIES = new Set(['H2O', 'e-']);

  const COEF = /^([0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)(.*)$/;
  /** rtm.html's rule for a species name (rtm-model.js, SPECIES_NAME). */
  const RTM_NAME = /^[A-Za-z](?:[A-Za-z0-9_]|\([A-Za-z0-9_]+\))*(?:[+-][0-9]*)?$/;

  /**
   * PHREEQC's own lines: '#' starts a comment, ';' separates two lines, and
   * a backslash at the end carries a line on to the next.
   */
  function logicalLines(text) {
    const out = [];
    let buf = '';
    for (const raw of String(text).split(/\r\n|\r|\n/)) {
      let line = raw.split('#', 1)[0].replace(/\s+$/, '');
      if (line.endsWith('\\')) {
        buf += `${line.slice(0, -1)} `;
        continue;
      }
      line = buf + line;
      buf = '';
      out.push(...line.split(';'));
    }
    if (buf) out.push(buf);
    return out;
  }

  /**
   * One side of a reaction as {c, n} pairs, c signed. Read: '2.0000 UO2+2 +
   * 2.0000 H2O'; 'X +2.0000 H+' (a sign glued to the next coefficient);
   * '+1.000H2O -1.000H+' (signed terms, a minus meaning the species belongs
   * on the other side, as the NAGRA-PSI and SKB databases write them); and a
   * coefficient glued to its species, '2H2O'.
   */
  function parseSide(side) {
    const terms = [];
    let pending = null;
    let sign = 1;
    for (let tok of String(side).trim().split(/\s+/)) {
      if (!tok || tok === '+') continue;
      if (tok === '-') { sign = -sign; continue; }
      if ((tok[0] === '+' || tok[0] === '-') && tok.length > 1 && /[0-9.]/.test(tok[1])) {
        if (tok[0] === '-') sign = -sign;
        tok = tok.slice(1);
      }
      const m = COEF.exec(tok);
      let c;
      let n;
      if (m) {
        const num = Number(m[1]);
        if (m[2] === '') {
          pending = pending === null ? num : pending * num;
          continue;
        }
        c = num;
        n = m[2];
      } else {
        c = 1;
        n = tok;
      }
      if (pending !== null) { c *= pending; pending = null; }
      terms.push({ c: sign * c, n });
      sign = 1;
    }
    return terms;
  }

  /**
   * The reaction with every coefficient positive: a species written with a
   * minus moves to the other side, one on both sides is netted out, and the
   * species the reaction defines stays first on the right.
   */
  function normalise(left, right) {
    const defined = right[0].n;
    const net = new Map();
    const order = [];
    for (const { c, n } of left) { net.set(n, (net.get(n) || 0) - c); order.push(n); }
    for (const { c, n } of right) { net.set(n, (net.get(n) || 0) + c); order.push(n); }
    const lhs = [];
    const rhs = [{ c: net.get(defined), n: defined }];
    const seen = new Set();
    for (const n of order) {
      if (seen.has(n) || n === defined) continue;
      seen.add(n);
      const v = net.get(n);
      if (v < -1e-12) lhs.push({ c: -v, n });
      else if (v > 1e-12) rhs.push({ c: v, n });
    }
    return { left: lhs, right: rhs };
  }

  /** 'Fe(+3)' -> 'Fe', 'C(4)' -> 'C', 'Hdg' -> 'Hdg'. */
  function elementOf(label) {
    return String(label).split('(', 1)[0];
  }

  /** 'Fe(+2)' and 'Fe(2)' are one valence state; PHREEQC reports the second. */
  function normLabel(label) {
    return String(label).replace(/\(\+/g, '(');
  }

  /**
   * Atoms of `element` in a formula: H2 has 2 H, UO2(CO3)3-4 has 3 C. An
   * element is a capital letter and any lower-case letters or underscores
   * after it, as PHREEQC reads one.
   */
  function countAtoms(formula, element) {
    const body = String(formula).split(':', 1)[0].replace(/[+-][0-9.]*$/, '');
    let i = 0;
    function parse() {
      const counts = new Map();
      const add = (k, v) => counts.set(k, (counts.get(k) || 0) + v);
      while (i < body.length) {
        const ch = body[i];
        if (ch === '(') {
          i++;
          const inner = parse();
          const m = /^[0-9.]+/.exec(body.slice(i));
          const n = m ? Number(m[0]) : 1;
          i += m ? m[0].length : 0;
          for (const [k, v] of inner) add(k, v * n);
        } else if (ch === ')') {
          i++;
          return counts;
        } else if (ch >= 'A' && ch <= 'Z') {
          const name = /^[A-Z][a-z_]*/.exec(body.slice(i))[0];
          i += name.length;
          const m = /^[0-9.]+/.exec(body.slice(i));
          const n = m ? Number(m[0]) : 1;
          i += m ? m[0].length : 0;
          add(name, n);
        } else {
          i++;
        }
      }
      return counts;
    }
    return parse().get(element) || 0;
  }

  /** Every element of a formula and its atoms; 'CaSO4:2H2O' with its waters. */
  function atomsOf(formula) {
    const out = new Map();
    for (const part of String(formula).replace(/[+-][0-9.]*$/, '').split(':')) {
      const m = /^([0-9.]*)(.*)$/.exec(part.trim());
      const n = m[1] ? Number(m[1]) : 1;
      const els = new Set((m[2].match(/[A-Z][a-z_]*/g) || []));
      for (const el of els) out.set(el, (out.get(el) || 0) + n * countAtoms(m[2], el));
    }
    return out;
  }

  /**
   * A chemical formula's dissolution, as PHREEQC adds a kinetic reactant's
   * elements to the water: each element as its master species, the oxygen
   * left over as water, the hydrogen as H+, and the charge that leaves as
   * electrons -- CH2O is CO3-2 + 6 H+ + 4 e- less 2 H2O. A Map, species to
   * its coefficient, products positive.
   */
  function formulaReaction(formula, db) {
    const atoms = atomsOf(formula);
    if (!atoms.size) throw new Error(`"${formula}" is no phase or chemical formula`);
    const out = new Map();
    let O = atoms.get('O') || 0;
    let H = atoms.get('H') || 0;
    let charge = 0;
    for (const [el, n] of atoms) {
      if (el === 'H' || el === 'O') continue;
      const master = db.master.get(el);
      if (!master) throw new Error(`the database has no element ${el}, which ${formula} has`);
      const ma = atomsOf(master);
      if ([...ma.keys()].some((e) => e !== el && e !== 'H' && e !== 'O')) {
        throw new Error(`${el}'s master species, ${master}, has another element in it`);
      }
      const k = n / (ma.get(el) || 1);
      out.set(master, (out.get(master) || 0) + k);
      O -= k * (ma.get('O') || 0);
      H -= k * (ma.get('H') || 0);
      charge += k * chargeOf(master);
    }
    const water = O;
    const hplus = H - 2 * water;
    if (water) out.set('H2O', water);
    if (hplus) out.set('H+', hplus);
    // What the products' charge comes to, as electrons given up.
    const e = charge + hplus;
    if (Math.abs(e) > 1e-12) out.set('e-', e);
    return out;
  }

  /**
   * The name as rtm.html can write it. Most PHREEQC names already are; a
   * leading group is not, so (UO2)2(OH)2+2 becomes UO2_2(OH)2+2. `taken`
   * (a Map, name -> original) keeps two originals from landing on one name.
   */
  /** A species' charge as its name ends: H+ 1, SO4-2 -2; 0 for none. */
  function chargeOf(name) {
    const m = /([+-])([0-9]*)$/.exec(String(name));
    if (!m) return 0;
    return (m[1] === '+' ? 1 : -1) * (m[2] ? Number(m[2]) : 1);
  }

  /** A species' charge as its name ends, halves and all: Goe_uniOH-0.5 -0.5, Hfo_wOH2+ 1. */
  function chargeFraction(name) {
    const m = /([+-])([0-9]*\.?[0-9]*)$/.exec(String(name));
    if (!m) return 0;
    return (m[1] === '+' ? 1 : -1) * (m[2] && m[2] !== '.' ? Number(m[2]) : 1);
  }

  function rtmName(name, taken) {
    let out = String(name);
    if (!RTM_NAME.test(out)) {
      const m = /^\(([A-Za-z0-9_]+)\)([0-9]*)(.*)$/.exec(out);
      if (m) out = `${m[1]}_${m[2] || '1'}${m[3]}`;
    }
    if (!RTM_NAME.test(out)) {
      const m = /^(.*?)([+-][0-9]*)?$/.exec(out);
      let body = m[1].replace(/[^A-Za-z0-9_()]/g, '_');
      const charge = m[2] || '';
      if (!RTM_NAME.test(body + charge)) body = body.replace(/[()]/g, '_');
      if (!/^[A-Za-z]/.test(body)) body = `X${body}`;
      out = body + charge;
    }
    if (taken) {
      const base = /^(.*?)([+-][0-9]*)?$/.exec(out);
      let k = 2;
      while (taken.has(out) && taken.get(out) !== name) {
        out = `${base[1]}_${k}${base[2] || ''}`;
        k++;
      }
      taken.set(out, name);
    }
    return out;
  }

  /*
    A REACTION'S LOG K AND HOW IT GOES WITH TEMPERATURE, as PHREEQC reads it:
    the options of its read_species, read_phases, read_exchange_species,
    read_surface_species and read_named_logk, in their order. A word after a
    dash is the first option it begins, -l log_k, -d delta_h, -a the analytic
    expression; a word without one is the option it is, exactly.
  */
  const LK_OPTIONS = {
    SOLUTION_SPECIES: ['no_check', 'check', 'gamma', 'mb', 'mass_balance', 'log_k', 'logk', 'delta_h', 'deltah',
      'analytical_expression', 'a_e', 'ae', 'mole_balance', 'llnl_gamma', 'co2_llnl_gamma', 'activity_water',
      'add_logk', 'add_log_k', 'add_constant', 'dw', 'erm_ddl', 'millero', 'vm', 'viscosity'],
    PHASES: ['no_check', 'check', 'log_k', 'logk', 'delta_h', 'deltah', 'analytical_expression', 'a_e', 'ae',
      'add_logk', 'add_log_k', 'add_constant', 't_c', 'p_c', 'omega', 'vm'],
    EXCHANGE_SPECIES: ['no_check', 'check', 'mb', 'mass_balance', 'log_k', 'logk', 'delta_h', 'deltah',
      'analytical_expression', 'a_e', 'ae', 'mole_balance', 'gamma', 'davies', 'offset', 'llnl_gamma', 'add_logk',
      'add_log_k', 'add_constant', 'vm'],
    SURFACE_SPECIES: ['no_check', 'check', 'mb', 'mass_balance', 'log_k', 'logk', 'delta_h', 'deltah',
      'analytical_expression', 'a_e', 'ae', 'mole_balance', 'offset', 'add_logk', 'add_log_k', 'add_constant',
      'cd_music', 'music', 'vm'],
    NAMED_EXPRESSIONS: ['log_k', 'logk', 'delta_h', 'deltah', 'analytical_expression', 'a_e', 'ae', 'ln_alpha1000',
      'add_logk', 'add_log_k', 'vm'],
  };

  /** LLNL_AQUEOUS_MODEL_PARAMETERS's options in PHREEQC's order, and the table each fills. */
  const LLNL_OPTIONS = ['temperatures', 'temperature', 'temp', 'adh', 'debye_huckel_a', 'dh_a', 'bdh', 'debye_huckel_b',
    'dh_b', 'bdot', 'b_dot', 'c_co2', 'co2_coefs'];
  const LLNL_KINDS = { temperatures: 'temps', temperature: 'temps', temp: 'temps', adh: 'adh', debye_huckel_a: 'adh',
    dh_a: 'adh', bdh: 'bdh', debye_huckel_b: 'bdh', dh_b: 'bdh', bdot: 'bdot', b_dot: 'bdot', c_co2: 'co2', co2_coefs: 'co2' };

  /*
    PITZER's options in PHREEQC's read_pitzer order, the first a word after
    a dash begins, and what each parameter type is and how many species it
    names.
  */
  const PZ_OPTIONS = ['b0', 'b1', 'b2', 'c0', 'theta', 'lamda', 'zeta', 'psi', 'macinnes', 'macinnis', 'mac', 'redox',
    'pe', 'alphas', 'mu', 'eta', 'etheta', 'use_etheta', 'lambda', 'aphi'];
  const PZ_KINDS = { b0: ['B0', 2], b1: ['B1', 2], b2: ['B2', 2], c0: ['C0', 2], theta: ['THETA', 2], lamda: ['LAMBDA', 2],
    lambda: ['LAMBDA', 2], zeta: ['ZETA', 3], psi: ['PSI', 3], alphas: ['ALPHAS', 2], mu: ['MU', 3], eta: ['ETA', 3],
    aphi: ['APHI', 0] };

  /** The option a line of `block` is, as PHREEQC's get_option finds it, and the words after it; or null. */
  function lkOption(block, line) {
    const list = LK_OPTIONS[block];
    const s = String(line).trim();
    if (!list || !s) return null;
    const dashed = /^-[A-Za-z]/.test(s);
    const first = s.split(/\s+/)[0];
    const word = (dashed ? first.slice(1) : first).toLowerCase();
    const opt = dashed ? list.find((o) => o.startsWith(word)) : list.find((o) => o === word);
    if (!opt) return null;
    // PHREEQC reads its numbers with the first = taken for a space.
    return { opt, words: s.slice(first.length).replace('=', ' ').trim().split(/\s+/).filter(Boolean) };
  }

  /** The numbers at the start of `words`, as sscanf takes them: up to the first that is not one. */
  function leadingNumbers(words, most) {
    const out = [];
    for (const t of words.slice(0, most)) {
      const v = Number(t);
      if (t === '' || !Number.isFinite(v)) break;
      out.push(v);
    }
    return out;
  }

  /** PHREEQC's select_log_k_expression: an expression with a term not zero replaces log_k and delta_h. */
  function selectTerms(k) {
    return k.slice(2).some((v) => v !== 0) ? [0, 0, ...k.slice(2)] : [k[0], k[1], 0, 0, 0, 0, 0, 0];
  }

  /** Pure water's viscosity at 25 C, mPa s, that PHREEQC scales each species' Dw by (viscosity(), Huber et al. 2009). */
  const VISCOS_0_25 = 0.8900239182946;

  /** PHREEQC's R, kJ/(mol K) (R_KJ_DEG_MOL), and its k_calc: log K at tk kelvin of terms [logK, dH, A1 ... A6]. */
  const R_KJ = 0.00831470;
  function kCalc(k, tk) {
    const me = tk * R_KJ;
    return k[0] - k[1] * (298.15 - tk) / (Math.LN10 * me * 298.15)
      + k[2] + k[3] * tk + k[4] / tk + k[5] * Math.log10(tk) + k[6] / (tk * tk) + k[7] * tk * tk;
  }

  /**
   * What the hand-off needs from a database, and from any
   * SOLUTION_MASTER_SPECIES or SOLUTION_SPECIES in an input read after it,
   * which redefine as PHREEQC would.
   */
  class Database {
    constructor() {
      this.master = new Map();      // label -> master species: 'Fe(+3)' -> 'Fe+3'
      this.reaction = new Map();    // species -> {left, right}, right[0] the species
      this.dw = new Map();          // species -> tracer diffusion coefficient, m2/s
      this.dwT = new Map();         // species -> -dw's second value, its temperature dependence (dw_t)
      this.dwVisc = new Map();      // species -> -dw's seventh, the exponent on the viscosity (dw_a_v_dif)
      this.gamma = new Map();       // species -> {a, b}: its -gamma, the WATEQ Debye-Hueckel
      this.otherGamma = new Map();  // species -> an activity option this page does not have
      this.model = null;            // 'Pitzer', 'SIT' or 'LLNL' when the database is one of those
      this.phases = [];
      this.phaseReaction = new Map(); // phase -> {left, right}, its formula first on the left
      this.exMaster = new Map();    // exchanger label -> master species: 'X' -> 'X-'
      this.exReaction = new Map();  // exchange species -> {left, right}, right[0] the species
      this.exGamma = new Map();     // exchange species -> {a, b}: -gamma; Davies as a = b = 0
      this.sfMaster = new Map();    // surface site type -> master species: 'Hfo_w' -> 'Hfo_wOH'
      this.sfReaction = new Map();  // surface species -> {left, right}, right[0] the species
      // SIT's interaction coefficients, by kind and pair: 'eps Cl- Na+' -> {type, s1, s2, a},
      // a its temperature terms as PHREEQC reads them (sitParam); a pair given again replaces it.
      this.sit = new Map();
      // Pitzer's parameters, by type and species as a set: 'B0 Cl- Na+' -> {type, sp, a}, sp the species in the
      // order given and a its terms in the temperature, as PHREEQC reads them; one given again replaces it.
      this.pitzer = new Map();
      // LLNL_AQUEOUS_MODEL_PARAMETERS: its tables, and each species' -llnl_gamma a, -co2_llnl_gamma, and an
      // exchange species' -llnl_gamma.
      this.llnl = { temps: [], adh: [], bdh: [], bdot: [], co2: [] };
      this.llnlGamma = new Map();
      this.co2Gamma = new Set();
      this.exLlnl = new Map();
      // PITZER's options (PHREEQC's defaults: the MacInnes scaling, E-theta, and no redox) and its -Aphi.
      this.pitzerOpts = { macinnes: true, etheta: true, redox: false };
      this.aphi = null;
      // A phase's critical temperature (K) and pressure (atm) and acentric factor, where the database gives
      // them: PHREEQC then holds that gas in a gas phase by Peng and Robinson's equation of state.
      this.critical = new Map();
      // Molar volumes, for log K at the pressure: a species' -Vm (up to ten numbers, as written) and -Millero (up to
      // six), and a phase's -Vm, cm3/mol (read_aq_species_vm_parms, read_millero_abcdef, read_vm_only).
      this.vm = new Map();
      this.millero = new Map();
      this.phaseVm = new Map();
      // A surface species' -cd_music: the charges it puts on planes 0, 1 and 2 of a CD-MUSIC surface.
      this.sfCd = new Map();
      // GAS_BINARY_PARAMETERS: 'CO2(g) H2O(g)' (the pair, sorted) -> k.
      this.gasBinary = new Map();
      // Each reaction's log K as PHREEQC reads it, by 'kind name' -- s a solution species, p a phase, x a species on
      // an exchanger, f one on a surface -- {k: [log_k, delta_h in kJ/mol, A1 ... A6], add: [[name, coef]]}, add the
      // named expressions it adds in; NAMED_EXPRESSIONS by lower-case name, likewise. See logKTerms.
      this.lk = new Map();
      this.named = new Map();
    }

    /**
     * A reaction's log K terms, [log_k, delta_h, A1 ... A6], as PHREEQC puts
     * them together (tidy.cpp): its own, the analytic expression replacing
     * log_k and delta_h where it has one, and each named expression it adds,
     * times its coefficient -- the expression's analytic terms where it has
     * them, else its log_k and delta_h. Null where there is no reaction, or
     * one adds an expression the database does not name.
     */
    logKTerms(kind, name) {
      const e = this.lk.get(`${kind} ${name}`);
      if (!e) return null;
      const out = selectTerms(e.k);
      for (const [nm, coef] of e.add) {
        const n = this.namedTerms(nm, 0);
        if (!n) return null;
        if (n.slice(2).some((v) => v !== 0)) for (let j = 2; j < 8; j++) out[j] += n[j] * coef;
        else { out[0] += n[0] * coef; out[1] += n[1] * coef; }
      }
      return out;
    }

    /** A named expression's terms, with those it adds in (PHREEQC's add_logks); add_constant's is 1. */
    namedTerms(name, depth) {
      const key = String(name).toLowerCase();
      if (key === 'xconstantx') return [1, 0, 0, 0, 0, 0, 0, 0];
      const e = this.named.get(key);
      if (!e || depth > 15) return null;
      const out = selectTerms(e.k);
      for (const [nm, coef] of e.add) {
        const n = this.namedTerms(nm, depth + 1);
        if (!n) return null;
        for (let j = 0; j < 8; j++) out[j] += n[j] * coef;
      }
      return out;
    }

    /** One option line of a reaction's log K into its entry e: true where it was one. */
    readLogKOption(block, line, e) {
      const o = lkOption(block, line);
      if (!o || !e) return false;
      const v = leadingNumbers(o.words, 1)[0];
      switch (o.opt) {
        case 'log_k': case 'logk':
          if (Number.isFinite(v)) e.k[0] = v;
          return true;
        case 'delta_h': case 'deltah': {
          if (!Number.isFinite(v)) return true;
          // kJ/mol unless a unit says otherwise: not beginning with k, a thousandth; with a c in it, calories.
          let dh = v;
          const unit = o.words[1];
          if (unit && /^[A-Za-z]/.test(unit)) {
            const u = unit.toLowerCase();
            if (!u.startsWith('k')) dh /= 1000;
            if (u.includes('c')) dh *= 4.184;
          }
          e.k[1] = dh;
          return true;
        }
        case 'analytical_expression': case 'a_e': case 'ae': case 'ln_alpha1000': {
          const a = leadingNumbers(o.words, 6);
          if (!a.length) return true;
          for (let j = 0; j < 6; j++) e.k[2 + j] = j < a.length ? a[j] : 0;
          // 1000 ln alpha into log K: A1 to A5 over 1000 ln 10, and A6 as it stands, as PHREEQC has it.
          if (o.opt === 'ln_alpha1000') for (let j = 0; j < 5; j++) e.k[2 + j] /= 1000 * Math.LN10;
          return true;
        }
        case 'add_logk': case 'add_log_k':
          if (o.words.length) {
            const c = leadingNumbers(o.words.slice(1), 1)[0];
            e.add.push([o.words[0], Number.isFinite(c) ? c : 1]);
          }
          return true;
        case 'add_constant':
          if (Number.isFinite(v)) e.add.push(['XconstantX', v]);
          return true;
        case 'offset':
          if (Number.isFinite(v)) e.k[0] += v;
          return true;
        default:
          return false;
      }
    }

    /**
     * The binary parameter k of two gases as PHREEQC's
     * calc_gas_binary_parameter takes it: GAS_BINARY_PARAMETERS where it is
     * given, and otherwise PHREEQC's own for water vapour with CO2, H2S,
     * CH4, N2, ethane and propane; 0 for any other pair.
     */
    gasK(g1, g2) {
      const key = [g1, g2].sort().join(' ');
      if (this.gasBinary.has(key)) return this.gasBinary.get(key);
      const other = g1 === 'H2O(g)' ? g2 : g2 === 'H2O(g)' ? g1 : null;
      if (other === null || g1 === g2) return 0;
      if (['CO2(g)', 'H2S(g)', 'H2Sg(g)'].includes(other)) return 1 - 0.81;
      if (['CH4(g)', 'Mtg(g)', 'Methane(g)', 'N2(g)', 'Ntg(g)', 'Ethane(g)'].includes(other)) return 1 - 0.51;
      if (other === 'Propane(g)') return 1 - 0.45;
      return 0;
    }

    /**
     * `asDatabase`: the text is the database, which PHREEQC reads to its
     * first END and no further (read_database is one read_input): a block
     * after it is not in the database. An input is read whole.
     */
    read(text, asDatabase = false) {
      let block = null;
      let last = null;
      let sitType = null;
      let pzType = null;
      let llnlKey = null;
      let phase = null;
      for (const line of logicalLines(text)) {
        const tokens = line.trim().split(/\s+/).filter(Boolean);
        if (!tokens.length) continue;
        if (KEYWORDS.has(tokens[0].toUpperCase())) {
          block = tokens[0].toUpperCase();
          if (asDatabase && block === 'END') break;
          last = null;
          sitType = null;
          pzType = null;
          llnlKey = null;
          // Activity models other than the Debye-Hueckel ones this page has.
          if (block === 'PITZER') this.model = 'Pitzer';
          else if (block === 'SIT') this.model = 'SIT';
          else if (block === 'LLNL_AQUEOUS_MODEL_PARAMETERS') this.model = 'LLNL';
          continue;
        }
        if (block === 'SOLUTION_MASTER_SPECIES' && tokens.length >= 2) {
          this.master.set(tokens[0], tokens[1]);
        } else if (block === 'SOLUTION_SPECIES') {
          if (line.includes('=')) {
            const at = line.indexOf('=');
            const left = parseSide(line.slice(0, at));
            const right = parseSide(line.slice(at + 1));
            if (right.length && right[0].c > 0) {
              last = right[0].n;
              // 'Ca+2 = Ca+2' defines a master species and is kept as written.
              const identity = left.length === 1 && right.length === 1 && left[0].n === last;
              this.reaction.set(last, identity ? { left, right } : normalise(left, right));
              this.lk.set(`s ${last}`, { k: [0, 0, 0, 0, 0, 0, 0, 0], add: [] });
              // A reaction read again starts from PHREEQC's defaults: Davies
              // for an ion, 0.1 I for a neutral species.
              this.dw.delete(last);
              this.dwT.delete(last);
              this.dwVisc.delete(last);
              this.gamma.delete(last);
              this.otherGamma.delete(last);
              this.llnlGamma.delete(last);
              this.co2Gamma.delete(last);
              this.vm.delete(last);
              this.millero.delete(last);
            }
          } else if (last && this.readLogKOption(block, line, this.lk.get(`s ${last}`))) {
            // log_k, delta_h, the analytic expression or a named one: read.
          } else if (last && lkOption(block, line) && ['vm', 'millero'].includes(lkOption(block, line).opt)) {
            // A species' molar volume: -Vm's ten numbers, a1 to a4, W, b and i1 to i4, or -Millero's.
            const { opt, words } = lkOption(block, line);
            const v = leadingNumbers(words, opt === 'vm' ? 10 : 6);
            if (v.length) this[opt === 'vm' ? 'vm' : 'millero'].set(last, v);
          } else if (last && /^-?dw$/i.test(tokens[0]) && tokens.length > 1) {
            // Dw, dw_t, dw_a, dw_a2, dw_a_visc, dw_a3, dw_a_v_dif, as far as they are numbers (read.cpp).
            const all = tokens.slice(1).map(Number);
            const bad = all.findIndex((x) => !Number.isFinite(x));
            const v = bad < 0 ? all : all.slice(0, bad);
            if (v.length) {
              this.dw.set(last, v[0]);
              this.dwT.set(last, v[1] || 0);
              this.dwVisc.set(last, v[6] || 0);
            }
          } else if (last && /^-g(a(m(m(a)?)?)?)?$/i.test(tokens[0]) && tokens.length > 2) {
            const a = Number(tokens[1]);
            const b = Number(tokens[2]);
            if (Number.isFinite(a) && Number.isFinite(b)) {
              // The last of -gamma, -llnl_gamma and -co2_llnl_gamma is the species' rule, as PHREEQC's gflag.
              this.gamma.set(last, { a, b });
              this.llnlGamma.delete(last);
              this.co2Gamma.delete(last);
            }
          } else if (last && lkOption(block, line) && ['llnl_gamma', 'co2_llnl_gamma', 'activity_water']
            .includes(lkOption(block, line).opt)) {
            const { opt, words } = lkOption(block, line);
            if (opt === 'llnl_gamma') {
              const a = Number(words[0]);
              if (Number.isFinite(a)) { this.llnlGamma.set(last, a); this.co2Gamma.delete(last); this.gamma.delete(last); }
            } else if (opt === 'co2_llnl_gamma') {
              this.co2Gamma.add(last);
              this.llnlGamma.delete(last);
              this.gamma.delete(last);
            } else this.otherGamma.set(last, opt);
          }
        } else if (block === 'EXCHANGE_MASTER_SPECIES' && tokens.length >= 2) {
          this.exMaster.set(tokens[0], tokens[1]);
        } else if (block === 'EXCHANGE_SPECIES') {
          if (line.includes('=')) {
            const at = line.indexOf('=');
            const left = parseSide(line.slice(0, at));
            const right = parseSide(line.slice(at + 1));
            if (right.length && right[0].c > 0) {
              last = right[0].n;
              // 'X- = X-' defines the exchanger itself.
              const identity = left.length === 1 && right.length === 1 && left[0].n === last;
              if (identity) this.exReaction.delete(last); else this.exReaction.set(last, normalise(left, right));
              this.exGamma.delete(last);
              this.exLlnl.delete(last);
              this.lk.set(`x ${last}`, { k: [0, 0, 0, 0, 0, 0, 0, 0], add: [] });
            }
          } else if (last && this.readLogKOption(block, line, this.lk.get(`x ${last}`))) {
            // log_k, delta_h, the analytic expression, an offset or a named one: read.
          } else if (last && /^-g(a(m(m(a)?)?)?)?$/i.test(tokens[0]) && tokens.length > 2) {
            const a = Number(tokens[1]);
            const b = Number(tokens[2]);
            if (Number.isFinite(a) && Number.isFinite(b)) this.exGamma.set(last, { a, b });
          } else if (last && /^-dav(i(e(s)?)?)?$/i.test(tokens[0])) {
            this.exGamma.set(last, { a: 0, b: 0 });
          } else if (last && lkOption(block, line) && lkOption(block, line).opt === 'llnl_gamma') {
            const a = Number(lkOption(block, line).words[0]);
            if (Number.isFinite(a)) this.exLlnl.set(last, a);
          }
        } else if (block === 'SURFACE_MASTER_SPECIES' && tokens.length >= 2) {
          this.sfMaster.set(tokens[0], tokens[1]);
        } else if (block === 'SURFACE_SPECIES') {
          if (line.includes('=')) {
            const at = line.indexOf('=');
            const left = parseSide(line.slice(0, at));
            const right = parseSide(line.slice(at + 1));
            if (right.length && right[0].c > 0) {
              last = right[0].n;
              // 'Hfo_wOH = Hfo_wOH' defines a site's master species.
              const identity = left.length === 1 && right.length === 1 && left[0].n === last;
              if (identity) this.sfReaction.delete(last); else this.sfReaction.set(last, normalise(left, right));
              this.lk.set(`f ${last}`, { k: [0, 0, 0, 0, 0, 0, 0, 0], add: [] });
              this.sfCd.delete(last);
            }
          } else if (last && lkOption(block, line) && ['cd_music', 'music'].includes(lkOption(block, line).opt)) {
            /*
              CD-MUSIC: the charges the species puts on the planes 0, 1 and 2,
              from PHREEQC's five numbers -- dz0 + f z, dz1 + (1 - f) z and dz2,
              z a central ion's charge split between planes 0 and 1 (read.cpp).
            */
            const v = leadingNumbers(lkOption(block, line).words, 5);
            while (v.length < 5) v.push(0);
            this.sfCd.set(last, [v[0] + v[3] * v[4], v[1] + (1 - v[3]) * v[4], v[2]]);
          } else if (last) {
            this.readLogKOption(block, line, this.lk.get(`f ${last}`));
          }
        } else if (block === 'NAMED_EXPRESSIONS') {
          // A name on its own line, then its log K's options.
          if (tokens.length === 1 && !tokens[0].startsWith('-') && !lkOption(block, line)) {
            last = tokens[0].toLowerCase();
            this.named.set(last, { k: [0, 0, 0, 0, 0, 0, 0, 0], add: [] });
          } else if (last) {
            this.readLogKOption(block, line, this.named.get(last));
          }
        } else if (block === 'GAS_BINARY_PARAMETERS') {
          if (tokens.length >= 3 && Number.isFinite(Number(tokens[2]))) {
            this.gasBinary.set([tokens[0], tokens[1]].sort().join(' '), Number(tokens[2]));
          }
        } else if (block === 'LLNL_AQUEOUS_MODEL_PARAMETERS') {
          // An option, and its numbers on its line and the lines after it (read_llnl_aqueous_model_parameters).
          let rest = tokens;
          if (/^-[A-Za-z]/.test(tokens[0])) {
            const word = tokens[0].slice(1).toLowerCase();
            const opt = LLNL_OPTIONS.find((o) => o.startsWith(word));
            llnlKey = opt ? LLNL_KINDS[opt] : null;
            rest = tokens.slice(1);
          }
          if (!llnlKey) continue;
          for (const t of rest) {
            const v = Number(t);
            if (t === '' || !Number.isFinite(v)) break;
            this.llnl[llnlKey].push(v);
          }
        } else if (block === 'PITZER') {
          // An option starts a list of parameters, or is MacInnes, E-theta or redox and true or false (read_pitzer).
          if (/^-[A-Za-z]/.test(tokens[0])) {
            const word = tokens[0].slice(1).toLowerCase();
            const opt = PZ_OPTIONS.find((o) => o.startsWith(word));
            pzType = null;
            // PHREEQC's get_true_false: false where the word begins with an f, true otherwise or with none.
            const yes = !(tokens[1] && /^f/i.test(tokens[1]));
            if (opt === 'macinnes' || opt === 'macinnis' || opt === 'mac') this.pitzerOpts.macinnes = yes;
            else if (opt === 'redox' || opt === 'pe') this.pitzerOpts.redox = yes;
            else if (opt === 'etheta' || opt === 'use_etheta') this.pitzerOpts.etheta = yes;
            else if (opt) pzType = PZ_KINDS[opt];
            continue;
          }
          if (!pzType) continue;
          const [type, n] = pzType;
          const sp = tokens.slice(0, n);
          const a = leadingNumbers(tokens.slice(n), 6);
          if (sp.length < n || !a.length) continue;
          if (type === 'APHI') { this.aphi = a; continue; }
          const key = `${type} ${[...new Set(sp)].sort().join(' ')}`;
          this.pitzer.delete(key);
          this.pitzer.set(key, { type, sp, a });
        } else if (block === 'SIT') {
          // -epsilon and -epsilon1 start a list of pairs; PHREEQC takes the first option a shorter word begins.
          if (tokens[0].startsWith('-')) {
            const opt = tokens[0].slice(1).toLowerCase();
            sitType = opt && 'epsilon'.startsWith(opt) ? 'eps' : opt === 'epsilon1' ? 'eps1' : null;
            continue;
          }
          if (!sitType || tokens.length < 3) continue;
          const a = [];
          for (const t of tokens.slice(2, 8)) {
            const v = Number(t);
            if (!Number.isFinite(v)) break;
            a.push(v);
          }
          if (!a.length) continue;
          // PHREEQC keys a pair by its species as a set: either way round, and once for a species with itself.
          const key = `${sitType} ${[...new Set([tokens[0], tokens[1]])].sort().join(' ')}`;
          this.sit.delete(key);
          this.sit.set(key, { type: sitType, s1: tokens[0], s2: tokens[1], a });
        } else if (block === 'PHASES') {
          // A phase's name: the first word of a line that is no reaction and no option, as PHREEQC's
          // read_phases takes it -- phreeqc.dat has 'Willemite 289'.
          if (!line.includes('=') && !tokens[0].startsWith('-') && !lkOption(block, line)) {
            if (!this.phases.includes(tokens[0])) this.phases.push(tokens[0]);
            last = tokens[0];
            phase = tokens[0];
            this.critical.delete(phase);
            this.phaseVm.delete(phase);
            this.lk.set(`p ${phase}`, { k: [0, 0, 0, 0, 0, 0, 0, 0], add: [] });
          } else if (phase && this.readLogKOption(block, line, this.lk.get(`p ${phase}`))) {
            // log_k, delta_h, the analytic expression or a named one: read.
          } else if (phase && lkOption(block, line) && lkOption(block, line).opt === 'vm') {
            // A phase's molar volume, cm3/mol unless a unit after it says dm3 or m3 (read_vm_only).
            const { words } = lkOption(block, line);
            const v = leadingNumbers(words, 8);
            if (v.length) {
              const unit = (words[v.length] || '').toLowerCase();
              const f = unit.includes('cm3') ? 1 : unit.includes('dm3') ? 1e3 : unit.includes('m3') ? 1e6 : 1;
              this.phaseVm.set(phase, v[0] * f);
            }
          } else if (phase && /^-(t_c|p_c|omega)$/i.test(tokens[0]) && tokens.length > 1) {
            const v = Number(tokens[1]);
            if (Number.isFinite(v)) {
              const c = this.critical.get(phase) || { tc: 0, pc: 0, omega: 0 };
              c[{ '-t_c': 'tc', '-p_c': 'pc', '-omega': 'omega' }[tokens[0].toLowerCase()]] = v;
              this.critical.set(phase, c);
            }
          } else if (last && line.includes('=') && !tokens[0].startsWith('-')) {
            // The phase's reaction as written: its own formula, then whatever
            // else it takes, on the left; what it dissolves to on the right.
            const at = line.indexOf('=');
            this.phaseReaction.set(last, { left: parseSide(line.slice(0, at)), right: parseSide(line.slice(at + 1)) });
            last = null;
          }
        }
      }
      return this;
    }

    /**
     * The most specific label `species` is the master of: 'Fe(+2)' for Fe+2
     * where the database lists valence states, 'Na' for Na+.
     */
    masterLabel(species) {
      const labels = [];
      for (const [lb, sp] of this.master) if (sp === species) labels.push(lb);
      if (!labels.length) return null;
      const withState = labels.filter((lb) => lb.includes('('));
      return withState.length ? withState[0] : labels[0];
    }

    /** Whether the database writes `species` with electrons. */
    isRedox(species) {
      const r = this.reaction.get(species);
      return !!r && [...r.left, ...r.right.slice(1)].some((t) => t.n === 'e-');
    }

    /**
     * `species` as amounts of each element valence state, the way PHREEQC's
     * SOLUTION counts them: {'C(4)': 1} for HCO3-, {'U(+6)': 2} for
     * (UO2)2(OH)2+2, {'H(0)': 2} for H2. H+, H2O and e- are left out -- the
     * pH and the water are given otherwise -- and an electron left over
     * means the species could not be tied to a valence state ('e-' in the
     * result).
     */
    expand(species, seen) {
      if (species === 'H+' || species === 'H2O') return new Map();
      if (species === 'e-') return new Map([['e-', 1]]);
      const label = this.masterLabel(species);
      if (label !== null) {
        const el = elementOf(label);
        if (['H', 'H(1)', 'H(+1)', 'O', 'O(-2)'].includes(label)) return new Map();
        return new Map([[label, countAtoms(species, el) || 1]]);
      }
      const r = this.reaction.get(species);
      if (!r) throw new Error(`the database has no species ${species}`);
      const visited = new Set(seen || []);
      if (visited.has(species)) throw new Error(`${species} is defined in terms of itself`);
      visited.add(species);
      const out = new Map();
      const add = (k, v) => out.set(k, (out.get(k) || 0) + v);
      for (const { c, n } of r.left) for (const [k, v] of this.expand(n, visited)) add(k, c * v);
      for (const { c, n } of r.right.slice(1)) for (const [k, v] of this.expand(n, visited)) add(k, -c * v);
      const c0 = r.right[0].c;
      const res = new Map();
      for (const [k, v] of out) if (Math.abs(v) > 1e-12) res.set(k, v / c0);
      return res;
    }
  }

  /**
   * The phases of the EQUILIBRIUM_PHASES blocks of an input as PHREEQC's
   * read_pp_assemblage reads a line -- the phase, its saturation index (0
   * unless given), a word there the alternative formula or phase that
   * dissolves to hold it (`alt`), the amount, then d[issolve_only] or
   * p[recipitate_only] (`only`) -- with -force_equality on the line after
   * (`forced`), and anything else it says (`extra`). A phase named again
   * takes the later line.
   */
  function readAssemblage(text) {
    const out = new Map();
    let inBlock = false;
    let last = null;
    const num = (x) => x !== undefined && Number.isFinite(Number(x));
    for (const line of logicalLines(text)) {
      const tokens = line.trim().split(/\s+/).filter(Boolean);
      if (!tokens.length) continue;
      const word = tokens[0].toUpperCase();
      if (KEYWORDS.has(word)) { inBlock = word === 'EQUILIBRIUM_PHASES'; last = null; continue; }
      if (!inBlock) continue;
      if (tokens[0].startsWith('-')) {
        if (/^-f/i.test(tokens[0]) && last) last.forced = !/^f/i.test(tokens[1] || '');
        continue;
      }
      const a = { name: tokens[0], si: 0, alt: null, only: null, forced: false, extra: '' };
      let i = 1;
      if (num(tokens[i])) a.si = Number(tokens[i++]);
      if (tokens[i] !== undefined && /^[A-Za-z]/.test(tokens[i])) a.alt = tokens[i++];
      if (num(tokens[i])) i++;
      if (tokens[i] !== undefined && /^[dp]/i.test(tokens[i])) a.only = /^d/i.test(tokens[i++]) ? 'dissolve' : 'precipitate';
      a.extra = tokens.slice(i).join(' ');
      out.set(tokens[0], a);
      last = a;
    }
    return [...out.values()];
  }

  /**
   * The SURFACE blocks of an input: each site type's master species with its
   * sites (mol), and for the first of a surface its specific area (m2/g) and
   * mass (g), as PHREEQC reads `Hfo_wOH 2e-4 600 0.09`; and how the block is
   * electrostatic -- 'none' for -no_edl, 'ddl' by default -- with anything
   * else it says that this page does not carry (`other`). A block numbered
   * again takes the later one.
   */
  function readSurfaces(text) {
    const out = new Map();
    let cur = null;
    for (const line of logicalLines(text)) {
      const tokens = line.trim().split(/\s+/).filter(Boolean);
      if (!tokens.length) continue;
      const word = tokens[0].toUpperCase();
      if (KEYWORDS.has(word)) {
        cur = null;
        if (word === 'SURFACE') {
          cur = { sites: [], model: 'ddl', units: 'absolute', other: [] };
          out.set(tokens[1] || '1', cur);
        }
        continue;
      }
      if (!cur) continue;
      if (tokens[0].startsWith('-')) {
        const opt = tokens[0].toLowerCase();
        if (/^-no_e/.test(opt)) cur.model = 'none';
        // CD-MUSIC, and the capacitances of the surface of the site line before, F/m2.
        else if (/^-cd/.test(opt)) cur.model = 'cd';
        else if (/^-cap/.test(opt)) {
          const last = cur.sites[cur.sites.length - 1];
          if (last) last.cap = [Number(tokens[1]), Number(tokens[2])];
        }
        // How the sites are given (moles, or sites per nm2) says nothing once PHREEQC has loaded them.
        else if (/^-s/.test(opt) && /^d/i.test(tokens[1] || '')) cur.units = 'density';
        else if (/^-s/.test(opt) && /^a/i.test(tokens[1] || '')) cur.units = 'absolute';
        else if (!/^-(eq|equilibrate)/.test(opt)) cur.other.push(tokens.join(' '));
        continue;
      }
      const num = (x) => (x === undefined ? null : Number(x));
      // Sites that go with a phase: `Hfo_wOH Fe(OH)3(a) equilibrium_phase 0.2 5.34e4`, sites and m2 per mole of it.
      if (tokens.length > 2 && !Number.isFinite(Number(tokens[1])) && /^(e|k)/i.test(tokens[2])) {
        cur.sites.push({ master: tokens[0], sites: null, phase: tokens[1],
          kind: /^e/i.test(tokens[2]) ? 'equilibrium_phase' : 'kinetic_reactant', ratio: num(tokens[3]), area: num(tokens[4]),
          mass: null });
        continue;
      }
      cur.sites.push({ master: tokens[0], sites: num(tokens[1]), area: num(tokens[2]), mass: num(tokens[3]) });
    }
    return out;
  }

  /**
   * The GAS_PHASE blocks of an input: how each is held -- 'pressure', PHREEQC's
   * default, or 'volume' -- its total pressure (atm) and volume (L), as
   * PHREEQC reads them (1 and 1 unless given), and its gases with the partial
   * pressures they are given. A block numbered again takes the later one.
   */
  function readGasPhases(text) {
    const out = new Map();
    let cur = null;
    for (const line of logicalLines(text)) {
      const tokens = line.trim().split(/\s+/).filter(Boolean);
      if (!tokens.length) continue;
      const word = tokens[0].toUpperCase();
      if (KEYWORDS.has(word)) {
        cur = null;
        if (word === 'GAS_PHASE') {
          cur = { fixed: 'pressure', pressure: 1, volume: 1, comps: [] };
          out.delete(tokens[1] || '1');
          out.set(tokens[1] || '1', cur);
        }
        continue;
      }
      if (!cur) continue;
      if (tokens[0].startsWith('-')) {
        const opt = tokens[0].slice(1).toLowerCase();
        const v = Number(tokens[1]);
        if (opt === 'fixed_pressure') cur.fixed = 'pressure';
        else if (opt === 'fixed_volume') cur.fixed = 'volume';
        else if ('pressure'.startsWith(opt) && opt.length >= 2 && Number.isFinite(v)) cur.pressure = v;
        else if ('volume'.startsWith(opt) && Number.isFinite(v)) cur.volume = v;
        continue;
      }
      cur.comps.push({ name: tokens[0], p: tokens.length > 1 ? Number(tokens[1]) : null });
    }
    return out;
  }

  /*
    SOLID_SOLUTIONS as PHREEQC's read_solid_solutions reads them: a line that
    is no option names a solid solution; -comp (or -component) adds a member
    with its moles, -comp1 and -comp2 are the two of a binary one, first and
    second whatever their order; the parameters are any one of PHREEQC's ten
    forms, kept as given (input, p) for ssEnergies; -tempk is its
    temperature in kelvin, -tempc and -temp in C, which PHREEQC adds to
    298.15, and so does this.
  */
  const SS_OPTIONS = ['component', 'comp', 'parms', 'gugg_nondimensional', 'gugg_kj', 'activity_coefficients',
    'distribution_coefficients', 'miscibility_gap', 'spinodal_gap', 'critical_point', 'alyotropic_point', 'temp', 'tempk',
    'tempc', 'thompson', 'margules', 'comp1', 'comp2'];
  const SS_INPUT = { parms: 'a0a1', gugg_nondimensional: 'a0a1', gugg_kj: 'kj', activity_coefficients: 'gammas',
    distribution_coefficients: 'dist', miscibility_gap: 'misc', spinodal_gap: 'spinodal', critical_point: 'critical',
    alyotropic_point: 'alyotropic', thompson: 'thompson', margules: 'margules' };

  /** The SOLID_SOLUTIONS blocks of an input, by number: each its solid solutions, in order. */
  function readSolidSolutions(text) {
    const out = new Map();
    let block = null;
    let cur = null;
    const finish = () => {
      if (!cur) return;
      cur.comps = [...(cur.c1 ? [cur.c1] : []), ...(cur.c2 ? [cur.c2] : []), ...cur.comps];
      delete cur.c1;
      delete cur.c2;
      block.push(cur);
      cur = null;
    };
    for (const line of logicalLines(text)) {
      const tokens = line.trim().split(/\s+/).filter(Boolean);
      if (!tokens.length) continue;
      const word = tokens[0].toUpperCase();
      if (KEYWORDS.has(word)) {
        if (block) finish();
        block = null;
        if (word === 'SOLID_SOLUTIONS') {
          block = [];
          out.delete(tokens[1] || '1');
          out.set(tokens[1] || '1', block);
        }
        continue;
      }
      if (!block) continue;
      const dashed = /^-[A-Za-z]/.test(tokens[0]);
      const key = (dashed ? tokens[0].slice(1) : tokens[0]).toLowerCase();
      const opt = dashed ? SS_OPTIONS.find((o) => o.startsWith(key)) : SS_OPTIONS.find((o) => o === key);
      if (!opt) {
        finish();
        cur = { name: tokens[0], comps: [], c1: null, c2: null, input: null, p: [0, 0, 0, 0], tk: 298.15 };
        continue;
      }
      const nums = tokens.slice(1).map(Number);
      const comp = () => ({ name: tokens[1], moles: tokens.length > 2 ? Number(tokens[2]) : NaN });
      if (opt === 'component' || opt === 'comp') { if (cur && tokens[1]) cur.comps.push(comp()); continue; }
      if (opt === 'comp1') { if (cur && tokens[1]) cur.c1 = comp(); continue; }
      if (opt === 'comp2') { if (cur && tokens[1]) cur.c2 = comp(); continue; }
      if (!cur) continue;
      if (opt === 'tempk') { cur.tk = Number.isFinite(nums[0]) ? nums[0] : 298.15; continue; }
      if (opt === 'temp' || opt === 'tempc') { cur.tk = Number.isFinite(nums[0]) ? nums[0] + 298.15 : 298.15; continue; }
      cur.input = SS_INPUT[opt];
      if (cur.input === 'a0a1' || cur.input === 'kj') {
        if (Number.isFinite(nums[0])) cur.p[0] = nums[0];
        if (Number.isFinite(nums[1])) cur.p[1] = nums[1];
      } else {
        cur.p = nums.filter((v) => Number.isFinite(v));
      }
    }
    if (block) finish();
    return out;
  }

  /**
   * PHREEQC's ss_calc_a0_a1: a binary solid solution's Guggenheim energies
   * g0 and g1, kJ/mol, from whichever form its parameters were given in, at
   * its temperature tk; kc and kb its two members' K there. Null for an
   * ideal one (no parameters, or both zero).
   */
  function ssEnergies(ss, kc, kb) {
    const tol = 1e-6;
    const rt = ss.tk * R_KJ;
    const p = ss.p;
    let a0 = 0;
    let a1 = 0;
    let ag0 = 0;
    let ag1 = 0;
    switch (ss.input) {
      case 'a0a1':
        a0 = p[0]; a1 = p[1]; ag0 = a0 * rt; ag1 = a1 * rt;
        break;
      case 'gammas': {
        const [q1, q2, xbq1, xbq2] = p;
        let done = false;
        let dq1 = 0;
        let dq2 = 0;
        if (Math.abs(1 - xbq1) > 0 && q1 > 0) {
          dq1 = Math.log(q1) / ((1 - xbq1) * (1 - xbq1));
          if (xbq2 <= 0 || xbq2 > 1) { a0 = dq1; a1 = 0; done = true; }
        }
        if (!done && q2 <= 0) done = true;
        if (!done) {
          dq2 = Math.log(q2) / (xbq2 * xbq2);
          if (xbq1 < 0 || xbq2 > 1) { a0 = dq2; a1 = 0; done = true; }
        }
        if (!done) {
          const denom = 4 * (xbq1 - xbq2) + 2;
          if (Math.abs(denom) >= tol && Math.abs(1 - xbq1) > 0 && q1 > 0) {
            dq1 = Math.log(q1) / ((1 - xbq1) * (1 - xbq1));
            a0 = (dq1 * (3 - 4 * xbq2) + dq2 * (4 * xbq1 - 1)) / denom;
            a1 = (dq1 - dq2) / denom;
          }
        }
        ag0 = a0 * rt; ag1 = a1 * rt;
        break;
      }
      case 'dist': {
        const [q1, q2, xbq1, xbq2] = p;
        const ratio = kc / kb;
        const dr1 = Math.log(q1 / ratio);
        const x21 = 2 * xbq1 - 1;
        if (Math.abs(xbq1 - xbq2) < tol || xbq2 < 0) { a0 = dr1 / x21; a1 = 0; }
        else {
          const dr2 = Math.log(q2 / ratio);
          const x22 = 2 * xbq2 - 1;
          if (xbq1 < 0) { a0 = dr2 / x22; a1 = 0; }
          else {
            const x61 = 6 * xbq1 * xbq1 - 6 * xbq1 + 1;
            const x62 = 6 * xbq2 * xbq2 - 6 * xbq2 + 1;
            a0 = (x61 * dr2 - x62 * dr1) / (x22 * x61 - x21 * x62);
            a1 = (x21 * dr2 - x22 * dr1) / (x21 * x62 - x22 * x61);
          }
        }
        ag0 = a0 * rt; ag1 = a1 * rt;
        break;
      }
      case 'misc': {
        const xb1 = p[0];
        const xb2 = p[1];
        const xc1 = 1 - xb1;
        const xc2 = 1 - xb2;
        const r1 = Math.log(xb1 / xb2);
        const r2 = Math.log(xc1 / xc2);
        const pa1 = xc2 * xc2 - xc1 * xc1;
        const pb1 = 3 * (xc2 * xc2 - xc1 * xc1) - 4 * (xc2 * xc2 * xc2 - xc1 * xc1 * xc1);
        const pa2 = xb2 * xb2 - xb1 * xb1;
        const pb2 = -(3 * (xb2 * xb2 - xb1 * xb1) - 4 * (xb2 * xb2 * xb2 - xb1 * xb1 * xb1));
        a0 = (r1 - (pb1 / pb2) * r2) / (pa1 - (pa2 * pb1) / pb2);
        a1 = (r1 - (pa1 / pa2) * r2) / (pb1 - (pb2 * pa1) / pa2);
        ag0 = a0 * rt; ag1 = a1 * rt;
        break;
      }
      case 'spinodal': {
        const xsm1 = p[0];
        const xsm2 = p[1];
        const pn9 = 1 / xsm1;
        const pn10 = 1 / xsm2;
        const c5 = 1 - xsm1;
        const c6 = 1 - xsm2;
        const pl9 = 6 * c5 - 12 * c5 * c5;
        const pl10 = 6 * c6 - 12 * c6 * c6;
        const pj9 = 2 * c5;
        const pj10 = 2 * c6;
        a0 = (pn9 - (pl9 / pl10) * pn10) / (pj9 - (pl9 / pl10) * pj10);
        a1 = (pn9 - (pj9 / pj10) * pn10) / (pl9 - (pj9 / pj10) * pl10);
        ag0 = a0 * rt; ag1 = a1 * rt;
        break;
      }
      case 'critical': {
        const xc = p[0];
        const tc = p[1];
        const r = R_KJ;
        ag1 = (r * tc * (2 * xc - 1)) / (12 * xc * xc * (1 - xc) * (1 - xc));
        ag0 = ((r * tc) / (xc * (1 - xc)) - (12 * xc - 6) * ag1) / 2;
        a0 = ag0 / rt; a1 = ag1 / rt;
        break;
      }
      case 'alyotropic': {
        const xaly = p[0];
        const r = Math.log(kb / kc);
        const alpha0 = 2 * xaly - 1;
        const alpha1 = 6 * xaly * (xaly - 1) + 1;
        const spialy = Math.pow(10, p[1]);
        a0 = -999;
        a1 = -999;
        if (Math.abs(alpha0) >= tol) {
          let azero = r / alpha0;
          const xcaly = 1 - xaly;
          let i;
          for (i = 0; i < 50; i++) {
            let phi1 = xcaly * xcaly * (azero + ((r - azero * alpha0) * (4 * xaly - 1)) / alpha1);
            let phi2 = xaly * xaly * (azero + ((3 - 4 * xaly) * (azero * alpha0 - r)) / alpha1);
            phi1 = xaly * kb * Math.exp(phi1);
            phi2 = xcaly * kc * Math.exp(phi2);
            const fx = phi1 + phi2 - spialy;
            const fx1 = xcaly * xcaly * (1 - (alpha0 * (4 * xaly - 1)) / alpha1) * phi1
              + xaly * xaly * (1 + (alpha0 * (3 - 4 * xaly)) / alpha1) * phi2;
            if (Math.abs(fx1) < 1e-10) break;
            a0 = azero - fx / fx1;
            const test = Math.abs(a0 - azero) + Math.abs(fx);
            azero = a0;
            if (test < tol) break;
          }
          if (i < 50) { a1 = (r - a0 * alpha0) / alpha1; ag0 = a0 * rt; ag1 = a1 * rt; }
        }
        break;
      }
      case 'kj':
        ag0 = p[0]; ag1 = p[1]; a0 = ag0 / rt; a1 = ag1 / rt;
        break;
      case 'thompson':
        ag0 = (p[0] + p[1]) / 2; ag1 = (p[0] - p[1]) / 2; a0 = ag0 / rt; a1 = ag1 / rt;
        break;
      case 'margules':
        a0 = p[0] + (3 * p[1]) / 4; a1 = p[1] / 4; ag0 = a0 * rt; ag1 = a1 * rt;
        break;
      default:
        return null;
    }
    if (a0 === 0 && a1 === 0) return null;
    return { a0, a1, ag0, ag1 };
  }

  /** The database, read as PHREEQC reads one, and then any inputs after it. */
  function readDatabase(...texts) {
    const db = new Database();
    texts.forEach((t, i) => { if (t) db.read(t, i === 0); });
    return db;
  }

  /**
   * A SIT coefficient at tk kelvin from its terms, as PHREEQC's
   * calc_sit_param works it out: a0 + a1 (1/T - 1/Tr) + a2 ln(T/Tr) +
   * a3 (T - Tr) + a4 (T^2 - Tr^2), Tr = 298.15 K, and a0 itself within a
   * hundredth of a degree of that.
   */
  function sitParam(a, tk) {
    const TR = 298.15;
    if (Math.abs(tk - TR) < 0.01) return a[0];
    return (a[0] || 0) + (a[1] || 0) * (1 / tk - 1 / TR) + (a[2] || 0) * Math.log(tk / TR)
      + (a[3] || 0) * (tk - TR) + (a[4] || 0) * (tk * tk - TR * TR);
  }

  /* ======================================================================
     Asking PHREEQC
     ====================================================================== */

  /** Our own selected-output number, clear of any the input uses. */
  const SEL = 99;

  /**
   * SELECTED_OUTPUT and USER_PUNCH 99: every aqueous species with its
   * molality and log gamma, every phase with its saturation index, every
   * element and valence state with its total, and the usual numbers. ';'
   * cannot go in a BASIC string -- PHREEQC splits lines on it -- hence ','
   * and '|'.
   */
  function punchBlock(extra) {
    const more = extra || [];
    const lines = [
      `SELECTED_OUTPUT ${SEL}`, '  -reset false', '  -solution true', '  -state true',
      `USER_PUNCH ${SEL}`,
      `  -headings aq phases elements mu pH mH cb aw tc pe ex sf${more.map((_, i) => ` x${i}`).join('')}`,
      '  -start',
      '  10 t = SYS("aq", n, nm$, ty$, mo)',
      '  20 s$ = ""',
      '  30 FOR i = 1 TO n',
      '  40   s$ = s$ + nm$(i) + "," + STR_E$(MOL(nm$(i)), 23, 15) + "," + STR_E$(LG(nm$(i)), 23, 15) + "|"',
      '  50 NEXT i',
      '  60 PUNCH s$',
      '  70 t = SYS("phases", n2, pn$, pt$, pv)',
      '  80 p$ = ""',
      '  90 FOR i = 1 TO n2',
      '  100   p$ = p$ + pn$(i) + "," + STR_E$(SI(pn$(i)), 23, 15) + "|"',
      '  110 NEXT i',
      '  120 PUNCH p$',
      '  130 t = SYS("elements", n3, en$, et$, ev)',
      '  140 e$ = ""',
      '  150 FOR i = 1 TO n3',
      '  160   e$ = e$ + en$(i) + "," + STR_E$(ev(i), 23, 15) + "|"',
      '  170 NEXT i',
      '  180 PUNCH e$, MU, -LA("H+"), MOL("H+"), CHARGE_BALANCE, ACT("H2O"), TC, -LA("e-")',
      // The species on an exchanger: mol/kgw, log activity and the log gamma
      // of its ion that the activity takes, the equivalent fraction left out.
      // A FOR over no species at all is jumped, not entered: PHREEQC's BASIC
      // skipping an empty FOR left its memory spoiled, and a later load of
      // the database fell over it (WebAssembly: memory access out of bounds).
      '  182 t = SYS("ex", n4, xn$, xt$, xm)',
      '  183 x$ = ""',
      '  184 IF n4 < 1 THEN GOTO 188',
      '  185 FOR i = 1 TO n4',
      '  186   x$ = x$ + xn$(i) + "," + STR_E$(MOL(xn$(i)), 23, 15) + "," + STR_E$(LA(xn$(i)), 23, 15) + "," + STR_E$(LG(xn$(i)), 23, 15) + "|"',
      '  187 NEXT i',
      '  188 PUNCH x$',
      // The species on a surface, as on an exchanger: mol/kgw, log activity
      // (its fraction of the sites), log of what the fraction adds. Jumped
      // over when there are none, for the same reason.
      '  190 t = SYS("surf", n5, sn$, st$, sm)',
      '  191 f$ = ""',
      '  192 IF n5 < 1 THEN GOTO 196',
      '  193 FOR i = 1 TO n5',
      '  194   f$ = f$ + sn$(i) + "," + STR_E$(MOL(sn$(i)), 23, 15) + "," + STR_E$(LA(sn$(i)), 23, 15) + "," + STR_E$(LG(sn$(i)), 23, 15) + "|"',
      '  195 NEXT i',
      '  196 PUNCH f$',
    ];
    more.forEach((expr, i) => lines.push(`  ${200 + 10 * i} PUNCH ${expr}`));
    lines.push('  -end');
    return `${lines.join('\n')}\n`;
  }

  function pairs(s) {
    const out = [];
    for (const rec of String(s || '').split('|')) {
      if (!rec) continue;
      const parts = rec.split(',');
      out.push([parts[0].trim(), ...parts.slice(1).map(Number)]);
    }
    return out;
  }

  /** The rows of selected output 99 as objects. */
  function parseRows(rows) {
    if (!rows || rows.length < 2) return [];
    const head = rows[0].map((h) => String(h).trim());
    const at = (name) => head.indexOf(name);
    const xs = head.map((h, i) => (/^x[0-9]+$/.test(h) ? i : -1)).filter((i) => i >= 0);
    return rows.slice(1).map((r) => {
      const species = new Map();
      for (const [n, m, g] of pairs(r[at('aq')])) species.set(n, [m, g]);
      const phases = new Map();
      for (const [n, si] of pairs(r[at('phases')])) phases.set(n, si);
      const elements = new Map();
      for (const [n, v] of pairs(r[at('elements')])) elements.set(n, v);
      const exchange = new Map();
      if (at('ex') >= 0) for (const [n, m, la, g] of pairs(r[at('ex')])) exchange.set(n, { m, la, lg: g });
      const surface = new Map();
      if (at('sf') >= 0) for (const [n, m, la, g] of pairs(r[at('sf')])) surface.set(n, { m, la, lg: g });
      const num = (name) => Number(r[at(name)]);
      return {
        soln: at('soln') >= 0 ? r[at('soln')] : null,
        state: at('state') >= 0 ? String(r[at('state')]).trim() : '',
        species, phases, elements, exchange, surface,
        mu: num('mu'), pH: num('pH'), mH: num('mH'), cb: num('cb'), aw: num('aw'), tc: num('tc'),
        pe: num('pe'),
        x: xs.map((i) => r[i]),
      };
    });
  }

  function runRows(engine, text) {
    return parseRows(engine.run(text));
  }

  /* ======================================================================
     Numbers as text
     ====================================================================== */

  /** %g: `p` significant figures, trailing zeros dropped. */
  function fmtG(x, p) {
    if (!Number.isFinite(x)) return String(x);
    const s = x.toPrecision(p);
    const [mant, exp] = s.split('e');
    const m = mant.includes('.') ? mant.replace(/0+$/, '').replace(/\.$/, '') : mant;
    return exp === undefined ? m : `${m}e${exp}`;
  }

  function fmtCoef(c) {
    return Math.abs(c - Math.round(c)) < 1e-9 ? String(Math.round(c)) : fmtG(c, 10);
  }

  const log10 = (x) => (x > 0 ? Math.log10(x) : -Infinity);
  // PHREEQC's own Faraday constant and gas constant, with which it reports a
  // potential in volts: that potential as an activity, exp(-F psi/RT).
  const FARADAY = 96493.5;
  const GAS_R = 8.31470;

  /* ======================================================================
     KINETICS and RATES: PHREEQC's kinetic reactants, and their BASIC rate
     programs as rate laws of rtm.html
     ====================================================================== */

  /**
   * The RATES of a database and of inputs read after it: each rate's BASIC
   * program by name (any case, as PHREEQC finds one), its numbered lines as
   * written; a rate given again replaces the first.
   */
  function readRates(...texts) {
    const out = new Map();
    for (const text of texts) {
      let inBlock = false;
      let cur = null;
      for (const line of logicalLines(text)) {
        const s = line.trim();
        if (!s) continue;
        const first = s.split(/\s+/)[0];
        if (!/^[0-9]/.test(first) && KEYWORDS.has(first.toUpperCase())) {
          inBlock = first.toUpperCase() === 'RATES';
          cur = null;
          continue;
        }
        if (!inBlock) continue;
        if (/^-s(t(a(r(t)?)?)?)?$/i.test(first)) continue;
        if (/^-e(n(d)?)?$/i.test(first)) { cur = null; continue; }
        if (/^[0-9]/.test(first)) { if (cur) cur.lines.push(s); continue; }
        cur = { name: first, lines: [] };
        out.set(first.toLowerCase(), cur);
      }
    }
    return out;
  }

  /** Seconds in PHREEQC's time unit, as Utilities::convert_time reads its first letter. */
  function secondsIn(unit) {
    const u = String(unit || 's').toLowerCase()[0];
    return u === 'm' ? 60 : u === 'h' ? 3600 : u === 'd' ? 86400 : u === 'y' ? 86400 * 365.25 : 1;
  }

  /**
   * The KINETICS blocks of an input, as PHREEQC's read_kinetics reads them:
   * each reactant -- its rate's name, -formula (phase or formula names with
   * their coefficients; the name itself by default), -m and -m0 (each the
   * other's where not given, else 1), -parms, -tol -- and the block's steps
   * in seconds, `-steps 3600 in 10` ten of 360, `4*10` four of ten, a unit
   * word converting them. A block numbered again replaces the first.
   */
  function readKinetics(text) {
    const out = new Map();
    const OPTS = ['tol', 'm', 'm0', 'parms', 'formula', 'steps', 'step_divide', 'parameters', 'runge-kutta',
      'runge_kutta', 'rk', 'bad_step_max', 'cvode', 'cvode_steps', 'cvode_order', 'time_steps'];
    const option = (word) => {
      const w = word.toLowerCase();
      return OPTS.includes(w) ? w : OPTS.find((o) => o.startsWith(w)) || null;
    };
    let cur = null;
    let comp = null;
    const finish = (b) => {
      if (!b) return;
      if (b.count > 0 && b.steps.length === 1) {
        const total = b.steps[0];
        b.steps = Array.from({ length: b.count }, () => total / b.count);
      }
      if (!b.steps.length) b.steps.push(1);
      b.steps = b.steps.map((s) => s * secondsIn(b.units));
      for (const c of b.comps) {
        if (c.m0 === null) c.m0 = c.m === null ? 1 : c.m;
        if (c.m === null) c.m = c.m0;
        if (!c.formula.length) c.formula.push([c.name, 1]);
      }
    };
    for (const line of logicalLines(text)) {
      const tokens = line.trim().split(/\s+/).filter(Boolean);
      if (!tokens.length) continue;
      const word = tokens[0].toUpperCase();
      if (KEYWORDS.has(word) && !tokens[0].startsWith('-')) {
        finish(cur);
        cur = null;
        comp = null;
        if (word === 'KINETICS') {
          const n = parseInt(tokens[1], 10);
          cur = { n: Number.isFinite(n) ? n : 1, comps: [], steps: [], count: 0, units: null, opts: {} };
          out.set(cur.n, cur);
        }
        continue;
      }
      if (!cur) continue;
      if (!tokens[0].startsWith('-')) {
        comp = { name: tokens[0], formula: [], m: null, m0: null, parms: [], tol: 1e-8 };
        cur.comps.push(comp);
        continue;
      }
      const opt = option(tokens[0].slice(1));
      const rest = tokens.slice(1);
      const num = (s) => (s !== undefined && /^[-+]?[0-9.]/.test(s) ? Number(s) : NaN);
      switch (opt) {
        case 'tol': if (comp && Number.isFinite(num(rest[0]))) comp.tol = num(rest[0]); break;
        case 'm': if (comp && Number.isFinite(num(rest[0]))) comp.m = num(rest[0]); break;
        case 'm0': if (comp && Number.isFinite(num(rest[0]))) comp.m0 = num(rest[0]); break;
        case 'parms': case 'parameters':
          if (comp) for (const s of rest) comp.parms.push(Number.isFinite(num(s)) ? num(s) : s);
          break;
        case 'formula':
          if (comp) {
            let name = null;
            for (const s of rest) {
              if (/^[A-Za-z([]/.test(s)) { if (name) comp.formula.push([name, 1]); name = s; } else if (name) {
                comp.formula.push([name, Number(s)]);
                name = null;
              }
            }
            if (name) comp.formula.push([name, 1]);
          }
          break;
        case 'steps': case 'time_steps':
          for (let i = 0; i < rest.length; i++) {
            const s = rest[i];
            if (/^[0-9.]/.test(s)) {
              const rep = /^([0-9]+)\*(.+)$/.exec(s);
              if (rep) for (let k = 0; k < Number(rep[1]); k++) cur.steps.push(Number(rep[2]));
              else cur.steps.push(Number(s));
            } else if (/^i/i.test(s)) {
              const n = parseInt(rest[i + 1], 10);
              if (Number.isFinite(n)) { cur.count = Math.abs(n); i++; }
            } else cur.units = s;
          }
          break;
        default:
          if (opt) cur.opts[opt] = rest.join(' ');
          break;
      }
    }
    finish(cur);
    return out;
  }

  /** An input without its KINETICS (and KINETICS_MODIFY) blocks: the water a kinetic run starts from. */
  function withoutKinetics(text) {
    const out = [];
    let skip = false;
    for (const raw of String(text).split(/\r\n|\r|\n/)) {
      const first = raw.trim().split(/\s+/)[0] || '';
      const word = first.toUpperCase();
      if (KEYWORDS.has(word) && !first.startsWith('-')) skip = word === 'KINETICS' || word === 'KINETICS_MODIFY';
      if (!skip) out.push(raw);
    }
    return out.join('\n');
  }

  /**
   * An input's SURFACE lines whose sites go with a kinetic reactant, as the
   * sites, and the area, they come to at its -m: what PHREEQC loads at the
   * start, which it will not without the KINETICS (withoutKinetics).
   * `Hfo_wOH Ferrihydrite kinetic_reactant 0.2 5.33e4` with -m 0.002 is
   * `Hfo_wOH 0.0004 5.33e4 0.002`, the area per mole of it times its moles
   * as the grams.
   */
  function kineticSurfacesAtStart(text, comps) {
    let block = null;
    return String(text).split(/\r\n|\r|\n/).map((raw) => {
      const tokens = raw.split('#', 1)[0].trim().split(/\s+/).filter(Boolean);
      if (!tokens.length) return raw;
      const word = tokens[0].toUpperCase();
      if (KEYWORDS.has(word) && !tokens[0].startsWith('-')) {
        block = word === 'SURFACE' || word === 'EXCHANGE' ? word : null;
        return raw;
      }
      if (!block || tokens[0].startsWith('-') || tokens.length < 4 || !/^k/i.test(tokens[2])) return raw;
      const c = comps.find((x) => x.name.toLowerCase() === tokens[1].toLowerCase());
      if (!c) return raw;
      // An exchanger's capacity, so many per mole of the reactant: at its -m.
      if (block === 'EXCHANGE') return ` ${tokens[0]}  ${fmtG(Number(tokens[3]) * c.m, 15)}`;
      const area = tokens[4];
      return ` ${tokens[0]}  ${fmtG(Number(tokens[3]) * c.m, 15)}${area !== undefined ? `  ${area}  ${fmtG(c.m, 15)}` : ''}`;
    }).join('\n');
  }

  /**
   * The exchangers of an input's EXCHANGE blocks whose capacity goes with a
   * phase or a kinetic reactant -- `X Calcite equilibrium_phase 0.1`,
   * `X Organic_C kinetic_reactant 0.5` -- each with the phase or reactant,
   * which, and the capacity to each mole of it.
   */
  function linkedExchangers(text) {
    const out = [];
    let inBlock = false;
    for (const line of logicalLines(text)) {
      const tokens = line.trim().split(/\s+/).filter(Boolean);
      if (!tokens.length) continue;
      const word = tokens[0].toUpperCase();
      if (KEYWORDS.has(word) && !tokens[0].startsWith('-')) { inBlock = word === 'EXCHANGE'; continue; }
      if (!inBlock || tokens[0].startsWith('-') || tokens.length < 4 || Number.isFinite(Number(tokens[1]))) continue;
      if (!/^(e|k)/i.test(tokens[2])) continue;
      out.push({ master: tokens[0], phase: tokens[1], kind: /^e/i.test(tokens[2]) ? 'equilibrium_phase' : 'kinetic_reactant',
        ratio: Number(tokens[3]) });
    }
    return out;
  }

  /*
    PHREEQC's TRANSPORT and ADVECTION options, in the order its readtr.cpp
    and read_advection list them: a word with its dash is the first of them
    it begins, one without the whole word (find_option); a line that is
    neither goes on with the list before it.
  */
  const TRANSPORT_OPTS = ['cells', 'shifts', 'print', 'selected_output', 'bcond', 'timest', 'diffc', 'tempr', 'length',
    'disp', 'punch', 'stagnant', 'bc', 'boundary_conditions', 'time_step', 'temp_retardation_factor',
    'diffusion_coefficient', 'dispersivity', 'direction', 'temperature_retardation_factor', 'print_cells',
    'selected_cells', 'flow_direction', 'flow', 'lengths', 'dispersivities', 'dump', 'output', 'output_frequency',
    'selected_output_frequency', 'punch_cells', 'dump_frequency', 'dump_restart', 'punch_frequency', 'print_frequency',
    'correct_disp', 'initial_time', 'warning', 'warnings', 'thermal_diffusion', 'multi_d', 'interlayer_d', 'porosities',
    'porosity', 'fix_current', 'current', 'implicit', 'same_model'];
  const ADVECTION_OPTS = ['cells', 'shifts', 'print', 'selected_output', 'punch', 'print_cells', 'selected_cells',
    'time_step', 'timest', 'output', 'output_frequency', 'selected_output_frequency', 'punch_frequency',
    'print_frequency', 'punch_cells', 'initial_time', 'warning', 'warnings'];

  /**
   * The input's first TRANSPORT block -- or, where it has none, its first
   * ADVECTION -- as PHREEQC reads it, with PHREEQC's defaults: one cell of
   * 1 m, one shift, a time step of 0, the water flowing forward, flux at
   * both ends, no dispersivity, a diffusion coefficient of 0.3e-9 m2/s.
   * Returns null without either, else {kind, cells, shifts, dt (seconds),
   * dir (1 forward, -1 back, 0 diffusion only), bc [first, last] (1
   * constant, 2 closed, 3 flux), lengths and disp (one a cell), correctDisp,
   * diffc, heat (thermal diffusion asked for), stag (one layer of stagnant
   * cells exchanging at a first order, {alpha, thm, thim}, or null), mcd
   * (multicomponent diffusion, -multi_D's {dw, por, lim, n}, or null), por
   * (-porosities, one a cell, or null), implicit (-implicit true, PHREEQC's
   * implicit scheme for -multi_D), others (what it says that no column
   * of the page has: stagnant cells in more layers or mixed by MIX blocks,
   * interlayer diffusion, a current, diffusion coefficients corrected for
   * the ionic strength), reactions (a REACTION numbered as a cell or a stagnant cell),
   * before (the input up to the END of the block's simulation, without the
   * block), after (whether anything is calculated after that)}.
   */
  function readTransport(text) {
    const lines = logicalLines(text);
    const first = (ln) => ln.trim().split(/\s+/)[0] || '';
    const isKey = (ln) => { const w = first(ln); return !!w && !w.startsWith('-') && KEYWORDS.has(w.toUpperCase()); };
    let kind = 'TRANSPORT';
    let at = lines.findIndex((ln) => isKey(ln) && first(ln).toUpperCase() === kind);
    if (at < 0) {
      kind = 'ADVECTION';
      at = lines.findIndex((ln) => isKey(ln) && first(ln).toUpperCase() === kind);
    }
    if (at < 0) return null;
    let stop = at + 1;
    while (stop < lines.length && !isKey(lines[stop])) stop++;
    let end = stop;
    while (end < lines.length && !(isKey(lines[end]) && first(lines[end]).toUpperCase() === 'END')) end++;
    const quiet = /^(END|PRINT|SELECTED_OUTPUT|USER_PUNCH|USER_GRAPH|USER_PRINT|TITLE|KNOBS)$/i;
    const t = { kind, cells: 1, shifts: 1, dt: 0, dir: 1, bc: [3, 3], lengths: [], disp: [], correctDisp: false,
      diffc: 0.3e-9, heat: false, others: [], stag: null, mcd: null, por: [], implicit: false,
      before: `${[...lines.slice(0, at), ...lines.slice(stop, end)].join('\n')}\nEND\n`,
      after: lines.slice(end + 1).some((ln) => isKey(ln) && !quiet.test(first(ln))) };
    const opts = kind === 'TRANSPORT' ? TRANSPORT_OPTS : ADVECTION_OPTS;
    // A list: numbers, a repeat written n*x.
    const values = (tokens) => tokens.flatMap((s) => {
      const rep = /^([0-9]+)\*(.+)$/.exec(s);
      return rep ? Array.from({ length: Number(rep[1]) }, () => Number(rep[2])) : [Number(s)];
    }).filter((v) => Number.isFinite(v));
    const bcOf = (s) => {
      if (s === undefined) return 3;
      const w = s.toLowerCase();
      if (/^[123]$/.test(w)) return Number(w);
      return w.startsWith('co') ? 1 : w.startsWith('cl') ? 2 : w.startsWith('f') ? 3 : NaN;
    };
    const yes = (s) => s === undefined || !/^f/i.test(s);
    let list = null;
    for (const raw of lines.slice(at + 1, stop)) {
      const tokens = raw.trim().split(/\s+/).filter(Boolean);
      if (!tokens.length) continue;
      const w = tokens[0].toLowerCase();
      let opt = null;
      if (/^-[a-z]/.test(w)) opt = opts.find((x) => x.startsWith(w.slice(1))) || `?${tokens[0]}`;
      else if (opts.includes(w)) opt = w;
      const args = opt ? tokens.slice(1) : tokens;
      if (!opt) {
        if (list === 'lengths') t.lengths.push(...values(args));
        else if (list === 'disp') t.disp.push(...values(args));
        else if (list === 'por') t.por.push(...values(args));
        continue;
      }
      list = null;
      switch (opt) {
        case 'cells': t.cells = parseInt(args[0], 10); break;
        case 'shifts':
          t.shifts = parseInt(args[0], 10);
          // An old form: the direction after the shifts, 1, -1 or 0.
          if (/^-?[01]$/.test(args[1] || '')) t.dir = Number(args[1]);
          break;
        case 'timest': case 'time_step':
          t.dt = Number(args[0]) * (/^[a-z]/i.test(args[1] || '') ? secondsIn(args[1]) : 1);
          break;
        case 'bcond': case 'bc': case 'boundary_conditions': t.bc = [bcOf(args[0]), bcOf(args[1])]; break;
        case 'diffc': case 'diffusion_coefficient': t.diffc = Number(args[0]); break;
        case 'length': case 'lengths': t.lengths.push(...values(args)); list = 'lengths'; break;
        case 'disp': case 'dispersivity': case 'dispersivities': t.disp.push(...values(args)); list = 'disp'; break;
        case 'direction': case 'flow_direction': case 'flow': {
          const d = (args[0] || '').toLowerCase()[0];
          t.dir = d === 'f' ? 1 : d === 'b' ? -1 : d === 'd' || d === 'n' ? 0 : NaN;
          break;
        }
        case 'correct_disp': t.correctDisp = yes(args[0]); break;
        case 'stagnant': {
          /*
            Stagnant cells: one layer exchanging with each cell at a first
            order, -stagnant 1 alpha theta_m theta_im, is carried (columnSetup);
            more layers, or one without its exchange factor, PHREEQC mixes as
            the input's MIX blocks say, which the page does not read.
          */
          const k = parseInt(args[0], 10);
          t.stag = null;
          t.stagOther = null;
          if (!(k > 0)) break;
          const [a, m, im] = args.slice(1, 4).map(Number);
          if (k > 1) t.stagOther = `stagnant cells in ${k} layers (-stagnant ${k}), which PHREEQC mixes as the input's MIX blocks say`;
          else if (args[1] === undefined) t.stagOther = 'stagnant cells mixed as the input\'s MIX blocks say (-stagnant 1 with no exchange factor)';
          else if (!(a > 0) || !(m > 0) || !(im > 0)) {
            t.stagOther = 'stagnant cells whose -stagnant does not give an exchange factor and the mobile and immobile '
              + 'porosities, each above zero';
          } else t.stag = { alpha: a, thm: m, thim: im };
          break;
        }
        case 'multi_d': {
          /*
            Multicomponent diffusion, -multi_D true [Dw porosity limit n
            correct], each value back at PHREEQC's default unless given (1e-9
            m2/s for a species without -dw, 0.3, 0, 1, false): each species at
            its own Dw times the porosity to the n, the ions coupled so that no
            current flows, down their activities (transport.cpp, find_J). Dw's
            corrected as specific conductance has them are not carried.
          */
          const w0 = (args[0] || '').toLowerCase();
          t.mcd = null;
          t.mcdOther = null;
          if (w0.startsWith('f')) break;
          if (!w0.startsWith('t')) { t.mcdOther = 'a -multi_D that says neither true nor false'; break; }
          const num = (i, def) => (args[i] === undefined ? def : Number(args[i]));
          const m = { dw: num(1, 1e-9), por: num(2, 0.3), lim: num(3, 0), n: num(4, 1) };
          if (![m.dw, m.por, m.lim, m.n].every(Number.isFinite)) t.mcdOther = 'a -multi_D whose values are not numbers';
          else if (/^t/i.test(args[5] || '')) {
            t.mcdOther = 'diffusion coefficients corrected for the ionic strength as specific conductance has them '
              + '(-multi_D\'s sixth value, true)';
          } else t.mcd = m;
          break;
        }
        case 'porosities': case 'porosity': t.por.push(...values(args)); list = 'por'; break;
        // PHREEQC's implicit scheme for -multi_D, which takes each species down its concentration (diffuse_implicit).
        case 'implicit': t.implicit = /^t/i.test(args[0] || ''); break;
        case 'interlayer_d': if (yes(args[0])) t.others.push('interlayer diffusion (-interlayer_D)'); break;
        case 'fix_current': case 'current': t.others.push('a fixed current (-fix_current)'); break;
        case 'tempr': case 'temp_retardation_factor': case 'temperature_retardation_factor': case 'thermal_diffusion':
          t.heat = true;
          break;
        default:
          // Printing, punching, dumping, warnings, the time it starts at.
          if (opt.startsWith('?')) t.others.push(`an option PHREEQC does not have, ${opt.slice(1)}`);
          else if (['print', 'print_cells', 'punch', 'punch_cells', 'selected_cells'].includes(opt)) list = 'cells';
      }
    }
    const fill = (given, def) => Array.from({ length: Math.max(t.cells, 0) }, (_, i) => (given.length
      ? given[Math.min(i, given.length - 1)] : def));
    t.lengths = fill(t.lengths, 1);
    t.disp = fill(t.disp, 0);
    if (kind === 'ADVECTION') t.diffc = 0;
    if (t.stagOther) t.others.push(t.stagOther);
    delete t.stagOther;
    if (t.mcdOther) t.others.push(t.mcdOther);
    delete t.mcdOther;
    // -porosities, one a cell, the last going on (readtr.cpp); none read, null.
    t.por = t.por.length ? fill(t.por, 0) : null;
    // A REACTION numbered as a cell, which PHREEQC adds to it at every shift -- a stagnant cell's too.
    t.reactions = [];
    const n = t.cells;
    for (const ln of lines.slice(0, at)) {
      const m = /^\s*REACTION\s+([0-9]+)(?:-([0-9]+))?/i.exec(ln);
      if (!m || !isKey(ln)) continue;
      const lo = Number(m[1]);
      const hi = m[2] !== undefined ? Number(m[2]) : lo;
      if ((lo <= n && hi >= 1) || (t.stag && lo <= 2 * n + 1 && hi >= n + 2)) {
        t.reactions.push(lo === hi ? `${lo}` : `${lo}-${hi}`);
      }
    }
    return t;
  }

  /**
   * The column of an input's TRANSPORT (or ADVECTION) for waterToModel:
   * what it starts from, what comes in, and what has to be written.
   *
   * PHREEQC's TRANSPORT begins by equilibrating each cell, its stagnant
   * cells and the water at each end with whatever is numbered as each
   * (transport.cpp, "Equilibrating initial solutions"); RUN_CELLS with no
   * time does the same here, after everything the input does before. Runs of
   * cells that come out alike are zones, cell 1's water the one the page
   * writes in <SPECIES> and the others' written in <INITIAL>; the stagnant
   * cells behind them make zones of their own, which the page's rock matrix
   * starts from. The water at each end that comes in, or that a constant end
   * holds the column to, is speciated as PHREEQC has it. Each water takes a
   * trace of every other, so that what only one of them has is a total that
   * can be held everywhere -- 1e-12, as 1e-20 left totals of 1e-24 that the
   * solver could not start from. The species written are those above the
   * floor in any of them, or in a zone's water and an end's mixed half and
   * half on what the zone holds: NaCl in a column without chloride is
   * nothing until the chloride comes.
   *
   * Returns null without TRANSPORT or ADVECTION, else {t, cellInput (the
   * input whose last calculation is cell 1, with its traces), left and
   * right (each end's water: species -> molality, or null), keep and keepOn
   * (species to write whatever the floor), corr (-correct_disp's factor),
   * tc, trace, zones (runs of cells alike, {lo, hi, rep, row}), stag (null,
   * or -stagnant's {alpha, thm, thim} and its zones, {lo, hi, rep, row,
   * same}), mcd (null, or -multi_D's {dw, por, lim, n} with the porosity the
   * cells diffuse at and porosity^n, {porosity, factor})}.
   */
  function columnSetup(o, floor) {
    const t = readTransport(o.water.text);
    if (!t) return null;
    const n = t.cells;
    const no = (s) => { throw new Error(`From PHREEQC carries the column of the input's ${t.kind} block, and ${s}.`); };
    if (!(n >= 1)) no('it has no cells');
    if (!Number.isFinite(t.dir)) no('its -flow_direction is not forward, back or diffusion_only');
    if (t.bc.some((b) => !Number.isFinite(b))) no('its -boundary_conditions are not constant, closed or flux');
    if (t.others.length) no(`it has ${t.others.join(' and ')}, which no column of the page has`);
    if (t.reactions.length) {
      no(`the input has a REACTION numbered as a cell (${t.reactions.join(', ')}), which PHREEQC adds to the cell at every `
        + 'shift: write it as a rate in <REACTIONS> instead');
    }
    if (!(t.shifts >= 1)) no('it has no shifts');
    if (!(t.dt > 0)) {
      no(t.dir ? 'it gives no -time_step: the water moves a cell in each, and the page needs to know how fast that is'
        : 'it gives no -time_step: the diffusion goes on for -shifts of them');
    }
    if (t.dir && t.bc[t.dir > 0 ? 0 : 1] === 2) no('the water comes in through an end that is closed');
    const alike = (a) => a.every((v) => Math.abs(v - a[0]) <= 1e-12 * Math.abs(a[0]));
    if (t.dir && !alike(t.lengths)) {
      no('its cells are of different lengths, which PHREEQC\'s water crosses each in one time step, at a speed of its '
        + 'own there: the page\'s column has one velocity');
    }
    if (t.dir && !alike(t.disp)) no('its cells have dispersivities of their own, where the page\'s column has one');
    /*
      Multicomponent diffusion: each species diffuses at its Dw times the
      porosity to the n -- the cells' porosity, -stagnant's mobile one where
      both are given, as PHREEQC has it, or -multi_D's where none is (at
      least 1e-10). PHREEQC gives each cell its water whatever its length,
      and lets nothing diffuse across a face where a porosity is below
      -multi_D's limit.
    */
    let mcd = null;
    if (t.mcd) {
      /*
        With stagnant cells PHREEQC moves each species into its stagnant cell
        at its own Dw, by -stagnant's mixing fraction for a mixing step taken
        as one for a whole shift and divided by the steps again (multi_D,
        find_J): what crosses in a shift falls as the steps grow -- a quarter,
        over a shift of 3600 s, at four times the steps (-time_step 3600 4).
      */
      if (t.stag) {
        no('it has stagnant cells (-stagnant) with -multi_D, which PHREEQC exchanges species by species at a rate that '
          + 'falls as its mixing steps grow (a quarter at four times as many): no model of the page follows that');
      }
      if (!alike(t.lengths)) {
        no('its cells are of different lengths: under -multi_D PHREEQC gives each cell its water whatever its length, '
          + 'where the page\'s cells hold water as they are long');
      }
      const por = t.stag && t.por ? t.stag.thm : t.por ? t.por[0] : Math.max(t.mcd.por, 1e-10);
      if (t.por && !(t.stag) && !alike(t.por)) {
        no('its cells have porosities of their own, which under -multi_D make each diffuse at its own rate, '
          + 'where the page\'s column has one');
      }
      if (por < t.mcd.lim) {
        no(`its porosity, ${fmtG(por, 6)}, is below -multi_D's limit, ${fmtG(t.mcd.lim, 6)}, where PHREEQC lets nothing diffuse`);
      }
      mcd = { ...t.mcd, porosity: por, factor: por ** t.mcd.n };
    }
    // The water at each end that the column needs: coming in, or held at a constant end.
    const leftSol = (t.dir > 0 && t.bc[0] === 3) || t.bc[0] === 1 ? 0 : -1;
    const rightSol = (t.dir < 0 && t.bc[1] === 3) || t.bc[1] === 1 ? n + 1 : -1;
    const ends = [leftSol, rightSol].filter((s) => s >= 0);
    // The stagnant cell behind cell i, as PHREEQC numbers it: n + 1 + i.
    const stag = t.stag;
    const stagOf = (i) => i + 1 + n;
    const cells = [`1-${n}`, ...(stag ? [`${n + 2}-${2 * n + 1}`] : []), ...ends.map(String)].join(' ');
    const equil = `${t.before}RUN_CELLS\n -cells ${cells}\n -time_step 0\nEND\n`;
    // Every cell alike: its water, what is on its exchangers and surfaces, its phases, reactants and gases.
    const extras = [...readAssemblage(t.before).map((a) => `EQUI("${a.name}")`),
      ...[...readKinetics(t.before).values()].flatMap((b) => b.comps.map((c) => `KIN("${c.name}")`)),
      ...[...readGasPhases(t.before).values()].flatMap((b) => b.comps.map((c) => `GAS("${c.name}")`)),
      ...[...readSolidSolutions(t.before).values()].flatMap((b) => b.flatMap((ss) => ss.comps.map((c) => `S_S("${c.name}")`)))];
    let rows;
    try {
      rows = runRows(o.engine, `${punchBlock(extras)}${equil}`);
    } catch (e) {
      no(`PHREEQC could not equilibrate its cells before the first shift: ${String(e.message || e).split('\n')[0]}`);
    }
    const last = new Map();
    for (const r of rows) last.set(Number(r.soln), r);
    for (let c = 1; c <= n; c++) if (!last.has(c)) no(`PHREEQC has no water for cell ${c}`);
    for (const s of ends) {
      if (!last.has(s)) no(`PHREEQC has no SOLUTION ${s}, the water ${s ? 'at its last end' : 'coming in'}`);
    }
    // PHREEQC leaves a cell without a stagnant water out of the exchange; the page's stagnant water is behind every cell.
    if (stag) {
      for (let i = 1; i <= n; i++) {
        if (!last.has(stagOf(i))) {
          no(`it has stagnant cells (-stagnant), and stagnant cell ${stagOf(i)}, behind cell ${i}, has no SOLUTION, where `
            + 'the page has stagnant water behind every cell');
        }
      }
    }
    /*
      Two cells alike: what is in them, PHREEQC's totals -- each element's,
      hydrogen and oxygen apart, which are mostly the water, and the protons
      beyond the water's, H - 2 O, which is its pH; each valence state's;
      what is on its exchangers and surfaces, and its phases' and
      reactants' amounts. Not its species: two cells defined alike come out
      of PHREEQC's convergence apart in those -- twenty of one water with
      nitrate, H+ by 5.7e-6 and O2 by 7.6e-5 -- where their totals, its mass
      balances, agree to 2e-14.
    */
    const differs = (a, b) => {
      if (Math.abs(a.tc - b.tc) > 1e-9) return 'its temperature';
      const totals = (r, states) => {
        const m = new Map();
        for (const [k, v] of r.elements) if (k.includes('(') === states) m.set(k, v);
        return m;
      };
      const ea = totals(a, false);
      const eb = totals(b, false);
      let scale = 0;
      for (const mm of [ea, eb]) for (const [k, v] of mm) if (k !== 'H' && k !== 'O') scale = Math.max(scale, Math.abs(v));
      if (!(scale > 0)) scale = 1e-3;
      const near = (x, y, rel = 1e-6) => Math.abs(x - y) <= rel * Math.max(Math.abs(x), Math.abs(y)) + 1e-12 * scale;
      const apart = (ma, mb, rel) => [...new Set([...ma.keys(), ...mb.keys()])]
        .find((k) => !near(ma.has(k) ? ma.get(k) : 0, mb.has(k) ? mb.get(k) : 0, rel));
      const el = apart(new Map([...ea].filter(([k]) => k !== 'H' && k !== 'O')),
        new Map([...eb].filter(([k]) => k !== 'H' && k !== 'O')));
      if (el) return el;
      const excess = (mm) => (mm.get('H') || 0) - 2 * (mm.get('O') || 0);
      if (Math.abs(excess(ea) - excess(eb)) > 1e-6 * scale) return 'its pH';
      // Valence states as PHREEQC's redox converges: a part in 1e4, and a part in 1e6 of the largest total.
      const sa = totals(a, true);
      const sb = totals(b, true);
      const vs = [...new Set([...sa.keys(), ...sb.keys()])].filter((k) => !/^(H|O)\(/.test(k))
        .find((k) => Math.abs((sa.get(k) || 0) - (sb.get(k) || 0)) > 1e-4 * Math.max(Math.abs(sa.get(k) || 0),
          Math.abs(sb.get(k) || 0)) + 1e-6 * scale);
      if (vs) return vs;
      const on = (r, what) => new Map([...r[what]].map(([k, e]) => [k, e.m]));
      const ex = apart(on(a, 'exchange'), on(b, 'exchange')) || apart(on(a, 'surface'), on(b, 'surface'));
      if (ex) return ex;
      const i = a.x.findIndex((v, j) => !near(Number(v), Number(b.x[j])));
      return i >= 0 ? extras[i] : null;
    };
    const one = last.get(1);
    /*
      THE CELLS' ZONES: runs of cells that come out alike, each started
      from its first cell's water -- cell 1's in <SPECIES>, the others' in
      <INITIAL> (waterToModel). At one temperature, the page's column has
      one; and what is on an exchanger or a surface in every zone or none,
      as the page's exchangers and surfaces are in every cell.
    */
    const zones = [{ lo: 1, hi: 1, rep: 1, row: null }];
    for (let c = 2; c <= n; c++) {
      const z = zones[zones.length - 1];
      if (differs(last.get(z.rep), last.get(c))) zones.push({ lo: c, hi: c, rep: c, row: null }); else z.hi = c;
    }
    const holds = (row, what) => [...row[what].values()].some((e) => e.m > 0);
    for (const z of zones.slice(1)) {
      const r = last.get(z.rep);
      if (Math.abs(r.tc - one.tc) > 1e-9) {
        no(`cell ${z.rep} starts at ${fmtG(r.tc, 6)} C and cell 1 at ${fmtG(one.tc, 6)} C, where the page's column has one `
          + 'temperature');
      }
      for (const [what, name] of [['exchange', 'an exchanger'], ['surface', 'a surface']]) {
        if (holds(r, what) !== holds(one, what)) {
          no(`${name} is in some of its cells and not in others (cell ${holds(one, what) ? z.rep : 1} has none), where the `
            + `page's ${name === 'an exchanger' ? 'exchangers are' : 'surfaces are'} in every cell`);
        }
      }
    }
    if (zones.length > 1 && (readGasPhases(t.before).size || readSolidSolutions(t.before).size)) {
      no('its cells start apart, and it has a gas phase or a solid solution, which the page does not write cell by cell');
    }
    /*
      THE STAGNANT CELLS' ZONES, behind the cells: runs of them alike, each
      as its first comes out of PHREEQC's equilibration -- the page's rock
      matrix starts as <SPECIES> says, cell 1's water, and the others are
      written in <INITIAL> aimed at it (waterToModel). `same`: alike with
      cell 1, which needs nothing written.
    */
    const szones = [];
    if (stag) {
      for (let i = 1; i <= n; i++) {
        const z = szones[szones.length - 1];
        if (z && !differs(last.get(z.rep), last.get(stagOf(i)))) z.hi = i;
        else szones.push({ lo: i, hi: i, rep: stagOf(i), row: null, same: !differs(one, last.get(stagOf(i))) });
      }
      for (const z of szones) {
        const r = last.get(z.rep);
        if (Math.abs(r.tc - one.tc) > 1e-9) {
          no(`stagnant cell ${z.rep} starts at ${fmtG(r.tc, 6)} C and cell 1 at ${fmtG(one.tc, 6)} C, where the page's column `
            + 'has one temperature');
        }
        for (const [what, name] of [['exchange', 'an exchanger'], ['surface', 'a surface']]) {
          if (holds(r, what) !== holds(one, what)) {
            no(`${name} is in ${holds(one, what) ? 'its cells and not in its stagnant cells' : 'its stagnant cells and not in '
              + 'its cells'} (stagnant cell ${z.rep}), where the page's ${name === 'an exchanger' ? 'exchangers are' : 'surfaces are'} `
              + 'in every cell, the stagnant ones too');
          }
        }
      }
      if (readGasPhases(t.before).size || readSolidSolutions(t.before).size) {
        no('it has stagnant cells, and a gas phase or a solid solution, which the page does not write cell by cell');
      }
    }
    for (const s of ends) {
      if (Math.abs(last.get(s).tc - one.tc) > 1e-9) {
        no(`SOLUTION ${s} is at ${fmtG(last.get(s).tc, 6)} C and the column at ${fmtG(one.tc, 6)} C: PHREEQC carries the `
          + 'heat as well, which the page does not');
      }
    }
    /*
      Each water takes a trace of every other -- the ends', each zone's and
      each stagnant zone's -- so that what only one of them has is a total
      that can be held everywhere. PHREEQC keeps a MIX from one run to the
      next, and RUN_CELLS takes a cell's MIX for its water: these have a
      number no cell has, and go when done.
    */
    const MIXED = 9999991;
    const TRACE = o.columnTrace || 1e-12;
    const mixed = (parts) => `MIX ${MIXED}\n${parts}`;
    const gone = `DELETE\n -mix ${MIXED}\nEND\n`;
    const behind = szones.filter((z) => !z.same);
    const waters = [...zones.map((z) => z.rep), ...behind.map((z) => z.rep), ...ends];
    const traced = (s) => `${mixed(` ${s} 1\n${waters.filter((x) => x !== s).map((x) => ` ${x} ${TRACE}\n`).join('')}`)}`;
    const side = (s) => {
      if (s < 0) return null;
      const r = runRows(o.engine, `${punchBlock()}${equil}${traced(s)}END\n${gone}`).pop();
      return new Map([...r.species].map(([k, [m]]) => [k, m]));
    };
    const left = side(leftSol);
    const right = side(rightSol);
    // A cell's water with its traces, put on what the cell holds.
    const inCell = (c, parts) => `${mixed(parts)}SAVE solution ${c}\nEND\n${gone}RUN_CELLS\n -cells ${c}\n -time_step 0\nEND\n`;
    const others = waters.length > 1;
    const cellInput = `${equil}${others ? inCell(1, traced(1).slice(`MIX ${MIXED}\n`.length)) : 'RUN_CELLS\n -cells 1\n'
      + ' -time_step 0\nEND\n'}`;
    // Each other zone's first cell as it starts, and each stagnant zone's, its phases', reactants' and water's amounts too.
    const zx = [...extras, 'TOT("water")'];
    for (const z of [...zones.slice(1), ...behind]) {
      z.row = runRows(o.engine, `${punchBlock(zx)}${equil}${inCell(z.rep, traced(z.rep).slice(`MIX ${MIXED}\n`.length))}`).pop();
      z.extras = zx;
    }
    /*
      The species that matter anywhere the column goes: in each zone's water,
      in the water at each end, and in each zone's first cell with that
      water, alone and half and half with its own, put on what the cell
      holds -- calcium coming into a column with none goes onto its
      exchanger as CaX2.
    */
    const keep = new Set();
    const keepOn = new Set();
    // The most of each species any of them has: what cell 1 has a trace of (waterToModel's elsewhere).
    const keepAt = new Map();
    const take = (r) => {
      for (const [k, [m]] of r.species) {
        if (!(m >= floor)) continue;
        keep.add(k);
        if (!(keepAt.get(k) >= m)) keepAt.set(k, m);
      }
      for (const [k, e] of r.exchange) if (e.m >= floor) keepOn.add(k);
      for (const [k, e] of r.surface) if (e.m >= floor) keepOn.add(k);
    };
    // A stagnant cell sees what comes in only through its cell, and in the end the same water.
    for (const z of [...zones.slice(1), ...behind]) take(z.row);
    for (const s of ends) {
      take(last.get(s));
      for (const z of [...zones, ...behind]) {
        for (const mix of [` ${s} 1\n`, ` ${z.rep} 0.5\n ${s} 0.5\n`]) {
          take(runRows(o.engine, `${punchBlock()}${equil}${inCell(z.rep, mix)}`).pop());
        }
      }
    }
    const corr = t.correctDisp && t.dir ? 1 + (t.bc[0] === 3 ? 1 / n : 0) + (t.bc[1] === 3 ? 1 / n : 0) : 1;
    return { t, cellInput, left, right, leftSol, rightSol, keep, keepAt, keepOn, corr, tc: one.tc, trace: TRACE, zones,
      stag: stag ? { ...stag, zones: szones } : null, mcd };
  }

  /*
    A RATE PROGRAM AS A RATE LAW. PHREEQC runs a rate's BASIC at each step
    of its integration, with M the reactant's moles, M0 its initial moles,
    PARM(i) its -parms, TIME the step, and the program SAVEs the moles that
    react in it. Here the program is run once, symbolically: each variable
    holds the expression it comes to, numbers worked out as they go, and
    what the water decides -- M, an activity, a saturation, the
    temperature -- left standing, in rtm.html's words. A condition on those
    becomes step() (1 where it holds, 0 where not, PHREEQC's comparison
    giving 1 and 0); an IF that only sets variables sets each to its two
    values weighed by the condition, and one that jumps (GOTO, END, SAVE)
    takes both ways, each weighed by its own condition. The rate is what is
    saved, over TIME, summed over the ways. PHREEQC's own arithmetic is
    kept where it differs: x/0 is 0, 0^y is 0, and a unary minus binds
    before ^ (10^-pk is 10^(-pk), and -x^2 is (-x)^2). A power whose
    exponent reads the water is written exp(y ln x), the page's rate laws
    taking powers to exponents that do not.
  */
  const BASIC_FUNCS = new Set(['act', 'la', 'lm', 'lg', 'mol', 'tot', 'gamma', 'si', 'sr', 'parm', 'kin', 'equi',
    'sqrt', 'sqr', 'exp', 'log', 'log10', 'abs', 'sgn', 'sin', 'cos', 'tan', 'arctan', 'ceil', 'floor']);
  const BASIC_VALUES = new Set(['m', 'm0', 'time', 'tc', 'tk', 'mu', 'soln_vol', 'sim_time', 'total_time']);
  const BASIC_WORDS = new Set(['and', 'or', 'xor', 'not', 'mod', 'then', 'else', 'to', 'step']);

  /** One line of BASIC as tokens: {k: 'num'|'str'|'id'|'op', v}. */
  function basicTokens(text, line) {
    const out = [];
    for (let i = 0; i < text.length;) {
      const ch = text[i];
      if (/\s/.test(ch)) { i++; continue; }
      if (ch === '"') {
        const end = text.indexOf('"', i + 1);
        if (end < 0) throw new Error(`line ${line}: a string is never closed`);
        out.push({ k: 'str', v: text.slice(i + 1, end) });
        i = end + 1;
        continue;
      }
      const num = /^(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][-+]?[0-9]+)?/.exec(text.slice(i));
      if (num) { out.push({ k: 'num', v: Number(num[0]) }); i += num[0].length; continue; }
      const id = /^[A-Za-z_][A-Za-z0-9_]*\$?/.exec(text.slice(i));
      if (id) {
        out.push({ k: 'id', v: id[0].toLowerCase(), raw: id[0] });
        i += id[0].length;
        // REM: the rest of the line is words.
        if (id[0].toLowerCase() === 'rem') break;
        continue;
      }
      const op = /^(<=|>=|<>|[-+*/^()[\]=<>,:])/.exec(text.slice(i));
      if (op) {
        out.push({ k: 'op', v: op[0] === '[' ? '(' : op[0] === ']' ? ')' : op[0] });
        i += op[0].length;
        continue;
      }
      throw new Error(`line ${line}: "${ch}" is not BASIC this page reads`);
    }
    return out;
  }

  /** Expressions of the rate law, worked out where they can be: rtm.html's own words in `s`. */
  const RL = {
    num: (v) => ({ k: 'n', v }),
    // An atom of the page's: w, read by the Jacobian (the water); d, moving otherwise (TK, TC, t).
    atom: (s, w, d) => ({ k: 'a', s, w: !!w, d: !!d }),
    isNum: (a, v) => a.k === 'n' && (v === undefined || a.v === v),
  };
  // A number, or a name for one (M0, PARM(i), a constant of the program): its value, else undefined.
  const numOf = (a) => (a.k === 'n' ? a.v : a.k === 'ref' && a.value && a.value.k === 'n' ? a.value.v : undefined);
  const flagsOf = (...xs) => ({ w: xs.some((x) => x.w), d: xs.some((x) => x.d), t: xs.some((x) => x.t) });
  function rlBin(op, l, r) {
    if (l.k === 'n' && r.k === 'n') {
      switch (op) {
        case '+': return RL.num(l.v + r.v);
        case '-': return RL.num(l.v - r.v);
        case '*': return RL.num(l.v * r.v);
        case '/': return RL.num(r.v !== 0 ? l.v / r.v : 0);
        default: break;
      }
    }
    if (op === '+') { if (RL.isNum(l, 0)) return r; if (RL.isNum(r, 0)) return l; }
    if (op === '-' && RL.isNum(r, 0)) return l;
    if (op === '-' && RL.isNum(l, 0)) return rlNeg(r);
    // 1 - (1 - x), a condition turned twice: x.
    if (op === '-' && RL.isNum(l, 1) && r.k === 'bin' && r.op === '-' && RL.isNum(r.l, 1)) return r.r;
    if (op === '*') {
      if (RL.isNum(l, 0) || RL.isNum(r, 0)) return RL.num(0);
      if (RL.isNum(l, 1)) return r;
      if (RL.isNum(r, 1)) return l;
    }
    if (op === '/') {
      // PHREEQC's BASIC: x/0 is 0.
      if (RL.isNum(r, 0)) return RL.num(0);
      if (RL.isNum(r, 1)) return l;
      if (RL.isNum(l, 0)) return RL.num(0);
    }
    return { k: 'bin', op, l, r, ...flagsOf(l, r), b: (op === '*' && l.b && r.b) || undefined };
  }
  function rlNeg(a) {
    if (a.k === 'n') return RL.num(-a.v);
    if (a.k === 'neg') return a.a;
    return { k: 'neg', a, ...flagsOf(a) };
  }
  function rlFn(f, a) {
    if (a.k === 'n') {
      const v = { exp: Math.exp, ln: Math.log, log10: Math.log10, sqrt: Math.sqrt, abs: Math.abs, sign: Math.sign,
        step: (x) => (x > 0 ? 1 : 0), ramp: (x) => (x > 0 ? x : 0) }[f](a.v);
      if (Number.isFinite(v)) return RL.num(v);
    }
    return { k: 'fn', f, a, ...flagsOf(a), b: f === 'step' || undefined };
  }
  /** PHREEQC's x^y: x > 0 exp(y ln x); 0 for x = 0 whatever y; a negative x to a whole y only. */
  function rlPow(x, y) {
    if (x.k === 'n' && y.k === 'n') {
      if (x.v > 0) return RL.num(Math.exp(y.v * Math.log(x.v)));
      if (x.v === 0) return RL.num(0);
      if (y.v !== Math.trunc(y.v)) throw new Error('a negative number to a fractional power, which PHREEQC refuses');
      const v = Math.exp(y.v * Math.log(-x.v));
      return RL.num(Math.trunc(y.v) % 2 ? -v : v);
    }
    if (RL.isNum(x, 0)) return RL.num(0);
    if (numOf(y) !== undefined) {
      if (numOf(y) === 1) return x;
      // 0^0 is 0 in PHREEQC's BASIC, anything else to 0 is 1.
      if (numOf(y) === 0) return rlBin('+', rlFn('step', x), rlFn('step', rlNeg(x)));
    }
    if (y.w) {
      // An exponent that reads the water: exp(y ln x).
      const ln = x.k === 'n' ? RL.num(Math.log(x.v)) : rlFn('ln', x);
      return rlFn('exp', rlBin('*', y, ln));
    }
    return { k: 'bin', op: '^', l: x, r: y, ...flagsOf(x, y) };
  }
  /** A comparison, PHREEQC's 1 or 0. */
  function rlRel(op, a, b) {
    const x = numOf(a);
    const y = numOf(b);
    if (x !== undefined && y !== undefined) {
      const v = { '=': x === y, '<>': x !== y, '<': x < y, '>': x > y, '<=': x <= y, '>=': x >= y }[op];
      return RL.num(v ? 1 : 0);
    }
    const d = rlBin('-', a, b);
    const gt = rlFn('step', d);
    const lt = rlFn('step', rlNeg(d));
    const one = RL.num(1);
    let out;
    switch (op) {
      case '>': out = gt; break;
      case '<': out = lt; break;
      case '>=': out = rlBin('-', one, lt); break;
      case '<=': out = rlBin('-', one, gt); break;
      case '=': out = rlBin('*', rlBin('-', one, gt), rlBin('-', one, lt)); break;
      default: out = rlBin('-', one, rlBin('*', rlBin('-', one, gt), rlBin('-', one, lt))); break;
    }
    return { ...out, b: true };
  }
  const isBool = (a) => (a.k === 'n' ? a.v === 0 || a.v === 1 : !!a.b);

  /** The expression as rtm.html writes it. */
  function rlText(a, ctx = 0) {
    const wrap = (s, p) => (p < ctx ? `(${s})` : s);
    switch (a.k) {
      case 'n': {
        const s = String(a.v);
        return a.v < 0 && ctx > 1 ? `(${s})` : s;
      }
      case 'a': return a.s;
      case 'ref': return a.name;
      case 'time': return 'TIME';
      case 'neg': return wrap(`-${rlText(a.a, 4)}`, 2);
      case 'fn': return `${a.f}(${rlText(a.a, 0)})`;
      case 'bin': {
        if (a.op === '+' || a.op === '-') return wrap(`${rlText(a.l, 1)} ${a.op} ${rlText(a.r, 2)}`, 1);
        if (a.op === '*' || a.op === '/') return wrap(`${rlText(a.l, 2)}${a.op}${rlText(a.r, 3)}`, 2);
        return wrap(`${rlText(a.l, 4)}^${rlText(a.r, 3)}`, 3);
      }
      default: return '?';
    }
  }

  /** The moles a way saves, over TIME: the rate, or null where TIME is not a factor of it. */
  function overTime(a) {
    if (!a.t) return RL.isNum(a, 0) ? a : null;
    switch (a.k) {
      case 'time': return RL.num(1);
      case 'neg': { const x = overTime(a.a); return x && rlNeg(x); }
      case 'ref': return a.over || null;
      case 'bin': {
        if (a.op === '+' || a.op === '-') {
          const l = overTime(a.l);
          const r = overTime(a.r);
          return l && r ? rlBin(a.op, l, r) : null;
        }
        if (a.op === '*') {
          if (a.l.t && !a.r.t) { const x = overTime(a.l); return x && rlBin('*', x, a.r); }
          if (a.r.t && !a.l.t) { const x = overTime(a.r); return x && rlBin('*', a.l, x); }
          return null;
        }
        if (a.op === '/' && a.l.t && !a.r.t) { const x = overTime(a.l); return x && rlBin('/', x, a.r); }
        return null;
      }
      default: return null;
    }
  }

  /**
   * A RATES program (readRates' entry) as a rate law. `ctx` says how the
   * water is read, in the model's words:
   *   m        the reactant's moles, M, as text: 'ramp([Calcite])'
   *   m0, parms  M0 and PARM(i), numbers
   *   W        PHREEQC's kilograms of water, which TOT("water") is
   *   phase(name, 'SI'|'SR')  the saturation as text, or null where the database has no such phase
   *   act(name), mol(name)   '{X}' and '[X]', or null where the water has no such species
   *   tot(label)  the total of an element or a valence state as text, or null where the water has none
   *   kin(name), equi(name)  another reactant's or a mineral's moles as text, or null
   *   solnVol  the water's volume, L (SOLN_VOL), or null
   * Returns { r, names: [[name, text]] }, the law and the names it uses in
   * order; throws an Error saying what the program does that a rate law
   * here cannot.
   */
  function rateLaw(rate, ctx) {
    // The lines: number and tokens; DATA gathered, with the line each comes from.
    // The lines by number, as BASIC keeps them, a number given again replacing the line.
    const byNum = new Map();
    for (const src of rate.lines) {
      const m = /^([0-9]+)\s*(.*)$/.exec(src);
      byNum.set(Number(m[1]), { num: Number(m[1]), tokens: basicTokens(m[2], m[1]), src });
    }
    const lines = [...byNum.values()].sort((a, b) => a.num - b.num);
    // A variable as the program first spells it.
    const spelling = new Map();
    for (const ln of lines) for (const t of ln.tokens) if (t.k === 'id' && !spelling.has(t.v)) spelling.set(t.v, t.raw);
    const data = [];
    for (const ln of lines) {
      const tk = ln.tokens;
      if (!tk.length || tk[0].k !== 'id' || tk[0].v !== 'data') continue;
      let sign = 1;
      for (const t of tk.slice(1)) {
        if (t.k === 'op' && t.v === '-') { sign = -1; continue; }
        if (t.k === 'num') { data.push({ line: ln.num, v: sign * t.v }); sign = 1; }
      }
    }
    // The names the law will use, in the order made.
    const names = [];
    const taken = new Set(['r', 'rb', 'on', 'k', 'kf', 'kb', ...['I', 'TK', 'TC', 't', 'SI', 'SR', 'exp', 'log', 'ln',
      'log10', 'sqrt', 'abs', 'sign', 'step', 'ramp', 'min', 'max', 'pow']]);
    const nameFor = (base) => {
      let n = base;
      for (let i = 2; taken.has(n); i++) n = `${base}_${i}`;
      taken.add(n);
      return n;
    };
    const ref = (base, value) => {
      if (value.k === 'n' && base === null) return value;
      if (value.k === 'a' || value.k === 'ref' || (value.k === 'n' && base === null)) return value;
      if (value.k === 'time') return value;
      const name = nameFor(spelling.get(base) || base);
      const r = { k: 'ref', name, value, w: value.w, d: value.d, t: value.t, b: value.b };
      if (value.t) {
        // Moles over a step: kept as the rate it is per TIME, for overTime.
        r.over = overTime(value);
        if (!r.over) throw new Error(`${base} goes with TIME other than as moles in a step, rate times TIME`);
      }
      names.push(r);
      return r;
    };
    const fixedNames = new Map();
    const fixed = (key, value) => {
      if (!fixedNames.has(key)) {
        const name = nameFor(key);
        const r = { k: 'ref', name, value, w: value.w, d: value.d };
        names.push(r);
        fixedNames.set(key, r);
      }
      return fixedNames.get(key);
    };
    const str = (node) => {
      if (node.t !== 'str') throw new Error('a name is given other than as a "string"');
      return node.v;
    };
    const missing = (what) => { throw new Error(what); };

    // Expressions: PHREEQC's precedence (PBasic expr, andexpr, relexpr, sexpr, term, upexpr, factor).
    function parseExpr(st) {
      const peek = () => st.tk[st.i];
      const isOp = (v) => peek() && peek().k === 'op' && peek().v === v;
      const isWord = (v) => peek() && peek().k === 'id' && peek().v === v;
      const next = () => st.tk[st.i++];
      function factor() {
        const t = next();
        if (!t) throw new Error(`line ${st.line}: an expression ends too soon`);
        if (t.k === 'num') return { t: 'num', v: t.v };
        if (t.k === 'str') return { t: 'str', v: t.v };
        if (t.k === 'op' && t.v === '(') {
          const e = expr();
          if (!isOp(')')) throw new Error(`line ${st.line}: a bracket is never closed`);
          next();
          return e;
        }
        if (t.k === 'op' && t.v === '-') return { t: 'neg', a: factor() };
        if (t.k === 'op' && t.v === '+') return factor();
        if (t.k === 'id' && t.v === 'not') return { t: 'not', a: factor() };
        if (t.k === 'id') {
          if (BASIC_FUNCS.has(t.v)) {
            if (!isOp('(')) throw new Error(`line ${st.line}: ${t.v.toUpperCase()} needs its argument in brackets`);
            next();
            const args = [expr()];
            while (isOp(',')) { next(); args.push(expr()); }
            if (!isOp(')')) throw new Error(`line ${st.line}: a bracket is never closed`);
            next();
            return { t: 'call', name: t.v, args };
          }
          if (BASIC_VALUES.has(t.v)) return { t: 'value', name: t.v };
          if (isOp('(') || t.v.endsWith('$')) {
            throw new Error(`line ${st.line}: ${t.v.toUpperCase()}, which a rate law here cannot read`);
          }
          return { t: 'var', name: t.v };
        }
        throw new Error(`line ${st.line}: "${t.v}" where a value should be`);
      }
      function upexpr() {
        const n = factor();
        if (isOp('^')) { next(); return { t: 'bin', op: '^', l: n, r: upexpr() }; }
        return n;
      }
      function term() {
        let n = upexpr();
        while (isOp('*') || isOp('/') || isWord('mod')) {
          const op = next().v;
          if (op === 'mod') throw new Error(`line ${st.line}: MOD, which a rate law here cannot write`);
          n = { t: 'bin', op, l: n, r: upexpr() };
        }
        return n;
      }
      function sexpr() {
        let n = term();
        while (isOp('+') || isOp('-')) { const op = next().v; n = { t: 'bin', op, l: n, r: term() }; }
        return n;
      }
      function relexpr() {
        let n = sexpr();
        while (peek() && peek().k === 'op' && ['=', '<>', '<', '>', '<=', '>='].includes(peek().v)) {
          const op = next().v;
          n = { t: 'rel', op, l: n, r: sexpr() };
        }
        return n;
      }
      function andexpr() {
        let n = relexpr();
        while (isWord('and')) { next(); n = { t: 'and', l: n, r: relexpr() }; }
        return n;
      }
      function expr() {
        let n = andexpr();
        while (isWord('or') || isWord('xor')) {
          const op = next().v;
          if (op === 'xor') throw new Error(`line ${st.line}: XOR, which a rate law here cannot write`);
          n = { t: 'or', l: n, r: andexpr() };
        }
        return n;
      }
      return expr();
    }

    // Values: the program's expressions in the page's words.
    function value(node, env) {
      switch (node.t) {
        case 'num': return RL.num(node.v);
        case 'str': throw new Error('a string where a number should be');
        case 'neg': return rlNeg(value(node.a, env));
        case 'not': {
          const a = value(node.a, env);
          if (a.k !== 'n') throw new Error('NOT of what the water decides, which PHREEQC takes bit by bit');
          return RL.num(-Math.trunc(a.v) - 1);
        }
        case 'var': return env.vars.has(node.name) ? env.vars.get(node.name) : RL.num(0);
        case 'value': return builtin(node.name);
        case 'bin': {
          const l = value(node.l, env);
          const r = value(node.r, env);
          return node.op === '^' ? rlPow(l, r) : rlBin(node.op, l, r);
        }
        case 'rel': return rlRel(node.op, value(node.l, env), value(node.r, env));
        case 'and': case 'or': {
          const l = value(node.l, env);
          const r = value(node.r, env);
          if (l.k === 'n' && r.k === 'n') {
            return RL.num(node.t === 'and' ? (Math.trunc(l.v) & Math.trunc(r.v)) : (Math.trunc(l.v) | Math.trunc(r.v)));
          }
          if (!isBool(l) || !isBool(r)) throw new Error(`${node.t.toUpperCase()} of other than comparisons`);
          const v = node.t === 'and' ? rlBin('*', l, r) : rlBin('-', rlBin('+', l, r), rlBin('*', l, r));
          return { ...v, b: true };
        }
        case 'call': return call(node.name, node.args.map((a) => (a.t === 'str' ? a : value(a, env))));
        default: throw new Error('an expression this page does not read');
      }
    }
    function builtin(name) {
      switch (name) {
        case 'm': return fixed('m', RL.atom(ctx.m, true, false));
        case 'm0': return fixed('m0', RL.num(ctx.m0));
        case 'time': return { k: 'time', t: true };
        case 'tc': return RL.atom('TC', false, true);
        case 'tk': return RL.atom('TK', false, true);
        case 'mu': return RL.atom('I', true, false);
        case 'sim_time': case 'total_time': return RL.atom('t', false, true);
        case 'soln_vol':
          if (!(ctx.solnVol > 0)) missing('SOLN_VOL, the water\'s volume, which PHREEQC did not give');
          return fixed('soln_vol', RL.num(ctx.solnVol));
        default: return missing(`${name.toUpperCase()}, which a rate law here cannot read`);
      }
    }
    function call(name, args) {
      const one = args[0];
      const num = (a) => (a && a.k === 'n' ? a.v : NaN);
      switch (name) {
        case 'parm': {
          const i = num(one);
          if (!(Number.isInteger(i) && i >= 1 && i <= ctx.parms.length)) {
            missing(`PARM(${Number.isFinite(i) ? i : '?'}), which -parms does not give`);
          }
          const p = ctx.parms[i - 1];
          if (typeof p !== 'number') missing(`PARM(${i}), "${p}", which is no number`);
          return fixed(`p${i}`, RL.num(p));
        }
        case 'si': case 'sr': {
          const s = ctx.phase(str(one), name.toUpperCase());
          if (s === null) missing(`${name.toUpperCase()}("${one.v}"): the database has no such phase`);
          return RL.atom(s, true, false);
        }
        case 'act': case 'mol': case 'la': case 'lm': case 'lg': case 'gamma': {
          const sp = str(one);
          const a = ctx.act(sp);
          const c = ctx.mol(sp);
          if (name === 'act') return a === null ? RL.num(0) : RL.atom(a, true, false);
          if (name === 'mol') return c === null ? RL.num(0) : RL.atom(c, true, false);
          // PHREEQC's -999.999 for a species the water has none of.
          if (name === 'la') return a === null ? RL.num(-999.999) : rlFn('log10', RL.atom(a, true, false));
          if (name === 'lm') return c === null ? RL.num(-999.999) : rlFn('log10', RL.atom(c, true, false));
          if (a === null || c === null) return RL.num(name === 'gamma' ? 0 : 0);
          const g = rlBin('/', RL.atom(a, true, false), RL.atom(c, true, false));
          return name === 'gamma' ? g : rlFn('log10', g);
        }
        case 'tot': {
          const label = str(one);
          if (/^water$/i.test(label)) return RL.num(ctx.W);
          const s = ctx.tot(label);
          return s === null ? RL.num(0) : RL.atom(s, true, false);
        }
        case 'kin': case 'equi': {
          const s = ctx[name](str(one));
          return s === null ? RL.num(0) : RL.atom(s, true, false);
        }
        case 'sqrt': return rlFn('sqrt', one);
        case 'sqr': return rlBin('*', one, one);
        case 'exp': return rlFn('exp', one);
        case 'log': return rlFn('ln', one);
        case 'log10': return rlFn('log10', one);
        case 'abs': return rlFn('abs', one);
        case 'sgn': return rlFn('sign', one);
        default: {
          const f = { sin: Math.sin, cos: Math.cos, tan: Math.tan, arctan: Math.atan, ceil: Math.ceil,
            floor: Math.floor }[name];
          if (f && one && one.k === 'n') return RL.num(f(one.v));
          return missing(`${name.toUpperCase()} of what the water decides, which a rate law here cannot write`);
        }
      }
    }

    /*
      Running it: ways through the program, each with its condition, its
      variables, where it is, and what it saved. A way ends at END or the
      last line.
    */
    const lineAt = new Map(lines.map((ln, i) => [ln.num, i]));
    const ways = [{ cond: RL.num(1), vars: new Map(), li: 0, ti: 0, saved: null, dataAt: 0 }];
    const ended = [];
    let made = 1;
    const clone = (w) => ({ ...w, vars: new Map(w.vars) });
    // The THEN and ELSE of an IF: token positions in the line, as PHREEQC's cmdif finds them.
    const elseOf = (tk, from) => {
      let depth = 0;
      for (let i = from; i < tk.length; i++) {
        if (tk[i].k !== 'id') continue;
        if (tk[i].v === 'if') depth++;
        if (tk[i].v === 'else') { if (depth === 0) return i; depth--; }
      }
      return -1;
    };
    const jumps = (tk, a, b) => tk.slice(a, b).some((t) => t.k === 'id' && ['goto', 'go', 'end', 'stop', 'save', 'if',
      'return', 'gosub'].includes(t.v)) || (tk[a] && tk[a].k === 'num');
    function gotoLine(w, num, from) {
      if (!lineAt.has(num)) throw new Error(`line ${from}: GOTO ${num}, a line the program does not have`);
      if (num <= from) throw new Error(`line ${from}: GOTO ${num} goes back, a loop, which a rate law cannot be`);
      w.li = lineAt.get(num);
      w.ti = 0;
    }
    // One statement of way w at its place; returns false where the way has ended.
    function statement(w) {
      const ln = lines[w.li];
      const tk = ln.tokens;
      const st = { tk, i: w.ti, line: ln.num };
      const t = tk[st.i];
      const endLine = () => { w.li++; w.ti = 0; };
      // After a statement: ':' goes on, ELSE skips the rest of the line, the end of the line the next.
      const after = () => {
        const n = tk[st.i];
        if (!n) { endLine(); return; }
        if (n.k === 'op' && n.v === ':') { w.ti = st.i + 1; return; }
        if (n.k === 'id' && n.v === 'else') { endLine(); return; }
        throw new Error(`line ${ln.num}: "${n.v}" after a statement`);
      };
      if (!t) { endLine(); return true; }
      if (t.k === 'op' && t.v === ':') { w.ti = st.i + 1; return true; }
      if (t.k !== 'id') throw new Error(`line ${ln.num}: "${t.v}" where a statement should be`);
      const kw = t.v;
      if (kw === 'rem') { endLine(); return true; }
      if (kw === 'data' || kw === 'print' || kw === 'punch') {
        // DATA was read before; PRINT and PUNCH write, and change nothing.
        let i = st.i + 1;
        while (tk[i] && !(tk[i].k === 'op' && tk[i].v === ':') && !(tk[i].k === 'id' && tk[i].v === 'else')) i++;
        st.i = i;
        after();
        return true;
      }
      if (kw === 'restore') {
        st.i++;
        const n = tk[st.i] && tk[st.i].k === 'num' ? tk[st.i++].v : 0;
        w.dataAt = data.findIndex((d) => d.line >= n);
        if (w.dataAt < 0) w.dataAt = data.length;
        after();
        return true;
      }
      if (kw === 'read') {
        st.i++;
        for (;;) {
          const v = tk[st.i];
          if (!v || v.k !== 'id') throw new Error(`line ${ln.num}: READ needs a variable`);
          if (w.dataAt >= data.length) throw new Error(`line ${ln.num}: READ past the last DATA`);
          w.vars.set(v.v, RL.num(data[w.dataAt++].v));
          st.i++;
          if (tk[st.i] && tk[st.i].k === 'op' && tk[st.i].v === ',') { st.i++; continue; }
          break;
        }
        after();
        return true;
      }
      if (kw === 'end' || kw === 'stop') return false;
      if (kw === 'goto' || (kw === 'go' && tk[st.i + 1] && tk[st.i + 1].v === 'to')) {
        st.i += kw === 'go' ? 2 : 1;
        const n = tk[st.i];
        if (!n || n.k !== 'num') throw new Error(`line ${ln.num}: GOTO needs a line number`);
        gotoLine(w, n.v, ln.num);
        return true;
      }
      if (kw === 'save') {
        st.i++;
        w.saved = value(parseExpr(st), w);
        after();
        return true;
      }
      if (kw === 'if') {
        st.i++;
        const cond = value(parseExpr(st), w);
        if (!(tk[st.i] && tk[st.i].k === 'id' && tk[st.i].v === 'then')) throw new Error(`line ${ln.num}: IF without THEN`);
        const thenAt = st.i + 1;
        const elseAt = elseOf(tk, thenAt);
        const elseFrom = elseAt < 0 ? -1 : elseAt + 1;
        // THEN or ELSE with a line number: a GOTO.
        const go = (ww, at) => {
          if (at >= 0 && tk[at] && tk[at].k === 'num') { gotoLine(ww, tk[at].v, ln.num); return; }
          if (at < 0 || at >= tk.length) { ww.li = w.li + 1; ww.ti = 0; return; }
          ww.ti = at;
          ww.li = w.li;
        };
        if (cond.k === 'n') {
          if (cond.v !== 0) go(w, thenAt); else go(w, elseFrom);
          return true;
        }
        const c = cond;
        const notC = rlBin('-', RL.num(1), c);
        const thenEnd = elseAt < 0 ? tk.length : elseAt;
        if (!jumps(tk, thenAt, thenEnd) && (elseFrom < 0 || !jumps(tk, elseFrom, tk.length))) {
          // Only variables set: each to its two values, weighed.
          const a = clone(w);
          const b = clone(w);
          const runPart = (ww, from, to) => {
            ww.li = w.li;
            ww.ti = from;
            while (ww.li === w.li && ww.ti < to) statement(ww);
          };
          runPart(a, thenAt, thenEnd);
          if (elseFrom >= 0) runPart(b, elseFrom, tk.length);
          const keys = new Set([...a.vars.keys(), ...b.vars.keys()]);
          for (const key of keys) {
            const va = a.vars.has(key) ? a.vars.get(key) : RL.num(0);
            const vb = b.vars.has(key) ? b.vars.get(key) : RL.num(0);
            if (va === vb) { w.vars.set(key, va); continue; }
            const mixed = rlBin('+', rlBin('*', c, va), rlBin('*', notC, vb));
            w.vars.set(key, ref(key, mixed));
          }
          if (a.saved !== b.saved) throw new Error(`line ${ln.num}: SAVE in an IF`);
          w.dataAt = a.dataAt;
          w.li++;
          w.ti = 0;
          return true;
        }
        // It jumps: both ways, each with its condition.
        const other = clone(w);
        w.cond = rlBin('*', w.cond, c);
        other.cond = rlBin('*', other.cond, notC);
        go(w, thenAt);
        go(other, elseFrom);
        ways.push(other);
        if (++made > 64) throw new Error('the program takes more than 64 ways through it');
        return true;
      }
      // An assignment, LET or not.
      if (kw === 'let') st.i++;
      const v = tk[st.i];
      if (!v || v.k !== 'id' || !(tk[st.i + 1] && tk[st.i + 1].k === 'op' && tk[st.i + 1].v === '=')) {
        throw new Error(`line ${ln.num}: ${kw.toUpperCase()}, which a rate law here cannot be made of`);
      }
      if (BASIC_FUNCS.has(v.v) || BASIC_VALUES.has(v.v) || BASIC_WORDS.has(v.v) || v.v.endsWith('$')) {
        throw new Error(`line ${ln.num}: ${v.v.toUpperCase()} cannot be set`);
      }
      st.i += 2;
      w.vars.set(v.v, ref(v.v, value(parseExpr(st), w)));
      after();
      return true;
    }
    while (ways.length) {
      const w = ways.pop();
      for (let guard = 0; ; guard++) {
        if (guard > 100000) throw new Error('the program does not end');
        if (w.li >= lines.length) { ended.push(w); break; }
        if (!statement(w)) { ended.push(w); break; }
      }
    }
    // The rate: what each way saved, over TIME, weighed by its condition.
    let law = RL.num(0);
    for (const w of ended) {
      if (w.saved === null) throw new Error('a way through the program saves nothing, where PHREEQC would stop');
      const per = overTime(w.saved);
      if (!per) throw new Error('what it saves is not moles in a step, a rate times TIME');
      law = rlBin('+', law, rlBin('*', w.cond, per));
    }
    if (ctx.W !== 1) law = rlBin('/', law, RL.num(ctx.W));
    // The names the rate reads, and those they read, in the order made.
    const used = new Set();
    const mark = (a) => {
      if (!a || typeof a !== 'object') return;
      if (a.k === 'ref') {
        if (used.has(a.name)) return;
        used.add(a.name);
        mark(a.over || a.value);
        return;
      }
      for (const key of ['a', 'l', 'r']) if (a[key]) mark(a[key]);
    };
    mark(law);
    return {
      r: rlText(law),
      names: names.filter((n) => used.has(n.name)).map((n) => [n.name, rlText(n.over || n.value)]),
    };
  }

  /* ======================================================================
     A water into a model
     ====================================================================== */

  /**
   * @param {object} o
   *   engine      { run(text) }
   *   database    { name, text }      the database PHREEQC was given
   *   water       { name, text }      PHREEQC input holding the water
   *   solution    SOLUTION number to use (default: the last calculation)
   *   floor       mol/kgw below which a species is left out (1e-20)
   *   activity    the activity coefficients follow the ionic strength:
   *               ACTIVITY = debye-huckel at the water's temperature, each
   *               species' -gamma as a= and b=, the relations with their
   *               water and the database's own log K -- or with a SIT
   *               database ACTIVITY = sit, its interaction coefficients
   *               between the species written in <SIT>; with a Pitzer one
   *               ACTIVITY = pitzer, its parameters between them in
   *               <PITZER> with their terms in the temperature; else each log K is
   *               conditional, the coefficients at this water folded in
   *   exact       hold every relation exactly during the run: EQUILIBRATE =
   *               always, no kf, each relation an algebraic equation
   *   phases      with exact: the input's EQUILIBRIUM_PHASES become minerals,
   *               at the amounts PHREEQC left, each held at its saturation
   *               index while there is any of it
   *   exchange    with exact, unless false: an exchanger PHREEQC's last
   *               calculation holds becomes an exchanger and the species on
   *               it, at the molalities PHREEQC put there
   *   redox       with exact, unless false: each species the database
   *               writes with electrons is tied to the electron, e-, by its
   *               reaction, so that every couple is in equilibrium at one pe
   *               as in PHREEQC, starting at this water's; a phase that
   *               dissolves with electrons can then be a mineral. Without it
   *               each valence state keeps its own total
   *   relax       ... or as fast pairs, each with the kf that makes it relax
   *               back at this rate per second here
   *   kf          ... or as fast pairs all with this one forward constant
   *   D, dw       one diffusion coefficient for every species; or the
   *               database's -dw where it has one
   *   date        the date to stamp (default today)
   * @returns {{text, report, water}}
   */
  function waterToModel(o) {
    const floor = o.floor != null ? o.floor : 1e-20;
    if (o.exact && (o.relax || o.kf)) {
      throw new Error('The relations are held either exactly or as fast pairs with a kf, not both.');
    }
    /*
      A TRANSPORT (or ADVECTION) in the input: its column, every cell
      starting from cell 1's water as PHREEQC equilibrates it before the
      first shift, with the water at each end flowing in or holding it
      (columnSetup). What follows is that water's, as for any other.
    */
    const column = o.transport === false ? null : columnSetup(o, floor);
    if (column) {
      if (!o.exact) {
        throw new Error(`A column needs the relations held exactly, as the input's ${column.t.kind} holds them in every `
          + 'cell at every shift.');
      }
      o = { ...o, water: { ...o.water, text: column.cellInput } };
    }
    const db = readDatabase(o.database.text, o.water.text);
    const follow = !!o.activity;
    // A SIT database: the page has SIT, and follows it; and Pitzer's.
    const sit = follow && db.model === 'SIT';
    const pitz = follow && db.model === 'Pitzer';
    // Under SIT and Pitzer the same: every solute's coefficient from the model, a species on an exchanger its ion's.
    const sitLike = sit || pitz;
    // LLNL's B-dot model: each species' own rule, from the database's tables.
    const llnl = follow && db.model === 'LLNL';
    if (follow && db.model && !sitLike && !llnl) {
      throw new Error(`${o.database.name || 'This database'} gives PHREEQC the ${db.model} activity model, which `
        + 'this page does not have: its activity coefficients cannot follow the ionic strength here. Keep '
        + 'them fixed at this water instead.');
    }
    // EQUILIBRIUM_PHASES carried as minerals: held at saturation while there
    // is any, which is the relations held exactly. PHREEQC says how much of
    // each it left, per kilogram of water, and its log K at this temperature.
    const assemblage = o.phases ? readAssemblage(o.water.text) : [];
    if (assemblage.length && !o.exact) {
      throw new Error('The phases are carried as minerals held at saturation while there is any of them, which '
        + 'needs the relations held exactly.');
    }
    const extras = [];
    for (const a of assemblage) extras.push(`EQUI("${a.name}")`, `LK_PHASE("${a.name}")`, `SI("${a.name}")`);
    const waterAt = assemblage.length ? extras.length : -1;
    if (assemblage.length) extras.push('TOT("water")');
    /*
      A GAS_PHASE carried as a gas phase, held as PHREEQC held it: each gas's
      moles in it, its log K at this temperature and pressure, and the
      pressure the water holds it at (10^SI); the phase's pressure, and the
      water's kilograms, which the amounts are per.
    */
    const gasBlock = (() => { const g = readGasPhases(o.water.text); return g.size ? [...g.values()].pop() : null; })();
    const carryGas = !!gasBlock && o.gas !== false && !!o.exact;
    const gasAt = extras.length;
    if (carryGas) {
      for (const c of gasBlock.comps) extras.push(`GAS("${c.name}")`, `LK_PHASE("${c.name}")`, `SI("${c.name}")`);
      extras.push('GAS_P', 'TOT("water")');
    }
    /*
      SOLID_SOLUTIONS carried as the page's: each member's moles in its solid
      solution, S_S (none while the solid solution is not there), and its log
      K at this water, and the water's kilograms the amounts are per.
    */
    const ssBlock = (() => { const g = readSolidSolutions(o.water.text); return g.size ? [...g.values()].pop() : null; })();
    const carrySs = !!ssBlock && ssBlock.length > 0 && o.solids !== false && !!o.exact;
    const ssAt = extras.length;
    if (carrySs) {
      for (const ss of ssBlock) for (const c of ss.comps) extras.push(`S_S("${c.name}")`, `LK_PHASE("${c.name}")`);
      extras.push('TOT("water")');
    }
    /*
      KINETICS carried as reactions at a rate: each kinetic reactant a
      mineral species at its -m, its formula's dissolution a reaction of
      <REACTIONS>, its rate the RATES program as a rate law (rateLaw). The
      water the run starts from is the input's without its KINETICS -- the
      run is what PHREEQC's kinetic steps are -- and the run goes as long as
      they do. The phases the formulas are and the rates read the
      saturation of: each one's log K here; and the water's kilograms and
      volume, which M and SOLN_VOL are in.
    */
    const kinBlock = (() => { const k = readKinetics(o.water.text); return k.size ? [...k.values()].pop() : null; })();
    const carryKin = !!kinBlock && kinBlock.comps.length > 0 && o.kinetics !== false;
    let waterText = carryKin ? kineticSurfacesAtStart(withoutKinetics(o.water.text), kinBlock.comps) : o.water.text;
    const rateDefs = carryKin ? readRates(o.database.text, o.water.text) : new Map();
    const phaseKey = new Map([...db.phaseReaction.keys()].map((k) => [k.toLowerCase(), k]));
    const kinPhases = [];
    if (carryKin) {
      const want = new Set();
      for (const c of kinBlock.comps) {
        for (const [f] of c.formula) if (phaseKey.has(f.toLowerCase())) want.add(phaseKey.get(f.toLowerCase()));
        const def = rateDefs.get(c.name.toLowerCase());
        if (!def) continue;
        for (const ln of def.lines) {
          for (const m of ln.matchAll(/\b(?:SI|SR)\s*[([]\s*"([^"]+)"/gi)) {
            if (phaseKey.has(m[1].toLowerCase())) want.add(phaseKey.get(m[1].toLowerCase()));
          }
        }
      }
      kinPhases.push(...want);
    }
    const kinAt = extras.length;
    if (carryKin) {
      for (const p of kinPhases) extras.push(`LK_PHASE("${p}")`);
      extras.push('TOT("water")', 'SOLN_VOL');
    }
    // Each exchanger's activity: its master species is no amount, and
    // SYS("ex") leaves it out.
    const exMasters = [...new Set(db.exMaster.values())];
    const laAt = extras.length;
    for (const sp of exMasters) extras.push(`LA("${sp}")`);
    /*
      Each redox species' log K at this temperature, the database's own. A
      relation without electrons holds in any water PHREEQC speciates, and
      its log K can be read back off it; one with them need not: a water
      given two valence states of an element keeps both as given, whatever
      its pe says, and only PHREEQC's next step puts them on one pe.
    */
    const carryRedox = !!o.exact && o.redox !== false;
    // With the floor at 0, every species' log K: one PHREEQC finds none of is written too (see atNone).
    const everything = carryRedox && floor === 0;
    const lkSpecies = carryRedox ? [...db.reaction.keys()].filter((sp) => sp !== 'e-' && sp !== 'H2O'
      && (everything || db.isRedox(sp))) : [];
    // A column: what another water brings, for one cell 1 has none of (elsewhere, below).
    if (column) {
      for (const sp of column.keep) if (db.reaction.has(sp) && sp !== 'e-' && sp !== 'H2O' && !lkSpecies.includes(sp)) lkSpecies.push(sp);
    }
    const lkAt = extras.length;
    for (const sp of lkSpecies) extras.push(`LK_SPECIES("${sp}")`);
    // Each surface species' log K, the database's at this temperature, where the input has a surface.
    const sfBlocks = readSurfaces(o.water.text);
    const sfSpecies = sfBlocks.size && o.exact && o.surface !== false ? [...db.sfReaction.keys()] : [];
    const sfLkAt = extras.length;
    for (const sp of sfSpecies) extras.push(`LK_SPECIES("${sp}")`);
    /*
      With a diffuse double layer, each surface's potential, in volts, and
      the water's mass, for the grams of the solid to each kilogram of it:
      the surface is the part of a site's name before the underscore, and
      its area and mass are on the first of its sites' lines that gives them.
    */
    const layers = new Map();
    if (sfSpecies.length) {
      for (const b of sfBlocks.values()) {
        if (b.model !== 'ddl' && b.model !== 'cd') continue;
        for (const x of b.sites) {
          const cut = x.master.indexOf('_');
          if (cut < 1) continue;
          const name = x.master.slice(0, cut);
          const had = layers.get(name);
          if (!had || (had.area === null && Number.isFinite(x.area))) {
            // Sites that go with a phase: m2 to each mole of it, the phase in the grams' place.
            layers.set(name, { area: Number.isFinite(x.area) ? x.area : null, mass: Number.isFinite(x.mass) ? x.mass : null,
              phase: x.phase || null, kind: x.kind || null, cd: b.model === 'cd', cap: had ? had.cap : null });
          }
          // CD-MUSIC: the capacitances, given after one of the surface's site lines.
          if (x.cap) layers.get(name).cap = x.cap;
        }
      }
    }
    // Each surface's potential, psi, and CD-MUSIC's on planes 1 and 2 as well, psi1 and psi2 (EDL), volts.

    const layerCols = new Map();
    for (const [name, l] of layers) {
      layerCols.set(name, (l.cd ? ['psi', 'psi1', 'psi2'] : ['psi']).map((what) => {
        extras.push(`EDL("${what}", "${name}")`);
        return extras.length - 1;
      }));
    }
    const massAt = layers.size ? extras.length : -1;
    if (layers.size) extras.push('TOT("water")');
    // The water's pressure (volumesAt, below).
    const withVm = follow && !llnl && (db.vm.size > 0 || db.millero.size > 0 || db.phaseVm.size > 0);
    const presAt = extras.length;
    extras.push('PRESSURE');
    // Under -multi_D, pure water's viscosity at the water's temperature, and the water's: each species' Dw there (fill_spec).
    const viscAt = column && column.mcd ? extras.length : -1;
    if (viscAt >= 0) extras.push('VISCOS_0', 'VISCOS');
    const punch = punchBlock(extras);
    const takeWater = (text) => {
      let rows = runRows(o.engine, `${punch}${text}\nEND\n`);
      if (o.solution != null) rows = rows.filter((r) => Number(r.soln) === Number(o.solution));
      if (!rows.length) {
        throw new Error('PHREEQC calculated no water from that input'
          + (o.solution != null ? ` with SOLUTION ${o.solution}` : '')
          + ': it needs a SOLUTION, or something PHREEQC calculates.');
      }
      return rows[rows.length - 1];
    };
    let w = takeWater(waterText);
    /*
      A kinetic reactant may bring what the water has none of -- calcite
      into a water without calcium -- and a total at none cannot be held:
      the water is then taken again with 1e-20 mol of the reactants added
      (PHREEQC's REACTION), so that their species are there to grow from.
      Where the input reacts already, that is left as it is.
    */
    let traced = false;
    if (carryKin) {
      const has = new Set([...w.species].filter(([, [m]]) => m > 0).map(([n]) => n));
      const of = (c) => c.formula.flatMap(([f]) => {
        const pk = phaseKey.get(f.toLowerCase());
        if (pk) { const r = db.phaseReaction.get(pk); return [...r.left.slice(1), ...r.right].map((t) => t.n); }
        try { return [...formulaReaction(f, db).keys()]; } catch (e) { return []; }
      }).filter((n) => n !== 'H2O' && n !== 'e-');
      const lacking = kinBlock.comps.some((c) => of(c).some((n) => !has.has(n)));
      if (lacking && !/^\s*REACTION\b/im.test(waterText)) {
        // In the last simulation: before its END, where it has one.
        const trace = `REACTION 1\n${kinBlock.comps.flatMap((c) => c.formula.map(([f, k]) => ` ${f}  ${k}`)).join('\n')}`
          + '\n 1e-20 moles\n';
        const lines = waterText.split(/\r\n|\r|\n/);
        let at = lines.length;
        while (at > 0 && !lines[at - 1].trim()) at--;
        if (at > 0 && /^END$/i.test(lines[at - 1].trim())) at--;
        waterText = [...lines.slice(0, at), trace, ...lines.slice(at)].join('\n');
        w = takeWater(waterText);
        traced = true;
      }
    }
    /*
      ONE PE. PHREEQC keeps the valence states an initial solution is given,
      whatever its pe says: sulfate given, there is no sulfide in it, however
      reducing the pe. Its next step -- any reaction -- puts every couple on
      one pe, the electrons the water holds kept, and forms valence states
      the water was given none of. With the couples tied to the electron, the
      model is that next step: the water mixed with nothing else.
    */
    let settled = null;
    if (carryRedox && w.state === 'i_soln' && Number.isFinite(Number(w.soln))) {
      const more = runRows(o.engine, `${punch}${waterText}\nEND\nMIX 1\n ${Number(w.soln)} 1.0\nEND\n`);
      const w2 = more[more.length - 1];
      if (w2 && w2.state === 'react') {
        settled = { from: w.pe, to: w2.pe };
        w = w2;
      }
    }

    const molal = new Map();
    const lg = new Map();
    for (const [n, [m, g]] of w.species) {
      lg.set(n, g);
      if (m > 0 && !NOT_A_SPECIES.has(n)) molal.set(n, m);
    }
    const logAw = log10(w.aw);
    /*
      THE PRESSURE. PHREEQC's water is at the pressure given, or at the
      vapour pressure times a(H2O) where that is higher (calc_rho_0); the
      model works the latter out itself, and is given the former (PRESSURE).
      Above one atmosphere PHREEQC's log K are less dV (P - 1)/(R T ln 10),
      dV the reaction's molar volumes at the water: with <VOLUMES> written
      the model takes the same off, and each log K is written at one
      atmosphere, PHREEQC's own dV put back (atOneAtm).
    */
    const atm = Number(w.x[presAt]);
    const tkP = w.tc + 273.15;
    const pSatAw = Math.exp(11.6702 - 3816.44 / (tkP - 46.13)) * Math.min(w.aw, 1);
    const atVapour = Number.isFinite(atm) && Math.abs(atm - pSatAw) <= 1e-9 * atm;
    const fP = atm > 1 ? (1e-9 * (atm * 101325 - 101325)) / (R_KJ * tkP) : 0;
    // Set once the species written are known: with a molar volume to write, and the water above one atmosphere.
    let volumes = false;
    const vmOf = (n) => (vmAt.has(n) ? vmAt.get(n) : 0);
    const vmAt = new Map();
    // A log K PHREEQC has at this water's pressure, at one atmosphere: `phase` the phase on the left, if any.
    const atOneAtm = (here, left, right, phase) => {
      if (!volumes) return here;
      let dv = 0;
      for (const t of right) dv += t.c * vmOf(t.n);
      for (const t of left) dv -= t.c * (phase && t.n === phase ? (db.phaseVm.get(phase) || 0) : vmOf(t.n));
      return here + (fP * dv) / Math.LN10;
    };
    /*
      REDOX: each species the database writes with electrons tied to the
      electron by that reaction, which a run holds exactly, so that the
      couples share one pe as in PHREEQC. The electron's activity is
      10^-pe, its activity coefficient 1, and a relation reads it as it
      reads a species.
    */
    const isE = (n) => carryRedox && n === 'e-';
    const lkOf = new Map(lkSpecies.map((sp, i) => [sp, Number(w.x[lkAt + i])]));
    const logM = (n) => (isE(n) ? -w.pe : log10(molal.get(n)));
    const lgOf = (n) => (isE(n) ? 0 : lg.get(n));

    // Kept: everything above the floor, and whatever a kept relation needs.
    const kept = new Set([...molal].filter(([, m]) => m >= floor).map(([n]) => n));
    /*
      With the floor at 0 and the couples tied, a species PHREEQC lists at
      none -- oxygen in a reducing water, ferric iron's complexes, PHREEQC
      counting nothing below 1e-30 -- is written as well, at none, with the
      database's log K: an oxidant or a reductant then has species to arrive
      as and become, and the start puts each where the water's pe has it.
    */
    const atNone = new Set();
    if (everything) {
      const zero = [...w.species].filter(([n, [m]]) => !(m > 0) && !NOT_A_SPECIES.has(n) && db.reaction.has(n)
        && Number.isFinite(lkOf.get(n)) && Number.isFinite(lg.get(n)));
      for (let grew = true; grew;) {
        grew = false;
        for (const [n] of zero) {
          if (atNone.has(n)) continue;
          const r = db.reaction.get(n);
          if (r.left.length === 1 && r.right.length === 1 && r.left[0].n === r.right[0].n) continue;
          const others = [...r.left, ...r.right.slice(1)].filter((t) => t.n !== 'H2O' && t.n !== 'e-');
          if (!others.every((t) => molal.get(t.n) > 0 || atNone.has(t.n))) continue;
          atNone.add(n);
          molal.set(n, 0);
          kept.add(n);
          grew = true;
        }
      }
    }
    const redox = new Set();
    const unknown = new Set();
    const pulled = new Set();
    // A column: what the water at its ends has, and what that and the column's water make together (columnSetup).
    if (column) for (const n of column.keep) if (molal.has(n) && !kept.has(n)) { kept.add(n); pulled.add(n); }
    /*
      What another water of the column has -- an end's, a zone's, a stagnant
      cell's -- that cell 1's has none of, PHREEQC counting nothing below
      1e-30: the trace cell 1 takes of that water, gone elsewhere in it --
      the nitrate an inflow brings, N2 in a water at pe 4 with nothing to
      oxidise it. Each is written at the trace it came in as, the most any
      water has of it times the trace, with the database's log K, so that it
      has a species to arrive as and a total to be held at.
    */
    const elsewhere = new Set();
    if (column) {
      for (const n of column.keep) {
        if (molal.has(n) || NOT_A_SPECIES.has(n) || !lg.has(n)) continue;
        const r = db.reaction.get(n);
        if (!r) continue;
        const master = r.left.length === 1 && r.right.length === 1 && r.left[0].n === r.right[0].n;
        if (!master && !Number.isFinite(lkOf.get(n))) continue;
        molal.set(n, column.trace * column.keepAt.get(n));
        kept.add(n);
        pulled.add(n);
        elsewhere.add(n);
      }
    }

    // The phases, each as its reaction: its formula first on the left, then
    // what else it takes, and what it dissolves to.
    const minerals = [];
    const phasesSkipped = [];
    const waterKg = waterAt >= 0 ? Number(w.x[waterAt]) : 1;
    assemblage.forEach((a, i) => {
      const r = db.phaseReaction.get(a.name);
      const moles = Number(w.x[3 * i]);
      const lk = Number(w.x[3 * i + 1]);
      // Held where PHREEQC left it: at its target while there is any of it,
      // to PHREEQC's own tolerance, which is the water the model starts from.
      const siLeft = Number(w.x[3 * i + 2]);
      const skip = (why) => phasesSkipped.push({ name: a.name, why });
      if (!r || !r.left.length) { skip('the database has no reaction for it'); return; }
      if (a.extra) { skip(`its line says more than this page carries (${a.extra})`); return; }
      /*
        An alternative reaction -- Fix_H+ -8 NaOH, PHREEQC adding or taking
        away NaOH to hold the phase's SI -- the formula's dissolution, or the
        alternative phase's: a mineral of its own at the moles PHREEQC left
        of it, held where the phase's SI is (SI() on its relation), the
        phase in <PHASES>.
      */
      let alt = null;
      if (a.alt) {
        const pk = phaseKey.get(a.alt.toLowerCase());
        let terms;
        if (pk) {
          const ar = db.phaseReaction.get(pk);
          terms = [...ar.left.slice(1).map((t) => [t.n, -t.c / ar.left[0].c]), ...ar.right.map((t) => [t.n, t.c / ar.left[0].c])];
        } else {
          try { terms = [...formulaReaction(a.alt, db)]; } catch (e) { skip(`its alternative formula ${a.alt}: ${e.message}`); return; }
        }
        alt = { formula: a.alt, reac: terms.filter(([, c]) => c < 0).map(([n, c]) => ({ c: -c, n })),
          prod: terms.filter(([, c]) => c > 0).map(([n, c]) => ({ c, n })) };
      }
      const others = [...r.left.slice(1), ...r.right, ...(alt ? [...alt.reac, ...alt.prod] : [])];
      if (others.some((t) => t.n === 'e-') && !carryRedox) {
        skip('it dissolves with electrons, and the valence states are not held at one pe');
        return;
      }
      const missing = others.filter((t) => t.n !== 'H2O' && !isE(t.n) && !molal.has(t.n)).map((t) => t.n);
      if (missing.length) { skip(`the water has no ${missing.join(', ')}`); return; }
      if (!Number.isFinite(moles) || !Number.isFinite(lk) || !(waterKg > 0)) { skip('PHREEQC gave no amount or log K for it'); return; }
      // One at a bound of its own (dissolve_only, precipitate_only) is held at its target, not where its bound left it.
      const atTarget = Number.isFinite(siLeft) && (!a.only || Math.abs(siLeft - a.si) < 1e-3);
      minerals.push({ phase: a.name, si: (moles > 0 || a.forced) && atTarget ? siLeft : a.si, target: a.si,
        amount: (a.forced ? moles : Math.max(moles, 0)) / waterKg, lk, c0: r.left[0].c, reac: r.left.slice(1),
        prod: r.right, alt, only: a.only, forced: a.forced });
      for (const t of others) {
        if (t.n !== 'H2O' && !isE(t.n) && !kept.has(t.n)) { kept.add(t.n); pulled.add(t.n); }
      }
    });
    /*
      THE GAS PHASE: each gas at the moles PHREEQC left in it, per kilogram of
      water, with its dissolution as the database writes it, which a run
      holds exactly. A gas PHREEQC holds as a real gas -- the database gives
      it a critical temperature and pressure, and PHREEQC then uses Peng and
      Robinson's equation of state -- is not carried, and nor is a bubble one
      of whose gases is not.
    */
    const gases = [];
    const gasSkipped = [];
    let gasFixed = null;
    if (gasBlock && !carryGas) {
      gasSkipped.push({ name: 'GAS_PHASE', why: o.gas === false ? 'asked not to be carried'
        : 'a gas phase is carried when the relations are held exactly' });
    } else if (carryGas) {
      const n = gasBlock.comps.length;
      const kgw = Number(w.x[gasAt + 3 * n + 1]);
      const dropped = [];
      gasBlock.comps.forEach((c, i) => {
        const r = db.phaseReaction.get(c.name);
        const moles = Number(w.x[gasAt + 3 * i]);
        const lk = Number(w.x[gasAt + 3 * i + 1]);
        const si = Number(w.x[gasAt + 3 * i + 2]);
        const skip = (why) => { gasSkipped.push({ name: c.name, why }); if (moles > 0) dropped.push(c.name); };
        if (!r || !r.left.length) { skip('the database has no reaction for it'); return; }
        const crit = db.critical.get(c.name);
        const real = !!crit && crit.tc > 0 && crit.pc > 0;
        const others = [...r.left.slice(1), ...r.right];
        if (others.some((t) => t.n === 'e-') && !carryRedox) {
          skip('it dissolves with electrons, and the valence states are not held at one pe');
          return;
        }
        const missing = others.filter((t) => t.n !== 'H2O' && !isE(t.n) && !molal.has(t.n)).map((t) => t.n);
        if (missing.length) { skip(`the water has no ${missing.join(', ')}`); return; }
        if (!Number.isFinite(moles) || !Number.isFinite(lk) || !(kgw > 0)) { skip('PHREEQC gave no amount or log K for it'); return; }
        // PHREEQC keeps 1e-25 mol of a gas phase that is not there (MIN_TOTAL): that is none.
        gases.push({ phase: c.name, amount: moles > 1e-20 ? moles / kgw : 0, lk, pressure: Number.isFinite(si) ? 10 ** si : 0,
          c0: r.left[0].c, reac: r.left.slice(1), prod: r.right, crit: real ? crit : null });
      });
      // PHREEQC does not mix ideal and real gases in a phase: neither is carried then.
      if (gases.some((g) => g.crit) && gases.some((g) => !g.crit)) {
        for (const g of gases) gasSkipped.push({ name: g.phase, why: 'the gas phase mixes real gases (a critical temperature '
          + 'and pressure in the database) with ideal ones, which PHREEQC does not hold together' });
        gases.length = 0;
      }
      if (dropped.length && gasBlock.fixed === 'pressure' && gases.length) {
        for (const g of gases) gasSkipped.push({ name: g.phase, why: `its bubble holds ${dropped.join(', ')} as well, which is not carried` });
        gases.length = 0;
      }
      if (gases.length) {
        gasFixed = gasBlock.fixed === 'pressure' ? { fixed: 'pressure', pressure: gasBlock.pressure }
          : { fixed: 'volume', volume: gasBlock.volume / kgw, atm: Number(w.x[gasAt + 3 * n]) };
        for (const g of gases) {
          for (const t of [...g.reac, ...g.prod]) {
            if (t.n !== 'H2O' && !isE(t.n) && !kept.has(t.n)) { kept.add(t.n); pulled.add(t.n); }
          }
        }
      }
    }
    /*
      THE SOLID SOLUTIONS: each member a mineral at the moles PHREEQC left in
      its solid solution, per kilogram of water, with its dissolution as the
      database writes it; and for a binary one PHREEQC's Guggenheim energies
      and temperature, from whichever form its parameters were given in
      (ssEnergies). A solid solution one of whose members cannot be written
      is not carried.
    */
    const solids = [];
    const solidsSkipped = [];
    if (ssBlock && ssBlock.length && !carrySs) {
      solidsSkipped.push({ name: 'SOLID_SOLUTIONS', why: o.solids === false ? 'asked not to be carried'
        : 'a solid solution is carried when the relations are held exactly' });
    } else if (carrySs) {
      const nComp = ssBlock.reduce((acc, ss) => acc + ss.comps.length, 0);
      const kgw = Number(w.x[ssAt + 2 * nComp]);
      let at = ssAt;
      for (const ss of ssBlock) {
        const comps = ss.comps.map((c) => {
          const moles = Number(w.x[at]);
          const lk = Number(w.x[at + 1]);
          at += 2;
          return { phase: c.name, moles, lk, r: db.phaseReaction.get(c.name) };
        });
        let why = '';
        for (const c of comps) {
          if (!c.r || !c.r.left.length) { why = `the database has no reaction for ${c.phase}`; break; }
          const others = [...c.r.left.slice(1), ...c.r.right];
          if (others.some((t) => t.n === 'e-') && !carryRedox) { why = `${c.phase} dissolves with electrons`; break; }
          const missing = others.filter((t) => t.n !== 'H2O' && !isE(t.n) && !molal.has(t.n)).map((t) => t.n);
          if (missing.length) { why = `the water has no ${missing.join(', ')} for ${c.phase}`; break; }
          if (!Number.isFinite(c.moles) || !Number.isFinite(c.lk) || !(kgw > 0)) { why = 'PHREEQC gave no amount or log K'; break; }
        }
        if (!why && comps.length < 2) why = 'it has one member, a pure phase';
        let energy = null;
        if (!why && ss.input) {
          if (comps.length !== 2) why = `Guggenheim's parameters are for two members, and it has ${comps.length}`;
          else {
            const kAt = (ph) => 10 ** kCalc(db.logKTerms('p', ph) || [0, 0, 0, 0, 0, 0, 0, 0], ss.tk);
            energy = ssEnergies(ss, kAt(comps[0].phase), kAt(comps[1].phase));
          }
        }
        if (why) { solidsSkipped.push({ name: ss.name, why }); continue; }
        // PHREEQC keeps 1e-27 mol of a member of a solid solution that is not there: none.
        for (const c of comps) {
          c.amount = c.moles > 1e-20 ? c.moles / kgw : 0;
          c.c0 = c.r.left[0].c;
          c.reac = c.r.left.slice(1);
          c.prod = c.r.right;
          for (const t of [...c.reac, ...c.prod]) {
            if (t.n !== 'H2O' && !isE(t.n) && !kept.has(t.n)) { kept.add(t.n); pulled.add(t.n); }
          }
        }
        solids.push({ name: ss.name, comps, energy, tk: ss.tk, input: ss.input });
      }
    }
    /*
      THE KINETIC REACTANTS. Each a mineral species at PHREEQC's -m, per
      kilogram of water, and a reaction at the rate its RATES program comes
      to: its formula's dissolution -- a phase's as the database writes it,
      a chemical formula's into the master species of its elements with H+,
      the water and the electrons (formulaReaction). What the rate reads is
      pulled into the model as a mineral's species are: the species, the
      phases it reads the saturation of (written in <PHASES>), and an
      element's total, a sum over the species written (filled in below).
    */
    const kinetics = [];
    const kinSkipped = [];
    const kinPhaseUse = new Map();
    // The phases whose saturation index a mineral's alternative reaction holds (readAssemblage): in <PHASES> as well.
    for (const mn of minerals) if (mn.alt) kinPhaseUse.set(mn.phase, mn.lk);
    const holes = [];
    const hole = (kind, key) => { holes.push({ kind, key }); return `\u0001${holes.length - 1}\u0001`; };
    if (carryKin) {
      const kgw = Number(w.x[kinAt + kinPhases.length]);
      const solnVol = Number(w.x[kinAt + kinPhases.length + 1]);
      // PHREEQC's kilogram, 1 where it is 1 but for rounding (0.999999999999994 after an initial solution).
      const W = kgw > 0 && Math.abs(kgw - 1) > 1e-9 ? kgw : 1;
      const perW = W !== 1 ? `${fmtG(W, 15)}*` : '';
      const lkPhase = new Map(kinPhases.map((p, i) => [p, Number(w.x[kinAt + i])]));
      const usePhase = (pk) => {
        const r = db.phaseReaction.get(pk);
        const others = [...r.left.slice(1), ...r.right];
        if (others.some((t) => t.n === 'e-') && !carryRedox) {
          throw new Error(`${pk} dissolves with electrons, and the valence states are not held at one pe`);
        }
        const missing = others.filter((t) => t.n !== 'H2O' && t.n !== 'e-' && !molal.has(t.n)).map((t) => t.n);
        if (missing.length) throw new Error(`${pk}'s saturation: the water has no ${missing.join(', ')}`);
        if (!Number.isFinite(lkPhase.get(pk))) throw new Error(`PHREEQC gave no log K for ${pk}`);
        for (const t of others) if (t.n !== 'H2O' && t.n !== 'e-' && !kept.has(t.n)) { kept.add(t.n); pulled.add(t.n); }
        kinPhaseUse.set(pk, lkPhase.get(pk));
      };
      const useSpecies = (sp) => {
        if (!molal.has(sp)) return false;
        if (!kept.has(sp)) { kept.add(sp); pulled.add(sp); }
        return true;
      };
      for (const comp of kinBlock.comps) {
        const skip = (why) => kinSkipped.push({ name: comp.name, why });
        const def = rateDefs.get(comp.name.toLowerCase());
        if (!def) { skip('the database and the input have no RATES for it'); continue; }
        // Its reaction, per mole of it.
        const terms = new Map();
        const add = (n, c) => terms.set(n, (terms.get(n) || 0) + c);
        let why = null;
        for (const [f, coef] of comp.formula) {
          const pk = phaseKey.get(f.toLowerCase());
          if (pk) {
            const r = db.phaseReaction.get(pk);
            const c0 = r.left[0].c;
            for (const t of r.left.slice(1)) add(t.n, (-t.c * coef) / c0);
            for (const t of r.right) add(t.n, (t.c * coef) / c0);
            continue;
          }
          try {
            for (const [n, c] of formulaReaction(f, db)) add(n, c * coef);
          } catch (e) { why = e.message; break; }
        }
        if (why) { skip(why); continue; }
        const rx = [...terms].filter(([n, c]) => n !== 'H2O' && Math.abs(c) > 1e-12);
        if (rx.some(([n]) => n === 'e-') && !carryRedox) {
          skip('it reacts with electrons, and the valence states are not held at one pe');
          continue;
        }
        const missing = rx.filter(([n]) => n !== 'e-' && !molal.has(n)).map(([n]) => n);
        if (missing.length) { skip(`the water has no ${missing.join(', ')}`); continue; }
        // Its rate, what the program reads in the model's words.
        const ctx = {
          m: `${perW}ramp([${hole('kin', comp.name)}])`, m0: comp.m0, parms: comp.parms, W,
          solnVol: solnVol > 0 ? solnVol : null,
          phase: (p, kind) => {
            const pk = phaseKey.get(p.toLowerCase());
            if (!pk) return null;
            if (minerals.some((mn) => mn.phase === pk)) return `${kind}(${hole('mineral', pk)})`;
            usePhase(pk);
            return `${kind}(${hole('phase', pk)})`;
          },
          act: (sp) => (sp === 'H2O' ? '{H2O}' : useSpecies(sp) ? `{${hole('sp', sp)}}` : null),
          mol: (sp) => (sp === 'H2O' ? '55.50837' : useSpecies(sp) ? `[${hole('sp', sp)}]` : null),
          tot: (label) => {
            if (/^(H|O)(\(|$)/.test(label)) {
              throw new Error(`TOT("${label}"), hydrogen or oxygen, which the model does not count`);
            }
            return hole('tot', label);
          },
          kin: (n) => (kinBlock.comps.some((c) => c.name === n) ? `${perW}[${hole('kin', n)}]` : null),
          equi: (n) => {
            const pk = phaseKey.get(n.toLowerCase());
            return pk && minerals.some((mn) => mn.phase === pk) ? `${perW}[${hole('mineral', pk)}]` : null;
          },
        };
        let law;
        try { law = rateLaw(def, ctx); } catch (e) { skip(`its rate: ${e.message}`); continue; }
        for (const [n] of rx) if (n !== 'e-' && !kept.has(n)) { kept.add(n); pulled.add(n); }
        /*
          Every species of what it brings or takes, whatever the floor: they
          grow, or go. Of the element, where the valence states are held at one
          pe; else of the valence states it moves, the others staying where
          they are (a trace of Fe(2) beside the Fe(3) it brings, at 1e-29, is
          a total no factorisation resolves).
        */
        const key = (lb) => (carryRedox ? elementOf(lb) : normLabel(lb));
        const els = new Set();
        for (const [n] of rx) {
          if (n === 'e-' || n === 'H+') continue;
          try { for (const [lb] of db.expand(n)) if (lb !== 'e-') els.add(key(lb)); } catch (e) { /* no terms */ }
        }
        for (const sp of molal.keys()) {
          if (kept.has(sp)) continue;
          let ex;
          try { ex = db.expand(sp); } catch (e) { continue; }
          if ([...ex.keys()].some((lb) => els.has(key(lb)))) { kept.add(sp); pulled.add(sp); }
        }
        kinetics.push({ comp, rate: def, amount: Math.max(comp.m, 0) / W, rx, law, name: null });
      }
    }
    /*
      THE EXCHANGERS: each species PHREEQC put on one, at its molality, with
      its relation as the database writes it, which a run holds exactly.
      Its activity is its equivalent fraction (Gaines-Thomas), times its
      ion's activity coefficient where PHREEQC gives it one (-gamma).
    */
    const onEx = [];
    const exSkipped = [];
    const laMaster = new Map(exMasters.map((sp, i) => [sp, Number(w.x[laAt + i])]));
    if (w.exchange && w.exchange.size && o.exchange !== false) {
      if (!o.exact) {
        exSkipped.push({ name: [...w.exchange.keys()].join(', '), why: 'an exchanger needs the relations held exactly' });
      } else {
        for (const [n, e] of w.exchange) {
          // In a column, whatever goes on the exchanger as the water at its ends comes in (columnSetup).
          if (!(e.m >= floor) && !(column && column.keepOn.has(n))) continue;
          const skip = (why) => exSkipped.push({ name: n, why });
          const r = db.exReaction.get(n);
          if (!r) { skip('the database has no reaction for it'); continue; }
          const terms = [...r.left, ...r.right.slice(1)];
          const masters = terms.filter((t) => laMaster.has(t.n));
          if (masters.length !== 1 || terms.some((t) => db.exReaction.has(t.n))) {
            skip('it is not formed from one exchanger');
            continue;
          }
          if (!Number.isFinite(laMaster.get(masters[0].n)) || laMaster.get(masters[0].n) < -99) {
            skip(`PHREEQC gave no activity for ${masters[0].n}`);
            continue;
          }
          if (terms.some((t) => t.n === 'e-')) { skip('it is formed with electrons'); continue; }
          const missing = terms.filter((t) => t.n !== 'H2O' && !laMaster.has(t.n) && !molal.has(t.n)).map((t) => t.n);
          if (missing.length) { skip(`the water has no ${missing.join(', ')}`); continue; }
          onEx.push({ species: n, master: masters[0].n, m: e.m, la: e.la, lg: e.lg, left: r.left, right: r.right });
          for (const t of terms) {
            if (t.n !== 'H2O' && !laMaster.has(t.n) && !kept.has(t.n)) { kept.add(t.n); pulled.add(t.n); }
          }
        }
      }
    }
    /*
      An exchanger whose sites go with a phase or a kinetic reactant,
      PHREEQC's `CaX2 Montmorillonite equilibrium_phase 0.165`: its formula
      a species on it, charge-balanced with its ion as PHREEQC's manual has
      it, so many of it to each mole -- written on that species, sites= per=
      the mineral it is carried as, its sites n times as many. Held at what
      PHREEQC loaded at the start instead, and said: a formula that is the
      bare exchanger (X), whose sites PHREEQC takes away leaving their charge
      behind; one that is no species carried on it; a phase or reactant not
      carried; two such lines on one exchanger.
    */
    const exPer = new Map();
    const exHeld = [];
    if (onEx.length) {
      const linked = linkedExchangers(o.water.text);
      const formOf = (x) => onEx.find((q) => q.species === x.master) || null;
      const lines = new Map();
      for (const x of linked) {
        const e = formOf(x);
        if (e) lines.set(e.master, (lines.get(e.master) || 0) + 1);
      }
      for (const x of linked) {
        const e = formOf(x);
        const ph = x.phase.toLowerCase();
        const carrier = x.kind === 'kinetic_reactant' ? kinetics.find((k) => k.comp.name.toLowerCase() === ph) || null
          : minerals.find((mn) => mn.phase.toLowerCase() === ph) || null;
        let why = null;
        if (!e) {
          why = db.exMaster.has(x.master) ? `its formula is the bare exchanger, ${x.master}, where PHREEQC's manual has a `
            + `species on it with its ion, Na${x.master} or Ca${x.master}2` : `its formula, ${x.master}, is no species carried on it`;
        } else if (!carrier) {
          why = `${x.kind === 'kinetic_reactant' ? 'the kinetic reactant' : 'the phase'} ${x.phase} is not carried`;
        } else if (lines.get(e.master) > 1) why = 'more than one line of its exchanger goes with a phase or a reactant';
        if (why) {
          exHeld.push({ exchanger: x.master, phase: x.phase, kind: x.kind, ratio: x.ratio, why });
          continue;
        }
        const n = (e.right.concat(e.left).find((t) => t.n === e.master) || { c: 0 }).c;
        exPer.set(e.species, { ratio: x.ratio, sites: n * x.ratio, carrier, kind: x.kind });
      }
    }
    /*
      THE SURFACES: each species PHREEQC put on one, at its molality, with
      its relation as the database writes it and the database's log K, which
      a run holds exactly; its activity is its fraction of its type's sites.
      Without electrostatics (-no_edl) only, for now.
    */
    const onSf = [];
    const sfSkipped = [];
    const sfMasters = new Set(db.sfMaster.values());
    const sfLk = new Map(sfSpecies.map((sp, i) => [sp, Number(w.x[sfLkAt + i])]));
    if (w.surface && w.surface.size && o.surface !== false) {
      const all = [...w.surface.keys()].join(', ');
      const models = new Set([...sfBlocks.values()].map((b) => b.model));
      const noLayer = [...layers].filter(([, l]) => !(l.area > 0 && (l.mass > 0 || l.phase)
        && (!l.cd || (l.cap && l.cap.every((v) => v > 0))))).map(([n]) => n);
      if (!o.exact) sfSkipped.push({ name: all, why: 'a surface needs the relations held exactly' });
      else if (models.size > 1) {
        sfSkipped.push({ name: all, why: 'the input has a surface with a double layer and one without (-no_edl)' });
      } else if ([...sfBlocks.values()].some((b) => b.sites.some((x) => x.kind === 'kinetic_reactant'
        && !kinetics.some((k) => k.comp.name.toLowerCase() === x.phase.toLowerCase())))) {
        sfSkipped.push({ name: all, why: 'its sites follow a kinetic reactant that is not carried' });
      } else if ([...sfBlocks.values()].some((b) => b.sites.some((x) => x.phase && x.kind !== 'kinetic_reactant'
        && !minerals.some((mn) => mn.phase === x.phase)))) {
        sfSkipped.push({ name: all, why: 'its sites follow a phase that is not carried as a mineral' });
      } else if (noLayer.length) {
        sfSkipped.push({ name: all, why: `the double layer of ${noLayer.join(', ')} needs its area and grams, which `
          + 'its first site\'s line gives, and under CD-MUSIC its two capacitances' });
      } else if ([...sfBlocks.values()].some((b) => b.sites.some((x) => !x.phase && !Number.isFinite(x.sites)))) {
        sfSkipped.push({ name: all, why: 'its sites are given in a way this page does not read' });
      } else if ([...sfBlocks.values()].some((b) => b.other.length)) {
        sfSkipped.push({ name: all, why: `its block says more than this page carries (${[...sfBlocks.values()]
          .flatMap((b) => b.other).join('; ')})` });
      } else {
        for (const [n, e] of w.surface) {
          if (!(e.m >= floor) && !(column && column.keepOn.has(n))) continue;
          const skip = (why) => sfSkipped.push({ name: n, why });
          if (sfMasters.has(n)) { onSf.push({ species: n, master: true, m: e.m }); continue; }
          const r = db.sfReaction.get(n);
          if (!r) { skip('the database has no reaction for it'); continue; }
          const terms = [...r.left, ...r.right.slice(1)];
          const kinds = new Set(terms.filter((t) => sfMasters.has(t.n)).map((t) => t.n));
          if (!kinds.size) { skip('it is formed from no site'); continue; }
          if (kinds.size > 1) { skip('it is formed from two kinds of site'); continue; }
          if (terms.some((t) => db.sfReaction.has(t.n) && !sfMasters.has(t.n))) {
            skip('it is formed from a species on the surface that is not a site'); continue;
          }
          if (terms.some((t) => t.n === 'e-')) { skip('it is formed with electrons'); continue; }
          if (!Number.isFinite(sfLk.get(n))) { skip('PHREEQC gave no log K for it'); continue; }
          const missing = terms.filter((t) => t.n !== 'H2O' && !sfMasters.has(t.n) && !molal.has(t.n)).map((t) => t.n);
          if (missing.length) { skip(`the water has no ${missing.join(', ')}`); continue; }
          onSf.push({ species: n, master: false, m: e.m, left: r.left, right: r.right, lk: sfLk.get(n) });
          for (const t of terms) {
            if (t.n !== 'H2O' && !sfMasters.has(t.n) && !kept.has(t.n)) { kept.add(t.n); pulled.add(t.n); }
          }
        }
        // A species formed from a site that is not carried is not carried either.
        const have = new Set(onSf.map((e) => e.species));
        for (let i = onSf.length - 1; i >= 0; i--) {
          const e = onSf[i];
          if (e.master) continue;
          const sites = [...e.left, ...e.right.slice(1)].filter((t) => sfMasters.has(t.n));
          if (sites.every((t) => have.has(t.n))) continue;
          sfSkipped.push({ name: e.species, why: `its site ${sites.find((t) => !have.has(t.n)).n} is not carried` });
          onSf.splice(i, 1);
        }
        // By site, in the order the input lists them: each bare site first, then what is on it, the most first.
        const listed = [...sfBlocks.values()].flatMap((b) => b.sites.map((x) => db.sfMaster.get(x.master) || x.master));
        const siteOf = (e) => (e.master ? e.species
          : [...e.left, ...e.right.slice(1)].find((t) => sfMasters.has(t.n)).n);
        const rank = (sp) => (listed.includes(sp) ? listed.indexOf(sp) : listed.length);
        onSf.sort((a, b) => rank(siteOf(a)) - rank(siteOf(b)) || (siteOf(a) < siteOf(b) ? -1 : siteOf(a) > siteOf(b) ? 1 : 0)
          || Number(b.master) - Number(a.master) || b.m - a.m);
      }
    }
    /*
      Each surface's potential, where its double layer is carried: PHREEQC's,
      written as its activity exp(-F psi/RT), with the surface's area and the
      grams of the solid to each kilogram of the water.
    */
    const potentials = [];
    if (onSf.length && layers.size) {
      const tk = w.tc + 273.15;
      const kgw = massAt >= 0 && Number(w.x[massAt]) > 0 ? Number(w.x[massAt]) : 1;
      [...layers].forEach(([surface, l]) => {
        if (!onSf.some((e) => e.species.startsWith(`${surface}_`))) return;
        // CD-MUSIC: its three planes, Hfo_psi with the area and capacitances, Hfo_psib and Hfo_psid.
        layerCols.get(surface).forEach((col, plane) => {
          const psi = Number(w.x[col]);
          potentials.push({ surface, species: `${surface}_psi${['', 'b', 'd'][plane]}`, psi, plane, cd: l.cd,
            a: Math.exp(-FARADAY * psi / (GAS_R * tk)), area: plane ? null : l.area,
            grams: plane || l.phase ? null : l.mass / kgw, phase: plane ? null : l.phase, kind: plane ? null : l.kind,
            cap: plane ? null : l.cap });
        });
      });
    }


    let changed = true;
    while (changed) {
      changed = false;
      for (const n of [...kept].sort()) {
        const r = db.reaction.get(n);
        if (!r) {
          if (db.masterLabel(n) === null) unknown.add(n);
          continue;
        }
        if (db.isRedox(n) && !carryRedox) { redox.add(n); continue; }
        for (const { n: x } of [...r.left, ...r.right.slice(1)]) {
          if (NOT_A_SPECIES.has(x) || kept.has(x)) continue;
          if (molal.has(x)) { kept.add(x); pulled.add(x); changed = true; }
        }
      }
    }

    const byAmount = (a, b) => molal.get(b) - molal.get(a) || (a < b ? -1 : a > b ? 1 : 0);
    // The relations, each as the database writes it, water left out.
    const eqs = [];
    const skipped = [];
    for (const n of [...kept].sort(byAmount)) {
      const r = db.reaction.get(n);
      if (!r || redox.has(n)) continue;
      if (r.left.length === 1 && r.right.length === 1 && r.left[0].n === r.right[0].n) continue;
      const reac = r.left.filter((t) => t.n !== 'H2O');
      const prod = r.right.filter((t) => t.n !== 'H2O');
      const missing = [...reac, ...prod].map((t) => t.n).filter((x) => !kept.has(x) && !isE(x));
      if (missing.length) { skipped.push({ species: n, missing }); continue; }
      const sumLog = (terms) => terms.reduce((s, t) => s + t.c * logM(t.n), 0);
      const sumLg = (terms) => terms.reduce((s, t) => s + t.c * lgOf(t.n), 0);
      const nw = r.right.filter((t) => t.n === 'H2O').reduce((s, t) => s + t.c, 0)
        - r.left.filter((t) => t.n === 'H2O').reduce((s, t) => s + t.c, 0);
      // A species at none has no molality to read its log K back off, and one from elsewhere none of PHREEQC's here.
      const dbK = atNone.has(n) || elsewhere.has(n);
      let logk = dbK ? lkOf.get(n) : null;
      let logkC = dbK ? logk - sumLg(prod) + sumLg(reac) - nw * logAw : sumLog(prod) - sumLog(reac);
      if (logk === null) logk = logkC + sumLg(prod) - sumLg(reac) + nw * logAw;
      /*
        A couple tied to the electron takes the database's log K, and says
        what pe it stands at in this water: PHREEQC's own, unless the water
        was given both its valence states.
      */
      let peHere = null;
      const ne = prod.filter((t) => isE(t.n)).reduce((s, t) => s + t.c, 0)
        - reac.filter((t) => isE(t.n)).reduce((s, t) => s + t.c, 0);
      if (ne && Number.isFinite(lkOf.get(n)) && !dbK) {
        const lk = lkOf.get(n);
        peHere = w.pe - (lk - logk) / ne;
        logkC += lk - logk;
        logk = lk;
      }
      let kf = (!o.exact && o.kf) || null;
      if (o.relax && !o.exact) {
        // Near equilibrium a relation relaxes at kf * prod(reactants) * sum(nu^2 / c).
        const forward = reac.reduce((p, t) => p * molal.get(t.n) ** t.c, 1);
        const spread = [...reac, ...prod].reduce((s, t) => s + (t.c * t.c) / molal.get(t.n), 0);
        kf = o.relax / (forward * spread);
      }
      // As the database writes it, water and all, for a model that keeps activities.
      eqs.push({ species: n, reac, prod, logkC, logk, kf, left: r.left, right: r.right, peHere });
    }

    // Names as rtm.html can write them; H+ and OH- first.
    const taken = new Map();
    const order = [...kept].sort(byAmount);
    for (const front of ['OH-', 'H+']) {
      const i = order.indexOf(front);
      if (i >= 0) { order.splice(i, 1); order.unshift(front); }
    }
    // The electron, when a relation written has it: PHREEQC's e-, under that name.
    const withE = (terms) => terms.some((t) => t.n === 'e-');
    const tied = carryRedox ? eqs.filter((e) => withE(e.reac) || withE(e.prod)) : [];
    const eUsed = carryRedox && (tied.length > 0 || minerals.some((mn) => withE(mn.reac) || withE(mn.prod))
      || kinetics.some((k) => k.rx.some(([n]) => n === 'e-'))
      || [...kinPhaseUse.keys()].some((pk) => withE(db.phaseReaction.get(pk).left) || withE(db.phaseReaction.get(pk).right)));
    if (eUsed) taken.set('e-', 'e-');
    // The pe each couple stands at in PHREEQC's water: one, unless it was given
    // two valence states of an element, which the run then settles on one pe.
    const pes = tied.map((e) => e.peHere).filter((v) => Number.isFinite(v));
    const peSpread = pes.length ? [Math.min(...pes), Math.max(...pes)] : null;
    const outOfEq = !!peSpread && peSpread[1] - peSpread[0] > 1e-6;
    const name = new Map(order.map((s) => [s, rtmName(s, taken)]));
    // A mineral that is an alternative reaction is named for what dissolves and the phase it holds, no charge in it.
    for (const mn of minerals) mn.name = rtmName(mn.alt ? `${mn.alt.formula}_${mn.phase.replace(/[+-][0-9.]*$/, '')}` : mn.phase, taken);
    for (const g of gases) g.name = rtmName(g.phase, taken);
    for (const ss of solids) for (const c of ss.comps) c.name = rtmName(c.phase, taken);
    /*
      The kinetic reactants' names, and the phases of <PHASES>, which may have
      a species' name (Calcite the reactant, Calcite the phase its rate reads
      the saturation of); then what each rate law reads, in the names
      written: an element's total the sum of the species written that hold
      it, each to its atoms (TOT, which counts the water's species alone).
    */
    for (const k of kinetics) k.name = rtmName(k.comp.name, taken);
    const phaseName = new Map([...kinPhaseUse.keys()].map((pk) => [pk, rtmName(pk, new Map())]));
    const totText = (label) => {
      const want = normLabel(label);
      const whole = !label.includes('(');
      const parts = [];
      for (const sp of order) {
        let ex;
        try { ex = db.expand(sp); } catch (e) { continue; }
        let n = 0;
        for (const [lb, c] of ex) if (lb !== 'e-' && (whole ? elementOf(lb) === label : normLabel(lb) === want)) n += c;
        if (n) parts.push(`${Math.abs(n - 1) > 1e-12 ? `${fmtCoef(n)}*` : ''}[${name.get(sp)}]`);
      }
      return parts.length ? `(${parts.join(' + ')})` : '0';
    };
    const holeText = (h) => {
      if (h.kind === 'sp') return name.get(h.key) || null;
      if (h.kind === 'kin') { const k = kinetics.find((x) => x.comp.name === h.key); return k ? k.name : null; }
      if (h.kind === 'mineral') { const mn = minerals.find((x) => x.phase === h.key); return mn ? mn.name : null; }
      if (h.kind === 'phase') return phaseName.get(h.key) || null;
      return totText(h.key);
    };
    for (let pass = 0; pass < 2; pass++) {
      for (let i = kinetics.length - 1; i >= 0; i--) {
        const k = kinetics[i];
        const fill = (text) => text.replace(/\u0001(\d+)\u0001/g, (_, j) => {
          const t = holeText(holes[Number(j)]);
          if (t === null) throw new Error(`its rate reads ${holes[Number(j)].key}, which is not carried`);
          return t;
        });
        try {
          k.r = fill(k.law.r);
          k.names = k.law.names.map(([n, v]) => [n, fill(v)]);
        } catch (e) {
          kinSkipped.push({ name: k.comp.name, why: e.message });
          kinetics.splice(i, 1);
        }
      }
    }
    /*
      <VOLUMES>: each species written that the database gives a molar volume
      -- -Vm with a1 not 0, PHREEQC's supcrt form, or else -Millero -- and
      each phase its -Vm, as PHREEQC's calc_vm reads them; where there is one
      and the water is above one atmosphere, the log K are written at one.
    */
    const volLines = [];
    if (withVm && fP > 0) {
      for (const sp of order) {
        const v = db.vm.get(sp);
        const m = db.millero.get(sp);
        if (v && v[0] !== 0) volLines.push([name.get(sp), v.map(String).join('  ')]);
        else if (m && m[0] !== 0) volLines.push([name.get(sp), `millero  ${m.map(String).join('  ')}`]);
      }
      const ph = (n, phase) => { if (db.phaseVm.get(phase)) volLines.push([n, String(db.phaseVm.get(phase))]); };
      for (const mn of minerals) ph(mn.name, mn.phase);
      for (const g of gases) ph(g.name, g.phase);
      for (const ss of solids) for (const c of ss.comps) ph(c.name, c.phase);
      volumes = volLines.length > 0;
    }
    /*
      Each species' molar volume in PHREEQC's water, VM(), PHREEQC's at its
      pressure (calc_vm), for the log K written at one atmosphere: a column
      each, from the same input run again. (A volume put into the string of
      every species' molality instead left PHREEQC's memory spoiled for a
      later load of the database, a few runs on.)
    */
    if (volumes) {
      const names = [...new Set([...kept].filter((n) => db.reaction.has(n) && n !== 'e-'))].concat('H2O');
      const more = settled ? `MIX 1\n ${Number(w.soln)} 1.0\nEND\n` : '';
      let vr = runRows(o.engine, `${punchBlock(names.map((n) => `VM("${n}")`))}${waterText}\nEND\n${more}`);
      if (o.solution != null && !settled) vr = vr.filter((r) => Number(r.soln) === Number(o.solution));
      const last = vr[vr.length - 1];
      names.forEach((n, i) => vmAt.set(n, Number(last.x[i])));
    }
    // The exchangers used, and the species on them, by the names written.
    const exUsed = exMasters.filter((sp) => onEx.some((e) => e.master === sp));
    const exName = new Map(exUsed.map((sp) => [sp, rtmName(sp, taken)]));
    for (const e of onEx) { e.name = rtmName(e.species, taken); exName.set(e.species, e.name); }
    for (const e of onSf) { e.name = rtmName(e.species, taken); exName.set(e.species, e.name); }
    for (const pp of potentials) pp.name = rtmName(pp.species, taken);
    const renamed = order.filter((s) => name.get(s) !== s).map((s) => [s, name.get(s)])
      .concat(minerals.filter((mn) => mn.name !== mn.phase).map((mn) => [mn.phase, mn.name]))
      .concat(gases.filter((g) => g.name !== g.phase).map((g) => [g.phase, g.name]))
      .concat(solids.flatMap((ss) => ss.comps.filter((c) => c.name !== c.phase).map((c) => [c.phase, c.name])))
      .concat([...exName].filter(([sp, nm]) => sp !== nm));
    const side = (terms) => terms
      .map((t) => (Math.abs(t.c - 1) > 1e-12 ? `${fmtCoef(t.c)} ` : '') + (name.get(t.n) || exName.get(t.n) || t.n))
      .join(' + ');
    /*
      Each exchange species' relation: its log K the one PHREEQC's activities
      give at this water, the database's at this temperature. Its ion's
      coefficient goes with it as a= and b= where PHREEQC takes it from the
      one ion of the relation, a master species, as this page does; where
      PHREEQC takes it otherwise, or from something this page does not
      write, it is folded into the log K at this water.
    */
    for (const e of onEx) {
      const aq = (terms) => terms.filter((t) => t.n !== 'H2O');
      const ions = aq([...e.left, ...e.right.slice(1)]).filter((t) => !laMaster.has(t.n));
      const g = db.exGamma.get(e.species);
      const hasWater = [...e.left, ...e.right].some((t) => t.n === 'H2O');
      /*
        Under SIT the page gives a species on an exchanger its ion's
        coefficient to the ion's power whenever its relation forms it from the
        exchanger and one ion, as PHREEQC does from the master species of its
        reaction (-pitzer_exchange_gammas): its log a here is its fraction and
        that (sitLg), and the log K takes whatever differs from PHREEQC's.
      */
      if (sitLike) {
        const one = ions.length === 1 && !hasWater ? ions[0] : null;
        e.sitLg = one ? Math.abs(one.c / e.right[0].c) * lg.get(one.n) : 0;
        e.gamma = one ? { sit: true } : null;
        e.folded = Math.abs(e.sitLg - e.lg) > 1e-12;
      } else {
        // Under LLNL's model its -llnl_gamma a, with its ion's B-dot form.
        const gg = llnl ? (db.exLlnl.has(e.species) ? { a: db.exLlnl.get(e.species), llnl: true } : null) : g;
        e.gamma = follow && e.lg !== 0 && gg && ions.length === 1 && !hasWater && db.masterLabel(ions[0].n) !== null
          ? gg : null;
        e.folded = follow && e.lg !== 0 && !e.gamma;
      }
      // log a: PHREEQC's ('db'); or this page's, an ion its molality alone
      // ('conditional') or times its coefficient ('follow'), the species its
      // fraction, times its ion's coefficient where it keeps it. The
      // exchanger's activity is PHREEQC's throughout.
      const laOf = (n, how) => {
        if (laMaster.has(n)) return laMaster.get(n);
        if (n === e.species && sitLike && how === 'follow') return e.la - e.lg + e.sitLg;
        if (n === e.species) return how === 'db' || (how === 'follow' && e.gamma) ? e.la : e.la - e.lg;
        return log10(molal.get(n)) + (how === 'conditional' ? 0 : lg.get(n));
      };
      const sum = (terms, how) => aq(terms).reduce((acc, t) => acc + t.c * laOf(t.n, how), 0);
      const nw = e.right.filter((t) => t.n === 'H2O').reduce((acc, t) => acc + t.c, 0)
        - e.left.filter((t) => t.n === 'H2O').reduce((acc, t) => acc + t.c, 0);
      e.logkC = sum(e.right, 'conditional') - sum(e.left, 'conditional');
      e.logkDb = sum(e.right, 'db') - sum(e.left, 'db') + nw * logAw;
      e.logk = sum(e.right, 'follow') - sum(e.left, 'follow') + nw * logAw;
    }
    // With activities: each species' -gamma, and a charge where a new name
    // would read differently; and the species whose activity PHREEQC works
    // out in a way this page does not.
    // (Under SIT every solute has SIT's coefficient, whatever its line says.)
    const unsupported = follow && !sitLike ? order.filter((sp) => db.otherGamma.has(sp)) : [];
    /*
      LLNL's: its tables, and every ion written with its -llnl_gamma: PHREEQC
      works out no coefficient of its own for one without (its A is not read
      under LLNL's model), and neither does this page. The water within the
      tables' temperatures, where PHREEQC stops otherwise.
    */
    if (llnl) {
      const T = db.llnl.temps;
      if (!T.length || [db.llnl.adh, db.llnl.bdh, db.llnl.bdot].some((x) => x.length !== T.length)) {
        throw new Error(`${o.database.name || 'This database'} gives LLNL's activity model without its tables at each `
          + 'temperature (-temperatures, -dh_a, -dh_b, -bdot).');
      }
      const bare = order.filter((sp) => chargeOf(sp) && !db.llnlGamma.has(sp) && !db.co2Gamma.has(sp));
      if (bare.length) {
        throw new Error(`${o.database.name || 'This database'} gives ${bare.slice(0, 4).join(', ')}${bare.length > 4 ? ', ...' : ''} `
          + 'no -llnl_gamma, and under LLNL\'s model PHREEQC has no coefficient for such an ion: keep the coefficients '
          + 'fixed at this water instead.');
      }
      if (order.some((sp) => db.co2Gamma.has(sp)) && db.llnl.co2.length !== 5) {
        throw new Error(`${o.database.name || 'This database'} gives a species -co2_llnl_gamma and no -co2_coefs, Drummond's five.`);
      }
    }
    /*
      SIT's interaction coefficients between the species written, at this
      water's temperature as PHREEQC works them out (sitParam), one line a
      pair: eps, and eps1 where the database gives the pair an -epsilon1.
    */
    const sitPairs = [];
    if (sit) {
      const tk = w.tc + 273.15;
      const written = new Set(order);
      const byPair = new Map();
      for (const p of db.sit.values()) {
        if (!written.has(p.s1) || !written.has(p.s2)) continue;
        const key = [...new Set([p.s1, p.s2])].sort().join(' ');
        const pair = byPair.get(key) || { s1: p.s1, s2: p.s2, eps: 0, eps1: 0 };
        pair[p.type] = sitParam(p.a, tk);
        byPair.set(key, pair);
      }
      sitPairs.push(...byPair.values());
    }
    /*
      PITZER'S PARAMETERS between the species written, each with the
      database's terms in the temperature, so that the run follows them as
      PHREEQC does (calc_pitz_param). And for the MacInnes scaling, which
      reads the ln gamma of Cl- whether the water has chloride or not, and the
      B0, B1 and C0 of K+ and Cl-: those, and every parameter of Cl- with the
      species written, where Cl- or K+ is not among them. The scaling is
      written off where PHREEQC turns it off.
    */
    const pzLines = [];
    const pzOpts = [];
    // PHREEQC's Pitzer model holds the pe where the water has it unless its PITZER says -redox (model.cpp).
    const holdPe = pitz && !db.pitzerOpts.redox;
    if (pitz) {
      const written = new Set(order);
      const kcl = (p) => ['B0', 'B1', 'C0'].includes(p.type) && new Set(p.sp).size === 2 && p.sp.includes('K+')
        && p.sp.includes('Cl-');
      const hasKcl = [...db.pitzer.values()].some(kcl);
      const icon = db.pitzerOpts.macinnes && hasKcl;
      const ok = (p) => p.sp.every((x) => written.has(x))
        || (icon && (kcl(p) || p.sp.every((x) => written.has(x) || x === 'Cl-')));
      for (const p of db.pitzer.values()) if (ok(p)) pzLines.push(p);
      if (!icon) pzOpts.push('MACINNES  no');
      if (!db.pitzerOpts.etheta) pzOpts.push('ETHETA  no');
    }

    const tc = w.tc;
    const date = o.date || new Date().toISOString().slice(0, 10);
    const width = Math.max(...order.map((s) => name.get(s).length), ...minerals.map((mn) => mn.name.length),
      ...gases.map((g) => g.name.length), ...solids.flatMap((ss) => ss.comps.map((c) => c.name.length)),
      ...[...exName.values()].map((nm) => nm.length), ...onSf.map((e) => e.name.length),
      ...potentials.map((pp) => pp.name.length), ...kinetics.map((k) => k.name.length)) + 2;
    const out = [];
    out.push(`# ${o.water.name || 'The water'} as PHREEQC leaves it, written on ${date}.`);
    out.push(`# Database: ${o.database.name || 'unnamed'}.`);
    out.push(`# PHREEQC: ${fmtG(tc, 6)} C, ionic strength ${fmtG(w.mu, 4)} mol/kgw, pH ${w.pH.toFixed(4)} `
      + `(-log a), -log m(H+) ${(-log10(w.mH)).toFixed(4)}, pe ${w.pe.toFixed(3)}, `
      + `a(H2O) ${w.aw.toFixed(6)}, charge balance ${fmtG(w.cb, 3)} eq/kgw.`);
    out.push('#');
    out.push('# Concentrations are molalities (mol/kgw); rate constants you add must use the same unit.');
    if (sit) {
      out.push(`# Each log K is the database's own at ${fmtG(tc, 6)} C, and the relations hold between activities:`);
      out.push("# ACTIVITY = sit works out each species' activity coefficient in its cell as the run goes on,");
      out.push("# as PHREEQC's SIT does: a Debye-Hueckel term in the ionic strength and, for each species it");
      out.push("# is paired with in <SIT>, the database's interaction coefficient times that species' molality");
      out.push(`# (${sitPairs.length} pair${sitPairs.length === 1 ? '' : 's'} among the species here); and the activity of water from SIT's osmotic`);
      out.push('# coefficient. The comment gives the conditional log K at this water, the coefficients folded in.');
    } else if (llnl) {
      out.push(`# Each log K is the database's own at ${fmtG(tc, 6)} C, and the relations hold between activities:`);
      out.push("# ACTIVITY = llnl works out each species' activity coefficient in its cell as the run goes on, as");
      out.push("# PHREEQC's LLNL model does: an ion by its B-dot form with the database's -llnl_gamma (a=) and A, B");
      out.push('# and B-dot from the tables in <LLNL> at the temperature, a neutral species given -llnl_gamma at 1,');
      out.push("# CO2 and its like by Drummond's formula (drummond); and the activity of water where a relation has");
      out.push('# H2O. The comment gives the conditional log K at this water, the coefficients folded in.');
    } else if (pitz) {
      out.push(`# Each log K is the database's own at ${fmtG(tc, 6)} C, and the relations hold between activities:`);
      out.push("# ACTIVITY = pitzer works out each species' activity coefficient in its cell as the run goes on,");
      out.push("# as PHREEQC's Pitzer model does: the Debye-Hueckel term and, between the species here, the");
      out.push(`# database's parameters in <PITZER> (${pzLines.length}, each with its terms in the temperature); and the activity`);
      out.push("# of water from the osmotic coefficient. The comment gives the conditional log K at this water,");
      out.push('# the coefficients folded in.');
    } else if (follow) {
      out.push(`# Each log K is the database's own at ${fmtG(tc, 6)} C, and the relations hold between activities:`);
      out.push("# ACTIVITY works out each species' activity coefficient from the ionic strength of its cell");
      out.push("# as the run goes on, by the database's -gamma (a= and b=) where it gives one and Davies for");
      out.push('# any other ion, as PHREEQC does, and the activity of water where a relation has H2O. The');
      out.push('# comment gives the conditional log K at this water, the activity coefficients folded in.');
    } else {
      out.push('# Each log K is CONDITIONAL: the activity coefficients at this ionic strength and the');
      out.push('# activity of water are folded in, so the relations hold between concentrations exactly');
      out.push("# where PHREEQC's hold between activities. The comment gives the database's own log K at");
      out.push(`# ${fmtG(tc, 6)} C. If a run moves the ionic strength far from ${fmtG(w.mu, 3)}, look at it through`);
      out.push('# PHREEQC afterwards: the drift of the activity coefficients says how far off this gets.');
    }
    if (volumes) {
      out.push(`# The water is at ${fmtG(atm, 6)} atm${atVapour ? ', its vapour pressure times a(H2O)' : ''}: PHREEQC corrects each log K for the`);
      out.push("# pressure with the reaction's molar volumes, less dV (P - 1)/(R T ln 10), and so does the model with");
      out.push(`# the database's -Vm in <VOLUMES> (${volLines.length}) and the water's own, each going with the ionic strength. The`);
      out.push('# log K written are at one atmosphere.');
    }
    if (eUsed) {
      const list = tied.map((e) => name.get(e.species) || e.species);
      out.push('# Redox: each species the database writes with electrons is tied to the electron, e-, by its');
      out.push(`# reaction (${list.slice(0, 8).join(', ')}${list.length > 8 ? `, and ${list.length - 8} more` : ''}${
        minerals.some((mn) => withE(mn.reac) || withE(mn.prod)) ? '; and the phases that dissolve with electrons' : ''}),`);
      out.push("# so the couples share one pe, as in PHREEQC, each with the database's log K. e- is no amount:");
      out.push('# its activity is 10^-pe, which the run works out from the electrons the couples hold between them.');
      if (atNone.size) {
        const none = [...atNone].map((sp) => name.get(sp) || sp);
        out.push(`# Written at none, PHREEQC finding less than 1e-30 of them, so that they can arrive and form: ${none.length} species`);
        out.push(`# (${none.slice(0, 8).join(', ')}${none.length > 8 ? ', ...' : ''}), each with the database's log K.`);
      }
      if (outOfEq) {
        out.push(`# PHREEQC's water is out of redox equilibrium: it was given valence states its pe of ${fmtG(w.pe, 6)} does not`);
        out.push(`# hold, and its couples stand at pe ${fmtG(peSpread[0], 6)} to ${fmtG(peSpread[1], 6)}. The run starts where they settle on`);
        out.push("# one pe, the electrons kept, as PHREEQC's next step would.");
      } else if (settled && Math.abs(settled.to - settled.from) > 1e-6) {
        out.push(`# The water is PHREEQC's next step: its valence states put on one pe, ${fmtG(settled.to, 6)}, where it was`);
        out.push(`# given ${fmtG(settled.from, 6)} and the valence states as written.`);
      } else {
        out.push(`# The start is PHREEQC's water, at its pe of ${fmtG(w.pe, 6)}.`);
      }
      if (holdPe) {
        out.push("# PHREEQC's Pitzer model holds the pe where the water has it, its PITZER giving no -redox, and so");
        out.push(`# does the run: the electron is fixed at pe ${fmtG(w.pe, 6)}.`);
      }
    } else if (carryRedox) {
      out.push('# Redox: no species written here is one the database writes with electrons, so none is');
      out.push('# tied to a pe.');
    } else {
      out.push('# No redox relation is written: each valence state keeps its own total, and electrons');
      out.push('# move only through the reactions you add.');
    }
    if (o.exact) {
      out.push('# Every relation is also held exactly during the run (EQUILIBRATE = always): in every');
      out.push('# cell it is an algebraic equation, and what the relations conserve is integrated in');
      out.push('# place of the species they move. Only the NDF solves that; Auto hands it to the NDF.');
    } else if (o.relax) {
      out.push('# Every relation is also held during the run, as a fast pair (kb = kf/K): each kf is');
      out.push(`# what makes that relation relax back at ${fmtG(o.relax, 6)} per second at this water. The kf are`);
      out.push('# per second: change TIME_UNIT and they have to change with it.');
    } else if (o.kf) {
      out.push(`# Every relation is also held during the run, as a fast pair with kf = ${fmtG(o.kf, 6)}.`);
    } else {
      out.push('# The relations put the start on equilibrium (EQUILIBRATE = 1) and nothing more; give');
      out.push('# each a kf to hold them during the run as well.');
    }
    if (minerals.length) {
      out.push('# The phases of EQUILIBRIUM_PHASES are minerals, at the amounts PHREEQC left (mol/kgw), each');
      out.push(`# held at its saturation index while there is any of it: ${minerals.map((mn) => `${mn.name} (SI ${fmtG(mn.target, 6)})`).join(', ')}.`);
    }
    if (phasesSkipped.length) {
      out.push(`# Phases not carried: ${phasesSkipped.map((ps) => `${ps.name}, ${ps.why}`).join('; ')}.`);
    }
    if (gases.length) {
      const list = gases.map((g) => `${g.name} ${fmtG(g.amount, 4)}`).join(', ');
      if (gases[0].crit) {
        out.push("# Its gases are real gases, as PHREEQC holds them where the database gives each its critical temperature");
        out.push("# and pressure: each gas's activity is its fugacity, phi times its partial pressure, phi from Peng and");
        out.push("# Robinson's equation of state (Tc, Pc, omega on its line, the pairs' binary parameters in <GAS_PAIRS>).");
      }
      if (gasFixed.fixed === 'pressure') {
        out.push(`# A gas phase at a fixed total pressure of ${fmtG(gasFixed.pressure, 6)} atm (PHREEQC's GAS_PHASE), its gases at the`);
        out.push(`# moles PHREEQC left in it to each kg of water (${list}). Each gas's activity is its partial`);
        out.push("# pressure, its share of the bubble times the total, and the bubble is there only while the");
        out.push('# pressures the water holds its gases at add up to the total.');
      } else {
        out.push(`# A gas phase in a fixed volume of ${fmtG(gasFixed.volume, 6)} L to each kg of water (PHREEQC's GAS_PHASE), its gases`);
        out.push(`# at the moles PHREEQC left in it (${list}). Each gas's partial pressure is ${gases[0].crit ? 'its share of the'
          + " equation's pressure at V/N" : 'n R T/V'}.`);
        out.push(`# PHREEQC puts the water at the gas phase's pressure, ${fmtG(gasFixed.atm, 6)} atm here, and so does PRESSURE: the run`);
        out.push('# holds it there, where PHREEQC follows the pressure as the gas phase fills or empties.');
      }
    }
    if (gasSkipped.length) {
      out.push(`# Not carried from the gas phase: ${gasSkipped.map((x) => `${x.name}, ${x.why}`).join('; ')}.`);
    }
    for (const ss of solids) {
      const present = ss.comps.some((c) => c.amount > 0);
      out.push(`# The solid solution ${ss.name} (PHREEQC's SOLID_SOLUTIONS): ${ss.comps.map((c) => c.name).join(', ')}, `
        + `${present ? 'at the moles PHREEQC left in it' : 'which PHREEQC finds the water undersaturated in: none of it'}`
        + `${ss.energy ? `; Guggenheim's a0 ${fmtG(ss.energy.a0, 6)} and a1 ${fmtG(ss.energy.a1, 6)} at ${fmtG(ss.tk, 6)} K` : '; ideal'}.`);
    }
    if (solidsSkipped.length) {
      out.push(`# Not carried from the solid solutions: ${solidsSkipped.map((x) => `${x.name}, ${x.why}`).join('; ')}.`);
    }
    if (onEx.length) {
      const cap = (sp) => onEx.filter((e) => e.master === sp)
        .reduce((acc, e) => acc + e.m * (e.right.concat(e.left).find((t) => t.n === sp) || { c: 0 }).c, 0);
      out.push(`# The exchanger${exUsed.length > 1 ? 's' : ''} ${exUsed.map((sp) => `${exName.get(sp)} (${fmtG(cap(sp), 6)} eq/kgw)`).join(', ')}`
        + ' with the species PHREEQC put on');
      out.push('# it at their molalities: an exchanger is no amount, its activity is solved for, and each');
      out.push("# species on it has its equivalent fraction for its activity (Gaines-Thomas)"
        + (follow ? ", times its ion's activity" : '.'));
      if (sitLike) out.push(`# coefficient, as PHREEQC's ${sit ? 'SIT' : 'Pitzer model'} has it.`);
      else if (llnl) out.push("# coefficient where the database gives it -llnl_gamma (a=), LLNL's B-dot form.");
      else if (follow) out.push('# coefficient where the database gives it -gamma (a= and b=).');
      const folded = onEx.filter((e) => e.folded);
      if (folded.length) {
        out.push(`# PHREEQC takes the coefficient of ${folded.map((e) => e.name).join(', ')} from more than its one ion; `
          + 'here it is folded into the log K at this water.');
      }
      for (const e of onEx) {
        const p = exPer.get(e.species);
        if (!p) continue;
        out.push(`# The sites of ${exName.get(e.master)} go with ${p.carrier.name}, ${fmtG(p.ratio, 6)} of ${e.name} to each mole `
          + `of it (PHREEQC's ${p.kind}),`);
        out.push(`# ${fmtG(p.sites, 6)} sites a mole (sites= per=): each species on them has its fraction of what is on it now.`);
      }
      for (const x of exHeld) {
        out.push(`# In PHREEQC the capacity of ${x.exchanger} goes with ${x.phase}; here it is held at what PHREEQC loaded at `
          + `the start: ${x.why}.`);
      }
    }
    if (exSkipped.length) {
      out.push(`# Not carried from the exchanger: ${exSkipped.map((x) => `${x.name}, ${x.why}`).join('; ')}.`);
    }
    if (onSf.length) {
      const sites = onSf.filter((e) => e.master).map((e) => {
        const total = onSf.filter((x) => x === e || (!x.master && [...x.left, ...x.right.slice(1)].some((t) => t.n === e.species)))
          .reduce((acc, x) => acc + x.m * (x === e ? 1 : [...x.left, ...x.right.slice(1)].find((t) => t.n === e.species).c), 0);
        return `${e.name} (${fmtG(total, 4)} mol/kgw)`;
      });
      if (potentials.some((pp) => pp.cd)) {
        out.push(`# On a surface, by CD-MUSIC: the sites ${sites.join(' and ')},`);
      } else if (potentials.length) {
        out.push(`# On a surface, with its diffuse double layer: the sites ${sites.join(' and ')},`);
      } else {
        out.push(`# On a surface, without electrostatics (-no_edl): the sites ${sites.join(' and ')},`);
      }
      out.push('# with the species PHREEQC put on them at their molalities. Each has its fraction of its');
      out.push("# sites for its activity, and its relation the database's log K.");
      for (const pp of potentials.filter((x) => x.cd && !x.plane)) {
        const [b, d] = potentials.filter((x) => x.surface === pp.surface && x.plane).map((x) => x);
        out.push(`# ${pp.name}, ${b.name} and ${d.name} are the potentials of the planes 0, 1 and 2 of the CD-MUSIC surface`);
        out.push(`# ${pp.surface}, ${fmtG(pp.psi * 1e3, 5)}, ${fmtG(b.psi * 1e3, 5)} and ${fmtG(d.psi * 1e3, 5)} mV here, with the capacitances`);
        out.push(`# ${fmtG(pp.cap[0], 6)} and ${fmtG(pp.cap[1], 6)} F/m2 between them: rtm.html puts each into the relations on ${pp.surface} by`);
        out.push('# the charge they put on its plane (dz0, dz1 and dz2, the database\'s -cd_music), as PHREEQC does,');
        out.push("# and solves for them with PHREEQC's three equations, the diffuse layer's from every ion.");
      }
      for (const pp of potentials.filter((x) => !x.cd)) {
        out.push(pp.phase ? `# ${pp.name} is the potential of the surface ${pp.surface}, ${fmtG(pp.area, 6)} m2 to each mole of ${pp.phase},`
          + ' whose amount it goes with,'
          : `# ${pp.name} is the potential of the surface ${pp.surface}, ${fmtG(pp.area, 6)} m2/g and ${fmtG(pp.grams, 6)} g of it`
            + ' to each kg of water,');
        out.push(`# at ${fmtG(pp.psi * 1e3, 5)} mV here: rtm.html puts it into each relation on ${pp.surface}`);
        out.push("# by the charge the relation puts on the surface, as PHREEQC does, and solves for it with Gouy");
        out.push("# and Chapman's equation. Its value is its activity, exp(-F psi/RT).");
      }
    }
    if (sfSkipped.length) {
      out.push(`# Not carried from the surface: ${sfSkipped.map((x) => `${x.name}, ${x.why}`).join('; ')}.`);
    }
    if (unsupported.length) {
      out.push(`# PHREEQC works out the activity of ${unsupported.join(', ')} otherwise (${[...new Set(
        unsupported.map((sp) => db.otherGamma.get(sp)))].join(', ')}); here ${unsupported.length > 1 ? 'they follow' : 'it follows'}`);
      out.push('# the rule above.');
    }
    if (renamed.length) {
      out.push('# Renamed, since rtm.html cannot write the name as PHREEQC does:');
      for (const [s, r] of renamed) out.push(`#   ${s}  ->  ${r}`);
    }
    /*
      THE COLUMN (columnSetup): PHREEQC's cells, each as long; its time step
      the time the water takes to cross one; its dispersivity a Peclet number
      over the column and its diffusion coefficient every species' D, both
      times -correct_disp's factor where it has one, as PHREEQC's mixing
      takes it (transport.cpp); its ends, each water at an end that flows in
      or holds the column on every species that moves.

      STAGNANT CELLS (-stagnant 1 alpha theta_m theta_im): PHREEQC mixes each
      cell's water with the stagnant water behind it at every step as the
      first order exchange theta_m dC/dt = -alpha (C - C_im), theta_im
      dC_im/dt = alpha (C - C_im) comes to over it (transport.cpp, b and f).
      The page's rock matrix of one layer is that exchange: a layer of depth
      d and porosity eps behind water touching aw of it changes the water at
      2 aw De/d times the difference and itself at 2 De/(eps d^2). A layer 1 m
      deep, of the stagnant porosity, aw = 1/theta_m and every species' Dm =
      alpha/2 give alpha/theta_m and alpha/theta_im, and the stagnant water
      per cell's water, aw eps d, is theta_im/theta_m.
    */
    let colSettings = null;
    let colReport = null;
    let colD = 0;
    let mcdOf = null;
    let leftAt = null;
    let rightAt = null;
    if (column) {
      const { t, corr, mcd } = column;
      const L = t.lengths.reduce((a, b) => a + b, 0);
      const even = t.lengths.every((x) => Math.abs(x - t.lengths[0]) <= 1e-12 * t.lengths[0]);
      const v = t.dir ? (t.dir * t.lengths[0]) / t.dt : 0;
      const alpha = t.dir ? t.disp[0] * corr : 0;
      colD = mcd ? 0 : t.diffc * corr;
      /*
        MULTICOMPONENT DIFFUSION (-multi_D): each species at PHREEQC's Dw at
        the water's temperature, Dw times viscos_0(25 C)/viscos_0, times
        exp(dw_t/T - dw_t/298.15) and (viscos_0/viscos)^dw_a_v_dif where -dw
        gives them -- -multi_D's own Dw, without those, for a species without
        -dw -- and times the porosity to the n (fill_spec, find_J): its D
        along the column. PHREEQC couples the ions so that no current flows,
        DIFFUSION = nernst-planck, and moves each down its activity,
        DIFFUSION_GRADIENT = activity, where the activity coefficients
        follow the water. -diffusion_coefficient is then for heat alone.
      */
      if (mcd) {
        const visc0 = Number(w.x[viscAt]);
        const visc = Number(w.x[viscAt + 1]);
        const tk = w.tc + 273.15;
        mcdOf = (sp) => {
          const dw = db.dw.get(sp) || 0;
          let d = (dw || mcd.dw) * (VISCOS_0_25 / visc0);
          if (dw) {
            const dwt = db.dwT.get(sp) || 0;
            if (dwt) d *= Math.exp(dwt / tk - dwt / 298.15);
            const avd = db.dwVisc.get(sp) || 0;
            if (avd) d *= (visc0 / visc) ** avd;
          }
          return d * mcd.factor;
        };
      }
      const face = (b, isIn) => (b === 1 ? 'dirichlet' : b === 2 ? 'neumann' : isIn ? 'robin' : t.dir ? 'free' : 'neumann');
      const leftKind = face(t.bc[0], t.dir > 0);
      const rightKind = face(t.bc[1], t.dir < 0);
      if (leftKind === 'dirichlet' || leftKind === 'robin') leftAt = column.left;
      if (rightKind === 'dirichlet' || rightKind === 'robin') rightAt = column.right;
      let x = 0;
      const faces = [0, ...t.lengths.map((l) => { x += l; return x; })];
      colSettings = ['MODE = transport', `CELLS = ${t.cells}`,
        ...(even ? [`LENGTH = ${fmtG(L, 15)}`] : ['GRID = faces', `FACES = ${faces.map((f) => fmtG(f, 15)).join(', ')}`]),
        ...(mcd ? ['DIFFUSION = nernst-planck', ...(follow && !t.implicit ? ['DIFFUSION_GRADIENT = activity'] : [])]
          : colD > 0 || alpha > 0 ? ['DIFFUSION = 1'] : []),
        ...(t.dir ? ['ADVECTION = 1', 'ADVECTION_SCHEME = limited', `VELOCITY = ${fmtG(v, 15)}`] : []),
        ...(alpha > 0 ? [`PECLET = ${fmtG(L / alpha, 15)}`] : []),
        `LEFT = ${leftKind}`, `RIGHT = ${rightKind}`,
        ...(column.stag ? ['MATRIX_CELLS = 1', 'MATRIX_DEPTH = 1', 'MATRIX_FIRST = 1',
          `MATRIX_POROSITY = ${fmtG(column.stag.thim, 15)}`, `WETTED_SURFACE = ${fmtG(1 / column.stag.thm, 15)}`] : [])];
      colReport = { kind: t.kind, cells: t.cells, length: L, lengths: even ? null : t.lengths, shifts: t.shifts,
        timeStep: t.dt, velocity: v, dispersivity: t.dir ? t.disp[0] : 0, correction: corr, diffusion: t.diffc,
        multiD: mcd ? { porosity: mcd.porosity, n: mcd.n, factor: mcd.factor, defaultDw: mcd.dw,
          gradient: follow && !t.implicit ? 'activity' : 'concentration', implicit: t.implicit,
          withoutDw: order.filter((sp) => !db.dw.get(sp)) } : null,
        left: leftKind, right: rightKind, leftSolution: leftAt ? column.leftSol : null,
        rightSolution: rightAt ? column.rightSol : null, tend: t.shifts * t.dt, after: t.after,
        zones: column.zones.map((z) => ({ cells: [z.lo, z.hi], as: z.rep })),
        stagnant: column.stag ? { alpha: column.stag.alpha, thm: column.stag.thm, thim: column.stag.thim,
          zones: column.stag.zones.map((z) => ({ cells: [z.lo, z.hi], as: z.rep, same: z.same })) } : null,
        elsewhere: [...elsewhere] };
      const sol = (s) => `SOLUTION ${s}`;
      const endSay = (kind, s, where) => (kind === 'robin' ? `${sol(s)} flows in at the ${where}`
        : kind === 'dirichlet' ? `${sol(s)} holds the ${where} end (constant)`
          : kind === 'free' ? `the water leaves at the ${where}` : `the ${where} end is closed`);
      out.push(`# The column of the input's ${t.kind}: ${t.cells} cells${even ? ` of ${fmtG(t.lengths[0], 6)} m`
        : `, ${fmtG(L, 6)} m in all`}, ${t.dir ? `the water moving a cell in each time step of ${fmtG(t.dt, 6)} s, `
        + `${fmtG(Math.abs(v), 6)} m/s ${t.dir > 0 ? 'to the right' : 'to the left'}, for ${t.shifts} shifts`
        : `diffusing for ${t.shifts} periods of ${fmtG(t.dt, 6)} s`}, ${fmtG(t.shifts * t.dt, 6)} s;`);
      out.push(`# dispersivity ${fmtG(t.dir ? t.disp[0] : 0, 6)} m${corr !== 1 ? ` (times ${fmtG(corr, 6)}, -correct_disp)` : ''}, `
        + (mcd ? 'multicomponent diffusion (below). '
          : `diffusion coefficient ${fmtG(t.diffc, 6)} m2/s${corr !== 1 && t.diffc > 0 ? ` (times ${fmtG(corr, 6)})` : ''}. `)
        + `${endSay(leftKind, column.leftSol, 'left')}; ${endSay(rightKind, column.rightSol, 'right')}.`);
      if (mcd) {
        const none = order.filter((sp) => !db.dw.get(sp));
        out.push(`# Multicomponent diffusion (-multi_D): each species at its Dw in the database at ${fmtG(w.tc, 6)} C${none.length
          ? `, ${fmtG(mcd.dw, 6)} m2/s for ${none.length === 1 ? 'the one' : `the ${none.length}`} without -dw` : ''},`);
        out.push(`# times the porosity ${fmtG(mcd.porosity, 6)} to the ${fmtG(mcd.n, 6)}, ${fmtG(mcd.factor, 6)}: its D. The ions are coupled so that no current flows,`);
        out.push(t.implicit ? '# as PHREEQC has them; each diffuses down its concentration, as PHREEQC\'s -implicit scheme takes it.'
          : follow ? '# and each diffuses down its activity, as PHREEQC has them.'
            : '# as PHREEQC has them; each diffuses down its concentration, the activity coefficients folded into the log K.');
      }
      out.push(column.zones.length > 1 ? `# The cells start as PHREEQC equilibrates them before the first shift, in ${column.zones.length} zones: `
        + `${column.zones.map((z) => `${z.lo}-${z.hi}`).join(', ')}, the first as written here and the rest in <INITIAL>,`
        : '# Every cell starts from the water of cell 1 as PHREEQC equilibrates it before the first shift,');
      const endSols = [column.leftSol, column.rightSol].filter((s) => s >= 0).map(sol).join(' and ');
      out.push(column.zones.length > 1 ? `# each with ${fmtG(column.trace, 3)} of every other zone's water${endSols ? ` and of ${endSols}` : ''}, `
        + 'which have as much of each: what only one has is then a total everywhere.'
        : `# with ${fmtG(column.trace, 3)} of ${endSols || 'nothing'} in it, which each have ${fmtG(column.trace, 3)} of the column's: `
          + 'what only one has is then a total everywhere.');
      if (elsewhere.size) {
        out.push(`# Cell 1's water has none of ${[...elsewhere].map((sp) => name.get(sp) || sp).join(', ')}, which another water `
          + 'brings, its trace of it gone elsewhere in');
        out.push('# PHREEQC\'s speciation: written here at that trace, with the database\'s log K.');
      }
      if (column.stag) {
        const st = column.stag;
        const apart = st.zones.filter((z) => !z.same);
        out.push(`# Stagnant cells behind them (-stagnant 1 ${fmtG(st.alpha, 6)} ${fmtG(st.thm, 6)} ${fmtG(st.thim, 6)}): PHREEQC's `
          + 'first order exchange at alpha between a cell\'s water (theta_m)');
        out.push('# and its stagnant water (theta_im), here a rock matrix of one layer of the stagnant porosity, 1 m deep, the');
        out.push(`# wetted surface 1/theta_m and every species' Dm alpha/2, which change them at alpha/theta_m and alpha/theta_im.`);
        out.push(apart.length ? `# The stagnant cells start as PHREEQC equilibrates them, ${apart.map((z) => `behind cells ${z.lo}-${z.hi} as `
          + `cell ${z.rep}`).join(', ')} in <INITIAL>${apart.length < st.zones.length ? ', the rest as cell 1' : ''}.`
          : '# The stagnant cells start as cell 1, as PHREEQC equilibrates them.');
      }
      if (t.dir) {
        out.push('# PHREEQC shifts each cell\'s water whole and then reacts it; here the water moves through the cells as');
        out.push('# it reacts: a cell of PHREEQC\'s after shift k is this one half a time step later, and the two meet');
        out.push('# as the cells are refined, the velocity and the time kept.');
      }
    }
    // A kinetic run goes as long as PHREEQC's steps; a column as long as its shifts.
    const kinTime = kinetics.length ? kinBlock.steps.reduce((a, b) => a + b, 0) : 0;
    const tend = column ? column.t.shifts * column.t.dt : kinTime;
    out.push('', '<SETTINGS>', ...(colSettings || ['MODE = batch']), `TEND = ${tend > 0 ? fmtG(tend, 15) : 1}`,
      'TIME_UNIT = second', `EQUILIBRATE = ${o.exact ? 'always' : '1'}`);
    // A relation whose log K goes with temperature reads it, without ACTIVITY too.
    const withT = (terms) => !!terms && (terms[1] !== 0 || terms.slice(2).some((v) => v !== 0));
    const anyT = eqs.some((e) => withT(db.logKTerms('s', e.species))) || minerals.some((mn) => withT(db.logKTerms('p', mn.phase)))
      || solids.some((ss) => !!ss.energy || ss.comps.some((c) => withT(db.logKTerms('p', c.phase))))
      || gases.some((g) => withT(db.logKTerms('p', g.phase))) || onEx.some((e) => withT(db.logKTerms('x', e.species)))
      || onSf.some((e) => !e.master && withT(db.logKTerms('f', e.species)));
    if (follow) out.push(`ACTIVITY = ${sit ? 'sit' : pitz ? 'pitzer' : llnl ? 'llnl' : 'debye-huckel'}`, `TEMPERATURE = ${fmtG(tc, 10)}`);
    // A double layer reads it too, without ACTIVITY, and a gas phase (R T).
    else if (potentials.length || gases.length || anyT) out.push(`TEMPERATURE = ${fmtG(tc, 10)}`);
    if (gases.length) {
      out.push(gasFixed.fixed === 'pressure' ? `GAS_PRESSURE = ${fmtG(gasFixed.pressure, 12)}`
        : `GAS_VOLUME = ${fmtG(gasFixed.volume, 12)}`);
      // The water at the gas phase's pressure, as PHREEQC puts it: its A, B and dielectric constant.
      if (gasFixed.fixed === 'volume' && gasFixed.atm > 0 && Math.abs(gasFixed.atm - 1) > 1e-12) {
        out.push(`PRESSURE = ${fmtG(gasFixed.atm, 15)}`);
      }
    }
    /*
      The water's own pressure where it is another than one atmosphere, as
      PHREEQC keeps it with the solution: the vapour pressure times a(H2O)
      where that is higher than the pressure given, which a later step holds
      the water at while its vapour pressure is no higher (calc_rho_0). A gas
      phase sets its own.
    */
    if (!gases.length && Number.isFinite(atm) && Math.abs(atm - 1) > 1e-12) out.push(`PRESSURE = ${fmtG(atm, 15)}`);
    // Each species its own D: the ions coupled, so the water stays neutral as they spread. A column has TRANSPORT's.
    if (o.dw && !column) out.push('DIFFUSION = nernst-planck');
    out.push('', '<SPECIES>');
    const width2 = Math.max(...order.map((sp) => fmtG(molal.get(sp), 15).length),
      ...minerals.map((mn) => fmtG(mn.amount, 15).length), ...onEx.map((e) => fmtG(e.m, 15).length),
      ...onSf.map((e) => fmtG(e.m, 15).length), ...potentials.map((pp) => fmtG(pp.a, 15).length),
      ...gases.map((g) => fmtG(g.amount, 15).length), ...solids.flatMap((ss) => ss.comps.map((c) => fmtG(c.amount, 15).length)),
      ...kinetics.map((k) => fmtG(k.amount, 15).length)) + 2;
    for (const s of order) {
      let d = '';
      if (column) {
        // In a column: TRANSPORT's D, and the water at each end that flows in or holds it.
        d = [mcdOf ? `D=${fmtG(mcdOf(s), 10)}` : colD > 0 ? `D=${fmtG(colD, 6)}` : '',
          column.stag ? `Dm=${fmtG(column.stag.alpha / 2, 15)}` : '',
          leftAt ? `left=${fmtG(leftAt.get(s) || 0, 15)}` : '',
          rightAt ? `right=${fmtG(rightAt.get(s) || 0, 15)}` : ''].filter(Boolean).join('  ');
      } else if (o.dw && db.dw.has(s)) d = `D=${fmtG(db.dw.get(s), 6)}`;
      else if (o.D) d = `D=${fmtG(o.D, 6)}`;
      if (!follow) {
        out.push(`${name.get(s).padEnd(width)}${fmtG(molal.get(s), 15)}${d ? `  ${d}` : ''}`);
        continue;
      }
      const bits = [];
      if (chargeOf(name.get(s)) !== chargeOf(s)) bits.push(`z=${chargeOf(s)}`);
      // SIT and Pitzer take no a or b; LLNL's model the database's -llnl_gamma a, or drummond for -co2_llnl_gamma.
      const g = sitLike || llnl ? null : db.gamma.get(s);
      if (llnl) {
        if (db.co2Gamma.has(s)) bits.push('drummond');
        else if (db.llnlGamma.has(s)) bits.push(`a=${fmtG(db.llnlGamma.get(s), 15)}`);
      } else if (g) {
        if (chargeOf(s)) bits.push(`a=${fmtG(g.a, 6)}`);
        bits.push(`b=${fmtG(g.b, 6)}`);
      }
      if (d) bits.push(d);
      const more = bits.join('  ');
      out.push(`${name.get(s).padEnd(width)}${more ? fmtG(molal.get(s), 15).padEnd(width2) + more
        : fmtG(molal.get(s), 15)}`);
    }
    if (eUsed) {
      out.push(`${'e-'.padEnd(width)}${''.padEnd(follow ? width2 : 0)}electron${holdPe ? `  pe=${fmtG(w.pe, 15)}  fixed` : ''}`);
    }
    for (const mn of minerals) {
      const amount = fmtG(mn.amount, 15);
      // PHREEQC's dissolve_only, precipitate_only, -force_equality.
      const flags = `${mn.only ? `  ${mn.only}_only` : ''}${mn.forced ? '  force_equality' : ''}`;
      out.push(`${mn.name.padEnd(width)}${follow ? `${amount.padEnd(width2)}mineral` : `${amount}  mineral`}${flags}`);
    }
    for (const ss of solids) {
      for (const c of ss.comps) {
        const amount = fmtG(c.amount, 15);
        out.push(`${c.name.padEnd(width)}${follow ? `${amount.padEnd(width2)}mineral` : `${amount}  mineral`}`);
      }
    }
    // A kinetic reactant: what is left of it, which its rate takes and gives.
    for (const k of kinetics) {
      const amount = fmtG(k.amount, 15);
      out.push(`${k.name.padEnd(width)}${follow ? `${amount.padEnd(width2)}mineral` : `${amount}  mineral`}`);
    }
    for (const g of gases) {
      const amount = fmtG(g.amount, 15);
      const crit = g.crit ? `  Tc=${fmtG(g.crit.tc, 10)}  Pc=${fmtG(g.crit.pc, 10)}  omega=${fmtG(g.crit.omega, 10)}` : '';
      out.push(`${g.name.padEnd(width)}${follow ? `${amount.padEnd(width2)}gas` : `${amount}  gas`}${crit}`);
    }
    for (const sp of exUsed) out.push(`${exName.get(sp).padEnd(width)}${''.padEnd(follow ? width2 : 0)}exchanger`);
    for (const e of onEx) {
      const amount = fmtG(e.m, 15);
      const g = e.gamma && !sitLike ? (e.gamma.llnl ? `  a=${fmtG(e.gamma.a, 15)}`
        : `  a=${fmtG(e.gamma.a, 6)}  b=${fmtG(e.gamma.b, 6)}`) : '';
      // The form an exchanger's sites go with a mineral in: so many sites to each mole of it (sites= per=).
      const p = exPer.get(e.species);
      out.push(`${e.name.padEnd(width)}${follow ? amount.padEnd(width2) : `${amount}  `}exchange${g}`
        + `${p ? `  sites=${fmtG(p.sites, 12)}  per=${p.carrier.name}` : ''}`);
    }
    // What a surface's sites, and its area, go with: a mineral, or a kinetic reactant, as written.
    const carrierOf = (phase, kind) => (!phase ? null : kind === 'kinetic_reactant'
      ? kinetics.find((k) => k.comp.name.toLowerCase() === phase.toLowerCase()) || null
      : minerals.find((m) => m.phase === phase) || null);
    for (const pp of potentials) {
      const amount = fmtG(pp.a, 15);
      const mn = carrierOf(pp.phase, pp.kind);
      // CD-MUSIC's planes 1 and 2 take nothing; its first the area and the capacitances too.
      out.push(`${pp.name.padEnd(width)}${follow ? amount.padEnd(width2) : `${amount}  `}potential`
        + (pp.plane ? '' : `  area=${fmtG(pp.area, 10)}  ${mn ? `per=${mn.name}` : `grams=${fmtG(pp.grams, 8)}`}`
          + (pp.cd ? `  c0=${fmtG(pp.cap[0], 12)}  c1=${fmtG(pp.cap[1], 12)}` : '')));
    }
    // A site whose sites go with a phase or a kinetic reactant: so many per mole of the mineral it is carried as (sites= per=).
    const perOf = new Map();
    const perInfo = new Map();
    for (const b of sfBlocks.values()) {
      for (const x of b.sites) {
        const mn = carrierOf(x.phase, x.kind);
        if (!mn) continue;
        const site = db.sfMaster.get(x.master) || x.master;
        perOf.set(site, `  sites=${fmtG(x.ratio, 12)}  per=${mn.name}`);
        perInfo.set(site, { ratio: x.ratio, mineral: mn.name });
      }
    }
    for (const e of onSf) {
      const amount = fmtG(e.m, 15);
      // A charge the page's name does not give, a half on a CD-MUSIC site; and what the species puts on each plane.
      const zq = chargeFraction(e.species);
      const cut = e.species.indexOf('_');
      const dz = cut > 0 && layers.has(e.species.slice(0, cut)) && layers.get(e.species.slice(0, cut)).cd
        ? db.sfCd.get(e.species) : null;
      out.push(`${e.name.padEnd(width)}${follow ? amount.padEnd(width2) : `${amount}  `}surface`
        + `${e.master && perOf.has(e.species) ? perOf.get(e.species) : ''}`
        + `${zq !== chargeOf(e.name) ? `  z=${fmtG(zq, 12)}` : ''}`
        + `${dz ? dz.map((v, i) => (v ? `  dz${i}=${fmtG(v, 12)}` : '')).join('') : ''}`);
    }
    /*
      A column whose cells start apart (columnSetup's zones): each zone but
      cell 1's in <INITIAL>, its cells counted from 0 as the page counts
      them, every species as the zone's first cell comes out of PHREEQC's
      equilibration with its traces -- the water's species, what is on its
      exchangers and surfaces, and its phases' and kinetic reactants'
      amounts, per kilogram of its water. And each stagnant zone not alike
      with cell 1 the same way, "matrix" after it: the rock behind those
      cells, which otherwise starts as <SPECIES> says.
    */
    const stagApart = column && column.stag ? column.stag.zones.filter((z) => !z.same) : [];
    if (column && (column.zones.length > 1 || stagApart.length)) {
      out.push('', '<INITIAL>');
      const zoneLines = (z, rock) => {
        const cells = z.lo === z.hi ? `${z.lo - 1}` : `${z.lo - 1}-${z.hi - 1}`;
        const x = (expr) => { const i = z.extras.indexOf(expr); return i >= 0 ? Number(z.row.x[i]) : NaN; };
        const kgw = x('TOT("water")') > 0 ? x('TOT("water")') : 1;
        out.push(rock ? `# PHREEQC's stagnant cell${z.lo === z.hi ? ` behind cell ${z.lo}` : `s behind cells ${z.lo} to ${z.hi}`}, `
          + `as cell ${z.rep} comes out of its equilibration before the first shift`
          : `# PHREEQC's cell${z.lo === z.hi ? ` ${z.lo}` : `s ${z.lo} to ${z.hi}`}, as cell ${z.rep} comes out of its `
          + 'equilibration before the first shift');
        const put = (nm, v) => out.push(`${nm.padEnd(width)}  ${cells.padEnd(9)}${fmtG(Number.isFinite(v) ? v : 0, 15)}`
          + `${rock ? '  matrix' : ''}`);
        for (const sp of order) put(name.get(sp), (z.row.species.get(sp) || [0])[0]);
        for (const e of onEx) put(e.name, (z.row.exchange.get(e.species) || { m: 0 }).m);
        for (const e of onSf) put(e.name, (z.row.surface.get(e.species) || { m: 0 }).m);
        for (const mn of minerals) put(mn.name, x(`EQUI("${mn.phase}")`) / kgw);
        for (const k of kinetics) put(k.name, x(`KIN("${k.comp.name}")`) / kgw);
      };
      for (const z of column.zones.slice(1)) zoneLines(z, false);
      for (const z of stagApart) zoneLines(z, true);
    }
    out.push('', '<EQUILIBRIUM>');
    /*
      EACH RELATION'S LOG K AS IT GOES WITH TEMPERATURE: the database's terms
      (logKTerms) -- logK and dH, or the analytic expression with log_k and
      delta_h put into it where it has both -- so that a run at another
      TEMPERATURE, or one that follows it, has PHREEQC's; moved by what
      makes it, at this water's temperature, the one written here (`here`):
      PHREEQC's at this water, its pressure in it, or with activity
      coefficients fixed, those folded in. A number where the database gives
      none that goes with temperature.
    */
    const tkW = tc + 273.15;
    const kText = (terms, here) => {
      if (!terms || (terms[1] === 0 && terms.slice(2).every((v) => v === 0))) return `logK = ${here.toFixed(10)}`;
      const off = here - kCalc(terms, tkW);
      if (terms.slice(2).every((v) => v === 0)) return `logK = ${(terms[0] + off).toFixed(10)}, dH = ${fmtG(terms[1], 12)}`;
      const a = terms.slice(2);
      a[0] += terms[0] + terms[1] / (Math.LN10 * R_KJ * 298.15) + off;
      a[2] -= terms[1] / (Math.LN10 * R_KJ);
      let n = 6;
      while (n > 1 && a[n - 1] === 0) n--;
      // Each term as the shortest decimal that is that number exactly.
      return `analytic = ${a.slice(0, n).map((v) => String(v)).join(' ')}`;
    };
    const lines = eqs.map((e) => {
      const reac = follow ? e.left : e.reac;
      const prod = follow ? e.right : e.prod;
      return {
        rel: reac.length ? `${side(reac)} <=> ${side(prod)}` : ` <=> ${side(prod)}`,
        k: `${kText(db.logKTerms('s', e.species), follow ? atOneAtm(e.logk, e.left, e.right) : e.logkC)}`
          + `${e.kf ? `, kf = ${fmtG(e.kf, 6)}` : ''}`,
        note: follow ? `# here ${e.logkC.toFixed(4)}` : `# log K ${e.logk.toFixed(4)}`,
      };
    });
    // A mineral's saturation: its activity is 1, and its log K the phase's at
    // this temperature plus the saturation index it is held at.
    for (const mn of minerals) {
      const aq = (terms) => terms.filter((t) => t.n !== 'H2O');
      // An alternative reaction: what dissolves, held where its phase's saturation index is (SI(), <PHASES>).
      if (mn.alt) {
        lines.push({
          rel: `${side([{ c: 1, n: mn.name }, ...(follow ? mn.alt.reac : aq(mn.alt.reac))])} <=> `
            + `${side(follow ? mn.alt.prod : aq(mn.alt.prod))}`,
          k: `SI(${phaseName.get(mn.phase) || mn.phase}) = ${fmtG(mn.si, 15)}`,
          note: `# ${mn.alt.formula} as it holds ${mn.phase} there`,
        });
        continue;
      }
      const sumLg = (terms) => aq(terms).reduce((acc, t) => acc + t.c * lgOf(t.n), 0);
      const nw = mn.prod.filter((t) => t.n === 'H2O').reduce((acc, t) => acc + t.c, 0)
        - mn.reac.filter((t) => t.n === 'H2O').reduce((acc, t) => acc + t.c, 0);
      const logk = mn.lk + mn.si;
      const logkC = logk - sumLg(mn.prod) + sumLg(mn.reac) - nw * logAw;
      const reac = [{ c: mn.c0, n: mn.name }, ...(follow ? mn.reac : aq(mn.reac))];
      const prod = follow ? mn.prod : aq(mn.prod);
      lines.push({
        rel: `${side(reac)} <=> ${side(prod)}`,
        k: kText(db.logKTerms('p', mn.phase), follow ? atOneAtm(logk, [{ c: mn.c0, n: mn.phase }, ...mn.reac], mn.prod,
          mn.phase) : logkC),
        note: `${follow ? `# here ${logkC.toFixed(4)}` : `# log K ${logk.toFixed(4)}`}${mn.target ? `, SI ${fmtG(mn.target, 6)}` : ''}`,
      });
    }
    // A gas's dissolution: its activity is its partial pressure, and its log K the phase's at this temperature.
    for (const g of gases) {
      const aq = (terms) => terms.filter((t) => t.n !== 'H2O');
      const sumLg = (terms) => aq(terms).reduce((acc, t) => acc + t.c * lgOf(t.n), 0);
      const nw = g.prod.filter((t) => t.n === 'H2O').reduce((acc, t) => acc + t.c, 0)
        - g.reac.filter((t) => t.n === 'H2O').reduce((acc, t) => acc + t.c, 0);
      const logkC = g.lk - sumLg(g.prod) + sumLg(g.reac) - nw * logAw;
      const reac = [{ c: g.c0, n: g.name }, ...(follow ? g.reac : aq(g.reac))];
      const prod = follow ? g.prod : aq(g.prod);
      lines.push({
        rel: `${side(reac)} <=> ${side(prod)}`,
        k: kText(db.logKTerms('p', g.phase), follow ? atOneAtm(g.lk, [{ c: g.c0, n: g.phase }, ...g.reac], g.prod, g.phase)
          : logkC),
        note: `${follow ? `# here ${logkC.toFixed(4)}` : `# log K ${g.lk.toFixed(4)}`}, ${fmtG(g.pressure, 4)} atm`,
      });
    }
    // A solid solution's member's dissolution: its log K the pure phase's at this temperature.
    for (const ss of solids) {
      for (const c of ss.comps) {
        const aq = (terms) => terms.filter((t) => t.n !== 'H2O');
        const sumLg = (terms) => aq(terms).reduce((acc, t) => acc + t.c * lgOf(t.n), 0);
        const nw = c.prod.filter((t) => t.n === 'H2O').reduce((acc, t) => acc + t.c, 0)
          - c.reac.filter((t) => t.n === 'H2O').reduce((acc, t) => acc + t.c, 0);
        const logkC = c.lk - sumLg(c.prod) + sumLg(c.reac) - nw * logAw;
        const reac = [{ c: c.c0, n: c.name }, ...(follow ? c.reac : aq(c.reac))];
        const prod = follow ? c.prod : aq(c.prod);
        lines.push({
          rel: `${side(reac)} <=> ${side(prod)}`,
          k: kText(db.logKTerms('p', c.phase), follow ? atOneAtm(c.lk, [{ c: c.c0, n: c.phase }, ...c.reac], c.prod, c.phase)
            : logkC),
          note: `${follow ? `# here ${logkC.toFixed(4)}` : `# log K ${c.lk.toFixed(4)}`}, in ${ss.name}`,
        });
      }
    }
    for (const e of onEx) {
      const aq = (terms) => terms.filter((t) => t.n !== 'H2O');
      const reac = follow ? e.left : aq(e.left);
      const prod = follow ? e.right : aq(e.right);
      lines.push({
        rel: `${side(reac)} <=> ${side(prod)}`,
        k: kText(db.logKTerms('x', e.species), follow ? atOneAtm(e.logk, e.left, e.right) : e.logkC),
        note: follow ? `# here ${e.logkC.toFixed(4)}${e.folded ? `, the database's ${e.logkDb.toFixed(4)}` : ''}`
          : `# log K ${e.logkDb.toFixed(4)}`,
      });
    }
    // A surface species' relation: the database's log K, its aqueous partners'
    // coefficients folded in where the constants are conditional.
    for (const e of onSf) {
      if (e.master) continue;
      const aq = (terms) => terms.filter((t) => t.n !== 'H2O');
      const water = (terms) => terms.filter((t) => t.n === 'H2O').reduce((acc, t) => acc + t.c, 0);
      const sumLg = (terms) => aq(terms).filter((t) => !sfMasters.has(t.n) && t.n !== e.species)
        .reduce((acc, t) => acc + t.c * lgOf(t.n), 0);
      const nw = water(e.right) - water(e.left);
      const logkC = e.lk - sumLg(e.right) + sumLg(e.left) - nw * logAw;
      const reac = follow ? e.left : aq(e.left);
      const prod = follow ? e.right : aq(e.right);
      lines.push({
        rel: `${side(reac)} <=> ${side(prod)}`,
        k: kText(db.logKTerms('f', e.species), follow ? atOneAtm(e.lk, e.left, e.right) : logkC),
        note: follow ? `# here ${logkC.toFixed(4)}` : `# log K ${e.lk.toFixed(4)}`,
      });
    }
    const wrel = Math.max(0, ...lines.map((l) => l.rel.length)) + 1;
    const wk = Math.max(0, ...lines.map((l) => l.k.length)) + 3;
    for (const l of lines) out.push(`${`${l.rel},`.padEnd(wrel)} ${l.k.padEnd(wk)}${l.note}`);
    if (sit) {
      out.push('', '<SIT>');
      if (!sitPairs.length) out.push('# The database pairs none of the species written here.');
      const wn = Math.max(0, ...sitPairs.map((p) => Math.max(name.get(p.s1).length, name.get(p.s2).length))) + 2;
      for (const p of sitPairs) {
        out.push(`${name.get(p.s1).padEnd(wn)}${name.get(p.s2).padEnd(wn)}${fmtG(p.eps, 15)}`
          + `${p.eps1 ? `  eps1=${fmtG(p.eps1, 15)}` : ''}`);
      }
    }
    if (pitz) {
      // Each parameter as the database gives it: its type, species and terms, up to the last that is not zero.
      out.push('', '<PITZER>');
      if (!pzLines.length) out.push('# The database gives no parameter between the species written here.');
      const nm = (x) => name.get(x) || x;
      const wt = Math.max(0, ...pzLines.map((p) => p.type.length)) + 2;
      const wn = Math.max(0, ...pzLines.flatMap((p) => p.sp.map((x) => nm(x).length))) + 2;
      for (const p of pzLines) {
        let n = p.a.length;
        while (n > 1 && p.a[n - 1] === 0) n--;
        out.push(`${p.type.padEnd(wt)}${p.sp.map((x) => nm(x).padEnd(wn)).join('')}${p.a.slice(0, n).map((v) => String(v)).join('  ')}`);
      }
      if (db.aphi) out.push(`APHI  ${db.aphi.map((v) => String(v)).join('  ')}`);
      out.push(...pzOpts);
    }
    if (llnl) {
      // LLNL_AQUEOUS_MODEL_PARAMETERS: A, B and B-dot at each temperature, and Drummond's CO2 where a species reads it.
      out.push('', '<LLNL>');
      out.push(`TEMPERATURES  ${db.llnl.temps.map((v) => String(v)).join('  ')}`);
      out.push(`DH_A          ${db.llnl.adh.map((v) => String(v)).join('  ')}`);
      out.push(`DH_B          ${db.llnl.bdh.map((v) => String(v)).join('  ')}`);
      out.push(`BDOT          ${db.llnl.bdot.map((v) => String(v)).join('  ')}`);
      if (order.some((sp) => db.co2Gamma.has(sp))) out.push(`CO2           ${db.llnl.co2.map((v) => String(v)).join('  ')}`);
    }
    if (volumes) {
      const wv = Math.max(...volLines.map(([n]) => n.length)) + 2;
      out.push('', '<VOLUMES>', ...volLines.map(([n, v]) => `${n.padEnd(wv)}${v}`));
    }
    // Real gases: each pair's binary parameter, where PHREEQC's is not 0.
    const gasPairs = [];
    if (gases.some((g) => g.crit)) {
      for (let i = 0; i < gases.length; i++) {
        for (let j = i + 1; j < gases.length; j++) {
          const k = db.gasK(gases[i].phase, gases[j].phase);
          if (k) gasPairs.push([gases[i].name, gases[j].name, k]);
        }
      }
    }
    if (gasPairs.length) {
      out.push('', '<GAS_PAIRS>');
      const wn = Math.max(...gasPairs.map((pr) => Math.max(pr[0].length, pr[1].length))) + 2;
      for (const [a, b, k] of gasPairs) out.push(`${a.padEnd(wn)}${b.padEnd(wn)}${fmtG(k, 15)}`);
    }
    if (solids.length) {
      /*
        PHREEQC's Guggenheim parameters, a0 and a1, at the temperature it
        holds their energies a R T at: tc, the kelvin it reads less 273.15,
        where that is not 25 C. PHREEQC's own a0 is g0/RT there, which is
        what the page works out from these.
      */
      out.push('', '<SOLID_SOLUTIONS>');
      for (const ss of solids) {
        const tc = ss.tk - 273.15;
        const prm = ss.energy ? `  a0=${String(ss.energy.a0)}  a1=${String(ss.energy.a1)}`
          + `${Math.abs(ss.tk - 298.15) > 1e-9 ? `  tc=${fmtG(tc, 15)}` : ''}` : '';
        out.push(`${ss.name}  ${ss.comps.map((c) => c.name).join('  ')}${prm}`);
      }
    }
    /*
      <PHASES>: the phases the rates read the saturation of, that are no
      mineral of the model, each as the database writes its dissolution,
      its log K as a mineral's is (above).
    */
    if (kinPhaseUse.size) {
      out.push('', '<PHASES>');
      for (const [pk, lk] of kinPhaseUse) {
        const r = db.phaseReaction.get(pk);
        const c0 = r.left[0].c;
        const reac = r.left.slice(1);
        const prod = r.right;
        const aq = (terms) => terms.filter((t) => t.n !== 'H2O');
        const sumLg = (terms) => aq(terms).reduce((acc, t) => acc + t.c * lgOf(t.n), 0);
        const nw = prod.filter((t) => t.n === 'H2O').reduce((acc, t) => acc + t.c, 0)
          - reac.filter((t) => t.n === 'H2O').reduce((acc, t) => acc + t.c, 0);
        const logkC = lk - sumLg(prod) + sumLg(reac) - nw * logAw;
        const left = [{ c: c0, n: phaseName.get(pk) }, ...(follow ? reac : aq(reac))];
        out.push(`${side(left)} <=> ${side(follow ? prod : aq(prod))}, `
          + `${kText(db.logKTerms('p', pk), follow ? atOneAtm(lk, [{ c: c0, n: pk }, ...reac], prod, pk) : logkC)}`);
      }
    }
    out.push('', '<REACTIONS>');
    if (!kinetics.length) out.push('# Your kinetic reactions here, in the same species and units.');
    /*
      Each kinetic reactant's dissolution at its rate, PHREEQC's program
      above it: M is the reactant (ramp, so never below none), each line's
      names the program's variables, conditions on the water step().
    */
    for (const k of kinetics) {
      out.push(`# ${k.comp.name}: PHREEQC's RATES ${k.rate.name}, M its moles, M0 ${fmtG(k.comp.m0, 15)}`
        + `${k.comp.parms.length ? `, PARM ${k.comp.parms.join(' ')}` : ''}, a time step TIME:`);
      for (const ln of k.rate.lines) out.push(`#   ${ln}`);
      const reac = [{ c: 1, n: k.name }].concat(k.rx.filter(([, c]) => c < 0).map(([n, c]) => ({ c: -c, n })));
      const prod = k.rx.filter(([, c]) => c > 0).map(([n, c]) => ({ c, n }));
      out.push(`${side(reac)} => ${side(prod)}, r = ${k.r}${k.names.map(([n, v]) => `, ${n} = ${v}`).join('')}`);
    }
    const text = `${out.join('\n')}\n`;

    const dropped = [...molal.keys()].filter((n) => !kept.has(n));
    const top = dropped.length ? dropped.reduce((a, b) => (molal.get(b) > molal.get(a) ? b : a)) : null;
    return {
      text,
      water: w,
      names: name,
      molal,
      // PHREEQC's molar volumes of the species, where <VOLUMES> is written (VM(), cm3/mol), by PHREEQC's names.
      volumes: vmAt,
      // The minerals' and exchange species' amounts as written, by their names in the model.
      amounts: new Map(minerals.map((mn) => [mn.name, mn.amount]).concat(onEx.map((e) => [e.name, e.m]))
        .concat(gases.map((g) => [g.name, g.amount]))
        .concat(solids.flatMap((ss) => ss.comps.map((c) => [c.name, c.amount])))
        .concat(onSf.map((e) => [e.name, e.m])).concat(potentials.map((pp) => [pp.name, pp.a]))
        .concat(kinetics.map((k) => [k.name, k.amount]))),
      report: {
        species: order.length, equilibria: eqs.length, temperature: tc, ionicStrength: w.mu,
        // The relations written with the database's dH or analytic expression: their log K go with TEMPERATURE.
        withTemperature: lines.filter((l) => /^analytic = |, dH = /.test(l.k)).length, relations: lines.length,
        pH: w.pH, chargeBalance: w.cb,
        dropped: dropped.length, droppedTop: top, droppedTopValue: top ? molal.get(top) : null,
        pulled: pulled.size, redox: [...redox].sort(), unknown: [...unknown].sort(), skipped, renamed,
        // The electron, when the couples are tied to it: its pe here, and the species tied.
        electron: eUsed ? { name: 'e-', pe: w.pe, tied: tied.map((e) => name.get(e.species) || e.species),
          minerals: minerals.filter((mn) => withE(mn.reac) || withE(mn.prod)).map((mn) => mn.name),
          spread: outOfEq ? peSpread : null,
          atNone: [...atNone].map((sp) => name.get(sp) || sp),
          // PHREEQC's next step, where the input ended on a water as given: the pe it was given, and the one it settles at.
          settled } : null,
        activity: follow ? { kind: sit ? 'sit' : pitz ? 'pitzer' : llnl ? 'llnl' : 'debye-huckel', temperature: tc, unsupported,
          pitzer: pitz ? pzLines.length : 0,
          sitPairs: sit ? sitPairs.length : 0 } : null,
        // The water's pressure, and the molar volumes written for each log K at it.
        pressure: { atm, vapour: atVapour, volumes: volumes ? volLines.length : 0 },
        minerals: minerals.map((mn) => ({ phase: mn.phase, as: mn.name, amount: mn.amount, si: mn.target,
          alt: mn.alt ? mn.alt.formula : null, only: mn.only, forced: mn.forced })),
        phasesSkipped,
        // An exchanger whose sites go with a phase or a kinetic reactant in PHREEQC: carried so (per, sites= per=), or
        // held here at what PHREEQC loaded at the start (linked), and why.
        exchange: onEx.length ? { exchangers: exUsed.map((sp) => exName.get(sp)),
          per: onEx.filter((e) => exPer.has(e.species)).map((e) => {
            const p = exPer.get(e.species);
            return { exchanger: exName.get(e.master), species: e.species, as: e.name, ratio: p.ratio, sites: p.sites,
              mineral: p.carrier.name, kind: p.kind };
          }),
          linked: exHeld,
          species: onEx.map((e) => ({ species: e.species, as: e.name, amount: e.m, folded: e.folded })) } : null,
        exchangeSkipped: exSkipped,
        // The column of the input's TRANSPORT (or ADVECTION), where it has one (columnSetup).
        transport: colReport,
        surface: onSf.length ? { sites: onSf.filter((e) => e.master).map((e) => e.name),
          // Sites so many per mole of a mineral (sites= per=): the site, the number and the mineral.
          per: onSf.filter((e) => e.master && perInfo.has(e.species)).map((e) => ({ site: e.name, ...perInfo.get(e.species) })),
          species: onSf.map((e) => ({ species: e.species, as: e.name, amount: e.m })),
          potentials: potentials.map((pp) => ({ name: pp.name, surface: pp.surface, psi: pp.psi, area: pp.area,
            grams: pp.grams, phase: pp.phase, cd: pp.cd, plane: pp.plane, cap: pp.cap })) } : null,
        surfaceSkipped: sfSkipped,
        gas: gases.length ? { ...gasFixed, species: gases.map((g) => ({ phase: g.phase, as: g.name, amount: g.amount,
          pressure: g.pressure })) } : null,
        gasSkipped,
        solids: solids.map((ss) => ({ name: ss.name, members: ss.comps.map((c) => ({ phase: c.phase, as: c.name,
          amount: c.amount })), binary: ss.energy ? { a0: ss.energy.a0, a1: ss.energy.a1, tk: ss.tk } : null })),
        solidsSkipped,
        // KINETICS: each reactant as written, its rate's program and its amount; the steps, s, and the run's end.
        kinetics: kinetics.length ? { reactants: kinetics.map((k) => ({ name: k.comp.name, as: k.name, rate: k.rate.name,
          amount: k.amount, m0: k.comp.m0, parms: k.comp.parms })), phases: [...kinPhaseUse.keys()],
        steps: kinBlock.steps, tend: kinTime, trace: traced ? 1e-20 : 0 } : null,
        kineticsSkipped: kinSkipped,
      },
    };
  }

  /* ======================================================================
     A run back out
     ====================================================================== */

  const SKIP_ALWAYS = new Map([
    ['H2O', 'water itself'],
    ['e-', "rtm.html's e- is the hydrated electron, not PHREEQC's"],
  ]);

  /** The species a model text makes PHREEQC's electron (`electron` on its line), or null. */
  function modelElectron(text) {
    let section = null;
    for (const raw of String(text || '').split(/\r\n|\r|\n/)) {
      const line = raw.split('#', 1)[0].trim();
      if (!line) continue;
      const m = /^<\s*([A-Za-z_]+)(?:\s[^>]*)?>$/.exec(line);
      if (m) { section = m[1].toUpperCase(); continue; }
      if (section !== 'SPECIES') continue;
      const parts = line.split(/[\s,;]+/).filter(Boolean);
      if (parts.slice(1).some((p) => /^electron$/i.test(p))) return parts[0];
    }
    return null;
  }

  /**
   * The surfaces' potentials a model text has (`potential` on a line), by
   * the surface each is of -- its name up to the underscore -- with its name,
   * area and grams.
   */
  function modelPotentials(text) {
    const out = new Map();
    let section = null;
    for (const raw of String(text || '').split(/\r\n|\r|\n/)) {
      const line = raw.split('#', 1)[0].trim();
      if (!line) continue;
      const m = /^<\s*([A-Za-z_]+)(?:\s[^>]*)?>$/.exec(line);
      if (m) { section = m[1].toUpperCase(); continue; }
      if (section !== 'SPECIES') continue;
      const parts = line.split(/[\s,;]+/).filter(Boolean);
      if (!parts.slice(1).some((p) => /^potential$/i.test(p))) continue;
      const num = (key) => {
        const kv = parts.find((p) => new RegExp(`^${key}=`, 'i').test(p));
        return kv ? Number(kv.split('=')[1]) : NaN;
      };
      const cut = parts[0].indexOf('_');
      // per=: the area to each mole of a mineral of the model, whose amount in a water then takes the grams' place.
      const per = (parts.find((p) => /^per=/i.test(p)) || '').split('=')[1] || null;
      if (cut <= 0) continue;
      const sn = parts[0].slice(0, cut);
      // CD-MUSIC: planes 1 and 2, Hfo_psib and Hfo_psid, beside the first with its capacitances c0 and c1.
      const plane = /_psib$/.test(parts[0]) ? 1 : /_psid$/.test(parts[0]) ? 2 : 0;
      const had = out.get(sn) || { planes: [null, null, null] };
      if (plane) {
        had.planes[plane] = parts[0];
        out.set(sn, had);
        continue;
      }
      out.set(sn, { ...had, name: parts[0], area: num('area'), grams: num('grams'), per, c0: num('c0'), c1: num('c1'),
        planes: [parts[0], had.planes[1], had.planes[2]] });
    }
    return out;
  }

  /**
   * A model's gas phase: its gases, and how the phase is held -- GAS_VOLUME,
   * litres to each kg of water, or GAS_PRESSURE, atm -- at TEMPERATURE. Null
   * where the model has no gas.
   */
  function modelGas(text) {
    const names = new Set();
    const set = {};
    let section = null;
    for (const raw of String(text || '').split(/\r\n|\r|\n/)) {
      const line = raw.split('#', 1)[0].trim();
      if (!line) continue;
      const m = /^<\s*([A-Za-z_]+)(?:\s[^>]*)?>$/.exec(line);
      if (m) { section = m[1].toUpperCase(); continue; }
      if (section === 'SETTINGS') {
        const kv = /^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(\S+)/.exec(line);
        if (kv) set[kv[1].toUpperCase()] = Number(kv[2]);
      } else if (section === 'SPECIES') {
        const parts = line.split(/[\s,;]+/).filter(Boolean);
        if (parts.slice(1).some((x) => /^gas$/i.test(x))) names.add(parts[0]);
      }
    }
    if (!names.size) return null;
    const volume = set.GAS_VOLUME > 0 ? set.GAS_VOLUME : 0;
    return { names, fixed: volume ? 'volume' : 'pressure', volume, pressure: set.GAS_PRESSURE > 0 ? set.GAS_PRESSURE : 0,
      temperature: Number.isFinite(set.TEMPERATURE) ? set.TEMPERATURE : 25 };
  }

  /** The <EQUILIBRIUM> lines of a model text as {rel, reac, prod}. */
  function modelEquilibria(text) {
    const out = [];
    let section = null;
    for (const raw of String(text || '').split(/\r\n|\r|\n/)) {
      const line = raw.split('#', 1)[0].trim();
      if (!line) continue;
      const m = /^<\s*([A-Za-z_]+)(?:\s[^>]*)?>$/.exec(line);
      if (m) { section = m[1].toUpperCase(); continue; }
      if (section !== 'EQUILIBRIUM' || !line.includes('<=>')) continue;
      const rel = line.split(',', 1)[0];
      const [lhs, rhs] = rel.split('<=>');
      const side = (s) => s.trim().split(' + ').map((p) => p.trim()).filter(Boolean).map((p) => {
        const mm = /^([0-9.]+(?:[eE][-+]?[0-9]+)?)\s+(\S+)$/.exec(p);
        return mm ? { c: Number(mm[1]), n: mm[2] } : { c: 1, n: p };
      });
      out.push({ rel: rel.trim(), reac: side(lhs), prod: side(rhs) });
    }
    return out;
  }

  /**
   * Every stored water of a run, seen by PHREEQC.
   *
   * @param {object} o
   *   engine, database {name, text}
   *   run         {t, states, n, width, model: {species, cells, stride, fracture}}
   *               as rtm-worker.js posts it
   *   modelText   the model, for its <EQUILIBRIUM>
   *   water       {name, text}: the water the model started from -- its
   *               temperature, and any element the model does not carry;
   *               one PHREEQC refuses is reported (report.waterError) and
   *               left out. Without a water or `temp`, the temperature is the
   *               one at the top of a model written from a water, else 25 C.
   *   map         {rtmName: phreeqcName}; skip [names]
   *   scale       model concentration unit -> mol/kgw (1)
   *   times       at most this many stored times per cell (100; 0 for all)
   *   cells       [fracture cell numbers] (all); rock: read the layers too
   *   temp        C, overriding the water's (25 without either) and the run's
   *               (run.temps: each stored point's cells in C, where the model's
   *               TEMPERATURE goes with the cell or the time)
   *   phases      [names] to report, else any within siFloor (-3) of saturation
   *   unit        the model's time unit, for the CSV
   *   onProgress  (done, total) as PHREEQC works through the waters
   */
  function viewRun(o) {
    const db = readDatabase(o.database.text, o.water && o.water.text);
    const run = o.run;
    const model = run.model;
    const ns = model.species.length;
    const stride = model.stride || 1;
    const nfr = model.fracture || Math.ceil(model.cells / stride);
    const scale = o.scale || 1;
    const skip = new Set(o.skip || []);
    const map = o.map || {};

    // --- which species PHREEQC knows, and what each counts as -------------
    const back = new Map();
    for (const s of db.reaction.keys()) if (!back.has(rtmName(s))) back.set(rtmName(s), s);
    const mapped = new Map();         // rtm name -> {p, contrib: Map}
    const skipped = new Map();
    const unmapped = [];
    // A mineral of the model is a phase of the database: not in the water,
    // and PHREEQC says how far the water is from its saturation.
    const phaseBack = new Map(db.phases.map((ph) => [rtmName(ph), ph]));
    const minerals = [];
    // A species on an exchanger is not in the water either: the exchanger is
    // looked at as PHREEQC would load it from each water (see below).
    const exBack = new Map([...db.exReaction.keys()].map((sp) => [rtmName(sp), sp]));
    const exMasterOf = new Map([...db.exMaster].map(([lb, sp]) => [sp, lb]));
    const exMasterBack = new Map([...db.exMaster.values()].map((sp) => [rtmName(sp), sp]));
    const onExchanger = [];
    // A species on a surface, likewise: the surface is looked at as PHREEQC
    // would load it from each water, with the sites the run has there.
    const sfMasterSet = new Set(db.sfMaster.values());
    const sfBack = new Map([...db.sfReaction.keys(), ...sfMasterSet].map((sp) => [rtmName(sp), sp]));
    const onSurface = [];
    // And each surface's potential, with the area and grams PHREEQC's double layer is given.
    const potentials = modelPotentials(o.modelText);
    const potNames = new Set([...potentials.values()].flatMap((pp) => [pp.name, ...pp.planes]).filter(Boolean));
    // The model's electron is PHREEQC's: its activity is the pe each water is given.
    const electron = modelElectron(o.modelText);
    const eIndex = electron ? model.species.indexOf(electron) : -1;
    // A gas of the model is a phase of the database too: its pressure against the one each water holds it at.
    const gasModel = modelGas(o.modelText);
    const gasSpecies = [];
    model.species.forEach((n) => {
      let p;
      if (skip.has(n)) { skipped.set(n, 'asked'); return; }
      if (n === electron) { skipped.set(n, "the electron: its activity is the run's pe, which each water is given"); return; }
      if (potNames.has(n)) { skipped.set(n, "a surface's potential: no amount, and looked at with its surface"); return; }
      if (map[n]) {
        p = map[n];
        if (!db.reaction.has(p) && db.masterLabel(p) === null) {
          throw new Error(`${n} is to be counted as ${p}, which the database does not have`);
        }
      } else if (SKIP_ALWAYS.has(n)) { skipped.set(n, SKIP_ALWAYS.get(n)); return; }
      else if (db.reaction.has(n)) p = n;
      else if (back.has(n)) p = back.get(n);
      else if (gasModel && gasModel.names.has(n) && phaseBack.has(n)) {
        skipped.set(n, 'a gas: not in the water, and its partial pressure is compared with the one each water holds it at');
        gasSpecies.push({ name: n, phase: phaseBack.get(n) });
        return;
      } else if (phaseBack.has(n)) {
        skipped.set(n, 'a mineral: not in the water, and its saturation index is among the phases');
        minerals.push({ name: n, phase: phaseBack.get(n) });
        return;
      } else if (exBack.has(n)) {
        skipped.set(n, 'on an exchanger: not in the water, and looked at with its exchanger');
        onExchanger.push({ name: n, p: exBack.get(n) });
        return;
      } else if (exMasterBack.has(n)) {
        skipped.set(n, 'an exchanger: no amount, its activity solved for');
        return;
      } else if (sfBack.has(n)) {
        skipped.set(n, 'on a surface: not in the water, and looked at with its surface');
        onSurface.push({ name: n, p: sfBack.get(n) });
        return;
      } else { unmapped.push(n); return; }
      if (p === 'H+') { mapped.set(n, { p, contrib: new Map() }); return; }
      let contrib;
      try {
        contrib = new Map([...db.expand(p)].map(([k, v]) => [normLabel(k), v]));
      } catch (e) {
        skipped.set(n, `could not be written in master species (${e.message})`);
        return;
      }
      if (contrib.has('e-')) { skipped.set(n, 'a redox species the database does not tie to a valence state'); return; }
      mapped.set(n, { p, contrib });
    });
    const hname = [...mapped].find(([, v]) => v.p === 'H+');
    const hIndex = hname ? model.species.indexOf(hname[0]) : -1;

    // --- the water the model started from ----------------------------------
    // Its temperature, and any element the model does not carry. A water
    // PHREEQC will not take is said, and the run is looked at without it.
    const background = new Map();
    let temp = o.temp != null ? o.temp : null;
    let tempFrom = temp !== null ? 'given' : null;
    let waterError = null;
    if (o.water && o.water.text) {
      let wrows = [];
      try {
        wrows = runRows(o.engine, `${punchBlock()}${o.water.text}\nEND\n`);
      } catch (e) {
        waterError = String(e.message || e).trim().split('\n')[0];
      }
      if (!waterError && !wrows.length) waterError = 'PHREEQC calculated no water from it';
      if (!waterError) {
        const w = wrows[wrows.length - 1];
        if (temp === null) { temp = w.tc; tempFrom = 'the water'; }
        const carried = new Set();
        for (const { contrib } of mapped.values()) for (const k of contrib.keys()) carried.add(elementOf(k));
        for (const [label, v] of w.elements) {
          const el = elementOf(label);
          if (['H', 'O', 'E'].includes(el) || carried.has(el) || !(v > 0)) continue;
          const states = [...w.elements.keys()].filter((lb) => elementOf(lb) === el && lb.includes('('));
          if (label.includes('(') === (states.length > 0)) background.set(label, v);
        }
      }
    }
    // A model written from a water says at what temperature, at its top.
    if (temp === null) {
      const m = /^# PHREEQC: (-?[0-9.]+(?:[eE][-+]?[0-9]+)?) C,/m.exec(String(o.modelText || ''));
      if (m) { temp = Number(m[1]); tempFrom = 'the model text'; }
    }
    if (temp === null) { temp = 25; tempFrom = 'none'; }
    // A run whose TEMPERATURE goes with the cell or the time: each water at its own, unless one is given.
    const temps = o.temp == null && run.temps && run.temps.length === run.n * model.cells ? run.temps : null;
    if (temps) tempFrom = 'the run';

    // --- the waters: cells x times ------------------------------------------
    const nT = run.n;
    let idx = [...Array(nT).keys()];
    const times = o.times != null ? o.times : 100;
    if (times && nT > times) {
      const set = new Set();
      for (let i = 0; i < times; i++) set.add(Math.round((i * (nT - 1)) / (times - 1)));
      idx = [...set].sort((a, b) => a - b);
    }
    const wantCells = o.cells ? new Set(o.cells.map(Number)) : null;
    const groups = [];
    for (let c = 0; c < model.cells; c++) {
      const i = Math.floor(c / stride);
      const j = c % stride;
      if (i >= nfr) continue;                       // past a semi-infinite end
      if (j > 0 && !o.rock) continue;
      if (wantCells && !wantCells.has(i)) continue;
      groups.push({ state: c, cell: i, layer: j });
    }
    if (!groups.length) throw new Error('No cells to read.');
    const value = (c, si, k) => run.states[k * run.width + c * ns + si];
    const rows = [];
    for (const g of groups) {
      for (const k of idx) {
        const totals = new Map(background);
        for (const [n, { contrib }] of mapped) {
          const c = Math.max(value(g.state, model.species.indexOf(n), k), 0) * scale;
          for (const [lb, v] of contrib) totals.set(lb, (totals.get(lb) || 0) + v * c);
        }
        const h = hIndex >= 0 ? Math.max(value(g.state, hIndex, k), 0) * scale : null;
        const ae = eIndex >= 0 ? value(g.state, eIndex, k) : 0;
        rows.push({ t: run.t[k], cell: g.cell, layer: g.layer, totals, H: h, pH: h > 0 ? -Math.log10(h) : null,
          pe: ae > 0 ? -Math.log10(ae) : null, state: g.state, k, tc: temps ? temps[k * model.cells + g.state] : temp });
      }
    }

    // --- PHREEQC, with the pH walked onto the run's [H+] -------------------
    // totals: the element totals to give PHREEQC, by valence state unless
    // `together` says to give an element's valence states as one.
    /*
      The model's water's pressure, PRESSURE, which PHREEQC's waters are put
      at; with <VOLUMES> each species' molar volume as well, for the log K at
      that pressure on both sides (pressurePart).
    */
    const mText = String(o.modelText || '');
    const pGiven = (() => { const m = /^[ \t]*PRESSURE[ \t]*=[ \t]*(\S+)/m.exec(mText); return m ? Number(m[1]) : 1; })();
    const withVol = /^[ \t]*<VOLUMES>[ \t]*$/m.test(mText);
    const solution = (k, r, together) => {
      const lines = [`SOLUTION ${k}`, `  temp ${fmtG(r.tc, 12)}`, '  units mol/kgw',
        ...(pGiven > 0 && pGiven !== 1 ? [`  pressure ${fmtG(pGiven, 15)}`] : []),
        `  pe ${r.pe !== null && r.pe !== undefined ? r.pe.toFixed(12) : '4'}`,
        r.pH !== null ? `  pH ${r.pH.toFixed(12)}` : '  pH 7 charge'];
      const totals = new Map();
      for (const [lb, v] of r.totals) {
        const el = elementOf(lb);
        const key = together && together.has(el) ? el : lb;
        totals.set(key, (totals.get(key) || 0) + v);
      }
      for (const [lb, v] of [...totals].sort((a, b) => (a[0] < b[0] ? -1 : 1))) {
        if (v > 0) lines.push(`  ${lb} ${fmtG(v, 15)}`);
      }
      return `${lines.join('\n')}\n`;
    };
    // With <VOLUMES>, each mapped species' molar volume, VM(), a column each, and the water's.
    const vmNames = withVol ? [...new Set([...mapped.values()].map((v) => v.p))].concat('H2O') : [];
    const runSome = (sub) => runRows(o.engine,
      `${punchBlock(vmNames.map((n) => `VM("${n}")`))}${sub.map((r, k) => solution(k + 1, r)).join('')}END\n`);
    const CHUNK = 400;
    let done = 0;
    for (let start = 0; start < rows.length; start += CHUNK) {
      const sub = rows.slice(start, start + CHUNK);
      for (let pass = 0; pass < 8; pass++) {
        let out;
        try {
          out = runSome(sub);
        } catch (e) {                          // one bad water stops the whole run: find it
          out = sub.map((r) => {
            try {
              return runSome([r])[0] || null;
            } catch (e2) {
              const msg = String(e2.message || e2).trim().split('\n');
              r.error = msg[msg.length - 1].slice(0, 200);
              return null;
            }
          });
        }
        let worst = 0;
        sub.forEach((r, k) => {
          r.pq = out[k] || null;
          if (r.pq && r.H) {
            const d = Math.log10(r.pq.mH / r.H);
            r.pH += d;
            worst = Math.max(worst, Math.abs(d));
          }
        });
        if (!(worst >= 1e-9)) break;
      }
      done += sub.length;
      if (o.onProgress) o.onProgress(done, rows.length);
    }
    const good = rows.filter((r) => r.pq);
    if (!good.length) {
      throw new Error(`PHREEQC could not calculate any of the waters: ${rows[0].error || ''}`);
    }

    // --- the model's exchangers: the run's fractions against PHREEQC's ------
    // Each water given to PHREEQC with an exchanger of the run's capacity
    // there, loaded from it (EXCHANGE -equilibrate, the water left as it is):
    // how far the fraction of each species the run has on it is from the
    // fraction PHREEQC puts there.
    let exchange = null;
    const exOf = [];
    for (const e of onExchanger) {
      const r = db.exReaction.get(e.p);
      const t = r.left.find((x) => exMasterOf.has(x.n));
      if (t) exOf.push({ ...e, si: model.species.indexOf(e.name), label: exMasterOf.get(t.n), n: t.c });
    }
    if (exOf.length) {
      const capOf = (r) => {
        const cap = new Map();
        for (const e of exOf) cap.set(e.label, (cap.get(e.label) || 0) + e.n * Math.max(value(r.state, e.si, r.k), 0) * scale);
        return cap;
      };
      let worst = { by: 0, at: null, species: null };
      let error = null;
      for (let start = 0; start < good.length && !error; start += CHUNK) {
        const sub = good.slice(start, start + CHUNK);
        const caps = sub.map(capOf);
        const blocks = sub.map((r, k) => {
          const lines = [...caps[k]].filter(([, v]) => v > 0).map(([lb, v]) => ` ${lb} ${fmtG(v, 15)}`);
          return lines.length ? `EXCHANGE ${k + 1}\n -equilibrate ${k + 1}\n${lines.join('\n')}\n` : '';
        }).join('');
        let out;
        try {
          out = runRows(o.engine, `${punchBlock()}${sub.map((r, k) => solution(k + 1, r)).join('')}END\n${blocks}END\n`);
        } catch (e) {
          error = String(e.message || e).trim().split('\n')[0];
          break;
        }
        const byK = new Map(out.filter((q) => q.state === 'i_exch').map((q) => [Number(q.soln), q]));
        sub.forEach((r, k) => {
          const q = byK.get(k + 1);
          if (!q) return;
          for (const e of exOf) {
            const cap = caps[k].get(e.label);
            if (!(cap > 0)) continue;
            const ours = (e.n * Math.max(value(r.state, e.si, r.k), 0) * scale) / cap;
            const theirs = q.exchange.has(e.p) ? (e.n * q.exchange.get(e.p).m) / cap : 0;
            if (Math.abs(ours - theirs) > Math.abs(worst.by)) worst = { by: ours - theirs, at: r, species: e.name };
          }
        });
      }
      exchange = {
        exchangers: [...new Set(exOf.map((e) => e.label))],
        species: exOf.map((e) => e.name),
        gap: worst.by, worst: worst.species,
        t: worst.at ? worst.at.t : null, cell: worst.at ? worst.at.cell : null,
        error,
      };
    }

    // --- the model's surfaces: the run's fractions against PHREEQC's --------
    // Each water given to PHREEQC with the sites the run has there, each type
    // its own total, loaded from it without electrostatics (SURFACE
    // -equilibrate -no_edl, the water left as it is): how far the fraction of
    // its sites each species the run has on a surface takes is from the
    // fraction PHREEQC puts there.
    let surface = null;
    const sfOf = [];
    for (const e of onSurface) {
      const si = model.species.indexOf(e.name);
      if (sfMasterSet.has(e.p)) { sfOf.push({ ...e, si, site: e.p, n: 1 }); continue; }
      const r = db.sfReaction.get(e.p);
      const t = r.left.find((x) => sfMasterSet.has(x.n));
      if (t) sfOf.push({ ...e, si, site: t.n, n: t.c });
    }
    if (sfOf.length) {
      const sitesOf = (r) => {
        const sites = new Map();
        for (const e of sfOf) sites.set(e.site, (sites.get(e.site) || 0) + e.n * Math.max(value(r.state, e.si, r.k), 0) * scale);
        return sites;
      };
      /*
        With potentials, PHREEQC's double layer: each surface's area and
        grams on the first of its sites' lines; and each potential the run
        has, against PHREEQC's (EDL "psi"), in volts.
      */
      const surfaceOf = (site) => site.slice(0, Math.max(site.indexOf('_'), 0));
      const surfaces = [...new Set(sfOf.map((e) => surfaceOf(e.site)))];
      const layered = surfaces.filter((sn) => potentials.has(sn));
      let error = null;
      if (layered.length && layered.length < surfaces.length) {
        error = `${surfaces.filter((sn) => !potentials.has(sn)).join(', ')} has no potential and ${layered.join(', ')} has: `
          + 'PHREEQC loads the surfaces of one water together, all with a double layer or all without';
      }
      // Each potential the run has against PHREEQC's EDL: psi, and on a CD-MUSIC surface psi1 and psi2 too.
      const cdOf = (pp) => Number.isFinite(pp.c0) && Number.isFinite(pp.c1) && pp.planes[1] && pp.planes[2];
      const potAt = layered.flatMap((sn) => {
        const pp = potentials.get(sn);
        return (cdOf(pp) ? [0, 1, 2] : [0]).map((plane) => ({ sn, plane, si: model.species.indexOf(pp.planes[plane]), ...pp,
          name: pp.planes[plane], what: ['psi', 'psi1', 'psi2'][plane] }));
      });
      let worstPsi = { by: 0, at: null, name: null };
      let worst = { by: 0, at: null, species: null };
      for (let start = 0; start < good.length && !error; start += CHUNK) {
        const sub = good.slice(start, start + CHUNK);
        const sites = sub.map(sitesOf);
        const blocks = sub.map((r, k) => {
          const first = new Set();
          const lines = [...sites[k]].filter(([, v]) => v > 0).map(([sp, v]) => {
            const sn = surfaceOf(sp);
            const pp = potentials.get(sn);
            if (!layered.length || first.has(sn) || !pp) return ` ${sp} ${fmtG(v, 15)}`;
            first.add(sn);
            const grams = pp.per ? Math.max(value(r.state, model.species.indexOf(pp.per), r.k), 0) * scale : pp.grams;
            return ` ${sp} ${fmtG(v, 15)} ${fmtG(pp.area, 15)} ${fmtG(grams, 15)}`
              + (cdOf(pp) ? `\n -capacitances ${fmtG(pp.c0, 15)} ${fmtG(pp.c1, 15)}` : '');
          });
          const cdm = layered.some((sn) => cdOf(potentials.get(sn)));
          return lines.length ? `SURFACE ${k + 1}\n -equilibrate ${k + 1}\n${layered.length ? (cdm ? ' -cd_music\n' : '') : ' -no_edl\n'}`
            + `${lines.join('\n')}\n` : '';
        }).join('');
        let out;
        try {
          out = runRows(o.engine, `${punchBlock(potAt.map((pp) => `EDL("${pp.what}", "${pp.sn}")`))}`
            + `${sub.map((r, k) => solution(k + 1, r)).join('')}END\n${blocks}END\n`);
        } catch (e) {
          error = String(e.message || e).trim().split('\n')[0];
          break;
        }
        const byK = new Map(out.filter((q) => q.state === 'i_surf').map((q) => [Number(q.soln), q]));
        sub.forEach((r, k) => {
          const q = byK.get(k + 1);
          if (!q) return;
          for (const e of sfOf) {
            const total = sites[k].get(e.site);
            if (!(total > 0)) continue;
            const ours = (e.n * Math.max(value(r.state, e.si, r.k), 0) * scale) / total;
            const theirs = q.surface && q.surface.has(e.p) ? (e.n * q.surface.get(e.p).m) / total : 0;
            if (Math.abs(ours - theirs) > Math.abs(worst.by)) worst = { by: ours - theirs, at: r, species: e.name };
          }
          // The potentials: the run's, -RT ln(a)/F, against PHREEQC's.
          potAt.forEach((pp, i) => {
            const a = pp.si >= 0 ? value(r.state, pp.si, r.k) : NaN;
            const theirs = Number(q.x[i]);
            if (!(a > 0) || !Number.isFinite(theirs)) return;
            const ours = -Math.log(a) * GAS_R * (r.tc + 273.15) / FARADAY;
            if (Math.abs(ours - theirs) > Math.abs(worstPsi.by)) worstPsi = { by: ours - theirs, at: r, name: pp.name };
          });
        });
      }
      surface = {
        sites: [...new Set(sfOf.map((e) => e.site))].map((sp) => rtmName(sp)),
        species: sfOf.map((e) => e.name),
        gap: worst.by, worst: worst.species,
        t: worst.at ? worst.at.t : null, cell: worst.at ? worst.at.cell : null,
        // With a double layer, or by CD-MUSIC: the potentials, and how far the run's are from PHREEQC's, in volts.
        potentials: potAt.map((pp) => pp.name),
        cd: potAt.some((pp) => pp.plane > 0),
        psiGap: potAt.length ? { by: worstPsi.by, name: worstPsi.name, t: worstPsi.at ? worstPsi.at.t : null,
          cell: worstPsi.at ? worstPsi.at.cell : null } : null,
        error,
      };
    }

    // --- the model's redox couples: the run's valence states against PHREEQC's ----
    // Each water given to PHREEQC at the run's pe with each element of
    // several valence states as one total, which PHREEQC shares out between
    // them as that pe has it: how far each valence state the run has is from
    // PHREEQC's, as a part of its element.
    let redox = null;
    if (eIndex >= 0) {
      const states = new Map();
      for (const { contrib } of mapped.values()) {
        for (const lb of contrib.keys()) {
          const el = elementOf(lb);
          if (['H', 'O'].includes(el) || !lb.includes('(')) continue;
          if (!states.has(el)) states.set(el, new Set());
          states.get(el).add(lb);
        }
      }
      const together = new Set([...states].filter(([, set]) => set.size > 1).map(([el]) => el));
      const pes = good.filter((r) => r.pe !== null).map((r) => r.pe);
      let worst = { by: 0, at: null, label: null };
      let error = null;
      if (together.size) {
        for (let start = 0; start < good.length && !error; start += CHUNK) {
          const sub = good.slice(start, start + CHUNK);
          let out;
          try {
            out = runRows(o.engine, `${punchBlock()}${sub.map((r, k) => solution(k + 1, r, together)).join('')}END\n`);
          } catch (e) {
            error = String(e.message || e).trim().split('\n')[0];
            break;
          }
          sub.forEach((r, k) => {
            const q = out[k];
            if (!q) return;
            for (const el of together) {
              let whole = 0;
              for (const [lb, v] of r.totals) if (elementOf(lb) === el) whole += v;
              if (!(whole > 0)) continue;
              for (const lb of states.get(el)) {
                const ours = (r.totals.get(lb) || 0) / whole;
                const theirs = (q.elements.get(lb) || 0) / whole;
                if (Math.abs(ours - theirs) > Math.abs(worst.by)) worst = { by: ours - theirs, at: r, label: lb };
              }
            }
          });
        }
      }
      redox = {
        electron,
        pe: pes.length ? [Math.min(...pes), Math.max(...pes)] : null,
        elements: [...together].sort(),
        gap: worst.by, worst: worst.label,
        t: worst.at ? worst.at.t : null, cell: worst.at ? worst.at.cell : null,
        error,
      };
    }

    // --- phases worth a column ----------------------------------------------
    let phases;
    if (o.phases && o.phases.length) phases = o.phases.slice();
    else {
      const best = new Map();
      for (const r of good) {
        for (const [p, si] of r.pq.phases) if (si > -990) best.set(p, Math.max(best.has(p) ? best.get(p) : -1e9, si));
      }
      const floor = o.siFloor != null ? o.siFloor : -3;
      phases = [...best].sort((a, b) => b[1] - a[1]).filter(([, si]) => si >= floor).map(([p]) => p);
    }
    // The model's own minerals always: what it holds, PHREEQC can look at; and its gases.
    for (const mn of minerals) if (!phases.includes(mn.phase)) phases.push(mn.phase);
    for (const g of gasSpecies) if (!phases.includes(g.phase)) phases.push(g.phase);

    /*
      --- the model's gases: each one's partial pressure in the run -- n R T/V
      in a fixed volume, its share of the bubble times the total at a fixed
      pressure -- against the pressure the water holds it at, 10^SI, where
      the run has any of it. Held, they are the same.
    */
    let gas = null;
    if (gasSpecies.length) {
      const at = gasSpecies.map((g) => model.species.indexOf(g.name));
      // Real gases: the model's own Peng and Robinson, phi times the partial pressure, its fugacity.
      const RtmG = (typeof self !== 'undefined' && self.RtmModel) || (typeof globalThis !== 'undefined' && globalThis.RtmModel) || null;
      let real = null;
      if (RtmG && /\bTc\s*=/i.test(String(o.modelText || ''))) {
        try {
          const own = RtmG.compile(o.modelText);
          if (own.act && own.act.gas && own.act.gas.pr) real = own.act.gas;
        } catch (e) { real = null; }
      }
      let worst = { by: 0, at: null, name: '' };
      let compared = 0;
      for (const r of good) {
        const amt = at.map((si) => value(r.state, si, r.k));
        const N = amt.reduce((a, v) => a + Math.max(v, 0), 0);
        // R T at this water's temperature, the run's where it has one, and Peng and Robinson's terms there.
        const RT = 0.0820597 * ((temps ? r.tc : gasModel.temperature) + 273.15);
        if (real && RtmG.prAt) RtmG.prAt(real.pr, (temps ? r.tc : gasModel.temperature) + 273.15);
        let lnPhi = null;
        let Ptot = gasModel.fixed === 'volume' ? 0 : gasModel.pressure;
        if (real && N > 0) {
          const x = new Float64Array(real.list.length);
          gasSpecies.forEach((g, i) => { const q = real.qOf[model.species.indexOf(g.name)]; if (q >= 0) x[q] = Math.max(amt[i], 0) / N; });
          const st = RtmG.prState(real.pr, x, real.fixed === 'pressure' ? real.pressure : 0, real.fixed === 'volume' ? real.volume / N : 0);
          Ptot = st.P;
          lnPhi = Float64Array.from(real.pr.lnPhi);
        }
        gasSpecies.forEach((g, i) => {
          if (!(amt[i] > 0) || !r.pq.phases.has(g.phase)) return;
          const si = r.pq.phases.get(g.phase);
          if (!(si > -990)) return;
          let pr;
          if (lnPhi) pr = Math.exp(lnPhi[real.qOf[model.species.indexOf(g.name)]]) * (amt[i] / N) * Ptot;
          else pr = gasModel.fixed === 'volume' ? amt[i] * RT / gasModel.volume : (amt[i] / N) * gasModel.pressure;
          if (!(pr > 0)) return;
          const by = Math.log10(pr) - si;
          compared++;
          if (Math.abs(by) > Math.abs(worst.by)) worst = { by, at: r, name: g.name };
        });
      }
      gas = { fixed: gasModel.fixed, volume: gasModel.volume, pressure: gasModel.pressure,
        species: gasSpecies.map((g) => g.name), compared, gap: worst.by, worst: worst.name,
        t: worst.at ? worst.at.t : null, cell: worst.at ? worst.at.cell : null };
    }

    /*
      --- the model's solid solutions: where the run has one, each member's
      saturation index PHREEQC finds in the water against log10 of its
      activity in the run's solid, x lambda, lambda the run's at the water's
      temperature -- or inside a miscibility gap the gap's edge's, as the run
      holds it. Held, they are the same. Its members are not looked at as
      pure minerals below.
    */
    let solidCheck = null;
    const RtmS = (typeof self !== 'undefined' && self.RtmModel) || (typeof globalThis !== 'undefined' && globalThis.RtmModel) || null;
    if (RtmS && /<\s*SOLID_SOLUTIONS\s*>/i.test(String(o.modelText || ''))) {
      let own = null;
      try { own = RtmS.compile(o.modelText); } catch (e) { own = null; }
      const defs = own ? [...new Set(own.equilibria.map((eq) => eq.grp).filter((d) => d && d.kind === 'ss'))] : [];
      solidCheck = defs.map((def) => {
        const names = def.members.map((k) => own.speciesNames[k]);
        const at = names.map((n) => model.species.indexOf(n));
        const phase = names.map((n) => (minerals.find((mn) => mn.name === n) || { phase: n }).phase);
        let worst = { by: 0, at: null, name: '' };
        let compared = 0;
        for (const r of good) {
          const amt = at.map((si) => Math.max(value(r.state, si, r.k), 0));
          const N = amt.reduce((a, v) => a + v, 0);
          if (!(N > 0)) continue;
          const lnA = amt.map((v) => Math.log(v / N));
          if (def.coef === 'binary') {
            const { a0, a1, gap } = RtmS.binaryAt(def, (r.tc != null ? r.tc : temp) + 273.15);
            const xb = amt[1] / N;
            if (gap && xb > gap.xb1 && xb < gap.xb2) { lnA[0] = gap.lnAc; lnA[1] = gap.lnAb; }
            else {
              lnA[0] += xb * xb * (a0 - a1 * (3 - 4 * xb));
              lnA[1] += (1 - xb) * (1 - xb) * (a0 + a1 * (4 * xb - 1));
            }
          }
          names.forEach((n, j) => {
            if (!r.pq.phases.has(phase[j])) return;
            const si = r.pq.phases.get(phase[j]);
            if (!(si > -990) || !Number.isFinite(lnA[j])) return;
            const by = lnA[j] / Math.LN10 - si;
            compared++;
            if (Math.abs(by) > Math.abs(worst.by)) worst = { by, at: r, name: n };
          });
        }
        return { name: def.name, members: names, binary: def.coef === 'binary', compared, gap: worst.by, worst: worst.name,
          t: worst.at ? worst.at.t : null, cell: worst.at ? worst.at.cell : null };
      });
    }
    const ssMember = new Set((solidCheck || []).flatMap((ss) => ss.members));

    // --- the model's minerals: PHREEQC's saturation index where the model has
    // some of each, which holding it means is its target, and where none ----
    const mineralCheck = minerals.filter((mn) => !ssMember.has(mn.name)).map((mn) => {
      const si = model.species.indexOf(mn.name);
      let present = null;
      let absent = null;
      for (const r of good) {
        const v = r.pq.phases.has(mn.phase) ? r.pq.phases.get(mn.phase) : null;
        if (v === null || v < -990) continue;
        const amount = value(r.state, si, r.k);
        if (amount > 0) present = present ? [Math.min(present[0], v), Math.max(present[1], v)] : [v, v];
        else absent = absent === null ? v : Math.max(absent, v);
      }
      return { name: mn.name, phase: mn.phase, present, absent };
    });

    /*
      With <VOLUMES>, the part of PHREEQC's log K that goes with the pressure
      at a water r, dV (P - 1)/(R T ln 10) for a relation as written, dV from
      its species' molar volumes there (VM) and the water's own: PHREEQC's
      log K is less it, so a conditional constant moves with it as with the
      coefficients. 0 at one atmosphere or without volumes.
    */
    const vmCol = new Map(vmNames.map((n, i) => [n, i]));
    const vmOf = (r, n) => (vmCol.has(n) ? Number(r.pq.x[vmCol.get(n)]) || 0 : 0);
    const pressurePart = (r, prod, reac, water) => {
      if (!withVol || !r.pq.x || r.pq.x.length < vmNames.length) return 0;
      const tk = r.pq.tc + 273.15;
      const P = Math.max(pGiven, Math.exp(11.6702 - 3816.44 / (tk - 46.13)) * Math.min(r.pq.aw, 1));
      if (!(P > 1)) return 0;
      const f = (1e-9 * (P * 101325 - 101325)) / (R_KJ * tk);
      let dv = water ? water * vmOf(r, 'H2O') : 0;
      for (const t of prod) dv += t.c * vmOf(r, t.n);
      for (const t of reac) dv -= t.c * vmOf(r, t.n);
      return (f * dv) / Math.LN10;
    };

    // --- the equilibria's activity coefficients along the run --------------
    // H2O in a relation is the water, whose activity enters it.
    const drift = [];
    const unchecked = [];
    const isWater = (t) => t.n === 'H2O' && !model.species.includes('H2O');
    for (const e of modelEquilibria(o.modelText)) {
      const reac = e.reac.filter((t) => !isWater(t));
      const prod = e.prod.filter((t) => !isWater(t));
      const all = [...reac, ...prod].every((t) => mapped.has(t.n));
      // An exchanger's relations are looked at with the exchanger, whole; a surface's with the surface.
      const onEx = (t) => exBack.has(t.n) || exMasterBack.has(t.n) || sfBack.has(t.n) || t.n === electron;
      if (!all) { if (![...reac, ...prod].every((t) => mapped.has(t.n) || onEx(t))) unchecked.push(e.rel); continue; }
      const conv = (terms) => terms.map((t) => ({ c: t.c, n: mapped.get(t.n).p }));
      const water = e.prod.filter(isWater).reduce((a, t) => a + t.c, 0) - e.reac.filter(isWater).reduce((a, t) => a + t.c, 0);
      drift.push({ rel: e.rel, reac: conv(reac), prod: conv(prod), water });
    }
    const lgsum = (r, d) => {
      const sp = r.pq.species;
      let s = d.water ? d.water * log10(r.pq.aw) : 0;
      for (const t of d.prod) { if (!sp.has(t.n)) return null; s += t.c * sp.get(t.n)[1]; }
      for (const t of d.reac) { if (!sp.has(t.n)) return null; s -= t.c * sp.get(t.n)[1]; }
      return s + pressurePart(r, d.prod, d.reac, d.water);
    };
    const first = new Map();
    for (const r of good) {
      const key = `${r.cell}/${r.layer}`;
      if (!first.has(key)) first.set(key, r);
    }
    const drifts = drift.map((d) => {
      let top = { by: 0, at: null };
      for (const r of good) {
        const v0 = lgsum(first.get(`${r.cell}/${r.layer}`), d);
        const v = lgsum(r, d);
        if (v0 === null || v === null) continue;
        if (Math.abs(v - v0) > Math.abs(top.by)) top = { by: v - v0, at: r };
      }
      return { rel: d.rel, by: top.by, at: top.at };
    }).sort((a, b) => Math.abs(b.by) - Math.abs(a.by));

    // --- a model that keeps activities: its own against PHREEQC's ----------
    // Under ACTIVITY the model works its activity coefficients out itself, so
    // the question is no longer how far PHREEQC's moved but how closely the
    // model's own follow them: the same relations, both sides at each water.
    let activity = null;
    const Rtm = (typeof self !== 'undefined' && self.RtmModel)
      || (typeof globalThis !== 'undefined' && globalThis.RtmModel) || null;
    if (Rtm && /^\s*ACTIVITY\s*=\s*(?!none\b)\S/im.test(String(o.modelText || ''))) {
      let own = null;
      try { own = Rtm.compile(o.modelText); } catch (e) { own = null; }
      if (own && own.act && own.speciesNames.length === ns) {
        const lnG = new Float64Array(ns);
        const dG = new Float64Array(ns);
        const cw = new Float64Array(ns);
        const rels = own.equilibria.filter((eq) => eq.net.every(([si]) => mapped.has(own.speciesNames[si])));
        const gaps = rels.map((eq) => ({ rel: eq.text.split(',', 1)[0].trim(), eq, by: 0, at: null }));
        for (const r of good) {
          for (let si = 0; si < ns; si++) cw[si] = value(r.state, si, r.k);
          // A and B at this water's time, where the temperature goes with it.
          if (own.thermoAt) own.thermoAt(r.t);
          const w = Rtm.activityAt(own.act, cw, 0, lnG, dG, r.state);
          for (const g of gaps) {
            let pqSide = g.eq.water ? g.eq.water * log10(r.pq.aw) : 0;
            // With <VOLUMES> the log K's part at the pressure on each side, the model's its own (lnKAtP).
            let ours = (g.eq.water ? g.eq.water * w.lnAw / Math.LN10 : 0)
              + (Rtm.lnKAtP(g.eq, r.state, null) - Rtm.lnKAtP(g.eq, r.state, w)) / Math.LN10;
            let ok = true;
            const prod = [];
            const reac = [];
            for (const [si, c] of g.eq.net) {
              const p = mapped.get(own.speciesNames[si]).p;
              if (!r.pq.species.has(p)) { ok = false; break; }
              pqSide += c * r.pq.species.get(p)[1];
              ours += c * lnG[si] / Math.LN10;
              (c > 0 ? prod : reac).push({ c: Math.abs(c), n: p });
            }
            if (ok) pqSide += pressurePart(r, prod, reac, g.eq.water || 0);
            if (ok && Math.abs(pqSide - ours) > Math.abs(g.by)) { g.by = pqSide - ours; g.at = r; }
          }
        }
        gaps.sort((a, b) => Math.abs(b.by) - Math.abs(a.by));
        activity = {
          kind: own.act.kind,
          // TEMPERATURE as the model gives it: a number, or the expression each cell's comes from.
          temperature: own.temperature && own.temperature.varies ? own.temperature.given : own.act.temperature,
          gap: gaps.map((g) => ({ rel: g.rel, by: g.by, t: g.at ? g.at.t : null, cell: g.at ? g.at.cell : null })),
        };
      }
    }

    // --- what to say about it ----------------------------------------------
    const peak = (n) => {
      const si = model.species.indexOf(n);
      let m = 0;
      for (const g of groups) for (let k = 0; k < nT; k++) m = Math.max(m, Math.abs(value(g.state, si, k)));
      return m;
    };
    const supersaturated = [];
    for (const p of phases) {
      let best = null;
      for (const r of good) {
        const si = r.pq.phases.has(p) ? r.pq.phases.get(p) : -1e9;
        if (!best || si > best.si) best = { si, at: r };
      }
      if (best && best.si > 0) supersaturated.push({ phase: p, si: best.si, at: best.at });
    }
    supersaturated.sort((a, b) => b.si - a.si);
    const range = (f) => [Math.min(...good.map(f)), Math.max(...good.map(f))];
    const off = good.reduce((a, r) => (Math.abs(r.pq.cb) / Math.max(r.pq.mu, 1e-30)
      > Math.abs(a.pq.cb) / Math.max(a.pq.mu, 1e-30) ? r : a));
    const report = {
      waters: rows.length, cells: groups.length, times: idx.length, temperature: temp, temperatureFrom: tempFrom,
      // The run's, low and high, where each water is at its own.
      temperatures: temps ? [Math.min(...rows.map((r) => r.tc)), Math.max(...rows.map((r) => r.tc))] : null,
      waterError,
      counted: [...mapped].map(([n, v]) => ({ name: n, as: v.p })),
      skipped: [...skipped].map(([n, why]) => ({ name: n, why })),
      unmapped: unmapped.map((n) => ({ name: n, peak: peak(n) })).sort((a, b) => b.peak - a.peak),
      background: [...background].sort((a, b) => (a[0] < b[0] ? -1 : 1)),
      noH: hIndex < 0,
      failed: rows.filter((r) => !r.pq).map((r) => ({ t: r.t, cell: r.cell, layer: r.layer, error: r.error || '' })),
      ionicStrength: range((r) => r.pq.mu),
      pH: range((r) => r.pq.pH),
      chargeBalance: range((r) => r.pq.cb),
      notNeutral: Math.abs(off.pq.cb) > 0.05 * off.pq.mu ? { cb: off.pq.cb, t: off.t, cell: off.cell, layer: off.layer } : null,
      supersaturated: supersaturated.map((s) => ({ phase: s.phase, si: s.si, t: s.at.t, cell: s.at.cell, layer: s.at.layer })),
      drift: drifts.map((d) => ({ rel: d.rel, by: d.by, t: d.at ? d.at.t : null, cell: d.at ? d.at.cell : null })),
      activity,
      exchange,
      surface,
      redox,
      minerals: mineralCheck,
      gas,
      // Each solid solution's members against x lambda in the run, where it has the solid solution.
      solids: solidCheck,
      unchecked,
      phases,
    };

    const unit = o.unit || 'model time unit';
    const csv = () => {
      const head = [`t (${unit})`, 'cell', 'layer', 'ionic strength (mol/kgw)', 'pH (-log a H+)',
        '-log m(H+)', 'charge balance (eq/kgw)', 'a(H2O)', ...phases.map((p) => `SI ${p}`)];
      const lines = [head.map(csvCell).join(',')];
      for (const r of rows) {
        const q = r.pq;
        lines.push((q ? [fmtG(r.t, 10), r.cell, r.layer, fmtG(q.mu, 6), q.pH.toFixed(5), (-Math.log10(q.mH)).toFixed(5),
          fmtG(q.cb, 4), q.aw.toFixed(6), ...phases.map((p) => (q.phases.has(p) ? q.phases.get(p).toFixed(4) : 'NaN'))]
          : [fmtG(r.t, 10), r.cell, r.layer, ...Array(5 + phases.length).fill('')]).map(csvCell).join(','));
      }
      return `${lines.join('\n')}\n`;
    };
    return { rows, phases, report, csv };
  }

  function csvCell(v) {
    const s = String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  }

  return {
    readDatabase, readAssemblage, readSurfaces, Database, parseSide, normalise, countAtoms, rtmName, elementOf, normLabel,
    punchBlock, parseRows, modelEquilibria, modelElectron, modelPotentials, waterToModel, viewRun, fmtG, SEL, sitParam,
    readGasPhases, modelGas, kCalc, lkOption, readSolidSolutions, ssEnergies, readRates, readKinetics, withoutKinetics,
    rateLaw, readTransport,
  };
}));
