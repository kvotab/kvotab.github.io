/**
 * Charting and tabulating: what the Chart draws from what is picked
 * (../src/ui/chartplan.js), the looks of named lines (../src/ui/linestyles.js),
 * the chart's own window and panels (../src/ui/chart.js, ../src/ui/chartstack.js),
 * the Table's layouts (../src/ui/tableviews.js), numbers typed with a decimal
 * comma (../src/ui/readnum.js), the saved views and axes in the model, and the
 * tree as the chart's picker.
 *
 *   node test/run.js "charting"      the part the suite runs
 */

import { readFileSync, existsSync } from 'node:fs';
import * as ed from '../src/domain/edit.js';
import {
	NAMED_LINE_STYLES, NAMED_DASHES, namedStyle, dashOf, parseColor, contrast, forSurface, LINE_CONTRAST,
} from '../src/ui/linestyles.js';
import {
	planChart, describeBlock, indexOrder, identityStyle, largestLines, peakOf,
	PANEL_EACH_UP_TO, MOST_PANELS, MOST_PER_PANEL,
} from '../src/ui/chartplan.js';
import { readNumber, readNumberList } from '../src/ui/readnum.js';
import {
	valuesAt, peakRow, cellValue, pivotChoices, pivotCells, toTSV,
} from '../src/ui/tableviews.js';
import {
	TimeChart, lineLook, MAX_SERIES, MOST_LINES, SERIES_DASHES,
} from '../src/ui/chart.js';
import { ChartStack } from '../src/ui/chartstack.js';
import {
	AXIS_PREFIXES, unitWithPrefix, unitsWithPrefix, shiftDecimal, prefixExponent, powerOfTen,
} from '../src/ui/prefix.js';
import { SvgCanvas } from '../src/ui/svgcanvas.js';
import { renderBlockTree, treeTools, resetFolds } from '../src/ui/tree.js';

/** [name, fn] for the suite. */
export const TESTS = [];
const test = (name, fn) => TESTS.push([`charting: ${name}`, fn]);

function assert(cond, msg) {
	if (!cond) throw new Error(msg ?? 'assertion failed');
}

const json = (v) => JSON.stringify(v);
const src = (path) => readFileSync(new URL(path, import.meta.url), 'utf8');

/** `landscape.json`'s shape: four nuclides across three objects, two blocks of them, one over nuclides only, and a scalar. */
function landscapeOutputs() {
	const nucs = ['I-129', 'Tc-99', 'Ra-226', 'Pb-210'];
	const objs = ['Lake', 'Mire', 'Forest'];
	const outs = [];
	for (const block of ['Regolith', 'Water']) {
		for (const n of nucs) {
			for (const o of objs) {
				outs.push({
					kind: 'compartment', block, nuclide: n, dims: ['Radionuclides', 'Object'], index: [n, o],
					label: `${block} [${n}, ${o}]`, unit: 'Bq',
				});
			}
		}
	}
	for (const n of nucs) {
		outs.push({
			kind: 'compartment', block: 'Downstream', nuclide: n, dims: ['Radionuclides'], index: [n],
			label: `Downstream [${n}]`, unit: 'Bq',
		});
	}
	outs.push({ kind: 'expression', block: 'Dose', nuclide: null, dims: [], index: null, label: 'Dose', unit: 'Sv/year' });
	return outs;
}
const of = (outs, block) => outs.map((o, i) => [o, i]).filter(([o]) => o.block === block).map(([, i]) => i);
const at = (outs, label) => outs.findIndex((o) => o.label === label);

// --- the named lines --------------------------------------------------------------

test('the named line styles are the HDF5 Browser’s, so a nuclide looks the same in both', () => {
	const rb = new URL('../../resources/js/rb-chart-axes.js', import.meta.url);
	// The browser lives beside this tool in the site's repository; a copy of
	// the tool on its own has nothing to compare with.
	if (!existsSync(rb)) return;
	const text = readFileSync(rb, 'utf8');
	const m = /const NAMED_LINE_STYLES = (\{[\s\S]*?\n\});/.exec(text);
	assert(m, 'the browser no longer has the table where this looks for it');
	// The browser's own file, from this repository: read as the object it is.
	const theirs = new Function(`return ${m[1]};`)();
	const norm = (c) => String(c).replace(/\s+/g, '');
	assert(json(Object.keys(theirs)) === json(Object.keys(NAMED_LINE_STYLES)),
		`the names differ: ${Object.keys(theirs).filter((k) => !(k in NAMED_LINE_STYLES)).join(', ')}`
		+ ` / ${Object.keys(NAMED_LINE_STYLES).filter((k) => !(k in theirs)).join(', ')}`);
	for (const [name, s] of Object.entries(theirs)) {
		const mine = NAMED_LINE_STYLES[name];
		assert(norm(mine.color) === norm(s.color) && mine.dash === s.dash && mine.width === s.width,
			`${name}: ${json(mine)} against ${json(s)}`);
	}
	// Every pattern the table names is one this side can draw.
	for (const s of Object.values(NAMED_LINE_STYLES)) assert(s.dash in NAMED_DASHES, s.dash);
});

test('a name is looked up as it is, then in lower case, and an unknown one is not a style', () => {
	assert(namedStyle('I-129')?.color === 'rgb(30,144,255)', json(namedStyle('I-129')));
	assert(namedStyle('Ing_water')?.color === NAMED_LINE_STYLES.ing_water.color, 'a pathway in another case');
	assert(namedStyle('Unobtainium-1') === null, 'an unknown index has a style');
	assert(namedStyle('constructor') === null && namedStyle('toString') === null,
		'a name from the object prototype is taken for a style');
	assert(namedStyle(null) === null && namedStyle(undefined) === null, 'no name');
	assert(json(dashOf('dashdot')) === json([9, 3, 3, 3]) && json(dashOf('nonsense')) === '[]', 'the patterns');
});

test('a line’s colour is moved only as far as it takes to stand off the chart it is on', () => {
	const light = '#fcfcfb';
	const dark = '#1a1a19';
	const on = (c, bg) => contrast(parseColor(c), parseColor(bg));
	// Already standing off it: left exactly as it is.
	assert(forSurface('rgb(30,144,255)', light) === 'rgb(30,144,255)', 'I-129 moved on a light chart');
	assert(forSurface('rgb(30,144,255)', dark) === 'rgb(30,144,255)', 'I-129 moved on a dark chart');
	// White on a light chart, navy and black on a dark one: moved, to the floor.
	for (const [c, bg, floor] of [
		['rgb(255,255,255)', light, LINE_CONTRAST.light],
		['rgb(255,255,0)', light, LINE_CONTRAST.light],
		['rgb(0,0,128)', dark, LINE_CONTRAST.dark],
		['rgb(0,0,0)', dark, LINE_CONTRAST.dark],
	]) {
		const out = forSurface(c, bg);
		assert(out !== c, `${c} was not moved on ${bg}`);
		const k = on(out, bg);
		assert(k >= floor - 1e-9 && k < floor + 0.15, `${c} on ${bg}: ${out} at ${k.toFixed(3)}:1`);
	}
	// The hue is kept: navy made lighter is still blue.
	const [r, g, b] = parseColor(forSurface('rgb(0,0,128)', dark));
	assert(b > r && b > g, `navy became ${r},${g},${b}`);
	// What cannot be judged is not: a colour or a ground this cannot read, and
	// a colour asked to be transparent.
	assert(forSurface('var(--x)', light) === 'var(--x)', 'an unreadable colour was changed');
	assert(forSurface('rgb(0,0,0)', 'color-mix(in oklab, red, blue)') === 'rgb(0,0,0)', 'an unreadable ground');
	assert(forSurface('rgba(255,255,255,0)', light) === 'rgba(255,255,255,0)', 'transparent was made visible');
	// Colours as a file or a stylesheet writes them.
	assert(json(parseColor('#abc')) === json([170, 187, 204, 1]), 'three-digit hex');
	assert(json(parseColor('rgb(224, 234, 239)')) === json([224, 234, 239, 1]), 'rgb with spaces');
	assert(parseColor('rgba(1,2,3,0.5)')[3] === 0.5 && parseColor('hsl(0 0% 0%)') === null, 'rgba and hsl');
});

