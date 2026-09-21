/**
 * Running a model many times over its distributions.
 *
 * A deterministic run reads each parameter's value. A probabilistic one reads
 * its *distribution* -- per index, as ../domain/pdf.js keeps them -- draws a
 * value for each realisation, and integrates the model again. What comes back
 * is not a curve but a band: at every output time, what the spread of outcomes
 * was.
 *
 * **Built once, integrated many times.** The expensive half of a run here is
 * the build -- a minute on model G -- and none of it depends on
 * the parameter values: the layout, the generated derivative, the sparsity
 * pattern and its colouring are all structure. So the system is built once and
 * each realisation only rewrites `P`, which the generated code reads live. Two
 * things do have to be redone per realisation and are:
 *
 *   - `system.evaluateInvariant()`, because the algebra that depends on
 *     neither the clock nor the state is worked out at build time *from the
 *     parameters* and left in `X`. Rewriting `P` without this leaves the last
 *     realisation's transfer rates in place, which is a wrong answer that
 *     looks entirely plausible. See *Three passes, not one* in INTERNALS.md.
 *   - `system.initialState()`, because an initial inventory may be an equation
 *     over parameters.
 *
 * **What is kept.** Every realisation of every series is not an option: a
 * thousand runs of `model G` would be 831,314 series by 356 times by 1,000, which
 * is 2.4 terabytes. So a probabilistic run keeps the series it is asked for --
 * the model's endpoints, or a chosen few -- and for those keeps every
 * realisation, because quantiles need them. What that costs is said before it
 * is spent (`estimate`), and refused rather than attempted when it cannot be
 * held.
 */

import { sampleOccurrences } from '../domain/disruption.js';
import { Project } from '../domain/project.js';
import { buildSystem, tupleByList } from './builder.js';
import { run } from './runner.js';
import { effectiveValue } from '../domain/edit.js';
import { streamFor, uniforms, valueAtProbability, distributedSlots } from '../domain/sample.js';
import { correlationPairs, imanConover } from '../domain/correlate.js';

/**
 * What one distributed slot is called, for the stream that draws it.
 *
 * The indexed name, so `Kd[Tc-99]` and `Kd[I-129]` draw independently -- they
 * are two quantities that happen to share a spelling, and a model that gains a
 * nuclide should not move the numbers drawn for the ones it already had.
 * The same spelling `slotLabel` uses, so a reader naming one in the dialog and
 * this agree.
 */
/**
 * Which correlation group an input is in, or null for none.
 *
 * On the distribution rather than the block, because it is a statement about
 * how this spread is drawn: the same group is the same underlying sample.
 */
export function groupOf(entry) {
	const g = entry?.spec?.group;
	const t = g == null ? '' : String(g).trim();
	return t === '' ? null : t;
}

/** The groups in a plan, with who is in each -- for the dialog to report. */
function groupsOf(plan, names) {
	const out = new Map();
	plan.forEach((e, k) => {
		const g = groupOf(e);
		if (!g) return;
		if (!out.has(g)) out.set(g, []);
		out.get(g).push(names[k]);
	});
	return [...out].map(([name, members]) => ({ name, members }));
}

export function slotName(entry) {
	const idx = Object.values(entry?.index ?? {});
	return idx.length ? `${entry.name}[${idx.join('][')}]` : String(entry?.name ?? '');
}

/**
 * Bytes a run of this shape would hold, and whether that is sane.
 *
 * `double` is what a run holds while it is running -- Float64Array throughout,
 * because that is what the solver produces. `float32` is what a *file* of it
 * costs, which is how the realisations are written: half the size, and still
 * far finer than a Monte Carlo sample of a thousand draws can justify. AMBER
 * offers the same choice and defaults to single precision for the same reason.
 */
export function estimate({ series, times, iterations, precision = 'double' }) {
	const bytes = series * times * iterations * (precision === 'float32' ? 4 : 8);
	return {
		bytes,
		text: bytes >= 1073741824 ? `${(bytes / 1073741824).toFixed(1)} GB`
			: bytes >= 1048576 ? `${Math.round(bytes / 1048576)} MB`
				: `${Math.max(1, Math.round(bytes / 1024))} kB`,
	};
}

