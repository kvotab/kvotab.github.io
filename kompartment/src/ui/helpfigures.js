/**
 * Diagrams for the documentation.
 *
 * A guide about a graphical editor that has no pictures in it is asking the
 * reader to build the picture themselves, from prose, while looking at the
 * thing it describes. These are the pictures.
 *
 * HOW THEY ARE WRITTEN. A figure is a fenced block in the Markdown:
 *
 *     ```figure block-kinds
 *     [ Compartment ] --rate--> [ Compartment ]
 *     ```
 *
 * The fence body is an ASCII sketch and the fence's word is a key into the
 * table below. Inside the application the key wins and the SVG is drawn; in a
 * plain Markdown viewer -- a text editor, a repository page -- there is no
 * table, and the ASCII sketch shows instead. So the document is legible in
 * both places and neither copy has to be maintained twice: the sketch is the
 * alt text, written where alt text is easy to write.
 *
 * WHY SVG AND NOT IMAGES. Two reasons that matter more than they look. A
 * drawing built from the same palette variables as the rest of the interface
 * follows the theme, so the light diagram does not glare out of a dark page.
 * And a `.png` of a box labelled "Compartment" is a second statement of what
 * a compartment looks like, which goes stale the week the node styling
 * changes; this is at least written beside the code that draws the real one.
 *
 * Every figure returns one `<svg>` with a `viewBox`, so it scales to whatever
 * measure the reader has chosen for the text.
 */

import { el } from './parts.js';

const NS = 'http://www.w3.org/2000/svg';

/** One SVG element with its attributes, as the rest of the interface makes them. */
const svg = (tag, attrs = {}) => {
	const n = document.createElementNS(NS, tag);
	for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, String(v));
	return n;
};

/* ------------------------------------------------------------------ *
 * The pieces every figure is drawn from
 * ------------------------------------------------------------------ */

/** A labelled box. `kind` picks the outline: solid, dashed, or a note. */
function box(x, y, w, h, label, kind = 'solid', sub = null) {
	const g = svg('g', { class: `hf-box hf-${kind}` });
	g.append(svg('rect', { x, y, width: w, height: h, rx: 6 }));
	const cy = sub ? y + h / 2 - 5 : y + h / 2;
	g.append(text(x + w / 2, cy, label, 'hf-label'));
	if (sub) g.append(text(x + w / 2, y + h / 2 + 9, sub, 'hf-sub'));
	return g;
}

/** Centred text. The baseline is nudged so `y` reads as the middle. */
function text(x, y, s, cls = 'hf-label') {
	const t = svg('text', { x, y, class: cls, 'text-anchor': 'middle' });
	t.textContent = s;
	return t;
}

/** Left-aligned text, for a caption that sits beside something. */
function label(x, y, s, cls = 'hf-sub') {
	const t = svg('text', { x, y, class: cls });
	t.textContent = s;
	return t;
}

/**
 * An arrow from one point to another, bowed by `bow` pixels.
 *
 * The head is drawn as a filled triangle rather than a marker: a marker
 * inherits the stroke width and comes out spindly on a thin line, and this
 * way the same head serves a dashed influence and a solid transfer.
 */
function arrow(x1, y1, x2, y2, { bow = 0, kind = 'flow', caption = null } = {}) {
	const g = svg('g', { class: `hf-arrow hf-${kind}` });
	const mx = (x1 + x2) / 2;
	const my = (y1 + y2) / 2 - bow;
	g.append(svg('path', { d: `M ${x1} ${y1} Q ${mx} ${my} ${x2} ${y2}`, class: 'hf-line' }));

	// The head points along the tangent at the end, which for a quadratic is
	// the line from the control point to the end.
	const a = Math.atan2(y2 - my, x2 - mx);
	const s = 5;
	const p = (ang, r) => `${x2 - r * Math.cos(ang)} ${y2 - r * Math.sin(ang)}`;
	g.append(svg('path', {
		class: 'hf-head',
		d: `M ${x2} ${y2} L ${p(a - 0.4, s * 1.8)} L ${p(a + 0.4, s * 1.8)} Z`,
	}));
	if (caption) {
		const ty = (y1 + y2) / 2 - bow * 0.55 - 5;
		g.append(text(mx, ty, caption, 'hf-cap'));
	}
	return g;
}

/** The frame a whole figure lives in. */
function figure(w, h, ...parts) {
	const s = svg('svg', {
		class: 'md-figure', viewBox: `0 0 ${w} ${h}`, role: 'img',
		preserveAspectRatio: 'xMidYMid meet',
	});
	s.append(...parts);
	return s;
}

