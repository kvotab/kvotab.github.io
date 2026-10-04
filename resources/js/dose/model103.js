/*
  The compartment system of an intake in the ICRP 103 system for members of
  the public (ICRP Publication 158, EIR Part 1, and the EIR Part 2 and Part 3
  drafts):

    respiratory tract   the revised Human Respiratory Tract Model of ICRP 130
                        (ICRP 158 section 2.2): deposition by age and aerosol
                        size (Table A.1), particle transport (Fig. 2.4),
                        dissolution and uptake (Fig. 2.5), bound state
    alimentary tract    the Human Alimentary Tract Model of ICRP 100 (ICRP
                        158 section 2.3, Table 2.10), absorption from the
                        small intestine
    urinary bladder     voided at 40, 32 and 12 d-1 at 3 mo, 1 y and from 5 y
                        (ICRP 158 para 146)
    systemic models     the element files (resources/data/dose/icrp103/
                        elements.json), transcribed from the element sections

  and every member of the decay chain in its own copy of these, linked by
  decay. Progeny follow the rules of ICRP 158 section 2.5:

    - in the respiratory tract every member keeps the parent's absorption
      parameters (shared kinetics), except noble gases, which escape at
      100 d-1 (para 155)
    - activity cleared from the respiratory tract to the alimentary tract is
      absorbed with fA = fr x fA (para 104; for progeny fr of the parent and
      the progeny's reference fA, para 132); progeny produced in the
      alimentary tract after ingestion take their reference fA (para 130),
      and so does activity secreted from systemic compartments into the small
      intestine or above (para 133): the highest of the element's values, or
      the one the ICRP's calculations used where that differs (polonium 0.1,
      the element's fAsecreted). The intake and the secretions therefore pass
      through two copies of the alimentary tract.
    - isotopes of the same element share the parent's model (para 154)
    - in systemic compartments progeny of other elements follow the models
      that the parent element's section of the OIR series gives them
      (Publications 134, 137, 141, 151; progeny103.js and icrp103/progeny.json),
      the same for every chain the parent's element heads: a compartment the
      progeny's model has under the same name (or that the section
      identifies) is the progeny's; the unspecific soft-tissue pools of
      another element's model are not; anywhere else the progeny sits in a
      compartment of its own in that tissue and moves to its blood at the
      section's rate (1000 d-1 from blood, a rate of its own model from soft
      tissue, the bone turnover rate from bone volume, ...)
    - noble gases produced in the body follow the generic model of the OIR
      series: to blood at 100 d-1 from bone surface, 1.5 or 0.36 d-1 from
      exchangeable or other bone volume, with a half-time of 30, 20 or 15 min
      from soft tissue (radon, xenon, krypton); exhaled at 1000 d-1

  For progeny that the parent's section does not name (yttrium from
  zirconium, molybdenum and niobium from technetium) the older rules of this
  page remain: progeny produced in bone volume leave it at the parent's
  rates; in blood they join their own model's blood; elsewhere they go to
  the compartment of their own model with the same name, else the first one
  in the same source region, else into a compartment of their own in that
  region, from which they return to their blood at the rate their own model
  returns its intermediate soft tissue (ST1); elements without a model
  (none in the chains of the catalogue since Part 3) share the kinetics of
  the member they come from.

  OPTIONS103 holds these choices; the tests try alternatives through
  spec.rules. resources/tests/dose_coefficients/README.md records what they
  gave.
*/
import { buildChain } from './chain.js';
import { progenySpec, buildProgenyModel, unidentifiedRule, boneVolumeKind, BONE_TURNOVER, GAS_PROGENY } from './progeny103.js';

export const F_A_MAX = 0.99; // fA of 1 makes the absorption rate infinite

/* HRTM (ICRP 130; ICRP 158 Fig. 2.4, paras 74-80): particle transport, d-1,
   the same at all ages and for all materials. */
export const HRTM = {
  comps: ['ET1', 'ET2', 'ETseq', 'LNET', 'BB', 'BBseq', 'bb', 'bbseq', 'ALV', 'INT', 'LNTH'],
  transport: [
    ['ET1', 'Env', 0.6], ['ET1', 'ET2', 1.5], ['ET2', 'Oes', 100], ['ETseq', 'LNET', 0.001],
    ['BB', 'ET2', 10], ['BBseq', 'LNTH', 0.001], ['bb', 'BB', 0.2], ['bbseq', 'LNTH', 0.001],
    ['ALV', 'bb', 0.002], ['ALV', 'INT', 0.001], ['INT', 'LNTH', 0.00003],
  ],
  // Region of each compartment (for the bound state) and its SAF source region.
  region: { ET1: 'ET1', ET2: 'ET2', ETseq: 'ET2', LNET: 'LNET', BB: 'BB', BBseq: 'BB', bb: 'bb', bbseq: 'bb', ALV: 'AI', INT: 'AI', LNTH: 'LNTH' },
  source: { ET1: 'ET1-sur', ET2: 'ET2-sur', ETseq: 'ET2-seq', LNET: 'LN-ET', BB: 'Bronchi', BBseq: 'Bronchi-q', bb: 'Brchiole', bbseq: 'Brchiole-q', ALV: 'ALV', INT: 'ALV', LNTH: 'LN-Th' },
  boundSource: { ET2: 'ET2-bnd', BB: 'Bronchi-b', bb: 'Brchiole-b', AI: 'ALV', LNET: 'LN-ET', LNTH: 'LN-Th' },
  // 0.2% of what deposits in ET2, BB and bb is retained in the airway wall (para 79).
  seq: 0.002,
  gasEscape: 100, // noble gases formed in the respiratory and alimentary tracts, d-1 (para 155)
};

/* HATM (ICRP 100; ICRP 158 Table 2.10), total diet, d-1, at 3 mo, 1 y, 5,
   10 and 15 y, and adult (male). */
