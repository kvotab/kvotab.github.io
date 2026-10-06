/*
  The dose engines' decay data from a whole ENSDF release: one record per
  radionuclide (ground state or isomer), in the shape the ICRP 107 files
  give (dose-decay.mjs; decay/index.json and decay/<El>.json).

  Two readers of the same release meet here:
    - the Chart of Nuclides' (ensdf-parse.js summary): the states, their
      adopted half-lives and decay modes, and how each branch lands in the
      daughter's isomers;
    - the decay-radiation processor (ensdf-decay.js): the radiations of each
      decay data set, EDISTR04's way.

  Which states are chain members of their own: every ground state, and the
  isomers that live at least `minIsomer` seconds (ICRP 38 and 107 called a
  level an isomer from one minute on) or that decay otherwise than by IT.
  Shorter IT isomers stay inside the decay that makes them: their gamma rays
  are counted there, as EDISTR counted them. Isomers are named in ICRP 107's
  way, m, n, p ... by energy among the members of the same nuclide.

  A mode the release names but gives no decay data set for (Pt-202's
  beta-minus decay, U-235m's IT) is estimated, and the record says so: alpha
  and beta-minus to the ground state from the Q value; capture to the ground
  state, its X-rays and Auger electrons; IT from the adopted gamma rays of
  the level, carried down the cascade. Spontaneous fission is always the
  fission module's (ENSDF gives only its branch).
*/
import { parentStates, stateRadiations, decayRecord, SYMBOL, family, firstSpin } from './ensdf-decay.js';
import { positronFraction } from './ensdf-capture.js';

const SUFFIX = ['m', 'n', 'p', 'q', 'r', 's', 't'];
const FAM = { 'B-': 'B-', EC: 'EC', 'B+': 'EC', 'EC+B+': 'EC', A: 'A', IT: 'IT', SF: 'SF' };
const pct = (x) => (x * 100).toPrecision(3);

/* Which states of a nuclide (a summary entry: its states s, each with ts in
   seconds and branches br) are chain members, and their names. */
function memberRules(MIN_ISO) {
  const nonIT = (st) => (st.br || []).some(([m, p]) => m !== 'IT' && p > 0);
  const isMember = (e, k) => {
    const st = e?.s?.[k];
    if (!st || !(st.ts > 0) || !Number.isFinite(st.ts)) return false;
    return k === 0 || st.ts >= MIN_ISO || nonIT(st);
  };
  const nameOf = (e, k) => {
    const base = `${SYMBOL[e.z]}-${e.a}`;
    if (k === 0) return base;
    const at = e.s.map((_, i) => i).filter((i) => i > 0 && isMember(e, i)).indexOf(k);
    return at < 0 ? null : base + SUFFIX[at];
  };
  return { isMember, nameOf, nonIT };
}

/**
 * The chain members of a release by the summary alone, named as
 * releaseRecords names them: [{name, z, a, k, T (days), to: [[z, a]...]}],
 * `to` the nuclides its adopted branches lead to.
 * @param {object} summary  ensdf-parse.js's
 * @param {object} [opt]    {minIsomer: s (60)}
 */
export function releaseMembers(summary, opt = {}) {
  const { isMember, nameOf } = memberRules(opt.minIsomer ?? 60);
  const out = [];
  for (const e of summary.nuclides) {
    if (!(e.z >= 1) || !SYMBOL[e.z]) continue;
    (e.s || []).forEach((st, k) => {
      if (!isMember(e, k)) return;
      const to = (st.br || []).flatMap(([, p, list]) => (p > 0 ? (list || []).map(([z, a]) => [z, a]) : []));
      out.push({ name: nameOf(e, k), z: e.z, a: e.a, k, T: st.ts / 86400, to });
    });
  }
  return out;
}

/**
 * @param {object} release  {summary, datasets, adopted}: the summary of
 *                          ensdf-parse.js, and readDatasets(text, {adopted:
 *                          true}) of every file, split into decay and adopted
 * @param {object} mods     {beta (beta-spectrum.js), atom(Z), icc(Z, gamma, atom) -> ensdf-icc.js conversion() result,
 *                          capture(Z, Et, n, rec, atom),
 *                          fission(name, Z, A, br, notes) -> {lines: [[E, Y, kind]], betas: [branch]}}
 * @param {object} [opt]    {minIsomer: s (60), only: (z, a) => bool, the nuclides to make records of (all)}
 * @returns {{records: Map<string, object>, names: Map<string, string>}} records by name; names: "Z,A,k" -> name
 */
