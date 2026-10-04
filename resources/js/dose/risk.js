/*
  Detriment-adjusted nominal risk coefficients, calculated the way the ICRP
  derived them, step by step, beside the values it printed.

    ICRP 103  Annex A, paras A 141-A 147, Box A.1, Tables A.4.1, A.4.2 and
              A.4.5. For each tissue the nominal risk coefficient R (lifetime
              cases of cancer, or of heritable disease, per 10 000 persons per
              Sv at low dose rate) is adjusted for lethality k and for the
              quality of life of those who survive, with the non-fatal weight
              q = qmin + (1 - qmin) k (qmin 0.1; 0.2 for thyroid, 0 for skin),
              and weighted by the relative cancer-free life lost l:
                  D = R (k + q (1 - k)) l
              Table 1 of the main text: cancer = the sum of D over the
              cancers, heritable = the lethality-adjusted heritable risk
              (para A 164), total = the sum of D.
    ICRP 60   Annex B, paras B115-B119, Tables B-17 to B-20. For each organ the
              probability of fatal cancer F per 10 000 per Sv, with non-fatal
              cancers weighted by their lethality k, F (2 - k), and the
              relative length of life lost l/l̄ (l̄ = 15.0 y):
                  D = F (l/l̄) (2 - k)
              and severe hereditary effects, 100 per 10 000 per Sv with 20 y
              of life lost. Workers: 80 % of F (para B119) and 60 % of the
              hereditary risk (para 89). Table 3 of the main text: fatal =
              the sum of F (its footnote: for fatal cancer the detriment is
              the probability), non-fatal = the sum of F (1 - k) l/l̄,
              hereditary = 100 x 1.33, total.

  The nominal risks themselves come from risk models fitted to the atomic
  bomb survivors and carried to other populations (ICRP 103: Asian and
  Euro-American; ICRP 60: five national populations) with life tables and
  age weights the publications do not give; the calculation starts from them.

  nominalDetriment(system, pop, out) applies the coefficients to a
  calculated intake, two ways: the committed effective dose times the total
  coefficient, and tissue by tissue, each tissue's detriment per Sv times
  the equivalent dose it relates to (DOSE_OF below).
*/

