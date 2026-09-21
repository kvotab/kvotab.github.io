/**
 * Importing blocks from another model file.
 *
 * The room the decisions in ../domain/import.js are made in. Two panes: what
 * the file holds on the left, and what taking it would mean on the right --
 * which is the half that matters, and the reason this is a dialog rather than
 * a file picker. Ticking a block in a 3,000-block model is easy; knowing that
 * it drags four parameters with it, that its nuclide dimension has three
 * indices this model has never heard of, and that eleven per-index values will
 * be dropped unless you say otherwise, is not. So the right pane is written
 * before the import happens and says all of it, and every line of it is a
 * choice rather than a warning.
 *
 * Nothing is written to the model being imported into until Import is pressed.
 * The survey is worked out again on every tick, which is cheap enough to do
 * that way: the expensive half -- the reference graph of the file being read
 * from -- is worked out once and kept.
 */

import * as ed from '../domain/edit.js';
import * as imp from '../domain/import.js';
import { Project } from '../domain/project.js';
import { buildSystem } from '../sim/builder.js';
import { openModal, closeModal } from './modal.js';
import { blockIcon } from './icons.js';
import { parentOf, isWithin } from '../domain/systems.js';

/**
 * The same node builder the rest of the interface uses, with one difference:
 * a hyphenated key is set as an *attribute*.
 *
 * `Object.assign(el, {'aria-label': x})` lands an expando property on the
 * element and nothing at all in the DOM -- the label is simply not there, and
 * nothing says so. Found here by asking the browser for one that had just been
 * written. The other copies of this helper have the same hole; this one is the
 * one with labels in it.
 */
const el = (tag, props = {}, ...kids) => {
	const n = document.createElement(tag);
	for (const [k, v] of Object.entries(props)) {
		if (!k.includes('-')) n[k] = v;
		else if (v != null) n.setAttribute(k, v);
	}
	for (const k of kids.flat()) {
		if (k == null || k === false) continue;
		n.append(k.nodeType ? k : document.createTextNode(String(k)));
	}
	return n;
};

/** How many rows a search draws before it says how many more there are. */
const ROWS = 400;

/** How many names a list in the right-hand pane spells out before counting. */
const NAMED = 12;

/** What the dialog is showing. Module state: the modal rebuilds its body. */
let ui = null;

/** The sub-systems holding something that is coming, for this draw. */
let partly = new Set();

/**
 * The block rows in the order they are drawn.
 *
 * What a shift-click reaches across. Ticking a hundred parameters one at a
 * time is not an interface, so a click sets an anchor and a shift-click takes
 * everything between the two -- the same gesture a file list has.
 */
let rowOrder = [];

/** The pending "would the result build" check. */
let checkTimer = null;

/**
 * How long a check may take before it stops running by itself.
 *
 * It is a whole import and a whole build, on a copy: cheap on an ordinary
 * model -- 85 ms for 94 blocks out of one small vault model into the biosphere
 * example -- and not on a model of a few thousand. A dialog that freezes for
 * two seconds every time a box is ticked is worse than one that does not
 * answer the question.
 */
const CHECK_BUDGET = 1200;

const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/**
 * Opens the importer.
 *
 * @param {object} opts
 * @param {object} opts.target the model being imported into
 * @param {object} opts.source the model read from the file
 * @param {string} opts.fileName what to call it
 * @param {(report: object) => void} opts.onImport given the applied report
 * @param {(message: string, tone?: string) => void} [opts.onStatus]
 * @param {() => void} [opts.onPickAnother]
 */
