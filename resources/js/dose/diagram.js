/*
  A drawing of a compartment model, as SVG built from DOM nodes (no markup
  strings). With the ICRP's figure of the model (figures.js), the boxes stand
  where the figure has them; without one, the layout follows the way the ICRP
  draws its systemic models: soft tissues on the left, blood in the middle,
  bone and marrow on the right, the contents of the alimentary tract and the
  bladder and the ways out of the body along the bottom. Each arrow carries
  the transfer coefficient at the chosen age in its tooltip.

    drawModel({ compartments: [{name, region, parts?, badge?}], transfers: [{from, to, rate, model?}],
                entries: [{name, tip, arrows: [{label, tip}]}], figure? })
      -> SVGSVGElement

  A transfer with a `model` ('alimentary' or 'bladder') belongs to the
  alimentary tract or bladder model around the systemic one, and is dashed.
  `entries` are the boxes activity comes into from outside the drawing: tip
  joins the box's tooltip, and each of arrows comes in from a name of where
  the activity comes from (as the ICRP draws "Inhaled" and "Ingested"). They
  light like transfers (data-t), in a group of their own (.entry-g) that the
  transfer table has no row for.

  `figure` ({boxes: {name: [x, y, w, h]}, in?: {name: side}}) places each
  box it names x·UX from the left and y rows down, w·UX wide and h rows high
  (less the gap between rows; a name may list its other spellings, a|b).
  Boxes it does not name go in a column on its right, the gut's contents and
  the ways out in a row below. Its arrows run straight across where two boxes
  face each other, as short arrows into and out of a box drawn inside
  another, and otherwise at right angles round the boxes between; an arrow in
  comes from the side `in` names, else from a side with room.

  parts (ids of body.js) go on the box as data-part, and badge, the number
  of its part in the drawing of the body, in its corner. Each arrow is a
  <g data-t="from→to"> (transferKey), and each box lists the compartments it
  holds in data-names (a|b), so the page can light an arrow, its row of the
  transfer table and the boxes at its ends together.

  fillBoxes(svg, levelOf) fills the boxes as buckets, each to its share of
  the activity in the body (the Model tab after a calculation).
*/
import { badge } from './body.js';

const NS = 'http://www.w3.org/2000/svg';
const el = (tag, attrs = {}, ...kids) => {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v != null) e.setAttribute(k, String(v));
  for (const k of kids) if (k != null) e.append(k);
  return e;
};

/** The key of a transfer, on its arrow and on its row of the transfer table. */
export const transferKey = (from, to) => `${from}→${to}`;

const norm = (r) => String(r || '').replace(/_/g, '-').toLowerCase();
export function laneOf(region, name = '') {
  const r = norm(region);
  if (['urine', 'faeces', 'feces', 'excreta', 'exhaled', 'env'].includes(r)) return 'sink';
  if (r === 'blood') return 'blood';
  if (/bone|marrow/.test(r)) return 'bone';
  if (/cont$|^o-cavity$|^oesophag-[fs]$/.test(r)) return 'content';
  if (/^(urine|faeces|feces|excreta)$/i.test(name)) return 'sink';
  return 'tissue';
}

const W = 156, H = 34, GAP = 12, COLGAP = 92;
const BAND = 36;     // room above the columns for the names of arrows coming in
const CHAR_W = 6.6;  // about the width of a character of those names (11px Verdana italic)
// A figure's grid: x and w in UX, y and h in rows; a way out is a line of text.
const UX = 26, ROW = H + GAP, SINK_H = 18, IN_LEN = 24;
const CONTENT_ORDER = ['o-cavity', 'oesophag-f', 'oesophag-s', 'st-cont', 'si-cont', 'gb-cont', 'rc-cont', 'uli-cont', 'lc-cont', 'lli-cont', 'rs-cont', 'ub-cont'];

export function fmtRate(r) {
  if (!(r > 0)) return '0';
  return r >= 0.01 && r < 1e5 ? String(+r.toPrecision(3)) : r.toExponential(2).replace('e', 'E');
}
function halfTime(r) {
  if (!(r > 0)) return '';
  const t = Math.LN2 / r;
  if (t < 1 / 24) return `${+(t * 1440).toPrecision(2)} min`;
  if (t < 1) return `${+(t * 24).toPrecision(2)} h`;
  if (t < 365.25) return `${+t.toPrecision(2)} d`;
  return `${+(t / 365.25).toPrecision(2)} y`;
}

/* The bottom row: the gut's contents down to faeces, then the bladder's to
   urine, then the other ways out; so that each flows to its neighbour. */
