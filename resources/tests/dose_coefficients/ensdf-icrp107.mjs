/*
  The ENSDF processor (resources/js/dose/ensdf-*.js) run the way EDISTR04 ran
  for ICRP Publication 107, on ICRP 107's own inputs, so that its records can
  be held against ICRP 107's.

  ICRP 107's supplementary data hold, besides the ICRP-07 files the page has
  built in, an ARCHIVE folder: INPUT, the ENSDF data sets as Endo and
  Eckerman revised them for EDISTR04 (2004), and OUTPUT, EDISTR04's printout
  for every nuclide (1033 files: the conversion coefficients it used, its
  every radiation line with its INDEX, the beta spectra). Neither is ours to
  publish; they are read from your own copy of the package.

  What EDISTR04 did that the processor does differently by default, and that
  the emulation here sets back:
    - conversion coefficients: EDISTR04's own (Rösel's theory), read off its
      radiation list per gamma ray (edistrIcc), instead of ENSDF's;
    - electron capture: the neutrino energies with the parent atom's binding
      energies (captureFractions' qAtom), which is what EDISTR04 did (with
      it, Np-235's K X-rays are a third of what the daughter's give);
    - vacancies beyond the O shell are not relaxed;
    - conversion electrons written at E - B(M3) for M and at the transition
      energy for N+ (decayRecord's edistr);
    - which daughter levels are chain members: those ICRP 107 lists as
      daughters, by the isomer's level energy (some carry dummy half-lives in
      the inputs);
    - spontaneous fission: ICRP 107's lines and spectra, scaled to the
      branch.
  And ICRP 107's own hand edits after EDISTR04 (OUTPUT/Mod_List.pdf).
*/
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { readDatasets, parentStates, stateRadiations, decayRecord, SYMBOL } from '../../js/dose/ensdf-decay.js';
import { captureFractions } from '../../js/dose/ensdf-capture.js';
import * as beta from '../../js/dose/beta-spectrum.js';
import * as atomic from '../../js/dose/atomic-relax.js';

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const ROOT = path.resolve(HERE, '../../..');

/* Where your copies are: ICRP107 = the folder "P 107 JAICRP 38(3) Nuclear
   Decay Data for Dosimetric Calculations(supplementary data)" (with ARCHIVE/
   and ICRP-07.*), EADL1991 = the atomic tables of the 1991 library, made by
   scripts/gen-dose-atomic.mjs from ENDF/B-VII.1's atomic relaxation zip. */
export const PATHS = {
  icrp107: process.env.ICRP107 || `${process.env.HOME}/Downloads/ICRP/icrp 107/P 107 JAICRP 38(3) Nuclear Decay Data for Dosimetric Calculations(supplementary data)`,
  eadl1991: process.env.EADL1991 || path.join(HERE, 'local/eadl1991'),
};
export const have = () => fs.existsSync(path.join(PATHS.icrp107, 'ARCHIVE/INPUT')) && fs.existsSync(PATHS.eadl1991);

const lines = (f) => fs.readFileSync(f, 'latin1').replace(/\r/g, '').split('\n');
const num = (s) => { const t = String(s).trim().replace(/E\s+/i, 'E+'); return t ? Number(t) : NaN; };
const UNIT = { us: 1e-6, ms: 1e-3, s: 1, m: 60, h: 3600, d: 86400, y: 31557600 };

/* ---------------------------------------------------------------------------
   ICRP 107's files
   --------------------------------------------------------------------------- */

/** ICRP-07.NDX: name -> {T (s), d: [[name, br]]} */
export function readNdx(dir = PATHS.icrp107) {
  const out = new Map();
  for (const l of lines(path.join(dir, 'ICRP-07.NDX')).slice(1)) {
    if (!l.trim()) continue;
    const name = l.slice(0, 7).trim();
    const d = [];
    let p = 53;
    for (let k = 0; k < 4; k++) {
      const dn = l.slice(p, p + 7).trim();
      if (dn) d.push([dn, num(l.slice(p + 13, p + 24))]);
      p += 25;
    }
    out.set(name, { name, T: num(l.slice(7, 15)) * UNIT[l.slice(15, 17).trim()], d });
  }
  return out;
}

