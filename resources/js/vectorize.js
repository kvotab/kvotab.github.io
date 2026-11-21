/*
  vectorize.js -- the page of vectorize.html: getting an image in (a dropped
  or chosen file, a pasted image, a web address), the settings, the two panes
  and the download. The tracing itself is vectorize-trace.js, in a worker, so
  the page stays responsive while it works.

  The two panes share one view -- a zoom and the source point at their centre
  -- so the original and the vector always show the same part of the picture.
  Coordinates throughout are the source image's pixels; the SVG's viewBox is
  that image's size, and its width and height the size of the file as given.
*/
'use strict';

(function () {
  const ENGINE = './resources/js/vectorize-trace.js?v=20261121';
  // Larger images are scaled down on the way in; the tracer works on at most
  // MAX_WORK pixels after the Detail enlargement (a phone gets fewer).
  const MAX_SOURCE = 16e6;
  const MAX_WORK = (navigator.deviceMemory && navigator.deviceMemory < 4) ? 4e6 : 10e6;
  const STORE = 'vectorize.settings';
  const PASTE_KEY = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent) ? '⌘V' : 'Ctrl+V';

  const PRESETS = {
    lineart: { detail: 2, smooth: 0.7, faint: 70, weight: 45, invert: false, specks: 4, tolerance: 0.5, corners: 15 },
    logo: { detail: 3, smooth: 0.5, faint: 30, weight: 50, invert: false, specks: 8, tolerance: 0.3, corners: 60 },
    sketch: { detail: 2, smooth: 1.1, faint: 85, weight: 45, invert: false, specks: 16, tolerance: 0.7, corners: 0 },
    shape: { detail: 1, smooth: 2, faint: 0, weight: 50, invert: false, specks: 60, tolerance: 1, corners: 25 },
  };
  // preset reads 'custom' once a setting is moved; base keeps the preset it
  // was moved from, for Reset.
  const DEFAULTS = Object.assign({ preset: 'lineart', base: 'lineart', color: '#000000', background: 'transparent' }, PRESETS.lineart);

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
  // change it).
  const FIELD_KEYS = ['detail', 'smooth', 'faint', 'invert', 'weight'];

  const $ = id => document.getElementById(id);
  const el = {
    file: $('vz-file'), urlForm: $('vz-url-form'), url: $('vz-url'), source: $('vz-source'),
    preset: $('vz-preset'), invert: $('vz-invert'), color: $('vz-color'), background: $('vz-background'),
    auto: $('vz-auto'), reset: $('vz-reset'),
    modeOriginal: $('vz-mode-original'), modePrepared: $('vz-mode-prepared'), under: $('vz-under'),
    zoomIn: $('vz-zoom-in'), zoomOut: $('vz-zoom-out'), zoomVal: $('vz-zoom-val'), fit: $('vz-fit'),
    copy: $('vz-copy'), download: $('vz-download'),
    paneSrc: $('vz-pane-src'), paneVec: $('vz-pane-vec'), canvas: $('vz-canvas'), srcLabel: $('vz-src-label'),
    svg: $('vz-svg'), page: $('vz-page'), underimg: $('vz-underimg'), path: $('vz-path'),
    checker: $('vz-checker'), ck1: $('vz-ck-1'), ck2: $('vz-ck-2'),
    empty: $('vz-empty'), busy: $('vz-busy'), status: $('vz-status'), stats: $('vz-stats'),
  };

  let settings = loadSettings();
  let src = null;        // { name, w, h, natW, natH, canvas, url }
  let result = null;     // { d, shapes, curves, ms, scale }
  let preview = null;    // the black-and-white field, as a canvas
  let previewKey = '';
  let mode = 'original';
  let autoWeight = null;
  let worker = null, busy = false, pending = false, jobId = 0, jobKey = '', timer = 0;
  const view = { z: 1, cx: 0, cy: 0, minZ: 0.05, fitted: true };

  // ── Settings ──────────────────────────────────────────────────────────────

  function loadSettings() {
    const s = Object.assign({}, DEFAULTS);
    try {
      const saved = JSON.parse(localStorage.getItem(STORE) || '{}');
      for (const k of Object.keys(SLIDERS)) {
        const v = +saved[k];
        if (Number.isFinite(v)) s[k] = Math.min(SLIDERS[k].max, Math.max(SLIDERS[k].min, v));
      }
      if (typeof saved.invert === 'boolean') s.invert = saved.invert;
      if (/^#[0-9a-f]{6}$/i.test(saved.color || '')) s.color = saved.color;
      if (saved.background === 'white' || saved.background === 'transparent') s.background = saved.background;
      if (saved.preset === 'custom' || PRESETS[saved.preset]) s.preset = saved.preset;
      if (PRESETS[saved.base]) s.base = saved.base;
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
    el.invert.checked = settings.invert;
    el.color.value = settings.color;
    el.background.value = settings.background;
    el.preset.value = settings.preset;
    applyLook();
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
  el.invert.addEventListener('change', () => { settings.invert = el.invert.checked; edited(); schedule(0); draw(); });
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
    jobKey = fieldKey();
    const want = mode === 'prepared';
    setBusy(true, 'Working');
    worker.postMessage({
      type: 'run', id: ++jobId, maxWork: MAX_WORK, wantPreview: want,
      params: {
        detail: settings.detail, smooth: settings.smooth, faint: settings.faint, invert: settings.invert,
        threshold: 1 - settings.weight / 100, specks: settings.specks,
        tolerance: settings.tolerance, corners: settings.corners,
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
    result = { d: m.d, shapes: m.shapes, curves: m.curves, ms: m.ms, scale: m.scale };
    autoWeight = Math.min(95, Math.max(5, Math.round((1 - m.auto) * 100)));
    el.auto.disabled = false;
    el.path.setAttribute('d', m.d);
    if (m.preview) {
      const c = document.createElement('canvas');
      c.width = m.preview.width; c.height = m.preview.height;
      c.getContext('2d').putImageData(new ImageData(m.preview.data, m.preview.width, m.preview.height), 0, 0);
      preview = c;
      previewKey = jobKey;
    }
    el.copy.disabled = el.download.disabled = !m.d;
    if (!m.d) {
      el.stats.textContent = '';
      setStatus('Nothing came out as ink. Raise Line weight or Faint lines, or, for light lines on a dark background, tick that box.', true);
    } else {
      const parts = [
        `${m.shapes.toLocaleString('en')} shapes`,
        `${m.curves.toLocaleString('en')} curves`,
        size(svgText().length),
        `${(m.ms / 1000).toFixed(1)} s`,
      ];
      el.stats.textContent = parts.join(' · ');
      if (m.scale < settings.detail - 0.05) setStatus(`Detail held at ${m.scale.toFixed(1)}× for an image this size.`);
      else if (el.status.classList.contains('vz-error') || /^Detail held/.test(el.status.textContent)) setStatus('');
    }
    draw();
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

    if (src && src.url) URL.revokeObjectURL(src.url);
    src = { name: baseName(name), w, h, natW, natH, canvas, url: URL.createObjectURL(blob) };
    result = null; preview = null; previewKey = ''; autoWeight = null;
    el.auto.disabled = true;
    el.path.setAttribute('d', '');
    el.copy.disabled = el.download.disabled = true;
    el.stats.textContent = '';
    el.page.setAttribute('width', w); el.page.setAttribute('height', h);
    el.underimg.setAttribute('width', w); el.underimg.setAttribute('height', h);
    el.underimg.setAttribute('href', src.url);
    el.empty.hidden = true;
    el.source.hidden = false;
    el.source.textContent = `${src.name} — ${natW} × ${natH} px` + (w !== natW ? ` (traced at ${w} × ${h})` : '');
    setStatus('');

    if (!worker) startWorker(); else sendSource();
    fit();
    schedule(0);
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

  document.querySelectorAll('[data-act]').forEach(b => b.addEventListener('click', () => {
    const act = b.dataset.act;
    if (act === 'pick') el.file.click();
    else if (act === 'paste') pasteFromClipboard().catch(fail);
    else if (act === 'sample') sample().then(blob => loadBlob(blob, 'sample-drawing')).catch(fail);
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
    g.fillStyle = settings.invert ? '#000' : '#fff';
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

  function panes(pane) {
    const pts = new Map();
    pane.addEventListener('wheel', (e) => {
      if (!src) return;
      e.preventDefault();
      const r = pane.getBoundingClientRect();
      const dy = e.deltaMode === 1 ? e.deltaY * 33 : e.deltaMode === 2 ? e.deltaY * r.height : e.deltaY;
      zoomAt(e.clientX - r.left - r.width / 2, e.clientY - r.top - r.height / 2, Math.exp(-dy * (e.ctrlKey ? 0.01 : 0.0015)));
    }, { passive: false });
    pane.addEventListener('pointerdown', (e) => {
      if (!src || (e.pointerType === 'mouse' && e.button !== 0)) return;
      pane.setPointerCapture(e.pointerId);
      pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
      pane.classList.add('vz-grabbing');
    });
    pane.addEventListener('pointermove', (e) => {
      const prev = pts.get(e.pointerId);
      if (!prev) return;
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
    const end = (e) => { pts.delete(e.pointerId); if (!pts.size) pane.classList.remove('vz-grabbing'); };
    pane.addEventListener('pointerup', end);
    pane.addEventListener('pointercancel', end);
    pane.addEventListener('dblclick', fit);
  }
  panes(el.paneSrc);
  panes(el.paneVec);

  el.zoomIn.addEventListener('click', () => zoomAt(0, 0, 1.5));
  el.zoomOut.addEventListener('click', () => zoomAt(0, 0, 1 / 1.5));
  el.zoomVal.addEventListener('click', () => zoomAt(0, 0, 1 / view.z));
  el.fit.addEventListener('click', fit);
  document.addEventListener('keydown', (e) => {
    const t = e.target;
    if (!src || e.metaKey || e.ctrlKey || e.altKey || (t && /^(INPUT|SELECT|TEXTAREA)$/.test(t.tagName))) return;
    if (e.key === '+' || e.key === '=') zoomAt(0, 0, 1.5);
    else if (e.key === '-') zoomAt(0, 0, 1 / 1.5);
    else if (e.key === '0') fit();
    else if (e.key === '1') zoomAt(0, 0, 1 / view.z);
    else return;
    e.preventDefault();
  });

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

  // ── Saving ────────────────────────────────────────────────────────────────

  function svgText() {
    const bg = settings.background === 'white' ? `<rect width="${src.w}" height="${src.h}" fill="#ffffff"/>\n` : '';
    return '<?xml version="1.0" encoding="UTF-8"?>\n' +
      `<svg xmlns="http://www.w3.org/2000/svg" width="${src.natW}" height="${src.natH}" viewBox="0 0 ${src.w} ${src.h}">\n` +
      `${bg}<path fill="${settings.color}" d="${result.d}"/>\n</svg>\n`;
  }

  el.download.addEventListener('click', () => {
    if (!result || !result.d) return;
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([svgText()], { type: 'image/svg+xml' }));
    a.download = `${src.name}.svg`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  });

  el.copy.addEventListener('click', () => {
    if (!result || !result.d) return;
    if (!navigator.clipboard) { setStatus('This browser does not let the page copy. Use Download SVG.', true); return; }
    navigator.clipboard.writeText(svgText()).then(() => {
      el.copy.textContent = 'Copied';
      setTimeout(() => { el.copy.textContent = 'Copy SVG'; }, 1500);
    }, () => setStatus('The browser did not let the page copy. Use Download SVG.', true));
  });

  // ── Start ─────────────────────────────────────────────────────────────────

  document.querySelectorAll('.vz-pastekey').forEach(k => { k.textContent = PASTE_KEY; });
  showSettings();
  startWorker();
  draw();
})();
