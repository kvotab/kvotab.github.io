/**
 * Time chart on a 2D canvas.
 *
 * Log-log is the default because that is how activity-versus-time results are
 * read in a safety assessment: inventories span many decades and the
 * interesting behaviour is spread over four or five orders of magnitude of time.
 */

import { SvgCanvas } from './svgcanvas.js';
import { wheelPixels } from './wheel.js';
import { PICTURE_KINDS, fileName, saveBlob } from './picture.js';
import { el } from './parts.js';

/**
 * Colour comes from the validated categorical palette in the page's CSS custom
 * properties (--series-1 .. --series-8), read at draw time so a theme change
 * is picked up.
 *
 * Eight hues, assigned in fixed order. Past the eighth they begin again, and
 * what tells the second set from the first is the *line style*: a series is a
 * hue and a dash pattern together, so no two of the 32 look alike. Cycling a
 * palette on its own would be the one thing a categorical palette must not do
 * -- two lines the same colour are two lines you cannot tell apart -- and a
 * second channel is what makes the repeat legible rather than a collision.
 * Every place that shows a series shows both: the line, the label at its end,
 * the legend, the tooltip and the picker.
 */
export const SERIES_COLORS = 8;

/**
 * The dash patterns, in the order the sets take them, in device-independent
 * pixels at the 2px line width the chart draws with.
 *
 * Chosen to survive that width: `[2, 4]` with the round cap the solid lines
 * use would grow each dot by a line width at both ends and close the gaps, so
 * a dashed line is drawn with a butt cap instead.
 */
export const SERIES_DASHES = [[], [8, 5], [2, 4], [12, 4, 2.5, 4]];

/** How many series one chart can hold: every hue in every style. */
export const MAX_SERIES = SERIES_COLORS * SERIES_DASHES.length;

/**
 * How many a chart *opens* with, when nothing has been picked.
 *
 * One set, so the first thing anyone sees is eight solid lines rather than
 * thirty-two lines in four styles. The rest is there to be asked for.
 */
export const DEFAULT_SERIES = SERIES_COLORS;

/**
 * Which hue and which dash pattern series `i` wears.
 *
 * @param {number} i the series' position on the chart
 * @returns {{color: number, dash: number[], set: number}} `color` is the
 *   zero-based index into the palette; `set` is which repeat it is, which is
 *   what the swatches key their pattern off.
 */
export function seriesStyle(i) {
	const slot = ((Math.trunc(i) % MAX_SERIES) + MAX_SERIES) % MAX_SERIES;
	return {
		color: slot % SERIES_COLORS,
		set: Math.floor(slot / SERIES_COLORS),
		dash: SERIES_DASHES[Math.floor(slot / SERIES_COLORS)],
	};
}

/**
 * The hue and the pattern a series wears, honouring what it asks for.
 *
 * A series may name another's `slot` to say it *is* that series in another
 * guise: the mean of the realisations beside their median, the model's own run
 * beside both. Those want the one colour in different patterns -- the colour
 * says which output this is, the pattern says which line of it -- which is
 * what `set` names on its own.
 *
 * Both are the exception. A series with neither wears the style its position
 * gives it, which is every series on an ordinary chart.
 *
 * @param {object} s   the series
 * @param {number} si  where it sits on the chart
 */
export function styleOf(s, si) {
	const base = seriesStyle(Number.isInteger(s?.slot) ? s.slot : si);
	if (!Number.isInteger(s?.set)) return base;
	const n = SERIES_DASHES.length;
	const set = ((s.set % n) + n) % n;
	return { color: base.color, set, dash: SERIES_DASHES[set] };
}

/**
 * The markup for a swatch that stands for series `i`: a short line in its own
 * colour and its own pattern.
 *
 * One function for the legend, the tooltip and the picker, because three
 * swatches that disagreed about which line they meant would be worse than
 * none. The pattern itself is in the stylesheet, keyed by `data-set` --
 * repeating gradients belong there, and the palette is already there.
 */
export function swatchAttrs(i) {
	const { color, set } = seriesStyle(i);
	return { '--swatch': `var(--series-${color + 1})`, 'data-set': String(set) };
}

/**
 * Which of a run's outputs pass the chart's filter.
 *
 * Here rather than in the panel because it is the one part of the picker that
 * is a rule rather than a rendering, and a rule with a history: it used to be
 * ruled on index *names* without regard to which list they came from, and that
 * let two kinds of line through a filter they did not satisfy.
 *
 * The rule now: every list with a selection is a constraint, and to pass, an
 * output has to be indexed by that list *and* carry one of the chosen indices
 * there. So a filter nothing satisfies lists nothing -- which is the point of
 * a filter -- and a line with no dimension of a constrained list is out,
 * rather than in on the argument that a sum over nuclides concerns them all.
 *
 * A constraint may stand for several lists at once -- `groups` says which. A
 * sub-set shares its indices' names with the list it is cut from, so the
 * radionuclides and the materials they are among are one question to a
 * reader ("which nuclide?"), asked once and answered for a line indexed by
 * either. A line indexed by none of a group's lists fails the constraint, as
 * before.
 *
 * @param {Array<{kind: string, label: string, dims?: string[], index?: string[]}>} outputs
 * @param {{query?: string, kinds?: Set<string>, indices?: Map<string, Set<string>>,
 *          groups?: Map<string, string[]>}} filter `indices` is keyed by list, or by
 *   group where `groups` names the lists a key stands for
 * @param {(label: string) => boolean} matches the name matcher for `query`
 * @returns {number[]} the indices of the outputs that pass, in order
 */
export function filterOutputs(outputs, filter, matches) {
	const kinds = filter.kinds ?? new Set();
	const indices = filter.indices ?? new Map();
	const groups = filter.groups ?? new Map();
	const out = [];
	outputs.forEach((o, i) => {
		if (kinds.size && !kinds.has(o.kind)) return;
		for (const [key, chosen] of indices) {
			if (!chosen.size) continue;
			const lists = groups.get(key) ?? [key];
			const dims = o.dims ?? [];
			const at = dims.findIndex((d) => lists.includes(d));
			if (at < 0) return;
			if (!chosen.has(o.index?.[at])) return;
		}
		if (!matches(o.label)) return;
		out.push(i);
	});
	return out;
}

/**
 * Which lists the chart's filter asks about together: a sub-set and the list
 * it is cut from share their index names, so they are one question. A mapped
 * list is not -- its indices are its own (`Cs` is not `Cs-137`) -- and stays a
 * group of its own. The key is the root of the sub-set chain; the value lists
 * the members, the root first when it is there.
 *
 * @param {Array<{name: string, sub_set_of?: string|null}>} lists the model's index lists
 * @param {Iterable<string>} used the lists the outputs actually carry
 * @returns {Map<string, string[]>}
 */
export function filterGroups(lists, used) {
	const byName = new Map((lists ?? []).map((l) => [l.name, l]));
	const rootOf = (name) => {
		let at = name;
		for (let i = 0; at && i <= byName.size; i++) {
			const parent = byName.get(at)?.sub_set_of;
			if (!parent || !byName.has(parent)) return at;
			at = parent;
		}
		return name;
	};
	const groups = new Map();
	for (const name of used) {
		const root = rootOf(name);
		if (!groups.has(root)) groups.set(root, []);
		groups.get(root).push(name);
	}
	for (const [root, members] of groups) {
		members.sort((a, b) => (a === root ? -1 : b === root ? 1 : 0));
	}
	return groups;
}

