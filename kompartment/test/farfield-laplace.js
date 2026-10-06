/**
 * The semi-analytical far-field path (../src/domain/farfield-laplace.js)
 * against what it has to reproduce.
 *
 *   - FARF31.html's model on its own cases, and the independent 40-digit
 *     solution of TR 90-01's recursion those cases carry
 *     (resources/tests/farf31/ref/mpmath-ref.json), including its made-up
 *     chain with sorption on the fracture surfaces;
 *   - closed forms: without a matrix the inverse Gaussian in t/Rf; under plug
 *     flow with an unlimited matrix the classical solution delayed by Rf TW;
 *     at finite Pe with an unlimited matrix the subordination integral; what
 *     the path holds in the first two;
 *   - the Bateman solution for nuclides that move alike, on a branched network
 *     that merges again, listed out of order, in amounts and in activities;
 *   - the mass balance: T(0) columns, integrals of responses, k' = -Lambda k -
 *     h, and the inventory against the integrated fluxes;
 *   - Kompartment's own discretised block, refined towards it;
 *   - species that do not decay, the three ways of giving the wetted surface,
 *     and the settings the method refuses.
 *
 * Every number in here is made up.
 *
 *   node test/farfield-laplace.js      everything, the long comparison with
 *                                      the discretised block included
 *   node test/run.js semi-analytical   the part the suite runs
 */

import { readFileSync, existsSync } from 'node:fs';
import os from 'node:os';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';
import * as L from '../src/domain/farfield-laplace.js';
import { run } from '../src/sim/runner.js';
import { runProbabilistic } from '../src/sim/probabilistic.js';
import { Project } from '../src/domain/project.js';

/** [name, fn] for the suite; the slow ones only when run on their own. */
export const TESTS = [];
const SLOW = [];
const test = (name, fn) => TESTS.push([`semi-analytical path: ${name}`, fn]);
const slow = (name, fn) => SLOW.push([`semi-analytical path: ${name}`, fn]);

const LN2 = Math.LN2;
const HERE = fileURLToPath(new URL('.', import.meta.url));
const REPO = `${HERE}../../`;

function assert(cond, msg) {
	if (!cond) throw new Error(msg ?? 'assertion failed');
}

function below(err, tol, what) {
	assert(err <= tol, `${what}: ${err.toExponential(2)} > ${tol.toExponential(0)}`);
}

const logGrid = (a, b, n) => Array.from({ length: n }, (_, k) => a * (b / a) ** (k / (n - 1)));

/** The largest relative error where the wanted value exceeds `frac` of its largest. */
function worstRel(ts, got, want, frac = 1e-6) {
	let pk = 0;
	for (const v of want) pk = Math.max(pk, Math.abs(v));
	let w = 0;
	ts.forEach((t, k) => {
		if (Math.abs(want[k]) > frac * pk) w = Math.max(w, Math.abs(got[k] - want[k]) / Math.abs(want[k]));
	});
	return w;
}

/** e^(x^2) erfc(x) for x >= 0: Numerical Recipes' Chebyshev fit, to rounding. */
function erfcx(x) {
	const t = 2 / (2 + x);
	const ty = 4 * t - 2;
	const cof = [
		-1.3026537197817094, 6.4196979235649026e-1, 1.9476473204185836e-2, -9.561514786808631e-3,
		-9.46595344482036e-4, 3.66839497852761e-4, 4.2523324806907e-5, -2.0278578112534e-5,
		-1.624290004647e-6, 1.303655835580e-6, 1.5626441722e-8, -8.5238095915e-8, 6.529054439e-9,
		5.059343495e-9, -9.91364156e-10, -2.27365122e-10, 9.6467911e-11, 2.394038e-12, -6.886027e-12,
		8.94487e-13, 3.13092e-13, -1.12708e-13, 3.81e-16, 7.106e-15,
	];
	let d = 0;
	let dd = 0;
	for (let j = cof.length - 1; j > 0; j--) {
		const tmp = d;
		d = ty * d - dd + cof[j];
		dd = tmp;
	}
	return t * Math.exp(0.5 * (cof[0] + ty * d) - dd);
}
const erfc = (x) => (x >= 0 ? erfcx(x) * Math.exp(-x * x) : 2 - erfcx(-x) * Math.exp(-x * x));

/** The inverse Gaussian: the flux-in, flux-out response of advection and dispersion. */
const ig = (t, tw, Pe) => Math.sqrt(Pe * tw / (4 * Math.PI * t ** 3)) * Math.exp(-Pe * (tw - t) ** 2 / (4 * tw * t));

/** Its survival function, 1 - F(x): what is still upstream of the outlet. */
function igSurvival(x, tw, Pe) {
	const r = Math.sqrt(Pe * tw / (2 * x));
	const a = r * (x / tw - 1);
	const b = r * (x / tw + 1);
	return 0.5 * erfc(a / Math.SQRT2) - 0.5 * erfcx(b / Math.SQRT2) * Math.exp(Pe - b * b / 2);
}

/** Diffusion into an unlimited matrix under plug flow: u after the front, k = TW aw sqrt(De Rm). */
const neret = (u, k) => (u > 0 ? k / (2 * Math.sqrt(Math.PI) * u ** 1.5) * Math.exp(-k * k / (4 * u)) : 0);

/** Adaptive Gauss-Kronrod (7-15). */
function quad(f, a, b, tol = 1e-12, depth = 0) {
	const xk = [0.991455371120813, 0.949107912342759, 0.864864423359769, 0.741531185599394, 0.586087235467691, 0.405845151377397, 0.207784955007898, 0];
	const wk = [0.022935322010529, 0.063092092629979, 0.104790010322250, 0.140653259715525, 0.169004726639267, 0.190350578064785, 0.204432940075298, 0.209482141084728];
	const wg = [0, 0.129484966168870, 0, 0.279705391489277, 0, 0.381830050505119, 0, 0.417959183673469];
	const c = 0.5 * (a + b);
	const h = 0.5 * (b - a);
	let K = 0;
	let G = 0;
	for (let q = 0; q < 8; q++) {
		const s = q === 7 ? f(c) : f(c - h * xk[q]) + f(c + h * xk[q]);
		K += wk[q] * s;
		G += wg[q] * s;
	}
	K *= h;
	G *= h;
	if (Math.abs(K - G) <= tol * Math.abs(K) + 1e-300 || depth > 40) return K;
	return quad(f, a, c, tol, depth + 1) + quad(f, c, b, tol, depth + 1);
}

/** e^(-Lambda t) for a dense Lambda, by scaling and squaring a Taylor series:
    independent of the matrix functions under test, and indifferent to equal
    decay constants. */
function expm(Lam, t) {
	const n = Lam.length;
	const A = Lam.map((r) => r.map((v) => -v * t));
	let nrm = 0;
	for (const r of A) nrm = Math.max(nrm, r.reduce((s, v) => s + Math.abs(v), 0));
	const sq = Math.max(0, Math.ceil(Math.log2(nrm + 1e-300)) + 4);
	const B = A.map((r) => r.map((v) => v * 2 ** -sq));
	const mul = (X, Y) => X.map((r, p) => r.map((_, q) => {
		let s = 0;
		for (let k = 0; k < n; k++) s += X[p][k] * Y[k][q];
		return s;
	}));
	let E = B.map((r, p) => r.map((_, q) => (p === q ? 1 : 0)));
	let term = E.map((r) => r.slice());
	for (let k = 1; k < 30; k++) {
		term = mul(term, B).map((r) => r.map((v) => v / k));
		E = E.map((r, p) => r.map((v, q) => v + term[p][q]));
	}
	for (let k = 0; k < sq; k++) E = mul(E, E);
	return E;
}

/** A single species with no decay table: what the path does to anything. */
const single = (set, lam = 0) => L.preparePath(set, lam ? L.decayTable([lam]) : null, { n: 1 });

/**
 * A branched network that merges again, listed out of order, with a stable
 * end: P decays into A (0.7) and B (0.3), both into D, D into S. `unit` says
 * which decay constant the ingrowth coefficient carries, as the builder does:
 * the parent's for amounts, the daughter's for activities.
 */
function network(halfLives, unit = 'mol') {
	const canon = ['P', 'A', 'B', 'D', 'S'];
	const list = ['D', 'P', 'S', 'B', 'A'];
	const idx = Object.fromEntries(list.map((x, k) => [x, k]));
	const lam = list.map((x) => {
		const th = halfLives[canon.indexOf(x)];
		return Number.isFinite(th) ? LN2 / th : 0;
	});
	const links = [['P', 'A', 0.7], ['P', 'B', 0.3], ['A', 'D', 1], ['B', 'D', 1], ['D', 'S', 1]];
	const pairs = links.map(([p, d, b]) => [idx[p], idx[d], b * (unit === 'mol' ? lam[idx[p]] : lam[idx[d]])]);
	const Lam = list.map((_, i) => list.map((__, j) => (i === j ? lam[i] : 0)));
	for (const [p, d, c] of pairs) Lam[d][p] -= c;
	return { list, idx, lam, pairs, Lam, decay: L.decayTable(lam, pairs) };
}

// ---------------------------------------------------------------------------
// FARF31.html's model and its 40-digit references
// ---------------------------------------------------------------------------

const PAGE_MODEL = `${REPO}resources/js/farf31-model.js`;
const REFERENCE = `${REPO}resources/tests/farf31/ref/mpmath-ref.json`;

/** One of the page's cases as a path: its `input`, as the page's run() takes it. */
function pageCase(input) {
	const { params: p, nuclides: nucs } = input;
	const lam = nucs.map((x) => (Number.isFinite(x.thalf) ? LN2 / x.thalf : 0));
	const pairs = [];
	nucs.forEach((x, q) => { if (x.daughter) pairs.push([q, q + 1, lam[q]]); });
	return L.preparePath({
		surface: 'aw', aw: p.aw, tw: p.tw, rho_m: p.rho ?? 2700, pe: p.Pe, pen_dep: p.x0,
		kd_f: nucs.map((x) => x.ka ?? 0), eps_m: p.eps, kd_m: nucs.map((x) => x.kd), de_m: nucs.map((x) => x.de),
	}, L.decayTable(lam, pairs), { names: nucs.map((x) => x.name) });
}

test('T(s) is the page model’s on its chain, element by element', () => {
	if (!existsSync(PAGE_MODEL)) return;
	const M = createRequire(import.meta.url)(PAGE_MODEL);
	const c = {
		tw: 150, Pe: 15, aw: 800, eps: 0.005, x0: 1.5, nuclides: [
			{ name: 'Am241', thalf: 432.6, kd: 2.0, de: 4e-6, daughter: true },
			{ name: 'Np237', thalf: 2.144e6, kd: 0.1, de: 5e-6, daughter: true },
			{ name: 'U233', thalf: 1.592e5, kd: 0.05, de: 3e-6, daughter: true },
			{ name: 'Th229', thalf: 7340, kd: 1.0, de: 6e-6 },
		],
	};
	const ctx = M.prepare(c);
	const ws = M.makeWorkspace(ctx);
	const path = pageCase({ params: c, nuclides: c.nuclides });
	let worst = 0;
	for (const [sr, si] of [[1e-3, 2e-3], [5e-6, 1e-5], [-2e-7, 3e-6], [0.02, -0.05]]) {
		for (let j = 0; j < 4; j++) {
			for (let i = j; i < 4; i++) {
				const a = M.transfer(ctx, ws, sr, si, i, j);
				const b = L.transfer(path, sr, si, i, j);
				if (Math.hypot(a[0], a[1]) > 1e-250) {
					worst = Math.max(worst, Math.hypot(a[0] - b[0], a[1] - b[1]) / Math.hypot(a[0], a[1]));
				}
			}
		}
	}
	below(worst, 1e-12, 'T(s) against the page');
	// ...and the responses, which the page inverts on the same contour
	let wh = 0;
	for (const [i, j] of [[0, 0], [1, 0], [3, 0], [3, 2]]) {
		const ax = M.realAxis(ctx, ws, i, j, 1e-3, 1e12);
		for (const t of logGrid(200, 1e6, 12)) {
			const a = M.invertParabola(ctx, ws, ax, t).h;
			if (Math.abs(a) > 1e-200) wh = Math.max(wh, Math.abs(L.responseAt(path, i, j, t).h - a) / Math.abs(a));
		}
	}
	below(wh, 1e-9, 'responses against the page');
});

test('the page’s cases against their 40-digit references, fracture sorption included', () => {
	if (!existsSync(REFERENCE)) return;
	const mp = JSON.parse(readFileSync(REFERENCE, 'utf8'));
	assert(mp.cases.fsorb, 'the reference has no case with sorption on the fracture surfaces');
	for (const [name, c] of Object.entries(mp.cases)) {
		const path = pageCase(c.input);
		const nucs = c.input.nuclides;
		// A sharp front with a long slow tail (little matrix, Pe up to 300):
		// its release is held relative above 1e-4 of the peak and absolute
		// below it, as the page holds it.
		const tail = name.startsWith('tail-');
		let wr = 0;
		for (const r of c.responses) {
			let pk = 0;
			for (const v of r.values) pk = Math.max(pk, v[1]);
			for (const [t, v] of r.values) {
				if (v > 1e-6 * pk) wr = Math.max(wr, Math.abs(L.responseAt(path, r.i, r.j, t).h - v) / v);
			}
		}
		// The page's own inversion stops at 2.3e-11 at one time of
		// tail-300-0.1, where two sums agree a step early; this one, the same.
		below(wr, 1e-10, `${name}: unit responses`);
		const T0 = L.transferAtZero(path);
		for (const [key, v] of Object.entries(c.T0)) {
			const [i, j] = key.split(',').map(Number);
			below(Math.abs(T0[i * path.n + j] / v - 1), 1e-12, `${name}: T(0) of ${nucs[i].name} from ${nucs[j].name}`);
		}
		const R = L.unitResponses(path, { kinds: ['release'] });
		const inflows = nucs.map((x) => (c.input.series[x.name] ? L.inflowSeries(c.input.series[x.name]) : null));
		for (const [nuc, vals] of Object.entries(c.outputs)) {
			const i = nucs.findIndex((x) => x.name === nuc);
			let pk = 0;
			for (const v of vals) pk = Math.max(pk, v[1]);
			let wo = 0;
			let wa = 0;
			for (const [t, v] of vals) {
				const got = L.releaseAt(path, R, inflows, t)[i];
				if (v > (tail ? 1e-4 : 1e-6) * pk) wo = Math.max(wo, Math.abs(got - v) / v);
				wa = Math.max(wa, Math.abs(got - v) / pk);
			}
			// the responses are interpolated to 2e-8 between their samples
			below(wo, 2e-8, `${name}: the release of ${nuc}`);
			if (tail) below(wa, 1e-10, `${name}: the release of ${nuc}, absolute, over its peak`);
		}
	}
});

/** A made-up case in the page's terms, rho 2700: {params, nuclides}. */
const pageInput = (params, nuclides) => ({ params: { rho: 2700, ...params }, nuclides });

