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

  The calculations behind the published coefficients follow a chain way by
  way (sidePaths with minor: waysByEnergy below). A way from one member to the
  next is followed if the energy that comes by it -- the next member's own and
  that of everything after it that is made through it -- is at least a
  thousandth of what the chain emits in 50 years, or in its first year
  (early), with the alpha energy weighted by 20 or without. What the
  coefficients show:
  - a lesser way to a member is not followed: 209Pb after 213Bi is made by
    213Po (97.91 %) and by 209Tl (2.09 %); what 209Tl leaves is 0.0004 of the
    chain's energy, and the annex of Publication 158 has 213Bi without it;
  - a member that no followed way reaches is no member: 195mHg after 195mPb
    is made by 0.34 % of 195Tl, and it and all it leaves emit 0.0006 of the
    chain's energy. It lives 42 hours and gathers in the kidneys: followed,
    it gave 0.7 % of the kidney dose, 0.3 % of the gonads' and 0.2 % of the
    liver's, which is what the page was above the annex there;
  - a chain ends where what is left is too little, though members before it
    emit less: after 235U the OIR Data Viewer has 231Th, 231Pa, 227Ac, 227Th
    and 223Ra (231Pa, 227Th and 223Ra with 0.0006, 0.0003 and 0.0003 of the
    energy) but not 219Rn, 215Po, 211Pb and 211Bi (0.0009 together). With
    all of them e was 1.0008 of the viewer's, with none after 231Th 0.9987,
    so 1.0000 and every organ dose to its four figures;
  - the first year counts too: 216At after 228Pa, on a side branch (2 % of
    228Pa makes 224Ac, 9 % of that 220Fr), brings 0.0009 of the chain's
    energy over 50 years but 0.003 over the first year, when little of the
    228Th made beside it has decayed, and the OIR Data Viewer has it. Any
    first stretch from 14 days to 6 years gives the same chains of all
    1,252; a shorter one brings in members the viewer has not (226Ac after
    230Pa, 220Ra and 216Rn after 224Ac).
  With sidePaths alone (minor not 'drop'), only the lesser ways are cut
  (lesserWays), as the page did before it left members out.
*/

export const LN2 = Math.LN2;

/**
 * @param {object} index  nuclide name -> {T (days), d: [[daughter, branch]...], E: [Ea, Ee, Ep]}
 * @param {string} parent
 * @param {object} [opt]  {last: number|null, cutoff: 1e-3, horizonDays: 36525, keep: (name) => bool,
 *                        sidePaths: 0 | share (1e-3) below which a lesser way to a member is cut,
 *                        minor: 'drop' | null: leave out the minor members (not with `last`),
 *                        early: days (0): the ways are judged over this first stretch too}
 * @returns {{members: Array<{name, T, lambda, E}>, branches: Array<{from, to, b}>, dropped: string[], cut: Array<[from, to]>, minor: string[]}}
 *   dropped: left out by the cut-off (or `last`); minor: left out as minor members
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
  if (opt.minor === 'drop' && !opt.last && opt.sidePaths > 0) {
    // way by way: the lesser ways and the members that no followed way reaches
    const { lost, keep } = waysByEnergy(index, names, branches, opt.sidePaths, opt.early);
    branches = branches.filter((x) => !lost.includes(x));
    for (const x of lost) if (keep.has(names[x.from]) && keep.has(names[x.to])) cut.push([names[x.from], names[x.to]]);
    if (keep.size < names.length) {
      const left = names.filter((n) => keep.has(n)), to = new Map(left.map((n, i) => [n, i]));
      return {
        members: members.filter((m) => keep.has(m.name)),
        branches: branches.filter((x) => keep.has(names[x.from]) && keep.has(names[x.to])).map((x) => ({ from: to.get(names[x.from]), to: to.get(names[x.to]), b: x.b })),
        dropped, cut, minor: names.filter((n) => !keep.has(n)),
      };
    }
    return { members, branches, dropped, cut, minor: [] };
  }
  if (opt.sidePaths > 0) {
    const lesser = lesserWays(index, names, branches, opt.sidePaths);
    for (const x of lesser) cut.push([names[x.from], names[x.to]]);
    if (lesser.length) branches = branches.filter((x) => !lesser.includes(x));
  }
  return { members, branches, dropped, cut, minor: [] };
}

/**
 * A chain followed way by way, from the parent down: a way is followed if the
 * energy that comes by it -- the member's own and that of everything after it
 * that is made through it -- is at least `share` of what the whole chain
 * emits over `horizon` days, or over its first `early` days, with the alpha
 * energy weighted by 20 or without. A member's ways are judged with
 * everything below still in place. Where several ways lead to a member and
 * together bring that much, the one that brings most is followed whatever it
 * brings. A member that no followed way reaches is no member of the chain.
 * @returns {{lost: Array<branch>, keep: Set<string>}}
 */
function waysByEnergy(index, names, branches, share, early = 0, horizon = 18262.5) {
  const times = early > 0 && early < horizon ? [early, horizon] : [horizon];
  // [plain, weighted] energy over each stretch, without the ways in `skipped`
  const energy = (skipped) => times.map((h) => {
    const u = batemanTransformations(index, names, h, skipped.size ? (j, i) => skipped.has(`${j},${i}`) : null);
    let plain = 0, weighted = 0;
    names.forEach((n, i) => { const [a, e, p] = index[n].E; plain += u[i] * (a + e + p); weighted += u[i] * (20 * a + e + p); });
    return [plain, weighted];
  });
  const key = (x) => `${x.from},${x.to}`;
  const skipped = new Set(), lost = [], keep = new Set([names[0]]);
  const whole = energy(skipped);
  let now = whole;
  // the largest share of the whole chain's energy that these ways bring, over either stretch and by either measure
  const brings = (extra) => {
    const e = energy(new Set([...skipped, ...extra]));
    let most = 0;
    e.forEach(([p, w], k) => { most = Math.max(most, whole[k][0] > 0 ? (now[k][0] - p) / whole[k][0] : 0, whole[k][1] > 0 ? (now[k][1] - w) / whole[k][1] : 0); });
    return most;
  };
  for (let i = 1; i < names.length; i++) {
    const ways = branches.filter((x) => x.to === i);
    const open = ways.filter((x) => keep.has(names[x.from]));
    for (const x of ways) if (!open.includes(x)) { skipped.add(key(x)); lost.push(x); }
    if (!open.length) continue;
    const all = brings(open.map(key));
    if (all < share) { for (const x of open) { skipped.add(key(x)); lost.push(x); } now = energy(skipped); continue; }
    keep.add(names[i]);
    if (open.length < 2) continue;
    const each = open.map((x) => brings([key(x)]));
    const most = each.indexOf(Math.max(...each));
    let any = false;
    open.forEach((x, k) => { if (k !== most && each[k] < share) { skipped.add(key(x)); lost.push(x); any = true; } });
    if (any) now = energy(skipped);
  }
  return { lost, keep };
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
