/* ==========================================================================
   SIMPLEFUNCTIONS.HTML: THE MODEL

   Radionuclide solubility limits by the "Simple Functions" of Grivé et al.
   (SKB TR-10-61): a small speciation scheme per element, activity
   corrections by the Oelkers & Helgeson form of the Davies equation, the
   free ligand concentrations from a handful of major-ion mass balances, and
   for each element the lowest of the solubilities of a few candidate solid
   phases. SKB used it in SR-Site (as Excel with @Risk, SKBdoc 1282962) and
   the PSAR, sampling the equilibrium constants and drawing the groundwater
   from a table of compositions.

   This file is the arithmetic only. It knows nothing of files or of the
   page: it compiles a thermodynamic dataset (see sf-data.js) into a plan,
   evaluates one groundwater at a time, and runs the probabilistic
   calculation. It runs under Node for the tests in resources/tests/
   simplefunctions/ and in the browser, on the page and in sf-worker.js.

   REACTIONS ARE TEXT. Every species and solid is written as a reaction,
   for example "Sr+2 + CO3-2 + H+ = SrHCO3+", and everything the
   calculation needs is derived from it:

     - the activity correction of the constant: logK' = logK° + Σ ν_r q|z_r|
       − Σ ν_p q|z_p| over reactants r and products p, solids excluded. H2O
       and O2(g) count as neutral species, as they do in the workbooks.
     - the ligand dependence of the species (or of the free metal ion in
       equilibrium with a solid): the exponent of [H+], [CO3-2], [SO4-2],
       [Cl-], [Ca+2], [Na+], [Fe+2], pO2 and [H4SiO4].
     - the nuclearity of a complex and the metal count of a solid.

   The SR-Site workbooks wrote the activity term of every constant by hand.
   Three of them disagree with their own reaction (NiCO3:5.5H2O, PaO2OH(aq),
   SmOHCO3(s)), and one ligand exponent (the uranyl dimer
   (UO2)2CO3(OH)3- carries [CO3-2]^3 for its one carbonate). sf-data.js
   keeps the workbook's terms as `qSRSite` and `ligSRSite` so the SR-Site
   numbers are reproduced; the option `reactionTerms` takes every term from
   the reactions instead.

   Conventions of the SR-Site calculation, kept so the answers agree:

     - Concentrations in mol/kg water ("m"). pH is taken as −log[H+] and the
       H+ activity coefficient sits in the conditional constants.
     - [HCO3-] in the input is the FREE hydrogen carbonate; [CO3-2] follows
       from it and the pH. [Ca] stands for Ca + Mg.
     - Version B (the SR-Site setting): the redox state is that of the
       magnetite/goethite boundary, Eh = 0.059/4 ((−4(−logK_mag −
       3(−logK_goe))) + 83.1 − 4 pH) mV with the constants at I = 0, pe =
       Eh/59.16, pO2 = 10^(−83.1 + 4 pH + 4 pe), and [Fe+2] from goethite
       with its constant corrected to the ionic strength.
     - Version A (TR-10-61, section 3.1): Eh and [Fe]tot are inputs, and
       [Fe+2] follows from the iron mass balance over the iron species of
       the major-ion table.
     - Free sulphate is solved together with free calcium and sodium (the
       workbooks iterate the circular reference; here a safeguarded
       Newton on the monotone mass balance).
     - A dimer or trimer of the metal contributes P^n·Eq_n to the total,
       counting the complex once rather than n times, as the workbooks do.
       The option `polyStoichiometry` counts it n times.
   ========================================================================== */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.SFModel = api;
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const LN10 = Math.LN10;

  /* ---------------------------------------------------------------------
     The basis: the ligands the element expressions may depend on
     --------------------------------------------------------------------- */
  // Index order of the ligand vector. 'H' is [H+] = 10^-pH, 'O2' is pO2.
  const LIGANDS = ['H', 'CO3', 'SO4', 'Cl', 'Ca', 'Na', 'Fe', 'O2', 'Si'];
  const LIG = Object.fromEntries(LIGANDS.map((k, i) => [k, i]));
  const LIGAND_LABEL = {
    H: '[H+]', CO3: '[CO3-2]', SO4: '[SO4-2]', Cl: '[Cl-]', Ca: '[Ca+2]', Na: '[Na+]',
    Fe: '[Fe+2]', O2: 'pO2(g)', Si: '[H4SiO4]',
  };
  // Species of the basis as they are written in reactions. The value is the
  // ligand key, or null for water (activity one, but its activity
  // coefficient term q0 still enters the correction, as in the workbooks).
  const BASIS = {
    'H+': 'H', 'H2O': null, 'O2(g)': 'O2', 'O2': 'O2', 'CO3-2': 'CO3', 'SO4-2': 'SO4',
    'Cl-': 'Cl', 'Ca+2': 'Ca', 'Na+': 'Na', 'Fe+2': 'Fe', 'H4SiO4': 'Si', 'Si(OH)4': 'Si',
  };

  /* ---------------------------------------------------------------------
     Formulas, charges and element balances
     --------------------------------------------------------------------- */
  const PHASE_SUFFIX = /\((aq|g|s|cr|c|am|l|sol|am,\s*fresh|am,\s*aged|am, aged|am,fresh|am,aged|beta|alpha|nat|cer)\)\s*$/i;

  /**
   * Tidy a written formula: "PdCl4 -2" → "PdCl4-2". The charge is always
   * written sign first ("Th+4", "SO4-2", "Fe(OH)4-"); the chemists' "Th4+"
   * is NOT read, because "Fe(OH)4-" would then be taken for a charge of −4.
   */
  function normaliseFormula(s) {
    return String(s).trim().replace(/\s+(?=[+-]\d*$)/, '');
  }

  /** The phase tag at the end of a formula, if any ("(s)", "(aq)", "(am,aged)"). */
  function phaseOf(formula) {
    const m = PHASE_SUFFIX.exec(formula);
    return m ? m[1].toLowerCase().replace(/\s+/g, '') : '';
  }

  function stripPhase(formula) {
    let f = formula;
    for (let i = 0; i < 3; i++) {
      const g = f.replace(PHASE_SUFFIX, '');
      if (g === f) break;
      f = g;
    }
    return f;
  }

  /** Charge of a species from its written formula: "UO2(CO3)3-4" → −4, "SrCO3(aq)" → 0. */
  function chargeOf(formula) {
    const f = stripPhase(normaliseFormula(formula));
    if (f === 'e-') return -1;
    const m = /([+-])(\d*)$/.exec(f);
    if (!m) return 0;
    const n = m[2] === '' ? 1 : parseInt(m[2], 10);
    return m[1] === '+' ? n : -n;
  }

  /**
   * Element counts of a formula, for the balance check. Understands brackets,
   * decimal subscripts (Fe1.04Se), and hydrate dots or colons ("·2H2O",
   * ":5.5H2O"). The phase tag and the charge are dropped.
   */
  function elementCounts(formula) {
    let f = stripPhase(normaliseFormula(formula)).replace(/[+-]\d*$/, '');
    const parts = f.split(/[·:*•]/);
    const total = {};
    for (let i = 0; i < parts.length; i++) {
      let p = parts[i].trim();
      if (!p) continue;
      let mult = 1;
      if (i > 0) {
        const m = /^(\d*\.?\d+)(.*)$/.exec(p);
        if (m) { mult = parseFloat(m[1]); p = m[2]; }
      }
      const c = parseGroup(p.replace(/\[/g, '(').replace(/\]/g, ')'));
      for (const [el, n] of Object.entries(c)) total[el] = (total[el] || 0) + n * mult;
    }
    return total;
  }

  function parseGroup(s) {
    let i = 0;
    function num() {
      const m = /^\d*\.?\d+/.exec(s.slice(i));
      if (!m) return 1;
      i += m[0].length;
      return parseFloat(m[0]);
    }
    function group() {
      const out = {};
      while (i < s.length) {
        const ch = s[i];
        if (ch === '(') {
          i++;
          const inner = group();
          if (s[i] !== ')') throw new Error(`unbalanced bracket in "${s}"`);
          i++;
          const k = num();
          for (const [el, n] of Object.entries(inner)) out[el] = (out[el] || 0) + n * k;
        } else if (ch === ')') {
          break;
        } else if (/[A-Z]/.test(ch)) {
          let el = ch; i++;
          while (i < s.length && /[a-z]/.test(s[i])) { el += s[i]; i++; }
          const k = num();
          out[el] = (out[el] || 0) + k;
        } else {
          throw new Error(`cannot read "${ch}" in "${s}"`);
        }
      }
      return out;
    }
    return group();
  }

  /* ---------------------------------------------------------------------
     Reactions
     --------------------------------------------------------------------- */
  /** "0.25 O2(g)" → {coef: 0.25, formula: 'O2(g)'}. Terms are separated by " + ". */
  function parseTerm(t) {
    const s = t.trim();
    const m = /^(\d*\.?\d+)\s*(?=[A-Z(\[])(.+)$/.exec(s);
    if (m) return { coef: parseFloat(m[1]), formula: normaliseFormula(m[2]) };
    return { coef: 1, formula: normaliseFormula(s) };
  }

  function parseSide(side) {
    const s = side.trim();
    if (!s) return [];
    // Split on " + " with the spaces, so the "+" of "H+" or "Ca+2" stays put.
    return s.split(/\s+\+\s+/).map(parseTerm);
  }

  function parseReaction(text) {
    const s = String(text || '').replace(/→|⇌|<=>|=>/g, '=');
    const parts = s.split('=');
    if (parts.length !== 2) throw new Error(`a reaction needs exactly one "=": "${text}"`);
    return { left: parseSide(parts[0]), right: parseSide(parts[1]) };
  }

  /** Charge and element balance of a parsed reaction; returns [] when it balances. */
  function balanceIssues(rx) {
    const issues = [];
    let charge = 0;
    const els = {};
    const add = (terms, sign) => {
      for (const t of terms) {
        charge += sign * t.coef * chargeOf(t.formula);
        let c;
        try { c = elementCounts(t.formula); } catch (e) { issues.push(e.message); continue; }
        for (const [el, n] of Object.entries(c)) els[el] = (els[el] || 0) + sign * t.coef * n;
      }
    };
    add(rx.left, 1);
    add(rx.right, -1);
    if (Math.abs(charge) > 1e-9) issues.push(`charge does not balance (${fmtNum(charge)})`);
    const bad = Object.entries(els).filter(([, n]) => Math.abs(n) > 1e-9);
    if (bad.length) issues.push(`elements do not balance: ${bad.map(([el, n]) => `${el} ${n > 0 ? '+' : ''}${fmtNum(n)}`).join(', ')}`);
    return issues;
  }

  function fmtNum(x) { return String(Math.round(x * 1e6) / 1e6); }

  /** Activity-correction coefficients q0..q6 of a reaction, solids excluded. */
  function activityTerm(rx, isSolid) {
    const q = [0, 0, 0, 0, 0, 0, 0];
    const acc = (terms, sign) => {
      for (const t of terms) {
        if (isSolid(t.formula)) continue;
        const z = Math.abs(chargeOf(t.formula));
        if (z > 6) throw new Error(`charge ${z} of ${t.formula} is beyond the correction table (6)`);
        q[z] += sign * t.coef;
      }
    };
    acc(rx.left, 1);
    acc(rx.right, -1);
    return q.map((v) => Math.round(v * 1e9) / 1e9);
  }

  /**
   * Compile an aqueous species of an element: the reaction must have the
   * master species on the left and the species on the right; everything
   * else must be in the basis. Returns {q, lig[9], n}.
   */
  function compileSpecies(sp, master) {
    const rx = parseReaction(sp.rx);
    const lig = new Array(LIGANDS.length).fill(0);
    let n = 0;
    let product = null;
    const notBasis = [];
    for (const t of rx.left) {
      if (t.formula === master) { n += t.coef; continue; }
      if (t.formula in BASIS) { const k = BASIS[t.formula]; if (k) lig[LIG[k]] += t.coef; continue; }
      notBasis.push(t.formula);
    }
    for (const t of rx.right) {
      if (t.formula in BASIS) { const k = BASIS[t.formula]; if (k) lig[LIG[k]] -= t.coef; continue; }
      if (t.formula === master) { notBasis.push(t.formula); continue; }
      if (product) notBasis.push(t.formula); else { product = t; }
    }
    if (!n) throw new Error(`${sp.id}: the master species ${master} is not on the left of "${sp.rx}"`);
    if (!product) throw new Error(`${sp.id}: no product species on the right of "${sp.rx}"`);
    if (notBasis.length) throw new Error(`${sp.id}: ${notBasis.join(', ')} is neither ${master} nor a basis species (${Object.keys(BASIS).join(', ')})`);
    if (Math.abs(product.coef - 1) > 1e-12) throw new Error(`${sp.id}: the species should appear once on the right of "${sp.rx}"`);
    const q = activityTerm(rx, () => false);
    return { rx, q, lig, n, product: product.formula, charge: chargeOf(product.formula) };
  }

  /**
   * Compile a solid: the solid on the left, the master species (m times) on
   * the right; P = [master] = (K' Π L^lig)^(1/m).
   */
  function compileSolid(so, master) {
    const rx = parseReaction(so.rx);
    const lig = new Array(LIGANDS.length).fill(0);
    let m = 0;
    let solid = null;
    const notBasis = [];
    for (const t of rx.left) {
      if (t.formula in BASIS) { const k = BASIS[t.formula]; if (k) lig[LIG[k]] += t.coef; continue; }
      if (solid) notBasis.push(t.formula); else solid = t;
    }
    for (const t of rx.right) {
      if (t.formula === master) { m += t.coef; continue; }
      if (t.formula in BASIS) { const k = BASIS[t.formula]; if (k) lig[LIG[k]] -= t.coef; continue; }
      notBasis.push(t.formula);
    }
    if (!solid) throw new Error(`${so.id}: no solid on the left of "${so.rx}"`);
    if (!m) throw new Error(`${so.id}: the master species ${master} is not on the right of "${so.rx}"`);
    if (notBasis.length) throw new Error(`${so.id}: ${notBasis.join(', ')} is neither ${master} nor a basis species`);
    const q = activityTerm(rx, (f) => f === solid.formula);
    return { rx, q, lig, m, solid: solid.formula };
  }

  /* ---------------------------------------------------------------------
     The major-ion table. The roles are fixed; the constants are data.
     --------------------------------------------------------------------- */
  const MAJOR_IDS = ['CaOH+', 'FeOH+', 'Fe(OH)3(aq)', 'Fe(OH)4-', 'Calcite', 'HCO3-', 'CaCO3(aq)',
    'CaHCO3+', 'NaCO3-', 'NaHCO3(aq)', 'FeCO3(aq)', 'FeHCO3+', 'Magnetite', 'Goethite', 'HSO4-',
    'CaSO4(aq)', 'NaSO4-', 'FeHSO4+', 'FeSO4(aq)', 'FeCl+'];
  const SOLID_MAJORS = new Set(['Calcite', 'Magnetite', 'Goethite']);

  /* ---------------------------------------------------------------------
     Compiling a dataset into a plan
     --------------------------------------------------------------------- */
  const DEFAULT_OPTIONS = {
    version: 'B',               // 'B': magnetite/goethite (SR-Site); 'A': Eh and [Fe]tot from the water
    reactionTerms: false,       // take every term from the reactions, dropping the workbooks' hand-written ones
    polyStoichiometry: false,   // count a dimer twice and a trimer three times in the total
    singleRaOH: false,          // sample Ra(OH)+ once (the workbooks nest three normals)
    ehFactor: 0.059,            // the workbooks' 0.059 in the magnetite/goethite Eh; 0.05916 is RT ln10/F
    analogueDraws: false,       // an element with `analogue` (Cm → Am) draws its constants with the analogue's numbers
    limit: 0.01,                // "No solubility limited" above this, mol/kg (flag only)
  };

  /** The workbook's ligand exponents where it wrote them by hand ({CO3: 3}). */
  function srsiteLigands(lig, over, opt) {
    if (!over || opt.reactionTerms) return lig;
    const out = lig.slice();
    for (const [k, v] of Object.entries(over)) {
      if (!(k in LIG)) throw new Error(`unknown ligand ${k} in ligSRSite`);
      out[LIG[k]] = v;
    }
    return out;
  }

  /**
   * Compile a dataset {major:[], elements:[]} into flat arrays. Every
   * sampled constant gets an index into one parameter vector; the plan says
   * which vector entry each species and solid reads.
   */
  function compile(data, options = {}) {
    const opt = { ...DEFAULT_OPTIONS, ...options };
    const params = [];   // {key, group, id, logK, dlogK, depth, sampled}
    const issues = [];   // {where, message, severity}
    const addParam = (p) => { params.push(p); return params.length - 1; };

    // Major ions
    const major = {};
    const majorById = Object.fromEntries((data.major || []).map((s) => [s.id, s]));
    for (const id of MAJOR_IDS) {
      const s = majorById[id];
      if (!s) throw new Error(`the major-ion table has no ${id}`);
      const rx = parseReaction(s.rx);
      let q = activityTerm(rx, (f) => SOLID_MAJORS.has(id) && !(f in BASIS) && chargeOf(f) === 0 && /[(]s[)]$/.test(f));
      const qDerived = q;
      if (s.qSRSite && !opt.reactionTerms) q = s.qSRSite.slice();
      const bal = balanceIssues(rx);
      if (bal.length) issues.push({ where: `major ${id}`, message: bal.join('; '), severity: 'warn' });
      const sampled = !s.fixed && s.dlogK > 0;
      const index = addParam({ key: `major:${id}`, group: 'Major ions', id, logK: s.logK, dlogK: s.dlogK || 0, depth: 1, sampled, rx: s.rx });
      major[id] = { index, q, qDerived, logK0: s.logK, rx: s.rx };
    }

    // Elements
    const elements = [];
    for (const e of data.elements || []) {
      const species = [];
      const solids = [];
      for (const sp of e.species || []) {
        if (sp.off) continue;
        let c;
        try { c = compileSpecies(sp, e.master); } catch (err) { issues.push({ where: `${e.el} ${sp.id}`, message: err.message, severity: 'error' }); continue; }
        const bal = balanceIssues(c.rx);
        if (bal.length) issues.push({ where: `${e.el} ${sp.id}`, message: bal.join('; '), severity: 'warn' });
        let q = c.q;
        if (sp.qSRSite && !opt.reactionTerms) q = sp.qSRSite.slice();
        const lig = srsiteLigands(c.lig, sp.ligSRSite, opt);
        const depth = opt.singleRaOH ? 1 : (sp.depth || 1);
        const index = addParam({ key: `${e.el}:${sp.id}`, group: e.el, id: sp.id, logK: sp.logK, dlogK: sp.dlogK || 0, depth, sampled: (sp.dlogK || 0) > 0, rx: sp.rx });
        species.push({ id: sp.id, index, q, qDerived: c.q, lig, ligDerived: c.lig, n: c.n, charge: c.charge, rx: sp.rx,
          override: !opt.reactionTerms && !!(sp.qSRSite || sp.ligSRSite) });
      }
      for (const so of e.solids || []) {
        if (so.off) continue;
        let c;
        try { c = compileSolid(so, e.master); } catch (err) { issues.push({ where: `${e.el} ${so.id}`, message: err.message, severity: 'error' }); continue; }
        const bal = balanceIssues(c.rx);
        if (bal.length) issues.push({ where: `${e.el} ${so.id}`, message: bal.join('; '), severity: 'warn' });
        let q = c.q;
        if (so.qSRSite && !opt.reactionTerms) q = so.qSRSite.slice();
        const lig = srsiteLigands(c.lig, so.ligSRSite, opt);
        const index = addParam({ key: `${e.el}:${so.id}`, group: e.el, id: so.id, logK: so.logK, dlogK: so.dlogK || 0, depth: 1, sampled: (so.dlogK || 0) > 0, rx: so.rx });
        solids.push({ id: so.id, index, q, qDerived: c.q, lig, ligDerived: c.lig, m: c.m, use: so.use !== false, rx: so.rx,
          override: !opt.reactionTerms && !!(so.qSRSite || so.ligSRSite) });
      }
      // The analogue's draws: the entry of the analogue element whose
      // reaction reads the same with the element's symbol put back.
      if (e.analogue) {
        const A = (data.elements || []).find((x) => x.el === e.analogue);
        if (A) {
          const swap = (rx) => rx.split(e.el).join(A.el);
          for (const list of [species, solids]) {
            for (const s of list) {
              const twin = [...(A.species || []), ...(A.solids || [])].find((t) => !t.off && t.rx === swap(s.rx));
              if (twin) params[s.index].analogueKey = `${A.el}:${twin.id}`;
            }
          }
        }
      }
      const nmax = species.reduce((a, s) => Math.max(a, s.n), 1);
      elements.push({ el: e.el, name: e.name || e.el, master: e.master, analogue: e.analogue || '', species, solids, nmax, used: solids.filter((s) => s.use).length });
      if (!solids.some((s) => s.use)) issues.push({ where: e.el, message: 'no solid phase is used in the minimum', severity: 'error' });
    }

    const nominal = new Float64Array(params.length);
    const sigma = new Float64Array(params.length);
    params.forEach((p, i) => {
      nominal[i] = p.logK;
      // The workbooks sample N(logK, ΔlogK/2); Ra(OH)+ nests three such
      // normals, which is one normal with the variance three times over.
      sigma[i] = p.sampled ? (p.dlogK / 2) * Math.sqrt(p.depth || 1) : 0;
    });
    return { options: opt, params, nominal, sigma, major, elements, issues, label: data.label || '' };
  }

  /* ---------------------------------------------------------------------
     Activity coefficients (Oelkers & Helgeson 1990, TR-10-61 equation 2)
     --------------------------------------------------------------------- */
  function activityCorrections(I) {
    const s = Math.sqrt(I);
    const D = 0.5091 * s / (1 + 1.5 * s);
    const G = -Math.log10(1 + 0.0180153 * I);
    const b = 0.064 * I;
    const q = new Float64Array(7);
    for (let z = 0; z < 7; z++) q[z] = -z * z * D + G + b;
    return q;
  }

  function corrected(logK, qc, q) {
    let v = logK;
    for (let z = 0; z < 7; z++) if (qc[z]) v += qc[z] * q[z];
    return v;
  }

  /* ---------------------------------------------------------------------
     The groundwater: free ligands and redox state
     --------------------------------------------------------------------- */
  /**
   * water: {pH, I, HCO3, SO4, Cl, Ca, Na, Si, Eh?, Fe?} (mol/kg, mV)
   * K: the parameter vector (logK° of every constant, sampled or nominal)
   * Returns the free ligands in the order of LIGANDS plus the diagnostics.
   */
  function groundwater(plan, water, K, out) {
    const opt = plan.options;
    const M = plan.major;
    const q = activityCorrections(water.I);
    const kc = (id) => corrected(K[M[id].index], M[id].q, q);
    const pH = water.pH;
    const H = Math.pow(10, -pH);

    let Eh, pe, logPO2;
    if (opt.version === 'A') {
      if (!Number.isFinite(water.Eh)) throw new Error('Version A needs Eh (mV) for every water');
      Eh = water.Eh;
      pe = Eh / 59.16;
      logPO2 = -83.1 + 4 * pH + 4 * pe;
    } else {
      // The workbooks put the magnetite and goethite constants at I = 0 here
      // (DON'T TOUCH!D33, D34), and the ionic-strength corrected goethite
      // constant into [Fe+2] below.
      const kMag0 = K[M.Magnetite.index];
      const kGoe0 = K[M.Goethite.index];
      Eh = opt.ehFactor / 4 * ((-4 * (-kMag0 - 3 * (-kGoe0))) + 83.1 - 4 * pH) * 1000;
      pe = Eh / 59.16;
      logPO2 = -83.1 + 4 * pH + 4 * pe;
    }
    const pO2 = Math.pow(10, logPO2);

    const kHCO3 = Math.pow(10, kc('HCO3-'));
    const CO3 = water.HCO3 / kHCO3 / H;

    const kCaOH = Math.pow(10, kc('CaOH+'));
    const kCaCO3 = Math.pow(10, kc('CaCO3(aq)'));
    const kCaHCO3 = Math.pow(10, kc('CaHCO3+'));
    const kCaSO4 = Math.pow(10, kc('CaSO4(aq)'));
    const kNaCO3 = Math.pow(10, kc('NaCO3-'));
    const kNaHCO3 = Math.pow(10, kc('NaHCO3(aq)'));
    const kNaSO4 = Math.pow(10, kc('NaSO4-'));
    const kHSO4 = Math.pow(10, kc('HSO4-'));
    const kFeSO4 = Math.pow(10, kc('FeSO4(aq)'));
    const kFeHSO4 = Math.pow(10, kc('FeHSO4+'));
    const kFeCl = Math.pow(10, kc('FeCl+'));
    const aCa = 1 + kCaOH / H + kCaCO3 * CO3 + kCaHCO3 * CO3 * H;
    const aNa = 1 + kNaCO3 * CO3 + kNaHCO3 * CO3 * H;

    let Fe, Cl;
    let feSolve = null;
    if (opt.version === 'A') {
      if (!(water.Fe > 0)) throw new Error('Version A needs [Fe]tot (mol/kg) for every water');
      // Fe(II) with its hydrolysis, carbonate and sulphate complexes and the
      // two Fe(III) hydroxides, which depend on pO2.
      const kFeOH = Math.pow(10, kc('FeOH+'));
      const kFeOH3 = Math.pow(10, kc('Fe(OH)3(aq)'));
      const kFeOH4 = Math.pow(10, kc('Fe(OH)4-'));
      const kFeCO3 = Math.pow(10, kc('FeCO3(aq)'));
      const kFeHCO3 = Math.pow(10, kc('FeHCO3+'));
      const o = Math.pow(pO2, 0.25);
      const aFe0 = 1 + kFeOH / H + kFeOH3 * o / (H * H) + kFeOH4 * o / (H * H * H) + kFeCO3 * CO3 + kFeHCO3 * CO3 * H;
      feSolve = { aFe0, kFeSO4, kFeHSO4, kFeCl };
    } else {
      Fe = Math.pow(10, -kc('Goethite') - 2 * pH - 0.25 * logPO2);
      Cl = water.Cl / (1 + kFeCl * Fe);
    }

    // Free sulphate. F(s) is strictly increasing, F(0) = −SO4tot < 0 and
    // F(SO4tot) ≥ 0, so a Newton step kept inside the bracket always converges.
    const S = water.SO4;
    const H1 = 1 + kHSO4 * H;
    const feCl = (s) => {
      if (!feSolve) return { Fe, Cl };
      // [Fe] = Fetot / (a + b s + kFeCl [Cl]) and [Cl] = Cltot / (1 + kFeCl [Fe]):
      // the positive root of the quadratic in [Fe].
      const a = feSolve.aFe0 + (feSolve.kFeSO4 + feSolve.kFeHSO4 * H) * s;
      const k = feSolve.kFeCl;
      const Ft = water.Fe, Ct = water.Cl;
      // a k F² + (a + k Ct − k Ft) F − Ft = 0
      const A = a * k, B = a + k * Ct - k * Ft, C = -Ft;
      let f;
      if (A === 0) f = Ft / a;
      else {
        const disc = B * B - 4 * A * C;
        f = B > 0 ? (2 * -C) / (B + Math.sqrt(disc)) : (-B + Math.sqrt(disc)) / (2 * A);
      }
      return { Fe: f, Cl: Ct / (1 + k * f) };
    };
    const F = (s) => {
      const fc = feCl(s);
      const ca = water.Ca / (aCa + kCaSO4 * s);
      const na = water.Na / (aNa + kNaSO4 * s);
      return s * (H1 + kCaSO4 * ca + kNaSO4 * na + (kFeSO4 + kFeHSO4 * H) * fc.Fe) - S;
    };
    let SO4 = 0;
    let iterations = 0;
    if (S > 0) {
      let lo = 0, hi = S;
      // The workbooks' first guess: Ca and Na of 0.1 m.
      let s = S / (H1 + kCaSO4 * 0.1 + kNaSO4 * 0.1 + (kFeSO4 + kFeHSO4 * H) * (Fe || 0));
      if (!(s > lo && s < hi)) s = 0.5 * S;
      for (iterations = 1; iterations <= 200; iterations++) {
        const f = F(s);
        if (f > 0) hi = s; else lo = s;
        const h = Math.max(s * 1e-7, 1e-300);
        const d = (F(s + h) - f) / h;
        let next = s - f / d;
        if (!(next > lo && next < hi) || !Number.isFinite(next)) next = 0.5 * (lo + hi);
        if (Math.abs(next - s) <= 1e-15 * Math.max(s, 1e-300) || hi - lo <= 1e-15 * hi) { s = next; break; }
        s = next;
      }
      SO4 = s;
    }
    const fc = feCl(SO4);
    Fe = fc.Fe;
    Cl = fc.Cl;
    const Ca = water.Ca / (aCa + kCaSO4 * SO4);
    const Na = water.Na / (aNa + kNaSO4 * SO4);
    const siCalcite = Math.log10(CO3 * Ca / Math.pow(10, -kc('Calcite')));

    const lig = out || new Float64Array(LIGANDS.length);
    lig[LIG.H] = H;
    lig[LIG.CO3] = CO3;
    lig[LIG.SO4] = SO4;
    lig[LIG.Cl] = Cl;
    lig[LIG.Ca] = Ca;
    lig[LIG.Na] = Na;
    lig[LIG.Fe] = Fe;
    lig[LIG.O2] = pO2;
    lig[LIG.Si] = water.Si;
    return { lig, q, Eh, pe, logPO2, siCalcite, iterations };
  }

  /* ---------------------------------------------------------------------
     One element in one groundwater
     --------------------------------------------------------------------- */
  const scratch = { logL: new Float64Array(LIGANDS.length), eq: new Float64Array(8) };

  function logLigands(lig, logL) {
    for (let i = 0; i < LIGANDS.length; i++) logL[i] = lig[i] > 0 ? Math.log10(lig[i]) : -Infinity;
    return logL;
  }

  function dotLig(p, logL) {
    let v = 0;
    for (let i = 0; i < p.length; i++) if (p[i]) v += p[i] * logL[i];
    return v;
  }

  /**
   * Solubility of every solid of an element; returns the index of the
   * controlling one and fills `sol` (mol/kg, one per solid).
   */
  function evaluateElement(plan, E, K, q, logL, sol, detail) {
    const eq = scratch.eq;
    eq.fill(0);
    eq[1] = 1;
    const polyN = plan.options.polyStoichiometry;
    const specTerms = detail ? new Float64Array(E.species.length) : null;
    for (let j = 0; j < E.species.length; j++) {
      const s = E.species[j];
      const lt = corrected(K[s.index], s.q, q) + dotLig(s.lig, logL);
      const v = Math.pow(10, lt);
      eq[s.n] += v;
      if (specTerms) specTerms[j] = lt;
    }
    let best = -1;
    let bestS = Infinity;
    for (let k = 0; k < E.solids.length; k++) {
      const so = E.solids[k];
      const logP = (corrected(K[so.index], so.q, q) + dotLig(so.lig, logL)) / so.m;
      let S = 0;
      for (let n = 1; n <= E.nmax; n++) {
        if (!eq[n]) continue;
        S += (polyN ? n : 1) * Math.pow(10, n * logP) * eq[n];
      }
      sol[k] = S;
      if (so.use && S < bestS) { bestS = S; best = k; }
    }
    if (detail) {
      detail.specTerms = specTerms;
      detail.eq = Array.from(eq.slice(0, E.nmax + 1));
    }
    return best;
  }

  /**
   * Everything about one groundwater at one parameter vector: ligands and
   * every element's solid solubilities, the controlling solid, and (when
   * asked) the aqueous speciation at the controlling solid.
   */
  function evaluateWater(plan, water, K, wantSpeciation) {
    const K2 = K || plan.nominal;
    const gw = groundwater(plan, water, K2);
    const logL = logLigands(gw.lig, new Float64Array(LIGANDS.length));
    const elements = plan.elements.map((E) => {
      const sol = new Float64Array(E.solids.length);
      const detail = wantSpeciation ? {} : null;
      const best = evaluateElement(plan, E, K2, gw.q, logL, sol, detail);
      const res = { el: E.el, S: best >= 0 ? sol[best] : NaN, control: best, solids: Array.from(sol) };
      if (detail && best >= 0) {
        // Species concentrations at the controlling solid's free-ion level.
        const so = E.solids[best];
        const logP = (corrected(K2[so.index], so.q, gw.q) + dotLig(so.lig, logL)) / so.m;
        const polyN = plan.options.polyStoichiometry;
        const rows = [{ id: E.master, n: 1, conc: Math.pow(10, logP) }];
        E.species.forEach((s, j) => rows.push({ id: s.id, n: s.n, conc: Math.pow(10, s.n * logP + detail.specTerms[j]) }));
        const total = rows.reduce((a, r) => a + (polyN ? r.n : 1) * r.conc, 0);
        rows.forEach((r) => { r.frac = (polyN ? r.n : 1) * r.conc / total; });
        res.speciation = rows;
      }
      return res;
    });
    return { gw, elements };
  }

  /* ---------------------------------------------------------------------
     Random numbers: seeded, reproducible, one stream per parameter
     --------------------------------------------------------------------- */
  /** sfc32 from four 32-bit words; 53-bit doubles from two outputs. */
  function makeRng(seedWords) {
    let [a, b, c, d] = seedWords.map((x) => x >>> 0);
    function next32() {
      a >>>= 0; b >>>= 0; c >>>= 0; d >>>= 0;
      const t = (a + b) | 0;
      a = b ^ (b >>> 9);
      b = (c + (c << 3)) | 0;
      c = (c << 21) | (c >>> 11);
      d = (d + 1) | 0;
      const r = (t + d) | 0;
      c = (c + r) | 0;
      return r >>> 0;
    }
    for (let i = 0; i < 15; i++) next32();
    return {
      next32,
      /** Uniform on (0, 1), never 0 or 1. */
      uniform() {
        const hi = next32() >>> 5, lo = next32() >>> 6;
        return (hi * 67108864 + lo + 0.5) / 9007199254740992;
      },
    };
  }

  /** A stable 128-bit seed for a named stream: the run seed hashed with the name. */
  function streamSeed(seed, name) {
    // cyrb128
    let h1 = 1779033703, h2 = 3144134277, h3 = 1013904242, h4 = 2773480762;
    const str = `${seed}|${name}`;
    for (let i = 0; i < str.length; i++) {
      const k = str.charCodeAt(i);
      h1 = h2 ^ Math.imul(h1 ^ k, 597399067);
      h2 = h3 ^ Math.imul(h2 ^ k, 2869860233);
      h3 = h4 ^ Math.imul(h3 ^ k, 951274213);
      h4 = h1 ^ Math.imul(h4 ^ k, 2716044179);
    }
    h1 = Math.imul(h3 ^ (h1 >>> 18), 597399067);
    h2 = Math.imul(h4 ^ (h2 >>> 22), 2869860233);
    h3 = Math.imul(h1 ^ (h3 >>> 17), 951274213);
    h4 = Math.imul(h2 ^ (h4 >>> 19), 2716044179);
    h1 ^= (h2 ^ h3 ^ h4); h2 ^= h1; h3 ^= h1; h4 ^= h1;
    return [h1 >>> 0, h2 >>> 0, h3 >>> 0, h4 >>> 0];
  }

  /** n uniforms, stratified (Latin hypercube, one column) or plain. */
  function uniforms(rng, n, lhs) {
    const u = new Float64Array(n);
    if (!lhs) { for (let i = 0; i < n; i++) u[i] = rng.uniform(); return u; }
    const perm = new Int32Array(n);
    for (let i = 0; i < n; i++) perm[i] = i;
    for (let i = n - 1; i > 0; i--) {
      const j = Math.floor(rng.uniform() * (i + 1));
      const t = perm[i]; perm[i] = perm[j]; perm[j] = t;
    }
    for (let i = 0; i < n; i++) u[i] = (perm[i] + rng.uniform()) / n;
    return u;
  }

  /**
   * The inverse of the standard normal distribution: Wichura's AS 241
   * (PPND16), accurate to about 1e-16 over the whole range.
   */
  function normInv(p) {
    if (!(p > 0 && p < 1)) return p === 0 ? -Infinity : p === 1 ? Infinity : NaN;
    const q = p - 0.5;
    if (Math.abs(q) <= 0.425) {
      const r = 0.180625 - q * q;
      return q * (((((((r * 2509.0809287301226727 + 33430.575583588128105) * r + 67265.770927008700853) * r
        + 45921.953931549871457) * r + 13731.693765509461125) * r + 1971.5909503065514427) * r + 133.14166789178437745) * r
        + 3.387132872796366608)
        / (((((((r * 5226.495278852545925 + 28729.085735721942674) * r + 39307.89580009271061) * r
        + 21213.794301586595867) * r + 5394.1960214247511077) * r + 687.1870074920579083) * r + 42.313330701600911252) * r + 1);
    }
    let r = q < 0 ? p : 1 - p;
    r = Math.sqrt(-Math.log(r));
    let v;
    if (r <= 5) {
      r -= 1.6;
      v = (((((((r * 7.7454501427834140764e-4 + 0.0227238449892691845833) * r + 0.24178072517745061177) * r
        + 1.27045825245236838258) * r + 3.64784832476320460504) * r + 5.7694972214606914055) * r + 4.6303378461565452959) * r
        + 1.42343711074968357734)
        / (((((((r * 1.05075007164441684324e-9 + 5.475938084995344946e-4) * r + 0.0151986665636164571966) * r
        + 0.14810397642748007459) * r + 0.68976733498510000455) * r + 1.6763848301838038494) * r + 2.05319162663775882187) * r + 1);
    } else {
      r -= 5;
      v = (((((((r * 2.01033439929228813265e-7 + 2.71155556874348757815e-5) * r + 0.0012426609473880784386) * r
        + 0.026532189526576123093) * r + 0.29656057182850489123) * r + 1.7848265399172913358) * r + 5.4637849111641143699) * r
        + 6.6579046435011037772)
        / (((((((r * 2.04426310338993978564e-15 + 1.4215117583164458887e-7) * r + 1.8463183175100546818e-5) * r
        + 7.868691311456132591e-4) * r + 0.0148753612908506148525) * r + 0.13692988092273580531) * r + 0.59983220655588793769) * r + 1);
    }
    return q < 0 ? -v : v;
  }

  /* ---------------------------------------------------------------------
     The probabilistic calculation
     --------------------------------------------------------------------- */
  const DEFAULT_RUN = {
    n: 6916,            // realisations; the SR-Site and PSAR number
    seed: 1,
    lhs: true,          // Latin hypercube per parameter, as @Risk
    draw: 'randrep',    // groundwater: 'randrep' | 'randnorep' | 'inorder' | 'fixed'
    fixedWater: 0,      // the water used with draw 'fixed'
    varyTD: true,       // sample the thermodynamic data
    keepInputs: true,   // keep the sampled constants (for the sensitivity analysis)
    keepSolids: false,  // keep every candidate solid's solubility per realisation (memory: n × solids × 4 bytes)
    maxKeptValues: 6e6, // …but not more than this many numbers
  };

  /** The groundwater index of every realisation. */
  function drawWaters(nWaters, cfg) {
    const n = cfg.n;
    const idx = new Int32Array(n);
    if (cfg.draw === 'fixed') { idx.fill(Math.max(0, Math.min(nWaters - 1, cfg.fixedWater | 0))); return idx; }
    if (cfg.draw === 'inorder') { for (let i = 0; i < n; i++) idx[i] = i % nWaters; return idx; }
    const rng = makeRng(streamSeed(cfg.seed, 'groundwater'));
    if (cfg.draw === 'randnorep') {
      if (n > nWaters) throw new Error(`drawing ${n} realisations without replacement needs at least as many waters (there are ${nWaters})`);
      const perm = new Int32Array(nWaters);
      for (let i = 0; i < nWaters; i++) perm[i] = i;
      for (let i = nWaters - 1; i > 0; i--) {
        const j = Math.floor(rng.uniform() * (i + 1));
        const t = perm[i]; perm[i] = perm[j]; perm[j] = t;
      }
      for (let i = 0; i < n; i++) idx[i] = perm[i];
      return idx;
    }
    // With replacement, as @Risk's RiskIntUniform(1, N): stratified on the
    // index when the hypercube is on.
    const u = uniforms(rng, n, cfg.lhs);
    for (let i = 0; i < n; i++) idx[i] = Math.min(nWaters - 1, Math.floor(u[i] * nWaters));
    return idx;
  }

  /** The sampled logK of every parameter: Float64Array per parameter (or null when fixed). */
  function sampleParams(plan, cfg) {
    const cols = new Array(plan.params.length);
    for (let p = 0; p < plan.params.length; p++) {
      const par = plan.params[p];
      if (!cfg.varyTD || !(plan.sigma[p] > 0)) { cols[p] = null; continue; }
      // With analogue draws, Cm's constants take the random numbers of the Am
      // constants of the same reaction: fully correlated, as data carried
      // over by analogy are.
      const key = plan.options.analogueDraws && par.analogueKey ? par.analogueKey : par.key;
      const rng = makeRng(streamSeed(cfg.seed, key));
      const u = uniforms(rng, cfg.n, cfg.lhs);
      const col = new Float64Array(cfg.n);
      const mu = plan.nominal[p], sd = plan.sigma[p];
      for (let i = 0; i < cfg.n; i++) col[i] = mu + sd * normInv(u[i]);
      cols[p] = col;
    }
    return cols;
  }

  /**
   * The Monte Carlo, in steps: createRunner(...).step(k) evaluates the next k
   * realisations and returns how many are done; result() hands over the
   * arrays once all are. waters: [{pH, I, HCO3, SO4, Cl, Ca, Na, Si, Eh, Fe}].
   * `injected` (tests) replaces the sampled columns: {cols, waterIndex}.
   */
  function createRunner(plan, waters, runCfg = {}, injected) {
    const cfg = { ...DEFAULT_RUN, ...runCfg };
    if (!waters.length) throw new Error('no groundwater to draw from');
    if (!(cfg.n >= 1)) throw new Error('the number of realisations must be at least 1');
    const n = cfg.n;
    const waterIndex = injected && injected.waterIndex ? Int32Array.from(injected.waterIndex) : drawWaters(waters.length, cfg);
    const cols = injected && injected.cols ? injected.cols : sampleParams(plan, cfg);
    const nE = plan.elements.length;
    const S = plan.elements.map(() => new Float64Array(n));
    const control = plan.elements.map(() => new Uint8Array(n));
    const solidS = cfg.keepSolids ? plan.elements.map((E) => E.solids.map(() => new Float32Array(n))) : null;
    const diag = { siCalcite: new Float32Array(n), Eh: new Float32Array(n), Fe: new Float32Array(n), overI: 0, calciteOver: 0, maxSIcalcite: -Infinity, failed: 0, firstError: '' };
    const K = Float64Array.from(plan.nominal);
    const logL = new Float64Array(LIGANDS.length);
    const lig = new Float64Array(LIGANDS.length);
    const sols = plan.elements.map((E) => new Float64Array(E.solids.length));
    let i = 0;
    function step(k) {
      const stop = Math.min(n, i + Math.max(1, k | 0));
      for (; i < stop; i++) {
        for (let p = 0; p < cols.length; p++) if (cols[p]) K[p] = cols[p][i];
        const w = waters[waterIndex[i]];
        let gw;
        try {
          gw = groundwater(plan, w, K, lig);
        } catch (err) {
          diag.failed++;
          if (!diag.firstError) diag.firstError = err.message;
          for (let e = 0; e < nE; e++) { S[e][i] = NaN; control[e][i] = 255; }
          continue;
        }
        logLigands(gw.lig, logL);
        diag.siCalcite[i] = gw.siCalcite;
        diag.Eh[i] = gw.Eh;
        diag.Fe[i] = gw.lig[LIG.Fe];
        if (w.I > 0.2) diag.overI++;
        if (gw.siCalcite > 0) { diag.calciteOver++; if (gw.siCalcite > diag.maxSIcalcite) diag.maxSIcalcite = gw.siCalcite; }
        for (let e = 0; e < nE; e++) {
          const E = plan.elements[e];
          const best = evaluateElement(plan, E, K, gw.q, logL, sols[e], null);
          S[e][i] = best >= 0 ? sols[e][best] : NaN;
          control[e][i] = best >= 0 ? best : 255;
          if (solidS) for (let k2 = 0; k2 < E.solids.length; k2++) solidS[e][k2][i] = sols[e][k2];
        }
      }
      return i;
    }
    function result() {
      let inputs = null;
      if (cfg.keepInputs) {
        const sampled = cols.map((c, p) => (c ? p : -1)).filter((p) => p >= 0);
        const keepN = Math.min(n, Math.floor(cfg.maxKeptValues / Math.max(1, sampled.length)));
        inputs = { index: sampled, n: keepN, values: sampled.map((p) => (keepN === n ? cols[p] : cols[p].slice(0, keepN))) };
      }
      return {
        n, done: i, cfg, waterIndex, S, control, solidS, diag, inputs,
        elements: plan.elements.map((E) => E.el),
      };
    }
    return { n, step, result, get done() { return i; } };
  }

  /** The whole Monte Carlo at once; onProgress(done, total) every 500. */
  function run(plan, waters, runCfg = {}, onProgress, injected) {
    const r = createRunner(plan, waters, runCfg, injected);
    while (r.done < r.n) {
      r.step(500);
      if (onProgress) onProgress(r.done, r.n);
    }
    return r.result();
  }

  /* ---------------------------------------------------------------------
     Deterministic analysis with linearised uncertainty (TR-10-61 §2, step 3)
     --------------------------------------------------------------------- */
  /**
   * The solubility of every element at nominal constants, and its
   * sensitivity to every uncertain constant, by central differences through
   * the whole calculation (the ligand mass balances included). σ_logS² =
   * Σ (∂logS/∂logK_i · σ_i)² with σ_i = ΔlogK_i/2, and fZ_i the share of
   * each term (TR-10-61 equation 13). The derivative is taken with the
   * controlling solid held, as the workbooks do.
   */
  function analyse(plan, water, h = 1e-4) {
    const base = evaluateWater(plan, water, plan.nominal, true);
    const K = Float64Array.from(plan.nominal);
    const nE = plan.elements.length;
    const grads = plan.elements.map(() => new Map());
    const logS0 = base.elements.map((r) => Math.log10(r.S));
    const heldSolid = (res, e) => {
      const k = base.elements[e].control;
      return k >= 0 ? res.elements[e].solids[k] : NaN;
    };
    for (let p = 0; p < plan.params.length; p++) {
      if (!(plan.sigma[p] > 0)) continue;
      const touchesAll = plan.params[p].group === 'Major ions';
      K[p] = plan.nominal[p] + h;
      const up = evaluateWater(plan, water, K, false);
      K[p] = plan.nominal[p] - h;
      const dn = evaluateWater(plan, water, K, false);
      K[p] = plan.nominal[p];
      for (let e = 0; e < nE; e++) {
        if (!touchesAll && plan.params[p].group !== plan.elements[e].el) continue;
        const d = (Math.log10(heldSolid(up, e)) - Math.log10(heldSolid(dn, e))) / (2 * h);
        if (Number.isFinite(d) && Math.abs(d) > 1e-12) grads[e].set(p, d);
      }
    }
    const elements = base.elements.map((r, e) => {
      const terms = [];
      let v = 0;
      for (const [p, d] of grads[e]) {
        const c = d * plan.sigma[p];
        v += c * c;
        terms.push({ param: p, key: plan.params[p].key, id: plan.params[p].id, group: plan.params[p].group, dlogS: d, contrib: c * c });
      }
      terms.sort((a, b) => b.contrib - a.contrib);
      terms.forEach((t) => { t.fZ = v > 0 ? 100 * t.contrib / v : 0; });
      return { ...r, logS: logS0[e], sigma: Math.sqrt(v), terms };
    });
    return { gw: base.gw, elements };
  }

  /* ---------------------------------------------------------------------
     Statistics
     --------------------------------------------------------------------- */
  function sortedFinite(a) {
    const b = [];
    for (let i = 0; i < a.length; i++) if (Number.isFinite(a[i])) b.push(a[i]);
    b.sort((x, y) => x - y);
    return b;
  }

  /** Percentile of sorted data, linear between order statistics (numpy's default). */
  function quantileSorted(s, p) {
    if (!s.length) return NaN;
    const x = (s.length - 1) * p;
    const i = Math.floor(x);
    const f = x - i;
    return i + 1 < s.length ? s[i] + f * (s[i + 1] - s[i]) : s[i];
  }

  function describe(values, log = true) {
    const v = log ? Array.from(values, (x) => (x > 0 ? Math.log10(x) : NaN)) : Array.from(values);
    const s = sortedFinite(v);
    const n = s.length;
    let mean = 0;
    for (const x of s) mean += x;
    mean /= n || 1;
    let m2 = 0;
    for (const x of s) m2 += (x - mean) * (x - mean);
    const sd = n > 1 ? Math.sqrt(m2 / (n - 1)) : 0;
    return {
      n, mean, sd,
      min: s[0], max: s[n - 1],
      p5: quantileSorted(s, 0.05), p25: quantileSorted(s, 0.25), p50: quantileSorted(s, 0.5),
      p75: quantileSorted(s, 0.75), p95: quantileSorted(s, 0.95),
      p1: quantileSorted(s, 0.01), p99: quantileSorted(s, 0.99),
    };
  }

  /** Two-sample Kolmogorov–Smirnov distance and its asymptotic p-value. */
  function ks2(a, b) {
    const x = sortedFinite(a), y = sortedFinite(b);
    const n = x.length, m = y.length;
    if (!n || !m) return { D: NaN, p: NaN };
    let i = 0, j = 0, D = 0;
    while (i < n && j < m) {
      const v = Math.min(x[i], y[j]);
      while (i < n && x[i] <= v) i++;
      while (j < m && y[j] <= v) j++;
      D = Math.max(D, Math.abs(i / n - j / m));
    }
    const en = Math.sqrt(n * m / (n + m));
    const lam = (en + 0.12 + 0.11 / en) * D;
    let p = 0;
    for (let k = 1; k <= 100; k++) {
      const t = 2 * Math.pow(-1, k - 1) * Math.exp(-2 * k * k * lam * lam);
      p += t;
      if (Math.abs(t) < 1e-12) break;
    }
    return { D, p: Math.max(0, Math.min(1, p)) };
  }

  /** Ranks with ties averaged. */
  function ranks(a) {
    const n = a.length;
    const idx = Array.from({ length: n }, (_, i) => i).sort((i, j) => a[i] - a[j]);
    const r = new Float64Array(n);
    let k = 0;
    while (k < n) {
      let l = k;
      while (l + 1 < n && a[idx[l + 1]] === a[idx[k]]) l++;
      const rv = (k + l) / 2 + 1;
      for (let t = k; t <= l; t++) r[idx[t]] = rv;
      k = l + 1;
    }
    return r;
  }

  function pearson(x, y) {
    const n = Math.min(x.length, y.length);
    let mx = 0, my = 0;
    for (let i = 0; i < n; i++) { mx += x[i]; my += y[i]; }
    mx /= n; my /= n;
    let sxy = 0, sxx = 0, syy = 0;
    for (let i = 0; i < n; i++) {
      const dx = x[i] - mx, dy = y[i] - my;
      sxy += dx * dy; sxx += dx * dx; syy += dy * dy;
    }
    return sxx > 0 && syy > 0 ? sxy / Math.sqrt(sxx * syy) : 0;
  }

  /** Spearman rank correlation of every input column with log S of an element. */
  function spearman(inputs, y) {
    const ry = ranks(y);
    return inputs.map((col) => pearson(ranks(col), ry));
  }

  /* ---------------------------------------------------------------------
     Fitted distributions of log10 S: normal, and skew-normal by maximum
     likelihood with the Akaike criterion deciding between them
     --------------------------------------------------------------------- */
  function normCdf(x) {
    // Abramowitz & Stegun 7.1.26 is too coarse for log-likelihoods far in the
    // tail; use erfc by continued fraction / series instead.
    return 0.5 * erfc(-x / Math.SQRT2);
  }

  function erfc(x) {
    const z = Math.abs(x);
    const t = 1 / (1 + 0.5 * z);
    // Numerical Recipes erfc, relative error < 1.2e-7 everywhere.
    const r = t * Math.exp(-z * z - 1.26551223 + t * (1.00002368 + t * (0.37409196 + t * (0.09678418
      + t * (-0.18628806 + t * (0.27886807 + t * (-1.13520398 + t * (1.48851587
      + t * (-0.82215223 + t * 0.17087277)))))))));
    return x >= 0 ? r : 2 - r;
  }

  function logNormCdf(x) {
    if (x > -5) return Math.log(normCdf(x));
    // Asymptotic series for the far lower tail.
    const x2 = x * x;
    return -0.5 * x2 - Math.log(-x) - 0.5 * Math.log(2 * Math.PI) + Math.log(1 - 1 / x2 + 3 / (x2 * x2));
  }

  function fitDistribution(values) {
    const x = sortedFinite(Array.from(values, (v) => (v > 0 ? Math.log10(v) : NaN)));
    const n = x.length;
    if (n < 5) return null;
    let mean = 0;
    for (const v of x) mean += v;
    mean /= n;
    let m2 = 0, m3 = 0;
    for (const v of x) { const d = v - mean; m2 += d * d; m3 += d * d * d; }
    const sd = Math.sqrt(m2 / n);
    const llNormal = -n * (Math.log(sd) + 0.5 * Math.log(2 * Math.PI)) - m2 / (2 * sd * sd);
    const aicNormal = 4 - 2 * llNormal;
    // Skew-normal: start from the method of moments, then Nelder–Mead on
    // (ξ, ln ω, α).
    const g1 = (m3 / n) / Math.pow(sd, 3);
    const gc = Math.max(-0.99, Math.min(0.99, g1));
    const k = Math.pow(Math.abs(gc), 2 / 3);
    let delta = Math.sign(gc) * Math.sqrt((Math.PI / 2) * k / (k + Math.pow((4 - Math.PI) / 2, 2 / 3)));
    delta = Math.max(-0.995, Math.min(0.995, delta));
    const alpha0 = delta / Math.sqrt(1 - delta * delta);
    const omega0 = sd / Math.sqrt(1 - 2 * delta * delta / Math.PI);
    const xi0 = mean - omega0 * delta * Math.sqrt(2 / Math.PI);
    // α is kept below 50 in size (α = 50 tanh(θ/50)): a sample with a sharp
    // edge drives the likelihood towards the half-normal limit α → ∞, and a
    // fitted α of 1e9 describes nothing a finite one does not.
    const A_MAX = 50;
    const alphaOf = (t) => A_MAX * Math.tanh(t / A_MAX);
    const nll = (th) => {
      const xi = th[0], om = Math.exp(th[1]), al = alphaOf(th[2]);
      let ll = 0;
      for (const v of x) {
        const z = (v - xi) / om;
        ll += -0.5 * z * z + logNormCdf(al * z);
      }
      return -(ll + n * (Math.log(2) - Math.log(om) - 0.5 * Math.log(2 * Math.PI)));
    };
    const t0 = A_MAX * Math.atanh(Math.max(-0.999, Math.min(0.999, alpha0 / A_MAX)));
    const best = nelderMead(nll, [xi0, Math.log(omega0), t0], [0.1 * sd, 0.1, 0.5]);
    const llSkew = -best.f;
    const aicSkew = 6 - 2 * llSkew;
    const skew = { xi: best.x[0], omega: Math.exp(best.x[1]), alpha: alphaOf(best.x[2]), ll: llSkew, aic: aicSkew };
    const useSkew = aicSkew < aicNormal - 2;
    return {
      n,
      normal: { mu: mean, sigma: sd, ll: llNormal, aic: aicNormal },
      skew,
      best: useSkew ? 'skew-normal' : 'normal',
    };
  }

  function skewNormalPdf(x, xi, omega, alpha) {
    const z = (x - xi) / omega;
    return (2 / omega) * Math.exp(-0.5 * z * z) / Math.sqrt(2 * Math.PI) * normCdf(alpha * z);
  }

  function nelderMead(f, x0, step, maxIter = 600) {
    const nd = x0.length;
    let simplex = [x0.slice()];
    for (let i = 0; i < nd; i++) { const p = x0.slice(); p[i] += step[i]; simplex.push(p); }
    let vals = simplex.map(f);
    for (let it = 0; it < maxIter; it++) {
      const order = vals.map((v, i) => i).sort((a, b) => vals[a] - vals[b]);
      simplex = order.map((i) => simplex[i]);
      vals = order.map((i) => vals[i]);
      if (Math.abs(vals[nd] - vals[0]) < 1e-10 * (Math.abs(vals[0]) + 1e-10)) break;
      const c = new Array(nd).fill(0);
      for (let i = 0; i < nd; i++) for (let j = 0; j < nd; j++) c[j] += simplex[i][j] / nd;
      const xr = c.map((v, j) => v + (v - simplex[nd][j]));
      const fr = f(xr);
      if (fr < vals[0]) {
        const xe = c.map((v, j) => v + 2 * (v - simplex[nd][j]));
        const fe = f(xe);
        if (fe < fr) { simplex[nd] = xe; vals[nd] = fe; } else { simplex[nd] = xr; vals[nd] = fr; }
      } else if (fr < vals[nd - 1]) {
        simplex[nd] = xr; vals[nd] = fr;
      } else {
        const xc = c.map((v, j) => v + 0.5 * (simplex[nd][j] - v));
        const fc = f(xc);
        if (fc < vals[nd]) { simplex[nd] = xc; vals[nd] = fc; } else {
          for (let i = 1; i <= nd; i++) {
            simplex[i] = simplex[i].map((v, j) => simplex[0][j] + 0.5 * (v - simplex[0][j]));
            vals[i] = f(simplex[i]);
          }
        }
      }
    }
    let bi = 0;
    for (let i = 1; i <= nd; i++) if (vals[i] < vals[bi]) bi = i;
    return { x: simplex[bi], f: vals[bi] };
  }

  /* ---------------------------------------------------------------------
     A sweep: log S of one element's solids against one groundwater variable
     --------------------------------------------------------------------- */
  const SWEEP_VARS = {
    pH: { label: 'pH', log: false },
    HCO3: { label: 'log [HCO3-] free (m)', log: true },
    SO4: { label: 'log [SO4]tot (m)', log: true },
    Cl: { label: 'log [Cl]tot (m)', log: true },
    Ca: { label: 'log [Ca]tot (m)', log: true },
    Na: { label: 'log [Na]tot (m)', log: true },
    Si: { label: 'log [Si]tot (m)', log: true },
    I: { label: 'Ionic strength (mol/kg)', log: false },
    Eh: { label: 'Eh (mV), Version A', log: false },
    Fe: { label: 'log [Fe]tot (m), Version A', log: true },
  };

  function sweep(plan, water, elIndex, variable, from, to, points = 121) {
    const xs = [];
    const solids = plan.elements[elIndex].solids.map(() => []);
    const total = [];
    const control = [];
    for (let i = 0; i < points; i++) {
      const x = from + (to - from) * i / (points - 1);
      const w = { ...water };
      w[variable] = SWEEP_VARS[variable] && SWEEP_VARS[variable].log ? Math.pow(10, x) : x;
      let res;
      try { res = evaluateWater(plan, w, plan.nominal, false); } catch (e) { continue; }
      const r = res.elements[elIndex];
      xs.push(x);
      r.solids.forEach((s, k) => solids[k].push(Math.log10(s)));
      total.push(Math.log10(r.S));
      control.push(r.control);
    }
    return { x: xs, solids, total, control };
  }

  /* ---------------------------------------------------------------------
     Groundwater tables: column recognition
     --------------------------------------------------------------------- */
  // What each column may be called. Matched on a normalised header: lower
  // case, brackets, spaces and footnote stars removed.
  const COLUMN_PATTERNS = {
    pH: [/^ph$/],
    Ca: [/^\[?ca\]?(tot)?(\(m\)|m|\(mol\/kg\)|molkg|\(mol\/l\))?$/, /^catot/, /^ca$/],
    Mg: [/^\[?mg\]?(tot)?/, /^mg$/],
    Cl: [/^\[?cl-?\]?(tot)?/],
    Na: [/^\[?na\+?\]?(tot)?/],
    SO4: [/^\[?so4(-2|2-)?\]?(tot)?/, /^sulph?f?ate/],
    Si: [/^\[?si\]?(tot)?/, /^h4sio4/],
    I: [/^is(\(mol\/kg\)|molkg)?$/, /^i(\(mol\/kg\))?$/, /^ionicstrength/],
    HCO3: [/^\[?hco3-?\]?/, /^bicarbonate/, /^alkalinity/],
    Eh: [/^eh/],
    Fe: [/^\[?fe\]?(tot)?/],
    K: [/^\[?k\+?\]?(tot)?$/],
    id: [/^id/, /^name$/, /^sample/, /^water$/],
    domain: [/^domain/, /^climate/],
  };
  const REQUIRED = ['pH', 'Ca', 'Cl', 'Na', 'SO4', 'Si', 'I', 'HCO3'];

  function normaliseHeader(h) {
    return String(h == null ? '' : h).toLowerCase().replace(/[\s*_]+/g, '').replace(/[‐-―]/g, '-');
  }

  /** Map header names to the model's keys; returns {map: {key: col}, missing: [...]}. */
  function recogniseColumns(headers) {
    const map = {};
    const norm = headers.map(normaliseHeader);
    for (const [key, pats] of Object.entries(COLUMN_PATTERNS)) {
      for (let c = 0; c < norm.length; c++) {
        if (Object.values(map).includes(c)) continue;
        if (pats.some((re) => re.test(norm[c]))) {
          // "[Ca]tot" must not claim "[Cl]tot" and the like: the first letters must agree.
          map[key] = c;
          break;
        }
      }
    }
    const missing = REQUIRED.filter((k) => !(k in map));
    return { map, missing };
  }

  /**
   * Rows (arrays) with a header row → waters. Values may carry a decimal
   * comma. Mg is added to Ca when asked (the SR-Site convention).
   */
  function watersFromRows(rows, opts = {}) {
    if (!rows.length) throw new Error('the table is empty');
    let h = 0;
    // The header is the first row with a pH column in it.
    for (let r = 0; r < Math.min(rows.length, 30); r++) {
      if (rows[r].some((c) => normaliseHeader(c) === 'ph')) { h = r; break; }
    }
    const headers = rows[h].map((c) => String(c == null ? '' : c).trim());
    const { map, missing } = recogniseColumns(headers);
    if (missing.length) {
      throw new Error(`the table has no column for ${missing.join(', ')} (headers found: ${headers.filter(Boolean).join(', ')})`);
    }
    const num = (v) => {
      if (typeof v === 'number') return v;
      const s = String(v == null ? '' : v).trim().replace(/−/g, '-');
      if (!s) return NaN;
      const t = /^[-+]?\d+,\d+(e[-+]?\d+)?$/i.test(s) ? s.replace(',', '.') : s;
      return Number(t);
    };
    const waters = [];
    const skipped = [];
    for (let r = h + 1; r < rows.length; r++) {
      const row = rows[r];
      if (!row || row.every((c) => c === '' || c == null)) continue;
      const w = {};
      for (const k of ['pH', 'Ca', 'Cl', 'Na', 'SO4', 'Si', 'I', 'HCO3', 'Eh', 'Fe', 'Mg', 'K']) {
        if (k in map) w[k] = num(row[map[k]]);
      }
      if ('id' in map) w.id = String(row[map.id] ?? '');
      if ('domain' in map) w.domain = String(row[map.domain] ?? '');
      if (opts.addMg && Number.isFinite(w.Mg)) w.Ca += w.Mg;
      const bad = REQUIRED.filter((k) => !Number.isFinite(w[k]));
      if (bad.length) { skipped.push({ row: r + 1, missing: bad }); continue; }
      waters.push(w);
    }
    return { waters, headers, map, headerRow: h, skipped };
  }

  /* ---------------------------------------------------------------------
     Export
     --------------------------------------------------------------------- */
  function describeReaction(plan, elIndex, which, k) {
    const E = plan.elements[elIndex];
    return which === 'solid' ? E.solids[k].rx : E.species[k].rx;
  }

  /** The ligand dependence written out: "[H+]^2 pO2^0.5 / [H4SiO4]". */
  function ligandText(lig) {
    const up = [], down = [];
    lig.forEach((p, i) => {
      if (!p) return;
      const name = LIGAND_LABEL[LIGANDS[i]];
      const a = Math.abs(p);
      const t = a === 1 ? name : `${name}^${fmtNum(a)}`;
      (p > 0 ? up : down).push(t);
    });
    const u = up.join('·') || '1';
    return down.length ? `${u} / ${down.join('·')}` : u;
  }

  function qText(q) {
    const parts = [];
    q.forEach((c, z) => {
      if (!c) return;
      const a = Math.abs(c);
      parts.push(`${c < 0 ? '−' : '+'} ${a === 1 ? '' : `${fmtNum(a)}·`}q${z}`);
    });
    return parts.join(' ').replace(/^\+ /, '') || '0';
  }

  return {
    LIGANDS, LIG, LIGAND_LABEL, BASIS, MAJOR_IDS, DEFAULT_OPTIONS, DEFAULT_RUN, SWEEP_VARS, REQUIRED,
    parseReaction, parseTerm, chargeOf, elementCounts, balanceIssues, activityTerm, normaliseFormula, phaseOf,
    compileSpecies, compileSolid, compile,
    activityCorrections, groundwater, evaluateWater, analyse, sweep,
    makeRng, streamSeed, uniforms, normInv, drawWaters, sampleParams, run, createRunner,
    describe, quantileSorted, sortedFinite, ks2, spearman, ranks, pearson,
    fitDistribution, skewNormalPdf, normCdf,
    recogniseColumns, watersFromRows, normaliseHeader,
    ligandText, qText, describeReaction,
  };
}));
