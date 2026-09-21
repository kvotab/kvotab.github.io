/**
 * The completion popup for equation fields.
 *
 * Everything about *what* may be written at the caret is in
 * ../domain/complete.js, which is a pure function of the model and the text.
 * This file is the list: where it goes, what a row looks like, and which keys
 * move through it.
 *
 * One popup for the whole application, moved to whichever field is being typed
 * in. It is parented to the field's own `<dialog>` when there is one -- a
 * modal dialog makes the rest of the document inert, so a popup hanging off
 * `<body>` would be there and unclickable -- and positioned `fixed`, which is
 * what gets it out of `.modal`'s `overflow: hidden` without needing a portal.
 *
 * The list opens as you type rather than on a key, which is the one place this
 * departs from Ecolego (its equation editor opens an unfiltered list of every
 * name in the model on the space bar). Ctrl-Space still opens it against
 * whatever is under the caret, including nothing, for when you want to see
 * what is available rather than to finish a word you have started.
 */

import {
	completionsAt, applyCompletion, searchCandidates, rankCompletions,
} from '../domain/complete.js';
import * as db from '../domain/decaydb.js';
import { blockIcon } from './icons.js';
import { summarise } from './summary.js';
import { symbolNodes } from './symbol.js';
import { hasSymbol } from '../domain/symbol.js';
import { el } from './parts.js';

/** How far the list may grow before it scrolls. */
const MAX_HEIGHT = 280;
/** How wide it is, whatever the field's own width. */
const MIN_WIDTH = 300;

/** The one popup, built on first use. */
let pop = null;
let list = null;
let foot = null;

/** What is open: the field, how to ask it for candidates, and where we are. */
let live = null;

function build() {
	if (pop) return;
	list = el('div', { className: 'ac-list', role: 'listbox', id: 'ac-list' });
	foot = el('div', { className: 'ac-foot' });
	pop = el('div', { className: 'ac-pop' }, list, foot);
	pop.hidden = true;
	// The field must keep focus when a row is clicked, or the click lands on a
	// popup that the blur has already taken away.
	pop.addEventListener('mousedown', (ev) => ev.preventDefault());
	document.body.append(pop);
	// The list is anchored to a field that can move underneath it.
	window.addEventListener('scroll', () => { if (live) place(); }, true);
	window.addEventListener('resize', () => { if (live) place(); });
}

/** The glyph at the head of a row: what kind of thing this is. */
function markFor(item) {
	if (item.type === 'block') return blockIcon(item.kind);
	if (item.type === 'index') return el('span', { className: 'ac-glyph' }, '[ ]');
	// A name from a run's outputs: a block's, or an index's.
	if (item.type === 'search') {
		return item.what === 'block'
			? blockIcon(item.kind)
			: el('span', { className: 'ac-glyph' }, '[ ]');
	}
	// A nuclide's mark is its atomic number, which is the one thing about it
	// that orders the list and is not already in its name.
	if (item.type === 'nuclide') {
		return el('span', { className: 'ac-glyph ac-glyph-z' }, String(item.z));
	}
	return el('span', { className: 'ac-glyph ac-glyph-fn' }, 'ƒ');
}

/** The part of a label the typed word matched, marked. */
function highlight(label, word) {
	if (!word) return [document.createTextNode(label)];
	const at = label.toLowerCase().indexOf(word.toLowerCase());
	if (at < 0) return [document.createTextNode(label)];
	return [
		document.createTextNode(label.slice(0, at)),
		el('mark', {}, label.slice(at, at + word.length)),
		document.createTextNode(label.slice(at + word.length)),
	];
}

/** The dim text on the right of a row. */
function detailFor(item) {
	if (item.type === 'block') {
		return item.unit || (hasSymbol(item.block) ? '' : item.kind.replace(/_/g, ' '));
	}
	if (item.type === 'index') return item.list;
	if (item.type === 'nuclide') return item.halfLife;
	if (item.type === 'search') return item.detail;
	return item.help.category;
}

