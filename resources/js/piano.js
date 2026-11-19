/* ==========================================================================
   PIANO - THE PAGE (piano.html, "Pianoskolan")

   A path of short lessons for a child learning the piano, with Christmas
   songs along the way. The page listens to the piano through the microphone
   and answers what is played; the keys on the screen, the computer's
   keyboard and a MIDI keyboard do the same job.

   What is taught is in piano-songs.js, what counts as right and what is
   kept between visits in piano-game.js, what the microphone hears in
   piano-ear.js and what the page sounds like in piano-sound.js. This file
   draws: the path, the staff, the keyboard, and one exercise at a time.

     info    a card that explains, with the keys or the notes it is about
     find    "play C": one key
     name    "which note is this?": a choice of names
     echo    the page plays a few notes, the pupil plays them back
     play    a melody from the staff at the pupil's own pace: the page
             waits for the right key
     tempo   the same melody in time, after a count-in

   THE PAGE HEARS ITSELF. Every sound the page makes would come back through
   the microphone as a key played, so the listener is deaf while the page
   sounds (deafen), and a melody being played by the pupil is never answered
   with sounds note by note - only when it is over.
   ========================================================================== */

const PN = (() => {
  'use strict';

  const S = PN_SONGS;
  const G = PN_GAME;
  const KEY = 'piano.v1';
  /* From a key going down to the listener's clock: the sound's way through
     the microphone and the browser, on top of what the listener allows for. */
  const MIC_LAG = 40;
  const FRAME_MS = 18;
  const IDLE_STOP_MS = 5 * 60 * 1000;
  const SVGNS = 'http://www.w3.org/2000/svg';

  let store = G.blank();
  let dom = {};
  let view = 'home';
  let tab = 'path';
  let run = null;          // the lesson or song under way
  let ctl = null;          // the exercise on screen
  let goFn = null;
  let altFn = null;
  let askFn = null;
  let timers = [];
  let staff = null;
  let keys = null;
  let speed = 0.8;         // the song list's tempo, as a share of the song's own
  let ownId = null;        // the own song being edited
  let wakeLock = null;
  let clock = null;        // the tests' day
  let tempoScale = 1;      // the tests' hurry
  let midiAccess = null;

  const today = () => clock || G.dayKey(new Date());
  const style = () => store.settings.names;
  const nameOf = n => S.nameOf(n, style());
  const sayName = n => S.sayName(n, style());
  const fill = text => S.fillNames(text, style());

  /* ── Small tools ──────────────────────────────────────────────────────── */

  function h(tag, attrs, ...kids) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === 'class') e.className = v;
      else if (k === 'text') e.textContent = v;
      else if (k === 'icon') e.innerHTML = ICON[v] || '';
      else e.setAttribute(k, v === true ? '' : v);
    }
    for (const kid of kids.flat()) {
      if (kid === null || kid === undefined || kid === false) continue;
      e.append(kid);
    }
    return e;
  }

  function sv(name, attrs, ...kids) {
    const e = document.createElementNS(SVGNS, name);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === 'text') e.textContent = v;
      else e.setAttribute(k, v);
    }
    for (const kid of kids.flat()) if (kid) e.append(kid);
    return e;
  }

  /* The page's pictures: 24 by 24, drawn with the text's colour. */
  const svgIcon = (body, more) => `<svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"${more || ''}>${body}</svg>`;
  const ICON = {
    star: svgIcon('<path fill="currentColor" stroke-width="1.4" d="M12 2.9l2.8 5.8 6.3.9-4.6 4.4 1.1 6.3L12 17.3l-5.6 3 1.1-6.3L2.9 9.6l6.3-.9z"/>'),
    flame: svgIcon('<path fill="currentColor" stroke-width="1.2" d="M12.4 2.6c.5 3.2 5 5.3 5 10.4a5.4 5.4 0 0 1-10.8 0c0-2 .8-3.5 2-4.7.1 1.5.7 2.5 1.7 3 .1-3.3.7-6.3 2.1-8.7z"/>'),
    lock: svgIcon('<rect x="5.5" y="10.5" width="13" height="9.5" rx="2"/><path d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5"/>'),
    mic: svgIcon('<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v3"/>'),
    note: svgIcon('<ellipse cx="8.5" cy="17.5" rx="3.4" ry="2.6" fill="currentColor" transform="rotate(-20 8.5 17.5)"/><path d="M11.7 16.8V4.5c2.6.6 4.8 2.2 5 5.3"/>'),
    notes: svgIcon('<ellipse cx="6.8" cy="18" rx="2.9" ry="2.2" fill="currentColor" transform="rotate(-20 6.8 18)"/><ellipse cx="16.8" cy="16" rx="2.9" ry="2.2" fill="currentColor" transform="rotate(-20 16.8 16)"/><path d="M9.5 17.4V6.5l10-2v11"/><path d="M9.5 9.7l10-2" stroke-width="2.6"/>'),
    keys: svgIcon('<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M9 5v14M15 5v14"/><path d="M9 5v8M15 5v8" stroke-width="3.4" stroke-linecap="butt"/>'),
    eye: svgIcon('<path d="M2.5 12s3.5-6.2 9.5-6.2S21.5 12 21.5 12s-3.5 6.2-9.5 6.2S2.5 12 2.5 12z"/><circle cx="12" cy="12" r="2.6" fill="currentColor"/>'),
    hand: svgIcon('<path d="M7.5 12.5V6.3a1.5 1.5 0 0 1 3 0v4.2V4.8a1.5 1.5 0 0 1 3 0v5.7V6a1.5 1.5 0 0 1 3 0v5.5V8.8a1.4 1.4 0 0 1 2.8 0v5.7c0 3.8-2.7 6.5-6.3 6.5-2.9 0-4.4-1.2-5.8-3.5l-2.5-4.2a1.5 1.5 0 0 1 2.5-1.6z"/>'),
    trophy: svgIcon('<path d="M7.5 4h9v5.5a4.5 4.5 0 0 1-9 0z"/><path d="M7.5 5.5H4.3c0 3 1.3 4.7 3.7 5M16.5 5.5h3.2c0 3-1.3 4.7-3.7 5M12 14v3.5M8.5 20h7M9.5 17.5h5"/>'),
    target: svgIcon('<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="4.6"/><circle cx="12" cy="12" r="1.2" fill="currentColor"/>'),
    tree: svgIcon('<path d="M12 2.8l4 5.2h-2.2l3.7 4.8h-2.3l3.8 5H5l3.8-5H6.5l3.7-4.8H8z"/><path d="M12 17.8V21"/>'),
    gift: svgIcon('<rect x="4" y="10" width="16" height="10.5" rx="1.5"/><path d="M3 7h18v3H3zM12 7v13.5M12 7c-1.5-3.5-5.5-3.7-5.5-1.5S9 7 12 7zm0 0c1.5-3.5 5.5-3.7 5.5-1.5S15 7 12 7z"/>'),
    pen: svgIcon('<path d="M4 20l1-4.5L16.2 4.3a2 2 0 0 1 2.8 0l.7.7a2 2 0 0 1 0 2.8L8.5 19z"/><path d="M14.5 6l3.5 3.5"/>'),
    check: svgIcon('<path d="M5 12.5l4.5 4.5L19 7.5" stroke-width="2.6"/>'),
    play: svgIcon('<path fill="currentColor" d="M8 5.5v13l10.5-6.5z"/>'),
    ear: svgIcon('<path d="M7 9.5a5.5 5.5 0 0 1 11 0c0 3.5-3.2 4.2-3.2 7.3a3.3 3.3 0 0 1-6 1.7"/><path d="M10 10a2.6 2.6 0 0 1 5 .5"/>'),
    plus: svgIcon('<path d="M12 5v14M5 12h14" stroke-width="2.4"/>'),
  };

  function later(fn, ms) {
    const id = setTimeout(() => {
      timers = timers.filter(t => t !== id);
      fn();
    }, Math.max(0, ms));
    timers.push(id);
    return id;
  }

  function clearTimers() {
    for (const id of timers) clearTimeout(id);
    timers = [];
  }

  /* ── What is kept ─────────────────────────────────────────────────────── */

  function load() {
    try {
      store = G.validate(JSON.parse(localStorage.getItem(KEY)));
    } catch (e) {
      store = G.blank();
    }
    PN_SOUND.setOn(store.settings.sound);
  }

  function save() {
    try {
      localStorage.setItem(KEY, JSON.stringify(store));
    } catch (e) {
      ignoreFailure('piano: saving', e);
    }
  }

  /* ── Sound, and the listener deaf while it lasts ──────────────────────── */

  function deafen() {
    if (mic.ear) mic.ear.deaf(PN_SOUND.busyUntil());
  }

  function sound(midi, opts) {
    PN_SOUND.note(midi, opts);
    deafen();
  }

  function effect(name, delay) {
    PN_SOUND.effect(name, delay);
    deafen();
  }

  /**
   * Play notes as the page: each sounds at its moment (so that stopping
   * stops it), onNote(i) as it does, onEnd() after the last. Returns the
   * function that stops it.
   */
  function playback(notes, bpm, onNote, onEnd) {
    const beat = 60 / bpm;
    const first = notes.length ? notes[0].start : 0;
    const ids = [];
    let end = 0;
    notes.forEach((n, i) => {
      const at = (n.start - first) * beat;
      const dur = n.beats * beat;
      ids.push(later(() => {
        if (!n.rest) sound(n.midi, { dur: Math.max(0.12, dur * 0.9) });
        onNote(i, n);
      }, at * 1000 + 60));
      end = at + dur;
    });
    ids.push(later(() => onEnd(), end * 1000 + 200));
    return () => { for (const id of ids) clearTimeout(id); };
  }

  /* ── The staff ────────────────────────────────────────────────────────── */

  const yOf = step => 80 - (step - 30) * 5;

  /* The G clef, drawn as one line: staff's top line at y 0, the G line at 30. */
  const CLEF = 'M-5.5 47.5c-.3 5.4 7.9 6.3 8.3.3.2-3-1-9.5-2.3-17.8C-1 20.5-3.2 8.5-3 1.5-2.8-5.5 0-11.5 3-12.5c2.3-.8 3.8 3 3.3 7.5C5.5 2.5-9.5 10-9.5 22.5c0 7 4.7 12.3 10.8 12.3 5 0 8.5-3.5 8.5-7.8 0-4.3-3.3-7.2-7-7.2-3.5 0-6 2.5-6 5.6 0 2.3 1.5 4.1 3.4 4.6';

  /* A box of notes whose size changes - a card appears beside it, the phone
     is turned - puts its notes back in sight. */
  const fitWatch = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(entries => {
    for (const e of entries) if (e.target.pnFit) e.target.pnFit();
  });

  function shape(beats) {
    if (beats >= 4) return { open: true, stem: false, flags: 0, dot: beats >= 6 };
    if (beats >= 2) return { open: true, stem: true, flags: 0, dot: beats >= 3 };
    if (beats >= 1) return { open: false, stem: true, flags: 0, dot: beats >= 1.5 };
    if (beats >= 0.5) return { open: false, stem: true, flags: 1, dot: beats >= 0.75 };
    return { open: false, stem: true, flags: 2, dot: false };
  }

  function drawRest(g, n, x) {
    if (n.beats >= 3) g.append(sv('rect', { x: x - 7, y: 50, width: 14, height: 5, class: 'pn-ink' }));
    else if (n.beats >= 2) g.append(sv('rect', { x: x - 7, y: 55, width: 14, height: 5, class: 'pn-ink' }));
    else if (n.beats >= 1) g.append(sv('path', { d: `M${x - 3} 46l6 8-5 6 6 8c-5-2-8.5 1-5.5 6`, class: 'pn-line' }));
    else g.append(sv('path', { d: `M${x + 3.5} 54l-4.5 15M${x + 3.5} 54c-1.5 2.5-4 3.5-6.5 2.5`, class: 'pn-line' }));
  }

  /**
   * Draw notes on a staff inside `host`. opts: time, letters, fingers (the
   * key under the thumb), fing (a finger per sounding note, as a string),
   * plain (whole notes with no rhythm, for explaining).
   *
   * The drawing is only as tall as what is on it - the staff and its clef,
   * the highest and the lowest note, the rows of fingers and letters where
   * there are any - so that a low box (a phone on its side) is filled with
   * notes and not with empty paper.
   *
   * Returns { now, mark, shake, clear, playhead, fit }.
   */
  function drawStaff(host, notes, opts) {
    const o = opts || {};
    host.textContent = '';
    const per = o.time || 4;
    const xs = [];
    const barXs = [];
    let x = o.plain ? 62 : 78;
    notes.forEach((n, i) => {
      if (i > 0 && !o.plain && n.bar !== notes[i - 1].bar) { barXs.push(x + 1); x += 13; }
      xs.push(x + 11);
      x += o.plain ? 46 : 18 + 16 * Math.min(4, n.beats);
    });
    const W = x + (o.plain ? 14 : 20);

    // Two eighth notes that share a beat share a beam.
    const beamWith = new Map();
    if (!o.plain) {
      for (let i = 0; i + 1 < notes.length; i++) {
        const a = notes[i], b = notes[i + 1];
        if (a.rest || b.rest || a.beats !== 0.5 || b.beats !== 0.5 || !Number.isInteger(a.beat) || a.bar !== b.bar) continue;
        const up = (a.step + b.step) / 2 < 34;
        const y = up ? Math.min(yOf(a.step), yOf(b.step)) - 29 : Math.max(yOf(a.step), yOf(b.step)) + 29;
        beamWith.set(i, { up, y, first: true, other: i + 1 });
        beamWith.set(i + 1, { up, y, first: false, other: i });
        i++;
      }
    }

    // Each note's shape, and where its stem ends.
    const geo = notes.map((n, i) => {
      if (n.rest) return null;
      const y = yOf(n.step);
      const sh = o.plain ? { open: true, stem: false, flags: 0, dot: false } : shape(n.beats);
      const beam = beamWith.get(i) || null;
      const up = beam ? beam.up : n.step < 34;
      const end = !sh.stem ? y : beam ? beam.y : up ? y - 31 : y + 31;
      return { y, sh, beam, up, end };
    });

    // How high and how low the drawing reaches: the clef, then the notes.
    const thumb = o.fingers ? S.fromMidi(o.fingers).step : null;
    let top = 26;
    let bottom = 97;
    notes.forEach((n, i) => {
      const q = geo[i];
      if (!q) return;
      top = Math.min(top, q.y - (n.acc < 0 ? 14 : n.acc > 0 ? 11 : 6), q.end - 1);
      bottom = Math.max(bottom, q.y + (n.acc > 0 ? 10 : 6), q.end + 1);
    });
    const fingerY = o.fing || thumb !== null ? top - 5 : null;
    if (fingerY !== null) top = fingerY - 10;
    const letterY = o.letters ? bottom + 14 : null;
    if (letterY !== null) bottom = letterY + 3;
    top -= 4;
    bottom += 4;
    const H = bottom - top;

    const root = sv('svg', { class: 'pn-staff', viewBox: `0 ${top} ${W} ${H}`, role: 'img', 'aria-label': o.label || 'Noter' });
    root.style.aspectRatio = `${W} / ${H}`;
    // The stylesheet sizes the drawing by its own height, so that a note is
    // as large in a tall drawing as in a low one.
    root.style.setProperty('--pn-h', String(H));
    const cursor = sv('rect', { class: 'pn-cursor', x: -14, y: top + 2, width: 28, height: H - 4, rx: 9, visibility: 'hidden' });
    root.append(cursor);
    for (let k = 0; k < 5; k++) root.append(sv('line', { x1: 4, x2: W - 4, y1: 40 + 10 * k, y2: 40 + 10 * k, class: 'pn-staffline' }));
    root.append(sv('path', { d: CLEF, transform: 'translate(24 40)', class: 'pn-clef' }));
    if (!o.plain) {
      root.append(sv('text', { x: 56, y: 59, class: 'pn-timesig', text: String(per) }));
      root.append(sv('text', { x: 56, y: 79, class: 'pn-timesig', text: '4' }));
      for (const bx of barXs) root.append(sv('line', { x1: bx, x2: bx, y1: 40, y2: 80, class: 'pn-barline' }));
      root.append(sv('line', { x1: W - 10, x2: W - 10, y1: 40, y2: 80, class: 'pn-barline' }));
      root.append(sv('line', { x1: W - 5.5, x2: W - 5.5, y1: 40, y2: 80, class: 'pn-barline pn-barline-end' }));
    }

    let sounding = 0;
    const groups = notes.map((n, i) => {
      const g = sv('g', { class: 'pn-n' });
      const nx = xs[i];
      if (n.rest) {
        drawRest(g, n, nx);
        root.append(g);
        return g;
      }
      const { y, sh, beam, up, end } = geo[i];
      for (let e = 28; e >= n.step; e -= 2) g.append(sv('line', { x1: nx - 10, x2: nx + 10, y1: yOf(e), y2: yOf(e), class: 'pn-staffline pn-ledger' }));
      for (let e = 40; e <= n.step; e += 2) g.append(sv('line', { x1: nx - 10, x2: nx + 10, y1: yOf(e), y2: yOf(e), class: 'pn-staffline pn-ledger' }));
      if (n.acc < 0) g.append(sv('path', { d: `M${nx - 15.5} ${y - 13}v17c4-2 6.5-4.5 6.5-7.5 0-3.5-4.5-3.5-6.5-.5`, class: 'pn-line' }));
      if (n.acc > 0) g.append(sv('path', { d: `M${nx - 16} ${y - 8}v17M${nx - 11.5} ${y - 9.5}v17M${nx - 18.5} ${y - 1.5}l9.5-3M${nx - 18.5} ${y + 5}l9.5-3`, class: 'pn-line pn-sharp' }));
      const wide = !sh.stem;
      g.append(sv('ellipse', {
        cx: nx, cy: y, rx: wide ? 7.2 : 6.4, ry: 4.6, transform: `rotate(-22 ${nx} ${y})`,
        class: sh.open ? 'pn-head pn-head-open' : 'pn-head',
      }));
      const sx = up ? nx + 5.7 : nx - 5.7;
      if (sh.stem) {
        g.append(sv('line', { x1: sx, x2: sx, y1: up ? y - 1.5 : y + 1.5, y2: end, class: 'pn-stem' }));
        if (beam && beam.first) {
          const ox = beam.up ? xs[beam.other] + 5.7 : xs[beam.other] - 5.7;
          g.append(sv('rect', { x: Math.min(sx, ox) - 0.7, y: beam.up ? beam.y - 0.5 : beam.y - 4, width: Math.abs(ox - sx) + 1.4, height: 4.5, class: 'pn-ink' }));
        }
        if (!beam) {
          for (let f = 0; f < sh.flags; f++) {
            const fy = up ? end + 7 * f : end - 7 * f;
            g.append(sv('path', {
              d: up ? `M${sx} ${fy}c1 7 9 8.5 7.5 18.5-1-5.5-4.5-8-7.5-9.5z` : `M${sx} ${fy}c1-7 9-8.5 7.5-18.5-1 5.5-4.5 8-7.5 9.5z`,
              class: 'pn-ink',
            }));
          }
        }
      }
      if (sh.dot) g.append(sv('circle', { cx: nx + 11.5, cy: n.step % 2 === 0 ? y - 5 : y, r: 1.9, class: 'pn-ink' }));
      if (o.letters) g.append(sv('text', { x: nx, y: letterY, class: 'pn-letter', text: nameOf(n) }));
      let finger = null;
      if (o.fing) finger = o.fing[sounding] || null;
      else if (thumb !== null && n.step - thumb >= 0 && n.step - thumb <= 4) finger = String(n.step - thumb + 1);
      if (finger) g.append(sv('text', { x: nx, y: fingerY, class: 'pn-finger', text: finger }));
      sounding++;
      root.append(g);
      return g;
    });

    const head = sv('line', { class: 'pn-playhead', x1: 0, x2: 0, y1: top + 4, y2: bottom - 4, visibility: 'hidden' });
    root.append(head);
    host.append(root);

    const STATES = ['is-right', 'is-missed', 'is-now', 'is-shake'];
    let lastX = xs.length ? xs[0] : 0;

    /* Keep x in sight: the notes scroll under the window of the box. */
    function follow(fx, smooth) {
      lastX = fx;
      const scale = root.getBoundingClientRect().height / H;
      if (!(scale > 0)) return;
      const total = W * scale;
      const room = host.clientWidth;
      const tx = total <= room ? (room - total) / 2 : Math.max(room - total, Math.min(0, room * 0.36 - fx * scale));
      root.style.transition = smooth ? 'transform .28s ease' : 'none';
      root.style.transform = `translateX(${Math.round(tx)}px)`;
    }

    function xAt(beat) {
      if (!notes.length) return 0;
      if (beat <= notes[0].start) return xs[0] + (beat - notes[0].start) * 34;
      for (let i = 0; i + 1 < notes.length; i++) {
        if (beat < notes[i + 1].start) return xs[i] + (xs[i + 1] - xs[i]) * (beat - notes[i].start) / (notes[i + 1].start - notes[i].start);
      }
      const lastNote = notes[notes.length - 1];
      return xs[xs.length - 1] + Math.min(1, (beat - lastNote.start) / lastNote.beats) * (W - 12 - xs[xs.length - 1]);
    }

    follow(lastX, false);
    host.pnFit = () => follow(lastX, false);
    if (fitWatch) fitWatch.observe(host);
    return {
      now(i) {
        for (const g of groups) g.classList.remove('is-now');
        if (i === null || i === undefined || !groups[i]) { cursor.setAttribute('visibility', 'hidden'); return; }
        groups[i].classList.add('is-now');
        cursor.setAttribute('visibility', 'visible');
        cursor.setAttribute('transform', `translate(${xs[i]} 0)`);
        follow(xs[i], true);
      },
      mark(i, cls) {
        if (!groups[i]) return;
        groups[i].classList.remove(...STATES);
        if (cls) groups[i].classList.add(cls);
      },
      shake(i) {
        const g = groups[i];
        if (!g) return;
        g.classList.remove('is-shake');
        void g.getBoundingClientRect();
        g.classList.add('is-shake');
      },
      clear() {
        for (const g of groups) g.classList.remove(...STATES);
        cursor.setAttribute('visibility', 'hidden');
        head.setAttribute('visibility', 'hidden');
      },
      playhead(beat) {
        if (beat === null) { head.setAttribute('visibility', 'hidden'); return; }
        const px = xAt(beat);
        head.setAttribute('visibility', 'visible');
        head.setAttribute('transform', `translate(${px.toFixed(1)} 0)`);
        follow(px, false);
      },
      fit: () => follow(lastX, false),
      states: () => groups.map(g => STATES.find(s => g.classList.contains(s)) || ''),
      count: notes.length,
    };
  }

  const NO_STAFF = { now() {}, mark() {}, shake() {}, clear() {}, playhead() {}, fit() {}, states: () => [], count: 0 };

  function showStaff(notes, opts) {
    dom.staff.hidden = false;
    staff = drawStaff(dom.staff, notes, opts);
    return staff;
  }

  function hideStaff() {
    dom.staff.hidden = true;
    dom.staff.textContent = '';
    staff = NO_STAFF;
  }

  /* ── The keyboard ─────────────────────────────────────────────────────── */

  const isBlack = midi => [1, 3, 6, 8, 10].includes(((midi % 12) + 12) % 12);

  /* The keys to draw for some notes: from middle C, a whole octave at least. */
  function rangeFor(midis) {
    const list = midis.filter(m => m !== null && m !== undefined);
    const min = list.length ? Math.min(...list) : 60;
    const max = list.length ? Math.max(...list) : 72;
    const lo = min >= 60 ? 60 : min >= 55 ? 55 : 48;
    const hi = max <= 72 ? 72 : max <= 77 ? 77 : max <= 84 ? 84 : 89;
    return [lo, hi];
  }

  /* What a key says on itself: short, so that it fits a black key. */
  function keyLabel(midi, spelled) {
    const n = spelled || S.fromMidi(midi);
    if (n.acc === 0) return nameOf(n);
    if (n.letter === 'B' && n.acc < 0 && style() !== 'b') return 'B';
    return n.letter + (n.acc > 0 ? '♯' : '♭');
  }

  /**
   * Draw the keys from lo to hi inside `host`. opts.named: the names show;
   * opts.spell: notes whose spelling names their keys (F sharp, not G flat).
   */
  function drawKeys(host, lo, hi, opts) {
    const o = opts || {};
    host.textContent = '';
    const spell = new Map((o.spell || []).filter(n => !n.rest).map(n => [n.midi, n]));
    const whites = [];
    for (let m = lo; m <= hi; m++) if (!isBlack(m)) whites.push(m);
    const box = h('div', { class: 'pn-keys' + (o.named ? ' is-named' : ''), style: `--n: ${whites.length}`, role: 'group', 'aria-label': 'Tangenter' });
    const byMidi = new Map();
    function make(m, black) {
      const b = h('button', {
        type: 'button', class: `pn-key ${black ? 'pn-black' : 'pn-white'}`, 'data-midi': m, tabindex: '-1',
        'aria-label': sayName(spell.get(m) || S.fromMidi(m)),
      }, h('span', { class: 'pn-keyfinger' }), h('span', { class: 'pn-keyname', text: keyLabel(m, spell.get(m)) }));
      if (m === 60) b.classList.add('pn-middle');
      byMidi.set(m, b);
      return b;
    }
    for (const m of whites) box.append(make(m, false));
    for (let m = lo + 1; m < hi; m++) {
      if (!isBlack(m)) continue;
      const b = make(m, true);
      b.style.left = `calc(5px + (100% - 10px) * ${whites.indexOf(m - 1) + 1} / var(--n))`;
      box.append(b);
    }
    host.append(box);
    return {
      lo, hi,
      has: m => byMidi.has(m),
      named(show) { box.classList.toggle('is-named', !!show); },
      hint(midi) {
        for (const b of byMidi.values()) b.classList.remove('is-hint');
        if (midi !== null && midi !== undefined && byMidi.has(midi)) byMidi.get(midi).classList.add('is-hint');
      },
      show(midis) {
        for (const b of byMidi.values()) b.classList.remove('is-show');
        for (const m of midis || []) if (byMidi.has(m)) byMidi.get(m).classList.add('is-show');
      },
      fingers(thumbMidi) {
        for (const b of byMidi.values()) b.querySelector('.pn-keyfinger').textContent = '';
        if (!thumbMidi) return;
        const base = S.fromMidi(thumbMidi).step;
        for (const [m, b] of byMidi) {
          const n = spell.get(m) || S.fromMidi(m);
          const f = n.step - base + 1;
          if (f >= 1 && f <= 5 && (n.acc === 0 || spell.has(m))) b.querySelector('.pn-keyfinger').textContent = String(f);
        }
      },
      light(midi, cls) {
        const b = byMidi.get(midi);
        if (!b) return;
        b.classList.remove('is-down', 'is-right', 'is-wrong');
        void b.getBoundingClientRect();
        b.classList.add(cls);
        setTimeout(() => b.classList.remove(cls), 420);
      },
      classes: m => (byMidi.has(m) ? [...byMidi.get(m).classList] : []),
    };
  }

  function showKeys(midis, opts) {
    const [lo, hi] = rangeFor(midis);
    keys = drawKeys(dom.keys, lo, hi, opts);
    return keys;
  }

  /* ── A key is played ──────────────────────────────────────────────────── */

  /* A key on the screen or on the computer's keyboard: the page sounds it. */
  function press(midi, source) {
    PN_SOUND.context();
    sound(midi, { dur: 0.42 });
    noteIn({ midi, source, t: performance.now(), again: false });
  }

  /* Any key from anywhere: to the exercise on screen, and lit on the picture. */
  function noteIn(ev) {
    if (ev.source === 'mic' || ev.source === 'midi') {
      mic.heardAt = performance.now();
      if (run) run.real = true;
    }
    const answer = ctl && ctl.hear ? ctl.hear(ev) : null;
    if (keys) keys.light(ev.midi, answer === 'right' ? 'is-right' : answer === 'wrong' ? 'is-wrong' : 'is-down');
    if (dom.heard) {
      dom.heard.textContent = nameOf(S.fromMidi(ev.midi));
      dom.heard.setAttribute('data-state', answer || 'heard');
      clearTimeout(noteIn.fade);
      noteIn.fade = setTimeout(() => { dom.heard.textContent = ''; }, 1200);
    }
    last = { midi: ev.midi, source: ev.source, answer };
    return answer;
  }
  let last = null;

  /* The computer's keys: the home row is the white keys from middle C. */
  const CODES = {
    KeyA: 60, KeyW: 61, KeyS: 62, KeyE: 63, KeyD: 64, KeyF: 65, KeyT: 66, KeyG: 67, KeyY: 68, KeyH: 69, KeyU: 70, KeyJ: 71,
    KeyK: 72, KeyO: 73, KeyL: 74, KeyP: 75, Semicolon: 76, Quote: 77,
  };

  function onKeyDown(e) {
    if (e.defaultPrevented || e.repeat || e.ctrlKey || e.metaKey || e.altKey) return;
    if (document.querySelector('dialog[open]')) return;
    const t = e.target;
    if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable)) return;
    if (view !== 'lesson') return;
    if (e.key === 'Enter') {
      if (goFn && !dom.go.hidden && !dom.go.disabled && !(t && t.tagName === 'BUTTON')) { e.preventDefault(); goFn(); }
      return;
    }
    const midi = CODES[e.code];
    if (midi !== undefined && keys && keys.has(midi)) {
      e.preventDefault();
      press(midi, 'keys');
    }
  }

  /* ── The microphone ───────────────────────────────────────────────────── */

  const mic = { on: false, starting: false, error: null, note: null, stream: null, source: null, analyser: null, buf: null, ear: null, raf: 0, lastRead: 0, heardAt: 0, player: null, resume: false };

  function micError(e) {
    const name = e && e.name;
    if (name === 'NotAllowedError' || name === 'SecurityError' || name === 'PermissionDeniedError') {
      return 'Sidan fick inte använda mikrofonen. Tillåt mikrofonen för den här sidan i webbläsarens inställningar och tryck igen.';
    }
    if (name === 'NotFoundError' || name === 'OverconstrainedError' || name === 'DevicesNotFoundError') {
      return 'Hittade ingen mikrofon. Du kan spela på tangenterna på skärmen i stället.';
    }
    if (name === 'NotReadableError' || name === 'AbortError' || name === 'TrackStartError') {
      return 'Mikrofonen gick inte att starta. Den kanske används av en annan app.';
    }
    return 'Mikrofonen gick inte att starta.';
  }

  async function micStart() {
    if (mic.on || mic.starting) return;
    mic.error = null;
    mic.note = null;
    if (!window.isSecureContext) {
      mic.error = 'Mikrofonen fungerar bara när sidan öppnas över https.';
      renderMic();
      return;
    }
    // Made and resumed inside the tap, which is what a browser asks of sound.
    const ctx = PN_SOUND.context();
    if (!ctx || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      mic.error = 'Den här webbläsaren kan inte lyssna via mikrofonen. Du kan spela på tangenterna på skärmen i stället.';
      renderMic();
      return;
    }
    mic.starting = true;
    renderMic();
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
      });
    } catch (e) {
      mic.starting = false;
      mic.error = micError(e);
      renderMic();
      return;
    }
    if (!mic.starting) {
      stream.getTracks().forEach(t => t.stop());
      return;
    }
    micConnect(ctx, ctx.createMediaStreamSource(stream), stream);
    if (!store.settings.mic) { store.settings.mic = true; save(); }
  }

  /* source → high-pass at 70 Hz (rumble, the pedal's thud) → analyser. The
     analyser also feeds a silent gain to the output, which keeps the graph
     running in browsers that only process what reaches the destination. */
  function micConnect(ctx, source, stream) {
    const ear = PN_EAR.createListener(ctx.sampleRate, { tune: store.tune });
    const hp = ctx.createBiquadFilter();
    hp.type = 'highpass';
    hp.frequency.value = 70;
    hp.Q.value = Math.SQRT1_2;
    const analyser = ctx.createAnalyser();
    let size = 2048;
    while (size < ear.need && size < 32768) size *= 2;
    analyser.fftSize = size;
    const sink = ctx.createGain();
    sink.gain.value = 0;
    source.connect(hp);
    hp.connect(analyser);
    analyser.connect(sink);
    sink.connect(ctx.destination);
    Object.assign(mic, { on: true, starting: false, stream, source, analyser, sink, hp, ear, buf: new Float32Array(size), lastRead: -Infinity, heardAt: performance.now() });
    deafen();
    renderMic();
    if (!mic.raf) mic.raf = requestAnimationFrame(micFrame);
  }

  function micStop(why) {
    mic.starting = false;
    if (mic.on) {
      if (mic.ear) {
        store.tune = Math.round(mic.ear.tune() * 10) / 10;
        save();
      }
      if (mic.stream) mic.stream.getTracks().forEach(t => t.stop());
      if (mic.player) { try { mic.player.stop(); } catch (e) { /* already ended */ } }
      for (const node of [mic.source, mic.hp, mic.analyser, mic.sink]) { try { node.disconnect(); } catch (e) { /* not connected */ } }
    }
    if (mic.raf) cancelAnimationFrame(mic.raf);
    Object.assign(mic, { on: false, raf: 0, stream: null, source: null, analyser: null, sink: null, hp: null, ear: null, buf: null, player: null });
    mic.note = why === 'idle' ? 'Mikrofonen stängdes av efter en stund utan pianoljud. Tryck för att lyssna igen.' : null;
    setLevel(0);
    renderMic();
  }

  function setLevel(v) {
    const shown = Math.max(0, Math.min(1, v));
    for (const b of [dom.mic, dom.mic2]) if (b) b.style.setProperty('--pn-level', shown.toFixed(2));
  }

  function micFrame(now) {
    mic.raf = 0;
    if (!mic.on) return;
    if (now - mic.lastRead >= FRAME_MS) {
      mic.lastRead = now;
      // Sound can be taken away while the page listens (a call, another
      // app): context() asks for it back, and until then this reads silence.
      PN_SOUND.context();
      mic.analyser.getFloatTimeDomainData(mic.buf);
      hearFrame(mic.buf, now, mic.ear);
      if (now - mic.heardAt > IDLE_STOP_MS && view !== 'lesson') {
        micStop('idle');
        return;
      }
    }
    mic.raf = requestAnimationFrame(micFrame);
  }

  /* One reading of the microphone: the notes that began go to the exercise. */
  function hearFrame(samples, now, ear) {
    const events = ear.push(samples, now);
    // -50 dBFS is no bar, -14 dBFS all of it.
    setLevel((20 * Math.log10(Math.max(ear.level(), 1e-6)) + 50) / 36);
    for (const e of events) noteIn({ midi: e.midi, source: 'mic', t: e.t - MIC_LAG, again: e.again });
    return events;
  }

  function renderMic() {
    const label = mic.starting ? 'Startar …' : mic.on ? 'Lyssnar' : 'Lyssna på pianot';
    for (const b of [dom.mic, dom.mic2]) {
      if (!b) continue;
      b.textContent = '';
      b.append(h('span', { class: 'pn-micicon', icon: 'mic' }), h('span', { class: 'pn-miclabel', text: label }), h('span', { class: 'pn-miclevel', 'aria-hidden': 'true' }, h('i')));
      b.setAttribute('aria-pressed', mic.on ? 'true' : 'false');
      b.setAttribute('title', mic.on ? 'Sidan lyssnar på pianot. Tryck för att stänga av mikrofonen.' : 'Låt sidan lyssna på pianot genom mikrofonen');
      b.disabled = mic.starting;
    }
    const text = mic.error || mic.note;
    dom.micnote.hidden = !text;
    dom.micnote.textContent = text || '';
    dom.micnote.setAttribute('data-state', mic.error ? 'error' : 'note');
    if (text && view === 'lesson') toast(text);
  }

  function toast(text) {
    dom.toast.textContent = text;
    dom.toast.hidden = false;
    clearTimeout(toast.id);
    toast.id = setTimeout(() => { dom.toast.hidden = true; }, 6000);
  }

  function onVisibility() {
    if (document.hidden) {
      if (mic.on && !mic.player) {
        mic.resume = true;
        micStop('hidden');
      }
      if (ctl && ctl.pause) ctl.pause();
    } else if (mic.resume) {
      mic.resume = false;
      micStart();
    }
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

  /* ── A MIDI keyboard ──────────────────────────────────────────────────── */

  function midiState(text) {
    const e = document.getElementById('pn-midi-state');
    if (e) e.textContent = text;
  }

  function midiListen() {
    let n = 0;
    for (const input of midiAccess.inputs.values()) {
      n++;
      input.onmidimessage = m => {
        const [status, key, velocity] = m.data;
        if ((status & 0xf0) === 0x90 && velocity > 0) noteIn({ midi: key, source: 'midi', t: performance.now(), again: false });
      };
    }
    midiState(n ? `${n === 1 ? 'En klaviatur' : `${n} klaviaturer`} ansluten.` : 'Ingen klaviatur hittades. Koppla in den och tryck igen.');
  }

  async function midiStart() {
    if (!navigator.requestMIDIAccess) {
      midiState('Den här webbläsaren har inget stöd för MIDI. Pröva Chrome eller Edge.');
      return;
    }
    try {
      midiAccess = await navigator.requestMIDIAccess();
      midiAccess.onstatechange = midiListen;
      midiListen();
    } catch (e) {
      midiState('Sidan fick inte använda MIDI.');
    }
  }

  /* ── Home ─────────────────────────────────────────────────────────────── */

  const KIND_ICON = { notes: 'keys', read: 'eye', patterns: 'hand', phrase: 'note', song: 'notes', concert: 'trophy' };

  function isOpen(entry) {
    return store.settings.openAll || entry.index === 0 || !!store.lessons[S.ORDER[entry.index - 1].id] || !!store.lessons[entry.id];
  }

  function nextLesson() {
    return S.ORDER.find(e => !store.lessons[e.id]) || null;
  }

  /* The Christmas songs whose concert has been played. */
  function xmasCount(s) {
    let n = 0;
    for (const e of S.ORDER) {
      if (e.lesson.kind !== 'concert' || !s.lessons[e.id]) continue;
      const song = S.songById(e.lesson.song);
      if (song && song.xmas) n++;
    }
    return n;
  }

  function starRow(n, cls) {
    const row = h('span', { class: `pn-stars ${cls || ''}`, role: 'img', 'aria-label': `${n} av 3 stjärnor` });
    for (let k = 1; k <= 3; k++) row.append(h('span', { class: k <= n ? 'pn-star is-on' : 'pn-star', icon: 'star' }));
    return row;
  }

  function renderStats() {
    const day = today();
    const streak = G.streakNow(store, day);
    const xp = store.days[day] || 0;
    const goal = store.settings.goal;
    dom.statStreak.textContent = '';
    dom.statStreak.append(h('span', { class: 'pn-stat-icon', icon: 'flame' }), h('b', { text: String(streak) }));
    dom.statStreak.classList.toggle('is-lit', store.streak.last === day);
    dom.statStreak.setAttribute('aria-label', `${streak} ${streak === 1 ? 'dag' : 'dagar'} i rad`);
    dom.statStreak.setAttribute('title', `${streak} ${streak === 1 ? 'dag' : 'dagar'} i rad`);
    const share = Math.min(1, xp / goal);
    const ring = sv('svg', { viewBox: '0 0 24 24', width: 24, height: 24, 'aria-hidden': 'true', class: 'pn-ring' },
      sv('circle', { cx: 12, cy: 12, r: 9, class: 'pn-ring-track' }),
      share > 0 ? sv('circle', { cx: 12, cy: 12, r: 9, class: 'pn-ring-fill', 'stroke-dasharray': `${(share * 56.55).toFixed(2)} 56.55`, transform: 'rotate(-90 12 12)' }) : null);
    dom.statGoal.textContent = '';
    dom.statGoal.append(h('span', { class: 'pn-stat-icon' }, ring), h('b', { text: `${xp}/${goal}` }));
    dom.statGoal.classList.toggle('is-lit', xp >= goal);
    dom.statGoal.setAttribute('aria-label', `Dagens mål: ${xp} av ${goal} poäng`);
    dom.statGoal.setAttribute('title', `Dagens mål: ${xp} av ${goal} poäng`);
    const stars = G.totalStars(store);
    dom.statStars.textContent = '';
    dom.statStars.append(h('span', { class: 'pn-stat-icon', icon: 'star' }), h('b', { text: String(stars) }));
    dom.statStars.classList.toggle('is-lit', stars > 0);
    dom.statStars.setAttribute('aria-label', `${stars} ${stars === 1 ? 'stjärna' : 'stjärnor'}`);
    dom.statStars.setAttribute('title', `${stars} ${stars === 1 ? 'stjärna' : 'stjärnor'}`);
  }

  function renderPath() {
    const next = nextLesson();
    dom.path.textContent = '';
    for (const unit of S.UNITS) {
      const entries = S.ORDER.filter(e => e.unit === unit);
      const done = entries.filter(e => store.lessons[e.id]).length;
      const list = h('ol', { class: 'pn-lessons' });
      entries.forEach((e, k) => {
        const got = store.lessons[e.id];
        const open = isOpen(e);
        const current = next && next.id === e.id && open;
        const state = got ? 'done' : current ? 'current' : open ? 'open' : 'locked';
        const b = h('button', {
          type: 'button', class: 'pn-node', 'data-id': e.id, 'data-state': state, 'data-kind': e.lesson.kind,
          'data-on-click': 'pn:lesson', disabled: !open,
          title: open ? null : 'Öppnas när lektionen före är klar',
        },
        h('span', { class: 'pn-node-dot', icon: open ? (got ? 'check' : KIND_ICON[e.lesson.kind]) : 'lock' }),
        h('span', { class: 'pn-node-text' },
          h('span', { class: 'pn-node-title', text: fill(e.lesson.title) }),
          got ? starRow(got.stars) : current ? h('span', { class: 'pn-node-go', text: 'Starta' }) : null));
        list.append(h('li', { style: `--k: ${k}` }, b));
      });
      dom.path.append(h('section', { class: 'pn-unit' + (unit.xmas ? ' is-xmas' : ''), 'data-unit': unit.id },
        h('div', { class: 'pn-unit-head' },
          h('span', { class: 'pn-unit-mark', icon: unit.xmas ? 'tree' : 'keys' }),
          h('div', { class: 'pn-unit-text' }, h('h2', { text: unit.title }), h('p', { text: unit.sub })),
          h('span', { class: 'pn-unit-count', text: `${done}/${entries.length}`, 'aria-label': `${done} av ${entries.length} lektioner klara` })),
        list));
    }
  }

  function renderSongs() {
    dom.songs.textContent = '';
    const pick = h('select', { id: 'pn-speed', 'data-on-change': 'pn:speed', 'aria-label': 'Tempo när du spelar i takt' },
      ...[[0.6, 'Lugnt'], [0.8, 'Lagom'], [1, 'Fullt tempo']].map(([v, t]) => h('option', { value: v, text: t, selected: v === speed })));
    dom.songs.append(h('div', { class: 'pn-songbar' },
      h('p', { text: 'Spela vilken låt du vill, i din egen takt eller i takt med sidan.' }),
      h('label', { class: 'pn-field' }, h('span', { text: 'I takt' }), pick)));
    const grid = h('div', { class: 'pn-songgrid' });
    for (const song of [...S.SONGS, ...store.own]) {
      const got = store.songs[song.id];
      const dots = h('span', { class: 'pn-level', role: 'img', 'aria-label': `Svårighet ${song.level || 1} av 3` });
      for (let k = 1; k <= 3; k++) dots.append(h('i', { class: k <= (song.level || 1) ? 'is-on' : '' }));
      grid.append(h('article', { class: 'pn-song' + (song.xmas ? ' is-xmas' : ''), 'data-song': song.id },
        h('div', { class: 'pn-song-head' },
          h('span', { class: 'pn-song-mark', icon: song.xmas ? 'tree' : song.own ? 'pen' : 'note' }),
          h('div', {}, h('h3', { text: song.title }), h('p', { text: song.own ? 'Egen låt' : song.by }))),
        h('div', { class: 'pn-song-meta' }, song.own ? h('span') : dots, starRow(got ? got.stars : 0)),
        h('div', { class: 'pn-song-btns' },
          h('button', { type: 'button', class: 'pn-btn pn-btn-quiet', 'data-on-click': 'pn:song', 'data-song': song.id, 'data-mode': 'play', text: 'Öva' }),
          h('button', { type: 'button', class: 'pn-btn pn-btn-go', 'data-on-click': 'pn:song', 'data-song': song.id, 'data-mode': 'tempo', text: 'I takt' }),
          song.own ? h('button', { type: 'button', class: 'pn-btn pn-btn-quiet', 'data-on-click': 'pn:own', 'data-song': song.id, text: 'Ändra' }) : null)));
    }
    grid.append(h('button', { type: 'button', class: 'pn-song pn-song-new', 'data-on-click': 'pn:own' },
      h('span', { class: 'pn-song-mark', icon: 'plus' }), h('span', { text: 'Egen låt' }), h('small', { text: 'Skriv in en melodi ur en notbok' })));
    dom.songs.append(grid);
  }

  const WEEKDAYS = ['sö', 'må', 'ti', 'on', 'to', 'fr', 'lö'];

  function renderBadges() {
    const day = today();
    const lv = G.level(store.xp);
    const streak = G.streakNow(store, day);
    dom.badges.textContent = '';
    const week = h('div', { class: 'pn-week', role: 'img', 'aria-label': 'De senaste sju dagarna' });
    for (const d of G.week(store, day)) {
      const [y, m, dd] = d.day.split('-').map(Number);
      week.append(h('span', { class: 'pn-day' + (d.met ? ' is-met' : d.xp ? ' is-some' : '') + (d.day === day ? ' is-today' : '') },
        h('i', { icon: d.met ? 'check' : null }), h('small', { text: WEEKDAYS[new Date(y, m - 1, dd).getDay()] })));
    }
    dom.badges.append(h('div', { class: 'pn-summary' },
      h('div', { class: 'pn-tile pn-tile-level' },
        h('span', { class: 'pn-tile-big', text: `Nivå ${lv.level}` }),
        h('div', { class: 'pn-bar', role: 'img', 'aria-label': `${lv.into} av ${lv.need} poäng till nästa nivå` }, h('i', { style: `width: ${Math.round(100 * lv.into / lv.need)}%` })),
        h('small', { text: `${store.xp} poäng · ${lv.need - lv.into} till nivå ${lv.level + 1}` })),
      h('div', { class: 'pn-tile' }, h('span', { class: 'pn-tile-big', text: String(streak) }), h('small', { text: `${streak === 1 ? 'dag' : 'dagar'} i rad · som mest ${store.streak.best}` })),
      h('div', { class: 'pn-tile' }, h('span', { class: 'pn-tile-big', text: String(store.notes) }), h('small', { text: 'toner spelade rätt' })),
      h('div', { class: 'pn-tile pn-tile-week' }, week, h('small', { text: `Dagens mål: ${store.days[day] || 0} av ${store.settings.goal} poäng` }))));
    const grid = h('div', { class: 'pn-badgegrid' });
    for (const b of G.BADGES) {
      const got = store.badges[b.id];
      grid.append(h('div', { class: 'pn-badge' + (got ? ' is-got' : ''), 'data-badge': b.id },
        h('span', { class: 'pn-badge-mark', icon: b.icon }),
        h('b', { text: b.title }),
        h('small', { text: got ? `Klart ${String(got).slice(0, 10)}` : b.how })));
    }
    dom.badges.append(h('h2', { class: 'pn-h', text: 'Märken' }), grid);
  }

  function renderHome() {
    renderStats();
    renderPath();
    renderSongs();
    renderBadges();
    showTab(tab);
  }

  function showTab(name) {
    tab = ['path', 'songs', 'badges'].includes(name) ? name : 'path';
    for (const t of ['path', 'songs', 'badges']) {
      document.getElementById(`pn-tab-${t}`).setAttribute('aria-selected', t === tab ? 'true' : 'false');
      dom[t].hidden = t !== tab;
    }
  }

  function show(name) {
    view = name;
    dom.home.hidden = name !== 'home';
    dom.lesson.hidden = name !== 'lesson';
    dom.finish.hidden = name !== 'finish';
    document.documentElement.classList.toggle('pn-deep', name !== 'home');
    if (name === 'home') {
      renderHome();
      sleepOK();
    }
  }

  /* The lesson to do next, brought into sight. */
  function seeCurrent() {
    const b = dom.path.querySelector('.pn-node[data-state="current"]');
    if (b && tab === 'path') b.scrollIntoView({ block: 'center' });
  }

  /* ── A lesson ─────────────────────────────────────────────────────────── */

  function startLesson(id) {
    const entry = S.lessonById(id);
    if (!entry || !isOpen(entry)) return;
    const got = store.lessons[id];
    const ex = S.buildLesson(id, { seed: got ? got.times : 0, own: store.own });
    if (!ex.length) return;
    begin({ kind: 'lesson', id, title: fill(entry.lesson.title), ex, concert: entry.lesson.kind === 'concert' });
  }

  function startSong(id, mode) {
    const song = S.songById(id, store.own);
    if (!song) return;
    const notes = S.partNotes(song);
    if (!S.sounding(notes).length) return;
    const base = { notes, time: song.time || 4, fingers: song.fingers ? S.pitch(song.fingers).midi : null, letters: true };
    const ex = mode === 'tempo'
      ? [Object.assign({ type: 'tempo', bpm: Math.round(song.bpm * speed), grade: true }, base)]
      : [Object.assign({ type: 'play', whole: true, hint: false }, base)];
    begin({ kind: 'song', id, title: song.title, ex, mode });
  }

  function begin(r) {
    PN_SOUND.context();
    run = Object.assign(r, { i: 0, items: 0, right: 0, notes: 0, real: false, graded: null });
    show('lesson');
    if (store.settings.mic && !mic.on) micStart();
    wake();
    showExercise();
  }

  function stopCtl() {
    if (ctl && ctl.stop) ctl.stop();
    ctl = null;
    clearTimers();
    goFn = null;
    altFn = null;
  }

  function showExercise() {
    stopCtl();
    const ex = run.ex[run.i];
    const share = Math.round(100 * run.i / run.ex.length);
    dom.progressFill.style.width = `${share}%`;
    dom.progress.setAttribute('aria-valuenow', String(share));
    dom.card.hidden = true;
    dom.card.textContent = '';
    dom.lesson.setAttribute('data-type', ex.type);
    feedback('', '');
    setGo(null);
    setAlt(null);
    ctl = CONTROL[ex.type](ex);
  }

  function advance() {
    if (!run) return;
    run.i++;
    if (run.i >= run.ex.length) finish();
    else showExercise();
  }

  function score(items, right, notes) {
    run.items += items;
    run.right += right;
    run.notes += notes;
  }

  function setPrompt(title, sub) {
    dom.prompt.textContent = title;
    dom.sub.textContent = sub || '';
  }

  function setGo(label, fn, quiet) {
    goFn = label ? fn : null;
    dom.go.hidden = !label;
    dom.go.textContent = label || '';
    dom.go.classList.toggle('pn-btn-go', !quiet);
    dom.go.classList.toggle('pn-btn-quiet', !!quiet);
  }

  function setAlt(label, fn, primary) {
    altFn = label ? fn : null;
    dom.alt.hidden = !label;
    dom.alt.textContent = label || '';
    dom.alt.classList.toggle('pn-btn-go', !!primary);
    dom.alt.classList.toggle('pn-btn-quiet', !primary);
  }

  function feedback(text, kind) {
    dom.feedback.textContent = text;
    dom.feedback.setAttribute('data-state', kind || '');
    dom.foot.setAttribute('data-state', kind || '');
  }

  /* On to the next exercise by itself, with a button for the impatient. */
  function autoNext(ms) {
    const id = later(advance, ms);
    setGo('Fortsätt', () => { clearTimeout(id); advance(); });
  }

  const PRAISE = ['Rätt!', 'Snyggt!', 'Bra jobbat!', 'Precis!', 'Just det!', 'Strålande!', 'Vad fint!'];
  const praise = () => PRAISE[(run.i * 3 + run.right) % PRAISE.length];

  const wantLetters = ex => (store.settings.letters === 'always' ? true : store.settings.letters === 'never' ? false : !!ex.letters);

  /* The page's companion: a note with a face (and a red cap in winter). */
  function mascot(mood) {
    const month = new Date().getMonth();
    const cap = month >= 10 || month === 0;
    return h('span', { class: `pn-mascot is-${mood || 'calm'}`, 'aria-hidden': 'true' }, (() => {
      const g = sv('svg', { viewBox: '0 0 96 110', width: 96, height: 110 });
      g.append(sv('path', { d: 'M71 62V14c9 3 17 9 17 22', class: 'pn-m-stem' }));
      g.append(sv('ellipse', { cx: 44, cy: 70, rx: 34, ry: 27, transform: 'rotate(-14 44 70)', class: 'pn-m-body' }));
      g.append(sv('circle', { cx: 33, cy: 64, r: 8, class: 'pn-m-eye' }), sv('circle', { cx: 55, cy: 60, r: 8, class: 'pn-m-eye' }));
      g.append(sv('circle', { cx: 35, cy: 65, r: 3.4, class: 'pn-m-pupil' }), sv('circle', { cx: 57, cy: 61, r: 3.4, class: 'pn-m-pupil' }));
      g.append(sv('path', { d: mood === 'cheer' ? 'M34 79c6 9 18 7 23-2' : 'M36 80c5 5 13 4 18-1', class: 'pn-m-mouth' }));
      if (cap) {
        g.append(sv('path', { d: 'M17 51C22 30 44 22 62 34l-4 9z', class: 'pn-m-cap' }));
        g.append(sv('path', { d: 'M15 53c12-9 30-13 46-9', class: 'pn-m-brim' }));
        g.append(sv('circle', { cx: 64, cy: 33, r: 5, class: 'pn-m-bob' }));
      }
      return g;
    })());
  }

  /* ── The exercises ────────────────────────────────────────────────────── */

  const soundingIndex = notes => notes.map((n, i) => (n.rest ? -1 : i)).filter(i => i >= 0);

  /**
   * A melody at the pupil's own pace, on the staff and keys already drawn.
   * opts: hint (the next key is lit from the start), onDone(wait).
   */
  function waitRun(ex, opts) {
    const idx = soundingIndex(ex.notes);
    const w = G.createWait(idx.map(i => ex.notes[i].midi), { anyOctave: store.settings.anyOctave });
    let lit = !!opts.hint;
    function point() {
      if (w.done()) { staff.now(null); keys.hint(null); return; }
      staff.now(idx[w.index()]);
      keys.hint(lit ? w.expected() : null);
    }
    point();
    return {
      wait: w,
      point,
      hear(ev) {
        const r = w.hear(ev);
        if (r.kind === 'right') {
          staff.mark(idx[r.index], 'is-right');
          lit = !!opts.hint;
          point();
          feedback('', '');
          if (r.done) opts.onDone(w);
          return 'right';
        }
        if (r.kind === 'wrong') {
          staff.shake(idx[r.index]);
          if (r.showHint) { lit = true; point(); }
          feedback(r.showHint ? `Det var ${nameOf(S.fromMidi(ev.midi))}. Titta på tangenten som lyser.` : `Det var ${nameOf(S.fromMidi(ev.midi))}. Prova igen!`, 'bad');
          return 'wrong';
        }
        return null;
      },
    };
  }

  function melodyDone(w) {
    score(w.total, w.total - w.mistakes(), w.total);
    feedback(w.mistakes() === 0 ? `${praise()} Alla toner rätt.` : `${praise()} ${w.total - w.mistakes()} av ${w.total} toner rätt på första försöket.`, 'good');
    effect('right');
    autoNext(1500);
  }

  function drawMelody(ex) {
    const midis = ex.notes.map(n => n.midi);
    showStaff(ex.notes, { time: ex.time, letters: wantLetters(ex), fingers: ex.fingers, fing: ex.fing });
    showKeys(midis, { named: store.settings.keyNames, spell: ex.notes });
  }

  const CONTROL = {
    info(ex) {
      setPrompt(fill(ex.title), '');
      dom.card.hidden = false;
      dom.card.append(h('div', { class: 'pn-info' }, mascot('calm'), h('p', { class: 'pn-bubble', text: fill(ex.text) })));
      let stop = null;
      if (ex.listen) {
        showStaff(ex.listen, { time: ex.time, letters: true, fingers: ex.fingers });
        showKeys(ex.listen.map(n => n.midi), { named: store.settings.keyNames, spell: ex.listen });
        const bpm = 92;
        const listen = () => {
          if (stop) stop();
          staff.clear();
          stop = playback(ex.listen, bpm, (i, n) => { staff.now(i); if (!n.rest) keys.light(n.midi, 'is-down'); }, () => { staff.now(null); stop = null; });
        };
        setAlt('Lyssna', listen);
        later(listen, 500);
      } else {
        if (ex.staff.length) showStaff(ex.staff.map((n, i) => Object.assign({}, n, { beats: 4, start: 4 * i, bar: i, beat: 0, rest: false })), { plain: true, letters: true });
        else hideStaff();
        const shown = ex.keys.length ? ex.keys : ex.staff;
        showKeys(shown.map(n => n.midi), { named: true, spell: shown });
        keys.show(ex.keys.map(n => n.midi));
        keys.fingers(ex.fingers);
      }
      setGo('Fortsätt', advance);
      return { hear: () => null, stop() { if (stop) stop(); } };
    },

    find(ex) {
      const target = ex.note;
      setPrompt(`Spela ${sayName(target)}`, ex.hint ? 'Tangenten lyser. Tryck ner den på pianot.' : ex.staff ? 'Vilken tangent hör till noten?' : 'Var sitter den?');
      if (ex.staff) {
        showStaff([Object.assign({}, target, { beats: 4, start: 0, bar: 0, beat: 0, rest: false })], { plain: true, letters: wantLetters(ex) });
      } else {
        hideStaff();
        dom.card.hidden = false;
        dom.card.append(h('div', { class: 'pn-bigname', text: nameOf(target) }));
      }
      showKeys([target.midi], { named: store.settings.keyNames && ex.hint, spell: [target] });
      keys.hint(ex.hint ? target.midi : null);
      let wrong = 0;
      let done = false;
      let lastWrong = null;
      return {
        hear(ev) {
          if (done) return null;
          if (G.matches(target.midi, ev, { anyOctave: store.settings.anyOctave })) {
            done = true;
            score(1, wrong ? 0 : 1, 1);
            keys.hint(null);
            staff.mark(0, 'is-right');
            feedback(`${praise()} Det är ${sayName(target)}.`, 'good');
            effect('right');
            autoNext(1200);
            return 'right';
          }
          if (ev.source === 'mic' && lastWrong && lastWrong.midi === ev.midi && ev.t - lastWrong.t < G.RING_MS) return null;
          lastWrong = { midi: ev.midi, t: ev.t };
          wrong++;
          if (wrong >= G.HINT_AFTER) { keys.hint(target.midi); keys.named(store.settings.keyNames); }
          feedback(wrong >= G.HINT_AFTER ? `Det var ${nameOf(S.fromMidi(ev.midi))}. Titta på tangenten som lyser.` : `Det var ${nameOf(S.fromMidi(ev.midi))}. Leta lite till!`, 'bad');
          return 'wrong';
        },
      };
    },

    name(ex) {
      const target = ex.note;
      setPrompt('Vilken ton är det?', ex.from === 'staff' ? 'Titta på noten och välj namn.' : 'Titta på tangenten som lyser och välj namn.');
      // The card first: beside it the notes' box has the size it will keep,
      // and the note is drawn in the middle of that.
      const row = h('div', { class: 'pn-choices', role: 'group', 'aria-label': 'Välj tonens namn' });
      dom.card.hidden = false;
      dom.card.append(row);
      if (ex.from === 'staff') showStaff([Object.assign({}, target, { beats: 4, start: 0, bar: 0, beat: 0, rest: false })], { plain: true, letters: false });
      else hideStaff();
      showKeys(ex.choices.map(n => n.midi), { named: false, spell: ex.choices });
      if (ex.from === 'key') keys.hint(target.midi);
      let wrong = 0;
      let done = false;
      function answer(n, button) {
        if (done) return;
        if (n.midi === target.midi) {
          done = true;
          if (button) button.classList.add('is-right');
          else for (const b of row.children) if (Number(b.getAttribute('data-midi')) === target.midi) b.classList.add('is-right');
          score(1, wrong ? 0 : 1, 0);
          staff.mark(0, 'is-right');
          keys.named(true);
          keys.hint(target.midi);
          feedback(`${praise()} Det är ${sayName(target)}.`, 'good');
          effect('right');
          autoNext(1300);
        } else {
          wrong++;
          if (button) { button.classList.add('is-wrong'); button.disabled = true; }
          feedback('Inte den. Prova en annan!', 'bad');
          effect('wrong');
        }
      }
      for (const n of ex.choices) {
        const b = h('button', { type: 'button', class: 'pn-choice', 'data-midi': n.midi, text: sayName(n) });
        b.addEventListener('click', () => answer(n, b));
        row.append(b);
      }
      // The choices are in now, and may have changed the boxes' sizes.
      staff.fit();
      return {
        // The note may be answered on the piano too, where that says something.
        hear(ev) {
          if (done || ex.from !== 'staff') return null;
          if (G.matches(target.midi, ev, { anyOctave: store.settings.anyOctave })) { answer(target, null); return 'right'; }
          return null;
        },
      };
    },

    echo(ex) {
      drawMelody(ex);
      let stop = null;
      let w = null;
      const bpm = 84;
      function listen() {
        if (stop) stop();
        w = null;
        staff.clear();
        keys.hint(null);
        feedback('', '');
        setPrompt('Lyssna och härma', 'Först spelar jag …');
        setAlt(null);
        stop = playback(ex.notes, bpm, (i, n) => { staff.now(i); if (!n.rest) keys.light(n.midi, 'is-down'); }, () => {
          stop = null;
          setPrompt('Lyssna och härma', '… och nu är det din tur!');
          setAlt('Lyssna igen', listen);
          w = waitRun(ex, { hint: ex.hint, onDone: melodyDone });
        });
      }
      setPrompt('Lyssna och härma', 'Först spelar jag …');
      later(listen, 350);
      return {
        hear: ev => (w ? w.hear(ev) : null),
        stop() { if (stop) stop(); },
      };
    },

    play(ex) {
      drawMelody(ex);
      setPrompt(ex.again ? 'En gång till!' : ex.whole ? 'Hela vägen' : 'Spela noterna',
        ex.again ? 'Nu utan lika mycket hjälp. Ta det lugnt.' : 'Spela i din egen takt. Jag väntar på rätt ton.');
      let stop = null;
      let w = waitRun(ex, { hint: ex.hint, onDone: melodyDone });
      function listen() {
        if (stop) { stop(); stop = null; }
        staff.clear();
        keys.hint(null);
        const held = w;
        w = null;
        stop = playback(ex.notes, 92, (i, n) => { staff.now(i); if (!n.rest) keys.light(n.midi, 'is-down'); }, () => {
          stop = null;
          w = held;
          // What was already played stays played.
          const idx = soundingIndex(ex.notes);
          for (let k = 0; k < w.wait.index(); k++) staff.mark(idx[k], 'is-right');
          w.point();
        });
      }
      setAlt('Lyssna', listen);
      return {
        hear: ev => (w ? w.hear(ev) : null),
        stop() { if (stop) stop(); },
      };
    },

    tempo(ex) {
      drawMelody(ex);
      const idx = soundingIndex(ex.notes);
      const tnotes = idx.map(i => ({ midi: ex.notes[i].midi, start: ex.notes[i].start }));
      const bpm = Math.round(ex.bpm * tempoScale);
      const beatMs = 60000 / bpm;
      const firstNote = ex.notes[idx[0]];
      const lastNote = ex.notes[ex.notes.length - 1];
      const per = ex.time || 4;
      // The count-in: a whole bar, or the bar up to where the melody begins.
      const lead = firstNote.beat > 0 ? (firstNote.beat >= 2 ? firstNote.beat : firstNote.beat + per) : per;
      const length = lastNote.start + lastNote.beats - firstNote.start;
      const count = h('div', { class: 'pn-count', 'aria-hidden': 'true' });
      dom.staff.append(count);
      let state = 'ready';
      let T = null;
      let t0 = 0;
      let raf = 0;
      let best = null;
      let stopListen = null;
      let ticks = [];

      function halt() {
        if (raf) cancelAnimationFrame(raf);
        raf = 0;
        for (const id of ticks) clearTimeout(id);
        ticks = [];
        if (stopListen) { stopListen(); stopListen = null; }
        count.textContent = '';
      }

      function ready() {
        halt();
        state = 'ready';
        staff.clear();
        setPrompt('Spela i takt', 'Lyssna på inräkningen och följ strecket. Fortsätt framåt även om en ton blir fel.');
        setAlt('Lyssna', listen);
        setGo(best ? 'En gång till' : 'Starta', start);
        if (best) setAlt('Fortsätt', commit, true);
      }

      function listen() {
        halt();
        staff.clear();
        stopListen = playback(ex.notes, bpm, (i, n) => { staff.now(i); if (!n.rest) keys.light(n.midi, 'is-down'); }, () => { stopListen = null; staff.now(null); });
      }

      function start() {
        halt();
        staff.clear();
        feedback('', '');
        T = G.createTempo(tnotes, bpm, { anyOctave: store.settings.anyOctave });
        t0 = performance.now() + lead * beatMs + 400;
        state = 'running';
        setGo(null);
        setAlt('Börja om', ready);
        setPrompt('Spela i takt', `Räkna med: ${Array.from({ length: per }, (_, k) => k + 1).join(', ')} …`);
        for (let k = 0; k < lead + length; k++) {
          const at = t0 + (k - lead) * beatMs - performance.now();
          ticks.push(setTimeout(() => {
            if (store.settings.tick) PN_SOUND.tick(k % per === 0);
            count.textContent = k < lead ? String((k % per) + 1) : '';
            count.classList.remove('is-beat');
            void count.getBoundingClientRect();
            count.classList.add('is-beat');
            dom.lesson.classList.remove('is-beat');
            void dom.lesson.getBoundingClientRect();
            dom.lesson.classList.add('is-beat');
          }, at));
        }
        raf = requestAnimationFrame(frame);
      }

      function frame(now) {
        raf = 0;
        if (state !== 'running') return;
        const t = (now - t0) / 1000;
        staff.playhead(firstNote.start + t / T.beat);
        for (const j of T.sweep(t)) staff.mark(idx[j], 'is-missed');
        if (t > length * T.beat + T.window + 0.15) { over(); return; }
        raf = requestAnimationFrame(frame);
      }

      function over() {
        halt();
        state = 'done';
        T.sweep(Infinity);
        const res = T.result();
        if (!best || res.accuracy > best.accuracy) best = res;
        staff.playhead(null);
        const n = G.stars(res.accuracy);
        let text = `${res.hits} av ${res.total} toner i takt.`;
        if (res.accuracy >= 0.9) text = `${praise()} ${text}`;
        else if (res.hits >= 3 && res.late > 0.12) text += ' Du kommer lite efter takten – våga spela på slaget.';
        else if (res.hits >= 3 && res.late < -0.12) text += ' Du har lite bråttom – vänta in slaget.';
        else if (res.accuracy < 0.5) text += ' Pröva en gång till, eller lyssna först.';
        feedback(text, res.accuracy >= 0.5 ? 'good' : '');
        effect(n === 3 ? 'done' : 'star');
        if (res.accuracy >= 0.5) { setAlt('En gång till', start); setGo('Fortsätt', commit); }
        else { setAlt('Fortsätt ändå', commit); setGo('En gång till', start); }
      }

      function commit() {
        score(best.total, best.hits, best.hits);
        if (ex.grade) run.graded = best.accuracy;
        advance();
      }

      ready();
      return {
        hear(ev) {
          if (state !== 'running') return null;
          const r = T.hear(ev, (ev.t - t0) / 1000);
          if (r.kind !== 'hit') return null;
          staff.mark(idx[r.index], 'is-right');
          return 'right';
        },
        pause() { if (state === 'running') ready(); },
        stop: halt,
        info: () => ({ state, bpm, lead, t0, times: T ? T.times.slice() : [], midis: tnotes.map(n => n.midi), best }),
      };
    },
  };

  /* ── A lesson is over ─────────────────────────────────────────────────── */

  function confetti(host) {
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const box = h('div', { class: 'pn-confetti', 'aria-hidden': 'true' });
    for (let k = 0; k < 36; k++) {
      box.append(h('i', { style: `--x: ${(k * 37) % 100}%; --d: ${((k * 53) % 90) / 100}s; --r: ${(k * 71) % 360}deg; --c: ${k % 4}` }));
    }
    host.append(box);
    setTimeout(() => box.remove(), 4200);
  }

  function finish() {
    stopCtl();
    const accuracy = run.graded !== null ? run.graded : run.items ? run.right / run.items : 1;
    const result = { accuracy, notes: run.notes, real: run.real };
    const day = today();
    const out = run.kind === 'lesson'
      ? G.finishLesson(store, run.id, result, day, { concert: run.concert, xmas: xmasCount })
      : G.finishSong(store, run.id, result, day, { xmas: xmasCount });
    save();
    const was = run;
    run = null;
    lastFinish = { id: was.id, kind: was.kind, stars: out.stars, xp: out.xp, accuracy, streak: out.streak.after, badges: out.badges.map(b => b.id) };
    show('finish');
    const next = was.kind === 'lesson' ? nextLesson() : null;
    const stars = h('div', { class: 'pn-finish-stars', role: 'img', 'aria-label': `${out.stars} av 3 stjärnor` });
    for (let k = 1; k <= 3; k++) stars.append(h('span', { class: k <= out.stars ? 'pn-star is-on' : 'pn-star', icon: 'star', style: `--k: ${k}` }));
    const tiles = h('div', { class: 'pn-finish-tiles' },
      h('div', { class: 'pn-tile' }, h('span', { class: 'pn-tile-big', text: `+${out.xp}` }), h('small', { text: 'poäng' })),
      h('div', { class: 'pn-tile' }, h('span', { class: 'pn-tile-big', text: `${Math.round(accuracy * 100)} %` }), h('small', { text: 'rätt' })),
      h('div', { class: 'pn-tile' + (out.streak.grew ? ' is-new' : '') }, h('span', { class: 'pn-tile-big', text: String(out.streak.after) }), h('small', { text: `${out.streak.after === 1 ? 'dag' : 'dagar'} i rad` })));
    const notes = [];
    if (out.goal.reached) notes.push(h('p', { class: 'pn-finish-note', text: `Dagens mål är nått: ${out.goal.after} poäng!` }));
    else if (out.goal.after < out.goal.target) notes.push(h('p', { class: 'pn-finish-note', text: `${out.goal.target - out.goal.after} poäng kvar till dagens mål.` }));
    if (out.level > out.levelBefore) notes.push(h('p', { class: 'pn-finish-note', text: `Du har nått nivå ${out.level}!` }));
    const badges = out.badges.length ? h('div', { class: 'pn-finish-badges' }, ...out.badges.map(b => h('div', { class: 'pn-badge is-got is-new' },
      h('span', { class: 'pn-badge-mark', icon: b.icon }), h('b', { text: b.title }), h('small', { text: 'Nytt märke!' })))) : null;
    const title = was.kind === 'song' ? was.title : out.stars === 3 ? 'Strålande!' : out.stars === 2 ? 'Bra jobbat!' : 'Lektionen är klar!';
    dom.finish.textContent = '';
    dom.finish.append(
      mascot('cheer'),
      h('h2', { text: title }),
      h('p', { class: 'pn-finish-sub', text: was.kind === 'song' ? (out.stars === 3 ? 'Strålande spelat!' : 'Bra spelat!') : was.title }),
      stars, tiles, ...notes, badges,
      h('div', { class: 'pn-finish-btns' },
        was.kind === 'song'
          ? h('button', { type: 'button', class: 'pn-btn pn-btn-quiet', 'data-on-click': 'pn:song', 'data-song': was.id, 'data-mode': was.mode, text: 'En gång till' })
          : h('button', { type: 'button', class: 'pn-btn pn-btn-quiet', 'data-on-click': 'pn:lesson', 'data-id': was.id, text: 'Gör om' }),
        next && isOpen(next) && next.id !== was.id
          ? h('button', { type: 'button', class: 'pn-btn pn-btn-quiet', 'data-on-click': 'pn:home', text: 'Till lektionerna' }) : null,
        next && isOpen(next) && next.id !== was.id
          ? h('button', { type: 'button', class: 'pn-btn pn-btn-go', id: 'pn-next', 'data-on-click': 'pn:lesson', 'data-id': next.id, text: 'Nästa lektion' })
          : h('button', { type: 'button', class: 'pn-btn pn-btn-go', id: 'pn-next', 'data-on-click': 'pn:home', text: was.kind === 'song' ? 'Till låtarna' : 'Till lektionerna' })));
    effect(out.stars === 3 ? 'fanfare' : 'done');
    if (out.stars === 3 || out.badges.length) confetti(dom.finish);
  }
  let lastFinish = null;

  function goHome() {
    stopCtl();
    run = null;
    show('home');
    seeCurrent();
  }

  function quit() {
    if (view !== 'lesson') return;
    if (!run || run.i === 0) { goHome(); return; }
    ask('Avsluta?', run.kind === 'lesson' ? 'Lektionen räknas inte förrän den är klar.' : 'Låten räknas inte förrän den är klar.', 'Avsluta', 'Fortsätt spela', goHome);
  }

  /* ── Dialogs ──────────────────────────────────────────────────────────── */

  function openDialog(id) {
    const d = document.getElementById(id);
    if (!d) return;
    if (typeof d.showModal === 'function') d.showModal();
    else d.setAttribute('open', '');
  }

  function closeDialog(e, elem) {
    const d = elem && elem.closest ? elem.closest('dialog') : elem;
    if (!d) return;
    if (typeof d.close === 'function') d.close();
    else d.removeAttribute('open');
  }

  function ask(title, text, yes, no, fn) {
    document.getElementById('pn-ask-title').textContent = title;
    document.getElementById('pn-ask-text').textContent = text;
    document.getElementById('pn-ask-yes').textContent = yes;
    document.getElementById('pn-ask-no').textContent = no;
    askFn = fn;
    openDialog('pn-ask');
  }

  function syncSettings() {
    const d = document.getElementById('pn-settings');
    const t = store.settings;
    for (const r of d.querySelectorAll('input[name="names"]')) r.checked = r.value === t.names;
    d.querySelector('select[name="letters"]').value = t.letters;
    d.querySelector('select[name="goal"]').value = String(t.goal);
    for (const k of ['keyNames', 'sound', 'tick', 'anyOctave', 'openAll']) d.querySelector(`input[name="${k}"]`).checked = !!t[k];
  }

  function changeSetting(e, elem) {
    const t = store.settings;
    const k = elem.name;
    if (k === 'names' && (elem.value === 'h' || elem.value === 'b')) t.names = elem.value;
    else if (k === 'letters' && ['auto', 'always', 'never'].includes(elem.value)) t.letters = elem.value;
    else if (k === 'goal' && [20, 40, 60].includes(Number(elem.value))) t.goal = Number(elem.value);
    else if (['keyNames', 'sound', 'tick', 'anyOctave', 'openAll'].includes(k)) t[k] = !!elem.checked;
    else return;
    PN_SOUND.setOn(t.sound);
    save();
    fillHelp();
    if (view === 'home') renderHome();
    else if (view === 'lesson' && run) showExercise();
  }

  function fillHelp() {
    const body = document.getElementById('pn-songtable');
    body.textContent = '';
    for (const s of S.SONGS) body.append(h('tr', {}, h('td', { text: s.title }), h('td', { text: s.by })));
    for (const e of document.querySelectorAll('.pn-hname')) e.textContent = nameOf(S.pitch('B4'));
  }

  /* ── Own songs ────────────────────────────────────────────────────────── */

  /* The notation as it is typed in the chosen style: H and B, or B and Bb. */
  function toTyped(text) {
    if (style() === 'b') return text;
    return text.split(/\s+/).map(t => (/^Bb/.test(t) ? `B${t.slice(2)}` : /^B/.test(t) ? `H${t.slice(1)}` : t)).join(' ');
  }

  function ownRead() {
    const typed = S.fromUser(document.getElementById('pn-own-text').value, style());
    const time = Number(document.getElementById('pn-own-time').value) === 3 ? 3 : 4;
    const pickup = Number(document.getElementById('pn-own-pickup').value) || 0;
    const bpm = Number(document.getElementById('pn-own-bpm').value) || 90;
    const parsed = S.parse(typed.text, { time, pickup });
    const problems = [...typed.problems, ...parsed.problems];
    const low = parsed.notes.filter(n => !n.rest && (n.midi < 48 || n.midi > 89));
    return { title: document.getElementById('pn-own-name').value.trim(), text: typed.text, time, pickup, bpm, parsed, problems, low };
  }

  function ownPreview() {
    const r = ownRead();
    const msg = document.getElementById('pn-own-msg');
    const host = document.getElementById('pn-own-staff');
    const sounding = S.sounding(r.parsed.notes).length;
    let text = '';
    let bad = false;
    if (r.problems.length) { text = `Förstår inte: ${r.problems.slice(0, 6).join(' ')}`; bad = true; }
    else if (r.low.length) { text = 'En ton ligger utanför tangenterna som sidan lyssnar efter (låga C till höga F).'; bad = true; }
    else if (sounding) text = `${sounding} toner, ${Math.ceil((r.parsed.total - r.pickup) / r.time) + (r.pickup ? 1 : 0)} takter.`;
    msg.textContent = text;
    msg.setAttribute('data-state', bad ? 'bad' : '');
    if (r.parsed.notes.length) drawStaff(host, r.parsed.notes, { time: r.time, letters: true, label: 'Din melodi' });
    else host.textContent = '';
    document.getElementById('pn-own-save').disabled = bad || sounding < 2 || !r.title;
    return r;
  }

  function ownOpen(id) {
    const song = id ? store.own.find(s => s.id === id) : null;
    ownId = song ? song.id : null;
    document.getElementById('pn-own-name').value = song ? song.title : '';
    document.getElementById('pn-own-text').value = song ? toTyped(song.text) : '';
    document.getElementById('pn-own-time').value = String(song ? song.time : 4);
    document.getElementById('pn-own-pickup').value = String(song ? song.pickup : 0);
    document.getElementById('pn-own-bpm').value = String(song && [70, 90, 110].includes(song.bpm) ? song.bpm : 90);
    document.getElementById('pn-own-delete').hidden = !song;
    openDialog('pn-own');
    ownPreview();
  }

  function ownSave() {
    const r = ownPreview();
    if (document.getElementById('pn-own-save').disabled) return;
    const old = ownId ? store.own.find(s => s.id === ownId) : null;
    const song = { id: old ? old.id : `own-${Date.now().toString(36)}`, title: r.title.slice(0, 60), text: r.text, time: r.time, pickup: r.pickup, bpm: r.bpm, own: true };
    if (old) store.own[store.own.indexOf(old)] = song;
    else store.own.push(song);
    G.award(store, { xmas: xmasCount(store) }, today());
    save();
    closeDialog(null, document.getElementById('pn-own'));
    renderHome();
  }

  function ownDelete() {
    if (!ownId) return;
    const id = ownId;
    ask('Ta bort låten?', 'Den går inte att få tillbaka.', 'Ta bort', 'Behåll', () => {
      store.own = store.own.filter(s => s.id !== id);
      delete store.songs[id];
      save();
      closeDialog(null, document.getElementById('pn-own'));
      renderHome();
    });
  }

  /* ── Actions ──────────────────────────────────────────────────────────── */

  const actions = {
    'pn:tab': (e, elem) => { showTab(elem.getAttribute('data-tab')); if (tab === 'path') seeCurrent(); },
    'pn:lesson': (e, elem) => startLesson(elem.getAttribute('data-id')),
    'pn:song': (e, elem) => startSong(elem.getAttribute('data-song'), elem.getAttribute('data-mode')),
    'pn:speed': (e, elem) => { const v = Number(elem.value); if ([0.6, 0.8, 1].includes(v)) speed = v; },
    'pn:home': () => { if (lastFinish && lastFinish.kind === 'song') tab = 'songs'; goHome(); },
    'pn:quit': quit,
    'pn:go': () => { if (goFn) goFn(); },
    'pn:alt': () => { if (altFn) altFn(); },
    'pn:mic': () => (mic.on ? (store.settings.mic = false, save(), micStop('user')) : micStart()),
    'pn:midi': midiStart,
    'pn:help': () => openDialog('pn-help'),
    'pn:settings': () => { syncSettings(); openDialog('pn-settings'); },
    'pn:close': closeDialog,
    'pn:setting': changeSetting,
    'pn:reset': () => ask('Börja om från början?', 'Alla poäng, stjärnor, märken och egna låtar tas bort. Det går inte att ångra.', 'Börja om', 'Behåll allt', () => {
      const settings = store.settings;
      store = G.blank();
      store.settings = Object.assign(store.settings, settings, { mic: false, openAll: false });
      save();
      closeDialog(null, document.getElementById('pn-settings'));
      goHome();
    }),
    'pn:askYes': (e, elem) => { const fn = askFn; askFn = null; closeDialog(e, elem); if (fn) fn(); },
    'pn:askNo': (e, elem) => { askFn = null; closeDialog(e, elem); },
    'pn:own': (e, elem) => ownOpen(elem.getAttribute('data-song')),
    'pn:ownEdit': () => ownPreview(),
    'pn:ownSave': ownSave,
    'pn:ownDelete': ownDelete,
  };

  /* ── Start-up ─────────────────────────────────────────────────────────── */

  function init() {
    const id = x => document.getElementById(x);
    dom = {
      home: id('pn-home'), lesson: id('pn-lesson'), finish: id('pn-finish'),
      path: id('pn-path'), songs: id('pn-songs'), badges: id('pn-badges'),
      statStreak: id('pn-stat-streak'), statGoal: id('pn-stat-goal'), statStars: id('pn-stat-stars'),
      mic: id('pn-mic'), mic2: id('pn-mic2'), micnote: id('pn-micnote'), toast: id('pn-toast'),
      progress: id('pn-progress'), progressFill: id('pn-progress-fill'), heard: id('pn-heard'),
      prompt: id('pn-prompt'), sub: id('pn-sub'), card: id('pn-card'), staff: id('pn-staff'), keys: id('pn-keys'),
      foot: id('pn-foot'), feedback: id('pn-feedback'), go: id('pn-go'), alt: id('pn-alt'),
    };
    staff = NO_STAFF;
    load();
    registerActions(actions);
    fillHelp();
    renderMic();
    show('home');
    seeCurrent();
    // A key goes down at the touch, not when the finger lifts.
    dom.keys.addEventListener('pointerdown', e => {
      const k = e.target.closest ? e.target.closest('.pn-key') : null;
      if (!k) return;
      e.preventDefault();
      press(Number(k.getAttribute('data-midi')), 'screen');
    });
    dom.keys.addEventListener('contextmenu', e => e.preventDefault());
    document.addEventListener('keydown', onKeyDown);
    document.addEventListener('visibilitychange', onVisibility);
    window.addEventListener('resize', () => { if (staff) staff.fit(); });
    window.addEventListener('pagehide', () => { if (mic.on) micStop('hidden'); });
    for (const d of document.querySelectorAll('.pn-dialog')) {
      d.addEventListener('click', e => { if (e.target === d && typeof d.close === 'function') d.close(); });
    }
  }

  /* ── For the tests ────────────────────────────────────────────────────── */

  function inspect() {
    const ex = run ? run.ex[run.i] : null;
    return JSON.parse(JSON.stringify({
      view, tab,
      run: run && { kind: run.kind, id: run.id, i: run.i, count: run.ex.length, items: run.items, right: run.right, notes: run.notes, real: run.real, types: run.ex.map(x => x.type) },
      ex: ex && {
        type: ex.type,
        midis: ex.notes ? ex.notes.filter(n => !n.rest).map(n => n.midi) : ex.note ? [ex.note.midi] : [],
        note: ex.note ? ex.note.midi : null,
        choices: ex.choices ? ex.choices.map(n => n.midi) : null,
        from: ex.from || null, hint: !!ex.hint, letters: !!ex.letters, bpm: ex.bpm || null, grade: !!ex.grade,
      },
      tempo: ctl && ctl.info ? ctl.info() : null,
      prompt: dom.prompt.textContent,
      sub: dom.sub.textContent,
      feedback: dom.feedback.textContent,
      feedbackState: dom.feedback.getAttribute('data-state'),
      go: dom.go.hidden ? null : dom.go.textContent,
      alt: dom.alt.hidden ? null : dom.alt.textContent,
      staff: staff ? staff.states() : [],
      keys: keys ? { lo: keys.lo, hi: keys.hi } : null,
      last,
      finish: lastFinish,
      mic: { on: mic.on, starting: mic.starting, error: mic.error, note: mic.note, tune: mic.ear ? mic.ear.tune() : null },
      store: { xp: store.xp, streak: store.streak, lessons: store.lessons, songs: store.songs, notes: store.notes, badges: Object.keys(store.badges), days: store.days, settings: store.settings, own: store.own.length, tune: store.tune },
      next: (nextLesson() || {}).id || null,
      sounds: PN_SOUND.log(),
    }));
  }

  const testEars = {};

  const test = {
    /* A key played, as if heard from `source`. */
    hear(midi, source, more) {
      return noteIn(Object.assign({ midi, source: source || 'midi', t: performance.now(), again: false }, more || {}));
    },
    /* One reading of these samples through the page's own listening. */
    feed(samples, sampleRate, now) {
      if (!testEars[sampleRate]) testEars[sampleRate] = PN_EAR.createListener(sampleRate, { tune: 0 });
      const x = samples instanceof Float32Array ? samples : Float32Array.from(samples);
      return hearFrame(x, now, testEars[sampleRate]).map(e => e.midi);
    },
    /* Play samples through the real audio path, in place of the microphone. */
    play(samples, sampleRate) {
      if (mic.on) micStop('user');
      const ctx = PN_SOUND.context();
      const buffer = ctx.createBuffer(1, samples.length, sampleRate);
      buffer.copyToChannel(samples instanceof Float32Array ? samples : Float32Array.from(samples), 0);
      const player = ctx.createBufferSource();
      player.buffer = buffer;
      micConnect(ctx, player, null);
      mic.player = player;
      player.start();
      return ctx.resume().then(() => ctx.state);
    },
    stopMic: () => micStop('user'),
    today(day) { clock = day || null; if (view === 'home') renderHome(); },
    hurry(k) { tempoScale = k > 0 ? k : 1; },
    reload() { load(); goHome(); },
  };

  return { init, inspect, test };
})();
