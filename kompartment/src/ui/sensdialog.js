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
	['distribution', 'Distribution: EASI, δ, MI, RSA',
		'Measures that read the output’s whole distribution rather than a straight line through '
		+ 'it: EASI’s first-order index, Borgonovo’s δ, mutual information and regional '
		+ 'sensitivity. A bootstrap per input, so a few seconds on a large sample.'],
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
 */
export function paintCurves(canvas, t, curves, names, scale = null) {
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
 * @param {number} opts.at       the time the table is for
 * @param {Array} opts.rows      from the worker: name, where, pearson, spearman
 * @param {Array} opts.curves    the few that matter, over time
 * @param {number} opts.iterations
 * @param {string} opts.timeUnit
 * @param {(ask: {index: number, at: number}) => void} opts.onAsk  ask again
 * @param {() => void} [opts.onClose]
 * @returns {{update: (next: object) => void, close: () => void}}
 */
export function openSensitivityDialog({
	output, outputs = [], index = 0, t, at, rows, curves, iterations, measures = null,
	distribution = null, kept = null, timeUnit = 'year', onAsk, onClose,
}) {
	// What is on screen. Replaced wholesale when an answer arrives, so the
	// dialog is built from one object and there is no half-updated state.
	let view = { output, outputs, index, t, at, rows, curves, iterations, measures, distribution, kept };
	// What the regression family is fitted to: the values, their ranks (SRRC
	// and PRCC), or their logarithms. See ../domain/sensitivity.js.
	let translate = 'none';
	// Which measures stand beside the correlations: the regression family,
	// or the ones that read the output's whole distribution -- EASI, δ, mutual
	// information and RSA, from ../domain/gsa.js.
	let family = 'regression';
	// Whether the time was chosen or asked for as "wherever it peaks". Kept
	// apart from `view.at`, which is always a resolved index: asking for the
	// peak and then changing the output has to find the *new* output's peak,
	// and sending the old one's index back would quietly pin it there.
	let atPeak = false;
	// Set while the worker is being waited on, so the pickers cannot be used to
	// queue up three questions whose answers arrive in any order.
	let asking = false;

	const ask = (next) => {
		if (asking) return;
		asking = true;
		modal.refresh();
		onAsk?.({ index: view.index, at: atPeak ? 'peak' : view.at, translate, family, ...next });
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
					lines.map((c) => inputName(table.find((r) => r.k === c.k)))));
			}

			// --- and the table, at one time.
			const pick = el('select', { className: 'sens-time', disabled: asking });
			// The time a reader actually means by "at the peak", and the one
			// they cannot pick out of four hundred: wherever this output is
			// largest averaged over the realisations. Which time that is comes
			// back with the answer, so the entry says it.
			pick.append(el('option', {
				value: 'peak', selected: atPeak,
				title: 'Wherever this output is largest averaged over the realisations — '
					+ 'not the peak of any one of them.',
			}, atPeak
				? `where it peaks on average — ${fmtTime(time[view.at])} ${timeUnit}`
				: 'where it peaks on average'));
			for (let j = 0; j < time.length; j++) {
				// Through the same formatter the chart and the table use: a log
				// grid gives times like 5746.434968715976, and four hundred of
				// those in a list is unreadable.
				pick.append(el('option', { value: String(j), selected: !atPeak && j === view.at },
					`${fmtTime(time[j])} ${timeUnit}`));
			}
			pick.addEventListener('change', () => {
				atPeak = pick.value === 'peak';
				ask({ at: atPeak ? 'peak' : Number(pick.value) });
			});
			body.append(el('div', { className: 'pdf-row pdf-row-wide' },
				el('label', {}, 'At'), pick));

			const fam = el('select', { className: 'sens-family', disabled: asking });
			for (const [value, label, why] of FAMILIES) {
				fam.append(el('option', { value, selected: value === family, title: why }, label));
			}
			fam.addEventListener('change', () => { family = fam.value; ask({}); });
			body.append(el('div', { className: 'pdf-row' },
				el('label', { title: 'Which measures stand beside the two correlations.' }, 'Measures'), fam));
			const dist = family === 'distribution' ? view.distribution : null;

			// The regression family beside the two correlations, when the worker
			// could compute it, and what it was fitted to. On ranks SRC and PCC
			// are SRRC and PRCC, which is what to read for the
			// monotone-and-bent relationships here; on logs the coefficient is
			// an elasticity.
			const m = family === 'regression' ? view.measures : null;
			const wide = !!(m && m.ok);
			if (m) {
				const how = el('select', { className: 'sens-translate', disabled: asking });
				for (const [value, label, why] of TRANSLATIONS) {
					how.append(el('option', { value, selected: value === translate, title: why }, label));
				}
				how.addEventListener('change', () => { translate = how.value; ask({}); });
				body.append(el('div', { className: 'pdf-row' },
					el('label', { title: 'What the regression is fitted to. It does not change '
						+ 'Spearman, which is already a rank correlation, and cannot change '
						+ 'any measure that only cares about order.' },
					'Translate'), how));
				// On its own line. In the row above it the sentence wrapped
				// inside a column a third of the dialog wide, and the four
				// lines it took left the rest of the row empty.
				body.append(el('p', { className: `sens-r2${m.ok ? '' : ' is-bad'}` }, m.ok
					? `R² = ${m.r2.toFixed(3)}${TRANSLATED[translate]} — the share of the spread `
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
			if (family === 'distribution' && dist && !dist.ok) {
				body.append(el('p', { className: 'sens-r2 is-bad' }, dist.flat
					? 'The output is the same in every realisation here, so there is no distribution to compare.'
					: `Only ${dist.used} realisations to read, which is too few for these measures.`));
			}
			const shown = !!(dist && dist.ok);
			if (shown) {
				body.append(el('p', { className: 'sens-r2' },
					`RSA splits the ${dist.used.toLocaleString()} realisations at the output’s mean, `
					+ `${fmtValue(dist.threshold)}: ${dist.behavioural.toLocaleString()} above it. Ten dummy `
					+ `inputs the model never saw reach a KS distance of ${dist.ksDummyMean.toFixed(3)} `
					+ `± ${dist.ksDummySd.toFixed(3)} by chance alone.`));
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
					] : [el('span', { title: 'Linear correlation.' }, 'Pearson')]),
					...(wide ? [
						el('span', { title: 'Standardized regression coefficient: this input’s own linear '
							+ 'share of the output, given the others, in standard deviations. '
							+ 'Comparable between inputs, which is why the table is ranked by it. '
							+ 'On ranks: SRRC.' }, translate === 'rank' ? 'SRRC' : 'SRC'),
						el('span', { title: translate === 'log'
							? 'The coefficient in units: the elasticity, a percentage in the output '
								+ 'per percentage in this input, with the others held.'
							: 'The coefficient in units: how much the output moves per unit of this '
								+ 'input, with the others held. The same fit as SRC, not '
								+ 'standardized — so it can be read against what the input is, '
								+ 'and cannot be compared between inputs.',
						className: 'sens-head-sym' }, 'b'),
						el('span', { title: 'Partial correlation: the relationship left once the other '
							+ 'inputs’ linear effects are removed from both. On ranks: PRCC.' },
						translate === 'rank' ? 'PRCC' : 'PCC'),
						el('span', { title: 'First-order index: the share of the output’s variance that '
							+ 'knowing this input alone would remove, of any shape. Estimated by binning.' }, 'S₁'),
					] : [])));
			table.forEach((r, i) => {
				const d = shown ? dist.rows[i] : null;
				box.append(el('div', { className: 'sens-row' },
					el('code', { title: inputName(r) }, inputName(r)),
					bar(r.spearman),
					...(shown
						? [bar(d?.easi ?? NaN), bar(d?.delta ?? NaN), coef(d?.miS ?? NaN), bar(d?.ks ?? NaN)]
						: [bar(r.pearson)]),
					...(wide ? [bar(m.src[i]), coef(m.b?.[i]), bar(m.pcc[i]), bar(m.s1[i])] : [])));
			});
			if (!table.length) {
				box.append(el('p', { className: 'hint' },
					'Nothing correlates with this output at this time — either it does not '
					+ 'vary here, or none of the sampled inputs reach it.'));
			}
			body.append(box);

			body.append(el('p', { className: 'sens-note' }, shown
				? 'Ranked by the rank correlation. EASI’s S₁ and δ find a relationship of any shape — '
					+ 'one that peaks in the middle of an input’s range and correlates with nothing — '
					+ 'and δ one that moves the spread or the tail rather than the mean; mutual '
					+ 'information is what knowing the input tells about the output, in bits, above '
					+ 'what chance gives; RSA is how differently the input is distributed in the '
					+ 'realisations above the mean and below it. GlobalSensitivity.jl’s estimators, '
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
			view = { ...view, ...next };
			asking = false;
			modal.refresh();
		},
	};
}
