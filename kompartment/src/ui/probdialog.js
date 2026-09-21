/**
 * Starting a probabilistic run.
 *
 * A run over a model's distributions is not something to begin by accident.
 * An imported assessment says `<no-simulations>1000</no-simulations>`, and
 * model B takes 50 seconds for one integration of its 23,436
 * states -- so a thousand of them is fourteen hours, and the one thing this
 * dialog must do is say so before anybody presses anything.
 *
 * It therefore leads with the arithmetic: how many values will be drawn, how
 * many realisations of what, how much memory the answer takes and roughly how
 * long it will run, measured from the deterministic run that has already
 * happened rather than guessed. Ecolego's own numbers -- the count, the
 * sampling method and the seed -- are the defaults, because they came from the
 * file.
 */

import { el } from './parts.js';
import { openModal } from './modal.js';
import { describePDF } from '../domain/pdf.js';
import { estimate, MOST_BYTES, slotName } from '../sim/probabilistic.js';
import { describeCorrelation } from '../domain/correlate.js';

/** A duration a person would say out loud. */
export function howLong(ms) {
	if (!Number.isFinite(ms) || ms <= 0) return null;
	// Under a second, say so in milliseconds. Rounding a 19-millisecond
	// integration up to "1 second" is not a harmless simplification here: the
	// total beside it is that same figure times the realisation count, and a
	// reader who multiplies the two numbers on the screen has to get the third.
	if (ms < 1000) return `${ms < 10 ? ms.toFixed(1) : Math.round(ms)} ms`;
	const s = ms / 1000;
	const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;
	if (s < 90) return plural(Math.round(s), 'second');
	const m = s / 60;
	if (m < 90) return plural(Math.round(m), 'minute');
	return `${(m / 60).toFixed(1)} hours`;
}

/**
 * @param {object} opts
 * @param {Array} opts.plan        what would be sampled, from `samplingPlan`
 * @param {object} opts.simulation the model's own settings, as the defaults
 * @param {number} opts.series     how many series a run produces
 * @param {number} opts.times      how many output times
 * @param {number|null} opts.lastSolveMs  what one integration took, if known
 * @param {string[]} opts.endpoints the model's endpoint list, if it has one
 * @param {number|null} [opts.endpointSeries] how many *series* those endpoints
 *   come to -- an endpoint is a block, and a block indexed by four nuclides is
 *   four series
 * @param {number} [opts.workers]  how many cores the run will be shared over
 * @param {((done: (names: string[]) => void) => void)|null} [opts.onChooseEndpoints]
 *   opens the picker that decides the list, and calls back with the new one
 * @param {(choice: object) => void} opts.onRun
 * @param {(() => void)|null} [opts.onDiscard] throws away the sample already
 *   held, where there is one. Null when there is not.
 */
