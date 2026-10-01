/**
 * Choosing a distribution for a parameter, and seeing it.
 *
 * A parameter in an assessment is a number and the distribution it was drawn
 * from, per index -- model B carries 644 of them, mostly sorption
 * coefficients with one log-triangular per nuclide per material. The domain
 * half is in ../domain/pdf.js; this is the dialog.
 *
 * **The chart is the point.** A log-triangular given as `min 7e-12, max 5e-11,
 * mode 1e-11` is three numbers that mean nothing until they are a shape, and
 * the mistakes they invite -- a mode outside the range, a truncation that
 * removes most of the mass, a geometric SD of 1.05 where 5 was meant -- are
 * all instantly visible and otherwise invisible. So the curve is drawn as the
 * numbers are typed, on the same grid the distribution lives on: a
 * log-scaled kind gets a log x-axis, because a log-triangular over five
 * decades drawn arithmetically is a spike against a flat line -- and on that
 * axis the density of ln x, so a log-normal is the bell it is in ln x.
 *
 * What it does not do is sample anything. A run here is deterministic and
 * uses the value beside the distribution; this stores, shows and edits what a
 * probabilistic run would need.
 */

import { el } from './parts.js';
import { openModal } from './modal.js';
import {
	PDF_KINDS, PDF_KIND_IDS, TRUNCATION, PERCENTILE_TRUNCATION, parsePDF, formatPDF, complete, kindInfo,
	curveOf, describePDF, pdfProblems, supportOf,
} from '../domain/pdf.js';
import { dialogInfo } from './dialoginfo.js';

/** A number as a person would type it back. */
function fmt(v) {
	if (v == null) return '';
	if (v === 0) return '0';
	const a = Math.abs(v);
	return a >= 1e5 || a < 1e-4 ? String(v) : String(v);
}

/** The ticks for a log axis: one per decade, or per 3 when there are many. */
export function logTicks(lo, hi) {
	const a = Math.ceil(Math.log10(lo));
	const b = Math.floor(Math.log10(hi));
	const decades = b - a;
	if (decades < 0) return [lo, hi];
	const step = decades > 8 ? Math.ceil(decades / 6) : 1;
	const out = [];
	for (let e = a; e <= b; e += step) out.push(10 ** e);
	return out;
}

/**
 * The unlabelled marks between the labelled ticks of a log axis: 2 to 9 times
 * each power of ten where a decade is wide enough to hold them apart, 2 and 5
 * where it is narrower, and the powers of ten the labels skip when there are
 * many decades. 9 and 10 are a twentieth of a decade apart, so a decade has
 * to be about 80 pixels wide for the nine of them to read as nine.
 */
export function logMinorTicks(lo, hi, pxPerDecade) {
	if (!(lo > 0 && hi > lo)) return [];
	const labelled = new Set(logTicks(lo, hi));
	const multiples = pxPerDecade >= 80 ? [1, 2, 3, 4, 5, 6, 7, 8, 9]
		: pxPerDecade >= 24 ? [1, 2, 5] : [1];
	const out = [];
	for (let e = Math.floor(Math.log10(lo)); e <= Math.ceil(Math.log10(hi)); e++) {
		for (const m of multiples) {
			const v = m * 10 ** e;
			if (v >= lo && v <= hi && !labelled.has(v)) out.push(v);
		}
	}
	return out;
}

/** Ticks for a linear axis: a round step, five or so of them. */
function linearTicks(lo, hi) {
	const raw = (hi - lo) / 5;
	const mag = 10 ** Math.floor(Math.log10(raw));
	const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? mag * 10;
	const out = [];
	for (let x = Math.ceil(lo / step) * step; x <= hi + step * 1e-9; x += step) out.push(x);
	return out;
}

