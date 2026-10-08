/**
 * Several time charts stacked over one time axis.
 *
 * Two blocks charted together are often two different quantities -- a release
 * in Bq/year and an inventory in Bq -- and one axis for both is an axis that
 * is right for neither. And a block over nuclides and landscape objects is a
 * chart per object before it is anything else. So the Chart tab draws panels:
 * one chart each, stacked, sharing the time axis, which is lettered under the
 * last of them only.
 *
 * Each panel is an ordinary `TimeChart`, so everything one chart does -- zoom,
 * pan, the readout, the labels at the ends of lines -- each panel does. What
 * this adds is the axis they share: zooming or panning one moves the time
 * window of all of them and leaves each one's values alone, which is how
 * linked panels behave in every plotting tool that has them.
 *
 * A picture of the stack is one picture: every panel drawn by its own code,
 * one under the other, at the sizes they have on screen, with the legend the
 * page shows under them -- the chart in a report is the chart on the screen.
 */

import { TimeChart, lineLook } from './chart.js';
import { SvgCanvas } from './svgcanvas.js';
import { PICTURE_KINDS, fileName, saveBlob } from './picture.js';
import { el } from './parts.js';

/** The legend band of a picture: a column a label, rows as they wrap. */
const LEGEND_COL = 180;
const LEGEND_ROW = 16;
const LEGEND_PAD = 16;

export class ChartStack {
	/**
	 * @param {HTMLElement} host  what the panels are put in
	 */
	constructor(host) {
		this.host = host;
		this.host.classList.add('chart-stack');
		/** The panels, in order: `{ key, node, chart }`. */
		this.panels = [];
		this.xLog = true;
		this.yLog = true;
		/** The prefixes the axes are lettered in, as powers of ten. */
		this.xExp = 0;
		this.yExp = 0;
		this.fixed = null;
		this.dragPans = false;
		/** Told `(panel index, window)` whenever a gesture moves a window. */
		this.onWindow = null;
	}

	/**
	 * What to draw, a panel at a time.
	 *
	 * A panel that keeps its `key` keeps its chart, and with it the window it
	 * was zoomed to, so a re-run or a line added to one panel does not throw
	 * away where the reader was looking. A panel that is new starts at the
	 * time window the others are at.
	 *
	 * @param {Float64Array} t
	 * @param {Array<{key: string, title?: string, series: object[], yLabel?: string}>} panels
	 * @param {{xLabel?: string}} [opts]
	 */
	setPanels(t, panels, { xLabel } = {}) {
		const old = new Map(this.panels.map((p) => [p.key, p]));
		const shared = this.panels[0]?.chart.isZoomed() ? this.panels[0].chart.window() : null;
		const next = [];
		panels.forEach((spec, k) => {
			let p = old.get(spec.key);
			if (p) old.delete(spec.key);
			else {
				const node = el('div', { className: 'chart-panel' });
				const chart = new TimeChart(node);
				chart.setDragPans(this.dragPans);
				chart.xLog = this.xLog;
				chart.yLog = this.yLog;
				chart.xExp = this.xExp;
				chart.yExp = this.yExp;
				chart.fixed = this.fixed;
				p = { key: spec.key, node, chart };
			}
			next.push(p);
			p.index = k;
		});
		for (const gone of old.values()) gone.chart.destroy();
		this.panels = next;
		// In order, and only where the order changed: moving a canvas that is
		// already in place throws its drawing away.
		const nodes = next.map((p) => p.node);
		if (nodes.length !== this.host.children.length
			|| nodes.some((n, k) => this.host.children[k] !== n)) {
			this.host.replaceChildren(...nodes);
		}
		this.host.dataset.panels = String(next.length);
		next.forEach((p, k) => {
			const spec = panels[k];
			p.chart.onWindow = (w) => this._moved(k, w);
			p.chart.setData(t, spec.series, {
				xLabel,
				yLabel: spec.yLabel ?? '',
				// A lone chart needs no name over it: the bar above says what
				// is charted. Several do, or they are charts of nothing in
				// particular.
				title: next.length > 1 ? spec.title ?? '' : '',
				axisX: k === next.length - 1,
			});
		});
		if (shared) {
			for (const p of next) {
				if (!p.chart.isZoomed()) p.chart.setXWindow(shared.xMin, shared.xMax);
			}
		}
	}

