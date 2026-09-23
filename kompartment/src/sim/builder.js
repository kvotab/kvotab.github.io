/**
 * Builds a runnable ODE system from a Project.
 *
 * Lays out the state vector over every index combination, orders the
 * algebraic blocks, and generates a single derivative function which the JS
 * engine then compiles.
 *
 * The equations it assembles are, per compartment C at index tuple i:
 *
 *   dC[i]/dt = sum(inflows) - sum(outflows) + sources
 *              - lambda[m] * C[i]                       (decay)
 *              + sum over parents p ( lambda[p]*ratio * C[i with m := p] )
 *
 * where m is the position of i along the material index list, with flux taken
 * from the standard flux equation:
 *
 *   flux = multiply_by_donor ? donor * rate : rate
 *
 * and the decay/ingrowth terms from the standard decay term.
 *
 * Blocks of different dimension are related through IndexSpace.projection,
 * which is where sub-set and mapped index lists earn their keep.
 */

import { parse, collectReferences, ParseError } from '../parser/parser.js';
import { emit, buildFunction } from '../parser/compile.js';
import { FUNCTIONS } from '../parser/functions.js';
import { valueAt, hasDydt } from '../domain/project.js';
import { makeTable, LookupError } from '../domain/lookup.js';
import { materialUnit } from '../domain/units.js';
import { OPERATION_FUNCTION, operatedList } from '../domain/reduce.js';
import {
	schemeOf, expressionOf, operandKeys, isShared, basisOf, molesPerUnit,
} from '../domain/availability.js';
import { TIME_UNITS, SECONDS_PER_YEAR, lambda } from '../domain/nuclides.js';
import { TERMS as BUDGET_TERMS, UNINDEXED } from '../domain/massbalance.js';
import {
	WASTE_EQUATION_KEYS, WASTE_NUCLIDE_KEYS, FAILURE_KEYS, failureOf, hazardCode,
} from '../domain/wastepackage.js';
import { TIMING_KEYS, timingOf, normaliseActions } from '../domain/disruption.js';
import {
	REMEMBERING_KINDS, RECORDER_KINDS, EVENT_FIELDS, EVENT_ACTION,
	DIRECTION_SIGN, RECORDER_COLLECTION, EQUATION_FIELDS,
} from '../domain/recorders.js';
import { Recorder } from './history.js';
import {
	IndexError, COMPARTMENT_LIST, TRANSFER_LIST, SOURCE_INDEX, TARGET_INDEX,
} from '../domain/indexlists.js';
import { buildJacobian, buildParamTangent } from './jacobian.js';
import { userFunctions, FunctionError } from './functions.js';
import { FarfPath } from './farfield.js';
import { expandTransports, TransportError } from './transport.js';
import {
	FARF_EQUATION_KEYS, FARF_NUCLIDE_KEYS, cellCount, structureProblem,
	geometryProblem,
} from '../domain/farfield.js';
import { resolveReference, systemOf, allBlocks } from '../domain/systems.js';
import { parseUnit, scaleLiterals } from '../domain/unitcheck.js';

export class BuildError extends Error {
	constructor(message, blockName) {
		super(blockName ? `${blockName}: ${message}` : message);
		this.name = 'BuildError';
		this.blockName = blockName;
	}
}

/**
 * @param project a `Project`
 * @param {{jacobian?: boolean}} [opts] `jacobian: false` builds everything the
 *   model needs to be *evaluated* and skips the analytic df/dy. The editor's
 *   value-at-the-start preview never differentiates anything, and generating
 *   the derivative is a quarter to a half of the build on a large model --
 *   1,935 ms against 1,470 on one landscape model, 285 against 136 on
 *   a smaller one. A run leaves it on.
 */