function bottomRow(list) {
  const isUB = (n) => norm(n.region) === 'ub-cont';
  const sinkIs = (n, re) => re.test(n.name);
  const content = list.filter((n) => n.lane === 'content').sort((a, b) => CONTENT_ORDER.indexOf(norm(a.region)) - CONTENT_ORDER.indexOf(norm(b.region)));
  const sinks = list.filter((n) => n.lane === 'sink');
  return [
    ...content.filter((n) => !isUB(n)), ...sinks.filter((n) => sinkIs(n, /^(faeces|feces)$/i)),
    ...content.filter(isUB), ...sinks.filter((n) => sinkIs(n, /^urine$/i)),
    ...sinks.filter((n) => !sinkIs(n, /^(faeces|feces|urine)$/i)),
  ];
}

/**
 * @param {object} m  {compartments: [{name, region, label?}], transfers: [{from, to, rate}], entries: [{name, tip, arrows}], figure?}
 */
export function drawModel(m) {
  // Compartments of the same alimentary or bladder contents are one box
  // (a model may name the stomach contents twice).
  const nodes = [];
  const byName = new Map();
  const contentBy = new Map();
  for (const c of m.compartments) {
    const lane = laneOf(c.region, c.name);
    if (lane === 'content') {
      const k = norm(c.region);
      if (contentBy.has(k)) { byName.set(c.name, contentBy.get(k)); continue; }
      const n = { ...c, lane };
      contentBy.set(k, n);
      nodes.push(n); byName.set(c.name, n);
      continue;
    }
    const n = { ...c, lane };
    nodes.push(n); byName.set(c.name, n);
  }
  // Sinks named only as destinations.
  for (const t of m.transfers) if (!byName.has(t.to)) { const n = { name: t.to, region: t.to, lane: 'sink' }; nodes.push(n); byName.set(t.to, n); }
  const namesOf = (n) => [...byName].filter(([, x]) => x === n).map(([k]) => k);
  // The arrows in from outside the drawing, by the box they come into.
  const tipOf = new Map((m.entries || []).map((e) => [e.name, e.tip]));
  const comeIn = new Map();
  for (const e of m.entries || []) {
    const n = byName.get(e.name);
    if (!n || n.lane === 'sink') continue;
    for (const a of e.arrows || []) {
      const list = comeIn.get(n) || [];
      if (!list.some((x) => x.label === a.label)) list.push({ ...a, name: e.name });
      comeIn.set(n, list);
    }
  }
  const at = m.figure ? figurePlaces(nodes, namesOf, m.figure, comeIn) : autoPlaces(nodes, comeIn, tipOf);
  let { width, height } = at;

  const svg = el('svg', { width, height, viewBox: `0 0 ${width} ${height}`, role: 'img', 'aria-label': 'Compartment model' });
  const defs = el('defs');
  for (const [id, cls] of [['dcArrow', 'arrow'], ['dcArrowOut', 'arrow out'], ['dcArrowLit', 'arrow lit'], ['dcArrowIn', 'arrow in']]) {
    defs.append(el('marker', { id, viewBox: '0 0 10 10', refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: 'auto-start-reverse' },
      el('path', { d: 'M0,0 L10,5 L0,10 z', class: cls })));
  }
  svg.append(defs);
  for (const l of at.laneLabels) svg.append(el('text', { x: l.x, y: l.y ?? 14, class: 'lane' }, document.createTextNode(l.text)));
  for (const f of at.groups || []) {
    svg.append(el('g', { class: 'group' }, el('rect', { x: f.x0, y: f.y0, width: f.x1 - f.x0, height: f.y1 - f.y0, rx: 6 }),
      el('text', { x: f.x0 + 7, y: f.y0 + 13, class: 'lane' }, document.createTextNode(f.name))));
  }

  // Edges under the nodes; those into and out of a box drawn inside another over them.
  const g = el('g'), over = el('g');
  const pairCount = new Map();
  m.transfers.forEach((t, i) => {
    const a = byName.get(t.from), b = byName.get(t.to);
    if (!a || !b || a === b) return;
    const key = [a.name, b.name].sort().join('|');
    const k = pairCount.get(key) || 0;
    pairCount.set(key, k + 1);
    const off = (k % 2 ? 1 : -1) * 4; // two arrows between the same pair stay apart
    const route = m.figure ? figureRoute(a, b, off, nodes, i) : autoRoute(a, b, off, at.bottom);
    height = Math.max(height, route.bottom || 0);
    const out = a.lane === 'blood' && b.lane !== 'blood';
    const tract = t.model ? ' tract' : '';
    const whose = t.model ? ` — the ${t.model === 'bladder' ? 'urinary bladder' : 'alimentary tract'} model` : '';
    // A wide transparent copy under the line, so that the pointer finds it.
    (route.over || a.inside || b.inside ? over : g).append(el('g', { class: `edge-g${out ? ' out' : ''}${tract}`, 'data-t': transferKey(t.from, t.to),
      'data-tip': `${t.from} → ${t.to}: ${fmtRate(t.rate)} d⁻¹${t.rate > 0 ? ` (half-time ${halfTime(t.rate)} if it were the only way out)` : ''}${whose}` },
      el('path', { d: route.d, class: 'hit' }),
      el('path', { d: route.d, class: `edge${out ? ' out' : ''}${tract}`, 'marker-end': `url(#${out ? 'dcArrowOut' : 'dcArrow'})` })));
  });
  svg.append(g);
  // The arrows in from outside, each from the name of where its activity comes from.
  const ins = el('g');
  for (const a of at.ins) {
    ins.append(el('g', { class: 'entry-g', 'data-t': transferKey(a.label, a.name), 'data-tip': a.tip },
      el('path', { d: a.d, class: 'hit' }),
      el('path', { d: a.d, class: 'edge entry', 'marker-end': 'url(#dcArrow)' }),
      a.text ? el('text', { x: a.text.x, y: a.text.y, class: 'source', 'text-anchor': a.text.anchor || null }, document.createTextNode(a.label)) : null));
  }
  svg.append(ins);
  // How many drawn transfers come into each box and go out of it, for its tooltip.
  const flows = new Map(nodes.map((n) => [n, [0, 0]]));
  for (const t of m.transfers) {
    const a = byName.get(t.from), b = byName.get(t.to);
    if (!a || !b || a === b) continue;
    flows.get(b)[0]++;
    flows.get(a)[1]++;
  }
  svg.setAttribute('height', height);
  svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
  // Boxes drawn inside another come after it.
  const order = nodes.map((n, i) => [n, i]).sort(([a], [b]) => (a.inside ? 1 : 0) - (b.inside ? 1 : 0));
  for (const [n, i] of order) {
    const w = n.w || W, h = n.h || H;
    const label = n.label || n.name;
    const room = n.fit ? Math.floor((w - (n.badge ? 30 : 12)) / 6.6) : (n.badge ? 19 : 22); // a figure's box by its width
    const short = label.length > room ? `${label.slice(0, room - 1)}…` : label;
    const names = namesOf(n);
    const [nin, nout] = flows.get(n);
    const counts = nin || nout ? `. ${nin} ${nin === 1 ? 'transfer' : 'transfers'} in (blue), ${nout} out (red)` : '';
    const entry = names.filter((k) => tipOf.has(k)).map((k) => tipOf.get(k)).join('; ');
    const grp = el('g', { class: `node ${n.lane}`, transform: `translate(${n.x},${n.y})`, 'data-part': n.parts?.length ? n.parts.join(' ') : null, 'data-names': names.join('|'),
      'data-region': n.region || null,
      'data-tip': `${label}${n.region && n.region !== label ? ` — source region ${n.region}` : ''}${entry ? ` — ${entry}` : ''}${counts}` },
      el('rect', { width: w, height: h, rx: 6 }));
    if (n.lane !== 'sink') {
      // The bucket's level, empty until fillBoxes() fills it, inside the box's rounded corners.
      defs.append(el('clipPath', { id: `dcClip${i}` }, el('rect', { width: w, height: h, rx: 6 })));
      grp.append(el('path', { class: 'level', d: '', 'clip-path': `url(#dcClip${i})` }));
    }
    // A tall box has its name in the middle, as the ICRP's figures have blood, unless boxes are drawn inside it.
    const holds = h > H + 8 && nodes.some((o) => o.inside && contains(n, o));
    const y1 = n.lane === 'sink' ? (h < H ? 13 : 21) : h > H + 8 && !holds ? Math.round(h / 2) - 2 : 15;
    grp.append(el('text', { x: 8, y: y1 }, document.createTextNode(short)));
    if (n.lane !== 'sink' && n.region && n.region !== label) grp.append(el('text', { x: 8, y: y1 + 13, class: 'region rcode' }, document.createTextNode(n.region)));
    if (n.lane !== 'sink') grp.append(el('text', { x: 8, y: y1 + 13, class: 'share' }));
    if (n.badge) {
      const b = el('g', { class: 'badge', transform: `translate(${w - 11 - (String(n.badge).length - 1) * 2.5},${h - 10})` });
      b.append(badge(n.badge));
      grp.append(b);
    }
    svg.append(grp);
  }
  svg.append(over);
  return svg;
}

