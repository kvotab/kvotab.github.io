/**
 * Global sensitivity: choosing a method and reading its answer.
 *
 * The methods are ../domain/gsa.js's -- GlobalSensitivity.jl's designed ones,
 * and what SALib adds to them (../domain/salib.js), each an experiment of its
 * own over the model's distributions. The setup
 * dialog prices the design before anything runs, since the methods differ by
 * orders of magnitude in what they cost: a fractional factorial of fifteen
 * inputs is 32 runs and Sobol's indices with a thousand samples are 17,000.
 * The result dialog reads the runs for any output and any statistic without
 * running anything again, the way the tornado's does.
 */

import { el } from './parts.js';
import { openModal } from './modal.js';
import { fmtTime } from '../domain/timeseries.js';
import { STATS, STAT_LABEL } from '../domain/categories.js';
import { GSA_METHODS, GSA_METHOD_IDS, gsaOptions, gsaRuns, gsaRefusal } from '../domain/gsa.js';
import { howLong } from './probdialog.js';
import { inputName, paintCurves } from './sensdialog.js';
import { coresRow } from './cores.js';
import { dialogInfo } from './dialoginfo.js';

/**
 * @param {object} opts
 * @param {number} opts.inputs        how many factors the design would vary
 * @param {number} [opts.grouped]     how many of them are correlation groups
 * @param {number} [opts.correlated]  correlations between factors the model gives
 * @param {number|null} opts.lastSolveMs
 * @param {number} opts.workers       cores when the tool decides
 * @param {number|null} [opts.cores]  the reader's own number
 * @param {string[]} opts.endpoints
 * @param {object} opts.simulation    the model's settings: its seed, and the last choice
 * @param {(choice: object) => void} opts.onRun
 */
