/**
 * The Chart tab's other mode: what a probabilistic run makes of one instant.
 *
 * Over time, a probabilistic run is a band -- the median with the spread drawn
 * behind it -- and that is the right picture for a quantity that moves. It is
 * the wrong one for a quantity that does not: a sampled parameter is one number
 * per realisation and a flat band across the page says only that it is flat.
 * What a reader wants of it is its *shape*, and a shape is a histogram.
 *
 * So the Chart tab has two modes over the same selection, and this draws the
 * second one.
 *
 * **Two arrangements.** *One each* is the default: a panel per series, each on
 * its own scale, in the order the picker has them. It is the safe one --
 * several histograms overlaid are several quantities on one axis, becquerels
 * beside a partition coefficient beside a porosity, and only the tall one is
 * readable.
 *
 * *All in one* is the other, and it is the right picture for the case the safe
 * one serves badly: four series of the same quantity -- one dose per nuclide,
 * say -- which want comparing and cannot be compared across four boxes with
 * four different axes. Drawn as outlines over a common axis in the chart's own
 * series colours, with the bins re-laid on the range they share. Where the
 * units disagree it says so, because then the picture is the misleading one.
 *
 * **Log bins where the sample spans decades**, which `histogram` in
 * ../domain/distribution.js decides from the sample's own body rather than
 * from its extremes. A dose over a thousand realisations spans five decades,
 * and on a linear axis that is one tall bin against a tail nobody can see.
 *
 * Nothing here computes anything: the bins and the summary come from the
 * worker, which has the realisations. This turns them into pixels.
 */

import { el } from './parts.js';
import { fmtStat } from './distdialog.js';

/** Panels drawn at once. Past this the picture is a wall of thumbnails. */
export const MOST_PANELS = 12;

/** The chart's own eight, so a series is the same colour in both pictures. */
const SERIES = ['--series-1', '--series-2', '--series-3', '--series-4',
	'--series-5', '--series-6', '--series-7', '--series-8'];

/** The bars, the axis under them, and the median where it falls. */
function paint(canvas, item) {
	const ctx = canvas.getContext('2d');
	if (!ctx) return;
	const dpr = window.devicePixelRatio || 1;
	const w = canvas.clientWidth || 260;
	const h = canvas.clientHeight || 120;
	canvas.width = Math.round(w * dpr);
	canvas.height = Math.round(h * dpr);
	ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
	ctx.clearRect(0, 0, w, h);

	const style = getComputedStyle(canvas);
	const ink = style.getPropertyValue('--text-secondary').trim() || '#555';
	const faint = style.getPropertyValue('--border').trim() || 'rgba(0,0,0,.14)';
	const fill = style.getPropertyValue('--series-1').trim() || '#2a78d6';

	const { edges, counts, log } = item.hist ?? {};
	const pad = { l: 4, r: 4, t: 6, b: 16 };
	const plotW = Math.max(10, w - pad.l - pad.r);
	const plotH = Math.max(10, h - pad.t - pad.b);
	// The axis line is drawn whatever happens, so an empty panel is a panel
	// rather than a blank.
	ctx.strokeStyle = faint;
	ctx.lineWidth = 1;
	ctx.beginPath();
	ctx.moveTo(pad.l, pad.t + plotH + 0.5);
	ctx.lineTo(pad.l + plotW, pad.t + plotH + 0.5);
	ctx.stroke();
	if (!counts?.length) {
		ctx.fillStyle = ink;
		ctx.font = '11px system-ui, sans-serif';
		ctx.textAlign = 'center';
		ctx.fillText('no spread here', pad.l + plotW / 2, pad.t + plotH / 2);
		return;
	}

	const most = counts.reduce((a, b) => Math.max(a, b), 0) || 1;
	const k = counts.length;
	// Bars are drawn on the bin *positions*, which on a log axis are not
	// evenly spaced in value -- but the edges were built evenly in log, so
	// they are evenly spaced on screen either way. One arithmetic for both.
	const bw = plotW / k;
	ctx.fillStyle = fill;
	for (let b = 0; b < k; b++) {
		const bh = (counts[b] / most) * plotH;
		if (bh <= 0) continue;
		// A two-pixel gap, as every other filled mark in this application has.
		ctx.fillRect(pad.l + b * bw + 1, pad.t + plotH - bh, Math.max(1, bw - 2), bh);
	}

	// The two ends, said in numbers, because a histogram with no axis labels
	// is a shape with no size.
	ctx.fillStyle = ink;
	ctx.font = '10px var(--mono), ui-monospace, monospace';
	ctx.textBaseline = 'top';
	ctx.textAlign = 'left';
	ctx.fillText(fmtStat(edges[0]), pad.l, pad.t + plotH + 4);
	ctx.textAlign = 'right';
	ctx.fillText(fmtStat(edges[k]), pad.l + plotW, pad.t + plotH + 4);
	if (log) {
		ctx.textAlign = 'center';
		ctx.fillText('log', pad.l + plotW / 2, pad.t + plotH + 4);
	}
}

