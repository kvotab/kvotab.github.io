/**
 * What an app's controls set in the model, and what its results read.
 *
 * ./apps.js is the app as data. This is the app against a model: which blocks
 * an input can be pointed at, what the model holds there now, the copy of the
 * model a run is made on once the inputs have been moved, and which of a run's
 * series an output names.
 *
 * **The model is never edited by an app.** An input holds a value of its own
 * for as long as the page is open -- the *session* value, kept by the page --
 * and a run is made on a copy of the model with those values written in
 * (`applyInputs`). So a reviewer can drag every slider to its end without
 * leaving a mark on the file, and the model in the editor is still the model.
 *
 * **Two inputs that set the same thing are one input.** A slider and a number
 * field on the same parameter share one value (`targetKey`), which is the
 * usual reason for putting both on a page.
 */

import * as ed from './edit.js';
import {
	allComponents, readApp, INPUT_TYPES, OUTPUT_TYPES, CURVE_TYPES, APP_COLUMNS, APP_PERCENTILES,
} from './apps.js';
import { supportOf, parsePDF, complete as pdfComplete } from './pdf.js';

/** The distributions whose spread is in the logarithm: a slider over one is too. */
const LOG_PDFS = new Set(['logu', 'logt', 'logdt', 'Logn4', 'logn', 'logn5']);

/** What each kind of target may be set by. */
const SETTABLE_BY = {
	value: new Set(['slider', 'number', 'dropdown', 'radio', 'switch']),
	end_time: new Set(['slider', 'number']),
	scenario: new Set(['dropdown', 'radio']),
	enabled: new Set(['switch']),
};

/** Whether an input of `type` can set a target of `kind`. */
export function canSet(type, kind) {
	return !!SETTABLE_BY[kind]?.has(type);
}

/**
 * Which key of a block an input sets: a parameter's value, or a compartment's
 * value at the start. Nothing else is an input -- an expression is worked out
 * from the model, and a number typed over it would be a different model.
 */
export function settableKey(kind) {
	if (kind === 'parameter') return 'value';
	if (kind === 'compartment') return 'initial';
	return null;
}

const indexText = (index) => {
	const v = Object.values(index ?? {});
	return v.length ? ` [${v.join(', ')}]` : '';
};

/**
 * The key two inputs setting the same thing share. Null for a target that is
 * not complete enough to set anything.
 */
export function targetKey(t) {
	if (!t) return null;
	if (t.kind === 'scenario' || t.kind === 'end_time') return t.kind;
	if (!t.block) return null;
	if (t.kind === 'enabled') return `enabled:${t.block}`;
	const index = Object.entries(t.index ?? {}).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
		.map(([k, v]) => `${k}=${v}`).join(',');
	return `value:${t.block}[${index}]${t.factor ? '*' : ''}`;
}

/** A target, as a person reads it: `Kd [I-129]`, `Scenario`. */
export function describeTarget(t) {
	if (!t) return 'nothing yet';
	if (t.kind === 'scenario') return 'Scenario';
	if (t.kind === 'end_time') return 'End time';
	if (t.kind === 'enabled') return t.block;
	return `${t.block}${indexText(t.index)}${t.factor ? ' ×' : ''}`;
}

/** The block a value target names, with the key it sets and its dimensions. */
function valueSlot(raw, t) {
	const found = ed.findBlock(raw, t.block);
	if (!found) return null;
	const key = settableKey(found.kind);
	if (!key) return { found, key: null, dims: [] };
	return { found, key, dims: ed.effectiveDims(raw, found.block) };
}

/** The unit what an input sets is in, for the label beside it. */
export function targetUnit(raw, t) {
	if (!t) return '';
	if (t.kind === 'end_time') return String(raw?.simulation?.time_unit ?? 'year');
	if (t.kind !== 'value' || t.factor) return '';
	const found = ed.findBlock(raw, t.block);
	return found ? String(found.block.unit ?? '') : '';
}

/**
 * What stops a target being set, in a sentence, or null when nothing does.
 *
 * Checked against the model as it stands, so a parameter deleted after its
 * slider was placed is said here -- on the slider, in the designer -- rather
 * than being a slider that moves and changes nothing.
 */
