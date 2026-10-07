/*
  The calculations of dose_coefficients.html, in module workers so that the
  page stays responsive while a long decay chain is integrated. The page
  keeps a pool of them and gives each one request at a time: the ages of a
  run, or the inhalations behind radon at home, one to a worker.

  main -> worker   {id, type: 'catalog', system}
                   {id, type: 'run', system, spec, ages, outputs, rtol, withSystem, lean}
                       withSystem: whether the first age's result carries the
                       chain, the models and the intake (default true); lean:
                       the doses only, without the transformations (batches);
                       spec.route 'external' (spec.geometry): dose rate
                       coefficients for external exposure (external.js),
                       every age in one request
                   {id, type: 'describe', system, spec, age}
                       the chain, the models, the intake and the size of the
                       system a run would solve, without solving it
                   {id, type: 'radon-plan', kind: 'radon' | 'thoron'}  (radon.js, ICRP 103)
                   {id, type: 'radon-job', job}   one job of the plan: its e, Sv per Bq
                   each of them with `decay`: the decay data to use, '' (or
                   none) for the system's own, 'ensdf:YYMMDD' for a release of
                   ENSDF built into the site (resources/data/dose/ensdf/),
                   'open:' and a key for one made in this browser from a
                   release a visitor opened (decay-store.js)
  worker -> main   {id, type: 'progress', done, total, text}
                   {id, type: 'result', result}
                   {id, type: 'error', message}
*/
import { loadSystem, fetchIO } from './data.js';
import { coefficients60, AGES_60, TISSUES_60, W_60, REMAINDER_60 } from './dose60.js';
import { recipe60, f1Table, assemble60 } from './model60.js';
import { assemble103, sexSpecific103 } from './model103.js';
import { TARGETS_60 } from './see60.js';
import { LUNG_REGIONS, CONTENTS, regionOf, key } from './regions.js';
import { coefficients103, AGES_103, TISSUES_103, W_103, W_REMAINDER_103, REMAINDER_103 } from './dose103.js';
import { catalog60, catalog103 } from './catalog.js';
import { batemanTransformations, buildChain } from './chain.js';
import { radonPlan, radonJob } from './radon.js';
import { storeIO } from './decay-store.js';
import { External, externalRun, equilibrium, effective, PHANTOM_OF_AGE } from './external.js';

const DATA = new URL('../../data/dose/', import.meta.url);
const io = fetchIO(DATA);
const systems = {};
function decayIO(decay) {
  if (!decay) return null;
  const m = /^ensdf:(\d{6})$/.exec(decay);
  if (m) return fetchIO(new URL(`ensdf/${m[1]}/`, DATA));
  const o = /^open:([\s\S]+)$/.exec(decay);
  if (o) return storeIO(o[1]);
  throw new Error(`unknown decay data: ${decay}`);
}
const system = (s, decay = '') => {
  const k = `${s}|${decay || ''}`;
  return (systems[k] ||= loadSystem(s, io, decayIO(decay)).catch((err) => { delete systems[k]; throw err; }));
};
/* External exposure: the monoenergetic data of the system's report (FGR 12
   or FGR 15), loaded once; what they give per geometry and age is kept. */
const externals = {};
const externalOf = (s) => (externals[s] ||= io.json(`external/fgr${s === '60' ? 12 : 15}.json`).then((d) => new External(d))
  .catch((err) => { delete externals[s]; throw err; }));

