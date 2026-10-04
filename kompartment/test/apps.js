/**
 * Apps on a model: the App designer's data (../src/domain/apps.js), what its
 * controls set and its results read (../src/domain/appinputs.js), the arithmetic
 * of its sliders and dials (../src/ui/appwidgets.js), and every rename in the
 * editor following into it.
 *
 * The one test that matters most is near the end: a run at an app's controls
 * is exactly the run of the model edited to the same values, bit for bit --
 * the app's copy of the model is the model, edited, and nothing else.
 *
 *   node test/run.js "apps on"      the part the suite runs
 */

import { readFileSync } from 'node:fs';
import * as apps from '../src/domain/apps.js';
import * as ai from '../src/domain/appinputs.js';
import * as ed from '../src/domain/edit.js';
import { Project } from '../src/domain/project.js';
import { run, outputsOf } from '../src/sim/runner.js';
import { buildSystem } from '../src/sim/builder.js';

/** [name, fn] for the suite. */
export const TESTS = [];
const test = (name, fn) => TESTS.push([`apps on a model: ${name}`, fn]);

function assert(cond, msg) {
	if (!cond) throw new Error(msg ?? 'assertion failed');
}

const json = (v) => JSON.stringify(v);

/** A bundled example, as the editor holds it once opened. */
function example(file) {
	let raw = JSON.parse(readFileSync(new URL(`../examples/${file}`, import.meta.url), 'utf8'));
	raw = ed.migrateKeys(raw);
	ed.materialiseShorthand(raw);
	return raw;
}

/** What a model reports, from its layout. */
function outputsOfModel(raw) {
	const project = new Project(structuredClone(raw));
	return outputsOf(buildSystem(project), project);
}

/** A small model: two compartments, a rate, a dose, a per-nuclide parameter. */
function small() {
	return {
		name: 'Small',
		simulation: { start_time: 0, end_time: 100, output_points: 50, spacing: 'linear', solver: 'ndf', rtol: 1e-8, abstol: 1e-12 },
		index_lists: [{ name: 'N', indices: [{ name: 'a' }, { name: 'b' }] }],
		parameters: [
			{ name: 'k', value: 0.05, unit: '1/year', pdf: { kind: 'logu', params: { min: 0.01, max: 0.2 } } },
			{ name: 'f', value: 2, index_lists: ['N'], entries: [{ index: { N: 'a' }, value: 3 }, { index: { N: 'b' }, value: 5 }] },
		],
		compartments: [{ name: 'A', initial: '100' }, { name: 'B', initial: '0' }, { name: 'C', initial: '2 * k' }],
		transfers: [{ name: 'T', from: 'A', to: 'B', rate: 'k' }],
		expressions: [{ name: 'D', equation: 'B * 2', unit: 'Sv' }],
	};
}

// --- reading ------------------------------------------------------------------------

test('an app is read for what this file defines, and nothing else', () => {
	const raw = {
		app: {
			title: 'T', run: 'nonsense', open: 'app', edit_button: false, extra: 'dropped',
			pages: [{
				name: 'P',
				components: [
					{ id: 'a', type: 'slider', x: 30, y: -4, w: 1, h: 99, target: { kind: 'value', block: 'k', index: { __proto__: null, N: 'a' } }, min: '0.1', max: 2, scale: 'weird', onload: 'x' },
					{ id: 'a', type: 'chart', series: [{ block: 'D' }, { nope: 1 }, 'str'] },
					{ type: 'iframe', src: 'https://example.com' },
					{ id: 'bad id!', type: 'text', text: 42 },
					'not an object',
				],
			}, 'not a page'],
		},
	};
	const app = apps.readApp(raw);
	assert(app.run === 'change' && app.open === 'app' && app.edit_button === false && !('extra' in app), json(app));
	const [s, c, t] = app.pages[0].components;
	assert(app.pages.length === 1 && app.pages[0].components.length === 3, json(app.pages));
	// Clamped to the grid and the slider's floor; the range read as numbers.
	assert(s.w === 2 && s.x === 10 && s.y === 0 && s.h === apps.MAX_HEIGHT, json(s));
	assert(s.min === 0.1 && s.max === 2 && s.scale === 'linear' && !('onload' in s), json(s));
	// A repeated id and a malformed one are given free ones.
	assert(s.id === 'a' && c.id !== 'a' && t.id !== 'bad id!' && new Set([s.id, c.id, t.id]).size === 3, json([s.id, c.id, t.id]));
	assert(c.series.length === 1 && c.series[0].block === 'D', json(c.series));
	assert(t.text === '', json(t));
	// Nothing overlaps once read: the chart was on top of the slider.
	assert(!apps.overlaps(s, c), json([s, c]));
	// No app, no reading; an app with no pages has one.
	assert(apps.readApp({}) === null && apps.readApp({ app: [] }) === null);
	assert(apps.readApp({ app: {} }).pages.length === 1);
});

test('an index keyed by __proto__ is never written into an object', () => {
	const text = '{"app":{"pages":[{"components":[{"type":"value","series":[{"block":"D","index":{"__proto__":{"polluted":1},"N":"a"}}]}]}]}}';
	const app = apps.readApp(JSON.parse(text));
	const ref = app.pages[0].components[0].series[0];
	assert(json(ref.index) === '{"N":"a"}' && ({}).polluted === undefined && Object.getPrototypeOf(ref.index) === Object.prototype, json(ref));
});

test('an app holds at most so many parts and pages', () => {
	const many = Array.from({ length: apps.MAX_COMPONENTS + 20 }, () => ({ type: 'text' }));
	const app = apps.readApp({ app: { pages: [{ components: many }, ...Array.from({ length: 40 }, () => ({}))] } });
	assert(apps.allComponents(app).length === apps.MAX_COMPONENTS, String(apps.allComponents(app).length));
	assert(app.pages.length === apps.MAX_PAGES, String(app.pages.length));
});

// --- the grid ------------------------------------------------------------------------

test('a part put on another pushes it down, and whatever that lands on in turn', () => {
	const items = [
		{ id: 'a', x: 0, y: 0, w: 4, h: 2 },
		{ id: 'b', x: 0, y: 2, w: 4, h: 2 },
		{ id: 'c', x: 2, y: 4, w: 4, h: 2 },
		{ id: 'z', x: 8, y: 0, w: 4, h: 3 },
	];
	// `a` grows onto `b`, which lands on `c`.
	const where = apps.settle(items.map((i) => (i.id === 'a' ? { ...i, h: 3 } : i)), 'a');
	assert(json(where.get('a')) === '{"x":0,"y":0,"w":4,"h":3}', json(where.get('a')));
	assert(where.get('b').y === 3 && where.get('c').y === 5 && where.get('z').y === 0, json([...where]));
	// Nothing is pulled up to fill a gap: a gap is somebody's choice.
	const gap = apps.settle([{ id: 'a', x: 0, y: 5, w: 2, h: 1 }]);
	assert(gap.get('a').y === 5, json([...gap]));
});

test('a new part goes in the first place it fits, and is clamped to the grid', () => {
	const items = [{ id: 'a', x: 0, y: 0, w: 4, h: 2 }, { id: 'b', x: 4, y: 0, w: 8, h: 8 }];
	assert(json(apps.freeSpot(items, 4, 2)) === '{"x":0,"y":2}', json(apps.freeSpot(items, 4, 2)));
	assert(json(apps.freeSpot(items, 12, 1)) === '{"x":0,"y":8}', json(apps.freeSpot(items, 12, 1)));
	assert(json(apps.clampBox('chart', { x: 11, y: -3, w: 1, h: 1 })) === '{"x":9,"y":0,"w":3,"h":4}',
		json(apps.clampBox('chart', { x: 11, y: -3, w: 1, h: 1 })));
});

test('a part resized at the right-hand edge keeps its left edge, and a part moved there moves left', () => {
	assert(json(apps.clampBox('slider', { x: 8, y: 0, w: 6, h: 2 }, { keepLeft: true })) === '{"x":8,"y":0,"w":4,"h":2}',
		json(apps.clampBox('slider', { x: 8, y: 0, w: 6, h: 2 }, { keepLeft: true })));
	assert(json(apps.clampBox('slider', { x: 8, y: 0, w: 6, h: 2 })) === '{"x":6,"y":0,"w":6,"h":2}');
	// Never narrower than the type allows, even against the edge.
	assert(json(apps.clampBox('chart', { x: 11, y: 0, w: 1, h: 4 }, { keepLeft: true })) === '{"x":9,"y":0,"w":3,"h":4}');
});