/* ------------------------------------------------------------------ *
 * The figures
 * ------------------------------------------------------------------ */

const FIGURES = {
	/** What the six block shapes on the diagram mean. */
	'block-kinds': () => figure(640, 200,
		box(10, 20, 120, 44, 'Compartment', 'solid', 'holds an amount'),
		box(150, 20, 120, 44, 'Expression', 'dashed', 'worked out'),
		box(290, 20, 120, 44, 'Parameter', 'param', 'a number'),
		box(430, 20, 120, 44, 'Lookup', 'param', 'value vs time'),
		box(10, 92, 120, 44, 'Source / sink', 'sink', 'outside the model'),
		box(150, 92, 120, 44, 'Sub-system', 'group', 'a model inside'),
		box(290, 92, 120, 44, 'Min / max', 'recorder', 'remembers'),
		box(430, 92, 120, 44, 'Discrete event', 'event', 'an instant'),
		label(10, 168, 'Solid outline: the solver integrates it. Dashed: it is worked out from'),
		label(10, 182, 'the others at every step. Shape carries the family, colour the member.'),
	),

	/** The smallest model there is, and what each part of it is called. */
	'two-box': () => figure(560, 190,
		box(40, 60, 130, 52, 'Source', 'solid', 'initial 1000 Bq'),
		box(370, 60, 130, 52, 'Sink', 'solid', 'initial 0'),
		arrow(170, 86, 370, 86, { bow: 26, caption: 'rate = k · Source' }),
		label(40, 140, 'A transfer carries rate × the amount in the compartment it leaves.'),
		label(40, 156, 'Its unit follows from that, so it is never typed in.'),
		label(40, 172, 'k is a Parameter; give it a value and the model runs.'),
	),

	/** How an index list turns one drawn block into many states. */
	'indexing': () => figure(600, 210,
		box(20, 24, 150, 46, 'Soil', 'solid', 'one block drawn'),
		text(230, 52, '×', 'hf-op'),
		box(270, 24, 150, 46, 'Radionuclides', 'param', 'I-129, Cs-137, U-238'),
		text(470, 52, '=', 'hf-op'),
		box(20, 106, 110, 34, 'Soil[I-129]', 'solid'),
		box(145, 106, 110, 34, 'Soil[Cs-137]', 'solid'),
		box(270, 106, 110, 34, 'Soil[U-238]', 'solid'),
		label(20, 170, 'Three states, one equation, one drawn box. Index lists are what make a'),
		label(20, 186, 'model N-dimensional: add a Landscape list and the three become fifteen.'),
	),

	/** What happens between pressing Run and seeing a curve. */
	'run-pipeline': () => figure(680, 150,
		box(10, 30, 110, 44, 'Model', 'param', 'blocks & equations'),
		arrow(120, 52, 165, 52),
		box(165, 30, 110, 44, 'Build', 'dashed', 'one derivative fn'),
		arrow(275, 52, 320, 52),
		box(320, 30, 110, 44, 'Solve', 'solid', 'in a Worker'),
		arrow(430, 52, 475, 52),
		box(475, 30, 110, 44, 'Results', 'recorder', 'chart, table, file'),
		label(10, 106, 'The build is where an error in an equation is caught, and where the'),
		label(10, 122, 'analytic Jacobian is written. The solve runs off the page, so the'),
		label(10, 138, 'interface stays live and a long run can be stopped.'),
	),

	/** Which solver to reach for. */
	'solver-choice': () => figure(640, 240,
		box(240, 10, 160, 38, 'Is it stiff?', 'event'),
		arrow(280, 48, 150, 86, { kind: 'flow', caption: 'no' }),
		arrow(360, 48, 470, 86, { kind: 'flow', caption: 'yes' }),
		box(60, 86, 180, 38, 'Dormand-Prince 4-5', 'dashed'),
		box(390, 86, 180, 38, 'NDF (the default)', 'solid'),
		box(390, 144, 180, 38, 'Rosenbrock 5', 'solid'),
		arrow(480, 124, 480, 144, { kind: 'dotted' }),
		label(60, 142, 'Smooth, well-scaled,'),
		label(60, 158, 'few states.'),
		label(60, 196, 'Half-lives spanning decades make a model stiff, which is'),
		label(60, 212, 'most of them here. If a run will not converge, try Rosenbrock 5:'),
		label(60, 228, 'it has no Newton iteration, so there is nothing to fail.'),
	),

	/** Where everything is on screen. */
	'anatomy': () => figure(660, 260,
		box(10, 10, 640, 26, 'New   Open   Import        Run        Theme', 'group'),
		box(10, 44, 150, 170, 'Model tree', 'param', 'every block, by sub-system'),
		box(170, 44, 320, 140, 'Build  ·  Matrix  ·  Chart  ·  Table', 'dashed', 'the eight tabs'),
		box(500, 44, 150, 170, 'Inspector', 'param', 'what is selected'),
		box(170, 192, 320, 22, 'Problems · statistics · run log', 'group'),
		label(10, 238, 'The tree, the diagram, the matrix and the JSON tab all edit one model:'),
		label(10, 254, 'a change in any of them shows in the others straight away.'),
	),

	/** What the sparsity pattern of df/dy looks like, and how to read it. */
	'jacobian-pattern': () => figure(620, 250,
		label(20, 18, 'columns: the state differentiated with respect to'),
		label(20, 34, 'rows: the equation for that state'),
		(() => {
			// A little 8x8 matrix: a diagonal, a sub-diagonal band (a decay
			// chain) and one dense row (something that reads everything).
			const g = svg('g');
			const x0 = 30, y0 = 52, cell = 22;
			for (let i = 0; i < 8; i++) {
				for (let j = 0; j < 8; j++) {
					const on = i === j || i === j + 1 || i === 7;
					if (!on) continue;
					g.append(svg('rect', {
						x: x0 + j * cell, y: y0 + i * cell, width: cell - 2, height: cell - 2,
						class: i === j ? 'hf-diag' : 'hf-entry', rx: 2,
					}));
				}
			}
			g.append(svg('rect', {
				x: x0 - 3, y: y0 - 3, width: 8 * cell + 4, height: 8 * cell + 4,
				class: 'hf-frame', rx: 3,
			}));
			return g;
		})(),
		label(240, 90, 'the diagonal: how a state moves with itself'),
		label(240, 112, 'the band under it: ingrowth from a parent'),
		label(240, 134, 'a dense row: something that reads everything'),
		label(240, 156, 'everything else is a structural zero, and'),
		label(240, 172, 'is never evaluated, stored or factorised'),
		label(20, 240, 'A compartment model is nearly all zeros; the shape of what is left is the model.'),
	),

	/** The three availability schemes on one axis. */
	'availability': () => figure(620, 200,
		label(20, 22, 'Flux = rate × availability × amount in the donor'),
		box(20, 40, 170, 40, 'No limit', 'dashed', 'availability = 1'),
		box(210, 40, 170, 40, 'Solubility limit', 'solid', 'min(limit ÷ amount, 1)'),
		box(400, 40, 190, 40, 'Langmuir', 'recorder', '(amount + α) ÷ (amount + β)'),
		label(20, 110, 'Past a solubility limit the excess is precipitate: it stays behind.'),
		label(20, 126, 'Under a sorption isotherm the fraction free to move rises with the'),
		label(20, 142, 'inventory instead of staying fixed.'),
		label(20, 170, 'The availability belongs to the transfer, not to the compartment —'),
		label(20, 186, 'a limit holds back what leaches and not what erodes.'),
	),
};

/** Whether a fenced block names a figure this module can draw. */
export function hasFigure(name) {
	return Object.prototype.hasOwnProperty.call(FIGURES, String(name ?? '').trim());
}

/**
 * The drawing for a figure fence, or null.
 *
 * The caller falls back to the fence body when this answers null, which is
 * what keeps a typo in a figure name from silently swallowing a diagram.
 *
 * @param {string} name   the word after ```figure
 * @param {string} sketch the fence body, used as the accessible description
 * @returns {SVGElement|null}
 */
export function renderFigure(name, sketch = '') {
	const key = String(name ?? '').trim();
	const make = FIGURES[key];
	if (!make) return null;
	const drawing = make();
	// The ASCII sketch is the alt text. It was written to be read, which is
	// more than can be said for most alt text, and it is already in the file.
	const title = svg('title');
	title.textContent = sketch.trim() || key.replace(/-/g, ' ');
	drawing.prepend(title);
	return el('div', { className: 'md-figure-wrap' }, drawing);
}

/** The names, for a test that every figure a document asks for exists. */
export const FIGURE_NAMES = Object.keys(FIGURES);
