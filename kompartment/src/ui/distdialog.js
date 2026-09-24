/**
 * One output at one time, as a distribution.
 *
 * The band on the chart is two percentiles at every time. This is the whole
 * distribution at one of them: how the realisations are spread, how sure the
 * mean is, and -- the question a band cannot answer -- what the probability
 * is of exceeding a given value. GoldSim's Distribution Summary, in this tool's
 * clothes: the numbers from ../domain/distribution.js, a density and a
 * cumulative curve, and a calculator between value and probability that
 * answers from the sorted column already here rather than asking the worker.
 *
 * The confidence band on the cumulative curve is the Dvoretzky–Kiefer–
 * Wolfowitz one: with N realisations, the true distribution function is
 * within ±ε of the sampled one everywhere, at 95%, where ε = √(ln(2/0.05)/2N).
 * It holds for any shape, which is the point -- a dose is not normal and a
 * band that assumed it was would be a band about the wrong thing.
 *
 * Over the histogram, curves: the distribution a varied parameter was drawn
 * from, which says whether the draws are what was asked for, and any of the
 * distributions ../domain/fit.js fits to the sample, ranked by how well they
 * describe it. Each is drawn as the count a bar would expect under it, so a
 * curve and the bars are on one scale on either axis, and again as its
 * cumulative curve beside the sample's, where the Kolmogorov–Smirnov gap is.
 */

import { el } from './parts.js';
import { openModal } from './modal.js';
import { fmtTime } from '../domain/timeseries.js';
import { valueAt, probabilityOf, conditionalTailExpectation, histogram } from '../domain/distribution.js';
import { densityAt, cumulativeAt, valueCuts, formatPDF } from '../domain/pdf.js';
import {
	FIT_METHODS, FIT_TESTS, FIT_MIN_SAMPLE, fitAll, rankFits, scoreFit, fitText,
} from '../domain/fit.js';

/**
 * The three things *At* can mean, as in What drove it: each realisation's own
 * peak, whenever it comes; the realisations at the one time the output peaks
 * on average; or at a chosen time.
 */
const WHEN = [
	['own', 'each realisation’s peak',
		'The largest value each realisation reaches, whenever it reaches it: the distribution of the peaks.'],
	['mean', 'where it peaks on average',
		'Every realisation’s value at the one time this output is largest averaged over them.'],
	['time', 'a chosen time',
		'Every realisation’s value at a time picked from the output grid; the last one to start with.'],
];

/**
 * The axis the density and the cumulative curve are drawn on. Automatic is
 * logarithmic when the middle 90% of the sample spans more than two decades,
 * which a dose usually does and a pressure does not.
 */
const SCALES = [
	['auto', 'automatic', 'Logarithmic when the middle 90% of the realisations spans more than a factor of 100, linear otherwise.'],
	['linear', 'linear', 'The values as they are.'],
	['log', 'logarithmic', 'The logarithm of the values: bins of equal width in decades, and a cumulative curve on '
		+ 'the same axis. Only for a sample that is above zero throughout.'],
];

/**
 * Each fitted shape's colour, from the chart palette past the bars' own
 * (`--series-1` is the accent), and the double triangles in their plain
 * sibling's colour, dashed: eight shapes for seven colours, and the pairing
 * says something true. The specified distribution is ink, dotted.
 */
const FIT_STYLE = {
	unif: { color: '--series-6', dash: [] },
	triang: { color: '--series-5', dash: [] },
	dtriang: { color: '--series-5', dash: [6, 3] },
	norm: { color: '--series-4', dash: [] },
	logu: { color: '--series-7', dash: [] },
	logt: { color: '--series-3', dash: [] },
	logdt: { color: '--series-3', dash: [6, 3] },
	logn: { color: '--series-2', dash: [] },
};
const SPEC_STYLE = { color: '--text-primary', dash: [2, 3] };

/** A swatch for a curve in the legend and the table: its colour, its dash. */
function swatch(style) {
	return el('span', {
		className: 'fit-swatch',
		style: `border-top-color: var(${style.color}); border-top-style: ${style.dash.length ? 'dashed' : 'solid'};`,
	});
}

/**
 * Where a curve turns a corner: the ends and the mode, and where a truncation
 * cuts it. Drawn on either side of each, so a uniform's edge is an edge and
 * not a slope one sample wide.
 */
