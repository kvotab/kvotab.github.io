/**
 * An app on a model: the few controls and results somebody else needs, laid
 * out on a page, with the model behind them.
 *
 * The editor is for the person who builds a model. The person who uses one --
 * a reviewer asking what a tenfold sorption coefficient does to the peak dose,
 * a colleague choosing between three climates -- needs four sliders and a
 * chart, and none of the rest. The App designer tab lays those out; *Run app*
 * then shows them and nothing else, and every change to a control runs the
 * model at the values the controls hold.
 *
 * **Kept in the model file**, under `app`, so a model and its app travel as
 * one file and a rename in the model follows into the app (see
 * `retargetAppNames` below, which edit.js calls from every rename and move).
 * The app changes no number the model computes: moving a slider runs a *copy*
 * of the model at the slider's value, and the model keeps its own.
 *
 * **Read, never trusted.** A model arrives as a file, so everything here is
 * read through `readApp`, which keeps only the keys this file defines, clamps
 * every number to its range and every string to a length, and reads a
 * component type it does not know as nothing at all. Every edit is made on
 * that reading and written back whole, so what is stored is always what was
 * read -- there is no second, looser path into the file. Nothing here becomes
 * markup: the page builds every element and every run of text itself.
 *
 * **Laid out on a grid**: twelve columns across whatever width the page has,
 * and rows of a fixed height. A component is a box of cells -- `x`, `y`, `w`,
 * `h` -- so the same app is laid out sensibly in a narrow window and a wide
 * one, and on a phone it becomes one column in reading order. Two boxes never
 * overlap: putting one where another is pushes the other down, and whatever
 * that lands on in turn (`settle`).
 *
 * This file is pure: the app as data, its geometry and its edits. What an
 * input *sets* and what an output *reads* are questions about the model, and
 * they are in ./appinputs.js.
 */

/** Columns across the page. Twelve divide into halves, thirds and quarters. */
export const APP_COLUMNS = 12;

/** How far down a page may go, in rows. */
export const MAX_ROWS = 400;

/** How tall one component may be, in rows. */
export const MAX_HEIGHT = 60;

/** How many pages an app may have. */
export const MAX_PAGES = 24;

/** How many components an app may have, over all its pages. */
export const MAX_COMPONENTS = 300;

/** How many series one output may name. A chart shows at most 32 lines. */
export const MAX_SERIES = 32;

/** How many choices a drop-down or a set of option buttons may offer. */
export const MAX_OPTIONS = 60;

const LABEL_MAX = 200;
/**
 * What a Text part may hold: a few paragraphs, which is what a page of an app
 * has room for. It is Markdown drawn from a file, so it is also a bound on
 * the work one part can ask of the renderer.
 */
export const TEXT_MAX = 4000;
const NAME_MAX = 60;

/**
 * The components, by type: which palette group each is in, what it is called
 * there, and the size it lands at and may be shrunk to, in cells.
 *
 * `group` is what it is for -- an input sets something in the model, an output
 * shows something a run produced, and text is neither.
 */
export const COMPONENTS = {
	slider: { group: 'input', name: 'Slider', w: 4, h: 2, minW: 2, minH: 2 },
	number: { group: 'input', name: 'Number field', w: 3, h: 2, minW: 2, minH: 2 },
	dropdown: { group: 'input', name: 'Drop-down', w: 3, h: 2, minW: 2, minH: 2 },
	radio: { group: 'input', name: 'Option buttons', w: 3, h: 3, minW: 2, minH: 2 },
	switch: { group: 'input', name: 'Switch', w: 3, h: 1, minW: 2, minH: 1 },
	button: { group: 'input', name: 'Button', w: 2, h: 1, minW: 1, minH: 1 },
	chart: { group: 'output', name: 'Chart', w: 8, h: 8, minW: 3, minH: 4 },
	value: { group: 'output', name: 'Value', w: 3, h: 2, minW: 2, minH: 2 },
	gauge: { group: 'output', name: 'Gauge', w: 3, h: 4, minW: 2, minH: 3 },
	bars: { group: 'output', name: 'Bar chart', w: 6, h: 6, minW: 3, minH: 3 },
	table: { group: 'output', name: 'Table', w: 6, h: 6, minW: 3, minH: 3 },
	text: { group: 'static', name: 'Text', w: 6, h: 2, minW: 1, minH: 1 },
};