/** How many rows the crosshair readout shows before it starts summarising. */
const TOOLTIP_ROWS = 12;

/**
 * The legend band a picture of the chart carries.
 *
 * A column has to hold a swatch, a gap and a label; 180 is what the longest
 * output names in these models need before they are cut, and cutting is worse
 * than a second row.
 */
/**
 * How many series get their name at the end of their own line.
 *
 * Past this the chart says nothing about which line is which and the legend
 * does the naming -- which is why a picture of one needs the band.
 */
export const DIRECT_LABELS_UP_TO = 4;

/** Whether a point is inside the plot, with a hair of slack. */
const inPlot = (p, r) => p.x >= r.x - 0.01 && p.x <= r.x + r.w + 0.01
	&& p.y >= r.y - 0.01 && p.y <= r.y + r.h + 0.01;

/**
 * The part of a segment that is inside the plot, or null.
 *
 * Liang--Barsky, which is the short one: the segment is parameterised, each
 * edge of the rectangle clips the parameter range, and what is left is the
 * visible piece. Cheap enough to run on every segment of every series --
 * thirty-two series of four hundred points is arithmetic, not a bottleneck.
 */
export function clipSegment(a, b, r) {
	const dx = b.x - a.x;
	const dy = b.y - a.y;
	let t0 = 0;
	let t1 = 1;
	const edges = [
		[-dx, a.x - r.x],
		[dx, r.x + r.w - a.x],
		[-dy, a.y - r.y],
		[dy, r.y + r.h - a.y],
	];
	for (const [p, q] of edges) {
		if (p === 0) {
			// Parallel to this edge, and outside it: nothing to draw.
			if (q < 0) return null;
			continue;
		}
		const t = q / p;
		if (p < 0) {
			if (t > t1) return null;
			if (t > t0) t0 = t;
		} else {
			if (t < t0) return null;
			if (t < t1) t1 = t;
		}
	}
	return {
		a: { x: a.x + t0 * dx, y: a.y + t0 * dy },
		b: { x: a.x + t1 * dx, y: a.y + t1 * dy },
	};
}

/** The least room two direct labels can share. */
const LABEL_GAP = 13;

/**
 * Label positions that do not overlap and stay inside the plot.
 *
 * A greedy pass down the list and then, if the last one has been pushed past
 * the bottom, a pass back up: that is the standard way, and the reason for the
 * second pass is a chart zoomed so that every line leaves through the top of
 * the window -- all four want the same height, and stacking them downwards
 * alone would run them off the end of the axis.
 *
 * @param {Array<{at: number}>} wanted where each label would like to be
 * @param {{y: number, h: number}} plot
 * @returns the same objects with a `y` that can be drawn at
 */
export function spreadLabels(wanted, plot, gap = 13) {
	const top = plot.y + 6;
	const bottom = plot.y + plot.h - 6;
	const out = [...wanted]
		.map((p) => ({ ...p, y: Math.min(Math.max(p.at, top), bottom) }))
		.sort((a, b) => a.y - b.y);
	for (let i = 1; i < out.length; i++) {
		if (out[i].y - out[i - 1].y < gap) out[i].y = out[i - 1].y + gap;
	}
	// Off the bottom: shift the whole stack up by the overflow, which keeps
	// the spacing the forward pass just established -- correcting label by
	// label instead compounds the shift and stacks two of them again.
	const over = out.length ? out[out.length - 1].y - bottom : 0;
	if (over > 0) {
		for (const p of out) p.y -= over;
		// Unless that pushed the first above the top, in which case there is
		// less room than there are labels and downwards is all there is.
		if (out[0].y < top) {
			out[0].y = top;
			for (let i = 1; i < out.length; i++) {
				if (out[i].y - out[i - 1].y < gap) out[i].y = out[i - 1].y + gap;
			}
		}
	}
	return out;
}

/** How far a drag has to go before it is a zoom rather than a click. */
const ZOOM_SLOP = 6;

const LEGEND_COL = 180;
const LEGEND_ROW = 16;
const LEGEND_PAD = 16;

const AXIS_FONT = '11px ui-sans-serif, -apple-system, "Segoe UI", system-ui, sans-serif';
const LABEL_FONT = '600 11px ui-sans-serif, -apple-system, "Segoe UI", system-ui, sans-serif';

export class TimeChart {
	/**
	 * @param {HTMLElement} container
	 */
	constructor(container) {
		this.container = container;
		this.container.classList.add('chart-root');

		this.canvas = document.createElement('canvas');
		this.canvas.className = 'chart-canvas';
		// A crosshair over the plot: the pointer is for reading a value off
		// it and for dragging a window out of it, and an arrow says neither.
		this.canvas.style.cursor = 'crosshair';
		this.container.appendChild(this.canvas);

		this.tooltip = document.createElement('div');
		this.tooltip.className = 'chart-tooltip';
		this.tooltip.hidden = true;
		this.container.appendChild(this.tooltip);

		this.ctx = this.canvas.getContext('2d');

		this.data = { t: new Float64Array(0), series: [] };
		this.xLog = true;
		this.yLog = true;
		this.xLabel = 'Time';
		this.yLabel = '';
		this.hover = null;
		/**
		 * The window being looked at, or null for the whole of the data.
		 *
		 * Kept across a re-run on purpose: changing a parameter and running
		 * again, while watching one decade of one peak, is the reason to zoom
		 * in the first place -- and a window that reset itself every time
		 * would make that the one thing zoom could not do. It survives a
		 * change of series for the same reason, and the menu says when the
		 * chart is not showing everything.
		 */
		this.zoom = null;
		this.drag = null;
		/**
		 * What a plain drag does: draw a zoom rectangle, or pan.
		 *
		 * A rectangle by default, because that is the conventional gesture and so
		 * Ecolego's. The modifier -- shift, alt or the platform key -- does
		 * the other one, whichever way round this is set, so both are always
		 * available and neither is hidden behind a mode you have to remember
		 * being in. The menu carries it as a tick, which is also how anyone
		 * finds out that panning is there at all.
		 */
		this.dragPans = false;

		this._onMove = this._onMove.bind(this);
		this._onLeave = this._onLeave.bind(this);
		this._onDown = this._onDown.bind(this);
		this._onUp = this._onUp.bind(this);
		this._onWheel = this._onWheel.bind(this);
		this._onDblClick = this._onDblClick.bind(this);
		this.canvas.addEventListener('pointermove', this._onMove);
		this.canvas.addEventListener('pointerleave', this._onLeave);
		this.canvas.addEventListener('pointerdown', this._onDown);
		this.canvas.addEventListener('pointerup', this._onUp);
		this.canvas.addEventListener('pointercancel', this._onUp);
		this.canvas.addEventListener('dblclick', this._onDblClick);
		// Not passive: a wheel over the chart zooms it, and the page must not
		// scroll underneath the gesture.
		this.canvas.addEventListener('wheel', this._onWheel, { passive: false });

		this._ro = new ResizeObserver(() => this._scheduleDraw());
		this._ro.observe(this.container);
		this._frame = 0;
	}

