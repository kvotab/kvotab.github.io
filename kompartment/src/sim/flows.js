/**
 * Where the inventory goes: what each transfer carried, and the account of
 * every compartment, for one nuclide over a run.
 *
 * The mass-balance audit (../domain/massbalance.js) says whether a family's
 * books close -- what came in, went out, decayed and grew in, against what is
 * held. It does not say *by which route*: a reviewer asking where the Cs-135
 * went after ten thousand years wants to see that most of it decayed in the
 * near field, a third reached the rock, and a sliver the well. That is this:
 * for one nuclide (one *family*, in the audit's word), each compartment's
 * inventory over the run, and each route an amount took, added up from the
 * start to every output time.
 *
 * **Worked out from the run, by the derivative's own arithmetic.** A transfer
 * carries its value -- its rate times its availability, the very slot the
 * solver read -- times its donor's inventory, or its value alone where it is
 * an absolute flux; a source delivers its value; a compartment loses its
 * decay constant times what it holds and gains its parents' share of theirs,
 * from the same decay tables. Each is worked out at every output time from
 * the stored states, as every series of a run is, with each index carried to
 * its donor and its target through the same projection the builder writes
 * into the derivative. Nothing is solved again and nothing about the run is
 * changed.
 *
 * **Added up between the output times by the trapezium rule**, as a derived
 * integral is, so a route's total is as good as the output grid is fine. What
 * no route here accounts for -- an explicit dy/dt term, a far-field path's
 * return, a waste package's release, an event's jump, and the summing between
 * the points -- is each compartment's change of inventory less every route,
 * and is shown as such rather than spread over the routes.
 */

import { UNINDEXED } from '../domain/massbalance.js';
import { decayTables } from './builder.js';

/** Where a route ends that is not a compartment of the account. */
export const OUTSIDE = '(outside)';

/**
 * Which of a layout's dimensions are along the nuclides: the material list and
 * any sub-set of it -- not a mapping onto it, which decays along nothing. The
 * builder's own rule (`isNuclideDim`).
 */
function nuclideDims(project, space) {
	const list = project.materialListName;
	if (!list) return () => false;
	const root = space.get(list)?.rootName;
	return (d) => {
		const L = space.get(d);
		return !!L && !L.mapping && L.rootName === root;
	};
}

/** The position along each of `dims` of the tuple at `off`. */
function positions(space, dims, off) {
	const strides = space.strides(dims);
	const out = new Int32Array(dims.length);
	let rest = off;
	for (let i = 0; i < dims.length; i++) {
		out[i] = Math.floor(rest / strides[i]);
		rest -= out[i] * strides[i];
	}
	return out;
}

/**
 * Where an index of a block of `sourceDims` reads a state: the builder's
 * `stateOffsetExpr`, evaluated rather than written as code. Null where the
 * projection cannot be made.
 */
function locator(space, sourceDims, entry, owner) {
	if (!entry) return null;
	if (!entry.dims.length) return () => entry.base;
	let terms;
	try {
		terms = space.projection(sourceDims, entry.dims, {}, { owner, target: entry.name });
	} catch {
		return null;
	}
	return (pos) => {
		let off = entry.base;
		for (const term of terms) {
			if (term.fixed != null) { off += term.fixed * term.stride; continue; }
			const v = pos[term.from];
			const p = term.table ? term.table[v] : v;
			if (!(p >= 0)) return null;
			off += p * term.stride;
		}
		return off;
	};
}

/**
 * The account of one family over a run.
 *
 * @param {object} results  a run: `{project, system, t, y}`, y a row per time
 * @param {object} [opts]
 * @param {string|null} [opts.family]  the nuclide; the one with the most
 *   inventory at the start when not given, or the run's only family
 * @returns {object} `{family, families, t, places, links, held}`: `places` a
 *   compartment state each, `{key, label, block, series}`; `links` a route
 *   each, `{kind, name, from, to, cum}`, where `kind` is 'transfer', 'in',
 *   'out', 'decay', 'ingrowth' or 'other', `from` and `to` a place's key or
 *   `OUTSIDE`, and `cum` the amount carried from the start to each output time
 */