/** The palette's groups, in the order it lists them. */
export const COMPONENT_GROUPS = [
	{ id: 'input', name: 'Inputs' },
	{ id: 'output', name: 'Results' },
	{ id: 'static', name: 'Text' },
];

/** The types that set something, and so carry a `target`. */
export const INPUT_TYPES = new Set(Object.keys(COMPONENTS).filter((t) => COMPONENTS[t].group === 'input' && t !== 'button'));

/** The types that show a run, and so carry `series`. */
export const OUTPUT_TYPES = new Set(Object.keys(COMPONENTS).filter((t) => COMPONENTS[t].group === 'output'));

/** The types that show one number, read off one series. */
export const SINGLE_SERIES = new Set(['value', 'gauge']);

/**
 * What an input can set.
 *
 *   value     a parameter's value, or a compartment's value at the start --
 *             at one index, or at every index as a factor on what the model
 *             holds there
 *   enabled   whether a block takes part in the run
 *   scenario  which scenario is live
 *   end_time  how long the run is
 */
export const TARGET_KINDS = ['value', 'enabled', 'scenario', 'end_time'];

/**
 * The one number a value, a gauge or a bar reads off a series.
 *
 * `max_time` is the time of the peak rather than its height -- the year a dose
 * is highest is as often the question as how high it gets.
 */
export const STATISTICS = {
	final: 'At the end',
	max: 'Peak',
	max_time: 'Time of the peak',
	min: 'Lowest',
	initial: 'At the start',
	at: 'At a time',
	mean: 'Mean over the run',
};

/** How an axis, a slider or a bar is scaled. */
export const SCALES = ['linear', 'log'];

/** How a run follows the controls. */
export const RUN_WHEN = ['change', 'button'];

/** What opening a model file that carries an app shows first. */
export const OPENS = ['editor', 'app'];

/** How a block of text is set. */
export const TEXT_STYLES = ['body', 'title', 'heading', 'note'];

/** And aligned. */
export const ALIGNS = ['left', 'center', 'right'];

/** What a button does. */
export const ACTIONS = ['run', 'reset'];

/**
 * Keys that must never be written into an object from a file: the first
 * would set the object's prototype, and the other two are how a prototype is
 * reached. An index map is keyed by list names out of the file.
 */
const UNSAFE_KEYS = new Set(['__proto__', 'constructor', 'prototype']);

// --- reading ----------------------------------------------------------------------

const isObject = (v) => !!v && typeof v === 'object' && !Array.isArray(v);

/** A string, trimmed of nothing but capped, or `fallback` for anything else. */
function str(v, max = LABEL_MAX, fallback = '') {
	if (typeof v !== 'string') return fallback;
	return v.length > max ? v.slice(0, max) : v;
}

/** A finite number, or null. A numeric string is a number: JSON edited by hand. */
function num(v) {
	if (typeof v === 'number') return Number.isFinite(v) ? v : null;
	if (typeof v === 'string' && v.trim() !== '') {
		const n = Number(v);
		return Number.isFinite(n) ? n : null;
	}
	return null;
}

/** A whole number within `[lo, hi]`, or `fallback`. */
function int(v, lo, hi, fallback) {
	const n = num(v);
	if (n == null) return fallback;
	return Math.min(hi, Math.max(lo, Math.round(n)));
}

/** One of `choices`, or the first of them. */
function oneOf(v, choices, fallback = choices[0]) {
	return choices.includes(v) ? v : fallback;
}

/**
 * An index combination: list name to index name, both strings.
 *
 * Null for nothing, so a component that names no index carries no key at all
 * rather than an empty object.
 */
export function readIndex(v) {
	if (!isObject(v)) return null;
	const out = {};
	let n = 0;
	for (const [k, x] of Object.entries(v)) {
		if (UNSAFE_KEYS.has(k) || typeof k !== 'string' || !k) continue;
		if (typeof x !== 'string' && typeof x !== 'number') continue;
		out[k] = String(x);
		if (++n >= 16) break;
	}
	return n ? out : null;
}

/**
 * What an input sets, or null for a target this file cannot read.
 *
 * `block` is a qualified name, which is what the rest of the editor addresses
 * a block by; `index` narrows a value to one combination, and `factor` makes
 * the input a multiplier over every combination the index leaves open.
 */
