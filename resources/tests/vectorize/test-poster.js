#!/usr/bin/env node
/* vectorize.html's poster PDF, in Node: resources/js/vectorize-poster.js,
   its layout of the sheets and the file it writes, with no page and no
   browser.

       node resources/tests/vectorize/test-poster.js

   Exit status 0 when every check passes. */
'use strict';

const path = require('path');
const zlib = require('zlib');
const P = require(path.join(__dirname, '../../js/vectorize-poster.js'));

let checks = 0;
const failures = [];
function check(label, ok, detail) {
  checks++;
  if (!ok) failures.push(label);
  console.log(`${ok ? 'ok  ' : 'FAIL'}  ${label}${detail === undefined ? '' : ': ' + detail}`);
}
const near = (a, b, eps = 1e-6) => Math.abs(a - b) <= eps;

// ── Reading the path ──────────────────────────────────────────────────────────
{
  const a = P.parse('M10 20C10 30 20 40 30 40C40 40 50 30 50 20Z M60 60C70 60 70 70 60 70Z');
  check('M, C and Z become m, c and h', a.ops.split('\n').map(l => l.split(' ').pop()).join('') === 'mcchmch', a.ops);
  check('the bounds take every point', a.bounds.x0 === 10 && a.bounds.y0 === 20 && a.bounds.x1 === 70 && a.bounds.y1 === 70,
    JSON.stringify(a.bounds));
  const b = P.parse('m10 10l5 0h5v5c0 1 1 2 2 2z');
  check('relative commands and L, H, V are read', b.ops === '10 10 m\n15 10 l\n20 10 l\n20 15 l\n20 16 21 17 22 17 c\nh', JSON.stringify(b.ops));
  check('an empty path has no bounds', P.parse('').bounds === null);
  for (const bad of ['M10 10 X 5', '10 10', 'M10 10Z 5 5', 'M10 10 A5 5 0 2 0 20 20']) {
    let threw = false;
    try { P.parse(bad); } catch (e) { threw = /could not be read/.test(e.message); }
    check(`malformed path data is refused: ${bad}`, threw);
  }
  check('no exponents reach the PDF', !/e/i.test(P.parse('M1e-9 2C1e-7 3 4 5 6 7Z').ops), P.parse('M1e-9 2C1e-7 3 4 5 6 7Z').ops);
}

// ── Curves and arcs ───────────────────────────────────────────────────────────

