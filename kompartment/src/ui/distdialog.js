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
 */

import { el } from './parts.js';
import { openModal } from './modal.js';
import { fmtTime } from '../domain/timeseries.js';
import { valueAt, probabilityOf, conditionalTailExpectation } from '../domain/distribution.js';

/** A number the way the table shows it. */
export function fmtStat(v) {
	if (!Number.isFinite(v)) return '—';
	const a = Math.abs(v);
	if (a === 0) return '0';
	if (a >= 1e5 || a < 1e-3) return v.toExponential(3);
	return v.toPrecision(4);
}

/** Density on the left, cumulative on the right, one canvas. */
function paint(canvas, sorted, hist, summary) {
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
	const sx = (x, x0) => {
		const f = hist.log
			? (Math.log(x) - Math.log(lo)) / (Math.log(hi) - Math.log(lo))
			: (x - lo) / (hi - lo);
		return x0 + Math.min(1, Math.max(0, f)) * pw;
	};
	ctx.font = '9px system-ui, sans-serif';
	ctx.textBaseline = 'top';

	// --- density: the histogram, as bars.
	{
		const x0 = pad.l;
		const peak = Math.max(1, ...hist.counts);
		ctx.fillStyle = accent;
		ctx.globalAlpha = 0.55;
		for (let b = 0; b < hist.counts.length; b++) {
			const a = sx(hist.edges[b], x0);
			const c = sx(hist.edges[b + 1], x0);
			const bh = (hist.counts[b] / peak) * ph;
			ctx.fillRect(a + 0.5, pad.t + ph - bh, Math.max(1, c - a - 1), bh);
		}
		ctx.globalAlpha = 1;
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

/**
 * @param {object} opts
 * @param {string} opts.output      the series
 * @param {string[]} opts.outputs   every series the run kept
 * @param {number} opts.index
 * @param {Float64Array} opts.t
 * @param {number} opts.at          which time
 * @param {object} opts.summary     from `describeSample`
 * @param {object} opts.histogram   from `histogram`
 * @param {Float64Array} opts.column  the sorted realisations
 * @param {number} opts.of          how many realisations the run had
 * @param {string} opts.unit
 * @param {string} opts.timeUnit
 * @param {(ask: {index: number, at: number}) => void} opts.onAsk
 */
export function openDistributionDialog({
	output, outputs = [], index = 0, t, at, summary, histogram: hist, column, of,
	unit = '', timeUnit = 'year', onAsk, onClose,
}) {
	let view = { output, outputs, index, t, at, summary, hist, column, of, unit };
	let asking = false;
	// The calculator's own state, kept across refreshes.
	let askValue = '';
	let askProb = '95';
	let tailQ = '95';

	const ask = (next) => {
		if (asking) return;
		asking = true;
		modal.refresh();
		onAsk?.({ index: view.index, at: view.at, ...next });
	};

	const modal = openModal({
		wide: true,
		title: () => `Distribution of ${view.output}`,
		subtitle: () => `${view.summary.n.toLocaleString()} of ${view.of.toLocaleString()} `
			+ `realisations at ${fmtTime(view.t[view.at])} ${timeUnit}`
			+ (view.unit ? ` — in ${view.unit}` : ''),
		onClose,
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
			const pick = el('select', { className: 'sens-time', disabled: asking });
			for (let j = 0; j < view.t.length; j++) {
				pick.append(el('option', { value: String(j), selected: j === view.at },
					`${fmtTime(view.t[j])} ${timeUnit}`));
			}
			pick.addEventListener('change', () => ask({ at: Number(pick.value) }));
			body.append(el('div', { className: 'pdf-row pdf-row-wide' }, el('label', {}, 'At'), pick));

			if (!s.n) {
				body.append(el('p', { className: 'hint' },
					'No realisation has a finite value here.'));
			} else {
				const canvas = el('canvas', { className: 'dist-canvas' });
				body.append(el('div', { className: 'sens-chart' }, canvas));
				requestAnimationFrame(() => paint(canvas, col, view.hist, s));

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
