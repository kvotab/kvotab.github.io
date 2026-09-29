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
 * markup: the page builds every element and every run of text itself, and a
 * picture is kept only as a data address of one of five image types.
 *
 * **Laid out on a grid**: twelve columns across whatever width there is, and
 * rows of a fixed height. A component is a box of cells -- `x`, `y`, `w`,
 * `h` -- so the same app is laid out sensibly in a narrow window and a wide
 * one, and on a phone it becomes one column in reading order. Two boxes never
 * overlap: putting one where another is pushes the other down, and whatever
 * that lands on in turn (`settle`).
 *
 * **Parts hold parts.** A Panel is a titled box with a grid of its own, and
 * Tabs are several such grids, one showing at a time. Their contents are laid
 * out on twelve columns across the container, in rows of the page's height,
 * and a container grows to hold what is put in it. They nest three deep.
 * Wherever a part is, it is addressed by its id, and a place to put one is a
 * *where*: a page, or a container and which of its grids (`slot`).
 *
 * This file is pure: the app as data, its geometry and its edits. What an
 * input *sets* and what an output *reads* are questions about the model, and
 * they are in ./appinputs.js.
 */

/** Columns across the page, and across every container. Twelve divide into halves, thirds and quarters. */
export const APP_COLUMNS = 12;

/** How far down a page may go, in rows. */
export const MAX_ROWS = 400;

/** How tall one component may be, in rows. */
export const MAX_HEIGHT = 60;

/** How many pages an app may have. */
export const MAX_PAGES = 24;

/** How many components an app may have, over all its pages and containers. */
export const MAX_COMPONENTS = 300;

/** How many series one output may name. A chart shows at most 32 lines. */
export const MAX_SERIES = 32;

/** How many choices a drop-down or a set of option buttons may offer. */
export const MAX_OPTIONS = 60;

/** How many containers deep a part may be: a panel in a tab of a set of tabs in a panel. */
export const MAX_NEST = 3;

/** How many tabs one set of tabs may have. */
export const MAX_TABS = 12;

/**
 * How large a picture may be, as the data address it is kept as: about 1.5 MB
 * of image. A model file carries its pictures, and a picture larger than this
 * is made smaller before it is kept (see ../ui/appdesigner.js).
 */
export const IMAGE_MAX = 2000000;

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
 * shows something a run produced, a layout part holds other parts, and text
 * and pictures are none of those.
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
	panel: { group: 'layout', name: 'Panel', w: 6, h: 6, minW: 2, minH: 2 },
	tabs: { group: 'layout', name: 'Tabs', w: 8, h: 8, minW: 3, minH: 2 },
	text: { group: 'static', name: 'Text', w: 6, h: 2, minW: 1, minH: 1 },
	image: { group: 'static', name: 'Picture', w: 4, h: 4, minW: 1, minH: 1 },
};

/** The palette's groups, in the order it lists them. */
export const COMPONENT_GROUPS = [
	{ id: 'input', name: 'Inputs' },
	{ id: 'output', name: 'Results' },
	{ id: 'layout', name: 'Layout' },
	{ id: 'static', name: 'Text and pictures' },
];

/** The types that set something, and so carry a `target`. */
export const INPUT_TYPES = new Set(Object.keys(COMPONENTS).filter((t) => COMPONENTS[t].group === 'input' && t !== 'button'));

/** The types that show a run, and so carry `series`. */
export const OUTPUT_TYPES = new Set(Object.keys(COMPONENTS).filter((t) => COMPONENTS[t].group === 'output'));

/** The types that show one number, read off one series. */
export const SINGLE_SERIES = new Set(['value', 'gauge']);

/** The types that hold other parts. */
export const CONTAINER_TYPES = new Set(['panel', 'tabs']);

/** The results that read one number or one curve per series: see `CURVES`. */
export const CURVE_TYPES = new Set(['value', 'gauge', 'bars', 'table']);

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

