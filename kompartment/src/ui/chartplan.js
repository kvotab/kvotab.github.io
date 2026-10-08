/**
 * What the Chart tab draws, worked out from what is picked.
 *
 * What is picked is a set of series, and a series is one index of one block:
 * `Outflow [I-129]`. But nobody thinks of a chart as a set of series. They
 * think "the release, by nuclide" -- a block, drawn over one of its index
 * lists -- and "the water in the lake and in the mire": the same block, cut at
 * another of them. So the picked series are grouped back into their blocks and
 * each block is drawn as one thing:
 *
 *   - one line per index of the list the lines run over -- the nuclides,
 *     where the block has them -- each wearing that index's own colour (see
 *     ./linestyles.js), so a nuclide is the same line on every chart;
 *   - for each other list the block is indexed by, one choice: a panel per
 *     index, the sum over them, or just one of them;
 *   - and, where it is asked for, the block's total: every line of it added.
 *
 * Blocks go in a panel each, or -- *Same chart* -- in one chart, where a block
 * after the first wears thinner lines wherever it repeats a line the first one
 * drew. One chart is one chart: series of different units share its axis,
 * which names every one of them, and the page says they cannot be compared.
 * Only a block's own choice of a panel per index still cuts it.
 *
 * Nothing here reads a number. The plan says which series make up each line
 * and how it looks; the page fetches and adds the columns. That keeps this a
 * rule that can be tested without a run, and a plan cheap enough to work out
 * on every redraw.
 */

import { namedStyle } from './linestyles.js';

/** Up to this many indices of a list are a panel each by default; past it, one of them. */
export const PANEL_EACH_UP_TO = 6;

/** How many panels a chart is split into before the rest are left out and said so. */
export const MOST_PANELS = 12;

/** How many lines one panel draws before the rest are left out and said so. */
export const MOST_PER_PANEL = 300;

const PALETTE = 8;
const SETS = 4;

/**
 * Where each index stands in its list, as the run reports them: list ->
 * index -> place. A line with no named colour takes the palette's colour at
 * that place, so it is the same colour on every chart of the run, whatever
 * else is drawn with it.
 *
 * @param {Array<{dims?: string[], index?: string[]}>} outputs
 * @returns {Map<string, Map<string, number>>}
 */
export function indexOrder(outputs) {
	const order = new Map();
	for (const o of outputs ?? []) {
		(o.dims ?? []).forEach((d, k) => {
			let m = order.get(d);
			if (!m) order.set(d, (m = new Map()));
			const v = o.index?.[k];
			if (v != null && !m.has(v)) m.set(v, m.size);
		});
	}
	return order;
}

/** The colour and pattern of a line that stands for index `value` of `list`. */
export function identityStyle(list, value, order) {
	const named = namedStyle(value);
	if (named) {
		return { kind: 'named', color: named.color, dash: named.dash, ...(named.width ? { width: named.width } : {}) };
	}
	const at = order?.get(list)?.get(value) ?? 0;
	return { kind: 'palette', color: at % PALETTE, set: Math.floor(at / PALETTE) % SETS };
}

/**
 * A block as picked: its lists, which of them the lines run over, and for
 * each of the others the indices picked and what is done with them.
 *
 * `choice` is what the reader said for this block, `{ lines, others: { list:
 * 'panel' | 'sum' | index } }`; anything it does not say, or says about a list
 * or an index the block does not have, is decided here:
 *
 *   - the lines run over the block's material -- the nuclides -- where it has
 *     one and more than one of them is picked, and otherwise over the list
 *     with the most indices picked;
 *   - another list with one index picked has nothing to decide;
 *   - one with a few picked is a panel each, and one with many is the first
 *     of them, which is the choice that draws something readable at once.
 */