/* ---- ICRP 103 ------------------------------------------------------------- */
const T103 = ['Oesophagus', 'Stomach', 'Colon', 'Liver', 'Lung', 'Bone', 'Skin', 'Breast', 'Ovary', 'Bladder', 'Thyroid', 'Bone marrow', 'Other solid', 'Gonads (heritable)'];
export const P103 = {
  tissues: T103,
  // Table A.4.5 footnote and para A 145.
  qmin: T103.map((t) => (t === 'Skin' ? 0 : t === 'Thyroid' ? 0.2 : 0.1)),
  // Lethality as Table A.4.1 prints it, and the non-fatal weight q of Table
  // A.4.5, which has a digit more: the calculation takes k = (q - qmin)/(1 - qmin).
  k: [0.93, 0.83, 0.48, 0.95, 0.89, 0.45, 0.002, 0.29, 0.57, 0.29, 0.07, 0.67, 0.49, 0.80],
  q: [0.935, 0.846, 0.530, 0.959, 0.901, 0.505, 0.002, 0.365, 0.609, 0.357, 0.253, 0.702, 0.541, 0.820],
  populations: {
    whole: {
      label: 'Whole population (ages 0–85 at exposure)',
      // Table A.4.2, 'Current incidence' (one decimal; Table A.4.1a rounds them).
      R: [15.1, 79.1, 65.4, 30.3, 114.2, 7.0, 1000.0, 112.1, 10.6, 43.4, 32.5, 41.9, 143.8, 20.0],
      Rsource: 'Table A.4.2 (current incidence)',
      l: [0.87, 0.88, 0.97, 0.88, 0.80, 1.00, 1.00, 1.29, 1.12, 0.71, 1.29, 1.63, 1.03, 1.32],
      published: { // Table A.4.1a
        R: [15, 79, 65, 30, 114, 7, 1000, 112, 11, 43, 33, 42, 144, 20],
        adjusted: [15.1, 77.0, 49.4, 30.2, 112.9, 5.1, 4.0, 61.9, 8.8, 23.5, 9.8, 37.7, 110.2, 19.3],
        D: [13.1, 67.7, 47.9, 26.6, 90.3, 5.1, 4.0, 79.8, 9.9, 16.7, 12.7, 61.5, 113.5, 25.4],
        rel: [0.023, 0.118, 0.083, 0.046, 0.157, 0.009, 0.007, 0.139, 0.017, 0.029, 0.022, 0.107, 0.198, 0.044],
        totals: { R: 1715, adjusted: 565, D: 574 },
        table1: { cancer: 5.5, heritable: 0.2, total: 5.7 },
      },
    },
    adult: {
      label: 'Adults of working age (18–64 years at exposure)',
      // Table A.4.1b (whole numbers: single tissues differ from the printed detriment by a few per cent).
      R: [16, 60, 50, 21, 127, 5, 670, 49, 7, 42, 9, 23, 88, 12],
      Rsource: 'Table A.4.1b',
      l: [0.91, 0.89, 1.13, 0.93, 0.96, 1.00, 1.00, 1.20, 1.16, 0.85, 1.19, 1.17, 0.97, 1.32],
      published: { // Table A.4.1b
        R: [16, 60, 50, 21, 127, 5, 670, 49, 7, 42, 9, 23, 88, 12],
        adjusted: [16, 58, 38, 21, 126, 3, 3, 27, 6, 23, 3, 20, 67, 12],
        D: [14.2, 51.8, 43.0, 19.7, 120.7, 3.4, 2.7, 32.6, 6.6, 19.3, 3.4, 23.9, 65.4, 15.3],
        rel: [0.034, 0.123, 0.102, 0.047, 0.286, 0.008, 0.006, 0.077, 0.016, 0.046, 0.008, 0.057, 0.155, 0.036],
        totals: { R: 1179, adjusted: 423, D: 422 },
        table1: { cancer: 4.1, heritable: 0.1, total: 4.2 },
      },
    },
  },
  // The Publication 60 values Table 1 compares with.
  table1p60: { whole: { cancer: 6.0, heritable: 1.3, total: 7.3 }, adult: { cancer: 4.8, heritable: 0.8, total: 5.6 } },
  // Where each R comes from (Box A.1 c; paras A 111-A 124, A 139-A 140): the
  // weights of the excess relative and excess absolute risk models.
  basis: [
    'LSS incidence; ERR:EAR 50:50', 'LSS incidence; ERR:EAR 50:50', 'LSS incidence; ERR:EAR 50:50', 'LSS incidence; ERR:EAR 50:50',
    'LSS incidence; ERR:EAR 30:70', 'Publication 60 (radium-224)', 'Publication 59: 0.1 per Gy', 'pooled analysis; EAR only',
    'LSS incidence; ERR:EAR 50:50', 'LSS incidence; ERR:EAR 50:50', 'pooled analysis; ERR only', 'leukaemia, linear-quadratic EAR; no DDREF',
    'LSS incidence; ERR:EAR 50:50', 'two generations (Section A.6)',
  ],
  // Tissue weighting factors (Table A.4.3; judgements of para A 159): the
  // ovary and the heritable effects make the gonads' 0.08, the other solid
  // cancers the remainder's 0.12 with brain and salivary glands 0.01 each.
  wT: ['0.04', '0.12', '0.12', '0.04', '0.12', '0.01 (bone surface)', '0.01', '0.12', '0.08 with the heritable (gonads)', '0.04', '0.04', '0.12', '0.12 remainder, 0.01 brain, 0.01 salivary glands', '0.08 with the ovary (gonads)'],
};

