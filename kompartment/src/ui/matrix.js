/**
 * Transfer matrix.
 *
 * Laid out the way a Jacobian is drawn: **the blocks are on the diagonal and
 * the interactions are off it**. Row i, column j is what flows out of the
 * block named at (i,i) and into the block named at (j,j), so the diagonal is a
 * staircase of names and everything beside it is a transfer.
 *
 * That saves the header band a from/to grid needs -- the diagonal is the
 * header, in both directions at once -- and it is the shape anyone who has
 * looked at a sparsity pattern already knows how to read. Each filled cell
 * carries the elbow that says which way it runs: in along its row from the
 * name on the diagonal, out down or up its column to the other one.
 *
 * The extra row and column marked "outside" are transfers with no compartment
 * at one end -- inflows from, and outflows to, the world beyond the model.
 */

import * as ed from '../domain/edit.js';
import { qualifiedName, baseName } from '../domain/systems.js';
import { inkFor } from './ink.js';
import { el } from './parts.js';
import { symbolNodes } from './symbol.js';
import { hasSymbol } from '../domain/symbol.js';

const OUTSIDE = 'outside';

const NS = 'http://www.w3.org/2000/svg';
const svg = (tag, attrs = {}) => {
	const n = document.createElementNS(NS, tag);
	for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, String(v));
	return n;
};

/**
 * Which way a cell runs, drawn as the path it takes.
 *
 * A cell's donor is the name on the diagonal along its own row and its
 * receiver is the name on the diagonal down its own column, so the flow is an
 * elbow: in along the row, a quarter turn, out along the column. Which way it
 * turns follows from which side of the diagonal the cell is on, and that is
 * the whole of what has to be said -- above it the receiver is further down
 * the list, below it the receiver is further up.
 *
 * Drawn rather than written, because an arrow that traces the route needs no
 * convention remembered: the line starts where the donor's name is and ends
 * pointing at the receiver's.
 *
 * @param {boolean} down true above the diagonal, where the flow turns down
 */
function flowArrow(down) {
	const g = svg('svg', {
		class: 'matrix-arrow', viewBox: '0 0 22 22', width: 16, height: 16,
		'aria-hidden': 'true', focusable: 'false',
	});
	g.append(svg('path', {
		class: 'matrix-arrow-line',
		// Above the diagonal: in from the left (the donor is back along the
		// row), turning down. Below it: in from the right, turning up.
		d: down ? 'M 2 5 H 11 Q 15 5 15 9 V 12' : 'M 20 17 H 11 Q 7 17 7 13 V 10',
		fill: 'none',
	}));
	g.append(svg('path', {
		class: 'matrix-arrow-head',
		d: down ? 'M 15 18.5 l 3.4 -5.4 h -6.8 z' : 'M 7 3.5 l 3.4 5.4 h -6.8 z',
	}));
	return g;
}

/**
 * A block's own colour, if it was given one.
 *
 * Only the explicit choice: a block with no colour keeps the cell's theme
 * background, the way it keeps the diagram's default fill. `findBlock` walks
 * every collection, so this is the one lookup rather than a guess from which
 * list the name came out of.
 */
function colorOf(project, name) {
	const block = ed.findBlock(project, name)?.block;
	const color = String(block?.color ?? '').trim();
	return color || null;
}

/**
 * @param {HTMLElement} host
 * @param {object} project
 * @param {{kind: string, name: string}|null} selection
 * @param {{onChange: Function, onSelect: Function, onStatus: Function,
 *          onOpenSettings: Function}} hooks
 */
/**
 * Moves the highlight to a different connection, leaving the grid alone.
 *
 * The grid is (compartments + paths + 1) squared: a model of two hundred
 * compartments is forty thousand cells, and rebuilding all of them because the
 * selection moved -- which happens on every click anywhere in the application,
 * since `setSelection` re-renders this view -- is the whole cost of the view
 * paid for a class on one cell.
 */
export function markSelection(host, selection) {
	const name = selection?.name ?? null;
	for (const td of host.querySelectorAll('td[data-names]')) {
		td.classList.toggle('is-selected',
			!!name && td.dataset.names.split('\u0000').includes(name));
	}
	// And every button that stands for one block: the connections inside a
	// cell -- a cell may hold several -- and the blocks on the diagonal.
	for (const btn of host.querySelectorAll('[data-name]')) {
		btn.classList.toggle('is-selected', btn.dataset.name === name);
	}
}

