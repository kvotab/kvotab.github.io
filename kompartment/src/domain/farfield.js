/**
 * The dual-porosity far-field: radionuclide transport along a fracture in
 * rock, with diffusion into the rock matrix beside it.
 *
 * PROVENANCE. The formulation is the one set out in Appendix B of *SKB
 * TR-19-06, Radionuclide transport and dose calculations for the safety
 * evaluation SE-SFL*, with Chapter 3 of TR-90-01 behind it. The variable names
 * below follow those reports, so that a result can be compared against them
 * term by term.
 *
 * THE CONCEPTUAL MODEL. Solute travels by advection along one discrete
 * migration path. Three things retain it:
 *
 *   - equilibrium sorption on the fracture coating,
 *   - diffusion into the stagnant pore water of the rock matrix,
 *   - equilibrium sorption on the matrix's own micro-surfaces.
 *
 * The matrix diffusion is one-dimensional and perpendicular to the flow path:
 *
 *      FRACTURE         ROCK MATRIX
 *      <2*TW/F>   <--------PENDEP-------->  (m)
 *   NF  |||||||| <-> | <-> ||| <-> ... <-> ||||||||
 *        ...
 *    2  |||||||| <-> | <-> ||| <-> ... <-> ||||||||
 *    1  |||||||| <-> | <-> ||| <-> ... <-> ||||||||
 *         (advection + dispersion along the fracture; diffusion sideways)
 *
 * so the discretisation is N_F fracture cells in series, each with its own
 * chain of N_M matrix layers behind it, and every one of those cells decays
 * and grows in along the model's own decay chain.
 *
 * WHAT MAKES IT WORTH A BLOCK OF ITS OWN rather than a few hundred hand-drawn
 * compartments: the equations are written in terms of the *water travel time*
 * TW and the *Peclet number* Pe instead of a pore velocity and a dispersion
 * coefficient -- effectively v = 1, z = TW, D = TW/Pe -- and the whole path is
 * then described by two numbers a hydrogeological model can supply, TW and the
 * flow-related transport resistance F, plus per-nuclide sorption and
 * diffusion data. Nothing about the cell count is a modelling choice: it is
 * numerics, and the block owns it.
 *
 * UNITS. Everything here is in the *model's own* time unit: TW in [time], F in
 * [time]*m2/m3, De in m2/[time], so every rate comes out in 1/[time] and the
 * decay constants the rest of this tool computes can be used unchanged. The
 * reference implementation is in years throughout.
 */

/**
 * A path whose geometry cannot be laid out.
 *
 * Raised rather than returned because the settings it complains about are
 * equations: most of the time they are constants and `geometryProblem` catches
 * the mistake before a run starts, but one that follows the clock or a
 * compartment can only be found when it is evaluated.
 */
export class FarfError extends Error {
	constructor(message) {
		super(message);
		this.name = 'FarfError';
	}
}

/**
 * How the downstream end of the path is closed. Ecolego's `OB` for 0 to 3;
 * 4 is this tool's own.
 *
 * 4 is the outlet the analytical far-field models have: the rock does not stop
 * where the release is measured, it goes on, and the concentration falls to
 * zero only infinitely far downstream (FARF31's stream tube, TR 90-01). What
 * leaves is the total flux, advection plus dispersion, across the plane at the
 * end of the path. A finite grid cannot hold an infinite rock, so it holds a
 * few cells of it past that plane -- `extraCells` says how many -- reads the
 * flux at the plane, and closes the last of the extra cells by linear
 * extrapolation. How few is a matter of how far upstream dispersion can
 * reach, which is what `autoExtraCells` works out.
 *
 * The four conditions of the reference implementation close the path at the
 * plane itself, and each is a different assumption about water nobody models:
 * 1, the default there, is a closed (Danckwerts) outlet, and it releases
 * 4a/(1+a)² of the semi-infinite rock's flux at a frequency where
 * a = sqrt(1 + 4·T_w·g/P_e) -- about 3 % short at the peak of the bundled
 * example, and far more for a nuclide the path holds back hard.
 */
export const OUTFLOWS = [0, 1, 2, 3, 4];

/** The outflow condition that is the semi-infinite rock. */
export const CONTINUES = 4;

/** The order the choice is offered in: the one new paths get first. */
export const OUTFLOW_ORDER = [4, 1, 0, 2, 3];

/** What each outflow boundary condition assumes about the water downstream. */
export const OUTFLOW_LABEL = {
	0: 'Infinite dilution (zero concentration downstream)',
	1: 'Same concentration as the last fracture cell',
	2: 'Linear extrapolation from the last two cells',
	3: 'Quadratic extrapolation from the last three cells',
	4: 'The rock goes on past the release point, as in FARF31',
};

/**
 * How the far-field block works the path out. Every setting that describes
 * the path or the chemistry is the method's input rather than the method's
 * own, so the two read the same block:
 *
 *   discretized      cells in the fracture and layers in the rock behind
 *                    them, solved with the rest of the model; the cells, the
 *                    layers and the outlet are its own settings;
 *   semi-analytical  the path solved exactly in the Laplace domain, as FARF31
 *                    solves it, and its unit responses convolved with the
 *                    inflow as the run goes (./farfield-laplace.js and
 *                    ../sim/farfield-laplace.js). No cells: one state per
 *                    nuclide for what the path holds. The rock goes on past
 *                    the release point, which is the outlet it solves; the
 *                    settings have to be constant through a run.
 *
 * `usesCells` is what anything outside this module asks.
 */
export const FARF_METHODS = ['discretized', 'semi-analytical'];

/** Each method, in words, for the choice. */
export const METHOD_LABEL = {
	discretized: 'On cells, with the rest of the model',
	'semi-analytical': 'Semi-analytically, from its transfer function',
};

/** Whether a path is worked out on cells, which is what gives it states. */
export function usesCells(block) {
	const m = block?.method;
	return m == null || m === '' || m === 'discretized';
}

/** Whether a path is worked out semi-analytically: no cells, a state per nuclide for what it holds. */
export function isSemiAnalytic(block) {
	return block?.method === 'semi-analytical';
}

/**
 * How the flow-wetted surface is given. All three say the same thing:
 *
 *   F    the flow-related transport resistance, in [time]·m²/m³ -- what a
 *        hydrogeological model supplies, with the travel time;
 *   a_w  the wetted surface per unit volume of flowing water, in m²/m³;
 *   δ    the fracture aperture, in m, for a fracture of two walls: a_w = 2/δ.
 *
 * and a_w = F/T_w links them. Whichever is given, the engines work out a_w
 * (and its tangent) from it, and F, which is what the reference
 * implementation reads, is a_w·T_w.
 */
export const SURFACES = ['f', 'aw', 'aperture'];

/** The setting each way of giving the surface is written in. */
export const SURFACE_KEY = { f: 'f', aw: 'aw', aperture: 'aperture' };

/** Each way, in words, for the choice. */
export const SURFACE_LABEL = {
	f: 'F, the flow-related transport resistance',
	aw: 'a_w, the wetted surface per volume of water',
	aperture: 'δ, the fracture aperture',
};

/**
 * How the rock matrix's layers are laid out.
 *
 *   matched    a geometric series whose first layer is worked out from the
 *              path's own time scales, with each node placed so that the
 *              layers' exchange with the fracture matches exact diffusion into
 *              the rock -- see `matchedGrid`;
 *   reference  the reference implementation's: ratio e from a first layer
 *              that makes it so, nodes at the layers' centres. Kept exactly,
 *              bit for bit, for the models built on it.
 */
export const GRIDS = ['matched', 'reference'];

/** Each layout, in words, for the choice. */
export const GRID_LABEL = {
	matched: 'Matched to diffusion into the rock',
	reference: 'As in SKB’s reference implementation',
};

/**
 * The settings that are a property of the *nuclide* rather than of the path,
 * and so may hold a value per nuclide.
 *
 * Chemistry, in other words: how strongly the element sorbs on the fracture
 * coating and in the matrix, how fast it diffuses through the pore water, and
 * -- because the transport porosity a nuclide sees depends on the size of its
 * species -- the porosity. The reference implementation's own documentation
 * says the same of it: *EPSM (0.0018) - Porosity of rock matrix (-),
 * optionally [#RN]*.
 */