test('a narrow page stacks band by band, and each band column by column', () => {
	// Sliders down the left beside a chart, then three numbers along a row
	// over a table: the sliders come before the chart, and the numbers in a row.
	const items = [
		{ id: 's1', x: 0, y: 0, w: 4, h: 2 }, { id: 'chart', x: 4, y: 0, w: 8, h: 6 },
		{ id: 's2', x: 0, y: 2, w: 4, h: 2 }, { id: 's3', x: 0, y: 4, w: 4, h: 2 },
		{ id: 'v1', x: 0, y: 6, w: 4, h: 2 }, { id: 'v3', x: 8, y: 6, w: 4, h: 2 }, { id: 'v2', x: 4, y: 6, w: 4, h: 2 },
		{ id: 'table', x: 0, y: 8, w: 12, h: 4 },
	];
	const order = apps.stackOrder(items).map((i) => i.id).join();
	assert(order === 's1,s2,s3,chart,v1,v2,v3,table', order);
});

// --- edits ----------------------------------------------------------------------------

test('parts are added, changed, moved, copied and removed through the reader', () => {
	const raw = small();
	const a = apps.addComponent(raw, 0, 'slider', { props: { target: { kind: 'value', block: 'k' }, min: 0.01, max: 1 } });
	const b = apps.addComponent(raw, 0, 'chart', { at: { x: 0, y: 0 }, props: { series: [{ block: 'D' }] } });
	let app = apps.readApp(raw);
	const [sa, sb] = [apps.findComponent(app, a).component, apps.findComponent(app, b).component];
	// The chart dropped on the slider pushed it down.
	assert(a === 'c1' && b === 'c2' && sb.y === 0 && sa.y === sb.h, json(app.pages[0].components));
	// A change is read again: no unknown key, no new type, no out-of-range size.
	apps.updateComponent(raw, a, { type: 'chart', id: 'x', label: 'L', w: 99, evil: true });
	app = apps.readApp(raw);
	const after = apps.findComponent(app, a).component;
	assert(after.type === 'slider' && after.id === a && after.label === 'L' && after.w === 12 && !('evil' in after), json(after));
	// Stored exactly as read: the next read changes nothing.
	assert(json(apps.readApp(raw)) === json(raw.app));
	const copy = apps.duplicateComponent(raw, b);
	app = apps.readApp(raw);
	const cb = apps.findComponent(app, copy).component;
	assert(cb.type === 'chart' && json(cb.series) === json(sb.series) && !apps.overlaps(cb, apps.findComponent(app, b).component), json(cb));
	apps.placeComponent(raw, a, { x: 0, y: 0, w: 4, h: 2 });
	app = apps.readApp(raw);
	assert(apps.findComponent(app, a).component.y === 0 && apps.findComponent(app, b).component.y === 2, json(app.pages[0].components));
	assert(apps.removeComponent(raw, copy) && !apps.findComponent(apps.readApp(raw), copy));
	let refused = null;
	try { apps.addComponent(raw, 0, 'iframe'); } catch (e) { refused = e.message; }
	assert(/no component called/.test(refused ?? ''), refused);
});

test('pages are added, renamed, moved and removed, and the last one stays', () => {
	const raw = small();
	apps.addComponent(raw, 0, 'text', { props: { text: 'one' } });
	assert(apps.addPage(raw, 'Two') === 1 && apps.addPage(raw) === 2);
	let app = apps.readApp(raw);
	assert(app.pages.map((p) => p.name).join() === 'Main,Two,Page 3', app.pages.map((p) => p.name).join());
	apps.renamePage(raw, 2, '  Three ');
	apps.movePage(raw, 0, 2);
	const id = apps.allComponents(apps.readApp(raw))[0].component.id;
	apps.moveComponentToPage(raw, id, 0);
	app = apps.readApp(raw);
	assert(app.pages.map((p) => p.name).join() === 'Two,Three,Main' && app.pages[0].components.length === 1, json(app.pages));
	apps.removePage(raw, 0);
	apps.removePage(raw, 0);
	assert(!apps.removePage(raw, 0) && apps.readApp(raw).pages.length === 1, 'the last page went');
	apps.setAppSettings(raw, { title: 'X', run: 'button', open: 'nope', pages: [] });
	app = apps.readApp(raw);
	assert(app.title === 'X' && app.run === 'button' && app.open === 'editor' && app.pages.length === 1, json(app));
	assert(apps.removeApp(raw) && !('app' in raw) && !apps.removeApp(raw));
});

// --- following the model ----------------------------------------------------------------

/** A model with an app that names `k`, `f` at `N=a`, `D`, and a far-field style name. */
function withApp() {
	const raw = small();
	raw.app = {
		pages: [{
			components: [
				{ id: 's', type: 'slider', target: { kind: 'value', block: 'k' }, min: 0.01, max: 1 },
				{ id: 'n', type: 'number', target: { kind: 'value', block: 'f', index: { N: 'a' } } },
				{ id: 'w', type: 'switch', target: { kind: 'enabled', block: 'T' } },
				{ id: 'c', type: 'chart', series: [{ block: 'D' }, { block: 'A held', index: { N: 'b' } }, { block: 'B', index: { Compartments: 'A' } }] },
			],
		}],
	};
	return raw;
}

const refs = (raw) => apps.readApp(raw).pages[0].components.flatMap((c) => [c.target, ...(c.series ?? [])].filter(Boolean));

test('a rename, a move and a sub-system rename follow into the app', () => {
	const raw = withApp();
	ed.renameBlock(raw, 'k', 'rate');
	ed.renameBlock(raw, 'T', 'Flow');
	ed.renameBlock(raw, 'A', 'Source');
	const r = refs(raw);
	assert(r[0].block === 'rate' && r[2].block === 'Flow', json(r));
	// A series named after a block follows it, and so does a compartment's
	// name where it is an index of the compartment dimension.
	assert(r[4].block === 'Source held' && r[5].index.Compartments === 'Source', json(r));
	ed.addSystem(raw, { name: 'Sub' });
	ed.moveBlock(raw, 'D', 'Sub');
	assert(refs(raw)[3].block === 'Sub.D', json(refs(raw)));
	ed.renameSystem(raw, 'Sub', 'Post');
	assert(refs(raw)[3].block === 'Post.D', json(refs(raw)));
});

test('an index and a list renamed follow into the app', () => {
	const raw = withApp();
	ed.renameIndex(raw, 'N', 'a', 'alpha');
	let r = refs(raw);
	assert(r[1].index.N === 'alpha' && r[4].index.N === 'b', json(r));
	ed.renameIndexList(raw, 'N', 'Nuc');
	r = refs(raw);
	assert(json(r[1].index) === '{"Nuc":"alpha"}' && json(r[4].index) === '{"Nuc":"b"}', json(r));
});

test('a paste does not pull the app onto the copies', () => {
	const raw = withApp();
	const before = json(raw.app);
	ed.pasteBlocks(raw, ed.copyBlocks(raw, ['k', 'A', 'T']), { system: '' });
	assert(json(raw.app) === before, json(raw.app));
});

// --- what an input sets -----------------------------------------------------------------

test('two controls on the same thing share one key, whatever order the index is written in', () => {
	const a = ai.targetKey({ kind: 'value', block: 'X', index: { A: '1', B: '2' } });
	const b = ai.targetKey({ kind: 'value', block: 'X', index: { B: '2', A: '1' } });
	assert(a === b && a !== ai.targetKey({ kind: 'value', block: 'X', index: { A: '1', B: '2' }, factor: true }), `${a} ${b}`);
	assert(ai.targetKey({ kind: 'scenario' }) === 'scenario' && ai.targetKey(null) === null);
});

test('an input starts where the model stands, and says what stops it', () => {
	const raw = small();
	const v = (t) => ai.modelValue(raw, t);
	assert(v({ kind: 'value', block: 'k' }) === 0.05 && v({ kind: 'value', block: 'f', index: { N: 'b' } }) === 5);
	assert(v({ kind: 'value', block: 'A' }) === 100 && v({ kind: 'value', block: 'f', factor: true }) === 1);
	assert(v({ kind: 'value', block: 'C' }) === null, 'an equation is not a number');
	assert(v({ kind: 'end_time' }) === 100 && v({ kind: 'enabled', block: 'T' }) === true && v({ kind: 'scenario' }) === null);
	const p = (t, type = 'slider') => ai.targetProblem(raw, t, type);
	assert(p({ kind: 'value', block: 'k' }) === null && p({ kind: 'value', block: 'f', factor: true }) === null);
	assert(/not in the model/.test(p({ kind: 'value', block: 'nope' })));
	assert(/only a parameter/.test(p({ kind: 'value', block: 'D' })), p({ kind: 'value', block: 'D' }));
	assert(/Choose which N/.test(p({ kind: 'value', block: 'f' })));
	assert(/'c' is not in 'N'/.test(p({ kind: 'value', block: 'f', index: { N: 'c' } })));
	assert(/cannot set/.test(p({ kind: 'enabled', block: 'T' }, 'slider')) && p({ kind: 'enabled', block: 'T' }, 'switch') === null);
	assert(/no scenarios/.test(p({ kind: 'scenario' }, 'dropdown')));
	assert(/Not connected/.test(p(null)));
});

