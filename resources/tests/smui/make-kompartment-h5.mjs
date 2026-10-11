/* Files as Kompartment writes them (kompartment/src/io/resultfile.js,
   datafile.js and hdf5.js, the app's own writers, not a copy of their
   layout), for test_hdf5.py and test-ui-hdf5.py: a deterministic run, a
   probabilistic one, and a data file (parameters with units and
   distributions, a lookup table, a text value), with the values they were
   given, as JSON beside them.

     node make-kompartment-h5.mjs <folder>

   writes komp-run.h5, komp-prob.h5, komp-data.h5 and komp.json. */
import { writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const io = (f) => pathToFileURL(path.join(here, '..', '..', '..', 'kompartment', 'src', 'io', f)).href;
const { resultTree } = await import(io('resultfile.js'));
const { writeHDF5 } = await import(io('hdf5.js'));
const { writeDataHDF5 } = await import(io('datafile.js'));

const out = process.argv[2];
const nt = 24;
const t = Float64Array.from({ length: nt }, (_, k) => (k === 0 ? 0 : 10 ** (k / 4)));
const outputs = [
  { block: 'Soil', label: 'Soil.Cs-137', dims: ['Radionuclides'], index: ['Cs-137'], nuclide: 'Cs-137', unit: 'Bq', kind: 'compartment', timeDependent: true },
  { block: 'Soil', label: 'Soil.I-129', dims: ['Radionuclides'], index: ['I-129'], nuclide: 'I-129', unit: 'Bq', kind: 'compartment', timeDependent: true },
  { block: 'Water', label: 'Water.Cs-137', dims: ['Radionuclides'], index: ['Cs-137'], nuclide: 'Cs-137', unit: 'Bq', kind: 'compartment', timeDependent: true },
  { block: 'Dose', label: 'Dose', unit: 'Sv/year', kind: 'expression', timeDependent: true },
  { block: 'Soil.kd', label: 'Soil.kd', unit: 'm3/kg', kind: 'parameter', timeDependent: false },
  { block: 'Water.depth', label: 'Water.depth', unit: 'm', kind: 'parameter', timeDependent: false },
];
const indexLists = [{ name: 'Radionuclides', elements: ['Cs-137', 'I-129'] }];
const value = (i, k) => (outputs[i].timeDependent ? (i + 1) * Math.exp(-t[k] / (300 * (i + 1))) * (1 + k / 7) : 0.5 + i);
const column = (i) => Float64Array.from({ length: nt }, (_, k) => value(i, k));
const which = outputs.map((_, i) => i);
const project = { name: 'smui test', simulation: { time_unit: 'year', start_time: 0, end_time: t[nt - 1], solver: 'ndf' }, description: 'A run for <smui>\n\nwritten by its test.' };
const now = new Date(Date.UTC(2026, 9, 11, 8, 0, 0));
writeFileSync(path.join(out, 'komp-run.h5'), writeHDF5(resultTree({ t, outputs, column, which, project, indexLists, now })));

// realisations: [nt, S] time-major for a series, S values for a parameter
const S = 30;
const draw = (i, k, s) => (outputs[i].timeDependent ? value(i, k) * (1 + 0.1 * Math.sin(s + 1.7 * i)) : (0.5 + i) * (1 + 0.01 * s * (i + 1)));
const realisations = {
  iterations: S,
  matrixFor(i) {
    const m = new Float32Array(nt * S);
    for (let k = 0; k < nt; k++) for (let s = 0; s < S; s++) m[k * S + s] = draw(i, k, s);
    return m;
  },
};
writeFileSync(path.join(out, 'komp-prob.h5'), writeHDF5(resultTree({ t, outputs, column, which, project, indexLists, now, realisations })));

// a data file: rows as Kompartment's data sheet has them
const data = [
  { id: 'Soil.kd', unit: 'm3/kg', value: 0.25, pdf: { kind: 'logn', params: { gm: 0.25, gsd: 2 } }, note: 'SKB R-01-01' },
  { id: 'Soil.porosity', unit: '-', value: 0.3, pdf: { kind: 'unif', params: { min: 0.2, max: 0.4 } } },
  { id: 'Well.flow', unit: 'm3/year', time: 0, value: 10 },
  { id: 'Well.flow', unit: 'm3/year', time: 1000, value: 12.5 },
  { id: 'Well.flow', unit: 'm3/year', time: 100, value: 11 },
  { id: 'Site.name', unit: '', value: 'Forsmark' },
];
writeFileSync(path.join(out, 'komp-data.h5'), writeDataHDF5(data, { root: 'model' }));

writeFileSync(path.join(out, 'komp.json'), JSON.stringify({
  t: Array.from(t),
  outputs: outputs.map((o, i) => ({ ...o, run: Array.from(column(i)), prob: Array.from(realisations.matrixFor(i)) })),
  S,
}));
