/**
 * Automatic diagram layout.
 *
 * A compartment model is a flow, so it is drawn the way a flow is drawn: a
 * layered (Sugiyama) layout, left to right along the transfers. The three
 * classic stages are all here --
 *
 *   1. layering    which column a node belongs in, from the longest path
 *                  along the transfers, with cycles broken first
 *   2. ordering    the top-to-bottom order inside each column, chosen to cut
 *                  the number of times one line crosses another
 *   3. coordinates where each node actually goes, pulled towards the middle
 *                  of what it is joined to without letting boxes touch
 *
 * -- plus two things the textbook version leaves out and a model needs:
 *
 *   * Real models come apart into several independent flows. Each is laid out
 *     on its own and the results are packed into rows, so a model of twelve
 *     unconnected sub-systems reads as a grid rather than one tall column.
 *
 *   * Only compartments are in the flow. Expressions, parameters, lookup
 *     tables and reductions supply it, so they hang underneath in rows
 *     ordered by how far they are from the flow -- an expression that feeds a
 *     transfer directly above the parameters that feed the expression -- and
 *     each one sits under whatever reads it. That is `hangRows`.
 *
 * Everything here is deliberately free of the project object: it takes nodes
 * with sizes and edges with names, and gives back positions. That keeps the
 * graph work testable on its own, and keeps this module out of the import
 * cycle with `edit.js`, which is what builds the graph.
 *
 * Positions are top-left corners, which is what the diagram draws with.
 */

/** How much air to leave between two boxes, if the caller says nothing. */
const GAP_X = 124;
const GAP_Y = 58;

// --- 1. layering -----------------------------------------------------------

/**
 * Drops the edges that close a cycle, by depth-first search: an edge to a node
 * already on the stack is a back edge. What is left is a DAG over the same
 * nodes.
 *
 * Cycles are not a defect in a compartment model -- water moves between a pool
 * and its sediment in both directions -- so the pair has to be laid out as one
 * direction plus a return, and this decides which direction wins: whichever is
 * met first, which for a model read in file order is the one written first.
 */
/**
 * The pitch of the lattice a diagram is laid out on.
 *
 * One number for three things that have to agree: what the automatic layout
 * rounds to, what a drag snaps to, and what the grid behind the canvas is
 * drawn at. They did not agree before -- the grid was a fixed 20px screen
 * lattice while a drag snapped to 10 model units -- and a grid that is not the
 * thing blocks land on is a grid that lies about alignment.
 */
export const GRID = 10;

/** A coordinate on that lattice. */
export const onGrid = (v) => Math.round(v / GRID) * GRID;

export function acyclic(ids, edges) {
	const out = new Map(ids.map((id) => [id, []]));
	for (const e of edges) {
		if (out.has(e.from) && out.has(e.to)) out.get(e.from).push(e);
	}

	const WHITE = 0; const GREY = 1; const BLACK = 2;
	const state = new Map(ids.map((id) => [id, WHITE]));
	const kept = [];

	for (const root of ids) {
		if (state.get(root) !== WHITE) continue;
		state.set(root, GREY);
		const stack = [{ id: root, i: 0 }];
		while (stack.length) {
			const top = stack[stack.length - 1];
			const list = out.get(top.id);
			if (top.i >= list.length) {
				state.set(top.id, BLACK);
				stack.pop();
				continue;
			}
			const e = list[top.i++];
			const s = state.get(e.to);
			if (s === GREY) continue; // a back edge, and a self loop
			kept.push(e);
			if (s === WHITE) {
				state.set(e.to, GREY);
				stack.push({ id: e.to, i: 0 });
			}
		}
	}
	return kept;
}

/**
 * The column for each node: the longest path to it, so a node sits one to the
 * right of everything that flows into it.
 *
 * Then sources are pulled right. A compartment whose only outflow lands five
 * columns along would otherwise sit alone at the far left with one very long
 * line across the diagram; moving it to just left of what it feeds costs
 * nothing and removes the line.
 */
