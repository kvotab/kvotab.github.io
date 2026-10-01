/* ==========================================================================
   GLOSOR - THE PAGE

   flashcards.html: choose themes or a list of one's own, go through them a
   card at a time, and see the words sorted into Kan and Öva mer. The words,
   and how an answer is judged, are in flashcards-words.js; the look is
   Winnetkakort's (winnetkakort.css), and so is the routine:

     - A round goes through the chosen cards once, in shuffled order.
     - A card answered right without the hint goes to Kan, anything else to
       Öva mer, and the Öva mer pile is offered as the next round until it
       is empty.

   On top of that, a word is due again later, by Leitner's boxes: every day
   while it is not known, after two days when it nearly is, after a week
   once it is. Those are the cards in "Dags att repetera".

   Progress, settings and the pupil's own lists are kept in localStorage
   under 'flashcards.v1', and never leave the browser unless the pupil shares
   a list, which puts the list - and only the list - in a link.
   ========================================================================== */

const FC = (() => {
  'use strict';

  const W = FC_WORDS;
  const $ = id => document.getElementById(id);
  const esc = kvotEscapeHtml;
  const reduceMotion = () => matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ── Storage ─────────────────────────────────────────────────────────── */

  const STORE_KEY = 'flashcards.v1';
  const FULL_KEY = 'flashcards.full';
  const DEFAULTS = Object.freeze({
    lang: 'en', dir: 'till', mode: 'skriv', count: 20, pics: true, speak: true, accents: 'valfri', article: 'valfri', sound: false,
    look: 'kvot',
  });
  const CHOICES = Object.freeze({
    lang: ['en', 'es'], dir: ['till', 'fran', 'blandat'], mode: ['skriv', 'valj', 'vand', 'lyssna'], count: [10, 20, 30, 0],
    pics: [true, false], speak: [true, false], accents: ['valfri', 'krav'], article: ['valfri', 'krav'], sound: [true, false],
    look: CARD_LOOKS.ids,
  });

  let store = null;
  let saveWarned = false;

  const newProfile = name => ({ name, settings: { ...DEFAULTS }, facts: Object.create(null) });

  function loadStore() {
    let raw = null;
    try {
      const text = localStorage.getItem(STORE_KEY);
      if (text) raw = JSON.parse(text);
    } catch (e) {
      ignoreFailure('flashcards: read progress', e);
    }
    return cleanStore(raw);
  }

  const cleanText = (s, max) => (typeof s === 'string' ? s.trim().slice(0, max) : '');

  /*
    Storage is written by this page, but it can be edited by hand or left by
    an older version, so every field is checked on the way in, and a list is
    held to the same limits as one arriving in a link. The maps are
    prototype-free: a key read from storage is only ever a map key.
  */
  function cleanStore(raw) {
    const out = { v: 1, current: null, profiles: Object.create(null), lists: [] };
    if (raw && typeof raw === 'object') {
      if (raw.profiles && typeof raw.profiles === 'object') {
        for (const [id, p] of Object.entries(raw.profiles)) {
          if (!/^p\d{1,6}$/.test(id) || !p || typeof p !== 'object') continue;
          const profile = newProfile(cleanText(p.name, 30) || 'Jag');
          if (p.settings && typeof p.settings === 'object') {
            for (const k of Object.keys(DEFAULTS)) if (CHOICES[k].includes(p.settings[k])) profile.settings[k] = p.settings[k];
          }
          if (p.facts && typeof p.facts === 'object') {
            for (const [key, st] of Object.entries(p.facts)) {
              if (!st || typeof st !== 'object' || !Number.isFinite(st.n) || st.n < 1 || typeof key !== 'string' || key.length > 300) continue;
              const box = [1, 2, 3].includes(st.box) ? st.box : 1;
              profile.facts[key] = {
                n: Math.floor(st.n), w: Math.max(0, Math.floor(Number(st.w) || 0)), box,
                d: typeof st.d === 'string' && /^\d{4}-\d\d-\d\d$/.test(st.d) ? st.d : '',
              };
            }
          }
          out.profiles[id] = profile;
        }
      }
      if (Array.isArray(raw.lists)) {
        for (const l of raw.lists.slice(0, W.LIMITS.lists)) {
          if (!l || typeof l !== 'object' || !/^l\d{1,6}$/.test(l.id) || !W.LANGS[l.lang] || !Array.isArray(l.words)) continue;
          const words = l.words
            .filter(p => Array.isArray(p) && p.length === 2 && p.every(x => typeof x === 'string' && x.trim()))
            .slice(0, W.LIMITS.words)
            .map(([sv, x]) => [sv.trim().slice(0, W.LIMITS.field), x.trim().slice(0, W.LIMITS.field)]);
          if (!words.length || out.lists.some(o => o.id === l.id)) continue;
          out.lists.push({ id: l.id, name: cleanText(l.name, W.LIMITS.name) || 'Min lista', lang: l.lang, words });
        }
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
      ignoreFailure('flashcards: save progress', e);
      if (!saveWarned) {
        saveWarned = true;
        notifyUser('Framstegen kan inte sparas i den här webbläsaren. De finns kvar tills du stänger sidan.');
      }
    }
  }

  const profile = () => store.profiles[store.current];
  const settings = () => profile().settings;
  const lang = () => settings().lang;
  const langName = l => W.LANGS[l || lang()].name;

  /* The day in Sweden, not in Greenwich: a word practised at half past
     midnight belongs to the new day. */
  function today() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  }

  /* ── Progress per card ───────────────────────────────────────────────── */

  const statOf = key => profile().facts[key];
  const statusOf = key => W.statusOf(statOf(key));

  function record(key, kan) {
    profile().facts[key] = W.nextStat(statOf(key), kan, today());
  }

  /* ── Speech ──────────────────────────────────────────────────────────── */

  /* The browser's own voices. A word is only read out by a voice that
     speaks its language: Spanish read by an English voice teaches the wrong
     sounds, so without one there is no loudspeaker button at all. */
  const speech = { supported: typeof speechSynthesis !== 'undefined' && typeof SpeechSynthesisUtterance !== 'undefined' };

  function voiceFor(l) {
    if (!speech.supported) return null;
    const voices = speechSynthesis.getVoices() || [];
    for (const want of W.LANGS[l].speech) {
      const v = voices.find(x => String(x.lang || '').replace('_', '-').toLowerCase().startsWith(want.toLowerCase()));
      if (v) return v;
    }
    return null;
  }

  const canSpeak = l => !!voiceFor(l);

  function say(text, l) {
    const voice = voiceFor(l);
    if (!voice || !text) return;
    try {
      speechSynthesis.cancel();
      const u = new SpeechSynthesisUtterance(String(text).replace(/…/g, ''));
      u.voice = voice;
      u.lang = voice.lang;
      u.rate = 0.85;
      speechSynthesis.speak(u);
    } catch (e) {
      ignoreFailure('flashcards: speak', e);
    }
  }

  /* ── Themes, lists and the pile of words due again ───────────────────── */

  const REPEAT = 'repetera';
  const topicCache = new Map();

  function listTopic(l) {
    return { id: l.id, title: l.name, list: true, words: l.words, lang: l.lang };
  }

  function builtinTopics() {
    const key = `topics:${lang()}`;
    if (!topicCache.has(key)) {
      const map = new Map();
      for (const g of W.topicsFor(lang())) for (const t of g.topics) map.set(t.id, { ...t, group: g.id, color: g.color });
      topicCache.set(key, map);
    }
    return topicCache.get(key);
  }

  const ownLists = () => store.lists.filter(l => l.lang === lang());

  function topicById(id) {
    if (id === REPEAT) return { id: REPEAT, title: 'Dags att repetera', color: 'accent' };
    const l = store.lists.find(x => x.id === id && x.lang === lang());
    if (l) return { ...listTopic(l), color: 'teal' };
    return builtinTopics().get(id) || null;
  }

  /* Cards of one theme one way round, made once per language and direction. */
  function cardsOf(topic, dir) {
    if (topic.list) return W.cardsFor(topic, lang(), dir);
    const key = `${lang()}:${topic.id}:${topic.kind ? 'x' : dir}`;
    if (!topicCache.has(key)) topicCache.set(key, W.cardsFor(topic, lang(), dir));
    return topicCache.get(key);
  }

  const RANK = { none: 0, ova: 1, nara: 2, kan: 3 };

  /* Mixed directions: each word once, the way round it is weaker in. */
  function mixed(topic) {
    const till = cardsOf(topic, 'till'), fran = cardsOf(topic, 'fran');
    return till.map((c, i) => {
      const a = RANK[statusOf(c.key)], b = RANK[statusOf(fran[i].key)];
      if (a !== b) return a < b ? c : fran[i];
      return Math.random() < 0.5 ? c : fran[i];
    });
  }

  function cardsForTopic(topic) {
    if (topic.kind) return cardsOf(topic, 'till');
    const dir = settings().dir;
    return dir === 'blandat' ? mixed(topic) : cardsOf(topic, dir);
  }

  /* Every card of this language that the pupil has met, and that its box
     says is due today - both ways round, whatever the direction setting. */
  function dueCards() {
    const day = today();
    const seen = new Set(), out = [];
    const topics = [...builtinTopics().values(), ...ownLists().map(listTopic)];
    for (const t of topics) {
      const sets = t.kind ? [cardsOf(t, 'till')] : [cardsOf(t, 'till'), cardsOf(t, 'fran')];
      for (const set of sets) for (const c of set) {
        if (seen.has(c.key) || !W.isDue(statOf(c.key), day)) continue;
        seen.add(c.key);
        out.push(c);
      }
    }
    return out;
  }

  function cardsForSelection(id) {
    if (id === REPEAT) return dueCards();
    const t = topicById(id);
    return t ? cardsForTopic(t) : [];
  }

  /* How a theme stands, the way the direction setting asks it. */
  function topicCounts(topic) {
    let kan = 0, nara = 0;
    const cards = topic.kind || settings().dir !== 'blandat' ? cardsForTopic(topic) : null;
    if (cards) {
      for (const c of cards) { const st = statusOf(c.key); if (st === 'kan') kan++; else if (st === 'nara') nara++; }
      return { n: cards.length, kan, nara };
    }
    const till = cardsOf(topic, 'till'), fran = cardsOf(topic, 'fran');
    till.forEach((c, i) => {
      const a = statusOf(c.key), b = statusOf(fran[i].key);
      if (a === 'kan' && b === 'kan') kan++;
      else if ([a, b].some(s => s === 'kan' || s === 'nara')) nara++;
    });
    return { n: till.length, kan, nara };
  }

  /* ── Small helpers ───────────────────────────────────────────────────── */

  function shuffle(list) {
    for (let i = list.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [list[i], list[j]] = [list[j], list[i]];
    }
    return list;
  }

  const pct = (n, of) => (of ? Math.round((1000 * n) / of) / 10 : 0);
  const unit = topic => (topic.kind === 'forms' ? 'verb' : topic.kind === 'konj' ? 'former' : 'ord');

  const DIR_LABEL = { till: l => `Svenska → ${langName(l)}`, fran: l => `${W.LANGS[l || lang()].Name} → svenska`, blandat: () => 'Blandat' };
  const MODE_LABEL = { skriv: 'Skriv ordet', valj: 'Välj bland fyra', vand: 'Vänd kortet', lyssna: 'Lyssna och skriv' };

  /* A word's picture: an emoji, or a colour for the theme Färger. Only when
     pictures are on, unless asked for anyway (the hint shows it). */
  function picHtml(pic, always) {
    if (!pic || (!always && !settings().pics)) return '';
    if (/^#[0-9a-f]{6}$/i.test(pic)) return `<span class="fc-swatch" style="--fc-swatch:${pic}"></span>`;
    return `<span class="fc-emoji">${esc(pic)}</span>`;
  }

  /* A long word or phrase gets a smaller size on the card. */
  const lengthClass = text => (text.length > 26 ? 'xl' : text.length > 14 ? 'l' : '');

  /* ── Views ───────────────────────────────────────────────────────────── */

  function showView(name) {
    for (const v of ['home', 'study', 'practice', 'summary']) $(`fc-${v}`).hidden = v !== name;
    $('fc-scroll').scrollTop = 0;
    if (name === 'home') renderHome();
  }

  /* ── The home view ───────────────────────────────────────────────────── */

  const selected = new Set();

  /* A card from the pile, as the direction setting will ask it. */
  function example(topic) {
    const cards = topic.id === REPEAT ? dueCards() : cardsOf(topic, 'till');
    const c = cards[Math.min(cards.length - 1, 2)];
    if (!c) return '';
    if (c.kind === 'konj') return `${c.front.text}: ${c.person.split(' / ')[0]} → ${c.answer}`;
    if (c.kind !== 'word' || topic.id === REPEAT) return cardLine(c);
    const dir = settings().dir;
    if (dir === 'fran') return `${c.answer} → ${c.front.text}`;
    return `${c.front.text} ${dir === 'blandat' ? '↔' : '→'} ${c.answer}`;
  }

  function tileHtml(topic) {
    const repeat = topic.id === REPEAT;
    const counts = repeat ? { n: dueCards().length, kan: 0, nara: 0 } : topicCounts(topic);
    const meta = [`${counts.n} ${unit(topic)}`, counts.kan ? `${counts.kan} kan` : ''].filter(Boolean).join(' · ');
    return `<button type="button" class="wk-tile" data-set="${esc(topic.id)}" aria-pressed="${selected.has(topic.id)}" data-on-click="fc:toggle">
        <span class="wk-tile-band" aria-hidden="true"></span>
        <span class="wk-tile-title">${esc(topic.title)}</span>
        <span class="wk-tile-eg">${esc(example(topic))}</span>
        <span class="wk-meter" aria-hidden="true"><span class="wk-meter-kan" style="width:${pct(counts.kan, counts.n)}%"></span><span class="wk-meter-nara" style="width:${pct(counts.nara, counts.n)}%"></span></span>
        <span class="wk-tile-meta">${esc(meta)}</span>
        <span class="wk-tile-tick" aria-hidden="true"></span>
      </button>`;
  }

  function groupHtml(g, extra) {
    return `<section class="wk-group" style="--wk-c: var(--wk-${g.color})" aria-labelledby="fc-g-${g.id}">
        <div class="wk-group-head"><h2 id="fc-g-${g.id}">${esc(g.title)}</h2>${g.grade ? `<span class="wk-grade">${esc(g.grade)}</span>` : ''}</div>
        <p class="wk-group-desc">${esc(g.desc)}</p>
        <div class="wk-tiles">${g.topics.map(tileHtml).join('')}${extra || ''}</div>
      </section>`;
  }

  function listsHtml() {
    const lists = ownLists();
    if (!lists.length) return '';
    return `<ul class="fc-lists">${lists.map(l => `<li>
        <span class="fc-lists-name">${esc(l.name)} <span class="fc-lists-n">${l.words.length} ord</span></span>
        <span class="fc-row">
          <button type="button" class="wk-btn wk-btn-quiet" data-list="${esc(l.id)}" data-on-click="fc:editList">Ändra</button>
          <button type="button" class="wk-btn wk-btn-quiet" data-list="${esc(l.id)}" data-on-click="fc:shareList">Dela</button>
          <button type="button" class="wk-btn wk-btn-quiet" data-list="${esc(l.id)}" data-on-click="fc:deleteList">Ta bort</button>
        </span>
        <span class="fc-share" data-share="${esc(l.id)}" hidden></span>
      </li>`).join('')}</ul>`;
  }

  function renderGroups() {
    const due = dueCards();
    if (!due.length) selected.delete(REPEAT);
    for (const id of [...selected]) if (id !== REPEAT && !topicById(id)) selected.delete(id);
    let own = '';
    if (due.length) {
      own += groupHtml({
        id: 'repeat', title: 'Att repetera', color: 'accent', grade: '',
        desc: 'Ord som behöver övas i dag: de du inte kunde, och de du kunde för några dagar sedan.', topics: [topicById(REPEAT)],
      });
    }
    const lists = ownLists();
    own += `<section class="wk-group fc-own" style="--wk-c: var(--wk-teal)" aria-labelledby="fc-g-own">
        <div class="wk-group-head"><h2 id="fc-g-own">Mina glosor</h2><span class="wk-grade">${esc(langName())}</span></div>
        <p class="wk-group-desc">${lists.length ? 'Dina egna listor – till exempel veckans glosor från skolan.' : 'Har du fått glosor i skolan? Skriv in dem här, så övar du på dem som på alla andra kort.'}</p>
        <div class="wk-tiles">${lists.map(l => tileHtml({ ...listTopic(l), color: 'teal' })).join('')}
          <button type="button" class="fc-newlist" data-on-click="fc:newList"><span aria-hidden="true">＋</span> Ny lista</button></div>
        ${listsHtml()}
      </section>`;
    $('fc-groups-own').innerHTML = own;
    $('fc-groups').innerHTML = W.topicsFor(lang())
      .map(g => groupHtml({ ...g, grade: g.grade[lang()], topics: g.topics.map(t => builtinTopics().get(t.id)) })).join('');
  }

  function selectedIds() {
    const order = [REPEAT, ...ownLists().map(l => l.id), ...builtinTopics().keys()];
    return order.filter(id => selected.has(id));
  }

  function selectedCards(ids) {
    const seen = new Set(), out = [];
    for (const id of ids) for (const c of cardsForSelection(id)) if (!seen.has(c.key)) { seen.add(c.key); out.push(c); }
    return out;
  }

  function renderSelection() {
    const ids = selectedIds();
    const n = selectedCards(ids).length;
    const count = settings().count;
    let text;
    if (!ids.length) text = 'Välj ett eller flera teman att öva på.';
    else {
      const names = ids.map(id => topicById(id).title);
      text = `${names.length <= 3 ? names.join(', ') : `${names.length} teman`} · ${n} kort`;
      if (count && n > count) text += ` · ${count} åt gången`;
    }
    $('fc-selbar-text').textContent = text;
    for (const id of ['fc-start', 'fc-print-btn', 'fc-study-btn']) $(id).disabled = !n;
    $('fc-clear').hidden = !ids.length;
  }

  function renderLang() {
    for (const b of document.querySelectorAll('.fc-lang [data-lang]')) b.setAttribute('aria-pressed', String(b.dataset.lang === lang()));
    document.documentElement.dataset.fcLang = lang();
  }

  function renderWho() {
    $('fc-who').innerHTML = Object.entries(store.profiles)
      .map(([id, p]) => `<option value="${esc(id)}"${id === store.current ? ' selected' : ''}>${esc(p.name)}</option>`).join('');
    const name = profile().name;
    disarm($('fc-reset'), `Nollställ framstegen för ${name}`);
    disarm($('fc-remove'), `Ta bort ${name}`);
    $('fc-remove').hidden = Object.keys(store.profiles).length < 2;
  }

  function renderSettings() {
    const st = settings();
    for (const input of document.querySelectorAll('#fc-settings input')) {
      if (input.type === 'checkbox') input.checked = !!st[input.name];
      else input.checked = String(st[input.name]) === input.value;
    }
    for (const span of document.querySelectorAll('[data-dir-label]')) span.textContent = DIR_LABEL[span.dataset.dirLabel]();
    for (const span of document.querySelectorAll('[data-lang-name]')) span.textContent = langName();
    const speakable = canSpeak(lang());
    const listen = document.querySelector('#fc-settings input[name=mode][value=lyssna]');
    listen.disabled = !speakable;
    document.querySelector('#fc-settings input[name=speak]').disabled = !speakable;
    $('fc-speech-help').hidden = speakable;
    const mode = effectiveMode();
    const summary = [DIR_LABEL[st.dir](), MODE_LABEL[mode], st.count ? `${st.count} kort per omgång` : 'hela högen'];
    if (st.look !== CARD_LOOKS.DEFAULT) summary.push(CARD_LOOKS.label(st.look));
    $('fc-settings-sum').textContent = summary.join(' · ');
    /* The picker is made once and then only marked, so the tile just pressed
       keeps the focus; the page is in this person's look. */
    const picker = $('fc-looks');
    if (!picker.childElementCount) picker.innerHTML = CARD_LOOKS.pickerHtml(st.look, 'fc:look', 'hund');
    else CARD_LOOKS.markPicked(picker, st.look);
    CARD_LOOKS.apply(st.look);
  }

  /* Listening needs a voice; without one the page types instead. */
  const effectiveMode = () => (settings().mode === 'lyssna' && !canSpeak(lang()) ? 'skriv' : settings().mode);

  function renderProgress() {
    let kan = 0, nara = 0, ova = 0;
    const weak = [];
    const topics = [...builtinTopics().values(), ...ownLists().map(listTopic)];
    const seen = new Set();
    for (const t of topics) for (const set of (t.kind ? [cardsOf(t, 'till')] : [cardsOf(t, 'till'), cardsOf(t, 'fran')])) for (const c of set) {
      if (seen.has(c.key)) continue;
      seen.add(c.key);
      const st = statusOf(c.key);
      if (st === 'kan') kan++;
      else if (st === 'nara') nara++;
      else if (st === 'ova') { ova++; if (weak.length < 40) weak.push(c); }
    }
    const due = dueCards().length;
    const total = kan + nara + ova;
    $('fc-progress-sum').textContent = total
      ? `På ${langName()} kan du ${kan} kort, ${nara} är på gång och ${ova} behöver du öva mer på.${due ? ` ${due} är dags att repetera i dag.` : ''}`
      : `Du har inte övat på några ord på ${langName()} än.`;
    $('fc-progress-list').innerHTML = weak.length
      ? `<p class="wk-help">Att öva mer på:</p><ul class="wk-chips">${weak.map(c => `<li class="wk-chip">${esc(cardLine(c))}</li>`).join('')}</ul>`
      : '';
  }

  /** A card as one line of text: "hund → dog", "go → went – gone". */
  function cardLine(c) {
    if (c.kind === 'forms') return `${c.base} → ${c.answer}`;
    if (c.kind === 'genus') return c.say;
    if (c.kind === 'konj') return `${c.front.text}: ${c.say}`;
    return `${c.front.text} → ${c.answer}`;
  }

  function renderHome() {
    renderLang();
    renderWho();
    renderSettings();
    renderGroups();
    renderSelection();
    renderProgress();
  }

  /* ── A round ─────────────────────────────────────────────────────────── */

  const PRIORITY = { ova: 0, none: 1, nara: 2, kan: 3 };
  let round = null;
  let advanceTimer = 0;

  /* A pile larger than a round starts with what needs practice most; the
     shuffle first keeps equals in a different order every time. */
  function chooseCards(cards, count) {
    if (!count || cards.length <= count) return shuffle(cards.slice());
    const ranked = shuffle(cards.slice()).sort((x, y) => PRIORITY[statusOf(x.key)] - PRIORITY[statusOf(y.key)]);
    return shuffle(ranked.slice(0, count));
  }

  function roundTitle(ids, again) {
    const names = ids.map(id => (topicById(id) || { title: '' }).title);
    const title = names.length === 1 ? names[0] : names.length === 2 ? names.join(' och ') : `${names.length} teman`;
    return again ? `Öva mer · ${title}` : title;
  }

  function startRound(ids, again) {
    const cards = again || selectedCards(ids);
    if (!cards.length) return;
    clearTimeout(advanceTimer);
    round = {
      ids, title: roundTitle(ids, again), cards: again ? shuffle(again.slice()) : chooseCards(cards, settings().count),
      mode: effectiveMode(), i: 0, kan: [], ova: [], card: null, phase: 'idle', pending: null,
    };
    $('fc-round-title').textContent = round.title;
    for (const pile of ['kan', 'ova']) $(`wk-pile-${pile}`).querySelector('.wk-pile-stack').innerHTML = '';
    showView('practice');
    renderPiles();
    showCard();
  }

  function renderPiles() {
    for (const pile of ['kan', 'ova']) {
      const n = round[pile].length;
      $(`fc-pile-${pile}-n`).textContent = n;
      const stack = $(`wk-pile-${pile}`).querySelector('.wk-pile-stack');
      const want = Math.min(n, 6);
      while (stack.children.length > want) stack.lastChild.remove();
      while (stack.children.length < want) {
        const slip = document.createElement('span');
        slip.style.setProperty('--r', `${(Math.random() * 10 - 5).toFixed(1)}deg`);
        slip.style.setProperty('--y', `${-stack.children.length * 3}px`);
        stack.appendChild(slip);
      }
    }
    $('fc-practice').dataset.phase = round.phase;
  }

  /* The way this card is asked: listening only works for words, and el or
     la is always a choice between the two. */
  function modeFor(c) {
    if (round.mode === 'lyssna' && c.kind !== 'word') return 'skriv';
    return round.mode;
  }

  /* The pool the three wrong answers come from: the same theme, same way round. */
  function poolFor(c) {
    const t = topicById(c.topic);
    if (!t) return round.cards;
    return t.kind ? cardsOf(t, 'till') : cardsOf(t, c.dir);
  }

  function askText(c, mode) {
    if (mode === 'lyssna') return 'Skriv ordet du hör';
    if (c.kind === 'word') return c.dir === 'till' ? `på ${langName(c.lang)}` : 'på svenska';
    return c.ask;
  }

  /* Not ¿ or ¡: punctuation never counts, and ¡ looks like an i. */
  const ACCENTS = ['á', 'é', 'í', 'ó', 'ú', 'ñ', 'ü'];

  function inputHtml(c) {
    return `<input class="fc-input" id="fc-input" type="text" lang="${esc(c.answerLang)}" autocomplete="off" autocorrect="off"
      autocapitalize="off" spellcheck="false" enterkeyhint="done" aria-label="Ditt svar" data-on-keydown="fc:answerKey">`;
  }

  function turn(side) {
    $('fc-card').dataset.side = side;
    $('fc-front').setAttribute('aria-hidden', String(side !== 'front'));
    $('fc-back').setAttribute('aria-hidden', String(side !== 'back'));
  }

  function setFeedback(text, tone) {
    const el = $('fc-feedback');
    el.textContent = text;
    el.dataset.tone = tone || '';
  }

  function showCard() {
    clearTimeout(advanceTimer);
    if (round.i >= round.cards.length) { finishRound(); return; }
    const c = round.cards[round.i];
    const mode = modeFor(c);
    const topic = topicById(c.topic) || { title: '' };
    round.card = { c, mode, hinted: false, options: mode === 'valj' ? W.options(c, poolFor(c), Math.random) : null, typed: '' };

    const deck = $('fc-deck');
    deck.style.setProperty('--wk-c', `var(--wk-${topic.color || 'teal'})`);
    $('fc-band-front').textContent = topic.title;
    $('fc-band-back').textContent = topic.title;

    /* The front. */
    $('fc-pic-front').innerHTML = mode === 'lyssna' || c.kind === 'forms' || c.kind === 'konj' ? '' : picHtml(c.pic);
    const prompt = $('fc-prompt');
    prompt.dataset.len = mode === 'lyssna' ? '' : lengthClass(c.front.text);
    if (mode === 'lyssna') {
      prompt.removeAttribute('lang');
      prompt.innerHTML = '<button type="button" class="fc-say fc-say-big" data-say="listen" data-on-click="fc:say" aria-label="Lyssna igen">🔊</button>';
    } else {
      prompt.lang = c.front.lang;
      const frontSays = c.front.lang !== 'sv' && canSpeak(c.lang);
      prompt.innerHTML = `<span class="fc-prompt-text">${esc(c.front.text)}</span>`
        + (frontSays ? '<button type="button" class="fc-say" data-say="front" data-on-click="fc:say" aria-label="Lyssna">🔊</button>' : '');
    }
    $('fc-sub').textContent = mode === 'lyssna' ? '' : c.sub || '';
    $('fc-ask').textContent = askText(c, mode);
    $('fc-answerbox').innerHTML = mode === 'skriv' || mode === 'lyssna' ? inputHtml(c)
      : mode === 'vand' ? '<span class="fc-q">?</span>' : '';

    /* The back. */
    $('fc-pic-back').innerHTML = c.kind === 'forms' || c.kind === 'konj' ? '' : picHtml(c.pic);
    const back = $('fc-prompt-back');
    back.lang = c.front.lang;
    back.textContent = c.kind === 'konj' ? `${c.front.text} · ${c.person}` : c.kind === 'genus' ? `${c.front.text} (${c.sub})` : c.front.text;
    const answer = $('fc-answer');
    answer.lang = c.answerLang;
    answer.textContent = c.kind === 'forms' ? c.full : c.kind === 'genus' ? c.say : c.kind === 'konj' ? c.say : c.answer;
    $('fc-answer').parentElement.dataset.len = lengthClass(answer.textContent);
    $('fc-say-back').hidden = !canSpeak(c.lang);
    const verdict = $('fc-verdict');
    verdict.textContent = '';
    verdict.dataset.tone = '';
    setFeedback('');
    $('fc-hint').hidden = true;
    $('fc-hint').innerHTML = '';

    /* Beside the card: four to choose from, or the Spanish letters. */
    const choices = $('fc-choices');
    choices.hidden = mode !== 'valj';
    choices.innerHTML = mode === 'valj'
      ? round.card.options.map((o, i) => `<button type="button" class="fc-choice" data-i="${i}" lang="${esc(c.answerLang)}" data-on-click="fc:choose"><span class="fc-choice-n" aria-hidden="true">${i + 1}</span>${esc(o)}</button>`).join('')
      : '';
    choices.dataset.count = round.card.options ? round.card.options.length : 0;
    const accents = $('fc-accents');
    accents.hidden = !((mode === 'skriv' || mode === 'lyssna') && c.answerLang === 'es' && c.kind !== 'genus');
    if (!accents.hidden && !accents.childElementCount) {
      accents.innerHTML = ACCENTS.map(a => `<button type="button" data-char="${a}" data-on-click="fc:accent" aria-label="${a}">${a}</button>`).join('');
      /* A key must not take the focus from the answer: the phone's keyboard would close. */
      accents.addEventListener('pointerdown', e => e.preventDefault());
    }

    const card = $('fc-card');
    card.classList.add('wk-still');
    turn('front');
    void card.offsetWidth;
    for (const a of card.getAnimations()) a.cancel();
    card.classList.remove('wk-still');
    if (!reduceMotion()) {
      card.animate([{ opacity: 0, translate: '0 16px', scale: '0.97' }, { opacity: 1, translate: '0 0', scale: '1' }],
        { duration: 220, easing: 'ease-out' });
    }

    round.phase = 'answer';
    $('fc-round-count').textContent = `Kort ${round.i + 1} av ${round.cards.length}`;
    renderActions();
    renderPiles();
    if (mode === 'skriv' || mode === 'lyssna') $('fc-input').focus({ preventScroll: true });
    else if (mode === 'valj') choices.querySelector('button').focus({ preventScroll: true });
    else deck.focus({ preventScroll: true });
    if (mode === 'lyssna') setTimeout(() => { if (round && round.card && round.card.c === c) say(c.say, c.lang); }, 250);
  }

  function renderActions() {
    const box = $('fc-actions');
    const rc = round.card;
    const tips = `<button type="button" class="wk-btn wk-btn-quiet" data-on-click="fc:hint"${rc && rc.hinted ? ' disabled' : ''}>Tips</button>`;
    let html = '';
    if (round.phase === 'answer') {
      if (rc.mode === 'skriv' || rc.mode === 'lyssna') html = tips + '<button type="button" class="wk-btn wk-btn-go" data-on-click="fc:submit">Svara</button>';
      else if (rc.mode === 'valj') html = tips;
      else html = tips + '<button type="button" class="wk-btn wk-btn-go" id="fc-flip" data-on-click="fc:flip">Vänd kortet</button>';
    } else if (round.phase === 'feedback') {
      html = '<button type="button" class="wk-btn wk-btn-go" id="fc-next" data-on-click="fc:next">Nästa kort →</button>';
    } else if (round.phase === 'judge') {
      html = '<button type="button" class="wk-btn wk-btn-ova" data-on-click="fc:judge" data-kan="0">← Öva mer</button>'
        + `<button type="button" class="wk-btn wk-btn-kan" data-on-click="fc:judge" data-kan="1"${rc.hinted ? ' disabled' : ''}>Kan →</button>`;
    }
    box.innerHTML = html;
    $('fc-practice').dataset.phase = round.phase;
  }

  const judgeOpts = () => ({ accents: settings().accents, article: settings().article });

  function submit() {
    if (!round || round.phase !== 'answer' || !(round.card.mode === 'skriv' || round.card.mode === 'lyssna')) return;
    const input = $('fc-input');
    const res = W.judge(round.card.c, input.value, judgeOpts());
    if (res.verdict === 'empty') {
      setFeedback('Skriv ditt svar först.', 'info');
      if (!reduceMotion()) {
        input.animate([{ transform: 'translateX(0)' }, { transform: 'translateX(-6px)' }, { transform: 'translateX(6px)' },
          { transform: 'translateX(0)' }], { duration: 240 });
      }
      input.focus({ preventScroll: true });
      return;
    }
    round.card.typed = input.value.trim();
    input.readOnly = true;
    settle(res);
  }

  function choose(i) {
    if (!round || round.phase !== 'answer' || round.card.mode !== 'valj') return;
    const rc = round.card;
    const picked = rc.options[i];
    if (picked == null) return;
    const res = W.judge(rc.c, picked, { accents: 'valfri', article: 'valfri' });
    rc.typed = picked;
    for (const b of $('fc-choices').querySelectorAll('button')) {
      const o = rc.options[Number(b.dataset.i)];
      b.disabled = true;
      if (W.judge(rc.c, o, { accents: 'valfri', article: 'valfri' }).ok) b.dataset.state = 'right';
      else if (Number(b.dataset.i) === i) b.dataset.state = 'wrong';
    }
    settle(res);
  }

  function settle(res) {
    const rc = round.card;
    const c = rc.c;
    const kan = res.ok && !rc.hinted;
    record(c.key, kan);
    saveStore();
    round.pending = kan ? 'kan' : 'ova';
    (kan ? round.kan : round.ova).push({ c, typed: res.ok ? null : rc.typed });

    const verdict = $('fc-verdict');
    verdict.textContent = res.ok ? '✓ Rätt' : `Du ${rc.mode === 'valj' ? 'valde' : 'skrev'} ${rc.typed}`;
    verdict.dataset.tone = kan ? 'kan' : 'ova';
    const shownAnswer = c.kind === 'forms' ? `${c.base} – ${c.answer}` : c.kind === 'genus' || c.kind === 'konj' ? c.say : c.answer;
    let message, wait;
    if (kan && !res.note) { message = 'Rätt!'; wait = 1100; }
    else if (kan) { message = res.note; wait = 2800; }
    else if (res.ok) { message = 'Rätt! Du tog hjälp av tipset, så ordet läggs i Öva mer-högen den här gången.'; wait = 2800; }
    else if (res.note) { message = `${res.note} Ordet läggs i Öva mer-högen.`; wait = 0; }
    else { message = `Inte riktigt – det heter ${shownAnswer}.`; wait = 0; }
    setFeedback(message, kan ? 'kan' : 'ova');

    turn('back');
    WK_SOUND.play('flip');
    /* Nearly right - a letter off, an accent or el/la missing - is the softer
       note, like right with the hint: only a wrong word gets the uh-oh. */
    const near = res.ok || ['almost', 'accent', 'article'].includes(res.verdict);
    WK_SOUND.play(kan ? 'right' : near ? 'okay' : 'wrong', 0.16);
    round.phase = 'feedback';
    renderActions();
    if (settings().speak) setTimeout(() => { if (round && round.card === rc) say(c.say, c.lang); }, afterChime(reduceMotion() ? 0 : 350));
    const flip = reduceMotion() ? 0 : 450;
    if (wait) advanceTimer = setTimeout(advance, flip + wait);
    else $('fc-next').focus({ preventScroll: true });
  }

  function flip() {
    if (!round || round.phase !== 'answer' || round.card.mode !== 'vand') return;
    turn('back');
    round.phase = 'judge';
    if (round.card.hinted) setFeedback('Du tog hjälp av tipset, så ordet läggs i Öva mer-högen den här gången.', 'ova');
    else setFeedback('Kunde du? Lägg kortet i rätt hög.');
    renderActions();
    WK_SOUND.play('flip');
    const rc = round.card;
    if (settings().speak) setTimeout(() => { if (round && round.card === rc) say(rc.c.say, rc.c.lang); }, settings().sound ? 250 : 0);
    $('fc-deck').focus({ preventScroll: true });
  }

  /* With the sound effects on, a word is read out once the chime has
     rung, not on top of it. */
  const afterChime = ms => (settings().sound ? 650 : ms);

  function judge(kanSaid) {
    if (!round || round.phase !== 'judge') return;
    const rc = round.card;
    const kan = kanSaid && !rc.hinted;
    record(rc.c.key, kan);
    saveStore();
    round.pending = kan ? 'kan' : 'ova';
    (kan ? round.kan : round.ova).push({ c: rc.c, typed: null });
    if (kan) WK_SOUND.play('right');
    advance();
  }

  function advance() {
    if (!round || (round.phase !== 'feedback' && round.phase !== 'judge')) return;
    clearTimeout(advanceTimer);
    round.phase = 'moving';
    renderActions();
    const next = () => {
      if (!round || round.phase !== 'moving') return;
      WK_SOUND.play('land');
      round.i += 1;
      renderPiles();
      showCard();
    };
    if (reduceMotion()) { next(); return; }
    const from = $('fc-deck').getBoundingClientRect();
    const to = $(`wk-pile-${round.pending}`).querySelector('.wk-pile-stack').getBoundingClientRect();
    const dx = to.left + to.width / 2 - (from.left + from.width / 2);
    const dy = to.top + to.height / 2 - (from.top + from.height / 2);
    const scale = Math.max(0.12, to.width / from.width);
    const fly = $('fc-card').animate([
      { transform: 'rotateY(180deg)', opacity: 1 },
      { transform: `translate(${dx}px, ${dy}px) rotateY(180deg) scale(${scale})`, opacity: 0.35 },
    ], { duration: 380, easing: 'cubic-bezier(.45,.05,.75,.5)', fill: 'forwards' });
    fly.finished.then(next, next);
  }

  function showHint() {
    if (!round || round.phase !== 'answer') return;
    const rc = round.card;
    rc.hinted = true;
    const box = $('fc-hint');
    /* With pictures off, or listening, the picture is part of the hint. */
    const pic = rc.c.kind === 'word' && (!settings().pics || rc.mode === 'lyssna') ? picHtml(rc.c.pic, true) : '';
    box.innerHTML = `<p class="wk-hint-text fc-hint-letters" lang="${esc(rc.c.answerLang)}">${esc(W.hint(rc.c))}</p>`
      + (pic ? `<p class="fc-hint-pic">${pic}</p>` : '')
      + '<p class="wk-hint-note">Med tipset hamnar ordet i Öva mer-högen den här gången.</p>';
    box.hidden = false;
    WK_SOUND.play('hint');
    renderActions();
    if (rc.mode === 'skriv' || rc.mode === 'lyssna') $('fc-input').focus({ preventScroll: true });
  }

  function finishRound() {
    clearTimeout(advanceTimer);
    round.phase = 'done';
    const r = round;
    /* After the last card's tap into its pile. */
    WK_SOUND.play(r.ova.length ? 'done' : 'allKan', 0.12);
    $('fc-sum-title').textContent = r.ova.length ? 'Högen är slut' : 'Alla kort hamnade i Kan-högen!';
    $('fc-sum-kan').textContent = r.kan.length;
    $('fc-sum-ova').textContent = r.ova.length;
    $('fc-sum-list').innerHTML = r.ova.length
      ? '<p class="wk-sum-lead">Ord att öva mer på:</p><ul class="wk-chips">' + r.ova.map(o =>
        `<li class="wk-chip">${esc(cardLine(o.c))}${o.typed != null ? ` <span class="wk-chip-typed">(du svarade ${esc(o.typed)})</span>` : ''}</li>`).join('') + '</ul>'
      : '';
    const n = r.ova.length;
    let actions = '';
    if (n) actions += `<button type="button" class="wk-btn wk-btn-go" data-on-click="fc:again">Öva på ${n === 1 ? 'ordet' : `de ${n} orden`} igen</button>`;
    actions += '<button type="button" class="wk-btn" data-on-click="fc:repeat">Hela högen igen</button>';
    actions += '<button type="button" class="wk-btn wk-btn-quiet" data-on-click="fc:home">Välj andra ord</button>';
    $('fc-sum-actions').innerHTML = actions;
    showView('summary');
    const first = $('fc-sum-actions').querySelector('button');
    if (first) first.focus({ preventScroll: true });
  }

  function quit() {
    clearTimeout(advanceTimer);
    if (speech.supported) speechSynthesis.cancel();
    round = null;
    showView('home');
  }

  function accentKey(ch) {
    const input = $('fc-input');
    if (!input || input.readOnly) return;
    const start = input.selectionStart ?? input.value.length, end = input.selectionEnd ?? input.value.length;
    input.setRangeText(ch, start, end, 'end');
    input.focus({ preventScroll: true });
  }

  /* ── Looking at the words first ──────────────────────────────────────── */

  function showStudy() {
    const ids = selectedIds();
    const cards = selectedCards(ids);
    if (!cards.length) return;
    /* Words are shown the way the card asks them: Swedish first. */
    const rows = cards.map((c, i) => {
      const x = c.kind === 'word' ? (c.dir === 'till' ? c.answer : c.front.text) : c.kind === 'forms' ? c.full : c.say;
      const sv = c.kind === 'word' ? (c.dir === 'till' ? c.front.text : c.answer) : c.sub || c.front.text;
      return `<li class="fc-study-row"><span class="fc-study-pic">${c.kind === 'word' ? picHtml(c.pic) : ''}</span>
        <span class="fc-study-sv" lang="sv">${esc(sv)}</span>
        <span class="fc-study-x" lang="${esc(c.lang)}">${esc(x)}</span>
        ${canSpeak(c.lang) ? `<button type="button" class="fc-say" data-i="${i}" data-on-click="fc:sayStudy" aria-label="Lyssna på ${esc(x)}">🔊</button>` : '<span></span>'}</li>`;
    });
    studyCards = cards;
    $('fc-study-title').textContent = `Titta på orden · ${roundTitle(ids)}`;
    $('fc-study-list').innerHTML = `<ul>${rows.join('')}</ul>`;
    showView('study');
  }
  let studyCards = [];

  /* ── Lists of one's own ──────────────────────────────────────────────── */

  let editing = null; // the id of the list being edited, or 'new'

  function openEditor(id) {
    const l = id && store.lists.find(x => x.id === id);
    editing = l ? l.id : 'new';
    $('fc-editor-title').textContent = l ? `Ändra ${l.name}` : 'Ny lista';
    $('fc-list-name').value = l ? l.name : '';
    $('fc-list-text').value = l ? W.listText(l.words) : '';
    const listLang = l ? l.lang : lang();
    for (const r of document.querySelectorAll('input[name=listlang]')) r.checked = r.value === listLang;
    $('fc-editor').hidden = false;
    renderListStatus();
    $('fc-editor').scrollIntoView({ block: 'start', behavior: reduceMotion() ? 'auto' : 'smooth' });
    $('fc-list-name').focus({ preventScroll: true });
  }

  function closeEditor() {
    editing = null;
    $('fc-editor').hidden = true;
  }

  function renderListStatus() {
    const parsed = W.parseList($('fc-list-text').value);
    const el = $('fc-list-status');
    let text = parsed.words.length === 1 ? '1 ord' : `${parsed.words.length} ord`;
    if (parsed.errors.length) {
      const e = parsed.errors[0];
      text += ` · rad ${e.line} har inget = eller - mellan orden: ”${e.text}”`;
      if (parsed.errors.length > 1) text += ` (och ${parsed.errors.length - 1} rader till)`;
    }
    el.textContent = text;
    el.dataset.tone = parsed.errors.length ? 'ova' : '';
    $('fc-list-save').disabled = !parsed.words.length;
  }

  function saveList() {
    const parsed = W.parseList($('fc-list-text').value);
    if (!parsed.words.length) return;
    const listLang = document.querySelector('input[name=listlang]:checked')?.value || lang();
    const name = $('fc-list-name').value.trim().slice(0, W.LIMITS.name) || 'Min lista';
    let l = editing !== 'new' && store.lists.find(x => x.id === editing);
    if (!l) {
      if (store.lists.length >= W.LIMITS.lists) { notifyUser(`Det går att ha högst ${W.LIMITS.lists} egna listor.`); return; }
      l = { id: nextListId() };
      store.lists.push(l);
    }
    Object.assign(l, { name, lang: listLang, words: parsed.words });
    saveStore();
    closeEditor();
    if (listLang !== lang()) setSetting('lang', listLang);
    selected.add(l.id);
    renderHome();
    notifyUser(`Listan ${name} är sparad: ${parsed.words.length} ord.`, { tone: 'success' });
  }

  function nextListId() {
    const n = store.lists.map(l => Number(l.id.slice(1))).filter(Number.isFinite);
    return `l${Math.max(0, ...n) + 1}`;
  }

  function shareLink(l) {
    return `${location.origin}${location.pathname}#glosor=${W.encodeShare(l)}`;
  }

  async function shareList(id) {
    const l = store.lists.find(x => x.id === id);
    if (!l) return;
    const link = shareLink(l);
    const box = document.querySelector(`.fc-share[data-share="${CSS.escape(id)}"]`);
    let copied = false;
    try {
      await navigator.clipboard.writeText(link);
      copied = true;
    } catch (e) {
      ignoreFailure('flashcards: copy the link', e);
    }
    box.innerHTML = `<span>${copied ? 'Länken är kopierad – klistra in den där du vill dela listan.' : 'Kopiera länken:'}</span>
      <input type="text" readonly value="${esc(link)}" aria-label="Länk till listan ${esc(l.name)}">`;
    box.hidden = false;
    const input = box.querySelector('input');
    input.addEventListener('focus', () => input.select());
    if (!copied) input.focus();
  }

  /* A link somebody shared: offered at the top of the page, added only on a yes. */
  let offered = null;

  function readShared() {
    const m = /^#glosor=([A-Za-z0-9_-]+)$/.exec(location.hash);
    if (!m) return;
    offered = W.decodeShare(m[1]);
    if (!offered) {
      clearHash();
      notifyUser('Länken innehöll ingen lista som gick att läsa.');
      return;
    }
    $('fc-import-text').textContent = `Någon har delat glosorna ”${offered.name}”: ${offered.words.length} ord på ${langName(offered.lang)}.`;
    $('fc-import').hidden = false;
  }

  function clearHash() {
    try { history.replaceState(null, '', location.pathname + location.search); } catch (e) { ignoreFailure('flashcards: clear the link', e); }
  }

  function importOffered() {
    if (!offered) return;
    const same = store.lists.find(l => l.lang === offered.lang && l.name === offered.name
      && JSON.stringify(l.words) === JSON.stringify(offered.words));
    let l = same;
    if (!l) {
      if (store.lists.length >= W.LIMITS.lists) { notifyUser(`Det går att ha högst ${W.LIMITS.lists} egna listor.`); return; }
      l = { id: nextListId(), name: offered.name, lang: offered.lang, words: offered.words };
      store.lists.push(l);
      saveStore();
    }
    dismissOffer();
    if (l.lang !== lang()) setSetting('lang', l.lang);
    selected.add(l.id);
    renderHome();
    notifyUser(same ? `Listan ${l.name} fanns redan.` : `Listan ${l.name} finns nu i Mina glosor.`, { tone: 'success' });
  }

  function dismissOffer() {
    offered = null;
    $('fc-import').hidden = true;
    clearHash();
  }

  /* ── People ──────────────────────────────────────────────────────────── */

  function armed(button, text) {
    if (button.dataset.armed === '1') return true;
    button.dataset.armed = '1';
    button.textContent = text;
    button.classList.add('wk-btn-armed');
    clearTimeout(button._disarm);
    button._disarm = setTimeout(() => { button.dataset.armed = ''; renderHome(); }, 5000);
    return false;
  }

  function disarm(button, text) {
    clearTimeout(button._disarm);
    button.dataset.armed = '';
    button.textContent = text;
    button.classList.remove('wk-btn-armed');
  }

  function addPerson() {
    const input = $('fc-newname');
    const name = input.value.trim().slice(0, 30);
    if (!name) { input.focus(); return; }
    const ids = Object.keys(store.profiles).map(id => Number(id.slice(1)));
    const id = `p${Math.max(0, ...ids) + 1}`;
    store.profiles[id] = newProfile(name);
    store.current = id;
    saveStore();
    $('fc-newperson').hidden = true;
    $('fc-newperson-btn').hidden = false;
    selected.clear();
    renderHome();
    syncSound();
    $('fc-who').focus();
  }

  /* ── Printing ────────────────────────────────────────────────────────── */

  const PER_SHEET = 18; // 3 × 6 cards of 63 × 44 mm on A4
  const PER_ROW = 3;

  /* Printed cards are Swedish on the front, whichever way the screen asks. */
  function tillVersion(c) {
    if (c.kind !== 'word' || c.dir === 'till') return c;
    const t = topicById(c.topic);
    const key = c.key.replace('|fran|', '|till|');
    return (t && cardsOf(t, 'till').find(x => x.key === key)) || c;
  }

  function printCards() {
    const seen = new Set();
    const cards = selectedCards(selectedIds()).map(tillVersion).filter(c => !seen.has(c.key) && seen.add(c.key));
    if (!cards.length) return;
    let box = $('wk-print');
    if (!box) {
      box = document.createElement('div');
      box.id = 'wk-print';
      box.setAttribute('aria-hidden', 'true');
      document.body.appendChild(box);
    }
    const face = (c, back) => {
      const t = topicById(c.topic) || { title: '', color: 'teal' };
      const band = `<span class="wk-pc-band">${esc(t.title)}</span>`;
      const pic = c.kind === 'word' && c.pic ? (c.pic.startsWith('#')
        ? `<span class="fc-pc-swatch" style="--fc-swatch:${c.pic}"></span>` : `<span class="fc-pc-emoji">${esc(c.pic)}</span>`) : '';
      const body = back
        ? `<span class="wk-pc-ans fc-pc-word" lang="${esc(c.lang)}">${esc(c.kind === 'forms' ? c.answer : c.kind === 'genus' || c.kind === 'konj' ? c.say : c.answer)}</span>`
          + (c.kind === 'forms' ? `<span class="wk-pc-full">${esc(c.full)}</span>` : '')
        : `${pic}<span class="wk-pc-eq fc-pc-word">${esc(c.kind === 'konj' ? `${c.front.text}: ${c.person} …` : c.front.text)}</span>`
          + (c.sub ? `<span class="wk-pc-note">${esc(c.sub)}</span>` : '');
      return `<div class="wk-pc${back ? ' wk-pc-back' : ''}" style="--wk-c: var(--wk-${t.color || 'teal'})">${band}${body}</div>`;
    };
    const empty = '<div class="wk-pc wk-pc-empty"></div>';
    const sheets = Math.ceil(cards.length / PER_SHEET);
    let html = '';
    for (let s = 0; s < sheets; s++) {
      const chunk = cards.slice(s * PER_SHEET, (s + 1) * PER_SHEET);
      const fronts = chunk.map(c => face(c, false));
      const backs = chunk.map(c => face(c, true));
      while (fronts.length < PER_SHEET) { fronts.push(empty); backs.push(empty); }
      /* Turned over the long edge, a row reads right to left. */
      const mirrored = [];
      for (let r = 0; r < PER_SHEET; r += PER_ROW) mirrored.push(...backs.slice(r, r + PER_ROW).reverse());
      const head = side => `<p class="wk-sheet-head">Glosor · ${side} ${s + 1} av ${sheets}${side === 'framsida'
        ? ' · skriv ut dubbelsidigt och vänd längs långsidan' : ''}</p>`;
      html += `<section class="wk-sheet" data-side="front">${head('framsida')}<div class="wk-sheet-grid">${fronts.join('')}</div></section>`;
      html += `<section class="wk-sheet" data-side="back">${head('baksida')}<div class="wk-sheet-grid">${mirrored.join('')}</div></section>`;
    }
    box.innerHTML = html;
    window.print();
  }

  /* ── The full window, and the phone's keyboard ───────────────────────── */

  function setFull(on) {
    document.documentElement.classList.toggle('wk-full', on);
    try { localStorage.setItem(FULL_KEY, on ? '1' : '0'); } catch (e) { ignoreFailure('flashcards: remember the full window', e); }
    fullState();
  }

  function fullState() {
    const on = document.documentElement.classList.contains('wk-full');
    for (const b of document.querySelectorAll('.wk-fullbtn')) {
      b.setAttribute('aria-pressed', String(on));
      b.title = on ? 'Visa sajtens sidhuvud och sidfot igen' : 'Helt fönster: sidan utan sajtens sidhuvud och sidfot';
    }
  }

  /* While the phone's keyboard is up, the card is sized to what is left above
     it (flashcards.css reads --fc-vh), so the word and the answer stay in
     sight. Android does this itself with interactive-widget=resizes-content;
     an iPhone needs telling. */
  function watchKeyboard() {
    const vv = window.visualViewport;
    if (!vv) return;
    const update = () => {
      const up = vv.height < window.innerHeight - 80;
      if (up) document.documentElement.style.setProperty('--fc-vh', `${Math.round(vv.height)}px`);
      else document.documentElement.style.removeProperty('--fc-vh');
    };
    vv.addEventListener('resize', update);
    update();
  }

  /* ── Sound effects ───────────────────────────────────────────────────── */

  /* Winnetkakort's (winnetkakort-sound.js). On or off from a tap - the
     loudspeaker in either bar, or the setting - so the audio may start at
     once; switching on plays the chime, so the child hears what "on" sounds
     like. */
  function setSound(on) {
    setSetting('sound', !!on);
    WK_SOUND.setOn(on, true);
    soundState();
    renderSettings();
    if (on) WK_SOUND.play('right');
  }

  function soundState() {
    const on = !!settings().sound;
    for (const button of document.querySelectorAll('.wk-soundbtn')) {
      button.setAttribute('aria-pressed', String(on));
      button.title = on ? 'Ljudeffekterna är på – tryck för att stänga av dem' : 'Ljudeffekterna är av – tryck för att slå på dem';
    }
  }

  /* Each person has settings of their own, the sounds among them. */
  function syncSound() {
    WK_SOUND.setOn(settings().sound, true);
    soundState();
  }

  /* ── Settings ────────────────────────────────────────────────────────── */

  function setSetting(name, value) {
    if (!(name in DEFAULTS) || !CHOICES[name].includes(value)) return;
    settings()[name] = value;
    saveStore();
  }

  function onSetting(e, el) {
    const name = el.name;
    if (!(name in DEFAULTS)) return;
    if (name === 'sound') { setSound(el.checked); return; }
    const value = el.type === 'checkbox' ? el.checked : typeof DEFAULTS[name] === 'number' ? Number(el.value) : el.value;
    setSetting(name, value);
    renderHome();
  }

  /* ── Keys ────────────────────────────────────────────────────────────── */

  function onKey(e) {
    if (!round || $('fc-practice').hidden || e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey) return;
    const onButton = e.target && e.target.tagName === 'BUTTON';
    const key = e.key.length === 1 ? e.key.toLowerCase() : e.key;
    const mode = round.card && round.card.mode;
    if (round.phase === 'feedback' && !onButton && (key === 'Enter' || key === ' ')) {
      e.preventDefault();
      advance();
    } else if (round.phase === 'answer' && mode === 'vand' && !onButton && (key === 'Enter' || key === ' ')) {
      e.preventDefault();
      flip();
    } else if (round.phase === 'judge' && (key === 'ArrowRight' || key === 'k')) {
      e.preventDefault();
      if (!round.card.hinted) judge(true);
    } else if (round.phase === 'judge' && (key === 'ArrowLeft' || key === 'ö' || key === 'o')) {
      e.preventDefault();
      judge(false);
    } else if (round.phase === 'answer' && mode === 'valj' && /^[1-4]$/.test(key)) {
      e.preventDefault();
      choose(Number(key) - 1);
    } else if (round.phase === 'answer' && (mode === 'skriv' || mode === 'lyssna') && key.length === 1 && /\p{L}/u.test(key)) {
      /* Typing with the answer out of focus puts the letter in it. */
      const input = $('fc-input');
      if (input && document.activeElement !== input) input.focus({ preventScroll: true });
    }
  }

  /* ── Actions ─────────────────────────────────────────────────────────── */

  function registerAll() {
    registerActions({
      'fc:toggle': (e, el) => {
        const id = el.dataset.set;
        if (selected.has(id)) selected.delete(id); else selected.add(id);
        el.setAttribute('aria-pressed', String(selected.has(id)));
        renderSelection();
      },
      'fc:clear': () => { selected.clear(); renderGroups(); renderSelection(); },
      'fc:start': () => startRound(selectedIds()),
      'fc:study': () => showStudy(),
      'fc:print': () => printCards(),
      'fc:full': () => setFull(!document.documentElement.classList.contains('wk-full')),
      'fc:sound': () => setSound(!settings().sound),
      /* A look is each person's own, like their other settings. */
      'fc:look': (e, el) => {
        if (!CARD_LOOKS.valid(el.dataset.look)) return;
        setSetting('look', el.dataset.look);
        renderSettings();
      },
      'fc:setting': onSetting,
      'fc:lang': (e, el) => {
        if (el.dataset.lang === lang()) return;
        setSetting('lang', el.dataset.lang);
        selected.clear();
        closeEditor();
        renderHome();
      },
      'fc:who': (e, el) => {
        if (!store.profiles[el.value]) return;
        store.current = el.value;
        saveStore();
        selected.clear();
        renderHome();
        syncSound();
      },
      'fc:newPerson': () => {
        $('fc-newperson').hidden = false;
        $('fc-newperson-btn').hidden = true;
        $('fc-newname').value = '';
        $('fc-newname').focus();
      },
      'fc:addPerson': () => addPerson(),
      'fc:cancelPerson': () => { $('fc-newperson').hidden = true; $('fc-newperson-btn').hidden = false; $('fc-newperson-btn').focus(); },
      'fc:newNameKey': e => {
        if (e.key === 'Enter') { e.preventDefault(); addPerson(); }
        else if (e.key === 'Escape') { e.preventDefault(); $('fc-newperson').hidden = true; $('fc-newperson-btn').hidden = false; $('fc-newperson-btn').focus(); }
      },
      'fc:resetPerson': (e, el) => {
        const p = profile();
        if (!armed(el, `Tryck igen för att radera allt för ${p.name}`)) return;
        p.facts = Object.create(null);
        saveStore();
        renderHome();
        notifyUser(`Framstegen för ${p.name} är raderade.`, { tone: 'success' });
      },
      'fc:removePerson': (e, el) => {
        const p = profile();
        if (Object.keys(store.profiles).length < 2) return;
        if (!armed(el, `Tryck igen för att ta bort ${p.name}`)) return;
        delete store.profiles[store.current];
        store.current = Object.keys(store.profiles)[0];
        saveStore();
        selected.clear();
        renderHome();
        syncSound();
        notifyUser(`${p.name} är borttagen.`, { tone: 'success' });
      },

      'fc:newList': () => openEditor(null),
      'fc:editList': (e, el) => openEditor(el.dataset.list),
      'fc:closeEditor': () => closeEditor(),
      'fc:listTyped': () => renderListStatus(),
      'fc:saveList': () => saveList(),
      'fc:shareList': (e, el) => shareList(el.dataset.list),
      'fc:deleteList': (e, el) => {
        const l = store.lists.find(x => x.id === el.dataset.list);
        if (!l || !armed(el, 'Tryck igen för att ta bort')) return;
        store.lists = store.lists.filter(x => x !== l);
        selected.delete(l.id);
        saveStore();
        if (editing === l.id) closeEditor();
        renderHome();
        notifyUser(`Listan ${l.name} är borttagen.`, { tone: 'success' });
      },
      'fc:importYes': () => importOffered(),
      'fc:importNo': () => dismissOffer(),

      'fc:answerKey': e => {
        if (e.key !== 'Enter') return;
        e.preventDefault();
        if (round && round.phase === 'answer') submit();
        else advance();
      },
      'fc:submit': () => submit(),
      'fc:choose': (e, el) => choose(Number(el.dataset.i)),
      'fc:accent': (e, el) => accentKey(el.dataset.char),
      'fc:hint': () => showHint(),
      'fc:flip': () => flip(),
      'fc:tapCard': e => {
        if (!round || round.phase !== 'answer' || e.target.closest('button, input')) return;
        if (round.card.mode === 'vand') flip();
        else if ($('fc-input')) $('fc-input').focus({ preventScroll: true });
      },
      /* The front reads out only what the front shows: "ser", not the
         "vosotros sois" of its back, nor the el of "el perro". */
      'fc:say': (e, el) => {
        if (round && round.card) {
          const c = round.card.c;
          say(el.dataset.say === 'front' ? c.front.text : c.say, c.lang);
        }
        const input = $('fc-input');
        if (input && round && round.phase === 'answer') input.focus({ preventScroll: true });
      },
      'fc:sayStudy': (e, el) => { const c = studyCards[Number(el.dataset.i)]; if (c) say(c.say, c.lang); },
      'fc:judge': (e, el) => judge(el.dataset.kan === '1'),
      'fc:pile': (e, el) => {
        if (!round || round.phase !== 'judge') return;
        if (el.dataset.pile === 'kan' && round.card.hinted) return;
        judge(el.dataset.pile === 'kan');
      },
      'fc:next': () => advance(),
      'fc:quit': () => quit(),
      'fc:again': () => { const r = round; startRound(r.ids, r.ova.map(o => o.c)); },
      /* "Dags att repetera" may be empty by now - that is the point of it -
         so the cards just played are the pile to go through again. */
      'fc:repeat': () => {
        const r = round;
        startRound(r.ids, selectedCards(r.ids).length ? null : r.cards.slice());
      },
      'fc:home': () => { round = null; showView('home'); },
    });
  }

  function init() {
    try {
      store = loadStore();
      registerAll();
      document.addEventListener('keydown', onKey);
      /* The page never scrolls as a whole (winnetkakort.css pins it), but an
         iPhone can leave it shifted once its keyboard has closed: put it back
         when no field is being typed in any more. */
      document.addEventListener('focusout', () => setTimeout(() => {
        const field = document.activeElement;
        if (!field || !/^(INPUT|SELECT|TEXTAREA)$/.test(field.tagName)) window.scrollTo(0, 0);
      }, 100));
      if (speech.supported) speechSynthesis.addEventListener('voiceschanged', () => { if (!$('fc-home').hidden) renderSettings(); });
      watchKeyboard();
      fullState();
      CARD_LOOKS.apply(settings().look);
      WK_SOUND.setOn(settings().sound, false);
      soundState();
      /* A browser lets the audio run only after a tap or a key: the first one
         starts it, if sounds are on, and later ones wake it after the browser
         has put it to sleep. */
      for (const type of ['pointerup', 'keydown']) document.addEventListener(type, () => WK_SOUND.unlock(), true);
      showView('home');
      readShared();
    } catch (e) {
      reportFailure('flashcards: init', e, { userMessage: 'Glosorna kunde inte starta.' });
    }
  }

  /* For the tests: the page's own view of its state, read-only. */
  const inspect = () => ({
    keys: round && round.cards.map(c => c.key),
    round: round && {
      phase: round.phase, i: round.i, n: round.cards.length, kan: round.kan.length, ova: round.ova.length,
      mode: round.card && round.card.mode, key: round.card && round.card.c.key, kind: round.card && round.card.c.kind,
      answer: round.card && (round.card.c.kind === 'forms' ? `${round.card.c.past[0]} ${round.card.c.part[0]}` : round.card.c.answer),
      options: round.card && round.card.options, front: round.card && round.card.c.front.text, say: round.card && round.card.c.say,
    },
    status: key => statusOf(key),
    stat: key => statOf(key) || null,
    store: JSON.parse(JSON.stringify(store)),
    sounds: WK_SOUND.log(),
    audio: WK_SOUND.state(),
  });

  return { init, inspect };
})();