function cornersOf(spec) {
	const p = spec.params ?? {};
	const cut = valueCuts(spec);
	return [p.min, p.max, p.mode, cut.lo, cut.hi].filter((v) => v != null && Number.isFinite(v));
}

/** The x values to draw a curve at, `steps` across the axis and its corners. */
function curveXs(spec, lo, hi, log, steps) {
	const xs = [];
	for (let i = 0; i <= steps; i++) {
		const f = i / steps;
		xs.push(log ? Math.exp(Math.log(lo) + f * (Math.log(hi) - Math.log(lo))) : lo + f * (hi - lo));
	}
	for (const c of cornersOf(spec)) {
		if (!(c > lo && c < hi)) continue;
		const e = Math.abs(c) * 1e-9 || 1e-300;
		xs.push(c - e, c, c + e);
	}
	return xs.sort((a, b) => a - b);
}

/** A number the way the table shows it. */
export function fmtStat(v) {
	if (!Number.isFinite(v)) return '—';
	const a = Math.abs(v);
	if (a === 0) return '0';
	if (a >= 1e5 || a < 1e-3) return v.toExponential(3);
	return v.toPrecision(4);
}

/**
 * Density on the left, cumulative on the right, one canvas; `curves` over
 * both, each `{spec, color, dash}` with `color` a custom property's name.
 */