export function rankNodes(ids, dag) {
	const succ = new Map(ids.map((id) => [id, []]));
	const pred = new Map(ids.map((id) => [id, []]));
	for (const e of dag) {
		succ.get(e.from).push(e.to);
		pred.get(e.to).push(e.from);
	}

	const rank = new Map(ids.map((id) => [id, 0]));
	const left = new Map(ids.map((id) => [id, pred.get(id).length]));
	const queue = ids.filter((id) => left.get(id) === 0);
	for (let head = 0; head < queue.length; head++) {
		const u = queue[head];
		for (const v of succ.get(u)) {
			rank.set(v, Math.max(rank.get(v), rank.get(u) + 1));
			left.set(v, left.get(v) - 1);
			if (left.get(v) === 0) queue.push(v);
		}
	}

	for (const id of ids) {
		if (pred.get(id).length || !succ.get(id).length) continue;
		let earliest = Infinity;
		for (const v of succ.get(id)) earliest = Math.min(earliest, rank.get(v));
		if (Number.isFinite(earliest)) rank.set(id, earliest - 1);
	}

	let lowest = Infinity;
	for (const r of rank.values()) lowest = Math.min(lowest, r);
	if (Number.isFinite(lowest) && lowest !== 0) {
		for (const id of ids) rank.set(id, rank.get(id) - lowest);
	}
	return rank;
}

// --- 2. ordering -----------------------------------------------------------

/**
 * Splits an edge that spans more than one column into a chain of one-column
 * edges through invisible nodes. Their names start with a `#`, which no block
 * name can, so they cannot collide with a real one.
 *
 * Without them the ordering stage cannot see a line that skips a column, so it
 * happily arranges the middle column so that the line runs straight through a
 * box. They take no height, only a slot in the order and a slice of the gap,
 * which keeps a lane for the line without spreading the diagram out.
 *
 * Past a certain size they stop being worth it. The root of a landscape model
 * is a hundred and fifty sub-systems joined by hundreds of transfers, and
 * splitting every long one of those makes thousands of placeholders: the
 * ordering slows to a crawl and the lanes they hold open make the diagram tens
 * of thousands of units tall. So there is a budget, and over it the edges are
 * left whole -- a diagram that large is going to be read by drilling into a
 * sub-system anyway.
 */
function withDummies(dag, rank, budget) {
	let needed = 0;
	for (const e of dag) needed += Math.max(0, rank.get(e.to) - rank.get(e.from) - 1);
	if (needed > budget) return { edges: dag.map((e) => ({ ...e })), dummies: [] };

	const edges = [];
	const dummies = [];
	let n = 0;
	for (const e of dag) {
		const span = rank.get(e.to) - rank.get(e.from);
		if (span <= 1) { edges.push({ ...e }); continue; }
		let prev = e.from;
		for (let r = rank.get(e.from) + 1; r < rank.get(e.to); r++) {
			const id = `#${n++}`;
			dummies.push({ id, rank: r });
			edges.push({ from: prev, to: id });
			prev = id;
		}
		edges.push({ from: prev, to: e.to });
	}
	return { edges, dummies };
}

/**
 * How many pairs of edges between two adjacent columns cross.
 *
 * Barth, Junger and Mutzel's counting method: walk the edges in the order
 * their upper ends appear and, for each, count the ones already seen that end
 * below it, using an accumulator tree so the count is a walk up the tree
 * rather than a scan of everything seen so far. The obvious nested loop is
 * quadratic in the number of edges, which on the largest model in the corpus
 * meant tens of seconds inside the ordering loop.
 */
function crossings(upper, lower, down) {
	const at = new Map(lower.map((id, i) => [id, i]));
	const ends = [];
	for (const u of upper) {
		const to = (down.get(u) ?? [])
			.map((v) => at.get(v))
			.filter((i) => i !== undefined)
			.sort((a, b) => a - b);
		ends.push(...to);
	}
	if (!ends.length || !lower.length) return 0;

	let leaves = 1;
	while (leaves < lower.length) leaves *= 2;
	const tree = new Int32Array(2 * leaves - 1);
	const first = leaves - 1;

	let total = 0;
	for (const e of ends) {
		let i = e + first;
		tree[i]++;
		while (i > 0) {
			// Coming up from a left child, everything under the right sibling
			// was seen earlier and ends below: those are the crossings.
			if (i % 2) total += tree[i + 1];
			i = (i - 1) >> 1;
			tree[i]++;
		}
	}
	return total;
}