/** Past this a probabilistic run is refused rather than attempted. */
export const MOST_BYTES = 1073741824;

/**
 * The distributions a model would sample, without running anything.
 *
 * Wanted before a run as well as during one: the dialog says how many values
 * will be drawn and from what, and a model with none is told so rather than
 * running a thousand identical realisations.
 */
export function samplingPlan(project, system) {
	const p = project instanceof Project ? project : new Project(project);
	const sys = system ?? buildSystem(p);
	const all = distributedSlots(
		sys.layout,
		effectiveValue,
		(space, dims, off) => tupleByList(space, dims, off),
	);

	// A model may name which parameters it varies -- Ecolego's
	// `<selected-parameter>`, of which one assessment model lists 427 --
	// and the rest keep their values however good a distribution they carry.
	const chosen = p.simulation?.varied;
	if (!Array.isArray(chosen) || !chosen.length) return all;
	const want = new Set(chosen);
	const named = (e) => {
		const idx = Object.values(e.index ?? {});
		return idx.length ? `${e.name}${idx.map((v) => `[${v}]`).join('')}` : e.name;
	};
	const kept = all.filter((e) => want.has(named(e)) || want.has(e.name));
	// A list that matches nothing is a list about some other spelling of this
	// model -- the importer renames a block whose name is not an identifier --
	// and honouring it would silently vary nothing at all. Better to vary
	// everything, which is what a model with no list means.
	return kept.length ? kept : all;
}

/**
 * Runs `iterations` realisations and keeps the series asked for.
 *
 * @param {object|Project} input
 * @param {object} opts
 * @param {number} opts.iterations
 * @param {number} [opts.seed]         the run is a function of this and nothing else
 * @param {boolean} [opts.latin]       stratified sampling, on by default
 * @param {string[]} [opts.varied]     only these are sampled; the rest stay at
 *                                     the value the model holds. Named as
 *                                     `slotName` spells them.
 * @param {{low: number, high: number}} [opts.tornado]  a one-at-a-time design
 *                                     instead of a sample: see `designFor`
 * @param {(name: string) => boolean} [opts.keep]  which series to hold on to
 * @param {(done: number, total: number) => void} [opts.onProgress]
 * @param {{aborted: boolean}} [opts.signal]
 * @returns {{t: Float64Array, outputs: Array, draws: Float64Array,
 *   values: Float64Array[], plan: Array, iterations: number, stats: object}}
 */
/**
 * What every realisation of a run will set, before any of them is integrated.
 *
 * Shared by the run itself, by a *replay* of one realisation, and by a tornado
 * -- the three ways a design point becomes a model run. The draws are a
 * function of the seed and each input's name and nothing else, so a replay
 * can rebuild realisation 734 of a thousand from the settings alone; it does
 * not need the matrix the run kept.
 *
 * @returns {{plan, names, best, varies, iterations, valueFor, stats}} where
 *   `valueFor(k, i)` is what input `k` takes in realisation `i`, and `stats`
 *   is what to say about the design in the run's statistics
 */