test('a slider over a parameter spans its distribution, and a decade either side where it has none', () => {
	const raw = small();
	assert(json(ai.defaultRange(raw, { kind: 'value', block: 'k' })) === '{"min":0.01,"max":0.2,"scale":"log"}',
		json(ai.defaultRange(raw, { kind: 'value', block: 'k' })));
	assert(json(ai.defaultRange(raw, { kind: 'value', block: 'f', index: { N: 'a' } })) === '{"min":0.3,"max":30,"scale":"log"}');
	assert(json(ai.defaultRange(raw, { kind: 'value', block: 'f', factor: true })) === '{"min":0.1,"max":10,"scale":"log"}');
	assert(json(ai.defaultRange(raw, { kind: 'end_time' })) === '{"min":10,"max":200,"scale":"linear"}',
		json(ai.defaultRange(raw, { kind: 'end_time' })));
	raw.simulation.spacing = 'log';
	assert(json(ai.defaultRange(raw, { kind: 'end_time' })) === '{"min":1,"max":1000,"scale":"log"}');
	// A triangular distribution is linear, a normal one four deviations wide.
	const bio = example('biosphere.json');
	assert(json(ai.defaultRange(bio, { kind: 'value', block: 'wellVolume' })) === '{"min":3000,"max":8000,"scale":"linear"}');
	assert(json(ai.defaultRange(bio, { kind: 'value', block: 'rho' })) === '{"min":1180,"max":1820,"scale":"linear"}');
});

test('the inputs a run changes are those away from the model, once per thing, and none that cannot be set', () => {
	const raw = small();
	raw.app = {
		pages: [{
			components: [
				{ id: 'a', type: 'slider', target: { kind: 'value', block: 'k' }, min: 0.01, max: 1 },
				{ id: 'b', type: 'number', target: { kind: 'value', block: 'k' } },
				{ id: 'c', type: 'number', target: { kind: 'value', block: 'f', index: { N: 'a' } } },
				{ id: 'd', type: 'number', target: { kind: 'value', block: 'gone' } },
			],
		}],
	};
	const values = new Map([
		[ai.targetKey({ kind: 'value', block: 'k' }), 0.1],
		[ai.targetKey({ kind: 'value', block: 'f', index: { N: 'a' } }), 3],
		[ai.targetKey({ kind: 'value', block: 'gone' }), 7],
	]);
	const changes = ai.inputChanges(raw, values);
	assert(changes.length === 1 && changes[0].value === 0.1, json(changes));
	assert(ai.signature(changes) === '[["value:k[]",0.1]]', ai.signature(changes));
	assert(ai.signature([]) === '' && ai.signature([{ key: 'b', value: 1 }, { key: 'a', value: 2 }]) === ai.signature([{ key: 'a', value: 2 }, { key: 'b', value: 1 }]));
});

test('a control that cannot set its target does not stand in for one after it that can', () => {
	const raw = small();
	raw.app = {
		pages: [{
			components: [
				{ id: 'a', type: 'dropdown', target: { kind: 'end_time' } },
				{ id: 'b', type: 'slider', target: { kind: 'end_time' }, min: 10, max: 200 },
			],
		}],
	};
	const changes = ai.inputChanges(raw, new Map([['end_time', 50]]));
	assert(changes.length === 1 && changes[0].value === 50, json(changes));
});

test('the inputs are written into a copy: a value, one index, a factor on every index, a block off, the scenario and the end', () => {
	const raw = example('scenarios.json');
	const copy = structuredClone(raw);
	const out = ai.applyInputs(copy, [
		{ key: 'a', target: { kind: 'value', block: 'Flush' }, value: 0.3 },
		{ key: 'b', target: { kind: 'value', block: 'LakeVolume', index: { Climate: 'Drier' } }, value: 1e6 },
		{ key: 'c', target: { kind: 'value', block: 'Runoff', factor: true }, value: 2 },
		{ key: 'd', target: { kind: 'enabled', block: 'Outflow' }, value: false },
		{ key: 'e', target: { kind: 'scenario' }, value: 'Drier' },
		{ key: 'f', target: { kind: 'end_time' }, value: 50 },
		{ key: 'g', target: { kind: 'scenario' }, value: 'Nowhere' },
	]);
	assert(out.applied === 6 && out.skipped.length === 1 && out.skipped[0].key === 'g', json(out));
	const block = (n) => ed.findBlock(copy, n).block;
	assert(block('Flush').value === 0.3 && ed.effectiveValue(block('LakeVolume'), 'value', { Climate: 'Drier' }) === 1e6);
	for (const i of ['Present', 'Warmer and wetter', 'Drier']) {
		const was = Number(ed.effectiveValue(ed.findBlock(raw, 'Runoff').block, 'value', { Climate: i }));
		assert(ed.effectiveValue(block('Runoff'), 'value', { Climate: i }) === 2 * was, i);
	}
	assert(block('Outflow').enabled === false && copy.scenario === 'Drier' && copy.simulation.end_time === 50);
	// And the model itself is as it was.
	assert(json(raw) === json(example('scenarios.json')), 'the model was written to');
});

test('a run at the app’s controls is the run of the model edited to the same values, bit for bit', () => {
	const raw = example('biosphere.json');
	const changes = [
		{ key: 'a', target: { kind: 'value', block: 'geoTransit' }, value: 0.001 },
		{ key: 'b', target: { kind: 'value', block: 'Kd', factor: true }, value: 0.5 },
	];
	const viaApp = structuredClone(raw);
	ai.applyInputs(viaApp, changes);
	// The same edits, made the way the editor makes them.
	const edited = structuredClone(raw);
	ed.findBlock(edited, 'geoTransit').block.value = 0.001;
	for (const n of ['I-129', 'Cl-36', 'Tc-99', 'Se-79']) {
		const idx = { Radionuclides: n };
		ed.setEntryValue(edited, 'Kd', idx, 'value', Number(ed.effectiveValue(ed.findBlock(raw, 'Kd').block, 'value', idx)) * 0.5);
	}
	const series = (m) => {
		const r = run(new Project(structuredClone(m)).toJSON());
		return r.outputs().filter((o) => o.block === 'Dose').map((o) => Array.from(r.series(o)));
	};
	const [a, b, base] = [series(viaApp), series(edited), series(raw)];
	assert(json(a) === json(b), 'the app’s copy is not the edited model');
	assert(json(a) !== json(base), 'the controls changed nothing');
});

// --- what a result shows ------------------------------------------------------------------

test('a result names a block, and each index it leaves open', () => {
	const bio = example('biosphere.json');
	const outputs = outputsOfModel(bio);
	const labels = (ref) => ai.matchSeries(outputs, ref).map((i) => outputs[i].label).join();
	assert(labels({ block: 'Dose' }) === 'Dose [I-129],Dose [Cl-36],Dose [Tc-99],Dose [Se-79]', labels({ block: 'Dose' }));
	assert(labels({ block: 'Dose', index: { Radionuclides: 'Tc-99' } }) === 'Dose [Tc-99]');
	assert(labels({ block: 'Dose', index: { Radionuclides: 'U-238' } }) === '' && labels({ block: 'nope' }) === '');
	const dose = ai.seriesChoices(outputs).find((c) => c.block === 'Dose');
	assert(json(dose.dims) === '["Radionuclides"]' && dose.indices[0].length === 4 && dose.count === 4, json(dose));
	assert(/not among what the model reports/.test(ai.seriesProblem(outputs, { block: 'nope' })));
	assert(ai.seriesProblem(outputs, { block: 'Dose' }) === null);
});

test('the numbers read off a curve: at the ends, the peak and when, a time between two, the mean', () => {
	const t = [0, 1, 2, 4];
	const v = [1, 3, 2, NaN];
	assert(apps.statistic(t, v, 'initial') === 1 && apps.statistic(t, v, 'final') === 2);
	assert(apps.statistic(t, v, 'max') === 3 && apps.statistic(t, v, 'max_time') === 1 && apps.statistic(t, v, 'min') === 1);
	assert(apps.statistic(t, v, 'at', 1.5) === 2.5 && Number.isNaN(apps.statistic(t, v, 'at', 9)));
	// The mean of a straight line over its span is its midpoint, on any grid.
	const tt = [0, 1, 3, 10];
	assert(Math.abs(apps.statistic(tt, tt.map((x) => 2 * x + 1), 'mean') - 11) < 1e-12);
	assert(Number.isNaN(apps.statistic([], [], 'max')) && Number.isNaN(apps.statistic([0], [NaN], 'final')));
	assert(json(apps.tableTimes([0, 1, 2, 3, 4, 5, 6, 7, 8], 3)) === '[0,4,8]' && apps.tableTimes([1, 2], 10).length === 2);
	assert(apps.valueAt([0, 10], [0, 100], 2.5) === 25 && apps.valueAt([0, 10], [0, 100], 10) === 100);
});