/* Without a figure: columns of tissues, blood and bone, the bottom row, and
   the arrows in from above the columns or from below the bottom row. */
function autoPlaces(nodes, comeIn, tipOf) {
  const lanes = { tissue: [], blood: [], bone: [], content: [], sink: [] };
  for (const n of nodes) lanes[n.lane].push(n);
  // A box an arrow comes into first in its column, then blood that activity
  // enters otherwise; bone surfaces before volumes.
  const inFirst = (a, b) => comeIn.has(b) - comeIn.has(a);
  lanes.tissue.sort(inFirst);
  lanes.blood.sort((a, b) => inFirst(a, b) || tipOf.has(b.name) - tipOf.has(a.name));
  const boneOrder = (n) => (/-s$/.test(norm(n.region)) ? 0 : /-v$/.test(norm(n.region)) ? 1 : 2);
  lanes.bone.sort((a, b) => inFirst(a, b) || boneOrder(a) - boneOrder(b));

  // Columns: tissues (on both sides of blood when there are many), blood, bone.
  const split = (list, max) => (list.length > max ? [list.slice(0, Math.ceil(list.length / 2)), list.slice(Math.ceil(list.length / 2))] : [list]);
  const tissueCols = split(lanes.tissue, 8);
  const boneCols = split(lanes.bone, 7);
  const columns = (tissueCols.length > 1
    ? [tissueCols[0], lanes.blood, tissueCols[1], ...boneCols]
    : [...tissueCols, lanes.blood, ...boneCols]).filter((c) => c.length);
  const tallest = Math.max(1, ...columns.map((c) => c.length));
  const colHeight = tallest * (H + GAP);
  const top = 26 + ([...comeIn.keys()].some((n) => n.lane !== 'content') ? BAND : 0);
  let x = 16;
  const laneLabels = [];
  columns.forEach((col) => {
    const y0 = top + (colHeight - col.length * (H + GAP)) / 2;
    col.forEach((n, i) => { n.x = x; n.y = y0 + i * (H + GAP); });
    const lane = col[0].lane;
    if (!laneLabels.some((l) => l.lane === lane)) laneLabels.push({ lane, x, text: { tissue: 'Tissues', blood: 'Blood', bone: 'Bone and marrow' }[lane] });
    x += W + COLGAP;
  });
  // Room on the right for the arcs between boxes of the last column.
  const width = Math.max(x - COLGAP + 76, 16 + (lanes.content.length + lanes.sink.length) * (W * 0.8 + 14));
  const bottom = bottomRow([...lanes.content, ...lanes.sink]);
  const rowY = top + colHeight + 40;
  const bw = Math.min(W, (width - 32 - (bottom.length - 1) * 14) / Math.max(1, bottom.length));
  bottom.forEach((n, i) => { n.x = 16 + i * (bw + 14); n.y = rowY; n.w = bw; });
  if (bottom.length) laneLabels.push({ lane: 'bottom', x: 16, y: rowY - 8, text: 'Alimentary tract, bladder and excretion' });
  let height = (bottom.length ? rowY + H : top + colHeight) + 18;
  // The arrows in: into a box of the columns from the band above them,
  // straight down into the first box of its column, else round the column's
  // right side into the box's; names that share a column side by side, each
  // once. Into a box of the bottom row from below it.
  const ins = [];
  for (const col of columns) {
    const nameX = new Map(); // a name -> the x of its text
    let lx = col[0].x + 4;
    for (const n of col.filter((c) => comeIn.has(c))) {
      const w = n.w || W;
      for (const a of comeIn.get(n)) {
        const first = !nameX.has(a.label);
        if (first) { nameX.set(a.label, lx); lx += a.label.length * CHAR_W + 14; }
        const sx = nameX.get(a.label) + 8, sy = top - BAND + 17;
        const d = n === col[0] && sx < n.x + w - 8
          ? `M${sx},${sy} L${sx},${n.y}`
          : `M${sx},${sy} C${n.x + w + 26},${sy} ${n.x + w + 26},${n.y + H / 2} ${n.x + w},${n.y + H / 2}`;
        ins.push({ ...a, d, text: first ? { x: nameX.get(a.label), y: top - BAND + 12 } : null });
      }
    }
  }
  for (const n of bottom.filter((c) => comeIn.has(c))) {
    let lx = n.x + 4;
    for (const a of comeIn.get(n)) {
      const sx = lx + 8, ly = n.y + H + 28;
      ins.push({ ...a, d: `M${sx},${ly - 11} L${sx},${n.y + H}`, text: { x: lx, y: ly } });
      lx += a.label.length * CHAR_W + 14;
      height = Math.max(height, ly + 8);
    }
  }
  return { width, height, laneLabels, bottom, ins };
}

