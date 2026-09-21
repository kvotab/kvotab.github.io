/**
 * The decay chains of a model, drawn.
 *
 * The table beside this says the same thing in rows -- parent, daughter,
 * branching -- and a table is the right shape for editing one number. It is
 * the wrong shape for the question anyone actually has about a set of chains,
 * which is *what shape are they*: how many separate chains there are, which
 * nuclide is the head of each, where a chain forks and how much goes each way,
 * and which member is the end of the line. Eleven rows of `Pu-241 -> Am-241 |
 * 0.99998` do not answer that; four columns of boxes with arrows between them
 * answer it at a glance.
 *
 * Drawn rather than laid out by a library, for the same reason the rest of this
 * tool is: no build step, no dependencies. It is a layered drawing of a
 * directed acyclic graph, which is a hundred lines when the graph is a decay
 * chain -- a few dozen nodes, mostly linear, occasionally forking.
 *
 * Two things the picture says that the table cannot. A pair the database states
 * as a decay in its own right gets a solid arrow with its mode on it (`α`,
 * `β−`); a pair that only exists because this model leaves the members between
 * out gets a dashed one saying how many were left out (`via 5`). And the
 * arrangement itself is the chain's structure: a fork is visibly a fork.
 */

import * as db from '../domain/decaydb.js';

const NS = 'http://www.w3.org/2000/svg';

const svg = (tag, attrs = {}) => {
	const n = document.createElementNS(NS, tag);
	for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, String(v));
	return n;
};

/** A node's box, and the room between boxes. All in user units. */
const NODE_W = 96;
const NODE_H = 34;
const GAP_X = 16;
const GAP_Y = 34;
/** Space between one chain and the next, when several are drawn side by side. */
const GAP_CHAIN = 40;
/** Room over the row of nuclides that are in no chain, for its caption. */
const NOTE_H = 16;
/** The drawing wraps to a new row rather than growing wider than this. */
const DEFAULT_WIDTH = 760;

/**
 * Where every nuclide goes.
 *
 * Pure, and separate from the drawing, so the arrangement can be checked
 * without a browser -- which matters because the arrangement is the part with
 * decisions in it.
 *
 * Layered by longest path from a head, so a nuclide is always drawn below
 * every nuclide that decays into it: the alternative (shortest path) puts a
 * fork's short arm level with its own parent, which reads as two unrelated
 * chains. Within a layer, nodes sit under the average position of their
 * parents -- one barycentre pass, top to bottom -- which is enough to keep a
 * fork's two arms from crossing on chains this shape.
 *
 * Chains that share no nuclide are laid out separately and packed left to
 * right, wrapping when the row is full, so four decay series read as four
 * pictures rather than one wide one.
 *
 * @param {Iterable<string>} names the nuclides the model carries
 * @param {Array<[string, string, number]>} pairs parent, daughter, branching
 * @param {{width?: number}} [opts]
 * @returns {{nodes: Array<{name: string, x: number, y: number, w: number,
 *              h: number, depth: number}>,
 *            edges: Array<{from: string, to: string, branching: number}>,
 *            width: number, height: number, isolated: string[]}}
 *   Every node carries the index of the chain it belongs to, which the
 *   drawing needs to route an arrow past the boxes between its ends without
 *   straying into the chain alongside. `isolated` names the nuclides in no
 *   chain at all; they are placed too, in a captioned row of their own, and
 *   marked `alone`.
 */