test('a slider’s track and a dial’s needle, on either scale', async () => {
	const W = await import('../src/ui/appwidgets.js');
	const log = { min: 1e-6, max: 1e-2, scale: 'log', step: null };
	assert(W.sliderPosition(log, 1e-4) === 500 && W.sliderValue(log, 500) === 1e-4 && W.sliderValue(log, 1000) === 1e-2);
	assert(W.sliderPosition(log, 1) === 1000 && W.sliderPosition(log, 1e-9) === 0, 'not clamped to the ends');
	const lin = { min: 0, max: 100, scale: 'linear', step: 5 };
	assert(W.sliderSteps(lin) === 20 && W.sliderValue(lin, 7) === 35 && W.sliderPosition(lin, 35) === 7);
	// A log scale over nothing positive is drawn linear rather than not at all.
	assert(W.sliderScale({ min: 0, max: 1, scale: 'log' }) === 'linear' && W.sliderScale({ min: 1, max: 1 }) === null);
	assert(W.gaugeFraction(1e-4, 1e-6, 1e-2, 'log') === 0.5 && W.gaugeFraction(5, 0, 10, 'linear') === 0.5);
	assert(W.gaugeFraction(-1, 1e-6, 1e-2, 'log') === 0 && W.gaugeFraction(99, 0, 10) === 1);
	assert(W.fmtNumber(1.23456e-5) === '1.235e-5' && W.fmtNumber(0.5) === '0.5' && W.fmtNumber(NaN) === '—');
	assert(W.parseNumber(' 2e-3 ') === 0.002 && W.parseNumber('−1') === -1 && W.parseNumber('x') === null && W.parseNumber('') === null);
});

test('a dial’s fill runs along its track, however far round it goes', async () => {
	const W = await import('../src/ui/appwidgets.js');
	const { R, cx, cy } = W.GAUGE_DIAL;
	// The centre an SVG arc is drawn about, from its ends, its radius and its
	// two flags -- the conversion in the SVG specification (F.6.5), for a
	// circle with no rotation.
	const centreOf = (d) => {
		const m = /^M ([\d.-]+) ([\d.-]+) A ([\d.]+) ([\d.]+) 0 ([01]) ([01]) ([\d.-]+) ([\d.-]+)$/.exec(d);
		assert(m, `not an arc: ${d}`);
		const [x1, y1, r0, , large, sweep, x2, y2] = m.slice(1).map(Number);
		const hx = (x1 - x2) / 2;
		const hy = (y1 - y2) / 2;
		const r = Math.max(r0, Math.hypot(hx, hy));
		const k = (large !== sweep ? 1 : -1) * Math.sqrt(Math.max(0, (r * r - hx * hx - hy * hy) / (hx * hx + hy * hy)));
		return { x: k * hy + (x1 + x2) / 2, y: -k * hx + (y1 + y2) / 2, sweep, ends: [[x1, y1], [x2, y2]], chord: 2 * Math.hypot(hx, hy) };
	};
	for (let f = 0.001; f <= 1.0000001; f += 0.037) {
		for (const d of [W.gaugeArc(0, Math.min(1, f)), W.gaugeArc(Math.min(1, f) / 3, Math.min(1, f))]) {
			const c = centreOf(d);
			assert(c.sweep === 1, `${d} runs the other way`);
			for (const [x, y] of c.ends) assert(Math.abs(Math.hypot(x - cx, y - cy) - R) < 0.01, `${d} ends off the dial`);
			// Where the ends are far enough apart to say where the centre is:
			// two hundredths of rounding on a short chord moves it further.
			if (c.chord >= 10) {
				assert(Math.hypot(c.x - cx, c.y - cy) < 0.05, `${d} is drawn about ${c.x.toFixed(2)}, ${c.y.toFixed(2)}, not the dial’s centre`);
			}
		}
	}
	// And the track itself: the upper half, left to right.
	assert(W.gaugeArc(0, 1) === `M ${cx - R}.00 ${cy}.00 A ${R} ${R} 0 0 1 ${cx + R}.00 ${cy}.00`, W.gaugeArc(0, 1));
});

test('a Text part out of a file is drawn in bounded time, however it nests', async () => {
	const md = await import('../src/ui/markdown.js');
	const t0 = performance.now();
	for (const text of [
		'['.repeat(apps.TEXT_MAX), '[a](x'.repeat(apps.TEXT_MAX / 5), '<i>'.repeat(apps.TEXT_MAX / 3),
		`${'<i>'.repeat(600)}deep${'</i>'.repeat(600)}`, `${'**a'.repeat(1300)}`, `${'*a '.repeat(1300)}`,
	]) {
		const runs = md.inlineRuns(text);
		assert(Array.isArray(runs) && runs.map((r) => r.text).join('').length > 0, text.slice(0, 20));
	}
	assert(performance.now() - t0 < 500, `${(performance.now() - t0).toFixed(0)} ms`);
	// Past eight deep the tags are text, and what they hold is still there.
	const deep = md.inlineRuns(`${'<i>'.repeat(20)}x${'</i>'.repeat(20)}`);
	assert(deep.map((r) => r.text).join('').includes('x') && deep.some((r) => r.em), json(deep).slice(0, 200));
	// A Text part holds no more than a Text part may.
	const read = apps.readComponent({ type: 'text', text: 'a'.repeat(apps.TEXT_MAX + 50) });
	assert(read.text.length === apps.TEXT_MAX, String(read.text.length));
});

test('what keeps a part from working is said, part by part', () => {
	const raw = small();
	const outputs = outputsOfModel(raw);
	const p = (c) => ai.componentProblem(raw, apps.readComponent(c), outputs);
	assert(p({ type: 'slider', target: { kind: 'value', block: 'k' }, min: 0.1, max: 1 }) === null);
	assert(/range/.test(p({ type: 'slider', target: { kind: 'value', block: 'k' } })));
	assert(/above its lowest/.test(p({ type: 'slider', target: { kind: 'value', block: 'k' }, min: 2, max: 1 })));
	assert(/starts above zero/.test(p({ type: 'slider', target: { kind: 'value', block: 'k' }, min: 0, max: 1, scale: 'log' })));
	assert(/choices/.test(p({ type: 'dropdown', target: { kind: 'value', block: 'k' } })));
	assert(/Choose what it shows/.test(p({ type: 'chart' })) && p({ type: 'chart', series: [{ block: 'D' }] }) === null);
	assert(/time/.test(p({ type: 'value', series: [{ block: 'D' }], statistic: 'at' })));
	assert(p({ type: 'text' }) === null && p({ type: 'button' }) === null);
	// With no outputs to hand, a block of the model is enough.
	assert(ai.componentProblem(raw, apps.readComponent({ type: 'chart', series: [{ block: 'D' }] }), null) === null);
});

test('a first app from the model: a control per uncertain parameter, and a chart of what it is for', () => {
	const raw = example('biosphere.json');
	delete raw.app;
	const outputs = outputsOfModel(raw);
	const app = ai.starterApp(raw, outputs);
	const parts = app.pages[0].components;
	const sliders = parts.filter((c) => c.type === 'slider');
	assert(sliders.map((c) => ai.describeTarget(c.target)).join() === 'leachRate ×,geoTransit,soilLeach,Kd ×,wellVolume,wellTurnover',
		sliders.map((c) => ai.describeTarget(c.target)).join());
	assert(sliders[1].scale === 'log' && sliders[1].min === 2e-5 && sliders[1].max === 0.002, json(sliders[1]));
	const chart = parts.find((c) => c.type === 'chart');
	assert(json(chart.series) === '[{"block":"Dose"}]' && chart.x === 4, json(chart));
	for (const c of parts) assert(ai.componentProblem(raw, c, outputs) === null, `${c.id}: ${ai.componentProblem(raw, c, outputs)}`);
	// And it is an app as read: what the page stores is what it draws.
	assert(json(apps.readApp({ app })) === json(app));
	// A model with scenarios starts with the choice of one.
	const sc = ai.starterApp(example('scenarios.json'), null);
	assert(sc.pages[0].components[0].type === 'dropdown' && sc.pages[0].components[0].target.kind === 'scenario');
});

test('the bundled example’s app is stored as it is read, and every part of it works', () => {
	const raw = example('biosphere.json');
	assert(json(apps.readApp(raw)) === json(raw.app), 'reading the example’s app changes it');
	const outputs = outputsOfModel(raw);
	const all = apps.allComponents(apps.readApp(raw));
	assert(all.length >= 10 && apps.readApp(raw).pages.length === 2, String(all.length));
	for (const { component: c } of all) assert(ai.componentProblem(raw, c, outputs) === null, `${c.id}: ${ai.componentProblem(raw, c, outputs)}`);
});

// --- parts that hold parts ------------------------------------------------------------------