export function openImportDialog(opts) {
	const { target, source } = opts;
	ui = {
		// `source` is the *model being read from* -- not an inflow, and not a
		// source term. A sweep that renamed the block kind took this field's
		// name with it and left six reads of a field nothing sets, so every
		// block import threw before the dialog could draw. The fields here
		// come from `...opts`, which is why no test caught it; one does now.
		...opts,
		// Names of blocks, and paths of whole sub-systems.
		picked: new Set(),
		filter: { query: '', kinds: new Set() },
		open: new Set(['']),
		bringNeeded: true,
		choices: {},
		// null is "wherever they were" -- the sub-systems they came from, made
		// in this model if it has none of that name.
		into: null,
		survey: null,
		error: null,
	};
	// The whole file is offered ticked when it is small enough that taking all
	// of it is plainly the point; a big one starts empty, because ticking 3,000
	// blocks is not a decision anyone makes by accident.
	const all = ed.allBlocks(source).map((b) => ed.qualifiedName(b));
	if (all.length && all.length <= 12) for (const n of all) ui.picked.add(n);

	openModal({
		wide: true,
		title: () => 'Import blocks',
		subtitle: () => `${ui.fileName} · ${plural(all.length, 'block')}`
			+ `${ed.systems(source).length
				? ` in ${plural(ed.systems(source).length, 'sub-system')}` : ''}`,
		build,
		onClose: () => { ui = null; },
	});
	restate();
}

/** Works the survey out again, then redraws. Called after every change. */
function restate() {
	const names = [...ui.picked];
	ui.error = null;
	try {
		ui.survey = names.length
			? imp.surveyImport(ui.target, ui.source, names, { bringNeeded: ui.bringNeeded })
			: null;
	} catch (e) {
		ui.survey = null;
		ui.error = e.message;
	}
	// Answers are kept across a change of selection where they still apply: a
	// list that is still involved keeps what was said about it, and one that
	// is no longer is forgotten rather than quietly applied later.
	const fresh = ui.survey ? imp.defaultChoices(ui.survey) : {};
	const kept = {};
	for (const [name, def] of Object.entries(fresh)) {
		const was = ui.choices[name];
		kept[name] = was && validChoice(ui.survey, name, was) ? was : def;
	}
	ui.choices = kept;
	changed();
}

/** A choice was made: ask again whether the result would build, and redraw. */
function changed() {
	// Armed first, so that the draw that follows shows the question being
	// asked rather than the answer to the question before it.
	scheduleCheck();
	redraw();
}

/**
 * Whether the model would still build once this import had been made.
 *
 * The question the dialog exists to answer, in the end: everything else on the
 * right-hand pane is a reason the answer might be no. It is not free, so it is
 * asked once the clicking stops rather than on every tick -- and it is asked
 * by actually doing the import on a copy and building it, because a rule
 * written here to predict the answer would be a second implementation of the
 * builder's dimension algebra, and the wrong one.
 */
function scheduleCheck() {
	clearTimeout(checkTimer);
	if (!ui) return;
	if (ui.checkCost > CHECK_BUDGET) return;
	ui.check = ui.survey?.count ? { pending: true } : null;
	checkTimer = setTimeout(runCheck, 400);
}

function runCheck() {
	if (!ui?.survey?.count) return;
	const started = Date.now();
	// A model that does not build as it stands cannot be broken by an import,
	// and saying it can would be worse than saying nothing. Asked once.
	if (ui.baseOk === undefined) {
		try {
			buildSystem(new Project(structuredClone(ui.target)));
			ui.baseOk = true;
		} catch { ui.baseOk = false; }
	}
	if (!ui.baseOk) {
		ui.check = { skipped: 'this model does not build as it stands' };
		redraw();
		return;
	}
	try {
		const copy = structuredClone(ui.target);
		imp.applyImport(copy, ui.source, ui.survey, ui.choices, { into: ui.into });
		buildSystem(new Project(structuredClone(copy)));
		ui.check = { ok: true };
	} catch (e) {
		ui.check = { ok: false, message: e.message };
	}
	ui.checkCost = Date.now() - started;
	redraw();
}

