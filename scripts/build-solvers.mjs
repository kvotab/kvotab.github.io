#!/usr/bin/env node
/*
  Build every solver package into the two forms its users need.

      node scripts/build-solvers.mjs            # write
      node scripts/build-solvers.mjs --check    # write nothing; exit 1 if anything is stale

  Each package is written once, as ES modules under resources/js/ode/ (the
  NDF and its linear algebra in core/ and solvers/, the ported solvers in
  julia/), and that is the source of truth. Two things are made from it:

  - a single-file build for a plain <script> tag and a classic worker.
    facsimile.html and rtm.html run their solver in a classic worker with an
    inline fallback -- a classic worker starts in more browsers, and a file://
    visit has no worker at all -- so they cannot import ES modules. The build
    concatenates the modules in dependency order, strips the import and export
    keywords and wraps the result in the site's UMD preamble. Nothing is
    minified or rewritten: the bundle is the sources with two kinds of line
    removed, so a stack trace from it still reads.

  - an identical copy inside kompartment/src/ode/, at the same relative paths,
    since Kompartment is self-contained by design: no build step, and servable
    from its own folder, so it cannot reach up into resources/js/. Its copy is
    the same bytes, and --check fails the moment it is edited by hand.

  It refuses to build if two modules of a package declare the same top-level
  name, which concatenation would otherwise turn into a syntax error or, worse,
  a silent redefinition.
*/
import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const CHECK = process.argv.includes('--check');

const PACKAGES = [
	{
		name: 'ode',
		src: 'resources/js/ode',
		bundle: 'resources/js/ode-core.js',
		global: 'OdeCore',
		files: ['core/linalg.js', 'core/refactor.js', 'core/sparse.js', 'core/events.js', 'solvers/ndf.js'],
		exports: [
			'EPS', 'zeros', 'identity', 'norm', 'LU', 'DenseLU', 'createMiter',
			'RefactorLU', 'PIVOT_THRESHOLD', 'KEEP_THRESHOLD', 'OPS_BUDGET',
			'CSC', 'cscTranspose', 'cscFromTriplets', 'cscToDense', 'cscMulVec', 'sparseMatVec',
			'makeMiterBuilder', 'SparseLU', 'reverseCuthillMcKee', 'reverseCuthillMcKeeOrder',
			'colourColumns', 'differenceIncrement', 'differenceJacobian',
			'DENSE_MAX_BYTES', 'DENSE_BELOW', 'DENSE_FILL',
			'iterationMatrix', 'makeIterationMatrix', 'sparseIterationMatrix',
			'crosses', 'anyCrossing', 'crossingTolerance', 'firstCrossing', 'locateCrossing',
			'ndf', 'SolverError', 'NdfFailure', 'MAX_ORDER',
		],
		// The same relative paths in Kompartment's src/ode/, whose core/ and
		// solvers/ also hold Kompartment's own driver and solvers beside these.
		// The five modules are the same bytes; index.js and the README stay here.
		copyTo: 'kompartment/src/ode',
		copy: [],
		describe: `ode/core and ode/solvers -- a single-file build

   The stiff-solver core of facsimile.html, rtm.html and Kompartment: the
   variable-order NDF/BDF integrator, the dense, sparse and kept-pivot LUs of
   its iteration matrix and the choice between them, column colouring and
   differenced Jacobians, and event location. No dependencies.

     const { ndf } = OdeCore;
     const res = ndf((t, y, out) => { out[0] = -y[0]; return out; },
                     [0, 1, 2], Float64Array.of(1), { rtol: 1e-8, abstol: 1e-12 });`,
	},
	{
		name: 'ode_julia',
		src: 'resources/js/ode/julia',
		bundle: 'resources/js/ode-julia.js',
		global: 'OdeJulia',
		// Dependency order. Checked: a module may only use names already defined.
		files: [
			'core/linalg.js',
			'core/jacobian.js',
			'core/newton.js',
			'core/controller.js',
			'core/integrator.js',
			'solvers/rodas5p-tableau.js',
			'solvers/rosenbrock.js',
			'solvers/esdirk-tableaus.js',
			'solvers/esdirk.js',
			'solvers/fbdf.js',
			'solvers/qndf.js',
			'solvers/radau-tableau.js',
			'solvers/radau.js',
		],
		// What the bundle puts on the global. Kept in step with index.js by the
		// check below, which fails if index.js exports a name this list does not.
		exports: [
			'ODEProblem', 'ODESolution', 'ODEError', 'solve',
			'Success', 'MaxIters', 'DtLessThanMin', 'Unstable', 'Terminated',
			'DenseMatrix', 'CSC', 'cscFromTriplets', 'DenseLU', 'ComplexDenseLU', 'SparseLU',
			'reverseCuthillMcKee',
			'JacobianCache', 'WFactorization', 'colourColumns', 'densePattern',
			'NewtonSolver', 'PIController', 'initialStep',
			'Rodas5P', 'rosenbrockAlgorithm', 'Rodas5PTableau',
			'TRBDF2', 'KenCarp4', 'esdirkAlgorithm', 'TRBDF2Tableau', 'KenCarp4Tableau',
			'FBDF', 'fornbergWeights',
			'QNDF', 'QBDF', 'rescaleMatrix',
			'RadauIIA5', 'RadauIIA5Tableau',
		],
		copyTo: 'kompartment/src/ode/julia',
		// Kompartment keeps its own README (its paths are its own); everything
		// that runs is the same bytes.
		copy: ['index.js', 'LICENSE'],
		describe: `ode_julia -- a single-file build

   Stiff ODE solvers ported from DifferentialEquations.jl -- FBDF, Rodas5P,
   KenCarp4, TRBDF2 and RadauIIA5 -- with their linear algebra, Jacobian
   handling, Newton iteration and step-size control. No dependencies.

     const { solve, ODEProblem, FBDF } = OdeJulia;
     const sol = solve(new ODEProblem(f, u0, [0, 1e5], { jac }), FBDF(),
                       { reltol: 1e-8, abstol: 1e-12 });`,
	},
];

