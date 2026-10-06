/*
  Decay data for dose_coefficients.html from a release of ENSDF, in the form
  of the ICRP data the page has built in: decay/index.json (half-lives,
  modes, daughters, energies per decay) and decay/<El>.json (the radiations,
  in decay-format.js's form), with notes.json, what the making had to decide
  for each state (ensdf-release.js).

  One module for scripts/gen-dose-ensdf.mjs, which builds the release the
  site offers, and for the page's own worker (ensdf-make-worker.js), which
  makes a release a visitor opens: the same release gives the same data
  either way, to the round-off of the JavaScript engine's arithmetic (Node
  and the browser can differ in a line's sixth figure, and in the order of
  two lines of the same energy; the index, with every half-life, branch and
  energy per decay, comes out the same).

  `page`: only what the page can reach -- every state of at least 10
  minutes, every state that takes the name of a nuclide of a system's own
  decay data (decay-names.js), and the chains of those. A whole release is
  265 MB of text; for the page it is read twice and never held at once:
  first for its summary (ensdf-parse.js), which says what can be reached,
  then for the decay data sets of those nuclides only. Without `page`, every
  state, in one reading.
*/
import { readDatasets, SYMBOL, nucid } from './ensdf-decay.js';
import { releaseRecords, releaseMembers } from './ensdf-release.js';
import { captureFractions } from './ensdf-capture.js';
import { fissionParameters, fissionRadiations, delayedBetaBranches } from './ensdf-fission.js';
import * as beta from './beta-spectrum.js';
import * as atomic from './atomic-relax.js';
import * as icc from './ensdf-icc.js';
import { pairNames } from './decay-names.js';
import { compactRad, compactSpectrum, sig } from './decay-format.js';
export { MAKE_VERSION } from './decay-store.js';

const TEN_MINUTES = 10 / 1440; // days

/**
 * @param {object} p
 * @param {() => (AsyncIterable|Iterable)<{name: string, text: string}>} p.texts  the release's files,
 *        read afresh at each call (twice with `page`)
 * @param {object} p.ENSDF   ensdf-parse.js (createBuilder)
 * @param {object} p.tables  {atomic: (symbol) => json | null (atomic-relax.js's tables), icc: icc.json, capture: capture.json}
 * @param {object} [p.own]   {icrp103: index, icrp60: index}: the systems' own decay indexes (`page` only)
 * @param {boolean} [p.page] only what the page can reach
 * @param {number} [p.minIsomer]  seconds (60)
 * @param {object} p.release {id, label, source}
 * @param {function} [p.progress]  ({stage: 'reading' | 'sorting' | 'making', done, total, name})
 * @returns {Promise<{index: object, elements: object, notes: object, stats: object}>}
 *   index: decay/index.json; elements: symbol -> decay/<El>.json; notes: notes.json
 */