/**
 * Every item's bins re-laid on one axis, so they can be drawn over each other.
 *
 * The bins that came back are each series' own -- its own range, its own count,
 * its own choice of linear or logarithmic -- and three sets of bars on three
 * different axes drawn in one box would be three pictures on top of each
 * other. So one axis is built over everything they cover and each sample is
 * counted into it again, from the edges and counts in hand: a bin of the new
 * axis takes the share of each old bin that falls inside it, which for bins
 * that are already narrow is the same answer as counting the realisations and
 * costs nothing.
 *
 * **The axis is built on the bodies of the samples, not their extremes.** One
 * series' smallest realisation can be sixty decades below another's, and an
 * axis that reaches it puts every sample in the last bin against a page of
 * white. So the range is the 1st to the 99th percentile across the series, and
 * whatever falls outside is counted into the end bin -- which is what a
 * histogram's end bin means anyway.
 *
 * Logarithmic when every sample in range is positive and the span is decades,
 * on the same rule `histogram` uses for one.
 */
function together(items, bins = 36, scale = 'auto') {
	let lo = Infinity;
	let hi = -Infinity;
	let positive = true;
	const pc = (it, p) => it.summary?.percentiles
		?.find((x) => Math.abs(x.p - p) < 1e-9)?.value;
	for (const it of items) {
		const e = it.hist?.edges;
		if (!e?.length) continue;
		// The body where the summary has it, the full range otherwise.
		const a = pc(it, 0.01) ?? e[0];
		const b = pc(it, 0.99) ?? e[e.length - 1];
		lo = Math.min(lo, Number.isFinite(a) ? a : e[0]);
		hi = Math.max(hi, Number.isFinite(b) ? b : e[e.length - 1]);
		if (e[0] <= 0) positive = false;
	}
	if (!Number.isFinite(lo) || !(hi > lo)) return null;
	// A body of one value -- every realisation the same -- still needs a range
	// to be drawn over.
	if (!(hi > lo)) { hi = lo + Math.abs(lo || 1) * 0.5; }
	positive = positive && lo > 0;
	// The reader's choice where they made one. A log axis over a body that
	// reaches zero has no edges to draw, so that request falls back to linear
	// -- the panel says so rather than quietly drawing something else.
	const log = scale === 'log' ? positive
		: scale === 'linear' ? false
			: positive && hi / lo > 100;
	const refused = scale === 'log' && !positive;
	const at = (x) => (log
		? (Math.log(x) - Math.log(lo)) / (Math.log(hi) - Math.log(lo))
		: (x - lo) / (hi - lo));
	const edges = new Float64Array(bins + 1);
	for (let b = 0; b <= bins; b++) {
		edges[b] = log
			? Math.exp(Math.log(lo) + (Math.log(hi) - Math.log(lo)) * (b / bins))
			: lo + (hi - lo) * (b / bins);
	}
	const series = items.map((it) => {
		const counts = new Float64Array(bins);
		const e = it.hist?.edges ?? [];
		const c = it.hist?.counts ?? [];
		for (let b = 0; b < c.length; b++) {
			if (!c[b]) continue;
			// The old bin spread over the new ones it covers, by overlap.
			// Clamped to the axis: an old bin that reaches past the body is
			// counted into the end bin, which is what an end bin means.
			const a0 = Math.min(bins, Math.max(0, at(e[b]) * bins));
			const a1 = Math.min(bins, Math.max(0, at(e[b + 1]) * bins));
			const from = Math.max(0, Math.floor(Math.min(a0, a1)));
			const to = Math.min(bins - 1, Math.max(from, Math.ceil(Math.max(a0, a1)) - 1));
			const width = Math.abs(a1 - a0);
			if (!(width > 0)) { counts[from] += c[b]; continue; }
			for (let j = from; j <= to; j++) {
				const overlap = Math.max(0, Math.min(Math.max(a0, a1), j + 1)
					- Math.max(Math.min(a0, a1), j));
				counts[j] += c[b] * (overlap / width);
			}
		}
		return { label: it.label, counts };
	});
	return { edges, log, series, refused };
}