/*
 * In the order the panel and the per-index grid show them, which is the order
 * they are read in: sorption on the coating, then the porosity the species
 * sees, then sorption in the matrix, then diffusion through it. Membership is
 * what the engine asks of this list -- `FARF_NUCLIDE_KEYS.includes(key)` is
 * how a setting is known to be per-nuclide -- so the order is the interface's
 * to choose.
 */
export const FARF_NUCLIDE_KEYS = ['kd_f', 'eps_m', 'kd_m', 'de_m'];

/**
 * The settings that describe the *path*, and so hold one value however many
 * nuclides travel along it: the travel time, the flow resistance, the rock's
 * density, the Peclet number and the depth the matrix is modelled to.
 *
 * They are still equations -- a travel time may follow a lookup table over a
 * glacial cycle, a resistance may be scaled by an expression -- and they are
 * still read at each derivative call. What they cannot do is differ from one
 * nuclide to the next: the water does not travel at one speed for caesium and
 * another for iodine.
 */
export const FARF_SINGLE_KEYS = ['tw', 'f', 'aw', 'aperture', 'rho_m', 'pe', 'pen_dep', 'pen_dep_0'];

/**
 * Every setting that is written as an equation, in the order the panel shows
 * them: what carries the nuclide, then what retains it, then the rock.
 *
 * All three ways of giving the flow-wetted surface are here, because each is
 * text the model keeps -- renamed with the blocks it names, listed where a
 * reference is looked for -- whichever of them is in use. Only the one in use
 * is worked out: see `activeEquationKeys`.
 */
export const FARF_EQUATION_KEYS = [
	'tw', 'f', 'aw', 'aperture', 'kd_f', 'kd_m', 'de_m', 'eps_m', 'rho_m', 'pe',
	'pen_dep', 'pen_dep_0',
];

/** How a path gives its flow-wetted surface: F unless it says otherwise. */
export function surfaceOf(block) {
	const s = block?.surface;
	return SURFACES.includes(s) ? s : 'f';
}

/**
 * The settings a path is worked out from: every equation but the two ways of
 * giving the surface it does not use. What the builder gives a slot, in the
 * order it gives them -- which, for a path that gives F, is the order it always
 * was, so the slots of a model built before the choice existed are where they
 * were.
 */
export function activeEquationKeys(block) {
	const used = SURFACE_KEY[surfaceOf(block)];
	return FARF_EQUATION_KEYS.filter(
		(k) => !(Object.values(SURFACE_KEY).includes(k) && k !== used),
	);
}

/** The structural settings: they decide how many states there are. */
export const FARF_STRUCTURE_KEYS = ['n_f', 'n_m', 'o_b', 'n_b'];

/** The settings that are a choice among words rather than a number. */
export const FARF_CHOICE_KEYS = ['surface', 'grid', 'method'];

/**
 * The short name each setting goes by in the literature, for a column header
 * or a label. SKB's own notation, which is what a report will be read against.
 *
 * Written in this tool's own symbol markup -- `<sub>` and nothing else -- so
 * that a subscript is a subscript: these are `T_w`, `K_{d,f}`, `ε_m` on paper,
 * and `TW`, `Kd,f`, `EPSM` was a transliteration that made the panel read like
 * a variable listing rather than like the model. Anywhere the label has to be
 * plain text -- a tooltip, a message, a CSV header -- `symbolText` takes the
 * markup off; see ./symbol.js, which the diagram and the block tree already
 * render block names through.
 */
export const FARF_LABEL = {
	tw: 'T<sub>w</sub>',
	f: 'F',
	aw: 'a<sub>w</sub>',
	aperture: 'δ',
	kd_f: 'K<sub>d,f</sub>',
	kd_m: 'K<sub>d,m</sub>',
	de_m: 'D<sub>e,m</sub>',
	eps_m: '\u03b5<sub>m</sub>',
	rho_m: '\u03c1<sub>m</sub>',
	pe: 'P<sub>e</sub>',
	// These three keep the reference implementation's own spelling: they are
	// not symbols in the literature, they are the names of its inputs.
	pen_dep: 'PENDEP', pen_dep_0: 'PENDEP0',
	n_f: 'NF', n_m: 'NM', o_b: 'OB', n_b: 'NB',
};

/**
 * What each numerical setting is, in words, for a label.
 *
 * The discretisation is not physics and its inputs are not symbols anybody
 * reads a report against: `PENDEP`, `NF`, `OB` are the names of the reference
 * implementation's own inputs, and a panel headed by them reads as a listing
 * of variables rather than as a set of choices. So the choice is the label and
 * the reference name goes on the field's tooltip, for anyone cross-checking
 * against the SKB reports.
 */
export const FARF_TERM = {
	pen_dep: 'Depth into the matrix modelled',
	pen_dep_0: 'First layer\u2019s thickness',
	n_f: 'Fracture cells',
	n_m: 'Matrix layers',
	n_b: 'Cells past the release point',
	o_b: 'Water downstream of the path',
	grid: 'Matrix layers laid out',
	surface: 'Flow-wetted surface given as',
	method: 'Worked out',
};

/**
 * One line each, for the panel and the documentation.
 *
 * Without the symbol in front of it: the label beside the field is the symbol,
 * and printing it again both wasted the line and disagreed with it once the
 * labels learned their subscripts -- a field headed T_w with `TW —` under it
 * reads as two different quantities.
 */
export const FARF_HELP = {
	tw: 'The water travel time along the path, in [time]',
	f: 'The flow-related transport resistance, in [time]·m²/m³',
	aw: 'The flow-wetted surface per unit volume of flowing water, in m²/m³',
	aperture: 'The fracture aperture, in m: two walls, so the wetted surface is 2/δ per m³ of water',
	kd_f: 'Sorption on the fracture coating, in m³/m² (0 for none)',
	kd_m: 'The partition coefficient in the rock matrix, in m³/kg',
	de_m: 'The effective diffusivity in the rock matrix, in m²/[time]',
	eps_m: 'The porosity of the rock matrix',
	rho_m: 'The dry bulk density of the rock matrix, in kg/m³',
	pe: 'The Peclet number; dispersion is the travel time over it',
	pen_dep: 'The greatest depth into the matrix that is modelled, in m',
	pen_dep_0: 'The first matrix layer’s thickness, in m; empty for automatic',
	n_f: 'How many cells the fracture is divided into',
	n_m: 'How many layers the rock matrix is divided into (at least 2)',
	o_b: 'What is assumed about the water downstream of the path',
	n_b: 'Extra fracture cells past the point the release is measured at',
	grid: 'How the matrix layers are laid out',
	surface: 'Which of F, the wetted surface or the aperture is given',
	method: 'On cells with the rest of the model, or exactly from the path’s transfer function',
	handle_decay: 'Adds −λC and ingrowth from parents in every cell of the path',
	report_cells: 'Reports the inventory of every cell, not only the total',
};

/**
 * What a new path starts with: the reference implementation's own numbers for
 * everything that has one -- 20 × 20 cells, Pe 10, a penetration depth of
 * 12.5 m, granite porosity and density -- and this tool's numerics for the
 * two things that are numerics rather than physics: an outlet where the rock
 * goes on past the release point, as the analytical models have it, and matrix
 * layers matched to diffusion into the rock. A model saved before those two
 * existed keeps what it had: see `FARF_LEGACY`.
 */
export const FARF_DEFAULTS = {
	method: 'discretized',
	tw: '100', surface: 'f', f: '1e5',
	kd_f: '0', kd_m: '0', de_m: '1e-4',
	eps_m: '0.0018', rho_m: '2700', pe: '10',
	pen_dep: '12.5', pen_dep_0: '',
	// Empty extra cells: as many as the outlet needs, worked out.
	n_f: 20, n_m: 20, o_b: CONTINUES, n_b: '', grid: 'matched',
	// The same switch a compartment has, and there for the same reason: to be
	// able to compare against a path that does not decay.
	handle_decay: true,
	// One series per cell is hundreds of series for one block, so they are
	// reported when they are asked for. What is always reported is the total
	// the path holds, which is the other half of a mass balance.
	report_cells: false,
};

