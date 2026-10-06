/*
  Internal conversion by atomic subshell for the gamma transitions of ENSDF
  decay data sets: how many conversion electrons each transition sends out
  of which subshell, per gamma ray, for the conversion-electron lines
  (E_gamma - B_subshell) and for the vacancies whose X-rays and Auger
  electrons follow (atomic-relax.js).

  EDISTR04, the code that made ICRP Publication 107 from ENSDF (Endo,
  Yamaguchi and Eckerman, JAERI 1347, 2005, sec. 3.1.3; Dillman, ORNL/TM-6689,
  1980, sec. 1.4), took theoretical coefficients for every subshell (Rösel et
  al. 1978; Band and Trzhaskovskaya for E5 and M5) for the multipolarity of
  the MUL field or, without one, of the levels' spins and parities, mixed
  two multipoles by the mixing ratio delta,

      alpha(M1+E2) = (alpha(M1) + delta^2 alpha(E2)) / (1 + delta^2),

  and scaled them to the evaluator's total CC where the two differed by more
  than 10 %. Current ENSDF gives more: the total CC on the G record and, for
  most converted transitions, the shell values KC, LC, MC, NC+ (or NC, OC,
  PC, QC) on its continuation, which the evaluators compute with BrIcc. So:

    shells  ENSDF's shell values are used as given, being the evaluators'
            choice, and only split into subshells: L by the table's
            L1:L2:L3, M and N+ (see below). A CC larger than the shells
            given leaves a remainder for the shells not given, in the
            table's proportions. Above 1022 keV CC (BrIcc's total) includes
            internal pair formation: ENSDF's IPC is taken off it, and
            without IPC it is used as an upper bound only.
    total   with only CC, the table's K:L1:L2:L3:M:N+ proportions for the
            multipolarity (mixed by delta when given) times CC.
    theory  with neither, the table's values for the multipolarity; for a
            placed gamma without one, EDISTR's rule: the lowest multipole the
            spins and parities allow (when the caller gives them), else M1 at
            Z <= 50 and E2 above. An unplaced gamma without one gets none:
            ENSDF's intensity balances leave unplaced gammas out, and so did
            EDISTR04 (JAERI 1347 p. 16).
    E0      a pure E0 transition has no gamma ray; its electrons come from
            the K, L, M and N+ shells in the proportions of an M1 transition's
            (Dillman sec. 1.4), from the s1/2 and p1/2 subshells only (an
            electric monopole reaches no others): EDISTR04's printed ratios
            "K/L1/M/N+" are M1's K : L1 + L2 : M : N+. The values returned
            are M1's, to be used as proportions of the transition's intensity.
  With opt.mode 'edistr04' the module does what EDISTR04 did instead: theory
  always, scaled to CC only beyond 10 %, ENSDF's shell values not read,
  unplaced gammas never converted; for checks against ICRP 107.

  The table (icc.json, from scripts/gen-dose-icc.mjs) is fitted to the
  coefficients EDISTR04 printed for ICRP 107 and so is the theory EDISTR04
  applied: log10 alpha of each pure multipolarity and shell group K, L1, L2,
  L3, M, N+ as cubic B-splines in ln Z and in log10(E/B) (K and L subshells,
  B the binding energy) or log10(E/keV) (M, N+); E5 and M5, of which ICRP 107
  has a handful, as the linear extrapolation in multipole order from E3 and
  E4 (M3, M4) times a constant per shell. Below Z = 30 (EDISTR04's older
  bank, K and L only) and beyond the energies where a shell's coefficient
  falls under 0.001 (nothing smaller was printed) the table is not used:
  the module continues it by physics (below, at alphaOf).
  The table knows M and N+ only as totals; this module splits them like the
  L subshells of the same kind, M1:M2:M3 as L1:L2:L3 at the same electron
  energy (the L coefficients evaluated at E - B(Mi) + B(Li)), M4 and M5 (3d,
  with no L counterpart, converting little but at low energy in heavy atoms)
  none; N+ the same way into N1-N3, or, when ENSDF gives NC, OC, PC and QC
  apart, each into its own s, p1/2 and p3/2 subshells. Subshells the atom
  lacks or whose binding energy is above E take no share. E6 and above,
  beyond the table (and EDISTR04's), get no theoretical values; ENSDF's own
  are split with E5's (M5's) proportions.

  Multipolarity (ENSDF's MUL field):
    [E2]            square brackets: assigned from the level scheme; used.
    (M1)            parentheses: uncertain; used.
    M1+E2           a mixture, delta from MR; without MR the lower multipole
                    alone (Dillman). E2+M1 is the same mixture (MR is always
                    the higher order's amplitude over the lower's).
    M1(+E2), M1+(E2), E1(+M2)   the same as M1+E2, E1+M2.
    E1+M2+E3        the two lowest orders; MR mixes them.
    M1,E2           alternatives: the first explicit E or M (EDISTR04 took
                    M1 here, E2 for [D,E2] and E2 for E2,M1).
    D, Q, O         dipole, quadrupole, octupole of unknown parity: E1, M2,
                    E3 when the levels' parities change, else M1, E2, M3
                    (Dillman: "assuming no parity change"); D+Q is M1+E2 (or
                    E1+M2) mixed by MR. EDISTR04 did not read D and Q: it went
                    by the levels, or its default (a D at Z > 50 became E2).
    E0+M1+E2        an E0 component besides the gamma ray: the multipoles of
                    the gamma ray (M1+E2) give the table's values; ENSDF's own
                    values, which carry the evaluator's E0 part if any, are
                    used as given.
    E0              pure E0, above.
    IF E1, NOT E1   historical forms: IF is dropped; NOT ... is unknown.
  A single multipole with MR (M1 with MR given) is mixed with the next order
  of the other kind (E2).

  Energies in keV.
*/