	/**
	 * A repaint at the next animation frame, and at most one per frame.
	 *
	 * The chart redraws every series from scratch, and the hover redrew it
	 * synchronously on every pointer move. A pointer reports faster than the
	 * display refreshes -- a high-rate mouse, or the run of coalesced moves a
	 * trackpad delivers in one go -- so a chart of thirty-two series over
	 * twenty thousand points was painted several times between frames, and
	 * every painting but the last was thrown away unseen.
	 */
	_scheduleDraw() {
		// No frame clock: the tests drive this class in Node, where a repaint
		// deferred to a frame that never comes is a repaint that never
		// happens. Straight to the paint there.
		if (typeof requestAnimationFrame !== 'function') { this.draw(); return; }
		if (this._frame) return;
		this._frame = requestAnimationFrame(() => {
			this._frame = 0;
			this.draw();
		});
	}

	destroy() {
		if (this._frame && typeof cancelAnimationFrame === 'function') {
			cancelAnimationFrame(this._frame);
		}
		this._frame = 0;
		this._ro.disconnect();
		this.canvas.removeEventListener('pointermove', this._onMove);
		this.canvas.removeEventListener('pointerleave', this._onLeave);
		this.canvas.removeEventListener('pointerdown', this._onDown);
		this.canvas.removeEventListener('pointerup', this._onUp);
		this.canvas.removeEventListener('pointercancel', this._onUp);
		this.canvas.removeEventListener('dblclick', this._onDblClick);
		this.canvas.removeEventListener('wheel', this._onWheel);
	}

	/**
	 * @param {Float64Array} t
	 * @param {Array<{label: string, values: Float64Array, unit?: string}>} series
	 */
	setData(t, series, { xLabel, yLabel } = {}) {
		if (series.length > MAX_SERIES) {
			throw new Error(
				`A chart shows at most ${MAX_SERIES} series; ${series.length} were given.`,
			);
		}
		this.data = { t, series };
		if (xLabel !== undefined) this.xLabel = xLabel;
		if (yLabel !== undefined) this.yLabel = yLabel;
		this.hover = null;
		this.draw();
	}

	/**
	 * Whether a plain drag pans instead of drawing a zoom rectangle.
	 *
	 * The cursor is set from it, because a gesture that does two different
	 * things has to say which one it is about to do.
	 */
	setDragPans(on) {
		this.dragPans = !!on;
		this.canvas.style.cursor = this.dragPans ? 'grab' : 'crosshair';
	}

	setScales({ xLog, yLog }) {
		if (xLog !== undefined) this.xLog = xLog;
		if (yLog !== undefined) this.yLog = yLog;
		this.draw();
	}

	// --- theme ------------------------------------------------------------
	_colors() {
		const cs = getComputedStyle(this.container);
		const v = (n, fallback) => (cs.getPropertyValue(n).trim() || fallback);
		return {
			surface: v('--surface-1', '#fcfcfb'),
			text: v('--text-primary', '#0b0b0b'),
			muted: v('--text-secondary', '#52514e'),
			faint: v('--text-muted', '#8a8880'),
			grid: v('--grid', 'rgba(0,0,0,0.07)'),
			axis: v('--axis', 'rgba(0,0,0,0.25)'),
			accent: v('--accent', '#2a78d6'),
			// The band's fill: the accent at a fraction of itself, so the
			// chart stays readable under it.
			band: `color-mix(in oklab, ${v('--accent', '#2a78d6')} 16%, transparent)`,
			series: Array.from({ length: SERIES_COLORS }, (_, i) =>
				v(`--series-${i + 1}`, '#2a78d6')),
		};
	}

	// --- scales -----------------------------------------------------------
	/**
	 * The window to draw: the zoom when there is one, the data's own extent
	 * otherwise.
	 *
	 * A zoom that no longer overlaps the data at all -- a re-run whose results
	 * moved somewhere else entirely -- is dropped rather than shown as an
	 * empty chart, because an empty chart looks like a model that produced
	 * nothing.
	 */
	_range() {
		const ext = this._extent();
		const z = this.zoom;
		if (!z) return ext;
		const overlaps = z.xMax > ext.xMin && z.xMin < ext.xMax
			&& z.yMax > ext.yMin && z.yMin < ext.yMax;
		if (!overlaps) { this.zoom = null; return ext; }
		return z;
	}

	/** Whether the chart is showing less than everything. */
	isZoomed() { return !!this.zoom; }

	_extent() {
		const { t, series } = this.data;
		let xMin = Infinity, xMax = -Infinity;
		let yMin = Infinity, yMax = -Infinity;

		for (let i = 0; i < t.length; i++) {
			const x = t[i];
			if (this.xLog && !(x > 0)) continue;
			if (x < xMin) xMin = x;
			if (x > xMax) xMax = x;
		}
		// The band counts as much as the line: a chart scaled to the median of a
		// probabilistic run draws its 95th percentile off the top.
		const reach = (values) => {
			for (let i = 0; i < values.length; i++) {
				const y = values[i];
				if (!Number.isFinite(y)) continue;
				if (this.yLog && !(y > 0)) continue;
				if (y < yMin) yMin = y;
				if (y > yMax) yMax = y;
			}
		};
		for (const s of series) {
			reach(s.values);
			for (const b of s.bands ?? []) { reach(b.lo); reach(b.hi); }
		}

		if (!Number.isFinite(xMin)) { xMin = this.xLog ? 1 : 0; xMax = 1; }
		if (!Number.isFinite(yMin)) { yMin = this.yLog ? 1e-3 : 0; yMax = 1; }
		if (xMin === xMax) { xMax = this.xLog ? xMin * 10 : xMin + 1; }
		if (yMin === yMax) {
			if (this.yLog) { yMin /= 10; yMax *= 10; } else { yMin -= 1; yMax += 1; }
		}

		if (this.yLog) {
			// Clamp the visible range: results often decay towards zero and a
			// full 300-decade axis would be unreadable. Twelve decades below
			// the peak is well past anything meaningful.
			const floor = yMax * 1e-12;
			if (yMin < floor) yMin = floor;
		} else {
			const pad = (yMax - yMin) * 0.05;
			yMax += pad;
			if (yMin > 0 && yMin - pad < 0) yMin = 0; else yMin -= pad;
		}
		return { xMin, xMax, yMin, yMax };
	}

	// --- drawing ----------------------------------------------------------
	draw() {
		const dpr = window.devicePixelRatio || 1;
		const w = Math.max(1, this.container.clientWidth);
		const h = Math.max(1, this.container.clientHeight);
		if (this.canvas.width !== Math.round(w * dpr)
			|| this.canvas.height !== Math.round(h * dpr)) {
			this.canvas.width = Math.round(w * dpr);
			this.canvas.height = Math.round(h * dpr);
		}
		this.canvas.style.width = `${w}px`;
		this.canvas.style.height = `${h}px`;

		const ctx = this.ctx;
		ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
		ctx.clearRect(0, 0, w, h);
		this._paint(ctx, w, h);
		// The rubber band is the gesture, not the chart: it is drawn after
		// the chart and never into a picture.
		if (this.drag?.moved && !this.drag.pan) this._drawBand(ctx);
	}