/* The path's cubic pieces, as [x0, y0, x1, y1, x2, y2, x3, y3]. */
function cubics(ops) {
  const out = [];
  let x = 0, y = 0;
  for (const line of ops.split('\n')) {
    const t = line.split(' '), op = t.pop(), v = t.map(Number);
    if (op === 'm' || op === 'l') { x = v[0]; y = v[1]; }
    if (op === 'c') { out.push([x, y, ...v]); x = v[4]; y = v[5]; }
  }
  return out;
}
const bez = (c, t) => {
  const u = 1 - t;
  return [u * u * u * c[0] + 3 * u * u * t * c[2] + 3 * u * t * t * c[4] + t * t * t * c[6],
    u * u * u * c[1] + 3 * u * u * t * c[3] + 3 * u * t * t * c[5] + t * t * t * c[7]];
};
{
  // A circle of radius 40 about (50, 50), as two half-turn arcs.
  const circle = cubics(P.parse('M90 50A40 40 0 0 1 10 50A40 40 0 0 1 90 50Z').ops);
  let worst = 0;
  for (const c of circle) for (let k = 0; k <= 20; k++) { const [px, py] = bez(c, k / 20); worst = Math.max(worst, Math.abs(Math.hypot(px - 50, py - 50) - 40)); }
  check('arcs become quarter-turn curves that keep to the circle', circle.length === 4 && worst < 0.04, `${circle.length} curves, ${worst.toFixed(4)} off`);
  const half = cubics(P.parse('M90 50A40 40 0 0 1 10 50').ops);
  check('a sweep of 1 goes the positive way (downwards first, y pointing down)', bez(half[0], 0.5)[1] > 50, String(bez(half[0], 0.5)));
  const big = cubics(P.parse('M50 10a40 40 0 1 1-0.01 0').ops);
  check('the large-arc flag takes the long way round', big.length === 4, String(big.length));
  const tight = cubics(P.parse('M0 0a5 5 0 1010 0').ops);
  check('arc flags written together, without spaces, are read', tight.length > 0 && tight[tight.length - 1][6] === 10 && tight[tight.length - 1][7] === 0);
  const small = cubics(P.parse('M0 0A1 1 0 0 1 100 0').ops);
  // Scaled to 50, about (50, 0): from the left end, sweeping the positive way, over the top.
  check('radii too small for the endpoints are scaled up to reach', Math.abs(small[small.length - 1][6] - 100) < 1e-9 &&
    Math.abs(bez(small[0], 1)[0] - 50) < 1e-3 && Math.abs(bez(small[0], 1)[1] + 50) < 1e-3, String(bez(small[0], 1)));
  check('an arc of radius 0 is a line', P.parse('M0 0A0 5 0 0 1 10 10').ops === '0 0 m\n10 10 l');

  const q = cubics(P.parse('M0 0Q10 20 20 0T40 0').ops);
  check('Q is the same curve as a cubic, and T mirrors its control point',
    q.length === 2 && near(q[0][2], 20 / 3, 1e-3) && near(q[0][3], 40 / 3, 1e-3) && near(q[1][2], 20 + 20 / 3, 1e-3) && near(q[1][3], -40 / 3, 1e-3),
    JSON.stringify(q.map(c => c.slice(2, 6).map(v => +v.toFixed(3)))));
  const sm = cubics(P.parse('M0 0C0 10 10 10 10 0S20 -10 20 0').ops);
  check('S mirrors the last control point', near(sm[1][2], 10) && near(sm[1][3], -10), JSON.stringify(sm[1]));
  const rel = P.parse('m10 10 10 0 0 10z m5 5 h5').ops;
  check('implicit lines after m, and m after z from where the subpath began', rel === '10 10 m\n20 10 l\n20 20 l\nh\n15 15 m\n20 15 l', JSON.stringify(rel));
  const t = P.parse('M0 0L10 0', { a: 2, b: 0, c: 0, d: 3, e: 1, f: 1 }, true);
  check('a matrix moves the coordinates, and the bounds with them', t.ops === '1 1 m\n21 1 l' && t.bounds.x1 === 21 && t.bounds.y1 === 1, JSON.stringify(t));
}

// ── Names and text ────────────────────────────────────────────────────────────
{
  const names = [0, 25, 26, 27, 701, 702].map(P.rowName).join(' ');
  check('rows are lettered A-Z, then AA', names === 'A Z AA AB ZZ AAA', names);
  check('sheet names', P.sheetName(1, 2) === 'B3');
  check('Helvetica widths', near(P.textWidth('A', false, 1000), 667) && near(P.textWidth('m', true, 1000), 889) &&
    near(P.textWidth('–×', false, 1000), 556 + 584));
  check('strings escape what PDF reserves, and go as WinAnsi',
    P.pdfStr('a(b)\\ × –') === '(a\\(b\\)\\\\ \\327 \\226)', P.pdfStr('a(b)\\ × –'));
}

