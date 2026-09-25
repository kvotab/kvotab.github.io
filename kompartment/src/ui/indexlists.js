/**
 * The Index lists panel: every dimension of the model, and what the
 * radionuclide dimension decays into.
 *
 * Index lists, sub-sets, mappings, the contaminant catalogue and the decay
 * data are all here -- one place, because they are one subject. An index list
 * is what makes a model N-dimensional; the contaminant
 * list is an index list with a flag, and half-lives and decay chains are
 * properties of its indices. Splitting them across a cramped sidebar section
 * and a separate tab meant adding a nuclide and giving it a half-life were two
 * different places, and the mapping editor never had the width to be read.
 *
 * Two things worth knowing about the data behind the decay half of this panel:
 *
 *  - `half_lives` is an *override map* on ICRP 107, so a nuclide with no entry
 *    here still decays at the published rate. The table shows which is which,
 *    and lets an override be dropped again.
 *  - `chains`, by contrast, *replaces* the computed default wholesale (see
 *    Project's constructor). The first edit therefore materialises the
 *    built-ins into the project, which src/domain/edit.js handles; without
 *    that, adding one pair would silently delete every other chain.
 */

import * as ed from '../domain/edit.js';
import { HALF_LIVES, lambda, halfLifeFromLambda } from '../domain/nuclides.js';
import { attachCompletion, nuclideLook, completionIsOpen } from './complete.js';
import { chainGraph } from './chaingraph.js';
// What a list is, in three words, for the side list and the detail header.
// Shared with the Information view; see ./summary.js.
import { summariseIndexList as roleTag, fmtTime } from './summary.js';
import { el } from './parts.js';

/**
 * Which list the detail pane is showing.
 *
 * Module state rather than DOM state: every edit re-renders the whole panel,
 * so anything held in the markup would be lost on the next keystroke. It
 * survives a re-render, and falls back when the name it names is gone.
 */
let picked = null;

/** Which list the pane on screen was last built for, so a move to another one
 *  starts at the top while an edit to this one does not. */
let shownFor = null;

/** Opens the panel on a particular list -- used after adding or renaming one. */
export function selectIndexList(name) { picked = name ?? null; }

/** Years, shown compactly across the 20-odd orders of magnitude involved. */
function fmtYears(v) {
	if (v == null) return '';
	if (!Number.isFinite(v)) return 'stable';
	if (v >= 1e5 || v < 1e-2) return v.toExponential(4);
	return String(Number(v.toPrecision(6)));
}

/**
 * A half-life in the unit that suits it: `4.468e9 y`, `18.7 d`, `22 m`.
 *
 * The table under the picture is in years throughout, because years is what
 * the file stores and what the solver works in, and a column of one unit can
 * be compared down its length. A box in the picture has room for about six
 * characters, and `4.183e-5 y` spends them all on the exponent when what the
 * reader wants to know is that Fr-223 is gone within the hour.
 */
function fmtSpan(years) {
	if (years == null) return null;
	if (!Number.isFinite(years)) return 'stable';
	if (years >= 1 || years <= 0) return `${fmtTime(years)} y`;
	for (const [size, unit] of [[1 / 365.25, 'd'], [1 / 8766, 'h'], [1 / 525960, 'm']]) {
		if (years >= size) return `${Number((years / size).toPrecision(3))} ${unit}`;
	}
	return `${fmtTime(years * 31557600)} s`;
}

/**
 * Draw something into a box, again whenever the box changes width.
 *
 * The chain drawing wraps its chains to fit the room it is given, so it has to
 * be told how wide that is -- and now that it shares a row with the table,
 * that changes with the window, with the panel splitter, and with whether the
 * row is wide enough to hold both at all. A ResizeObserver redraws it.
 *
 * Keyed on whole pixels with a few to spare, so a redraw cannot set off
 * another one, and the guessed width is remembered across renders: editing a
 * branching ratio rebuilds this panel, and the guess being right means the
 * rebuild draws once rather than twice.
 */
let lastGraphWidth = 720;

function fitGraph(frame, draw) {
	let was = 0;
	const paint = (width) => {
		if (Math.abs(width - was) < 8) return;
		was = width;
		lastGraphWidth = width;
		const picture = draw(width);
		frame.replaceChildren(...(picture ? [picture] : []));
	};
	paint(lastGraphWidth);
	if (typeof ResizeObserver === 'function') {
		// One observer for the one frame that is on screen. The panel is
		// rebuilt on every visit, and an observer per rebuild watching a frame
		// that has since been thrown away is a leak in all but name.
		graphWatch?.disconnect();
		graphWatch = new ResizeObserver((entries) => {
			const width = entries[0]?.contentRect?.width ?? 0;
			if (width > 0) paint(width);
		});
		graphWatch.observe(frame);
	}
	return frame;
}

/** The observer on the current decay drawing's frame, replaced with it. */
let graphWatch = null;

/** One titled block of the detail pane. */
function card(title, ...kids) {
	return el('section', { className: 'ix-card' },
		title ? el('h3', {}, title) : null, ...kids);
}

/**
 * @param {HTMLElement} host
 * @param {object} project  the raw project object
 * @param {{onChange: Function, onStatus: Function}} hooks
 */
export function renderIndexLists(host, project, hooks = {}) {
	// Every edit rebuilds this panel, and the half-life table of a 30-nuclide
	// model is far longer than the window. Rebuilding under a scrolled pane
	// would throw the reader back to the top on each committed value, so the
	// two scroll offsets are carried across -- but only while the pane is
	// still about the same list. Opening another one starts at its top.
	const wasAt = {
		detail: host.querySelector('.ix-detail')?.scrollTop ?? 0,
		side: host.querySelector('.ix-side')?.scrollTop ?? 0,
	};
	host.replaceChildren();

	const lists = ed.indexLists(project);
	if (!lists.some((l) => l.name === picked)) picked = null;
	picked ??= (lists.find((l) => l.for_contaminants) ?? lists[0])?.name ?? null;
	const sameList = picked === shownFor;
	shownFor = picked;

	// A pure-selection change moves nothing in the model, so it redraws this
	// panel rather than going through the application's change path.
	const draw = () => renderIndexLists(host, project, hooks);
	const pick = (name) => { picked = name; draw(); };

	const wrap = el('div', { className: 'ix' });
	wrap.append(renderSide(project, lists, hooks, pick));

	const detail = el('div', { className: 'ix-detail' });
	const list = lists.find((l) => l.name === picked);
	if (list) renderDetail(detail, project, list, lists, hooks, pick);
	wrap.append(detail);

	host.append(wrap);
	// After the append, so the offsets are not clamped against a pane that has
	// no height yet.
	wrap.querySelector('.ix-side').scrollTop = wasAt.side;
	if (sameList) detail.scrollTop = wasAt.detail;
}