/**
 * Which curve of a series a result reads: the run at the controls, or one of
 * what a sampled run of the app made of it -- the mean of its realisations,
 * or a percentile of them at each time. See `sampleModel` in ./appinputs.js.
 */
export const CURVES = {
	run: 'The run at the controls',
	mean: 'Mean of the realisations',
	p50: 'Median of the realisations',
	p5: '5th percentile',
	p25: '25th percentile',
	p75: '75th percentile',
	p95: '95th percentile',
};

/** The percentile each curve is, and the percentiles an app's sample is made at. */
export const CURVE_QUANTILE = { p5: 0.05, p25: 0.25, p50: 0.5, p75: 0.75, p95: 0.95 };
export const APP_PERCENTILES = [0.05, 0.25, 0.5, 0.75, 0.95];

/** What a chart draws behind its lines: nothing, or the sample's percentile bands. */
export const SPREADS = ['none', 'bands'];

/** When an app samples its spread: when asked, or after every change of a control. */
export const SPREAD_WHEN = ['button', 'change'];

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

/** How a picture fills its box: all of it shown, or the box filled and the rest cut off. */
export const FITS = ['contain', 'cover'];

/** What a button does. */
export const ACTIONS = ['run', 'sample', 'reset'];

/**
 * The looks an app can wear when it runs -- the styles of designprompts.dev
 * that suit a page of controls and charts, each drawn from this tool's own
 * palette of tokens (see `.app-theme-*` in css/app.css). `page` follows the
 * editor's own light and dark; every other one is one or the other.
 */
export const THEMES = [
	{ id: 'standard', name: 'Kompartment', mode: 'page' },
	{ id: 'saas', name: 'SaaS', mode: 'light' },
	{ id: 'swiss', name: 'Swiss', mode: 'light' },
	{ id: 'neo-brutalism', name: 'Neo-brutalism', mode: 'light' },
	{ id: 'bauhaus', name: 'Bauhaus', mode: 'light' },
	{ id: 'flat', name: 'Flat', mode: 'light' },
	{ id: 'neumorphism', name: 'Neumorphism', mode: 'light' },
	{ id: 'claymorphism', name: 'Claymorphism', mode: 'light' },
	{ id: 'newsprint', name: 'Newsprint', mode: 'light' },
	{ id: 'academia', name: 'Academia', mode: 'light' },
	{ id: 'luxury', name: 'Luxury', mode: 'light' },
	{ id: 'organic', name: 'Organic', mode: 'light' },
	{ id: 'retro', name: 'Retro', mode: 'light' },
	{ id: 'modern-dark', name: 'Modern dark', mode: 'dark' },
	{ id: 'terminal', name: 'Terminal', mode: 'dark' },
	{ id: 'cyberpunk', name: 'Cyberpunk', mode: 'dark' },
	{ id: 'art-deco', name: 'Art deco', mode: 'dark' },
];
const THEME_IDS = THEMES.map((t) => t.id);

/**
 * Keys that must never be written into an object from a file: the first
 * would set the object's prototype, and the other two are how a prototype is
 * reached. An index map is keyed by list names out of the file.
 */
const UNSAFE_KEYS = new Set(['__proto__', 'constructor', 'prototype']);

/**
 * A picture, as a data address: one of five image types, base64, and nothing
 * else in it. A picture drawn with `<img>` runs no script whatever its type --
 * an SVG included -- and a data address fetches nothing.
 */
const IMAGE_RE = /^data:image\/(?:png|jpeg|gif|webp|svg\+xml);base64,[A-Za-z0-9+/]+={0,2}$/;

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

/** A picture's data address, or nothing: see `IMAGE_RE`. */
export function readImageSrc(v) {
	return typeof v === 'string' && v.length <= IMAGE_MAX && IMAGE_RE.test(v) ? v : '';
}