const IMPORT_RE = /^import\s[\s\S]*?from\s+'[^']+';\s*$/gm;
const TOPLEVEL_RE = /^export\s+(?:default\s+)?(class|function|const|let|var)\s+([A-Za-z_$][\w$]*)/gm;
const PLAIN_TOPLEVEL_RE = /^(?:class|function|const|let|var)\s+([A-Za-z_$][\w$]*)/gm;

let stale = 0;
let failed = 0;

/** Writes `text` to `rel`, or in --check says whether it would have changed. */
function emit(rel, text) {
	const path = join(ROOT, rel);
	const now = existsSync(path) ? readFileSync(path, 'utf8') : null;
	if (now === text) return;
	if (CHECK) {
		console.error(`stale: ${rel} is not what its sources build to`);
		stale++;
		return;
	}
	mkdirSync(dirname(path), { recursive: true });
	writeFileSync(path, text);
	console.log(`wrote ${rel}`);
}

function bundle(pkg) {
	const seen = new Map();
	const register = (name, rel) => {
		if (seen.has(name) && seen.get(name) !== rel) {
			console.error(`${pkg.name}: duplicate top-level name "${name}" in ${rel} and ${seen.get(name)}`);
			failed++;
		}
		seen.set(name, rel);
	};
	const chunks = [];
	for (const rel of pkg.files) {
		const raw = readFileSync(join(ROOT, pkg.src, rel), 'utf8');
		for (const m of raw.matchAll(TOPLEVEL_RE)) register(m[2], rel);
		for (const m of raw.matchAll(PLAIN_TOPLEVEL_RE)) register(m[1], rel);
		let body = raw.replace(IMPORT_RE, '');
		// `export class X` -> `class X`; a bare `export { ... };` line disappears.
		body = body.replace(/^export\s+(?=(class|function|const|let|var)\s)/gm, '');
		body = body.replace(/^export\s*\{[^}]*\}\s*;?\s*$/gm, '');
		chunks.push(`/* ---------- ${rel} ---------- */\n${body.trim()}\n`);
	}

	// Everything index.js exports must be reachable and must be on the global.
	const index = readFileSync(join(ROOT, pkg.src, 'index.js'), 'utf8');
	const exported = new Set();
	for (const m of index.matchAll(/^export\s*\{([^}]*)\}/gm)) {
		for (const raw of m[1].split(',')) {
			const name = raw.trim().split(/\s+as\s+/).pop().trim();
			if (name) exported.add(name);
		}
	}
	for (const name of exported) {
		if (!pkg.exports.includes(name)) { console.error(`${pkg.name}: index.js exports ${name}, the bundle does not`); failed++; }
		if (!seen.has(name)) { console.error(`${pkg.name}: index.js exports ${name}, no module declares it`); failed++; }
	}
	for (const name of pkg.exports) {
		if (!seen.has(name)) { console.error(`${pkg.name}: the bundle exports ${name}, no module declares it`); failed++; }
	}

	const header = `/* ==========================================================================
   ${pkg.describe}

   GENERATED by scripts/build-solvers.mjs from ${pkg.src}/.
   Do not edit: edit the modules and run the script. The modules are the
   source of truth and are what to read; this file exists because a page that
   must also work with no Web Worker cannot use ES modules for everything.
   ========================================================================== */
(function (root, factory) {
  const api = factory();
  root.${pkg.global} = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

`;
	const footer = `
  return { ${pkg.exports.join(', ')} };
}));
`;
	const body = chunks.join('\n').split('\n').map((l) => (l ? `  ${l}` : l)).join('\n');
	return header + body + footer;
}

for (const pkg of PACKAGES) {
	const text = bundle(pkg);
	if (failed) break;
	emit(pkg.bundle, text);
	for (const rel of [...pkg.files, ...pkg.copy]) {
		emit(join(pkg.copyTo, rel), readFileSync(join(ROOT, pkg.src, rel), 'utf8'));
	}
}

if (failed) process.exit(1);
if (CHECK) {
	if (stale) process.exit(1);
	console.log(`up to date: ${PACKAGES.map((p) => p.name).join(', ')}`);
}
