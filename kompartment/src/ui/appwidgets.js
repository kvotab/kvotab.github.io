/**
 * The parts of an app, drawn: one function per kind of component, each
 * returning the element and a way to bring it up to date.
 *
 * The same drawing serves the App designer and the running app, so what is
 * laid out is what is used. In the designer the component is drawn *inert* --
 * the frame round it takes the pointer, to move and resize it, and a slider
 * that moved under a drag would be the page arguing with the person placing it
 * -- and its results are whatever run the page holds. Running, it is live, and
 * its results are the run at the values its inputs hold.
 *
 * Everything comes out of a model file, so everything is built from elements
 * and text nodes: a label, a title, the text of a Text component. That last
 * one is Markdown, drawn by the Help tab's own renderer, which makes no markup
 * from strings either and makes a link only of a web address.
 *
 * A context carries what a component reads (see `AppContext`), so this file
 * knows nothing about runs, workers or the editor's state.
 */

import { el } from './parts.js';
import { TimeChart, MAX_SERIES, styleOf } from './chart.js';
import { renderMarkdown } from './markdown.js';
import {
	COMPONENTS, STATISTICS, SINGLE_SERIES, statistic, valueAt, tableTimes,
} from '../domain/apps.js';
import {
	describeTarget, targetUnit, matchSeries, seriesLabel,
} from '../domain/appinputs.js';

/**
 * @typedef {object} AppContext
 * @property {object} raw        the model
 * @property {boolean} live      the running app, rather than the designer
 * @property {(t: object) => *} valueOf  where an input stands: its value this
 *   session, or the model's
 * @property {(t: object, value: *, final: boolean, from: string) => void} set  an
 *   input moved; `final` once it has come to rest (a slider let go, a box left),
 *   and `from` the id of the component that moved it
 * @property {(action: string) => void} act  a button: `run` or `reset`
 * @property {{t: ArrayLike<number>, outputs: object[], column: (i: number) => ArrayLike<number>}|null} results
 * @property {string} timeUnit
 * @property {string[]} scenarios  the model's, for a scenario control
 * @property {(c: object) => string|null} problemOf  what keeps a component
 *   from working, or null
 */

const SVG = 'http://www.w3.org/2000/svg';
const svg = (tag, attrs = {}) => {
	const n = document.createElementNS(SVG, tag);
	for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, String(v));
	return n;
};

/**
 * A number for a label: four significant figures, and exponent notation below
 * a thousandth and from a hundred thousand -- the form the rest of the editor
 * writes times and values in.
 */
export function fmtNumber(v, digits = 4) {
	if (v == null || Number.isNaN(v)) return '—';
	if (!Number.isFinite(v)) return v > 0 ? '∞' : '−∞';
	if (v === 0) return '0';
	const n = Number(v.toPrecision(Math.min(12, Math.max(1, digits))));
	if (Math.abs(n) >= 1e5 || Math.abs(n) < 1e-3) return n.toExponential().replace('e+', 'e');
	return String(n);
}

/** A number typed into a box: plain or exponent notation; null for anything else. */
export function parseNumber(text) {
	const s = String(text ?? '').trim().replace(/−/g, '-');
	if (!s) return null;
	const n = Number(s);
	return Number.isFinite(n) ? n : null;
}

// --- slider arithmetic ----------------------------------------------------------------

/** How many positions a slider's track has, where no step says otherwise. */
export const SLIDER_STEPS = 1000;

/** Whether a slider's range can be drawn at all, and on the scale asked for. */
export function sliderScale(c) {
	const { min, max } = c;
	if (!Number.isFinite(min) || !Number.isFinite(max) || !(max > min)) return null;
	return c.scale === 'log' && min > 0 ? 'log' : 'linear';
}

/** A slider's position, `0..steps`, for a value -- clamped to the ends. */
export function sliderPosition(c, value, steps = sliderSteps(c)) {
	const scale = sliderScale(c);
	if (!scale || !Number.isFinite(value)) return 0;
	const f = scale === 'log'
		? (Math.log(Math.max(value, c.min)) - Math.log(c.min)) / (Math.log(c.max) - Math.log(c.min))
		: (value - c.min) / (c.max - c.min);
	return Math.round(Math.min(1, Math.max(0, f)) * steps);
}