export function layoutChains(names, pairs, opts = {}) {
	const width = opts.width ?? DEFAULT_WIDTH;
	const present = new Set(names);
	const live = pairs.filter(([p, d]) => present.has(p) && present.has(d));

	const inChain = new Set();
	for (const [p, d] of live) { inChain.add(p); inChain.add(d); }
	const isolated = [...present].filter((n) => !inChain.has(n));
	if (!inChain.size) {
		return { nodes: [], edges: [], width, height: 0, isolated };
	}

	const parentsOf = new Map([...inChain].map((n) => [n, []]));
	const kidsOf = new Map([...inChain].map((n) => [n, []]));
	// The biggest share of a decay that arrives here, for ordering a fork.
	const inflow = new Map();
	for (const [p, d, branching] of live) {
		parentsOf.get(d).push(p);
		kidsOf.get(p).push(d);
		inflow.set(d, Math.max(inflow.get(d) ?? 0, branching ?? 0));
	}

	// Longest path from a head. Iterated rather than recursed: the graph is
	// acyclic (the database is, and `collapse` cannot invent a cycle), so this
	// settles in as many passes as the chain is long, and a hand-edited
	// `chains` list with a cycle in it stops at the bound instead of hanging.
	const depth = new Map([...inChain].map((n) => [n, 0]));
	for (let pass = 0; pass < inChain.size; pass++) {
		let moved = false;
		for (const n of inChain) {
			const want = Math.max(0, ...parentsOf.get(n).map((p) => depth.get(p) + 1));
			if (want > depth.get(n)) { depth.set(n, want); moved = true; }
		}
		if (!moved) break;
	}

	// Which nuclides belong to the same chain: joined by any pair, in either
	// direction, since a fork's two arms are one chain.
	const home = new Map([...inChain].map((n) => [n, n]));
	const root = (n) => {
		let r = n;
		while (home.get(r) !== r) r = home.get(r);
		return r;
	};
	for (const [p, d] of live) {
		const a = root(p);
		const b = root(d);
		if (a !== b) home.set(a, b);
	}
	const chains = new Map();
	for (const n of inChain) {
		const r = root(n);
		if (!chains.has(r)) chains.set(r, []);
		chains.get(r).push(n);
	}

	// Longest first, so the biggest chain leads and the stragglers fill in.
	const order = [...chains.values()].sort((a, b) => b.length - a.length
		|| (a[0] < b[0] ? -1 : 1));

	const nodes = [];
	// Where the next chain goes, and how tall this row of chains has become.
	let penX = 0;
	let penY = 0;
	let rowH = 0;
	let widest = 0;

	order.forEach((members, chainIndex) => {
		// Rows of this chain, by depth.
		const layers = new Map();
		for (const n of members) {
			const d = depth.get(n);
			if (!layers.has(d)) layers.set(d, []);
			layers.get(d).push(n);
		}
		const depths = [...layers.keys()].sort((a, b) => a - b);

		// Order within a layer: under the middle of the parents, then by the
		// share of the decay that reaches it, then by name -- never by
		// iteration order, which would shuffle the picture between edits. The
		// two arms of a fork have the same parent in the same slot, so it is
		// the second rule that separates them, and it puts the main line of
		// the chain down the left where the eye starts.
		const slot = new Map();
		for (const d of depths) {
			const row = layers.get(d);
			row.sort((a, b) => {
				const ba = mean(parentsOf.get(a).map((p) => slot.get(p) ?? 0));
				const bb = mean(parentsOf.get(b).map((p) => slot.get(p) ?? 0));
				return ba - bb || (inflow.get(b) ?? 0) - (inflow.get(a) ?? 0)
					|| (a < b ? -1 : a > b ? 1 : 0);
			});
			row.forEach((n, i) => slot.set(n, i));
		}

		const cols = Math.max(...depths.map((d) => layers.get(d).length));
		const chainW = cols * NODE_W + (cols - 1) * GAP_X;
		const chainH = depths.length * NODE_H + (depths.length - 1) * GAP_Y;

		// Wrap when this chain would not fit beside the ones already placed.
		if (penX > 0 && penX + chainW > width) {
			penX = 0;
			penY += rowH + GAP_CHAIN;
			rowH = 0;
		}

		depths.forEach((d, rowIndex) => {
			const row = layers.get(d);
			// Centred over the chain's own width, so a chain that forks once
			// does not sit off to one side of its own block.
			const rowW = row.length * NODE_W + (row.length - 1) * GAP_X;
			const left = penX + (chainW - rowW) / 2;
			row.forEach((n, i) => {
				nodes.push({
					name: n,
					x: left + i * (NODE_W + GAP_X),
					y: penY + rowIndex * (NODE_H + GAP_Y),
					w: NODE_W,
					h: NODE_H,
					depth: d,
					chain: chainIndex,
				});
			});
		});

		penX += chainW + GAP_CHAIN;
		rowH = Math.max(rowH, chainH);
		widest = Math.max(widest, penX - GAP_CHAIN);
	});

	// A nuclide with no parent and no daughter in this model still belongs to
	// the model, so it is drawn -- in a row of its own under everything else,
	// captioned by the drawing. Leaving it out silently would make the picture
	// say the model carries nineteen nuclides when it carries twenty-three.
	if (isolated.length && nodes.length) {
		penX = 0;
		penY += rowH + GAP_CHAIN + NOTE_H;
		// `penY` walks down to the top of the last row, so the height owed at
		// the end is one row, not the whole block.
		rowH = NODE_H;
		for (const n of isolated.sort(byMass)) {
			if (penX > 0 && penX + NODE_W > width) {
				penX = 0;
				// Tighter than a chain's rows: there are no arrows to leave
				// room for, and the closer spacing reads as a grid of names
				// rather than as more chains.
				penY += NODE_H + GAP_X;
			}
			nodes.push({
				name: n, x: penX, y: penY, w: NODE_W, h: NODE_H,
				depth: 0, chain: -1, alone: true,
			});
			penX += NODE_W + GAP_X;
			widest = Math.max(widest, penX - GAP_X);
		}
	}

	return {
		nodes,
		edges: live.map(([from, to, branching]) => ({ from, to, branching })),
		// The drawing's own width, which is at most `width` unless one chain
		// is wider than that on its own -- a chain that forks five ways has to
		// be as wide as it is, and the card scrolls.
		width: Math.max(1, widest),
		height: penY + rowH,
		isolated,
	};
}