export function targetProblem(raw, t, type) {
	if (!t) return 'Not connected yet: choose what it sets.';
	if (!canSet(type, t.kind)) return 'This kind of control cannot set that.';
	if (t.kind === 'end_time') return null;
	if (t.kind === 'scenario') {
		return ed.scenarioNames(raw).length ? null : 'This model has no scenarios to choose between.';
	}
	const found = ed.findBlock(raw, t.block);
	if (!found) return `'${t.block}' is not in the model.`;
	if (t.kind === 'enabled') return null;
	const slot = valueSlot(raw, t);
	if (!slot.key) {
		return `'${t.block}' is ${article(found.kind)} ${found.kind.replace(/_/g, ' ')}: only a parameter's `
			+ 'value or a compartment’s value at the start can be set.';
	}
	const index = t.index ?? {};
	for (const [list, name] of Object.entries(index)) {
		const d = slot.dims.indexOf(list);
		if (d < 0) return `'${t.block}' is not indexed by '${list}'.`;
		if (!ed.dimensionIndices(raw, [list])[0].includes(name)) return `'${name}' is not in '${list}'.`;
	}
	const open = slot.dims.filter((d) => !Object.prototype.hasOwnProperty.call(index, d));
	if (open.length && !t.factor) {
		return `Choose which ${open.join(' and ')} it sets, or set every index at once as a factor.`;
	}
	return null;
}

const article = (word) => (/^[aeiou]/i.test(word) ? 'an' : 'a');

/** Whether a target names every one of its block's dimensions. */
function fullIndex(dims, index) {
	return dims.every((d) => Object.prototype.hasOwnProperty.call(index ?? {}, d));
}

/**
 * What the model holds where an input points, which is where the input starts.
 *
 * A number, a scenario's name, or whether a block is on; a factor starts at
 * one. Null where the model holds something an input cannot show as a number
 * -- an equation, most often -- in which case the input starts at the bottom
 * of its range and a run at that input replaces the equation with the number.
 */
export function modelValue(raw, t) {
	if (!t) return null;
	if (t.kind === 'scenario') return ed.activeScenario(raw);
	if (t.kind === 'end_time') {
		const v = Number(raw?.simulation?.end_time);
		return Number.isFinite(v) ? v : null;
	}
	const found = ed.findBlock(raw, t.block);
	if (!found) return null;
	if (t.kind === 'enabled') return ed.isEnabled(found.block);
	if (t.factor) return 1;
	const slot = valueSlot(raw, t);
	if (!slot.key) return null;
	const v = slot.dims.length
		? (fullIndex(slot.dims, t.index) ? ed.effectiveValue(found.block, slot.key, t.index) : null)
		: found.block[slot.key];
	const n = typeof v === 'number' ? v : (typeof v === 'string' && v.trim() !== '' ? Number(v) : NaN);
	return Number.isFinite(n) ? n : null;
}

/** The distribution that applies where a target points, if it has one. */
function pdfAt(raw, t) {
	const slot = valueSlot(raw, t);
	if (!slot?.key || slot.key !== 'value') return null;
	const block = slot.found.block;
	let spec = slot.dims.length && fullIndex(slot.dims, t.index)
		? ed.effectiveValue(block, 'pdf', t.index)
		: block.pdf;
	if (typeof spec === 'string') {
		try { spec = parsePDF(spec); } catch { spec = null; /* not a distribution this can read: no range from it */ }
	}
	return spec && pdfComplete(spec) ? spec : null;
}

/**
 * The range a new slider over this target spans, and how it is scaled.
 *
 * The parameter's own distribution where it has one -- the spread an
 * assessment already argued for, logarithmic when the distribution is -- and
 * otherwise a decade either side of the value the model holds. A factor is a
 * tenth to ten times. The end of the run is a hundredth to ten times what it
 * is on a logarithmic grid, where the interesting question is decades, and
 * the start to twice the end otherwise.
 */
export function defaultRange(raw, t) {
	const r = rangeOf(raw, t);
	// Six figures: a distribution's ends are often written with the float
	// noise of whatever computed them, and a slider does not need to say so.
	return { ...r, min: Number(r.min.toPrecision(6)), max: Number(r.max.toPrecision(6)) };
}