/**
 * What a setting a saved path does not mention means.
 *
 * Every path written before the outlet and the layer choices existed says
 * nothing about either, and meant the reference implementation's: a closed
 * outlet unless it said otherwise, no extra cells, layers at ratio e, and F
 * given. Read that way it runs exactly as it did -- which is the point: a
 * validated model is not re-validated by opening it. `migrateFarfieldDefaults`
 * in ./keys.js writes these into the file's blocks on the way in, so that the
 * editor and everything after it sees one explicit model.
 */
export const FARF_LEGACY = { o_b: 1, n_b: 0, grid: 'reference', surface: 'f', method: 'discretized' };

/**
 * What a new setting's equation is when the path gives none: the same
 * geometry as the defaults, F = 1e5 over T_w = 100, said the other two ways.
 */
export const FARF_SURFACE_DEFAULTS = { f: '1e5', aw: '1000', aperture: '0.002' };

/**
 * Dekker's zeroin, 1969, in the form the reports use -- written so
 * that the layer thicknesses come out bit for bit the same. It converges to
 * the last representable step, so there is no tolerance to agree on.
 *
 * https://blogs.mathworks.com/cleve/2015/10/12/zeroin-part-1-dekkers-algorithm
 */
export function zeroin(fn, a, b) {
	let fa = fn(a);
	let fc = fa;
	let c = a;
	let fb;
	// A bracket that does not hold a root cannot be detected here -- the
	// reference does not check either -- but the loop is bounded so a
	// pathological input cannot hang the tab.
	for (let guard = 0; guard < 1000; guard++) {
		fb = fn(b);
		if (Math.sign(fb) === Math.sign(fc)) { c = a; fc = fa; }

		// Swap so that f(b) is the smallest value so far.
		if (Math.abs(fc) < Math.abs(fb)) {
			[a, b, c] = [b, c, b];
			[fa, fb, fc] = [fb, fc, fb];
		}

		const m = (b + c) / 2;
		if (Math.abs(m - b) <= spacing(Math.abs(b))) return b;

		// p/q is the secant step.
		let p = (b - a) * fb;
		let q = fa - fb;
		if (p < 0) { q = -q; p = -p; }

		a = b;
		fa = fb;

		if (p <= spacing(q)) b += Math.sign(c - b) * spacing(b);
		else if (p <= (m - b) * q) b += p / q;
		else b = m;
	}
	return b;
}

const SPACING_VIEW = new DataView(new ArrayBuffer(8));

/**
 * numpy's `spacing`: the distance from x to the next double away from zero,
 * signed like x. The convergence test above is written in it, so it has to
 * mean the same thing here.
 */
export function spacing(x) {
	const a = Math.abs(x);
	if (a === 0) return Number.MIN_VALUE;
	if (!Number.isFinite(a)) return NaN;
	SPACING_VIEW.setFloat64(0, a);
	let hi = SPACING_VIEW.getUint32(0);
	let lo = SPACING_VIEW.getUint32(4);
	lo = (lo + 1) >>> 0;
	if (lo === 0) hi = (hi + 1) >>> 0;
	SPACING_VIEW.setUint32(0, hi);
	SPACING_VIEW.setUint32(4, lo);
	const up = SPACING_VIEW.getFloat64(0) - a;
	return x < 0 ? -up : up;
}

/**
 * The rock matrix's layer thicknesses, in metres: `get_d`.
 *
 * A geometric series, because the concentration gradient is steepest at the
 * fracture wall and all but flat at depth: `d[j] = d0 * q^j`, with q chosen so
 * that the N_M layers add up to exactly the penetration depth.
 *
 * `first` is the first layer's thickness. Given, it is used and q follows from
 * it. Left out, the reference picks the thickness that makes the ratio come
 * out at e -- `sum(x*e^k) = pen_dep` for k = 1..N_M, which is linear in x and
 * so has one answer -- bracketed between a micrometre and the fracture's own
 * aperture, `2/aw`. A first layer thicker than the fracture it lines would be
 * geometry, not discretisation.
 *
 * @param {number} penDep total depth modelled (m)
 * @param {number} nm how many layers
 * @param {number} aw flow-wetted surface per unit volume of water (m2/m3)
 * @param {number|null} first the first layer's thickness (m), or null for auto
 * @returns {Float64Array} nm thicknesses, adding up to penDep
 */
export function layerDepths(penDep, nm, aw, first = null) {
	if (!(penDep > 0) || !Number.isFinite(penDep)) {
		throw new FarfError(`The penetration depth must be a positive length (got ${penDep})`);
	}
	if (!(aw > 0) || !Number.isFinite(aw)) {
		throw new FarfError(
			`F/TW must be positive: it is the flow-wetted surface per unit volume of `
			+ `water (got ${aw})`,
		);
	}
	let d0 = first;
	if (d0 == null || !Number.isFinite(d0) || d0 <= 0) {
		// sum over k = 1..nm of x*e^k, which is what the reference solves.
		const geo = (x) => {
			let s = 0;
			for (let k = 1; k <= nm; k++) s += x * Math.exp(k);
			return s - penDep;
		};
		const E = Math.E;
		d0 = zeroin(geo, 1e-12 / E, 2 / aw / E) * E;
	}
	// The layers grow with depth, so nm of them are at least nm times the
	// first: a first layer thicker than that cannot add up to the penetration
	// depth however the rest are chosen. The reference implementation brackets
	// its search in [1, 100] and so assumes this without checking; asking for
	// the impossible there returns a grid that quietly reaches deeper than the
	// depth it was given.
	if (d0 * nm > penDep * (1 + 1e-12)) {
		throw new FarfError(
			`${nm} matrix layers starting at ${d0} m cannot add up to a penetration `
			+ `depth of ${penDep} m: the layers grow with depth, so the first must be `
			+ `smaller than ${penDep / nm} m. Use a thinner first layer, fewer layers, `
			+ `a greater depth, or leave the first layer empty to have it worked out.`,
		);
	}

	// ...and the ratio that makes nm layers of that first thickness reach the
	// penetration depth.
	//
	// ONE DELIBERATE DIFFERENCE FROM THE REFERENCE. It brackets this search in
	// [1, 100], and a ratio above 100 is perfectly ordinary when there are few
	// layers: two layers starting at a millimetre reach 10 m at a ratio of
	// 9,999. Asked for that, the reference returns a grid whose layers add up
	// to 0.101 m rather than 10 -- a rock matrix a hundred times shallower
	// than the one it was given, with no complaint. So the upper bound is
	// found rather than assumed: doubled until the series overshoots, which is
	// where the root has to be.
	const total = (q) => {
		let s = 0;
		for (let j = 0; j < nm; j++) s += d0 * q ** j;
		return s - penDep;
	};
	let hi = 100;
	while (total(hi) < 0 && hi < 1e300) hi *= 100;
	const q = zeroin(total, 1, hi);
	const d = new Float64Array(nm);
	for (let j = 0; j < nm; j++) d[j] = d0 * q ** j;
	return d;
}

/**
 * The tangent of `layerDepths` with respect to its own inputs.
 *
 * Both thicknesses come out of a root-find, so the derivative comes out of the
 * implicit function theorem rather than of the expression:
 *
 *   auto d0:  sum(x*e^k) - penDep = 0  =>  dd0 = e * dpenDep / sum(e^k)
 *   q:        d0*sum(q^j) - penDep = 0  =>  dq = (dpenDep - sum(q^j)*dd0)
 *                                             / (d0 * sum(j*q^(j-1)))
 *
 * and then `d[j] = d0*q^j` differentiates termwise. Only reached when a
 * setting depends on the state -- a travel time that follows a compartment --
 * which is the one case where a Jacobian that ignored this would be wrong
 * rather than merely approximate.
 */
