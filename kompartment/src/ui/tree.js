/**
 * The block tree: the whole model in the shape it is actually organised in.
 *
 * This panel used to be a flat list grouped by kind. That works for a model
 * with twenty blocks and not at all for the ones this tool was built to read:
 * One assessment model holds 1,298 blocks across 55 sub-systems, another
 * 3,789 across 46. In those a bare name means nothing -- there are several
 * blocks called `Kd`, and the one you want is the one in `NearField` -- and
 * the thing you navigate by is the sub-system, which the old list mentioned
 * only in a tooltip.
 *
 * So the sub-systems are the spine, as they are in any tree of such a
 * model, and the kind of a
 * block rides along as an icon instead of as a heading it has to be filed
 * under. Two of that factory's rules are kept because they are right: a
 * sub-system's own sub-systems come before its blocks, and names are ordered
 * ignoring case (`TreeNodeComparator`). The headings are still there for the
 * asking -- `Group by type` -- because one sub-system can hold hundreds, and
 * with them on the blocks go in kind order so that each run of a kind is a
 * heading. With them off the order is the name alone: there is nothing to file
 * a block under, so an order by kind is one only somebody who knows the
 * collection list can see.
 */

import * as ed from '../domain/edit.js';
import { parentOf, scopeChain, isWithin } from '../domain/systems.js';
import { blockIcon, sampleMark } from './icons.js';
import { symbolNodes, symbolText } from './symbol.js';
import { hasSymbol } from '../domain/symbol.js';
import { summarise } from './summary.js';
import { el } from './parts.js';

/** The last block the tree scrolled to, so it only chases a *new* selection. */
let lastRevealed = null;

/** What each of the sample's marks says, on hover. */
const SAMPLE_TITLE = {
	kept: 'An endpoint the probabilistic run kept: every realisation of it is held, '
		+ 'so a chart of it is a band.',
	varied: 'A parameter the probabilistic run varied: the value each realisation drew '
		+ 'is held, so a chart of it is its spread.',
	inside: 'Holds blocks the probabilistic run has realisations of.',
};

/** A kind heading is a node too, and needs a key of its own to be opened by. */
const groupKey = (path, collection) => `${path} :: ${collection}`;

/**
 * How many rows a search will draw before it stops and says so.
 *
 * A search opens everything holding a match, and on a large model a single letter
 * matches 2,875 blocks. Nobody reads 2,875 results, and drawing them on every
 * keystroke makes the box that produced them unusable. The count of what was
 * left out is shown, so this narrows the view without hiding anything
 * silently.
 */
const SEARCH_ROWS = 600;

/**
 * @param {HTMLElement} host
 * @param {object} project
 * @param {{kind: string, name: string}|null} selection
 * @param {{onSelect?: Function, onOpenSystem?: Function, onOpenSettings?: Function,
 *          onContextMenu?: (name: string, ev: MouseEvent) => void,
 *          onPlaceMenu?: (system: string, ev: MouseEvent) => void,
 *          onMoveTo?: (names: string[], system: string) => void,
 *          onDelete?: () => void,
 *          currentSystem?: string, picked?: string[]}} hooks
 * @param {{query?: string, kinds?: Set<string>, only?: string[]}|null} filter
 * @param {{open: Set<string>, group: boolean}} view
 *   Which nodes are expanded, and whether kinds are grouped. This lives in the
 *   caller's state and not in the project: it is a way of looking at a model,
 *   not a fact about one, and it has no business turning up in a diff.
 */
