#!/usr/bin/env node
/*
  Writes the data the Python package reads, from the application's own
  modules, so the two cannot drift apart:

      node kompartment/python/tools/gen_data.mjs          # write
      node kompartment/python/tools/gen_data.mjs --check  # exit 1 if stale

  kompartment/data/icrp107.json   the ICRP 107 decay database: every nuclide's
                                  half-life in years (null for stable) and
                                  its daughters with their branching ratios.
                                  What `half_life_of` and the default decay
                                  chains are worked out from.
  kompartment/data/reserved.json  the names no block may take -- the
                                  functions an equation can call, and the
                                  words the language keeps -- exactly
                                  Kompartment's RESERVED set.

  The Python test suite runs this with --check, so a change to either table
  in the application fails there until the data is written again.
*/
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const SRC = join(HERE, '..', '..', 'src');
const OUT = join(HERE, '..', 'kompartment', 'data');
const CHECK = process.argv.includes('--check');

const { ICRP107 } = await import(join(SRC, 'domain', 'icrp107.js'));
const { RESERVED } = await import(join(SRC, 'domain', 'names.js'));

const files = {
	'icrp107.json': JSON.stringify({
		source: 'ICRP Publication 107, Nuclear Decay Data for Dosimetric Calculations '
			+ '(Annals of the ICRP 38(3), 2008), as Kompartment carries it in '
			+ 'src/domain/icrp107.js. Half-lives in years; null is stable.',
		// One row per nuclide, in the database's own order (by Z, then A):
		// [name, half-life, [[daughter, branching], ...]].
		nuclides: ICRP107.map(([name, , , halfLife, , progeny]) => [
			name,
			Number.isFinite(halfLife) ? halfLife : null,
			progeny.map(([daughter, branching]) => [daughter, branching]),
		]),
	}) + '\n',
	'reserved.json': JSON.stringify({
		source: "Kompartment's RESERVED set, src/domain/names.js.",
		names: [...RESERVED].sort(),
	}, null, 1) + '\n',
};

let stale = 0;
mkdirSync(OUT, { recursive: true });
for (const [name, text] of Object.entries(files)) {
	const path = join(OUT, name);
	let had = null;
	try { had = readFileSync(path, 'utf8'); } catch { /* not written yet */ }
	if (had === text) { console.log(`up to date: ${name}`); continue; }
	if (CHECK) { console.log(`STALE: ${name}`); stale++; continue; }
	writeFileSync(path, text);
	console.log(`wrote ${name} (${text.length.toLocaleString()} bytes)`);
}
process.exit(stale ? 1 : 0);
