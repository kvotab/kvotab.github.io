/**
 * A Canvas2D-shaped surface that writes SVG.
 *
 * WHY. The chart is drawn on a canvas, which is right for the screen: 63
 * series over 400 points is 25,000 line segments, and a canvas draws them in
 * one pass where an SVG of the same thing is 25,000 DOM nodes. But a canvas is
 * pixels, and a chart in a safety assessment is read in a report -- printed,
 * zoomed, and sometimes edited. So the chart is painted twice: once onto the
 * canvas for the screen, and once through here when a picture is asked for.
 *
 * The point is that it is *painted twice by the same code*. A second drawing
 * routine that emitted SVG would be a second chart, and the two would disagree
 * about a tick label or a dash pattern within a month. The chart's own paint
 * routine takes a context and does not care which of these it is.
 *
 * Only the members that chart uses are here -- twenty-two of them -- and
 * anything else is deliberately absent rather than a silent no-op: a call this
 * does not implement should be a loud failure while the drawing code is being
 * changed, not a shape missing from a report.
 *
 * `measureText` is delegated to a real canvas context. Text metrics are the one
 * thing that cannot be worked out from the values here, and getting them
 * slightly wrong shows up as tick labels that collide or a title that runs
 * past the plot -- so they come from the thing that will actually lay the text
 * out, at the same font.
 */

const NS = 'http://www.w3.org/2000/svg';

/** Rounded, because 14 decimal places of a pixel is noise in a file. */
const r = (v) => (Number.isFinite(v) ? Math.round(v * 100) / 100 : 0);

