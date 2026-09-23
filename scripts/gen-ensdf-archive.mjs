#!/usr/bin/env node
/*
  List the ENSDF releases in the NNDC archive, for ensdf.html's database menu.

      node scripts/gen-ensdf-archive.mjs              # fetch the index from NNDC
      node scripts/gen-ensdf-archive.mjs files.json   # or read a saved copy

  NNDC keeps every release since 2004 at https://www.nndc.bnl.gov/ensdfarchivals/,
  indexed by distributions/files.json. The page cannot read that index, or the
  zips, itself -- NNDC's server sends no CORS header -- so this script takes a
  copy of the list, and the page offers each release with a link to download
  it and a way to open the download. Run it again, as gen-ensdf.mjs is run,
  when a new release comes out.

  Writes resources/data/ensdf/nndc.js, one call:

      KVOT_ENSDF_DATA("*", "nndc", {fetched, page, base, releases: [
        {id: "260901", label: "ENSDF 2026-09-01", files: ["dist26/ensdf_260901.zip"]},
        {id: "120307", label: "ENSDF 2012-03-07",
         files: ["dist12/ensdf_120307_099.zip", "dist12/ensdf_120307_199.zip", "dist12/ensdf_120307_299.zip"],
         parts: ["1-99", "100-199", "200-299"]},
        ...]})

  newest first, with the files relative to `base`. Only whole releases: until
  2021 NNDC published each one in parts by mass number (_099, _199, _299 --
  in 2004 _070, _130, _180, _293), since 2022 as one zip. Left out are the
  _upd zips (the changes since the release before, not a database), XUNDL
  (unevaluated data) and the loose .upd files. A release NNDC lists without
  one of its parts is marked `missing` with the mass numbers it lacks.
*/
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const OUT = path.join(ROOT, 'resources/data/ensdf/nndc.js');
const PAGE = 'https://www.nndc.bnl.gov/ensdfarchivals/';
const INDEX = `${PAGE}distributions/files.json`;

const index = process.argv[2]
  ? JSON.parse(fs.readFileSync(process.argv[2], 'utf8'))
  : await fetch(INDEX).then((r) => {
    if (!r.ok) throw new Error(`${INDEX}: HTTP ${r.status}`);
    return r.json();
  });

/* ensdf_YYMMDD.zip, ensdf_YYMMDD_099.zip, ENSDF_YYMM_099.zip */
const NAME = /^ensdf_(\d{4}|\d{6})(?:_(\d{3}))?\.zip$/i;
const groups = new Map();
for (const { year, files } of index.distributions || []) {
  for (const file of files || []) {
    const m = NAME.exec(file);
    if (!m) continue;
    const [, date, part] = m;
    const month = +date.slice(2, 4);
    if (month < 1 || month > 12) continue;
    if (!groups.has(date)) groups.set(date, { date, whole: [], parts: [] });
    const g = groups.get(date);
    const rel = `dist${String(year).slice(2)}/${file}`;
    if (part) g.parts.push({ top: +part, rel });
    else g.whole.push(rel);
  }
}

const releases = [];
for (const g of groups.values()) {
  const { date } = g;
  const label = `ENSDF 20${date.slice(0, 2)}-${date.slice(2, 4)}${date.length === 6 ? `-${date.slice(4, 6)}` : ''}`;
  if (g.whole.length) {
    /* A release published whole (2009-10 has both): the one zip is enough. */
    releases.push({ id: date, label, files: [g.whole[0]] });
    continue;
  }
  if (!g.parts.length) continue;
  const parts = g.parts.sort((p, q) => p.top - q.top);
  /* Each part runs on from the one before (the 2004 parts are 70, 60, 50 and
     113 masses wide, the later ones 99, 100 and 100), so one that ends more
     than 115 past the last mass covered has lost the part before it, and
     starts at its own hundred: _199 at 100, _300 at 200. */
  const ranges = [];
  const missing = [];
  let next = 1;
  for (const p of parts) {
    const from = p.top - (next - 1) > 115 ? Math.max(next, p.top % 100 ? p.top - 99 : p.top - 100) : next;
    if (from > next) missing.push(`${next}-${from - 1}`);
    ranges.push(`${from}-${p.top}`);
    next = p.top + 1;
  }
  if (next <= 290) missing.push(`${next}-`);
  const entry = { id: date, label, files: parts.map((p) => p.rel), parts: ranges };
  if (missing.length) entry.missing = missing;
  releases.push(entry);
}
/* Newest first; a YYMM release sorts as the first of its month. */
const key = (r) => (r.id.length === 6 ? r.id : `${r.id}01`);
releases.sort((p, q) => key(q).localeCompare(key(p)));

/* One release a line: small to load, and a new release is a one-line diff. */
const head = JSON.stringify({ fetched: new Date().toISOString().slice(0, 10), page: PAGE, base: `${PAGE}distributions/` }).slice(0, -1);
fs.writeFileSync(OUT, `KVOT_ENSDF_DATA("*","nndc",${head},"releases":[\n${releases.map((r) => JSON.stringify(r)).join(',\n')}\n]});\n`);
const split = releases.filter((r) => r.parts).length;
const partial = releases.filter((r) => r.missing);
console.log(`nndc.js lists ${releases.length} releases, ${releases[0].label} to ${releases[releases.length - 1].label}; ${split} in parts`);
for (const r of partial) console.log(`  ${r.label} lacks A = ${r.missing.join(', ')}`);
