/* ==========================================================================
   SVENSK TEXT - the page (svensk_text.html)

   English subtitles in, Swedish subtitles out, in the browser and for free.
   The translating is done by one of two engines, both on the visitor's own
   computer:

     - Google's translator built into Chrome and Edge (the Translator API,
       Chrome 138 and later on a computer). The browser fetches its English
       to Swedish model the first time; create() needs the click that asked
       for it, which is why nothing is awaited before it in run().
     - OPUS-MT English to Swedish (University of Helsinki), run in the page
       with Transformers.js, for every other browser. It is fetched from
       jsDelivr and Hugging Face the first time it is chosen, and it is fed
       one sentence at a time: in a batch the shorter sentences come back
       with junk on the end, and a longer input loses sentences.

   What goes to either engine and what comes back is ST_CORE's business
   (svensk_text-core.js); this file is the screen, the list, the preview,
   the run and the saving. Work in progress is kept in this browser only.
   ========================================================================== */

const ST = (() => {
  const {
    SAMPLE_SRT, SAMPLE_GOOGLE, fmtSrtTime, fmtClock, stripTags, visLen, isDialogue,
    decodeBytes, parseSubtitles, normalizeCue, cleanSDH, buildUnits, splitForParts,
    phrasebook, postFix, polish, computeQA, nextActiveIn, buildSRT, encodeText,
    splitSentences, collectNames, isNamesOnly, chunkUnits, outName,
  } = ST_CORE;

  const $ = (s, r) => (r || document).querySelector(s);
  const KEY = 'kvot-st-v1';
  const TRANSFORMERS_URL = 'https://cdn.jsdelivr.net/npm/@huggingface/transformers@3.8.1';
  const OPUS_MODEL = 'Xenova/opus-mt-en-sv';
  const DEFAULTS = { engine: 'chrome', engineChosen: false, audience: 'adult', maxLen: 42, dash: 'nospace', sdh: 'remove', fillers: true, extend: true, encoding: 'utf8bom' };
  const S = {
    p: null, set: { ...DEFAULTS }, sel: 1, filter: 'all', q: '', qa: [], job: { running: false }, rows: new Map(),
    editing: 0, play: null, dirty: new Set(), frame: 0, names: null,
    chrome: { state: 'checking', tr: null }, opus: { state: 'idle', pipe: null, loading: null, progress: 0 },
  };

  function opts() {
    const s = S.set;
    return { cps: s.audience === 'kids' ? 13 : 17, maxLen: Math.min(60, Math.max(30, parseInt(s.maxLen, 10) || 42)), dash: s.dash, extend: !!s.extend, sdh: s.sdh, fillers: !!s.fillers, encoding: s.encoding };
  }

  /* ---------- the translators ---------- */
  // A browser built on Chrome without Google's models (the desktop apps that
  // embed Chromium) has the API and never answers; it counts as missing.
  const hasTranslator = () => !!(self.Translator && typeof self.Translator.availability === 'function');
  const withTimeout = (p, ms) => Promise.race([p, new Promise(r => setTimeout(() => r('timeout'), ms))]);

  async function checkChrome() {
    let st = 'missing';
    if (hasTranslator()) {
      try { st = await withTimeout(self.Translator.availability({ sourceLanguage: 'en', targetLanguage: 'sv' }), 6000); }
      catch { st = 'unavailable'; }
    }
    S.chrome.state = st;
    if (!S.set.engineChosen) S.set.engine = st === 'missing' || st === 'unavailable' || st === 'timeout' ? 'opus' : 'chrome';
    renderEngines();
    renderRail();
  }
  async function chromeTranslator() {
    if (S.chrome.tr) return S.chrome.tr;
    if (!hasTranslator()) throw { code: 'chrome-missing' };
    S.chrome.tr = await self.Translator.create({
      sourceLanguage: 'en', targetLanguage: 'sv',
      monitor(m) {
        m.addEventListener('downloadprogress', e => {
          const v = e.total ? e.loaded / e.total : e.loaded;
          S.job.note = `Chrome is downloading Google's English-to-Swedish model: ${Math.round(Math.min(1, v) * 100)}%`;
          renderRail();
        });
      },
    });
    S.chrome.state = 'available';
    renderEngines();
    return S.chrome.tr;
  }
  // Each engine takes a list of lines and gives back the translated lines in the same order.
  async function translateChrome(lines) {
    const tr = await chromeTranslator();
    if (lines.length > 1) {
      const out = String(await tr.translate(lines.join('\n'))).split('\n');
      if (out.length === lines.length) return out;
    }
    const out = [];
    for (const l of lines) out.push(String(await tr.translate(l)));
    return out;
  }
  async function opusTranslator() {
    if (S.opus.pipe) return S.opus.pipe;
    if (!S.opus.loading) {
      S.opus.loading = (async () => {
        S.opus.state = 'downloading';
        renderEngines();
        let T;
        try { T = await import(TRANSFORMERS_URL); }
        catch { throw { code: 'opus-download' }; }
        T.env.allowLocalModels = false;
        const files = {};
        return T.pipeline('translation', OPUS_MODEL, {
          dtype: 'q8', device: 'wasm',
          progress_callback: p => {
            if (p.status !== 'progress' || !p.file || !p.total) return;
            files[p.file] = { loaded: p.loaded, total: p.total };
            const all = Object.values(files), loaded = all.reduce((a, f) => a + f.loaded, 0), total = all.reduce((a, f) => a + f.total, 0);
            S.opus.progress = total ? loaded / total : 0;
            S.job.note = `Downloading the open model: ${Math.round(loaded / 1e6)} of ${Math.max(Math.round(total / 1e6), 100)} MB`;
            renderEngines(); renderRail();
          },
        });
      })();
    }
    try { S.opus.pipe = await S.opus.loading; }
    catch (e) { S.opus.loading = null; S.opus.state = 'idle'; renderEngines(); throw e && e.code ? e : { code: 'opus-download', message: e && e.message }; }
    S.opus.state = 'ready';
    renderEngines();
    return S.opus.pipe;
  }
  async function translateOpus(lines) {
    const pipe = await opusTranslator();
    const names = S.names || (S.names = collectNames(S.p.cues));
    const out = [];
    for (const line of lines) {
      const parts = [];
      for (const s of splitSentences(line)) {
        if (isNamesOnly(s, names)) { parts.push(s); continue; }
        const words = s.split(/\s+/).length;
        const res = await pipe(s, { max_new_tokens: Math.min(200, 12 + Math.ceil(words * 2.5)), num_beams: 1 });
        let txt = String((Array.isArray(res) ? res[0] : res).translation_text || '').trim();
        // The model learnt on film subtitles: it adds speaker hyphens, and a reply nobody said.
        txt = txt.replace(/^[-–—]\s*/, '').replace(/\s+[-–—]\s+(?=\p{Lu})/gu, ' ');
        const said = splitSentences(txt);
        if (said.length > 1) txt = said[0];
        parts.push(txt.replace(/([.!?…])[.!?…]+$/u, '$1'));
        await new Promise(r => setTimeout(r, 0));
      }
      out.push(parts.join(' '));
    }
    return out;
  }
  const ENGINE_ERR = {
    'chrome-missing': 'Google’s translator isn’t built into this browser. Open the page in Chrome or Edge on a computer (version 138 or later), or choose the open model under Translator.',
    'chrome-unavailable': 'Chrome can’t translate English to Swedish on this computer. Choose the open model under Translator instead.',
    'opus-download': 'Couldn’t download the open model. Check the internet connection and press Resume. It’s only needed the first time.',
  };
  function engineError(e) {
    if (!e) return 'Something went wrong. Press Resume to try again.';
    if (ENGINE_ERR[e.code]) return ENGINE_ERR[e.code];
    if (e.name === 'NotAllowedError') return 'Chrome needs a click to start the download. Press the button again.';
    if (e.name === 'NotSupportedError' || e.name === 'OperationError') return 'Chrome couldn’t prepare the English-to-Swedish translator: ' + (e.message || e.name) + '. Choose the open model under Translator instead.';
    return 'Translation stopped: ' + (e.message || String(e)) + '. Press Resume to try again.';
  }

  /* ---------- the project ---------- */
  function makeProject(name, parsed, kind, sdh) {
    parsed.sort((a, b) => a.start - b.start);
    const cues = parsed.map((c, i) => {
      const nc = normalizeCue(c.raw);
      return { n: i + 1, start: c.start, end: c.end, raw: nc.text, pos: nc.pos, ital: nc.ital, en: '', removed: false, sv: null, prev: null, why: '', by: '', err: '', pieces: null };
    });
    applySDH(cues, sdh);
    return { v: 1, name, kind, cues, phase: 'new', stats: null };
  }
  function applySDH(cues, mode) {
    for (const c of cues) {
      if (c.kept) { c.en = c.raw; c.removed = false; continue; }
      const t = mode === 'remove' ? cleanSDH(c.raw) : c.raw;
      c.en = t;
      c.removed = !stripTags(t).trim();
    }
  }
  const active = () => S.p.cues.filter(c => !c.removed && c.en);
  const pendingIds = () => active().filter(c => c.sv == null).map(c => c.n);

  // Puts one translated sentence back into the subtitles it came from.
  function applyUnit(u, sv, by) {
    const o = opts(), cues = S.p.cues, notes = [];
    let t = sv == null ? '' : String(sv);
    if (by === 'google') t = postFix(t, u.text, notes);
    if (by === 'phrasebook') notes.push('Standard subtitle wording.');
    const live = u.parts.filter(p => p.clean);
    const pieces = live.length > 1 ? splitForParts(t, live.map(p => Math.max(1, visLen(p.clean)))) : [t];
    const multi = live.length > 1 ? `One sentence over subtitles ${live[0].n}–${live[live.length - 1].n}.` : '';
    const touched = new Set();
    for (const p of u.parts) {
      const c = cues[p.n - 1];
      if (!c.pieces) c.pieces = {};
      const i = live.indexOf(p);
      c.pieces[p.k] = i >= 0 ? pieces[i] : '';
      c.notes = c.notes || [];
      if (p.clean !== p.en && p.clean) c.notes.push('Fillers left out.');
      if (!p.clean) c.notes.push('Only fillers, left out.');
      if (multi) c.notes.push(multi);
      c.notes.push(...notes);
      c.via = by;
      touched.add(c);
    }
    for (const c of touched) {
      const lines = isDialogue(c.en) ? c.en.split('\n').length : 1;
      if (Object.keys(c.pieces).length < lines) continue;
      if (c.by === 'you') { c.pieces = null; c.notes = []; continue; }
      const parts = [];
      for (let k = 0; k < lines; k++) parts.push(c.pieces[k] || '');
      const kept = parts.filter(Boolean);
      c.sv = polish(kept.length > 1 ? kept.map(x => '-' + x).join('\n') : (kept[0] || ''), o);
      c.by = c.via === 'phrasebook' ? 'phrasebook' : 'google';
      c.why = [...new Set(c.notes)].join(' ');
      c.prev = null; c.err = ''; c.pieces = null; c.notes = [];
      qaOne(c.n);
      if (c.n > 1) qaOne(c.n - 1);
      touch(c.n);
    }
  }

  // The sample scene as Google translated it, put through the same steps as a run.
  function makeSampleProject() {
    const p = makeProject('Sample scene', parseSubtitles(SAMPLE_SRT), 'sample', 'remove');
    S.p = p;
    const units = buildUnits(p.cues, { fillers: true });
    for (const u of units) {
      const pb = phrasebook(u.text);
      if (pb) applyUnit(u, pb, 'phrasebook');
      else if (!u.text) applyUnit(u, '', 'filler');
      else applyUnit(u, SAMPLE_GOOGLE[u.text] ?? null, 'google');
    }
    p.phase = 'done';
    p.stats = { units: units.length };
    return p;
  }

  function setProject(p, sel) {
    stopPlay();
    S.p = p;
    S.names = null;
    S.editing = 0;
    const first = p.cues.find(c => !c.removed) || p.cues[0];
    S.sel = sel && p.cues[sel - 1] ? sel : (first ? first.n : 1);
    tlStatic = null;
    qaAll();
    buildList();
    renderAll();
  }

  function nextActive(n) { return nextActiveIn(S.p.cues, n); }
  function qaAll() { const o = opts(); S.qa = S.p.cues.map(c => computeQA(c, nextActive(c.n), o)); }
  function qaOne(n) { S.qa[n - 1] = computeQA(S.p.cues[n - 1], nextActive(n), opts()); }

  /* ---------- text with <i>, <b> and <u>, and nothing else, as formatting ---------- */
  function renderRich(el, text) {
    el.replaceChildren();
    const stack = [el];
    const re = /<(\/?)([ibu])>|([^<]+|<)/gi;
    const t = String(text ?? '').replace(/\{\\[^}]*\}/g, '');
    let m;
    while ((m = re.exec(t))) {
      const top = stack[stack.length - 1];
      if (m[2]) {
        if (m[1]) { if (stack.length > 1) stack.pop(); }
        else { const tag = m[2].toLowerCase(); const e = document.createElement(tag === 'i' ? 'em' : tag === 'b' ? 'strong' : 'u'); top.appendChild(e); stack.push(e); }
      } else top.appendChild(document.createTextNode(m[3]));
    }
  }

  /* ---------- the list ---------- */
  const ROW_HTML = '<div class="st-n"></div><div class="st-t"></div><div class="st-en"></div><div class="st-sv"></div><div class="st-qa"></div>';
  function buildList() {
    const list = $('#st-list');
    list.replaceChildren();
    S.rows.clear();
    const frag = document.createDocumentFragment();
    for (const c of S.p.cues) {
      const r = document.createElement('div');
      r.className = 'st-row';
      r.dataset.n = c.n;
      r.innerHTML = ROW_HTML;
      S.rows.set(c.n, r);
      fillRow(r, c);
      frag.appendChild(r);
    }
    list.appendChild(frag);
    applyFilter();
  }
  function chip(text, level, title) {
    const s = document.createElement('span');
    s.className = 'st-chip' + (level ? ' st-' + level : '');
    s.textContent = text;
    if (title) s.title = title;
    return s;
  }
  function fillRow(r, c) {
    const q = S.qa[c.n - 1] || { level: 'todo', issues: [], lens: [] };
    const o = opts();
    r.dataset.lv = c.removed ? 'off' : q.level;
    r.classList.toggle('st-sel', c.n === S.sel);
    const [nEl, tEl, enEl, svEl, qaEl] = r.children;
    nEl.textContent = c.n;
    tEl.replaceChildren(fmtClock(c.start), document.createElement('br'), Object.assign(document.createElement('span'), { textContent: ((c.end - c.start) / 1000).toFixed(1) + ' s' }));
    enEl.classList.toggle('st-gone', c.removed);
    enEl.classList.toggle('st-ital', !!(c.ital && !c.removed));
    renderRich(enEl, c.removed ? c.raw : c.en);

    if (S.editing !== c.n) {
      svEl.replaceChildren();
      const box = document.createElement('div');
      box.className = 'st-sv-text';
      if (c.removed) { box.classList.add('st-muted'); box.textContent = 'Sound description, left out'; }
      else {
        box.tabIndex = 0;
        box.setAttribute('role', 'button');
        box.setAttribute('aria-label', `Edit the Swedish for subtitle ${c.n}`);
        if (c.sv == null) { box.classList.add('st-muted'); box.textContent = c.err ? 'Not translated. Press Resume to try again, or type it here.' : 'Not translated yet'; }
        else if (!c.sv) { box.classList.add('st-muted'); box.textContent = 'Left out (only fillers)'; }
        else { renderRich(box, c.sv); box.classList.toggle('st-ital', !!c.ital); }
      }
      svEl.appendChild(box);
      if (!c.removed && (c.why || c.prev != null)) {
        const note = document.createElement('div');
        note.className = 'st-note';
        if (c.why) note.appendChild(document.createTextNode(c.why + ' '));
        if (c.prev != null) {
          const u = document.createElement('button');
          u.type = 'button'; u.className = 'st-link'; u.dataset.onClick = 'st:undo'; u.textContent = 'Undo';
          u.title = 'Go back to: ' + (c.prev || '(empty)');
          note.appendChild(u);
        }
        svEl.appendChild(note);
      }
    }

    qaEl.replaceChildren();
    if (c.removed) {
      qaEl.appendChild(chip('SDH', '', 'Sound description or speaker label'));
      const k = document.createElement('button');
      k.type = 'button'; k.className = 'st-btn st-btn-sm st-qa-end'; k.dataset.onClick = 'st:keep'; k.textContent = 'Keep';
      k.title = 'Translate this subtitle instead of leaving it out';
      qaEl.appendChild(k);
      return;
    }
    if (c.sv) {
      const lv = q.issues.find(x => x.code === 'cps');
      qaEl.appendChild(chip(q.cps.toFixed(1) + ' cps', lv ? lv.lv : 'ok', 'Characters per second'));
      qaEl.appendChild(chip(q.lens.join(' · '), q.lens.some(l => l > o.maxLen) || q.lens.length > 2 ? 'bad' : '', `Characters per line (limit ${o.maxLen})`));
      if (q.ext > 0) qaEl.appendChild(chip('+' + Math.max(0.1, Math.ceil(q.ext / 100) / 10).toFixed(1) + ' s', '', 'Stays on screen a little longer, into the pause after it'));
      if (c.by === 'phrasebook') qaEl.appendChild(chip('phrase', '', 'Standard subtitle wording from the built-in phrasebook'));
    }
    for (const x of q.issues) {
      if (x.code === 'cps' && x.lv === 'warn') continue;
      const d = document.createElement('div');
      d.className = 'st-issue' + (x.lv === 'warn' ? ' st-warn' : '');
      d.textContent = x.msg;
      qaEl.appendChild(d);
    }
  }
  function rowVisible(c) {
    const q = S.qa[c.n - 1];
    if (S.filter === 'attn' && !(q && (q.level === 'warn' || q.level === 'bad'))) return false;
    if (S.filter === 'edited' && c.by !== 'you') return false;
    if (S.filter === 'todo' && !(c.sv == null && !c.removed && c.en)) return false;
    if (S.q && !((c.en + '\n' + (c.sv || '')).toLowerCase().includes(S.q))) return false;
    return true;
  }
  function applyFilter() {
    let shown = 0;
    for (const c of S.p.cues) { const r = S.rows.get(c.n); if (!r) continue; const v = rowVisible(c); r.hidden = !v; if (v) shown++; }
    $('#st-list-empty').hidden = shown > 0;
    $('#st-replace').hidden = !S.q;
    updateCounts();
  }
  function updateCounts() {
    let attn = 0, edited = 0, todo = 0, all = 0;
    for (const c of S.p.cues) {
      const q = S.qa[c.n - 1];
      if (!c.removed) all++;
      if (q && (q.level === 'warn' || q.level === 'bad')) attn++;
      if (c.by === 'you') edited++;
      if (c.sv == null && !c.removed && c.en) todo++;
    }
    $('#st-c-all').textContent = all; $('#st-c-attn').textContent = attn; $('#st-c-edit').textContent = edited; $('#st-c-todo').textContent = todo;
    for (const b of document.querySelectorAll('.st-seg button')) b.setAttribute('aria-pressed', String(b.dataset.f === S.filter));
  }

  // While a run fills the list, rows are redrawn once a frame rather than once a sentence.
  function touch(n) {
    if (n) S.dirty.add(n);
    if (!S.frame) S.frame = (document.hidden ? (f => setTimeout(f, 50)) : requestAnimationFrame)(flush);
  }
  function flush() {
    S.frame = 0;
    for (const n of S.dirty) { const r = S.rows.get(n); if (r) { fillRow(r, S.p.cues[n - 1]); r.hidden = !rowVisible(S.p.cues[n - 1]); } }
    const hadSel = S.dirty.has(S.sel);
    S.dirty.clear();
    updateCounts();
    renderRail();
    renderSave();
    drawTimeline(true);
    if (hadSel && !S.play) renderStage();
  }

  /* ---------- the preview screen ---------- */
  function renderStage() {
    const c = S.p.cues[S.sel - 1];
    if (!c) return;
    const q = S.qa[c.n - 1] || {};
    const o = opts();
    showOnScreen(c, c.start);
    $('#st-tc').textContent = fmtSrtTime(c.start);
    renderRich($('#st-en-line'), c.removed ? c.raw : c.en);
    const meta = $('#st-meta');
    meta.replaceChildren(chip('#' + c.n, ''), chip(((c.end - c.start) / 1000).toFixed(1) + ' s' + (q.ext ? ' +' + (q.ext / 1000).toFixed(1) : ''), ''));
    if (c.sv) {
      const lv = (q.issues || []).find(x => x.code === 'cps');
      meta.appendChild(chip(q.cps.toFixed(1) + ' cps', lv ? lv.lv : 'ok', 'Characters per second'));
      meta.appendChild(chip(q.lens.join(' · ') + ' / ' + o.maxLen, q.lens.some(l => l > o.maxLen) || q.lens.length > 2 ? 'bad' : '', 'Characters per line'));
    }
    drawTimeline(false);
  }
  function showOnScreen(c, t) {
    const sub = $('#st-sub'), empty = $('#st-scr-empty');
    const text = c && !c.removed && c.sv ? c.sv : '';
    renderRich(sub, text);
    sub.classList.toggle('st-ital', !!(c && c.ital));
    sub.classList.toggle('st-sub-top', !!(c && /\\an?8/.test(c.pos)));
    if (!S.play && c && !text) {
      empty.hidden = false;
      empty.textContent = c.removed ? 'Sound description, left out' : c.sv == null ? 'Not translated yet' : 'Left out (only fillers)';
    } else empty.hidden = true;
    $('#st-scr-tc').textContent = fmtSrtTime(t);
  }

  // The timeline: every subtitle as a block in its check's colour, drawn once
  // per change on a canvas of its own, with the selection or the playhead on top.
  let tlStatic = null;
  function tlColors() {
    const cs = getComputedStyle($('#st')), v = k => cs.getPropertyValue(k).trim();
    return { ok: v('--st-ok-fill'), warn: v('--st-warn-fill'), bad: v('--st-bad-fill'), todo: v('--st-todo-fill'), off: v('--border-color'), bg: v('--bg-surface'), mark: v('--color-kvot-bright'), ink: v('--text-primary') };
  }
  function totalMs() { return Math.max(1000, ...S.p.cues.map(c => c.end)) + 500; }
  function drawTimeline(rebuild, playT) {
    const cv = $('#st-timeline');
    const w = cv.clientWidth, h = cv.clientHeight;
    if (!w || !h) return;
    const dpr = window.devicePixelRatio || 1;
    if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); rebuild = true; }
    const col = tlColors(), T = totalMs();
    if (rebuild || !tlStatic) {
      tlStatic = document.createElement('canvas');
      tlStatic.width = cv.width; tlStatic.height = cv.height;
      const g = tlStatic.getContext('2d');
      g.scale(dpr, dpr);
      g.fillStyle = col.bg; g.fillRect(0, 0, w, h);
      for (const c of S.p.cues) {
        const q = S.qa[c.n - 1];
        const lv = c.removed ? 'off' : q ? q.level : 'todo';
        const x = c.start / T * w, x2 = Math.max(x + 1, c.end / T * w);
        g.fillStyle = col[lv] || col.todo;
        g.fillRect(x, 9, x2 - x, h - 18);
      }
    }
    const g = cv.getContext('2d');
    g.setTransform(1, 0, 0, 1, 0, 0);
    g.drawImage(tlStatic, 0, 0);
    g.scale(dpr, dpr);
    const c = S.p.cues[S.sel - 1];
    if (c && playT == null) {
      const x = c.start / T * w, x2 = Math.max(x + 3, c.end / T * w);
      g.fillStyle = col.mark; g.fillRect(x - 1, 2, x2 - x + 2, 4); g.fillRect(x - 1, h - 6, x2 - x + 2, 4);
    }
    if (playT != null) { const x = playT / T * w; g.fillStyle = col.ink; g.fillRect(x - 1, 1, 2, h - 2); }
  }

  // Playback in real time, to feel the reading speed.
  function cueAt(t) {
    const cs = S.p.cues;
    let lo = 0, hi = cs.length - 1, k = -1;
    while (lo <= hi) { const m = (lo + hi) >> 1; if (cs[m].start <= t) { k = m; lo = m + 1; } else hi = m - 1; }
    for (let j = k; j >= 0 && j > k - 4; j--) { const c = cs[j], q = S.qa[j]; const end = (S.set.extend && q && q.end) || c.end; if (!c.removed && t >= c.start && t < end) return c; }
    return null;
  }
  function togglePlay() { if (S.play) stopPlay(); else startPlay(); }
  function startPlay() {
    const c = S.p.cues[S.sel - 1];
    S.play = { t0: performance.now(), base: c ? c.start : 0, last: null };
    setPlayIcon(true);
    requestAnimationFrame(tick);
  }
  function stopPlay() {
    if (!S.play) return;
    const last = S.play.last;
    S.play = null;
    setPlayIcon(false);
    if (last) select(last.n, true); else renderStage();
  }
  function tick(now) {
    if (!S.play) return;
    const t = S.play.base + (now - S.play.t0);
    const c = cueAt(t);
    if (c) S.play.last = c;
    showOnScreen(c, t);
    drawTimeline(false, t);
    if (t > totalMs()) { stopPlay(); return; }
    requestAnimationFrame(tick);
  }
  function setPlayIcon(playing) {
    $('#st-play-icon').innerHTML = playing ? '<path d="M4 2.5h3v11H4zM9 2.5h3v11H9z"/>' : '<path d="M4 2.5v11L13 8z"/>';
    $('#st-play').setAttribute('aria-label', playing ? 'Pause' : 'Play');
  }
  function select(n, scroll) {
    if (!S.p.cues[n - 1]) return;
    const old = S.rows.get(S.sel);
    if (old) old.classList.remove('st-sel');
    S.sel = n;
    const r = S.rows.get(n);
    if (r) { r.classList.add('st-sel'); if (scroll && !r.hidden) r.scrollIntoView({ block: 'nearest' }); }
    if (!S.play) renderStage();
  }
  function step(dir) {
    const cs = S.p.cues;
    for (let n = S.sel + dir; n >= 1 && n <= cs.length; n += dir) { const r = S.rows.get(n); if (!cs[n - 1].removed && !(r && r.hidden)) { select(n, true); return; } }
  }

  /* ---------- editing ---------- */
  function startEdit(n) {
    if (S.editing && S.editing !== n) commitEdit();
    const c = S.p.cues[n - 1];
    if (!c || c.removed) return;
    stopPlay();
    S.editing = n;
    select(n);
    const cell = S.rows.get(n).children[3];
    const ta = document.createElement('textarea');
    ta.className = 'st-sv-ta'; ta.lang = 'sv'; ta.spellcheck = true;
    ta.value = c.sv || '';
    ta.rows = Math.max(2, (c.sv || '').split('\n').length + 1);
    ta.setAttribute('aria-label', `Swedish for subtitle ${n}`);
    const meter = document.createElement('div');
    meter.className = 'st-meter';
    const help = document.createElement('span');
    help.textContent = 'Enter for a new line, Ctrl+Enter or click outside to save, Esc to cancel';
    const upd = () => {
      const o = opts(), q = computeQA({ ...c, sv: ta.value.replace(/\r/g, '') }, nextActive(n), o);
      meter.replaceChildren(chip(q.cps ? q.cps.toFixed(1) + ' cps' : '0 cps', q.cps > o.cps + 3 ? 'bad' : q.cps > o.cps ? 'warn' : 'ok'), chip(q.lens.join(' · ') || '0', q.lens.some(l => l > o.maxLen) || q.lens.length > 2 ? 'bad' : ''), help);
    };
    ta.addEventListener('input', upd);
    ta.addEventListener('keydown', e => {
      if (e.key === 'Escape') { e.preventDefault(); cancelEdit(); }
      else if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); commitEdit(); }
    });
    ta.addEventListener('blur', () => setTimeout(() => { if (S.editing === n && document.activeElement !== ta) commitEdit(); }, 120));
    cell.replaceChildren(ta, meter);
    upd();
    ta.focus();
    ta.setSelectionRange(ta.value.length, ta.value.length);
  }
  function commitEdit() {
    const n = S.editing;
    if (!n) return;
    const c = S.p.cues[n - 1], ta = S.rows.get(n).querySelector('textarea');
    S.editing = 0;
    if (ta) {
      const v = ta.value.replace(/\r/g, '').split('\n').map(l => l.trim()).filter(Boolean).join('\n');
      if (v !== (c.sv || '') && !(c.sv == null && !v)) {
        c.prev = c.sv == null ? null : c.sv;
        c.sv = v; c.by = 'you'; c.why = ''; c.err = '';
        qaOne(n);
        if (n > 1) qaOne(n - 1);
        scheduleSave();
      }
    }
    touch(n);
  }
  function cancelEdit() { const n = S.editing; S.editing = 0; touch(n); }
  function undo(n) {
    const c = S.p.cues[n - 1];
    if (c.prev == null) return;
    c.sv = c.prev; c.prev = null; c.why = ''; c.by = 'you';
    qaOne(n); touch(n); scheduleSave();
  }
  function keep(n) {
    const c = S.p.cues[n - 1];
    c.kept = true; c.removed = false; c.en = c.raw; c.sv = null;
    if (S.p.phase === 'done') S.p.phase = 'translating';
    qaOne(n); touch(n); scheduleSave(); renderRail();
  }
  function replaceAll() {
    const find = $('#st-q').value, rep = $('#st-rep').value;
    if (!find) return;
    const re = new RegExp(find.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi');
    let count = 0;
    for (const c of S.p.cues) {
      if (!c.sv || !rowVisible(c)) continue;
      const v = c.sv.replace(re, () => { count++; return rep; });
      if (v !== c.sv) { c.prev = c.sv; c.sv = v; c.by = 'you'; c.why = ''; qaOne(c.n); touch(c.n); }
    }
    setAlert(count ? `Replaced ${count} time${count === 1 ? '' : 's'} in the Swedish. Each changed subtitle has an Undo.` : `"${find}" isn’t in the Swedish text.`, count ? 'ok' : 'info');
    scheduleSave();
  }

  /* ---------- a run ---------- */
  function stopJob() { if (!S.job.running) return; S.job.stop = true; S.job.note = 'Stopping after the current sentences…'; renderRail(); }
  async function run() {
    const p = S.p;
    if (!p || S.job.running) return;
    if (S.editing) commitEdit();
    stopPlay();
    const engine = S.set.engine;
    const J = S.job = { running: true, stop: false, done: 0, total: 0, note: 'Getting ready…', t0: performance.now() };
    setAlert('');
    renderRail();
    try {
      if (engine === 'chrome') {
        if (!hasTranslator()) throw { code: 'chrome-missing' };
        if (S.chrome.state === 'unavailable' || S.chrome.state === 'timeout') throw { code: 'chrome-unavailable' };
        await chromeTranslator();
      } else await opusTranslator();
      const translate = engine === 'chrome' ? translateChrome : translateOpus;

      const pend = new Set(pendingIds());
      const units = buildUnits(p.cues, opts()).filter(u => u.parts.some(x => pend.has(x.n)));
      p.stats = { units: units.length };
      p.phase = 'translating';
      J.total = units.length;
      const todo = [];
      for (const u of units) {
        const pb = phrasebook(u.text);
        if (pb) { applyUnit(u, pb, 'phrasebook'); J.done++; }
        else if (!u.text) { applyUnit(u, '', 'filler'); J.done++; }
        else todo.push(u);
      }
      for (const chunk of chunkUnits(todo, engine === 'chrome' ? 12 : 4, 1500)) {
        if (J.stop) throw { code: 'cancelled' };
        const lastPart = chunk[chunk.length - 1].parts;
        J.note = `Translating subtitles ${chunk[0].parts[0].n}–${lastPart[lastPart.length - 1].n}`;
        renderRail();
        const out = await translate(chunk.map(u => u.text));
        chunk.forEach((u, i) => {
          const sv = out[i];
          if (sv == null || !String(sv).trim()) { for (const x of u.parts) { p.cues[x.n - 1].err = 'empty'; qaOne(x.n); touch(x.n); } }
          else applyUnit(u, sv, 'google');
          J.done++;
        });
        scheduleSave();
        await new Promise(r => setTimeout(r, 0));
      }
      const left = pendingIds().length;
      if (!left) {
        p.phase = 'done';
        const attn = S.qa.filter(q => q.level === 'warn' || q.level === 'bad').length;
        setAlert(attn ? `Done. ${attn} subtitle${attn === 1 ? ' needs' : 's need'} a look, mostly to shorten. Choose Needs a look above the list.` : 'Done. Every subtitle is within the limits.', 'ok');
      } else setAlert(`${left} subtitle${left === 1 ? ' was' : 's were'} not translated. Press Resume to try again.`, 'bad');
    } catch (e) {
      if ((e && e.code === 'cancelled') || J.stop) setAlert('Stopped. Everything translated so far is kept. Press Resume to continue.', 'info');
      else setAlert(engineError(e), 'bad');
    } finally {
      J.running = false;
      saveNow();
      // The whole list now, not on the next frame: a tab in the background may not get one for a while.
      if (S.frame) { cancelAnimationFrame(S.frame); clearTimeout(S.frame); }
      for (const c of S.p.cues) S.dirty.add(c.n);
      flush();
      renderAll();
    }
  }

  /* ---------- the panels ---------- */
  function setAlert(msg, kind) {
    const a = $('#st-alert');
    a.hidden = !msg;
    a.textContent = msg || '';
    a.dataset.kind = kind || 'bad';
  }
  function renderEngines() {
    const st = S.chrome.state, pill = $('#st-chrome-state');
    const map = {
      checking: ['Checking…', ''], available: ['Ready', 'ok'], downloadable: ['Ready to download', 'warn'], downloading: ['Downloading', 'warn'],
      unavailable: ['Not for Swedish here', 'bad'], missing: ['Not in this browser', 'bad'], timeout: ['Not responding', 'bad'],
    };
    const [label, s] = map[st] || [st, ''];
    pill.textContent = label; pill.dataset.s = s;
    $('#st-chrome-note').textContent = st === 'downloadable' || st === 'downloading' ? 'The first translation starts a one-time download of the language model. Keep the tab open until it finishes.'
      : st === 'missing' ? 'This browser has no built-in translator. Open the page in Chrome or Edge on a computer, or use the open model.'
      : st === 'unavailable' ? 'Chrome says it can’t translate English to Swedish on this computer. Use the open model.'
      : st === 'timeout' ? 'The built-in translator didn’t answer. This happens in browsers based on Chrome that don’t include Google’s models. Use the open model.'
      : '';
    $('#st-eng-chrome').checked = S.set.engine === 'chrome';
    $('#st-eng-opus').checked = S.set.engine === 'opus';
    const o = S.opus, op = $('#st-opus-state');
    op.textContent = o.state === 'ready' ? 'Ready' : o.state === 'downloading' ? `Downloading ${Math.round(o.progress * 100)}%` : 'Not downloaded';
    op.dataset.s = o.state === 'ready' ? 'ok' : o.state === 'downloading' ? 'warn' : '';
    $('#st-opus-note').textContent = o.state === 'downloading' ? 'Keep the tab open until the download finishes.' : '';
  }
  function renderRail() {
    const p = S.p, J = S.job, o = opts();
    const act = active().length, pend = pendingIds().length, translated = act - pend;
    const isSample = p.kind === 'sample';
    const pill = $('#st-state');
    let st = 'idle', label = 'Ready';
    if (isSample) label = 'Example';
    else if (J.running) { st = 'run'; label = 'Translating'; }
    else if (p.phase === 'done' && !pend) { st = 'done'; label = 'Done'; }
    else if (translated > 0) { st = 'paused'; label = 'Paused'; }
    pill.dataset.s = st; pill.textContent = label;

    const left = p.cues.length - act;
    $('#st-intro').textContent = isSample
      ? 'This sample scene shows what the page does with Google’s real output. Click a subtitle to see what changed. Open your own English .srt file to translate a film or an episode.'
      : `${act} subtitles${left ? `, plus ${left} sound description${left === 1 ? '' : 's'} left out` : ''}.`;

    const fills = p.cues.filter(c => /Fillers left out|Only fillers/.test(c.why || '')).length;
    const pbs = p.cues.filter(c => c.by === 'phrasebook').length;
    const fixes = p.cues.filter(c => /is "|converted|Filler removed|allihop|Herregud/.test(c.why || '')).length;
    const attn = S.qa.filter(q => q.level === 'warn' || q.level === 'bad').length;
    const done = p.phase === 'done' && !pend;
    const state = {
      prep: translated || J.running ? 'done' : 'todo',
      translate: J.running ? 'run' : act && !pend ? 'done' : 'todo',
      clean: done ? 'done' : 'todo',
      check: done ? 'done' : 'todo',
    };
    const cnt = {
      prep: p.stats ? `${p.stats.units} sentences` : '',
      translate: act ? `${translated}/${act}` : '',
      clean: translated ? `${pbs} phrase${pbs === 1 ? '' : 's'} · ${fixes + fills} fix${fixes + fills === 1 ? '' : 'es'}` : '',
      check: done ? `${attn} to look at` : '',
    };
    for (const li of document.querySelectorAll('#st-steps li')) { li.dataset.state = state[li.dataset.step]; li.querySelector('.st-cnt').textContent = cnt[li.dataset.step]; }
    $('#st-check-desc').textContent = `Two lines, ${o.maxLen} characters per line, ${o.cps} characters per second. Subtitles over the limit are marked for you to shorten.`;
    const google = S.set.engine === 'chrome';
    $('#st-step-tr-h').textContent = google ? 'Translate with Google' : 'Translate with the open model';
    $('#st-step-tr-d').textContent = google ? 'Whole sentences go to Google, a dozen at a time, so word order and context come out right.' : 'Whole sentences go to the model instead of fragments, so word order comes out right.';

    $('#st-progress').hidden = !J.running;
    if (J.running) {
      $('#st-bar-fill').style.width = Math.max(3, Math.round((J.total ? J.done / J.total : 0) * 100)) + '%';
      $('#st-ptext').textContent = (J.note || '') + (J.total ? ` · ${J.done} of ${J.total} sentences` : '');
    }
    const go = $('#st-go');
    $('#st-stop').hidden = !J.running;
    go.hidden = J.running;
    go.disabled = false;
    if (isSample) go.textContent = 'Translate the sample live';
    else if (!translated) go.textContent = 'Translate';
    else if (pend) go.textContent = 'Resume';
    else { go.textContent = 'All translated'; go.disabled = true; }

    const est = $('#st-estimate');
    if (J.running || go.disabled) est.textContent = '';
    else if (S.set.engine === 'chrome') est.textContent = `Free, and runs on this computer.${S.chrome.state === 'downloadable' ? ' The first time, Chrome downloads Google’s language model.' : ''}`;
    else est.textContent = `Free, and runs on this computer.${S.opus.state === 'ready' ? '' : ' The first time, the page downloads the open model (about 105 MB).'} A film takes several minutes.`;
  }
  function renderFileChip() {
    const p = S.p, dur = p.cues.length ? p.cues[p.cues.length - 1].end : 0;
    $('#st-file-name').textContent = p.kind === 'file' ? p.name : 'Sample scene';
    $('#st-file-meta').textContent = `· ${p.cues.length} subtitles · ${fmtClock(dur)}`;
    $('#st-close').hidden = p.kind === 'sample';
  }
  function renderSettings() {
    const s = S.set, f = $('#st-settings');
    f.elements.audience.value = s.audience; f.elements.maxLen.value = opts().maxLen; f.elements.dash.value = s.dash;
    f.elements.sdh.value = s.sdh; f.elements.fillers.checked = !!s.fillers; f.elements.extend.checked = !!s.extend;
    $('#st-encoding').value = s.encoding;
    const started = S.p.kind !== 'sample' && S.p.cues.some(c => c.sv != null);
    f.elements.sdh.disabled = started || S.p.kind === 'sample';
    $('#st-sdh-note').textContent = S.p.kind === 'sample' ? 'Applies to your own files.' : started ? 'Set this before translating. Use Keep on a single subtitle to bring it back.' : '';
    $('#st-guide-lbl').textContent = `${opts().maxLen} characters`;
  }
  function renderSave() {
    const todo = pendingIds().length;
    $('#st-save-name').textContent = S.p.kind === 'file' ? outName(S.p.name) : 'sample.sv.srt';
    $('#st-save-info').textContent = (todo ? `${todo} subtitle${todo === 1 ? ' is' : 's are'} not translated yet and will be saved in English. ` : '') +
      'Put the .srt next to the video with the same name, and players like VLC and Plex pick it up as Swedish.';
  }
  function renderAll() { renderFileChip(); renderSettings(); renderEngines(); renderRail(); renderSave(); renderStage(); updateCounts(); }

  /* ---------- saving the .srt ---------- */
  const srtText = () => buildSRT(S.p.cues, S.qa, opts());
  const saveFileName = () => (S.p.kind === 'file' ? outName(S.p.name) : 'sample.sv.srt');
  function saveSrt() {
    if (S.editing) commitEdit();
    const name = saveFileName();
    const { bytes, bad } = encodeText(srtText().replace(/\n/g, '\r\n'), S.set.encoding);
    const url = URL.createObjectURL(new Blob([bytes], { type: 'application/x-subrip' }));
    const a = document.createElement('a');
    a.href = url; a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 4000);
    const sa = $('#st-save-alert');
    sa.hidden = false; sa.dataset.kind = 'ok';
    sa.textContent = `Saved ${name} to your downloads.` + (bad ? ` ${bad} character${bad === 1 ? '' : 's'} had no Windows-1252 version and became "?".` : '');
  }
  function copySrt() {
    if (S.editing) commitEdit();
    const text = srtText(), sa = $('#st-save-alert'), box = $('#st-copy-box'), name = saveFileName();
    const fallback = () => { box.hidden = false; box.value = text; box.focus(); box.select(); sa.hidden = false; sa.dataset.kind = 'info'; sa.textContent = 'Copy the selected text below, paste it into a plain text file and save it as ' + name + '.'; };
    try { navigator.clipboard.writeText(text).then(() => { box.hidden = true; sa.hidden = false; sa.dataset.kind = 'ok'; sa.textContent = 'Copied. Paste it into a plain text file and save it as ' + name + '.'; }, fallback); }
    catch { fallback(); }
  }

  /* ---------- this browser's memory of the work ---------- */
  let saveTimer = 0;
  function scheduleSave() { clearTimeout(saveTimer); saveTimer = setTimeout(saveNow, 700); }
  function saveNow() {
    clearTimeout(saveTimer);
    try {
      localStorage.setItem(KEY + ':settings', JSON.stringify(S.set));
      if (S.p && S.p.kind === 'file') localStorage.setItem(KEY + ':project', JSON.stringify({ p: S.p, sel: S.sel }));
    } catch { /* storage full or blocked: the work goes on without it */ }
  }
  function loadSaved() {
    try { const s = JSON.parse(localStorage.getItem(KEY + ':settings') || 'null'); if (s && typeof s === 'object') S.set = { ...DEFAULTS, ...s }; } catch { /* ignore */ }
    if (S.set.engine !== 'chrome' && S.set.engine !== 'opus') S.set.engine = 'chrome';
    try {
      const d = JSON.parse(localStorage.getItem(KEY + ':project') || 'null');
      if (d && d.p && Array.isArray(d.p.cues) && d.p.cues.length) return d;
    } catch { /* ignore */ }
    return null;
  }
  function forgetProject() { try { localStorage.removeItem(KEY + ':project'); } catch { /* ignore */ } }

  /* ---------- opening and closing files ---------- */
  let pendingFile = null;
  function confirmBar(text, yes) {
    $('#st-confirm-text').textContent = text;
    $('#st-confirm-yes').textContent = yes;
    $('#st-confirm').hidden = false;
  }
  async function openFile(file) {
    if (!file) return;
    if (S.job.running) { setAlert('Stop the current translation before opening another file.', 'bad'); return; }
    const p = S.p;
    if (p.kind === 'file' && p.cues.some(c => c.sv != null)) {
      pendingFile = file;
      confirmBar(`Open ${file.name}? The translation of ${p.name} in this browser will be replaced. Save it first if you want to keep it.`, 'Open');
      return;
    }
    await loadFile(file);
  }
  async function loadFile(file) {
    try {
      if (file.size > 20 * 1024 * 1024) { setAlert('That file is larger than 20 MB, which is far more than a subtitle file. Pick the .srt file.', 'bad'); return; }
      const parsed = parseSubtitles(decodeBytes(new Uint8Array(await file.arrayBuffer())));
      if (!parsed.length) { setAlert(`No subtitles found in ${file.name}. Pick an English .srt or .vtt file.`, 'bad'); return; }
      const p = makeProject(file.name, parsed, 'file', S.set.sdh);
      p.stats = { units: buildUnits(p.cues, opts()).length };
      setAlert('');
      $('#st-save-alert').hidden = true; $('#st-copy-box').hidden = true;
      setProject(p);
      saveNow();
      $('#st-content').scrollTo({ top: 0, behavior: 'smooth' });
    } catch (e) {
      setAlert(`Couldn’t read ${file.name}. Pick an English .srt or .vtt file.`, 'bad');
    }
  }
  function closeProject() {
    if (S.job.running) return;
    pendingFile = null;
    if (S.p.kind === 'file' && S.p.cues.some(c => c.sv != null)) {
      confirmBar(`Close ${S.p.name}? Its translation is removed from this browser. Save it first if you want to keep it.`, 'Close');
      return;
    }
    doClose();
  }
  function doClose() { forgetProject(); setAlert(''); setProject(makeSampleProject()); }

  /* ---------- the controls ---------- */
  const rowOf = el => +el.closest('.st-row').dataset.n;
  const requalify = () => { qaAll(); for (const c of S.p.cues) touch(c.n); renderStage(); };
  const repolish = () => { const o = opts(); for (const c of S.p.cues) if (c.sv) c.sv = polish(c.sv, o); requalify(); };
  const SETTING_EFFECTS = {
    audience: requalify,
    extend: requalify,
    maxLen: repolish,
    dash: repolish,
    sdh: () => {
      if (S.p.kind === 'sample' || S.p.cues.some(c => c.sv != null)) return;
      applySDH(S.p.cues, S.set.sdh);
      S.p.stats = { units: buildUnits(S.p.cues, opts()).length };
      qaAll(); buildList(); renderStage();
    },
    fillers: () => { if (S.p.kind === 'file') S.p.stats = { units: buildUnits(S.p.cues, opts()).length }; },
  };

  function bind() {
    registerActions({
      'st:open': () => $('#st-file-input').click(),
      'st:close': () => closeProject(),
      'st:confirm-no': () => { pendingFile = null; $('#st-confirm').hidden = true; },
      'st:confirm-yes': async () => {
        $('#st-confirm').hidden = true;
        if (pendingFile) { const f = pendingFile; pendingFile = null; await loadFile(f); } else doClose();
      },
      'st:go': () => {
        if (S.p.kind === 'sample') setProject(makeProject('Sample scene', parseSubtitles(SAMPLE_SRT), 'sample-live', 'remove'));
        run();
      },
      'st:stop': () => stopJob(),
      'st:engine': (e, el) => { S.set.engine = el.value; S.set.engineChosen = true; scheduleSave(); renderEngines(); renderRail(); },
      'st:setting': (e, el) => {
        S.set[el.name] = el.type === 'checkbox' ? el.checked : el.name === 'maxLen' ? Math.min(60, Math.max(30, parseInt(el.value, 10) || 42)) : el.value;
        scheduleSave();
        if (SETTING_EFFECTS[el.name]) SETTING_EFFECTS[el.name]();
        renderSettings(); renderRail(); renderSave();
      },
      'st:prev': () => { stopPlay(); step(-1); },
      'st:next': () => { stopPlay(); step(1); },
      'st:play': () => togglePlay(),
      'st:filter': (e, el) => { S.filter = el.dataset.f; applyFilter(); },
      'st:search': (e, el) => { S.q = el.value.trim().toLowerCase(); applyFilter(); },
      'st:replace': () => replaceAll(),
      'st:undo': (e, el) => undo(rowOf(el)),
      'st:keep': (e, el) => keep(rowOf(el)),
      'st:save': () => saveSrt(),
      'st:copy': () => copySrt(),
    });

    $('#st-file-input').addEventListener('change', e => { const f = e.target.files && e.target.files[0]; e.target.value = ''; openFile(f); });
    // Enter in "Characters per line" would otherwise submit the form and reload the page.
    $('#st-settings').addEventListener('submit', e => e.preventDefault());
    $('#st-timeline').addEventListener('click', e => {
      const rect = e.currentTarget.getBoundingClientRect(), t = (e.clientX - rect.left) / rect.width * totalMs();
      let best = null, bd = Infinity;
      for (const c of S.p.cues) { const d = t < c.start ? c.start - t : t > c.end ? t - c.end : 0; if (d < bd) { bd = d; best = c; } }
      if (best) { stopPlay(); select(best.n, true); }
    });
    // A row is chosen by a click anywhere on it, and its Swedish edited by a click on the Swedish.
    $('#st-list').addEventListener('click', e => {
      const row = e.target.closest('.st-row');
      if (!row || e.target.closest('[data-on-click]') || e.target.closest('textarea')) return;
      const n = +row.dataset.n;
      if (e.target.closest('.st-sv-text') && !S.p.cues[n - 1].removed) { startEdit(n); return; }
      if (S.editing && S.editing !== n) commitEdit();
      select(n);
    });
    $('#st-list').addEventListener('keydown', e => {
      if (e.key === 'Enter' && e.target.classList.contains('st-sv-text')) { e.preventDefault(); startEdit(+e.target.closest('.st-row').dataset.n); }
    });
    document.addEventListener('keydown', e => {
      const t = e.target, tag = t && t.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || (t && t.isContentEditable) || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === 'j' || e.key === 'J') { e.preventDefault(); stopPlay(); step(1); }
      else if (e.key === 'k' || e.key === 'K') { e.preventDefault(); stopPlay(); step(-1); }
      else if (e.key === ' ' && tag !== 'BUTTON' && tag !== 'SUMMARY' && tag !== 'A' && !(t && t.classList && t.classList.contains('st-sv-text'))) { e.preventDefault(); togglePlay(); }
    });

    let depth = 0;
    const hasFiles = e => e.dataTransfer && Array.from(e.dataTransfer.types || []).includes('Files');
    window.addEventListener('dragenter', e => { if (!hasFiles(e)) return; e.preventDefault(); depth++; $('#st-drop').hidden = false; });
    window.addEventListener('dragover', e => { if (hasFiles(e)) e.preventDefault(); });
    window.addEventListener('dragleave', e => { if (!hasFiles(e)) return; depth = Math.max(0, depth - 1); if (!depth) $('#st-drop').hidden = true; });
    window.addEventListener('drop', e => { if (!hasFiles(e)) return; e.preventDefault(); depth = 0; $('#st-drop').hidden = true; openFile(e.dataTransfer.files && e.dataTransfer.files[0]); });

    new ResizeObserver(() => drawTimeline(true)).observe($('#st-timeline'));
    document.documentElement.addEventListener('kvot-theme-change', () => requestAnimationFrame(() => drawTimeline(true)));
    window.addEventListener('beforeunload', saveNow);
  }

  function init() {
    const saved = loadSaved();
    bind();
    setProject(saved && saved.p ? saved.p : makeSampleProject(), saved && saved.sel);
    checkChrome();
  }

  return { init };
})();
