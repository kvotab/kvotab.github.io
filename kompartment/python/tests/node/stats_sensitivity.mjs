// The application's sensitivity analysis, for the Python package's tests to compare with.
//
//   node stats_sensitivity.mjs <kompartment src directory> < request.json
//
// A request is { calls: [call, ...] } and the answer { results: [...] }, one
// per call: { value } or { error, name }. A call is
//
//   { module, fn, args, returnArgs? }   module is fft, sensitivity, categories,
//                                       gsa or salib; fn one of its exports
//                                       (a constant when args is absent);
//                                       returnArgs lists arguments to send
//                                       back as they are after the call, for
//                                       the functions that work in place
//   { special: 'buildDesign', method, keys, options, seed, corr }
//   { special: 'gsaTable', method, keys, options, seed, corr, y, next, intervals }
//   { special: 'gsaMain', method, keys, options, seed, corr, y }
//   { special: 'stream', seed, name, count }       the first draws of streamFor
//   { special: 'uniforms', seed, name, n, latin }  uniforms(n, streamFor(seed, name))
//   { special: 'methods', K }                      GSA_METHODS, defaults worked out for K
//
// Numbers that JSON cannot carry travel as tagged objects, both ways:
// { $f64: base64 of Float64 bytes } for a Float64Array, { $i32 | $u8 | $u16 |
// $i8: [...] } for the integer arrays, { $num: 'NaN' | 'Infinity' |
// '-Infinity' | '-0' } for a number, { $undefined: true }. An argument can also
// be a function: { $stream: [seed, name] } is streamFor(seed, name), { $lcg:
// seed } the test suite's little congruential generator, { $fnList: [a, b, ...] }
// the function k => list[k], and { $drawAB: { A, B, n } } a Sobol draw
// (k, which, block) => the block's slice of A[k] or B[k].

import { readFileSync } from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const src = process.argv[2];
const load = (file) => import(pathToFileURL(path.join(src, file)).href);
const modules = {
	fft: await load('domain/fft.js'),
	sensitivity: await load('domain/sensitivity.js'),
	categories: await load('domain/categories.js'),
	gsa: await load('domain/gsa.js'),
	salib: await load('domain/salib.js'),
};
const { streamFor, uniforms } = await load('domain/sample.js');

const f64 = (s) => {
	const b = Buffer.from(s, 'base64');
	return new Float64Array(b.buffer.slice(b.byteOffset, b.byteOffset + b.length));
};
const b64 = (a) => Buffer.from(a.buffer, a.byteOffset, a.byteLength).toString('base64');
const NUMS = { NaN, Infinity, '-Infinity': -Infinity, '-0': -0 };

function dec(v) {
	if (v === null || typeof v !== 'object') return v;
	if (Array.isArray(v)) return v.map(dec);
	if ('$f64' in v) return f64(v.$f64);
	if ('$i32' in v) return Int32Array.from(v.$i32);
	if ('$u8' in v) return Uint8Array.from(v.$u8);
	if ('$u16' in v) return Uint16Array.from(v.$u16);
	if ('$i8' in v) return Int8Array.from(v.$i8);
	if ('$num' in v) return NUMS[v.$num];
	if ('$undefined' in v) return undefined;
	if ('$stream' in v) return streamFor(v.$stream[0], v.$stream[1]);
	if ('$lcg' in v) {
		let n = v.$lcg;
		return () => { n = (n * 9301 + 49297) % 233280; return n / 233280; };
	}
	if ('$fnList' in v) {
		const items = v.$fnList.map(dec);
		return (k) => items[k];
	}
	if ('$drawAB' in v) {
		const A = v.$drawAB.A.map(dec);
		const B = v.$drawAB.B.map(dec);
		const n = v.$drawAB.n;
		return (k, which, b) => (which === 'A' ? A[k] : B[k]).slice(b * n, (b + 1) * n);
	}
	const out = {};
	for (const [k, x] of Object.entries(v)) out[k] = dec(x);
	return out;
}

function enc(v) {
	if (v === undefined) return { $undefined: true };
	if (v === null) return null;
	if (typeof v === 'number') {
		if (Number.isNaN(v)) return { $num: 'NaN' };
		if (v === Infinity) return { $num: 'Infinity' };
		if (v === -Infinity) return { $num: '-Infinity' };
		if (Object.is(v, -0)) return { $num: '-0' };
		return v;
	}
	if (typeof v === 'boolean' || typeof v === 'string') return v;
	if (typeof v === 'function') return { $function: v.length };
	if (v instanceof Float64Array) return { $f64: b64(v) };
	if (v instanceof Int32Array) return { $i32: Array.from(v) };
	if (v instanceof Uint8Array) return { $u8: Array.from(v) };
	if (v instanceof Uint16Array) return { $u16: Array.from(v) };
	if (v instanceof Int8Array) return { $i8: Array.from(v) };
	if (Array.isArray(v)) return v.map(enc);
	if (typeof v === 'object') {
		const out = {};
		for (const [k, x] of Object.entries(v)) out[k] = enc(x);
		return out;
	}
	return String(v);
}

const g = modules.gsa;
const design = (c) => g.buildDesign(c.method, c.keys, dec(c.options ?? {}),
	{ seed: c.seed ?? 1, corr: c.corr ? dec(c.corr) : null, streamFor, uniforms });

function answer(c) {
	switch (c.special) {
		case 'buildDesign': return design(c);
		case 'gsaTable': {
			const d = design(c);
			const o = { intervals: c.intervals ?? true };
			if (c.next) o.next = streamFor(c.next[0], c.next[1]);
			return g.gsaTable(d, dec(c.y), o);
		}
		case 'gsaMain': return g.gsaMain(design(c), dec(c.y));
		case 'stream': {
			const next = streamFor(c.seed, c.name);
			return Float64Array.from({ length: c.count }, () => next());
		}
		case 'uniforms': return uniforms(c.n, streamFor(c.seed, c.name), { latin: c.latin ?? true });
		case 'methods': {
			const out = {};
			for (const [id, m] of Object.entries(g.GSA_METHODS)) {
				out[id] = {
					...m,
					options: m.options.map(([key, label, def, kind, title, choices]) => [
						key, label, typeof def === 'function' ? def(c.K) : def, kind, title,
						...(choices ? [choices] : []),
					]),
				};
			}
			return out;
		}
		default: break;
	}
	const mod = modules[c.module];
	if (!mod) throw new Error(`No module ${c.module}`);
	if (!(c.fn in mod)) throw new Error(`${c.module} has no export ${c.fn}`);
	if (!('args' in c)) return mod[c.fn];
	const args = dec(c.args);
	const value = mod[c.fn](...args);
	if (c.returnArgs) return { value, args: c.returnArgs.map((i) => args[i]) };
	return value;
}

const req = JSON.parse(readFileSync(0, 'utf8'));
const results = req.calls.map((c) => {
	try {
		return { value: enc(answer(c)) };
	} catch (e) {
		return { error: e.message, name: e.name };
	}
});
process.stdout.write(JSON.stringify({ results }));
