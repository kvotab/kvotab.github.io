/*
  Decay radiations from ENSDF: the energies and yields of the radiations a
  radionuclide emits, computed from the decay data sets of the Evaluated
  Nuclear Structure Data File the way EDISTR (Dillman, ORNL/TM-6689, 1980)
  and EDISTR04 (Endo, Yamaguchi and Eckerman, JAERI 1347, 2005) computed
  them for ICRP Publications 38 and 107.

  ENSDF holds the nuclear part: levels, gamma rays with relative intensities
  and their normalisation, the alpha, beta and electron-capture branches that
  feed each level, conversion coefficients, Q values and half-lives. What
  the dose calculation reads besides is derived here:

    alpha particles   their kinetic energy and the recoil nucleus's, from the
                      Q value and the level energies (momentum conservation,
                      Dillman eqs 1-3);
    beta particles    end points from the Q value (eqs 4-5), shapes and mean
                      energies from Fermi theory (beta-spectrum.js), the
                      forbiddenness from the spins and parities (Table 1);
    positrons         two annihilation photons of 0.511 MeV each;
    conversion        electrons E_gamma - B_shell per shell, from the
                      conversion coefficients;
    atomic radiations X-rays and Auger electrons from the vacancies that
                      capture and conversion leave (atomic-relax.js).

  A decay data set describes one decay mode of one parent state; the states
  of one nuclide (its ground state and isomers) and their modes are put
  together here by the parent records. Gamma rays that leave a daughter
  isomer the dose calculation follows as a chain member of its own belong to
  that member's decay, not to the parent's, which therefore feeds the isomer
  and stops there.

  What the caller decides, through `ctx`:
    member(Z, A, level)   the chain member a daughter level is, if it is one
                          (an isomer the calculation follows by itself);
    icc(dataset, gamma)   the conversion coefficients of a gamma ray, by
                          shell, when the data set's own are not to be used;
    atomic(Z)             binding energies and the relaxation of vacancies;
    beta                  { shape, spectrum } (beta-spectrum.js);
    capture(...)          electron-capture probabilities by subshell;
    positronFraction(...) the positrons' share of a capture branch whose
                          total alone is known;
    feedingsFromBalance   level feedings from the gamma-ray balance when a
                          capture or beta-minus data set gives none;
    checkBalance          NR and NT checked against the data set's own
                          intensity balance, and no level letting out more
                          than enters it;
    continuation(Z, A, level)  the radiations of a short isomer the cascade
                          reaches and the data set does not let out;
    unlistedDeexcitation  a fed level the data set lets out by no gamma ray
                          sends its energy to the ground state as one;
    memberCascades        false keeps a member isomer's cascade below it in
                          the parent's decay, as EDISTR04 did (by default
                          it is taken out);
    self                  the name of the state being processed.
  The other flags are off by default, EDISTR04's way (ensdf-icrp107.mjs);
  ensdf-release.js sets them for a whole release.

  Energies inside are in keV as ENSDF writes them; the radiation lists come
  out in MeV with yields per decay, as dose-decay.mjs writes ICRP 107's.
*/

/* ---------------------------------------------------------------------------
   Fields
   --------------------------------------------------------------------------- */

/** Columns a..b, counted from 1 as the ENSDF manual counts them, trimmed. */
const col = (l, a, b) => l.slice(a - 1, b).trim();

/** A number from a field: "1.4E-7", "(2248)", "0.6406"; NaN when blank or not a number. */
export function num(s) {
  if (s == null) return NaN;
  const t = String(s).trim().replace(/^\((.*)\)$/, '$1').replace(/^\[(.*)\]$/, '$1');
  if (!t) return NaN;
  const m = /^[-+]?(\d+\.?\d*|\.\d+)(E[-+]?\d+)?/i.exec(t);
  return m ? Number(m[0]) : NaN;
}

const UNIT_S = {
  YS: 1e-24, ZS: 1e-21, AS: 1e-18, FS: 1e-15, PS: 1e-12, NS: 1e-9, US: 1e-6, MS: 1e-3, S: 1, M: 60, H: 3600, D: 86400,
  Y: 31556952, KY: 31556952e3, MY: 31556952e6, GY: 31556952e9, TY: 31556952e12, PY: 31556952e15, EY: 31556952e18,
};

/* The year ENSDF and the ICRP files mean: 365.2425 days, so that a half-life
   in years round-trips through seconds the way the NDX file writes it. */
export const YEAR_S = 31556952;

/** A half-life field ("30.1671 Y", "2.99E-7 S", "STABLE") in seconds; Infinity for stable, NaN if none. */
export function halfLifeSeconds(field) {
  const t = String(field || '').trim().toUpperCase();
  if (!t) return NaN;
  if (t.startsWith('STABLE')) return Infinity;
  const m = /^[~<>]?\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:E[-+]?\d+)?)\s*([A-Z]+)/.exec(t);
  if (!m || !(m[2] in UNIT_S)) return NaN;
  return Number(m[1]) * UNIT_S[m[2]];
}

/**
 * Spin and parity from a J field: "7/2+", "(5/2,7/2+)", "1(-)", "[3/2-]".
 * Returns {J: [values], p: '+', '-' or '', firm} with firm false when the
 * evaluator wrote the assignment in parentheses or gave several.
 */