/**
 * The value at a slider position. On a step, where the slider has one and is
 * linear: a slider of whole years should say whole years.
 */
export function sliderValue(c, position, steps = sliderSteps(c)) {
	const scale = sliderScale(c);
	if (!scale) return NaN;
	const f = Math.min(1, Math.max(0, position / steps));
	if (scale === 'log') {
		const v = Math.exp(Math.log(c.min) + f * (Math.log(c.max) - Math.log(c.min)));
		// Four figures: a slider over six decades has no business reporting
		// the seventeenth digit of where the thumb happens to be.
		return Number(v.toPrecision(4));
	}
	let v = c.min + f * (c.max - c.min);
	if (c.step) v = c.min + Math.round((v - c.min) / c.step) * c.step;
	return Number(Math.min(c.max, Math.max(c.min, v)).toPrecision(10));
}

/** Positions along the track: one per step where a linear slider has few enough. */
export function sliderSteps(c) {
	if (sliderScale(c) === 'linear' && c.step) {
		const n = Math.round((c.max - c.min) / c.step);
		if (n >= 1 && n <= 10000) return n;
	}
	return SLIDER_STEPS;
}

// --- what an output reads ---------------------------------------------------------------

/**
 * The series an output draws, in the order its references name them and
 * without repeats, up to what a chart can hold.
 */
export function seriesOf(c, results) {
	if (!results?.outputs?.length) return [];
	const seen = new Set();
	const out = [];
	for (const ref of c.series ?? []) {
		for (const i of matchSeries(results.outputs, ref)) {
			if (seen.has(i)) continue;
			seen.add(i);
			out.push(i);
			if (out.length >= (SINGLE_SERIES.has(c.type) ? 1 : MAX_SERIES)) return out;
		}
	}
	return out;
}

/**
 * Labels without what every one of them says: the block's name where they all
 * share one -- `I-129` rather than `Dose [I-129]` -- and the index where they
 * all share that, `Soil` rather than `Soil [I-129]`. The title says the rest.
 */
export function shortLabels(outputs, indices) {
	const blocks = new Set(indices.map((i) => outputs[i].block));
	const tuples = new Set(indices.map((i) => (outputs[i].index ?? []).join('\u0000')));
	return indices.map((i) => {
		const o = outputs[i];
		if (blocks.size === 1 && indices.length > 1 && o.index?.length) return o.index.join(', ');
		if (tuples.size === 1 && blocks.size > 1 && o.block) return o.block;
		return o.label;
	});
}

/** The unit a set of series shares, or '' when they do not share one. */
function commonUnit(outputs, indices) {
	const units = new Set(indices.map((i) => outputs[i].unit ?? ''));
	return units.size === 1 ? [...units][0] : '';
}

/** What a statistic is called on a caption: `peak`, `at 1000 year`. */
function statCaption(c, timeUnit) {
	if (c.statistic === 'at') return `at ${fmtNumber(c.at)} ${timeUnit}`;
	return STATISTICS[c.statistic]?.toLowerCase() ?? '';
}

// --- the frame every component shares ---------------------------------------------------

/**
 * A component's box and heading. The heading is its label or title as typed,
 * and what it is about when that is empty -- a slider over `Kd [I-129]` that
 * nobody has named is still better called that than nothing.
 */
function frame(c, ctx, heading, ...body) {
	const node = el('div', { className: `app-part app-${c.type}` });
	node.dataset.type = c.type;
	if (heading) node.append(el('div', { className: 'app-part-head' }, heading));
	node.append(...body);
	showProblem(node, c, ctx);
	return node;
}

/**
 * What keeps a part from working, under it -- said again on every update,
 * since what the model reports changes with a run: a series named before the
 * model could build is found once it has.
 */
function showProblem(node, c, ctx) {
	const problem = ctx?.problemOf?.(c) ?? null;
	node.classList.toggle('has-problem', !!problem);
	let p = node.querySelector(':scope > .app-part-problem');
	if (!problem) { p?.remove(); return; }
	if (!p) {
		p = el('p', { className: 'app-part-problem' });
		node.append(p);
	}
	p.textContent = ctx.live ? 'This part of the app is not connected to the model.' : problem;
}