export function renderMatrix(host, project, selection, hooks = {}, opts = {}) {
	host.replaceChildren();
	// Compartments are listed by qualified name: two called Water in different
	// sub-systems are two blocks, and something has to say which is which. On
	// this grid that something is the frame around the sub-system, so the cell
	// shows the local name and keeps the path for its tooltip.
	const comps = (project.compartments ?? []).map((c) => qualifiedName(c));
	const paths = (project.farfields ?? []).map((f) => qualifiedName(f));

	if (!comps.length) {
		host.append(el('div', { className: 'empty' },
			'Add a compartment to start building the model.'));
		return;
	}

	// Which sub-systems are unfolded. The view's, not the model's: it changes
	// nothing and is never saved.
	const open = opts.open ?? new Set();
	const plan = ed.matrixPlan(project, open);
	const { slots, frames, representative } = plan;

	// donor -> receiver -> the transfers between them, keyed by what each end
	// *lands on*: a block, or the closed sub-system standing for it. A list,
	// not one transfer: two blocks may be joined by several, and folding a
	// sub-system up puts more of them in the same cell.
	const byPair = new Map();
	const key = (a, b) => `${a ?? ''}\u0000${b ?? ''}`;
	const add = (k, block) => {
		if (!byPair.has(k)) byPair.set(k, []);
		byPair.get(k).push(block);
	};
	// What a closed sub-system has swallowed: transfers between two blocks
	// inside it, which have no row and no column left to sit on. Counted
	// rather than dropped -- a grid that quietly stops showing part of the
	// model is worse than one that says how much it is not showing.
	const inside = new Map();
	const connections = [
		...(project.transfers ?? []),
		...(project.inflows ?? []).map((x) => ({ ...x, from: null, _source: true })),
	];
	for (const t of connections) {
		const a = representative(t.from);
		const b = representative(t.to);
		if (a != null && a === b) {
			inside.set(a, (inside.get(a) ?? 0) + 1);
			continue;
		}
		add(key(a, b), t);
	}

	const isPath = new Set(paths);
	// A folded sub-system's tile carries a second line -- what it holds -- and
	// the tile is placed out of flow, so it cannot make the row taller for
	// itself. The rows are given the room when any group is on the grid.
	const anyGroups = slots.some((x) => x.kind === 'group');
	const table = el('table', {
		className: `matrix${anyGroups ? ' has-groups' : ''}`,
	});
	const body = el('tbody');

	/** What a slot stands for when a flux lands on it; undefined for a label. */
	const idOf = (slot) => (slot.kind === 'block' ? slot.name
		: slot.kind === 'group' ? slot.path
			: slot.kind === 'outside' ? null : undefined);
	/** What to call it on screen, and what to call it in a tooltip. */
	const nameOf = (slot) => (slot.kind === 'outside' ? OUTSIDE : slot.local);
	const fullOf = (slot) => (slot.kind === 'block' ? slot.name
		: slot.kind === 'outside' ? 'outside the model' : slot.path);

	// The frame each cell sits on the edge of. A cell may be on more than one
	// -- a sub-system whose last member is itself a sub-system shares its
	// bottom and right edge -- so the shadows are composed rather than set as
	// a border, which cannot stack. The outermost frame wins the colour.
	const edgesAt = (i, j) => {
		const parts = [];
		let depth = null;
		for (const f of frames) {
			const inRows = i >= f.from && i <= f.to;
			const inCols = j >= f.from && j <= f.to;
			if (!inRows || !inCols) continue;
			const want = [];
			if (i === f.from) want.push('inset 0 2px 0 0 var(--matrix-frame)');
			if (i === f.to) want.push('inset 0 -2px 0 0 var(--matrix-frame)');
			if (j === f.from) want.push('inset 2px 0 0 0 var(--matrix-frame)');
			if (j === f.to) want.push('inset -2px 0 0 0 var(--matrix-frame)');
			if (!want.length) continue;
			for (const w of want) if (!parts.includes(w)) parts.push(w);
			depth = depth == null ? f.depth : Math.min(depth, f.depth);
		}
		return { shadow: parts.join(', '), depth };
	};

	/** Whether a slot is inside the open sub-system at `f`. */
	const within = (f, at) => at > f.from && at <= f.to;

	for (let i = 0; i < slots.length; i++) {
		const r = slots[i];
		const tr = el('tr', {});

		for (let j = 0; j < slots.length; j++) {
			const c = slots[j];
			const frame = edgesAt(i, j);

			// --- the diagonal: the thing itself ---------------------------
			if (i === j) {
				tr.append(diagonalCell(r, {
					project, selection, hooks, isPath, inside, frame, open,
					nameOf, fullOf,
				}));
				continue;
			}

			// --- a sub-system's header band -------------------------------
			// Nothing flows into or out of a header: it is the label of the
			// group it opens. The band runs along the group's top row and
			// left column, which is where the eye looks for a heading on a
			// grid that is read both ways.
			if (r.kind === 'head' || c.kind === 'head') {
				const band = r.kind === 'head'
					? frames.find((f) => f.path === r.path && within(f, j))
					: frames.find((f) => f.path === c.path && within(f, i));
				const td = el('td', {
					className: band ? 'matrix-band' : 'matrix-void',
					title: band
						? `${band.path} \u2014 everything inside it is framed here`
						: '',
				});
				if (frame.shadow) td.style.setProperty('box-shadow', frame.shadow);
				tr.append(td);
				continue;
			}

			const a = idOf(r);
			const b = idOf(c);
			const here = byPair.get(key(a, b)) ?? [];
			// A release cannot be delivered straight into another path: that
			// pair can never be joined, whatever is open.
			const impossible = isPath.has(a) && isPath.has(b);
			// A pair with a folded sub-system at either end cannot be joined
			// *by hand* -- there is no single block at that end to connect --
			// which is a different thing, and must not look like the first: a
			// cell holding seven fluxes should not be greyed out as forbidden.
			const folded = r.kind === 'group' || c.kind === 'group';
			const td = el('td', {
				className: [
					impossible ? 'matrix-na' : '',
					here.length ? 'matrix-has' : 'matrix-empty',
					here.some((t) => selection?.name === qualifiedName(t)) ? 'is-selected' : '',
				].filter(Boolean).join(' '),
			});
			if (frame.shadow) td.style.setProperty('box-shadow', frame.shadow);
			if (here.length) td.dataset.names = here.map((t) => qualifiedName(t)).join('\u0000');

			// Which way this cell runs. Above the diagonal the receiver is
			// further down the list, so the elbow turns down; below it, up.
			const down = j > i;

			if (here.length > 1 && folded) {
				// Several fluxes across a folded boundary. Summarised rather
				// than listed: every one of them belongs to a block that is
				// not on the grid, so reading its rate here says less than
				// the count does -- and a dozen of them stacked in one cell
				// made the row a screen tall, which is the opposite of what
				// folding a sub-system is for. Opening the group is one click
				// away, and that is where the detail belongs.
				td.append(summaryCell(here, {
					hooks, down, from: fullOf(r), to: fullOf(c),
					open: r.kind === 'group' ? r.path : c.path,
				}));
			} else if (here.length) {
				td.append(cellStack(here, {
					project, selection, hooks, down, from: fullOf(r), to: fullOf(c),
				}));
				// Room for one more, where a pair can take one by hand.
				if (!impossible && !folded) {
					td.querySelector('.matrix-stack')
						.append(addButton({ project, hooks, a, b, isPath, extra: here.length }));
				}
			} else if (impossible) {
				td.title = `A release from ${fullOf(r)} cannot be delivered straight `
					+ `into ${fullOf(c)}: give it a compartment in between.`;
			} else if (folded) {
				td.title = `${fullOf(r.kind === 'group' ? r : c)} is folded up. Open it `
					+ `to connect the block inside it that a flux would belong to.`;
			} else {
				td.append(addButton({ project, hooks, a, b, isPath, extra: 0 }));
			}
			tr.append(td);
		}
		body.append(tr);
	}
	table.append(body);
	host.append(table);

	host.append(el('p', { className: 'hint' },
		'The blocks are on the diagonal, the flows between them off it \u2014 the '
		+ 'shape a Jacobian is drawn in. A cell is what leaves the name on the '
		+ 'diagonal along its row and arrives at the name down its column, and '
		+ 'the elbow in it traces that route: above the diagonal it turns down, '
		+ 'below it turns up. Click anything here to select it and double-click '
		+ 'to open its settings, blocks and transfers alike; click an empty cell '
		+ 'to add a transfer. A pair may hold more than one, and their fluxes add.'
		+ (frames.length || slots.some((x) => x.kind === 'group')
			? ' A sub-system folds up into a single row and column, with every '
				+ 'flux in and out of it landing there; open it with the arrow on '
				+ 'its cell to see the blocks inside, framed together.'
			: '')
		+ (paths.length
			? ' A far-field path sits on the diagonal like any other block: a flux '
				+ 'goes into its first fracture cell, and its release comes out of '
				+ 'its last \u2014 and that rate is the release itself, so it is not '
				+ 'editable.'
			: '')));
}