test('a panel holds parts of its own: put in, taken out, grown to fit, never inside itself', () => {
	const raw = small();
	const panel = apps.addComponent(raw, 0, 'panel', { props: { title: 'Inputs' } });
	const where = { page: 0, parent: panel, slot: 0 };
	const s1 = apps.addComponent(raw, where, 'slider', { props: { target: { kind: 'value', block: 'k' } } });
	const s2 = apps.addComponent(raw, where, 'number', { props: { target: { kind: 'value', block: 'k' } } });
	let app = apps.readApp(raw);
	const f = apps.findComponent(app, s2);
	assert(f.parent?.id === panel && f.depth === 1 && f.slot === 0 && f.page === 0, json({ parent: f.parent?.id, depth: f.depth }));
	// Stacked in the panel's grid, not the page's, and the panel as tall as a
	// row for its title and the rows of what it holds.
	const box = apps.findComponent(app, panel).component;
	assert(!apps.overlaps(box.components[0], box.components[1]), json(box.components));
	assert(box.h >= 1 + apps.rowsOf(box.components), `${box.h} rows for ${apps.rowsOf(box.components)}`);
	// A part made taller inside grows it, and what is under it on the page
	// moves down out of the way.
	const under = apps.addComponent(raw, 0, 'chart', { at: { x: 0, y: box.y + box.h }, props: { series: [{ block: 'D' }] } });
	apps.updateComponent(raw, s1, { h: 12 });
	app = apps.readApp(raw);
	const grown = apps.findComponent(app, panel).component;
	const moved = apps.findComponent(app, under).component;
	assert(grown.h >= 1 + 12, `the panel did not grow: ${grown.h}`);
	assert(moved.y >= grown.y + grown.h, `what was under the panel stayed under it: ${moved.y} < ${grown.y + grown.h}`);
	// A panel's contents are no setting of it: an update cannot empty it.
	apps.updateComponent(raw, panel, { title: 'Set', components: [] });
	app = apps.readApp(raw);
	assert(apps.findComponent(app, panel).component.components.length === 2 && apps.findComponent(app, panel).component.title === 'Set');
	// Taken out, a part is on the page, and inputs inside count as inputs.
	apps.moveComponent(raw, s2, 0);
	app = apps.readApp(raw);
	assert(apps.findComponent(app, s2).parent === null && apps.findComponent(app, s2).depth === 0);
	const values = new Map([[ai.targetKey({ kind: 'value', block: 'k' }), 0.1]]);
	assert(ai.inputChanges(raw, values).length === 1, 'an input inside a panel sets nothing');
	// Never into itself, nor into what is inside it.
	const inner = apps.addComponent(raw, where, 'panel');
	for (const into of [panel, inner]) {
		let refused = null;
		try { apps.moveComponent(raw, panel, { page: 0, parent: into, slot: 0 }); } catch (e) { refused = e.message; }
		assert(/inside itself/.test(refused ?? ''), `${into}: ${refused}`);
	}
	// Removed, it takes what it holds; duplicated, a copy of every part in it,
	// every one with an id of its own.
	const copy = apps.duplicateComponent(raw, panel);
	app = apps.readApp(raw);
	const ids = apps.allComponents(app).map((x) => x.component.id);
	assert(new Set(ids).size === ids.length && apps.findComponent(app, copy).component.components.length === 2, json(ids));
	apps.removeComponent(raw, panel);
	app = apps.readApp(raw);
	assert(!apps.findComponent(app, s1) && apps.findComponent(app, copy), 'a removed panel left its parts behind');
});

test('tabs: each a grid of its own, added, renamed, moved and deleted with what is on them, and one at least', () => {
	const raw = small();
	const t = apps.addComponent(raw, 0, 'tabs');
	assert(apps.readApp(raw).pages[0].components[0].tabs.length === 1, 'a set of tabs starts with one');
	assert(apps.addTab(raw, t, 'Detail') === 1 && apps.addTab(raw, t) === 2);
	const a = apps.addComponent(raw, { page: 0, parent: t, slot: 1 }, 'value', { props: { series: [{ block: 'D' }] } });
	const b = apps.addComponent(raw, { page: 0, parent: t, slot: 2 }, 'text', { props: { text: 'x' } });
	let set = apps.readApp(raw).pages[0].components[0];
	assert(json(set.tabs.map((x) => [x.name, x.components.map((c) => c.id)])) === json([['Tab 1', []], ['Detail', [a]], ['Tab 3', [b]]]), json(set.tabs));
	assert(apps.renameTab(raw, t, 2, '  Notes ') && !apps.renameTab(raw, t, 2, '   ') && !apps.renameTab(raw, t, 9, 'x'));
	assert(apps.moveTab(raw, t, 2, 0) && !apps.moveTab(raw, t, 0, 0) && !apps.moveTab(raw, t, 0, 5));
	set = apps.readApp(raw).pages[0].components[0];
	assert(json(set.tabs.map((x) => x.name)) === json(['Notes', 'Tab 1', 'Detail']), json(set.tabs.map((x) => x.name)));
	// A tab goes with what is on it; the last one stays.
	assert(apps.removeTab(raw, t, 2));
	assert(!apps.findComponent(apps.readApp(raw), a), 'a deleted tab left its part');
	assert(apps.removeTab(raw, t, 0) && !apps.removeTab(raw, t, 0), 'the last tab went');
	// As many as a set holds, and no more.
	for (let i = apps.readApp(raw).pages[0].components[0].tabs.length; i < apps.MAX_TABS; i++) apps.addTab(raw, t);
	let refused = null;
	try { apps.addTab(raw, t); } catch (e) { refused = e.message; }
	assert(/at most/.test(refused ?? ''), String(refused));
	// A tab is only of a set of tabs.
	const panel = apps.addComponent(raw, 0, 'panel');
	assert(apps.addTab(raw, panel) === -1 && !apps.renameTab(raw, panel, 0, 'x'));
});

test('containers go three deep, whether added, moved or read from a file', () => {
	const raw = small();
	const p1 = apps.addComponent(raw, 0, 'panel');
	const t2 = apps.addComponent(raw, { page: 0, parent: p1, slot: 0 }, 'tabs');
	const p3 = apps.addComponent(raw, { page: 0, parent: t2, slot: 0 }, 'panel');
	// A leaf in the third is fine; a container is not.
	apps.addComponent(raw, { page: 0, parent: p3, slot: 0 }, 'text', { props: { text: 'deep' } });
	let refused = null;
	try { apps.addComponent(raw, { page: 0, parent: p3, slot: 0 }, 'panel'); } catch (e) { refused = e.message; }
	assert(/3 deep/.test(refused ?? ''), String(refused));
	// Moved, a container counts what it holds: the tabs and the panel in them
	// are two levels, and into a panel on the page make three; the panel
	// holding both is three, and into another makes four.
	const other = apps.addComponent(raw, 0, 'panel');
	apps.moveComponent(raw, t2, { page: 0, parent: other, slot: 0 });
	assert(apps.findComponent(apps.readApp(raw), t2).parent.id === other);
	apps.moveComponent(raw, t2, { page: 0, parent: p1, slot: 0 });
	refused = null;
	try { apps.moveComponent(raw, p1, { page: 0, parent: other, slot: 0 }); } catch (e) { refused = e.message; }
	assert(/deeper/.test(refused ?? ''), String(refused));
	assert(apps.findComponent(apps.readApp(raw), p1).parent === null, 'a refused move moved it anyway');
	// A file nested ten deep is read three deep, and every walk over a file
	// stops at a depth, however deep it goes.
	let deep = { type: 'text', text: 'bottom' };
	for (let i = 0; i < 10; i++) deep = { type: i % 2 ? 'panel' : 'tabs', components: [deep], tabs: [{ name: 't', components: [deep] }] };
	const file = { ...small(), app: { pages: [{ components: [deep] }] } };
	const read = apps.readApp(file);
	assert(Math.max(...apps.allComponents(read).map((x) => x.depth)) <= apps.MAX_NEST, 'read deeper than containers go');
	assert(apps.countAppParts(file) > 0 && apps.countAppParts(file) < 2 ** 11, String(apps.countAppParts(file)));
	apps.retargetAppNames(file, () => null);
});

test('a file’s containers are read tidy: ids unique across the whole app, grids settled, each container tall enough', () => {
	const raw = small();
	raw.app = { pages: [{ components: [
		{ id: 'c1', type: 'panel', x: 0, y: 0, w: 6, h: 2, components: [
			{ id: 'c1', type: 'text', x: 0, y: 0, w: 6, h: 3, text: 'a' },
			{ id: 'c2', type: 'text', x: 0, y: 0, w: 6, h: 3, text: 'b' },
		] },
		{ id: 'c2', type: 'tabs', x: 0, y: 1, w: 6, h: 2, tabs: [{ name: 'One', components: [{ type: 'text', h: 8, text: 'c' }] }, 'not a tab'] },
	] }] };
	const app = apps.readApp(raw);
	const all = apps.allComponents(app);
	const ids = all.map((x) => x.component.id);
	assert(new Set(ids).size === ids.length && ids.every((id) => /^c\d+$/.test(id)), json(ids));
	const [panel, tabs] = app.pages[0].components;
	assert(!apps.overlaps(panel.components[0], panel.components[1]), 'a panel’s parts overlap');
	assert(panel.h >= 1 + 6 && tabs.h >= 1 + 8, `${panel.h} and ${tabs.h} rows`);
	assert(!apps.overlaps(panel, tabs), 'the page’s containers overlap once grown');
	assert(tabs.tabs.length === 1 && tabs.tabs[0].name === 'One', json(tabs.tabs));
	// And a reading reads as itself.
	assert(json(apps.readApp({ app })) === json(app), 'reading the tidy app changes it');
});