/** The overlay: one axis, one outline per series, in the chart's colours. */
function paintTogether(canvas, laid) {
	const ctx = canvas.getContext('2d');
	if (!ctx || !laid) return;
	const dpr = window.devicePixelRatio || 1;
	const w = canvas.clientWidth || 600;
	const h = canvas.clientHeight || 260;
	canvas.width = Math.round(w * dpr);
	canvas.height = Math.round(h * dpr);
	ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
	ctx.clearRect(0, 0, w, h);

	const style = getComputedStyle(canvas);
	const ink = style.getPropertyValue('--text-secondary').trim() || '#555';
	const faint = style.getPropertyValue('--border').trim() || 'rgba(0,0,0,.14)';
	const pad = { l: 6, r: 6, t: 8, b: 20 };
	const plotW = Math.max(10, w - pad.l - pad.r);
	const plotH = Math.max(10, h - pad.t - pad.b);
	ctx.strokeStyle = faint;
	ctx.lineWidth = 1;
	ctx.beginPath();
	ctx.moveTo(pad.l, pad.t + plotH + 0.5);
	ctx.lineTo(pad.l + plotW, pad.t + plotH + 0.5);
	ctx.stroke();

	const k = laid.edges.length - 1;
	let most = 0;
	for (const s of laid.series) for (const v of s.counts) most = Math.max(most, v);
	if (!(most > 0)) return;
	const bw = plotW / k;
	laid.series.forEach((s, i) => {
		const colour = style.getPropertyValue(SERIES[i % SERIES.length]).trim() || '#2a78d6';
		// A filled step at low alpha with its own outline over it: the fill
		// says where the mass is and the outline survives being overlapped.
		ctx.beginPath();
		ctx.moveTo(pad.l, pad.t + plotH);
		for (let b = 0; b < k; b++) {
			const y = pad.t + plotH - (s.counts[b] / most) * plotH;
			ctx.lineTo(pad.l + b * bw, y);
			ctx.lineTo(pad.l + (b + 1) * bw, y);
		}
		ctx.lineTo(pad.l + plotW, pad.t + plotH);
		ctx.closePath();
		ctx.globalAlpha = 0.18;
		ctx.fillStyle = colour;
		ctx.fill();
		ctx.globalAlpha = 1;
		ctx.strokeStyle = colour;
		ctx.lineWidth = 1.6;
		ctx.stroke();
	});

	ctx.fillStyle = ink;
	ctx.font = '10px var(--mono), ui-monospace, monospace';
	ctx.textBaseline = 'top';
	ctx.textAlign = 'left';
	ctx.fillText(fmtStat(laid.edges[0]), pad.l, pad.t + plotH + 5);
	ctx.textAlign = 'right';
	ctx.fillText(fmtStat(laid.edges[k]), pad.l + plotW, pad.t + plotH + 5);
	if (laid.log) {
		ctx.textAlign = 'center';
		ctx.fillText('log', pad.l + plotW / 2, pad.t + plotH + 5);
	}
}

/**
 * Draws the panels into `host`.
 *
 * @param {HTMLElement} host
 * @param {object} opts
 * @param {Array<{label: string, unit: string, hist: object, summary: object}>} opts.items
 * @param {string} opts.when   what the time is, already in words
 * @param {number} opts.of     how many realisations the run drew
 * @param {number} [opts.more] series selected past what is drawn
 * @param {'each'|'one'} [opts.arrange] a panel per series, or all on one axis
 * @param {(how: string) => void} [opts.onArrange]
 */
