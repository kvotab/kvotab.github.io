/**
 * Where it goes: the account of one nuclide over the run on show, drawn.
 *
 * Three views of one account (../sim/flows.js), all at the time the slider
 * names:
 *
 *   - **the flow diagram** -- the compartments in columns by the order the
 *     inventory reaches them, with what came in and grew in on the left and
 *     what left the model and decayed on the right, and a band for every
 *     route as wide as the amount it has carried. A route back to a column
 *     already passed is drawn dashed;
 *   - **where it is** -- what each compartment holds over the whole run,
 *     stacked, with what has left and what has decayed on top, so that the
 *     height of the whole is what there has been to account for; and
 *   - **every route** -- a row each, the largest first, with how much it
 *     carried and its share of what there was.
 *
 * Choosing another nuclide asks the worker for its account; the slider only
 * redraws. Nothing here changes the model or the run.
 */

import { el } from './parts.js';
import { openModal } from './modal.js';
import { dialogInfo } from './dialoginfo.js';
import { accountAt, OUTSIDE } from '../sim/flows.js';

const NS = 'http://www.w3.org/2000/svg';

const svg = (tag, attrs = {}) => {
	const n = document.createElementNS(NS, tag);
	for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, String(v));
	return n;
};

const fmt = (v) => {
	if (v == null || !Number.isFinite(v)) return '—';
	if (v === 0) return '0';
	return Math.abs(v) >= 1e5 || Math.abs(v) < 1e-2 ? v.toExponential(2) : String(Number(v.toPrecision(4)));
};
const pct = (part, whole) => {
	if (!(whole > 0) || !Number.isFinite(part)) return '';
	const p = (100 * part) / whole;
	return `${p >= 10 ? p.toFixed(0) : p >= 0.1 ? p.toFixed(1) : p > 0 ? '<0.1' : '0'} %`;
};

/** The ends of the account that are not compartments, and how each is called. */
const ENDS = {
	in: 'Came in',
	ingrowth: 'Grew in',
	otherIn: 'Not accounted for',
	out: 'Left the model',
	decay: 'Decayed',
	otherOut: 'Not accounted for ',
};

/**
 * @param {object} opts
 * @param {string} opts.timeUnit
 * @param {string} opts.unit              the inventory's unit
 * @param {(family: string|null) => void} opts.onFamily  ask for a family's account
 * @param {boolean} [opts.stale]          the run is of the model before the latest edits
 */
