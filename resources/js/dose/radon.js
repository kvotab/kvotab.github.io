/*
  Effective dose per exposure to radon (222Rn) and thoron (220Rn) and their
  short-lived progeny in homes, calculated the way Publication 158 does it
  (Section 32 and Annex C, with the method of Publication 137 Annex A):

    1. Each progeny nuclide (218Po, 214Pb and 214Bi; 212Pb and 212Bi) inhaled
       in each mode of the home aerosol -- unattached (1 nm), nucleation (30
       or 40 nm) and accumulation (200 nm) -- is an ordinary inhalation here:
       the deposition of Table C.1 for that mode and age, the absorption of
       Table 32.1 for its element, the element's systemic model, and its chain
       up to 210Pb (which with its progeny adds under 0.01 %). This gives e,
       Sv per Bq, for each nuclide and mode (Table C.8).
    2. For each mode i, the dose per unit exposure to potential alpha energy:
           D_i = B Σ_j r_ij e_ij / Σ_j r_ij ε_j      Sv per J h m^-3
       with the activity ratios r of the progeny in that mode (Publication 137
       paras A80-A81), the potential alpha energy per becquerel ε (its Table
       A.1) and the mean breathing rate at home B (Table 32.3).
    3. E = fp D_u + (1 - fp) [fpn D_n + (1 - fpn) D_a] (Table C.9), with the
       unattached fraction fp of the potential alpha energy concentration and
       the nucleation mode's share fpn of the attached part (Table 32.2).
    4. The gas itself: its dose coefficient (Sv per Bq, the radon model) times
       λ V / 24, λ the rate from lung air to the environment (d^-1) and V the
       volume of lung air (para C 18): Sv per Bq h m^-3 of gas.

  Units: Sv per J h m^-3 is mSv per mJ h m^-3; 1 WLM = 3.54 mJ h m^-3; an
  exposure of 1 Bq h m^-3 of equilibrium equivalent concentration (EEC) is
  5.56 × 10^-6 mJ h m^-3 for radon and 7.56 × 10^-5 for thoron, and for radon
  gas the EEC is F times the gas concentration.
*/

/* Publication 137 Table A.1: potential alpha energy per becquerel, J. */
export const PAE_PER_BQ = { 'Po-218': 5.79e-10, 'Pb-214': 2.86e-9, 'Bi-214': 2.12e-9, 'Pb-212': 6.91e-8, 'Bi-212': 6.55e-9 };
/* The same per becquerel of the gas with its progeny in equilibrium, J. */
export const EEC_J_PER_BQ = { radon: 5.56e-9, thoron: 7.56e-8 };
export const MJ_PER_WLM = 3.54;
/* Publication 137 paras A80-A81: activity ratios of the progeny, unattached
   and attached (the same for every attached mode). */
export const KINDS = {
  radon: { gas: 'Rn-222', progeny: ['Po-218', 'Pb-214', 'Bi-214'], stopBefore: 'Pb-210', ratios: { u: [1, 0.1, 0], attached: [1, 0.75, 0.6] } },
  thoron: { gas: 'Rn-220', progeny: ['Pb-212', 'Bi-212'], stopBefore: null, ratios: { u: [1, 0], attached: [1, 0.25] } },
};
export const MODES = ['u', 'n', 'a'];
export const MODE_LABEL = { u: 'unattached', n: 'nucleation', a: 'accumulation' };
const BOUND_IN = ['ET2', 'BB', 'bb', 'AI', 'LNET', 'LNTH']; // lead: throughout but ET1 (Pb.json)
const ratio = (kind, mode, j) => (mode === 'u' ? KINDS[kind].ratios.u : KINDS[kind].ratios.attached)[j];

/** The aerosol sizes (AMTD, nm) of the modes, from Table 32.2. */
export function modeSizes(data, kind) {
  return { u: 1, ...Object.fromEntries(data.radon.aerosol[kind].modes.map((m) => [m.mode, m.AMTD])) };
}

/**
 * The inhalations behind the doses per exposure: each progeny nuclide in each
 * mode at each age, then the gas at each age; and λ and V of step 4. Every
 * job is independent of the others: the page runs them in a pool of workers,
 * radonCoefficients one after another. buildChain comes from chain.js.
 */
export function radonPlan(data, kind, ages, buildChain) {
  const K = KINDS[kind], R = data.radon;
  const size = modeSizes(data, kind);
  const jobs = [];
  K.progeny.forEach((nuclide, j) => {
    // The chain up to the first long-lived member (210Pb), as a member count.
    const names = buildChain(data.index, nuclide, { cutoff: 0 }).members.map((m) => m.name);
    const last = K.stopBefore && names.includes(K.stopBefore) ? names.indexOf(K.stopBefore) : null;
    for (const mode of MODES) {
      if (!ratio(kind, mode, j)) continue;
      for (let a = 0; a < ages.length; a++) jobs.push({ nuclide, mode, a, size: size[mode], last });
    }
  });
  for (let a = 0; a < ages.length; a++) jobs.push({ nuclide: K.gas, mode: null, a });
  // The gas's dose per exposure (para C 18): λ from the male model of the
  // radon file, V the lung-air volume of the sexes averaged (Table C.3).
  const model = data.elements.Rn.systemic.male;
  const out = model.transfers.find(([f, t]) => f === 'RT-air' && ['Exhaled', 'Env'].includes(model.compartments[t]));
  if (!out) throw new Error('radon model: no transfer from RT-air to the environment');
  const L = R.lungAir.litres;
  const volume = [L[0], L[1], L[2], L[3], (L[4] + L[5]) / 2, (L[6] + L[7]) / 2].map((x) => x / 1000);
  return { kind, ages, jobs, lambda: out[2], volume };
}