/** The line under the list, describing whichever row is active. */
function describe(item) {
	foot.replaceChildren();
	if (!item) return;
	if (item.type === 'function') {
		foot.append(
			el('code', { className: 'ac-sig' }, item.help.signature),
			el('span', { className: 'ac-say' }, item.help.alias
				? `${item.help.summary} — the same function as ${item.help.alias}`
				: item.help.summary),
		);
		return;
	}
	if (item.type === 'index') {
		foot.append(el('span', { className: 'ac-say' },
			`An index of ${item.list}.`));
		return;
	}
	if (item.type === 'search') {
		foot.append(el('code', { className: 'ac-sig' }, item.label));
		foot.append(el('span', { className: 'ac-say' }, item.say));
		return;
	}
	// A nuclide's line is what a modeller needs to decide: how long it lives,
	// and what it turns into. The same footer the functions get, because
	// choosing between Cs-134 and Cs-137 is the same kind of choice as
	// choosing between `min` and `max` -- the name alone does not settle it.
	if (item.type === 'nuclide') {
		foot.append(el('code', { className: 'ac-sig' }, item.name));
		foot.append(el('span', { className: 'ac-say' },
			[`${item.element} · Z = ${item.z}`, `half-life ${item.halfLife}`]
				.join(' · ')));
		if (item.decays) foot.append(el('span', { className: 'ac-note' }, item.decays));
		return;
	}
	const bits = [item.kind.replace(/_/g, ' ')];
	const sum = summarise(item.collection, item.block);
	if (sum) bits.push(sum);
	if (item.block.unit) bits.push(item.block.unit);
	foot.append(el('code', { className: 'ac-sig' }, item.name));
	if (hasSymbol(item.block)) {
		foot.append(el('span', { className: 'ac-symbol' }, ...symbolNodes(item.block.symbol)));
	}
	foot.append(el('span', { className: 'ac-say' }, bits.join(' · ')));
	if (item.block.comment) {
		foot.append(el('span', { className: 'ac-note' }, item.block.comment));
	}
}

function setActive(i) {
	if (!live) return;
	const rows = list.children;
	if (!rows.length) return;
	live.active = Math.max(0, Math.min(i, rows.length - 1));
	for (let k = 0; k < rows.length; k++) {
		const on = k === live.active;
		rows[k].classList.toggle('is-on', on);
		rows[k].setAttribute('aria-selected', on ? 'true' : 'false');
	}
	const row = rows[live.active];
	row.scrollIntoView({ block: 'nearest' });
	live.input.setAttribute('aria-activedescendant', row.id);
	describe(live.result.items[live.active]);
}

/** Below the field, or above it when there is no room below. */
function place() {
	if (!live) return;
	const r = live.input.getBoundingClientRect();
	const w = Math.min(Math.max(r.width, MIN_WIDTH), window.innerWidth - 16);
	pop.style.width = `${w}px`;
	pop.style.left = `${Math.max(8, Math.min(r.left, window.innerWidth - w - 8))}px`;
	// Measured rather than assumed: the list is as tall as its rows until it
	// hits the cap, and a four-row list should not be placed as if it were
	// twenty.
	const h = Math.min(pop.offsetHeight || MAX_HEIGHT, MAX_HEIGHT + 60);
	const below = window.innerHeight - r.bottom - 8;
	if (below < h && r.top > below) pop.style.top = `${Math.max(8, r.top - h - 2)}px`;
	else pop.style.top = `${r.bottom + 2}px`;
}

function render() {
	const { result, word } = live;
	list.replaceChildren();
	result.items.forEach((item, i) => {
		const row = el('div', {
			className: 'ac-item', role: 'option', id: `ac-item-${i}`,
			'aria-selected': 'false',
		},
		markFor(item),
		el('span', { className: 'ac-label' }, ...highlight(item.label, word)),
		el('span', { className: 'ac-detail' }, detailFor(item)));
		row.addEventListener('mouseenter', () => setActive(i));
		row.addEventListener('click', () => accept(i));
		list.append(row);
	});
	if (result.total > result.items.length) {
		list.append(el('div', { className: 'ac-more' },
			`${result.total - result.items.length} more — keep typing`));
	}
	live.active = 0;
	setActive(0);
}

