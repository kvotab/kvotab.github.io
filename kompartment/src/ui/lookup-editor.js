/**
 * Reading, writing and drawing a lookup table's points.
 *
 * A table is a list of (x, y) pairs, and the real ones are long: the models on
 * this machine average 82 points per table and one has 1961. Nobody types
 * those, they paste them, so the editor is a text box with one pair per line --
 * which is what a spreadsheet column pair and a CSV both already are.
 *
 * Shared by the inspector, which edits a table, and the diagram, which draws a
 * thumbnail of one.
 */

import { el } from './parts.js';

/** `x, y` per line, which is what the text box holds. */
export function pointsToText(points) {
	return (points ?? [])
		.map((p) => `${fmt(Number(p?.[0]))}, ${fmt(Number(p?.[1]))}`)
		.join('\n');
}

/**
 * Enough digits to round-trip a double, without `1` coming back as `1.0000000`.
 */
function fmt(v) {
	if (!Number.isFinite(v)) return '0';
	return String(v);
}

/**
 * Parses the text box back into points.
 *
 * Separators are comma, tab, semicolon or whitespace, so a column pair copied
 * out of Excel, a CSV line and a hand-typed `0 1` all work. A blank line is
 * skipped rather than read as a point at the origin.
 *
 * @returns {{points: Array<[number, number]>, error: string|null}}
 */
export function parsePointsText(text) {
	const points = [];
	const lines = String(text ?? '').split(/\r?\n/);
	for (let i = 0; i < lines.length; i++) {
		const line = lines[i].trim();
		if (!line || line.startsWith('#')) continue;
		const parts = line.split(/[,;\t]|\s+/).map((p) => p.trim()).filter((p) => p !== '');
		if (parts.length !== 2) {
			return {
				points,
				error: `Line ${i + 1} has ${parts.length} value(s); each line needs `
					+ `an x and a y, as "0, 1".`,
			};
		}
		const x = Number(parts[0]);
		const y = Number(parts[1]);
		if (!Number.isFinite(x) || !Number.isFinite(y)) {
			return { points, error: `Line ${i + 1} ("${line}") is not a pair of numbers.` };
		}
		points.push([x, y]);
	}
	// Two points at the same x are how a table expresses a step, so they are
	// allowed; the same x three times is not something to guess at.
	const seen = new Map();
	for (const [x] of points) seen.set(x, (seen.get(x) ?? 0) + 1);
	for (const [x, n] of seen) {
		if (n > 2) return { points, error: `x = ${x} appears ${n} times.` };
	}
	return { points, error: null };
}

/**
 * The points to draw for a block: its own table, or the first indexed one when
 * the block keeps its data per index. A thumbnail, so the first is
 * representative enough -- the inspector shows them all.
 */
export function tablePoints(block) {
	const own = block?.points ?? [];
	if (own.length) return own;
	for (const e of block?.entries ?? []) if (e.points?.length) return e.points;
	return [];
}

/**
 * A sparkline path for a table, fitted to the box (x, y, w, h).
 *
 * **It draws the rule the table is actually read with.** This used to draw
 * straight segments whatever the interpolation was, on the argument that at
 * thumbnail size a staircase and a line differ by less than a pixel. That is
 * true of a table of two hundred points and quite false of one with five: a
 * five-point table read with *use input below* is a staircase, and drawing it
 * as a sloping line shows a quantity ramping where the model holds it flat --
 * which is the one thing a reader looks at a lookup table's picture to find
 * out. Every picture of a table now has the same shape as the table.
 *
 * `linear` and `extrapolate` are straight segments between the points.
 * `below` holds each value until the next point (a step *after* each x),
 * `above` takes the next value immediately (a step *before* it), and `nearest`
 * changes over half way between. Those three are exactly what `makeTable` does
 * in ../domain/lookup.js -- the same three cases, in the same order -- and if
 * one changes there this has to change with it.
 *
 * A flat table draws down the middle rather than dividing by a zero range.
 *
 * @param {Array} points
 * @param {number} x @param {number} y @param {number} w @param {number} h
 * @param {string} [interpolation] one of INTERPOLATIONS; linear by default
 */
export function sparkPath(points, x, y, w, h, interpolation = 'linear') {
	if (!points || points.length === 0 || w <= 2 || h <= 2) return null;
	const pts = [...points]
		.map((p) => [Number(p[0]), Number(p[1])])
		.filter((p) => Number.isFinite(p[0]) && Number.isFinite(p[1]))
		.sort((a, b) => a[0] - b[0]);
	if (!pts.length) return null;
	if (pts.length === 1) return `M ${x} ${y + h / 2} L ${x + w} ${y + h / 2}`;

	const xs = pts.map((p) => p[0]);
	const ys = pts.map((p) => p[1]);
	const x0 = Math.min(...xs);
	const x1 = Math.max(...xs);
	const y0 = Math.min(...ys);
	const y1 = Math.max(...ys);
	const sx = x1 > x0 ? w / (x1 - x0) : 0;
	const sy = y1 > y0 ? h / (y1 - y0) : 0;
	const at = (p) => [
		x + (sx ? (p[0] - x0) * sx : w / 2),
		y + h - (sy ? (p[1] - y0) * sy : h / 2),
	];

	// More points than pixels is path data nobody can see, so thin by column --
	// but always keep the last, or the line stops short of the right edge.
	// Thinning a staircase drops whole steps rather than shaving a line, which
	// is fine for the same reason: past one point per pixel there is nothing
	// left to see either way.
	const step = Math.max(1, Math.ceil(pts.length / Math.max(2, Math.round(w))));
	const shown = [];
	for (let i = 0; i < pts.length; i += step) shown.push(pts[i]);
	if ((pts.length - 1) % step !== 0) shown.push(pts[pts.length - 1]);

	const out = [];
	let last = null;
	const move = (px, py) => {
		// A staircase repeats points where a step has no width -- the first
		// one under *above*, any pair sharing an x -- and a path full of
		// zero-length segments is longer to send and no different to look at.
		const key = `${px.toFixed(1)} ${py.toFixed(1)}`;
		if (key === last) return;
		out.push(`${out.length ? 'L' : 'M'} ${key}`);
		last = key;
	};
	const stepped = interpolation === 'below' || interpolation === 'above'
		|| interpolation === 'nearest';

	if (!stepped) {
		for (const p of shown) move(...at(p));
		return out.join(' ');
	}

	// Where the value changes, between one point and the next.
	const changeAt = (a, b) => {
		if (interpolation === 'below') return at(b)[0];     // holds until the next x
		if (interpolation === 'above') return at(a)[0];     // takes the next value at once
		return (at(a)[0] + at(b)[0]) / 2;                   // nearest: half way
	};
	for (let i = 0; i < shown.length; i++) {
		const [px, py] = at(shown[i]);
		if (i === 0) { move(px, py); continue; }
		const cut = changeAt(shown[i - 1], shown[i]);
		const prevY = at(shown[i - 1])[1];
		// Along at the old value to where it changes, then up or down to the
		// new one, then along to the point itself.
		move(cut, prevY);
		move(cut, py);
		move(px, py);
	}
	return out.join(' ');
}