export function designFor(project, system, opts = {}) {
	const seed = opts.seed ?? 1;
	const plan = samplingPlan(project, system);
	// A model with no distributed parameter can still have dice: a disruptive
	// event that draws its occurrences makes every realisation a different run.
	const dice = (system.layout.events ?? []).some((D) => D.timing === 'poisson' && D.sampled);
	if (!plan.length && !(dice && !opts.tornado)) {
		throw new Error('No parameter in this model has a distribution' + (dice
			? ', and a tornado swings parameters; the disruptive events are what varies here, and they need a probabilistic run.'
			: ', so every realisation would be the same run. Give a parameter one first — the '
			+ 'curve at the end of its row in the left panel — or add a disruptive event that draws its occurrences.'));
	}
	const names = plan.map(slotName);
	const P = system.parameterValues;
	// What each slot holds with nothing sampled, so a parameter held back by a
	// partial run can be put back to it -- and what a tornado swings about.
	const best = plan.map((e) => P[e.slot]);

	// Which of them actually vary. The rest sit at the value the model holds,
	// which is what a partial run is: the spread with one input's uncertainty
	// switched off, against the same numbers everywhere else.
	const varied = opts.varied == null
		? null
		: new Set((Array.isArray(opts.varied) ? opts.varied : [...opts.varied]).map(String));
	const varies = (e) => !varied || varied.has(slotName(e));

	// --- a tornado: not a sample at all, but the same shape of run.
	//
	// One point with everything at its value, then every varying input swung
	// on its own to a low and a high probability with the rest held -- GoldSim's
	// "three simulations per variable", with the central one shared. What a
	// probabilistic run answers statistically this answers by construction,
	// and it is what to run when a distribution is not yet trusted enough to
	// sample from.
	if (opts.tornado) {
		const low = Number(opts.tornado.low ?? 0.05);
		const high = Number(opts.tornado.high ?? 0.95);
		const swung = plan.map((e, k) => k).filter((k) => varies(plan[k]));
		const iterations = 2 * swung.length + 1;
		const valueFor = (k, i) => {
			if (i === 0) return best[k];
			const which = swung[Math.floor((i - 1) / 2)];
			if (which !== k) return best[k];
			return valueAtProbability(plan[k].spec, (i - 1) % 2 === 0 ? low : high, i);
		};
		return {
			plan, names, best, varies, iterations, valueFor, seed,
			stats: { seed, latin: false, sampled: plan.length, tornado: { low, high, swung } },
		};
	}

	const iterations = Math.max(1, Math.round(opts.iterations ?? 100));

	// The uniforms first, all of them, because Latin hypercube is a statement
	// about the whole column: the i-th realisation takes the i-th entry of each
	// parameter's own shuffled stratification.
	//
	// **One stream per parameter, named after it.** A single stream split
	// across the plan in order made a sample a fact about the whole list:
	// giving one more parameter a distribution shifted every parameter after it
	// onto different numbers, so the same seed on a model that had gained an
	// input answered differently for every input it already had. See
	// `streamFor`. It is also what makes `varied` below a comparison rather
	// than a different experiment.
	const latin = opts.latin !== false;
	// **A group is one stream shared.** Inputs a data set puts in the same
	// group are the same uncertainty seen in several places -- one element's
	// concentration ratio quoted for four ecosystems, say -- so they are not
	// two draws that happen to agree, they are one draw used twice. Naming the
	// stream after the group rather than the slot is the whole implementation:
	// every member gets the identical uniform column, so they rise and fall
	// together in every realisation. Members with *different* distributions
	// still get different values, which is what full correlation means -- the
	// rank is shared, not the number.
	const draws = plan.map((e) => uniforms(iterations,
		streamFor(seed, groupOf(e) ?? slotName(e)), { latin }));

	// Inputs the model says move together. A permutation of the columns that
	// take part, and only those -- see ../domain/correlate.js -- so every
	// other input's draws are exactly what they were. A pair with a held
	// input in it is left alone: a column of one value has no ranks to
	// arrange.
	const { pairs, problems } = correlationPairs(project, names);
	// A group already says the correlation is one, and Iman-Conover works by
	// permuting a column -- which would take a member out of step with the
	// rest of its group. The group is the stronger statement and the one the
	// data set makes, so it wins and the pair is reported as ignored.
	const grouped = new Set(plan.map((e, k) => (groupOf(e) ? k : -1)).filter((k) => k >= 0));
	for (const pr of pairs) {
		if (!grouped.has(pr.a) && !grouped.has(pr.b)) continue;
		const who = grouped.has(pr.a) ? names[pr.a] : names[pr.b];
		problems.push(`${names[pr.a]} and ${names[pr.b]}: ${who} is in a correlation group, `
			+ 'which already fixes its sample. The correlation was ignored.');
	}
	const usable = pairs.filter((pr) => varies(plan[pr.a]) && varies(plan[pr.b])
		&& !grouped.has(pr.a) && !grouped.has(pr.b));
	const corr = imanConover(draws, usable, names, seed);

	const valueFor = (k, i) => (varies(plan[k])
		? valueAtProbability(plan[k].spec, draws[k][i], i)
		: best[k]);
	return {
		plan, names, best, varies, iterations, valueFor, seed,
		stats: {
			seed, latin, sampled: plan.length,
			correlated: corr.columns.length,
			correlationAdjusted: corr.adjusted,
			correlationProblems: problems,
			groups: groupsOf(plan, names),
		},
	};
}