export const HATM = [
  ['O-cavity', 'Oesophag-f', [38880, 6480, 6480, 6480, 6480, 6480]],
  ['O-cavity', 'Oesophag-s', [4320, 720, 720, 720, 720, 720]],
  ['Oesophag-f', 'St-cont', [21600, 12343, 12343, 12343, 12343, 12343]],
  ['Oesophag-s', 'St-cont', [2880, 2160, 2160, 2160, 2160, 2160]],
  ['St-cont', 'SI-cont', [19.2, 20.57, 20.57, 20.57, 20.57, 20.57]],
  ['SI-cont', 'RC-cont', [6, 6, 6, 6, 6, 6]],
  ['RC-cont', 'LC-cont', [3, 2.4, 2.182, 2.182, 2.182, 2]],
  ['LC-cont', 'RS-cont', [3, 2.4, 2.182, 2.182, 2.182, 2]],
  ['RS-cont', 'Faeces', [2, 2, 2, 2, 2, 2]],
];
export const HATM_COMPS = ['O-cavity', 'Oesophag-f', 'Oesophag-s', 'St-cont', 'SI-cont', 'RC-cont', 'LC-cont', 'RS-cont'];
const SI_TO_RC = [6, 6, 6, 6, 6, 6];
/* Urinary bladder (ICRP 158 para 146). */
export const BLADDER = { ages: [100, 365, 1825], rates: [40, 32, 12] };

export const SINKS = new Set(['Urine', 'Faeces', 'Excreta', 'Exhaled', 'Env']);
const NOBLE = new Set(['He', 'Ne', 'Ar', 'Kr', 'Xe', 'Rn']);
/* The rules for progeny where the publications defer to the OIR series
   (see the head of this file); tests try alternatives through spec.rules. */
export const OPTIONS103 = {
  shortLived: 0,          // days: progeny shorter-lived than this decay where produced
  gasEscape: 'oir',       // noble gas produced in soft tissue, to blood: 'oir' = the generic OIR model (half-time
                          // 30 min radon, 20 min xenon, 15 min krypton), a rate in d-1, or 'instant'
  boneShared: 'out',      // progeny produced in bone volume, where no OIR section gives their model:
                          // 'out' = the parent's rates out of bone volume only; 'turnover' = to blood
                          // at the bone turnover rate (the OIR sections' rule);
                          // 'marrow' = the parent's kinetics through bone and marrow until it reaches blood
  toBlood: 'ST1',         // from a compartment the progeny's model does not have to its blood: 'ST1' =
                          // the rate of its own model's intermediate soft tissue (as the ICRP 67/69
                          // progeny models of DCAL do), or a number of d-1
  secretionFA: 'max',     // fA of activity secreted into the alimentary tract: 'max' = the highest
                          // reference value (para 133), or the element's fAsecreted where the
                          // calculations used another (polonium, 0.1: the annex of Publication 158);
                          // 'soluble' = that of soluble non-dietary forms
  sameRegion: 'first',    // progeny produced in a tissue its model has several compartments of
  bloodPools: false,      // red cells and other slow blood pools count as foreign to progeny (no measurable effect)
  sameOther: false,       // progeny produced in another element's ST0-ST2/Other: true = the progeny's pool of the
                          // same name (where the OIR section does not say the structures are the same)
  giProgenyFA: 'own',     // progeny produced in the contents after ingestion: 'own' highest reference
                          // fA (para 130), or 'parent' = the ingested form's fA
};
const GAS_EXHALE = GAS_PROGENY.exhale;
export const elementOf = (nuclide) => nuclide.split('-')[0];
const isBoneVolume = (region) => region === 'T-bone-V' || region === 'C-bone-V';

/** Deposition fractions at an age group for an aerosol size (log-log in size, Table A.1). */
export function deposition103(dep, ageGroup, size, kind = 'AMAD') {
  const k = Math.max(0, Math.min(5, ageGroup));
  const F = dep.fractions[k];
  const sizes = dep.sizes;
  const pick = (i) => Object.fromEntries(['ET1', 'ET2', 'BB', 'bb', 'AI'].map((r) => [r, F[r][i]]));
  const exact = sizes.findIndex((s) => s.kind === kind && Math.abs(s.d - size) < 1e-12);
  if (exact >= 0) return pick(exact);
  // Interpolate between the neighbouring sizes of the whole table (AMTD then AMAD).
  const xs = sizes.map((s) => Math.log(s.d));
  const x = Math.log(size);
  if (x <= xs[0]) return pick(0);
  if (x >= xs[xs.length - 1]) return pick(xs.length - 1);
  let i = 0;
  while (xs[i + 1] < x) i++;
  const w = (x - xs[i]) / (xs[i + 1] - xs[i]);
  const out = {};
  for (const r of ['ET1', 'ET2', 'BB', 'bb', 'AI']) {
    const a = F[r][i], b = F[r][i + 1];
    out[r] = a > 0 && b > 0 ? Math.exp(Math.log(a) + w * (Math.log(b) - Math.log(a))) : a + w * (b - a);
  }
  return out;
}

/** Systemic model of an element: by key, else "default", else the first. */
function modelOf(el, key) {
  const m = el.systemic || {};
  return m[key] || m.default || m[Object.keys(m)[0]];
}

const SI_ABS = (fA) => { const f = Math.min(fA, F_A_MAX); return (f / (1 - f)); };

/** Absorption parameters in the respiratory tract of an inhaled form. */
function absorbFor(E0, form, gas) {
  if (form) return form;
  if (!gas || gas.absorption === 'V') return null;
  const base = typeof gas.absorption === 'object' ? gas.absorption : defaultType(E0, gas.absorption);
  return { ...base, fA: gas.fA ?? base.fA ?? null };
}

