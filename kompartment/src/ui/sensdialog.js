/**
 * What drove the spread.
 *
 * A probabilistic run answers "how uncertain is this"; this answers "because of
 * what". It is Ecolego's default sensitivity method -- the one computed from
 * the Monte Carlo sample already drawn -- shown the two ways Ecolego shows it:
 * a ranked table, and the coefficients over time.
 *
 * **Ranked by |Spearman|, and both coefficients shown.** Spearman finds any
 * monotone relationship, Pearson only a straight-line one, and the interesting
 * case here is monotone and bent -- a log-triangular sorption coefficient
 * driving a dose through four compartments. Where the two disagree, the
 * relationship is curved, and seeing that is worth a column.
 *
 * **Over time, because "which input matters" is not one answer.** A release
 * rate governs the first century and a sorption coefficient the next ten
 * thousand years, and a single number at a single time would report whichever
 * of them the reader happened to ask about.
 */

import { el } from './parts.js';
import { openModal } from './modal.js';
import { renderDualTree, dualTreeState } from './dualtree.js';
import { fmtTime } from '../domain/timeseries.js';

/**
 * How one sampled input is named, index and all.
 *
 * One spelling for both halves of the dialog. The table and the key name the
 * same inputs, and a key that said "Kd" twice -- once for each nuclide -- would
 * leave two curves on the chart with no way to tell them apart.
 */
export function inputName(row) {
	if (!row) return '';
	const where = (row.where ?? []).join(' · ');
	return `${row.name}${where ? `[${where}]` : ''}`;
}

/**
 * What the regression may be fitted to, and what each one is for.
 *
 * `rank` is what the tick box used to be; the other two are the reasons it
 * wanted to be a list. See ../domain/sensitivity.js.
 */
const TRANSLATIONS = [
	['none', 'nothing — the values',
		'The values as the run drew them. The coefficients are in the model’s own units.'],
	['rank', 'ranks',
		'Each input and the output replaced by their ranks, which gives SRRC and PRCC — '
		+ 'the reading for a relationship that is monotone but not straight.'],
	['log', 'logarithms',
		'The logarithm of each input and of the output. A power law is a straight line in '
		+ 'logs, and the coefficient is then an elasticity. Realisations where anything is '
		+ 'zero or negative are left out, and the line below says how many.'],
];

/**
 * The measures beside the correlations, and what each set is for.
 *
 * The second set is ../domain/gsa.js's reading of a plain sample -- the half
 * of GlobalSensitivity.jl that needs no design of its own.
 */
const FAMILIES = [
	['regression', 'Regression: SRC, PCC, S₁',
		'One regression of the output on every input at once, which separates inputs the output '
		+ 'merely tracks together, and a first-order index by binning.'],
	['distribution', 'Distribution: EASI, δ, MI, RSA, PAWN, discrepancy',
		'Measures that read the output’s whole distribution rather than a straight line through '
		+ 'it: EASI’s first-order index, Borgonovo’s δ, mutual information and regional '
		+ 'sensitivity, from GlobalSensitivity.jl, and PAWN and discrepancy from SALib. A '
		+ 'bootstrap per input, so a few seconds on a large sample.'],
];

/**
 * The three things *At* can mean, and what each one is for.
 *
 * `own` and `mean` are different questions, and the difference is the point
 * of offering both. Where the output peaks on average is one time, and the
 * table is every realisation's value then, which for a realisation that peaks
 * much earlier or later is not its peak at all. Each realisation's own peak is
 * the largest value it reaches whenever that is, so what drives the height of
 * the peak is read apart from what drives its timing.
 */
const WHEN = [
	['own', 'each realisation’s peak',
		'The largest value each realisation reaches, whenever it reaches it — so one that peaks '
		+ 'early and one that peaks late are compared by how high they get.'],
	['mean', 'where it peaks on average',
		'The one time at which this output is largest averaged over the realisations, and every '
		+ 'realisation’s value then — not the peak of any one of them.'],
	['time', 'a chosen time',
		'Every realisation’s value at a time picked from the output grid; the last one to start with.'],
];

/** A number for a sentence: four figures, or an exponent. */
function fmtValue(v) {
	if (!Number.isFinite(v)) return '—';
	const a = Math.abs(v);
	return a !== 0 && (a >= 1e5 || a < 1e-3) ? v.toExponential(3) : String(Number(v.toPrecision(4)));
}

/** What to append to `R²` so the number says what it is of. */
const TRANSLATED = { none: '', rank: ' on ranks', log: ' on logarithms' };