export function openProbabilisticDialog({
	plan, simulation, series, times, lastSolveMs = null, endpoints = [],
	endpointSeries = null, workers = 1, onChooseEndpoints = null, onDiscard = null, onRun,
}) {
	// A local copy of the list and of what it comes to in series, because the
	// picker below can change both while this dialog is open and the estimate
	// on screen has to follow. An endpoint is a block; a block indexed by four
	// nuclides is four series, which is why the count cannot be worked out
	// here from the names alone.
	let kept = [...endpoints];
	let keptSeries = endpointSeries;
	let iterations = Math.max(1, Math.round(simulation?.iterations ?? 1000));
	let seed = Math.round(simulation?.seed ?? 1);
	let latin = simulation?.sampling !== 'random';
	// Which of the sampled inputs actually vary. `null` is all of them, which
	// is the ordinary run; a set is a *partial* run -- see the note beside the
	// control below. Remembered on the model, the way the realisation count
	// and the seed are, so a comparison can be repeated.
	const everything = plan.map(slotName);
	let varied = Array.isArray(simulation?.partial)
		? new Set(simulation.partial.filter((n) => everything.includes(n)))
		: null;
	let showPartial = varied != null;
	let partialQuery = '';
	// Keeping every series of every realisation is what makes this expensive,
	// and an assessment already says which series it is about. So the endpoint
	// list is the default where there is one.
	let onlyEndpoints = endpoints.length > 0;
	// Inputs that move together. The model's, edited here and saved with the
	// run's other settings; see ../domain/correlate.js for what a pair and a
	// group are.
	let correlations = (Array.isArray(simulation?.correlations) ? simulation.correlations : [])
		.map((c) => ({ ...c }));
	let showCorrelations = correlations.length > 0;
	// The parameters with more than one sampled index, which is what a group
	// correlates.
	const groupable = [...new Set(plan.filter((e) => Object.keys(e.index ?? {}).length).map((e) => e.name))]
		.filter((name) => plan.filter((e) => e.name === name).length > 1);

	const modal = openModal({
		wide: true,
		title: 'Probabilistic run',
		subtitle: 'The model integrated once per realisation, over its distributions',
		build: (body) => {
			// An endpoint is a *block*, and a block on the radionuclide list is
			// one series per nuclide -- so counting the endpoints counted
			// `Dose` as one where the run produces four. The dialog said 305 MB
			// and the run refused at 1.2 GB, which is a hard thing to act on
			// when the two numbers are four times apart and neither says why.
			const keeping = onlyEndpoints
				? (keptSeries ?? Math.min(series, kept.length))
				: series;
			const size = estimate({ series: keeping, times, iterations });
			// What a *file* of it would be, which is the number that surprises
			// people: the realisations are written as float32, so half what
			// the run holds -- and still 2.8 GB for a large assessment.
			const asFile = estimate({ series: keeping, times, iterations, precision: 'float32' });
			// What asking for fewer costs later. A series the run did not keep
			// cannot be charted as a band, exported as realisations, or asked
			// about in *What drove it* -- so the trade is worth stating before
			// it is made rather than discovered afterwards.
			const dropped = Math.max(0, series - keeping);
			const perRun = lastSolveMs;
			// Over however many cores the run will actually use. Not a promise
			// -- the browser decides what it can start, and a machine with
			// other work on it will not give all of them -- but it is the
			// number the estimate is made with, so it is the number to show.
			const cores = Math.max(1, Math.min(workers, iterations));
			const total = perRun ? (perRun * iterations) / cores : null;
			const tooBig = size.bytes > MOST_BYTES;

			// --- what it would do, before what to set.
			const kinds = new Map();
			for (const e of plan) kinds.set(e.kind ?? e.spec?.kind, (kinds.get(e.kind ?? e.spec?.kind) ?? 0) + 1);
			const summary = el('div', { className: 'prob-summary' },
				el('p', {},
					el('b', {}, `${plan.length.toLocaleString()} value${plan.length === 1 ? '' : 's'}`),
					` drawn per realisation, from `,
					[...kinds].map(([k, v]) => `${v} ${k}`).join(', '),
					'.'),
				el('p', {},
					el('b', {}, `${iterations.toLocaleString()} realisation${iterations === 1 ? '' : 's'}`),
					` of `,
					el('b', {}, `${keeping.toLocaleString()} series`),
					` over ${times.toLocaleString()} times — `,
					el('b', { className: tooBig ? 'is-bad' : '' }, size.text),
					' of results.'),
				el('p', { className: 'hint' },
					'Written out, every realisation of those is about ',
					el('b', {}, asFile.text),
					' — they are saved as float32, which is half what the run holds and '
					+ 'still finer than a sample of this size can justify.'),
				// A model set to the solver's own points is the one case where
				// a sample cannot report what a single run reports, and it is
				// worth saying before the run rather than leaving the reader to
				// notice that the axis changed.
				simulation?.spacing === 'solver' || simulation?.spacing === 'both'
					? el('p', { className: 'hint' },
						'This model reports ',
						el('b', {}, simulation.spacing === 'solver'
							? 'the solver’s own points' : 'a grid and the solver’s own points'),
						'. A sample cannot: every realisation steps differently, so there '
						+ 'would be no shared time to take a percentile down. The '
						+ `realisations are reported on the grid — ${times.toLocaleString()} `
						+ 'times — and the solver is asked for exactly those, so they are as '
						+ 'accurate as any other run. Single runs are unaffected.')
					: null,
				dropped
					? el('p', { className: 'prob-warn' },
						el('b', {}, `${dropped.toLocaleString()} series`),
						' will not be kept. Those keep their single deterministic curve, '
						+ 'but they cannot be drawn as a band, exported as realisations, '
						+ 'or asked about under ',
						el('i', {}, 'What drove it'),
						' — running again is the only way back to them.')
					: null,
				total
					? el('p', {},
						'One integration took ',
						el('b', {}, howLong(perRun)),
						', so this is about ',
						el('b', { className: total > 30 * 60 * 1000 ? 'is-bad' : '' }, howLong(total)),
						cores > 1
							? ` of solving, over ${cores} cores.`
							: ' of solving.')
					: el('p', { className: 'hint' },
						'Run the model once first and this will say how long it is likely '
						+ 'to take.'),
			);
			body.append(summary);

			if (tooBig) {
				body.append(el('p', { className: 'prob-warn' },
					`That is more than a tab can hold. Keep fewer series — the model's `
					+ `endpoints rather than everything — or ask for fewer realisations.`));
			}

			// --- the numbers.
			const numberRow = (label, get, set, hint) => {
				const input = el('input', {
					type: 'text', className: 'mono', value: String(get()), spellcheck: false,
				});
				input.addEventListener('change', () => {
					const v = Number(input.value);
					if (Number.isFinite(v)) { set(v); modal.refresh(); } else input.value = String(get());
				});
				return el('div', { className: 'pdf-row' },
					el('label', { title: hint }, label), input);
			};
			body.append(numberRow('Realisations', () => iterations,
				(v) => { iterations = Math.max(1, Math.round(v)); },
				'How many times the model is integrated.'));
			body.append(numberRow('Seed', () => seed, (v) => { seed = Math.round(v); },
				'The run is a function of this and nothing else: the same seed gives '
				+ 'the same realisations, which is what makes a result quotable.'));

			const how = el('select', {});
			for (const [v, text, why] of [
				['latin', 'Latin hypercube', 'One draw from each of N equal slices of every '
					+ 'distribution, shuffled — so the range is covered evenly instead of '
					+ 'clumping. What an assessment uses, and what the file says.'],
				['random', 'Independent draws', 'Each value drawn on its own. Simpler, and '
					+ 'needs more realisations to reach the same coverage.'],
			]) {
				how.append(el('option', { value: v, selected: latin === (v === 'latin'), title: why }, text));
			}
			how.addEventListener('change', () => { latin = how.value === 'latin'; });
			body.append(el('div', { className: 'pdf-row' }, el('label', {}, 'Sampling'), how));

			// --- a partial run: vary some of them, hold the rest.
			//
			// Worth its own control because of what it answers. "How much of
			// this spread is that one parameter?" cannot be read off a
			// correlation -- a correlation ranks what the sample happens to
			// show. Run it twice, once with everything varying and once with
			// one input held at its value, and the difference between the two
			// bands *is* the answer.
			//
			// That only works because a parameter's draws do not depend on
			// which other parameters were sampled: the held ones are held, and
			// every other input takes exactly the numbers it took in the full
			// run. See `streamFor` in ../domain/sample.js, which is what makes
			// this a comparison rather than a second experiment.
			if (plan.length > 1) {
				const box = el('input', { type: 'checkbox', checked: showPartial });
				box.addEventListener('change', () => {
					showPartial = box.checked;
					if (showPartial && !varied) varied = new Set(everything);
					if (!showPartial) varied = null;
					modal.refresh();
				});
				body.append(el('div', { className: 'pdf-row' },
					el('label', { title: 'Hold some of the sampled inputs at the value the '
						+ 'model holds and vary the rest. Everything that does vary takes '
						+ 'exactly the numbers it takes in a full run, so the two are '
						+ 'comparable.' }, 'Vary only some'), box));

				if (showPartial) {
					const chosen = varied ?? new Set(everything);
					const q = partialQuery.trim().toLowerCase();
					const found = q ? everything.filter((n) => n.toLowerCase().includes(q)) : everything;
					const search = el('input', {
						type: 'search', className: 'ep-search', value: partialQuery,
						placeholder: `Search ${everything.length.toLocaleString()} sampled inputs`,
						'aria-label': 'Search the sampled inputs',
					});
					search.addEventListener('input', () => { partialQuery = search.value; modal.refresh(); });
					const all = el('button', { type: 'button', className: 'ghost' }, 'All');
					all.addEventListener('click', () => { varied = new Set(everything); modal.refresh(); });
					const none = el('button', { type: 'button', className: 'ghost' }, 'None');
					none.addEventListener('click', () => { varied = new Set(); modal.refresh(); });
					body.append(el('div', { className: 'pdf-row pdf-row-wide' },
						el('label', {}, 'Varying'), search, all, none));

					const list = el('div', { className: 'prob-list' });
					for (const name of found.slice(0, 200)) {
						const tick = el('input', { type: 'checkbox', checked: chosen.has(name) });
						tick.addEventListener('change', () => {
							if (tick.checked) chosen.add(name); else chosen.delete(name);
							varied = chosen;
							modal.refresh();
						});
						list.append(el('label', { className: 'prob-item is-pick' },
							tick, el('code', {}, name)));
					}
					if (found.length > 200) {
						list.append(el('div', { className: 'prob-more' },
							`Showing 200 of ${found.length.toLocaleString()} — narrow the search.`));
					}
					body.append(list);
					body.append(el('p', { className: 'prob-more' },
						`${chosen.size.toLocaleString()} of ${everything.length.toLocaleString()} `
						+ 'varying; the rest stay at the value the model holds.'));
				}
			}

			// --- correlations: inputs the model says move together.
			//
			// A rank correlation between two sampled inputs, or across every
			// index of one parameter. Applied as a permutation of the draws
			// (Iman and Conover), so each input keeps exactly the values it
			// would have had and only which realisation gets which changes;
			// inputs outside a pair are untouched.
			if (plan.length > 1) {
				const box = el('input', { type: 'checkbox', checked: showCorrelations });
				box.addEventListener('change', () => { showCorrelations = box.checked; modal.refresh(); });
				body.append(el('div', { className: 'pdf-row' },
					el('label', { title: 'Make two sampled inputs, or every index of one '
						+ 'parameter, move together with a chosen rank correlation. The '
						+ 'sorption coefficients of one element in several compartments are '
						+ 'the usual case.' }, 'Correlate inputs'), box));
				if (showCorrelations) {
					const list = el('div', { className: 'prob-list' });
					const rInput = (c) => {
						const r = el('input', { type: 'text', className: 'mono corr-r', value: String(c.r ?? 0.8) });
						r.addEventListener('change', () => {
							const v = Number(r.value);
							if (Number.isFinite(v) && v >= -1 && v <= 1) c.r = v; else r.value = String(c.r);
						});
						return r;
					};
					const pick = (value, options, onPick) => {
						const sel = el('select', { className: 'corr-pick' });
						if (!options.includes(value)) sel.append(el('option', { value, selected: true }, value || '—'));
						for (const o of options.slice(0, 400)) sel.append(el('option', { value: o, selected: o === value }, o));
						sel.addEventListener('change', () => onPick(sel.value));
						return sel;
					};
					correlations.forEach((c, i) => {
						const del = el('button', { type: 'button', className: 'ghost icon', title: 'Remove' }, '×');
						del.addEventListener('click', () => { correlations.splice(i, 1); modal.refresh(); });
						const row = el('div', { className: 'prob-item corr-row', title: describeCorrelation(c) });
						if (c.group != null) {
							row.append(el('span', { className: 'corr-kind' }, 'every index of'),
								pick(c.group, groupable, (v) => { c.group = v; }),
								el('span', { className: 'corr-kind' }, 'at r ='), rInput(c), del);
						} else {
							row.append(pick(c.a ?? '', everything, (v) => { c.a = v; }),
								el('span', { className: 'corr-kind' }, 'with'),
								pick(c.b ?? '', everything, (v) => { c.b = v; }),
								el('span', { className: 'corr-kind' }, 'at r ='), rInput(c), del);
						}
						list.append(row);
					});
					const addPair = el('button', { type: 'button', className: 'ghost' }, 'Add a pair');
					addPair.addEventListener('click', () => {
						correlations.push({ a: everything[0], b: everything[Math.min(1, everything.length - 1)], r: 0.8 });
						modal.refresh();
					});
					const addGroup = el('button', { type: 'button', className: 'ghost', disabled: !groupable.length,
						title: groupable.length ? 'Every sampled index of one parameter, pairwise'
							: 'No parameter here has more than one sampled index.' }, 'Add a group');
					addGroup.addEventListener('click', () => {
						correlations.push({ group: groupable[0], r: 0.9 });
						modal.refresh();
					});
					body.append(list, el('div', { className: 'pdf-row' }, addPair, addGroup));
					body.append(el('p', { className: 'prob-more' },
						'Rank (Spearman) correlations. A set that no real inputs could have — A with B '
						+ 'at 0.9, B with C at 0.9, A with C at −0.9 — is moved to the nearest one that '
						+ 'is possible, and the run says so.'));
				}
			}

			// What is kept, and where that is decided. The row is here even
			// with no endpoints chosen yet: the tick box alone said how many
			// there were and nothing said *which*, and the picker is under
			// Export, which is nowhere near this dialog.
			{
				const box = el('input', {
					type: 'checkbox', checked: onlyEndpoints, disabled: !kept.length,
				});
				box.addEventListener('change', () => { onlyEndpoints = box.checked; modal.refresh(); });
				const row = el('div', { className: 'pdf-row prob-keep' },
					el('label', { title: kept.length
						? 'The blocks this model was saved as being about. Keeping every '
							+ 'series of every realisation is what makes a probabilistic '
							+ 'run expensive.'
						: 'This model has no endpoint list yet, so every series of every '
							+ 'realisation would be kept. Choose… picks the blocks.' },
					kept.length
						? `Keep only the ${kept.length} endpoint${kept.length === 1 ? '' : 's'}`
						: 'Keep only the endpoints'),
					box);
				if (onChooseEndpoints) {
					const pick = el('button', {
						type: 'button', className: 'ghost prob-endpoints',
						title: 'Pick which blocks the run keeps. A block brings every index '
							+ 'of it, and the choice is saved with the model.',
					}, kept.length ? 'Choose\u2026' : 'Choose blocks\u2026');
					pick.addEventListener('click', () => onChooseEndpoints((names, count = null) => {
						kept = [...(names ?? [])];
						keptSeries = count;
						onlyEndpoints = kept.length > 0;
						modal.refresh();
					}));
					row.append(pick);
				}
				body.append(row);
			}

			// --- what will be sampled, so it can be checked.
			if (plan.length) {
				const list = el('div', { className: 'prob-list' });
				for (const e of plan.slice(0, 12)) {
					const where = Object.values(e.index ?? {});
					list.append(el('div', { className: 'prob-item' },
						el('code', {}, `${e.name}${where.length ? `[${where.join(' · ')}]` : ''}`),
						el('span', {}, e.spec ? describePDF(e.spec) : e.kind)));
				}
				if (plan.length > 12) {
					list.append(el('div', { className: 'prob-more' },
						`and ${(plan.length - 12).toLocaleString()} more`));
				}
				body.append(el('details', { className: 'prob-plan' },
					el('summary', {}, 'What will be sampled'), list));
			}

			const go = el('button', {
				type: 'button', className: 'primary', disabled: tooBig,
			}, 'Run');
			go.addEventListener('click', () => {
				modal.close();
				onRun({
					iterations, seed, latin,
					blocks: onlyEndpoints && kept.length ? kept : null,
					varied: varied ? [...varied] : null,
					correlations: showCorrelations ? correlations.map((c) => ({ ...c })) : [],
				});
			});
			const cancel = el('button', { type: 'button', className: 'ghost' }, 'Cancel');
			cancel.addEventListener('click', () => modal.close());
			// The way out of a sample, beside the way into one. A reader who
			// opens this dialog is thinking about the realisations, which is
			// where "I am done with the last lot" is worth offering.
			const foot = el('div', { className: 'pdf-foot' },
				el('span', { className: 'pdf-note' },
					'Stop is available while it runs, and keeps what has finished.'));
			if (onDiscard) {
				const drop = el('button', { type: 'button', className: 'ghost' }, 'Discard sample');
				drop.title = 'Throw away the realisations already held, without running. '
					+ 'The model is not touched.';
				drop.addEventListener('click', () => { modal.close(); onDiscard(); });
				foot.append(drop);
			}
			foot.append(cancel, go);
			body.append(foot);
		},
	});
	return modal;
}