/** The parts in one grid: read in order, as far as the app's allowance goes. */
function readList(v, depth, ctx) {
	const out = [];
	for (const c of Array.isArray(v) ? v : []) {
		if (ctx.count >= MAX_COMPONENTS) break;
		const r = readComponent(c, depth, ctx);
		if (r) out.push(r);
	}
	return out;
}

/** A set of tabs' tabs: at least one, each a name and a grid of parts. */
function readTabs(v, depth, ctx) {
	const out = [];
	for (const t of Array.isArray(v) ? v : []) {
		if (!isObject(t) || out.length >= MAX_TABS) continue;
		out.push({ name: str(t.name, NAME_MAX) || `Tab ${out.length + 1}`, components: readList(t.components, depth, ctx) });
	}
	if (!out.length) out.push({ name: 'Tab 1', components: [] });
	return out;
}

/**
 * The keys each type carries besides its place, with what each is when the
 * file does not say. The one list of them: `readComponent` reads through it
 * and `updateComponent` writes through it, so a key cannot be accepted by one
 * and dropped by the other. A container's contents are read a level down.
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
		spread: oneOf(c.spread, SPREADS), mean: c.mean === true,
	}),
	value: (c) => ({
		title: str(c.title), series: readSeriesList(c.series, 1),
		statistic: oneOf(c.statistic, Object.keys(STATISTICS), 'max'), at: num(c.at),
		digits: int(c.digits, 1, 10, 3), limit: num(c.limit),
		curve: oneOf(c.curve, Object.keys(CURVES)),
	}),
	gauge: (c) => ({
		title: str(c.title), series: readSeriesList(c.series, 1),
		statistic: oneOf(c.statistic, Object.keys(STATISTICS), 'max'), at: num(c.at),
		min: num(c.min), max: num(c.max), limit: num(c.limit),
		scale: oneOf(c.scale, SCALES),
		curve: oneOf(c.curve, Object.keys(CURVES)),
	}),
	bars: (c) => ({
		title: str(c.title), series: readSeriesList(c.series),
		statistic: oneOf(c.statistic, Object.keys(STATISTICS), 'max'), at: num(c.at),
		scale: oneOf(c.scale, SCALES, 'log'), sort: c.sort === true,
		curve: oneOf(c.curve, Object.keys(CURVES)),
	}),
	table: (c) => ({
		title: str(c.title), series: readSeriesList(c.series),
		rows: int(c.rows, 2, 200, 10),
		times: Array.isArray(c.times) ? c.times.map(num).filter((t) => t != null).slice(0, 200) : [],
		curve: oneOf(c.curve, Object.keys(CURVES)),
	}),
	panel: (c, depth, ctx) => ({ title: str(c.title), components: readList(c.components, depth + 1, ctx) }),
	tabs: (c, depth, ctx) => ({ tabs: readTabs(c.tabs, depth + 1, ctx) }),
	text: (c) => ({
		text: str(c.text, TEXT_MAX),
		style: oneOf(c.style, TEXT_STYLES), align: oneOf(c.align, ALIGNS),
	}),
	image: (c) => ({
		src: readImageSrc(c.src), alt: str(c.alt), fit: oneOf(c.fit, FITS), caption: str(c.caption),
	}),
};

function positive(v) {
	const n = num(v);
	return n != null && n > 0 ? n : null;
}

const ID_RE = /^[A-Za-z0-9_-]{1,40}$/;

/**
 * One component, as this file understands it -- or null for a type it does not
 * know, or for a container deeper than containers go. The geometry is clamped
 * to the grid and to the type's own floor.
 *
 * @param {number} [depth]  how many containers it is inside
 * @param {{count: number}} [ctx]  how many components the app has read so far
 */
export function readComponent(v, depth = 0, ctx = { count: 0 }) {
	if (!isObject(v)) return null;
	const type = typeof v.type === 'string' && Object.prototype.hasOwnProperty.call(COMPONENTS, v.type)
		? v.type : null;
	if (!type || (CONTAINER_TYPES.has(type) && depth >= MAX_NEST)) return null;
	ctx.count++;
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
		...PROPS[type](v, depth, ctx),
	};
}