export function renderBlockTree(host, project, selection, hooks = {}, filter = null, view = null) {
	const state = view ?? { open: new Set(['']), group: false };
	// `only` is the answer to a structured question, pinned over the list --
	// see ../domain/queries.js. It filters like the rest, and it counts as
	// filtering, so the tree opens onto what was found rather than leaving it
	// folded away inside closed sub-systems.
	const filtering = !!String(filter?.query ?? '').trim()
		|| !!(filter?.kinds && [...filter.kinds].length)
		|| !!filter?.only;
	const current = hooks.currentSystem ?? '';

	const pickedNames = hooks.picked ?? (selection?.name ? [selection.name] : []);

	// What the sample on screen holds -- `kept` or `varied` by block -- and the
	// sub-systems that hold any of it, so a folded one says so: on a model of
	// fifty sub-systems the marked blocks are otherwise found by opening them
	// one at a time. The top level is left out, since it holds everything.
	const sampled = hooks.sample ?? null;
	const holding = new Set();
	if (sampled) {
		for (const name of sampled.keys()) {
			for (const s of scopeChain(parentOf(name))) if (s) holding.add(s);
		}
	}

	// A block selected elsewhere -- clicked on the diagram, or landed on by
	// the search -- is revealed wherever it lives. The tree follows the canvas
	// rather than making you find the thing you are already looking at. Not
	// for a selection of several: scrolling to whichever one happens to be
	// primary would drag the panel away from what is being done to the group.
	const chasing = !!selection?.name && selection.name !== lastRevealed
		&& pickedNames.length <= 1;
	if (chasing) for (const s of scopeChain(parentOf(selection.name))) state.open.add(s);

	const draw = () => {
		// Expanding a node redraws the tree under the keyboard, so the row
		// that had focus has to get it back.
		const focused = host.contains(document.activeElement)
			? document.activeElement.dataset?.key
			: null;
		// Where the list was scrolled to. The whole tree is rebuilt on every
		// selection, and a new element starts at the top -- so clicking a row
		// far down the list threw the list back to its head, and the row just
		// clicked, along with the double-click on its way, went out of view.
		const scrolled = host.querySelector('.tree')?.scrollTop ?? 0;
		host.replaceChildren();

		const root = ed.blockTree(project, filter ?? {}, { group: state.group });
		// Expand all and Collapse are not drawn here: they sit in the row of
		// Add tabs above the tree (`treeTools`), because anything put between
		// that row and this box parts the tabs from the edge they stand on.
		if (!root.deep) {
			// Inside the tree's own frame, not loose under the toolbar. The
			// panel is a bordered area with a background, and a model with
			// nothing in it used to lose that area entirely -- leaving the
			// three Add buttons floating over the rail with no surface under
			// them, which reads as a broken panel rather than an empty one.
			// An empty container is still the container.
			const empty = el('div', {
				className: 'tree is-empty', role: 'tree',
				'aria-label': 'The blocks of the model, by sub-system',
			}, el('p', { className: 'hint' }, filtering
				? 'No block matches the search above.'
				: 'The model is empty. Add a compartment to start.'));
			// And it is still a place: right-clicking it offers what can be put
			// here, which is exactly what somebody looking at an empty model
			// wants.
			empty.addEventListener('contextmenu', (ev) => {
				ev.preventDefault();
				hooks.onPlaceMenu?.('', ev);
			});
			host.append(empty);
			return;
		}

		const rows = [];
		let hidden = 0;
		const room = () => !filtering || rows.length < SEARCH_ROWS;
		const tree = el('div', {
			className: 'tree', role: 'tree',
			'aria-label': 'The blocks of the model, by sub-system',
		});
		// Rows that have a menu of their own stop this from being reached; the
		// rest -- a kind heading, the empty space below the last row -- would
		// otherwise get the browser's menu, which offers nothing about a model
		// and covers the tree with Reload and View Source.
		//
		// What is left is a place rather than a thing: pointing at no row is
		// pointing at the model and not at anything in it, so what can be done
		// here is what can be put here.
		tree.addEventListener('contextmenu', (ev) => {
			ev.preventDefault();
			hooks.onPlaceMenu?.('', ev);
		});
		// And a plain click on it selects the model itself -- the same thing
		// the root row stands for. Clicking below the last row is pointing at
		// no block, and pointing at no block is pointing at the model; without
		// this it left whatever was selected before selected, so the
		// Information view went on describing a block the pointer had just
		// been moved away from.
		//
		// Guarded on the target rather than by `stopPropagation` in each row:
		// a row's own click has already done its work by the time this sees
		// it, and rows are built in four places.
		tree.addEventListener('click', (ev) => {
			if (ev.target.closest('[data-key]')) return;
			hooks.onSelect?.({ kind: 'system', name: '' }, []);
		});

		const expanded = (key) => (
			// While a search is on, everything still holding a match is open:
			// a result you have to go digging for is not a result.
			filtering || state.open.has(key)
		);

		const row = (depth, spec) => {
			const node = el('div', {
				className: `trow${spec.cls ? ` ${spec.cls}` : ''}`,
				role: 'treeitem',
				tabIndex: -1,
			});
			node.dataset.key = spec.key;
			node.setAttribute('aria-level', String(depth));
			node.style.paddingLeft = `${4 + (depth - 1) * 13}px`;
			// Drives the hairlines that show which container a row is in;
			// see `.trow` in the stylesheet.
			node.style.setProperty('--depth', String(depth));
			if (spec.expandable) node.setAttribute('aria-expanded', spec.open ? 'true' : 'false');

			const twisty = el('span', {
				className: `twisty${spec.expandable ? '' : ' is-leaf'}`,
				'aria-hidden': 'true',
			}, spec.expandable ? '▸' : '');
			if (spec.expandable) {
				twisty.addEventListener('click', (e) => {
					e.stopPropagation();
					spec.onOpen(!spec.open);
				});
			}
			const label = el('span', { className: 'tname' });
			// The name first -- it is what the equations, the search and the
			// problem strip use, and the thing you look a row up by -- and
			// what the block is shown as after it, in brackets, where it has
			// one. The diagram shows the symbol alone, since a box is read at
			// a glance; a list is read by name.
			label.textContent = spec.name;
			if (spec.symbol) {
				label.append(' (', el('span', { className: 'tname-symbol' }, ...symbolNodes(spec.symbol)), ')');
			}
			node.append(twisty, blockIcon(spec.kind), label);
			// What the sample holds of it: the same glyph the chart's chips and
			// the table's heads wear. A sub-system gets a dot for what is
			// inside it.
			if (spec.sample) {
				node.append(el('span', {
					className: `tsample is-${spec.sample}`,
					title: SAMPLE_TITLE[spec.sample],
					'aria-label': spec.sample === 'inside'
						? 'holds blocks with realisations' : `${spec.sample} by the probabilistic run`,
				}, spec.sample === 'inside' ? '' : sampleMark(spec.sample)));
			}
			// What is wrong here, or inside here: the same mark the diagram
			// wears, so a fault can be found by walking the tree as well as by
			// opening sub-systems one by one.
			const mark = spec.key && hooks.marks?.get(spec.markName ?? spec.key);
			if (mark) {
				node.append(el('span', {
					className: `tmark is-${mark.level}`, title: mark.message,
					'aria-label': mark.level === 'error' ? 'has a problem' : 'has a warning',
				}, '!'));
			}
			if (spec.sub) node.append(el('span', { className: 'tsub' }, spec.sub));
			if (spec.count != null) node.append(el('span', { className: 'tcount' }, String(spec.count)));
			// The event is handed on: which block a click selects is one
			// question, and whether it replaces, extends or toggles the
			// selection is another, and only the modifiers answer the second.
			node.addEventListener('click', (ev) => spec.onPick(ev));

			// The same menu the diagram offers. Whatever it is about has to be
			// selected first, so the panels agree with the menu's own title.
			if (spec.onMenu) {
				node.addEventListener('contextmenu', (ev) => {
					ev.preventDefault();
					ev.stopPropagation();
					spec.onMenu(ev);
				});
			}
			if (spec.onDragStart) wireDrag(node, spec);
			if (spec.onDrop) wireDrop(node, spec);
			if (spec.onOpen2) {
				// Double-click opens the thing: a block's full settings, a
				// sub-system's own diagram. The same gesture the canvas uses.
				node.addEventListener('dblclick', (ev) => {
					ev.preventDefault();
					spec.onOpen2();
				});
			}

			tree.append(node);
			rows.push({
				el: node,
				key: spec.key,
				selectable: !!spec.selectable,
				depth,
				expandable: !!spec.expandable,
				open: !!spec.open,
				onOpen: spec.onOpen,
				onPick: spec.onPick,
			});
			return node;
		};

		// Several blocks can be selected on the diagram at once; the tree marks
		// all of them, and the inspector shows the one named by `selection`.
		const picked = new Set(pickedNames);
		// The blocks on screen in the order they are drawn, which is the order
		// a shift-click means by "everything between".
		const order = [];
		const addBlock = (b, depth) => {
			if (!room()) { hidden += 1; return; }
			const selected = picked.has(b.name);
			const held = sampled?.get(b.name) ?? null;
			order.push(b);
			const r = row(depth, {
				key: `b:${b.name}`,
				markName: b.name,
				kind: b.kind,
				name: b.block.name,
				symbol: hasSymbol(b.block) ? b.block.symbol : null,
				sub: summarise(b.collection, b.block),
				sample: held,
				cls: `trow-block${selected ? ' is-selected' : ''}`
					+ `${ed.isEffectivelyEnabled(project, b.block) ? '' : ' is-disabled'}`
					+ `${held ? ` has-sample is-${held}` : ''}`,
				selectable: true,
				onPick: (ev) => choose(b, ev, order, pickedNames, hooks),
				onOpen2: () => hooks.onOpenSettings?.(b.name),
				onMenu: (ev) => {
					// Not part of the group: the menu is about this one, so
					// this one becomes the selection first, exactly as on the
					// diagram.
					if (!picked.has(b.name)) {
						hooks.onSelect?.({ kind: b.kind, name: b.name }, [b.name]);
					}
					hooks.onContextMenu?.(b.name, ev);
				},
				// A member of the selection drags the whole selection; anything
				// else drags alone. The selection is deliberately *not*
				// changed here: `onSelect` redraws the tree, and removing the
				// element a `dragstart` is being dispatched on cancels the
				// drag. Nothing is lost -- what lands somewhere new becomes
				// the selection when the move completes.
				// Returning nothing cancels the drag, which is what a connection
				// on its own gets: it goes where its compartments go, so there
				// is nowhere to drop it that would mean anything. Dragged as
				// part of a selection that holds them, it travels with them.
				onDragStart: () => {
					const names = picked.has(b.name) && pickedNames.length > 1
						? [...pickedNames]
						: [b.name];
					return ed.canTravel(project, names) ? names : [];
				},
			});
			if (selected) r.setAttribute('aria-selected', 'true');
			if (b.name === selection?.name) r.classList.add('is-primary');
			r.title = `${b.name} — ${(ed.roleLabel(project, b.block) ?? b.kind).replace(/_/g, ' ').toLowerCase()}`
				+ (hasSymbol(b.block) ? `, shown as ${symbolText(b.block.symbol)}` : '')
				+ (held ? `\n${SAMPLE_TITLE[held]}` : '');
		};

		const addChildren = (node, depth) => {
			// Sub-systems first, then blocks: the containers are the map, and
			// the blocks are what is on it.
			for (const s of node.systems) addSystem(s, depth);
			if (!state.group) {
				for (const b of node.blocks) addBlock(b, depth);
				return;
			}
			// Grouped: the blocks arrive sorted by kind, so one run of a kind
			// is one heading.
			for (let i = 0; i < node.blocks.length;) {
				const { collection, kind } = node.blocks[i];
				let j = i;
				while (j < node.blocks.length && node.blocks[j].collection === collection) j++;
				const key = groupKey(node.path, collection);
				const open = expanded(key);
				row(depth, {
					key,
					kind,
					name: ed.KIND_LABEL[kind] ?? collection,
					count: j - i,
					expandable: true,
					open,
					cls: 'trow-group',
					onOpen: (want) => { toggle(state, key, want); draw(); },
					onPick: () => { toggle(state, key, !open); draw(); },
				});
				if (open) for (let k = i; k < j; k++) addBlock(node.blocks[k], depth + 1);
				i = j;
			}
		};

		function addSystem(node, depth) {
			if (!room()) { hidden += node.deep; return; }
			const open = expanded(node.path);
			const here = node.count === 1 ? '1 block here' : `${node.count} blocks here`;
			// A sub-system takes part in a selection like anything else in the
			// tree, so it is one of the rows a range runs over.
			const selected = !!node.path && picked.has(node.path);
			if (node.path) order.push({ name: node.path, kind: 'system' });
			const r = row(depth, {
				key: node.path,
				markName: node.path,
				// A transport is its own kind of thing -- a sub-system that is
				// also a block -- and wears its own icon here, as on the diagram.
				kind: node.path && ed.isTransport(project, node.path) ? 'transport' : 'system',
				name: node.path ? node.name : `${node.name} — top level`,
				count: node.deep,
				expandable: node.deep > 0 || node.systems.length > 0,
				open,
				selectable: !!node.path,
				sample: node.path && holding.has(node.path) ? 'inside' : null,
				cls: `trow-system${node.path === current ? ' is-current' : ''}`
					+ `${selected ? ' is-selected' : ''}`
					+ `${node.path && !ed.isSystemEnabled(project, node.path) ? ' is-disabled' : ''}`,
				onOpen: (want) => { toggle(state, node.path, want); draw(); },
				// Clicking a sub-system shows it on the diagram, which is what
				// the old list did, and opens it, which is what a tree does.
				// It never closes one: that would take away the thing you have
				// just asked to see.
				//
				// With a modifier it is being picked out instead: a sub-system
				// is a thing you can select, and several of them can be copied
				// or deleted in one go. Navigating then would be wrong twice
				// over -- it would take the canvas away from the rest of the
				// selection, and there would be no way to add one to a group.
				onPick: (ev) => {
					if (node.path && (ev?.shiftKey || ev?.metaKey || ev?.ctrlKey)) {
						choose({ name: node.path, kind: 'system' }, ev, order, pickedNames, hooks);
						return;
					}
					state.open.add(node.path);
					hooks.onOpenSystem?.(node.path);
				},
				onOpen2: () => { toggle(state, node.path, !expanded(node.path)); draw(); },
				onMenu: (ev) => {
					// About this one, unless it is part of the group -- the
					// same rule a block row follows, so the panels agree with
					// the menu's own title.
					if (node.path && !picked.has(node.path)) {
						hooks.onSelect?.({ kind: 'system', name: node.path }, [node.path]);
					}
					hooks.onContextMenu?.(node.path, ev);
				},
				// A sub-system can be dragged like anything else here:
				// moving one is renaming the path its blocks wear. A member of
				// the selection takes the whole selection with it.
				// The top level is not a thing that can be moved, so its row
				// is not made draggable at all rather than starting a drag
				// and cancelling it.
				onDragStart: node.path
					? () => (picked.has(node.path) && pickedNames.length > 1
						? [...pickedNames]
						: [node.path])
					: undefined,
				// Where things are dropped. The root row is the way *out* of a
				// sub-system, which is the half a diagram cannot offer: on the
				// canvas you can drop a block onto a container, but there is
				// nothing to drop it on to take it back out.
				onDrop: (names) => hooks.onMoveTo?.(names, node.path),
				// Something already here has nowhere to go, and a sub-system
				// cannot be dropped into itself or into anything inside it.
				canDrop: (names) => names.some((n) => parentOf(n) !== node.path)
					&& !names.some((n) => isWithin(node.path, n)),
			});
			if (selected) r.setAttribute('aria-selected', 'true');
			r.title = node.path
				? `${node.path} — ${here}, ${node.deep} in all. `
					+ 'Click to show it on the diagram, ⌘-click to select it.'
				: `The top level — ${here}, ${node.deep} in the model.`;
			if (open) addChildren(node, depth + 1);
		}

		// A model with no sub-systems has nothing to nest, so it gets neither
		// an indent nor a root row that would say what the title bar says.
		if (root.systems.length) addSystem(root, 1);
		else addChildren(root, 1);

		host.append(tree);
		// Put back once the element is in the document and has a height to
		// scroll within. A selection made elsewhere is still brought into
		// view below, where `chasing` says so; one made here is already in it.
		if (scrolled) tree.scrollTop = scrolled;
		if (hidden) {
			host.append(el('p', { className: 'hint tree-more' },
				`${hidden.toLocaleString()} more ${hidden === 1 ? 'match is' : 'matches are'} `
				+ 'not shown. Narrow the search to see them.'));
		}
		wireKeys(tree, rows, state, draw, hooks);

		// Exactly one row is in the tab order, and it is the one the eye is
		// already on: the selected block, or failing that the first row.
		const home = rows.find((r) => r.el.classList.contains('is-selected')) ?? rows[0];
		if (home) home.el.tabIndex = 0;
		if (focused) {
			const back = rows.find((r) => r.el.dataset.key === focused);
			if (back) {
				for (const r of rows) r.el.tabIndex = -1;
				back.el.tabIndex = 0;
				back.el.focus({ preventScroll: true });
			}
		} else if (chasing && home?.el.classList.contains('is-selected')) {
			home.el.scrollIntoView({ block: 'nearest' });
		}
	};

	draw();
	// Cleared as well as set: with nothing selected, the next selection is a
	// new one wherever it lands, including on the block just deselected.
	lastRevealed = selection?.name ?? null;
	// An anchor naming a block that has been deleted, renamed or filtered out
	// would make the next shift-click take a range from nowhere.
	if (anchorName && !ed.findBlock(project, anchorName)
		&& !ed.systems(project).includes(anchorName)) anchorName = null;
}