/* ---------------------------------------------------------------------------
   The table
   --------------------------------------------------------------------------- */

export const GROUPS = ['K', 'L1', 'L2', 'L3', 'M', 'N+'];
const MULS = ['E1', 'E2', 'E3', 'E4', 'E5', 'M1', 'M2', 'M3', 'M4', 'M5'];
const MUL_INDEX = Object.fromEntries(MULS.map((m, i) => [m, i]));
const GROUP_INDEX = Object.fromEntries(GROUPS.map((g, i) => [g, i]));

function knotVector(k) {
  const a = k[1] - k[0], b = k[k.length - 1] - k[k.length - 2];
  return Float64Array.from([k[0] - 3 * a, k[0] - 2 * a, k[0] - a, ...k, k[k.length - 1] + b, k[k.length - 1] + 2 * b, k[k.length - 1] + 3 * b]);
}

/** The four non-zero cubic B-splines at x (clamped into the knot domain) into v; returns the first one's index. */
function basis(t, x, v) {
  const n = t.length - 4;
  if (!(x > t[3])) x = t[3]; else if (x > t[n]) x = t[n];
  let k = 3, hi = n - 1;
  if (x >= t[hi]) k = hi;
  else while (hi - k > 1) { const m = (k + hi) >> 1; if (t[m] <= x) k = m; else hi = m; }
  const l1 = x - t[k], l2 = x - t[k - 1], l3 = x - t[k - 2];
  const r1 = t[k + 1] - x, r2 = t[k + 2] - x, r3 = t[k + 3] - x;
  // Cox-de Boor, degrees 1 to 3 unrolled
  let a = 1 / (r1 + l1);
  const b0 = r1 * a, b1 = l1 * a;
  a = b0 / (r1 + l2); const c0 = r1 * a; let s = l2 * a;
  a = b1 / (r2 + l1); const c1 = s + r2 * a; const c2 = l1 * a;
  a = c0 / (r1 + l3); v[0] = r1 * a; s = l3 * a;
  a = c1 / (r2 + l2); v[1] = s + r2 * a; s = l2 * a;
  a = c2 / (r3 + l1); v[2] = s + r3 * a; v[3] = l1 * a;
  return k - 3;
}

const compiled = new WeakMap();

/**
 * The table of icc.json ready for evaluation (memoised per object).
 * @param {object} json  the parsed icc.json
 */
export function compileTable(json) {
  let c = compiled.get(json);
  if (c) return c;
  const tx = knotVector(json.knots.Z.map(Math.log));
  const ty = { w: knotVector(json.knots.w), u: knotVector(json.knots.u) };
  const nx = tx.length - 4;
  const surf = {};
  for (const [mul, groups] of Object.entries(json.surfaces)) {
    surf[mul] = {};
    for (const g of GROUPS) {
      const kind = json.shells[g], ny = ty[kind].length - 4;
      const s = groups[g];
      const a = new Float64Array(nx * ny);
      for (let i = 0; i < nx; i++) {
        const row = s.c[i] || [], j0 = s.j0[i] || 0;
        // Rows were trimmed to what 1 <= Z <= 110, B/1.3 <= E <= 10 MeV reach; beyond, the edge value.
        for (let j = 0; j < ny; j++) a[i * ny + j] = row.length ? row[Math.min(row.length - 1, Math.max(0, j - j0))] : -30;
      }
      surf[mul][g] = a;
    }
  }
  // E5 and M5: the linear extrapolation in multipole order of the two below, and a constant
  // (B-splines add up to one, so adding it to every coefficient adds it to the function).
  for (const [mul, d] of Object.entries(json.derived || {})) {
    surf[mul] = {};
    for (const g of GROUPS) {
      const parts = d.from.map(([k, m]) => [k, surf[m][g]]);
      const a = new Float64Array(parts[0][1].length).fill(d.offset[g] || 0);
      for (const [k, b] of parts) for (let i = 0; i < a.length; i++) a[i] += k * b[i];
      surf[mul][g] = a;
    }
  }
  const bind = {};
  for (const k of ['K', 'L1', 'L2', 'L3', 'M1', 'N1']) bind[k] = json.binding[k];
  c = {
    tx, ty, nx, ny: { w: ty.w.length - 4, u: ty.u.length - 4 }, kind: json.shells, surf, bind,
    zmax: json.binding.K.length, anchor: json.lowZ.anchor, occ: json.lowZ.occupancy, at: new Map(), edge: new Map(),
  };
  compiled.set(json, c);
  return c;
}

/* The binding energy y is measured from (and the low-Z rule's edges): the table's own. */
const EDGE = { K: 'K', L1: 'L1', L2: 'L2', L3: 'L3', M: 'M1', 'N+': 'N1' };
function refB(tab, g, Z, binding) {
  const arr = tab.bind[EDGE[g]];
  if (Z <= tab.zmax && arr[Z - 1]) return arr[Z - 1];
  const own = binding?.[EDGE[g]];
  if (own > 0) return own;
  if (Z > tab.zmax && arr[tab.zmax - 1]) return arr[tab.zmax - 1] * Math.exp(0.035 * (Z - tab.zmax)); // ~3.5 % per Z at the top
  return NaN;
}