/**
 * Crossings between two neighbouring nodes' own edges, in the order given.
 * Enough to decide whether swapping them helps, and it costs their two degrees
 * rather than a recount of the whole column.
 */
function pairCrossings(a, b, side, at) {
	const ends = (id) => (side.get(id) ?? []).map((v) => at.get(v)).filter((i) => i !== undefined);
	const first = ends(a);
	const second = ends(b);
	let n = 0;
	for (const i of first) for (const j of second) if (j < i) n++;
	return n;
}

/**
 * The weighted median Gansner et al. use: the middle of the positions, and
 * when there are two middles, the one whose half is tighter. -1 means there
 * was nothing to take a median of.
 */
function median(xs) {
	if (!xs.length) return -1;
	const s = [...xs].sort((a, b) => a - b);
	const m = s.length >> 1;
	if (s.length % 2) return s[m];
	const lo = s[m - 1] - s[0];
	const hi = s[s.length - 1] - s[m];
	if (lo === hi) return (s[m - 1] + s[m]) / 2;
	return (s[m - 1] * hi + s[m] * lo) / (lo + hi);
}

/** The plain middle, for placing along a row where -1 is a real position. */
function middle(xs) {
	if (!xs.length) return null;
	const s = [...xs].sort((a, b) => a - b);
	const m = s.length >> 1;
	return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

/**
 * Orders the nodes inside each column so that as few lines cross as possible.
 *
 * The standard heuristic: sweep down putting every node at the median position
 * of what feeds it, sweep up doing the same with what it feeds, then try
 * swapping neighbours to see whether that helps. A sweep is kept only when the
 * total improves, so the result is never worse than where it started.
 */
function orderLayers(layers, down, up, rounds = 8) {
	const total = (ls) => {
		let n = 0;
		for (let r = 0; r + 1 < ls.length; r++) n += crossings(ls[r], ls[r + 1], down);
		return n;
	};

	let best = layers.map((l) => [...l]);
	let bestCount = total(best);
	let current = layers.map((l) => [...l]);

	for (let round = 0; round < rounds && bestCount > 0; round++) {
		const forward = round % 2 === 0;
		const from = forward ? 1 : current.length - 2;
		const step = forward ? 1 : -1;
		for (let r = from; r >= 0 && r < current.length; r += step) {
			const neighbours = forward ? up : down;
			const fixed = new Map(current[r - step].map((id, i) => [id, i]));
			const key = new Map();
			for (const id of current[r]) {
				const ps = (neighbours.get(id) ?? [])
					.map((n) => fixed.get(n))
					.filter((i) => i !== undefined);
				key.set(id, median(ps));
			}
			// A node with no neighbour on that side keeps where it was, which
			// is what the -1 means: the stable sort leaves it in place.
			const was = new Map(current[r].map((id, i) => [id, i]));
			current[r] = [...current[r]].sort((a, b) => {
				const ka = key.get(a); const kb = key.get(b);
				if (ka < 0 || kb < 0) return was.get(a) - was.get(b);
				return ka - kb || was.get(a) - was.get(b);
			});
		}

		transpose(current, down, up);
		const count = total(current);
		if (count < bestCount) {
			bestCount = count;
			best = current.map((l) => [...l]);
		} else {
			current = best.map((l) => [...l]);
		}
	}
	return best;
}

/**
 * Swaps neighbours for as long as doing so removes crossings.
 *
 * The decision is local: whether two adjacent nodes cross depends only on
 * their own edges, to the column on either side, so each check costs their
 * degrees instead of a recount of the column.
 */
function transpose(layers, down, up) {
	let improved = true;
	let guard = 0;
	while (improved && guard++ < 8) {
		improved = false;
		for (let r = 0; r < layers.length; r++) {
			const below = r + 1 < layers.length
				? new Map(layers[r + 1].map((id, i) => [id, i])) : null;
			const above = r > 0
				? new Map(layers[r - 1].map((id, i) => [id, i])) : null;
			for (let i = 0; i + 1 < layers[r].length; i++) {
				const a = layers[r][i];
				const b = layers[r][i + 1];
				let now = 0;
				let swapped = 0;
				if (below) {
					now += pairCrossings(a, b, down, below);
					swapped += pairCrossings(b, a, down, below);
				}
				if (above) {
					now += pairCrossings(a, b, up, above);
					swapped += pairCrossings(b, a, up, above);
				}
				if (swapped < now) {
					layers[r][i] = b;
					layers[r][i + 1] = a;
					improved = true;
				}
			}
		}
	}
}

// --- 3. coordinates --------------------------------------------------------

/**
 * Places boxes along one axis in a fixed order, each as near its target as the
 * ones before it allow, then relieves the pile-up that leaves.
 *
 * The forward pass can only push a box further along, so a column with one
 * badly placed node at the top drifts. The backward pass gives every box its
 * target back wherever the gap on both sides permits, which is what keeps a
 * chain of nodes with a common neighbour lined up on it.
 *
 * @param {number[]} size  extent of each box, in order
 * @param {number[]} want  where each box would like to start
 * @param {number|number[]} gap  between every pair, or one per pair: a lane
 *        held open for a line needs less room than a box does
 */
export function packLine(size, want, gap) {
	const n = size.length;
	const between = (i) => (Array.isArray(gap) ? gap[i] : gap);
	const at = new Array(n);
	let cursor = -Infinity;
	for (let i = 0; i < n; i++) {
		at[i] = cursor === -Infinity ? want[i] : Math.max(cursor, want[i]);
		cursor = at[i] + size[i] + between(i);
	}
	for (let i = n - 1; i >= 0; i--) {
		const low = i > 0 ? at[i - 1] + size[i - 1] + between(i - 1) : -Infinity;
		const high = i < n - 1 ? at[i + 1] - between(i) - size[i] : Infinity;
		at[i] = Math.min(Math.max(want[i], low), Math.max(high, low));
	}
	return at;
}

// --- putting it together ---------------------------------------------------

/**
 * Lays out one connected flow, in the columns it ranks its nodes into.
 *
 * @param {Array<{id: string, w: number, h: number}>} nodes
 * @param {Array<{from: string, to: string}>} edges
 * @returns {{at: Map<string, {x: number, y: number}>, w: number, h: number}}
 *          positions relative to (0, 0), and the size of what they occupy
 */
export function layerFlow(nodes, edges, { gapX = GAP_X, gapY = GAP_Y, rounds = 8 } = {}) {
	const ids = nodes.map((n) => n.id);
	const box = new Map(nodes.map((n) => [n.id, n]));
	const dag = acyclic(ids, edges);
	const rank = rankNodes(ids, dag);

	// One placeholder per node is enough for the models this is for, and stops
	// the largest from paying for thousands of them.
	const { edges: short, dummies } = withDummies(dag, rank, Math.max(64, ids.length));
	const invisible = new Set(dummies.map((d) => d.id));
	for (const d of dummies) {
		rank.set(d.id, d.rank);
		box.set(d.id, { id: d.id, w: 0, h: 0 });
	}

	const depth = Math.max(0, ...rank.values()) + 1;
	const layers = Array.from({ length: depth }, () => []);
	for (const id of ids) layers[rank.get(id)].push(id);
	for (const d of dummies) layers[d.rank].push(d.id);

	const down = new Map();
	const up = new Map();
	for (const e of short) {
		if (!down.has(e.from)) down.set(e.from, []);
		if (!up.has(e.to)) up.set(e.to, []);
		down.get(e.from).push(e.to);
		up.get(e.to).push(e.from);
	}

	const ordered = orderLayers(layers, down, up, rounds);

	// Columns: each as wide as its widest box, so one long name does not push
	// every later column out with it.
	const colX = [];
	let x = 0;
	for (const layer of ordered) {
		const wide = Math.max(0, ...layer.map((id) => box.get(id).w));
		colX.push({ x, w: wide });
		x += wide + gapX;
	}

	// Rows: start stacked, then pull each node towards the middle of what it
	// joins, alternating which side does the pulling so both get a say.
	const at = new Map();
	for (const layer of ordered) {
		let y = 0;
		for (const id of layer) {
			at.set(id, y);
			y += box.get(id).h + gapY;
		}
	}
	const centre = (id) => at.get(id) + box.get(id).h / 2;
	for (let pass = 0; pass < 6; pass++) {
		const forward = pass % 2 === 0;
		const sweep = [...ordered.keys()];
		if (!forward) sweep.reverse();
		for (const r of sweep) {
			const layer = ordered[r];
			const neighbours = forward ? up : down;
			const want = layer.map((id) => {
				const ns = (neighbours.get(id) ?? []).filter((n) => at.has(n));
				if (!ns.length) return at.get(id);
				const m = ns.reduce((s, n) => s + centre(n), 0) / ns.length;
				return m - box.get(id).h / 2;
			});
			// A lane held open for a line needs less room beside it than a
			// box does.
			const gaps = layer.slice(0, -1).map((id, i) => (
				invisible.has(id) || invisible.has(layer[i + 1]) ? gapY / 4 : gapY));
			const placed = packLine(layer.map((id) => box.get(id).h), want, gaps);
			layer.forEach((id, i) => at.set(id, placed[i]));
		}
	}

	let top = Infinity;
	for (const id of ids) top = Math.min(top, at.get(id));
	if (!Number.isFinite(top)) top = 0;

	const out = new Map();
	let right = 0;
	let bottom = 0;
	for (let r = 0; r < ordered.length; r++) {
		for (const id of ordered[r]) {
			if (invisible.has(id)) continue; // it holds a lane open, nothing more
			const n = box.get(id);
			// Centre a narrow box in its column, so a row of mixed sizes reads
			// as a row rather than as a left-aligned list.
			const px = colX[r].x + (colX[r].w - n.w) / 2;
			const py = at.get(id) - top;
			out.set(id, { x: px, y: py });
			right = Math.max(right, px + n.w);
			bottom = Math.max(bottom, py + n.h);
		}
	}
	return { at: out, w: right, h: bottom };
}

/** The connected pieces of a graph, as lists of node ids. */
export function components(ids, edges) {
	const parent = new Map(ids.map((id) => [id, id]));
	const find = (a) => {
		let r = a;
		while (parent.get(r) !== r) r = parent.get(r);
		while (parent.get(a) !== r) { const next = parent.get(a); parent.set(a, r); a = next; }
		return r;
	};
	for (const e of edges) {
		if (!parent.has(e.from) || !parent.has(e.to)) continue;
		const a = find(e.from); const b = find(e.to);
		if (a !== b) parent.set(a, b);
	}
	const groups = new Map();
	for (const id of ids) {
		const root = find(id);
		if (!groups.has(root)) groups.set(root, []);
		groups.get(root).push(id);
	}
	return [...groups.values()];
}

/**
 * Lays out a whole flow -- however many separate pieces it is in -- and packs
 * the pieces into rows.
 *
 * The pieces go biggest first, so the main flow of the model is at the top
 * left where a reader starts, and a row wraps at whatever is widest: either
 * the widest single piece, or a width that keeps the whole thing roughly the
 * shape of the pane it is drawn in.
 */
export function layoutFlow(nodes, edges, opts = {}) {
	const { gapX = GAP_X, gapY = GAP_Y } = opts;
	if (!nodes.length) return { at: new Map(), w: 0, h: 0 };

	const pieces = components(nodes.map((n) => n.id), edges)
		.map((ids) => {
			const set = new Set(ids);
			return layerFlow(
				nodes.filter((n) => set.has(n.id)),
				edges.filter((e) => set.has(e.from) && set.has(e.to)),
				opts,
			);
		})
		.sort((a, b) => b.w * b.h - a.w * a.h || b.w - a.w);

	const area = pieces.reduce((s, p) => s + (p.w + gapX) * (p.h + gapY), 0);
	const widest = Math.max(...pieces.map((p) => p.w));
	// 16:9 is the shape of the pane this ends up in, and a diagram of the same
	// shape needs the least zooming out to read.
	const limit = Math.max(widest, Math.sqrt(area * (16 / 9)));

	const at = new Map();
	let x = 0;
	let y = 0;
	let rowH = 0;
	let right = 0;
	for (const piece of pieces) {
		if (x > 0 && x + piece.w > limit) { x = 0; y += rowH + gapY * 2; rowH = 0; }
		for (const [id, p] of piece.at) at.set(id, { x: x + p.x, y: y + p.y });
		right = Math.max(right, x + piece.w);
		rowH = Math.max(rowH, piece.h);
		x += piece.w + gapX * 1.5;
	}
	return { at, w: right, h: y + rowH };
}

/**
 * Places the blocks that supply a flow, in rows underneath it.
 *
 * Which row comes from how far a block is from the flow: a block nothing else
 * here reads is in the first row, and a block read only by blocks in that row
 * is in the second. So an expression sits directly under the transfer it
 * feeds, and the parameters it reads sit under it -- the diagram reads
 * upwards, from what a number is made of to what it is used for.
 *
 * Where in the row comes from what the block is joined to, in both directions:
 * the middle of everything already placed that either reads it or is read by
 * it. That is the same median that orders the flow, applied along the row.
 *
 * @param {Array<{id: string, w: number, h: number}>} nodes  the supply blocks
 * @param {Array<{from: string, to: string}>} links  `from` is read by `to`,
 *        over every name in the model, not only these
 * @param {Map<string, {x: number, y: number}>} anchors  centres of everything
 *        already on the diagram: the flow's nodes, and the midpoints of its
 *        lines, which is where an influence into a transfer lands
 */
export function hangRows(nodes, links, anchors, { top = 0, gapX = GAP_X, gapY = GAP_Y } = {}) {
	const at = new Map();
	if (!nodes.length) return { at, h: 0 };

	const mine = new Map(nodes.map((n) => [n.id, n]));
	const readers = new Map(nodes.map((n) => [n.id, []]));
	const reads = new Map(nodes.map((n) => [n.id, []]));
	for (const l of links) {
		if (mine.has(l.from)) readers.get(l.from).push(l.to);
		if (mine.has(l.to)) reads.get(l.to).push(l.from);
	}

	// Distance from the flow, counting only steps between these blocks. The
	// visiting set is not defensive tidiness: a model can name a block that
	// names it back, and the diagram still has to be drawn.
	const depth = new Map();
	const visiting = new Set();
	const depthOf = (id) => {
		if (depth.has(id)) return depth.get(id);
		if (visiting.has(id)) return 0;
		visiting.add(id);
		let d = 0;
		for (const r of readers.get(id)) {
			if (mine.has(r)) d = Math.max(d, depthOf(r) + 1);
		}
		visiting.delete(id);
		depth.set(id, d);
		return d;
	};
	for (const n of nodes) depthOf(n.id);

	const byDepth = new Map();
	for (const n of nodes) {
		const d = depth.get(n.id);
		if (!byDepth.has(d)) byDepth.set(d, []);
		byDepth.get(d).push(n);
	}
	const order = [...byDepth.keys()].sort((a, b) => a - b);

	const gap = gapX / 2;
	let left = Infinity;
	let right = -Infinity;
	for (const p of anchors.values()) {
		left = Math.min(left, p.x);
		right = Math.max(right, p.x);
	}
	if (!Number.isFinite(left)) { left = 0; right = 0; }

	const widest = Math.max(...nodes.map((n) => n.w));
	// Wide enough for the flow above, and wide enough that this many blocks do
	// not end up in a column: whichever is more. A tall narrow band is as hard
	// to read as a long thin one, and 16:9 is the shape of the pane both are
	// drawn in.
	const bulk = nodes.reduce((a, n) => a + (n.w + gapX) * (n.h + gapY), 0);
	const edge = left + Math.max(right - left, widest, Math.sqrt(bulk * (16 / 9)));

	// Centre x of everything already on the diagram: the flow to begin with,
	// and each row as it is placed.
	const xOf = new Map([...anchors].map(([id, p]) => [id, p.x]));

	/**
	 * Puts one row in place along x.
	 *
	 * Blocks go where they want to be -- the middle of everything they are
	 * joined to -- in the topmost lane with room for them there. When several
	 * want the same place they stack under it in lanes, rather than being
	 * pushed along a row away from whatever reads them: that is what makes a
	 * row of 250 parameters legible instead of 25,000 units wide.
	 *
	 * Both extremes have to work, so the run of space a block may use is
	 * worked out first. Blocks whose wanted positions would collide are one
	 * group, and a group has the space from where it starts to wherever the
	 * next group does -- so evenly spread blocks each land exactly where they
	 * want, and a hundred blocks all wanting one place share the width
	 * between them.
	 */
	const placeRow = (row) => {
		const want = new Map();
		for (const n of row) {
			const xs = [...readers.get(n.id), ...reads.get(n.id)]
				.map((other) => xOf.get(other))
				.filter((v) => v !== undefined);
			const m = middle(xs);
			if (m !== null) want.set(n.id, m);
		}
		const sorted = [...row].sort((a, b) => {
			const wa = want.has(a.id) ? want.get(a.id) : Infinity;
			const wb = want.has(b.id) ? want.get(b.id) : Infinity;
			return wa - wb;
		});

		const groups = [];
		const loose = [];
		for (const n of sorted) {
			if (!want.has(n.id)) { loose.push(n); continue; }
			const wants = want.get(n.id) - n.w / 2;
			const last = groups[groups.length - 1];
			if (last && wants < last.end) {
				last.items.push({ node: n, wants });
				last.end += n.w + gap;
			} else {
				groups.push({ start: wants, end: wants + n.w + gap, items: [{ node: n, wants }] });
			}
		}

		const lanes = [];
		const lane = [];
		const xs = [];
		for (let g = 0; g < groups.length; g++) {
			const { start, items } = groups[g];
			// A group runs as far as the next one starts: that is exactly the
			// space nothing else wants, and no more.
			const stop = Math.max(
				g + 1 < groups.length ? groups[g + 1].start : edge,
				start + Math.max(...items.map((i) => i.node.w)),
			);
			for (const { node, wants } of items) {
				// The topmost lane with room where it wants to be. Lanes carry
				// across groups, so two groups cannot run into each other.
				let l = 0;
				let x = wants;
				for (; l < lanes.length; l++) {
					x = Math.max(wants, lanes[l]);
					if (x + node.w <= stop) break;
				}
				if (l === lanes.length) { lanes.push(-Infinity); x = wants; }
				lanes[l] = x + node.w + gap;
				lane.push(l);
				xs.push(x);
			}
		}

		// Blocks joined to nothing that has a position -- a spare parameter --
		// have nowhere in particular to be, so they fill rows of their own
		// below, wrapping at the width of the diagram.
		let l = lanes.length;
		let cursor = left;
		for (const n of loose) {
			if (cursor > left && cursor + n.w > edge) { l++; cursor = left; }
			while (l >= lanes.length) lanes.push(-Infinity);
			lane.push(l);
			xs.push(cursor);
			cursor += n.w + gap;
		}

		return {
			nodes: [...groups.flatMap((g) => g.items.map((i) => i.node)), ...loose],
			xs,
			lane,
			lanes: lanes.length,
		};
	};

	// Three sweeps, down then up then down. The first can only place a row
	// against the rows above it, so a block whose every neighbour is further
	// from the flow -- an expression written in terms of other expressions --
	// has nothing to go on and lands at the left. The sweep back up gives it
	// the positions of the rows below, and the last sweep settles the rest
	// against that.
	const plan = new Map();
	for (let pass = 0; pass < 3; pass++) {
		const sweep = pass % 2 === 0 ? order : [...order].reverse();
		for (const d of sweep) {
			const row = placeRow(byDepth.get(d));
			plan.set(d, row);
			row.nodes.forEach((n, i) => xOf.set(n.id, row.xs[i] + n.w / 2));
		}
	}

	let y = top;
	for (const d of order) {
		const row = plan.get(d);
		const laneH = new Array(row.lanes).fill(0);
		row.nodes.forEach((n, i) => { laneH[row.lane[i]] = Math.max(laneH[row.lane[i]], n.h); });
		const laneY = [];
		let below = y;
		for (const h of laneH) {
			laneY.push(below);
			// Lanes of one row are a group, so they sit closer together than
			// one row does to the next.
			below += h + gapY / 2;
		}
		row.nodes.forEach((n, i) => {
			at.set(n.id, { x: row.xs[i], y: laneY[row.lane[i]] + (laneH[row.lane[i]] - n.h) / 2 });
		});
		y = below + gapY / 2;
	}
	return { at, h: y - gapY - top };
}

// --- 4. lining up by hand --------------------------------------------------

/**
 * The eight ways a hand-picked set of boxes can be tidied: six edges to line
 * them up on, and two directions to spread them along.
 *
 * `centre` and `middle` are the two axes of the same idea, named the way every
 * drawing program names them -- centre across, middle down -- so that a menu
 * built from this list reads the way people already expect it to.
 */
export const ARRANGEMENTS = [
	'left', 'centre', 'right', 'top', 'middle', 'bottom', 'across', 'down',
];

/**
 * Equal gaps, not equal centres.
 *
 * With boxes of one size the two rules agree, and a diagram of equal blocks is
 * the ordinary case -- but when the sizes differ it is the space between them
 * that the eye reads as even, which is why the drawing programs that offer
 * only one rule offer this one.
 *
 * The span is preserved exactly: the first box in order keeps its leading edge
 * and the last keeps its trailing one, because the gaps are what is left of
 * the span after the boxes themselves are taken out of it. That remainder can
 * be negative, when the boxes are wider than the space they sit in; they are
 * then spread to overlap evenly rather than refusing to move, which is what
 * asking to spread out boxes that cannot fit has to mean.
 */
function spread(boxes, at, axis, span, lo, hi) {
	// By leading edge, and by the order given when two share one -- Array.sort
	// is stable, so that second rule needs no code.
	const order = boxes.map((_, i) => i).sort((a, b) => boxes[a][axis] - boxes[b][axis]);
	const total = boxes.reduce((s, b) => s + b[span], 0);
	const gap = ((hi - lo) - total) / (boxes.length - 1);
	// Accumulated unrounded and rounded only on the way out, so the error
	// stays within half a unit of the true position instead of gathering.
	let edge = lo;
	for (const i of order) {
		at[i] = { ...at[i], [axis]: Math.round(edge) };
		edge += boxes[i][span] + gap;
	}
	return at;
}

/**
 * Where a hand-picked set of boxes goes when it is lined up or spread out.
 *
 * The lines are drawn through the extent of the selection itself -- align left
 * takes the leftmost left edge, align centre the middle of the whole -- which
 * is "align selected objects" and not "align to the page". There is no page
 * here to align to: the canvas is unbounded.
 *
 * Pure geometry, like the rest of this module: boxes in, positions out. The
 * boxes must be normalised, with no negative widths, and their positions are
 * top-left corners as everything here uses.
 *
 * @param {{x: number, y: number, w: number, h: number}[]} boxes
 * @param {string} how one of `ARRANGEMENTS`
 * @returns {{x: number, y: number}[]} the corners, in the order given
 */
export function alignBoxes(boxes, how) {
	if (!ARRANGEMENTS.includes(how)) throw new Error(`No such arrangement: '${how}'`);
	const at = boxes.map((b) => ({ x: Math.round(b.x), y: Math.round(b.y) }));
	// One box is already lined up with itself. Every rule below happens to be
	// the identity on a single box anyway -- as is a spread of two, whose two
	// boxes *are* the ends of the span -- but a spread of one would share the
	// space out between no gaps at all, which is a division by zero.
	if (boxes.length < 2) return at;

	const left = Math.min(...boxes.map((b) => b.x));
	const right = Math.max(...boxes.map((b) => b.x + b.w));
	const top = Math.min(...boxes.map((b) => b.y));
	const bottom = Math.max(...boxes.map((b) => b.y + b.h));
	const put = (i, v, axis) => { at[i] = { ...at[i], [axis]: Math.round(v) }; };

	switch (how) {
		case 'left': boxes.forEach((_, i) => put(i, left, 'x')); break;
		case 'right': boxes.forEach((b, i) => put(i, right - b.w, 'x')); break;
		case 'centre':
			boxes.forEach((b, i) => put(i, (left + right) / 2 - b.w / 2, 'x'));
			break;
		case 'top': boxes.forEach((_, i) => put(i, top, 'y')); break;
		case 'bottom': boxes.forEach((b, i) => put(i, bottom - b.h, 'y')); break;
		case 'middle':
			boxes.forEach((b, i) => put(i, (top + bottom) / 2 - b.h / 2, 'y'));
			break;
		case 'across': return spread(boxes, at, 'x', 'w', left, right);
		case 'down': return spread(boxes, at, 'y', 'h', top, bottom);
		// No default: the list is checked above.
	}
	return at;
}