/** Where an input stands, as a number: NaN where the model holds none -- an equation. */
function numberOf(ctx, target) {
	const v = ctx.valueOf(target);
	return v == null || v === '' ? NaN : Number(v);
}

function inputHeading(c, ctx) {
	const name = c.label || (c.target ? describeTarget(c.target) : COMPONENTS[c.type].name);
	return el('span', { className: 'app-part-label' }, name);
}

function outputHeading(c, ctx, what) {
	if (c.title) return el('span', { className: 'app-part-label' }, c.title);
	return el('span', { className: 'app-part-label' }, what || COMPONENTS[c.type].name);
}

// --- inputs -------------------------------------------------------------------------

function slider(c, ctx) {
	const scale = sliderScale(c);
	const steps = sliderSteps(c);
	const unit = c.target ? targetUnit(ctx.raw, c.target) : '';
	const range = el('input', {
		type: 'range', min: '0', max: String(steps), step: '1', className: 'app-range',
		'aria-label': c.label || describeTarget(c.target),
	});
	const box = el('input', {
		type: 'text', className: 'app-box', spellcheck: false, inputMode: 'decimal',
		'aria-label': `${c.label || describeTarget(c.target)}, value`,
	});
	const ends = el('div', { className: 'app-range-ends' },
		el('span', {}, scale ? fmtNumber(c.min) : ''), el('span', {}, scale ? fmtNumber(c.max) : ''));
	range.disabled = !scale || !c.target || !ctx.live;
	box.disabled = !c.target || !ctx.live;
	const node = frame(c, ctx,
		el('span', { className: 'app-part-row' }, inputHeading(c, ctx),
			el('span', { className: 'app-box-wrap' }, box, unit ? el('span', { className: 'app-unit' }, unit) : null)),
		range, ends);
	const show = () => {
		const v = numberOf(ctx, c.target);
		// Not while the box is being typed into: the value it would write is
		// the one being replaced.
		if (document.activeElement !== box) box.value = Number.isFinite(v) ? fmtNumber(v, 6) : '';
		range.value = String(sliderPosition(c, Number.isFinite(v) ? v : c.min, steps));
		range.style.setProperty('--fill', `${(100 * Number(range.value)) / steps}%`);
	};
	range.addEventListener('input', () => {
		const v = sliderValue(c, Number(range.value), steps);
		box.value = fmtNumber(v, 6);
		range.style.setProperty('--fill', `${(100 * Number(range.value)) / steps}%`);
		ctx.set(c.target, v, false, c.id);
	});
	range.addEventListener('change', () => ctx.set(c.target, sliderValue(c, Number(range.value), steps), true, c.id));
	box.addEventListener('change', () => {
		const v = parseNumber(box.value);
		if (v == null) { show(); return; }
		ctx.set(c.target, v, true, c.id);
		show();
	});
	box.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') box.blur(); });
	show();
	return { node, update: show };
}

function numberField(c, ctx) {
	const unit = c.target ? targetUnit(ctx.raw, c.target) : '';
	const box = el('input', {
		type: 'text', className: 'app-box app-box-wide', spellcheck: false, inputMode: 'decimal',
		'aria-label': c.label || describeTarget(c.target),
	});
	box.disabled = !c.target || !ctx.live;
	const bounds = [c.min != null ? `from ${fmtNumber(c.min)}` : null, c.max != null ? `to ${fmtNumber(c.max)}` : null]
		.filter(Boolean).join(' ');
	// The bounds beside the box rather than under it: a number field two rows
	// tall has room for one line under its name.
	const node = frame(c, ctx, inputHeading(c, ctx),
		el('span', { className: 'app-box-wrap' }, box, unit ? el('span', { className: 'app-unit' }, unit) : null,
			bounds ? el('span', { className: 'app-part-note' }, bounds) : null));
	const show = () => {
		const v = numberOf(ctx, c.target);
		if (document.activeElement !== box) box.value = Number.isFinite(v) ? fmtNumber(v, 8) : '';
	};
	box.addEventListener('change', () => {
		let v = parseNumber(box.value);
		if (v == null) { show(); return; }
		if (c.min != null) v = Math.max(c.min, v);
		if (c.max != null) v = Math.min(c.max, v);
		ctx.set(c.target, v, true, c.id);
		show();
	});
	box.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') box.blur(); });
	show();
	return { node, update: show };
}