export function openGsaSetup({
	inputs, grouped = 0, correlated = 0, lastSolveMs = null, workers = 1, cores: chosen = null,
	endpoints = [], simulation = {}, onRun,
}) {
	const last = simulation.gsa ?? {};
	let method = GSA_METHODS[last.method] ? last.method : 'morris';
	// Settings per method, so switching between two does not lose either.
	const settings = {};
	for (const id of GSA_METHOD_IDS) settings[id] = gsaOptions(id, inputs, id === method ? last.options : {});
	let seed = Math.round(Number(last.seed ?? simulation.seed ?? 1)) || 1;
	let chosenCores = chosen;
	let onlyEndpoints = endpoints.length > 0;

	const modal = openModal({
		info: dialogInfo('gsa'),
		wide: true,
		title: 'Global sensitivity',
		subtitle: 'An experiment over the distributions, designed for one question',
		build: (body) => {
			const info = GSA_METHODS[method];
			const o = settings[method];
			const runs = gsaRuns(method, inputs, o);
			const refused = gsaRefusal(method, inputs, o);
			const on = Math.max(1, Math.min(chosenCores ?? workers, runs));
			const total = lastSolveMs ? (lastSolveMs * runs) / on : null;

			const pick = el('select', {});
			for (const id of GSA_METHOD_IDS) {
				pick.append(el('option', { value: id, selected: id === method, title: GSA_METHODS[id].blurb },
					GSA_METHODS[id].label));
			}
			pick.addEventListener('change', () => { method = pick.value; modal.refresh(); });
			body.append(el('div', { className: 'pdf-row pdf-row-wide' }, el('label', {}, 'Method'), pick));
			body.append(el('p', { className: 'hint' }, info.blurb));

			for (const [key, label, , kind, title, choices] of info.options) {
				let input;
				if (kind === 'switch') {
					input = el('input', { type: 'checkbox', checked: !!o[key] });
					input.addEventListener('change', () => { o[key] = input.checked; modal.refresh(); });
				} else if (kind === 'choice') {
					input = el('select', {});
					for (const [v, text] of choices) input.append(el('option', { value: v, selected: v === o[key] }, text));
					input.addEventListener('change', () => { o[key] = input.value; modal.refresh(); });
				} else {
					input = el('input', { type: 'text', className: 'mono', value: String(o[key]), spellcheck: false });
					input.addEventListener('change', () => {
						const v = Number(input.value);
						if (Number.isFinite(v)) o[key] = kind === 'int' ? Math.round(v) : v;
						modal.refresh();
					});
				}
				body.append(el('div', { className: 'pdf-row' }, el('label', { title }, label), input));
			}

			const seedBox = el('input', { type: 'text', className: 'mono', value: String(seed), spellcheck: false });
			seedBox.addEventListener('change', () => {
				const v = Math.round(Number(seedBox.value));
				if (Number.isFinite(v)) seed = v;
				modal.refresh();
			});
			body.append(el('div', { className: 'pdf-row' },
				el('label', { title: 'The design is a function of this and nothing else, so the same seed '
					+ 'gives the same runs.' }, 'Seed'), seedBox));
			if (endpoints.length) {
				const box = el('input', { type: 'checkbox', checked: onlyEndpoints });
				box.addEventListener('change', () => { onlyEndpoints = box.checked; });
				body.append(el('div', { className: 'pdf-row' },
					el('label', { title: 'Keep only the series the model names as its endpoints.' },
						`Keep only the ${endpoints.length} endpoints`), box));
			}
			body.append(coresRow({
				auto: workers, value: chosenCores,
				onChange: (n) => { chosenCores = n; modal.refresh(); },
			}));

			const facts = [
				el('p', {},
					el('b', {}, `${inputs.toLocaleString()} input${inputs === 1 ? '' : 's'}`),
					grouped ? ` (${grouped} of them correlation groups, each moved as one)` : '',
					' varied; ',
					el('b', { className: refused ? 'is-bad' : '' }, refused ? 'no design' : `${runs.toLocaleString()} runs`),
					'.'),
				refused ? el('p', { className: 'prob-warn' }, refused) : null,
				!refused && total
					? el('p', {}, 'One integration took ', el('b', {}, howLong(lastSolveMs)),
						', so this is about ', el('b', { className: total > 30 * 60 * 1000 ? 'is-bad' : '' }, howLong(total)),
						on > 1 ? ` of solving, over ${on} cores.` : ' of solving.')
					: null,
				correlated && method !== 'shapley'
					? el('p', { className: 'hint' },
						`The model correlates ${correlated} pair${correlated === 1 ? '' : 's'} of inputs. `
						+ `${info.short} assumes independent inputs and samples them so; Shapley effects `
						+ 'are the method that honours the correlations.')
					: null,
			];
			body.append(el('div', { className: 'prob-summary' }, ...facts));

			const go = el('button', { type: 'button', className: 'primary', disabled: !!refused }, 'Run');
			go.addEventListener('click', () => {
				modal.close();
				onRun({
					method, options: { ...o }, seed, cores: chosenCores,
					blocks: onlyEndpoints ? endpoints : null,
				});
			});
			const cancel = el('button', { type: 'button', className: 'ghost' }, 'Cancel');
			cancel.addEventListener('click', () => modal.close());
			body.append(el('div', { className: 'pdf-foot' },
				el('span', { className: 'pdf-note' }, 'Stop is available while it runs.'), cancel, go));
		},
	});
	return modal;
}

/** A number for a table cell: four figures, or an exponent where that is clearer. */
function num(v) {
	if (!Number.isFinite(v)) return '—';
	const a = Math.abs(v);
	if (a === 0) return '0';
	if (a >= 1e5 || a < 1e-3) return v.toExponential(2);
	const s = v.toPrecision(4);
	return s.includes('.') ? s.replace(/\.?0+$/, '') : s;
}

/** A share of the variance, as a bar against one. */
function share(v) {
	const box = el('div', { className: 'sens-bar' });
	if (!Number.isFinite(v)) {
		box.append(el('span', { className: 'sens-none' }, '—'));
		return box;
	}
	const fill = el('div', { className: `sens-fill${v < 0 ? ' is-down' : ''}` });
	fill.style.width = `${Math.min(100, Math.abs(v) * 100)}%`;
	box.append(el('div', { className: 'sens-track' }, fill), el('span', { className: 'sens-num mono' }, v.toFixed(3)));
	return box;
}