/** ICRP-07.RAD: name -> [{code, Y, E (MeV), tag}] */
export function readRad(dir = PATHS.icrp107) {
  const L = lines(path.join(dir, 'ICRP-07.RAD'));
  const out = new Map();
  for (let i = 0; i < L.length; i++) {
    const h = L[i].trim().split(/\s+/);
    if (h.length < 3 || !/^[A-Z][a-z]?-\d+[a-z]*$/.test(h[0])) continue;
    const n = Number(h[2]);
    const list = [];
    for (let k = 1; k <= n; k++) {
      const t = L[i + k].trim().split(/\s+/);
      list.push({ code: Number(t[0]), Y: num(t[1]), E: num(t[2]), tag: t[3] || '' });
    }
    out.set(h[0], list);
    i += n;
  }
  return out;
}

/** ICRP-07.BET: name -> [[E...], [N...]] */
export function readBet(dir = PATHS.icrp107) {
  const L = lines(path.join(dir, 'ICRP-07.BET'));
  const out = new Map();
  for (let i = 0; i < L.length; i++) {
    const h = L[i].trim().split(/\s+/);
    if (h.length !== 2 || !/^[A-Z][a-z]?-\d+[a-z]*$/.test(h[0])) continue;
    const n = Number(h[1]);
    const E = [], N = [];
    for (let k = 1; k <= n; k++) { E.push(num(L[i + k].slice(0, 8))); N.push(num(L[i + k].slice(8))); }
    out.set(h[0], [E, N]);
    i += n;
  }
  return out;
}

/**
 * An EDISTR04 printout (ARCHIVE/OUTPUT/*.out): one entry per parent state
 * {date, head: {A, el, Z, iso, Ts}, seei: [{code, idx, Y (per decay), E, Emax, x}]}.
 */
export function readOut(file) {
  const states = [];
  let st = null, sec = null;
  for (const l of lines(file)) {
    if (l.startsWith('%%%%')) {
      const head = l.slice(4, 60);
      const key = head.trim();
      if (!st || st.key !== key) {
        const m = /^\s*(\d+)\s+([A-Z]+)\s+(\d+)\s+(M?)\s*(.*?)\s+([0-9.]+E[-+]\d+)/.exec(head);
        st = { key, date: (/(\d\d-\d\d-\d{4})/.exec(l) || [])[1] || '', head: m ? { A: Number(m[1]), el: m[2], Z: Number(m[3]), iso: m[4] === 'M', Ts: Number(m[6]) } : null, seei: [] };
        states.push(st);
      }
      const tag = l.slice(-8).trim();
      sec = tag.endsWith('STAR') ? tag.slice(0, 4) : null;
      continue;
    }
    if (st && sec === 'SEEI' && /^\s*\d/.test(l) && !/^\s*\d+\.\s+[A-Z]/.test(l)) {
      const code = Number(l.slice(0, 2)), idx = Number(l.slice(2, 4));
      const f = l.slice(4, 56).trim().split(/\s+/).map(num);
      if (Number.isFinite(code) && f.length >= 4) st.seei.push({ code, idx, Y: f[0] / 100, E: f[1], Emax: f[2], x: f[3] });
    }
  }
  return states;
}

/* ---------------------------------------------------------------------------
   EDISTR04's ways
   --------------------------------------------------------------------------- */

/**
 * EDISTR04's conversion coefficients per gamma ray, from its radiation list:
 * each shell's electrons over the gamma's photons; electron lines at
 * E - B with EADL 1991's binding energies (K, L1-L3, M at B(M3), N+ at 0).
 * Gamma rays of one energy take the photon lines one each, by expected
 * photon yield, their electron lines in the same order of yield. M and N+
 * are spread over M1-M3 and N1-N3 (four parts) and O1-O3 (one) like L1:L2:L3.
 */
