/**
 * The matrix layers of every far-field path, as a run lays them out at its
 * first instant.
 *
 * For the Ecolego exporter, which writes a path out as the compartments of
 * its cells and the transfers between them (see ../io/ecoexport.js). The rates
 * go out as expressions of the path's own settings, so Ecolego works them out
 * as the run goes, as this tool does. The layers' thicknesses cannot: they come
 * out of a root-find over the settings (`layerDepths`, `matchedGrid` in
 * ../domain/farfield.js), which no Ecolego expression can do, so they go out as
 * the numbers a run here starts from, from the settings as the built model
 * evaluates them at the start. The matched layers are the run's to the last
 * bit: `FarfPath` lays them out here as it does when a run starts. The
 * reference layers are laid out by `referenceLayers`, which is `layerDepths`
 * with every power a running product -- the one thing the Python package
 * cannot reproduce is V8's `**`, and the export is the same file from both --
 * so they may differ from the run's in the last digit or two.
 *
 * A path worked out semi-analytically has no cells. Its equivalent on cells --
 * `cellEquivalent` -- is what the exporter writes for it, and its layers are
 * laid out here the same way, from its own settings.
 */

import { Project } from '../domain/project.js';
import { buildSystem } from './builder.js';
import { FarfPath } from './farfield.js';
import {
	CONTINUES, FARF_DEFAULTS, GRIDS, isSemiAnalytic, layerDepths, matchedGrid, structureProblem, wettedSurface, zeroin,
} from '../domain/farfield.js';

/**
 * The structure a path is written out on: its own, for a path on cells; for
 * one worked out semi-analytically, its cell settings with the outlet it
 * solves -- the rock going on past the release point -- or, where those do not
 * describe a path that can be built, the defaults.
 *
 * @returns {object} the block, with `n_f`, `n_m`, `o_b`, `n_b`, `grid` as the cells have them
 */
export function cellEquivalent(block) {
	if (!isSemiAnalytic(block)) return block;
	const cells = {
		...block,
		method: 'discretized',
		o_b: CONTINUES,
		n_b: '',
		grid: GRIDS.includes(block.grid) ? block.grid : FARF_DEFAULTS.grid,
	};
	if (structureProblem(cells)) {
		cells.n_f = FARF_DEFAULTS.n_f;
		cells.n_m = FARF_DEFAULTS.n_m;
	}
	return cells;
}

/**
 * Every path's layers, by its qualified name.
 *
 * @param {object} raw the model, as it is saved (it is not changed)
 * @returns {Map<string, {grid: string, otherDims: string[], combos: Array<{index: object,
 *   d: Float64Array, h: Float64Array|null}>}|{error: string}>} one layout per combination of
 *   the path's other dimensions -- everything it is indexed by but the radionuclides --
 *   keyed by index name; or why none could be had
 */
export function pathLayouts(raw) {
	const out = new Map();
	const paths = (raw?.farfields ?? []).filter((b) => b && typeof b === 'object');
	if (!paths.length) return out;
	const qname = (b) => (b.system ? `${b.system}.${b.name}` : String(b.name ?? ''));
	let sys;
	let X;
	try {
		// The same pass `valuesAtStart` makes (./atstart.js): the initial
		// state, the recorders primed, and the algebraic slots once.
		const project = new Project(structuredClone(raw));
		sys = buildSystem(project, { jacobian: false });
		const t0 = project.simulation.start_time;
		const y = sys.initialState();
		sys.primeRecorders?.(t0, y);
		X = sys.evaluateAlgebraic(t0, y);
	} catch (e) {
		const why = `the model does not build, so its layers cannot be laid out: ${e.message}`;
		for (const b of paths) out.set(qname(b), { error: why });
		return out;
	}
	const space = sys.layout.indexSpace;
	for (const p of sys.layout.farfields ?? []) {
		const F = sys.paths[p.farfIndex];
		const block = cellEquivalent(p.block);
		const nm = Number(block.n_m);
		const matched = block.grid === 'matched';
		const { otherDims, otherWidth } = p.farf;
		const names = otherDims.map((d) => space.indexNames(d));
		const strides = space.strides(otherDims);
		try {
			const combos = [];
			for (let o = 0; o < otherWidth; o++) {
				const index = {};
				otherDims.forEach((d, k) => { index[d] = names[k][Math.floor(o / strides[k]) % names[k].length]; });
				combos.push({ index, ...layersAt(F, X, o, nm, matched) });
			}
			out.set(p.name, { grid: matched ? 'matched' : 'reference', otherDims: [...otherDims], combos });
		} catch (e) {
			out.set(p.name, { error: e.message });
		}
	}
	return out;
}

/**
 * One combination's layers. On cells, the matched layers are laid out by the
 * path's own code, as `FarfPath` lays them out when a run starts; the reference
 * layers by `referenceLayers`, from the settings `coefficients` reads. A
 * semi-analytical path is read the same way from its settings, with the decay
 * constants it was handed.
 */
function layersAt(F, X, o, nm, matched) {
	if (F instanceof FarfPath) {
		if (matched) {
			const g = F._layOut(X, o);
			return { d: g.d, h: g.h };
		}
		const s = F._read(X, o, 0, {});
		return { d: referenceLayers(s.pen_dep, nm, wettedSurface(s), s.pen_dep_0), h: null };
	}
	const s = F.settingsOf(X, o);
	const first = s.pen_dep_0 > 0 ? s.pen_dep_0 : null;
	const aw = wettedSurface(s);
	if (!matched) return { d: referenceLayers(s.pen_dep, nm, aw, first), h: null };
	const lam = F.D?.lam ?? null;
	const nucs = s.de_m.map((de, m) => ({
		de, rm: s.eps_m[m] + s.rho_m * s.kd_m[m], lam: lam ? lam[m] ?? 0 : 0, rf: 1 + s.kd_f[m] * aw,
	}));
	const g = matchedGrid({ penDep: s.pen_dep, nm, first, aw, tw: s.tw, pe: s.pe, nucs });
	return { d: g.d, h: g.h };
}

/**
 * The reference layers, as `layerDepths` lays them out -- the same first
 * layer, the same root-find for the ratio -- with every power of the ratio a
 * running product: the arithmetic both this and the Python package do to the
 * last bit (see the note at the top).
 */
export function referenceLayers(penDep, nm, aw, first = null) {
	// What cannot be laid out is refused as the path itself refuses it.
	layerDepths(penDep, nm, aw, first);
	let d0 = first;
	if (d0 == null || !Number.isFinite(d0) || d0 <= 0) {
		const geo = (x) => {
			let s = 0;
			for (let k = 1; k <= nm; k++) s += x * Math.exp(k);
			return s - penDep;
		};
		d0 = zeroin(geo, 1e-12 / Math.E, 2 / aw / Math.E) * Math.E;
	}
	const total = (q) => {
		let s = 0;
		let t = d0;
		for (let j = 0; j < nm; j++) { s += t; t *= q; }
		return s - penDep;
	};
	let hi = 100;
	while (total(hi) < 0 && hi < 1e300) hi *= 100;
	const q = zeroin(total, 1, hi);
	const d = new Float64Array(nm);
	let t = d0;
	for (let j = 0; j < nm; j++) { d[j] = t; t *= q; }
	return d;
}