export function readTarget(v) {
	if (!isObject(v)) return null;
	const kind = TARGET_KINDS.includes(v.kind) ? v.kind : null;
	if (!kind) return null;
	if (kind === 'scenario' || kind === 'end_time') return { kind };
	const block = str(v.block, 400);
	if (!block) return null;
	if (kind === 'enabled') return { kind, block };
	const out = { kind, block };
	const index = readIndex(v.index);
	if (index) out.index = index;
	if (v.factor === true) out.factor = true;
	return out;
}

/** What an output shows: a block, and optionally which of its indices. */
export function readSeriesRef(v) {
	if (!isObject(v)) return null;
	const block = str(v.block, 400);
	if (!block) return null;
	const index = readIndex(v.index);
	return index ? { block, index } : { block };
}

function readSeriesList(v, max = MAX_SERIES) {
	if (!Array.isArray(v)) return [];
	const out = [];
	for (const s of v) {
		const r = readSeriesRef(s);
		if (r) out.push(r);
		if (out.length >= max) break;
	}
	return out;
}

function readOptions(v) {
	if (!Array.isArray(v)) return [];
	const out = [];
	for (const o of v) {
		if (!isObject(o)) continue;
		const value = num(o.value);
		if (value == null) continue;
		out.push({ label: str(o.label, 80), value });
		if (out.length >= MAX_OPTIONS) break;
	}
	return out;
}

/**
 * The keys each type carries besides its place, with what each is when the
 * file does not say. The one list of them: `readComponent` reads through it
 * and `updateComponent` writes through it, so a key cannot be accepted by one
 * and dropped by the other.
 */
const PROPS = {
	slider: (c) => ({
		label: str(c.label), target: readTarget(c.target),
		min: num(c.min), max: num(c.max), step: positive(c.step),
		scale: oneOf(c.scale, SCALES),
	}),
	number: (c) => ({
		label: str(c.label), target: readTarget(c.target),
		min: num(c.min), max: num(c.max), step: positive(c.step),
	}),
	dropdown: (c) => ({ label: str(c.label), target: readTarget(c.target), options: readOptions(c.options) }),
	radio: (c) => ({ label: str(c.label), target: readTarget(c.target), options: readOptions(c.options) }),
	switch: (c) => ({
		label: str(c.label), target: readTarget(c.target),
		on: num(c.on) ?? 1, off: num(c.off) ?? 0,
	}),
	button: (c) => ({ label: str(c.label), action: oneOf(c.action, ACTIONS) }),
	chart: (c) => ({
		title: str(c.title), series: readSeriesList(c.series),
		x_scale: oneOf(c.x_scale, SCALES, 'log'), y_scale: oneOf(c.y_scale, SCALES, 'log'),
		legend: c.legend !== false,
	}),
	value: (c) => ({
		title: str(c.title), series: readSeriesList(c.series, 1),
		statistic: oneOf(c.statistic, Object.keys(STATISTICS), 'max'), at: num(c.at),
		digits: int(c.digits, 1, 10, 3), limit: num(c.limit),
	}),
	gauge: (c) => ({
		title: str(c.title), series: readSeriesList(c.series, 1),
		statistic: oneOf(c.statistic, Object.keys(STATISTICS), 'max'), at: num(c.at),
		min: num(c.min), max: num(c.max), limit: num(c.limit),
		scale: oneOf(c.scale, SCALES),
	}),
	bars: (c) => ({
		title: str(c.title), series: readSeriesList(c.series),
		statistic: oneOf(c.statistic, Object.keys(STATISTICS), 'max'), at: num(c.at),
		scale: oneOf(c.scale, SCALES, 'log'), sort: c.sort === true,
	}),
	table: (c) => ({
		title: str(c.title), series: readSeriesList(c.series),
		rows: int(c.rows, 2, 200, 10),
		times: Array.isArray(c.times) ? c.times.map(num).filter((t) => t != null).slice(0, 200) : [],
	}),
	text: (c) => ({
		text: str(c.text, TEXT_MAX),
		style: oneOf(c.style, TEXT_STYLES), align: oneOf(c.align, ALIGNS),
	}),
};