// --- the list of lists -------------------------------------------------------

function renderSide(project, lists, hooks, pick) {
	const side = el('div', { className: 'ix-side' });
	// What this pane is, behind an (i) at the end of its heading, where the
	// sections of the left panel keep theirs. See ./infopanel.js.
	side.append(el('h2', {}, el('span', {}, 'Index lists'), hooks.info?.() ?? null));

	const nav = el('div', { className: 'ix-nav' });
	for (const list of lists) {
		const on = list.indices.filter((i) => i.enabled !== false).length;
		const b = el('button', {
			className: 'ix-nav-item' + (list.name === picked ? ' is-current' : '')
				+ (list.derived ? ' is-derived' : ''),
			type: 'button',
		},
		el('span', { className: 'ix-nav-name' }, list.name),
		el('span', { className: 'ix-nav-count' },
			on === list.indices.length ? String(on) : `${on}/${list.indices.length}`),
		el('span', { className: 'ix-nav-role' }, roleTag(list)));
		b.addEventListener('click', () => pick(list.name));
		nav.append(b);
	}
	side.append(nav);

	const addList = el('button', { type: 'button', className: 'ghost ix-new' },
		'+ Index list');
	addList.addEventListener('click', () => {
		try {
			const l = ed.addIndexList(project);
			picked = l.name;
			hooks.onChange?.();
			hooks.onStatus?.(
				`Added '${l.name}'. Double-click an index to rename it, and tick the `
				+ 'list on a block to index that block by it.', 'info');
		} catch (e) { hooks.onStatus?.(e.message, 'warn'); }
	});
	side.append(addList);

	// Scenarios are an index list with a flag, which is not something anyone
	// would guess from a blank model. One button, and the model has them.
	if (!ed.scenarioList(project)) {
		const addScenarios = el('button', {
			type: 'button', className: 'ghost ix-new',
			title: 'Alternative futures to run the model under. One is live at a '
				+ 'time, chosen under Simulation; every block indexed by them is '
				+ 'read at that one.',
		}, '+ Scenarios');
		addScenarios.addEventListener('click', () => {
			try {
				const l = ed.addIndexList(project, {
					base: 'Scenario', indices: ['Base', 'Alternative'],
				});
				ed.setScenarioList(project, l.name);
				picked = l.name;
				hooks.onChange?.();
				hooks.onStatus?.(
					`Added '${l.name}' with two to choose between. Double-click either `
					+ 'to rename it, and pick the live one at the top of Simulation.',
					'info');
			} catch (e) { hooks.onStatus?.(e.message, 'warn'); }
		});
		side.append(addScenarios);
	}

	side.append(el('p', { className: 'hint ix-blurb' },
		'A block indexed by a list holds one value per index, so a compartment '
		+ 'indexed by two lists of 5 and 3 is 15 state variables. Tick the lists '
		+ 'a block is indexed by in its own settings.'));

	return side;
}

// --- one list ----------------------------------------------------------------

function renderDetail(host, project, list, lists, hooks, pick) {
	// The catalogue of materials and the radionuclides among them: both built
	// in, both protected, and each with its own half of the panel -- the units
	// belong to the materials, the half-lives and the chains to the nuclides.
	const isMaterial = !!list.for_contaminants;
	const isNuclides = !!list.for_nuclides;
	const builtIn = isMaterial || isNuclides;
	const derived = !!list.derived;

	// --- header: name, what it is, and the way to delete it ---
	const head = el('div', { className: 'ix-head' });
	if (builtIn || derived) {
		head.append(el('h2', { className: 'ix-title' }, list.name));
	} else {
		const nameInput = el('input', {
			type: 'text', value: list.name, className: 'ix-name', spellcheck: false,
		});
		nameInput.addEventListener('change', () => {
			const next = nameInput.value.trim();
			try {
				ed.renameIndexList(project, list.name, next);
				// Every block that was indexed by it followed the rename, and so
				// does the pane looking at it.
				picked = next;
				hooks.onChange?.();
			} catch (e) {
				hooks.onStatus?.(e.message, 'warn');
				nameInput.value = list.name;
			}
		});
		head.append(nameInput);
	}
	head.append(el('span', { className: 'ix-role-tag' }, roleTag(list)));
	head.append(el('span', { className: 'spacer' }));

	if (!builtIn && !derived) {
		const del = el('button', {
			className: 'ghost ix-del', type: 'button', title: `Delete ${list.name}`,
		}, 'Delete');
		del.addEventListener('click', () => {
			try {
				ed.deleteIndexList(project, list.name);
				picked = null;
				hooks.onChange?.();
			} catch (e) { hooks.onStatus?.(e.message, 'warn'); }
		});
		head.append(del);
	}
	host.append(head);

	// Who is indexed by this: the reason a delete is refused, and the fastest
	// answer to "what does widening this list cost".
	// Blocks and lists apart, because they are not the same answer. The
	// catalogue is the parent of the radionuclides and of the elements in
	// every model there is, so lumping them in said "indexes 2 blocks" about a
	// dimension nothing was indexed by.
	const users = ed.indexListUsers(project, list.name);
	const fromLists = new Set(ed.indexLists(project)
		.filter((l) => l.sub_set_of === list.name || l.mapping?.to === list.name)
		.map((l) => l.name));
	const blocks = users.filter((u) => !fromLists.has(u));
	const said = [
		blocks.length
			? `Indexes ${blocks.length} block${blocks.length === 1 ? '' : 's'}: `
				+ blocks.slice(0, 12).join(', ')
				+ (blocks.length > 12 ? `, and ${blocks.length - 12} more` : '') + '.'
			: 'Nothing is indexed by this yet.',
		fromLists.size ? `${[...fromLists].join(' and ')} ${fromLists.size === 1 ? 'is' : 'are'} `
			+ `defined from it.` : '',
	].filter(Boolean);
	host.append(el('p', { className: 'ix-users' }, said.join(' ')));

	if (isMaterial) {
		const nuclides = ed.nuclideList(project);
		host.append(el('p', { className: 'hint ix-note' },
			'Every material the model knows, and built in: it keeps its name and '
			+ 'cannot be deleted. ',
			nuclides && nuclides !== list
				? el('span', {}, 'The ones that decay are in ',
					el('b', {}, nuclides.name),
					' and arrive here with them; anything else here is a material '
					+ 'that does not decay — stable carbon beside C-14, water, a '
					+ 'population. A compartment indexed by this holds all of them '
					+ 'and decays the ones that decay.')
				: 'Decay and ingrowth act along it.'));
	}
	if (isNuclides) {
		const root = ed.materialList(project);
		host.append(el('p', { className: 'hint ix-note' },
			'The materials that have a half-life, and built in: it keeps its name '
			+ 'and cannot be deleted. Decay and ingrowth act along it. ',
			root && root !== list
				? el('span', {}, 'Adding one here adds the material to ',
					el('b', {}, root.name), ' as well, and removing one removes '
					+ 'the material — to keep it in the model without decay, add it '
					+ 'there instead.')
				: ''));
	}
	if (derived) {
		// Each derived list says what it follows. The element one follows the
		// nuclides; the compartment and transfer ones follow the model itself,
		// and carry their own note (see deriveBlockLists).
		host.append(list.note
			? el('p', { className: 'hint ix-note' }, list.note)
			: el('p', { className: 'hint ix-note' },
				'Worked out from ', el('b', {}, list.mapping?.to ?? 'the materials'),
				' rather than stored, so there is nothing to edit here: chemistry is a '
				+ 'property of the element, and this list follows the materials so the '
				+ 'two cannot fall out of step. Every material has one — the element of '
				+ 'a nuclide’s name is its symbol, so C-12 joins C-14 under C; a name '
				+ 'that is not a nuclide’s is its own element.'));
	}
	if (list.for_scenarios) {
		const active = ed.activeScenario(project);
		host.append(el('p', { className: 'hint ix-note' },
			active
				? `Not an axis of the model: one scenario is live at a time -- '${active}' `
					+ 'right now, chosen at the top of Simulation -- and every block '
					+ 'indexed by this is read at that one.'
				: 'Not an axis of the model: one scenario is live at a time, chosen at '
					+ 'the top of Simulation. Add one to choose between them.'));
	}

	// --- how it is defined ---
	if (!builtIn && !derived) host.append(renderRole(project, list, lists, hooks));

	// --- its indices ---
	host.append(renderIndices(project, list, hooks));

	// --- what it is defined from, in detail ---
	if (list.mapping) host.append(renderMapping(project, list, lists, hooks));
	if (list.sub_set_of && !isNuclides) host.append(renderSubSet(project, list, lists, hooks));

	// --- what the materials that do not decay are measured in ---
	if (isMaterial) host.append(renderMaterialUnits(project, list, hooks));

	// --- and, for the nuclides, what they decay into ---
	if (isNuclides) {
		const enabled = new Set(
			list.indices.filter((i) => i.enabled !== false).map((i) => i.name),
		);
		const timeUnit = project.simulation?.time_unit ?? 'year';
		host.append(renderDecayUnit(project, hooks));
		host.append(renderHalfLives(project, list, enabled, timeUnit, hooks));
		host.append(renderChains(project, list, enabled, hooks));
	}

	// A grouping is defined by its parent's indices, so it is reachable from
	// here rather than only from the side list.
	const parentName = list.sub_set_of ?? list.mapping?.to ?? null;
	if (parentName) {
		const go = el('button', { className: 'ghost ix-goto', type: 'button' },
			`Open ${parentName}`);
		go.addEventListener('click', () => pick(parentName));
		host.append(go);
	}
}