test('a rename follows into a part inside a tab inside a panel', () => {
	const raw = small();
	const p = apps.addComponent(raw, 0, 'panel');
	const t = apps.addComponent(raw, { page: 0, parent: p, slot: 0 }, 'tabs');
	const s = apps.addComponent(raw, { page: 0, parent: t, slot: 0 }, 'slider', { props: { target: { kind: 'value', block: 'f', index: { N: 'a' } } } });
	const c = apps.addComponent(raw, { page: 0, parent: p, slot: 0 }, 'chart', { props: { series: [{ block: 'D' }] } });
	ed.renameBlock(raw, 'f', 'g');
	ed.renameBlock(raw, 'D', 'Dose');
	ed.renameIndex(raw, 'N', 'a', 'alpha');
	const app = apps.readApp(raw);
	assert(json(apps.findComponent(app, s).component.target) === json({ kind: 'value', block: 'g', index: { N: 'alpha' } }),
		json(apps.findComponent(app, s).component.target));
	assert(apps.findComponent(app, c).component.series[0].block === 'Dose', json(apps.findComponent(app, c).component.series));
	assert(apps.countAppParts(raw) === 4, String(apps.countAppParts(raw)));
});

// --- pictures ---------------------------------------------------------------------------------

test('a picture is a data address of a picture type and nothing else', () => {
	const png = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==';
	assert(apps.readImageSrc(png) === png);
	for (const type of ['jpeg', 'gif', 'webp', 'svg+xml']) assert(apps.readImageSrc(`data:image/${type};base64,AAAA`), type);
	for (const bad of [
		'javascript:alert(1)', 'data:text/html;base64,PHNjcmlwdD4=', 'https://example.org/a.png', '/a.png',
		'data:image/png,rawtext', 'data:image/png;base64,AAAA BBBB', 'data:image/png;charset=utf-8;base64,AAAA',
		'data:image/svg+xml;utf8,<svg onload=alert(1)>', 'DATA:image/png;base64,AAAA', `data:image/png;base64,${'A'.repeat(apps.IMAGE_MAX)}`,
		42, null, { src: png },
	]) assert(apps.readImageSrc(bad) === '', `took ${String(bad).slice(0, 60)}`);
	// Read through a file, a picture it will not take is no picture, and says so.
	const raw = small();
	raw.app = { pages: [{ components: [{ type: 'image', src: 'https://example.org/a.png', alt: 'A map', fit: 'fill' }] }] };
	const c = apps.readApp(raw).pages[0].components[0];
	assert(c.src === '' && c.alt === 'A map' && c.fit === 'contain', json(c));
	assert(ai.componentProblem(raw, c, []) === 'Choose a picture for it.', ai.componentProblem(raw, c, []));
	assert(ai.componentProblem(raw, { ...c, src: png }, []) === null);
	// The page lets a data address be drawn, and nothing it would fetch.
	const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
	assert(/img-src 'self' data: blob:;/.test(html), 'the page’s policy does not draw a data address');
});

// --- the spread ---------------------------------------------------------------------------------

test('a distribution scaled by a factor: every quantile is the factor times the quantile', async () => {
	const pdf = await import('../src/domain/pdf.js');
	const specs = [
		{ kind: 'unif', params: { min: 2, max: 5 } },
		{ kind: 'triang', params: { min: 1, max: 9, mode: 3 } },
		{ kind: 'dtriang', params: { min: 1, max: 9, mode: 7 } },
		{ kind: 'norm', params: { mean: 10, sd: 2 } },
		{ kind: 'logu', params: { min: 1e-4, max: 1e-2 } },
		{ kind: 'logt', params: { min: 1e-4, max: 1e-2, mode: 1e-3 } },
		{ kind: 'logdt', params: { min: 1e-4, max: 1e-2, mode: 3e-3 } },
		{ kind: 'Logn4', params: { gm: 0.3, gsd: 2.5 } },
		{ kind: 'logn', params: { mean: 5, sd: 3 } },
		{ kind: 'logn5', params: { p1: 0.05, x1: 0.2, p2: 0.95, x2: 7 } },
	];
	for (const spec of specs) {
		for (const c of [2.5, 0.1]) {
			const scaled = ai.scalePdf(spec, c);
			assert(scaled && scaled.kind === spec.kind, `${spec.kind} was not scaled`);
			for (const u of [0.01, 0.1, 0.3, 0.5, 0.7, 0.9, 0.99]) {
				const want = c * pdf.quantile(spec, u);
				const got = pdf.quantile(scaled, u);
				assert(Math.abs(got - want) <= 1e-12 * Math.abs(want), `${spec.kind} × ${c} at ${u}: ${got} against ${want}`);
			}
		}
	}
	// A truncation at a value is scaled with it; at a probability, not.
	const cut = ai.scalePdf({ kind: 'norm', params: { mean: 1, sd: 1 }, trmin: 0.5, trmax: 3, pmin: 0.1 }, 2);
	assert(cut.trmin === 1 && cut.trmax === 6 && cut.pmin === 0.1, json(cut));
	// A sample of values is scaled value by value; a factor not above zero, or a kind it does not know, is no distribution.
	assert(json(ai.scalePdf({ kind: 'pg', values: [1, 2, 4] }, 3).values) === json([3, 6, 12]));
	assert(ai.scalePdf(specs[0], 0) === null && ai.scalePdf(specs[0], -1) === null && ai.scalePdf(specs[0], NaN) === null);
	assert(ai.scalePdf({ kind: 'nonsense', params: {} }, 2) === null);
});

test('the model a spread is sampled on: a moved control held, a factor scaling the distribution, the rest sampled', async () => {
	const { samplingPlan, slotName } = await import('../src/sim/probabilistic.js');
	const raw = example('biosphere.json');
	const app = apps.readApp(raw);
	const slider = (block) => apps.allComponents(app).find((x) => x.component.target?.block === block).component.target;
	const values = new Map([
		[ai.targetKey(slider('geoTransit')), 5e-4],
		[ai.targetKey(slider('Kd')), 2],
		[ai.targetKey(slider('soilLeach')), ai.modelValue(raw, slider('soilLeach'))],
	]);
	const changes = ai.inputChanges(raw, values);
	assert(changes.length === 2, `a control at the model’s value is a change: ${json(changes)}`);
	const before = new Set(samplingPlan(new Project(structuredClone(raw))).map(slotName));
	const copy = ai.sampleModel(raw, changes);
	const plan = samplingPlan(new Project(structuredClone(copy)));
	const after = new Set(plan.map(slotName));
	// Held where it was moved to, and not drawn.
	assert(before.has('geoTransit') && !after.has('geoTransit'), 'a moved slider’s parameter is still sampled');
	assert(copy.parameters.find((p) => p.name === 'geoTransit').value === 5e-4, 'not held at the slider’s value');
	// Still at the model's value, still drawn -- and every index of a factor too.
	assert(after.has('soilLeach'), 'a control at the model’s value holds its parameter');
	for (const nuclide of ['I-129', 'Cl-36', 'Tc-99', 'Se-79']) assert(after.has(`Kd[${nuclide}]`), `Kd[${nuclide}] is not sampled`);
	// Scaled by the factor, each index from its own.
	const kd = (m, nuclide) => ed.effectiveValue(m.parameters.find((p) => p.name === 'Kd'), 'pdf', { Radionuclides: nuclide });
	for (const nuclide of ['I-129', 'Se-79']) {
		const was = kd(raw, nuclide).params;
		const now = kd(copy, nuclide).params;
		assert(now.min === 2 * was.min && now.max === 2 * was.max && now.mode === 2 * was.mode, `${nuclide}: ${json(now)} from ${json(was)}`);
	}
	// At the percentiles the parts read, whatever the model's own; and the
	// model the app is on is not touched.
	assert(json(copy.simulation.percentiles) === json(apps.APP_PERCENTILES));
	assert(json(raw) === json(example('biosphere.json')), 'sampling changed the model');
	// What it keeps is what the app shows.
	assert(json(ai.appOutputBlocks(raw).sort()) === json(['Dose', 'Geosphere', 'Repository', 'Soil', 'Well']), json(ai.appOutputBlocks(raw)));
	// And the example's app reads the spread.
	assert(ai.usesSpread(app) && !ai.usesSpread(apps.readApp({ app: { pages: [{ components: [{ type: 'chart' }] }] } })));
});

// --- a model as a link -----------------------------------------------------------------------

