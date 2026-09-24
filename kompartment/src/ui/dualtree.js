/**
 * Choosing some of many named things, as two trees.
 *
 * What is not chosen is on the left and what is chosen is on the right, each
 * the shape the left panel's tree has -- sub-systems as the spine, the kind of
 * a block as its icon -- with a search and a kind filter of its own, because
 * the question "which of these three thousand blocks" is answered by finding
 * them, and a model of that size is found by sub-system and by name. A list
 * of tick boxes answered it for twenty blocks and not for the models this
 * tool was built to read.
 *
 * Things move the ways a list of this kind is expected to move them: dragged
 * from one tree to the other, double-clicked, the buttons between the trees
 * (the selection, or everything shown), Enter, and the right-click menu. A
 * selection is made the way the left panel makes one -- click, ⌘ or Ctrl to
 * add and remove, shift for a range -- and a sub-system selected stands for
 * every block in it that the tree is showing. **What is shown is what
 * moves**: with the search set to `*_out`, a sub-system moves only its `_out`
 * blocks, and *everything shown* is everything the search and filter leave.
 *
 * The component redraws only itself. Typing in a search box, opening a
 * sub-system or selecting a row does not rebuild the dialog around it, which
 * would take the caret out of the box being typed in; the dialog is told after
 * a move, through `onChange`, and redraws what depends on the choice.
 */

import { el } from './parts.js';
import { blockIcon } from './icons.js';
import { openMenu } from './menu.js';
import { nameMatcher, KIND_LABEL } from '../domain/edit.js';

/** Rows drawn in one tree at once. The search is how the rest are reached. */
export const MOST_ROWS = 600;

/** What the two trees remember between rebuilds of the dialog around them. */
export function dualTreeState() {
	const side = () => ({ query: '', kind: '', open: new Set(), sel: new Set(), anchor: null });
	return { sides: [side(), side()], group: false };
}

/** Node keys: a block, a sub-system, a kind heading inside a sub-system. */
const itemKey = (key) => `i\u0000${key}`;
const systemKey = (path) => `s\u0000${path}`;
const groupKey = (path, kind) => `g\u0000${path}\u0000${kind}`;

const parentOf = (path) => (path.includes('.') ? path.slice(0, path.lastIndexOf('.')) : '');
const ORDER = new Intl.Collator(undefined, { sensitivity: 'base', numeric: true });

/**
 * One side's tree: the sub-systems and blocks its items make, narrowed by its
 * search and filter, and what every node stands for. Exported for the tests;
 * the component is its only other reader.
 *
 * @returns {{root, filtering: boolean, cover: Map<string, string[]>}}
 */
export function build(items, ui, group) {
	const matches = nameMatcher(ui.query);
	const filtering = !!String(ui.query ?? '').trim() || !!ui.kind;
	const byPath = new Map();
	const at = (path) => {
		const found = byPath.get(path);
		if (found) return found;
		const node = {
			path, name: path.slice(path.lastIndexOf('.') + 1), systems: [], items: [], deep: [],
		};
		byPath.set(path, node);
		if (path) at(parentOf(path)).systems.push(node);
		return node;
	};
	const root = at('');
	for (const it of items) {
		if (ui.kind && it.kind !== ui.kind) continue;
		const cut = it.name.lastIndexOf('.');
		const leaf = cut >= 0 ? it.name.slice(cut + 1) : it.name;
		if (!matches(leaf) && !matches(it.name)) continue;
		at(cut >= 0 ? it.name.slice(0, cut) : '').items.push({ it, leaf });
	}
	// What each node stands for: the keys of the items under it that the tree
	// is showing. Worked out once per draw, since a selection is resolved to
	// these and a move is made of them.
	const cover = new Map();
	const finish = (node) => {
		for (const s of node.systems) finish(s);
		node.systems = node.systems.filter((s) => s.deep.length);
		node.systems.sort((a, b) => ORDER.compare(a.name, b.name));
		node.items.sort(group
			? (a, b) => ORDER.compare(a.it.kind ?? '', b.it.kind ?? '') || ORDER.compare(a.leaf, b.leaf)
			: (a, b) => ORDER.compare(a.leaf, b.leaf));
		node.deep = [...node.systems.flatMap((s) => s.deep), ...node.items.map((x) => x.it.key)];
		if (node.path) cover.set(systemKey(node.path), node.deep);
		for (const x of node.items) cover.set(itemKey(x.it.key), [x.it.key]);
		if (group) {
			for (const x of node.items) {
				const g = groupKey(node.path, x.it.kind ?? '');
				if (!cover.has(g)) cover.set(g, []);
				cover.get(g).push(x.it.key);
			}
		}
	};
	finish(root);
	return { root, filtering, cover };
}