/**
 * What a list is defined from.
 *
 * Three ways for a list to exist, all of them in the file format and in
 * Ecolego: an axis of its own, a sub-set of another list, or a mapping that
 * groups another list's indices. A mapping is written in the many-to-one
 * direction -- which element is this nuclide, which climate class is this year
 * -- because that is the direction a modeller thinks in and the only one that
 * is total.
 */
function renderRole(project, list, lists, hooks) {
	// Only a root list can be a parent: a sub-set of a sub-set has no meaning
	// the engine can resolve, so it is not offered.
	const roots = lists.filter((l) => l.name !== list.name && !l.sub_set_of && !l.mapping);
	const role = list.sub_set_of ? 'sub_set' : list.mapping ? 'mapping' : 'plain';
	const target = list.sub_set_of ?? list.mapping?.to ?? roots[0]?.name ?? '';

	const kindSel = el('select', { className: 'ix-role-kind' });
	for (const [value, label] of [
		['plain', 'an axis of its own'],
		['sub_set', 'a sub-set of'],
		['mapping', 'a grouping of'],
	]) {
		const option = el('option', { value, selected: value === role }, label);
		if (value !== 'plain' && !roots.length) option.disabled = true;
		kindSel.append(option);
	}

	const whichSel = el('select', { className: 'ix-role-of' });
	for (const l of roots) {
		whichSel.append(el('option', { value: l.name, selected: l.name === target }, l.name));
	}
	whichSel.hidden = role === 'plain';

	const apply = () => {
		try {
			ed.setListRole(project, list.name, kindSel.value, whichSel.value || null);
		} catch (e) {
			hooks.onStatus?.(e.message, 'warn');
		}
		hooks.onChange?.();
	};
	kindSel.addEventListener('change', apply);
	whichSel.addEventListener('change', apply);

	// One list at a time can be the scenarios, so this is a choice about the
	// model rather than about the list.
	const cb = el('input', { type: 'checkbox', checked: !!list.for_scenarios });
	cb.addEventListener('change', () => {
		try { ed.setScenarioList(project, list.name, cb.checked); hooks.onChange?.(); }
		catch (e) {
			hooks.onStatus?.(e.message, 'warn');
			cb.checked = !!list.for_scenarios;
		}
	});

	return card('Defined as',
		el('div', { className: 'ix-role-row' }, kindSel, whichSel),
		el('label', {
			className: 'inline-check ix-scenario',
			title: 'One index of the scenarios is live at a time, chosen under '
				+ 'Simulation. Every block indexed by them is read at that one, and '
				+ 'the dimension never reaches the state vector.',
		}, cb, 'these are the model’s scenarios'));
}

/** Above this many indices the card filters rather than showing them all. */
const FILTER_ABOVE = 60;

/** And shows at most this many at once, however few the filter leaves. */
const FILTER_WINDOW = 240;

/**
 * A filter over an already-built chip list. Hides rather than rebuilds, so the
 * caret stays where it is and a 1,600-chip list costs one pass per keystroke.
 */
function indexFilter(list, chips) {
	const field = el('input', {
		type: 'search', className: 'ix-filter', spellcheck: false,
		placeholder: `filter ${list.indices.length} indices`,
	});
	const note = el('p', { className: 'hint ix-shown' });
	chips._note = note;

	const apply = () => {
		const q = field.value.trim().toLowerCase();
		let shown = 0;
		let matched = 0;
		for (const wrap of chips.children) {
			const name = (wrap.dataset.index ?? '').toLowerCase();
			const hit = !q || name.includes(q);
			if (hit) matched++;
			const show = hit && shown < FILTER_WINDOW;
			if (show) shown++;
			wrap.hidden = !show;
		}
		note.textContent = matched > shown
			? `Showing ${shown} of ${matched}${q ? ' matching' : ''}` +
				` — narrow the filter to reach the rest.`
			: q
				? `${matched} of ${list.indices.length} match.`
				: '';
		note.hidden = !note.textContent;
	};
	field.addEventListener('input', apply);
	apply();
	return field;
}