function validChoice(survey, name, choice) {
	const row = survey.lists.find((l) => l.name === name);
	if (!row) return false;
	if (choice.mode === 'drop') return true;
	if (choice.mode === 'add') return row.status === 'missing';
	return row.candidates.some((c) => c.name === choice.into);
}

function redraw() {
	// The modal rebuilds its body from `build`, which reads `ui`.
	const body = document.querySelector('.modal-body');
	if (!body) return;
	body.replaceChildren();
	build(body);
}

function build(body) {
	if (!ui) return;
	body.append(el('div', { className: 'imp' },
		el('div', { className: 'imp-panes' }, pickPane(), planPane()),
		footer()));
}

// --- the left pane: what the file holds -------------------------------------

function pickPane() {
	const pane = el('section', { className: 'imp-pane imp-pick' });

	const search = el('input', {
		type: 'search', className: 'search-input', value: ui.filter.query,
		placeholder: 'Find a block — try Kd, or *_out',
		spellcheck: false,
		title: 'Matches anywhere in the name. With * or ? it is a pattern over '
			+ 'the whole name.',
	});
	search.addEventListener('input', () => {
		ui.filter.query = search.value;
		redraw();
		// Redrawing takes the caret with it, and this is the one field typed
		// into continuously.
		const again = document.querySelector('.imp-pick .search-input');
		again?.focus();
		again?.setSelectionRange(again.value.length, again.value.length);
	});

	const kinds = el('div', { className: 'imp-kinds' });
	const present = new Map();
	for (const b of ed.allBlocks(ui.source)) {
		present.set(b.kind, (present.get(b.kind) ?? 0) + 1);
	}
	for (const [kind, n] of [...present].sort((a, b) => b[1] - a[1])) {
		const on = ui.filter.kinds.has(kind);
		const chip = el('button', {
			type: 'button',
			className: `chip${on ? ' is-on' : ''}`,
			title: `${plural(n, kind.replace(/_/g, ' '))} in the file`,
		}, `${kind.replace(/_/g, ' ')} ${n}`);
		chip.addEventListener('click', () => {
			if (on) ui.filter.kinds.delete(kind); else ui.filter.kinds.add(kind);
			redraw();
		});
		kinds.append(chip);
	}

	// Which sub-systems hold something that is coming, worked out once for the
	// whole draw: a row that asked the model directly turned one redraw into
	// a scan of every block for every row, which on the files this reads is
	// several million comparisons for one keystroke.
	partly = new Set();
	for (const b of ed.allBlocks(ui.source)) {
		const name = ed.qualifiedName(b);
		if (!taken(name)) continue;
		for (let p = parentOf(name); p; p = parentOf(p)) partly.add(p);
	}

	const root = ed.blockTree(ui.source, ui.filter);
	// Everything the filter leaves, whether or not there is room to draw it:
	// what All and None act on, so that narrowing to one kind and taking the
	// lot is two clicks rather than a hundred.
	const matching = namesIn(root);
	const shown = [];
	const tree = el('div', { className: 'imp-tree' });
	rowOrder = [];
	let cut = 0;
	const rows = (node, depth) => {
		for (const s of node.systems) {
			if (shown.length >= ROWS) { cut += s.deep; continue; }
			shown.push(systemRow(s, depth));
			if (ui.open.has(s.path) || filtering()) rows(s, depth + 1);
		}
		for (const b of node.blocks) {
			if (shown.length >= ROWS) { cut++; continue; }
			rowOrder.push(b.name);
			shown.push(blockRow(b, depth));
		}
	};
	rows(root, 0);
	tree.append(...shown);
	if (!shown.length) {
		tree.append(el('p', { className: 'hint' },
			filtering() ? 'No block in the file matches that.' : 'The file holds no blocks.'));
	}

	const chosen = ui.survey ? ui.survey.chosen.length : 0;
	const narrowed = filtering();
	pane.append(
		el('div', { className: 'imp-tools' },
			search,
			kinds,
			el('div', { className: 'imp-actions' },
				action(narrowed ? `All ${matching.length}` : 'All',
					narrowed
						? `Take the ${plural(matching.length, 'block')} the filter leaves`
						: 'Take everything in the file',
					() => { for (const n of matching) take(n, true); restate(); }),
				action('None',
					narrowed ? 'Leave those behind' : 'Start again',
					() => {
						// Unfiltered, None means none: that includes the
						// sub-systems taken whole, which hold no block name of
						// their own for the loop to find.
						if (narrowed) for (const n of matching) take(n, false);
						else ui.picked.clear();
						restate();
					}),
				el('span', { className: 'imp-chosen' },
					chosen ? `${plural(chosen, 'block')} chosen` : 'nothing chosen')),
			// Said rather than left to be discovered: it is the difference
			// between one click and a hundred, and nothing on the row shows it.
			rowOrder.length > 8
				? el('p', { className: 'imp-hint' },
					'Click a row, then shift-click another to take everything between.')
				: null),
		tree,
	);
	if (cut) {
		pane.append(el('p', { className: 'hint' },
			`${cut} more not listed — narrow the search to reach them.`));
	}
	return pane;
}

