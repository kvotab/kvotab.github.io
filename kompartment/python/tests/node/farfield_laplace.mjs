// The application's semi-analytical far-field path, for the Python engine's
// tests to compare with.
//
//   node farfield_laplace.mjs <kompartment src directory> < request.json
//
// A request is { cases: [case, ...] }, each case
//
//   { settings, decay, names,
//     s:         [[sr, si, i, j], ...]   -> transfer, inventoryTransfer: [re, im] each
//     at:        [[i, j, t, kind], ...]  -> at: {h, dh, d2} each, inverted directly
//     responses: {kinds, tMax} | null    -> responses: {'<kind>:<i>,<j>': {t, h, dh, d2h, integral, T0}}
//     inflows:   [[[t, rate], ...] | null, ...], times: [...]
//                                        -> release, inventory: one row per time }
//
// and the answer { cases: [...] } with T0 for every case. Infinity and NaN
// travel as the strings 'Infinity', '-Infinity' and 'NaN'.

import { readFileSync } from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const src = process.argv[2];
const L = await import(pathToFileURL(path.join(src, 'domain/farfield-laplace.js')).href);

const req = JSON.parse(readFileSync(0, 'utf8'), (k, v) => (
	v === 'Infinity' ? Infinity : v === '-Infinity' ? -Infinity : v === 'NaN' ? NaN : v));

const plain = (x) => JSON.parse(JSON.stringify(x, (k, v) => {
	if (typeof v === 'number' && !Number.isFinite(v)) return String(v);
	if (ArrayBuffer.isView(v)) return Array.from(v, (n) => (Number.isFinite(n) ? n : String(n)));
	return v;
}));

const out = [];
for (const c of req.cases) {
	const p = L.preparePath(c.settings, c.decay ?? null, { names: c.names ?? undefined });
	const answer = { T0: L.transferAtZero(p) };
	if (c.s) {
		answer.transfer = c.s.map(([sr, si, i, j]) => L.transfer(p, sr, si, i, j));
		answer.inventoryTransfer = c.s.map(([sr, si, i, j]) => L.inventoryTransfer(p, sr, si, i, j));
	}
	if (c.at) {
		answer.at = c.at.map(([i, j, t, kind]) => {
			const r = L.responseAt(p, i, j, t, { kind });
			return { h: r.h, dh: r.dh, d2: r.d2 };
		});
	}
	if (c.responses) {
		const R = L.unitResponses(p, c.responses);
		answer.responses = {};
		for (const kind of L.KINDS) {
			for (const r of R[kind]) {
				if (!r) continue;
				answer.responses[`${kind}:${r.i},${r.j}`] = {
					t: r.t, h: r.h, dh: r.dh, d2h: r.d2h, integral: r.integral, T0: r.T0,
					m0: r.m0 ?? 0, expected: r.expected ?? null, balanced: r.balanced ?? null,
				};
			}
		}
		if (c.inflows) {
			const inflows = c.inflows.map((pts) => (pts ? L.inflowSeries(pts) : null));
			answer.release = c.times.map((t) => L.releaseAt(p, R, inflows, t));
			answer.inventory = c.times.map((t) => L.inventoryAt(p, R, inflows, t));
		}
	}
	out.push(answer);
}
process.stdout.write(JSON.stringify(plain({ cases: out })));