export function releaseRecords({ summary, datasets, adopted }, mods, opt = {}) {
  const MIN_ISO = opt.minIsomer ?? 60;
  const nuc = new Map(summary.nuclides.map((e) => [e.z * 1000 + e.a, e]));
  const adoptedOf = new Map((adopted || []).map((ds) => [ds.Z * 1000 + ds.A, ds]));
  const { isMember, nameOf, nonIT } = memberRules(MIN_ISO);
  const offsetOf = (raw) => /[A-Z]/i.test(String(raw || '').replace(/E[-+]?\d+$/i, ''));
  const letterOf = (raw) => (/([A-Z])/i.exec(String(raw || '').replace(/E[-+]?\d+$/i, '')) || [])[1]?.toUpperCase() || '';
  // The state of a nuclide at a level: by energy; for an offset level ("0.0+X")
  // by the offset's letter and the number with it, else by half-life.
  function stateIndex(e, E, Eraw, T, groundToo) {
    if (!e?.s) return -1;
    let k = -1, d = Infinity;
    // A level above zero is never the ground state, however close: Th-229's
    // 8 eV isomer would otherwise lend the ground state its IT decay.
    const ground = groundToo && !(E > 0);
    const tol = Math.max(1, 0.002 * E);
    if (!offsetOf(Eraw)) {
      e.s.forEach((st, i) => { if (i === 0 && !ground) return; if (st.ex) return; const x = Math.abs((st.en || 0) - E); if (x < d) { d = x; k = i; } });
      if (k >= 0 && d <= tol) return k;
    } else {
      const letter = letterOf(Eraw);
      e.s.forEach((st, i) => { if (String(st.ex || '').toUpperCase() !== letter) return; const x = Math.abs((st.en || 0) - E); if (x < d) { d = x; k = i; } });
      if (k >= 0 && d <= tol) return k;
    }
    if (T > 0 && Number.isFinite(T)) {
      k = -1; d = Infinity;
      e.s.forEach((st, i) => { if ((i === 0 && !groundToo) || !(st.ts > 0)) return; const x = Math.abs(Math.log10(st.ts / T)); if (x < d) { d = x; k = i; } });
      if (k >= 0 && d < 0.15) return k;
    }
    return -1;
  }

  // Decay data sets by parent state (ions stripped of electrons are left out).
  const byState = new Map();
  for (const ps of parentStates(datasets.filter((ds) => !/\[/.test(ds.parentNucid || '')))) {
    const e = nuc.get(ps.Z * 1000 + ps.A);
    const k = stateIndex(e, ps.E, ps.Eraw, ps.T, true);
    if (k < 0) continue;
    const key = `${ps.Z * 1000 + ps.A}:${k}`;
    if (!byState.has(key)) byState.set(key, []);
    byState.get(key).push(...ps.datasets);
  }

  // One data set per mode: one of this state alone, one with a
  // normalisation, then the fullest, then the newest. ENSDF's SF data sets are the gamma rays of single fission
  // fragments (248CM SF DECAY under 82GE ...), never the fission's whole
  // radiation, which the fission module gives from the adopted branch.
  function pick(list) {
    const byFam = new Map();
    for (const ds of list) {
      const f = family(ds.mode);
      if (!f || f === 'SF') continue;
      if (!byFam.has(f)) byFam.set(f, []);
      byFam.get(f).push(ds);
    }
    // A data set of this state alone before one shared with another
    // ("108IN EC DECAY (58.0 M)" before "(58.0 M+39.6 M)").
    const score = (ds) => [ds.parents.length <= 1 ? 1 : 0, Number.isFinite(ds.norm?.NR) || Number.isFinite(ds.norm?.BR) ? 1 : 0,
      ds.levels.reduce((s, lv) => s + lv.gammas.length + lv.feeds.length, 0) + ds.unplaced.gammas.length, Number(ds.date) || 0];
    return [...byFam.values()].map((l) => l.sort((p, q) => { const a = score(p), b = score(q); return (b[0] - a[0]) || (b[1] - a[1]) || (b[2] - a[2]) || (b[3] - a[3]); })[0]);
  }

  // A decay data set's level is the adopted state found by its energy only
  // if their half-lives agree within a factor of 10, or, with none on the
  // level, their first spins do: Pb-212's beta decay feeds a level at
  // 238.6 keV that is not the 25 min (9-) isomer of Bi-212 at "239".
  const sameState = (lv, st) => {
    if (lv.T > 0 && Number.isFinite(lv.T) && st.ts > 0 && Number.isFinite(st.ts)) return Math.abs(Math.log10(lv.T / st.ts)) < 1;
    const a = firstSpin(lv.J), b = firstSpin(st.j);
    return !(a && b && a.J !== b.J);
  };
  const stateOfLevel = (de, lv) => {
    const dk = stateIndex(de, lv.E, lv.Eraw, lv.T, false);
    return dk > 0 && sameState(lv, de.s[dk]) ? dk : -1;
  };

  // The processor's context for a state whose adopted branches are brs.
  const contCache = new Map();
  function ctxFor(st, brs, self) {
    return {
      self,
      member(Zd, Ad, lv) {
        const de = nuc.get(Zd * 1000 + Ad);
        const dk = stateOfLevel(de, lv);
        return dk > 0 && isMember(de, dk) ? nameOf(de, dk) : null;
      },
      // The levels' spins and parities go along, for a gamma ray without a
      // multipolarity; one of order 3 or more read off them is not taken (a
      // gamma ray seen at all is no pure M3 at 73 keV: Th-229's alpha decay
      // would send out 8 electrons per decay through it), the default is.
      icc: (ds, g, lv) => {
        const a = mods.atom(ds.Z);
        let c = mods.icc(ds.Z, { ...g, placed: !!lv, Ji: lv?.J, Jf: lv ? finalLevel(ds, lv, g)?.J : undefined }, a);
        if (c?.rule === 'theory' && !String(g.MUL || '').trim() && /[EM][3-9]/.test(c.mul || '')) c = mods.icc(ds.Z, { ...g, placed: !!lv }, a);
        return c ? c.alpha : null;
      },
      atomic: (Z) => mods.atom(Z),
      capture: (Z, Et, n, rec, a) => mods.capture(Z, Et, n, rec, a),
      minAtomicZ: 11,
      // A data set without a branching ratio takes the adopted one, and one
      // with relative intensities only is scaled by its own balance.
      branchOf: (f) => {
        const pcts = brs.filter(([m, p]) => FAM[m] === f && p > 0).map(([, p]) => p);
        return pcts.length ? pcts.reduce((a, b) => a + b, 0) / 100 : NaN;
      },
      normaliseRelative: true,
      adoptedBranches: true,
      feedingsFromBalance: true,
      checkBalance: true,
      unlistedDeexcitation: true,
      positronFraction: (Z, A, Et, n, rec, a) => positronFraction(Z, A, Et, n, mods.capture(Z, Et, n, rec, a)?.K || 0, a.binding.K),
      // A short isomer that a cascade reaches and its data set does not let
      // out: the isomer's own IT data set carries on (one that decays
      // otherwise is a radionuclide of its own, not a de-excitation).
      continuation(Zd, Ad, lv) {
        const de = nuc.get(Zd * 1000 + Ad);
        const dk = stateOfLevel(de, lv);
        if (!(dk > 0) || isMember(de, dk) || nonIT(de.s[dk])) return null;
        const key = `${Zd * 1000 + Ad}:${dk}`;
        if (contCache.has(key)) return contCache.get(key);
        contCache.set(key, null); // a cycle stops here
        const dss = pick(byState.get(key) || []);
        if (!dss.length) return null;
        const cst = de.s[dk];
        const r = stateRadiations({ Z: Zd, A: Ad, E: cst.en || 0, T: cst.ts, J: cst.j, Q: NaN, datasets: dss }, ctxFor(cst, branchesOf(cst, [])));
        contCache.set(key, r);
        return r;
      },
    };
  }

  const records = new Map();
  const names = new Map();
  for (const e of summary.nuclides) {
    if (!(e.z >= 1) || !SYMBOL[e.z]) continue; // the free neutron is no radionuclide of the body
    if (opt.only && !opt.only(e.z, e.a)) continue;
    for (let k = 0; k < (e.s || []).length; k++) {
      if (!isMember(e, k)) continue;
      const st = e.s[k];
      const name = nameOf(e, k);
      names.set(`${e.z},${e.a},${k}`, name);
      const notes = [];
      const brs = branchesOf(st, notes);
      // A data set of a mode the adopted levels do not give (or give as 0)
      // counts with a minor branch of its own (Pb-202's alpha decay, BR 0.01
      // beside the adopted "%EC=100"), and is set aside without one: Tb-156's
      // 88 keV isomer decays by IT, and its capture data set, taken as the
      // whole decay, would add a second one.
      const dss = pick(byState.get(`${e.z * 1000 + e.a}:${k}`) || []).filter((ds) => {
        if (!brs.length || brs.some(([m, p]) => FAM[m] === family(ds.mode) && p > 0)) return true;
        const own = ds.norm?.BR;
        if (own > 0 && own < 1) {
          // ... taken from the adopted levels' largest branch where they add up to 100 %
          const sum = brs.reduce((t, [, p]) => t + p, 0);
          const top = brs.reduce((b, x) => (x[1] > (b?.[1] ?? -1) ? x : b), null);
          if (top && sum + own * 100 > 100.001) top[1] = Math.max(0, top[1] - (sum + own * 100 - 100));
          notes.push(`${ds.dsid}: a mode the adopted levels do not give, with its own branch ${own}`);
          return true;
        }
        notes.push(`${ds.dsid}: a mode the adopted levels do not give, and no branch of its own: set aside`);
        return false;
      });
      const covered = new Set(dss.map((ds) => family(ds.mode)));
      // IT with no data set of its own: one made from the adopted gamma rays.
      const itBr = brs.filter(([m, p]) => m === 'IT' && p > 0).reduce((s, [, p]) => s + p / 100, 0);
      if (k > 0 && itBr > 0 && !covered.has('IT')) {
        const syn = adoptedIT(adoptedOf.get(e.z * 1000 + e.a), st, itBr, mods);
        if (syn) { dss.push(syn); covered.add('IT'); notes.push(`IT ${pct(itBr)} %: no decay data set, the adopted gamma rays of the level carried down the cascade`); }
      }
      const state = { Z: e.z, A: e.a, E: st.en || 0, T: st.ts, J: st.j, Q: NaN, datasets: dss };
      const ctx = ctxFor(st, brs, name);
      const res = stateRadiations(state, ctx);
      for (const [mode, p, to] of brs) {
        const f = FAM[mode];
        if (!f || !(p > 0) || covered.has(f)) continue;
        const br = p / 100;
        if (f === 'SF') { res.sf = { br }; continue; }
        estimate(e, k, f, br, res, notes);
        res.modes.push(f);
        for (const [Zd, Ad, kd, frac] of to || []) {
          const de = nuc.get(Zd * 1000 + Ad);
          res.branches.push({ to: { Z: Zd, A: Ad, E: 0, member: kd > 0 && isMember(de, kd) ? nameOf(de, kd) : null }, br: br * frac, estimated: true });
        }
      }
      // Fission: lines {FF, N, P, BD} and the delayed betas' branches for the
      // spectrum, from a branch of 1e-9 on, as ICRP 107 counted it (JAERI
      // 1347, sec. 2.1): Am-241's 4e-12 is left out.
      let sf = null;
      if (res.sf && !(res.sf.br >= 1e-9)) res.sf = null;
      if (res.sf && mods.fission) sf = mods.fission(name, e.z, e.a, res.sf.br, notes);
      const rec = decayRecord(state, res, {
        name, beta: mods.beta, atom: mods.atom(e.z), sf: sf?.lines, sfBetas: sf?.betas, daughterName: (Z, A) => `${SYMBOL[Z]}-${A}`,
      });
      // The half-life as the evaluators wrote it ("65.924 H" -> "65.924h").
      const tm = /^\s*([0-9.]+(?:E[-+]?\d+)?)\s*(Y|D|H|M|S|MS|US|NS|PS|KY|MY|GY)\b/i.exec(st.t || '');
      if (tm) rec.t = tm[1] + tm[2].toLowerCase();
      if (res.sf?.br > 0) rec.sf = res.sf.br;
      rec.notes = [...res.notes, ...notes];
      records.set(name, rec);
    }
  }
  return { records, names };

  /* A mode with no decay data set, estimated from the Q value. */
  function estimate(e, k, f, br, res, notes) {
    const st = e.s[k];
    const q = (i) => Number(String(e.q?.[i] ?? '').replace(/[()]/g, ''));
    const Ep = st.en || 0;
    if (f === 'A') {
      const Qa = q(6);
      if (!(Qa > 0)) { notes.push(`alpha ${pct(br)} %: no decay data set and no Q value, left out`); return; }
      const Et = Qa + Ep, Ea = Et / (1 + 4.0026 / (e.a - 4));
      res.lines.push({ type: 'A', E: Ea, Y: br }, { type: 'AR', E: Et - Ea, Y: br });
      notes.push(`alpha ${pct(br)} %: no decay data set, one alpha group to the ground state from the Q value`);
    } else if (f === 'B-') {
      const Qb = q(0);
      if (!(Qb > 0)) { notes.push(`beta-minus ${pct(br)} %: no decay data set and no Q value, left out`); return; }
      res.betas.push({ Z: e.z + 1, A: e.a, E0: (Qb + Ep) / 1000, n: 0, positron: false, yield: br });
      notes.push(`beta-minus ${pct(br)} %: no decay data set, an allowed spectrum to the ground state from the Q value`);
    } else if (f === 'EC') {
      const d = nuc.get((e.z - 1) * 1000 + e.a);
      const Qec = d?.q ? -Number(String(d.q[0]).replace(/[()]/g, '')) : NaN;
      const atom = mods.atom(e.z - 1);
      if (!(Qec > 0) || !atom) { notes.push(`capture ${pct(br)} %: no decay data set and no Q value, left out`); return; }
      const Et = Qec + Ep;
      const p = mods.capture(e.z - 1, Et, 0, null, atom) || {};
      const fb = positronFraction(e.z - 1, e.a, Et, 0, p.K || 0, atom.binding.K);
      if (fb > 0) {
        res.betas.push({ Z: e.z - 1, A: e.a, E0: (Et - 2 * 510.99895) / 1000, n: 0, positron: true, yield: br * fb });
        res.lines.push({ type: 'AQ', E: 510.99895, Y: 2 * br * fb });
      }
      const vac = Object.fromEntries(Object.entries(p).map(([s, x]) => [s, br * (1 - fb) * x]));
      for (const [s, x] of Object.entries(vac)) res.vacancies[s] = (res.vacancies[s] || 0) + x;
      if (e.z - 1 >= 11) for (const ln of atom.relax(vac)) res.lines.push({ ...ln, type: ln.kind === 'X' ? 'X' : 'AE', E: ln.E * 1000 });
      notes.push(`capture ${pct(br)} %: no decay data set, allowed capture${fb > 0 ? ' and positrons' : ''} to the ground state from the Q value (no gamma rays)`);
    }
  }
}

/*
  The adopted branches of a state for the dose: a minor branch given only as
  an upper limit is left out (Es-250's "%A<3": no alpha was seen), and a
  branch given as a lower limit takes what the others leave ("%EC>97" is
  then 100 %).
*/
function branchesOf(st, notes) {
  const list = (st.br || []).filter(([, p]) => p > 0).map((b) => [...b]); // copies: the caller may adjust them
  const top = Math.max(0, ...list.map(([, p]) => p));
  const kept = list.filter(([m, p, , , op]) => {
    if (!/^<=?$/.test(op || '') || p >= top) return true;
    notes.push(`${m} ${op}${p} %: an upper limit only, left out`);
    return false;
  });
  const sum = kept.reduce((s, [, p]) => s + p, 0);
  const low = kept.find(([, , , , op]) => /^>=?$/.test(op || ''));
  if (low && sum < 100) {
    notes.push(`${low[0]} ${low[4]}${low[1]} %: taken as ${+(low[1] + 100 - sum).toPrecision(6)} %, what the other branches leave`);
    return kept.map((b) => (b === low ? [b[0], b[1] + 100 - sum, ...b.slice(2)] : b));
  }
  return kept;
}

/* The level a gamma ray of `lv` ends at: its FL field's, or the one at lv.E - E_gamma (same offset). */
function finalLevel(ds, lv, g) {
  const E = g.cont?.FL ? Number(String(g.cont.FL).replace(/[()]/g, '')) : lv.E - g.E;
  let best = null, d = Infinity;
  for (const x of ds.levels) { if ((x.offset || '') !== (lv.offset || '')) continue; const e = Math.abs(x.E - E); if (e < d) { d = e; best = x; } }
  return best && d <= Math.max(1, 0.002 * E) ? best : null;
}

/*
  IT of an isomer the release gives no IT data set for: a data set made from
  the adopted levels. The adopted gamma intensities are relative within each
  level, so the transitions are carried down from the isomer: a level's
  population leaves by its gamma rays in proportion to RI (1 + alpha), and
  lands where each one ends. The result carries total transition
  intensities (TI), which the processor turns into photons and electrons.
*/
function adoptedIT(ad, st, br, mods) {
  if (!ad) return null;
  const top = ad.levels.reduce((b, lv) => (Math.abs(lv.E - (st.en || 0)) < Math.abs((b?.E ?? Infinity) - (st.en || 0)) ? lv : b), null);
  if (!top || Math.abs(top.E - (st.en || 0)) > Math.max(1, 0.002 * top.E) || !top.gammas.length) return null;
  const levels = ad.levels.filter((lv) => lv.E <= top.E + 0.01).sort((a, b) => b.E - a.E);
  const pop = new Map([[top, 100]]);
  const atom = mods.atom(ad.Z);
  const out = levels.map((lv) => ({ ...lv, gammas: [], feeds: [] }));
  const at = new Map(levels.map((lv, i) => [lv, out[i]]));
  const near = (E) => levels.reduce((b, lv) => (Math.abs(lv.E - E) < Math.abs(b.E - E) ? lv : b), levels[0]);
  for (const lv of levels) {
    const P = pop.get(lv) || 0;
    if (!(P > 0) || !lv.gammas.length) continue;
    const w = lv.gammas.map((g) => {
      let r = mods.icc(ad.Z, { ...g, placed: true, Ji: lv.J, Jf: finalLevel(ad, lv, g)?.J }, atom);
      if (r?.rule === 'theory' && !String(g.MUL || '').trim() && /[EM][3-9]/.test(r.mul || '')) r = mods.icc(ad.Z, { ...g, placed: true }, atom);
      const c = r?.alpha || {};
      const a = Object.values(c).reduce((s, x) => s + x, 0);
      return Number.isFinite(g.RI) ? g.RI * (1 + a) : Number.isFinite(g.TI) ? g.TI : 0;
    });
    const W = w.reduce((s, x) => s + x, 0);
    if (!(W > 0)) continue;
    lv.gammas.forEach((g, i) => {
      const T = P * w[i] / W;
      at.get(lv).gammas.push({ ...g, RI: NaN, TI: T });
      const to = near(lv.E - g.E);
      if (to !== lv) pop.set(to, (pop.get(to) || 0) + T);
    });
  }
  return {
    Z: ad.Z, A: ad.A, nucid: ad.nucid, dsid: `${ad.A}${SYMBOL[ad.Z].toUpperCase()} IT DECAY (from the adopted levels)`, mode: 'IT', synthetic: true,
    parents: [{ Z: ad.Z, A: ad.A, E: top.E, Eraw: top.Eraw, J: top.J, T: st.ts, Q: NaN }],
    norm: { NR: 1, NT: 1, BR: br, NB: 1, NP: NaN }, pn: null, levels: out.reverse(), unplaced: { gammas: [], feeds: [] }, fission: null, date: '',
  };
}