export function renderHistograms(host, {
	items, when, of, more = 0, arrange = 'one', onArrange = null,
	bins = null, scale = 'auto',
}) {
	host.replaceChildren();
	if (!items.length) {
		host.append(el('p', { className: 'hint' },
			'Nothing is selected. Tick a series above to see its distribution.'));
		return;
	}
	// The arrangement, offered only where there is more than one thing to
	// arrange: with one series the two pictures are the same picture.
	if (onArrange && items.length > 1) {
		const pick = el('select', { className: 'hist-arrange' });
		for (const [value, label, why] of [
			['one', 'all in one', 'Every series over one axis, as outlines. The default: '
				+ 'series ticked together are usually the same quantity, and comparing them '
				+ 'is why they were ticked together.'],
			['each', 'one panel each', 'Each series on its own scale. Right when they are '
				+ 'different quantities, and the only honest picture when the units differ.'],
		]) {
			pick.append(el('option', { value, selected: value === arrange, title: why }, label));
		}
		pick.addEventListener('change', () => onArrange(pick.value));
		host.append(el('div', { className: 'hist-head' },
			el('label', {}, 'Draw'), pick));
	}
	if (arrange === 'one' && items.length > 1) {
		const units = new Set(items.map((i) => i.unit).filter(Boolean));
		const box = el('div', { className: 'hist-panel hist-one' });
		const canvas = el('canvas', { className: 'hist-canvas is-tall' });
		box.append(canvas);
		const key = el('div', { className: 'hist-key' });
		items.forEach((it, i) => {
			key.append(el('span', { className: `hist-key-item c${i % 8}`, title: it.label },
				it.label));
		});
		box.append(key);
		host.append(box);
		// The shared axis takes the reader's bin count too. Its own default is
		// finer than a single panel's, because outlines over one another read
		// as curves and a curve wants more than eleven steps.
		const shared = together(items, bins ?? 36, scale);
		requestAnimationFrame(() => paintTogether(canvas, shared));
		host.append(el('p', { className: 'hint hist-foot' },
			`${of.toLocaleString()} realisations, at ${when}.`
			+ (units.size > 1
				? ` Mixed units on one axis (${[...units].join(', ')}) — these are not `
					+ 'comparable, and one panel each is the honest picture for them.'
				: '')
			+ ` Each outline is one series, counted into ${shared?.edges?.length
				? shared.edges.length - 1 : 0} bins shared by all of them`
			+ (shared?.log ? ', spaced logarithmically.' : '.')
			+ (shared?.refused
				? ' Logarithmic bins were asked for and cannot be drawn: the body of '
					+ 'this selection reaches zero, which has no logarithm.'
				: '')));
		return;
	}
	const grid = el('div', { className: 'hist-grid' });
	for (const item of items) {
		const panel = el('div', { className: 'hist-panel' });
		panel.append(el('div', { className: 'hist-name', title: item.label }, item.label));
		const canvas = el('canvas', { className: 'hist-canvas' });
		panel.append(canvas);
		const s = item.summary ?? {};
		// `describeSample` carries the percentiles as a list of {p, value},
		// so they are looked up by the fraction rather than by a field name.
		const pc = (p) => s.percentiles?.find((x) => Math.abs(x.p - p) < 1e-9)?.value;
		panel.append(el('div', { className: 'hist-stats mono' },
			el('span', { title: 'The middle of the sample' }, `median ${fmtStat(pc(0.5))}`),
			el('span', { title: 'The 5th and 95th percentiles' },
				`5–95% ${fmtStat(pc(0.05))} to ${fmtStat(pc(0.95))}`),
			el('span', { title: 'Realisations this is drawn from' }, `n ${(s.n ?? 0).toLocaleString()}`)));
		if (item.unit) panel.append(el('div', { className: 'hist-unit' }, item.unit));
		grid.append(panel);
		requestAnimationFrame(() => paint(canvas, item));
	}
	host.append(grid);
	// Each panel is binned on its own, so what the count and the spacing came
	// to is a per-panel fact; the foot reports it where every panel agrees and
	// says "each on its own" where they do not.
	const counts = new Set(items.map((i) => Math.max(0, (i.hist?.edges?.length ?? 1) - 1)));
	const logs = new Set(items.map((i) => !!i.hist?.log));
	const refused = items.some((i) => i.hist?.refused);
	host.append(el('p', { className: 'hint hist-foot' },
		`${of.toLocaleString()} realisations, at ${when}.`
		+ (more ? ` ${more.toLocaleString()} more series are selected than fit here — `
			+ 'narrow the picker above.' : '')
		+ ' Bars are counts, in '
		+ (counts.size === 1 ? `${[...counts][0]} bins` : 'a count of bins chosen per panel')
		+ (logs.size === 1
			? (logs.has(true) ? ', spaced logarithmically.' : ', evenly spaced.')
			: ', spaced logarithmically where the sample spans decades.')
		+ (refused
			? ' Logarithmic bins were asked for and cannot be drawn where a sample '
				+ 'reaches zero, which has no logarithm; those are evenly spaced.'
			: '')));
}
