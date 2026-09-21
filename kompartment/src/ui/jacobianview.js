/**
 * The Jacobian, drawn.
 *
 * `df/dy` is the one thing a stiff run depends on that nobody ever looks at.
 * It is generated from the equations, it decides how many steps the solve
 * takes, and when it is wrong the symptom is a slow run or a subtly different
 * answer rather than an error. So it is worth being able to *see* it, and
 * worth being able to ask whether it is right.
 *
 * **The picture is the sparsity pattern**, one cell per (row, column), row i
 * being the equation for state i and column j the state it is differentiated
 * with respect to. A compartment model's matrix is nearly all zeros and the
 * shape of what is left says a great deal at a glance: a decay chain is a band
 * just off the diagonal, a landscape model is a block per object, and a
 * transport is a tridiagonal stripe. A dense row means something everything
 * feeds; a dense column means something that feeds everything.
 *
 * **Why a canvas and not SVG.** A 1,266-state model is 1.6 million cells. As
 * elements that is a page that never finishes laying out; as pixels it is one
 * pass and a hover handler that does arithmetic instead of hit-testing.
 *
 * **Above one cell per pixel the picture is a summary, and says so.** At
 * 22,000 states a cell is a fortieth of a pixel, so each pixel stands for a
 * block of the matrix and is drawn if *anything* in that block is non-zero.
 * That over-states the density, which is the safe direction for a picture
 * whose job is to show where the structure is.
 */

import { el } from './parts.js';

/** Colours read off the stylesheet, so the picture follows the theme. */
function palette(host) {
	const css = getComputedStyle(host);
	const pick = (name, fallback) => (css.getPropertyValue(name) || '').trim() || fallback;
	return {
		ink: pick('--text-primary', '#111'),
		accent: pick('--accent', '#3b7dd8'),
		muted: pick('--text-muted', '#888'),
		grid: pick('--border', '#ddd'),
		surface: pick('--surface-0', '#fff'),
	};
}

/**
 * Draws the pattern and returns what the hover needs to read it back.
 *
 * @param {HTMLCanvasElement} canvas
 * @param {{n: number, colPtr: ArrayLike<number>, rowIdx: ArrayLike<number>}} pattern
 * @param {object} colours
 * @param {number} box  the widest the picture may be, in CSS pixels
 */
function paint(canvas, pattern, colours, box) {
	const n = pattern.n;
	const dpr = Math.min(2, globalThis.devicePixelRatio || 1);
	// A cell is at most this many device pixels. Without a ceiling a 5x5 decay
	// chain fills five hundred pixels a side and reads as a mural rather than
	// as a matrix; the information in it is the shape, and the shape is legible
	// long before that.
	const MAX_CELL = 26 * dpr;
	const cell = Math.min(MAX_CELL, Math.max(1, Math.floor((box * dpr) / n)));
	const side = cell * n <= box * dpr ? cell * n : Math.floor(box * dpr);
	canvas.width = side;
	canvas.height = side;
	canvas.style.width = `${Math.round(side / dpr)}px`;
	canvas.style.height = `${Math.round(side / dpr)}px`;

	const ctx = canvas.getContext('2d');
	ctx.fillStyle = colours.surface;
	ctx.fillRect(0, 0, side, side);

	const scale = side / n;              // device pixels per matrix cell
	const w = Math.max(1, Math.floor(scale));
	const { colPtr, rowIdx } = pattern;

	// A rule between cells once they are big enough to count, so a reader can
	// follow a row across to the diagonal. Below that it would be most of the
	// picture.
	if (scale >= 7) {
		ctx.strokeStyle = colours.grid;
		ctx.lineWidth = 1;
		ctx.beginPath();
		for (let k = 1; k < n; k++) {
			const at = Math.floor(k * scale) + 0.5;
			ctx.moveTo(at, 0); ctx.lineTo(at, side);
			ctx.moveTo(0, at); ctx.lineTo(side, at);
		}
		ctx.stroke();
	}
	// Off-diagonal first, then the diagonal over it: the diagonal is what
	// orients the eye, and at one pixel per cell it would otherwise be hidden
	// under whatever was drawn last.
	ctx.fillStyle = colours.ink;
	for (let j = 0; j < n; j++) {
		const x = Math.floor(j * scale);
		for (let k = colPtr[j]; k < colPtr[j + 1]; k++) {
			const i = rowIdx[k];
			if (i === j) continue;
			ctx.fillRect(x, Math.floor(i * scale), w, w);
		}
	}
	ctx.fillStyle = colours.accent;
	for (let j = 0; j < n; j++) {
		for (let k = colPtr[j]; k < colPtr[j + 1]; k++) {
			if (rowIdx[k] !== j) continue;
			ctx.fillRect(Math.floor(j * scale), Math.floor(j * scale), w, w);
		}
	}
	return { side, scale, dpr, summarised: scale < 1 };
}