self.onmessage = async (ev) => {
  const msg = ev.data;
  const reply = (o) => self.postMessage({ id: msg.id, ...o });
  try {
    if (msg.type === 'catalog') {
      const data = await system(msg.system, msg.decay);
      const cat = msg.system === '60' ? catalog60(data) : catalog103(data);
      reply({ type: 'result', result: { ...cat, decay: { label: data.decaySource.label, own: data.decaySource.own } } });
      return;
    }
    if (msg.type === 'run' && msg.spec.route === 'external') {
      const data = await system(msg.system, msg.decay);
      const chain = await data.prepare(msg.spec.nuclide);
      const X = await externalOf(msg.system);
      const out = externalRun(X, data, chain, msg.system, msg.spec.geometry, msg.ages || [7300]);
      if (msg.withSystem !== false && out.length) Object.assign(out[0], externalSummary(msg.system, data, chain, X, msg.spec.geometry));
      if (msg.lean) for (const o of out) delete o.members;
      reply({ type: 'result', result: out });
      return;
    }
    if (msg.type === 'run') {
      reply({ type: 'progress', done: 0, total: 1, text: 'loading data' });
      const data = await system(msg.system, msg.decay);
      await data.prepare(msg.spec.nuclide);
      const ages = msg.ages || (msg.system === '60' ? AGES_60 : AGES_103);
      const out = [];
      for (let k = 0; k < ages.length; k++) {
        reply({ type: 'progress', done: k, total: ages.length, text: `age at intake ${k + 1} of ${ages.length}` });
        const t0 = performance.now();
        const opt = { outputs: msg.outputs, rtol: msg.rtol };
        const r = msg.system === '60'
          ? coefficients60(data, specFor60(data, msg.spec), [ages[k]], opt)[0]
          : coefficients103(data, msg.spec, [ages[k]], opt)[0];
        const o = summarise(msg.system, data, r, k === 0 && msg.withSystem !== false, performance.now() - t0);
        if (msg.lean) delete o.transformations;
        out.push(o);
      }
      reply({ type: 'result', result: out });
      return;
    }
    if (msg.type === 'describe') {
      const data = await system(msg.system, msg.decay);
      const chain = await data.prepare(msg.spec.nuclide);
      if (msg.spec.route === 'external') {
        const X = await externalOf(msg.system);
        reply({ type: 'result', result: externalSummary(msg.system, data, chain, X, msg.spec.geometry) });
        return;
      }
      reply({ type: 'result', result: describe(msg.system, data, msg.spec, msg.age ?? 7300) });
      return;
    }
    if (msg.type === 'radon-plan') {
      const data = await system('103', msg.decay);
      reply({ type: 'result', result: { ...radonPlan(data, msg.kind, AGES_103, buildChain), inputs: data.radon } });
      return;
    }
    if (msg.type === 'radon-job') {
      const data = await system('103', msg.decay);
      reply({ type: 'result', result: await radonJob(data, msg.job, coefficients103, AGES_103) });
      return;
    }
    throw new Error(`unknown request ${msg.type}`);
  } catch (e) {
    reply({ type: 'error', message: e && e.message ? e.message : String(e) });
  }
};

/* The ICRP 72 case for a nuclide and form, as DCAL's batch files ran it. */
function specFor60(data, spec) {
  // null picks the case without a special file; undefined would pick any.
  const s = recipe60(data.cases, spec.route, { nuclide: spec.nuclide, bio: spec.bio, f1file: spec.f1file === undefined ? undefined : spec.f1file,
    type: spec.type ?? undefined, lung: spec.route === 'inhalation' ? (spec.lung ?? null) : undefined, amad: spec.amad });
  if (spec.cutoff != null) s.cutoff = spec.cutoff;
  return s;
}

/* What the page shows of a result. */
function summarise(sys, data, r, withSystem, ms) {
  const S = r.system;
  const out = { age: r.age, intakeAge: r.intakeAge, E: r.E, H: r.H, ms, stats: r.stats, transformations: r.transformations, notes: S.notes || [] };
  if (sys === '60') Object.assign(out, { split: r.split, remainderShares: r.remainderShares });
  if (withSystem) Object.assign(out, systemSummary(sys, data, S));
  if (r.series) out.series = seriesSummary(sys, r);
  return out;
}

/* The chain, the models and the intake of an assembled system. */
function systemSummary(sys, data, S) {
  // A member's name in the decay data used, where it is not the system's (decay-names.js).
  const otherName = (n) => { const o = data.decaySource.otherOf?.(n); return o && o !== n ? o : null; };
  return {
    decay: data.decaySource.label,
    members: S.members.map((m, j) => ({ name: m.name, T: m.T, lambda: m.lambda, E: S.chain.members[j]?.E || null, kind: m.kind || (m.ownModel === false ? 'shared' : m.ownModel ? 'own model' : null), model: m.model || m.bio || null, of: m.of ?? null, other: otherName(m.name), decayNotes: data.decaySource.notesOf?.(m.name) || [] })),
    branches: S.chain.branches,
    dropped: S.chain.dropped,
    models: sys === '60' ? models60(data, S) : models103(data, S),
    progenyShare: progenyShare(data, S),
    intake: sys === '60' ? intake60(data, S) : S.intake,
    spec: S.spec,
    notes: S.notes || [],
  };
}