/** The diagonal: a block, a folded sub-system, or an open one's header. */
function diagonalCell(slot, ctx) {
	const { project, selection, hooks, isPath, inside, frame, nameOf, fullOf } = ctx;
	const th = el('th', {
		className: `matrix-self matrix-${slot.kind}${
			slot.kind === 'outside' ? ' matrix-outside'
				: slot.kind === 'block' && isPath.has(slot.name) ? ' matrix-path' : ''}`,
		scope: 'row',
	});
	if (frame.shadow) th.style.setProperty('box-shadow', frame.shadow);

	if (slot.kind === 'outside') {
		th.title = 'The world beyond the model: its row is what comes in from '
			+ 'outside, its column what leaves.';
		// A tile of its own, like every other thing on the diagonal, so the
		// grid does not have one cell that is a bare word. Not a control:
		// there is nothing to select and nothing to open.
		th.append(el('span', { className: 'matrix-block matrix-nowhere' }, OUTSIDE));
		return th;
	}

	// A sub-system: its name, what it holds, and the one control that folds it.
	if (slot.kind === 'group' || slot.kind === 'head') {
		const isOpen = slot.kind === 'head';
		const held = slot.kind === 'group'
			? [
				`${slot.blocks} block${slot.blocks === 1 ? '' : 's'}`,
				slot.systems ? `${slot.systems} sub-system${slot.systems === 1 ? '' : 's'}` : '',
				inside.get(slot.path) ? `${inside.get(slot.path)} flux inside` : '',
			].filter(Boolean).join(', ')
			: '';
		const btn = el('button', {
			className: `matrix-block matrix-system${isOpen ? ' is-open' : ''}`,
			type: 'button',
			title: `${slot.path} \u2014 ${isOpen
				? 'open: the blocks inside it are framed here. Click to fold it up.'
				: `folded up, holding ${held}. Click to open it.`}`,
		});
		btn.dataset.name = slot.path;
		btn.append(el('span', { className: 'matrix-fold' }, isOpen ? '\u25be' : '\u25b8'));
		btn.append(el('span', { className: 'matrix-system-name' }, slot.local));
		if (!isOpen && held) {
			btn.append(el('span', { className: 'matrix-system-held' }, held));
		}
		btn.addEventListener('click', () => hooks.onToggleSystem?.(slot.path));
		// Selecting it is what the rest of the application means by clicking a
		// sub-system; folding is what this view is for, so the click folds and
		// the selection follows.
		btn.addEventListener('dblclick', (ev) => {
			ev.preventDefault();
			hooks.onSelect?.({ kind: 'system', name: slot.path });
		});
		th.append(btn);
		return th;
	}

	// A block. A click selects it, a double-click opens its settings -- the
	// same two gestures it answers on the diagram and in the tree.
	const kind = isPath.has(slot.name) ? 'farfield' : 'compartment';
	const btn = el('button', {
		className: 'matrix-block', type: 'button',
		title: `${fullOf(slot)} \u2014 its row is what flows out of it, its column `
			+ `what flows in.${isPath.has(slot.name)
				? ' A far-field path: a flux goes into its first fracture cell and '
					+ 'its release comes out of its last.'
				: ''}\nClick to select it, double-click to open its settings.`,
	}, nameOf(slot));
	// What it is shown as, in brackets after its name, as the tree has it.
	const named = ed.findBlock(project, slot.name)?.block;
	if (named && hasSymbol(named)) {
		btn.append(' (', el('span', { className: 'matrix-symbol' }, ...symbolNodes(named.symbol)), ')');
	}
	btn.dataset.name = slot.name;
	if (selection?.name === slot.name) btn.classList.add('is-selected');
	// Whatever colour the block was given on the diagram. Written as a
	// property, never pasted into a style string: the value comes out of a
	// project file. The label is picked from the fill rather than from the
	// theme, so a dark colour does not hide it.
	const own = colorOf(project, slot.name);
	if (own) paint(btn, own);
	btn.addEventListener('click', () => hooks.onSelect?.({ kind, name: slot.name }));
	btn.addEventListener('dblclick', (ev) => {
		ev.preventDefault();
		hooks.onOpenSettings?.(slot.name);
	});
	th.append(btn);
	return th;
}