// ── The layout ────────────────────────────────────────────────────────────────
const art = P.parse('M0 0C0 0 1000 0 1000 0C1000 0 1000 1250 1000 1250C1000 1250 0 1250 0 1250Z');
{
  const L = P.layout(art.bounds, { paper: 'a4', orient: 'portrait', by: 'across', n: 6 });
  check('A4 upright: 190 x 277 mm printed, sheets 180 and 267 mm apart',
    L.iw === 190 && L.ih === 277 && L.sx === 180 && L.sy === 267, `${L.iw} ${L.ih} ${L.sx} ${L.sy}`);
  // Every sheet loses its left and top margins, so the finished poster runs
  // from CUT_IN before the printed area to the last sheets' paper edges.
  const extra = P.CUT_IN + P.MARGIN;
  check('6 across prints 1090 mm, and the finished poster is 1100.15 mm wide',
    L.cols === 6 && L.W === 1090 && near(L.FW, 1090 + extra) && near(L.fx0, -P.CUT_IN), `${L.W} ${L.FW}`);
  // 1076.15 mm wide, so 1345.2 mm tall: 1369.2 with the borders, more than five rows' 1355.15.
  check('and as tall as the drawing needs', L.rows === 6 && L.H === 5 * 267 + 277 && near(L.FH, L.H + extra), `${L.rows} ${L.H}`);
  check('the white round the drawing is the same left and right', near(L.ox - L.fx0, P.BORDER) && near(L.fx0 + L.FW - L.ox - L.dw, P.BORDER));
  check('and top and bottom, at least as wide', near(L.oy - L.fy0, L.fy0 + L.FH - L.oy - L.dh) && L.oy - L.fy0 >= P.BORDER - 1e-9);
  // Enough sheets the other way, never one more; the drawing inside the printed area.
  const shapes = [[1000, 1250], [1000, 300], [300, 1000], [1000, 1000], [1000, 1 + 1e-6]];
  const bad = [], outside = [];
  for (const [w, h] of shapes) {
    for (const by of ['across', 'down']) {
      for (const orient of ['portrait', 'landscape']) {
        for (let n = 1; n <= 12; n++) {
          const T = P.layout({ x0: 0, y0: 0, x1: w, y1: h }, { paper: 'a4', orient, by, n });
          const [k, step, first, len] = by === 'across' ? [T.rows, T.sy, T.ih, T.dh] : [T.cols, T.sx, T.iw, T.dw];
          const full = (k - 1) * step + first + extra, less = (k - 2) * step + first + extra;
          if (full < len + 2 * P.BORDER - 1e-9 || (k > 1 && less >= len + 2 * P.BORDER - 1e-9)) bad.push(`${w}x${h} ${by} ${orient} ${n}`);
          if (T.ox < -1e-9 || T.oy < -1e-9 || T.ox + T.dw > T.W + 1e-9 || T.oy + T.dh > T.H + 1e-9) outside.push(`${w}x${h} ${by} ${orient} ${n}`);
        }
      }
    }
  }
  check('as many sheets the other way as the drawing needs, and no more', !bad.length, bad.join(', '));
  check('the drawing always lies inside the printed area', !outside.length, outside.join(', '));

  const D = P.layout(art.bounds, { paper: 'a4', orient: 'landscape', by: 'down', n: 3 });
  check('sideways sheets swap the sides', D.pw === 297 && D.ph === 210 && D.sx === 267 && D.sy === 180);
  check('3 down fills the finished height less the border',
    D.rows === 3 && near(D.dh, 2 * 180 + 190 + extra - 2 * P.BORDER) && D.dw <= D.FW - 2 * P.BORDER + 1e-9);

  const Lt = P.layout(art.bounds, { paper: 'letter', orient: 'portrait', by: 'across', n: 2 });
  check('Letter is 215.9 x 279.4 mm', near(Lt.pw, 215.9) && near(Lt.ph, 279.4) && near(Lt.W, 2 * (215.9 - 20) - 10), String(Lt.W));
  const S = P.layout(art.bounds, { by: 'across', n: 1 });
  check('one sheet across can be one sheet in all, A4 upright by default', S.sheets === 1 && S.pw === 210, `${S.sheets} ${S.pw}`);
  check('a single sheet is not cut: the drawing is centred on the page',
    S.FW === 210 && S.FH === 297 && near(S.ox + P.MARGIN, 210 - P.MARGIN - S.ox - S.dw) && near(S.oy + P.MARGIN, 297 - P.MARGIN - S.oy - S.dh));
}

// ── The file ──────────────────────────────────────────────────────────────────

/* The PDF's objects by number, checked against the cross-reference table, and
   each stream's content, inflated. */