/**
 * How long a click waits to find out whether it is half of a double-click.
 *
 * The platform's own threshold is not readable from a page, and 250ms is what
 * every desktop uses. Only the chips need it: they are the one control here
 * carrying two gestures.
 */
const DOUBLE_CLICK_MS = 250;

/** The indices themselves: toggle, rename, remove, add. */
function renderIndices(project, list, hooks) {
	const derived = !!list.derived;
	const on = list.indices.filter((i) => i.enabled !== false).length;
	const box = card(null,
		el('h3', {}, 'Indices',
			el('span', { className: 'ix-card-count' },
				on === list.indices.length
					? `${on}`
					: `${on} of ${list.indices.length} enabled`)));

	const chips = el('div', { className: 'chips ix-chips' });
	for (const idx of list.indices) {
		const enabled = idx.enabled !== false;
		if (derived) {
			const one = el('span', { className: 'chip chip-static' }, idx.name);
			one.dataset.index = idx.name;
			chips.append(one);
			continue;
		}
		const chip = el('button', {
			className: `chip chip-toggle${enabled ? '' : ' is-off'}`,
			type: 'button',
			title: `${enabled ? 'Enabled: click to exclude from the simulation'
				: 'Disabled: click to include'} · double-click to rename`,
		}, idx.name);
		// The toggle waits to see whether a second click is coming.
		//
		// Both gestures are on this one element, and the toggle re-renders the
		// whole panel -- so acting on the first click destroyed the chip before
		// the second arrived, the second landed on the element that replaced
		// it, and the browser sent `dblclick` to the nearest common ancestor of
		// the two, which is not the chip. The rename could not be reached at
		// all, while the title on the chip went on offering it, and the two
		// toggles cancelled out so nothing looked as though it had happened.
		//
		// Deferring the toggle by the double-click interval is what makes both
		// gestures reachable: nothing is rebuilt until the second click has had
		// its chance. A lone click therefore takes a quarter of a second to
		// take effect, which is the price of putting two gestures on one chip
		// and is invisible beside the re-run it causes.
		let clickTimer = null;
		const cancelClick = () => { clearTimeout(clickTimer); clickTimer = null; };
		chip.addEventListener('click', (ev) => {
			// The second click of a double-click: the `dblclick` below owns it.
			if (ev.detail > 1) { cancelClick(); return; }
			cancelClick();
			clickTimer = setTimeout(() => {
				clickTimer = null;
				try { ed.setIndexEnabled(project, list.name, idx.name, !enabled); hooks.onChange?.(); }
				catch (e) { hooks.onStatus?.(e.message, 'warn'); }
			}, DOUBLE_CLICK_MS);
		});
		// Renamed in place. Everything keyed on the old name follows, which is
		// the whole reason this is not delete-and-add-again.
		chip.addEventListener('dblclick', (ev) => {
			ev.preventDefault();
			cancelClick();
			const field = el('input', {
				type: 'text', value: idx.name, className: 'chip-rename', spellcheck: false,
			});
			let done = false;
			const finish = (save) => {
				if (done) return;
				done = true;
				if (!save || field.value.trim() === idx.name) { hooks.onChange?.(); return; }
				try { ed.renameIndex(project, list.name, idx.name, field.value); }
				catch (e) { hooks.onStatus?.(e.message, 'warn'); }
				hooks.onChange?.();
			};
			field.addEventListener('keydown', (e) => {
				if (e.key === 'Enter') { e.preventDefault(); finish(true); }
				if (e.key === 'Escape') { e.preventDefault(); finish(false); }
			});
			field.addEventListener('blur', () => finish(true));
			chip.replaceWith(field);
			field.focus();
			field.select();
		});
		const x = el('button', {
			className: 'chip-x', type: 'button', title: `Remove ${idx.name}`,
		}, '×');
		x.addEventListener('click', (ev) => {
			ev.stopPropagation();
			try { ed.removeIndex(project, list.name, idx.name); hooks.onChange?.(); }
			catch (e) { hooks.onStatus?.(e.message, 'warn'); }
		});
		const wrap = el('span', { className: 'chip-wrap' }, chip, x);
		wrap.dataset.index = idx.name;
		chips.append(wrap);
	}
	if (!list.indices.length) {
		chips.append(el('span', { className: 'hint' },
			list.for_nuclides
				? 'No radionuclides yet. Add one below and it appears in the '
					+ 'half-life table with its built-in value — and in '
					+ `${ed.materialList(project)?.name ?? 'the materials'}, `
					+ 'since a radionuclide is a material.'
				: list.for_contaminants
					? 'No materials yet. Radionuclides added below arrive here too; '
						+ 'anything else typed here is a material that does not decay.'
					: 'No indices yet.'));
	}
	// A real model's index list can be enormous -- one assessment model's Transfers list has
	// 1,624 -- and a wall of that many chips is 20,000 pixels of pane. Above a
	// threshold the card gets a filter and shows a windowful at a time. The
	// chips are all built and hidden rather than re-rendered, so typing keeps
	// the caret and costs nothing.
	if (list.indices.length > FILTER_ABOVE) box.append(indexFilter(list, chips));
	box.append(chips);
	if (list.indices.length > FILTER_ABOVE) box.append(chips._note);

	if (derived) return box;

	// A sub-set holds names its parent has, so there is nothing to type: a name
	// the parent does not know is accepted here and then fails the build with
	// "is in the sub-set but not in its root list". The picker below adds them.
	//
	// The radionuclides are the exception, and they are a sub-set: a
	// radionuclide added here is added to the catalogue too -- one material,
	// entered where the half-life and the database are. Falling through to the
	// picker made the ICRP database unreachable in every imported model, where
	// the only way to add a nuclide was to type it into the materials and then
	// come back here and tick it.
	if (list.sub_set_of && !list.for_nuclides) {
		box.append(el('p', { className: 'hint' },
			'Taken from ', el('b', {}, list.sub_set_of), ', so they are picked rather '
			+ `than typed — see below. Removing one here leaves it in ${list.sub_set_of}.`));
		return box;
	}

	const addRow = el('div', { className: 'ix-add' });
	const input = el('input', {
		type: 'text', spellcheck: false,
		placeholder: list.for_nuclides ? 'e.g. Cs-137'
			: list.for_contaminants ? 'e.g. Carbon_12' : 'new index',
	});
	// The radionuclide field gets the same completion an equation field has,
	// over the database instead of over the model's blocks: it was the one
	// place in the application where a name had to be typed from memory. The
	// browser's `<datalist>` used to stand in for this, and it could not say
	// what anything was -- no half-life, no decay, no ordering by isotope, and
	// a different look in every browser.
	if (list.for_nuclides) {
		attachCompletion(input, nuclideLook({
			exclude: list.indices.map((i) => i.name),
		}));
		input.title = 'Type an element or a mass number — Cs, 137, caesium, cs137. '
			+ 'Ctrl-Space lists them all.';
	}
	// The other way in, for the radionuclides: browse the published database
	// rather than typing a name and then a half-life and then the pairs.
	if (list.for_nuclides && hooks.onBrowseNuclides) {
		const browse = el('button', {
			type: 'button', className: 'ghost',
			title: 'Choose from the radionuclides of ICRP Publication 107, with '
				+ 'their half-lives, and have the decay chain worked out for you',
		}, 'Browse ICRP 107…');
		browse.addEventListener('click', () => hooks.onBrowseNuclides());
		addRow.append(browse);
	}
	const commit = () => {
		const v = input.value.trim();
		if (!v) return;
		try {
			ed.addIndex(project, list.name, v);
		} catch (e) {
			hooks.onStatus?.(e.message, 'warn');
			return;
		}
		input.value = '';
		hooks.onChange?.();

		// A name the database has never heard of is still allowed -- this is a
		// modelling tool, and a model may carry a tracer that is not a nuclide
		// at all -- and addIndex starts it off stable so the model still runs.
		// Say so, since the one thing that must not happen is a decay rate
		// quietly assumed for you. With 1,252 radionuclides behind the field
		// this now means a name that is not one, or one spelled differently.
		if (list.for_nuclides && !(v in HALF_LIVES)) {
			hooks.onStatus?.(
				`Added '${v}' as stable — ICRP 107 has no nuclide of that name. `
				+ `Set a half-life below if it decays.`, 'info');
		} else if (list.for_contaminants && !list.for_nuclides) {
			// A material typed into the catalogue is not a radionuclide: it
			// gets no half-life and takes no part in a decay chain. Said,
			// because the two lists sit next to each other and the difference
			// between them is exactly this.
			hooks.onStatus?.(
				`Added '${v}' as a material. It does not decay — add it under `
				+ `${ed.nuclideList(project)?.name ?? 'the radionuclides'} instead `
				+ `if it should. Give it a unit below if it is not measured in `
				+ `${ed.inventoryUnit(project)}.`, 'info');
		}
	};
	const addBtn = el('button', { type: 'button', className: 'ghost' }, 'Add');
	addBtn.addEventListener('click', commit);
	input.addEventListener('keydown', (e) => {
		// While the list is up, Enter belongs to it: it takes the highlighted
		// nuclide, and the next Enter adds it.
		if (e.key === 'Enter' && !completionIsOpen(input)) { e.preventDefault(); commit(); }
	});
	addRow.prepend(input, addBtn);
	box.append(addRow);

	{
		box.append(el('p', { className: 'hint' },
			'A disabled index stays in the file and keeps its values, but takes no '
			+ 'part in a simulation. Double-click one to rename it — everything '
			+ 'keyed on the old name follows.'));
	}
	return box;
}