/* The table at one Z: the x basis once (cached per Z of the table's range). */
function atZ(tab, Z, binding) {
  let ev = Z <= tab.zmax ? tab.at.get(Z) : null;
  if (ev) return ev;
  const vx = [0, 0, 0, 0], v = [0, 0, 0, 0];
  const i0 = basis(tab.tx, Math.log(Math.max(1, Z)), vx);
  const ref = {};
  for (const g of GROUPS) ref[g] = refB(tab, g, Z, binding);
  /* log10 alpha of a pure multipolarity and group at energy E (no edge test) */
  const log10a = (mul, g, E) => {
    const kind = tab.kind[g];
    let y;
    if (kind === 'w') { if (!(ref[g] > 0)) return -Infinity; y = Math.log10(E / ref[g]); } else y = Math.log10(E);
    const j0 = basis(tab.ty[kind], y, v);
    const a = tab.surf[mul][g], ny = tab.ny[kind];
    let s = 0;
    for (let r = 0; r < 4; r++) {
      const row = (i0 + r) * ny + j0;
      s += vx[r] * (v[0] * a[row] + v[1] * a[row + 1] + v[2] * a[row + 2] + v[3] * a[row + 3]);
    }
    return s;
  };
  ev = { log10a, ref };
  if (Z <= tab.zmax) tab.at.set(Z, ev);
  return ev;
}

/*
  Where EDISTR04 printed nothing the table only extrapolates, and goes astray
  far out; there this module continues it by physics instead.

  Above the last energy at which L1, M or N+ is 0.001 or more (nothing
  smaller was printed) it keeps its ratio there to the next inner shell, L1
  to K, M to L, N+ to M, as these ratios nearly do at high energy (BrIcc's
  L/K for E1 at Z = 60: 0.137 at 254 keV, 0.129 at 0.4-0.9 MeV, 0.124 at
  1.4-2.6 MeV; M/L 0.21 throughout). L2 and L3, of p electrons, keep
  falling against K there (as E2's L3/K does from 0.25 to 0.15 between 0.5
  and 2.6 MeV at Z = 80): for them, and for K, the table's own trend stands.

  Below the table's anchor (Z = 30, 37 for N+: EDISTR04 had K and L there
  from its older bank for some elements only, no M, no N+) the coefficients
  are carried down from the anchor Za at the same energy, as the physics of
  conversion goes (Born approximation: the bound electrons' density near the
  nucleus, s states as Z^3, p states as Z^5), times the ratio of the group's
  s and p electrons (EADL's occupancies, in the table):
    K       as the power of Z the table has between Za and Za + 6 at that
            energy (Z^3 bare, more with the outgoing electron's Coulomb
            attraction; on EDISTR04's own K values below Z = 30 it is off
            by a median 1 %, 10th to 90th percentile -11 % to +8 %);
    others  their ratio to the next inner group at Za (L to K, M to L1,
            N+ to M), the p subshells L2 and L3 another (Z / Za)^2;
    near the edge (E under 1.5 times the edge at Za + 6) at the same E / B,
            as a hydrogen-like atom's alpha ~ Z^3 k^-(L+5/2) (EL) or
            Z^3 k^-(L+3/2) (ML) goes with k ~ Z^2 E / B: Z^-(2L+2), Z^-2L.
*/
const INNER = { L1: 'K', L2: 'K', L3: 'K', M: 'L1', 'N+': 'M' };
const P_STATE = { L2: true, L3: true };

const PRINTED = -3; // log10 of the smallest value EDISTR04 printed
/* The groups the high-energy ratio holds for, and to what: L1 (s
   electrons) to K; M and N+, which mix s and p electrons, to the L shell and
   to M; the p subshells L2 and L3 keep falling against K there, and keep
   the table. */
const HIGH_E = { L1: ['K'], M: ['L1', 'L2', 'L3'], 'N+': ['M'] };

/* The energy above which group g of multipolarity mul has no printed value at
   Z (going up from 1.5 times the K edge, the first where the table falls
   under 0.001), and the group's ratio there to the groups HIGH_E ties it to:
   {Es, ratio}, or null if the table starts under 0.001. Memoised. */
function highE(tab, mul, g, Z, binding) {
  const key = (MUL_INDEX[mul] * 8 + GROUP_INDEX[g]) * 200 + Z;
  let h = tab.edge.get(key);
  if (h !== undefined) return h;
  const ev = atZ(tab, Z, binding);
  const lo = Math.max(1.5 * refB(tab, 'K', Z, binding), 1.05 * refB(tab, g, Z, binding) || 0);
  h = null;
  if (ev.log10a(mul, g, lo) >= PRINTED) {
    for (let u = Math.log10(lo); u <= 4; u += 0.01) {
      if (ev.log10a(mul, g, 10 ** (u + 0.01)) >= PRINTED) continue;
      const Es = 10 ** u;
      h = { Es, ratio: 10 ** ev.log10a(mul, g, Es) / HIGH_E[g].reduce((sum, k) => sum + alphaOf(tab, mul, k, Z, Es, binding), 0) };
      break;
    }
  }
  tab.edge.set(key, h);
  return h;
}

