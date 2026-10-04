/*
  The compartment system of one intake in the ICRP 60 system: the ICRP 66
  respiratory tract model, the ICRP 30 gastrointestinal tract, the ICRP 67
  bladder, and the element-specific systemic models of ICRP Publications
  56-72, for the parent and each member of its decay chain -- assembled the
  way DCAL's ACTACAL assembles them (ORNL/TM-2001/190, chapters 3, 7 and 9).

  What comes out is plain data the solver reads:

    members    the chain, with decay constants
    comps      one entry per (member, compartment): its name and the source
               region its activity counts toward
    transfers  first-order transfers between compartments of one member, or
               out of the body (to: -1), each with a rate table over age
    decays     ingrowth: compartment of a member -> the same compartment of a
               daughter, with the branching fraction
    init       the activity deposited at the time of intake

  Rates are per day and ages in days, as in DCAL's files. A rate table holds
  the rates at the model's reference ages; between them the rate is
  interpolated linearly in age and beyond them held at the end values
  (ORNL/TM-2001/190, 7.1).
*/
import { buildChain } from './chain.js';
import { regionOf, key, isSink, LUNG_REGIONS, CONTENTS } from './regions.js';

const NOBLE_GASES = new Set(['He', 'Ne', 'Ar', 'Kr', 'Xe', 'Rn']);

const GI = ['St_Cont', 'SI_Cont', 'ULI_Cont', 'LLI_Cont'];
const SI_TRANSIT = 6; // d^-1, SI contents -> ULI contents in the ICRP 30 model

const elementOf = (nuclide) => /^([A-Z][a-z]?)-/.exec(nuclide)[1];

/* DCAL's names for chain members' own models: the member's symbol, then the
   parent's; a one-letter member symbol takes a hyphen (I-TE, U-TH). */
function memberModelName(memberEl, parentEl) {
  const m = memberEl.toUpperCase(), p = parentEl.toUpperCase();
  return (m.length === 1 ? `${m}-` : m) + p;
}

const ROUTE_CODE = { ingestion: 'g', inhalation: 'h', injection: 'j' };

/**
 * Which systemic model file the parent uses (ORNL/TM-2001/190, 3.6 and the
 * notes of $BIODEF.DAT): a nuclide assignment, then an assignment by route of
 * intake, then the form the caller chose among the element's prompts, then
 * the short-lived/long-lived pair (_SUR, _VOL) split at 15 days, then the
 * element's own file.
 */
export function parentModelName(models, index, nuclide, route, chosen) {
  const el = elementOf(nuclide);
  const r = ROUTE_CODE[route];
  if (chosen) return key(chosen);
  const byNuc = (models.biodef.nuclide[el] || []).find((a) => a.nuclide === nuclide && (a.route === 'a' || a.route === r));
  if (byNuc) return byNuc.file;
  const byRoute = (models.biodef.intake[el] || []).find((a) => a.route === 'a' || a.route === r);
  if (byRoute) return byRoute.file;
  const prompts = (models.biodef.prompts[el] || []).filter((a) => a.route === 'a' || a.route === r);
  if (prompts.length) return prompts[0].file;
  const E = el.toUpperCase();
  if (models.systemic[`${E}_SUR`] && models.systemic[`${E}_VOL`]) return index[nuclide].T <= 15 ? `${E}_SUR` : `${E}_VOL`;
  if (models.systemic[E]) return E;
  throw new Error(`no systemic model for ${nuclide}`);
}

/** Which f1 file: the caller's, then $F1DEF.DAT's for the model, then the inhaled type's, then the element's. */
export function f1FileName(models, el, route, bioName, type, chosen) {
  if (chosen) return key(chosen);
  const r = ROUTE_CODE[route];
  const a = models.f1def.biokinetic.find((x) => x.file === bioName && (x.route === 'a' || x.route === r));
  if (a) return a.f1;
  const E = el.toUpperCase();
  if (route === 'inhalation' && type && models.f1[`${E}$${type}`]) return `${E}$${type}`;
  if (models.f1[E]) return E;
  return null;
}

/* The f1 value is applied as a transfer coefficient from SI contents to blood,
   lambda_B = f1 lambda_SI / (1 - f1), and it is that coefficient that is
   interpolated in age (ORNL/TM-2001/190, 7.3). An f1 of 1 has no finite
   coefficient; DCAL takes it as 0.99, which leaves 1 % of the activity to pass
   on to the large intestine -- and the ICRP 72 colon doses of the nuclides
   with f1 = 1 (iodine, caesium, organic carbon) are those of 0.99, twice those
   of complete absorption for 131I. */
