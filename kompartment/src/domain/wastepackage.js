/**
 * Waste packages: the source term with its barriers, as one block.
 *
 * A repository's inventory does not start in the water. It starts inside
 * packages -- canisters, drums, concrete moulds -- and reaches the near field
 * only as those fail and the waste form inside them dissolves. Written as
 * compartments and transfers that is a compartment for the intact packages, a
 * compartment for the exposed waste, a transfer between them whose rate is a
 * failure *hazard* that changes shape with time, and a release that is part
 * instant and part congruent with the matrix -- eight blocks per waste type,
 * every one of them a place to make a sign error. GoldSim's Source element is
 * that written once, and so is this: a block that holds the inventory, says how
 * the packages fail, and releases through a transfer drawn out of it exactly
 * as a far-field path does.
 *
 * WHAT IT INTEGRATES, per nuclide (or once, indexed by nothing):
 *
 *     intact   dP/dt = -h(t) P            + decay and ingrowth
 *     exposed  dM/dt = +h(t) P (1 - irf)  - d(t) M   + decay and ingrowth
 *     release  R(t)  =  h(t) P irf        + d(t) M
 *
 * where `h(t)` is the failure hazard -- the fraction of the still-intact
 * packages failing per unit time -- `irf` the instant-release fraction (the
 * part of a package's inventory that is in the water the moment the barrier
 * goes: gap and grain-boundary inventory in spent fuel, GoldSim's "unbound"
 * mass), and `d(t)` the matrix degradation rate, the fraction of the exposed
 * waste form dissolving per unit time, which carries what is bound in the
 * matrix out *congruently* -- every nuclide in proportion to what the matrix
 * holds of it. Decay and ingrowth run in both inventories along the model's
 * own chain, so a daughter grown in inside an intact canister is there to be
 * released when the canister fails.
 *
 * THE FAILURE, as a hazard rather than a fraction, because the hazard is what
 * multiplies an inventory that is also decaying: a fraction failed F(t) says
 * how many packages have gone, and says nothing about what was left in them.
 * The two are one function -- h = F'/(1 - F) -- and the five ways of writing
 * it here each have a closed form for both:
 *
 *   never        nothing fails; the packages are a store that only decays
 *   at           every package at one time: a jump, not a rate, applied by
 *                the runner at that corner (see `solveAcrossBreaks`)
 *   uniform      evenly between two times: h = 1/(t_to - t), which is what
 *                makes F linear; capped near the end so the last package goes
 *                without the hazard reaching infinity
 *   exponential  a constant rate from a start time: F = 1 - exp(-λ(t - t0))
 *   weibull      a rate that rises (shape > 1) or falls (shape < 1) with age:
 *                h = (k/η)((t - t0)/η)^(k-1), the standard corrosion form
 *
 * The times are corners the solver should not step across, and they are given
 * to it as switch times without being written down twice -- see
 * ./switchtimes.js.
 *
 * WHAT IT IS NOT. Solubility is not in here. GoldSim's Source applies an
 * elemental solubility inside its own water volume; this tool already has that
 * on a transfer -- an *availability*, with the molar sharing an element's
 * isotopes need -- so the release goes into an ordinary near-field compartment
 * and the solubility limit sits on the transfer out of it, where it can be
 * seen and where erosion can ignore it. Nor are the packages counted one by
 * one: `packages` is a number the modeller states, the hazard applies to the
 * inventory as a whole, and a realisation that sampled each package's failure
 * would be the disruptive-event machinery's to add.
 */

import { qualifiedName } from './systems.js';

/** How the packages fail, as a model spells it. */
export const FAILURES = ['never', 'at', 'uniform', 'exponential', 'weibull'];

/** What each is called where somebody reads it. */
export const FAILURE_LABEL = {
	never: 'never — the packages stay intact',
	at: 'all at one time',
	uniform: 'evenly over a window',
	exponential: 'at a constant rate',
	weibull: 'Weibull — a rate that changes with age',
};

/** A line each, for the panel that offers them. */
export const FAILURE_BLURB = {
	never: 'Nothing fails. The block is a store: its inventory decays and grows in, and '
		+ 'nothing is released.',
	at: 'Every package fails at one time. The intact inventory moves to the exposed '
		+ 'waste form in one step, and the instant-release fraction goes into the release '
		+ 'target at that moment.',
	uniform: 'Failures are spread evenly between two times, so the fraction failed rises '
		+ 'in a straight line from 0 to 1.',
	exponential: 'A constant fraction of the still-intact packages fails per unit time '
		+ 'from a start time: the fraction failed is 1 − exp(−rate × (t − start)).',
	weibull: 'The failure rate rises with age when the shape is above 1 — corrosion, '
		+ 'wear — and falls when it is below. The scale is the characteristic life, '
		+ 'measured from the start time.',
};