test('a line says what it is with a style, and the swatch beside it says the same', () => {
	const c = {
		surface: '#1a1a19', text: '#ffffff', muted: '#999', series: ['#a00', '#0a0', '#00a', '#aa0', '#0aa', '#a0a', '#555', '#fa0'],
	};
	// Placed by position: as before, hue and pattern from the place.
	let look = lineLook({}, 9, c);
	assert(look.stroke === '#0a0' && look.set === 1 && look.dash === SERIES_DASHES[1], json(look));
	// Named: its own colour, moved for the ground, and its own pattern.
	look = lineLook({ style: { kind: 'named', color: 'rgb(0,0,128)', dash: 'dot' } }, 0, c);
	assert(look.stroke !== 'rgb(0,0,128)' && json(look.dash) === json([3, 3]) && look.dashName === 'dot', json(look));
	// A total: the text colour, a little thicker.
	look = lineLook({ style: { kind: 'total' } }, 0, c);
	assert(look.stroke === '#ffffff' && look.width === 2.5 && !look.dash.length, json(look));
	// The palette at a place, and thinned for a second block.
	look = lineLook({ style: { kind: 'palette', color: 10, set: 1, thin: 1 } }, 0, c);
	assert(look.stroke === '#00a' && look.width === 1 && look.dash === SERIES_DASHES[1], json(look));
	// The mean beside a median, a scenario, the run beside: the pattern says
	// which, on the line's own colour.
	look = lineLook({ style: { kind: 'named', color: 'rgb(30,144,255)', dash: 'dash' }, set: 3 }, 0, c);
	assert(look.stroke === 'rgb(30,144,255)' && look.dash === SERIES_DASHES[3] && look.dashName === null, json(look));
	// What a chart will hold: lines placed by position up to what they can be
	// told apart by, lines with a style of their own up to many more.
	assert(MAX_SERIES === 32 && MOST_LINES > MAX_SERIES, `${MAX_SERIES} / ${MOST_LINES}`);
	const chart = Object.create(TimeChart.prototype);
	Object.assign(chart, { data: { t: new Float64Array(0), series: [] }, draw: () => {} });
	const lines = (n, style) => Array.from({ length: n }, (_, k) => ({ label: `s${k}`, values: new Float64Array(0), ...(style ? { style } : {}) }));
	let threw = false;
	try { chart.setData(new Float64Array(0), lines(33)); } catch { threw = true; }
	assert(threw, 'thirty-three placed lines were taken');
	chart.setData(new Float64Array(0), lines(54, { kind: 'named', color: 'rgb(0,0,0)', dash: 'solid' }));
	assert(chart.data.series.length === 54, 'fifty-four named lines were refused');
	// The stylesheet draws every named pattern on a swatch.
	const css = src('../css/app.css');
	for (const name of Object.keys(NAMED_DASHES)) {
		if (name === 'solid') continue;
		assert(new RegExp(`\\.series-swatch\\[data-dash="${name}"\\]\\s*\\{[^}]*repeating-linear-gradient`).test(css),
			`no swatch pattern for ${name}`);
	}
});

// --- the plan -----------------------------------------------------------------------

test('a block is drawn as one thing: a line per nuclide, a panel per object, and its total', () => {
	const outs = landscapeOutputs();
	const plan = planChart(outs, of(outs, 'Water'));
	assert(json(plan.panels.map((p) => p.title)) === json(['Water · Lake', 'Water · Mire', 'Water · Forest']),
		json(plan.panels.map((p) => p.title)));
	for (const p of plan.panels) {
		assert(json(p.lines.map((l) => l.label)) === json(['Total', 'I-129', 'Tc-99', 'Ra-226', 'Pb-210']),
			json(p.lines.map((l) => l.label)));
		assert(p.lines[0].total && p.lines[0].outputs.length === 4 && p.lines[0].style.kind === 'total', 'the total');
		assert(p.lines.slice(1).every((l) => l.outputs.length === 1 && l.style.kind === 'named'), 'a nuclide’s own colour');
		assert(p.unit === 'Bq', p.unit);
	}
	// The same nuclide wears the same colour in every panel, and in a chart of
	// something else entirely.
	const i129 = (pl) => pl.panels.flatMap((p) => p.lines).filter((l) => l.value === 'I-129').map((l) => json(l.style));
	const other = planChart(outs, of(outs, 'Downstream'));
	assert(new Set([...i129(plan), ...i129(other)]).size === 1, 'I-129 changes colour between charts');
	// The block, as described for the bar above the chart.
	const info = plan.blocks[0];
	assert(info.lines === 'Radionuclides' && json(info.others.map((x) => [x.list, x.how])) === json([['Object', 'panel']]),
		json(info));
	// Without the total.
	assert(!planChart(outs, of(outs, 'Water'), { total: false }).panels[0].lines.some((l) => l.total), 'a total drawn unasked');
});

test('the other list of a block can be added up, cut at one index, or made the lines', () => {
	const outs = landscapeOutputs();
	const water = of(outs, 'Water');
	const split = (c) => new Map([['Water', c]]);
	let plan = planChart(outs, water, { split: split({ others: { Object: 'sum' } }) });
	assert(plan.panels.length === 1 && plan.panels[0].title === 'Water · sum over Object', json(plan.panels.map((p) => p.title)));
	assert(plan.panels[0].lines.filter((l) => !l.total).every((l) => l.sum && l.outputs.length === 3), 'a nuclide is not the sum of its objects');
	plan = planChart(outs, water, { split: split({ others: { Object: 'Mire' } }) });
	assert(plan.panels.length === 1 && plan.panels[0].title === 'Water · Mire', json(plan.panels.map((p) => p.title)));
	assert(plan.panels[0].lines.filter((l) => !l.total)
		.every((l) => l.outputs.length === 1 && outs[l.outputs[0]].index[1] === 'Mire'), 'not cut at the mire');
	// Turned round: a line per object, for one nuclide.
	plan = planChart(outs, water, { split: split({ lines: 'Object', others: { Radionuclides: 'Tc-99' } }) });
	assert(plan.panels.length === 1 && json(plan.panels[0].lines.map((l) => l.label)) === json(['Total', 'Lake', 'Mire', 'Forest']),
		json(plan.panels[0].lines.map((l) => l.label)));
	// An object has no named colour, so it takes the palette at its place in
	// its own list -- the same place on every chart of the run.
	assert(json(plan.panels[0].lines.slice(1).map((l) => [l.style.kind, l.style.color])) === json([['palette', 0], ['palette', 1], ['palette', 2]]),
		json(plan.panels[0].lines.map((l) => l.style)));
	// A choice the block cannot have is not taken: an index it does not have,
	// a list it is not indexed by.
	plan = planChart(outs, water, { split: split({ lines: 'Nonsense', others: { Object: 'Atlantis' } }) });
	assert(plan.blocks[0].lines === 'Radionuclides' && plan.blocks[0].others[0].how === 'panel', json(plan.blocks[0]));
});