/* A run's system without the run: assembled for the age at intake given (its
   intake differs with age, its models do not), and how big it is -- the
   equations of one integration are the compartments' activities and, for
   each group of compartments that share their dose per transformation (a
   member in a source region), four integrals of its activity in the ICRP 103
   system and two in the ICRP 60 one, from which solve.js puts the doses to
   all targets together. In the ICRP 103 system a sex-specific model (radon)
   is two integrations per age, each with one sex's targets. */
const CUTOFFS = [0, 1e-5, 1e-4, 1e-3];
function describe(sys, data, spec, age0) {
  let S, regions, sexes, targets, perAge = 1;
  if (sys === '60') {
    const s = specFor60(data, spec);
    S = assemble60(data, { ...s, intakeAge: age0 === 7300 && s.adultAge ? s.adultAge : age0 });
    // The remainder, and the remainder with each of its tissues split off (dose60.js).
    regions = TARGETS_60.length;
    sexes = 0;
    const nr = Object.keys(REMAINDER_60).length;
    targets = regions + 1 + 2 * nr + nr * nr; // dose60.js's virtual targets
  } else {
    const adultAge = data.elements[spec.nuclide.split('-')[0]]?.adultAge || 7300;
    const split = sexSpecific103(data, spec);
    S = assemble103(data, { ...spec, intakeAge: age0 === 7300 ? adultAge : age0, sex: split ? 'M' : undefined });
    regions = data.saf.index.targets.length;
    sexes = split ? 1 : 2;
    targets = regions * sexes;
    perAge = split ? 2 : 1;
  }
  // The groups as dose103.js and dose60.js share their columns: a member in
  // a source region (and in the ICRP 103 system, for Other, whose Other).
  const groups = new Set(S.comps.map((c) => (sys === '60' ? `${c.member}|${c.region}`
    : `${c.member}|${c.region}|${c.region === 'Other' ? (c.otherOf ?? c.member) : -1}`))).size;
  const perGroup = sys === '60' ? 2 : 4;
  // The matrix: the diagonal, a value for each pair of compartments a
  // transfer or a decay joins, and a basis function for each compartment
  // in each of its group's integrals (solve.js).
  const pairs = new Set();
  for (const t of S.transfers) if (t.to >= 0) pairs.add(`${t.to},${t.from}`);
  for (const d of S.decays) pairs.add(`${d.to},${d.from}`);
  const size = {
    nuclides: S.members.length, compartments: S.comps.length, transfers: S.transfers.length, decays: S.decays.length,
    regions, sexes, targets, groups, perGroup, equations: S.comps.length + perGroup * groups, perAge,
    coefficients: S.comps.length + pairs.size + perGroup * (S.comps.length + groups),
  };
  // How many nuclides each cut-off keeps (ICRP 103; the ICRP 60 system cuts as DCAL did).
  const cutoffs = sys === '60' ? null : CUTOFFS.map((c) => ({
    cutoff: c, nuclides: buildChain(data.index, spec.nuclide, { cutoff: c, last: spec.last, horizonDays: 36525 }).members.length,
  }));
  return { ...systemSummary(sys, data, S), size, cutoffs, describedAge: age0 };
}

/* External exposure, for the Model and Decay chain tabs: the whole chain with
   each member's activity in equilibrium with the parent (null where it never
   is), its energies by kind, and the report's monoenergetic coefficients in
   the geometry: e and the skin's dose per photon at each energy and age, and
   the skin's per electron. */