/** Which settings each way of failing reads. */
export const FAILURE_KEYS = {
	never: [],
	at: ['fail_at'],
	uniform: ['fail_from', 'fail_to'],
	exponential: ['fail_start', 'fail_rate'],
	weibull: ['fail_start', 'fail_scale', 'fail_shape'],
};

/** The settings that are a property of the nuclide and so hold one value per nuclide. */
export const WASTE_NUCLIDE_KEYS = ['inventory', 'irf'];

/**
 * The settings that describe the packages and the waste form, and so hold one
 * value however many nuclides the block is indexed by: canisters do not fail
 * at one rate for caesium and another for iodine.
 */
export const WASTE_SINGLE_KEYS = [
	'degradation_rate', 'fail_at', 'fail_from', 'fail_to', 'fail_start', 'fail_rate',
	'fail_scale', 'fail_shape',
];

/** Every setting written as an equation, in the order the panel shows them. */
export const WASTE_EQUATION_KEYS = [...WASTE_NUCLIDE_KEYS, ...WASTE_SINGLE_KEYS];

export const WASTE_LABEL = {
	inventory: 'Inventory',
	irf: 'Instant release fraction',
	degradation_rate: 'Matrix degradation rate',
	fail_at: 'Fail at',
	fail_from: 'Failures from',
	fail_to: 'Failures until',
	fail_start: 'Failures start',
	fail_rate: 'Failure rate',
	fail_scale: 'Weibull scale',
	fail_shape: 'Weibull shape',
};

export const WASTE_HELP = {
	inventory: 'What the packages hold at the start, in the model’s inventory unit — the '
		+ 'total over all of them, not per package.',
	irf: 'The fraction of a package’s inventory that is released the moment it fails — '
		+ 'the gap and grain-boundary inventory of spent fuel, or whatever is not bound in '
		+ 'the matrix. 0 to 1; the rest waits for the matrix to degrade.',
	degradation_rate: 'The fraction of the exposed waste form that dissolves per unit time, '
		+ 'carrying every nuclide bound in it out in proportion — a congruent release. 0 '
		+ 'leaves the exposed inventory where it is.',
	fail_at: 'The time every package fails, in the model’s time unit.',
	fail_from: 'When the first packages fail.',
	fail_to: 'When the last have failed.',
	fail_start: 'No package fails before this.',
	fail_rate: 'The fraction of the still-intact packages failing per unit time, from the '
		+ 'start.',
	fail_scale: 'The characteristic life, measured from the start: 63% of the packages '
		+ 'have failed one scale after it.',
	fail_shape: 'Above 1 the rate rises with age; 1 is a constant rate; below 1 it falls.',
};

export const WASTE_DEFAULTS = {
	failure: 'never',
	packages: 1,
	inventory: '0',
	irf: '0',
	degradation_rate: '0',
	fail_at: '',
	fail_from: '',
	fail_to: '',
	fail_start: '0',
	fail_rate: '',
	fail_scale: '',
	fail_shape: '1',
	// The same switch a compartment has, for the same reason.
	handle_decay: true,
};

/** The way the packages fail, `never` unless the block says otherwise. */
export function failureOf(block) {
	const f = block?.failure;
	return FAILURES.includes(f) ? f : 'never';
}

/** The settings whose values are times the solver should land on exactly. */
export function failureTimeKeys(failure) {
	return {
		never: [], at: ['fail_at'], uniform: ['fail_from', 'fail_to'],
		exponential: ['fail_start'], weibull: ['fail_start'],
	}[failure] ?? [];
}

/**
 * Below this share of the window the uniform hazard stops growing. `1/(to - t)`
 * is infinite at the end of the window, and the solver would have to chase it
 * there; capped at a thousandth of the window the last packages go in a few
 * thousandths more, which is the same answer at any resolution a model has.
 */
export const WINDOW_TAIL = 1e-3;

/**
 * The hazard as JavaScript, over the variable names given.
 *
 * `v.t` is the clock and the rest are expressions for the settings -- slots
 * of the algebraic vector, in the builder -- so the text can be dropped into
 * the generated code. `at` is a jump rather than a rate and has no hazard.
 */
export function hazardCode(failure, v) {
	switch (failure) {
		case 'uniform':
			return `((${v.t}) < (${v.from}) ? 0 : 1 / Math.max((${v.to}) - (${v.t}), `
				+ `${WINDOW_TAIL} * Math.abs((${v.to}) - (${v.from}))))`;
		case 'exponential':
			return `((${v.t}) < (${v.start}) ? 0 : (${v.rate}))`;
		case 'weibull':
			return `((${v.t}) < (${v.start}) ? 0 : ((${v.shape}) / (${v.scale})) * `
				+ `Math.pow(Math.max((${v.t}) - (${v.start}), 1e-12 * Math.abs(${v.scale})) / (${v.scale}), (${v.shape}) - 1))`;
		default:
			return '0';
	}
}