function positive(v) {
	const n = num(v);
	return n != null && n > 0 ? n : null;
}

const ID_RE = /^[A-Za-z0-9_-]{1,40}$/;

/**
 * One component, as this file understands it -- or null for a type it does not
 * know. The geometry is clamped to the grid and to the type's own floor.
 */
export function readComponent(v) {
	if (!isObject(v)) return null;
	const type = typeof v.type === 'string' && Object.prototype.hasOwnProperty.call(COMPONENTS, v.type)
		? v.type : null;
	if (!type) return null;
	const spec = COMPONENTS[type];
	const w = int(v.w, spec.minW, APP_COLUMNS, spec.w);
	const h = int(v.h, spec.minH, MAX_HEIGHT, spec.h);
	return {
		id: typeof v.id === 'string' && ID_RE.test(v.id) ? v.id : '',
		type,
		x: int(v.x, 0, APP_COLUMNS - w, 0),
		y: int(v.y, 0, MAX_ROWS, 0),
		w,
		h,
		...PROPS[type](v),
	};
}

/**
 * The app a model carries, read: every key this file defines and nothing
 * else, every component with an id of its own, and no two boxes overlapping.
 *
 * @returns {object|null} null when the model has no app at all
 */
export function readApp(raw) {
	const a = raw?.app;
	if (!isObject(a)) return null;
	const seen = new Set();
	let count = 0;
	const pages = [];
	for (const p of Array.isArray(a.pages) ? a.pages : []) {
		if (!isObject(p) || pages.length >= MAX_PAGES) continue;
		const components = [];
		for (const c of Array.isArray(p.components) ? p.components : []) {
			if (count >= MAX_COMPONENTS) break;
			const r = readComponent(c);
			if (!r) continue;
			components.push(r);
			count++;
		}
		pages.push({ name: str(p.name, NAME_MAX) || `Page ${pages.length + 1}`, components });
	}
	if (!pages.length) pages.push({ name: 'Main', components: [] });
	// Ids after the whole app is read, so a missing or repeated one is given
	// the next free number rather than one a later component already has.
	const all = pages.flatMap((p) => p.components);
	for (const c of all) {
		if (c.id && !seen.has(c.id)) seen.add(c.id);
		else c.id = '';
	}
	let next = nextNumber(seen);
	for (const c of all) {
		if (c.id) continue;
		c.id = `c${next++}`;
		seen.add(c.id);
	}
	for (const page of pages) placeAll(page.components, settle(page.components));
	return {
		title: str(a.title),
		description: str(a.description, 2000),
		run: oneOf(a.run, RUN_WHEN),
		open: oneOf(a.open, OPENS),
		edit_button: a.edit_button !== false,
		pages,
	};
}

/** Whether a model carries an app with anything on it. */
export function hasApp(raw) {
	const app = readApp(raw);
	return !!app && app.pages.some((p) => p.components.length > 0);
}

/** A new app: one empty page. */
export function emptyApp() {
	return {
		title: '', description: '', run: 'change', open: 'editor', edit_button: true,
		pages: [{ name: 'Main', components: [] }],
	};
}

/** One more than the largest `c<n>` among `ids`. */
function nextNumber(ids) {
	let max = 0;
	for (const id of ids) {
		const m = /^c(\d+)$/.exec(id);
		if (m) max = Math.max(max, Number(m[1]));
	}
	return max + 1;
}

/** Every component, with the page it is on. */
export function allComponents(app) {
	return (app?.pages ?? []).flatMap((page, p) => page.components.map((c) => ({ page: p, component: c })));
}

/** A component by id, with where it is. */
export function findComponent(app, id) {
	for (let p = 0; p < (app?.pages?.length ?? 0); p++) {
		const i = app.pages[p].components.findIndex((c) => c.id === id);
		if (i >= 0) return { page: p, index: i, component: app.pages[p].components[i] };
	}
	return null;
}

// --- the grid ------------------------------------------------------------------------

/** Whether two boxes share a cell. */
export function overlaps(a, b) {
	return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
}

/** How many rows a page's boxes reach down to. */
export function rowsOf(items) {
	return items.reduce((n, c) => Math.max(n, c.y + c.h), 0);
}

/** Top to bottom, then left to right. */
export function readingOrder(items) {
	return [...items].sort((a, b) => a.y - b.y || a.x - b.x);
}

