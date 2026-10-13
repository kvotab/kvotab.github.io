/*
  A drawing of a compartment model, as SVG built from DOM nodes (no markup
  strings). The layout follows the way the ICRP draws its systemic models:
  soft tissues on the left, blood in the middle, bone and marrow on the right,
  the contents of the alimentary tract and the bladder and the ways out of the
  body along the bottom. Each arrow carries the transfer coefficient at the
  chosen age in its tooltip.

    drawModel({ compartments: [{name, region, parts?, badge?}], transfers: [{from, to, rate, model?}],
                entries: [{name, tip, arrows: [{label, tip}]}] })
      -> SVGSVGElement

  A transfer with a `model` ('alimentary' or 'bladder') belongs to the
  alimentary tract or bladder model around the systemic one, and is dashed.
  `entries` are the boxes activity comes into from outside the drawing: tip
  joins the box's tooltip, and each of arrows comes in from a name of where
  the activity comes from (as the ICRP draws "Inhaled" and "Ingested"): from
  above into a box of the columns, which goes first in its column, from
  below into one of the bottom row. They light like transfers (data-t), in
  a group of their own (.entry-g) that the transfer table has no row for.

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
export const transferKey = (from, to) => `${from}\u2192${to}`;

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

/**
 * @param {object} m  {compartments: [{name, region, label?}], transfers: [{from, to, rate}], entries: [{name, tip, arrows}]}
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
  const lanes = { tissue: [], blood: [], bone: [], content: [], sink: [] };
  for (const n of nodes) lanes[n.lane].push(n);
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
  // A box an arrow comes into first in its column, then blood that activity
  // enters otherwise; bone surfaces before volumes.
  const inFirst = (a, b) => comeIn.has(b) - comeIn.has(a);
  lanes.tissue.sort(inFirst);
  lanes.blood.sort((a, b) => inFirst(a, b) || tipOf.has(b.name) - tipOf.has(a.name));
  const boneOrder = (n) => (/-s$/.test(norm(n.region)) ? 0 : /-v$/.test(norm(n.region)) ? 1 : 2);
  lanes.bone.sort((a, b) => inFirst(a, b) || boneOrder(a) - boneOrder(b));
  const contentOrder = ['o-cavity', 'oesophag-f', 'oesophag-s', 'st-cont', 'si-cont', 'gb-cont', 'rc-cont', 'uli-cont', 'lc-cont', 'lli-cont', 'rs-cont', 'ub-cont'];
  lanes.content.sort((a, b) => contentOrder.indexOf(norm(a.region)) - contentOrder.indexOf(norm(b.region)));

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
  columns.forEach((col, k) => {
    const y0 = top + (colHeight - col.length * (H + GAP)) / 2;
    col.forEach((n, i) => { n.x = x; n.y = y0 + i * (H + GAP); });
    const lane = col[0].lane;
    if (!laneLabels.some((l) => l.lane === lane)) laneLabels.push({ lane, x, text: { tissue: 'Tissues', blood: 'Blood', bone: 'Bone and marrow' }[lane] });
    x += W + COLGAP;
  });
  // Room on the right for the arcs between boxes of the last column.
  const width = Math.max(x - COLGAP + 76, 16 + (lanes.content.length + lanes.sink.length) * (W * 0.8 + 14));
  // The bottom row: the gut's contents down to faeces, then the bladder's to
  // urine, then the other ways out; so that each flows to its neighbour.
  const isUB = (n) => norm(n.region) === 'ub-cont';
  const sinkIs = (n, re) => re.test(n.name);
  const bottom = [
    ...lanes.content.filter((n) => !isUB(n)), ...lanes.sink.filter((n) => sinkIs(n, /^(faeces|feces)$/i)),
    ...lanes.content.filter(isUB), ...lanes.sink.filter((n) => sinkIs(n, /^urine$/i)),
    ...lanes.sink.filter((n) => !sinkIs(n, /^(faeces|feces|urine)$/i)),
  ];
  const rowY = top + colHeight + 40;
  const bw = Math.min(W, (width - 32 - (bottom.length - 1) * 14) / Math.max(1, bottom.length));
  bottom.forEach((n, i) => { n.x = 16 + i * (bw + 14); n.y = rowY; n.w = bw; });
  if (bottom.length) laneLabels.push({ lane: 'bottom', x: 16, y: rowY - 8, text: 'Alimentary tract, bladder and excretion' });
  let height = (bottom.length ? rowY + H : top + colHeight) + 18;

  const svg = el('svg', { width, height, viewBox: `0 0 ${width} ${height}`, role: 'img', 'aria-label': 'Compartment model' });
  const defs = el('defs');
  for (const [id, cls] of [['dcArrow', 'arrow'], ['dcArrowOut', 'arrow out'], ['dcArrowLit', 'arrow lit'], ['dcArrowIn', 'arrow in']]) {
    defs.append(el('marker', { id, viewBox: '0 0 10 10', refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: 'auto-start-reverse' },
      el('path', { d: 'M0,0 L10,5 L0,10 z', class: cls })));
  }
  svg.append(defs);
  for (const l of laneLabels) svg.append(el('text', { x: l.x, y: l.y ?? 14, class: 'lane' }, document.createTextNode(l.text)));

  // Edges under the nodes.
  const g = el('g');
  const pairCount = new Map();
  for (const t of m.transfers) {
    const a = byName.get(t.from), b = byName.get(t.to);
    if (!a || !b || a === b) continue;
    const key = [a.name, b.name].sort().join('|');
    const k = pairCount.get(key) || 0;
    pairCount.set(key, k + 1);
    const wa = a.w || W, wb = b.w || W;
    const ca = { x: a.x + wa / 2, y: a.y + H / 2 }, cb = { x: b.x + wb / 2, y: b.y + H / 2 };
    const anchor = (n, w, c, o) => {
      const dx = o.x - c.x, dy = o.y - c.y;
      if (Math.abs(dx) * H > Math.abs(dy) * w) return { x: dx > 0 ? n.x + w : n.x, y: c.y, side: 'h' };
      return { x: c.x, y: dy > 0 ? n.y + H : n.y, side: 'v' };
    };
    const p = anchor(a, wa, ca, cb), q = anchor(b, wb, cb, ca);
    const off = (k % 2 ? 1 : -1) * 4; // two arrows between the same pair stay apart
    if (p.side === 'h') p.y += off; else p.x += off;
    if (q.side === 'h') q.y += off; else q.x += off;
    let d;
    const ia = bottom.indexOf(a), ib = bottom.indexOf(b);
    if (ia >= 0 && ib >= 0 && Math.abs(ia - ib) > 1) { // along the bottom row past others: an arc under it
      const ax = a.x + wa / 2 + off, bx = b.x + wb / 2 + off, y = a.y + H;
      const dip = 16 + Math.abs(ax - bx) * 0.06;
      d = `M${ax},${y} C${ax},${y + dip} ${bx},${y + dip} ${bx},${y}`;
      height = Math.max(height, y + dip * 0.75 + 12);
    } else if (Math.abs(a.x - b.x) < 1) { // same column: an arc out to the side
      const bulge = 28 + Math.abs(a.y - b.y) * 0.12;
      const sx = a.x + wa;
      d = `M${sx},${a.y + H / 2 + off} C${sx + bulge},${a.y + H / 2 + off} ${sx + bulge},${b.y + H / 2 + off} ${sx},${b.y + H / 2 + off}`;
    } else {
      const mx = (p.x + q.x) / 2, my = (p.y + q.y) / 2;
      d = p.side === 'h' && q.side === 'h' ? `M${p.x},${p.y} C${mx},${p.y} ${mx},${q.y} ${q.x},${q.y}` : `M${p.x},${p.y} Q${mx + off * 3},${my} ${q.x},${q.y}`;
    }
    const out = a.lane === 'blood' && b.lane !== 'blood';
    const tract = t.model ? ' tract' : '';
    const whose = t.model ? ` — the ${t.model === 'bladder' ? 'urinary bladder' : 'alimentary tract'} model` : '';
    // A wide transparent copy under the line, so that the pointer finds it.
    g.append(el('g', { class: `edge-g${out ? ' out' : ''}${tract}`, 'data-t': transferKey(t.from, t.to),
      'data-tip': `${t.from} → ${t.to}: ${fmtRate(t.rate)} d⁻¹${t.rate > 0 ? ` (half-time ${halfTime(t.rate)} if it were the only way out)` : ''}${whose}` },
      el('path', { d, class: 'hit' }),
      el('path', { d, class: `edge${out ? ' out' : ''}${tract}`, 'marker-end': `url(#${out ? 'dcArrowOut' : 'dcArrow'})` })));
  }
  svg.append(g);
  // The arrows in from outside, each from the name of where its activity
  // comes from. Into a box of the columns from the band above them: straight
  // down into the first box of its column, else round the column's right
  // side into the box's; names that share a column side by side, each once.
  // Into a box of the bottom row from below it.
  const ins = el('g');
  const arrowIn = (a, d, text) => ins.append(el('g', { class: 'entry-g', 'data-t': transferKey(a.label, a.name), 'data-tip': a.tip },
    el('path', { d, class: 'hit' }),
    el('path', { d, class: 'edge entry', 'marker-end': 'url(#dcArrow)' }),
    text));
  const nameAt = (label, x, y) => el('text', { x, y, class: 'source' }, document.createTextNode(label));
  for (const col of columns) {
    const at = new Map(); // a name -> the x of its text
    let lx = col[0].x + 4;
    for (const n of col.filter((c) => comeIn.has(c))) {
      const w = n.w || W;
      for (const a of comeIn.get(n)) {
        const first = !at.has(a.label);
        if (first) { at.set(a.label, lx); lx += a.label.length * CHAR_W + 14; }
        const sx = at.get(a.label) + 8, sy = top - BAND + 17;
        const d = n === col[0] && sx < n.x + w - 8
          ? `M${sx},${sy} L${sx},${n.y}`
          : `M${sx},${sy} C${n.x + w + 26},${sy} ${n.x + w + 26},${n.y + H / 2} ${n.x + w},${n.y + H / 2}`;
        arrowIn(a, d, first ? nameAt(a.label, at.get(a.label), top - BAND + 12) : null);
      }
    }
  }
  for (const n of bottom.filter((c) => comeIn.has(c))) {
    let lx = n.x + 4;
    for (const a of comeIn.get(n)) {
      const sx = lx + 8, ly = n.y + H + 28;
      arrowIn(a, `M${sx},${ly - 11} L${sx},${n.y + H}`, nameAt(a.label, lx, ly));
      lx += a.label.length * CHAR_W + 14;
      height = Math.max(height, ly + 8);
    }
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
  nodes.forEach((n, i) => {
    const w = n.w || W;
    const label = n.label || n.name;
    const room = n.badge ? 19 : 22;
    const short = label.length > room ? `${label.slice(0, room - 1)}…` : label;
    const names = [...byName].filter(([, x]) => x === n).map(([k]) => k);
    const [nin, nout] = flows.get(n);
    const counts = nin || nout ? `. ${nin} ${nin === 1 ? 'transfer' : 'transfers'} in (blue), ${nout} out (red)` : '';
    const entry = names.filter((k) => tipOf.has(k)).map((k) => tipOf.get(k)).join('; ');
    const grp = el('g', { class: `node ${n.lane}`, transform: `translate(${n.x},${n.y})`, 'data-part': n.parts?.length ? n.parts.join(' ') : null, 'data-names': names.join('|'),
      'data-region': n.region || null,
      'data-tip': `${label}${n.region && n.region !== label ? ` — source region ${n.region}` : ''}${entry ? ` — ${entry}` : ''}${counts}` },
      el('rect', { width: w, height: H, rx: 6 }));
    if (n.lane !== 'sink') {
      // The bucket's level, empty until fillBoxes() fills it, inside the box's rounded corners.
      defs.append(el('clipPath', { id: `dcClip${i}` }, el('rect', { width: w, height: H, rx: 6 })));
      grp.append(el('path', { class: 'level', d: '', 'clip-path': `url(#dcClip${i})` }));
    }
    grp.append(el('text', { x: 8, y: n.lane === 'sink' ? 21 : 15 }, document.createTextNode(short)));
    if (n.lane !== 'sink' && n.region && n.region !== label) grp.append(el('text', { x: 8, y: 28, class: 'region rcode' }, document.createTextNode(n.region)));
    if (n.lane !== 'sink') grp.append(el('text', { x: 8, y: 28, class: 'share' }));
    if (n.badge) {
      const b = el('g', { class: 'badge', transform: `translate(${w - 11 - (String(n.badge).length - 1) * 2.5},${H - 10})` });
      b.append(badge(n.badge));
      grp.append(b);
    }
    svg.append(grp);
  });
  return svg;
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
    const w = g.querySelector('rect').getAttribute('width');
    level.setAttribute('d', f > 0 ? `M0,${(H * (1 - f)).toFixed(2)}H${w}V${H}H0Z` : '');
    share.textContent = v ? v.text : '';
    g.setAttribute('data-tip', v?.tip ? `${g.dataset.tipBase}. ${v.tip}` : g.dataset.tipBase);
    if (v) g.dataset.share = String(f); else delete g.dataset.share;
  }
}