/**
 * The pairs of a mapping, in the direction they are read: one row per index of
 * the parent, saying which of these it belongs to.
 */
function renderMapping(project, list, lists, hooks) {
	const parent = lists.find((l) => l.name === list.mapping.to);
	const mine = new Map((list.mapping.pairs ?? []).map((p) => [p.to, p.from]));
	const unset = (parent?.indices ?? []).filter((i) => !mine.has(i.name)).length;

	const box = card(null,
		el('h3', {}, 'Mapping',
			el('span', { className: 'ix-card-count' },
				unset ? `${unset} not yet assigned` : 'complete')));

	box.append(el('p', { className: 'hint' },
		'Each index of ', el('b', {}, list.mapping.to), ' belongs to one of ',
		el('b', {}, list.name), '. Written this way round because it is the '
		+ 'direction that is total: one index of ' + list.mapping.to + ' has '
		+ 'exactly one counterpart here, while one of these may stand for '
		+ 'several — an element and its isotopes, a climate class and its years.'));

	// Nothing to choose, so nothing needs a column of its own: the pairs flow
	// like text and read as a sentence rather than as a form with the fields
	// taken out.
	if (list.derived) {
		const flow = el('div', { className: 'ix-map-flow' });
		for (const [to, from] of mine) {
			flow.append(el('span', { className: 'ix-map-static' },
				el('span', { className: 'ix-map-from' }, to),
				el('span', { className: 'ix-map-arrow' }, '\u2192'),
				el('b', {}, from)));
		}
		box.append(flow);
		return box;
	}

	const grid = el('div', { className: 'ix-map' });
	for (const idx of parent?.indices ?? []) {
		const pick = el('select', {});
		pick.append(el('option', { value: '', selected: !mine.has(idx.name) }, '—'));
		for (const own of list.indices ?? []) {
			pick.append(el('option', {
				value: own.name, selected: mine.get(idx.name) === own.name,
			}, own.name));
		}
		pick.addEventListener('change', () => {
			try {
				ed.setMappedIndex(project, list.name, idx.name, pick.value || null);
				hooks.onChange?.();
			} catch (e) { hooks.onStatus?.(e.message, 'warn'); }
		});
		grid.append(el('div', { className: 'ix-map-pair' },
			el('span', { className: 'ix-map-from' }, idx.name),
			el('span', { className: 'ix-map-to' }, pick)));
	}
	box.append(grid);

	if (unset) {
		const one = unset === 1;
		box.append(el('p', { className: 'ix-warn' },
			`${unset} ${one ? 'index' : 'indices'} of ${list.mapping.to} `
			+ `${one ? 'has' : 'have'} no counterpart here, so a block indexed by `
			+ `${list.name} cannot be read at ${one ? 'it' : 'them'}. The build says `
			+ `which.`));
	}
	return box;
}

/**
 * A sub-set holds names its parent has, so they are picked rather than typed:
 * a name the parent does not know would never resolve.
 */