function show() {
	build();
	const parent = live.input.closest('dialog') ?? document.body;
	if (pop.parentNode !== parent) parent.append(pop);
	pop.hidden = false;
	render();
	place();
	live.input.setAttribute('aria-expanded', 'true');
	live.input.setAttribute('aria-controls', 'ac-list');
}

/**
 * Whether the popup is open on a given field.
 *
 * For a field whose own Enter means something -- "add this index" -- which has
 * to give way while the list is up: the first Enter takes the highlighted
 * nuclide, the second adds it. Without this the field would commit whatever
 * fragment had been typed and the completion would land on an empty box.
 */
export function completionIsOpen(input = null) {
	if (!live || pop?.hidden) return false;
	return input ? live.input === input : true;
}

export function closeCompletion() {
	if (!live) return;
	live.input.setAttribute('aria-expanded', 'false');
	live.input.removeAttribute('aria-activedescendant');
	live = null;
	if (pop) pop.hidden = true;
}

/**
 * Take a row: the word under the caret becomes the chosen text, and the caret
 * lands where the next thing to type goes -- inside a function's parentheses,
 * after a closed bracket.
 *
 * The field is not committed here. An equation is usually half-written at the
 * moment a name is finished, and these fields commit on `change`, which is
 * what leaving the field or pressing Enter against a closed list does -- the
 * same as before this existed. `_acDirty` is the one thing that has to be
 * remembered: a value set by script is not user input, so a browser is within
 * its rights never to raise `change` for it, and the edit would be lost on the
 * way out. The blur handler makes up the difference only when the field's own
 * `change` did not arrive.
 */
function accept(i) {
	if (!live) return;
	const item = live.result.items[i ?? live.active];
	if (!item) return;
	const { input, result } = live;
	const { text, caret } = applyCompletion(input.value, result, item);
	input.value = text;
	input.setSelectionRange(caret, caret);
	input._acDirty = true;
	closeCompletion();
	// Anything listening for the value to change should hear it -- but not
	// this, or finishing a word would immediately offer to finish it again.
	input._acSkip = true;
	input.dispatchEvent(new Event('input', { bubbles: true }));
	input._acSkip = false;
}

/** Ask for candidates at the caret and either open, update or close. */
function refresh(input, auto) {
	const look = input._acLook;
	if (!look) return;
	const caret = input.selectionStart ?? input.value.length;
	const result = look(input.value, caret);
	// Opening on its own accord needs something to have been typed; asked for
	// explicitly, an empty word means "show me everything". A bracket is the
	// exception, because typing `[` is already the whole request: an index
	// name is the one thing in an equation nobody can be expected to have
	// memorised -- `[F.18:00_51_FORSMARK]` -- and there is nothing else it
	// could be the start of.
	const enough = result && (result.word || result.kind === 'index');
	if (!result || (auto && !enough)) { closeCompletion(); return; }
	// Back to the top on every keystroke: the list is a different list, and
	// leaving the highlight on row seven of the last one is how you commit to
	// something you never read.
	live = { input, result, word: result.word, active: 0 };
	show();
}

/**
 * Gives a text field completion over an equation.
 *
 * @param {HTMLInputElement} input
 * @param {(text: string, caret: number) => object|null} look normally a call
 *   to `completionsAt` with the project and the block this field belongs to
 */
