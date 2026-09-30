/* ==========================================================================
   WINNETKAKORT - THE PAGE

   winnetkakort.html: choose piles, go through them a card at a time, and see
   the cards sorted into Kan and Öva mer. The arithmetic is in
   winnetkakort-sets.js; this file is the practice itself.

   The Winnetka routine, as the page runs it:

     - A round goes through the chosen cards once, in shuffled order.
     - A card answered right, within the time limit and without the hint,
       goes to Kan; anything else to Öva mer.
     - When the round is over, the Öva mer pile is offered as the next round,
       until it is empty.

   Progress is kept per fact and per person in localStorage, under
   'winnetkakort.v1'. That is the only state that outlives the page, and it
   never leaves the browser. A fact is "kan" after one quick right answer if
   it has never been missed, and after two in a row once it has.
   ========================================================================== */

const WK = (() => {
  'use strict';

  const S = WK_SETS;
  const $ = id => document.getElementById(id);
  const esc = kvotEscapeHtml;
  const reduceMotion = () => matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ── Storage ─────────────────────────────────────────────────────────── */

  const STORE_KEY = 'winnetkakort.v1';
  const DEFAULTS = Object.freeze({ mode: 'skriv', limit: 5, count: 20, form: 'vanlig', signs: 'punkt', pad: 'auto' });
  const CHOICES = Object.freeze({
    mode: ['skriv', 'vand'], limit: [3, 5, 8, 12, 0], count: [10, 20, 30, 0],
    form: ['vanlig', 'saknat', 'blandat'], signs: ['punkt', 'kryss'], pad: ['auto', 'pa', 'av'],
  });

  let store = null;
  let saveWarned = false;

  const newProfile = name => ({ name, facts: Object.create(null), best: Object.create(null) });

  function loadStore() {
    let raw = null;
    try {
      const text = localStorage.getItem(STORE_KEY);
      if (text) raw = JSON.parse(text);
    } catch (e) {
      ignoreFailure('winnetkakort: read progress', e);
    }
    return cleanStore(raw);
  }

  /*
    Storage is written by this page, but it can be edited by hand or left by
    an older version, so every field is checked on the way in. The maps are
    prototype-free: a fact key read from storage is only ever a map key.
  */
  function cleanStore(raw) {
    const out = { v: 1, current: null, profiles: Object.create(null), settings: { ...DEFAULTS } };
    if (raw && typeof raw === 'object') {
      if (raw.profiles && typeof raw.profiles === 'object') {
        for (const [id, p] of Object.entries(raw.profiles)) {
          if (!/^p\d{1,6}$/.test(id) || !p || typeof p !== 'object') continue;
          const name = typeof p.name === 'string' && p.name.trim() ? p.name.trim().slice(0, 30) : 'Jag';
          const profile = newProfile(name);
          if (p.facts && typeof p.facts === 'object') {
            for (const [key, st] of Object.entries(p.facts)) {
              if (!st || typeof st !== 'object' || !Number.isFinite(st.n) || st.n < 1) continue;
              profile.facts[key] = {
                n: Math.floor(st.n), w: Math.max(0, Math.floor(Number(st.w) || 0)), s: Math.max(0, Math.floor(Number(st.s) || 0)),
                t: Math.max(0, Number(st.t) || 0), d: typeof st.d === 'string' ? st.d.slice(0, 10) : '',
              };
            }
          }
          if (p.best && typeof p.best === 'object') {
            for (const [setId, ms] of Object.entries(p.best)) if (Number.isFinite(ms) && ms > 0) profile.best[setId] = ms;
          }
          out.profiles[id] = profile;
        }
      }
      if (raw.settings && typeof raw.settings === 'object') {
        for (const k of Object.keys(DEFAULTS)) if (CHOICES[k].includes(raw.settings[k])) out.settings[k] = raw.settings[k];
      }
      if (typeof raw.current === 'string' && out.profiles[raw.current]) out.current = raw.current;
    }
    if (!Object.keys(out.profiles).length) out.profiles.p1 = newProfile('Jag');
    if (!out.current) out.current = Object.keys(out.profiles)[0];
    return out;
  }

  function saveStore() {
    try {
      localStorage.setItem(STORE_KEY, JSON.stringify(store));
    } catch (e) {
      ignoreFailure('winnetkakort: save progress', e);
      if (!saveWarned) {
        saveWarned = true;
        notifyUser('Framstegen kan inte sparas i den här webbläsaren. De finns kvar tills du stänger sidan.');
      }
    }
  }

  const profile = () => store.profiles[store.current];
  const settings = () => store.settings;

  /* ── Progress per fact ───────────────────────────────────────────────── */

  function statusOf(key) {
    const st = profile().facts[key];
    if (!st) return 'none';
    if (st.s >= 2 || (st.s >= 1 && st.w === 0)) return 'kan';
    if (st.s === 1) return 'nara';
    return 'ova';
  }

  function record(key, kan, ms) {
    const facts = profile().facts;
    const st = facts[key] || (facts[key] = { n: 0, w: 0, s: 0, t: 0, d: '' });
    st.n += 1;
    if (kan) st.s += 1;
    else { st.s = 0; st.w += 1; }
    st.t = Math.round(ms);
    st.d = new Date().toISOString().slice(0, 10);
  }

  /* The virtual pile of everything that went to Öva mer last time. */
  const HARD = 'svara';
  function hardFacts() {
    return Object.keys(profile().facts)
      .filter(key => S.factByKey[key] && statusOf(key) === 'ova')
      .map(key => S.factByKey[key]);
  }
  const hardSet = () => ({ id: HARD, title: 'Mina svåra kort', color: 'accent', facts: hardFacts() });
  const setOf = id => (id === HARD ? hardSet() : S.setById[id]);

  /* ── Small helpers ───────────────────────────────────────────────────── */

  function shuffle(list) {
    for (let i = list.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [list[i], list[j]] = [list[j], list[i]];
    }
    return list;
  }

  function mmss(ms) {
    const s = Math.round(ms / 1000);
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
  }

  const seconds = ms => `${(ms / 1000).toFixed(1).replace('.', ',')} sekunder`;
  const pct = (n, of) => (of ? Math.round((1000 * n) / of) / 10 : 0);

  /* Hints are written with · and /; the × ÷ setting reaches them here. */
  function withSigns(text) {
    return settings().signs === 'kryss' ? text.replace(/ · /g, ' × ').replace(/ \/ /g, ' ÷ ') : text;
  }

  function padOn() {
    const pad = settings().pad;
    return pad === 'pa' || (pad === 'auto' && matchMedia('(pointer: coarse)').matches);
  }

  /* ── Drawing a card ──────────────────────────────────────────────────── */

  function tokenHtml(t, blank) {
    if (t === S.BLANK) return blank();
    if (typeof t === 'string') {
      if (t === '%') return '<span class="wk-pct">%</span>';
      if (t === '=') return '<span class="wk-sym">=</span>';
      return `<span class="wk-word">${esc(t)}</span>`;
    }
    if ('num' in t) {
      const s = esc(S.fmtPlain(t.num));
      return `<span class="wk-num${t.ans ? ' wk-ans' : ''}">${t.paren ? `(${s})` : s}</span>`;
    }
    if ('op' in t) return `<span class="wk-sym">${S.SIGNS[settings().signs][t.op]}</span>`;
    if ('frac' in t) {
      return `<span class="wk-frac" aria-label="${t.frac[0]}/${t.frac[1]}"><span>${t.frac[0]}</span><span>${t.frac[1]}</span></span>`;
    }
    if ('pow' in t) return `<span class="wk-num">${t.pow[0]}<sup>${t.pow[1]}</sup></span>`;
    if ('sqrt' in t) return `<span class="wk-sqrt"><span class="wk-sqrt-sign">√</span><span class="wk-sqrt-arg">${t.sqrt}</span></span>`;
    return '';
  }

  const eqHtml = (tokens, blank) => tokens.map(t => tokenHtml(t, blank)).join('');

  /** The tokens with the blank filled in: the back of the card. */
  const answered = q => q.tokens.map(t => (t === S.BLANK ? { num: q.answer, ans: true } : t));

  function inputHtml(fact) {
    const mode = padOn() ? 'none' : fact.neg ? 'text' : 'decimal';
    return `<input class="wk-blank" id="wk-input" type="text" inputmode="${mode}" autocomplete="off" autocorrect="off"
      autocapitalize="off" spellcheck="false" enterkeyhint="done" aria-label="Ditt svar"
      data-on-input="wk:typed" data-on-keydown="wk:answerKey">`;
  }

  function sizeInput(input) {
    input.style.width = `${Math.max(2.2, input.value.length + 1)}ch`;
  }

  /* ── Pictures for the hints ──────────────────────────────────────────── */

  function tenFramesSvg(pic) {
    const tones = pic.parts.flatMap(p => Array(p.n).fill(p.tone));
    const total = tones.length;
    const frames = Math.max(1, Math.ceil(total / 10));
    const cell = 26, gap = 16;
    const width = frames * 5 * cell + (frames - 1) * gap, height = 2 * cell;
    let out = '';
    for (let i = 0; i < frames * 10; i++) {
      const frame = Math.floor(i / 10), j = i % 10;
      const x = frame * (5 * cell + gap) + (j % 5) * cell, y = Math.floor(j / 5) * cell;
      out += `<rect class="wk-pic-cell" x="${x + 0.5}" y="${y + 0.5}" width="${cell - 1}" height="${cell - 1}"/>`;
      if (i < total) {
        const cx = x + cell / 2, cy = y + cell / 2;
        const crossed = i >= total - pic.crossed;
        out += `<circle class="wk-pic-${tones[i]}${crossed ? ' wk-pic-gone' : ''}" cx="${cx}" cy="${cy}" r="8.5"/>`;
        if (crossed) out += `<path class="wk-pic-x" d="M${cx - 7} ${cy - 7}L${cx + 7} ${cy + 7}M${cx + 7} ${cy - 7}L${cx - 7} ${cy + 7}"/>`;
      }
    }
    return `<svg class="wk-pic" viewBox="-1 -1 ${width + 2} ${height + 2}" width="${width + 2}" height="${height + 2}" role="img" aria-label="Tiorutor">${out}</svg>`;
  }

  function arraySvg(pic) {
    const step = 15, gap = 7;
    const at = i => i * step + Math.floor(i / 5) * gap + step / 2;
    const width = at(pic.cols - 1) + step / 2, height = at(pic.rows - 1) + step / 2;
    let out = '';
    for (let r = 0; r < pic.rows; r++) for (let c = 0; c < pic.cols; c++) {
      out += `<circle class="wk-pic-a" cx="${at(c)}" cy="${at(r)}" r="5"/>`;
    }
    return `<svg class="wk-pic" viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" role="img"
      aria-label="${pic.rows} rader med ${pic.cols} prickar">${out}</svg>`;
  }

  function lineSvg(pic) {
    const step = 22, pad = 14, width = 20 * step + 2 * pad, y = 22;
    const x = n => pad + (n + 10) * step;
    let out = `<path class="wk-pic-axis" d="M${pad - 8} ${y}H${width - pad + 8}"/>`;
    for (let n = -10; n <= 10; n++) {
      const major = n % 5 === 0;
      out += `<path class="wk-pic-axis" d="M${x(n)} ${y - (major ? 7 : 4)}V${y + (major ? 7 : 4)}"/>`;
      if (major && n !== pic.mark) out += `<text class="wk-pic-label" x="${x(n)}" y="${y + 22}">${esc(S.fmtPlain(n))}</text>`;
    }
    out += `<circle class="wk-pic-a" cx="${x(pic.mark)}" cy="${y}" r="7"/>`;
    out += `<text class="wk-pic-label wk-pic-mark" x="${x(pic.mark)}" y="${y + 22}">${esc(S.fmtPlain(pic.mark))}</text>`;
    return `<svg class="wk-pic" viewBox="0 0 ${width} 50" width="${width}" height="50" role="img" aria-label="Tallinje från −10 till 10">${out}</svg>`;
  }

  function picHtml(pic) {
    if (!pic) return '';
    if (pic.type === 'ten') return tenFramesSvg(pic);
    if (pic.type === 'array') return arraySvg(pic);
    if (pic.type === 'line') return lineSvg(pic);
    return '';
  }

  /* ── Views ───────────────────────────────────────────────────────────── */

  function showView(name) {
    for (const v of ['home', 'practice', 'summary']) $(`wk-${v}`).hidden = v !== name;
    $('wk-scroll').scrollTop = 0;
    if (name === 'home') renderHome();
  }

  /* ── The home view ───────────────────────────────────────────────────── */

  const selected = new Set();
  let gridName = 'plus';
  let gridPick = null;

  function example(set) {
    const f = set.facts[Math.floor(set.facts.length * 0.6)] || set.facts[0];
    if (!f) return '';
    return S.plainText(S.question(f, f.kind === 'op' ? f.form0 : 'text').tokens, settings().signs);
  }

  function tileHtml(set) {
    const n = set.facts.length;
    let kan = 0, nara = 0;
    for (const f of set.facts) {
      const st = statusOf(f.key);
      if (st === 'kan') kan++;
      else if (st === 'nara') nara++;
    }
    const best = profile().best[set.id];
    const meta = [`${n} kort`, kan ? `${kan} kan` : '', best ? `rekord ${mmss(best)}` : ''].filter(Boolean).join(' · ');
    return `<button type="button" class="wk-tile" data-set="${esc(set.id)}" aria-pressed="${selected.has(set.id)}" data-on-click="wk:toggle">
        <span class="wk-tile-band" aria-hidden="true"></span>
        <span class="wk-tile-title">${esc(set.title)}</span>
        <span class="wk-tile-eg">${esc(example(set))}</span>
        <span class="wk-meter" aria-hidden="true"><span class="wk-meter-kan" style="width:${pct(kan, n)}%"></span><span class="wk-meter-nara" style="width:${pct(nara, n)}%"></span></span>
        <span class="wk-tile-meta">${esc(meta)}</span>
        <span class="wk-tile-tick" aria-hidden="true"></span>
      </button>`;
  }

  function groupHtml(g) {
    return `<section class="wk-group" style="--wk-c: var(--wk-${g.color})" aria-labelledby="wk-g-${g.id}">
        <div class="wk-group-head"><h2 id="wk-g-${g.id}">${esc(g.title)}</h2>${g.grade ? `<span class="wk-grade">${esc(g.grade)}</span>` : ''}</div>
        <p class="wk-group-desc">${esc(g.desc)}</p>
        <div class="wk-tiles">${g.sets.map(tileHtml).join('')}</div>
      </section>`;
  }

  function renderGroups() {
    const hard = hardSet();
    if (!hard.facts.length) selected.delete(HARD);
    let html = '';
    if (hard.facts.length) {
      html += groupHtml({
        id: 'hard', title: 'Att öva på', color: 'accent', grade: '',
        desc: 'Korten som hamnade i Öva mer-högen senast, från alla högar.', sets: [hard],
      });
    }
    for (const g of S.GROUPS) html += groupHtml(g);
    $('wk-groups').innerHTML = html;
  }

  function selectedFacts(ids) {
    const seen = new Set();
    const out = [];
    for (const id of ids) {
      const set = setOf(id);
      if (!set) continue;
      for (const f of set.facts) if (!seen.has(f.key)) { seen.add(f.key); out.push(f); }
    }
    return out;
  }

  /* Tiles are drawn in pile order; the selection is listed the same way. */
  function selectedIds() {
    return [HARD, ...S.allSets.map(s => s.id)].filter(id => selected.has(id));
  }

  function renderSelection() {
    const ids = selectedIds();
    const facts = selectedFacts(ids);
    const count = settings().count;
    let text;
    if (!ids.length) text = 'Välj en eller flera högar att öva på.';
    else {
      const names = ids.map(id => setOf(id).title);
      const list = names.length <= 3 ? names.join(', ') : `${names.length} högar`;
      text = `${list} · ${facts.length} kort`;
      if (count && facts.length > count) text += ` · ${count} åt gången`;
    }
    $('wk-selbar-text').textContent = text;
    $('wk-start').disabled = !facts.length;
    $('wk-print-btn').disabled = !facts.length;
    $('wk-clear').hidden = !ids.length;
  }

  function renderWho() {
    const select = $('wk-who');
    select.innerHTML = Object.entries(store.profiles)
      .map(([id, p]) => `<option value="${esc(id)}"${id === store.current ? ' selected' : ''}>${esc(p.name)}</option>`)
      .join('');
    const name = profile().name;
    disarm($('wk-reset'), `Nollställ framstegen för ${name}`);
    disarm($('wk-remove'), `Ta bort ${name}`);
    $('wk-remove').hidden = Object.keys(store.profiles).length < 2;
  }

  function renderSettings() {
    const st = settings();
    for (const input of document.querySelectorAll('#wk-settings input[type=radio]')) {
      input.checked = String(st[input.name]) === input.value;
    }
    const parts = [
      st.mode === 'skriv' ? 'Skriv svaret' : 'Vänd kortet',
      st.limit ? `snabbt inom ${st.limit} s` : 'ingen tidsgräns',
      st.count ? `${st.count} kort per omgång` : 'hela högen',
    ];
    $('wk-settings-sum').textContent = parts.join(' · ');
  }

  /* ── The progress grids ──────────────────────────────────────────────── */

  const one2nine = [1, 2, 3, 4, 5, 6, 7, 8, 9];
  const one2ten = [...one2nine, 10];
  const GRIDS = {
    plus: {
      rows: one2nine, cols: one2nine, corner: () => '+', row: r => r, col: c => c,
      key: (r, c) => `add:${r}:${c}`, shown: (r, c) => r + c,
      help: 'Raden plus kolumnen: 8 + 7 står i rad 8 och kolumn 7.',
    },
    minus: {
      rows: one2nine, cols: one2nine, corner: () => '−', row: r => `− ${r}`, col: c => `= ${c}`,
      key: (r, c) => `sub:${r + c}:${r}`, shown: (r, c) => r + c,
      help: 'Raden är talet som tas bort och kolumnen svaret: 15 − 8 = 7 står i rad 8 och kolumn 7.',
    },
    ganger: {
      rows: one2ten, cols: one2ten, corner: () => S.SIGNS[settings().signs]['*'], row: r => r, col: c => c,
      key: (r, c) => `mul:${r}:${c}`, shown: (r, c) => r * c,
      help: () => `Raden gånger kolumnen: 6 ${S.SIGNS[settings().signs]['*']} 7 står i rad 6 och kolumn 7.`,
    },
    delat: {
      rows: one2ten.slice(1), cols: one2ten, corner: () => S.SIGNS[settings().signs]['/'],
      row: r => `${S.SIGNS[settings().signs]['/']} ${r}`, col: c => `= ${c}`,
      key: (r, c) => `div:${r * c}:${r}`, shown: (r, c) => r * c,
      help: () => `Raden är talet du delar med och kolumnen svaret: 42 ${S.SIGNS[settings().signs]['/']} 6 = 7 står i rad 6 och kolumn 7.`,
    },
  };

  const STATUS_WORDS = { none: 'inte övat än', ova: 'öva mer', nara: 'på gång', kan: 'kan' };

  function renderGrid() {
    const g = GRIDS[gridName];
    const signs = settings().signs;
    let kan = 0, cells = 0;
    let html = `<table class="wk-grid" data-grid="${gridName}"><thead><tr><th scope="col" class="wk-grid-corner">${esc(g.corner())}</th>`;
    html += g.cols.map(c => `<th scope="col">${esc(g.col(c))}</th>`).join('') + '</tr></thead><tbody>';
    for (const r of g.rows) {
      html += `<tr><th scope="row">${esc(g.row(r))}</th>`;
      for (const c of g.cols) {
        const key = g.key(r, c);
        const fact = S.factByKey[key];
        const st = statusOf(key);
        cells++;
        if (st === 'kan') kan++;
        const label = `${S.plainText(S.statement(fact).tokens, signs)}, ${STATUS_WORDS[st]}`;
        html += `<td><button type="button" class="wk-cell" data-key="${esc(key)}" data-status="${st}" aria-label="${esc(label)}"
          aria-pressed="${gridPick === key}" data-on-click="wk:cell">${g.shown(r, c)}</button></td>`;
      }
      html += '</tr>';
    }
    html += '</tbody></table>';
    $('wk-grid').innerHTML = html;
    $('wk-grid-sum').textContent = `Du kan ${kan} av ${cells}. ${typeof g.help === 'function' ? g.help() : g.help}`;
    for (const tab of document.querySelectorAll('.wk-tabs [role=tab]')) {
      tab.setAttribute('aria-selected', String(tab.dataset.grid === gridName));
    }
    renderCaption();
  }

  function renderCaption() {
    const cap = $('wk-grid-caption');
    if (!gridPick || !S.factByKey[gridPick]) { cap.textContent = 'Tryck på en ruta för att se hur det har gått.'; return; }
    const fact = S.factByKey[gridPick];
    const st = profile().facts[gridPick];
    let text = `${S.plainText(S.statement(fact).tokens, settings().signs)} · ${STATUS_WORDS[statusOf(gridPick)]}`;
    if (st) {
      text += ` · ${st.n === 1 ? 'övat en gång' : `övat ${st.n} gånger`}`;
      text += st.w ? `, ${st.w === 1 ? 'ett fel' : `${st.w} fel`}` : ', inga fel';
    }
    cap.textContent = text;
  }

  function renderHome() {
    renderWho();
    renderSettings();
    renderGroups();
    renderSelection();
    renderGrid();
  }

  /* ── A round ─────────────────────────────────────────────────────────── */

  const PRIORITY = { ova: 0, none: 1, nara: 2, kan: 3 };
  let round = null;
  let tickTimer = 0;
  let advanceTimer = 0;

  /* A pile larger than a round starts with what needs practice most. The
     shuffle first keeps equals in a different order every time. */
  function chooseCards(facts, count) {
    if (!count || facts.length <= count) return { cards: shuffle(facts.slice()), whole: true };
    const ranked = shuffle(facts.slice()).sort((x, y) => PRIORITY[statusOf(x.key)] - PRIORITY[statusOf(y.key)]);
    return { cards: shuffle(ranked.slice(0, count)), whole: false };
  }

  function roundTitle(ids, again) {
    const names = ids.map(id => setOf(id).title);
    const title = names.length === 1 ? names[0] : names.length === 2 ? names.join(' och ') : `${names.length} högar`;
    return again ? `Öva mer · ${title}` : title;
  }

  function startRound(ids, again) {
    const facts = again || selectedFacts(ids);
    if (!facts.length) return;
    const pick = again ? { cards: shuffle(again.slice()), whole: false } : chooseCards(facts, settings().count);
    clearInterval(tickTimer);
    clearTimeout(advanceTimer);
    round = {
      ids, title: roundTitle(ids, again), cards: pick.cards, mode: settings().mode,
      /* A record needs the whole of one real pile, first time through. */
      recordable: pick.whole && !again && ids.length === 1 && ids[0] !== HARD,
      i: 0, kan: [], ova: [], respMs: 0, clean: true, started: performance.now(), card: null, phase: 'idle',
    };
    $('wk-round-title').textContent = round.title;
    $('wk-pile-kan').querySelector('.wk-pile-stack').innerHTML = '';
    $('wk-pile-ova').querySelector('.wk-pile-stack').innerHTML = '';
    showView('practice');
    renderPiles();
    renderNumpad();
    tick();
    tickTimer = setInterval(tick, 500);
    showCard();
  }

  function tick() {
    if (!round) return;
    $('wk-round-time').textContent = mmss(performance.now() - round.started);
  }

  function renderPiles() {
    for (const pile of ['kan', 'ova']) {
      const n = round[pile].length;
      $(`wk-pile-${pile}-n`).textContent = n;
      const stack = $(`wk-pile-${pile}`).querySelector('.wk-pile-stack');
      const want = Math.min(n, 6);
      /* Slips are added, never redrawn, so each keeps the angle it landed at. */
      while (stack.children.length > want) stack.lastChild.remove();
      while (stack.children.length < want) {
        const slip = document.createElement('span');
        const k = stack.children.length;
        slip.style.setProperty('--r', `${(Math.random() * 10 - 5).toFixed(1)}deg`);
        slip.style.setProperty('--y', `${-k * 3}px`);
        stack.appendChild(slip);
      }
    }
    $('wk-practice').dataset.phase = round.phase;
  }

  function renderNumpad() {
    const pad = $('wk-numpad');
    const show = round.mode === 'skriv' && padOn();
    pad.hidden = !show;
    if (!show || pad.childElementCount) return;
    const KEYS = [
      ['7', '7'], ['8', '8'], ['9', '9'], ['back', '⌫', 'Sudda'],
      ['4', '4'], ['5', '5'], ['6', '6'], ['minus', '−', 'Minustecken'],
      ['1', '1'], ['2', '2'], ['3', '3'], ['comma', ',', 'Decimalkomma'],
      ['0', '0'], ['ok', 'OK', 'Svara'],
    ];
    pad.innerHTML = KEYS.map(([key, label, name]) =>
      `<button type="button" data-key="${key}" data-on-click="wk:key"${name ? ` aria-label="${name}"` : ''}>${label}</button>`).join('');
    /* The keys must not take the focus from the answer: on a desktop with the
       pad switched on, Enter would otherwise press the last key clicked. */
    pad.addEventListener('pointerdown', e => e.preventDefault());
  }

  function renderActions() {
    const box = $('wk-actions');
    const c = round.card;
    const hinted = c && c.hinted;
    const tips = `<button type="button" class="wk-btn wk-btn-quiet" data-on-click="wk:hint"${hinted ? ' disabled' : ''}>Tips</button>`;
    let html = '';
    if (round.phase === 'answer') {
      if (round.mode === 'skriv') html = tips + (padOn() ? '' : '<button type="button" class="wk-btn wk-btn-go" data-on-click="wk:submit">Svara</button>');
      else html = tips + '<button type="button" class="wk-btn wk-btn-go" id="wk-flip" data-on-click="wk:flip">Vänd kortet</button>';
    } else if (round.phase === 'feedback') {
      html = '<button type="button" class="wk-btn wk-btn-go" id="wk-next" data-on-click="wk:next">Nästa kort →</button>';
    } else if (round.phase === 'judge') {
      html = '<button type="button" class="wk-btn wk-btn-ova" data-on-click="wk:judge" data-kan="0">← Öva mer</button>'
        + `<button type="button" class="wk-btn wk-btn-kan" data-on-click="wk:judge" data-kan="1"${hinted ? ' disabled' : ''}>Kan →</button>`;
    }
    box.innerHTML = html;
    $('wk-practice').dataset.phase = round.phase;
  }

  /* Only the side facing the child is there for a screen reader: the back
     holds the answer. */
  function turn(side) {
    $('wk-card').dataset.side = side;
    $('wk-front').setAttribute('aria-hidden', String(side !== 'front'));
    $('wk-back').setAttribute('aria-hidden', String(side !== 'back'));
  }

  function setFeedback(text, tone) {
    const el = $('wk-feedback');
    el.textContent = text;
    el.dataset.tone = tone || '';
  }

  function startTimerBar() {
    const bar = $('wk-timer');
    const limit = settings().limit;
    bar.hidden = round.mode !== 'skriv' || !limit;
    bar.classList.remove('run', 'stop');
    if (bar.hidden) return;
    bar.style.setProperty('--wk-limit', `${limit}s`);
    void bar.offsetWidth; // restart the animation
    bar.classList.add('run');
  }

  function showCard() {
    clearTimeout(advanceTimer);
    if (round.i >= round.cards.length) { finishRound(); return; }
    const fact = round.cards[round.i];
    const form = S.pickForm(fact, settings().form, Math.random);
    const q = S.question(fact, form);
    round.card = { fact, form, q, hinted: false, shownAt: 0, flipMs: 0 };
    const set = S.setById[fact.set];
    const typing = round.mode === 'skriv';

    const deck = $('wk-deck');
    const card = $('wk-card');
    deck.style.setProperty('--wk-c', `var(--wk-${set.color})`);
    $('wk-band-front').textContent = set.title;
    $('wk-band-back').textContent = set.title;
    $('wk-eq').innerHTML = eqHtml(q.tokens, () => (typing ? inputHtml(fact) : '<span class="wk-blank wk-blank-q">?</span>'));
    $('wk-note').textContent = q.note || '';
    $('wk-eq-back').innerHTML = eqHtml(answered(q), () => '');
    const verdict = $('wk-verdict');
    verdict.textContent = '';
    verdict.dataset.tone = '';
    setFeedback('');
    $('wk-hint').hidden = true;
    $('wk-hint').innerHTML = '';

    /* Back to the front without playing the flip backwards. */
    card.classList.add('wk-still');
    turn('front');
    void card.offsetWidth;
    for (const a of card.getAnimations()) a.cancel();
    card.classList.remove('wk-still');
    /* translate and scale, not transform: transform is the flip, and a card
       turned while it is still arriving must turn. */
    if (!reduceMotion()) {
      card.animate([{ opacity: 0, translate: '0 16px', scale: '0.97' }, { opacity: 1, translate: '0 0', scale: '1' }],
        { duration: 220, easing: 'ease-out' });
    }

    round.phase = 'answer';
    $('wk-round-count').textContent = `Kort ${round.i + 1} av ${round.cards.length}`;
    renderActions();
    renderPiles();
    startTimerBar();
    if (typing) {
      const input = $('wk-input');
      sizeInput(input);
      input.focus({ preventScroll: true });
    } else {
      deck.focus({ preventScroll: true });
    }
    round.card.shownAt = performance.now();
  }

  function submit() {
    if (!round || round.phase !== 'answer' || round.mode !== 'skriv') return;
    const input = $('wk-input');
    const x = S.parseAnswer(input.value);
    if (x === null) {
      setFeedback(input.value.trim() ? 'Det där är inget tal. Skriv svaret med siffror.' : 'Skriv ditt svar först.', 'info');
      if (!reduceMotion()) {
        input.animate([{ transform: 'translateX(0)' }, { transform: 'translateX(-6px)' }, { transform: 'translateX(6px)' },
          { transform: 'translateX(0)' }], { duration: 240 });
      }
      input.focus({ preventScroll: true });
      return;
    }
    const ms = performance.now() - round.card.shownAt;
    const ok = S.sameNumber(x, round.card.q.answer);
    const limit = settings().limit;
    settle(ok, !limit || ms <= limit * 1000, ms, input.value.trim());
  }

  function settle(ok, quick, ms, typed) {
    const c = round.card;
    const kan = ok && quick && !c.hinted;
    record(c.fact.key, kan, ms);
    saveStore();
    round.respMs += ms;
    if (!ok || c.hinted) round.clean = false;
    round.pending = kan ? 'kan' : 'ova';
    (kan ? round.kan : round.ova).push({ fact: c.fact, q: c.q, typed: ok ? null : typed });

    const bar = $('wk-timer');
    bar.classList.add('stop');
    const input = $('wk-input');
    input.readOnly = true;

    const answer = S.fmtPlain(c.q.answer);
    const verdict = $('wk-verdict');
    if (ok) {
      verdict.textContent = '✓ Rätt';
      verdict.dataset.tone = kan ? 'kan' : 'ova';
    } else {
      verdict.textContent = `Du skrev ${typed}`;
      verdict.dataset.tone = 'ova';
    }
    if (kan) setFeedback('Rätt!', 'kan');
    else if (ok && c.hinted) setFeedback('Rätt! Du tog hjälp av tipset, så kortet läggs i Öva mer-högen den här gången.', 'ova');
    else if (ok) setFeedback(`Rätt, men det tog ${seconds(ms)}. Kortet läggs i Öva mer-högen – nästa gång går det fortare.`, 'ova');
    else setFeedback(`Inte riktigt – rätt svar är ${answer}.`, 'ova');

    turn('back');
    round.phase = 'feedback';
    renderActions();
    const flipTime = reduceMotion() ? 0 : 450;
    if (kan) advanceTimer = setTimeout(advance, flipTime + 650);
    else if (ok) advanceTimer = setTimeout(advance, flipTime + 2600);
    else $('wk-next').focus({ preventScroll: true });
  }

  function flip() {
    if (!round || round.phase !== 'answer' || round.mode !== 'vand') return;
    round.card.flipMs = performance.now() - round.card.shownAt;
    turn('back');
    round.phase = 'judge';
    if (round.card.hinted) setFeedback('Du tog hjälp av tipset, så kortet läggs i Öva mer-högen den här gången.', 'ova');
    else setFeedback('Kunde du? Lägg kortet i rätt hög.');
    renderActions();
    $('wk-deck').focus({ preventScroll: true });
  }

  function judge(kanSaid) {
    if (!round || round.phase !== 'judge') return;
    const c = round.card;
    const kan = kanSaid && !c.hinted;
    record(c.fact.key, kan, c.flipMs);
    saveStore();
    if (!kan) round.clean = false;
    round.pending = kan ? 'kan' : 'ova';
    (kan ? round.kan : round.ova).push({ fact: c.fact, q: c.q, typed: null });
    advance();
  }

  function advance() {
    if (!round || (round.phase !== 'feedback' && round.phase !== 'judge')) return;
    clearTimeout(advanceTimer);
    round.phase = 'moving';
    renderActions();
    const next = () => {
      if (!round || round.phase !== 'moving') return;
      round.i += 1;
      renderPiles();
      showCard();
    };
    if (reduceMotion()) { next(); return; }
    const card = $('wk-card');
    const from = $('wk-deck').getBoundingClientRect();
    const to = $(`wk-pile-${round.pending}`).querySelector('.wk-pile-stack').getBoundingClientRect();
    const dx = to.left + to.width / 2 - (from.left + from.width / 2);
    const dy = to.top + to.height / 2 - (from.top + from.height / 2);
    const scale = Math.max(0.12, to.width / from.width);
    const fly = card.animate([
      { transform: 'rotateY(180deg)', opacity: 1 },
      { transform: `translate(${dx}px, ${dy}px) rotateY(180deg) scale(${scale})`, opacity: 0.35 },
    ], { duration: 380, easing: 'cubic-bezier(.45,.05,.75,.5)', fill: 'forwards' });
    fly.finished.then(next, next);
  }

  function showHint() {
    if (!round || round.phase !== 'answer') return;
    const c = round.card;
    const h = S.hint(c.fact, c.form);
    c.hinted = true;
    const box = $('wk-hint');
    box.innerHTML = `<p class="wk-hint-text">${esc(withSigns(h.text))}</p>${picHtml(h.pic)}`
      + '<p class="wk-hint-note">Med tipset hamnar kortet i Öva mer-högen den här gången.</p>';
    box.hidden = false;
    renderActions();
    if (round.mode === 'skriv') $('wk-input').focus({ preventScroll: true });
  }

  function finishRound() {
    clearInterval(tickTimer);
    clearTimeout(advanceTimer);
    round.phase = 'done';
    const r = round;
    let timeText = '';
    if (r.mode === 'skriv') {
      timeText = `Tid att svara: ${mmss(r.respMs)}.`;
      if (r.recordable) {
        const id = r.ids[0];
        const prev = profile().best[id];
        if (r.clean && (!prev || r.respMs < prev)) {
          profile().best[id] = Math.round(r.respMs);
          saveStore();
          timeText += prev ? ` Nytt rekord! Förra var ${mmss(prev)}.` : ' Det är ditt rekord för den här högen.';
        } else if (prev) {
          timeText += ` Rekordet är ${mmss(prev)}.`;
        } else {
          timeText += ' Klarar du hela högen rätt på första försöket sparas tiden som rekord.';
        }
      }
    }
    const allKan = !r.ova.length;
    $('wk-sum-title').textContent = allKan ? 'Alla kort hamnade i Kan-högen!' : 'Högen är slut';
    $('wk-sum-kan').textContent = r.kan.length;
    $('wk-sum-ova').textContent = r.ova.length;
    $('wk-sum-time').textContent = timeText;
    const signs = settings().signs;
    $('wk-sum-list').innerHTML = r.ova.length
      ? '<p class="wk-sum-lead">Kort att öva mer på:</p><ul class="wk-chips">' + r.ova.map(o =>
        `<li class="wk-chip">${esc(S.plainText(answered(o.q), signs))}${o.typed != null ? ` <span class="wk-chip-typed">(du skrev ${esc(o.typed)})</span>` : ''}</li>`).join('') + '</ul>'
      : '';
    const n = r.ova.length;
    let actions = '';
    if (n) actions += `<button type="button" class="wk-btn wk-btn-go" data-on-click="wk:again">Öva på ${n === 1 ? 'kortet' : `de ${n} korten`} igen</button>`;
    actions += '<button type="button" class="wk-btn" data-on-click="wk:repeat">Hela högen igen</button>';
    actions += '<button type="button" class="wk-btn wk-btn-quiet" data-on-click="wk:home">Välj andra kort</button>';
    $('wk-sum-actions').innerHTML = actions;
    showView('summary');
    const first = $('wk-sum-actions').querySelector('button');
    if (first) first.focus({ preventScroll: true });
  }

  function quit() {
    clearInterval(tickTimer);
    clearTimeout(advanceTimer);
    round = null;
    showView('home');
  }

  /* ── Keys ────────────────────────────────────────────────────────────── */

  function onKey(e) {
    if (!round || $('wk-practice').hidden || e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey) return;
    const onButton = e.target && e.target.tagName === 'BUTTON';
    const key = e.key.length === 1 ? e.key.toLowerCase() : e.key;
    if (round.phase === 'feedback' && !onButton && (key === 'Enter' || key === ' ')) {
      e.preventDefault();
      advance();
    } else if (round.phase === 'answer' && round.mode === 'vand' && !onButton && (key === 'Enter' || key === ' ')) {
      e.preventDefault();
      flip();
    } else if (round.phase === 'judge' && (key === 'ArrowRight' || key === 'k')) {
      e.preventDefault();
      if (!round.card.hinted) judge(true);
    } else if (round.phase === 'judge' && (key === 'ArrowLeft' || key === 'ö' || key === 'o')) {
      e.preventDefault();
      judge(false);
    } else if (round.phase === 'answer' && round.mode === 'skriv' && /^[0-9,.\-−]$/.test(key)) {
      /* Typing with the answer box out of focus puts the digit in it. */
      const input = $('wk-input');
      if (input && document.activeElement !== input) input.focus({ preventScroll: true });
    }
  }

  function padKey(key) {
    if (!round || round.phase !== 'answer' || round.mode !== 'skriv') {
      if (key === 'ok' && round && round.phase === 'feedback') advance();
      return;
    }
    const input = $('wk-input');
    if (key === 'ok') { submit(); return; }
    let v = input.value;
    if (key === 'back') v = v.slice(0, -1);
    else if (key === 'minus') v = v.startsWith('−') || v.startsWith('-') ? v.slice(1) : '−' + v;
    else if (key === 'comma') { if (!/[,.]/.test(v)) v += v ? ',' : '0,'; }
    else if (v.length < 10) v += key;
    input.value = v;
    sizeInput(input);
  }

  /* ── People ──────────────────────────────────────────────────────────── */

  /* A destructive button asks twice: the first press changes its label. */
  function armed(button, text) {
    if (button.dataset.armed === '1') return true;
    button.dataset.armed = '1';
    button.textContent = text;
    button.classList.add('wk-btn-armed');
    clearTimeout(button._disarm);
    button._disarm = setTimeout(() => renderWho(), 5000);
    return false;
  }

  function disarm(button, text) {
    clearTimeout(button._disarm);
    button.dataset.armed = '';
    button.textContent = text;
    button.classList.remove('wk-btn-armed');
  }

  function addPerson() {
    const input = $('wk-newname');
    const name = input.value.trim().slice(0, 30);
    if (!name) { input.focus(); return; }
    const ids = Object.keys(store.profiles).map(id => Number(id.slice(1)));
    const id = `p${Math.max(0, ...ids) + 1}`;
    store.profiles[id] = newProfile(name);
    store.current = id;
    saveStore();
    closeNewPerson();
    renderHome();
    $('wk-who').focus();
  }

  function openNewPerson() {
    $('wk-newperson').hidden = false;
    $('wk-newperson-btn').hidden = true;
    $('wk-newname').value = '';
    $('wk-newname').focus();
  }

  function closeNewPerson() {
    $('wk-newperson').hidden = true;
    $('wk-newperson-btn').hidden = false;
  }

  /* ── Printing ────────────────────────────────────────────────────────── */

  const PER_SHEET = 18; // 3 × 6 cards of 63 × 44 mm on A4
  const PER_ROW = 3;

  function printCards() {
    const facts = selectedFacts(selectedIds());
    if (!facts.length) return;
    let box = $('wk-print');
    if (!box) {
      box = document.createElement('div');
      box.id = 'wk-print';
      box.setAttribute('aria-hidden', 'true');
      document.body.appendChild(box);
    }
    const signs = settings().signs;
    const face = (f, back) => {
      const set = S.setById[f.set];
      const q = S.question(f, f.kind === 'op' ? f.form0 : 'text');
      const band = `<span class="wk-pc-band">${esc(set.title)}</span>`;
      const body = back
        ? `<span class="wk-pc-ans">${esc(S.fmtPlain(q.answer))}</span><span class="wk-pc-full">${esc(S.plainText(answered(q), signs))}</span>`
        : `<span class="wk-pc-eq">${eqHtml(q.tokens, () => '<span class="wk-pc-box"></span>')}</span>`
          + (q.note ? `<span class="wk-pc-note">${esc(q.note)}</span>` : '');
      return `<div class="wk-pc${back ? ' wk-pc-back' : ''}" style="--wk-c: var(--wk-${set.color})">${band}${body}</div>`;
    };
    const empty = '<div class="wk-pc wk-pc-empty"></div>';
    const sheets = Math.ceil(facts.length / PER_SHEET);
    let html = '';
    for (let s = 0; s < sheets; s++) {
      const chunk = facts.slice(s * PER_SHEET, (s + 1) * PER_SHEET);
      const fronts = chunk.map(f => face(f, false));
      const backs = chunk.map(f => face(f, true));
      while (fronts.length < PER_SHEET) { fronts.push(empty); backs.push(empty); }
      /* Turned over the long edge, a row reads right to left. */
      const mirrored = [];
      for (let r = 0; r < PER_SHEET; r += PER_ROW) mirrored.push(...backs.slice(r, r + PER_ROW).reverse());
      const head = side => `<p class="wk-sheet-head">Winnetkakort · ${side} ${s + 1} av ${sheets}${side === 'framsida'
        ? ' · skriv ut dubbelsidigt och vänd längs långsidan' : ''}</p>`;
      html += `<section class="wk-sheet" data-side="front">${head('framsida')}<div class="wk-sheet-grid">${fronts.join('')}</div></section>`;
      html += `<section class="wk-sheet" data-side="back">${head('baksida')}<div class="wk-sheet-grid">${mirrored.join('')}</div></section>`;
    }
    box.innerHTML = html;
    window.print();
  }

  /* ── Actions ─────────────────────────────────────────────────────────── */

  function onSetting(e, el) {
    const name = el.name;
    if (!(name in DEFAULTS)) return;
    const value = typeof DEFAULTS[name] === 'number' ? Number(el.value) : el.value;
    if (!CHOICES[name].includes(value)) return;
    settings()[name] = value;
    saveStore();
    renderSettings();
    renderSelection();
    if (name === 'signs') { renderGroups(); renderGrid(); }
  }

  function registerAll() {
    registerActions({
      'wk:toggle': (e, el) => {
        const id = el.dataset.set;
        if (selected.has(id)) selected.delete(id); else selected.add(id);
        el.setAttribute('aria-pressed', String(selected.has(id)));
        renderSelection();
      },
      'wk:clear': () => { selected.clear(); renderGroups(); renderSelection(); },
      'wk:start': () => startRound(selectedIds()),
      'wk:print': () => printCards(),
      'wk:setting': onSetting,
      'wk:who': (e, el) => {
        if (!store.profiles[el.value]) return;
        store.current = el.value;
        saveStore();
        gridPick = null;
        renderHome();
      },
      'wk:newPerson': () => openNewPerson(),
      'wk:addPerson': () => addPerson(),
      'wk:cancelPerson': () => { closeNewPerson(); $('wk-newperson-btn').focus(); },
      'wk:newNameKey': e => {
        if (e.key === 'Enter') { e.preventDefault(); addPerson(); }
        else if (e.key === 'Escape') { e.preventDefault(); closeNewPerson(); $('wk-newperson-btn').focus(); }
      },
      'wk:resetPerson': (e, el) => {
        const p = profile();
        if (!armed(el, `Tryck igen för att radera allt för ${p.name}`)) return;
        p.facts = Object.create(null);
        p.best = Object.create(null);
        saveStore();
        renderHome();
        notifyUser(`Framstegen för ${p.name} är raderade.`, { tone: 'success' });
      },
      'wk:removePerson': (e, el) => {
        const p = profile();
        if (Object.keys(store.profiles).length < 2) return;
        if (!armed(el, `Tryck igen för att ta bort ${p.name}`)) return;
        delete store.profiles[store.current];
        store.current = Object.keys(store.profiles)[0];
        saveStore();
        renderHome();
        notifyUser(`${p.name} är borttagen.`, { tone: 'success' });
      },
      'wk:grid': (e, el) => { gridName = el.dataset.grid; gridPick = null; renderGrid(); },
      'wk:cell': (e, el) => {
        gridPick = el.dataset.key;
        for (const b of document.querySelectorAll('.wk-cell[aria-pressed=true]')) b.setAttribute('aria-pressed', 'false');
        el.setAttribute('aria-pressed', 'true');
        renderCaption();
      },

      'wk:typed': (e, el) => {
        const clean = el.value.replace(/[^0-9,.\-−\s]/g, '').slice(0, 12);
        if (clean !== el.value) el.value = clean;
        sizeInput(el);
      },
      'wk:answerKey': e => {
        if (e.key !== 'Enter') return;
        e.preventDefault();
        if (round && round.phase === 'answer') submit();
        else advance();
      },
      'wk:submit': () => submit(),
      'wk:key': (e, el) => padKey(el.dataset.key),
      'wk:hint': () => showHint(),
      'wk:flip': () => flip(),
      'wk:tapCard': () => {
        if (!round || round.phase !== 'answer') return;
        if (round.mode === 'vand') flip();
        else $('wk-input').focus({ preventScroll: true });
      },
      'wk:judge': (e, el) => judge(el.dataset.kan === '1'),
      'wk:pile': (e, el) => {
        if (!round || round.phase !== 'judge') return;
        if (el.dataset.pile === 'kan' && round.card.hinted) return;
        judge(el.dataset.pile === 'kan');
      },
      'wk:next': () => advance(),
      'wk:quit': () => quit(),
      'wk:again': () => { const r = round; startRound(r.ids, r.ova.map(o => o.fact)); },
      /* "Mina svåra kort" may be empty by now - that is the point of it - so
         the cards of the round just played are the pile to go through again. */
      'wk:repeat': () => {
        const r = round;
        startRound(r.ids, selectedFacts(r.ids).length ? null : r.cards.slice());
      },
      'wk:home': () => { round = null; showView('home'); },
    });
  }

  function init() {
    try {
      store = loadStore();
      registerAll();
      $('wk-deck').setAttribute('data-on-click', 'wk:tapCard');
      $('wk-deck').tabIndex = -1;
      for (const pile of ['kan', 'ova']) $(`wk-pile-${pile}`).setAttribute('data-on-click', 'wk:pile');
      document.addEventListener('keydown', onKey);
      showView('home');
    } catch (e) {
      reportFailure('winnetkakort: init', e, { userMessage: 'Winnetkakorten kunde inte starta.' });
    }
  }

  /* For the tests: the page's own view of the progress, read-only. */
  const inspect = () => ({
    keys: round && round.cards.map(f => f.key),
    round: round && { phase: round.phase, i: round.i, n: round.cards.length, kan: round.kan.length, ova: round.ova.length,
      answer: round.card && round.card.q.answer, form: round.card && round.card.form, key: round.card && round.card.fact.key },
    status: key => statusOf(key),
    store: JSON.parse(JSON.stringify(store)),
  });

  return { init, inspect };
})();