test('a front at Pe 5440 against its 100-digit values, and plug flow’s spike and hair', () => {
	// Just past the peak of a front this sharp the contour's step has to
	// follow the fastest phase along it, or two halvings agree on a value
	// 7e-6 off: mpmath's de Hoog at 60 and 100 digits.
	const sharp = pageCase(pageInput({ tw: 260, Pe: 5440, aw: 4.9, eps: 0.002, x0: 0.038 },
		[{ name: 'X', thalf: 1.4e7, kd: 0, de: 7.1e-7, ka: 6.6e-5 }]));
	for (const [t, v] of [[265, 0.0490426509324], [265.5254028201174, 0.0440903175807], [266, 0.0396963774933]]) {
		below(Math.abs(L.responseAt(sharp, 0, 0, t).h / v - 1), 1e-10, `Pe 5440 at ${t}`);
	}
	const rs = L.unitResponse(sharp, 0, 0);
	assert(rs.balanced, `Pe 5440: the response misses its mass balance by ${rs.rel}`);
	// Plug flow, a matrix that fills at once: a spike 0.40 a after a delay of
	// 120 a, found and carrying T(0).
	const spike = L.unitResponse(pageCase(pageInput({ tw: 119.84, Pe: Infinity, aw: 380.5, eps: 1.085e-4, x0: 0.0817 },
		[{ name: 'X', thalf: 2.727e5, kd: 0, de: 3.157e-3 }])), 0, 0);
	assert(Math.abs(spike.tPeak - 120.244) < 0.005, `the spike is at ${spike.tPeak}`);
	below(Math.abs(spike.integral / spike.T0 - 1), 1e-8, 'the spike carries T(0)');
	// A daughter born near the outlet, and one the matrix barely holds,
	// arrive within a hair of the delay: what comes before the first grid
	// time is kept as a point mass, and the response carries what leaves.
	const hair = pageCase(pageInput({ tw: 50.27, Pe: Infinity, aw: 0.3922, eps: 1.888e-4, x0: Infinity }, [
		{ name: 'P', thalf: 13.05, kd: 3.703e-4, de: 1.508e-6, daughter: true }, { name: 'D', thalf: 8.216e5, kd: 0, de: 1.508e-6 }]));
	const d = L.unitResponse(hair, 1, 0);
	assert(d.m0 > 1e-3, `the part before the first grid time is ${d.m0}`);
	below(Math.abs(d.integral - d.expected) / d.T0, 1e-8, 'the daughter carries what leaves by its last time');
	const own = L.unitResponse(hair, 1, 1);
	assert(own.m0 > 0.2 * own.T0 && own.balanced, `the daughter alone: m0 ${own.m0} of ${own.T0}`);
	// ...and a long constant inflow of it comes out at its rate times T(0),
	// the point mass included (it is 29 % of it).
	const R = { release: [null, null, null, own], inventory: [null, null, null, null] };
	const at = L.releaseAt(hair, R, [null, L.inflowSeries([[0, 1], [2e6, 1]])], 1e6)[1];
	below(Math.abs(at / own.T0 - 1), 1e-6, 'a constant inflow of the daughter, at 1e6 a');
});

/**
 * Single nuclides and chains of two or three with one porosity, Pe 1 to 1e4
 * and plug flow, matrices finite and unlimited, sorption on the fracture or
 * not: made up by a seeded generator. Each response against what leaves the
 * path by its last time, and at its own samples against the page model's
 * inversion (or its de Hoog where that does not converge).
 */
function seededSweep(count, first = 20260926) {
	if (!existsSync(PAGE_MODEL)) return;
	const M = createRequire(import.meta.url)(PAGE_MODEL);
	let seed = first;
	const rnd = () => {
		seed = (seed + 0x6D2B79F5) | 0;
		let x = Math.imul(seed ^ (seed >>> 15), 1 | seed);
		x = (x + Math.imul(x ^ (x >>> 7), 61 | x)) ^ x;
		return ((x ^ (x >>> 14)) >>> 0) / 4294967296;
	};
	const lu = (a, b) => a * (b / a) ** rnd();
	let worstBal = 0;
	let worstPage = 0;
	for (let c = 0; c < count; c++) {
		const n = 1 + Math.floor(rnd() * 3);
		const params = {
			tw: lu(1, 1000), Pe: rnd() < 0.15 ? Infinity : lu(1, 1e4), aw: lu(0.1, 1000), eps: lu(1e-4, 1e-2),
			x0: rnd() < 0.25 ? Infinity : lu(1e-3, 10),
		};
		const kaPlug = rnd() < 0.5 ? 0 : lu(1e-6, 1e-3);
		const nucs = [];
		for (let k = 0; k < n; k++) {
			nucs.push({
				name: `N${k}`, thalf: k === n - 1 && rnd() < 0.15 ? Infinity : lu(10, 1e7), kd: rnd() < 0.4 ? 0 : lu(1e-5, 1),
				de: lu(1e-7, 1e-3), ka: rnd() < 0.5 ? 0 : lu(1e-6, 1e-3), daughter: k < n - 1,
			});
		}
		// the page asks one retardation of a chain under plug flow
		if (!Number.isFinite(params.Pe)) for (const x of nucs) x.ka = kaPlug;
		const input = pageInput(params, nucs);
		const path = pageCase(input);
		const ctx = M.prepare({ ...input.params, nuclides: nucs });
		const ws = M.makeWorkspace(ctx);
		for (let j = 0; j < n; j++) {
			for (let i = j; i < n; i++) {
				const r = L.unitResponse(path, i, j);
				if (r.checked) worstBal = Math.max(worstBal, Math.abs(r.integral - r.expected) / Math.max(Math.abs(r.T0), 1e-10));
				if (!(r.peak > 0)) continue;
				const ax = M.realAxis(ctx, ws, i, j, ctx.infPe ? M.pairDelay(ctx, i, j) * (1 + 1e-9) : ctx.tw * 1e-6, 1e12);
				const step = Math.max(1, Math.floor(r.t.length / 12));
				// Under plug flow a time within a millionth of the delay leaves
				// t - delay with ten digits or fewer, and two codes that form it
				// differently part at 1e-8 there: those samples are not compared.
				const delay = ctx.infPe ? M.pairDelay(ctx, i, j) : 0;
				for (let k = 0; k < r.t.length; k += step) {
					if (delay > 0 && r.t[k] - delay < 1e-6 * delay) continue;
					const v = M.invertParabola(ctx, ws, ax, r.t[k]);
					const h = Number.isFinite(v.h) && !(v.err > 1e-6 * Math.abs(v.h)) ? v.h
						: M.invertDeHoog(ctx, ws, i, j, r.t[k], { M: Math.min(2 * M.deHoogTerms(ctx, ax, r.t[k]), 320) });
					worstPage = Math.max(worstPage, Math.abs(h - r.h[k]) / r.peak);
				}
			}
		}
	}
	// the run's own check holds a response to 1e-5; a path whose response is
	// mostly a point mass at its delay (plug flow, an unlimited matrix that
	// barely takes anything up) gets that point mass from de Hoog to 2e-6
	below(worstBal, 1e-5, 'every response against what leaves the path');
	below(worstPage, 1e-8, 'every response against the page, over its peak');
}

test('a seeded sweep: every response carries what leaves the path, and is the page’s', () => seededSweep(4));