function paint(canvas, sorted, hist, summary, curves = []) {
	const ctx = canvas.getContext('2d');
	if (!ctx) return;
	const dpr = window.devicePixelRatio || 1;
	const w = canvas.clientWidth || 480;
	const h = canvas.clientHeight || 170;
	canvas.width = Math.round(w * dpr);
	canvas.height = Math.round(h * dpr);
	ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
	ctx.clearRect(0, 0, w, h);
	const n = sorted.length;
	if (n < 2) return;

	const style = getComputedStyle(canvas);
	const ink = style.getPropertyValue('--text-muted').trim() || '#888';
	const faint = style.getPropertyValue('--border').trim() || '#333';
	const accent = style.getPropertyValue('--accent').trim() || '#2a78d6';
	const pad = { l: 8, r: 8, t: 8, b: 18 };
	const gap = 18;
	const pw = (w - pad.l - pad.r - gap) / 2;
	const ph = h - pad.t - pad.b;
	const lo = hist.edges[0];
	const hi = hist.edges[hist.edges.length - 1];
	const along = (x) => (hist.log
		? (Math.log(x) - Math.log(lo)) / (Math.log(hi) - Math.log(lo))
		: (x - lo) / (hi - lo));
	const sx = (x, x0) => x0 + Math.min(1, Math.max(0, along(x))) * pw;
	ctx.font = '9px system-ui, sans-serif';
	ctx.textBaseline = 'top';

	// The curves, sampled once for both panels. A curve's height on the
	// density panel is the count a bar would expect under it: n·f(x)·Δx for
	// bins of equal width, n·f(x)·x·Δln x for bins of equal width in log --
	// so it is on the bars' scale whichever axis they are on.
	const drawn = hi > lo ? curves.map((c) => {
		const xs = curveXs(c.spec, lo, hi, hist.log, Math.max(60, Math.round(pw)));
		const per = hist.log ? (Math.log(hi) - Math.log(lo)) / hist.counts.length : (hi - lo) / hist.counts.length;
		return {
			...c,
			xs,
			expect: xs.map((x) => n * densityAt(c.spec, x) * (hist.log ? x : 1) * per),
			below: xs.map((x) => cumulativeAt(c.spec, x)),
			ink: style.getPropertyValue(c.color).trim() || ink,
		};
	}) : [];
	const stroke = (c, ys, x0, sy) => {
		ctx.strokeStyle = c.ink;
		ctx.lineWidth = 1.7;
		ctx.setLineDash(c.dash ?? []);
		ctx.beginPath();
		let on = false;
		for (let i = 0; i < c.xs.length; i++) {
			const y = ys[i];
			if (!Number.isFinite(y)) { on = false; continue; }
			const px = x0 + along(c.xs[i]) * pw;
			if (on) ctx.lineTo(px, sy(y)); else ctx.moveTo(px, sy(y));
			on = true;
		}
		ctx.stroke();
		ctx.setLineDash([]);
		ctx.lineWidth = 1;
	};
	const clipTo = (x0) => {
		ctx.save();
		ctx.beginPath();
		ctx.rect(x0, pad.t - 1, pw, ph + 2);
		ctx.clip();
	};

	// --- density: the histogram, as bars.
	{
		const x0 = pad.l;
		// Room for a curve that rises above the bars, up to twice the tallest:
		// past that it is cut at the top rather than flattening the sample.
		const bars = Math.max(1, ...hist.counts);
		let rise = 0;
		for (const c of drawn) for (const v of c.expect) if (Number.isFinite(v) && v > rise) rise = v;
		const peak = Math.max(bars, Math.min(rise, 2 * bars));
		ctx.fillStyle = accent;
		ctx.globalAlpha = 0.55;
		for (let b = 0; b < hist.counts.length; b++) {
			const a = sx(hist.edges[b], x0);
			const c = sx(hist.edges[b + 1], x0);
			const bh = (hist.counts[b] / peak) * ph;
			ctx.fillRect(a + 0.5, pad.t + ph - bh, Math.max(1, c - a - 1), bh);
		}
		ctx.globalAlpha = 1;
		clipTo(x0);
		for (const c of drawn) stroke(c, c.expect, x0, (v) => pad.t + ph - (v / peak) * ph);
		ctx.restore();
		ctx.strokeStyle = faint;
		ctx.beginPath();
		ctx.moveTo(x0, pad.t + ph + 0.5);
		ctx.lineTo(x0 + pw, pad.t + ph + 0.5);
		ctx.stroke();
		ctx.fillStyle = ink;
		ctx.textAlign = 'left';
		ctx.fillText(fmtStat(lo), x0, pad.t + ph + 4);
		ctx.textAlign = 'right';
		ctx.fillText(fmtStat(hi), x0 + pw, pad.t + ph + 4);
		ctx.textAlign = 'center';
		ctx.fillText(`density${hist.log ? ' (log axis)' : ''}`, x0 + pw / 2, pad.t + ph + 4);
	}

	// --- cumulative: the step function with its DKW band.
	{
		const x0 = pad.l + pw + gap;
		const sy = (p) => pad.t + (1 - p) * ph;
		const eps = summary.dkw;
		// The band first, as a filled region between F±ε clamped to [0, 1].
		ctx.fillStyle = accent;
		ctx.globalAlpha = 0.14;
		ctx.beginPath();
		ctx.moveTo(sx(sorted[0], x0), sy(Math.min(1, eps)));
		for (let i = 0; i < n; i++) ctx.lineTo(sx(sorted[i], x0), sy(Math.min(1, (i + 1) / n + eps)));
		for (let i = n - 1; i >= 0; i--) ctx.lineTo(sx(sorted[i], x0), sy(Math.max(0, (i + 1) / n - eps)));
		ctx.closePath();
		ctx.fill();
		ctx.globalAlpha = 1;
		// Grid at the quartiles.
		ctx.strokeStyle = faint;
		for (const p of [0.25, 0.5, 0.75]) {
			ctx.globalAlpha = 0.5;
			ctx.beginPath();
			ctx.moveTo(x0, sy(p) + 0.5);
			ctx.lineTo(x0 + pw, sy(p) + 0.5);
			ctx.stroke();
		}
		ctx.globalAlpha = 1;
		ctx.strokeStyle = accent;
		ctx.lineWidth = 1.6;
		ctx.beginPath();
		ctx.moveTo(sx(sorted[0], x0), sy(0));
		for (let i = 0; i < n; i++) {
			const x = sx(sorted[i], x0);
			ctx.lineTo(x, sy(i / n));
			ctx.lineTo(x, sy((i + 1) / n));
		}
		ctx.stroke();
		ctx.lineWidth = 1;
		clipTo(x0);
		for (const c of drawn) stroke(c, c.below, x0, sy);
		ctx.restore();
		ctx.strokeStyle = faint;
		ctx.beginPath();
		ctx.moveTo(x0, pad.t + ph + 0.5);
		ctx.lineTo(x0 + pw, pad.t + ph + 0.5);
		ctx.stroke();
		ctx.fillStyle = ink;
		ctx.textAlign = 'center';
		ctx.fillText(`cumulative, 95% band ±${(eps * 100).toFixed(1)}%`, x0 + pw / 2, pad.t + ph + 4);
		ctx.textAlign = 'left';
		ctx.fillText('1', x0 + 2, pad.t);
		ctx.fillText('0', x0 + 2, pad.t + ph - 10);
	}
}