function autoRoute(a, b, off, bottom) {
  const wa = a.w || W, wb = b.w || W;
  const ca = { x: a.x + wa / 2, y: a.y + H / 2 }, cb = { x: b.x + wb / 2, y: b.y + H / 2 };
  const anchor = (n, w, c, o) => {
    const dx = o.x - c.x, dy = o.y - c.y;
    if (Math.abs(dx) * H > Math.abs(dy) * w) return { x: dx > 0 ? n.x + w : n.x, y: c.y, side: 'h' };
    return { x: c.x, y: dy > 0 ? n.y + H : n.y, side: 'v' };
  };
  const p = anchor(a, wa, ca, cb), q = anchor(b, wb, cb, ca);
  if (p.side === 'h') p.y += off; else p.x += off;
  if (q.side === 'h') q.y += off; else q.x += off;
  const ia = bottom.indexOf(a), ib = bottom.indexOf(b);
  if (ia >= 0 && ib >= 0 && Math.abs(ia - ib) > 1) { // along the bottom row past others: an arc under it
    const ax = a.x + wa / 2 + off, bx = b.x + wb / 2 + off, y = a.y + H;
    const dip = 16 + Math.abs(ax - bx) * 0.06;
    return { d: `M${ax},${y} C${ax},${y + dip} ${bx},${y + dip} ${bx},${y}`, bottom: y + dip * 0.75 + 12 };
  }
  if (Math.abs(a.x - b.x) < 1) { // same column: an arc out to the side
    const bulge = 28 + Math.abs(a.y - b.y) * 0.12;
    const sx = a.x + wa;
    return { d: `M${sx},${a.y + H / 2 + off} C${sx + bulge},${a.y + H / 2 + off} ${sx + bulge},${b.y + H / 2 + off} ${sx},${b.y + H / 2 + off}` };
  }
  const mx = (p.x + q.x) / 2, my = (p.y + q.y) / 2;
  return { d: p.side === 'h' && q.side === 'h' ? `M${p.x},${p.y} C${mx},${p.y} ${mx},${q.y} ${q.x},${q.y}` : `M${p.x},${p.y} Q${mx + off * 3},${my} ${q.x},${q.y}` };
}