export function openFlowsDialog({ timeUnit = '', unit = '', onFamily, stale = false }) {
	const state = { account: null, k: null, error: null, busy: true };
	let handle = null;
	const redraw = () => handle?.refresh();

	handle = openModal({
		info: dialogInfo('flows'),
		title: 'Where it goes',
		subtitle: 'What each compartment holds, and what each route carried, over the run on show',
		wide: true,
		className: 'flows-modal',
		build(body) {
			body.replaceChildren();
			if (stale) {
				body.append(el('p', { className: 'prob-warn' },
					'The run on show is of the model before the latest edits, and so is this account.'));
			}
			const a = state.account;
			if (state.error) body.append(el('p', { className: 'prob-warn' }, state.error));
			if (!a) {
				if (state.busy) body.append(el('p', { className: 'hint' }, 'Working the account out…'));
				body.append(foot());
				return;
			}
			if (!a.places.length) {
				body.append(el('p', { className: 'hint' }, 'This run has no compartments to account for.'));
				body.append(foot());
				return;
			}
			const T = a.t.length;
			if (state.k == null || state.k >= T) state.k = T - 1;
			const k = state.k;

			// --- what is shown: the nuclide and the time -------------------
			const bar = el('div', { className: 'flows-bar' });
			if (a.families.length > 1) {
				const sel = el('select', { 'aria-label': 'The nuclide accounted for' },
					...[...a.families].sort((p, q) => q.start - p.start)
						.map((f) => el('option', { value: f.name, selected: f.name === a.family }, f.name)));
				sel.addEventListener('change', () => {
					state.busy = true;
					state.error = null;
					redraw();
					onFamily?.(sel.value);
				});
				bar.append(el('label', { className: 'cs-tick' }, 'Of', sel));
			} else {
				bar.append(el('span', { className: 'flows-family' }, a.family));
			}
			const slider = el('input', {
				type: 'range', min: '0', max: String(T - 1), step: '1', value: String(k),
				'aria-label': 'Up to which output time',
			});
			const when = el('span', { className: 'flows-when mono' }, `${fmt(a.t[k])} ${timeUnit}`);
			slider.addEventListener('input', () => {
				state.k = Number(slider.value);
				when.textContent = `${fmt(a.t[state.k])} ${timeUnit}`;
				paint();
			});
			bar.append(el('label', { className: 'cs-tick flows-slider' }, 'Up to', slider), when);
			body.append(bar);

			const summaryHost = el('p', { className: 'flows-summary' });
			const pictureHost = el('div', { className: 'flows-picture' });
			const chartHost = el('div', { className: 'flows-chart' });
			const tableHost = el('div', { className: 'flows-table' });
			body.append(summaryHost, pictureHost, chartHost, tableHost);
			body.append(el('p', { className: 'hint' },
				'Each route’s amount is its rate at every output time — a transfer’s value times what its '
				+ 'donor holds, a source’s value, a compartment’s decay and its parents’ ingrowth, by the '
				+ 'same arithmetic as the run — added up between the output times by the trapezium rule. '
				+ 'Not accounted for is each compartment’s change less every route: an explicit dy/dt term, a '
				+ 'far-field path’s return, an event’s jump, and the summing between the points.'));

			// One colour per compartment in both pictures, in the order of the
			// most each ever held.
			const tone = new Map([...a.places]
				.sort((p, q) => peak(q.series) - peak(p.series))
				.map((p, i) => [p.key, (i % 8) + 1]));
			const paint = () => {
				const now = accountAt(a, state.k);
				const u = a.unit ?? unit;
				summaryHost.replaceChildren(...summary(now, u));
				pictureHost.replaceChildren(flowPicture(now, tone));
				chartHost.replaceChildren(stackChart(a, state.k, timeUnit, u, tone));
				tableHost.replaceChildren(routesTable(now, u));
			};
			paint();
			body.append(foot());
		},
	});

	function foot() {
		const f = el('div', { className: 'pdf-foot' });
		f.append(el('span', { className: 'pdf-note' }, 'Nothing in the model or the run has changed.'));
		const close = el('button', { type: 'button', className: 'ghost' }, 'Close');
		close.addEventListener('click', () => handle.close());
		f.append(close);
		return f;
	}

	return {
		handle,
		show(account) { state.account = account; state.busy = false; state.error = null; redraw(); },
		failed(message) { state.busy = false; state.error = message; redraw(); },
	};
}

/** The most a series reaches. */
function peak(series) {
	let most = -Infinity;
	for (const v of series) if (v > most) most = v;
	return most;
}

/** One sentence of the account at the time shown. */
function summary(now, unit) {
	const T = now.totals;
	const whole = T.start + T.in + T.ingrowth;
	const u = unit ? ` ${unit}` : '';
	const parts = [`Of ${fmt(T.start)}${u} at the start`];
	if (T.in > 0) parts.push(`${fmt(T.in)} that came in`);
	if (T.ingrowth > 0) parts.push(`${fmt(T.ingrowth)} that grew in`);
	const lead = parts.length > 1
		? `${parts.slice(0, -1).join(', ')} and ${parts[parts.length - 1]}`
		: parts[0];
	const rest = [`${fmt(T.now)} is held (${pct(T.now, whole)})`];
	if (T.decay > 0) rest.push(`${fmt(T.decay)} has decayed (${pct(T.decay, whole)})`);
	if (T.out > 0) rest.push(`${fmt(T.out)} has left the model (${pct(T.out, whole)})`);
	const out = [el('span', {}, `${lead}: ${rest.join(', ')}.`)];
	if (Math.abs(T.other) > 1e-3 * whole) {
		out.push(el('span', { className: 'flows-other' },
			` ${fmt(Math.abs(T.other))} (${pct(Math.abs(T.other), whole)}) no route here accounts for.`));
	}
	return out;
}