/** A p-value, or a statistic, the way the fit table shows it. */
const fmtP = (p) => (!Number.isFinite(p) ? '—' : p < 0.001 ? '<0.001' : p.toFixed(3));
const fmtScore = (v) => {
	if (v === Infinity) return '∞';
	if (!Number.isFinite(v)) return '—';
	const a = Math.abs(v);
	if (a !== 0 && (a < 1e-4 || a >= 1e5)) return v.toExponential(2);
	// Three figures, but a whole number as one: toPrecision writes 5030 as 5.03e+3.
	return a >= 1000 ? String(Math.round(v)) : v.toPrecision(3);
};

/** Why a row's A² and AIC are infinite, when they are. */
const outsideNote = (f) => (f.outside > 0
	? el('small', { className: 'is-warn' }, `${f.outside.toLocaleString()} realisation${f.outside === 1 ? ' lies' : 's lie'} `
		+ 'where it has no probability')
	: null);

/**
 * The fits, ranked by `test`, with the specified distribution above them.
 *
 * AIC is shown less the smallest in the table: its absolute value depends on
 * the units the output is in, and only the differences mean anything -- under
 * two is no real preference, over ten is a clear one.
 */
function fitTable(fitted, test, { spec, showSpec, shown, onSpec, onShow }) {
	const ranked = rankFits(fitted.fits, test);
	const aics = [...ranked.filter((f) => !f.why).map((f) => f.aic), fitted.own?.aic ?? Infinity]
		.filter(Number.isFinite);
	const floor = aics.length ? Math.min(...aics) : 0;
	const key = (k) => (k === test ? ' is-key' : '');
	const box = el('div', { className: 'fit-table' });
	box.append(el('div', { className: 'fit-head' },
		el('span', {}), el('span', {}, '#'), el('span', {}, 'Distribution'),
		el('span', { className: `fit-num${key('ks')}`, title: FIT_TESTS[1][2] }, 'K–S D'),
		el('span', { className: `fit-num${key('ks')}` }, 'p'),
		el('span', { className: `fit-num${key('ad')}`, title: FIT_TESTS[0][2] }, 'A²'),
		el('span', { className: `fit-num${key('ad')}` }, 'p'),
		el('span', { className: `fit-num${key('aic')}`, title: FIT_TESTS[2][2] }, 'ΔAIC')));
	const numbers = (f) => [
		el('span', { className: `fit-num mono${key('ks')}` }, fmtScore(f.ks)),
		el('span', { className: `fit-num mono${key('ks')}` }, fmtP(f.ksP)),
		el('span', { className: `fit-num mono${key('ad')}` }, fmtScore(f.ad)),
		el('span', { className: `fit-num mono${key('ad')}` }, fmtP(f.adP)),
		el('span', { className: `fit-num mono${key('aic')}`,
			title: f.aic === Infinity ? 'A realisation lies where this distribution has no probability.' : '' },
		f.aic === Infinity ? '∞' : (f.aic - floor).toFixed(1)),
	];
	if (spec && fitted.own) {
		const tick = el('input', { type: 'checkbox', checked: showSpec, 'aria-label': 'Draw the specified distribution' });
		tick.addEventListener('change', () => onSpec(tick.checked));
		box.append(el('div', { className: 'fit-row is-spec' }, tick, el('span', {}, '—'),
			el('span', { className: 'fit-name' }, el('span', {}, swatch(SPEC_STYLE), 'As specified'),
				el('code', {}, formatPDF(spec)), outsideNote(fitted.own)),
			...numbers(fitted.own)));
	}
	let rank = 0;
	for (const f of ranked) {
		if (f.why) {
			box.append(el('div', { className: 'fit-row is-none' }, el('span', {}), el('span', {}),
				el('span', { className: 'fit-name' }, el('span', {}, f.label), el('small', {}, f.why))));
			continue;
		}
		rank++;
		const tick = el('input', { type: 'checkbox', checked: shown.has(f.family), 'aria-label': `Draw the ${f.label}` });
		tick.addEventListener('change', () => onShow(f.family, tick.checked));
		box.append(el('div', { className: 'fit-row', title: f.note ?? '' }, tick, el('span', {}, String(rank)),
			el('span', { className: 'fit-name' },
				el('span', {}, swatch(FIT_STYLE[f.family]), f.label),
				el('code', {}, fitText(f.spec)),
				f.note ? el('small', {}, f.note) : null, outsideNote(f)),
			...numbers(f)));
	}
	return box;
}