test('a list with more indices than a panel each would bear is cut at its first', () => {
	const outs = [];
	const paths = Array.from({ length: PANEL_EACH_UP_TO + 4 }, (_, k) => `P${k + 1}`);
	for (const n of ['I-129', 'Cs-135']) {
		for (const p of paths) {
			outs.push({ block: 'Flux', nuclide: n, dims: ['Radionuclides', 'FlowPaths'], index: [n, p], label: `Flux [${n}, ${p}]`, unit: 'Bq/year' });
		}
	}
	const plan = planChart(outs, outs.map((_, i) => i));
	assert(plan.panels.length === 1 && plan.panels[0].title === 'Flux · P1', json(plan.panels.map((p) => p.title)));
	assert(plan.blocks[0].others[0].how === 'P1', json(plan.blocks[0].others));
	// And a chart cut into more panels than it has room for draws what it has
	// room for, and says so.
	const wide = [];
	for (let k = 0; k < MOST_PANELS + 3; k++) {
		for (const n of ['I-129', 'Cs-135']) {
			wide.push({ block: 'Flux', nuclide: n, dims: ['Radionuclides', 'FlowPaths'], index: [n, `Q${k}`], label: `Flux [${n}, Q${k}]`, unit: 'Bq/year' });
		}
	}
	const many = planChart(wide, wide.map((_, i) => i), {
		split: new Map([['Flux', { lines: 'Radionuclides', others: { FlowPaths: 'panel' } }]]),
	});
	assert(many.panels.length === MOST_PANELS, String(many.panels.length));
	assert(many.notes.length === 1 && /3 more panels/.test(many.notes[0]), json(many.notes));
	// A panel of more lines than it draws keeps the first of them, and says so.
	const crowd = Array.from({ length: MOST_PER_PANEL + 5 }, (_, k) => ({
		block: 'Big', nuclide: `N${k}`, dims: ['Radionuclides'], index: [`N${k}`], label: `Big [N${k}]`, unit: 'Bq',
	}));
	const big = planChart(crowd, crowd.map((_, i) => i));
	assert(big.panels[0].lines.length === MOST_PER_PANEL && big.notes.length === 1, `${big.panels[0].lines.length} lines`);
});

test('series picked one by one go in one chart, a panel per unit, coloured by their places', () => {
	const outs = landscapeOutputs();
	const picks = [at(outs, 'Water [I-129, Lake]'), at(outs, 'Dose'), at(outs, 'Downstream [Tc-99]')];
	const plan = planChart(outs, picks);
	assert(plan.panels.length === 2, json(plan.panels.map((p) => p.key)));
	const bq = plan.panels.find((p) => p.unit === 'Bq');
	assert(json(bq.lines.map((l) => l.label)) === json(['Water [I-129, Lake]', 'Downstream [Tc-99]']),
		json(bq.lines.map((l) => l.label)));
	// The colours are the places on the chart, as lines picked one by one
	// always have been -- the third pick takes the third hue.
	assert(json(bq.lines.map((l) => [l.style.kind, l.style.color])) === json([['palette', 0], ['palette', 2]]),
		json(bq.lines.map((l) => l.style)));
	assert(!bq.lines.some((l) => l.total), 'loose lines were totalled');
});

test('Same chart puts the blocks together, the second thinner where it repeats the first', () => {
	const outs = landscapeOutputs();
	const plan = planChart(outs, [...of(outs, 'Downstream'), ...of(outs, 'Water')],
		{ layout: 'same', split: new Map([['Water', { others: { Object: 'sum' } }]]) });
	assert(plan.panels.length === 1, json(plan.panels.map((p) => p.key)));
	const lines = plan.panels[0].lines;
	assert(json(lines.filter((l) => l.total).map((l) => l.label)) === json(['Downstream total', 'Water total']),
		json(lines.map((l) => l.label)));
	const water = lines.filter((l) => l.block === 'Water');
	assert(water.every((l) => l.style.thin), 'the second block is drawn as thick as the first');
	assert(lines.filter((l) => l.block === 'Downstream').every((l) => !l.style.thin), 'the first block is thinned');
	assert(lines.some((l) => l.label === 'Water [I-129]'), 'a line of a shared chart does not say its block');
});

test('only the largest lines are drawn when that is asked, and every total stays', () => {
	const lines = [
		{ total: true, v: [1e9] }, { v: [5] }, { v: [500] }, { v: [50] }, { v: [-1, 0] }, { v: [NaN] },
	];
	const peak = (l) => peakOf(l.v, true);
	const { kept, left } = largestLines(lines, peak, 2);
	assert(kept.length === 3 && kept[0].total && kept.includes(lines[2]) && kept.includes(lines[3]) && left === 3,
		`${kept.length} kept, ${left} left`);
	assert(largestLines(lines, peak, 0).kept === lines, 'zero is not all');
	assert(peakOf([-1, 0], true) === -Infinity && peakOf([-1, 0]) === 0, 'a line that is never positive');
	assert(peakOf([NaN, 3, Infinity]) === 3, 'infinity is a peak');
	assert(json([...indexOrder(landscapeOutputs()).get('Object').entries()]) === json([['Lake', 0], ['Mire', 1], ['Forest', 2]]),
		'the places of a list’s indices');
	assert(identityStyle('Object', 'Forest', indexOrder(landscapeOutputs())).color === 2, 'a place is not a colour');
	assert(describeBlock(landscapeOutputs(), 'Dose', [at(landscapeOutputs(), 'Dose')]).scalar, 'a block with no index');
});

// --- the chart's window and its panels ------------------------------------------

/** A chart that can be painted in this process, as the tests of zooming have it. */
function bareChart(t, values) {
	const chart = Object.create(TimeChart.prototype);
	Object.assign(chart, {
		data: { t, series: values.map((v, k) => ({ label: `s${k}`, values: v })) },
		xLog: true, yLog: true, xLabel: 'Time', yLabel: '', hover: null, zoom: null, drag: null,
		draw: () => {},
	});
	return chart;
}