/** A container's grids of parts: a panel's one, a set of tabs' one per tab. */
export function slotsOf(c) {
	if (c?.type === 'panel') return [c.components];
	if (c?.type === 'tabs') return c.tabs.map((t) => t.components);
	return [];
}

/**
 * The app a model carries, read: every key this file defines and nothing
 * else, every component with an id of its own, no two boxes overlapping, and
 * every container tall enough for what is in it.
 *
 * @returns {object|null} null when the model has no app at all
 */
export function readApp(raw) {
	const a = raw?.app;
	if (!isObject(a)) return null;
	const ctx = { count: 0 };
	const pages = [];
	for (const p of Array.isArray(a.pages) ? a.pages : []) {
		if (!isObject(p) || pages.length >= MAX_PAGES) continue;
		pages.push({ name: str(p.name, NAME_MAX) || `Page ${pages.length + 1}`, components: readList(p.components, 0, ctx) });
	}
	if (!pages.length) pages.push({ name: 'Main', components: [] });
	// Ids after the whole app is read, so a missing or repeated one is given
	// the next free number rather than one a later component already has.
	const app = {
		title: str(a.title),
		description: str(a.description, 2000),
		run: oneOf(a.run, RUN_WHEN),
		open: oneOf(a.open, OPENS),
		edit_button: a.edit_button !== false,
		theme: oneOf(a.theme, THEME_IDS),
		realisations: int(a.realisations, 10, 20000, 200),
		spread_when: oneOf(a.spread_when, SPREAD_WHEN),
		pages,
	};
	const all = allComponents(app).map((x) => x.component);
	const seen = new Set();
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
	for (const page of pages) tidy(page.components);
	return app;
}

/**
 * A grid put in order from the inside out: every container's own grids first,
 * then the container grown to hold them, then this grid settled.
 */
function tidy(list) {
	for (const c of list) {
		if (!CONTAINER_TYPES.has(c.type)) continue;
		for (const inner of slotsOf(c)) tidy(inner);
		fitBox(c);
	}
	placeAll(list, settle(list));
}

/**
 * A container at least as tall as what it holds: a row for its title or its
 * tabs, and the rows of its tallest grid under it. Never made shorter: a
 * container kept taller than its contents is somebody's choice.
 */
function fitBox(c) {
	const need = 1 + Math.max(0, ...slotsOf(c).map(rowsOf));
	c.h = Math.min(MAX_HEIGHT, Math.max(c.h, need));
}

/** Whether a model carries an app with anything on it. */
export function hasApp(raw) {
	const app = readApp(raw);
	return !!app && allComponents(app).length > 0;
}