export function layerDepthsTangent(penDep, nm, aw, first, d, dPenDep, dAw, dFirst) {
	const d0 = d[0];
	const q = nm > 1 ? d[1] / d[0] : 1;
	let dd0;
	if (first == null || !Number.isFinite(first) || first <= 0) {
		// The bracket only binds in the degenerate case of a fracture narrower
		// than the layer the depth asks for; there `d0 = 2/aw` and the
		// automatic value is not what came out.
		const bracket = 2 / aw;
		if (d0 >= bracket * (1 - 1e-12)) {
			dd0 = (-2 / (aw * aw)) * dAw;
		} else {
			let s = 0;
			for (let k = 1; k <= nm; k++) s += Math.exp(k);
			dd0 = (Math.E / s) * dPenDep;
		}
	} else {
		dd0 = dFirst;
	}
	let sum = 0;
	let dsum = 0;
	for (let j = 0; j < nm; j++) {
		sum += q ** j;
		if (j > 0) dsum += j * q ** (j - 1);
	}
	const dq = dsum === 0 ? 0 : (dPenDep - sum * dd0) / (d0 * dsum);
	const out = new Float64Array(nm);
	for (let j = 0; j < nm; j++) {
		out[j] = dd0 * q ** j + (j > 0 ? d0 * j * q ** (j - 1) * dq : 0);
	}
	return out;
}

/*
 * THE MATCHED LAYERS.
 *
 * What the matrix does to the fracture is a boundary flux: the rock takes up
 * Y(s)·c per unit wall area at frequency s, with
 *
 *     Y(s) = sqrt(D_e R_m s) · tanh(x0 · sqrt(R_m s / D_e)),     R_m = ε + ρ K_d
 *
 * (s + λ for a nuclide that decays), and that admittance is all the fracture
 * ever sees of it. The layers are a ladder of capacities R_m·d_j joined by
 * conductances D_e/h_j, and their admittance is a continued fraction in s. How
 * well the two agree over the frequencies a release is made of is the whole
 * accuracy of the matrix, and it was measured before anything here was chosen:
 *
 *   - Nodes at the layers' centres, h_j = (d_(j-1) + d_j)/2, under-state Y by
 *     a constant fraction on a geometric grid: 0.4 % at a ratio of 1.3, 1 % at
 *     1.5, 5.8 % at e. The reference implementation's automatic grid grows by
 *     e, so its matrix takes up 5.8 % too little, and an error in the exponent
 *     is multiplied by the exponent: the bundled example's peaks came out
 *     6-10 % high, and its rising edge twice as high at a hundredth of the
 *     peak.
 *   - Nodes spaced by the geometric mean of the two layers they join,
 *     h_j = sqrt(d_(j-1)·d_j), and the first at d_0/(1 + sqrt q) from the
 *     wall, remove that bias outright -- the node position that zeroes it is
 *     1/(1 + sqrt q) of the way into each layer, to every digit measured --
 *     and what is left is a ripple, 1e-7 at a ratio of 1.35 and 1e-5 at 1.5
 *     on the imaginary axis. This is the interlacing Ingerman, Druskin and
 *     Knizhnerman's optimal grids have (CPAM 53, 2000): primal and dual steps
 *     that approximate sqrt(s) spectrally rather than to second order.
 *
 * That leaves where the ladder starts and where it ends. It ends at the depth
 * modelled, with the whole capacity in it, so the lowest frequencies are exact
 * whatever the steps. It has to start thin enough to resolve the fastest
 * frequency that still matters: `penetrationScale` below.
 */

/**
 * How far down the path's transfer function may fall before a frequency stops
 * mattering: e^-25, about 1.4e-11 of what went in.
 */
const ATTENUATION = 25;

/**
 * How many times thinner the first layer is than the shallowest depth the
 * diffusion reaches at that frequency. The layers' admittance falls away from
 * exact as 0.1·(d_0/L)² where the ladder begins, so 10 keeps it within 1e-3
 * at the fastest frequency that matters and far closer below it.
 */
const RESOLVE = 10;

/**
 * The depth diffusion reaches into the rock at the fastest frequency the path
 * lets through, for one nuclide, in m.
 *
 * With u = sqrt(s + λ) the fracture sees g = R_f·u² + a_w·sqrt(D_e R_m)·u (the
 * matrix as a half-space, which it is at those frequencies), and the path's
 * transfer function is exp((P_e/2)(1 - sqrt(1 + 4 T_w g/P_e))). It is down to
 * e^-A where T_w·g = A(1 + A/P_e); the positive root of that quadratic in u
 * is the fastest frequency, and the depth is sqrt(D_e/(R_m u²)). A nuclide
 * whose own decay is faster than that is resolved at its decay constant
 * instead: however strongly the path holds it back, it grows in along the way
 * and its daughters see its profile.
 *
 * Nothing but square roots and the four operations, so the application and the
 * Python engine agree on it to the last bit.
 *
 * @returns {number} the depth, or Infinity for a nuclide that does not enter
 *   the rock (no diffusion, no capacity, no wetted surface)
 */
export function penetrationScale({ de, rm, lam = 0, rf = 1 }, { aw, tw, pe }) {
	if (!(de > 0) || !(rm > 0) || !(aw > 0) || !Number.isFinite(aw)) return Infinity;
	if (!(tw > 0) || !(pe > 0)) return Infinity;
	const G = (ATTENUATION * (1 + ATTENUATION / pe)) / tw;
	const A = aw * Math.sqrt(de * rm);
	// The positive root of rf·u² + A·u - G = 0, in the form that does not
	// cancel when A dominates.
	const u = (2 * G) / (A + Math.sqrt(A * A + 4 * rf * G));
	const u2 = Math.max(u * u, Number.isFinite(lam) && lam > 0 ? lam : 0);
	if (!(u2 > 0) || !Number.isFinite(u2)) return Infinity;
	return Math.sqrt(de / rm / u2);
}

/**
 * The matched layers' first thickness, worked out: the shallowest of every
 * nuclide's `penetrationScale`, divided by `RESOLVE` -- one grid for all of
 * them, because a daughter grows in cell by cell from its parent and the two
 * have to share the cells -- and never thicker than an even split of the
 * depth, which is where the series stops growing at all.
 *
 * @param {object} p
 * @param {number} p.penDep the depth modelled (m)
 * @param {number} p.nm how many layers
 * @param {number} p.aw the flow-wetted surface per unit volume of water
 * @param {number} p.tw the water travel time
 * @param {number} p.pe the Peclet number
 * @param {Array<{de:number, rm:number, lam?:number, rf?:number}>} p.nucs every
 *   nuclide travelling the path, with its decay constant and its retardation
 *   in the fracture
 */
export function autoFirstLayer({ penDep, nm, aw, tw, pe, nucs }) {
	let L = Infinity;
	for (const n of nucs ?? []) {
		const l = penetrationScale(n, { aw, tw, pe });
		if (l < L) L = l;
	}
	const even = penDep / nm;
	if (!(L < Infinity)) return even;
	const d0 = L / RESOLVE;
	return d0 < even ? d0 : even;
}

/**
 * The matched layers: a geometric series from the first thickness to exactly
 * the depth modelled, and the node spacings that make its exchange with the
 * fracture match diffusion into the rock (see THE MATCHED LAYERS above).
 *
 * The first thickness is given, or worked out by `autoFirstLayer`. The ratio
 * comes from the same root-finder the reference layers use, over a sum built
 * by repeated multiplication rather than by powers -- so that both engines
 * reach the same double.
 *
 * @returns {{kind: 'matched', d: Float64Array, h: Float64Array, q: number}}
 *   d the thicknesses, h[0] the wall to the first node and h[j] node j-1 to
 *   node j, q the ratio
 */
