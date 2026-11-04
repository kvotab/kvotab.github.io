/* ==========================================================================
   PYLAB.HTML: FIGURES

   Figure windows float over the desktop (moved by their title bar, sized
   from the corner). Each draws the description the engine sends (see
   graphics_base.serialize_figure) on a canvas:

     2-D axes   grid, data, then the box, ticks and labels on top
     3-D axes   an orthographic view from View [azimuth elevation]: the
                back walls with their grid, then every face, line and marker
                sorted far to near (the painter's algorithm)

   In the axes, a drag pans (2-D) or turns (3-D), the wheel zooms, a double
   click goes back to the view the program set. The toolbar picks zoom by
   box, pan, rotate or data tips instead. The limits and views a person sets
   are sent back, so xlim and view report them.

   A program's own window (MenuBar or ToolBar 'none') has no plot tools and
   none of that: its clicks, keys, wheel and close button go to the program
   (CurrentPoint, SelectionType, CurrentCharacter, gco, and its callbacks),
   as do clicks in any figure that a ButtonDownFcn or WindowButtonDownFcn
   takes. Its menus, toolbars and controls are pylab-ui.js's.
   ========================================================================== */
(function (root) {
  'use strict';
  const PL = root.PL || (root.PL = {});
  const { el, icon, Emitter } = PL;

  const FONT = 'Helvetica, Arial, "IBM Plex Sans", sans-serif';
  const PT = 1.25;                // points to CSS pixels on screen
  const AXIS_INK = 'rgb(38,38,38)';
  /* Line widths are in points, drawn as CSS pixels, but never thinner than a
     pixel of the canvas: half a pixel on a plain screen is a faint grey. */
  let MIN_LW = 1;
  const lw = (w) => Math.max(w > 0 ? w : 0.5, MIN_LW);

  /* ---- data ------------------------------------------------------------------ */
  const decodeCache = new WeakMap();

  function decode(spec) {
    if (!spec) return null;
    if (spec.data) return spec;
    const hit = decodeCache.get(spec);
    if (hit) return hit;
    const bin = atob(spec.$);
    const buf = new ArrayBuffer(bin.length);
    const u8 = new Uint8Array(buf);
    for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
    const out = { data: new Float64Array(buf), shape: spec.shape };
    decodeCache.set(spec, out);
    return out;
  }

  /* Row-major access to a 2-D array that may be a vector. */
  function at2(a, i, j) {
    const sh = a.shape;
    if (sh.length === 1) return a.data[j * 0 + i];
    return a.data[i * sh[1] + j];
  }

  function vec(a) { return a ? a.data : new Float64Array(0); }

  /* Is (px, py) inside the panel or tab that holds the axes (anywhere, when the figure does)? */
  function inBox(ax, px, py) {
    const b = ax && ax._box;
    return !b || (px >= b.x && px <= b.x + b.w && py >= b.y && py <= b.y + b.h);
  }

  function rgb(c, alpha = 1) {
    if (!c || c === 'none') return 'transparent';
    if (typeof c === 'string') return c;
    const r = Math.round(c[0] * 255), g = Math.round(c[1] * 255), b = Math.round(c[2] * 255);
    return alpha < 1 ? `rgba(${r},${g},${b},${alpha})` : `rgb(${r},${g},${b})`;
  }

  function cmapColor(cmap, clim, v, alpha = 1) {
    if (Array.isArray(v)) return rgb(v, alpha);        // a true colour (FaceVertexCData given as RGB rows)
    const n = cmap.shape[0];
    if (!Number.isFinite(v)) return null;
    let t = clim[1] > clim[0] ? (v - clim[0]) / (clim[1] - clim[0]) : 0.5;
    t = Math.max(0, Math.min(1, t));
    const k = Math.min(n - 1, Math.floor(t * n));
    const d = cmap.data;
    return rgb([d[k * 3], d[k * 3 + 1], d[k * 3 + 2]], alpha);
  }

  function cmapRGB(cmap, clim, v) {
    const n = cmap.shape[0];
    let t = clim[1] > clim[0] ? (v - clim[0]) / (clim[1] - clim[0]) : 0.5;
    t = Math.max(0, Math.min(1, t));
    const k = Math.min(n - 1, Math.floor(t * n));
    const d = cmap.data;
    return [d[k * 3], d[k * 3 + 1], d[k * 3 + 2]];
  }

  /* ---- ticks -------------------------------------------------------------------- */
  function niceStep(span, maxn) {
    if (!(span > 0) || !Number.isFinite(span)) return 1;
    const raw = span / Math.max(maxn - 1, 1);
    const p = 10 ** Math.floor(Math.log10(raw));
    for (const m of [1, 2, 2.5, 5, 10]) {
      const step = m * p;
      if (span / step <= maxn - 1 + 1e-9) return step;
    }
    return 10 * p;
  }

  function niceTicks(lo, hi, maxn) {
    if (!(Number.isFinite(lo) && Number.isFinite(hi)) || hi <= lo) return Number.isFinite(lo) ? [lo] : [];
    const step = niceStep(hi - lo, maxn);
    const start = Math.ceil(lo / step - 1e-9) * step;
    const out = [];
    for (let k = 0; k < 1000; k++) {
      const v = start + k * step;
      if (v > hi + step * 1e-9) break;
      out.push(Math.abs(v) < step * 1e-10 ? 0 : Math.round(v / step) * step);
    }
    return out;
  }

  function logTicks(lo, hi) {
    if (lo <= 0 || hi <= 0) return [];
    const a = Math.floor(Math.log10(lo) + 1e-9);
    const b = Math.ceil(Math.log10(hi) - 1e-9);
    const n = b - a;
    const step = n <= 10 ? 1 : Math.ceil(n / 10);
    const out = [];
    for (let e = a; e <= b; e += step) {
      const v = 10 ** e;
      if (v >= lo * (1 - 1e-9) && v <= hi * (1 + 1e-9)) out.push(v);
    }
    return out;
  }

  /* ---- datetime and duration axes: the values are date numbers (days from year 0) or days ---- */
  function civilOf(dn) {
    const day = Math.floor(dn + 1e-9);
    let sod = Math.round((dn - day) * 86400 * 1000) / 1000;
    const z = day - 719529 + 719468;
    const era = Math.floor(z / 146097), doe = z - era * 146097;
    const yoe = Math.floor((doe - Math.floor(doe / 1460) + Math.floor(doe / 36524) - Math.floor(doe / 146096)) / 365);
    const doy = doe - (365 * yoe + Math.floor(yoe / 4) - Math.floor(yoe / 100));
    const mp = Math.floor((5 * doy + 2) / 153);
    const d = doy - Math.floor((153 * mp + 2) / 5) + 1, m = mp < 10 ? mp + 3 : mp - 9;
    const y = yoe + era * 400 + (m <= 2 ? 1 : 0);
    const h = Math.floor(sod / 3600), mi = Math.floor((sod - h * 3600) / 60), s = sod - h * 3600 - mi * 60;
    return { y, m, d, h, mi, s };
  }
  function datenumOf(y, m, d) {
    const yy = m <= 2 ? y - 1 : y, era = Math.floor(yy / 400), yoe = yy - era * 400;
    const mp = (m + 9) % 12, doy = Math.floor((153 * mp + 2) / 5) + d - 1;
    const doe = yoe * 365 + Math.floor(yoe / 4) - Math.floor(yoe / 100) + doy;
    return era * 146097 + doe - 719468 + 719529;
  }
  const MON3 = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const two = (n) => String(n).padStart(2, '0');
  /* Ticks at whole calendar units: a step of seconds to years that gives at most maxn ticks. */
  function dateTicks(lo, hi, maxn) {
    if (!(Number.isFinite(lo) && Number.isFinite(hi)) || hi <= lo) return { ticks: [], labels: [] };
    const span = hi - lo, S = 1 / 86400;
    const fixed = [[1, 's'], [2, 's'], [5, 's'], [10, 's'], [15, 's'], [30, 's'], [60, 'm'], [120, 'm'], [300, 'm'], [600, 'm'], [900, 'm'], [1800, 'm'],
      [3600, 'h'], [7200, 'h'], [10800, 'h'], [21600, 'h'], [43200, 'h'], [86400, 'd'], [172800, 'd'], [604800, 'd'], [1209600, 'd']];
    let ticks = [], unit = null;
    for (const [secs, u] of fixed) {
      const step = secs * S;
      if (span / step <= maxn - 1 + 1e-9) {
        const start = Math.ceil(lo / step - 1e-9) * step;
        for (let k = 0; k < 1000; k++) { const v = start + k * step; if (v > hi + step * 1e-9) break; ticks.push(Math.round(v / S) * S); }
        unit = u;
        break;
      }
    }
    if (!unit) {
      const a = civilOf(lo), b = civilOf(hi);
      const months = (b.y - a.y) * 12 + (b.m - a.m);
      let stepM = [1, 2, 3, 6].find((k) => months / k <= maxn - 1);
      if (stepM) unit = 'M';
      else { stepM = 12 * ([1, 2, 5, 10, 20, 50, 100, 200, 500, 1000].find((k) => months / 12 / k <= maxn - 1) || 1000); unit = 'y'; }
      let y = a.y, m = a.m;
      // the first boundary of the step at or after lo
      let idx = Math.ceil(((y * 12 + m - 1) + (datenumOf(y, m, 1) < lo - 1e-9 ? 1 : 0)) / stepM) * stepM;
      for (let k = 0; k < 1000; k++, idx += stepM) {
        const v = datenumOf(Math.floor(idx / 12), idx % 12 + 1, 1);
        if (v > hi + 1e-9) break;
        if (v >= lo - 1e-9) ticks.push(v);
      }
    }
    const labels = ticks.map((t) => {
      const c = civilOf(t);
      switch (unit) {
        case 's': return `${two(c.h)}:${two(c.mi)}:${two(Math.round(c.s))}`;
        case 'm': case 'h': return `${two(c.h)}:${two(c.mi)}`;
        case 'd': return `${MON3[c.m - 1]} ${two(c.d)}`;
        case 'M': return `${MON3[c.m - 1]} ${c.y}`;
        default: return `${c.y}`;
      }
    });
    // the date under time ticks, and the year under day ticks (on the first one), as a second line
    if ((unit === 's' || unit === 'm' || unit === 'h') && labels.length) {
      const c = civilOf(ticks[0]);
      labels[0] = `${labels[0]}\n${MON3[c.m - 1]} ${two(c.d)}, ${c.y}`;
    } else if (unit === 'd' && labels.length) {
      labels[0] = `${labels[0]}\n${civilOf(ticks[0]).y}`;
    }
    return { ticks, labels };
  }
  /* Durations (in days) in the data's format: a single unit ('y', 'd', 'h',
     'm', 's') at round numbers of it, labelled '2 hr'; else whole seconds,
     minutes, hours or days, labelled hh:mm:ss or in days. */
  const DUR_UNITS = { y: [365.2425, 'yr', 'yrs'], d: [1, 'day', 'days'], h: [1 / 24, 'hr', 'hr'], m: [1 / 1440, 'min', 'min'], s: [1 / 86400, 'sec', 'sec'] };
  function durationTicks(lo, hi, maxn, fmt) {
    if (!(Number.isFinite(lo) && Number.isFinite(hi)) || hi <= lo) return { ticks: [], labels: [] };
    const unit = DUR_UNITS[fmt];
    if (unit) {
      const [u, one, many] = unit;
      const step = niceStep((hi - lo) / u, maxn);
      const ticks = [];
      const start = Math.ceil(lo / u / step - 1e-9) * step;
      for (let k = 0; k < 1000; k++) { const v = start + k * step; if (v > hi / u + step * 1e-9) break; ticks.push(v * u); }
      const labels = ticks.map((t) => {
        const v = Math.round(t / u / step) * step, x = Number(v.toPrecision(12));
        return `${x} ${Math.abs(x) === 1 ? one : many}`;
      });
      return { ticks, labels };
    }
    const S = 1 / 86400, span = hi - lo;
    const steps = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 10800, 21600, 43200, 86400, 172800, 432000, 864000];
    const k0 = steps.find((k) => span / (k * S) <= maxn - 1);
    const step = k0 ? k0 * S : niceStep(span, maxn);
    const ticks = [];
    const start = Math.ceil(lo / step - 1e-9) * step;
    for (let k = 0; k < 1000; k++) { const v = start + k * step; if (v > hi + step * 1e-9) break; ticks.push(v); }
    const labels = ticks.map((t) => {
      if (step >= 1) return `${Math.round(t * 1e6) / 1e6} days`;
      const sg = t < 0 ? '-' : '', x = Math.round(Math.abs(t) * 86400);
      return `${sg}${two(Math.floor(x / 3600))}:${two(Math.floor(x % 3600 / 60))}:${two(x % 60)}`;
    });
    return { ticks, labels };
  }

  /* A categorical axis: each category at its place (1, 2, ...), named. */
  function categoryTicks(lo, hi, namesJson) {
    let names = [];
    try { names = JSON.parse(namesJson); } catch (e) { names = []; }
    const ticks = [], labels = [];
    for (let k = Math.max(1, Math.ceil(Math.min(lo, hi) - 1e-9)); k <= Math.min(names.length, Math.floor(Math.max(lo, hi) + 1e-9)); k++) {
      ticks.push(k);
      labels.push(String(names[k - 1]));
    }
    return { ticks, labels };
  }

  function maxTicks(px, is3d) { return Math.max(3, Math.min(is3d ? 7 : 11, Math.floor(px / 30) + 1)); }

  /* Tick labels and the exponent written at the axis' end. */
  function tickLabels(ticks, log) {
    if (!ticks.length) return { labels: [], exp: null };
    if (log) return { labels: ticks.map((t) => `10^{${Math.round(Math.log10(t))}}`), exp: null };
    const m = Math.max(...ticks.map(Math.abs));
    let exp = null;
    let vals = ticks;
    if (m > 0) {
      const e = Math.floor(Math.log10(m));
      if (e >= 4 || e <= -4) { exp = e; vals = ticks.map((t) => t / 10 ** e); }
    }
    let step = Infinity;
    for (let i = 1; i < vals.length; i++) step = Math.min(step, Math.abs(vals[i] - vals[i - 1]));
    if (!Number.isFinite(step)) step = 1;
    let dec = 0;
    while (dec < 10 && Math.abs(Math.round(step * 10 ** dec) - step * 10 ** dec) > 1e-6 * Math.max(1, step * 10 ** dec)) dec++;
    const labels = vals.map((v) => {
      let s = v.toFixed(dec);
      if (s.includes('.')) s = s.replace(/0+$/, '').replace(/\.$/, '');
      if (s === '-0') s = '0';
      return s;
    });
    return { labels, exp };
  }

  /* ---- text with a little TeX: ^{} _{} \alpha \bf \it ------------------------------ */
  const TEX = {
    alpha: 'α', beta: 'β', gamma: 'γ', delta: 'δ', epsilon: 'ε', varepsilon: 'ε', zeta: 'ζ', eta: 'η', theta: 'θ', vartheta: 'ϑ',
    iota: 'ι', kappa: 'κ', lambda: 'λ', mu: 'μ', nu: 'ν', xi: 'ξ', pi: 'π', rho: 'ρ', sigma: 'σ', varsigma: 'ς', tau: 'τ',
    upsilon: 'υ', phi: 'φ', varphi: 'φ', chi: 'χ', psi: 'ψ', omega: 'ω', Gamma: 'Γ', Delta: 'Δ', Theta: 'Θ', Lambda: 'Λ',
    Xi: 'Ξ', Pi: 'Π', Sigma: 'Σ', Upsilon: 'Υ', Phi: 'Φ', Psi: 'Ψ', Omega: 'Ω', pm: '±', mp: '∓', times: '×', div: '÷',
    cdot: '·', infty: '∞', circ: '°', deg: '°', leq: '≤', le: '≤', geq: '≥', ge: '≥', neq: '≠', ne: '≠', approx: '≈', equiv: '≡',
    sim: '∼', propto: '∝', rightarrow: '→', leftarrow: '←', leftrightarrow: '↔', uparrow: '↑', downarrow: '↓', Rightarrow: '⇒',
    partial: '∂', nabla: '∇', sum: '∑', int: '∫', prod: '∏', surd: '√', in: '∈', forall: '∀', exists: '∃', cap: '∩', cup: '∪',
    subset: '⊂', supset: '⊃', emptyset: '∅', bullet: '•', ldots: '…', cdots: '⋯', prime: '′', angle: '∠', perp: '⊥', ast: '∗',
    langle: '⟨', rangle: '⟩', neg: '¬', wedge: '∧', vee: '∨', oplus: '⊕', otimes: '⊗', copyright: '©', Re: 'ℜ', Im: 'ℑ', aleph: 'ℵ',
    wp: '℘', heartsuit: '♥', clubsuit: '♣', spadesuit: '♠', diamondsuit: '♦', lfloor: '⌊', rfloor: '⌋', lceil: '⌈', rceil: '⌉',
  };

  /* Runs of text with their style: [{t, sup, sub, bold, italic}]. */
  function texRuns(s, interp) {
    if (interp === 'none') return [{ t: s, shift: 0, small: false, bold: false, italic: false }];
    if (interp === 'latex') s = s.replace(/\$/g, '').replace(/\\frac\{([^}]*)\}\{([^}]*)\}/g, '$1/$2').replace(/\\(mathrm|textrm|mathit|text)\{([^}]*)\}/g, '$2').replace(/\\sqrt\{([^}]*)\}/g, '√($1)');
    const runs = [];
    let bold = false, italic = false;
    let i = 0;
    const push = (t, shift, small) => { if (t) runs.push({ t, shift, small, bold, italic }); };
    const readGroup = () => {
      if (s[i] === '{') {
        let d = 1, j = i + 1;
        while (j < s.length && d) { if (s[j] === '{') d++; else if (s[j] === '}') d--; j++; }
        const g = s.slice(i + 1, j - 1);
        i = j;
        return g;
      }
      if (s[i] === '\\') {
        const m = /^\\([A-Za-z]+)/.exec(s.slice(i));
        if (m) { i += m[0].length; return TEX[m[1]] || m[0]; }
      }
      const c = s[i];
      i += 1;
      return c || '';
    };
    let buf = '';
    while (i < s.length) {
      const c = s[i];
      if (c === '\\') {
        const m = /^\\([A-Za-z]+)\s?/.exec(s.slice(i));
        if (m) {
          const w = m[1];
          if (w === 'bf') { push(buf, 0, false); buf = ''; bold = true; i += m[0].length; continue; }
          if (w === 'it') { push(buf, 0, false); buf = ''; italic = true; i += m[0].length; continue; }
          if (w === 'rm') { push(buf, 0, false); buf = ''; bold = false; italic = false; i += m[0].length; continue; }
          if (w === 'fontsize' || w === 'color' || w === 'fontname') {
            i += m[0].length - (m[0].endsWith(' ') ? 1 : 0);
            if (s[i] === '{') readGroup();
            continue;
          }
          buf += TEX[w] || w;
          i += m[1].length + 1;
          continue;
        }
        if ('{}_^\\'.includes(s[i + 1])) { buf += s[i + 1]; i += 2; continue; }
      }
      if (c === '^' || c === '_') {
        push(buf, 0, false);
        buf = '';
        i += 1;
        const g = readGroup();
        push(texRuns(g, 'tex').map((r) => r.t).join(''), c === '^' ? 1 : -1, true);
        continue;
      }
      if (c === '{' || c === '}') { i += 1; continue; }
      buf += c;
      i += 1;
    }
    push(buf, 0, false);
    return runs;
  }

  const MONO_FONT = 'ui-monospace, "IBM Plex Mono", Menlo, Consolas, monospace';

  function runFont(r, size, base) {
    const sz = r.small ? size * 0.72 : size;
    return `${r.italic || base.italic ? 'italic ' : ''}${r.bold || base.bold ? 'bold ' : ''}${sz}px ${base.family || FONT}`;
  }

  /* FontName FixedWidth (and the usual monospaced names) draws monospaced. */
  function faceOf(name) {
    const n = String(name || '').toLowerCase();
    return n === 'fixedwidth' || /courier|mono|consol|menlo/.test(n) ? MONO_FONT : null;
  }

  /* A FontSize in its FontUnits as CSS pixels (normalized: of the axes' height). */
  function fontSizePx(t, boxH) {
    const s = t.fontSize;
    switch (t.fontUnits) {
      case 'normalized': return s * boxH;
      case 'pixels': return s;
      case 'inches': return s * 96;
      case 'centimeters': return s * 96 / 2.54;
      default: return s * PT;
    }
  }

  function measureRuns(ctx, runs, size, base) {
    let w = 0;
    for (const r of runs) { ctx.font = runFont(r, size, base); w += ctx.measureText(r.t).width; }
    return w;
  }

  /* Text at (x, y) with an alignment, a rotation, TeX and several lines. */
  function drawText(ctx, str, x, y, opts = {}) {
    const size = opts.size || 12;
    const lines = Array.isArray(str) ? str : String(str).split('\n');
    const base = { bold: opts.bold, italic: opts.italic, family: opts.family };
    const lh = size * 1.2;
    ctx.save();
    ctx.translate(x, y);
    if (opts.rotation) ctx.rotate(-opts.rotation * Math.PI / 180);
    ctx.fillStyle = opts.color || AXIS_INK;
    ctx.textBaseline = 'alphabetic';
    const total = lines.length * lh;
    let y0;
    const va = opts.valign || 'middle';
    if (va === 'top' || va === 'cap') y0 = size * 0.85;
    else if (va === 'bottom') y0 = -total + size * 0.85 + (lh - size) * 0.2;
    else if (va === 'baseline') y0 = 0;
    else y0 = -total / 2 + size * 0.85;
    let maxw = 0;
    const measured = lines.map((line) => {
      const runs = texRuns(line, opts.interpreter || 'tex');
      const w = measureRuns(ctx, runs, size, base);
      maxw = Math.max(maxw, w);
      return { runs, w };
    });
    if (opts.background && opts.background !== 'transparent' || opts.edge && opts.edge !== 'transparent') {
      const ha = opts.halign || 'left';
      const bx = ha === 'center' ? -maxw / 2 : ha === 'right' ? -maxw : 0;
      const m = opts.margin == null ? 3 : opts.margin;
      const by = y0 - size * 0.85;
      if (opts.background && opts.background !== 'transparent') { ctx.fillStyle = opts.background; ctx.fillRect(bx - m, by - m, maxw + 2 * m, total + 2 * m); }
      if (opts.edge && opts.edge !== 'transparent' && opts.edgeStyle !== 'none') {
        ctx.strokeStyle = opts.edge; ctx.lineWidth = opts.boxWidth || 0.75;
        if (opts.edgeStyle && opts.edgeStyle !== '-') dash(ctx, opts.edgeStyle, ctx.lineWidth);
        ctx.strokeRect(bx - m, by - m, maxw + 2 * m, total + 2 * m);
        ctx.setLineDash([]);
      }
      ctx.fillStyle = opts.color || AXIS_INK;
    }
    measured.forEach(({ runs, w }, k) => {
      const ha = opts.halign || 'left';
      let cx = ha === 'center' ? -w / 2 : ha === 'right' ? -w : 0;
      const cy = y0 + k * lh;
      for (const r of runs) {
        ctx.font = runFont(r, size, base);
        ctx.fillText(r.t, cx, cy - r.shift * size * 0.38);
        cx += ctx.measureText(r.t).width;
      }
    });
    ctx.restore();
    return { width: maxw, height: total };
  }

  function textSize(ctx, str, size, opts = {}) {
    const lines = Array.isArray(str) ? str : String(str).split('\n');
    let w = 0;
    for (const line of lines) w = Math.max(w, measureRuns(ctx, texRuns(line, opts.interpreter || 'tex'), size, opts));
    return { width: w, height: lines.length * size * 1.2 };
  }

  /* ---- markers and lines ---------------------------------------------------------------- */
  function dash(ctx, style, lw) {
    const u = Math.max(1, lw);
    if (style === '--') ctx.setLineDash([6 * u, 4 * u]);
    else if (style === ':') ctx.setLineDash([1.2 * u, 3 * u]);
    else if (style === '-.') ctx.setLineDash([6 * u, 3 * u, 1.2 * u, 3 * u]);
    else ctx.setLineDash([]);
  }

  // a quiver arrow from (x0, y0) to (x1, y1) in pixels: its head MaxHeadSize
  // of the arrow's length (at most 9 px at the usual 0.2)
  function arrowPath(ctx, x0, y0, x1, y1, maxHeadSize) {
    ctx.moveTo(x0, y0); ctx.lineTo(x1, y1);
    const L = Math.hypot(x1 - x0, y1 - y0);
    if (L <= 0.5) return;
    const mh = maxHeadSize ?? 0.2;
    const hs = Math.min(L * mh * 1.4, 45 * mh);
    const a = Math.atan2(y1 - y0, x1 - x0);
    ctx.moveTo(x1, y1); ctx.lineTo(x1 - hs * Math.cos(a - 0.4), y1 - hs * Math.sin(a - 0.4));
    ctx.moveTo(x1, y1); ctx.lineTo(x1 - hs * Math.cos(a + 0.4), y1 - hs * Math.sin(a + 0.4));
  }

  function markerPath(ctx, m, x, y, s) {
    const r = s / 2;
    switch (m) {
      case 'o': ctx.moveTo(x + r, y); ctx.arc(x, y, r, 0, 2 * Math.PI); break;
      case '.': ctx.moveTo(x + r / 3, y); ctx.arc(x, y, Math.max(1, r / 3), 0, 2 * Math.PI); break;
      case 's': ctx.rect(x - r * 0.9, y - r * 0.9, 1.8 * r, 1.8 * r); break;
      case 'd': ctx.moveTo(x, y - r); ctx.lineTo(x + r * 0.8, y); ctx.lineTo(x, y + r); ctx.lineTo(x - r * 0.8, y); ctx.closePath(); break;
      case '^': ctx.moveTo(x, y - r); ctx.lineTo(x + r, y + r * 0.8); ctx.lineTo(x - r, y + r * 0.8); ctx.closePath(); break;
      case 'v': ctx.moveTo(x, y + r); ctx.lineTo(x + r, y - r * 0.8); ctx.lineTo(x - r, y - r * 0.8); ctx.closePath(); break;
      case '>': ctx.moveTo(x + r, y); ctx.lineTo(x - r * 0.8, y - r); ctx.lineTo(x - r * 0.8, y + r); ctx.closePath(); break;
      case '<': ctx.moveTo(x - r, y); ctx.lineTo(x + r * 0.8, y - r); ctx.lineTo(x + r * 0.8, y + r); ctx.closePath(); break;
      case '+': ctx.moveTo(x - r, y); ctx.lineTo(x + r, y); ctx.moveTo(x, y - r); ctx.lineTo(x, y + r); break;
      case 'x': ctx.moveTo(x - r * 0.75, y - r * 0.75); ctx.lineTo(x + r * 0.75, y + r * 0.75); ctx.moveTo(x - r * 0.75, y + r * 0.75); ctx.lineTo(x + r * 0.75, y - r * 0.75); break;
      case '*': for (let k = 0; k < 3; k++) { const a = k * Math.PI / 3; ctx.moveTo(x - r * Math.cos(a), y - r * Math.sin(a)); ctx.lineTo(x + r * Math.cos(a), y + r * Math.sin(a)); } break;
      case '_': ctx.moveTo(x - r, y); ctx.lineTo(x + r, y); break;
      case '|': ctx.moveTo(x, y - r); ctx.lineTo(x, y + r); break;
      case 'p': case 'h': {
        const n = m === 'p' ? 5 : 6;
        for (let k = 0; k < 2 * n; k++) {
          const a = -Math.PI / 2 + k * Math.PI / n;
          const rr = k % 2 ? r * 0.45 : r * 1.1;
          const px = x + rr * Math.cos(a), py = y + rr * Math.sin(a);
          if (k) ctx.lineTo(px, py); else ctx.moveTo(px, py);
        }
        ctx.closePath();
        break;
      }
      default: break;
    }
  }

  const OPEN_MARKERS = new Set(['+', 'x', '*', '_', '|']);

  /* A marker's edge and face: MarkerEdgeColor and MarkerFaceColor, 'auto'
     and 'flat' the line's own colour col, 'none' none. */
  function markerInk(c, col) {
    return { edge: c.mec === 'none' ? 'transparent' : Array.isArray(c.mec) ? rgb(c.mec) : col,
      face: c.mfc === 'none' || c.mfc == null ? null : Array.isArray(c.mfc) ? rgb(c.mfc) : col };
  }

  /* One scatter point of colour col: MarkerFaceColor and MarkerEdgeColor
     ('flat' and 'auto' the point's colour), each with its alpha, the edge
     LineWidth wide. */
  function scatterMark(ctx, c, px, py, size, col) {
    const pick = (v) => (v === 'flat' || v === 'auto' ? col : Array.isArray(v) ? rgb(v) : null);
    const open = OPEN_MARKERS.has(c.marker);
    const face = open ? null : pick(c.mfc);
    const edge = pick(c.mec) || (open ? col : null);
    ctx.save();
    ctx.beginPath();
    markerPath(ctx, c.marker, px, py, size);
    if (face) { ctx.globalAlpha = c.markerFaceAlpha ?? 1; ctx.fillStyle = face; ctx.fill(); }
    if (edge) { ctx.globalAlpha = c.markerEdgeAlpha ?? 1; ctx.strokeStyle = edge; ctx.lineWidth = Math.max(0.75, lw(c.lineWidth)); ctx.stroke(); }
    ctx.restore();
  }

  function drawMarkers(ctx, pts, m, size, edge, face, lw = 0.5) {
    if (!m || m === 'none') return;
    const s = m === '.' ? size * 1.6 : size * 1.3;
    ctx.setLineDash([]);
    ctx.lineWidth = Math.max(MIN_LW, 0.75, lw);
    if (OPEN_MARKERS.has(m)) {
      ctx.strokeStyle = edge;
      ctx.beginPath();
      for (const [x, y] of pts) markerPath(ctx, m, x, y, s);
      ctx.stroke();
      return;
    }
    ctx.beginPath();
    for (const [x, y] of pts) markerPath(ctx, m, x, y, s);
    if (m === '.') { ctx.fillStyle = edge; ctx.fill(); return; }
    if (face && face !== 'transparent') { ctx.fillStyle = face; ctx.fill(); }
    if (edge && edge !== 'transparent') { ctx.strokeStyle = edge; ctx.stroke(); }
  }

  /* ---- the 2-D coordinate frame ---------------------------------------------------------- */
  class Frame2 {
    constructor(ax, rect) {
      this.ax = ax;
      this.r = rect;
      this.xl = ax.xlim;
      this.yl = ax.ylim;
      this.xlog = ax.xscale === 'log';
      this.ylog = ax.yscale === 'log';
      this.xrev = ax.xdir === 'reverse';
      this.yrev = ax.ydir === 'reverse';
    }
    fx(v) {
      const [a, b] = this.xl;
      let t = this.xlog ? (Math.log10(v) - Math.log10(a)) / (Math.log10(b) - Math.log10(a)) : (v - a) / (b - a);
      if (this.xrev) t = 1 - t;
      return this.r.x + t * this.r.w;
    }
    fy(v) {
      const [a, b] = this.yl;
      let t = this.ylog ? (Math.log10(v) - Math.log10(a)) / (Math.log10(b) - Math.log10(a)) : (v - a) / (b - a);
      if (this.yrev) t = 1 - t;
      return this.r.y + this.r.h - t * this.r.h;
    }
    ix(px) {
      let t = (px - this.r.x) / this.r.w;
      if (this.xrev) t = 1 - t;
      const [a, b] = this.xl;
      return this.xlog ? 10 ** (Math.log10(a) + t * (Math.log10(b) - Math.log10(a))) : a + t * (b - a);
    }
    iy(py) {
      let t = (this.r.y + this.r.h - py) / this.r.h;
      if (this.yrev) t = 1 - t;
      const [a, b] = this.yl;
      return this.ylog ? 10 ** (Math.log10(a) + t * (Math.log10(b) - Math.log10(a))) : a + t * (b - a);
    }
    ok(x, y) { return Number.isFinite(x) && Number.isFinite(y) && (!this.xlog || x > 0) && (!this.ylog || y > 0); }
  }

  /* ---- the 3-D view ------------------------------------------------------------------------ */
  class Frame3 {
    constructor(ax, rect) {
      this.ax = ax;
      this.r = rect;
      const [az, el] = ax.view;
      this.az = az * Math.PI / 180;
      this.el = el * Math.PI / 180;
      this.lims = [ax.xlim, ax.ylim, ax.zlim];
      this.logs = [ax.xscale === 'log', ax.yscale === 'log', ax.zscale === 'log'];
      this.revs = [ax.xdir === 'reverse', ax.ydir === 'reverse', ax.zdir === 'reverse'];
      const ca = Math.cos(this.az), sa = Math.sin(this.az), ce = Math.cos(this.el), se = Math.sin(this.el);
      this.right = [ca, sa, 0];
      this.up = [-sa * se, ca * se, ce];
      this.toward = [sa * ce, -ca * ce, se];
      // the plot box: equal data units when the aspect is fixed, else a stretched cube
      let box = [1, 1, 1];
      if (ax.darMode === 'manual') {
        const d = ax.dar;
        box = [0, 1, 2].map((k) => (this.lims[k][1] - this.lims[k][0]) / d[k]);
        const m = Math.max(...box);
        box = box.map((b) => b / m);
      } else if (ax.pbarMode === 'manual') {
        const m = Math.max(...ax.pbar);
        box = ax.pbar.map((b) => b / m);
      } else {
        box = [1, 1, 0.75];
      }
      this.box = box;
      // CameraUpVector: the view turned about its axis so that the vector (in data units) points up
      if (ax.camUp) {
        const u = [0, 1, 2].map((k) => ax.camUp[k] / ((this.lims[k][1] - this.lims[k][0]) || 1) * box[k]);
        const t = this.toward, d = u[0] * t[0] + u[1] * t[1] + u[2] * t[2];
        const v = [u[0] - d * t[0], u[1] - d * t[1], u[2] - d * t[2]];
        const len = Math.hypot(v[0], v[1], v[2]);
        if (len > 1e-9) {
          this.up = v.map((c) => c / len);
          const w = this.up;
          this.right = [w[1] * t[2] - w[2] * t[1], w[2] * t[0] - w[0] * t[2], w[0] * t[1] - w[1] * t[0]];
        }
      }
      // fit the projected box into the rectangle
      const corners = [];
      for (const x of [-1, 1]) for (const y of [-1, 1]) for (const z of [-1, 1]) corners.push(this.proj0([x * box[0] / 2, y * box[1] / 2, z * box[2] / 2]));
      const xs = corners.map((c) => c[0]), ys = corners.map((c) => c[1]);
      const w = Math.max(...xs) - Math.min(...xs), h = Math.max(...ys) - Math.min(...ys);
      this.scale = Math.min(rect.w / w, rect.h / h) * (ax.zoom3 || 1) * (ax.camZoom || 1);
      this.cx = rect.x + rect.w / 2 - (Math.max(...xs) + Math.min(...xs)) / 2 * this.scale;
      this.cy = rect.y + rect.h / 2 + (Math.max(...ys) + Math.min(...ys)) / 2 * this.scale;
      // CameraTarget: that point in the middle of the axes
      if (ax.camTarget) {
        const q = this.proj0([0, 1, 2].map((k) => this.norm(k, ax.camTarget[k])));
        this.cx = rect.x + rect.w / 2 - q[0] * this.scale;
        this.cy = rect.y + rect.h / 2 + q[1] * this.scale;
      }
    }
    norm(k, v) {
      const [a, b] = this.lims[k];
      let t = this.logs[k] ? (Math.log10(v) - Math.log10(a)) / (Math.log10(b) - Math.log10(a)) : (v - a) / (b - a);
      if (this.revs && this.revs[k]) t = 1 - t;
      return (t - 0.5) * this.box[k];
    }
    proj0(p) {
      return [p[0] * this.right[0] + p[1] * this.right[1] + p[2] * this.right[2], p[0] * this.up[0] + p[1] * this.up[1] + p[2] * this.up[2],
        p[0] * this.toward[0] + p[1] * this.toward[1] + p[2] * this.toward[2]];
    }
    /* data -> [screen x, screen y, depth (bigger is nearer)] */
    p(x, y, z) {
      const q = this.proj0([this.norm(0, x), this.norm(1, y), this.norm(2, z)]);
      return [this.cx + q[0] * this.scale, this.cy - q[1] * this.scale, q[2]];
    }
    pn(nx, ny, nz) {
      const q = this.proj0([nx, ny, nz]);
      return [this.cx + q[0] * this.scale, this.cy - q[1] * this.scale, q[2]];
    }
  }

  /* A tick's length in pixels: TickLength (its first, 2-D) of the axes' longer side. */
  function tickLen(ax, r) {
    const t = ax.tickLength && Number.isFinite(ax.tickLength[0]) ? ax.tickLength[0] : 0.01;
    return t > 0 ? Math.max(t === 0.01 ? 3 : 1, t * Math.max(r.w, r.h)) : 0;
  }

  /* Where the minor ticks (and minor grid) of an axis are: 2..9 times each
     power of ten on a log axis, else four between the ticks. */
  function minorTicks(ticks, log, lim) {
    const out = [];
    const lo = Math.min(lim[0], lim[1]), hi = Math.max(lim[0], lim[1]);
    if (log) {
      const a = Math.floor(Math.log10(lo)), b = Math.ceil(Math.log10(hi));
      if (!Number.isFinite(a) || !Number.isFinite(b) || b - a > 60) return out;
      for (let e = a; e < b; e++) for (let k = 2; k < 10; k++) { const v = k * 10 ** e; if (v >= lo && v <= hi) out.push(v); }
    } else if (ticks.length > 1) {
      const step = (ticks[1] - ticks[0]) / 5;
      if (!(Math.abs(step) > 0) || (hi - lo) / Math.abs(step) > 2000) return out;
      for (let v = ticks[0] - 5 * step; v <= hi + 1e-12; v += Math.abs(step)) if (v >= lo - 1e-12) out.push(v);
    }
    return out;
  }

  /* ---- drawing a figure -------------------------------------------------------------------- */
  class Renderer {
    constructor() {
      this.frames = [];
      this.textBoxes = new Map();
      this.waits = [];          // basemap tiles and land still loading (pylab-basemap.js)
      this.onTile = null;       // called as each arrives
    }

    draw(ctx, fig, W, H) {
      this.frames = [];
      this.textBoxes = new Map();
      this.waits = [];
      MIN_LW = 1 / (ctx.getTransform().a || 1);
      ctx.save();
      ctx.fillStyle = rgb(fig.color);
      ctx.fillRect(0, 0, W, H);
      // panels and tabs: their colour here, under the axes they hold
      for (const f of fig._fills || []) { ctx.fillStyle = rgb(f.color); ctx.fillRect(f.x, f.y, f.w, f.h); }
      ctx.lineJoin = 'round';
      const legendFor = new Map((fig.legends || []).map((l) => [l.axes, l]));
      const cbarFor = new Map((fig.colorbars || []).map((c) => [c.axes, c]));
      for (const ax of fig.axes) {
        if (ax._skip) continue;
        try {
          this.drawAxes(ctx, fig, ax, W, H, legendFor.get(ax.id), cbarFor.get(ax.id));
        } catch (e) {
          console.error(e);
        }
      }
      for (const t of fig.annotations || []) {
        if (t.shape) { this.drawShape(ctx, t, W, H); continue; }
        const p = t.position;
        if (t.units === 'normalized') this.textOf(t, ctx, t.string, p[0] * W, H - p[1] * H, { size: t.fontSize * PT, color: rgb(t.color), halign: t.halign, valign: t.valign, rotation: t.rotation, background: rgb(t.background), edge: rgb(t.edge), interpreter: t.interpreter, bold: t.fontWeight === 'bold' });
      }
      if (fig.sgtitle && fig.sgtitle.string && fig.sgtitle.visible !== false) {
        this.axesText(ctx, fig.sgtitle, W / 2, 8, 'below', 0, { size: fig.sgtitle.fontSize * PT, bold: fig.sgtitle.fontWeight === 'bold', color: rgb(fig.sgtitle.color) });
      }
      ctx.restore();
    }

    /* Text drawn for an object (a title, a label, a text): where its letters
       are, for a click on it, as drawText leaves them (turned with the text). */
    textOf(t, ctx, str, x, y, opts) {
      const m = drawText(ctx, str, x, y, opts);
      if (!t || t.id == null || !m || !(m.width > 0)) return m;
      const size = opts.size || 12;
      const x0 = opts.halign === 'center' ? -m.width / 2 : opts.halign === 'right' ? -m.width : 0;
      const va = opts.valign || 'middle';
      const y0 = va === 'top' || va === 'cap' ? 0 : va === 'bottom' ? -m.height : va === 'baseline' ? -size * 0.85 : -m.height / 2;
      const a = -(opts.rotation || 0) * Math.PI / 180, c = Math.cos(a), s = Math.sin(a);
      const xs = [], ys = [];
      for (const [px, py] of [[x0, y0], [x0 + m.width, y0], [x0, y0 + m.height], [x0 + m.width, y0 + m.height]]) {
        xs.push(x + px * c - py * s);
        ys.push(y + px * s + py * c);
      }
      this.textBoxes.set(t.id, { x: Math.min(...xs), y: Math.min(...ys), w: Math.max(...xs) - Math.min(...xs), h: Math.max(...ys) - Math.min(...ys) });
      return m;
    }

    /* An axes' title or label t at the edge (x, y) of the space it has:
       'below' and 'above' the axes (y the box's top or bottom edge), 'left'
       and 'right' of them (x the box's right or left edge). Turned by its
       Rotation, about its middle, and kept clear of the edge; at its usual
       turn (def: 0, or 90 for a y label, drawn -90 on the right), where it
       has always stood (a y label's middle off the edge by inset). Its font,
       italics, background and edge are its own. The box it takes, {w, h}. */
    axesText(ctx, t, x, y, side, inset, opts) {
      const def = side === 'left' || side === 'right' ? 90 : 0;
      const rot = Number.isFinite(t.rotation) ? t.rotation : def;
      const o = Object.assign({ interpreter: t.interpreter, italic: t.fontAngle === 'italic', family: faceOf(t.fontName),
        background: Array.isArray(t.background) ? rgb(t.background) : null, edge: Array.isArray(t.edge) ? rgb(t.edge) : null,
        margin: t.margin, boxWidth: t.lineWidth ? lw(t.lineWidth) : null, edgeStyle: t.lineStyle }, opts);
      if (rot === def) {
        if (side === 'left' || side === 'right') {
          this.textOf(t, ctx, t.string, side === 'left' ? x - inset : x + inset, y, Object.assign(o, { halign: 'center', valign: 'middle', rotation: side === 'left' ? 90 : -90 }));
        } else this.textOf(t, ctx, t.string, x, y, Object.assign(o, { halign: 'center', valign: side === 'below' ? 'top' : 'bottom', rotation: 0 }));
        const m = textSize(ctx, t.string, o.size, o);
        return side === 'left' || side === 'right' ? { w: m.height, h: m.width } : { w: m.width, h: m.height };
      }
      const m = textSize(ctx, t.string, o.size, o);
      const a = rot * Math.PI / 180;
      const w = Math.abs(m.width * Math.cos(a)) + Math.abs(m.height * Math.sin(a));
      const h = Math.abs(m.width * Math.sin(a)) + Math.abs(m.height * Math.cos(a));
      const cx = side === 'left' ? x - w / 2 : side === 'right' ? x + w / 2 : x;
      const cy = side === 'below' ? y + h / 2 : side === 'above' ? y - h / 2 : y;
      this.textOf(t, ctx, t.string, cx, cy, Object.assign(o, { halign: 'center', valign: 'middle', rotation: rot }));
      return { w, h };
    }

    /* annotation(...): a line, arrow, double arrow, text arrow, rectangle,
       ellipse or text box, in the figure's normalized units (or its Units). */
    drawShape(ctx, a, W, H) {
      if (a.visible === false) return;
      const u = a.units && a.units !== 'normalized' ? (PL.uiUnits && PL.uiUnits[a.units]) || [1, 1] : null;
      const px = (x) => (u ? x * u[0] : x * W), py = (y) => H - (u ? y * u[1] : y * H);
      const textOpts = { size: a.fontSize * PT, interpreter: a.interpreter, bold: a.fontWeight === 'bold', italic: a.fontAngle === 'italic', family: faceOf(a.fontName) };
      const lines = Array.isArray(a.string) ? a.string : String(a.string ?? '').split('\n');
      const hasText = lines.some((l) => l !== '');
      ctx.save();
      ctx.lineJoin = 'round';
      if (a.shape === 'rectangle' || a.shape === 'ellipse' || a.shape === 'textbox') {
        const p = a.position;
        let x = px(p[0]), y = py(p[1] + p[3]), w = px(p[0] + p[2]) - x, h = py(p[1]) - y;
        const box = a.shape === 'textbox';
        const edge = box ? a.edgeColor : a.color, face = box ? a.background : a.faceColor;
        const m = box ? (a.margin ?? 5) : 0;
        if (box && a.fitBox && hasText) {
          // the box takes the size of its text, its top left corner kept
          const t = textSize(ctx, lines, textOpts.size, textOpts);
          w = t.width + 2 * m; h = t.height + 2 * m;
        }
        ctx.beginPath();
        if (a.shape === 'ellipse') ctx.ellipse(x + w / 2, y + h / 2, Math.abs(w / 2), Math.abs(h / 2), 0, 0, 2 * Math.PI);
        else ctx.rect(x, y, w, h);
        if (face && face !== 'none') { ctx.fillStyle = rgb(face, a.faceAlpha ?? 1); ctx.fill(); }
        if (edge && edge !== 'none' && a.lineStyle !== 'none') {
          ctx.strokeStyle = rgb(edge);
          ctx.lineWidth = lw(a.lineWidth);
          dash(ctx, a.lineStyle, a.lineWidth);
          ctx.stroke();
          ctx.setLineDash([]);
        }
        if (box && hasText) {
          const ha = a.halign || 'left', va = a.valign || 'top';
          const tx = ha === 'center' ? x + w / 2 : ha === 'right' ? x + w - m : x + m;
          const ty = va === 'middle' ? y + h / 2 : va === 'bottom' || va === 'baseline' ? y + h - m : y + m;
          drawText(ctx, lines, tx, ty, { ...textOpts, color: rgb(a.color), halign: ha, valign: va === 'baseline' ? 'bottom' : va === 'cap' ? 'top' : va });
        }
        ctx.restore();
        return;
      }
      const x1 = px(a.x[0]), y1 = py(a.y[0]), x2 = px(a.x[1]), y2 = py(a.y[1]);
      const len = Math.hypot(x2 - x1, y2 - y1);
      const d = len > 0 ? [(x2 - x1) / len, (y2 - y1) / len] : [1, 0];
      const heads = [];
      if (a.head2 && a.shape !== 'line') heads.push({ tip: [x2, y2], d, ...a.head2 });
      if (a.head1 && a.shape === 'doublearrow') heads.push({ tip: [x1, y1], d: [-d[0], -d[1]], ...a.head1 });
      // the line stops inside each head, so that a thick line does not show past its point
      let s = [x1, y1], e = [x2, y2];
      for (const hd of heads) {
        if (!hd.style || hd.style === 'none') continue;
        const back = Math.min(len / 2, (hd.length || 10) * PT * 0.5);
        if (hd.tip[0] === x2 && hd.tip[1] === y2) e = [x2 - d[0] * back, y2 - d[1] * back];
        else s = [x1 + d[0] * back, y1 + d[1] * back];
      }
      if (a.color && a.color !== 'none') {
        if (a.lineStyle !== 'none') {
          ctx.strokeStyle = rgb(a.color);
          ctx.lineWidth = lw(a.lineWidth);
          dash(ctx, a.lineStyle, a.lineWidth);
          ctx.beginPath(); ctx.moveTo(s[0], s[1]); ctx.lineTo(e[0], e[1]); ctx.stroke();
          ctx.setLineDash([]);
        }
        for (const hd of heads) this.arrowHead(ctx, hd, rgb(a.color));
      }
      if (a.shape === 'textarrow' && hasText) {
        // the text at the tail, on the side away from the head
        let ha = 'center', va = 'middle';
        if (Math.abs(d[0]) >= Math.abs(d[1])) ha = d[0] > 0 ? 'right' : 'left';
        else va = d[1] > 0 ? 'bottom' : 'top';
        drawText(ctx, lines, x1 - d[0] * 3, y1 - d[1] * 3, { ...textOpts, color: rgb(a.textColor), halign: ha, valign: va, rotation: a.textRotation || 0,
          background: rgb(a.textBackground), edge: rgb(a.textEdge), boxWidth: a.textLineWidth, margin: a.textMargin });
      }
      ctx.restore();
    }

    /* An arrow's head at tip, pointing along d; its HeadLength and HeadWidth in points. */
    arrowHead(ctx, hd, color) {
      const style = hd.style || 'vback2';
      if (style === 'none') return;
      const L = (hd.length || 10) * PT, Wd = (hd.width || 10) * PT;
      const { tip, d } = hd;
      const n = [-d[1], d[0]];
      const at = (along, across) => [tip[0] - d[0] * along + n[0] * across, tip[1] - d[1] * along + n[1] * across];
      const poly = (pts) => { ctx.moveTo(...pts[0]); for (const p of pts.slice(1)) ctx.lineTo(...p); ctx.closePath(); };
      const notch = { vback1: 0.15, vback2: 0.3, vback3: 0.45, cback1: 0.15, cback2: 0.3, cback3: 0.45 }[style];
      ctx.beginPath();
      if (style === 'plain' || style === 'deltoid') poly([tip, at(L, Wd / 2), at(L, -Wd / 2)]);
      else if (style === 'diamond') poly([tip, at(L / 2, Wd / 2), at(L, 0), at(L / 2, -Wd / 2)]);
      else if (style === 'rectangle') poly([at(0, Wd / 2), at(L, Wd / 2), at(L, -Wd / 2), at(0, -Wd / 2)]);
      else if (style === 'ellipse') { const c = at(L / 2, 0); ctx.ellipse(c[0], c[1], L / 2, Wd / 2, Math.atan2(d[1], d[0]), 0, 2 * Math.PI); }
      else if (style.startsWith('cback')) {
        ctx.moveTo(...tip); ctx.lineTo(...at(L, Wd / 2));
        const q = at(L * (1 - 2 * notch), 0), b = at(L, -Wd / 2);
        ctx.quadraticCurveTo(q[0], q[1], b[0], b[1]);
        ctx.closePath();
      } else poly([tip, at(L, Wd / 2), at(L * (1 - (notch ?? 0.3)), 0), at(L, -Wd / 2)]);
      ctx.fillStyle = color;
      ctx.fill();
    }

    axesRect(ax, W, H, cbar, legend) {
      const p = ax.position;
      // in its container (the figure, or a panel or tab the page placed), in its Units
      const b = ax._box || { x: 0, y: 0, w: W, h: H };
      let x, y, w, h;
      const u = PL.uiUnits && ax.units && ax.units !== 'normalized' ? PL.uiUnits[ax.units] : null;
      if (u) { x = b.x + p[0] * u[0]; w = p[2] * u[0]; h = p[3] * u[1]; y = b.y + b.h - p[1] * u[1] - h; }
      else { x = b.x + p[0] * b.w; w = p[2] * b.w; h = p[3] * b.h; y = b.y + b.h - (p[1] + p[3]) * b.h; }
      if (cbar && cbar.visible && (cbar.location || 'eastoutside') === 'eastoutside') w -= Math.min(70, w * 0.16);
      if (cbar && cbar.visible && cbar.location === 'southoutside') h -= Math.min(54, h * 0.18);
      if (legend && legend.visible && /outside$/.test(legend.location) && legend.location.startsWith('northeast')) w -= Math.min(120, w * 0.25);
      if (ax.kind === 'polar') {
        const s = Math.min(w, h);
        return { x: x + (w - s) / 2, y: y + (h - s) / 2, w: s, h: s };
      }
      const is3d = !(Math.abs(ax.view[1]) === 90 && ax.view[0] % 90 === 0);
      if (!is3d && (ax.darMode === 'manual' || ax.pbarMode === 'manual')) {
        let ratio;
        if (ax.darMode === 'manual') {
          const dx = (ax.xlim[1] - ax.xlim[0]) / ax.dar[0];
          const dy = (ax.ylim[1] - ax.ylim[0]) / ax.dar[1];
          ratio = dy / dx;
        } else ratio = ax.pbar[1] / ax.pbar[0];
        if (Number.isFinite(ratio) && ratio > 0) {
          if (h / w > ratio) { const nh = w * ratio; y += (h - nh) / 2; h = nh; }
          else { const nw = h / ratio; x += (w - nw) / 2; w = nw; }
        }
      }
      return { x, y, w, h };
    }

    drawAxes(ctx, fig, ax, W, H, legend, cbar) {
      // axes in a panel or tab are drawn inside it (a camera zoom takes them past their Position)
      const b = ax._box;
      if (b) { ctx.save(); ctx.beginPath(); ctx.rect(b.x, b.y, b.w, b.h); ctx.clip(); }
      try { this.drawAxesIn(ctx, fig, ax, W, H, legend, cbar); } finally { if (b) ctx.restore(); }
    }

    drawAxesIn(ctx, fig, ax, W, H, legend, cbar) {
      let rect = this.axesRect(ax, W, H, cbar, legend);
      const is3d = !(Math.abs(ax.view[1]) === 90 && ax.view[0] % 90 === 0);
      const cmap = decode(ax.cmap) || decode(fig.cmap);
      ax._cmap = cmap;
      if (ax.kind === 'polar') { this.drawPolar(ctx, ax, rect); if (legend) this.drawLegend(ctx, ax, rect, legend, null); return; }
      // a CameraViewAngle smaller than the automatic one: the axes drawn larger about their middle
      const k = ax.camZoom || 1;
      if (k !== 1 && !is3d) rect = { x: rect.x + rect.w * (1 - k) / 2, y: rect.y + rect.h * (1 - k) / 2, w: rect.w * k, h: rect.h * k };
      if (is3d) {
        const fr = new Frame3(ax, rect);
        this.frames.push({ ax, fr, rect, is3d: true });
        this.draw3(ctx, ax, fr);
      } else {
        const fr = new Frame2(ax, rect);
        this.frames.push({ ax, fr, rect, is3d: false });
        this.draw2(ctx, ax, fr);
        if (ax.yy && ax.yy.right) {
          const right = ax.yy.right;
          right.position = ax.position;
          const fr2 = new Frame2(Object.assign({}, right, { xlim: ax.xlim, xscale: ax.xscale, xdir: ax.xdir }), rect);
          fr2.ax._cmap = cmap;
          this.frames.push({ ax: right, fr: fr2, rect, is3d: false, yyRight: true });
          this.children2(ctx, right, fr2, rect);
          this.yAxisRight(ctx, right, fr2, rect);
        }
      }
      if (cbar && cbar.visible) this.drawColorbar(ctx, ax, rect, cbar, cmap);
      if (legend && legend.visible) this.drawLegend(ctx, ax, rect, legend, cmap);
    }

    /* ---- 2-D ---------------------------------------------------------------------- */
    ticksFor(ax, which, rect, is3d) {
      const lim = ax[`${which}lim`];
      const given = ax[`${which}tick`];
      const log = ax[`${which}scale`] === 'log';
      const px = which === 'x' ? rect.w : rect.h;
      const kind = ax[`${which}kind`];
      if (kind && !given && !ax[`${which}ticklabel`]) {
        // a datetime or duration axis: its own ticks and labels
        const n = Math.max(3, Math.min(maxTicks(px, is3d), which === 'x' ? Math.floor(px / 70) + 1 : 11));
        if (kind.startsWith('categorical:')) return Object.assign(categoryTicks(lim[0], lim[1], kind.slice(12)), { exp: null });
        return Object.assign(kind === 'datetime' ? dateTicks(lim[0], lim[1], n) : durationTicks(lim[0], lim[1], n, kind.split(':')[1]), { exp: null });
      }
      let ticks = given || (log ? logTicks(lim[0], lim[1]) : niceTicks(lim[0], lim[1], maxTicks(px, is3d)));
      ticks = ticks.filter((t) => t >= Math.min(lim[0], lim[1]) - 1e-12 * Math.abs(lim[1] - lim[0]) && t <= Math.max(lim[0], lim[1]) + 1e-12 * Math.abs(lim[1] - lim[0]));
      const manual = ax[`${which}ticklabel`];
      let labels, exp = null;
      if (manual) { labels = ticks.map((_, i) => manual.length ? manual[i % manual.length] : ''); }
      else if (ax.geo && (which === 'x' || which === 'y')) {
        // geographic axes: degrees with their hemisphere, 10°W and 30°N
        ({ labels } = tickLabels(ticks.map(Math.abs), false));
        labels = labels.map((s, i) => `${s}°${ticks[i] === 0 ? '' : which === 'x' ? (ticks[i] > 0 ? 'E' : 'W') : (ticks[i] > 0 ? 'N' : 'S')}`);
      } else ({ labels, exp } = tickLabels(ticks, log));
      return { ticks, labels, exp };
    }

    /* The axes' children in their order, each kept inside the axes' box
       unless its Clipping is off (text's is, unless set). Bubbles are kept
       by their middles instead (series2). */
    children2(ctx, ax, fr, r) {
      let clipped = false;
      for (const c of ax.children) {
        if (c.visible === false) continue;
        const want = c.clip !== false && c.kind !== 'bubblechart';
        if (want !== clipped) {
          if (clipped) ctx.restore();
          else { ctx.save(); ctx.beginPath(); ctx.rect(r.x, r.y, r.w, r.h); ctx.clip(); }
          clipped = want;
        }
        this.child2(ctx, ax, fr, c);
      }
      if (clipped) ctx.restore();
    }

    draw2(ctx, ax, fr) {
      const r = fr.r;
      const fs = ax.fontSize * PT;
      const ink = rgb(ax.xcolor);
      const yink = rgb(ax.ycolor);
      if (ax.visible && ax.color !== 'none') {
        ctx.fillStyle = rgb(ax.color);
        ctx.fillRect(r.x, r.y, r.w, r.h);
      }
      // geographic axes: their basemap, under the grid and the data
      const mapNote = ax.visible && ax.geo && ax.basemap && ax.basemap !== 'none' && PL.basemap ? PL.basemap.draw(ctx, ax, fr, this) : null;
      const xt = this.ticksFor(ax, 'x', r, false);
      const yt = this.ticksFor(ax, 'y', r, false);
      ax._ticks = { xt, yt };
      // grid under the data (over it with Layer top)
      if (ax.visible && ax.layer !== 'top') this.grid2(ctx, ax, fr, xt, yt);
      this.children2(ctx, ax, fr, r);
      if (ax.visible && ax.layer === 'top') this.grid2(ctx, ax, fr, xt, yt);
      if (mapNote) this.mapNote(ctx, r, mapNote);
      if (!ax.visible) { this.labels2(ctx, ax, fr, null, null, true); return; }
      // the axes' lines, ticks and labels on top
      ctx.save();
      ctx.lineWidth = lw(ax.lineWidth);
      ctx.setLineDash([]);
      const tl = tickLen(ax, r);
      const dirOut = ax.tickDir === 'out' ? -1 : 1;
      const xAtTop = ax.xaxisLocation === 'top';
      const yAtRight = ax.yaxisLocation === 'right';
      const yb = xAtTop ? r.y : r.y + r.h;
      const xl = yAtRight ? r.x + r.w : r.x;
      ctx.strokeStyle = ink;
      ctx.beginPath();
      ctx.moveTo(r.x, yb); ctx.lineTo(r.x + r.w, yb);
      if (ax.box) { ctx.moveTo(r.x, xAtTop ? r.y + r.h : r.y); ctx.lineTo(r.x + r.w, xAtTop ? r.y + r.h : r.y); }
      ctx.stroke();
      ctx.strokeStyle = yink;
      ctx.beginPath();
      ctx.moveTo(xl, r.y); ctx.lineTo(xl, r.y + r.h);
      if (ax.box && !(ax.yy && ax.yy.right)) { ctx.moveTo(yAtRight ? r.x : r.x + r.w, r.y); ctx.lineTo(yAtRight ? r.x : r.x + r.w, r.y + r.h); }
      ctx.stroke();
      // ticks
      ctx.strokeStyle = ink;
      ctx.beginPath();
      const xTick = (x, len) => {
        ctx.moveTo(x, yb); ctx.lineTo(x, yb - (xAtTop ? -1 : 1) * len * dirOut);
        if (ax.box) { const yo = xAtTop ? r.y + r.h : r.y; ctx.moveTo(x, yo); ctx.lineTo(x, yo + (xAtTop ? -1 : 1) * len * dirOut); }
      };
      for (const t of xt.ticks) {
        const x = fr.fx(t);
        if (Number.isFinite(x)) xTick(x, tl);
      }
      if (ax.xminortick) for (const v of minorTicks(xt.ticks, ax.xscale === 'log', ax.xlim)) xTick(fr.fx(v), tl / 2);
      ctx.stroke();
      ctx.strokeStyle = yink;
      ctx.beginPath();
      const yTick = (y, len) => {
        ctx.moveTo(xl, y); ctx.lineTo(xl + (yAtRight ? -1 : 1) * len * dirOut, y);
        if (ax.box && !(ax.yy && ax.yy.right)) { const xo = yAtRight ? r.x : r.x + r.w; ctx.moveTo(xo, y); ctx.lineTo(xo - (yAtRight ? -1 : 1) * len * dirOut, y); }
      };
      for (const t of yt.ticks) {
        const y = fr.fy(t);
        if (Number.isFinite(y)) yTick(y, tl);
      }
      if (ax.yminortick) for (const v of minorTicks(yt.ticks, ax.yscale === 'log', ax.ylim)) yTick(fr.fy(v), tl / 2);
      ctx.stroke();
      ctx.restore();
      // tick labels, in the axes' font
      const tf = { size: fs, interpreter: ax.tickLabelInterpreter || 'tex', bold: ax.fontWeight === 'bold', family: faceOf(ax.fontName) };
      let maxYLabel = 0;
      xt.labels.forEach((s, i) => {
        const x = fr.fx(xt.ticks[i]);
        if (!Number.isFinite(x)) return;
        if (ax.xtickrot) drawText(ctx, s, x, xAtTop ? yb - 4 : yb + 5, Object.assign({}, tf, { color: ink, halign: 'right', valign: 'middle', rotation: ax.xtickrot }));
        else drawText(ctx, s, x, xAtTop ? yb - 4 : yb + 4, Object.assign({}, tf, { color: ink, halign: 'center', valign: xAtTop ? 'bottom' : 'top' }));
      });
      yt.labels.forEach((s, i) => {
        const y = fr.fy(yt.ticks[i]);
        if (!Number.isFinite(y)) return;
        const rot = ax.ytickrot || 0;
        const m = drawText(ctx, s, yAtRight ? xl + 5 : xl - 5, y, Object.assign({}, tf, { color: yink, halign: yAtRight ? 'left' : 'right', valign: 'middle', rotation: rot }));
        const a = rot * Math.PI / 180;
        maxYLabel = Math.max(maxYLabel, Math.abs(m.width * Math.cos(a)) + Math.abs(m.height * Math.sin(a)) * (rot ? 1 : 0));
      });
      if (xt.exp !== null) drawText(ctx, `\\times10^{${xt.exp}}`, r.x + r.w, xAtTop ? yb - fs * 1.6 : yb + fs * 1.6 + 2, { size: fs, color: ink, halign: 'right', valign: 'top' });
      if (yt.exp !== null) drawText(ctx, `\\times10^{${yt.exp}}`, yAtRight ? r.x + r.w : r.x, r.y - 4, { size: fs, color: yink, halign: yAtRight ? 'right' : 'left', valign: 'bottom' });
      this.labels2(ctx, ax, fr, maxYLabel, yt.exp !== null ? fs : 0, false);
    }

    /* A basemap's attribution, small in the lower right corner of the axes,
       made smaller to fit narrow axes. */
    mapNote(ctx, r, text) {
      let size = 9;
      const w = textSize(ctx, text, size, { interpreter: 'none' }).width;
      if (w > r.w - 8) size = Math.max(5, size * (r.w - 8) / w);
      drawText(ctx, text, r.x + r.w - 3, r.y + r.h - 2, { size, color: '#333333', halign: 'right', valign: 'bottom',
        interpreter: 'none', background: 'rgba(255,255,255,0.72)', margin: 2 });
    }

    yAxisRight(ctx, ax, fr, r) {
      const fs = ax.fontSize * PT;
      const ink = rgb(ax.ycolor);
      const yt = this.ticksFor(ax, 'y', r, false);
      const tl = tickLen(ax, r);
      ctx.save();
      ctx.strokeStyle = ink;
      ctx.lineWidth = lw(ax.lineWidth);
      ctx.beginPath();
      ctx.moveTo(r.x + r.w, r.y); ctx.lineTo(r.x + r.w, r.y + r.h);
      for (const t of yt.ticks) { const y = fr.fy(t); ctx.moveTo(r.x + r.w, y); ctx.lineTo(r.x + r.w - tl, y); }
      ctx.stroke();
      ctx.restore();
      let mw = 0;
      yt.labels.forEach((s, i) => { const m = drawText(ctx, s, r.x + r.w + 5, fr.fy(yt.ticks[i]), { size: fs, color: ink, valign: 'middle' }); mw = Math.max(mw, m.width); });
      if (ax.ylabel && ax.ylabel.string && ax.ylabel.visible !== false) this.axesText(ctx, ax.ylabel, r.x + r.w + mw + 10, r.y + r.h / 2, 'right', fs * 0.9, { size: ax.ylabel.fontSize * PT * 1.1, color: ink });
    }

    grid2(ctx, ax, fr, xt, yt) {
      const r = fr.r;
      ctx.save();
      ctx.strokeStyle = rgb(ax.gridColor, ax.gridAlpha);
      ctx.lineWidth = lw(0.5);
      dash(ctx, ax.gridLineStyle, 0.5);
      ctx.beginPath();
      if (ax.xgrid) for (const t of xt.ticks) { const x = fr.fx(t); ctx.moveTo(x, r.y); ctx.lineTo(x, r.y + r.h); }
      if (ax.ygrid) for (const t of yt.ticks) { const y = fr.fy(t); ctx.moveTo(r.x, y); ctx.lineTo(r.x + r.w, y); }
      ctx.stroke();
      // minor grid on log axes, or when asked (MinorGridAlpha against its usual 0.25)
      ctx.strokeStyle = rgb(ax.gridColor, ax.gridAlpha * 0.6 * ((ax.minorGridAlpha ?? 0.25) / 0.25));
      if (!ax.minorGridLineStyle || ax.minorGridLineStyle === ':') ctx.setLineDash([1, 2]);
      else dash(ctx, ax.minorGridLineStyle, 0.5);
      ctx.beginPath();
      const minor = (ticks, log, lim, f, horiz) => {
        if (ax.minorGridLineStyle === 'none') return;
        for (const v of minorTicks(ticks, log, lim)) {
          const q = f(v);
          if (horiz) { ctx.moveTo(r.x, q); ctx.lineTo(r.x + r.w, q); } else { ctx.moveTo(q, r.y); ctx.lineTo(q, r.y + r.h); }
        }
      };
      if (ax.xminorgrid || (ax.xgrid && ax.xscale === 'log')) minor(xt.ticks, ax.xscale === 'log', ax.xlim, (v) => fr.fx(v), false);
      if (ax.yminorgrid || (ax.ygrid && ax.yscale === 'log')) minor(yt.ticks, ax.yscale === 'log', ax.ylim, (v) => fr.fy(v), true);
      ctx.stroke();
      ctx.restore();
    }

    labels2(ctx, ax, fr, maxYLabel, expPad, hiddenAxes) {
      const r = fr.r;
      const fs = ax.fontSize * PT;
      const lfs = fs * 1.1;
      const xAtTop = ax.xaxisLocation === 'top';
      if (!hiddenAxes) {
        if (ax.xlabel.string && ax.xlabel.visible !== false) {
          const y = xAtTop ? r.y - fs * 1.6 - 4 : r.y + r.h + fs * 1.4 + 6;
          this.axesText(ctx, ax.xlabel, r.x + r.w / 2, y, xAtTop ? 'above' : 'below', 0, { size: ax.xlabel.fontSize * PT * (ax.labelSize ?? 1.1), color: rgb(ax.xlabel.color === 'none' ? [0, 0, 0] : ax.xlabel.color), bold: ax.xlabel.fontWeight === 'bold' });
        }
        if (ax.ylabel.string && ax.ylabel.visible !== false) {
          const right = ax.yaxisLocation === 'right';
          const x = right ? r.x + r.w + (maxYLabel || 0) + 10 : r.x - (maxYLabel || 0) - 10;
          this.axesText(ctx, ax.ylabel, x, r.y + r.h / 2, right ? 'right' : 'left', lfs * 0.6, { size: ax.ylabel.fontSize * PT * (ax.labelSize ?? 1.1), color: rgb(ax.ylabel.color === 'none' ? [0, 0, 0] : ax.ylabel.color), bold: ax.ylabel.fontWeight === 'bold' });
        }
      }
      this.titles(ctx, ax, r.x + r.w / 2, r.y - 6 - (xAtTop ? fs * 3 : 0));
    }

    /* The axes' title above (x, y), its subtitle under it. */
    titles(ctx, ax, x, y) {
      if (ax.subtitle && ax.subtitle.string && ax.subtitle.visible !== false) {
        const m = this.axesText(ctx, ax.subtitle, x, y, 'above', 0, { size: ax.subtitle.fontSize * PT, color: rgb(ax.subtitle.color), bold: ax.subtitle.fontWeight === 'bold' });
        y -= Math.max(ax.subtitle.fontSize * PT * 1.3, m.h);
      }
      if (ax.title.string && ax.title.visible !== false) this.axesText(ctx, ax.title, x, y, 'above', 0, { size: ax.title.fontSize * PT * (ax.titleSize ?? 1.1), color: rgb(ax.title.color), bold: ax.title.fontWeight !== 'normal' });
    }

    child2(ctx, ax, fr, c) {
      switch (c.type) {
        case 'line': return this.line2(ctx, ax, fr, c);
        case 'surface': return this.surface2(ctx, ax, fr, c);
        case 'patch': return this.patch2(ctx, ax, fr, c);
        case 'image': return this.image2(ctx, ax, fr, c);
        case 'text': return this.text2(ctx, ax, fr, c);
        case 'series': return this.series2(ctx, ax, fr, c);
        default: return null;
      }
    }

    line2(ctx, ax, fr, c) {
      let x = vec(decode(c.x)), y = vec(decode(c.y));
      // xline and yline: a constant value across all of the other axis, whatever its limits are now
      if (c.span === 'vertical') { x = [x[0], x[0]]; y = [fr.yl[0], fr.yl[1]]; }
      else if (c.span === 'horizontal') { y = [y[0], y[0]]; x = [fr.xl[0], fr.xl[1]]; }
      const n = Math.min(x.length, y.length);
      const col = rgb(c.color);
      if (c.span && c.label) this.spanLabel(ctx, fr, c, x, y, col);
      if (c.lineStyle !== 'none' && n > 1) {
        ctx.save();
        ctx.strokeStyle = col;
        ctx.lineWidth = lw(c.lineWidth);
        dash(ctx, c.lineStyle, c.lineWidth);
        ctx.beginPath();
        let pen = false;
        for (let i = 0; i < n; i++) {
          if (!fr.ok(x[i], y[i])) { pen = false; continue; }
          const px = fr.fx(x[i]), py = fr.fy(y[i]);
          if (pen) ctx.lineTo(px, py); else { ctx.moveTo(px, py); pen = true; }
        }
        ctx.stroke();
        ctx.restore();
      }
      if (c.marker && c.marker !== 'none') {
        const pts = [];
        const idx = c.markerIndices ? vec(decode(c.markerIndices)) : null;
        const take = idx ? Array.from(idx) : null;
        if (take) { for (const i of take) if (fr.ok(x[i], y[i])) pts.push([fr.fx(x[i]), fr.fy(y[i])]); }
        else for (let i = 0; i < n; i++) if (fr.ok(x[i], y[i])) pts.push([fr.fx(x[i]), fr.fy(y[i])]);
        const edge = c.mec === 'auto' ? col : c.mec === 'none' ? 'transparent' : rgb(c.mec);
        const face = c.mfc === 'auto' ? col : c.mfc === 'none' ? null : rgb(c.mfc);
        drawMarkers(ctx, pts, c.marker, c.markerSize, edge, face, c.lineWidth);
      }
    }

    /* The label of an xline or yline: at the top (or bottom, or middle) of a vertical line, turned along it unless
       'horizontal'; at the right (or left, or centre) of a horizontal one, above (or below) it. */
    spanLabel(ctx, fr, c, x, y, col) {
      const lines = Array.isArray(c.label) ? c.label : String(c.label).split('\n');
      const size = (c.fontSize || 9) * PT;
      ctx.save();
      ctx.font = `${c.fontWeight === 'bold' ? 'bold ' : ''}${size}px Helvetica, Arial, sans-serif`;
      ctx.fillStyle = col;
      const pad = 3;
      const lh = size * 1.15;
      if (c.span === 'vertical') {
        const px = fr.fx(x[0]);
        if (!Number.isFinite(px) || px < fr.r.x - 1 || px > fr.r.x + fr.r.w + 1) { ctx.restore(); return; }
        const va = c.labelVertical || 'top', ha = c.labelHorizontal || 'right';
        const aligned = c.labelOrientation !== 'horizontal';
        if (aligned) {
          const yy = va === 'top' ? fr.r.y + pad : va === 'bottom' ? fr.r.y + fr.r.h - pad : fr.r.y + fr.r.h / 2;
          ctx.translate(px, yy);
          ctx.rotate(-Math.PI / 2);
          ctx.textAlign = va === 'top' ? 'right' : va === 'bottom' ? 'left' : 'center';
          ctx.textBaseline = ha === 'right' ? 'top' : ha === 'left' ? 'bottom' : 'middle';
          lines.forEach((t, i) => ctx.fillText(t, 0, (ha === 'left' ? -1 : 1) * (pad + i * lh)));
        } else {
          ctx.textAlign = ha === 'right' ? 'left' : ha === 'left' ? 'right' : 'center';
          ctx.textBaseline = 'top';
          const y0 = va === 'top' ? fr.r.y + pad : va === 'bottom' ? fr.r.y + fr.r.h - pad - lines.length * lh : fr.r.y + fr.r.h / 2 - lines.length * lh / 2;
          lines.forEach((t, i) => ctx.fillText(t, px + (ha === 'right' ? pad : ha === 'left' ? -pad : 0), y0 + i * lh));
        }
      } else {
        const py = fr.fy(y[0]);
        if (!Number.isFinite(py) || py < fr.r.y - 1 || py > fr.r.y + fr.r.h + 1) { ctx.restore(); return; }
        const ha = c.labelHorizontal || 'right', va = c.labelVertical || 'top';
        ctx.textAlign = ha === 'right' ? 'right' : ha === 'left' ? 'left' : 'center';
        const xx = ha === 'right' ? fr.r.x + fr.r.w - pad : ha === 'left' ? fr.r.x + pad : fr.r.x + fr.r.w / 2;
        ctx.textBaseline = va === 'top' ? 'bottom' : va === 'bottom' ? 'top' : 'middle';
        const n = lines.length;
        lines.forEach((t, i) => ctx.fillText(t, xx, va === 'top' ? py - pad - (n - 1 - i) * lh : va === 'bottom' ? py + pad + i * lh : py + (i - (n - 1) / 2) * lh));
      }
      ctx.restore();
    }

    patch2(ctx, ax, fr, c) {
      if (c.span) {
        // xregion and yregion: a band across all of the other axis
        const a = vec(decode(c.x)), b = vec(decode(c.y));
        let x0, x1, y0, y1;
        if (c.span === 'vertical') { x0 = fr.fx(a[0]); x1 = fr.fx(a[1]); y0 = fr.r.y; y1 = fr.r.y + fr.r.h; }
        else { y0 = fr.fy(b[0]); y1 = fr.fy(b[1]); x0 = fr.r.x; x1 = fr.r.x + fr.r.w; }
        if (![x0, x1, y0, y1].every(Number.isFinite)) return;
        const rx = Math.min(x0, x1), ry = Math.min(y0, y1), rw = Math.abs(x1 - x0), rh = Math.abs(y1 - y0);
        ctx.save();
        if (c.faceColor !== 'none') { ctx.globalAlpha = c.faceAlpha ?? 1; ctx.fillStyle = rgb(c.faceColor); ctx.fillRect(rx, ry, rw, rh); }
        if (c.edgeColor !== 'none' && c.lineStyle !== 'none') {
          ctx.globalAlpha = c.edgeAlpha ?? 1;
          ctx.strokeStyle = rgb(c.edgeColor);
          ctx.lineWidth = lw(c.lineWidth);
          dash(ctx, c.lineStyle, c.lineWidth);
          ctx.beginPath();
          if (c.span === 'vertical') { ctx.moveTo(x0, ry); ctx.lineTo(x0, ry + rh); ctx.moveTo(x1, ry); ctx.lineTo(x1, ry + rh); }
          else { ctx.moveTo(rx, y0); ctx.lineTo(rx + rw, y0); ctx.moveTo(rx, y1); ctx.lineTo(rx + rw, y1); }
          ctx.stroke();
        }
        ctx.restore();
        return;
      }
      const polys = patchPolys(c);
      const cmap = ax._cmap;
      for (const [pi, poly] of polys.entries()) {
        if (poly.pts.length < 2) continue;
        ctx.beginPath();
        if (c.rings) {
          // a map's polygon (geoshow): rings parted by NaN, filled even-odd so that holes stay open
          let start = true;
          for (const [x, y] of poly.pts) {
            if (!Number.isFinite(x) || !Number.isFinite(y)) { if (!start) ctx.closePath(); start = true; continue; }
            if (start) ctx.moveTo(fr.fx(x), fr.fy(y)); else ctx.lineTo(fr.fx(x), fr.fy(y));
            start = false;
          }
          if (!start) ctx.closePath();
        } else if (poly.open) {
          let start = true;
          for (const [x, y] of poly.pts) {
            if (!Number.isFinite(x) || !Number.isFinite(y)) { start = true; continue; }
            if (start) ctx.moveTo(fr.fx(x), fr.fy(y)); else ctx.lineTo(fr.fx(x), fr.fy(y));
            start = false;
          }
        } else {
          poly.pts.forEach(([x, y], i) => { const px = fr.fx(x), py = fr.fy(y); if (i) ctx.lineTo(px, py); else ctx.moveTo(px, py); });
          ctx.closePath();
        }
        let fill = null;
        if (poly.open) fill = null;
        else if (Array.isArray(c.faceColor)) fill = rgb(c.faceColor, c.faceAlpha);
        else if ((c.faceColor === 'flat' || c.faceColor === 'interp') && poly.c != null) fill = cmapColor(cmap, ax.clim, poly.c, c.faceAlpha);
        if (fill) { ctx.fillStyle = fill; ctx.fill(c.rings ? 'evenodd' : 'nonzero'); }
        if (c.edgeColor !== 'none' && c.lineStyle !== 'none') {
          ctx.strokeStyle = Array.isArray(c.edgeColor) ? rgb(c.edgeColor, c.edgeAlpha) : (poly.c != null ? cmapColor(cmap, ax.clim, poly.c) : AXIS_INK);
          ctx.lineWidth = lw(c.lineWidth);
          dash(ctx, c.lineStyle, c.lineWidth);
          ctx.stroke();
          ctx.setLineDash([]);
          if (c.arrowSize && poly.pts.length === 2) arrowHead(ctx, fr, poly.pts, c.arrowSize, (c.arrowBack || [])[pi] || 0, ctx.strokeStyle);
        }
      }
    }

    image2(ctx, ax, fr, c) {
      const C = decode(c.c);
      if (!C) return;
      const sh = C.shape;
      const rows = sh[0], cols = sh[1];
      const xd = vec(decode(c.x)), yd = vec(decode(c.y));
      const dx = cols > 1 ? (xd[xd.length - 1] - xd[0]) / (cols - 1) : 1;
      const dy = rows > 1 ? (yd[yd.length - 1] - yd[0]) / (rows - 1) : 1;
      const x0 = xd[0] - dx / 2, x1 = xd[xd.length - 1] + dx / 2;
      const y0 = yd[0] - dy / 2, y1 = yd[yd.length - 1] + dy / 2;
      const off = document.createElement('canvas');
      off.width = cols;
      off.height = rows;
      const octx = off.getContext('2d');
      const img = octx.createImageData(cols, rows);
      const cmap = ax._cmap;
      const n = cmap.shape[0];
      const cm = cmap.data;
      const rgbImg = c.rgb && sh.length === 3;
      for (let i = 0; i < rows; i++) {
        for (let j = 0; j < cols; j++) {
          const k = (i * cols + j) * 4;
          let r, g, b;
          if (rgbImg) {
            const base = (i * cols + j) * 3;
            r = C.data[base]; g = C.data[base + 1]; b = C.data[base + 2];
          } else {
            const v = C.data[i * cols + j];
            if (!Number.isFinite(v)) { img.data[k + 3] = 0; continue; }
            let idx;
            if (c.cmapping === 'scaled') {
              let t = ax.clim[1] > ax.clim[0] ? (v - ax.clim[0]) / (ax.clim[1] - ax.clim[0]) : 0.5;
              t = Math.max(0, Math.min(1, t));
              idx = Math.min(n - 1, Math.floor(t * n));
            } else idx = Math.max(0, Math.min(n - 1, Math.round(v) - 1));
            r = cm[idx * 3]; g = cm[idx * 3 + 1]; b = cm[idx * 3 + 2];
          }
          img.data[k] = r * 255; img.data[k + 1] = g * 255; img.data[k + 2] = b * 255; img.data[k + 3] = (c.alpha ?? 1) * 255;
        }
      }
      octx.putImageData(img, 0, 0);
      const px0 = fr.fx(x0), px1 = fr.fx(x1), py0 = fr.fy(y0), py1 = fr.fy(y1);
      ctx.save();
      ctx.imageSmoothingEnabled = false;
      ctx.translate(px0, py0);
      ctx.scale((px1 - px0) / cols, (py1 - py0) / rows);
      ctx.drawImage(off, 0, 0);
      ctx.restore();
    }

    surface2(ctx, ax, fr, c) {
      // a surface seen from straight above (pcolor, view(2) of surf)
      const X = decode(c.x), Y = decode(c.y), Z = decode(c.z);
      const Cd = c.c ? decode(c.c) : Z;
      if (!X || !Z) return;
      const [m, n] = Z.shape.length === 2 ? Z.shape : [1, Z.shape[0]];
      const gx = (i, j) => (X.shape.length === 2 && X.shape[0] === m ? at2(X, i, j) : X.data[j]);
      const gy = (i, j) => (Y.shape.length === 2 && Y.shape[0] === m ? at2(Y, i, j) : Y.data[i]);
      const gc = (i, j) => (Cd.shape.length >= 2 ? Cd.data[i * Cd.shape[1] + j] : Cd.data[j]);
      const cmap = ax._cmap;
      for (let i = 0; i < m - 1; i++) {
        for (let j = 0; j < n - 1; j++) {
          ctx.beginPath();
          ctx.moveTo(fr.fx(gx(i, j)), fr.fy(gy(i, j)));
          ctx.lineTo(fr.fx(gx(i, j + 1)), fr.fy(gy(i, j + 1)));
          ctx.lineTo(fr.fx(gx(i + 1, j + 1)), fr.fy(gy(i + 1, j + 1)));
          ctx.lineTo(fr.fx(gx(i + 1, j)), fr.fy(gy(i + 1, j)));
          ctx.closePath();
          let v = gc(i, j);
          if (c.faceColor === 'interp') v = (gc(i, j) + gc(i, j + 1) + gc(i + 1, j) + gc(i + 1, j + 1)) / 4;
          const fill = Array.isArray(c.faceColor) ? rgb(c.faceColor) : c.faceColor === 'none' ? null : cmapColor(cmap, ax.clim, v);
          if (fill) { ctx.fillStyle = fill; ctx.fill(); }
          if (c.edgeColor !== 'none' && c.lineStyle !== 'none') {
            ctx.strokeStyle = Array.isArray(c.edgeColor) ? rgb(c.edgeColor) : (cmapColor(cmap, ax.clim, v) || AXIS_INK);
            ctx.lineWidth = lw(c.lineWidth);
            dash(ctx, c.lineStyle || '-', c.lineWidth);
            ctx.stroke();
            ctx.setLineDash([]);
          } else if (fill) { ctx.strokeStyle = fill; ctx.lineWidth = 0.6; ctx.stroke(); }
        }
      }
    }

    text2(ctx, ax, fr, c) {
      const p = c.position;
      // normalized and the lengths (pixels, points ...) from the axes' lower left; data as plotted
      const u = c.units && c.units !== 'data' && c.units !== 'normalized' ? (PL.uiUnits && PL.uiUnits[c.units]) || [1, 1] : null;
      let x, y;
      if (c.units === 'normalized') { x = fr.r.x + p[0] * fr.r.w; y = fr.r.y + fr.r.h - p[1] * fr.r.h; }
      else if (u) { x = fr.r.x + p[0] * u[0]; y = fr.r.y + fr.r.h - p[1] * u[1]; }
      else { x = fr.fx(p[0]); y = fr.fy(p[1]); }
      const size = fontSizePx(c, fr.r.h);
      const boxed = Array.isArray(c.background) || Array.isArray(c.edge);
      const margin = c.margin == null ? 3 : c.margin;
      const m = drawText(ctx, c.string, x, y, { size, color: rgb(c.color), halign: c.halign, valign: c.valign, rotation: c.rotation, background: rgb(c.background), edge: rgb(c.edge), interpreter: c.interpreter, bold: c.fontWeight === 'bold', italic: c.fontAngle === 'italic', family: faceOf(c.fontName), margin, boxWidth: c.lineWidth ? lw(c.lineWidth) : null, edgeStyle: c.lineStyle });
      // where the letters are (and a box drawn round them), for a click on the text
      if (m && m.width > 0 && !c.rotation) {
        const x0 = c.halign === 'center' ? x - m.width / 2 : c.halign === 'right' ? x - m.width : x;
        const va = c.valign || 'middle';
        const y0 = va === 'top' || va === 'cap' ? y : va === 'bottom' ? y - m.height : va === 'baseline' ? y - size * 0.85 : y - m.height / 2;
        const g = boxed ? margin : 0;
        this.textBoxes.set(c.id, { x: x0 - g, y: y0 - g, w: m.width + 2 * g, h: m.height + 2 * g });
      }
    }

    series2(ctx, ax, fr, c) {
      const k = c.kind;
      const cmap = ax._cmap;
      if (k === 'bar') {
        const xs = vec(decode(c.xs)), top = vec(decode(c.top)), bottom = vec(decode(c.bottom));
        const w = c.width;
        const face = Array.isArray(c.faceColor) ? rgb(c.faceColor, c.faceAlpha) : rgb([0, 0.447, 0.741]);
        for (let i = 0; i < xs.length; i++) {
          if (!Number.isFinite(top[i])) continue;
          let x0, x1, y0, y1;
          if (c.horizontal) { y0 = fr.fy(xs[i] - w / 2); y1 = fr.fy(xs[i] + w / 2); x0 = fr.fx(bottom[i]); x1 = fr.fx(top[i]); }
          else { x0 = fr.fx(xs[i] - w / 2); x1 = fr.fx(xs[i] + w / 2); y0 = fr.fy(bottom[i]); y1 = fr.fy(top[i]); }
          ctx.fillStyle = face;
          ctx.fillRect(Math.min(x0, x1), Math.min(y0, y1), Math.abs(x1 - x0), Math.abs(y1 - y0));
          if (c.edgeColor !== 'none') { ctx.strokeStyle = rgb(c.edgeColor); ctx.lineWidth = lw(c.lineWidth); ctx.strokeRect(Math.min(x0, x1), Math.min(y0, y1), Math.abs(x1 - x0), Math.abs(y1 - y0)); }
        }
        return;
      }
      if (k === 'histogram') {
        const e = vec(decode(c.edges)), v = vec(decode(c.values));
        const face = Array.isArray(c.faceColor) ? rgb(c.faceColor, c.faceAlpha) : rgb([0, 0.447, 0.741], 0.6);
        const stairs = c.display === 'stairs';
        ctx.beginPath();
        for (let i = 0; i < v.length; i++) {
          let x0, x1, y0, y1;
          if (c.horizontal) { y0 = fr.fy(e[i]); y1 = fr.fy(e[i + 1]); x0 = fr.fx(0); x1 = fr.fx(v[i]); }
          else { x0 = fr.fx(e[i]); x1 = fr.fx(e[i + 1]); y0 = fr.fy(Math.max(0, fr.ylog ? 1e-300 : 0)); y1 = fr.fy(v[i]); }
          if (stairs && c.horizontal) { if (i === 0) ctx.moveTo(x0, y0); ctx.lineTo(x1, y0); ctx.lineTo(x1, y1); if (i === v.length - 1) ctx.lineTo(x0, y1); continue; }
          if (stairs) { if (i === 0) ctx.moveTo(x0, y0); ctx.lineTo(x0, y1); ctx.lineTo(x1, y1); if (i === v.length - 1) ctx.lineTo(x1, y0); continue; }
          if (v[i] === 0) continue;
          ctx.fillStyle = face;
          ctx.fillRect(Math.min(x0, x1), Math.min(y0, y1), Math.abs(x1 - x0), Math.abs(y1 - y0));
          if (c.edgeColor !== 'none') {
            ctx.strokeStyle = rgb(c.edgeColor);
            ctx.lineWidth = lw(c.lineWidth || 0.5);
            ctx.strokeRect(Math.min(x0, x1), Math.min(y0, y1), Math.abs(x1 - x0), Math.abs(y1 - y0));
          }
        }
        if (stairs) { ctx.strokeStyle = Array.isArray(c.faceColor) ? rgb(c.faceColor) : AXIS_INK; ctx.lineWidth = 1; ctx.stroke(); }
        return;
      }
      if (k === 'area') {
        const x = vec(decode(c.xData)), top = vec(decode(c.top)), bot = vec(decode(c.bottom));
        ctx.beginPath();
        for (let i = 0; i < x.length; i++) { const px = fr.fx(x[i]), py = fr.fy(top[i]); if (i) ctx.lineTo(px, py); else ctx.moveTo(px, py); }
        for (let i = x.length - 1; i >= 0; i--) ctx.lineTo(fr.fx(x[i]), fr.fy(bot[i]));
        ctx.closePath();
        ctx.fillStyle = Array.isArray(c.faceColor) ? rgb(c.faceColor, c.faceAlpha) : 'gray';
        ctx.fill();
        ctx.strokeStyle = Array.isArray(c.edgeColor) ? rgb(c.edgeColor) : AXIS_INK;
        ctx.lineWidth = lw(c.lineWidth);
        ctx.stroke();
        return;
      }
      if (k === 'stair') {
        const x = vec(decode(c.xData)), y = vec(decode(c.yData));
        ctx.save();
        ctx.strokeStyle = rgb(c.color);
        ctx.lineWidth = lw(c.lineWidth);
        dash(ctx, c.lineStyle, c.lineWidth);
        ctx.beginPath();
        for (let i = 0; i < x.length; i++) {
          const px = fr.fx(x[i]), py = fr.fy(y[i]);
          if (i === 0) ctx.moveTo(px, py);
          else { ctx.lineTo(px, fr.fy(y[i - 1])); ctx.lineTo(px, py); }
        }
        ctx.stroke();
        ctx.restore();
        if (c.marker !== 'none') { const k = markerInk(c, rgb(c.color)); drawMarkers(ctx, Array.from(x, (v, i) => [fr.fx(v), fr.fy(y[i])]), c.marker, c.markerSize, k.edge, k.face, c.lineWidth); }
        return;
      }
      if (k === 'stem') {
        const x = vec(decode(c.xData)), y = vec(decode(c.yData));
        const col = rgb(c.color);
        ctx.save();
        ctx.strokeStyle = col;
        ctx.lineWidth = lw(c.lineWidth);
        dash(ctx, c.lineStyle, c.lineWidth);
        ctx.beginPath();
        const b = fr.fy(c.baseValue);
        for (let i = 0; i < x.length; i++) { const px = fr.fx(x[i]); ctx.moveTo(px, b); ctx.lineTo(px, fr.fy(y[i])); }
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.strokeStyle = AXIS_INK;
        ctx.beginPath();
        ctx.moveTo(fr.r.x, b); ctx.lineTo(fr.r.x + fr.r.w, b);
        ctx.stroke();
        ctx.restore();
        const mk = markerInk(c, col);
        drawMarkers(ctx, Array.from(x, (v, i) => [fr.fx(v), fr.fy(y[i])]), c.marker, c.markerSize, mk.edge, mk.face, c.lineWidth);
        return;
      }
      if (k === 'errorbar') {
        const x = vec(decode(c.xData)), y = vec(decode(c.yData));
        const yn = c.yNegativeDelta ? vec(decode(c.yNegativeDelta)) : null, yp = c.yPositiveDelta ? vec(decode(c.yPositiveDelta)) : null;
        const xn = c.xNegativeDelta ? vec(decode(c.xNegativeDelta)) : null, xp = c.xPositiveDelta ? vec(decode(c.xPositiveDelta)) : null;
        const col = rgb(c.color);
        ctx.save();
        ctx.strokeStyle = col;
        ctx.lineWidth = lw(c.lineWidth);
        const cap = c.capSize / 2;
        ctx.beginPath();
        for (let i = 0; i < x.length; i++) {
          const px = fr.fx(x[i]), py = fr.fy(y[i]);
          if (yn) { const a = fr.fy(y[i] - yn[i]), b = fr.fy(y[i] + yp[i]); ctx.moveTo(px, a); ctx.lineTo(px, b); ctx.moveTo(px - cap, a); ctx.lineTo(px + cap, a); ctx.moveTo(px - cap, b); ctx.lineTo(px + cap, b); }
          if (xn) { const a = fr.fx(x[i] - xn[i]), b = fr.fx(x[i] + xp[i]); ctx.moveTo(a, py); ctx.lineTo(b, py); ctx.moveTo(a, py - cap); ctx.lineTo(a, py + cap); ctx.moveTo(b, py - cap); ctx.lineTo(b, py + cap); }
        }
        ctx.stroke();
        if (c.lineStyle !== 'none') {
          dash(ctx, c.lineStyle, c.lineWidth);
          ctx.beginPath();
          for (let i = 0; i < x.length; i++) { const px = fr.fx(x[i]), py = fr.fy(y[i]); if (i) ctx.lineTo(px, py); else ctx.moveTo(px, py); }
          ctx.stroke();
        }
        ctx.restore();
        if (c.marker !== 'none') { const k = markerInk(c, col); drawMarkers(ctx, Array.from(x, (v, i) => [fr.fx(v), fr.fy(y[i])]), c.marker, c.markerSize, k.edge, k.face, c.lineWidth); }
        return;
      }
      if (k === 'scatter') return this.scatter(ctx, ax, (xx, yy) => [fr.fx(xx), fr.fy(yy)], c, null);
      if (k === 'bubblechart') {
        // a bubble whose middle is in the box is drawn whole, the others not at all
        const r = fr.r, keep = c.clip === false;
        return this.scatter(ctx, ax, (xx, yy) => {
          const px = fr.fx(xx), py = fr.fy(yy);
          return keep || (px >= r.x - 0.5 && px <= r.x + r.w + 0.5 && py >= r.y - 0.5 && py <= r.y + r.h + 0.5) ? [px, py] : [NaN, NaN];
        }, c, null);
      }
      if (k === 'quiver') {
        const X = vec(decode(c.xData)), Y = vec(decode(c.yData)), U = vec(decode(c.uData)), V = vec(decode(c.vData));
        const s = c.scale || 1;
        ctx.save();
        ctx.strokeStyle = rgb(c.color);
        ctx.lineWidth = lw(c.lineWidth);
        if (c.lineStyle === 'none') { ctx.restore(); return; }
        dash(ctx, c.lineStyle, c.lineWidth);
        ctx.beginPath();
        for (let i = 0; i < X.length; i++) {
          if (!Number.isFinite(U[i]) || !Number.isFinite(V[i])) continue;
          const x0 = fr.fx(X[i]), y0 = fr.fy(Y[i]);
          const x1 = fr.fx(X[i] + U[i] * s), y1 = fr.fy(Y[i] + V[i] * s);
          arrowPath(ctx, x0, y0, x1, y1, c.maxHeadSize);
        }
        ctx.stroke();
        ctx.restore();
        return;
      }
      if (k === 'contour') return this.contour2(ctx, ax, fr, c);
      if (k === 'pie') return this.pie(ctx, ax, fr, c);
    }

    scatter(ctx, ax, map, c, depthOf) {
      const x = vec(decode(c.xData)), y = vec(decode(c.yData)), z = c.zData ? vec(decode(c.zData)) : null;
      const cd = c.cData ? vec(decode(c.cData)) : null;
      const rgbc = c.rgb ? decode(c.rgb) : null;
      const sd = c.sizeData ? vec(decode(c.sizeData)) : null;
      const bub = c.bubbleSize ? vec(decode(c.bubbleSize)) : null;
      const cmap = ax._cmap;
      const base = rgb(c.color);
      const order = [...Array(x.length).keys()];
      const proj = order.map((i) => (z ? map(x[i], y[i], z[i]) : map(x[i], y[i])));
      const diam = (i) => (bub.length === x.length ? bub[i] : bub[0]);
      if (z) order.sort((a, b) => proj[a][2] - proj[b][2]);
      // bubbles: the largest first, so that none hides a smaller one
      else if (bub) order.sort((a, b) => diam(b) - diam(a));
      if (!bub && (!c.marker || c.marker === 'none')) return;
      for (const i of order) {
        const [px, py] = proj[i];
        if (!Number.isFinite(px) || !Number.isFinite(py)) continue;
        let col = base;
        if (rgbc) col = rgb([rgbc.data[i * 3], rgbc.data[i * 3 + 1], rgbc.data[i * 3 + 2]]);
        else if (cd && cd.length === x.length) col = cmapColor(cmap, ax.clim, cd[i]) || base;
        if (bub) { this.bubble(ctx, px, py, diam(i) * PT, col, c); continue; }
        const area = sd ? (sd.length === x.length ? sd[i] : sd[0]) : 36;
        const size = Math.sqrt(Math.max(area, 0.5)) * 1.0;
        scatterMark(ctx, c, px, py, size, col);
      }
    }

    /* A bubble of diameter d (CSS px): its face see-through by MarkerFaceAlpha,
       its edge by MarkerEdgeAlpha; 'flat' takes the bubble's colour. */
    bubble(ctx, x, y, d, col, c) {
      if (!(d > 0)) return;
      const pick = (v) => (v === 'flat' || v === 'auto' ? col : Array.isArray(v) ? rgb(v) : null);
      const face = pick(c.mfc), edge = pick(c.mec);
      ctx.save();
      ctx.beginPath();
      markerPath(ctx, 'o', x, y, d);
      if (face) { ctx.globalAlpha = c.markerFaceAlpha ?? 1; ctx.fillStyle = face; ctx.fill(); }
      if (edge) { ctx.globalAlpha = c.markerEdgeAlpha ?? 1; ctx.strokeStyle = edge; ctx.lineWidth = lw(c.lineWidth); ctx.stroke(); }
      ctx.restore();
    }

    contour2(ctx, ax, fr, c) {
      const lines = decode(c.lines);
      const lev = vec(decode(c.lineLevels));
      const levels = vec(decode(c.levels));
      const cmap = ax._cmap;
      const clim = levels.length > 1 ? [levels[0], levels[levels.length - 1]] : ax.clim;
      if (c.fill) this.contourFill(ctx, ax, fr, c, levels, cmap);
      if (!lines) return;
      const d = lines.data;
      const n = lines.shape[0];
      let k = 0;
      ctx.save();
      ctx.lineWidth = lw(c.lineWidth);
      dash(ctx, c.lineStyle, c.lineWidth);
      ctx.beginPath();
      let started = false;
      let curColor = null;
      const flush = () => { if (started) { ctx.stroke(); ctx.beginPath(); started = false; } };
      const labelsAt = [];
      for (let i = 0; i < n; i++) {
        const x = d[i * 2], y = d[i * 2 + 1];
        if (!Number.isFinite(x)) { k += 1; started = false; ctx.stroke(); ctx.beginPath(); continue; }
        const L = lev[Math.min(k, lev.length - 1)];
        const col = c.edgeColor === 'flat' ? (cmapColor(cmap, c.fill ? ax.clim : clim, L) || AXIS_INK) : Array.isArray(c.edgeColor) ? rgb(c.edgeColor) : AXIS_INK;
        if (col !== curColor) { ctx.stroke(); ctx.beginPath(); curColor = col; ctx.strokeStyle = col; if (started) ctx.moveTo(fr.fx(x), fr.fy(y)); }
        if (!started) { ctx.moveTo(fr.fx(x), fr.fy(y)); started = true; if (c.showText && labelsAt.length < 400) labelsAt.push([fr.fx(x), fr.fy(y), L]); }
        else ctx.lineTo(fr.fx(x), fr.fy(y));
      }
      ctx.stroke();
      ctx.restore();
      if (c.showText) {
        for (const [px, py, L] of labelsAt) drawText(ctx, String(+L.toPrecision(4)), px, py, { size: 9 * PT, color: AXIS_INK, halign: 'center', valign: 'middle', background: 'rgba(255,255,255,0.75)', margin: 1 });
      }
    }

    /* Filled contours: each pixel takes the band of the value interpolated
       from the grid (rectilinear grids). */
    contourFill(ctx, ax, fr, c, levels, cmap) {
      const X = decode(c.xData), Y = decode(c.yData), Z = decode(c.zData);
      if (!X || !Z) return;
      const [m, n] = Z.shape;
      const xs = X.shape.length === 2 ? Array.from({ length: n }, (_, j) => at2(X, 0, j)) : Array.from(X.data);
      const ys = Y.shape.length === 2 ? Array.from({ length: m }, (_, i) => at2(Y, i, 0)) : Array.from(Y.data);
      const r = fr.r;
      const x0 = Math.max(r.x, Math.min(fr.fx(xs[0]), fr.fx(xs[n - 1])));
      const x1 = Math.min(r.x + r.w, Math.max(fr.fx(xs[0]), fr.fx(xs[n - 1])));
      const y0 = Math.max(r.y, Math.min(fr.fy(ys[0]), fr.fy(ys[m - 1])));
      const y1 = Math.min(r.y + r.h, Math.max(fr.fy(ys[0]), fr.fy(ys[m - 1])));
      const dpr = ctx.getTransform().a || 1;
      const W = Math.max(1, Math.round((x1 - x0) * dpr)), H = Math.max(1, Math.round((y1 - y0) * dpr));
      if (W * H > 9e6) return;
      const off = document.createElement('canvas');
      off.width = W; off.height = H;
      const o = off.getContext('2d');
      const img = o.createImageData(W, H);
      const incX = xs[n - 1] > xs[0], incY = ys[m - 1] > ys[0];
      const find = (arr, v, inc) => {
        let lo = 0, hi = arr.length - 1;
        if (inc ? v <= arr[0] : v >= arr[0]) return [0, 0];
        if (inc ? v >= arr[hi] : v <= arr[hi]) return [hi - 1, 1];
        while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (inc ? arr[mid] <= v : arr[mid] >= v) lo = mid; else hi = mid; }
        return [lo, (v - arr[lo]) / (arr[lo + 1] - arr[lo])];
      };
      const nl = levels.length;
      const bandRGB = [];
      const lo = levels[0], hi = levels[nl - 1];
      const clim = ax.clim;
      for (let b = 0; b <= nl; b++) {
        const v = b === 0 ? lo - (nl > 1 ? (levels[1] - levels[0]) : 1) : levels[b - 1];
        bandRGB.push(cmapRGB(cmap, clim, v));
      }
      const zd = Z.data;
      const colI = new Array(W), colT = new Array(W);
      for (let px = 0; px < W; px++) { const xv = fr.ix(x0 + (px + 0.5) / dpr); const f = find(xs, xv, incX); colI[px] = f[0]; colT[px] = f[1]; }
      for (let py = 0; py < H; py++) {
        const yv = fr.iy(y0 + (py + 0.5) / dpr);
        const [i, ty] = find(ys, yv, incY);
        for (let px = 0; px < W; px++) {
          const j = colI[px], tx = colT[px];
          const z00 = zd[i * n + j], z01 = zd[i * n + j + 1], z10 = zd[(i + 1) * n + j], z11 = zd[(i + 1) * n + j + 1];
          const z = (z00 * (1 - tx) + z01 * tx) * (1 - ty) + (z10 * (1 - tx) + z11 * tx) * ty;
          const k = (py * W + px) * 4;
          if (!Number.isFinite(z)) { img.data[k + 3] = 0; continue; }
          let b = 0;
          while (b < nl && z >= levels[b]) b++;
          const col = bandRGB[b];
          img.data[k] = col[0] * 255; img.data[k + 1] = col[1] * 255; img.data[k + 2] = col[2] * 255; img.data[k + 3] = 255;
        }
      }
      o.putImageData(img, 0, 0);
      ctx.save();
      ctx.imageSmoothingEnabled = true;
      ctx.drawImage(off, x0, y0, x1 - x0, y1 - y0);
      ctx.restore();
    }

    pie(ctx, ax, fr, c) {
      const f = vec(decode(c.frac)), ex = vec(decode(c.explode));
      const cols = decode(c.colors);
      const cx = fr.fx(0), cy = fr.fy(0);
      const R = Math.min(Math.abs(fr.fx(1) - cx), Math.abs(fr.fy(1) - cy)) * 0.8;
      let a = Math.PI / 2;
      const labels = c.labels || [];
      for (let i = 0; i < f.length; i++) {
        const da = f[i] * 2 * Math.PI;
        const mid = a - da / 2;
        const off = ex[i] ? R * 0.1 : 0;
        const ox = cx + off * Math.cos(mid), oy = cy - off * Math.sin(mid);
        ctx.beginPath();
        ctx.moveTo(ox, oy);
        ctx.arc(ox, oy, R, -a, -(a - da), false);
        ctx.closePath();
        ctx.fillStyle = cols ? rgb([cols.data[i * 3], cols.data[i * 3 + 1], cols.data[i * 3 + 2]]) : 'gray';
        ctx.fill();
        if (c.edgeColor !== 'none') {
          ctx.strokeStyle = Array.isArray(c.edgeColor) ? rgb(c.edgeColor) : AXIS_INK;
          ctx.lineWidth = lw(c.lineWidth || 0.5);
          ctx.stroke();
        }
        const lx = ox + R * 1.15 * Math.cos(mid), ly = oy - R * 1.15 * Math.sin(mid);
        drawText(ctx, labels[i] || '', lx, ly, { size: 10 * PT, halign: Math.cos(mid) >= 0 ? 'left' : 'right', valign: 'middle' });
        a -= da;
      }
    }

    /* ---- polar ---------------------------------------------------------------------- */
    drawPolar(ctx, ax, rect) {
      const cx = rect.x + rect.w / 2, cy = rect.y + rect.h / 2;
      const R = Math.min(rect.w, rect.h) / 2 * 0.86;
      let rmax = 0;
      // lines' radii in y, scatter series' in yData
      const radii = (c) => (c.type === 'line' || (c.type === 'patch' && c.y) ? c.y : c.type === 'series' && (c.kind === 'scatter' || c.kind === 'bubblechart') ? c.yData : null);
      for (const c of ax.children) if (radii(c)) for (const v of vec(decode(radii(c)))) if (Number.isFinite(v)) rmax = Math.max(rmax, Math.abs(v));
      if (!(rmax > 0)) rmax = 1;
      const ticks = niceTicks(0, rmax, 6);
      const top = ticks[ticks.length - 1] < rmax ? ticks[ticks.length - 1] + (ticks[1] - ticks[0]) : ticks[ticks.length - 1];
      const fs = ax.fontSize * PT;
      const tf = { interpreter: ax.tickLabelInterpreter || 'tex', bold: ax.fontWeight === 'bold', family: faceOf(ax.fontName) };
      ctx.save();
      if (ax.visible) {
        if (ax.color !== 'none') { ctx.fillStyle = rgb(ax.color); ctx.beginPath(); ctx.arc(cx, cy, R, 0, 2 * Math.PI); ctx.fill(); }
        // the grid: GridColor, its alpha as the Cartesian grid's (0.15 drawn 0.25), GridLineStyle
        ctx.strokeStyle = rgb(ax.gridColor || [0.15, 0.15, 0.15], Math.min(1, (ax.gridAlpha ?? 0.15) * 5 / 3));
        ctx.lineWidth = lw(0.5);
        dash(ctx, ax.gridLineStyle || '-', 0.5);
        if (ax.gridLineStyle !== 'none') {
          for (const t of ticks) { if (t <= 0) continue; ctx.beginPath(); ctx.arc(cx, cy, R * t / top, 0, 2 * Math.PI); ctx.stroke(); }
          for (let d = 0; d < 360; d += 30) {
            const a = d * Math.PI / 180;
            ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(cx + R * Math.cos(a), cy - R * Math.sin(a)); ctx.stroke();
          }
        }
        ctx.setLineDash([]);
        for (let d = 0; d < 360; d += 30) {
          const a = d * Math.PI / 180;
          drawText(ctx, `${d}°`, cx + (R + fs * 1.2) * Math.cos(a), cy - (R + fs * 1.2) * Math.sin(a), Object.assign({ size: fs, halign: 'center', valign: 'middle' }, tf));
        }
        ctx.strokeStyle = AXIS_INK;
        ctx.lineWidth = lw(ax.lineWidth || 0.5);
        ctx.beginPath(); ctx.arc(cx, cy, R, 0, 2 * Math.PI); ctx.stroke();
        for (const t of ticks) if (t > 0) drawText(ctx, String(+t.toPrecision(6)), cx + R * t / top * Math.cos(Math.PI / 12) + 2, cy - R * t / top * Math.sin(Math.PI / 12), Object.assign({ size: fs * 0.9, valign: 'bottom' }, tf));
      }
      ctx.beginPath(); ctx.arc(cx, cy, R, 0, 2 * Math.PI); ctx.clip();
      const at = (th, r) => [cx + R * r / top * Math.cos(th), cy - R * r / top * Math.sin(th)];
      for (const c of ax.children) {
        if (c.visible === false) continue;
        if (c.type === 'series' && (c.kind === 'scatter' || c.kind === 'bubblechart')) { this.scatter(ctx, ax, at, c, null); continue; }
        if (c.type === 'patch' && c.x && c.y) {
          // a polygon of angles and radii (polarhistogram's wedges)
          const th = vec(decode(c.x)), rr = vec(decode(c.y));
          ctx.beginPath();
          let first = true;
          for (let i = 0; i < th.length; i++) {
            if (!Number.isFinite(th[i]) || !Number.isFinite(rr[i])) continue;
            const q = at(th[i], rr[i]);
            if (first) { ctx.moveTo(q[0], q[1]); first = false; } else ctx.lineTo(q[0], q[1]);
          }
          ctx.closePath();
          if (Array.isArray(c.faceColor)) { ctx.save(); ctx.globalAlpha = c.faceAlpha ?? 1; ctx.fillStyle = rgb(c.faceColor); ctx.fill(); ctx.restore(); }
          if (Array.isArray(c.edgeColor) && c.lineStyle !== 'none') { ctx.save(); ctx.globalAlpha = c.edgeAlpha ?? 1; ctx.strokeStyle = rgb(c.edgeColor); ctx.lineWidth = lw(c.lineWidth); ctx.stroke(); ctx.restore(); }
          continue;
        }
        if (c.type !== 'line') continue;
        const th = vec(decode(c.x)), rr = vec(decode(c.y));
        const pts = [];
        for (let i = 0; i < th.length; i++) pts.push(Number.isFinite(th[i]) && Number.isFinite(rr[i]) ? [cx + R * rr[i] / top * Math.cos(th[i]), cy - R * rr[i] / top * Math.sin(th[i])] : null);
        if (c.lineStyle !== 'none') {
          ctx.strokeStyle = rgb(c.color); ctx.lineWidth = lw(c.lineWidth); dash(ctx, c.lineStyle, c.lineWidth);
          ctx.beginPath();
          let pen = false;
          for (const p of pts) { if (!p) { pen = false; continue; } if (pen) ctx.lineTo(p[0], p[1]); else { ctx.moveTo(p[0], p[1]); pen = true; } }
          ctx.stroke();
          ctx.setLineDash([]);
        }
        if (c.marker !== 'none') { const k = markerInk(c, rgb(c.color)); drawMarkers(ctx, pts.filter(Boolean), c.marker, c.markerSize, k.edge, k.face, c.lineWidth); }
      }
      ctx.restore();
      this.titles(ctx, ax, cx, rect.y - 4);
      this.frames.push({ ax, fr: { r: rect, polar: true, cx, cy, R, top }, rect, is3d: false });
    }

    /* ---- 3-D ---------------------------------------------------------------------- */
    draw3(ctx, ax, fr) {
      const fs = ax.fontSize * PT;
      const lims = fr.lims;
      const ticks = ['x', 'y', 'z'].map((w, k) => this.ticksFor(ax, w, { w: 220, h: 200 }, true));
      const corner = (sx, sy, sz) => fr.pn(sx * fr.box[0] / 2, sy * fr.box[1] / 2, sz * fr.box[2] / 2);
      // the back walls: for each axis, the wall facing away from the viewer
      const away = [fr.toward[0] > 0 ? -1 : 1, fr.toward[1] > 0 ? -1 : 1, fr.toward[2] > 0 ? -1 : 1];
      if (ax.visible) {
        ctx.save();
        ctx.lineWidth = lw(0.5);
        // wall fills
        ctx.fillStyle = rgb(ax.color);
        const walls = [
          [[away[0], -1, -1], [away[0], 1, -1], [away[0], 1, 1], [away[0], -1, 1]],
          [[-1, away[1], -1], [1, away[1], -1], [1, away[1], 1], [-1, away[1], 1]],
          [[-1, -1, away[2]], [1, -1, away[2]], [1, 1, away[2]], [-1, 1, away[2]]],
        ];
        for (const w of walls) {
          ctx.beginPath();
          w.forEach((c, i) => { const p = corner(...c); if (i) ctx.lineTo(p[0], p[1]); else ctx.moveTo(p[0], p[1]); });
          ctx.closePath();
          ctx.fill();
        }
        // grids on the walls
        ctx.strokeStyle = rgb(ax.gridColor, ax.gridAlpha);
        dash(ctx, ax.gridLineStyle, 0.5);
        ctx.beginPath();
        const grid = (k, on) => {
          if (!on) return;
          for (const t of ticks[k].ticks) {
            const nv = fr.norm(k, t) / (fr.box[k] / 2);
            if (!Number.isFinite(nv)) continue;
            // the two walls this axis' grid lines run across
            for (let other = 0; other < 3; other++) {
              if (other === k) continue;
              const third = 3 - k - other;
              const a = [0, 0, 0], b = [0, 0, 0];
              a[k] = nv; b[k] = nv;
              a[other] = away[other]; b[other] = away[other];
              a[third] = -1; b[third] = 1;
              const p = corner(...a), q = corner(...b);
              ctx.moveTo(p[0], p[1]); ctx.lineTo(q[0], q[1]);
            }
          }
        };
        grid(0, ax.xgrid); grid(1, ax.ygrid); grid(2, ax.zgrid);
        ctx.stroke();
        ctx.setLineDash([]);
        // the back edges of the box
        ctx.strokeStyle = AXIS_INK;
        ctx.lineWidth = lw(ax.lineWidth);
        ctx.beginPath();
        for (const w of walls) w.forEach((c, i) => { const p = corner(...c); const q = corner(...w[(i + 1) % 4]); ctx.moveTo(p[0], p[1]); ctx.lineTo(q[0], q[1]); });
        ctx.stroke();
        ctx.restore();
      }
      // the data, far to near
      this.scene3(ctx, ax, fr);
      if (ax.box && ax.visible) {
        ctx.save();
        ctx.strokeStyle = AXIS_INK;
        ctx.lineWidth = lw(ax.lineWidth);
        ctx.beginPath();
        for (const sx of [-1, 1]) for (const sy of [-1, 1]) for (const sz of [-1, 1]) {
          const p = corner(sx, sy, sz);
          for (const q of [corner(-sx, sy, sz), corner(sx, -sy, sz), corner(sx, sy, -sz)]) { ctx.moveTo(p[0], p[1]); ctx.lineTo(q[0], q[1]); }
        }
        ctx.stroke();
        ctx.restore();
      }
      if (!ax.visible) return;
      // ticks and labels on the front-bottom edges
      const turned = !!ax.camUp;
      const outerEdge = (k) => {
        // with the view turned by CameraUpVector: an axis running across the screen on its lowest edge, one running up it on its left-most
        const u = [0, 0, 0]; u[k] = 1;
        const p0 = corner(0, 0, 0), p1 = corner(...u);
        const across = Math.abs(p1[0] - p0[0]) >= Math.abs(p1[1] - p0[1]);
        let best = null;
        for (const s1 of [-1, 1]) for (const s2 of [-1, 1]) {
          const a = [0, 0, 0];
          const o = [0, 1, 2].filter((i) => i !== k);
          a[o[0]] = s1; a[o[1]] = s2;
          const p = corner(...a);
          const score = across ? p[1] : -p[0];
          if (!best || score > best.score) best = { a, score };
        }
        return best.a;
      };
      const edgeFor = (k) => {
        if (turned) return outerEdge(k);
        // the edge parallel to axis k that lies lowest on screen at the front
        let best = null;
        for (const s1 of [-1, 1]) for (const s2 of [-1, 1]) {
          const a = [0, 0, 0];
          const o = [0, 1, 2].filter((i) => i !== k);
          a[o[0]] = s1; a[o[1]] = s2;
          if (k !== 2 && a[2] !== -1) continue;
          const p = corner(...a.map((v, i) => (i === k ? 0 : v)));
          const score = k === 2 ? -p[0] : p[1];
          if (!best || score > best.score) best = { a, score };
        }
        return best.a;
      };
      const zEdge = turned ? outerEdge(2) : (() => {
        // the z axis on the left-most vertical edge
        let best = null;
        for (const sx of [-1, 1]) for (const sy of [-1, 1]) {
          const p = corner(sx, sy, 0);
          if (!best || p[0] < best.x) best = { x: p[0], a: [sx, sy, 0] };
        }
        return best.a;
      })();
      ctx.save();
      ctx.lineWidth = lw(ax.lineWidth);
      const tf = { interpreter: ax.tickLabelInterpreter || 'tex', bold: ax.fontWeight === 'bold', family: faceOf(ax.fontName) };
      for (let k = 0; k < 3; k++) {
        const a = k === 2 ? zEdge : edgeFor(k);
        const t = ticks[k];
        // each axis in its own colour (XColor, YColor, ZColor)
        const inkK = rgb([ax.xcolor, ax.ycolor, ax.zcolor][k] || [0.15, 0.15, 0.15]);
        ctx.strokeStyle = inkK;
        const isTop = Math.abs(ax.view[1]) === 90;
        if (isTop && k === 2) continue;
        const center = corner(0, 0, 0);
        t.ticks.forEach((tv, i) => {
          const nv = fr.norm(k, tv) / (fr.box[k] / 2);
          if (!Number.isFinite(nv)) return;
          const pa = a.slice(); pa[k] = nv;
          const p = corner(...pa);
          // the label sits outward from the box's centre
          let dx = p[0] - center[0], dy = p[1] - center[1];
          if (k === 2 && !turned) { dx = -1; dy = 0; }
          const L = Math.hypot(dx, dy) || 1;
          dx /= L; dy /= L;
          ctx.beginPath(); ctx.moveTo(p[0], p[1]); ctx.lineTo(p[0] + dx * 5, p[1] + dy * 5); ctx.stroke();
          drawText(ctx, t.labels[i], p[0] + dx * 9, p[1] + dy * 9, Object.assign({ size: fs, color: inkK, halign: dx > 0.3 ? 'left' : dx < -0.3 ? 'right' : 'center', valign: dy > 0.3 ? 'top' : dy < -0.3 ? 'bottom' : 'middle' }, tf));
        });
        const lab = [ax.xlabel, ax.ylabel, ax.zlabel][k];
        if (lab.string && lab.visible !== false) {
          const pa = a.slice(); pa[k] = 0;
          const p = corner(...pa);
          let dx = p[0] - center[0], dy = p[1] - center[1];
          if (k === 2 && !turned) { dx = -1; dy = 0; }
          const L = Math.hypot(dx, dy) || 1;
          dx /= L; dy /= L;
          this.textOf(lab, ctx, lab.string, p[0] + dx * (fs * 3.2), p[1] + dy * (fs * 2.4), { size: lab.fontSize * PT * (ax.labelSize ?? 1.1), halign: 'center', valign: 'middle', rotation: k === 2 ? 90 : 0, interpreter: lab.interpreter,
            color: rgb(lab.color === 'none' ? [0, 0, 0] : lab.color), bold: lab.fontWeight === 'bold', italic: lab.fontAngle === 'italic', family: faceOf(lab.fontName) });
        }
      }
      ctx.restore();
      let minY = Infinity;
      for (const sx of [-1, 1]) for (const sy of [-1, 1]) for (const sz of [-1, 1]) minY = Math.min(minY, corner(sx, sy, sz)[1]);
      this.titles(ctx, ax, fr.r.x + fr.r.w / 2, Math.max(fs * 1.2, minY - 8));
    }

    scene3(ctx, ax, fr) {
      const items = [];          // {depth, draw}
      const cmap = ax._cmap;
      const lights = ax.children.filter((c) => c.type === 'light');
      const lightDir = lights.length ? (() => { const p = lights[0].position; const L = Math.hypot(...p) || 1; return p.map((v) => v / L); })() : null;
      for (const c of ax.children) {
        if (c.visible === false) continue;
        if (c.type === 'surface') this.surface3(items, ax, fr, c, cmap, lightDir);
        else if (c.type === 'line') {
          const x = vec(decode(c.x)), y = vec(decode(c.y)), z = c.z ? vec(decode(c.z)) : null;
          const n = Math.min(x.length, y.length);
          const P = [];
          for (let i = 0; i < n; i++) P.push(fr.p(x[i], y[i], z ? z[i] : fr.lims[2][0]));
          const col = rgb(c.color);
          if (c.lineStyle !== 'none') {
            for (let i = 0; i + 1 < n; i++) {
              const a = P[i], b = P[i + 1];
              if (!Number.isFinite(a[0] + a[1] + b[0] + b[1])) continue;
              items.push({ d: (a[2] + b[2]) / 2 + 1e-6, f: () => { ctx.strokeStyle = col; ctx.lineWidth = lw(c.lineWidth); dash(ctx, c.lineStyle, c.lineWidth); ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke(); ctx.setLineDash([]); } });
            }
          }
          if (c.marker && c.marker !== 'none') {
            for (const p of P) if (Number.isFinite(p[0] + p[1])) items.push({ d: p[2] + 2e-6, f: () => drawMarkers(ctx, [[p[0], p[1]]], c.marker, c.markerSize, c.mec === 'auto' ? col : rgb(c.mec), c.mfc === 'none' ? null : c.mfc === 'auto' ? col : rgb(c.mfc), c.lineWidth) });
          }
        } else if (c.type === 'series' && (c.kind === 'scatter' || c.kind === 'bubblechart')) {
          const x = vec(decode(c.xData)), y = vec(decode(c.yData)), z = c.zData ? vec(decode(c.zData)) : null;
          const cd = c.cData ? vec(decode(c.cData)) : null;
          const rgbc = c.rgb ? decode(c.rgb) : null;
          const sd = c.sizeData ? vec(decode(c.sizeData)) : null;
          const bub = c.bubbleSize ? vec(decode(c.bubbleSize)) : null;
          for (let i = 0; i < x.length; i++) {
            const p = fr.p(x[i], y[i], z ? z[i] : fr.lims[2][0]);
            if (!Number.isFinite(p[0] + p[1])) continue;
            let col = rgb(c.color);
            if (rgbc) col = rgb([rgbc.data[i * 3], rgbc.data[i * 3 + 1], rgbc.data[i * 3 + 2]]);
            else if (cd && cd.length === x.length) col = cmapColor(cmap, ax.clim, cd[i]) || col;
            if (bub) { const d = (bub.length === x.length ? bub[i] : bub[0]) * PT; items.push({ d: p[2], f: () => this.bubble(ctx, p[0], p[1], d, col, c) }); continue; }
            const size = Math.sqrt(sd ? (sd.length === x.length ? sd[i] : sd[0]) : 36);
            if (c.marker && c.marker !== 'none') items.push({ d: p[2], f: () => scatterMark(ctx, c, p[0], p[1], size, col) });
          }
        } else if (c.type === 'series' && c.kind === 'contour') {
          const lines = decode(c.lines);
          const lev = vec(decode(c.lineLevels));
          const levels = vec(decode(c.levels));
          if (!lines) continue;
          const d = lines.data;
          let k = 0;
          let prev = null;
          const clim = levels.length > 1 ? [levels[0], levels[levels.length - 1]] : ax.clim;
          for (let i = 0; i < lines.shape[0]; i++) {
            const x = d[i * 2], y = d[i * 2 + 1];
            if (!Number.isFinite(x)) { k++; prev = null; continue; }
            const L = lev[Math.min(k, lev.length - 1)];
            const zz = c.zplane != null ? c.zplane : (c.is3d ? L : fr.lims[2][0]);
            const p = fr.p(x, y, zz);
            if (prev) {
              const a = prev, b = p;
              const col = c.edgeColor === 'flat' ? cmapColor(cmap, clim, L) : Array.isArray(c.edgeColor) ? rgb(c.edgeColor) : AXIS_INK;
              items.push({ d: (a[2] + b[2]) / 2, f: () => { ctx.strokeStyle = col; ctx.lineWidth = lw(c.lineWidth); ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke(); } });
            }
            prev = p;
          }
        } else if (c.type === 'patch') {
          for (const poly of patchPolys(c)) {
            const P = poly.pts.map(([x, y, z]) => fr.p(x, y, z == null ? fr.lims[2][0] : z));
            if (P.length < 2) continue;
            const d = P.reduce((s, p) => s + p[2], 0) / P.length;
            const fill = poly.open ? null : Array.isArray(c.faceColor) ? rgb(c.faceColor, c.faceAlpha) : (poly.c != null && c.faceColor !== 'none' ? cmapColor(cmap, ax.clim, poly.c, c.faceAlpha) : null);
            const edge = c.edgeColor === 'none' ? null : Array.isArray(c.edgeColor) ? rgb(c.edgeColor)
              : ((c.edgeColor === 'flat' || c.edgeColor === 'interp') && poly.c != null) ? cmapColor(cmap, ax.clim, poly.c) : AXIS_INK;
            const fin = P.filter((p) => Number.isFinite(p[0]) && Number.isFinite(p[1]));
            if (fin.length < 2) continue;
            const dd = fin.reduce((s, p) => s + p[2], 0) / fin.length;
            items.push({ d: poly.open ? dd : d, f: () => {
              ctx.beginPath();
              if (poly.open) {
                let start = true;
                for (const p of P) {
                  if (!Number.isFinite(p[0]) || !Number.isFinite(p[1])) { start = true; continue; }
                  if (start) ctx.moveTo(p[0], p[1]); else ctx.lineTo(p[0], p[1]);
                  start = false;
                }
              } else {
                P.forEach((p, i) => (i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1])));
                ctx.closePath();
              }
              if (fill) { ctx.fillStyle = fill; ctx.fill(); }
              if (edge) { ctx.strokeStyle = edge; ctx.lineWidth = lw(c.lineWidth); ctx.stroke(); }
            } });
          }
        } else if (c.type === 'text') {
          const p = fr.p(c.position[0], c.position[1], c.position[2] || 0);
          items.push({ d: p[2] + 1, f: () => drawText(ctx, c.string, p[0], p[1], { size: c.fontSize * PT, color: rgb(c.color), halign: c.halign, valign: c.valign, interpreter: c.interpreter }) });
        } else if (c.type === 'series' && c.kind === 'quiver' && c.lineStyle !== 'none') {
          // quiver3's arrows from (X, Y, Z) along (U, V, W); a 2-D quiver's on the floor
          const X = vec(decode(c.xData)), Y = vec(decode(c.yData)), U = vec(decode(c.uData)), V = vec(decode(c.vData));
          const Z = c.zData ? vec(decode(c.zData)) : null, W = c.wData ? vec(decode(c.wData)) : null;
          const s = c.scale || 1;
          for (let i = 0; i < X.length; i++) {
            const z0 = Z ? Z[i] : fr.lims[2][0], dz = Z && W ? W[i] * s : 0;
            const a = fr.p(X[i], Y[i], z0), b = fr.p(X[i] + U[i] * s, Y[i] + V[i] * s, z0 + dz);
            if (!Number.isFinite(a[0] + a[1] + b[0] + b[1])) continue;
            items.push({ d: (a[2] + b[2]) / 2, f: () => {
              ctx.strokeStyle = rgb(c.color); ctx.lineWidth = lw(c.lineWidth); dash(ctx, c.lineStyle, c.lineWidth);
              ctx.beginPath(); arrowPath(ctx, a[0], a[1], b[0], b[1], c.maxHeadSize); ctx.stroke(); ctx.setLineDash([]);
            } });
          }
        }
      }
      items.sort((a, b) => a.d - b.d);
      ctx.save();
      for (const it of items) it.f(ctx);
      ctx.restore();
    }

    surface3(items, ax, fr, c, cmap, lightDir) {
      const X = decode(c.x), Y = decode(c.y), Z = decode(c.z);
      if (!Z) return;
      const Cd = c.c ? decode(c.c) : Z;
      const [m, n] = Z.shape.length === 2 ? Z.shape : [1, Z.shape[0]];
      const gx = (i, j) => (X.shape.length === 2 && X.shape[0] === m ? at2(X, i, j) : X.data[j]);
      const gy = (i, j) => (Y.shape.length === 2 && Y.shape[0] === m ? at2(Y, i, j) : Y.data[i]);
      const rgbC = Cd.shape.length === 3;
      const gc = (i, j) => (Cd.shape.length >= 2 ? Cd.data[(i * Cd.shape[1] + j) * (rgbC ? 3 : 1)] : Cd.data[j]);
      const P = new Array(m);
      for (let i = 0; i < m; i++) { P[i] = new Array(n); for (let j = 0; j < n; j++) P[i][j] = fr.p(gx(i, j), gy(i, j), at2(Z, i, j)); }
      const faceMode = c.faceColor;
      // LineStyle none: no mesh lines, as EdgeColor none
      const edgeMode = c.lineStyle === 'none' ? 'none' : c.edgeColor;
      const alpha = typeof c.faceAlpha === 'number' ? c.faceAlpha : 1;
      const clim = ax.clim;
      const lit = lightDir && c.lighting !== 'none';
      const shade = (col, i, j) => {
        if (!lit) return col;
        // the face's normal from two edges, in data-normalised space
        const nrm = (k, a, b) => fr.norm(k, a) - fr.norm(k, b);
        const ux = nrm(0, gx(i, j + 1), gx(i, j)), uy = nrm(1, gy(i, j + 1), gy(i, j)), uz = nrm(2, at2(Z, i, j + 1), at2(Z, i, j));
        const vx = nrm(0, gx(i + 1, j), gx(i, j)), vy = nrm(1, gy(i + 1, j), gy(i, j)), vz = nrm(2, at2(Z, i + 1, j), at2(Z, i, j));
        let nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx;
        const L = Math.hypot(nx, ny, nz) || 1;
        nx /= L; ny /= L; nz /= L;
        const d = Math.abs(nx * lightDir[0] + ny * lightDir[1] + nz * lightDir[2]);
        const f = 0.35 + 0.65 * d;
        return [col[0] * f, col[1] * f, col[2] * f];
      };
      for (let i = 0; i < m - 1; i++) {
        for (let j = 0; j < n - 1; j++) {
          const q = [P[i][j], P[i][j + 1], P[i + 1][j + 1], P[i + 1][j]];
          if (q.some((p) => !Number.isFinite(p[0] + p[1] + p[2]))) continue;
          const d = (q[0][2] + q[1][2] + q[2][2] + q[3][2]) / 4;
          let fill = null, grad = null;
          if (Array.isArray(faceMode)) fill = shade(faceMode, i, j);
          else if (faceMode === 'flat' || faceMode === 'texturemap') {
            fill = rgbC ? [Cd.data[(i * n + j) * 3], Cd.data[(i * n + j) * 3 + 1], Cd.data[(i * n + j) * 3 + 2]] : (Number.isFinite(gc(i, j)) ? cmapRGB(cmap, clim, gc(i, j)) : null);
            if (fill) fill = shade(fill, i, j);
          } else if (faceMode === 'interp') {
            const vals = [gc(i, j), gc(i, j + 1), gc(i + 1, j + 1), gc(i + 1, j)];
            if (vals.every(Number.isFinite)) grad = { vals, i, j };
          }
          const edge = edgeMode === 'none' ? null : Array.isArray(edgeMode) ? edgeMode : (Number.isFinite(gc(i, j)) ? cmapRGB(cmap, clim, gc(i, j)) : null);
          items.push({
            d,
            f: (g) => {
              g.beginPath();
              g.moveTo(q[0][0], q[0][1]); g.lineTo(q[1][0], q[1][1]); g.lineTo(q[2][0], q[2][1]); g.lineTo(q[3][0], q[3][1]);
              g.closePath();
              if (fill) { g.fillStyle = rgb(fill, alpha); g.fill(); }
              else if (grad) this.interpQuad(g, q, grad.vals, cmap, clim, alpha, (col) => shade(col, grad.i, grad.j));
              if (edge) { g.strokeStyle = rgb(edge, c.edgeAlpha); g.lineWidth = c.lineWidth; dash(g, c.lineStyle || '-', c.lineWidth); g.stroke(); g.setLineDash([]); }
              else if (fill && alpha === 1) { g.strokeStyle = rgb(fill); g.lineWidth = 0.5; g.stroke(); }
            },
          });
        }
      }
    }

    /* Interpolated colour over a quad: two triangles, each filled with a
       linear gradient along the direction its value changes most. */
    interpQuad(ctx, q, vals, cmap, clim, alpha, shade) {
      const tri = (a, b, cc, va, vb, vc) => {
        // solve v = p*x + r*y + s through the three points
        const det = (b[0] - a[0]) * (cc[1] - a[1]) - (cc[0] - a[0]) * (b[1] - a[1]);
        ctx.save();
        ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.lineTo(cc[0], cc[1]); ctx.closePath();
        if (Math.abs(det) < 1e-9) { ctx.fillStyle = rgb(shade(cmapRGB(cmap, clim, (va + vb + vc) / 3)), alpha); ctx.fill(); ctx.restore(); return; }
        const p = ((vb - va) * (cc[1] - a[1]) - (vc - va) * (b[1] - a[1])) / det;
        const r = ((vc - va) * (b[0] - a[0]) - (vb - va) * (cc[0] - a[0])) / det;
        const g2 = p * p + r * r;
        if (g2 < 1e-24) { ctx.fillStyle = rgb(shade(cmapRGB(cmap, clim, va)), alpha); ctx.fill(); ctx.restore(); return; }
        const lo = Math.min(va, vb, vc), hi = Math.max(va, vb, vc);
        // points where the value is lo and hi along the gradient through a
        const t0 = (lo - va) / g2, t1 = (hi - va) / g2;
        const gr = ctx.createLinearGradient(a[0] + p * t0, a[1] + r * t0, a[0] + p * t1, a[1] + r * t1);
        const steps = 6;
        for (let s = 0; s <= steps; s++) {
          const v = lo + (hi - lo) * s / steps;
          gr.addColorStop(s / steps, rgb(shade(cmapRGB(cmap, clim, v)), alpha));
        }
        ctx.fillStyle = gr;
        ctx.fill();
        ctx.lineWidth = 0.6;
        ctx.strokeStyle = gr;
        ctx.stroke();
        ctx.restore();
      };
      tri(q[0], q[1], q[2], vals[0], vals[1], vals[2]);
      tri(q[0], q[2], q[3], vals[0], vals[2], vals[3]);
    }

    /* ---- legends and colorbars ---------------------------------------------------------- */
    drawLegend(ctx, ax, rect, lg, cmap) {
      const fs = lg.fontSize * PT;
      const entries = lg.entries.filter((e) => e.name !== undefined);
      if (!entries.length) return;
      const sample = 30;
      const pad = 6;
      const rowH = fs * 1.35;
      const cols = Math.max(1, lg.orientation === 'horizontal' ? entries.length : (lg.numColumns || 1));
      const widths = entries.map((e) => textSize(ctx, e.name, fs, { interpreter: lg.interpreter }).width);
      const colW = Math.max(...widths) + sample + 10;
      const rows = Math.ceil(entries.length / cols);
      // its Title, bold and centred above the entries
      const title = Array.isArray(lg.title) ? lg.title.join('\n') : (lg.title || '');
      const tsz = title ? textSize(ctx, title, fs, { interpreter: lg.interpreter, bold: true }) : null;
      const titleH = tsz ? tsz.height + 2 : 0;
      const W = Math.max(cols * colW + pad * 2 - 4, tsz ? tsz.width + pad * 2 : 0);
      const H = rows * rowH + pad * 2 - 2 + titleH;
      const loc = lg.location || 'northeast';
      let x, y;
      const m = 8;
      const best = loc === 'best' ? this.bestCorner(ax, rect, W, H) : loc;
      switch (best) {
        case 'northwest': x = rect.x + m; y = rect.y + m; break;
        case 'southwest': x = rect.x + m; y = rect.y + rect.h - H - m; break;
        case 'southeast': x = rect.x + rect.w - W - m; y = rect.y + rect.h - H - m; break;
        case 'north': x = rect.x + (rect.w - W) / 2; y = rect.y + m; break;
        case 'south': x = rect.x + (rect.w - W) / 2; y = rect.y + rect.h - H - m; break;
        case 'east': x = rect.x + rect.w - W - m; y = rect.y + (rect.h - H) / 2; break;
        case 'west': x = rect.x + m; y = rect.y + (rect.h - H) / 2; break;
        case 'northeastoutside': case 'eastoutside': x = rect.x + rect.w + 10; y = rect.y; break;
        case 'northoutside': x = rect.x + (rect.w - W) / 2; y = rect.y - H - 30; break;
        case 'southoutside': x = rect.x + (rect.w - W) / 2; y = rect.y + rect.h + 40; break;
        default: x = rect.x + rect.w - W - m; y = rect.y + m;
      }
      ctx.save();
      if (lg.box) {
        ctx.fillStyle = rgb(lg.color);
        ctx.fillRect(x, y, W, H);
        ctx.strokeStyle = rgb(lg.edgeColor);
        ctx.lineWidth = lw(0.5);
        ctx.strokeRect(x, y, W, H);
      }
      if (title) drawText(ctx, title, x + W / 2, y + pad - 1, { size: fs, color: rgb(lg.textColor), halign: 'center', valign: 'top', bold: true, interpreter: lg.interpreter });
      entries.forEach((e, i) => {
        const col = i % cols, row = Math.floor(i / cols);
        const ex = x + pad + col * colW, ey = y + pad + titleH + row * rowH + rowH / 2;
        const isPatch = e.type === 'patch' || e.type === 'surface' || (e.type === 'series' && ['bar', 'histogram', 'area', 'pie'].includes(e.kind));
        if (isPatch) {
          const fc = Array.isArray(e.faceColor) ? rgb(e.faceColor, e.faceAlpha ?? 1) : 'rgb(0,114,189)';
          ctx.fillStyle = fc;
          ctx.fillRect(ex + 2, ey - fs * 0.4, sample - 6, fs * 0.8);
          ctx.strokeStyle = Array.isArray(e.edgeColor) ? rgb(e.edgeColor) : AXIS_INK;
          ctx.lineWidth = lw(0.5);
          ctx.strokeRect(ex + 2, ey - fs * 0.4, sample - 6, fs * 0.8);
        } else {
          const col = rgb(e.color || [0, 0.447, 0.741]);
          if (e.type === 'series' && e.kind === 'bubblechart') {
            this.bubble(ctx, ex + (sample - 4) / 2, ey, fs * 0.8, col, { mfc: e.markerFaceColor, mec: e.markerEdgeColor, markerFaceAlpha: e.markerFaceAlpha, lineWidth: e.lineWidth });
          } else if (e.lineStyle !== 'none' && !(e.type === 'series' && e.kind === 'scatter')) {
            ctx.strokeStyle = col;
            ctx.lineWidth = e.lineWidth || 0.5;
            dash(ctx, e.lineStyle, e.lineWidth || 0.5);
            ctx.beginPath(); ctx.moveTo(ex, ey); ctx.lineTo(ex + sample - 4, ey); ctx.stroke();
            ctx.setLineDash([]);
          }
          const mk = e.type === 'series' && e.kind === 'scatter' ? (e.marker === 'none' ? 'o' : e.marker) : e.type === 'series' && e.kind === 'bubblechart' ? 'none' : e.marker;
          if (mk && mk !== 'none') drawMarkers(ctx, [[ex + (sample - 4) / 2, ey]], mk, e.markerSize || 6, e.markerEdgeColor === 'auto' || e.markerEdgeColor === 'flat' || !e.markerEdgeColor ? col : rgb(e.markerEdgeColor), e.markerFaceColor === 'none' || !e.markerFaceColor ? null : (e.markerFaceColor === 'auto' || e.markerFaceColor === 'flat' ? col : rgb(e.markerFaceColor)));
        }
        drawText(ctx, e.name, ex + sample + 2, ey, { size: fs, color: rgb(lg.textColor), valign: 'middle', interpreter: lg.interpreter });
      });
      ctx.restore();
      this.frames.push({ legend: lg, rect: { x, y, w: W, h: H } });
    }

    bestCorner(ax, rect, W, H) {
      const corners = ['northeast', 'northwest', 'southeast', 'southwest'];
      const fr = this.frames.find((f) => f.ax === ax)?.fr;
      if (!fr || !fr.fx) return 'northeast';
      const count = { northeast: 0, northwest: 0, southeast: 0, southwest: 0 };
      const box = (c) => ({
        northeast: [rect.x + rect.w - W - 8, rect.y + 8], northwest: [rect.x + 8, rect.y + 8],
        southeast: [rect.x + rect.w - W - 8, rect.y + rect.h - H - 8], southwest: [rect.x + 8, rect.y + rect.h - H - 8],
      })[c];
      for (const c of ax.children) {
        if (c.type !== 'line') continue;
        const x = vec(decode(c.x)), y = vec(decode(c.y));
        const step = Math.max(1, Math.floor(x.length / 400));
        for (let i = 0; i < x.length; i += step) {
          const px = fr.fx(x[i]), py = fr.fy(y[i]);
          for (const k of corners) { const [bx, by] = box(k); if (px >= bx && px <= bx + W && py >= by && py <= by + H) count[k]++; }
        }
      }
      return corners.reduce((a, b) => (count[b] < count[a] ? b : a));
    }

    drawColorbar(ctx, ax, rect, cb, cmap) {
      const fs = cb.fontSize * PT;
      const horiz = /^(south|north)/.test(cb.location);
      let x, y, w, h;
      if (horiz) { w = rect.w; h = 12; x = rect.x; y = rect.y + rect.h + 34; }
      else { w = 14; h = rect.h; x = rect.x + rect.w + 14; y = rect.y; }
      if (cb.location === 'east') { x = rect.x + rect.w - 30; y = rect.y + 10; h = rect.h - 20; }
      const n = cmap.shape[0];
      // Direction reverse: the colours and the ticks run the other way
      const rev = cb.direction === 'reverse';
      for (let k = 0; k < n; k++) {
        const j = rev ? n - 1 - k : k;
        ctx.fillStyle = rgb([cmap.data[j * 3], cmap.data[j * 3 + 1], cmap.data[j * 3 + 2]]);
        if (horiz) ctx.fillRect(x + w * k / n, y, w / n + 0.5, h);
        else ctx.fillRect(x, y + h - h * (k + 1) / n, w, h / n + 0.5);
      }
      ctx.strokeStyle = rgb(cb.color);
      ctx.lineWidth = lw(0.5);
      if (cb.box !== false) ctx.strokeRect(x, y, w, h);
      const lim = ax.clim;
      const ticks = cb.ticks || niceTicks(lim[0], lim[1], 9);
      const { labels, exp } = cb.tickLabels ? { labels: cb.tickLabels, exp: null } : tickLabels(ticks, false);
      // TickDirection: in (into the bar), out, or both
      const tin = cb.tickDirection !== 'out' ? 3 : 0, tout = cb.tickDirection === 'out' || cb.tickDirection === 'both' ? 3 : 0;
      ctx.beginPath();
      ticks.forEach((t, i) => {
        let f = (t - lim[0]) / (lim[1] - lim[0]);
        if (f < -1e-9 || f > 1 + 1e-9) return;
        if (rev) f = 1 - f;
        if (horiz) { const px = x + f * w; ctx.moveTo(px, y + h + tout); ctx.lineTo(px, y + h - tin); drawText(ctx, labels[i] ?? '', px, y + h + 3 + tout, { size: fs, halign: 'center', valign: 'top', color: rgb(cb.color) }); }
        else { const py = y + h - f * h; ctx.moveTo(x + w + tout, py); ctx.lineTo(x + w - tin, py); drawText(ctx, labels[i] ?? '', x + w + 4 + tout, py, { size: fs, valign: 'middle', color: rgb(cb.color) }); }
      });
      ctx.stroke();
      if (exp !== null) drawText(ctx, `\\times10^{${exp}}`, x, y - 4, { size: fs, valign: 'bottom', color: rgb(cb.color) });
      // where it is, for a click in the figure's edit mode (with its tick labels)
      this.frames.push({ colorbar: cb, rect: horiz ? { x, y, w, h: h + fs * 1.4 + 3 } : { x, y, w: w + fs * 2.6 + 4, h } });
      const L = cb.label;
      if (L && L.string && L.visible !== false) {
        const o = { size: L.fontSize * PT, color: rgb(L.color === 'none' ? [0, 0, 0] : L.color), bold: L.fontWeight === 'bold', italic: L.fontAngle === 'italic',
          family: faceOf(L.fontName), interpreter: L.interpreter, background: Array.isArray(L.background) ? rgb(L.background) : null,
          edge: Array.isArray(L.edge) ? rgb(L.edge) : null, margin: L.margin, boxWidth: L.lineWidth ? lw(L.lineWidth) : null };
        if (horiz) this.textOf(L, ctx, L.string, x + w / 2, y + h + fs * 1.6 + 4, Object.assign(o, { halign: 'center', valign: 'top' }));
        else this.textOf(L, ctx, L.string, x + w + fs * 3.4, y + h / 2, Object.assign(o, { halign: 'center', valign: 'middle', rotation: -90 }));
      }
    }
  }

  /* The polygons of a patch: [{pts: [[x, y, z]], c}] */
  /* Where an annotation is on a canvas W by H: a box, or a line's two ends for the line kinds. */
  function shapeBox(a, W, H) {
    if (!a.shape) return null;
    const u = a.units && a.units !== 'normalized' ? (PL.uiUnits && PL.uiUnits[a.units]) || [1, 1] : null;
    const px = (x) => (u ? x * u[0] : x * W), py = (y) => H - (u ? y * u[1] : y * H);
    if (a.x && a.y) return { line: [px(a.x[0]), py(a.y[0]), px(a.x[1]), py(a.y[1])] };
    const p = a.position;
    const x = px(p[0]), y = py(p[1] + p[3]), w = px(p[0] + p[2]) - x, h = py(p[1]) - y;
    return { x: Math.min(x, x + w), y: Math.min(y, y + h), w: Math.abs(w), h: Math.abs(h) };
  }

  /* An arrowhead (a graph plot's digraph edge) at the end of the segment a -> b, drawn in screen space so that the
     axes' aspect does not bend it: size points long, its tip back from b by back points (the node's marker). */
  function arrowHead(ctx, fr, [a, b], size, back, style) {
    const x0 = fr.fx(a[0]), y0 = fr.fy(a[1]), x1 = fr.fx(b[0]), y1 = fr.fy(b[1]);
    const len = Math.hypot(x1 - x0, y1 - y0);
    if (![x0, y0, x1, y1].every(Number.isFinite) || len < 1) return;
    const ux = (x1 - x0) / len, uy = (y1 - y0) / len;
    const L = Math.min(size * PT, len * 0.45), t = Math.min(back * PT, len * 0.3);
    const tx = x1 - ux * t, ty = y1 - uy * t, bx = tx - ux * L, by = ty - uy * L, w = L * 0.38;
    ctx.save();
    ctx.fillStyle = style;
    ctx.beginPath();
    ctx.moveTo(tx, ty);
    ctx.lineTo(bx - uy * w, by + ux * w);
    ctx.lineTo(bx + uy * w, by - ux * w);
    ctx.closePath();
    ctx.fill();
    ctx.restore();
  }

  function patchPolys(c) {
    const out = [];
    if (c.faces && c.vertices) {
      const F = decode(c.faces), V = decode(c.vertices);
      const fvc = c.fvc ? decode(c.fvc) : null;
      const nv = V.shape[1] || 2;
      const nf = F.shape[0], k = F.shape[1] || F.shape[0];
      // FaceVertexCData: a value (or an RGB row) for each face, or for each vertex (a face then gets its vertices' mean)
      const rows = fvc ? fvc.shape[0] : 0, width = fvc && fvc.shape.length > 1 ? fvc.shape[1] : 1;
      const perVertex = fvc && rows === V.shape[0] && rows !== nf;
      const colorOf = (r) => (width === 3 ? [fvc.data[r * 3], fvc.data[r * 3 + 1], fvc.data[r * 3 + 2]] : fvc.data[r * width]);
      for (let i = 0; i < nf; i++) {
        const pts = [];
        const idx = [];
        for (let j = 0; j < k; j++) {
          const vi = F.data[i * k + j];
          if (!Number.isFinite(vi)) break;
          const b = (vi - 1) * nv;
          pts.push([V.data[b], V.data[b + 1], nv > 2 ? V.data[b + 2] : null]);
          idx.push(vi - 1);
        }
        // a NaN vertex leaves the face open: no fill, its edge broken there and not closed
        const open = pts.some(([x, y, z]) => !Number.isFinite(x) || !Number.isFinite(y) || (z != null && !Number.isFinite(z)));
        let col = null;
        if (fvc && perVertex && idx.length) {
          const cs = idx.map(colorOf);
          col = width === 3 ? [0, 1, 2].map((q) => cs.reduce((t, v) => t + v[q], 0) / cs.length) : cs.reduce((t, v) => t + v, 0) / cs.length;
        } else if (fvc) col = colorOf(Math.min(i, rows - 1));
        out.push({ pts, c: col, open });
      }
      return out;
    }
    const X = decode(c.x), Y = decode(c.y), Z = c.z ? decode(c.z) : null;
    if (!X || !Y) return out;
    const C = c.c ? decode(c.c) : null;
    const rows = X.shape[0], cols = X.shape.length > 1 ? X.shape[1] : 1;
    for (let j = 0; j < cols; j++) {
      const pts = [];
      for (let i = 0; i < rows; i++) pts.push([X.data[i * cols + j], Y.data[i * cols + j], Z ? Z.data[i * cols + j] : null]);
      let cv = null;
      if (C) cv = C.data.length === cols ? C.data[j] : C.data[0];
      out.push({ pts, c: cv });
    }
    return out;
  }

  /* ---- figure windows -------------------------------------------------------------------- */
  // what the save button offers: format, menu label, extension, media type
  const SAVE_KINDS = [
    ['png', 'PNG picture (.png)', 'png', 'image/png'],
    ['svg', 'SVG drawing (.svg)', 'svg', 'image/svg+xml'],
    ['pdf', 'PDF document (.pdf)', 'pdf', 'application/pdf'],
    ['eps', 'EPS drawing (.eps)', 'eps', 'application/postscript'],
    ['jpg', 'JPEG picture (.jpg)', 'jpg', 'image/jpeg'],
  ];

  class FigureWindow extends Emitter {
    constructor(mgr, fig) {
      super();
      this.mgr = mgr;
      this.fig = fig;
      this.id = fig.id;
      this.renderer = new Renderer();
      this.renderer.onTile = () => this.redrawSoon();
      this.tool = null;                 // null (drag pans/turns), 'edit', 'zoomin', 'zoomout', 'pan', 'rotate', 'datatip'
      this.tips = [];
      this.selection = null;            // the object the property editor shows (outlined while it is open)
      this.title = el('span', { class: 't' });
      const tb = (name, title, fn, toggle) => {
        const b = el('button', { class: 'pl-iconbtn', type: 'button', title, 'aria-label': title }, icon(name));
        if (toggle) b.setAttribute('aria-pressed', 'false');
        b.addEventListener('click', (ev) => { ev.stopPropagation(); fn(b); });
        return b;
      };
      this.btnClose = tb('close', 'Close the figure', () => this.mgr.requestClose(this));
      this.btnSave = tb('image', 'Save as a picture or a drawing (PNG, SVG, PDF, EPS, JPEG)', () => this.saveMenu());
      this.titlebar = el('div', { class: 'pl-figtitle' }, icon('figure', 'pl-ficon'), this.title, this.btnSave, this.btnClose);
      this.toolBtns = {
        edit: tb('editplot', 'Edit the plot: click a part of it to see and change its properties', () => this.setTool('edit'), true),
        zoomin: tb('zoomin', 'Zoom in (drag a box, or click)', (b) => this.setTool('zoomin'), true),
        zoomout: tb('zoomout', 'Zoom out (click)', (b) => this.setTool('zoomout'), true),
        pan: tb('pan', 'Pan (drag)', (b) => this.setTool('pan'), true),
        rotate: tb('rotate', 'Rotate in 3-D (drag)', (b) => this.setTool('rotate'), true),
        datatip: tb('datatip', 'Data tips (click a point)', (b) => this.setTool('datatip'), true),
      };
      this.tools = el('div', { class: 'pl-figtools', role: 'toolbar', 'aria-label': 'Figure tools' },
        this.toolBtns.edit, this.toolBtns.zoomin, this.toolBtns.zoomout, this.toolBtns.pan, this.toolBtns.rotate, this.toolBtns.datatip,
        tb('home', 'Restore the view', () => this.restoreView()), el('span', { class: 'gap' }),
        tb('grid', 'Grid on or off', () => this.mgr.run(`figure(${fig.number}); grid`)),
        tb('legend', 'Legend on or off', () => this.mgr.run(`figure(${fig.number}); if isempty(get(gca,'Legend')), legend show, else, legend off, end`)),
        tb('colorbar', 'Colorbar on or off', () => this.mgr.run(`figure(${fig.number}); if isempty(findobj(gcf,'Type','colorbar')), colorbar, else, colorbar off, end`)));
      this.canvas = el('canvas');
      // what the program made with uicontrol, uimenu, uitoolbar ... (pylab-ui.js)
      this.ui = new PL.FigureUI(this);
      // in edit mode a click on a control picks it, and does not press it
      const pick = (ev) => {
        if (this.tool !== 'edit') return;
        const c = ev.target.closest && ev.target.closest('.pl-uictl');
        if (!c) return;
        ev.preventDefault();
        ev.stopPropagation();
        if (ev.type === 'pointerdown') this.mgr.inspect(this, Number(c.dataset.id));
      };
      for (const t of ['pointerdown', 'mousedown', 'click', 'dblclick']) this.ui.layer.addEventListener(t, pick, true);
      this.stage = el('div', { class: 'pl-figcanvas' }, this.canvas, this.ui.layer);
      this.grip = el('div', { class: 'pl-figgrip', title: 'Drag to resize' });
      this.el = el('div', { class: 'pl-figwin', role: 'dialog', 'aria-label': 'Figure', tabindex: '-1' }, this.titlebar, this.ui.menubar, this.ui.toolbars, this.tools, this.stage, this.grip);
      this.el.addEventListener('pointerdown', () => this.mgr.focus(this), true);
      this._drag();
      this._resize();
      this._interact();
      this._keys();
      this.update(fig);
    }

    update(fig) {
      this.fig = fig;
      const t = fig.numberTitle ? `Figure ${fig.number}${fig.name ? `: ${fig.name}` : ''}` : (fig.name || (fig.dialog ? '' : `Figure ${fig.number}`));
      this.title.textContent = t;
      this.el.setAttribute('aria-label', t || 'Dialog');
      this.ui.update(fig);
      // a program's own window: no plot tools unless it asks (MenuBar none hides them, as ToolBar none does)
      this.plotTools = fig.toolBar === 'figure' || (fig.toolBar !== 'none' && fig.menuBar !== 'none');
      this.tools.hidden = !this.plotTools;
      // (edit mode stays: plotedit turns it on in a program's own window too)
      if (!this.plotTools && this.tool && this.tool !== 'edit') this.setTool(this.tool);
      this.btnSave.hidden = !!fig.dialog;
      this.grip.hidden = fig.resize === false;
      this.el.classList.toggle('is-dialog', !!fig.dialog);
      if (!this.sized) {
        this.sized = true;
        this.setSize(fig.width, fig.height);
      } else if (this.figSize && (fig.width !== this.figSize.w || fig.height !== this.figSize.h)) {
        // a size the program set (set(f, 'Position', ...), a ResizeFcn squaring the window): the window takes it
        this.setSize(fig.width, fig.height);
      }
      this.figSize = { w: fig.width, h: fig.height };
      this.el.hidden = !fig.visible;
      this.setPointer();
      this.redraw();
    }

    /* The program's Pointer, unless a figure tool shows its own. */
    setPointer() {
      if (this.tool) return;
      const P = { crosshair: 'crosshair', watch: 'wait', hand: 'pointer', ibeam: 'text', fleur: 'move', circle: 'crosshair', cross: 'crosshair',
        topl: 'nwse-resize', botr: 'nwse-resize', topr: 'nesw-resize', botl: 'nesw-resize', left: 'ew-resize', right: 'ew-resize', top: 'ns-resize', bottom: 'ns-resize' };
      this.stage.style.cursor = P[this.fig.pointer] || '';
    }

    redrawSoon() {
      cancelAnimationFrame(this._soon);
      this._soon = requestAnimationFrame(() => this.redraw());
    }

    setSize(w, h) {
      // the rows above the canvas: title, and menus and tools when there are
      let chrome = 26;
      for (const row of [this.ui.menubar, this.ui.toolbars, this.tools]) if (!row.hidden) chrome += row.offsetHeight || (row === this.tools ? 27 : row === this.ui.menubar ? 25 : 30 * row.childElementCount);
      const layer = this.mgr.layer.getBoundingClientRect();
      const maxW = Math.max(240, layer.width - 16), maxH = Math.max(180, layer.height - 16);
      const W = Math.min(w, maxW), H = Math.min(h + chrome, maxH);
      this.el.style.width = `${W}px`;
      this.el.style.height = `${H}px`;
      // a window grown past the edge of the windows' area moves back in, as far as it fits
      if (this.el.offsetLeft + W > layer.width) this.el.style.left = `${Math.max(0, layer.width - W - 4)}px`;
      if (this.el.offsetTop + H > layer.height) this.el.style.top = `${Math.max(0, layer.height - H - 4)}px`;
    }

    canvasSize() {
      const r = this.stage.getBoundingClientRect();
      return { w: Math.max(10, Math.floor(r.width)), h: Math.max(10, Math.floor(r.height)) };
    }

    redraw() {
      if (this.ui) this.ui.prepare(this.fig);
      const { w, h } = this.canvasSize();
      const dpr = window.devicePixelRatio || 1;
      this.canvas.width = Math.round(w * dpr);
      this.canvas.height = Math.round(h * dpr);
      this.canvas.style.width = `${w}px`;
      this.canvas.style.height = `${h}px`;
      const ctx = this.canvas.getContext('2d');
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      PL.figureCtx = ctx;
      this.renderer.draw(ctx, this.fig, w, h);
      this.drawTips(ctx);
      this.lastSize = { w, h };
      this.drawSelection(ctx);
    }

    /* The size the figure is drawn at: as on screen, or its own for a window not shown. */
    exportSize() {
      if (this.el.hidden || !this.el.isConnected) return { w: Math.max(10, Math.round(this.fig.width)), h: Math.max(10, Math.round(this.fig.height)) };
      return this.lastSize || this.canvasSize();
    }

    /* The figure drawn on a canvas of its size times scale (and the renderer that drew it). */
    rasterize(scale = 2) {
      const { w, h } = this.exportSize();
      const c = document.createElement('canvas');
      c.width = Math.max(1, Math.round(w * scale));
      c.height = Math.max(1, Math.round(h * scale));
      const ctx = c.getContext('2d');
      ctx.setTransform(scale, 0, 0, scale, 0, 0);
      PL.figureCtx = ctx;
      const r = new Renderer();
      r.draw(ctx, this.fig, w, h);
      PL.figureCtx = this.canvas.getContext('2d');
      return { canvas: c, renderer: r, w, h };
    }

    /* Before a picture or file of the figure: draw it once to learn which
       basemap tiles it needs, and wait for those still loading (at most 20 s). */
    async ready(scale = 2) {
      if (!(this.fig.axes || []).some((a) => a.geo && a.basemap && a.basemap !== 'none')) return;
      const { w, h } = this.exportSize();
      const ctx = document.createElement('canvas').getContext('2d');
      ctx.setTransform(scale, 0, 0, scale, 0, 0);
      const r = new Renderer();
      r.draw(ctx, this.fig, w, h);
      if (r.waits.length) await Promise.race([Promise.allSettled(r.waits), new Promise((res) => setTimeout(res, 20000))]);
    }

    renderTo(scale = 2, type = 'image/png') {
      return this.rasterize(scale).canvas.toDataURL(type, 0.92);
    }

    /* saveas, print and exportgraphics: the file's bytes as base64. PNG and JPEG
       come from the canvas, BMP and TIFF from its pixels, and SVG, PDF and EPS
       from the drawing itself (pylab-export.js). */
    async fileData(format, scale = 2) {
      const X = PL.figureExport;
      await this.ready(format === 'svg' || format === 'pdf' || format === 'eps' ? 2 : scale);
      if (format === 'svg' || format === 'pdf' || format === 'eps') {
        const { w, h } = this.exportSize();
        const title = this.title.textContent || `Figure ${this.fig.number}`;
        return X.base64(await X.vector(format, w, h, (ctx) => new Renderer().draw(ctx, this.fig, w, h), title));
      }
      const { canvas } = this.rasterize(scale);
      if (format === 'bmp' || format === 'tif') return X.base64(X.raster(format, canvas, 96 * scale));
      const url = canvas.toDataURL(format === 'jpg' ? 'image/jpeg' : 'image/png', 0.92);
      return url.slice(url.indexOf(',') + 1);
    }

    /* getframe: the figure's pixels at its size on screen, or those of an axes'
       box; rect [left bottom width height] in pixels from the lower-left corner
       of the figure (or of the axes). RGB rows from the top, as base64. */
    async frame(axesId, rect) {
      await this.ready(1);
      const { canvas, renderer, w, h } = this.rasterize(1);
      let x = 0, y = 0, cw = w, ch = h;
      if (axesId != null) {
        const f = renderer.frames.find((fr) => fr.ax && fr.ax.id === axesId && !fr.yyRight);
        if (f) ({ x, y, w: cw, h: ch } = f.rect);
      }
      if (rect && rect.length === 4) {
        const bottom = y + ch;
        x += rect[0]; cw = rect[2]; ch = rect[3]; y = bottom - rect[1] - ch;
      }
      const x0 = Math.max(0, Math.round(x)), y0 = Math.max(0, Math.round(y));
      const x1 = Math.min(canvas.width, Math.round(x + cw)), y1 = Math.min(canvas.height, Math.round(y + ch));
      if (x1 <= x0 || y1 <= y0) return { width: 0, height: 0, data: '' };
      const d = canvas.getContext('2d').getImageData(x0, y0, x1 - x0, y1 - y0).data;
      const rgb = new Uint8Array((x1 - x0) * (y1 - y0) * 3);
      for (let i = 0, j = 0; j < d.length; i += 3, j += 4) {
        const a = d[j + 3] / 255;
        rgb[i] = Math.round(d[j] * a + 255 * (1 - a)); rgb[i + 1] = Math.round(d[j + 1] * a + 255 * (1 - a)); rgb[i + 2] = Math.round(d[j + 2] * a + 255 * (1 - a));
      }
      return { width: x1 - x0, height: y1 - y0, data: PL.figureExport.base64(rgb) };
    }

    /* The save button's choice of file: a picture, or a drawing whose lines and text stay sharp at any size. */
    saveMenu() {
      const r = this.btnSave.getBoundingClientRect();
      PL.util.menu(r.left, r.bottom + 2, [
        { heading: 'Save the figure as' },
        ...SAVE_KINDS.map(([f, label]) => ({ label, action: () => this.savePicture(f) })),
      ]);
    }

    /* The figure as a file to download: PNG by default, or SVG, PDF, EPS or
       JPEG, written as saveas writes them (pylab-export.js for the drawings). */
    async savePicture(format = 'png') {
      const [, , ext, type] = SAVE_KINDS.find((k) => k[0] === format) || SAVE_KINDS[0];
      let url;
      if (format === 'png') {
        await this.ready(2);
        url = this.renderTo(2);
      } else {
        const b64 = await this.fileData(format, 2);
        const bin = atob(b64);
        const bytes = new Uint8Array(bin.length);
        for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
        url = URL.createObjectURL(new Blob([bytes], { type }));
      }
      const a = el('a', { href: url, download: `figure${this.fig.number}.${ext}` });
      document.body.append(a);
      a.click();
      a.remove();
      if (url.startsWith('blob:')) setTimeout(() => URL.revokeObjectURL(url), 10000);
    }

    setTool(t) {
      const was = this.tool;
      this.tool = this.tool === t ? null : t;
      for (const [k, b] of Object.entries(this.toolBtns)) b.setAttribute('aria-pressed', String(k === this.tool));
      this.stage.style.cursor = this.tool === 'zoomin' ? 'zoom-in' : this.tool === 'zoomout' ? 'zoom-out' : this.tool === 'pan' ? 'grab' : this.tool === 'rotate' ? 'move' : this.tool === 'datatip' ? 'crosshair' : 'default';
      this.el.classList.toggle('is-editing', this.tool === 'edit');
      if (!this.tool) this.setPointer();
      if (this.tool !== 'datatip') { this.tips = []; this.redraw(); }
      // edit mode opens the property editor on what was picked last (or the figure); leaving it closes the editor
      if (this.tool === 'edit' && was !== 'edit') this.mgr.inspect(this, this.selection || this.fig.id);
      else if (was === 'edit' && !this.tool) this.mgr.closeInspector(this);
    }

    /* What a click in edit mode picks: a legend or colorbar, a text (a title,
       a label), an annotation, a plotted object (also one that takes no
       clicks), its axes (with their tick labels round them), else the figure. */
    editHit(px, py) {
      const fs = this.renderer.frames;
      for (let i = fs.length - 1; i >= 0; i--) {
        const f = fs[i], r = f.rect;
        if ((f.legend || f.colorbar) && px >= r.x && px <= r.x + r.w && py >= r.y && py <= r.y + r.h) return (f.legend || f.colorbar).id;
      }
      let best = null;
      for (const [id, b] of this.renderer.textBoxes) {
        if (px >= b.x - 2 && px <= b.x + b.w + 2 && py >= b.y - 2 && py <= b.y + b.h + 2 && (!best || b.w * b.h < best.a)) best = { id, a: b.w * b.h };
      }
      if (best) return best.id;
      const W = this.lastSize ? this.lastSize.w : 0, H = this.lastSize ? this.lastSize.h : 0;
      for (let i = (this.fig.annotations || []).length - 1; i >= 0; i--) {
        const a = this.fig.annotations[i];
        const b = shapeBox(a, W, H);
        if (!b || a.visible === false) continue;
        if (b.line) {
          const [x1, y1, x2, y2] = b.line;
          const dx = x2 - x1, dy = y2 - y1, L = dx * dx + dy * dy;
          const t = L ? Math.max(0, Math.min(1, ((px - x1) * dx + (py - y1) * dy) / L)) : 0;
          if (Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy)) <= 5) return a.id;
        } else if (px >= b.x - 3 && px <= b.x + b.w + 3 && py >= b.y - 3 && py <= b.y + b.h + 3) return a.id;
      }
      const axes = fs.filter((f) => f.ax && !f.yyRight);
      for (let i = axes.length - 1; i >= 0; i--) {
        const f = axes[i], r = f.rect;
        if (px < r.x || px > r.x + r.w || py < r.y || py > r.y + r.h) continue;
        if (!f.is3d && !f.fr.polar) {
          for (const fr of fs.filter((g) => g.ax && g.rect === r && g.yyRight).concat([f])) {
            for (let k = fr.ax.children.length - 1; k >= 0; k--) if (this.hits(fr, fr.ax.children[k], px, py)) return fr.ax.children[k].id;
          }
        }
        return f.ax.id;
      }
      // a click by the axes (on their tick labels): the nearest axes
      let near = null;
      for (const f of axes) {
        const r = f.rect;
        const d = Math.hypot(Math.max(r.x - px, 0, px - r.x - r.w), Math.max(r.y - py, 0, py - r.y - r.h));
        if (d <= 40 && (!near || d < near.d)) near = { d, id: f.ax.id };
      }
      return near ? near.id : this.fig.id;
    }

    /* Where the selected object is on the canvas, for its outline. */
    selectionBox(id) {
      const R = this.renderer;
      const W = this.lastSize ? this.lastSize.w : 0, H = this.lastSize ? this.lastSize.h : 0;
      if (id === this.fig.id) return { x: 7, y: 7, w: W - 14, h: H - 14 };
      for (const f of R.frames) {
        if ((f.ax && f.ax.id === id) || (f.legend && f.legend.id === id) || (f.colorbar && f.colorbar.id === id)) return f.rect;
      }
      if (R.textBoxes.has(id)) return R.textBoxes.get(id);
      const a = (this.fig.annotations || []).find((x) => x.id === id);
      if (a) {
        const b = shapeBox(a, W, H);
        if (b && b.line) return { x: Math.min(b.line[0], b.line[2]), y: Math.min(b.line[1], b.line[3]), w: Math.abs(b.line[2] - b.line[0]), h: Math.abs(b.line[3] - b.line[1]) };
        return b;
      }
      for (const f of R.frames) {
        if (!f.ax) continue;
        const c = f.ax.children.find((x) => x.id === id);
        if (!c) continue;
        if (f.is3d || f.fr.polar) return f.rect;
        const fr = f.fr;
        let xs = [], ys = [];
        if (c.type === 'patch' && !c.x && c.vertices) {
          const V = decode(c.vertices);
          const n = V.shape[0], m = V.shape[1] || 1;
          for (let i = 0; i < n; i++) { xs.push(V.data[i * m]); ys.push(V.data[i * m + 1]); }
        } else {
          xs = vec(decode(c.x || c.xData));
          ys = vec(decode(c.y || c.yData));
          if (c.type === 'series' && c.kind === 'bar' && xs.length && ys.length) ys = ys.concat([c.baseValue || 0]);
        }
        const X = xs.filter((v) => Number.isFinite(v)).map((v) => fr.fx(v)).filter(Number.isFinite);
        const Y = ys.filter((v) => Number.isFinite(v)).map((v) => fr.fy(v)).filter(Number.isFinite);
        if (!X.length || !Y.length) return f.rect;
        const r = f.rect;
        const x0 = Math.max(r.x, Math.min(...X)), x1 = Math.min(r.x + r.w, Math.max(...X));
        const y0 = Math.max(r.y, Math.min(...Y)), y1 = Math.min(r.y + r.h, Math.max(...Y));
        return x1 >= x0 && y1 >= y0 ? { x: x0, y: y0, w: x1 - x0, h: y1 - y0 } : null;
      }
      return null;
    }

    drawSelection(ctx) {
      const id = this.selection;
      this.ui.mark(this.mgr.inspecting(this) ? id : null);
      if (id == null || !this.mgr.inspecting(this)) return;
      const b = this.selectionBox(id);
      if (!b) return;
      const x = b.x - 3, y = b.y - 3, w = b.w + 6, h = b.h + 6;
      ctx.save();
      ctx.strokeStyle = '#2f6db5';
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 3]);
      ctx.strokeRect(x, y, w, h);
      ctx.setLineDash([]);
      ctx.fillStyle = '#fff';
      for (const [hx, hy] of [[x, y], [x + w, y], [x, y + h], [x + w, y + h], [x + w / 2, y], [x + w / 2, y + h], [x, y + h / 2], [x + w, y + h / 2]]) {
        ctx.fillRect(hx - 3, hy - 3, 6, 6);
        ctx.strokeRect(hx - 3, hy - 3, 6, 6);
      }
      ctx.restore();
    }

    /* What a click at (px, py) on the canvas hits: the topmost object that
       takes clicks (a text's letters, a line, a patch's face or edge, an
       image), else its axes, else the figure; and the point in the axes'
       data. */
    hitTest(px, py) {
      const fig = this.fig;
      const fs = this.renderer.frames.filter((f) => f.ax && !f.yyRight);
      for (let i = fs.length - 1; i >= 0; i--) {
        const f = fs[i];
        const r = f.rect;
        if (px < r.x || px > r.x + r.w || py < r.y || py > r.y + r.h || !inBox(f.ax, px, py)) continue;
        const ax = f.ax;
        const point = f.is3d || f.fr.polar ? null : [f.fr.ix(px), f.fr.iy(py)];
        const at = (c) => ({ id: c.id, axes: ax.id, point, bdf: !!c.bdf, cmenu: c.cmenu || ax.cmenu || fig.cmenu || null });
        if (!f.is3d && !f.fr.polar) {
          for (let k = ax.children.length - 1; k >= 0; k--) {
            const c = ax.children[k];
            if (c.visible === false || c.hit === false) continue;
            if (this.hits(f, c, px, py)) return at(c);
          }
        }
        if (ax.hit === false) return { id: fig.id, axes: ax.id, point, bdf: !!(fig.flags && fig.flags.bdf), cmenu: fig.cmenu || null };
        return at(ax);
      }
      return { id: fig.id, axes: null, point: null, bdf: !!(fig.flags && fig.flags.bdf), cmenu: fig.cmenu || null };
    }

    hits(f, c, px, py) {
      const fr = f.fr;
      if (c.type === 'text') {
        const b = this.renderer.textBoxes.get(c.id);
        return !!b && px >= b.x - 2 && px <= b.x + b.w + 2 && py >= b.y - 2 && py <= b.y + b.h + 2;
      }
      const near = (pts, tol) => {
        for (let i = 1; i < pts.length; i++) {
          const [x1, y1] = pts[i - 1], [x2, y2] = pts[i];
          const dx = x2 - x1, dy = y2 - y1;
          const L = dx * dx + dy * dy;
          const t = L ? Math.max(0, Math.min(1, ((px - x1) * dx + (py - y1) * dy) / L)) : 0;
          if (Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy)) <= tol) return true;
        }
        return pts.length === 1 && Math.hypot(px - pts[0][0], py - pts[0][1]) <= tol;
      };
      if (c.type === 'line') {
        const x = vec(decode(c.x)), y = vec(decode(c.y));
        const pts = [];
        for (let i = 0; i < Math.min(x.length, y.length); i++) if (fr.ok(x[i], y[i])) pts.push([fr.fx(x[i]), fr.fy(y[i])]);
        const tol = Math.max(3, (c.lineWidth || 0.5) / 2 + 2);
        if (c.lineStyle !== 'none' && near(pts, tol)) return true;
        return c.marker && c.marker !== 'none' && pts.some(([qx, qy]) => Math.hypot(px - qx, py - qy) <= (c.markerSize || 6) / 2 + 2);
      }
      if (c.type === 'patch') {
        for (const poly of patchPolys(c)) {
          const pts = poly.pts.map(([x, y]) => [fr.fx(x), fr.fy(y)]);
          if (pts.length < 2) continue;
          if (c.faceColor !== 'none') {
            let inside = false;
            for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
              const [xi, yi] = pts[i], [xj, yj] = pts[j];
              if ((yi > py) !== (yj > py) && px < ((xj - xi) * (py - yi)) / (yj - yi) + xi) inside = !inside;
            }
            if (inside) return true;
          }
          if (c.edgeColor !== 'none' && near(pts.concat([pts[0]]), 3)) return true;
        }
        return false;
      }
      if (c.type === 'image' || c.type === 'surface') {
        const xs = vec(decode(c.x)), ys = vec(decode(c.y));
        if (!xs.length || !ys.length) return false;
        const X = [fr.fx(Math.min(...xs)), fr.fx(Math.max(...xs))], Y = [fr.fy(Math.min(...ys)), fr.fy(Math.max(...ys))];
        return px >= Math.min(...X) && px <= Math.max(...X) && py >= Math.min(...Y) && py <= Math.max(...Y);
      }
      return false;
    }

    /* Keys in the window go to the program: menu accelerators first, then
       the figure's (or a control's) key callbacks. */
    _keys() {
      const send = (ev, release) => {
        const fig = this.fig;
        if (!fig || !fig.flags) return;
        const ctl = this.ui.controlOf(ev.target);
        const typing = ev.target && (ev.target.tagName === 'INPUT' && ev.target.type === 'text' || ev.target.tagName === 'TEXTAREA' || ev.target.tagName === 'SELECT');
        const own = ctl && ctl.kpf;
        const fl = fig.flags;
        const toFigure = !ctl || (!own && !typing);
        const listens = release ? (fl.krf || fl.wkrf) : (fl.kpf || fl.wkpf || own);
        if (!listens || (!toFigure && !own && !(release ? fl.wkrf : fl.wkpf))) return;
        const info = PL.uiKeys(ev);
        this.mgr.ui(Object.assign({ type: 'key', id: own ? ctl.id : fig.id, release, toFigure }, info));
        // the figure's keys are the program's (arrows scroll nothing, space presses nothing)
        if (toFigure && !release && (fl.kpf || fl.wkpf) && !ev.metaKey && !(ev.ctrlKey && ['c', 'v', 'x'].includes(ev.key))) ev.preventDefault();
      };
      this.el.addEventListener('keydown', (ev) => {
        if (ev.target.closest && ev.target.closest('.pl-figtitle, .pl-figtools')) return;
        if (this.fig && this.fig.menus && this.ui.accelerator(ev)) return;
        send(ev, false);
        if (this.fig && this.fig.flags && (this.fig.flags.kpf || this.fig.flags.wkpf) && !this.ui.controlOf(ev.target)) ev.stopPropagation();
      });
      this.el.addEventListener('keyup', (ev) => send(ev, true));
    }

    frameAt(px, py) {
      const fs = this.renderer.frames.filter((f) => f.ax && !f.yyRight);
      for (let i = fs.length - 1; i >= 0; i--) {
        const f = fs[i];
        const r = f.rect;
        if (px >= r.x - 4 && px <= r.x + r.w + 4 && py >= r.y - 4 && py <= r.y + r.h + 4 && inBox(f.ax, px, py)) return f;
      }
      return null;
    }

    restoreView() {
      for (const f of this.renderer.frames) {
        if (!f.ax || f.yyRight) continue;
        const ax = f.ax;
        if (ax._orig) {
          ax.xlim = ax._orig.xlim; ax.ylim = ax._orig.ylim; ax.zlim = ax._orig.zlim; ax.view = ax._orig.view; ax.zoom3 = 1;
          this.mgr.send({ type: 'limits', id: ax.id, reset: true });
          this.mgr.send({ type: 'view', id: ax.id, view: ax.view });
        }
      }
      this.tips = [];
      this.redraw();
    }

    remember(ax) {
      if (!ax._orig) ax._orig = { xlim: ax.xlim.slice(), ylim: ax.ylim.slice(), zlim: ax.zlim.slice(), view: ax.view.slice() };
    }

    sendLimits(ax) {
      this.mgr.send({ type: 'limits', id: ax.id, xlim: ax.xlim, ylim: ax.ylim, zlim: ax.zlim });
    }

    zoomAt(f, px, py, factor) {
      const ax = f.ax;
      this.remember(ax);
      if (f.is3d) { ax.zoom3 = (ax.zoom3 || 1) / factor; this.redraw(); return; }
      const fr = f.fr;
      const cx = fr.ix(px), cy = fr.iy(py);
      const scale = (lim, c, log) => {
        if (log) { const a = Math.log10(lim[0]), b = Math.log10(lim[1]), lc = Math.log10(c); return [10 ** (lc + (a - lc) * factor), 10 ** (lc + (b - lc) * factor)]; }
        return [c + (lim[0] - c) * factor, c + (lim[1] - c) * factor];
      };
      ax.xlim = scale(ax.xlim, cx, ax.xscale === 'log');
      ax.ylim = scale(ax.ylim, cy, ax.yscale === 'log');
      this.redraw();
      clearTimeout(this._limTimer);
      this._limTimer = setTimeout(() => this.sendLimits(ax), 250);
    }

    _interact() {
      let drag = null;
      const pos = (ev) => { const r = this.canvas.getBoundingClientRect(); return [ev.clientX - r.left, ev.clientY - r.top]; };
      const mouse = (type, ev, px, py, hit, clicks = 1) => {
        const h = hit || this.hitTest(px, py);
        this.mgr.ui({ type, id: this.fig.id, hit: h.id, axes: h.axes, point: h.point, fpt: [px, (this.lastSize ? this.lastSize.h : 0) - py],
          button: ev.button === 2 ? 3 : ev.button === 1 ? 2 : 1, clicks, modifiers: PL.uiMods(ev) });
      };
      // a pointerdown's detail is 0, so presses are counted here: the same button
      // again within half a second and a few pixels makes a double-click
      let last = null;
      const presses = (ev, px, py) => {
        const n = last && last.button === ev.button && ev.timeStamp - last.t < 500 && Math.hypot(px - last.x, py - last.y) < 5 ? last.n + 1 : 1;
        last = { t: ev.timeStamp, x: px, y: py, button: ev.button, n };
        return n;
      };
      this.canvas.addEventListener('pointerdown', (ev) => {
        const [px, py] = pos(ev);
        const f = this.frameAt(px, py);
        if (this.mgr.ginput) { if (ev.button === 0) this.mgr.ginputClick(this, f, px, py, ev.button); return; }
        this.el.focus({ preventScroll: true });
        // edit mode: a click picks what is under it for the property editor; the program hears nothing
        if (this.tool === 'edit') { if (ev.button === 0) this.mgr.inspect(this, this.editHit(px, py)); return; }
        const fl = this.fig.flags || {};
        const hit = this.hitTest(px, py);
        // the program hears every press (CurrentPoint, SelectionType, gco; and its callbacks)
        mouse('down', ev, px, py, hit, presses(ev, px, py));
        if (fl.wbuf || fl.wbmf) { this.canvas.setPointerCapture(ev.pointerId); this.pressed = true; }
        if (ev.button !== 0 || !f) return;
        this.mgr.send({ type: 'currentaxes', id: f.ax.id });
        // a click the program takes, or a window of the program's own, is not panned or tipped
        if (!this.tool && (fl.wbdf || hit.bdf || !this.plotTools)) return;
        const mode = this.tool || (f.is3d ? 'rotate' : 'pan');
        if (mode === 'datatip') { this.addTip(f, px, py); return; }
        if (mode === 'zoomout') { this.zoomAt(f, px, py, 1.6); return; }
        this.canvas.setPointerCapture(ev.pointerId);
        this.remember(f.ax);
        drag = { f, mode, x0: px, y0: py, xl: f.ax.xlim.slice(), yl: f.ax.ylim.slice(), view: f.ax.view.slice(), moved: false };
        if (mode === 'zoomin') {
          drag.box = el('div', { class: 'pl-zoombox' });
          this.stage.append(drag.box);
        }
      });
      this.canvas.addEventListener('pointermove', (ev) => {
        if (!drag) {
          if (this.fig.flags && this.fig.flags.wbmf && !this._moveRaf) {
            const [mx, my] = pos(ev);
            this._moveRaf = requestAnimationFrame(() => { this._moveRaf = 0; mouse('motion', ev, mx, my); });
          }
          return;
        }
        const [px, py] = pos(ev);
        const dx = px - drag.x0, dy = py - drag.y0;
        if (Math.abs(dx) + Math.abs(dy) > 2) drag.moved = true;
        const ax = drag.f.ax;
        if (drag.mode === 'zoomin') {
          const b = drag.box;
          b.style.left = `${Math.min(px, drag.x0)}px`; b.style.top = `${Math.min(py, drag.y0)}px`;
          b.style.width = `${Math.abs(dx)}px`; b.style.height = `${Math.abs(dy)}px`;
          return;
        }
        if (drag.mode === 'rotate') {
          let az = drag.view[0] - dx * 0.5;
          let elv = drag.view[1] + dy * 0.5;
          elv = Math.max(-90, Math.min(90, elv));
          ax.view = [az, elv];
          this.redraw();
          return;
        }
        if (drag.mode === 'pan' && !drag.f.is3d) {
          const r = drag.f.rect;
          const sh = (lim, d, len, log, rev) => {
            const s = (rev ? -1 : 1) * d / len;
            if (log) { const a = Math.log10(lim[0]), b = Math.log10(lim[1]); const k = (b - a) * s; return [10 ** (a - k), 10 ** (b - k)]; }
            const k = (lim[1] - lim[0]) * s;
            return [lim[0] - k, lim[1] - k];
          };
          ax.xlim = sh(drag.xl, dx, r.w, ax.xscale === 'log', ax.xdir === 'reverse');
          ax.ylim = sh(drag.yl, -dy, r.h, ax.yscale === 'log', ax.ydir === 'reverse');
          this.redraw();
        }
      });
      const end = (ev) => {
        if (this.pressed) {
          this.pressed = false;
          if (this.fig.flags && this.fig.flags.wbuf) { const [ux, uy] = pos(ev); mouse('up', ev, ux, uy); }
        }
        if (!drag) return;
        const [px, py] = pos(ev);
        const d = drag;
        drag = null;
        const ax = d.f.ax;
        if (d.mode === 'zoomin') {
          d.box.remove();
          if (!d.moved || d.f.is3d) { this.zoomAt(d.f, d.x0, d.y0, 1 / 1.6); return; }
          const fr = d.f.fr;
          const xa = fr.ix(d.x0), xb = fr.ix(px), ya = fr.iy(d.y0), yb = fr.iy(py);
          if (Math.abs(px - d.x0) > 3) ax.xlim = [Math.min(xa, xb), Math.max(xa, xb)];
          if (Math.abs(py - d.y0) > 3) ax.ylim = [Math.min(ya, yb), Math.max(ya, yb)];
          this.redraw();
          this.sendLimits(ax);
          return;
        }
        if (d.mode === 'rotate' && d.moved) { this.mgr.send({ type: 'view', id: ax.id, view: ax.view }); return; }
        if (d.mode === 'pan' && d.moved) this.sendLimits(ax);
        if (!d.moved && !this.tool) this.addTip(d.f, d.x0, d.y0, true);
      };
      this.canvas.addEventListener('pointerup', end);
      this.canvas.addEventListener('pointercancel', end);
      this.canvas.addEventListener('wheel', (ev) => {
        const [px, py] = pos(ev);
        if (this.fig.flags && this.fig.flags.scroll) {
          ev.preventDefault();
          this.mgr.ui({ type: 'scroll', id: this.fig.id, count: Math.sign(ev.deltaY) || 1, fpt: [px, (this.lastSize ? this.lastSize.h : 0) - py] });
          return;
        }
        if (!this.plotTools) return;
        const f = this.frameAt(px, py);
        if (!f || f.fr.polar) return;
        ev.preventDefault();
        this.zoomAt(f, px, py, ev.deltaY > 0 ? 1.15 : 1 / 1.15);
      }, { passive: false });
      this.canvas.addEventListener('dblclick', () => { if (this.plotTools && this.tool !== 'edit' && !(this.fig.flags && this.fig.flags.wbdf)) this.restoreView(); });
      this.canvas.addEventListener('contextmenu', (ev) => {
        const [px, py] = pos(ev);
        const hit = this.hitTest(px, py);
        if (hit.cmenu && this.ui.showCmenu(hit.cmenu, ev.clientX, ev.clientY)) ev.preventDefault();
        else if (!this.plotTools || hit.bdf) ev.preventDefault();
      });
    }

    /* A tip at the data point nearest the click (lines, scatter, images). */
    addTip(f, px, py, transient = false) {
      if (f.is3d || f.fr.polar) return;
      const fr = f.fr;
      let best = null;
      for (const c of f.ax.children) {
        if (c.type === 'line' || (c.type === 'series' && ['scatter', 'bubblechart', 'stem', 'stair', 'errorbar'].includes(c.kind))) {
          const x = vec(decode(c.x || c.xData)), y = vec(decode(c.y || c.yData));
          for (let i = 0; i < Math.min(x.length, y.length); i++) {
            if (!fr.ok(x[i], y[i])) continue;
            const d = Math.hypot(fr.fx(x[i]) - px, fr.fy(y[i]) - py);
            if (d < 14 && (!best || d < best.d)) best = { d, x: x[i], y: y[i], px: fr.fx(x[i]), py: fr.fy(y[i]) };
          }
        } else if (c.type === 'image') {
          const C = decode(c.c);
          const xd = vec(decode(c.x)), yd = vec(decode(c.y));
          const cols = C.shape[1], rows = C.shape[0];
          const dx = cols > 1 ? (xd[xd.length - 1] - xd[0]) / (cols - 1) : 1, dy = rows > 1 ? (yd[yd.length - 1] - yd[0]) / (rows - 1) : 1;
          const j = Math.round((fr.ix(px) - xd[0]) / dx), i = Math.round((fr.iy(py) - yd[0]) / dy);
          if (i >= 0 && i < rows && j >= 0 && j < cols) best = { d: 0, x: xd[0] + j * dx, y: yd[0] + i * dy, v: C.shape.length === 3 ? `[${[0, 1, 2].map((k) => +C.data[(i * cols + j) * 3 + k].toPrecision(4)).join(' ')}]` : +C.data[i * cols + j].toPrecision(6), px, py };
        }
      }
      if (!best) { if (this.tips.length && !transient) { this.tips = []; this.redraw(); } return; }
      const fmt = (v) => (Number.isInteger(v) ? String(v) : String(+v.toPrecision(6)));
      const text = `X ${fmt(best.x)}\nY ${fmt(best.y)}${best.v !== undefined ? `\nValue ${best.v}` : ''}`;
      if (transient) this.tips = [];
      this.tips.push({ px: best.px, py: best.py, text, ax: f.ax.id });
      this.redraw();
    }

    drawTips(ctx) {
      for (const t of this.tips) {
        ctx.save();
        ctx.fillStyle = '#111';
        ctx.beginPath(); ctx.arc(t.px, t.py, 3.5, 0, 2 * Math.PI); ctx.fill();
        const lines = t.text.split('\n');
        ctx.font = `11px ${FONT}`;
        const w = Math.max(...lines.map((l) => ctx.measureText(l).width)) + 10;
        const h = lines.length * 14 + 6;
        let x = t.px + 8, y = t.py - h - 8;
        if (x + w > this.lastSize.w) x = t.px - w - 8;
        if (y < 0) y = t.py + 8;
        ctx.fillStyle = 'rgba(255,255,242,0.96)';
        ctx.strokeStyle = '#555';
        ctx.fillRect(x, y, w, h);
        ctx.strokeRect(x, y, w, h);
        ctx.fillStyle = '#111';
        lines.forEach((l, i) => ctx.fillText(l, x + 5, y + 15 + i * 14));
        ctx.restore();
      }
    }

    _drag() {
      let d = null;
      this.titlebar.addEventListener('pointerdown', (ev) => {
        if (ev.target.closest('button') || this.el.classList.contains('is-docked')) return;
        d = { x: ev.clientX, y: ev.clientY, l: this.el.offsetLeft, t: this.el.offsetTop };
        this.titlebar.setPointerCapture(ev.pointerId);
      });
      this.titlebar.addEventListener('pointermove', (ev) => {
        if (!d) return;
        const layer = this.mgr.layer;
        const l = Math.max(-this.el.offsetWidth + 60, Math.min(layer.clientWidth - 60, d.l + ev.clientX - d.x));
        const t = Math.max(0, Math.min(layer.clientHeight - 26, d.t + ev.clientY - d.y));
        this.el.style.left = `${l}px`;
        this.el.style.top = `${t}px`;
      });
      const up = () => { if (d) { d = null; this.mgr.savePlaces(); } };
      this.titlebar.addEventListener('pointerup', up);
      this.titlebar.addEventListener('pointercancel', up);
    }

    _resize() {
      let d = null;
      this.grip.addEventListener('pointerdown', (ev) => {
        ev.preventDefault();
        d = { x: ev.clientX, y: ev.clientY, w: this.el.offsetWidth, h: this.el.offsetHeight };
        this.grip.setPointerCapture(ev.pointerId);
      });
      this.grip.addEventListener('pointermove', (ev) => {
        if (!d) return;
        this.el.style.width = `${Math.max(220, d.w + ev.clientX - d.x)}px`;
        this.el.style.height = `${Math.max(160, d.h + ev.clientY - d.y)}px`;
        cancelAnimationFrame(this._rz);
        this._rz = requestAnimationFrame(() => this.redraw());
      });
      const up = () => {
        if (!d) return;
        d = null;
        const { w, h } = this.canvasSize();
        const fl = this.fig.flags || {};
        this.figSize = { w, h };
        // a program that listens (SizeChangedFcn) hears it; the size is set either way
        if (fl.size || fl.resize) this.mgr.ui({ type: 'resize', id: this.id, width: w, height: h });
        else this.mgr.send({ type: 'resize', id: this.id, width: w, height: h });
        this.mgr.savePlaces();
      };
      this.grip.addEventListener('pointerup', up);
      this.grip.addEventListener('pointercancel', up);
      new ResizeObserver(() => { cancelAnimationFrame(this._rz2); this._rz2 = requestAnimationFrame(() => this.redraw()); }).observe(this.stage);
    }
  }

  /* ---- the windows together ------------------------------------------------------------------ */
  class Figures extends Emitter {
    constructor(layer) {
      super();
      this.layer = layer;
      this.wins = new Map();
      this.z = 10;
      this.current = null;
      this.engineCurrent = null;     // gcf as the engine last told it
      this.ginput = null;
      this.places = PL.util.store.get('figplaces', {});
    }

    send(ev) { this.emit('event', ev); }
    run(code) { this.emit('run', code); }
    ui(ev) { this.emit('ui', ev); }

    /* The property editor (pylab-inspector.js): one, beside the figure it edits. */
    inspect(w, id) {
      if (!PL.FigureInspector) return;
      if (!this.inspector) this.inspector = new PL.FigureInspector(this);
      this.inspector.show(w, id);
    }

    closeInspector(w) { if (this.inspector && this.inspector.isOpen(w)) this.inspector.close(); }

    inspecting(w) { return !!this.inspector && this.inspector.isOpen(w); }

    /* inspect(h) and plotedit in a program. */
    inspectObject(figId, id) {
      const w = this.wins.get(figId);
      if (!w) return;
      w.el.hidden = false;
      this.focus(w, false);
      this.inspect(w, id);
    }

    plotEdit(figId, on) {
      const w = this.wins.get(figId);
      if (!w) return;
      if (on === null || on === undefined || on !== (w.tool === 'edit')) w.setTool('edit');
    }

    /* movegui: a window to the middle (or an edge) of the desktop. */
    move(id, where) {
      const w = this.wins.get(id);
      if (!w) return;
      const L = this.layer.getBoundingClientRect();
      const ww = w.el.offsetWidth, wh = w.el.offsetHeight;
      let l = w.el.offsetLeft, t = w.el.offsetTop;
      if (where === 'center') { l = (L.width - ww) / 2; t = (L.height - wh) / 2; }
      else {
        if (where.includes('north')) t = 4;
        if (where.includes('south')) t = L.height - wh - 4;
        if (where.includes('west')) l = 4;
        if (where.includes('east')) l = L.width - ww - 4;
        if (where === 'north' || where === 'south') l = (L.width - ww) / 2;
        if (where === 'east' || where === 'west') t = (L.height - wh) / 2;
      }
      w.el.style.left = `${Math.max(0, Math.min(l, L.width - 60))}px`;
      w.el.style.top = `${Math.max(0, Math.min(t, L.height - 26))}px`;
      this.savePlaces();
    }

    focusControl(id) {
      for (const w of this.wins.values()) if (w.ui.ctl.has(id)) { this.focus(w); w.ui.focusControl(id); }
    }

    apply(msg) {
      for (const id of msg.closed || []) this.remove(id);
      const opened = new Set();
      for (const fig of msg.figures || []) {
        let w = this.wins.get(fig.id);
        if (!w) {
          w = new FigureWindow(this, fig);
          this.wins.set(fig.id, w);
          this.layer.append(w.el);
          this.place(w);
          opened.add(fig.id);
          this.emit('opened', w);
        } else w.update(fig);
      }
      // gcf comes to the front when it changes (figure(h) raises it on its own),
      // not with every drawing, and a window just opened is already stacked in
      // the order made: a dialog opened over it stays over it
      if (msg.current && msg.current !== this.engineCurrent && !opened.has(msg.current)) this.setCurrent(msg.current, false);
      this.engineCurrent = msg.current;
      this.updateModal();
      if (this.inspector) for (const fig of msg.figures || []) this.inspector.figureChanged(fig.id);
    }

    /* A figure whose WindowStyle is 'modal' keeps the rest of the page from
       being used while it is shown: a veil under it takes the clicks, keys
       typed elsewhere go nowhere (Ctrl+C still stops a program), and the
       focus stays in it. The page's own dialogs stay above it. */
    updateModal() {
      const modal = [...this.wins.values()].filter((w) => w.fig.windowStyle === 'modal' && !w.el.hidden && !w.el.classList.contains('is-docked'));
      for (const w of this.wins.values()) w.el.classList.toggle('is-modal', modal.includes(w));
      if (!modal.length) {
        if (this.veil) {
          this.veil.remove();
          this.veil = null;
          document.removeEventListener('keydown', this.veilKeys, true);
          document.removeEventListener('focusin', this.veilFocus, true);
        }
        return;
      }
      if (!this.veil) {
        this.veil = el('div', { class: 'pl-figveil' });
        this.layer.append(this.veil);
        const inside = (t) => t && t.closest && !!(t.closest('.pl-figwin.is-modal') || t.closest('.pl-modal-back'));
        this.veilKeys = (ev) => {
          if (inside(ev.target) || ((ev.ctrlKey || ev.metaKey) && (ev.key === 'c' || ev.key === 'C'))) return;
          ev.preventDefault();
          ev.stopPropagation();
        };
        this.veilFocus = (ev) => { if (!inside(ev.target)) this.modalFocus(); };
        document.addEventListener('keydown', this.veilKeys, true);
        document.addEventListener('focusin', this.veilFocus, true);
      }
      this.restackModal();
      this.modalFocus();
    }

    /* The veil over every other window, the modal windows over it (in their order). */
    restackModal() {
      const modal = [...this.wins.values()].filter((w) => w.el.classList.contains('is-modal'))
        .sort((p, q) => (+p.el.style.zIndex || 0) - (+q.el.style.zIndex || 0));
      this.veil.style.zIndex = String(++this.z);
      for (const w of modal) w.el.style.zIndex = String(++this.z);
      return modal;
    }

    modalFocus() {
      const modal = [...this.wins.values()].filter((w) => w.el.classList.contains('is-modal'))
        .sort((p, q) => (+p.el.style.zIndex || 0) - (+q.el.style.zIndex || 0));
      const top = modal[modal.length - 1];
      if (top && !top.el.contains(document.activeElement)) top.el.focus({ preventScroll: true });
    }

    place(w) {
      const saved = w.fig.dialog ? null : this.places[w.fig.number];
      const layer = this.layer.getBoundingClientRect();
      w.setSize(w.fig.width, w.fig.height);
      if (w.fig.dialog) {
        // a dialog: in the middle, over the rest (and beside one already there)
        let l = Math.max(4, (layer.width - w.el.offsetWidth) / 2);
        let t = Math.max(4, (layer.height - w.el.offsetHeight) / 3);
        const others = [...this.wins.values()].filter((o) => o !== w && o.fig.dialog && !o.el.hidden);
        while (others.some((o) => Math.abs(o.el.offsetLeft - l) < 12 && Math.abs(o.el.offsetTop - t) < 12) && t < layer.height - 60) { l += 26; t += 26; }
        w.el.style.left = `${l}px`;
        w.el.style.top = `${t}px`;
      } else if (saved && saved.l < layer.width - 40 && saved.t < layer.height - 30) {
        w.el.style.left = `${saved.l}px`;
        w.el.style.top = `${saved.t}px`;
        // the size a window was left at, unless the program gave the figure its Position
        if (saved.w && saved.h && !w.fig.placed) { w.el.style.width = `${Math.min(saved.w, layer.width)}px`; w.el.style.height = `${Math.min(saved.h, layer.height)}px`; }
        else if (w.el.offsetLeft + w.el.offsetWidth > layer.width) w.el.style.left = `${Math.max(0, layer.width - w.el.offsetWidth - 4)}px`;
      } else {
        const n = this.wins.size - 1;
        const ww = w.el.offsetWidth, wh = w.el.offsetHeight;
        const l = Math.max(4, layer.width - ww - 24 - (n % 6) * 26);
        const t = Math.max(4, 12 + (n % 6) * 26);
        w.el.style.left = `${l}px`;
        w.el.style.top = `${Math.min(t, Math.max(4, layer.height - wh - 4))}px`;
      }
      this.focus(w);
      w.redraw();
    }

    savePlaces() {
      for (const w of this.wins.values()) {
        if (w.fig.dialog) continue;
        this.places[w.fig.number] = { l: w.el.offsetLeft, t: w.el.offsetTop, w: w.el.offsetWidth, h: w.el.offsetHeight };
      }
      PL.util.store.set('figplaces', this.places);
    }

    focus(w, tell = true) {
      w.el.style.zIndex = String(++this.z);
      for (const x of this.wins.values()) x.el.classList.toggle('is-current', x === w);
      if (this.current !== w.id && tell) this.send({ type: 'current', id: w.id });
      this.current = w.id;
      if (this.inspector && this.inspector.isOpen(w)) this.inspector.raise();
      if (this.veil) this.restackModal();
    }

    setCurrent(id, tell) {
      const w = this.wins.get(id);
      if (w) this.focus(w, tell);
    }

    raise(id) {
      const w = this.wins.get(id);
      if (w) { w.el.hidden = false; this.focus(w, false); }
    }

    requestClose(w) {
      if (w.fig.closeDefault === false) { this.ui({ type: 'closerequest', id: w.id }); return; }   // the program's CloseRequestFcn decides
      this.send({ type: 'close', id: w.id });
      this.remove(w.id);
    }

    remove(id) {
      const w = this.wins.get(id);
      if (!w) return;
      w.el.remove();
      this.wins.delete(id);
      if (this.current === id) this.current = null;
      if (this.inspector) this.inspector.figureClosed(id);
      this.emit('closed', id);
      this.updateModal();
    }

    clear() {
      for (const id of [...this.wins.keys()]) this.remove(id);
    }

    /* saveas/print: the figure drawn to a picture, as base64. */
    async render(id, format, scale = 2) {
      const w = this.wins.get(id);
      if (!w) return null;
      return w.fileData(format, scale);
    }

    /* getframe: a figure's (or an axes') pixels. */
    frame(id, axesId, rect) {
      const w = this.wins.get(id);
      return w ? w.frame(axesId, rect) : null;
    }

    /* ginput: clicks in the current axes until n are taken or Enter. */
    startGinput(id, n, done) {
      const w = this.wins.get(id);
      if (!w) { done([]); return; }
      this.focus(w, false);
      this.ginput = { w, n, pts: [], done };
      w.stage.style.cursor = 'crosshair';
      const key = (ev) => { if (ev.key === 'Enter' || ev.key === 'Escape') { ev.preventDefault(); this.finishGinput(); } };
      this.ginput.key = key;
      document.addEventListener('keydown', key, true);
    }

    ginputClick(w, f, px, py, button) {
      const g = this.ginput;
      if (!g || g.w !== w || !f || f.is3d || !f.fr.ix) return;
      g.pts.push([f.fr.ix(px), f.fr.iy(py), button + 1]);
      if (g.n > 0 && g.pts.length >= g.n) this.finishGinput();
    }

    finishGinput() {
      const g = this.ginput;
      if (!g) return;
      this.ginput = null;
      document.removeEventListener('keydown', g.key, true);
      g.w.stage.style.cursor = '';
      g.done(g.pts);
    }

    redrawAll() { for (const w of this.wins.values()) w.redraw(); }
  }

  PL.Figures = Figures;
  PL.FigureRenderer = Renderer;
  PL.figureTicks = { niceTicks, tickLabels };
})(window);
