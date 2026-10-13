/*
  A drawing of a compartment model, as SVG built from DOM nodes (no markup
  strings). With the ICRP's figure of the model (figures.js), the boxes stand
  where the figure has them; without one, where a figure made the way most of
  the ICRP's are made puts them (synthFigure), with the organs that may stand
  on either side of the blood where the arrows cross the fewest other boxes.
  Each arrow carries the transfer coefficient at the chosen age in its
  tooltip.

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

  `figure` ({boxes: {name: [x, y, w, h]}, in?: {name: side}}; made by
  synthFigure when not given) places each box it names x·UX from the left and y rows down, w·UX wide and h rows high
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

const W = 156, H = 34, GAP = 12;
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

/* The boxes of a model, placed: by its figure, or by one made like the
   ICRP's (from m.links, every pair a transfer joins at any age, so that the
   boxes do not move when another age's rates leave one out). */
function place(m) {
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
  // Without the ICRP's figure of the model, one made like theirs.
  const links = m.links || m.transfers.map((t) => [t.from, t.to]);
  const edges = links.map(([a, b]) => [byName.get(a), byName.get(b)]).filter(([a, b]) => a && b && a !== b);
  const at = figurePlaces(nodes, namesOf, m.figure || synthFigure(nodes, namesOf, edges), comeIn);
  return { nodes, byName, namesOf, tipOf, at };
}

/**
 * Of figures a model might stand as (figures.js similarFigures), the one
 * whose arrows cross the fewest other boxes, if none more than in the figure
 * made for it; else null, and the model takes the made one.
 */
export function chooseFigure(m, candidates) {
  if (!candidates.length) return null;
  const crossing = (figure) => layoutModel({ ...m, figure }).routes.filter((r) => !r.clear).length;
  const made = crossing(null);
  let best = null, least = made;
  for (const f of candidates) {
    const c = crossing(f);
    if (c <= least && (!best || c < least)) { best = f; least = c; }
  }
  return best;
}

/**
 * Where drawModel puts the boxes, and which arrows cross another box: for
 * the tests and chooseFigure, without a document.
 */
export function layoutModel(m) {
  const { nodes, byName, at } = place(m);
  const routes = routeAll(m, nodes, byName).map((r) => ({ from: r.t.from, to: r.t.to, pts: r.pts, clear: routeClear(r, nodes) }));
  return { nodes: nodes.map(({ name, lane, x, y, w, h, inside }) => ({ name, lane, x, y, w, h, inside: !!inside })), routes, groups: at.groups };
}

/**
 * @param {object} m  {compartments: [{name, region, label?}], transfers: [{from, to, rate}], links?, entries: [{name, tip, arrows}], figure?}
 */
export function drawModel(m) {
  const { nodes, byName, namesOf, tipOf, at } = place(m);
  let { width, height } = at;

  const svg = el('svg', { width, height, viewBox: `0 0 ${width} ${height}`, role: 'img', 'aria-label': 'Compartment model' });
  const defs = el('defs');
  for (const [id, cls] of [['dcArrow', 'arrow'], ['dcArrowOut', 'arrow out'], ['dcArrowLit', 'arrow lit'], ['dcArrowIn', 'arrow in']]) {
    defs.append(el('marker', { id, viewBox: '0 0 10 10', refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: 'auto-start-reverse' },
      el('path', { d: 'M0,0 L10,5 L0,10 z', class: cls })));
  }
  svg.append(defs);
  const routes = routeAll(m, nodes, byName);
  // A group's name where no arrow passes: at the left of its frame, in the middle, or at the right.
  const segments = routes.flatMap((r) => (r.pts ? r.pts.slice(1).map((p, k) => [r.pts[k], p]) : []));
  const crossed = (x0, y0, x1, y1) => segments.filter(([[ax, ay], [bx, by]]) => Math.min(ax, bx) < x1 && Math.max(ax, bx) > x0 && Math.min(ay, by) < y1 && Math.max(ay, by) > y0).length;
  for (const f of at.groups || []) {
    const w = f.name.length * LANE_CHAR_W;
    const hits = f.heads.map((x) => crossed(x - 4, f.y0 + 2, x + w + 4, f.y0 + 17));
    const at0 = f.heads[hits.indexOf(Math.min(...hits))];
    svg.append(el('g', { class: 'group' }, el('rect', { x: f.x0, y: f.y0, width: f.x1 - f.x0, height: f.y1 - f.y0, rx: 6 }),
      el('text', { x: at0, y: f.y0 + 13, class: 'lane' }, document.createTextNode(f.name))));
  }

  // Edges under the nodes; those into and out of a box drawn inside another over them.
  const g = el('g'), over = el('g');
  for (const route of routes) {
    const { t, a, b } = route;
    const out = a.lane === 'blood' && b.lane !== 'blood';
    const tract = t.model ? ' tract' : '';
    const whose = t.model ? ` — the ${t.model === 'bladder' ? 'urinary bladder' : 'alimentary tract'} model` : '';
    // A wide transparent copy under the line, so that the pointer finds it.
    (route.over || a.inside || b.inside ? over : g).append(el('g', { class: `edge-g${out ? ' out' : ''}${tract}`, 'data-t': transferKey(t.from, t.to),
      'data-tip': `${t.from} → ${t.to}: ${fmtRate(t.rate)} d⁻¹${t.rate > 0 ? ` (half-time ${halfTime(t.rate)} if it were the only way out)` : ''}${whose}` },
      el('path', { d: route.d, class: 'hit' }),
      el('path', { d: route.d, class: `edge${out ? ' out' : ''}${tract}`, 'marker-end': `url(#${out ? 'dcArrowOut' : 'dcArrow'})` })));
  }
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
  for (const f of groups) { f.x0 += dx; f.x1 += dx; f.y0 += dy; f.y1 += dy; f.heads = f.heads.map((x) => x + dx); }
  // Room on the right and below for arrows that go round.
  return { width: Math.max(...xs) + dx + 40, height: Math.max(...ys) + dy + 28, ins, groups };
}