function rangeOf(raw, t) {
	if (t?.kind === 'end_time') {
		const sim = raw?.simulation ?? {};
		const end = Number(sim.end_time) || 1;
		const start = Number(sim.start_time) || 0;
		if ((sim.spacing ?? 'log') === 'log' && end > 0) return { min: end / 100, max: end * 10, scale: 'log' };
		return { min: start + (end - start) / 10, max: start + 2 * (end - start), scale: 'linear' };
	}
	if (t?.kind === 'value' && t.factor) return { min: 0.1, max: 10, scale: 'log' };
	if (t?.kind === 'value') {
		const spec = pdfAt(raw, t);
		const span = spec ? supportOf(spec) : null;
		if (span) {
			const log = LOG_PDFS.has(spec.kind) && span[0] > 0;
			return { min: span[0], max: span[1], scale: log ? 'log' : 'linear' };
		}
		const v = modelValue(raw, t);
		if (Number.isFinite(v) && v > 0) return { min: v / 10, max: v * 10, scale: 'log' };
		if (Number.isFinite(v) && v < 0) return { min: v * 2, max: 0, scale: 'linear' };
	}
	return { min: 0, max: 1, scale: 'linear' };
}

/**
 * Everything an input can be pointed at, for the designer's picker.
 *
 * `values` is every parameter and every compartment, with its dimensions and
 * the indices along each; `blocks` every block, for a switch that turns one
 * off; `scenarios` the model's, when it has any.
 */
export function inputChoices(raw) {
	const values = [];
	const blocks = [];
	for (const b of ed.allBlocks(raw)) {
		const name = ed.qualifiedName(b);
		blocks.push(name);
		const key = settableKey(b.kind);
		if (!key) continue;
		const dims = ed.effectiveDims(raw, b);
		values.push({
			block: name, kind: b.kind, key, dims,
			indices: ed.dimensionIndices(raw, dims),
			unit: String(b.unit ?? ''),
		});
	}
	return { values, blocks, scenarios: ed.scenarioNames(raw) };
}

/**
 * The inputs that stand at something other than what the model holds: what a
 * run at the app's values has to write into its copy.
 *
 * One change per target, whichever of the controls on it was moved last --
 * they share the value -- and only for a target the model can take, so a
 * slider left pointing at a deleted parameter changes nothing rather than
 * stopping the run.
 *
 * @param {object} raw
 * @param {Map<string, *>} values  the session values, by `targetKey`
 * @returns {Array<{key: string, target: object, value: *}>}
 */
export function inputChanges(raw, values) {
	const app = readApp(raw);
	if (!app || !values?.size) return [];
	const out = [];
	const seen = new Set();
	for (const { component: c } of allComponents(app)) {
		if (!INPUT_TYPES.has(c.type) || !c.target) continue;
		const key = targetKey(c.target);
		if (!key || seen.has(key) || !values.has(key)) continue;
		// Before it counts as the control on this target: one that cannot set
		// it -- a drop-down on the end time, from a file written by hand --
		// must not stand in for a slider after it that can.
		if (targetProblem(raw, c.target, c.type)) continue;
		seen.add(key);
		const value = values.get(key);
		if (sameValue(value, modelValue(raw, c.target))) continue;
		out.push({ key, target: c.target, value });
	}
	return out;
}

/** Whether an input's value is the one the model holds. */
function sameValue(a, b) {
	if (typeof a === 'number' && typeof b === 'number') return a === b || Math.abs(a - b) <= 1e-12 * Math.max(Math.abs(a), Math.abs(b));
	return a === b;
}

/**
 * The changes, as one string: two runs at the same inputs have the same one,
 * and the model's own values are the empty string.
 */
export function signature(changes) {
	if (!changes?.length) return '';
	return JSON.stringify(changes.map((c) => [c.key, c.value]).sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0)));
}

