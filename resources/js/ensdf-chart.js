/* ==========================================================================
   ENSDF.HTML: THE CHART OF NUCLIDES

   One canvas, N across and Z up as in NuDat, one cell per nuclide coloured
   by the page's colour mode. Pan by dragging, zoom with the wheel or a pinch
   (or the buttons, or + and -), arrow keys walk from cell to cell. The cells
   carry their name from about 24 px, the half-life from 44 px and the decay
   modes from 64 px. The selected nuclide's decay chain is drawn over the
   chart when the page hands one in.

   Canvas rather than SVG: 3400 cells redrawn on every frame of a pan is
   cheap on a canvas and heavy as DOM, and nothing in a cell needs to be an
   element of its own -- the hover card and the legend, which do, are HTML.

   One global: KVOT_ENSDF_CHART.
   ========================================================================== */
/* global KVOT_ENSDF_CORE */
(function () {
  'use strict';

  const C = KVOT_ENSDF_CORE;
  const MAGIC = [2, 8, 20, 28, 50, 82, 126];
  const GUTTER_LEFT = 30;
  const GUTTER_BOTTOM = 20;
  const MIN_CELL = 2;
  const MAX_CELL = 140;

  function cssVar(name, fallback) {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fallback;
  }

  /**
   * @param {HTMLElement} host - positioned container; the canvas fills it
   * @param {Object} [hooks]
   * @param {function({z,a,k})} [hooks.onSelect]
   * @param {function(Object|null, number, number)} [hooks.onHover] - nuclide, client x, y
   */
  function createChart(host, hooks = {}) {
    const canvas = document.createElement('canvas');
    canvas.className = 'nz-canvas';
    canvas.tabIndex = 0;
    canvas.setAttribute('role', 'img');
    canvas.setAttribute('aria-label', 'Chart of nuclides: neutron number across, proton number up. Arrow keys move between nuclides, Enter opens one, plus and minus zoom, 0 shows the whole chart.');
    host.insertBefore(canvas, host.firstChild);
    const ctx = canvas.getContext('2d');

    const st = {
      idx: null, mode: 'halflife', domain: null, theme: 'light',
      fills: new Map(), classes: new Map(),
      view: { s: 6, cx: 90, cy: 60 }, W: 0, H: 0, dpr: 1, fitted: false,
      hover: null, sel: null, chain: null, highlight: null,
      rowSpan: new Map(), colSpan: new Map(),
      ink: '#352921', muted: '#786b5d', bg: '#ffffff', line: '#e0d7ce', accent: '#bb7d37', select: '#bb6c5d',
      frame: 0,
    };

    /* ---------------- geometry ---------------- */
    const px = (n) => st.W / 2 + (n - st.view.cx) * st.view.s;
    const py = (z) => st.H / 2 + (st.view.cy - z) * st.view.s;
    const worldN = (x) => st.view.cx + (x - st.W / 2) / st.view.s;
    const worldZ = (y) => st.view.cy - (y - st.H / 2) / st.view.s;

    function nuclideAt(x, y) {
      if (!st.idx) return null;
      const n = Math.round(worldN(x)), z = Math.round(worldZ(y));
      const hit = st.idx.get(z, z + n);
      return hit && !hit.hidden ? hit : null;
    }

    function clampView() {
      if (!st.idx) return;
      const v = st.view;
      v.s = Math.max(MIN_CELL, Math.min(MAX_CELL, v.s));
      v.cx = Math.max(-5, Math.min(st.idx.maxN + 5, v.cx));
      v.cy = Math.max(-5, Math.min(st.idx.maxZ + 5, v.cy));
    }

    function fit() {
      if (!st.idx || !st.W) return;
      const cols = st.idx.maxN + 3, rows = st.idx.maxZ + 3;
      const s = Math.min((st.W - GUTTER_LEFT - 8) / cols, (st.H - GUTTER_BOTTOM - 8) / rows);
      st.view.s = Math.max(MIN_CELL, s);
      /* The middle of the data at the middle of what the gutters leave. */
      st.view.cx = st.idx.maxN / 2 - (GUTTER_LEFT / 2) / st.view.s;
      st.view.cy = st.idx.maxZ / 2 - (GUTTER_BOTTOM / 2) / st.view.s;
      st.fitted = true;
      redraw();
    }

    function zoomAt(factor, x, y) {
      const n0 = worldN(x), z0 = worldZ(y);
      st.view.s *= factor;
      clampView();
      st.view.cx = n0 - (x - st.W / 2) / st.view.s;
      st.view.cy = z0 + (y - st.H / 2) / st.view.s;
      clampView();
      redraw();
    }

    function centreOn(z, a, minCell) {
      const n = a - z;
      if (minCell && st.view.s < minCell) st.view.s = minCell;
      st.view.cx = n;
      st.view.cy = z;
      clampView();
      redraw();
    }

    /** Pan just enough that a cell is inside the drawing, away from the gutters. */
    function reveal(z, a) {
      const n = a - z, s = st.view.s, pad = s * 1.5;
      const x = px(n), y = py(z);
      if (x < GUTTER_LEFT + pad) st.view.cx -= (GUTTER_LEFT + pad - x) / s;
      if (x > st.W - pad) st.view.cx += (x - (st.W - pad)) / s;
      if (y < pad) st.view.cy += (pad - y) / s;
      if (y > st.H - GUTTER_BOTTOM - pad) st.view.cy -= (y - (st.H - GUTTER_BOTTOM - pad)) / s;
      clampView();
    }

    /* ---------------- colours ---------------- */
    function readTheme() {
      st.theme = document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
      st.ink = cssVar('--text-primary', '#352921');
      st.muted = cssVar('--text-muted', '#786b5d');
      st.bg = cssVar('--nz-chart-bg', cssVar('--bg-primary', '#ffffff'));
      st.line = cssVar('--nz-magic', cssVar('--border-color', '#e0d7ce'));
      st.accent = cssVar('--accent-line', '#bb7d37');
      st.select = cssVar('--nz-select', cssVar('--color-kvot-accent', '#bb6c5d'));
    }

    function recolour() {
      st.fills.clear();
      st.classes.clear();
      if (!st.idx) return;
      st.domain = (st.mode === 'halflife' || st.mode === 'mode') ? null : C.scaleDomain(st.mode, st.idx.shown);
      for (const n of st.idx.shown) {
        const id = n.z * 1000 + n.a;
        st.fills.set(id, C.nuclideColour(n, st.mode, st.domain, st.theme));
        const g = n.s && n.s[0];
        if (st.mode === 'halflife') st.classes.set(id, C.halfLifeClass(g));
        else if (st.mode === 'mode') st.classes.set(id, g ? C.primaryMode(g) : 'unknown');
      }
    }

    function spans() {
      st.rowSpan.clear();
      st.colSpan.clear();
      for (const n of st.idx.shown) {
        const r = st.rowSpan.get(n.z) || [Infinity, -Infinity];
        r[0] = Math.min(r[0], n.n); r[1] = Math.max(r[1], n.n);
        st.rowSpan.set(n.z, r);
        const c = st.colSpan.get(n.n) || [Infinity, -Infinity];
        c[0] = Math.min(c[0], n.z); c[1] = Math.max(c[1], n.z);
        st.colSpan.set(n.n, c);
      }
    }

    /* ---------------- drawing ---------------- */
    function redraw() {
      if (st.frame) return;
      st.frame = requestAnimationFrame(() => { st.frame = 0; draw(); });
    }

    function draw() {
      const { W, H, dpr } = st;
      if (!W || !H) return;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.fillStyle = st.bg;
      ctx.fillRect(0, 0, W, H);
      if (!st.idx) return;
      const s = st.view.s;
      const gap = s >= 7 ? Math.max(1, Math.min(3, s * 0.06)) : (s >= 4 ? 0.5 : 0);
      const nMin = Math.floor(worldN(0)) - 1, nMax = Math.ceil(worldN(W)) + 1;
      const zMin = Math.floor(worldZ(H)) - 1, zMax = Math.ceil(worldZ(0)) + 1;

      /* Magic numbers: a pair of hairlines along the row or column, only
         where there are nuclides, so the lines trace the chart and not the
         empty page. */
      ctx.strokeStyle = st.line;
      ctx.lineWidth = s >= 10 ? 1.5 : 1;
      for (const m of MAGIC) {
        const r = st.rowSpan.get(m);
        if (r) {
          const x0 = px(r[0]) - s / 2 - s * 0.3, x1 = px(r[1]) + s / 2 + s * 0.3;
          for (const dz of [0.5, -0.5]) { const y = py(m + dz); ctx.beginPath(); ctx.moveTo(x0, y); ctx.lineTo(x1, y); ctx.stroke(); }
        }
        const c = st.colSpan.get(m);
        if (c) {
          const y0 = py(c[1]) - s / 2 - s * 0.3, y1 = py(c[0]) + s / 2 + s * 0.3;
          for (const dn of [0.5, -0.5]) { const x = px(m + dn); ctx.beginPath(); ctx.moveTo(x, y0); ctx.lineTo(x, y1); ctx.stroke(); }
        }
      }

      const hi = st.highlight;
      const chainKeys = st.chain ? st.chain.cells : null;
      const label = s >= 24;
      for (const n of st.idx.shown) {
        if (n.n < nMin || n.n > nMax || n.z < zMin || n.z > zMax) continue;
        const id = n.z * 1000 + n.a;
        const x = px(n.n) - s / 2, y = py(n.z) - s / 2;
        const fill = st.fills.get(id);
        const dim = (hi && !hi(n, st.classes.get(id))) || (chainKeys && !chainKeys.has(id) && st.chain.dim);
        ctx.globalAlpha = dim ? 0.18 : 1;
        ctx.fillStyle = fill;
        if (s >= 7) roundRect(x + gap / 2, y + gap / 2, s - gap, s - gap, Math.min(3, s * 0.08));
        else ctx.fillRect(x + gap / 2, y + gap / 2, s - gap, s - gap);
        if (n.s && n.s.length > 1 && s >= 12) {
          /* A nuclide with isomers carries a notch in its top-right corner. */
          const t = Math.max(3, s * 0.16);
          ctx.fillStyle = C.inkOn(fill);
          ctx.globalAlpha = dim ? 0.1 : 0.55;
          ctx.beginPath();
          ctx.moveTo(x + s - gap / 2 - t, y + gap / 2);
          ctx.lineTo(x + s - gap / 2, y + gap / 2);
          ctx.lineTo(x + s - gap / 2, y + gap / 2 + t);
          ctx.closePath();
          ctx.fill();
        }
        ctx.globalAlpha = 1;
        if (label && !dim) drawLabel(n, x, y, s, fill);
      }
      ctx.globalAlpha = 1;

      /* Element symbols at the left end of each row, as NuDat has them. */
      if (s >= 7) {
        ctx.fillStyle = st.muted;
        ctx.textAlign = 'right';
        ctx.textBaseline = 'middle';
        ctx.font = `${Math.min(15, Math.max(9, s * 0.55))}px verdana, sans-serif`;
        for (const [z, r] of st.rowSpan) {
          if (z < zMin || z > zMax) continue;
          const el = C.ELEMENTS[z] ? C.ELEMENTS[z][0] : '';
          ctx.fillText(el, px(r[0]) - s / 2 - Math.max(3, s * 0.2), py(z));
        }
      }

      if (st.chain) drawChain();

      const outline = (id, colour, width) => {
        const n = st.idx.byId.get(id);
        if (!n) return;
        const x = px(n.n) - s / 2, y = py(n.z) - s / 2;
        ctx.strokeStyle = colour;
        ctx.lineWidth = width;
        ctx.strokeRect(x + width / 2, y + width / 2, s - width, s - width);
      };
      if (st.hover !== null) outline(st.hover, st.ink, Math.max(1, Math.min(2, s * 0.08)));
      if (st.sel) {
        const id = st.sel.z * 1000 + st.sel.a;
        const w = Math.max(2, Math.min(4, s * 0.12));
        outline(id, st.bg, w + 2);
        outline(id, st.select, w);
      }
      drawAxes();
    }

    function roundRect(x, y, w, h, r) {
      ctx.beginPath();
      if (ctx.roundRect) ctx.roundRect(x, y, w, h, r);
      else ctx.rect(x, y, w, h);
      ctx.fill();
    }

    function drawLabel(n, x, y, s, fill) {
      const g = n.s && n.s[0];
      const nm = C.name(n.z, n.a, 0, n);
      ctx.fillStyle = C.inkOn(fill);
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      const big = Math.min(22, s * 0.3);
      const small = Math.min(15, s * 0.19);
      const lines = s >= 64 ? 3 : s >= 44 ? 2 : 1;
      const cy = y + s / 2 - (lines - 1) * small * 0.72;
      /* Mass number set small and high before the symbol. */
      ctx.font = `600 ${big}px verdana, sans-serif`;
      const symW = ctx.measureText(nm.sym).width;
      ctx.font = `${big * 0.62}px verdana, sans-serif`;
      const massW = nm.mass ? ctx.measureText(nm.mass).width : 0;
      const x0 = x + s / 2 - (symW + massW) / 2;
      ctx.textAlign = 'left';
      if (nm.mass) ctx.fillText(nm.mass, x0, cy - big * 0.28);
      ctx.font = `600 ${big}px verdana, sans-serif`;
      ctx.fillText(nm.sym, x0 + massW, cy);
      if (lines >= 2 && g) drawRich(C.halfLifeShort(g), x + s / 2, cy + small * 1.45, small, s - 4);
      if (lines >= 3 && g) {
        const modes = (g.br || []).slice().sort((p, q) => (q[1] ?? -1) - (p[1] ?? -1)).slice(0, 2)
          .map((b) => `${C.modeText(b[0])}${b[1] !== null && b[1] < 100 ? ' ' + C.pctText(b[1]).replace(' %', '%') : ''}`);
        if (modes.length) drawRich(modes.join('  '), x + s / 2, cy + small * 2.75, small * 0.9, s - 4);
      }
    }

    /**
     * Text centred on (cx, y) with its superscripts set small and raised,
     * rather than drawn as Unicode superscript characters, which Verdana
     * mostly lacks. Shrinks to fit maxW.
     */
    function drawRich(text, cx, y, size, maxW) {
      const runs = C.supRuns(text);
      if (!runs.length) return;
      let px = size;
      const width = () => runs.reduce((t, r) => {
        ctx.font = `${r.sup ? px * 0.7 : px}px verdana, sans-serif`;
        r.w = ctx.measureText(r.t).width;
        return t + r.w;
      }, 0);
      let total = width();
      if (maxW && total > maxW) { px *= maxW / total; total = width(); }
      ctx.textAlign = 'left';
      let at = cx - total / 2;
      for (const r of runs) {
        ctx.font = `${r.sup ? px * 0.7 : px}px verdana, sans-serif`;
        ctx.fillText(r.t, at, r.sup ? y - px * 0.36 : y);
        at += r.w;
      }
      ctx.textAlign = 'center';
    }

    function drawChain() {
      const s = st.view.s;
      const ch = st.chain;
      /* Members outlined; arrows between cell centres. Same-cell moves (IT)
         are not drawn here -- they are in the chain panel. */
      ctx.save();
      ctx.lineCap = 'round';
      const w = Math.max(1.2, Math.min(2.5, s * 0.07));
      /* Members ringed, so the chain reads even where its arrows are short. */
      if (!ch.dim && s >= 4) {
        ctx.strokeStyle = st.ink;
        ctx.lineWidth = Math.max(1, Math.min(2, s * 0.06));
        for (const id of ch.cells) {
          const n = st.idx.byId.get(id);
          if (!n) continue;
          const x = px(n.n) - s / 2, y = py(n.z) - s / 2, inset = ctx.lineWidth / 2 + (s >= 7 ? 1 : 0);
          ctx.strokeRect(x + inset, y + inset, s - 2 * inset, s - 2 * inset);
        }
      }
      for (const e of ch.arrows) {
        const x0 = px(e.n0), y0 = py(e.z0), x1 = px(e.n1), y1 = py(e.z1);
        const dx = x1 - x0, dy = y1 - y0, L = Math.hypot(dx, dy);
        if (L < 1) continue;
        const ux = dx / L, uy = dy / L;
        const trim = Math.min(L / 3, s * 0.32);
        const ax = x0 + ux * trim, ay = y0 + uy * trim, bx = x1 - ux * trim, by = y1 - uy * trim;
        for (const [colour, width] of [[st.bg, w + 2.5], [st.ink, w]]) {
          ctx.strokeStyle = colour;
          ctx.lineWidth = width;
          ctx.setLineDash(e.faint ? [w * 2, w * 2] : []);
          ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(bx, by); ctx.stroke();
          const hl = Math.max(4, Math.min(10, s * 0.25)) + (width - w);
          ctx.setLineDash([]);
          ctx.fillStyle = colour;
          ctx.beginPath();
          ctx.moveTo(bx + ux * (width - w) * 0.5, by + uy * (width - w) * 0.5);
          ctx.lineTo(bx - ux * hl - uy * hl * 0.55, by - uy * hl + ux * hl * 0.55);
          ctx.lineTo(bx - ux * hl + uy * hl * 0.55, by - uy * hl - ux * hl * 0.55);
          ctx.closePath();
          ctx.fill();
        }
      }
      ctx.restore();
    }

    function drawAxes() {
      const { W, H } = st;
      const s = st.view.s;
      ctx.fillStyle = st.bg;
      ctx.globalAlpha = 0.92;
      ctx.fillRect(0, 0, GUTTER_LEFT, H);
      ctx.fillRect(0, H - GUTTER_BOTTOM, W, GUTTER_BOTTOM);
      ctx.globalAlpha = 1;
      ctx.fillStyle = st.muted;
      ctx.font = '10px verdana, sans-serif';
      const step = s >= 18 ? 1 : s >= 9 ? 2 : s >= 5 ? 5 : 10;
      const step10 = Math.max(step, 1);
      ctx.textAlign = 'right';
      ctx.textBaseline = 'middle';
      for (let z = Math.ceil(worldZ(H)); z <= Math.floor(worldZ(0)); z++) {
        if (z < 0 || z % step10) continue;
        const y = py(z);
        if (y > H - GUTTER_BOTTOM - 4) continue;
        ctx.fillText(String(z), GUTTER_LEFT - 5, y);
      }
      ctx.textAlign = 'center';
      ctx.textBaseline = 'alphabetic';
      for (let n = Math.ceil(worldN(GUTTER_LEFT)); n <= Math.floor(worldN(W)); n++) {
        if (n < 0 || n % step10) continue;
        ctx.fillText(String(n), px(n), H - 6);
      }
      /* Axis names in the corners the gutters leave free of numbers. */
      ctx.fillStyle = st.bg;
      ctx.fillRect(0, H - GUTTER_BOTTOM, GUTTER_LEFT, GUTTER_BOTTOM);
      ctx.fillRect(0, 0, GUTTER_LEFT, 18);
      ctx.textAlign = 'left';
      ctx.fillStyle = st.ink;
      ctx.font = '600 10px verdana, sans-serif';
      ctx.fillText('N →', 3, H - 6);
      ctx.fillText('Z ↑', 3, 12);
    }

    /* ---------------- sizing ---------------- */
    function resize() {
      const r = host.getBoundingClientRect();
      const W = Math.max(1, Math.floor(r.width)), H = Math.max(1, Math.floor(r.height));
      const dpr = Math.min(3, window.devicePixelRatio || 1);
      if (W === st.W && H === st.H && dpr === st.dpr) return;
      const first = !st.W;
      st.W = W; st.H = H; st.dpr = dpr;
      canvas.width = Math.round(W * dpr);
      canvas.height = Math.round(H * dpr);
      canvas.style.width = W + 'px';
      canvas.style.height = H + 'px';
      if ((first || !st.fitted) && st.idx) fit();
      else redraw();
    }
    const ro = new ResizeObserver(() => resize());
    ro.observe(host);

    /* ---------------- pointer and keys ---------------- */
    const pointers = new Map();
    let drag = null;
    let pinch = null;

    function local(ev) {
      const r = canvas.getBoundingClientRect();
      return [ev.clientX - r.left, ev.clientY - r.top];
    }

    canvas.addEventListener('pointerdown', (ev) => {
      canvas.focus({ preventScroll: true });
      const [x, y] = local(ev);
      pointers.set(ev.pointerId, [x, y]);
      canvas.setPointerCapture(ev.pointerId);
      if (pointers.size === 1) drag = { x, y, cx: st.view.cx, cy: st.view.cy, moved: false, type: ev.pointerType };
      else if (pointers.size === 2) {
        const [a, b] = [...pointers.values()];
        pinch = { d: Math.hypot(a[0] - b[0], a[1] - b[1]), s: st.view.s, mx: (a[0] + b[0]) / 2, my: (a[1] + b[1]) / 2 };
        drag = null;
      }
    });
    canvas.addEventListener('pointermove', (ev) => {
      const [x, y] = local(ev);
      if (pointers.has(ev.pointerId)) pointers.set(ev.pointerId, [x, y]);
      if (pinch && pointers.size === 2) {
        const [a, b] = [...pointers.values()];
        const d = Math.hypot(a[0] - b[0], a[1] - b[1]);
        const target = pinch.s * d / pinch.d;
        zoomAt(target / st.view.s, pinch.mx, pinch.my);
        return;
      }
      if (drag) {
        const dx = x - drag.x, dy = y - drag.y;
        if (!drag.moved && Math.hypot(dx, dy) > (drag.type === 'touch' ? 8 : 4)) drag.moved = true;
        if (drag.moved) {
          st.view.cx = drag.cx - dx / st.view.s;
          st.view.cy = drag.cy + dy / st.view.s;
          clampView();
          canvas.classList.add('panning');
          setHover(null, ev);
          redraw();
          return;
        }
      }
      if (ev.pointerType !== 'touch') setHover(nuclideAt(x, y), ev);
    });
    const end = (ev) => {
      const [x, y] = local(ev);
      const wasDrag = drag && drag.moved;
      pointers.delete(ev.pointerId);
      if (pointers.size < 2) pinch = null;
      if (drag && !wasDrag && ev.type === 'pointerup') {
        const n = nuclideAt(x, y);
        if (n && hooks.onSelect) hooks.onSelect({ z: n.z, a: n.a, k: 0, via: 'chart' });
      }
      if (!pointers.size) { drag = null; canvas.classList.remove('panning'); }
    };
    canvas.addEventListener('pointerup', end);
    canvas.addEventListener('pointercancel', end);
    canvas.addEventListener('pointerleave', (ev) => { if (!drag) setHover(null, ev); });
    canvas.addEventListener('wheel', (ev) => {
      ev.preventDefault();
      const [x, y] = local(ev);
      const dy = ev.deltaMode === 1 ? ev.deltaY * 16 : ev.deltaY;
      zoomAt(Math.exp(-dy * (ev.ctrlKey ? 0.01 : 0.0022)), x, y);
    }, { passive: false });
    canvas.addEventListener('dblclick', (ev) => { const [x, y] = local(ev); zoomAt(2, x, y); });
    canvas.addEventListener('keydown', (ev) => {
      if (!st.idx) return;
      const k = ev.key;
      if (k === '+' || k === '=') { zoomAt(1.4, st.W / 2, st.H / 2); ev.preventDefault(); return; }
      if (k === '-' || k === '_') { zoomAt(1 / 1.4, st.W / 2, st.H / 2); ev.preventDefault(); return; }
      if (k === '0') { fit(); ev.preventDefault(); return; }
      const dir = { ArrowLeft: [0, -1], ArrowRight: [0, 1], ArrowUp: [1, 0], ArrowDown: [-1, 0] }[k];
      if (!dir) {
        if (k === 'Enter' && st.sel && hooks.onSelect) hooks.onSelect({ z: st.sel.z, a: st.sel.a, k: 0, via: 'key', open: true });
        return;
      }
      ev.preventDefault();
      const cur = st.sel || { z: Math.round(st.view.cy), a: Math.round(st.view.cy) + Math.round(st.view.cx) };
      let z = cur.z, n = cur.a - cur.z;
      for (let step = 1; step <= 12; step++) {
        const z2 = z + dir[0] * step, n2 = n + dir[1] * step;
        const hit = st.idx.get(z2, z2 + n2);
        if (hit && !hit.hidden) {
          reveal(hit.z, hit.a);
          if (hooks.onSelect) hooks.onSelect({ z: hit.z, a: hit.a, k: 0, via: 'key' });
          return;
        }
      }
    });

    function setHover(n, ev) {
      const id = n ? n.z * 1000 + n.a : null;
      if (id !== st.hover) { st.hover = id; redraw(); }
      if (hooks.onHover) hooks.onHover(n, ev ? ev.clientX : 0, ev ? ev.clientY : 0);
    }

    document.documentElement.addEventListener('kvot-theme-change', () => { readTheme(); recolour(); redraw(); });
    readTheme();

    return {
      canvas,
      setIndex(idx) {
        st.idx = idx;
        spans();
        recolour();
        if (st.W) { if (!st.fitted) fit(); else redraw(); }
      },
      setMode(mode) { st.mode = mode; recolour(); redraw(); },
      get mode() { return st.mode; },
      get domain() { return st.domain; },
      get theme() { return st.theme; },
      classOf(n) { return st.classes.get(n.z * 1000 + n.a); },
      select(sel, centre) {
        st.sel = sel ? { z: sel.z, a: sel.a } : null;
        if (sel && centre) {
          const x = px(sel.a - sel.z), y = py(sel.z);
          if (x < GUTTER_LEFT || x > st.W || y < 0 || y > st.H - GUTTER_BOTTOM) centreOn(sel.z, sel.a);
        }
        redraw();
      },
      /**
       * The chain drawn over the chart: {cells: Set<id>, arrows: [{z0, n0, z1, n1, faint}], dim}
       * or null to take it away.
       */
      setChain(overlay) { st.chain = overlay; redraw(); },
      setHighlight(fn) { st.highlight = fn; redraw(); },
      fit,
      zoom(f) { zoomAt(f, st.W / 2, st.H / 2); },
      centreOn,
      /** Zoom so the given cells fill the view. */
      frame(ids, pad = 2) {
        if (!st.idx || !ids.length) return;
        let n0 = Infinity, n1 = -Infinity, z0 = Infinity, z1 = -Infinity;
        for (const id of ids) {
          const n = st.idx.byId.get(id);
          if (!n) continue;
          n0 = Math.min(n0, n.n); n1 = Math.max(n1, n.n); z0 = Math.min(z0, n.z); z1 = Math.max(z1, n.z);
        }
        if (!Number.isFinite(n0)) return;
        const cols = n1 - n0 + 1 + 2 * pad, rows = z1 - z0 + 1 + 2 * pad;
        st.view.s = Math.min((st.W - GUTTER_LEFT) / cols, (st.H - GUTTER_BOTTOM) / rows, 90);
        st.view.cx = (n0 + n1) / 2 - (GUTTER_LEFT / 2) / st.view.s;
        st.view.cy = (z0 + z1) / 2 - (GUTTER_BOTTOM / 2) / st.view.s;
        clampView();
        redraw();
      },
      redraw,
      resize,
      /** The chart as it is on screen, for saving. */
      toBlob(cb) { canvas.toBlob(cb, 'image/png'); },
      get view() { return { ...st.view }; },
    };
  }

  window.KVOT_ENSDF_CHART = { createChart };
})();