	/** The rectangle being dragged out, over the chart it will become. */
	_drawBand(ctx) {
		const d = this.drag;
		const c = this._colors();
		const x = Math.min(d.x0, d.x1);
		const y = Math.min(d.y0, d.y1);
		const w = Math.abs(d.x1 - d.x0);
		const h = Math.abs(d.y1 - d.y0);
		// One axis at a time when the drag is only along one: the band shows
		// what the release will actually do.
		const full = { x: this.plot.x, y: this.plot.y, w: this.plot.w, h: this.plot.h };
		const box = {
			x: w >= ZOOM_SLOP ? x : full.x,
			w: w >= ZOOM_SLOP ? w : full.w,
			y: h >= ZOOM_SLOP ? y : full.y,
			h: h >= ZOOM_SLOP ? h : full.h,
		};
		ctx.save();
		ctx.fillStyle = c.band;
		ctx.fillRect(box.x, box.y, box.w, box.h);
		ctx.strokeStyle = c.accent;
		ctx.lineWidth = 1;
		ctx.setLineDash([4, 3]);
		ctx.strokeRect(Math.round(box.x) + 0.5, Math.round(box.y) + 0.5,
			Math.round(box.w), Math.round(box.h));
		ctx.restore();
	}

	/**
	 * The chart itself, onto anything that behaves like a 2D context.
	 *
	 * Split from `draw` so that a picture of the chart is *this* chart. The
	 * screen gets the canvas; a saved SVG gets `SvgCanvas`, which implements
	 * the same twenty-two members. A second routine that emitted SVG would be
	 * a second chart, and the two would disagree about a tick label or a dash
	 * pattern within a month.
	 *
	 * @param ctx a canvas 2D context, or anything shaped like one
	 * @param {number} w the width to draw in, in device-independent pixels
	 * @param {number} h the height of the *chart*; a legend band, when one is
	 *   asked for, is drawn below it and the surface has to be that much taller
	 * @param {{hover?: boolean, legend?: boolean, stash?: boolean}} [opts]
	 *   `hover` draws the crosshair, which belongs on screen and not in a
	 *   picture; `legend` draws the band; `stash` remembers the geometry for
	 *   the pointer to read, which only the on-screen pass should do.
	 */
	_paint(ctx, w, h, { hover = true, legend = false, stash = true } = {}) {
		const c = this._colors();
		const { series } = this.data;
		// Room on the right for direct labels when there are few series.
		const labelling = series.length > 0 && series.length <= DIRECT_LABELS_UP_TO;
		const pad = {
			l: 62, r: labelling ? 96 : 16, t: 14, b: 38,
		};
		const plot = {
			x: pad.l, y: pad.t,
			w: Math.max(10, w - pad.l - pad.r),
			h: Math.max(10, h - pad.t - pad.b),
		};
		if (stash) this.plot = plot;

		const ext = this._range();
		if (stash) this.ext = ext;

		const sx = (x) => {
			if (this.xLog) {
				const a = Math.log10(ext.xMin), b = Math.log10(ext.xMax);
				return plot.x + ((Math.log10(x) - a) / (b - a)) * plot.w;
			}
			return plot.x + ((x - ext.xMin) / (ext.xMax - ext.xMin)) * plot.w;
		};
		const sy = (y) => {
			if (this.yLog) {
				const a = Math.log10(ext.yMin), b = Math.log10(ext.yMax);
				return plot.y + plot.h - ((Math.log10(y) - a) / (b - a)) * plot.h;
			}
			return plot.y + plot.h - ((y - ext.yMin) / (ext.yMax - ext.yMin)) * plot.h;
		};
		// The way back, for a gesture: a drag and a wheel arrive in pixels and
		// have to become times and values.
		const ix = (px) => {
			const f = (px - plot.x) / plot.w;
			if (this.xLog) {
				const a = Math.log10(ext.xMin);
				const b = Math.log10(ext.xMax);
				return 10 ** (a + f * (b - a));
			}
			return ext.xMin + f * (ext.xMax - ext.xMin);
		};
		const iy = (py) => {
			const f = (plot.y + plot.h - py) / plot.h;
			if (this.yLog) {
				const a = Math.log10(ext.yMin);
				const b = Math.log10(ext.yMax);
				return 10 ** (a + f * (b - a));
			}
			return ext.yMin + f * (ext.yMax - ext.yMin);
		};
		if (stash) { this.sx = sx; this.sy = sy; this.ix = ix; this.iy = iy; }

		// --- grid (recessive) ---
		const xTicks = this.xLog ? logTicks(ext.xMin, ext.xMax) : linTicks(ext.xMin, ext.xMax);
		const yTicks = this.yLog ? logTicks(ext.yMin, ext.yMax) : linTicks(ext.yMin, ext.yMax);

		ctx.lineWidth = 1;
		ctx.strokeStyle = c.grid;
		ctx.beginPath();
		for (const tk of xTicks) {
			const px = Math.round(sx(tk)) + 0.5;
			if (px < plot.x - 1 || px > plot.x + plot.w + 1) continue;
			ctx.moveTo(px, plot.y);
			ctx.lineTo(px, plot.y + plot.h);
		}
		for (const tk of yTicks) {
			const py = Math.round(sy(tk)) + 0.5;
			if (py < plot.y - 1 || py > plot.y + plot.h + 1) continue;
			ctx.moveTo(plot.x, py);
			ctx.lineTo(plot.x + plot.w, py);
		}
		ctx.stroke();

		// --- axes ---
		ctx.strokeStyle = c.axis;
		ctx.beginPath();
		ctx.moveTo(plot.x + 0.5, plot.y);
		ctx.lineTo(plot.x + 0.5, plot.y + plot.h + 0.5);
		ctx.lineTo(plot.x + plot.w, plot.y + plot.h + 0.5);
		ctx.stroke();

		// --- tick labels (text tokens, never series colour) ---
		ctx.font = AXIS_FONT;
		ctx.fillStyle = c.muted;
		ctx.textAlign = 'center';
		ctx.textBaseline = 'top';
		let lastRight = -Infinity;
		for (const tk of xTicks) {
			const px = sx(tk);
			if (px < plot.x - 1 || px > plot.x + plot.w + 1) continue;
			const label = fmtTick(tk, this.xLog);
			const half = ctx.measureText(label).width / 2;
			if (px - half < lastRight + 6) continue; // avoid collisions
			lastRight = px + half;
			ctx.fillText(label, px, plot.y + plot.h + 7);
		}
		ctx.textAlign = 'right';
		ctx.textBaseline = 'middle';
		let lastTop = Infinity;
		for (const tk of yTicks) {
			const py = sy(tk);
			if (py < plot.y - 1 || py > plot.y + plot.h + 1) continue;
			if (lastTop - py < 14 && lastTop !== Infinity) continue;
			lastTop = py;
			ctx.fillText(fmtTick(tk, this.yLog), plot.x - 8, py);
		}

		// --- axis titles ---
		ctx.fillStyle = c.faint;
		ctx.textAlign = 'center';
		ctx.textBaseline = 'bottom';
		ctx.fillText(this.xLabel, plot.x + plot.w / 2, h - 2);
		if (this.yLabel) {
			ctx.save();
			ctx.translate(11, plot.y + plot.h / 2);
			ctx.rotate(-Math.PI / 2);
			ctx.textBaseline = 'top';
			ctx.fillText(this.yLabel, 0, 0);
			ctx.restore();
		}

		// --- bands, under the lines --------------------------------------
		// A probabilistic run is a spread, not a curve: the line is its median
		// and the band is where the realisations were. Drawn first so every
		// line sits on top of every band -- otherwise a wide band from one
		// series hides the median of the next -- and in the series' own colour,
		// so which spread belongs to which line needs no explaining.
		{
			const { t: tb } = this.data;
			series.forEach((s, si) => {
				if (!s.bands?.length) return;
				const { color } = styleOf(s, si);
				ctx.fillStyle = c.series[color];
				for (const band of s.bands) {
					ctx.globalAlpha = band.alpha ?? 0.16;
					ctx.beginPath();
					let open = false;
					// Up the low edge and back down the high one, breaking
					// wherever either end is a value the scale cannot show.
					for (let i = 0; i < tb.length; i++) {
						const x = tb[i];
						const lo = band.lo[i];
						const hi = band.hi[i];
						const okX = this.xLog ? x > 0 : Number.isFinite(x);
						const ok = okX && Number.isFinite(lo) && Number.isFinite(hi)
							&& (!this.yLog || (lo > 0 && hi > 0));
						if (!ok) { open = false; continue; }
						if (!open) {
							// A run of good points starts here: draw its lower
							// edge forward, then its upper edge back.
							let j = i;
							while (j < tb.length) {
								const xj = tb[j];
								const lj = band.lo[j];
								const hj = band.hi[j];
								const okj = (this.xLog ? xj > 0 : Number.isFinite(xj))
									&& Number.isFinite(lj) && Number.isFinite(hj)
									&& (!this.yLog || (lj > 0 && hj > 0));
								if (!okj) break;
								if (j === i) ctx.moveTo(sx(xj), sy(lj));
								else ctx.lineTo(sx(xj), sy(lj));
								j++;
							}
							for (let k = j - 1; k >= i; k--) ctx.lineTo(sx(tb[k]), sy(band.hi[k]));
							ctx.closePath();
							i = j - 1;
							open = false;
						}
					}
					ctx.fill();
				}
			});
			ctx.globalAlpha = 1;
		}

		// --- series: 2px lines, breaking across values the scale can't show ---
		const { t } = this.data;
		ctx.lineWidth = 2;
		ctx.lineJoin = 'round';
		series.forEach((s, si) => {
			const { color, dash } = styleOf(s, si);
			ctx.strokeStyle = c.series[color];
			ctx.setLineDash(dash);
			// A round cap adds half a line width at each end of every dash,
			// which closes the gaps of the tightest pattern and turns a dotted
			// line back into a solid one.
			ctx.lineCap = dash.length ? 'butt' : 'round';
			ctx.beginPath();
			// Clipped segment by segment against the plot rather than by a
			// canvas clip: a zoomed chart has lines running well outside the
			// axes, and the surface a picture is drawn on has no `clip` --
			// while both of them can draw the piece that is inside. Cutting
			// at the boundary rather than dropping the point keeps a line
			// touching the edge it leaves through, which a chart zoomed to
			// ten samples would otherwise show as a gap.
			let prev = null;
			let pen = null;
			for (let i = 0; i < t.length; i++) {
				const x = t[i], y = s.values[i];
				const okX = this.xLog ? x > 0 : Number.isFinite(x);
				// A log axis cannot show zero or less; anything else outside
				// the window is clipped rather than skipped.
				const okY = Number.isFinite(y) && (this.yLog ? y > 0 : true);
				if (!okX || !okY) { prev = null; pen = null; continue; }
				const cur = { x: sx(x), y: sy(y) };
				if (prev) {
					const seg = clipSegment(prev, cur, plot);
					if (seg) {
						if (!pen || Math.abs(pen.x - seg.a.x) > 0.01
							|| Math.abs(pen.y - seg.a.y) > 0.01) {
							ctx.moveTo(seg.a.x, seg.a.y);
						}
						ctx.lineTo(seg.b.x, seg.b.y);
						pen = seg.b;
					} else {
						pen = null;
					}
				}
				prev = cur;
			}
			// A single point is a line of no length, which a butt cap draws
			// as nothing at all: give it a dot so a one-sample series is
			// visible rather than absent.
			if (t.length === 1 && prev && inPlot(prev, plot)) {
				ctx.moveTo(prev.x, prev.y);
				ctx.lineTo(prev.x, prev.y);
			}
			ctx.stroke();
		});
		// Left set, the crosshair and the labels below would inherit it.
		ctx.setLineDash([]);
		ctx.lineCap = 'round';

		// --- direct labels for up to four series ---
		if (labelling) {
			ctx.font = LABEL_FONT;
			ctx.textAlign = 'left';
			ctx.textBaseline = 'middle';
			// Where each line ends, as far as this window is concerned.
			const wanted = [];
			series.forEach((s, si) => {
				let idx = -1;
				for (let i = t.length - 1; i >= 0; i--) {
					const y = s.values[i];
					if (!Number.isFinite(y)) continue;
					if (this.yLog && !(y > 0)) continue;
					// Inside the window, not merely inside the data: a zoomed
					// chart labelling a line at a value it is not showing
					// would put the name against the wrong height.
					if (y < ext.yMin || y > ext.yMax) continue;
					const x = t[i];
					if (x < ext.xMin || x > ext.xMax) continue;
					idx = i;
					break;
				}
				if (idx < 0) return;
				wanted.push({ si, label: s.label, at: sy(s.values[idx]) });
			});
			// Spread apart *after* clamping, not before. Nudging first and
			// clamping second let two labels land on the same pixel -- which
			// is what a zoomed chart produces every time, since every line
			// leaving through the top of the window wants the same height.
			for (const p of spreadLabels(wanted, plot, LABEL_GAP)) {
				const { color, dash } = styleOf(series[p.si], p.si);
				ctx.strokeStyle = c.series[color];
				ctx.setLineDash(dash);
				ctx.lineCap = dash.length ? 'butt' : 'round';
				ctx.lineWidth = 2;
				ctx.beginPath();
				ctx.moveTo(plot.x + plot.w + 4, p.y);
				ctx.lineTo(plot.x + plot.w + 18, p.y);
				ctx.stroke();
				ctx.setLineDash([]);
				ctx.fillStyle = c.muted;
				ctx.fillText(truncate(ctx, p.label, pad.r - 30),
					plot.x + plot.w + 24, p.y);
			}
		}

		// --- the legend, in a picture that needs one ---
		// On screen the legend is HTML beside the chart; in a picture there is
		// no beside. Without it a chart of more than four series is lines
		// nobody can name -- which is the one thing a chart must not be.
		if (legend) this._paintLegend(ctx, w, h, c);

		// --- crosshair ---
		// Never in a picture: it says where the pointer was.
		if (hover && this.hover != null) this._drawHover(c, ctx);
	}

