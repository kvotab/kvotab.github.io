#!/usr/bin/env node
/*
  The ICRP 60 engine against DCAL itself: the committed doses in the dose-rate
  files (*.HRT) that dcal-run.sh leaves in WORK/wrk/fgr13, beside the engine's,
  and both beside ICRP 72's when local/icrp72.json is there.

      node resources/tests/dose_coefficients/dcal-compare.mjs WORK NUCLIDE ROUTE [TYPE] [TISSUE...]

  ROUTE is ingestion, inhalation or injection; TYPE F, M or S for inhalation
  (or - to skip it). Each cell is this page / DCAL, then DCAL / ICRP 72.
*/
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '../../..');
const DATA = path.join(ROOT, 'resources/data/dose');
const JS = path.join(ROOT, 'resources/js/dose');
const [work, nuc, route, typeArg, ...tissueArgs] = process.argv.slice(2);
if (!work || !nuc || !route) {
  console.error('usage: dcal-compare.mjs WORK NUCLIDE ROUTE [TYPE|-] [TISSUE...]');
  process.exit(2);
}
const type = !typeArg || typeArg === '-' ? null : typeArg.toUpperCase();
const tissues = tissueArgs.length ? tissueArgs : ['E', 'Testes', 'Ovaries', 'Red marrow', 'Bone surface', 'Liver', 'Kidneys', 'Lung', 'Colon'];

/* An EPACAL dose-rate file: the exposure age and each target's committed dose. */
function readHrt(file) {
  const t = fs.readFileSync(file, 'latin1').replace(/\r/g, '');
  const age = Number(/^\s*([\d.]+) d, or\s+[\d.]+ y = exposure age/m.exec(t)?.[1]);
  const d = {};
  const re = /^(\S[^\n,]*?), t = [^\n]*\n[\s\S]*?Committed Dose \(Sv\/Bq\) = *([-\d.E+]+)/gm;
  let m;
  while ((m = re.exec(t))) d[m[1].trim()] = Number(m[2]);
  const eff = /Effective Dose Rate[^\n]*\n[\s\S]*?Committed Dose \(Sv\/Bq\) = *([-\d.E+]+)/.exec(t);
  if (eff) d.E = Number(eff[1]);
  const g = (k) => d[k] ?? NaN;
  return {
    age,
    H: {
      E: d.E, Testes: g('Testes'), Ovaries: g('Ovaries'), 'Red marrow': g('R_Marrow'), 'Bone surface': g('Bone_Sur'),
      Liver: g('Liver'), Kidneys: g('Kidneys'), Spleen: g('Spleen'), Lung: d.Lung_66 ?? NaN, ET: d.ET_Reg ?? NaN,
      Colon: 0.57 * g('ULI_Wall') + 0.43 * g('LLI_Wall'), Stomach: g('St_Wall'), Bladder: g('UB_Wall'),
      Muscle: g('Muscle'), Breast: g('Breasts'), Thyroid: g('Thyroid'), Brain: g('Brain'), Skin: g('Skin'),
    },
  };
}
/* DCAL's file name: XXZZZ from the nuclide, the age letter, the route or type, the AMAD. */
const n = nuc.replace('-', '');
const stem5 = (nuc.length > 6 ? nuc.slice(0, 2) + nuc.slice(3, 5) + nuc.slice(-1) : nuc.length === 6 ? n : nuc.padEnd(5, '_')).toUpperCase();
const mode = route === 'inhalation' ? `${type}1` : route === 'ingestion' ? 'G_' : 'J_';
const dir = path.join(path.resolve(work), 'wrk/fgr13');
const files = fs.readdirSync(dir).filter((f) => f.toUpperCase().startsWith(stem5) && f.slice(6, 8).toUpperCase() === mode && /\.HRT$/i.test(f)).sort();
if (!files.length) { console.error(`no ${stem5}?${mode}.HRT in ${dir}: run dcal-run.sh first`); process.exit(1); }
const dcal = new Map(files.map((f) => { const r = readHrt(path.join(dir, f)); return [r.age, r.H]; }));

const { loadSystem } = await import(path.join(JS, 'data.js'));
const { coefficients60, AGES_60 } = await import(path.join(JS, 'dose60.js'));
const { recipe60 } = await import(path.join(JS, 'model60.js'));
const io = {
  json: async (p) => JSON.parse(fs.readFileSync(path.join(DATA, p), 'utf8')),
  bin: async (p) => { const b = fs.readFileSync(path.join(DATA, p)); return b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength); },
};
const d60 = await loadSystem('60', io);
await d60.prepare(nuc);
const res = coefficients60(d60, recipe60(d60.cases, route, { nuclide: nuc, type: type ?? undefined }), AGES_60);
const refFile = path.join(HERE, 'local/icrp72.json');
const ref = fs.existsSync(refFile) ? JSON.parse(fs.readFileSync(refFile, 'utf8')) : null;
const N72 = { E: 'E', Testes: 'Testes', Ovaries: 'Ovaries', 'Red marrow': 'Red Marrow', 'Bone surface': 'Bone Surface', Liver: 'Liver', Kidneys: 'Kidneys', Spleen: 'Spleen', Lung: 'Lungs', ET: 'ET', Colon: 'Colon', Stomach: 'Stomach', Bladder: 'Urinary Bladder', Muscle: 'Muscle', Breast: 'Breast', Thyroid: 'Thyroid', Brain: 'Brain', Skin: 'Skin' };

console.log(`${nuc} ${route}${type ? ` Type ${type}` : ''}: this page / DCAL${ref ? ', and DCAL / ICRP 72' : ''} (${files.join(' ')})`);
console.log('age    ' + tissues.map((k) => k.slice(0, 12).padStart(ref ? 14 : 8)).join(''));
for (const r of res) {
  const D = [...dcal].find(([a]) => Math.abs(a - r.intakeAge) < 1)?.[1];
  const R = ref?.find((x) => x.route === route && x.nuclide === nuc && x.age === r.age && (!type || x.type === type));
  const ours = { ...r.H, E: r.E };
  const cells = tissues.map((k) => {
    const a = D ? ours[k] / D[k] : NaN;
    const b = D && R ? D[k] / R.H[N72[k]] : NaN;
    const s = isFinite(a) ? a.toFixed(3) : '-';
    return (ref ? `${s} ${isFinite(b) ? b.toFixed(2) : '-'}` : s).padStart(ref ? 14 : 8);
  });
  console.log(`${String(r.age).padEnd(7)}${cells.join('')}`);
}