test('the axes can be set, a zoom can fix one axis, and the lines in the window are known', () => {
	const t = Float64Array.from({ length: 41 }, (_, i) => 10 ** (i / 10));
	const up = Float64Array.from(t, (x) => x);
	const late = Float64Array.from(t, (x) => (x > 100 ? 1e6 : NaN));
	const chart = bareChart(t, [up, late]);
	const auto = chart.window();
	assert(auto.xMin === 1 && auto.xMax === 1e4, json(auto));
	// Set: the ends that were set, and the data's for the rest.
	chart.setFixed({ xMin: 10, yMax: 1e8 });
	let w = chart.window();
	assert(w.xMin === 10 && w.xMax === 1e4 && w.yMax === 1e8, json(w));
	// A bound the scale cannot show is the data's.
	chart.setFixed({ xMin: -5, xMax: 100 });
	w = chart.window();
	assert(w.xMin === 1 && w.xMax === 100, json(w));
	// A pair the wrong way round is the data's.
	chart.setFixed({ xMin: 1000, xMax: 10 });
	assert(chart.window().xMin === 1 && chart.window().xMax === 1e4, json(chart.window()));
	chart.setFixed(null);
	assert(chart.fixed === null, 'the axes were not given back');
	// A window from another panel moves the time axis and leaves the values.
	chart.setXWindow(100, 1000);
	w = chart.window();
	assert(w.xMin === 100 && w.xMax === 1000 && w.yMin === auto.yMin && w.yMax === auto.yMax, json(w));
	assert(chart.isZoomed(), 'a window from another panel is not a zoom');
	// ...and it is not reported back, or two panels would answer each other.
	let told = 0;
	chart.onWindow = () => { told += 1; };
	chart.setXWindow(10, 1000);
	assert(told === 0, 'a window set from outside was passed on');
	chart.resetZoom();
	assert(told === 1 && !chart.isZoomed(), 'going back was not passed on');
	// The lines in the window: the late one has nothing before a hundred.
	chart.setXWindow(1, 50);
	assert(json([...chart.visibleSeries()]) === json([0]), json([...chart.visibleSeries()]));
	chart.setXWindow(200, 1e4);
	assert(json([...chart.visibleSeries()].sort()) === json([0, 1]), json([...chart.visibleSeries()]));
	// A line crossing the window between two points outside it is in it.
	const cross = bareChart(Float64Array.from([1, 10]), [Float64Array.from([1e-3, 1e3])]);
	cross.zoom = { xMin: 2, xMax: 5, yMin: 1e-3, yMax: 1e3 };
	assert(cross.visibleSeries().size === 1, 'a line crossing the window is outside it');
});

test('panels share one time axis: a gesture in one moves the others, and the menu’s zoom moves each once', () => {
	const stack = Object.create(ChartStack.prototype);
	const moved = [];
	const panel = (k) => ({
		index: k,
		chart: {
			setXWindow: (a, b) => moved.push([k, a, b]),
			zoomBy: () => { stack._moved(k, { xMin: 1, xMax: 2 }); },
			window: () => ({ xMin: 1, xMax: 2 }),
		},
	});
	Object.assign(stack, { panels: [panel(0), panel(1), panel(2)], onWindow: null });
	stack._moved(1, { xMin: 10, xMax: 100 });
	assert(json(moved) === json([[0, 10, 100], [2, 10, 100]]), json(moved));
	moved.length = 0;
	let told = 0;
	stack.onWindow = () => { told += 1; };
	stack.zoomBy(1.6);
	assert(!moved.length && told === 1, `the menu's zoom moved the time axis ${moved.length} more times`);
	// A picture of a stack carries the legend as the page shows it.
	const s = src('../src/ui/chartstack.js');
	assert(/p\.chart\._paint\(ctx, w, heights\[k\], \{ hover: false, legend: false, stash: false \}\);/.test(s)
		&& /paintLegend\(ctx, legend, w, y, c, band\);/.test(s), 'the picture is not the panels and the legend');
	const app = src('../src/ui/app.js');
	assert(/legend: legendEntries\.filter\(\(e\) => e\.shown !== false\)/.test(app), 'the picture’s legend is not the page’s');
});

// --- numbers, and the table ------------------------------------------------------

test('a number is read with a decimal comma, and a list of times with its separators', () => {
	const cases = [
		['6,21E12', 6.21e12], ['1 000', 1000], ['-2,5', -2.5], ['1e5', 1e5], ['0.015', 0.015],
		['−1,5', -1.5], ['1.5e', null], ['abc', null], ['0x10', null], ['Infinity', null], ['', null],
		['1,000.5', null], ['1,2,3', null],
	];
	for (const [text, want] of cases) {
		const got = readNumber(text);
		assert(got === want, `${json(text)} read as ${got}`);
	}
	let r = readNumberList('1e3, 1e4, 1e5');
	assert(json(r.values) === json([1e3, 1e4, 1e5]) && !r.bad.length, json(r));
	r = readNumberList('1,5; 2,5');
	assert(json(r.values) === json([1.5, 2.5]), json(r));
	r = readNumberList('1000 10000\t1e5');
	assert(json(r.values) === json([1000, 10000, 1e5]), json(r));
	r = readNumberList('1e3; soon; 1e4');
	assert(json(r.values) === json([1e3, 1e4]) && json(r.bad) === json(['soon']), json(r));
});

test('the peaks, a value between points, and a pivot that adds before it takes the number', () => {
	const t = [0, 10, 20, 30];
	const v = [0, 4, 8, 2];
	assert(json(valuesAt(t, v, [5, 25, -1, 99])) === json([2, 5, 0, 2]), json(valuesAt(t, v, [5, 25, -1, 99])));
	const row = peakRow(t, v, [15]);
	assert(row.peak === 8 && row.at === 20 && row.total === 20 + 60 + 50 && json(row.values) === json([6]), json(row));
	assert(cellValue('time_of_peak', t, v) === 20 && cellValue('integral', t, v) === 130 && cellValue('at', t, v, 25) === 5,
		'the cells');
	// The peak of a sum is not the sum of the peaks: two curves peaking at
	// different times.
	const a = [0, 10, 0, 0];
	const b = [0, 0, 0, 10];
	const outs = [
		{ block: 'Flux', dims: ['Nuclide', 'Path'], index: ['I-129', 'P1'], unit: 'Bq' },
		{ block: 'Flux', dims: ['Nuclide', 'Path'], index: ['I-129', 'P2'], unit: 'Bq' },
		{ block: 'Dose', dims: [], index: null, unit: 'Sv' },
	];
	const cells = pivotCells(outs, [0, 1, 2], { rows: 'Nuclide', cols: 'block' });
	assert(json(cells.rowKeys) === json(['I-129']) && json(cells.colKeys) === json(['Flux']), json(cells));
	assert(json(cells.cells.get('I-129\u0001Flux')) === json([0, 1]) && json(cells.summed) === json(['Path']), json(cells));
	assert(cells.left === 1 && cells.units.get('Flux') === 'Bq', 'the series with no row, or the unit');
	const sum = a.map((x, k) => x + b[k]);
	assert(cellValue('peak', t, sum) === 10 && cellValue('peak', t, a) + cellValue('peak', t, b) === 20, 'arithmetic');
	const app = src('../src/ui/app.js');
	assert(/for \(let j = 0; j < n; j\+\+\) sum\[j\] \+= v\[j\];\n\t\t\}\n\t\treturn cellValue\(kind, times, sum, at\);/.test(app),
		'a pivot cell takes the number of each series and adds those');
	// What lists and blocks a pivot can be made of.
	assert(json(pivotChoices(outs, [0, 2])) === json({ lists: ['Nuclide', 'Path'], blocks: ['Flux', 'Dose'] }), 'the choices');
	// Text for a spreadsheet: a tab or a line break inside a cell stays inside it.
	assert(toTSV([['a\tb', 'c\nd'], [1.5, NaN, Infinity, null]]) === 'a b\tc d\n1.5\t\t\t', json(toTSV([['a\tb', 'c\nd'], [1.5, NaN, Infinity, null]])));
});