/**
 * A coefficient that is not on a fixed scale, so it gets a number and no bar.
 *
 * `b` is in units -- becquerels per year per cubic metre, whatever the pair
 * happens to be -- and a bar drawn against a scale of one would be full for
 * every input whose units are small and empty for every input whose units are
 * large, which says nothing about either.
 */
function coef(v) {
	if (!Number.isFinite(v)) {
		return el('span', { className: 'sens-none', title: 'No coefficient: this input never '
			+ 'varied, or the fit left it out.' }, '—');
	}
	const a = Math.abs(v);
	// Trailing zeros go only from a fraction: `toPrecision(4)` gives `1000`
	// for a thousand, and stripping zeros off the end of that leaves `1`.
	const trim = (x) => (x.includes('.') ? x.replace(/\.?0+$/, '') : x);
	const text = a === 0 ? '0'
		: a >= 1e5 || a < 1e-3 ? v.toExponential(2)
			: trim(v.toPrecision(4));
	return el('span', { className: 'sens-coef mono', title: String(v) }, text);
}

/** A coefficient as a bar: the sign is the direction, the length the strength. */
function bar(v) {
	const box = el('div', { className: 'sens-bar' });
	if (!Number.isFinite(v)) {
		box.append(el('span', { className: 'sens-none', title: 'This input never varied, '
			+ 'or the output never did — there is nothing to correlate.' }, '—'));
		return box;
	}
	const fill = el('div', {
		className: `sens-fill${v < 0 ? ' is-down' : ''}`,
	});
	fill.style.width = `${Math.min(100, Math.abs(v) * 100)}%`;
	box.append(el('div', { className: 'sens-track' }, fill),
		el('span', { className: 'sens-num mono' }, v.toFixed(3)));
	return box;
}

/**
 * The little multi-line chart of coefficients against time.
 *
 * `scale` is the vertical axis: a correlation's [-1, 1] unless told otherwise
 * -- a variance share lives on [0, 1], and Morris's μ* in the output's units.
 *
 * @param {{lo: number, hi: number, ticks: number[], label?: (v: number) => string}} [scale]
 * @param {object} [extra]
 * @param {(v: number) => string} [extra.time]  labels the time axis, when given
 * @param {{at?: number, low?: number, high?: number}} [extra.mark]  the time the
 *   table under the chart is for, as a line; with `low` and `high`, a band
 */
