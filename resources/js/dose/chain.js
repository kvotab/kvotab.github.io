/*
  The decay chain of a radionuclide taken into the body: the parent and the
  radioactive progeny that the dose calculation follows.

  Members are numbered so that no member decays to an earlier one, which is
  what the solver needs (decay then only ever feeds forward) and what DCAL's
  ACTACAL does (ORNL/TM-2001/190, section 8.6). The numbering is the order in
  which a breadth-first walk from the parent meets the members, made
  topological where a member is reached along two paths of different length.
  DCAL's batch files cut some chains after a given member ("I-131 1" keeps
  only 131I); `last` does the same with this numbering.

  Without `last`, ACTACAL truncates a chain where the cumulative energy
  emitted over 100 years by 1 Bq of the parent stops increasing. This does the
  same with the number of transformations from the Bateman equations and the
  energy per transformation (alpha weighted by 20, as an equivalent-dose
  proxy): members whose share of the total is below `cutoff` are left out,
  with everything after them that is not reached another way. A member left
  out this way carries less than `cutoff` of the 100-year energy, so the dose
  it would have added is of that order or smaller.

  A member reached along two ways (sidePaths): the way that brings less than
  that share of the chain's 50-year energy, with the alpha energy weighted by
  20 and without, is not followed, as in the calculations behind the published
  coefficients, which follow a chain way by way. 209Pb after 213Bi is made by
  213Po (97.91 %) and by 209Tl (2.09 %): what 209Tl leaves is 0.0004 of the
  chain's energy, and the annex of Publication 158 has 213Bi without it.
*/

export const LN2 = Math.LN2;

/**
 * @param {object} index  nuclide name -> {T (days), d: [[daughter, branch]...], E: [Ea, Ee, Ep]}
 * @param {string} parent
 * @param {object} [opt]  {last: number|null, cutoff: 1e-3, horizonDays: 36525, keep: (name) => bool,
 *                        sidePaths: 0 | share (1e-3) below which a lesser way to a member is cut}
 * @returns {{members: Array<{name, T, lambda, E}>, branches: Array<{from, to, b}>, dropped: string[], cut: Array<[from, to]>}}
 */
export function buildChain(index, parent, opt = {}) {
  if (!index[parent]) throw new Error(`${parent} is not in the decay data`);
  const order = [];
  const seen = new Set([parent]);
  const queue = [parent];
  while (queue.length) {
    const n = queue.shift();
    order.push(n);
    for (const [d] of index[n].d || []) {
      if (!index[d] || seen.has(d)) continue; // a daughter without a record is stable
      seen.add(d);
      queue.push(d);
    }
  }
  // Kahn's algorithm with the breadth-first position as the tie-break.
  const pos = new Map(order.map((n, i) => [n, i]));
  const indeg = new Map(order.map((n) => [n, 0]));
  for (const n of order) for (const [d] of index[n].d || []) if (pos.has(d)) indeg.set(d, indeg.get(d) + 1);
  const ready = order.filter((n) => indeg.get(n) === 0);
  const topo = [];
  while (ready.length) {
    ready.sort((a, b) => pos.get(a) - pos.get(b));
    const n = ready.shift();
    topo.push(n);
    for (const [d] of index[n].d || []) {
      if (!pos.has(d)) continue;
      indeg.set(d, indeg.get(d) - 1);
      if (indeg.get(d) === 0) ready.push(d);
    }
  }
  if (topo.length !== order.length) throw new Error(`the decay chain of ${parent} has a cycle`);

  let names = topo;
  const dropped = [];
  if (opt.last) {
    dropped.push(...names.slice(opt.last));
    names = names.slice(0, opt.last);
  } else if (opt.cutoff !== 0) {
    const keep = significantMembers(index, names, opt.cutoff ?? 1e-3, opt.horizonDays ?? 36525, opt.measure);
    for (const n of names) if (!keep.has(n)) dropped.push(n);
    names = names.filter((n) => keep.has(n));
  }
  const at = new Map(names.map((n, i) => [n, i]));
  const members = names.map((n) => ({ name: n, T: index[n].T, lambda: LN2 / index[n].T, E: index[n].E }));
  let branches = [];
  names.forEach((n, i) => {
    for (const [d, b] of index[n].d || []) if (at.has(d) && b > 0) branches.push({ from: i, to: at.get(d), b });
  });
  const cut = [];
  if (opt.sidePaths > 0) {
    const lesser = lesserWays(index, names, branches, opt.sidePaths);
    for (const x of lesser) cut.push([names[x.from], names[x.to]]);
    if (lesser.length) branches = branches.filter((x) => !lesser.includes(x));
  }
  return { members, branches, dropped, cut };
}

/**
 * The ways into members that have more than one, each bringing less than
 * `share` of the chain's energy over `horizon` days by both measures (alpha
 * weighted by 20, and not): the energy the chain loses without that way. The
 * way that brings a member most is never one of them.
 */
function lesserWays(index, names, branches, share, horizon = 18262.5) {
  const into = new Map();
  for (const x of branches) { if (!into.has(x.to)) into.set(x.to, []); into.get(x.to).push(x); }
  const energy = (skip) => {
    const u = batemanTransformations(index, names, horizon, skip);
    let plain = 0, weighted = 0;
    names.forEach((n, i) => { const [a, e, p] = index[n].E; plain += u[i] * (a + e + p); weighted += u[i] * (20 * a + e + p); });
    return [plain, weighted];
  };
  let whole = null;
  const out = [];
  for (const ways of into.values()) {
    if (ways.length < 2) continue;
    whole ||= energy(null);
    const loss = ways.map((x) => { const [p, w] = energy((j, i) => j === x.from && i === x.to); return Math.max(whole[0] > 0 ? 1 - p / whole[0] : 0, whole[1] > 0 ? 1 - w / whole[1] : 0); });
    const most = loss.indexOf(Math.max(...loss));
    ways.forEach((x, k) => { if (k !== most && loss[k] < share) out.push(x); });
  }
  return out;
}