	/**
	 * How much room a legend band needs, and how it is laid out.
	 *
	 * Columns as wide as a label needs and as many as the width allows, which
	 * is the same arithmetic the band is drawn with -- the caller sizes the
	 * picture from this before anything is drawn.
	 */
	_legendBand(w) {
		const n = this.data.series.length;
		if (!n) return { rows: 0, cols: 0, col: 0, height: 0 };
		const cols = Math.max(1, Math.min(n, Math.floor((w - LEGEND_PAD * 2) / LEGEND_COL)));
		const rows = Math.ceil(n / cols);
		return {
			rows,
			cols,
			col: Math.floor((w - LEGEND_PAD * 2) / cols),
			height: rows * LEGEND_ROW + LEGEND_PAD,
		};
	}

	_paintLegend(ctx, w, h, c) {
		const { series } = this.data;
		const band = this._legendBand(w);
		if (!band.rows) return;
		ctx.font = AXIS_FONT;
		ctx.textAlign = 'left';
		ctx.textBaseline = 'middle';
		series.forEach((s, si) => {
			const row = Math.floor(si / band.cols);
			const col = si % band.cols;
			const x = LEGEND_PAD + col * band.col;
			const y = h + LEGEND_PAD * 0.5 + row * LEGEND_ROW + LEGEND_ROW / 2;
			const { color, dash } = styleOf(s, si);
			ctx.strokeStyle = c.series[color];
			ctx.setLineDash(dash);
			ctx.lineCap = dash.length ? 'butt' : 'round';
			ctx.lineWidth = 2;
			ctx.beginPath();
			ctx.moveTo(x, y);
			ctx.lineTo(x + 18, y);
			ctx.stroke();
			ctx.setLineDash([]);
			// The label in a text colour, never the series colour: the line
			// beside it is what carries the identity.
			ctx.fillStyle = c.muted;
			ctx.fillText(truncate(ctx, s.label, band.col - 30), x + 24, y);
		});
	}