const mean = (xs) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0);

/** Up the periodic table, then up the mass -- the order the database is in. */
function byMass(a, b) {
	const ra = db.nuclide(a);
	const rb = db.nuclide(b);
	return (ra?.z ?? 0) - (rb?.z ?? 0) || (ra?.a ?? 0) - (rb?.a ?? 0)
		|| (a < b ? -1 : a > b ? 1 : 0);
}

/** `94.4%`, and nothing at all when a branch takes everything. */
function branchLabel(branching) {
	if (branching > 0.9995) return '';
	const pct = branching * 100;
	if (pct >= 1) return `${pct.toPrecision(3)}%`;
	// A rare branch is the interesting one, so it keeps its magnitude rather
	// than being rounded to `0.00%`.
	return `${pct.toPrecision(2)}%`;
}

/**
 * The picture.
 *
 * @param {object} project the raw project, for which indices are enabled
 * @param {Iterable<string>} names
 * @param {Array<[string, string, number]>} pairs
 * @param {{enabled?: Set<string>, halfLife?: (name: string) => string|null,
 *          onPick?: (name: string) => void, width?: number}} [opts]
 * @returns {SVGElement|null} null when there is no chain to draw
 */
export function chainGraph(names, pairs, opts = {}) {
	const enabled = opts.enabled ?? null;
	const halfLifeText = opts.halfLife ?? ((n) => db.halfLifeText(n));
	const kept = [...names];
	const plan = layoutChains(kept, pairs, { width: opts.width });
	if (!plan.nodes.length) return null;

	const pad = 4;
	const root = svg('svg', {
		class: 'cg',
		viewBox: `${-pad} ${-pad} ${plan.width + pad * 2} ${plan.height + pad * 2}`,
		// Its natural size in pixels, not a percentage: at 100% the browser
		// would scale a wide drawing down to fit rather than let the card
		// scroll, and nuclide names set in 11px do not survive being shrunk.
		width: plan.width + pad * 2,
		height: plan.height + pad * 2,
		role: 'img',
		'aria-label': `${plan.nodes.length} nuclides and ${plan.edges.length} `
			+ 'decay pairs between them',
	});

	const defs = svg('defs');
	for (const [id, cls] of [['cg-arrow', 'cg-head'], ['cg-arrow-via', 'cg-head cg-head-via']]) {
		const marker = svg('marker', {
			id, viewBox: '0 0 8 8', refX: 7, refY: 4,
			markerWidth: 5, markerHeight: 5, orient: 'auto-start-reverse',
		});
		marker.append(svg('path', { class: cls, d: 'M 0 0 L 8 4 L 0 8 z' }));
		defs.append(marker);
	}
	root.append(defs);

	const at = new Map(plan.nodes.map((n) => [n.name, n]));

	// Edges first, so a box is never drawn under an arrow.
	const wires = svg('g', { class: 'cg-edges' });
	for (const e of plan.edges) {
		const a = at.get(e.from);
		const b = at.get(e.to);
		if (!a || !b) continue;
		const x1 = a.x + a.w / 2;
		const y1 = a.y + a.h;
		const x2 = b.x + b.w / 2;
		const y2 = b.y;
		const mode = db.directMode(e.from, e.to);
		const via = mode ? 0 : db.stepsBetween(e.from, e.to, kept);
		// A pair whose ends are more than one layer apart -- a nuclide and its
		// grand-daughter, both modelled, with the daughter modelled too -- has
		// a box sitting in the straight line between them, so it goes round:
		// out of the parent's side, down a lane clear of everything it passes,
		// and back into the daughter's side. Drawn straight it would lie under
		// the boxes and read as the arrow between them.
		const bypass = b.depth - a.depth > 1;
		const g = svg('g', {
			class: `cg-edge${mode ? '' : ' is-via'}${bypass ? ' is-bypass' : ''}`,
		});

		let d;
		let label = null;
		if (bypass) {
			// Clear of every box the lane runs past, which is not just the two
			// columns at its ends: a fork in between can be wider than both.
			const span = plan.nodes.filter((n) => n.chain === a.chain
				&& n.depth >= a.depth && n.depth <= b.depth);
			const lane = Math.max(...span.map((n) => n.x + n.w))
				+ Math.min(GAP_CHAIN / 2 - 4, 6 + 5 * (b.depth - a.depth));
			const ya = a.y + a.h / 2;
			const yb = b.y + b.h / 2;
			d = `M ${a.x + a.w} ${ya} C ${lane} ${ya}, ${lane} ${yb}, ${b.x + b.w} ${yb}`;
			// Turned to run down the lane rather than across it: the lane is
			// as narrow as the gap between two columns, and `via 5` set
			// horizontally there would sit on the chain alongside.
			label = { x: lane + 9, y: (ya + yb) / 2, turned: true };
		} else {
			// Straight down where it can be, an S-curve where the daughter is
			// off to one side. Curved rather than dog-legged because a fork of
			// two curves reads as one thing dividing.
			const dy = Math.max(12, (y2 - y1) / 2);
			d = Math.abs(x2 - x1) < 1
				? `M ${x1} ${y1} L ${x2} ${y2}`
				: `M ${x1} ${y1} C ${x1} ${y1 + dy}, ${x2} ${y2 - dy}, ${x2} ${y2}`;
			// Nearer the daughter than the midpoint: at the midpoint the two
			// labels of a fork are 56px apart, which is narrower than either
			// of them, and `98.6% β−` lands on `1.38% α`.
			label = { x: x1 + (x2 - x1) * 0.72, y: (y1 + y2) / 2 + 3, turned: false };
		}
		g.append(svg('path', {
			class: 'cg-wire', d, 'marker-end': `url(#${mode ? 'cg-arrow' : 'cg-arrow-via'})`,
		}));

		// What the arrow is: the decay mode when the database states this pair
		// itself, and how many members were left out when it does not.
		const bits = [branchLabel(e.branching), mode ?? (via ? `via ${via}` : '')]
			.filter(Boolean);
		if (bits.length) {
			const attrs = {
				x: label.x,
				y: label.y,
				...(label.turned
					? { transform: `rotate(-90 ${label.x} ${label.y})` }
					: {}),
			};
			const text = svg('text', { class: 'cg-edge-label', ...attrs });
			text.textContent = bits.join('  ');
			// A halo under the text, so a label over a wire stays readable.
			const halo = svg('text', { class: 'cg-edge-halo', ...attrs });
			halo.textContent = text.textContent;
			g.append(halo, text);
		}
		const title = svg('title');
		title.textContent = `${e.from} → ${e.to}`
			+ `, branching ${e.branching.toPrecision(6)}`
			+ (mode ? ` (${mode})` : via ? ` — through ${via} nuclide`
				+ `${via === 1 ? '' : 's'} this model does not carry` : '');
		g.append(title);
		wires.append(g);
	}
	root.append(wires);

	// Why a box down there has no arrows on it.
	const alone = plan.nodes.filter((n) => n.alone);
	if (alone.length) {
		const note = svg('text', {
			class: 'cg-note',
			x: Math.min(...alone.map((n) => n.x)),
			y: Math.min(...alone.map((n) => n.y)) - 7,
		});
		note.textContent = alone.length === 1
			? 'in no chain in this model:'
			: `in no chain in this model (${alone.length}):`;
		root.append(note);
	}

	const boxes = svg('g', { class: 'cg-nodes' });
	for (const n of plan.nodes) {
		const off = enabled && !enabled.has(n.name);
		const g = svg('g', {
			class: `cg-node${off ? ' is-off' : ''}`,
			transform: `translate(${n.x} ${n.y})`,
			'data-nuclide': n.name,
		});
		g.append(svg('rect', {
			class: 'cg-box', x: 0, y: 0, width: n.w, height: n.h, rx: 5,
		}));
		const name = svg('text', { class: 'cg-name', x: n.w / 2, y: 14 });
		name.textContent = n.name;
		g.append(name);
		const hl = halfLifeText(n.name);
		if (hl) {
			const sub = svg('text', { class: 'cg-hl', x: n.w / 2, y: 26 });
			sub.textContent = hl;
			g.append(sub);
		}
		const title = svg('title');
		const kids = plan.edges.filter((e) => e.from === n.name);
		title.textContent = `${n.name}${hl ? ` — half-life ${hl}` : ''}`
			+ (off ? ' — disabled, so it takes no part in a simulation' : '')
			+ (kids.length
				? `; decays to ${kids.map((k) => k.to).join(', ')}`
				: n.alone
					? '; nothing in this model decays into it and it decays'
						+ ' into nothing this model carries'
					: '; the end of the chain in this model');
		g.append(title);
		if (opts.onPick) {
			g.setAttribute('tabindex', '0');
			g.setAttribute('role', 'button');
			g.addEventListener('click', () => opts.onPick(n.name));
			g.addEventListener('keydown', (ev) => {
				if (ev.key === 'Enter' || ev.key === ' ') {
					ev.preventDefault();
					opts.onPick(n.name);
				}
			});
		}
		boxes.append(g);
	}
	root.append(boxes);
	return root;
}