const tickText = (v) => {
	const a = Math.abs(v);
	if (v === 0) return '0';
	if (a >= 1e5 || a < 1e-3) {
		const e = Math.round(Math.log10(a));
		return 10 ** e === a ? `1e${e}` : v.toExponential(0);
	}
	return String(Number(v.toPrecision(3)));
};

/** The deterministic value as its label on the chart says it. */
const valueText = (v) => {
	const a = Math.abs(v);
	if (v === 0) return '0';
	if (a >= 1e5 || a < 1e-3) return Number(v.toPrecision(3)).toExponential().replace('e+', 'e');
	return String(Number(v.toPrecision(4)));
};

/**
 * The value a deterministic run uses, as a number, or null where there is
 * none: an index's own entry holds what was typed, which may be an expression,
 * and an empty field is no value rather than zero.
 */
export function deterministicValue(value) {
	if (typeof value === 'number') return Number.isFinite(value) ? value : null;
	if (typeof value !== 'string' || value.trim() === '') return null;
	const n = Number(value);
	return Number.isFinite(n) ? n : null;
}

/**
 * Where the chart marks the deterministic value: the value, when it lies in
 * what the chart draws, and null when it does not -- which is when the notes
 * under the chart say it is outside instead.
 */
export function valueOnChart(spec, value) {
	const v = deterministicValue(value);
	const span = v == null ? null : supportOf(spec);
	return span && v >= span[0] && v <= span[1] ? v : null;
}

/**
 * The heights the chart draws for a curve from `curveOf`.
 *
 * On a log axis the height is x·f(x), the density per unit of ln x, so the
 * area between two ticks is the probability between them as it is on a
 * linear one. f(x) itself peaks at the mode of x and leans left of the body
 * the axis shows: a log-normal through P5 = 1 and P95 = 10 would peak at 1.9
 * instead of at its median 3.2, and a log-triangular would not be the
 * triangle in ln x that it is.
 */
export function drawnHeights(curve) {
	return curve.log ? curve.ys.map((y, i) => y * curve.xs[i]) : curve.ys;
}

/**
 * Draws the density on a canvas, and the deterministic value on it where it
 * falls inside.
 *
 * Read from the stylesheet rather than written in, so the picture follows the
 * theme the way every other drawing here does.
 */