/** What a drop-down or a set of option buttons offers: `[label, value]`. */
function choicesOf(c, ctx) {
	if (c.target?.kind === 'scenario') return (ctx.scenarios ?? []).map((s) => [s, s]);
	return (c.options ?? []).map((o) => [o.label || fmtNumber(o.value), o.value]);
}

function dropdown(c, ctx) {
	const select = el('select', { className: 'app-select', 'aria-label': c.label || describeTarget(c.target) });
	select.disabled = !c.target || !ctx.live;
	const node = frame(c, ctx, inputHeading(c, ctx), select);
	const show = () => {
		const choices = choicesOf(c, ctx);
		const now = ctx.valueOf(c.target);
		select.replaceChildren();
		let found = false;
		choices.forEach(([label, value], k) => {
			const on = value === now;
			found ||= on;
			select.append(el('option', { value: String(k), selected: on }, label));
		});
		// The model holds something none of the choices is: said, rather than
		// shown as the first choice, which it is not.
		if (!found) {
			select.prepend(el('option', { value: '', selected: true, disabled: true },
				now == null ? 'Choose…' : `${typeof now === 'number' ? fmtNumber(now) : now} (the model's)`));
		}
	};
	select.addEventListener('change', () => {
		const pick = choicesOf(c, ctx)[Number(select.value)];
		if (pick) ctx.set(c.target, pick[1], true, c.id);
	});
	show();
	return { node, update: show };
}

let radioGroups = 0;

function radio(c, ctx) {
	const group = el('div', { className: 'app-radios', role: 'radiogroup', 'aria-label': c.label || describeTarget(c.target) });
	const name = `app-radio-${++radioGroups}`;
	const node = frame(c, ctx, inputHeading(c, ctx), group);
	const show = () => {
		const now = ctx.valueOf(c.target);
		group.replaceChildren(...choicesOf(c, ctx).map(([label, value]) => {
			const input = el('input', { type: 'radio', name, checked: value === now });
			input.disabled = !c.target || !ctx.live;
			input.addEventListener('change', () => { if (input.checked) ctx.set(c.target, value, true, c.id); });
			return el('label', { className: 'app-radio-choice' }, input, el('span', {}, label));
		}));
	};
	show();
	return { node, update: show };
}

function toggle(c, ctx) {
	const input = el('input', { type: 'checkbox', className: 'app-switch-box', role: 'switch' });
	input.disabled = !c.target || !ctx.live;
	const label = el('label', { className: 'app-switch-row' }, input,
		el('span', { className: 'app-switch-track', 'aria-hidden': 'true' }), inputHeading(c, ctx));
	const node = frame(c, ctx, null, label);
	const onValue = () => (c.target?.kind === 'enabled' ? true : c.on);
	const offValue = () => (c.target?.kind === 'enabled' ? false : c.off);
	const show = () => { input.checked = ctx.valueOf(c.target) === onValue(); };
	input.addEventListener('change', () => ctx.set(c.target, input.checked ? onValue() : offValue(), true, c.id));
	show();
	return { node, update: show };
}

function button(c, ctx) {
	const label = c.label || (c.action === 'reset' ? 'Reset' : 'Run');
	const b = el('button', { type: 'button', className: c.action === 'run' ? 'primary app-go' : 'app-go' }, label);
	b.disabled = !ctx.live;
	b.addEventListener('click', () => ctx.act(c.action));
	b.title = c.action === 'reset'
		? 'Put every control back to the value the model holds'
		: 'Run the model at the values the controls hold';
	return { node: frame(c, ctx, null, b), update: () => {} };
}

// --- outputs ---------------------------------------------------------------------------