/** alpha of a pure multipolarity and group at (Z, E), the edge already passed. */
function alphaOf(tab, mul, g, Z, E, binding) {
  const Za = tab.anchor[g];
  if (Z >= Za) {
    const ev = atZ(tab, Z, binding);
    const inner = HIGH_E[g];
    if (inner) {
      const h = highE(tab, mul, g, Z, binding);
      if (h && E > h.Es) {
        let ref = 0;
        for (const k of inner) ref += alphaOf(tab, mul, k, Z, E, binding);
        return ref * h.ratio;
      }
    }
    return 10 ** ev.log10a(mul, g, E);
  }
  const o = tab.occ[g][Z - 1], oa = tab.occ[g][Za - 1];
  if (!(o > 0) || !(oa > 0)) return 0;
  const Zb = Za + 6, Bz = refB(tab, g, Z), Bb = refB(tab, g, Zb);
  const table = (z, e) => alphaOf(tab, mul, g, z, e);
  const occ = o / oa;
  const nearEdge = () => {
    const L = Number(mul.slice(1));
    return table(Za, E * refB(tab, g, Za) / Bz) * (Z / Za) ** (mul[0] === 'E' ? -(2 * L + 2) : -2 * L) * occ;
  };
  if (E < 1.5 * Bb && Bz > 0) return nearEdge();
  const inner = INNER[g];
  if (!inner) {
    const a = table(Za, E), b = table(Zb, E);
    const pow = Math.min(8, Math.max(1, Math.log(b / a) / Math.log(Zb / Za)));
    return a * (Z / Za) ** pow * occ;
  }
  // the ratio to the inner group needs that group open here and well open at the anchor
  if (!(E >= 1.5 * refB(tab, inner, Zb)) || !(E > 1.05 * refB(tab, inner, Z))) return Bz > 0 ? nearEdge() : 0;
  const ratio = table(Za, E) / alphaOf(tab, mul, inner, Za, E);
  return alphaOf(tab, mul, inner, Z, E) * ratio * occ * (P_STATE[g] ? (Z / Za) ** 2 : 1);
}

/* ---------------------------------------------------------------------------
   Subshells
   --------------------------------------------------------------------------- */

/** Is subshell s present in the atom and open to a transition of energy E? */
const open = (binding, s, E) => binding && binding[s] !== undefined && binding[s] < E;

/* The least bound subshell of a group the atom has: a last resort for a share no open subshell can take. */
function outermost(binding, names) {
  let best = null;
  for (const s of names) if (binding && binding[s] !== undefined && (best === null || binding[s] < binding[best])) best = s;
  return best;
}

/**
 * Theoretical coefficients of a pure multipolarity by shell group, the
 * table's values with each group zero where the transition cannot reach it.
 * @param {number} Z    atomic number of the atom that converts (the daughter's)
 * @param {number} E    transition energy, keV
 * @param {string} mul  'E1' ... 'E5', 'M1' ... 'M5'
 * @param {object} opt  {table: icc.json, binding: {K: keV, L1: keV, ...}}
 * @returns {{K: number, L1: number, L2: number, L3: number, M: number, 'N+': number}}
 */
export function theory(Z, E, mul, opt) {
  return groupValues(compileTable(opt.table), Z, E, mul, opt.binding || fallbackBinding(Z, opt.table, []));
}

/* The lowest energy each group opens at, for one atom's binding energies (memoised per object). */
const opensAt = new WeakMap();
function groupEdges(binding) {
  let e = opensAt.get(binding);
  if (e) return e;
  e = { K: Infinity, L1: Infinity, L2: Infinity, L3: Infinity, M: Infinity, 'N+': Infinity };
  for (const [s, B] of Object.entries(binding)) {
    const g = s === 'K' || s === 'L1' || s === 'L2' || s === 'L3' ? s : s[0] === 'M' ? 'M' : /^[NOPQ]/.test(s) ? 'N+' : null;
    if (g && B < e[g]) e[g] = B;
  }
  opensAt.set(binding, e);
  return e;
}

function groupValues(tab, Z, E, mul, binding) {
  const out = { K: 0, L1: 0, L2: 0, L3: 0, M: 0, 'N+': 0 };
  if (!(E > 0)) return out;
  // E6 and above are beyond the table: as EDISTR04, which had none, nothing.
  if (MUL_INDEX[mul] === undefined) return out;
  const edges = groupEdges(binding);
  for (const g of GROUPS) if (E > edges[g]) out[g] = alphaOf(tab, mul, g, Z, E, binding);
  return out;
}

/* Shares of s, p1/2 and p3/2 for the subshells n1, n2, n3 of shell n: the table's
   L1:L2:L3 at the same electron energy, E - B(ni) + B(Li). */
function likeL(mixL, E, binding, names) {
  const w = [];
  for (let i = 0; i < 3; i++) {
    const s = names[i], L = `L${i + 1}`;
    if (!open(binding, s, E)) { w.push(0); continue; }
    const El = binding[L] !== undefined ? E - binding[s] + binding[L] : E;
    w.push(mixL(L, El));
  }
  return w;
}