function toggle(state, key, want) {
	if (want) state.open.add(key);
	else state.open.delete(key);
}

/**
 * Which row a shift-click counts from. Remembered across redraws, since every
 * click redraws the tree, and cleared when it names a row that has gone.
 */
let anchorName = null;

/**
 * What a click on a block row does to the selection.
 *
 * The list conventions, which are richer than the diagram's: plain replaces,
 * the platform modifier adds and removes one, and shift takes everything
 * between the last row clicked and this one -- in the order the tree draws
 * them, which is the only order "between" can mean here.
 */
function choose(b, ev, order, pickedNames, hooks) {
	const names = order.map((x) => x.name);
	const at = names.indexOf(b.name);
	const one = { kind: b.kind, name: b.name };

	// Reached from the keyboard as well, where the modifiers come off a
	// KeyboardEvent, and from Enter with none at all.
	if (ev?.shiftKey && anchorName && anchorName !== b.name) {
		const from = names.indexOf(anchorName);
		if (from >= 0 && at >= 0) {
			const [a, z] = from < at ? [from, at] : [at, from];
			// The anchor stays where it was, so shift-clicking again from the
			// same starting point grows and shrinks one range rather than
			// walking off across the tree.
			hooks.onSelect?.(one, names.slice(a, z + 1));
			return;
		}
	}

	if (ev?.metaKey || ev?.ctrlKey) {
		const next = new Set(pickedNames);
		if (next.has(b.name)) next.delete(b.name);
		else next.add(b.name);
		anchorName = b.name;
		// Taking the last one out leaves nothing selected, which is what
		// Escape does and what clicking it off should do too.
		if (!next.size) { hooks.onSelect?.(null, []); return; }
		// The one just clicked leads, unless it was the one removed.
		const lead = next.has(b.name)
			? one
			: (() => {
				const first = order.find((x) => next.has(x.name));
				return first ? { kind: first.kind, name: first.name } : null;
			})();
		hooks.onSelect?.(lead, [...next]);
		return;
	}

	anchorName = b.name;
	hooks.onSelect?.(one, [b.name]);
}