/** The same hazard as a number, for a preview or a test. */
export function hazard(failure, t, p) {
	const fn = new Function('t', 'p', `return ${hazardCode(failure, {
		t: 't', from: 'p.from', to: 'p.to', start: 'p.start', rate: 'p.rate',
		scale: 'p.scale', shape: 'p.shape',
	})};`);
	return fn(t, p);
}

/** The fraction of the packages failed by time `t`, in closed form. */
export function failedFraction(failure, t, p) {
	switch (failure) {
		case 'at': return t >= p.at ? 1 : 0;
		case 'uniform': return Math.min(1, Math.max(0, (t - p.from) / (p.to - p.from)));
		case 'exponential': return t < p.start ? 0 : 1 - Math.exp(-p.rate * (t - p.start));
		case 'weibull': return t < p.start ? 0 : 1 - Math.exp(-(((t - p.start) / p.scale) ** p.shape));
		default: return 0;
	}
}

/** How the block should be read, for a subtitle or the Information view. */
export function describeWaste(block) {
	const n = Number(block?.packages);
	const count = Number.isFinite(n) && n > 1 ? `${n.toLocaleString()} packages, ` : '';
	const f = failureOf(block);
	const say = (k) => String(block[k] ?? '').trim() || '?';
	const how = {
		never: 'never fail',
		at: `fail at ${say('fail_at')}`,
		uniform: `fail ${say('fail_from')} – ${say('fail_to')}`,
		exponential: `fail at ${say('fail_rate')} a ${'time unit'} from ${say('fail_start')}`,
		weibull: `fail Weibull(${say('fail_scale')}, ${say('fail_shape')}) from ${say('fail_start')}`,
	}[f];
	return `${count}${how}`;
}

/**
 * What is wrong with the model's waste packages, before the run.
 *
 * Errors rather than warnings: a block whose failure cannot be worked out is a
 * release that cannot be worked out.
 *
 * @returns {Array<{name: string, field: string|null, message: string}>}
 */
export function wasteProblems(project) {
	const out = [];
	for (const b of project?.waste_packages ?? []) {
		const name = qualifiedName(b);
		const f = b.failure ?? 'never';
		if (!FAILURES.includes(f)) {
			out.push({
				name, field: 'failure',
				message: `'${f}' is not a way for packages to fail (${FAILURES.join(', ')}).`,
			});
			continue;
		}
		for (const key of FAILURE_KEYS[f]) {
			if (!String(b[key] ?? '').trim()) {
				out.push({
					name, field: key,
					message: `Packages that fail ${FAILURE_LABEL[f].split(' — ')[0]} need `
						+ `${WASTE_LABEL[key].toLowerCase()}: a number or an equation.`,
				});
			}
		}
		const num = (key) => {
			const v = Number(String(b[key] ?? '').trim());
			return Number.isFinite(v) ? v : null;
		};
		if (f === 'uniform') {
			const a = num('fail_from');
			const z = num('fail_to');
			if (a != null && z != null && !(z > a)) {
				out.push({
					name, field: 'fail_to',
					message: `The failures end (${z}) before they begin (${a}).`,
				});
			}
		}
		if (f === 'weibull' && num('fail_shape') != null && !(num('fail_shape') > 0)) {
			out.push({ name, field: 'fail_shape', message: 'A Weibull shape has to be above 0.' });
		}
		if (f === 'weibull' && num('fail_scale') != null && !(num('fail_scale') > 0)) {
			out.push({ name, field: 'fail_scale', message: 'A Weibull scale has to be above 0.' });
		}
		if (f === 'exponential' && num('fail_rate') != null && num('fail_rate') < 0) {
			out.push({ name, field: 'fail_rate', message: 'A failure rate cannot be negative.' });
		}
		if (b.packages != null && b.packages !== '') {
			const n = Number(b.packages);
			if (!Number.isInteger(n) || n < 1) {
				out.push({
					name, field: 'packages',
					message: `'${b.packages}' is not a number of packages: a whole number, at least 1.`,
				});
			}
		}
		const irf = num('irf');
		if (irf != null && (irf < 0 || irf > 1)) {
			out.push({ name, field: 'irf', message: 'The instant release fraction is between 0 and 1.' });
		}
		const d = num('degradation_rate');
		if (d != null && d < 0) {
			out.push({ name, field: 'degradation_rate', message: 'A degradation rate cannot be negative.' });
		}
	}
	return out;
}