/**
 * Writes the app's inputs into a model -- a copy, which is what a run of the
 * app is made on.
 *
 * A factor multiplies what the model holds at every index it leaves open,
 * read before anything is written so that one index's new value is never the
 * base of another's. Anything the copy will not take is passed over and
 * named, since a run at the other inputs is still worth making.
 *
 * @returns {{applied: number, skipped: Array<{key: string, why: string}>}}
 */
export function applyInputs(raw, changes) {
	let applied = 0;
	const skipped = [];
	for (const c of changes ?? []) {
		try {
			writeInput(raw, c.target, c.value);
			applied++;
		} catch (e) {
			skipped.push({ key: c.key, why: e?.message ?? String(e) });
		}
	}
	return { applied, skipped };
}

function writeInput(raw, t, value) {
	if (t.kind === 'end_time') {
		const v = Number(value);
		if (!Number.isFinite(v)) throw new Error('The end time has to be a number.');
		raw.simulation = { ...raw.simulation, end_time: v };
		return;
	}
	if (t.kind === 'scenario') { ed.setScenario(raw, String(value)); return; }
	if (t.kind === 'enabled') { ed.setBlockEnabled(raw, t.block, !!value); return; }
	const slot = valueSlot(raw, t);
	if (!slot?.key) throw new Error(`'${t.block}' cannot be set.`);
	const v = Number(value);
	if (!Number.isFinite(v)) throw new Error(`'${value}' is not a number.`);
	const { found, key, dims } = slot;
	if (!t.factor) {
		if (dims.length) ed.setEntryValue(raw, t.block, { ...t.index }, key, v);
		else found.block[key] = v;
		return;
	}
	if (!dims.length) {
		const base = Number(found.block[key]);
		if (Number.isFinite(base)) found.block[key] = base * v;
		return;
	}
	const fixed = t.index ?? {};
	const combos = ed.indexCombinations(raw, dims)
		.filter((combo) => Object.entries(fixed).every(([l, i]) => combo[l] === i));
	const bases = combos.map((combo) => Number(ed.effectiveValue(found.block, key, combo)));
	combos.forEach((combo, k) => {
		if (Number.isFinite(bases[k])) ed.setEntryValue(raw, t.block, combo, key, bases[k] * v);
	});
}

// --- outputs --------------------------------------------------------------------------

const byBlockCache = new WeakMap();

/** A run's series by the block they belong to, worked out once per run. */
function byBlock(outputs) {
	let map = byBlockCache.get(outputs);
	if (map) return map;
	map = new Map();
	outputs.forEach((o, i) => {
		const key = o.block ?? o.label;
		if (!map.has(key)) map.set(key, []);
		map.get(key).push(i);
	});
	byBlockCache.set(outputs, map);
	return map;
}

/**
 * Which of a run's series an output names, in the run's own order.
 *
 * Every series of the block at every index the reference leaves open: `Dose`
 * is the dose for each radionuclide, `Dose [I-129]` is one of them.
 */
export function matchSeries(outputs, ref) {
	if (!outputs?.length || !ref?.block) return [];
	const list = byBlock(outputs).get(ref.block) ?? [];
	const index = Object.entries(ref.index ?? {});
	if (!index.length) return list;
	return list.filter((i) => {
		const o = outputs[i];
		return index.every(([l, v]) => {
			const d = (o.dims ?? []).indexOf(l);
			return d >= 0 && o.index?.[d] === v;
		});
	});
}

/** A series reference, as a person reads it: `Dose`, or `Dose [I-129]`. */
export function seriesLabel(ref) {
	return ref ? `${ref.block}${indexText(ref.index)}` : '';
}

/**
 * What a run can show, block by block, for the designer's picker: each block
 * once, with its dimensions, the indices along them, its unit and its kind.
 */
export function seriesChoices(outputs) {
	const out = [];
	const at = new Map();
	for (const o of outputs ?? []) {
		const block = o.block ?? o.label;
		let entry = at.get(block);
		if (!entry) {
			entry = { block, kind: o.kind, unit: o.unit ?? '', dims: [...(o.dims ?? [])], indices: (o.dims ?? []).map(() => []), count: 0 };
			at.set(block, entry);
			out.push(entry);
		}
		entry.count++;
		(o.dims ?? []).forEach((d, k) => {
			const name = o.index?.[k];
			const col = entry.indices[entry.dims.indexOf(d)];
			if (col && name != null && !col.includes(name)) col.push(name);
		});
	}
	return out;
}

