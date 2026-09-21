/**
 * The Chart tab's third picture: one output against another, realisation by
 * realisation.
 *
 * Over time says where a quantity went. A distribution says what one quantity
 * came to. Neither says how two of them move *together* -- and that is the
 * question a scatter answers, and the only one of the three where a reader can
 * see the shape of a relationship rather than a number standing for it. *What
 * drove the spread* reports a rank correlation of 0.91; this is the picture
 * that says whether the 0.91 is a line, a curve, a fan, or two clusters with
 * nothing in between.
 *
 * **A point is a realisation.** Its x is one output's value at the chosen time
 * and its y is another's, from the same realisation -- which is why the worker
 * sends these columns unsorted, where every other question about the sample
 * takes them sorted.
 *
 * **The line is least squares, and it is drawn on what is plotted.** On a log
 * axis the fit is on the logarithms, so a power law is straight and its slope
 * is the exponent; on a linear axis it is the ordinary fit. Either way the
 * equation says which, because `y = 3.2·x^1.4` and `y = 3.2 + 1.4·x` are
 * different claims and the difference is the whole point of choosing the axis.
 *
 * **R² is of the line as drawn**, so a curve fitted straight reports the poor
 * number it deserves rather than the good one it would get in logs.
 */

import { el } from './parts.js';
import { fmtStat } from './distdialog.js';
import { lineFit } from '../domain/sensitivity.js';

/** Panels drawn at once, as the distributions have. */
export const MOST_PANELS = 12;

/** The chart's own eight, so a series keeps its colour across the pictures. */
const SERIES = ['--series-1', '--series-2', '--series-3', '--series-4',
	'--series-5', '--series-6', '--series-7', '--series-8'];

/** Whether a column is worth a logarithmic axis: positive, and decades wide. */
function wantsLog(cols) {
	let lo = Infinity;
	let hi = -Infinity;
	for (const c of cols) {
		for (let i = 0; i < c.length; i++) {
			const v = c[i];
			if (!Number.isFinite(v)) continue;
			if (v <= 0) return false;
			if (v < lo) lo = v;
			if (v > hi) hi = v;
		}
	}
	return Number.isFinite(lo) && hi / lo > 100;
}

/** The extent of some columns, ignoring what cannot be drawn. */
function span(cols, log) {
	let lo = Infinity;
	let hi = -Infinity;
	for (const c of cols) {
		for (let i = 0; i < c.length; i++) {
			const v = c[i];
			if (!Number.isFinite(v) || (log && v <= 0)) continue;
			if (v < lo) lo = v;
			if (v > hi) hi = v;
		}
	}
	if (!Number.isFinite(lo)) return null;
	if (!(hi > lo)) { hi = lo + Math.abs(lo || 1) * 0.5; }
	return { lo, hi };
}

/** The equation in words, which is what makes the picture quotable. */
export function equationOf(fit, log) {
	if (!fit?.ok) return 'no line: the points do not vary enough to fit one';
	// On logs the fit is `log y = a + b·log x`, which is `y = e^a · x^b`.
	return log
		? `y = ${fmtStat(Math.exp(fit.a))}·x^${fmtStat(fit.b)}`
		: `y = ${fmtStat(fit.a)} ${fit.b < 0 ? '−' : '+'} ${fmtStat(Math.abs(fit.b))}·x`;
}

/**
 * One panel: the points, and the line if it was asked for.
 *
 * @param {object} opts
 * @param {Float64Array} opts.x
 * @param {Array<{label: string, values: Float64Array, colour: number}>} opts.ys
 */