function paint(canvas, spec, value = null) {
	const ctx = canvas.getContext('2d');
	if (!ctx) return;
	const dpr = window.devicePixelRatio || 1;
	const w = canvas.clientWidth || 420;
	const h = canvas.clientHeight || 150;
	canvas.width = Math.round(w * dpr);
	canvas.height = Math.round(h * dpr);
	ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
	ctx.clearRect(0, 0, w, h);

	const style = getComputedStyle(canvas);
	const ink = style.getPropertyValue('--text-secondary').trim() || '#888';
	const faint = style.getPropertyValue('--border').trim() || '#333';
	const accent = style.getPropertyValue('--accent').trim() || '#3b82f6';
	const strong = style.getPropertyValue('--text-primary').trim() || '#ccc';

	// A parameter with a value keeps a row above the curve for its label,
	// whether or not this shape reaches it: the value does not change while
	// the dialog is open, and a curve that jumped down whenever typing carried
	// the range across it would look like a change of shape.
	const fixed = deterministicValue(value);
	const pad = { l: 8, r: 8, t: fixed == null ? 10 : 22, b: 18 };
	const plotW = w - pad.l - pad.r;
	const plotH = h - pad.t - pad.b;

	const curve = curveOf(spec, { points: 260 });
	if (!curve) {
		ctx.fillStyle = ink;
		ctx.font = '11px system-ui, sans-serif';
		ctx.textAlign = 'center';
		ctx.fillText(complete(spec)
			? 'These numbers do not describe a shape.'
			: 'Fill the numbers in to see the shape.', w / 2, h / 2);
		return;
	}

	const { xs, log, bars } = curve;
	const ys = drawnHeights(curve);
	const lo = xs[0];
	const hi = xs[xs.length - 1];
	const peak = Math.max(...ys, Number.MIN_VALUE);
	const sx = (x) => {
		const f = log
			? (Math.log(x) - Math.log(lo)) / (Math.log(hi) - Math.log(lo))
			: (x - lo) / (hi - lo);
		return pad.l + f * plotW;
	};
	const sy = (y) => pad.t + plotH - (y / peak) * plotH;

	// The axis, and a tick per decade where the scale is logarithmic -- which
	// is the one thing that says *this is five decades wide* rather than
	// leaving the reader to infer it from a shape that looks the same either
	// way. Each labelled tick has a mark under the axis, and a log axis has
	// shorter unlabelled ones between them, so a value can be read off it
	// between the decades too.
	const axisY = pad.t + plotH + 0.5;
	const crisp = (px) => Math.round(px) + 0.5;
	ctx.strokeStyle = faint;
	ctx.lineWidth = 1;
	ctx.beginPath();
	ctx.moveTo(pad.l, axisY);
	ctx.lineTo(pad.l + plotW, axisY);
	ctx.stroke();

	const mark = (t, length) => {
		ctx.beginPath();
		ctx.moveTo(crisp(sx(t)), axisY);
		ctx.lineTo(crisp(sx(t)), axisY + length);
		ctx.stroke();
	};
	ctx.fillStyle = ink;
	ctx.font = '9.5px system-ui, sans-serif';
	ctx.textAlign = 'center';
	ctx.textBaseline = 'top';
	const ticks = (log ? logTicks(lo, hi) : linearTicks(lo, hi))
		.filter((t) => t >= lo && t <= hi);
	for (const t of ticks) {
		const px = sx(t);
		ctx.strokeStyle = faint;
		ctx.beginPath();
		ctx.moveTo(crisp(px), pad.t);
		ctx.lineTo(crisp(px), pad.t + plotH);
		ctx.globalAlpha = 0.45;
		ctx.stroke();
		ctx.strokeStyle = ink;
		ctx.globalAlpha = 0.8;
		mark(t, 4);
		ctx.globalAlpha = 1;
		ctx.fillText(tickText(t), px, axisY + 5.5);
	}
	if (log) {
		ctx.strokeStyle = ink;
		ctx.globalAlpha = 0.55;
		for (const t of logMinorTicks(lo, hi, plotW / Math.log10(hi / lo))) mark(t, 2.5);
		ctx.globalAlpha = 1;
	}

	ctx.fillStyle = accent;
	if (bars) {
		// A list is bars: it has no density, and a line through a histogram
		// would claim one.
		const width = Math.max(1, plotW / xs.length - 1);
		for (let i = 0; i < xs.length; i++) {
			const top = sy(ys[i]);
			ctx.globalAlpha = 0.55;
			ctx.fillRect(sx(xs[i]) - width / 2, top, width, pad.t + plotH - top);
		}
		ctx.globalAlpha = 1;
	} else {
		// The area, then the line over it: the filled shape is what carries
		// the spread at a glance, and the line is what carries the mode.
		ctx.beginPath();
		ctx.moveTo(sx(xs[0]), pad.t + plotH);
		for (let i = 0; i < xs.length; i++) ctx.lineTo(sx(xs[i]), sy(ys[i]));
		ctx.lineTo(sx(xs[xs.length - 1]), pad.t + plotH);
		ctx.closePath();
		ctx.globalAlpha = 0.18;
		ctx.fill();
		ctx.globalAlpha = 1;

		ctx.strokeStyle = accent;
		ctx.lineWidth = 2;
		ctx.lineJoin = 'round';
		ctx.beginPath();
		for (let i = 0; i < xs.length; i++) {
			const px = sx(xs[i]);
			const py = sy(ys[i]);
			if (i === 0) ctx.moveTo(px, py);
			else ctx.lineTo(px, py);
		}
		ctx.stroke();
	}

	// The value a deterministic run uses, over the shape a probabilistic one
	// would draw from: dashed, as a value marked on the sensitivity charts
	// is, with its number in the row kept for it above the curve. A list's
	// bars stand on bin centres, so its extremes are half a bin past the ends
	// and are drawn at them.
	const at = valueOnChart(spec, fixed);
	if (at != null) {
		const px = crisp(Math.min(pad.l + plotW, Math.max(pad.l, sx(at))));
		ctx.strokeStyle = strong;
		ctx.lineWidth = 1;
		ctx.globalAlpha = 0.7;
		ctx.setLineDash([3, 3]);
		ctx.beginPath();
		ctx.moveTo(px, pad.t - 6);
		ctx.lineTo(px, pad.t + plotH);
		ctx.stroke();
		ctx.setLineDash([]);
		ctx.globalAlpha = 1;
		const text = `value ${valueText(at)}`;
		const half = ctx.measureText(text).width / 2;
		ctx.fillStyle = strong;
		ctx.textAlign = 'center';
		ctx.textBaseline = 'top';
		ctx.fillText(text, Math.min(w - pad.r - half, Math.max(pad.l + half, px)), 3);
	}
}