export const F1_MAX = 0.99;
function siToBlood(f1) {
  const f = Math.min(f1, F1_MAX);
  return (f * SI_TRANSIT) / (1 - f);
}

export function f1Table(models, name) {
  const f = models.f1[name];
  if (!f) return null;
  return { ages: f.ages.slice(), rates: f.f1.map(siToBlood), f1: f.f1.slice(), title: f.title };
}

/* Lead isotopes of the natural decay series: the chains ICRP 67 gave
   independent kinetics. */
const PB_NATURAL = new Set(['Pb-210', 'Pb-211', 'Pb-212', 'Pb-214']);

/**
 * The ICRP 72 recipe for an intake: DCAL's batch case for it (its FGR-13
 * runs: chain length, kinetics of the progeny, special model and f1 files,
 * adult age), with the two places where ICRP 72 itself did otherwise.
 *
 *   - Lead isotopes outside the natural series take shared kinetics. DCAL's
 *     batch file runs every lead isotope with independent kinetics; ICRP 72's
 *     coefficients for 195mPb ... 209Pb are those of shared kinetics (198Pb:
 *     0.79-0.87 of them independently, 1.00-1.06 shared), those of
 *     210Pb ... 214Pb those of independent kinetics.
 *   - Actinium and protactinium take ICRP 30's models with shared kinetics
 *     (assemble60 does this when it meets the _I30 models).
 *
 * @param {object} cases   cases.json
 * @param {string} route   'ingestion' | 'inhalation'
 * @param {object} pick    {nuclide, bio?, f1file?, type?, lung?}
 */
export function recipe60(cases, route, pick) {
  const list = cases[route] || [];
  const nuc = pick.nuclide;
  const match = list.filter((c) => c.nuclide === nuc
    && (pick.bio == null || (c.bio || null) === (pick.bio ? key(pick.bio) : null))
    && (pick.f1file === undefined || (c.f1 || null) === (pick.f1file ? key(pick.f1file) : null))
    && (route !== 'inhalation' || pick.type == null || c.type === pick.type)
    && (route !== 'inhalation' || pick.lung === undefined || (c.lung || null) === (pick.lung ? key(pick.lung) : null)));
  const c = match[0] || null;
  const spec = {
    nuclide: nuc, route,
    bio: pick.bio ?? c?.bio ?? null, f1file: pick.f1file ?? c?.f1 ?? null,
    kinetics: c?.kinetics || 'S', last: c?.last || null,
    adultAge: c?.adultAge || 7300, type: pick.type ?? c?.type ?? null,
    lung: pick.lung ?? c?.lung ?? null, amad: pick.amad ?? c?.amad ?? 1,
  };
  if (/^Pb-/.test(nuc) && !PB_NATURAL.has(nuc)) spec.kinetics = 'S';
  return spec;
}

/**
 * @param {{index, models}} data
 * @param {object} spec  { nuclide, route, type, lung, amad, bio, f1file, kinetics, last, intakeAge, adultAge }
 */