/**
 * Dragging rows out of the tree and into a sub-system.
 *
 * The browser's own drag rather than pointer events, as the diagram uses:
 * a list is what HTML drag-and-drop is for, and it brings the drag image, the
 * cursor and -- the one that matters in a tree of nine hundred rows -- the
 * automatic scrolling of the box the pointer is near the edge of.
 *
 * What is being dragged is kept here rather than read back out of the
 * DataTransfer, because the payload is deliberately unreadable during
 * `dragover`: a drop target is told the *kinds* of data on offer and not their
 * values, so whether a drop is allowed cannot be decided from it.
 */
let dragging = null;

function wireDrag(node, spec) {
	node.draggable = true;
	node.addEventListener('dragstart', (ev) => {
		dragging = spec.onDragStart() ?? [];
		if (!dragging.length) { ev.preventDefault(); return; }
		node.classList.add('is-dragging');
		ev.dataTransfer.effectAllowed = 'move';
		// Text, so that dragging out of the window at least yields the names
		// rather than nothing.
		ev.dataTransfer.setData('text/plain', dragging.join('\n'));
	});
	node.addEventListener('dragend', () => {
		dragging = null;
		node.classList.remove('is-dragging');
		for (const el2 of node.closest('.tree')?.querySelectorAll('.is-drop') ?? []) {
			el2.classList.remove('is-drop');
		}
	});
}