// --- saved views and axes -----------------------------------------------------------

test('saved views and axes are read with suspicion, and written only when there are any', () => {
	const model = { name: 'm' };
	// Nothing to read: nothing.
	assert(!ed.chartPresets(model).length && !ed.chartViews(model).length, 'something from nothing');
	// A preset, a duplicate and junk.
	const changed = ed.setChartPresets(model, [
		{ name: ' Release ', x_scale: 'log', x_min: 100, x_max: 1e5, y_min: 'big' },
		{ name: 'Release', x_min: 1 },
		{ name: '' }, null, 'Dose', { name: 'Dose', y_scale: 'sideways', y_max: Infinity },
	]);
	assert(changed, 'nothing was written');
	const presets = ed.chartPresets(model);
	assert(json(presets.map((p) => p.name)) === json(['Release', 'Dose']), json(presets));
	assert(presets[0].x_min === 100 && presets[0].y_min === null && presets[1].y_scale === null && presets[1].y_max === null,
		json(presets));
	assert(!ed.setChartPresets(model, presets), 'the same list is a change');
	// Emptied: out of the file, and the view with it when it held nothing else.
	assert(ed.setChartPresets(model, []) && !('view' in model), json(model));
	model.view = { show_grid: false };
	ed.setChartPresets(model, [{ name: 'A' }]);
	ed.setChartPresets(model, []);
	assert(json(model.view) === json({ show_grid: false }), 'the rest of the view went with the presets');
	// A view, as a file might say one.
	ed.setChartViews(model, [{
		name: 'Release by nuclide', layout: 'stacked', total: 'yes', largest: 2.5,
		picks: [{ block: 'Outflow' }, { block: 'Water', labels: ['Water [I-129, Lake]', 3] }, { labels: ['x'] }],
		split: { Water: { lines: 'Radionuclides', others: { Object: 'sum', Bad: 4 } }, Broken: 'no' },
		x_min: 1000, x_scale: 'log',
	}]);
	const [v] = ed.chartViews(model);
	assert(v.layout === 'panels' && v.total === true && v.largest === 0 && v.peaks === false && v.in_view === true, json(v));
	assert(json(v.picks) === json([{ block: 'Outflow' }, { block: 'Water', labels: ['Water [I-129, Lake]'] }]), json(v.picks));
	assert(json(v.split) === json({ Water: { lines: 'Radionuclides', others: { Object: 'sum' } } }), json(v.split));
	assert(v.x_min === 1000 && v.x_scale === 'log' && v.y_min === null, json(v));
	// The view's scales and the rest of `view` are untouched by either.
	assert(ed.chartScales(model).xLog && json(ed.view(model).chart_views) === json(model.view.chart_views), 'the view');
});

// --- the tree beside a chart, and the endpoints -----------------------------------

