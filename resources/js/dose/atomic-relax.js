/*
  Atomic relaxation: the X-rays and the Auger and Coster-Kronig electrons an
  atom emits while the inner-shell vacancies that electron capture and
  internal conversion leave move outwards. ENSDF lists none of these; the
  code that made ICRP Publication 107 from ENSDF, EDISTR04, computed them
  from the vacancies (Endo, Yamaguchi and Eckerman, JAERI 1347, 2005,
  section 3.1.4 and Appendix A), and this does the same.

  Method. EDISTR04's routine SRELAX is the computational part of D.E. Cullen's
  RELAX (UCRL-ID-110438, 1992) over the Livermore Evaluated Atomic Data
  Library, EADL (Perkins et al., UCRL-50400 Vol. 30, 1991). A vacancy in
  subshell i is filled either by a radiative transition i -> j, an X-ray of
  energy B_i - B_j that moves the vacancy to j, or by a non-radiative one
  i -> j,k, an electron of energy B_i - B_j - B_k that leaves vacancies in j
  and k, with EADL's probabilities for a singly ionised atom. Vacancies only
  move to less bound subshells, so the expected numbers follow in one pass
  from the inside out: a subshell's vacancies, its own and those its inner
  subshells feed it, are shared among its transitions. Vacancies that reach a
  subshell with no transitions (the outermost ones) are filled from the
  continuum, one "free-bound" photon each, as RELAX assumes.

  Three details come from reproducing EDISTR04's own output (the
  ARCHIVE/OUTPUT files and ICRP-07.ACK of ICRP 107's package) with the 1991
  library:
  - EADL keeps some non-radiative transitions that its binding energies put
    below threshold (Te M1-M2N2 at -7 eV, ...). EDISTR04 moves their
    vacancies on to j and k but emits no electron; so does this.
  - The free-bound photons carry what is left of the initial vacancies'
    energy once the X-rays and electrons are counted, so the emitted energy
    equals the vacancies' binding energy exactly. Without transitions below
    threshold that is the binding energy of each final vacancy; with them,
    a little less (EDISTR04's free-bound mean energy says so).
  - The lines are grouped as in JAERI 1347 Appendix A: K and L X-rays one by
    one, INDEX 1-16 (K), 21-36 (L1), 41-55 (L2), 61-83 (L3); every M, N and
    O X-ray in one line each, 91, 92 and 93; free-bound 94; Auger and CK
    electrons in 15 groups, KLL ... OXY. A group's energy is its
    yield-weighted mean. Every radiative transition in the 1991 and 2017
    libraries has its INDEX; no subshell beyond O has transitions.

  EDISTR04 lists no atomic radiation at all when the atom has Z <= 10
  (ICRP 107: Na-22 -> Ne has none, Ne-24 -> Na has X-rays). That is the
  caller's to apply; relaxation() computes whatever it is given.

  Tables: resources/data/dose/atomic/<symbol>.json, made by
  scripts/gen-dose-atomic.mjs from the atomic relaxation sub-library of
  ENDF/B-VIII.0, which is EPICS2017 (Cullen, IAEA-NDS-224, 2017): EADL's
  transition probabilities with newer binding energies. Line energies come
  from those binding energies, never from the library's transition energies.
*/

/** Subshell names in ENDF-6 order: MF28 designator d is SUBSHELLS[d - 1]. */
export const SUBSHELLS = ['K', 'L1', 'L2', 'L3', 'M1', 'M2', 'M3', 'M4', 'M5',
  'N1', 'N2', 'N3', 'N4', 'N5', 'N6', 'N7', 'O1', 'O2', 'O3', 'O4', 'O5', 'O6', 'O7', 'O8', 'O9',
  'P1', 'P2', 'P3', 'P4', 'P5', 'P6', 'P7', 'P8', 'P9', 'P10', 'P11', 'Q1', 'Q2', 'Q3'];

// JAERI 1347 Table A.1: the subshells a K or L vacancy is filled from, in INDEX order.
const XRAY = {
  K: [1, ['L2', 'L3', 'M2', 'M3', 'M4', 'M5', 'N2', 'N3', 'N4', 'N5', 'O2', 'O3', 'O4', 'O5', 'P2', 'P3']],
  L1: [21, ['L2', 'L3', 'M2', 'M3', 'M4', 'M5', 'N2', 'N3', 'N4', 'N5', 'O2', 'O3', 'O4', 'O5', 'P2', 'P3']],
  L2: [41, ['L3', 'M1', 'M3', 'M4', 'N1', 'N3', 'N4', 'N6', 'O1', 'O3', 'O4', 'O6', 'P1', 'P3', 'Q1']],
  L3: [61, ['M1', 'M2', 'M3', 'M4', 'M5', 'N1', 'N2', 'N3', 'N4', 'N5', 'N6', 'N7',
    'O1', 'O2', 'O3', 'O4', 'O5', 'O6', 'O7', 'P1', 'P2', 'P3', 'Q1']],
};
const X_SERIES = { M: 91, N: 92, O: 93 };