test('a model as a link: the whole of it after #m=, read back as it went, and a link that is not one said so', async () => {
	const L = await import('../src/io/applink.js');
	const raw = example('biosphere.json');
	const payload = await L.encodeModel(raw);
	assert(/^[A-Za-z0-9_-]+$/.test(payload), 'the text is not what an address carries');
	assert(json(L.decodeModel(payload)) === json(raw), 'the model did not come back as it went');
	const link = L.linkFor('https://example.org/kompartment.html?theme=dark&model=decay-chain.json#old', payload);
	assert(link === `https://example.org/kompartment.html?app#m=${payload}`, link.slice(0, 120));
	assert(L.linkFor('https://example.org/k/', payload, { app: false }) === `https://example.org/k/#m=${payload}`);
	assert(L.modelInHash(new URL(link).hash) === payload && L.modelInHash('#x=1&m=abc') === 'abc' && L.modelInHash('#nothing') === null);
	// The example's app goes in about three thousand characters, which any
	// program a link is sent through will take.
	assert(link.length < 4000 && L.linkAdvice(link.length).tone === 'info', String(link.length));
	assert(L.linkAdvice(L.LINK_LONG + 1).tone === 'warn' && L.linkAdvice(L.LINK_MAX + 1).ok === false);
	// Every byte back, however it was written.
	for (let n = 0; n < 9; n++) {
		const bytes = Uint8Array.from({ length: n * 37 }, (_, i) => (i * 131 + n) & 255);
		assert(json([...L.fromBase64Url(L.toBase64Url(bytes))]) === json([...bytes]), `${n * 37} bytes`);
	}
	// A link cut short, changed, or not one at all: an error that says so,
	// never a model half read.
	for (const bad of ['', '!!!', 'abc$', payload.slice(0, payload.length >> 1), `A${payload}`]) {
		let said = null;
		try { L.decodeModel(bad); } catch (e) { said = e.message; }
		assert(said && /link/.test(said), `${bad.slice(0, 20)}: ${said}`);
	}
	const squeeze = async (text) => L.encodeModel(JSON.parse(text));
	for (const text of ['[1,2]', '"model"', 'null']) {
		let said = null;
		try { L.decodeModel(await squeeze(text)); } catch (e) { said = e.message; }
		assert(/not a model file/.test(said ?? ''), `${text}: ${said}`);
	}
	// What a link may expand to is bounded, as every file this tool reads is.
	const { inflateRaw } = await import('../src/io/inflate.js');
	const zeros = new Uint8Array(1 << 20);
	const packed = new Uint8Array(await new Response(new Blob([zeros]).stream().pipeThrough(new CompressionStream('deflate'))).arrayBuffer()).subarray(2, -4);
	let bounded = null;
	try { inflateRaw(packed, 0, 1000); } catch (e) { bounded = e.message; }
	assert(bounded, 'a link expanding past its bound was read');
	const src = readFileSync(new URL('../src/io/applink.js', import.meta.url), 'utf8');
	assert(/inflateRaw\(bytes, 0, INFLATE_LIMIT\)/.test(src), 'the link is read without a bound');
});

test('a link opens its model before anything else, keeps the draft it would replace, and the site page hands it through', () => {
	const app = readFileSync(new URL('../src/ui/app.js', import.meta.url), 'utf8');
	const boot = app.slice(app.indexOf('export function boot()'));
	const linked = boot.indexOf('const linked = modelInHash(location.hash);');
	assert(linked > 0 && linked < boot.indexOf("if (wanted === 'draft') {") && linked < boot.indexOf('loadExample(start)'),
		'a link in the address is not what opens');
	assert(/setModel\(model, \{ label: [^}]*, link: true \}\);\n\t\t\topenApp\(\);\n\t\t\tofferDraft\(held\);/.test(boot), 'a link’s model does not open as its app, or hides the draft');
	// Not written over the draft until it is edited; an edit takes it out of the address.
	assert(/if \(!source\?\.link\) draftKeeper\.note\(state\.raw, draftMeta\(\)\);/.test(app), 'a link’s model is kept as the draft');
	assert(/draftKeeper\.note\(state\.raw, draftMeta\(\)\);\n\tleaveLinkAddress\(\);/.test(app), 'an edit leaves the model in the address');
	// The dialog has its (i), and a Guide heading behind it.
	assert(/info: dialogInfo\('app-link'\),/.test(app), 'the share dialog has no (i)');
	const html = readFileSync(new URL('../../kompartment.html', import.meta.url), 'utf8');
	assert(/url\.hash = location\.hash;\n\s+return url;/.test(html), 'the site page drops the model in its address');
});

test('the site page’s full window puts its header and footer away in place, asked by the frame’s own button', () => {
	const html = readFileSync(new URL('../../kompartment.html', import.meta.url), 'utf8');
	// As it was left, from the first paint -- and in the frame's address, so
	// the frame starts without the room kept for them.
	assert(/if \(localStorage\.getItem\('kompartment\.full'\) === '1'\) document\.documentElement\.classList\.add\('komp-full'\);/.test(html), 'not from the first paint');
	assert(/:root\.komp-full \{ --header-height: 0px; --footer-height: 0px; \}/.test(html), 'the room is not given back');
	assert(/if \(isFull\(\)\) url\.searchParams\.set\('full', '1'\);/.test(html), 'the frame does not start in the full window');
	// In place: the page answers the frame's request and tells it, and nothing
	// reloads the frame -- the model in there is the reader's unsaved work.
	const setFull = html.slice(html.indexOf('function setFull('), html.indexOf("window.addEventListener('message'"));
	assert(/postMessage\(\{ type: 'kvot:full', full: on \}, location\.origin\)/.test(setFull), 'the frame is not told');
	assert(!/\.src\b|location\.(href|assign|replace)/.test(setFull), 'the full window reloads the frame or leaves the page');
	assert(/localStorage\.setItem\('kompartment\.full'/.test(setFull), 'the choice is not kept');
	assert(!/komp-open|model', 'draft'/.test(html), 'the old link to the bare page is still there');
	// Only from the frame, same-origin, and only the two requests.
	assert(/e\.origin !== location\.origin \|\| e\.source !== frame\.contentWindow/.test(html), 'the page listens to any window');
	assert(/m\.type === 'kvot:full' && typeof m\.full === 'boolean'/.test(html) && /m\.type === 'kvot:toggle-theme'\) KVOT\.toggleTheme\(\)/.test(html), 'the page takes other requests');
	// The frame: the attribute from the page's answer only, as a boolean, and
	// from `?full=1` before the first paint.
	const chrome = readFileSync(new URL('../src/ui/sitechrome.js', import.meta.url), 'utf8');
	assert(/ev\.origin !== location\.origin \|\| ev\.source !== window\.parent/.test(chrome) && /typeof ev\.data\.full !== 'boolean'/.test(chrome), 'the frame listens to any window');
	assert(/root\(\)\.toggleAttribute\('data-chrome-full', ev\.data\.full\)/.test(chrome), 'the answer does not set the attribute');
	const start = readFileSync(new URL('../src/ui/start.js', import.meta.url), 'utf8');
	assert(/params\.get\('full'\) === '1'\) document\.documentElement\.setAttribute\('data-chrome-full', ''\)/.test(start), 'not before the first paint');
	// The room goes in the full window; the mark and the switch show only there.
	const css = readFileSync(new URL('../css/theme-kvotab.css', import.meta.url), 'utf8');
	assert(/:root\[data-chrome="kvotab"\]:not\(\[data-chrome-full\]\) body \{/.test(css), 'the room is kept in the full window');
	assert(/:root\[data-chrome="kvotab"\]:not\(\[data-chrome-full\]\) \.kvot-home,\n:root\[data-chrome="kvotab"\]:not\(\[data-chrome-full\]\) \.kvot-theme \{ display: none; \}/.test(css), 'the mark and the switch show outside the full window');
	// There the kvot mark takes the place of the tool's own rather than sitting beside it.
	assert(/\n:root\[data-chrome="kvotab"\]\[data-chrome-full\] \.brand-mark \{ display: none; \}/.test(css), 'the tool’s mark beside the kvot mark in the full window');
	// The home page in a new tab, as the footer's kvotab.se: the model lives in this page.
	assert(/href: '\.\.\/index\.html', target: '_blank', rel: 'noopener'/.test(chrome), 'the mark navigates away from the model');
	// Both bars: the editor's and the running app's.
	const app = readFileSync(new URL('../src/ui/app.js', import.meta.url), 'utf8');
	const run = readFileSync(new URL('../src/ui/apprun.js', import.meta.url), 'utf8');
	assert(/bar\.prepend\(sitechrome\.homeLink\(\)\);\n\t\tbar\.append\(\.\.\.sitechrome\.endButtons\(\)\);\n\t\tsitechrome\.listen\(\);/.test(app), 'the editor’s bar has no full window');
	assert(/homeLink\(\),\n/.test(run) && /edit, \.\.\.endButtons\(\)\);/.test(run), 'the running app’s bar has no full window');
});

// --- how an app looks -------------------------------------------------------------------------