/**
 * Which realisation to run again in full.
 *
 * GoldSim's "Run the following Realization only". A number rather than a
 * pick from a list: the reader has one in mind, from a table or a category,
 * and a list of a thousand is not a way to say it.
 */
export function openReplayDialog({ iterations, seed, suggested = 1, onRun }) {
	let which = Math.min(iterations, Math.max(1, Math.round(suggested)));
	const modal = openModal({
		title: 'Replay a realisation',
		subtitle: `One of the ${iterations.toLocaleString()} realisations of seed ${seed}, `
			+ 'run again as an ordinary run — every series of it, not only the ones the band kept',
		build: (body) => {
			const input = el('input', { type: 'text', className: 'mono', value: String(which) });
			input.addEventListener('change', () => {
				const v = Math.round(Number(input.value));
				if (Number.isFinite(v) && v >= 1 && v <= iterations) which = v; else input.value = String(which);
			});
			body.append(el('div', { className: 'pdf-row' },
				el('label', {}, `Realisation (1–${iterations.toLocaleString()})`), input));
			body.append(el('p', { className: 'hint' },
				'Rebuilt from the seed and the input names, not read back from the run: the same '
				+ 'settings give the same draws, so this is that realisation to the last digit, and '
				+ 'the values it used are listed with the result.'));
			const go = el('button', { type: 'button', className: 'primary' }, 'Run');
			go.addEventListener('click', () => { modal.close(); onRun(which - 1); });
			const cancel = el('button', { type: 'button', className: 'ghost' }, 'Cancel');
			cancel.addEventListener('click', () => modal.close());
			body.append(el('div', { className: 'pdf-foot' }, el('span', { className: 'pdf-note' }, ''), cancel, go));
		},
	});
	return modal;
}