/* With a figure: its boxes where it has them, the rest beside and below,
   and the arrows in from the side it names, else from one with room; then
   all of it moved in from the edges. */
function figurePlaces(nodes, namesOf, figure, comeIn) {
  const spot = new Map();
  for (const [names, p] of Object.entries(figure.boxes)) for (const k of names.split('|')) spot.set(k, p);
  const placed = [], rest = [];
  for (const n of nodes) {
    const p = namesOf(n).map((k) => spot.get(k)).find(Boolean);
    if (!p) { rest.push(n); continue; }
    const [x, y, w = 6, h = 1] = p;
    const sink = n.lane === 'sink';
    Object.assign(n, { x: x * UX, y: y * ROW, w: sink ? (n.label || n.name).length * CHAR_W + 14 : w * UX, h: sink ? SINK_H : h * ROW - GAP, fit: true });
    // Two boxes given one place (a figure's name and its other spelling both in a model) side by side.
    while (placed.some((o) => o.x === n.x && o.y === n.y)) n.x += n.w + UX;
    placed.push(n);
  }
  for (const n of placed) n.inside = placed.some((o) => o !== n && contains(o, n));
  // What the figure lacks: boxes of the columns in rows of six below it, then
  // the gut's contents and the ways out in a row of their own.
  const side = rest.filter((n) => n.lane !== 'content' && n.lane !== 'sink');
  const low = Math.max(0, ...placed.map((n) => n.y + n.h)) + ROW;
  side.forEach((n, i) => Object.assign(n, { x: (i % 6) * (W + 2 * UX), y: low + Math.floor(i / 6) * (ROW + GAP), w: W, h: H }));
  const lower = low + Math.ceil(side.length / 6) * (ROW + GAP);
  bottomRow(rest).forEach((n, i) => Object.assign(n, { x: i * (W * 0.8 + 14), y: lower, w: n.lane === 'sink' ? (n.label || n.name).length * CHAR_W + 14 : W * 0.8, h: n.lane === 'sink' ? SINK_H : H }));
  // The arrows in.
  const ins = [];
  for (const [n, list] of comeIn) {
    const side0 = namesOf(n).map((k) => figure.in?.[k]).find(Boolean) || roomySide(n, nodes, Math.max(...list.map((a) => a.label.length)) * CHAR_W);
    list.forEach((a, k) => {
      const d = k * 14;
      let path, text;
      if (side0 === 'left' || side0 === 'right') {
        const y = n.y + Math.min(10, n.h / 2) + d, x1 = side0 === 'left' ? n.x : n.x + n.w, x0 = side0 === 'left' ? x1 - IN_LEN : x1 + IN_LEN;
        path = [[x0, y], [x1, y]];
        text = { x: side0 === 'left' ? x0 - 4 : x0 + 4, y: y + 4, anchor: side0 === 'left' ? 'end' : null };
      } else {
        const x = n.x + 12 + d, y1 = side0 === 'top' ? n.y : n.y + n.h, y0 = side0 === 'top' ? y1 - IN_LEN + 6 : y1 + IN_LEN - 6;
        path = [[x, y0], [x, y1]];
        text = { x: x - 4, y: side0 === 'top' ? y0 - 5 : y0 + 12 };
      }
      ins.push({ ...a, path, text });
    });
  }
  const groups = groupFrames(nodes, ins, side);
  // Moved in from the edges, with room for the names of the arrows in.
  const xs = [], ys = [];
  for (const n of nodes) { xs.push(n.x, n.x + n.w); ys.push(n.y, n.y + n.h); }
  for (const f of groups) { xs.push(f.x0, f.x1); ys.push(f.y0, f.y1); }
  for (const a of ins) {
    const w = a.label.length * CHAR_W;
    xs.push(a.text.anchor === 'end' ? a.text.x - w : a.text.x, a.text.anchor === 'end' ? a.text.x : a.text.x + w);
    ys.push(a.text.y - 11, a.text.y + 3);
    for (const [x, y] of a.path) { xs.push(x); ys.push(y); }
  }
  const dx = 16 - Math.min(...xs), dy = 16 - Math.min(...ys);
  for (const n of nodes) { n.x += dx; n.y += dy; }
  for (const a of ins) {
    a.d = `M${a.path.map(([x, y]) => `${x + dx},${y + dy}`).join(' L')}`;
    a.text = { ...a.text, x: a.text.x + dx, y: a.text.y + dy };
  }
  for (const f of groups) { f.x0 += dx; f.x1 += dx; f.y0 += dy; f.y1 += dy; }
  // Room on the right and below for arrows that go round.
  return { width: Math.max(...xs) + dx + 40, height: Math.max(...ys) + dy + 28, laneLabels: [], bottom: [], ins, groups };
}