/**
 * The order a page is read in, and stacked in when it is too narrow for
 * columns: band by band down the page, and in each band column by column.
 *
 * A band is as far down as the parts that start in it reach, so no part
 * crosses from one into the next. Within one, a column of sliders beside a
 * chart is read down the column first -- every slider, then the chart --
 * which is what a phone should show: read along the rows instead, the chart
 * came between the first slider and the second.
 */
export function stackOrder(items) {
	const sorted = readingOrder(items);
	const out = [];
	let i = 0;
	while (i < sorted.length) {
		let end = sorted[i].y + sorted[i].h;
		let j = i + 1;
		while (j < sorted.length && sorted[j].y < end) {
			end = Math.max(end, sorted[j].y + sorted[j].h);
			j++;
		}
		out.push(...sorted.slice(i, j).sort((a, b) => a.x - b.x || a.y - b.y));
		i = j;
	}
	return out;
}

/**
 * Where every box goes once one of them is put somewhere.
 *
 * The one put -- `fixed` -- stays exactly where it was put. The others are
 * taken top to bottom, each at the row it asks for, and pushed down past
 * anything already placed that it would overlap; so a box dropped onto
 * another moves that one down, and whatever that one then lands on, in turn.
 * Nothing is pulled up to fill a gap: a gap on a page is somebody's choice.
 *
 * Pure: the boxes are not touched, and what comes back is where each should
 * be, by id.
 *
 * @param {Array<{id: string, x: number, y: number, w: number, h: number}>} items
 * @param {string|null} [fixed]
 * @returns {Map<string, {x: number, y: number, w: number, h: number}>}
 */
export function settle(items, fixed = null) {
	const out = new Map();
	const placed = [];
	const first = fixed != null ? items.find((c) => c.id === fixed) : null;
	if (first) {
		const box = { x: first.x, y: first.y, w: first.w, h: first.h };
		out.set(first.id, box);
		placed.push(box);
	}
	for (const c of readingOrder(items.filter((c) => c !== first))) {
		const box = { x: c.x, y: c.y, w: c.w, h: c.h };
		// Bounded: each step moves the box below one it overlapped, and
		// there are only so many of those.
		for (let guard = 0; guard <= placed.length; guard++) {
			const hit = placed.filter((p) => overlaps(p, box));
			if (!hit.length) break;
			box.y = Math.max(...hit.map((p) => p.y + p.h));
		}
		out.set(c.id, box);
		placed.push(box);
	}
	return out;
}

/** Puts every box where `settle` said, in place. */
function placeAll(items, where) {
	for (const c of items) {
		const at = where.get(c.id);
		if (at) Object.assign(c, at);
	}
}

/**
 * The first place, reading along the rows, where a box of `w` by `h` fits
 * without moving anything; below everything when nowhere above does.
 */
export function freeSpot(items, w, h) {
	const bottom = rowsOf(items);
	for (let y = 0; y <= bottom; y++) {
		for (let x = 0; x + w <= APP_COLUMNS; x++) {
			const box = { x, y, w, h };
			if (!items.some((c) => overlaps(c, box))) return { x, y };
		}
	}
	return { x: 0, y: bottom };
}

/**
 * A box clamped to the grid and to the floor its type has.
 *
 * Where a box too wide for the columns left of it has to give, it is moved
 * left -- what a moved part wants. A part being resized wants its left edge
 * to stay where it is and its width to stop at the page's edge instead:
 * `keepLeft`.
 */
export function clampBox(type, box, { keepLeft = false } = {}) {
	const spec = COMPONENTS[type] ?? { minW: 1, minH: 1 };
	const h = Math.min(MAX_HEIGHT, Math.max(spec.minH, Math.round(box.h)));
	const y = Math.min(MAX_ROWS, Math.max(0, Math.round(box.y)));
	if (keepLeft) {
		const x = Math.min(APP_COLUMNS - spec.minW, Math.max(0, Math.round(box.x)));
		return { x, y, w: Math.min(APP_COLUMNS - x, Math.max(spec.minW, Math.round(box.w))), h };
	}
	const w = Math.min(APP_COLUMNS, Math.max(spec.minW, Math.round(box.w)));
	return { x: Math.min(APP_COLUMNS - w, Math.max(0, Math.round(box.x))), y, w, h };
}

