// The application's distributions and sampling, for the Python package's tests
// to compare with (tests/test_stats_sampling.py).
//
//   node stats_sampling.mjs <kompartment src directory> < request.json
//
// A request is { calls: [[module, name, ...args], ...] } and the answer is
// { results: [...] }, one per call: { value } or { error, type }. `module` is
// pdf, sample, correlate, fit or distribution, and `name` one of its exports:
// a function is called with the arguments, anything else is returned as it is.
// A few names are not exports but the steps a test wants run together:
//
//   sample rngSeq      seed, count              -> rng(seed) called count times
//   sample streamSeq   seed, name, count        -> streamFor(seed, name) called count times
//   sample uniformsOf  seed, name, n, latin     -> uniforms(n, streamFor(seed, name), { latin });
//                                                  name null for rng(seed)
//   sample draws       seed, plan, n, latin     -> per { name, spec }: the uniforms from the
//                                                  name's stream, and the values drawn at them
//   sample slots       layout                   -> distributedSlots, with the effective value
//                                                  and index tuple worked out as below
//   sample design      project, plan, seed, n, latin, varied
//                                               -> the draws designFor makes in ../sim/probabilistic.js:
//                                                  group streams, correlations, held inputs
//   correlate run      columns, pairs, names, seed -> imanConover, and the columns it left
//   math    <fn>       xs                       -> Math[fn] of each
//
// JSON has no NaN, infinities, -0 or undefined, and they matter here, so both
// directions spell them { "$": "NaN" | "Infinity" | "-Infinity" | "-0" |
// "undefined" }. An argument { "$f64": [...] } is a Float64Array ($f32, $u8
// likewise); a typed array in an answer comes back as a plain array.

import { readFileSync } from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const src = process.argv[2];
const load = (file) => import(pathToFileURL(path.join(src, file)).href);
const modules = {
	pdf: await load('domain/pdf.js'),
	sample: await load('domain/sample.js'),
	correlate: await load('domain/correlate.js'),
	fit: await load('domain/fit.js'),
	distribution: await load('domain/distribution.js'),
};
const { slotName, groupOf } = await load('sim/probabilistic.js');

const SPECIAL = { NaN: NaN, Infinity: Infinity, '-Infinity': -Infinity, '-0': -0, undefined };

function decode(x) {
	if (Array.isArray(x)) return x.map(decode);
	if (x && typeof x === 'object') {
		const keys = Object.keys(x);
		if (keys.length === 1 && keys[0] === '$') return SPECIAL[x.$];
		if (keys.length === 1 && keys[0] === '$f64') return Float64Array.from(x.$f64.map(decode));
		if (keys.length === 1 && keys[0] === '$f32') return Float32Array.from(x.$f32.map(decode));
		if (keys.length === 1 && keys[0] === '$u8') return Uint8Array.from(x.$u8.map(decode));
		const out = {};
		for (const k of keys) out[k] = decode(x[k]);
		return out;
	}
	return x;
}

function encode(x) {
	if (x === undefined) return { $: 'undefined' };
	if (typeof x === 'number') {
		if (Number.isNaN(x)) return { $: 'NaN' };
		if (x === Infinity) return { $: 'Infinity' };
		if (x === -Infinity) return { $: '-Infinity' };
		if (x === 0 && 1 / x < 0) return { $: '-0' };
		return x;
	}
	if (ArrayBuffer.isView(x)) return Array.from(x, encode);
	if (Array.isArray(x)) return x.map(encode);
	if (typeof x === 'function') return { $: 'function' };
	if (x && typeof x === 'object') {
		const out = {};
		for (const k of Object.keys(x)) out[k] = encode(x[k]);
		return out;
	}
	return x;
}

// The index tuple of an offset into a block's dimensions, the last fastest,
// and a parameter's distribution at a tuple: the entry whose index matches,
// else the block's own. The Python test works both out the same way.
const tupleAt = (space, dims, off) => {
	const out = {};
	let rest = off;
	for (let d = dims.length - 1; d >= 0; d--) {
		const list = space[dims[d]];
		out[dims[d]] = list[rest % list.length];
		rest = Math.floor(rest / list.length);
	}
	const ordered = {};
	for (const d of dims) ordered[d] = out[d];
	return ordered;
};
const effective = (block, key, tuple) => {
	const hit = (block.entries ?? []).find((e) => Object.keys(tuple).length
		&& Object.entries(tuple).every(([k, v]) => e.index?.[k] === v));
	return hit && hit[key] !== undefined ? hit[key] : block[key];
};

const special = {
	sample: {
		rngSeq(seed, count) {
			const next = modules.sample.rng(seed);
			return Array.from({ length: count }, () => next());
		},
		streamSeq(seed, name, count) {
			const next = modules.sample.streamFor(seed, name);
			return Array.from({ length: count }, () => next());
		},
		uniformsOf(seed, name, n, latin) {
			const next = name == null ? modules.sample.rng(seed) : modules.sample.streamFor(seed, name);
			return modules.sample.uniforms(n, next, { latin });
		},
		draws(seed, plan, n, latin) {
			return plan.map(({ name, spec }) => {
				const u = modules.sample.uniforms(n, modules.sample.streamFor(seed, name), { latin });
				return { u, values: Array.from(u, (x, i) => modules.sample.valueAtProbability(spec, x, i)) };
			});
		},
		slots(layout) {
			return modules.sample.distributedSlots(layout, effective, tupleAt);
		},
		// designFor's sampling, from its uniforms to the values: see ../sim/probabilistic.js.
		design(project, plan, seed, n, latin, varied) {
			const { streamFor, uniforms, valueAtProbability } = modules.sample;
			const { correlationPairs, imanConover } = modules.correlate;
			const names = plan.map(slotName);
			const held = varied == null ? null : new Set(varied);
			const varies = (e) => !held || held.has(slotName(e));
			const draws = plan.map((e) => uniforms(n, streamFor(seed, groupOf(e) ?? slotName(e)), { latin }));
			const { pairs, problems } = correlationPairs(project, names);
			const grouped = new Set(plan.map((e, k) => (groupOf(e) ? k : -1)).filter((k) => k >= 0));
			const usable = pairs.filter((pr) => varies(plan[pr.a]) && varies(plan[pr.b])
				&& !grouped.has(pr.a) && !grouped.has(pr.b));
			const corr = imanConover(draws, usable, names, seed);
			const values = plan.map((e, k) => Array.from(draws[k], (u, i) => valueAtProbability(e.spec, u, i)));
			return { names, draws, values, pairs, problems, corr };
		},
	},
	correlate: {
		run(columns, pairs, names, seed) {
			const cols = columns.map((c) => Float64Array.from(c));
			const result = modules.correlate.imanConover(cols, pairs, names, seed);
			return { result, columns: cols };
		},
	},
};

const req = decode(JSON.parse(readFileSync(0, 'utf8')));
const results = req.calls.map(([mod, name, ...args]) => {
	try {
		if (mod === 'math') return { value: args[0].map((x) => Math[name](x)) };
		const fn = special[mod]?.[name] ?? modules[mod][name];
		if (fn === undefined) throw new Error(`${mod} has no ${name}`);
		return { value: typeof fn === 'function' ? fn(...args) : fn };
	} catch (e) {
		return { error: String(e?.message ?? e), type: e?.constructor?.name ?? 'Error' };
	}
});
process.stdout.write(JSON.stringify(encode({ results })));