/**
 * The flow diagram: places in columns, the account's other ends at its sides,
 * a band per route as wide as what it carried.
 */
function flowPicture(now, tone) {
	const W = 880;
	const PAD = 8;
	const NODE = 12;
	const GAP = 14;
	const LABEL = 150;
	const totals = now.totals;
	const whole = totals.start + totals.in + totals.ingrowth;
	const smallest = whole * 1e-6;

	// The nodes: every place, and the ends that carried anything.
	const nodes = new Map();
	const node = (key, label, kind) => {
		if (!nodes.has(key)) nodes.set(key, { key, label, kind, ins: [], outs: [], start: 0, now: 0 });
		return nodes.get(key);
	};
	for (const p of now.held) Object.assign(node(p.key, p.label, 'place'), { start: p.start, now: p.now });
	const links = [];
	const link = (from, to, amount, kind, name) => {
		if (!(amount > smallest)) return;
		const l = { from: nodes.get(from), to: nodes.get(to), amount, kind, name };
		l.from.outs.push(l);
		l.to.ins.push(l);
		links.push(l);
	};
	for (const r of now.routes) {
		if (r.kind === 'transfer') { link(r.from, r.to, r.amount, r.kind, r.name); continue; }
		if (r.kind === 'in') { node('end:in', ENDS.in, 'source'); link('end:in', r.to, r.amount, r.kind, r.name); continue; }
		if (r.kind === 'ingrowth') { node('end:ingrowth', ENDS.ingrowth, 'source'); link('end:ingrowth', r.to, r.amount, r.kind, r.name); continue; }
		if (r.kind === 'out') { node('end:out', ENDS.out, 'sink'); link(r.from, 'end:out', r.amount, r.kind, r.name); continue; }
		if (r.kind === 'decay') { node('end:decay', ENDS.decay, 'sink'); link(r.from, 'end:decay', r.amount, r.kind, r.name); continue; }
		// What nothing accounts for is drawn only where it is worth a look; the
		// line above and the table say it whatever its size.
		if (r.kind === 'other' && Math.abs(r.amount) > 1e-3 * whole) {
			if (r.amount > 0) { node('end:otherIn', ENDS.otherIn, 'source'); link('end:otherIn', r.to, r.amount, r.kind, r.name); } else { node('end:otherOut', ENDS.otherOut, 'sink'); link(r.to, 'end:otherOut', -r.amount, r.kind, r.name); }
		}
	}
	// Places that hold or carried nothing are left out of the picture, and so
	// is an end every route to which was too small to draw.
	for (const [key, n] of nodes) {
		const idle = !n.ins.length && !n.outs.length;
		if (idle && (n.kind !== 'place' || (!(n.start > smallest) && !(n.now > smallest)))) nodes.delete(key);
	}
	const sum = (ls) => ls.reduce((s, l) => s + l.amount, 0);
	for (const n of nodes.values()) {
		n.size = n.kind === 'place'
			? Math.max(n.start + sum(n.ins), n.now + sum(n.outs))
			: n.kind === 'source' ? sum(n.outs) : sum(n.ins);
	}

	// Columns: the ends that brought anything in first, then each place by the
	// longest run of transfers that reaches it, then the ends it left by.
	// A route back to a column already passed is a cycle, broken where it is
	// met and drawn dashed.
	const places = [...nodes.values()].filter((n) => n.kind === 'place');
	const col = new Map();
	const order = [...places].sort((p, q) => (q.start - p.start) || (q.size - p.size));
	const onPath = new Set();
	const back = new Set();
	const depth = (n) => {
		if (col.has(n)) return col.get(n);
		onPath.add(n);
		let d = 1;
		for (const l of n.ins) {
			if (l.kind !== 'transfer') continue;
			if (onPath.has(l.from)) { back.add(l); continue; }
			d = Math.max(d, depth(l.from) + 1);
		}
		onPath.delete(n);
		col.set(n, d);
		return d;
	};
	for (const n of order) depth(n);
	const last = Math.max(1, ...col.values()) + 1;
	for (const n of nodes.values()) {
		if (n.kind === 'source') col.set(n, 0);
		if (n.kind === 'sink') col.set(n, last);
	}
	for (const l of links) if (col.get(l.to) <= col.get(l.from) && l.kind === 'transfer') back.add(l);
	// Columns nothing stands in take no room: a run with nothing coming in
	// starts with its first compartments at the left edge.
	{
		const used = [...new Set(col.values())].sort((p, q) => p - q);
		const at = new Map(used.map((c, i) => [c, i]));
		for (const [n, c] of col) col.set(n, at.get(c));
	}
	const lastCol = Math.max(0, ...col.values());
	// Sizes: the fullest column fills the height.
	const columns = Array.from({ length: lastCol + 1 }, () => []);
	for (const n of nodes.values()) columns[col.get(n)].push(n);
	for (const c of columns) c.sort((p, q) => q.size - p.size);
	const H = Math.max(160, Math.min(420, 40 + 26 * Math.max(...columns.map((c) => c.length))));
	const room = (c) => H - 2 * PAD - 12 - GAP * Math.max(0, c.length - 1);
	const scale = Math.min(...columns.filter((c) => c.length).map((c) => room(c) / (sum(c.map((n) => ({ amount: n.size }))) || 1)));
	const inner = W - 2 * PAD - LABEL;
	const xOf = (c) => PAD + (lastCol ? (inner * c) / lastCol : 0);
	for (const [c, list] of columns.entries()) {
		let y0 = PAD + 12;
		for (const n of list) {
			n.x = xOf(c);
			n.h = Math.max(2, n.size * scale);
			n.y = y0;
			y0 += n.h + GAP;
		}
	}

	const g = svg('svg', {
		class: 'flows-svg', viewBox: `0 0 ${W} ${H}`, width: '100%', role: 'img',
		'aria-label': 'Where the inventory went: a band per route, as wide as the amount it carried',
	});
	// Bands, stacked at each end in the order of the node at the other end.
	for (const n of nodes.values()) {
		n.outs.sort((p, q) => p.to.y - q.to.y);
		n.ins.sort((p, q) => p.from.y - q.from.y);
		let o = 0;
		for (const l of n.outs) { l.y0 = n.y + o; o += l.amount * scale; }
		let i = n.kind === 'place' ? n.start * scale : 0;
		for (const l of n.ins) { l.y1 = n.y + i; i += l.amount * scale; }
	}
	const bandLayer = svg('g', { class: 'flows-bands' });
	for (const l of links) {
		const w = Math.max(0.6, l.amount * scale);
		const x0 = l.from.x + NODE;
		const x1 = l.to.x;
		const y0 = l.y0 ?? l.from.y;
		const y1 = l.y1 ?? l.to.y;
		const isBack = back.has(l);
		const mid = isBack ? Math.max(40, Math.abs(x1 - x0) / 2 + 40) : (x1 - x0) / 2;
		const c0 = x0 + mid;
		const c1 = x1 - mid;
		const d = `M ${x0} ${y0} C ${c0} ${y0}, ${c1} ${y1}, ${x1} ${y1} `
			+ `L ${x1} ${y1 + w} C ${c1} ${y1 + w}, ${c0} ${y0 + w}, ${x0} ${y0 + w} Z`;
		bandLayer.append(svg('path', {
			class: `flows-band is-${l.kind}${isBack ? ' is-back' : ''}`, d,
		}));
	}
	g.append(bandLayer);
	const nodeLayer = svg('g', { class: 'flows-nodes' });
	for (const n of nodes.values()) {
		const cls = n.kind === 'place' ? `flows-node series-${tone.get(n.key) ?? 1}` : `flows-node is-${n.key.slice(4)}`;
		nodeLayer.append(svg('rect', { class: cls, x: n.x, y: n.y, width: NODE, height: n.h, rx: 2 }));
	}
	// Labels last, over the bands: the ends of the account to the right of
	// their node, in the room kept for them; a place above its node, in the
	// gap the column leaves, where no band runs.
	for (const n of nodes.values()) {
		const sink = n.kind === 'sink';
		const text = svg('text', {
			class: 'flows-label',
			x: sink ? n.x + NODE + 5 : n.x,
			y: sink ? n.y + Math.min(n.h, 22) / 2 + 4 : n.y - 3,
			'text-anchor': 'start',
		});
		const amount = n.kind === 'place' ? n.now : n.size;
		text.textContent = `${n.label} ${fmt(amount)}${n.kind === 'place' ? ' held' : ''}`;
		nodeLayer.append(text);
	}
	g.append(nodeLayer);
	return g;
}

