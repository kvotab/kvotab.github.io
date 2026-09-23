/* ==========================================================================
   ENSDF.HTML: THE INVENTORY OVER TIME

   The line chart of the Inventory tab: one line for each member of the
   chain, activity, amount, mass or emitted energy against time, on
   logarithmic or linear axes. Pointing at the chart puts a cursor on the
   nearest time and picks out the nearest line; the page is told which, so
   it can pick out the same member in the chain drawing and fill each box to
   its share at that time. A cursor can also be set -- by a click, or by the
   page running through the times -- and stays until it is moved.

   SVG, drawn from the page's theme tokens when it is drawn, so that a saved
   copy carries plain colours.

   One global: KVOT_ENSDF_INVENTORY.
   ========================================================================== */
/* global KVOT_ENSDF_CORE */
(function () {
  'use strict';

  const C = KVOT_ENSDF_CORE;
  const NS = 'http://www.w3.org/2000/svg';

  /*
    Line colours: the eight slots of the validated categorical palette, in
    their order (adjacent pairs clear the colour-vision gates in both themes),
    and past eight the same hues again with a dash, so a line is told apart
    by hue and pattern together. The legend is the members table beside the
    chart, and pointing names a line outright.
  */
  const HUES = {
    light: ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#4a3aa7', '#e34948'],
    dark: ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300', '#9085e9', '#e66767'],
  };
  const DASHES = ['', '6 3', '2 3', '9 3 2 3'];

  /** The colour and dash of line i. */
  function lineStyle(i, theme) {
    const hues = HUES[theme] || HUES.light;
    return { color: hues[i % hues.length], dash: DASHES[Math.floor(i / hues.length) % DASHES.length] };
  }

  function el(tag, attrs, parent) {
    const e = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs || {})) if (v !== undefined && v !== null && v !== '') e.setAttribute(k, v);
    if (parent) parent.appendChild(e);
    return e;
  }

  /* Text with its superscripts raised, as the chain drawing sets them. */
  function richText(textEl, text, size) {
    const rise = Math.round(size * 0.4);
    let up = false;
    for (const r of C.supRuns(text)) {
      const t = el('tspan', {}, textEl);
      if (r.sup) { t.setAttribute('font-size', Math.round(size * 0.72)); t.setAttribute('dy', up ? 0 : -rise); up = true; }
      else if (up) { t.setAttribute('dy', rise); up = false; }
      t.textContent = r.t;
    }
    return textEl;
  }

  /* A number for an axis or a tooltip: 3 significant digits, powers of ten outside 0.01 .. 10 000. */
  function numText(v) {
    if (!Number.isFinite(v)) return '–';
    if (v === 0) return '0';
    const a = Math.abs(v);
    if (a >= 1e4 || a < 1e-2) {
      let e = Math.floor(Math.log10(a));
      let m = +(v / Math.pow(10, e)).toPrecision(3);
      if (Math.abs(m) >= 10) { m = +(m / 10).toPrecision(3); e += 1; }
      return `${m === 1 ? '' : `${m}×`}10${C.sup(String(e).replace('-', '−'))}`;
    }
    return String(+v.toPrecision(3));
  }

  /* Ticks for a log axis, a decade apart (or several, when there are many). */
  function logTicks(lo, hi) {
    const a = Math.floor(Math.log10(lo)), b = Math.ceil(Math.log10(hi));
    const step = Math.max(1, Math.ceil((b - a) / 7));
    const out = [];
    for (let e = Math.ceil(a / step) * step; e <= b; e += step) { const v = Math.pow(10, e); if (v >= lo * 0.999 && v <= hi * 1.001) out.push(v); }
    return out;
  }

  /* Ticks for a linear axis, at 1, 2 or 5 times a power of ten. */
  function linTicks(lo, hi) {
    const span = hi - lo || 1;
    const raw = span / 5;
    const p = Math.pow(10, Math.floor(Math.log10(raw)));
    const step = [1, 2, 5, 10].map((m) => m * p).find((s) => s >= raw) || raw;
    const out = [];
    for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-9; v += step) out.push(Math.abs(v) < step * 1e-9 ? 0 : v);
    return out;
  }

  /**
   * @param {HTMLElement} host - an empty element; the chart fills its width
   * @param {Object} opt
   * @param {function(number|null, number|null)} [opt.onHover] - the member
   *   index picked out and the time index under the pointer, or nulls when
   *   the pointer leaves
   * @param {function(number)} [opt.onPick] - a click set the cursor at this time index
   */
  function createInventoryChart(host, opt = {}) {
    const svg = el('svg', { class: 'nz-inv-svg', role: 'img', 'aria-label': 'The inventory over time' });
    host.appendChild(svg);
    const tip = document.createElement('div');
    tip.className = 'nz-inv-tip';
    tip.hidden = true;
    host.appendChild(tip);
    let data = null;
    let geo = null;
    let hot = null;
    let cursor = null;     // time index of the set cursor
    let pointerAt = null;  // time index under the pointer
    const els = { lines: [], total: null, cursor: null, cursorLabel: null, plot: null };

    function colours() {
      const css = getComputedStyle(document.documentElement);
      const v = (name, fb) => (css.getPropertyValue(name).trim() || fb);
      const theme = document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
      return {
        theme,
        bg: v('--bg-surface', '#fcf7f2'), ink: v('--text-primary', '#352921'), muted: v('--text-muted', '#786b5d'),
        grid: v('--border-color', '#e0d7ce'), axis: v('--text-secondary', '#6b5d4f'), accent: v('--accent-line', '#bb7d37'),
      };
    }

    /**
     * @param {Object|null} d - {times: number[] (s), tScale: {factor, unit},
     *   series: [{label, values: number[], color, dash}], total: number[]|null,
     *   yTitle, xLog, yLog}; null for an empty chart with a message in d0
     * @param {string} [message] - shown when there is nothing to draw
     */
    function render(d, message) {
      data = d;
      hot = null;
      pointerAt = null;
      if (cursor !== null && (!d || cursor >= d.times.length)) cursor = null;
      while (svg.firstChild) svg.removeChild(svg.firstChild);
      tip.hidden = true;
      const col = colours();
      const W = Math.max(260, Math.round(host.clientWidth || 400));
      const H = Math.max(220, Math.min(420, Math.round(W * 0.66)));
      svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
      svg.setAttribute('width', W);
      svg.setAttribute('height', H);
      svg.setAttribute('font-family', 'verdana, sans-serif');
      el('rect', { x: 0, y: 0, width: W, height: H, fill: col.bg }, svg);
      if (!d || !d.series.length) {
        const t = el('text', { x: W / 2, y: H / 2, 'text-anchor': 'middle', 'font-size': 12, fill: col.muted }, svg);
        t.textContent = message || 'Nothing to draw.';
        geo = null;
        return;
      }
      const m = { l: 62, r: 12, t: 22, b: 40 };
      const pw = W - m.l - m.r, ph = H - m.t - m.b;
      const tv = d.times.map((t) => t / d.tScale.factor);
      /* The x range: the times drawn, less t = 0 on a log axis. */
      const xs = d.xLog ? tv.filter((t) => t > 0) : tv;
      const x0 = Math.min(...xs), x1 = Math.max(...xs);
      /* The y range: everything drawn; on a log axis no more than twelve
         decades under the top, where the calculation is still good. */
      let ymax = 0, ymin = Infinity;
      const all = d.total ? d.series.concat([{ values: d.total }]) : d.series;
      for (const s of all) for (const v of s.values) { if (v > ymax) ymax = v; if (v > 0 && v < ymin) ymin = v; }
      if (!(ymax > 0)) {
        const t = el('text', { x: W / 2, y: H / 2, 'text-anchor': 'middle', 'font-size': 12, fill: col.muted }, svg);
        t.textContent = message || 'Every value is zero.';
        geo = null;
        return;
      }
      let y0, y1;
      if (d.yLog) {
        y1 = Math.pow(10, Math.ceil(Math.log10(ymax) + 0.02));
        y0 = Math.max(ymin, y1 * 1e-12);
        y0 = Math.pow(10, Math.floor(Math.log10(y0)));
        if (y1 / y0 < 100) y0 = y1 / 100;
      } else { y0 = 0; y1 = ymax * 1.05; }
      const fx = d.xLog ? (t) => m.l + pw * (Math.log10(t / x0) / Math.log10(x1 / x0 || 10))
        : (t) => m.l + pw * ((t - x0) / (x1 - x0 || 1));
      const fy = d.yLog ? (v) => m.t + ph * (1 - Math.log10(Math.max(v, y0) / y0) / Math.log10(y1 / y0))
        : (v) => m.t + ph * (1 - (v - y0) / (y1 - y0 || 1));
      geo = { m, pw, ph, W, H, fx, fy, tv, y0, y1 };

      /* Grid and axes, recessive. */
      const grid = el('g', { stroke: col.grid, 'stroke-width': 1 }, svg);
      const labels = el('g', { 'font-size': 10, fill: col.muted }, svg);
      const xt = d.xLog ? logTicks(x0, x1) : linTicks(x0, x1);
      for (const t of xt) {
        const x = fx(t);
        el('line', { x1: x, y1: m.t, x2: x, y2: m.t + ph }, grid);
        richText(el('text', { x, y: m.t + ph + 14, 'text-anchor': 'middle' }, labels), numText(t), 10);
      }
      const yt = d.yLog ? logTicks(y0, y1) : linTicks(y0, y1);
      for (const v of yt) {
        const y = fy(v);
        el('line', { x1: m.l, y1: y, x2: m.l + pw, y2: y }, grid);
        richText(el('text', { x: m.l - 6, y: y + 3.5, 'text-anchor': 'end' }, labels), numText(v), 10);
      }
      el('rect', { x: m.l, y: m.t, width: pw, height: ph, fill: 'none', stroke: col.axis, 'stroke-width': 1 }, svg);
      richText(el('text', { x: m.l + pw / 2, y: H - 6, 'text-anchor': 'middle', 'font-size': 11, fill: col.axis }, svg), `Time (${d.tScale.unit})`, 11);
      richText(el('text', { x: m.l, y: 13, 'font-size': 11, fill: col.axis }, svg), d.yTitle, 11);

      /* The lines, clipped to the plot. */
      const clipId = `nzInvClip${Math.random().toString(36).slice(2, 8)}`;
      el('rect', { x: m.l, y: m.t, width: pw, height: ph }, el('clipPath', { id: clipId }, el('defs', {}, svg)));
      const plot = el('g', { 'clip-path': `url(#${clipId})`, fill: 'none', 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }, svg);
      els.plot = plot;
      const pathOf = (vals) => {
        let dd = '';
        let pen = false;
        for (let i = 0; i < tv.length; i++) {
          const t = tv[i], v = vals[i];
          if ((d.xLog && !(t > 0)) || (d.yLog && !(v > 0))) { pen = false; continue; }
          dd += `${pen ? 'L' : 'M'}${fx(t).toFixed(1)},${fy(v).toFixed(1)}`;
          pen = true;
        }
        return dd;
      };
      els.lines = d.series.map((s) => el('path', { d: pathOf(s.values), stroke: s.color, 'stroke-width': 2, 'stroke-dasharray': s.dash || null }, plot));
      els.total = d.total ? el('path', { d: pathOf(d.total), stroke: col.ink, 'stroke-width': 1.5, 'stroke-dasharray': '1.5 3', opacity: 0.8 }, plot) : null;
      els.cursor = el('line', { x1: 0, y1: m.t, x2: 0, y2: m.t + ph, stroke: col.accent, 'stroke-width': 1.5, visibility: 'hidden' }, svg);
      els.cursorLabel = el('text', { x: 0, y: m.t + 12, 'font-size': 10, fill: col.accent, 'text-anchor': 'middle', visibility: 'hidden', stroke: col.bg, 'stroke-width': 3, 'paint-order': 'stroke', 'stroke-linejoin': 'round' }, svg);
      /* The whole plot takes the pointer. */
      const hit = el('rect', { x: m.l, y: m.t, width: pw, height: ph, fill: 'transparent', style: 'cursor: crosshair' }, svg);
      hit.addEventListener('pointermove', (ev) => pointer(ev));
      hit.addEventListener('pointerdown', (ev) => pointer(ev));
      hit.addEventListener('pointerleave', () => leave());
      hit.addEventListener('click', () => { if (pointerAt !== null) { cursor = pointerAt; if (opt.onPick) opt.onPick(cursor); } });
      showCursor();
      paintHot();
    }

    /* The time index nearest a screen x. */
    function indexAt(x) {
      if (!geo) return null;
      let best = null, bd = Infinity;
      geo.tv.forEach((t, i) => {
        if (data.xLog && !(t > 0)) return;
        const d = Math.abs(geo.fx(t) - x);
        if (d < bd) { bd = d; best = i; }
      });
      return best;
    }

    function pointer(ev) {
      if (!geo) return;
      const r = svg.getBoundingClientRect();
      const sx = (ev.clientX - r.left) * (geo.W / r.width), sy = (ev.clientY - r.top) * (geo.H / r.height);
      const i = indexAt(sx);
      if (i === null) return;
      pointerAt = i;
      /* The line nearest the pointer at that time, if one is near enough. */
      let near = null, nd = 28;
      data.series.forEach((s, k) => {
        const v = s.values[i];
        if (data.yLog && !(v > 0)) return;
        const dy = Math.abs(geo.fy(v) - sy);
        if (dy < nd) { nd = dy; near = k; }
      });
      hot = near;
      paintHot();
      showCursor(i);
      showTip(i, ev);
      if (opt.onHover) opt.onHover(hot, i);
    }

    function leave() {
      pointerAt = null;
      hot = null;
      tip.hidden = true;
      paintHot();
      showCursor();
      if (opt.onHover) opt.onHover(null, null);
    }

    function paintHot() {
      els.lines.forEach((p, k) => {
        p.setAttribute('stroke-width', hot === k ? 3.5 : 2);
        p.setAttribute('opacity', hot === null || hot === k ? 1 : 0.3);
        if (hot === k) p.parentNode.appendChild(p);
      });
    }

    function showCursor(at) {
      const i = at ?? cursor;
      if (!geo || i === null || i === undefined) {
        if (els.cursor) { els.cursor.setAttribute('visibility', 'hidden'); els.cursorLabel.setAttribute('visibility', 'hidden'); }
        return;
      }
      const t = geo.tv[i];
      if (data.xLog && !(t > 0)) return;
      const x = geo.fx(t);
      els.cursor.setAttribute('x1', x); els.cursor.setAttribute('x2', x);
      els.cursor.setAttribute('visibility', 'visible');
      els.cursorLabel.setAttribute('x', Math.min(Math.max(x, geo.m.l + 30), geo.m.l + geo.pw - 30));
      while (els.cursorLabel.firstChild) els.cursorLabel.removeChild(els.cursorLabel.firstChild);
      richText(els.cursorLabel, `${numText(t)} ${data.tScale.unit}`, 10);
      els.cursorLabel.setAttribute('visibility', 'visible');
    }

    function showTip(i, ev) {
      const rows = data.series.map((s, k) => ({ k, s, v: s.values[i] })).filter((r) => r.v > 0).sort((p, q) => q.v - p.v);
      tip.replaceChildren();
      const head = document.createElement('div');
      head.className = 'nz-inv-tip-head';
      head.replaceChildren(supSpan(`t = ${numText(geo.tv[i])} ${data.tScale.unit}`));
      tip.appendChild(head);
      const show = rows.slice(0, 8);
      if (hot !== null && !show.some((r) => r.k === hot)) { const r = rows.find((x) => x.k === hot); if (r) show.push(r); }
      for (const r of show) {
        const line = document.createElement('div');
        line.className = 'nz-inv-tip-row' + (r.k === hot ? ' hot' : '');
        const sw = document.createElement('span');
        sw.className = 'nz-inv-sw';
        sw.style.borderTopColor = r.s.color;
        sw.style.borderTopStyle = r.s.dash ? 'dashed' : 'solid';
        line.appendChild(sw);
        line.appendChild(supSpan(r.s.label));
        const val = document.createElement('span');
        val.className = 'nz-inv-tip-val';
        val.appendChild(supSpan(numText(r.v)));
        line.appendChild(val);
        tip.appendChild(line);
      }
      if (rows.length > show.length) {
        const more = document.createElement('div');
        more.className = 'nz-inv-tip-more';
        more.textContent = `and ${rows.length - show.length} more`;
        tip.appendChild(more);
      }
      if (data.total) {
        const line = document.createElement('div');
        line.className = 'nz-inv-tip-row total';
        line.appendChild(document.createTextNode('Total'));
        const val = document.createElement('span');
        val.className = 'nz-inv-tip-val';
        val.appendChild(supSpan(numText(data.total[i])));
        line.appendChild(val);
        tip.appendChild(line);
      }
      tip.hidden = false;
      const hr = host.getBoundingClientRect();
      const x = ev.clientX - hr.left, y = ev.clientY - hr.top;
      const w = tip.offsetWidth, h = tip.offsetHeight;
      tip.style.left = `${Math.max(4, Math.min(hr.width - w - 4, x + (x > hr.width / 2 ? -w - 14 : 14)))}px`;
      tip.style.top = `${Math.max(4, Math.min(hr.height - h - 4, y - h / 2))}px`;
    }

    /* A span with its superscripts as <sup>, text only. */
    function supSpan(text) {
      const span = document.createElement('span');
      for (const r of C.supRuns(text)) {
        if (r.sup) { const s = document.createElement('sup'); s.textContent = r.t; span.appendChild(s); }
        else span.appendChild(document.createTextNode(r.t));
      }
      return span;
    }

    return {
      render,
      /** Pick out member k (from outside: the table, the chain drawing), or none. */
      setHot(k) { hot = k === undefined ? null : k; paintHot(); },
      /** Put the cursor at time index i, or take it away. */
      setCursor(i) { cursor = i === undefined ? null : i; showCursor(); },
      get cursor() { return cursor; },
      /** The drawing as a stand-alone SVG file. */
      svgFile() {
        const copy = svg.cloneNode(true);
        copy.setAttribute('xmlns', NS);
        copy.querySelectorAll('rect[style]').forEach((r) => r.remove());
        return '<?xml version="1.0" encoding="UTF-8"?>\n' + new XMLSerializer().serializeToString(copy);
      },
      get svg() { return svg; },
    };
  }

  window.KVOT_ENSDF_INVENTORY = { createInventoryChart, lineStyle, numText };
})();