/**
 * Draws the two trees into `host`.
 *
 * @param {HTMLElement} host
 * @param {object} o
 * @param {Array<{key: string, name: string, kind?: string, unit?: string, count?: number, title?: string}>} o.items
 *   `name` is qualified: `NearField.Buffer` is `Buffer` in the sub-system `NearField`
 * @param {Set<string>} o.chosen   the keys on the right, edited in place
 * @param {object} o.ui            from `dualTreeState()`, kept by the caller across rebuilds
 * @param {[string, string]} [o.titles]  what the two sides are called
 * @param {string} [o.noun]        what one item is, for the counts
 * @param {() => void} [o.onChange]  after anything has moved
 * @returns {{picked: number, total: number}}
 */
export function renderDualTree(host, {
	items, chosen, ui, titles = ['Not chosen', 'Chosen'], noun = 'block', onChange = null,
}) {
	const byKey = new Map(items.map((it) => [it.key, it]));
	const kinds = [...new Set(items.map((it) => it.kind).filter(Boolean))].sort();
	const plural = (n) => `${n.toLocaleString()} ${noun}${n === 1 ? '' : 's'}`;
	const on = (s) => items.filter((it) => (chosen.has(it.key) ? 1 : 0) === s);

	// What the last draw of each side built, and the rows it drew in order.
	const built = [null, null];
	const rows = [[], []];
	let dragging = null;

	const frame = el('div', { className: 'dual' });
	const sides = [0, 1].map((s) => sideFrame(s));
	const moves = el('div', { className: 'dual-moves' });
	frame.append(sides[0].root, moves, sides[1].root);
	const group = el('input', { type: 'checkbox', checked: ui.group });
	group.addEventListener('change', () => { ui.group = group.checked; drawAll(); });
	host.append(frame, el('label', { className: 'dual-foot', title: 'Headings for each kind of block '
		+ 'inside every sub-system, as the left panel can have them' }, group, 'Group by type'));

	const button = (text, label, act) => {
		const b = el('button', { type: 'button', className: 'ghost dual-move', title: label, 'aria-label': label }, text);
		b.addEventListener('click', act);
		return b;
	};
	const toRight = button('›', `Move what is selected on the left to ${titles[1]}`, () => moveSelected(0));
	const allRight = button('»', `Move everything shown on the left to ${titles[1]}`, () => moveShown(0));
	const toLeft = button('‹', `Move what is selected on the right back to ${titles[0]}`, () => moveSelected(1));
	const allLeft = button('«', `Move everything shown on the right back to ${titles[0]}`, () => moveShown(1));
	moves.append(toRight, allRight, toLeft, allLeft);

	function sideFrame(s) {
		const u = ui.sides[s];
		const count = el('span', { className: 'dual-count' });
		const search = el('input', {
			type: 'search', className: 'dual-search', value: u.query,
			placeholder: 'Find — try C*_out', 'aria-label': `Search ${titles[s]}`,
		});
		search.addEventListener('input', () => { u.query = search.value; drawSide(s); updateButtons(); });
		const kind = el('select', { className: 'dual-kind', 'aria-label': `Kinds in ${titles[s]}` });
		kind.append(el('option', { value: '' }, 'All kinds'));
		for (const k of kinds) {
			kind.append(el('option', { value: k, selected: u.kind === k }, KIND_LABEL[k] ?? k.replace(/_/g, ' ')));
		}
		kind.addEventListener('change', () => { u.kind = kind.value; drawSide(s); updateButtons(); });
		const tree = el('div', {
			className: 'tree dual-tree', role: 'tree', 'aria-multiselectable': 'true',
			'aria-label': titles[s],
		});
		wireKeys(s, tree);
		wireDrop(s, tree);
		tree.addEventListener('contextmenu', (ev) => {
			ev.preventDefault();
			menu(s, ev);
		});
		tree.addEventListener('click', (ev) => {
			// A click below the last row selects nothing, as it does in any list.
			if (ev.target.closest('.trow')) return;
			u.sel.clear();
			u.anchor = null;
			markSelection(s);
			updateButtons();
		});
		const root = el('div', { className: 'dual-side' },
			el('div', { className: 'dual-head' }, el('span', { className: 'dual-title' }, titles[s]), count),
			el('div', { className: 'dual-tools' }, search, kind),
			tree);
		return { root, tree, count };
	}

	/** Every item key a side's selection stands for, in the tree as it is shown. */
	function covered(s) {
		const out = new Set();
		for (const k of ui.sides[s].sel) for (const key of built[s]?.cover.get(k) ?? []) out.add(key);
		return out;
	}

	function drawSide(s) {
		const u = ui.sides[s];
		const b = build(on(s), u, ui.group);
		built[s] = b;
		const { tree, count } = sides[s];
		const focused = tree.contains(document.activeElement) ? document.activeElement.dataset?.node : null;
		const scrolled = tree.scrollTop;
		tree.replaceChildren();
		rows[s] = [];
		// A selection of nodes that are no longer here -- moved, or searched
		// away -- is dropped, so what the buttons say is what they would move.
		for (const k of [...u.sel]) if (!b.cover.has(k)) u.sel.delete(k);
		let hidden = 0;
		const expanded = (key) => b.filtering || u.open.has(key);

		const row = (depth, spec) => {
			if (rows[s].length >= MOST_ROWS) { hidden += spec.weight ?? 1; return null; }
			const node = el('div', { className: `trow${spec.cls ? ` ${spec.cls}` : ''}`, role: 'treeitem', tabIndex: -1 });
			node.dataset.node = spec.key;
			node.setAttribute('aria-level', String(depth));
			node.style.paddingLeft = `${4 + (depth - 1) * 13}px`;
			node.style.setProperty('--depth', String(depth));
			if (spec.expandable) node.setAttribute('aria-expanded', spec.open ? 'true' : 'false');
			const twisty = el('span', { className: `twisty${spec.expandable ? '' : ' is-leaf'}`, 'aria-hidden': 'true' },
				spec.expandable ? '▸' : '');
			if (spec.expandable) {
				twisty.addEventListener('click', (ev) => {
					ev.stopPropagation();
					toggle(s, spec.key, !spec.open);
				});
			}
			node.append(twisty, blockIcon(spec.kind), el('span', { className: 'tname' }, spec.name));
			if (spec.sub) node.append(el('span', { className: 'tsub' }, spec.sub));
			if (spec.count != null) node.append(el('span', { className: 'tcount' }, spec.count));
			if (spec.title) node.title = spec.title;
			node.addEventListener('click', (ev) => pick(s, spec.key, ev));
			node.addEventListener('dblclick', (ev) => {
				ev.preventDefault();
				// A block goes across; a heading opens or closes, which is what
				// double-clicking one does everywhere else.
				if (spec.expandable) toggle(s, spec.key, !spec.open);
				else moveKeys(s, b.cover.get(spec.key) ?? []);
			});
			node.addEventListener('contextmenu', (ev) => {
				ev.preventDefault();
				ev.stopPropagation();
				// About this row, unless it is part of the selection -- the rule
				// the left panel follows.
				if (!u.sel.has(spec.key)) {
					u.sel = new Set([spec.key]);
					u.anchor = spec.key;
					markSelection(s);
				}
				menu(s, ev);
			});
			wireDrag(s, node, spec.key);
			tree.append(node);
			rows[s].push({ el: node, key: spec.key, depth, expandable: !!spec.expandable, open: !!spec.open });
			return node;
		};

		const addItem = (x, depth) => {
			const it = x.it;
			row(depth, {
				key: itemKey(it.key),
				kind: it.kind,
				name: x.leaf,
				sub: it.unit || '',
				count: (it.count ?? 1) > 1 ? `×${it.count.toLocaleString()}` : null,
				cls: 'trow-block',
				title: it.title ?? `${it.name}${it.kind ? ` — ${(KIND_LABEL[it.kind] ?? it.kind).toLowerCase()}` : ''}`
					+ ((it.count ?? 1) > 1 ? `, ${it.count.toLocaleString()} series` : ''),
			});
		};
		const addChildren = (node, depth) => {
			for (const sys of node.systems) addSystem(sys, depth);
			if (!ui.group) {
				for (const x of node.items) addItem(x, depth);
				return;
			}
			for (let i = 0; i < node.items.length;) {
				const kind = node.items[i].it.kind ?? '';
				let j = i;
				while (j < node.items.length && (node.items[j].it.kind ?? '') === kind) j++;
				const key = groupKey(node.path, kind);
				const open = expanded(key);
				const r = row(depth, {
					key, kind, name: KIND_LABEL[kind] ?? (kind.replace(/_/g, ' ') || 'other'),
					count: String(j - i), expandable: true, open, cls: 'trow-group', weight: j - i,
				});
				if (r && open) for (let k = i; k < j; k++) addItem(node.items[k], depth + 1);
				i = j;
			}
		};
		const addSystem = (node, depth) => {
			const key = systemKey(node.path);
			const open = expanded(key);
			const r = row(depth, {
				key, kind: 'system', name: node.name, count: node.deep.length.toLocaleString(),
				expandable: true, open, cls: 'trow-system', weight: node.deep.length,
				title: `${node.path} — ${plural(node.deep.length)} here${b.filtering ? ' that match' : ''}. `
					+ 'Selected, it stands for all of them.',
			});
			if (r && open) addChildren(node, depth + 1);
		};
		addChildren(b.root, 1);

		if (!rows[s].length) {
			tree.append(el('p', { className: 'hint dual-empty' }, b.filtering
				? 'Nothing here matches.'
				: s === 1 ? `Nothing yet — move ${noun}s here.` : `Every ${noun} has been moved across.`));
		}
		if (hidden) {
			tree.append(el('p', { className: 'hint tree-more' },
				`${hidden.toLocaleString()} more not drawn. Narrow the search to reach them — `
				+ 'the buttons act on every match, drawn or not.'));
		}
		tree.scrollTop = scrolled;
		markSelection(s);
		if (focused) {
			const back = rows[s].find((r) => r.key === focused);
			if (back) { back.el.tabIndex = 0; back.el.focus({ preventScroll: true }); }
		}
		if (!rows[s].some((r) => r.el.tabIndex === 0) && rows[s][0]) rows[s][0].el.tabIndex = 0;

		const all = on(s);
		const series = all.reduce((n, it) => n + (it.count ?? 1), 0);
		const shown = b.root.deep.length;
		count.textContent = `${plural(all.length)}${series !== all.length ? ` · ${series.toLocaleString()} series` : ''}`
			+ (b.filtering ? ` · ${shown.toLocaleString()} shown` : '');
	}

	function drawAll() {
		drawSide(0);
		drawSide(1);
		updateButtons();
	}

	function markSelection(s) {
		const sel = ui.sides[s].sel;
		for (const r of rows[s]) {
			const yes = sel.has(r.key);
			r.el.classList.toggle('is-selected', yes);
			r.el.setAttribute('aria-selected', yes ? 'true' : 'false');
		}
	}

	function updateButtons() {
		toRight.disabled = !covered(0).size;
		toLeft.disabled = !covered(1).size;
		allRight.disabled = !built[0]?.root.deep.length;
		allLeft.disabled = !built[1]?.root.deep.length;
	}

	function toggle(s, key, want) {
		if (want) ui.sides[s].open.add(key);
		else ui.sides[s].open.delete(key);
		drawSide(s);
		updateButtons();
	}

	/** What a click does to one side's selection: the left panel's rules. */
	function pick(s, key, ev) {
		const u = ui.sides[s];
		const order = rows[s].map((r) => r.key);
		if (ev?.shiftKey && u.anchor && order.includes(u.anchor)) {
			const a = order.indexOf(u.anchor);
			const z = order.indexOf(key);
			const [from, to] = a < z ? [a, z] : [z, a];
			u.sel = new Set(order.slice(from, to + 1));
		} else if (ev?.metaKey || ev?.ctrlKey) {
			if (u.sel.has(key)) u.sel.delete(key);
			else u.sel.add(key);
			u.anchor = key;
		} else {
			u.sel = new Set([key]);
			u.anchor = key;
		}
		for (const r of rows[s]) r.el.tabIndex = r.key === key ? 0 : -1;
		markSelection(s);
		updateButtons();
	}

	/** Moves items from side `s` to the other, and shows them where they landed. */
	function moveKeys(s, keys) {
		const list = [...keys].filter((k) => byKey.has(k));
		if (!list.length) return;
		for (const k of list) {
			if (s === 0) chosen.add(k);
			else chosen.delete(k);
		}
		const there = ui.sides[1 - s];
		there.sel = new Set(list.map(itemKey));
		there.anchor = null;
		// Opened where they went, so a move can be seen -- unless it was so
		// many that opening every sub-system they came from would bury the
		// tree, which is what moving everything does.
		if (list.length <= 200) {
			for (const k of list) {
				const it = byKey.get(k);
				for (let p = parentOf(it.name); p; p = parentOf(p)) there.open.add(systemKey(p));
				if (ui.group) there.open.add(groupKey(parentOf(it.name), it.kind ?? ''));
			}
		}
		ui.sides[s].sel.clear();
		ui.sides[s].anchor = null;
		drawAll();
		onChange?.();
	}

	const moveSelected = (s) => moveKeys(s, covered(s));
	const moveShown = (s) => moveKeys(s, built[s]?.root.deep ?? []);

	function menu(s, ev) {
		const n = covered(s).size;
		const shown = built[s]?.root.deep.length ?? 0;
		const u = ui.sides[s];
		openMenu({
			x: ev.clientX, y: ev.clientY, title: titles[s].toLowerCase(),
			items: [
				{ label: s === 0 ? `Move to ${titles[1]}` : `Move back to ${titles[0]}`,
					hint: n ? plural(n) : '', disabled: !n, onPick: () => moveSelected(s) },
				{ label: `Move everything shown ${s === 0 ? `to ${titles[1]}` : `back to ${titles[0]}`}`,
					hint: shown ? plural(shown) : '', disabled: !shown, onPick: () => moveShown(s) },
				{ separator: true },
				{ label: 'Select everything shown', disabled: !rows[s].length,
					onPick: () => { u.sel = new Set(rows[s].map((r) => r.key)); markSelection(s); updateButtons(); } },
				{ label: 'Expand all', onPick: () => {
					const add = (node) => {
						for (const sys of node.systems) { u.open.add(systemKey(sys.path)); add(sys); }
						if (ui.group) for (const x of node.items) u.open.add(groupKey(node.path, x.it.kind ?? ''));
					};
					add(build(on(s), { ...u, query: '', kind: '' }, ui.group).root);
					drawSide(s);
				} },
				{ label: 'Collapse all', onPick: () => { u.open.clear(); drawSide(s); } },
			],
		});
	}

	/**
	 * The browser's own drag, as the left panel's tree uses: a list is what
	 * it is for, and it brings the cursor and the scrolling near an edge. A
	 * row of the selection carries the whole selection; any other row is
	 * selected and carries itself -- marked, not redrawn, since removing the
	 * element a `dragstart` is dispatched on cancels the drag.
	 */
	function wireDrag(s, node, key) {
		node.draggable = true;
		node.addEventListener('dragstart', (ev) => {
			const u = ui.sides[s];
			if (!u.sel.has(key)) {
				u.sel = new Set([key]);
				u.anchor = key;
				markSelection(s);
			}
			const keys = [...covered(s)];
			if (!keys.length) { ev.preventDefault(); return; }
			dragging = { from: s, keys };
			node.classList.add('is-dragging');
			ev.dataTransfer.effectAllowed = 'move';
			ev.dataTransfer.setData('text/plain', keys.map((k) => byKey.get(k)?.name ?? k).join('\n'));
		});
		node.addEventListener('dragend', () => {
			dragging = null;
			node.classList.remove('is-dragging');
			for (const t of sides) t.tree.classList.remove('is-drop');
		});
	}

	function wireDrop(s, tree) {
		const allowed = () => dragging && dragging.from !== s;
		tree.addEventListener('dragenter', (ev) => { if (allowed()) ev.preventDefault(); });
		tree.addEventListener('dragover', (ev) => {
			if (!allowed()) return;
			ev.preventDefault();
			ev.dataTransfer.dropEffect = 'move';
			tree.classList.add('is-drop');
		});
		tree.addEventListener('dragleave', (ev) => {
			if (!tree.contains(ev.relatedTarget)) tree.classList.remove('is-drop');
		});
		tree.addEventListener('drop', (ev) => {
			ev.preventDefault();
			tree.classList.remove('is-drop');
			const d = dragging;
			dragging = null;
			if (d && d.from !== s) moveKeys(d.from, d.keys);
		});
	}

	/** The keyboard: the tree pattern, plus Enter to move and ⌘A to select. */
	function wireKeys(s, tree) {
		tree.addEventListener('keydown', (e) => {
			const list = rows[s];
			const i = list.findIndex((r) => r.el === document.activeElement);
			if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'a') {
				e.preventDefault();
				ui.sides[s].sel = new Set(list.map((r) => r.key));
				markSelection(s);
				updateButtons();
				return;
			}
			if (i < 0) return;
			const r = list[i];
			const go = (j, extend) => {
				if (!list[j]) return;
				list[i].el.tabIndex = -1;
				list[j].el.tabIndex = 0;
				list[j].el.focus();
				if (extend) pick(s, list[j].key, { shiftKey: true });
			};
			switch (e.key) {
				case 'ArrowDown': go(i + 1, e.shiftKey); break;
				case 'ArrowUp': go(i - 1, e.shiftKey); break;
				case 'Home': go(0); break;
				case 'End': go(list.length - 1); break;
				case 'ArrowRight':
					if (r.expandable && !r.open) toggle(s, r.key, true);
					else go(i + 1);
					break;
				case 'ArrowLeft':
					if (r.expandable && r.open) {
						toggle(s, r.key, false);
					} else {
						for (let k = i - 1; k >= 0; k--) if (list[k].depth < r.depth) { go(k); break; }
					}
					break;
				case ' ':
					pick(s, r.key, e);
					break;
				case 'Enter':
					// Across, the selection or else the row the cursor is on.
					if (!ui.sides[s].sel.size) ui.sides[s].sel = new Set([r.key]);
					moveSelected(s);
					break;
				case 'Escape':
					if (!ui.sides[s].sel.size) return;
					ui.sides[s].sel.clear();
					markSelection(s);
					updateButtons();
					break;
				default:
					return;
			}
			e.preventDefault();
			e.stopPropagation();
		});
	}

	drawAll();
	return { picked: items.filter((it) => chosen.has(it.key)).length, total: items.length };
}
