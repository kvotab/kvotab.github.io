/* ==========================================================================
   GITARR - THE PAGE

   gitarr.html: the headstock drawn in SVG, the microphone, and the loop that
   turns what GT_PITCH hears into the key to turn and the way to turn it.

   The drawing is a right-handed acoustic guitar seen from the front with the
   headstock up, three tuners a side: E, A and D on the left with the low E
   nearest the nut, G, B and E on the right with the high E nearest the nut.
   A left-handed guitar is its mirror image (the setting `lefty`). Which way
   a key turns is GT_PITCH.turn's business; the drawing only shows it.

   GT.inspect() is read-only state for the tests; GT.test feeds samples
   through the page's own frame logic, or plays them through the real audio
   path, without a microphone.
   ========================================================================== */

const GT = (() => {
  'use strict';

  const P = GT_PITCH;
  const NS = 'http://www.w3.org/2000/svg';
  const STORE = 'gitarr.settings';
  const IDLE_STOP_MS = 3 * 60 * 1000;   // the microphone closes after this long with no string heard
  const FRAME_MS = 28;                  // a reading at most this often
  const MARK_TAU = 90;                  // ms; how fast the meter's mark follows

  /* The strings in running text: the two E strings must be told apart. */
  const NAMES = ['låga E', 'A', 'D', 'G', 'B', 'höga E'];
  const ORDINAL = { 1: '1:a', 2: '2:a', 3: '3:e', 4: '4:e', 5: '5:e', 6: '6:e' };

  /* ── The drawing's geometry (400 wide; gitarr.html shows y 26 to 588) ─ */

  const VIEW_W = 400;
  const SLOT_Y = 484;                                   // where the strings leave the nut
  const BOTTOM = 588;                                   // the drawing's lower edge (gitarr.html's viewBox)
  const SLOTS = [152.5, 171.5, 190.5, 209.5, 228.5, 247.5];
  const POST_Y = [384, 290, 196];                       // nearest the nut first
  const POST_X = [128, 126, 124];                       // the left side; the right is mirrored
  const KEY_X = 50;
  const KEY_RX = 21, KEY_RY = 27;
  const WIND_R = 6.4;                                   // the string wound round the post
  const STRING_W = [4.4, 3.8, 3.2, 2.7, 2.1, 1.8];
  const WOUND = [true, true, true, true, false, false];
  const HEAD = 'M142 486 C130 455 104 420 100 380 L93 72 Q92 50 114 47 Q200 34 286 47 Q308 50 307 72 L300 380 C296 420 270 455 258 486 Z';

  function el(tag, attrs, parent) {
    const e = document.createElementNS(NS, tag);
    if (attrs) for (const k of Object.keys(attrs)) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }

  /* Numbers for people (decimal comma) and for SVG (decimal point). */
  const fmt = (x, d = 1) => x.toFixed(d).replace('.', ',');
  const num = x => String(Math.round(x * 100) / 100);
  const pt = (x, y) => `${num(x)} ${num(y)}`;

  /* Where a string coming from S touches a post (centre C, radius r) on the
     post's inner side - the side toward the middle of the headstock, which
     is where a string is wound on. */
  function tangent(S, C, r, left) {
    const dx = S.x - C.x, dy = S.y - C.y;
    const d = Math.hypot(dx, dy);
    const base = Math.atan2(dy, dx), off = Math.acos(Math.min(1, r / d));
    const a = { x: C.x + r * Math.cos(base + off), y: C.y + r * Math.sin(base + off) };
    const b = { x: C.x + r * Math.cos(base - off), y: C.y + r * Math.sin(base - off) };
    return (a.x > b.x) === left ? a : b;
  }

  /* Each string's slot in the nut, post and key, for this hand. */
  function geometry(lefty) {
    return P.STRINGS.map((s, i) => {
      const bass = i < 3;
      const k = bass ? i : 5 - i;
      const left = bass !== lefty;
      const slot = SLOTS[lefty ? 5 - i : i];
      const post = { x: left ? POST_X[k] : VIEW_W - POST_X[k], y: POST_Y[k] };
      const key = { x: left ? KEY_X : VIEW_W - KEY_X, y: POST_Y[k] };
      return { i, left, slot, post, key, tan: tangent({ x: slot, y: SLOT_Y }, post, WIND_R, left) };
    });
  }

  /* The loop round a key. A key turns about its shaft, which lies across
     the picture, so a circle round the shaft is seen almost edge on: a tall,
     narrow ellipse. Angle 0 is the key's front (drawn on the inner side, over
     the key), 90° its top. `front` says which way the front moves. */
  const LOOP_RX = 19, LOOP_RY = 47;
  function loopPoint(sgn, deg) {
    const a = deg * Math.PI / 180;
    return [sgn * LOOP_RX * Math.cos(a), -LOOP_RY * Math.sin(a)];
  }
  function arcPath(points) {
    return points.map((p, k) => (k ? 'L' : 'M') + pt(p[0], p[1])).join(' ');
  }
  function headPath(tip, from, len, half) {
    const dx = tip[0] - from[0], dy = tip[1] - from[1];
    const n = Math.hypot(dx, dy) || 1;
    const ux = dx / n, uy = dy / n;
    const bx = tip[0] - ux * len, by = tip[1] - uy * len;
    return `M${pt(tip[0] + ux * 2, tip[1] + uy * 2)} L${pt(bx - uy * half, by + ux * half)} L${pt(bx + uy * half, by - ux * half)} Z`;
  }
  function keyLoop(sgn, front) {
    const [a0, a1] = front === 'up' ? [-66, 58] : [66, -58];
    const pts = [];
    for (let k = 0; k <= 24; k++) pts.push(loopPoint(sgn, a0 + (a1 - a0) * k / 24));
    const back = [];
    for (let k = 0; k <= 16; k++) back.push(loopPoint(sgn, 118 + 124 * k / 16));
    return { line: arcPath(pts), head: headPath(pts[pts.length - 1], pts[pts.length - 3], 17, 11), back: arcPath(back) };
  }

  /* The arrow round a post, which turns in the plane of the picture. SVG's
     y runs down, so increasing angles go clockwise on the screen. */
  const SPIN_R = 17.5;
  function postSpin(turn) {
    const s = turn === 'cw' ? 1 : -1;
    const pts = [];
    for (let k = 0; k <= 30; k++) {
      const a = (-40 + s * 250 * k / 30) * Math.PI / 180;
      pts.push([SPIN_R * Math.cos(a), SPIN_R * Math.sin(a)]);
    }
    return { line: arcPath(pts), head: headPath(pts[pts.length - 1], pts[pts.length - 3], 8, 5.5) };
  }

  /* ── State ────────────────────────────────────────────────────────────── */

  const state = {
    running: false,
    starting: false,
    error: null,          // a message when the microphone could not start
    stopped: null,        // why it stopped: 'user', 'idle', 'hidden', 'tap' (sound needs a tap first)
    picked: null,         // the string the player picked, or null: automatic
    settings: { lefty: false, reverse: false },
    snap: null,           // GT_PITCH's tracker, as of the last reading
    level: 0,             // the last window's rms
    heardAt: 0,           // when a string was last heard
    mark: 0,              // the meter mark's position in cents, eased
    markAt: 0,
  };
  const tracker = P.createTracker();
  let gate = P.createGate();
  let audio = null;       // { ctx, stream, analyser, buf, det }
  let raf = 0, lastRead = -Infinity;
  let wakeLock = null;
  let resumeOnShow = false;
  let idleStopMs = IDLE_STOP_MS;
  let parts = [];         // per string: the key, string and post elements
  let dom = {};
  let said = { text: '', at: 0 };

  function loadSettings() {
    try {
      const raw = JSON.parse(localStorage.getItem(STORE) || 'null');
      if (raw && typeof raw === 'object') {
        state.settings.lefty = raw.lefty === true;
        state.settings.reverse = raw.reverse === true;
      }
    } catch (e) { /* storage unavailable or damaged: the defaults stand */ }
  }

  function saveSettings() {
    try {
      localStorage.setItem(STORE, JSON.stringify({ lefty: state.settings.lefty, reverse: state.settings.reverse }));
    } catch (e) { /* private mode: the setting lasts for this visit */ }
  }

  /* ── The drawing ──────────────────────────────────────────────────────── */

  function defs(svg) {
    const d = el('defs', null, svg);
    const lin = (id, stops, attrs) => {
      const g = el('linearGradient', Object.assign({ id }, attrs || { x1: 0, y1: 0, x2: 0, y2: 1 }), d);
      for (const [o, c] of stops) el('stop', { offset: o, 'stop-color': c }, g);
      return g;
    };
    lin('gt-wood', [[0, '#2a160d'], [0.16, '#4b2a1a'], [0.5, '#5a3322'], [0.84, '#4b2a1a'], [1, '#2a160d']], { x1: 0, y1: 0, x2: 1, y2: 0 });
    lin('gt-board', [[0, '#24150e'], [0.5, '#3a2317'], [1, '#24150e']], { x1: 0, y1: 0, x2: 1, y2: 0 });
    lin('gt-bone', [[0, '#fbf6ea'], [1, '#d9cba9']]);
    lin('gt-chrome', [[0, '#fdfefe'], [0.32, '#dfe3e7'], [0.68, '#a8b0b8'], [1, '#e4e8eb']]);
    lin('gt-chrome-ok', [[0, '#f0fff4'], [0.32, '#b9efc9'], [0.68, '#5fc07f'], [1, '#c8f2d5']]);
    lin('gt-shaft', [[0, '#7c848c'], [0.45, '#f1f3f5'], [1, '#6d757d']]);
    lin('gt-fretwire', [[0, '#f4f6f7'], [1, '#9aa2a9']]);
    const rg = el('radialGradient', { id: 'gt-bush', cx: 0.4, cy: 0.35, r: 0.7 }, d);
    el('stop', { offset: 0, 'stop-color': '#ffffff' }, rg);
    el('stop', { offset: 0.55, 'stop-color': '#c3c9ce' }, rg);
    el('stop', { offset: 1, 'stop-color': '#7b838a' }, rg);
    const halo = el('filter', { id: 'gt-halo', x: '-60%', y: '-60%', width: '220%', height: '220%' }, d);
    el('feGaussianBlur', { stdDeviation: 7 }, halo);
    const sh = el('filter', { id: 'gt-shadow', x: '-15%', y: '-10%', width: '130%', height: '125%' }, d);
    el('feDropShadow', { dx: 0, dy: 4, stdDeviation: 6, 'flood-color': '#000', 'flood-opacity': 0.32 }, sh);
    // Cut into the face, lit from the upper left: inside the cut, the wall
    // under the upper edge lies in shadow and the wall over the lower edge
    // catches the light. The filter draws only those two rims, from the
    // shape's outline; the cut's floor is the shape's own fill, drawn apart.
    const cv = el('filter', { id: 'gt-carve', x: '-20%', y: '-20%', width: '140%', height: '140%' }, d);
    el('feOffset', { in: 'SourceAlpha', dx: 0.55, dy: 0.65, result: 'down' }, cv);
    el('feComposite', { in: 'SourceAlpha', in2: 'down', operator: 'out', result: 'upper' }, cv);
    el('feFlood', { 'flood-color': '#080302', 'flood-opacity': 0.7 }, cv);
    el('feComposite', { in2: 'upper', operator: 'in', result: 'shade' }, cv);
    el('feOffset', { in: 'SourceAlpha', dx: -0.45, dy: -0.55, result: 'up' }, cv);
    el('feComposite', { in: 'SourceAlpha', in2: 'up', operator: 'out', result: 'lower' }, cv);
    el('feFlood', { 'flood-color': '#f7d29e', 'flood-opacity': 0.36 }, cv);
    el('feComposite', { in2: 'lower', operator: 'in', result: 'lit' }, cv);
    const rims = el('feMerge', null, cv);
    el('feMergeNode', { in: 'shade' }, rims);
    el('feMergeNode', { in: 'lit' }, rims);
    const cp = el('clipPath', { id: 'gt-headclip' }, d);
    el('path', { d: HEAD }, cp);
    const kc = el('clipPath', { id: 'gt-keyclip' }, d);
    el('ellipse', { cx: 0, cy: 0, rx: KEY_RX - 1, ry: KEY_RY - 1 }, kc);
  }

  function draw() {
    const svg = dom.svg;
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    defs(svg);
    const geo = geometry(state.settings.lefty);

    // The neck below the nut, with the first fret.
    el('path', { d: `M142 486 L258 486 L262 ${BOTTOM} L138 ${BOTTOM} Z`, fill: 'url(#gt-board)' }, svg);
    el('rect', { x: 139, y: 566, width: 122, height: 6, rx: 1.5, fill: 'url(#gt-fretwire)' }, svg);

    // The keys' shafts come out from under the headstock's edge.
    for (const g of geo) {
      const x0 = g.left ? g.key.x + KEY_RX - 3 : 300 - 6;
      const x1 = g.left ? 100 + 6 : g.key.x - KEY_RX + 3;
      el('rect', { x: x0, y: g.key.y - 4.5, width: x1 - x0, height: 9, rx: 2, fill: 'url(#gt-shaft)' }, svg);
    }

    // The headstock: its face, a little grain, the binding, the name.
    const head = el('g', { class: 'gt-head' }, svg);
    el('path', { d: HEAD, fill: 'url(#gt-wood)', filter: 'url(#gt-shadow)' }, head);
    const grain = el('g', { 'clip-path': 'url(#gt-headclip)', fill: 'none', 'stroke-width': 1.1 }, head);
    [104, 121, 139, 158, 176, 195, 214, 233, 251, 270, 288].forEach((x, k) => {
      const w = k % 2 ? 7 : -6;
      el('path', { d: `M${x} 500 C${x + w} 400 ${x - w} 260 ${x + w / 2} 140 S${x - w} 60 ${x} 20`,
        stroke: k % 3 ? 'rgba(0,0,0,0.22)' : 'rgba(255,214,170,0.07)' }, grain);
    });
    el('path', { d: HEAD, fill: 'none', stroke: '#eadfc6', 'stroke-width': 3 }, head);
    carveLogo(head);

    // The truss rod cover between the D and G strings.
    el('path', { d: 'M187 476 L213 476 Q215 452 206 441 Q200 435 194 441 Q185 452 187 476 Z',
      fill: '#141110', stroke: '#eadfc6', 'stroke-width': 0.9 }, head);
    el('circle', { cx: 200, cy: 446, r: 1.6, fill: '#b9bfc4' }, head);
    el('circle', { cx: 200, cy: 469, r: 1.6, fill: '#b9bfc4' }, head);

    // The nut.
    el('rect', { x: 139, y: 478, width: 122, height: 12, rx: 2.5, fill: 'url(#gt-bone)', stroke: '#b6a684', 'stroke-width': 0.8 }, svg);

    parts = geo.map(g => ({ geo: g }));

    // The posts: a bushing, the post, the string wound on it.
    for (const g of geo) {
      const post = el('g', { class: 'gt-postbody', transform: `translate(${pt(g.post.x, g.post.y)})` }, svg);
      el('circle', { r: 11.5, fill: 'url(#gt-bush)', stroke: '#596067', 'stroke-width': 1 }, post);
      el('circle', { r: 8.6, fill: 'none', stroke: 'rgba(255,255,255,0.4)', 'stroke-width': 1 }, post);
      el('circle', { r: 5, fill: '#e3e7ea', stroke: '#79818a', 'stroke-width': 0.8 }, post);
      parts[g.i].postBody = post;
    }

    // The strings: from below the picture to the nut, and on to the post.
    // Their glows go first, under all of them.
    const glows = el('g', { class: 'gt-glows' }, svg);
    for (const g of geo) {
      const i = g.i, w = STRING_W[i];
      const colour = WOUND[i] ? '#c99a52' : '#d3d8dc';
      const grp = el('g', { class: 'gt-string', 'data-i': i }, svg);
      parts[i].glow = el('path', { class: 'gt-string-glow', d: `M${pt(g.slot, BOTTOM)} L${pt(g.slot, SLOT_Y)} L${pt(g.tan.x, g.tan.y)}`,
        'stroke-width': w + 9, 'stroke-linecap': 'butt', 'stroke-linejoin': 'round' }, glows);
      const neck = el('g', { class: 'gt-string-neck' }, grp);
      el('line', { x1: g.slot, y1: SLOT_Y + 1, x2: g.slot, y2: BOTTOM, stroke: colour, 'stroke-width': w }, neck);
      el('line', { x1: g.slot, y1: SLOT_Y, x2: num(g.tan.x), y2: num(g.tan.y),
        stroke: colour, 'stroke-width': w, 'stroke-linecap': 'round' }, grp);
      if (WOUND[i]) {
        // the winding of a wound string, as fine dark lines across it
        el('line', { x1: g.slot, y1: SLOT_Y + 1, x2: g.slot, y2: BOTTOM, stroke: '#6e4b1f', 'stroke-width': w,
          'stroke-dasharray': '0.9 1.5', opacity: 0.45 }, neck);
        el('line', { x1: g.slot, y1: SLOT_Y, x2: num(g.tan.x), y2: num(g.tan.y),
          stroke: '#6e4b1f', 'stroke-width': w, 'stroke-dasharray': '0.9 1.5', opacity: 0.45 }, grp);
      }
      // wound on the post, over it
      el('circle', { cx: g.post.x, cy: g.post.y, r: WIND_R, fill: 'none', stroke: colour, 'stroke-width': Math.max(1.6, w * 0.85) }, svg);
      el('circle', { cx: g.post.x, cy: g.post.y, r: 1.7, fill: '#2f353a' }, svg);
      parts[i].string = grp;
    }

    // The arrows round the posts.
    for (const g of geo) {
      const post = el('g', { class: 'gt-post', 'data-i': g.i, transform: `translate(${pt(g.post.x, g.post.y)})` }, svg);
      const spin = el('g', { class: 'gt-spin' }, post);
      const inner = el('g', { class: 'gt-spin-inner' }, spin);
      parts[g.i].post = post;
      parts[g.i].spinLine = el('path', { class: 'gt-spin-line' }, inner);
      parts[g.i].spinHead = el('path', { class: 'gt-spin-head' }, inner);
    }

    // The keys, each a button.
    for (const g of geo) {
      const i = g.i, s = P.STRINGS[i];
      const sgn = g.left ? 1 : -1;
      const key = el('g', {
        class: 'gt-key', 'data-i': i, role: 'button', tabindex: 0,
        'data-on-click': 'gt:pick', 'data-on-keydown': 'gt:pickKey',
        transform: `translate(${pt(g.key.x, g.key.y)})`,
      }, svg);
      el('ellipse', { class: 'gt-key-halo', rx: KEY_RX + 9, ry: KEY_RY + 9, filter: 'url(#gt-halo)' }, key);
      el('ellipse', { class: 'gt-key-hit', rx: KEY_RX + 10, ry: KEY_RY + 14, fill: 'transparent' }, key);
      el('ellipse', { class: 'gt-key-ring', rx: KEY_RX + 6, ry: KEY_RY + 6 }, key);
      const back = el('g', { class: 'gt-turn' }, key);
      const backLine = el('path', { class: 'gt-turn-back' }, back);
      // the collar where the key meets its shaft
      el('rect', { x: sgn > 0 ? KEY_RX - 7 : -KEY_RX - 3, y: -7, width: 10, height: 14, rx: 2.5,
        fill: 'url(#gt-chrome)', stroke: '#6d757d', 'stroke-width': 0.8 }, key);
      el('ellipse', { class: 'gt-key-face', rx: KEY_RX, ry: KEY_RY, fill: 'url(#gt-chrome)', stroke: '#5f676f', 'stroke-width': 1.2 }, key);
      const roll = el('g', { class: 'gt-roll', 'clip-path': 'url(#gt-keyclip)' }, key);
      const rollInner = el('g', { class: 'gt-roll-inner' }, roll);
      for (let y = -42; y <= 42; y += 14) el('line', { x1: -KEY_RX, y1: y, x2: KEY_RX, y2: y }, rollInner);
      for (let y = -38; y <= 46; y += 14) el('line', { class: 'gt-roll-lit', x1: -KEY_RX, y1: y, x2: KEY_RX, y2: y }, rollInner);
      const letter = el('text', { class: 'gt-key-letter', x: 0, y: 8.5, 'text-anchor': 'middle' }, key);
      letter.textContent = s.name;
      const front = el('g', { class: 'gt-turn' }, key);
      const edge = el('path', { class: 'gt-turn-edge' }, front);
      const line = el('path', { class: 'gt-turn-line' }, front);
      const march = el('path', { class: 'gt-turn-march' }, front);
      const head = el('path', { class: 'gt-turn-head' }, front);
      const check = el('g', { class: 'gt-key-check', transform: `translate(${pt(-sgn * 17, -24)})` }, key);
      el('circle', { r: 9.5 }, check);
      el('path', { d: 'M-4.4 0.2 L-1.2 3.4 L4.6 -3.4' }, check);
      el('ellipse', { class: 'gt-pulse', rx: KEY_RX, ry: KEY_RY }, key);
      Object.assign(parts[i], { key, sgn, backLine, edge, line, march, head });
    }

    for (const p of parts) setTurn(p, 'up', 'cw', true);
    render(true);
  }

  /* kvot ab's logo - the three-faced mark and the letters kv/ot, as the
     site's header draws it (KVOT_ICONS.LOGO_SVG) - cut small into the
     headstock as a maker's mark. Each face of the mark is a cut of its own.
     What the header draws in its light colour (class stTop: the mark's top
     face and the letters) is gilded, gold laid in the cut as headstock
     marks often are; the two other faces stay bare wood, a mid and a dark
     shade, as the header's red-brown and green would be in wood. (Without
     kvot-icons.js the site's header fails too; the headstock is then left
     plain.) */
  const LOGO_WIDTH = 86, LOGO_MID = 128;
  const GILDED = 'stTop';
  const WOOD_TONES = { stRight: 'rgba(12,5,2,0.17)', stLeft: 'rgba(12,5,2,0.33)' };
  const BARE_TONE = 'rgba(12,5,2,0.25)';
  const GOLD = [[0, '#f9e8b0'], [0.3, '#e2b555'], [0.55, '#b8862c'], [0.8, '#e9c56e'], [1, '#c9963a']];

  /* The logo's parts: each polygon (a face of the mark) a cut of its own,
     the paths (the letters) one cut together. */
  function logoSource() {
    try {
      if (typeof KVOT_ICONS === 'undefined' || !KVOT_ICONS.LOGO_SVG) return null;
      const doc = new DOMParser().parseFromString(KVOT_ICONS.LOGO_SVG, 'image/svg+xml');
      const svg = doc.documentElement;
      if (!svg || svg.nodeName !== 'svg' || doc.querySelector('parsererror')) return null;
      const box = (svg.getAttribute('viewBox') || '').trim().split(/[\s,]+/).map(Number);
      if (box.length !== 4 || !box.every(Number.isFinite) || !(box[2] > 0) || !(box[3] > 0)) return null;
      const part = e => ({ tag: e.nodeName, shape: e.nodeName === 'polygon' ? { points: e.getAttribute('points') } : { d: e.getAttribute('d') },
        cls: e.getAttribute('class') });
      const faces = [...svg.querySelectorAll('polygon')].map(part);
      const letters = [...svg.querySelectorAll('path')].map(part);
      if (faces.length !== 3 || !letters.length || ![...faces, ...letters].every(p => p.shape.points || p.shape.d)) return null;
      return { box, cuts: [...faces.map(f => [f]), letters] };
    } catch (e) {
      return null;
    }
  }

  function carveLogo(parent) {
    const src = logoSource();
    if (!src) return;
    const logo = el('g', { class: 'gt-logo' }, parent);
    const [bx, by, bw, bh] = src.box;
    const s = LOGO_WIDTH / bw;
    const place = `translate(${num(200 - LOGO_WIDTH / 2)} ${num(LOGO_MID - bh * s / 2)}) scale(${s.toFixed(5)}) translate(${-bx} ${-by})`;
    // The gold runs across the whole logo, in the logo's own units.
    const gold = el('linearGradient', { id: 'gt-gold', gradientUnits: 'userSpaceOnUse', x1: bx, y1: by, x2: bx + bw, y2: by + bh },
      dom.svg.querySelector('defs'));
    for (const [o, c] of GOLD) el('stop', { offset: o, 'stop-color': c }, gold);
    // Every cut's floor first, then every cut's rims. The rims are drawn by
    // the filter in the headstock's units, so the group carrying the filter
    // is not the scaled one; and each face being a cut of its own, the edges
    // between the faces show too.
    const floors = el('g', { transform: place }, logo);
    const rims = el('g', null, logo);
    for (const parts of src.cuts) {
      const edge = el('g', { transform: place }, el('g', { filter: 'url(#gt-carve)' }, rims));
      for (const p of parts) {
        const fill = p.cls === GILDED ? 'url(#gt-gold)' : (WOOD_TONES[p.cls] || BARE_TONE);
        el(p.tag, Object.assign({ fill }, p.shape), floors);
        el(p.tag, Object.assign({ fill: '#000' }, p.shape), edge);
      }
    }
  }

  /* Point a key's loop and a post's spin, if they changed. */
  function setTurn(p, front, turn, force) {
    if (force || p.front !== front) {
      const loop = keyLoop(p.sgn, front);
      p.edge.setAttribute('d', loop.line);
      p.line.setAttribute('d', loop.line);
      p.march.setAttribute('d', loop.line);
      p.head.setAttribute('d', loop.head);
      p.backLine.setAttribute('d', loop.back);
      p.key.setAttribute('data-front', front);
      p.front = front;
    }
    if (force || p.turn !== turn) {
      const spin = postSpin(turn);
      p.spinLine.setAttribute('d', spin.line);
      p.spinHead.setAttribute('d', spin.head);
      p.post.setAttribute('data-turn', turn);
      p.turn = turn;
    }
  }

  /* ── Rendering ────────────────────────────────────────────────────────── */

  function tone(cents) {
    const a = Math.abs(cents);
    return a <= P.TRACKER.inTuneCents ? 'ok' : a <= 15 ? 'near' : 'off';
  }

  function capital(s) { return s.charAt(0).toUpperCase() + s.slice(1); }

  /* "A-strängen", with a hyphen that never breaks the line. */
  function stringLabel(i) {
    return `${NAMES[i]}\u2011strängen`;
  }

  function message() {
    if (state.error) return { text: state.error, state: 'error' };
    if (state.starting) return { text: 'Startar mikrofonen …', state: 'info' };
    const snap = state.snap;
    if (!state.running) {
      if (state.stopped === 'idle') return { text: 'Mikrofonen stängdes efter tre minuter utan gitarrljud. Tryck på Starta för att fortsätta.', state: 'info' };
      if (state.stopped === 'hidden') return { text: 'Mikrofonen stängdes när du lämnade sidan. Tryck på Starta för att fortsätta.', state: 'info' };
      if (state.stopped === 'user') return { text: 'Mikrofonen är avstängd. Tryck på Starta för att fortsätta.', state: 'info' };
      if (state.stopped === 'tap') return { text: 'Tryck på Starta för att börja lyssna.', state: 'info' };
      return { text: 'Tryck på Starta och tillåt mikrofonen.', state: 'info' };
    }
    if (!snap || !snap.shown) {
      if (state.picked !== null) return { text: `Slå an ${stringLabel(state.picked)}.`, state: 'info' };
      return { text: 'Slå an en sträng i taget och låt den klinga.', state: 'info' };
    }
    const c = snap.cents, t = tone(c), name = stringLabel(snap.string);
    if (t === 'ok') return { text: `${capital(name)} är stämd!`, state: 'ok' };
    const low = c < 0;
    if (t === 'near') return { text: low ? 'Lite för lågt – spänn lite till.' : 'Lite för högt – släpp efter lite.', state: 'near' };
    const much = Math.abs(c) > 50 ? 'Mycket för ' : 'För ';
    return { text: much + (low ? `lågt – spänn ${name}.` : `högt – släpp efter på ${name}.`), state: 'off' };
  }

  let shown = {};
  function put(key, value, apply) {
    if (shown[key] === value) return;
    shown[key] = value;
    apply(value);
  }

  function render(force) {
    if (force) shown = {};
    const snap = state.snap;
    const active = snap && snap.shown ? snap.string : null;
    const live = !!(snap && snap.live);
    const cents = active === null ? null : snap.cents;
    const t = cents === null ? null : tone(cents);
    const turnable = active !== null && t !== 'ok';
    const way = turnable ? P.turn(active, cents, state.settings) : null;

    parts.forEach((p, i) => {
      const on = i === active;
      const cls = p.key.classList;
      cls.toggle('is-active', on);
      cls.toggle('is-near', on && t === 'near');
      cls.toggle('is-ok', on && t === 'ok');
      cls.toggle('is-quiet', on && !live);
      cls.toggle('is-turn', on && turnable);
      cls.toggle('is-picked', state.picked === i);
      cls.toggle('is-tuned', !!(snap && snap.tuned[i]));
      for (const sc of [p.string.classList, p.glow.classList]) {
        sc.toggle('is-active', on);
        sc.toggle('is-near', on && t === 'near');
        sc.toggle('is-ok', on && t === 'ok');
        sc.toggle('is-quiet', on && !live);
        sc.toggle('is-live', on && live);
        sc.toggle('is-picked', state.picked === i && !on);
      }
      p.post.classList.toggle('is-turn', on && turnable);
      p.post.classList.toggle('is-near', on && t === 'near');
      if (on && way) setTurn(p, way.keyFront, way.post);
      const label = `${capital(stringLabel(i))}, ${ORDINAL[P.STRINGS[i].n]} strängen`
        + (state.picked === i ? ', vald' : '') + (snap && snap.tuned[i] ? ', stämd' : '');
      put('label' + i, label, v => p.key.setAttribute('aria-label', v));
      put('pressed' + i, String(state.picked === i), v => p.key.setAttribute('aria-pressed', v));
    });
    if (way) {
      const a = Math.abs(cents);
      put('speed', a > 50 ? '0.55s' : a > 15 ? '0.8s' : '1.25s', v => dom.svg.style.setProperty('--gt-speed', v));
    }

    // The readout above the meter.
    put('quiet', String(active !== null && !live), v => dom.panel.classList.toggle('is-quiet', v === 'true'));
    if (active === null) {
      put('what', state.picked === null ? 'Ingen sträng än' : `Bara ${stringLabel(state.picked)}`, v => { dom.what.textContent = v; });
      put('cents', '', v => { dom.cents.textContent = v; });
    } else {
      const s = P.STRINGS[active];
      put('what', `${active}|${fmt(snap.freq)}`, () => {
        dom.what.textContent = '';
        const b = document.createElement('b');
        b.textContent = s.name;
        const hz = document.createElement('span');
        hz.className = 'gt-hz';
        hz.textContent = ` · ${fmt(snap.freq)} Hz`;
        dom.what.append(b, ` ${ORDINAL[s.n]} strängen`, hz);
      });
      const r = Math.round(cents);
      put('cents', (r > 0 ? '+' : r < 0 ? '−' : '') + Math.abs(r) + ' cent', v => { dom.cents.textContent = v; });
    }
    put('meter', active === null ? 'idle' : t, v => dom.meter.setAttribute('data-state', v));
    put('markNote', active === null ? (state.picked === null ? '' : P.STRINGS[state.picked].name) : P.STRINGS[active].name,
      v => { dom.markNote.textContent = v; });

    const m = message();
    put('msg', m.text, v => { dom.msg.textContent = v; });
    put('msgState', m.state, v => dom.msg.setAttribute('data-state', v));

    // The start button, Auto and the level.
    const label = state.running ? 'Stoppa' : state.starting ? 'Startar …' : 'Starta';
    put('start', label, v => { dom.startLabel.textContent = v; });
    put('startOn', String(state.running), v => dom.start.classList.toggle('is-on', v === 'true'));
    put('startDisabled', String(state.starting), v => { dom.start.disabled = v === 'true'; });
    put('auto', String(state.picked === null), v => dom.auto.setAttribute('aria-pressed', v));
    const db = state.level > 0 ? 20 * Math.log10(state.level) : -120;
    const lit = state.running ? [-60, -50, -40, -30, -20].filter(x => db >= x).length : 0;
    put('level', lit, v => dom.levelBars.forEach((b, k) => b.classList.toggle('is-lit', k < v)));
    put('levelOn', String(state.running), v => dom.level.classList.toggle('is-on', v === 'true'));

    const all = !!(snap && snap.tuned.every(Boolean));
    put('done', String(all), v => { dom.done.hidden = v !== 'true'; });

    announce(active, t, cents, snap);
  }

  /* What a screen reader hears: the string when it changes, and when it is
     in tune - not every frame's cents. */
  function announce(active, t, cents, snap) {
    let text = '';
    if (snap && snap.justTuned !== null) text = `${capital(stringLabel(snap.justTuned))} är stämd.`;
    else if (active !== null && snap.live) {
      const r = Math.round(cents);
      text = t === 'ok' ? '' : `${capital(stringLabel(active))}, ${Math.abs(r)} cent för ${r < 0 ? 'lågt' : 'högt'}.`;
    }
    const now = performance.now();
    if (!text || text === said.text) return;
    if (snap.justTuned === null && now - said.at < 2500) return;
    said = { text, at: now };
    dom.say.textContent = text;
  }

  /* The mark eases toward the reading, frame by frame. */
  function moveMark(now) {
    const snap = state.snap;
    const target = snap && snap.shown ? Math.max(-50, Math.min(50, snap.cents)) : 0;
    const dt = Math.min(200, Math.max(0, now - (state.markAt || now)));
    state.markAt = now;
    state.mark += (target - state.mark) * (1 - Math.exp(-dt / MARK_TAU));
    if (Math.abs(target - state.mark) < 0.05) state.mark = target;
    dom.mark.style.left = `${50 + state.mark}%`;
  }

  /* ── One reading ──────────────────────────────────────────────────────── */

  function step(now, samples, det) {
    const { reading, hit } = P.hear(det, samples, { string: state.picked });
    state.level = reading.rms;
    const heard = gate.pass(reading) && hit ? hit : null;
    if (heard) state.heardAt = now;
    state.snap = tracker.update(now, heard);
    if (state.snap.justTuned !== null) pulse(state.snap.justTuned);
    return heard;
  }

  function pulse(i) {
    const k = parts[i] && parts[i].key;
    if (!k) return;
    k.classList.remove('is-pulse');
    void k.getBoundingClientRect();
    k.classList.add('is-pulse');
  }

  function frame(now) {
    raf = 0;
    if (!audio) return;
    // Sound can be taken away while the page listens - a phone call, another
    // app taking the audio - and an analyser then reads silence. One try at
    // resuming; if the sound does not come back, ask for a tap.
    if (audio.ctx.state !== 'running') {
      if (!audio.pausedAt) {
        audio.pausedAt = now;
        audio.ctx.resume().catch(() => {});
      } else if (now - audio.pausedAt > 1500) {
        stop('tap');
        return;
      }
    } else {
      audio.pausedAt = 0;
    }
    if (now - lastRead >= FRAME_MS) {
      lastRead = now;
      audio.analyser.getFloatTimeDomainData(audio.buf);
      step(now, audio.buf, audio.det);
      if (now - state.heardAt > idleStopMs) {
        stop('idle');
        return;
      }
      render();
    }
    moveMark(now);
    raf = requestAnimationFrame(frame);
  }

  /* ── The microphone ───────────────────────────────────────────────────── */

  function micError(e) {
    const name = e && e.name;
    if (name === 'NotAllowedError' || name === 'SecurityError' || name === 'PermissionDeniedError') {
      return 'Sidan fick inte använda mikrofonen. Tillåt mikrofonen för den här sidan i webbläsarens inställningar och tryck på Starta igen.';
    }
    if (name === 'NotFoundError' || name === 'OverconstrainedError' || name === 'DevicesNotFoundError') {
      return 'Hittade ingen mikrofon. Koppla in en och tryck på Starta igen.';
    }
    if (name === 'NotReadableError' || name === 'AbortError' || name === 'TrackStartError') {
      return 'Mikrofonen gick inte att starta. Den kanske används av en annan app.';
    }
    return 'Mikrofonen gick inte att starta.';
  }

  async function start() {
    if (state.running || state.starting) return;
    state.error = null;
    if (!window.isSecureContext) {
      state.error = 'Mikrofonen fungerar bara när sidan öppnas över https.';
      render();
      return;
    }
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      state.error = 'Den här webbläsaren kan inte lyssna via mikrofonen.';
      render();
      return;
    }
    state.starting = true;
    render();
    // Made and resumed inside the tap, which is what a browser asks of sound.
    const ctx = new AC();
    const resumed = ctx.resume().catch(() => {});
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
      });
    } catch (e) {
      ctx.close().catch(() => {});
      state.starting = false;
      state.error = micError(e);
      render();
      return;
    }
    // A browser that wants a tap before sound runs leaves resume() waiting
    // for ever - it does when the microphone reopens by itself after the
    // page was hidden - so the wait is bounded and a tap on Starta is asked.
    await Promise.race([resumed, new Promise(r => setTimeout(r, 1500))]);
    if (!state.starting || ctx.state !== 'running') {
      stream.getTracks().forEach(t => t.stop());
      ctx.close().catch(() => {});
      if (state.starting) {
        state.starting = false;
        state.stopped = 'tap';
        render();
      }
      return;
    }
    connect(ctx, ctx.createMediaStreamSource(stream), stream);
  }

  /* source → high-pass at 50 Hz (rumble, handling) → analyser. The analyser
     also feeds a silent gain to the output, which keeps the graph running in
     browsers that only process what reaches the destination. */
  function connect(ctx, source, stream) {
    const det = P.createDetector(ctx.sampleRate);
    const hp = ctx.createBiquadFilter();
    hp.type = 'highpass';
    hp.frequency.value = 50;
    hp.Q.value = Math.SQRT1_2;
    const analyser = ctx.createAnalyser();
    let size = 2048;
    while (size < det.need && size < 32768) size *= 2;
    analyser.fftSize = size;
    const sink = ctx.createGain();
    sink.gain.value = 0;
    source.connect(hp);
    hp.connect(analyser);
    analyser.connect(sink);
    sink.connect(ctx.destination);
    audio = { ctx, stream, source, analyser, buf: new Float32Array(size), det };
    gate = P.createGate();
    freshStart();
    state.starting = false;
    state.running = true;
    state.stopped = null;
    state.heardAt = performance.now();
    lastRead = -Infinity;
    wake();
    render();
    if (!raf) raf = requestAnimationFrame(frame);
  }

  function stop(why) {
    state.starting = false;
    if (audio) {
      if (audio.stream) audio.stream.getTracks().forEach(t => t.stop());
      if (audio.player) { try { audio.player.stop(); } catch (e) { /* already ended */ } }
      audio.ctx.close().catch(() => {});
      audio = null;
    }
    if (raf) cancelAnimationFrame(raf);
    raf = 0;
    state.running = false;
    state.stopped = why || 'user';
    state.level = 0;
    freshStart();
    sleepOK();
    render();
    moveMark(performance.now());
  }

  async function wake() {
    try {
      if (!wakeLock && navigator.wakeLock && document.visibilityState === 'visible') {
        wakeLock = await navigator.wakeLock.request('screen');
        wakeLock.addEventListener('release', () => { wakeLock = null; });
      }
    } catch (e) { /* not granted (battery saver, an old browser): the screen may dim */ }
  }

  function sleepOK() {
    if (wakeLock) {
      wakeLock.release().catch(() => {});
      wakeLock = null;
    }
  }

  function onVisibility() {
    if (document.hidden) {
      if (state.running && !(audio && audio.player)) {
        resumeOnShow = true;
        stop('hidden');
      }
    } else if (resumeOnShow) {
      resumeOnShow = false;
      start();
    }
  }

  /* ── Actions ──────────────────────────────────────────────────────────── */

  /* No string on screen, the ticks kept. */
  function freshStart() {
    tracker.reset();
    state.snap = tracker.update(performance.now(), null);
  }

  function pick(i) {
    state.picked = state.picked === i ? null : i;
    freshStart();
    render();
  }

  function openDialog(id) {
    const d = document.getElementById(id);
    if (!d) return;
    if (id === 'gt-settings') {
      d.querySelector('input[name="reverse"]').checked = state.settings.reverse;
      d.querySelector('input[name="lefty"]').checked = state.settings.lefty;
    }
    if (typeof d.showModal === 'function') d.showModal();
    else d.setAttribute('open', '');
  }

  function closeDialog(e, elem) {
    const d = elem && elem.closest('dialog');
    if (!d) return;
    if (typeof d.close === 'function') d.close();
    else d.removeAttribute('open');
  }

  const actions = {
    'gt:start': () => (state.running ? stop('user') : start()),
    'gt:auto': () => {
      if (state.picked === null) return;
      state.picked = null;
      freshStart();
      render();
    },
    'gt:pick': (e, elem) => pick(Number(elem.getAttribute('data-i'))),
    'gt:pickKey': (e, elem) => {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      e.preventDefault();
      pick(Number(elem.getAttribute('data-i')));
    },
    'gt:again': () => {
      tracker.clearTuned();
      if (state.snap) state.snap = Object.assign({}, state.snap, { tuned: state.snap.tuned.map(() => false) });
      render();
    },
    'gt:help': () => openDialog('gt-help'),
    'gt:settings': () => openDialog('gt-settings'),
    'gt:close': closeDialog,
    'gt:setting': (e, elem) => {
      const name = elem.name;
      if (name !== 'reverse' && name !== 'lefty') return;
      state.settings[name] = elem.checked;
      saveSettings();
      if (name === 'lefty') draw();
      else render(true);
    },
  };

  /* ── Start-up ─────────────────────────────────────────────────────────── */

  function fillTable() {
    const body = document.getElementById('gt-table-body');
    if (!body) return;
    for (let i = 5; i >= 0; i--) {
      const s = P.STRINGS[i];
      const tr = document.createElement('tr');
      const cells = [`${s.n}`, `${s.name}${s.name === 'B' ? ' (H)' : ''} · ${s.name}${s.octave}`, `${fmt(s.freq, 2)} Hz`];
      for (const c of cells) {
        const td = document.createElement('td');
        td.textContent = c;
        tr.appendChild(td);
      }
      body.appendChild(tr);
    }
  }

  function init() {
    dom = {
      svg: document.getElementById('gt-guitar'),
      panel: document.getElementById('gt-panel'),
      what: document.getElementById('gt-what'),
      cents: document.getElementById('gt-cents'),
      meter: document.getElementById('gt-meter'),
      mark: document.getElementById('gt-mark'),
      markNote: document.getElementById('gt-mark-note'),
      msg: document.getElementById('gt-msg'),
      start: document.getElementById('gt-start'),
      startLabel: document.getElementById('gt-start-label'),
      auto: document.getElementById('gt-auto'),
      level: document.getElementById('gt-level'),
      levelBars: [...document.querySelectorAll('#gt-level i')],
      done: document.getElementById('gt-done'),
      say: document.getElementById('gt-say'),
    };
    loadSettings();
    registerActions(actions);
    fillTable();
    draw();
    moveMark(performance.now());
    document.addEventListener('visibilitychange', onVisibility);
    // A click on the dialog's backdrop closes it.
    for (const d of document.querySelectorAll('.gt-dialog')) {
      d.addEventListener('click', e => { if (e.target === d && typeof d.close === 'function') d.close(); });
    }
  }

  /* ── For the tests ────────────────────────────────────────────────────── */

  function inspect() {
    const snap = state.snap;
    const activeKey = parts.findIndex(p => p.key.classList.contains('is-active'));
    const p = activeKey >= 0 ? parts[activeKey] : null;
    return JSON.parse(JSON.stringify({
      running: state.running,
      starting: state.starting,
      error: state.error,
      stopped: state.stopped,
      picked: state.picked,
      settings: state.settings,
      snap: snap && { string: snap.string, cents: snap.cents, live: snap.live, shown: snap.shown, inTune: snap.inTune, tuned: snap.tuned },
      active: activeKey >= 0 ? activeKey : null,
      turn: p && p.key.classList.contains('is-turn') ? { front: p.key.getAttribute('data-front'), post: p.post.getAttribute('data-turn'), side: p.geo.left ? 'left' : 'right' } : null,
      tuned: parts.map(q => q.key.classList.contains('is-tuned')),
      picked_keys: parts.map(q => q.key.classList.contains('is-picked')),
      keys: parts.map(q => ({ left: q.geo.left, x: q.geo.key.x, y: q.geo.key.y })),
      msg: dom.msg.textContent,
      msgState: dom.msg.getAttribute('data-state'),
      what: dom.what.textContent,
      cents: dom.cents.textContent,
      meter: dom.meter.getAttribute('data-state'),
      mark: Math.round(state.mark * 10) / 10,
      done: !dom.done.hidden,
      level: state.level,
      sampleRate: audio ? audio.ctx.sampleRate : null,
    }));
  }

  /* A detector per sample rate for feed(), made on first use. */
  const testDetectors = {};

  const test = {
    /* One frame of the page's own logic on these samples, at this clock
       time, as if the microphone were on. */
    feed(samples, sampleRate, now) {
      if (!testDetectors[sampleRate]) testDetectors[sampleRate] = P.createDetector(sampleRate);
      state.running = true;
      state.stopped = null;
      const x = samples instanceof Float32Array ? samples : Float32Array.from(samples);
      const heard = step(now, x, testDetectors[sampleRate]);
      render();
      state.markAt = now - 1000;
      moveMark(now);
      return heard;
    },
    /* Play samples through the real audio path - an AudioBufferSource in
       place of the microphone - and let the frame loop read them. */
    play(samples, sampleRate, loop) {
      if (audio) stop('user');
      const AC = window.AudioContext || window.webkitAudioContext;
      const ctx = new AC({ sampleRate });
      const buffer = ctx.createBuffer(1, samples.length, sampleRate);
      buffer.copyToChannel(samples instanceof Float32Array ? samples : Float32Array.from(samples), 0);
      const player = ctx.createBufferSource();
      player.buffer = buffer;
      player.loop = !!loop;
      connect(ctx, player, null);
      audio.player = player;
      player.start();
      return ctx.resume().then(() => ctx.state);
    },
    stop: () => stop('user'),
    /* The running AudioContext, to take its sound away. */
    context: () => (audio ? audio.ctx : null),
    /* How long the microphone stays open with no string heard. */
    idleAfter(ms) { idleStopMs = ms > 0 ? ms : IDLE_STOP_MS; },
    reset() {
      if (audio) stop('user');
      tracker.clearTuned();
      gate = P.createGate();
      freshStart();
      state.running = false;
      state.stopped = null;
      state.error = null;
      state.picked = null;
      state.mark = 0;
      render(true);
      moveMark(performance.now());
    },
  };

  return { init, inspect, test };
})();