/**
 * Number of transformations of each member within `horizon` days after 1 Bq
 * of the first, by integrating the linear decay system exactly (it is lower
 * triangular): each member's activity is a sum of exponentials.
 */
export function batemanTransformations(index, names, horizon, skip = null) {
  const lam = names.map((n) => LN2 / index[n].T);
  const at = new Map(names.map((n, i) => [n, i]));
  // A_i(t) = sum_k c[i][k] exp(-lam_k t)
  const c = names.map(() => new Float64Array(names.length));
  c[0][0] = 1;
  for (let i = 0; i < names.length; i++) {
    // inflow to i from each earlier member j: b_ji * lam_i * A_j
    for (let j = 0; j < i; j++) {
      for (const [d, b] of index[names[j]].d || []) {
        if (at.get(d) !== i || (skip && skip(j, i))) continue;
        for (let k = 0; k < names.length; k++) {
          if (!c[j][k]) continue;
          const den = lam[i] - lam[k];
          // d/dt A_i = -lam_i A_i + b lam_i c_jk e^{-lam_k t}
          const coef = Math.abs(den) > 1e-12 * lam[i] ? b * lam[i] * c[j][k] / den : 0;
          c[i][k] += coef;
          c[i][i] -= coef;
        }
      }
    }
  }
  return names.map((_, i) => {
    let u = 0;
    for (let k = 0; k < names.length; k++) if (c[i][k]) u += c[i][k] * (-Math.expm1(-lam[k] * horizon)) / lam[k];
    return u;
  });
}

/**
 * The members of a chain (names in chain order, the parent first) that the
 * calculations behind the published coefficients carry: those that emit a
 * thousandth of the chain's energy over 50 years, counted with the alpha
 * energy weighted by 20 or without, and what leads to them. Read off the OIR
 * Data Viewer (Publications 134, 137, 141) from the tissues whose dose shows
 * that a member's model was there or was not: 239Pu after 243Cm is not
 * (0.0008 of the energy either way), nor 230Th after 234U, 234U after 238Pu,
 * 248Cm after 252Cf, or 235mU after 239Pu, which emits next to nothing;
 * 237Np after 237U is (0.0045 weighted, 0.0002 not), 234U after 234Np, 148Gd
 * after 152Dy, 245Cm after 249Cf (0.002), and so are 207Tl and 209Pb at the
 * end of an alpha chain (0.0008 and 0.0004 weighted, 0.014 and 0.007 not).
 */
export function carriedMembers(index, names, cutoff = 1e-3, horizon = 18262.5) {
  return significantMembers(index, names, cutoff, horizon, 'either');
}

function significantMembers(index, names, cutoff, horizon, measure) {
  const u = batemanTransformations(index, names, horizon);
  const plain = names.map((n, i) => { const [a, e, p] = index[n].E; return u[i] * (a + e + p); });
  const plainTotal = plain.reduce((s, x) => s + x, 0) || 1;
  const w = names.map((n, i) => {
    const [a, e, p] = index[n].E;
    return u[i] * (20 * a + e + p);
  });
  const total = w.reduce((s, x) => s + x, 0) || 1;
  // 'either': by the energy with the alpha weighting or without.
  if (measure === 'either') for (let i = 0; i < w.length; i++) w[i] = Math.max(w[i], plain[i] * total / plainTotal);
  // A member is kept when it, or anything below it, carries a share of the
  // energy: 228Ra emits next to nothing itself, but the 232Th chain's alpha
  // energy all comes through it.
  const at = new Set(names);
  const keep = new Set();
  if (measure !== 'either') {
    for (let i = names.length - 1; i >= 0; i--) {
      const n = names[i];
      if (i === 0 || w[i] / total >= cutoff || (index[n].d || []).some(([d]) => at.has(d) && keep.has(d))) keep.add(n);
    }
    return keep;
  }
  // 'either': what is below it counts only if it comes through it. 218At, on
  // a branch of 0.02 % of 218Po that joins 214Po again, is no member for that
  // (counted, astatine's thyroid, salivary glands and stomach wall were
  // tissues of radon's chain). The share of a kept member's making that
  // passes a member: the products of the branching fractions along the ways.
  const pos = new Map(names.map((n, i) => [n, i]));
  const ways = (from) => {
    const v = new Float64Array(names.length);
    v[from] = 1;
    for (let j = from; j < names.length; j++) if (v[j] > 0) for (const [d, b] of index[names[j]].d || []) if (pos.has(d) && pos.get(d) > j) v[pos.get(d)] += v[j] * b;
    return v;
  };
  const fromParent = ways(0);
  for (let i = names.length - 1; i >= 0; i--) {
    if (i === 0 || w[i] / total >= cutoff) { keep.add(names[i]); continue; }
    const below = ways(i);
    for (let x = i + 1; x < names.length; x++) {
      if (keep.has(names[x]) && below[x] > 0 && fromParent[i] * below[x] >= cutoff * fromParent[x]) { keep.add(names[i]); break; }
    }
  }
  return keep;
}