const filtering = () => !!String(ui.filter.query ?? '').trim() || ui.filter.kinds.size > 0;

function action(label, title, onClick) {
	const b = el('button', { type: 'button', className: 'ghost', title }, label);
	b.addEventListener('click', onClick);
	return b;
}

/** Whether a name is coming: ticked itself, or inside a ticked sub-system. */
function taken(name) {
	if (ui.picked.has(name)) return true;
	for (const p of ui.picked) if (p !== name && isWithin(name, p)) return true;
	return false;
}

/** Every block in a tree node and everything under it, in the drawn order. */
function namesIn(node) {
	const out = [];
	const walk = (n) => {
		for (const s of n.systems) walk(s);
		for (const b of n.blocks) out.push(b.name);
	};
	walk(node);
	return out;
}

/**
 * Takes a block, or leaves it.
 *
 * One that is inside a sub-system taken whole is already coming and its own
 * tick is disabled -- so a range, or an All, must not quietly take it back out
 * from under the sub-system that is carrying it.
 */
function take(name, on) {
	if (taken(name) && !ui.picked.has(name)) return;
	if (on) ui.picked.add(name); else ui.picked.delete(name);
}

/**
 * The whole row is the control.
 *
 * A row used to be a `<label>` around its checkbox, which is the tidy way to
 * build one and is wrong here: a shift-click on the *text* of a label is a
 * shift-click on text, so the browser extends a selection with it and the
 * label is never activated. Measured, not assumed -- the gesture worked on the
 * thirteen pixels of the box and nowhere else on the row, which is exactly the
 * aim nobody takes.
 *
 * So the row handles the click itself and the box is left out of the hit
 * testing (`pointer-events: none`, in the stylesheet, with `user-select: none`
 * beside it so a shift-click cannot smear a selection across the list). The
 * box stays a real checkbox, focusable and announced: Tab and Space still
 * reach it, and the click that Space produces bubbles up to here, where `on`
 * is worked out from the model rather than from the box so that both routes
 * agree.
 */
function rowGesture(row, box, inert, name, apply) {
	if (inert) return;
	// The state as drawn, read now rather than at the click: the keyboard's
	// Space flips the box itself before the click it produces is dispatched,
	// and the pointer -- which never reaches the box -- does not. Reading it
	// here is the one answer both routes agree on, and the row is redrawn
	// after every change, so it cannot go stale.
	const was = box.checked;
	row.addEventListener('click', (ev) => {
		const on = !was;
		const n = apply(on, ev);
		ui.anchor = name;
		if (n > 1) {
			ui.onStatus?.(`${on ? 'Taking' : 'Leaving'} ${plural(n, 'block')}.`, 'info');
		}
		restate();
	});
	// Space and Enter on the focused box: the click it produces is handled
	// above, so nothing else is needed -- but a plain Enter inside the dialog
	// must not reach the form and count as Import.
	box.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') ev.preventDefault(); });
}