function wireDrop(node, spec) {
	const allowed = () => !!dragging?.length && (spec.canDrop?.(dragging) ?? true);
	node.addEventListener('dragover', (ev) => {
		if (!allowed()) return;
		// Only a target that has called preventDefault will take a drop, so
		// this is both "yes" and "show the move cursor".
		ev.preventDefault();
		ev.dataTransfer.dropEffect = 'move';
		node.classList.add('is-drop');
	});
	node.addEventListener('dragenter', (ev) => { if (allowed()) ev.preventDefault(); });
	node.addEventListener('dragleave', () => node.classList.remove('is-drop'));
	node.addEventListener('drop', (ev) => {
		ev.preventDefault();
		node.classList.remove('is-drop');
		const names = dragging;
		dragging = null;
		if (names?.length) spec.onDrop(names);
	});
}

/**
 * The two buttons that save a great deal of clicking.
 *
 * `Group by type` used to be here too. It sits beside `All kinds` now, in the
 * search above -- the two are the same kind of control, each saying how the
 * list below is to be arranged, and they read as a pair rather than as one
 * setting in the search and another in the tree.
 *
 * Built for the row of Add tabs on the tree's top edge (see `addTabs` in
 * ./app.js), at its left, where that row has room. They were a row of their
 * own between the tabs and the tree, which lifted the tabs off the edge they
 * are drawn to stand on as soon as a model had a sub-system.
 *
 * @param {object} project
 * @param {{open: Set<string>, group: boolean}} state  the tree's view, as
 *   `renderBlockTree` is handed it
 * @param {() => void} redraw  draws the tree again
 * @param {object|null} [filter]  the tree's filter, for the group headings
 *   Expand all opens when the tree is grouped by kind
 * @returns {HTMLElement|null} null when there is nothing to expand
 */