/** The detriment of each tissue and the coefficients of Table 1, for 'whole' or 'adult'. */
export function detriment103(pop = 'whole') {
  const P = P103.populations[pop];
  const rows = P103.tissues.map((tissue, i) => {
    const qmin = P103.qmin[i], q = P103.q[i];
    const k = (q - qmin) / (1 - qmin);
    const R = P.R[i];
    const adjusted = R * (k + q * (1 - k));
    const D = adjusted * P.l[i];
    return { tissue, R, k, kPrinted: P103.k[i], qmin, q, adjusted, l: P.l[i], D, heritable: i === P103.tissues.length - 1 };
  });
  const sum = (f) => rows.reduce((s, r) => s + f(r), 0);
  const total = { R: sum((r) => r.R), adjusted: sum((r) => r.adjusted), D: sum((r) => r.D) };
  rows.forEach((r, i) => {
    r.rel = r.D / total.D;
    r.published = { R: P.published.R[i], adjusted: P.published.adjusted[i], D: P.published.D[i], rel: P.published.rel[i] };
  });
  const her = rows.find((r) => r.heritable);
  // In 10^-2 Sv^-1: per 10 000 per Sv / 100.
  const table1 = { cancer: (total.D - her.D) / 100, heritable: her.adjusted / 100, total: total.D / 100 };
  return { pop, label: P.label, Rsource: P.Rsource, rows, total, table1, published: { totals: P.published.totals, table1: P.published.table1 }, p60: P103.table1p60[pop] };
}

/* ---- ICRP 60 -------------------------------------------------------------- */
const T60 = ['Bladder', 'Bone marrow', 'Bone surface', 'Breast', 'Colon', 'Liver', 'Lung', 'Oesophagus', 'Ovary', 'Skin', 'Stomach', 'Thyroid', 'Remainder'];
export const P60 = {
  organs: T60,
  // Table B-17: probability of fatal cancer, whole population, per 10 000 per Sv.
  F: [30, 50, 5, 20, 85, 15, 85, 30, 10, 2, 110, 8, 50],
  // Table B-18: expected years of life lost per fatal cancer; l̄ = 15.0 y.
  lYears: [9.8, 30.9, 15.0, 18.2, 12.5, 15.0, 13.5, 11.5, 16.8, 15.0, 12.4, 15.0, 13.7],
  lbar: 15.0,
  // Table B-19, proposed lethality fraction (bone marrow: acute leukaemia; bone
  // surface: bone; lung: lung and bronchus); the remainder's 0.71 from Table B-20 (2 - k = 1.29).
  k: [0.50, 0.99, 0.70, 0.50, 0.55, 0.95, 0.95, 0.95, 0.70, 0.002, 0.90, 0.10, 0.71],
  // Severe hereditary effects per 10 000 per Sv (para 89; Table B-20) and their life lost (para B116).
  hereditary: { whole: 100, adult: 60, lYears: 20.0 },
  adultFactor: 0.8, // workers' F (para B119)
  // Where each F comes from: Table B-15's share of the 5 × 10^-2 Sv^-1 (500
  // per 10 000), or another study (paras B108-B111), the remainder less those.
  basis: [
    'Table B-15: 0.058 × 500 = 29', 'Table B-15: 0.096 × 500 = 48', 'BEIR IV (radium-224): 133 × 10⁻⁴ Gy⁻¹ × lethality 0.70 / Q 20 = 4.7',
    'Table B-15: 0.041 × 500 = 20.5', 'Table B-15: 0.174 × 500 = 87', 'thorotrast: 300 × 10⁻⁴ Gy⁻¹ / Q 20 = 15', 'Table B-15: 0.168 × 500 = 84',
    'Table B-15: 0.061 × 500 = 30.5', 'Table B-15: 0.022 × 500 = 11', 'incidence 10⁻¹ Sv⁻¹ × lethality 0.002 = 2', 'Table B-15: 0.229 × 500 = 114.5',
    'NCRP 80: 0.075 × 10⁻² Gy⁻¹ = 7.5', 'Table B-15: 0.150 × 500 = 75, less thyroid, bone surface, skin and liver',
  ],
  // Tissue weighting factors (para B120): four groups.
  wT: ['0.05', '0.12', '0.01', '0.05', '0.12', '0.05', '0.12', '0.05', '0.20 with the hereditary (gonads)', '0.01', '0.12', '0.05', '0.05'],
  hereditaryBasis: 'severe effects in all generations, 1 × 10⁻² Sv⁻¹ (para 89)',
  hereditaryWT: '0.20 with the ovary (gonads)',
  labels: { whole: 'Whole population', adult: 'Adult workers' },
  published: {
    // Table B-20 (whole population).
    product: [29.4, 104.0, 6.5, 36.4, 102.7, 15.8, 80.3, 24.2, 14.6, 4.0, 100.0, 15.2, 58.9],
    rel: [0.040, 0.143, 0.009, 0.050, 0.141, 0.022, 0.111, 0.034, 0.020, 0.006, 0.139, 0.021, 0.081],
    gonads: { product: 133.3, rel: 0.183 },
    total: 725.3,
    // Table 4, aggregated detriment, 10^-2 Sv^-1.
    table4: {
      whole: { D: [0.29, 1.04, 0.07, 0.36, 1.03, 0.16, 0.80, 0.24, 0.15, 0.04, 1.00, 0.15, 0.59], cancer: 5.92, gonads: 1.33, total: 7.3 },
      adult: { D: [0.24, 0.83, 0.06, 0.29, 0.82, 0.13, 0.64, 0.19, 0.12, 0.03, 0.80, 0.12, 0.47], cancer: 4.74, gonads: 0.80, total: 5.6 },
    },
    // Table 3, 10^-2 Sv^-1 (rounded values).
    table3: { whole: { fatal: 5.0, nonfatal: 1.0, hereditary: 1.3, total: 7.3 }, adult: { fatal: 4.0, nonfatal: 0.8, hereditary: 0.8, total: 5.6 } },
  },
};

