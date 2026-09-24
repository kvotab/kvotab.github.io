/**
 * A tornado: every uncertain input swung on its own.
 *
 * The probabilistic sensitivity asks the sample which inputs the output
 * followed. A tornado asks the model directly: hold everything at its value,
 * move one input to a low and a high probability of its distribution, and
 * see what the output does; then the next input, and the next. GoldSim's
 * "three simulations per variable", with the central one shared, so 2K+1
 * runs for K inputs. It needs no sample and finds no interactions -- it is the
 * chart to draw when the distributions are not yet trusted enough to sample
 * from, or when the question is which inputs to bother with at all.
 *
 * Two dialogs: one that prices the runs and starts them, one that draws the
 * bars. The bars are read out of the worker's result for whichever output,
 * statistic and time is asked for, without running anything again.
 */

import { el } from './parts.js';
import { openModal } from './modal.js';
import { fmtTime } from '../domain/timeseries.js';
import { STATS, STAT_LABEL } from '../domain/categories.js';
import { howLong } from './probdialog.js';
import { inputName } from './sensdialog.js';
import { fmtStat } from './distdialog.js';
import { coresRow } from './cores.js';
import { dialogInfo } from './dialoginfo.js';

/**
 * Prices the runs and asks which probabilities to swing to.
 *
 * @param {object} opts
 * @param {Array} opts.plan            what would be swung, from `samplingPlan`
 * @param {number|null} opts.lastSolveMs
 * @param {number} opts.workers          how many cores when the tool decides
 * @param {number|null} [opts.cores]     the reader's own number, or null for that
 * @param {string[]} opts.endpoints
 * @param {object} opts.simulation
 * @param {(choice: {low: number, high: number, blocks: string[]|null, cores: number|null}) => void} opts.onRun
 */
export function openTornadoSetup({
	plan, lastSolveMs = null, workers = 1, cores: chosen = null, endpoints = [], simulation = {}, onRun,
}) {
	let chosenCores = chosen;
	let low = Number(simulation.tornado_low ?? 0.05);
	let high = Number(simulation.tornado_high ?? 0.95);
	let onlyEndpoints = endpoints.length > 0;
	const modal = openModal({
		info: dialogInfo('tornado'),
		title: 'Tornado',
		subtitle: 'Each sampled input swung on its own, low and high, with the rest held',
		build: (body) => {
			const runs = 2 * plan.length + 1;
			const cores = Math.max(1, Math.min(chosenCores ?? workers, runs));
			const total = lastSolveMs ? (lastSolveMs * runs) / cores : null;
			body.append(el('div', { className: 'prob-summary' },
				el('p', {}, el('b', {}, `${runs.toLocaleString()} runs`),
					` — one with everything at the model’s values, then each of the `
					+ `${plan.length.toLocaleString()} sampled inputs at its ${Math.round(low * 100)}th and `
					+ `${Math.round(high * 100)}th percentile.`),
				total
					? el('p', {}, 'One integration took ', el('b', {}, howLong(lastSolveMs)),
						', so this is about ', el('b', { className: total > 30 * 60 * 1000 ? 'is-bad' : '' }, howLong(total)),
						cores > 1 ? ` over ${cores} cores.` : '.')
					: el('p', { className: 'hint' }, 'Run the model once first and this will say how long it is likely to take.')));
			const pctRow = (label, get, set) => {
				const input = el('input', { type: 'text', className: 'mono', value: String(Math.round(get() * 100)) });
				input.addEventListener('change', () => {
					const v = Number(input.value) / 100;
					if (Number.isFinite(v) && v > 0 && v < 1) { set(v); modal.refresh(); } else input.value = String(Math.round(get() * 100));
				});
				return el('div', { className: 'pdf-row' }, el('label', {}, label), input, el('span', { className: 'unit' }, '%'));
			};
			body.append(pctRow('Low percentile', () => low, (v) => { low = v; }));
			body.append(pctRow('High percentile', () => high, (v) => { high = v; }));
			body.append(coresRow({
				auto: workers, value: chosenCores,
				onChange: (n) => { chosenCores = n; modal.refresh(); },
			}));
			if (endpoints.length) {
				const box = el('input', { type: 'checkbox', checked: onlyEndpoints });
				box.addEventListener('change', () => { onlyEndpoints = box.checked; });
				body.append(el('div', { className: 'pdf-row' },
					el('label', { title: 'Keep only the series the model names as its endpoints.' },
						`Keep only the ${endpoints.length} endpoints`), box));
			}
			const go = el('button', { type: 'button', className: 'primary', disabled: !(high > low) }, 'Run');
			go.addEventListener('click', () => {
				modal.close();
				onRun({ low, high, blocks: onlyEndpoints ? endpoints : null, cores: chosenCores });
			});
			const cancel = el('button', { type: 'button', className: 'ghost' }, 'Cancel');
			cancel.addEventListener('click', () => modal.close());
			body.append(el('div', { className: 'pdf-foot' },
				el('span', { className: 'pdf-note' }, 'Stop is available while it runs.'), cancel, go));
		},
	});
	return modal;
}