	/** The single-chart call, for a stack of one. */
	setData(t, series, { xLabel, yLabel } = {}) {
		this.setPanels(t, [{ key: 'only', series, yLabel }], { xLabel });
	}

	/** A gesture in panel `k`: the others take its time window. */
	_moved(k, w) {
		if (this._quiet) return;
		for (const p of this.panels) {
			if (p.index !== k) p.chart.setXWindow(w.xMin, w.xMax);
		}
		this.onWindow?.(k, w);
	}

	setScales({ xLog, yLog }) {
		if (xLog !== undefined) this.xLog = xLog;
		if (yLog !== undefined) this.yLog = yLog;
		for (const p of this.panels) p.chart.setScales({ xLog, yLog });
	}

	/** The prefixes the axes are lettered in, on every panel: `{ x, y }` as powers of ten. */
	setPrefixes({ x, y }) {
		if (x !== undefined) this.xExp = Number(x) || 0;
		if (y !== undefined) this.yExp = Number(y) || 0;
		for (const p of this.panels) p.chart.setPrefixes({ x: this.xExp, y: this.yExp });
	}

	/** The axes' window, the same in every panel; null gives them to the data. */
	setFixed(win) {
		this.fixed = win && Object.keys(win).length ? { ...win } : null;
		for (const p of this.panels) p.chart.setFixed(this.fixed);
	}

	setDragPans(on) {
		this.dragPans = !!on;
		for (const p of this.panels) p.chart.setDragPans(on);
	}

	/**
	 * Zooms every panel about its middle. They share a time window, so the
	 * same factor about the same middle leaves them sharing it -- which is
	 * why the panels are not told about each other's zoom on the way: each
	 * would move the others' time axis a second time.
	 */
	zoomBy(factor) {
		if (!this.panels.length) return;
		this._quiet = true;
		try {
			for (const p of this.panels) p.chart.zoomBy(factor);
		} finally {
			this._quiet = false;
		}
		this.onWindow?.(0, this.window());
	}

	resetZoom() {
		for (const p of this.panels) {
			if (!p.chart.zoom) continue;
			p.chart.zoom = null;
			p.chart.draw();
		}
		this.onWindow?.(0, this.window());
	}

	isZoomed() { return this.panels.some((p) => p.chart.isZoomed()); }

	draw() { for (const p of this.panels) p.chart.draw(); }

	/** The window of the first panel: the time axis is everybody's. */
	window() { return this.panels[0]?.chart.window() ?? null; }

	/**
	 * What each panel has in its window, by panel key: the positions of its
	 * series with something inside it.
	 *
	 * @returns {Map<string, Set<number>>}
	 */
	visibleSeries() {
		return new Map(this.panels.map((p) => [p.key, p.chart.visibleSeries()]));
	}

	/** The colours the first panel draws with, for swatches beside it. */
	colours() { return this.panels[0]?.chart._colors() ?? null; }

	destroy() {
		for (const p of this.panels) p.chart.destroy();
		this.panels = [];
		this.host.replaceChildren();
	}