export async function makeDecayData(p) {
  const minIsomer = p.minIsomer ?? 60;
  const progress = p.progress || (() => {});
  const t0 = Date.now();

  // First reading: the summary, and without `page` the data sets too.
  let builder = p.ENSDF.createBuilder();
  let datasets = [], adopted = [];
  let files = 0;
  for await (const { name, text } of p.texts()) {
    builder.addText(text);
    if (!p.page) for (const ds of readDatasets(text, { adopted: true })) (ds.adopted ? adopted : datasets).push(ds);
    progress({ stage: 'reading', done: ++files, name });
  }
  const { summary } = builder.finish({ id: p.release.id || 'ensdf', label: p.release.label, source: p.release.source, built: '' });
  builder = null; // it holds the whole release
  if (!summary.nuclides?.length) throw new Error('no adopted ENSDF data sets were found; is this an ENSDF file?');
  const t1 = Date.now();

  // The radiations: atomic data, conversion and capture tables, fission.
  const atoms = new Map();
  const atom = (Z) => {
    if (!atoms.has(Z)) { const json = SYMBOL[Z] ? p.tables.atomic(SYMBOL[Z]) : null; atoms.set(Z, json ? atomic.element(json) : null); }
    return atoms.get(Z);
  };
  const captureTable = p.tables.capture.table;
  const mods = {
    beta,
    atom,
    icc: (Z, g, a) => (a ? icc.conversion(Z, g, { table: p.tables.icc, binding: a.binding }) : null),
    capture: (Z, Et, n, rec, a) => captureFractions(Z, Et, n, rec, a, captureTable),
    fission(name, Z, A, br, notes) {
      const f = fissionParameters(name, Z, A);
      if (f.estimated) notes.push(`fission ${(br * 100).toPrecision(3)} %: nu-bar and Watt parameters estimated (not in EDISTR04's table)`);
      return {
        lines: fissionRadiations(Z, A, br, f).map(([E, Y, kind]) => [E, Y, kind === 'PG' || kind === 'DG' ? 'P' : kind]),
        betas: delayedBetaBranches(Z, A, br, beta.betaShape),
      };
    },
  };
  const make = (only) => releaseRecords({ summary, datasets, adopted }, mods, { minIsomer, only }).records;

  let records, seeds = null;
  if (!p.page) {
    progress({ stage: 'making', done: 0 });
    records = make(undefined);
  } else {
    // What the page can reach: the seeds, and the nuclides their chains pass
    // through by the adopted branches.
    const members = releaseMembers(summary, { minIsomer });
    const radioactive = new Map(members.map((m) => [m.name, m.z * 1000 + m.a]));
    // Adopted levels serve only the IT of an isomer that has no IT data set (ensdf-release.js adoptedIT).
    const withIT = new Set(summary.nuclides.filter((e) => (e.s || []).some((st, k) => k > 0 && (st.br || []).some(([m, pc]) => m === 'IT' && pc > 0)))
      .map((e) => e.z * 1000 + e.a));
    const prov = Object.fromEntries(members.map((m) => [m.name, { T: m.T, d: [] }]));
    seeds = new Set(members.filter((m) => m.T >= TEN_MINUTES).map((m) => m.name));
    for (const own of Object.values(p.own || {})) {
      const names = pairNames(own, prov);
      for (const m of members) if (own[names.pageOf(m.name)]) seeds.add(m.name);
    }
    const toOf = new Map();
    for (const m of members) {
      const k = m.z * 1000 + m.a;
      if (!toOf.has(k)) toOf.set(k, []);
      toOf.get(k).push(...m.to.map(([z, a]) => z * 1000 + a));
    }
    const reach = new Set();
    const widen = (start) => {
      const added = new Set();
      const stack = [...start];
      while (stack.length) {
        const k = stack.pop();
        if (reach.has(k)) continue;
        reach.add(k); added.add(k);
        for (const d of toOf.get(k) || []) stack.push(d);
      }
      return added;
    };
    let todo = widen(members.filter((m) => seeds.has(m.name)).map((m) => m.z * 1000 + m.a));
    // The data sets of those nuclides, read again; and again for any nuclide
    // a record decays to that the adopted branches did not name (a data set
    // of a mode the adopted levels leave out: Md-258m's beta decay to No-258).
    for (let round = 0; todo.size && round < 4; round++) {
      files = 0;
      for await (const { name, text } of p.texts()) {
        for (const ds of readDatasets(text, { adopted: true })) {
          if (ds.adopted) { if (todo.has(ds.Z * 1000 + ds.A) && withIT.has(ds.Z * 1000 + ds.A)) adopted.push(ds); continue; }
          const par = ds.parents[0] || nucid(ds.parentNucid || '') || ds;
          if (par && todo.has(par.Z * 1000 + par.A)) datasets.push(ds);
        }
        progress({ stage: 'sorting', done: ++files, name, round });
      }
      progress({ stage: 'making', done: 0, round });
      records = make((z, a) => reach.has(z * 1000 + a));
      const more = [];
      for (const r of records.values()) for (const [d] of r.d) if (!records.has(d) && radioactive.has(d) && !reach.has(radioactive.get(d))) more.push(radioactive.get(d));
      todo = widen(more);
    }
  }
  datasets = adopted = null;
  const t3 = Date.now();

  // With `page`, the seeds' chains as the records give them.
  let keep = null;
  if (seeds) {
    keep = new Set();
    const stack = [...seeds].filter((n) => records.has(n));
    while (stack.length) {
      const n = stack.pop();
      if (keep.has(n) || !records.has(n)) continue;
      keep.add(n);
      for (const [d] of records.get(n).d) stack.push(d);
    }
  }
  const nuclides = {}, elements = {}, notes = {};
  for (const [name, r] of records) {
    if (keep && !keep.has(name)) continue;
    const el = /^([A-Z][a-z]?)-/.exec(name)[1];
    nuclides[name] = { t: r.t, T: sig(r.T, 8), m: r.mode, d: r.d.map(([d, b]) => [d, sig(b)]), E: r.E.map((x) => sig(x, 6)) };
    if (r.sf > 0) nuclides[name].sf = sig(r.sf);
    (elements[el] ||= {})[name] = { r: compactRad(r.rad), bs: compactSpectrum(r.bs) };
    if (r.notes.length) notes[name] = r.notes;
  }
  return {
    index: { label: p.release.label, release: p.release.id, source: p.release.source, nuclides },
    elements, notes,
    stats: { states: records.size, kept: Object.keys(nuclides).length, files, ms: { read: t1 - t0, make: t3 - t1 } },
  };
}