/**
 * The percentiles the bands are drawn at, as pairs.
 *
 * Typed as "5–95, 25–75": a band is two percentiles, and asking for them as a
 * pair is asking for what will be drawn. Parsed to the sorted list of
 * probabilities the worker wants; the median is always in it.
 */
export function parseBands(text) {
	const out = new Set([0.5]);
	for (const part of String(text ?? '').split(/[,;]+/)) {
		const m = part.trim().match(/^(\d+(?:\.\d+)?)\s*[-–—]\s*(\d+(?:\.\d+)?)$/);
		if (!m) continue;
		for (const v of [Number(m[1]) / 100, Number(m[2]) / 100]) {
			if (v > 0 && v < 1) out.add(v);
		}
	}
	return [...out].sort((a, b) => a - b);
}

/** The pairs a percentile list draws, outermost first: (p, 1−p) for each p below the median. */
export function bandPairs(percentiles) {
	const ps = [...new Set(percentiles)].filter((p) => p > 0 && p < 1).sort((a, b) => a - b);
	const pairs = [];
	for (const p of ps) {
		if (p >= 0.5) break;
		const mirror = ps.find((q) => Math.abs(q - (1 - p)) < 1e-9);
		if (mirror != null) pairs.push([p, mirror]);
	}
	return pairs;
}