/**
 * Opens the editor.
 *
 * @param {object} opts
 * @param {object|null} opts.spec     the distribution as it stands, or null
 * @param {string} opts.title         what is being edited, for the heading
 * @param {string} [opts.subtitle]
 * @param {string} [opts.unit]        shown beside the numbers
 * @param {number|string} [opts.value] the constant a deterministic run uses,
 *                                   marked on the chart where it is a number
 * @param {(spec: object|null) => void} opts.onSave
 */
export function openPDFEditor({
	spec = null, title, subtitle = '', unit = '', value = null, onSave,
}) {
	// Edited on a copy: closing with Escape has to leave the model as it was,
	// and the live chart means every keystroke would otherwise be an edit.
	// A parameter with no distribution yet opens on the normal curve. It is the
	// shape somebody reaches for when they have a value and an uncertainty and
	// nothing more, and its two fields -- a mean and a standard deviation --
	// are the ones a reader can fill in without first deciding what kind of
	// spread this is. Log-triangular is the commonest in a finished assessment
	// and a poor thing to be handed before any numbers are typed: three fields,
	// all of them refused unless positive.
	// A spec of a kind this tool does not have -- one a file named, even
	// `constructor` -- opens as a new draft rather than a dialog with no
	// fields to draw.
	let draft = spec && kindInfo(spec.kind)
		? JSON.parse(JSON.stringify(spec))
		: {
			kind: 'norm', params: {}, values: null,
			trmin: null, trmax: null, pmin: null, pmax: null,
			inorder: true, pos: 0,
		};

	let canvas = null;
	const fixed = deterministicValue(value);
	const redraw = () => { if (canvas) paint(canvas, draft, fixed); };

	const modal = openModal({
		info: dialogInfo('distribution-editor'),
		title: `Distribution — ${title}`,
		subtitle: subtitle || (unit ? `Every number below is in ${unit}` : ''),
		build: (body) => {
			const meta = kindInfo(draft.kind);

			// --- which shape.
			const kindSel = el('select', { className: 'pdf-kind' });
			for (const id of PDF_KIND_IDS) {
				kindSel.append(el('option', {
					value: id, selected: id === draft.kind, title: PDF_KINDS[id].blurb,
				}, PDF_KINDS[id].label));
			}
			kindSel.addEventListener('change', () => {
				// The numbers do not carry across: `min` on a triangular and
				// `min` on a log-triangular mean the same thing, but `gm` and
				// `mean` do not, and silently reinterpreting one as the other
				// is how a distribution changes shape without anyone asking.
				const kept = {};
				const from = kindInfo(draft.kind).params.map((p) => p.key);
				for (const p of PDF_KINDS[kindSel.value].params) {
					if (from.includes(p.key)) kept[p.key] = draft.params[p.key];
				}
				draft = { ...draft, kind: kindSel.value, params: kept };
				modal.refresh();
			});
			body.append(el('div', { className: 'pdf-row pdf-row-wide' },
				el('label', {}, 'Shape'), kindSel));
			body.append(el('p', { className: 'pdf-blurb' }, meta.blurb));

			// --- the chart, above the numbers: it is the thing being made.
			canvas = el('canvas', { className: 'pdf-canvas' });
			body.append(el('div', { className: 'pdf-chart' }, canvas));

			// --- its numbers.
			const numberRow = (key, label, get, set, { placeholder = '' } = {}) => {
				const input = el('input', {
					type: 'text', className: 'mono', spellcheck: false,
					value: fmt(get()), placeholder,
				});
				input.dataset.pdf = key;
				const commit = () => {
					const text = input.value.trim();
					const n = text === '' ? null : Number(text);
					if (text !== '' && !Number.isFinite(n)) return;
					set(n);
					// Only the chart and the notes: rebuilding the body would
					// take the caret out of the field being typed into.
					redraw();
					notes();
				};
				input.addEventListener('input', commit);
				input.addEventListener('change', commit);
				// No unit on the row: the subtitle says it once, and repeating it
				// nine times costs the labels the room they need -- `Most likely`
				// truncated to `Most likel…` to make space for a unit already on
				// screen.
				return el('div', { className: 'pdf-row' },
					el('label', { title: label }, label), input);
			};

			if (draft.kind === 'pg') {
				// A list, which is text rather than a row of boxes: these come
				// from somewhere else -- an external sampler, a previous run --
				// and are pasted in hundreds at a time.
				const area = el('textarea', {
					className: 'mono pdf-values', rows: 5, spellcheck: false,
					placeholder: 'One value per line, or separated by ; or spaces',
				});
				area.value = (draft.values ?? []).join('\n');
				area.addEventListener('input', () => {
					draft.values = area.value.split(/[\s;,]+/)
						.map((v) => Number(v.trim()))
						.filter((v) => Number.isFinite(v));
					redraw();
					notes();
				});
				body.append(el('div', { className: 'pdf-row pdf-row-wide pdf-row-tall' },
					el('label', {}, 'Values'), area));
			} else {
				for (const p of meta.params) {
					body.append(numberRow(p.key, p.label,
						() => draft.params[p.key],
						(v) => { draft.params[p.key] = v; }));
				}
			}

			// --- truncation, which any of them may carry, in either of the two
			// ways it can be written: as the values it cuts at, or as the
			// percentiles of this curve's own shape. Both are offered together
			// because they answer the same question and a data set uses
			// whichever it quotes -- and both may be set, which means the part
			// inside all four.
			const cut = el('details', { className: 'pdf-trunc' });
			const anyCut = draft.trmin != null || draft.trmax != null
				|| draft.pmin != null || draft.pmax != null;
			if (anyCut) cut.open = true;
			cut.append(el('summary', {}, anyCut ? 'Truncation' : 'Truncate…'));
			for (const t of TRUNCATION) {
				cut.append(numberRow(t.key, t.label,
					() => draft[t.key],
					(v) => { draft[t.key] = v; },
					{ placeholder: 'none' }));
			}
			cut.append(el('p', { className: 'hint pdf-trunc-note' },
				'Or as percentiles of this curve — 0.05 for the 5th, which cuts wherever '
				+ 'the numbers above put it. A data set that fixes the same tail fraction '
				+ 'for a thousand distributions says it this way.'));
			for (const t of PERCENTILE_TRUNCATION) {
				cut.append(numberRow(t.key, t.label,
					() => draft[t.key],
					(v) => { draft[t.key] = v; },
					{ placeholder: 'none', step: 'any' }));
			}
			body.append(cut);

			// --- what is wrong with it, and what it comes to.
			const noteBox = el('div', { className: 'pdf-notes' });
			body.append(noteBox);
			const summary = el('p', { className: 'pdf-summary mono' });
			body.append(summary);

			function notes() {
				noteBox.replaceChildren();
				for (const m of pdfProblems(draft)) {
					noteBox.append(el('p', { className: 'pdf-warn' }, m));
				}
				// Where the deterministic value sits in the shape, which is the
				// other question this dialog can answer: a value outside its own
				// distribution is a real mistake and an invisible one.
				const span = supportOf(draft);
				if (fixed != null && span && (fixed < span[0] || fixed > span[1])) {
					noteBox.append(el('p', { className: 'pdf-warn' },
						`The parameter's value, ${fixed}, is outside this distribution. `
						+ 'A deterministic run uses that value; a probabilistic one would '
						+ 'never draw it.'));
				}
				summary.textContent = complete(draft) ? formatPDF(draft) : describePDF(draft);
			}
			notes();

			// --- out.
			const clear = el('button', { type: 'button', className: 'ghost' }, 'No distribution');
			clear.title = 'Removes it from this index. The parameter keeps its value.';
			clear.addEventListener('click', () => { modal.close(); onSave(null); });
			const done = el('button', { type: 'button', className: 'primary' }, 'Done');
			done.addEventListener('click', () => {
				modal.close();
				onSave(draft);
			});
			body.append(el('div', { className: 'pdf-foot' },
				el('span', { className: 'pdf-note' },
					'Stored on the model. Runs here are deterministic and use the '
					+ 'value beside it.'),
				clear, done));

			// The canvas has no size until it is in the document.
			requestAnimationFrame(redraw);
		},
	});
	return modal;
}

