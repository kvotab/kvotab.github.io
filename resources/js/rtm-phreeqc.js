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
      // A phase's critical temperature (K) and pressure (atm) and acentric factor, where the database gives
      // them: PHREEQC then holds that gas in a gas phase by Peng and Robinson's equation of state.
      this.critical = new Map();
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
      let phase = null;
      for (const line of logicalLines(text)) {
        const tokens = line.trim().split(/\s+/).filter(Boolean);
        if (!tokens.length) continue;
        if (KEYWORDS.has(tokens[0].toUpperCase())) {
          block = tokens[0].toUpperCase();
          if (asDatabase && block === 'END') break;
          last = null;
          sitType = null;
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
              this.gamma.delete(last);
              this.otherGamma.delete(last);
            }
          } else if (last && this.readLogKOption(block, line, this.lk.get(`s ${last}`))) {
            // log_k, delta_h, the analytic expression or a named one: read.
          } else if (last && /^-?dw$/i.test(tokens[0]) && tokens.length > 1) {
            const v = Number(tokens[1]);
            if (Number.isFinite(v)) this.dw.set(last, v);
          } else if (last && /^-g(a(m(m(a)?)?)?)?$/i.test(tokens[0]) && tokens.length > 2) {
            const a = Number(tokens[1]);
            const b = Number(tokens[2]);
            if (Number.isFinite(a) && Number.isFinite(b)) this.gamma.set(last, { a, b });
          } else if (last && /^-(llnl_gamma|co2_llnl_gamma|activity_water)$/i.test(tokens[0])) {
            this.otherGamma.set(last, tokens[0].replace(/^-/, '').toLowerCase());
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
            }
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
            this.lk.set(`p ${phase}`, { k: [0, 0, 0, 0, 0, 0, 0, 0], add: [] });
          } else if (phase && this.readLogKOption(block, line, this.lk.get(`p ${phase}`))) {
            // log_k, delta_h, the analytic expression or a named one: read.
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
   * The phases of the EQUILIBRIUM_PHASES blocks of an input, each with the
   * saturation index it is held at (0 unless given) and anything else its
   * line says, which this page does not carry (an alternative reaction,
   * dissolve_only, precipitate_only). A phase named again takes the later line.
   */
  function readAssemblage(text) {
    const out = new Map();
    let inBlock = false;
    for (const line of logicalLines(text)) {
      const tokens = line.trim().split(/\s+/).filter(Boolean);
      if (!tokens.length) continue;
      const word = tokens[0].toUpperCase();
      if (KEYWORDS.has(word)) { inBlock = word === 'EQUILIBRIUM_PHASES'; continue; }
      if (!inBlock || tokens[0].startsWith('-')) continue;
      const si = tokens.length > 1 ? Number(tokens[1]) : 0;
      out.set(tokens[0], { name: tokens[0], si: Number.isFinite(si) ? si : 0, extra: tokens.slice(3).join(' ') });
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
        // How the sites are given (moles, or sites per nm2) says nothing once PHREEQC has loaded them.
        else if (/^-s/.test(opt) && /^d/i.test(tokens[1] || '')) cur.units = 'density';
        else if (/^-s/.test(opt) && /^a/i.test(tokens[1] || '')) cur.units = 'absolute';
        else if (!/^-(eq|equilibrate)/.test(opt)) cur.other.push(tokens.join(' '));
        continue;
      }
      const num = (x) => (x === undefined ? null : Number(x));
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
   *               between the species written in <SIT>; else each log K is
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
    const db = readDatabase(o.database.text, o.water.text);
    const follow = !!o.activity;
    // A SIT database: the page has SIT, and follows it.
    const sit = follow && db.model === 'SIT';
    if (follow && db.model && !sit) {
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
        if (b.model !== 'ddl') continue;
        for (const x of b.sites) {
          const cut = x.master.indexOf('_');
          if (cut < 1) continue;
          const name = x.master.slice(0, cut);
          const had = layers.get(name);
          if (!had || (had.area === null && Number.isFinite(x.area))) {
            layers.set(name, { area: Number.isFinite(x.area) ? x.area : null, mass: Number.isFinite(x.mass) ? x.mass : null });
          }
        }
      }
    }
    const layerAt = extras.length;
    for (const name of layers.keys()) extras.push(`EDL("psi", "${name}")`);
    const massAt = layers.size ? extras.length : -1;
    if (layers.size) extras.push('TOT("water")');
    let rows = runRows(o.engine, `${punchBlock(extras)}${o.water.text}\nEND\n`);
    if (o.solution != null) rows = rows.filter((r) => Number(r.soln) === Number(o.solution));
    if (!rows.length) {
      throw new Error('PHREEQC calculated no water from that input'
        + (o.solution != null ? ` with SOLUTION ${o.solution}` : '')
        + ': it needs a SOLUTION, or something PHREEQC calculates.');
    }
    let w = rows[rows.length - 1];
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
      const more = runRows(o.engine, `${punchBlock(extras)}${o.water.text}\nEND\nMIX 1\n ${Number(w.soln)} 1.0\nEND\n`);
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
      const others = [...r.left.slice(1), ...r.right];
      if (others.some((t) => t.n === 'e-') && !carryRedox) {
        skip('it dissolves with electrons, and the valence states are not held at one pe');
        return;
      }
      const missing = others.filter((t) => t.n !== 'H2O' && !isE(t.n) && !molal.has(t.n)).map((t) => t.n);
      if (missing.length) { skip(`the water has no ${missing.join(', ')}`); return; }
      if (!Number.isFinite(moles) || !Number.isFinite(lk) || !(waterKg > 0)) { skip('PHREEQC gave no amount or log K for it'); return; }
      minerals.push({ phase: a.name, si: moles > 0 && Number.isFinite(siLeft) ? siLeft : a.si, target: a.si,
        amount: Math.max(moles, 0) / waterKg, lk, c0: r.left[0].c, reac: r.left.slice(1), prod: r.right });
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
          if (!(e.m >= floor)) continue;
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
      const noLayer = [...layers].filter(([, l]) => !(l.area > 0 && l.mass > 0)).map(([n]) => n);
      if (!o.exact) sfSkipped.push({ name: all, why: 'a surface needs the relations held exactly' });
      else if (models.size > 1) {
        sfSkipped.push({ name: all, why: 'the input has a surface with a double layer and one without (-no_edl)' });
      } else if (noLayer.length) {
        sfSkipped.push({ name: all, why: `the double layer of ${noLayer.join(', ')} needs its area and grams, which `
          + 'its first site\'s line gives' });
      } else if ([...sfBlocks.values()].some((b) => b.sites.some((x) => !Number.isFinite(x.sites)))) {
        sfSkipped.push({ name: all, why: 'its sites follow a phase or a kinetic reactant, which this page does not carry' });
      } else if ([...sfBlocks.values()].some((b) => b.other.length)) {
        sfSkipped.push({ name: all, why: `its block says more than this page carries (${[...sfBlocks.values()]
          .flatMap((b) => b.other).join('; ')})` });
      } else {
        for (const [n, e] of w.surface) {
          if (!(e.m >= floor)) continue;
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
      [...layers].forEach(([surface, l], i) => {
        if (!onSf.some((e) => e.species.startsWith(`${surface}_`))) return;
        const psi = Number(w.x[layerAt + i]);
        potentials.push({ surface, species: `${surface}_psi`, psi, a: Math.exp(-FARADAY * psi / (GAS_R * tk)),
          area: l.area, grams: l.mass / kgw });
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
      // A species at none has no molality to read its log K back off.
      let logk = atNone.has(n) ? lkOf.get(n) : null;
      let logkC = atNone.has(n) ? logk - sumLg(prod) + sumLg(reac) - nw * logAw : sumLog(prod) - sumLog(reac);
      if (logk === null) logk = logkC + sumLg(prod) - sumLg(reac) + nw * logAw;
      /*
        A couple tied to the electron takes the database's log K, and says
        what pe it stands at in this water: PHREEQC's own, unless the water
        was given both its valence states.
      */
      let peHere = null;
      const ne = prod.filter((t) => isE(t.n)).reduce((s, t) => s + t.c, 0)
        - reac.filter((t) => isE(t.n)).reduce((s, t) => s + t.c, 0);
      if (ne && Number.isFinite(lkOf.get(n)) && !atNone.has(n)) {
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
    const eUsed = carryRedox && (tied.length > 0 || minerals.some((mn) => withE(mn.reac) || withE(mn.prod)));
    if (eUsed) taken.set('e-', 'e-');
    // The pe each couple stands at in PHREEQC's water: one, unless it was given
    // two valence states of an element, which the run then settles on one pe.
    const pes = tied.map((e) => e.peHere).filter((v) => Number.isFinite(v));
    const peSpread = pes.length ? [Math.min(...pes), Math.max(...pes)] : null;
    const outOfEq = !!peSpread && peSpread[1] - peSpread[0] > 1e-6;
    const name = new Map(order.map((s) => [s, rtmName(s, taken)]));
    for (const mn of minerals) mn.name = rtmName(mn.phase, taken);
    for (const g of gases) g.name = rtmName(g.phase, taken);
    for (const ss of solids) for (const c of ss.comps) c.name = rtmName(c.phase, taken);
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
      if (sit) {
        const one = ions.length === 1 && !hasWater ? ions[0] : null;
        e.sitLg = one ? Math.abs(one.c / e.right[0].c) * lg.get(one.n) : 0;
        e.gamma = one ? { sit: true } : null;
        e.folded = Math.abs(e.sitLg - e.lg) > 1e-12;
      } else {
        e.gamma = follow && e.lg !== 0 && g && ions.length === 1 && !hasWater && db.masterLabel(ions[0].n) !== null
          ? g : null;
        e.folded = follow && e.lg !== 0 && !e.gamma;
      }
      // log a: PHREEQC's ('db'); or this page's, an ion its molality alone
      // ('conditional') or times its coefficient ('follow'), the species its
      // fraction, times its ion's coefficient where it keeps it. The
      // exchanger's activity is PHREEQC's throughout.
      const laOf = (n, how) => {
        if (laMaster.has(n)) return laMaster.get(n);
        if (n === e.species && sit && how === 'follow') return e.la - e.lg + e.sitLg;
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
    const unsupported = follow && !sit ? order.filter((sp) => db.otherGamma.has(sp)) : [];
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

    const tc = w.tc;
    const date = o.date || new Date().toISOString().slice(0, 10);
    const width = Math.max(...order.map((s) => name.get(s).length), ...minerals.map((mn) => mn.name.length),
      ...gases.map((g) => g.name.length), ...solids.flatMap((ss) => ss.comps.map((c) => c.name.length)),
      ...[...exName.values()].map((nm) => nm.length), ...onSf.map((e) => e.name.length),
      ...potentials.map((pp) => pp.name.length)) + 2;
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
      if (sit) out.push("# coefficient, as PHREEQC's SIT has it.");
      else if (follow) out.push('# coefficient where the database gives it -gamma (a= and b=).');
      const folded = onEx.filter((e) => e.folded);
      if (folded.length) {
        out.push(`# PHREEQC takes the coefficient of ${folded.map((e) => e.name).join(', ')} from more than its one ion; `
          + 'here it is folded into the log K at this water.');
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
      if (potentials.length) {
        out.push(`# On a surface, with its diffuse double layer: the sites ${sites.join(' and ')},`);
      } else {
        out.push(`# On a surface, without electrostatics (-no_edl): the sites ${sites.join(' and ')},`);
      }
      out.push('# with the species PHREEQC put on them at their molalities. Each has its fraction of its');
      out.push("# sites for its activity, and its relation the database's log K.");
      for (const pp of potentials) {
        out.push(`# ${pp.name} is the potential of the surface ${pp.surface}, ${fmtG(pp.area, 6)} m2/g and ${fmtG(pp.grams, 6)} g of it`);
        out.push(`# to each kg of water, at ${fmtG(pp.psi * 1e3, 5)} mV here: rtm.html puts it into each relation on ${pp.surface}`);
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
    out.push('', '<SETTINGS>', 'MODE = batch', 'TEND = 1', 'TIME_UNIT = second',
      `EQUILIBRATE = ${o.exact ? 'always' : '1'}`);
    // A relation whose log K goes with temperature reads it, without ACTIVITY too.
    const withT = (terms) => !!terms && (terms[1] !== 0 || terms.slice(2).some((v) => v !== 0));
    const anyT = eqs.some((e) => withT(db.logKTerms('s', e.species))) || minerals.some((mn) => withT(db.logKTerms('p', mn.phase)))
      || solids.some((ss) => !!ss.energy || ss.comps.some((c) => withT(db.logKTerms('p', c.phase))))
      || gases.some((g) => withT(db.logKTerms('p', g.phase))) || onEx.some((e) => withT(db.logKTerms('x', e.species)))
      || onSf.some((e) => !e.master && withT(db.logKTerms('f', e.species)));
    if (follow) out.push(`ACTIVITY = ${sit ? 'sit' : 'debye-huckel'}`, `TEMPERATURE = ${fmtG(tc, 10)}`);
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
    // Each species its own D: the ions coupled, so the water stays neutral as they spread.
    if (o.dw) out.push('DIFFUSION = nernst-planck');
    out.push('', '<SPECIES>');
    const width2 = Math.max(...order.map((sp) => fmtG(molal.get(sp), 15).length),
      ...minerals.map((mn) => fmtG(mn.amount, 15).length), ...onEx.map((e) => fmtG(e.m, 15).length),
      ...onSf.map((e) => fmtG(e.m, 15).length), ...potentials.map((pp) => fmtG(pp.a, 15).length),
      ...gases.map((g) => fmtG(g.amount, 15).length), ...solids.flatMap((ss) => ss.comps.map((c) => fmtG(c.amount, 15).length)))
      + 2;
    for (const s of order) {
      let d = '';
      if (o.dw && db.dw.has(s)) d = `D=${fmtG(db.dw.get(s), 6)}`;
      else if (o.D) d = `D=${fmtG(o.D, 6)}`;
      if (!follow) {
        out.push(`${name.get(s).padEnd(width)}${fmtG(molal.get(s), 15)}${d ? `  ${d}` : ''}`);
        continue;
      }
      const bits = [];
      if (chargeOf(name.get(s)) !== chargeOf(s)) bits.push(`z=${chargeOf(s)}`);
      // SIT takes no a or b.
      const g = sit ? null : db.gamma.get(s);
      if (g) {
        if (chargeOf(s)) bits.push(`a=${fmtG(g.a, 6)}`);
        bits.push(`b=${fmtG(g.b, 6)}`);
      }
      if (d) bits.push(d);
      const more = bits.join('  ');
      out.push(`${name.get(s).padEnd(width)}${more ? fmtG(molal.get(s), 15).padEnd(width2) + more
        : fmtG(molal.get(s), 15)}`);
    }
    if (eUsed) out.push(`${'e-'.padEnd(width)}${''.padEnd(follow ? width2 : 0)}electron`);
    for (const mn of minerals) {
      const amount = fmtG(mn.amount, 15);
      out.push(`${mn.name.padEnd(width)}${follow ? `${amount.padEnd(width2)}mineral` : `${amount}  mineral`}`);
    }
    for (const ss of solids) {
      for (const c of ss.comps) {
        const amount = fmtG(c.amount, 15);
        out.push(`${c.name.padEnd(width)}${follow ? `${amount.padEnd(width2)}mineral` : `${amount}  mineral`}`);
      }
    }
    for (const g of gases) {
      const amount = fmtG(g.amount, 15);
      const crit = g.crit ? `  Tc=${fmtG(g.crit.tc, 10)}  Pc=${fmtG(g.crit.pc, 10)}  omega=${fmtG(g.crit.omega, 10)}` : '';
      out.push(`${g.name.padEnd(width)}${follow ? `${amount.padEnd(width2)}gas` : `${amount}  gas`}${crit}`);
    }
    for (const sp of exUsed) out.push(`${exName.get(sp).padEnd(width)}${''.padEnd(follow ? width2 : 0)}exchanger`);
    for (const e of onEx) {
      const amount = fmtG(e.m, 15);
      const g = e.gamma && !sit ? `  a=${fmtG(e.gamma.a, 6)}  b=${fmtG(e.gamma.b, 6)}` : '';
      out.push(`${e.name.padEnd(width)}${follow ? amount.padEnd(width2) : `${amount}  `}exchange${g}`);
    }
    for (const pp of potentials) {
      const amount = fmtG(pp.a, 15);
      out.push(`${pp.name.padEnd(width)}${follow ? amount.padEnd(width2) : `${amount}  `}potential  `
        + `area=${fmtG(pp.area, 10)}  grams=${fmtG(pp.grams, 8)}`);
    }
    for (const e of onSf) {
      const amount = fmtG(e.m, 15);
      out.push(`${e.name.padEnd(width)}${follow ? amount.padEnd(width2) : `${amount}  `}surface`);
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
        k: `${kText(db.logKTerms('s', e.species), follow ? e.logk : e.logkC)}${e.kf ? `, kf = ${fmtG(e.kf, 6)}` : ''}`,
        note: follow ? `# here ${e.logkC.toFixed(4)}` : `# log K ${e.logk.toFixed(4)}`,
      };
    });
    // A mineral's saturation: its activity is 1, and its log K the phase's at
    // this temperature plus the saturation index it is held at.
    for (const mn of minerals) {
      const aq = (terms) => terms.filter((t) => t.n !== 'H2O');
      const sumLg = (terms) => aq(terms).reduce((acc, t) => acc + t.c * lgOf(t.n), 0);
      const nw = mn.prod.filter((t) => t.n === 'H2O').reduce((acc, t) => acc + t.c, 0)
        - mn.reac.filter((t) => t.n === 'H2O').reduce((acc, t) => acc + t.c, 0);
      const logk = mn.lk + mn.si;
      const logkC = logk - sumLg(mn.prod) + sumLg(mn.reac) - nw * logAw;
      const reac = [{ c: mn.c0, n: mn.name }, ...(follow ? mn.reac : aq(mn.reac))];
      const prod = follow ? mn.prod : aq(mn.prod);
      lines.push({
        rel: `${side(reac)} <=> ${side(prod)}`,
        k: kText(db.logKTerms('p', mn.phase), follow ? logk : logkC),
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
        k: kText(db.logKTerms('p', g.phase), follow ? g.lk : logkC),
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
          k: kText(db.logKTerms('p', c.phase), follow ? c.lk : logkC),
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
        k: kText(db.logKTerms('x', e.species), follow ? e.logk : e.logkC),
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
        k: kText(db.logKTerms('f', e.species), follow ? e.lk : logkC),
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
    out.push('', '<REACTIONS>', '# Your kinetic reactions here, in the same species and units.');
    const text = `${out.join('\n')}\n`;

    const dropped = [...molal.keys()].filter((n) => !kept.has(n));
    const top = dropped.length ? dropped.reduce((a, b) => (molal.get(b) > molal.get(a) ? b : a)) : null;
    return {
      text,
      water: w,
      names: name,
      molal,
      // The minerals' and exchange species' amounts as written, by their names in the model.
      amounts: new Map(minerals.map((mn) => [mn.name, mn.amount]).concat(onEx.map((e) => [e.name, e.m]))
        .concat(gases.map((g) => [g.name, g.amount]))
        .concat(solids.flatMap((ss) => ss.comps.map((c) => [c.name, c.amount])))
        .concat(onSf.map((e) => [e.name, e.m])).concat(potentials.map((pp) => [pp.name, pp.a]))),
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
        activity: follow ? { kind: sit ? 'sit' : 'debye-huckel', temperature: tc, unsupported,
          sitPairs: sit ? sitPairs.length : 0 } : null,
        minerals: minerals.map((mn) => ({ phase: mn.phase, as: mn.name, amount: mn.amount, si: mn.target })),
        phasesSkipped,
        exchange: onEx.length ? { exchangers: exUsed.map((sp) => exName.get(sp)),
          species: onEx.map((e) => ({ species: e.species, as: e.name, amount: e.m, folded: e.folded })) } : null,
        exchangeSkipped: exSkipped,
        surface: onSf.length ? { sites: onSf.filter((e) => e.master).map((e) => e.name),
          species: onSf.map((e) => ({ species: e.species, as: e.name, amount: e.m })),
          potentials: potentials.map((pp) => ({ name: pp.name, surface: pp.surface, psi: pp.psi, area: pp.area,
            grams: pp.grams })) } : null,
        surfaceSkipped: sfSkipped,
        gas: gases.length ? { ...gasFixed, species: gases.map((g) => ({ phase: g.phase, as: g.name, amount: g.amount,
          pressure: g.pressure })) } : null,
        gasSkipped,
        solids: solids.map((ss) => ({ name: ss.name, members: ss.comps.map((c) => ({ phase: c.phase, as: c.name,
          amount: c.amount })), binary: ss.energy ? { a0: ss.energy.a0, a1: ss.energy.a1, tk: ss.tk } : null })),
        solidsSkipped,
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
      if (cut > 0) out.set(parts[0].slice(0, cut), { name: parts[0], area: num('area'), grams: num('grams') });
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
    const potNames = new Set([...potentials.values()].map((pp) => pp.name));
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
    const solution = (k, r, together) => {
      const lines = [`SOLUTION ${k}`, `  temp ${fmtG(r.tc, 12)}`, '  units mol/kgw',
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
    const runSome = (sub) => runRows(o.engine,
      `${punchBlock()}${sub.map((r, k) => solution(k + 1, r)).join('')}END\n`);
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
      const potAt = layered.map((sn) => ({ sn, si: model.species.indexOf(potentials.get(sn).name), ...potentials.get(sn) }));
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
            return ` ${sp} ${fmtG(v, 15)} ${fmtG(pp.area, 15)} ${fmtG(pp.grams, 15)}`;
          });
          return lines.length ? `SURFACE ${k + 1}\n -equilibrate ${k + 1}\n${layered.length ? '' : ' -no_edl\n'}`
            + `${lines.join('\n')}\n` : '';
        }).join('');
        let out;
        try {
          out = runRows(o.engine, `${punchBlock(layered.map((sn) => `EDL("psi", "${sn}")`))}`
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
        // With a double layer: the potentials, and how far the run's are from PHREEQC's, in volts.
        potentials: potAt.map((pp) => pp.name),
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
      return s;
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
            let ours = g.eq.water ? g.eq.water * w.lnAw / Math.LN10 : 0;
            let ok = true;
            for (const [si, c] of g.eq.net) {
              const p = mapped.get(own.speciesNames[si]).p;
              if (!r.pq.species.has(p)) { ok = false; break; }
              pqSide += c * r.pq.species.get(p)[1];
              ours += c * lnG[si] / Math.LN10;
            }
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
    readGasPhases, modelGas, kCalc, lkOption, readSolidSolutions, ssEnergies,
  };
}));