// --- edits -------------------------------------------------------------------------

/**
 * Makes an edit to the app, on its reading, and writes the result back whole.
 *
 * Whole, because a partial write into whatever the file held would be the
 * one path by which a key the reader dropped could survive. The first edit to
 * an app read from a file is therefore also the one that tidies it; every one
 * after is a small change, which is what the undo stack stores.
 *
 * @template T
 * @param {object} raw  the model
 * @param {(app: object) => T} fn
 * @returns {T}
 */
export function editApp(raw, fn) {
	const app = readApp(raw) ?? emptyApp();
	const out = fn(app);
	raw.app = app;
	return out;
}

/** The page at `index`, or the first. */
function pageAt(app, index) {
	return app.pages[Math.min(app.pages.length - 1, Math.max(0, index | 0))];
}

/**
 * Adds a component to a page and returns its id.
 *
 * `at` is where it was dropped, as a cell; without one it goes in the first
 * place it fits. Either way what is under it moves out of the way.
 */
export function addComponent(raw, page, type, { at = null, props = {} } = {}) {
	if (!Object.prototype.hasOwnProperty.call(COMPONENTS, type)) {
		throw new Error(`There is no component called '${type}'.`);
	}
	return editApp(raw, (app) => {
		if (allComponents(app).length >= MAX_COMPONENTS) {
			throw new Error(`An app holds at most ${MAX_COMPONENTS} components.`);
		}
		const target = pageAt(app, page);
		const spec = COMPONENTS[type];
		const size = { w: num(props.w) ?? spec.w, h: num(props.h) ?? spec.h };
		const spot = at ?? freeSpot(target.components, size.w, size.h);
		const id = `c${nextNumber(allComponents(app).map((x) => x.component.id))}`;
		const c = readComponent({ ...props, id, type, ...clampBox(type, { ...size, ...spot }) });
		target.components.push(c);
		placeAll(target.components, settle(target.components, id));
		return id;
	});
}

/**
 * Changes some of a component's settings.
 *
 * Read again afterwards, through the same reader a file goes through, so an
 * edit can no more store an unknown key or an out-of-range number than a file
 * can. The type and the id are not settings.
 */
export function updateComponent(raw, id, patch) {
	return editApp(raw, (app) => {
		const found = findComponent(app, id);
		if (!found) return false;
		const { type, id: own } = found.component;
		const next = readComponent({ ...found.component, ...patch, type, id: own });
		const page = app.pages[found.page];
		page.components[found.index] = next;
		// A change of size can reach into a neighbour.
		placeAll(page.components, settle(page.components, own));
		return true;
	});
}

/** Moves or resizes a component, pushing whatever it lands on down. */
export function placeComponent(raw, id, box) {
	return editApp(raw, (app) => {
		const found = findComponent(app, id);
		if (!found) return false;
		Object.assign(found.component, clampBox(found.component.type, box));
		const page = app.pages[found.page];
		placeAll(page.components, settle(page.components, id));
		return true;
	});
}

export function removeComponent(raw, id) {
	return editApp(raw, (app) => {
		const found = findComponent(app, id);
		if (!found) return false;
		app.pages[found.page].components.splice(found.index, 1);
		return true;
	});
}

/** A copy of a component, beside it where there is room and below it where not. */
export function duplicateComponent(raw, id) {
	const app = readApp(raw);
	const found = findComponent(app, id);
	if (!found) return null;
	const c = found.component;
	const page = app.pages[found.page].components;
	const beside = { x: c.x + c.w, y: c.y, w: c.w, h: c.h };
	const at = beside.x + c.w <= APP_COLUMNS && !page.some((o) => overlaps(o, beside))
		? { x: beside.x, y: c.y }
		: { x: c.x, y: c.y + c.h };
	const { id: _drop, type, ...props } = structuredClone(c);
	return addComponent(raw, found.page, type, { at, props });
}

/** Takes a component to another page, into the first place it fits there. */
export function moveComponentToPage(raw, id, page) {
	return editApp(raw, (app) => {
		const found = findComponent(app, id);
		if (!found || page === found.page || !app.pages[page]) return false;
		const [c] = app.pages[found.page].components.splice(found.index, 1);
		const target = app.pages[page].components;
		Object.assign(c, freeSpot(target, c.w, c.h));
		target.push(c);
		return true;
	});
}

