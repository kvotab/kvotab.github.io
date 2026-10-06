/* ==========================================================================
   ENSDF.HTML: THE DECAY-CHAIN CHART

   Draws a chain from KVOT_ENSDF_CORE.buildChain() as a decay-series chart:
   atomic number Z across, mass number A down, one box per state coloured by
   its half-life. Alpha decay steps down a row and two columns left, beta-
   minus one column right on the same row, electron capture one column left,
   neutron emission down a row. An isomer and the ground state it decays to
   share a column and stand one above the other. Fission ends in the column
   at the far right. A chain built going up -- the parents of a state -- is
   drawn the same way, the start then at the foot of its arrows.

   Only the rows that hold a member are drawn, so a chain that jumps from
   A = 238 to 206 by cluster emission does not leave thirty empty rows, but
   every Z between the lightest and heaviest member keeps its column: the
   distance across is the change in charge, and that should read true.

   The other way to draw it, the series, is the one Radionuclide Decay
   Chains (rdc.html) uses: a circle for each state, with its mass number,
   atomic number, symbol and half-life, alpha decay straight down, beta-
   minus one step to the right and electron capture one to the left -- the
   chart turned so that Z - N runs across. Both are laid out, routed and
   labelled by the rules below; render() takes the one asked for.

   SVG, not canvas: the chain is a few dozen boxes, each is something to
   click and hover, and the same markup saves as a file.

   One global: KVOT_ENSDF_CHAIN.
   ========================================================================== */