	/**
	 * Writes the stack out as one picture: the panels one under the other at
	 * their sizes on screen, and under them the legend the page shows --
	 * `legend` is its entries, `{ label, series, si }`, each drawn with the
	 * look its line has.
	 *
	 * @param {'svg'|'png'|'jpeg'} kind
	 * @param {{name?: string, scale?: number, legend?: Array<{label: string, series: object, si: number}>}} [opts]
	 */
	async savePicture(kind, { name = '', scale = 2, legend = [] } = {}) {
		const spec = PICTURE_KINDS[kind];
		if (!spec) throw new Error(`'${kind}' is not a picture format`);
		const panels = this.panels.filter((p) => p.chart.data.series.length);
		if (!panels.length) throw new Error('There is nothing on the chart to make a picture of.');
		if (panels.length === 1 && !legend.length) return panels[0].chart.savePicture(kind, { name, scale });
		const w = Math.max(1, this.host.clientWidth || panels[0].node.clientWidth);
		const heights = panels.map((p) => Math.max(1, p.node.clientHeight));
		const c = panels[0].chart._colors();
		const band = legendBand(legend.length, w);
		const total = heights.reduce((a, b) => a + b, 0) + band.height;
		const background = c.surface;
		const title = [name, 'chart'].filter(Boolean).join(' — ');
		const file = fileName([name, 'chart'], spec.extension);

		const paint = (ctx) => {
			let y = 0;
			panels.forEach((p, k) => {
				ctx.save();
				ctx.translate(0, y);
				p.chart._paint(ctx, w, heights[k], { hover: false, legend: false, stash: false });
				ctx.restore();
				y += heights[k];
			});
			paintLegend(ctx, legend, w, y, c, band);
		};

		if (kind === 'svg') {
			const svg = new SvgCanvas(w, total);
			paint(svg);
			saveBlob(file, new Blob([svg.toSVG({ background, title })], { type: spec.mime }));
			return { file, width: w, height: total };
		}
		const canvas = document.createElement('canvas');
		canvas.width = Math.round(w * scale);
		canvas.height = Math.round(total * scale);
		const ctx = canvas.getContext('2d');
		ctx.setTransform(scale, 0, 0, scale, 0, 0);
		ctx.fillStyle = background;
		ctx.fillRect(0, 0, w, total);
		paint(ctx);
		const blob = await new Promise((ok, no) => canvas.toBlob(
			(b) => (b ? ok(b) : no(new Error('the browser produced no image'))),
			spec.mime,
			kind === 'jpeg' ? 0.92 : undefined,
		));
		saveBlob(file, blob);
		return { file, width: canvas.width, height: canvas.height };
	}
}

/** How a legend of `n` entries is laid out across `w`. */
export function legendBand(n, w) {
	if (!n) return { rows: 0, cols: 0, col: 0, height: 0 };
	const cols = Math.max(1, Math.min(n, Math.floor((w - LEGEND_PAD * 2) / LEGEND_COL)));
	const rows = Math.ceil(n / cols);
	return { rows, cols, col: Math.floor((w - LEGEND_PAD * 2) / cols), height: rows * LEGEND_ROW + LEGEND_PAD };
}

/** The legend under a picture of the stack, from `y` down. */
function paintLegend(ctx, entries, w, y0, c, band) {
	if (!band.rows) return;
	ctx.save();
	ctx.font = c.font ? `11px ${c.font}` : '11px ui-sans-serif, -apple-system, "Segoe UI", system-ui, sans-serif';
	ctx.textAlign = 'left';
	ctx.textBaseline = 'middle';
	entries.forEach((e, k) => {
		const row = Math.floor(k / band.cols);
		const col = k % band.cols;
		const x = LEGEND_PAD + col * band.col;
		const y = y0 + LEGEND_PAD * 0.5 + row * LEGEND_ROW + LEGEND_ROW / 2;
		const look = lineLook(e.series, e.si, c);
		ctx.strokeStyle = look.stroke;
		ctx.setLineDash(look.dash);
		ctx.lineCap = look.dash.length ? 'butt' : 'round';
		ctx.lineWidth = look.width;
		ctx.beginPath();
		ctx.moveTo(x, y);
		ctx.lineTo(x + 18, y);
		ctx.stroke();
		ctx.setLineDash([]);
		ctx.fillStyle = c.muted;
		let text = String(e.label ?? '');
		const room = band.col - 30;
		if (ctx.measureText(text).width > room) {
			while (text.length > 1 && ctx.measureText(`${text}…`).width > room) text = text.slice(0, -1);
			text = `${text}…`;
		}
		ctx.fillText(text, x + 24, y);
	});
	ctx.restore();
}