export function assemble60(data, spec) {
  const { index, models } = data;
  const route = spec.route;
  const chain = buildChain(index, spec.nuclide, { last: spec.last || null });
  const parentEl = elementOf(spec.nuclide);
  const notes = [];

  let parentBio = parentModelName(models, index, spec.nuclide, route, spec.bio);
  if (spec.icrp72 !== false && !spec.bio && models.systemic[`${parentBio}_I30`]) parentBio = `${parentBio}_I30`;
  if (!models.systemic[parentBio]) throw new Error(`no systemic model file ${parentBio}.DEF`);
  const lungName = route === 'inhalation' ? (spec.lung ? key(spec.lung) : `ICRP66${spec.type}`) : null;
  const lung = lungName ? models.lung[lungName] : null;
  if (route === 'inhalation' && !lung) throw new Error(`no respiratory tract model ${lungName}`);
  const inhaledType = lung && /^ICRP66[FMS]$/.test(lungName) ? spec.type : null;
  const parentF1 = f1FileName(models, parentEl, route, parentBio, inhaledType, spec.f1file);
  // ICRP 72's actinium and protactinium are ICRP 30's, with ICRP 30's shared
  // kinetics for their progeny; DCAL's batch files run them independently
  // with FGR 13's updated models.
  const kinetics = spec.kinetics === 'I' && !(spec.icrp72 !== false && /_I30$/.test(parentBio)) ? 'I' : 'S';

  /* ICRP 72 took the actinium and protactinium models from ICRP 30 (see
     gen-dose-icrp60.mjs); DCAL's FGR-13 library has updated ones. */
  const override = spec.icrp72 !== false ? { AC: 'AC_I30', PA: 'PA_I30' } : {};
  /* Each member's systemic model and f1. */
  const memberModels = chain.members.map((m, j) => {
    const el = elementOf(m.name);
    if (j === 0) return { bio: parentBio, f1: parentF1, own: true };
    if (kinetics === 'I') {
      const name = memberModelName(el, parentEl);
      if (models.systemic[name]) {
        const f1 = f1FileName(models, el, route, name, inhaledType, null);
        return { bio: name, f1: f1 || parentF1, own: true };
      }
      notes.push(`${m.name}: no model ${name}.DEF for it as a member of the ${parentEl} chain; it takes the parent's model`);
    }
    return { bio: parentBio, f1: parentF1, own: false };
  });

  /* Compartments: a list per member, created on first use. */
  const comps = [];
  const compIndex = chain.members.map(() => new Map());
  const comp = (j, name, create = true) => {
    const k = key(name);
    let i = compIndex[j].get(k);
    if (i === undefined && create) {
      const region = regionOf(name);
      if (!region) throw new Error(`compartment "${name}" of ${chain.members[j].name} is no source region`);
      i = comps.length;
      comps.push({ member: j, name, region });
      compIndex[j].set(k, i);
    }
    return i;
  };

  const transfers = [];
  const addTransfer = (j, from, to, ages, rates, origin) => {
    const f = comp(j, from);
    const t = isSink(to) ? -1 : comp(j, to);
    transfers.push({ from: f, to: t, ages, rates, origin, sink: t < 0 ? regionOf(to) : null });
  };

  /* Noble gases born in the body under shared kinetics: the exceptions of
     ICRP 30 that DCAL's ACTACAL applies (ORNL/TM-2001/190, 9.1 and 9.3.2).
     A gas that "decays at the site of production" keeps the compartments it
     is born in and moves nowhere; one that "escapes" leaves before decaying,
     which is the same as never being formed in the body. */
  const gasRule = chain.members.map((m, j) => (j > 0 && kinetics === 'S' ? nobleGasRule(m.name, chain.members[0].name, m.T) : null));

  const git = models.git;
  const bladder = models.bladder;
  const giKeys = new Set(GI.map(key));
  chain.members.forEach((m, j) => {
    const mm = memberModels[j];
    const sys = models.systemic[mm.bio];
    if (gasRule[j]) return; // no biological transfers: it stays where it is born, or is never born
    // Respiratory tract: the parent's model for every member (ICRP 71: the
    // absorption parameters of the parent apply to the whole chain), except
    // noble gases, which leave it: radon at 100 d-1, xenon (from iodine)
    // before it decays (ORNL/TM-2001/190, 9.1).
    if (lung) {
      const el = elementOf(m.name);
      if (j > 0 && NOBLE_GASES.has(el)) {
        const rate = el === 'Rn' ? 100 : 1e5;
        for (const name of lung.compartments) {
          if (giKeys.has(key(name)) || isSink(name) || key(name) === 'BLOOD') continue;
          addTransfer(j, name, 'Excreta', null, [rate], 'noble gas leaves the respiratory tract');
        }
      } else {
        for (const [from, to, rate] of lung.transfers) {
          if (giKeys.has(key(from))) continue; // the GI tract comes from ICRP30.GIT
          addTransfer(j, from, to, null, [rate], 'lung');
        }
      }
    }
    // GI tract.
    for (const [from, to, rates] of git.transfers) addTransfer(j, from, to, git.ages, rates, 'gi');
    const f1 = f1Table(models, mm.f1);
    if (f1) addTransfer(j, 'SI_Cont', 'Blood', f1.ages, f1.rates, 'f1');
    else notes.push(`${m.name}: no f1 file, no absorption from the small intestine`);
    // Systemic model.
    for (const [from, to, rates] of sys.transfers) {
      if (rates.every((r) => r === 0)) { comp(j, from); if (!isSink(to)) comp(j, to); continue; }
      addTransfer(j, from, to, sys.ages, rates, 'systemic');
    }
    // Urinary bladder.
    for (const [from, to, rates] of bladder.transfers) addTransfer(j, from, to, bladder.ages, rates, 'bladder');
  });

  /* Ingrowth, and the compartments a daughter is born in. */
  const decays = [];
  for (const br of chain.branches) {
    for (const [k, i] of [...compIndex[br.from]]) {
      const keep = gasRule[br.to] ? gasRule[br.to](comps[i].region) : 1;
      if (!(keep > 0)) continue;
      let t = compIndex[br.to].get(k);
      if (t === undefined && gasRule[br.to]) t = comp(br.to, comps[i].name); // decays where it is born
      if (t === undefined) {
        // DCAL's category 1 problem: the daughter's model says nothing about
        // this compartment. Its own files are complete for the cases they
        // were written for; otherwise prompt transfer to blood (option b).
        t = comp(br.to, comps[i].name);
        addTransfer(br.to, comps[i].name, 'Blood', null, [1000], 'patch');
        notes.push(`${chain.members[br.to].name}: no removal from ${comps[i].name}; prompt transfer to blood assumed`);
      }
      decays.push({ from: i, to: t, b: br.b * keep });
    }
  }

  /* Intake. */
  const init = [];
  // Ingested tritiated water is absorbed at once and completely (ICRP 56):
  // the ICRP 72 doses give the stomach wall no dose from its contents for HTO,
  // while organically bound tritium passes through the tract like food.
  if (route === 'ingestion' && parentBio === 'H_H2O') init.push([comp(0, 'Blood'), 1]);
  else if (route === 'ingestion') init.push([comp(0, 'St_Cont'), 1]);
  else if (route === 'injection') init.push([comp(0, 'Blood'), 1]);
  else {
    const dep = Object.keys(lung.deposition).length ? lung.deposition : depositionFor(models, spec.intakeAge, spec.amad ?? 1);
    for (const [name, frac] of Object.entries(dep)) if (frac > 0) init.push([comp(0, name), frac]);
  }

  /* Explicit systemic source regions of each member's own model: what
     "Other" is the complement of. */
  const explicit = memberModels.map((mm) => explicitRegions(models.systemic[mm.bio]));

  return {
    system: 'icrp60', spec: { ...spec, kinetics }, chain, notes,
    members: chain.members.map((m, j) => ({ ...m, bio: memberModels[j].bio, f1: memberModels[j].f1, ownModel: memberModels[j].own, explicit: [...explicit[j]] })),
    comps, transfers, decays, init,
    lungModel: lungName, f1Parent: parentF1,
  };
}