/** What an output says in place of a picture it has nothing to draw with. */
function waiting(ctx, what = 'Results appear here once the model has run.') {
	return el('p', { className: 'app-part-empty' }, ctx.results ? 'Nothing to show.' : what);
}

function chartPart(c, ctx) {
	const host = el('div', { className: 'app-chart-host' });
	const legend = el('div', { className: 'app-legend legend' });
	const empty = el('p', { className: 'app-part-empty', hidden: true });
	const heading = outputHeading(c, ctx, c.series?.length ? c.series.map(seriesLabel).join(', ') : '');
	const node = frame(c, ctx, heading, el('div', { className: 'app-chart-body' }, host, empty), legend);
	const chart = new TimeChart(host);
	chart.setDragPans(false);
	const draw = (next) => {
		ctx = next ?? ctx;
		const r = ctx.results;
		const idx = seriesOf(c, r);
		empty.hidden = !!idx.length;
		empty.textContent = r ? 'Nothing to show.' : 'Results appear here once the model has run.';
		host.hidden = !idx.length;
		legend.replaceChildren();
		if (!idx.length) return;
		const labels = shortLabels(r.outputs, idx);
		const series = idx.map((i, k) => ({ label: labels[k], values: r.column(i), unit: r.outputs[i].unit ?? '' }));
		chart.setScales({ xLog: c.x_scale === 'log', yLog: c.y_scale === 'log' });
		chart.setData(r.t, series, { xLabel: `Time (${ctx.timeUnit})`, yLabel: commonUnit(r.outputs, idx) });
		legend.hidden = !c.legend || series.length < 2;
		if (!legend.hidden) {
			series.forEach((s, k) => {
				const { color, set } = styleOf(s, k);
				const sw = el('span', { className: 'series-swatch legend-swatch' });
				sw.dataset.set = String(set);
				sw.style.setProperty('--swatch', `var(--series-${color + 1})`);
				legend.append(el('span', { className: 'legend-item' }, sw, s.label));
			});
		}
		// Drawn once the layout has settled too: a chart built into a box
		// that is not on the page yet has no size to draw at.
		if (typeof requestAnimationFrame === 'function') requestAnimationFrame(() => chart.draw());
	};
	draw();
	return { node, update: draw, destroy: () => chart.destroy(), redraw: () => chart.draw() };
}

/** The one number a value, a gauge or a bar reads, with the series it came from. */
function oneNumber(c, r, i) {
	const col = r.column(i);
	return statistic(r.t, col, c.statistic, c.at);
}

/** Whether a value is over a limit, which is what a limit is for. */
function overLimit(c, v) {
	return c.limit != null && Number.isFinite(v) && v > c.limit;
}

function valuePart(c, ctx) {
	const number = el('span', { className: 'app-value-number' });
	const unit = el('span', { className: 'app-value-unit' });
	const caption = el('span', { className: 'app-value-caption' });
	const node = frame(c, ctx, outputHeading(c, ctx, ''), el('div', { className: 'app-value-line' }, number, unit), caption);
	const head = node.querySelector('.app-part-label');
	const draw = (next) => {
		ctx = next ?? ctx;
		const r = ctx.results;
		const [i] = seriesOf(c, r);
		const o = i != null ? r.outputs[i] : null;
		if (!c.title) {
			head.textContent = o ? `${STATISTICS[c.statistic]} · ${o.label}`
				: (c.series?.[0] ? seriesLabel(c.series[0]) : COMPONENTS.value.name);
		}
		node.classList.remove('is-over', 'is-under');
		if (!o) {
			number.textContent = '—';
			unit.textContent = '';
			caption.textContent = r ? 'Nothing to show.' : 'Appears once the model has run.';
			return;
		}
		const v = oneNumber(c, r, i);
		number.textContent = fmtNumber(v, c.digits);
		unit.textContent = c.statistic === 'max_time' ? ctx.timeUnit : (o.unit ?? '');
		const parts = [];
		if (c.statistic === 'max') {
			const when = statistic(r.t, r.column(i), 'max_time');
			if (Number.isFinite(when)) parts.push(`at ${fmtNumber(when)} ${ctx.timeUnit}`);
		} else if (c.statistic !== 'max_time') {
			parts.push(statCaption(c, ctx.timeUnit));
		}
		if (c.limit != null && c.statistic !== 'max_time' && Number.isFinite(v)) {
			const over = overLimit(c, v);
			node.classList.add(over ? 'is-over' : 'is-under');
			parts.push(`${over ? 'above' : 'below'} the limit of ${fmtNumber(c.limit)}`);
		}
		caption.textContent = parts.join(' · ');
	};
	draw();
	return { node, update: draw };
}