export function paintCurves(canvas, t, curves, names, scale = null, { time = null, mark = null } = {}) {
	const ctx = canvas.getContext('2d');
	if (!ctx) return;
	const dpr = window.devicePixelRatio || 1;
	const w = canvas.clientWidth || 420;
	const h = canvas.clientHeight || 150;
	canvas.width = Math.round(w * dpr);
	canvas.height = Math.round(h * dpr);
	ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
	ctx.clearRect(0, 0, w, h);
	if (!curves.length || !t.length) return;

	const style = getComputedStyle(canvas);
	const ink = style.getPropertyValue('--text-muted').trim() || '#888';
	const faint = style.getPropertyValue('--border').trim() || '#333';
	const { lo, hi, ticks, label = String } = scale ?? { lo: -1, hi: 1, ticks: [1, 0.5, 0, -0.5, -1] };
	// Room for the widest tick label: a coefficient's is `-0.5`, a value in
	// the output's units can be `8.21e+14`.
	ctx.font = '9px system-ui, sans-serif';
	const widest = Math.max(...ticks.map((v) => ctx.measureText(label(v)).width));
	const pad = { l: Math.max(30, Math.ceil(widest) + 8), r: 8, t: 8, b: 16 };
	const pw = w - pad.l - pad.r;
	const ph = h - pad.t - pad.b;

	// Time on a log axis where the run is logarithmic, which is how these
	// models are reported -- the first century of a hundred-thousand-year run
	// is where half the story is.
	const t0 = t[0];
	const tN = t[t.length - 1];
	const useLog = t0 > 0 && tN / t0 > 100;
	const sx = (x) => pad.l + (useLog
		? (Math.log(x) - Math.log(t0)) / (Math.log(tN) - Math.log(t0))
		: (x - t0) / (tN - t0)) * pw;
	// Always the whole range: a coefficient lives in [-1, 1] and rescaling it
	// would make a weak correlation look like a strong one.
	const sy = (v) => pad.t + ((hi - v) / (hi - lo)) * ph;

	ctx.strokeStyle = faint;
	ctx.lineWidth = 1;
	for (const v of ticks) {
		const y = sy(v);
		ctx.globalAlpha = v === 0 ? 0.9 : 0.35;
		ctx.beginPath();
		ctx.moveTo(pad.l, y + 0.5);
		ctx.lineTo(pad.l + pw, y + 0.5);
		ctx.stroke();
		ctx.globalAlpha = 1;
		ctx.fillStyle = ink;
		ctx.font = '9px system-ui, sans-serif';
		ctx.textAlign = 'right';
		ctx.textBaseline = 'middle';
		ctx.fillText(label(v), pad.l - 4, y);
	}

	// The time axis, labelled: without it the reader could see that an input
	// mattered and then stopped, but not when. Decades on a log axis, round
	// steps on a linear one.
	if (time) {
		const at = [];
		if (useLog) {
			for (let e = Math.ceil(Math.log10(t0)); e <= Math.floor(Math.log10(tN)); e++) at.push(10 ** e);
			while (at.length > 7) for (let i = at.length - 2; i > 0; i -= 2) at.splice(i, 1);
		} else {
			const raw = (tN - t0) / 5;
			const mag = 10 ** Math.floor(Math.log10(raw));
			const step = [1, 2, 5, 10].map((m) => m * mag).find((d) => d >= raw) ?? raw;
			for (let v = Math.ceil(t0 / step) * step; v <= tN + step * 1e-9; v += step) at.push(v);
		}
		ctx.fillStyle = ink;
		ctx.font = '9px system-ui, sans-serif';
		ctx.textAlign = 'center';
		ctx.textBaseline = 'top';
		for (const v of at) ctx.fillText(time(v), Math.min(pad.l + pw - 10, Math.max(pad.l + 10, sx(v))), pad.t + ph + 3);
	}
	// Where the table is read: a line at its time, or for each realisation's
	// own peak a band over where those peaks fall, with a line at the median.
	if (mark) {
		const inRange = (v) => Number.isFinite(v) && (!useLog || v > 0);
		const accent = style.getPropertyValue('--text-primary').trim() || '#ccc';
		if (inRange(mark.low) && inRange(mark.high)) {
			const x0 = sx(Math.max(t0, mark.low));
			const x1 = sx(Math.min(tN, mark.high));
			ctx.globalAlpha = 0.12;
			ctx.fillStyle = accent;
			ctx.fillRect(x0, pad.t, Math.max(1, x1 - x0), ph);
			ctx.globalAlpha = 1;
		}
		if (inRange(mark.at)) {
			const x = Math.round(sx(Math.min(tN, Math.max(t0, mark.at)))) + 0.5;
			ctx.strokeStyle = accent;
			ctx.globalAlpha = 0.6;
			ctx.setLineDash([3, 3]);
			ctx.beginPath();
			ctx.moveTo(x, pad.t);
			ctx.lineTo(x, pad.t + ph);
			ctx.stroke();
			ctx.setLineDash([]);
			ctx.globalAlpha = 1;
		}
	}

	const colours = ['--series-1', '--series-2', '--series-3', '--series-4', '--series-5', '--series-6'];
	curves.forEach((c, i) => {
		const colour = style.getPropertyValue(colours[i % colours.length]).trim()
			|| ['#4a9eff', '#f08c3a', '#54c08a', '#d96c8a', '#9b7fe0', '#d8c15a'][i % 6];
		ctx.strokeStyle = colour;
		ctx.lineWidth = 1.8;
		ctx.lineJoin = 'round';
		ctx.beginPath();
		let pen = false;
		for (let j = 0; j < t.length; j++) {
			const x = t[j];
			const v = c.y[j];
			if (!Number.isFinite(v) || (useLog && !(x > 0))) { pen = false; continue; }
			const px = sx(x);
			const py = sy(v);
			if (!pen) { ctx.moveTo(px, py); pen = true; } else ctx.lineTo(px, py);
		}
		ctx.stroke();
	});
}

/**
 * How many series the *Of* list offers before it stops.
 *
 * A probabilistic run keeps whatever it was asked to keep, and on a landscape
 * model that can be tens of thousands of series -- a `<select>` with an option
 * apiece is a browser that stops answering. The chart's own picker caps its
 * chips for the same reason; past this the older route still works, which is
 * to chart the line and reopen.
 */
const MOST_OUTPUTS = 300;