/**
 * Sets one design point into the system, ready to run.
 *
 * @returns {number[]} the values set, one per input of the plan
 */
export function applyPoint(system, design, i) {
	const P = system.parameterValues;
	const out = new Array(design.plan.length);
	for (let k = 0; k < design.plan.length; k++) {
		const v = design.valueFor(k, i);
		out[k] = v;
		if (Number.isFinite(v)) P[design.plan[k].slot] = v;
		else if (!design.varies(design.plan[k])) P[design.plan[k].slot] = design.best[k];
	}
	// The algebra that was worked out from the old parameters, worked out
	// again from these. Without this the run is silently the last one's.
	system.evaluateInvariant();
	// A tornado has no dice: its points are the model's values swung one at a
	// time, and a random event keeps its expected-value form throughout.
	drawDisruptions(system, design.seed ?? 1, i, { sample: !design.stats?.tornado });
	return out;
}

/**
 * The occurrences of this realisation's random events.
 *
 * Each disruptive event that samples draws its own times from a stream keyed
 * by the run's seed, the block's name and the realisation's number -- so two
 * events are independent, a replay reproduces the draw, and one realisation's
 * dice do not depend on how many others were run. The rate and the window are
 * read off their slots after the parameters are set, so a rate that is itself
 * a sampled parameter is drawn at this realisation's value; a rate that moves
 * with the clock or the state cannot be a homogeneous process, and the event
 * keeps its expected-value form with a note in the design's statistics.
 * A tornado has no dice by definition and samples nothing.
 */
export function drawDisruptions(system, seed, i, { sample = true } = {}) {
	const layout = system.layout;
	for (const D of layout.events ?? []) {
		if (D.timing !== 'poisson' || !D.sampled || !sample) {
			system.setDisruption(D.index, { sampled: false });
			continue;
		}
		const fixed = (slot) => slot == null || layout.slotClass?.[slot] === 0;
		if (!fixed(D.rateSlot) || !fixed(D.fromSlot) || !fixed(D.untilSlot)) {
			system.setDisruption(D.index, { sampled: false });
			continue;
		}
		const rate = system.slotValue(D.rateSlot);
		const from = D.fromSlot == null ? system.spanStart() : system.slotValue(D.fromSlot);
		const until = D.untilSlot == null ? system.spanEnd() : system.slotValue(D.untilSlot);
		const stream = streamFor(seed, `${D.name}#occurrences#${i}`);
		system.setDisruption(D.index, {
			sampled: true,
			times: sampleOccurrences(rate, Math.max(from, system.spanStart()), Math.min(until, system.spanEnd()), stream),
		});
	}
}

/**
 * One realisation of a probabilistic run, as an ordinary deterministic run.
 *
 * GoldSim's "Run the following Realization only": the chart shows a band and
 * a table says realisation 734 is the one where the dose peaked, and the
 * question is what *that* run looked like -- every series of it, not just the
 * ones the band kept. Rebuilt from the settings, because the draws are a
 * function of the seed and each input's name; the matrix is not needed and
 * need not still be held.
 *
 * @param {object|Project} input
 * @param {object} opts  the run's settings: `seed`, `iterations`, `latin`,
 *   `varied`, or `tornado`
 * @param {number} index  which realisation, from 0
 * @returns {{results: Results, index: number, iterations: number,
 *   values: Array<{name: string, value: number, held: boolean}>}}
 */