/** The rate(s) at which a model returns its intermediate soft tissue (ST1, or
    its only "Other" compartment) to blood: [ages, rates] or null. */
export function st1Return(model) {
  if (!model) return null;
  const comps = model.compartments;
  const blood = new Set(Object.entries(comps).filter(([, r]) => r === 'Blood').map(([n]) => n));
  const others = Object.entries(comps).filter(([, r]) => r === 'Other').map(([n]) => n);
  const back = (name) => {
    const rows = model.transfers.filter(([a, b]) => a === name && blood.has(b));
    if (!rows.length) return null;
    const n = rows[0][2].length;
    const rates = new Array(n).fill(0);
    for (const [, , r] of rows) r.forEach((x, k) => { rates[k] += x; });
    return [model.ages.length === n ? model.ages : [model.ages[model.ages.length - 1]], rates];
  };
  const named = others.find((n) => /^ST ?1$/i.test(n)) || others.find((n) => /^Other ?1$/i.test(n));
  if (named && back(named)) return back(named);
  const withBack = others.map((n) => [n, back(n)]).filter(([, b]) => b);
  if (!withBack.length) return null;
  // Several: the middle one by its adult rate.
  withBack.sort((a, b) => a[1][1].at(-1) - b[1][1].at(-1));
  return withBack[Math.floor((withBack.length - 1) / 2)][1];
}

/** True when the element's model for this intake differs between the sexes (radon). */
export function sexSpecific103(data, spec) {
  const E0 = data.elements[elementOf(spec.nuclide)];
  if (!E0?.systemic?.male || !E0?.systemic?.female) return false;
  const forms = [...(E0.ingestion || []), ...(E0.inhalation?.particulate || []), ...(E0.inhalation?.gases || [])];
  const f = forms.find((x) => x.id === spec.form);
  return !f || !f.systemic || f.systemic === 'male' || f.systemic === 'female';
}

/**
 * @param {object} data  {index (decay), elements: {El: element file}, deposition (Table A.1)}
 * @param {object} spec  {nuclide, route: 'ingestion'|'inhalation'|'injection', form, amad (um), intakeAge (d),
 *                        cutoff, last, sex ('M'|'F', for sex-specific models)}
 */