/**
 * Everything between the last row clicked and this one takes its state.
 *
 * The order is the drawn one, so a run that crosses a sub-system heading takes
 * what is on the screen between the two rows -- which is what the gesture
 * looks like it is doing. An anchor that is no longer drawn, because the
 * filter has moved on, is no anchor: the click is then a plain one.
 */
function applyRange(from, to, on) {
	const run = rangeOf(rowOrder, from, to);
	if (!run) { take(to, on); return 1; }
	for (const name of run) take(name, on);
	return run.length;
}

/**
 * The rows from one to the other, in drawn order, either way round.
 *
 * Null when one of them is not on the screen -- the filter has moved since the
 * anchor was set -- which the caller reads as "no range, just this one".
 */
export function rangeOf(order, from, to) {
	const i = order.indexOf(from);
	const j = order.indexOf(to);
	if (i < 0 || j < 0) return null;
	return order.slice(Math.min(i, j), Math.max(i, j) + 1);
}

function systemRow(node, depth) {
	const insideTicked = taken(node.path) && !ui.picked.has(node.path);
	// While the tree is filtered this row cannot honestly mean "take the
	// sub-system whole": what is drawn under it is a few of the blocks in it,
	// chosen by the filter, and taking the other hundred as well because the
	// heading was ticked would be a different thing from what it looks like.
	// So filtered it takes what is shown; unfiltered it takes the sub-system
	// itself, which arrives as a sub-system with everything in it.
	const shownInside = filtering() ? namesIn(node) : null;
	const box = el('input', {
		type: 'checkbox',
		'aria-label': shownInside
			? `the ${plural(shownInside.length, 'block')} shown in ${node.path}`
			: `${node.path}, and everything in it`,
	});
	box.checked = shownInside
		? shownInside.length > 0 && shownInside.every(taken)
		: taken(node.path);
	box.disabled = insideTicked;
	// Part of it is coming, but not all: the tick says so rather than claiming
	// either.
	box.indeterminate = !box.checked
		&& (shownInside ? shownInside.some(taken) : partly.has(node.path));
	const twisty = el('button', {
		type: 'button', className: 'imp-twisty',
		'aria-label': ui.open.has(node.path) ? 'Collapse' : 'Expand',
	}, ui.open.has(node.path) ? '▾' : '▸');
	twisty.addEventListener('click', (ev) => {
		// Opening a sub-system is not taking it.
		ev.stopPropagation();
		if (ui.open.has(node.path)) ui.open.delete(node.path); else ui.open.add(node.path);
		redraw();
	});

	const row = el('div', {
		className: 'imp-row imp-row-system', style: `--depth:${depth}`,
		title: shownInside
			? `${node.path} — the tick takes the ${plural(shownInside.length, 'block')} `
				+ 'shown under it, since the tree is filtered'
			: `${node.path} — the tick takes it as a sub-system, with everything in it`,
	}, box, twisty, el('span', { className: 'imp-name' }, node.name),
	el('span', { className: 'imp-count' },
		String(shownInside ? shownInside.length : node.deep)));
	rowGesture(row, box, insideTicked, node.path, (on) => {
		if (shownInside) {
			for (const n of shownInside) take(n, on);
			return shownInside.length;
		}
		if (on) {
			// Everything under it is covered by the sub-system itself now.
			for (const n of [...ui.picked]) if (isWithin(n, node.path)) ui.picked.delete(n);
			ui.picked.add(node.path);
		} else {
			ui.picked.delete(node.path);
		}
		return 1;
	});
	return row;
}