export function attachCompletion(input, look) {
	input._acLook = look;
	input.setAttribute('role', 'combobox');
	input.setAttribute('aria-expanded', 'false');
	input.setAttribute('aria-autocomplete', 'list');
	// The browser's own suggestions are a list of things typed into other
	// forms, over the top of this one.
	input.autocomplete = 'off';
	// The list opens on its own once a word is started, so this is only for
	// the other half -- asking to see what is available before typing. Fields
	// that already say something about themselves keep what they say.
	if (!input.title) {
		input.title = 'Ctrl-Space lists the blocks and functions that can go here';
	}

	input.addEventListener('input', () => {
		if (input._acSkip) return;
		refresh(input, true);
	});
	input.addEventListener('change', () => { input._acDirty = false; });
	input.addEventListener('blur', () => {
		closeCompletion();
		// `change` is fired before `blur` where the browser fires it at all,
		// so reaching here still dirty means it is not coming.
		if (!input._acDirty) return;
		input._acDirty = false;
		input.dispatchEvent(new Event('change', { bubbles: true }));
	});
	input.addEventListener('keydown', (ev) => {
		const open = live && live.input === input;

		if ((ev.ctrlKey || ev.metaKey) && ev.key === ' ') {
			ev.preventDefault();
			refresh(input, false);
			return;
		}
		if (!open) {
			// Down against a closed list is the other way of asking for it.
			if (ev.key === 'ArrowDown' && !ev.altKey) {
				ev.preventDefault();
				refresh(input, false);
			}
			return;
		}
		switch (ev.key) {
			case 'ArrowDown': ev.preventDefault(); setActive(live.active + 1); break;
			case 'ArrowUp': ev.preventDefault(); setActive(live.active - 1); break;
			case 'PageDown': ev.preventDefault(); setActive(live.active + 8); break;
			case 'PageUp': ev.preventDefault(); setActive(live.active - 8); break;
			case 'Home': ev.preventDefault(); setActive(0); break;
			case 'End': ev.preventDefault(); setActive(live.result.items.length - 1); break;
			case 'Enter':
			case 'Tab':
				ev.preventDefault();
				accept();
				break;
			case 'Escape':
				// Stopped here, or the dialog this field is in would take it
				// as "close the dialog" and throw away the popup and the form
				// together.
				ev.preventDefault();
				ev.stopPropagation();
				closeCompletion();
				break;
			default:
		}
	});
	// Clicking elsewhere in the same field is a new caret, and usually a
	// different word.
	input.addEventListener('click', () => { if (live?.input === input) refresh(input, true); });
	return input;
}

/**
 * The usual `look` for a block's equation: everything nameable from the
 * block's own sub-system, minus the block itself.
 *
 * The project is read at the moment the list opens rather than captured, so a
 * field left focused while a block is added elsewhere offers the new one.
 */
export function equationLook(project, ownerName, system, opts = {}) {
	return (text, caret) => completionsAt(project, {
		text, caret, system, owner: ownerName, ...opts,
	});
}

/**
 * The `look` for the chart's search box: the names in the run's outputs.
 *
 * The box matches anywhere in a label, so what it offers is the names a label
 * is made of -- blocks and indices -- rather than whole labels, of which a
 * landscape model has thousands and no two differ by more than an index. The
 * whole box is the word: there is one thing being typed. A pattern with a
 * star or a question mark in it is the box's own language, and completes to
 * nothing.
 *
 * @param {() => Array<object>} outputs read when the list opens, since the
 *   results change under a field that stays on screen
 */
export function searchLook(outputs, { limit = 80 } = {}) {
	return (text) => {
		const src = String(text ?? '');
		const word = src.trim();
		if (/[*?]/.test(word)) return null;
		const { items, total } = rankCompletions(word, searchCandidates(outputs()), limit);
		if (!items.length) return null;
		return { start: 0, end: src.length, word, kind: 'search', items, total };
	};
}

/**
 * The nuclides a typed fragment could mean, best first.
 *
 * Ranked the way the equation list is: what the word *starts* beats what
 * merely contains it, and a shorter name beats a longer one that matched the
 * same way. On top of that, two things particular to nuclides:
 *
 *  - the separator is optional and so is its position, so `cs137`, `cs-137`
 *    and `Cs 137` are one query. The name is matched with the hyphen taken
 *    out, which also makes `137` match the mass number of everything.
 *  - an element typed in words -- `caesium`, `plutonium` -- is a query for its
 *    isotopes, which is how the database's own page is arranged and how anyone
 *    who does not remember whether it is Cs or Ce gets to the right list.
 *
 * Stable nuclides are left out. They are in the database because chains end on
 * them, but a compartment model does not integrate something that does not
 * decay, and offering Pb-206 among the leads is offering a mistake.
 */