/* The deposition fractions of ICRP66.DEP for a reference age and AMAD. Ages
   between reference individuals are not interpolated: the ICRP gives
   coefficients only at the reference ages, and DCAL deposits per reference
   individual. AMADs between the 13 tabulated values are interpolated
   linearly in log AMAD. */
export function depositionFor(models, intakeAge, amad) {
  const dep = models.deposition;
  const groups = dep.groups.filter((g) => typeof g.age === 'number');
  let g = groups[0];
  for (const x of groups) if (x.age <= intakeAge) g = x;
  const a = dep.amad;
  const out = {};
  const la = Math.log(amad);
  let k = a.findIndex((x) => x >= amad);
  if (k < 0) k = a.length - 1;
  for (const [name, fr] of Object.entries(g.fractions)) {
    if (a[k] === amad || k === 0) { out[name] = fr[k]; continue; }
    const w = (la - Math.log(a[k - 1])) / (Math.log(a[k]) - Math.log(a[k - 1]));
    out[name] = fr[k - 1] + w * (fr[k] - fr[k - 1]);
  }
  return out;
}

const NOBLE = new Set(['He', 'Ne', 'Ar', 'Kr', 'Xe', 'Rn']);
const BONE = new Set(['C_Bone-S', 'C_Bone-V', 'T_Bone-S', 'T_Bone-V']);

/**
 * ICRP 30's rule for a noble-gas daughter under shared kinetics, as the
 * fraction of it that decays where it is formed, by source region; null when
 * the member is no noble gas.
 *   222Rn from 226Ra: escapes from soft tissues; 30 % of it decays in bone
 *   220Rn: decays at the site of production
 *   83mKr from 83Rb: 20 % decays at the site, 80 % escapes
 *   any other noble gas: escapes before it decays
 */
export function nobleGasRule(member, parent, halfLifeDays) {
  const el = elementOf(member);
  if (!NOBLE.has(el)) return null;
  // 220Rn (56 s) decays where it is born; so, a fortiori, do 219Rn (4 s) and 218Rn (35 ms).
  if (member === 'Rn-220' || halfLifeDays < 60 / 86400) return () => 1;
  if (member === 'Rn-222' && parent === 'Ra-226') return (region) => (BONE.has(region) ? 0.3 : 0);
  if (member === 'Kr-83m') return () => 0.2;
  return () => 0;
}

export function explicitRegions(sys) {
  const out = new Set();
  for (const [from, to] of sys.transfers) {
    for (const n of [from, to]) {
      const r = regionOf(n);
      if (!r || ['Blood', 'Other', 'Body_Tis', 'BT-Soft', 'Urine', 'Feces', 'Excreta'].includes(r)) continue;
      if (CONTENTS.has(r) || LUNG_REGIONS.has(r)) continue;
      out.add(r);
    }
  }
  return out;
}