	/**
	 * Writes the chart out as a picture.
	 *
	 * Two routes, and both draw the chart again rather than copy the pixels on
	 * screen. PNG and JPEG go onto a canvas at twice the size, because a
	 * bitmap scaled up is a bitmap scaled up and a chart in a report is read
	 * at print resolution. SVG goes through `SvgCanvas`, which is worth having
	 * for a chart in a way it is not for a screenshot: the lines stay lines,
	 * so the figure can be zoomed, re-lettered, or dropped into a document at
	 * whatever size the page wants.
	 *
	 * What is in the picture and not on screen is the legend, when the chart
	 * has more series than it draws direct labels for. On screen that legend
	 * is HTML beside the canvas; a picture has no beside.
	 *
	 * What is on screen and not in the picture is the crosshair.
	 *
	 * @param {'svg'|'png'|'jpeg'} kind
	 * @param {{name?: string, scale?: number}} [opts]
	 * @returns {Promise<{file: string, width: number, height: number}>}
	 */
	async savePicture(kind, { name = '', scale = 2 } = {}) {
		const spec = PICTURE_KINDS[kind];
		if (!spec) throw new Error(`'${kind}' is not a picture format`);
		if (!this.data.series.length) {
			throw new Error('There is nothing on the chart to make a picture of.');
		}
		const w = Math.max(1, this.container.clientWidth);
		const h = Math.max(1, this.container.clientHeight);
		// The band only where the chart is not already labelling its own
		// lines: four series or fewer say who they are at their right-hand end.
		const wants = this.data.series.length > DIRECT_LABELS_UP_TO;
		const band = wants ? this._legendBand(w).height : 0;
		const c = this._colors();
		// The ground it is drawn on. A chart is dark lines on a light page or
		// the reverse, and a transparent PNG of the dark one is unreadable
		// wherever it lands.
		const background = c.surface;
		const title = [name, 'chart'].filter(Boolean).join(' — ');
		const file = fileName([name, 'chart'], spec.extension);
		const opts = { hover: false, legend: wants, stash: false };

		if (kind === 'svg') {
			const svg = new SvgCanvas(w, h + band);
			this._paint(svg, w, h, opts);
			saveBlob(file, new Blob([svg.toSVG({ background, title })], { type: spec.mime }));
			return { file, width: w, height: h + band };
		}

		const canvas = document.createElement('canvas');
		canvas.width = Math.round(w * scale);
		canvas.height = Math.round((h + band) * scale);
		const ctx = canvas.getContext('2d');
		ctx.setTransform(scale, 0, 0, scale, 0, 0);
		ctx.fillStyle = background;
		ctx.fillRect(0, 0, w, h + band);
		this._paint(ctx, w, h, opts);
		const blob = await new Promise((ok, no) => canvas.toBlob(
			(b) => (b ? ok(b) : no(new Error('the browser produced no image'))),
			spec.mime,
			kind === 'jpeg' ? 0.92 : undefined,
		));
		saveBlob(file, blob);
		return { file, width: canvas.width, height: canvas.height };
	}

	_drawHover(c, ctx = this.ctx) {
		const { t, series } = this.data;
		const i = this.hover;
		if (i == null || i < 0 || i >= t.length) return;
		const px = this.sx(t[i]);
		if (!Number.isFinite(px)) return;
		// Off the side of a zoomed window: the readout still names the point,
		// but a crosshair drawn outside the axes is a line across the panel.
		if (px < this.plot.x - 0.5 || px > this.plot.x + this.plot.w + 0.5) return;

		ctx.save();
		ctx.setLineDash([3, 3]);
		ctx.lineWidth = 1;
		ctx.strokeStyle = c.axis;
		ctx.beginPath();
		ctx.moveTo(Math.round(px) + 0.5, this.plot.y);
		ctx.lineTo(Math.round(px) + 0.5, this.plot.y + this.plot.h);
		ctx.stroke();
		ctx.restore();

		// A ring in the surface colour keeps overlapping markers readable.
		series.forEach((s, si) => {
			const y = s.values[i];
			if (!Number.isFinite(y)) return;
			if (this.yLog && !(y > 0)) return;
			if (y < this.ext.yMin || y > this.ext.yMax) return;
			const py = this.sy(y);
			ctx.beginPath();
			ctx.arc(px, py, 4.5, 0, Math.PI * 2);
			ctx.fillStyle = c.series[styleOf(series[si], si).color];
			ctx.fill();
			ctx.lineWidth = 2;
			ctx.strokeStyle = c.surface;
			ctx.stroke();
		});
	}

	// --- zoom --------------------------------------------------------------
	/**
	 * Zooming, the two ways a chart is zoomed.
	 *
	 * Dragging a rectangle over the part you want is the conventional gesture,
	 * which is what Ecolego's charts do, and it is still the quickest way to
	 * say "that peak, at that scale". The wheel is the other habit, and this
	 * application already zooms its diagram that way.
	 *
	 * Both work in *scale space* -- the logarithm of the value on a log axis,
	 * the value itself on a linear one -- because that is the space the axis is
	 * even in. Zooming a log axis by halving its numbers would take four
	 * decades to two and a half and look like nothing had been done to the
	 * bottom of it.
	 */
	_scaleOf(axis) {
		const log = axis === 'x' ? this.xLog : this.yLog;
		return log
			? { to: (v) => Math.log10(v), from: (u) => 10 ** u }
			: { to: (v) => v, from: (u) => u };
	}