/* Frames round neighbouring boxes of one kind, the kind's name at the head,
   as the ICRP's figures group soft tissue, bone, the liver, the kidneys and
   the gut; and round what the figure does not have (extra). Only where one
   fits: no other box inside it (a way out may be), no other frame across it,
   its name clear of the names of the arrows in. */
const GROUP_KINDS = [
  ['Other soft tissue', (n) => /^(ST\d|Other \d)$/.test(n.name)],
  ['Bone', (n) => n.lane === 'bone'],
  ['Liver', (n) => /^Liver( \d)?$/.test(n.name)],
  ['Kidneys', (n) => /^(Kidneys( \d)?|Urinary path|Other kidney tissue)$/.test(n.name)],
  ['Thyroid', (n) => /^Thyroid( \d)?$/.test(n.name)],
  ['Brain', (n) => /^Brain( \d)?$/.test(n.name)],
  ['Alimentary tract', (n) => n.lane === 'content' && norm(n.region) !== 'ub-cont'],
];
const LANE_CHAR_W = 7.4; // about the width of a character of a group's name (10px Verdana bold capitals, spaced)
function groupFrames(nodes, ins, extra) {
  const near = (a, b) => Math.max(a.x - (b.x + b.w), b.x - (a.x + a.w), 0) <= 3.5 * UX && Math.max(a.y - (b.y + b.h), b.y - (a.y + a.h), 0) <= 1.5 * ROW;
  const hits = (r, q) => r.x0 < q.x1 && r.x1 > q.x0 && r.y0 < q.y1 && r.y1 > q.y0;
  const box = (n) => ({ x0: n.x, y0: n.y, x1: n.x + n.w, y1: n.y + n.h });
  const names = ins.map((a) => {
    const w = a.label.length * CHAR_W, x = a.text.anchor === 'end' ? a.text.x - w : a.text.x;
    return { x0: x, y0: a.text.y - 11, x1: x + w, y1: a.text.y + 3 };
  });
  const sets = [];
  for (const [name, is] of GROUP_KINDS) {
    const left = new Set(nodes.filter((n) => !n.inside && n.lane !== 'sink' && !extra.includes(n) && is(n)));
    while (left.size) {
      const set = [left.values().next().value];
      left.delete(set[0]);
      for (let k = 0; k < set.length; k++) for (const o of [...left]) if (near(set[k], o)) { set.push(o); left.delete(o); }
      if (set.length > 1) sets.push([name === 'Bone' && set.some((n) => /marrow/i.test(n.region)) ? 'Bone and marrow' : name, set]);
    }
  }
  if (extra.length) sets.push(['Not in the figure', extra]);
  const out = [];
  for (const [name, set] of sets) {
    const r = {
      x0: Math.min(...set.map((n) => n.x)) - 6, y0: Math.min(...set.map((n) => n.y)) - 20,
      x1: Math.max(...set.map((n) => n.x + n.w)) + 6, y1: Math.max(...set.map((n) => n.y + n.h)) + 6,
    };
    r.x1 = Math.max(r.x1, r.x0 + name.length * LANE_CHAR_W + 14);
    const head = { x0: r.x0, y0: r.y0, x1: r.x0 + name.length * LANE_CHAR_W + 14, y1: r.y0 + 18 };
    if (nodes.some((n) => n.lane !== 'sink' && !set.includes(n) && !set.some((m) => contains(m, n)) && hits(r, box(n)))) continue;
    if (out.some((f) => hits(r, f)) || names.some((q) => hits(head, q))) continue;
    out.push({ name, ...r });
  }
  return out;
}