/** A round number at or above `v`: 1, 2 or 5 times a power of ten. */
function niceAbove(v) {
	if (!(v > 0)) return 1;
	const p = 10 ** Math.floor(Math.log10(v));
	for (const m of [1, 2, 5, 10]) if (m * p >= v) return m * p;
	return 10 * p;
}

/** Where a gauge's needle sits for a value, `0..1`, on its scale. */
export function gaugeFraction(v, lo, hi, scale) {
	if (!Number.isFinite(v)) return 0;
	if (scale === 'log' && lo > 0 && hi > lo) {
		if (!(v > 0)) return 0;
		return Math.min(1, Math.max(0, (Math.log(v) - Math.log(lo)) / (Math.log(hi) - Math.log(lo))));
	}
	if (!(hi > lo)) return 0;
	return Math.min(1, Math.max(0, (v - lo) / (hi - lo)));
}

/** The span a gauge is drawn over: the one set, or one that holds the value and the limit. */
function gaugeSpan(c, v) {
	const top = Math.max(Number.isFinite(v) ? v : 0, c.limit ?? 0);
	let hi = c.max ?? niceAbove(top * (c.limit != null && top === c.limit ? 1.5 : 1.1));
	// On a logarithmic dial, three decades under the top -- or a decade under
	// the value or the limit, where either is further down, so that neither
	// sits on the end of the dial.
	const floor = () => {
		const low = [v, c.limit].filter((x) => Number.isFinite(x) && x > 0 && x < hi);
		return Math.min(hi / 1e3, ...low.map((x) => x / 10));
	};
	let lo = c.min ?? (c.scale === 'log' ? floor() : 0);
	if (!(hi > lo)) hi = lo + 1;
	if (c.scale === 'log' && !(lo > 0)) lo = floor();
	return { lo, hi };
}