export function spinParity(field) {
  const raw = String(field || '').trim();
  if (!raw) return { J: [], p: '', firm: false };
  const J = [];
  for (const m of raw.matchAll(/(\d+)(?:\/(\d))?/g)) J.push(m[2] ? Number(m[1]) / Number(m[2]) : Number(m[1]));
  const ps = new Set((raw.match(/[+-]/g) || []));
  const p = ps.size === 1 ? [...ps][0] : '';
  return { J, p, firm: !/[(\[]/.test(raw) && J.length === 1 };
}

/** Continuation-record fields "KC=11.69 17$LC=1.596 25" -> {KC: '11.69', LC: '1.596', ...} (values as written). */
function contFields(text, into) {
  for (const part of text.split('$')) {
    const m = /^\s*([A-Z%][A-Z0-9%+\-/()]*?)\s*(=|<|>|<=|>=| AP | LT | GT | LE | GE )\s*(.*?)\s*$/i.exec(part);
    if (!m) continue;
    const name = m[1].toUpperCase();
    // A value given as approximate ("KC AP 0.12") is kept for the conversion
    // coefficients, where it is the evaluator's estimate; limits are not.
    const rel = m[2].trim().toUpperCase();
    if (!(name in into)) into[name] = rel === '=' || (rel === 'AP' && /^(?:[KLMNOPQ]\d?C\+?|CC)$/.test(name)) ? m[3].split(/\s+/)[0] : '';
  }
  return into;
}

/* ---------------------------------------------------------------------------
   Data sets
   --------------------------------------------------------------------------- */

const ELEMENTS = ['n', 'H', 'He', 'Li', 'Be', 'B', 'C', 'N', 'O', 'F', 'Ne', 'Na', 'Mg', 'Al', 'Si', 'P', 'S', 'Cl', 'Ar', 'K', 'Ca', 'Sc', 'Ti',
  'V', 'Cr', 'Mn', 'Fe', 'Co', 'Ni', 'Cu', 'Zn', 'Ga', 'Ge', 'As', 'Se', 'Br', 'Kr', 'Rb', 'Sr', 'Y', 'Zr', 'Nb', 'Mo', 'Tc', 'Ru', 'Rh', 'Pd', 'Ag',
  'Cd', 'In', 'Sn', 'Sb', 'Te', 'I', 'Xe', 'Cs', 'Ba', 'La', 'Ce', 'Pr', 'Nd', 'Pm', 'Sm', 'Eu', 'Gd', 'Tb', 'Dy', 'Ho', 'Er', 'Tm', 'Yb', 'Lu',
  'Hf', 'Ta', 'W', 'Re', 'Os', 'Ir', 'Pt', 'Au', 'Hg', 'Tl', 'Pb', 'Bi', 'Po', 'At', 'Rn', 'Fr', 'Ra', 'Ac', 'Th', 'Pa', 'U', 'Np', 'Pu', 'Am',
  'Cm', 'Bk', 'Cf', 'Es', 'Fm', 'Md', 'No', 'Lr', 'Rf', 'Db', 'Sg', 'Bh', 'Hs', 'Mt', 'Ds', 'Rg', 'Cn', 'Nh', 'Fl', 'Mc', 'Lv', 'Ts', 'Og'];
export const SYMBOL = ELEMENTS;
const Z_OF = new Map(ELEMENTS.map((s, z) => [s.toUpperCase(), z]));

/** NUCID "137CS", " 99TC", "248CM" -> {A, Z}; null for mass-chain records ("137  "). */
export function nucid(s) {
  const m = /^\s*(\d{1,3})\s*([A-Z]{0,2})\s*$/i.exec(s);
  if (!m || !m[2]) return null;
  const Z = Z_OF.get(m[2].toUpperCase());
  // Above Z = 103 ENSDF writes the element as two digits of Z - 100.
  if (Z === undefined) {
    const n = /^\d\d$/.exec(m[2]) ? 100 + Number(m[2]) : NaN;
    return Number.isFinite(n) ? { A: Number(m[1]), Z: n } : null;
  }
  return { A: Number(m[1]), Z };
}

function readParent(l) {
  const id = nucid(l.slice(0, 5));
  const { E, offset } = levelEnergy(col(l, 10, 19));
  return {
    Z: id?.Z, A: id?.A, Eraw: col(l, 10, 19), E: E || 0, offset, J: col(l, 22, 39),
    T: halfLifeSeconds(col(l, 40, 49)), Traw: col(l, 40, 49), Q: num(col(l, 65, 74)), ion: col(l, 77, 80),
  };
}

function readNorm(l) {
  return { NR: num(col(l, 10, 19)), NT: num(col(l, 22, 29)), BR: num(col(l, 32, 39)), NB: num(col(l, 42, 49)), NP: num(col(l, 56, 62)) };
}

/* A level energy with an unknown offset ("X+54.15", "0.0+X", "Y"): the
   number, and the offset's letter. Levels of one offset are placed among
   themselves; their absolute energy is taken as the number. */
function levelEnergy(raw) {
  const t = raw.replace(/\s+/g, '');
  const m = /^([A-Z])\+?([0-9.]*)$|^([0-9.]+(?:E[-+]?\d+)?)\+([A-Z])$/i.exec(t);
  if (m) return { E: num(m[2] || m[3] || '0') || 0, offset: (m[1] || m[4]).toUpperCase() };
  return { E: num(t), offset: '' };
}

function readLevel(l) {
  const { E, offset } = levelEnergy(col(l, 10, 19));
  return {
    Eraw: col(l, 10, 19), E, offset, J: col(l, 22, 39), T: halfLifeSeconds(col(l, 40, 49)), Traw: col(l, 40, 49),
    ms: col(l, 78, 79), q: l.charAt(79).trim(), gammas: [], feeds: [], cont: {},
  };
}

function readGamma(l) {
  return {
    kind: 'G', Eraw: col(l, 10, 19), E: num(col(l, 10, 19)), RI: num(col(l, 22, 29)), MUL: col(l, 32, 41), MR: num(col(l, 42, 49)),
    CC: num(col(l, 56, 62)), TI: num(col(l, 65, 74)), flag: l.charAt(76).trim(), q: l.charAt(79).trim(), cont: {},
  };
}

function readBeta(l) {
  return { kind: 'B', Eraw: col(l, 10, 19), E: num(col(l, 10, 19)), IB: num(col(l, 22, 29)), logft: num(col(l, 42, 49)), UN: col(l, 78, 79), q: l.charAt(79).trim(), cont: {} };
}

function readEc(l) {
  return {
    kind: 'E', Eraw: col(l, 10, 19), E: num(col(l, 10, 19)), IB: num(col(l, 22, 29)), IE: num(col(l, 32, 39)), logft: num(col(l, 42, 49)),
    TI: num(col(l, 65, 74)), UN: col(l, 78, 79), q: l.charAt(79).trim(), cont: {},
  };
}

function readAlpha(l) {
  return { kind: 'A', Eraw: col(l, 10, 19), E: num(col(l, 10, 19)), IA: num(col(l, 22, 29)), HF: num(col(l, 32, 39)), q: l.charAt(79).trim(), cont: {} };
}

/* ICRP 107's own extension (EDISTR's "FISSION record"): nu-bar, % SF, Watt a and b. */
function readFission(l) {
  return { nu: num(col(l, 10, 19)), pct: num(col(l, 22, 29)), a: num(col(l, 40, 59)), b: num(col(l, 60, 80)) };
}

/** The mode a DSID names: "137CS B- DECAY (30.1 Y)" -> {parent: '137CS', mode: 'B-'}. */
function decayOf(dsid) {
  const m = /^\s*(\S+)\s+(\S+)\s+DECAY\b\s*(.*)$/.exec(dsid);
  return m ? { parent: m[1], mode: m[2].replace(/^\[|\]$/g, ''), qualifier: m[3] } : null;
}

/**
 * Every decay data set of an ENSDF text, records read and continuation
 * fields attached. Adopted-level data sets come back too when asked for
 * ({adopted: true}), for their isomers and half-lives.
 */
export function readDatasets(text, opt = {}) {
  const out = [];
  const lines = text.replace(/\r/g, '').split('\n');
  let block = [];
  const flush = () => {
    if (block.length) {
      const ds = readDataset(block, opt);
      if (ds) out.push(ds);
    }
    block = [];
  };
  for (const raw of lines) {
    if (!raw.trim()) { flush(); continue; }
    block.push(raw.padEnd(80));
  }
  flush();
  return out;
}

function readDataset(L, opt) {
  const head = L[0];
  const id = nucid(head.slice(0, 5));
  if (!id) return null;
  let dsid = col(head, 10, 39);
  let start = 1;
  // A DSID too long for its field ends in a comma and continues on a second
  // identification record.
  if (dsid.endsWith(',') && L.length > 1 && L[1].slice(0, 5) === head.slice(0, 5) && L[1].charAt(5) !== ' ' && L[1].slice(6, 9) === '   ') {
    dsid += ' ' + col(L[1], 10, 39);
    start = 2;
  }
  const decay = decayOf(dsid);
  const adopted = /^ADOPTED LEVELS/.test(dsid);
  if (!decay && !(adopted && opt.adopted)) return null;
  const ds = {
    Z: id.Z, A: id.A, nucid: head.slice(0, 5), dsid, date: col(head, 75, 80), adopted,
    mode: decay?.mode || null, qualifier: decay?.qualifier || '', parentNucid: decay?.parent || null,
    parents: [], norm: null, pn: null, levels: [], unplaced: { gammas: [], feeds: [] }, fission: null,
  };
  let level = null;
  let last = null;
  for (let i = start; i < L.length; i++) {
    const l = L[i];
    const c6 = l.charAt(5), c7 = l.charAt(6), type = l.charAt(7), c9 = l.charAt(8);
    if (c7 === 'P' && type === 'N') { ds.pn = { NRBR: num(col(l, 10, 19)), NTBR: num(col(l, 22, 29)), NBBR: num(col(l, 42, 49)), NP: num(col(l, 56, 62)) }; continue; }
    if (c7 !== ' ') continue; // comments, documentation
    const cont = c6 !== ' ' && c6 !== '1';
    if (cont) {
      if (last && type === last.type) contFields(l.slice(9, 80), last.rec.cont);
      continue;
    }
    last = null;
    // Particle records with a particle in column 9 (delayed particles) are not
    // used; a digit there on a P or N record numbers the parents of a data
    // set for two states ("160HO EC DECAY (25.6 M+5.02 H)"), N1 the first's.
    if (c9 !== ' ' && type !== ' ' && !((type === 'P' || type === 'N') && /\d/.test(c9))) continue;
    let rec = null;
    switch (type) {
      case 'P': ds.parents.push(readParent(l)); break;
      case 'N': if (!ds.norm) ds.norm = readNorm(l); break;
      case 'L': level = readLevel(l); ds.levels.push(level); rec = level; break;
      case 'G': rec = readGamma(l); (level ? level.gammas : ds.unplaced.gammas).push(rec); break;
      case 'B': rec = readBeta(l); (level ? level.feeds : ds.unplaced.feeds).push(rec); break;
      case 'E': rec = readEc(l); (level ? level.feeds : ds.unplaced.feeds).push(rec); break;
      case 'A': rec = readAlpha(l); (level ? level.feeds : ds.unplaced.feeds).push(rec); break;
      case 'F': ds.fission = readFission(l); break;
      default: break;
    }
    if (rec) last = { type, rec };
  }
  return ds;
}

/* ---------------------------------------------------------------------------
   Parent states
   --------------------------------------------------------------------------- */

const sameEnergy = (a, b) => Math.abs(a - b) <= Math.max(0.05, 1e-4 * Math.max(a, b));

/**
 * The decay data sets put together by the state that decays: [{Z, A, E (keV),
 * T (s), J, Q, datasets}], ground state first, then isomers by energy.
 */
export function parentStates(datasets) {
  const states = [];
  for (const ds of datasets) {
    if (ds.adopted) continue;
    const p = ds.parents[0];
    let Z, A, E, T, J, Q, Eraw;
    // An IT data set comes from an excited level; one whose parent record
    // says 0 (Th-229's 8 eV isomer) is placed by its own decaying level.
    if (p && !(ds.mode === 'IT' && !(p.E > 0) && !p.offset)) ({ Z, A, E, T, J, Q, Eraw } = p);
    else if (ds.mode === 'IT') {
      // An IT data set may leave the parent record out: the decaying level is the highest with a half-life.
      const iso = ds.levels.filter((l) => l.T > 0 && Number.isFinite(l.T)).sort((a, b) => b.E - a.E)[0];
      if (!iso) continue;
      Z = ds.Z; A = ds.A; E = iso.E; T = iso.T; J = iso.J; Q = NaN; Eraw = iso.Eraw;
    } else continue;
    // A level written with an unknown offset ("0+X", "X") is not the level
    // its number says: such parents are told apart by their half-lives.
    // A level above zero is never the ground state, however close (Th-229's 8 eV isomer).
    const offset = /[A-Z]/i.test(String(Eraw || '').replace(/E[-+]?\d+$/i, ''));
    let st = states.find((s) => s.Z === Z && s.A === A && s.offset === offset
      && (offset ? s.Eraw === Eraw || (Number.isFinite(T) && Number.isFinite(s.T) && Math.abs(Math.log10(T / s.T)) < 0.1)
        : sameEnergy(s.E, E) && (s.E > 0) === (E > 0)));
    if (!st) { st = { Z, A, E, Eraw, offset, T, J, Q, datasets: [] }; states.push(st); }
    if (!Number.isFinite(st.T) && Number.isFinite(T)) st.T = T;
    if (!Number.isFinite(st.Q) && Number.isFinite(Q)) st.Q = Q;
    st.datasets.push(ds);
  }
  return states.sort((a, b) => (a.Z - b.Z) || (a.A - b.A) || (a.E - b.E));
}

/* ---------------------------------------------------------------------------
   Forbiddenness of a beta transition (Dillman 1980, Table 1 and p. 7)
   --------------------------------------------------------------------------- */

/* The first spin a J field lists and the first parity written after it ("3/2+,5/2+" is 3/2+, "1,2+" is 1+), as EDISTR reads it. */
export function firstSpin(field) {
  const s = String(field || '');
  const m = /(\d+)(?:\/(\d))?\)?(?:\(([+-])\)|([+-]))?/.exec(s);
  if (!m) return null;
  const p = m[3] || m[4] || (/[+-]/.exec(s.slice(m.index)) || [])[0] || '';
  return { J: m[2] ? Number(m[1]) / Number(m[2]) : Number(m[1]), p };
}

/**
 * The shape order n of a beta transition: 0 allowed (and first-forbidden
 * non-unique), 1 first-forbidden unique (and second non-unique), 2 second
 * unique (and third non-unique), 3 third unique. From the evaluator's
 * uniqueness flag where there is one, else from the spins and parities when
 * both are known, else from log ft (Dillman's rules: <= 9 allowed, 9-13
 * first unique, > 13 second unique).
 */
export function shapeOrder(parentJ, levelJ, un, logft) {
  const flag = String(un || '').trim().toUpperCase();
  const u = /^([1-4])U$/.exec(flag);
  if (u) return Number(u[1]);
  const nu = /^([1-4])NU$/.exec(flag);
  if (nu) return Number(nu[1]) - 1;
  // EDISTR takes the first spin a field lists ("3/2+,5/2+" is 3/2+, "1,2+"
  // is 1+) and the first parity written after it. A change of 0 or 1 is
  // allowed (first-forbidden non-unique has the allowed shape), 2 the first
  // unique shape (second non-unique alike), 3 the second; 4 with a change of
  // parity is third unique, and anything further EDISTR has no shape for
  // and takes as allowed (Cd-113 1/2+ -> 9/2+, In-115 9/2+ -> 1/2+). These
  // rules give every one of ICRP 107's 7242 beta branches EDISTR04's shape.
  // "If spin or parity information is lacking for parent or daughter level,
  // then the log(ft) input data are examined" (Dillman 1980, p. 7).
  const a = firstSpin(parentJ), b = firstSpin(levelJ);
  if (a && b && a.p && b.p) {
    const dJ = Math.abs(a.J - b.J);
    const flip = a.p !== b.p;
    if (dJ <= 1) return 0;
    if (dJ === 2) return 1;
    if (dJ === 3) return 2;
    if (dJ === 4 && flip === true) return 3;
    return 0;
  }
  if (Number.isFinite(logft)) return logft <= 9 ? 0 : logft <= 13 ? 1 : 2;
  return 0;
}

/* ---------------------------------------------------------------------------
   One parent state's radiations
   --------------------------------------------------------------------------- */

const ME = 510.99895; // keV
const ALPHA_MASS = 4.0026; // u, as EDISTR's eqs (1)-(2)

/** The decay family of a data set's mode: 'B-', 'EC' (with B+), 'A', 'IT', 'SF', or null. */
export function family(mode) {
  const m = String(mode || '').toUpperCase();
  // Double beta decay (2B-, 2EC, 2B+), of half-lives of 1E18 years and
  // more, is not followed: ICRP 107 has none of these nuclides either.
  if (m === 'B-') return 'B-';
  if (m === 'EC' || m === 'B+' || m === 'EC+B+') return 'EC';
  if (m === 'A') return 'A';
  if (m === 'IT') return 'IT';
  if (m === 'SF') return 'SF';
  return null;
}

/**
 * The radiations of one parent state, per decay, and where its decays go.
 *
 * @param {object} state  a parentStates() entry
 * @param {object} ctx    see the header; ctx.member(Z, A, level, state) -> name | null,
 *                        ctx.icc(ds, gamma, level) -> {K, L1, L2, L3, M, N, ...} | null,
 *                        ctx.atomic(Z) -> {binding: {K: keV, ...}, relax(vacancies) -> lines} | null,
 *                        ctx.beta = {shape, spectrum}, ctx.capture(Z, q, n, ec) -> {K: p, L1: p, ...},
 *                        ctx.positronFraction(Z, A, Et (keV), n, ec, atom) -> share, ctx.feedingsFromBalance
 * @returns {object} {lines: [{type, E (keV), Y, ...}], branches: [{to: {Z, A, member}, br}], betas, balance, notes}
 */
export function stateRadiations(state, ctx) {
  const out = { lines: [], branches: [], betas: [], vacancies: {}, notes: [], sf: null, modes: [] };
  for (const ds of state.datasets) {
    const fam = family(ds.mode);
    if (!fam) { out.notes.push(`${ds.dsid}: mode not used`); continue; }
    out.modes.push(fam);
    if (fam === 'SF') {
      const br = Number.isFinite(ds.norm?.BR) ? ds.norm.BR : (ds.fission ? ds.fission.pct / 100 : NaN);
      out.sf = { br, ...(ds.fission || {}) };
      continue;
    }
    datasetRadiations(state, ds, fam, ctx, out);
  }
  return out;
}

/* The subshell a vacancy of the named one goes to for a transition of
   energy E (keV): itself when it is bound less than E; when it is bound
   more, the most bound subshell that is not; when the atom has no such
   subshell (rhodium has no 5p for an O2 share), its outermost one that E
   reaches. null when none is open. */
const OPEN = new WeakMap();
function openShell(atom, name, E) {
  const B = atom.binding[name];
  if (B >= 0 && B < E) return name;
  let list = OPEN.get(atom);
  if (!list) { list = Object.entries(atom.binding).filter(([, b]) => b > 0).sort((p, q) => q[1] - p[1]); OPEN.set(atom, list); }
  if (B >= E) { const hit = list.find(([, b]) => b < E); return hit ? hit[0] : null; }
  for (let i = list.length - 1; i >= 0; i--) if (list[i][1] < E) return list[i][0];
  return null;
}

function datasetRadiations(state, ds, fam, ctx, out) {
  const n = ds.norm || {};
  // The branch: the normalisation record's, or what the production record
  // implies, or (ctx.branchOf) the release's adopted percentage for the mode;
  // EDISTR took 1 (Dillman 1980, p. 44), which makes Mn-54's tiny beta-minus
  // data set, written without one, a second whole decay.
  // With ctx.adoptedBranches the adopted percentage comes first: a data set
  // may give the branch as 1 (Mn-54's beta-minus one, adopted 9.3E-5 %).
  const adopted = ctx.branchOf?.(fam);
  const BR = ctx.adoptedBranches && adopted > 0 ? adopted
    : Number.isFinite(n.BR) ? n.BR
      : Number.isFinite(ds.pn?.NRBR) && Number.isFinite(n.NR) && n.NR ? ds.pn.NRBR / n.NR
        : adopted > 0 ? adopted : 1;
  let NR = Number.isFinite(n.NR) ? n.NR : (Number.isFinite(ds.pn?.NRBR) ? ds.pn.NRBR / BR : NaN);
  const relative = !Number.isFinite(NR);
  if (relative && !ctx.normaliseRelative) NR = 1; // EDISTR's default
  let NT = Number.isFinite(n.NT) ? n.NT : NR;
  const NB = Number.isFinite(n.NB) ? n.NB : 1;
  const Zd = ds.Z, Ad = ds.A;
  // Each mode has its own ground-state Q, on its own data set's parent record.
  const P = ds.parents[0];
  const Q = Number.isFinite(P?.Q) ? P.Q : (state.datasets.length === 1 ? state.Q : NaN); // keV
  const Ep = P ? P.E || 0 : state.E || 0;
  const atom = Zd >= 1 ? ctx.atomic?.(Zd) : null;
  const vac = {};
  const addVac = (shell, x) => { if (x > 0) vac[shell] = (vac[shell] || 0) + x; };

  // Which daughter levels are chain members by themselves (isomers the
  // calculation follows): their gamma rays are theirs, not this decay's.
  const isIT = fam === 'IT';
  const memberAt = new Map();
  for (const lv of ds.levels) {
    if (!(lv.E > 0) && !lv.offset) continue; // the ground state ("X+0.0" is an isomer)
    if (isIT && sameEnergy(lv.E, Ep) && (lv.offset || '') === (P?.offset || '')) continue; // the decaying isomer itself
    const name = ctx.member?.(Zd, Ad, lv, state, ds);
    // ctx.self: the state being processed, never its own member (Hf-178m2's
    // IT data set gives it at 2446.07 keV, its parent record at 2445.69).
    if (name && name !== ctx.self) memberAt.set(lv, name);
  }

  // Feeding of each level and the transitions between levels, per 100 decays of the parent.
  const feedIn = new Map(ds.levels.map((lv) => [lv, 0]));
  // The level a gamma ray ends at: by energy, among the levels of its own
  // offset (Pt-186's capture data set sits wholly on Ir-186m at "X").
  const levelOf = (E, offset = '') => {
    let best = null, d = Infinity;
    for (const lv of ds.levels) { if ((lv.offset || '') !== offset) continue; const x = Math.abs(lv.E - E); if (x < d) { d = x; best = lv; } }
    return best && d <= Math.max(1, 0.002 * E) ? best : null;
  };

  // Alpha, beta and capture branches.
  const placedFeeds = [];
  ds.levels.forEach((lv) => lv.feeds.forEach((f) => placedFeeds.push([lv, f])));
  ds.unplaced.feeds.forEach((f) => placedFeeds.push([null, f]));
  // The intensities of a branch's feedings are percentages of that branch
  // (Dillman 1980, p. 47), so EDISTR scales them to add up to 100: Am-241's
  // alphas, listed to 99.73 %, come out 1.0027 times their listed values.
  const fsum = { A: 0, B: 0, E: 0 }, fcount = { A: 0, B: 0, E: 0 };
  for (const [, f] of placedFeeds) {
    if (!(f.kind in fsum)) continue;
    fcount[f.kind]++;
    if (f.kind === 'A') fsum.A += Number.isFinite(f.IA) ? f.IA : 0;
    else if (f.kind === 'B') fsum.B += Number.isFinite(f.IB) ? f.IB : 0;
    else if (f.kind === 'E') fsum.E += (Number.isFinite(f.IB) ? f.IB : 0) + (Number.isFinite(f.IE) ? f.IE : 0) || (Number.isFinite(f.TI) ? f.TI : 0);
  }
  // A branch with a single feeding and no intensity on it (Hf-174's one
  // alpha group) is that feeding entirely; unless it is the ground state's
  // and excited levels give out gamma rays (W-189's beta-minus data set),
  // where how much it takes is unknown.
  const excitedGammas = ds.levels.some((lv) => (lv.E > 0 || lv.offset) && lv.gammas.length);
  for (const [lv, f] of placedFeeds) {
    if (fcount[f.kind] !== 1 || fsum[f.kind] > 0) continue;
    if (ctx.feedingsFromBalance && excitedGammas && lv && !(lv.E > 0) && !lv.offset) continue;
    if (f.kind === 'A') f.IA = 100;
    else if (f.kind === 'B') f.IB = 100;
    else if (f.kind === 'E') f.TI = 100;
    fsum[f.kind] = 100;
  }
  const scale = (k) => (ctx.normaliseFeeds !== false && fsum[k] > 0 ? 100 / fsum[k] : NB);
  const parentJ = ds.parents[0]?.J ?? state.J;
  // The shape LOGFT gives the capture/positron split: the evaluator's
  // uniqueness flag, else allowed (EDISTR's spin rule is for the spectrum).
  const flagOrder = (un) => { const m = /^([1-4])U$/.exec(String(un || '').trim().toUpperCase()); return m ? Number(m[1]) : 0; };
  /* One feeding; sc: per kind, the factor from its listed intensity to percent of the branch. */
  function feedBranch(lv, f, sc) {
    const EL = lv ? lv.E : NaN;
    const Et = Number.isFinite(Q) && lv && Number.isFinite(EL) ? Q + Ep - EL : NaN; // transition energy, keV
    if (f.kind === 'A') {
      const I = (Number.isFinite(f.IA) ? f.IA : 0) * sc.A * BR / 100;
      if (!(I > 0)) return;
      let Ea, Er;
      if (Number.isFinite(Et)) { Ea = Et / (1 + ALPHA_MASS / Ad); Er = Et - Ea; }
      else { Ea = f.E; Er = ALPHA_MASS * Ea / Ad; }
      out.lines.push({ type: 'A', E: Ea, Y: I }, { type: 'AR', E: Er, Y: I });
      if (lv) feedIn.set(lv, feedIn.get(lv) + I * 100);
    } else if (f.kind === 'B') {
      const I = (Number.isFinite(f.IB) ? f.IB : 0) * sc.B * BR / 100;
      if (!(I > 0)) return;
      const E0 = Number.isFinite(Et) ? Et : f.E;
      if (!(E0 > 0)) { out.notes.push(`${ds.dsid}: beta to ${lv?.Eraw} without end point`); return; }
      const nOrd = shapeOrder(parentJ, lv?.J, f.UN, f.logft);
      out.betas.push({ Z: Zd, A: Ad, E0: E0 / 1000, n: nOrd, positron: false, yield: I });
      if (lv) feedIn.set(lv, feedIn.get(lv) + I * 100);
    } else if (f.kind === 'E') {
      let Ib = (Number.isFinite(f.IB) ? f.IB : 0) * sc.E * BR / 100;
      let Ie = (Number.isFinite(f.IE) ? f.IE : 0) * sc.E * BR / 100;
      if (!(Ib > 0) && !(Ie > 0) && Number.isFinite(f.TI)) {
        // Only the total: capture alone where positrons are energetically
        // impossible, otherwise split by the caller's capture/positron ratio.
        const tot = f.TI * sc.E * BR / 100;
        const frac = Et > 2 * ME && ctx.positronFraction && atom ? ctx.positronFraction(Zd, Ad, Et, flagOrder(f.UN), f, atom) : 0;
        Ib = tot * frac; Ie = tot - Ib;
      }
      const Etr = Number.isFinite(Et) ? Et : f.E;
      if (Ib > 0) {
        const E0 = Etr - 2 * ME;
        if (E0 > 0) {
          const nOrd = shapeOrder(parentJ, lv?.J, f.UN, f.logft);
          out.betas.push({ Z: Zd, A: Ad, E0: E0 / 1000, n: nOrd, positron: true, yield: Ib });
          out.lines.push({ type: 'AQ', E: ME, Y: 2 * Ib });
        } else out.notes.push(`${ds.dsid}: positrons to ${lv?.Eraw} below threshold`);
      }
      if (Ie > 0 && atom) {
        const nOrd = shapeOrder(parentJ, lv?.J, f.UN, f.logft);
        const p = ctx.capture ? ctx.capture(Zd, Etr, nOrd, f, atom) : null;
        if (p) for (const [shell, x] of Object.entries(p)) addVac(shell, Ie * x);
      }
      if (lv) feedIn.set(lv, feedIn.get(lv) + (Ib + Ie) * 100);
    }
  }
  const listed = { A: ctx.normaliseFeeds !== false && fsum.A > 0 ? 100 / fsum.A : 1, B: scale('B'), E: scale('E') };
  for (const [lv, f] of placedFeeds) feedBranch(lv, f, listed);
  if (ds.parents.length > 1) out.notes.push(`${ds.dsid}: one data set for ${ds.parents.length} parent states, all of it taken for the first (${P.Eraw} keV, ${P.Traw})`);

  // Conversion coefficients once per gamma ray.
  const coefOf = new Map();
  const coefficients = (g, lv) => {
    if (!coefOf.has(g)) coefOf.set(g, ctx.icc ? ctx.icc(ds, g, lv) : null);
    return coefOf.get(g);
  };

  // A transition's total intensity in the data set's own units (RI (1 + alpha),
  // or TI, times nr or nt). A gamma ray with %IG and no RI takes RI from it
  // (%IG = RI NR BR) where NR is known.
  const alphaOf = (g, lv) => { const c = coefficients(g, lv); return c ? Object.values(c).reduce((x, y) => x + (y > 0 ? y : 0), 0) : 0; };
  const rawTotal = (g, lv, nr = 1, nt = 1) => {
    if (/^\W*E0\W*$/.test(g.MUL)) return Number.isFinite(g.TI) ? g.TI * nt : Number.isFinite(g.RI) ? g.RI * nr : 0;
    if (Number.isFinite(g.TI)) return g.TI * nt;
    let ri = g.RI;
    if (!Number.isFinite(ri)) {
      const ig = num(g.cont['%IG']);
      if (!(Number.isFinite(ig) && NR > 0 && BR > 0)) return 0;
      ri = ig / (NR * BR);
    }
    return ri * nr * (1 + alphaOf(g, lv));
  };
  const destOf = (g, lv) => (g.cont.FL ? levelOf(num(g.cont.FL), lv.offset) : levelOf(lv.E - g.E, lv.offset));
  const isGround = (lv) => !(lv.E > 0) && !lv.offset;

  // TI on RI's scale under an NT that says otherwise (ENSDF 2026's Pd-111
  // beta-minus data set: NR 0.0087, NT 1.0, and the 70.4 keV transition with
  // RI 90, CC 1.18, TI 197): when the gamma rays that give both put NT off
  // by more than a factor of 3, NT follows them.
  if (Number.isFinite(NR) && Number.isFinite(NT) && ctx.checkBalance) {
    const r = [];
    for (const lv of ds.levels) {
      for (const g of lv.gammas) {
        if (!(g.TI > 0) || !(g.RI > 0) || /E0/.test(g.MUL)) continue;
        r.push(g.TI * NT / (g.RI * NR * (1 + alphaOf(g, lv))));
      }
    }
    r.sort((a, b) => a - b);
    const m = r[r.length >> 1];
    if (r.length && Math.abs(Math.log(m)) > Math.log(3)) {
      out.notes.push(`${ds.dsid}: NT ${n.NT ?? NT} puts TI ${m.toPrecision(3)} times RI (1 + alpha) NR: NT taken as ${(NT / m).toPrecision(3)}`);
      NT /= m;
    }
  }

  // Each level's net outflow: what its gamma rays take out less what those
  // from above bring in, on RI's scale (NR = 1, TI by NT/NR). For a level
  // fed directly it is that feeding; for the ground state, and for low
  // levels whose own transition the data set does not list (Np-239's
  // 7.9 keV level in Pu-239), it is negative.
  const levelNet = () => {
    const nt = Number.isFinite(NR) && Number.isFinite(NT) && NR > 0 ? NT / NR : 1;
    const outOf = new Map(), inOf = new Map();
    for (const lv of ds.levels) {
      for (const g of lv.gammas) {
        const t = rawTotal(g, lv, 1, nt);
        if (!(t > 0)) continue;
        outOf.set(lv, (outOf.get(lv) || 0) + t);
        const to = destOf(g, lv);
        if (to && to !== lv) inOf.set(to, (inOf.get(to) || 0) + t);
      }
    }
    return { outOf, net: (lv) => (outOf.get(lv) || 0) - (inOf.get(lv) || 0) };
  };
  // Three estimates of NR from the data set itself, with the feedings as
  // listed (times NB, in percent of the branch; not scaled to 100):
  //   net     the feedings of the excited levels over their positive net
  //           outflows (100 % less the ground state's listed feeding);
  //   levels  at each level fed by more than 0.2 % of the branch, its
  //           feeding over its net outflow: their median, weighted by the
  //           feedings, when those cover half the branch;
  //   energy  the excitation energy the feedings bring over the energy the
  //           transitions carry (sum of feeding x level energy over sum of
  //           intensity x gamma energy).
  const nrEstimates = () => {
    const { outOf, net } = levelNet();
    const listed = (lv) => lv.feeds.reduce((t, f) => t + ((((f.IB || 0) + (f.IE || 0)) || f.TI || f.IA || 0) * (Number.isFinite(f.IA) ? 1 : NB)), 0);
    let pos = 0, fedAbove = 0, fedGround = 0, fE = 0, gE = 0;
    const pairs = [];
    for (const lv of ds.levels) {
      if (memberAt.has(lv)) continue;
      for (const g of lv.gammas) gE += rawTotal(g, lv, 1, Number.isFinite(NR) && Number.isFinite(NT) && NR > 0 ? NT / NR : 1) * g.E;
      const f = listed(lv);
      if (isGround(lv)) { fedGround += f; continue; }
      const o = net(lv);
      pos += Math.max(0, o); fedAbove += f; fE += f * lv.E;
      if (f > 0.2 && outOf.get(lv) > 0 && o > 0) pairs.push([f / o, f]);
    }
    const est = {};
    if (pos > 0 && fedAbove > 0) est.net = fedAbove / pos;
    const W = pairs.reduce((t, [, w]) => t + w, 0);
    if (W >= 50) {
      pairs.sort((a, b) => a[0] - b[0]);
      let acc = 0;
      for (const [r, w] of pairs) { acc += w; if (acc >= W / 2) { est.levels = r; break; } }
    }
    if (fE > 0 && gE > 0) est.energy = fE / gE;
    return est;
  };

  // A capture or beta-minus data set with gamma rays and no feeding
  // intensities (ENSDF 2026's Pr-135 capture data set; with
  // ctx.feedingsFromBalance): each excited level is fed by its net outflow,
  // and with relative intensities only these feedings make up the branch;
  // with an absolute normalisation the ground state takes what is left.
  // Capture and positrons share each feeding by their rate functions
  // (ctx.positronFraction).
  let balanced = false;
  if (!(fsum.A + fsum.B + fsum.E > 0) && (fam === 'EC' || fam === 'B-') && ctx.feedingsFromBalance) {
    const { net } = levelNet();
    const fed = [];
    let sum = 0;
    for (const lv of ds.levels) {
      if (isGround(lv)) continue;
      const d = net(lv);
      if (d > 0) { fed.push([lv, d]); sum += d; }
    }
    if (sum > 0) {
      if (relative && ctx.normaliseRelative) { NR = 100 / sum; NT = Number.isFinite(n.NT) ? n.NT : NR; }
      // In percent of the branch, never more than all of it.
      const k = Math.min(NR, 100 / sum);
      const toFeed = (lv, pc) => feedBranch(lv, fam === 'EC' ? { kind: 'E', E: NaN, IB: NaN, IE: NaN, TI: pc, UN: '', logft: NaN, cont: {} }
        : { kind: 'B', E: NaN, IB: pc, UN: '', logft: NaN, cont: {} }, { A: 1, B: 1, E: 1 });
      for (const [lv, d] of fed) toFeed(lv, d * k);
      const gs = relative ? 0 : 100 - sum * k;
      const ground = ds.levels.find(isGround) || { E: 0, J: '', offset: '', Eraw: '0' };
      if (gs > 0.01) toFeed(ground, gs);
      balanced = true;
      out.notes.push(`${ds.dsid}: no feeding intensities given, each level's from its gamma-ray balance, the ground state's ${gs > 0.01 ? `what is left (${gs.toPrecision(3)} %)` : 'none'}${relative ? `; relative intensities, NR ${NR.toPrecision(4)}` : ''}`);
    }
  }

  // An NR that the data set contradicts (ENSDF 2026's Pa-228 capture data
  // set: 0.0095 for the 0.095 of 1997, which makes every level give out a
  // tenth of its feeding): when the three estimates agree among themselves
  // (within a factor of 1.5) and all put NR more than a factor of 3 away,
  // NR (and NT) take their median. Data sets whose estimates disagree are
  // left as they are (Zr-83's capture data set: 0.18, 2.3 and 0.087).
  // Gamma rays given per 100 decays of the parent instead of the branch
  // (ENSDF 2026's two data sets of Pm-146: NR 1 with BR 0.657 and 0.343,
  // where ICRP 107's inputs had 0.985 and 1.919) show as estimates that
  // agree within 5 % and equal NR / BR within 3 %: NR is divided by BR. (The
  // reverse, NR x BR, is feedings given per parent decay, which the
  // feedings' own scaling to 100 % takes care of.)
  if (!relative && !balanced && ctx.checkBalance && fsum.A + fsum.B + fsum.E > 0) {
    const e = Object.values(nrEstimates()).sort((a, b) => a - b);
    const mid = e.length === 3 ? e[1] : NaN;
    if (e.length === 3 && e[2] / e[0] <= 1.05 && BR < 0.97 && Math.abs(Math.log(mid * BR / NR)) < Math.log(1.03)) {
      out.notes.push(`${ds.dsid}: NR ${n.NR} with the gamma rays per 100 decays of the parent (the data set's balance gives ${mid.toPrecision(4)} = NR / BR): divided by BR ${+BR.toPrecision(4)}`);
      NR /= BR; NT /= BR;
    } else if (e.length === 3 && e[2] / e[0] <= 1.5 && Math.abs(Math.log(mid / NR)) > Math.log(3)) {
      const k = mid / NR;
      out.notes.push(`${ds.dsid}: NR ${n.NR} against ${e.map((x) => x.toPrecision(3)).join(', ')} from the feedings and the gamma-ray balance: scaled by ${k.toPrecision(3)}`);
      NR *= k; NT *= k;
    }
  }

  // Relative intensities only (no NR, no production record): with
  // ctx.normaliseRelative they are scaled so that what the excited levels
  // send out net (with ctx.checkBalance), or else what reaches the ground
  // state and the member isomers, makes up the branch less its direct
  // feeding of those (Tb-154's capture data set gives neither NR nor a
  // feeding; at NR = 1 it would emit 31 MeV of photons per decay). The net
  // outflows are what ICRP 107's own NR for Lu-165 (0.15) comes out of;
  // what reaches the ground state misses whatever stops at a low level the
  // data set does not let out.
  const relativeRI = (g) => Number.isFinite(g.RI) && !Number.isFinite(num(g.cont['%IG']));
  const hasRI = ds.levels.some((lv) => lv.gammas.some(relativeRI)) || (ctx.checkBalance && ds.unplaced.gammas.some(relativeRI));
  if (relative && ctx.normaliseRelative && !hasRI && !balanced) NR = 1;
  if (relative && ctx.normaliseRelative && hasRI && !balanced) {
    let direct = 0;
    for (const lv of ds.levels) if (isGround(lv) || memberAt.has(lv)) direct += feedIn.get(lv);
    let how = '';
    if (ctx.checkBalance) {
      const { net } = levelNet();
      let pos = 0;
      for (const lv of ds.levels) if (!isGround(lv) && !memberAt.has(lv)) pos += Math.max(0, net(lv));
      if (pos > 0 && 100 * BR > direct) { NR = (100 * BR - direct) / (BR * pos); how = "so that the levels' net outflows make up the branch"; }
    }
    if (!how) {
      const atRest = (to) => to && (isGround(to) || memberAt.has(to));
      let toRest = 0;
      for (const lv of ds.levels) {
        if (memberAt.has(lv)) continue;
        for (const g of lv.gammas) {
          if (Number.isFinite(num(g.cont['%IG']))) continue;
          if (atRest(destOf(g, lv))) toRest += Number.isFinite(g.RI) ? g.RI * (1 + alphaOf(g, lv)) : Number.isFinite(g.TI) ? g.TI : 0;
        }
      }
      if (toRest > 0 && 100 * BR > direct) { NR = (100 * BR - direct) / (BR * toRest); how = 'so that what reaches the ground state makes up the branch'; }
      else if (ctx.checkBalance) {
        // Nothing to scale them by (Os-178's capture data set: 14 unplaced
        // gamma rays, no levels): they are left out, and a branch with no
        // feeding either is taken to the ground state.
        NR = 0;
        how = 'by nothing in the data set: its gamma rays are left out';
        if (!(fsum.A + fsum.B + fsum.E > 0) && (fam === 'EC' || fam === 'B-')) {
          const ground = ds.levels.find(isGround) || { E: 0, J: '', offset: '', Eraw: '0' };
          feedBranch(ground, fam === 'EC' ? { kind: 'E', E: NaN, IB: NaN, IE: NaN, TI: 100, UN: '', logft: NaN, cont: {} }
            : { kind: 'B', E: NaN, IB: 100, UN: '', logft: NaN, cont: {} }, { A: 1, B: 1, E: 1 });
          how += ', the branch taken to the ground state';
        }
      } else { NR = 1; how = 'as given (NR 1)'; }
    }
    NT = Number.isFinite(n.NT) ? n.NT : NR;
    out.notes.push(`${ds.dsid}: relative intensities only, scaled ${how} (NR ${NR.toPrecision(4)})`);
  }

  // The gamma rays below a member isomer carry the isomer's own decay as
  // well when the data set lists the isomer's transitions (Ir-190n's
  // capture feeds Os-190m, whose cascade through the 6+, 4+ and 2+ levels
  // the data set gives with the rest): that part is the isomer's. Each
  // level's gamma rays lose the share of its outflow that the members'
  // transitions bring down, carried through the cascade in the data set's
  // proportions (ctx.memberCascades false: EDISTR's way, no such share).
  const ownShare = new Map();
  if (memberAt.size && ctx.memberCascades !== false) {
    const flow = new Map();
    for (const lv of [...ds.levels].sort((a, b) => b.E - a.E)) {
      const outs = lv.gammas.map((g) => [rawTotal(g, lv, NR, NT), destOf(g, lv)]).filter(([t]) => t > 0);
      const S = outs.reduce((x, [t]) => x + t, 0);
      if (!(S > 0)) continue;
      const f = memberAt.has(lv) ? S : Math.min(S, flow.get(lv) || 0);
      if (!(f > 0)) continue;
      if (!memberAt.has(lv)) ownShare.set(lv, 1 - f / S);
      for (const [t, to] of outs) if (to && to !== lv) flow.set(to, (flow.get(to) || 0) + f * t / S);
    }
    const moved = [...ownShare.values()].filter((x) => x < 0.999).length;
    if (moved) out.notes.push(`${ds.dsid}: the cascade of member isomers (${[...new Set(memberAt.values())].join(', ')}) taken out of ${moved} levels below them`);
  }

  // Gamma rays and their conversion electrons, level by level from the top,
  // so that what enters a level (its feeding and the transitions from above)
  // is known when it is let out.
  const enter = new Map(feedIn);
  /* A transition's photons and total intensity per decay, and its coefficients. */
  function intensity(lv, g) {
    if (!(g.E > 0)) return null;
    const own = lv ? ownShare.get(lv) ?? 1 : 1;
    if (!(own > 0)) return null;
    const coef = coefficients(g, lv);
    const alpha = coef ? Object.values(coef).reduce((x, y) => x + (y > 0 ? y : 0), 0) : 0;
    // A total transition intensity, where the data set gives one, is what
    // EDISTR starts from; the photons are then what the conversion
    // coefficients leave (Cd-109: TI 100 and alpha 26.8 give 0.0360 photons
    // per decay, not the 0.0370 of RI). A pure E0 transition has no photons;
    // an intensity in its RI field is the transition's own (Ir-196's three
    // E0 transitions are written so).
    let photons, total;
    const ig = num(g.cont['%IG']);
    const e0 = /^\W*E0\W*$/.test(g.MUL);
    if (e0 && (Number.isFinite(g.TI) || Number.isFinite(g.RI))) {
      total = (Number.isFinite(g.TI) ? g.TI * NT : g.RI * NR) * BR / 100;
      photons = 0;
    } else if (Number.isFinite(g.TI) && (ctx.transitionFirst !== false || !Number.isFinite(g.RI))) {
      total = g.TI * NT * BR / 100;
      photons = total / (1 + alpha);
    } else if (Number.isFinite(ig)) { photons = ig / 100; total = photons * (1 + alpha); }
    else if (Number.isFinite(g.RI)) { photons = g.RI * NR * BR / 100; total = photons * (1 + alpha); }
    else return null;
    return { g, coef, alpha, photons: photons * own, total: total * own };
  }
  // Conversion that nothing measured: a gamma ray with neither a
  // multipolarity nor a conversion coefficient of the evaluators', whose
  // coefficients are the default multipole's.
  const unmeasured = (g) => !String(g.MUL || '').trim() && !Number.isFinite(g.CC) && !Number.isFinite(g.TI)
    && !Object.keys(g.cont).some((k) => /^(?:[KLMNOPQ]\d?C\+?|CC)$/.test(k));
  function emit(lv, it) {
    const { g, coef, alpha, photons, total } = it;
    if (photons > 0) out.lines.push({ type: 'G', E: g.E, Y: photons });
    if (coef && atom && total > 0) {
      const ce = total - photons;
      const sumA = alpha || 1;
      for (const [name, a] of Object.entries(coef)) {
        if (!(a > 0)) continue;
        const y = ce * a / sumA;
        if (!(y > 0)) continue;
        // A transition cannot free an electron bound more strongly than its
        // own energy: such a share goes to the most bound subshell it can
        // reach (U-235m's 76 eV transition converts in the P and Q shells,
        // not in the N and O shells a generic split would give it).
        const shell = openShell(atom, name, g.E);
        const B = shell ? atom.binding[shell] : 0;
        out.lines.push({ type: 'IE', shell: shell || name, gamma: g.E, Z: Zd, E: Math.max(0, g.E - B), Y: y, BM3: atom.binding.M3 });
        if (shell) addVac(shell, y);
      }
    }
    if (lv) {
      const to = destOf(g, lv);
      if (to && to !== lv && enter.has(to)) enter.set(to, enter.get(to) + total * 100);
    }
  }
  for (const g of ds.unplaced.gammas) { const it = intensity(null, g); if (it) emit(null, it); }
  for (const lv of [...ds.levels].sort((a, b) => b.E - a.E)) {
    if (memberAt.has(lv)) continue; // the isomer's own decay
    const its = lv.gammas.map((g) => intensity(lv, g)).filter(Boolean);
    // No level sends out more than enters it: where its transitions add up
    // to more than 3 times that, the conversion nothing measured is cut
    // to fit (with ctx.checkBalance; a 28.7 keV gamma ray of Th-229's alpha
    // decay, 0.1 % without a multipolarity, would as the default E2 make
    // four transitions per decay). What enters a level is at least what its
    // photons and measured conversion take out: data sets list gamma rays of
    // levels whose feeding is too weak to list.
    const measuredOut = its.reduce((t, x) => t + (unmeasured(x.g) ? x.photons : x.total), 0);
    const P = Math.max(enter.get(lv) / 100, measuredOut);
    const sum = its.reduce((t, x) => t + x.total, 0);
    if (ctx.checkBalance && sum > 3 * P) {
      const free = its.filter((x) => unmeasured(x.g) && x.total > x.photons);
      const ceFree = free.reduce((t, x) => t + x.total - x.photons, 0);
      if (ceFree > 0) {
        const f = Math.max(0, ceFree - (sum - P)) / ceFree;
        for (const x of free) x.total = x.photons + f * (x.total - x.photons);
        out.notes.push(`${ds.dsid}: the level at ${lv.Eraw} keV sends out ${(sum / Math.max(P, 1e-12)).toPrecision(3)} times what enters it: the conversion of ${free.map((x) => x.g.Eraw).join(', ')} keV (no multipolarity given) cut by ${f < 1e-6 ? '0' : f.toPrecision(3)}`);
      }
    }
    for (const it of its) {
      emit(lv, it);
    }
  }

  // A level the cascade reaches but this data set lets out by no gamma ray:
  // an isomer whose own data set carries on (ENSDF 2026's IT data set of
  // Hf-177m stops at the 1.09 s isomer at 1315 keV, whose cascade the other
  // IT data set gives). With ctx.continuation(Z, A, level) -> the isomer's
  // stateRadiations, its radiations follow, scaled by what reaches the
  // level, and so do its branches that end elsewhere than this daughter's
  // ground state.
  let toMembers = 0;
  const continued = new Set();
  if (ctx.continuation) {
    for (const lv of ds.levels) {
      if (isGround(lv) || memberAt.has(lv) || lv.gammas.length) continue;
      const pop = enter.get(lv) / 100;
      if (!(pop > 1e-9)) continue;
      const c = ctx.continuation(Zd, Ad, lv);
      if (!c) continue;
      continued.add(lv);
      for (const ln of c.lines) out.lines.push({ ...ln, Y: ln.Y * pop });
      for (const b of c.betas) out.betas.push({ ...b, yield: b.yield * pop });
      for (const b of c.branches) {
        if (!(b.br > 0) || (!b.to.member && b.to.Z === Zd && b.to.A === Ad)) continue;
        out.branches.push({ to: b.to, br: b.br * pop });
        toMembers += b.br * pop;
      }
      out.notes.push(`${ds.dsid}: the level at ${lv.Eraw} keV${lv.Traw ? ` (${lv.Traw})` : ''}, reached by ${(pop * 100).toPrecision(3)} % of the decays, carried on by its own decay data set`);
    }
  }

  // A level the branch reaches that the data set lets out by no gamma ray
  // and nothing carries on (ENSDF 2026's Lu-165 capture data set puts 16 %
  // of the decays on pseudo levels at 2.8-3.6 MeV from a total-absorption
  // measurement): with ctx.unlistedDeexcitation its energy goes out as one
  // gamma ray to the ground state, from 200 keV up (below, a transition left
  // out is a highly converted one, whose electrons are left out as well).
  if (ctx.unlistedDeexcitation) {
    const left = [];
    for (const lv of ds.levels) {
      if (isGround(lv) || lv.offset || memberAt.has(lv) || lv.gammas.length || continued.has(lv) || !(lv.E >= 200)) continue;
      const pop = enter.get(lv) / 100;
      if (!(pop > 1e-6)) continue;
      out.lines.push({ type: 'G', E: lv.E, Y: pop });
      left.push(`${lv.Eraw} (${(pop * 100).toPrecision(3)} %)`);
    }
    if (left.length) out.notes.push(`${ds.dsid}: levels fed and let out by no gamma ray given, their energy taken as one gamma ray each to the ground state: ${left.join(', ')} keV`);
  }

  // Where the branch comes to rest: each member level takes what enters it,
  // the ground state the rest of the branch. Unless nothing the data set
  // gives reaches the ground state and the parent's spin rules out feeding
  // it directly (a change of 3 or more): then what the intensities leave
  // unaccounted is the members', in proportion (Sn-128's beta-minus data
  // set brings 90 % of the decays down to Sb-128m and none to the 8- ground
  // state, which its 0+ parent cannot feed).
  const toMember = [];
  for (const [lv, name] of memberAt) {
    const x = enter.get(lv) / 100;
    if (x > 0) toMember.push([lv, name, x]);
  }
  const memberSum = toMember.reduce((t, [, , x]) => t + x, 0);
  const groundLv = ds.levels.find(isGround);
  const groundIn = groundLv ? enter.get(groundLv) / 100 : 0;
  const pj = firstSpin(parentJ), gj = firstSpin(groundLv?.J);
  let k = 1;
  if (ctx.checkBalance && memberSum > 0 && !(groundIn > 1e-9) && pj && gj && Math.abs(pj.J - gj.J) >= 3 && BR - toMembers - memberSum > 1e-3 * BR) {
    k = (BR - toMembers) / memberSum;
    out.notes.push(`${ds.dsid}: ${((BR - toMembers - memberSum) / BR * 100).toPrecision(3)} % of the branch unaccounted and the ground state (${groundLv.J}) out of the parent's (${parentJ}) reach: given to ${toMember.map(([, nm]) => nm).join(', ')}`);
  }
  for (const [lv, name, x] of toMember) { out.branches.push({ to: { Z: Zd, A: Ad, E: lv.E, member: name }, br: x * k }); toMembers += x * k; }
  const rest = BR - toMembers;
  out.branches.push({ to: { Z: Zd, A: Ad, E: 0, member: null }, br: rest > 1e-9 * BR ? rest : 0, raw: rest, fam });

  // Atomic radiations of the vacancies in the daughter atom (ctx.relaxable
  // can leave some subshells out: EDISTR04 relaxed none beyond O).
  if (atom && Zd >= (ctx.minAtomicZ ?? 11)) {
    const v = ctx.relaxable ? Object.fromEntries(Object.entries(vac).filter(([k]) => ctx.relaxable(k))) : vac;
    for (const ln of atom.relax(v)) out.lines.push({ ...ln, type: ln.kind === 'X' ? 'X' : 'AE', E: ln.E * 1000 });
  }
  for (const [k, v] of Object.entries(vac)) out.vacancies[k] = (out.vacancies[k] || 0) + v;
}

/* ---------------------------------------------------------------------------
   A nuclide's record, in the form the dose engines read (dose-decay.mjs)
   --------------------------------------------------------------------------- */

const MEV = (keV) => keV / 1000;

/* The half-life as the ICRP files write it: "30.1671y", "6.015h", "2.10m". */
export function halfLifeText(s) {
  if (!Number.isFinite(s)) return 'stable';
  const units = [['y', YEAR_S], ['d', 86400], ['h', 3600], ['m', 60], ['s', 1], ['ms', 1e-3], ['us', 1e-6]];
  let [u, f] = units.find(([, x]) => s >= x) || units[units.length - 1];
  if (u === 'd' && s >= 1000 * 86400) [u, f] = ['y', YEAR_S];
  const v = s / f;
  const txt = v >= 1e5 ? v.toExponential(3).replace(/\.?0+e/, 'E').replace('E+', 'E') : String(+v.toPrecision(6));
  return txt + u;
}

/*
  Conversion electrons are written per shell the way ICRP 107 writes them:
  K, L1, L2, L3, M (all M subshells, at the energy E - B(M3)) and N+ (the
  rest, at the transition energy), whatever subshells the vacancies were
  counted in.
*/
function electronGroup(shell) {
  if (shell === 'K' || shell === 'L1' || shell === 'L2' || shell === 'L3') return shell;
  if (/^M/.test(shell)) return 'M';
  return 'N+';
}

/**
 * The record of one parent state.
 *
 * @param {object} state  parentStates() entry
 * @param {object} res    stateRadiations() result
 * @param {object} opt    {name, daughterName(Z, A, member) -> name, beta: {shape, spectrum},
 *                         atom: the parent's daughter atom {binding}, sf: [[E, Y, kind]] fission lines
 *                         in MeV, sfSpectrum, edistr: electron energies as ICRP 107 writes them}
 * @returns {object} {name, t, T (days), mode, d, E, rad, bs, betaLines}
 */
export function decayRecord(state, res, opt) {
  const rad = { p: [], b: [], e: [], a: [], ar: [], ff: [], n: [] };
  const groups = new Map(); // conversion lines grouped per gamma and shell group
  for (const l of res.lines) {
    if (l.type === 'G' || l.type === 'X' || l.type === 'AQ') rad.p.push([MEV(l.E), l.Y]);
    else if (l.type === 'A') rad.a.push([MEV(l.E), l.Y]);
    else if (l.type === 'AR') rad.ar.push([MEV(l.E), l.Y]);
    else if (l.type === 'AE') rad.e.push([MEV(l.E), l.Y]);
    else if (l.type === 'IE') {
      const g = electronGroup(l.shell);
      // One line per gamma ray and shell group, and per atom: an IT gamma
      // ray and a beta branch's of the same energy convert in different atoms.
      const key = `${l.Z}|${l.gamma ?? l.E}|${g}`;
      const cur = groups.get(key) || { E: 0, Y: 0, Eg: l.gamma, g, BM3: l.BM3 };
      cur.Y += l.Y; cur.E += l.Y * l.E;
      groups.set(key, cur);
    }
  }
  for (const c of groups.values()) {
    if (!(c.Y > 0)) continue;
    let E = c.E / c.Y;
    // ICRP 107 writes the M group at E - B(M3) and N+ at the transition
    // energy itself (counting N+'s binding energy twice, once more in the
    // relaxation); opt.edistr follows it, for comparisons with ICRP 107.
    if (opt.edistr && Number.isFinite(c.Eg)) {
      if (c.g === 'M' && c.BM3 > 0) E = c.Eg - c.BM3;
      else if (c.g === 'N+') E = c.Eg;
    }
    rad.e.push([MEV(E), c.Y]);
  }
  // beta-spectrum.js: betaShape for each branch's mean, betaSpectrum for the sum.
  const shape = opt.beta.betaShape || opt.beta.shape, spectrum = opt.beta.betaSpectrum || opt.beta.spectrum;
  const betaLines = [];
  for (const b of res.betas) {
    const mean = shape(b).mean; // MeV
    rad.b.push([mean, b.yield]);
    betaLines.push({ ...b, mean });
  }
  // Delayed betas of fission (opt.sfBetas) belong in the spectrum as well.
  const branches = [...res.betas, ...(opt.sfBetas || [])];
  let bs = branches.length ? spectrum(branches) : null;
  for (const [E, Y, kind] of opt.sf || []) (kind === 'FF' ? rad.ff : kind === 'N' ? rad.n : kind === 'BD' ? rad.b : rad.p).push([E, Y]);
  if (opt.sfSpectrum) bs = bs ? addSpectra(bs, opt.sfSpectrum) : opt.sfSpectrum;
  for (const k of Object.keys(rad)) rad[k].sort((p, q) => p[0] - q[0]);

  // Where the decays go: one entry per daughter, the branches of all modes added.
  const d = new Map();
  for (const br of res.branches) {
    const name = br.to.member || opt.daughterName(br.to.Z, br.to.A, null);
    if (br.br > 0 && name !== opt.name) d.set(name, (d.get(name) || 0) + br.br);
  }
  const sum = (k) => rad[k].reduce((s, [e, y]) => s + e * y, 0);
  const fams = new Set(res.modes);
  const hasBplus = res.betas.some((b) => b.positron);
  const mode = [fams.has('IT') && 'IT', fams.has('EC') && (hasBplus ? 'ECB+' : 'EC'), fams.has('B-') && 'B-', fams.has('A') && 'A', res.sf && 'SF']
    .filter(Boolean).join('');
  return {
    name: opt.name, t: halfLifeText(state.T), T: state.T / 86400, mode,
    d: [...d].sort((p, q) => q[1] - p[1]), E: [sum('a') + sum('ar'), sum('b') + sum('e'), sum('p')],
    rad, bs, betaLines,
  };
}

/** Two spectra on the same grid added (the longer grid wins). */
function addSpectra(a, b) {
  const [ea, na] = a, [eb, nb] = b;
  const E = ea.length >= eb.length ? ea : eb;
  const at = (es, ns, e) => {
    if (e <= es[0]) return ns[0];
    if (e >= es[es.length - 1]) return 0;
    let k = 0; while (es[k + 1] < e) k++;
    return ns[k] + (ns[k + 1] - ns[k]) * (e - es[k]) / (es[k + 1] - es[k]);
  };
  return [E, E.map((e) => at(ea, na, e) + at(eb, nb, e))];
}