export function edistrIcc(out, atom) {
  if (!out || !atom) return () => null;
  const ie = out.seei.filter((l) => l.code === 6);
  const gam = out.seei.filter((l) => l.code === 1);
  const B = atom.binding;
  const shellB = { 1: B.K, 5: B.L1, 6: B.L2, 7: B.L3, 3: B.M3, 4: 0 };
  const name = { 1: 'K', 5: 'L1', 6: 'L2', 7: 'L3', 3: 'M', 4: 'N+' };
  const near = (l, E) => Math.abs(l.E - E) <= Math.max(2e-6, 2e-5 * E);
  const atE = (idx, Ee) => ie.filter((l) => l.idx === idx && Math.abs(l.E - Ee) <= Math.max(3e-6, 3e-5 * Ee)).sort((a, b) => b.Y - a.Y);
  const usedPh = new Set();
  const split = (r) => {
    const out2 = {};
    for (const s of ['K', 'L1', 'L2', 'L3']) if (r[s] > 0) out2[s] = r[s];
    const L = (r.L1 || 0) + (r.L2 || 0) + (r.L3 || 0);
    const w = L > 0 ? [r.L1 || 0, r.L2 || 0, r.L3 || 0].map((x) => x / L) : [1, 0, 0];
    for (const [g2, pre, part] of [['M', 'M', 1], ['N+', 'N', 0.8], ['N+', 'O', 0.2]]) {
      if (!(r[g2] > 0)) continue;
      w.forEach((f, i) => { if (f > 0) out2[`${pre}${i + 1}`] = (out2[`${pre}${i + 1}`] || 0) + r[g2] * f * part; });
    }
    return out2;
  };
  return (ds, g) => {
    const Eg = g.E / 1000;
    const phs = gam.filter((l) => near(l, Eg) && l.Y > 0).sort((a, b) => b.Y - a.Y);
    if (!phs.length) {
      // No photons (an E0 transition, or one given only by its total): the
      // shells' electrons as weights so large that no photon is left over.
      if (!(/^\W*E0\W*$/.test(g.MUL) || (!Number.isFinite(g.RI) && Number.isFinite(g.TI)))) return null;
      const r = {};
      for (const idx of [1, 5, 6, 7, 3, 4]) {
        if (!(shellB[idx] >= 0)) continue;
        const hit = atE(idx, (g.E - shellB[idx]) / 1000)[0];
        if (hit) r[name[idx]] = hit.Y * 1e12;
      }
      return Object.keys(r).length ? split(r) : null;
    }
    const pool = phs.filter((l) => !usedPh.has(l)).length ? phs.filter((l) => !usedPh.has(l)) : phs;
    let ph = pool[0];
    if (pool.length > 1) {
      const n = ds.norm || {};
      const want = Number.isFinite(g.RI) ? g.RI * (Number.isFinite(n.NR) ? n.NR : 1) * (Number.isFinite(n.BR) ? n.BR : 1) / 100 : NaN;
      ph = Number.isFinite(want) ? pool.reduce((b, l) => (Math.abs(Math.log(l.Y / want)) < Math.abs(Math.log(b.Y / want)) ? l : b)) : pool[pool.length - 1];
    }
    usedPh.add(ph);
    const rank = phs.indexOf(ph);
    const r = {};
    for (const idx of [1, 5, 6, 7, 3, 4]) {
      if (!(shellB[idx] >= 0)) continue;
      const hits = atE(idx, (g.E - shellB[idx]) / 1000);
      const hit = hits[Math.min(rank, hits.length - 1)];
      if (hit) r[name[idx]] = hit.Y / ph.Y;
    }
    return Object.keys(r).length ? split(r) : null;
  };
}

/* ICRP 107's hand edits after EDISTR04 (OUTPUT/Mod_List.pdf): branching
   fractions set by hand, and three isomers EDISTR04 could not tell from
   their ground states (their records are left as ICRP 107 has them). */
export const MOD_BRANCH = new Set(['Fe-52', 'Y-85', 'Y-87', 'Nb-89m', 'Ru-94', 'Pd-101', 'Cd-104', 'Cd-115', 'Sn-108', 'Sn-126', 'Sn-128',
  'Hf-172', 'Hf-180m', 'Os-182', 'Th-234', 'U-240', 'Pu-239', 'Pu-246', 'Kr-76', 'Rb-81', 'Rb-81m', 'Dy-151', 'Hg-193', 'Hg-193m']);
export const MOD_KEEP = new Set(['Pr-134', 'Pr-134m', 'Np-242', 'Np-242m', 'Ir-192m', 'Ir-192n']);

/**
 * Every state of ICRP 107's inputs processed EDISTR04's way.
 * @returns {{ndx, rad, bet, results: Array<{name, state, res, rec, out}>}}
 */