export function describeBlock(outputs, block, items, choice = {}) {
	const first = outputs[items[0]];
	const dims = first?.dims ?? [];
	if (!dims.length) return { block, dims, lines: null, others: [], scalar: true, items };
	const values = dims.map(() => []);
	const seen = dims.map(() => new Set());
	for (const i of items) {
		const idx = outputs[i]?.index ?? [];
		dims.forEach((_, k) => {
			const v = idx[k];
			if (!seen[k].has(v)) { seen[k].add(v); values[k].push(v); }
		});
	}
	let lines = dims.includes(choice?.lines) ? choice.lines : null;
	if (!lines) {
		const mat = first.nuclide != null ? (first.index ?? []).indexOf(first.nuclide) : -1;
		if (mat >= 0 && values[mat].length > 1) lines = dims[mat];
		else {
			let best = 0;
			for (let k = 1; k < dims.length; k++) if (values[k].length > values[best].length) best = k;
			lines = dims[best];
		}
	}
	const others = [];
	dims.forEach((list, k) => {
		if (list === lines) return;
		const picked = values[k];
		const said = choice?.others?.[list];
		let how;
		if (picked.length <= 1) how = picked[0];
		else if (said === 'panel' || said === 'sum' || picked.includes(said)) how = said;
		else how = picked.length <= PANEL_EACH_UP_TO ? 'panel' : picked[0];
		others.push({ list, at: k, values: picked, how });
	});
	return { block, dims, lines, linesAt: dims.indexOf(lines), others, scalar: false, items };
}

/**
 * The panels and their lines.
 *
 * @param {Array<object>} outputs  the run's series descriptors
 * @param {number[]} selected      what is picked, in the order it was picked
 * @param {object} [opts]
 * @param {'panels'|'same'} [opts.layout]
 * @param {Map<string, object>} [opts.split]  each block's `choice`, by block
 * @param {Map<string, Map<string, number>>} [opts.order]  see `indexOrder`
 * @param {boolean} [opts.total]  a total line for each block with two or more
 * @returns {{panels: Array<object>, blocks: Array<object>, notes: string[]}}
 */