// --- the editor ------------------------------------------------------------

const svgEl = (tag, attrs = {}) => {
	const n = document.createElementNS('http://www.w3.org/2000/svg', tag);
	for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, String(v));
	return n;
};

const PREVIEW_W = 260;
const PREVIEW_H = 72;

/**
 * A larger version of the diagram's sparkline, with the range labelled.
 *
 * `interpolation` because the picture has to be of the table as it is read:
 * see `sparkPath`.
 */
export function pointsPreview(points, interpolation = 'linear') {
	const box = svgEl('svg', {
		class: 'lk-preview',
		viewBox: `0 0 ${PREVIEW_W} ${PREVIEW_H}`,
		preserveAspectRatio: 'none',
		role: 'img',
	});
	const pad = { l: 4, r: 4, t: 6, b: 14 };
	const w = PREVIEW_W - pad.l - pad.r;
	const h = PREVIEW_H - pad.t - pad.b;
	box.append(svgEl('rect', {
		class: 'lk-preview-bg', x: 0, y: 0, width: PREVIEW_W, height: PREVIEW_H,
	}));
	const d = sparkPath(points, pad.l, pad.t, w, h, interpolation);
	if (!d) {
		const t = svgEl('text', { class: 'lk-preview-note', x: PREVIEW_W / 2, y: PREVIEW_H / 2 });
		t.textContent = 'no points';
		box.append(t);
		return box;
	}
	box.append(svgEl('path', { class: 'lk-preview-line', d }));

	const xs = points.map((p) => Number(p[0])).filter(Number.isFinite);
	const ys = points.map((p) => Number(p[1])).filter(Number.isFinite);
	const num = (v) => String(Number(v.toPrecision(4)));
	const label = (x, anchor, text) => {
		const t = svgEl('text', { class: 'lk-preview-tick', x, y: PREVIEW_H - 4, 'text-anchor': anchor });
		t.textContent = text;
		return t;
	};
	box.append(label(pad.l, 'start', num(Math.min(...xs))));
	box.append(label(PREVIEW_W - pad.r, 'end', num(Math.max(...xs))));
	const range = svgEl('text', { class: 'lk-preview-tick', x: PREVIEW_W / 2, y: PREVIEW_H - 4, 'text-anchor': 'middle' });
	range.textContent = `y ${num(Math.min(...ys))} – ${num(Math.max(...ys))}`;
	box.append(range);
	return box;
}

/**
 * The points editor: a preview, a text box, and what it currently says.
 *
 * Committed on blur rather than per keystroke, like every other field here --
 * a half-typed line is not a table, and re-rendering the panel under the
 * cursor would take the text away mid-edit.
 *
 * @param {{points: Array, onCommit: (points: Array) => void,
 *          onStatus?: (message: string, level?: string) => void,
 *          rows?: number, placeholder?: string}} opts
 */
export function pointsBox({
	points, onCommit, onStatus = null, rows = 7, placeholder = '',
	interpolation = 'linear',
}) {
	const box = el('div', { className: 'lk-points' });
	const preview = el('div', { className: 'lk-preview-wrap' }, pointsPreview(points ?? [], interpolation));
	const area = el('textarea', {
		className: 'lk-text mono',
		rows,
		spellcheck: false,
		value: pointsToText(points),
		placeholder: placeholder || 'x, y\n0, 1\n100, 4',
	});
	const status = el('p', { className: 'lk-status' });

	const describe = (pts, error) => {
		status.classList.toggle('is-error', !!error);
		status.textContent = error
			|| (pts.length
				? `${pts.length} point${pts.length === 1 ? '' : 's'}`
				: 'No points: this table reads as zero everywhere.');
	};
	describe(points ?? [], null);

	area.addEventListener('change', () => {
		const { points: next, error } = parsePointsText(area.value);
		describe(next, error);
		if (error) {
			onStatus?.(error, 'warn');
			return;
		}
		preview.replaceChildren(pointsPreview(next, interpolation));
		onCommit(next);
	});
	// Live feedback on the preview while typing, without committing: seeing
	// the curve is the whole reason to paste a column of numbers here.
	area.addEventListener('input', () => {
		const { points: next, error } = parsePointsText(area.value);
		describe(next, error);
		if (!error) preview.replaceChildren(pointsPreview(next, interpolation));
	});

	box.append(preview, area, status);
	return box;
}