/**
 * @param {object} opts
 * @param {string} opts.output      the series
 * @param {string[]} opts.outputs   every series the run kept
 * @param {number} opts.index
 * @param {Float64Array} opts.t
 * @param {number|null} opts.at     which time, as an index; null for each realisation's own peak
 * @param {object|null} [opts.peaks] when those peaks fall: `{median, low, high}`
 * @param {object} opts.summary     from `describeSample`
 * @param {Float64Array} opts.column  the sorted realisations -- the histogram is
 *   drawn from these here, on whichever axis is chosen
 * @param {number} opts.of          how many realisations the run had
 * @param {object|null} [opts.spec] the distribution a varied parameter was
 *   drawn from (../domain/pdf.js); null for anything the model computed
 * @param {boolean} [opts.screened] the categories leave realisations out
 * @param {string} opts.unit
 * @param {string} opts.timeUnit
 * @param {(ask: {index: number, at: number|'peak'|'max'}) => void} opts.onAsk
 */
export function openDistributionDialog({
	output, outputs = [], index = 0, t, at, peaks = null, summary, column, of,
	spec = null, screened = false, unit = '', timeUnit = 'year', onAsk, onClose,
}) {
	// The histogram is not part of this: it is made here from `column`, so it
	// cannot be left behind by an answer. It used to arrive from the worker as
	// `histogram` and be kept as `hist`, and every answer after the first
	// updated the one name the drawing did not read -- the statistics and the
	// cumulative curve followed a change of series and the density did not.
	let view = { output, outputs, index, t, at, peaks, summary, column, of, spec, screened, unit };
	let asking = false;
	// Which of the three questions (WHEN), and the chosen time: the last to
	// start with, kept while the others are asked.
	let when = 'time';
	let chosen = Number.isInteger(at) ? at : Math.max(0, (t?.length ?? 1) - 1);
	const question = () => (when === 'own' ? 'max' : when === 'mean' ? 'peak' : chosen);
	// The axis, which is drawing only: no question to the worker.
	let scale = 'auto';
	// The calculator's own state, kept across refreshes.
	let askValue = '';
	let askProb = '95';
	let tailQ = '95';
	// The curves. The specified distribution is drawn whenever there is one.
	// Fitting is asked for once and then done for every sample shown after
	// it -- another output, another time -- by the method chosen; the fits
	// are kept with the column they were made from, so a redraw for a tick
	// box does not fit again. `shown` is which shapes are drawn, by shape,
	// so it survives a refit.
	let showSpec = true;
	let fitOn = false;
	let fitMethod = 'mle';
	let fitTest = 'ad';
	let fitted = null;
	let fitTimer = 0;
	let closed = false;
	const shown = new Set();
	// A curve there is one of: filled in, and not a list of values.
	const drawable = (sp) => !!sp && Number.isFinite(cumulativeAt(sp, 0));
	const fitsCurrent = () => fitted && fitted.column === view.column && fitted.method === fitMethod;
	// Off the click, so the page can say it is working first: the four
	// triangles by maximum likelihood are a search each, a fifth of a second
	// for ten thousand realisations.
	const fitLater = () => {
		if (fitTimer) return;
		fitTimer = setTimeout(() => {
			fitTimer = 0;
			if (closed || !fitOn) return;
			const col = view.column;
			const fits = fitAll(col, fitMethod);
			const own = drawable(view.spec) ? scoreFit(col, view.spec, 0) : null;
			const first = !fitted;
			fitted = { column: col, method: fitMethod, fits, own };
			if (first && !shown.size) {
				const best = rankFits(fits, fitTest)[0];
				if (best && !best.why) shown.add(best.family);
			}
			modal.refresh();
		}, 20);
	};

	const ask = (next) => {
		if (asking) return;
		asking = true;
		modal.refresh();
		onAsk?.({ index: view.index, at: question(), ...next });
	};

	const modal = openModal({
		wide: true,
		title: () => `Distribution of ${view.output}`,
		subtitle: () => `${view.summary.n.toLocaleString()} of ${view.of.toLocaleString()} realisations`
			+ (view.at == null ? ', each at its own peak'
				: ` at ${fmtTime(view.t[view.at])} ${timeUnit}${when === 'mean' ? ', where it peaks on average' : ''}`)
			+ (view.unit ? ` — in ${view.unit}` : ''),
		onClose: () => { closed = true; clearTimeout(fitTimer); onClose?.(); },
		build: (body) => {
			const { summary: s, column: col } = view;

			if (view.outputs.length > 1) {
				const ofSel = el('select', { className: 'sens-of', disabled: asking });
				view.outputs.slice(0, 300).forEach((label, k) => {
					ofSel.append(el('option', { value: String(k), selected: k === view.index }, label));
				});
				ofSel.addEventListener('change', () => ask({ index: Number(ofSel.value) }));
				body.append(el('div', { className: 'pdf-row pdf-row-wide' }, el('label', {}, 'Of'), ofSel));
			}
			// *At*, as in What drove it: which question, and for a chosen time,
			// which time, on one line.
			const how = el('select', { className: 'sens-when', disabled: asking });
			for (const [value, label, why] of WHEN) {
				const text = value === 'mean' && when === 'mean' && Number.isInteger(view.at)
					? `${label} — ${fmtTime(view.t[view.at])} ${timeUnit}` : label;
				how.append(el('option', { value, selected: value === when, title: why }, text));
			}
			how.addEventListener('change', () => { when = how.value; ask({}); });
			const atRow = el('span', { className: 'sens-at' }, how);
			if (when === 'time') {
				const pick = el('select', { className: 'sens-time', disabled: asking, 'aria-label': 'Time' });
				for (let j = 0; j < view.t.length; j++) {
					pick.append(el('option', { value: String(j), selected: j === chosen },
						`${fmtTime(view.t[j])} ${timeUnit}`));
				}
				pick.addEventListener('change', () => { chosen = Number(pick.value); ask({}); });
				atRow.append(pick);
			}
			body.append(el('div', { className: 'pdf-row pdf-row-wide' }, el('label', {}, 'At'), atRow));
			if (when === 'own' && view.at == null) {
				const p = view.peaks;
				body.append(el('p', { className: 'hint' }, p
					? 'The largest value each realisation reaches, whenever it reaches it. They peak '
						+ `between ${fmtTime(p.low)} and ${fmtTime(p.high)} ${timeUnit} (5th to 95th `
						+ `percentile), at ${fmtTime(p.median)} ${timeUnit} in the median realisation.`
					: 'The largest value each realisation reaches, whenever it reaches it.'));
			}

			// The axis: drawing only, answered here.
			const axis = el('select', { className: 'dist-scale' });
			for (const [value, label, why] of SCALES) {
				axis.append(el('option', { value, selected: value === scale, title: why }, label));
			}
			axis.addEventListener('change', () => { scale = axis.value; modal.refresh(); });
			body.append(el('div', { className: 'pdf-row' },
				el('label', { title: 'The axis of the density and the cumulative curve. The statistics and '
					+ 'the calculator are of the values whichever it is.' }, 'Scale'), axis));
			const hist = histogram(col, null, scale);
			if (hist.refused) {
				const below = col.findIndex((v) => v > 0);
				const n = below < 0 ? col.length : below;
				body.append(el('p', { className: 'hint' },
					`A logarithmic axis needs every value above zero, and ${n.toLocaleString()} `
					+ `realisation${n === 1 ? ' is' : 's are'} zero or below here — drawn on a linear one instead.`));
			}

			if (!s.n) {
				body.append(el('p', { className: 'hint' },
					'No realisation has a finite value here.'));
			} else {
				// The curves to draw: the specified one, and the fits ticked.
				const canFit = s.n >= FIT_MIN_SAMPLE && col[col.length - 1] > col[0];
				if (fitOn && canFit && !fitsCurrent()) fitLater();
				const ready = fitOn && fitsCurrent();
				const specOk = drawable(view.spec);
				// The specified one last, on top: it is dotted, and a fit that
				// matches it -- the point of looking -- would otherwise hide it.
				const curves = [];
				const legend = [];
				if (ready) {
					for (const f of rankFits(fitted.fits, fitTest)) {
						if (f.why || !shown.has(f.family)) continue;
						curves.push({ spec: f.spec, ...FIT_STYLE[f.family] });
						legend.push(el('span', {}, swatch(FIT_STYLE[f.family]), `${f.label} (${fitMethod.toUpperCase()})`));
					}
				}
				if (specOk && showSpec) {
					curves.push({ spec: view.spec, ...SPEC_STYLE });
					legend.unshift(el('span', {}, swatch(SPEC_STYLE), 'as specified'));
				}
				const canvas = el('canvas', { className: 'dist-canvas' });
				body.append(el('div', { className: 'sens-chart' }, canvas));
				requestAnimationFrame(() => paint(canvas, col, hist, s, curves));
				if (legend.length) {
					body.append(el('div', { className: 'fit-legend' },
						el('span', {}, el('span', { className: 'fit-bars' }), 'realisations'), ...legend));
				}

				// --- the distribution it was drawn from, for a varied parameter.
				if (view.spec) {
					if (specOk) {
						const tick = el('input', { type: 'checkbox', checked: showSpec });
						tick.addEventListener('change', () => { showSpec = tick.checked; modal.refresh(); });
						body.append(el('label', { className: 'fit-spec' }, tick,
							'Show the distribution it was drawn from: ', el('code', {}, formatPDF(view.spec))));
					} else {
						body.append(el('p', { className: 'hint' }, view.spec.kind === 'pg'
							? 'Drawn from a list of values, which has no curve to lay over the histogram.'
							: 'Drawn from a distribution that is not filled in, so there is no curve to draw.'));
					}
					if (view.screened) {
						body.append(el('p', { className: 'hint' },
							'The categories leave some realisations out, so this sample need not follow '
							+ 'the distribution it was drawn from.'));
					}
				}

				// --- fitting.
				const method = el('select', { className: 'fit-method', disabled: !canFit });
				for (const [value, label, why] of FIT_METHODS) {
					method.append(el('option', { value, selected: value === fitMethod, title: why }, label));
				}
				method.addEventListener('change', () => { fitMethod = method.value; modal.refresh(); });
				const test = el('select', { className: 'fit-test', disabled: !canFit });
				for (const [value, label, why] of FIT_TESTS) {
					test.append(el('option', { value, selected: value === fitTest, title: why }, label));
				}
				test.addEventListener('change', () => { fitTest = test.value; modal.refresh(); });
				const go = el('button', { type: 'button', className: 'fit-go', disabled: !canFit },
					fitOn ? 'Clear' : 'Fit');
				go.addEventListener('click', () => {
					fitOn = !fitOn;
					if (!fitOn) { shown.clear(); fitted = null; }
					modal.refresh();
				});
				body.append(el('div', { className: 'pdf-row pdf-row-wide' },
					el('label', { title: 'Fit each shape a parameter can have to this sample, and rank the fits.' }, 'Fit'),
					el('span', { className: 'sens-at' }, method, el('span', { className: 'fit-by' }, 'ranked by'), test, go)));
				if (!canFit) {
					body.append(el('p', { className: 'hint' }, s.n < FIT_MIN_SAMPLE
						? `Fitting needs at least ${FIT_MIN_SAMPLE} realisations.`
						: 'Every realisation has the same value: there is no shape to fit.'));
				} else if (fitOn && !ready) {
					body.append(el('p', { className: 'hint' }, 'Fitting…'));
				} else if (ready) {
					body.append(fitTable(fitted, fitTest, {
						spec: specOk ? view.spec : null,
						showSpec,
						shown,
						onSpec: (on) => { showSpec = on; modal.refresh(); },
						onShow: (family, on) => { if (on) shown.add(family); else shown.delete(family); modal.refresh(); },
					}));
					body.append(el('p', { className: 'sens-note' },
						(fitMethod === 'mle'
							? 'Maximum likelihood: the parameters under which this sample is the most probable. The '
								+ 'uniforms’ ends are then the smallest and largest realisation, and those two are left '
								+ 'out of the tests, which they would fail by construction. '
							: 'Method of moments: the parameters whose mean and variance, and for a three-parameter '
								+ 'shape the skewness, are the sample’s. Of the values, not their logarithms, so on a '
								+ 'log shape it follows the largest realisations. ')
						+ 'A fit that leaves a realisation where it has no probability calls it impossible, and its A² '
						+ 'and AIC are infinite. '
						+ 'The p-values are for a distribution chosen before the sample was seen — for one fitted to '
						+ 'it they are too large, so they rank the fits rather than accept one'
						+ (fitted.own ? '; for the specified distribution they are what they say.' : '.')));
				}

				// --- the numbers.
				const stat = (label, value, hint) => el('div', { className: 'dist-stat', title: hint ?? '' },
					el('span', {}, label), el('b', { className: 'mono' }, value));
				body.append(el('div', { className: 'dist-grid' },
					stat('Mean', fmtStat(s.mean)),
					stat('95% bounds on the mean', `${fmtStat(s.meanBounds[0])} – ${fmtStat(s.meanBounds[1])}`,
						'Where the true mean is likely to be, given only this many realisations: '
						+ 'mean ± 1.96 × SD/√N.'),
					stat('Std. deviation', fmtStat(s.sd)),
					stat('Skewness', fmtStat(s.skewness),
						'0 is symmetric; positive means a long right tail, which a dose has.'),
					stat('Kurtosis (excess)', fmtStat(s.kurtosis),
						'0 is a normal curve’s; positive means heavier tails than that.'),
					stat('Min – max', `${fmtStat(s.min)} – ${fmtStat(s.max)}`),
				));
				const tab = el('div', { className: 'dist-pct' });
				for (const { p, value } of s.percentiles) {
					tab.append(el('div', { className: 'dist-pct-cell' },
						el('span', {}, `${Math.round(p * 100)}%`), el('b', { className: 'mono' }, fmtStat(value))));
				}
				body.append(el('p', { className: 'dist-label' }, 'Percentiles'), tab);

				// --- the calculator, answered from the column here.
				const calc = el('div', { className: 'dist-calc' });
				const vIn = el('input', { type: 'text', className: 'mono', value: askValue, placeholder: 'a value' });
				const vOut = el('b', { className: 'mono' });
				const showV = () => {
					const x = Number(vIn.value);
					vOut.textContent = vIn.value.trim() && Number.isFinite(x)
						? `P(≤ ${fmtStat(x)}) = ${(probabilityOf(col, x) * 100).toFixed(1)}%, `
							+ `P(> ${fmtStat(x)}) = ${((1 - probabilityOf(col, x)) * 100).toFixed(1)}%`
						: '';
				};
				vIn.addEventListener('input', () => { askValue = vIn.value; showV(); });
				showV();
				const pIn = el('input', { type: 'text', className: 'mono', value: askProb, placeholder: '95' });
				const pOut = el('b', { className: 'mono' });
				const showP = () => {
					const p = Number(pIn.value) / 100;
					pOut.textContent = Number.isFinite(p) && p >= 0 && p <= 1
						? `the ${pIn.value}th percentile is ${fmtStat(valueAt(col, p))}` : '';
				};
				pIn.addEventListener('input', () => { askProb = pIn.value; showP(); });
				showP();
				const qIn = el('input', { type: 'text', className: 'mono', value: tailQ, placeholder: '95' });
				const qOut = el('b', { className: 'mono' });
				const showQ = () => {
					const q = Number(qIn.value) / 100;
					qOut.textContent = Number.isFinite(q) && q >= 0 && q < 1
						? `the realisations above the ${qIn.value}th percentile average `
							+ fmtStat(conditionalTailExpectation(col, q)) : '';
				};
				qIn.addEventListener('input', () => { tailQ = qIn.value; showQ(); });
				showQ();
				calc.append(
					el('div', { className: 'dist-calc-row' }, el('label', {}, 'Probability of a value'), vIn, vOut),
					el('div', { className: 'dist-calc-row' }, el('label', {}, 'Value at a percentile'), pIn, el('span', {}, '%'), pOut),
					el('div', { className: 'dist-calc-row' }, el('label', {}, 'Tail expectation above'), qIn, el('span', {}, '%'), qOut),
				);
				body.append(el('p', { className: 'dist-label' }, 'Calculator'), calc);
			}

			body.append(el('p', { className: 'sens-note' },
				'Statistics of the sample as drawn. The band on the cumulative curve is the '
				+ 'Dvoretzky–Kiefer–Wolfowitz 95% band, which holds for any shape: with '
				+ `${s.n.toLocaleString()} realisations no probability read off the curve `
				+ `is closer than ±${(s.dkw * 100).toFixed(1)}% to the truth. The mean’s `
				+ 'bounds are the usual normal ones and are honest only when N is large.'));

			const done = el('button', { type: 'button', className: 'primary' }, 'Close');
			done.addEventListener('click', () => modal.close());
			body.append(el('div', { className: 'pdf-foot' },
				el('span', { className: 'pdf-note' },
					asking ? 'Working it out…' : 'From the sample already drawn — no further runs.'),
				done));
		},
	});
	return {
		close: () => modal.close(),
		update(next) {
			view = { ...view, ...next };
			asking = false;
			modal.refresh();
		},
	};
}
