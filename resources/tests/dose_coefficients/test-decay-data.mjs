#!/usr/bin/env node
/*
  The decay data the page offers besides each system's own: every release of
  ENSDF in resources/data/dose/ensdf/ (scripts/gen-dose-ensdf.mjs --page),
  read as the page reads it (data.js, decay-names.js), in both systems.

      node resources/tests/dose_coefficients/test-decay-data.mjs

  For each release: the list of releases names it; every name of the
  system's own decay data finds its state but the isomers of less than a
  minute (which ENSDF's parents carry in their own decay); the swapped names
  of Ta-178 pair by half-life; the folder holds every daughter its records
  name; the catalogues have every nuclide they have with the system's own
  data; and a few dose coefficients, ICRP 103 and ICRP 60, stay close to
  those with the system's own decay data. About 20 s.
*/
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadSystem } from '../../js/dose/data.js';
import { catalog103, catalog60 } from '../../js/dose/catalog.js';
import { coefficients103 } from '../../js/dose/dose103.js';
import { coefficients60 } from '../../js/dose/dose60.js';
import { recipe60 } from '../../js/dose/model60.js';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DATA = path.resolve(HERE, '../../data/dose');
const io = (root) => ({
  json: async (p) => JSON.parse(fs.readFileSync(path.join(root, p), 'utf8')),
  bin: async (p) => { const b = fs.readFileSync(path.join(root, p)); return b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength); },
});
let pass = 0, fail = 0;
function check(label, ok, detail = '') {
  if (ok) { pass++; console.log(`ok    ${label}`); } else { fail++; console.log(`FAIL  ${label}${detail ? `\n      ${detail}` : ''}`); }
}

const list = JSON.parse(fs.readFileSync(path.join(DATA, 'ensdf/index.json'), 'utf8')).releases;
check(`releases offered: ${list.map((r) => r.label).join(', ')}`, list.length > 0 && list.every((r) => fs.existsSync(path.join(DATA, 'ensdf', r.id, 'decay/index.json'))));
const SHORT = /^(Ag-109m|Au-195m|Er-167m|Ir-191m|Se-77m|Y-89m|Nb-97m)$/; // IT isomers under a minute

for (const rel of list) {
  const folder = io(path.join(DATA, 'ensdf', rel.id));
  const raw = JSON.parse(fs.readFileSync(path.join(DATA, 'ensdf', rel.id, 'decay/index.json'), 'utf8'));
  check(`${rel.label}: the index names its release`, raw.label === rel.label && raw.release === rel.release);
  const missing = Object.values(raw.nuclides).flatMap((e) => e.d.map(([d]) => d)).filter((d) => d !== 'SF' && !raw.nuclides[d] && /[a-z]$/.test(d));
  check(`${rel.label}: every isomer a record decays to has its own record`, missing.length === 0, missing.slice(0, 10).join(', '));
  for (const sys of ['103', '60']) {
    const own = await loadSystem(sys, io(DATA)), other = await loadSystem(sys, io(DATA), folder);
    const lost = Object.keys(own.index).filter((n) => !other.index[n] && !SHORT.test(n));
    check(`ICRP ${sys} with ${rel.label}: every nuclide of ${own.decaySource.label} finds its state (but isomers under a minute)`, lost.length === 0, lost.join(', '));
    const ta = other.decaySource.renamed.find(([, page]) => page === 'Ta-178m');
    check(`... Ta-178m by half-life: ${ta ? `${rel.label}'s ${ta[0]}` : 'not renamed'}`, !!ta && Math.abs(Math.log(other.index['Ta-178m'].T / own.index['Ta-178m'].T)) < 0.1);
    const cat = (d) => (sys === '103' ? catalog103(d) : catalog60(d));
    const a = new Set(cat(own).nuclides.map((n) => n.name)), b = new Set(cat(other).nuclides.map((n) => n.name));
    // External exposure lists every radionuclide, so the catalogue has the isomers under a minute too.
    const gone = [...a].filter((n) => !b.has(n) && !SHORT.test(n));
    check(`... the catalogue keeps all ${a.size} nuclides but the isomers under a minute (${b.size} with ${rel.label})`, gone.length === 0, gone.join(', '));
    // A few coefficients: the adult's committed effective dose by ingestion, the default form.
    for (const [nuc, tol] of [['Cs-137', 0.01], ['I-131', 0.03], ['Sr-90', 0.01], ['Pb-212', 0.02], ['Ra-226', 0.03], ['Pu-239', 0.02], ['Am-241', 0.02]]) {
      const run = async (d) => {
        await d.prepare(nuc);
        if (sys === '103') {
          const el = d.elements[nuc.split('-')[0]];
          const form = (el.ingestion.find((f) => f.default) || el.ingestion[0]).id;
          return coefficients103(d, { nuclide: nuc, route: 'ingestion', form, cutoff: 1e-4 }, [7300])[0].E;
        }
        const entry = catalog60(d).nuclides.find((n) => n.name === nuc);
        const f = entry.ingestion[0];
        return coefficients60(d, recipe60(d.cases, 'ingestion', { nuclide: nuc, bio: f.spec.bio, f1file: f.spec.f1file }), [7300])[0].E;
      };
      const ea = await run(own), eb = await run(other);
      check(`... ${nuc}: adult ingestion ${eb.toExponential(3)} with ${rel.label}, ${ea.toExponential(3)} with ${own.decaySource.label} (within ${tol * 100} %)`, Math.abs(eb / ea - 1) <= tol);
    }
  }
}
console.log(`${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