export function matchedGrid({ penDep, nm, first = null, aw, tw, pe, nucs = [] }) {
	if (!(penDep > 0) || !Number.isFinite(penDep)) {
		throw new FarfError(`The penetration depth must be a positive length (got ${penDep})`);
	}
	let d0 = first;
	if (d0 == null || !Number.isFinite(d0) || d0 <= 0) {
		d0 = autoFirstLayer({ penDep, nm, aw, tw, pe, nucs });
	}
	if (d0 * nm > penDep * (1 + 1e-12)) {
		throw new FarfError(
			`${nm} matrix layers starting at ${d0} m cannot add up to a penetration `
			+ `depth of ${penDep} m: the layers grow with depth, so the first must be `
			+ `smaller than ${penDep / nm} m. Use a thinner first layer, fewer layers, `
			+ `a greater depth, or leave the first layer empty to have it worked out.`,
		);
	}
	const d = new Float64Array(nm);
	const h = new Float64Array(nm);
	let q = 1;
	if (nm === 1 || d0 * nm >= penDep * (1 - 1e-12)) {
		// An even split: the series has nothing left to grow into.
		d.fill(penDep / nm);
	} else {
		const total = (r) => {
			let s = 0;
			let t = d0;
			for (let j = 0; j < nm; j++) { s += t; t *= r; }
			return s - penDep;
		};
		let hi = 2;
		while (total(hi) < 0 && hi < 1e300) hi *= 2;
		q = zeroin(total, 1, hi);
		d[0] = d0;
		for (let j = 1; j < nm; j++) d[j] = d[j - 1] * q;
	}
	h[0] = d[0] / (1 + Math.sqrt(q));
	for (let j = 1; j < nm; j++) h[j] = Math.sqrt(d[j - 1] * d[j]);
	return { kind: 'matched', d, h, q };
}

/**
 * The flow-wetted surface per unit volume of water, from whichever way the
 * path gives it: F/T_w, a_w itself, or 2/δ for an aperture δ.
 */
export function wettedSurface(s) {
	const how = SURFACES.includes(s.surface) ? s.surface : 'f';
	if (how === 'aw') return s.aw;
	if (how === 'aperture') return 2 / s.aperture;
	return s.f / s.tw;
}

/** The tangent of `wettedSurface`, given the tangent of each setting. */
export function wettedSurfaceTangent(s, ds) {
	const how = SURFACES.includes(s.surface) ? s.surface : 'f';
	if (how === 'aw') return ds.aw ?? 0;
	if (how === 'aperture') return (-2 * (ds.aperture ?? 0)) / (s.aperture * s.aperture);
	return (ds.f * s.tw - s.f * ds.tw) / (s.tw * s.tw);
}

/** Why a wetted surface cannot be used, said in the terms it was given in. */
function surfaceProblem(s, aw) {
	if (aw > 0 && Number.isFinite(aw)) return null;
	const how = SURFACES.includes(s.surface) ? s.surface : 'f';
	if (how === 'aw') {
		return `The flow-wetted surface a_w must be positive: it is the wetted `
			+ `surface per unit volume of water (got ${aw})`;
	}
	if (how === 'aperture') {
		return `The fracture aperture must be a positive length: the wetted surface `
			+ `is 2/δ per unit volume of water (got δ = ${s.aperture})`;
	}
	return `F/TW must be positive: it is the flow-wetted surface per unit volume of `
		+ `water (got ${aw})`;
}

/**
 * One path's rates, for one nuclide: everything `get_jac_rn` is written in.
 *
 * `aw = F/TW` is the flow-wetted surface per unit volume of water, which is
 * what turns a resistance into a geometry; `f_df` is the fraction of the
 * nuclide that is dissolved rather than sorbed on the fracture coating, and it
 * retards advection, dispersion and the diffusive exchange alike.
 *
 * The dispersion rate is `adv_f*(N_F/Pe - 1/2)`, floored at zero: a chain of
 * N_F cells already disperses as if Pe were 2*N_F, so a coarser
 * discretisation than the Peclet number asks for gets no explicit dispersion
 * on top -- it is already there, numerically. Above the floor that makes the
 * fracture a central scheme, second order in the cell length, whose first two
 * moments -- the mean travel time and the spread -- are exactly the continuous
 * path's.
 *
 * `grid` is the matrix layout every nuclide of the path shares (see
 * `pathGrid`). Left out, the reference layers are worked out from `s` itself,
 * as they always were -- they depend on the path's settings alone -- or, for
 * `s.grid === 'matched'`, a matched layout for this one nuclide.
 */
export function coefficients(s, grid = null) {
	const { nf, nm } = s;
	if (!(s.pe > 0) || !Number.isFinite(s.pe)) {
		throw new FarfError(
			`The Peclet number must be greater than zero: the dispersion is TW/Pe `
			+ `(got ${s.pe})`,
		);
	}
	const aw = wettedSurface(s);
	const bad = surfaceProblem(s, aw);
	if (bad) throw new FarfError(bad);
	if (!(s.tw > 0) || !Number.isFinite(s.tw)) {
		throw new FarfError(`The travel time T_w must be positive (got ${s.tw})`);
	}
	const rM = s.eps_m + s.rho_m * s.kd_m;
	if (!(rM > 0) || !Number.isFinite(rM)) {
		// eps + rho*Kd is the matrix's capacity for the nuclide, and it divides
		// every diffusion rate. Zero porosity with no sorption is a rock the
		// nuclide cannot enter at all, which this discretisation cannot
		// express -- and left alone it put Infinity in the rates and the
		// solver reported "unable to meet integration tolerances", which says
		// nothing about the porosity.
		throw new FarfError(
			`The matrix capacity eps + rho*Kd must be greater than zero (got `
			+ `${s.eps_m} + ${s.rho_m}*${s.kd_m} = ${rM}). A rock with no porosity `
			+ `and no sorption has nothing for the nuclide to diffuse into.`,
		);
	}
	const fDf = 1 / (1 + s.kd_f * aw);
	const advF = (fDf * nf) / s.tw;
	const dF = Math.max(0, advF * (nf / s.pe - 0.5));
	const g = grid ?? (s.grid === 'matched'
		? matchedGrid({
			penDep: s.pen_dep, nm, first: s.pen_dep_0, aw, tw: s.tw, pe: s.pe,
			nucs: [{ de: s.de_m, rm: rM, lam: s.lam ?? 0, rf: 1 + s.kd_f * aw }],
		})
		: { kind: 'reference', d: layerDepths(s.pen_dep, nm, aw, s.pen_dep_0), h: null });
	const d = g.d;
	const diffMMF = new Float64Array(Math.max(0, nm - 1));
	const diffMMB = new Float64Array(Math.max(0, nm - 1));
	let diffFM1;
	let diffM1F;
	if (g.kind === 'matched') {
		// The same exchange, over the matched node spacings: h[0] from the
		// wall to the first node, h[j+1] between node j and node j+1.
		const h = g.h;
		diffFM1 = (fDf * aw * s.de_m) / h[0];
		diffM1F = s.de_m / (rM * d[0] * h[0]);
		for (let j = 0; j < nm - 1; j++) {
			diffMMF[j] = s.de_m / (rM * d[j] * h[j + 1]);
			diffMMB[j] = s.de_m / (rM * d[j + 1] * h[j + 1]);
		}
		return {
			aw, rM, fDf, advF, dF, d, h, grid: 'matched', diffFM1, diffM1F, diffMMF, diffMMB,
		};
	}

	// Fracture -> first matrix layer, and back. The forward rate is a loss
	// from the fracture's own water, so it carries `f_df` and the wetted area
	// per unit volume; the backward one is a loss from a layer whose capacity
	// is `r_m` times its pore volume. Their ratio is the equilibrium
	// partitioning between the two, which is why neither may be simplified.
	diffFM1 = (fDf * 2 * aw * s.de_m) / d[0];
	diffM1F = (2 * s.de_m) / (rM * d[0] * d[0]);

	// Layer to layer: a conductance over the distance between two layer
	// centres, divided by the losing layer's own capacity -- so the two
	// directions differ whenever the layers do.
	for (let j = 0; j < nm - 1; j++) {
		diffMMF[j] = (2 * s.de_m) / (rM * d[j] * (d[j] + d[j + 1]));
		diffMMB[j] = (2 * s.de_m) / (rM * d[j + 1] * (d[j + 1] + d[j]));
	}
	return {
		aw, rM, fDf, advF, dF, d, h: null, grid: 'reference', diffFM1, diffM1F, diffMMF, diffMMB,
	};
}