export function addPage(raw, name = '') {
	return editApp(raw, (app) => {
		if (app.pages.length >= MAX_PAGES) throw new Error(`An app has at most ${MAX_PAGES} pages.`);
		app.pages.push({ name: str(name, NAME_MAX) || `Page ${app.pages.length + 1}`, components: [] });
		return app.pages.length - 1;
	});
}

export function renamePage(raw, index, name) {
	return editApp(raw, (app) => {
		const page = app.pages[index];
		const to = str(String(name ?? '').trim(), NAME_MAX);
		if (!page || !to) return false;
		page.name = to;
		return true;
	});
}

/** Removes a page and what is on it. The last page stays: an app has one. */
export function removePage(raw, index) {
	return editApp(raw, (app) => {
		if (app.pages.length <= 1 || !app.pages[index]) return false;
		app.pages.splice(index, 1);
		return true;
	});
}

/** Moves a page to another place in the order. */
export function movePage(raw, from, to) {
	return editApp(raw, (app) => {
		if (!app.pages[from] || to < 0 || to >= app.pages.length || to === from) return false;
		const [page] = app.pages.splice(from, 1);
		app.pages.splice(to, 0, page);
		return true;
	});
}

/** The app's own settings: its title and description, and how it runs. */
export function setAppSettings(raw, patch) {
	return editApp(raw, (app) => {
		for (const key of ['title', 'description', 'run', 'open', 'edit_button']) {
			if (Object.prototype.hasOwnProperty.call(patch, key)) app[key] = patch[key];
		}
		const read = readApp({ app });
		Object.assign(app, { ...read, pages: app.pages });
		return true;
	});
}

/** Takes the app off the model. */
export function removeApp(raw) {
	if (!raw || !Object.prototype.hasOwnProperty.call(raw, 'app')) return false;
	delete raw.app;
	return true;
}

// --- following the model -------------------------------------------------------------

/** Every reference to the model an app holds: its targets and its series. */
function eachReference(raw, fn) {
	const pages = raw?.app?.pages;
	if (!Array.isArray(pages)) return;
	for (const page of pages) {
		for (const c of Array.isArray(page?.components) ? page.components : []) {
			if (!isObject(c)) continue;
			if (isObject(c.target)) fn(c.target);
			if (Array.isArray(c.series)) for (const s of c.series) if (isObject(s)) fn(s);
		}
	}
}

/**
 * A name after a rename or a move: the block's own, or -- for a series a run
 * names after a block, such as a far-field path's `Rock held` and
 * `Rock.gravel1` -- the block at the front of it, at a boundary.
 */
function followName(name, newNameOf) {
	const to = newNameOf(name);
	if (to) return to;
	for (const cut of [name.lastIndexOf(' '), name.lastIndexOf('.')]) {
		if (cut <= 0) continue;
		const head = newNameOf(name.slice(0, cut));
		if (head) return head + name.slice(cut);
	}
	return name;
}

/**
 * Follows a rename or a move of blocks into the app.
 *
 * Called by every edit in ./edit.js that changes what a block is called --
 * `renameBlock`, and the moves and sub-system renames through `retargetAll` --
 * with the same `newNameOf` they apply to the model's own references. Written
 * into the model as the file holds it rather than through `editApp`: a rename
 * is not an edit of the app, and should not tidy one.
 *
 * @param {(qualified: string) => string|null} newNameOf
 */
export function retargetAppNames(raw, newNameOf) {
	eachReference(raw, (ref) => {
		if (typeof ref.block === 'string' && ref.block) ref.block = followName(ref.block, newNameOf);
	});
}

/**
 * Follows an index rename: in every list named, an index `from` is now `to`.
 *
 * Several lists at once because a material is one material across the
 * catalogue and its radionuclide sub-set, which `renameIndex` renames together.
 */
export function renameAppIndex(raw, lists, from, to) {
	retargetAppIndexes(raw, new Map([...lists].map((l) => [l, new Map([[from, to]])])));
}

/**
 * Follows several index renames at once: `moves` is list name to a map of old
 * index to new. At once, so that two compartments swapping names -- which a
 * move can make of the indices of the compartment dimension -- swap here too,
 * rather than the second rename undoing the first.
 *
 * @param {Map<string, Map<string, string>>} moves
 */