export function treeTools(project, state, redraw, filter = null) {
	const paths = ed.systems(project);
	// Nothing to expand: no buttons.
	if (!paths.length) return null;
	const bar = el('span', { className: 'tree-tools' });
	const all = el('button', {
		className: 'ghost tree-btn', type: 'button',
		title: 'Open every sub-system',
	}, 'Expand all');
	all.addEventListener('click', () => {
		state.open = new Set(['', ...paths]);
		if (state.group) {
			const root = ed.blockTree(project, filter ?? {}, { group: true });
			const add = (n) => {
				for (const b of n.blocks) state.open.add(groupKey(n.path, b.collection));
				n.systems.forEach(add);
			};
			add(root);
		}
		redraw();
	});
	const none = el('button', {
		className: 'ghost tree-btn', type: 'button',
		title: 'Close every sub-system',
	}, 'Collapse');
	none.addEventListener('click', () => { state.open = new Set(); redraw(); });
	bar.append(all, none);
	return bar;
}

/**
 * Arrow-key navigation, as a tree is expected to have.
 *
 * Down and up walk the rows actually on screen; right opens a node or steps
 * into it, left closes it or steps back out to whatever holds it. That is the
 * ARIA tree pattern, and with a few hundred rows in front of you it beats the
 * mouse comfortably.
 */