function paint(canvas, { x, ys, xLog, yLog, fits }) {
	const ctx = canvas.getContext('2d');
	if (!ctx) return;
	const dpr = window.devicePixelRatio || 1;
	const w = canvas.clientWidth || 420;
	const h = canvas.clientHeight || 260;
	canvas.width = Math.round(w * dpr);
	canvas.height = Math.round(h * dpr);
	ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
	ctx.clearRect(0, 0, w, h);

	const style = getComputedStyle(canvas);
	const ink = style.getPropertyValue('--text-secondary').trim() || '#555';
	const faint = style.getPropertyValue('--grid').trim() || 'rgba(0,0,0,.07)';
	const axis = style.getPropertyValue('--axis').trim() || 'rgba(0,0,0,.28)';

	const pad = { l: 52, r: 10, t: 10, b: 26 };
	const plotW = Math.max(10, w - pad.l - pad.r);
	const plotH = Math.max(10, h - pad.t - pad.b);
	const xr = span([x], xLog);
	const yr = span(ys.map((s) => s.values), yLog);
	if (!xr || !yr) {
		ctx.fillStyle = ink;
		ctx.font = '11px system-ui, sans-serif';
		ctx.textAlign = 'center';
		ctx.fillText('nothing to plot here', w / 2, h / 2);
		return;
	}
	const px = (v) => pad.l + plotW * (xLog
		? (Math.log(v) - Math.log(xr.lo)) / (Math.log(xr.hi) - Math.log(xr.lo))
		: (v - xr.lo) / (xr.hi - xr.lo));
	const py = (v) => pad.t + plotH - plotH * (yLog
		? (Math.log(v) - Math.log(yr.lo)) / (Math.log(yr.hi) - Math.log(yr.lo))
		: (v - yr.lo) / (yr.hi - yr.lo));

	// A frame and four gridlines, which is what a reader needs to place a
	// point without counting pixels.
	ctx.strokeStyle = faint;
	ctx.lineWidth = 1;
	for (let k = 1; k < 4; k++) {
		const gy = pad.t + (plotH * k) / 4;
		ctx.beginPath();
		ctx.moveTo(pad.l, Math.round(gy) + 0.5);
		ctx.lineTo(pad.l + plotW, Math.round(gy) + 0.5);
		ctx.stroke();
	}
	ctx.strokeStyle = axis;
	ctx.beginPath();
	ctx.moveTo(pad.l + 0.5, pad.t);
	ctx.lineTo(pad.l + 0.5, pad.t + plotH + 0.5);
	ctx.lineTo(pad.l + plotW, pad.t + plotH + 0.5);
	ctx.stroke();

	// The points. Small and semi-transparent, because a thousand realisations
	// of a tight relationship are a thousand dots on one line and what is
	// worth seeing is where they pile up.
	ys.forEach((s, k) => {
		const colour = style.getPropertyValue(SERIES[s.colour % SERIES.length]).trim() || '#2a78d6';
		ctx.fillStyle = colour;
		ctx.globalAlpha = ys.length > 1 ? 0.45 : 0.55;
		const n = Math.min(x.length, s.values.length);
		for (let i = 0; i < n; i++) {
			const a = x[i];
			const b = s.values[i];
			if (!Number.isFinite(a) || !Number.isFinite(b)) continue;
			if ((xLog && a <= 0) || (yLog && b <= 0)) continue;
			ctx.beginPath();
			ctx.arc(px(a), py(b), 2.1, 0, Math.PI * 2);
			ctx.fill();
		}
		ctx.globalAlpha = 1;
		// The line, over its own points, in its own colour but heavier.
		const fit = fits?.[k];
		if (!fit?.ok) return;
		const at = (v) => {
			const t = xLog ? Math.log(v) : v;
			const u = fit.a + fit.b * t;
			return yLog ? Math.exp(u) : u;
		};
		ctx.strokeStyle = colour;
		ctx.lineWidth = 2;
		ctx.beginPath();
		// Walked rather than drawn end to end: with a log axis on one side and
		// not the other the line is a curve on screen.
		const steps = 64;
		for (let j = 0; j <= steps; j++) {
			const v = xLog
				? Math.exp(Math.log(xr.lo) + (Math.log(xr.hi) - Math.log(xr.lo)) * (j / steps))
				: xr.lo + (xr.hi - xr.lo) * (j / steps);
			const u = at(v);
			if (!Number.isFinite(u) || (yLog && u <= 0)) continue;
			const sx = px(v);
			const sy = Math.min(pad.t + plotH + 2, Math.max(pad.t - 2, py(u)));
			if (j === 0) ctx.moveTo(sx, sy);
			else ctx.lineTo(sx, sy);
		}
		ctx.stroke();
	});

	ctx.fillStyle = ink;
	ctx.font = '10px var(--mono), ui-monospace, monospace';
	ctx.textBaseline = 'top';
	ctx.textAlign = 'left';
	ctx.fillText(fmtStat(xr.lo), pad.l, pad.t + plotH + 6);
	ctx.textAlign = 'right';
	ctx.fillText(fmtStat(xr.hi), pad.l + plotW, pad.t + plotH + 6);
	ctx.textBaseline = 'middle';
	ctx.textAlign = 'right';
	ctx.fillText(fmtStat(yr.hi), pad.l - 6, pad.t + 6);
	ctx.fillText(fmtStat(yr.lo), pad.l - 6, pad.t + plotH - 6);
}

/**
 * Draws the scatter into `host`.
 *
 * @param {HTMLElement} host
 * @param {object} opts
 * @param {{label: string, unit: string, values: Float64Array}} opts.x
 * @param {Array<{label: string, unit: string, values: Float64Array}>} opts.ys
 * @param {string} opts.when
 * @param {'one'|'each'} [opts.arrange]
 * @param {boolean} [opts.fit]   draw the least-squares line
 * @param {boolean} [opts.xLog]
 * @param {boolean} [opts.yLog]
 */