/** The vertical scale for the ranking index over time. */
function scaleFor(columns, rank, curves) {
	const kind = columns.find(([key]) => key === rank)?.[2];
	if (kind === 'index') return { lo: 0, hi: 1, ticks: [1, 0.5, 0] };
	let top = 0;
	for (const c of curves) for (const v of c.y) if (Number.isFinite(v)) top = Math.max(top, Math.abs(v));
	if (!(top > 0)) top = 1;
	return { lo: 0, hi: top, ticks: [top, top / 2, 0], label: num };
}

/**
 * @param {object} opts
 * @param {string[]} opts.outputs
 * @param {Float64Array} opts.t
 * @param {object} opts.answer    from the worker: the table for one output
 * @param {number} opts.points    runs the design took
 * @param {object} opts.stats     the run's statistics, `gsa` among them
 * @param {string} opts.timeUnit
 * @param {boolean} [opts.stale]  the model has changed since the runs were made
 * @param {(ask: {index: number, stat: string, at: number}) => void} opts.onAsk
 */
export function openGsaResult({
	outputs = [], t, answer, points, stats, timeUnit = 'year', stale = false, onAsk, onClose,
}) {
	let view = { outputs, t, answer, points, stats };
	let asking = false;
	const ask = (next) => {
		if (asking) return;
		asking = true;
		modal.refresh();
		onAsk?.({ index: view.answer.index, stat: view.answer.stat, at: view.answer.at, ...next });
	};
	const modal = openModal({
		info: dialogInfo('gsa-result'),
		wide: true,
		title: () => `${GSA_METHODS[view.answer.method]?.short ?? 'Sensitivity'} for ${view.outputs[view.answer.index] ?? ''}`,
		subtitle: () => `${view.points.toLocaleString()} runs — ${GSA_METHODS[view.answer.method]?.label ?? ''}`
			+ (stale ? ' — of the model as it was before the latest edits' : ''),
		onClose,
		build: (body) => {
			const a = view.answer;
			const ofSel = el('select', { className: 'sens-of', disabled: asking });
			view.outputs.slice(0, 300).forEach((label, k) => {
				ofSel.append(el('option', { value: String(k), selected: k === a.index }, label));
			});
			ofSel.addEventListener('change', () => ask({ index: Number(ofSel.value) }));
			body.append(el('div', { className: 'pdf-row pdf-row-wide' }, el('label', {}, 'Of'), ofSel));
			const statSel = el('select', { disabled: asking });
			for (const s2 of STATS) statSel.append(el('option', { value: s2, selected: s2 === a.stat }, STAT_LABEL[s2]));
			statSel.addEventListener('change', () => ask({ stat: statSel.value }));
			const atSel = el('select', { className: 'sens-time', disabled: asking, hidden: a.stat !== 'at' });
			for (let j = 0; j < view.t.length; j++) {
				atSel.append(el('option', { value: String(j), selected: j === a.at }, `${fmtTime(view.t[j])} ${timeUnit}`));
			}
			atSel.addEventListener('change', () => ask({ at: Number(atSel.value) }));
			body.append(el('div', { className: 'pdf-row pdf-row-wide' }, el('label', {}, 'Reading'), statSel, atSel));

			if (a.curves?.length) {
				const canvas = el('canvas', { className: 'sens-canvas' });
				body.append(el('div', { className: 'sens-chart' }, canvas));
				const key = el('div', { className: 'sens-key' });
				a.curves.forEach((c, i) => {
					const row = a.rows.find((r) => r.k === c.k);
					key.append(el('span', { className: `sens-key-item c${i % 6}` }, row ? inputName(row) : `input ${c.k + 1}`));
				});
				body.append(key);
				const rankLabel = a.columns.find(([k]) => k === a.rank)?.[1] ?? '';
				body.append(el('p', { className: 'hint' }, `${rankLabel} of the value at each output time, for the inputs that lead the table.`));
				requestAnimationFrame(() => paintCurves(canvas, view.t, a.curves,
					a.curves.map((c) => inputName(a.rows.find((r) => r.k === c.k))), scaleFor(a.columns, a.rank, a.curves)));
			}

			if (a.flat) {
				body.append(el('p', { className: 'prob-warn' },
					'This output came out the same in every run at this reading, so there is no spread '
					+ 'to attribute to anything. Another reading — the value at a later time, say — or '
					+ 'another output may.'));
			}
			if (a.failed) {
				body.append(el('p', { className: 'prob-warn' },
					`${a.failed.toLocaleString()} of the runs did not produce a number for this output, `
					+ 'and a designed method needs every one of them: the indices cannot be read. The run '
					+ 'log says why they failed.'));
			}
			const box = el('div', { className: 'sens-table gsa-table' });
			box.style.setProperty('--gsa-cols', String(a.columns.length));
			box.append(el('div', { className: 'sens-head' },
				el('span', {}, 'Input'),
				// Symbols, Greek and subscripted, which the heading row's
				// capitals would change into other symbols.
				...a.columns.map(([, label, kind, title]) => el('span', {
					title, className: `sens-head-greek${kind === 'index' ? '' : ' is-num'}`,
				}, label))));
			for (const r of a.rows.slice(0, 60)) {
				box.append(el('div', { className: 'sens-row' },
					el('code', { title: r.members ? `A correlation group: ${r.members.join(', ')}` : inputName(r) },
						r.members ? `${r.name} (group)` : inputName(r)),
					...a.columns.map(([key, , kind]) => (kind === 'index'
						? share(r.values[key])
						: el('span', { className: 'sens-coef mono', title: String(r.values[key]) },
							kind === 'count' ? String(r.values[key] ?? '') : num(r.values[key]))))));
			}
			if (a.rows.length > 60) box.append(el('div', { className: 'prob-more' }, `and ${a.rows.length - 60} more, all smaller`));
			body.append(box);

			if (a.pairs?.length) {
				const pairLabel = a.method === 'dgsm' ? 'mean squared mixed derivative'
					: a.method === 'ff' ? 'two-way interaction effect, each summed with the pairs aliased with it'
						: 'S₂, the interaction';
				const list = el('div', { className: 'gsa-pairs' },
					el('p', { className: 'hint' }, `The pairs, by ${pairLabel}:`),
					...a.pairs.slice(0, 10).map((p) => el('div', { className: 'gsa-pair' },
						el('code', {}, `${inputName(p.a)} × ${inputName(p.b)}`),
						el('span', { className: 'mono' }, num(p.value) + (p.ci != null ? ` ± ${num(p.ci)}` : '')))));
				body.append(list);
			}

			const g = view.stats?.gsa ?? {};
			const notes = [];
			if (g.correlated && !g.correlationsUsed) {
				notes.push(`The model correlates ${g.correlated} pair${g.correlated === 1 ? '' : 's'} of inputs; `
					+ 'this method sampled them independently.');
			}
			if (g.correlationShrunk > 0) {
				notes.push(`The correlations were not consistent with each other and were weakened by `
					+ `${Math.round(g.correlationShrunk * 100)} % until they were.`);
			}
			notes.push('Designed in probability: each input is moved through its own distribution, so an '
				+ 'effect or a derivative is per unit of probability and the inputs are comparable with '
				+ 'each other whatever their units.');
			body.append(el('p', { className: 'sens-note' }, notes.join(' ')));

			const done = el('button', { type: 'button', className: 'primary' }, 'Close');
			done.addEventListener('click', () => modal.close());
			body.append(el('div', { className: 'pdf-foot' },
				el('span', { className: 'pdf-note' }, asking ? 'Working it out…' : 'Read from the runs already made.'), done));
		},
	});
	return {
		close: () => modal.close(),
		update(next) { view = { ...view, ...next }; asking = false; modal.refresh(); },
	};
}