/**
 * What drove one output, with the two choices that decide which answer this is.
 *
 * **One dialog, refreshed.** Both pickers ask the worker again -- the sample is
 * there and a coefficient is one pass over it, so neither costs a run -- and
 * the answer comes back into *this* dialog rather than opening another over it.
 * It used to open another: every change of time pushed a second dialog onto the
 * stack, and closing it revealed the one before with the older table still in
 * it.
 *
 * @param {object} opts
 * @param {string} opts.output   which series this is about
 * @param {string[]} opts.outputs  every series the run kept, for the picker
 * @param {number} opts.index    which of those this is
 * @param {Float64Array} opts.t
 * @param {number|null} opts.at  the time the table is for, as an index; null when it
 *   is each realisation's own peak
 * @param {object|null} [opts.peaks] when those peaks fall: `{median, low, high}`
 * @param {Array} opts.rows      from the worker: name, where, pearson, spearman
 * @param {Array} opts.curves    the few that matter, over time
 * @param {number} opts.iterations
 * @param {string} opts.timeUnit
 * @param {(ask: {index: number, at: number|'peak'|'max'}) => void} opts.onAsk  ask again
 * @param {() => void} [opts.onClose]
 * @returns {{update: (next: object) => void, reask: () => void, close: () => void}}
 */