function readPdf(buf) {
  const s = buf.toString('latin1');
  const start = +/startxref\n(\d+)\n%%EOF\n$/.exec(s)[1];
  const xr = /^xref\n0 (\d+)\n0000000000 65535 f \n([\s\S]*?)trailer\n<<([^]*?)>>\n/.exec(s.slice(start));
  if (!xr) throw new Error('no cross-reference table at startxref');
  const objs = {};
  let badOffsets = 0;
  xr[2].trim().split('\n').forEach((row, i) => {
    const at = +row.slice(0, 10), head = `${i + 1} 0 obj\n`;
    if (s.slice(at, at + head.length) !== head) { badOffsets++; return; }
    const end = s.indexOf('\nendobj\n', at);
    const body = s.slice(at + head.length, end);
    const m = /^<< \/Length (\d+)( \/Filter \/FlateDecode)?([^\n]*)>>\nstream\n/.exec(body);
    if (m) {
      const from = at + head.length + m[0].length, len = +m[1];
      const raw = buf.subarray(from, from + len);
      objs[i + 1] = { dict: m[0], stream: (m[2] ? zlib.inflateSync(raw) : raw).toString('latin1'), lengthOk: s.slice(from + len, from + len + 10) === '\nendstream' };
    } else {
      objs[i + 1] = { dict: body };
    }
  });
  return { s, objs, count: +xr[1] - 1, trailer: xr[3], badOffsets };
}