/** The detriment of each organ (Table B-20) and the coefficients of Tables 3 and 4, for 'whole' or 'adult'. */
export function detriment60(pop = 'whole') {
  const f = pop === 'adult' ? P60.adultFactor : 1;
  const rows = P60.organs.map((organ, i) => {
    const F = P60.F[i] * f, lRel = P60.lYears[i] / P60.lbar, k = P60.k[i];
    return { organ, F, lYears: P60.lYears[i], lRel, k, twoMinusK: 2 - k, D: F * lRel * (2 - k), fatalWeighted: F * lRel, nonfatal: F * lRel * (1 - k) };
  });
  const H = P60.hereditary[pop], hRel = P60.hereditary.lYears / P60.lbar;
  const gonads = { organ: 'Gonads (severe hereditary effects)', H, lYears: P60.hereditary.lYears, lRel: hRel, D: H * hRel };
  const cancer = rows.reduce((s, r) => s + r.D, 0);
  const total = cancer + gonads.D;
  for (const r of rows) r.rel = r.D / total;
  gonads.rel = gonads.D / total;
  const pub = P60.published;
  rows.forEach((r, i) => {
    r.published = { table4: pub.table4[pop].D[i], ...(pop === 'whole' ? { product: pub.product[i], rel: pub.rel[i] } : {}) };
  });
  gonads.published = { table4: pub.table4[pop].gonads, ...(pop === 'whole' ? pub.gonads : {}) };
  const sumF = rows.reduce((s, r) => s + r.F, 0), nonfatal = rows.reduce((s, r) => s + r.nonfatal, 0);
  return {
    pop, label: P60.labels[pop], rows, gonads, cancer, total, sumF,
    table3: { fatal: sumF / 100, nonfatal: nonfatal / 100, hereditary: gonads.D / 100, total: (sumF + nonfatal + gonads.D) / 100 },
    table4: { cancer: cancer / 100, gonads: gonads.D / 100, total: total / 100 },
    published: { table3: pub.table3[pop], table4: pub.table4[pop], total: pop === 'whole' ? pub.total : null },
  };
}

