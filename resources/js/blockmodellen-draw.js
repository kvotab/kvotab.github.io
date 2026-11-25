/* ==========================================================================
   BLOCKMODELLEN - DRAWING A MODEL (blockmodellen.html)

   A model is drawn in SVG at the size of its box, one pixel a pixel, so
   that its text is as large on a phone as anywhere: the page draws it
   again when the box changes size.

     m = {
       rows:    [{ key, label, color, pieces: [{ k: 'bit' | 'del', w, name,
                   marked }], under: { row, from, to } }],
       groups:  [{ id, row, pieces, label, mark, link }],
       values:  { slot: text }      what is written, '?' for the question
       answer:  slot                where the answer stands in for the '?'
       schematic: true              bits 1, other pieces 0.55: the pupil's
                                    own drawing, before it has numbers
       targets: true                every place a number can go is shown
       hl, bad: slot                a place pointed at, a place tapped wrong
       markRow: key                 the pieces of this row can be tapped
       mini:    true                a small picture: no words, no numbers
     }

   How the parts are placed, as in the books:

     - one block alone: its whole above it, under a brace;
     - blocks under each other: each block's whole at its end, all of them
       together under a brace at the right;
     - a block of one piece has its number inside it, and so has a piece;
     - a named run of pieces (a group) has a brace under it, with its name
       and number; a run that has an extra block of its own under it
       (the rest) has dashed lines down to it instead.

   render() returns where everything went: the places a number can go
   (slots, with the names BM_PROBLEMS.canon gives them) and the pieces.
   ========================================================================== */