const esc = (s) => String(s)
	.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
	.replace(/"/g, '&quot;');

/** `600 11px ui-sans-serif, …` -> the SVG attributes for it. */
export function fontAttrs(font) {
	const m = /^\s*(?:(italic|oblique)\s+)?(?:(bold|bolder|lighter|[1-9]00)\s+)?([\d.]+)px\s+(.+)$/
		.exec(String(font ?? ''));
	if (!m) return { 'font-family': String(font ?? ''), 'font-size': '11' };
	const out = {
		'font-size': m[3],
		'font-family': m[4].trim(),
	};
	if (m[1]) out['font-style'] = m[1];
	if (m[2]) out['font-weight'] = m[2];
	return out;
}

/** The identity, and the two operations the chart applies to it. */
const IDENTITY = [1, 0, 0, 1, 0, 0];

const multiply = (m, n) => [
	m[0] * n[0] + m[2] * n[1],
	m[1] * n[0] + m[3] * n[1],
	m[0] * n[2] + m[2] * n[3],
	m[1] * n[2] + m[3] * n[3],
	m[0] * n[4] + m[2] * n[5] + m[4],
	m[1] * n[4] + m[3] * n[5] + m[5],
];

export class SvgCanvas {
	/**
	 * @param {number} width  in the same units the drawing code uses
	 * @param {number} height
	 * @param {CanvasRenderingContext2D} [measurer] where text metrics come
	 *   from; a scratch canvas is made when none is given
	 */
	constructor(width, height, measurer = null) {
		this.width = width;
		this.height = height;
		this._out = [];
		this._path = [];
		this._m = [...IDENTITY];
		this._stack = [];

		// Canvas defaults, so a drawing that sets none of these gets what it
		// would have got on a canvas.
		this.strokeStyle = '#000';
		this.fillStyle = '#000';
		this.lineWidth = 1;
		this.lineCap = 'butt';
		this.lineJoin = 'miter';
		this.font = '10px sans-serif';
		this.textAlign = 'start';
		this.textBaseline = 'alphabetic';
		this._dash = [];

		this._measurer = measurer ?? SvgCanvas.scratch();
	}

	/** A 2D context to measure text with, made once and kept. */
	static scratch() {
		if (!SvgCanvas._scratch) {
			const canvas = typeof document === 'undefined'
				? null
				: document.createElement('canvas');
			SvgCanvas._scratch = canvas ? canvas.getContext('2d') : null;
		}
		return SvgCanvas._scratch;
	}

	// --- state ------------------------------------------------------------
	save() {
		this._stack.push({
			m: [...this._m],
			strokeStyle: this.strokeStyle,
			fillStyle: this.fillStyle,
			lineWidth: this.lineWidth,
			lineCap: this.lineCap,
			lineJoin: this.lineJoin,
			font: this.font,
			textAlign: this.textAlign,
			textBaseline: this.textBaseline,
			dash: [...this._dash],
		});
	}

	restore() {
		const s = this._stack.pop();
		if (!s) return;
		this._m = s.m;
		this.strokeStyle = s.strokeStyle;
		this.fillStyle = s.fillStyle;
		this.lineWidth = s.lineWidth;
		this.lineCap = s.lineCap;
		this.lineJoin = s.lineJoin;
		this.font = s.font;
		this.textAlign = s.textAlign;
		this.textBaseline = s.textBaseline;
		this._dash = s.dash;
	}

	setLineDash(d) { this._dash = Array.from(d ?? []); }

	getLineDash() { return [...this._dash]; }

	translate(x, y) { this._m = multiply(this._m, [1, 0, 0, 1, x, y]); }

	rotate(a) {
		const c = Math.cos(a);
		const s = Math.sin(a);
		this._m = multiply(this._m, [c, s, -s, c, 0, 0]);
	}

	/** Only the reset form the chart uses: the picture has its own scale. */
	setTransform() { this._m = [...IDENTITY]; }

	/** A canvas starts blank and so does an SVG, so there is nothing to do. */
	clearRect() {}

	// --- paths ------------------------------------------------------------
	beginPath() { this._path = []; }

	moveTo(x, y) { this._path.push(`M ${r(x)} ${r(y)}`); }

	lineTo(x, y) { this._path.push(`L ${r(x)} ${r(y)}`); }

	/**
	 * Circles and arcs, as the chart's hover markers use them.
	 *
	 * A full turn cannot be written as one elliptical arc -- start and end
	 * would be the same point and nothing would be drawn -- so it goes as two
	 * halves, which is what every SVG library does.
	 */
	arc(cx, cy, radius, from, to, ccw = false) {
		const full = Math.abs(to - from) >= Math.PI * 2 - 1e-9;
		const sweep = ccw ? 0 : 1;
		const at = (a) => `${r(cx + radius * Math.cos(a))} ${r(cy + radius * Math.sin(a))}`;
		if (full) {
			this._path.push(`M ${at(from)}`);
			this._path.push(`A ${r(radius)} ${r(radius)} 0 1 ${sweep} ${at(from + Math.PI)}`);
			this._path.push(`A ${r(radius)} ${r(radius)} 0 1 ${sweep} ${at(from)}`);
			return;
		}
		const large = Math.abs(to - from) > Math.PI ? 1 : 0;
		this._path.push(`M ${at(from)}`);
		this._path.push(`A ${r(radius)} ${r(radius)} 0 ${large} ${sweep} ${at(to)}`);
	}

	stroke() {
		if (!this._path.length) return;
		this._emit('path', {
			d: this._path.join(' '),
			fill: 'none',
			stroke: this.strokeStyle,
			'stroke-width': r(this.lineWidth),
			...(this.lineCap !== 'butt' ? { 'stroke-linecap': this.lineCap } : {}),
			...(this.lineJoin !== 'miter' ? { 'stroke-linejoin': this.lineJoin } : {}),
			...(this._dash.length ? { 'stroke-dasharray': this._dash.map(r).join(' ') } : {}),
		});
	}

	fill() {
		if (!this._path.length) return;
		this._emit('path', {
			d: `${this._path.join(' ')} Z`,
			fill: this.fillStyle,
			stroke: 'none',
		});
	}

	// --- text -------------------------------------------------------------
	measureText(text) {
		if (!this._measurer) {
			// No canvas to ask -- a test, or a worker. An average character
			// width is the honest fallback; it is only used to keep labels
			// from colliding, and saying nothing would collide every time.
			const size = Number(fontAttrs(this.font)['font-size']) || 10;
			return { width: String(text ?? '').length * size * 0.55 };
		}
		this._measurer.font = this.font;
		return this._measurer.measureText(String(text ?? ''));
	}

	/**
	 * Text, with the baseline worked out here rather than left to SVG.
	 *
	 * `dominant-baseline` is the SVG way to say "middle" or "top", and it is
	 * the one thing in this file that other programs disagree about: Inkscape
	 * honours it, Word and Illustrator variously do not. So the offset from
	 * the alphabetic baseline is computed from the font's own metrics and put
	 * into `y`, which every reader gets right.
	 */
	fillText(text, x, y) {
		const attrs = fontAttrs(this.font);
		this._emit('text', {
			x: r(x),
			y: r(y + this._baselineShift()),
			fill: this.fillStyle,
			...attrs,
			...(this.textAlign && this.textAlign !== 'start' && this.textAlign !== 'left'
				? { 'text-anchor': this.textAlign === 'center' ? 'middle' : 'end' }
				: {}),
			// Whitespace at either end of a label is meaningful to nobody, but
			// a reader that collapses it would shift the text.
			'xml:space': 'preserve',
		}, esc(text));
	}

	_baselineShift() {
		const m = this.measureText('Mg');
		const size = Number(fontAttrs(this.font)['font-size']) || 10;
		const ascent = m.fontBoundingBoxAscent ?? m.actualBoundingBoxAscent ?? size * 0.8;
		const descent = m.fontBoundingBoxDescent ?? m.actualBoundingBoxDescent ?? size * 0.2;
		switch (this.textBaseline) {
			case 'top':
			case 'hanging':
				return ascent;
			case 'middle':
				return (ascent - descent) / 2;
			case 'bottom':
			case 'ideographic':
				return -descent;
			default:
				return 0;
		}
	}

	// --- output -----------------------------------------------------------
	_emit(tag, attrs, body = null) {
		const m = this._m;
		const moved = m.some((v, i) => v !== IDENTITY[i]);
		const parts = Object.entries(attrs)
			.filter(([, v]) => v !== undefined && v !== null && v !== '')
			.map(([k, v]) => `${k}="${esc(v)}"`);
		if (moved) parts.push(`transform="matrix(${m.map(r).join(' ')})"`);
		this._out.push(body == null
			? `<${tag} ${parts.join(' ')}/>`
			: `<${tag} ${parts.join(' ')}>${body}</${tag}>`);
	}

	/**
	 * @param {{background?: string, title?: string}} [opts]
	 * @returns {string} a standalone SVG document
	 */
	toSVG({ background = '', title = '' } = {}) {
		const head = `<svg xmlns="${NS}" width="${r(this.width)}" `
			+ `height="${r(this.height)}" viewBox="0 0 ${r(this.width)} ${r(this.height)}">`;
		const bg = background
			? `<rect x="0" y="0" width="${r(this.width)}" height="${r(this.height)}" `
				+ `fill="${esc(background)}"/>`
			: '';
		return [
			'<?xml version="1.0" encoding="UTF-8"?>',
			head,
			title ? `<title>${esc(title)}</title>` : '',
			bg,
			...this._out,
			'</svg>',
		].filter(Boolean).join('\n');
	}
}