/** What is wrong with a series reference against a run's outputs, or null. */
export function seriesProblem(outputs, ref) {
	if (!ref?.block) return 'Choose what it shows.';
	if (!outputs) return null;
	if (!(byBlock(outputs).get(ref.block) ?? []).length) return `'${ref.block}' is not among what the model reports.`;
	if (!matchSeries(outputs, ref).length) return `'${seriesLabel(ref)}' is not among what the model reports.`;
	return null;
}

/**
 * What keeps a component from doing its job, in a sentence, or null.
 *
 * An input: what it sets, and whether it has a range or choices to set it
 * within. An output: what it shows -- checked against `outputs`, a run's
 * series or the ones the model would report, where they are known, and
 * against the model's blocks where they are not.
 *
 * @param {object} raw
 * @param {object} c  a component, as ../domain/apps.js reads it
 * @param {Array<object>|null} outputs
 */
export function componentProblem(raw, c, outputs) {
	if (!c) return null;
	if (INPUT_TYPES.has(c.type)) {
		const wrong = targetProblem(raw, c.target, c.type);
		if (wrong) return wrong;
		if (c.type === 'slider') {
			if (c.min == null || c.max == null) return 'Give it a range: its lowest and highest value.';
			if (!(c.max > c.min)) return 'Its highest value has to be above its lowest.';
			if (c.scale === 'log' && !(c.min > 0)) return 'A logarithmic slider starts above zero.';
		}
		if (c.type === 'number' && c.min != null && c.max != null && !(c.max >= c.min)) {
			return 'Its highest value has to be at least its lowest.';
		}
		if ((c.type === 'dropdown' || c.type === 'radio') && c.target.kind === 'value' && !c.options?.length) {
			return 'Give it the choices it offers.';
		}
		return null;
	}
	if (c.type === 'button' || c.type === 'text' || c.type === 'panel' || c.type === 'tabs') return null;
	if (c.type === 'image') return c.src ? null : 'Choose a picture for it.';
	if (!c.series?.length) return 'Choose what it shows.';
	if (c.statistic === 'at' && c.at == null) return 'Choose the time it reads the value at.';
	if (c.type === 'gauge' && c.min != null && c.max != null && !(c.max > c.min)) {
		return 'Its highest value has to be above its lowest.';
	}
	for (const ref of c.series) {
		if (!outputs) {
			// A series a run names after a block -- `Rock held` -- counts for
			// the block at the front of it.
			const cut = Math.max(ref.block.lastIndexOf(' '), ref.block.lastIndexOf('.'));
			const head = ed.findBlock(raw, ref.block) ?? (cut > 0 ? ed.findBlock(raw, ref.block.slice(0, cut)) : null);
			if (!head) return `'${ref.block}' is not in the model.`;
			continue;
		}
		const wrong = seriesProblem(outputs, ref);
		if (wrong) return wrong;
	}
	return null;
}

// --- the spread ------------------------------------------------------------------------

/**
 * What each kind of distribution is scaled by, when the quantity it spreads is
 * multiplied by a factor: the values of its parameters that are in the
 * quantity's own unit. A standard deviation scales with the mean; a geometric
 * standard deviation is a ratio, and does not; a percentile's probability does
 * not either, only where it falls.
 */
const SCALE_KEYS = {
	unif: ['min', 'max'],
	triang: ['min', 'max', 'mode'],
	dtriang: ['min', 'max', 'mode'],
	norm: ['mean', 'sd'],
	logu: ['min', 'max'],
	logt: ['min', 'max', 'mode'],
	logdt: ['min', 'max', 'mode'],
	Logn4: ['gm'],
	logn: ['mean', 'sd'],
	logn5: ['x1', 'x2'],
};

/**
 * The distribution of `c` times a quantity, given the quantity's: every
 * quantile of the one returned is `c` times the quantile of `spec`, and so is
 * a truncation at a value. Null where it cannot be scaled -- a factor that is
 * not above zero, a kind this does not know.
 */