/** Spread a group's value over subshells by weights; closed or absent subshells take none. */
function spread(into, total, names, weights, binding, E, notes, label) {
  if (!(total > 0)) return;
  let sum = 0;
  for (let i = 0; i < names.length; i++) if (weights[i] > 0 && open(binding, names[i], E)) sum += weights[i];
  if (sum > 0) {
    for (let i = 0; i < names.length; i++) if (weights[i] > 0 && open(binding, names[i], E)) into[names[i]] = (into[names[i]] || 0) + total * weights[i] / sum;
    return;
  }
  // No open subshell with a share (the evaluator's binding energies differ from these, or only 3d is open)
  const openOnes = names.filter((s) => open(binding, s, E));
  const s = openOnes.length ? openOnes[openOnes.length - 1] : outermost(binding, names);
  if (s) { into[s] = (into[s] || 0) + total; notes.push(`${label} all in ${s}`); } else notes.push(`${label} dropped: the atom has no such subshell`);
}

/* ---------------------------------------------------------------------------
   Multipolarity
   --------------------------------------------------------------------------- */

const ORDER = (t) => Number(t.slice(1));

/* Pick one alternative of each comma list, innermost first: the first with an explicit E or M multipole. */
function chooseAlternatives(s) {
  const pick = (list) => {
    const alts = list.split(',').filter((x) => x.length);
    return alts.find((a) => /[EM]\d/.test(a)) ?? alts[0] ?? '';
  };
  let prev;
  do { prev = s; s = s.replace(/\(([^()]*)\)/g, (m, inner) => (inner.includes(',') ? `(${pick(inner)})` : m)); } while (s !== prev);
  return pick(s);
}

/**
 * ENSDF's MUL field read as multipoles.
 * @param {string} raw  e.g. "M1+E2", "[E2]", "(M1)", "E1(+M2)", "D+Q", "M1,E2", "E0+M1+E2"
 * @param {boolean} [parityChange]  whether the parity changes, if known (for D, Q, O)
 * @returns {{terms: string[], e0: boolean, notes: string[]}|null}  photon multipoles
 *   lowest order first; null when the field says nothing usable
 */
export function parseMultipolarity(raw, parityChange) {
  let s = String(raw ?? '').toUpperCase().replace(/\s+/g, '');
  if (!s) return null;
  const notes = [];
  if (/NOT/.test(s)) return null;
  s = s.replace(/IF/g, '').replace(/[[\]]/g, '');
  if (s.includes(',')) { s = chooseAlternatives(s); notes.push(`alternatives: ${s}`); }
  s = s.replace(/[()]/g, '');
  const terms = [];
  let e0 = false;
  for (const tok of s.split('+')) {
    let m = /^([EM])(\d)$/.exec(tok);
    if (m) { if (tok === 'E0') e0 = true; else if (m[2] !== '0') terms.push(tok); continue; }
    m = /^([DQO])$/.exec(tok);
    if (m) {
      const L = { D: 1, Q: 2, O: 3 }[m[1]];
      // E for odd L with a parity change or even L without; Dillman assumes none when unknown.
      const electric = parityChange === true ? L % 2 === 1 : L % 2 === 0;
      terms.push(`${electric ? 'E' : 'M'}${L}`);
      if (parityChange === undefined) notes.push(`${m[1]}: no parity change assumed`);
    }
  }
  const uniq = [...new Set(terms)].sort((a, b) => ORDER(a) - ORDER(b));
  if (!uniq.length && !e0) return null;
  return { terms: uniq, e0, notes };
}

/* The first spin of a J field and the parity written after it: "3/2+" -> 3/2 +,
   "(3/2,5/2)-" -> 3/2 -, "2+,3-,4+" -> 2 + (EDISTR04 reads the first assignment). */
function spinParity(text) {
  const t = String(text ?? '');
  const m = /(\d+)(?:\/(\d))?/.exec(t);
  const after = /[+-]/.exec(m ? t.slice(m.index + m[0].length) : t);
  return { J: m ? (m[2] ? Number(m[1]) / Number(m[2]) : Number(m[1])) : NaN, p: after ? after[0] : '' };
}

/**
 * EDISTR's multipolarity from the spins and parities of the levels (Dillman
 * Table 5 and p. 20, as EDISTR04 applied it to ICRP 107's inputs): from the
 * first listed spins the lowest order allowed (at least 1, so 0 -> 0 gives
 * M1), no parity change assumed when either parity is unknown; without both
 * spins, E1 if the parity is known to change, else nothing (EDISTR04 then
 * takes its default, M1 or E2 by Z, also where the parity stays: Dillman's
 * text says M1 there, the printouts say otherwise).
 * @returns {string|null}  'E2', 'M1', ...
 */
export function multipolarityFromLevels(Ji, Jf) {
  const a = spinParity(Ji), b = spinParity(Jf);
  const flip = a.p && b.p ? a.p !== b.p : false;
  if (!Number.isFinite(a.J) || !Number.isFinite(b.J)) return flip ? 'E1' : null;
  const L = Math.max(1, Math.abs(a.J - b.J));
  return `${flip === (L % 2 === 1) ? 'E' : 'M'}${L}`;
}

/* ---------------------------------------------------------------------------
   One transition
   --------------------------------------------------------------------------- */

const PAIR_E = 1021.998; // keV, 2 m c^2: above it internal pair formation competes

const N = (v) => {
  if (typeof v === 'number') return v;
  const m = /^\s*[([]?\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:E[-+]?\d+)?)/i.exec(String(v ?? ''));
  return m ? Number(m[1]) : NaN;
};