/** Whether (i, j) is in the pattern. Binary search: the rows of a column are sorted. */
function has(pattern, i, j) {
	const { colPtr, rowIdx } = pattern;
	let lo = colPtr[j];
	let hi = colPtr[j + 1] - 1;
	while (lo <= hi) {
		const mid = (lo + hi) >> 1;
		if (rowIdx[mid] === i) return true;
		if (rowIdx[mid] < i) lo = mid + 1; else hi = mid - 1;
	}
	return false;
}

/** How many entries a column has, and a row -- for the "what feeds what" line. */
function degrees(pattern) {
	const n = pattern.n;
	const rows = new Int32Array(n);
	const cols = new Int32Array(n);
	for (let j = 0; j < n; j++) {
		cols[j] = pattern.colPtr[j + 1] - pattern.colPtr[j];
		for (let k = pattern.colPtr[j]; k < pattern.colPtr[j + 1]; k++) rows[pattern.rowIdx[k]]++;
	}
	return { rows, cols };
}

const pct = (x) => (x >= 0.1 ? `${(100 * x).toFixed(1)}%` : `${(100 * x).toFixed(2)}%`);
const num = (v) => v.toLocaleString();

/**
 * Renders the whole view into `host`.
 *
 * @param {HTMLElement} host
 * @param {object} opts
 * @param {object|null} opts.pattern  from `jacobianPattern` — the drawing
 * @param {object|null} opts.check    from `checkJacobian`, or null if not asked
 * @param {object|null} opts.stats    the last run's statistics
 * @param {string|null} opts.busy     'pattern' | 'check' | null
 * @param {number} opts.progress      0..1 while checking
 * @param {() => void} opts.onCheck
 * @param {() => void} opts.onDraw
 */