/** A fill, with the label and the marks on it inked from that fill. */
function paint(el2, color) {
	el2.style.setProperty('background-color', color);
	el2.style.setProperty('--own', color);
	const ink = inkFor(color);
	if (!ink) return;
	el2.style.setProperty('color', ink.strong);
	el2.style.setProperty('--matrix-ink', ink.strong);
	el2.style.setProperty('--matrix-ink-dim', ink.dim);
}

/** The transfers in one cell, newest last. */
function cellStack(here, { project, selection, hooks, down, from, to }) {
	const stack = el('div', { className: 'matrix-stack' });
	for (const t of here) {
		// A source has no `from` key at all; a transfer out of the model has
		// one set to null.
		const isSource = t.from === undefined || t._source;
		const btn = el('button', {
			className: `matrix-cell${
				selection?.name === qualifiedName(t) ? ' is-selected' : ''}`,
			type: 'button',
			title: `${qualifiedName(t)}: ${t.rate}\n${from} \u2192 ${to}\n`
				+ 'Click to select it, double-click to open its settings.',
		},
		// The elbow first: it is the one part of the cell that says which of
		// the two names on the diagonal is the donor.
		flowArrow(down),
		el('span', { className: 'matrix-flux' },
			el('span', { className: 'matrix-rate' }, t.rate || '0'),
			el('span', { className: 'matrix-name' }, t.name)));
		btn.dataset.name = qualifiedName(t);
		// Its own colour, if it was given one on the diagram. A line's weight
		// and dash are about a line and have nothing to say in a cell, so only
		// the colour crosses.
		const own = ed.connectionLook(t).color;
		if (own) paint(btn, own);
		btn.addEventListener('click', () => hooks.onSelect?.({
			kind: isSource ? 'inflow' : 'transfer', name: qualifiedName(t),
		}));
		// The same gesture the diagram, the tree and the diagonal use.
		btn.addEventListener('dblclick', (ev) => {
			ev.preventDefault();
			hooks.onOpenSettings?.(qualifiedName(t));
		});
		stack.append(btn);
	}
	return stack;
}