/** The pairs as text, for the field. */
export function bandsText(percentiles) {
	return bandPairs(percentiles).map(([a, b]) => `${Math.round(a * 1000) / 10}–${Math.round(b * 1000) / 10}`).join(', ');
}

export function openBandsDialog({ percentiles, showMean = false, onApply }) {
	let text = bandsText(percentiles) || '5–95, 25–75';
	let mean = !!showMean;
	const modal = openModal({
		title: 'Bands',
		subtitle: 'Which percentiles the probabilistic bands are drawn at',
		build: (body) => {
			const input = el('input', { type: 'text', className: 'mono', value: text, placeholder: '5–95, 25–75' });
			input.addEventListener('input', () => { text = input.value; });
			body.append(el('div', { className: 'pdf-row pdf-row-wide' }, el('label', {}, 'Pairs'), input));
			const box = el('input', { type: 'checkbox', checked: mean });
			box.addEventListener('change', () => { mean = box.checked; });
			body.append(el('div', { className: 'pdf-row' },
				el('label', { title: 'Draw the mean of the realisations as a dashed line beside the '
					+ 'median. For a skewed output the two are far apart, and which one a '
					+ 'reader means is worth seeing.' }, 'Show the mean'), box));
			body.append(el('p', { className: 'hint' },
				'Outermost pair first is the convention, but any order works; the median is '
				+ 'always drawn as the line. GoldSim’s default set is 1–99, 5–95, 15–85, 25–75, 35–65, 45–55.'));
			const go = el('button', { type: 'button', className: 'primary' }, 'Apply');
			go.addEventListener('click', () => {
				const list = parseBands(text);
				if (list.length < 3) return;
				modal.close();
				onApply({ percentiles: list, showMean: mean });
			});
			const cancel = el('button', { type: 'button', className: 'ghost' }, 'Cancel');
			cancel.addEventListener('click', () => modal.close());
			body.append(el('div', { className: 'pdf-foot' },
				el('span', { className: 'pdf-note' }, 'Saved with the model; redrawn at once when a run stands.'),
				cancel, go));
		},
	});
	return modal;
}
