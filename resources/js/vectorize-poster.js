/*
  vectorize-poster.js -- the poster PDF of vectorize.html: the traced drawing
  printed large, over as many sheets of A4 or Letter as it takes, to cut and
  glue together into one picture.

  Every sheet keeps a white margin round it (MARGIN), where a home printer
  cannot print, and neighbouring sheets overlap by a glue strip (OVERLAP). A
  sheet's left and top margins are cut off on a dashed line, and the sheet
  then goes on top of the glue strips of the sheets to its left and above
  it, its cut edge just covering a grey line there. The drawing runs on a
  little past each cut line (BLEED), so a cut a hair outside the line leaves
  no white seam. Each sheet is named by its row and column, B3 being the
  third sheet of the second row, in its top margin and on the glue strips it
  goes over.

  The drawing goes into the file once, as a form XObject in the source
  image's pixels, and each sheet draws it through a clip: the file stays
  small however many sheets there are, and the lines stay sharp at any size,
  as nothing is turned into pixels. The first page tells how to put the
  sheets together, with a picture of the whole poster and its sheets.

  The PDF is written here without a library, as arsred-export.js writes its
  own: the text uses three of PDF's fourteen standard fonts, which need no
  embedding, only their widths for centring and wrapping.

  Loaded in Node, for resources/tests/vectorize, it exports its functions.
*/
'use strict';