export function buildSystem(project, { jacobian: wantJacobian = true } = {}) {
	// A transport sub-system is a chain of N compartments drawn as two. It is
	// unrolled here, before anything is laid out, into ordinary compartments
	// and transfers -- see ./transport.js -- so that nothing below has to know
	// a chain from a model. The elements in the middle are marked `hidden`,
	// and the layout carries the mark so the results can leave them out.
	if (project.transports?.size) {
		try {
			project = expandTransports(project);
		} catch (e) {
			if (e instanceof TransportError) throw new BuildError(e.message, e.blockName);
			throw e;
		}
	}
	const space = project.indexSpace;
	const materialList = project.materialListName;
	const decay = project.decayModel();

	/**
	 * A block's dimensions as the simulation sees them.
	 *
	 * Ecolego's scenario list is not an axis of the model: one of its indices
	 * is active and every block indexed by it is read at that one. So the
	 * dimension is dropped here, exactly as the scenario rule drops it
	 * when the desktop tools generate their class, and everything below -- widths,
	 * strides, projections, the state vector -- never sees it.
	 */
	const dimsOf = (block) => space.withoutScenarios(block.index_lists);

	/**
	 * Whether a dimension is a nuclide dimension -- one the decay chain runs
	 * along. A *mapped* list is not, however related: the element list shares
	 * its root with the nuclides and decays along nothing. Hoisted above the
	 * state layout because a far-field path's own layout depends on which of
	 * its dimensions the nuclides are.
	 */
	const materialRoot = materialList ? space.get(materialList).rootName : null;
	const isNuclideDim = (d) => !!materialList && !space.get(d).mapping
		&& space.get(d).rootName === materialRoot;

	/**
	 * The tuple to read a stored value at: where the block is being evaluated,
	 * with the active scenario put back in. `ScenarioIndexWrapper.wrap`.
	 */
	const entryTuple = (block, dims, off) => space.pinScenario(
		block.index_lists, tupleByList(space, dims, off),
	);

	// Index-to-index tables referenced by generated code, as MAPS[k].
	const maps = [];
	const mapKey = new Map();
	const mapIndex = (table) => {
		const key = table.join(',');
		if (!mapKey.has(key)) {
			mapKey.set(key, maps.length);
			maps.push(table);
		}
		return mapKey.get(key);
	};

	// --- layout ----------------------------------------------------------
	const stateLayout = [];
	let nstate = 0;
	for (const c of project.compartments) {
		const width = space.width(dimsOf(c));
		// Keyed by qualified name: two compartments called Water in different
		// sub-systems are two different compartments.
		stateLayout.push({
			name: c.qname ?? c.name, local: c.name, system: systemOf(c),
			base: nstate, width, dims: dimsOf(c), block: c,
			kind: 'compartment',
			// An element in the middle of a transport chain: run, not reported.
			...(c.hidden ? { hidden: true } : {}),
		});
		nstate += width;
	}
	// (checked below, once the algebraic blocks are known)
	// A model with no compartments is not an error: Ecolego has plenty of them
	// -- 15 of the 71 real projects tested here -- and they are the ones that
	// read a released inventory and work out a dose. There is nothing to
	// integrate, so the runner evaluates the algebraic blocks over the output
	// grid instead. Everything below handles an empty state vector already;
	// the loops simply do not run.
	// A running mean is integrated: `dS/dt = target`, and the block's value is
	// that integral divided by the time it covers. That makes it a state
	// block, so its states sit in the same vector, after the compartments.
	const meanStates = [];
	for (const m of project.running_means ?? []) {
		const width = space.width(dimsOf(m));
		const entry = {
			name: m.qname ?? m.name, local: m.name, system: systemOf(m),
			base: nstate, width, dims: dimsOf(m), block: m,
			kind: 'running_mean', hidden: true,
		};
		stateLayout.push(entry);
		meanStates.push(entry);
		nstate += width;
	}
	// --- far-field paths ---------------------------------------------------
	// A FARFCOMP block is a transport model of its own: N_F fracture cells,
	// each with N_M matrix layers behind it, per nuclide, per whatever else
	// the block is indexed by. Several hundred states behind one block, laid
	// out nuclide-innermost so that the decay chain is a stride-1 walk. See
	// ../domain/farfield.js.
	const farfLayout = [];
	for (const b of project.farfields ?? []) {
		const problem = structureProblem(b) ?? geometryProblem(b);
		if (problem) throw new BuildError(problem, b.qname ?? b.name);
		const dims = dimsOf(b);
		// Which of them the decay chain runs along. Indexed by nothing it
		// transports one quantity with no decay and no ingrowth, since there
		// is no chain for them to run along.
		const mIdx = dims.findIndex(isNuclideDim);
		// Two of them would be two decay chains along one path, and the second
		// would be laid out as an ordinary dimension -- silently transporting
		// the same nuclides twice. The dimension rules refuse a pair like that
		// before it reaches here (they share a root list); this is the guard
		// for a file that reached the builder another way.
		if (dims.filter(isNuclideDim).length > 1) {
			throw new BuildError(
				'A far-field path runs one decay chain, and it is indexed by two '
				+ `radionuclide dimensions (${dims.filter(isNuclideDim).join(' and ')}).`,
				b.qname ?? b.name,
			);
		}
		const listName = mIdx < 0 ? null : dims[mIdx];
		const nnuc = listName ? space.size(listName) : 1;
		// Everything else it is indexed by. One block is one path, and a path
		// per landscape object -- or per climate, or per waste type -- is that
		// many paths side by side: the same geometry read at that index, the
		// same cells, its own states. The runtime has always been written for
		// this (see FarfPath, which loops over `otherWidth`); what was missing
		// was the layout that says where each combination's values live.
		const otherIdx = dims.map((_, i) => i).filter((i) => i !== mIdx);
		const otherDims = otherIdx.map((i) => dims[i]);
		const otherWidth = space.width(otherDims);
		const ncells = cellCount(b);
		// Where each (combination, nuclide) sits among the block's own
		// dimensions, which is how every per-index slot of the block is
		// addressed -- and, for the settings that are not per nuclide, where
		// the combination alone sits among the other dimensions.
		const strides = space.strides(dims);
		const otherStrides = space.strides(otherDims);
		const dimOff = new Int32Array(otherWidth * nnuc);
		const singleOff = new Int32Array(otherWidth);
		for (let o = 0; o < otherWidth; o++) {
			let at = 0;
			for (let k = 0; k < otherDims.length; k++) {
				const pos = Math.floor(o / otherStrides[k]) % space.size(otherDims[k]);
				at += pos * strides[otherIdx[k]];
			}
			// A setting that is one value per path holds its values over the
			// other dimensions alone, laid out in the same order, so the
			// combination's own number is its offset.
			singleOff[o] = o;
			for (let m = 0; m < nnuc; m++) {
				dimOff[o * nnuc + m] = at + (mIdx >= 0 ? m * strides[mIdx] : 0);
			}
		}
		const entry = {
			name: b.qname ?? b.name, local: b.name, system: systemOf(b),
			base: nstate, width: otherWidth * ncells * nnuc, dims, block: b,
			kind: 'farfield', hidden: true,
			farf: {
				structure: {
					n_f: b.n_f, n_m: b.n_m, o_b: b.o_b, n_b: b.n_b,
				},
				nnuc, otherDims, otherWidth, ncells, mIdx, listName, dimOff, singleOff,
			},
		};
		stateLayout.push(entry);
		farfLayout.push(entry);
		nstate += entry.width;
	}
	// --- waste packages ------------------------------------------------------
	// Two inventories per index behind one block: what is still inside intact
	// packages, and what the failed ones have exposed. Both decay along the
	// model's chain like a compartment does (the decay loop below takes them),
	// neither answers to a name -- the block's name is its release, an
	// algebraic slot -- and what moves between them and out is worked out in
	// the derivative from the block's hazard, instant-release fraction and
	// degradation rate. See ../domain/wastepackage.js.
	const wasteLayout = [];
	for (const w of project.waste_packages ?? []) {
		const q = w.qname ?? w.name;
		const dims = dimsOf(w);
		const width = space.width(dims);
		const shared = {
			local: w.name, system: systemOf(w), width, dims, block: w, qname: q,
			kind: 'waste_package', hidden: true,
			// An inventory, in the inventory unit: the block's own unit is
			// its release's, which is that per unit time.
			unit: project.decayUnit,
		};
		const intact = { ...shared, name: `${q} intact`, role: 'intact', base: nstate };
		const exposed = { ...shared, name: `${q} exposed`, role: 'exposed', base: nstate + width };
		stateLayout.push(intact, exposed);
		wasteLayout.push({ q, block: w, intact, exposed, dims, width, failure: failureOf(w) });
		nstate += 2 * width;
	}
	const wasteByName = new Map(wasteLayout.map((W) => [W.q, W]));
	// --- disruptive events ---------------------------------------------------
	// One state per event: how many times it has happened -- the expected
	// number in a deterministic run, the count in a sampled realisation. It
	// is the block's own value, and it is charted. See ../domain/disruption.js.
	const disruptionLayout = [];
	for (const d of project.events ?? []) {
		const q = d.qname ?? d.name;
		const entry = {
			name: q, local: d.name, system: systemOf(d), base: nstate, width: 1, dims: [],
			block: d, qname: q, kind: 'event', hidden: false, unit: '',
		};
		stateLayout.push(entry);
		disruptionLayout.push({
			q, block: d, entry, timing: timingOf(d), actions: normaliseActions(d.actions),
			index: disruptionLayout.length, sampledTimes: [],
		});
		nstate += 1;
	}
	// --- the mass-balance budgets -------------------------------------------
	// Last in the vector, and only when asked for: one state per family per
	// kind of movement, accumulated as the derivative is emitted below and
	// integrated with everything else. A family is a radionuclide, plus one
	// for the compartments that are not indexed by any. See
	// ../domain/massbalance.js for what is done with them.
	const budgetLayout = (() => {
		if (!project.simulation?.mass_balance) return null;
		const mat = materialList ? space.get(materialList) : null;
		const families = [...(mat ? mat.enabled.map((i) => i.name) : []), UNINDEXED];
		const nfam = families.length;
		const members = [];
		for (const s of stateLayout) {
			// Waste packages hold inventory too, so the release out of them
			// into a compartment is a move rather than an arrival.
			if (s.kind !== 'compartment' && s.kind !== 'waste_package') continue;
			const famOf = new Int32Array(s.width).fill(nfam - 1);
			const m = s.dims.findIndex(isNuclideDim);
			if (m >= 0 && mat) {
				for (let off = 0; off < s.width; off++) {
					const name = tupleByList(space, s.dims, off)[s.dims[m]];
					famOf[off] = mat.positionOf.get(name) ?? nfam - 1;
				}
			}
			members.push({ name: s.name, base: s.base, width: s.width, famOf });
		}
		const budget = { base: nstate, nfam, families, terms: BUDGET_TERMS, members };
		stateLayout.push({
			name: '#mass-balance', local: '#mass-balance', system: '',
			base: nstate, width: BUDGET_TERMS.length * nfam, dims: [], block: null,
			kind: 'budget', hidden: true, budget,
		});
		nstate += BUDGET_TERMS.length * nfam;
		return budget;
	})();

	// Only compartments answer to a name in an equation: a reference to a
	// running mean means its value, which is an algebraic slot, not the
	// integral underneath it. Nor does a far-field path -- its name means the
	// release out of its far end, which is an algebraic slot too.
	const stateByName = new Map(
		stateLayout
			.filter((s) => s.kind === 'compartment')
			.map((s) => [s.name, s]),
	);
	// ...but a path is somewhere a flux can be delivered, so it answers as a
	// connection's endpoint. The inlet is the first fracture cell.
	const pathByName = new Map(farfLayout.map((f) => [f.name, f]));

	const paramLayout = [];
	let nparam = 0;
	for (const p of project.parameters) {
		const width = space.width(dimsOf(p));
		paramLayout.push({
			name: p.qname ?? p.name, local: p.name, system: systemOf(p),
			base: nparam, width, dims: dimsOf(p), block: p,
		});
		nparam += width;
	}
	const paramByName = new Map(paramLayout.map((p) => [p.name, p]));

	/**
	 * A point of a lookup table may carry its own distribution.
	 *
	 * A table is not one number, it is a curve, and a data set that knows how
	 * uncertain a release fraction is at the year it was measured knows it
	 * point by point -- `SRF` at year 0 is triangular on 62..1911 and at year
	 * 8700 on 1..23. Those are two spreads of one quantity, not one spread of
	 * two.
	 *
	 * Such a point gets a slot in `P`, because `P` is where every distributed
	 * value lives and a realisation has to be able to write it somewhere. The
	 * table is then rebuilt from those slots in `evaluateInvariant`, which is
	 * where everything else that a changed parameter invalidates is worked out
	 * again -- see `refreshTables`.
	 *
	 * Counted before `P` is allocated, since it decides how big `P` is.
	 */
	const pointLayout = [];
	for (const l of project.lookups ?? []) {
		const dims = dimsOf(l);
		const width = space.width(dims);
		for (let off = 0; off < width; off++) {
			const tuple = entryTuple(l, dims, off);
			const points = valueAt(l, 'points', tuple) ?? [];
			points.forEach((pt, i) => {
				const spec = Array.isArray(pt) ? pt[2] : null;
				if (!spec) return;
				pointLayout.push({
					name: l.qname ?? l.name, block: l, dims, index: tuple, off,
					point: i, at: Number(pt?.[0]), value: Number(pt?.[1]),
					spec, slot: nparam, tab: -1, row: -1,
				});
				nparam += 1;
			});
		}
	}
	const pointsByEntry = new Map();
	for (const pt of pointLayout) {
		const key = `${pt.name}\u0000${pt.off}`;
		if (!pointsByEntry.has(key)) pointsByEntry.set(key, []);
		pointsByEntry.get(key).push(pt);
	}

	const P = new Float64Array(Math.max(1, nparam));
	// A distributed point starts at the value the model holds, so a run with
	// nothing sampled is the run it always was.
	for (const pt of pointLayout) P[pt.slot] = pt.value;
	for (const entry of paramLayout) {
		for (let off = 0; off < entry.width; off++) {
			const tuple = entryTuple(entry.block, entry.dims, off);
			const v = valueAt(entry.block, 'value', tuple);
			const n = Number(v);
			if (!Number.isFinite(n)) {
				throw new BuildError(`Value '${v}' is not a number`, entry.name);
			}
			P[entry.base + off] = n;
		}
	}

	// --- lookup tables --------------------------------------------------
	// The tables are data, handed to the generated code as TAB rather than
	// written into it: the models on this machine carry 278,495 points, up to
	// 1961 in a single sub-table, and inlining those would make the derivative
	// function larger than the model it came from.
	//
	// A table indexed by, say, the nuclide list but given only one set of
	// points is one table shared by every slot, not N copies of it -- which is
	// what a per-nuclide table of a thousand points would otherwise cost.
	const TAB = [];
	const lookupLayout = [];
	for (const l of project.lookups ?? []) {
		const dims = dimsOf(l);
		const width = space.width(dims);
		const cache = new Map();
		const base = TAB.length;
		for (let off = 0; off < width; off++) {
			const tuple = entryTuple(l, dims, off);
			const points = valueAt(l, 'points', tuple) ?? [];
			// A table whose points are distributed is *not* shared: two index
			// slots reading one entry would otherwise be one draw shown twice,
			// where every other distributed value is drawn per slot. Saying so
			// here is also what keeps the cache correct for the ordinary case.
			const mine = pointsByEntry.get(`${l.qname ?? l.name}\u0000${off}`) ?? null;
			let table = mine ? undefined : cache.get(points);
			if (table === undefined) {
				try {
					// A table with no points reads as zero everywhere, which is
					// what Ecolego computes for one: a compiled lookup table keeps
					// a cached value it never fills in. Refusing to build would
					// mean a model with one unfinished table would not run at
					// all, and the editor says so beside the block instead.
					table = makeTable(points.length ? points : [[0, 0]], {
						interpolation: l.interpolation, cyclic: l.cyclic,
					});
				} catch (e) {
					if (e instanceof LookupError) {
						throw new BuildError(
							`${e.message}${dims.length ? ` at ${describeTuple(tuple)}` : ''}`,
							l.qname ?? l.name,
						);
					}
					throw e;
				}
				if (!mine) cache.set(points, table);
			}
			TAB.push(table);
			// Where this point's value ends up once the table is built:
			// `makeTable` sorts by x, so the row is the point's rank among the
			// times rather than its position in the file.
			if (mine) {
				const order = points.map((_, i) => i)
					.sort((a2, b2) => Number(points[a2]?.[0]) - Number(points[b2]?.[0]));
				const rank = new Map(order.map((from, to) => [from, to]));
				for (const pt of mine) {
					pt.tab = TAB.length - 1;
					pt.row = rank.get(pt.point) ?? pt.point;
				}
			}
		}
		lookupLayout.push({
			name: l.qname ?? l.name, local: l.name, system: systemOf(l),
			tab: base, width, dims, block: l, argument: l.argument ?? null,
		});
	}
	// A table with an argument is a function -- `Table(x)` -- so it has no slot
	// of its own; one without is read at the clock, and gets one like any other
	// algebraic quantity.
	const tableByName = new Map(
		lookupLayout.filter((l) => l.argument).map((l) => [l.name, l]),
	);

	// Algebraic blocks: expressions, transfer rates, source rates.
	const algebraic = [];
	let nalg = 0;
	// `over` overrides the block's own dimensions, for a slot that holds one
	// value where the block holds several: a far-field path's travel time is
	// one number however many nuclides travel along it.
	const addAlgebraic = (name, kind, block, valueKey, over = null) => {
		const dims = over ?? dimsOf(block);
		const width = space.width(dims);
		const entry = {
			name, local: block.name, system: systemOf(block),
			kind, block, valueKey, dims, base: nalg, width,
			// A copy the transport unrolling made, for one pair of the chain.
			...(block.hidden ? { hidden: true } : {}),
		};
		algebraic.push(entry);
		nalg += width;
		return entry;
	};
	for (const e of project.expressions) addAlgebraic(e.qname ?? e.name, 'expression', e, 'equation');
	for (const t of project.transfers) {
		const slot = addAlgebraic(t.qname ?? t.name, 'transfer', t, 'rate');
		// An availability's limit, or its two Langmuir coefficients, are the
		// transfer's own equations with slots of their own -- of the transfer's
		// dimensions, named with a `#` so that nothing can refer to them --
		// worked out before the transfer's value, which is then its rate times
		// the availability. So the flux is still `donor × value` wherever it
		// is assembled, `T * donor` in an equation is still the flux through
		// `T`, and the tangent generator differentiates the operands like any
		// other equation. See ../domain/availability.js.
		const scheme = schemeOf(t);
		if (!scheme) continue;
		slot.availability = { scheme, operands: {} };
		for (const key of operandKeys(scheme)) {
			const op = addAlgebraic(`${slot.name}#${key}`, `availability:${key}`,
				{ ...t, entries: [], [key]: scheme[key] }, key, slot.dims);
			op.hidden = true;
			// The transfer it belongs to, so that `k[_source_]` and a value
			// per transfer read in a limit mean what they mean in the rate.
			op.transfer = slot.name;
			slot.availability.operands[key] = op;
		}
		slot.needs = Object.values(slot.availability.operands).map((op) => op.name);
	}
	for (const s of project.inflows) addAlgebraic(s.qname ?? s.name, 'inflow', s, 'rate');
	// A compartment's explicit dy/dt term -- the extra term the standard
	// differential-equation assembly puts first in the sum of fluxes -- is a
	// rate read with the state, exactly as an inflow's is. So
	// it gets a slot of the compartment's own dimensions, named with a `#`
	// so that nothing can refer to it, and the derivative assembly adds it
	// to the compartment's own row. One slot per compartment that has one,
	// anywhere: a term set for one index alone is `0` at the others.
	const dydtSlots = [];
	for (const c of project.compartments) {
		if (!hasDydt(c)) continue;
		const name = c.qname ?? c.name;
		const slot = addAlgebraic(`${name}#dydt`, 'compartment:dydt', c, 'dydt');
		slot.hidden = true;
		slot.stateName = name;
		dydtSlots.push(slot);
	}
	for (const l of lookupLayout) {
		if (l.argument) continue;
		addAlgebraic(l.name, 'lookup', l.block, 'points').tab = l.tab;
	}
	for (const o of project.index_reductions ?? []) {
		addAlgebraic(o.qname ?? o.name, 'index_reduction', o, 'target');
	}
	for (const g of project.block_reductions ?? []) {
		addAlgebraic(g.qname ?? g.name, 'block_reduction', g, 'targets');
	}

	// Waste packages: every setting is an equation with a slot of its own --
	// the inventory and the instant-release fraction per index, the failure
	// and degradation settings one value per block -- named with a `#` so that
	// no equation can reach them. Two more slots are worked out from those and
	// from the two inventories: the hazard, and the block's own value, the
	// release. `needs` puts each after the slots it reads in the evaluation
	// order, which no equation of theirs would otherwise say. A setting the
	// block's way of failing does not read gets no slot: an empty Weibull
	// scale on packages that fail at a constant rate is not an equation to
	// compile. See ../domain/wastepackage.js.
	for (const W of wasteLayout) {
		W.setting = {};
		for (const key of WASTE_EQUATION_KEYS) {
			if (key.startsWith('fail_') && !FAILURE_KEYS[W.failure].includes(key)) continue;
			const single = !WASTE_NUCLIDE_KEYS.includes(key);
			const slot = addAlgebraic(`${W.q}#${key}`, `waste_package:${key}`, W.block, key, single ? [] : null);
			slot.hidden = true;
			if (single) slot.single = true;
			W.setting[key] = slot;
		}
		const hazard = addAlgebraic(`${W.q}#hazard`, 'waste_package:hazard', W.block, null, []);
		hazard.hidden = true;
		hazard.needs = FAILURE_KEYS[W.failure].map((key) => W.setting[key].name);
		hazard.waste = W;
		W.hazardSlot = hazard;
		const release = addAlgebraic(W.q, 'waste_package', W.block, null);
		release.needs = [hazard.name, W.setting.irf.name, W.setting.degradation_rate.name];
		release.waste = W;
		W.releaseSlot = release;
	}

	// Disruptive events: the time or the rate and its window as slots, one
	// slot per action for its share, and a `#lambda` slot holding the
	// expected-value rate -- the rate inside its window, switched off for a
	// realisation that samples the occurrences (`ctx.dis`). A blank window end
	// is the run's own, read off the context rather than given a slot. A fail
	// action adds `lambda * share` to the waste block's hazard, which is why
	// that slot has to be worked out after these. See ../domain/disruption.js.
	for (const D of disruptionLayout) {
		D.setting = {};
		for (const key of TIMING_KEYS[D.timing]) {
			if (!String(D.block[key] ?? '').trim()) continue;
			const slot = addAlgebraic(`${D.q}#${key}`, `event:${key}`, D.block, key, []);
			slot.hidden = true;
			slot.single = true;
			D.setting[key] = slot;
		}
		D.shares = D.actions.map((a, k) => {
			// The share is an equation on the action, resolved where the event
			// is: a holder that stands in for the block for that one key.
			const holder = { name: D.block.name, system: D.block.system, index_lists: [], entries: [], fraction: a.fraction };
			const slot = addAlgebraic(`${D.q}#share${k}`, 'event:share', holder, 'fraction', []);
			slot.hidden = true;
			slot.single = true;
			return slot;
		});
		const lam = addAlgebraic(`${D.q}#lambda`, 'event:lambda', D.block, null, []);
		lam.hidden = true;
		lam.needs = Object.values(D.setting).map((slot) => slot.name);
		lam.event = D;
		D.lambdaSlot = lam;
		D.actions.forEach((a, k) => {
			if (a.kind !== 'fail') return;
			const W = wasteByName.get(a.block);
			if (!W) {
				throw new BuildError(`'${a.block}' is not a set of waste packages, so it has no packages to fail.`, D.q);
			}
			W.hazardSlot.needs.push(lam.name, D.shares[k].name);
			(W.disrupted ??= []).push({ D, share: D.shares[k] });
		});
	}

	// A path's settings are equations like any other -- a travel time read from
	// a lookup table, a Kd per nuclide, a resistance scaled by an expression --
	// so each gets an algebraic slot of the block's own dimensions, and the
	// block's own slot holds the release out of the far end. The settings are
	// named with a `#`, which a block name cannot contain, so no equation can
	// reach them.
	const FARF = [];
	for (const p of farfLayout) {
		const settingBase = {};
		for (const key of FARF_EQUATION_KEYS) {
			// Chemistry is per nuclide; the path is not. A single-valued
			// setting gets one slot whatever the block is indexed by, so
			// `travel_time` cannot quietly differ between two nuclides
			// travelling the same fracture.
			const perNuclide = FARF_NUCLIDE_KEYS.includes(key);
			// ...but a path *per object* is a different path, so a setting
			// that is not per nuclide is still per everything else the block
			// is indexed by: one travel time for each of them, not one for the
			// block. With no other dimensions this is the scalar it was.
			const slot = addAlgebraic(
				`${p.name}#${key}`, `farfield:${key}`, p.block, key,
				perNuclide ? null : p.farf.otherDims,
			);
			slot.hidden = true;
			settingBase[key] = slot.base;
			if (!perNuclide) slot.single = true;
		}
		const rel = addAlgebraic(p.name, 'farfield', p.block, null);
		// Computed after every setting, whatever the equations mention.
		rel.needs = FARF_EQUATION_KEYS.map((key) => `${p.name}#${key}`);
		rel.farf = p;
		rel.farfIndex = FARF.length;
		p.algRelease = rel;
		p.farfIndex = FARF.length;
		FARF.push(new FarfPath({
			structure: p.farf.structure,
			base: p.base,
			nnuc: p.farf.nnuc,
			otherWidth: p.farf.otherWidth,
			dimOff: p.farf.dimOff,
			singleOff: p.farf.singleOff,
			settingBase,
			// Which settings hold one value: those are read at their own slot
			// rather than at the nuclide's.
			single: FARF_EQUATION_KEYS.filter((k) => !FARF_NUCLIDE_KEYS.includes(k)),
			releaseBase: rel.base,
		}));
	}

	// --- the blocks that remember ------------------------------------------
	// Each keeps a history at runtime -- `MEM`, beside `TAB` -- and each holds
	// its target in an ordinary algebraic slot of its own, so the dependency
	// order, the index machinery and the tangent generator all apply to it
	// without knowing anything about recorders. The slots are named with a
	// `#`, which a block name cannot contain, so nothing can refer to them.
	const MEM = [];
	const recorders = [];
	// Which collection each kind lives in, and which of its fields hold an
	// equation: both from ../domain/recorders.js, which is where the kinds
	// themselves are declared. They used to be written out again here, and a
	// second copy of a table is a table that can disagree with the first.
	const meanStateByName = new Map(meanStates.map((m) => [m.name, m]));
	for (const kind of RECORDER_KINDS) {
		for (const b of project[RECORDER_COLLECTION[kind]] ?? []) {
			const name = b.qname ?? b.name;
			const aux = {};
			for (const key of EQUATION_FIELDS[kind]) {
				const slot = addAlgebraic(`${name}#${key}`, `${kind}:${key}`, b, key);
				slot.hidden = true;
				aux[key] = slot;
			}
			const entry = addAlgebraic(name, kind, b, null);
			entry.aux = aux;
			// Computed after the parts it is made of, whatever the equations
			// happen to mention.
			entry.needs = Object.values(aux).map((a) => a.name);

			const rec = {
				name, kind, block: b, entry, aux,
				dims: entry.dims, width: entry.width,
				mem: REMEMBERING_KINDS.includes(kind) ? MEM.length : -1,
				state: meanStateByName.get(name) ?? null,
			};
			if (rec.mem >= 0) {
				for (let off = 0; off < entry.width; off++) {
					const tuple = entryTuple(b, entry.dims, off);
					// A recorder with a start event waits for it; one without
					// records from the first step, which is the decision
					// the min/max code generator makes when it generates the class.
					const start = valueAt(b, 'start_trigger', tuple);
					MEM.push(new Recorder(kind, {
						operation: b.operation,
						recording: !(start != null && String(start).trim() !== ''),
					}));
				}
			}
			recorders.push(rec);
			entry.recorder = rec;
		}
	}

	const algByName = new Map(algebraic.map((a) => [a.name, a]));

	// Nothing to integrate and nothing to evaluate used to be a BuildError
	// here. It is not an error: it is what a model looks like before anything
	// has been added to it, and refusing to build one meant that emptying a
	// model -- or starting one from nothing -- reported a fault in the file
	// where what was wanted was an empty chart and somewhere to click. The
	// run produces the time grid and whatever constants the model carries,
	// and the interface says there is nothing else yet.

	/**
	 * The lookup table a call names, seen from `system`, or null. Used both to
	 * let the parser accept the call and, later, to emit it.
	 */
	const callTarget = (name, system) => {
		if (!tableByName.size) return null;
		const q = resolveReference(name, system ?? '', (n) => (
			stateByName.has(n) || paramByName.has(n) || algByName.has(n)
			|| tableByName.has(n)
		));
		return q && tableByName.has(q) ? tableByName.get(q) : null;
	};

	// The user-defined functions, parsed once. A call of one is replaced by
	// its body where it is written, so nothing downstream has to know they
	// exist -- see ./functions.js.
	//
	// A function is global and a block is not, so a block of the same name in
	// the caller's own sub-system wins: `TR_adv(x)` inside `NF` means
	// `NF.TR_adv` if there is one, which is then not callable and is reported
	// as such. That is the ordinary resolution rule, applied to a call.
	let functions;
	try {
		// A body is written at the top level and may call what any equation
		// there may call: another function, or a table read at an argument.
		functions = userFunctions(project, {
			callable: (n, system) => !!callTarget(n, system ?? ''),
		});
	} catch (e) {
		if (e instanceof FunctionError) throw new BuildError(e.message, e.blockName);
		throw e;
	}
	const functionCall = (name, system) => (functions.size
		? functions.resolve(name, system ?? '')
		: null);
	/** Every call the parser should accept in an equation owned by `system`. */
	const callable = (name, system) => !!callTarget(name, system) || !!functionCall(name, system);
	/**
	 * One equation, parsed and with its function calls written out.
	 *
	 * Both halves together because they always go together: an AST that still
	 * holds a call of a user function is one no other pass here understands.
	 */
	// What a name is measured in, for the literal conversion below. Built from
	// the project's own blocks, whose units `Project` has already derived --
	// so a transfer's `1/year` and a compartment's inventory unit are here
	// without deriving them a second time.
	const unitBlocks = new Map(allBlocks(project).map((b) => [b.qname ?? b.name, b]));
	const timeDim = parseUnit(project.simulation.time_unit ?? 'year');
	const unitOfIn = (system) => (written) => {
		const q = resolveReference(String(written), system ?? '', (n) => unitBlocks.has(n));
		const text = q ? unitBlocks.get(q)?.unit : null;
		return text ? parseUnit(text) : null;
	};

	const parseEquation = (text, system, owner) => {
		let ast;
		try {
			ast = parse(text, { calls: (n) => callable(n, system) });
			// `p1 + 1000[mm]` with `p1` in metres is `p1 + 1`: a literal is
			// scaled to the unit of what it is written against, wherever the
			// two have to agree. Here rather than in the emitter because the
			// tangent generator compiles the same tree, so it converts too.
			// See ../domain/unitcheck.js.
			scaleLiterals(ast, unitOfIn(system), timeDim);
		} catch (e) {
			// A name called like a function that nobody defines. The parser
			// can only say it is not one of its own; what the reader needs is
			// the other half -- that a model may define its own, and how.
			const unknown = e instanceof ParseError
				&& /^Unknown function '([^']+)'/.exec(e.message);
			if (unknown) {
				throw new BuildError(
					`${e.message} in "${text}". If '${unknown[1]}' is meant to be one of `
					+ 'this model’s own, add a function of that name under Functions '
					+ 'and write what it works out to; Ecolego keeps some functions in a '
					+ 'library beside the project, and those do not travel with the file.',
					owner,
				);
			}
			throw e;
		}
		try {
			return functions.size ? functions.inline(ast, owner, system ?? '') : ast;
		} catch (e) {
			if (e instanceof FunctionError) throw new BuildError(e.message, e.blockName ?? owner);
			throw e;
		}
	};

	/** The layout entry a name refers to, seen from `system`, or null. */
	const targetEntry = (name, system) => {
		const q = resolveReference(name, system ?? '', (n) => (
			stateByName.has(n) || paramByName.has(n) || algByName.has(n)
			|| tableByName.has(n)
		));
		if (!q) return null;
		return stateByName.get(q) ?? paramByName.get(q) ?? algByName.get(q)
			?? tableByName.get(q) ?? null;
	};

	/**
	 * The equation an `index-operation` block stands for.
	 *
	 * the index-operation code generator writes a loop over the one index list of the
	 * target that the block itself is *not* indexed by -- `Total[nuclide] =
	 * sum over objects of Soil[nuclide][object]`. Written out as a call to the
	 * language's own `sum`, that loop is an ordinary equation, which is what
	 * the rest of this file already knows how to compile, differentiate and
	 * order.
	 *
	 * The reference nodes pin the operated dimension *by name of the list*
	 * rather than by index name: a target indexed by a list and a copy of it
	 * has the same index names twice, and asking for them by name would pin
	 * the wrong one -- or both.
	 */
	const indexOperationAst = (a, target) => {
		const entry = targetEntry(target, a.system);
		if (!entry) {
			throw new BuildError(
				`'${target}' is not a block in this model`
				+ (a.system ? ` or in '${a.system}'` : '') + '.', a.name,
			);
		}
		const dims = entry.dims ?? [];
		if (!dims.length) {
			throw new BuildError(
				`'${target}' holds a single value, so there is no index to reduce `
				+ `over. An index operation needs a target with one more dimension `
				+ `than it has itself.`, a.name,
			);
		}
		const over = operatedList(a.dims, dims, (d) => space.get(d)?.for_scenarios);
		if (!over) {
			throw new BuildError(
				`'${a.name}' is indexed by every list '${target}' is `
				+ `(${dims.join(', ')}), so there is nothing left to reduce over.`, a.name,
			);
		}
		const names = space.indexNames(over);
		// The convention is 0 for a target with no values at all, rather than
		// the -Infinity an empty max would otherwise give.
		if (!names.length) return { ast: { type: 'num', value: 0 }, text: '0', over };

		const fn = OPERATION_FUNCTION[a.block.operation];
		const args = names.map((idx) => ({
			type: 'ref', name: target, indices: { [over]: idx },
		}));
		if (a.block.operation === 'percentile') {
			args.unshift({ type: 'num', value: Number(a.block.percentile) });
		}
		const shown = names.map((idx) => `${target}[${idx}]`);
		if (a.block.operation === 'percentile') shown.unshift(String(a.block.percentile));
		return {
			ast: { type: 'call', name: fn, args },
			text: `${fn}(${shown.join(', ')})`,
			over,
		};
	};

	/**
	 * The equation an `aggregate` block stands for: its targets, combined
	 * element-wise at each index.
	 *
	 * the aggregate code generator assembles exactly this -- the tokens
	 * `sum ( t1 , t2 , ... )` -- and hands them to the ordinary equation
	 * compiler. A target whose dimensions cannot be reached from the
	 * aggregate's own position is left out rather than making the whole block
	 * fail, which is what that writer does with its `resolveIndexNames` check.
	 */
	const aggregateAst = (a, targets) => {
		const kept = [];
		const dropped = [];
		for (const t of targets) {
			const entry = targetEntry(t, a.system);
			if (!entry) {
				throw new BuildError(
					`'${t}' is not a block in this model`
					+ (a.system ? ` or in '${a.system}'` : '') + '.', a.name,
				);
			}
			try {
				space.projection(a.dims, entry.dims ?? [], {}, { owner: a.name, target: t });
				kept.push(t);
			} catch (e) {
				if (e instanceof IndexError) { dropped.push(t); continue; }
				throw e;
			}
		}
		if (dropped.length && !kept.length) {
			throw new BuildError(
				`none of its targets (${dropped.join(', ')}) can be reached from `
				+ `${a.dims.length ? `'${a.dims.join(', ')}'` : 'a single value'}.`, a.name,
			);
		}
		if (!kept.length) return { ast: { type: 'num', value: 0 }, text: '0', dropped };
		if (kept.length === 1) {
			return {
				ast: { type: 'ref', name: kept[0], indices: [] },
				text: kept[0],
				dropped,
			};
		}
		const fn = OPERATION_FUNCTION[a.block.operation];
		return {
			ast: {
				type: 'call',
				name: fn,
				args: kept.map((t) => ({ type: 'ref', name: t, indices: [] })),
			},
			text: `${fn}(${kept.join(', ')})`,
			dropped,
		};
	};

	// --- parse every equation, per index tuple ----------------------------
	for (const a of algebraic) {
		a.equations = [];
		a.asts = [];
		// A lookup has points, not an equation; there is nothing to parse and
		// nothing it can depend on.
		if (a.kind === 'lookup') { a.uniform = true; continue; }

		// Nor has a block that remembers: its value comes from its history and
		// from the slots holding its parts, which are parsed as the ordinary
		// algebraic blocks they are.
		if (a.recorder) { a.uniform = true; continue; }

		// Nor has a far-field path: its value is the release read off its own
		// cells, and its settings are the slots parsed beside it.
		if (a.kind === 'farfield') { a.uniform = true; continue; }

		// Nor have a waste package's hazard and release: both are worked out
		// from the setting slots parsed beside them and the two inventories.
		if (a.kind === 'waste_package' || a.kind === 'waste_package:hazard') { a.uniform = true; continue; }
		// Nor has an event's expected-value rate: it is the rate slot, gated.
		if (a.kind === 'event:lambda') { a.uniform = true; continue; }

		// The two reducing blocks have a target, not an equation: the equation
		// is worked out from the model and built directly, so that no name has
		// to survive a round trip through the tokenizer.
		if (a.kind === 'index_reduction' || a.kind === 'block_reduction') {
			for (let off = 0; off < a.width; off++) {
				const tuple = entryTuple(a.block, a.dims, off);
				const spec = a.kind === 'index_reduction'
					? indexOperationAst(a, String(valueAt(a.block, 'target', tuple) ?? ''))
					: aggregateAst(a, valueAt(a.block, 'targets', tuple) ?? []);
				a.equations.push(spec.text);
				a.asts.push(spec.ast);
				if (spec.over) a.over = spec.over;
				if (spec.dropped?.length) a.dropped = spec.dropped;
			}
			a.uniform = a.equations.every((e) => e === a.equations[0]);
			continue;
		}

		// One parse per distinct equation, not one per index tuple. A block
		// indexed by a thousand-index list nearly always writes one equation
		// for all of them -- that is what `uniform` below is about -- and it
		// was tokenised and parsed a thousand times over. The trees are read
		// and never written after this, by the emitter or by anything else,
		// so the tuples that share a text can share a tree.
		const parsed = new Map();
		for (let off = 0; off < a.width; off++) {
			const tuple = entryTuple(a.block, a.dims, off);
			const eq = String(valueAt(a.block, a.valueKey, tuple) ?? '0');
			a.equations.push(eq);
			let ast = parsed.get(eq);
			if (ast === undefined) {
				try {
					ast = parseEquation(eq, a.system, a.name);
				} catch (err) {
					if (err instanceof ParseError) {
						throw new BuildError(
							`${err.message} in "${eq}" (at character ${err.position + 1})`, a.name,
						);
					}
					throw err;
				}
				parsed.set(eq, ast);
			}
			a.asts.push(ast);
		}
		a.uniform = a.equations.every((e) => e === a.equations[0]);
	}

	orderAlgebraic(algebraic, algByName);

	// --- reference resolution ---------------------------------------------
	/**
	 * Emits the JS expression for a reference.
	 *
	 * `loopVars` names the in-scope loop variable per source dimension, or is
	 * null when the referring statement is unrolled at a fixed tuple (in which
	 * case `fixedTuple` gives that tuple).
	 */
	/**
	 * `owner` is the block the equation belongs to: its name for messages, and
	 * its sub-system, which is what a bare reference is looked up in.
	 */
	const makeLocator = (owner, sourceDims, loopVars, fixedTuple) => (name, indices, node) => {
		const ownerName = typeof owner === 'string' ? owner : owner?.name;
		// A reference the function inliner moved here was written somewhere
		// else, and means what it meant there: `Water` in a function's body is
		// the `Water` that body could see, not the one in the sub-system the
		// call happens to be in. The node carries that scope; everything
		// written in place carries none and takes the owner's.
		const ownerSystem = node?.scope != null
			? node.scope
			: (typeof owner === 'string' ? '' : owner?.system ?? '');
		const qname = resolveReference(name, ownerSystem, (n) => (
			stateByName.has(n) || paramByName.has(n) || algByName.has(n)
			|| tableByName.has(n)
		));
		const target = qname
			? (stateByName.get(qname) ?? paramByName.get(qname) ?? algByName.get(qname)
				?? tableByName.get(qname))
			: null;
		if (!target) {
			// A block that exists and is switched off is a different mistake
			// from a name that is nobody's, and the fix is different too.
			const off = resolveReference(name, ownerSystem, (n) => project.disabled?.has(n));
			if (off) {
				throw new BuildError(
					`'${name}' is disabled, so it has no value for this equation to `
					+ `read. Enable '${off}', or disable this block as well.`,
					ownerName,
				);
			}
			throw new BuildError(
				`Unknown name '${name}'. It is not a parameter, compartment, expression `
				+ `or transfer ${ownerSystem
					? `in sub-system '${ownerSystem}' or at the top level of this model. `
						+ `To reach a block in another sub-system, give its full path, as in `
						+ `'${ownerSystem}.${name}'.`
					: 'in this model.'}`, ownerName,
			);
		}
		// Keyed by the *resolved* name. Asking with the written one gets it
		// wrong the moment a sub-system is involved: `Water` inside `NF` is not
		// in stateByName, so a compartment reference was classified as
		// algebraic and read out of the wrong array.
		const kind = stateByName.has(qname) ? 'state'
			: paramByName.has(qname) ? 'param'
				: tableByName.has(qname) ? 'table' : 'alg';

		// Explicit indices, `C1[Cs-137]` or `M[_Ra-226][Pb-210]`, pin one
		// dimension each.
		//
		// A *synthesised* reference -- the ones the reducing blocks build --
		// may instead name the dimension outright, as { Objects: '01' }. That
		// is not something an equation can write, and it exists because a
		// target indexed by a list and a copy of it carries the same index
		// names twice: asking for them by name would pin the wrong list.
		const context = implicitIndices(owner);
		const fixedIndices = indices && !Array.isArray(indices) && typeof indices === 'object'
			? { ...indices }
			: pinIndices(space, target, indices, name, ownerName, context);

		// The dimensions the reference has not accounted for: not pinned in
		// the equation, and not carried by the position the equation is being
		// evaluated at. A transfer and a compartment can still answer for two
		// of them, by being themselves.
		for (const dim of target.dims) {
			if (fixedIndices[dim] !== undefined) continue;
			// `relate` covers the exact list, a sub-set of it and a mapping
			// onto it -- every way the loop can supply a position.
			if (sourceDims.some((sd) => space.relate(dim, sd))) continue;
			let implied = context?.[dim] ?? null;
			// A list *derived from* one of those two -- a sub-set of the
			// transfers that are advective, a mapping of media onto the
			// compartments -- is answered for the same way: the block's own
			// index, carried into the list. the desktop tool's index-name
			// resolution answers the same way for a sub-set and a mapping alike; a
			// block outside the list is the one case it cannot answer.
			if (implied == null && context) {
				const root = space.get(dim).rootName;
				if (root !== dim && context[root] != null) {
					const own = derivedIndex(space, dim, context[root]);
					if (own === false) {
						throw new BuildError(
							`'${name}' has a value per index of '${dim}', which is made of `
							+ `${root === TRANSFER_LIST ? 'transfers' : 'compartments'}, and `
							+ `'${ownerName}' is not one of them. Add it to '${dim}', or name `
							+ `one, as '${name}[<index>]'.`,
							ownerName,
						);
					}
					implied = own;
				}
			}
			if (implied != null) { fixedIndices[dim] = implied; continue; }
			// Nothing can answer for it. For the two derived lists that is
			// worth saying properly: the fix is a word rather than a rethink,
			// and the generic message would name a list nobody declared.
			if (dim === COMPARTMENT_LIST) {
				throw new BuildError(
					`'${name}' has a value per compartment, and `
					+ `${ownerName ? `'${ownerName}'` : 'this equation'} does not say `
					+ `which. ${owner?.kind === 'transfer'
						? `Write '${name}[${SOURCE_INDEX}]' for the compartment it flows `
							+ `out of, or '${name}[${TARGET_INDEX}]' for the one it flows `
							+ `into.`
						: `Name one, as '${name}[<compartment>]'.`}`,
					ownerName,
				);
			}
			if (dim === TRANSFER_LIST) {
				throw new BuildError(
					`'${name}' has a value per transfer, and `
					+ `${ownerName ? `'${ownerName}'` : 'this equation'} is not a `
					+ `transfer, so there is no transfer to take it from. Name one, `
					+ `as '${name}[<transfer>]'.`,
					ownerName,
				);
			}
		}

		const targetBase = kind === 'table' ? target.tab : target.base;
		if (target.width === 1 && target.dims.length === 0) {
			return { kind, target, offset: String(targetBase) };
		}

		// Unrolled: every component is known, so the offset is a constant.
		if (fixedTuple) {
			const tuple = { ...fixedTuple, ...fixedIndices };
			let off = 0;
			const strides = space.strides(target.dims);
			for (let i = 0; i < target.dims.length; i++) {
				const dim = target.dims[i];
				const pos = positionIn(space, dim, tuple);
				if (pos == null) {
					// Reuse the projection machinery for its error text, which
					// names the list and suggests a fix.
					try {
						space.projection(sourceDims, [dim], fixedIndices,
							{ owner: ownerName, target: name });
					} catch (e) {
						if (e instanceof IndexError) throw new BuildError(e.message, ownerName);
						throw e;
					}
					throw new BuildError(
						`Cannot resolve index '${dim}' of '${name}'`, ownerName,
					);
				}
				off += pos * strides[i];
			}
			return { kind, target, offset: String(targetBase + off) };
		}

		// Looped: build the offset expression from the loop variables.
		let terms;
		try {
			terms = space.projection(sourceDims, target.dims, fixedIndices,
				{ owner: ownerName, target: name });
		} catch (e) {
			if (e instanceof IndexError) throw new BuildError(e.message, ownerName);
			throw e;
		}

		const parts = [];
		let constant = targetBase;
		for (const term of terms) {
			if (term.fixed != null) {
				constant += term.fixed * term.stride;
				continue;
			}
			const v = loopVars[term.from];
			const comp = term.table ? `MAPS[${mapIndex(term.table)}][${v}]` : v;
			parts.push(term.stride === 1 ? comp : `${comp} * ${term.stride}`);
		}
		const expr = [constant, ...parts].filter((p) => p !== 0 || parts.length === 0).join(' + ');
		return { kind, target, offset: expr || '0' };
	};

	// The array each kind of block lives in. Splitting "where is it" from "how
	// do I read it" is what lets the Jacobian generator reuse the offsets: it
	// needs the same slot in a different array (the seed, or the tangent), and
	// rewriting an emitted `y[...]` string would be guesswork.
	const ARRAY_OF = { state: 'y', param: 'P', alg: 'X' };
	const makeResolver = (owner, sourceDims, loopVars, fixedTuple) => {
		const locate = makeLocator(owner, sourceDims, loopVars, fixedTuple);
		// `node` goes through: a reference the function inliner moved here
		// carries the scope it was written in, and only the node says so.
		return (name, indices, node) => {
			const r = locate(name, indices, node);
			if (r.kind === 'table') {
				throw new BuildError(
					`'${name}' is a lookup table with an argument, so it has no value `
					+ `of its own; call it, as '${name}(...)'.`,
					typeof owner === 'string' ? owner : owner?.name,
				);
			}
			return `${ARRAY_OF[r.kind]}[${r.offset}]`;
		};
	};

	/**
	 * Emits a call the model itself defines: a lookup table with an argument,
	 * `Table(x)`. Returns null for every other name, which leaves `min`, `exp`
	 * and the rest to the built-in function table.
	 *
	 * The slope comes back beside the value because the Jacobian needs it and
	 * the table is the only thing that can supply it -- the derivative of a
	 * piecewise-linear table is the slope of the segment the argument lands in,
	 * which is exact, unlike a difference taken across one of its corners.
	 */
	const makeCall = (owner, sourceDims, loopVars, fixedTuple) => {
		const locate = makeLocator(owner, sourceDims, loopVars, fixedTuple);
		const ownerName = typeof owner === 'string' ? owner : owner?.name;
		const ownerSystem = typeof owner === 'string' ? '' : owner?.system ?? '';
		return (name, args) => {
			if (!callTarget(name, ownerSystem)) return null;
			if (args.length !== 1) {
				throw new BuildError(
					`'${name}' is a lookup table and takes exactly one argument; `
					+ `${args.length} were given.`, ownerName,
				);
			}
			const { offset } = locate(name, []);
			return {
				value: `TAB[${offset}].at(${args[0]})`,
				slope: `TAB[${offset}].slopeAt(${args[0]})`,
			};
		};
	};

	// --- discrete events ---------------------------------------------------
	// One slot per event block per index tuple, in the order the solver sees
	// them. The event function is the block's own value -- `first - second`,
	// which is what the event code generator assembles -- so the solver reads
	// it straight out of the algebraic vector.
	const eventSlots = [];
	for (const rec of recorders) {
		if (rec.kind !== 'trigger') continue;
		rec.eventBase = eventSlots.length;
		for (let off = 0; off < rec.width; off++) {
			const tuple = entryTuple(rec.block, rec.dims, off);
			const written = valueAt(rec.block, 'direction', tuple) ?? rec.block.direction;
			eventSlots.push({
				slot: rec.entry.base + off,
				direction: DIRECTION_SIGN[written] ?? 0,
				name: rec.name,
				index: rec.dims.length ? tupleByList(space, rec.dims, off) : null,
			});
		}
	}
	const eventDirection = Int8Array.from(eventSlots.map((e) => e.direction));

	// What each event does when it fires: take a snapshot, reset a min/max,
	// start or stop a recording. Ecolego stores these as equations whose one
	// token is a reference to the event block, so they are resolved exactly
	// the way a reference in any other equation is.
	const eventHandlers = new Map();
	for (const rec of recorders) {
		if (rec.mem < 0) continue;
		for (const field of EVENT_FIELDS[rec.kind]) {
			for (let off = 0; off < rec.width; off++) {
				const tuple = entryTuple(rec.block, rec.dims, off);
				const written = valueAt(rec.block, field, tuple);
				const text = written == null ? '' : String(written).trim();
				if (!text) continue;

				let ast;
				try {
					ast = parse(text);
				} catch (err) {
					throw new BuildError(
						`'${text}' is not the name of a discrete event.`, rec.name,
					);
				}
				if (ast.type !== 'ref') {
					throw new BuildError(
						`'${field.replace(/_/g, ' ')}' must name a discrete event, `
						+ `not an expression; '${text}' is one.`, rec.name,
					);
				}
				const found = makeLocator(rec.entry, rec.dims, null, tuple)(ast.name, ast.indices);
				const owner = found.target?.recorder;
				if (!owner || owner.kind !== 'trigger') {
					throw new BuildError(
						`'${ast.name}' is not a discrete event, so it cannot `
						+ `${field === 'trigger' ? 'take a snapshot' : field.replace(/_/g, ' ')}.`,
						rec.name,
					);
				}
				const which = owner.eventBase + (Number(found.offset) - found.target.base);
				if (!eventHandlers.has(which)) eventHandlers.set(which, []);
				eventHandlers.get(which).push({
					rec, off, action: EVENT_ACTION[field],
				});
			}
		}
	}

	/**
	 * What an availability's amount is made of: one term per inventory it
	 * sums, each `{ off, factor, when }` -- a state offset, the weight a unit
	 * of it carries (1, or moles per unit on a molar basis), and the condition
	 * under which it is in this flux's group at all (null for always).
	 *
	 * For an individual scheme that is the donor's own inventory. For a
	 * shared one it is the donor summed over a group, and `over` says which:
	 *
	 *   one of the donor's own lists   the whole of it -- one limit for every
	 *                                  nuclide the donor holds;
	 *   a grouping of one of them      one group per index of the grouping --
	 *                                  over `Elements`, the isotopes of each
	 *                                  element against that element's limit,
	 *                                  which is what an elemental solubility
	 *                                  is.
	 *
	 * Which group this flux is in is only known when the code runs -- it is
	 * the grouping's table read at the loop's own index -- so a grouped term
	 * carries its condition, `MAPS[g][peer] === 3`, against the member's group
	 * worked out here. The members are written out one per term, as the
	 * whole-list sum always was: the group is known at build time. Every
	 * member of a group then gets the same availability, which is what keeps
	 * the proportions of what moves those of what is there; AMBER makes the
	 * same point, that the values "are all equal ... this ensures that the
	 * available amounts are in proportion to the full amounts".
	 *
	 * The derivative (as the amount), the tangent (as its tangent) and the
	 * sparsity pattern (as the columns a flux reads) are all written from this
	 * one list, so the three cannot disagree about what is in a group.
	 */
	const availabilityTerms = (transfer, scheme, src, alg, space2, vars, mapIdx) => {
		const base = stateOffsetExpr(space2, alg.dims, vars, src, transfer.name, mapIdx);
		const own = [{ off: base, factor: 1, when: null }];
		if (!isShared(scheme.scheme)) return own;
		const over = String(scheme.over ?? '').trim();
		const dims = src.dims ?? [];
		// Which of the donor's lists the group runs along, and how: the list
		// itself (one group), or a grouping of it -- several of its indices to
		// one of `over`'s, as `Elements` is of the nuclides.
		let which = dims.indexOf(over);
		let groups = null;
		if (which < 0 && over && space2.has(over)) {
			const grouping = space2.get(over);
			for (let k = 0; k < dims.length && which < 0; k++) {
				if (!grouping.mapping || grouping.rootName !== space2.get(dims[k]).rootName) continue;
				const rel = space2.relate(over, dims[k]);
				if (!rel || rel.kind !== 'map') continue;
				which = k;
				groups = rel.table;
			}
		}
		// Where the donor has nothing along `over` there is nothing to share,
		// and the sum is the donor itself -- which is the individual scheme,
		// and the right answer rather than an error.
		if (which < 0) return own;
		const along = dims[which];
		const size = space2.size(along);
		if (!(size > 1)) return own;
		const stride = space2.strides(dims)[which];
		// Where in its list *this* one sits. `vars` is positional against the
		// dimensions the loop was opened over -- the transfer's, not the
		// donor's -- so the variable is found by position in those, and carried
		// through a table when the transfer is indexed by a sub-set of it.
		let peer = null;
		const at = (alg.dims ?? []).indexOf(along);
		if (at >= 0 && vars[at] != null) {
			peer = vars[at];
		} else {
			for (let k = 0; k < (alg.dims ?? []).length && peer == null; k++) {
				const rel = space2.relate(along, alg.dims[k]);
				if (rel && rel.kind === 'map' && vars[k] != null) {
					peer = `MAPS[${mapIdx(Array.from(rel.table))}][${vars[k]}]`;
				}
			}
		}
		if (peer == null) {
			throw new BuildError(
				`'${transfer.name}' shares its amount along '${along}', which the transfer is `
				+ 'not indexed by, so there is no telling which member of the group each flux '
				+ 'belongs to.', transfer.name,
			);
		}
		// The offset of the list's first member: this one's offset with its
		// own contribution along the shared dimension taken back out.
		const first = `((${base}) - ${stride === 1 ? peer : `${stride} * ${peer}`})`;
		// In moles, each member is weighted by what a unit of its inventory is
		// in atoms -- a build-time constant per isotope, from its half-life --
		// so an elemental limit is shared by atoms and not by activity. The
		// factors are written into the line, where the tangent generator sees
		// them as the constants they are.
		const moles = basisOf(scheme) === 'moles';
		const names = space2.get(along).enabled ?? [];
		const unit = project.simulation?.time_unit ?? 'year';
		const secondsPer = TIME_UNITS[unit] * SECONDS_PER_YEAR;
		const groupAt = groups ? `MAPS[${mapIdx(Array.from(groups))}][${peer}]` : null;
		const terms = [];
		for (let i = 0; i < size; i++) {
			// A member in no group shares with nothing.
			if (groups && groups[i] < 0) continue;
			const factor = moles
				? molesPerUnit(project.decayUnit, lambda(names[i]?.name, unit, project.halfLives), secondsPer)
				: 1;
			// A stable isotope contributes nothing in becquerels: left out
			// rather than multiplied by zero, which reads as what it is.
			if (factor === 0) continue;
			terms.push({
				off: i === 0 ? first : `${first} + ${i * stride}`,
				factor,
				when: groupAt ? `${groupAt} === ${groups[i]}` : null,
			});
		}
		return terms;
	};

	/** The amount, as one expression over `y` -- or over `v`, for its tangent. */
	const availabilitySum = (terms, vec) => {
		if (!terms.length) return '0';
		const parts = terms.map((term) => {
			const read = term.factor === 1 ? `${vec}[${term.off}]` : `${term.factor} * ${vec}[${term.off}]`;
			return term.when ? `(${term.when} ? ${read} : 0)` : read;
		});
		return parts.length === 1 ? parts[0] : `(${parts.join(' + ')})`;
	};

	/**
	 * A transfer with an availability: its value is its rate times the
	 * availability, worked out right after the rate -- one pass over the
	 * transfer's dimensions, whichever way the rate itself was written out --
	 * so that the flux is `donor × value` wherever it is assembled and the
	 * transfer's name in an equation means the same product.
	 */
	const emitAvailability = (lines, a) => {
		const t = a.block;
		const src = t.from ? stateByName.get(t.from) : null;
		if (!src) {
			throw new BuildError(
				`'${t.name}' has an availability, which is a fraction of what is in the `
				+ 'compartment it flows out of, and it does not flow out of one.', t.name,
			);
		}
		const { scheme, operands } = a.availability;
		emitLoop(lines, space, a.dims, '\t', (vars, offExpr, indent) => {
			const terms = availabilityTerms(t, scheme, src, a, space, vars, mapIndex);
			const ops = {};
			for (const [key, op] of Object.entries(operands)) ops[key] = `X[${op.base} + ${offExpr}]`;
			lines.push(`${indent}{`);
			lines.push(`${indent}\tconst am = ${availabilitySum(terms, 'y')};`);
			lines.push(`${indent}\tX[${a.base} + ${offExpr}] *= ${expressionOf(scheme, 'am', ops)};`);
			lines.push(`${indent}}`);
		});
	};

	// --- generate the algebraic block --------------------------------------
	const algLines = [];
	// Which lines belong to which block, so that the few an initial condition
	// reads can be run before it -- see `buildInitialState`.
	const algLineRanges = new Map();
	// Where each block's lines start, recorded positionally. `algLineRanges`
	// cannot be used for this: three kinds -- a lookup, a far-field, a block
	// that remembers -- `continue` out of the loop below before it is set, and
	// a split that lost their lines would drop them from the run.
	const algSpans = [];
	for (const a of algebraic) {
		const from = algLines.length;
		algSpans.push(from);
		algLines.push(`\t// ${a.kind} ${inComment(a.name)}`
			+ `${a.dims.length ? ` [${inComment(a.dims.join(' x '))}]` : ''}`);
		if (a.kind === 'lookup') {
			// Read at the clock. Nothing else in the model can move it, which
			// is what makes it a time-dependent parameter rather than a state.
			if (a.width === 1 && a.dims.length === 0) {
				algLines.push(`\tX[${a.base}] = TAB[${a.tab}].at(ctx.t);`);
			} else {
				emitLoop(algLines, space, a.dims, '\t', (vars, offExpr, indent) => {
					algLines.push(
						`${indent}X[${a.base} + ${offExpr}] = TAB[${a.tab} + ${offExpr}].at(ctx.t);`,
					);
				});
			}
			continue;
		}
		if (a.kind === 'farfield') {
			// One call fills every slot of the block: the release is read off
			// the path's own cells, and the rates it is read with come from
			// the settings computed just above. Runtime rather than generated
			// code because the structure is the same for every nuclide and
			// every index -- see ./farfield.js.
			algLines.push(`\tFARF[${a.farfIndex}].release(y, X);`);
			continue;
		}
		if (a.kind === 'waste_package:hazard') {
			// The fraction of the still-intact packages failing per unit time,
			// from the clock and the failure settings. `at` is a jump, not a
			// rate, and its hazard is 0 -- see the jumps below.
			const W = a.waste;
			const at = (key) => (W.setting[key] ? `X[${W.setting[key].base}]` : '0');
			// ...plus, for each disruptive event that fails a share of these
			// packages, its expected-value rate times the share.
			const extra = (W.disrupted ?? [])
				.map(({ D, share }) => ` + X[${D.lambdaSlot.base}] * X[${share.base}]`).join('');
			algLines.push(`\tX[${a.base}] = ${hazardCode(W.failure, {
				t: 'ctx.t', from: at('fail_from'), to: at('fail_to'), start: at('fail_start'),
				rate: at('fail_rate'), scale: at('fail_scale'), shape: at('fail_shape'),
			})}${extra};`);
			continue;
		}
		if (a.kind === 'event:lambda') {
			// The expected-value rate: the rate inside the window, and nothing
			// for an event at a time, which is a jump. `ctx.dis` is 1 unless a
			// realisation has drawn the occurrences, when it is 0.
			const D = a.event;
			if (D.timing !== 'poisson') { algLines.push(`\tX[${a.base}] = 0;`); continue; }
			const from = D.setting.from ? `X[${D.setting.from.base}]` : 'ctx.startTime';
			const until = D.setting.until ? `X[${D.setting.until.base}]` : 'ctx.endTime';
			algLines.push(`\tX[${a.base}] = ctx.dis[${D.index}] * `
				+ `(ctx.t >= ${from} && ctx.t < ${until} ? X[${D.setting.rate.base}] : 0);`);
			continue;
		}
		if (a.kind === 'waste_package') {
			// The release: what the failing packages let go at once, and what
			// the degrading matrix carries out congruently.
			const W = a.waste;
			emitLoop(algLines, space, a.dims, '\t', (vars, offExpr, indent) => {
				algLines.push(`${indent}X[${a.base} + ${offExpr}] = X[${W.hazardSlot.base}] * `
					+ `y[${W.intact.base} + ${offExpr}] * X[${W.setting.irf.base} + ${offExpr}] + `
					+ `X[${W.setting.degradation_rate.base}] * y[${W.exposed.base} + ${offExpr}];`);
			});
			continue;
		}
		if (a.recorder) {
			// The value of a block that remembers: its history, its target as
			// it stands, and for a running mean the integral the solver
			// carries. Every part shares the block's own dimensions, so one
			// offset addresses all of them.
			const rec = a.recorder;
			const value = (off) => {
				const at = (slot) => `X[${slot.base} + ${off}]`;
				switch (rec.kind) {
					case 'min_max':
						return `MEM[${rec.mem} + ${off}].extreme(ctx.t, ${at(rec.aux.target)})`;
					case 'running_mean':
						return `MEM[${rec.mem} + ${off}].mean(ctx.t, `
							+ `y[${rec.state.base} + ${off}], ${at(rec.aux.target)})`;
					case 'snapshot':
						return `MEM[${rec.mem} + ${off}].held(ctx.t)`;
					case 'delay':
						return `MEM[${rec.mem} + ${off}].delayed(ctx.t, ${at(rec.aux.delay)})`;
					default:
						// A discrete event is not a memory but a crossing: its
						// value is the gap between the two expressions, and the
						// solver stops where that passes through zero.
						return `${at(rec.aux.first)} - ${at(rec.aux.second)}`;
				}
			};
			if (a.width === 1 && a.dims.length === 0) {
				algLines.push(`\tX[${a.base}] = ${value('0')};`);
			} else {
				emitLoop(algLines, space, a.dims, '\t', (vars, offExpr, indent) => {
					algLines.push(`${indent}X[${a.base} + ${offExpr}] = ${value(offExpr)};`);
				});
			}
			continue;
		}
		if (a.width === 1 && a.dims.length === 0) {
			const code = emit(a.asts[0], makeResolver(a, [], null, {}), makeCall(a, [], null, {}));
			algLines.push(`\tX[${a.base}] = ${code};`);
		} else if (a.uniform) {
			emitLoop(algLines, space, a.dims, '\t', (vars, offExpr, indent) => {
				const code = emit(a.asts[0], makeResolver(a, a.dims, vars, null),
					makeCall(a, a.dims, vars, null));
				algLines.push(`${indent}X[${a.base} + ${offExpr}] = ${code};`);
			});
		} else {
			// Per-entry equations differ. One body per *distinct* equation,
			// looping the dimensions it does not vary along -- where every
			// index differs, that is one body per tuple, which is the switch
			// over index combinations the equation rewriter writes.
			emitByEquation(algLines, space, a, '\t', ({ ast, vars, tuple, slot, indent }) => {
				const code = emit(ast, makeResolver(a, a.dims, vars, tuple),
					makeCall(a, a.dims, vars, tuple));
				algLines.push(`${indent}X[${slot}] = ${code};`
					+ `${tuple ? `  // ${describeTuple(tuple)}` : ''}`);
			});
		}
		// Rate times availability, in the same block's lines -- so a rate that
		// reads nothing that moves still moves with the inventory it scales,
		// and is worked out on every call.
		if (a.availability) emitAvailability(algLines, a);
		algLineRanges.set(a.name, [from, algLines.length]);
	}

	// --- which of those never change -----------------------------------------
	// Every algebraic slot above is worked out again on every derivative call,
	// and most of them give the number they gave last time. On
	// model A that is 60,606 of 65,751 slots -- 92% -- recomputed
	// two or three times a step for eight hundred steps. They are the transfer
	// rates and the expressions built from parameters alone: constant for a run
	// by construction, and recomputed only because the emitted pass is one
	// straight line that does not distinguish them.
	//
	// A slot moves during a run if its own code reads the state (`y[`), the
	// clock (`ctx`, which covers `ctx.t` and `F.time.fn(ctx)` alike), a lookup
	// table (`TAB[`, read at the clock), a history (`MEM[`) or a far-field path
	// (`FARF`) -- or if anything it reads moves. Everything else is worked out
	// once, at the end of the build, and left in `X`.
	//
	// The test is deliberately crude in the safe direction. `start_time()` is
	// constant within a run and is marked as moving because it takes `ctx`; a
	// block whose *name* contains one of these words marks itself. Both cost an
	// optimisation and neither can make a moving slot look still, because the
	// scan only ever adds to the set.
	//
	// What it may not do is decide this from the equations' syntax and be
	// wrong: `test/run.js` perturbs the clock and the state on every bundled
	// example and fails if a slot called still has moved.
	// Two markers, not one. A slot that reads the state (`y[`), a history
	// (`MEM[`) or a far-field path (`FARF`) has to be worked out on every call.
	// A slot that reads only the clock -- `ctx`, which covers `ctx.t` and
	// `F.time.fn(ctx)` alike, or `TAB[`, a lookup read at the clock -- has to
	// be worked out once per *instant*, and a stiff solver asks for the
	// derivative several times at the same instant: every Newton iteration of a
	// step, and every colour of a differenced Jacobian.
	//
	// That distinction is most of the gain here. On model A only
	// **216 of 65,751 slots** depend on the state at all; on
	// model C, 216 of 128,479. The rest is a function of time, and
	// was being recomputed two or three times per step for no reason.
	const READS_STATE = /y\[|MEM\[|FARF/;
	const READS_CLOCK = /ctx|TAB\[/;
	const onState = new Set();
	const onClock = new Set();
	// `algebraic` is in dependency order -- orderAlgebraic put it there -- so
	// one pass forwards settles what reads what.
	const spanOf = (k) => [algSpans[k], k + 1 < algSpans.length ? algSpans[k + 1] : algLines.length];
	algebraic.forEach((a, k) => {
		const [from, to] = spanOf(k);
		let state = false;
		let clock = false;
		for (let i = from; i < to; i++) {
			if (!state) state = READS_STATE.test(algLines[i]);
			if (!clock) clock = READS_CLOCK.test(algLines[i]);
		}
		for (const d of a.readsAlg ?? []) {
			if (onState.has(d)) state = true;
			if (onClock.has(d)) clock = true;
		}
		if (state) onState.add(a.name);
		if (clock) onClock.add(a.name);
	});

	// Three passes, in this order: what never changes, what changes with the
	// clock, what changes with the state. A clock-only block can only read
	// constant or clock-only blocks -- reading a state-dependent one would make
	// it state-dependent -- so running them in this order keeps every block
	// after the ones it reads, which is what the dependency order was for.
	const onceLines = [];
	const clockLines = [];
	const stepLines = [];
	// Marked per slot, for the tests and for anything that wants to know what
	// it is looking at: 0 constant, 1 clock, 2 state.
	const slotClass = new Uint8Array(Math.max(1, nalg));
	algebraic.forEach((a, k) => {
		const [from, to] = spanOf(k);
		const cls = onState.has(a.name) ? 2 : (onClock.has(a.name) ? 1 : 0);
		const into = cls === 2 ? stepLines : (cls === 1 ? clockLines : onceLines);
		for (let i = from; i < to; i++) into.push(algLines[i]);
		slotClass.fill(cls, a.base, a.base + a.width);
	});
	let stillCount = 0;
	let clockCount = 0;
	for (let i = 0; i < nalg; i++) {
		if (slotClass[i] === 0) stillCount++;
		else if (slotClass[i] === 1) clockCount++;
	}
	const stillSlots = Uint8Array.from(slotClass, (c) => (c === 0 ? 1 : 0));

	// --- generate the derivative assembly ------------------------------------
	const dLines = [];
	dLines.push('\tout.fill(0);');

	// Which budget a term goes to. The family is the position in the material
	// list of the nuclide the loop is at; a loop over a sub-set of it goes
	// through a table (`BMAP<j>`, emitted at the top of the derivative once
	// every emission has said which lists it needs), and a loop with no
	// nuclide dimension is the un-indexed family. An endpoint without the
	// nuclide dimension is in that family too, whatever the loop is at: a
	// per-nuclide compartment draining into one that is not indexed moves
	// amounts *between* families, and the audit says so rather than lose them.
	const budgetMaps = [];
	const familyExpr = (dims, vars) => {
		const k = dims.findIndex(isNuclideDim);
		if (k < 0) return String(budgetLayout.nfam - 1);
		if (dims[k] === materialList) return vars[k];
		let j = budgetMaps.findIndex((m) => m.list === dims[k]);
		if (j < 0) {
			const rel = space.relate(materialList, dims[k]);
			j = budgetMaps.push({ list: dims[k], table: rel?.table ?? null }) - 1;
		}
		return `BMAP${j}[${vars[k]}]`;
	};
	const endpointFamily = (entry, loopDims, vars) => (entry.dims.some(isNuclideDim)
		? familyExpr(loopDims, vars) : String(budgetLayout.nfam - 1));
	const budgetAt = (term, familyText) => `${budgetLayout.base + BUDGET_TERMS.indexOf(term) * budgetLayout.nfam} + ${familyText}`;

	let fluxSeq = 0;
	for (const t of project.transfers) {
		const alg = algByName.get(t.qname ?? t.name);
		const src = t.from ? stateByName.get(t.from) : null;
		const tgt = t.to ? stateByName.get(t.to) : null;
		// A transfer may deliver into a far-field path instead: the flux
		// arrives in the first fracture cell, which is where the reference
		// implementation's input matrix B puts it.
		const path = t.to && !tgt ? pathByName.get(t.to) : null;

		dLines.push(`\t// transfer ${t.name}: ${t.from ?? '(outside)'} -> ${t.to ?? '(outside)'}`);
		if (t.multiply_by_donor && !src) {
			throw new BuildError(
				'A transfer with no source compartment cannot be multiplied by its ' +
				'donor; set "multiply_by_donor": false to give an absolute flux.', t.name,
			);
		}

		// How much of the donor's inventory is free to move. Null for almost
		// every transfer, which is the linear case this tool has always had.
		emitLoop(dLines, space, alg.dims, '\t', (vars, offExpr, indent) => {
			const f = `f${fluxSeq++}`;
			const rate = `X[${alg.base} + ${offExpr}]`;
			const resolveState = (entry) => stateOffsetExpr(
				space, alg.dims, vars, entry, t.name, mapIndex,
			);
			if (t.multiply_by_donor) {
				// The donor is read from the state vector; resolveState gives
				// an offset, not an access. A transfer with an availability has
				// it folded into its value already -- rate times availability,
				// worked out with the algebraic blocks -- so this line is the
				// same for every transfer. See `emitAvailability`.
				const held = `y[${resolveState(src)}]`;
				dLines.push(`${indent}const ${f} = ${held} * ${rate};`);
			} else {
				dLines.push(`${indent}const ${f} = ${rate};`);
			}
			if (src) dLines.push(`${indent}out[${resolveState(src)}] -= ${f};`);
			if (tgt) dLines.push(`${indent}out[${resolveState(tgt)}] += ${f};`);
			if (path) {
				const inlet = farfInletExpr(space, alg.dims, vars, path, t.name, mapIndex);
				dLines.push(`${indent}out[${inlet}] += ${f};`);
			}
			if (budgetLayout) {
				// A far-field path is outside the audited compartments: what
				// goes into one has left, and what comes back arrives as an
				// inflow from outside through the transfer that reads its release.
				const fS = src ? endpointFamily(src, alg.dims, vars) : null;
				const fT = tgt ? endpointFamily(tgt, alg.dims, vars) : null;
				if (src && !tgt) dLines.push(`${indent}out[${budgetAt('out', fS)}] += ${f};`);
				if (!src && tgt && !wasteByName.has(t.from)) dLines.push(`${indent}out[${budgetAt('in', fT)}] += ${f};`);
				if (src && tgt && fS !== fT) {
					dLines.push(`${indent}out[${budgetAt('between', fS)}] -= ${f};`);
					dLines.push(`${indent}out[${budgetAt('between', fT)}] += ${f};`);
				}
			}
		});
	}

	for (const s of project.inflows) {
		const alg = algByName.get(s.qname ?? s.name);
		const tgt = stateByName.get(s.to);
		const path = tgt ? null : pathByName.get(s.to);
		dLines.push(`\t// source ${s.name} -> ${s.to}`);
		emitLoop(dLines, space, alg.dims, '\t', (vars, offExpr, indent) => {
			const target = tgt
				? stateOffsetExpr(space, alg.dims, vars, tgt, s.name, mapIndex)
				: farfInletExpr(space, alg.dims, vars, path, s.name, mapIndex);
			dLines.push(`${indent}out[${target}] += X[${alg.base} + ${offExpr}];`);
			if (budgetLayout && tgt) {
				dLines.push(`${indent}out[${budgetAt('in', endpointFamily(tgt, alg.dims, vars))}] += X[${alg.base} + ${offExpr}];`);
			}
		});
	}

	// --- waste packages: failure, exposure and release ----------------------
	// `fail` is what the hazard takes out of the intact packages this instant;
	// `rel` is the block's release, already worked out in the algebraic pass
	// from the same numbers. What fails and is not released is exposed:
	// fail - rel = fail (1 - irf) - d M, which is the exposed inventory's whole
	// derivative bar decay. The release itself is delivered by the transfer
	// drawn out of the block, whose rate is the release slot -- or by nothing,
	// in which case it has left the model.
	for (const W of wasteLayout) {
		const { intact: P, exposed: M, hazardSlot, releaseSlot } = W;
		const carried = project.transfers.find((t) => t.from === W.q && t.to != null && stateByName.has(t.to));
		dLines.push(`\t// waste packages ${W.block.name}: failure, exposure and release`);
		emitLoop(dLines, space, P.dims, '\t', (vars, offExpr, indent) => {
			dLines.push(`${indent}{`);
			dLines.push(`${indent}\tconst fail = X[${hazardSlot.base}] * y[${P.base} + ${offExpr}];`);
			dLines.push(`${indent}\tconst rel = X[${releaseSlot.base} + ${offExpr}];`);
			dLines.push(`${indent}\tout[${P.base} + ${offExpr}] -= fail;`);
			dLines.push(`${indent}\tout[${M.base} + ${offExpr}] += fail - rel;`);
			// Into a compartment it is a move between audited inventories;
			// into a path or nowhere it has left them.
			if (budgetLayout && !carried) dLines.push(`${indent}\tout[${budgetAt('out', familyExpr(P.dims, vars))}] += rel;`);
			dLines.push(`${indent}}`);
		});
	}

	// --- disruptive events: the expected-value form --------------------------
	// The count grows at the expected-value rate, and a move at that rate is
	// a first-order transfer of the share. A fail is in the waste block's
	// hazard already. A realisation that samples the occurrences has the rate
	// switched off (`ctx.dis`), and everything below is then zero.
	const moveEnds = (D, a) => {
		const A = stateByName.get(a.from);
		if (!A) throw new BuildError(`'${a.from}' is not a compartment, so there is nothing to move out of it.`, D.q);
		const B = a.to ? stateByName.get(a.to) : null;
		if (a.to && !B) throw new BuildError(`'${a.to}' is not a compartment, so nothing can be moved into it.`, D.q);
		if (B && (B.width !== A.width || B.dims.join() !== A.dims.join())) {
			throw new BuildError(
				`'${a.from}' and '${a.to}' are indexed differently (${A.dims.join(' \u00d7 ') || 'by nothing'} `
				+ `against ${B.dims.join(' \u00d7 ') || 'by nothing'}). An event moves a share cell for cell, `
				+ 'so the two have to match.', D.q,
			);
		}
		return { A, B };
	};
	for (const D of disruptionLayout) {
		dLines.push(`\t// disruptive event ${D.block.name}: expected occurrences, and moves at that rate`);
		dLines.push(`\tout[${D.entry.base}] += X[${D.lambdaSlot.base}];`);
		D.actions.forEach((a, k) => {
			if (a.kind !== 'move') return;
			const { A, B } = moveEnds(D, a);
			emitLoop(dLines, space, A.dims, '\t', (vars, offExpr, indent) => {
				dLines.push(`${indent}{`);
				dLines.push(`${indent}\tconst m = X[${D.lambdaSlot.base}] * X[${D.shares[k].base}] * y[${A.base} + ${offExpr}];`);
				dLines.push(`${indent}\tout[${A.base} + ${offExpr}] -= m;`);
				if (B) dLines.push(`${indent}\tout[${B.base} + ${offExpr}] += m;`);
				else if (budgetLayout) dLines.push(`${indent}\tout[${budgetAt('out', familyExpr(A.dims, vars))}] += m;`);
				dLines.push(`${indent}}`);
			});
		});
	}

	// --- jumps ---------------------------------------------------------------
	// Packages that fail all at one time are a jump, not a rate: at the time
	// the block names, the intact inventory moves to the exposed waste form and
	// the instant-release part goes straight into wherever the release is
	// delivered. A disruptive event is the same shape: at its time -- or at
	// each occurrence a realisation drew -- a share of some packages fail, a
	// share of a compartment moves, and the count goes up by one. Generated
	// like the derivative, so the index machinery that finds a target's offset
	// is the same; applied by the runner at that corner, on the state, between
	// two segments of the integration.
	const jumps = [];
	// A jump's code may read the budget tables (`BMAP<j>`), which are spliced
	// into the derivative once every emission has said which lists it needs.
	// So a jump is compiled the first time it is applied, with the tables in
	// front of it, rather than at build time before the list is complete.
	const jumpFunction = (body) => {
		let fn = null;
		return (y) => {
			fn ??= new Function('y', 'X', [
				...budgetMaps.map((m, j) => `\tconst BMAP${j} = [${
					Array.from(m.table ?? [], (v) => (v < 0 ? budgetLayout.nfam - 1 : v)).join(', ')}];`),
				body,
			].join('\n'));
			fn(y, X);
		};
	};
	/** Lines failing `share` of the packages in `W`, `1` for all of them. */
	const failLines = (lines, W, share) => {
		const { intact: P, exposed: M } = W;
		const carrier = project.transfers.find((t) => t.from === W.q);
		const tgt = carrier?.to ? stateByName.get(carrier.to) : null;
		const path = carrier?.to && !tgt ? pathByName.get(carrier.to) : null;
		emitLoop(lines, space, P.dims, '\t', (vars, offExpr, indent) => {
			lines.push(`${indent}{`);
			lines.push(`${indent}\tconst fail = ${share} * y[${P.base} + ${offExpr}];`);
			lines.push(`${indent}\tconst irf = X[${W.setting.irf.base} + ${offExpr}];`);
			lines.push(`${indent}\ty[${P.base} + ${offExpr}] -= fail;`);
			lines.push(`${indent}\ty[${M.base} + ${offExpr}] += fail * (1 - irf);`);
			if (tgt) {
				lines.push(`${indent}\ty[${stateOffsetExpr(space, P.dims, vars, tgt, carrier.name, mapIndex)}] += fail * irf;`);
			} else if (path) {
				lines.push(`${indent}\ty[${farfInletExpr(space, P.dims, vars, path, carrier.name, mapIndex)}] += fail * irf;`);
			}
			if (budgetLayout && !tgt) lines.push(`${indent}\ty[${budgetAt('out', familyExpr(P.dims, vars))}] += fail * irf;`);
			lines.push(`${indent}}`);
		});
	};
	for (const W of wasteLayout) {
		if (W.failure !== 'at') continue;
		const lines = [];
		failLines(lines, W, '1');
		jumps.push({
			name: W.q, slot: W.setting.fail_at.base, text: String(W.block.fail_at ?? ''),
			apply: jumpFunction(lines.join('\n')),
		});
	}
	for (const D of disruptionLayout) {
		const lines = [`\ty[${D.entry.base}] += 1;`];
		D.actions.forEach((a, k) => {
			const share = `X[${D.shares[k].base}]`;
			if (a.kind === 'fail') {
				failLines(lines, wasteByName.get(a.block), share);
				return;
			}
			const { A, B } = moveEnds(D, a);
			emitLoop(lines, space, A.dims, '\t', (vars, offExpr, indent) => {
				lines.push(`${indent}{`);
				lines.push(`${indent}\tconst m = ${share} * y[${A.base} + ${offExpr}];`);
				lines.push(`${indent}\ty[${A.base} + ${offExpr}] -= m;`);
				if (B) lines.push(`${indent}\ty[${B.base} + ${offExpr}] += m;`);
				else if (budgetLayout) lines.push(`${indent}\ty[${budgetAt('out', familyExpr(A.dims, vars))}] += m;`);
				lines.push(`${indent}}`);
			});
		});
		const apply = jumpFunction(lines.join('\n'));
		if (D.timing === 'at') {
			jumps.push({ name: D.q, slot: D.setting.at.base, text: String(D.block.at ?? ''), apply });
		} else {
			// The occurrences a realisation drew, if it drew any: read when the
			// run starts, since they are set after the build.
			jumps.push({ name: D.q, slot: null, times: () => D.sampledTimes, apply });
		}
	}

	// --- explicit dy/dt terms ------------------------------------------------
	// `dydt + in - out`: the term goes into the compartment's own row, as the
	// first thing the standard differential-equation assembly adds. The slot
	// has the compartment's dimensions, so one offset serves both.
	for (const slot of dydtSlots) {
		const st = stateByName.get(slot.stateName);
		dLines.push(`\t// dy/dt term of ${inComment(st.name)}`);
		emitLoop(dLines, space, slot.dims, '\t', (vars, offExpr, indent) => {
			dLines.push(`${indent}out[${st.base} + ${offExpr}] += X[${slot.base} + ${offExpr}];`);
			if (budgetLayout) {
				dLines.push(`${indent}out[${budgetAt('explicit', endpointFamily(st, slot.dims, vars))}] += X[${slot.base} + ${offExpr}];`);
			}
		});
	}

	// --- running means -------------------------------------------------------
	// `dS/dt = target`, and nothing at all while the block is not recording,
	// which is what the standard running-mean derivative generates.
	for (const rec of recorders) {
		if (rec.kind !== 'running_mean') continue;
		dLines.push(`\t// running mean ${rec.name}`);
		const line = (off, indent) => dLines.push(
			`${indent}out[${rec.state.base} + ${off}] += `
			+ `MEM[${rec.mem} + ${off}].recording ? X[${rec.aux.target.base} + ${off}] : 0;`,
		);
		if (rec.width === 1 && !rec.dims.length) line('0', '\t');
		else emitLoop(dLines, space, rec.dims, '\t', (vars, offExpr, indent) => line(offExpr, indent));
	}

	// --- decay and ingrowth --------------------------------------------------
	// A compartment decays along whichever nuclide list it is indexed by, not
	// along one particular list. Real models keep two -- `Materials`, the
	// catalogue, and `Radionuclides`, the sub-set of it that decays -- and
	// index compartments by either; some index by both. Insisting on one made
	// every compartment indexed by the other silently skip decay, which is a
	// wrong answer that looks like a right one.
	//
	// So the decay tables are built per list, over that list's own indices.
	// A *mapped* list is not a nuclide dimension however related it is: the
	// element list shares its root with the nuclides and decays along nothing.
	const decayLists = [];
	const decayIndexOf = new Map();
	const decaySlot = (listName) => {
		if (!decayIndexOf.has(listName)) {
			decayIndexOf.set(listName, decayLists.length);
			decayLists.push(listName);
		}
		return decayIndexOf.get(listName);
	};

	const decaying = [];
	for (const s of stateLayout) {
		// A running mean's integral is not an inventory: it holds a sum of
		// whatever its target is, which does not decay however the block is
		// indexed.
		if (s.kind !== 'compartment' && s.kind !== 'waste_package') continue;
		if (s.block.handle_decay === false || !materialList) continue;
		const m = s.dims.findIndex(isNuclideDim);
		if (m < 0) continue;
		decaying.push({ ...s, m, slot: decaySlot(s.dims[m]) });
	}

	for (const s of decaying) {
		const strideM = space.strides(s.dims)[s.m];
		dLines.push(`\t// decay and ingrowth in ${s.name} along ${s.dims[s.m]}`);
		emitLoop(dLines, space, s.dims, '\t', (vars, offExpr, indent) => {
			const nm = vars[s.m];
			dLines.push(`${indent}{`);
			dLines.push(`${indent}\tconst si = ${s.base} + ${offExpr};`);
			dLines.push(`${indent}\tconst D = DEC[${s.slot}];`);
			dLines.push(`${indent}\tout[si] -= D.lam[${nm}] * y[si];`);
			if (budgetLayout) {
				dLines.push(`${indent}\tout[${budgetAt('decay', familyExpr(s.dims, vars))}] += D.lam[${nm}] * y[si];`);
			}
			dLines.push(`${indent}\tconst o = D.ioff[${nm}], c = D.icnt[${nm}];`);
			dLines.push(`${indent}\tfor (let q = 0; q < c; q++) {`);
			dLines.push(
				`${indent}\t\tout[si] += D.icoef[o + q] * ` +
				`y[si + (D.ipar[o + q] - ${nm}) * ${strideM}];`,
			);
			if (budgetLayout) {
				dLines.push(
					`${indent}\t\tout[${budgetAt('ingrowth', familyExpr(s.dims, vars))}] += D.icoef[o + q] * ` +
					`y[si + (D.ipar[o + q] - ${nm}) * ${strideM}];`,
				);
			}
			dLines.push(`${indent}\t}`);
			dLines.push(`${indent}}`);
		});
	}

	// --- far-field paths: transport and decay inside them ------------------
	// Emitted here rather than beside the transfers because it needs a decay
	// table, and which tables there are is only settled above. Order within
	// the derivative does not matter: every term accumulates into `out`.
	for (const p of farfLayout) {
		// `handle_decay: false` is the same switch a compartment has: no decay
		// table reaches the path and its cells only transport.
		// No nuclide dimension, no chain to run along: a path indexed by
		// nothing transports one quantity and neither decays nor grows in.
		p.decaySlot = p.block.handle_decay === false || !p.farf.listName
			? null
			: decaySlot(p.farf.listName);
		const dec = p.decaySlot == null ? 'null' : `DEC[${p.decaySlot}]`;
		dLines.push(`\t// far-field path ${p.name}: ${p.farf.structure.n_f} x `
			+ `${p.farf.structure.n_m} cells`
			+ `${p.farf.listName ? ` along ${p.farf.listName}` : ''}`
			+ `${p.decaySlot == null ? ', no decay' : ''}`);
		dLines.push(`\tFARF[${p.farfIndex}].apply(y, out, X, ${dec});`);
	}

	// --- decay tables --------------------------------------------------------
	const DEC = decayLists.map((listName) => decayTables(
		listName === materialList ? decay : project.decayModelFor(listName),
		space.size(listName),
	));

	// --- assemble -------------------------------------------------------------
	const ARGS = ['y', 'out', 'P', 'X', 'DEC', 'MAPS', 'TAB', 'MEM', 'FARF'];

	// The slots that never move are worked out once, below, and stay in `X`;
	// the derivative opens with the rest. See *which of those never change*.
	// The sub-set tables the budgets read through, after `out.fill(0)`.
	if (budgetLayout && budgetMaps.length) {
		dLines.splice(1, 0, ...budgetMaps.map((m, j) => `\tconst BMAP${j} = [${
			Array.from(m.table ?? [], (v) => (v < 0 ? budgetLayout.nfam - 1 : v)).join(', ')}];`));
	}

	const dydtSource = [
		'// --- algebraic blocks that move (dependency order) ---',
		...stepLines,
		'// --- derivative assembly ---',
		...dLines,
		'return out;',
	].join('\n');
	const algSource = [...stepLines, 'return X;'].join('\n');
	const onceSource = [
		'// --- algebraic blocks that never move, for the life of the run ---',
		...onceLines,
		'return X;',
	].join('\n');
	const clockSource = [
		'// --- algebraic blocks that move with the clock and nothing else ---',
		...clockLines,
		'return X;',
	].join('\n');

	const rawDydt = buildFunction(ARGS, dydtSource, 'dydt');
	const rawAlg = buildFunction(ARGS, algSource, 'algebraic');
	const rawOnce = buildFunction(ARGS, onceSource, 'invariant');
	const rawClock = buildFunction(ARGS, clockSource, 'atThisInstant');

	const X = new Float64Array(Math.max(1, nalg));
	const MAPS = maps;
	const ctx = {
		t: project.simulation.start_time,
		startTime: project.simulation.start_time,
		endTime: project.simulation.end_time,
		// Per disruptive event: 1 while its expected-value form is in force,
		// 0 for a realisation that has drawn its occurrences. See below.
		dis: new Float64Array(Math.max(1, disruptionLayout.length)).fill(1),
	};

	// The instant the clock-only slots in `X` were worked out for. NaN is never
	// equal to anything, so the first call always fills them.
	let clockAt = NaN;

	/**
	 * Working the clock-only algebra out on a coarser clock than the solver's.
	 *
	 * The clock pass is every rate, source and decay term that varies with time
	 * and nothing else, and it is worked out afresh at every step the solver
	 * takes. On a landscape model that is the largest single cost of a run --
	 * and on most of those models the rates change over centuries while the
	 * solver is stepping in years, so almost all of that work produces a number
	 * indistinguishable from the last one.
	 *
	 * `min_change_time` says how often they are *really* worth recomputing.
	 * Between two such instants the slots are linearly interpolated, which is
	 * second order in the interval and so a great deal safer than holding them
	 * flat: a rate that ramps would otherwise lag by half an interval
	 * throughout. AMBER calls the setting MinChangeTime and puts the rule the
	 * same way -- the rates are calculated every MinChangeTime or greater, and
	 * interpolated in between.
	 *
	 * **It is off unless a model asks for it**, and it is an approximation that
	 * the model has to choose knowingly: set larger than the time over which
	 * rates actually change, it will smooth away a change that mattered. The
	 * interval also never spans a declared switch time -- the runner re-anchors
	 * it at every restart -- because interpolating across a corner is precisely
	 * the mistake this is otherwise avoiding.
	 */
	const clockSlots = [];
	for (let i = 0; i < nalg; i++) if (slotClass[i] === 1) clockSlots.push(i);
	const clockIdx = Int32Array.from(clockSlots);
	const loX = new Float64Array(clockIdx.length);
	const hiX = new Float64Array(clockIdx.length);
	let minChange = 0;
	let origin = project.simulation.start_time;
	let loT = NaN;
	let hiT = NaN;

	/** Fills `into` with the clock-only slots as they are at `t`. */
	const clockInto = (t, y, into) => {
		ctx.t = t;
		rawClock(FUNCTIONS, ctx, y, scratchOut, P, X, DEC, MAPS, TAB, MEM, FARF);
		for (let i = 0; i < clockIdx.length; i++) into[i] = X[clockIdx[i]];
	};

	/**
	 * Turns the coarser clock on, from `from`.
	 *
	 * Called by the runner at the start of every segment, so an interval is
	 * measured from the last corner rather than from the start of the run and
	 * can never straddle one. `0` is off, which is what every model does unless
	 * it says otherwise.
	 */
	const useClockInterpolation = (interval, from) => {
		minChange = Number.isFinite(interval) && interval > 0 ? interval : 0;
		origin = Number.isFinite(from) ? from : project.simulation.start_time;
		loT = NaN;
		hiT = NaN;
		clockAt = NaN;
	};

	/** Brings the clock-only slots up to `t`, if they are not there already. */
	const atInstant = (t, y) => {
		if (t === clockAt) return;
		if (minChange > 0 && clockIdx.length) {
			const k = Math.floor((t - origin) / minChange);
			const a = origin + k * minChange;
			const b = a + minChange;
			// The two ends of the interval `t` falls in, each worked out once
			// however many steps land between them. A step that walks forward
			// by one interval keeps the old upper end as its new lower one.
			if (a !== loT) {
				if (a === hiT) { loX.set(hiX); } else { clockInto(a, y, loX); }
				loT = a;
			}
			if (b !== hiT) { clockInto(b, y, hiX); hiT = b; }
			const w = (t - a) / minChange;
			for (let i = 0; i < clockIdx.length; i++) {
				X[clockIdx[i]] = loX[i] + w * (hiX[i] - loX[i]);
			}
			ctx.t = t;
			clockAt = t;
			return;
		}
		ctx.t = t;
		rawClock(FUNCTIONS, ctx, y, scratchOut, P, X, DEC, MAPS, TAB, MEM, FARF);
		clockAt = t;
	};

	const dydt = (t, y, out) => {
		atInstant(t, y);
		ctx.t = t;
		return rawDydt(FUNCTIONS, ctx, y, out, P, X, DEC, MAPS, TAB, MEM, FARF);
	};

	const scratchOut = new Float64Array(nstate);
	// Handed to the invariant pass, which reads no state: it exists so that the
	// generated function can keep the one signature every other pass has.
	const primeY = new Float64Array(nstate);
	/**
	 * Works out the slots that never move, into `X`.
	 *
	 * Called once at the end of the build, which is the whole point of it, and
	 * exported so that anything changing a parameter can put `X` right again.
	 * It reads no state by construction, so the vector is a placeholder.
	 */
	/**
	 * The distributed points back into their tables.
	 *
	 * `makeTable` hands back the very array its reader closes over, so writing
	 * one number into `y` is the whole rebuild -- no table is made twice and
	 * nothing downstream has to be told. The x values never move: a point's
	 * *time* is a fact about the data, only its value is uncertain.
	 */
	const refreshTables = () => {
		for (const pt of pointLayout) {
			if (pt.tab < 0 || pt.row < 0) continue;
			const table = TAB[pt.tab];
			if (table?.y && pt.row < table.y.length) table.y[pt.row] = P[pt.slot];
		}
	};

	const evaluateInvariant = (t = project.simulation.start_time, y = primeY) => {
		// Before anything is worked out from them: a realisation writes `P`
		// and calls this, and a table read at the old value would be the last
		// realisation's curve under this one's parameters.
		refreshTables();
		ctx.t = t;
		rawOnce(FUNCTIONS, ctx, y, scratchOut, P, X, DEC, MAPS, TAB, MEM, FARF);
		// Whatever the clock-only slots were built on may have just moved under
		// them, so the next call works them out again.
		clockAt = NaN;
		return X;
	};

	const evaluateAlgebraic = (t, y) => {
		atInstant(t, y);
		ctx.t = t;
		rawAlg(FUNCTIONS, ctx, y, scratchOut, P, X, DEC, MAPS, TAB, MEM, FARF);
		return X;
	};

	// Once, here, so that `X` holds them before any caller can look. Nothing
	// after this writes them: `P` is fixed for the life of a build, `X` is
	// allocated once and never cleared, and an event acts on a history rather
	// than on a parameter.
	evaluateInvariant();

	// --- what the solver has to tell the recorders -------------------------
	const remembering = recorders.filter((r) => r.mem >= 0);

	/** Puts every history back to the start of a run. */
	const primeRecorders = (t0, y0) => {
		if (!remembering.length) return;
		// Cleared first, so the pass that works out the seeds reads an empty
		// history rather than the one left by the previous run.
		for (const r of MEM) r.prime(t0, 0);
		const values = evaluateAlgebraic(t0, y0);
		for (const rec of remembering) {
			// A snapshot starts at its own initial value; the others start at
			// their target, which is what `initBatch` seeds them with.
			const seed = rec.kind === 'snapshot' ? rec.aux.initial : rec.aux.target;
			for (let off = 0; off < rec.width; off++) {
				MEM[rec.mem + off].prime(t0, values[seed.base + off]);
			}
		}
	};

	/** Records a step the solver has accepted -- the accepted-step callback. */
	const storeStep = (t, y) => {
		if (!remembering.length) return;
		const values = evaluateAlgebraic(t, y);
		for (const rec of remembering) {
			// A delay reports its target's past, so that is what it keeps; the
			// others keep their own value, which is what makes their history
			// readable as their own past.
			const from = rec.kind === 'delay' ? rec.aux.target : rec.entry;
			for (let off = 0; off < rec.width; off++) {
				MEM[rec.mem + off].store(t, values[from.base + off]);
			}
		}
	};

	const events = eventSlots.length
		? {
			n: eventSlots.length,
			direction: eventDirection,
			slots: eventSlots,
			fun: (t, y, out) => {
				const values = evaluateAlgebraic(t, y);
				for (let i = 0; i < eventSlots.length; i++) out[i] = values[eventSlots[i].slot];
				return out;
			},
			fire: (which, t, y) => {
				const values = evaluateAlgebraic(t, y);
				for (const i of which) {
					for (const h of eventHandlers.get(i) ?? []) {
						// A running mean's integral travels in the state
						// vector, so a reset has to be told where it stood:
						// see `fire` in ./history.js.
						MEM[h.rec.mem + h.off].fire(
							h.action, t, values[h.rec.aux.target.base + h.off],
							h.rec.state ? y[h.rec.state.base + h.off] : 0,
						);
					}
				}
			},
		}
		: null;

	const initialState = buildInitialState(
		project, space, stateLayout, paramByName, nstate, P, ctx,
		{
			algebraic, algByName, stateByName, algLineRanges, algLines,
			X, MAPS, TAB, MEM, FARF, DEC, parseEquation,
		},
	);

	// df/dy, read off the equations rather than probed with finite
	// differences. Optional by construction: a model using a function with no
	// derivative rule declines it and the solvers fall back to differencing,
	// which is the path they took before this existed.
	// df/dy of nothing is nothing. Asked for anyway it produces a 0x0 matrix
	// and a NaN density, and the interface would report a Jacobian for a model
	// that is never differentiated.
	// Everything the generator reads, and nothing it does not: `stateLayout`,
	// `paramByName` and `materialList` were passed and never looked at, which
	// is the sort of thing that makes a bag of twenty-one fields hard to
	// reason about at all.
	const generatorInput = {
		project, space, algebraic, stateByName, algByName,
		makeLocator, makeCall, mapIndex, emitLoop, emitByEquation,
		stateOffsetExpr, tupleByList, nstate, nalg, nparam, decaying, recorders,
		farfLayout, pathByName, farfInletExpr, dydtSlots, wasteLayout, disruptionLayout,
		// What an availability's amount is made of, so that its tangent and
		// its columns come from the same list as its value.
		availabilityTerms, availabilitySum,
		// Where the run starts, for the probe that decides whether the
		// matrix is made of numbers there. See refuseNonFinite.
		initialState,
		runtime: {
			P, X, DEC, MAPS, TAB, MEM, FARF, ctx,
		},
	};

	const jacobian = !wantJacobian
		? { available: false, reason: 'not asked for' }
		: nstate === 0
		? { available: false, reason: 'the model has no compartments to differentiate' }
		: buildJacobian(generatorInput);

	/**
	 * `df/dp`, generated on demand.
	 *
	 * Nothing but a sensitivity run wants it, and it costs another pattern
	 * pass and another generated function of the model's whole size -- so it
	 * is built the first time it is asked for and kept, rather than paid for
	 * by every run. The column sets it needs are the Jacobian's own work, so
	 * a model that declined a Jacobian declines this too.
	 */
	let paramTangentCache = null;
	const paramTangent = () => {
		if (paramTangentCache) return paramTangentCache;
		paramTangentCache = jacobian.available
			? buildParamTangent(generatorInput)
			: { available: false, reason: `there is no analytic Jacobian: ${jacobian.reason}` };
		return paramTangentCache;
	};

	// The tangent shares `X` -- it works out each algebraic value and its
	// derivative together, and writes the value into the same slot the
	// derivative reads. So a Jacobian taken at one instant leaves the
	// clock-only slots holding *its* instant, and the cache below would
	// otherwise go on believing they hold the one it filled them for. Anything
	// that writes `X` behind the cache's back has to say so; this is the only
	// thing that does.
	if (jacobian?.available && typeof jacobian.evaluate === 'function') {
		const evaluate = jacobian.evaluate.bind(jacobian);
		jacobian.evaluate = (t, y, ...rest) => {
			const out = evaluate(t, y, ...rest);
			clockAt = NaN;
			return out;
		};
	}

	return {
		dydt,
		evaluateAlgebraic,
		initialState,
		jacobian,
		/**
		 * `df/dp` for the forward sensitivity equations, built on first ask.
		 *
		 * A function rather than a value so that an ordinary run never pays
		 * for it: see `paramTangent` above.
		 */
		paramTangent,
		// Waste packages that fail all at once, and disruptive events: the
		// state jumps at the time in `slot` -- or at each of `times()` -- and
		// the runner applies `apply` there. See the runner.
		jumps,
		/**
		 * Whether a disruptive event's occurrences are drawn for this run, and
		 * which they are. Sampled, its expected-value rate is switched off and
		 * the times become jumps; not sampled, the reverse.
		 */
		setDisruption: (index, { sampled, times = [] } = {}) => {
			const D = disruptionLayout[index];
			if (!D) return;
			ctx.dis[index] = sampled ? 0 : 1;
			D.sampledTimes = sampled ? [...times].sort((a, b) => a - b) : [];
		},
		/** One algebraic slot as it stands, for a time the runner needs as a number. */
		slotValue: (i) => X[i],
		/** The run's span, for a window that is blank at either end. */
		spanStart: () => ctx.startTime,
		spanEnd: () => ctx.endTime,
		// The blocks that depend on what has already happened, and the hooks
		// the runner gives the solver so that they can.
		recorders,
		memory: MEM,
		primeRecorders,
		storeStep: remembering.length ? storeStep : null,
		events,
		// Running the slots that never move again, which a caller that changes a
		// parameter has to do. It takes a clock and a state like every other
		// pass, and ignores both by construction -- which is exactly what
		// `test/run.js` checks, by handing it several of each.
		evaluateInvariant,
		useClockInterpolation,
		clockSlotCount: clockIdx.length,
		/** The clock-only slots, worked out for `t` if they are not already. */
		evaluateAtInstant: atInstant,
		layout: {
			nstate, nalg, nparam,
			// Per slot: 0 worked out once for the run, 1 once per instant,
			// 2 on every derivative call. See *which of those never change*.
			slotClass,
			// 1 where the slot is worked out once for the run, 0 otherwise --
			// kept as its own array because it is what the test reads.
			invariantSlots: stillSlots,
			ninvariant: stillCount,
			nclock: clockCount,
			states: stateLayout,
			meanStates,
			farfields: farfLayout,
			wastes: wasteLayout.map((W) => ({
				name: W.q, intact: W.intact.base, exposed: W.exposed.base, width: W.width,
				release: W.releaseSlot.base, failure: W.failure,
			})),
			budget: budgetLayout,
			// The points of a lookup table that carry their own distribution.
			// `../domain/sample.js` walks these beside `parameters`.
			lookupPoints: pointLayout.map((pt) => ({
				name: pt.name, index: pt.index, at: pt.at, slot: pt.slot, spec: pt.spec,
			})),
			events: disruptionLayout.map((D) => ({
				name: D.q, index: D.index, timing: D.timing, sampled: D.block.sampled !== false,
				state: D.entry.base,
				rateSlot: D.setting.rate?.base ?? null,
				fromSlot: D.setting.from?.base ?? null,
				untilSlot: D.setting.until?.base ?? null,
			})),
			algebraic,
			parameters: paramLayout,
			lookups: lookupLayout,
			indexSpace: space,
			materialList,
			nuclides: project.materialNames,
			hasNuclides: !!materialList,
			// What each material is measured in, for the series of a block that
			// states no unit of its own. `IndexSpace` keeps names and nothing
			// else, so the table is built here where the project is still in
			// reach. See units.materialUnit.
			materialUnits: new Map(project.materialNames.map(
				(n) => [n, materialUnit(project, n)],
			)),
		},
		decay,
		// The generated code, for the Model tab. Not an inflow: `source` here
		// is JavaScript source, which is why the rename of the block kind left
		// it alone.
		source: {
			dydt: rawDydt.source,
			// The whole algebraic pass, in the order the blocks are worked out,
			// which is what the generated-code tab is for and what this field
			// has always meant. The two halves it is compiled into are beside
			// it: `invariant` runs once at the end of the build, `moving` opens
			// every derivative call. See *which of those never change*.
			algebraic: algLines.join('\n'),
			invariant: rawOnce.source,
			atInstant: rawClock.source,
			moving: rawAlg.source,
			jacobian: jacobian.available ? jacobian.source : null,
		},
		parameterValues: P,
	};
}

/**
 * Which dimension of `target` each written index pins.
 *
 * Ecolego resolves the brackets **by name, not by position**
 * (index-name resolution): it walks the target's dimensions and gives
 * each one whichever of the written indices its own list contains. That is not
 * a detail -- a real model writes
 *
 *     Ecosystem_area_objects[11][Lake]
 *
 * for a block indexed by `Ecosystem x Objects`, so the brackets are in the
 * *other* order and Ecolego does not care. Reading them positionally would
 * look for a `11` among the ecosystems and fail, or worse, find one.
 *
 * Two deliberate refinements, in the cases where it is ambiguous
 * rather than merely unusual:
 *
 *   - a dimension prefers an index no other dimension has taken, so
 *     `M[A][B]` over two lists that both contain A and B reads as (A, B)
 *     rather than as (B, B), which is what a reverse scan gives;
 *   - an index that pins no dimension at all is an error, where the format
 * quietly keeps it as an `UnidentifiedIndex` and fails later somewhere
 *     less informative.
 *
 * One index may still pin several dimensions -- `M[Cs-137]` over a nuclide
 * list and a copy of it is the diagonal, which is what such a matrix is for.
 */
function pinIndices(space, target, indices, name, ownerName, context = null) {
	const fixed = {};
	// An empty bracket, `M[][Lake]`, pins nothing: it is how the format says
	// "take this dimension from the equation's own position".
	const written = (indices ?? []).filter((i) => i != null && i !== '');
	// `_source_` and `_target_` are the transfer's own ends. Translated here,
	// before anything matches them against a list, because no list holds them:
	// they are a way of naming a compartment, not an index.
	const given = written.map((i) => {
		if (i !== SOURCE_INDEX && i !== TARGET_INDEX) return i;
		const end = context?.[i];
		if (end) return end;
		const which = i === SOURCE_INDEX ? 'flows out of' : 'flows into';
		throw new BuildError(
			context?.[TRANSFER_LIST] != null
				? `'${name}[${i}]' asks for the compartment this transfer ${which}, `
					+ `and it has none: it ${i === SOURCE_INDEX ? 'comes from' : 'goes'} `
					+ `outside the model.`
				: `'${i}' means the compartment a transfer ${which}, so it can only be `
					+ `written in a transfer's own equation.`,
			ownerName,
		);
	});
	if (!given.length) return fixed;

	const asWritten = () => `${name}${(indices ?? []).map((i) => `[${i ?? ''}]`).join('')}`;
	if (given.length > target.dims.length) {
		throw new BuildError(
			`'${asWritten()}' pins ${given.length} `
			+ `${given.length === 1 ? 'index' : 'indices'}, but '${name}' is `
			+ `indexed by ${target.dims.length
				? `only ${target.dims.length} `
					+ `list${target.dims.length === 1 ? '' : 's'} (${target.dims.join(', ')})`
				: 'nothing, so it holds a single value'}.`, ownerName,
		);
	}

	// A name the list holds pins it. So does a compartment's or a transfer's
	// name written against a list *derived from* those -- `Kd[_source_]`
	// where Kd is per barrier compartment -- carried into the list the way the
	// block's own index is (see `derivedIndex`); what is pinned is then the
	// list's own index for it.
	const accepted = (dim, indexName) => {
		if (space.indexNames(dim).includes(indexName)) return indexName;
		return derivedIndex(space, dim, indexName) || null;
	};
	const accepts = (dim, indexName) => accepted(dim, indexName) != null;
	const claimed = new Set();
	for (const dim of target.dims) {
		// An unclaimed index first, in the order they were written; failing
		// that, one already used, which is the diagonal case above.
		let pick = given.findIndex((i, k) => !claimed.has(k) && accepts(dim, i));
		if (pick === -1) pick = given.findIndex((i) => accepts(dim, i));
		if (pick === -1) continue;
		fixed[dim] = accepted(dim, given[pick]);
		claimed.add(pick);
	}

	for (let k = 0; k < given.length; k++) {
		if (claimed.has(k)) continue;
		// Distinguish "no such index" from "disabled", which looks identical
		// from here but means something quite different -- and say it before
		// anything else, because it is the one with an obvious fix.
		const disabledIn = target.dims.filter((d) => space.get(d).indices
			.some((i) => i.name === given[k] && i.enabled === false));
		if (disabledIn.length) {
			throw new BuildError(
				`'${given[k]}' is disabled in '${disabledIn[0]}', so '${asWritten()}' `
				+ `has no value. Re-enable it, or change this equation.`, ownerName,
			);
		}
		// It may be a real index whose only dimension another bracket took --
		// a different mistake from a name that is nowhere.
		const owns = target.dims.filter((d) => accepts(d, given[k]));
		if (owns.length) {
			throw new BuildError(
				`'${asWritten()}' pins '${owns.join("' and '")}' twice: '${given[k]}' `
				+ `belongs to ${owns.length === 1 ? 'it' : 'them'}, and so does another `
				+ `index in the same reference.`, ownerName,
			);
		}
		throw new BuildError(
			`'${given[k]}' is not an index of any list that '${name}' is indexed by `
			+ `(${target.dims.join(', ') || 'none'})`, ownerName,
		);
	}
	return fixed;
}

/**
 * The decay model flattened into the arrays the generated code indexes.
 *
 * One entry per index of the list: its decay constant, and a run of
 * (parent, coefficient) pairs for the ingrowth term.
 */
function decayTables(model, size) {
	const n = Math.max(1, size);
	const ioff = new Int32Array(n);
	const icnt = new Int32Array(n);
	const ipar = [];
	const icoef = [];
	for (let k = 0; k < n; k++) {
		ioff[k] = ipar.length;
		const parents = model.parents[k] ?? [];
		for (const p of parents) {
			ipar.push(p.index);
			icoef.push(p.lambda * p.ratio);
		}
		icnt[k] = parents.length;
	}
	return {
		lam: Float64Array.from(model.lambdas.length ? model.lambdas : new Array(n).fill(0)),
		ioff,
		icnt,
		ipar: Int32Array.from(ipar),
		icoef: Float64Array.from(icoef),
	};
}

// --- code generation helpers ------------------------------------------------

/**
 * One body per *distinct equation*, rather than one per index tuple.
 *
 * A block whose indices all share one equation is emitted as a loop --
 * `entry.uniform`, and most blocks are. A block whose equations differ was
 * unrolled: one copy of the generated code per index tuple. That is where a
 * large model's generated code comes from, and where the analytic Jacobian is
 * lost: one assessment model has 2,938 algebraic entries, of which **thirty**
 * are non-uniform, and those thirty cover 82,124 of its 201,004 values. Its
 * tangent came to 587,780 lines against a ceiling of 300,000, so the model ran
 * on finite differences over a 16,244-square matrix.
 *
 * Those thirty are not arbitrary. `C_do_soil_objects` holds 686 values and
 * **fourteen** distinct equations -- one per landscape object, since each names
 * `Object_01`, `Object_02` and so on -- repeated for all 49 radionuclides. The
 * equation varies along one dimension and is identical along the other.
 *
 * So: find the dimensions the equation does *not* vary along, loop those, and
 * unroll only the rest. `C_do_soil_objects` becomes fourteen bodies each
 * looping 49 nuclides instead of 686 bodies. Across that model that is
 * 82,124 bodies down to 10,619.
 *
 * The offsets are what make this cheap rather than clever: the locator already
 * assembles an offset out of terms that are either fixed or driven by a loop
 * variable (see `space.projection` in `makeLocator`), so a pinned dimension is
 * a loop variable whose name happens to be a number. Nothing there changes.
 *
 * @param body called as `({ast, vars, tuple, slot, indent})`; exactly one of
 *   `vars` (looped) and `tuple` (unrolled) is set, and both are what
 *   `makeLocator(entry, entry.dims, vars, tuple)` wants.
 */
function emitByEquation(lines, space, entry, baseIndent, body) {
	const dims = entry.dims ?? [];
	const flat = flatDimensions(space, entry);
	if (flat.length) {
		// Straight into `lines`, and wound back to here if it does not work
		// out. The loop headers and the bodies are the same stream -- the
		// caller's own array, which is what its callback pushes to -- so they
		// cannot be built separately and joined afterwards.
		//
		// Why it might not work out: looping a dimension resolves references
		// through `space.projection`, which is more particular than reading
		// them off a known tuple, and a reference it cannot express as a
		// stride is an IndexError. Every uniform block in the corpus goes
		// through that same path, so this is insurance rather than an
		// expected case; when it fires, the block is unrolled exactly as it
		// was before.
		const mark = lines.length;
		try {
			emitGroups(lines, space, entry, new Set(flat), baseIndent, body);
			return;
		} catch (e) {
			if (!(e instanceof BuildError) && !(e instanceof IndexError)) throw e;
			lines.length = mark;
		}
	}
	for (let off = 0; off < entry.width; off++) {
		const tuple = tupleByList(space, dims, off);
		body({
			ast: entry.asts[off], vars: null, tuple,
			slot: String(entry.base + off), indent: baseIndent,
		});
	}
}

/**
 * The dimensions along which an entry's equation never changes.
 *
 * Compared by equation *text*, which is what `uniform` is already decided by
 * and what the parse cache is keyed on -- two tuples with the same text share
 * one tree, so equal text is identical tree.
 */
function flatDimensions(space, entry) {
	const dims = entry.dims ?? [];
	// One dimension that varies is the whole block; there is nothing to loop.
	if (dims.length < 2) return [];
	const equations = entry.equations ?? [];
	if (equations.length !== entry.width) return [];
	const strides = space.strides(dims);
	const sizes = dims.map((d) => space.size(d));
	const out = [];
	for (let i = 0; i < dims.length; i++) {
		let flat = true;
		for (let off = 0; off < entry.width && flat; off++) {
			const pos = Math.floor(off / strides[i]) % sizes[i];
			// Against the same tuple with this dimension at zero.
			if (pos !== 0 && equations[off] !== equations[off - pos * strides[i]]) flat = false;
		}
		if (flat) out.push(dims[i]);
	}
	return out;
}

/** One group per tuple of the varying dimensions, each looping the flat ones. */
function emitGroups(lines, space, entry, flatSet, baseIndent, body) {
	const dims = entry.dims;
	const strides = space.strides(dims);
	const sizes = dims.map((d) => space.size(d));
	const varying = dims.map((_, i) => i).filter((i) => !flatSet.has(dims[i]));
	const groups = varying.reduce((n, i) => n * sizes[i], 1);

	for (let g = 0; g < groups; g++) {
		// Where this group's varying dimensions are pinned.
		const at = new Array(dims.length).fill(0);
		let rest = g;
		for (let k = varying.length - 1; k >= 0; k--) {
			const i = varying[k];
			at[i] = rest % sizes[i];
			rest = Math.floor(rest / sizes[i]);
		}
		let base = entry.base;
		for (let i = 0; i < dims.length; i++) base += at[i] * strides[i];
		const ast = entry.asts[base - entry.base];

		// The loop variables, **by position in the entry's own dimensions**:
		// that is what `space.projection` reports a term as coming from, and
		// what the locator indexes with. A dimension being looped gets a
		// variable name; a pinned one gets its position, written as a number,
		// which the locator multiplies by a stride exactly as it would a
		// variable. That is the whole reason nothing there has to change.
		const vars = dims.map((_, i) => String(at[i]));

		let indent = baseIndent;
		const terms = [];
		let seq = 0;
		dims.forEach((d, i) => {
			if (!flatSet.has(d)) return;
			const v = `g${seq++}`;
			vars[i] = v;
			lines.push(`${indent}for (let ${v} = 0; ${v} < ${sizes[i]}; ${v}++) {`);
			indent += '\t';
			terms.push(strides[i] === 1 ? v : `${v} * ${strides[i]}`);
		});
		const looped = terms;
		body({
			ast, vars, tuple: null,
			slot: [base, ...terms].join(' + '), indent,
		});
		for (let k = looped.length - 1; k >= 0; k--) {
			indent = indent.slice(0, -1);
			lines.push(`${indent}}`);
		}
	}
}

/**
 * Emits nested loops over `dims`, calling `body(loopVars, offsetExpr, indent)`.
 * With no dimensions the body is emitted once at offset 0.
 *
 * **A dimension with nothing in it emits nothing.** A loop over an empty list
 * runs no iterations, so there is no code for it to be -- and generating the
 * body anyway is not merely wasteful: a block of width zero has no equations
 * parsed for it either, so `a.asts[0]` is undefined and the generator threw
 * `Cannot read properties of undefined` from inside itself. Four blocks of
 * model B are like this, indexed by waste-type lists that this
 * calculation case leaves empty, and none of them is read by anything.
 */
function emitLoop(lines, space, dims, baseIndent, body) {
	if (!dims.length) {
		body([], '0', baseIndent);
		return;
	}
	if (dims.some((d) => space.size(d) === 0)) return;
	const strides = space.strides(dims);
	const vars = dims.map((_, i) => `n${i}`);
	let indent = baseIndent;
	for (let i = 0; i < dims.length; i++) {
		lines.push(`${indent}for (let ${vars[i]} = 0; ${vars[i]} < ${space.size(dims[i])}; ${vars[i]}++) {`);
		indent += '\t';
	}
	const offExpr = vars
		.map((v, i) => (strides[i] === 1 ? v : `${v} * ${strides[i]}`))
		.join(' + ');
	body(vars, offExpr, indent);
	for (let i = dims.length - 1; i >= 0; i--) {
		indent = indent.slice(0, -1);
		lines.push(`${indent}}`);
	}
}

/** Offset expression for a state block read from inside `sourceDims`. */
/**
 * Where a flux delivered into a far-field path lands: cell 0 of the path, at
 * whichever nuclide and whichever of the block's other indices the flux
 * carries.
 *
 * `stateOffsetExpr` cannot do it, because a path's states are not laid out on
 * the index space's own strides: the cells come between the block's other
 * dimensions and its nuclide dimension. So the projection is reused -- the
 * hard part, which knows how to carry an index through a sub-set or a mapping
 * -- and only the strides are the path's own.
 */
function farfInletExpr(space, sourceDims, loopVars, entry, owner, mapIndex) {
	const { farf } = entry;
	let terms;
	try {
		terms = space.projection(sourceDims, entry.dims, {}, { owner, target: entry.name });
	} catch (e) {
		if (e instanceof IndexError) throw new BuildError(e.message, owner);
		throw e;
	}
	const stride = { [farf.listName]: 1 };
	const otherStrides = space.strides(farf.otherDims);
	farf.otherDims.forEach((d, i) => {
		stride[d] = otherStrides[i] * farf.ncells * farf.nnuc;
	});
	const parts = [];
	let constant = entry.base;
	for (const term of terms) {
		const st = stride[term.dim];
		if (term.fixed != null) { constant += term.fixed * st; continue; }
		const v = loopVars[term.from];
		const comp = term.table ? `MAPS[${mapIndex(term.table)}][${v}]` : v;
		parts.push(st === 1 ? comp : `${comp} * ${st}`);
	}
	return [constant, ...parts].join(' + ');
}

function stateOffsetExpr(space, sourceDims, loopVars, entry, owner, mapIndex) {
	if (!entry) return '0';
	if (!entry.dims.length) return String(entry.base);
	let terms;
	try {
		terms = space.projection(sourceDims, entry.dims, {}, { owner, target: entry.name });
	} catch (e) {
		if (e instanceof IndexError) throw new BuildError(e.message, owner);
		throw e;
	}
	const parts = [];
	let constant = entry.base;
	for (const term of terms) {
		if (term.fixed != null) { constant += term.fixed * term.stride; continue; }
		const v = loopVars[term.from];
		const comp = term.table ? `MAPS[${mapIndex(term.table)}][${v}]` : v;
		parts.push(term.stride === 1 ? comp : `${comp} * ${term.stride}`);
	}
	return [constant, ...parts].join(' + ');
}

/**
 * The index positions a block occupies simply by being what it is.
 *
 * A transfer *is* one of the transfers, so it is a position in the `Transfers`
 * list; a compartment is a position in `Compartments`. That is what makes a
 * per-transfer rate coefficient work: `k` indexed by `Transfers` and written
 * in the rate of `C1_to_C2` means `k[C1_to_C2]`, and nobody has to say so.
 *
 * A transfer also knows the two compartments it runs between, which is what
 * `_source_` and `_target_` reach.
 *
 * Anything else -- an expression, a recorder, a lookup table -- has no position
 * of its own in either list, and a reference from one has to pin the index the
 * ordinary way.
 */
function implicitIndices(owner) {
	if (!owner || typeof owner === 'string') return null;
	const block = owner.block;
	// A block the transport unrolling made answers as the block it was
	// copied from: the copies of a transfer between Begin and End are one
	// transfer in Ecolego's eyes (`currentTransferIndex` is the drawn one for
	// every pair, and `_source_`/`_target_` are Begin and End), and a slice
	// in the middle of the chain is Begin, whose initial condition it took.
	const alias = block?.alias ?? {};
	// An availability's limit and coefficients are equations of the transfer
	// they sit on, so they answer for its ends and its place in `Transfers`
	// exactly as its rate does.
	if (owner.kind === 'transfer' || String(owner.kind).startsWith('availability:')) {
		return {
			[TRANSFER_LIST]: alias.transfer ?? owner.transfer ?? owner.name,
			[SOURCE_INDEX]: alias.from ?? block?.from ?? null,
			[TARGET_INDEX]: alias.to ?? block?.to ?? null,
		};
	}
	// A compartment's dy/dt slot is the compartment, for this purpose: the
	// term is a statement about that compartment's row, and `_self_`-style
	// reads of a value held per compartment mean the one it belongs to.
	if (owner.kind === 'compartment' || owner.kind === 'compartment:dydt') {
		return { [COMPARTMENT_LIST]: alias.compartment ?? owner.stateName ?? owner.name };
	}
	return null;
}

/**
 * The index of `dim` that stands for `indexName` of the list `dim` is derived
 * from -- the same name in a sub-set, the index that maps onto it in a mapped
 * list. Null when `dim` is a root list or `indexName` is not one of its
 * root's; false when the root index has no counterpart in `dim`, which is
 * the answer "this block is not in that list".
 */
function derivedIndex(space, dim, indexName) {
	const list = space.get(dim);
	if (list.rootName === dim) return null;
	const root = space.get(list.rootName);
	const k = root.positionOf.get(indexName);
	if (k === undefined) return null;
	const rel = space.relate(dim, list.rootName);
	const pos = rel && rel.kind === 'map' ? rel.table[k] : k;
	if (pos == null || pos < 0) return false;
	return list.enabled[pos]?.name ?? false;
}

/**
 * { listName: indexName } for the tuple at `offset` of `dims`.
 *
 * Exported for the runner, which reads per-index properties that are not
 * equations -- a compartment's own absolute tolerance -- off the same offsets
 * this file lays the state vector out in.
 */
export function tupleByList(space, dims, offset) {
	const names = space.tupleAt(dims, offset);
	const out = {};
	dims.forEach((d, i) => { out[d] = names[i]; });
	return out;
}

/**
 * The enabled position of `dim` given a tuple, following sub-set and mapping
 * relations when the tuple names a related list instead.
 */
function positionIn(space, dim, tuple) {
	if (tuple[dim] != null) {
		const pos = space.get(dim).positionOf.get(tuple[dim]);
		if (pos !== undefined) return pos;
	}
	for (const [listName, indexName] of Object.entries(tuple)) {
		if (listName === dim) continue;
		const rel = space.relate(dim, listName);
		if (!rel) continue;
		if (rel.kind === 'same') {
			const pos = space.get(dim).positionOf.get(indexName);
			if (pos !== undefined) return pos;
		} else {
			const k = space.get(listName).positionOf.get(indexName);
			if (k === undefined) continue;
			const pos = rel.table[k];
			if (pos >= 0) return pos;
		}
	}
	return null;
}

/**
 * Safe to write into generated source as a comment.
 *
 * `Project` refuses a name with a line break in it, which is the real gate --
 * see `checkIndexName` there. This is the second lock on the same door: the
 * strings below end up in a `//` comment inside the derivative function, and a
 * newline there ends the comment and compiles whatever follows. One validator
 * that someone later relaxes should not be all that stands between a model
 * file and `new Function`.
 */
const inComment = (text) => String(text).replace(/[\r\n\u2028\u2029]+/g, ' ');

export const describeTuple = (tuple) => Object.entries(tuple)
	.map(([k, v]) => `${inComment(k)}=${inComment(v)}`).join(', ') || 'scalar';

/**
 * Topologically sorts algebraic blocks in place; throws on a cycle.
 *
 * A reference is resolved before it is followed: inside a sub-system, `Kd` and
 * the model's own `Kd` are different blocks, and ordering by the written name
 * would build the dependency graph of a model nobody wrote.
 */
/**
 * Bare references to the block's own name, if any -- the ones with no index.
 *
 * Walked as AST nodes rather than through `collectReferences`, which reports
 * names and loses the brackets that make the difference between a cycle and a
 * neighbour relation.
 */
function selfRefs(ast, a, algByName, out = []) {
	if (!ast || typeof ast !== 'object') return out;
	if (ast.type === 'ref') {
		if (!(ast.indices ?? []).length) {
			const q = resolveReference(ast.name, a.system ?? '', (n) => algByName.has(n));
			if (q === a.name) out.push(ast);
		}
		return out;
	}
	if (ast.type === 'unary') return selfRefs(ast.operand, a, algByName, out);
	if (ast.type === 'binary') {
		selfRefs(ast.left, a, algByName, out);
		return selfRefs(ast.right, a, algByName, out);
	}
	if (ast.type === 'cond') {
		selfRefs(ast.test, a, algByName, out);
		selfRefs(ast.then, a, algByName, out);
		return selfRefs(ast.otherwise, a, algByName, out);
	}
	if (ast.type === 'call') {
		for (const arg of ast.args ?? []) selfRefs(arg, a, algByName, out);
	}
	return out;
}

function orderAlgebraic(algebraic, algByName) {
	const deps = new Map();
	for (const a of algebraic) {
		const refs = new Set();
		for (const ast of a.asts) collectReferences(ast, refs);
		const resolved = new Set();
		for (const r of refs) {
			const q = resolveReference(r, a.system ?? '', (n) => algByName.has(n));
			if (q && q !== a.name) resolved.add(q);
		}
		// A block may read itself *at another index* -- `E[Cs-137]` inside E is
		// how a chain or a neighbour relation is written, and the fixed-point
		// pass in ../sim/jacobian.js exists for it. A **bare** self-reference
		// is a different thing: it reads its own slot, which has not been
		// written yet in this pass, so the value is whatever the previous
		// evaluation left there. `E = E + 1` built happily and counted the
		// solver's calls -- 14, 15, 16 -- a number that is not a function of
		// the state at all. It is the cycle the message below describes, one
		// step long.
		for (const ast of a.asts) {
			for (const r of selfRefs(ast, a, algByName)) {
				throw new BuildError(
					`'${a.local ?? a.name}' refers to itself. An equation cannot read `
					+ `its own value: there is nothing to read until it has been worked `
					+ `out.${a.dims.length
						? ` To read this block at another index, name that index -- `
							+ `'${a.local ?? a.name}[<index>]'.`
						: ''}`,
					a.name,
				);
			}
		}
		// A block that remembers is computed after the slots holding its
		// target and its parameters, which no equation of its own mentions.
		for (const n of a.needs ?? []) resolved.add(n);
		deps.set(a.name, [...resolved]);
		// Kept on the block: `buildInitialState` needs them to pull in
		// everything a value it reads is built from.
		a.readsAlg = [...resolved];
	}

	const state = new Map();
	const ordered = [];
	const stack = [];

	const visit = (name) => {
		const s = state.get(name) ?? 0;
		if (s === 2) return;
		if (s === 1) {
			const cycle = [...stack.slice(stack.indexOf(name)), name].join(' -> ');
			throw new BuildError(
				`Circular reference: ${cycle}. Expressions and transfer rates may not ` +
				`depend on themselves, directly or indirectly.`,
			);
		}
		state.set(name, 1);
		stack.push(name);
		for (const d of deps.get(name) ?? []) visit(d);
		stack.pop();
		state.set(name, 2);
		ordered.push(algByName.get(name));
	};

	for (const a of algebraic) visit(a.name);
	algebraic.length = 0;
	algebraic.push(...ordered);
}

/**
 * Which algebraic blocks hold the same value for the whole run.
 *
 * A compartment's initial condition is worked out before any state exists, so
 * it can only read what does not depend on the state -- which is why this used
 * to accept parameters and numbers and nothing else. That is narrower than it
 * needs to be, and narrower than the model: an initial inventory is very often
 * *derived* -- a concentration times a volume, an inventory per square metre
 * times an area -- and writing that as one expression and reading it here is
 * the natural way to say it. Ecolego puts no restriction on it at all: the
 * initial condition is compiled by the ordinary equation compiler, the same
 * one every other equation goes through.
 *
 * So the rule becomes the honest one. A block may be read by an initial
 * condition when its value cannot change over the run:
 *
 *   a parameter                  a number; always
 *   an expression, a reduction   when everything it reads is invariant too,
 *                                and it does not read the clock
 *   a compartment                never -- it *is* the state being initialised
 *   a lookup table               never -- it is read at the clock
 *   a far-field path             never -- its release comes out of the state
 *   a block that remembers       never -- a min, a mean, a delay and a
 *                                snapshot are all functions of history
 *
 * `algebraic` is already in dependency order by the time this runs, so one
 * forward pass settles it: everything a block depends on has been decided
 * before the block is reached.
 */
export function timeInvariantAlgebraic(algebraic, algByName, stateByName) {
	// A reduction of invariant blocks is invariant; the rest are not, and
	// `kind` is the whole of that question.
	const CAN = new Set(['expression', 'index_reduction', 'block_reduction']);
	// Walked as plain values rather than by node type: `time` is a call with no
	// arguments and can appear anywhere an expression can, including inside an
	// index, and a walk that knew the shapes would have to be right about all
	// of them to be safe. Missing one would call something invariant that is
	// not, which is a wrong initial inventory and no error at all.
	const readsClock = (node) => {
		if (Array.isArray(node)) return node.some(readsClock);
		if (!node || typeof node !== 'object') return false;
		if (node.type === 'call' && node.name === 'time') return true;
		return Object.values(node).some(readsClock);
	};

	const invariant = new Set();
	for (const a of algebraic) {
		if (!CAN.has(a.kind)) continue;
		if ((a.asts ?? []).some(readsClock)) continue;
		const refs = new Set();
		for (const ast of a.asts ?? []) collectReferences(ast, refs);
		// Anything a block that remembers watches is a dependency too, and
		// those blocks are never invariant -- but a reduction's target reaches
		// it the same way, so the same list is walked.
		for (const n of a.needs ?? []) refs.add(n);
		// The states are in here so that a reference to a compartment resolves
		// to the compartment. Without them a bare `Pool` would resolve to
		// nothing, and nothing is read below as "a parameter, which is a
		// number" -- so a block reading the state would be called invariant.
		const known = (n) => algByName.has(n) || stateByName.has(n);
		let ok = true;
		for (const r of refs) {
			const q = resolveReference(r, a.system ?? '', known);
			// A name that resolves to neither is a parameter, which is a number.
			if (q == null) continue;
			// Everything else has to be invariant itself -- and a compartment
			// never is, since only algebraic blocks are ever put in the set.
			// That is what keeps the state out, one step further back.
			if (q !== a.name && !invariant.has(q)) { ok = false; break; }
		}
		if (ok) invariant.add(a.name);
	}
	return invariant;
}

/**
 * Compiles the initial condition of every compartment.
 * Initial conditions may reference parameters and constants but not other
 * compartments, since no state exists yet when they are evaluated.
 */
function buildInitialState(
	project, space, stateLayout, paramByName, nstate, P, ctx,
	{ algebraic = [], algByName = new Map(), stateByName = new Map(), algLineRanges = new Map(),
		algLines = [], X = null, MAPS = [], TAB = [], MEM = [], FARF = [], DEC = [],
		// How an equation is read here, handed in so that an initial condition
		// may call a lookup table and a user-defined function exactly as every
		// other equation may. Built without it, `TR_adv(3)` in an initial
		// inventory was an unknown function in a model that ran.
		parseEquation = null } = {},
) {
	// Which blocks an initial condition may read besides the parameters, and
	// which of them it actually did: only those are worked out here, so a model
	// that uses none generates exactly the code it generated before.
	const invariant = timeInvariantAlgebraic(algebraic, algByName, stateByName);
	const used = new Set();
	// One entry per state slot, in slot order: `{ at, code }`. Collected
	// rather than written out, so that the runs of identical code -- which is
	// most of them, since a compartment usually has one initial inventory for
	// every index of it -- can be written as a loop instead of as one
	// statement each. Ten thousand states meant ten thousand statements, a
	// megabyte of source compiled by the browser for a calculation that runs
	// exactly once per simulation.
	const slots = [];

	for (const s of stateLayout) {
		// A far-field path starts empty. There is no way to write an initial
		// inventory for it -- it would need one value per cell per nuclide,
		// and a cell is numerics rather than a place in the model -- and the
		// reference implementation starts from zero too.
		if (s.kind === 'farfield') continue;
		// So does a budget: nothing has moved yet.
		if (s.kind === 'budget') continue;
		// Waste packages start intact: the inventory is inside them, and
		// nothing has been exposed.
		if (s.kind === 'waste_package' && s.role !== 'intact') continue;
		// An event has happened no times yet.
		if (s.kind === 'event') continue;
		const initialKey = s.kind === 'waste_package' ? 'inventory' : 'initial';
		for (let off = 0; off < s.width; off++) {
			const tuple = space.pinScenario(
				s.block.index_lists, tupleByList(space, s.dims, off),
			);
			const eq = String(valueAt(s.block, initialKey, tuple) ?? '0');

			const resolve = (name, indices) => {
				// Resolved in the compartment's own sub-system, like any other
				// reference. A parameter first, then a block whose value cannot
				// change over the run -- see `timeInvariantAlgebraic`.
				const reachable = (n) => paramByName.has(n) || invariant.has(n);
				const q = resolveReference(name, s.system ?? '', reachable);
				const pr = q ? paramByName.get(q) ?? algByName.get(q) : null;
				if (!pr) {
					throw new BuildError(whyNotInitial(name, s, algByName, stateByName), s.name);
				}
				// Read out of the algebraic slots, which the lines above have
				// filled by the time this runs.
				const store = paramByName.has(q) ? 'P' : 'X';
				if (store === 'X') used.add(q);
				if (!pr.dims.length) return `${store}[${pr.base}]`;
				// The same rule as everywhere else: each written index pins
				// whichever of the parameter's dimensions can take it -- and
				// the compartment being initialised is itself a position in
				// the `Compartments` list, so a parameter with a value per
				// compartment needs no index here. See implicitIndices.
				const here = { [COMPARTMENT_LIST]: s.name };
				const t = {
					...here,
					...tuple,
					...pinIndices(space, pr, indices, name, s.name, here),
				};
				const strides = space.strides(pr.dims);
				let o = 0;
				for (let i = 0; i < pr.dims.length; i++) {
					const pos = positionIn(space, pr.dims[i], t);
					if (pos == null) {
						throw new BuildError(
							pr.dims[i] === TRANSFER_LIST
								? `'${name}' has a value per transfer, and a compartment `
									+ `is not a transfer. Name one, as `
									+ `'${name}[<transfer>]'.`
								: `'${name}' is indexed by '${pr.dims[i]}', which the `
									+ `initial condition of '${s.name}' cannot resolve. `
									+ `Give an explicit index.`,
							s.name,
						);
					}
					o += pos * strides[i];
				}
				return `${store}[${pr.base + o}]`;
			};

			let code;
			try {
				code = emit(
					parseEquation ? parseEquation(eq, systemOf(s.block), s.name) : parse(eq),
					resolve,
				);
			} catch (e) {
				if (e instanceof ParseError) {
					throw new BuildError(
						`${e.message} in initial condition "${eq}"`, s.name,
					);
				}
				throw e;
			}
			slots.push({ at: s.base + off, code });
		}
	}

	const lines = [];
	for (let i = 0; i < slots.length;) {
		let j = i + 1;
		while (j < slots.length
			&& slots[j].code === slots[i].code
			&& slots[j].at === slots[j - 1].at + 1) j++;
		// Four is where a loop starts being shorter than the statements it
		// replaces; below that the statements read better in the Code tab.
		if (j - i >= 4) {
			lines.push(`\tfor (let i = ${slots[i].at}; i <= ${slots[j - 1].at}; i++) `
				+ `y0[i] = ${slots[i].code};`);
		} else {
			for (let k = i; k < j; k++) lines.push(`\ty0[${slots[k].at}] = ${slots[k].code};`);
		}
		i = j;
	}

	// The blocks the initial conditions read, worked out first and in the
	// order the algebraic pass settled -- which is dependency order, so a
	// block's own dependencies are filled before it is reached. Everything
	// they need has to come too, since one may be written in terms of another.
	const before = [];
	if (used.size) {
		const wanted = new Set(used);
		// Backwards, so that pulling in a dependency still reaches the blocks
		// *it* depends on before the pass moves past them.
		for (let i = algebraic.length - 1; i >= 0; i--) {
			const a = algebraic[i];
			if (!wanted.has(a.name)) continue;
			for (const d of a.readsAlg ?? []) wanted.add(d);
		}
		for (const a of algebraic) {
			if (!wanted.has(a.name)) continue;
			const range = algLineRanges.get(a.name);
			// One at a time: a per-entry block is one line per index tuple,
			// and spreading a block of 160,000 into `push` is past V8's
			// argument limit. See `expand` in runner.js for the same lesson.
			if (range) for (let i = range[0]; i < range[1]; i++) before.push(algLines[i]);
		}
	}

	const src = [
		...(before.length
			? ['\t// values the initial conditions read, which do not change over the run',
				...before, '']
			: []),
		'\ty0.fill(0);', ...lines, '\treturn y0;',
	].join('\n');
	// The same arguments the algebraic function takes, since the lines copied
	// in above are its lines. `TAB` most of all: an expression that calls a
	// lookup table at a fixed argument -- `Curve(2) * 3` -- is invariant and
	// so may be read by an initial condition, and its line reads `TAB`; built
	// without it, the first initial condition to do so failed with
	// `ReferenceError: TAB is not defined` from inside the generated code.
	const raw = buildFunction(['y0', 'P', 'X', 'MAPS', 'TAB', 'MEM', 'FARF', 'DEC'], src, 'initialState');

	return () => {
		const y0 = new Float64Array(nstate);
		ctx.t = project.simulation.start_time;
		return raw(FUNCTIONS, ctx, y0, P, X, MAPS, TAB, MEM, FARF, DEC);
	};
}

/**
 * Why a name cannot be read by an initial condition, in words.
 *
 * The old message said only that it was not a parameter, which is true of
 * every compartment in the model and says nothing about what to do. What a
 * reader needs is which of the reasons it is -- a state has no value yet, a
 * lookup is read at the clock -- because the way out differs.
 */
function whyNotInitial(name, s, algByName, stateByName) {
	const where = s.system ? ` in '${s.system}' or at the top level` : '';
	const q = resolveReference(name, s.system ?? '',
		(n) => algByName.has(n) || stateByName.has(n));
	if (q && stateByName.has(q)) {
		return `Initial condition cannot read '${name}': it is a compartment, and no `
			+ `compartment has a value until every initial condition has been worked `
			+ `out. Use a parameter or an expression that does not read the state.`;
	}
	const a = q ? algByName.get(q) : null;
	if (a) {
		return `Initial condition cannot read '${name}': its value changes over the `
			+ `run${a.kind === 'lookup' ? ', being read from a table at the clock'
				: a.kind === 'farfield' ? ', being the release out of a far-field path'
					: ''}. Only a parameter, or an expression made of parameters and `
			+ `numbers, holds the same value at every moment.`;
	}
	return `Initial condition may only use parameters, numbers and expressions that do `
		+ `not change over the run; '${name}' is not one of those${where}.`;
}