function blockRow(b, depth) {
	const inside = taken(b.name) && !ui.picked.has(b.name);
	const box = el('input', {
		type: 'checkbox', 'aria-label': b.name,
	});
	box.checked = taken(b.name);
	box.disabled = inside;
	// Two ways a block comes along without being ticked, and they are not the
	// same thing: an equation reads it, or it is the line between two blocks
	// that are coming. Both are worth marking; they are worth marking apart.
	const why = box.checked ? null
		: ui.survey?.needed.includes(b.name) ? 'needed'
			: ui.survey?.carried.includes(b.name) ? 'joins them' : null;
	const row = el('div', {
		className: `imp-row${why ? ' is-needed' : ''}`,
		style: `--depth:${depth}`,
		title: why === 'needed'
			? `${b.name} — coming anyway, because what you chose reads it`
			: why ? `${b.name} — coming anyway, because it joins two blocks that are`
				: b.name,
	}, box, blockIcon(b.kind), el('span', { className: 'imp-name' }, b.label),
	why ? el('span', { className: 'imp-tag' }, why) : null);
	rowGesture(row, box, inside, b.name, (on, ev) => (
		ev.shiftKey && ui.anchor && ui.anchor !== b.name
			? applyRange(ui.anchor, b.name, on)
			: (take(b.name, on), 1)));
	return row;
}

// --- the right pane: what taking it would mean ------------------------------

function planPane() {
	const pane = el('section', { className: 'imp-pane imp-plan' });
	if (ui.error) {
		pane.append(el('p', { className: 'imp-problem' }, ui.error));
		return pane;
	}
	const s = ui.survey;
	if (!s) {
		pane.append(el('p', { className: 'hint' },
			'Tick what to bring across. Whatever those blocks need — the '
			+ 'parameters their equations read, the compartments a transfer joins '
			+ '— comes with them, and this is where it will be listed, along '
			+ 'with everything that has to be decided about the index lists.'));
		return pane;
	}

	pane.append(group('Coming across', [
		el('p', { className: 'imp-line' },
			el('b', {}, plural(s.count, 'block')),
			s.needed.length ? ` · ${s.needed.length} brought along` : '',
			s.carried.length ? ` · ${plural(s.carried.length, 'connection')}` : ''),
		toggle('Bring what they need', ui.bringNeeded,
			'The parameters, expressions and compartments the chosen blocks refer to. '
			+ 'Without them the equations arrive reading names this model may not have.',
			(on) => { ui.bringNeeded = on; restate(); }),
		s.needed.length ? names('Brought along', s.needed) : null,
		s.stranded.length ? el('p', { className: 'imp-warn' },
			`${plural(s.stranded.length, 'connection')} cannot come: `
			+ `${s.stranded.slice(0, 3).join(', ')} would have an end left behind. `
			+ 'Tick the blocks at both ends to bring them.') : null,
	]));

	const rows = s.lists.filter((l) => l.status !== 'derived');
	const derived = s.lists.filter((l) => l.status === 'derived');
	if (rows.length || derived.length) {
		pane.append(group('Index lists', [
			...rows.map(listRow),
			derived.length ? el('p', { className: 'hint' },
				`${derived.map((l) => l.name).join(', ')} `
				+ `${derived.length === 1 ? 'is' : 'are'} worked out from the model `
				+ 'itself, so there is nothing to decide: the blocks will be indexed '
				+ 'by this model’s own.') : null,
		]));
	}

	const notes = imp.nuclideNotes(ui.target, ui.source, s, ui.choices);
	if (notes && (notes.adding.length || notes.conflicts.length)) {
		pane.append(group('Radionuclides', [
			notes.adding.length
				? names(`${plural(notes.adding.length, 'nuclide')} added to this model`,
					notes.adding)
				: null,
			notes.conflicts.length ? el('p', { className: 'imp-warn' },
				`${plural(notes.conflicts.length, 'half-life')} differ between the two `
				+ `models — ${notes.conflicts.slice(0, 3)
					.map((c) => `${c.nuclide} ${c.source} vs ${c.target}`).join(', ')}. `
				+ 'This model keeps its own.') : null,
			notes.unknown.length ? el('p', { className: 'imp-warn' },
				`No half-life anywhere for ${notes.unknown.join(', ')}; `
				+ 'they arrive as stable. Set them on the Index lists tab.') : null,
			notes.chainsPinned ? el('p', { className: 'imp-warn' },
				'This model writes its own decay chains, so the nuclides arriving have '
				+ 'no ingrowth until they are added there.') : null,
		]));
	}

	// The answer everything above is a reason for.
	if (ui.check) {
		pane.append(group('Afterwards', [
			ui.check.pending ? el('p', { className: 'hint' }, 'Checking whether it builds…')
				: ui.check.skipped ? el('p', { className: 'hint' },
					`Not checked: ${ui.check.skipped}.`)
					: ui.check.ok ? el('p', { className: 'imp-ok' }, 'The model still builds.')
						: el('p', { className: 'imp-warn' },
							'The model will not build: ', el('b', {}, ui.check.message)),
			ui.check.ok === false ? el('p', { className: 'hint' },
				'It can still be imported — the strip under the tabs will say the same '
				+ 'thing, and Cmd+Z takes the whole import back.') : null,
		]));
	}

	if (s.clashes.length) {
		pane.append(group('Names already used', [
			el('p', { className: 'hint' },
				'A name that is taken where the block lands gets a number, the way a '
				+ 'paste does.'),
			el('ul', { className: 'imp-renames' },
				...s.clashes.slice(0, NAMED).map(([from, to]) => el('li', {},
					el('code', {}, from), ' → ', el('code', {}, to)))),
			s.clashes.length > NAMED
				? el('p', { className: 'hint' }, `and ${s.clashes.length - NAMED} more`)
				: null,
		]));
	}
	return pane;
}