export function renderJacobianView(host, opts = {}) {
	const { pattern: drawn, check, stats, busy, progress = 0, onCheck, onDraw } = opts;
	host.replaceChildren();

	if (!drawn) {
		host.append(el('p', { className: 'hint' },
			busy === 'pattern'
				? 'Building the model…'
				: 'The matrix df/dy the stiff solvers are handed, drawn as its sparsity pattern.'));
		if (busy !== 'pattern') {
			const b = el('button', { className: 'primary', type: 'button' }, 'Draw it');
			b.addEventListener('click', () => onDraw?.());
			host.append(el('p', {}, b));
		}
		return;
	}

	if (!drawn.available) {
		host.append(el('p', { className: 'hint' },
			'This model has no analytic Jacobian, so there is nothing to draw: ',
			el('b', {}, drawn.reason ?? 'the generator declined it'),
			'. The solvers difference the matrix instead, which is slower and gives '
			+ 'the same answer.'));
		const b = el('button', { type: 'button' }, 'Try again');
		b.addEventListener('click', () => onDraw?.());
		host.append(el('p', {}, b));
		return;
	}

	const pattern = {
		n: drawn.n,
		colPtr: Int32Array.from(drawn.pattern.colPtr),
		rowIdx: Int32Array.from(drawn.pattern.rowIdx),
	};
	const colours = palette(host);

	// --- the picture ---------------------------------------------------------
	const canvas = el('canvas', { className: 'jac-canvas' });
	// Three lines, each one ellipsized, and the block's height never changes.
	// It used to be one sentence that wrapped, and every wrap moved everything
	// below it -- while the pointer was moving, which is the worst possible
	// moment for the page to jump.
	const hoverRow = el('div', { className: 'jac-hover-line' }, ' ');
	const hoverCol = el('div', { className: 'jac-hover-line' }, ' ');
	const hoverWhat = el('div', { className: 'jac-hover-line is-what' }, ' ');
	const hover = el('div', { className: 'jac-hover' }, hoverRow, hoverCol, hoverWhat);
	const figure = el('div', { className: 'jac-figure' }, canvas, hover);

	// --- what it is ----------------------------------------------------------
	const { rows, cols } = degrees(pattern);
	let widestRow = 0;
	let widestCol = 0;
	for (let i = 0; i < pattern.n; i++) {
		if (rows[i] > rows[widestRow]) widestRow = i;
		if (cols[i] > cols[widestCol]) widestCol = i;
	}
	const info = el('div', { className: 'jac-info' });
	info.append(el('p', {},
		el('b', {}, `${num(drawn.n)} × ${num(drawn.n)}`), ', with ',
		el('b', {}, `${num(drawn.nnz)}`), ' structurally non-zero entries (',
		pct(drawn.density), ').',
		drawn.constant ? ' It is the same matrix at every point, so it is formed once '
			+ 'and factorised once for the whole run.' : ''));
	info.append(el('p', {},
		'Row ', el('i', {}, 'i'), ' is the equation for state ', el('i', {}, 'i'),
		'; column ', el('i', {}, 'j'), ' is the state it is differentiated with respect '
		+ 'to. The diagonal is drawn in the accent colour. Hover to name a cell.'));
	// The question this view invites, answered where it is asked.
	info.append(el('p', { className: 'hint' },
		'The pattern is structural: it is read off the equations and is the same at '
		+ 'every instant of every run. Only the ', el('i', {}, 'values'),
		' depend on the time and the state, and those are what the check below '
		+ 'compares — at four states across the run, not at one.'));
	info.append(el('p', {},
		'Differencing this matrix through its pattern costs ',
		el('b', {}, `${num(drawn.colours)}`),
		' evaluations of the model — one per group of columns that share no row — '
		+ `against ${num(drawn.n)} without it. The generated one costs none of them: `
		+ 'its values come from the generated code beside it.'));
	if (drawn.n > 1) {
		info.append(el('p', { className: 'hint' },
			`Busiest row: ${drawn.labels[widestRow]} reads ${num(rows[widestRow])} states. `
			+ `Busiest column: ${drawn.labels[widestCol]} is read by ${num(cols[widestCol])}.`));
	}
	if (stats) {
		info.append(el('p', {},
			'Last run: the iteration matrix was factorised ',
			el('b', {}, stats.sparse ? 'sparsely' : 'densely'),
			stats.sparse === false && drawn.density < 0.05
				? ' — the pattern is sparse, but the factor filled in towards dense, '
					+ 'and a dense factorisation of it was measured to be cheaper.'
				: '.'));
	}

	host.append(el('div', { className: 'jac-split' }, figure, info));

	// --- the check -----------------------------------------------------------
	host.append(renderCheck({ drawn, check, busy, progress, onCheck }));

	// --- painting and the hover ---------------------------------------------
	const draw = () => {
		const box = Math.max(180, Math.min(520, (host.clientWidth || 560) - 320));
		const geom = paint(canvas, pattern, colours, box);
		// The hover is tied to the canvas's width, not left to find its own.
		// Its lines do not wrap, so a long pair of state names made this column
		// as wide as the text -- which on a small matrix is far wider than the
		// picture -- and the column beside it re-wrapped to fit whatever was
		// under the pointer. The text below the matrix must not decide the
		// width of the text beside it.
		hover.style.width = canvas.style.width;
		if (geom.summarised) {
			hoverRow.textContent = `Each pixel stands for ${Math.ceil(1 / geom.scale)} cells`;
			hoverCol.textContent = 'across, drawn where anything in that block is non-zero.';
			hoverWhat.textContent = ' ';
		}
	};
	draw();

	canvas.addEventListener('pointermove', (ev) => {
		const rect = canvas.getBoundingClientRect();
		const j = Math.floor(((ev.clientX - rect.left) / rect.width) * pattern.n);
		const i = Math.floor(((ev.clientY - rect.top) / rect.height) * pattern.n);
		if (i < 0 || j < 0 || i >= pattern.n || j >= pattern.n) return;
		const there = has(pattern, i, j);
		hoverRow.textContent = `row ${i}  ·  d[${drawn.labels[i]}]`;
		hoverCol.textContent = `col ${j}  ·  d${drawn.labels[j]}`;
		hoverWhat.textContent = i === j
			? `the diagonal — how it moves with itself${there ? '' : ' (absent)'}`
			: there ? 'structurally non-zero' : 'zero';
	});
	canvas.addEventListener('pointerleave', () => { draw(); });

	// Redrawn on a resize, since the cell size is read off the panel's width.
	// The observer watches `host`, which outlives the render -- so the previous
	// one is disconnected first, or every re-render would leave another behind
	// painting into a canvas that is no longer on the page.
	if (typeof ResizeObserver === 'function') {
		host._jacResize?.disconnect();
		const ro = new ResizeObserver(() => draw());
		ro.observe(host);
		host._jacResize = ro;
	}
}