/**
 * The tangent of `coefficients`, given the tangent of each setting.
 *
 * The matched layers are laid out once per run and held (see `pathGrid`), so
 * their thicknesses have no tangent: only the rates written over them move.
 * The reference layers follow the settings, and their tangent is
 * `layerDepthsTangent`'s.
 */
export function coefficientsTangent(s, ds, c) {
	const { nf, nm } = s;
	const dAw = wettedSurfaceTangent(s, ds);
	const dRM = ds.eps_m + ds.rho_m * s.kd_m + s.rho_m * ds.kd_m;
	const dFDf = -(ds.kd_f * c.aw + s.kd_f * dAw) * c.fDf * c.fDf;
	const dAdvF = (nf * (dFDf * s.tw - c.fDf * ds.tw)) / (s.tw * s.tw);
	const shape = nf / s.pe - 0.5;
	const dDF = c.dF > 0
		? dAdvF * shape + c.advF * (-(nf / (s.pe * s.pe)) * ds.pe)
		: 0;
	if (c.grid === 'matched') {
		const { d, h } = c;
		const dDiffFM1 = (dFDf * c.aw * s.de_m + c.fDf * dAw * s.de_m + c.fDf * c.aw * ds.de_m) / h[0];
		// Products rather than logs, for the reason given below: a nuclide
		// that does not diffuse at all has De = 0.
		const dDiffM1F = ds.de_m / (c.rM * d[0] * h[0]) - c.diffM1F * (dRM / c.rM);
		const dDiffMMF = new Float64Array(Math.max(0, nm - 1));
		const dDiffMMB = new Float64Array(Math.max(0, nm - 1));
		for (let j = 0; j < nm - 1; j++) {
			dDiffMMF[j] = ds.de_m / (c.rM * d[j] * h[j + 1]) - c.diffMMF[j] * (dRM / c.rM);
			dDiffMMB[j] = ds.de_m / (c.rM * d[j + 1] * h[j + 1]) - c.diffMMB[j] * (dRM / c.rM);
		}
		return {
			aw: dAw, rM: dRM, fDf: dFDf, advF: dAdvF, dF: dDF, d: new Float64Array(nm),
			diffFM1: dDiffFM1, diffM1F: dDiffM1F, diffMMF: dDiffMMF, diffMMB: dDiffMMB,
		};
	}
	const dd = layerDepthsTangent(
		s.pen_dep, nm, c.aw, s.pen_dep_0, c.d, ds.pen_dep, dAw, ds.pen_dep_0,
	);

	const dDiffFM1 = (2 / c.d[0]) * (
		dFDf * c.aw * s.de_m + c.fDf * dAw * s.de_m + c.fDf * c.aw * ds.de_m
	) - (c.diffFM1 / c.d[0]) * dd[0];
	// Written as a product rather than as `diffM1F * (dDe/De - ...)`. The log
	// form is shorter but divides by `de_m`, and a nuclide with no matrix
	// diffusion at all -- De = 0, a perfectly ordinary thing to model -- then
	// made every one of these NaN. The derivative stayed clean and only the
	// Jacobian was poisoned, which is the hardest kind of wrong to notice.
	const dDiffM1F = (2 * ds.de_m) / (c.rM * c.d[0] * c.d[0])
		- c.diffM1F * (dRM / c.rM + (2 * dd[0]) / c.d[0]);

	const dDiffMMF = new Float64Array(Math.max(0, nm - 1));
	const dDiffMMB = new Float64Array(Math.max(0, nm - 1));
	for (let j = 0; j < nm - 1; j++) {
		const sumd = c.d[j] + c.d[j + 1];
		const dsumd = dd[j] + dd[j + 1];
		dDiffMMF[j] = (2 * ds.de_m) / (c.rM * c.d[j] * sumd)
			- c.diffMMF[j] * (dRM / c.rM + dd[j] / c.d[j] + dsumd / sumd);
		dDiffMMB[j] = (2 * ds.de_m) / (c.rM * c.d[j + 1] * sumd)
			- c.diffMMB[j] * (dRM / c.rM + dd[j + 1] / c.d[j + 1] + dsumd / sumd);
	}
	return {
		aw: dAw, rM: dRM, fDf: dFDf, advF: dAdvF, dF: dDF, d: dd,
		diffFM1: dDiffFM1, diffM1F: dDiffM1F, diffMMF: dDiffMMF, diffMMB: dDiffMMB,
	};
}

/**
 * Where each state sits within one nuclide's block of cells.
 *
 * Cell `k*(n_m+1)` is fracture cell k; the n_m behind it are its matrix
 * layers. The reference implementation's own numbering, so an inventory can be
 * compared position by position.
 */
export function cellIndex(k, j, nm) {
	return k * (nm + 1) + j;
}

/**
 * How many cells of rock past the release point the semi-infinite outlet
 * needs, worked out from the fracture cells and the Peclet number.
 *
 * Downstream of the release point the rock is the same rock, so the cells
 * there are the path's own, and what they are for is the one thing a finite
 * grid cannot say: how the water beyond the plane pushes back on it. That push
 * is dispersion running upstream, and in the discrete path it dies away by a
 * factor of
 *
 *     ρ = (2·N_F − P_e) / (2·N_F + P_e)
 *
 * per cell at the lowest frequencies, where it dies slowest (faster at every
 * higher one). So the count is the fewest cells that bring ρ^N_B under a
 * tenth -- the far end then closes by linear extrapolation, itself a second-
 * order guess at the rock beyond, and a tenth of its error is left. Measured
 * against the rock going on for ever, that is within 5e-4 in the logarithm of
 * the transfer function at every frequency for 20 cells at P_e 10, which is
 * well under what the 20 fracture cells themselves cost. Where 2·N_F ≤ P_e the
 * fracture has no explicit dispersion left, nothing runs upstream at all, and
 * no cell is needed.
 *
 * Worked out by repeated multiplication, so both engines count the same.
 *
 * The count decides how many states there are, which is settled before any
 * equation is worked out -- so it needs a Peclet number that is a number. One
 * written as an equation is taken as 10, the common value, and the panel says
 * so; a path whose Peclet number is far from that can set the count itself.
 */
export function autoExtraCells(nf, pe) {
	const n = Number(nf);
	let p = Number(pe);
	if (!Number.isInteger(n) || n < 1) return 0;
	if (!(p > 0) || !Number.isFinite(p)) p = 10;
	const rho = (2 * n - p) / (2 * n + p);
	if (!(rho > 0)) return 0;
	let k = 0;
	let left = 1;
	while (left > 0.1 && k < 10000) { left *= rho; k++; }
	return k;
}

/** Whether a setting that is a count was left empty, which asks for it to be worked out. */
const isEmpty = (v) => v == null || (typeof v === 'string' && v.trim() === '');

/**
 * How many extra cells a path has past its release point: the count it gives,
 * or, left empty, none -- unless its outlet is the semi-infinite rock, which
 * works the count out (`autoExtraCells`).
 */
export function extraCells(block) {
	const nb = block?.n_b;
	if (isEmpty(nb)) {
		return Number(block?.o_b) === CONTINUES ? autoExtraCells(block?.n_f, block?.pe) : 0;
	}
	return Number(nb);
}

/**
 * The structure the cells are built on: counts as numbers, and the
 * semi-infinite outlet said as what it is on the grid -- extra cells past the
 * release point, closed at the far end by linear extrapolation, with the
 * release read at the plane between cell N_F and the first of them.
 *
 * `downstream` says the extra cells stand for rock past the release point,
 * so what they hold has already been released: they are not in the path's
 * inventory, and a release delivered to a compartment is not counted twice.
 * With the reference implementation's outlets the extra cells are the path's
 * own, read inside, as they always were.
 *
 * Idempotent: a structure that is already one comes back as it went in.
 */
export function effectiveStructure(block) {
	const ob = Number(block?.o_b);
	const nf = Number(block?.n_f);
	const nm = Number(block?.n_m);
	const nb = extraCells(block);
	if (ob === CONTINUES) return { n_f: nf, n_m: nm, o_b: 2, n_b: nb, downstream: true };
	return { n_f: nf, n_m: nm, o_b: ob, n_b: nb, downstream: !!block?.downstream };
}