export function runRealization(input, opts, index) {
	const project = input instanceof Project ? input : new Project(input);
	const system = buildSystem(project);
	const design = designFor(project, system, opts);
	const i = Math.min(design.iterations - 1, Math.max(0, Math.round(Number(index)) || 0));
	const set = applyPoint(system, design, i);
	const results = run(project, { system, signal: opts.signal });
	return {
		results,
		index: i,
		iterations: design.iterations,
		values: design.plan.map((e, k) => ({
			name: design.names[k],
			value: set[k],
			held: !design.varies(e) || (design.stats.tornado
				? set[k] === design.best[k] : false),
		})),
	};
}

export function runProbabilistic(input, opts = {}) {
	const project = input instanceof Project ? input : new Project(input);
	const started = Date.now();

	const system = buildSystem(project);
	const design = designFor(project, system, opts);
	const { plan, iterations } = design;

	// Which realisations *this* call integrates. The whole run by default; a
	// slice of it when several workers are sharing the job out.
	//
	// **The design is drawn whole whatever the slice is**, which is the only
	// reason splitting a run is safe. Latin hypercube is a statement about the
	// entire column -- the i-th realisation takes the i-th entry of each
	// parameter's own shuffled stratification -- so a worker given
	// realisations 250 to 500 must draw all thousand uniforms from the same
	// seed and then use the ones that are its own. It costs a few hundred
	// thousand random numbers per worker and it is what makes four cores and
	// one core give the same answer, to the last bit, for the same seed. The
	// same holds of a correlation, which is a permutation of the whole column.
	const from = Math.max(0, Math.min(iterations - 1, Math.round(opts.range?.from ?? 0)));
	const to = Math.max(from + 1, Math.min(iterations, Math.round(opts.range?.to ?? iterations)));
	const span = to - from;

	// The values actually set, kept beside the design that chose them: a
	// sensitivity analysis correlates the *value* of an input against the
	// output, and a log-uniform's uniform is its logarithm, which would rank
	// the same and correlate differently. An input held at its best estimate
	// is recorded as that: a column of one number correlates with nothing,
	// which is the right answer for an input that did not vary.
	//
	// This one is the slice's, not the whole run's: it is filled as each
	// realisation is applied, so a worker only knows its own, and whoever
	// shared the job out stitches them back together in order.
	const samples = plan.map(() => new Float64Array(span));
	const apply = (i) => {
		const set = applyPoint(system, design, i);
		for (let k = 0; k < plan.length; k++) samples[k][i - from] = set[k];
	};

	apply(from);
	// `onGrid`, always: see `steps` in ../sim/runner.js. A realisation must be
	// reported at the times every other realisation is reported at, and the
	// solver's own steps are different in each one.
	const first = run(project, { system, signal: opts.signal, onGrid: true });
	const outputs = first.outputs();
	const wanted = opts.keep
		? outputs.map((o, k) => k).filter((k) => opts.keep(outputs[k].block ?? outputs[k].label ?? '', outputs[k]))
		: outputs.map((o, k) => k);
	// The grid the realisations share is the one the model asked for. A run's
	// own time axis can carry more: a corner the solver landed on -- a package
	// failure at a time, a disruptive event's occurrence -- is an output point
	// of that run, and a sampled event puts corners where each realisation's
	// dice fell. Copied as they came, the columns of two realisations would
	// disagree about which row is which time; so each is read at the
	// requested times, which every run's axis contains exactly.
	//
	// **Exactly** is the word that matters, and it is why every realisation is
	// run `onGrid`. A model asking for the solver's own points is handed only
	// the two ends, so its axis contains *none* of these times and the search
	// below falls back to the first step after each one -- a state from a later
	// time than the row it is written into, from a different later time in
	// every realisation. On a decay model with the solver's own error tuned out
	// of the way that is 2% where a grid run is 7e-8. On the grid the search
	// finds every time exactly and the fallback is only ever the extra corners.
	const grid = Array.from(project.timeGrid());
	const times = grid.length;
	const rowsOf = (results) => {
		if (results.t.length === times) return null; // the grid itself
		const idx = new Int32Array(times);
		let k = 0;
		for (let j = 0; j < times; j++) {
			while (k < results.t.length && results.t[k] < grid[j]) k++;
			idx[j] = k < results.t.length ? k : results.t.length - 1;
		}
		return idx;
	};

	const size = estimate({ series: wanted.length, times, iterations });
	if (size.bytes > MOST_BYTES) {
		throw new Error(`${iterations} ${design.stats.tornado ? 'runs' : 'realisations'} of `
			+ `${wanted.length.toLocaleString()} series over ${times} times is ${size.text}, `
			+ 'which is more than a tab can hold. Choose fewer endpoints, or fewer '
			+ `${design.stats.tornado ? 'inputs' : 'realisations'}.`);
	}

	// One array per kept series, laid out realisation-major: `[i * times + j]`
	// is realisation i at time j. That is the order they are written in and the
	// order a quantile reads them in, so neither pass strides.
	// Indexed from the start of the *slice*: `[(i - from) * times + j]`.
	const values = wanted.map(() => new Float64Array(span * times));
	const take = (i, results) => {
		const at = (i - from) * times;
		const rows = rowsOf(results);
		for (let w = 0; w < wanted.length; w++) {
			const v = results.series(outputs[wanted[w]]);
			if (!rows) {
				values[w].set(v.subarray ? v.subarray(0, times) : v.slice(0, times), at);
			} else {
				for (let j = 0; j < times; j++) values[w][at + j] = v[rows[j]];
			}
		}
	};
	take(from, first);
	opts.onProgress?.(1, span);

	let failed = 0;
	const trouble = [];
	for (let i = from + 1; i < to; i++) {
		if (opts.signal?.aborted) break;
		apply(i);
		try {
			const r = run(project, { system, signal: opts.signal, onGrid: true });
			take(i, r);
		} catch (e) {
			// One realisation in a thousand can land on a combination the
			// solver cannot carry -- a rate that makes the model far stiffer
			// than any single value does. That is a fact about the model worth
			// reporting, not a reason to lose the other 999.
			failed++;
			// Named by its number in the whole run, not in this slice: "the
			// 734th realisation" means something to the reader and "the 22nd
			// of worker three" does not.
			if (trouble.length < 5) trouble.push(`realisation ${i + 1}: ${e.message}`);
			const at = (i - from) * times;
			for (let w = 0; w < wanted.length; w++) values[w].fill(NaN, at, at + times);
		}
		opts.onProgress?.(i - from + 1, span);
	}

	return {
		t: Float64Array.from(grid),
		outputs: wanted.map((k) => outputs[k]),
		values,
		plan,
		samples,
		iterations,
		// Which realisations these are, so a caller sharing the job out can put
		// them back in order.
		from,
		to,
		stats: {
			failed,
			trouble,
			ms: Date.now() - started,
			...design.stats,
		},
	};
}