function group(title, kids) {
	return el('div', { className: 'imp-group' },
		el('h3', {}, title), ...kids.filter(Boolean));
}

function toggle(label, on, title, onChange) {
	const box = el('input', { type: 'checkbox', checked: on });
	box.addEventListener('change', () => onChange(box.checked));
	return el('label', { className: 'imp-toggle', title }, box, label);
}

function names(label, list) {
	return el('p', { className: 'imp-line' },
		el('span', { className: 'imp-label' }, `${label}: `),
		list.slice(0, NAMED).join(', '),
		list.length > NAMED ? ` and ${list.length - NAMED} more` : '');
}

/**
 * One dimension, and what becomes of it.
 *
 * A select for what it becomes, and -- when what it becomes is missing some of
 * the indices the values are keyed by -- a tick for widening it. The two
 * together cover every case there is: the list is not here, the list is here,
 * the list is here under another name, the list is here but narrower, and the
 * dimension is not wanted at all.
 */
function listRow(row) {
	const choice = ui.choices[row.name];
	const sel = el('select', { className: 'imp-choice' });
	const add = (value, text, selected) => sel.append(
		el('option', { value, selected }, text));
	if (row.status === 'missing') {
		add('add', `Add ${row.name} to this model`, choice.mode === 'add');
	}
	for (const c of row.candidates) {
		add(`use:${c.name}`,
			(c.name === row.name ? `Use ${c.name}` : `Use ${c.name} instead`)
			+ (c.material ? ' — the radionuclides' : ''),
			choice.mode === 'use' && choice.into === c.name);
	}
	add('drop', 'Drop the dimension', choice.mode === 'drop');
	sel.addEventListener('change', () => {
		const v = sel.value;
		ui.choices[row.name] = v === 'add' ? { mode: 'add', into: null, widen: false }
			: v === 'drop' ? { mode: 'drop', into: null, widen: false }
				: { mode: 'use', into: v.slice(4), widen: false };
		changed();
	});

	const cost = imp.costOf(row, choice);
	const kids = [
		el('div', { className: 'imp-list-head' },
			el('span', { className: 'imp-list-name' }, row.name),
			sel),
	];
	if (choice.mode === 'use' && (cost.missing?.length || cost.adding?.length)) {
		const missing = cost.missing?.length ? cost.missing : cost.adding;
		const c = row.candidates.find((x) => x.name === choice.into);
		kids.push(toggle(
			`Add ${plural(missing.length, 'index', 'indices')} to ${choice.into}`,
			!!choice.widen,
			`${c?.users ?? 0} block${c?.users === 1 ? '' : 's'} in this model are `
			+ `indexed by ${choice.into}, and every one of them gains a column. `
			+ 'Leave it off to keep this model as it is.',
			(on) => { ui.choices[row.name].widen = on; changed(); },
		));
		kids.push(el('p', { className: choice.widen ? 'hint' : 'imp-warn' },
			choice.widen
				? `${missing.join(', ')} — added.`
				: `${missing.join(', ')} — not in ${choice.into}`
					+ (cost.lost ? `, so ${plural(cost.lost, 'value')} will be dropped.` : '.')));
	}
	if (choice.mode === 'drop') {
		kids.push(el('p', { className: 'imp-warn' },
			`The blocks arrive with no ${row.name} dimension`
			+ (row.values ? `, and ${plural(row.values, 'value')} under it go.` : '.')));
	}
	if (choice.mode === 'add' && row.incoming) {
		kids.push(el('p', { className: 'hint' },
			`${plural((row.incoming.indices ?? []).length, 'index', 'indices')}`
			+ `${row.incoming.for_contaminants ? ', as this model’s radionuclides' : ''}`
			+ `${row.incoming.sub_set_of ? `, a sub-set of ${row.incoming.sub_set_of}` : ''}.`));
		// A list of blocks, arriving in a model that has blocks of its own.
		if (row.uncovered) {
			kids.push(el('p', { className: 'imp-warn' },
				`${row.name} names blocks rather than indices, and will not name the `
				+ `${row.uncovered} already in this model. Anything that reads across `
				+ 'the two will not build until it does — which is a modelling '
				+ 'decision, so it is left to you on the Index lists tab.'));
		}
	}
	return el('div', { className: 'imp-list' }, ...kids);
}

