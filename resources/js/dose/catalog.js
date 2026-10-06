/*
  What each system can calculate, for the page's choices: per nuclide its
  half-life (T, days), decay modes (m, as the decay index has them: A, B-,
  B+, EC, IT, SF run together) and its forms by route.

    ICRP 60   the inhalation and ingestion cases of ICRP 72, as DCAL's batch
              files for Federal Guidance Report 13 run them: every nuclide of
              ICRP 72's tables with each of its forms (f1 values, absorption
              types, gases and vapours)
    ICRP 103  every ICRP 107 nuclide with a half-life of at least 10 minutes
              (ICRP 158 section 1.4.1) of an element whose model is
              transcribed here, with the element's inhaled and ingested forms
              and direct uptake to blood
*/
import { parentModelName, f1FileName, f1Table } from './model60.js';

const elementOf = (name) => /^([A-Z][a-z]?)-/.exec(name)[1];
const massOf = (name) => Number(/-(\d+)/.exec(name)[1]);
const sortNuclides = (a, b) => (a.Z - b.Z) || (massOf(a.name) - massOf(b.name)) || a.name.localeCompare(b.name);

export const ELEMENTS = ['H', 'He', 'Li', 'Be', 'B', 'C', 'N', 'O', 'F', 'Ne', 'Na', 'Mg', 'Al', 'Si', 'P', 'S', 'Cl', 'Ar', 'K', 'Ca', 'Sc', 'Ti', 'V', 'Cr', 'Mn', 'Fe', 'Co', 'Ni', 'Cu', 'Zn', 'Ga', 'Ge', 'As', 'Se', 'Br', 'Kr', 'Rb', 'Sr', 'Y', 'Zr', 'Nb', 'Mo', 'Tc', 'Ru', 'Rh', 'Pd', 'Ag', 'Cd', 'In', 'Sn', 'Sb', 'Te', 'I', 'Xe', 'Cs', 'Ba', 'La', 'Ce', 'Pr', 'Nd', 'Pm', 'Sm', 'Eu', 'Gd', 'Tb', 'Dy', 'Ho', 'Er', 'Tm', 'Yb', 'Lu', 'Hf', 'Ta', 'W', 'Re', 'Os', 'Ir', 'Pt', 'Au', 'Hg', 'Tl', 'Pb', 'Bi', 'Po', 'At', 'Rn', 'Fr', 'Ra', 'Ac', 'Th', 'Pa', 'U', 'Np', 'Pu', 'Am', 'Cm', 'Bk', 'Cf', 'Es', 'Fm', 'Md'];
export const Z = Object.fromEntries(ELEMENTS.map((e, i) => [e, i + 1]));

/** The f1 value of an f1 file for the adult (its last age group). */
function adultF1(models, name) {
  try {
    const t = f1Table(models, name);
    return t ? t.f1[t.f1.length - 1] : null;
  } catch { return null; }
}
const fmt = (x) => (x == null ? '?' : x >= 0.01 ? String(+x.toPrecision(3)) : x.toExponential(0).replace('e', 'E'));

/* DCAL's respiratory tract files for gases and vapours (ICRP 66 and 71). */
const GAS_60 = {
  H2OVAPOR: 'Tritiated water vapour (HTO)', HGAS: 'Tritium gas (HT)', HORGANIC: 'Organic tritium compounds',
  COGAS: 'Carbon monoxide', CO2GAS: 'Carbon dioxide', SO2GAS: 'Sulphur dioxide', CS2GAS: 'Carbon disulphide',
  NIVAPOR: 'Nickel carbonyl', RUO4: 'Ruthenium tetroxide', TEVAPOR: 'Tellurium vapour', IVAPOR: 'Elemental iodine vapour',
  IMETHYL: 'Methyl iodide', HGVAPOR: 'Mercury vapour',
};

export function catalog60(data) {
  const { cases, models, index } = data;
  const byName = new Map();
  const entry = (name) => {
    if (!byName.has(name)) byName.set(name, { name, Z: Z[elementOf(name)] || 0, t: index[name]?.t || null, T: index[name]?.T ?? null, m: index[name]?.m || '', ingestion: [], inhalation: [] });
    return byName.get(name);
  };
  for (const c of cases.ingestion) {
    if (!index[c.nuclide]) continue;
    const el = elementOf(c.nuclide);
    let bio, f1name;
    try {
      bio = parentModelName(models, index, c.nuclide, 'ingestion', c.bio);
      f1name = f1FileName(models, el, 'ingestion', bio, null, c.f1);
    } catch { continue; }
    const f1 = adultF1(models, f1name);
    const e = entry(c.nuclide);
    const label = `f1 = ${fmt(f1)}` + (c.bio ? ` (${c.bio})` : '');
    e.ingestion.push({ key: `${c.bio || ''}|${c.f1 || ''}`, label, f1, spec: { bio: c.bio || null, f1file: c.f1 || null } });
  }
  for (const c of cases.inhalation) {
    if (!index[c.nuclide]) continue;
    const el = elementOf(c.nuclide);
    let f1 = null;
    try {
      const bio = parentModelName(models, index, c.nuclide, 'inhalation', c.bio);
      f1 = adultF1(models, f1FileName(models, el, 'inhalation', bio, /^[FMS]$/.test(c.type) ? c.type : null, c.f1));
    } catch { /* gases without an f1 */ }
    const e = entry(c.nuclide);
    const gas = c.lung && !/^ICRP66[FMS]$/.test(c.lung);
    const what = gas ? `${GAS_60[c.lung] || c.lung} (${c.type === 'V' ? 'Type V' : 'gas or vapour'})` : `Type ${c.type}`;
    const label = `${what}${f1 != null ? `, f1 = ${fmt(f1)}` : ''}`;
    e.inhalation.push({ key: `${c.type}|${c.bio || ''}|${c.f1 || ''}|${c.lung || ''}`, label, spec: { type: c.type, bio: c.bio || null, f1file: c.f1 || null, lung: c.lung || null } });
  }
  return { system: '60', nuclides: [...byName.values()].sort(sortNuclides) };
}

export function catalog103(data) {
  const { elements, index } = data;
  const out = [];
  for (const [name, n] of Object.entries(index)) {
    const el = elementOf(name);
    const E = elements[el];
    if (!E || !(n.T >= 10 / 1440)) continue;
    const forms = (list) => list.map((f) => ({ key: f.id, label: f.label, default: !!f.default }));
    out.push({
      name, Z: Z[el] || 0, t: n.t, T: n.T, m: n.m || '',
      ingestion: (E.ingestion || []).map((f) => ({ key: f.id, label: `${f.label} (adult fA ${fmt(f.fA[5])})`, spec: { form: f.id } })),
      inhalation: [
        ...forms(E.inhalation?.particulate || []).map((f) => ({ ...f, spec: { form: f.key }, aerosol: true })),
        ...forms(E.inhalation?.gases || []).map((f) => ({ ...f, spec: { form: f.key }, aerosol: false })),
      ],
      // Direct uptake to blood, which the annex of Publication 158 gives too
      // (not for radon, whose model starts in the lungs or the stomach).
      injection: el === 'Rn' ? [] : [{ key: 'blood', label: 'Into blood (injection; wounds and skin with rapid uptake)', spec: {} }],
    });
  }
  return { system: '103', nuclides: out.sort(sortNuclides), elements: Object.keys(elements) };
}