/**
 * Several fluxes across a folded boundary, as a count.
 *
 * Clicking it opens the sub-system, which is where each of them can be read
 * against the block it actually joins.
 */
function summaryCell(here, { hooks, down, from, to, open }) {
	const names = here.map((t) => qualifiedName(t));
	const shown = names.slice(0, 8);
	const stack = el('div', { className: 'matrix-stack' });
	const btn = el('button', {
		className: 'matrix-cell matrix-summary', type: 'button',
		title: `${here.length} fluxes from ${from} to ${to}:\n  ${shown.join('\n  ')}`
			+ `${names.length > shown.length ? `\n  \u2026and ${names.length - shown.length} more` : ''}`
			+ `\nClick to open ${open} and read them against the blocks they join.`,
	},
	flowArrow(down),
	el('span', { className: 'matrix-flux' },
		el('span', { className: 'matrix-rate' }, `${here.length} fluxes`),
		el('span', { className: 'matrix-name' }, `open ${baseName(open)}`)));
	btn.addEventListener('click', () => hooks.onToggleSystem?.(open));
	stack.append(btn);
	return stack;
}

/** The `+` that adds a transfer between one pair. */
function addButton({ project, hooks, a, b, isPath, extra }) {
	const what = b === null
		? `Add an outflow from ${a} to outside the model`
		: a === null
			? `Add an inflow into ${b} from outside the model`
			: isPath.has(a)
				? `Deliver ${a}\u2019s release into ${b}`
				: `Add a transfer from ${a} to ${b}`
					+ (isPath.has(b) ? ', into its first fracture cell' : '');
	const btn = el('button', {
		className: `matrix-cell matrix-add${extra ? ' matrix-more' : ''}`,
		type: 'button',
		title: extra ? `${what} alongside the ${extra} already here` : what,
	}, '+');
	btn.addEventListener('click', () => {
		try {
			const nt = ed.addTransfer(project, a, b);
			hooks.onChange?.();
			hooks.onSelect?.({ kind: 'transfer', name: qualifiedName(nt) });
		} catch (e) {
			hooks.onStatus?.(e.message, 'warn');
		}
	});
	return btn;
}