function gauge(c, ctx) {
	const W = 120;
	const R = 50;
	const cx = W / 2;
	const cy = 58;
	const pic = svg('svg', { viewBox: `0 0 ${W} 70`, class: 'app-gauge-pic', role: 'img' });
	const arc = (f0, f1) => {
		const a0 = Math.PI * (1 - f0);
		const a1 = Math.PI * (1 - f1);
		const p = (a) => `${(cx + R * Math.cos(a)).toFixed(2)} ${(cy - R * Math.sin(a)).toFixed(2)}`;
		return `M ${p(a0)} A ${R} ${R} 0 ${f1 - f0 > 0.5 ? 1 : 0} 1 ${p(a1)}`;
	};
	const track = svg('path', { d: arc(0, 1), class: 'app-gauge-track' });
	const fill = svg('path', { d: arc(0, 0.001), class: 'app-gauge-fill' });
	const tick = svg('line', { class: 'app-gauge-limit' });
	const text = svg('text', { x: cx, y: cy - 8, class: 'app-gauge-value', 'text-anchor': 'middle' });
	const lo = svg('text', { x: cx - R, y: cy + 11, class: 'app-gauge-end', 'text-anchor': 'middle' });
	const hi = svg('text', { x: cx + R, y: cy + 11, class: 'app-gauge-end', 'text-anchor': 'middle' });
	pic.append(track, fill, tick, text, lo, hi);
	const caption = el('span', { className: 'app-value-caption' });
	const node = frame(c, ctx, outputHeading(c, ctx, ''), pic, caption);
	const head = node.querySelector('.app-part-label');
	const draw = (next) => {
		ctx = next ?? ctx;
		const r = ctx.results;
		const [i] = seriesOf(c, r);
		const o = i != null ? r.outputs[i] : null;
		if (!c.title) head.textContent = o ? `${STATISTICS[c.statistic]} · ${o.label}` : (c.series?.[0] ? seriesLabel(c.series[0]) : COMPONENTS.gauge.name);
		const v = o ? oneNumber(c, r, i) : NaN;
		const span = gaugeSpan(c, v);
		const f = gaugeFraction(v, span.lo, span.hi, c.scale);
		fill.setAttribute('d', arc(0, Math.max(0.001, f)));
		node.classList.toggle('is-over', overLimit(c, v));
		text.textContent = o ? fmtNumber(v, 3) : '—';
		lo.textContent = fmtNumber(span.lo, 3);
		hi.textContent = fmtNumber(span.hi, 3);
		const lf = c.limit != null ? gaugeFraction(c.limit, span.lo, span.hi, c.scale) : null;
		tick.style.display = lf == null ? 'none' : '';
		if (lf != null) {
			const a = Math.PI * (1 - lf);
			tick.setAttribute('x1', (cx + (R - 9) * Math.cos(a)).toFixed(2));
			tick.setAttribute('y1', (cy - (R - 9) * Math.sin(a)).toFixed(2));
			tick.setAttribute('x2', (cx + (R + 7) * Math.cos(a)).toFixed(2));
			tick.setAttribute('y2', (cy - (R + 7) * Math.sin(a)).toFixed(2));
		}
		pic.setAttribute('aria-label', o ? `${o.label}: ${fmtNumber(v)} ${c.statistic === 'max_time' ? ctx.timeUnit : o.unit ?? ''}` : 'No value yet');
		const unit = c.statistic === 'max_time' ? ctx.timeUnit : o?.unit;
		caption.textContent = o
			? [unit, statCaption(c, ctx.timeUnit), c.limit != null ? `limit ${fmtNumber(c.limit)}` : null].filter(Boolean).join(' · ')
			: (r ? 'Nothing to show.' : 'Appears once the model has run.');
	};
	draw();
	return { node, update: draw };
}

function bars(c, ctx) {
	const list = el('div', { className: 'app-bars-list', role: 'list' });
	const foot = el('span', { className: 'app-value-caption' });
	const node = frame(c, ctx, outputHeading(c, ctx, ''), list, foot);
	const head = node.querySelector('.app-part-label');
	const draw = (next) => {
		ctx = next ?? ctx;
		const r = ctx.results;
		const idx = seriesOf(c, r);
		if (!c.title) head.textContent = c.series?.length ? `${STATISTICS[c.statistic]} · ${c.series.map(seriesLabel).join(', ')}` : COMPONENTS.bars.name;
		list.replaceChildren();
		if (!idx.length) { list.append(waiting(ctx)); foot.textContent = ''; return; }
		const labels = shortLabels(r.outputs, idx);
		let rows = idx.map((i, k) => ({ i, k, label: labels[k], v: oneNumber(c, r, i) }));
		if (c.sort) rows = [...rows].sort((a, b) => (Number.isFinite(b.v) ? b.v : -Infinity) - (Number.isFinite(a.v) ? a.v : -Infinity));
		const finite = rows.map((x) => x.v).filter((v) => Number.isFinite(v));
		const top = finite.length ? Math.max(...finite.map(Math.abs)) : 0;
		const logFloor = (() => {
			const pos = finite.filter((v) => v > 0);
			if (!pos.length) return 0;
			// Six decades under the largest at most, or the bars of a model
			// whose smallest result is 1e-30 would all be the same length.
			return Math.max(Math.log10(Math.min(...pos)), Math.log10(Math.max(...pos)) - 6) - 0.5;
		})();
		const share = (v) => {
			if (!Number.isFinite(v) || !top) return 0;
			if (c.scale === 'log') {
				if (!(v > 0)) return 0;
				const hiL = Math.log10(top);
				return Math.max(0.02, (Math.log10(v) - logFloor) / (hiL - logFloor || 1));
			}
			return Math.abs(v) / top;
		};
		for (const row of rows) {
			const { color } = styleOf({}, row.k);
			const bar = el('span', { className: 'app-bar' });
			bar.style.setProperty('--bar', `${(100 * Math.min(1, share(row.v))).toFixed(2)}%`);
			bar.style.setProperty('--swatch', `var(--series-${color + 1})`);
			list.append(el('div', { className: 'app-bar-row', role: 'listitem' },
				el('span', { className: 'app-bar-label', title: r.outputs[row.i].label }, row.label),
				el('span', { className: 'app-bar-track' }, bar),
				el('span', { className: 'app-bar-value' }, fmtNumber(row.v, 3))));
		}
		const unit = c.statistic === 'max_time' ? ctx.timeUnit : commonUnit(r.outputs, idx);
		foot.textContent = [unit, c.statistic === 'at' ? statCaption(c, ctx.timeUnit) : null,
			c.scale === 'log' ? 'logarithmic' : null].filter(Boolean).join(' · ');
	};
	draw();
	return { node, update: draw };
}