function externalSummary(sys, data, chain, X, geometry) {
  const eq = equilibrium(chain);
  const otherName = (n) => { const o = data.decaySource.otherOf?.(n); return o && o !== n ? o : null; };
  const skin = X.tissues.indexOf('Skin');
  const mono = X.ages.map((phantom) => {
    const R = X.response(geometry, phantom);
    const age = Number(Object.keys(PHANTOM_OF_AGE).find((a) => PHANTOM_OF_AGE[a] === phantom));
    const points = X.data.energies.map((E) => {
      const h = R.tissues.map((t) => t.photon.at(E));
      return { E, e: effective(sys, X.tissues, h).E, skin: h[skin] };
    });
    return { age, phantom, points };
  });
  const curve = X.data.skin[{ air: 'air', water: 'water', surface: 'surface' }[geometry] || 'soil'];
  return {
    external: true, geometry, decay: data.decaySource.label,
    chain: chain.members.map((m, j) => ({ name: m.name, T: m.T, lambda: m.lambda, E: data.index[m.name]?.E || null, ratio: eq.ratio[j], other: otherName(m.name), decayNotes: data.decaySource.notesOf?.(m.name) || [] })),
    branches: chain.branches, days: eq.days, mono, electronSkin: { E: curve.E, h: curve.h },
  };
}

/* The share of the energy the chain emits in 50 years (alpha weighted by 20)
   that comes from members of another element than the parent: how much the
   coefficient rests on how progeny behave in the body. */
function progenyShare(data, S) {
  const names = S.chain.members.map((m) => m.name);
  if (names.length < 2) return 0;
  const u = batemanTransformations(data.index, names, 18262);
  const el = (n) => n.split('-')[0];
  let all = 0, other = 0;
  names.forEach((n, i) => {
    const [a, e, p] = data.index[n].E;
    const w = u[i] * (20 * a + e + p);
    all += w;
    if (el(n) !== el(names[0])) other += w;
  });
  return all > 0 ? other / all : 0;
}

/* ---- the models, for the Model tab ---------------------------------------- */
function models103(data, S) {
  return S.members.map((m, j) => {
    let k = j;
    while (S.members[k].kind === 'mirror') k = S.members[k].of;
    const mk = S.members[k];
    const E = data.elements[mk.el];
    const key = mk.modelKey || 'default';
    const model = mk.progeny?.model || E?.systemic?.[key] || (E && Object.values(E.systemic || {})[0]);
    const GAS = { gas: 'Noble gas formed in the body (the generic model of the OIR series): to blood at 100 d-1 from bone surfaces, 1.5 from exchangeable and 0.36 from other bone volume, from soft tissue with a half-time of 30 min (radon), 20 min (xenon) or 15 min (krypton); exhaled from blood at 1000 d-1',
      decay: 'Decays where it is formed (OIR series)' };
    if (!model || ['gas', 'decay', 'independent-fallback', 'gas-progeny-fallback'].includes(m.kind)) {
      return { member: m.name, kind: m.kind, label: GAS[m.kind] || 'No model', compartments: [], transfers: [], ages: [], entry: null };
    }
    return {
      member: m.name, kind: m.kind, of: k !== j ? S.members[k].name : null, element: E?.name || mk.el, source: mk.progeny?.model ? null : E?.source,
      label: model.label || key, table: model.table || null, ages: model.ages, entry: model.entry,
      compartments: Object.entries(model.compartments).map(([name, region]) => ({ name, region })),
      transfers: model.transfers,
    };
  }).map((v, j) => {
    if (!v.compartments.length) return v;
    const { rows, boxes } = onwardOf('103', S, memberOf103(S, j), v);
    return { ...v, onward: rows, tract: boxes };
  });
}
const memberOf103 = (S, j) => { let k = j; while (S.members[k].kind === 'mirror') k = S.members[k].of; return k; };

function models60(data, S) {
  return S.members.map((m, j) => {
    const def = data.models.systemic[m.bio];
    if (!def) return { member: m.name, label: m.bio, compartments: [], transfers: [], ages: [] };
    const names = new Set();
    for (const [a, b] of def.transfers) { names.add(a); names.add(b); }
    const v = {
      member: m.name, kind: m.ownModel ? 'own model' : 'shared', label: def.title, file: `${m.bio}.DEF`, ages: def.ages,
      entry: [...names].find((n) => /^blood$/i.test(n)) || [...names][0],
      compartments: [...names].map((name) => ({ name, region: regionOf(name) || name })),
      transfers: def.transfers, text: def.text || [],
    };
    const { rows, boxes } = onwardOf('60', S, j, v);
    return { ...v, onward: rows, tract: boxes };
  });
}