function wireKeys(tree, rows, state, draw, hooks) {
	const move = (from, to, extend = false) => {
		if (!rows[to]) return;
		rows[from].el.tabIndex = -1;
		rows[to].el.tabIndex = 0;
		// Focused before the selection is touched, so that the redraw the
		// selection causes knows which row to give focus back to.
		rows[to].el.focus();
		// Shift with an arrow grows the selection as it goes, which is what a
		// list does. A group heading is not a thing that can be selected;
		// a sub-system is, and comes along like any other row.
		if (extend && rows[to].selectable) rows[to].onPick({ shiftKey: true });
	};
	tree.addEventListener('keydown', (e) => {
		const i = rows.findIndex((r) => r.el === document.activeElement);
		if (i < 0) return;
		const r = rows[i];
		switch (e.key) {
			case 'ArrowDown': move(i, i + 1, e.shiftKey); break;
			case 'ArrowUp': move(i, i - 1, e.shiftKey); break;
			case 'Home': move(i, 0); break;
			case 'End': move(i, rows.length - 1); break;
			case 'ArrowRight':
				if (r.expandable && !r.open) r.onOpen(true);
				else move(i, i + 1);
				break;
			case 'ArrowLeft':
				if (r.expandable && r.open) {
					r.onOpen(false);
				} else {
					for (let k = i - 1; k >= 0; k--) {
						if (rows[k].depth < r.depth) { move(i, k); break; }
					}
				}
				break;
			case 'Enter':
			case ' ':
				r.onPick(e);
				break;
			case 'Delete':
			case 'Backspace':
				// The same key the diagram uses, on the same selection. The
				// menu offers it too, but with several rows picked in the tree
				// the key is what a hand reaches for.
				hooks.onDelete?.();
				break;
			case 'Escape':
				hooks.onSelect?.(null, []);
				break;
			case '*': {
				// The tree-pattern shortcut: open every sibling at this level,
				// as one redraw rather than one per row.
				for (const s of rows) if (s.depth === r.depth && s.expandable) state.open.add(s.key);
				draw();
				break;
			}
			default:
				return;
		}
		e.preventDefault();
	});
}