function table(c, ctx) {
	const wrap = el('div', { className: 'app-table-wrap' });
	const node = frame(c, ctx, outputHeading(c, ctx, c.series?.length ? c.series.map(seriesLabel).join(', ') : ''), wrap);
	const draw = (next) => {
		ctx = next ?? ctx;
		const r = ctx.results;
		const idx = seriesOf(c, r);
		wrap.replaceChildren();
		if (!idx.length) { wrap.append(waiting(ctx)); return; }
		const times = c.times?.length ? c.times : tableTimes(r.t, c.rows);
		const cols = idx.map((i) => r.column(i));
		const labels = shortLabels(r.outputs, idx);
		const t = el('table', { className: 'app-table-grid' });
		t.append(el('thead', {}, el('tr', {},
			el('th', { scope: 'col' }, `Time (${ctx.timeUnit})`),
			...idx.map((i, k) => el('th', { scope: 'col', title: r.outputs[i].label }, labels[k],
				r.outputs[i].unit ? el('span', { className: 'app-unit' }, ` ${r.outputs[i].unit}`) : null)))));
		const body = el('tbody');
		for (const time of times) {
			body.append(el('tr', {},
				el('th', { scope: 'row' }, fmtNumber(time)),
				...cols.map((col) => el('td', {}, fmtNumber(valueAt(r.t, col, time), 4)))));
		}
		t.append(body);
		wrap.append(t);
	};
	draw();
	return { node, update: draw };
}

function text(c, ctx) {
	const body = el('div', { className: `app-textbody is-${c.style} is-${c.align}` });
	const fill = () => {
		body.replaceChildren(renderMarkdown(c.text || (ctx.live ? '' : 'Text — write it under Properties.')));
		// The Help tab's headings carry ids to be linked to; here they would
		// only be ids a model file chose, on a page that has its own.
		for (const n of body.querySelectorAll('[id]')) n.removeAttribute('id');
	};
	fill();
	return { node: frame(c, ctx, null, body), update: () => {} };
}

const BUILDERS = {
	slider, number: numberField, dropdown, radio, switch: toggle, button,
	chart: chartPart, value: valuePart, gauge, bars, table, text,
};

/**
 * Draws one component.
 *
 * @param {object} c  the component, as ../domain/apps.js reads it
 * @param {AppContext} ctx
 * @returns {{node: HTMLElement, update: (ctx?: AppContext) => void, destroy?: () => void, redraw?: () => void}}
 */
export function buildComponent(c, ctx) {
	const make = BUILDERS[c.type];
	let out;
	try {
		out = make ? make(c, ctx) : { node: el('div', { className: 'app-part' }), update: () => {} };
	} catch (e) {
		// One part that cannot be drawn is said, where it would have been,
		// and the rest of the page is drawn around it: thrown on, it left the
		// running app a blank window.
		return {
			node: el('div', { className: `app-part app-${c.type} has-problem`, 'data-id': c.id },
				el('p', { className: 'app-part-problem' }, `This part could not be drawn: ${e?.message ?? e}`)),
			update: () => {},
		};
	}
	out.node.dataset.id = c.id;
	const draw = out.update;
	out.update = (next) => {
		draw(next);
		showProblem(out.node, c, next ?? ctx);
	};
	return out;
}