export function retargetAppIndexes(raw, moves) {
	eachReference(raw, (ref) => {
		if (!isObject(ref.index)) return;
		for (const [list, m] of moves) {
			if (!Object.prototype.hasOwnProperty.call(ref.index, list)) continue;
			const was = ref.index[list];
			if (m.has(was)) ref.index[list] = m.get(was);
		}
	});
}

/** Follows a list rename: an index keyed by `from` is keyed by `to`. */
export function renameAppIndexList(raw, from, to) {
	if (UNSAFE_KEYS.has(to)) return;
	eachReference(raw, (ref) => {
		if (!isObject(ref.index) || !Object.prototype.hasOwnProperty.call(ref.index, from)) return;
		ref.index[to] = ref.index[from];
		delete ref.index[from];
	});
}

// --- numbers off a curve ----------------------------------------------------------------

/**
 * A series at one time: linear between the two output times either side, the
 * value itself on one, and NaN outside the run or where either side is not a
 * number.
 */
export function valueAt(t, values, time) {
	const n = Math.min(t?.length ?? 0, values?.length ?? 0);
	if (!n || !Number.isFinite(time)) return NaN;
	if (time < t[0] || time > t[n - 1]) return NaN;
	let lo = 0;
	let hi = n - 1;
	while (hi - lo > 1) {
		const mid = (lo + hi) >> 1;
		if (t[mid] <= time) lo = mid; else hi = mid;
	}
	if (t[lo] === time) return values[lo];
	if (t[hi] === time) return values[hi];
	const span = t[hi] - t[lo];
	if (!(span > 0)) return values[lo];
	return values[lo] + ((values[hi] - values[lo]) * (time - t[lo])) / span;
}

/**
 * One number off a series: see `STATISTICS`.
 *
 * Values that are not numbers -- a column still on its way is NaN throughout
 * -- are passed over, so a peak is the peak of what there is; a series with
 * nothing in it is NaN. The mean is over the time the run covers, by the
 * trapezoid rule on the output times, which is what "mean over the run" means
 * on a grid that is logarithmic.
 */
export function statistic(t, values, stat, at = null) {
	const n = Math.min(t?.length ?? 0, values?.length ?? 0);
	if (!n) return NaN;
	switch (stat) {
		case 'initial':
			for (let i = 0; i < n; i++) if (Number.isFinite(values[i])) return values[i];
			return NaN;
		case 'final':
			for (let i = n - 1; i >= 0; i--) if (Number.isFinite(values[i])) return values[i];
			return NaN;
		case 'max':
		case 'min':
		case 'max_time': {
			let best = NaN;
			let when = NaN;
			for (let i = 0; i < n; i++) {
				const v = values[i];
				if (!Number.isFinite(v)) continue;
				if (Number.isNaN(best) || (stat === 'min' ? v < best : v > best)) { best = v; when = t[i]; }
			}
			return stat === 'max_time' ? when : best;
		}
		case 'at':
			return valueAt(t, values, at == null ? NaN : at);
		case 'mean': {
			let area = 0;
			let span = 0;
			for (let i = 1; i < n; i++) {
				const a = values[i - 1];
				const b = values[i];
				const dt = t[i] - t[i - 1];
				if (!Number.isFinite(a) || !Number.isFinite(b) || !(dt > 0)) continue;
				area += 0.5 * (a + b) * dt;
				span += dt;
			}
			return span > 0 ? area / span : (n === 1 && Number.isFinite(values[0]) ? values[0] : NaN);
		}
		default:
			return NaN;
	}
}

/**
 * The times a table lists when it is given none: `rows` of the run's own
 * output times, spread evenly along the list -- which on a logarithmic grid is
 * evenly in the logarithm, the way the run was asked for -- always with the
 * first and the last.
 */
export function tableTimes(t, rows) {
	const n = t?.length ?? 0;
	if (!n) return [];
	const want = Math.max(2, Math.min(rows | 0, n));
	if (want >= n) return Array.from(t);
	const out = [];
	for (let k = 0; k < want; k++) out.push(t[Math.round((k * (n - 1)) / (want - 1))]);
	return [...new Set(out)];
}