const BM_DRAW = (() => {
  'use strict';

  const SVGNS = 'http://www.w3.org/2000/svg';
  const FONT = '"IBM Plex Sans", system-ui, -apple-system, "Segoe UI", sans-serif';
  const FULL = {
    pad: 10, barH: 46, gap: 18, underGap: 26, minPiece: 30, labelGap: 10,
    above: 42, below: 58, belowSmall: 32, brace: 9,
    labelFont: `600 15px ${FONT}`, valueFont: `600 17px ${FONT}`, smallFont: `500 12.5px ${FONT}`,
  };
  const MINI = {
    pad: 2, barH: 14, gap: 5, underGap: 6, minPiece: 6, labelGap: 0,
    above: 0, below: 0, belowSmall: 0, brace: 0,
    labelFont: '', valueFont: '', smallFont: '',
  };

  let uid = 0;
  let ctx2d = null;

  function measure(text, font) {
    if (!text) return 0;
    if (ctx2d === null) {
      try { ctx2d = document.createElement('canvas').getContext('2d') || false; } catch (e) { ctx2d = false; }
    }
    if (!ctx2d) return String(text).length * 9;
    ctx2d.font = font;
    return ctx2d.measureText(String(text)).width;
  }

  function el(name, attrs, parent, text) {
    const e = document.createElementNS(SVGNS, name);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      e.setAttribute(k, String(v));
    }
    if (text !== undefined) e.textContent = text;
    if (parent) parent.appendChild(e);
    return e;
  }

  const r1 = v => Math.round(v * 10) / 10;

  /* A curly brace from x1 to x2 at y, its point d pixels up (dir -1) or
     down (dir 1). */
  function braceH(x1, x2, y, dir, d) {
    const mid = (x1 + x2) / 2;
    const q = Math.min(d, (x2 - x1) / 4);
    const yb = y + dir * d / 2, yt = y + dir * d;
    return `M${r1(x1)} ${r1(y)}Q${r1(x1)} ${r1(yb)} ${r1(x1 + q)} ${r1(yb)}L${r1(mid - q)} ${r1(yb)}`
      + `Q${r1(mid)} ${r1(yb)} ${r1(mid)} ${r1(yt)}Q${r1(mid)} ${r1(yb)} ${r1(mid + q)} ${r1(yb)}`
      + `L${r1(x2 - q)} ${r1(yb)}Q${r1(x2)} ${r1(yb)} ${r1(x2)} ${r1(y)}`;
  }
  /* A brace from y1 to y2 at x, pointing right. */
  function braceV(x, y1, y2, d) {
    const mid = (y1 + y2) / 2;
    const q = Math.min(d, (y2 - y1) / 4);
    const xb = x + d / 2, xt = x + d;
    return `M${r1(x)} ${r1(y1)}Q${r1(xb)} ${r1(y1)} ${r1(xb)} ${r1(y1 + q)}L${r1(xb)} ${r1(mid - q)}`
      + `Q${r1(xb)} ${r1(mid)} ${r1(xt)} ${r1(mid)}Q${r1(xb)} ${r1(mid)} ${r1(xb)} ${r1(mid + q)}`
      + `L${r1(xb)} ${r1(y2 - q)}Q${r1(xb)} ${r1(y2)} ${r1(x)} ${r1(y2)}`;
  }

  /* ── Where everything goes ────────────────────────────────────────────── */

  function layout(m, W) {
    const Z = m.mini ? MINI : FULL;
    const rows = m.rows || [];
    const values = m.values || {};
    const groups = (m.groups || []).filter(g => rows.some(rw => rw.key === g.row));
    const top = rows.filter(rw => !rw.under);
    const multi = top.length > 1;
    const atEnd = rw => multi || !!rw.under;          // the whole's number at the block's end

    const labelW = m.mini ? 0 : Math.min(W * 0.3, Math.max(0, ...rows.map(rw => measure(rw.label, Z.labelFont))));
    const x0 = Z.pad + (labelW ? labelW + Z.labelGap : 0);
    let endW = 0;
    if (!m.mini) {
      for (const rw of rows) {
        if (!atEnd(rw) || rw.pieces.length === 1 && !rw.under) continue;
        const t = values[rw.key];
        if (t !== undefined) endW = Math.max(endW, measure(t, Z.valueFont) + 14);
        else if (m.targets) endW = Math.max(endW, 52);
      }
      // a one-piece block whose number will not fit inside it has it at its end
    }
    const totalOn = !m.mini && multi && (values.T !== undefined || m.targets);
    const totalW = m.mini && m.miniTotal ? 7
      : totalOn ? Z.brace + 10 + Math.max(values.T !== undefined ? measure(values.T, Z.valueFont) : 0, m.targets ? 44 : 0) + 4 : 0;
    const x1 = W - Z.pad - endW - totalW;

    const wt = p => (m.schematic ? (p.k === 'bit' ? 1 : 0.55) : Math.max(Number(p.w) || 0, 1e-6));
    const len = rw => rw.pieces.reduce((s, p) => s + wt(p), 0);
    const span = Math.max(40, x1 - x0);
    const maxLen = Math.max(1e-6, ...top.map(len));
    const most = Math.max(1, ...top.map(rw => rw.pieces.length));
    const minPiece = Math.min(Z.minPiece, span / most);
    let scale = span / maxLen;
    const geo = {};
    for (let pass = 0; pass < 8; pass++) {
      let over = 0;
      for (const rw of top) {
        let x = x0;
        const xs = [], ws = [];
        for (const p of rw.pieces) {
          const w = Math.max(minPiece, wt(p) * scale);
          xs.push(x); ws.push(w); x += w;
        }
        geo[rw.key] = { xs, ws, end: x };
        over = Math.max(over, x - (x0 + span));
      }
      if (over <= 0.5) break;
      scale *= Math.max(0.5, (span - over) / span);
    }
    for (const rw of rows.filter(r => r.under)) {
      const pg = geo[rw.under.row];
      if (!pg) { geo[rw.key] = { xs: [], ws: [], end: x0 }; continue; }
      const from = Math.min(rw.under.from, pg.xs.length - 1), to = Math.min(rw.under.to, pg.xs.length - 1);
      const xa = pg.xs[from], xb = pg.xs[to] + pg.ws[to];
      const tot = len(rw) || 1;
      let x = xa;
      const xs = [], ws = [];
      for (const p of rw.pieces) { const w = (xb - xa) * wt(p) / tot; xs.push(x); ws.push(w); x += w; }
      geo[rw.key] = { xs, ws, end: xb };
    }

    // A number fits inside a piece, or goes under it on a small brace.
    const fits = (t, w) => measure(t, Z.valueFont) + 10 <= w;
    let y = Z.pad;
    rows.forEach((rw, i) => {
      const g = geo[rw.key];
      const one = rw.pieces.length === 1 && !rw.under;
      const above = !m.mini && !multi && !rw.under && rw.pieces.length > 1 && (values[rw.key] !== undefined || m.targets) ? Z.above : 0;
      const gs = groups.filter(gr => gr.row === rw.key && !gr.link);
      let below = 0;
      if (!m.mini) {
        if (gs.length) below = Z.below;
        rw.pieces.forEach((p, j) => {
          const t = one ? values[rw.key] : values[`${rw.key}.${j}`];
          if (t !== undefined && !fits(t, g.ws[j])) below = Math.max(below, Z.belowSmall);
        });
      }
      if (i > 0) y += rw.under ? Z.underGap : Z.gap;
      y += above;
      g.y = y; g.above = above; g.below = below; g.one = one; g.atEnd = atEnd(rw);
      y += Z.barH + below;
    });
    return { Z, W, H: Math.ceil(y + Z.pad), x0, x1, labelW, geo, multi, totalOn, groups, fits, endW, totalW, miniTotal: !!(m.mini && m.miniTotal) };
  }

  /* ── Drawing ──────────────────────────────────────────────────────────── */

  function render(svg, m, opts) {
    const o = opts || {};
    const W = Math.max(120, Math.floor(o.width || svg.clientWidth || 320));
    const L = layout(m, W);
    const { Z, geo } = L;
    const values = m.values || {};
    const id = `bm${++uid}`;
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    svg.setAttribute('viewBox', `0 0 ${W} ${L.H}`);
    svg.setAttribute('width', W);
    svg.setAttribute('height', L.H);
    svg.classList.toggle('is-mini', !!m.mini);

    const defs = el('defs', {}, svg);
    for (let c = 0; c < 4; c++) {
      const pat = el('pattern', { id: `${id}-h${c}`, patternUnits: 'userSpaceOnUse', width: 8, height: 8, patternTransform: 'rotate(45)' }, defs);
      el('rect', { width: 8, height: 8, class: `bm-hatch-bg bm-c${c}` }, pat);
      el('line', { x1: 0, y1: 0, x2: 0, y2: 8, class: `bm-hatch-line bm-c${c}` }, pat);
    }

    const out = { width: W, height: L.H, slots: [], pieces: [] };
    const gRows = el('g', { class: 'bm-rows' }, svg);
    const gNotes = el('g', { class: 'bm-notes' }, svg);
    const gTargets = el('g', { class: 'bm-targets' }, svg);
    const gHits = el('g', { class: 'bm-hits' }, svg);
    const slotRect = {};
    const addSlot = (sid, x, y, w, h) => {
      if (slotRect[sid]) return;
      slotRect[sid] = { x, y, w, h };
      out.slots.push({ id: sid, x, y, w, h });
    };
    const isQ = t => t === '?';
    const valueClass = sid => (sid === m.answer ? 'bm-val bm-ans' : isQ(values[sid]) ? 'bm-val bm-q' : 'bm-val');
    const text = (parent, x, y, t, cls, anchor) => el('text', { x: r1(x), y: r1(y), class: cls, 'text-anchor': anchor || 'middle', 'dominant-baseline': 'central' }, parent, t);

    for (const rw of m.rows) {
      const g = geo[rw.key];
      if (!g) continue;
      const y = g.y, h = Z.barH;
      const xa = g.xs[0], xb = g.end;
      const grow = el('g', { class: `bm-row bm-c${rw.color || 0}`, 'data-row': rw.key }, gRows);
      if (!m.mini) text(grow, L.x0 - Z.labelGap, y + h / 2, rw.label, 'bm-lab', 'end');
      const clip = el('clipPath', { id: `${id}-c${rw.key}` }, defs);
      const rad = m.mini ? 2.5 : 7;
      el('rect', { x: r1(xa), y: r1(y), width: r1(xb - xa), height: h, rx: rad }, clip);
      const gp = el('g', { 'clip-path': `url(#${id}-c${rw.key})` }, grow);
      rw.pieces.forEach((p, j) => {
        const x = g.xs[j], w = g.ws[j];
        const marked = p.marked || (m.groups || []).some(gr => gr.row === rw.key && gr.mark && gr.pieces.includes(j));
        el('rect', {
          x: r1(x), y: r1(y), width: r1(w), height: h,
          class: `bm-pc is-${p.k}${marked ? ' is-marked' : ''}`,
          fill: marked ? `url(#${id}-h${rw.color || 0})` : null,
        }, gp);
        if (j > 0) el('line', { x1: r1(x), y1: r1(y), x2: r1(x), y2: r1(y + h), class: `bm-div${p.k === 'del' || rw.pieces[j - 1].k === 'del' ? ' is-del' : ''}` }, gp);
        out.pieces.push({ id: `${rw.key}.${j}`, x, y, w, h, k: p.k, marked: !!marked });
      });
      el('rect', { x: r1(xa), y: r1(y), width: r1(xb - xa), height: h, rx: rad, class: 'bm-outline' }, grow);
      if (m.mini) continue;

      // Numbers and names in the pieces.
      rw.pieces.forEach((p, j) => {
        const x = g.xs[j], w = g.ws[j];
        const sid = g.one ? rw.key : `${rw.key}.${j}`;
        const t = values[sid];
        const showName = p.name && w >= measure(p.name, Z.smallFont) + 8;
        if (showName) text(gNotes, x + w / 2, y + (t !== undefined && L.fits(t, w) ? 12 : h / 2), p.name, 'bm-name');
        if (t === undefined) return;
        if (L.fits(t, w)) {
          text(gNotes, x + w / 2, y + (showName ? h / 2 + 8 : h / 2), t, valueClass(sid));
        } else {
          el('path', { d: braceH(x + 2, x + w - 2, y + h + 4, 1, 6), class: 'bm-brace' }, gNotes);
          text(gNotes, x + w / 2, y + h + 20, t, valueClass(sid));
        }
      });

      // The whole: above a block alone, at the end of a block among others.
      if (!g.one) {
        const t = values[rw.key];
        if (g.atEnd) {
          if (t !== undefined) text(gNotes, xb + 10, y + h / 2, t, valueClass(rw.key), 'start');
        } else if (t !== undefined || m.targets) {
          const by = y - 4;
          el('path', { d: braceH(xa + 2, xb - 2, by, -1, Z.brace), class: `bm-brace${t === undefined ? ' is-target' : ''}` }, t === undefined ? gTargets : gNotes);
          if (t !== undefined) text(gNotes, (xa + xb) / 2, by - Z.brace - 13, t, valueClass(rw.key));
        }
      }
    }

    // Groups: a brace under, with the name and the number; the rest has
    // dashed lines down to its extra block instead.
    for (const gr of L.groups) {
      const rw = m.rows.find(r => r.key === gr.row);
      const g = geo[gr.row];
      if (!g || !gr.pieces.length) continue;
      const a = Math.min(...gr.pieces), b = Math.max(...gr.pieces);
      if (a >= g.xs.length) continue;
      const xa = g.xs[a], xb = g.xs[Math.min(b, g.xs.length - 1)] + g.ws[Math.min(b, g.ws.length - 1)];
      if (m.mini) continue;
      if (gr.link) {
        const under = geo[gr.link];
        if (!under) continue;
        const y2 = under.y;
        for (const x of [xa, xb]) el('line', { x1: r1(x), y1: r1(g.y + Z.barH), x2: r1(x), y2: r1(y2), class: 'bm-link' }, gNotes);
        continue;
      }
      const whole = gr.pieces.length === rw.pieces.length;
      const sid = gr.pieces.length === 1 ? `${rw.key}.${a}` : whole ? rw.key : gr.id;
      const t = gr.pieces.length === 1 || whole ? undefined : values[sid];
      const by = g.y + Z.barH + 4;
      el('path', { d: braceH(xa + 2, xb - 2, by, 1, Z.brace), class: 'bm-brace' }, gNotes);
      const mid = (xa + xb) / 2;
      if (gr.label) text(gNotes, mid, by + Z.brace + 10, gr.label, 'bm-glab');
      if (t !== undefined) text(gNotes, mid, by + Z.brace + 29, t, valueClass(sid));
    }

    // All the blocks together (a small picture has the brace alone).
    if (L.miniTotal) {
      const tops = m.rows.filter(rw => !rw.under && geo[rw.key]);
      const ya = geo[tops[0].key].y, yb = geo[tops[tops.length - 1].key].y + Z.barH;
      el('path', { d: braceV(L.W - Z.pad - 6, ya, yb, 5), class: 'bm-brace' }, gNotes);
    }
    if (L.totalOn) {
      const tops = m.rows.filter(rw => !rw.under && geo[rw.key]);
      const ya = geo[tops[0].key].y, yb = geo[tops[tops.length - 1].key].y + Z.barH;
      const bx = L.W - Z.pad - L.totalW + 4;
      const t = values.T;
      el('path', { d: braceV(bx, ya, yb, Z.brace), class: `bm-brace${t === undefined ? ' is-target' : ''}` }, t === undefined ? gTargets : gNotes);
      if (t !== undefined) text(gNotes, bx + Z.brace + 8, (ya + yb) / 2, t, valueClass('T'), 'start');
    }

    // The places a number can go, and what a tap on them hits.
    if (!m.mini) {
      for (const rw of m.rows) {
        const g = geo[rw.key];
        if (!g) continue;
        const y = g.y, h = Z.barH, xa = g.xs[0], xb = g.end;
        if (g.one) {
          addSlot(rw.key, xa, y, xb - xa, h);
        } else {
          if (g.atEnd) addSlot(rw.key, xb + 2, y, Math.max(48, L.endW - 2), h);
          else addSlot(rw.key, xa, y - Z.above + 2, xb - xa, Z.above - 4);
          rw.pieces.forEach((p, j) => addSlot(`${rw.key}.${j}`, g.xs[j], y, g.ws[j], h));
        }
      }
      for (const gr of L.groups) {
        const rw = m.rows.find(r => r.key === gr.row);
        const g = geo[gr.row];
        if (!g || gr.link || gr.pieces.length < 2 || gr.pieces.length === rw.pieces.length) continue;
        const a = Math.min(...gr.pieces), b = Math.max(...gr.pieces);
        const xa = g.xs[a], xb = g.xs[b] + g.ws[b];
        addSlot(gr.id, xa, g.y + Z.barH + 2, xb - xa, Math.max(30, g.below - 4));
      }
      if (L.totalOn) {
        const tops = m.rows.filter(rw => !rw.under && geo[rw.key]);
        const ya = geo[tops[0].key].y, yb = geo[tops[tops.length - 1].key].y + Z.barH;
        const bx = L.W - Z.pad - L.totalW + 4;
        addSlot('T', bx - 4, ya, L.totalW, yb - ya);
      }
      if (m.targets) {
        for (const s of out.slots) {
          if (values[s.id] !== undefined) continue;
          const isPiece = /\.\d+$/.test(s.id) || (geo[s.id] && geo[s.id].one);
          if (isPiece) {
            el('rect', { x: r1(s.x + 4), y: r1(s.y + 4), width: r1(Math.max(4, s.w - 8)), height: r1(s.h - 8), rx: 5, class: 'bm-target is-piece' }, gTargets);
          } else {
            const bw = 40, bh = 26;
            let cx = s.x + s.w / 2, cy = s.y + s.h / 2;
            if (s.id === 'T') cx = s.x + Z.brace + 30;
            else if (geo[s.id] && geo[s.id].atEnd) cx = s.x + 8 + bw / 2;
            else if (s.id.includes(':')) cy = geo[s.id.split(':')[0]].y + Z.barH + 4 + Z.brace + 29;
            else cy = s.y + bh / 2 - 2;
            el('rect', { x: r1(cx - bw / 2), y: r1(cy - bh / 2), width: bw, height: bh, rx: 6, class: 'bm-target bm-target-box' }, gTargets);
            if (s.id.includes(':')) {
              const g = geo[s.id.split(':')[0]];
              el('path', { d: braceH(s.x + 2, s.x + s.w - 2, g.y + Z.barH + 4, 1, Z.brace), class: 'bm-brace is-target' }, gTargets);
            }
          }
        }
      }
      for (const [cls, sid] of [['bm-hl', m.hl], ['bm-bad', m.bad]]) {
        const s = sid && slotRect[sid];
        if (s) el('rect', { x: r1(s.x - 3), y: r1(s.y - 3), width: r1(s.w + 6), height: r1(s.h + 6), rx: 9, class: cls }, gTargets);
      }
      // What can be tapped can be reached with the keyboard too, and is named.
      if (o.slots) {
        for (const s of out.slots) {
          el('rect', {
            x: r1(s.x), y: r1(s.y), width: r1(Math.max(s.w, 24)), height: r1(Math.max(s.h, 24)), class: 'bm-hit', 'data-slot': s.id,
            tabindex: 0, role: 'button', 'aria-label': o.slotName ? o.slotName(s.id) : s.id,
          }, gHits);
        }
      }
      if (m.markRow) {
        out.pieces.filter(pp => pp.id.startsWith(`${m.markRow}.`)).forEach((pc, i) => {
          el('rect', {
            x: r1(pc.x), y: r1(pc.y), width: r1(pc.w), height: pc.h, class: 'bm-hit bm-hit-piece', 'data-piece': pc.id,
            tabindex: 0, role: 'button', 'aria-pressed': String(pc.marked), 'aria-label': `Bit ${i + 1}`,
          }, gHits);
        });
      }
    }
    return out;
  }

  /* The model in words, for a screen reader. */
  function describe(m) {
    const values = m.values || {};
    const parts = [];
    for (const rw of m.rows) {
      const nbits = rw.pieces.filter(p => p.k === 'bit').length;
      const ndel = rw.pieces.length - nbits;
      let s = `${rw.label}: ${nbits === 1 ? '1 bit' : `${nbits} bitar`}${ndel ? ` och ${ndel === 1 ? 'en annan bit' : `${ndel} andra bitar`}` : ''}`;
      const v = values[rw.key];
      if (v !== undefined) s += `, ${v === '?' ? 'frågetecken' : v}`;
      parts.push(s);
    }
    if (values.T !== undefined) parts.push(`Tillsammans: ${values.T === '?' ? 'frågetecken' : values.T}`);
    return parts.join('. ');
  }

  return { render, layout, describe, measure, braceH, braceV };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = BM_DRAW;