	/** The window, with anything a scale cannot show refused. */
	_setZoom(next) {
		const ext = this._extent();
		const ok = (min, max, log) => Number.isFinite(min) && Number.isFinite(max)
			&& max > min && (!log || min > 0);
		if (!ok(next.xMin, next.xMax, this.xLog)) return false;
		if (!ok(next.yMin, next.yMax, this.yLog)) return false;
		// A window wider than the data is the data: there is nothing out
		// there to see, and a chart of mostly empty axes reads as a chart of
		// nothing.
		const wide = next.xMin <= ext.xMin && next.xMax >= ext.xMax
			&& next.yMin <= ext.yMin && next.yMax >= ext.yMax;
		this.zoom = wide ? null : next;
		this.draw();
		return true;
	}

	/**
	 * Zooms about a point, which defaults to the middle of the window.
	 *
	 * `factor` above 1 zooms in. Keeping the point under the pointer fixed is
	 * what makes a wheel zoom feel like moving a lens rather than resizing a
	 * box.
	 */
	zoomBy(factor, at = null) {
		if (!this.plot || !this.ix) return;
		const ext = this.zoom ?? this._extent();
		const k = 1 / Math.max(0.05, Math.min(20, factor));
		const out = {};
		for (const axis of ['x', 'y']) {
			const scale = this._scaleOf(axis);
			const min = scale.to(axis === 'x' ? ext.xMin : ext.yMin);
			const max = scale.to(axis === 'x' ? ext.xMax : ext.yMax);
			const focus = at != null
				? scale.to(axis === 'x' ? at.x : at.y)
				: (min + max) / 2;
			const p = Number.isFinite(focus) ? focus : (min + max) / 2;
			out[`${axis}Min`] = scale.from(p + (min - p) * k);
			out[`${axis}Max`] = scale.from(p + (max - p) * k);
		}
		this._setZoom(out);
	}

	/** Zooms to a rectangle in the canvas's own pixels. */
	zoomToRect(rect) {
		if (!this.ix || !this.iy) return false;
		const x0 = Math.min(rect.x0, rect.x1);
		const x1 = Math.max(rect.x0, rect.x1);
		const y0 = Math.min(rect.y0, rect.y1);
		const y1 = Math.max(rect.y0, rect.y1);
		return this._setZoom({
			xMin: this.ix(x0),
			xMax: this.ix(x1),
			// Screen y runs downwards, so the top of the rectangle is the
			// larger value.
			yMin: this.iy(y1),
			yMax: this.iy(y0),
		});
	}

	/** Back to the whole of the data. */
	resetZoom() {
		if (!this.zoom) return;
		this.zoom = null;
		this.draw();
	}

	/** Moves the window without changing its size. */
	panBy(dx, dy) {
		if (!this.plot) return;
		// From the window if there is one, and from the whole extent if there
		// is not: refusing to pan an unzoomed chart made the gesture look
		// broken rather than unnecessary, and moving a peak off the edge to
		// see the shoulder of it is a reasonable thing to ask for.
		const ext = this.zoom ?? this._extent();
		const out = {};
		for (const [axis, d, span] of [
			['x', -dx, this.plot.w],
			['y', dy, this.plot.h],
		]) {
			const scale = this._scaleOf(axis);
			const min = scale.to(axis === 'x' ? ext.xMin : ext.yMin);
			const max = scale.to(axis === 'x' ? ext.xMax : ext.yMax);
			const step = ((max - min) * d) / Math.max(1, span);
			out[`${axis}Min`] = scale.from(min + step);
			out[`${axis}Max`] = scale.from(max + step);
		}
		// Panning off the end of the data is allowed -- it is how you look at
		// the edge of a peak -- so this does not go through the "wider than
		// the data" test that would drop the window entirely.
		if (Number.isFinite(out.xMin) && out.xMax > out.xMin
			&& Number.isFinite(out.yMin) && out.yMax > out.yMin) {
			this.zoom = out;
			this.draw();
		}
	}

	/** Where a pointer is, in the canvas's own pixels. */
	_at(ev) {
		const r = this.canvas.getBoundingClientRect();
		return { x: ev.clientX - r.left, y: ev.clientY - r.top };
	}

	_onDown(ev) {
		// The middle button pans, as it does in every other plot.
		const middle = ev.button === 1;
		if (ev.button !== 0 && !middle) return;
		if (middle) ev.preventDefault();
		const p = this._at(ev);
		// Only over the plot: the margins hold the axis labels, and a drag
		// beginning on one of those is a text selection anywhere else.
		if (!this.plot || !inPlot(p, this.plot)) { this._onMove(ev); return; }
		// The modifier does the opposite of whatever a plain drag does, the
		// way Alt inverts snapping on the diagram.
		// Coerced, because this is compared with `!==` against a boolean: an
		// event whose modifier fields are absent rather than false would
		// otherwise read as "the other gesture".
		const other = !!(ev.shiftKey || ev.altKey || ev.metaKey);
		this.drag = {
			x0: p.x, y0: p.y, x1: p.x, y1: p.y,
			pan: middle || this.dragPans !== other,
			moved: false,
		};
		this.canvas.setPointerCapture?.(ev.pointerId);
		// The readout would follow the pointer through the gesture and get in
		// the way of the rectangle.
		this.tooltip.hidden = true;
		this._onMove(ev);
	}

	_onUp(ev) {
		const d = this.drag;
		this.drag = null;
		if (!d) return;
		this.canvas.releasePointerCapture?.(ev.pointerId);
		this.canvas.style.cursor = this.dragPans ? 'grab' : 'crosshair';
		if (!d.moved || d.pan) { this.draw(); return; }
		const wide = Math.abs(d.x1 - d.x0) >= ZOOM_SLOP;
		const tall = Math.abs(d.y1 - d.y0) >= ZOOM_SLOP;
		// A rectangle in one direction only is a request to zoom that axis --
		// which is what a chart is usually asked for: this decade of time, at
		// whatever the values do.
		if (!wide && !tall) { this.draw(); return; }
		const box = {
			x0: wide ? d.x0 : this.plot.x,
			x1: wide ? d.x1 : this.plot.x + this.plot.w,
			y0: tall ? d.y0 : this.plot.y,
			y1: tall ? d.y1 : this.plot.y + this.plot.h,
		};
		this.zoomToRect(box);
	}

	_onDblClick() { this.resetZoom(); }

	_onWheel(ev) {
		if (!this.plot) return;
		const p = this._at(ev);
		if (!inPlot(p, this.plot)) return;
		ev.preventDefault();
		const px = wheelPixels(ev.deltaY, ev.deltaMode, this.plot.h);
		if (!px) return;
		// The same feel as the diagram: a mouse notch is a few per cent, a
		// trackpad is smooth, and up is in.
		this.zoomBy(Math.exp(-px / 240), { x: this.ix(p.x), y: this.iy(p.y) });
	}

	_nearestIndex(clientX) {
		const rect = this.canvas.getBoundingClientRect();
		const x = clientX - rect.left;
		const { t } = this.data;
		if (!t.length || !this.sx) return null;
		let best = 0, bestD = Infinity;
		for (let i = 0; i < t.length; i++) {
			if (this.xLog && !(t[i] > 0)) continue;
			const d = Math.abs(this.sx(t[i]) - x);
			if (d < bestD) { bestD = d; best = i; }
		}
		return bestD < Infinity ? best : null;
	}