export function openSensitivityDialog({
	output, outputs = [], index = 0, t, at, rows, curves, iterations, measures = null,
	distribution = null, kept = null, peaks = null, sampled = [], using = null, timeUnit = 'year', onAsk, onClose,
}) {
	// What is on screen. Replaced wholesale when an answer arrives, so the
	// dialog is built from one object and there is no half-updated state.
	// `family` and `translate` are the ones *this answer* was worked out
	// with, which the table is drawn from; the pickers show what was asked
	// since, and until its answer arrives the table stays as it was rather than
	// dropping to the two correlations for a moment.
	let view = {
		output, outputs, index, t, at, rows, curves, iterations, measures, distribution, kept, peaks,
		sampled, using, family: 'regression', translate: 'none',
	};
	// What the regression family is fitted to: the values, their ranks (SRRC
	// and PRCC), or their logarithms. See ../domain/sensitivity.js.
	let translate = 'none';
	// Which measures stand beside the correlations: the regression family,
	// or the ones that read the output's whole distribution -- EASI, δ, mutual
	// information and RSA, from ../domain/gsa.js.
	let family = 'regression';
	// Which question the table answers, of the three under *At* (see WHEN):
	// each realisation's own peak, where the output peaks on average, or a
	// chosen time. Kept apart from `view.at`, which is whatever time the last
	// answer was for: asking for a peak and then changing the output has to
	// find the *new* output's peak, and sending the old one's index back would
	// quietly pin it there.
	let when = 'time';
	// The chosen time, as an index into the output grid: the last one to
	// start with, and kept while another question is asked, so coming back to
	// it comes back to the same time.
	let chosen = Number.isInteger(at) ? at : Math.max(0, (t?.length ?? 1) - 1);
	const question = () => (when === 'own' ? 'max' : when === 'mean' ? 'peak' : chosen);
	// Which sampled inputs the analysis is over, as sample columns: null for
	// all of them. Kept across changes of output and time -- it is a choice
	// about the sample, not about one series.
	let inputs = null;
	const pickerUi = dualTreeState();
	// What the question in flight was asked with, for `update` to file the
	// answer under.
	let asked = { family: 'regression', translate: 'none' };
	// Set while the worker is being waited on, so the pickers cannot be used to
	// queue up three questions whose answers arrive in any order.
	let asking = false;

	const ask = (next) => {
		if (asking) return;
		asking = true;
		asked = { family, translate };
		modal.refresh();
		onAsk?.({ index: view.index, at: question(), translate, family, inputs, ...next });
	};

	// The inputs, chosen in the two trees Save… uses: a sample can vary
	// hundreds, and they are found by name and sub-system rather than ticked
	// down a list. Applied on Apply, since each change is a new analysis and
	// the distribution measures take seconds.
	const pickInputs = () => {
		const items = view.sampled.map((x) => ({
			key: String(x.k),
			// The tree reads dots as sub-systems, so an index value that has one
			// keeps it out of the way with a one-dot leader, which looks the same.
			name: `${x.name}${x.where.length ? `[${x.where.join(' · ').replaceAll('.', '\u2024')}]` : ''}`,
			title: inputName(x),
			kind: x.name.includes('@') ? 'lookup' : 'parameter',
		}));
		const picked = new Set((inputs ?? view.sampled.map((x) => x.k)).map(String));
		const inner = openModal({
			wide: true,
			title: 'Inputs in the analysis',
			subtitle: 'The table ranks these, the regression is fitted to these, and the distribution '
				+ 'measures are of these.',
			build(body) {
				body.replaceChildren();
				const box = el('div', { className: 'save-pick' });
				const apply = el('button', { type: 'button', className: 'primary' }, 'Apply');
				const note = el('span', { className: 'pdf-note' });
				const settle = () => {
					apply.disabled = picked.size === 0;
					note.textContent = picked.size ? '' : 'Choose at least one.';
				};
				renderDualTree(box, {
					items, chosen: picked, ui: pickerUi, titles: ['Left out', 'In the analysis'],
					noun: 'input', onChange: settle,
				});
				body.append(box);
				const cancel = el('button', { type: 'button', className: 'ghost' }, 'Cancel');
				cancel.addEventListener('click', () => inner.close());
				apply.addEventListener('click', () => {
					inputs = picked.size === items.length ? null
						: [...picked].map(Number).sort((p, q) => p - q);
					inner.close();
					ask({});
				});
				body.append(el('div', { className: 'pdf-foot' }, note, cancel, apply));
				settle();
			},
		});
	};

	const modal = openModal({
		wide: true,
		title: () => `What drove ${view.output}`,
		subtitle: () => `From ${(view.kept ?? view.iterations).toLocaleString()}`
			+ (view.kept != null && view.kept !== view.iterations
				? ` of ${view.iterations.toLocaleString()} realisations (the categories shown)` : ' realisations')
			+ ' — how each sampled input relates to this output',
		onClose,
		build: (body) => {
			const { t: time, rows: table, curves: lines } = view;

			// --- which series. The answer is about one output and the reader
			// arrived here from the chart, where only one of them was in front
			// of them -- so the question "and this other one?" is the commonest
			// thing to want next, and it used to mean closing this, changing
			// the chart and opening it again.
			if (view.outputs.length > 1) {
				const shown = view.outputs.slice(0, MOST_OUTPUTS);
				// Always offer the one being shown, even past the cap.
				if (view.index >= MOST_OUTPUTS) shown.unshift(view.outputs[view.index]);
				const of = el('select', { className: 'sens-of', disabled: asking });
				for (const label of shown) {
					const k = view.outputs.indexOf(label);
					of.append(el('option', { value: String(k), selected: k === view.index }, label));
				}
				of.addEventListener('change', () => ask({ index: Number(of.value) }));
				const row = el('div', { className: 'pdf-row pdf-row-wide' },
					el('label', {}, 'Of'), of);
				body.append(row);
				if (view.outputs.length > shown.length) {
					body.append(el('p', { className: 'hint' },
						`${shown.length} of ${view.outputs.length.toLocaleString()} series the `
						+ 'run kept. For one that is not listed, chart it and open this again.'));
				}
			}

			// --- over time first: which input matters is not one answer.
			if (lines.length) {
				// What the chart is, and where on it the table below is read.
				const own = when === 'own' && view.at == null;
				const mark = own
					? (view.peaks ? { low: view.peaks.low, high: view.peaks.high, at: view.peaks.median } : null)
					: Number.isInteger(view.at) ? { at: time[view.at] } : null;
				body.append(el('p', { className: 'hint sens-caption' },
					`The rank correlation of each of the ${lines.length === 1 ? 'input' : `${lines.length} inputs`} at the `
					+ `top of the table with ${view.output}, at every output time: 1 is `
					+ 'a rise with the input, −1 a fall, 0 nothing. '
					+ (own && mark ? 'The shaded band is where the realisations peak (5th to 95th percentile), '
						+ 'the dashed line the median — the table is of their peaks.'
						: mark ? 'The dashed line is the time the table is for.' : '')));
				const canvas = el('canvas', { className: 'sens-canvas' });
				body.append(el('div', { className: 'sens-chart' }, canvas));
				const key = el('div', { className: 'sens-key' });
				lines.forEach((c, i) => {
					const row = table.find((r) => r.k === c.k);
					key.append(el('span', { className: `sens-key-item c${i % 6}` },
						row ? inputName(row) : `input ${c.k}`));
				});
				body.append(key);
				requestAnimationFrame(() => paintCurves(canvas, time, lines,
					lines.map((c) => inputName(table.find((r) => r.k === c.k))), null,
					{ time: (v) => fmtTime(v), mark }));
			}

			// --- and the table: at which time, or at whose peak.
			const how = el('select', { className: 'sens-when', disabled: asking });
			for (const [value, label, why] of WHEN) {
				// Which time the average peaks at comes back with the answer,
				// so the entry says it once it is known.
				const text = value === 'mean' && when === 'mean' && Number.isInteger(view.at)
					? `${label} — ${fmtTime(time[view.at])} ${timeUnit}` : label;
				how.append(el('option', { value, selected: value === when, title: why }, text));
			}
			how.addEventListener('change', () => { when = how.value; ask({}); });
			const at = el('span', { className: 'sens-at' }, how);
			if (when === 'time') {
				const pick = el('select', { className: 'sens-time', disabled: asking, 'aria-label': 'Time' });
				for (let j = 0; j < time.length; j++) {
					// Through the same formatter the chart and the table use: a
					// log grid gives times like 5746.434968715976, and four
					// hundred of those in a list is unreadable.
					pick.append(el('option', { value: String(j), selected: j === chosen },
						`${fmtTime(time[j])} ${timeUnit}`));
				}
				pick.addEventListener('change', () => { chosen = Number(pick.value); ask({}); });
				at.append(pick);
			}
			body.append(el('div', { className: 'pdf-row pdf-row-wide' },
				el('label', {}, 'At'), at));
			// A realisation's own peak has no one time, so the table says when
			// they fell: the question behind it is often "and is that early or
			// late?".
			if (when === 'own' && view.at == null) {
				const p = view.peaks;
				body.append(el('p', { className: 'hint' }, p
					? 'The largest value each realisation reaches, whenever it reaches it. They peak '
						+ `between ${fmtTime(p.low)} and ${fmtTime(p.high)} ${timeUnit} (5th to 95th `
						+ `percentile), at ${fmtTime(p.median)} ${timeUnit} in the median realisation.`
					: 'The largest value each realisation reaches, whenever it reaches it.'));
			}

			// Which sampled inputs are in the analysis. All of them unless the
			// reader narrows it: to the inputs a study is about, or without one
			// that is known to dominate so the rest can be seen.
			if (view.sampled.length > 1) {
				const total = view.sampled.length;
				const using = inputs ? inputs.length : total;
				const choose = el('button', { type: 'button', className: 'ghost sens-inputs', disabled: asking,
					title: 'Choose which of the sampled inputs the table ranks, the regression is fitted to and '
						+ 'the distribution measures are worked out for.' },
				using === total ? `all ${total.toLocaleString()} sampled inputs`
					: `${using.toLocaleString()} of ${total.toLocaleString()} sampled inputs`);
				choose.addEventListener('click', () => pickInputs());
				body.append(el('div', { className: 'pdf-row' }, el('label', {}, 'Inputs'), choose));
			}

			const fam = el('select', { className: 'sens-family', disabled: asking });
			for (const [value, label, why] of FAMILIES) {
				fam.append(el('option', { value, selected: value === family, title: why }, label));
			}
			fam.addEventListener('change', () => { family = fam.value; ask({}); });
			body.append(el('div', { className: 'pdf-row' },
				el('label', { title: 'Which measures stand beside the two correlations.' }, 'Measures'), fam));

			// What the output is read as, for either set of measures. It is
			// offered where it changes something: every regression measure, and
			// of the distribution measures EASI and where RSA splits.
			if (family === 'distribution' || view.measures) {
				const how = el('select', { className: 'sens-translate', disabled: asking });
				for (const [value, label, why] of TRANSLATIONS) {
					how.append(el('option', { value, selected: value === translate, title: why }, label));
				}
				how.addEventListener('change', () => { translate = how.value; ask({}); });
				body.append(el('div', { className: 'pdf-row' },
					el('label', { title: family === 'distribution'
						? 'What the output is read as. It changes EASI, which is a share of the variance, and '
							+ 'where RSA splits the realisations: at the mean, the geometric mean on logarithms '
							+ 'and the median on ranks. δ, MI, PAWN and discrepancy depend on order alone and do '
							+ 'not change — except that logarithms leave out realisations that are not positive.'
						: 'What the regression is fitted to. It does not change Spearman, which is already a '
							+ 'rank correlation, and cannot change any measure that only cares about order.' },
					'Translate'), how));
			}

			// The table is drawn from the answer on screen, which may be of the
			// other family while a new one is being worked out.
			const dist = view.family === 'distribution' ? view.distribution : null;
			const shownTranslate = view.translate;

			// The regression family beside the two correlations, when the worker
			// could compute it, and what it was fitted to. On ranks SRC and PCC
			// are SRRC and PRCC, which is what to read for the
			// monotone-and-bent relationships here; on logs the coefficient is
			// an elasticity.
			const m = view.family === 'regression' ? view.measures : null;
			const wide = !!(m && m.ok);
			if (m) {
				// On its own line. In the row above it the sentence wrapped
				// inside a column a third of the dialog wide, and the four
				// lines it took left the rest of the row empty.
				body.append(el('p', { className: `sens-r2${m.ok ? '' : ' is-bad'}` }, m.ok
					? `R² = ${m.r2.toFixed(3)}${TRANSLATED[shownTranslate]} — the share of the spread `
						+ 'a linear fit to every input explains.'
						+ (m.dropped
							? ` ${m.dropped.toLocaleString()} realisation`
								+ `${m.dropped === 1 ? '' : 's'} left out: a logarithm needs a `
								+ 'positive number, and something there was not.'
							: '')
					: 'The regression could not be fitted: more inputs than realisations, two '
						+ 'inputs that are the same numbers, or — on logs — too few realisations '
						+ 'left once the non-positive ones were dropped.'));
			}
			const leftOut = (k) => (k
				? ` ${k.toLocaleString()} realisation${k === 1 ? '' : 's'} left out: a logarithm needs a `
					+ 'positive number, and something there was not.'
				: '');
			if (dist && !dist.ok) {
				body.append(el('p', { className: 'sens-r2 is-bad' }, (dist.flat
					? 'The output is the same in every realisation here, so there is no distribution to compare.'
					: `Only ${dist.used} realisations to read, which is too few for these measures.`)
					+ leftOut(dist.dropped)));
			}
			const shown = !!(dist && dist.ok);
			if (shown) {
				body.append(el('p', { className: 'sens-r2' },
					`RSA splits the ${dist.used.toLocaleString()} realisations at the output’s `
					+ `${dist.splitAt ?? 'mean'}, ${fmtValue(dist.threshold)}: ${dist.behavioural.toLocaleString()} `
					+ `above it. Ten dummy inputs the model never saw reach a KS distance of `
					+ `${dist.ksDummyMean.toFixed(3)} ± ${dist.ksDummySd.toFixed(3)} by chance alone.`
					+ leftOut(dist.dropped)));
			}
			const box = el('div', { className: `sens-table${wide ? ' is-wide' : ''}${shown ? ' is-dist' : ''}` },
				el('div', { className: 'sens-head' },
					el('span', {}, 'Input'),
					el('span', { title: 'Rank correlation: any monotone relationship.' }, 'Spearman'),
					...(shown ? [
						el('span', { title: 'EASI’s first-order index (Plischke), corrected for the bias a '
							+ 'random sample leaves in it: the share of the variance this input explains '
							+ 'alone, of any shape, from the spectrum along its sorted values.' }, 'EASI S₁'),
						el('span', { title: 'Borgonovo’s moment-independent δ, bias-adjusted by bootstrap: '
							+ 'how far knowing this input moves the output’s whole distribution, not only '
							+ 'its variance. 0 to 1. Estimated on the output’s normal scores, which leaves δ '
							+ 'unchanged and gives the density estimate something it can resolve.',
						className: 'sens-head-greek' }, 'δ'),
						el('span', { title: 'Mutual information, in bits, less what shuffling the output gives '
							+ 'at its 95th percentile: what is left is what chance does not explain. On ranks, '
							+ 'which leave it unchanged and give every histogram bin its share.' }, 'MI'),
						el('span', { title: 'Regional sensitivity: the Kolmogorov-Smirnov distance between this '
							+ 'input’s values in the realisations above the output’s mean and in those '
							+ 'below. Compare with the dummies above.' }, 'RSA KS'),
						el('span', { title: 'PAWN (Pianosi and Wagener), as SALib has it: hold this input to '
							+ 'each of ten slices of its range and measure how far the output’s distribution '
							+ 'moves, by the Kolmogorov-Smirnov distance to the whole; the median over the '
							+ 'slices. 0 to 1.' }, 'PAWN'),
						el('span', { title: 'Discrepancy (Puy, Roy and Saltelli), as SALib has it: how far this '
							+ 'input’s scatter against the output is from covering the square evenly, read on '
							+ 'the ranks of both, as a share of the total over '
							+ (dist.discrepancyOver === 'all' ? 'every input that varies.' : 'the inputs listed '
								+ '— over all of them would take too long on a sample this size.') }, 'Discr.'),
					] : [el('span', { title: 'Linear correlation.' }, 'Pearson')]),
					...(wide ? [
						el('span', { title: 'Standardized regression coefficient: this input’s own linear '
							+ 'share of the output, given the others, in standard deviations. '
							+ 'Comparable between inputs, which is why the table is ranked by it. '
							+ 'On ranks: SRRC.' }, shownTranslate === 'rank' ? 'SRRC' : 'SRC'),
						el('span', { title: shownTranslate === 'log'
							? 'The coefficient in units: the elasticity, a percentage in the output '
								+ 'per percentage in this input, with the others held.'
							: 'The coefficient in units: how much the output moves per unit of this '
								+ 'input, with the others held. The same fit as SRC, not '
								+ 'standardized — so it can be read against what the input is, '
								+ 'and cannot be compared between inputs.',
						className: 'sens-head-sym' }, 'b'),
						el('span', { title: 'Partial correlation: the relationship left once the other '
							+ 'inputs’ linear effects are removed from both. On ranks: PRCC.' },
						shownTranslate === 'rank' ? 'PRCC' : 'PCC'),
						el('span', { title: 'First-order index: the share of the output’s variance that '
							+ 'knowing this input alone would remove, of any shape. Estimated by binning.' }, 'S₁'),
					] : [])));
			table.forEach((r, i) => {
				const d = shown ? dist.rows[i] : null;
				box.append(el('div', { className: 'sens-row' },
					el('code', { title: inputName(r) }, inputName(r)),
					bar(r.spearman),
					...(shown
						? [bar(d?.easi ?? NaN), bar(d?.delta ?? NaN), coef(d?.miS ?? NaN), bar(d?.ks ?? NaN),
							bar(d?.pawn ?? NaN), bar(d?.discrepancy ?? NaN)]
						: [bar(r.pearson)]),
					...(wide ? [bar(m.src[i]), coef(m.b?.[i]), bar(m.pcc[i]), bar(m.s1[i])] : [])));
			});
			if (!table.length) {
				box.append(el('p', { className: 'hint' },
					`Nothing correlates with this output ${when === 'own' ? 'at its peaks' : 'at this time'} — `
					+ 'either it does not vary there, or none of the sampled inputs reach it.'));
			}
			body.append(box);

			body.append(el('p', { className: 'sens-note' }, shown
				? 'Ranked by the rank correlation. EASI’s S₁ and δ find a relationship of any shape — '
					+ 'one that peaks in the middle of an input’s range and correlates with nothing — '
					+ 'and δ one that moves the spread or the tail rather than the mean; mutual '
					+ 'information is what knowing the input tells about the output, in bits, above '
					+ 'what chance gives; RSA is how differently the input is distributed in the '
					+ 'realisations above the mean and below it. PAWN is how far holding the input to a '
					+ 'slice moves the output’s distribution, and discrepancy how unevenly its scatter '
					+ 'against the output fills the square. GlobalSensitivity.jl’s estimators and SALib’s, '
					+ 'from the same realisations.'
				: 'Ranked by the rank correlation, which finds any monotone relationship; '
				+ 'Pearson beside it finds only a straight-line one. Where the two '
				+ 'disagree the relationship is curved — which for a log-scaled input '
				+ 'driving a dose is the normal case, not a warning.'
				+ (wide
					? ' SRC and PCC come from one regression of the output on every input at '
						+ 'once, so they separate inputs the output happens to track together; '
						+ 'S₁ finds a relationship of any shape, including one that peaks in the '
						+ 'middle of an input’s range and correlates with nothing.'
					: '')));

			const done = el('button', { type: 'button', className: 'primary' }, 'Close');
			done.addEventListener('click', () => modal.close());
			body.append(el('div', { className: 'pdf-foot' },
				el('span', { className: 'pdf-note' },
					asking
						? 'Working it out…'
						: 'From the sample already drawn — no further runs.'),
				done));
		},
	});

	return {
		dialog: modal.dialog,
		close: () => modal.close(),
		/** An answer arrived: show it here rather than in a dialog on top. */
		update(next) {
			view = { ...view, ...next, family: asked.family, translate: asked.translate };
			asking = false;
			modal.refresh();
		},
		/**
		 * The same question again, as the dialog now puts it -- for when what
		 * answers it has changed underneath, as screening realisations out
		 * does. Asked from outside with no time, it came back for the last
		 * time whatever *At* said.
		 */
		reask() {
			asking = false;
			ask({});
		},
	};
}