/** INDEX of the free-bound photons. */
export const FREE_BOUND = 94;

/** Names of the X-ray INDEXes: 'K-L3' (IUPAC), 'M', 'N', 'O', 'free-bound'. */
export const X_LABELS = { 91: 'M', 92: 'N', 93: 'O', [FREE_BOUND]: 'free-bound' };
for (const [i, [base, to]] of Object.entries(XRAY)) to.forEach((j, p) => { X_LABELS[base + p] = `${i}-${j}`; });

/** Names of the Auger and Coster-Kronig groups 1-15 (JAERI 1347 Table A.2). */
export const AE_LABELS = [null, 'KLL', 'KLX', 'KXY', 'CK LLX', 'LMM', 'LMX', 'LXY', 'CK MMX',
  'MNN', 'MNX', 'MXY', 'CK NNX', 'NXY', 'CK OOX', 'OXY'];

/**
 * EDISTR04's X-ray INDEX for a vacancy in subshell i filled from subshell j.
 * @returns {number|undefined}
 */
export function xIndex(i, j) {
  const x = XRAY[i];
  if (x) { const p = x[1].indexOf(j); return p < 0 ? undefined : x[0] + p; }
  return X_SERIES[i[0]];
}

/**
 * EDISTR04's Auger/CK group (1-15) for a vacancy in i that leaves vacancies in j and k.
 * K: both new vacancies in L (KLL), one (KLX), none (KXY). L, M: any in the same
 * shell is Coster-Kronig (LLX, MMX), else both, one or none in the next shell
 * (LMM, LMX, LXY; MNN, MNX, MXY). N and O: Coster-Kronig (NNX, OOX) or not (NXY, OXY).
 * @returns {number|undefined}
 */
export function augerIndex(i, j, k) {
  const s = i[0], a = j[0], b = k[0];
  if (s === 'K') return [3, 2, 1][(a === 'L') + (b === 'L')];
  const ck = { L: 4, M: 8, N: 12, O: 14 }[s];
  if (ck === undefined) return undefined;
  if (a === s || b === s) return ck;
  if (s === 'N' || s === 'O') return ck + 1;
  const next = s === 'L' ? 'M' : 'N';
  return ck + 3 - ((a === next) + (b === next));
}

// Per table: transitions with their energies and groups, and an order in which
// every subshell comes before the subshells its vacancies move to.
const compiled = new WeakMap();
function compile(table) {
  let c = compiled.get(table);
  if (c) return c;
  const names = table.shells, m = names.length;
  const B = table.E.map((e) => e / 1e6); // MeV
  const eV = table.E; // line energies from differences in eV, then MeV: no needless rounding
  const tr = names.map((i, s) => {
    const list = [];
    const x = table.x[s] || [], a = table.a[s] || [];
    for (let q = 0; q < x.length; q += 2) {
      const j = x[q];
      list.push({ j, k: -1, p: x[q + 1], E: (eV[s] - eV[j]) / 1e6, kind: 'X', index: xIndex(i, names[j]), label: `${i}-${names[j]}` });
    }
    for (let q = 0; q < a.length; q += 3) {
      const j = a[q], k = a[q + 1];
      list.push({ j, k, p: a[q + 2], E: (eV[s] - eV[j] - eV[k]) / 1e6, kind: 'AE', index: augerIndex(i, names[j], names[k]), label: `${i}-${names[j]}${names[k]}` });
    }
    for (const t of list) if (t.index === undefined) throw new Error(`${table.symbol}: ${t.label} has no EDISTR04 group`);
    // The libraries' probabilities add up to 1 within 1e-6; exactly 1 keeps the number
    // of vacancies, and so the free-bound energy, right (EDISTR04's agrees).
    const sum = list.reduce((acc, t) => acc + t.p, 0);
    for (const t of list) t.p /= sum;
    return list;
  });
  // Kahn's algorithm; ties by binding energy, most bound first
  const indeg = new Array(m).fill(0);
  for (const list of tr) for (const t of list) { indeg[t.j]++; if (t.k >= 0) indeg[t.k]++; }
  const ready = names.map((_, s) => s).filter((s) => !indeg[s]);
  const order = [];
  while (ready.length) {
    ready.sort((p, q) => B[q] - B[p]);
    const s = ready.shift();
    order.push(s);
    for (const t of tr[s]) for (const d of t.k >= 0 ? [t.j, t.k] : [t.j]) if (!--indeg[d]) ready.push(d);
  }
  if (order.length !== m) throw new Error(`${table.symbol}: the transitions go round in a circle`);
  c = { names, B, tr, order, pos: new Map(names.map((n, s) => [n, s])) };
  compiled.set(table, c);
  return c;
}

