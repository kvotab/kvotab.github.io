/* ==========================================================================
   PYLAB.HTML: FIGURES WRITTEN AS FILES

   saveas, print and exportgraphics write a figure as SVG, PDF or EPS by
   letting the figure renderer draw into a Recorder instead of a canvas.
   The Recorder has the part of the canvas 2-D interface the renderer uses
   and keeps what is drawn, in the canvas's own (device) coordinates: paths
   filled, stroked or clipping, text with its font, pictures and linear
   gradients. The list is then written as

     SVG  paths, text (any characters) and pictures as embedded PNG
     PDF  a page of paths, text in the standard fonts (Helvetica or
          Courier, Greek letters and mathematical signs from Symbol),
          pictures as images with their transparency, and gradients as
          axial shadings
     EPS  the same in PostScript (LanguageLevel 3). PostScript has no
          transparency: translucent colours are mixed with white, and a
          picture's transparent pixels are left out by a colour key

   BMP and TIFF are written from a canvas's pixels, uncompressed.
   ========================================================================== */
(function (root) {
  'use strict';
  const PL = root.PL || (root.PL = {});

  const TAU = 2 * Math.PI;
  const mul = (m, n) => [m[0] * n[0] + m[2] * n[1], m[1] * n[0] + m[3] * n[1], m[0] * n[2] + m[2] * n[3],
    m[1] * n[2] + m[3] * n[3], m[0] * n[4] + m[2] * n[5] + m[4], m[1] * n[4] + m[3] * n[5] + m[5]];
  const apply = (m, x, y) => [m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]];
  const ok = (...v) => v.every(Number.isFinite);

  /* A canvas for measuring text and reading colours. */
  let scratch = null;
  const scratchCtx = () => scratch || (scratch = document.createElement('canvas').getContext('2d'));

  /* Any CSS colour as [r, g, b, a] in 0..1; null when nothing would show. */
  const colours = new Map();
  function parseColor(s) {
    if (typeof s !== 'string') return null;
    if (colours.has(s)) return colours.get(s);
    const g = scratchCtx();
    g.fillStyle = '#000';
    g.fillStyle = s;
    const v = g.fillStyle;
    let c;
    if (v[0] === '#') c = [1, 3, 5].map((i) => parseInt(v.slice(i, i + 2), 16) / 255).concat(1);
    else {
      const p = (v.match(/\(([^)]*)\)/) || [0, '0,0,0,0'])[1].split(',').map(Number);
      c = [p[0] / 255, p[1] / 255, p[2] / 255, p.length > 3 ? p[3] : 1];
    }
    if (!(c[3] > 0)) c = null;
    colours.set(s, c);
    return c;
  }

  /* A canvas font ("italic bold 13.75px Helvetica, ...") taken apart. */
  function parseFont(s) {
    const m = String(s).match(/^(.*?)([\d.]+)px(?:\/\S+)?\s+(.+)$/);
    if (!m) return { size: 10, bold: false, italic: false, mono: false };
    return { size: parseFloat(m[2]), bold: /\b(bold|bolder|[6-9]00)\b/i.test(m[1]), italic: /\b(italic|oblique)\b/i.test(m[1]),
      mono: /mono|courier|menlo|consol/i.test(m[3]) };
  }

  class Gradient {
    constructor(x0, y0, x1, y1) { this.p = [x0, y0, x1, y1]; this.stops = []; }
    addColorStop(offset, color) { this.stops.push([Math.max(0, Math.min(1, Number(offset) || 0)), parseColor(color) || [0, 0, 0, 0]]); }
  }

  /* ---- the recorder ------------------------------------------------------------------ */
  class Recorder {
    /* w, h: the figure's size in CSS pixels. The transform starts as a
       canvas's does; the caller scales it to the device units it wants. */
    constructor(w, h) {
      this.width = w;
      this.height = h;
      this.ops = [];
      this.path = [];
      this.cur = null;
      this.start = null;
      this.stack = [];
      this.st = { m: [1, 0, 0, 1, 0, 0], fillStyle: '#000', strokeStyle: '#000', lineWidth: 1, lineCap: 'butt', lineJoin: 'miter',
        miterLimit: 10, dash: [], dashOffset: 0, font: '10px sans-serif', textAlign: 'start', textBaseline: 'alphabetic',
        globalAlpha: 1, imageSmoothingEnabled: true };
    }

    get fillStyle() { return this.st.fillStyle; }
    set fillStyle(v) { this.st.fillStyle = v; }
    get strokeStyle() { return this.st.strokeStyle; }
    set strokeStyle(v) { this.st.strokeStyle = v; }
    get lineWidth() { return this.st.lineWidth; }
    set lineWidth(v) { if (v > 0 && Number.isFinite(+v)) this.st.lineWidth = +v; }
    get lineCap() { return this.st.lineCap; }
    set lineCap(v) { if (['butt', 'round', 'square'].includes(v)) this.st.lineCap = v; }
    get lineJoin() { return this.st.lineJoin; }
    set lineJoin(v) { if (['miter', 'round', 'bevel'].includes(v)) this.st.lineJoin = v; }
    get miterLimit() { return this.st.miterLimit; }
    set miterLimit(v) { if (v > 0 && Number.isFinite(+v)) this.st.miterLimit = +v; }
    get lineDashOffset() { return this.st.dashOffset; }
    set lineDashOffset(v) { if (Number.isFinite(+v)) this.st.dashOffset = +v; }
    get font() { return this.st.font; }
    set font(v) { this.st.font = String(v); }
    get textAlign() { return this.st.textAlign; }
    set textAlign(v) { this.st.textAlign = v; }
    get textBaseline() { return this.st.textBaseline; }
    set textBaseline(v) { this.st.textBaseline = v; }
    get globalAlpha() { return this.st.globalAlpha; }
    set globalAlpha(v) { if (v >= 0 && v <= 1) this.st.globalAlpha = +v; }
    get imageSmoothingEnabled() { return this.st.imageSmoothingEnabled; }
    set imageSmoothingEnabled(v) { this.st.imageSmoothingEnabled = !!v; }

    save() { this.stack.push({ ...this.st, dash: this.st.dash.slice() }); this.ops.push({ op: 'save' }); }
    restore() { if (!this.stack.length) return; this.st = this.stack.pop(); this.ops.push({ op: 'restore' }); }

    getTransform() { const [a, b, c, d, e, f] = this.st.m; return { a, b, c, d, e, f }; }
    setTransform(a, b, c, d, e, f) {
      if (a && typeof a === 'object') ({ a, b, c, d, e, f } = a);
      if (ok(a, b, c, d, e, f)) this.st.m = [a, b, c, d, e, f];
    }
    resetTransform() { this.st.m = [1, 0, 0, 1, 0, 0]; }
    transform(a, b, c, d, e, f) { if (ok(a, b, c, d, e, f)) this.st.m = mul(this.st.m, [a, b, c, d, e, f]); }
    translate(x, y) { this.transform(1, 0, 0, 1, x, y); }
    scale(x, y) { this.transform(x, 0, 0, y, 0, 0); }
    rotate(t) { this.transform(Math.cos(t), Math.sin(t), -Math.sin(t), Math.cos(t), 0, 0); }

    /* Paths are kept in device coordinates, arcs as cubic curves. */
    beginPath() { this.path = []; this.cur = this.start = null; }
    moveTo(x, y) {
      if (!ok(x, y)) return;
      const p = apply(this.st.m, x, y);
      this.path.push(['M', p[0], p[1]]);
      this.cur = this.start = p;
    }
    lineTo(x, y) {
      if (!ok(x, y)) return;
      if (!this.cur) { this.moveTo(x, y); return; }
      const p = apply(this.st.m, x, y);
      this.path.push(['L', p[0], p[1]]);
      this.cur = p;
    }
    bezierCurveTo(x1, y1, x2, y2, x, y) {
      if (!ok(x1, y1, x2, y2, x, y)) return;
      if (!this.cur) this.moveTo(x1, y1);
      const a = apply(this.st.m, x1, y1), b = apply(this.st.m, x2, y2), p = apply(this.st.m, x, y);
      this.path.push(['C', a[0], a[1], b[0], b[1], p[0], p[1]]);
      this.cur = p;
    }
    quadraticCurveTo(qx, qy, x, y) {
      if (!ok(qx, qy, x, y)) return;
      if (!this.cur) this.moveTo(qx, qy);
      const q = apply(this.st.m, qx, qy), p = apply(this.st.m, x, y), o = this.cur;
      this.path.push(['C', o[0] + 2 / 3 * (q[0] - o[0]), o[1] + 2 / 3 * (q[1] - o[1]), p[0] + 2 / 3 * (q[0] - p[0]),
        p[1] + 2 / 3 * (q[1] - p[1]), p[0], p[1]]);
      this.cur = p;
    }
    closePath() { if (this.cur) { this.path.push(['Z']); this.cur = this.start; } }
    rect(x, y, w, h) {
      if (!ok(x, y, w, h)) return;
      this.moveTo(x, y); this.lineTo(x + w, y); this.lineTo(x + w, y + h); this.lineTo(x, y + h); this.closePath();
    }
    arc(x, y, r, a0, a1, ccw = false) {
      if (!ok(x, y, r, a0, a1) || r < 0) return;
      let sweep;
      if (!ccw) sweep = a1 - a0 >= TAU ? TAU : ((a1 - a0) % TAU + TAU) % TAU;
      else sweep = a0 - a1 >= TAU ? -TAU : -(((a0 - a1) % TAU + TAU) % TAU);
      const sx = x + r * Math.cos(a0), sy = y + r * Math.sin(a0);
      if (this.cur) this.lineTo(sx, sy); else this.moveTo(sx, sy);
      if (!sweep || !r) return;
      // quarter turns at most, each a cubic curve
      const n = Math.ceil(Math.abs(sweep) / (Math.PI / 2) - 1e-9);
      const d = sweep / n, k = 4 / 3 * Math.tan(d / 4);
      for (let i = 0, t = a0; i < n; i++, t += d) {
        const c0 = Math.cos(t), s0 = Math.sin(t), c1 = Math.cos(t + d), s1 = Math.sin(t + d);
        const p1 = apply(this.st.m, x + r * (c0 - k * s0), y + r * (s0 + k * c0));
        const p2 = apply(this.st.m, x + r * (c1 + k * s1), y + r * (s1 - k * c1));
        const p3 = apply(this.st.m, x + r * c1, y + r * s1);
        this.path.push(['C', p1[0], p1[1], p2[0], p2[1], p3[0], p3[1]]);
        this.cur = p3;
      }
    }
    ellipse(x, y, rx, ry, rot, a0, a1, ccw = false) {
      if (!ok(x, y, rx, ry, rot, a0, a1) || rx < 0 || ry < 0) return;
      const m = this.st.m;
      this.translate(x, y);
      this.rotate(rot);
      this.scale(rx || 1e-9, ry || 1e-9);
      this.arc(0, 0, 1, a0, a1, ccw);
      this.st.m = m;
    }

    /* What a fill or stroke paints with: a colour, or a gradient in device coordinates. */
    paint(style) {
      const ga = this.st.globalAlpha;
      if (style instanceof Gradient) {
        if (!style.stops.length) return null;
        const a = apply(this.st.m, style.p[0], style.p[1]), b = apply(this.st.m, style.p[2], style.p[3]);
        const stops = style.stops.slice().sort((u, v) => u[0] - v[0]).map(([o, c]) => [o, [c[0], c[1], c[2], c[3] * ga]]);
        return { grad: [a[0], a[1], b[0], b[1]], stops };
      }
      const c = parseColor(style);
      return c && c[3] * ga > 0 ? { color: [c[0], c[1], c[2], c[3] * ga] } : null;
    }
    fill(rule) {
      const paint = this.paint(this.st.fillStyle);
      if (paint && this.path.length) this.ops.push({ op: 'fill', path: this.path.slice(), paint, evenodd: rule === 'evenodd' });
    }
    stroke() {
      const paint = this.paint(this.st.strokeStyle);
      if (!paint || !this.path.length) return;
      const m = this.st.m, s = Math.sqrt(Math.abs(m[0] * m[3] - m[1] * m[2])) || 1;
      this.ops.push({ op: 'stroke', path: this.path.slice(), paint, width: this.st.lineWidth * s, cap: this.st.lineCap,
        join: this.st.lineJoin, miter: this.st.miterLimit, dash: this.st.dash.map((v) => v * s), dashOffset: this.st.dashOffset * s });
    }
    clip(rule) { this.ops.push({ op: 'clip', path: this.path.slice(), evenodd: rule === 'evenodd' }); }
    fillRect(x, y, w, h) { this.alone(() => { this.rect(x, y, w, h); this.fill(); }); }
    strokeRect(x, y, w, h) { this.alone(() => { this.rect(x, y, w, h); this.stroke(); }); }
    clearRect() { /* the figure's background is painted first: nothing is cleared to show through */ }
    alone(f) {
      const kept = [this.path, this.cur, this.start];
      this.beginPath();
      f();
      [this.path, this.cur, this.start] = kept;
    }
    setLineDash(a) {
      const v = Array.from(a || [], Number);
      if (v.some((x) => !Number.isFinite(x) || x < 0)) return;
      this.st.dash = v.length % 2 ? v.concat(v) : v;
    }
    getLineDash() { return this.st.dash.slice(); }

    measureText(t) { const g = scratchCtx(); g.font = this.st.font; return g.measureText(String(t)); }
    fillText(text, x, y) {
      const paint = this.paint(this.st.fillStyle);
      text = String(text ?? '').replace(/[\t\n\r\f\v]/g, ' ');
      if (!paint || !text || !ok(x, y)) return;
      const font = parseFont(this.st.font);
      const al = this.st.textAlign, bl = this.st.textBaseline;
      let dx = 0, dy = 0;
      if (al === 'center' || al === 'right' || al === 'end') {
        const w = this.measureText(text).width;
        dx = al === 'center' ? -w / 2 : -w;
      }
      if (bl === 'top' || bl === 'hanging') dy = font.size * 0.8;
      else if (bl === 'middle') dy = font.size * 0.32;
      else if (bl === 'bottom' || bl === 'ideographic') dy = -font.size * 0.22;
      this.ops.push({ op: 'text', text, font, m: mul(this.st.m, [1, 0, 0, 1, x + dx, y + dy]), paint });
    }
    strokeText() { /* not used by the figures */ }
    drawImage(img, ...a) {
      let sx = 0, sy = 0, sw = img.width, sh = img.height, dx, dy, dw, dh;
      if (a.length === 2) { [dx, dy] = a; dw = sw; dh = sh; } else if (a.length === 4) [dx, dy, dw, dh] = a;
      else [sx, sy, sw, sh, dx, dy, dw, dh] = a;
      if (!(sw > 0 && sh > 0) || !ok(dx, dy, dw, dh)) return;
      this.ops.push({ op: 'image', img, sx, sy, sw, sh, m: mul(this.st.m, [dw / sw, 0, 0, dh / sh, dx, dy]),
        smooth: this.st.imageSmoothingEnabled, alpha: this.st.globalAlpha });
    }
    createLinearGradient(x0, y0, x1, y1) { return new Gradient(x0, y0, x1, y1); }
  }

  /* ---- shared pieces ------------------------------------------------------------------- */
  /* A number as the files write it: at most d decimals, never an exponent. */
  const num = (v, d = 2) => {
    if (!Number.isFinite(+v)) return '0';
    const r = +Math.max(-1e9, Math.min(1e9, +v)).toFixed(d);
    return String(Object.is(r, -0) ? 0 : r);
  };
  const enc = (s) => { const u = new Uint8Array(s.length); for (let i = 0; i < s.length; i++) u[i] = s.charCodeAt(i) & 255; return u; };
  const concatBytes = (parts) => {
    const n = parts.reduce((t, p) => t + p.length, 0);
    const out = new Uint8Array(n);
    let k = 0;
    for (const p of parts) { out.set(p, k); k += p.length; }
    return out;
  };
  function base64(u8) {
    let s = '';
    for (let i = 0; i < u8.length; i += 0x8000) s += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000));
    return btoa(s);
  }
  /* zlib-wrapped deflate (what PDF and PostScript call FlateDecode); null where the browser has none. */
  async function deflate(u8) {
    if (typeof CompressionStream !== 'function') return null;
    try {
      const stream = new Blob([u8]).stream().pipeThrough(new CompressionStream('deflate'));
      return new Uint8Array(await new Response(stream).arrayBuffer());
    } catch (e) {
      return null;
    }
  }

  /* An image's pixels, as drawn from its source. */
  function pixelsOf(o) {
    const w = Math.max(1, Math.round(o.sw)), h = Math.max(1, Math.round(o.sh));
    const c = document.createElement('canvas');
    c.width = w;
    c.height = h;
    const g = c.getContext('2d');
    g.drawImage(o.img, o.sx, o.sy, o.sw, o.sh, 0, 0, w, h);
    return { canvas: c, w, h, data: g.getImageData(0, 0, w, h).data };
  }
  /* The matrix that maps the unit square onto an image's place, its first row at the top. */
  const imageMatrix = (o) => mul(o.m, [o.sw, 0, 0, -o.sh, 0, o.sh]);

  /* The stops of a gradient from 0 to 1, as a PDF or PostScript function. */
  function gradientFunction(stops, rgbOf) {
    const s = [];
    for (const [o, c] of stops) {
      if (s.length && o <= s[s.length - 1][0] + 1e-6) s[s.length - 1] = [s[s.length - 1][0], c];   // a jump: the later colour
      else s.push([o, c]);
    }
    if (s[0][0] > 0) s.unshift([0, s[0][1]]);
    if (s[s.length - 1][0] < 1) s.push([1, s[s.length - 1][1]]);
    if (s.length === 1) s.push([1, s[0][1]]);
    const t2 = (a, b) => `<< /FunctionType 2 /Domain [0 1] /C0 [${rgbOf(a).map((v) => num(v, 4)).join(' ')}] /C1 [${rgbOf(b).map((v) => num(v, 4)).join(' ')}] /N 1 >>`;
    if (s.length === 2) return t2(s[0][1], s[1][1]);
    const fns = [], bounds = [];
    for (let i = 0; i + 1 < s.length; i++) {
      fns.push(t2(s[i][1], s[i + 1][1]));
      if (i > 0) bounds.push(num(s[i][0], 6));
    }
    return `<< /FunctionType 3 /Domain [0 1] /Functions [${fns.join(' ')}] /Bounds [${bounds.join(' ')}] /Encode [${fns.map(() => '0 1').join(' ')}] >>`;
  }

  /* ---- text in the standard fonts (PDF and EPS) ------------------------------------- */
  // Windows-1252 (PDF's WinAnsiEncoding) beyond Latin-1
  const CP1252 = new Map([[0x20ac, 0x80], [0x201a, 0x82], [0x0192, 0x83], [0x201e, 0x84], [0x2026, 0x85], [0x2020, 0x86],
    [0x2021, 0x87], [0x02c6, 0x88], [0x2030, 0x89], [0x0160, 0x8a], [0x2039, 0x8b], [0x0152, 0x8c], [0x017d, 0x8e], [0x2018, 0x91],
    [0x2019, 0x92], [0x201c, 0x93], [0x201d, 0x94], [0x2022, 0x95], [0x2013, 0x96], [0x2014, 0x97], [0x02dc, 0x98], [0x2122, 0x99],
    [0x0161, 0x9a], [0x203a, 0x9b], [0x0153, 0x9c], [0x017e, 0x9e], [0x0178, 0x9f]]);
  // the Symbol font's codes: Greek letters and mathematical signs
  const SYMBOL = (() => {
    const m = new Map();
    [...'ΑΒΧΔΕΦΓΗΙϑΚΛΜΝΟΠΘΡΣΤΥςΩΞΨΖ'].forEach((ch, i) => m.set(ch.codePointAt(0), 0x41 + i));
    [...'αβχδεφγηιϕκλμνοπθρστυϖωξψζ'].forEach((ch, i) => m.set(ch.codePointAt(0), 0x61 + i));
    const more = {
      '∀': 0x22, '∃': 0x24, '∋': 0x27, '∗': 0x2a, '−': 0x2d, '≅': 0x40, '∴': 0x5c, '⊥': 0x5e, '∼': 0x7e, 'ϒ': 0xa1, '′': 0xa2,
      '≤': 0xa3, '⁄': 0xa4, '∞': 0xa5, 'ƒ': 0xa6, '♣': 0xa7, '♦': 0xa8, '♥': 0xa9, '♠': 0xaa, '↔': 0xab, '←': 0xac, '↑': 0xad,
      '→': 0xae, '↓': 0xaf, '″': 0xb2, '≥': 0xb3, '∝': 0xb5, '∂': 0xb6, '•': 0xb7, '≠': 0xb9, '≡': 0xba, '≈': 0xbb, '…': 0xbc,
      '↵': 0xbf, 'ℵ': 0xc0, 'ℑ': 0xc1, 'ℜ': 0xc2, '℘': 0xc3, '⊗': 0xc4, '⊕': 0xc5, '∅': 0xc6, '∩': 0xc7, '∪': 0xc8, '⊃': 0xc9,
      '⊇': 0xca, '⊄': 0xcb, '⊂': 0xcc, '⊆': 0xcd, '∈': 0xce, '∉': 0xcf, '∠': 0xd0, '∇': 0xd1, '∏': 0xd5, '√': 0xd6, '⋅': 0xd7,
      '∧': 0xd9, '∨': 0xda, '⇔': 0xdb, '⇐': 0xdc, '⇑': 0xdd, '⇒': 0xde, '⇓': 0xdf, '◊': 0xe0, '〈': 0xe1, '⟨': 0xe1, '™': 0xe4,
      '∑': 0xe5, '〉': 0xf1, '⟩': 0xf1, '∫': 0xf2, 'Ω': 0x57, '∆': 0x44, 'ϵ': 0x65,
    };
    for (const [ch, b] of Object.entries(more)) m.set(ch.codePointAt(0), b);
    return m;
  })();
  // what stands in for the characters neither font has
  const FALLBACK = { '∓': '-+', '⋯': '...', '⌊': '[', '⌋': ']', '⌈': '[', '⌉': ']', '“': '"', '”': '"', '„': '"', '–': '-',
    '—': '-', '‚': ',', '‹': '<', '›': '>', '€': 'EUR' };

  /* A run of text as pieces in one font each: [{sym, bytes}]. latin(cp) is the
     main font's byte for a character (null when it has none). */
  function pieces(text, latin) {
    const out = [];
    const push = (sym, b) => {
      const last = out[out.length - 1];
      if (last && last.sym === sym) last.bytes.push(b);
      else out.push({ sym, bytes: [b] });
    };
    for (const ch of text) {
      const cp = ch.codePointAt(0);
      const b = latin(cp);
      if (b != null) { push(false, b); continue; }
      const s = SYMBOL.get(cp);
      if (s != null) { push(true, s); continue; }
      const f = FALLBACK[ch];
      if (f) for (const c of f) push(false, latin(c.charCodeAt(0)) ?? 0x3f);
      else push(false, 0x3f);
    }
    return out;
  }
  const isLatin1 = (cp) => (cp >= 0x20 && cp < 0x7f) || (cp >= 0xa0 && cp <= 0xff);
  const winAnsi = (cp) => (isLatin1(cp) ? cp : CP1252.get(cp) ?? null);
  // PostScript's ISOLatin1Encoding: Latin-1, with the quotes at 0x60 and 0x27 and its minus at 0x2d
  const isoLatin1 = (cp) => (cp === 0x2018 ? 0x60 : cp === 0x2019 ? 0x27 : cp === 0x2212 ? 0x2d : isLatin1(cp) ? cp : null);
  const STD = { sans: ['Helvetica', 'Helvetica-Bold', 'Helvetica-Oblique', 'Helvetica-BoldOblique'],
    mono: ['Courier', 'Courier-Bold', 'Courier-Oblique', 'Courier-BoldOblique'] };
  const stdFont = (f) => STD[f.mono ? 'mono' : 'sans'][(f.bold ? 1 : 0) + (f.italic ? 2 : 0)];
  const textColor = (p) => p.color || p.stops[0][1];

  /* ---- SVG ------------------------------------------------------------------------------ */
  const xmlText = (s) => String(s).replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\ufffe\uffff]/g, '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  const hex2 = (v) => Math.round(Math.max(0, Math.min(1, v)) * 255).toString(16).padStart(2, '0');
  const svgColor = (c) => `#${hex2(c[0])}${hex2(c[1])}${hex2(c[2])}`;
  const svgPath = (path) => path.map((g) => (g[0] === 'Z' ? 'Z' : g[0] + g.slice(1).map((v) => num(v)).join(' '))).join('');

  function toSVG(rec, unit, title) {
    const defs = [], body = [];
    const open = [0];          // the clip groups opened since each save
    let n = 0;
    const paint = (p, what) => {
      if (p.color) return `${what}="${svgColor(p.color)}"${p.color[3] < 1 ? ` ${what}-opacity="${num(p.color[3], 3)}"` : ''}`;
      const id = `g${++n}`;
      const [x1, y1, x2, y2] = p.grad;
      defs.push(`<linearGradient id="${id}" gradientUnits="userSpaceOnUse" x1="${num(x1)}" y1="${num(y1)}" x2="${num(x2)}" y2="${num(y2)}">`
        + p.stops.map(([o, c]) => `<stop offset="${num(o, 4)}" stop-color="${svgColor(c)}"${c[3] < 1 ? ` stop-opacity="${num(c[3], 3)}"` : ''}/>`).join('')
        + '</linearGradient>');
      return `${what}="url(#${id})"`;
    };
    for (const o of rec.ops) {
      if (o.op === 'save') open.push(0);
      else if (o.op === 'restore') { if (open.length > 1) body.push('</g>'.repeat(open.pop())); }
      else if (o.op === 'clip') {
        const id = `c${++n}`;
        defs.push(`<clipPath id="${id}"><path d="${svgPath(o.path)}"${o.evenodd ? ' clip-rule="evenodd"' : ''}/></clipPath>`);
        body.push(`<g clip-path="url(#${id})">`);
        open[open.length - 1]++;
      } else if (o.op === 'fill') {
        body.push(`<path d="${svgPath(o.path)}" ${paint(o.paint, 'fill')}${o.evenodd ? ' fill-rule="evenodd"' : ''}/>`);
      } else if (o.op === 'stroke') {
        body.push(`<path d="${svgPath(o.path)}" fill="none" ${paint(o.paint, 'stroke')} stroke-width="${num(o.width, 3)}"`
          + (o.cap !== 'butt' ? ` stroke-linecap="${o.cap}"` : '') + (o.join !== 'miter' ? ` stroke-linejoin="${o.join}"` : ` stroke-miterlimit="${num(o.miter)}"`)
          + (o.dash.length ? ` stroke-dasharray="${o.dash.map((v) => num(v, 3)).join(' ')}"` + (o.dashOffset ? ` stroke-dashoffset="${num(o.dashOffset, 3)}"` : '') : '')
          + '/>');
      } else if (o.op === 'text') {
        const f = o.font;
        body.push(`<text transform="matrix(${o.m.map((v) => num(v, 4)).join(' ')})" font-family="${f.mono ? 'Courier New, Courier, monospace' : 'Helvetica, Arial, sans-serif'}"`
          + ` font-size="${num(f.size, 3)}"${f.bold ? ' font-weight="bold"' : ''}${f.italic ? ' font-style="italic"' : ''} ${paint(o.paint, 'fill')}`
          + ` xml:space="preserve">${xmlText(o.text)}</text>`);
      } else if (o.op === 'image') {
        const px = pixelsOf(o);
        const m = mul(o.m, [o.sw / px.w, 0, 0, o.sh / px.h, 0, 0]);
        body.push(`<image width="${px.w}" height="${px.h}" preserveAspectRatio="none" transform="matrix(${m.map((v) => num(v, 4)).join(' ')})"`
          + (o.smooth ? '' : ' image-rendering="optimizeSpeed" style="image-rendering:pixelated"') + (o.alpha < 1 ? ` opacity="${num(o.alpha, 3)}"` : '')
          + ` xlink:href="${px.canvas.toDataURL('image/png')}"/>`);
      }
    }
    while (open.length) { const k = open.pop(); if (k) body.push('</g>'.repeat(k)); }
    const W = rec.width, H = rec.height;
    return '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
      + `<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" version="1.1" width="${num(W)}" height="${num(H)}" viewBox="0 0 ${num(W * unit)} ${num(H * unit)}">\n`
      + (title ? `<title>${xmlText(title)}</title>\n` : '')
      + (defs.length ? `<defs>\n${defs.join('\n')}\n</defs>\n` : '')
      + body.join('\n') + '\n</svg>\n';
  }

  /* ---- PDF ------------------------------------------------------------------------------ */
  const pdfPath = (path) => {
    let s = '';
    let drawn = false;
    for (const g of path) {
      if (g[0] === 'M') s += `${num(g[1])} ${num(g[2])} m `;
      else if (g[0] === 'L') { s += `${num(g[1])} ${num(g[2])} l `; drawn = true; }
      else if (g[0] === 'C') { s += `${g.slice(1).map((v) => num(v)).join(' ')} c `; drawn = true; }
      else s += 'h ';
    }
    return drawn ? s : '';
  };
  const hexBytes = (bytes) => bytes.map((b) => b.toString(16).padStart(2, '0')).join('');
  /* A PDF text string: plain ASCII as such, anything else as UTF-16. */
  function pdfString(s) {
    if (/^[\x20-\x7e]*$/.test(s)) return `(${s.replace(/[\\()]/g, '\\$&')})`;
    let h = 'FEFF';
    for (let i = 0; i < s.length; i++) h += s.charCodeAt(i).toString(16).padStart(4, '0');
    return `<${h}>`;
  }

  async function toPDF(rec, unit, title) {
    const k = 0.75 / unit;                       // device units to points (96 px make 72 pt)
    const PW = rec.width * 0.75, PH = rec.height * 0.75;
    const B = [k, 0, 0, -k, 0, PH];              // device coordinates to the page's
    const objs = [];                             // the objects' bodies, by number - 1
    const add = (body) => { objs.push(body); return objs.length; };
    const ref = (n) => `${n} 0 R`;
    const stream = async (dict, bytes, compress = true) => {
      const z = compress ? await deflate(bytes) : null;
      const data = z || bytes;
      return concatBytes([enc(`<< ${dict}${z ? ' /Filter /FlateDecode' : ''} /Length ${data.length} >>\nstream\n`), data, enc('\nendstream')]);
    };
    const fonts = new Map(), states = new Map(), images = [], patterns = [];
    const fontRes = (name) => {
      if (!fonts.has(name)) fonts.set(name, `F${fonts.size + 1}`);
      return fonts.get(name);
    };
    const alphaRes = (a) => {
      const key = num(a, 3);
      if (!states.has(key)) states.set(key, `G${states.size + 1}`);
      return states.get(key);
    };
    const withAlpha = (a, s) => (a < 0.999 ? `q /${alphaRes(a)} gs ${s} Q` : s);
    const rgb = (c) => c.slice(0, 3).map((v) => num(v, 4)).join(' ');
    const paintOp = (p, stroke) => {
      if (p.color) return `${rgb(p.color)} ${stroke ? 'RG' : 'rg'}`;
      const name = `P${patterns.length + 1}`;
      patterns.push({ name, p });
      return `/Pattern ${stroke ? 'CS' : 'cs'} /${name} ${stroke ? 'SCN' : 'scn'}`;
    };
    const alphaOf = (p) => (p.color ? p.color[3] : p.stops[0][1][3]);
    const CAP = { butt: 0, round: 1, square: 2 }, JOIN = { miter: 0, round: 1, bevel: 2 };

    const out = [`q ${B.map((v) => num(v, 6)).join(' ')} cm`];
    let depth = 0;
    for (const o of rec.ops) {
      if (o.op === 'save') { out.push('q'); depth++; } else if (o.op === 'restore') { if (depth > 0) { out.push('Q'); depth--; } } else if (o.op === 'clip') out.push(`${pdfPath(o.path) || '0 0 m 0 0 l h '}W${o.evenodd ? '*' : ''} n`);
      else if (o.op === 'fill') {
        const p = pdfPath(o.path);
        if (p) out.push(withAlpha(alphaOf(o.paint), `${paintOp(o.paint, false)} ${p}f${o.evenodd ? '*' : ''}`));
      } else if (o.op === 'stroke') {
        const p = pdfPath(o.path);
        if (p) {
          out.push(withAlpha(alphaOf(o.paint), `${paintOp(o.paint, true)} ${num(o.width, 3)} w ${CAP[o.cap] ?? 0} J ${JOIN[o.join] ?? 0} j ${num(o.miter)} M`
            + ` [${o.dash.map((v) => num(v, 3)).join(' ')}] ${num(o.dashOffset, 3)} d ${p}S`));
        }
      } else if (o.op === 'text') {
        const m = o.m;
        const tm = [m[0], m[1], -m[2], -m[3], m[4], m[5]].map((v) => num(v, 4)).join(' ');
        const main = stdFont(o.font);
        let s = `${rgb(textColor(o.paint))} rg BT ${tm} Tm`;
        for (const g of pieces(o.text, winAnsi)) s += ` /${fontRes(g.sym ? 'Symbol' : main)} ${num(o.font.size, 3)} Tf <${hexBytes(g.bytes)}> Tj`;
        out.push(withAlpha(alphaOf(o.paint), `${s} ET`));
      } else if (o.op === 'image') {
        const name = `Im${images.length + 1}`;
        images.push({ name, o });
        out.push(withAlpha(o.alpha, `q ${imageMatrix(o).map((v) => num(v, 4)).join(' ')} cm /${name} Do Q`));
      }
    }
    while (depth-- > 0) out.push('Q');
    out.push('Q');

    // the objects: catalog, pages, page, content, then the resources
    const catalog = add(''), pages = add(''), page = add('');
    const content = add(await stream('', enc(out.join('\n'))));
    const fontDict = [...fonts].map(([name, res]) => `/${res} ${ref(add(name === 'Symbol' ? '<< /Type /Font /Subtype /Type1 /BaseFont /Symbol >>'
      : `<< /Type /Font /Subtype /Type1 /BaseFont /${name} /Encoding /WinAnsiEncoding >>`))}`).join(' ');
    const gsDict = [...states].map(([a, res]) => `/${res} ${ref(add(`<< /Type /ExtGState /ca ${a} /CA ${a} >>`))}`).join(' ');
    const xobj = [];
    for (const { name, o } of images) {
      const { w, h, data } = pixelsOf(o);
      const rgbBytes = new Uint8Array(w * h * 3), alpha = new Uint8Array(w * h);
      let opaque = true;
      for (let i = 0, j = 0; i < w * h; i++, j += 4) {
        rgbBytes[i * 3] = data[j]; rgbBytes[i * 3 + 1] = data[j + 1]; rgbBytes[i * 3 + 2] = data[j + 2];
        alpha[i] = data[j + 3];
        if (data[j + 3] !== 255) opaque = false;
      }
      const head = `/Type /XObject /Subtype /Image /Width ${w} /Height ${h} /BitsPerComponent 8${o.smooth ? ' /Interpolate true' : ''}`;
      const mask = opaque ? '' : ` /SMask ${ref(add(await stream(`${head} /ColorSpace /DeviceGray`, alpha)))}`;
      xobj.push(`/${name} ${ref(add(await stream(`${head} /ColorSpace /DeviceRGB${mask}`, rgbBytes)))}`);
    }
    const patDict = patterns.map(({ name, p }) => `/${name} ${ref(add(`<< /Type /Pattern /PatternType 2 /Matrix [${B.map((v) => num(v, 6)).join(' ')}]`
      + ` /Shading << /ShadingType 2 /ColorSpace /DeviceRGB /Coords [${p.grad.map((v) => num(v)).join(' ')}]`
      + ` /Function ${gradientFunction(p.stops, (c) => c.slice(0, 3))} /Extend [true true] >> >>`))}`).join(' ');
    const res = `<< /ProcSet [/PDF /Text /ImageB /ImageC]${fontDict ? ` /Font << ${fontDict} >>` : ''}${gsDict ? ` /ExtGState << ${gsDict} >>` : ''}`
      + `${xobj.length ? ` /XObject << ${xobj.join(' ')} >>` : ''}${patDict ? ` /Pattern << ${patDict} >>` : ''} >>`;
    objs[catalog - 1] = `<< /Type /Catalog /Pages ${ref(pages)} >>`;
    objs[pages - 1] = `<< /Type /Pages /Kids [${ref(page)}] /Count 1 >>`;
    objs[page - 1] = `<< /Type /Page /Parent ${ref(pages)} /MediaBox [0 0 ${num(PW)} ${num(PH)}] /Resources ${res} /Contents ${ref(content)} >>`;
    const d = new Date();
    const stamp = `D:${d.getUTCFullYear()}${[d.getUTCMonth() + 1, d.getUTCDate(), d.getUTCHours(), d.getUTCMinutes(), d.getUTCSeconds()].map((v) => String(v).padStart(2, '0')).join('')}Z`;
    const info = add(`<< /Producer (PyLAB) /Creator (PyLAB)${title ? ` /Title ${pdfString(title)}` : ''} /CreationDate (${stamp}) >>`);

    const chunks = [enc('%PDF-1.4\n%\xe2\xe3\xcf\xd3\n')];
    let off = chunks[0].length;
    const offsets = [];
    objs.forEach((body, i) => {
      offsets.push(off);
      const part = concatBytes([enc(`${i + 1} 0 obj\n`), typeof body === 'string' ? enc(body) : body, enc('\nendobj\n')]);
      chunks.push(part);
      off += part.length;
    });
    chunks.push(enc(`xref\n0 ${objs.length + 1}\n0000000000 65535 f \n${offsets.map((o) => `${String(o).padStart(10, '0')} 00000 n \n`).join('')}`
      + `trailer\n<< /Size ${objs.length + 1} /Root ${ref(catalog)} /Info ${ref(info)} >>\nstartxref\n${off}\n%%EOF\n`));
    return concatBytes(chunks);
  }

  /* ---- EPS ------------------------------------------------------------------------------ */
  const psPath = (path) => {
    let s = '';
    let drawn = false;
    for (const g of path) {
      if (g[0] === 'M') s += `${num(g[1])} ${num(g[2])} m `;
      else if (g[0] === 'L') { s += `${num(g[1])} ${num(g[2])} l `; drawn = true; }
      else if (g[0] === 'C') { s += `${g.slice(1).map((v) => num(v)).join(' ')} c `; drawn = true; }
      else s += 'h ';
    }
    return drawn ? s : '';
  };
  const psString = (bytes) => `(${bytes.map((b) => (b === 0x28 || b === 0x29 || b === 0x5c ? `\\${String.fromCharCode(b)}`
    : b >= 0x20 && b < 0x7f ? String.fromCharCode(b) : `\\${b.toString(8).padStart(3, '0')}`)).join('')})`;
  /* A line of PostScript broken at spaces outside strings, so that no line is
     longer than the 255 characters the DSC allows. */
  function psWrap(line, max = 200) {
    if (line.length <= max) return line;
    const out = [];
    let start = 0, lastSpace = -1, depth = 0;
    for (let i = 0; i < line.length; i++) {
      const ch = line[i];
      if (ch === '\\' && depth) { i++; continue; }
      if (ch === '(') depth++;
      else if (ch === ')' && depth) depth--;
      else if (ch === ' ' && !depth) lastSpace = i;
      if (i - start >= max && lastSpace > start) {
        out.push(line.slice(start, lastSpace));
        start = lastSpace + 1;
        lastSpace = -1;
      }
    }
    out.push(line.slice(start));
    return out.join('\n');
  }

  /* A colour over white: what PostScript, which has no transparency, can show of it. */
  const overWhite = (c) => c.slice(0, 3).map((v) => (c[3] < 1 ? c[3] * v + 1 - c[3] : v));
  function ascii85(u8) {
    let out = '';
    let line = 0;
    for (let i = 0; i < u8.length; i += 4) {
      const n = Math.min(4, u8.length - i);
      let v = 0;
      for (let j = 0; j < 4; j++) v = v * 256 + (j < n ? u8[i + j] : 0);
      let g;
      if (n === 4 && v === 0) g = 'z';
      else {
        const c = [];
        for (let j = 4; j >= 0; j--) { c[j] = String.fromCharCode(33 + (v % 85)); v = Math.floor(v / 85); }
        g = c.slice(0, n + 1).join('');
      }
      out += g;
      line += g.length;
      if (line >= 75) { out += '\n'; line = 0; }
    }
    return out;
  }

  async function psImage(o) {
    const { w, h, data } = pixelsOf(o);
    const rgbBytes = new Uint8Array(w * h * 3);
    const clear = [];
    for (let i = 0, j = 0; i < w * h; i++, j += 4) {
      const a = data[j + 3] / 255;
      if (a === 0) { clear.push(i); continue; }
      for (let q = 0; q < 3; q++) rgbBytes[i * 3 + q] = Math.round(a < 1 ? data[j + q] * a + 255 * (1 - a) : data[j + q]);
    }
    // transparent pixels take a colour the picture does not use, which the image leaves out
    let key = null;
    if (clear.length) {
      const used = new Set();
      for (let i = 0; i < w * h; i++) used.add((rgbBytes[i * 3] << 16) | (rgbBytes[i * 3 + 1] << 8) | rgbBytes[i * 3 + 2]);
      let k = 0x01fe02;
      while (used.has(k)) k = (k + 0x010307) & 0xffffff;
      key = [(k >> 16) & 255, (k >> 8) & 255, k & 255];
      for (const i of clear) { rgbBytes[i * 3] = key[0]; rgbBytes[i * 3 + 1] = key[1]; rgbBytes[i * 3 + 2] = key[2]; }
    }
    const z = await deflate(rgbBytes);
    const src = z ? 'currentfile /ASCII85Decode filter /FlateDecode filter' : 'currentfile /ASCIIHexDecode filter';
    const body = z ? `${ascii85(z)}~>` : `${hexBytes(Array.from(rgbBytes)).replace(/(.{78})/g, '$1\n')}>`;
    return `/DeviceRGB setcolorspace\n<< /ImageType ${key ? 4 : 1} /Width ${w} /Height ${h} /BitsPerComponent 8 /Decode [0 1 0 1 0 1]`
      + ` /ImageMatrix [${w} 0 0 ${-h} 0 ${h}] /DataSource ${src}${o.smooth ? ' /Interpolate true' : ''}`
      + `${key ? ` /MaskColor [${key[0]} ${key[0]} ${key[1]} ${key[1]} ${key[2]} ${key[2]}]` : ''} >> image\n${body}`;
  }

  async function toEPS(rec, unit, title) {
    const k = 0.75 / unit;
    const PW = rec.width * 0.75, PH = rec.height * 0.75;
    const fonts = new Set();
    const CAP = { butt: 0, round: 1, square: 2 }, JOIN = { miter: 0, round: 1, bevel: 2 };
    const rgb = (c) => overWhite(c).map((v) => num(v, 4)).join(' ');
    const shading = (p) => `<< /ShadingType 2 /ColorSpace /DeviceRGB /Coords [${p.grad.map((v) => num(v)).join(' ')}]`
      + ` /Function ${gradientFunction(p.stops, overWhite)} /Extend [true true] >> shfill`;
    const lineState = (o) => `${num(o.width, 3)} setlinewidth ${CAP[o.cap] ?? 0} setlinecap ${JOIN[o.join] ?? 0} setlinejoin`
      + ` ${num(o.miter)} setmiterlimit [${o.dash.map((v) => num(v, 3)).join(' ')}] ${num(o.dashOffset, 3)} setdash`;
    const out = [];
    let depth = 0;
    for (const o of rec.ops) {
      if (o.op === 'save') { out.push('gsave'); depth++; } else if (o.op === 'restore') { if (depth > 0) { out.push('grestore'); depth--; } } else if (o.op === 'clip') out.push(`newpath ${psPath(o.path) || '0 0 m 0 0 l h '}${o.evenodd ? 'eoclip' : 'clip'} newpath`);
      else if (o.op === 'fill') {
        const p = psPath(o.path);
        if (!p) continue;
        if (o.paint.color) out.push(`${rgb(o.paint.color)} setrgbcolor newpath ${p}${o.evenodd ? 'eofill' : 'fill'}`);
        else out.push(`gsave newpath ${p}${o.evenodd ? 'eoclip' : 'clip'} newpath ${shading(o.paint)} grestore`);
      } else if (o.op === 'stroke') {
        const p = psPath(o.path);
        if (!p) continue;
        if (o.paint.color) out.push(`${rgb(o.paint.color)} setrgbcolor ${lineState(o)} newpath ${p}stroke`);
        else out.push(`gsave ${lineState(o)} newpath ${p}strokepath clip newpath ${shading(o.paint)} grestore`);
      } else if (o.op === 'text') {
        const m = o.m;
        const main = stdFont(o.font);
        let s = `gsave ${rgb(textColor(o.paint))} setrgbcolor [${[m[0], m[1], -m[2], -m[3], m[4], m[5]].map((v) => num(v, 4)).join(' ')}] concat 0 0 moveto`;
        for (const g of pieces(o.text, isoLatin1)) {
          const name = g.sym ? 'Symbol' : `${main}-ISO`;
          if (!g.sym) fonts.add(main);
          s += ` /${name} ${num(o.font.size, 3)} selectfont ${psString(g.bytes)} show`;
        }
        out.push(`${s} grestore`);
      } else if (o.op === 'image') {
        out.push(`gsave [${imageMatrix(o).map((v) => num(v, 4)).join(' ')}] concat\n${await psImage(o)}\ngrestore`);
      }
    }
    while (depth-- > 0) out.push('grestore');
    const title1 = String(title || 'Figure').replace(/[^\x20-\x7e]/g, '?');
    return ['%!PS-Adobe-3.0 EPSF-3.0', '%%Creator: PyLAB', `%%Title: ${title1}`, `%%CreationDate: ${new Date().toISOString()}`,
      `%%BoundingBox: 0 0 ${Math.ceil(PW)} ${Math.ceil(PH)}`, `%%HiResBoundingBox: 0 0 ${num(PW, 3)} ${num(PH, 3)}`,
      '%%LanguageLevel: 3', '%%DocumentData: Clean7Bit', '%%Pages: 1', '%%EndComments', '%%BeginProlog',
      '/PyLABDict 20 dict def PyLABDict begin',
      '/m /moveto load def /l /lineto load def /c /curveto load def /h /closepath load def',
      '/isofont { findfont dup length dict begin { 1 index /FID ne { def } { pop pop } ifelse } forall',
      '  /Encoding ISOLatin1Encoding def currentdict end definefont pop } bind def',
      'end', '%%EndProlog', '%%BeginSetup', 'PyLABDict begin', ...[...fonts].map((f) => `/${f}-ISO /${f} isofont`), '%%EndSetup',
      '%%Page: 1 1', 'gsave', `0 ${num(PH, 3)} translate ${num(k, 6)} ${num(-k, 6)} scale`, ...out.map((s) => psWrap(s)), 'grestore', 'end', 'showpage',
      '%%Trailer', '%%EOF', ''].join('\n');
  }

  /* ---- BMP and TIFF ------------------------------------------------------------------- */
  /* The canvas's pixels over white, a row at a time (top first) as RGB. */
  function rgbRows(canvas) {
    const w = canvas.width, h = canvas.height;
    const d = canvas.getContext('2d').getImageData(0, 0, w, h).data;
    const out = new Uint8Array(w * h * 3);
    for (let i = 0, j = 0; i < w * h; i++, j += 4) {
      const a = d[j + 3] / 255;
      for (let q = 0; q < 3; q++) out[i * 3 + q] = Math.round(d[j + q] * a + 255 * (1 - a));
    }
    return { w, h, rgb: out };
  }

  function toBMP(canvas, dpi) {
    const { w, h, rgb } = rgbRows(canvas);
    const row = Math.ceil(w * 3 / 4) * 4, size = 54 + row * h;
    const b = new Uint8Array(size), v = new DataView(b.buffer);
    b[0] = 0x42; b[1] = 0x4d;
    v.setUint32(2, size, true); v.setUint32(10, 54, true); v.setUint32(14, 40, true);
    v.setInt32(18, w, true); v.setInt32(22, h, true); v.setUint16(26, 1, true); v.setUint16(28, 24, true);
    v.setUint32(34, row * h, true);
    const ppm = Math.round(dpi / 0.0254);
    v.setInt32(38, ppm, true); v.setInt32(42, ppm, true);
    for (let y = 0; y < h; y++) {
      const o = 54 + (h - 1 - y) * row;          // rows from the bottom up, each blue, green, red
      for (let x = 0; x < w; x++) {
        const i = (y * w + x) * 3;
        b[o + x * 3] = rgb[i + 2]; b[o + x * 3 + 1] = rgb[i + 1]; b[o + x * 3 + 2] = rgb[i];
      }
    }
    return b;
  }

  function toTIFF(canvas, dpi) {
    const { w, h, rgb } = rgbRows(canvas);
    const n = 13, ifd = 8, bps = ifd + 2 + n * 12 + 4, xres = bps + 6, yres = xres + 8, data = yres + 8;
    const b = new Uint8Array(data + rgb.length), v = new DataView(b.buffer);
    b[0] = 0x49; b[1] = 0x49; v.setUint16(2, 42, true); v.setUint32(4, ifd, true);
    v.setUint16(ifd, n, true);
    let p = ifd + 2;
    const tag = (t, type, count, value) => {
      v.setUint16(p, t, true); v.setUint16(p + 2, type, true); v.setUint32(p + 4, count, true);
      if (type === 3 && count === 1) v.setUint16(p + 8, value, true); else v.setUint32(p + 8, value, true);
      p += 12;
    };
    // baseline RGB, one strip, uncompressed (the tags in ascending order)
    tag(256, 4, 1, w); tag(257, 4, 1, h); tag(258, 3, 3, bps); tag(259, 3, 1, 1); tag(262, 3, 1, 2); tag(273, 4, 1, data);
    tag(277, 3, 1, 3); tag(278, 4, 1, h); tag(279, 4, 1, rgb.length); tag(282, 5, 1, xres); tag(283, 5, 1, yres); tag(284, 3, 1, 1);
    tag(296, 3, 1, 2);
    v.setUint32(p, 0, true);
    for (let q = 0; q < 3; q++) v.setUint16(bps + 2 * q, 8, true);
    v.setUint32(xres, Math.round(dpi), true); v.setUint32(xres + 4, 1, true);
    v.setUint32(yres, Math.round(dpi), true); v.setUint32(yres + 4, 1, true);
    b.set(rgb, data);
    return b;
  }

  PL.figureExport = {
    Recorder,
    /* A figure as a vector file's bytes: draw(ctx) draws it into a recorder of
       w x h CSS pixels, at two device units a pixel (as a picture saved at
       twice the screen's size), so lines keep the widths they have there. */
    async vector(format, w, h, draw, title) {
      const unit = 2;
      const rec = new Recorder(w, h);
      rec.setTransform(unit, 0, 0, unit, 0, 0);
      draw(rec);
      if (format === 'svg') return new TextEncoder().encode(toSVG(rec, unit, title));
      if (format === 'pdf') return toPDF(rec, unit, title);
      return enc(await toEPS(rec, unit, title));
    },
    /* A canvas as a BMP or TIFF file's bytes. */
    raster(format, canvas, dpi) {
      return format === 'bmp' ? toBMP(canvas, dpi) : toTIFF(canvas, dpi);
    },
    base64,
  };
})(window);