/**
 * How many cells one nuclide's path has, extra outflow cells included -- and
 * none for a path worked out some other way than on cells (see `usesCells`),
 * which is what the state count and the panel read.
 */
export function cellCount(block) {
	// What a semi-analytical path holds, per nuclide, is one state.
	if (isSemiAnalytic(block)) return 1;
	if (!usesCells(block)) return 0;
	const { n_f: nf, n_m: nm, n_b: nb } = effectiveStructure(block);
	return (nf + nb) * (nm + 1);
}

/**
 * The cells whose inventory is the path's: all of them, except the extra
 * cells of a semi-infinite outlet, which stand for rock downstream of the
 * release point.
 */
export function heldCells(block) {
	if (isSemiAnalytic(block)) return 1;
	if (!usesCells(block)) return 0;
	const g = effectiveStructure(block);
	const count = (g.downstream ? g.n_f : g.n_f + g.n_b) * (g.n_m + 1);
	return count;
}

/**
 * The matrix layout one path shares across every nuclide on it.
 *
 * The reference layers depend on the path's settings alone, and are worked out
 * from them. The matched layers are worked out from every nuclide at once (see
 * `autoFirstLayer`) -- so this is where the nuclides meet.
 *
 * @param {object} p  { grid, penDep, nm, first, aw, tw, pe, nucs }
 */
export function pathGrid(p) {
	if (p.grid === 'matched') return matchedGrid(p);
	return { kind: 'reference', d: layerDepths(p.penDep, p.nm, p.aw, p.first), h: null, q: NaN };
}

/**
 * Which (row, column) pairs the transport matrix can fill, in cell numbering.
 *
 * Structural: it depends on the cell counts and the boundary condition, never
 * on a rate. `values` below fills these same positions in this same order, so
 * one structure serves every nuclide and every index of the block.
 *
 * @returns {{rows: Int32Array, cols: Int32Array, nnz: number}}
 */
export function cellStructure(block) {
	const { n_f: nf, n_m: nm, o_b: ob, n_b: nb } = effectiveStructure(block);
	const NF = nf + nb;
	const rows = [];
	const cols = [];
	const at = (r, c) => { rows.push(r); cols.push(c); };
	const cell = (k, j) => cellIndex(k, j, nm);

	// Diagonals: every cell loses.
	for (let k = 0; k < NF; k++) at(cell(k, 0), cell(k, 0));
	for (let k = 0; k < NF; k++) {
		for (let j = 1; j <= nm; j++) at(cell(k, j), cell(k, j));
	}
	// Along the fracture: advection and dispersion forward, dispersion back.
	for (let k = 1; k < NF; k++) {
		at(cell(k, 0), cell(k - 1, 0));
		at(cell(k - 1, 0), cell(k, 0));
	}
	// The quadratic outflow condition reaches one cell further upstream.
	if (ob === 3) at(cell(NF - 1, 0), cell(NF - 3, 0));
	// Sideways, fracture to first layer and back.
	for (let k = 0; k < NF; k++) {
		at(cell(k, 1), cell(k, 0));
		at(cell(k, 0), cell(k, 1));
	}
	// ...and between layers.
	for (let j = 0; j < nm - 1; j++) {
		for (let k = 0; k < NF; k++) {
			at(cell(k, j + 2), cell(k, j + 1));
			at(cell(k, j + 1), cell(k, j + 2));
		}
	}
	return { rows: Int32Array.from(rows), cols: Int32Array.from(cols), nnz: rows.length };
}

/**
 * The transport matrix's values, in the order `cellStructure` lists them.
 *
 * `get_jac_rn`, entry for entry. Duplicate positions are *summed* there, by
 * scipy's own COO-to-CSR conversion, and the four corrections the boundary
 * conditions make to a diagonal are written that way -- so they are summed
 * here too, into `out`, rather than assigned.
 *
 * @param {Float64Array} out length `nnz`, written in place
 */
export function cellValues(block, c, out) {
	const { n_f: nf, n_m: nm, o_b: ob, n_b: nb } = effectiveStructure(block);
	const NF = nf + nb;
	const { advF, dF, diffFM1, diffM1F, diffMMF, diffMMB } = c;
	out.fill(0);
	let i = 0;

	// Fracture diagonals.
	const fracLoss = -(advF + 2 * dF + diffFM1);
	for (let k = 0; k < NF; k++) out[i + k] = fracLoss;
	// The first cell has no upstream neighbour to disperse into: the inlet is
	// a flux, not a concentration.
	out[i] += dF;
	// The last cell's downstream loss follows from what is assumed about the
	// water beyond it. 0 keeps both losses -- the concentration out there is
	// zero, so dispersion carries mass away as fast as advection does.
	if (ob === 1) out[i + NF - 1] += dF;
	else if (ob === 2) out[i + NF - 1] += 2 * dF;
	else if (ob === 3) out[i + NF - 1] += 3 * dF;
	i += NF;

	// Matrix diagonals: the first layer loses to the fracture and inwards, the
	// last only back outwards -- there is no flux through the far face, which
	// is what makes the penetration depth a depth rather than a boundary.
	for (let k = 0; k < NF; k++) {
		for (let j = 1; j <= nm; j++) {
			out[i++] = j === 1 ? -(diffM1F + diffMMF[0])
				: j === nm ? -diffMMB[nm - 2]
					: -(diffMMF[j - 1] + diffMMB[j - 2]);
		}
	}

	// Along the fracture.
	for (let k = 1; k < NF; k++) {
		out[i] = dF + advF;
		// An extrapolated outflow reads the concentration upstream of the last
		// cell, so the flux out of the path depends on it -- and the last
		// forward term loses exactly what the extrapolation adds.
		if (k === NF - 1) {
			if (ob === 2) out[i] -= dF;
			else if (ob === 3) out[i] -= 3 * dF;
		}
		i++;
		out[i++] = dF;
	}
	if (ob === 3) out[i++] = dF;

	// Sideways.
	for (let k = 0; k < NF; k++) {
		out[i++] = diffFM1;
		out[i++] = diffM1F;
	}
	for (let j = 0; j < nm - 1; j++) {
		for (let k = 0; k < NF; k++) {
			out[i++] = diffMMF[j];
			out[i++] = diffMMB[j];
		}
	}
	return out;
}

/**
 * The release out of the path: which cells it is read from, with what weight.
 *
 * `get_release`. The mass has already left the block -- the boundary condition
 * put that loss on the last cell's diagonal -- so this is a reading, not a
 * transfer: what it says is how much per unit time is crossing the outflow
 * face, ready to be handed to a compartment downstream.
 *
 * With extra outflow cells the face is *inside* the modelled domain, between
 * cell N_F and the first of the extra ones, and the reading is taken there --
 * which, for the semi-infinite outlet, is the release point itself, with the
 * rock beyond it in the extra cells.
 *
 * @returns {number[]} cell indices, paired with `releaseWeights`
 */
export function releaseCells(block) {
	const { n_f: nf, n_m: nm, n_b: nb, o_b: ob } = effectiveStructure(block);
	const cell = (k) => cellIndex(k - 1, 0, nm); // k is 1-based, as in the reference
	if (nb > 0) return [cell(nf), cell(nf + 1)];
	if (ob === 2) return [cell(nf), cell(nf - 1)];
	if (ob === 3) return [cell(nf), cell(nf - 1), cell(nf - 2)];
	return [cell(nf)];
}

/**
 * The weights for those cells, from the rates.
 *
 * ONE DELIBERATE DIFFERENCE FROM THE REFERENCE. With extra outflow cells the
 * reference reads `(adv_f - d_f)*I[N_F] - d_f*I[N_F+1]`, and that loses mass:
 * the flux the matrix itself implies is advection forward plus dispersion both
 * ways, `(adv_f + d_f)*I[N_F] - d_f*I[N_F+1]`, and the sign on the dispersive
 * self-term is the only thing that differs. Integrated over a unit release
 * through five cells at Pe 8, the reference's form comes to 0.750 and this one
 * to 1.000, against an inventory upstream of the face that has gone to zero --
 * so it is a slip rather than a modelling choice, and this tool does not
 * reproduce it. Every other case (no extra cells, any outflow condition) is
 * the reference's own arithmetic, and conserves mass exactly.
 */