/* ---- around the systemic model: the alimentary tract and the bladder ---------- */
/* What reaches the gut or the bladder goes on through the alimentary tract and
   bladder models the calculation adds around every systemic model: down the
   tract to faeces, back to blood by absorption, out of the bladder in urine.
   These are the transfers onward from the member's contents compartments
   that its activity can reach -- from its systemic compartments, swallowed
   or cleared from the airways, or formed there by decay -- read from the
   assembled system, with their rates at the model's ages; named as the
   systemic model names those compartments, the others by what they are. The
   mouth and the oesophagus, which activity passes in seconds to minutes, are
   left out. Of the two copies of the tract in the ICRP 103 system, the
   secretions' comes first: where both have a transfer, its rate is shown. */
const TRACT_NAMES = {
  'O-cavity': 'Oral cavity', 'Oesophag-f': 'Oesophagus (fast)', 'Oesophag-s': 'Oesophagus (slow)', 'St-cont': 'Stomach contents',
  'SI-cont': 'SI contents', 'RC-cont': 'Right colon contents', 'LC-cont': 'Left colon contents', 'RS-cont': 'Rectosigmoid contents', 'UB-cont': 'UB contents',
};
const TRACT_60 = new Set(['St_Cont', 'SI_Cont', 'ULI_Cont', 'LLI_Cont', 'UB_Cont']);
function onwardOf(sys, S, k, model) {
  const isTract = sys === '103' ? (c) => c.kind === 'gi' || c.kind === 'ub' : (c) => TRACT_60.has(c.region);
  const mine = (c) => c.member === k;
  const named = new Map(model.compartments.filter((c) => /cont/i.test(c.region)).map((c) => [c.region, c.name]));
  // ICRP 60: DCAL's names, as its models have them; ICRP 103: names that say what they are.
  const nameOf = (c) => (isTract(c) ? named.get(c.region) || (sys === '103' ? TRACT_NAMES[c.region] : c.name) || c.region : c.name);
  const ages = model.ages && model.ages.length ? model.ages : null;
  const ratesOf = (t) => (ages ? ages.map((a) => lerp(t.ages && t.rates.length > 1 ? t.ages : null, t.rates, a)) : [t.rates[t.rates.length - 1]]);
  const queue = [];
  const seen = new Set();
  for (const t of S.transfers) {
    if (t.to < 0) continue;
    const a = S.comps[t.from], b = S.comps[t.to];
    if (mine(a) && mine(b) && !isTract(a) && isTract(b) && !seen.has(t.to)) { seen.add(t.to); queue.push(t.to); }
  }
  const passing = (c) => /^(O-cavity|Oesophag-[fs])$/.test(c.region);
  const more = reachable(S).filter((i) => { const c = S.comps[i]; return mine(c) && isTract(c) && !passing(c) && !seen.has(i); })
    .sort((a, b) => (S.comps[a].track === 'I') - (S.comps[b].track === 'I') || a - b);
  for (const i of more) { seen.add(i); queue.push(i); }
  const out = [], keys = new Set();
  while (queue.length) {
    const i = queue.shift(), a = S.comps[i];
    for (const t of S.transfers) {
      if (t.from !== i) continue;
      const b = t.to >= 0 ? S.comps[t.to] : null;
      if (b && !mine(b)) continue;
      const row = { from: nameOf(a), to: b ? nameOf(b) : t.sink, fromRegion: a.region, toRegion: b ? b.region : t.sink,
        rates: ratesOf(t), model: /^UB/i.test(a.region) ? 'bladder' : 'alimentary' };
      const key = `${row.from}→${row.to}`;
      if (!keys.has(key)) { keys.add(key); out.push(row); }
      if (b && isTract(b) && !seen.has(t.to)) { seen.add(t.to); queue.push(t.to); }
    }
  }
  // Every contents compartment reached is a box, with transfers out of it or
  // not (a noble gas formed in the stomach decays there, ICRP 60).
  const boxes = new Map();
  for (const i of seen) { const c = S.comps[i]; if (!boxes.has(nameOf(c))) boxes.set(nameOf(c), { name: nameOf(c), region: c.region }); }
  return { rows: out, boxes: [...boxes.values()] };
}