export function planChart(outputs, selected, {
	layout = 'panels', split = new Map(), order = null, total = true,
} = {}) {
	const ord = order ?? indexOrder(outputs);
	const same = layout === 'same';
	const groups = new Map();
	for (const i of selected ?? []) {
		const o = outputs[i];
		if (!o) continue;
		const block = o.block ?? o.label;
		let g = groups.get(block);
		if (!g) groups.set(block, (g = []));
		g.push(i);
	}
	const panels = new Map();
	const blocks = [];
	const notes = [];
	let loose = 0;
	const panelFor = (key, title, unit) => {
		let p = panels.get(key);
		if (!p) panels.set(key, (p = { key, title, unit, units: [], lines: [], blocks: [] }));
		if (!p.units.includes(unit)) {
			p.units.push(unit);
			// The axis of a panel holding several units names them all.
			p.unit = p.units.filter(Boolean).join(', ');
		}
		return p;
	};
	for (const [block, items] of groups) {
		const info = describeBlock(outputs, block, items, split.get(block));
		blocks.push(info);
		// A series picked on its own -- a block with no index, or one index of
		// a block -- is a line like the series picked beside it, and goes in
		// one chart with them, as lines picked one by one always have: what
		// they share is that somebody wants to compare them. Their colours are
		// their places on that chart.
		if (info.scalar || items.length === 1) {
			info.loose = true;
			for (const i of items) {
				const o = outputs[i];
				const unit = o.unit ?? '';
				// The same key a shared panel with no cut has, so under *Same
				// chart* they join the blocks drawn there.
				const p = panelFor(same ? 'same|' : `loose||${unit}`, '', unit);
				const at = loose++;
				p.lines.push({
					key: o.label, label: o.label, outputs: [i], block, value: null, loose: true, unit,
					style: { kind: 'palette', color: at % PALETTE, set: Math.floor(at / PALETTE) % SETS },
				});
				if (!p.blocks.includes(block)) p.blocks.push(block);
			}
			continue;
		}
		const panelLists = info.others.filter((x) => x.how === 'panel');
		const sums = info.others.filter((x) => x.how === 'sum');
		const fixed = info.others.filter((x) => x.how !== 'panel' && x.how !== 'sum');
		// What this block's panels are called: the block, then each index it is
		// cut at -- `Water · Lake` -- and each list it is added over.
		const said = [
			...fixed.map((x) => String(x.how)),
			...sums.map((x) => `sum over ${x.list}`),
		];
		const byLine = new Map();
		for (const i of items) {
			const o = outputs[i];
			const idx = o.index ?? [];
			if (fixed.some((x) => idx[x.at] !== x.how)) continue;
			const cut = panelLists.map((x) => idx[x.at]);
			const unit = o.unit ?? '';
			const value = idx[info.linesAt];
			const key = `${cut.join('\u0000')}\u0001${unit}\u0001${value}`;
			let line = byLine.get(key);
			if (!line) {
				byLine.set(key, (line = { cut, unit, value, outputs: [] }));
			}
			line.outputs.push(i);
		}
		for (const line of byLine.values()) {
			const where = line.cut.map((v, k) => `${panelLists[k].list}=${v}`).join('\u0000');
			const title = [block, ...line.cut, ...said].join(' · ');
			const p = same
				? panelFor(`same|${where}`, line.cut.join(' · '), line.unit)
				: panelFor(`${block}|${where}|${line.unit}`, title, line.unit);
			if (!p.blocks.includes(block)) p.blocks.push(block);
			const style = identityStyle(info.lines, line.value, ord);
			// The second block in a shared panel draws its lines thinner where
			// they would be the same colour and pattern as the first's.
			const repeats = same && p.lines.some((l) => l.block !== block && l.value === line.value);
			p.lines.push({
				key: `${block}\u0001${line.value}`,
				label: same ? `${block} [${line.value}]` : String(line.value),
				outputs: line.outputs,
				block,
				value: line.value,
				unit: line.unit,
				sum: line.outputs.length > 1,
				style: repeats ? { ...style, thin: 1 } : style,
			});
		}
	}
	// The totals, a block at a time, ahead of its lines. Only where there is
	// something to add up: a block of one line is its own total.
	if (total) {
		for (const p of panels.values()) {
			const out = [];
			for (const block of p.blocks) {
				const mine = p.lines.filter((l) => l.block === block && l.value != null);
				// Nothing to add up in one line, and nothing that can be added
				// across units -- a material in kg beside the nuclides in Bq.
				if (mine.length < 2 || new Set(mine.map((l) => l.unit)).size > 1) continue;
				const first = p.blocks.find((b) => p.lines.some((l) => l.block === b && l.value != null));
				out.push({
					key: `${block}\u0001total`,
					label: same ? `${block} total` : 'Total',
					outputs: mine.flatMap((l) => l.outputs),
					block,
					value: null,
					unit: mine[0].unit,
					total: true,
					sum: true,
					style: same && block !== first ? { kind: 'total', thin: 1.25 } : { kind: 'total' },
				});
			}
			p.lines.unshift(...out);
		}
	}
	let list = [...panels.values()];
	if (list.length > MOST_PANELS) {
		notes.push(`${(list.length - MOST_PANELS).toLocaleString()} more panels are not drawn: `
			+ `a chart is cut into at most ${MOST_PANELS}. Pick fewer, or add one of the lists up.`);
		list = list.slice(0, MOST_PANELS);
	}
	for (const p of list) {
		if (p.lines.length > MOST_PER_PANEL) {
			notes.push(`${p.title || 'A panel'}: ${(p.lines.length - MOST_PER_PANEL).toLocaleString()} `
				+ `lines left out of ${p.lines.length.toLocaleString()}; a panel draws at most ${MOST_PER_PANEL}.`);
			p.lines = p.lines.slice(0, MOST_PER_PANEL);
		}
	}
	return { panels: list, blocks, notes };
}

/**
 * The largest value a line reaches, for ranking: the peak of what it draws,
 * finite values only, and on a log axis only the positive ones (a line that
 * is never above zero draws nothing there and ranks last).
 */
export function peakOf(values, positive = false) {
	let best = -Infinity;
	for (let i = 0; i < (values?.length ?? 0); i++) {
		const v = values[i];
		if (!Number.isFinite(v) || (positive && !(v > 0))) continue;
		if (v > best) best = v;
	}
	return best;
}

/**
 * The lines to draw when only the largest `n` are wanted: every total, and
 * the `n` others with the highest peaks. `n` of zero, or more than there are,
 * is all of them. Returns the lines kept, in their own order, and how many
 * were left out.
 *
 * @param {Array<{total?: boolean}>} lines
 * @param {(line: object) => number} peak
 * @param {number} n
 */
export function largestLines(lines, peak, n) {
	const plain = lines.filter((l) => !l.total);
	if (!(n > 0) || plain.length <= n) return { kept: lines, left: 0 };
	const keep = new Set(plain.map((l) => ({ l, p: peak(l) }))
		.sort((a, b) => b.p - a.p)
		.slice(0, n)
		.map((x) => x.l));
	return { kept: lines.filter((l) => l.total || keep.has(l)), left: plain.length - n };
}