function renderSubSet(project, list, lists, hooks) {
	const parent = lists.find((l) => l.name === list.sub_set_of);
	const have = new Set((list.indices ?? []).map((i) => i.name));
	const missing = (parent?.indices ?? []).filter((i) => !have.has(i.name));

	const box = card(null,
		el('h3', {}, `From ${list.sub_set_of}`,
			el('span', { className: 'ix-card-count' },
				`${have.size} of ${parent?.indices?.length ?? 0} taken`)));

	if (!missing.length) {
		box.append(el('p', { className: 'hint' },
			`Every index of ${list.sub_set_of} is in this sub-set. Remove one above `
			+ 'to narrow it.'));
		return box;
	}

	box.append(el('p', { className: 'hint' },
		`Not in this sub-set. Click one to add it — a value indexed by `
		+ `${list.name} is reachable from ${list.sub_set_of}, so the names have to `
		+ 'match.'));

	const chips = el('div', { className: 'chips ix-chips' });
	for (const idx of missing) {
		const b = el('button', {
			className: 'chip chip-add', type: 'button',
			title: `Add ${idx.name} to ${list.name}`,
		}, '+ ', idx.name);
		b.addEventListener('click', () => {
			try { ed.addIndex(project, list.name, idx.name); hooks.onChange?.(); }
			catch (e) { hooks.onStatus?.(e.message, 'warn'); }
		});
		chips.append(b);
	}
	box.append(chips);

	if (missing.length > 1) {
		const all = el('button', { className: 'ghost ix-addall', type: 'button' },
			`Add all ${missing.length}`);
		all.addEventListener('click', () => {
			try {
				for (const idx of missing) ed.addIndex(project, list.name, idx.name);
				hooks.onChange?.();
			} catch (e) { hooks.onStatus?.(e.message, 'warn'); }
		});
		box.append(all);
	}
	return box;
}

// --- the unit an inventory is held in ---------------------------------------

/**
 * What each material that is not a radionuclide is measured in.
 *
 * Ecolego holds a unit per material and a compartment reads it off the
 * material at the index -- `Compartment.getUnit(indices)` -- so a model with
 * stable carbon beside C-14 shows kgC at one index of a compartment and Bq at
 * the next. A radionuclide's unit is not here: the whole model's inventories
 * are in Bq or in mol, chosen just below, and every nuclide follows that.
 *
 * Only shown when there is something to show. A model whose materials are all
 * radionuclides -- which most are -- gets a line saying so rather than an
 * empty table.
 */
function renderMaterialUnits(project, list, hooks) {
	const nuclides = new Set(
		(ed.nuclideList(project)?.name === list.name ? [] : ed.nuclideList(project)?.indices ?? [])
			.map((i) => i.name),
	);
	const plain = list.indices.filter((i) => !nuclides.has(i.name));
	const box = card('Units');
	const inventory = ed.inventoryUnit(project);
	if (!plain.length) {
		box.append(el('p', { className: 'hint' },
			`Every material here is a radionuclide, so every one of them is an `
			+ `inventory in ${inventory} — set for the whole model just below. A `
			+ `material that is not a radionuclide carries a unit of its own, and `
			+ `gets a row here.`));
		return box;
	}
	box.append(el('p', { className: 'hint' },
		`What each material that does not decay is measured in. A compartment `
		+ `indexed by ${list.name} is labelled per index from these, so one that `
		+ `holds both reads ${plain[0].unit || 'its own unit'} at `
		+ `${plain[0].name} and ${inventory} at a radionuclide. Left blank it is `
		+ `labelled with nothing — a material that does not decay is not an `
		+ `inventory of anything in particular.`));

	const table = el('table', { className: 'ix-units' });
	const body = el('tbody');
	for (const idx of plain) {
		const field = el('input', {
			type: 'text', spellcheck: false, value: idx.unit ?? '',
			placeholder: inventory, className: 'ix-unit',
		});
		field.addEventListener('change', () => {
			try { ed.setMaterialUnit(project, idx.name, field.value); hooks.onChange?.(); }
			catch (e) { hooks.onStatus?.(e.message, 'warn'); field.value = idx.unit ?? ''; }
		});
		body.append(el('tr', {},
			el('th', { scope: 'row' }, idx.name),
			el('td', {}, field)));
	}
	table.append(body);
	box.append(table);
	return box;
}

/**
 * What the inventories are measured in.
 *
 * A property of the model rather than of the list, but this is where it
 * belongs: it is a fact about the radionuclides, and Ecolego keeps it on the
 * material model beside them (the catalogue’s decay unit, mirrored onto every
 * nuclide's own unit, which is how an .eco file carries it).
 *
 * The card says what the choice does, because the one thing it changes is
 * invisible until a chain is run: which decay constant multiplies a parent's
 * inventory in the ingrowth term.
 */
function renderDecayUnit(project, hooks) {
	const now = ed.decayUnit(project);
	const sel = el('select', { className: 'ix-unit-sel' });
	for (const [value, label] of [
		['Bq', 'Bq — an activity'],
		['mol', 'mol — an amount of substance'],
	]) {
		sel.append(el('option', { value, selected: value === now }, label));
	}
	sel.addEventListener('change', () => {
		try {
			const r = ed.setDecayUnit(project, sel.value);
			const said = r.relabelled.length
				? `, and ${r.relabelled.length} compartment`
					+ `${r.relabelled.length === 1 ? '' : 's'} relabelled`
				: '';
			const kept = r.left.length
				? `. ${r.left.length} compartment${r.left.length === 1 ? '' : 's'} `
					+ `keep${r.left.length === 1 ? 's' : ''} the unit written on `
					+ `${r.left.length === 1 ? 'it' : 'them'}: ${r.left.slice(0, 3).join(', ')}`
					+ (r.left.length > 3 ? '…' : '')
				: '';
			hooks.onStatus?.(
				`Inventories are now in ${r.unit}${said}${kept}.`
				+ (r.was !== r.unit
					? ` Ingrowth now uses the ${r.unit === 'mol' ? 'parent' : 'daughter'}'s `
						+ 'decay constant.'
					: ''),
				'info',
			);
		} catch (e) {
			hooks.onStatus?.(e.message, 'warn');
			sel.value = now;
		}
		hooks.onChange?.();
	});

	return card('Inventory unit',
		el('div', { className: 'ix-unit-row' }, sel),
		el('p', { className: 'hint' },
			'What a compartment indexed by these holds — and with it the ingrowth '
			+ 'term, which is the only number this changes. In ',
			el('b', {}, 'Bq'),
			' a daughter grows in at its ',
			el('b', {}, 'own'),
			' decay constant; in ',
			el('b', {}, 'mol'),
			' at its ',
			el('b', {}, 'parent’s'),
			', which is the classical Bateman equation for numbers of nuclei. '
			+ 'Both are exact for their own quantity — they are the same physics '
			+ 'written in A = λn — and the two coefficients differ by the ratio '
			+ 'of the half-lives, so this is not a setting to leave disagreeing '
			+ 'with what the numbers in the model mean. Nothing is converted: '
			+ 'use ',
			el('code', {}, 'bq2mole'),
			' and ',
			el('code', {}, 'mole2bq'),
			' in an equation that has to cross over.'));
}