/* The compartments an intake can ever put activity in: from where it is
   deposited, along the transfers and the decays. */
function reachable(S) {
  const next = S.comps.map(() => []);
  for (const t of S.transfers) if (t.to >= 0) next[t.from].push(t.to);
  for (const d of S.decays || []) if (d.to >= 0) next[d.from].push(d.to);
  const seen = new Set(S.init.map(([c]) => c));
  const stack = [...seen];
  while (stack.length) for (const j of next[stack.pop()]) if (!seen.has(j)) { seen.add(j); stack.push(j); }
  return [...seen].sort((a, b) => a - b);
}

function intake60(data, S) {
  const out = { route: S.spec.route, kinetics: S.spec.kinetics, adultAge: S.spec.adultAge };
  const f1 = f1Table(data.models, S.members[0].f1);
  if (f1) out.f1 = { file: `${S.members[0].f1}.GF1`, ages: f1.ages, values: f1.f1 };
  if (S.lungModel) {
    const lung = data.models.lung[S.lungModel];
    out.lung = { name: S.lungModel, title: lung?.title, transfers: lung?.transfers || [] };
    out.deposition = Object.fromEntries(S.init.map(([c, v]) => [S.comps[c].name, v]));
  }
  return out;
}

/* ---- the time series ------------------------------------------------------- */
const LUNG_103 = new Set(['ET1-sur', 'ET2-sur', 'ET2-seq', 'ET2-bnd', 'LN-ET', 'Bronchi', 'Bronchi-q', 'Bronchi-b', 'Brchiole', 'Brchiole-q', 'Brchiole-b', 'ALV', 'LN-Th']);
const GI_103 = new Set(['O-cavity', 'Oesophag-f', 'Oesophag-s', 'St-cont', 'SI-cont', 'RC-cont', 'LC-cont', 'RS-cont']);

function groupOf(sys, c) {
  if (sys === '103') {
    if (c.kind === 'rt' || LUNG_103.has(c.region)) return 'Respiratory tract';
    if (c.kind === 'gi' || GI_103.has(c.region)) return 'Alimentary tract';
    if (c.kind === 'ub' || c.region === 'UB-cont') return 'Urinary bladder';
    return 'Systemic tissues and blood';
  }
  if (LUNG_REGIONS.has(c.region)) return 'Respiratory tract';
  if (c.region === 'UB_Cont') return 'Urinary bladder';
  if (CONTENTS.has(c.region)) return 'Alimentary tract';
  return 'Systemic tissues and blood';
}

/* Where a compartment's activity is drawn in the Model tab, for its boxes
   filled as buckets: the contents of the gut and the bladder by region (the
   drawing makes one box of each, whichever copy of the tract), the other
   compartments by name, as ui.js's nodePlaces() keys a box; the respiratory
   tract, which the tab does not draw, by its regions; and the compartments a
   progeny is given where it is formed in a part of another member's model
   that its own lacks (model103.js, 'shadow'), by the region they are in.
   That is the place's key; its `at` is, for such a progeny, the compartment
   it was formed in (f:NAME): the box of that name where the whole chain's
   dose is drawn; for every other compartment, the key itself. d is a
   compartment, or a dose group's description of one, with `base` its kind
   after the mirrors it follows. */
const AIRWAYS = [[/^ET/, 'Extrathoracic (ET)'], [/^(BB|Bronchi)/, 'Bronchial (BB)'], [/^(bb|Brchiole)/, 'Bronchiolar (bb)'],
  [/^(AI|ALV)$/, 'Alveolar-interstitial (AI)'], [/^LN/, 'Lymph nodes (LN)']];