/* ENSDF's shell fields (NC+ is N and beyond, MC+ M and beyond, LC+ L and
   beyond) and its rare subshell fields (L1C ...). */
const SHELL_FIELD = Object.fromEntries(['KC', 'LC', 'MC', 'NC', 'OC', 'PC', 'QC', 'NC+', 'MC+', 'LC+'].map((f) => [f, true]));
const SUB_FIELD = Object.fromEntries(['L1', 'L2', 'L3', 'M1', 'M2', 'M3', 'M4', 'M5', 'N1', 'N2', 'N3', 'N4', 'N5', 'N6', 'N7'].map((sh) => [`${sh}C`, sh]));

/**
 * Conversion coefficients of one gamma transition by subshell.
 *
 * @param {number} Z      atomic number of the atom the transition happens in (the daughter's)
 * @param {object} gamma  {E (keV), MUL, MR, CC, cont: {KC, LC, MC, 'NC+', NC, OC, PC, QC, IPC, L1C, ...}
 *                        (numbers or ENSDF's text), placed (boolean), Ji, Jf (optional spin-parity
 *                        texts of the initial and final levels: D, Q parity and an unknown
 *                        multipolarity)}
 * @param {object} opt    {table: icc.json, binding: {K, L1, ..., N1, ...: keV} of that atom
 *                        (atomic-relax.js element(table).binding), mode: 'ensdf' (default) | 'edistr04'}
 * @returns {{alpha: Object<string, number>, total: number, rule: string, mul: string,
 *            delta2: number, groups: Object<string, number>, e0: boolean, notes: string[]}}
 *   alpha: per subshell, only those > 0; total their sum; rule 'shells', 'total', 'theory',
 *   'E0' or 'none'; mul the multipoles used ('M1+E2'); groups the K, L, M, N+ totals.
 *   For rule 'E0' the values are M1's, proportions of an all-electron transition.
 */