/**
 * Where it is over the whole run: each compartment's inventory, stacked, and
 * what has left and decayed on top; a line at the time shown.
 */
function stackChart(a, k, timeUnit, unit, tone) {
	const W = 880;
	const H = 220;
	const L = 64;
	const R = 12;
	const TOP = 10;
	const B = 34;
	const T = a.t.length;
	const sumKind = (kind) => {
		const out = new Float64Array(T);
		for (const l of a.links) {
			if (l.kind !== kind) continue;
			for (let i = 0; i < T; i++) out[i] += l.cum[i];
		}
		return out;
	};
	const places = [...a.places].sort((p, q) => peak(q.series) - peak(p.series));
	const layers = [
		...places.map((p) => ({ label: p.label, cls: `series-${tone.get(p.key) ?? 1}`, values: p.series })),
		{ label: ENDS.out, cls: 'is-out', values: sumKind('out') },
		{ label: ENDS.decay, cls: 'is-decay', values: sumKind('decay') },
	].filter((l) => l.values.some((v) => v > 0));
	const tops = layers.map(() => new Float64Array(T));
	let most = 0;
	for (let i = 0; i < T; i++) {
		let s = 0;
		layers.forEach((l, j) => { s += Math.max(0, l.values[i] || 0); tops[j][i] = s; });
		most = Math.max(most, s);
	}
	// A time axis on a logarithm where the run spans decades, as its output
	// grid usually does.
	const positive = a.t.filter((v) => v > 0);
	const lo = positive.length ? Math.min(...positive) : 0;
	const hi = a.t[T - 1];
	const logX = lo > 0 && hi / lo > 1e3;
	const plotW = W - L - R;
	const xOf = (v) => {
		if (logX) return L + (v <= lo ? 0 : (Math.log10(v / lo) / Math.log10(hi / lo)) * plotW);
		return L + ((v - a.t[0]) / ((hi - a.t[0]) || 1)) * plotW;
	};
	const yOf = (v) => TOP + (H - TOP - B) * (1 - (most > 0 ? v / most : 0));
	const g = svg('svg', {
		class: 'flows-svg flows-stack', viewBox: `0 0 ${W} ${H}`, width: '100%', role: 'img',
		'aria-label': 'Where the inventory is over the run, stacked',
	});
	layers.forEach((l, j) => {
		const top = tops[j];
		const below = j ? tops[j - 1] : null;
		let d = '';
		for (let i = 0; i < T; i++) d += `${i ? 'L' : 'M'} ${xOf(a.t[i]).toFixed(1)} ${yOf(top[i]).toFixed(1)} `;
		for (let i = T - 1; i >= 0; i--) d += `L ${xOf(a.t[i]).toFixed(1)} ${yOf(below ? below[i] : 0).toFixed(1)} `;
		g.append(svg('path', { class: `flows-area ${l.cls}`, d: `${d}Z` }));
	});
	// Axes: the time, and the amount.
	g.append(svg('line', { class: 'flows-axis', x1: L, y1: H - B, x2: W - R, y2: H - B }));
	g.append(svg('line', { class: 'flows-axis', x1: L, y1: TOP, x2: L, y2: H - B }));
	// On a logarithm, the decades inside the run; otherwise its ends and middle.
	const ticks = logX
		? Array.from({ length: Math.floor(Math.log10(hi)) - Math.ceil(Math.log10(lo)) + 1 },
			(_, i) => 10 ** (Math.ceil(Math.log10(lo)) + i))
		: [a.t[0], (a.t[0] + hi) / 2, hi];
	for (const v of ticks) {
		const x = xOf(v);
		g.append(svg('line', { class: 'flows-tick', x1: x, y1: H - B, x2: x, y2: H - B + 4 }));
		// A label at the right-hand end ends there rather than running off it.
		const end = x > W - R - 24;
		const text = svg('text', { class: 'flows-tick-label', x, y: H - B + 15, 'text-anchor': end ? 'end' : 'middle' });
		text.textContent = fmt(v);
		g.append(text);
	}
	const xTitle = svg('text', { class: 'flows-tick-label', x: L + plotW / 2, y: H - 4, 'text-anchor': 'middle' });
	xTitle.textContent = `Time (${timeUnit})`;
	g.append(xTitle);
	for (const v of [0, most]) {
		const text = svg('text', { class: 'flows-tick-label', x: L - 6, y: yOf(v) + 4, 'text-anchor': 'end' });
		text.textContent = fmt(v);
		g.append(text);
	}
	const yTitle = svg('text', {
		class: 'flows-tick-label', x: 12, y: TOP + (H - TOP - B) / 2, 'text-anchor': 'middle',
		transform: `rotate(-90 12 ${TOP + (H - TOP - B) / 2})`,
	});
	yTitle.textContent = unit || 'amount';
	g.append(yTitle);
	// The time shown.
	const xk = xOf(a.t[k]);
	g.append(svg('line', { class: 'flows-now', x1: xk, y1: TOP, x2: xk, y2: H - B }));
	const wrap = el('div', {});
	wrap.append(g);
	const legend = el('div', { className: 'flows-legend' }, ...layers.map((l) => el('span', { className: 'flows-key' },
		el('span', { className: `flows-swatch ${l.cls}` }), l.label)));
	wrap.append(legend);
	return wrap;
}