(async () => {
  const opt = { art, color: '#336699', name: 'test å drawing', paper: 'a4', orient: 'portrait', by: 'across', n: 3 };
  const L = P.layout(art.bounds, opt);
  const blob = await P.build(opt);
  const buf = Buffer.from(await blob.arrayBuffer());
  const pdf = readPdf(buf);
  check('the cross-reference table points at every object', pdf.badOffsets === 0 && Object.keys(pdf.objs).length === pdf.count, `${pdf.badOffsets} wrong`);
  const streams = Object.values(pdf.objs).filter(o => o.stream !== undefined);
  check('every stream is as long as it says', streams.every(o => o.lengthOk));
  check('the streams are compressed', streams.filter(o => /FlateDecode/.test(o.dict)).length >= L.sheets);
  const pages = Object.values(pdf.objs).filter(o => /\/Type \/Page /.test(o.dict));
  check('a first page and one page a sheet', pages.length === L.sheets + 1 && new RegExp(`/Count ${L.sheets + 1} `).test(pdf.s), `${pages.length} pages for ${L.sheets} sheets`);
  check('every page is A4', pages.every(p => /\/MediaBox \[0 0 595.276 841.89\]/.test(p.dict)));
  check('the print dialog is asked for 100 % and one side', /\/PrintScaling \/None \/Duplex \/Simplex/.test(pdf.s));
  check('the title is UTF-16, as information strings are not WinAnsi', /\/Title <FEFF0074006500730074002000E5/.test(pdf.s));

  const form = streams.find(o => /\/Subtype \/Form/.test(o.dict));
  check('the drawing goes in once, in its colour', streams.filter(o => /\/Subtype \/Form/.test(o.dict)).length === 1 &&
    /^0\.2 0\.4 0\.6 rg\n/.test(form.stream) && /\nf\n$/.test(form.stream));
  // The pages' contents, in page order.
  const contents = pages.map(p => pdf.objs[+/\/Contents (\d+) 0 R/.exec(p.dict)[1]].stream);
  check('the first page explains, with the 10 cm bar', /\(Poster: \d+ sheets of A4\) Tj/.test(contents[0]) && /\(10 cm\) Tj/.test(contents[0]));
  check('every sheet draws the drawing through a clip', contents.slice(1).every(c => /re W n [^\n]* cm \/Art Do Q/.test(c)));
  const b2 = contents[1 + L.cols + 1];
  check('B2 is named, cut on two sides, and glued on two', /\(B2\) Tj/.test(b2) && /cut off the left and top margins/.test(b2) &&
    /\(  \\267  sheet B3 goes on top/.test(b2) && /sheet C2 goes on top/.test(b2.replace(/\\267/g, '')));
  const a1 = contents[1];
  check('A1 is cut on both sides too, so its name goes with its margin',
    /cut off the left and top margins/.test(a1) && (a1.match(/\/F3 11 Tf \("\) Tj/g) || []).length === 2);
  check('and is named on its glue strips, which stay until the next sheet covers them',
    /\(A1\) Tj [^\n]*\(GLUE HERE\) Tj[^\n]*sheet A2 goes on top/.test(a1) && /\(A1\) Tj [^\n]*\(GLUE HERE\) Tj[^\n]*sheet B1 goes on top/.test(a1));
  const last = contents[contents.length - 1];
  check('the last sheet has no glue strip', !/GLUE HERE/.test(last));

  // The scissors lie wholly in the margins cut off: left of the vertical
  // line, above the horizontal one.
  const tms = [...a1.matchAll(/([-\d. ]+) Tm \/F3 11 Tf/g)].map(m => m[1].trim().split(' ').map(Number));
  const lineAt = (P.MARGIN - P.CUT_IN) * P.MM, em = 11;
  const vert = tms.find(t => t[1] === -1), horiz = tms.find(t => t[0] === 1);
  check('the scissors on the vertical cut are left of the line', vert && vert[4] + 0.655 * em < lineAt, vert && `${vert[4] + 0.655 * em} < ${lineAt}`);
  check('and those on the horizontal cut above it', horiz && horiz[5] + 0.035 * em > 841.89 - lineAt, horiz && `${horiz[5] + 0.035 * em} > ${841.89 - lineAt}`);

  const one = await P.build({ art, by: 'across', n: 1, paper: 'a4', orient: 'portrait' });
  const onePdf = readPdf(Buffer.from(await one.arrayBuffer()));
  const onePages = Object.values(onePdf.objs).filter(o => /\/Type \/Page /.test(o.dict));
  const sheet = onePdf.objs[+/\/Contents (\d+) 0 R/.exec(onePages[1].dict)[1]].stream;
  check('a single sheet has no cut lines, glue or labels', onePages.length === 2 && !/ d |Tj|GLUE/.test(sheet) && /\/Art Do/.test(sheet), sheet);

  // An SVG's own drawing brings its paint, and the states its opacities need.
  const painted = { ops: '0.2 0.4 0.6 rg\n/A0 gs\n0 0 m\n10 0 l\n10 10 l\nh\nf', bounds: { x0: 0, y0: 0, x1: 10, y1: 10 }, painted: true,
    gstates: [{ name: 'A0', ca: '0.5', CA: '1' }] };
  const pb = readPdf(Buffer.from(await (await P.build({ art: painted, by: 'across', n: 2 })).arrayBuffer()));
  const pform = Object.values(pb.objs).find(o => /\/Subtype \/Form/.test(o.dict || ''));
  check('a painted drawing goes in as it is, with its graphics states', pform.stream === painted.ops + '\n' &&
    /\/ExtGState << \/A0 << \/ca 0\.5 \/CA 1 >> >>/.test(pform.dict), pform.dict);

  // Where sheet (r, c) puts the drawing: its top left at MARGIN + ox - c*sx, MARGIN + oy - r*sy.
  const MM = P.MM;
  const cmOf = (c) => /re W n ([-\d. ]+) cm \/Art Do/.exec(c)[1].split(' ').map(Number);
  const [a, , , dd, e, f] = cmOf(contents[1 + L.cols + 1]);
  check('the drawing is at the poster\'s scale on every sheet', near(a, MM * L.s, 1e-5) && near(dd, -MM * L.s, 1e-5));
  check('B2 shows the drawing one step left and one step up',
    near(e, MM * (P.MARGIN + L.ox - L.sx), 1e-3) && near(f, MM * (L.ph - P.MARGIN - L.oy + L.sy), 1e-3), `${e} ${f}`);

  let threw = '';
  try { await P.build({ art, by: 'across', n: 30, paper: 'a4', orient: 'portrait' }); } catch (err) { threw = err.message; }
  check('a poster of too many sheets is refused', /sheets/.test(threw), threw);

  console.log(`\n${checks - failures.length} of ${checks} checks pass`);
  process.exit(failures.length ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