test('a response that misses its mass balance is said: by the response, the path, the run and its log', async () => {
	// A grid far too coarse to hold the response -- a point a decade, a dozen
	// at most -- misses even when worked out again, and says by how much.
	const path = L.preparePath({ tw: 50, f: 5e4, rho_m: 2700, pe: 10, pen_dep: 0.1, kd_f: 2e-4, eps_m: 0.005,
		kd_m: 1e-3, de_m: 1e-4 }, L.decayTable([LN2 / 3000]));
	const good = L.unitResponse(path, 0, 0);
	assert(good.balanced && good.rel < 1e-8, `as computed it misses by ${good.rel}`);
	const bad = L.unitResponse(path, 0, 0, { perDecade: 1, maxPts: 12 });
	assert(bad.balanced === false && bad.rel > 1e-5, `a coarse grid passes: ${bad.rel}`);
	// The path collects what its responses missed, in words...
	const { buildSystem } = await import('../src/sim/builder.js');
	const system = buildSystem(new Project(chainThroughPath({
		names: ['Aa-1'], half: { 'Aa-1': 3000 }, chains: [], kdf: [2e-4], kdm: [1e-3], dem: [1e-4],
		path: { tw: 50, f: 5e4, eps_m: 0.005, pe: 10, pen_dep: 0.1 }, times: [100, 1000],
	})));
	const F = system.paths[0];
	F.combos = [{ kernels: [], pairs: 0, misses: [{ i: 0, j: 0, integral: 0.5, expected: 0.9, T0: 1, rel: 0.4, until: 1e4 }] }];
	const said = F.balanceWarnings();
	assert(said.length === 1 && said[0].block === 'Rock', JSON.stringify(said));
	assert(said[0].message === 'the unit response of Aa-1 to Aa-1 integrates to 0.5000, but 0.9000 of a pulse leaves '
		+ 'the path by 1.000e+4 (T(0) = 1.000): the inversion failed there, and the release worked out from it is not '
		+ 'reliable', said[0].message);
	// ...and the run log says it, as the block's problems do.
	const { runLogLines } = await import('../src/domain/runlog.js');
	const lines = runLogLines({ project: { name: 'x', simulation: {} }, payload: { stats: { farfield: said } } });
	assert(lines.includes('semi-analytical far-field paths: 1 unit response missed its mass balance'), lines.join('\n'));
	assert(lines.includes(`  Rock: ${said[0].message}`), lines.join('\n'));
	const app = readFileSync(`${HERE}../src/ui/app.js`, 'utf8');
	// The run's warnings, this path's and those about a path's layers alike.
	assert(/state\.runWarnings = \[\s*\.\.\.\(Array\.isArray\(payload\.stats\?\.farfield\)/.test(app)
		&& /\.\.\.\(Array\.isArray\(payload\.stats\?\.layers\)/.test(app), 'the app does not take the run\'s warnings');
	assert(/for \(const w of state\.runWarnings\)/.test(app), 'the block is not marked');
});

slow('a longer seeded sweep: sixteen more made-up paths', () => seededSweep(16, 7));

// ---------------------------------------------------------------------------
// Closed forms
// ---------------------------------------------------------------------------

test('no matrix: the inverse Gaussian in t/Rf, e^(-lambda t) h(t/Rf)/Rf, and what is held', () => {
	for (const [Pe, kdf] of [[0.5, 0], [2, 2e-4], [10, 1e-3], [50, 5e-3], [300, 2e-2], [1e5, 1e-3]]) {
		const tw = 100;
		const lam = LN2 / 1e4;
		const f = 5e4;
		const Rf = 1 + kdf * f / tw;
		const path = single({ tw, f, rho_m: 2700, pe: Pe, pen_dep: 1, kd_f: kdf, eps_m: 0.005, kd_m: 0, de_m: 0 }, lam);
		const ts = logGrid(tw * Rf / 30, tw * Rf * 30, 121);
		const want = ts.map((t) => Math.exp(-lam * t) * ig(t / Rf, tw, Pe) / Rf);
		below(worstRel(ts, ts.map((t) => L.responseAt(path, 0, 0, t).h), want, 1e-10), 1e-9, `release at Pe ${Pe}, Rf ${Rf}`);
		if (Pe <= 300) {
			const held = ts.map((t) => Math.exp(-lam * t) * igSurvival(t / Rf, tw, Pe));
			const got = ts.map((t) => L.responseAt(path, 0, 0, t, { kind: 'inventory' }).h);
			below(worstRel(ts, got, held, 1e-10), 1e-9, `inventory at Pe ${Pe}, Rf ${Rf}`);
		}
		const T0 = L.transferAtZero(path)[0];
		const exact = Math.exp(-2 * tw * lam * Rf / (1 + Math.sqrt(1 + 4 * tw * lam * Rf / Pe)));
		below(Math.abs(T0 / exact - 1), 1e-14, `T(0) at Pe ${Pe}`);
	}
});

test('plug flow and an unlimited matrix: the classical solution, delayed by Rf TW', () => {
	for (const [kd, de, aw, th, kdf] of [
		[0, 1e-6, 500, 1e7, 0], [0.01, 5e-6, 1500, 7.6e4, 1e-3], [1, 4e-6, 800, Infinity, 0.01],
		[2, 4e-6, 800, 432.6, 0.1], [0.001, 1e-3, 1e4, 1e5, 1e-4],
	]) {
		const tw = 100;
		const eps = 0.005;
		const Rm = eps + kd * 2700;
		const k = tw * aw * Math.sqrt(de * Rm);
		const lam = Number.isFinite(th) ? LN2 / th : 0;
		const Rf = 1 + kdf * aw;
		const path = single({
			tw, surface: 'aw', aw, rho_m: 2700, pe: Infinity, pen_dep: Infinity, kd_f: kdf, eps_m: eps, kd_m: kd, de_m: de,
		}, lam);
		const up = k * k / 6;
		const ts = logGrid(up * 1e-3, up * 1e4, 141).map((u) => Rf * tw + u);
		const want = ts.map((t) => Math.exp(-lam * t) * neret(t - Rf * tw, k));
		below(worstRel(ts, ts.map((t) => L.responseAt(path, 0, 0, t).h), want, 1e-6), 1e-9, `release, Kd ${kd}, Rf ${Rf}`);
		assert(L.responseAt(path, 0, 0, Rf * tw * 0.999).h === 0, 'something arrived before Rf TW');
		const held = ts.map((t) => Math.exp(-lam * t) * (1 - erfc(k / (2 * Math.sqrt(t - Rf * tw)))));
		const got = ts.map((t) => L.responseAt(path, 0, 0, t, { kind: 'inventory' }).h);
		below(worstRel(ts, got, held, 1e-10), 1e-9, `inventory, Kd ${kd}, Rf ${Rf}`);
		for (const t of [0.1, 0.5, 0.95].map((x) => x * Rf * tw)) {
			below(Math.abs(L.responseAt(path, 0, 0, t, { kind: 'inventory' }).h / Math.exp(-lam * t) - 1), 1e-15,
				'the whole pulse held before the front');
		}
	}
});

test('finite Pe and an unlimited matrix, with fracture sorption: the subordination integral', () => {
	// h(t) = e^(-lambda t) int IG(u) K(t - Rf u, c u) du over the water residence time u
	const tw = 50;
	const Pe = 8;
	const kd = 0.005;
	const de = 2e-6;
	const aw = 400;
	const eps = 0.004;
	const th = 3e4;
	const kdf = 2e-3;
	const Rm = eps + kd * 2700;
	const Rf = 1 + kdf * aw;
	const lam = LN2 / th;
	const c = aw * Math.sqrt(de * Rm);
	const path = single({
		tw, f: aw * tw, rho_m: 2700, pe: Pe, pen_dep: Infinity, kd_f: kdf, eps_m: eps, kd_m: kd, de_m: de,
	}, lam);
	const ts = logGrid(50, 5e4, 25);
	const want = ts.map((t) => Math.exp(-lam * t) * quad((u) => (u > 0 && Rf * u < t ? ig(u, tw, Pe) * neret(t - Rf * u, c * u) : 0), 0, t / Rf));
	below(worstRel(ts, ts.map((t) => L.responseAt(path, 0, 0, t).h), want, 1e-6), 1e-7, 'against the integral');
});

// ---------------------------------------------------------------------------
// Bateman: nuclides that move alike
// ---------------------------------------------------------------------------

test('a network that branches and merges, moving alike: h_ij = [e^(-Lambda t)]_ij h(t), and so for k', () => {
	for (const [label, th] of [
		['distinct', [3000, 700, 5000, 1e4, Infinity]],
		['close', [3000, 3000.3, 3000, 3000.0001, Infinity]],
		['equal', [1e4, 1e4, 1e4, 1e4, Infinity]],
	]) {
		for (const unit of ['mol', 'Bq']) {
			const net = network(th, unit);
			for (const [matrix, Pe] of [[false, 20], [true, 10], [true, Infinity]]) {
				const set = {
					tw: 100, f: matrix ? 1e5 : 0, rho_m: 2700, pe: Pe, pen_dep: 0.5,
					kd_f: 1e-3, eps_m: 0.005, kd_m: 0.01, de_m: 1e-5,
				};
				const path = L.preparePath(set, net.decay, { names: net.list });
				const one = single(set);
				const ts = logGrid(10, 1e6, 30);
				const h0 = ts.map((t) => L.responseAt(one, 0, 0, t).h);
				const k0 = ts.map((t) => L.responseAt(one, 0, 0, t, { kind: 'inventory' }).h);
				const E = ts.map((t) => expm(net.Lam, t));
				let wh = 0;
				let wk = 0;
				for (const [i, j] of L.pairs(path)) {
					const hw = ts.map((t, q) => E[q][i][j] * h0[q]);
					wh = Math.max(wh, worstRel(ts, ts.map((t) => L.responseAt(path, i, j, t).h), hw, 1e-8));
					const kw = ts.map((t, q) => E[q][i][j] * k0[q]);
					wk = Math.max(wk, worstRel(ts, ts.map((t) => L.responseAt(path, i, j, t, { kind: 'inventory' }).h), kw, 1e-8));
				}
				const what = `${label} half-lives, ${unit}, ${matrix ? 'matrix' : 'no matrix'}, Pe ${Pe}`;
				below(wh, 1e-9, `${what}: releases`);
				below(wk, 1e-9, `${what}: inventories`);
			}
		}
	}
});

// ---------------------------------------------------------------------------
// The mass balance
// ---------------------------------------------------------------------------

/** The network with every nuclide its own chemistry. */
function chemistry() {
	const net = network([3000, 700, 5000, 1e4, Infinity], 'mol');
	const path = L.preparePath({
		tw: 80, f: 6.4e4, rho_m: 2700, pe: 10, pen_dep: 0.8,
		kd_f: [0, 1e-3, 2e-3, 0, 5e-3], eps_m: 0.004, kd_m: [0.05, 0.2, 0.01, 0.1, 0.02], de_m: [3e-6, 2e-6, 4e-6, 3e-6, 1e-6],
	}, net.decay, { names: net.list });
	return { net, path };
}

test('every column of T(0) sums to one when every chain ends stable', () => {
	const { path } = chemistry();
	const T0 = L.transferAtZero(path);
	for (let j = 0; j < path.n; j++) {
		let s = 0;
		for (let i = 0; i < path.n; i++) s += T0[i * path.n + j];
		below(Math.abs(s - 1), 1e-14, `column ${path.names[j]}`);
	}
});

test('each tabulated release integrates to T(0), and k\' = -Lambda k - h holds at every sample', () => {
	const { net, path } = chemistry();
	const R = L.unitResponses(path);
	const n = path.n;
	for (const r of R.release) {
		if (!r) continue;
		below(Math.abs(r.integral / r.T0 - 1), 1e-9, `the integral of ${path.names[r.i]} from ${path.names[r.j]}`);
	}
	let worst = 0;
	for (const r of R.inventory) {
		if (!r) continue;
		let pk = 0;
		for (const v of r.h) pk = Math.max(pk, Math.abs(v));
		for (let q = 1; q < r.t.length; q += 11) {
			const t = r.t[q];
			let lk = net.lam[r.i] * r.h[q];
			for (const [p, d, c] of net.pairs) {
				if (d === r.i && path.reach[r.j][p]) lk -= c * L.responseAt(path, p, r.j, t, { kind: 'inventory' }).h;
			}
			const h = L.responseAt(path, r.i, r.j, t).h;
			const scale = Math.max(Math.abs(r.dh[q]), Math.abs(h), net.lam[r.i] * pk, 1e-6 * pk / t);
			worst = Math.max(worst, Math.abs(r.dh[q] + lk + h) / scale);
		}
	}
	void n;
	below(worst, 1e-10, 'k\' + Lambda k + h');
});

test('what the path holds is what went in less what left and what decayed', () => {
	const { net, path } = chemistry();
	const R = L.unitResponses(path, { tMax: 5e4 });
	const n = path.n;
	const inflows = new Array(n).fill(null);
	inflows[net.idx.P] = L.inflowSeries([[0, 0], [100, 1], [2e4, 1], [2e4, 0.5], [3e4, 0]]);
	inflows[net.idx.B] = L.inflowSeries([[500, 0.2], [8000, 0.2]]);
	const T = 4e4;
	const N = 4000;
	const ts = Array.from({ length: N + 1 }, (_, k) => (k / N) * T);
	const out = ts.map((t) => L.releaseAt(path, R, inflows, t));
	const held = ts.map((t) => L.inventoryAt(path, R, inflows, t));
	const mass = (i) => (inflows[i] ? inflows[i].mass : 0);
	let worst = 0;
	for (let i = 0; i < n; i++) {
		// Simpson on in - out - (Lambda Inv)_i; the inflows' own integrals exactly
		const f = ts.map((t, q) => {
			let li = net.lam[i] * held[q][i];
			for (const [p, d, c] of net.pairs) if (d === i) li -= c * held[q][p];
			return -out[q][i] - li;
		});
		let s = 0;
		for (let q = 0; q < N; q += 2) s += (T / N) / 3 * (f[q] + 4 * f[q + 1] + f[q + 2]);
		worst = Math.max(worst, Math.abs(held[N][i] - held[0][i] - (s + mass(i))) / 2e4);
	}
	below(worst, 1e-9, 'the balance over 40,000 years, as a fraction of what went in');
});

test('a long constant inflow reaches its rate times T(0)', () => {
	const path = single({ tw: 50, f: 2.5e4, rho_m: 2700, pe: 20, pen_dep: 0.5, kd_f: 1e-3, eps_m: 0.004, kd_m: 0, de_m: 1e-6 }, LN2 / 1.57e7);
	const R = L.unitResponses(path);
	const inflows = [L.inflowSeries([[0, 2], [1e7, 2]])];
	const T0 = R.release[0].T0;
	for (const t of [1e6, 1.5e6]) below(Math.abs(L.releaseAt(path, R, inflows, t)[0] / (2 * T0) - 1), 1e-9, `at ${t}`);
});

// ---------------------------------------------------------------------------
// Species that do not decay, the surface, the other inversions, refusals
// ---------------------------------------------------------------------------

test('species that neither decay nor grow in each travel alone', () => {
	const tw = 40;
	const Pe = 12;
	const kdf = [0, 1e-3, 4e-3];
	const path = L.preparePath({ tw, f: 2e4, rho_m: 2700, pe: Pe, pen_dep: 1, kd_f: kdf, eps_m: 0.005, kd_m: 0, de_m: 0 }, null);
	assert(path.n === 3, `${path.n} species`);
	assert(L.pairs(path).length === 3, 'a species without decay reached another');
	const T0 = L.transferAtZero(path);
	for (let i = 0; i < 3; i++) {
		const Rf = 1 + kdf[i] * 500;
		below(Math.abs(T0[i * 3 + i] - 1), 1e-15, 'nothing is lost');
		const ts = logGrid(tw * Rf / 10, tw * Rf * 10, 41);
		const want = ts.map((t) => ig(t / Rf, tw, Pe) / Rf);
		below(worstRel(ts, ts.map((t) => L.responseAt(path, i, i, t).h), want, 1e-10), 1e-9, `species ${i}`);
		assert(L.unitResponse(path, (i + 1) % 3, i).t.length === 0, 'a response between species');
	}
});

test('F, a_w and the aperture give the same path', () => {
	const base = { tw: 60, rho_m: 2700, pe: 10, pen_dep: 0.5, kd_f: 1e-3, eps_m: 0.005, kd_m: 0.01, de_m: 1e-5 };
	const a = single({ ...base, f: 6e4 });
	const b = single({ ...base, surface: 'aw', aw: 1000 });
	const c = single({ ...base, surface: 'aperture', aperture: 0.002 });
	for (const t of [100, 1e3, 1e4]) {
		const h = L.responseAt(a, 0, 0, t).h;
		below(Math.abs(L.responseAt(b, 0, 0, t).h / h - 1), 1e-14, 'a_w');
		below(Math.abs(L.responseAt(c, 0, 0, t).h / h - 1), 1e-14, 'aperture');
	}
});

test('de Hoog’s method and Talbot’s contour agree with the parabola', () => {
	const { net, path } = chemistry();
	for (const [i, j] of [[net.idx.S, net.idx.P], [net.idx.D, net.idx.B], [net.idx.A, net.idx.A]]) {
		const ts = logGrid(500, 1e5, 9);
		const par = ts.map((t) => L.responseAt(path, i, j, t).h);
		const dh = ts.map((t) => L.responseAt(path, i, j, t, { method: 'dehoog' }).h);
		below(worstRel(ts, dh, par, 1e-6), 1e-5, `de Hoog, ${path.names[i]} from ${path.names[j]}`);
		const tal = ts.map((t) => L.responseAt(path, i, j, t, { method: 'talbot' }).h);
		below(worstRel(ts, tal, par, 1e-6), 1e-5, `Talbot, ${path.names[i]} from ${path.names[j]}`);
	}
});

test('what the method cannot solve is refused, saying why', () => {
	const ok = { tw: 10, f: 1e4, rho_m: 2700, pe: 10, pen_dep: 1, kd_f: 0, eps_m: 0.005, kd_m: 0, de_m: 1e-5 };
	const refuses = (settings, decay, re, what) => {
		let msg = '';
		try { L.preparePath(settings, decay); } catch (e) { msg = e.message; assert(e instanceof L.LaplacePathError, `${what}: ${e.name}`); }
		assert(re.test(msg), `${what}: ${msg || 'accepted'}`);
	};
	refuses({ ...ok, pe: Infinity, f: 0 }, null, /Plug flow .* needs matrix diffusion/, 'plug flow without a matrix');
	refuses({ ...ok, de_m: [1e-5, 0] }, L.decayTable([1e-3, 1e-4], [[0, 1, 1e-3]]), /does not diffuse into the matrix/, 'a chain half in the matrix');
	refuses(ok, L.decayTable([1e-3, 1e-4], [[0, 1, 1e-3], [1, 0, 1e-4]]), /closes on itself/, 'a cycle');
	refuses({ ...ok, tw: 0 }, null, /travel time/, 'TW = 0');
	refuses({ ...ok, kd_m: -1 }, null, /kd_m/, 'a negative Kd');
	refuses({ ...ok, pe: 0 }, null, /Peclet/, 'Pe = 0');
	refuses({ ...ok, eps_m: 0 }, null, /capacity/, 'no capacity in the matrix');
	refuses({ ...ok, surface: 'volume' }, null, /wetted surface/, 'an unknown surface');
	const long = Array.from({ length: 18 }, (_, k) => [k, k + 1, 1e-3]);
	refuses(ok, L.decayTable(new Array(19).fill(1e-3), long), /at most 16/, 'a chain of nineteen');
	// ...and a chain whose every member stays out of the matrix is fine
	L.preparePath({ ...ok, de_m: 0 }, L.decayTable([1e-3, 1e-4], [[0, 1, 1e-3]]));
});

// ---------------------------------------------------------------------------
// Shared contours: one parabola serves the times of a cell
// ---------------------------------------------------------------------------

/** An unbranched chain, one half-life each (Infinity: stable). */
const chainOf = (set, half) => {
	const lam = half.map((th) => (Number.isFinite(th) ? LN2 / th : 0));
	return L.preparePath(set, L.decayTable(lam, lam.slice(1).map((_, k) => [k, k + 1, lam[k]])));
};

/** Plug flow into a thin matrix, a parent into a stable daughter: what the
    path holds falls below half of what it would hold within the run, so K is
    also inverted whole. */
const plugThin = () => chainOf({ tw: 100, f: 2e4, rho_m: 2700, pe: Infinity, pen_dep: 0.05, kd_f: 1e-4, eps_m: 0.005,
	kd_m: [1e-3, 0.01], de_m: 1e-5 }, [2.4e5, Infinity]);

/** The far-field example's path, made up as the example makes it. */
function examplePath() {
	const { names, dec } = decayOfModel(JSON.parse(readFileSync(EXAMPLE, 'utf8')));
	const kd = { 'U-238': 0.0017, 'U-234': 0.0017, 'Th-230': 0.05 };
	return L.preparePath({
		tw: 50, f: 1e5, rho_m: 2700, pe: 10, pen_dep: 12.5, kd_f: 0, eps_m: 0.0018,
		kd_m: names.map((x) => kd[x]), de_m: 3.15e-5,
	}, dec, { names });
}

/** The axes a response of this kind is sampled on: a release's, or an
    inventory's two (A^-1 T for the split, K for the whole). */
function axesOf(path, i, j, kind) {
	const I = L._internal;
	if (kind === 'release') return [['release', I.axisOf(path, I.pairOf(path, i, j, 'release'))]];
	const [axC, axK] = I.inventoryAxes(path, i, j);
	return [['split', axC], ['whole', axK]];
}

/** The peak and absolute floor the app holds an axis's cells to: a release's
    peak estimate, an inventory's one unit. */
function cellOptions(ax) {
	const I = L._internal;
	const sup = I.responseSupport(ax, ax.tLo, 1e12);
	const peak = ax.pr.kind === I.RELEASE ? Math.exp(sup.logPeak) : 1;
	return { sup, opt: { atol: 1e-3 * I.RESP_ATOL * peak, peak } };
}

/** Whether the app samples an inventory's K inverted whole at t: only once
    less than half of what the path would hold is left in it (see
    sampleInventory). Before that K's terms cancel, and one parabola's own sums
    are cut short there as often as the cells'. */
function takesWhole(path, ax, t) {
	const I = L._internal;
	const k = I.invertParabola(path, path.ws, ax, t).h;
	return Math.abs(k) < 0.5 * Math.abs(I.bateman(path, path.ws, ax.pr.blk, t)[0]);
}

/** The times from the first at which the app takes K whole, which it goes on
    doing (found by bisection: before it, one parabola runs to its budget). */
function fromWhole(path, ax, ts) {
	let lo = -1;
	let hi = ts.length - 1;
	while (hi - lo > 1) { const c = (lo + hi) >> 1; if (takesWhole(path, ax, ts[c])) hi = c; else lo = c; }
	return ts.slice(hi);
}

/** Times over an axis's support, logarithmic in t less the delay: `per` a
    decade, `least` at least. */
function supportTimes(ax, sup, per, least) {
	const d = ax.pr.shift;
	const u0 = sup.tLo - d;
	const u1 = Math.min(sup.tHi, 1e12) - d;
	return logGrid(u0, u1, Math.max(least, Math.ceil(per * Math.log10(u1 / u0)) + 1)).map((u) => d + u);
}

test('shared parabolas: h, h\' and h\'\' agree with one parabola per time to 1e-10 of their peaks, on every kind of axis', () => {
	// The cells against invertParabola at the same times, 60 a decade (200 at
	// least; two dozen or so to a cell) over each axis's support where the
	// app samples it, each derivative over its largest value there. Only times
	// both answer are compared. The cells serve every time where the response
	// is above 1e-10 of its peak; far out in a long tail, below that, some
	// times need a parabola of their own, whose sums cancel there too or do
	// not converge (such a time is sized by the saddle-point estimate).
	const I = L._internal;
	const cases = [
		['the far-field example', examplePath(), [[2, 0, 'release'], [1, 1, 'release'], [1, 0, 'inventory']]],
		['plug flow, a thin matrix', plugThin(), [[1, 0, 'release'], [1, 0, 'inventory']]],
		['plug flow, a matrix without end', chainOf({ tw: 30, f: 5e4, rho_m: 2700, pe: Infinity, pen_dep: Infinity,
			kd_f: 0, eps_m: 0.004, kd_m: [0.001], de_m: 3e-5 }, [2.3e6]), [[0, 0, 'release'], [0, 0, 'inventory']]],
		['a sharp front, Pe 3000', chainOf({ tw: 20, f: 3e3, rho_m: 2700, pe: 3000, pen_dep: 1, kd_f: 0, eps_m: 0.003,
			kd_m: [5e-4, 2e-3], de_m: 2e-5 }, [1e5, 3e4]), [[1, 0, 'release'], [0, 0, 'inventory']]],
		['a front at Pe 5440', pageCase(pageInput({ tw: 260, Pe: 5440, aw: 4.9, eps: 0.002, x0: 0.038 },
			[{ name: 'X', thalf: 1.4e7, kd: 0, de: 7.1e-7, ka: 6.6e-5 }])), [[0, 0, 'release']]],
		['a long slow tail, Pe 300, stable', chainOf({ tw: 50, f: 1e3, rho_m: 2700, pe: 300, pen_dep: Infinity, kd_f: 0,
			eps_m: 0.002, kd_m: [0], de_m: 1e-5 }, [Infinity]), [[0, 0, 'release'], [0, 0, 'inventory']]],
	];
	for (const [label, path, pairs] of cases) {
		for (const [i, j, kind] of pairs) {
			for (const [which, ax] of axesOf(path, i, j, kind)) {
				const { sup, opt } = cellOptions(ax);
				const cells = I.makeCells(path, ax, opt);
				const own = [];
				const shared = [];
				const left = [];
				const ts = supportTimes(ax, sup, 60, 200);
				for (const t of which === 'whole' ? fromWhole(path, ax, ts) : ts) {
					const p = I.invertParabola(path, path.ws, ax, t, { atol: opt.atol });
					if (which === 'whole' && !(Math.abs(p.h) < 0.5 * Math.abs(I.bateman(path, path.ws, ax.pr.blk, t)[0]))) continue; // see takesWhole
					const s = I.invertShared(path, path.ws, cells, t);
					if (!s) { left.push(Math.exp(I.logEstimate(ax, t))); continue; }
					if (!Number.isFinite(p.h) || p.err > 1e-6 * Math.abs(p.h) + opt.atol) continue;
					own.push(p);
					shared.push(s);
				}
				const worst = ['h', 'dh', 'd2'].map((key) => {
					let top = 0;
					let w = 0;
					own.forEach((p, k) => { top = Math.max(top, Math.abs(p[key])); w = Math.max(w, Math.abs(shared[k][key] - p[key])); });
					return w / top;
				});
				const what = `${label}, ${path.names[i]} from ${path.names[j]}, ${which}`;
				assert(own.length > 50, `${what}: ${own.length} times compared`);
				assert(worst.every((w) => w <= 1e-10), `${what}: h, h' and h'' ${worst.map((w) => w.toExponential(1)).join(', ')}`);
				const top = Math.max(...own.map((p) => Math.abs(p.h)));
				const high = left.filter((v) => !(v <= 1e-10 * top)).length;
				assert(high === 0, `${what}: ${high} of ${left.length} times left to a parabola of their own are above 1e-10 of the peak`);
			}
		}
	}
});

test('shared parabolas: a time gives the same value, bit for bit, whatever was asked for before it', () => {
	// Each cell comes from the axis's table and its index alone: forwards,
	// backwards, shuffled or alone, a time gets the same sums.
	const I = L._internal;
	const plug = plugThin();
	const example = examplePath();
	const axes = [
		['a release', example, axesOf(example, 2, 0, 'release')[0][1]],
		['the split of an inventory, plug flow', plug, axesOf(plug, 1, 0, 'inventory')[0][1]],
		['a whole inventory, plug flow', plug, axesOf(plug, 1, 0, 'inventory')[1][1]],
	];
	const same = (p, q) => (p === null && q === null)
		|| (!!p && !!q && Object.is(p.h, q.h) && Object.is(p.dh, q.dh) && Object.is(p.d2, q.d2) && Object.is(p.err, q.err));
	for (const [label, path, ax] of axes) {
		const { sup, opt } = cellOptions(ax);
		let ts = supportTimes(ax, sup, 0, 150);
		if (ax.pr.kind === I.INVENTORY) {
			const from = fromWhole(path, ax, ts);
			ts = logGrid(from[0], from[from.length - 1], 150);
		}
		const inOrder = (order) => {
			const cells = I.makeCells(path, ax, opt);
			const out = new Array(ts.length);
			for (const k of order) out[k] = I.invertShared(path, path.ws, cells, ts[k]);
			return out;
		};
		const idx = ts.map((_, k) => k);
		const perm = idx.slice();
		let x = 12345;
		for (let k = perm.length - 1; k > 0; k--) {
			x = (x * 1103515245 + 12345) % 2147483648;
			const r = x % (k + 1);
			[perm[k], perm[r]] = [perm[r], perm[k]];
		}
		const fwd = inOrder(idx);
		const back = inOrder(idx.slice().reverse());
		const mixed = inOrder(perm);
		assert(fwd.filter((r) => r !== null).length > 0.95 * ts.length, `${label}: the cells serve too few times`);
		assert(idx.every((k) => same(fwd[k], back[k]) && same(fwd[k], mixed[k])), `${label}: a value depends on the order`);
		for (const k of [0, 37, 75, 149]) {
			assert(same(I.invertShared(path, path.ws, I.makeCells(path, ax, opt), ts[k]), fwd[k]), `${label}: time ${k} alone`);
		}
		// every cell spans at most a factor 2 either side of its middle time
		const cells = I.makeCells(path, ax, opt);
		for (const t of ts) I.invertShared(path, path.ws, cells, t);
		assert(cells.map.size > 3, `${label}: ${cells.map.size} cells`);
		for (const cell of cells.map.values()) {
			assert(cell.tHi <= 2 * cell.tA * (1 + 1e-12) && cell.tA <= 2 * cell.tLo * (1 + 1e-12),
				`${label}: a cell spans ${cell.tLo} to ${cell.tHi} about ${cell.tA}`);
		}
	}
});

test('shared parabolas: the far-field example is what one parabola per time gives, and hardly a sample needs one', () => {
	const path = examplePath();
	const R = L.unitResponses(path, { tMax: 1e6 });
	const own = L.unitResponses(examplePath(), { tMax: 1e6, shared: false });
	// how the samples were taken: the cells serve all of them but a few
	let left = 0;
	let all = 0;
	let failed = 0;
	for (const kind of L.KINDS) {
		for (const r of R[kind]) {
			if (!r) continue;
			left += r.shared.fallback;
			failed += r.shared.failed;
			all += r.shared.shared + r.shared.fallback + r.shared.negligible;
		}
	}
	assert(all > 2000 && left <= 0.01 * all, `${left} of ${all} samples needed a parabola of their own`);
	assert(failed === 0, `${failed} cells could not serve`);
	assert(own.release.every((r) => !r || r.shared === null), 'shared: false still shares');
	// ...and the values and both derivatives are one parabola per time's, at
	// every time both grids hold, each over its largest value
	for (const kind of L.KINDS) {
		R[kind].forEach((r, q) => {
			if (!r) return;
			const o = own[kind][q];
			const at = new Map(Array.from(o.t, (t, k) => [t, k]));
			const common = r.t.filter((t) => at.has(t)).length;
			const what = `${kind} of ${path.names[r.i]} from ${path.names[r.j]}`;
			assert(common >= 0.9 * r.t.length, `${what}: ${common} of ${r.t.length} times in both grids`);
			for (const key of ['h', 'dh', 'd2h']) {
				let pk = 0;
				for (const v of o[key]) pk = Math.max(pk, Math.abs(v));
				let worst = 0;
				r.t.forEach((t, k) => { if (at.has(t)) worst = Math.max(worst, Math.abs(r[key][k] - o[key][at.get(t)]) / pk); });
				below(worst, 1e-10, `${what}: ${key}, over its largest`);
			}
		});
	}
	// ...and so is what an inflow of the parent makes of them
	const n = path.n;
	const inflows = new Array(n).fill(null);
	inflows[path.names.indexOf('U-238')] = L.inflowSeries([[0, 0], [1e3, 1], [1e5, 1], [2e5, 0]]);
	for (const [fn, what] of [[L.releaseAt, 'the release'], [L.inventoryAt, 'what the path holds']]) {
		const a = logGrid(1e3, 1e6, 40).map((t) => fn(path, R, inflows, t));
		const b = logGrid(1e3, 1e6, 40).map((t) => fn(path, own, inflows, t));
		for (let i = 0; i < n; i++) {
			const pk = Math.max(...b.map((row) => Math.abs(row[i])));
			if (!(pk > 0)) continue;
			below(Math.max(...a.map((row, q) => Math.abs(row[i] - b[q][i]))) / pk, 1e-10, `${what} of ${path.names[i]}, over its peak`);
		}
	}
});

// ---------------------------------------------------------------------------
// Plug flow's exponent, a weak singularity next to a sharp front, a sharp
// front's rising edge, and responseAt's fallback
// ---------------------------------------------------------------------------

/** Adaptive Gauss-Kronrod (7-15) to tol relative or abs absolute, the absolute
    part halved with each split (for integrands tiny over most of the range). */
function quadAbs(f, a, b, tol, abs, depth = 0) {
	const xk = [0.991455371120813, 0.949107912342759, 0.864864423359769, 0.741531185599394, 0.586087235467691, 0.405845151377397, 0.207784955007898, 0];
	const wk = [0.022935322010529, 0.063092092629979, 0.104790010322250, 0.140653259715525, 0.169004726639267, 0.190350578064785, 0.204432940075298, 0.209482141084728];
	const wg = [0, 0.129484966168870, 0, 0.279705391489277, 0, 0.381830050505119, 0, 0.417959183673469];
	const c = 0.5 * (a + b);
	const h = 0.5 * (b - a);
	let K = 0;
	let G = 0;
	for (let q = 0; q < 8; q++) {
		const s = q === 7 ? f(c) : f(c - h * xk[q]) + f(c + h * xk[q]);
		K += wk[q] * s;
		G += wg[q] * s;
	}
	K *= h;
	G *= h;
	if (Math.abs(K - G) <= tol * Math.abs(K) + abs || depth > 24) return K;
	return quadAbs(f, a, c, tol, abs / 2, depth + 1) + quadAbs(f, c, b, tol, abs / 2, depth + 1);
}

/**
 * h, h' and h'' of one nuclide at finite Pe with an unlimited matrix, no
 * sorption on the fracture, by the subordination integral h = e^(-lambda t) J,
 * J(t) = int IG(u) K(t - u; a(u)) du, K(tau; a) = a/(2 sqrt(pi) tau^1.5)
 * exp(-a^2/(4 tau)), a = u aw sqrt(De R). Near a front the matrix delays of
 * interest are a few years, whose diffusion depth is well below a metre: for
 * a 1 m matrix the kernel is exact there. Since d/dt K = c K_a - d/du K (c =
 * da/du), parts move the time derivatives onto IG, which keeps the quadrature
 * free of cancellation: J' = int (IG' K + c IG K_a) du, J'' = int (IG'' K +
 * 2 c IG' K_a + c^2 IG K_aa) du, K_a = K (1/a - a/(2 tau)), K_aa = K (a^2/(4
 * tau^2) - 3/(2 tau)). In ln tau, with break points at the kernel's and the
 * front's scales, each part to 1e-16 of the integral of its modulus. Returns
 * [h, h', h''], or [h] alone when `alone`.
 */
function subordination({ tw, Pe, aw, R, De, lam }, t, alone) {
	const c = aw * Math.sqrt(De * R);
	const IG = (u) => Math.sqrt(Pe * tw / (4 * Math.PI * u ** 3)) * Math.exp(-Pe * (u - tw) ** 2 / (4 * tw * u));
	const part = (m) => (x) => {
		const tau = Math.exp(x);
		const u = t - tau;
		if (!(u > 0)) return 0;
		const a = c * u;
		const k = IG(u) * a / (2 * Math.sqrt(Math.PI) * Math.sqrt(tau)) * Math.exp(-a * a / (4 * tau)); // IG K dtau/dx
		if (m === 0) return k;
		const l1 = -1.5 / u - Pe / (4 * tw) * (1 - tw * tw / (u * u)); // (ln IG)'
		const l2 = 1.5 / (u * u) - Pe * tw / (2 * u ** 3); // (ln IG)''
		const ka = 1 / a - a / (2 * tau);
		if (m === 1) return k * (l1 + c * ka);
		return k * (l1 * l1 + l2 + 2 * c * l1 * ka + c * c * (a * a / (4 * tau * tau) - 1.5 / tau));
	};
	const sig = tw * Math.sqrt(2 / Pe);
	const a0 = c * tw;
	const d = t - tw;
	const bp = [Math.log(1e-16), Math.log(a0 * a0 / 60), Math.log(a0 * a0 / 6), Math.log(6 * a0 * a0), Math.log(t)];
	for (const k of [-8, -4, -2, -1, 0, 1, 2, 4, 8]) {
		const tau = d + k * sig;
		if (tau > 1e-16 && tau < t) bp.push(Math.log(tau));
	}
	const xs = bp.filter(Number.isFinite).sort((x, y) => x - y);
	const J = (alone ? [0] : [0, 1, 2]).map((m) => {
		const f = part(m);
		const fa = (x) => Math.abs(f(x));
		let size = 0;
		let sum = 0;
		for (let k = 0; k + 1 < xs.length; k++) if (xs[k + 1] > xs[k]) size += quadAbs(fa, xs[k], xs[k + 1], 1e-4, 1e-300, 6);
		if (!(size > 1e-250)) return 0;
		for (let k = 0; k + 1 < xs.length; k++) if (xs[k + 1] > xs[k]) sum += quadAbs(f, xs[k], xs[k + 1], 1e-13, 1e-16 * size);
		return sum;
	});
	const e = Math.exp(-lam * t);
	return alone ? [e * J[0]] : [e * J[0], e * (J[1] - lam * J[0]), e * (J[2] - 2 * lam * J[1] + lam * lam * J[0])];
}

/** One nuclide in a tube 100 a long with a 1 m matrix that takes up little
    (a_w 0.2 1/m, De 1e-5, eps 0.005): a sharp front at Pe 1e5 or 1e6. */
const TUBE = { tw: 100, aw: 0.2, R: 0.005, De: 1e-5, lam: LN2 / 1e6 };
const tubePath = (Pe) => L.preparePath({ tw: 100, f: 20, rho_m: 2700, pe: Pe, pen_dep: 1, kd_f: 0, eps_m: 0.005,
	kd_m: 0, de_m: 1e-5 }, L.decayTable([LN2 / 1e6]));

/** h at Pe 1e5 at 14 times across the front: the subordination integral at 40
    digits (mpmath, quadrature in ln tau with break points; the same at 60). */
const TUBE_REF = [[97.0, 7.7425173134802672717e-11], [97.5, 1.0003730354311338361e-7], [97.9, 1.1670634165061735854e-5],
	[98.3, 5.8050957020603802405e-4], [99.0, 0.071743739914590541379], [99.5, 0.47594316089825745417],
	[99.9, 0.8671308692850578021], [100.0, 0.88853639316213341001], [100.02, 0.88754487363082356384],
	[100.052, 0.88229307770110894935], [100.1, 0.86615182604107402573], [100.3, 0.70913263206761010465],
	[101.0, 0.075737186734056615885], [103.0, 2.5422010804685433653e-4]];
const TUBE_PEAK = 0.88853639316213341001;

test('plug flow: ln T at s from 1 to 1e8 is its closed form, one delay taken out of members whose Rf differ', () => {
	// Under plug flow the transform lacks the pair's delay e^(-TW Rmin s); what
	// is left must not be formed as g - Rmin s, which leaves it with the
	// rounding of Rmin s where the saddles lie right after the delay (s of 1e4
	// and more). ln T from evalBlock, held scaled, over |ln T|.
	const I = L._internal;
	const lnT = (path, i, j, s) => {
		I.evalBlock(path, path.ws, I.blockOf(path, i, j), s, 0, I.RELEASE);
		return Math.log(I.RE) - path.ws.E;
	};
	const S = [1, 1e2, 1e4, 1e5, 1e6, 1e7, 1e8];
	for (const [label, p, n] of [
		['a matrix without end', { tw: 50.27, aw: 0.3922, eps: 1.888e-4, x0: Infinity }, { th: 13.05, kd: 3.703e-4, de: 1.508e-6, ka: 0 }],
		['fracture sorption', { tw: 100, aw: 1500, eps: 0.005, x0: Infinity }, { th: 7.6e4, kd: 0.01, ka: 0.002, de: 5e-6 }],
		['a finite matrix', { tw: 119.84, aw: 380.5, eps: 1.085e-4, x0: 0.0817 }, { th: 2.727e5, kd: 0, de: 3.157e-3, ka: 0 }],
	]) {
		const path = L.preparePath({ surface: 'aw', aw: p.aw, tw: p.tw, rho_m: 2700, pe: Infinity, pen_dep: p.x0, kd_f: n.ka,
			eps_m: p.eps, kd_m: n.kd, de_m: n.de }, L.decayTable([LN2 / n.th]));
		const R = p.eps + n.kd * 2700;
		const lam = LN2 / n.th;
		const Rf = 1 + n.ka * p.aw;
		let worst = 0;
		for (const s of S) {
			const u = Math.sqrt(R * (s + lam) / n.de);
			const tau = Number.isFinite(p.x0) ? u * Math.tanh(p.x0 * u) : u;
			const want = -p.tw * Rf * lam - p.tw * p.aw * n.de * tau;
			worst = Math.max(worst, Math.abs(lnT(path, 0, 0, s) - want) / Math.max(1, Math.abs(want)));
		}
		below(worst, 1e-14, `plug flow, ${label}: ln T against its closed form, over |ln T|`);
	}
	// A parent into a daughter that the fracture holds back more: one delay,
	// TW Rmin s, taken out of both, the daughter keeping (Rf - Rmin) s of its
	// own. Divided differences of H are the same for points shifted alike, so
	// with an unlimited matrix T_21 = G_21 (H(g_2) - H(g_1))/(g_2 - g_1), H(g) =
	// e^(-TW g), g_p = Rf_p lambda_p + (Rf_p - Rmin) s + aw De tau_p and G_21 =
	// A_21 (Rf_1 + aw Rm_1/(tau_1 + tau_2)): the closed form of the two.
	const tw = 100;
	const aw = 1000;
	const kdf = [1e-4, 5e-4];
	const kdm = [1e-3, 0.01];
	const De = [1e-5, 2e-5];
	const lam = [LN2 / 2.4e5, LN2 / 3e3];
	const path = L.preparePath({ surface: 'aw', aw, tw, rho_m: 2700, pe: Infinity, pen_dep: Infinity, kd_f: kdf, eps_m: 0.005,
		kd_m: kdm, de_m: De }, L.decayTable(lam, [[0, 1, lam[0]]]));
	const Rf = kdf.map((k) => 1 + k * aw);
	const Rm = kdm.map((k) => 0.005 + k * 2700);
	const Rmin = Math.min(...Rf);
	let worst = 0;
	for (const s of S) {
		const tau = [0, 1].map((p) => Math.sqrt(Rm[p] * (s + lam[p]) / De[p]));
		const g = [0, 1].map((p) => Rf[p] * lam[p] + (Rf[p] - Rmin) * s + aw * De[p] * tau[p]);
		const G21 = -lam[0] * (Rf[0] + aw * Rm[0] / (tau[0] + tau[1]));
		const a = Math.min(...g);
		const d = Math.abs(g[1] - g[0]);
		const want = Math.log(-G21) - tw * a + Math.log(-Math.expm1(-tw * d) / d);
		worst = Math.max(worst, Math.abs(lnT(path, 1, 0, s) - want) / Math.max(1, Math.abs(want)));
	}
	below(worst, 1e-13, 'plug flow, a daughter held back more than its parent: ln T_21 against its closed form, over |ln T|');
});

test('plug flow: a spike right after the delay, against the classical solution and the Bromwich integral', () => {
	// A matrix without end, a nuclide it barely holds: the whole response lies
	// within 1e-4 a of the delay. The classical closed form at t less the delay
	// as the path forms it, by the parabola of each time and in the table.
	{
		const tw = 50.27;
		const aw = 0.3922;
		const R = 1.888e-4 + 3.703e-4 * 2700;
		const De = 1.508e-6;
		const lam = LN2 / 13.05;
		const path = L.preparePath({ surface: 'aw', aw, tw, rho_m: 2700, pe: Infinity, pen_dep: Infinity, kd_f: 0,
			eps_m: 1.888e-4, kd_m: 3.703e-4, de_m: De }, L.decayTable([lam]));
		const k = tw * aw * Math.sqrt(De * R);
		const d = tw;
		const exact = (u) => Math.exp(-lam * (u + d)) * neret(u, k);
		const up = k * k / 6;
		const ts = logGrid(up / 20, up * 1e4, 61).map((u) => d + u);
		below(worstRel(ts, ts.map((t) => L.responseAt(path, 0, 0, t).h), ts.map((t) => exact(t - d)), 1e-6), 1e-12,
			'a spike 1e-4 a after the delay, against the classical solution above 1e-6 of the peak');
		const r = L.unitResponse(path, 0, 0);
		let w = 0;
		for (let q = 0; q < r.t.length; q++) w = Math.max(w, Math.abs(r.h[q] - exact(r.t[q] - d)));
		below(w / r.peak, 1e-12, '  the tabulated response at its samples, over the peak');
	}
	// A finite matrix that fills at once: a Gaussian 0.008 a wide, 0.40 a
	// after the delay. The Bromwich integral of the closed-form transform on
	// the imaginary axis, (1/pi) int_0^inf Re[e^(i w u) T(i w)] dw, by
	// Gauss-Kronrod in pieces of a few turns (T(i w) dies by w = 2000).
	{
		const tw = 119.84;
		const aw = 380.5;
		const x0 = 0.0817;
		const R = 1.085e-4;
		const De = 3.157e-3;
		const lam = LN2 / 2.727e5;
		const path = L.preparePath({ surface: 'aw', aw, tw, rho_m: 2700, pe: Infinity, pen_dep: x0, kd_f: 0, eps_m: R,
			kd_m: 0, de_m: De }, L.decayTable([lam]));
		const d = tw;
		const lnT = (w) => { // ln T(i w), the delay taken out: -tw lam - tw aw De sqrt(z) tanh(x0 sqrt z), z = R (i w + lam)/De
			const zr = R * lam / De;
			const zi = R * w / De;
			const rr = Math.hypot(zr, zi);
			const ur = Math.sqrt((rr + zr) / 2);
			const ui = Math.sqrt((rr - zr) / 2);
			const e = Math.exp(-2 * x0 * ur);
			const c2 = Math.cos(2 * x0 * ui);
			const s2 = Math.sin(2 * x0 * ui);
			const nr = 1 - e * c2;
			const ni = e * s2;
			const dr = 1 + e * c2;
			const di = -e * s2;
			const dd = dr * dr + di * di;
			const tr = (nr * dr + ni * di) / dd;
			const ti = (ni * dr - nr * di) / dd;
			return [-tw * lam - tw * aw * De * (ur * tr - ui * ti), -tw * aw * De * (ur * ti + ui * tr)];
		};
		let W = 1;
		while (Math.exp(lnT(W)[0]) > 1e-22) W *= 2;
		const bromwich = (u) => {
			const f = (w) => { const l = lnT(w); return Math.exp(l[0]) * Math.cos(w * u + l[1]); };
			const pieces = Math.max(16, Math.ceil(W * u / Math.PI));
			let sum = 0;
			for (let q = 0; q < pieces; q++) sum += quadAbs(f, W * q / pieces, W * (q + 1) / pieces, 1e-13, 2e-15 * W / pieces);
			return sum / Math.PI;
		};
		// at t less the delay as the path forms it: t = d + u keeps fewer digits of u
		const us = Array.from({ length: 19 }, (_, q) => 0.37 + 0.004 * q);
		const want = us.map((u) => bromwich((d + u) - d));
		const pk = Math.max(...want);
		let w = 0;
		us.forEach((u, q) => { w = Math.max(w, Math.abs(L.responseAt(path, 0, 0, d + u).h - want[q])); });
		below(w / pk, 5e-14, 'a matrix that fills at once: the spike against the Bromwich integral, over the peak');
		const r = L.unitResponse(path, 0, 0);
		let wr = 0;
		let m = 0;
		for (let q = 0; q < r.t.length; q++) {
			const u = r.t[q] - d;
			if (u < 0.37 || u > 0.442) continue;
			m++;
			wr = Math.max(wr, Math.abs(r.h[q] - bromwich(u)));
		}
		assert(m > 10, `${m} samples across the spike`);
		below(wr / pk, 5e-13, '  the tabulated response at its samples across the spike, over the peak');
	}
});

test('plug flow, a chain with a thin matrix: the parabola is right or says it has not converged', () => {
	// Each member's own transform can exceed the chain's response and turn
	// thousands of times faster along the path than it. Once, under plug flow,
	// the step followed only the response's own phase, and two sums, both too
	// coarse, agreed on values 1e-4 and 2e-5 off with an error estimate of
	// 1e-15. Against de Hoog's method at 120 and 240 terms, at six times.
	const I = L._internal;
	const path = pageCase(pageInput({ tw: 2741.36, Pe: Infinity, aw: 4.401, eps: 0.0138, x0: 0.001016 }, [
		{ name: 'N0', thalf: 6234.3, kd: 0.0078128, ka: 0.00096121, de: 1.1566e-7, daughter: true },
		{ name: 'N1', thalf: 9884.0, kd: 0.031940, ka: 0.00096121, de: 2.1815e-5, daughter: true },
		{ name: 'N2', thalf: 2.7713e8, kd: 0.35151, ka: 0.00096121, de: 1.4778e-4, daughter: true },
		{ name: 'N3', thalf: 355.60, kd: 0, ka: 0.00096121, de: 1.1650e-5 }]));
	let silent = 0;
	let off = 0;
	for (const [i, j, tts] of [[1, 0, [72.5, 72.695, 72.9]], [2, 1, [1085, 1089.4, 1095]]]) {
		const pr = I.pairOf(path, i, j, 'release');
		const ax = I.axisOf(path, pr);
		const { opt } = cellOptions(ax);
		const cells = I.makeCells(path, ax, opt);
		for (const tt of tts) {
			const t = pr.shift + tt;
			const a = I.invertDeHoog(path, path.ws, pr, t, { M: 120 });
			const b = I.invertDeHoog(path, path.ws, pr, t, { M: 240 });
			const tol = 1e-9 * Math.abs(b) + 1e2 * Math.abs(a - b);
			const own = I.invertParabola(path, path.ws, ax, t);
			if (Number.isFinite(own.h) && !(own.err > 1e-6 * Math.abs(own.h)) && Math.abs(own.h - b) > tol) silent++;
			const s = I.invertShared(path, path.ws, cells, t);
			if (!s || Math.abs(s.h - b) > tol) off++;
			const r = L.responseAt(path, i, j, t);
			if (Math.abs(r.h - b) > tol) off++;
		}
	}
	assert(silent === 0, `${silent} parabolas converged on a wrong value`);
	assert(off === 0, `${off} answers from the cells or responseAt off`);
});

test('a sharp front without the matrix (Pe 1e5): the rising edge, from 1e-12 of the peak, is the inverse Gaussian', () => {
	// The real-axis table once stopped where ln T fell below -900, at 97.9 a
	// here: the response was zero before it.
	const lam = LN2 / 1e6;
	const path = L.preparePath({ tw: 100, f: 0, rho_m: 2700, pe: 1e5, pen_dep: 1, kd_f: 0, eps_m: 0.005, kd_m: 0, de_m: 0 },
		L.decayTable([lam]));
	const r = L.unitResponse(path, 0, 0, { tMax: 1e6 });
	const pk = Math.exp(-lam * 100) * ig(100, 100, 1e5);
	let w = 0;
	let first = Infinity;
	for (let q = 0; q < r.t.length && r.t[q] <= 100; q++) {
		const v = Math.exp(-lam * r.t[q]) * ig(r.t[q], 100, 1e5);
		if (v < 1e-12 * pk) continue;
		first = Math.min(first, r.t[q]);
		w = Math.max(w, Math.abs(r.h[q] - v) / v);
	}
	assert(r.t[0] < first, `the response starts at ${r.t[0]}`);
	below(w, 1e-10, 'its rising edge against the inverse Gaussian, relative, from 1e-12 of the peak');
});

test('a weak singularity next to a sharp front (Pe 1e5): the 40-digit values, the rising edge and the mass balance', () => {
	// The first pole of tanh in the matrix term lies within 0.01 of the saddles
	// just after the front; its residue (aw De = 2e-6) hardly shows in the
	// response, but it bounds a uniform trapezoidal step, and a parabola once
	// exhausted its budget at every time after the peak, 17 % off. Nodes
	// spaced as c sinh(u) need a few hundred evaluations there.
	const I = L._internal;
	const pk = TUBE_PEAK;
	const params = { ...TUBE, Pe: 1e5 };
	let wsub = 0;
	for (const [t, want] of TUBE_REF) wsub = Math.max(wsub, Math.abs(subordination(params, t, true)[0] - want) / pk);
	below(wsub, 1e-13, 'the subordination integral here against the 40-digit values, over the peak');
	const path = tubePath(1e5);
	const ax = I.axisOf(path, I.pairOf(path, 0, 0, 'release'));
	const sup = I.responseSupport(ax, ax.tLo, 1e12);
	const cells = I.makeCells(path, ax, { atol: 1e-3 * I.RESP_ATOL * Math.exp(sup.logPeak), peak: Math.exp(sup.logPeak) });
	let wa = 0;
	let wo = 0;
	let wc = 0;
	let most = 0;
	for (const [t, want] of TUBE_REF) {
		wa = Math.max(wa, Math.abs(L.responseAt(path, 0, 0, t).h - want) / pk);
		const n0 = path.ws.evaluations;
		const o = I.invertParabola(path, path.ws, ax, t);
		most = Math.max(most, path.ws.evaluations - n0);
		wo = Math.max(wo, Number.isFinite(o.err) ? Math.abs(o.h - want) / pk : Infinity);
		const s = I.invertShared(path, path.ws, cells, t);
		wc = Math.max(wc, s ? Math.abs(s.h - want) / pk : Infinity);
	}
	below(wa, 1e-12, 'responseAt at the 14 times from 97 to 103 a, over the peak');
	below(wo, 1e-12, `  the parabola of each time (at most ${most} evaluations)`);
	below(wc, 1e-12, '  and the shared parabolas');
	// h, h' and h'' after the peak, each over its largest value there
	const ts = [100.02, 100.052, 100.1, 100.2, 100.3, 100.5, 100.7, 101, 101.5, 102, 103];
	const want = ts.map((t) => subordination(params, t));
	const top = [0, 1, 2].map((m) => Math.max(...want.map((v) => Math.abs(v[m]))));
	let e3 = 0;
	ts.forEach((t, q) => {
		const r = L.responseAt(path, 0, 0, t);
		e3 = Math.max(e3, Math.abs(r.h - want[q][0]) / top[0], Math.abs(r.dh - want[q][1]) / top[1], Math.abs(r.d2 - want[q][2]) / top[2]);
	});
	below(e3, 1e-11, '  h, h\' and h\'\' after the peak against the subordination integral, each over its largest');
	// The tabulated response: every sample by a parabola, the rising edge down
	// to 1e-12 of the peak (the real-axis table once ended where ln T fell
	// below -900, and the response was zero before 97.9 a), the 40-digit values
	// between its samples, and its mass balance (once 1e-6 short).
	const r = L.unitResponse(path, 0, 0, { tMax: 1e6 });
	assert(r.shared.dehoog === 0, `samples went to de Hoog's method: ${JSON.stringify(r.shared)}`);
	let wr = 0;
	let first = Infinity;
	for (let q = 0; q < r.t.length && r.t[q] <= 104; q++) {
		const t = r.t[q];
		if (ig(t, TUBE.tw, 1e5) < 1e-15 * pk) continue; // before the edge (the matrix only delays)
		const v = subordination(params, t, true)[0];
		if (v < 1e-12 * pk) continue;
		first = Math.min(first, t);
		wr = Math.max(wr, Math.abs(r.h[q] - v) / Math.max(Math.abs(v), 1e-6 * pk));
	}
	assert(r.t[0] < first && r.h[0] < 1e-12 * pk, `the response starts at ${r.t[0]}, ${(r.h[0] / pk).toExponential(1)} of the peak`);
	below(wr, 1e-10, '  the tabulated response up to 104 a, relative above 1e-6 of the peak and over 1e-6 of it below');
	let wi = 0;
	for (const [t, v] of TUBE_REF) {
		let k = 0;
		while (k + 2 < r.t.length && r.t[k + 1] <= t) k++;
		wi = Math.max(wi, Math.abs(I.hermite5(r.t[k], r.h[k], r.dh[k], r.d2h[k], r.t[k + 1], r.h[k + 1], r.dh[k + 1], r.d2h[k + 1], t) - v) / pk);
	}
	below(wi, 1e-9, '  between its samples at the 14 times, over the peak');
	assert(r.balanced, `the mass balance misses by ${r.rel}`);
	below(Math.abs(r.integral - r.expected) / r.T0, 1e-9, '  its integral against what leaves by its last time, over T(0)');
});

test('the same tube at Pe 1e6: its mass balance, in a second or so', () => {
	// It once took two and a half minutes and missed its mass balance by 6 %.
	const path = tubePath(1e6);
	const t0 = Date.now();
	const r = L.unitResponse(path, 0, 0, { tMax: 1e6 });
	const ms = Date.now() - t0;
	assert(ms < 8000, `${ms} ms`);
	assert(r.balanced, `the mass balance misses by ${r.rel}`);
	below(Math.abs(r.integral - r.expected) / r.T0, 1e-9, 'Pe 1e6: the integral against what leaves by its last time, over T(0)');
	let w = 0;
	for (const t of [100, 100.1, 100.3, 101, 105, 110]) {
		const q = r.t.findIndex((x) => x >= t);
		w = Math.max(w, Math.abs(r.h[q] - subordination({ ...TUBE, Pe: 1e6 }, r.t[q], true)[0]) / r.peak);
	}
	below(w, 1e-12, '  the response near the front against the subordination integral, over the peak');
});

test('responseAt never returns a parabola that failed: de Hoog\'s method at twice its terms takes over', () => {
	const I = L._internal;
	// far out in a long tail the parabola does not converge (its terms cancel
	// or grow back): there responseAt answers with de Hoog's method, and its
	// error estimate
	const tail = chainOf({ tw: 50, f: 1e3, rho_m: 2700, pe: 300, pen_dep: Infinity, kd_f: 0, eps_m: 0.002, kd_m: [0], de_m: 1e-5 }, [Infinity]);
	const ax = I.axisOf(tail, I.pairOf(tail, 0, 0, 'release'));
	let replaced = 0;
	for (const t of logGrid(1e10, 1e11, 9)) {
		const own = I.invertParabola(tail, tail.ws, ax, t);
		const r = L.responseAt(tail, 0, 0, t);
		assert(Number.isFinite(r.h) && Number.isFinite(r.err), `at ${t}: h ${r.h}, err ${r.err}`);
		if (!(Number.isFinite(own.h) && !(own.err > 1e-6 * Math.abs(own.h)))) {
			replaced++;
			const M = Math.min(2 * I.deHoogTerms(tail, ax, t), 320);
			assert(r.h === I.invertDeHoog(tail, tail.ws, ax.pr, t, { M }), `at ${t} the answer is not de Hoog's`);
		}
	}
	assert(replaced > 0, 'no time where the parabola failed');
	// ...and across the sharp front and its tail every answer passes
	const path = tubePath(1e5);
	for (const t of logGrid(96, 1e4, 60)) {
		const r = L.responseAt(path, 0, 0, t);
		assert(Number.isFinite(r.h) && Number.isFinite(r.err) && !(r.err > 1e-6 * Math.abs(r.h)), `at ${t}: h ${r.h}, err ${r.err}`);
	}
});

// ---------------------------------------------------------------------------
// Kompartment's own discretised block
// ---------------------------------------------------------------------------

/**
 * A made-up branched chain through a path of Kompartment's own, on cells, and
 * the same path semi-analytically. The decay table comes from the model's
 * decay data exactly as the builder makes it, so the two solve the same
 * network. The release face is read inside the grid, extra cells past it
 * standing for the rock that goes on; the matrix starts with a thin layer.
 */
function discretisedCase({ nucs, half, chains, kdf, kdm, dem, inflow, times }) {
	const path0 = { tw: 50, f: 5e4, rho_m: 2700, pe: 10, pen_dep: 0.1, eps_m: 0.005 };
	const lut = (pts) => `interpolationUseEndValues(time(), ${pts.map((p) => p.join(', ')).join(', ')})`;
	const model = (nf, nb, nm, d0) => ({
		name: 'discretised', simulation: {
			start_time: 0, end_time: times[times.length - 1], spacing: 'series',
			output_times: [{ kind: 'times', times }], solver: 'ndf', rtol: 1e-8, abstol: 1e-14, time_unit: 'year',
		},
		nuclides: nucs, half_lives: half, chains, decay_unit: 'mol', compartments: [],
		inflows: [{
			name: 'In', to: 'Rock', rate: '0', index_lists: ['Radionuclides'],
			entries: Object.entries(inflow).map(([x, pts]) => ({ index: { Radionuclides: x }, rate: lut(pts) })),
		}],
		farfields: [{
			name: 'Rock', index_lists: ['Radionuclides'], to: null,
			tw: String(path0.tw), f: String(path0.f), kd_f: '0', kd_m: '0', de_m: '0', eps_m: String(path0.eps_m),
			rho_m: String(path0.rho_m), pe: String(path0.pe), pen_dep: String(path0.pen_dep), pen_dep_0: String(d0),
			n_f: nf, n_m: nm, o_b: 1, n_b: nb, handle_decay: true, report_cells: false,
			entries: nucs.map((x, i) => ({
				index: { Radionuclides: x }, kd_f: String(kdf[i]), kd_m: String(kdm[i]), de_m: String(dem[i]),
			})),
		}],
	});
	const dm = new Project(model(4, 0, 2, 1e-3)).decayModel();
	const pairs = [];
	dm.parents.forEach((ps, d) => { for (const p of ps) pairs.push([p.index, d, p.lambda * p.ratio]); });
	const path = L.preparePath({ ...path0, kd_f: kdf, kd_m: kdm, de_m: dem }, L.decayTable(dm.lambdas, pairs), { names: nucs });
	const R = L.unitResponses(path, { kinds: ['release'], tMax: 2 * times[times.length - 1] });
	const inflows = nucs.map((x) => (inflow[x] ? L.inflowSeries([...inflow[x], [times[times.length - 1] * 10, inflow[x].at(-1)[1]]]) : null));
	const semi = times.map((t) => L.releaseAt(path, R, inflows, t));
	/** The worst relative difference above a tenth of each nuclide's peak. */
	const against = (nf, nb, nm, d0) => {
		const res = run(model(nf, nb, nm, d0));
		const outs = res.outputs().filter((o) => o.block === 'Rock');
		const T = Array.from(res.t);
		let worst = 0;
		nucs.forEach((x, i) => {
			const got = res.series(outs.find((o) => o.nuclide === x));
			let pk = 0;
			for (const v of semi) pk = Math.max(pk, v[i]);
			times.forEach((t, k) => {
				const at = T.findIndex((tv) => Math.abs(tv - t) <= 1e-9 * t);
				assert(at >= 0, `${t} is not in the output grid`);
				if (semi[k][i] > 0.1 * pk) worst = Math.max(worst, Math.abs(got[at] - semi[k][i]) / semi[k][i]);
			});
		});
		return worst;
	};
	return { path, semi, against };
}

test('Kompartment’s discretised block approaches it as the fracture is refined', () => {
	// A parent that branches into two daughters of their own chemistry, each
	// with sorption on the fracture surfaces.
	const c = discretisedCase({
		nucs: ['Aa-1', 'Bb-2', 'Cc-3'],
		half: { 'Aa-1': 2000, 'Bb-2': 800, 'Cc-3': 5000 },
		chains: [['Aa-1', 'Bb-2', 0.6], ['Aa-1', 'Cc-3', 0.4]],
		kdf: [2e-4, 5e-4, 1e-4], kdm: [1e-3, 3e-3, 5e-4], dem: [1e-4, 2e-4, 1e-4],
		inflow: { 'Aa-1': [[0, 0], [200, 1], [1500, 1], [2000, 0]] },
		times: logGrid(100, 3e4, 15),
	});
	const coarse = c.against(20, 20, 15, 2e-4);
	const fine = c.against(40, 20, 15, 2e-4);
	assert(fine < coarse / 2.5, `the difference fell from ${coarse.toExponential(2)} to only ${fine.toExponential(2)}`);
	below(fine, 0.06, 'forty fracture cells, above a tenth of the peak');
});

slow('Kompartment’s discretised block converges to it: a branch that merges again, three refinements', () => {
	const c = discretisedCase({
		nucs: ['Aa-1', 'Bb-2', 'Cc-3', 'Dd-4'],
		half: { 'Aa-1': 2000, 'Bb-2': 800, 'Cc-3': 5000, 'Dd-4': 30000 },
		chains: [['Aa-1', 'Bb-2', 0.6], ['Aa-1', 'Cc-3', 0.4], ['Bb-2', 'Dd-4', 1], ['Cc-3', 'Dd-4', 1]],
		kdf: [2e-4, 5e-4, 1e-4, 0], kdm: [1e-3, 3e-3, 5e-4, 2e-3], dem: [1e-4, 2e-4, 1e-4, 5e-5],
		inflow: { 'Aa-1': [[0, 0], [200, 1], [1500, 1], [2000, 0]], 'Cc-3': [[0, 0.2]] },
		times: logGrid(10, 1e5, 41),
	});
	const errs = [[20, 20, 20, 2e-4], [40, 40, 30, 1e-4], [80, 40, 30, 1e-4]].map((g) => c.against(...g));
	assert(errs[1] < errs[0] / 2.5 && errs[2] < errs[1] / 2.5, `no convergence: ${errs.map((e) => e.toExponential(2)).join(', ')}`);
	below(errs[2], 0.02, 'eighty fracture cells, above a tenth of the peak');
});

// ---------------------------------------------------------------------------
// The block itself, method 'semi-analytical', run with the rest of a model
// ---------------------------------------------------------------------------

const GL8_X = [-0.9602898564975363, -0.7966664774136267, -0.525532409916329, -0.1834346424956498,
	0.1834346424956498, 0.525532409916329, 0.7966664774136267, 0.9602898564975363];
const GL8_W = [0.1012285362903763, 0.2223810344533745, 0.3137066458778873, 0.362683783378362,
	0.362683783378362, 0.3137066458778873, 0.2223810344533745, 0.1012285362903763];

/** A tabulated response's quintic Hermite piece k at u. */
function hermiteAt(r, k, u) {
	const d = r.t[k + 1] - r.t[k];
	const x = (u - r.t[k]) / d;
	const x2 = x * x; const x3 = x2 * x; const x4 = x3 * x; const x5 = x4 * x;
	const h0 = 1 - 10 * x3 + 15 * x4 - 6 * x5; const h1 = x - 6 * x3 + 8 * x4 - 3 * x5;
	const h2 = 0.5 * (x2 - 3 * x3 + 3 * x4 - x5); const h4 = -4 * x3 + 7 * x4 - 3 * x5;
	const h5 = 0.5 * (x3 - 2 * x4 + x5);
	return h0 * r.h[k] + d * h1 * r.dh[k] + d * d * h2 * r.d2h[k]
		+ (1 - h0) * r.h[k + 1] + d * h4 * r.dh[k + 1] + d * d * h5 * r.d2h[k + 1];
}

/**
 * integral h(u) in(t - u) du for a response tabulated as {t, h, dh, d2h} and
 * an inflow known as a function: eight-point Gauss-Legendre on every piece,
 * split where the inflow could change by more than a factor e across one.
 * `rate` is the fastest the inflow varies at, 1/[time].
 */
function convolveExactly(r, inflow, t, rate, from = 0) {
	let s = 0;
	for (let k = 0; k + 1 < r.t.length; k++) {
		const a = r.t[k];
		const b = Math.min(r.t[k + 1], t - from);
		if (!(b > a)) break;
		const parts = Math.max(1, Math.ceil((b - a) * rate / 0.5));
		for (let p = 0; p < parts; p++) {
			const lo = a + (b - a) * p / parts;
			const hi = a + (b - a) * (p + 1) / parts;
			const c = 0.5 * (lo + hi);
			const hw = 0.5 * (hi - lo);
			for (let g = 0; g < 8; g++) {
				const u = c + GL8_X[g] * hw;
				s += GL8_W[g] * hw * hermiteAt(r, k, u) * inflow(t - u);
			}
		}
	}
	return s;
}

/**
 * The Bateman solution of a compartment that leaches at rate k along the
 * model's own decay table, from `A0` of the first nuclide: A_i(t) = sum_m
 * C[i][m] e^(-(k + lambda_m) t). Distinct decay constants.
 */
function leached(dec, n, A0, first = 0) {
	const C = Array.from({ length: n }, () => new Array(n).fill(0));
	C[first][first] = A0;
	const order = Array.from({ length: n }, (_, i) => i);
	for (const i of order) {
		for (let q = 0; q < dec.icnt[i]; q++) {
			const p = dec.ipar[dec.ioff[i] + q];
			const c = dec.icoef[dec.ioff[i] + q];
			for (let m = 0; m < n; m++) {
				if (C[p][m] === 0) continue;
				const f = c * C[p][m] / (dec.lam[i] - dec.lam[m]);
				C[i][m] += f;
				C[i][i] -= f;
			}
		}
	}
	return (i, t, k) => {
		let s = 0;
		for (let m = 0; m < n; m++) s += C[i][m] * Math.exp(-(k + dec.lam[m]) * t);
		return s;
	};
}

/** The decay table a model's path runs on, as the builder makes it. */
function decayOfModel(raw) {
	const dm = new Project(structuredClone(raw)).decayModel();
	const pairs = [];
	dm.parents.forEach((ps, d) => { for (const p of ps) pairs.push([p.index, d, p.lambda * p.ratio]); });
	return { names: dm.names, dec: L.decayTable(dm.lambdas, pairs) };
}

const EXAMPLE = `${HERE}../examples/farfield.json`;

/**
 * One block's series at the given times -- the first row at each, since an
 * event or a jump adds rows of its own and the rows do not line up by index.
 */
function seriesAt(res, block, nuclide, times) {
	const o = res.outputs().find((x) => x.block === block && (nuclide == null || x.nuclide === nuclide));
	assert(o, `no series for ${block}${nuclide ? ` [${nuclide}]` : ''}`);
	const s = res.series(o);
	const T = res.t;
	let q = 0;
	return times.map((t) => {
		while (q < T.length && T[q] < t * (1 - 1e-12)) q++;
		assert(q < T.length && Math.abs(T[q] - t) <= 1e-9 * Math.max(1, t), `no row at ${t}`);
		return s[q];
	});
}

test('the far-field example worked out semi-analytically is its analytic inflow convolved exactly', () => {
	// The vault leaches at 1e-4 a year and decays along U-238 > U-234 >
	// Th-230, so what enters the path is a sum of exponentials: the release
	// is those convolved with the path's responses, by quadrature here.
	const model = JSON.parse(readFileSync(EXAMPLE, 'utf8'));
	model.farfields[0].method = 'semi-analytical';
	const times = logGrid(3e3, 1e6, 25);
	model.simulation.output_times = [{ kind: 'times', times }];
	model.simulation.spacing = 'series';
	const res = run(structuredClone(model));
	const { names, dec } = decayOfModel(model);
	const n = names.length;
	const kd = { 'U-238': 0.0017, 'U-234': 0.0017, 'Th-230': 0.05 };
	const path = L.preparePath({
		tw: 50, f: 1e5, rho_m: 2700, pe: 10, pen_dep: 12.5, kd_f: 0, eps_m: 0.0018,
		kd_m: names.map((x) => kd[x]), de_m: 3.15e-5,
	}, dec, { names });
	const R = L.unitResponses(path, { kinds: ['release'], tMax: 1e6 });
	const vault = leached(dec, n, 1e12, names.indexOf('U-238'));
	const fastest = 1e-4 + Math.max(...dec.lam);
	for (let i = 0; i < n; i++) {
		const got = seriesAt(res, 'Rock', names[i], times);
		const want = times.map((t) => {
			let s = 0;
			for (let j = 0; j < n; j++) {
				const r = R.release[i * n + j];
				if (r) s += convolveExactly(r, (tau) => 1e-4 * vault(j, tau, 1e-4), t, fastest);
			}
			return s;
		});
		below(worstRel(times, got, want, 1e-4), 1e-6, `the release of ${names[i]}`);
	}
});

test('the far-field example worked out semi-analytically against FARF31 itself', () => {
	// FARF31 1.2's own output for this example, in amounts: times lambda it
	// is the release in becquerels. Its input was the same leaching vault, and
	// what it adds is its own handling of that input (see
	// resources/tests/farf31/README.md), about a part in a thousand.
	const file = `${os.homedir()}/Downloads/Farf31-SKB-new/build-gfortran/ffcmp/out.ts`;
	if (!existsSync(file)) return;
	const blocks = {};
	let at = null;
	for (const line of readFileSync(file, 'utf8').split('\n')) {
		const m = /^\s{2}([A-Z][A-Z0-9]*)\s*$/.exec(line);
		if (m && m[1] !== 'Nuclide') { at = m[1]; blocks[at] = []; continue; }
		const nums = line.trim().split(/\s+/).map(Number);
		if (at && nums.length === 3 && nums.every(Number.isFinite) && nums[0] <= 1e6) blocks[at].push(nums);
	}
	const lam = { U238: 1.551358953804712e-10, U234: 2.82341010411383e-06, TH230: 9.195372520031113e-06 };
	const nuc = { U238: 'U-238', U234: 'U-234', TH230: 'Th-230' };
	const model = JSON.parse(readFileSync(EXAMPLE, 'utf8'));
	model.farfields[0].method = 'semi-analytical';
	const times = [...new Set(Object.values(blocks).flatMap((b) => b.map((r) => r[0])))].sort((a, b) => a - b);
	model.simulation.output_times = [{ kind: 'times', times }];
	model.simulation.spacing = 'series';
	const res = run(model);
	for (const [key, rows] of Object.entries(blocks)) {
		const ts = rows.map((r) => r[0]);
		const want = rows.map((r) => r[1] * lam[key]);
		below(worstRel(ts, seriesAt(res, 'Rock', nuc[key], ts), want, 1e-2), 3e-3, `${nuc[key]} above a hundredth of its peak`);
	}
});

/** A near-field compartment leaching into a path and a compartment downstream of it. */
function chainThroughPath({ method = 'semi-analytical', names, half, chains, kdf, kdm, dem, path, k = 1e-3, A0 = 1000,
	times, decayUnit = 'mol', extra = {} }) {
	return {
		name: 'through a path',
		simulation: {
			start_time: 0, end_time: times[times.length - 1], spacing: 'series', output_times: [{ kind: 'times', times }],
			solver: 'ndf', rtol: 1e-9, abstol: 1e-16, time_unit: 'year', ...(extra.simulation ?? {}),
		},
		nuclides: names, half_lives: half, chains, decay_unit: decayUnit,
		compartments: [
			{ name: 'Near', initial: '0', index_lists: ['Radionuclides'], entries: [{ index: { Radionuclides: names[0] }, initial: String(A0) }] },
			{ name: 'Down', initial: '0', index_lists: ['Radionuclides'] },
			...(extra.compartments ?? []),
		],
		transfers: [
			{ name: 'Leach', from: 'Near', to: 'Rock', rate: String(k), multiply_by_donor: true },
			{ name: 'Out', from: 'Rock', to: 'Down', rate: 'Rock', multiply_by_donor: false, index_lists: ['Radionuclides'] },
			...(extra.transfers ?? []),
		],
		farfields: [{
			name: 'Rock', index_lists: ['Radionuclides'], method, surface: 'f',
			tw: String(path.tw), f: String(path.f), kd_f: '0', kd_m: '0', de_m: '0', eps_m: String(path.eps_m),
			rho_m: String(path.rho_m ?? 2700), pe: String(path.pe), pen_dep: String(path.pen_dep),
			pen_dep_0: String(path.pen_dep_0 ?? ''), n_f: path.n_f ?? 20, n_m: path.n_m ?? 20, o_b: path.o_b ?? 4,
			n_b: path.n_b ?? '', grid: path.grid ?? 'matched', handle_decay: true, report_cells: false,
			entries: names.map((x, i) => ({
				index: { Radionuclides: x }, kd_f: String(kdf[i]), kd_m: String(kdm[i]), de_m: String(dem[i]),
			})),
		}],
		...(extra.blocks ?? {}),
	};
}

test('leaching from a decaying source through the page model’s own responses', () => {
	// in(t) = k A(t), A the Bateman solution of the leaching compartment: the
	// page model FARF31.html tabulates the responses of this unbranched chain
	// (its own made-up chain case), convolved here with that inflow exactly.
	if (!existsSync(PAGE_MODEL)) return;
	const M = createRequire(import.meta.url)(PAGE_MODEL);
	const c = {
		tw: 150, Pe: 15, aw: 800, eps: 0.005, x0: 1.5, nuclides: [
			{ name: 'Am-241', thalf: 432.6, kd: 2.0, de: 4e-6, daughter: true },
			{ name: 'Np-237', thalf: 2.144e6, kd: 0.1, de: 4e-6, daughter: true },
			{ name: 'U-233', thalf: 1.592e5, kd: 0.05, de: 4e-6, daughter: true },
			{ name: 'Th-229', thalf: 7340, kd: 1.0, de: 4e-6 },
		],
	};
	const names = c.nuclides.map((x) => x.name);
	const times = logGrid(1e3, 1e6, 22);
	const k = 1e-4;
	const raw = chainThroughPath({
		names, half: Object.fromEntries(c.nuclides.map((x) => [x.name, x.thalf])),
		chains: [['Am-241', 'Np-237', 1], ['Np-237', 'U-233', 1], ['U-233', 'Th-229', 1]],
		kdf: [0, 0, 0, 0], kdm: c.nuclides.map((x) => x.kd), dem: c.nuclides.map((x) => x.de),
		path: { tw: c.tw, f: c.aw * c.tw, eps_m: c.eps, pe: c.Pe, pen_dep: c.x0 }, k, times,
	});
	const res = run(structuredClone(raw));
	const { dec } = decayOfModel(raw);
	const n = names.length;
	const near = leached(dec, n, 1000, 0);
	const ctx = M.prepare(c);
	const ws = M.makeWorkspace(ctx);
	let compared = 0;
	for (let i = 0; i < n; i++) {
		const got = seriesAt(res, 'Rock', names[i], times);
		const want = times.map(() => 0);
		for (let j = 0; j <= i; j++) {
			const ax = M.realAxis(ctx, ws, i, j, 1e-3, 1e12);
			const sup = M.responseSupport(ctx, ax, 1e-3, 1e12);
			if (!sup) continue;
			const r = M.computeResponse(ctx, ws, ax, sup.tLo, Math.min(sup.tHi, 2e6), { peakEstimate: Math.exp(sup.logPeak) });
			times.forEach((t, q) => { want[q] += convolveExactly(r, (tau) => k * near(j, tau, k), t, k + Math.max(...dec.lam)); });
		}
		// Am-241 decays long before it comes through: nothing, on both sides.
		const most = Math.max(...want);
		if (most < 1e-30) {
			assert(Math.max(...got.map(Math.abs)) < 1e-30, `${names[i]} came through: ${Math.max(...got)}`);
			continue;
		}
		// The page's responses carry their own 2e-8 grid and the 1e-11 of its
		// inversion; the run carries the solver's 1e-9.
		below(worstRel(times, got, want, 1e-4), 1e-6, `the release of ${names[i]}`);
		compared++;
	}
	assert(compared === 3, `${compared} releases compared`);
});

test('what is held, what was delivered and what is left upstream add up to what there was', () => {
	// A parent into a stable daughter, in amounts: every atom is somewhere.
	const times = logGrid(10, 1e5, 30);
	const raw = chainThroughPath({
		names: ['Pp-1', 'Ss-2'], half: { 'Pp-1': 3000, 'Ss-2': 'stable' }, chains: [['Pp-1', 'Ss-2', 1]],
		kdf: [1e-3, 0], kdm: [2e-3, 1e-4], dem: [1e-4, 1e-4],
		path: { tw: 50, f: 5e4, eps_m: 0.005, pe: 10, pen_dep: 0.1 }, times,
	});
	const res = run(raw);
	const sum = new Float64Array(times.length);
	for (const block of ['Near', 'Down', 'Rock held']) {
		for (const x of ['Pp-1', 'Ss-2']) seriesAt(res, block, x, times).forEach((v, q) => { sum[q] += v; });
	}
	let worst = 0;
	for (let q = 0; q < times.length; q++) worst = Math.max(worst, Math.abs(sum[q] / 1000 - 1));
	below(worst, 1e-7, 'upstream + in the path + delivered, against the 1000 put in');
	// ...and it is not trivially so: by the end most of it has come through
	const through = seriesAt(res, 'Down', 'Ss-2', times).at(-1) + seriesAt(res, 'Down', 'Pp-1', times).at(-1);
	assert(through > 100, `only ${through} came through`);
});

test('packages that fail all at once: an inflow that starts with a step', () => {
	// The packages fail at 700. Three tenths of what they hold go at once into
	// a buffer that the path drains at k a year, the rest follows as the waste
	// form degrades: so the inflow into the path jumps from nothing at 700 and
	// is a sum of exponentials after it. One nuclide, so the reference is
	// closed: the unit response convolved with it.
	const lam = LN2 / 5000;
	const I0 = 100;
	const d = 2e-3;
	const k = 5e-3;
	const irf = 0.3;
	const times = logGrid(705, 2e5, 30);
	const raw = {
		name: 'at once',
		simulation: {
			start_time: 0, end_time: 2e5, spacing: 'series', output_times: [{ kind: 'times', times }],
			solver: 'ndf', rtol: 1e-9, abstol: 1e-16, time_unit: 'year',
		},
		nuclides: ['Xx-1'], half_lives: { 'Xx-1': 5000 }, decay_unit: 'mol',
		waste_packages: [{
			name: 'Packages', index_lists: ['Radionuclides'], failure: 'at', fail_at: '700',
			inventory: String(I0), irf: String(irf), degradation_rate: String(d), handle_decay: true,
		}],
		compartments: [
			{ name: 'Buffer', initial: '0', index_lists: ['Radionuclides'] },
			{ name: 'Down', initial: '0', index_lists: ['Radionuclides'] },
		],
		transfers: [
			{ name: 'Carrier', from: 'Packages', to: 'Buffer', rate: 'Packages', multiply_by_donor: false, index_lists: ['Radionuclides'] },
			{ name: 'Leach', from: 'Buffer', to: 'Rock', rate: String(k), multiply_by_donor: true },
			{ name: 'Out', from: 'Rock', to: 'Down', rate: 'Rock', multiply_by_donor: false, index_lists: ['Radionuclides'] },
		],
		farfields: [{
			name: 'Rock', index_lists: ['Radionuclides'], method: 'semi-analytical', surface: 'f',
			tw: '40', f: '4e4', kd_f: '5e-4', kd_m: '1e-3', de_m: '1e-4', eps_m: '0.005', rho_m: '2700', pe: '12',
			pen_dep: '0.2', pen_dep_0: '', n_f: 20, n_m: 20, o_b: 4, n_b: '', grid: 'matched',
			handle_decay: true, report_cells: false,
		}],
	};
	const res = run(raw);
	const path = L.preparePath({ tw: 40, f: 4e4, rho_m: 2700, pe: 12, pen_dep: 0.2, kd_f: 5e-4, eps_m: 0.005, kd_m: 1e-3, de_m: 1e-4 },
		L.decayTable([lam]));
	const r = L.unitResponse(path, 0, 0, { tMax: 3e5 });
	const A7 = I0 * Math.exp(-lam * 700);
	const buffer = (tau) => irf * A7 * Math.exp(-(k + lam) * tau)
		+ (1 - irf) * A7 * d * (Math.exp(-(d + lam) * tau) - Math.exp(-(k + lam) * tau)) / (k - d);
	const want = times.map((t) => convolveExactly(r, (tau) => (tau > 700 ? k * buffer(tau - 700) : 0), t, k + lam, 700));
	below(worstRel(times, seriesAt(res, 'Rock', null, times), want, 1e-4), 1e-6, 'the release');
	// The step is a corner the history keeps: the buffer holds the instant
	// release straight after it.
	const B = seriesAt(res, 'Buffer', null, [705])[0];
	below(Math.abs(B / buffer(5) - 1), 1e-7, 'the buffer just after the failure');
});

test('plug flow into a matrix without end: the point mass at the delay, released as the run goes', () => {
	// Plug flow and an unlimited matrix are written 1/0. A matrix that takes
	// up almost nothing makes the response a spike a hair after the delay,
	// 29 % of it before the first time the response is tabulated at: that
	// part is a point mass, and the run releases it from the recorded inflow
	// (and from the step being taken, when the step is longer than the delay).
	const lam = LN2 / 8.216e5;
	const k = 1e-3;
	const times = logGrid(60, 2e4, 25);
	const raw = {
		name: 'plug flow',
		simulation: {
			start_time: 0, end_time: 2e4, spacing: 'series', output_times: [{ kind: 'times', times }],
			solver: 'ndf', rtol: 1e-9, abstol: 1e-16, time_unit: 'year',
		},
		nuclides: ['Dd-1'], half_lives: { 'Dd-1': 8.216e5 }, decay_unit: 'mol',
		compartments: [
			{ name: 'Near', initial: '1000', index_lists: ['Radionuclides'] },
			{ name: 'Down', initial: '0', index_lists: ['Radionuclides'] },
		],
		transfers: [
			{ name: 'Leach', from: 'Near', to: 'Rock', rate: String(k), multiply_by_donor: true },
			{ name: 'Out', from: 'Rock', to: 'Down', rate: 'Rock', multiply_by_donor: false, index_lists: ['Radionuclides'] },
		],
		farfields: [{
			name: 'Rock', index_lists: ['Radionuclides'], method: 'semi-analytical', surface: 'aw',
			tw: '50.27', aw: '0.3922', kd_f: '0', kd_m: '0', de_m: '1.508e-6', eps_m: '1.888e-4', rho_m: '2700',
			pe: '1/0', pen_dep: '1/0', pen_dep_0: '', n_f: 20, n_m: 20, o_b: 4, n_b: '', grid: 'matched',
			handle_decay: true, report_cells: false,
		}],
	};
	const res = run(raw);
	const path = L.preparePath({ surface: 'aw', aw: 0.3922, tw: 50.27, rho_m: 2700, pe: Infinity, pen_dep: Infinity,
		kd_f: 0, eps_m: 1.888e-4, kd_m: 0, de_m: 1.508e-6 }, L.decayTable([lam]));
	const r = L.unitResponse(path, 0, 0, { tMax: 2e4 });
	assert(r.m0 > 0.2 * r.T0, `the point mass is ${r.m0} of ${r.T0}`);
	const inflow = (tau) => (tau > 0 ? k * 1000 * Math.exp(-(k + lam) * tau) : 0);
	const want = times.map((t) => convolveExactly(r, inflow, t, k + lam) + r.m0 * inflow(t - r.t[0]));
	below(worstRel(times, seriesAt(res, 'Rock', null, times), want, 1e-6), 1e-7, 'the release, the point mass included');
	// and what the path holds, delivered and left upstream add up
	const total = times.map((t, q) => seriesAt(res, 'Near', null, times)[q] + seriesAt(res, 'Down', null, times)[q]
		+ seriesAt(res, 'Rock held', null, times)[q]);
	below(Math.max(...total.map((v, q) => Math.abs(v / (1000 * Math.exp(-lam * times[q])) - 1))), 1e-7, 'the balance');
});

test('an event that does not touch the path leaves its release as it was', () => {
	const times = logGrid(100, 5e4, 20);
	const base = {
		names: ['Aa-1', 'Bb-2'], half: { 'Aa-1': 2000, 'Bb-2': 800 }, chains: [['Aa-1', 'Bb-2', 1]],
		kdf: [2e-4, 5e-4], kdm: [1e-3, 3e-3], dem: [1e-4, 2e-4],
		path: { tw: 50, f: 5e4, eps_m: 0.005, pe: 10, pen_dep: 0.1 }, times,
	};
	const plain = run(chainThroughPath(base));
	// A trigger at 1234 resets a running mean nothing reads: the solver
	// restarts there, and the path has to carry its history across.
	const evented = run(chainThroughPath({
		...base,
		extra: {
			blocks: {
				expressions: [{ name: 'Clock', equation: 'time()', index_lists: [] }],
				triggers: [{ name: 'Go', first: 'time()', second: '1234', direction: 'rising' }],
				running_means: [{ name: 'Mean', target: 'Clock', reset_trigger: 'Go' }],
			},
		},
	}));
	assert((evented.stats?.events ?? 0) >= 1, 'the event did not fire');
	for (const x of base.names) {
		const a = seriesAt(plain, 'Rock', x, times);
		const b = seriesAt(evented, 'Rock', x, times);
		below(worstRel(times, b, a, 1e-6), 1e-6, `the release of ${x}`);
	}
});

test('a sampled travel time: each realisation is the path with that travel time', () => {
	const times = logGrid(200, 2e4, 12);
	const raw = chainThroughPath({
		names: ['Aa-1'], half: { 'Aa-1': 3000 }, chains: [], kdf: [3e-4], kdm: [1e-3], dem: [1e-4],
		path: { tw: 'Tw', f: 5e4, eps_m: 0.005, pe: 10, pen_dep: 0.1 }, times,
	});
	raw.parameters = [{
		name: 'Tw', value: 50, index_lists: [],
		pdf: { kind: 'unif', params: { min: 30, max: 90 }, values: null, trmin: null, trmax: null, inorder: true, pos: 0 },
	}];
	const r = runProbabilistic(structuredClone(raw), { iterations: 3, seed: 7 });
	const k = r.outputs.findIndex((o) => o.block === 'Rock');
	const drawn = r.samples[r.plan.findIndex((e) => e.name === 'Tw')];
	for (let it = 0; it < r.iterations; it++) {
		const one = structuredClone(raw);
		one.parameters[0].value = drawn[it];
		delete one.parameters[0].pdf;
		const res = run(one);
		const want = res.series(res.outputs().find((o) => o.block === 'Rock'));
		const got = Array.from({ length: r.t.length }, (_, q) => r.values[k][it * r.t.length + q]);
		below(worstRel(times, got, Array.from(want), 1e-6), 1e-9, `realisation ${it} (T_w = ${drawn[it].toFixed(2)})`);
	}
});

test('the Jacobian carries the inflow of a step longer than the path takes to let anything through', async () => {
	// Straight after a run the history ends at the last output time; a step
	// from there past the arrival gives the current inflow a weight, and the
	// analytic Jacobian has to say so.
	const times = logGrid(100, 3000, 8);
	const raw = chainThroughPath({
		names: ['Aa-1'], half: { 'Aa-1': 3000 }, chains: [], kdf: [0], kdm: [1e-4], dem: [1e-5],
		path: { tw: 5, f: 5e2, eps_m: 0.005, pe: 20, pen_dep: 0.01 }, k: 1e-2, times,
	});
	const project = new Project(structuredClone(raw));
	const res = run(project);
	const system = res.system;
	const y = Float64Array.from(res.y[res.y.length - 1]);
	const t = 3000 + 60;
	const J = system.jacobian;
	assert(J.available, 'no analytic Jacobian');
	const n = system.layout.nstate;
	const dense = Array.from({ length: n }, () => new Float64Array(n));
	J.evaluateDense(t, y, dense);
	const f0 = Float64Array.from(system.dydt(t, y, new Float64Array(n)));
	let worst = 0;
	let biggest = 0;
	for (let j = 0; j < n; j++) {
		const h = 1e-6 * Math.max(1, Math.abs(y[j]));
		const yp = Float64Array.from(y);
		yp[j] += h;
		const f1 = system.dydt(t, yp, new Float64Array(n));
		for (let i = 0; i < n; i++) {
			const fd = (f1[i] - f0[i]) / h;
			worst = Math.max(worst, Math.abs(fd - dense[i][j]) / Math.max(1e-12, Math.abs(fd)));
			biggest = Math.max(biggest, Math.abs(fd));
		}
	}
	const held = system.layout.farfields[0].base;
	const near = system.layout.states.find((s) => s.name === 'Near').base;
	assert(dense[held][near] !== 0 && dense[held][near] !== 1e-2, `the release does not read the inflow: ${dense[held][near]}`);
	below(worst, 1e-5, 'analytic against differenced, every entry');
	void biggest;
	// ...and it is never a matrix to factorise once, even with the release
	// read by nothing: what the path holds loses it with a weight that
	// changes from step to step.
	assert(J.constant === false, 'df/dy of a semi-analytical path is taken for constant');
	const alone = structuredClone(raw);
	alone.transfers = alone.transfers.filter((t) => t.name !== 'Out');
	const { buildSystem } = await import('../src/sim/builder.js');
	assert(buildSystem(new Project(alone)).jacobian.constant === false,
		'df/dy of a path whose release nothing reads is taken for constant');
});

test('a run saved with its data and read back reports the same release', async () => {
	const { datasetEntries, readDataset, restoreResults } = await import('../src/io/dataset.js');
	const { Results } = await import('../src/sim/runner.js');
	const { buildSystem } = await import('../src/sim/builder.js');
	const times = logGrid(100, 3e4, 15);
	const raw = chainThroughPath({
		names: ['Aa-1', 'Bb-2'], half: { 'Aa-1': 2000, 'Bb-2': 800 }, chains: [['Aa-1', 'Bb-2', 1]],
		kdf: [2e-4, 5e-4], kdm: [1e-3, 3e-3], dem: [1e-4, 2e-4],
		path: { tw: 50, f: 5e4, eps_m: 0.005, pe: 10, pen_dep: 0.1 }, times,
	});
	const project = new Project(structuredClone(raw));
	const res = run(project);
	const parts = datasetEntries({ project, results: res, inner: 'model.json' });
	const entries = new Map(parts.map((e) => [e.name, e.bytes]));
	const data = readDataset(entries);
	const again = new Project(structuredClone(raw));
	const back = restoreResults({ project: again, system: buildSystem(again), data, Results });
	for (const o of res.outputs().filter((x) => x.block === 'Rock')) {
		const a = res.series(o);
		const b = back.series(back.outputs().find((x) => x.block === 'Rock' && x.nuclide === o.nuclide));
		below(worstRel(times, Array.from(b), Array.from(a), 1e-8), 1e-9, `the release of ${o.nuclide}`);
	}
});

test('a semi-analytical path is refused what it cannot do, before a run, by name', async () => {
	const { buildSystem, BuildError } = await import('../src/sim/builder.js');
	const { whyNotSplit } = await import('../src/sim/partition.js');
	const { uncarried } = await import('../src/sim/localsens.js');
	const { integrationFingerprint } = await import('../src/domain/fingerprint.js');
	const times = logGrid(100, 1e4, 5);
	const base = () => chainThroughPath({
		names: ['Aa-1', 'Bb-2'], half: { 'Aa-1': 2000, 'Bb-2': 800 }, chains: [['Aa-1', 'Bb-2', 1]],
		kdf: [2e-4, 5e-4], kdm: [1e-3, 3e-3], dem: [1e-4, 2e-4],
		path: { tw: 50, f: 5e4, eps_m: 0.005, pe: 10, pen_dep: 0.1 }, times,
	});
	const refused = (raw, re, what) => {
		let msg = '';
		let who = null;
		try { buildSystem(new Project(raw)); } catch (e) { msg = e.message; who = e.blockName; assert(e instanceof BuildError, `${what}: ${e.name}: ${e.message}`); }
		assert(re.test(msg), `${what}: ${msg || 'built'}`);
		assert(who === 'Rock', `${what}: the refusal names ${who}`);
	};
	const clock = base();
	clock.farfields[0].tw = '50 + time() / 1000';
	refused(clock, /Tw follows the clock/, 'a travel time that follows the clock');
	const state = base();
	state.farfields[0].f = '5e4 * (1 + Down[Aa-1])';
	refused(state, /F follows the state of the model/, 'a resistance that follows a compartment');
	const half = base();
	half.farfields[0].entries[1].de_m = '0';
	refused(half, /does not diffuse into the matrix/, 'a daughter that does not diffuse');
	const loop = base();
	loop.transfers[0] = { name: 'Leach', from: null, to: 'Rock', rate: 'Rock * 0.5', multiply_by_donor: false, index_lists: ['Radionuclides'] };
	refused(loop, /reads its own release at the same instant/, 'an inflow that reads the release');
	// ...and the runs that cannot carry its history say so rather than guess
	const system = buildSystem(new Project(base()));
	assert(/semi-analytically/.test(whyNotSplit(system) ?? ''), 'a split run is not refused');
	assert(/semi-analytically/.test(uncarried(new Project(base()), system, []) ?? ''), 'a local sensitivity run is not refused');
	assert(integrationFingerprint(base()) === null, 'a run of it would be reused across an edit');
});

test('the panel, the (i) topic and the Guide offer the choice and say what it cannot do', () => {
	const read = (rel) => readFileSync(`${HERE}${rel}`, 'utf8');
	const insp = read('../src/ui/inspector.js');
	// The choice is offered in words, beside the states it changes; worked
	// out exactly there is no discretisation to show, only the depth into the
	// matrix, and the outlet is said rather than offered.
	assert(/selectField\(FARF_TERM\.method, exact \? 'semi-analytical' : 'discretized',\s*FARF_METHODS\.map\(\(m\) => \[m, METHOD_LABEL\[m\]\]\)/.test(insp),
		'the panel does not offer the method');
	assert(/const grid = exact \? null : railSection\('farf-grid', 'Discretisation',/.test(insp),
		'the discretisation is shown for a path that has none');
	assert(/equationField\(FARF_TERM\.pen_dep,/.test(insp), 'the depth into the matrix is not offered when worked out exactly');
	// The (i) topic says what each way is.
	const info = read('../src/ui/blockinfo.js');
	assert(/\*\*Worked out\*\* — \*on cells\*/.test(info) && /\*Semi-analytically\*/.test(info),
		'the far-field topic does not describe the method');
	// The Guide has the section, with the limits, and says nothing about
	// another code there.
	const guide = read('../GUIDE.md');
	const at = guide.indexOf('### Worked out semi-analytically');
	assert(at > 0, 'the Guide has no section on the semi-analytical path');
	const section = guide.slice(at, guide.indexOf('\n## ', at));
	for (const limit of ['Settings that change during the run', 'Anything but the rock going on',
		'No cells, so no cell report', 'At most 16 nuclides linked by decay', 'Split runs and dy/dp']) {
		assert(section.includes(limit), `the Guide does not say: ${limit}`);
	}
	assert(!/Ecolego/i.test(section), 'the section compares with Ecolego');
});

test('the discretised block approaches it end to end, near field to downstream', () => {
	const times = logGrid(200, 3e4, 12);
	const spec = {
		names: ['Aa-1', 'Bb-2', 'Cc-3'], half: { 'Aa-1': 2000, 'Bb-2': 800, 'Cc-3': 5000 },
		chains: [['Aa-1', 'Bb-2', 0.6], ['Aa-1', 'Cc-3', 0.4]],
		kdf: [2e-4, 5e-4, 1e-4], kdm: [1e-3, 3e-3, 5e-4], dem: [1e-4, 2e-4, 1e-4], times,
	};
	const path = { tw: 50, f: 5e4, eps_m: 0.005, pe: 10, pen_dep: 0.1 };
	const semi = run(chainThroughPath({ ...spec, path }));
	const worst = (nf) => {
		const disc = run(chainThroughPath({ ...spec, method: 'discretized', path: { ...path, n_f: nf, n_m: 20 } }));
		let w = 0;
		for (const x of spec.names) {
			const a = semi.series(semi.outputs().find((o) => o.block === 'Rock' && o.nuclide === x));
			const b = disc.series(disc.outputs().find((o) => o.block === 'Rock' && o.nuclide === x));
			w = Math.max(w, worstRel(times, Array.from(b), Array.from(a), 0.1));
		}
		return w;
	};
	const coarse = worst(20);
	const fine = worst(40);
	assert(fine < coarse / 2.5, `the difference fell from ${coarse.toExponential(2)} to only ${fine.toExponential(2)}`);
	below(fine, 0.03, 'forty fracture cells, above a tenth of the peak');
});

slow('the discretised block converges to it end to end: Richardson over three refinements', () => {
	const times = logGrid(200, 3e4, 12);
	const spec = {
		names: ['Aa-1', 'Bb-2', 'Cc-3'], half: { 'Aa-1': 2000, 'Bb-2': 800, 'Cc-3': 5000 },
		chains: [['Aa-1', 'Bb-2', 0.6], ['Aa-1', 'Cc-3', 0.4]],
		kdf: [2e-4, 5e-4, 1e-4], kdm: [1e-3, 3e-3, 5e-4], dem: [1e-4, 2e-4, 1e-4], times,
	};
	const path = { tw: 50, f: 5e4, eps_m: 0.005, pe: 10, pen_dep: 0.1 };
	const semi = run(chainThroughPath({ ...spec, path }));
	const series = (res) => spec.names.map((x) => Array.from(res.series(res.outputs().find((o) => o.block === 'Rock' && o.nuclide === x))));
	const S = series(semi);
	const D = [40, 80, 160].map((nf) => series(run(chainThroughPath({ ...spec, method: 'discretized', path: { ...path, n_f: nf, n_m: 20 } }))));
	let worstFine = 0;
	let worstExtrapolated = 0;
	spec.names.forEach((x, i) => {
		// The cells' error falls with the square of the cell length: two
		// halvings give the limit by Richardson extrapolation.
		const lim = D[2][i].map((v, q) => v + (v - D[1][i][q]) / 3);
		worstFine = Math.max(worstFine, worstRel(times, D[2][i], S[i], 0.1));
		worstExtrapolated = Math.max(worstExtrapolated, worstRel(times, lim, S[i], 0.1));
	});
	below(worstFine, 0.01, '160 fracture cells');
	below(worstExtrapolated, 2e-3, 'the cells extrapolated to none');
});

slow('long runs: 1e4 and 1e5 steps of the far-field example', () => {
	for (const maxStep of [100, 10]) {
		const model = JSON.parse(readFileSync(EXAMPLE, 'utf8'));
		model.farfields[0].method = 'semi-analytical';
		model.simulation.max_step = maxStep;
		const t0 = Date.now();
		const res = run(model);
		const ms = Date.now() - t0;
		console.log(`         ${res.stats.nsteps} steps in ${ms} ms`);
		assert(res.stats.nsteps >= 1e6 / maxStep, `${res.stats.nsteps} steps`);
	}
});

// ---------------------------------------------------------------------------
// On its own
// ---------------------------------------------------------------------------

if (import.meta.url === pathToFileURL(process.argv[1] ?? '').href) {
	// `node test/farfield-laplace.js [words]`: every test, or those whose name has the words
	const only = process.argv[2] ?? '';
	const chosen = [...TESTS, ...SLOW].filter(([name]) => name.includes(only));
	let failed = 0;
	const t0 = Date.now();
	for (const [name, fn] of chosen) {
		const t1 = Date.now();
		try {
			await fn();
			console.log(`  ok   ${name} (${Date.now() - t1} ms)`);
		} catch (e) {
			failed++;
			console.log(`  FAIL ${name}\n         ${e.message.split('\n')[0]}`);
		}
	}
	console.log(`\n${chosen.length - failed} passed, ${failed} failed, ${((Date.now() - t0) / 1000).toFixed(1)} s`);
	process.exit(failed ? 1 : 0);
}