// --- the footer: where they go, and the button ------------------------------

function footer() {
	const where = el('select', { className: 'imp-where' });
	const paths = ed.systems(ui.target);
	where.append(el('option', { value: ' keep', selected: ui.into === null },
		'Wherever they were'));
	where.append(el('option', { value: '', selected: ui.into === '' }, 'The top level'));
	for (const p of paths) {
		where.append(el('option', { value: p, selected: ui.into === p }, p));
	}
	where.addEventListener('change', () => {
		ui.into = where.value === ' keep' ? null : where.value;
		redraw();
	});

	const go = el('button', {
		className: 'primary', type: 'button',
		disabled: !ui.survey || !ui.survey.count,
	}, ui.survey?.count ? `Import ${plural(ui.survey.count, 'block')}` : 'Import');
	go.addEventListener('click', doImport);

	const cancel = el('button', { className: 'ghost', type: 'button' }, 'Cancel');
	cancel.addEventListener('click', () => closeModal());

	const another = el('button', {
		className: 'ghost', type: 'button', title: 'Read a different file',
	}, 'Another file…');
	another.addEventListener('click', () => { closeModal(); ui?.onPickAnother?.(); });

	return el('div', { className: 'imp-foot' },
		el('label', { className: 'imp-into' }, 'Into', where),
		el('span', { className: 'spacer' }),
		ui.onPickAnother ? another : null,
		cancel, go);
}

function doImport() {
	const { target, source, survey, choices, into } = ui;
	try {
		const report = imp.applyImport(target, source, survey, choices, { into });
		const done = ui.onImport;
		closeModal();
		done?.(report);
	} catch (e) {
		ui.error = e.message;
		redraw();
		ui.onStatus?.(e.message, 'warn');
	}
}
