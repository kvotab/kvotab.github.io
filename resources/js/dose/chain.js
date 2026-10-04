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
*/

export const LN2 = Math.LN2;

/**
 * @param {object} index  nuclide name -> {T (days), d: [[daughter, branch]...], E: [Ea, Ee, Ep]}
 * @param {string} parent
 * @param {object} [opt]  {last: number|null, cutoff: 1e-3, horizonDays: 36525, keep: (name) => bool}
 * @returns {{members: Array<{name, T, lambda, E}>, branches: Array<{from, to, b}>, dropped: string[]}}
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
    const keep = significantMembers(index, names, opt.cutoff ?? 1e-3, opt.horizonDays ?? 36525);
    for (const n of names) if (!keep.has(n)) dropped.push(n);
    names = names.filter((n) => keep.has(n));
  }
  const at = new Map(names.map((n, i) => [n, i]));
  const members = names.map((n) => ({ name: n, T: index[n].T, lambda: LN2 / index[n].T, E: index[n].E }));
  const branches = [];
  names.forEach((n, i) => {
    for (const [d, b] of index[n].d || []) if (at.has(d) && b > 0) branches.push({ from: i, to: at.get(d), b });
  });
  return { members, branches, dropped };
}

/**
 * Number of transformations of each member within `horizon` days after 1 Bq
 * of the first, by integrating the linear decay system exactly (it is lower
 * triangular): each member's activity is a sum of exponentials.
 */
export function batemanTransformations(index, names, horizon) {
  const lam = names.map((n) => LN2 / index[n].T);
  const at = new Map(names.map((n, i) => [n, i]));
  // A_i(t) = sum_k c[i][k] exp(-lam_k t)
  const c = names.map(() => new Float64Array(names.length));
  c[0][0] = 1;
  for (let i = 0; i < names.length; i++) {
    // inflow to i from each earlier member j: b_ji * lam_i * A_j
    for (let j = 0; j < i; j++) {
      for (const [d, b] of index[names[j]].d || []) {
        if (at.get(d) !== i) continue;
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

function significantMembers(index, names, cutoff, horizon) {
  const u = batemanTransformations(index, names, horizon);
  const w = names.map((n, i) => {
    const [a, e, p] = index[n].E;
    return u[i] * (20 * a + e + p);
  });
  const total = w.reduce((s, x) => s + x, 0) || 1;
  // A member is kept when it, or anything below it, carries a share of the
  // energy: 228Ra emits next to nothing itself, but the 232Th chain's alpha
  // energy all comes through it.
  const at = new Set(names);
  const keep = new Set();
  for (let i = names.length - 1; i >= 0; i--) {
    const n = names[i];
    if (i === 0 || w[i] / total >= cutoff || (index[n].d || []).some(([d]) => at.has(d) && keep.has(d))) keep.add(n);
  }
  return keep;
}