/** A new app: one empty page. */
export function emptyApp() {
	return {
		title: '', description: '', run: 'change', open: 'editor', edit_button: true,
		theme: 'standard', realisations: 200, spread_when: 'button',
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

/**
 * Every component, with where it is: its page, the container it is in and
 * which of that container's grids (`parent`, `slot`), how many containers
 * deep it is, and the grid itself with its place in it (`list`, `index`).
 * Depth first, a container before what it holds.
 */
export function allComponents(app) {
	const out = [];
	const walk = (list, page, parent, slot, depth) => {
		list.forEach((component, index) => {
			out.push({ page, component, parent, slot, depth, list, index });
			slotsOf(component).forEach((inner, s) => walk(inner, page, component, s, depth + 1));
		});
	};
	(app?.pages ?? []).forEach((p, i) => walk(p.components, i, null, 0, 0));
	return out;
}

/** A component by id, with where it is: see `allComponents`. */
export function findComponent(app, id) {
	if (id == null) return null;
	return allComponents(app).find((x) => x.component.id === id) ?? null;
}

/**
 * A place to put a part: a page's own grid, or one of a container's. A bare
 * number is a page, which is what every place was before containers.
 */
export function whereOf(where) {
	if (typeof where === 'number') return { page: where, parent: null, slot: 0 };
	return { page: where?.page ?? 0, parent: where?.parent ?? null, slot: where?.slot ?? 0 };
}

/** The grid a place names, or null. */
export function listAt(app, where) {
	const w = whereOf(where);
	if (w.parent) return slotsOf(findComponent(app, w.parent)?.component)[w.slot] ?? null;
	return pageAt(app, w.page).components;
}

/** How many containers deep a part put in this place would be. */
function depthAt(app, where) {
	const w = whereOf(where);
	if (!w.parent) return 0;
	const f = findComponent(app, w.parent);
	return f ? f.depth + 1 : 0;
}

/** How many levels of containers a part is, itself and inside: 0 for a leaf. */
function nesting(c) {
	if (!CONTAINER_TYPES.has(c?.type)) return 0;
	return 1 + Math.max(0, ...slotsOf(c).flat().map(nesting));
}

/** Whether `id` is somewhere inside `outer`. */
function inside(app, id, outer) {
	for (let f = findComponent(app, id), guard = 0; f?.parent && guard < 20; guard++) {
		if (f.parent.id === outer) return true;
		f = findComponent(app, f.parent.id);
	}
	return false;
}

// --- the grid ------------------------------------------------------------------------

/** Whether two boxes share a cell. */
export function overlaps(a, b) {
	return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
}

/** How many rows a grid's boxes reach down to. */
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

/**
 * After a grid inside a container changed: the container grown to hold it,
 * the grid the container is in settled around the growth, and the same up
 * through every container above -- as far as anything grew.
 */
function fitUp(app, parentId) {
	let id = parentId;
	for (let guard = 0; id && guard <= MAX_NEST + 1; guard++) {
		const f = findComponent(app, id);
		if (!f) return;
		const before = f.component.h;
		fitBox(f.component);
		if (f.component.h === before) return;
		placeAll(f.list, settle(f.list, id));
		id = f.parent?.id ?? null;
	}
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

/** Every id a part and what it holds carry, made new, for a copy. */
function renumber(c, next) {
	c.id = `c${next()}`;
	for (const inner of slotsOf(c)) for (const child of inner) renumber(child, next);
}

/**
 * Adds a component and returns its id.
 *
 * `where` is a page, or a container's grid (see `whereOf`). `at` is where it
 * was dropped, as a cell; without one it goes in the first place it fits.
 * Either way what is under it moves out of the way, and a container it went
 * into grows to hold it.
 */
export function addComponent(raw, where, type, { at = null, props = {} } = {}) {
	if (!Object.prototype.hasOwnProperty.call(COMPONENTS, type)) {
		throw new Error(`There is no component called '${type}'.`);
	}
	return editApp(raw, (app) => {
		if (allComponents(app).length >= MAX_COMPONENTS) {
			throw new Error(`An app holds at most ${MAX_COMPONENTS} components.`);
		}
		const w = whereOf(where);
		const target = listAt(app, w);
		if (!target) throw new Error('There is no such place on the app.');
		const depth = depthAt(app, w);
		if (CONTAINER_TYPES.has(type) && depth >= MAX_NEST) {
			throw new Error(`Panels and tabs go ${MAX_NEST} deep at most.`);
		}
		const spec = COMPONENTS[type];
		const size = { w: num(props.w) ?? spec.w, h: num(props.h) ?? spec.h };
		const spot = at ?? freeSpot(target, size.w, size.h);
		const ids = allComponents(app).map((x) => x.component.id);
		let n = nextNumber(ids);
		const c = readComponent({ ...props, type, ...clampBox(type, { ...size, ...spot }) }, depth, { count: 0 });
		// The part and anything it brings with it -- a copy of a panel brings
		// its contents -- numbered past every id there is.
		renumber(c, () => n++);
		target.push(c);
		if (CONTAINER_TYPES.has(type)) fitBox(c);
		placeAll(target, settle(target, c.id));
		fitUp(app, w.parent);
		return c.id;
	});
}

/**
 * Changes some of a component's settings.
 *
 * Read again afterwards, through the same reader a file goes through, so an
 * edit can no more store an unknown key or an out-of-range number than a file
 * can. The type and the id are not settings, and nor is what a container
 * holds, which is changed by the edits that move parts.
 */
export function updateComponent(raw, id, patch) {
	return editApp(raw, (app) => {
		const found = findComponent(app, id);
		if (!found) return false;
		const { type, id: own } = found.component;
		const { components: _c, tabs: _t, ...settings } = patch ?? {};
		// What a container holds comes through as it was: the reading of the
		// part keeps the ids and places of its contents.
		const next = readComponent({ ...found.component, ...settings, type, id: own }, found.depth, { count: 0 });
		if (CONTAINER_TYPES.has(type)) fitBox(next);
		found.list[found.index] = next;
		// A change of size can reach into a neighbour.
		placeAll(found.list, settle(found.list, own));
		fitUp(app, found.parent?.id ?? null);
		return true;
	});
}

/** Moves or resizes a component in its own grid, pushing whatever it lands on down. */
export function placeComponent(raw, id, box) {
	return editApp(raw, (app) => {
		const found = findComponent(app, id);
		if (!found) return false;
		Object.assign(found.component, clampBox(found.component.type, box));
		if (CONTAINER_TYPES.has(found.component.type)) fitBox(found.component);
		placeAll(found.list, settle(found.list, id));
		fitUp(app, found.parent?.id ?? null);
		return true;
	});
}

/**
 * Takes a component to another grid -- another page, into a container or out
 * of one -- at a cell there, or into the first place it fits.
 *
 * Refused where it would go inside itself, or where the containers it is
 * made of would then go deeper than containers go.
 */
export function moveComponent(raw, id, where, at = null) {
	return editApp(raw, (app) => {
		const found = findComponent(app, id);
		if (!found) return false;
		const w = whereOf(where);
		if (w.parent && (w.parent === id || inside(app, w.parent, id))) {
			throw new Error('A part cannot be put inside itself.');
		}
		const target = listAt(app, w);
		if (!target) return false;
		if (depthAt(app, w) + nesting(found.component) > MAX_NEST) {
			throw new Error(`Panels and tabs go ${MAX_NEST} deep at most, and this would take them deeper.`);
		}
		const c = found.component;
		found.list.splice(found.index, 1);
		Object.assign(c, at
			? clampBox(c.type, { x: at.x, y: at.y, w: c.w, h: c.h })
			: { ...freeSpot(target, c.w, c.h), w: c.w, h: c.h });
		target.push(c);
		placeAll(target, settle(target, id));
		fitUp(app, w.parent);
		return true;
	});
}

export function removeComponent(raw, id) {
	return editApp(raw, (app) => {
		const found = findComponent(app, id);
		if (!found) return false;
		found.list.splice(found.index, 1);
		return true;
	});
}

/** A copy of a component -- and of what it holds -- beside it where there is room and below it where not. */
export function duplicateComponent(raw, id) {
	const app = readApp(raw);
	const found = findComponent(app, id);
	if (!found) return null;
	const c = found.component;
	const beside = { x: c.x + c.w, y: c.y, w: c.w, h: c.h };
	const at = beside.x + c.w <= APP_COLUMNS && !found.list.some((o) => overlaps(o, beside))
		? { x: beside.x, y: c.y }
		: { x: c.x, y: c.y + c.h };
	const { id: _drop, type, ...props } = structuredClone(c);
	return addComponent(raw, { page: found.page, parent: found.parent?.id ?? null, slot: found.slot }, type, { at, props });
}

/** Takes a component to another page, into the first place it fits there. */
export function moveComponentToPage(raw, id, page) {
	const app = readApp(raw);
	if (!app?.pages[page]) return false;
	return moveComponent(raw, id, { page, parent: null, slot: 0 });
}

/** A set of tabs, found for an edit of its tabs. */
function tabsOf(app, id) {
	const c = findComponent(app, id)?.component;
	return c?.type === 'tabs' ? c : null;
}

/** Adds a tab to a set of tabs and returns its place. */
export function addTab(raw, id, name = '') {
	return editApp(raw, (app) => {
		const c = tabsOf(app, id);
		if (!c) return -1;
		if (c.tabs.length >= MAX_TABS) throw new Error(`A set of tabs has at most ${MAX_TABS} of them.`);
		c.tabs.push({ name: str(name, NAME_MAX) || `Tab ${c.tabs.length + 1}`, components: [] });
		return c.tabs.length - 1;
	});
}

export function renameTab(raw, id, index, name) {
	return editApp(raw, (app) => {
		const tab = tabsOf(app, id)?.tabs[index];
		const to = str(String(name ?? '').trim(), NAME_MAX);
		if (!tab || !to) return false;
		tab.name = to;
		return true;
	});
}

/** Removes a tab and what is on it. The last tab stays: a set of tabs has one. */
export function removeTab(raw, id, index) {
	return editApp(raw, (app) => {
		const c = tabsOf(app, id);
		if (!c || c.tabs.length <= 1 || !c.tabs[index]) return false;
		c.tabs.splice(index, 1);
		return true;
	});
}

export function moveTab(raw, id, from, to) {
	return editApp(raw, (app) => {
		const c = tabsOf(app, id);
		if (!c?.tabs[from] || to < 0 || to >= c.tabs.length || to === from) return false;
		const [tab] = c.tabs.splice(from, 1);
		c.tabs.splice(to, 0, tab);
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

/** The app's own settings: its title and description, how it runs, how it looks. */
export function setAppSettings(raw, patch) {
	return editApp(raw, (app) => {
		for (const key of ['title', 'description', 'run', 'open', 'edit_button', 'theme', 'realisations', 'spread_when']) {
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

/**
 * How deep the walks below go into containers written in a file. Deeper than
 * any app is read (`MAX_NEST`), so nothing a reading keeps is missed, and
 * bounded, so a file nested ten thousand deep is not a stack to overflow.
 * python/kompartment/apps.py walks exactly as deep.
 */
const WALK_DEPTH = 8;

/** Every reference to the model an app holds -- its targets and its series -- wherever the part is. */
function eachReference(raw, fn) {
	const walk = (list, depth) => {
		if (!Array.isArray(list) || depth > WALK_DEPTH) return;
		for (const c of list) {
			if (!isObject(c)) continue;
			if (isObject(c.target)) fn(c.target);
			if (Array.isArray(c.series)) for (const s of c.series) if (isObject(s)) fn(s);
			walk(c.components, depth + 1);
			if (Array.isArray(c.tabs)) for (const t of c.tabs) if (isObject(t)) walk(t.components, depth + 1);
		}
	};
	const pages = raw?.app?.pages;
	if (!Array.isArray(pages)) return;
	for (const page of pages) if (isObject(page)) walk(page.components, 0);
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

/**
 * How many parts a model's app has, however it is written: every part on every
 * page, and every part inside a container. For the line an export writes
 * about what it left out; python/kompartment/io/ecoexport.py counts the same.
 */
export function countAppParts(raw) {
	let n = 0;
	const walk = (list, depth) => {
		if (!Array.isArray(list) || depth > WALK_DEPTH) return;
		for (const c of list) {
			n++;
			if (!isObject(c)) continue;
			walk(c.components, depth + 1);
			if (Array.isArray(c.tabs)) for (const t of c.tabs) if (isObject(t)) walk(t.components, depth + 1);
		}
	};
	const pages = raw?.app?.pages;
	if (Array.isArray(pages)) for (const p of pages) if (isObject(p)) walk(p.components, 0);
	return n;
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