export function flowAccount(results, { family = null } = {}) {
	const { project, system } = results;
	const layout = system.layout;
	const space = layout.indexSpace;
	const t = results.t;
	const y = results.y;
	const T = t.length;
	const isNuclide = nuclideDims(project, space);

	// --- the places: every compartment's state, with its family ----------------
	const stateByName = new Map(layout.states.map((s) => [s.name, s]));
	const familyOf = new Map(); // state offset -> family name
	const placeOf = new Map(); // state offset -> place
	const placesByFamily = new Map();
	// A waste package's two inventories are places too, as the audit counts
	// them: what fails moves from the intact to the exposed, and the release
	// leaves the exposed.
	const held = (s) => s.kind === 'compartment' || s.kind === 'waste_package';
	for (const s of layout.states) {
		if (!held(s)) continue;
		const m = s.dims.findIndex(isNuclide);
		for (let off = 0; off < s.width; off++) {
			const tuple = s.dims.length ? space.tupleAt(s.dims, off) : [];
			const fam = m >= 0 ? tuple[m] : UNINDEXED;
			const others = tuple.filter((_, i) => i !== m);
			const key = `${s.name}${others.length ? ` [${others.join(', ')}]` : ''}`;
			const place = { key, label: key, block: s.name, state: s.base + off };
			familyOf.set(place.state, fam);
			placeOf.set(place.state, place);
			if (!placesByFamily.has(fam)) placesByFamily.set(fam, []);
			placesByFamily.get(fam).push(place);
		}
	}
	const families = [...placesByFamily.entries()].map(([name, places]) => ({
		name, start: places.reduce((sum, p) => sum + (Number(y[0]?.[p.state]) || 0), 0),
	}));
	if (!families.length) {
		return { family: null, families: [], t: Array.from(t), places: [], links: [], held: 0 };
	}
	const chosen = family != null && placesByFamily.has(family) ? family
		: families.reduce((a, b) => (b.start > a.start ? b : a)).name;
	const places = placesByFamily.get(chosen);
	const inFamily = (off) => off != null && familyOf.get(off) === chosen;

	// --- the routes ----------------------------------------------------------
	// Each `{kind, name, from, to, rate(k, X, y)}`; the rate is worked out at
	// every output time below and added up.
	const routes = [];
	const algByName = new Map(layout.algebraic.map((a) => [a.name, a]));
	const wasteByName = new Map((layout.wastes ?? []).map((W) => [W.name, W]));
	const exposedOf = (W) => layout.states.find((s) => s.kind === 'waste_package' && s.base === W.exposed);
	const carried = new Set();
	for (const tr of project.transfers ?? []) {
		const alg = algByName.get(tr.qname ?? tr.name);
		if (!alg) continue;
		// Out of a waste package, the release leaves its exposed inventory.
		const W = tr.from ? wasteByName.get(tr.from) : null;
		if (W && tr.to && stateByName.has(tr.to)) carried.add(W.name);
		const src = W ? exposedOf(W) : tr.from ? stateByName.get(tr.from) : null;
		const tgt = tr.to ? stateByName.get(tr.to) : null;
		const findSrc = locator(space, alg.dims, src, tr.name);
		const findTgt = locator(space, alg.dims, tgt, tr.name);
		const byDonor = !!tr.multiply_by_donor && !!src;
		for (let off = 0; off < alg.width; off++) {
			const pos = positions(space, alg.dims, off);
			const d = findSrc ? findSrc(pos) : null;
			const r = findTgt ? findTgt(pos) : null;
			// A donor that is a compartment of this family, or a target that is.
			const fromHere = inFamily(d) && placeOf.has(d);
			const toHere = inFamily(r) && placeOf.has(r);
			if (!fromHere && !toHere) continue;
			const slot = alg.base + off;
			const from = fromHere ? placeOf.get(d).key : OUTSIDE;
			const to = toHere ? placeOf.get(r).key : OUTSIDE;
			const kind = fromHere && toHere ? 'transfer' : fromHere ? 'out' : 'in';
			routes.push({
				kind, name: tr.qname ?? tr.name, from, to,
				rate: byDonor
					? (X, row) => X[slot] * (d != null ? row[d] : 0)
					: (X) => X[slot],
			});
		}
	}
	// A waste package's own moves: what fails, from the intact packages to the
	// exposed inventory; and a release no transfer carries, out of the model.
	for (const W of layout.wastes ?? []) {
		const intact = layout.states.find((s) => s.kind === 'waste_package' && s.base === W.intact);
		if (!intact) continue;
		for (let off = 0; off < W.width; off++) {
			const p = W.intact + off;
			const e = W.exposed + off;
			if (!inFamily(p)) continue;
			if (W.hazard != null) {
				routes.push({
					kind: 'transfer', name: `${W.name} fail`, from: placeOf.get(p).key, to: placeOf.get(e).key,
					rate: (X, row) => X[W.hazard] * row[p],
				});
			}
			if (!carried.has(W.name)) {
				const slot = W.release + off;
				routes.push({
					kind: 'out', name: `${W.name} release`, from: placeOf.get(e).key, to: OUTSIDE,
					rate: (X) => X[slot],
				});
			}
		}
	}
	for (const s of project.inflows ?? []) {
		const alg = algByName.get(s.qname ?? s.name);
		const tgt = stateByName.get(s.to);
		if (!alg || !tgt) continue;
		const findTgt = locator(space, alg.dims, tgt, s.name);
		if (!findTgt) continue;
		for (let off = 0; off < alg.width; off++) {
			const r = findTgt(positions(space, alg.dims, off));
			if (!inFamily(r) || !placeOf.has(r)) continue;
			const slot = alg.base + off;
			routes.push({
				kind: 'in', name: s.qname ?? s.name, from: OUTSIDE, to: placeOf.get(r).key,
				rate: (X) => X[slot],
			});
		}
	}
	// Decay and ingrowth, from the same tables the derivative reads.
	const materialList = project.materialListName;
	const tables = new Map();
	const tableFor = (list) => {
		if (!tables.has(list)) {
			const model = list === materialList ? project.decayModel() : project.decayModelFor(list);
			tables.set(list, decayTables(model, space.size(list)));
		}
		return tables.get(list);
	};
	for (const s of layout.states) {
		if (!held(s) || s.block?.handle_decay === false || !materialList) continue;
		const m = s.dims.findIndex(isNuclide);
		if (m < 0) continue;
		const D = tableFor(s.dims[m]);
		const strideM = space.strides(s.dims)[m];
		for (let off = 0; off < s.width; off++) {
			const si = s.base + off;
			if (!inFamily(si)) continue;
			const nm = positions(space, s.dims, off)[m];
			const key = placeOf.get(si).key;
			const lam = D.lam[nm];
			if (lam > 0) {
				routes.push({ kind: 'decay', name: 'decay', from: key, to: OUTSIDE, rate: (X, row) => lam * row[si] });
			}
			const o = D.ioff[nm];
			const c = D.icnt[nm];
			if (c > 0) {
				const parents = [];
				for (let q = 0; q < c; q++) parents.push([D.icoef[o + q], si + (D.ipar[o + q] - nm) * strideM]);
				routes.push({
					kind: 'ingrowth', name: 'ingrowth', from: OUTSIDE, to: key,
					rate: (X, row) => {
						let g = 0;
						for (const [coef, at] of parents) g += coef * row[at];
						return g;
					},
				});
			}
		}
	}

	// --- worked out at every output time, and added up ----------------------
	const rates = routes.map(() => new Float64Array(T));
	const needsX = routes.some((r) => r.kind === 'transfer' || r.kind === 'in' || r.kind === 'out');
	for (let k = 0; k < T; k++) {
		const row = y[k];
		const X = needsX ? system.evaluateAlgebraic(t[k], row) : null;
		for (let j = 0; j < routes.length; j++) {
			const v = routes[j].rate(X, row);
			rates[j][k] = Number.isFinite(v) ? v : NaN;
		}
	}
	const cumulative = (r) => {
		const out = new Float64Array(T);
		let total = 0;
		for (let k = 1; k < T; k++) {
			const dt = t[k] - t[k - 1];
			const a = r[k - 1];
			const b = r[k];
			if (dt > 0 && Number.isFinite(a) && Number.isFinite(b)) total += 0.5 * (a + b) * dt;
			out[k] = total;
		}
		return out;
	};
	const links = routes.map((r, j) => ({ kind: r.kind, name: r.name, from: r.from, to: r.to, cum: cumulative(rates[j]) }));

	// What no route accounts for, compartment by compartment: its change of
	// inventory less what the routes brought and took.
	const series = new Map(places.map((p) => [p.key, Float64Array.from({ length: T }, (_, k) => y[k][p.state])]));
	for (const p of places) {
		const s = series.get(p.key);
		const other = new Float64Array(T);
		for (let k = 0; k < T; k++) other[k] = s[k] - s[0];
		for (const l of links) {
			if (l.to === p.key) for (let k = 0; k < T; k++) other[k] -= l.cum[k];
			if (l.from === p.key) for (let k = 0; k < T; k++) other[k] += l.cum[k];
		}
		let biggest = 0;
		for (let k = 0; k < T; k++) biggest = Math.max(biggest, Math.abs(other[k]));
		if (biggest > 0) links.push({ kind: 'other', name: 'other', from: OUTSIDE, to: p.key, cum: other });
	}
	// The inventory's unit: the model's decay unit for a nuclide, a compartment's
	// own for the family that is not one.
	const first = stateByName.get(places[0]?.block);
	const unit = chosen !== UNINDEXED ? (project.decayUnit ?? '') : (first?.block?.unit ?? '');
	return {
		family: chosen,
		families,
		unit,
		t: Array.from(t),
		places: places.map((p) => ({ key: p.key, label: p.label, block: p.block, series: series.get(p.key) })),
		links,
	};
}

/**
 * The account at one output time, as the views read it: what each place
 * holds, what each route has carried, and the totals.
 *
 * @param {object} account  from `flowAccount`
 * @param {number} k        the output time's index
 */
export function accountAt(account, k) {
	const at = (series) => series[Math.min(k, series.length - 1)];
	const held = account.places.map((p) => ({ key: p.key, label: p.label, start: p.series[0], now: at(p.series) }));
	const routes = account.links.map((l) => ({ ...l, amount: at(l.cum) }));
	const sum = (kind) => routes.filter((r) => r.kind === kind).reduce((s, r) => s + r.amount, 0);
	return {
		held,
		routes,
		totals: {
			start: held.reduce((s, p) => s + p.start, 0),
			now: held.reduce((s, p) => s + p.now, 0),
			in: sum('in'), out: sum('out'), decay: sum('decay'), ingrowth: sum('ingrowth'),
			moved: sum('transfer'), other: sum('other'),
		},
	};
}