/** The comparison, which is asked for separately because it is the slow half. */
function renderCheck({ drawn, check, busy, progress, onCheck }) {
	const checks = el('div', { className: 'jac-checks' });
	checks.append(el('h3', {}, 'Against finite differences'));

	if (busy === 'check') {
		checks.append(el('p', {}, 'Comparing the generated matrix with finite differences…'));
		const bar = el('div', { className: 'jac-bar' },
			el('div', { className: 'jac-bar-fill' }));
		bar.firstChild.style.width = `${Math.round(Math.min(1, progress) * 100)}%`;
		checks.append(bar);
		return checks;
	}

	if (!check) {
		checks.append(el('p', {},
			'The drawing above is the structure. Whether the ',
			el('i', {}, 'values'),
			' are right is a separate question, and a slower one: it costs an '
			+ 'evaluation of the whole model per colour group and per sampled column, '
			+ 'at four states across the run.'));
		const b = el('button', { className: 'primary', type: 'button' }, 'Check the values');
		b.addEventListener('click', () => onCheck?.());
		checks.append(el('p', {}, b));
		return checks;
	}

	const VERDICT = {
		agrees: ['is-ok', 'Agrees.', 'Every resolvable entry agrees with finite differences.'],
		differs: ['is-warn', 'Disagrees.', 'Some entries disagree with finite differences.'],
		missing: ['is-bad', 'An entry is missing.',
			'The pattern is missing an entry the model has. The solver never evaluates '
			+ 'a missing entry, so no tolerance recovers it.'],
		colouring: ['is-bad', 'The colouring is wrong.',
			'Two columns in one colour group share a row, so the values read back '
			+ 'through the colouring are sums.'],
	};
	const [cls, headline, said] = VERDICT[check.verdict] ?? ['', '', ''];
	checks.append(el('p', { className: `jac-verdict ${cls}` }, el('b', {}, headline), ` ${said}`));

	for (const c of check.at) {
		const line = el('p', {});
		line.append(el('b', {}, c.label), ': ');
		if (c.refused) { line.append(c.refused, '.'); checks.append(line); continue; }
		line.append(
			`${num(c.checked)} entries compared over ${num(c.groups)} colour group`
			+ `${c.groups === 1 ? '' : 's'}`,
			c.ofGroups && c.groups < c.ofGroups ? ` of ${num(c.ofGroups)}` : '',
			`, and ${num(c.columns)} column${c.columns === 1 ? '' : 's'} scanned for `
			+ 'entries the pattern does not have. ',
			el('b', {}, `${num(c.disagreements.length)}`),
			` differing by more than 0.1%. ${num(c.unresolvable)} were below what a `
			+ 'difference can resolve and were not judged.',
		);
		if (c.worst && !c.disagreements.length && c.checked) {
			line.append(` Worst agreement: ${c.worst.relative.toExponential(1)} relative, at `
				+ `d[${c.worst.rowLabel}]/d${c.worst.colLabel}.`);
		}
		checks.append(line);
		for (const d of c.disagreements.slice(0, 8)) {
			checks.append(el('p', { className: 'jac-bad' },
				`d[${d.rowLabel}] / d${d.colLabel}: generated `,
				el('b', {}, d.analytic.toExponential(4)),
				', differenced ', el('b', {}, d.numeric.toExponential(4)),
				` — ${pct(d.relative)} apart.`));
		}
		for (const o of c.outside.slice(0, 8)) {
			checks.append(el('p', { className: 'jac-bad' },
				`The pattern has no entry at d[${o.rowLabel}] / d${o.colLabel}, `
				+ 'and differencing finds ', el('b', {}, o.numeric.toExponential(4)),
				' there.'));
		}
	}
	checks.append(el('p', {},
		`The colouring is ${num(check.colouring.groups)} group`
		+ `${check.colouring.groups === 1 ? '' : 's'}`,
		check.colouring.clashes.length
			? `, and ${num(check.colouring.clashes.length)} of its columns share a row `
				+ 'with another in the same group — which is a fault in the colouring, '
				+ 'not in the matrix.'
			: ', and no two columns in a group share a row.'));
	checks.append(el('p', { className: 'hint' },
		'An entry counts as resolvable when its effect on the derivative over the '
		+ 'perturbation is larger than the rounding of that derivative; below that a '
		+ 'difference quotient is noise and says nothing either way. Most of a decay '
		+ 'chain is unresolvable at the starting state, which is why the comparison '
		+ 'is made at several.'));

	const again = el('button', { type: 'button' }, 'Check again');
	again.addEventListener('click', () => onCheck?.());
	checks.append(el('p', {}, again));
	return checks;
}