const contains = (o, n) => n.x >= o.x - 0.5 && n.x + n.w <= o.x + o.w + 0.5 && n.y >= o.y - 0.5 && n.y + n.h <= o.y + o.h + 0.5;

/* A side of box n with room for an arrow in and its name (text px wide):
   left, then top, right, bottom. */
function roomySide(n, nodes, text) {
  const free = (x0, y0, x1, y1) => !nodes.some((o) => o !== n && !contains(o, n) && o.x < x1 && o.x + o.w > x0 && o.y < y1 && o.y + o.h > y0);
  const need = text + IN_LEN + 8;
  if (free(n.x - need, n.y, n.x - 1, n.y + 20)) return 'left';
  if (free(n.x, n.y - 30, n.x + 8 + text, n.y - 1)) return 'top';
  if (free(n.x + n.w + 1, n.y, n.x + n.w + need, n.y + 20)) return 'right';
  return 'bottom';
}

/* An arrow of a figure: straight across where the two boxes face each other
   (at the middle of what they share), short arrows into and out of a box
   drawn inside another, else at right angles -- across and then up or down
   into b, down or up to a channel between them, across and on, or up or
   down and then across -- the first that crosses no other box; failing all,
   a curve. */
function figureRoute(a, b, off, nodes, i) {
  if (contains(a, b) || contains(b, a)) {
    const inner = contains(a, b) ? b : a, x = inner.x + inner.w / 2 + off * 2;
    return { d: inner === b ? `M${x},${inner.y - 16} L${x},${inner.y}` : `M${x},${inner.y} L${x},${inner.y - 16}`, over: true };
  }
  const others = nodes.filter((n) => n !== a && n !== b && !contains(n, a) && !contains(n, b));
  const clear = (pts) => pts.every(([x0, y0], k) => {
    if (k === 0) return true;
    const [x1, y1] = pts[k - 1];
    const lx = Math.min(x0, x1), hx = Math.max(x0, x1), ly = Math.min(y0, y1), hy = Math.max(y0, y1);
    return !others.some((n) => n.x < hx + 5 && n.x + n.w > lx - 5 && n.y < hy + 5 && n.y + n.h > ly - 5);
  });
  const line = (pts) => ({ d: `M${pts.map(([x, y]) => `${x},${y}`).join(' L')}` });
  const ax0 = a.x, ax1 = a.x + a.w, ay0 = a.y, ay1 = a.y + a.h, bx0 = b.x, bx1 = b.x + b.w, by0 = b.y, by1 = b.y + b.h;
  const acx = (ax0 + ax1) / 2, acy = (ay0 + ay1) / 2, bcx = (bx0 + bx1) / 2, bcy = (by0 + by1) / 2;
  const tries = [];
  const oy0 = Math.max(ay0, by0), oy1 = Math.min(ay1, by1);
  if (oy1 - oy0 > 6) {
    const y = (oy0 + oy1) / 2 + off;
    tries.push(ax1 <= bx0 ? [[ax1, y], [bx0, y]] : [[ax0, y], [bx1, y]]);
  }
  const ox0 = Math.max(ax0, bx0), ox1 = Math.min(ax1, bx1);
  if (ox1 - ox0 > 6) {
    const x = (ox0 + ox1) / 2 + off;
    tries.push(ay1 <= by0 ? [[x, ay1], [x, by0]] : [[x, ay0], [x, by1]]);
  }
  const below = by0 >= ay1, above = by1 <= ay0;
  if ((below || above) && (bcx < ax0 || bcx > ax1)) { // across, then down or up into b
    const y = acy + off, x = bcx + off;
    tries.push([[bcx < ax0 ? ax0 : ax1, y], [x, y], [x, below ? by0 : by1]]);
  }
  if (below || above) { // down or up to a channel between them, across, and on into b
    const cy = (below ? (ay1 + by0) / 2 : (by1 + ay0) / 2) + ((i % 3) - 1) * 4;
    const sx = acx + off, x = bcx + off;
    tries.push([[sx, below ? ay1 : ay0], [sx, cy], [x, cy], [x, below ? by0 : by1]]);
  }
  if ((bcy < ay0 || bcy > ay1) && (acx < bx0 || acx > bx1)) { // up or down, then across into b
    const x = acx + off, y = bcy + off;
    tries.push([[x, bcy < ay0 ? ay0 : ay1], [x, y], [acx < bx0 ? bx0 : bx1, y]]);
  }
  if (acx < bx0 || acx > bx1) { // out of a's top or bottom to a channel beside it, and across into b's side
    const x = acx + off, ex = acx < bx0 ? bx0 : bx1;
    for (const cy of [ay0 - 14 + off, ay1 + 14 + off]) if (cy > by0 + 4 && cy < by1 - 4) tries.push([[x, cy < ay0 ? ay0 : ay1], [x, cy], [ex, cy]]);
  }
  if (bcx < ax0 || bcx > ax1) { // out of a's side to a channel beside b, across, and into b's top or bottom
    const sx = bcx < ax0 ? ax0 : ax1, x = bcx + off;
    for (const cy of [by1 + 14 + off, by0 - 14 + off]) if (cy > ay0 + 4 && cy < ay1 - 4) tries.push([[sx, cy], [x, cy], [x, cy > by1 ? by1 : by0]]);
  }
  for (const pts of tries) if (clear(pts)) return line(pts);
  if (tries.length) return line(tries[0]);
  const sx = acx < bcx ? ax1 : ax0, ex = acx < bcx ? bx0 : bx1, mx = (sx + ex) / 2;
  return { d: `M${sx},${acy + off} C${mx},${acy + off} ${mx},${bcy + off} ${ex},${bcy + off}` };
}