/* global KVOT_ENSDF_CORE */
(function () {
  'use strict';

  const C = KVOT_ENSDF_CORE;
  const NS = 'http://www.w3.org/2000/svg';

  /* The gap between two boxes in a row (cellW - boxW), between rows
     (rowPad) and between an isomer and the state below it (vGap) is where the
     arrows and their labels go; vGap is a label's height and a little more,
     so the share of an IT branch fits on its short arrow. */
  const GEOM = {
    style: 'grid', cellW: 104, boxW: 68, boxH: 40, vGap: 22, rowPad: 26, left: 52, top: 50, right: 16, bottom: 30, fissionGap: 18,
    /* A label: its height, and how far to either side of its arrow it is tried. */
    labelH: 16, offsets: [0, -13, 13, -26, 26], flatOffsets: [0],
  };

  /* The series, as rdc.html draws it: circles 80 px across, a step of
     100√2 px either way -- beta-minus across, alpha down -- so that half a
     step across (unit) is one in Z - N. An isomer stands over its ground
     state, vGap apart, so the IT arrow between them shows round its label.
     Each arrow is labelled with its mode over its share, in two lines, on
     the arrow or just beside it (beside: the gap to a vertical one); a level
     arrow's label can rise into the room between the two circles, where
     their edges curve away. Fission ends in a point fissionReach px up and
     to one side of the state that splits. */
  const SERIES = {
    style: 'series', d: 80, boxW: 80, boxH: 80, unit: 50 * Math.SQRT2, rowGap: 100 * Math.SQRT2 - 80, vGap: 50, margin: 20,
    fissionReach: 100, labelH: 26, font: 10, lineH: 11.5, beside: 5,
    offsets: [0, -20, 20, -34, 34], flatOffsets: [0, -16, 16, -24, 24, -30, 30, -36, 36],
  };

  /* Modes whose arrow direction says what they are: in Z-A, beta-minus goes
     right, electron capture left, alpha down-left and IT straight down in
     the same cell. Their labels carry the share alone. */
  const PLAIN = new Set(['B-', 'EC+B+', 'EC', 'B+', 'A', 'IT']);

  /**
   * Where every box goes.
   *
   * @param {Object} chain - buildChain()
   * @param {Object} [g] - GEOM
   * @param {number[]} [grow] - extra height for each gap between rows, the
   *   one above the first row being 0 and the one below the last rows.length
   * @returns {{width: number, height: number, boxes: Map, cols: Array, rows: Array,
   *   bands: Array<{top: number, bottom: number}>, fissionX: number|null}}
   *   bands are those gaps: the free strips where labels go.
   */
  function layout(chain, g = GEOM, grow = []) {
    const members = chain.nodes.filter((n) => n.kind !== 'fission');
    const fissions = chain.nodes.filter((n) => n.kind === 'fission');
    const zs = members.map((n) => n.z);
    const zMin = Math.min(...zs), zMax = Math.max(...zs);
    const rowsA = [...new Set(members.map((n) => n.a))].sort((p, q) => q - p);
    /* Stacks: several states of one nuclide share a cell, isomers on top. */
    const cell = new Map();
    for (const n of members) {
      const k = `${n.z},${n.a}`;
      if (!cell.has(k)) cell.set(k, []);
      cell.get(k).push(n);
    }
    for (const list of cell.values()) list.sort((p, q) => q.k - p.k);
    const parentRow = new Map();
    const fissionByRow = new Map();
    for (const f of fissions) {
      const parent = chain.nodes.find((n) => n.key === f.parent);
      const a = parent ? parent.a : rowsA[0];
      parentRow.set(f.key, a);
      if (!fissionByRow.has(a)) fissionByRow.set(a, []);
      fissionByRow.get(a).push(f);
    }
    const rows = [];
    let y = g.top + (grow[0] || 0);
    rowsA.forEach((a, i) => {
      let stack = 1;
      for (const [k, list] of cell) if (+k.split(',')[1] === a) stack = Math.max(stack, list.length);
      stack = Math.max(stack, (fissionByRow.get(a) || []).length);
      const h = stack * g.boxH + (stack - 1) * g.vGap;
      rows.push({ a, y, h });
      y += h + (i < rowsA.length - 1 ? g.rowPad + (grow[i + 1] || 0) : 0);
    });
    const height = y + g.bottom + (grow[rowsA.length] || 0);
    /* The column heads take the top 24 px. */
    const bands = rows.map((r, i) => ({ top: i ? rows[i - 1].y + rows[i - 1].h : 24, bottom: r.y }));
    bands.push({ top: y, bottom: height - 2 });
    const colX = (z) => g.left + (z - zMin) * g.cellW;
    const cols = [];
    for (let z = zMin; z <= zMax; z++) cols.push({ z, x: colX(z) });
    const fissionX = fissions.length ? colX(zMax + 1) + g.fissionGap : null;
    const width = (fissionX !== null ? fissionX + g.cellW : colX(zMax + 1)) + g.right;
    const boxes = new Map();
    for (const [k, list] of cell) {
      const [z, a] = k.split(',').map(Number);
      const row = rows.find((r) => r.a === a);
      const h = list.length * g.boxH + (list.length - 1) * g.vGap;
      const y0 = row.y + (row.h - h) / 2;
      list.forEach((n, i) => boxes.set(n.key, { x: colX(z) + (g.cellW - g.boxW) / 2, y: y0 + i * (g.boxH + g.vGap), w: g.boxW, h: g.boxH }));
    }
    for (const [a, list] of fissionByRow) {
      const row = rows.find((r) => r.a === a);
      list.forEach((f, i) => boxes.set(f.key, { x: fissionX + (g.cellW - g.boxW) / 2, y: row.y + i * (g.boxH + g.vGap), w: g.boxW, h: g.boxH }));
    }
    /* The column heads and the row labels, where no label may go. */
    const reserved = [{ x: 0, y: 0, w: width, h: 24 }, { x: 0, y: 0, w: g.left - 2, h: height }];
    return { width, height, boxes, cols, rows, bands, fissionX, zMin, zMax, reserved };
  }

  /* The distance from (px, py) to the segment from (ax, ay) to (bx, by). */
  function segDist(ax, ay, bx, by, px, py) {
    const dx = bx - ax, dy = by - ay;
    const t = dx || dy ? Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy))) : 0;
    return Math.hypot(ax + t * dx - px, ay + t * dy - py);
  }

  /**
   * Where every circle goes in the series: Z - N across, so that alpha
   * decay goes straight down, beta-minus a step right and electron capture
   * a step left; one row for each mass number that holds a member, heaviest
   * at the top, as in the grid. States of one nuclide stand one above the
   * other, isomers on top. The same result as layout(), with `round` boxes.
   *
   * @param {Object} chain - buildChain()
   * @param {Object} [g] - SERIES
   * @param {number[]} [grow] - extra height for each gap between rows, as for layout()
   * @param {{left: number, right: number}} [side] - extra room at either side, for labels
   */
  function layoutSeries(chain, g = SERIES, grow = [], side = { left: 0, right: 0 }) {
    const D = g.d;
    const members = chain.nodes.filter((n) => n.kind !== 'fission');
    const fissions = chain.nodes.filter((n) => n.kind === 'fission');
    const cMin = Math.min(...members.map((n) => 2 * n.z - n.a));
    const rowsA = [...new Set(members.map((n) => n.a))].sort((p, q) => q - p);
    const cell = new Map();
    for (const n of members) {
      const k = `${n.z},${n.a}`;
      if (!cell.has(k)) cell.set(k, []);
      cell.get(k).push(n);
    }
    for (const list of cell.values()) list.sort((p, q) => q.k - p.k);
    const rows = [];
    let y = 0;
    rowsA.forEach((a, i) => {
      let stack = 1;
      for (const [k, list] of cell) if (+k.split(',')[1] === a) stack = Math.max(stack, list.length);
      const h = stack * D + (stack - 1) * g.vGap;
      rows.push({ a, y, h });
      y += h + (i < rowsA.length - 1 ? g.rowGap + (grow[i + 1] || 0) : 0);
    });
    const boxes = new Map();
    for (const [k, list] of cell) {
      const [z, a] = k.split(',').map(Number);
      const row = rows.find((r) => r.a === a);
      const h = list.length * D + (list.length - 1) * g.vGap;
      const y0 = row.y + (row.h - h) / 2;
      const x = (2 * z - a - cMin) * g.unit;
      list.forEach((n, i) => boxes.set(n.key, { x, y: y0 + i * (D + g.vGap), w: D, h: D, round: true }));
    }
    /* Fission ends in a point off the state that splits: up and to the
       right, as rdc.html draws it, or at the first other corner where the
       point and the way to it are clear of the circles and of the others. */
    const discs = [...boxes.values()];
    const points = [];
    for (const f of fissions) {
      const pb = boxes.get(f.parent);
      if (!pb) continue;
      const cx = pb.x + D / 2, cy = pb.y + D / 2, s = g.fissionReach;
      let best = null;
      for (const [sx, sy] of [[1, -1], [-1, -1], [1, 1], [-1, 1]]) {
        const px = cx + sx * s, py = cy + sy * s;
        let bad = 0;
        for (const b of discs) {
          if (b === pb) continue;
          const bx = b.x + D / 2, by = b.y + D / 2;
          if (Math.hypot(px - bx, py - by) < D / 2 + 18) bad += 10;
          else if (segDist(cx, cy, px, py, bx, by) < D / 2 + 6) bad++;
        }
        for (const [qx, qy] of points) if (Math.hypot(px - qx, py - qy) < 30) bad += 10;
        if (!best || bad < best.bad) best = { px, py, bad };
        if (!bad) break;
      }
      points.push([best.px, best.py]);
      boxes.set(f.key, { x: best.px - 3, y: best.py - 3, w: 6, h: 6 });
    }
    /* Everything moved so that the drawing starts at its margin: a point of
       fission can stand above the first row or left of the first column. */
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const b of boxes.values()) {
      x0 = Math.min(x0, b.x); y0 = Math.min(y0, b.y);
      x1 = Math.max(x1, b.x + b.w); y1 = Math.max(y1, b.y + b.h);
    }
    const dx = g.margin + side.left - x0, dy = g.margin + (grow[0] || 0) - y0;
    for (const b of boxes.values()) { b.x += dx; b.y += dy; }
    for (const r of rows) r.y += dy;
    const width = x1 + dx + g.margin + side.right;
    const height = y1 + dy + g.margin + (grow[rowsA.length] || 0);
    const last = rows[rows.length - 1];
    const bands = rows.map((r, i) => ({ top: i ? rows[i - 1].y + rows[i - 1].h : 2, bottom: r.y }));
    bands.push({ top: last.y + last.h, bottom: height - 2 });
    return { width, height, boxes, cols: [], rows, bands, fissionX: null, reserved: [] };
  }

  /* Where the segment from a box's centre towards (tx, ty) leaves the box,
     or the circle of a round one. */
  function edgePoint(b, tx, ty, pad = 2) {
    const cx = b.x + b.w / 2, cy = b.y + b.h / 2;
    const dx = tx - cx, dy = ty - cy;
    if (!dx && !dy) return [cx, cy];
    if (b.round) {
      const t = (b.w / 2 + pad) / Math.hypot(dx, dy);
      return [cx + dx * t, cy + dy * t];
    }
    const sx = dx ? (b.w / 2 + pad) / Math.abs(dx) : Infinity;
    const sy = dy ? (b.h / 2 + pad) / Math.abs(dy) : Infinity;
    const t = Math.min(sx, sy);
    return [cx + dx * t, cy + dy * t];
  }

  const f1 = (v) => Math.round(v * 10) / 10;
  const bezier = (P0, Q, P1, t) => [
    (1 - t) * (1 - t) * P0[0] + 2 * (1 - t) * t * Q[0] + t * t * P1[0],
    (1 - t) * (1 - t) * P0[1] + 2 * (1 - t) * t * Q[1] + t * t * P1[1],
  ];
  const tangent = (P0, Q, P1, t) => [
    2 * (1 - t) * (Q[0] - P0[0]) + 2 * t * (P1[0] - Q[0]),
    2 * (1 - t) * (Q[1] - P0[1]) + 2 * t * (P1[1] - Q[1]),
  ];

  /*
    The path of every arrow. A straight line where it is clear; where it
    would cut through another box, or run on top of an arrow already drawn,
    it bends -- a quadratic curve whose middle is pushed to one side of the
    straight line, a little more each try, until it is clear or the least
    crowded of the tries. The short arrows are routed first, so the long
    ones (cluster decays across the whole chain) bend around them rather
    than the other way round. Arrows between two states of one nuclide,
    stacked in a cell, stay straight.
  */
  /* How far the middle of a curve may be pushed aside, as a share of the
     arrow's length: a short arrow bends a little, a long one can swing wide. */
  const BENDS = [0, 0.1, -0.1, 0.18, -0.18, 0.27, -0.27, 0.38, -0.38, 0.5, -0.5];
  const SAMPLES = 24;

  /* A grid cell as one number, for the lookups the routing and the labels
     make by the million in a chain of a few hundred members. */
  const cellId = (i, j) => (i + 4096) * 65536 + (j + 4096);

  function routeEdges(chain, L) {
    const routes = new Map();
    const boxes = [...L.boxes.entries()].map(([key, b]) => ({ key, x: b.x - 4, y: b.y - 4, w: b.w + 8, h: b.h + 8 }));
    const centre = (b) => [b.x + b.w / 2, b.y + b.h / 2];
    /* Points of the arrows already placed, in 8 px cells, to find crowding quickly. */
    const grid = new Map();
    const cellKey = (x, y) => cellId(Math.floor(x / 8), Math.floor(y / 8));
    const crowded = (x, y) => {
      const cx = Math.floor(x / 8), cy = Math.floor(y / 8);
      for (let i = -1; i <= 1; i++) for (let j = -1; j <= 1; j++) {
        const list = grid.get(cellId(cx + i, cy + j));
        if (list && list.some(([u, v]) => Math.abs(u - x) < 6 && Math.abs(v - y) < 6)) return true;
      }
      return false;
    };
    const todo = chain.edges
      .map((e) => ({ e, b0: L.boxes.get(e.from.key), b1: L.boxes.get(e.to.key) }))
      .filter((x) => x.b0 && x.b1)
      .map((x) => ({ ...x, len: Math.hypot(centre(x.b1)[0] - centre(x.b0)[0], centre(x.b1)[1] - centre(x.b0)[1]) }))
      /* Shortest first; of two arrows between the same boxes, the direct one,
         so the one through a left-out isomer is the one that bends. */
      .sort((p, q) => (p.len - q.len) || (p.e.via.length - q.e.via.length));
    for (const { e, b0, b1 } of todo) {
      const c0 = centre(b0), c1 = centre(b1);
      const dx = c1[0] - c0[0], dy = c1[1] - c0[1];
      const len = Math.hypot(dx, dy) || 1;
      const nx = -dy / len, ny = dx / len;
      const stacked = e.from.z === e.to.z && e.from.a === e.to.a;
      let best = null;
      const tries = stacked ? [0] : BENDS.map((f) => (f ? Math.sign(f) * Math.min(170, Math.max(12, Math.abs(f) * len)) : 0));
      for (const bend of tries) {
        const M = [(c0[0] + c1[0]) / 2 + nx * bend, (c0[1] + c1[1]) / 2 + ny * bend];
        const P0 = edgePoint(b0, M[0], M[1]);
        const P1 = edgePoint(b1, M[0], M[1], 3);
        /* The control point that puts the middle of the curve at M. */
        const Q = [2 * M[0] - (P0[0] + P1[0]) / 2, 2 * M[1] - (P0[1] + P1[1]) / 2];
        const pts = [];
        for (let i = 0; i <= SAMPLES; i++) pts.push(bezier(P0, Q, P1, i / SAMPLES));
        let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
        for (const [x, y] of pts) { if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }
        let hits = 0;
        for (const r of boxes) {
          /* A box clear of the curve's bounding box holds none of its points. */
          if (r.x >= x1 || r.x + r.w <= x0 || r.y >= y1 || r.y + r.h <= y0) continue;
          if (r.key === e.from.key || r.key === e.to.key) continue;
          if (pts.some(([x, y]) => x > r.x && x < r.x + r.w && y > r.y && y < r.y + r.h)) hits++;
        }
        /* Crossing another arrow is fine; running along one for a stretch is
           not, and a few close points are what a crossing looks like. */
        let near = 0;
        for (let i = 2; i < pts.length - 2; i++) if (crowded(pts[i][0], pts[i][1])) near++;
        const along = Math.max(0, near - 4);
        const cost = hits * 1000 + along * 2 + (Math.abs(bend) / len) * 12;
        if (!best || cost < best.cost) best = { cost, P0, Q, P1, bend, pts };
        if (!hits && !along) break;
      }
      for (const [x, y] of best.pts.slice(2, -2)) {
        const k = cellKey(x, y);
        if (!grid.has(k)) grid.set(k, []);
        grid.get(k).push([x, y]);
      }
      routes.set(e.key, best);
    }
    return routes;
  }

  /*
    The arrows of the series. Its circles stand on a lattice, and an arrow
    often finds another circle right in its way: alpha decay keeps to its
    column, and a member a row or two further down that column stands on
    the line. The arrow bends as in the grid, but the bend may also come
    early or late -- the curve's control point a fifth, a third, two thirds
    or four fifths of the way along -- so that it can clear a circle near
    one end and be back in line before the next row, and a long arrow (a
    cluster decay across the chain) may swing out by a quarter of its
    length. Where no try is clear it takes the one that cuts least deep into
    the circles in its way: an arrow that grazes the edge of a circle is
    still seen to pass it; one through the middle looks as if it ended there.
  */
  const SERIES_BENDS = [0.1, -0.1, 0.18, -0.18, 0.27, -0.27, 0.38, -0.38, 0.5, -0.5, 0.65, -0.65];
  const SERIES_AT = [0.5, 1 / 3, 2 / 3, 0.2, 0.8];

  function routeSeries(chain, L) {
    const routes = new Map();
    /* Every circle 4 px wider; the end of a fission arrow, a point, 8. */
    const discs = [...L.boxes.entries()].map(([key, b]) => ({ key, cx: b.x + b.w / 2, cy: b.y + b.h / 2, r: (b.round ? b.w / 2 : 4) + 4 }));
    const centre = (b) => [b.x + b.w / 2, b.y + b.h / 2];
    const grid = new Map();
    const cellKey = (x, y) => cellId(Math.floor(x / 8), Math.floor(y / 8));
    const crowded = (x, y) => {
      const cx = Math.floor(x / 8), cy = Math.floor(y / 8);
      for (let i = -1; i <= 1; i++) for (let j = -1; j <= 1; j++) {
        const list = grid.get(cellId(cx + i, cy + j));
        if (list && list.some(([u, v]) => Math.abs(u - x) < 6 && Math.abs(v - y) < 6)) return true;
      }
      return false;
    };
    const todo = chain.edges
      .map((e) => ({ e, b0: L.boxes.get(e.from.key), b1: L.boxes.get(e.to.key) }))
      .filter((x) => x.b0 && x.b1)
      .map((x) => ({ ...x, len: Math.hypot(centre(x.b1)[0] - centre(x.b0)[0], centre(x.b1)[1] - centre(x.b0)[1]) }))
      .sort((p, q) => (p.len - q.len) || (p.e.via.length - q.e.via.length));
    for (const { e, b0, b1, len: span } of todo) {
      const c0 = centre(b0), c1 = centre(b1);
      const dx = c1[0] - c0[0], dy = c1[1] - c0[1];
      const len = span || 1;
      const nx = -dy / len, ny = dx / len;
      const stacked = e.from.z === e.to.z && e.from.a === e.to.a;
      /* Points about 10 px apart, so that none slips past a circle between two. */
      const n = Math.max(SAMPLES, Math.ceil(len / 10));
      const tries = [[0, 0.5]];
      for (const f of SERIES_BENDS) for (const at of SERIES_AT) tries.push([Math.sign(f) * Math.min(Math.max(220, len * 0.25), Math.max(12, Math.abs(f) * len)), at]);
      let best = null;
      for (const [bend, at] of tries) {
        /* Between two states of one nuclide the arrow stays straight unless
           a third stands between them (an IT from m2 past m1). */
        if (bend && stacked && !best.hits) break;
        let P0, P1, Q;
        if (!bend) {
          P0 = edgePoint(b0, c1[0], c1[1]);
          P1 = edgePoint(b1, c0[0], c0[1], 3);
          Q = [(P0[0] + P1[0]) / 2, (P0[1] + P1[1]) / 2];
        } else {
          /* At the middle, a control point twice the bend aside puts the
             middle of the curve the bend aside. The curve leaves and meets
             the circles heading for it. */
          Q = [c0[0] + dx * at + nx * 2 * bend, c0[1] + dy * at + ny * 2 * bend];
          P0 = edgePoint(b0, Q[0], Q[1]);
          P1 = edgePoint(b1, Q[0], Q[1], 3);
        }
        const pts = [];
        for (let i = 0; i <= n; i++) pts.push(bezier(P0, Q, P1, i / n));
        let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
        for (const [x, y] of pts) { if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }
        let hits = 0, depth = 0;
        for (const d of discs) {
          if (d.cx - d.r >= x1 || d.cx + d.r <= x0 || d.cy - d.r >= y1 || d.cy + d.r <= y0) continue;
          if (d.key === e.from.key || d.key === e.to.key) continue;
          let m = Infinity;
          for (const [x, y] of pts) { const q = Math.hypot(x - d.cx, y - d.cy); if (q < m) m = q; }
          if (m < d.r) { hits++; depth += d.r - m; }
        }
        let near = 0;
        for (let i = 2; i < pts.length - 2; i++) if (crowded(pts[i][0], pts[i][1])) near++;
        const along = Math.max(0, near - 4);
        const cost = hits * 300 + depth * 20 + along * 2 + (Math.abs(bend) / len) * 12 + (at === 0.5 ? 0 : 1);
        if (!best || cost < best.cost) best = { cost, hits, P0, Q, P1, bend, pts };
        if (!hits && !along) break;
      }
      for (const [x, y] of best.pts.slice(2, -2)) {
        const k = cellKey(x, y);
        if (!grid.has(k)) grid.set(k, []);
        grid.get(k).push([x, y]);
      }
      routes.set(e.key, best);
    }
    return routes;
  }

  /*
    A curve of the series may swing out past the circles at the edge of the
    drawing: the drawing grows to hold it, all of it moved right or down by
    what stands out on the left or at the top.
  */
  function holdRoutes(L, routes) {
    let x0 = 0, y0 = 0, x1 = L.width, y1 = L.height;
    for (const rt of routes.values()) {
      for (const [x, y] of rt.pts) {
        x0 = Math.min(x0, x - 8); y0 = Math.min(y0, y - 8);
        x1 = Math.max(x1, x + 8); y1 = Math.max(y1, y + 8);
      }
    }
    const sx = -x0, sy = -y0;
    if (!sx && !sy && x1 === L.width && y1 === L.height) return;
    const move = (p) => { p[0] += sx; p[1] += sy; };
    for (const b of L.boxes.values()) { b.x += sx; b.y += sy; }
    for (const r of L.rows) r.y += sy;
    for (const rt of routes.values()) { move(rt.P0); move(rt.Q); move(rt.P1); rt.pts.forEach(move); }
    L.width = x1 + sx;
    L.height = y1 + sy;
    const last = L.rows[L.rows.length - 1];
    L.bands = L.rows.map((r, i) => ({ top: i ? L.rows[i - 1].y + L.rows[i - 1].h : 2, bottom: r.y }));
    L.bands.push({ top: last.y + last.h, bottom: L.height - 2 });
  }

  /* A label is a line of 11 px text in a rounded box 16 px high (GEOM.labelH)
     -- in the series, two lines of 10 px, 26 high. It may sit up to REACH px
     from its arrow; farther off it could be taken for another's. */
  const REACH = 30;

  /* The text on an arrow, or '' for none. A branch that takes every decay
     (100 %) has no share to show -- the direction of the arrow already says
     alpha, beta-minus or electron capture, and the table gives it -- but an
     arrow through a left-out isomer still says which. */
  /** An arrow's share as text: "99.69 %", "≤ 20 %", or "≥ 83.2 %" where part of it has no percentage. */
  function shareText(e, which = 'pct') {
    if (e[which] === null) return '?';
    const more = which === 'pct' ? e.more : e.skippedMore;
    return C.sharePct(e[which], e.limit || (more ? '>=' : ''));
  }

  function labelText(e) {
    const p = e.pct;
    const whole = p !== null && p >= 99.995 && !e.inferred && !e.limit;
    /* An arrow that jumps over left-out members says which instead of how
       it began: its direction is no decay's own. */
    const via = viaNames(e);
    return [via || PLAIN.has(e.mode) ? '' : C.modeText(e.mode), whole ? '' : shareText(e), via ? `via ${via}` : '']
      .filter(Boolean).join(' ') + (e.inferred ? '*' : '');
  }

  /* The label of an arrow in the series: its mode over its share, as
     rdc.html writes them, 100 % and all -- or, for an arrow that jumps over
     left-out members, which ones over the share. */
  function seriesLines(e) {
    const via = viaNames(e);
    return [via ? `via ${via}` : C.modeText(e.mode), shareText(e) + (e.inferred ? '*' : '')];
  }

  /* A label as placeLabels() takes it: its text, its lines and its width,
     or null for an arrow that has none. */
  function labelFor(e, g) {
    if (g.style === 'series') {
      const lines = seriesLines(e);
      return { txt: lines.join(' '), lines, w: Math.ceil(Math.max(...lines.map((t) => textWidth(t, g.font)))) + 8 };
    }
    const txt = labelText(e);
    return txt ? { txt, lines: [txt], w: Math.ceil(textWidth(txt, 11)) + 12 } : null;
  }

  /* How wide a text comes out, superscripts and all, in the drawing's font. */
  let measurer;
  function textWidth(text, size, bold) {
    if (measurer === undefined) {
      try { measurer = document.createElement('canvas').getContext('2d'); } catch (err) { measurer = null; }
    }
    let w = 0;
    for (const r of C.supRuns(text)) {
      const px = r.sup ? Math.round(size * 0.72) : size;
      if (measurer) { measurer.font = `${bold ? 'bold ' : ''}${px}px verdana, sans-serif`; w += measurer.measureText(r.t).width; }
      else w += r.t.length * px * (bold ? 0.7 : 0.62);
    }
    return w;
  }

  /*
    Places a label w wide might go, the likeliest first: on the arrow and to
    either side of it; for an arrow between stacked states, beside the stack;
    then along each gap between rows that the arrow crosses or runs beside,
    in lanes a label high, slid either way from where the arrow meets the gap.
  */
  function candidates(rt, w, pts, L, g = GEOM) {
    const { P0, Q, P1, bend } = rt;
    const h = g.labelH;
    const out = [];
    const at = (cx, cy) => out.push({ x: cx - w / 2, y: cy - h / 2, w, h });
    const flat = !bend && Math.abs(P1[1] - P0[1]) < 2;
    const upright = !bend && Math.abs(P1[0] - P0[0]) < 2;
    for (const off of flat ? g.flatOffsets : g.offsets) {
      for (const t of [0.5, 0.4, 0.6, 0.3, 0.7, 0.22, 0.78]) {
        const [bx, by] = bezier(P0, Q, P1, t);
        const [tx, ty] = tangent(P0, Q, P1, t);
        const tl = Math.hypot(tx, ty) || 1;
        at(bx - (ty / tl) * off, by + (tx / tl) * off);
      }
    }
    if (upright) {
      const side = g.beside !== undefined ? w / 2 + g.beside : g.boxW / 2 + w / 2 + 4;
      for (const t of [0.5, 0.3, 0.7]) { const y = P0[1] + (P1[1] - P0[1]) * t; at(P0[0] + side, y); at(P0[0] - side, y); }
    }
    const slide = [0];
    for (let s = 6; s <= w / 2 + REACH; s += 6) slide.push(-s, s);
    /* Just above and below the two boxes of a level arrow: in a row where
       other states are stacked, that is room inside the row. */
    if (flat) {
      const dy = g.boxH / 2 + 3 + h / 2;
      for (const y of [P0[1] - dy, P0[1] + dy]) for (const s of slide) at((P0[0] + P1[0]) / 2 + s, y);
    }
    const mid = Math.floor(pts.length / 2);
    for (const band of L.bands) {
      const bh = band.bottom - band.top;
      if (bh < h + 2) continue;
      const n = Math.max(1, Math.floor((bh - 4) / (h + 2)));
      const lanes = n === 1 ? [(band.top + band.bottom) / 2]
        : Array.from({ length: n }, (_, i) => band.top + 2 + h / 2 + i * (bh - 4 - h) / (n - 1));
      /* Where the arrow meets the gap: where it crosses the gap's middle, or,
         for an arrow that stays out of the gap, its point nearest it. */
      const yc = (band.top + band.bottom) / 2;
      const xs = [];
      for (let i = 1; i < pts.length; i++) {
        const [x0, y0] = pts[i - 1], [x1, y1] = pts[i];
        if (y0 !== y1 && (y0 - yc) * (y1 - yc) <= 0) xs.push(x0 + (x1 - x0) * (yc - y0) / (y1 - y0));
      }
      if (!xs.length) {
        let bi = 0, bd = Infinity;
        pts.forEach(([, y], i) => {
          const d = (y < band.top ? band.top - y : y > band.bottom ? y - band.bottom : 0) + Math.abs(i - mid) * 1e-3;
          if (d < bd) { bd = d; bi = i; }
        });
        if (bd > REACH + h) continue;
        xs.push(pts[bi][0]);
      }
      for (const x of xs) for (const y of lanes) for (const s of slide) at(x + s, y);
    }
    return out;
  }

  /*
    Where each label goes: clear of every box and every other label, as near
    its own arrow as it can be, and hiding as little of the other arrows as
    it can. The labels with the fewest free places go first. One with nowhere
    free within REACH of its arrow takes the place that covers least, and
    the gap between rows it wanted is reported, so that render() can widen
    that gap and try again.

    @returns {{spots: Map, missed: number[]}} spots by edge key: {x, y, w, h, txt, lines};
      missed: for each label that found no free place, the index of its gap.
  */
  function placeLabels(chain, L, routes, g = GEOM) {
    const fixed = [];
    /* A circle is its square, and r: a label may take the square's corners. */
    for (const b of L.boxes.values()) fixed.push(b.round ? { x: b.x - 2, y: b.y - 2, w: b.w + 4, h: b.h + 4, r: b.w / 2 + 2 } : { x: b.x - 2, y: b.y - 2, w: b.w + 4, h: b.h + 4 });
    /* The column heads and row labels are not free either. */
    fixed.push(...L.reserved);
    const inside = (r) => r.x >= 2 && r.y >= 2 && r.x + r.w <= L.width - 2 && r.y + r.h <= L.height - 2;
    /* Within reach of a circle's centre: the point of the rectangle nearest it. */
    const touches = (r, t) => {
      const cx = t.x + t.w / 2, cy = t.y + t.h / 2;
      return Math.hypot(Math.max(r.x, Math.min(cx, r.x + r.w)) - cx, Math.max(r.y, Math.min(cy, r.y + r.h)) - cy) < t.r;
    };
    const hit = (r, t) => r.x < t.x + t.w && r.x + r.w > t.x && r.y < t.y + t.h && r.y + r.h > t.y && (!t.r || touches(r, t));
    /* The fixed places filed in 64 px cells: two that overlap share a cell. */
    const FIX = 64;
    const fixedAt = new Map();
    for (const t of fixed) {
      for (let i = Math.floor(t.x / FIX); i <= Math.floor((t.x + t.w) / FIX); i++) {
        for (let j = Math.floor(t.y / FIX); j <= Math.floor((t.y + t.h) / FIX); j++) {
          const k = cellId(i, j);
          if (!fixedAt.has(k)) fixedAt.set(k, []);
          fixedAt.get(k).push(t);
        }
      }
    }
    const blocked = (r) => {
      for (let i = Math.floor(r.x / FIX); i <= Math.floor((r.x + r.w) / FIX); i++) {
        for (let j = Math.floor(r.y / FIX); j <= Math.floor((r.y + r.h) / FIX); j++) {
          const list = fixedAt.get(cellId(i, j));
          if (list && list.some((t) => hit(r, t))) return true;
        }
      }
      return false;
    };
    /* Two labels on one lane keep a little apart. */
    const crowds = (r, t) => r.x < t.x + t.w + 3 && r.x + r.w + 3 > t.x && r.y < t.y + t.h && r.y + r.h > t.y;
    const overlap = (r, t) => Math.max(0, Math.min(r.x + r.w, t.x + t.w) - Math.max(r.x, t.x)) * Math.max(0, Math.min(r.y + r.h, t.y + t.h) - Math.max(r.y, t.y));

    /* Every arrow as points about 6 px apart, filed in 16 px cells. */
    const trace = new Map();
    const cells = new Map();
    for (const e of chain.edges) {
      const rt = routes.get(e.key);
      if (!rt) continue;
      const n = Math.max(8, Math.ceil(Math.hypot(rt.P1[0] - rt.P0[0], rt.P1[1] - rt.P0[1]) / 6));
      const pts = [];
      for (let i = 0; i <= n; i++) pts.push(bezier(rt.P0, rt.Q, rt.P1, i / n));
      trace.set(e.key, pts);
      for (const [x, y] of pts) {
        const k = cellId(Math.floor(x / 16), Math.floor(y / 16));
        if (!cells.has(k)) cells.set(k, []);
        cells.get(k).push([x, y, e.key]);
      }
    }
    /* How many points of the other arrows a label would hide. */
    const covers = (r, own) => {
      let n = 0;
      for (let i = Math.floor(r.x / 16); i <= Math.floor((r.x + r.w) / 16); i++) {
        for (let j = Math.floor(r.y / 16); j <= Math.floor((r.y + r.h) / 16); j++) {
          for (const [x, y, k] of cells.get(cellId(i, j)) || []) if (k !== own && x > r.x && x < r.x + r.w && y > r.y && y < r.y + r.h) n++;
        }
      }
      return n;
    };
    const distance = (r, pts) => {
      let d = Infinity;
      for (const [x, y] of pts) d = Math.min(d, Math.hypot(Math.max(r.x - x, 0, x - r.x - r.w), Math.max(r.y - y, 0, y - r.y - r.h)));
      return d;
    };
    const bandOf = (r) => {
      const cy = r.y + r.h / 2;
      let best = 0, bd = Infinity;
      L.bands.forEach((b, i) => { const d = cy < b.top ? b.top - cy : cy > b.bottom ? cy - b.bottom : 0; if (d < bd) { bd = d; best = i; } });
      return best;
    };

    /* For a label with no room, a free place just off the left or right of
       the drawing: room the series can make by widening it (arrange()). */
    const wide = { left: 0, right: 0 };
    const offSide = (job) => {
      for (const r of job.cands) {
        if (inside(r) || r.y < 2 || r.y + r.h > L.height - 2) continue;
        if (distance(r, job.pts) > REACH || blocked(r)) continue;
        if (r.x < 2) wide.left = Math.max(wide.left, Math.ceil(2 - r.x));
        else wide.right = Math.max(wide.right, Math.ceil(r.x + r.w - L.width + 2));
        return;
      }
    };
    const jobs = [];
    for (const e of chain.edges) {
      const rt = routes.get(e.key);
      const lab = rt ? labelFor(e, g) : null;
      if (!lab) continue;
      const { txt, lines } = lab;
      const pts = trace.get(e.key);
      const cands = candidates(rt, lab.w, pts, L, g);
      const free = [];
      cands.forEach((r, i) => {
        if (!inside(r) || blocked(r)) return;
        const d = distance(r, pts);
        if (d <= REACH) free.push({ r, cost: d + covers(r, e.key) * 3 + i * 0.01 });
      });
      free.sort((p, q) => p.cost - q.cost);
      jobs.push({ e, txt, lines, cands, free, pts });
    }
    jobs.sort((p, q) => p.free.length - q.free.length);
    const placed = [];
    const spots = new Map();
    const missed = [];
    for (const job of jobs) {
      const ok = job.free.find((f) => !placed.some((t) => crowds(f.r, t)));
      let spot = ok ? ok.r : null;
      if (!spot) {
        let best = Infinity;
        for (const r of job.cands) {
          if (!inside(r)) continue;
          const cost = fixed.reduce((t, q) => t + overlap(r, q) * 10, 0) + placed.reduce((t, q) => t + overlap(r, q), 0) + distance(r, job.pts);
          if (cost < best) { best = cost; spot = r; }
        }
        spot = spot || job.cands[0];
        missed.push(bandOf(job.free.length ? job.free[0].r : spot));
        offSide(job);
      }
      placed.push(spot);
      spots.set(job.e.key, { ...spot, txt: job.txt, lines: job.lines });
    }
    return { spots, missed, wide };
  }

  /*
    SVG text with its superscripts raised by dy and set smaller, rather than
    drawn as Unicode superscript characters (Verdana lacks most of them), or
    with baseline-shift (which Firefox ignores).
  */
  function richText(textEl, text, size) {
    const rise = Math.round(size * 0.4);
    let up = false;
    for (const r of C.supRuns(text)) {
      const t = el('tspan', {}, textEl);
      if (r.sup) { t.setAttribute('font-size', Math.round(size * 0.72)); t.setAttribute('dy', up ? 0 : -rise); up = true; }
      else if (up) { t.setAttribute('dy', rise); up = false; }
      t.textContent = r.t;
    }
  }

  function el(tag, attrs, parent) {
    const e = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs || {})) if (v !== undefined && v !== null) e.setAttribute(k, v);
    if (parent) parent.appendChild(e);
    return e;
  }

  /** Colours for one theme, read once per render so a saved file carries plain values. */
  function themeColours() {
    const css = getComputedStyle(document.documentElement);
    const v = (name, fb) => (css.getPropertyValue(name).trim() || fb);
    const theme = document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
    return {
      theme,
      bg: v('--nz-chart-bg', v('--bg-primary', '#ffffff')),
      ink: v('--text-primary', '#352921'),
      muted: v('--text-muted', '#786b5d'),
      line: v('--text-secondary', '#6b5d4f'),
      grid: v('--border-color', '#e0d7ce'),
      select: v('--nz-select', '#bb6c5d'),
      accent: v('--accent-line', '#bb7d37'),
      label: v('--bg-surface', '#fcf7f2'),
      /* What fills a circle of the series as a bucket: rdc.html's yellow. */
      bucket: v('--nz-bucket', theme === 'dark' ? '#5a4520' : '#fff4a3'),
      pal: C.PALETTE[theme],
    };
  }

  /*
    Lay out, route the arrows, place the labels; where a label found no
    room, widen the gap between rows it wanted by a lane and go again, up to
    three times, and keep the try that left the fewest without room -- so a
    crowded chain grows only where it is crowded. One lane more may not be
    enough: the labels of the level arrows take the lanes next to their
    rows, and those of the arrows crossing the gap need a third. Worked out
    once for each chain and kept: the panel's small copy and the big drawing
    are the same chain, and the parents of a heavy stable nuclide, a few
    hundred members, take a good part of a second. Kept for each way of
    drawing it, grid or series.
  */
  const arranged = new WeakMap();
  function arrange(chain, g = GEOM) {
    let kept = arranged.get(chain);
    if (!kept) { kept = new Map(); arranged.set(chain, kept); }
    let best = kept.get(g.style);
    if (best) return best;
    let grow = [];
    let side = { left: 0, right: 0 };
    for (let pass = 0; pass < 4; pass++) {
      let L, routes;
      if (g.style === 'series') {
        L = layoutSeries(chain, g, grow, side);
        routes = routeSeries(chain, L);
        holdRoutes(L, routes);
      } else {
        L = layout(chain, g, grow);
        routes = routeEdges(chain, L);
      }
      const labels = placeLabels(chain, L, routes, g);
      if (!best || labels.missed.length < best.labels.missed.length) best = { L, routes, labels };
      if (!labels.missed.length) break;
      grow = grow.slice();
      for (const b of new Set(labels.missed)) grow[b] = (grow[b] || 0) + g.labelH + 2;
      /* The series also widens itself where a label would fit just off its side. */
      if (g.style === 'series') side = { left: side.left + labels.wide.left, right: side.right + labels.wide.right };
    }
    kept.set(g.style, best);
    return best;
  }

  /**
   * Draw the chain into an <svg>.
   *
   * @param {SVGSVGElement} svg - emptied first
   * @param {Object} chain - buildChain()
   * @param {Object} [opt]
   * @param {string} [opt.style] - 'series' for circles as rdc.html draws them;
   *   anything else for the grid, Z across and A down
   * @param {string} [opt.bg] - the series: the colour of what the drawing
   *   stands on, for its background, its circles and its labels, so that it
   *   has no edge of its own. The grid keeps the chart's background.
   * @param {string} [opt.selected] - node key to ring as the one the panel shows
   * @param {function(Object)} [opt.onPick] - a box was clicked
   * @param {function(Object|null, MouseEvent)} [opt.onHover]
   * @returns {{width: number, height: number, root: Object|null, focus: Object|null}}
   *   root is the box of the start, focus the box around it and its daughters
   *   -- or, going up, its parents
   */
  function render(svg, chain, opt = {}) {
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    const series = opt.style === 'series';
    const { L, routes, labels } = arrange(chain, series ? SERIES : GEOM);
    const col = themeColours();
    if (series && opt.bg) col.bg = opt.bg;
    /* The series draws its arrows in ink, thin and all of one width, as
       rdc.html does; the grid's are thicker for the larger branches. */
    const lineCol = series ? col.ink : col.line;
    /* Marker ids must be unique in the document: the panel carries a small
       copy of the drawing beside the big one. */
    const mid = (svg.id || 'nzChain') + 'Arrow';
    svg.setAttribute('viewBox', `0 0 ${L.width} ${L.height}`);
    svg.setAttribute('width', L.width);
    svg.setAttribute('height', L.height);
    svg.setAttribute('font-family', 'verdana, sans-serif');
    el('rect', { x: 0, y: 0, width: L.width, height: L.height, fill: col.bg }, svg);

    const defs = el('defs', {}, svg);
    const marker = el('marker', { id: mid, viewBox: '0 0 10 10', refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: 'auto-start-reverse' }, defs);
    el('path', { d: 'M0,0 L10,5 L0,10 z', fill: lineCol }, marker);
    const markerHi = el('marker', { id: mid + 'Hi', viewBox: '0 0 10 10', refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: 'auto-start-reverse' }, defs);
    el('path', { d: 'M0,0 L10,5 L0,10 z', fill: col.select }, markerHi);

    /* The frame: element and Z over each column, A beside each row. The
       series has none: across, it is Z - N. */
    if (!series) {
      const frame = el('g', { 'font-size': 12, fill: col.muted }, svg);
      for (const c of L.cols) {
        const sym = C.ELEMENTS[c.z] ? C.ELEMENTS[c.z][0] : '';
        const t = el('text', { x: c.x + GEOM.cellW / 2, y: 18, 'text-anchor': 'middle' }, frame);
        t.textContent = `${sym} ${c.z}`;
        el('line', { x1: c.x, y1: GEOM.top - 6, x2: c.x, y2: L.bands[L.bands.length - 1].top, stroke: col.grid, 'stroke-width': 1 }, frame);
      }
      if (L.fissionX !== null) {
        const t = el('text', { x: L.fissionX + GEOM.cellW / 2, y: 18, 'text-anchor': 'middle' }, frame);
        t.textContent = 'fission';
      }
      for (const r of L.rows) {
        const t = el('text', { x: GEOM.left - 8, y: r.y + r.h / 2 + 4, 'text-anchor': 'end' }, frame);
        t.textContent = `A ${r.a}`;
      }
      const axis = el('text', { x: 6, y: 18, 'font-size': 10, 'font-weight': 600, fill: col.ink }, frame);
      axis.textContent = 'Z →';
    }

    /* Edges under the boxes, their labels over everything. */
    const edgeLayer = el('g', { fill: 'none' }, svg);
    const boxLayer = el('g', {}, svg);
    const labelLayer = el('g', { 'font-size': series ? SERIES.font : 11 }, svg);
    const edgeEls = new Map();
    for (const e of chain.edges) {
      const rt = routes.get(e.key);
      if (!rt) continue;
      const { P0, Q, P1, bend } = rt;
      const p = e.pct;
      const w = series ? 1.2 : p === null ? 1 : p >= 10 ? 2 : p >= 0.1 ? 1.5 : 1;
      const d = bend ? `M${f1(P0[0])},${f1(P0[1])} Q${f1(Q[0])},${f1(Q[1])} ${f1(P1[0])},${f1(P1[1])}` : `M${f1(P0[0])},${f1(P0[1])} L${f1(P1[0])},${f1(P1[1])}`;
      const path = el('path', {
        d, stroke: lineCol, 'stroke-width': w, 'marker-end': `url(#${mid})`,
        'stroke-dasharray': (e.inferred || p === null) ? '4 3' : null,
      }, edgeLayer);
      const about = edgeAbout(e);
      el('title', {}, path).textContent = C.asciiText(about);
      edgeEls.set(e.key, path);
      const spot = labels.spots.get(e.key);
      if (!spot) continue;
      const g = el('g', { class: 'nz-edge-label' }, labelLayer);
      if (series) {
        /* Two lines on the page's own colour, over the arrow, as rdc.html sets them. */
        el('rect', { x: f1(spot.x), y: f1(spot.y), width: f1(spot.w), height: spot.h, rx: 4, fill: col.bg, 'fill-opacity': 0.92 }, g);
        spot.lines.forEach((t, i) => richText(el('text', { x: f1(spot.x + spot.w / 2), y: f1(spot.y + 10.5 + i * SERIES.lineH), 'text-anchor': 'middle', fill: col.line }, g), t, SERIES.font));
      } else {
        el('rect', { x: f1(spot.x), y: f1(spot.y), width: f1(spot.w), height: spot.h, rx: 7, fill: col.label, 'fill-opacity': 0.95, stroke: col.grid, 'stroke-width': 0.8 }, g);
        richText(el('text', { x: f1(spot.x + spot.w / 2), y: f1(spot.y + 12), 'text-anchor': 'middle', fill: col.ink }, g), spot.txt, 11);
      }
      el('title', {}, g).textContent = C.asciiText(about);
    }

    let clips = 0;
    for (const n of chain.nodes) {
      const b = L.boxes.get(n.key);
      if (!b) continue;
      /* A point of fission in the series is nothing to tab to. */
      const g = series && n.kind === 'fission'
        ? el('g', { class: 'nz-node', 'data-key': n.key }, boxLayer)
        : el('g', { class: 'nz-node', tabindex: 0, 'data-key': n.key, role: 'button' }, boxLayer);
      if (series) seriesNode(g, n, b, col, chain, opt, `${svg.id || 'nzChain'}Clip${clips++}`, defs);
      else gridNode(g, n, b, col, chain, opt);
      const title = el('title', {}, g);
      title.textContent = C.asciiText(nodeTitle(n, chain));
      g.addEventListener('click', () => { if (opt.onPick) opt.onPick(n); });
      g.addEventListener('keydown', (ev) => { if ((ev.key === 'Enter' || ev.key === ' ') && opt.onPick) { ev.preventDefault(); opt.onPick(n); } });
      g.addEventListener('mouseenter', (ev) => {
        for (const e of n.in.concat(n.out)) {
          const line = edgeEls.get(e.key);
          if (line) { line.setAttribute('stroke', col.select); line.setAttribute('marker-end', `url(#${mid}Hi)`); line.parentNode.appendChild(line); }
        }
        if (opt.onHover) opt.onHover(n, ev);
      });
      g.addEventListener('mouseleave', (ev) => {
        for (const e of n.in.concat(n.out)) {
          const line = edgeEls.get(e.key);
          if (line) { line.setAttribute('stroke', lineCol); line.setAttribute('marker-end', `url(#${mid})`); }
        }
        if (opt.onHover) opt.onHover(null, ev);
      });
    }
    /* The start and where its own decays go -- or, going up, the parents
       it comes from: what the view should open on. */
    const rb = L.boxes.get(chain.root.key);
    let focus = rb ? { ...rb } : null;
    if (focus) {
      for (const e of chain.up ? chain.root.in : chain.root.out) {
        const b = L.boxes.get((chain.up ? e.from : e.to).key);
        if (!b) continue;
        const x0 = Math.min(focus.x, b.x), y0 = Math.min(focus.y, b.y);
        focus = { x: x0, y: y0, w: Math.max(focus.x + focus.w, b.x + b.w) - x0, h: Math.max(focus.y + focus.h, b.y + b.h) - y0 };
      }
    }
    return { width: L.width, height: L.height, root: rb ? { ...rb } : null, focus };
  }

  /* A state in the grid: a box in its half-life's colour, the name over the half-life. */
  function gridNode(g, n, b, col, chain, opt) {
    let fill, ink;
    if (n.kind === 'fission') { fill = col.pal.unknown; ink = C.inkOn(fill); }
    else if (n.kind === 'missing') { fill = 'none'; ink = col.ink; }
    else { fill = C.halfLifeColour(n.st, col.theme); ink = C.inkOn(fill); }
    el('rect', {
      x: b.x, y: b.y, width: b.w, height: b.h, rx: 5, fill,
      stroke: n.kind === 'missing' ? col.muted : 'none', 'stroke-dasharray': n.kind === 'missing' ? '4 3' : null,
    }, g);
    /* The bucket level of the Inventory tab, empty until setLevels() fills it. */
    if (n.kind !== 'missing') el('rect', { class: 'nz-level', x: b.x, y: b.y + b.h, width: b.w, height: 0, rx: 5, fill, visibility: 'hidden', 'pointer-events': 'none' }, g);
    g.dataset.fill = fill;
    g.dataset.ink = ink;
    if (n === chain.root || n.key === opt.selected) {
      el('rect', { x: b.x - 3, y: b.y - 3, width: b.w + 6, height: b.h + 6, rx: 7, fill: 'none', stroke: n === chain.root ? col.select : col.accent, 'stroke-width': 2.5 }, g);
    }
    const t1 = el('text', { x: b.x + b.w / 2, y: b.y + 17, 'text-anchor': 'middle', fill: ink, 'font-size': 14, 'font-weight': 600 }, g);
    const t2 = el('text', { x: b.x + b.w / 2, y: b.y + 33, 'text-anchor': 'middle', fill: ink, 'font-size': 11 }, g);
    if (n.kind === 'fission') {
      t1.textContent = 'fission';
      t2.textContent = 'SF';
    } else {
      const nm = C.name(n.z, n.a, n.k, n.nuc);
      if (nm.mass) {
        el('tspan', { 'font-size': 10, dy: -5 }, t1).textContent = nm.mass;
        el('tspan', { dy: 5 }, t1).textContent = nm.sym;
      } else {
        t1.textContent = nm.sym;
      }
      richText(t2, n.kind === 'missing' ? 'not in ENSDF' : C.halfLifeShort(n.st) || 'T½ unknown', 11);
    }
  }

  /*
    A state in the series, as rdc.html draws one: a circle, the mass number
    over the atomic number before the symbol, the half-life under them. The
    bucket of the Inventory tab is a level of yellow rising inside it. The
    end of a fission arrow is a point with nothing drawn -- the arrow and its
    label say what it is -- but something there to point at.
  */
  function seriesNode(g, n, b, col, chain, opt, clipId, defs) {
    const r = b.w / 2, cx = b.x + r, cy = b.y + r;
    if (n.kind === 'fission') {
      el('circle', { cx, cy, r: 8, fill: 'transparent' }, g);
      return;
    }
    const missing = n.kind === 'missing';
    const ink = missing ? col.muted : col.ink;
    el('circle', { class: 'nz-disc', cx, cy, r, fill: col.bg, stroke: ink, 'stroke-width': missing ? 1.2 : 1.6, 'stroke-dasharray': missing ? '4 3' : null }, g);
    if (!missing) {
      const clip = el('clipPath', { id: clipId }, defs);
      el('circle', { cx, cy, r: r - 0.8 }, clip);
      el('rect', { class: 'nz-level', x: b.x, y: b.y + b.h, width: b.w, height: 0, fill: col.bucket, stroke: col.ink, 'stroke-width': 0.6, 'clip-path': `url(#${clipId})`, visibility: 'hidden', 'pointer-events': 'none' }, g);
    }
    if (n === chain.root || n.key === opt.selected) {
      el('circle', { cx, cy, r: r + 4, fill: 'none', stroke: n === chain.root ? col.select : col.accent, 'stroke-width': 2.5 }, g);
    }
    /* The symbol as large as fits beside the mass number: 26 px, less for
       a long mass number and a wide symbol (²⁵⁴ᵐ²Md). */
    const nm = C.name(n.z, n.a, n.k, n.nuc);
    const room = 2 * r - 14;
    const side = nm.mass ? Math.max(textWidth(nm.mass, 10), textWidth(String(n.z), 10)) + 2 : 0;
    let size = 26;
    const wide = textWidth(nm.sym, size, true);
    if (side + wide > room) size = Math.max(12, Math.floor((size * (room - side)) / wide));
    const x0 = cx - (side + textWidth(nm.sym, size, true)) / 2;
    const base = cy + 1;
    if (nm.mass) {
      /* The mass number's top level with the symbol's, the atomic number on its line. */
      el('text', { x: f1(x0 + side - 2), y: f1(base - 0.73 * (size - 10)), 'text-anchor': 'end', fill: ink, 'font-size': 10 }, g).textContent = nm.mass;
      el('text', { x: f1(x0 + side - 2), y: f1(base), 'text-anchor': 'end', fill: ink, 'font-size': 10 }, g).textContent = String(n.z);
    }
    el('text', { x: f1(x0 + side), y: f1(base), fill: ink, 'font-size': size, 'font-weight': 700 }, g).textContent = nm.sym;
    const life = missing ? 'not in ENSDF' : C.halfLifeShort(n.st) || 'T½ unknown';
    let ls = 10;
    const lw = textWidth(life, ls);
    if (lw > room) ls = Math.max(7, Math.floor((ls * room * 10) / lw) / 10);
    richText(el('text', { x: f1(cx), y: f1(cy + 19), 'text-anchor': 'middle', fill: ink, 'font-size': ls }, g), life, ls);
  }

  /**
   * The left-out members an arrow jumps over, for its label: those of its
   * likeliest route, up to three by name and a longer run by its first and
   * last -- "²³⁴Th, ²³⁴ᵐPa", "²²²Rn … ²¹⁴Po". Empty for a plain arrow.
   */
  function viaNames(e) {
    const names = (e.via || []).map((x) => x.name);
    return names.length <= 3 ? names.join(', ') : `${names[0]} … ${names[names.length - 1]}`;
  }

  /* The left-out members behind an arrow other than those of its likeliest route. */
  const others = (e) => (e.skipped || []).filter((s) => !(e.via || []).some((v) => v.key === s.key)).map((s) => s.name);

  /**
   * The left-out members behind an arrow, for the table: "via ²³⁴Th, ²³⁴ᵐPa
   * (also ²³⁴Pa)" for an arrow that jumps over them, "94.7 % via ¹³⁷ᵐBa" for
   * the part of a plain arrow that went through an isomer's IT. Empty for a
   * plain branch.
   */
  function viaText(e) {
    const skipped = e.skipped || [];
    if ((e.via || []).length) {
      const also = others(e);
      return `via ${e.via.map((x) => x.name).join(', ')}${also.length ? ` (also ${also.join(', ')})` : ''}`;
    }
    return skipped.length ? `${shareText(e, 'skippedPct')} via ${skipped.map((x) => x.name).join(', ')}` : '';
  }

  /** What an arrow stands for, for its tooltip. */
  function edgeAbout(e) {
    const from = nodeName(e.from), to = nodeName(e.to);
    const tail = `${e.limit ? ' (the evaluators give a limit)' : ''}${e.inferred ? ' — not given in ENSDF; inferred' : ''}`;
    const life = (x) => x.t || 'T½ unknown';
    if ((e.via || []).length) {
      /* 238U to 234U: by α to 234Th (24.1 d), β⁻ to 234mPa (1.16 min), β⁻ to 234U. */
      const hops = e.via.map((x, i) => `${C.modeText(i ? e.via[i - 1].mode : e.mode)} to ${x.name} (${life(x)})`);
      hops.push(`${C.modeText(e.via[e.via.length - 1].mode)} to ${to}`);
      const also = others(e);
      return `${from} to ${to}: ${shareText(e)} of the decays of ${from}, ${also.length ? 'most ' : ''}by ${hops.join(', ')}. Left out: ${e.via.map((x) => x.name).join(', ')}${also.length ? `, and on rarer ways ${also.join(', ')}` : ''}${tail}`;
    }
    const skipped = e.skipped || [];
    const step = (x) => `${x.name} (${x.e} keV, ${life(x)}; left out), which decays by ${C.modeText(x.mode)}${x.inferred ? ' (assumed: ENSDF gives none)' : ''}`;
    const through = skipped.length ? `, ${e.skippedPct === e.pct ? 'all' : shareText(e, 'skippedPct')} through ${skipped.map(step).join(', then ')}` : '';
    return `${C.modeMeaning(e.mode) || C.modeText(e.mode)}: ${shareText(e)} of the decays of ${from}${through}${tail}`;
  }

  function nodeName(n) {
    if (n.kind === 'fission') return 'fission';
    return C.plainName(n.z, n.a, n.k, n.nuc);
  }

  /* A box's tooltip. Going down, the share is of the first nuclide's
     decays; going up, of the member's own decays that reach the start. */
  function nodeTitle(n, chain) {
    if (n.kind === 'fission') return 'Spontaneous fission: the chain ends in fission fragments.';
    const nm = C.plainName(n.z, n.a, n.k, n.nuc);
    if (n.kind === 'missing') return `${nm}: no adopted data for this nuclide in the database.`;
    const life = n.st.st ? 'stable' : `T½ ${C.halfLifeText(n.st, true)}`;
    const head = `${nm}${n.k > 0 ? ` (${n.st.e} keV)` : ''}: ${life}`;
    if (chain && chain.up) {
      if (n === chain.root) return `${head}; the parents drawn are those that decay to it.`;
      const share = n.cumUnknown && !n.cum ? 'a share not known' : `${C.pctText(n.cum * 100)}${n.cumUnknown ? ' or more' : ''}`;
      return `${head}; ${share} of its decays reach ${nodeName(chain.root)}.`;
    }
    const reached = n.cumUnknown && !n.cum ? 'share not known' : `${C.pctText(n.cum * 100)} of the decays of the first nuclide pass through here`;
    return `${head}; ${reached}.`;
  }

  /**
   * Fill each box as a bucket to its share of the whole, for the Inventory
   * tab: levels maps a node key to 0 .. 1; null puts the boxes back. A box in
   * bucket mode keeps its colour as an outline and a faint fill, with the
   * full colour rising from the bottom, and its text takes a halo so it reads
   * over either. A circle of the series fills with yellow, as in rdc.html.
   */
  function setLevels(svg, levels) {
    const css = getComputedStyle(document.documentElement);
    const halo = css.getPropertyValue('--bg-surface').trim() || '#fcf7f2';
    const ink = css.getPropertyValue('--text-primary').trim() || '#352921';
    svg.querySelectorAll('.nz-node').forEach((g) => {
      const base = g.querySelector('rect');
      const lv = g.querySelector('.nz-level');
      if (!lv) return;
      /* A circle of the series keeps its look: the level rises inside it. */
      const disc = g.querySelector('.nz-disc');
      if (disc) {
        const f = levels ? Math.max(0, Math.min(1, levels.get(g.dataset.key) || 0)) : 0;
        const cy = +disc.getAttribute('cy'), r = +disc.getAttribute('r');
        lv.setAttribute('y', (cy + r - 2 * r * f).toFixed(1));
        lv.setAttribute('height', (2 * r * f).toFixed(1));
        lv.setAttribute('visibility', f > 0.004 ? 'visible' : 'hidden');
        return;
      }
      const texts = g.querySelectorAll('text');
      if (!levels) {
        base.removeAttribute('fill-opacity');
        base.setAttribute('stroke', 'none');
        lv.setAttribute('visibility', 'hidden');
        texts.forEach((t) => { t.setAttribute('fill', g.dataset.ink); t.removeAttribute('stroke'); t.removeAttribute('stroke-width'); t.removeAttribute('paint-order'); });
        return;
      }
      const f = Math.max(0, Math.min(1, levels.get(g.dataset.key) || 0));
      const y = +base.getAttribute('y'), h = +base.getAttribute('height');
      base.setAttribute('fill-opacity', 0.16);
      base.setAttribute('stroke', g.dataset.fill);
      base.setAttribute('stroke-width', 1.2);
      lv.setAttribute('y', (y + h * (1 - f)).toFixed(1));
      lv.setAttribute('height', (h * f).toFixed(1));
      lv.setAttribute('visibility', f > 0.004 ? 'visible' : 'hidden');
      texts.forEach((t) => {
        t.setAttribute('fill', ink);
        t.setAttribute('stroke', halo);
        t.setAttribute('stroke-width', 3);
        t.setAttribute('stroke-linejoin', 'round');
        t.setAttribute('paint-order', 'stroke');
      });
    });
  }

  /** Ring one box (by node key) as the member picked out elsewhere, or none. */
  function setHot(svg, key) {
    svg.querySelectorAll('.nz-hot-ring').forEach((r) => r.remove());
    if (!key) return;
    const g = [...svg.querySelectorAll('.nz-node')].find((x) => x.dataset.key === key);
    if (!g) return;
    const css = getComputedStyle(document.documentElement);
    const disc = g.querySelector('.nz-disc');
    if (disc) {
      g.appendChild(el('circle', {
        class: 'nz-hot-ring', cx: disc.getAttribute('cx'), cy: disc.getAttribute('cy'), r: +disc.getAttribute('r') + 7,
        fill: 'none', stroke: css.getPropertyValue('--accent-line').trim() || '#bb7d37', 'stroke-width': 3, 'pointer-events': 'none',
      }));
      return;
    }
    const b = g.querySelector('rect');
    if (!b) return;
    const ring = el('rect', {
      class: 'nz-hot-ring', x: +b.getAttribute('x') - 4, y: +b.getAttribute('y') - 4, width: +b.getAttribute('width') + 8, height: +b.getAttribute('height') + 8,
      rx: 8, fill: 'none', stroke: css.getPropertyValue('--accent-line').trim() || '#bb7d37', 'stroke-width': 3, 'pointer-events': 'none',
    });
    g.appendChild(ring);
  }

  /** The drawing as a stand-alone SVG file, at its own size however it is zoomed on screen. */
  function svgFile(svg) {
    const copy = svg.cloneNode(true);
    copy.setAttribute('xmlns', NS);
    const vb = (svg.getAttribute('viewBox') || '').split(' ').map(Number);
    if (vb.length === 4) { copy.setAttribute('width', vb[2]); copy.setAttribute('height', vb[3]); }
    copy.querySelectorAll('[tabindex],[role]').forEach((e) => { e.removeAttribute('tabindex'); e.removeAttribute('role'); });
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + new XMLSerializer().serializeToString(copy);
  }

  window.KVOT_ENSDF_CHAIN = { layout, layoutSeries, render, svgFile, setLevels, setHot, nodeName, nodeTitle, viaNames, viaText, edgeAbout, shareText, GEOM, SERIES };
})();
