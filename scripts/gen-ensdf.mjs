#!/usr/bin/env node
/*
  Build the ENSDF release that ships with ensdf.html.

      node scripts/gen-ensdf.mjs ~/Downloads/ensdf_260901.zip

  Reads an ENSDF distribution as NNDC publishes it (a zip of ensdf.001 ...
  ensdf.300, from https://www.nndc.bnl.gov/ensdfarchivals/) with the same
  reader the page uses, resources/js/ensdf-parse.js, and writes

      resources/data/ensdf/<id>/summary.js     every nuclide, for the chart
      resources/data/ensdf/<id>/a/<AAA>.js     levels, gammas, data sets and
                                               radiation, one file per mass
      resources/data/ensdf/releases.js         the built-in releases, newest
                                               first; the page opens the first

  <id> is the YYMMDD in the file name. The data files are scripts rather than
  JSON so the page also works opened from the file system, where fetch() of a
  local file is refused but a <script> is not. Each one is a single call,
  KVOT_ENSDF_DATA(id, part, payload).

  Run it again with another release to add that one; the page's database
  menu lists every release found under resources/data/ensdf/. Remove a
  release by deleting its directory and re-running with any zip, or by
  editing releases.js.
*/
import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(import.meta.url);
const ENSDF = require(path.join(ROOT, 'resources/js/ensdf-parse.js'));
const OUT = path.join(ROOT, 'resources/data/ensdf');

const zipPath = process.argv[2];
if (!zipPath) {
  console.error('usage: node scripts/gen-ensdf.mjs <ensdf_YYMMDD.zip>');
  process.exit(2);
}
const base = path.basename(zipPath);
const m = /(\d{6})/.exec(base);
if (!m) {
  console.error(`cannot tell the release date from "${base}": expected ensdf_YYMMDD.zip`);
  process.exit(2);
}
const id = m[1];
const label = `ENSDF 20${id.slice(0, 2)}-${id.slice(2, 4)}-${id.slice(4, 6)}`;

const bytes = new Uint8Array(fs.readFileSync(zipPath));
const entries = ENSDF.zipEntries(bytes).filter((e) => ENSDF.isEnsdfName(e.name)).sort((p, q) => p.name.localeCompare(q.name));
if (!entries.length) {
  console.error('no ENSDF files in the archive');
  process.exit(1);
}
const builder = ENSDF.createBuilder();
const t0 = Date.now();
for (const e of entries) {
  const raw = bytes.subarray(e.offset, e.offset + e.csize);
  const data = e.method === 0 ? raw : zlib.inflateRawSync(raw);
  builder.addText(new TextDecoder('latin1').decode(data));
}
const { summary, details } = builder.finish({ id, label, source: base, built: new Date().toISOString().slice(0, 10) });
console.log(`${label}: ${summary.release.nuclides} nuclides, ${summary.release.states} states, ${summary.release.datasets} data sets (${Date.now() - t0} ms)`);

const dir = path.join(OUT, id);
fs.rmSync(dir, { recursive: true, force: true });
fs.mkdirSync(path.join(dir, 'a'), { recursive: true });
const call = (part, payload) => `KVOT_ENSDF_DATA(${JSON.stringify(id)},${JSON.stringify(part)},${JSON.stringify(payload)});\n`;
fs.writeFileSync(path.join(dir, 'summary.js'), call('summary', summary));
let bytesOut = 0;
for (const [a, d] of details) {
  const text = call(`a${a}`, d);
  bytesOut += text.length;
  fs.writeFileSync(path.join(dir, 'a', `${String(a).padStart(3, '0')}.js`), text);
}
console.log(`wrote ${path.relative(ROOT, dir)}: summary ${(fs.statSync(path.join(dir, 'summary.js')).size / 1e6).toFixed(2)} MB, details ${(bytesOut / 1e6).toFixed(1)} MB in ${details.size} files`);

/* The manifest: every release directory, newest first. */
const releases = fs.readdirSync(OUT)
  .filter((d) => /^\d{6}$/.test(d) && fs.existsSync(path.join(OUT, d, 'summary.js')))
  .sort().reverse()
  .map((d) => {
    const text = fs.readFileSync(path.join(OUT, d, 'summary.js'), 'utf8');
    const json = JSON.parse(text.slice(text.indexOf(',{') + 1, text.lastIndexOf(')')));
    const r = json.release;
    return { id: d, label: r.label || d, source: r.source || '', nuclides: r.nuclides, datasets: r.datasets, newest: r.newest };
  });
fs.writeFileSync(path.join(OUT, 'releases.js'), `KVOT_ENSDF_DATA("*","releases",${JSON.stringify(releases, null, 1)});\n`);
console.log(`releases.js lists ${releases.map((r) => r.id).join(', ')}`);