test('beside the Chart and the Table, the tree is the chart’s picker, and the endpoints come first', () => {
	const app = src('../src/ui/app.js');
	const tree = src('../src/ui/tree.js');
	// The hooks, only beside the two tabs and a run.
	assert(/pick: pickHooks\(\),\n\t\}, treeFilter\(\), state\.tree\);/.test(app), 'the tree is not handed the picker');
	assert(/function pickingInTree\(\) \{\n\treturn \(state\.tab === 'chart' \|\| state\.tab === 'table'\) && !!shownRun\(\);/.test(app),
		'the tree picks beside the wrong tabs');
	assert(/const picking = pickingInTree\(\);\n\tif \(picking !== treePicking\) \{/.test(app), 'a change of tab leaves the tree as it was');
	// A box on a block, a box on each index of an opened one, Space to tick,
	// and a sub-system that opens where it is.
	assert(/if \(spec\.tick\) node\.append\(twisty, tickBox\(spec\.tick\)\);/.test(tree), 'no box on the rows');
	assert(/if \(open\) addIndexRows\(b, depth \+ 1, key, all, 0, \[\], all\.items\);/.test(tree), 'a block does not open into its indices');
	assert(/case ' ':\n\t\t\t\t\/\/ Beside a chart, Space ticks the row's box/.test(tree), 'Space does not tick');
	assert(/if \(pick\) \{ toggle\(state, node\.path, !open\); draw\(\); return; \}/.test(tree),
		'a sub-system beside the chart takes the page to the diagram');
	// The platform key adds a block to the chart as it adds it to the
	// selection, the way the HDF5 Browser compares datasets.
	assert(/if \(pick && all && \(ev\?\.metaKey \|\| ev\?\.ctrlKey\) && !ev\?\.shiftKey\) \{\n\t\t\t\t\t\tpick\.toggle\(/.test(tree),
		'⌘-click does not reach the chart');
	// Alt is that and nothing else.
	assert(/if \(ev\?\.altKey\) next = \[\.\.\.new Set\(indices\)\];/.test(app), 'Alt-click is not "only this"');
	// The endpoints: at the top of the tree, the chart opens on them, and the
	// star edits only the name it is on.
	assert(/if \(pick && !filtering && !narrowed\) \{[\s\S]*?for \(const name of pick\.endpoints \?\? \[\]\)/.test(tree), 'no Endpoints section');
	const def = /function pickDefaultSeries\(\) \{([\s\S]*?)\n\}/.exec(app)?.[1] ?? '';
	assert(def.indexOf('ed.endpoints(state.raw)') >= 0 && def.indexOf('ed.endpoints(state.raw)') < def.indexOf("o.kind === 'compartment'"),
		'the chart does not open on the endpoints first');
	const star = /function toggleEndpoint\(name\) \{([\s\S]*?)\n\}/.exec(app)?.[1] ?? '';
	assert(/const next = on \? stored\.filter\(\(n\) => n !== name\) : \[\.\.\.stored, name\];/.test(star)
		&& /modelChanged\(\{\n\t\t\tlayoutOnly: true,/.test(star), 'the star rewrites the list, or runs the model');
	// The endpoints a star shows are the model's, which leave parameters out.
	const model = {
		simulation: { endpoints: ['k', 'Water', 'Gone'] },
		parameters: [{ name: 'k', value: 1 }],
		compartments: [{ name: 'Water', initial: '0' }],
	};
	assert(json(ed.endpoints(model)) === json(['Water']), json(ed.endpoints(model)));
	// The settings line keeps a box being typed in as it is.
	assert(/if \(host\.contains\(document\.activeElement\) && document\.activeElement\.matches\('input\.axis-box'\)\) \{/.test(app)
		&& /if \(document\.activeElement === box\) continue;/.test(app), 'a box is redrawn under the typing');
	// Every new control has its (i), and its topic a heading in the Guide.
	const guide = src('../GUIDE.md');
	for (const heading of ['Picking from the tree', 'The table’s layouts', 'Saved views', 'The chart’s settings',
		'A block drawn as one thing', 'Panels, or one chart', 'The chart and the table']) {
		assert(guide.includes(`\n### ${heading}\n`) || guide.includes(`\n## ${heading}\n`), `no Guide heading ${heading}`);
	}
	assert(/infoButton\(`panel:\$\{where\}-pick`, \(\) => panelTopic\(where === 'chart' \? 'chart' : 'table'\)\)/.test(app),
		'the bars have no (i)');
});

/**
 * Just enough of a document for the tree and the buttons over it to be drawn
 * in Node: elements that hold their children, attributes, classes and
 * listeners, and find each other by one class.
 */
function stubDocument() {
	class Stub {
		constructor(tag) {
			this.tagName = String(tag).toUpperCase();
			this.nodeType = 1;
			this.children = [];
			this.parentNode = null;
			this.attributes = {};
			this.dataset = {};
			this.style = { setProperty() {} };
			this.className = '';
			this.listeners = {};
			const classes = () => this.className.split(/\s+/).filter(Boolean);
			this.classList = {
				contains: (c) => classes().includes(c),
				add: (...c) => { this.className = [...new Set([...classes(), ...c])].join(' '); },
				remove: (...c) => { this.className = classes().filter((x) => !c.includes(x)).join(' '); },
			};
		}

		setAttribute(k, v) { this.attributes[k] = String(v); }

		getAttribute(k) { return this.attributes[k] ?? null; }

		removeAttribute(k) { delete this.attributes[k]; }

		append(...kids) {
			for (const k of kids) {
				const n = typeof k === 'string' ? { nodeType: 3, text: k } : k;
				n.parentNode = this;
				this.children.push(n);
			}
		}

		replaceChildren(...kids) {
			this.children = [];
			this.append(...kids);
		}

		addEventListener(type, fn) { (this.listeners[type] ??= []).push(fn); }

		/** What a click on it does, with the event's own methods stubbed. */
		fire(type, ev = {}) {
			for (const fn of this.listeners[type] ?? []) fn({ preventDefault() {}, stopPropagation() {}, target: this, ...ev });
		}

		contains(n) {
			for (let x = n; x; x = x.parentNode) if (x === this) return true;
			return false;
		}

		querySelectorAll(sel) {
			const c = sel.replace(/^\./, '');
			const all = (n) => n.children.filter((k) => k.nodeType === 1).flatMap((k) => [k, ...all(k)]);
			return all(this).filter((n) => n.classList.contains(c));
		}

		querySelector(sel) { return this.querySelectorAll(sel)[0] ?? null; }

		get textContent() { return this.children.map((k) => (k.nodeType === 3 ? k.text : k.textContent)).join(''); }

		set textContent(t) { this.children = [{ nodeType: 3, text: String(t) }]; }

		focus() {}

		scrollIntoView() {}
	}
	return {
		createElement: (tag) => new Stub(tag),
		createElementNS: (ns, tag) => new Stub(tag),
		createTextNode: (t) => ({ nodeType: 3, text: String(t) }),
		activeElement: null,
	};
}

test('the star beside Collapse shows only the endpoints, in their sub-systems, with folds of their own', () => {
	// Two endpoints, one three deep and one at the top; a parameter the list
	// names, which is no endpoint; a block beside one, another sub-system, and
	// an empty one.
	const model = {
		name: 'Star',
		systems: ['Empty'],
		simulation: { endpoints: ['Near.Inner.Deep', 'Out', 'Near.k'] },
		parameters: [{ name: 'k', system: 'Near', value: 1 }],
		compartments: [
			{ name: 'Water', system: 'Near', initial: '0' },
			{ name: 'Deep', system: 'Near.Inner', initial: '0' },
			{ name: 'Rock', system: 'Far', initial: '0' },
			{ name: 'Out', initial: '0' },
		],
	};
	const hooksFor = (m) => {
		const starred = new Set(ed.endpoints(m));
		return {
			endpoints: [...starred],
			starred,
			isEndpoint: (n) => starred.has(n),
			canStar: (b) => ed.canBeEndpoint(b.kind),
			star: () => {},
			seriesOf: () => null,
			chartedBlocks: new Set(),
		};
	};
	const pick = hooksFor(model);
	assert(json([...pick.starred]) === json(['Near.Inner.Deep', 'Out']), json([...pick.starred]));

	// Everything from here to the restore is synchronous: `document` is
	// global, and the suite's tests run beside one another.
	const previous = globalThis.document;
	globalThis.document = stubDocument();
	try {
		const host = document.createElement('div');
		const view = { open: new Set(['']), group: false, endpoints: false };
		let project = model;
		let filter = null;
		let hooks = { pick };
		const draw = () => renderBlockTree(host, project, null, hooks, filter, view);
		const keys = () => (host.querySelector('.tree')?.children ?? []).map((n) => n.dataset?.key);
		const hint = () => host.querySelector('.hint')?.textContent ?? '';
		const tools = () => treeTools(project, view, draw, filter, !!hooks.pick);
		const button = (label) => tools().children.find((b) => b.textContent === label);
		const whole = ['ep:', 'e:b:Near.Inner.Deep', 'e:b:Out', '', 'Empty', 'Far', 'b:Far.Rock', 'Near', 'b:Out'];
		const narrowed = ['', 'Near', 'Near.Inner', 'b:Near.Inner.Deep', 'b:Out'];

		// The whole tree, as it is beside a chart: the endpoints on top, and
		// one sub-system opened by hand.
		draw();
		view.open.add('Far');
		draw();
		assert(json(keys()) === json(whole), json(keys()));
		// The star follows Collapse, empty while it is off.
		const bar = tools();
		assert(json(bar.children.map((b) => b.textContent)) === json(['Expand all', 'Collapse', '☆']),
			json(bar.children.map((b) => b.textContent)));
		assert(bar.children[2].getAttribute('aria-pressed') === 'false' && !bar.children[2].classList.contains('is-on'),
			'the star is on before it is pressed');

		// Pressed: the endpoints and the sub-systems they are in, opened down
		// to each -- no other block, no sub-system holding none, and no list on
		// top that would be every row twice.
		button('☆').fire('click');
		assert(view.endpoints === true, 'the star did not turn on');
		assert(json(keys()) === json(narrowed), json(keys()));
		const on = button('★');
		assert(on && on.getAttribute('aria-pressed') === 'true' && on.classList.contains('is-on'), 'the star is not filled');

		// Not a search: Collapse and Expand all fold it as they fold the whole tree.
		button('Collapse').fire('click');
		assert(json(keys()) === json(['']), json(keys()));
		button('Expand all').fire('click');
		assert(json(keys()) === json(narrowed), json(keys()));
		button('Collapse').fire('click');

		// A tab where the tree is not the picker shows the whole tree, folded
		// as it was left; back beside the chart, the narrowed one as it was left.
		hooks = {};
		draw();
		assert(json(keys()) === json(['', 'Empty', 'Far', 'b:Far.Rock', 'Near', 'b:Out']), json(keys()));
		assert(tools().children.every((b) => !b.classList.contains('tree-star')), 'a star away from the chart');
		hooks = { pick };
		draw();
		assert(json(keys()) === json(['']), json(keys()));

		// Off: every block, folded as it was before the star was pressed.
		button('★').fire('click');
		assert(view.endpoints === false && json(keys()) === json(whole), json(keys()));
		// On again, it opens onto every endpoint rather than onto the folds it
		// was left with.
		button('☆').fire('click');
		assert(json(keys()) === json(narrowed), json(keys()));

		// The search narrows it further, and a pinned answer too.
		filter = { query: 'Deep' };
		draw();
		assert(json(keys()) === json(['', 'Near', 'Near.Inner', 'b:Near.Inner.Deep']), json(keys()));
		filter = { query: 'Water' };
		draw();
		assert(hint() === 'No endpoint matches the search above.', hint());
		filter = { only: ['Out', 'Near.Water'] };
		draw();
		assert(json(keys()) === json(['b:Out']), json(keys()));
		filter = null;

		// Grouped by type, the kind headings over the endpoints open too.
		view.group = true;
		button('★').fire('click');
		button('☆').fire('click');
		assert(json(keys()) === json(['', 'Near', 'Near.Inner', 'Near.Inner :: compartments', 'b:Near.Inner.Deep',
			' :: compartments', 'b:Out']), json(keys()));
		view.group = false;

		// A model just opened: back to the top level, and narrowed it opens
		// onto the new model's endpoints.
		resetFolds(view);
		draw();
		assert(json(keys()) === json(narrowed), json(keys()));

		// A model with no endpoints says where the stars to fill are.
		project = { name: 'None', compartments: [{ name: 'A', system: 'S', initial: '0' }] };
		hooks = { pick: hooksFor(project) };
		draw();
		assert(hint().startsWith('No block is an endpoint. Turn off the ★ above'), hint());

		// With no sub-systems there is nothing to expand, and the star is
		// the row's only button -- beside a chart, and nowhere else.
		project = { name: 'Flat', simulation: { endpoints: ['A'] }, compartments: [{ name: 'A', initial: '0' }, { name: 'B', initial: '0' }] };
		hooks = { pick: hooksFor(project) };
		assert(json(tools().children.map((b) => b.textContent)) === json(['★']), json(tools().children.map((b) => b.textContent)));
		draw();
		assert(json(keys()) === json(['b:A']), json(keys()));
		hooks = {};
		assert(tools() === null, 'buttons over a flat tree away from the chart');
	} finally {
		if (previous === undefined) delete globalThis.document;
		else globalThis.document = previous;
	}
	// The page hands the tree what a star is on, and the count above it is
	// of the rows below.
	const app = src('../src/ui/app.js');
	assert(/starred,\n\t\tisEndpoint: \(name\) => starred\.has\(name\),/.test(app), 'the tree is not told the endpoints');
	assert(/const starred = pickingInTree\(\) && state\.tree\.endpoints \? new Set\(ed\.endpoints\(state\.raw\)\) : null;/.test(app),
		'the count is not of what the tree shows');
	assert(/resetFolds\(state\.tree\);/.test(app), 'a model just opened keeps the last one’s folds');
});

// --- one chart, prefixes, and the tree beside a run that changes ----------------

test('Same chart is one chart whatever the units, and a total never adds two of them', () => {
	const outs = [
		...['I-129', 'Cs-135'].map((n) => ({ block: 'Release', nuclide: n, dims: ['Radionuclides'], index: [n], label: `Release [${n}]`, unit: 'Bq/year' })),
		...['I-129', 'Cs-135'].map((n) => ({ block: 'Stock', nuclide: n, dims: ['Radionuclides'], index: [n], label: `Stock [${n}]`, unit: 'Bq' })),
		{ block: 'Rate', nuclide: null, dims: [], index: null, label: 'Rate', unit: '1/year' },
		// A material in kg beside nuclides in Bq: one block, two units.
		{ block: 'Mixed', nuclide: 'I-129', dims: ['Materials'], index: ['I-129'], label: 'Mixed [I-129]', unit: 'Bq' },
		{ block: 'Mixed', nuclide: 'C', dims: ['Materials'], index: ['C'], label: 'Mixed [C]', unit: 'kg' },
	];
	const all = outs.map((_, i) => i);
	const same = planChart(outs, all, { layout: 'same' });
	assert(same.panels.length === 1, json(same.panels.map((p) => p.key)));
	assert(json(same.panels[0].units) === json(['Bq/year', 'Bq', '1/year', 'kg']), json(same.panels[0].units));
	assert(same.panels[0].unit === 'Bq/year, Bq, 1/year, kg', same.panels[0].unit);
	const totals = same.panels[0].lines.filter((l) => l.total).map((l) => l.label);
	assert(json(totals) === json(['Release total', 'Stock total']), json(totals));
	// Panels still keep a unit to a panel.
	const panels = planChart(outs, all);
	assert(panels.panels.every((p) => p.units.length === 1), json(panels.panels.map((p) => p.units)));
	assert(!panels.panels.some((p) => p.lines.some((l) => l.total && l.block === 'Mixed')), 'a total across kg and Bq');
	// And the page says when a panel holds several.
	const app = src('../src/ui/app.js');
	assert(/if \(units\.length > 1\) \{\n\t\t\tnotes\.push\(`Mixed units on one axis/.test(app), 'mixed units on one axis go unsaid');
	assert(/for \(const p of panels\) p\.yLabel = unitsWithPrefix\(p\.units, ey\);/.test(app), 'the axis does not name every unit');
});

test('a prefix letters a unit as the HDF5 Browser does, and moves numbers by their digits', () => {
	const cases = [
		['Bq', 3, 'kBq'], ['Bq/year', 3, 'kBq/year'], ['mSv/year', 3, 'Sv/year'], ['mSv/year', -3, 'µSv/year'],
		['Sv', -6, 'µSv'], ['year', 3, 'kyear'], ['m3', 3, '10³ m3'], ['m^3/year', 3, '10³ m^3/year'],
		['1/year', 3, '10³ 1/year'], ['', 3, '10³'], ['-', -6, '10⁻⁶'], ['pH', 3, '10³ pH'], ['kg', 3, 'Mg'],
		['kg', -3, 'g'], ['Bq', 0, 'Bq'], ['day', 3, '10³ day'], ['GBq', 9, 'EBq'], ['TBq', 9, '10⁹ TBq'],
	];
	for (const [unit, e, want] of cases) {
		const got = unitWithPrefix(unit, e);
		assert(got === want, `${unit} at 10^${e}: ${got}`);
	}
	assert(unitsWithPrefix(['Bq', '', 'mSv'], 3) === 'kBq, Sv' && unitsWithPrefix([], -3) === '10⁻³'
		&& unitsWithPrefix([], 0) === '', 'several units, or none');
	assert(shiftDecimal(1.1e-7, -3) === 1.1e-10 && 1.1e-7 / 1000 !== 1.1e-10, 'a thousandth by arithmetic');
	assert(shiftDecimal(0, 3) === 0 && Number.isNaN(shiftDecimal(NaN, 3)) && shiftDecimal(-2.5e4, -3) === -25, 'zero, NaN, negative');
	assert(prefixExponent('µ') === -6 && prefixExponent('x') === 0 && prefixExponent('') === 0, 'the exponents');
	assert(powerOfTen(-12) === '10⁻¹²', powerOfTen(-12));
	// The model offers exactly the chart's prefixes.
	assert(json(ed.CHART_PREFIXES) === json(Object.keys(AXIS_PREFIXES)), json(ed.CHART_PREFIXES));
	// The browser's own code, where it is in reach, on the same cases and more.
	const rb = new URL('../../resources/js/rb-chart-axes.js', import.meta.url);
	if (!existsSync(rb)) return;
	const text = readFileSync(rb, 'utf8');
	// A browser from before it had prefixes has nothing to compare with.
	if (!text.includes('const AXIS_PREFIXES')) return;
	const from = text.indexOf('const AXIS_PREFIXES');
	// Up to the axis title: the unit rule and the helpers around it, which
	// only declare functions.
	const to = text.indexOf('function axisTitle');
	assert(from > 0 && to > from, 'the browser no longer has its prefixes where this looks for them');
	// The browser's own file, from this repository: its unit rule as it stands.
	const theirs = new Function(`${text.slice(from, to)}; return { unitWithPrefix, shiftDecimal, AXIS_PREFIXES };`)();
	assert(json(theirs.AXIS_PREFIXES) === json(AXIS_PREFIXES), 'the prefixes differ');
	const units = [...cases.map(([u]) => u), 'Sv/h', 'mol', 'mmol/kg', 'µg/L', 'ug', 'kBq/m2', 'Gy/s', 'yr', 'years', 'eV',
		'g/cm3', 'm-1', 'm²', 'kWh', 'Ci', 'nCi/g', '%', 'ppm', '1'];
	for (const u of units) {
		for (const e of [-15, -12, -9, -6, -3, 3, 6, 9, 12, 15]) {
			assert(theirs.unitWithPrefix(u, e) === unitWithPrefix(u, e), `${u} at 10^${e}: ${theirs.unitWithPrefix(u, e)} there, ${unitWithPrefix(u, e)} here`);
		}
	}
	for (const v of [1.1e-7, 123456.789, -0.5, 7, 3.3e300]) {
		for (const e of [-6, 3, 9]) assert(theirs.shiftDecimal(v, e) === shiftDecimal(v, e), `${v} by ${e}`);
	}
});

test('the chart letters its axes and readout in the prefixes, and keeps its window in the model’s numbers', () => {
	const t = Float64Array.from([1000, 2000, 5000, 10000]);
	const chart = Object.create(TimeChart.prototype);
	Object.assign(chart, {
		data: { t, series: [{ label: 'A', values: Float64Array.from([1e6, 2e6, 3e6, 4e6]) }] },
		xLog: false, yLog: false, xLabel: 'Time (kyear)', yLabel: 'kBq', hover: null, zoom: null, drag: null,
		draw: () => {},
		_colors: () => ({
			surface: '#fff', text: '#000', muted: '#555', faint: '#888', grid: '#eee', axis: '#999', accent: '#00f',
			band: '#00f2', series: Array(8).fill('#111'),
		}),
	});
	const labels = () => {
		const svg = new SvgCanvas(600, 400);
		chart._paint(svg, 600, 400, { hover: false });
		return [...svg.toSVG().matchAll(/<text[^>]*>([^<]*)<\/text>/g)].map((m) => m[1]);
	};
	const plain = labels();
	assert(plain.includes('4000') || plain.includes('10000'), json(plain));
	chart.setPrefixes({ x: 3, y: 3 });
	const kilo = labels();
	assert(kilo.includes('4') || kilo.includes('10'), `the time axis is not in thousands: ${json(kilo)}`);
	assert(!kilo.some((l) => /e\+?6/.test(l)) && kilo.some((l) => /^\d{3,4}$/.test(l)), `the values are not in thousands: ${json(kilo)}`);
	// The window is the model's, prefix or none.
	assert(chart.window().xMin === 1000 && chart.window().xMax === 10000, json(chart.window()));
	// A chart told nothing about prefixes letters its numbers as they are.
	chart.xExp = undefined;
	chart.yExp = undefined;
	assert(json(labels()) === json(plain), 'no prefix is a prefix');
	const css = src('../css/app.css');
	assert(/\.chart-settings select/.test(css), 'the prefix boxes are not styled with the settings');
});

test('prefixes are saved with the model only while one is set, and presets and views carry them', () => {
	const model = { name: 'm' };
	assert(json(ed.chartPrefixes(model)) === json({ x: '', y: '' }), 'something from nothing');
	assert(ed.setChartPrefixes(model, { y: 'µ' }) && model.view.chart_value_prefix === 'µ' && !('chart_time_prefix' in model.view),
		json(model));
	assert(!ed.setChartPrefixes(model, { y: 'µ' }), 'the same prefix is a change');
	assert(ed.setChartPrefixes(model, { x: 'k', y: 'nonsense' }) && json(ed.chartPrefixes(model)) === json({ x: 'k', y: '' }),
		json(ed.chartPrefixes(model)));
	assert(ed.setChartPrefixes(model, { x: '' }) && !('view' in model), json(model));
	// Read defensively from a file.
	assert(json(ed.chartPrefixes({ view: { chart_time_prefix: 'K', chart_value_prefix: 3 } })) === json({ x: '', y: '' }),
		'a prefix that is not one');
	ed.setChartPresets(model, [{ name: 'A', x_prefix: 'k', y_prefix: 'zz' }, { name: 'B' }]);
	const [a, b] = ed.chartPresets(model);
	assert(a.x_prefix === 'k' && a.y_prefix === '' && b.x_prefix === null && b.y_prefix === null, json([a, b]));
	ed.setChartViews(model, [{ name: 'V', picks: [], y_prefix: 'm' }]);
	assert(ed.chartViews(model)[0].y_prefix === 'm' && ed.chartViews(model)[0].x_prefix === null, json(ed.chartViews(model)));
	// The page: the boxes read and show the prefixed unit, a preset and a view
	// put theirs back, and changing one is an edit that runs nothing.
	const app = src('../src/ui/app.js');
	assert(/else next\[k\] = shiftDecimal\(v, e\);/.test(app), 'a typed bound is not read in the prefixed unit');
	assert(/box\.placeholder = win && Number\.isFinite\(win\[k\]\) \? axisNumber\(shiftDecimal\(win\[k\], -e\)\) : 'auto';/.test(app),
		'the boxes do not show the prefixed unit');
	assert(/const prefixed = ed\.setChartPrefixes\(state\.raw, \{\n\t\tx: p\.x_prefix \?\? undefined, y: p\.y_prefix \?\? undefined,/.test(app),
		'a preset or a view does not put its prefixes back');
	assert(/modelChanged\(\{ layoutOnly: true, label: 'Change the chart’s prefixes' \}\);/.test(app), 'a prefix change re-runs, or is no edit');
});

test('the chart opens on a few endpoints, a carried pick keeps its order, and the tree follows the run on screen', () => {
	const app = src('../src/ui/app.js');
	const def = /function pickDefaultSeries\(\) \{([\s\S]*?)\n\}/.exec(app)?.[1] ?? '';
	assert(/const first = \[\.\.\.new Set\(mine\.map\(\(m\) => m\.k\)\)\]\.slice\(0, DEFAULT_ENDPOINTS\);/.test(def),
		'the chart opens on every endpoint');
	assert(/const DEFAULT_ENDPOINTS = 3;/.test(app), 'how many endpoints the chart opens on');
	assert(/for \(const old of state\.selected\) \{\n\t\t\tconst i = at\.get\(state\.prevLabels\[old\]\);/.test(app),
		'a pick carried to the next run is put in the run’s order');
	assert(/if \(pickingInTree\(\) !== treePicking \|\| \(treePicking && treeRun !== shownRun\(\)\)\) renderRail\(\);/.test(app),
		'the tree is not drawn again for another run');
	assert(/toggle: \(indices, ev\) => \{ if \(live\(\)\) toggleSeries\(indices, ev\); \},/.test(app),
		'a box ticks a series of a run that is no longer on screen');
});