/* Frames round neighbouring boxes of one kind, the kind's name at the head,
   as the ICRP's figures group soft tissue, bone, the liver, the kidneys and
   the gut (not what the figure does not have, extra). Only where one fits:
   no other box inside it (a way out may be), no other frame across it, and
   a place for its name clear of the arrows in and their names -- at the
   left, in the middle or at the right of its head (heads; drawModel takes
   the one clear of the other arrows). */
const GROUP_KINDS = [
  ['Other soft tissue', (n) => /^(ST\d|Other[ _]\w+|Body_Tis(_\w+)?|BT-Soft_\w+)$/.test(n.name)],
  ['Bone', (n) => n.lane === 'bone'],
  ['Liver', (n) => /^Liver([ _]\w+)?$/.test(n.name)],
  ['Kidneys', (n) => /^(Kidneys([ _]\w+)?|Urinary path|Other kidney tissue)$/.test(n.name)],
  ['Thyroid', (n) => /^Thyroid([ _]\w+)?$/.test(n.name)],
  ['Brain', (n) => /^Brain([ _]\w+)?$/.test(n.name)],
  ['Alimentary tract', (n) => n.lane === 'content' && norm(n.region) !== 'ub-cont'],
];
const LANE_CHAR_W = 7.4; // about the width of a character of a group's name (10px Verdana bold capitals, spaced)
function groupFrames(nodes, ins, extra) {
  const near = (a, b) => Math.max(a.x - (b.x + b.w), b.x - (a.x + a.w), 0) <= 3.5 * UX && Math.max(a.y - (b.y + b.h), b.y - (a.y + a.h), 0) <= 1.5 * ROW;
  const hits = (r, q) => r.x0 < q.x1 && r.x1 > q.x0 && r.y0 < q.y1 && r.y1 > q.y0;
  const box = (n) => ({ x0: n.x, y0: n.y, x1: n.x + n.w, y1: n.y + n.h });
  const names = ins.flatMap((a) => {
    const w = a.label.length * CHAR_W, x = a.text.anchor === 'end' ? a.text.x - w : a.text.x;
    const xs = a.path.map(([px]) => px), ys = a.path.map(([, py]) => py);
    return [{ x0: x, y0: a.text.y - 11, x1: x + w, y1: a.text.y + 3 },
      { x0: Math.min(...xs) - 2, y0: Math.min(...ys), x1: Math.max(...xs) + 2, y1: Math.max(...ys) }];
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
  const out = [];
  for (const [name, set] of sets) {
    const r = {
      x0: Math.min(...set.map((n) => n.x)) - 6, y0: Math.min(...set.map((n) => n.y)) - 20,
      x1: Math.max(...set.map((n) => n.x + n.w)) + 6, y1: Math.max(...set.map((n) => n.y + n.h)) + 6,
    };
    const headW = name.length * LANE_CHAR_W + 14;
    r.x1 = Math.max(r.x1, r.x0 + headW);
    if (nodes.some((n) => n.lane !== 'sink' && !set.includes(n) && !set.some((m) => contains(m, n)) && hits(r, box(n)))) continue;
    if (out.some((f) => hits(r, f))) continue;
    const heads = [r.x0, (r.x0 + r.x1 - headW) / 2, r.x1 - headW].filter((x) => !names.some((q) => hits({ x0: x, y0: r.y0, x1: x + headW, y1: r.y0 + 18 }, q)));
    if (!heads.length) continue;
    out.push({ name, ...r, heads: heads.map((x) => x + 7) });
  }
  return out;
}

/* The arrows of a model: each routed by figureRoute, two between the same
   pair a little apart, then spread (spreadRoutes). Each is {t, a, b, pts,
   d, over, clear}. */
function routeAll(m, nodes, byName) {
  const routes = [];
  const pairCount = new Map();
  m.transfers.forEach((t, i) => {
    const a = byName.get(t.from), b = byName.get(t.to);
    if (!a || !b || a === b) return;
    const key = [a.name, b.name].sort().join('|');
    const k = pairCount.get(key) || 0;
    pairCount.set(key, k + 1);
    const off = (k % 2 ? 1 : -1) * 4; // two arrows between the same pair stay apart
    routes.push({ t, a, b, ...figureRoute(a, b, off, nodes, i) });
  });
  spreadRoutes(routes, nodes);
  for (const r of routes) if (r.pts) r.d = `M${r.pts.map(([x, y]) => `${x},${y}`).join(' L')}`;
  return routes;
}

/* Whether a route keeps clear of the boxes (as figureRoute decides it): no
   segment within 5 px of another box, none through its own two but at its
   ends. */
function routeClear(r, nodes) {
  if (!r.pts) return r.clear;
  if (r.over) return true;
  const { a, b, pts } = r;
  const others = nodes.filter((n) => n !== a && n !== b && !contains(n, a) && !contains(n, b));
  const through = (n, lx, hx, ly, hy) => n.x + 2 < hx && n.x + n.w - 2 > lx && n.y + 2 < hy && n.y + n.h - 2 > ly;
  return pts.every(([x0, y0], k) => {
    if (k === 0) return true;
    const [x1, y1] = pts[k - 1];
    const lx = Math.min(x0, x1), hx = Math.max(x0, x1), ly = Math.min(y0, y1), hy = Math.max(y0, y1);
    if ((k > 1 && through(a, lx, hx, ly, hy)) || (k < pts.length - 1 && through(b, lx, hx, ly, hy))) return false;
    return !others.some((n) => n.x < hx + 5 && n.x + n.w > lx - 5 && n.y < hy + 5 && n.y + n.h > ly - 5);
  });
}

/* Lines of different arrows that run along one another, nearer than a
   track, are moved apart onto tracks TRACK px apart (closer where the room
   between the boxes is less), in the order that crosses the fewest of them;
   and so are ends that share a side of a box, spread along it. A line keeps
   clear of the boxes it passes, an end keeps to its side of its box, and a
   bend keeps turning the way it did. The lines up and down first, then the
   lines across, over again while anything moves; within each, over again
   while lines spread apart come near others. */
const TRACK = 7;
function spreadRoutes(routes, nodes) {
  for (let round = 0; round < 3; round++) {
    let moved = false;
    for (const across of [false, true]) for (let k = 0; k < 4 && spreadOnce(routes, nodes, across); k++) moved = true;
    if (!moved) break;
  }
}
function spreadOnce(routes, nodes, across) {
  let moved = false;
  {
    const C = across ? 1 : 0, S = across ? 0 : 1; // the coordinate a segment is at, and the one it runs along
    const segs = [];
    for (const r of routes) {
      if (!r.pts || r.over) continue;
      const n = r.pts.length;
      for (let k = 1; k < n; k++) {
        const p = r.pts[k - 1], q = r.pts[k];
        if (Math.abs(p[C] - q[C]) > 0.5 || Math.abs(p[S] - q[S]) < 1) continue;
        // Its two ends: on the route's own box, or bending into the next segment (and where that one goes).
        const ends = [[k - 1, k - 2], [k, k + 1]].map(([e, nb]) => ({
          at: r.pts[e][S], to: nb >= 0 && nb < n ? r.pts[nb][C] : null, box: e === 0 ? r.a : e === n - 1 ? r.b : null,
        }));
        segs.push({ r, k, c: p[C], lo: Math.min(p[S], q[S]), hi: Math.max(p[S], q[S]), ends });
      }
    }
    // Clusters: segments of different arrows nearer than a track, alongside one another.
    const parent = segs.map((_, i) => i);
    const find = (i) => (parent[i] === i ? i : (parent[i] = find(parent[i])));
    for (let i = 0; i < segs.length; i++) {
      for (let j = i + 1; j < segs.length; j++) {
        const s = segs[i], t = segs[j];
        if (s.r !== t.r && Math.abs(s.c - t.c) < TRACK - 0.5 && Math.min(s.hi, t.hi) - Math.max(s.lo, t.lo) > 1) parent[find(i)] = find(j);
      }
    }
    const clusters = new Map();
    segs.forEach((s, i) => { const g = find(i); if (!clusters.has(g)) clusters.set(g, []); clusters.get(g).push(s); });
    // Where a segment may go.
    const bound = (s) => {
      let lo = -Infinity, hi = Infinity;
      const own = [];
      for (const e of s.ends) {
        if (e.box) { // an end on a box keeps to its side, clear of the corners
          own.push(e.box);
          const b0 = e.box[across ? 'y' : 'x'], b1 = b0 + e.box[across ? 'h' : 'w'];
          lo = Math.max(lo, b0 + 6); hi = Math.min(hi, b1 - 6);
        } else if (e.to != null) { // a bend keeps turning the way it did
          if (e.to > s.c) hi = Math.min(hi, e.to - 3); else lo = Math.max(lo, e.to + 3);
        }
      }
      for (const o of nodes) { // clear of the boxes it passes
        if (own.includes(o) || own.some((b) => contains(o, b))) continue;
        const o0 = o[across ? 'x' : 'y'], o1 = o0 + o[across ? 'w' : 'h'];
        if (!(o0 < s.hi + 5 && o1 > s.lo - 5)) continue;
        const p0 = o[across ? 'y' : 'x'] - 5, p1 = o[across ? 'y' : 'x'] + o[across ? 'h' : 'w'] + 5;
        if (p1 <= s.c + 0.01) lo = Math.max(lo, p1);
        else if (p0 >= s.c - 0.01) hi = Math.min(hi, p0);
        else { lo = s.c; hi = s.c; }
      }
      s.min = Math.min(lo, s.c); s.max = Math.max(hi, s.c);
    };
    // Crossings if s goes before t (above it, or left of it): bends of one across the other.
    const cost = (s, t) => {
      let x = 0;
      for (const e of s.ends) if (e.to != null && e.at > t.lo + 1 && e.at < t.hi - 1 && e.to > t.c) x++;
      for (const e of t.ends) if (e.to != null && e.at > s.lo + 1 && e.at < s.hi - 1 && e.to < s.c) x++;
      return x;
    };
    // The order of the fewest crossings (exactly for up to nine, else by swapping neighbours), the present order on a tie.
    const orderOf = (group) => {
      const n = group.length;
      const pc = group.map((s) => group.map((t) => (s === t ? 0 : cost(s, t) + (s.c > t.c + 0.5 ? 0.001 : 0))));
      if (n > 9) {
        const order = group.map((_, i) => i).sort((i, j) => group[i].c - group[j].c);
        for (let pass = 0, swapped = true; swapped && pass < n * n; pass++) {
          swapped = false;
          for (let k = 0; k + 1 < n; k++) {
            const [i, j] = [order[k], order[k + 1]];
            if (pc[j][i] < pc[i][j]) { order[k] = j; order[k + 1] = i; swapped = true; }
          }
        }
        return order.map((i) => group[i]);
      }
      const N = 1 << n, best = new Float64Array(N).fill(Infinity), last = new Int32Array(N).fill(-1);
      best[0] = 0;
      for (let mask = 0; mask < N; mask++) {
        if (best[mask] === Infinity) continue;
        for (let j = 0; j < n; j++) {
          if (mask & (1 << j)) continue;
          let c = best[mask];
          for (let i = 0; i < n; i++) if (mask & (1 << i)) c += pc[i][j];
          if (c < best[mask | (1 << j)] - 1e-9) { best[mask | (1 << j)] = c; last[mask | (1 << j)] = j; }
        }
      }
      const order = [];
      for (let mask = N - 1; mask; mask &= ~(1 << last[mask])) order.unshift(group[last[mask]]);
      return order;
    };
    // Tracks about where the lines were, TRACK apart, or closer where they must be.
    const tracks = (order) => {
      const n = order.length, mid = order.reduce((a, s) => a + s.c, 0) / n;
      for (const sp of [TRACK, 5, 3.5]) {
        const cs = order.map((_, k) => mid + (k - (n - 1) / 2) * sp);
        for (let pass = 0; pass < 6; pass++) {
          order.forEach((s, k) => { cs[k] = Math.min(s.max, Math.max(s.min, cs[k])); });
          for (let k = 1; k < n; k++) cs[k] = Math.max(cs[k], cs[k - 1] + sp);
          for (let k = n - 2; k >= 0; k--) cs[k] = Math.min(cs[k], cs[k + 1] - sp);
        }
        if (order.every((s, k) => cs[k] >= s.min - 0.01 && cs[k] <= s.max + 0.01 && (k === 0 || cs[k] - cs[k - 1] >= sp - 0.01))) return cs;
      }
      return null;
    };
    for (const group of clusters.values()) {
      if (group.length < 2) continue;
      group.forEach(bound);
      const order = orderOf(group);
      const cs = tracks(order);
      if (!cs) continue;
      order.forEach((s, k) => {
        if (Math.abs(cs[k] - s.c) > 0.01) moved = true;
        s.r.pts[s.k - 1][C] = cs[k]; s.r.pts[s.k][C] = cs[k];
      });
    }
  }
  return moved;
}

/* A figure for a model none of the ICRP's figures draws: the shape most of
   theirs share -- the blood down the middle (other blood pools inside it at
   its foot), soft tissue at the top, bone below it on the left, a row each,
   kidneys over the bladder at the bottom left (the kidney the bladder takes
   from beside it), the liver (the part the gut takes from nearest it), the
   gut (each wall beside its contents) and other organs down the right, the
   ways out beside what they leave. What is free is found by trial, keeping
   the arrangement whose arrows cross the fewest other boxes (figureRoute's
   clear), the lower drawing for a tie: each bone row's order, and the side
   of the blood each other organ stands on. A second shape -- the blood on
   the left, the tissues in a column beside it, the bladder and the gut on
   the right, beside them or below them -- is taken where its arrows cross
   fewer: the ICRP 30 kind of model, whose tissues empty into the excreta.
   Made once for a model and its arrows. */
const GUT_WALL = /^(st|si|rc|lc|rs|uli|lli)-wall$/;
const SOFT = /^(ST\d|Other([ _]\w+)?|Body[ _]Tis\w*|BT-Soft\w*|Extravascular .*|All tissues|Short-term tissue|Long-term tissue)$/i;
const KIDNEY = /^(Kidneys?([ _]\w+)?|Urinary path|Other kidney tissue)$/i;
const madeFigures = new Map();
function* orders(list) {
  if (list.length < 2) { yield list; return; }
  for (let i = 0; i < list.length; i++) for (const rest of orders([...list.slice(0, i), ...list.slice(i + 1)])) yield [list[i], ...rest];
}
function synthFigure(nodes, namesOf, edges) {
  const key = `${nodes.map((n) => `${n.name}~${n.region}`).join('|')}#${edges.map(([a, b]) => `${a.name}>${b.name}`).join('|')}`;
  if (madeFigures.has(key)) return madeFigures.get(key);
  const kind = (n) => {
    const r = norm(n.region);
    if (n.lane === 'sink') return 'sink';
    if (n.lane === 'content') return r === 'ub-cont' ? 'bladder' : 'gut';
    if (n.lane === 'blood') return 'blood';
    if (n.lane === 'bone') return 'bone';
    if (GUT_WALL.test(r)) return 'wall';
    if (SOFT.test(n.name)) return 'soft';
    if (KIDNEY.test(n.name) || r === 'kidneys') return 'kidney';
    if (/^Liver/i.test(n.name)) return 'liver';
    return 'organ';
  };
  const of = { blood: [], soft: [], bone: [], kidney: [], liver: [], organ: [], wall: [], gut: [], bladder: [], sink: [] };
  for (const n of nodes) of[kind(n)].push(n);
  const links = new Map(nodes.map((n) => [n, new Set()]));
  for (const [a, b] of edges) { links.get(a).add(b); links.get(b).add(a); }
  const touches = (n, list) => list.some((o) => links.get(n).has(o));
  // The blood that exchanges with the most boxes is the tall one.
  const blood = [...of.blood].sort((a, b) => links.get(b).size - links.get(a).size);
  const [main, ...inner] = blood;
  of.liver.sort((a, b) => touches(a, of.gut) - touches(b, of.gut));
  of.kidney.sort((a, b) => touches(a, of.bladder) - touches(b, of.bladder));
  // Bone in rows, cortical, trabecular, the rest; each first in the order of steps from the blood.
  const steps = new Map(blood.map((n) => [n, 0]));
  for (const q = [...blood]; q.length;) {
    const n = q.shift();
    for (const o of links.get(n)) if (!steps.has(o)) { steps.set(o, steps.get(n) + 1); q.push(o); }
  }
  const away = (n) => steps.get(n) ?? 9;
  const rowOf = (n) => (/^c[-_]|cort/i.test(`${n.region} ${n.name}`) ? 0 : /^t[-_]|trab/i.test(`${n.region} ${n.name}`) ? 1 : 2);
  const marrow = (n) => /marrow/i.test(n.region);
  const rows0 = [0, 1, 2].map((k) => of.bone.filter((n) => rowOf(n) === k).sort((a, b) => away(a) - away(b) || marrow(b) - marrow(a))).filter((r) => r.length);
  const gut = [...of.gut].sort((a, b) => CONTENT_ORDER.indexOf(norm(a.region)) - CONTENT_ORDER.indexOf(norm(b.region)));
  const W6 = 6.5, LX = 9, BX = 17, RX = 24.5;
  const sinkW = (n) => ((n.label || n.name).length * CHAR_W + 14) / UX;
  // The ways out: urine beside the bladder, faeces beside the last of the gut, any other beside what it leaves.
  const placeSinks = (boxes, urineAt, faecesAt) => {
    const solid = Object.values(boxes).filter((b) => b.length === 4);
    const minX = Math.min(...solid.map((b) => b[0])), maxX = Math.max(...solid.map((b) => b[0] + b[2]));
    const taken = new Set();
    for (const n of of.sink) {
      let at;
      if (/^urine$/i.test(n.name) && urineAt) at = urineAt(n);
      else if (/^(faeces|feces)$/i.test(n.name) && faecesAt) at = faecesAt;
      else {
        const src = edges.filter(([, b]) => b === n).map(([a]) => boxes[a.name]).find((b) => b && b.length === 4);
        const leftward = src && src[0] + src[2] / 2 < BX + 2.25;
        at = [leftward ? minX - sinkW(n) - 1 : maxX + 1, src ? src[1] + 0.25 : 0.25];
      }
      while (taken.has(`${at[0]},${at[1]}`)) at = [at[0], at[1] + 0.7];
      taken.add(`${at[0]},${at[1]}`);
      boxes[n.name] = at;
    }
  };
  // The blood a little below the lowest box it exchanges with, and room for the pools inside it.
  const sizeBlood = (boxes, x, top) => {
    const reach = blood.flatMap((b) => [...links.get(b)]).map((n) => boxes[n.name]).filter((b) => b && b.length === 4).map(([, y, , h]) => y + h);
    const bottom = Math.max(top + 2, top + 0.6 + inner.length * 1.7, ...reach.map((r) => r + 0.5));
    if (main) boxes[main.name] = [x, top, 4.5, bottom - top];
    inner.forEach((n, i) => { boxes[n.name] = [x + 0.7, bottom - 2.1 - i * 1.7, 3.1, 1.4]; });
  };
  const layout = (rows, left, right) => {
    const boxes = {};
    const put = (n, x, y, w = W6, h = 1) => { boxes[n.name] = [x, y, w, h]; };
    const softTop = of.bone.length > 0 && of.soft.length > 0 && of.soft.length <= 3;
    const top = softTop ? 1.5 : 0;
    if (softTop) of.soft.forEach((n, i) => put(n, [LX, BX - 1, RX][i], 0));
    let ly = top;
    if (!softTop) {
      for (const n of of.soft) { put(n, LX, ly); ly += 1.1; }
      if (of.soft.length) ly += 0.4;
    }
    for (const row of rows) { row.forEach((n, i) => put(n, LX - 7.5 * i, ly, W6, 1.2)); ly += 1.8; }
    for (const n of left) { put(n, LX, ly); ly += 1.15; }
    if (left.length) ly += 0.2;
    of.kidney.forEach((n, i) => put(n, LX, ly + i * 1.2, W6, 1.2));
    const ubY = ly + Math.max(0, of.kidney.length - 1) * 1.2;
    of.bladder.forEach((n, i) => put(n, LX - 7.5, ubY + i * 1.3, 5.5, 1.2));
    let ry = top;
    for (const n of of.liver) { put(n, RX, ry); ry += 1.1; }
    if (of.liver.length) ry += 0.3;
    const gx = of.wall.length ? RX + 7.5 : RX;
    gut.forEach((n, i) => put(n, gx, ry + i * 1.1));
    let wy = ry + gut.length * 1.1;
    for (const w of of.wall) {
      const k = gut.findIndex((g) => norm(g.region) === norm(w.region).replace(/-wall$/, '-cont'));
      if (k >= 0) put(w, RX, ry + k * 1.1);
      else { put(w, RX, wy); wy += 1.1; }
    }
    const lastGut = ry + (gut.length - 1) * 1.1;
    ry = Math.max(ry + gut.length * 1.1, wy) + (gut.length ? 0.3 : 0);
    for (const n of right) { put(n, RX, ry); ry += 1.15; }
    sizeBlood(boxes, BX, top);
    placeSinks(boxes, () => [LX - 12, ubY + 0.3], gut.length ? [gx + 7, lastGut + 0.25] : null);
    return boxes;
  };
  const flow = (rows, below) => {
    const boxes = {};
    const put = (n, x, y, w = W6, h = 1) => { boxes[n.name] = [x, y, w, h]; };
    const mid = [...of.liver, ...of.kidney, ...rows.flat(), ...of.organ, ...of.wall, ...of.soft];
    mid.forEach((n, i) => put(n, 7.5, i * 1.15));
    let ry = below ? mid.length * 1.15 + 0.3 : 0;
    const ubY = ry;
    for (const n of of.bladder) { put(n, 16.5, ry, 6.5, 1.2); ry += 1.6; }
    gut.forEach((n, i) => put(n, 16.5, ry + i * 1.1));
    sizeBlood(boxes, 0, 0);
    placeSinks(boxes, () => [24, ubY + 0.3], gut.length ? [24, ry + (gut.length - 1) * 1.1 + 0.25] : null);
    return boxes;
  };
  const scoreOf = (boxes) => {
    const figure = { boxes };
    figurePlaces(nodes, namesOf, figure, new Map());
    let crossing = 0;
    edges.forEach(([a, b], i) => { if (!figureRoute(a, b, 0, nodes, i).clear) crossing++; });
    return [crossing * 1e5 + Math.max(...nodes.map((n) => n.y + n.h)), figure];
  };
  let rows = rows0.map((r) => [...r]), left = [], right = [...of.organ];
  let [best, figure] = scoreOf(layout(rows, left, right));
  const consider = ([s, f], then) => { if (s < best) { best = s; figure = f; then(); return true; } return false; };
  // Each bone row in its best order.
  for (let k = 0; k < rows.length; k++) {
    if (rows[k].length < 2 || rows[k].length > 4) continue;
    for (const order of orders(rows[k])) {
      const trial = rows.map((r, j) => (j === k ? order : r));
      consider(scoreOf(layout(trial, left, right)), () => { rows = trial; });
    }
  }
  // Each other organ on its better side, in its better place there.
  let tries = 0;
  for (let pass = 0; pass < 3 && tries < 150; pass++) {
    let better = false;
    for (const n of of.organ) {
      const onLeft = left.includes(n);
      const from = (onLeft ? left : right).filter((x) => x !== n), to = onLeft ? right : left;
      for (let k = 0; k <= to.length && tries < 150; k++, tries++) {
        const moved = [...to.slice(0, k), n, ...to.slice(k)];
        const [l, r] = onLeft ? [from, moved] : [moved, from];
        if (consider(scoreOf(layout(rows, l, r)), () => { [left, right] = [l, r]; })) { better = true; break; }
      }
    }
    if (!better) break;
  }
  // The second shape, the excreta beside the tissues or below them.
  if (main) for (const below of [false, true]) consider(scoreOf(flow(rows0, below)), () => {});
  // Arrows from outside into the gut from the right, clear of the column's head.
  figure.in = Object.fromEntries(gut.map((n) => [n.name, 'right']));
  if (madeFigures.size > 60) madeFigures.clear();
  madeFigures.set(key, figure);
  return figure;
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
   into b, down or up to a channel between them, across and on, up or down
   and then across, across to a channel in the gap between them, along it
   and across, or round the boxes between, out to a channel beside both (or
   above or below both), along and back -- the first that crosses no other
   box (clear); failing all, the first of them, or a curve. */
function figureRoute(a, b, off, nodes, i) {
  if (contains(a, b) || contains(b, a)) {
    const inner = contains(a, b) ? b : a, x = inner.x + inner.w / 2 + off * 2;
    const pts = inner === b ? [[x, inner.y - 16], [x, inner.y]] : [[x, inner.y], [x, inner.y - 16]];
    return { d: `M${pts[0].join(',')} L${pts[1].join(',')}`, pts, over: true, clear: true };
  }
  const others = nodes.filter((n) => n !== a && n !== b && !contains(n, a) && !contains(n, b));
  // Clear: no segment within 5 px of another box, and none through a or b but at its own end.
  const through = (n, lx, hx, ly, hy) => n.x + 2 < hx && n.x + n.w - 2 > lx && n.y + 2 < hy && n.y + n.h - 2 > ly;
  const clear = (pts) => pts.every(([x0, y0], k) => {
    if (k === 0) return true;
    const [x1, y1] = pts[k - 1];
    const lx = Math.min(x0, x1), hx = Math.max(x0, x1), ly = Math.min(y0, y1), hy = Math.max(y0, y1);
    if ((k > 1 && through(a, lx, hx, ly, hy)) || (k < pts.length - 1 && through(b, lx, hx, ly, hy))) return false;
    return !others.some((n) => n.x < hx + 5 && n.x + n.w > lx - 5 && n.y < hy + 5 && n.y + n.h > ly - 5);
  });
  const line = (pts) => ({ d: `M${pts.map(([x, y]) => `${x},${y}`).join(' L')}`, pts: pts.map(([x, y]) => [x, y]) });
  const ax0 = a.x, ax1 = a.x + a.w, ay0 = a.y, ay1 = a.y + a.h, bx0 = b.x, bx1 = b.x + b.w, by0 = b.y, by1 = b.y + b.h;
  const acx = (ax0 + ax1) / 2, acy = (ay0 + ay1) / 2, bcx = (bx0 + bx1) / 2, bcy = (by0 + by1) / 2;
  const tries = [];
  // Straight across where the boxes face each other: at the middle of what they share, else beside a box in the way.
  const oy0 = Math.max(ay0, by0), oy1 = Math.min(ay1, by1);
  if (oy1 - oy0 > 6) {
    const slid = others.flatMap((n) => [n.y - 9, n.y + n.h + 9]).filter((y) => y > oy0 + 3 && y < oy1 - 3);
    for (const y of [(oy0 + oy1) / 2 + off, ...slid]) tries.push(ax1 <= bx0 ? [[ax1, y], [bx0, y]] : [[ax0, y], [bx1, y]]);
  }
  const ox0 = Math.max(ax0, bx0), ox1 = Math.min(ax1, bx1);
  if (ox1 - ox0 > 6) {
    const slid = others.flatMap((n) => [n.x - 9, n.x + n.w + 9]).filter((x) => x > ox0 + 3 && x < ox1 - 3);
    for (const x of [(ox0 + ox1) / 2 + off, ...slid]) tries.push(ay1 <= by0 ? [[x, ay1], [x, by0]] : [[x, ay0], [x, by1]]);
  }
  const below = by0 >= ay1, above = by1 <= ay0;
  if ((below || above) && (bcx < ax0 || bcx > ax1)) { // across, then down or up into b
    const y = acy + off, x = bcx + off;
    tries.push([[bcx < ax0 ? ax0 : ax1, y], [x, y], [x, below ? by0 : by1]]);
  }
  if (below || above) { // down or up to a channel between them, across, and on into b (at its middle if the step aside does not fit)
    const mid = below ? (ay1 + by0) / 2 : (by1 + ay0) / 2, sx = acx + off, x = bcx + off;
    for (const cy of new Set([mid + ((i % 3) - 1) * 4, mid])) tries.push([[sx, below ? ay1 : ay0], [sx, cy], [x, cy], [x, below ? by0 : by1]]);
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
  if (ax1 <= bx0 - 12 || bx1 <= ax0 - 12) { // across to a channel in the gap between them, along it, and across into b
    const toRight = ax1 <= bx0;
    const gx = (toRight ? (ax1 + bx0) / 2 : (bx1 + ax0) / 2) + ((i % 5) - 2) * 4;
    tries.push([[toRight ? ax1 : ax0, acy + off], [gx, acy + off], [gx, bcy + off], [toRight ? bx0 : bx1, bcy + off]]);
  }
  // Round the boxes between: out to a channel beside both (or above or below both), along it, and back in.
  const jog = 12 + (i % 3) * 4 + Math.abs(off);
  for (const right of [true, false]) {
    const cx = right ? Math.max(ax1, bx1) + jog : Math.min(ax0, bx0) - jog, ex = right ? ax1 : ax0, bxe = right ? bx1 : bx0;
    tries.push([[ex, acy + off], [cx, acy + off], [cx, bcy + off], [bxe, bcy + off]]);
  }
  for (const up of [true, false]) {
    const cy = up ? Math.min(ay0, by0) - jog : Math.max(ay1, by1) + jog, ey = up ? ay0 : ay1, bye = up ? by0 : by1;
    tries.push([[acx + off, ey], [acx + off, cy], [bcx + off, cy], [bcx + off, bye]]);
  }
  for (const pts of tries) if (clear(pts)) return { ...line(pts), clear: true };
  if (tries.length) return { ...line(tries[0]), clear: false };
  const sx = acx < bcx ? ax1 : ax0, ex = acx < bcx ? bx0 : bx1, mx = (sx + ex) / 2;
  return { d: `M${sx},${acy + off} C${mx},${acy + off} ${mx},${bcy + off} ${ex},${bcy + off}`, pts: null, clear: false };
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