function placeOf(sys, d, group) {
  const own = (k, label) => ({ key: k, at: k, label });
  if (group === 'Respiratory tract') {
    const label = AIRWAYS.find(([re]) => re.test(d.region))?.[1] || 'Respiratory tract';
    return own(`l:${label}`, label);
  }
  if (d.base === 'shadow') {
    const k = `s:${d.region}`;
    return { key: k, at: d.place ? `f:${key(d.place.name)}` : k, label: `Formed in ${d.region}` };
  }
  if (sys === '103' ? d.kind === 'gi' || d.kind === 'ub' : CONTENTS.has(d.region)) {
    return own(`r:${String(d.region).replace(/_/g, '-').toLowerCase()}`, (sys === '103' && TRACT_NAMES[d.region]) || d.region);
  }
  return own(`n:${key(d.name)}`, d.name);
}
const baseKind = (c, comps) => { let b = c; while (b.kind === 'mirror' && comps[b.of]) b = comps[b.of]; return b.kind; };

function lerp(xs, ys, x) {
  if (!xs || ys.length === 1) return ys[0];
  if (x <= xs[0]) return ys[0];
  if (x >= xs[xs.length - 1]) return ys[ys.length - 1];
  let i = 0;
  while (x > xs[i + 1]) i++;
  return ys[i] + (ys[i + 1] - ys[i]) * (x - xs[i]) / (xs[i + 1] - xs[i]);
}

/*
  What the Retention tab draws, at each output time: the activity of each
  chain member in each body region and source region and in the whole body,
  and its daily excretion, all per Bq of the parent taken in (the activities
  of different nuclides are not added up); and the effective dose received
  up to the time, with the curves it is the sum of -- by body region, source
  region and chain member of the activity it comes from (each dose group's
  share, solve.js), and by tissue that receives it. For the Model tab, each
  member's activity by place (placeOf: by its key), and the effective dose
  received up to each time from its activity and the rate of it there (by
  the place's `at`; placeKey gives the key of each), with the places' names.
*/
function seriesSummary(sys, r) {
  const S = r.system;
  const n = S.comps.length;
  const groups = S.comps.map((c) => groupOf(sys, c));
  const times = r.series.map((p) => p.t);
  const members = S.members.map((m) => m.name);
  const zero = () => times.map(() => 0);
  const byGroup = members.map(() => ({})), byRegion = members.map(() => ({}));
  const byMember = members.map(zero);
  const urine = members.map(zero), faeces = members.map(zero);
  const place = S.comps.map((c, i) => placeOf(sys, { ...c, base: baseKind(c, S.comps) }, groups[i]));
  const places = members.map(() => ({})), placeLabel = {};
  r.series.forEach((p, k) => {
    for (let c = 0; c < n; c++) {
      const q = p.y[c];
      if (!q) continue;
      const m = S.comps[c].member;
      (byGroup[m][groups[c]] ||= zero())[k] += q;
      (byRegion[m][S.comps[c].region] ||= zero())[k] += q;
      (places[m][place[c].key] ||= zero())[k] += q;
      placeLabel[place[c].key] ??= place[c].label;
      byMember[m][k] += q;
    }
    // Excretion rates, Bq per day per Bq taken in.
    const age = r.intakeAge + p.t;
    for (const t of S.transfers) {
      if (t.to >= 0 || !p.y[t.from]) continue;
      const rate = lerp(t.ages && t.rates.length > 1 ? t.ages : null, t.rates, age);
      const m = S.comps[t.from].member;
      if (t.sink === 'Urine') urine[m][k] += rate * p.y[t.from];
      else if (t.sink === 'Faeces' || t.sink === 'Feces') faeces[m][k] += rate * p.y[t.from];
    }
  });
  const E = r.series.map((p) => effectiveAt(sys, r, p.y.subarray(n)));
  // The effective dose by place, received and its rate: a dose group for
  // each compartment (solve.js byCompartment), described by its compartment;
  // each member's places by `at`, with the key each stands for.
  const dosePlaces = members.map(() => ({})), ratePlaces = members.map(() => ({})), placeKey = members.map(() => ({}));
  if (r.doseGroups && r.series[0]?.rates) {
    r.doseGroups.forEach((g, gi) => {
      const c = S.comps[g.comps[0]];
      const d = { kind: g.kind ?? c?.kind, base: g.base ?? g.kind ?? c?.kind, region: g.region, name: g.name ?? c?.name, place: g.place ?? null };
      const pl = placeOf(sys, d, groupOf(sys, d));
      placeKey[g.member][pl.at] ??= pl.key;
      placeLabel[pl.at] ??= pl.label;
      placeLabel[pl.key] ??= pl.label;
      const dy = (dosePlaces[g.member][pl.at] ||= zero()), ry = (ratePlaces[g.member][pl.at] ||= zero());
      r.series.forEach((p, k) => { dy[k] += p.parts[gi]; ry[k] += p.rates[gi]; });
    });
  }
  // Where the effective dose comes from: each dose group's share, added up
  // by what the group is (its compartments share a member and a region).
  const dose = { tissue: tissuesAt(sys, r, n) };
  if (r.doseGroups && r.series[0]?.parts) {
    const by = (keyOf) => {
      const out = {};
      r.doseGroups.forEach((g, gi) => {
        const ys = (out[keyOf(g)] ||= zero());
        r.series.forEach((p, k) => { ys[k] += p.parts[gi]; });
      });
      return out;
    };
    dose.region = by((g) => groupOf(sys, { kind: g.kind, region: g.region }));
    dose.source = by((g) => g.region);
    dose.member = by((g) => members[g.member]);
  }
  // A sex-specific model (radon): the activities are the male model's.
  return { times, members, byGroup, byMember, byRegion, places, placeLabel, dosePlaces, ratePlaces, placeKey, urine, faeces, E, dose, model: r.sexSpecific ? 'male' : null };
}