/**
 * The band at each time: the quantiles asked for, across realisations.
 *
 * Sorted per time rather than interpolated between order statistics, which is
 * the definition anyone checking this by hand would use. Realisations that
 * failed are NaN and are left out, so a band is over what actually ran and the
 * count says how many that was. A `mask` -- 1 to use a realisation, 0 not to
 * -- leaves out the rest, which is how a band is drawn over the categories of
 * realisation a reader has chosen to keep.
 *
 * @returns {{q: number, y: Float64Array}[]} in the order asked for
 */
/**
 * One series' realisations, the way a result file stores them.
 *
 * A run holds them one realisation at a time -- `values[i * times + j]` -- which
 * is the order they are produced in and the order every statistic here reads
 * them in. A result file stores the same numbers one *time* at a time, with the
 * realisations varying fastest: `out[j * iterations + i]`, a matrix of `times`
 * rows and `iterations` columns. That is what Ecolego writes and what the result
 * browser reads, and getting it the wrong way round produces a file that opens,
 * draws, and is wrong -- every "realisation" a slice across time and every
 * "time" a slice across realisations. Hence a named function with a test.
 *
 * Narrowed to float32 on the way, which is what halves a matrix that is
 * `iterations` times the size of the series it came from.
 */
export function timeMajor(values, times, iterations, out = new Float32Array(times * iterations)) {
	for (let i = 0; i < iterations; i++) {
		const from = i * times;
		for (let j = 0; j < times; j++) out[j * iterations + i] = values[from + j];
	}
	return out;
}