// --- half-lives --------------------------------------------------------------

function renderHalfLives(project, material, enabled, timeUnit, hooks) {
	const nuclides = material.indices.map((i) => i.name);
	const box = card('Half-lives');

	if (!nuclides.length) {
		box.append(el('p', { className: 'hint' },
			'Add a nuclide above and it appears here with its half-life from ICRP '
			+ 'Publication 107. A name the database has never heard of starts '
			+ 'stable, and you set the half-life here.'));
		return box;
	}

	box.append(el('p', { className: 'hint' },
		`Half-lives in years; the solver converts them to the simulation's time `
		+ `unit (${timeUnit}). Either column can be typed into — they are one `
		+ 'value seen two ways, and setting one sets the other.'));

	const table = el('table', { className: 'ix-table' });
	table.append(el('thead', {}, el('tr', {},
		el('th', {}, 'Radionuclide'),
		el('th', {}, 'Half-life (years)'),
		el('th', { title: 'ln(2) ÷ the half-life, in the model’s own time unit. '
			+ 'Editable: setting it sets the half-life.' },
		`Decay constant (1/${timeUnit})`),
		el('th', {}, 'Source'),
		el('th', {}))));

	const body = el('tbody');
	for (const nuc of nuclides) {
		const overridden = ed.hasHalfLifeOverride(project, nuc);
		// One reader for a value that may be a number of years or the word
		// `stable`, which is how a non-decaying nuclide survives JSON.
		const effective = ed.halfLifeOf(project, nuc, HALF_LIVES);
		const off = !enabled.has(nuc);

		const input = el('input', {
			type: 'text', className: 'mono',
			value: fmtYears(effective),
			placeholder: HALF_LIVES[nuc] != null ? fmtYears(HALF_LIVES[nuc]) : 'required',
			spellcheck: false,
		});
		input.addEventListener('change', () => {
			const raw = input.value.trim();
			try {
				if (raw === '') {
					ed.setHalfLife(project, nuc, null);
				} else if (/^stable$/i.test(raw) || /^inf/i.test(raw)) {
					ed.setHalfLife(project, nuc, Infinity);
				} else {
					const v = Number(raw);
					if (!Number.isFinite(v)) throw new ed.EditError(`'${raw}' is not a number`);
					ed.setHalfLife(project, nuc, v);
				}
				hooks.onChange?.();
			} catch (e) {
				hooks.onStatus?.(e.message, 'warn');
				input.value = fmtYears(effective);
			}
		});

		const lam = effective != null && Number.isFinite(effective)
			? lambda(nuc, timeUnit, { [nuc]: effective })
			: 0;

		// The decay constant, and it is edited here rather than only shown.
		//
		// λ is the number that actually appears in the model -- it is what the
		// solver multiplies an inventory by, and what a report, a reviewer's
		// note or another code's input file quotes. Deriving it from a
		// half-life is one division; getting a half-life back out of it is the
		// same division and somebody doing it in their head at the wrong time
		// of day. So the column is a box.
		//
		// What is *stored* is still the half-life, in years, because that is
		// what the file format holds and what ICRP 107 is a table of. Typing a
		// λ sets the half-life it implies, and the half-life box beside it
		// shows the result — so the two are one value seen two ways, and there
		// is no second source of truth to fall out of step.
		const lamText = effective == null ? ''
			: Number.isFinite(effective) ? lam.toExponential(6) : '0';
		const lamBox = el('input', {
			type: 'text', className: 'mono',
			value: lamText,
			placeholder: effective == null ? 'or set λ' : '',
			spellcheck: false,
			title: `The decay constant, per ${timeUnit} — ln(2) divided by the `
				+ 'half-life in that unit. Type one here and the half-life beside it '
				+ 'follows; type 0 for a nuclide that does not decay.',
		});
		lamBox.addEventListener('change', () => {
			const raw = lamBox.value.trim();
			// Untouched, or tabbed through: a `change` that carries the value
			// this was rendered with must not write anything. The shown λ is
			// rounded, so acting on it would quietly replace an exact
			// half-life with one worked back from seven digits.
			if (raw === lamText) return;
			try {
				if (raw === '') {
					ed.setHalfLife(project, nuc, null);
				} else {
					const v = Number(raw);
					if (!Number.isFinite(v)) {
						throw new ed.EditError(`'${raw}' is not a decay constant`);
					}
					if (v < 0) {
						throw new ed.EditError('A decay constant cannot be negative — that '
							+ 'would be a nuclide growing rather than decaying.');
					}
					const years = halfLifeFromLambda(v, timeUnit);
					if (years == null) throw new ed.EditError(`'${raw}' is not a decay constant`);
					ed.setHalfLife(project, nuc, years);
				}
				hooks.onChange?.();
			} catch (e) {
				hooks.onStatus?.(e.message, 'warn');
				lamBox.value = lamText;
			}
		});

		const reset = el('button', {
			className: 'ix-reset', type: 'button',
			title: overridden
				? 'Clear this override and use the built-in value'
				: 'Not overridden',
			disabled: !overridden,
		}, '×');
		reset.addEventListener('click', () => {
			ed.setHalfLife(project, nuc, null);
			hooks.onChange?.();
		});

		body.append(el('tr', { className: off ? 'is-disabled' : '' },
			el('td', { className: 'ix-nuc' }, nuc,
				off ? el('span', { className: 'ix-off' }, ' (disabled)') : ''),
			el('td', {}, input),
			el('td', { className: 'ix-lambda' }, lamBox),
			el('td', { className: 'ix-src' },
				effective == null ? el('span', { className: 'ix-missing' }, 'missing')
					: overridden ? 'this model' : 'ICRP 107'),
			el('td', {}, reset)));
	}
	table.append(body);
	box.append(el('div', { className: 'ix-scroll' }, table));

	const missing = nuclides.filter((n) => ed.halfLifeOf(project, n, HALF_LIVES) == null);
	if (missing.length) {
		box.append(el('p', { className: 'ix-warn' },
			`No half-life for ${missing.join(', ')}. The model will not run until each `
			+ `has one — type a value above, or "stable".`));
	}

	box.append(el('p', { className: 'hint' },
		'An empty field falls back to ICRP 107, which is where every half-life '
		+ 'here comes from unless this model says otherwise. Type ',
		el('code', {}, 'stable'), ' for a nuclide that does not decay. A handful '
		+ 'of half-lives have been re-measured since ICRP 107 was published in '
		+ '2008 — Se-79 by 10% — so check any value the result turns on.'));
	return box;
}