test('every style an app can wear is in the stylesheet, light or dark as it says, with the tokens the parts read', () => {
	const css = readFileSync(new URL('../css/app.css', import.meta.url), 'utf8');
	const looks = css.slice(css.indexOf('/* --- how an app looks'));
	const blocks = new Map([...looks.matchAll(/\n\[data-app-theme="([a-z-]+)"\] \{\n\tcolor-scheme: (light|dark);([^}]*)\}/g)].map((m) => [m[1], { mode: m[2], body: m[3] }]));
	const ids = apps.THEMES.map((t) => t.id);
	assert(apps.THEMES[0].id === 'standard' && !blocks.has('standard'), 'the standard look is not the page’s own');
	for (const t of apps.THEMES.slice(1)) {
		const b = blocks.get(t.id);
		assert(b, `${t.id} has no style`);
		assert(b.mode === t.mode, `${t.id} is ${b.mode} in the stylesheet and ${t.mode} in the list`);
		for (const token of ['--surface-0', '--surface-1', '--surface-2', '--surface-sunken', '--border', '--border-strong',
			'--text-primary', '--text-secondary', '--text-muted', '--grid', '--axis', '--accent', '--accent-ink',
			'--accent-hover', '--danger', '--warn', '--radius', '--app-font']) {
			assert(new RegExp(`\\n\\t${token}: `).test(b.body), `${t.id} does not set ${token}`);
		}
		const series = [...b.body.matchAll(/--series-(\d): (#[0-9a-f]{6});/g)];
		assert(series.length === 8 && new Set(series.map((m) => m[2])).size === 8, `${t.id}: ${series.length} series colours`);
	}
	for (const id of blocks.keys()) assert(ids.includes(id), `${id} is styled and not in the list`);
	// A style is read and written like any other setting, and one it does not know is the standard one.
	const raw = small();
	apps.addComponent(raw, 0, 'text', { props: { text: 'x' } });
	apps.setAppSettings(raw, { theme: 'terminal' });
	assert(apps.readApp(raw).theme === 'terminal');
	assert(apps.readApp({ app: { theme: 'comic-sans' } }).theme === 'standard');
	// Worn by the running app and the designer's page, and by nothing else.
	const d = readFileSync(new URL('../src/ui/appdesigner.js', import.meta.url), 'utf8');
	const r = readFileSync(new URL('../src/ui/apprun.js', import.meta.url), 'utf8');
	assert(/wearTheme\(box, app\);/.test(d) && /wearTheme\(host, app\);/.test(r), 'a style is not worn where the app is drawn');
});

// --- the rest of the tool --------------------------------------------------------------------

test('an app is no number of the model: not in what a run depends on, and a line in the export report', async () => {
	const raw = small();
	const before = ed.integrationFingerprint(new Project(structuredClone(raw)));
	apps.addComponent(raw, 0, 'chart', { props: { series: [{ block: 'D' }] } });
	assert(ed.integrationFingerprint(new Project(structuredClone(raw))) === before, 'laying out an app changed the fingerprint');
	const { exportEco } = await import('../src/io/ecoexport.js');
	const { report } = await exportEco(raw);
	assert(report.warnings.some((w) => /The app built on the model .* not written \(1 part\)/.test(w)), json(report.warnings));
	// The version report names it as the rest of the file's other keys.
	const V = await import('../src/domain/versions.js');
	const diff = V.compareModels(small(), raw);
	assert(!diff.same && diff.other.some((o) => o.field === 'app'), json(diff.other));
});

test('the tab, its panel, and the running app’s surface inside the grid the chrome insets', () => {
	const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
	assert(/<button class="tab" role="tab" data-tab="app"/.test(html) && /<div class="panel" id="panel-app" role="tabpanel"><\/div>/.test(html));
	const inApp = html.slice(html.indexOf('<div id="app">'), html.indexOf('<div id="boot-problem"'));
	assert(/<section id="app-run" class="app-run" hidden/.test(inApp), 'the running app is not inside #app');
	const css = readFileSync(new URL('../css/app.css', import.meta.url), 'utf8');
	assert(/#app\.is-app-run > header,\n#app\.is-app-run > main \{ display: none; \}/.test(css), 'the editor shows under the app');
	// Its notices do not: the footer stays, as a row of no height they rise from.
	assert(/#app\.is-app-run > footer > :not\(#flash\) \{ display: none; \}/.test(css), 'the app hides its notices');
	// ROW and GAP in the designer are the grid's own two numbers.
	const d = readFileSync(new URL('../src/ui/appdesigner.js', import.meta.url), 'utf8');
	const row = /export const ROW = (\d+);/.exec(d)?.[1];
	const gap = /export const GAP = (\d+);/.exec(d)?.[1];
	assert(new RegExp(`--app-row: ${row}px;\\n\\t--app-gap: ${gap}px;`).test(css), `ROW ${row} / GAP ${gap} differ from the CSS`);
});

test('the running app\u2019s runs: owed rather than dropped, its own Stop, and a preview only for a run that starts', () => {
	const app = readFileSync(new URL('../src/ui/app.js', import.meta.url), 'utf8');
	const body = (name) => new RegExp(`function ${name}\\([^)]*\\) \\{([\\s\\S]*?)\\n\\}`).exec(app)?.[1] ?? '';
	// Opened while another run is going, the app's own run is queued behind it.
	assert(/if \(!appResultsFit\(\) && apps\.readApp\(state\.raw\)\?\.run !== 'button'\) runApp\(\);\n\telse followAppRun\(\);\n\treturn true;/.test(body('enterAppRun')),
		'the app\u2019s run is dropped when another is going');
	// Left, it owes nothing: a run it still owed would start ahead of an edit's.
	const leave = body('leaveAppRun');
	assert(/appRunWanted = false;/.test(leave) && /appSampleWanted = false;/.test(leave)
		&& /clearTimeout\(appRunTimer\);/.test(leave), 'leaving the app keeps its owed run');
	// Its spread, asked for during a run, is sampled once that run is over --
	// after the app's own run, which it is drawn under.
	const running = body('setRunning');
	assert(running.indexOf('if (appSampleWanted) {') > running.indexOf('if (appRunWanted) {'),
		'a spread asked for during a run is dropped, or sampled ahead of the run it is drawn under');
	assert(/if \(state\.running\) \{ appSampleWanted = true; paintAppStatus\(\); return; \}/.test(body('runAppSample')),
		'a spread asked for during a run is not owed');
	// Its Stop stops the run and leaves the editor's auto-run as it was.
	assert(/stop: \(\) => cancelSimulation\(\{ keepAutoRun: true \}\),/.test(app)
		&& /const wasAuto = state\.autoRun && !keepAutoRun;/.test(body('cancelSimulation')), 'the app\u2019s Stop turns auto-run off');
	// Its bar moves with the run.
	assert(/^\tpaintAppStatus\(\);/m.test(body('paintProgress')), 'the app\u2019s bar does not move');
	// And what a run is at is set once it is going, not before it is refused.
	const run = body('runSimulation');
	assert(run.indexOf('if (opts.app) state.preview = opts.preview ?? null;') > run.indexOf('new Project(structuredClone(raw))'),
		'a refused run of the app leaves its preview behind');
	assert(!/state\.preview = \{ from: 'app'/.test(body('runApp')), 'the app sets its preview before the run starts');
});

test('every (i) of the App designer has something to say, and its link lands on a Guide heading', async () => {
	const { appTopic, APP_TOPICS } = await import('../src/ui/appinfo.js');
	const { parseMarkdown, slug } = await import('../src/ui/markdown.js');
	const guide = readFileSync(new URL('../GUIDE.md', import.meta.url), 'utf8');
	const ids = new Set(parseMarkdown(guide).filter((b) => b.type === 'heading').map((b) => b.id));
	for (const key of APP_TOPICS) {
		const t = appTopic(key);
		assert(t && t.title && t.lead, `${key} has nothing to say`);
		assert(t.more && ids.has(slug(t.more)), `${key}: “Read more” names ${json(t.more)}, which is no heading in the Guide`);
		const strings = [t.title, ...[t.lead].flat(), ...(t.sections ?? []).flatMap((s) => [s.heading, ...[s.text].flat(), ...(s.list ?? []), ...(s.choices ?? []).flat()])]
			.filter((x) => typeof x === 'string');
		for (const x of strings) {
			assert((x.match(/\*\*/g) ?? []).length % 2 === 0, `${key}: an unpaired ** in ${x}`);
			assert((x.match(/`/g) ?? []).length % 2 === 0, `${key}: an unpaired backtick in ${x}`);
		}
	}
	assert(appTopic('nonsense') === null && appTopic('part:nonsense') === null);
	// Every (i) the designer draws names a topic there is.
	const src = readFileSync(new URL('../src/ui/appdesigner.js', import.meta.url), 'utf8');
	for (const m of src.matchAll(/info\('([a-z:]+)'\)|heading\([^,]+, '([a-z:]+)'\)/g)) {
		const key = m[1] ?? m[2];
		assert(APP_TOPICS.includes(key), `the designer draws an (i) for ${key}, which has no topic`);
	}
});