export function quantiles(values, times, iterations, qs = [0.05, 0.5, 0.95], mask = null) {
	const out = qs.map((q) => ({ q, y: new Float64Array(times) }));
	const column = new Float64Array(iterations);
	for (let j = 0; j < times; j++) {
		let n = 0;
		for (let i = 0; i < iterations; i++) {
			if (mask && !mask[i]) continue;
			const v = values[i * times + j];
			if (Number.isFinite(v)) column[n++] = v;
		}
		const slice = column.subarray(0, n);
		slice.sort();
		for (let k = 0; k < qs.length; k++) {
			out[k].y[j] = n ? slice[Math.min(n - 1, Math.max(0, Math.round(qs[k] * (n - 1))))] : NaN;
		}
	}
	return out;
}

/**
 * The two intervals that belong to the *median*, at each time, as order
 * statistics off the sorted realisations.
 *
 * Neither has the closed form its mean-shaped twin does. A standard error is
 * `sd/√n` because the mean of a sample is a sum; the median is not, and its
 * error is `1 / (2·f(m)·√n)` -- which wants the density of the output at its
 * own median, a thing nobody has. So both are read off the sample instead:
 *
 * * `errLo`..`errHi` is the median's own 95% interval, the ranks
 *   `(n-1)/2 ∓ z√n/2`. That is the distribution-free interval for a median --
 *   the sign test inverted, with the normal approximation to the binomial --
 *   and for a large sample it is the asymptotic error above, arrived at
 *   without assuming any shape. Rounded outwards, so the coverage is at least
 *   the nominal one rather than just under it.
 * * `bodyLo`..`bodyHi` is where the realisations are: the middle 68% of them,
 *   the ranks at 0.1587 and 0.8413. For a normal sample that is the median
 *   ± one standard deviation; for a skewed one it is the honest version.
 *
 * Both come out **asymmetric** for a skewed output, and that is the point. A
 * dose whose logarithm is normal has far more room above its median than
 * below it, and the same number either side would say otherwise.
 *
 * Costs a sort of each column, as `quantiles` does, over the realisations the
 * mask keeps and the ones that are finite -- the same set every other statistic
 * about this band was taken over.
 */
export function medianSpread(values, times, iterations, z = 1.959964, mask = null) {
	const errLo = new Float64Array(times);
	const errHi = new Float64Array(times);
	const bodyLo = new Float64Array(times);
	const bodyHi = new Float64Array(times);
	const column = new Float64Array(iterations);
	for (let j = 0; j < times; j++) {
		let n = 0;
		for (let i = 0; i < iterations; i++) {
			if (mask && !mask[i]) continue;
			const v = values[i * times + j];
			if (Number.isFinite(v)) column[n++] = v;
		}
		if (!n) {
			errLo[j] = errHi[j] = bodyLo[j] = bodyHi[j] = NaN;
			continue;
		}
		const slice = column.subarray(0, n);
		slice.sort();
		const at = (k) => slice[Math.min(n - 1, Math.max(0, k))];
		const half = (z * Math.sqrt(n)) / 2;
		errLo[j] = at(Math.ceil((n - 1) / 2 - half));
		errHi[j] = at(Math.floor((n - 1) / 2 + half));
		bodyLo[j] = at(Math.round(0.158655 * (n - 1)));
		bodyHi[j] = at(Math.round(0.841345 * (n - 1)));
	}
	return { errLo, errHi, bodyLo, bodyHi };
}

/** The mean at each time, over the realisations that ran. */
export function meanOf(values, times, iterations, mask = null) {
	const out = new Float64Array(times);
	for (let j = 0; j < times; j++) {
		let sum = 0;
		let n = 0;
		for (let i = 0; i < iterations; i++) {
			if (mask && !mask[i]) continue;
			const v = values[i * times + j];
			if (Number.isFinite(v)) { sum += v; n++; }
		}
		out[j] = n ? sum / n : NaN;
	}
	return out;
}