/** What a job is, for a progress line. */
export function radonJobText(job, ages) {
  return job.mode == null
    ? `${job.nuclide} gas, age ${job.a + 1} of ${ages.length}`
    : `${job.nuclide}, ${MODE_LABEL[job.mode]} mode, age ${job.a + 1} of ${ages.length}`;
}

/**
 * One job of the plan: e, Sv per Bq. A progeny nuclide is an inhalation of
 * a form made for it -- the deposition of Table C.1 and the absorption of
 * Table 32.1 -- that the element's forms hold only while it runs.
 */
export async function radonJob(data, job, coefficients103, ages) {
  await data.prepare(job.nuclide);
  if (job.mode == null) return coefficients103(data, { nuclide: job.nuclide, route: 'inhalation', form: 'gas', cutoff: 1e-4 }, [ages[job.a]])[0].E;
  const R = data.radon, el = job.nuclide.split('-')[0], E0 = data.elements[el], ab = R.absorption[el];
  const dep = R.deposition[job.a][job.size];
  const id = `radon-home-${job.mode}-${job.a}`;
  const form = {
    // Aerosol particles, given as a gas form only to set their deposition:
    // their progeny keep the parent's fr in the alimentary tract.
    id, label: `${MODE_LABEL[job.mode]} radon progeny in a home`, systemic: 'default', entry: null, fA: null, particles: true,
    deposition: { total: dep.total, ET1: dep.ET1, ET2: dep.ET2, BB: dep.BB, bb: dep.bb, AI: dep.AI },
    absorption: { fr: ab.fr, sr: ab.sr, ss: ab.ss ?? 0, fb: ab.fb, sb: ab.sb ?? 0, boundIn: ab.fb > 0 ? BOUND_IN : null },
  };
  const gases = E0.inhalation.gases || [];
  E0.inhalation.gases = [...gases, form];
  try {
    return coefficients103(data, { nuclide: job.nuclide, route: 'inhalation', form: id, cutoff: 1e-4, ...(job.last ? { last: job.last } : {}) }, [ages[job.a]])[0].E;
  } finally { E0.inhalation.gases = gases; }
}

/** The jobs' e (in the plan's order) put together, as radonDoses takes them. */
export function radonAssemble(plan, values) {
  const e = {}, gas = [];
  plan.jobs.forEach((job, k) => {
    if (job.mode == null) gas[job.a] = values[k];
    else ((e[job.nuclide] ||= {})[job.mode] ||= [])[job.a] = values[k];
  });
  const gasPerExposure = gas.map((x, a) => x * plan.lambda[a] * plan.volume[a] / 24);
  return { kind: plan.kind, ages: plan.ages, e, gas, gasPerExposure, lambda: plan.lambda, volume: plan.volume };
}

/**
 * e (Sv per Bq) of each progeny nuclide in each mode at each age, and of the
 * gas, one job after another; coefficients103 and the ages come from
 * dose103.js.
 */
export async function radonCoefficients(data, kind, coefficients103, ages, buildChain, progress = () => {}) {
  const plan = radonPlan(data, kind, ages, buildChain);
  const values = [];
  for (const job of plan.jobs) {
    values.push(await radonJob(data, job, coefficients103, ages));
    progress(values.length, plan.jobs.length, radonJobText(job, ages));
  }
  return radonAssemble(plan, values);
}

/**
 * Effective dose per exposure at each age, for the unattached fraction fp,
 * the nucleation share fpn and (radon) the equilibrium factor F given, or
 * those of Table 32.2.
 */
export function radonDoses(data, co, opt = {}) {
  const kind = co.kind, K = KINDS[kind], R = data.radon, A = R.aerosol[kind];
  const fp = opt.fp ?? A.fp, fpn = opt.fpn ?? A.modes.find((m) => m.mode === 'n').fpi, F = opt.F ?? A.F;
  const n = co.ages.length;
  const D = {};
  for (const mode of MODES) {
    D[mode] = Array.from({ length: n }, (_, a) => {
      let num = 0, den = 0;
      K.progeny.forEach((nuc, j) => {
        const r = ratio(kind, mode, j);
        if (!r) return;
        num += r * co.e[nuc][mode][a];
        den += r * PAE_PER_BQ[nuc];
      });
      return R.breathing[a] * num / den;
    });
  }
  // Sv per J h m^-3 (= mSv per mJ h m^-3).
  const progeny = D.u.map((_, a) => fp * D.u[a] + (1 - fp) * (fpn * D.n[a] + (1 - fpn) * D.a[a]));
  const eec = EEC_J_PER_BQ[kind];
  const res = { kind, fp, fpn, F, D, progeny, perWLM: progeny.map((x) => x * MJ_PER_WLM), perEEC: progeny.map((x) => x * eec), gas: co.gasPerExposure, breathing: R.breathing };
  if (kind === 'radon' && F > 0) {
    // Per Bq h m^-3 of radon gas: the progeny at F, and the gas.
    res.progenyPerGas = progeny.map((x) => x * eec * F);
    res.total = res.progenyPerGas.map((x, a) => x + co.gasPerExposure[a]);
    res.gasPerPAE = co.gasPerExposure.map((x) => x / (eec * F));
    res.totalPerPAE = res.total.map((x) => x / (eec * F));
  }
  return res;
}