function matchNuclides(word, { limit = 60, exclude = new Set() } = {}) {
	const q = String(word ?? '').trim().toLowerCase();
	const flat = q.replace(/[\s-]/g, '');
	// An element named in words, which is a query for all of its isotopes.
	const byWord = q.length >= 3
		? new Set(db.elements()
			.filter((e) => e.name.toLowerCase().startsWith(q))
			.map((e) => e.symbol))
		: null;

	const scored = [];
	for (const name of db.allUnstable()) {
		if (exclude.has(name)) continue;
		const low = name.toLowerCase();
		const bare = low.replace('-', '');
		let rank;
		if (!flat) rank = 4;                              // Ctrl-Space: all of them
		else if (bare.startsWith(flat)) rank = 0;         // Cs-13 -> Cs-137
		else if (byWord?.has(db.elementOf(name))) rank = 1;
		else if (bare.includes(flat)) rank = 2;           // 137 -> Cs-137
		else continue;
		scored.push({ name, rank });
	}
	// Within a rank, the database's own order: by element, then by mass
	// number. `cs` is then a caesium isotope list read the way an isotope list
	// is read, rather than an alphabetical accident.
	const order = new Map(db.allUnstable().map((n, i) => [n, i]));
	scored.sort((a, b) => a.rank - b.rank || order.get(a.name) - order.get(b.name));

	const total = scored.length;
	const items = scored.slice(0, limit).map(({ name }) => {
		const n = db.nuclide(name);
		return {
			type: 'nuclide',
			name,
			label: name,
			insert: name,
			caret: 0,
			z: n.z,
			element: db.element(db.elementOf(name))?.name ?? db.elementOf(name),
			halfLife: n.text,
			decays: n.progeny
				.map((k) => `${k.mode} to ${k.name}`
					+ (k.branching < 0.999 ? ` (${(k.branching * 100).toPrecision(3)}%)` : ''))
				.join(', '),
		};
	});
	items.total = total;
	return items;
}

/**
 * Gives a field completion over the radionuclide database.
 *
 * The same popup, the same keys, the same behaviour -- type and it opens,
 * Ctrl-Space shows everything, Tab or Enter takes the highlighted one -- but
 * the candidates are the 1,252 radionuclides of ICRP 107 rather than the
 * blocks of this model. Which is the point: adding `Cs-137` to a nuclide list
 * is the same act as writing `Kd_ter` into an equation, and it was the only
 * name-typing field in the application that did not work like one.
 *
 * The whole field is the word, since a nuclide list holds one name per entry:
 * accepting replaces everything, and there is no partial word to preserve.
 *
 * Matching is deliberately generous, because the three things anyone knows
 * about a nuclide are its element, its mass number and its name, and they
 * arrive in any order: `cs` finds the caesiums, `137` finds everything with
 * that mass number, `caesium` finds them by the element's name in words, and
 * `cs137` and `cs-137` both find Cs-137.
 *
 * @param {{exclude?: Iterable<string>, limit?: number}} [opts] `exclude` names
 *   the ones already in the list, which are dropped rather than offered again.
 */
export function nuclideLook(opts = {}) {
	const limit = opts.limit ?? 60;
	return (text, caret) => {
		const src = String(text ?? '');
		// The caret is irrelevant: there is one word and it is all of it.
		const word = src.trim();
		const already = new Set(opts.exclude ?? []);
		const items = matchNuclides(word, { limit, exclude: already });
		if (!items.length) return null;
		return {
			start: 0, end: src.length, word, kind: 'nuclide', items,
			total: items.total ?? items.length,
		};
	};
}