/**
 * A button that opens the editor, small enough for a row in the left panel.
 *
 * The panel is where values are actually edited, and a parameter with no index
 * list has no per-index grid for the column to live in -- so without this there
 * is no route to a distribution from the panel at all, only from the block's
 * settings. It is a curve rather than a word because the slot is twenty pixels
 * wide; what it is saying is in the tooltip, where the whole distribution is.
 */
export function pdfButton(spec, { onOpen, title = '' } = {}) {
	const set = !!spec;
	const b = el('button', {
		type: 'button',
		className: `sb-pdf${set ? ' is-set' : ''}`,
		title: set
			? `${describePDF(spec)}\n\nClick to edit or remove it.`
			: (title || 'No distribution. Click to give this parameter one.'),
		'aria-label': set ? `Distribution: ${describePDF(spec)}` : 'Add a distribution',
	});
	// A bell over a baseline, drawn rather than typed: no character in the
	// fonts here reads as a distribution at this size.
	const NS = 'http://www.w3.org/2000/svg';
	const svg = document.createElementNS(NS, 'svg');
	svg.setAttribute('viewBox', '0 0 16 12');
	svg.setAttribute('aria-hidden', 'true');
	const path = document.createElementNS(NS, 'path');
	// Wide shoulders and a flat approach to the baseline: drawn tighter it
	// reads as a caret rather than as a distribution.
	path.setAttribute('d', 'M0.8 10.6 C 4.2 10.6, 5.2 1.9, 8 1.9 S 11.8 10.6, 15.2 10.6');
	path.setAttribute('fill', 'none');
	path.setAttribute('stroke', 'currentColor');
	path.setAttribute('stroke-width', '1.4');
	path.setAttribute('stroke-linecap', 'round');
	svg.append(path);
	b.append(svg);
	b.addEventListener('click', (ev) => { ev.preventDefault(); ev.stopPropagation(); onOpen?.(); });
	return b;
}

/** The text a per-index cell shows for a distribution, or for none. */
export function pdfCellText(spec) {
	if (!spec) return '';
	return describePDF(spec);
}

export { parsePDF, formatPDF };