export function releaseWeights(block, c, out) {
	const { n_b: nb, o_b: ob } = effectiveStructure(block);
	const { advF, dF } = c;
	if (nb > 0) { out[0] = advF + dF; out[1] = -dF; return out; }
	if (ob === 0) { out[0] = advF + dF; return out; }
	if (ob === 1) { out[0] = advF; return out; }
	if (ob === 2) { out[0] = advF - dF; out[1] = dF; return out; }
	out[0] = advF - 2 * dF; out[1] = 3 * dF; out[2] = -dF;
	return out;
}

/**
 * Whether a set of structural settings describes a path that can be built,
 * and what is wrong when it cannot.
 *
 * @returns {string|null}
 */
export function structureProblem(block) {
	// A semi-analytical path has no cells: the counts and the outlet are the
	// cells' settings and are not read.
	if (isSemiAnalytic(block)) {
		return block.surface == null || block.surface === '' || SURFACES.includes(block.surface)
			? null
			: `surface must be one of ${SURFACES.join(', ')}`;
	}
	const int = (key, min) => {
		const v = Number(block[key]);
		if (!Number.isInteger(v)) return `${key} must be a whole number`;
		if (v < min) return `${key} must be at least ${min}`;
		return null;
	};
	// The extra cells may be left empty, which asks for them to be worked
	// out (none, unless the outlet is the semi-infinite rock).
	const problem = int('n_f', 1) ?? int('n_m', 2) ?? (isEmpty(block.n_b) ? null : int('n_b', 0))
		?? (OUTFLOWS.includes(Number(block.o_b))
			? null
			: `o_b must be one of ${OUTFLOWS.join(', ')}`)
		?? (block.method == null || block.method === '' || FARF_METHODS.includes(block.method)
			? null
			: `method must be one of ${FARF_METHODS.join(', ')}`)
		?? (block.grid == null || block.grid === '' || GRIDS.includes(block.grid)
			? null
			: `grid must be one of ${GRIDS.join(', ')}`)
		?? (block.surface == null || block.surface === '' || SURFACES.includes(block.surface)
			? null
			: `surface must be one of ${SURFACES.join(', ')}`);
	if (problem) return problem;
	// On the grid itself, the semi-infinite rock is a linear extrapolation at
	// the far end of its extra cells.
	const g = effectiveStructure(block);
	// The two extrapolating conditions read cells upstream of the last
	// one, and the release is read upstream of that again.
	if (g.o_b === 2 && g.n_f + g.n_b < 2) return 'a linearly extrapolated outflow needs at least two fracture cells';
	if (g.o_b === 3 && g.n_f + g.n_b < 3) return 'a quadratically extrapolated outflow needs at least three fracture cells';
	if (g.n_b === 0 && g.o_b === 3 && g.n_f < 3) return 'reading the release under a quadratic outflow needs three fracture cells';
	if (g.n_b === 0 && g.o_b === 2 && g.n_f < 2) return 'reading the release under a linear outflow needs two fracture cells';
	return null;
}

/**
 * The Peclet number the fracture grid produces on its own.
 *
 * The fracture is discretised with first-order upwinding, and that scheme
 * disperses whether or not it is asked to: each cell adds `v·Δx/2`, which over
 * `N_F` cells along a path of unit length is the same as a Peclet number of
 * `2·N_F`. So a grid of five cells already spreads a front as a Peclet number
 * of 10 would. With the difference added back as explicit dispersion the
 * scheme is central differencing, second order in the cell length.
 *
 * This is the number the `− ½` in `coefficients` is about: the dispersion the
 * model *adds* is the difference between what was asked for and what the grid
 * already does, `d_f = adv_f·(N_F/Pe − ½)`, which is zero exactly where
 * `2·N_F = Pe`.
 */
export const gridPeclet = (nf) => 2 * Number(nf);

/**
 * Warns when the grid disperses more than the Peclet number asked for.
 *
 * Three cases, and only the third is a problem:
 *
 *   2·N_F  <  Pe   the grid is coarser than the answer wants. The correction
 *                  would have to be *negative* to sharpen the front back up,
 *                  and `max(0, ...)` in `coefficients` clamps it away -- so
 *                  the path disperses as if Pe were 2·N_F, more spread than
 *                  was asked for, and no number in the model says so.
 *   2·N_F  == Pe   the grid's own dispersion is exactly the answer. Nothing
 *                  is added; this is the cheapest grid that gets it right.
 *   2·N_F  >  Pe   the grid is finer than needed and the difference is added
 *                  explicitly. The total is the Pe asked for, at more states.
 *
 * Null when the Peclet number is an equation rather than a number: what it
 * works out to is a thing only a run can know, and a warning that guessed
 * would be worse than none.
 *
 * @returns {string|null} the warning, phrased as the rest of them are
 */
export function dispersionWarning(g) {
	// Worked out exactly, the path disperses as its Peclet number says.
	if (isSemiAnalytic(g)) return null;
	const nf = Number(g?.n_f);
	const pe = Number(g?.pe);
	if (!Number.isInteger(nf) || nf < 1) return null;
	if (!Number.isFinite(pe) || !(pe > 0)) return null;
	const own = gridPeclet(nf);
	if (own >= pe) return null;
	const need = Math.ceil(pe / 2);
	return `${nf} fracture cell${nf === 1 ? '' : 's'} disperse${nf === 1 ? 's' : ''} `
		+ `as a Peclet number of ${own} would, and ${pe} was asked for: a coarser `
		+ `grid spreads a front more, and the correction that would sharpen it back `
		+ `up cannot be negative — so none is applied and the path is more `
		+ `dispersive than the setting says. ${need} cell${need === 1 ? '' : 's'} `
		+ `(Pe/2) is the fewest that reaches Pe ${pe}`;
}

/**
 * The same check ahead of a run, for the ordinary case where the depths are
 * numbers rather than equations. An equation is left to `layerDepths`, which
 * is where it will be evaluated.
 *
 * @returns {string|null}
 */
export function geometryProblem(block) {
	const nm = Number(block.n_m);
	const penDep = Number(block.pen_dep);
	// Without layers the depth is the only geometry: the rock's own thickness.
	if (isSemiAnalytic(block)) {
		return Number.isFinite(penDep) && !(penDep > 0) ? 'the penetration depth must be a positive length' : null;
	}
	const first = block.pen_dep_0 === '' || block.pen_dep_0 == null
		? null
		: Number(block.pen_dep_0);
	// Anything that is not a plain number is an equation, and an equation is
	// not this function's business.
	if (!Number.isFinite(penDep) || !Number.isInteger(nm)) return null;
	if (!(penDep > 0)) return 'the penetration depth must be a positive length';
	if (first == null || !Number.isFinite(first)) return null;
	if (!(first > 0)) return 'the first matrix layer must be a positive length';
	if (first * nm > penDep * (1 + 1e-12)) {
		return `${nm} matrix layers starting at ${first} m cannot add up to a `
			+ `penetration depth of ${penDep} m: the layers grow with depth, so the `
			+ `first must be smaller than ${penDep / nm} m`;
	}
	return null;
}

/**
 * What each cell is called, for a result label: `F3` is the third fracture
 * cell, `M3_1` the first matrix layer behind it. The reference
 * implementation's own names, from `calculate_inventory`.
 */
export function cellNames(block) {
	const { n_f: nf, n_m: nm, n_b: nb } = effectiveStructure(block);
	const names = new Array((nf + nb) * (nm + 1));
	for (let k = 0; k < nf + nb; k++) {
		names[cellIndex(k, 0, nm)] = `F${k + 1}`;
		for (let j = 1; j <= nm; j++) names[cellIndex(k, j, nm)] = `M${k + 1}_${j}`;
	}
	return names;
}