export function assemble103(data, spec) {
  const { index, elements } = data;
  const notes = [];
  const parentEl = elementOf(spec.nuclide);
  const E0 = elements[parentEl];
  if (!E0) throw new Error(`no ICRP 103 model for ${parentEl}`);
  const chain = buildChain(index, spec.nuclide, { cutoff: spec.cutoff ?? 1e-4, last: spec.last, horizonDays: 36525 });
  const rules = { ...OPTIONS103, ...(spec.rules || {}) };
  const route = spec.route;
  const adultAge = E0.adultAge || 7300;
  const hatmAges = [100, 365, 1825, 3650, 5475, adultAge];
  const turnoverAges = [100, 365, 1825, 3650, 5475, Math.max(adultAge, 9125)];

  // The form of the intake.
  let form = null, gas = null, ingest = null;
  if (route === 'inhalation') {
    form = (E0.inhalation?.particulate || []).find((p) => p.id === spec.form) || null;
    gas = form ? null : (E0.inhalation?.gases || []).find((g) => g.id === spec.form) || null;
    if (!form && !gas) throw new Error(`${parentEl}: no inhaled form "${spec.form}"`);
  } else if (route === 'ingestion') {
    ingest = (E0.ingestion || []).find((f) => f.id === spec.form) || (E0.ingestion || [])[0];
    if (!ingest) throw new Error(`${parentEl}: no ingested form "${spec.form}"`);
  } else if (route !== 'injection') throw new Error(`route ${route}`);
  const absorb = absorbFor(E0, form, gas);
  let parentModelKey = form?.systemic || gas?.systemic || ingest?.systemic || 'default';
  if ((parentModelKey === 'male' || parentModelKey === 'female') && E0.systemic?.male && E0.systemic?.female) {
    parentModelKey = spec.sex === 'F' ? 'female' : 'male';
  }
  if (gas && gas.systemic === null) throw new Error(`${parentEl}: ${gas.label} has no systemic model in the publication`);

  /* --- members ------------------------------------------------------------ */
  const members = chain.members.map((m, j) => {
    const el = elementOf(m.name);
    return { name: m.name, el, lambda: m.lambda, T: m.T, E: m.E, index: j, element: elements[el] || null };
  });
  const parentsOf = members.map(() => []);
  for (const b of chain.branches) parentsOf[b.to].push(b.from);
  members.forEach((m, j) => {
    if (j === 0) { m.kind = 'parent'; m.model = modelOf(E0, parentModelKey); m.modelKey = parentModelKey; return; }
    const i = parentsOf[j][0];
    const p = members[i];
    if (NOBLE.has(m.el)) { m.kind = 'gas'; m.model = null; return; }
    if (m.el === p.el && p.model) { m.kind = 'mirror'; m.of = i; m.model = p.model; return; }
    // The model the parent's element section gives this element (OIR series).
    const pspec = rules.progeny === false ? null : progenySpec(data.progeny, parentEl, m.el);
    if (pspec) {
      m.spec = pspec;
      if (pspec.decayAtSite) { m.kind = 'decay'; m.model = null; return; }
      m.kind = 'spec'; m.modelKey = pspec.set;
      m.model = buildProgenyModel(pspec, m.el, elements, modelOf);
      return;
    }
    if (!m.element || m.T < (spec.shortLived ?? rules.shortLived)) {
      // Decays where produced: the kinetics of the member it comes from.
      if (p.kind === 'gas') { m.kind = 'independent-fallback'; } else { m.kind = 'mirror'; m.of = i; m.model = p.model; return; }
    }
    if (m.element) { m.kind = 'independent'; m.modelKey = 'default'; m.model = modelOf(m.element, 'default'); return; }
    m.kind = 'gas-progeny-fallback'; m.model = null;
  });
  for (const m of members) {
    m.named = new Set();
    if (m.model) for (const r of Object.values(m.model.compartments)) if (!SINKS.has(r) && r !== 'Other') m.named.add(r);
    if (m.kind === 'mirror') m.named = members[m.of].named;
  }
  members.forEach((m) => {
    if (m.kind === 'independent-fallback' || m.kind === 'gas-progeny-fallback') {
      notes.push(`${m.name}: no model for ${m.el} here; produced from a noble gas, it is put in the gas's blood and decays there`);
    } else if (m.kind === 'mirror' && !members[m.index].element) {
      notes.push(`${m.name}: no model for ${m.el} here; it shares the kinetics of ${members[m.of].name}`);
    }
  });

  /* --- compartments ------------------------------------------------------- */
  const comps = [];
  const transfers = [];
  const decays = [];
  const init = [];
  const add = (member, name, region, kind, extra = {}) => {
    comps.push({ member, name, region, kind, ...extra });
    return comps.length - 1;
  };
  const tr = (from, to, ages, rates, origin, sink = null) => transfers.push({ from, to, ages, rates, origin, sink });
  const constant = (r) => [[0], [r]];
  /* Total outflow of a compartment at the adult age, d-1. */
  const outflow = (c) => transfers.reduce((a, t) => a + (t.from === c ? t.rates[t.rates.length - 1] : 0), 0);
  /* A blood compartment other than the entry that exchanges only with blood
     and slowly: red cells, bound plasma. */
  const bloodPool = (c) => {
    const x = comps[c];
    if (x.region !== 'Blood' || st[x.member].entry === c) return false;
    const links = transfers.filter((t) => t.from === c || t.to === c);
    const blood = (k) => k >= 0 && comps[k].region === 'Blood';
    return links.every((t) => blood(t.from) && blood(t.to)) && outflow(c) < 1;
  };

  // Per member: GI tracks, bladder, systemic compartments, shadows, entries.
  const st = members.map(() => ({ gi: { I: null, S: null }, ub: -1, sys: new Map(), shadow: new Map(), entry: -1, entryRT: -1, entrySplit: null, gasBlood: -1, giOverride: [] }));

  /* Systemic model of a member (its own compartments). */
  const systemicOf = (j) => {
    const m = members[j], S = st[j];
    if (S.built) return;
    S.built = true;
    if (m.kind === 'gas') {
      S.gasBlood = add(j, 'Blood', 'Blood', 'sys', { place: { el: m.el, name: 'Blood', member: j } });
      tr(S.gasBlood, -1, ...constant(GAS_EXHALE), 'noble gas exhaled', 'Exhaled');
      S.entry = S.gasBlood;
      return;
    }
    if (m.kind === 'independent-fallback' || m.kind === 'gas-progeny-fallback' || m.kind === 'decay') {
      S.entry = add(j, 'Blood', 'Blood', 'sys', { place: { el: m.el, name: 'Blood', member: j } });
      return;
    }
    if (m.kind === 'mirror') { systemicOf(m.of); return; } // its entries are the mirrored member's
    const model = m.model;
    const content = (r) => r === 'UB-cont' || HATM_COMPS.includes(r);
    for (const [name, region] of Object.entries(model.compartments)) {
      if (SINKS.has(region) || content(region)) continue;
      S.sys.set(name, add(j, name, region, 'sys', { place: { el: m.el, name, member: j } }));
    }
    S.entry = S.sys.get(model.entry);
    if (S.entry === undefined) throw new Error(`${m.name}: entry ${model.entry} is not a systemic compartment`);
    if (model.entryRespiratory) S.entryRT = S.sys.get(model.entryRespiratory) ?? -1;
    if (model.entryRespiratoryByState) {
      S.entryByState = {};
      for (const [state, name] of Object.entries(model.entryRespiratoryByState)) {
        if (!S.sys.has(name)) throw new Error(`${m.name}: respiratory entry ${name} is not a systemic compartment`);
        S.entryByState[state] = S.sys.get(name);
      }
    }
    if (model.entryFractions) S.entrySplit = Object.entries(model.entryFractions).map(([name, f]) => [S.sys.get(name), f]);
    for (const [a, b, rates] of model.transfers) {
      if (!rates.some((x) => x > 0)) continue;
      const ra = model.compartments[a], rb = model.compartments[b];
      const ages = model.ages.length === rates.length ? model.ages : [model.ages[model.ages.length - 1]];
      if (HATM_COMPS.includes(ra)) {
        // A model's own rates out of the alimentary contents (radon: stomach
        // emptying, absorption from the small intestine to the liver) replace
        // the HATM's in both copies of the tract.
        S.giOverride.push({ from: ra, toRegion: HATM_COMPS.includes(rb) ? rb : null, to: HATM_COMPS.includes(rb) ? null : b, ages, rates, origin: `${a} to ${b}` });
        continue;
      }
      const from = S.sys.get(a);
      if (from === undefined) throw new Error(`${m.name}: transfer from ${a}, not a systemic compartment`);
      if (SINKS.has(rb)) tr(from, -1, ages, rates, `${a} to ${b}`, rb);
      else if (rb === 'UB-cont') tr(from, bladderOf(j), ages, rates, `${a} to ${b}`);
      else if (HATM_COMPS.includes(rb)) tr(from, giOf(j, 'S')[rb], ages, rates, `${a} to ${b}`);
      else tr(from, S.sys.get(b), ages, rates, `${a} to ${b}`);
    }
  };

  /* Where activity absorbed to blood goes: [compartment, fraction] pairs.
     'rt' for absorption from the respiratory tract (polonium's Plasma 2), or
     'rt-rapid', 'rt-slow', 'rt-bound' from one state of it, where a model
     sends them to different compartments (mercury vapour: the rapidly
     dissolved vapour to Plasma 0, the rest as Hg2+ to Plasma 1; Part 3 draft
     paras 367-368). */
  const entryTargets = (j, how = 'gen') => {
    const m = members[j];
    systemicOf(j);
    if (m.kind === 'mirror') return entryTargets(m.of, how).map(([c, f]) => [mirrorOf(j, c), f]);
    const S = st[j];
    const rt = how === 'rt' || how.startsWith('rt-');
    if (rt && S.entryByState?.[how.slice(3)] !== undefined) return [[S.entryByState[how.slice(3)], 1]];
    if (rt && S.entryRT >= 0) return [[S.entryRT, 1]];
    if (S.entrySplit) return S.entrySplit;
    return [[S.entry, 1]];
  };
  const toEntry = (j, from, ages, rates, origin, how = 'gen') => {
    for (const [c, f] of entryTargets(j, how)) tr(from, c, ages, f === 1 ? rates : rates.map((r) => r * f), origin);
  };
  const entryOf = (j) => entryTargets(j)[0][0];

  /* Mirror of a member's compartment for a member that shares its kinetics. */
  const mirrorOf = (j, c) => {
    const key = `m${c}`;
    const S = st[j];
    if (S.shadow.has(key)) return S.shadow.get(key);
    const src = comps[c];
    const k = add(j, src.name, src.region, 'mirror', { of: c, otherOf: src.otherOf ?? src.member, place: src.place });
    S.shadow.set(key, k);
    // The source compartment's outflows, sinks and decays aside.
    for (const t of transfers.filter((x) => x.from === c)) {
      if (t.to < 0) tr(k, -1, t.ages, t.rates, t.origin, t.sink);
      else tr(k, placeLike(j, t.to), t.ages, t.rates, t.origin);
    }
    return k;
  };

  /* Where member j's activity is that is at the place of compartment c (of
     the member j comes from): for births by decay, and for the destinations of
     compartments that keep a parent's rates. */
  const placeLike = (j, c, opts = {}) => {
    const m = members[j];
    const src = comps[c];
    if (src.kind === 'rt') {
      const set = rtOf(j);
      if (set[src.rtKey] === undefined) st[j].boundOf(src.rtRegion);
      return set[src.rtKey];
    }
    if (src.kind === 'gi') return giOf(j, src.track)[src.name];
    if (src.kind === 'ub') return bladderOf(j);
    systemicOf(j);
    if (m.kind === 'mirror') return mirrorOf(j, c);
    const S = st[j];
    if (m.kind === 'gas') {
      if (src.region === 'Blood') return S.gasBlood;
      const key = `g${c}`;
      if (S.shadow.has(key)) return S.shadow.get(key);
      const k = add(j, `${src.name} (${members[src.member].name})`, src.region, 'shadow', { otherOf: src.otherOf ?? src.member, place: src.place });
      S.shadow.set(key, k);
      const surface = src.region === 'T-bone-S' || src.region === 'C-bone-S';
      if (!isBoneVolume(src.region) && !surface && rules.gasEscape === 'instant') {
        tr(k, -1, ...constant(1e7), 'noble gas leaves at once', 'Exhaled');
        return k;
      }
      const G = GAS_PROGENY;
      const kind = isBoneVolume(src.region) ? boneVolumeKind(src.place?.name ?? src.name) : null;
      const rate = kind ? G[kind] : surface ? G.surface
        : rules.gasEscape === 'oir' ? (G[m.el] || G.Rn).soft : rules.gasEscape;
      tr(k, S.gasBlood, ...constant(rate), 'noble gas to blood');
      return k;
    }
    if (m.kind === 'decay') {
      // Decays where it is produced.
      if (src.region === 'Blood' && comps[c].kind === 'sys' && entryOf(src.member) === c) return S.entry;
      const key = `d${c}`;
      if (S.shadow.has(key)) return S.shadow.get(key);
      const k = add(j, `${src.name} (${members[src.member].name})`, src.region, 'shadow', { otherOf: src.otherOf ?? src.member, place: src.place });
      S.shadow.set(key, k);
      return k;
    }
    if (m.kind === 'spec') return placeSpec(j, c);
    if (m.kind === 'independent-fallback' || m.kind === 'gas-progeny-fallback') return S.entry;
    // Independent kinetics.
    if (isBoneVolume(src.region) || (opts.inBone && rules.boneShared === 'marrow' && /bone|marrow/i.test(src.region) && src.region !== 'Blood')) {
      const key = `b${c}`;
      if (S.shadow.has(key)) return S.shadow.get(key);
      const k = add(j, `${src.name} (${members[src.member].name})`, src.region, 'shadow', { otherOf: src.otherOf ?? src.member, place: src.place });
      S.shadow.set(key, k);
      if (rules.boneShared === 'turnover' && isBoneVolume(src.region)) {
        tr(k, S.entry, turnoverAges, BONE_TURNOVER[src.region], 'to blood at the bone turnover rate');
        return k;
      }
      for (const t of transfers.filter((x) => x.from === c)) {
        if (t.to < 0) tr(k, -1, t.ages, t.rates, t.origin, t.sink);
        else tr(k, placeLike(j, t.to, { inBone: true }), t.ages, t.rates, `${t.origin} (with ${members[src.member].name})`);
      }
      return k;
    }
    // The parent's circulating blood is the progeny's; a pool that only
    // exchanges slowly with it (red cells, bound plasma) is not.
    if (S.sys.has(src.name)) return S.sys.get(src.name);
    if (src.region === 'Blood' && (rules.bloodPools === false || !bloodPool(c))) return S.entry;
    // A compartment of the same tissue: the first the progeny's model lists
    // ('first'), or the one whose residence is closest ('closest').
    if (src.region !== 'Other' && src.region !== 'Blood') {
      let best = -1, dist = Infinity;
      const r0 = outflow(c);
      for (const [, k] of S.sys) {
        if (comps[k].region !== src.region) continue;
        if (rules.sameRegion !== 'closest') { best = k; break; }
        const d = Math.abs(Math.log((outflow(k) || 1e-12) / (r0 || 1e-12)));
        if (d < dist) { dist = d; best = k; }
      }
      if (best >= 0) return best;
    }
    const key = `o${c}`;
    if (S.shadow.has(key)) return S.shadow.get(key);
    const k = add(j, `${src.name} (${members[src.member].name})`, src.region, 'shadow', { otherOf: src.otherOf ?? src.member, place: src.place });
    S.shadow.set(key, k);
    const fixed = typeof rules.toBlood === 'number' ? rules.toBlood : null;
    const st1 = fixed == null ? st1Return(m.model) : null;
    if (st1) tr(k, S.entry, st1[0], st1[1], `to blood at the rate of ${m.el}'s intermediate soft tissue`);
    else tr(k, S.entry, ...constant(fixed ?? 1000), 'to blood');
    return k;
  };

  /* Where progeny j, whose model its chain's parent element section gives,
     is when produced at the place of compartment c: the compartment of its
     model identified with that place, or a compartment of its own there from
     which it moves to its blood as the section says. */
  const placeSpec = (j, c) => {
    const m = members[j], S = st[j], spec = m.spec, src = comps[c];
    const place = src.place || { el: members[src.member].el, name: src.name };
    const keyed = spec.identify?.[`${place.el}:${place.name}`];
    const id = keyed !== undefined ? keyed : spec.identify?.[place.name];
    if (id) {
      const k = S.sys.get(id);
      if (k === undefined) throw new Error(`${m.name}: identified compartment ${id} is not in its model`);
      return k;
    }
    // A compartment of the same name is the same, except the unspecific soft
    // tissue pools (ST0-ST2, Other) of another element's model, unless the
    // section says the structures are the same (sameOther), or, with
    // sameOther 'progeny', when that model is a progeny's rather than the
    // chain parent's: the radium set's thorium and radium, as the ICRP's own
    // coefficients have them (227Ra and 228Ra in the annex, 231Pa and 228Ac
    // in the Part 2 draft; 229Th and 232Th, whose radium forms in the
    // parent's pools, keep them apart).
    const same = spec.sameName ?? true;
    const sameOther = spec.sameOther === 'progeny' ? (place.member ?? src.member) !== 0 : (spec.sameOther ?? rules.sameOther);
    const pooled = src.region === 'Other' && place.el !== m.el && !sameOther;
    if (id === undefined && !(pooled && same === true) && (same === true || (Array.isArray(same) && same.includes(place.name))) && S.sys.has(place.name)) {
      return S.sys.get(place.name);
    }
    const key = `u${c}`;
    if (S.shadow.has(key)) return S.shadow.get(key);
    let rule = unidentifiedRule(spec, src.region, place.name, place.el);
    if (rule === 'nonexch') {
      // Bone volume not divided as X's model divides it: its non-exchangeable part.
      const cands = [...S.sys].filter(([, k]) => comps[k].region === src.region);
      const hit = cands.find(([n]) => boneVolumeKind(n) === 'nonexch') || cands.find(([n]) => boneVolumeKind(n) === 'volume');
      if (hit) return hit[1];
      rule = 'turnover';
    }
    const k = add(j, `${src.name} (${members[src.member].name})`, src.region, 'shadow', { otherOf: src.otherOf ?? src.member, place });
    S.shadow.set(key, k);
    if (rule === 'decay') return k;
    if (typeof rule === 'object' && rule.exhale) {
      tr(k, -1, ...constant(rule.exhale), 'exhaled', 'Exhaled');
      return k;
    }
    if (rule === 'turnover') {
      const R = BONE_TURNOVER[src.region] || BONE_TURNOVER[src.region.replace(/-S$/, '-V')];
      if (!R) throw new Error(`${m.name}: bone turnover rule for ${src.region}`);
      tr(k, S.entry, turnoverAges, R, 'to blood at the bone turnover rate');
    } else if (typeof rule === 'object' && rule.like) {
      const t = m.model.transfers.find(([a, b]) => a === rule.like && b === m.model.entry);
      if (!t) throw new Error(`${m.name}: no transfer from ${rule.like} to ${m.model.entry}`);
      const ages = m.model.ages.length === t[2].length ? m.model.ages : [m.model.ages[m.model.ages.length - 1]];
      tr(k, S.entry, ages, t[2].map((x) => x * (rule.factor ?? 1)), `to blood at the rate of ${rule.like}`);
    } else tr(k, S.entry, ...constant(rule), 'to blood (not in its model)');
    return k;
  };

  /* Urinary bladder contents of a member. */
  const bladderOf = (j) => {
    if (st[j].ub >= 0) return st[j].ub;
    const k = add(j, 'UB-cont', 'UB-cont', 'ub');
    st[j].ub = k;
    tr(k, -1, BLADDER.ages, BLADDER.rates, 'bladder voiding', 'Urine');
    return k;
  };

  /* A copy of the alimentary tract: 'I' for the intake, 'S' for secretions. */
  const giOf = (j, track) => {
    const m = members[j];
    if (st[j].gi[track]) return st[j].gi[track];
    const g = {};
    for (const c of HATM_COMPS) g[c] = add(j, c, c, 'gi', { track });
    st[j].gi[track] = g;
    if (m.kind === 'gas') {
      for (const c of HATM_COMPS) tr(g[c], -1, ...constant(HRTM.gasEscape), 'noble gas escapes', 'Exhaled');
      return g;
    }
    systemicOf(j);
    const over = (m.kind === 'mirror' ? st[m.of] : st[j]).giOverride;
    for (const [a, b, rates] of HATM) {
      const o = over.find((x) => x.from === a && x.toRegion === b);
      if (o) { tr(g[a], g[b], o.ages, o.rates, o.origin); continue; }
      if (b === 'Faeces') tr(g[a], -1, hatmAges, rates, `${a} to faeces`, 'Faeces');
      else tr(g[a], g[b], hatmAges, rates, `${a} to ${b}`);
    }
    // Absorption from the small intestine: the model's own path if it has one,
    // else fA (ICRP 158 Table 2.10 note).
    const own = over.filter((x) => x.from === 'SI-cont' && x.to);
    if (own.length) {
      for (const o of own) {
        const to = m.kind === 'mirror' ? mirrorOf(j, st[m.of].sys.get(o.to)) : st[j].sys.get(o.to);
        tr(g['SI-cont'], to, o.ages, o.rates, o.origin);
      }
      return g;
    }
    const fA = fAfor(j, track);
    if (fA.some((x) => x > 0)) {
      toEntry(j, g['SI-cont'], hatmAges, fA.map((f, k) => SI_ABS(f) * SI_TO_RC[k]), `SI absorption (fA ${fA.map((x) => +x.toPrecision(3)).join(', ')})`);
    }
    return g;
  };

  /* fA of a member in a track (ICRP 158 paras 104, 130-133, 154). */
  const fAfor = (j, track) => {
    const m = members[j];
    // The reference fA of a progeny element (paras 130-133): its highest, or
    // the value the calculations used for polonium (fAsecreted).
    // A single value is the adult's reference fA; the 3-month-old's follows the
    // rule of Publication 158 para 129 (x10 up to 0.001, x2 up to 0.5, else 1).
    const infantFA = (a) => (a <= 0.001 ? 10 * a : a <= 0.5 ? Math.min(1, 2 * a) : 1);
    const specFA = m.spec?.fA != null && !m.element
      ? (Array.isArray(m.spec.fA) ? m.spec.fA : [infantFA(m.spec.fA), ...new Array(5).fill(m.spec.fA)]) : null;
    const el = m.element || members[m.of ?? 0].element;
    const own = specFA || (rules.secretionFA === 'max' && el?.fAsecreted) || el?.fAmax || [0, 0, 0, 0, 0, 0];
    if (track === 'S') {
      if (!specFA && rules.secretionFA === 'soluble') return el?.fAinhaled || own;
      return own;
    }
    if (route === 'ingestion') return j === 0 || rules.giProgenyFA === 'parent' ? ingest.fA : own;
    // Inhaled material cleared to the alimentary tract.
    const fr = frOf(absorb);
    if (j === 0) {
      const base = (E0.fAinhaled || E0.fAmax).map((x) => fr * x);
      if (Array.isArray(absorb?.fA)) return absorb.fA;
      // A single printed value is the adult's; the children keep fr x fA.
      if (typeof absorb?.fA === 'number') return base.map((x, k) => (k === 5 ? absorb.fA : x));
      return base;
    }
    // Progeny of an inhaled gas or vapour: their own fA. The parent's fr
    // stands for a particle matrix (Publication 130 paras 125, 130), which a
    // vapour has not; the annex's 94Ru and 95Ru as RuO4 (fr 0.5) agree only so.
    // (Radon at home gives its aerosols as gas forms marked particles.)
    if (gas && !gas.particles) return own;
    return own.map((x) => fr * x);
  };

  /* Respiratory tract of a member: transport compartments in two states, bound compartments. */
  const rtOf = (j) => {
    const S = st[j];
    if (S.rtSet) return S.rtSet;
    const m = members[j];
    const set = {};
    S.rtSet = set;
    const states = absorb?.sp != null ? ['p', 't'] : ['r', 's'];
    for (const c of HRTM.comps) for (const s of states) {
      set[`${c}/${s}`] = add(j, `${c}/${s}`, HRTM.source[c], 'rt', { rtKey: `${c}/${s}`, rtRegion: HRTM.region[c] });
    }
    const bound = {};
    if (m.kind === 'gas') {
      for (const k of Object.values(set)) tr(k, -1, ...constant(HRTM.gasEscape), 'noble gas escapes', 'Exhaled');
      S.boundOf = (region) => {
        if (bound[region] !== undefined) return bound[region];
        const k = add(j, `${region} bound`, HRTM.boundSource[region], 'rt', { rtKey: `${region}-bound`, rtRegion: region });
        set[`${region}-bound`] = bound[region] = k;
        tr(k, -1, ...constant(HRTM.gasEscape), 'noble gas escapes', 'Exhaled');
        return k;
      };
      return set;
    }
    for (const [a, b, r] of HRTM.transport) for (const s of states) {
      if (b === 'Env') tr(set[`${a}/${s}`], -1, ...constant(r), `${a} to environment`, 'Env');
      else if (b === 'Oes') tr(set[`${a}/${s}`], giOf(j, 'I')['Oesophag-s'], ...constant(r), `${a} to oesophagus`);
      else tr(set[`${a}/${s}`], set[`${b}/${s}`], ...constant(r), `${a} to ${b}`);
    }
    // Dissolution and uptake (none from ET1, para 82).
    const fb = absorb?.fb || 0, sb = absorb?.sb || 0;
    const boundIn = new Set(absorb?.boundIn || ['AI']);
    S.boundOf = (region) => {
      if (bound[region] !== undefined) return bound[region];
      const k = add(j, `${region} bound`, HRTM.boundSource[region], 'rt', { rtKey: `${region}-bound`, rtRegion: region });
      set[`${region}-bound`] = bound[region] = k;
      if (sb > 0) toEntry(j, k, ...constant(sb), 'bound to blood', 'rt-bound');
      return k;
    };
    const dissolve = absorb?.sp != null
      ? { p: absorb.sp, t: absorb.st }
      : { r: absorb?.sr ?? 0, s: absorb?.ss ?? 0 };
    for (const c of HRTM.comps) {
      if (c === 'ET1') continue;
      const region = HRTM.region[c];
      const f = fb > 0 && boundIn.has(region) ? fb : 0;
      for (const s of states) {
        const rate = dissolve[s] || 0;
        if (!rate) continue;
        if (f < 1) toEntry(j, set[`${c}/${s}`], ...constant(rate * (1 - f)), `dissolution (${s})`, s === 'r' ? 'rt-rapid' : s === 's' ? 'rt-slow' : 'rt');
        if (f > 0) tr(set[`${c}/${s}`], S.boundOf(region), ...constant(rate * f), `dissolution to bound (${s})`);
      }
      if (absorb?.sp != null && absorb.spt) tr(set[`${c}/p`], set[`${c}/t`], ...constant(absorb.spt), 'transformation');
    }
    return set;
  };

  /* --- the intake ---------------------------------------------------------- */
  // Reference age group of the intake age: 3 mo, 1, 5, 10, 15 y, adult.
  const ag = [100, 365, 1825, 3650, 5475].findIndex((a) => spec.intakeAge <= a + 1);
  const group = ag < 0 ? 5 : ag;
  if (route === 'ingestion') {
    init.push([giOf(0, 'I')['O-cavity'], 1]);
  } else if (route === 'injection') {
    // Direct uptake to blood (the annex of Publication 158 gives these too).
    for (const [c, f] of entryTargets(0, 'rt')) init.push([c, f]);
  } else if (gas && gas.absorption === 'V') {
    systemicOf(0);
    if (gas.entry) init.push([st[0].sys.get(gas.entry), gas.deposition.total]);
    else for (const [c, f] of entryTargets(0)) init.push([c, gas.deposition.total * f]);
  } else {
    const dep = gas ? gas.deposition : deposition103(data.deposition, group, spec.amad ?? 1, spec.sizeKind || 'AMAD');
    const rt = rtOf(0);
    const s0 = absorb?.sp != null ? ['p', 1] : ['r', absorb.fr];
    const s1 = absorb?.sp != null ? null : ['s', 1 - absorb.fr];
    const put = (c, amount) => {
      if (!(amount > 0)) return;
      init.push([rt[`${c}/${s0[0]}`], amount * s0[1]]);
      if (s1 && s1[1] > 0) init.push([rt[`${c}/${s1[0]}`], amount * s1[1]]);
    };
    put('ET1', dep.ET1);
    put('ET2', dep.ET2 * (1 - HRTM.seq)); put('ETseq', dep.ET2 * HRTM.seq);
    put('BB', dep.BB * (1 - HRTM.seq)); put('BBseq', dep.BB * HRTM.seq);
    put('bb', dep.bb * (1 - HRTM.seq)); put('bbseq', dep.bb * HRTM.seq);
    put('ALV', dep.AI);
  }

  /* --- decay links: every compartment of a member feeds its progeny -------- */
  // Walk members in chain order; compartments added while linking are linked too.
  for (let j = 0; j < members.length; j++) {
    const kids = chain.branches.filter((b) => b.from === j);
    if (!kids.length) continue;
    for (let c = 0; c < comps.length; c++) {
      if (comps[c].member !== j) continue;
      for (const b of kids) decays.push({ from: c, to: placeLike(b.to, c), b: b.b });
    }
  }
  if (decays.some((d) => d.to === undefined || d.to < 0)) throw new Error('a decay without a destination compartment');

  // Descriptions for the page.
  const memberInfo = members.map((m) => ({
    name: m.name, el: m.el, lambda: m.lambda, T: m.T, kind: m.kind, of: m.of ?? null,
    model: m.model ? (m.model.label || m.modelKey || 'default') : null, modelKey: m.modelKey ?? null, named: [...m.named],
    progeny: m.spec ? { set: m.spec.set, model: m.kind === 'spec' ? m.model : null } : null,
  }));
  const intake = {
    route, form: form || gas || ingest, absorb,
    fA: { intake: route === 'injection' ? null : fAfor(0, 'I'), secretions: fAfor(0, 'S') },
    deposition: route === 'inhalation' && !(gas && gas.absorption === 'V')
      ? (gas ? gas.deposition : deposition103(data.deposition, group, spec.amad ?? 1, spec.sizeKind || 'AMAD')) : null,
    ages: hatmAges,
  };
  return {
    system: '103', spec: { ...spec, adultAge }, chain, members: memberInfo, comps, transfers, decays, init, notes,
    form: form || gas || ingest, absorb, ageGroup: group, entryOf, intake,
  };
}

function frOf(absorb) {
  if (!absorb) return 1;
  if (absorb.sp != null) return absorb.sp / (absorb.sp + absorb.spt);
  return absorb.fr ?? 1;
}

/* The default Type F, M or S parameters (Table 2.6) with the element's
   rapid dissolution rate where Table 2.5 gives one (its Type F entry). */
function defaultType(el, type) {
  const f = (el.inhalation?.particulate || []).find((p) => p.id === type);
  if (f) return f;
  const sr = (el.inhalation?.particulate || []).find((p) => p.id === 'F')?.sr ?? 30;
  if (type === 'F') return { fr: 1, sr, ss: null, fb: 0 };
  if (type === 'M') return { fr: 0.2, sr: Math.min(3, sr), ss: 0.005, fb: 0 };
  return { fr: 0.01, sr: Math.min(3, sr), ss: 1e-4, fb: 0 };
}