export function scalePdf(spec, c) {
	if (!(c > 0) || !Number.isFinite(c)) return null;
	let from = spec;
	if (typeof from === 'string') {
		try { from = parsePDF(from); } catch { return null; /* not a distribution this can read */ }
	}
	if (!from || typeof from !== 'object') return null;
	const out = structuredClone(from);
	if (from.kind === 'pg') {
		if (!Array.isArray(from.values)) return null;
		out.values = from.values.map((v) => (Number.isFinite(Number(v)) ? Number(v) * c : v));
	} else {
		const keys = SCALE_KEYS[from.kind];
		if (!keys) return null;
		out.params = { ...(from.params ?? {}) };
		for (const k of keys) if (Number.isFinite(Number(out.params[k]))) out.params[k] = Number(out.params[k]) * c;
	}
	for (const k of ['trmin', 'trmax']) if (Number.isFinite(Number(out[k])) && out[k] != null) out[k] = Number(out[k]) * c;
	return out;
}

/**
 * The model a sampled run of the app is made on: a copy at the controls'
 * values, as a run of the app is, with what the controls say about the spread.
 *
 * A control that sets a value **holds** it: it is not sampled, since whoever
 * moved the slider has said what it is. A control that sets a **factor** on
 * every index scales the spread instead -- `Kd ×` at 2 samples twice each
 * nuclide's Kd -- which is the question a factor asks of an uncertain input.
 * Only a parameter carries a distribution; a compartment's value at the start,
 * the scenario and the end of the run are set and that is all.
 *
 * The percentiles are the five the app's parts read (`APP_PERCENTILES`),
 * whatever the model's own are.
 */
export function sampleModel(raw, changes) {
	const copy = structuredClone(raw);
	applyInputs(copy, changes);
	for (const ch of changes ?? []) {
		const t = ch.target;
		if (t?.kind !== 'value') continue;
		const found = ed.findBlock(copy, t.block);
		if (!found || found.kind !== 'parameter') continue;
		const block = found.block;
		const dims = ed.effectiveDims(copy, block);
		const fixed = Object.entries(t.index ?? {});
		const combos = dims.length
			? ed.indexCombinations(copy, dims).filter((combo) => fixed.every(([l, i]) => combo[l] === i))
			: [null];
		// Every distribution read before any is written, as `writeInput` reads
		// every base: one index's new one must not be the next one's old one.
		const specs = combos.map((combo) => (combo ? ed.effectiveValue(block, 'pdf', combo) : block.pdf) ?? null);
		combos.forEach((combo, k) => {
			if (!specs[k]) return;
			const next = t.factor ? scalePdf(specs[k], Number(ch.value)) : null;
			if (combo) ed.setEntryValue(copy, t.block, combo, 'pdf', next);
			else if (next) block.pdf = next;
			else delete block.pdf;
		});
	}
	copy.simulation = { ...copy.simulation, percentiles: [...APP_PERCENTILES] };
	return copy;
}

/**
 * The blocks an app's results name, which is all a sampled run of it has to
 * keep: a thousand realisations of the few series on the page, not of every
 * series the model has.
 */
export function appOutputBlocks(raw) {
	const app = readApp(raw);
	const out = new Set();
	for (const { component: c } of allComponents(app)) {
		if (OUTPUT_TYPES.has(c.type)) for (const s of c.series ?? []) out.add(s.block);
	}
	return [...out];
}

/** Whether anything on an app reads a sample: a chart's bands, a percentile, a button that samples. */
export function usesSpread(app) {
	return allComponents(app).some(({ component: c }) => (c.type === 'chart' && c.spread === 'bands')
		|| (CURVE_TYPES.has(c.type) && c.curve !== 'run')
		|| (c.type === 'button' && c.action === 'sample'));
}

// --- a first app ------------------------------------------------------------------------

/**
 * An app to start from: sliders for what the model is uncertain about, the
 * scenario where there is one, and a chart of what it is for.
 *
 * "What it is uncertain about" is the parameters carrying a distribution,
 * each at the spread it already has -- the inputs an assessment has already
 * said matter -- and the first few numeric parameters where none does. "What
 * it is for" is its endpoints where it names them, and otherwise the results
 * of the last kind of block a model is usually built up to: expressions over
 * the compartments, or the compartments themselves.
 *
 * @param {object} raw
 * @param {Array<object>|null} outputs  what a run reports, if it is known
 * @returns {object} an app, ready to be written as `raw.app`
 */