/**
 * An element's subshells, in designator order.
 * @param {object} table  the element's JSON from resources/data/dose/atomic/
 * @returns {Array<{name: string, E: number, n: number}>}  E binding energy (MeV), n electrons
 */
export function subshells(table) {
  return table.shells.map((name, s) => ({ name, E: table.E[s] / 1e6, n: table.n[s] }));
}

/**
 * Binding energy (MeV) of one subshell, e.g. for a conversion electron's
 * energy (E_gamma - B) or the neutrino of electron capture from it.
 * @throws if the element has no such subshell
 */
export function bindingEnergy(table, name) {
  const s = table.shells.indexOf(name);
  if (s < 0) throw new Error(`${table.symbol} has no ${name} subshell`);
  return table.E[s] / 1e6;
}

/**
 * One element, as the ENSDF processor uses it: binding energies by subshell name, and
 * relax(), which is relaxation() except that it skips vacancies in subshells the element
 * lacks (their energy is then not emitted) instead of refusing them.
 * @param {object} table  the element's JSON from resources/data/dose/atomic/
 * @returns {{Z: number, symbol: string, binding: Object<string, number>,
 *   relax: (vacancies: Object<string, number>, opt?: {detail?: boolean}) => Array<object>}}
 *   binding in keV, {K: ..., L1: ..., ...} for the element's own subshells
 */
export function element(table) {
  const binding = {};
  table.shells.forEach((name, s) => { binding[name] = table.E[s] / 1e3; });
  const own = new Set(table.shells);
  return {
    Z: table.Z, symbol: table.symbol, binding,
    relax(vacancies, opt) {
      const known = {};
      for (const [name, v] of Object.entries(vacancies)) if (own.has(name)) known[name] = v;
      return relaxation(table, known, opt);
    },
  };
}

/**
 * The X-rays and Auger/CK electrons that a distribution of vacancies relaxes into.
 * @param {object} table  the element's JSON from resources/data/dose/atomic/
 * @param {Object<string, number>} vacancies  vacancies per decay by subshell, e.g.
 *   {K: 0.80, L1: 0.25, L2: 0.013, M1: 0.054}; a subshell the element lacks is an error
 * @param {{detail?: boolean}} [opt]  detail: every transition as its own line (its
 *   `index` still the group's) instead of EDISTR04's groups
 * @returns {Array<{kind: 'X'|'AE', index: number, label: string, E: number, Y: number}>}
 *   X-rays by INDEX then electrons by group; E in MeV (a group's yield-weighted mean),
 *   Y per decay. The free-bound line is {kind: 'X', index: 94}.
 */
export function relaxation(table, vacancies, opt = {}) {
  const c = compile(table);
  const n = new Float64Array(c.names.length);
  let energy = 0; // MeV per decay held by the initial vacancies
  for (const [name, v] of Object.entries(vacancies)) {
    const s = c.pos.get(name);
    if (s === undefined) throw new Error(SUBSHELLS.includes(name) ? `${table.symbol} has no ${name} subshell` : `no subshell "${name}"`);
    if (!(v >= 0) || v === Infinity) throw new Error(`vacancies in ${name}: ${v}`);
    n[s] += v;
    energy += v * c.B[s];
  }
  const groups = new Map(), lines = [];
  let free = 0;
  for (const s of c.order) {
    const ns = n[s];
    if (!ns) continue;
    if (!c.tr[s].length) { free += ns; continue; }
    for (const t of c.tr[s]) {
      const y = ns * t.p;
      n[t.j] += y;
      if (t.k >= 0) n[t.k] += y;
      if (!(t.E > 0)) continue; // below threshold: the vacancies move on, nothing is emitted
      energy -= y * t.E;
      if (opt.detail) { lines.push({ kind: t.kind, index: t.index, label: t.label, E: t.E, Y: y }); continue; }
      const key = t.kind === 'X' ? t.index : 100 + t.index;
      const g = groups.get(key);
      if (g) { g.Y += y; g.EY += y * t.E; } else groups.set(key, { kind: t.kind, index: t.index, Y: y, EY: y * t.E });
    }
  }
  const out = opt.detail
    ? lines.sort((p, q) => (p.kind === q.kind ? p.index - q.index : p.kind === 'X' ? -1 : 1))
    : [...groups].sort((p, q) => p[0] - q[0]).map(([, g]) => ({
      kind: g.kind, index: g.index, label: g.kind === 'X' ? X_LABELS[g.index] : AE_LABELS[g.index], E: g.EY / g.Y, Y: g.Y }));
  if (free > 0) {
    const fb = { kind: 'X', index: FREE_BOUND, label: X_LABELS[FREE_BOUND], E: Math.max(energy, 0) / free, Y: free };
    const at = out.findIndex((l) => l.kind === 'AE');
    out.splice(at < 0 ? out.length : at, 0, fb);
  }
  return out;
}