export function renderScatter(host, {
	x, ys, when, of, arrange = 'one', fit = true, xLog = null, yLog = null,
	more = 0, onArrange = null, onFit = null,
}) {
	host.replaceChildren();
	if (!x || !ys.length) {
		host.append(el('p', { className: 'hint' },
			'Pick a series for the horizontal axis, and tick the ones to plot against it.'));
		return;
	}
	// Chosen from the data unless the caller has an opinion: a sample that
	// spans decades is unreadable on a linear axis, which is the same rule the
	// distributions use.
	const useXLog = xLog ?? wantsLog([x.values]);
	const useYLog = yLog ?? wantsLog(ys.map((s) => s.values));

	const controls = el('div', { className: 'hist-head' });
	if (onArrange && ys.length > 1) {
		const pick = el('select', { className: 'hist-arrange' });
		for (const [value, label, why] of [
			['one', 'all in one', 'Every series against the same axes. Right when they are '
				+ 'the same quantity, which is when comparing them means anything.'],
			['each', 'one panel each', 'Each series on its own axes, so a small one is not '
				+ 'flattened against a large one.'],
		]) {
			pick.append(el('option', { value, selected: value === arrange, title: why }, label));
		}
		pick.addEventListener('change', () => onArrange(pick.value));
		controls.append(el('label', {}, 'Draw'), pick);
	}
	if (onFit) {
		const box = el('input', { type: 'checkbox', checked: fit });
		box.addEventListener('change', () => onFit(box.checked));
		controls.append(el('label', { className: 'scatter-fit',
			title: 'A least-squares line through each set of points, with its equation '
				+ 'and R². Fitted on what is drawn, so on a logarithmic axis it is the fit '
				+ 'to the logarithms and the equation is a power law.' }, box, 'regression'));
	}
	if (controls.childNodes.length) host.append(controls);

	const fitFor = (s) => lineFit(x.values, s.values,
		{ translate: useXLog && useYLog ? 'log' : 'none' });
	const line = (s, f) => el('div', { className: 'scatter-line' },
		el('span', { className: `hist-key-item c${s.colour % 8}` }, s.label),
		el('span', { className: 'mono' }, equationOf(f, useXLog && useYLog)),
		el('span', { className: 'mono' }, f.ok ? `R² = ${f.r2.toFixed(3)}` : ''),
		f.dropped
			? el('span', { className: 'hist-unit' },
				`${f.dropped.toLocaleString()} left out — a logarithm needs a positive number`)
			: null);

	const axes = `${x.label}${x.unit ? ` (${x.unit})` : ''} across`
		+ (useXLog || useYLog
			? ` — ${[useXLog ? 'x' : null, useYLog ? 'y' : null].filter(Boolean).join(' and ')} `
				+ 'on a logarithmic scale'
			: '');

	if (arrange === 'one' || ys.length === 1) {
		const box = el('div', { className: 'hist-panel hist-one' });
		const canvas = el('canvas', { className: 'hist-canvas is-tall' });
		box.append(canvas);
		const fits = ys.map((s) => (fit ? fitFor(s) : null));
		if (ys.length > 1) {
			const key = el('div', { className: 'hist-key' });
			ys.forEach((s) => key.append(el('span',
				{ className: `hist-key-item c${s.colour % 8}`, title: s.label }, s.label)));
			box.append(key);
		}
		host.append(box);
		requestAnimationFrame(() => paint(canvas,
			{ x: x.values, ys, xLog: useXLog, yLog: useYLog, fits }));
		if (fit) {
			const list = el('div', { className: 'scatter-fits' });
			ys.forEach((s, k) => list.append(line(s, fits[k])));
			host.append(list);
		}
		host.append(el('p', { className: 'hint hist-foot' },
			`${of.toLocaleString()} realisations at ${when}; ${axes}. One point is one `
			+ 'realisation.'));
		return;
	}

	const grid = el('div', { className: 'hist-grid is-scatter' });
	for (const s of ys) {
		const panel = el('div', { className: 'hist-panel' });
		panel.append(el('div', { className: 'hist-name', title: s.label }, s.label));
		const canvas = el('canvas', { className: 'hist-canvas is-mid' });
		panel.append(canvas);
		const f = fit ? fitFor(s) : null;
		if (f) panel.append(line(s, f));
		grid.append(panel);
		requestAnimationFrame(() => paint(canvas, {
			x: x.values, ys: [s], xLog: useXLog, yLog: wantsLog([s.values]), fits: [f],
		}));
	}
	host.append(grid);
	host.append(el('p', { className: 'hint hist-foot' },
		`${of.toLocaleString()} realisations at ${when}; ${axes}.`
		+ (more ? ` ${more.toLocaleString()} more series are selected than fit here.` : '')
		+ ' One point is one realisation.'));
}