// --- chains ------------------------------------------------------------------

function renderChains(project, material, enabled, hooks) {
	const box = card('Decay chains');

	const chains = ed.effectiveChains(project);
	const inModel = new Set(material.indices.map((i) => i.name));

	// Chains whose two members are both in the model are the ones that do
	// anything; the rest are carried along but inert.
	const active = chains.filter((c) => inModel.has(c[0]) && inModel.has(c[1]));
	const inactive = chains.length - active.length;

	// Where the pairs came from matters here: a model that says nothing gets
	// them worked out from ICRP 107 for exactly the nuclides it carries, and
	// they follow the list as it changes. The first edit to any of them writes
	// the whole set into the file, and from then on they are the model's own.
	const stated = !!project.chains;
	box.append(el('p', { className: 'hint' },
		stated
			? `${active.length} of ${chains.length} pair(s) apply to this model, `
				+ 'and they are this model\u2019s own \u2014 written into the file '
				+ 'when one of them was first edited, so they no longer follow the '
				+ 'radionuclide list.'
			: `${active.length} pair(s), worked out from ICRP 107 for the nuclides `
				+ 'this model carries: the published chains collapsed onto them, so '
				+ 'the branching is the total probability of reaching each one '
				+ 'through the short-lived members left out. Add or remove a '
				+ 'nuclide and they follow.'));
	if (inactive) {
		box.append(el('p', { className: 'hint' },
			`${inactive} more name a nuclide this model does not carry, so they do `
			+ 'nothing. Ingrowth needs both parent and daughter present, and both '
			+ 'enabled.'));
	}

	// The table edits one branching ratio at a time, which is the one thing a
	// table is the right shape for; the picture answers the question the table
	// cannot, which is what shape the chains are. They belong beside each
	// other -- table left, picture taking whatever width is left over, and the
	// picture wrapping under the table when there is not room for both.
	const frame = active.length ? el('div', { className: 'ix-chain-graph' }) : null;
	if (frame) {
		fitGraph(frame, (width) => chainGraph(
			material.indices.map((i) => i.name),
			chains,
			{
				enabled,
				width,
				halfLife: (n) => fmtSpan(ed.halfLifeOf(project, n, HALF_LIVES)),
				onPick: (n) => hooks.onStatus?.(`${n} — half-life `
					+ `${fmtYears(ed.halfLifeOf(project, n, HALF_LIVES))} years`, 'info'),
			},
		));
	}
	// Everything that edits goes in the left column, and straight into the
	// card when there is no picture for it to sit beside.
	const edits = frame ? el('div', { className: 'ix-chain-edit' }) : box;
	if (frame) box.append(el('div', { className: 'ix-chain-split' }, edits, frame));

	if (active.length) {
		const table = el('table', { className: 'ix-table' });
		table.append(el('thead', {}, el('tr', {},
			el('th', {}, 'Parent'),
			el('th', {}, 'Daughter'),
			el('th', {}, 'Branching ratio'),
			el('th', {}, 'Applies'),
			el('th', {}))));

		const body = el('tbody');
		for (const [parent, daughter, ratio] of active) {
			const live = enabled.has(parent) && enabled.has(daughter);

			const input = el('input', {
				type: 'text', className: 'mono', value: String(ratio ?? 1), spellcheck: false,
			});
			input.addEventListener('change', () => {
				try {
					ed.setDecayRatio(project, parent, daughter, input.value);
					hooks.onChange?.();
				} catch (e) {
					hooks.onStatus?.(e.message, 'warn');
					input.value = String(ratio ?? 1);
				}
			});

			const del = el('button', {
				className: 'ix-reset', type: 'button', title: 'Remove this chain',
			}, '×');
			del.addEventListener('click', () => {
				try {
					ed.removeDecayPair(project, parent, daughter);
					hooks.onChange?.();
				} catch (e) { hooks.onStatus?.(e.message, 'warn'); }
			});

			body.append(el('tr', { className: live ? '' : 'is-disabled' },
				el('td', { className: 'ix-nuc' }, parent),
				el('td', { className: 'ix-nuc' }, daughter),
				el('td', {}, input),
				// Short, because this column shares a row with the drawing
				// now; the reason is on the cell rather than in it.
				el('td', {
					className: 'ix-src',
					title: live ? '' : 'one of the two nuclides is disabled',
				}, live ? 'yes' : 'no'),
				el('td', {}, del)));
		}
		table.append(body);
		edits.append(el('div', { className: 'ix-scroll' }, table));
	}

	// --- add a pair ---
	const options = material.indices.map((i) => i.name);
	if (options.length >= 2) {
		const parentSel = el('select', {});
		const daughterSel = el('select', {});
		for (const sel of [parentSel, daughterSel]) {
			for (const n of options) sel.append(el('option', { value: n }, n));
		}
		daughterSel.value = options[1];
		const ratioInput = el('input', {
			type: 'text', className: 'mono', value: '1', spellcheck: false,
		});
		const addBtn = el('button', { type: 'button' }, 'Add chain');
		addBtn.addEventListener('click', () => {
			try {
				ed.addDecayPair(project,
					parentSel.value, daughterSel.value, ratioInput.value);
				hooks.onChange?.();
				hooks.onStatus?.(
					`${parentSel.value} now decays to ${daughterSel.value}.`, 'info');
			} catch (e) { hooks.onStatus?.(e.message, 'warn'); }
		});
		edits.append(el('div', { className: 'ix-pair-add' },
			el('label', {}, el('span', {}, 'parent'), parentSel),
			el('label', {}, el('span', {}, 'daughter'), daughterSel),
			el('label', {}, el('span', {}, 'ratio'), ratioInput),
			addBtn));
	} else {
		edits.append(el('p', { className: 'hint' },
			'Two nuclides of one chain is all it takes: add U-238 and Pb-210 and '
			+ 'the pair between them appears here, with the branching that '
			+ 'reaches it. Browse ICRP 107 above to pick a whole chain at once.'));
	}

	if (inactive) {
		edits.append(el('details', { className: 'ix-details' },
			el('summary', {}, `${inactive} chain(s) not in this model`),
			el('p', { className: 'hint' },
				'Carried in the project but inert, because one or both nuclides are '
				+ 'absent. Add the missing nuclide above and the chain starts '
				+ 'applying.'),
			el('p', { className: 'ix-inactive' },
				chains
					.filter((c) => !(inModel.has(c[0]) && inModel.has(c[1])))
					.map((c) => `${c[0]} → ${c[1]}`)
					.join(', '))));
	}
	return box;
}
