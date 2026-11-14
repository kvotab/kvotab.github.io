/* ==========================================================================
   RTM.HTML: SIMPLE FUNCTIONS ON PHREEQC

   What the Batch tab needs to run SKB's Simple Functions -- the solubility
   limits of 20 elements that SimpleFunctions.html calculates (Grivé et al.,
   TR-10-61) -- through PHREEQC instead: a database, phreeqc.dat with the
   Simple Functions' own SR-Site data put into it (sf-data.js), and the
   batch's input, Version A or B, with the solids to try for each element and
   the constants to draw.

   THE DATABASE is phreeqc.dat with these definitions added before its END
   (PHREEQC reads a database only up to its first END):

     - the 18 elements phreeqc.dat lacks, each with the Simple Functions'
       master species (Ra+2, Zr+4, NbO3-, TcO(OH)2, ...);
     - every aqueous species of the 20 elements, written as the Simple
       Functions write it, and every candidate solid as a phase. The Simple
       Functions write redox with O2(g), PHREEQC with e-; O2(g) is taken out
       with O2(g) + 4 H+ + 4 e- = 2 H2O, log K 83.1, the constant the Simple
       Functions use, so that log K (PHREEQC) = log K + 83.1 c, c the net
       coefficient of O2(g) among the products. Nothing else changes: the
       constants are the Simple Functions' to the last digit;
     - phreeqc.dat's own species of Sr and Pb, the two of the 20 it has:
       those the Simple Functions have take their constants (and keep
       phreeqc.dat's -gamma), the others are suppressed (log_k -100), so
       each element has the Simple Functions' species and no others;
     - each of those species and solids `-add_logk dK_<name> 1`, the named
       expression dK_<name> nought here; an input that draws the constants
       sets them, NAMED_EXPRESSIONS dK_<name> log_k {dK_<name>};
     - goethite and magnetite with the Simple Functions' constants (Goethite
       redefined, Magnetite new), the redox buffer of Version B;
     - methane and sulfide suppressed (log_k -100): the Simple Functions have
       neither;
     - three pseudo-phases that hold a property of the water: Fix_H+ the pH;
       Fix_Eh the Eh in mV, its saturation index 59.16 pe; and Fix_HCO3- the
       free HCO3-, which the Simple Functions take as given, through Mark, a
       marker anion with HCO3-'s activity coefficient: with Mark at a
       millionth of the free HCO3- wanted and Fix_HCO3- at -6, HCO3- is at
       exactly that molality -- for the kilogram of water the water starts
       with, Mark being so many moles, where conditioning makes some water.

   THE INPUT holds the pH with hydrochloric acid, added or taken out. Each
   solid is offered in two halves, the first with the pH free and the second
   with it held: from the water the solid itself has made PHREEQC finds the
   held pH far more surely than in one step, where now and then it ends,
   without saying so, with all the chloride taken out and the pH far off.
   Taking acid out ends where the water has no chloride left, and a solid
   that releases more acid than that leaves the pH where it can: a run whose
   pH is not where it was asked gives no totals, so that it is never taken
   for the lowest. (A base beside the acid, to hold the pH either way, makes
   PHREEQC add both.)

   The major ions keep phreeqc.dat's species and constants, and its activity
   model is used throughout: this is the Simple Functions' chemistry on
   PHREEQC, not a copy of their arithmetic.

   It runs in the browser beside sf-data.js and sf-model.js (SFData,
   SFModel), and under Node for resources/tests/rtm/test-sf-phreeqc.js.
   ========================================================================== */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.RtmSfPhreeqc = api;
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  /** O2(g) + 4 H+ + 4 e- = 2 H2O, the Simple Functions' constant. */
  const LOGK_O2 = 83.1;
  const SUPPRESS = -100;
  /** The name the database goes by on the page. */
  const DATABASE_NAME = 'phreeqc.dat with Simple Functions (SR-Site)';
  /**
    How much of each solid a water is offered, mol: the Simple Functions' line between an element whose solubility
    limits it and one it does not, so that a solid that dissolves completely gives its element that much.
  */
  const AMOUNT = 0.01;
  /** How near its pH a run must end for its totals to count. */
  const PH_HELD = 0.001;
  /** The marker anion that holds the free HCO3-, a millionth of it. */
  const MARK = 'Mark';
  const PHASE_TAG = /\((aq|g|s|cr|c|am|l|sol|am,\s*fresh|am,\s*aged|beta|alpha|nat|cer)\)\s*$/i;

  /** A formula as PHREEQC writes it: no phase tag, a colon for the hydrate dot, H4SiO4 for Si(OH)4. */
  function phreeqcFormula(f) {
    let g = String(f).trim();
    if (g === 'O2' || g === 'O2(g)') return 'O2(g)';
    for (let i = 0; i < 3; i++) {
      const h = g.replace(PHASE_TAG, '');
      if (h === g) break;
      g = h;
    }
    g = g.replace(/[·•]/g, ':');
    return g === 'Si(OH)4' ? 'H4SiO4' : g;
  }

  /** A solid's phase name: its Simple Functions name, a colon for the hydrate dot and no comma or space, which the batch's Solids field parts names by. */
  function phaseName(id) {
    return String(id).trim().replace(/[·•]/g, ':').replace(/,\s*/g, '_').replace(/\s+/g, '_');
  }

  /** A reaction as net coefficients, products above nought: {formula: coefficient}, in the order written. */
  function netOf(SF, text) {
    const rx = SF.parseReaction(text);
    const d = new Map();
    const add = (t, s) => {
      const f = phreeqcFormula(t.formula);
      d.set(f, (d.get(f) || 0) + s * t.coef);
    };
    rx.left.forEach((t) => add(t, -1));
    rx.right.forEach((t) => add(t, 1));
    return { rx, d };
  }

  /** O2(g) taken out: the reaction less c times 2 H2O = O2(g) + 4 H+ + 4 e-, log K less c times -83.1. */
  function withoutO2(d, logK) {
    const c = d.get('O2(g)') || 0;
    const out = new Map();
    for (const [k, v] of d) if (k !== 'O2(g)') out.set(k, v);
    if (c) {
      for (const [k, v] of [['H2O', -2], ['H+', 4], ['e-', 4]]) out.set(k, (out.get(k) || 0) - c * v);
    }
    for (const [k, v] of out) if (Math.abs(v) < 1e-10) out.delete(k);
    return { d: out, logK: logK + LOGK_O2 * c, c };
  }

  const round = (x, n) => Number(x.toFixed(n));
  /** A coefficient as an equation writes it: none for one, else up to six decimals. */
  const coef = (v) => (Math.abs(Math.abs(v) - 1) < 1e-12 ? '' : `${round(Math.abs(v), 6)} `);
  /** A constant to ten decimals, which is every digit the data have. */
  const fmtK = (x) => String(round(x, 10));

  /** The charge and elements of a reaction, e- counted as a charge; a list of what does not balance. */
  function unbalanced(SF, d) {
    let charge = 0;
    const els = new Map();
    for (const [f, v] of d) {
      if (f === 'e-') { charge -= v; continue; }
      charge += v * SF.chargeOf(f);
      for (const [el, n] of Object.entries(SF.elementCounts(f))) els.set(el, (els.get(el) || 0) + v * n);
    }
    const out = [];
    if (Math.abs(charge) > 1e-9) out.push(`charge ${round(charge, 6)}`);
    for (const [el, n] of els) if (Math.abs(n) > 1e-9) out.push(`${el} ${round(n, 6)}`);
    return out;
  }

  /** An aqueous species' equation: the reactants, then the species first on the right. */
  function speciesEquation(d, name) {
    const lhs = [...d].filter(([, v]) => v < 0).map(([k, v]) => `${coef(v)}${k}`);
    const rhs = [...d].filter(([k, v]) => v > 0 && k !== name).map(([k, v]) => `${coef(v)}${k}`);
    return `${lhs.join(' + ')} = ${[name, ...rhs].join(' + ')}`;
  }

  /** A phase's equation: the phase first on the left, then the reactants, = the products. */
  function phaseEquation(d, formula) {
    const lhs = [...d].filter(([k, v]) => v < 0 && k !== formula).map(([k, v]) => `${coef(v)}${k}`);
    const rhs = [...d].filter(([, v]) => v > 0).map(([k, v]) => `${coef(v)}${k}`);
    return `${[formula, ...lhs].join(' + ')} = ${rhs.join(' + ')}`;
  }

  /**
    What a database already defines, read from its text up to its first END: the element of each primary master
    species, and each aqueous species with its equation and -gamma.
  */
  function readBase(text) {
    const lines = String(text).replace(/\r\n?/g, '\n').split('\n');
    const end = lines.findIndex((l) => /^\s*END\s*$/i.test(l));
    const masters = new Map();
    const species = new Map();
    let block = '';
    let cur = null;
    for (const line of lines.slice(0, end < 0 ? lines.length : end)) {
      const bare = line.replace(/#.*$/, '');
      if (/^[A-Z_]+\s*$/.test(bare.trim()) && /^[A-Z]/.test(bare)) { block = bare.trim(); cur = null; continue; }
      if (!bare.trim()) continue;
      if (block === 'SOLUTION_MASTER_SPECIES') {
        const [el, sp] = bare.trim().split(/\s+/);
        if (el && sp && !el.includes('(')) masters.set(el, sp);
      } else if (block === 'SOLUTION_SPECIES') {
        const opt = /^\s*-([a-z_]+)\s*(.*)$/i.exec(bare);
        if (opt && cur) {
          if (/^gamma$/i.test(opt[1])) cur.gamma = opt[2].trim().split(/\s+/).slice(0, 2).join(' ');
          continue;
        }
        if (bare.includes('=') && !/^\s/.test(bare)) {
          const eq = bare.split(';')[0].trim();
          const name = eq.split('=')[1].trim().split(/\s+\+\s+/)[0].trim();
          cur = { eq, name, gamma: null };
          species.set(name, cur);
        }
      }
    }
    return { masters, species };
  }

  /**
    The definitions to add, from a Simple Functions dataset (SFData.SRSITE): their text, and the species, solids and
    named expressions in it. SF is sf-model.js (SFModel), base the text of the database they go into (phreeqc.dat),
    weights the elements' atomic weights.
  */
  function build(data, SF, base, weights) {
    const known = readBase(base);
    const out = { species: [], solids: [], elements: [], suppressed: [] };
    const masterLines = [];
    const speciesBlocks = [];
    const phaseBlocks = [];
    const names = new Set();
    const named = (n, what) => {
      if (names.has(n)) throw new Error(`two of the Simple Functions' ${what} are named ${n} in PHREEQC`);
      names.add(n);
      return n;
    };
    const gammaHCO3 = (known.species.get('HCO3-') || {}).gamma;
    if (!gammaHCO3) throw new Error('the database has no -gamma for HCO3-, which the marker of free HCO3- copies');
    for (const E of data.elements) {
      const master = phreeqcFormula(E.master);
      const has = known.masters.get(E.el);
      if (has && has !== master) throw new Error(`${E.el}: the database's master species is ${has}, the Simple Functions' ${master}`);
      if (!has) {
        const w = weights[E.el];
        if (!(w > 0)) throw new Error(`no atomic weight for ${E.el}`);
        masterLines.push(`${E.el.padEnd(8)}${master.padEnd(12)}0   ${E.el.padEnd(6)}${w}`);
        speciesBlocks.push(`${master} = ${master}\n    log_k 0`);
      }
      const mine = new Set();
      for (const sp of E.species) {
        if (sp.off) continue;
        const { d } = netOf(SF, sp.rx);
        // The species formed: the one product of the reaction that is not among the Simple Functions' basis species.
        const name = phreeqcFormula(SF.compileSpecies(sp, E.master).product);
        const { d: d1, logK, c } = withoutO2(d, sp.logK);
        const bad = unbalanced(SF, d1);
        if (bad.length) throw new Error(`${E.el} ${sp.id}: ${sp.rx} does not balance (${bad.join(', ')})`);
        if (Math.abs((d1.get(name) || 0) - 1) > 1e-12) throw new Error(`${E.el} ${sp.id}: ${name} is not formed once`);
        const dk = named(`dK_${name}`, 'species and solids');
        const was = known.species.get(name);
        const eq = speciesEquation(d1, name);
        speciesBlocks.push([`# ${E.el} ${sp.id}: ${sp.rx}, log K ${sp.logK}, ± ${sp.dlogK}${c ? `; O2(g) taken out, ${round(LOGK_O2 * c, 6)}` : ''}`,
          eq, `    log_k ${fmtK(logK)}`, ...(was && was.gamma ? [`    -gamma ${was.gamma}`] : []), `    -add_logk ${dk} 1`].join('\n'));
        mine.add(name);
        out.species.push({ el: E.el, id: sp.id, name, rx: sp.rx, eq, logK: sp.logK, dlogK: sp.dlogK || 0, logKPhreeqc: round(logK, 10), c, dk });
      }
      // The database's own species of the element that the Simple Functions do not have: suppressed.
      if (has) {
        for (const [name, s] of known.species) {
          if (name === master || mine.has(name)) continue;
          let els;
          try { els = SF.elementCounts(name); } catch (e) { continue; }
          if (!(E.el in els)) continue;
          speciesBlocks.push(`# ${E.el}: ${name} is not among the Simple Functions' species\n${s.eq}\n    log_k ${SUPPRESS}`);
          out.suppressed.push(name);
        }
      }
      for (const so of E.solids) {
        if (so.off) continue;
        const { rx, d } = netOf(SF, so.rx);
        const formula = phreeqcFormula(rx.left[0].formula);
        const name = named(phaseName(so.id), 'species and solids');
        const { d: d1, logK, c } = withoutO2(d, so.logK);
        const bad = unbalanced(SF, d1);
        if (bad.length) throw new Error(`${E.el} ${so.id}: ${so.rx} does not balance (${bad.join(', ')})`);
        const dk = named(`dK_${name}`, 'species and solids');
        const eq = phaseEquation(d1, formula);
        phaseBlocks.push([`# ${E.el} ${so.id}: ${so.rx}, log K ${so.logK}, ± ${so.dlogK}${c ? `; O2(g) taken out, ${round(LOGK_O2 * c, 6)}` : ''}`,
          name, `    ${eq}`, `    log_k ${fmtK(logK)}`, `    -add_logk ${dk} 1`].join('\n'));
        out.solids.push({ el: E.el, id: so.id, name, formula, rx: so.rx, eq, logK: so.logK, dlogK: so.dlogK || 0, logKPhreeqc: round(logK, 10),
          c, dk, use: so.use !== false });
      }
      out.elements.push({ el: E.el, master, solids: out.solids.filter((s) => s.el === E.el && s.use).map((s) => s.name) });
    }
    // Goethite and magnetite, the Simple Functions' constants, written as they write them (forming the solid) and turned round.
    const fe = [];
    for (const id of ['Goethite', 'Magnetite']) {
      const m = (data.major || []).find((x) => x.id === id);
      if (!m) throw new Error(`the Simple Functions' data have no ${id}`);
      const { rx, d } = netOf(SF, m.rx);
      const formula = phreeqcFormula(rx.right[0].formula);
      const back = new Map([...d].map(([k, v]) => [k, -v]));
      const { d: d1, logK } = withoutO2(back, -m.logK);
      const bad = unbalanced(SF, d1);
      if (bad.length) throw new Error(`${id}: ${m.rx} does not balance (${bad.join(', ')})`);
      const eq = phaseEquation(d1, formula);
      phaseBlocks.push([`# ${id}: ${m.rx}, log K ${m.logK}, turned round, O2(g) taken out`, id, `    ${eq}`, `    log_k ${fmtK(logK)}`].join('\n'));
      fe.push({ id, eq, logKPhreeqc: round(logK, 10) });
    }
    out.fe = fe;
    // No methane, no sulfide: their species, and so all built on them, suppressed.
    for (const name of ['CH4', 'HS-']) {
      const s = known.species.get(name);
      if (!s) continue;
      speciesBlocks.push(`# No ${name === 'CH4' ? 'methane' : 'sulfide'}, as in the Simple Functions\n${s.eq}\n    log_k ${SUPPRESS}${s.gamma ? `\n    -gamma ${s.gamma}` : ''}`);
      out.suppressed.push(name);
    }
    out.named = [...names].filter((n) => n.startsWith('dK_'));
    const text = [
      '',
      '# ==========================================================================',
      `# ${DATABASE_NAME}: the Simple Functions' data, ${data.label || data.id || ''},`,
      '# added by rtm.html (resources/js/rtm-sf-phreeqc.js). O2(g) is taken out of',
      '# every reaction with O2(g) + 4 H+ + 4 e- = 2 H2O, log K 83.1, so that',
      '# log K (PHREEQC) = log K (Simple Functions) + 83.1 c, c the net coefficient of',
      '# O2(g) among the products. dK_<name> is added to each constant: nought unless',
      '# an input sets it in NAMED_EXPRESSIONS.',
      '# ==========================================================================',
      'SOLUTION_MASTER_SPECIES',
      ...masterLines,
      `${MARK.padEnd(8)}${`${MARK}-`.padEnd(12)}0   ${MARK.padEnd(6)}1`,
      '',
      'SOLUTION_SPECIES',
      speciesBlocks.join('\n'),
      `# The marker of free HCO3-: no complexes, HCO3-'s activity coefficient\n${MARK}- = ${MARK}-\n    log_k 0\n    -gamma ${gammaHCO3}`,
      '',
      'NAMED_EXPRESSIONS',
      out.named.map((n) => `${n}\n    log_k 0`).join('\n'),
      '',
      'PHASES',
      phaseBlocks.join('\n'),
      '# Holding a property of the water, with a reagent under EQUILIBRIUM_PHASES',
      '# or in SOLUTION: the pH (-pH), the Eh in mV (59.16 pe), and the free',
      `# HCO3- (-6, with ${MARK} at a millionth of the free HCO3- wanted)`,
      'Fix_H+\n    H+ = H+\n    log_k 0',
      'Fix_Eh\n    H2O + 59.16 e- = H2O\n    -no_check\n    log_k 0',
      `Fix_HCO3-\n    ${MARK} + HCO3- = ${MARK}-\n    -no_check\n    log_k 0`,
      '',
    ].join('\n');
    out.text = text;
    return out;
  }

  /** The database: the base's text with the definitions put in before its first END, or at its end. */
  function database(base, built) {
    const b = String(base);
    return /^[ \t]*END[ \t]*$/m.test(b) ? b.replace(/^[ \t]*END[ \t]*$/m, `${built.text}\nEND`) : `${b}\n${built.text}\nEND\n`;
  }

  /**
    A table's columns for the water, as the Simple Functions read them (SFModel.recogniseColumns): {role: column
    name}, and what is missing for Version B (pH, Ca, Na, Cl, SO4, Si, HCO3) and for Version A (also Eh, Fe).
  */
  function columnsOf(SF, columns) {
    const { map } = SF.recogniseColumns(columns);
    const out = {};
    for (const [k, i] of Object.entries(map)) out[k] = columns[i];
    // Potassium with its unit too, "[K]tot (m)", which the Simple Functions, having no use for it, do not look for.
    if (!out.K) {
      const k = columns.find((c) => /^\[?k\+?\]?(tot)?(\(m\)|m)?$/.test(SF.normaliseHeader(c)) && !Object.values(out).includes(c));
      if (k) out.K = k;
    }
    const need = ['pH', 'Ca', 'Na', 'Cl', 'SO4', 'Si', 'HCO3'];
    return { cols: out, missingB: need.filter((k) => !out[k]), missingA: [...need, 'Eh', 'Fe'].filter((k) => !out[k]) };
  }

  /** The solids to try, each element's own: "Sr: Strontianite, Celestite; Ra: ...", those the Simple Functions use. */
  function solidsSpec(built) {
    return built.elements.filter((e) => e.solids.length).map((e) => `${e.el}: ${e.solids.join(', ')}`).join('; ');
  }

  /** The constants to draw: each species and solid normal about nought, its ± two standard deviations, as the Simple Functions draw them. */
  function uncertainSpec(built) {
    return [...built.species, ...built.solids].filter((s) => s.dlogK > 0).map((s) => `${s.dk} normal 0 ${round(s.dlogK / 2, 10)}`).join('; ');
  }

  /**
    The batch's input. version 'B': each water conditioned by goethite and magnetite at its own pH and its free HCO3-,
    then each solid in turn with them, pH held; 'A': the water at its own Eh and iron, then each solid in turn, pH
    and Eh held. drawn: each constant set to its draw, dK_<name> as {dK_<name>}. cols: the table's columns.
  */
  function input(built, { version = 'B', drawn = false, cols, amount = AMOUNT }) {
    const c = (k) => `{${cols[k]}}`;
    const els = built.elements.map((e) => e.el);
    const lines = [];
    if (version === 'A') {
      lines.push("# The Simple Functions on PHREEQC, Version A: each water at its own pH and Eh, its iron",
        '# from the table, then each solid in turn, pH and Eh held. The lowest of each element is kept.');
    } else {
      lines.push('# The Simple Functions on PHREEQC, Version B: each water conditioned by goethite and',
        '# magnetite at its own pH, then each solid in turn with them, pH held. The lowest of each',
        '# element is kept.');
    }
    if (drawn) {
      const draws = [...built.species, ...built.solids].filter((s) => s.dlogK > 0);
      lines.push("# Each constant as drawn for this run, added to the Simple Functions' own:", 'NAMED_EXPRESSIONS',
        ...draws.flatMap((s) => [s.dk, `    log_k {${s.dk}}`]));
    }
    const water = [' units mol/kgw', ` pH ${c('pH')}`];
    if (version === 'A') water.push(` pe 0 Fix_Eh ${c('Eh')}    # the pe of the Eh in mV`);
    water.push(` Ca ${c('Ca')}`);
    if (cols.Mg) water.push(` Mg ${c('Mg')}`);
    water.push(` Na ${c('Na')}`);
    if (cols.K) water.push(` K ${c('K')}`);
    water.push(` Cl ${c('Cl')}`, ` S(6) ${c('SO4')}`, ` Si ${c('Si')}`);
    if (version === 'A') water.push(` Fe ${c('Fe')}`);
    water.push(` C(4) ${c('HCO3')} Fix_HCO3- -6    # carbon to give the free HCO3- of the table,`,
      ` ${MARK} ${c('HCO3')} umol/kgw    # a million times this marker`);
    const hold = [` Fix_H+ -${c('pH')} HCl 10    # the pH held, with acid added or taken out`];
    const half = round(amount / 2, 12);
    const halves = [`# Each solid in two halves of ${half} mol, the first with the pH${version === 'A' ? ' and Eh' : ''} free, the second with`,
      `# ${version === 'A' ? 'them' : 'it'} held: PHREEQC finds the held pH more surely from near it.`];
    // Each element's total, as -totals heads it; none where the pH is not held, so that the run is not taken for the lowest.
    const out = ['SELECTED_OUTPUT 1', ' -reset false', ' -pH true', ' -pe true', ' -ionic_strength true', ' -totals Fe',
      'USER_PUNCH 1', ` -headings ${els.map((el) => `${el}(mol/kgw)`).join(' ')}`,
      ` 10 IF ABS(-LA("H+") - ${c('pH')}) > ${PH_HELD} THEN END    # the pH not held: no totals`,
      ` 20 PUNCH ${els.map((el) => `TOT("${el}")`).join(', ')}`];
    if (version === 'A') {
      lines.push('SOLUTION 1', ...water, 'SAVE solution 1', 'END', ...halves, 'USE solution 1', 'EQUILIBRIUM_PHASES 2', ` {solid} 0 ${half}`,
        'SAVE solution 2', 'END',
        'USE solution 2', 'EQUILIBRIUM_PHASES 3', ...hold, ` Fix_Eh ${c('Eh')} H2 10    # the Eh held, with hydrogen`, ` {solid} 0 ${half}`,
        ...out, 'END');
    } else {
      lines.push('SOLUTION 1', ...water,
        'EQUILIBRIUM_PHASES 1', ' Goethite 0 10', ' Magnetite 0 10', ...hold, ' Fix_HCO3- -6 CO2 10    # the free HCO3- held, with CO2',
        'SAVE solution 1', 'END', ...halves,
        'USE solution 1', 'EQUILIBRIUM_PHASES 2', ' Goethite 0 10', ' Magnetite 0 10', ` {solid} 0 ${half}`,
        'SAVE solution 2', 'END',
        'USE solution 2', 'EQUILIBRIUM_PHASES 3', ' Goethite 0 10', ' Magnetite 0 10', ...hold, ` {solid} 0 ${half}`,
        ...out, 'END');
    }
    return lines.join('\n');
  }

  /**
    The Simple Functions' reference waters (TR-10-61 table A-1, SFData.TR1061_WATERS) as a table's rows: the names
    first, as the Simple Functions name the columns; a value it does not give left empty.
  */
  function referenceRows(waters) {
    const head = ['Water', 'pH', 'Eh (mV)', 'I (m)', '[HCO3-] (m)', '[SO4-2]tot (m)', '[Cl]tot (m)', '[Ca]tot (m)', '[Mg]tot (m)',
      '[Na]tot (m)', '[K]tot (m)', '[Fe]tot (m)', '[Si]tot (m)'];
    const keys = ['id', 'pH', 'Eh', 'I', 'HCO3', 'SO4', 'Cl', 'Ca', 'Mg', 'Na', 'K', 'Fe', 'Si'];
    return [head, ...waters.map((w) => keys.map((k) => (k === 'id' ? w.id : Number.isFinite(w[k]) ? w[k] : null)))];
  }

  return { LOGK_O2, DATABASE_NAME, MARK, AMOUNT, PH_HELD, phreeqcFormula, phaseName, readBase, build, database, columnsOf, solidsSpec, uncertainSpec, input,
    referenceRows };
}));