/* The effective dose up to each time as the weighted tissues' terms and the
   remainder's, which add up to it as effectiveAt does. */
function tissuesAt(sys, r, n) {
  const out = {};
  r.series.forEach((p, k) => {
    for (const [name, v] of Object.entries(effectiveTerms(sys, r, p.y.subarray(n)))) (out[name] ||= new Array(r.series.length).fill(0))[k] = v;
  });
  return out;
}

/* E accumulated to a time, from the integrated target doses that follow the
   compartments in the state vector: the sum of its terms. */
function effectiveAt(sys, r, h) {
  return Object.values(effectiveTerms(sys, r, h)).reduce((a, v) => a + v, 0);
}

/* The terms of E at a time: each weighted tissue's, and the remainder's. In
   the ICRP 60 system the gonads are those the committed doses chose, and so
   is the remainder's rule, so that the terms add up the same way at every time. */
function effectiveTerms(sys, r, h) {
  const out = {};
  if (sys === '103') {
    const targets = Object.keys(r.Ht.M);
    const nT = targets.length;
    const sexes = r.sexesInSeries || ['M', 'F'];
    const Ht = { M: {}, F: {} };
    sexes.forEach((x, k) => targets.forEach((t, i) => { Ht[x][t] = h[k * nT + i]; }));

    const tissue = (name, sex) => {
      const parts = typeof TISSUES_103[name] === 'function' ? TISSUES_103[name](sex) : TISSUES_103[name];
      return parts.reduce((a, [t, w]) => a + w * (Ht[sex][t] || 0), 0);
    };
    for (const [k, w] of Object.entries(W_103)) out[k] = w * (tissue(k, 'M') + tissue(k, 'F')) / 2;
    const rem = (sex) => REMAINDER_103.reduce((a, k) => a + tissue(k, sex), 0) / REMAINDER_103.length;
    out.Remainder = W_REMAINDER_103 * (rem('M') + rem('F')) / 2;
    return out;
  }
  const targets = Object.keys(r.Ht);
  const nT = targets.length;
  const Ht = Object.fromEntries(targets.map((t, i) => [t, h[i]]));
  const H = {};
  for (const [name, parts] of Object.entries(TISSUES_60)) H[name] = parts.reduce((a, [t, w]) => a + w * (Ht[t] || 0), 0);
  H.Gonads = r.gonads ? H[r.gonads] : Math.max(H.Testes, H.Ovaries);
  const remKeys = Object.keys(REMAINDER_60);
  let remainder = h[nT];
  if (r.split) remainder = 0.5 * H[r.split] + 0.5 * h[nT + 1 + remKeys.indexOf(r.split)];
  for (const [k, w] of Object.entries(W_60)) out[k] = w * H[k];
  out.Remainder = 0.05 * remainder;
  return out;
}
