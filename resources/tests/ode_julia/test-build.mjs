// The single-file builds and Kompartment's copies are what their sources build to.
//
//     node resources/tests/ode_julia/test-build.mjs
//
// scripts/build-solvers.mjs --check rebuilds every solver package in memory and
// compares: a bundle edited by hand, a copy in kompartment/ edited by hand, or a
// module changed without rebuilding all fail here.
import { spawnSync } from 'node:child_process';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..');
const r = spawnSync(process.execPath, [join(ROOT, 'scripts/build-solvers.mjs'), '--check'], { encoding: 'utf8' });
process.stdout.write(r.stdout);
process.stderr.write(r.stderr);
if (r.status === 0) console.log('1 of 1 checks passed');
else { console.log('0 of 1 checks passed'); process.exit(1); }