	_onMove(ev) {
		if (this.drag) {
			const p = this._at(ev);
			this.drag.x1 = p.x;
			this.drag.y1 = p.y;
			if (Math.abs(p.x - this.drag.x0) > 2 || Math.abs(p.y - this.drag.y0) > 2) {
				this.drag.moved = true;
			}
			if (this.drag.pan) {
				this.canvas.style.cursor = 'grabbing';
				const dx = p.x - this.drag.x0;
				const dy = p.y - this.drag.y0;
				this.drag.x0 = p.x;
				this.drag.y0 = p.y;
				this.panBy(dx, dy);
				return;
			}
			this._scheduleDraw();
			return;
		}
		const i = this._nearestIndex(ev.clientX);
		if (i === this.hover) { this._positionTooltip(ev); return; }
		this.hover = i;
		this._scheduleDraw();
		this._showTooltip(ev);
	}

	_onLeave() {
		// Not while a rectangle is being dragged out: the pointer is captured,
		// and dropping the gesture because it crossed the axis would be the
		// zoom refusing exactly the drag that reaches the edge of the plot.
		if (this.drag) return;
		this.hover = null;
		this.tooltip.hidden = true;
		this._scheduleDraw();
	}

	/**
	 * The readout at the crosshair.
	 *
	 * Every series, while every series fits. Thirty-two rows would be taller
	 * than most charts, so past a dozen it shows the largest values at this
	 * time point -- which is the question a crosshair is usually asking, "what
	 * is on top here" -- and says how many it left out. Only then: while it
	 * fits, the order is the legend's, because two lists of the same lines in
	 * different orders is a thing to have to reconcile.
	 */
	_showTooltip(ev) {
		const { t, series } = this.data;
		const i = this.hover;
		if (i == null || !series.length) { this.tooltip.hidden = true; return; }
		const c = this._colors();
		let shown = series.map((s, si) => ({ s, si }));
		let hidden = 0;
		if (shown.length > TOOLTIP_ROWS) {
			const rank = (x) => {
				const v = x.s.values[i];
				return Number.isFinite(v) ? v : -Infinity;
			};
			shown = shown.slice().sort((a, b) => rank(b) - rank(a));
			hidden = shown.length - TOOLTIP_ROWS;
			shown = shown.slice(0, TOOLTIP_ROWS);
		}
		// Elements, never markup: the series labels and the axis label come out
		// of the model file, and text nodes cannot be mistaken for tags. The
		// rest of the UI is built the same way, so this is also the one place
		// that used to need an escaper of its own.
		const rows = shown.map(({ s, si }) => {
			const v = s.values[i];
			const { color, set } = styleOf(s, si);
			const swatch = el('span', { className: 'series-swatch tt-swatch' });
			swatch.dataset.set = set;
			swatch.style.setProperty('--swatch', c.series[color]);
			return el('div', { className: 'tt-row' },
				swatch,
				el('span', { className: 'tt-name' }, s.label),
				el('span', { className: 'tt-val' }, fmtValue(v)));
		});
		this.tooltip.replaceChildren(
			el('div', { className: 'tt-head' }, `${this.xLabel} = ${fmtValue(t[i])}`),
			...rows,
			...(hidden ? [el('div', { className: 'tt-more' }, `${hidden} more, smaller at this time`)] : []),
		);
		this.tooltip.hidden = false;
		this._positionTooltip(ev);
	}

	_positionTooltip(ev) {
		if (this.tooltip.hidden) return;
		const rect = this.container.getBoundingClientRect();
		const tw = this.tooltip.offsetWidth;
		const th = this.tooltip.offsetHeight;
		let x = ev.clientX - rect.left + 14;
		let y = ev.clientY - rect.top + 14;
		if (x + tw > rect.width - 4) x = ev.clientX - rect.left - tw - 14;
		if (y + th > rect.height - 4) y = Math.max(4, rect.height - th - 4);
		this.tooltip.style.left = `${Math.max(4, x)}px`;
		this.tooltip.style.top = `${Math.max(4, y)}px`;
	}
}

// --- tick helpers ---------------------------------------------------------

function logTicks(min, max) {
	const lo = Math.floor(Math.log10(min));
	const hi = Math.ceil(Math.log10(max));
	const decades = hi - lo;
	const out = [];
	// How much of a decade is actually on screen, rather than how many
	// decade boundaries it straddles: a window from 4e5 to 1.2e6 crosses two
	// boundaries and is half a decade wide, and reading it the first way gave
	// a zoomed axis one tick label to be read against.
	const span = Math.log10(max / min);
	// With few decades on screen, add minors for readability -- every integer
	// inside a decade, then the 2/5 pair, then the decades alone.
	const minors = span <= 1.2 ? [1, 2, 3, 4, 5, 6, 7, 8, 9]
		: decades <= 4 ? [1, 2, 5] : decades <= 12 ? [1] : null;
	if (minors) {
		for (let e = lo; e <= hi; e++) {
			for (const m of minors) {
				const v = m * Math.pow(10, e);
				if (v >= min * 0.999 && v <= max * 1.001) out.push(v);
			}
		}
	} else {
		const step = Math.ceil(decades / 12);
		for (let e = lo; e <= hi; e += step) {
			const v = Math.pow(10, e);
			if (v >= min * 0.999 && v <= max * 1.001) out.push(v);
		}
	}
	return out;
}

function linTicks(min, max, target = 8) {
	const span = max - min;
	if (!(span > 0)) return [min];
	const raw = span / target;
	const mag = Math.pow(10, Math.floor(Math.log10(raw)));
	const norm = raw / mag;
	const step = (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10) * mag;
	const first = Math.ceil(min / step) * step;
	const out = [];
	for (let v = first; v <= max * (1 + 1e-12); v += step) {
		out.push(Math.abs(v) < step * 1e-9 ? 0 : v);
	}
	return out;
}

function fmtTick(v, isLog) {
	if (v === 0) return '0';
	const a = Math.abs(v);
	if (isLog) {
		const e = Math.log10(a);
		if (Number.isInteger(e)) {
			// Plain digits up to 1000, exponent notation above, so a decade
			// axis does not mix "10000" with "1e5".
			if (e >= -3 && e <= 3) return trimNum(a);
			return `1e${e}`;
		}
		return a >= 0.001 && a < 1e4 ? trimNum(a) : a.toExponential(0);
	}
	if (a >= 1e5 || (a < 1e-3 && a > 0)) return v.toExponential(1);
	return trimNum(v);
}

function trimNum(v) {
	const s = v.toPrecision(6);
	return String(Number(s));
}

export function fmtValue(v) {
	if (v == null || Number.isNaN(v)) return '--';
	if (v === 0) return '0';
	if (!Number.isFinite(v)) return v > 0 ? '∞' : '-∞';
	const a = Math.abs(v);
	if (a >= 1e5 || a < 1e-3) return v.toExponential(3);
	return String(Number(v.toPrecision(5)));
}

function truncate(ctx, text, maxWidth) {
	if (ctx.measureText(text).width <= maxWidth) return text;
	let s = text;
	while (s.length > 1 && ctx.measureText(`${s}…`).width > maxWidth) {
		s = s.slice(0, -1);
	}
	return `${s}…`;
}