export function emulate({ captureTable, raw = false } = {}) {
  const dir = PATHS.icrp107;
  const ndx = readNdx(dir), rad = readRad(dir), bet = readBet(dir);
  captureTable ||= JSON.parse(fs.readFileSync(path.join(ROOT, 'resources/data/dose/capture.json'), 'utf8')).table;
  const atoms = new Map();
  const atom = (Z) => {
    if (!atoms.has(Z)) {
      const f = path.join(PATHS.eadl1991, `${SYMBOL[Z]}.json`);
      atoms.set(Z, fs.existsSync(f) ? atomic.element(JSON.parse(fs.readFileSync(f, 'utf8'))) : null);
    }
    return atoms.get(Z);
  };
  // ICRP 107's names by element, mass and half-life.
  const byEA = new Map();
  for (const r of ndx.values()) {
    const m = /^([A-Z][a-z]?)-(\d+)([a-z]*)$/.exec(r.name);
    const k = `${m[1]}-${m[2]}`;
    if (!byEA.has(k)) byEA.set(k, []);
    byEA.get(k).push(r);
  }
  const nameOf = (Z, A, iso, T) => {
    let best = null, d = Infinity;
    for (const r of (byEA.get(`${SYMBOL[Z]}-${A}`) || []).filter((x) => iso === /[a-z]$/.test(x.name))) {
      const x = T > 0 ? Math.abs(Math.log10(r.T / T)) : 0;
      if (x < d) { d = x; best = r; }
    }
    return best && d < 0.5 ? best.name : null;
  };
  const outs = new Map();
  for (const f of fs.readdirSync(path.join(dir, 'ARCHIVE/OUTPUT')).filter((x) => /\.out$/i.test(x))) {
    for (const st of readOut(path.join(dir, 'ARCHIVE/OUTPUT', f))) {
      const name = st.head && nameOf(st.head.Z, st.head.A, st.head.iso, st.head.Ts);
      if (name) outs.set(name, st);
    }
  }
  const files = fs.readdirSync(path.join(dir, 'ARCHIVE/INPUT')).filter((x) => /\.ens$/i.test(x))
    .map((f) => parentStates(readDatasets(fs.readFileSync(path.join(dir, 'ARCHIVE/INPUT', f), 'latin1'))));
  const isomerAt = new Map();
  for (const states of files) for (const s of states) {
    const name = s.E > 0 && nameOf(s.Z, s.A, true, s.T);
    if (!name) continue;
    const k = `${s.Z},${s.A}`;
    if (!isomerAt.has(k)) isomerAt.set(k, []);
    isomerAt.get(k).push({ E: s.E, name });
  }
  const results = [];
  for (const states of files) {
    for (const state of states) {
      const name = nameOf(state.Z, state.A, state.E > 0, state.T);
      if (!name || (!raw && MOD_KEEP.has(name))) continue;
      const ref = ndx.get(name), out = outs.get(name);
      const daughters = new Set(ref.d.map(([d]) => d));
      const iccBy = {};
      const ctx = {
        member(Zd, Ad, lv) {
          for (const iso of isomerAt.get(`${Zd},${Ad}`) || []) if (Math.abs(iso.E - lv.E) <= Math.max(0.5, 2e-4 * lv.E) && daughters.has(iso.name)) return iso.name;
          if (!(lv.T > 0) || !Number.isFinite(lv.T)) return null;
          const n = nameOf(Zd, Ad, true, lv.T);
          return n && daughters.has(n) ? n : null;
        },
        icc: (ds, g) => (iccBy[ds.Z] ||= edistrIcc(out, atom(ds.Z)))(ds, g),
        atomic: atom,
        capture: (Z, Et, n, rec, a) => captureFractions(Z, Et, n, rec, a, captureTable, atom(Z + 1) || a),
        minAtomicZ: 11,
        relaxable: (k) => !/^[PQ]/.test(k),
        // EDISTR04 counted a member isomer's cascade where the input listed it (Hf-182m's beta decay through Ta-182m2).
        memberCascades: false,
      };
      const res = stateRadiations(state, ctx);
      let sf = null;
      if (res.sf && res.sf.br > 0) {
        const refBr = (ref.d.find(([d]) => d === 'SF') || [])[1];
        const k = refBr > 0 ? res.sf.br / refBr : 1;
        sf = (rad.get(name) || []).filter((l) => ['PG', 'DG', 'DB'].includes(l.tag) || l.code === 10 || l.code === 11)
          .map((l) => [l.E, l.Y * k, l.code === 10 ? 'FF' : l.code === 11 ? 'N' : l.tag === 'DB' ? 'BD' : 'P']);
      }
      const rec = decayRecord(state, res, { name, beta, sf, edistr: true, daughterName: (Z, A) => `${SYMBOL[Z]}-${A}` });
      if (sf && bet.get(name)) rec.bs = bet.get(name);
      if (!raw && MOD_BRANCH.has(name)) rec.d = ref.d.filter(([d]) => d !== 'SF');
      results.push({ name, state, res, rec, out, ref, refRad: rad.get(name) || [] });
    }
  }
  return { ndx, rad, bet, results };
}