/* ---- applied to a calculated intake ---------------------------------------- */
/* The equivalent dose each tissue's detriment relates to: per sex and averaged
   in the ICRP 103 system (dose103), one value per tissue in the ICRP 60 system
   (dose60, whose gonads are the higher of testes and ovaries; the hereditary
   risk relates to the gonad dose of the whole population, so the mean). */
export const DOSE_OF = {
  103: {
    Oesophagus: ['Oesophagus'], Stomach: ['Stomach'], Colon: ['Colon'], Liver: ['Liver'], Lung: ['Lung'], Bone: ['Bone surface'],
    Skin: ['Skin'], Breast: ['Breast'], Ovary: ['Gonads', 'F'], Bladder: ['Bladder'], Thyroid: ['Thyroid'], 'Bone marrow': ['Red marrow'],
    'Other solid': ['Remainder'], 'Gonads (heritable)': ['Gonads'],
  },
  60: {
    Bladder: ['Bladder'], 'Bone marrow': ['Red marrow'], 'Bone surface': ['Bone surface'], Breast: ['Breast'], Colon: ['Colon'], Liver: ['Liver'],
    Lung: ['Lung'], Oesophagus: ['Oesophagus'], Ovary: ['Ovaries'], Skin: ['Skin'], Stomach: ['Stomach'], Thyroid: ['Thyroid'],
    Remainder: ['Remainder'], 'Gonads (severe hereditary effects)': ['Testes', 'Ovaries'],
  },
};
export const DOSE_LABEL = {
  103: { Bone: 'bone surface', Ovary: 'ovaries (female)', 'Bone marrow': 'red marrow', 'Other solid': 'remainder', 'Gonads (heritable)': 'gonads (mean of testes and ovaries)' },
  60: { 'Bone marrow': 'red marrow', Ovary: 'ovaries', 'Gonads (severe hereditary effects)': 'mean of testes and ovaries' },
};
/* Committed equivalent dose, Sv per Bq, that a tissue's detriment relates to. */
function doseOf(system, tissue, o) {
  const keys = DOSE_OF[system][tissue];
  if (!keys) throw new Error(`no dose for ${tissue}`);
  if (system === '60') return keys.reduce((s, k) => s + (o.H[k] || 0), 0) / keys.length;
  const [name, sex] = keys;
  return (o.H[sex || 'avg'] || {})[name] || 0;
}

/**
 * The nominal detriment of a calculated intake at each age, per Bq taken in:
 * e times the total coefficient (the printed one), and tissue by tissue.
 *   out: the calculation's results (one per age, with E and H)
 */
export function nominalDetriment(system, pop, out) {
  const sys = String(system);
  const d = sys === '60' ? detriment60(pop) : detriment103(pop);
  // Per tissue: detriment, and the risk it starts from (ICRP 103 cancer
  // incidence R, ICRP 60 fatal cancer F), per Sv.
  const tissues = sys === '60'
    ? [...d.rows.map((r) => ({ tissue: r.organ, D: r.D / 1e4, R: r.F / 1e4, heritable: false })), { tissue: d.gonads.organ, D: d.gonads.D / 1e4, R: 0, heritable: true }]
    : d.rows.map((r) => ({ tissue: r.tissue, D: r.D / 1e4, R: r.heritable ? 0 : r.R / 1e4, heritable: r.heritable }));
  const coefficient = (sys === '60' ? d.published.table3.total : d.published.table1.total) / 100;
  const ages = out.map((o) => {
    const parts = tissues.map((t) => {
      const H = doseOf(sys, t.tissue, o);
      return { ...t, H, detriment: H * t.D, risk: H * t.R };
    });
    const organ = parts.reduce((s, p) => s + p.detriment, 0);
    for (const p of parts) p.share = organ > 0 ? p.detriment / organ : 0;
    return {
      age: o.age, E: o.E, fromE: o.E * coefficient, organ,
      heritable: parts.filter((p) => p.heritable).reduce((s, p) => s + p.detriment, 0),
      risk: parts.reduce((s, p) => s + p.risk, 0), parts,
    };
  });
  return { system: sys, pop, coefficient, label: d.label, ages };
}