/**
 * The bars.
 *
 * @param {object} opts
 * @param {string[]} opts.outputs   the series the tornado kept
 * @param {Float64Array} opts.t
 * @param {object} opts.table       from the worker: index, stat, at, central, rows
 * @param {number} opts.points      how many runs it was
 * @param {string} opts.timeUnit
 * @param {{low: number, high: number}} opts.swing
 * @param {(ask: {index: number, stat: string, at: number}) => void} opts.onAsk
 * @param {(point: number) => void} [opts.onReplay]  run one design point again, in full
 */
export function openTornadoResult({ outputs = [], t, table, points, timeUnit = 'year', swing, onAsk, onReplay, onClose }) {
	let view = { outputs, t, table, points };
	let asking = false;
	const ask = (next) => {
		if (asking) return;
		asking = true;
		modal.refresh();
		onAsk?.({ index: view.table.index, stat: view.table.stat, at: view.table.at, ...next });
	};
	const modal = openModal({
		info: dialogInfo('tornado-result'),
		wide: true,
		title: () => `Tornado for ${view.outputs[view.table.index] ?? ''}`,
		subtitle: () => `${view.points.toLocaleString()} runs — each input at its `
			+ `${Math.round(swing.low * 100)}th and ${Math.round(swing.high * 100)}th percentile, the rest held`,
		onClose,
		build: (body) => {
			const { table: tb } = view;
			const ofSel = el('select', { className: 'sens-of', disabled: asking });
			view.outputs.slice(0, 300).forEach((label, k) => {
				ofSel.append(el('option', { value: String(k), selected: k === tb.index }, label));
			});
			ofSel.addEventListener('change', () => ask({ index: Number(ofSel.value) }));
			body.append(el('div', { className: 'pdf-row pdf-row-wide' }, el('label', {}, 'Of'), ofSel));
			const statSel = el('select', { disabled: asking });
			for (const s2 of STATS) statSel.append(el('option', { value: s2, selected: s2 === tb.stat }, STAT_LABEL[s2]));
			statSel.addEventListener('change', () => ask({ stat: statSel.value }));
			const atSel = el('select', { className: 'sens-time', disabled: asking, hidden: tb.stat !== 'at' });
			for (let j = 0; j < view.t.length; j++) {
				atSel.append(el('option', { value: String(j), selected: j === tb.at }, `${fmtTime(view.t[j])} ${timeUnit}`));
			}
			atSel.addEventListener('change', () => ask({ at: Number(atSel.value) }));
			body.append(el('div', { className: 'pdf-row pdf-row-wide' }, el('label', {}, 'Reading'), statSel, atSel));

			// The bars. One axis for all rows, from the smallest low/high to the
			// largest, with the central value marked -- so a row's bar is where
			// the output went when that input alone moved.
			const finite = tb.rows.filter((r) => Number.isFinite(r.low) && Number.isFinite(r.high));
			const lo = Math.min(tb.central, ...finite.map((r) => Math.min(r.low, r.high)));
			const hi = Math.max(tb.central, ...finite.map((r) => Math.max(r.low, r.high)));
			const span = hi - lo || 1;
			const x = (v) => `${(100 * (v - lo)) / span}%`;
			const box = el('div', { className: 'tor-table' });
			box.append(el('div', { className: 'tor-head' },
				el('span', {}, 'Input'), el('span', {}, `at ${Math.round(swing.low * 100)}%`),
				el('span', {}, 'swing'), el('span', {}, `at ${Math.round(swing.high * 100)}%`)));
			for (const r of tb.rows.slice(0, 40)) {
				const bar = el('div', { className: 'tor-bar' });
				if (Number.isFinite(r.low) && Number.isFinite(r.high)) {
					const a = Math.min(r.low, r.high);
					const b = Math.max(r.low, r.high);
					const fill = el('div', { className: `tor-fill${r.high < r.low ? ' is-down' : ''}` });
					fill.style.left = x(a);
					fill.style.width = `calc(${(100 * (b - a)) / span}% + 1px)`;
					fill.title = `${inputName(r)}: ${fmtStat(r.low)} at the low input (${fmtStat(r.lowInput)}), `
						+ `${fmtStat(r.high)} at the high (${fmtStat(r.highInput)}); the rest held.`;
					bar.append(fill);
				}
				const mark = el('div', { className: 'tor-central' });
				mark.style.left = x(tb.central);
				bar.append(mark);
				const row = el('div', { className: 'tor-row' },
					el('code', { title: inputName(r) }, inputName(r)),
					el('span', { className: 'mono tor-num' }, fmtStat(r.low)),
					bar,
					el('span', { className: 'mono tor-num' }, fmtStat(r.high)));
				if (onReplay) {
					row.title = 'Double-click to run the high point of this input again in full';
					row.addEventListener('dblclick', () => onReplay(2 * tb.rows.indexOf(r) + 2, r));
				}
				box.append(row);
			}
			if (tb.rows.length > 40) box.append(el('div', { className: 'prob-more' }, `and ${tb.rows.length - 40} more, all smaller`));
			body.append(box);
			body.append(el('p', { className: 'sens-note' },
				`With everything at the model’s values the output is ${fmtStat(tb.central)} (the mark). `
				+ 'A bar to the right of it means the high input raised the output; red means the high '
				+ 'input lowered it. Ranked by the size of the swing. One input at a time, so what two '
				+ 'inputs do together is not here — that is what the probabilistic run is for.'));
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