export function conversion(Z, gamma, opt) {
  const notes = [];
  const mode = opt.mode || 'ensdf';
  const E = Number(gamma.E);
  const res = (alpha, rule, mul, delta2, e0 = false) => {
    const a = {};
    let total = 0;
    for (const [s, v] of Object.entries(alpha)) if (v > 0) { a[s] = v; total += v; }
    const groups = { K: 0, L: 0, M: 0, 'N+': 0 };
    for (const [s, v] of Object.entries(a)) groups[s === 'K' ? 'K' : s[0] === 'L' ? 'L' : s[0] === 'M' ? 'M' : 'N+'] += v;
    return { alpha: a, total, rule, mul, delta2, groups, e0, notes };
  };
  if (!(E > 0) || !opt.table) return res({}, 'none', '', 0);
  const binding = opt.binding || fallbackBinding(Z, opt.table, notes);
  const placed = gamma.placed !== false;
  if (mode === 'edistr04' && !placed) { notes.push('unplaced: EDISTR04 converted none'); return res({}, 'none', '', 0); }

  // ENSDF's own values. Above 1022 keV BrIcc's total, and so CC, includes internal
  // pair formation, which makes no electron of a shell: taken out when ENSDF gives
  // it (IPC), else CC is no conversion total to rely on.
  const cont = gamma.cont || {};
  let CC = Number.isFinite(N(gamma.CC)) ? N(gamma.CC) : N(cont.CC);
  const CCwritten = CC; // what its rounding is relative to
  const IPC = N(cont.IPC);
  let ccHasPairs = false;
  if (CC > 0 && E > PAIR_E && mode !== 'edistr04') {
    if (IPC >= 0) { CC = Math.max(0, CC - IPC); notes.push('CC less IPC (pair formation)'); } else ccHasPairs = true;
  }
  const given = {}, sub = {};
  for (const f in cont) {
    if (SHELL_FIELD[f]) { const v = N(cont[f]); if (v >= 0) given[f] = v; } else if (SUB_FIELD[f]) { const v = N(cont[f]); if (v >= 0) sub[SUB_FIELD[f]] = v; }
  }
  const hasShells = mode !== 'edistr04' && (Object.keys(given).length > 0 || Object.keys(sub).length > 0);

  // Multipoles
  const flip = parityChangeOf(gamma.Ji, gamma.Jf);
  let parsed = parseMultipolarity(gamma.MUL, flip);
  if (parsed) notes.push(...parsed.notes);
  if (!parsed || (!parsed.terms.length && !parsed.e0)) {
    const fromLevels = multipolarityFromLevels(gamma.Ji, gamma.Jf);
    if (fromLevels) { parsed = { terms: [fromLevels], e0: false }; notes.push(`multipolarity from the levels: ${fromLevels}`); }
    else if (placed || hasShells || CC > 0) {
      // EDISTR's default; for an unplaced gamma only to split ENSDF's own values
      const d = Z <= 50 ? 'M1' : 'E2';
      parsed = { terms: [d], e0: false };
      notes.push(`multipolarity unknown: ${d} (EDISTR, Z ${Z <= 50 ? '<=' : '>'} 50)`);
    } else { notes.push('unplaced, multipolarity unknown: no conversion'); return res({}, 'none', '', 0); }
  }
  let terms = parsed ? parsed.terms : [];
  const e0 = parsed ? parsed.e0 : false;
  const MR = N(gamma.MR);
  let delta2 = 0;
  if (terms.length === 1 && Number.isFinite(MR) && MR !== 0) {
    const t = terms[0], L = ORDER(t);
    terms = [t, `${t[0] === 'E' ? 'M' : 'E'}${L + 1}`];
    notes.push(`MR given with ${t} alone: mixed with ${terms[1]}`);
  }
  if (terms.length > 2) { notes.push(`${terms.slice(2).join('+')} left out`); terms = terms.slice(0, 2); }
  if (terms.length === 2) {
    if (Number.isFinite(MR)) delta2 = MR * MR;
    else { notes.push(`delta unknown: ${terms[0]} alone`); terms = [terms[0]]; }
  }

  // Beyond the table (E6, M6): EDISTR04 had none; with ENSDF's values, the order-5 proportions split them.
  if (terms.some((t) => ORDER(t) > 5)) {
    if (mode === 'edistr04' || !(hasShells || CC > 0)) { notes.push(`${terms.join('+')}: no coefficients beyond order 5`); return res({}, 'none', terms.join('+'), 0); }
    terms = terms.map((t) => (ORDER(t) > 5 ? `${t[0]}5` : t)).filter((t, i, a) => a.indexOf(t) === i);
    notes.push(`order above 5: ${terms.join('+')} proportions`);
  }

  // Theory at this transition
  const tab = compileTable(opt.table);
  const pureE0 = e0 && !terms.length;
  const mixTerms = pureE0 ? ['M1'] : terms.length ? terms : ['M1'];
  const w2 = mixTerms.length === 2 ? delta2 : 0;
  const pure = mixTerms.map((m) => groupValues(tab, Z, E, m, binding));
  const th = {};
  for (const g of GROUPS) th[g] = mixTerms.length === 2 ? (pure[0][g] + w2 * pure[1][g]) / (1 + w2) : pure[0][g];
  // the L coefficients of the mixture at another energy, for the M and N+ split
  const mixL = (L, El) => {
    let v = 0;
    mixTerms.forEach((m, k) => { const f = k ? w2 / (1 + w2) : mixTerms.length === 2 ? 1 / (1 + w2) : 1; if (f) v += f * alphaOf(tab, m, L, Z, El, binding); });
    return v;
  };
  const mulText = pureE0 ? 'E0' : mixTerms.join('+') + (e0 ? '+E0' : '');

  // Group values to use
  let groups = null, rule;
  if (pureE0) {
    // M1's K, L, M, N+ (Dillman eq. 31), from the s1/2 and p1/2 subshells only:
    // EDISTR04's "K/L1/M/N+" ratios are M1's K : L1 + L2 : M : N+.
    groups = { K: th.K, L1: th.L1, L2: th.L2, L3: 0, M: th.M, 'N+': th['N+'] };
    rule = 'E0';
  } else if (mode === 'edistr04') {
    groups = { ...th };
    const S = GROUPS.reduce((s, g) => s + th[g], 0);
    if (CC > 0 && S > 0 && Math.abs(S / CC - 1) > 0.1) { for (const g of GROUPS) groups[g] *= CC / S; notes.push('theory scaled to CC (more than 10 % apart)'); }
    rule = 'theory';
  } else if (hasShells) {
    rule = 'shells';
  } else if (CC > 0) {
    const S = GROUPS.reduce((s, g) => s + th[g], 0);
    // a CC that may hold pairs is only an upper bound on conversion
    const total = ccHasPairs && S > 0 ? Math.min(CC, S) : CC;
    if (ccHasPairs) notes.push(`above ${PAIR_E} keV without IPC: CC may hold pair formation, conversion ${total === CC ? 'CC' : 'the table\'s total'}`);
    if (S > 0) { groups = {}; for (const g of GROUPS) groups[g] = th[g] * total / S; } else {
      // The table has nothing at this energy (below every edge it knows): all in the least bound open shell.
      groups = { K: 0, L1: 0, L2: 0, L3: 0, M: 0, 'N+': CC };
      notes.push('CC with no theoretical shell open: all in N+');
    }
    rule = 'total';
  } else {
    groups = { ...th };
    rule = 'theory';
  }

  const alpha = {};
  const Lw = [th.L1, th.L2, th.L3];
  const mShare = () => likeL(mixL, E, binding, ['M1', 'M2', 'M3']);
  const nShare = (n) => likeL(mixL, E, binding, [`${n}1`, `${n}2`, `${n}3`]);
  const putM = (v) => {
    if (!(v > 0)) return;
    if (pureE0) return spread(alpha, v, ['M1', 'M2'], mShare().slice(0, 2), binding, E, notes, 'M');
    const w = mShare();
    if (w.some((x) => x > 0)) spread(alpha, v, ['M1', 'M2', 'M3'], w, binding, E, notes, 'M');
    else spread(alpha, v, ['M4', 'M5'], [4, 6], binding, E, notes, 'M'); // only 3d open
  };
  const putShell = (n, v) => {
    if (!(v > 0)) return;
    if (pureE0) return spread(alpha, v, [`${n}1`, `${n}2`], nShare(n).slice(0, 2), binding, E, notes, n);
    const names = [`${n}1`, `${n}2`, `${n}3`];
    const w = nShare(n);
    if (w.some((x) => x > 0)) spread(alpha, v, names, w, binding, E, notes, n);
    else spread(alpha, v, names, [1, 1, 1], binding, E, notes, n);
  };

  if (rule !== 'shells') {
    if (groups.K > 0) alpha.K = groups.K;
    spread(alpha, groups.L1, ['L1'], [1], binding, E, notes, 'L1');
    spread(alpha, groups.L2, ['L2'], [1], binding, E, notes, 'L2');
    spread(alpha, groups.L3, ['L3'], [1], binding, E, notes, 'L3');
    putM(groups.M);
    putShell('N', groups['N+']);
    return res(alpha, rule, mulText, delta2, pureE0);
  }

  // ENSDF's shell values, split; a CC above their sum goes to the shells not given.
  const done = new Set();
  const sumGiven = Object.values(given).reduce((s, v) => s + v, 0) + Object.values(sub).reduce((s, v) => s + v, 0);
  for (const [s, v] of Object.entries(sub)) { alpha[s] = v; done.add(s[0] === 'L' ? 'L' : s[0]); }
  if ('KC' in given) {
    if (given.KC > 0) { alpha.K = given.KC; if (!open(binding, 'K', E)) notes.push('KC given below the K edge of these binding energies: kept'); }
    done.add('K');
  }
  if ('LC' in given && !done.has('L')) { spread(alpha, given.LC, ['L1', 'L2', 'L3'], Lw, binding, E, notes, 'L'); done.add('L'); }
  if ('MC' in given && !done.has('M')) { putM(given.MC); done.add('M'); }
  let nGiven = false;
  for (const n of ['N', 'O', 'P', 'Q']) if (`${n}C` in given) { putShell(n, given[`${n}C`]); nGiven = true; }
  if (!nGiven && 'NC+' in given) { putShell('N', given['NC+']); nGiven = true; }
  if ('MC+' in given && !done.has('M')) {
    // M and beyond together: split between M and N+ as the table does
    const f = th.M + th['N+'] > 0 ? th.M / (th.M + th['N+']) : 1;
    putM(given['MC+'] * f); if (!nGiven) putShell('N', given['MC+'] * (1 - f));
    done.add('M'); nGiven = true;
  }
  if ('LC+' in given && !done.has('L')) {
    const t = th.L1 + th.L2 + th.L3 + th.M + th['N+'];
    if (t > 0) {
      spread(alpha, given['LC+'] * (th.L1 + th.L2 + th.L3) / t, ['L1', 'L2', 'L3'], Lw, binding, E, notes, 'L');
      if (!done.has('M')) putM(given['LC+'] * th.M / t);
      if (!nGiven) putShell('N', given['LC+'] * th['N+'] / t);
    }
    done.add('L'); done.add('M'); nGiven = true;
  }
  if (nGiven) done.add('N');
  // Shells ENSDF does not give: what CC leaves, else the table scaled like the shells given.
  const missing = [];
  if (!done.has('K') && th.K > 0) missing.push(['K', th.K]);
  if (!done.has('L') && th.L1 + th.L2 + th.L3 > 0) missing.push(['L', th.L1 + th.L2 + th.L3]);
  if (!done.has('M') && th.M > 0) missing.push(['M', th.M]);
  if (!done.has('N') && th['N+'] > 0) missing.push(['N', th['N+']]);
  if (missing.length) {
    const tMiss = missing.reduce((s, [, v]) => s + v, 0);
    let scale;
    // ENSDF's values carry three figures: a remainder within their rounding (of CC as written,
    // before IPC came off it) is no information
    if (!ccHasPairs && CC - sumGiven > 0.005 * CCwritten) { scale = (CC - sumGiven) / tMiss; notes.push(`CC - shells given -> ${missing.map(([g]) => g).join(', ')}`); }
    else {
      const tGiven = GROUPS.reduce((s, g) => s + th[g], 0) - tMiss;
      scale = tGiven > 0 && sumGiven > 0 ? sumGiven / tGiven : 1;
      notes.push(`${missing.map(([g]) => g).join(', ')} from the table, scaled like the shells given`);
    }
    for (const [g, v] of missing) {
      const x = v * scale;
      if (g === 'K') alpha.K = (alpha.K || 0) + x;
      else if (g === 'L') spread(alpha, x, ['L1', 'L2', 'L3'], Lw, binding, E, notes, 'L');
      else if (g === 'M') putM(x);
      else putShell('N', x);
    }
  }
  return res(alpha, rule, mulText, delta2, false);
}

function parityChangeOf(Ji, Jf) {
  if (Ji == null || Jf == null) return undefined;
  const a = spinParity(Ji), b = spinParity(Jf);
  return a.p && b.p ? a.p !== b.p : undefined;
}

/* Without the atom's binding energies: the table's K and L edges, M and N open where the atom has them. */
function fallbackBinding(Z, table, notes) {
  notes.push('no binding energies given: the table\'s K and L edges, M and N subshells taken as open');
  const tab = compileTable(table);
  const b = {};
  for (const s of ['K', 'L1', 'L2', 'L3']) { const v = refB(tab, s, Z); if (v > 0) b[s] = v; }
  if (Z >= 11) Object.assign(b, { M1: 0, M2: 0, M3: 0 });
  if (Z >= 21) Object.assign(b, { M4: 0, M5: 0 });
  if (Z >= 19) Object.assign(b, { N1: 0, N2: 0, N3: 0 });
  return b;
}