/** Every route, a row each, the largest first. */
function routesTable(now, unit) {
	const whole = now.totals.start + now.totals.in + now.totals.ingrowth;
	const rows = now.routes.filter((r) => Math.abs(r.amount) > 0)
		.sort((p, q) => Math.abs(q.amount) - Math.abs(p.amount));
	const table = el('table', { className: 'opt-table flows-routes' });
	table.append(el('thead', {}, el('tr', {},
		el('th', {}, 'Route'), el('th', {}, 'From'), el('th', {}, 'To'),
		el('th', {}, `Carried${unit ? ` (${unit})` : ''}`), el('th', {}, 'Of all'))));
	const tb = el('tbody');
	const name = (r) => (r.kind === 'decay' ? 'decay' : r.kind === 'ingrowth' ? 'ingrowth from its parents'
		: r.kind === 'other' ? 'not accounted for' : r.name);
	// Where a route's far end is not a compartment, what it is.
	const far = (r, side) => {
		if (r.kind === 'decay' && side === 'to') return 'decayed';
		if (r.kind === 'ingrowth' && side === 'from') return 'its parents';
		if (r.kind === 'other') return 'nowhere here';
		return 'outside';
	};
	const end = (r, key, side) => (key === OUTSIDE ? far(r, side) : key);
	for (const r of rows.slice(0, 200)) {
		const from = r.kind === 'other' && r.amount < 0 ? r.to : r.from;
		const to = r.kind === 'other' && r.amount < 0 ? OUTSIDE : r.to;
		tb.append(el('tr', { className: `is-${r.kind}` },
			el('td', { title: name(r) }, name(r)),
			el('td', { title: end(r, from, 'from') }, end(r, from, 'from')),
			el('td', { title: end(r, to, 'to') }, end(r, to, 'to')),
			el('td', { className: 'mono' }, fmt(Math.abs(r.amount))),
			el('td', { className: 'mono' }, pct(Math.abs(r.amount), whole))));
	}
	table.append(tb);
	const wrap = el('div', {});
	wrap.append(table);
	if (rows.length > 200) {
		wrap.append(el('p', { className: 'hint' }, `The 200 largest of ${rows.length.toLocaleString()} routes.`));
	}
	return wrap;
}
