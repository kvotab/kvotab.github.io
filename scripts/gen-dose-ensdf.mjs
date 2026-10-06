#!/usr/bin/env node
/*
  Decay data for dose_coefficients.html from an ENSDF release, in the form
  of the ICRP 107 data it has built in (decay/index.json and decay/<El>.json,
  as scripts/gen-dose-icrp103.mjs writes them):

      node scripts/gen-dose-ensdf.mjs <ensdf_YYMMDD.zip | folder> OUTDIR [--min-isomer 60] [--page]

  --page writes only what dose_coefficients.html can reach, for the site
  (resources/data/dose/ensdf/<YYMMDD>): every state of at least 10 minutes,
  every state that takes the name of an ICRP 107 or ICRP 38 nuclide
  (decay-names.js), and the chains of those; and it enters the release in
  the list of those the page offers (index.json beside OUTDIR). Without it,
  every state.

  The making is resources/js/dose/ensdf-make.js, the module the page runs on
  a release a visitor opens: the processor of resources/js/dose
  (ensdf-release.js, ensdf-decay.js and the modules it uses: beta-spectrum.js,
  atomic-relax.js with the tables of resources/data/dose/atomic, ensdf-icc.js
  with icc/icc.json, ensdf-capture.js with capture.json, ensdf-fission.js).
  Every record's notes (modes estimated for want of a data set, and the
  like) go to OUTDIR/notes.json.
*/
import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { makeDecayData } from '../resources/js/dose/ensdf-make.js';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(import.meta.url);
const ENSDF = require(path.join(ROOT, 'resources/js/ensdf-parse.js'));
const DATA = path.join(ROOT, 'resources/data/dose');

const args = process.argv.slice(2);
const [src, OUT] = args.filter((a, i) => !a.startsWith('--') && !(i > 0 && args[i - 1].startsWith('--')));
if (!src || !OUT) {
  console.error('usage: node scripts/gen-dose-ensdf.mjs <ensdf_YYMMDD.zip | folder> OUTDIR [--min-isomer 60] [--page]');
  process.exit(2);
}
const opt = (k, d) => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : d; };
const page = args.includes('--page');

/* The release's files, one at a time, as often as they are asked for. */
function* releaseTexts(p) {
  if (fs.statSync(p).isDirectory()) {
    for (const f of fs.readdirSync(p).filter((x) => /^ensdf\.\d{3}$/i.test(x)).sort()) yield { name: f, text: fs.readFileSync(path.join(p, f), 'latin1') };
    return;
  }
  const bytes = new Uint8Array(fs.readFileSync(p));
  for (const e of ENSDF.zipEntries(bytes).filter((x) => ENSDF.isEnsdfName(x.name)).sort((a, b) => a.name.localeCompare(b.name))) {
    const raw = bytes.subarray(e.offset, e.offset + e.csize);
    yield { name: e.name, text: new TextDecoder('latin1').decode(e.method === 0 ? raw : zlib.inflateRawSync(raw)) };
  }
}

const json = (f) => JSON.parse(fs.readFileSync(f, 'utf8'));
const id = /(\d{6})/.exec(path.basename(src))?.[1] || path.basename(src);
const label = /^\d{6}$/.test(id) ? `ENSDF 20${id.slice(0, 2)}-${id.slice(2, 4)}-${id.slice(4, 6)}` : `ENSDF ${id}`;
const made = await makeDecayData({
  texts: () => releaseTexts(src),
  ENSDF,
  tables: {
    atomic: (sym) => { const f = path.join(DATA, 'atomic', `${sym}.json`); return fs.existsSync(f) ? json(f) : null; },
    icc: json(path.join(DATA, 'icc/icc.json')),
    capture: json(path.join(DATA, 'capture.json')),
  },
  own: page ? { icrp103: json(path.join(DATA, 'icrp103/decay/index.json')).nuclides, icrp60: json(path.join(DATA, 'icrp60/decay/index.json')).nuclides } : null,
  page,
  minIsomer: Number(opt('--min-isomer', 60)),
  release: { id, label, source: `ENSDF release ${id} (${path.basename(src)}), processed by resources/js/dose/ensdf-release.js` },
});

fs.mkdirSync(path.join(OUT, 'decay'), { recursive: true });
fs.writeFileSync(path.join(OUT, 'decay/index.json'), JSON.stringify(made.index));
let bytes = 0;
for (const [el, obj] of Object.entries(made.elements)) { const f = path.join(OUT, `decay/${el}.json`); fs.writeFileSync(f, JSON.stringify(obj)); bytes += fs.statSync(f).size; }
fs.writeFileSync(path.join(OUT, 'notes.json'), JSON.stringify(made.notes, null, 1));
if (page) {
  // The releases the page offers, newest first.
  const list = path.join(OUT, '..', 'index.json');
  const have = fs.existsSync(list) ? json(list).releases : [];
  const entry = { id: path.basename(path.resolve(OUT)), label, release: id, nuclides: made.stats.kept };
  const releases = [entry, ...have.filter((r) => r.id !== entry.id)].sort((a, b) => b.id.localeCompare(a.id));
  fs.writeFileSync(list, JSON.stringify({ releases }, null, 1) + '\n');
}
const { ms } = made.stats;
console.log(`${made.stats.kept} of ${made.stats.states} nuclides, ${Object.keys(made.elements).length} elements, ${(bytes / 1e6).toFixed(1)} MB; `
  + `read ${ms.read} ms, made ${ms.make} ms; ${Object.keys(made.notes).length} with notes`);
