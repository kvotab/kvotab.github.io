/*
  vectorize.js -- the page of vectorize.html: getting an image in (a dropped
  or chosen file, a pasted image, a web address), the settings, the two panes
  and the download. The tracing itself is vectorize-trace.js, in a worker, so
  the page stays responsive while it works.

  The two panes share one view -- a zoom and the source point at their centre
  -- so the original and the vector always show the same part of the picture.
  Coordinates throughout are the source image's pixels; the SVG's viewBox is
  that image's size, and its width and height the size of the file as given.

  The vector can be edited: Remove takes whole parts out (each kept as a
  point inside it, its seed), Erase paints parts away (each stroke kept as
  its points and radius). The worker applies both on every trace, so they
  hold as the settings change; Undo and Redo step through them.
*/
'use strict';

(function () {
  const ENGINE = './resources/js/vectorize-trace.js?v=20261124';
  // Larger images are scaled down on the way in; the tracer works on at most
  // MAX_WORK pixels after the Detail enlargement (a phone gets fewer).
  const MAX_SOURCE = 16e6;
  const MAX_WORK = (navigator.deviceMemory && navigator.deviceMemory < 4) ? 4e6 : 10e6;
  const STORE = 'vectorize.settings';
  const PASTE_KEY = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent) ? '⌘V' : 'Ctrl+V';

  // ink: what is traced -- 'dark' (whatever is darker than the paper),
  // 'black' (black lines only, not colours) or 'light' (light lines on dark).
  const INKS = ['dark', 'black', 'light'];
  const PRESETS = {
    lineart: { detail: 2, smooth: 0.7, faint: 70, weight: 45, ink: 'dark', specks: 4, tolerance: 0.5, corners: 15 },
    cartoon: { detail: 2, smooth: 0.7, faint: 70, weight: 45, ink: 'black', specks: 6, tolerance: 0.5, corners: 15 },
    logo: { detail: 3, smooth: 0.5, faint: 30, weight: 50, ink: 'dark', specks: 8, tolerance: 0.3, corners: 60 },
    sketch: { detail: 2, smooth: 1.1, faint: 85, weight: 45, ink: 'dark', specks: 16, tolerance: 0.7, corners: 0 },
    shape: { detail: 1, smooth: 2, faint: 0, weight: 50, ink: 'dark', specks: 60, tolerance: 1, corners: 25 },
  };
  const INK_HINTS = {
    dark: 'Whatever is darker than the paper, in any colour.',
    black: 'Only the black lines and black areas: the colours are left out, however dark. For a coloured cartoon or picture with black outlines.',
    light: 'White or pale lines on a dark ground, as chalk on a blackboard.',
  };
  // preset reads 'custom' once a setting is moved; base keeps the preset it
  // was moved from, for Reset. The poster is posterN sheets across or down
  // (posterBy), on paper (Letter where that is the usual size) laid orient.
  const POSTER_MAX = 30;
  const DEFAULTS = Object.assign({
    preset: 'lineart', base: 'lineart', color: '#000000', background: 'transparent',
    posterBy: 'across', posterN: 4, orient: 'portrait', brush: 28,
    paper: /-(US|CA|MX|PH|CL|CO|VE)$/i.test(navigator.language || '') ? 'letter' : 'a4',
  }, PRESETS.lineart);
  const BRUSH = { min: 6, max: 120 };  // the eraser's width on screen, px

  // Each slider: its range (also in the HTML) and how its value reads.
  const SLIDERS = {
    smooth: { min: 0, max: 3, fmt: v => `${v.toFixed(1)} px` },
    detail: { min: 1, max: 4, fmt: v => `${v}×` },
    faint: { min: 0, max: 100, fmt: v => (v === 0 ? 'off' : `${Math.round(v)} %`) },
    weight: { min: 5, max: 95, fmt: v => `${Math.round(v)} %` },
    specks: { min: 0, max: 100, fmt: v => `${Math.round(v)} px²` },
    tolerance: { min: 0.1, max: 3, fmt: v => `${v.toFixed(2)} px` },
    corners: { min: 0, max: 100, fmt: v => (v === 0 ? 'off' : `${Math.round(v)} %`) },
  };
  // What the black-and-white view depends on (the curve settings do not
  // change it), beside the edits.
  const FIELD_KEYS = ['detail', 'smooth', 'faint', 'ink', 'weight'];

  const $ = id => document.getElementById(id);
  const el = {
    file: $('vz-file'), urlForm: $('vz-url-form'), url: $('vz-url'), source: $('vz-source'),
    preset: $('vz-preset'), inks: Array.from(document.querySelectorAll('input[name="vz-ink"]')), inkHint: $('vz-ink-hint'),
    faint: $('vz-faint'), faintField: $('vz-faint-field'), faintHint: $('vz-faint-hint'),
    color: $('vz-color'), background: $('vz-background'),
    auto: $('vz-auto'), reset: $('vz-reset'),
    modeOriginal: $('vz-mode-original'), modePrepared: $('vz-mode-prepared'), under: $('vz-under'),
    zoomIn: $('vz-zoom-in'), zoomOut: $('vz-zoom-out'), zoomVal: $('vz-zoom-val'), fit: $('vz-fit'),
    copy: $('vz-copy'), download: $('vz-download'), poster: $('vz-poster'),
    pp: $('vz-pp'), ppView: $('vz-pp-view'), ppSvg: $('vz-pp-svg'), ppBg: $('vz-pp-bg'), ppArt: $('vz-pp-art'),
    ppImg: $('vz-pp-img'), ppGrid: $('vz-pp-grid'), ppFromRow: $('vz-pp-from-row'), ppFrom: $('vz-pp-from'),
    ppAcross: $('vz-pp-across'), ppDown: $('vz-pp-down'), ppPaper: $('vz-pp-paper'), ppOrient: $('vz-pp-orient'),
    ppSize: $('vz-pp-size'), ppCount: $('vz-pp-count'), ppNote: $('vz-pp-note'), ppMsg: $('vz-pp-msg'),
    ppGo: $('vz-pp-go'), ppClose: $('vz-pp-close'), ppCancel: $('vz-pp-cancel'),
    paneSrc: $('vz-pane-src'), paneVec: $('vz-pane-vec'), canvas: $('vz-canvas'), srcLabel: $('vz-src-label'),
    svg: $('vz-svg'), page: $('vz-page'), underimg: $('vz-underimg'), path: $('vz-path'),
    checker: $('vz-checker'), ck1: $('vz-ck-1'), ck2: $('vz-ck-2'),
    hl: $('vz-hl'), boxsel: $('vz-boxsel'), brush: $('vz-brush'),
    erasingAll: $('vz-erasing-all'), erasingStrokes: $('vz-erasing-strokes'),
    tools: $('vz-tools'), toolBtns: Array.from(document.querySelectorAll('#vz-tools [data-tool]')),
    brushSize: $('vz-brushsize'), brushInput: $('vz-brush-size'), undo: $('vz-undo'), redo: $('vz-redo'),
    edits: $('vz-edits'), editsText: $('vz-edits-text'), restore: $('vz-restore'),
    empty: $('vz-empty'), busy: $('vz-busy'), status: $('vz-status'), stats: $('vz-stats'),
  };

  let settings = loadSettings();
  let src = null;        // { name, w, h, natW, natH, canvas, url }
  // The trace as shown: d, and its n pieces -- piece k is d.slice(cuts[k],
  // cuts[k + 1]), in boxes[4k..4k + 3], removed by its seed (seeds[2k], seeds[2k + 1]).
  let result = null;     // { d, n, cuts, boxes, seeds, shapes, curves, ms, scale, eraseKey }
  let preview = null;    // the black-and-white field, as a canvas
  let previewKey = '';
  let mode = 'original';
  let autoWeight = null;
  let worker = null, busy = false, pending = false, jobId = 0, jobKey = '', timer = 0;
  const view = { z: 1, cx: 0, cy: 0, minZ: 0.05, fitted: true };

  // The edits to the vector: removed, the seeds of the parts taken out;
  // erase, the erased strokes { id, r, pts } (source pixels), named by
  // eraseKey. An edits object is never changed: each change makes a new
  // one, and the old goes on past, for Undo.
  const NO_EDITS = Object.freeze({ removed: Object.freeze([]), erase: Object.freeze([]), eraseKey: '' });
  let edits = NO_EDITS, past = [], future = [], editsVersion = 0, strokeId = 0;
  let jobEdits = NO_EDITS;   // the edits the trace under way was given
  let tool = 'move';         // 'move', 'remove' or 'erase'
  let gesture = null;        // a Remove click or box, or an Erase stroke, under way
  let panKey = false;        // the space bar held: a drag moves the picture, whatever the tool
  const FAINT_HINT = el.faintHint.textContent;

  // ── Settings ──────────────────────────────────────────────────────────────

  function loadSettings() {
    const s = Object.assign({}, DEFAULTS);
    try {
      const saved = JSON.parse(localStorage.getItem(STORE) || '{}');
      for (const k of Object.keys(SLIDERS)) {
        const v = +saved[k];
        if (Number.isFinite(v)) s[k] = Math.min(SLIDERS[k].max, Math.max(SLIDERS[k].min, v));
      }
      if (INKS.includes(saved.ink)) s.ink = saved.ink;
      else if (saved.invert === true) s.ink = 'light';
      if (Number.isFinite(+saved.brush)) s.brush = Math.round(Math.min(BRUSH.max, Math.max(BRUSH.min, +saved.brush)));
      if (/^#[0-9a-f]{6}$/i.test(saved.color || '')) s.color = saved.color;
      if (saved.background === 'white' || saved.background === 'transparent') s.background = saved.background;
      if (saved.preset === 'custom' || PRESETS[saved.preset]) s.preset = saved.preset;
      if (PRESETS[saved.base]) s.base = saved.base;
      if (saved.posterBy === 'across' || saved.posterBy === 'down') s.posterBy = saved.posterBy;
      if (Number.isInteger(saved.posterN) && saved.posterN >= 1 && saved.posterN <= POSTER_MAX) s.posterN = saved.posterN;
      if (saved.paper === 'a4' || saved.paper === 'letter') s.paper = saved.paper;
      if (saved.orient === 'portrait' || saved.orient === 'landscape') s.orient = saved.orient;
    } catch (e) { /* storage unavailable or unreadable: the defaults stand */ }
    return s;
  }

  function saveSettings() {
    try { localStorage.setItem(STORE, JSON.stringify(settings)); } catch (e) { /* not kept, harmless */ }
  }

  function showSettings() {
    for (const [k, def] of Object.entries(SLIDERS)) {
      $(`vz-${k}`).value = settings[k];
      $(`vz-${k}-out`).textContent = def.fmt(settings[k]);
    }
    for (const r of el.inks) r.checked = r.value === settings.ink;
    showInk();
    el.color.value = settings.color;
    el.background.value = settings.background;
    el.preset.value = settings.preset;
    el.brushInput.value = settings.brush;
    applyLook();
  }

  /* What the chosen way of tracing does, and the setting it has no use for. */
  function showInk() {
    el.inkHint.textContent = INK_HINTS[settings.ink];
    const black = settings.ink === 'black';
    el.faint.disabled = black;
    el.faintField.classList.toggle('vz-off', black);
    el.faintHint.textContent = black ? 'Not used for black lines only: a line that is not black is left out.' : FAINT_HINT;
    // The offer of black lines only (suggestBlack) is spent once another way is chosen.
    if (settings.ink !== 'dark' && el.status.querySelector('.vz-linkbtn')) setStatus('');
  }

  function setInk(ink) {
    if (!INKS.includes(ink) || ink === settings.ink) return;
    settings.ink = ink;
    for (const r of el.inks) r.checked = r.value === ink;
    edited();
    showInk();
    schedule(0);
    draw();
  }

  function usePreset(name) {
    Object.assign(settings, PRESETS[name] || PRESETS.lineart);
    settings.preset = settings.base = PRESETS[name] ? name : 'lineart';
    showSettings();
    saveSettings();
    schedule(0);
  }

  function edited() {
    settings.preset = 'custom';
    el.preset.value = 'custom';
    saveSettings();
  }

  for (const [k, def] of Object.entries(SLIDERS)) {
    const input = $(`vz-${k}`), out = $(`vz-${k}-out`);
    input.addEventListener('input', () => {
      settings[k] = +input.value;
      out.textContent = def.fmt(settings[k]);
      edited();
      // The curve settings only refit, which is quick; the rest retrace.
      schedule(k === 'tolerance' || k === 'corners' || k === 'specks' ? 60 : 150);
    });
  }
  for (const r of el.inks) r.addEventListener('change', () => { if (r.checked) setInk(r.value); });
  el.color.addEventListener('input', () => { settings.color = el.color.value; saveSettings(); applyLook(); });
  el.background.addEventListener('change', () => { settings.background = el.background.value; saveSettings(); applyLook(); });
  el.preset.addEventListener('change', () => usePreset(el.preset.value));
  el.reset.addEventListener('click', () => usePreset(settings.base));
  el.auto.addEventListener('click', () => {
    if (autoWeight == null) return;
    settings.weight = autoWeight;
    edited();
    showSettings();
    schedule(0);
  });

  /* Colour and background change only how the result is drawn. */
  function applyLook() {
    el.path.setAttribute('fill', settings.color);
    el.page.setAttribute('fill', settings.background === 'white' ? '#ffffff' : 'url(#vz-checker)');
  }

  // ── The worker ────────────────────────────────────────────────────────────

  function startWorker() {
    try {
      worker = new Worker(ENGINE);
    } catch (e) {
      worker = null;
      setStatus('This browser could not start the tracing engine.', true);
      return;
    }
    worker.onmessage = onWorker;
    worker.onerror = (e) => {
      e.preventDefault();
      // Most likely out of memory on a large image at high detail.
      const msg = 'The tracing stopped part-way, probably for lack of memory. Try a lower Detail.';
      busy = false; pending = false;
      worker.terminate();
      setBusy(false);
      setStatus(msg, true);
      startWorker();
    };
    if (src) sendSource();
  }

  function sendSource() {
    const data = src.canvas.getContext('2d').getImageData(0, 0, src.w, src.h).data;
    worker.postMessage({ type: 'source', width: src.w, height: src.h, buffer: data.buffer }, [data.buffer]);
  }

  function fieldKey() { return FIELD_KEYS.map(k => settings[k]).join('|'); }

  function schedule(delay) {
    clearTimeout(timer);
    timer = setTimeout(run, delay == null ? 120 : delay);
  }

  /* One trace at a time; a change made meanwhile runs when it is done, with
     the settings as they are then. */
  function run() {
    if (!src || !worker) return;
    if (busy) { pending = true; return; }
    busy = true;
    jobKey = fieldKey() + '|' + editsVersion;
    jobEdits = edits;
    const want = mode === 'prepared';
    setBusy(true, 'Working');
    worker.postMessage({
      type: 'run', id: ++jobId, maxWork: MAX_WORK, wantPreview: want,
      params: {
        detail: settings.detail, smooth: settings.smooth, faint: settings.faint,
        invert: settings.ink === 'light', black: settings.ink === 'black',
        threshold: 1 - settings.weight / 100, specks: settings.specks,
        tolerance: settings.tolerance, corners: settings.corners,
        removed: edits.removed, erase: edits.erase, eraseKey: edits.eraseKey,
      },
    });
  }

  function onWorker(e) {
    const m = e.data;
    if (m.type === 'progress') { setBusy(true, m.stage); return; }
    busy = false;
    if (m.type === 'result') showResult(m);
    else if (m.type === 'error') setStatus(m.message, true);
    if (pending) { pending = false; run(); } else setBusy(false);
  }

  function showResult(m) {
    result = {
      d: m.d, n: m.n, cuts: m.cuts, boxes: m.boxes, seeds: m.seeds, shapes: m.shapes, curves: m.curves,
      ms: m.ms, scale: m.scale, eraseKey: m.eraseKey,
    };
    hitPaths = new Map();
    autoWeight = Math.min(95, Math.max(5, Math.round((1 - m.auto) * 100)));
    el.auto.disabled = false;
    // Parts removed while this was traced go at once; the next trace has them.
    const later = edits.removed.filter(s => !jobEdits.removed.includes(s));
    if (later.length) dropPieces(piecesAtSeeds(later), true);
    el.path.setAttribute('d', result.d);
    if (m.preview) {
      const c = document.createElement('canvas');
      c.width = m.preview.width; c.height = m.preview.height;
      c.getContext('2d').putImageData(new ImageData(m.preview.data, m.preview.width, m.preview.height), 0, 0);
      preview = c;
      previewKey = jobKey;
    }
    if (el.pp.open) showPoster();
    showErasing();
    showStats(m.ms);
    if (result.d && m.scale < settings.detail - 0.05) setStatus(`Detail held at ${m.scale.toFixed(1)}× for an image this size.`);
    else if (result.d && (el.status.classList.contains('vz-error') || /^Detail held/.test(el.status.textContent))) setStatus('');
    if (gesture === null && lastHover) hover(lastHover);
    draw();
  }

  /* The figures under the panes, and the buttons that need a drawing. */
  function showStats(ms) {
    const d = result && result.d;
    el.copy.disabled = el.download.disabled = !d;
    el.poster.disabled = !(d || (src && src.svgText)) || typeof KVOT_POSTER === 'undefined';
    if (!d) {
      el.stats.textContent = '';
      if (result && !edits.removed.length && !edits.erase.length) {
        setStatus(settings.ink === 'black'
          ? 'Nothing came out as black. Raise Line weight, or choose Everything dark under Trace.'
          : 'Nothing came out as ink. Raise Line weight or Faint lines, or, for light lines on a dark background, choose that under Trace.', true);
      }
      return;
    }
    const parts = [
      `${result.n.toLocaleString('en')} ${result.n === 1 ? 'shape' : 'shapes'}`,
      `${result.curves.toLocaleString('en')} curves`,
      size(svgText().length),
    ];
    if (ms != null) parts.push(`${(ms / 1000).toFixed(1)} s`);
    el.stats.textContent = parts.join(' · ');
  }

  function size(bytes) {
    return bytes < 1e6 ? `${Math.max(1, Math.round(bytes / 1024))} kB` : `${(bytes / 1048576).toFixed(1)} MB`;
  }

  function setBusy(on, stage) {
    el.busy.hidden = !on;
    el.busy.textContent = on ? `${stage}…` : '';
  }

  function setStatus(text, isError) {
    el.status.textContent = text || '';
    el.status.classList.toggle('vz-error', !!isError && !!text);
  }

  // ── Getting an image in ───────────────────────────────────────────────────

  async function decode(blob) {
    if (typeof createImageBitmap === 'function' && !/svg/i.test(blob.type)) {
      try {
        const bmp = await createImageBitmap(blob);
        return { img: bmp, w: bmp.width, h: bmp.height, done: () => bmp.close() };
      } catch (e) { /* not every format decodes this way; the <img> may manage */ }
    }
    const url = URL.createObjectURL(blob);
    const img = new Image();
    img.src = url;
    try {
      await img.decode();
    } catch (e) {
      URL.revokeObjectURL(url);
      if (/^text\/html/i.test(blob.type)) throw new Error('That address is a web page, not an image. Right-click the image itself and copy its address.');
      throw new Error('That is not an image this browser can open.');
    }
    // An SVG without a size of its own reports none; give it one.
    const w = img.naturalWidth || 1024, h = img.naturalHeight || 1024;
    return { img, w, h, done: () => URL.revokeObjectURL(url) };
  }

  function baseName(name) {
    const b = String(name || '').split(/[\\/]/).pop().replace(/\.[a-z0-9]{1,5}$/i, '')
      .replace(/[^\w.-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 60);
    return b || 'image';
  }

  async function loadBlob(blob, name) {
    setStatus('Opening the image…');
    const pic = await decode(blob);
    let w = pic.w, h = pic.h;
    const natW = w, natH = h;
    if (w * h > MAX_SOURCE) {
      const f = Math.sqrt(MAX_SOURCE / (w * h));
      w = Math.max(1, Math.round(w * f)); h = Math.max(1, Math.round(h * f));
    }
    const canvas = document.createElement('canvas');
    canvas.width = w; canvas.height = h;
    const ctx = canvas.getContext('2d', { willReadFrequently: true });
    ctx.drawImage(pic.img, 0, 0, w, h);
    pic.done();

    // An SVG is kept as it came too, for the poster to print as it is.
    let svgText = null;
    if (blob.size <= 64e6 && (/svg/i.test(blob.type) || /\.svg$/i.test(name || '') || /<svg[\s>]/i.test(await blob.slice(0, 2048).text()))) {
      try { svgText = await blob.text(); } catch (e) { svgText = null; }
    }

    if (el.pp.open) el.pp.close();
    if (src && src.url) URL.revokeObjectURL(src.url);
    if (src && src.svgArt && src.svgArt.previewUrl) URL.revokeObjectURL(src.svgArt.previewUrl);
    src = { name: baseName(name), w, h, natW, natH, canvas, url: URL.createObjectURL(blob), svgText, svgArt: null };
    posterFrom = svgText ? 'svg' : 'trace';
    result = null; preview = null; previewKey = ''; autoWeight = null;
    el.auto.disabled = true;
    el.path.setAttribute('d', '');
    el.copy.disabled = el.download.disabled = true;
    el.poster.disabled = !svgText || typeof KVOT_POSTER === 'undefined';
    el.stats.textContent = '';
    el.page.setAttribute('width', w); el.page.setAttribute('height', h);
    el.underimg.setAttribute('width', w); el.underimg.setAttribute('height', h);
    el.underimg.setAttribute('href', src.url);
    // The erasing mask reaches well past the picture.
    for (const node of [el.erasingAll, el.erasingAll.parentNode]) {
      node.setAttribute('x', -w); node.setAttribute('y', -h); node.setAttribute('width', 3 * w); node.setAttribute('height', 3 * h);
    }
    // A new picture starts with no edits, and nothing to undo.
    cancelGesture();
    past = []; future = [];
    edits = NO_EDITS; jobEdits = NO_EDITS;
    showEdits();
    el.empty.hidden = true;
    el.tools.hidden = false;
    el.source.hidden = false;
    el.source.textContent = `${src.name} — ${natW} × ${natH} px` + (w !== natW ? ` (traced at ${w} × ${h})` : '') +
      (svgText ? '. An SVG: Poster PDF can print it as it is, in vectors.' : '');
    setStatus('');
    suggestBlack(canvas);

    if (!worker) startWorker(); else sendSource();
    fit();
    schedule(0);
  }

  /* A picture in colour traced by darkness comes out with its darker
     colours as solid shapes; offer to trace its black lines alone. */
  function suggestBlack(canvas) {
    if (settings.ink !== 'dark') return;
    const n = 160, c = document.createElement('canvas');
    const k = Math.min(1, n / Math.max(canvas.width, canvas.height));
    c.width = Math.max(1, Math.round(canvas.width * k)); c.height = Math.max(1, Math.round(canvas.height * k));
    const g = c.getContext('2d', { willReadFrequently: true });
    g.drawImage(canvas, 0, 0, c.width, c.height);
    const px = g.getImageData(0, 0, c.width, c.height).data;
    let coloured = 0, all = 0;
    for (let i = 0; i < px.length; i += 4) {
      if (px[i + 3] < 128) continue;
      all++;
      const mx = Math.max(px[i], px[i + 1], px[i + 2]), mn = Math.min(px[i], px[i + 1], px[i + 2]);
      if (mx - mn > 60 && mx > 60) coloured++;
    }
    if (!all || coloured < 0.08 * all) return;
    setStatus('A picture in colour: to leave its colours out, ');
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'vz-linkbtn';
    b.textContent = 'trace black lines only';
    b.addEventListener('click', () => { setStatus(''); setInk('black'); });
    el.status.append(b, '.');
  }

  function fail(err) {
    setStatus((err && err.message) || String(err), true);
    if (typeof reportFailure === 'function' && !(err && err.expected)) reportFailure('vectorize', err);
  }

  function expected(message) { const e = new Error(message); e.expected = true; return e; }

  async function loadUrl(raw) {
    let url = String(raw || '').trim();
    if (!url) return;
    if (!/^(https?:|data:|blob:)/i.test(url)) url = 'https://' + url;
    setStatus('Fetching the image…');
    let res;
    try {
      res = await fetch(url, { mode: 'cors', credentials: 'omit', referrerPolicy: 'no-referrer' });
    } catch (e) {
      throw expected('The image could not be fetched. Many sites do not let other pages read their images: ' +
        `save it and drop the file here, or copy the image itself and paste it with ${PASTE_KEY}.`);
    }
    if (!res.ok) throw expected(`The address answered ${res.status}${res.statusText ? ' ' + res.statusText : ''}.`);
    const blob = await res.blob();
    let name = 'image';
    try { name = decodeURIComponent(new URL(url, location.href).pathname.split('/').pop()) || name; } catch (e) { /* keep 'image' */ }
    try { await loadBlob(blob, name); } catch (e) { throw expected(e.message); }
  }

  function loadFile(file) {
    if (!file) return;
    const isImage = /^image\//.test(file.type) || /\.(png|jpe?g|gif|webp|avif|bmp|svg|ico|tiff?|heic)$/i.test(file.name || '');
    if (!isImage) { fail(expected(`${file.name || 'That file'} is not an image.`)); return; }
    loadBlob(file, file.name).catch(e => fail(expected(e.message)));
  }

  async function pasteFromClipboard() {
    if (!navigator.clipboard || !navigator.clipboard.read) {
      setStatus(`Press ${PASTE_KEY} to paste an image.`);
      return;
    }
    try {
      const items = await navigator.clipboard.read();
      for (const item of items) {
        const type = item.types.find(t => /^image\//.test(t));
        if (type) { await loadBlob(await item.getType(type), 'pasted-image'); return; }
      }
      for (const item of items) {
        if (item.types.includes('text/plain')) {
          const text = (await (await item.getType('text/plain')).text()).trim();
          if (/^(https?:\/\/|data:image\/)\S+$/i.test(text)) { el.url.value = text; await loadUrl(text); return; }
        }
      }
      setStatus('The clipboard holds no image. Copy an image (not its file) and try again.', true);
    } catch (e) {
      if (e && e.expected) throw e;
      setStatus(`The browser did not let the page read the clipboard. Press ${PASTE_KEY} instead.`);
    }
  }

  /* A drawing to try the page on: drawn here, then saved as a small, fairly
     compressed JPEG, so it has the soft edges and noise of a real one. */
  function sample() {
    const w = 560, h = 380;
    const c = document.createElement('canvas');
    c.width = w; c.height = h;
    const g = c.getContext('2d');
    g.fillStyle = '#fff'; g.fillRect(0, 0, w, h);
    g.strokeStyle = '#1e1e1e'; g.fillStyle = '#1e1e1e';
    g.lineCap = 'round'; g.lineJoin = 'round'; g.lineWidth = 2.2;
    const line = (pts) => { g.beginPath(); g.moveTo(pts[0], pts[1]); for (let i = 2; i < pts.length; i += 6) g.bezierCurveTo(...pts.slice(i, i + 6)); g.stroke(); };
    // The sun and its rays.
    g.beginPath(); g.arc(92, 82, 34, 0, 2 * Math.PI); g.stroke();
    for (let i = 0; i < 12; i++) {
      const a = i * Math.PI / 6;
      g.beginPath(); g.moveTo(92 + 44 * Math.cos(a), 82 + 44 * Math.sin(a)); g.lineTo(92 + 60 * Math.cos(a), 82 + 60 * Math.sin(a)); g.stroke();
    }
    // Hills.
    line([0, 292, 120, 238, 220, 330, 340, 278, 430, 244, 500, 268, w, 252]);
    line([150, 380, 210, 330, 300, 330, 360, 380]);
    // A flower: stem, leaf, seven petals and a solid centre.
    line([402, 300, 396, 250, 412, 210, 402, 168]);
    g.beginPath(); g.moveTo(404, 246); g.bezierCurveTo(430, 224, 456, 230, 466, 240); g.bezierCurveTo(446, 260, 422, 260, 404, 246); g.stroke();
    for (let i = 0; i < 7; i++) {
      g.save(); g.translate(402, 136); g.rotate(i * 2 * Math.PI / 7);
      g.beginPath(); g.ellipse(0, -32, 13, 23, 0, 0, 2 * Math.PI); g.stroke();
      g.restore();
    }
    g.beginPath(); g.arc(402, 136, 13, 0, 2 * Math.PI); g.fill();
    // A faint pencil spiral, for the Faint lines setting.
    g.strokeStyle = '#a2a2a2'; g.lineWidth = 1.1;
    g.beginPath();
    for (let t = 0; t <= 6 * Math.PI; t += 0.05) {
      const r = 4 + t * 3.1, x = 236 + r * Math.cos(t), y = 128 + 0.8 * r * Math.sin(t);
      if (t) g.lineTo(x, y); else g.moveTo(x, y);
    }
    g.stroke();
    // Outlined lettering, for the corners.
    g.strokeStyle = '#1e1e1e'; g.lineWidth = 2;
    g.font = `bold 70px ${getComputedStyle(document.body).fontFamily}`;
    g.strokeText('kvot', 446 - g.measureText('kvot').width / 2 + 0, 362);
    return new Promise((resolve, reject) => c.toBlob(b => (b ? resolve(b) : reject(new Error('The sample could not be drawn.'))), 'image/jpeg', 0.6));
  }

  /* For black lines only, a coloured cartoon: flat colours, light and dark,
     outlined in black, a black cat, and colour meeting colour with no line
     between (the sky and the grass), saved as a JPEG for its colour noise. */
  function cartoon() {
    const w = 560, h = 380;
    const c = document.createElement('canvas');
    c.width = w; c.height = h;
    const g = c.getContext('2d');
    const INK = '#161616';
    g.lineJoin = 'round'; g.lineCap = 'round';
    const shape = (fill, lw, path) => {
      g.beginPath(); path();
      if (fill) { g.fillStyle = fill; g.fill(); }
      if (lw) { g.lineWidth = lw; g.strokeStyle = INK; g.stroke(); }
    };
    const horizon = () => { g.moveTo(-5, 262); g.bezierCurveTo(150, 236, 380, 276, w + 5, 250); };
    g.fillStyle = '#9fd0f5'; g.fillRect(0, 0, w, h);
    shape('#6cbf4a', 0, () => { horizon(); g.lineTo(w + 5, h + 5); g.lineTo(-5, h + 5); g.closePath(); });
    // The sun, and a cloud.
    shape('#ffd21f', 3, () => g.arc(482, 66, 34, 0, 2 * Math.PI));
    shape('#ffffff', 2.5, () => { g.arc(300, 70, 20, Math.PI * 0.9, Math.PI * 1.9); g.arc(330, 62, 24, Math.PI * 1.15, Math.PI * 0.05); g.arc(352, 84, 16, -Math.PI / 2, Math.PI / 2); g.lineTo(290, 100); g.arc(290, 86, 14, Math.PI / 2, Math.PI * 1.5); g.closePath(); });
    // The house: red walls, a dark roof, a brown door, blue windows.
    shape('#d9412b', 3, () => g.rect(84, 172, 176, 128));
    shape('#5b2a1e', 3, () => { g.moveTo(68, 178); g.lineTo(172, 94); g.lineTo(276, 178); g.closePath(); });
    shape('#6b3b1c', 3, () => g.rect(152, 226, 42, 74));
    shape('#2f6fd0', 3, () => g.rect(104, 196, 36, 30));
    shape('#2f6fd0', 3, () => g.rect(206, 196, 36, 30));
    shape(null, 2, () => { g.moveTo(122, 196); g.lineTo(122, 226); g.moveTo(104, 211); g.lineTo(140, 211); g.moveTo(224, 196); g.lineTo(224, 226); g.moveTo(206, 211); g.lineTo(242, 211); });
    shape('#f2c14e', 2, () => g.arc(184, 266, 3.5, 0, 2 * Math.PI));
    // The tree: a brown trunk and a dark green crown, with lines for leaves.
    shape('#7a4a22', 3, () => { g.moveTo(388, 300); g.lineTo(394, 206); g.lineTo(414, 206); g.lineTo(420, 300); g.closePath(); });
    shape('#2c7a33', 3, () => {
      g.moveTo(352, 214);
      g.bezierCurveTo(318, 206, 322, 160, 352, 160); g.bezierCurveTo(350, 120, 400, 108, 412, 136);
      g.bezierCurveTo(440, 112, 478, 136, 466, 166); g.bezierCurveTo(492, 180, 476, 222, 450, 216);
      g.bezierCurveTo(430, 232, 380, 232, 352, 214); g.closePath();
    });
    shape(null, 1.6, () => { g.moveTo(372, 182); g.quadraticCurveTo(382, 172, 394, 176); g.moveTo(420, 154); g.quadraticCurveTo(430, 146, 442, 150); g.moveTo(428, 196); g.quadraticCurveTo(440, 188, 452, 192); });
    shape(null, 3, horizon);
    // Flowers, pink with yellow middles.
    for (const [x, y] of [[300, 318], [332, 336], [470, 326], [510, 344]]) {
      shape(null, 2, () => { g.moveTo(x, y + 8); g.lineTo(x + 2, y + 34); });
      for (let i = 0; i < 5; i++) {
        const a = i * 2 * Math.PI / 5;
        shape('#f07fb0', 1.8, () => g.arc(x + 8 * Math.cos(a), y + 8 * Math.sin(a), 6, 0, 2 * Math.PI));
      }
      shape('#ffd21f', 1.8, () => g.arc(x, y, 5, 0, 2 * Math.PI));
    }
    // A black cat on the grass.
    g.fillStyle = INK;
    g.beginPath(); g.ellipse(120, 334, 30, 17, 0, 0, 2 * Math.PI); g.fill();
    g.beginPath(); g.arc(150, 312, 14, 0, 2 * Math.PI); g.fill();
    g.beginPath(); g.moveTo(139, 304); g.lineTo(141, 288); g.lineTo(150, 299); g.lineTo(159, 288); g.lineTo(162, 304); g.closePath(); g.fill();
    g.lineWidth = 6; g.strokeStyle = INK;
    g.beginPath(); g.moveTo(92, 330); g.bezierCurveTo(70, 326, 72, 300, 84, 296); g.stroke();
    g.fillStyle = '#ffd21f';
    g.beginPath(); g.arc(146, 310, 2.6, 0, 2 * Math.PI); g.arc(156, 310, 2.6, 0, 2 * Math.PI); g.fill();
    return new Promise((resolve, reject) => c.toBlob(b => (b ? resolve(b) : reject(new Error('The sample could not be drawn.'))), 'image/jpeg', 0.75));
  }

  document.querySelectorAll('[data-act]').forEach(b => b.addEventListener('click', () => {
    const act = b.dataset.act;
    if (act === 'pick') el.file.click();
    else if (act === 'paste') pasteFromClipboard().catch(fail);
    else if (act === 'sample') {
      const coloured = settings.ink === 'black';
      (coloured ? cartoon() : sample()).then(blob => loadBlob(blob, coloured ? 'sample-cartoon' : 'sample-drawing')).catch(fail);
    }
  }));
  el.file.addEventListener('change', () => { loadFile(el.file.files[0]); el.file.value = ''; });
  el.urlForm.addEventListener('submit', (e) => { e.preventDefault(); loadUrl(el.url.value).catch(fail); });

  // Paste anywhere: an image is loaded; a web address too, unless it is being
  // pasted into the address field, where it is just text.
  document.addEventListener('paste', (e) => {
    const dt = e.clipboardData;
    if (!dt) return;
    for (const item of dt.items) {
      if (item.kind === 'file' && /^image\//.test(item.type)) {
        e.preventDefault();
        loadBlob(item.getAsFile(), 'pasted-image').catch(err => fail(expected(err.message)));
        return;
      }
    }
    const t = e.target;
    if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
    const text = (dt.getData('text/plain') || '').trim();
    if (/^(https?:\/\/|data:image\/)\S+$/i.test(text)) {
      e.preventDefault();
      el.url.value = text;
      loadUrl(text).catch(fail);
    }
  });

  // Dropping anywhere: a file, or an image dragged from another page (which
  // arrives as its address).
  let dragDepth = 0;
  const droppable = (e) => {
    const types = Array.from((e.dataTransfer && e.dataTransfer.types) || []);
    return types.includes('Files') || types.includes('text/uri-list') || types.includes('text/html');
  };
  const veil = (on) => document.body.classList.toggle('vz-dragging', on);
  window.addEventListener('dragenter', (e) => { if (!droppable(e)) return; e.preventDefault(); dragDepth++; veil(true); });
  window.addEventListener('dragover', (e) => { if (!droppable(e)) return; e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; });
  window.addEventListener('dragleave', (e) => { if (!droppable(e)) return; dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) veil(false); });
  window.addEventListener('drop', (e) => {
    if (!droppable(e)) return;
    e.preventDefault();
    dragDepth = 0; veil(false);
    const dt = e.dataTransfer;
    if (dt.files && dt.files.length) { loadFile(dt.files[0]); return; }
    const html = dt.getData('text/html') || '';
    const m = html.match(/<img[^>]+src\s*=\s*["']([^"']+)["']/i);
    const list = (dt.getData('text/uri-list') || '').split(/\r?\n/).find(l => l && l[0] !== '#');
    const url = (m && m[1].replace(/&amp;/g, '&')) || list || dt.getData('text/plain');
    if (url) { el.url.value = url.trim(); loadUrl(url).catch(fail); }
  });

  // ── The two panes ─────────────────────────────────────────────────────────

  let raf = 0;
  function draw() {
    if (!raf) raf = requestAnimationFrame(() => { raf = 0; drawSource(); drawVector(); });
  }

  function drawSource() {
    const c = el.canvas, r = el.paneSrc.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
    const W = Math.max(1, Math.round(r.width * dpr)), H = Math.max(1, Math.round(r.height * dpr));
    if (c.width !== W || c.height !== H) { c.width = W; c.height = H; }
    const g = c.getContext('2d');
    g.setTransform(1, 0, 0, 1, 0, 0);
    g.clearRect(0, 0, W, H);
    el.zoomVal.textContent = src ? `${Math.round(view.z * 100)} %` : '–';
    if (!src) return;
    const z = view.z * dpr;
    g.setTransform(z, 0, 0, z, W / 2 - view.cx * z, H / 2 - view.cy * z);
    // Transparent pixels are traced as background, so they are shown as it.
    g.fillStyle = settings.ink === 'light' ? '#000' : '#fff';
    g.fillRect(0, 0, src.w, src.h);
    const img = mode === 'prepared' && preview ? preview : src.canvas;
    // Zoomed in, the pixels are shown as pixels: the steps the smoothing is
    // there to remove.
    g.imageSmoothingEnabled = z * (img.width / src.w) < 2;
    g.imageSmoothingQuality = 'high';
    g.drawImage(img, 0, 0, src.w, src.h);
  }

  function drawVector() {
    const r = el.paneVec.getBoundingClientRect();
    if (!src || !r.width || !r.height) return;
    const w = r.width / view.z, h = r.height / view.z;
    el.svg.setAttribute('viewBox', `${view.cx - w / 2} ${view.cy - h / 2} ${w} ${h}`);
    // Checker squares 8 screen pixels whatever the zoom.
    const s = 8 / view.z;
    el.checker.setAttribute('width', 2 * s); el.checker.setAttribute('height', 2 * s);
    el.checker.firstElementChild.setAttribute('width', 2 * s); el.checker.firstElementChild.setAttribute('height', 2 * s);
    for (const [ck, o] of [[el.ck1, 0], [el.ck2, s]]) {
      ck.setAttribute('x', o); ck.setAttribute('y', o); ck.setAttribute('width', s); ck.setAttribute('height', s);
    }
    // The brush is as wide on screen whatever the zoom.
    el.brush.setAttribute('r', settings.brush / 2 / view.z);
  }

  function paneRect() {
    const r = el.paneVec.getBoundingClientRect();
    return r.width && r.height ? r : el.paneSrc.getBoundingClientRect();
  }

  function fit() {
    if (!src) return;
    const r = paneRect();
    if (!r.width || !r.height) return;
    const z = Math.min(r.width / src.w, r.height / src.h) * 0.94;
    Object.assign(view, { z, cx: src.w / 2, cy: src.h / 2, minZ: z / 4, fitted: true });
    draw();
  }

  /* Zoom by k about a point (mx, my) given from the pane's centre. */
  function zoomAt(mx, my, k) {
    if (!src) return;
    const wx = view.cx + mx / view.z, wy = view.cy + my / view.z;
    const z = Math.min(64, Math.max(view.minZ, view.z * k));
    view.cx = wx - mx / z; view.cy = wy - my / z; view.z = z;
    view.fitted = false;
    draw();
  }

  /* Drag to move, scroll or pinch to zoom, double-click to fit. On the
     vector, with Remove or Erase chosen, a drag (or a click) is the tool's;
     the picture then moves with the space bar held, the middle button, or
     two fingers. */
  function panes(pane) {
    const pts = new Map();
    const vec = pane === el.paneVec;
    pane.addEventListener('wheel', (e) => {
      if (!src) return;
      e.preventDefault();
      const r = pane.getBoundingClientRect();
      const dy = e.deltaMode === 1 ? e.deltaY * 33 : e.deltaMode === 2 ? e.deltaY * r.height : e.deltaY;
      zoomAt(e.clientX - r.left - r.width / 2, e.clientY - r.top - r.height / 2, Math.exp(-dy * (e.ctrlKey ? 0.01 : 0.0015)));
    }, { passive: false });
    pane.addEventListener('pointerdown', (e) => {
      if (!src || (e.pointerType === 'mouse' && e.button !== 0 && e.button !== 1)) return;
      // The tools' own buttons and slider.
      if (vec && e.target.closest && e.target.closest('.vz-tools')) return;
      if (e.button === 1) e.preventDefault();
      if (vec && tool !== 'move' && !panKey && e.button === 0 && !pts.size && !gesture) {
        pane.setPointerCapture(e.pointerId);
        startGesture(e);
        return;
      }
      if (vec && gesture) {
        // A second finger: the stroke or box is let go, and the two fingers
        // move and zoom the picture.
        const g = gesture;
        cancelGesture();
        pts.set(g.pointerId, g.last);
      }
      pane.setPointerCapture(e.pointerId);
      pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
      pane.classList.add('vz-grabbing');
    });
    pane.addEventListener('pointermove', (e) => {
      if (vec && gesture && e.pointerId === gesture.pointerId) { moveGesture(e); return; }
      const prev = pts.get(e.pointerId);
      if (!prev) { if (vec) hover(e); return; }
      const now = { x: e.clientX, y: e.clientY };
      if (pts.size === 1) {
        view.cx -= (now.x - prev.x) / view.z; view.cy -= (now.y - prev.y) / view.z;
        view.fitted = false;
        draw();
      } else if (pts.size === 2) {
        // Pinch: follow the midpoint, and zoom by the change in spread.
        const other = [...pts.entries()].find(([id]) => id !== e.pointerId)[1];
        const m0 = { x: (prev.x + other.x) / 2, y: (prev.y + other.y) / 2 }, m1 = { x: (now.x + other.x) / 2, y: (now.y + other.y) / 2 };
        const d0 = Math.hypot(prev.x - other.x, prev.y - other.y), d1 = Math.hypot(now.x - other.x, now.y - other.y);
        view.cx -= (m1.x - m0.x) / view.z; view.cy -= (m1.y - m0.y) / view.z;
        const r = pane.getBoundingClientRect();
        if (d0 > 0) zoomAt(m1.x - r.left - r.width / 2, m1.y - r.top - r.height / 2, d1 / d0);
      }
      pts.set(e.pointerId, now);
    });
    const end = (e) => {
      if (vec && gesture && e.pointerId === gesture.pointerId) {
        if (e.type === 'pointerup') endGesture(e); else cancelGesture();
        return;
      }
      pts.delete(e.pointerId);
      if (!pts.size) pane.classList.remove('vz-grabbing');
    };
    pane.addEventListener('pointerup', end);
    pane.addEventListener('pointercancel', end);
    if (vec) {
      pane.addEventListener('pointerleave', () => {
        lastHover = null;
        if (!gesture) { showHover(null); el.brush.setAttribute('display', 'none'); }
      });
    }
    pane.addEventListener('dblclick', (e) => {
      if (vec && (tool !== 'move' || (e.target.closest && e.target.closest('.vz-tools')))) return;
      fit();
    });
  }
  panes(el.paneSrc);
  panes(el.paneVec);

  el.zoomIn.addEventListener('click', () => zoomAt(0, 0, 1.5));
  el.zoomOut.addEventListener('click', () => zoomAt(0, 0, 1 / 1.5));
  el.zoomVal.addEventListener('click', () => zoomAt(0, 0, 1 / view.z));
  el.fit.addEventListener('click', fit);
  document.addEventListener('keydown', (e) => {
    const t = e.target;
    if (!src || el.pp.open) return;
    // Text being typed keeps the browser's own undo.
    const typing = t && (t.tagName === 'TEXTAREA' || t.isContentEditable ||
      (t.tagName === 'INPUT' && !/^(range|radio|checkbox|color|button)$/.test(t.type)));
    const mod = (e.metaKey || e.ctrlKey) && !e.altKey;
    if (mod && !typing && (e.key === 'z' || e.key === 'Z' || (e.key === 'y' && !e.metaKey))) {
      e.preventDefault();
      if (e.key === 'y' || e.shiftKey) redo(); else undo();
      return;
    }
    if (e.key === 'Escape' && (gesture || tool !== 'move') && !typing) {
      e.preventDefault();
      if (gesture) cancelGesture(); else setTool('move');
      return;
    }
    if (e.metaKey || e.ctrlKey || e.altKey || (t && /^(INPUT|SELECT|TEXTAREA)$/.test(t.tagName))) return;
    if (e.key === ' ' && tool !== 'move') {
      // Held, the space bar lets a drag move the picture.
      e.preventDefault();
      if (!panKey) { panKey = true; el.paneVec.classList.add('vz-panning'); el.brush.setAttribute('display', 'none'); showHover(null); }
      return;
    }
    if ((e.key === '[' || e.key === ']') && tool === 'erase') {
      e.preventDefault();
      setBrush(settings.brush * (e.key === ']' ? 1.25 : 0.8));
      return;
    }
    if (e.key === '+' || e.key === '=') zoomAt(0, 0, 1.5);
    else if (e.key === '-') zoomAt(0, 0, 1 / 1.5);
    else if (e.key === '0') fit();
    else if (e.key === '1') zoomAt(0, 0, 1 / view.z);
    else return;
    e.preventDefault();
  });
  const spaceUp = () => {
    if (!panKey) return;
    panKey = false;
    el.paneVec.classList.remove('vz-panning');
  };
  // The space bar's release is prevented too, so a focused button is not pressed by it.
  document.addEventListener('keyup', (e) => { if (e.key === ' ' && panKey) { e.preventDefault(); spaceUp(); } });
  window.addEventListener('blur', spaceUp);

  if (typeof ResizeObserver === 'function') {
    new ResizeObserver(() => { if (view.fitted) fit(); else draw(); }).observe(el.paneVec);
  } else {
    window.addEventListener('resize', () => { if (view.fitted) fit(); else draw(); });
  }

  function setMode(m) {
    mode = m;
    el.modeOriginal.setAttribute('aria-pressed', String(m === 'original'));
    el.modePrepared.setAttribute('aria-pressed', String(m === 'prepared'));
    el.srcLabel.textContent = m === 'prepared' ? 'Black & white' : 'Original';
    if (m === 'prepared' && src && (!preview || previewKey !== fieldKey())) schedule(0);
    draw();
  }
  el.modeOriginal.addEventListener('click', () => setMode('original'));
  el.modePrepared.addEventListener('click', () => setMode('prepared'));
  el.under.addEventListener('change', () => el.underimg.setAttribute('display', el.under.checked ? 'inline' : 'none'));

  // ── Editing the vector ────────────────────────────────────────────────────

  const MAC = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
  const UNDO_KEY = MAC ? '⌘Z' : 'Ctrl+Z';
  el.undo.title = `Undo (${UNDO_KEY})`;
  el.redo.title = `Redo (${MAC ? '⇧⌘Z' : 'Ctrl+Y'})`;
  const TOUCH = matchMedia('(pointer: coarse)').matches;
  const TOOL_HINTS = TOUCH ? {
    remove: 'Tap a part to take it out, or drag a box round several.',
    erase: 'Paint over what should go.',
  } : {
    remove: 'Click a part to take it out, or drag a box round several.',
    erase: 'Paint over what should go; [ and ] size the brush.',
  };
  const MOVE_HINT = TOUCH ? 'Two fingers move the picture.' : `Hold the space bar to move the picture; ${UNDO_KEY} undoes.`;
  let hitPaths = new Map(), hitCtx = null, lastHover = null, hoverFrame = 0, boxFrame = 0;
  const r2 = (v) => Math.round(v * 100) / 100;

  /* The source point under a pointer on the vector. */
  function toSource(e) {
    const r = el.paneVec.getBoundingClientRect();
    return { x: view.cx + (e.clientX - r.left - r.width / 2) / view.z, y: view.cy + (e.clientY - r.top - r.height / 2) / view.z };
  }

  function setTool(t) {
    cancelGesture();
    const before = tool;
    tool = t;
    for (const b of el.toolBtns) b.setAttribute('aria-pressed', String(b.dataset.tool === t));
    if (t === 'move') el.paneVec.removeAttribute('data-edit'); else el.paneVec.dataset.edit = t;
    el.brushSize.hidden = t !== 'erase';
    el.brush.setAttribute('display', 'none');
    showHover(null);
    if (TOOL_HINTS[t]) setStatus(`${TOOL_HINTS[t]} ${MOVE_HINT}`);
    else if (TOOL_HINTS[before] && el.status.textContent.startsWith(TOOL_HINTS[before])) setStatus('');
  }
  for (const b of el.toolBtns) b.addEventListener('click', () => setTool(b.dataset.tool));

  function setBrush(v) {
    settings.brush = Math.round(Math.min(BRUSH.max, Math.max(BRUSH.min, v)));
    el.brushInput.value = settings.brush;
    el.brush.setAttribute('r', settings.brush / 2 / view.z);
    saveSettings();
  }
  el.brushInput.addEventListener('input', () => setBrush(+el.brushInput.value));

  /* Piece k of the drawing as a path the canvas can test points against. */
  function piecePath(k) {
    let p = hitPaths.get(k);
    if (!p) { p = new Path2D(result.d.slice(result.cuts[k], result.cuts[k + 1])); hitPaths.set(k, p); }
    return p;
  }

  /* The piece at (x, y): the smallest whose fill holds the point, or else
     whose outline passes within slop of it; -1 for none. */
  function pieceAt(x, y, slop) {
    if (!result || !result.n) return -1;
    const B = result.boxes, cand = [];
    for (let k = 0; k < result.n; k++) {
      if (x >= B[4 * k] - slop && x <= B[4 * k + 2] + slop && y >= B[4 * k + 1] - slop && y <= B[4 * k + 3] + slop) cand.push(k);
    }
    if (!cand.length) return -1;
    const area = (k) => (B[4 * k + 2] - B[4 * k]) * (B[4 * k + 3] - B[4 * k + 1]);
    cand.sort((a, b) => area(a) - area(b));
    const g = hitCtx || (hitCtx = document.createElement('canvas').getContext('2d'));
    for (const k of cand) if (g.isPointInPath(piecePath(k), x, y)) return k;
    if (slop > 0) {
      g.lineWidth = 2 * slop;
      for (const k of cand) if (g.isPointInStroke(piecePath(k), x, y)) return k;
    }
    return -1;
  }

  /* The pieces wholly inside the box [x0, y0, x1, y1]. */
  function piecesIn(b) {
    const out = [];
    if (!result) return out;
    const B = result.boxes;
    for (let k = 0; k < result.n; k++) {
      if (B[4 * k] >= b[0] && B[4 * k + 1] >= b[1] && B[4 * k + 2] <= b[2] && B[4 * k + 3] <= b[3]) out.push(k);
    }
    return out;
  }

  /* The pieces the seeds are in. */
  function piecesAtSeeds(seeds) {
    const out = new Set();
    for (const s of seeds) { const k = pieceAt(s[0], s[1], 0); if (k >= 0) out.add(k); }
    return out;
  }

  /* The pieces about to go, in red. */
  function showHover(list) {
    el.hl.setAttribute('d', list && list.length && result ? list.map(k => result.d.slice(result.cuts[k], result.cuts[k + 1])).join('') : '');
  }

  function showBrush(p) {
    el.brush.setAttribute('cx', p.x);
    el.brush.setAttribute('cy', p.y);
    el.brush.setAttribute('r', settings.brush / 2 / view.z);
    el.brush.setAttribute('display', 'inline');
  }

  /* A pointer over the vector, no button down: the brush follows it, or the
     part under it is shown in red. */
  function hover(e) {
    if (e.target && e.target.closest && e.target.closest('.vz-tools')) {
      lastHover = null;
      showHover(null);
      el.brush.setAttribute('display', 'none');
      return;
    }
    lastHover = { clientX: e.clientX, clientY: e.clientY };
    if (!src || panKey || gesture) return;
    if (tool === 'erase') { showBrush(toSource(e)); return; }
    if (tool !== 'remove' || hoverFrame) return;
    hoverFrame = requestAnimationFrame(() => {
      hoverFrame = 0;
      if (!lastHover || tool !== 'remove' || gesture || panKey) return;
      const p = toSource(lastHover);
      const k = pieceAt(p.x, p.y, 5 / view.z);
      showHover(k >= 0 ? [k] : null);
    });
  }

  function startGesture(e) {
    const p = toSource(e);
    gesture = { pointerId: e.pointerId, tool, x0: e.clientX, y0: e.clientY, p0: p, last: { x: e.clientX, y: e.clientY }, moved: false };
    if (tool === 'erase') {
      gesture.r = settings.brush / 2 / view.z;
      gesture.pts = [r2(p.x), r2(p.y)];
      gesture.el = strokeEl(gesture);
      el.erasingStrokes.appendChild(gesture.el);
      el.path.setAttribute('mask', 'url(#vz-erasing)');
      showBrush(p);
    }
  }

  function moveGesture(e) {
    const g = gesture, p = toSource(e);
    g.last = { x: e.clientX, y: e.clientY };
    if (g.tool === 'erase') {
      showBrush(p);
      const n = g.pts.length;
      if (Math.hypot(p.x - g.pts[n - 2], p.y - g.pts[n - 1]) * view.z >= 2) {
        g.pts.push(r2(p.x), r2(p.y));
        g.el.setAttribute('d', strokeD(g.pts));
      }
      return;
    }
    // Remove: past a few pixels, a click becomes a box.
    if (!g.moved && Math.hypot(e.clientX - g.x0, e.clientY - g.y0) < 5) return;
    g.moved = true;
    g.box = [Math.min(g.p0.x, p.x), Math.min(g.p0.y, p.y), Math.max(g.p0.x, p.x), Math.max(g.p0.y, p.y)];
    if (boxFrame) return;
    boxFrame = requestAnimationFrame(() => {
      boxFrame = 0;
      if (gesture !== g) return;
      const b = g.box;
      el.boxsel.setAttribute('x', b[0]); el.boxsel.setAttribute('y', b[1]);
      el.boxsel.setAttribute('width', b[2] - b[0]); el.boxsel.setAttribute('height', b[3] - b[1]);
      el.boxsel.setAttribute('display', 'inline');
      g.inside = piecesIn(b);
      showHover(g.inside);
    });
  }

  function endGesture(e) {
    const g = gesture;
    gesture = null;
    if (g.tool === 'erase') {
      const stroke = { id: ++strokeId, r: r2(g.r), pts: g.pts };
      const erase = edits.erase.concat([stroke]);
      changeEdits({ removed: edits.removed, erase, eraseKey: erase.map(s => s.id).join(',') });
      if (e.pointerType !== 'mouse') el.brush.setAttribute('display', 'none');
      return;
    }
    el.boxsel.setAttribute('display', 'none');
    let hit = [];
    if (g.moved) hit = g.box ? piecesIn(g.box) : [];
    else {
      const p = toSource(e);
      const k = pieceAt(p.x, p.y, (e.pointerType === 'mouse' ? 5 : 12) / view.z);
      if (k >= 0) hit = [k];
    }
    showHover(null);
    if (hit.length) removePieces(hit);
    if (e.pointerType === 'mouse') hover(e);
  }

  function cancelGesture() {
    const g = gesture;
    gesture = null;
    if (!g) return;
    if (g.el) { g.el.remove(); showErasing(); }
    el.boxsel.setAttribute('display', 'none');
    showHover(null);
  }

  function strokeD(pts) {
    const d = ['M', pts[0], pts[1]];
    if (pts.length === 2) d.push('l', 0.01, 0);  // a dab: round caps make it a dot
    for (let i = 2; i < pts.length; i += 2) d.push('L', pts[i], pts[i + 1]);
    return d.join(' ');
  }

  function strokeEl(s) {
    const p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    p.setAttribute('d', strokeD(s.pts));
    p.setAttribute('stroke-width', 2 * s.r);
    return p;
  }

  /* Strokes the trace does not have yet are hidden at once, through a mask
     on the drawing; the stroke being painted too. */
  function showErasing() {
    const g = el.erasingStrokes, live = gesture && gesture.el;
    g.textContent = '';
    if (edits.erase.length && (!result || result.eraseKey !== edits.eraseKey)) {
      for (const s of edits.erase) g.appendChild(strokeEl(s));
    }
    if (live) g.appendChild(live);
    if (g.firstChild) el.path.setAttribute('mask', 'url(#vz-erasing)');
    else el.path.removeAttribute('mask');
  }

  function removePieces(list) {
    if (!result || !list.length) return;
    const seeds = list.map(k => [r2(result.seeds[2 * k]), r2(result.seeds[2 * k + 1])]);
    changeEdits({ removed: edits.removed.concat(seeds), erase: edits.erase, eraseKey: edits.eraseKey });
    dropPieces(new Set(list));
  }

  /* The drawing at once without the pieces in drop; the next trace agrees.
     quiet: only the result, not the picture or the figures. */
  function dropPieces(drop, quiet) {
    if (!result || !drop.size) return;
    const keep = [];
    for (let k = 0; k < result.n; k++) if (!drop.has(k)) keep.push(k);
    const n = keep.length, parts = [];
    const cuts = new Int32Array(n + 1), boxes = new Float32Array(4 * n), seeds = new Float32Array(2 * n);
    let len = 0;
    keep.forEach((k, j) => {
      const s = result.d.slice(result.cuts[k], result.cuts[k + 1]);
      cuts[j] = len;
      len += s.length;
      parts.push(s);
      boxes.set(result.boxes.subarray(4 * k, 4 * k + 4), 4 * j);
      seeds.set(result.seeds.subarray(2 * k, 2 * k + 2), 2 * j);
    });
    cuts[n] = len;
    result = Object.assign({}, result, { d: parts.join(''), n, cuts, boxes, seeds, shapes: n });
    hitPaths = new Map();
    if (quiet) return;
    el.path.setAttribute('d', result.d);
    showStats();
    if (el.pp.open) showPoster();
  }

  function changeEdits(next) {
    past.push(edits);
    if (past.length > 500) past.shift();
    future = [];
    edits = next;
    editsChanged();
  }

  function undo() {
    if (!src || !past.length) return;
    cancelGesture();
    future.push(edits);
    edits = past.pop();
    editsChanged();
  }

  function redo() {
    if (!src || !future.length) return;
    cancelGesture();
    past.push(edits);
    edits = future.pop();
    editsChanged();
  }

  function editsChanged() {
    editsVersion++;
    showEdits();
    showErasing();
    schedule(0);
  }

  function showEdits() {
    el.undo.disabled = !past.length;
    el.redo.disabled = !future.length;
    const n = edits.removed.length, m = edits.erase.length, parts = [];
    if (n) parts.push(`${n.toLocaleString('en')} ${n === 1 ? 'part' : 'parts'} removed`);
    if (m) parts.push(`${m.toLocaleString('en')} ${m === 1 ? 'stroke' : 'strokes'} erased`);
    el.edits.hidden = !parts.length;
    el.editsText.textContent = parts.join(', ') + '.';
  }

  el.undo.addEventListener('click', undo);
  el.redo.addEventListener('click', redo);
  el.restore.addEventListener('click', () => { if (edits.removed.length || edits.erase.length) changeEdits(NO_EDITS); });

  // ── Saving ────────────────────────────────────────────────────────────────

  function svgText() {
    const bg = settings.background === 'white' ? `<rect width="${src.w}" height="${src.h}" fill="#ffffff"/>\n` : '';
    return '<?xml version="1.0" encoding="UTF-8"?>\n' +
      `<svg xmlns="http://www.w3.org/2000/svg" width="${src.natW}" height="${src.natH}" viewBox="0 0 ${src.w} ${src.h}">\n` +
      `${bg}<path fill="${settings.color}" d="${result.d}"/>\n</svg>\n`;
  }

  function save(blob, filename) {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    // Inside the dialog while it is open, as the page behind it is inert.
    (el.pp.open ? el.pp : document.body).appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 10000);
  }

  el.download.addEventListener('click', () => {
    if (!result || !result.d) return;
    save(new Blob([svgText()], { type: 'image/svg+xml' }), `${src.name}.svg`);
  });

  el.copy.addEventListener('click', () => {
    if (!result || !result.d) return;
    if (!navigator.clipboard) { setStatus('This browser does not let the page copy. Use Download SVG.', true); return; }
    navigator.clipboard.writeText(svgText()).then(() => {
      el.copy.textContent = 'Copied';
      setTimeout(() => { el.copy.textContent = 'Copy SVG'; }, 1500);
    }, () => setStatus('The browser did not let the page copy. Use Download SVG.', true));
  });

  // ── The poster ────────────────────────────────────────────────────────────

  /* The drawing printed large over many sheets of paper, to cut and glue
     together. vectorize-poster.js lays the sheets out and writes the PDF;
     here are its dialog, and the picture of the poster with its sheets. An
     SVG file can go on the poster as it is, in its own vectors and colours,
     or as traced. */
  const SVG_NS = 'http://www.w3.org/2000/svg';
  const LEFT_OUT = {
    text: 'text', pictures: 'pictures inside it', filters: 'filter effects', masks: 'masks',
    clipping: 'some clipping', patterns: 'pattern fills', paints: 'some fills',
  };
  let posterArt = null;      // KVOT_POSTER.parse of result.d, with that d
  let posterFrom = 'trace';  // or 'svg': an SVG file as it is
  let posterBusy = false;
  let ppArtD = null;         // the path data the dialog's picture has

  function posterOpts() {
    return { paper: settings.paper, orient: settings.orient, by: settings.posterBy, n: settings.posterN };
  }

  const svgMode = () => !!(src && src.svgText && posterFrom === 'svg');

  /* The drawing the poster is of, or null while there is none to print. */
  function posterDrawing() {
    if (!src) return null;
    if (svgMode()) {
      const a = src.svgArt;
      return a && a.bounds ? a : null;
    }
    if (!result || !result.d) return null;
    if (!posterArt || posterArt.d !== result.d) posterArt = Object.assign(KVOT_POSTER.parse(result.d), { d: result.d });
    return posterArt.bounds ? posterArt : null;
  }

  function openPoster() {
    if (!src || typeof KVOT_POSTER === 'undefined') return;
    el.ppFromRow.hidden = !src.svgText;
    el.ppFrom.value = posterFrom;
    el.ppMsg.textContent = '';
    el.pp.showModal();
    showPoster();
  }

  /* The SVG read for the poster, once a file, when first wanted. */
  async function readSvg() {
    const mine = src;
    mine.svgArt = { pending: true };
    let art;
    try {
      art = await KVOT_POSTER.fromSvg(mine.svgText);
      if (art.preview) art.previewUrl = URL.createObjectURL(new Blob([art.preview], { type: 'image/svg+xml' }));
    } catch (e) {
      art = { error: (e && e.message) || String(e) };
      if (typeof reportFailure === 'function' && !/could not be read/.test(art.error)) reportFailure('vectorize', e);
    }
    if (mine !== src) {
      if (art.previewUrl) URL.revokeObjectURL(art.previewUrl);
      return;
    }
    mine.svgArt = art;
    if (el.pp.open) showPoster();
  }

  const listed = (xs) => (xs.length < 2 ? xs.join('') : `${xs.slice(0, -1).join(', ')} and ${xs[xs.length - 1]}`);

  /* What printing the SVG as it is leaves out, or why it cannot. */
  function svgNote(a) {
    if (!a || a.pending) return '';
    if (a.error) return `${a.error} “The traced drawing” can still be printed.`;
    if (!a.bounds) return 'Nothing in this SVG has a fill or a stroke to print. “The traced drawing” can still be printed.';
    const out = a.notes.filter(k => LEFT_OUT[k]).map(k => LEFT_OUT[k]);
    let s = out.length ? `Left out of the poster: ${listed(out)}.` : '';
    if (a.notes.includes('text')) s += ' To keep text, turn it into outlines (paths) in the program that made the SVG.';
    if (a.notes.includes('gradients')) s += ' Gradients are printed as one colour each.';
    return s.trim();
  }

  /* The dialog as the settings stand; `typing` is the box being typed in,
     which is left as it is. */
  function showPoster(typing) {
    if (svgMode() && !src.svgArt) readSvg();
    el.ppNote.textContent = svgMode() ? svgNote(src.svgArt) : '';
    const art = posterDrawing();
    if (!art) {
      el.ppView.hidden = true;
      el.ppGo.disabled = true;
      el.ppSize.textContent = '';
      el.ppCount.textContent = svgMode() ? (src.svgArt && src.svgArt.pending ? 'Reading the SVG…' : '')
        : busy ? 'The drawing is being traced…' : 'There is no traced drawing to print.';
      return;
    }
    el.ppView.hidden = false;
    const L = KVOT_POSTER.layout(art.bounds, posterOpts());
    if (typing !== 'across') el.ppAcross.value = L.cols;
    if (typing !== 'down') el.ppDown.value = L.rows;
    el.ppPaper.value = settings.paper;
    el.ppOrient.value = settings.orient;
    el.ppSize.textContent = `${Math.round(L.FW / 10)} × ${Math.round(L.FH / 10)} cm`;
    const tooMany = L.sheets > KVOT_POSTER.MAX_SHEETS;
    el.ppCount.textContent = tooMany
      ? `${L.sheets.toLocaleString('en')} sheets of ${L.paper}, more than the ${KVOT_POSTER.MAX_SHEETS} a poster can have. Choose fewer.`
      : `${L.cols} × ${L.rows} = ${L.sheets} ${L.sheets === 1 ? 'sheet' : 'sheets'} of ${L.paper}, ` +
        `and a first page on putting ${L.sheets === 1 ? 'it' : 'them'} together.`;
    el.ppGo.disabled = tooMany || posterBusy;
    drawPoster(L, art);
  }

  /* The finished poster in millimetres: the paper, the drawing on it, the
     seams where one sheet's cut edge lies on the next, and the sheets'
     names where they are large enough to read. */
  function drawPoster(L, art) {
    const pad = Math.max(L.FW, L.FH) * 0.02, vw = L.FW + 2 * pad, vh = L.FH + 2 * pad;
    const set = (node, attrs) => { for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v); };
    el.ppSvg.setAttribute('viewBox', `${L.fx0 - pad} ${L.fy0 - pad} ${vw} ${vh}`);
    el.ppSvg.style.aspectRatio = `${vw} / ${vh}`;
    set(el.ppBg, { x: L.fx0, y: L.fy0, width: L.FW, height: L.FH });
    if (art.painted) {
      // The SVG as it will be printed: its shapes as read, not the file.
      el.ppArt.setAttribute('display', 'none');
      set(el.ppImg, { href: art.previewUrl || '', x: L.ox, y: L.oy, width: L.dw, height: L.dh });
      el.ppImg.removeAttribute('display');
    } else {
      el.ppImg.setAttribute('display', 'none');
      if (ppArtD !== art.d) { el.ppArt.setAttribute('d', art.d); ppArtD = art.d; }
      const b = art.bounds;
      set(el.ppArt, { fill: settings.color, transform: `translate(${L.ox} ${L.oy}) scale(${L.s}) translate(${-b.x0} ${-b.y0})` });
      el.ppArt.removeAttribute('display');
    }
    const grid = el.ppGrid;
    grid.textContent = '';
    const add = (tag, attrs, text) => {
      const e = document.createElementNS(SVG_NS, tag);
      set(e, attrs);
      if (text) e.textContent = text;
      grid.appendChild(e);
    };
    const cut = KVOT_POSTER.CUT_IN;
    for (let c = 1; c < L.cols; c++) add('line', { class: 'vz-pp-seam', x1: c * L.sx - cut, y1: L.fy0, x2: c * L.sx - cut, y2: L.fy0 + L.FH });
    for (let r = 1; r < L.rows; r++) add('line', { class: 'vz-pp-seam', x1: L.fx0, y1: r * L.sy - cut, x2: L.fx0 + L.FW, y2: r * L.sy - cut });
    const box = el.ppSvg.getBoundingClientRect();
    const pxPerMm = Math.min(box.width / vw, box.height / vh);
    const fs = Math.min(L.sx, L.sy) * 0.13;
    if (L.sheets > 1 && fs * pxPerMm >= 9) {
      for (let r = 0; r < L.rows; r++) {
        for (let c = 0; c < L.cols; c++) {
          const x = (c ? c * L.sx - cut : L.fx0) + fs * 0.45, y = (r ? r * L.sy - cut : L.fy0) + fs * 1.2;
          add('text', { class: 'vz-pp-name', x, y, 'font-size': fs }, KVOT_POSTER.sheetName(r, c));
        }
      }
    }
  }

  function posterNumber(which) {
    const input = which === 'across' ? el.ppAcross : el.ppDown;
    const v = +input.value;
    if (input.value === '' || !Number.isInteger(v) || v < 1 || v > POSTER_MAX) return;
    settings.posterBy = which;
    settings.posterN = v;
    saveSettings();
    showPoster(which);
  }

  el.poster.addEventListener('click', openPoster);
  el.ppFrom.addEventListener('change', () => { posterFrom = el.ppFrom.value; showPoster(); });
  el.ppAcross.addEventListener('input', () => posterNumber('across'));
  el.ppDown.addEventListener('input', () => posterNumber('down'));
  // Leaving a box puts back the number the poster is made with.
  el.ppAcross.addEventListener('change', () => showPoster());
  el.ppDown.addEventListener('change', () => showPoster());
  el.ppPaper.addEventListener('change', () => { settings.paper = el.ppPaper.value; saveSettings(); showPoster(); });
  el.ppOrient.addEventListener('change', () => { settings.orient = el.ppOrient.value; saveSettings(); showPoster(); });
  el.ppClose.addEventListener('click', () => el.pp.close());
  el.ppCancel.addEventListener('click', () => el.pp.close());
  // A click on the shade round the dialog closes it too.
  el.pp.addEventListener('click', (e) => { if (e.target === el.pp) el.pp.close(); });

  el.ppGo.addEventListener('click', async () => {
    const art = posterDrawing();
    if (posterBusy || !art) return;
    posterBusy = true;
    el.ppGo.disabled = true;
    el.ppMsg.textContent = 'Making the PDF…';
    try {
      const opts = posterOpts();
      const L = KVOT_POSTER.layout(art.bounds, opts);
      const blob = await KVOT_POSTER.build(Object.assign({ art, color: settings.color, name: src.name }, opts));
      save(blob, `${src.name}-poster-${L.cols}x${L.rows}-${L.paper}.pdf`);
      el.ppMsg.textContent = `Saved: ${L.sheets + 1} pages, ${size(blob.size)}.`;
    } catch (e) {
      el.ppMsg.textContent = (e && e.message) || String(e);
      if (typeof reportFailure === 'function') reportFailure('vectorize', e);
    } finally {
      posterBusy = false;
      if (el.pp.open) showPoster();
    }
  });

  // ── Start ─────────────────────────────────────────────────────────────────

  document.querySelectorAll('.vz-pastekey').forEach(k => { k.textContent = PASTE_KEY; });
  showSettings();
  startWorker();
  draw();
})();