/**
 * The boxes as buckets: levelOf(box) gives {share, text, tip} for a box (its
 * <g class="node">): its level rises from the bottom to share (0 .. 1), text
 * takes the place of its second line and tip follows its own tooltip. A
 * levelOf of null empties them all.
 */
export function fillBoxes(svg, levelOf) {
  svg.classList.toggle('buckets', !!levelOf);
  for (const g of svg.querySelectorAll('.node:not(.sink)')) {
    const level = g.querySelector('.level'), share = g.querySelector('.share');
    if (!level) continue;
    g.dataset.tipBase ??= g.getAttribute('data-tip') || '';
    const v = levelOf ? levelOf(g) : null;
    const f = v ? Math.max(0, Math.min(1, v.share || 0)) : 0;
    const rect = g.querySelector('rect'), w = rect.getAttribute('width'), h = Number(rect.getAttribute('height'));
    level.setAttribute('d', f > 0 ? `M0,${(h * (1 - f)).toFixed(2)}H${w}V${h}H0Z` : '');
    share.textContent = v ? v.text : '';
    g.setAttribute('data-tip', v?.tip ? `${g.dataset.tipBase}. ${v.tip}` : g.dataset.tipBase);
    if (v) g.dataset.share = String(f); else delete g.dataset.share;
  }
}