export function starterApp(raw, outputs) {
	const MAX_INPUTS = 6;
	const inputs = [];
	const scenario = ed.scenarioNames(raw).length > 1;
	const room = MAX_INPUTS - (scenario ? 1 : 0);
	// One control per parameter: over its value where it has one, and as a
	// factor on every index where it has index lists -- four sliders over the
	// four nuclides of one rate would crowd out every other parameter.
	// In the model's order, which is usually the order its author thought of
	// them in: the source term before the dose coefficient.
	const withPdf = [];
	const plain = [];
	for (const b of raw?.parameters ?? []) {
		if (b.enabled === false) continue;
		const name = ed.qualifiedName(b);
		const dims = ed.effectiveDims(raw, b);
		if (dims.length) {
			const combos = ed.indexCombinations(raw, dims);
			const numeric = combos.filter((index) => modelValue(raw, { kind: 'value', block: name, index }) != null);
			if (!numeric.length) continue;
			const t = { kind: 'value', block: name, factor: true };
			(numeric.some((index) => pdfAt(raw, { kind: 'value', block: name, index })) ? withPdf : plain).push(t);
			continue;
		}
		const t = { kind: 'value', block: name };
		if (modelValue(raw, t) == null) continue;
		(pdfAt(raw, t) ? withPdf : plain).push(t);
	}
	for (const t of (withPdf.length ? withPdf : plain).slice(0, room)) inputs.push(t);

	const components = [];
	let y = 0;
	let n = 1;
	if (scenario) {
		components.push({ id: `c${n++}`, type: 'dropdown', x: 0, y, w: 4, h: 2, label: '', target: { kind: 'scenario' }, options: [] });
		y += 2;
	}
	for (const t of inputs) {
		const r = defaultRange(raw, t);
		components.push({ id: `c${n++}`, type: 'slider', x: 0, y, w: 4, h: 2, label: '', target: t, min: r.min, max: r.max, step: null, scale: r.scale });
		y += 2;
	}
	const series = starterSeries(raw, outputs);
	const left = components.length > 0;
	const chartH = Math.max(8, y);
	if (series.length) {
		components.push({
			id: `c${n++}`, type: 'chart', x: left ? 4 : 0, y: 0, w: left ? APP_COLUMNS - 4 : APP_COLUMNS, h: chartH,
			title: '', series, x_scale: 'log', y_scale: 'log', legend: true,
		});
		components.push({
			id: `c${n++}`, type: 'value', x: 0, y: left ? y : chartH, w: left ? 4 : 3, h: 2,
			title: '', series: [series[0]], statistic: 'max', at: null, digits: 3, limit: null,
		});
		components.push({
			id: `c${n++}`, type: 'value', x: left ? 0 : 3, y: left ? y + 2 : chartH, w: left ? 4 : 3, h: 2,
			title: '', series: [series[0]], statistic: 'max_time', at: null, digits: 3, limit: null,
		});
	}
	const app = readApp({
		app: {
			title: String(raw?.name ?? ''), description: '', run: 'change', open: 'editor', edit_button: true,
			pages: [{ name: 'Main', components }],
		},
	});
	return app;
}

/** The series a first chart shows. */
function starterSeries(raw, outputs) {
	const known = outputs?.length ? new Set(outputs.map((o) => o.block ?? o.label)) : null;
	const have = (name) => !known || known.has(name);
	const picked = ed.endpoints(raw).filter(have);
	if (picked.length) return picked.slice(0, 8).map((block) => ({ block }));
	const last = (list) => {
		const names = (list ?? []).filter((b) => b.enabled !== false).map((b) => ed.qualifiedName(b)).filter(have);
		return names.length ? names[names.length - 1] : null;
	};
	const pick = last(raw?.expressions) ?? last(raw?.compartments);
	return pick ? [{ block: pick }] : [];
}