const KVOT_POSTER = (() => {
  const MM = 72 / 25.4;   // points in a millimetre
  const MARGIN = 10;      // mm round each sheet
  const OVERLAP = 10;     // mm, the glue strip
  const BLEED = 2;        // mm the drawing runs on past a cut edge
  const CUT_IN = 0.15;    // mm into the bleed, where the cut line runs
  const BORDER = 12;      // mm of white round the drawing on the poster
  const MAX_SHEETS = 400;
  const PAPERS = {
    a4: { name: 'A4', w: 210, h: 297 },
    letter: { name: 'Letter', w: 215.9, h: 279.4 },
  };

  // ── Text ──────────────────────────────────────────────────────────────────

  /* Glyph widths in 1/1000 em of Helvetica and Helvetica-Bold for the codes
     32-126, from Adobe's AFM files, and for the few WinAnsi codes above
     those that the text here uses. */
  const W_REGULAR = [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556,
    556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556, 1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500,
    667, 556, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556, 333, 556,
    556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500, 278, 556, 500, 722, 500,
    500, 500, 334, 260, 334, 584];
  const W_BOLD = [278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556,
    556, 556, 556, 556, 556, 556, 333, 333, 584, 584, 584, 611, 975, 722, 722, 722, 722, 667, 611, 778, 722, 278, 556,
    722, 611, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 333, 278, 333, 584, 556, 333, 556,
    611, 556, 611, 556, 333, 611, 611, 278, 278, 556, 278, 889, 611, 611, 611, 611, 389, 556, 333, 611, 556, 778, 556,
    556, 500, 389, 280, 389, 584];
  const W_HIGH = new Map([[0x85, [1000, 1000]], [0x91, [222, 278]], [0x92, [222, 278]], [0x93, [333, 500]],
    [0x94, [333, 500]], [0x95, [350, 350]], [0x96, [556, 556]], [0x97, [1000, 1000]], [0xa0, [278, 278]],
    [0xb0, [400, 400]], [0xb7, [278, 278]], [0xd7, [584, 584]]]);
  /* WinAnsi is cp1252: Latin-1, except that 0x80-0x9F hold typographic
     characters, the dashes and curly quotes among them. */
  const CP1252 = new Map([['…', 0x85], ['‘', 0x91], ['’', 0x92], ['“', 0x93], ['”', 0x94],
    ['•', 0x95], ['–', 0x96], ['—', 0x97], ['€', 0x80]]);

  /* The WinAnsi code of a character; '?' for one the encoding lacks. */
  function winAnsi(ch) {
    const u = ch.codePointAt(0);
    if (u < 0x80 || (u >= 0xa0 && u <= 0xff)) return u;
    return CP1252.get(ch) || 63;
  }

  function textWidth(text, bold, size) {
    let w = 0;
    for (const ch of String(text)) {
      const code = winAnsi(ch);
      if (code >= 32 && code <= 126) w += (bold ? W_BOLD : W_REGULAR)[code - 32];
      else w += (W_HIGH.get(code) || [556, 556])[bold ? 1 : 0];
    }
    return w * size / 1000;
  }

  /* A PDF string literal. Bytes outside printable ASCII go as octal escapes,
     so every content stream is plain ASCII. */
  function pdfStr(text) {
    let out = '(';
    for (const ch of String(text)) {
      const code = winAnsi(ch);
      if (code === 40 || code === 41 || code === 92) out += '\\' + String.fromCharCode(code);
      else if (code < 32 || code > 126) out += '\\' + code.toString(8).padStart(3, '0');
      else out += String.fromCharCode(code);
    }
    return out + ')';
  }

  /* A string for the document's information, outside any page: those are
     read as PDFDocEncoding, not WinAnsi, so anything beyond ASCII goes as
     UTF-16. */
  function infoStr(text) {
    const s = String(text);
    if (/^[\x20-\x7e]*$/.test(s)) return pdfStr(s);
    let hex = '<FEFF';
    for (let i = 0; i < s.length; i++) hex += s.charCodeAt(i).toString(16).padStart(4, '0').toUpperCase();
    return hex + '>';
  }

  /* A number for a content stream: no exponent, which PDF does not read. */
  function num(v, places = 3) {
    const k = 10 ** places;
    const r = Math.round(v * k) / k;
    return Object.is(r, -0) ? '0' : String(r);
  }

  // ── The drawing ───────────────────────────────────────────────────────────

  const NUM = /[\s,]*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)/y;
  const FLAG = /[\s,]*([01])/y;
  const CMD = /[\s,]*([MmZzLlHhVvCcSsQqTtAa])/y;
  const END = /[\s,]*$/y;

  /*
    SVG path data as PDF path operators (m, l, c, h, one to a line), with
    the bounds of its points. All of SVG's path language is read: the
    quadratic and smooth curves become cubic ones, and arcs cubic ones of at
    most a quarter turn each. The bounds include the control points, so they
    may be a little wider than the ink, never narrower.

    With a matrix m ({a, b, c, d, e, f}) the bounds are of the points so
    transformed; with apply, so are the operators' coordinates.
  */
  function parse(d, m = null, apply = false) {
    const s = String(d || '');
    const out = [];
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    const f = (v) => {
      const r = Math.round(v * 1e4) / 1e4;
      return Object.is(r, -0) ? '0' : String(r);
    };
    const pt = (px, py) => {
      const tx = m ? m.a * px + m.c * py + m.e : px, ty = m ? m.b * px + m.d * py + m.f : py;
      if (tx < x0) x0 = tx; if (tx > x1) x1 = tx;
      if (ty < y0) y0 = ty; if (ty > y1) y1 = ty;
      return apply ? f(tx) + ' ' + f(ty) : f(px) + ' ' + f(py);
    };
    const curve = (a, b, c, e, px, py) => out.push(`${pt(a, b)} ${pt(c, e)} ${pt(px, py)} c`);
    const bad = () => new Error('The drawing\'s path data could not be read.');
    let i = 0;
    const read = (re) => {
      re.lastIndex = i;
      const r = re.exec(s);
      if (!r) return null;
      i = re.lastIndex;
      return r[1];
    };
    const n = () => {
      const v = read(NUM);
      if (v === null || !Number.isFinite(+v)) throw bad();
      return +v;
    };
    const flag = () => {
      const v = read(FLAG);
      if (v === null) throw bad();
      return v === '1';
    };
    // The current point, where the subpath began, and the last control
    // points, which S (cubic) and T (quadratic) reflect.
    let x = 0, y = 0, sx = 0, sy = 0, cx = null, cy = null, qx = null, qy = null, cmd = '';
    for (;;) {
      const c = read(CMD);
      if (c !== null) cmd = c;
      else {
        END.lastIndex = i;
        if (END.test(s)) break;
        // Numbers without a letter repeat the last command; none may follow Z.
        if (!cmd || cmd === 'Z' || cmd === 'z') throw bad();
      }
      const rel = cmd >= 'a';
      const ox = rel ? x : 0, oy = rel ? y : 0;
      switch (cmd) {
        case 'M': case 'm':
          x = sx = ox + n(); y = sy = oy + n();
          out.push(pt(x, y) + ' m');
          cmd = rel ? 'l' : 'L';   // further pairs are lines
          cx = qx = null;
          break;
        case 'L': case 'l': case 'H': case 'h': case 'V': case 'v':
          if (cmd === 'H' || cmd === 'h') x = ox + n();
          else if (cmd === 'V' || cmd === 'v') y = oy + n();
          else { x = ox + n(); y = oy + n(); }
          out.push(pt(x, y) + ' l');
          cx = qx = null;
          break;
        case 'C': case 'c': case 'S': case 's': {
          let a, b;
          if (cmd === 'C' || cmd === 'c') { a = ox + n(); b = oy + n(); }
          else { a = cx === null ? x : 2 * x - cx; b = cx === null ? y : 2 * y - cy; }
          cx = ox + n(); cy = oy + n();
          const ex = ox + n(), ey = oy + n();
          curve(a, b, cx, cy, ex, ey);
          x = ex; y = ey; qx = null;
          break;
        }
        case 'Q': case 'q': case 'T': case 't': {
          if (cmd === 'Q' || cmd === 'q') { qx = ox + n(); qy = oy + n(); }
          else { qx = qx === null ? x : 2 * x - qx; qy = qy === null ? y : 2 * y - qy; }
          const ex = ox + n(), ey = oy + n();
          curve(x + 2 / 3 * (qx - x), y + 2 / 3 * (qy - y), ex + 2 / 3 * (qx - ex), ey + 2 / 3 * (qy - ey), ex, ey);
          x = ex; y = ey; cx = null;
          break;
        }
        case 'A': case 'a': {
          const rx = n(), ry = n(), rot = n(), large = flag(), sweep = flag();
          const ex = ox + n(), ey = oy + n();
          for (const k of arcCurves(x, y, rx, ry, rot, large, sweep, ex, ey)) {
            if (k.length === 2) out.push(pt(k[0], k[1]) + ' l');
            else curve(...k);
          }
          x = ex; y = ey; cx = qx = null;
          break;
        }
        case 'Z': case 'z':
          out.push('h');
          x = sx; y = sy; cx = qx = null;
          break;
        default:
          throw bad();
      }
    }
    return { ops: out.join('\n'), bounds: x1 >= x0 ? { x0, y0, x1, y1 } : null };
  }

  /*
    An SVG arc as cubic Béziers of at most a quarter turn ([x1, y1, x2, y2,
    x, y] each), or a line ([x, y]) where a radius is 0: the endpoint to
    centre conversion of the SVG specification (appendix B.2.4), radii too
    small for the endpoints scaled up to just reach.
  */
  function arcCurves(x1, y1, rx, ry, rotDeg, large, sweep, x2, y2) {
    if (x1 === x2 && y1 === y2) return [];
    rx = Math.abs(rx); ry = Math.abs(ry);
    if (!rx || !ry) return [[x2, y2]];
    const phi = rotDeg * Math.PI / 180, cos = Math.cos(phi), sin = Math.sin(phi);
    const dx = (x1 - x2) / 2, dy = (y1 - y2) / 2;
    const xp = cos * dx + sin * dy, yp = -sin * dx + cos * dy;
    const lam = (xp * xp) / (rx * rx) + (yp * yp) / (ry * ry);
    if (lam > 1) { rx *= Math.sqrt(lam); ry *= Math.sqrt(lam); }
    const num2 = rx * rx * ry * ry - rx * rx * yp * yp - ry * ry * xp * xp;
    const den = rx * rx * yp * yp + ry * ry * xp * xp;
    let k = Math.sqrt(Math.max(0, num2 / den));
    if (large === sweep) k = -k;
    const cxp = k * rx * yp / ry, cyp = -k * ry * xp / rx;
    const cx = cos * cxp - sin * cyp + (x1 + x2) / 2, cy = sin * cxp + cos * cyp + (y1 + y2) / 2;
    const angle = (ux, uy, vx, vy) => Math.atan2(ux * vy - uy * vx, ux * vx + uy * vy);
    const t1 = angle(1, 0, (xp - cxp) / rx, (yp - cyp) / ry);
    let dt = angle((xp - cxp) / rx, (yp - cyp) / ry, (-xp - cxp) / rx, (-yp - cyp) / ry);
    if (!sweep && dt > 0) dt -= 2 * Math.PI;
    else if (sweep && dt < 0) dt += 2 * Math.PI;
    const parts = Math.max(1, Math.ceil(Math.abs(dt) / (Math.PI / 2) - 1e-9));
    const step = dt / parts, h = 4 / 3 * Math.tan(step / 4);
    const at = (t) => [cx + rx * Math.cos(t) * cos - ry * Math.sin(t) * sin, cy + rx * Math.cos(t) * sin + ry * Math.sin(t) * cos];
    const dir = (t) => [-rx * Math.sin(t) * cos - ry * Math.cos(t) * sin, -rx * Math.sin(t) * sin + ry * Math.cos(t) * cos];
    const out = [];
    for (let j = 0; j < parts; j++) {
      const a = t1 + j * step, b = a + step;
      const p = at(a), q = j === parts - 1 ? [x2, y2] : at(b), da = dir(a), db = dir(b);
      out.push([p[0] + h * da[0], p[1] + h * da[1], q[0] - h * db[0], q[1] - h * db[1], q[0], q[1]]);
    }
    return out;
  }

  // ── The layout ────────────────────────────────────────────────────────────

  /*
    How the drawing falls on the sheets. The poster is opt.n sheets across
    (opt.by 'across') or down ('down'), and the other way as many as the
    drawing needs; the drawing (its bounds, in source pixels) fills it less
    BORDER on each side, and is centred the other way.

    Lengths are millimetres, from the top left of the first sheet's printed
    area. Sheet (r, c) prints the area from (c*sx, r*sy), iw by ih; its
    neighbour to the right starts sx further on, so the two share an
    OVERLAP-wide glue strip. Every sheet's left and top margins are cut off,
    so the finished poster, FW by FH, runs from CUT_IN before the first
    printed area (fx0, fy0) to the last sheets' paper edges, MARGIN after
    the last: the white round the drawing is the same on all four sides,
    and nothing printed in a margin is left showing. A poster of a single
    sheet is not cut at all, and is that sheet.
  */
  function layout(bounds, opt = {}) {
    const P = PAPERS[opt.paper] || PAPERS.a4;
    const land = opt.orient === 'landscape';
    const pw = land ? P.h : P.w, ph = land ? P.w : P.h;
    const iw = pw - 2 * MARGIN, ih = ph - 2 * MARGIN;
    const sx = iw - OVERLAP, sy = ih - OVERLAP;
    const bw = Math.max(1e-9, bounds.x1 - bounds.x0), bh = Math.max(1e-9, bounds.y1 - bounds.y0);
    const n = Math.max(1, Math.round(+opt.n) || 1);
    const extra = CUT_IN + MARGIN;   // the finished poster past the printed area
    const span = (k, step, first) => (k - 1) * step + first;
    const need = (len, step, first) => Math.max(1, Math.ceil((len - extra - first) / step - 1e-9) + 1);
    let cols, rows, s;
    if (opt.by === 'down') {
      rows = n;
      s = (span(rows, sy, ih) + extra - 2 * BORDER) / bh;
      cols = need(s * bw + 2 * BORDER, sx, iw);
    } else {
      cols = n;
      s = (span(cols, sx, iw) + extra - 2 * BORDER) / bw;
      rows = need(s * bh + 2 * BORDER, sy, ih);
    }
    const W = span(cols, sx, iw), H = span(rows, sy, ih);
    const one = cols * rows === 1;
    const fx0 = one ? -MARGIN : -CUT_IN, fy0 = fx0;
    const FW = one ? pw : W + extra, FH = one ? ph : H + extra;
    const dw = s * bw, dh = s * bh;
    return {
      paper: P.name, pw, ph, iw, ih, sx, sy, cols, rows, sheets: cols * rows,
      W, H, FW, FH, fx0, fy0, s, dw, dh, ox: fx0 + (FW - dw) / 2, oy: fy0 + (FH - dh) / 2, bounds,
    };
  }

  /* Rows are letters (A-Z, then AA ...), columns numbers from 1. */
  function rowName(r) {
    let s = '';
    for (let k = r + 1; k > 0; k = Math.floor((k - 1) / 26)) s = String.fromCharCode(65 + (k - 1) % 26) + s;
    return s;
  }
  const sheetName = (r, c) => rowName(r) + (c + 1);
  const cm = (mm) => Math.round(mm / 10);

  // ── Drawing a page ────────────────────────────────────────────────────────

  /* A page's content stream, drawn in millimetres from its top left. */
  function canvas(pw, ph) {
    const ops = [];
    const X = (v) => num(v * MM), Y = (v) => num((ph - v) * MM);
    return {
      pw, ph,
      raw(s) { ops.push(s); },
      rect(x0, y0, x1, y1) { return `${X(x0)} ${Y(y1)} ${num((x1 - x0) * MM)} ${num((y1 - y0) * MM)} re`; },
      line(xa, ya, xb, yb) { return `${X(xa)} ${Y(ya)} m ${X(xb)} ${Y(yb)} l`; },
      /* Runs of text from a baseline origin; rot 90 reads upwards, -90 down. */
      text(x, y, runs, size, opt = {}) {
        const m = opt.rot === 90 ? '0 1 -1 0' : opt.rot === -90 ? '0 -1 1 0' : '1 0 0 1';
        let s = `BT ${num(opt.gray || 0)} g ${m} ${X(x)} ${Y(y)} Tm`;
        for (const r of runs) s += ` /${r.font || (r.bold ? 'F2' : 'F1')} ${num(r.size || size)} Tf ${pdfStr(r.t)} Tj`;
        ops.push(s + ' ET');
      },
      content() { return ops.join('\n') + '\n'; },
    };
  }

  const runsWidth = (runs, size) => runs.reduce((w, r) => w + textWidth(r.t, r.bold, r.size || size), 0) / MM;

  /*
    Runs of text wrapped into a width, from a top edge; returns the top of
    what would follow. Without a canvas it only measures. Words are split at
    white space only, so a run may end mid-word ('Cut' then ': ...').
  */
  function flow(g, x, top, width, runs, size, opt = {}) {
    const lead = (opt.leading || 1.32) * size / MM;
    const space = textWidth(' ', false, size) / MM;
    const words = [];
    let cur = null;
    for (const r of runs) {
      for (const p of r.t.split(/(\s+)/)) {
        if (!p) continue;
        if (/^\s+$/.test(p)) { cur = null; continue; }
        if (!cur) { cur = { parts: [], w: 0 }; words.push(cur); }
        cur.parts.push({ t: p, bold: !!r.bold });
        cur.w += textWidth(p, !!r.bold, size) / MM;
      }
    }
    const lines = [];
    let line = [], lw = 0;
    for (const w of words) {
      if (line.length && lw + space + w.w > width) { lines.push(line); line = []; lw = 0; }
      lw += (line.length ? space : 0) + w.w;
      line.push(w);
    }
    if (line.length) lines.push(line);
    if (g) {
      lines.forEach((ln, k) => {
        const out = [];
        ln.forEach((w, j) => w.parts.forEach((p, q) => {
          const t = (j && !q ? ' ' : '') + p.t;
          const last = out[out.length - 1];
          if (last && last.bold === p.bold) last.t += t; else out.push({ t, bold: p.bold });
        }));
        g.text(x, top + k * lead + 0.78 * size / MM, out, size, { gray: opt.gray });
      });
    }
    return top + lines.length * lead;
  }

  /* The cm that puts the drawing's top left corner at (left, top), at scale
     millimetres a source pixel. */
  function artAt(g, L, left, top, scale) {
    const b = L.bounds;
    return `${num(MM * scale, 6)} 0 0 ${num(-MM * scale, 6)} ${num(MM * (left - scale * b.x0), 4)} ` +
      `${num(MM * (g.ph - top + scale * b.y0), 4)} cm`;
  }

  /* Diagonal hatching inside a rectangle. */
  function hatch(g, x0, y0, x1, y1, gap, grey) {
    const step = gap * Math.SQRT2;
    let s = `q ${g.rect(x0, y0, x1, y1)} W n ${grey} G 0.35 w`;
    for (let k = x0 + y0 + step / 2; k < x1 + y1; k += step) s += ' ' + g.line(k - y0, y0, k - y1, y1);
    g.raw(s + ' S Q');
  }

  // ── A sheet ───────────────────────────────────────────────────────────────

  function sheetPage(L, r, c) {
    const g = canvas(L.pw, L.ph);
    const left = MARGIN, top = MARGIN, right = MARGIN + L.iw, bottom = MARGIN + L.ih;
    const art = artAt(g, L, left + L.ox - c * L.sx, top + L.oy - r * L.sy, L.s);
    if (L.sheets === 1) {
      g.raw(`q ${g.rect(left, top, right, bottom)} W n ${art} /Art Do Q`);
      return g.content();
    }
    // The drawing: past the edges to be cut by BLEED, up to the glue strips.
    // The cut lines go under it, so what is left of them on an edge can only
    // show on white.
    const lastC = c === L.cols - 1, lastR = r === L.rows - 1;
    const ax0 = left - BLEED, ay0 = top - BLEED;
    const ax1 = right - (lastC ? 0 : OVERLAP), ay1 = bottom - (lastR ? 0 : OVERLAP);
    const cuts = [['v', left - CUT_IN, ay0, bottom], ['h', top - CUT_IN, ax0, right]];
    for (const [dir, at, from, to] of cuts) cutLine(g, dir, at, from, to, 'under');
    g.raw(`q ${g.rect(ax0, ay0, ax1, ay1)} W n ${art} /Art Do Q`);

    const name = sheetName(r, c);
    if (!lastC) glueStrip(g, 'v', ax1, ay0, right, bottom, name, sheetName(r, c + 1));
    if (!lastR) glueStrip(g, 'h', ax0, ay1, right, bottom, name, sheetName(r + 1, c));
    for (const [dir, at, from, to] of cuts) cutLine(g, dir, at, from, to, 'over');

    // The sheet's name and what to do with it, in the top margin, which is
    // cut off with all on it.
    const label = [
      { t: name, bold: true, size: 10 },
      { t: `    row ${rowName(r)}, column ${c + 1}   ·   sheet ${r * L.cols + c + 1} of ${L.sheets}   ·   ` +
        'cut off the left and top margins on the dashed lines' },
    ];
    const lx = left + 3;
    g.text(lx, 6.6, label, 8);

    // Where the sheet is on the poster, if there is room beside the label.
    const cell = Math.min(1.8, 5.6 / L.rows, 48 / L.cols);
    const mx = right - cell * L.cols, my = 1.4 + (5.6 - cell * L.rows) / 2;
    if (cell >= 0.6 && mx > lx + runsWidth(label, 8) + 5) {
      let s = `q 0.55 G 0.3 w ${g.rect(mx, my, right, my + cell * L.rows)}`;
      for (let k = 1; k < L.cols; k++) s += ' ' + g.line(mx + k * cell, my, mx + k * cell, my + cell * L.rows);
      for (let k = 1; k < L.rows; k++) s += ' ' + g.line(mx, my + k * cell, right, my + k * cell);
      g.raw(`${s} S 0 g ${g.rect(mx + c * cell, my + r * cell, mx + (c + 1) * cell, my + (r + 1) * cell)} f Q`);
    }
    return g.content();
  }

  /* A glue strip, which the next sheet (right, 'v', or below, 'h') covers:
     hatched, with the grey line that sheet's cut edge goes onto, and the
     sheet's own name, which its margin no longer shows once cut off. */
  function glueStrip(g, dir, x0, y0, x1, y1, own, next) {
    hatch(g, x0, y0, x1, y1, 2.5, 0.8);
    const gl = dir === 'v' ? g.line(x0 + 0.35, y0, x0 + 0.35, y1) : g.line(x0, y0 + 0.35, x1, y0 + 0.35);
    g.raw(`q 0.45 G 0.5 w ${gl} S Q`);
    const runs = [{ t: own, bold: true }, { t: '  ·  ' }, { t: 'GLUE HERE', bold: true },
      { t: `  ·  sheet ${next} goes on top, its cut edge just covering the grey line` }];
    const size = 7, w = runsWidth(runs, size), h = 1.55;
    const cx = (x0 + x1) / 2 + (dir === 'v' ? 0.3 : 0), cy = (y0 + y1) / 2 + (dir === 'h' ? 0.3 : 0);
    const up = 0.36 * size / MM;   // from the middle of the capitals to the baseline
    if (dir === 'v') {
      g.raw(`q 1 g ${g.rect(cx - h, cy - w / 2 - 1.2, cx + h, cy + w / 2 + 1.2)} f Q`);
      g.text(cx + up, cy + w / 2, runs, size, { rot: 90 });
    } else {
      g.raw(`q 1 g ${g.rect(cx - w / 2 - 1.2, cy - h, cx + w / 2 + 1.2, cy + h)} f Q`);
      g.text(cx - w / 2, cy + up, runs, size);
    }
  }

  /* A dashed cut line, at `at` across the page: light where the drawing is
     (from `from` to `to`), drawn under it, as a sliver of the line may stay
     on the edge; dark in the margins. The scissors where it starts lie
     wholly on the side that is cut off. */
  function cutLine(g, dir, at, from, to, part) {
    const seg = (a, b) => (dir === 'v' ? g.line(at, a, at, b) : g.line(a, at, b, at));
    if (part === 'under') {
      g.raw(`q [4 2.5] 0 d 0.6 w 0.62 G ${seg(from, to)} S Q`);
      return;
    }
    g.raw(`q [4 2.5] 0 d 0.5 w 0.2 G ${seg(0, from)} ${seg(to, dir === 'v' ? g.ph : g.pw)} S Q`);
    // ZapfDingbats' scissors reach from 0.035 to 0.655 em off their baseline.
    const size = 11, lo = 0.035 * size / MM, hi = 0.655 * size / MM, gap = 0.35;
    if (dir === 'v') g.text(at - gap - hi, 1.2, [{ t: '"', font: 'F3' }], size, { rot: -90 });
    else g.text(1.2, at - gap + lo, [{ t: '"', font: 'F3' }], size);
  }

  // ── The first page ────────────────────────────────────────────────────────

  function guidePage(L, name) {
    const g = canvas(L.pw, L.ph);
    const m = 15, cw = L.pw - 2 * m;
    const land = L.pw > L.ph;
    const many = L.sheets > 1;
    let y = m;

    y = flow(g, m, y, cw, [{ t: `Poster: ${L.sheets} ${many ? 'sheets' : 'sheet'} of ${L.paper}`, bold: true }], 20, { leading: 1.2 });
    g.text(m, y + 3.6, [{ t: `${name}   ·   ${L.cols} across, ${L.rows} down   ·   ` +
      `${cm(L.FW)} × ${cm(L.FH)} cm when put together` }], 10, { gray: 0.3 });
    y += 9;

    // Printing at the right size, in a box.
    const pages = many ? `pages 2–${L.sheets + 1}` : 'page 2';
    const bw = cw - 8;
    const say = [{ t: `Print ${pages} one-sided at 100 % (“Actual size”), not “Fit to page”.`, bold: true }];
    const check = [{ t: 'The bar at the foot of this page then measures 10 cm. If it is shorter or longer, the sheets will not line up.' }];
    const bh = flow(null, 0, 0, bw, say, 10) + flow(null, 0, 0, bw, check, 9) + 5;
    g.raw(`q 0.93 g ${g.rect(m, y, m + cw, y + bh)} f Q`);
    flow(g, m + 4, flow(g, m + 4, y + 2.5, bw, say, 10), bw, check, 9);
    y += bh + 6;

    // What to do, step by step.
    const steps = many ? [
      [{ t: 'Lay out', bold: true }, { t: ' the sheets as in the picture: row A at the top, column 1 on the left. ' +
        'Each sheet’s name is in its top margin, and again on its glue strips.' }],
      [{ t: 'Cut', bold: true }, { t: ' off the left and top margins of every sheet, A1 too, on the dashed lines, and put each back in ' +
        'its place. The names and marks in those margins go with them, so none are left on the poster.' }],
    ] : [[{ t: 'One sheet', bold: true }, { t: ': the drawing fits on a single sheet, so there is nothing to cut or glue.' }]];
    if (L.cols > 1) {
      steps.push([{ t: L.rows > 1 ? 'Glue each row' : 'Glue the sheets', bold: true }, { t: ' from left to right: glue on the hatched strip ' +
        'down the right of a sheet, then lay the next sheet on it so that its cut edge just covers the grey line and the drawing runs on.' }]);
    }
    if (L.rows > 1) {
      steps.push([{ t: L.cols > 1 ? 'Join the rows' : 'Glue the sheets', bold: true }, { t: ' from the top down, the same way: ' +
        `each cut top edge over the hatched strip along the bottom of the ${L.cols > 1 ? 'row' : 'sheet'} above, just covering the grey line.` }]);
    }
    if (many) steps.push([{ t: 'Put it up', bold: true }, { t: '. The white edge round the poster is blank paper, the same all round, so there is nothing to trim.' }]);

    const tips = !many ? [] : [
      [{ t: 'A glue stick or double-sided tape works best: wet glue wrinkles paper.' }],
      [{ t: 'Line the sheets up by the grey lines and the drawing, not by the paper’s edges, which a printer seldom places exactly.' }],
      [{ t: 'Colour it in sheet by sheet before gluing, or all at once after.' }],
    ];

    // The text goes under the picture on an upright page, beside it on one
    // lying down; the picture gets the room the text leaves.
    const foot = L.ph - 16;
    const tx = land ? m + cw * 0.5 + 5 : m, tw = land ? cw * 0.5 - 5 : cw;
    const sketchW = 72, tipsW = tw - sketchW - 6;
    const textBlock = (gg, top) => {
      let t = top;
      steps.forEach((s, k) => {
        if (gg) gg.text(tx, t + 0.78 * 9.5 / MM, [{ t: `${k + 1}`, bold: true }], 9.5);
        t = flow(gg, tx + 5, t, tw - 5, s, 9.5) + 1.6;
      });
      t += 3;
      const sketchTop = t;
      if (many) {
        if (gg) overlapSketch(gg, tx, sketchTop, L.cols > 1);
        let u = t;
        tips.forEach((tip) => { u = flow(gg, tx + sketchW + 6, u, tipsW, tip, 8.5, { gray: 0.25 }) + 1.2; });
        t = Math.max(sketchTop + 33, u);
      } else {
        tips.forEach((tip) => { t = flow(gg, tx, t, tw, tip, 8.5, { gray: 0.25 }) + 1.2; });
      }
      return t;
    };
    const textH = textBlock(null, 0);
    let box;
    if (land) box = { x: m, y, w: cw * 0.5 - 5, h: foot - 4 - y };
    else box = { x: m, y, w: cw, h: Math.max(40, foot - 4 - y - textH - 6) };
    const used = posterPicture(g, L, box);
    textBlock(g, land ? y : y + used + 6);

    // A bar to check the scale by, and where the page came from.
    let s = 'q 0 G 0.4 w';
    for (let k = 0; k < 10; k++) s += ` ${k % 2 ? 1 : 0} g ${g.rect(m + 10 * k, foot + 2, m + 10 * (k + 1), foot + 4.4)} B`;
    g.raw(s + ' Q');
    g.text(m, foot + 8, [{ t: '0' }], 7, { gray: 0.3 });
    g.text(m + 100 - runsWidth([{ t: '10 cm' }], 7), foot + 8, [{ t: '10 cm' }], 7, { gray: 0.3 });
    const credit = [{ t: 'Made with kvotab.se/vectorize.html' }];
    g.text(L.pw - m - runsWidth(credit, 7), foot + 8, credit, 7, { gray: 0.45 });
    return g.content();
  }

  /* The whole poster in a box: the drawing, where the sheets meet, and the
     rows and columns named. Returns the height it took. */
  function posterPicture(g, L, box) {
    const hx = 5, hy = 4.5;   // room for the row letters and column numbers
    const k = Math.min((box.w - hx) / L.FW, (box.h - hy) / L.FH);
    const w = L.FW * k, h = L.FH * k;
    const x0 = box.x + hx + (box.w - hx - w) / 2, y0 = box.y + hy;
    const X = (p) => x0 + k * (p - L.fx0), Y = (p) => y0 + k * (p - L.fy0);   // poster mm to page mm
    g.raw(`q 1 g 0.55 G 0.5 w ${g.rect(x0, y0, x0 + w, y0 + h)} B Q`);
    g.raw(`q ${g.rect(x0, y0, x0 + w, y0 + h)} W n ${artAt(g, L, X(L.ox), Y(L.oy), k * L.s)} /Art Do Q`);

    // Where one sheet's cut edge lies on the next.
    let s = 'q [2.5 1.8] 0 d 0.7 w 0.1 0.42 0.85 RG';
    for (let c = 1; c < L.cols; c++) s += ' ' + g.line(X(c * L.sx - CUT_IN), y0, X(c * L.sx - CUT_IN), y0 + h);
    for (let r = 1; r < L.rows; r++) s += ' ' + g.line(x0, Y(r * L.sy - CUT_IN), x0 + w, Y(r * L.sy - CUT_IN));
    g.raw(s + ' S Q');

    // Each sheet's part of the finished poster: from its cut edge to the
    // next one's, the last running on to the poster's edge.
    const band = (i, n, step, from, len) => [i ? i * step - CUT_IN : from, i === n - 1 ? from + len : (i + 1) * step - CUT_IN];
    const cellW = k * L.sx, cellH = k * L.sy;
    const hs = Math.max(4.5, Math.min(8, Math.min(cellW, cellH) * MM * 0.3));
    for (let c = 0; c < L.cols; c++) {
      const [a, b] = band(c, L.cols, L.sx, L.fx0, L.FW), t = String(c + 1);
      g.text((X(a) + X(b)) / 2 - runsWidth([{ t }], hs) / 2, y0 - 1.3, [{ t, bold: true }], hs, { gray: 0.35 });
    }
    for (let r = 0; r < L.rows; r++) {
      const [a, b] = band(r, L.rows, L.sy, L.fy0, L.FH), t = rowName(r);
      g.text(x0 - 1.3 - runsWidth([{ t, bold: true }], hs), (Y(a) + Y(b)) / 2 + 0.36 * hs / MM, [{ t, bold: true }], hs, { gray: 0.35 });
    }
    // The names in the sheets too, where they fit.
    const ns = Math.min(8, cellH * MM * 0.22);
    if (cellW >= 8 && ns >= 4.5) {
      for (let r = 0; r < L.rows; r++) {
        for (let c = 0; c < L.cols; c++) {
          const t = [{ t: sheetName(r, c), bold: true }];
          const tw = runsWidth(t, ns), lx = X(band(c, L.cols, L.sx, L.fx0, L.FW)[0]) + 0.9;
          const ly = Y(band(r, L.rows, L.sy, L.fy0, L.FH)[0]) + 0.9;
          g.raw(`q 1 g ${g.rect(lx, ly, lx + tw + 1.2, ly + 0.95 * ns / MM)} f Q`);
          g.text(lx + 0.6, ly + 0.76 * ns / MM, t, ns, { gray: 0.1 });
        }
      }
    }
    return hy + h;
  }

  /* Two sheets side by side: A1's glue strip and grey line, and A2, its
     left margin cut off, about to go over them. */
  function overlapSketch(g, x, y, across) {
    const w = 27, h = 21, strip = 6.5, gap = 13;
    const a = across ? ['A1', 'A2'] : ['A1', 'B1'];
    g.raw(`q 1 g 0 G 0.6 w ${g.rect(x, y, x + w, y + h)} B Q`);
    hatch(g, x + w - strip, y, x + w, y + h, 1.5, 0.7);
    g.raw(`q 0.4 G 0.6 w ${g.line(x + w - strip + 0.4, y, x + w - strip + 0.4, y + h)} S Q`);
    g.text(x + 2.5, y + 5.5, [{ t: a[0], bold: true }], 9);
    const x2 = x + w + gap;
    g.raw(`q 1 g 0 G 0.6 w ${g.rect(x2, y, x2 + w, y + h)} B Q`);
    g.text(x2 + 2.5, y + 5.5, [{ t: a[1], bold: true }], 9);
    const ay = y + h / 2, tip = x + w - strip + 0.9;
    g.raw(`q 0 G 0 g 0.8 w ${g.line(x2 - 1, ay, tip + 2.2, ay)} S ` +
      `${num(tip * MM)} ${num((g.ph - ay) * MM)} m ${num((tip + 2.6) * MM)} ${num((g.ph - ay + 1.3) * MM)} l ` +
      `${num((tip + 2.6) * MM)} ${num((g.ph - ay - 1.3) * MM)} l f Q`);
    flow(g, x, y + h + 1.5, w * 2 + gap, [{ t: `${a[1]}’s cut edge goes onto ${a[0]}’s grey line, over the glue.` +
      (across ? '' : ' (Rows go the same way, top over bottom strip.)') }], 7.5, { gray: 0.3 });
  }

  // ── An SVG as it is ───────────────────────────────────────────────────────

  /*
    An SVG file for the poster as it is, rather than traced: each shape in
    vectors, with its own fill and stroke. The browser lays the file out in
    a frame of its own, sandboxed and allowed to fetch nothing, so nothing
    in the file can run or call out; the shapes are read from there, each
    with its styles as the browser resolved them (classes, inheritance,
    units) and its transform into the root's user space, and become the
    same kind of drawing parse() makes of a trace, with its paint.

    Text, pictures inside the SVG, filters and masks are left out, and the
    result's notes say so; a gradient is printed as the average colour of
    its stops. Browser only: it needs a document to lay the SVG out in.
  */
  const SVG_NS = 'http://www.w3.org/2000/svg';
  const XLINK_NS = 'http://www.w3.org/1999/xlink';
  const SHAPES = new Set(['path', 'rect', 'circle', 'ellipse', 'line', 'polyline', 'polygon']);
  const GROUPS = new Set(['g', 'svg', 'a', 'switch']);
  const CAPS = { butt: 0, round: 1, square: 2 };
  const JOINS = { miter: 0, 'miter-clip': 0, arcs: 0, round: 1, bevel: 2 };

  async function fromSvg(text) {
    const xml = new DOMParser().parseFromString(String(text), 'image/svg+xml');
    const top = xml.documentElement;
    if (xml.getElementsByTagName('parsererror').length || !top || top.localName !== 'svg' || top.namespaceURI !== SVG_NS) {
      throw new Error('That SVG file could not be read.');
    }
    // The frame runs no scripts anyway; these go before the file is shown at all.
    for (const el of [...xml.getElementsByTagNameNS(SVG_NS, 'script'), ...xml.getElementsByTagNameNS(SVG_NS, 'foreignObject')]) el.remove();
    for (const el of xml.getElementsByTagName('*')) {
      for (const a of [...el.attributes]) if (/^on/i.test(a.localName)) el.removeAttributeNode(a);
    }

    const frame = document.createElement('iframe');
    frame.setAttribute('sandbox', 'allow-same-origin');
    frame.setAttribute('aria-hidden', 'true');
    frame.tabIndex = -1;
    frame.style.cssText = 'position:fixed;left:-30000px;top:0;width:1000px;height:1000px;border:0;visibility:hidden';
    frame.srcdoc = '<!doctype html><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" ' +
      'content="default-src \'none\'; style-src \'unsafe-inline\'"><body style="margin:0">';
    const loaded = new Promise((resolve) => frame.addEventListener('load', resolve, { once: true }));
    document.body.appendChild(frame);
    try {
      await loaded;
      const doc = frame.contentDocument;
      const root = doc.importNode(top, true);
      doc.body.appendChild(root);
      expandUses(root, doc);
      return svgArt(root, doc, frame.contentWindow);
    } finally {
      frame.remove();
    }
  }

  /* <use> draws a copy of what it points at, in a shadow tree the page
     cannot walk; it is replaced here by that copy, in a <g>. */
  function expandUses(root, doc) {
    let budget = 20000;
    for (let pass = 0; pass < 12; pass++) {
      const uses = [...root.getElementsByTagNameNS(SVG_NS, 'use')];
      if (!uses.length) return;
      for (const use of uses) {
        const href = use.getAttribute('href') || use.getAttributeNS(XLINK_NS, 'href') || '';
        const target = href[0] === '#' ? doc.getElementById(href.slice(1)) : null;
        const g = doc.createElementNS(SVG_NS, 'g');
        for (const a of use.attributes) {
          if (!a.namespaceURI && !/^(x|y|width|height|href|transform)$/.test(a.name)) g.setAttribute(a.name, a.value);
        }
        g.setAttribute('transform', `${use.getAttribute('transform') || ''} translate(${use.x.baseVal.value} ${use.y.baseVal.value})`);
        // Not what holds the <use> itself, which would never end.
        if (target && !target.contains(use) && --budget > 0) {
          if (target.localName === 'symbol') {
            const svg = doc.createElementNS(SVG_NS, 'svg');
            for (const a of ['viewBox', 'preserveAspectRatio']) if (target.hasAttribute(a)) svg.setAttribute(a, target.getAttribute(a));
            svg.setAttribute('width', use.getAttribute('width') || target.getAttribute('width') || '100%');
            svg.setAttribute('height', use.getAttribute('height') || target.getAttribute('height') || '100%');
            for (const ch of target.childNodes) svg.appendChild(ch.cloneNode(true));
            g.appendChild(svg);
          } else {
            g.appendChild(target.cloneNode(true));
          }
        }
        use.replaceWith(g);
      }
    }
  }

  /* A shape element's outline as path data, in its own user space. */
  function shapeData(el, tag) {
    const v = (name) => el[name].baseVal.value;
    switch (tag) {
      case 'path':
        return el.getAttribute('d') || '';
      case 'rect': {
        const x = v('x'), y = v('y'), w = v('width'), h = v('height');
        if (!(w > 0 && h > 0)) return '';
        let rx = el.hasAttribute('rx') ? v('rx') : NaN, ry = el.hasAttribute('ry') ? v('ry') : NaN;
        if (Number.isNaN(rx)) rx = Number.isNaN(ry) ? 0 : ry;
        if (Number.isNaN(ry)) ry = rx;
        rx = Math.min(Math.max(rx, 0), w / 2); ry = Math.min(Math.max(ry, 0), h / 2);
        if (!rx || !ry) return `M${x} ${y}H${x + w}V${y + h}H${x}Z`;
        const a = (ex, ey) => `A${rx} ${ry} 0 0 1 ${ex} ${ey}`;
        return `M${x + rx} ${y}H${x + w - rx}${a(x + w, y + ry)}V${y + h - ry}${a(x + w - rx, y + h)}` +
          `H${x + rx}${a(x, y + h - ry)}V${y + ry}${a(x + rx, y)}Z`;
      }
      case 'circle': case 'ellipse': {
        const cx = v('cx'), cy = v('cy');
        const rx = tag === 'circle' ? v('r') : v('rx'), ry = tag === 'circle' ? rx : v('ry');
        if (!(rx > 0 && ry > 0)) return '';
        return `M${cx + rx} ${cy}A${rx} ${ry} 0 0 1 ${cx - rx} ${cy}A${rx} ${ry} 0 0 1 ${cx + rx} ${cy}Z`;
      }
      case 'line':
        return `M${v('x1')} ${v('y1')}L${v('x2')} ${v('y2')}`;
      case 'polyline': case 'polygon': {
        const pts = el.points;
        if (!pts || pts.numberOfItems < 2) return '';
        let d = '';
        for (let k = 0; k < pts.numberOfItems; k++) {
          const p = pts.getItem(k);
          d += `${k ? 'L' : 'M'}${p.x} ${p.y}`;
        }
        return tag === 'polygon' ? d + 'Z' : d;
      }
      default:
        return '';
    }
  }

  function svgArt(root, doc, view) {
    // Matrices from the frame are copied into this page's own kind, which
    // some browsers would not otherwise multiply together.
    const mat = (x) => new DOMMatrix([x.a, x.b, x.c, x.d, x.e, x.f]);
    const rootCtm = root.getScreenCTM();
    if (!rootCtm) throw new Error('That SVG could not be laid out.');
    const inv = mat(rootCtm).inverse();
    const notes = new Set();
    const all = { x0: Infinity, y0: Infinity, x1: -Infinity, y1: -Infinity };
    const grow = (b, pad) => {
      all.x0 = Math.min(all.x0, b.x0 - pad); all.y0 = Math.min(all.y0, b.y0 - pad);
      all.x1 = Math.max(all.x1, b.x1 + pad); all.y1 = Math.max(all.y1, b.y1 + pad);
    };
    const ownTransform = (el) => {
      const t = el.transform && el.transform.baseVal.consolidate();
      return t ? mat(t.matrix) : new DOMMatrix();
    };
    const toRoot = (el) => inv.multiply(mat(el.getScreenCTM()));
    const amount = (v, dflt) => (Number.isFinite(parseFloat(v)) ? parseFloat(v) : dflt);

    /* A computed colour (or paint) as {r, g, b, a}, 0-255 and 0-1. */
    const probe = document.createElement('canvas').getContext('2d');
    const colour = (v) => {
      let m = /^rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)(?:[\s,/]+([\d.]+%?))?\s*\)$/.exec(v);
      if (!m && probe) {
        // Other colour forms (a colour space, a name) by way of a canvas, which writes hex or rgba().
        probe.fillStyle = '#000';
        probe.fillStyle = v;
        const h = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(probe.fillStyle);
        if (h) return { r: parseInt(h[1], 16), g: parseInt(h[2], 16), b: parseInt(h[3], 16), a: 1 };
        m = /^rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)(?:[\s,/]+([\d.]+%?))?\s*\)$/.exec(probe.fillStyle);
      }
      if (!m) return null;
      const a = m[4] === undefined ? 1 : /%$/.test(m[4]) ? parseFloat(m[4]) / 100 : +m[4];
      return { r: +m[1], g: +m[2], b: +m[3], a };
    };
    const gradientColour = (gr) => {
      for (let k = 0; gr && k < 10; k++) {
        const stops = [...gr.children].filter(s => s.localName === 'stop');
        if (stops.length) {
          const sum = { r: 0, g: 0, b: 0, a: 0 };
          for (const st of stops) {
            const cs = view.getComputedStyle(st);
            const c = colour(cs.stopColor) || { r: 0, g: 0, b: 0, a: 1 };
            sum.r += c.r; sum.g += c.g; sum.b += c.b; sum.a += c.a * amount(cs.stopOpacity, 1);
          }
          return { r: sum.r / stops.length, g: sum.g / stops.length, b: sum.b / stops.length, a: sum.a / stops.length };
        }
        const href = gr.getAttribute('href') || gr.getAttributeNS(XLINK_NS, 'href') || '';
        gr = href[0] === '#' ? doc.getElementById(href.slice(1)) : null;
      }
      return null;
    };
    const paint = (v) => {
      if (!v || v === 'none') return null;
      const ref = /url\(\s*["']?#([^"')]+)["']?\s*\)\s*(.*)$/.exec(v);
      if (!ref) return colour(v);
      const target = doc.getElementById(ref[1]);
      if (target && /Gradient$/.test(target.localName)) {
        const c = gradientColour(target);
        if (c) { notes.add('gradients'); return c; }
      }
      if (ref[2] && ref[2] !== 'none') return colour(ref[2]);
      notes.add(target && target.localName === 'pattern' ? 'patterns' : 'paints');
      return null;
    };

    /* An element's clip path, in the root's user space, or null. */
    const clipOf = (el, cs) => {
      const v = cs.clipPath;
      if (!v || v === 'none') return null;
      const ref = /url\(\s*["']?#([^"')]+)["']?\s*\)/.exec(v);
      const cp = ref && doc.getElementById(ref[1]);
      if (!cp || cp.localName !== 'clipPath') { notes.add('clipping'); return null; }
      let base = toRoot(el);
      if (cp.getAttribute('clipPathUnits') === 'objectBoundingBox') {
        const bb = el.getBBox();
        base = base.multiply(new DOMMatrix([bb.width, 0, 0, bb.height, bb.x, bb.y]));
      }
      base = base.multiply(ownTransform(cp));
      const parts = [];
      let rule = 'nonzero';
      const take = (node, m) => {
        for (const ch of node.children) {
          if (ch.localName === 'g') { take(ch, m.multiply(ownTransform(ch))); continue; }
          if (!SHAPES.has(ch.localName)) continue;
          const d = shapeData(ch, ch.localName);
          if (!d) continue;
          const p = parse(d, m.multiply(ownTransform(ch)), true);
          if (p.ops) parts.push(p.ops);
          rule = view.getComputedStyle(ch).clipRule;
        }
      };
      take(cp, base);
      return { ops: parts.join('\n'), rule };
    };

    const walk = (node, opacity, out) => {
      for (const el of node.children) {
        if (el.namespaceURI !== SVG_NS) continue;
        const tag = el.localName;
        if (tag === 'text') { notes.add('text'); continue; }
        if (tag === 'image') { notes.add('pictures'); continue; }
        if (!GROUPS.has(tag) && !SHAPES.has(tag)) continue;   // defs, symbols, markers, styles ...
        const cs = view.getComputedStyle(el);
        if (cs.display === 'none') continue;
        if (cs.filter && cs.filter !== 'none') notes.add('filters');
        if ((cs.mask && cs.mask !== 'none') || (cs.maskImage && cs.maskImage !== 'none')) notes.add('masks');
        const op = opacity * amount(cs.opacity, 1);
        if (op <= 0) continue;
        let into = out;
        const clip = clipOf(el, cs);
        if (clip) {
          if (!clip.ops) continue;   // an empty clip path hides it all
          const group = { clip, items: [] };
          out.push(group);
          into = group.items;
        }
        if (GROUPS.has(tag)) { walk(el, op, into); continue; }
        if (cs.visibility !== 'visible') continue;
        const d = shapeData(el, tag);
        if (!d) continue;
        const fill = tag === 'line' ? null : paint(cs.fill);
        const stroke = paint(cs.stroke);
        const sw = amount(cs.strokeWidth, 1);
        const fa = fill ? fill.a * amount(cs.fillOpacity, 1) * op : 0;
        const sa = stroke && sw > 0 ? stroke.a * amount(cs.strokeOpacity, 1) * op : 0;
        if (fa <= 0 && sa <= 0) continue;
        const m = toRoot(el);
        if (!Number.isFinite(m.a + m.b + m.c + m.d + m.e + m.f) || !(m.a * m.d - m.b * m.c)) continue;
        const p = parse(d, m);
        if (!p.bounds) continue;
        const scale = Math.max(Math.hypot(m.a, m.b), Math.hypot(m.c, m.d));
        grow(p.bounds, sa > 0 ? sw * 0.71 * scale : 0);   // half the width, and a corner's reach
        const dash = (cs.strokeDasharray || 'none').split(/[\s,]+/).map(parseFloat).filter(Number.isFinite);
        out.push({
          ops: p.ops, m, rule: cs.fillRule === 'evenodd' ? 'evenodd' : 'nonzero',
          fill: fa > 0 ? fill : null, fa, stroke: sa > 0 ? stroke : null, sa, sw,
          cap: cs.strokeLinecap in CAPS ? cs.strokeLinecap : 'butt', join: cs.strokeLinejoin in JOINS ? cs.strokeLinejoin : 'miter',
          miter: Math.max(1, amount(cs.strokeMiterlimit, 4)),
          dash: dash.length && dash.some(x => x > 0) && dash.every(x => x >= 0) ? (dash.length % 2 ? dash.concat(dash) : dash) : null,
          dashOffset: amount(cs.strokeDashoffset, 0),
        });
      }
    };
    const items = [];
    walk(root, 1, items);

    // What the SVG shows is its own viewport; a file that gives it no size
    // is shown whole.
    let bounds = all.x1 > all.x0 && all.y1 > all.y0 ? all : null;
    let viewClip = '';
    if (bounds && (root.hasAttribute('viewBox') || root.hasAttribute('width') || root.hasAttribute('height'))) {
      const r = root.getBoundingClientRect();
      const corners = [[r.left, r.top], [r.right, r.top], [r.left, r.bottom], [r.right, r.bottom]]
        .map(([px, py]) => new DOMPoint(px, py).matrixTransform(inv));
      const v = {
        x0: Math.min(...corners.map(p => p.x)), y0: Math.min(...corners.map(p => p.y)),
        x1: Math.max(...corners.map(p => p.x)), y1: Math.max(...corners.map(p => p.y)),
      };
      bounds = { x0: Math.max(bounds.x0, v.x0), y0: Math.max(bounds.y0, v.y0), x1: Math.min(bounds.x1, v.x1), y1: Math.min(bounds.y1, v.y1) };
      if (!(bounds.x1 > bounds.x0 && bounds.y1 > bounds.y0)) bounds = null;
      viewClip = `${num(v.x0, 4)} ${num(v.y0, 4)} ${num(v.x1 - v.x0, 4)} ${num(v.y1 - v.y0, 4)} re W n`;
    }

    // The drawing for the PDF: each shape in its own transform, with its paint.
    const gstates = new Map();
    const gs = (ca, CA) => {
      const key = `${num(ca)} ${num(CA)}`;
      if (!gstates.has(key)) gstates.set(key, `A${gstates.size}`);
      return gstates.get(key);
    };
    const pdfColour = (c) => [c.r, c.g, c.b].map(x => num(x / 255)).join(' ');
    const matrix = (m) => `${num(m.a, 6)} ${num(m.b, 6)} ${num(m.c, 6)} ${num(m.d, 6)} ${num(m.e, 4)} ${num(m.f, 4)}`;
    const toPdf = (list, out) => {
      for (const it of list) {
        if (it.clip) {
          out.push('q', it.clip.ops, it.clip.rule === 'evenodd' ? 'W* n' : 'W n');
          toPdf(it.items, out);
          out.push('Q');
          continue;
        }
        out.push('q', `${matrix(it.m)} cm`);
        const ca = it.fill ? it.fa : 1, CA = it.stroke ? it.sa : 1;
        if (ca < 1 || CA < 1) out.push(`/${gs(ca, CA)} gs`);
        if (it.fill) out.push(`${pdfColour(it.fill)} rg`);
        if (it.stroke) {
          out.push(`${pdfColour(it.stroke)} RG ${num(it.sw, 4)} w ${CAPS[it.cap]} J ${JOINS[it.join]} j ${num(it.miter)} M`);
          if (it.dash) out.push(`[${it.dash.map(x => num(x, 4)).join(' ')}] ${num(it.dashOffset, 4)} d`);
        }
        const eo = it.rule === 'evenodd' ? '*' : '';
        out.push(it.ops, it.fill && it.stroke ? 'B' + eo : it.fill ? 'f' + eo : 'S', 'Q');
      }
    };
    const pdf = viewClip ? ['q', viewClip] : [];
    toPdf(items, pdf);
    if (viewClip) pdf.push('Q');

    // And the same as an SVG of plain paths, to show in the dialog: what
    // will be printed, not the file as it came.
    const toD = (ops) => ops.split('\n').map((l) => {
      const op = l.charAt(l.length - 1);
      return op === 'h' ? 'Z' : (op === 'm' ? 'M' : op === 'l' ? 'L' : 'C') + l.slice(0, -2);
    }).join('');
    const css = (c) => `rgb(${Math.round(c.r)},${Math.round(c.g)},${Math.round(c.b)})`;
    const defs = [];
    const toSvg = (list, out) => {
      for (const it of list) {
        if (it.clip) {
          const id = `c${defs.length}`;
          defs.push(`<clipPath id="${id}"><path d="${toD(it.clip.ops)}" clip-rule="${it.clip.rule === 'evenodd' ? 'evenodd' : 'nonzero'}"/></clipPath>`);
          out.push(`<g clip-path="url(#${id})">`);
          toSvg(it.items, out);
          out.push('</g>');
          continue;
        }
        let a = `d="${toD(it.ops)}" transform="matrix(${matrix(it.m)})" fill="${it.fill ? css(it.fill) : 'none'}"`;
        if (it.fill && it.fa < 1) a += ` fill-opacity="${num(it.fa)}"`;
        if (it.rule === 'evenodd') a += ' fill-rule="evenodd"';
        if (it.stroke) {
          a += ` stroke="${css(it.stroke)}" stroke-width="${num(it.sw, 4)}" stroke-linecap="${it.cap}" ` +
            `stroke-linejoin="${it.join === 'round' || it.join === 'bevel' ? it.join : 'miter'}" stroke-miterlimit="${num(it.miter)}"`;
          if (it.sa < 1) a += ` stroke-opacity="${num(it.sa)}"`;
          if (it.dash) a += ` stroke-dasharray="${it.dash.map(x => num(x, 4)).join(' ')}" stroke-dashoffset="${num(it.dashOffset, 4)}"`;
        }
        out.push(`<path ${a}/>`);
      }
    };
    const body = [];
    toSvg(items, body);
    let preview = '';
    if (bounds) {
      const b = bounds, vb = `${num(b.x0, 4)} ${num(b.y0, 4)} ${num(b.x1 - b.x0, 4)} ${num(b.y1 - b.y0, 4)}`;
      preview = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${vb}" preserveAspectRatio="none">` +
        `<defs>${defs.join('')}</defs>${body.join('')}</svg>`;
    }
    return {
      ops: pdf.join('\n'), bounds, painted: true, preview, notes: [...notes],
      gstates: [...gstates].map(([key, name]) => ({ name, ca: key.split(' ')[0], CA: key.split(' ')[1] })),
    };
  }

  // ── The file ──────────────────────────────────────────────────────────────

  function bytesOf(s) {
    const b = new Uint8Array(s.length);
    for (let i = 0; i < s.length; i++) b[i] = s.charCodeAt(i) & 0xff;
    return b;
  }

  /* zlib deflate where the browser has it; the stream goes uncompressed
     where not. */
  async function deflate(bytes) {
    if (typeof CompressionStream !== 'function') return null;
    try {
      const stream = new Blob([bytes]).stream().pipeThrough(new CompressionStream('deflate'));
      return new Uint8Array(await new Response(stream).arrayBuffer());
    } catch (e) {
      return null;
    }
  }

  function writer() {
    const objs = [];
    return {
      reserve() { objs.push(null); return objs.length; },
      set(id, ...parts) { objs[id - 1] = parts; },
      add(...parts) { objs.push(parts); return objs.length; },
      async stream(content, dict = '') {
        const raw = bytesOf(content);
        const z = raw.length > 200 ? await deflate(raw) : null;
        const body = z || raw;
        return this.add(`<< /Length ${body.length}${z ? ' /Filter /FlateDecode' : ''}${dict ? ' ' + dict : ''} >>\nstream\n`,
          body, '\nendstream');
      },
      /* The file's bytes, in pieces, with the cross-reference table. */
      finish(root, info) {
        const out = [];
        let pos = 0;
        const put = (p) => { const b = typeof p === 'string' ? bytesOf(p) : p; out.push(b); pos += b.length; };
        put('%PDF-1.7\n%\xe2\xe3\xcf\xd3\n');
        const offsets = objs.map((parts, i) => {
          const at = pos;
          put(`${i + 1} 0 obj\n`);
          parts.forEach(put);
          put('\nendobj\n');
          return at;
        });
        const xref = pos;
        let t = `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n`;
        for (const o of offsets) t += String(o).padStart(10, '0') + ' 00000 n \n';
        put(t + `trailer\n<< /Size ${objs.length + 1} /Root ${root} 0 R /Info ${info} 0 R >>\nstartxref\n${xref}\n%%EOF\n`);
        return out;
      },
    };
  }

  function rgb(hex) {
    const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex || '');
    return m ? m.slice(1).map(h => num(parseInt(h, 16) / 255)).join(' ') : '0 0 0';
  }

  /*
    The poster as a PDF Blob.

    opt: art (from parse) or d; color '#rrggbb'; name, for the title; and
    the layout's paper, orient, by and n.
  */
  async function build(opt) {
    const art = opt.art || parse(opt.d);
    const b = art.bounds;
    if (!b || !(b.x1 > b.x0 && b.y1 > b.y0)) throw new Error('There is no drawing to make a poster of.');
    const L = layout(art.bounds, opt);
    if (L.sheets > MAX_SHEETS) throw new Error(`That would take ${L.sheets} sheets; ${MAX_SHEETS} is as many as the poster makes.`);
    const name = String(opt.name || 'drawing');
    const w = writer();
    const catalog = w.reserve(), pages = w.reserve();
    const fonts = ['Helvetica /Encoding /WinAnsiEncoding', 'Helvetica-Bold /Encoding /WinAnsiEncoding', 'ZapfDingbats']
      .map(f => w.add(`<< /Type /Font /Subtype /Type1 /BaseFont /${f} >>`));
    // A traced drawing is one shape in one colour; an SVG brings its own paint.
    const pad = Math.max(b.x1 - b.x0, b.y1 - b.y0) * 0.01;
    const states = (art.gstates || []).map(s => `/${s.name} << /ca ${s.ca} /CA ${s.CA} >>`).join(' ');
    const form = await w.stream(art.painted ? `${art.ops}\n` : `${rgb(opt.color)} rg\n${art.ops}\nf\n`,
      `/Type /XObject /Subtype /Form /BBox [${num(b.x0 - pad, 4)} ${num(b.y0 - pad, 4)} ${num(b.x1 + pad, 4)} ${num(b.y1 + pad, 4)}] ` +
      `/Resources << ${states ? `/ExtGState << ${states} >>` : ''} >>`);
    const res = `/Resources << /Font << /F1 ${fonts[0]} 0 R /F2 ${fonts[1]} 0 R /F3 ${fonts[2]} 0 R >> /XObject << /Art ${form} 0 R >> >>`;
    const kids = [];
    const page = async (content) => {
      const c = await w.stream(content);
      kids.push(w.add(`<< /Type /Page /Parent ${pages} 0 R /MediaBox [0 0 ${num(L.pw * MM)} ${num(L.ph * MM)}] ${res} /Contents ${c} 0 R >>`));
    };
    await page(guidePage(L, name));
    for (let r = 0; r < L.rows; r++) for (let c = 0; c < L.cols; c++) await page(sheetPage(L, r, c));
    w.set(pages, `<< /Type /Pages /Kids [${kids.map(k => k + ' 0 R').join(' ')}] /Count ${kids.length} >>`);
    // Asking the print dialog for 100 % and one side, where it listens.
    w.set(catalog, `<< /Type /Catalog /Pages ${pages} 0 R /ViewerPreferences << /PrintScaling /None /Duplex /Simplex >> >>`);
    const info = w.add(`<< /Title ${infoStr(`${name} – poster, ${L.cols} × ${L.rows} sheets of ${L.paper}`)} ` +
      `/Producer (kvot ab) /Creator (kvotab.se/vectorize.html) >>`);
    return new Blob(w.finish(catalog, info), { type: 'application/pdf' });
  }

  const api = {
    MM, MARGIN, OVERLAP, BLEED, CUT_IN, BORDER, MAX_SHEETS, PAPERS,
    parse, arcCurves, fromSvg, layout, build, rowName, sheetName, textWidth, pdfStr,
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  return api;
})();
