/* ==========================================================================
   BLOCKMODELLEN - THE PAGE (blockmodellen.html)

   Explains the block model (the Singapore model method, as Swedish schools
   teach it) to a pupil of about twelve, and trains it, one step of the
   method at a time:

     1 read the whole problem            5 write in what is known
     2 who or what is it about           6 put the question mark
     3 draw the block or blocks          7 work it out
     4 read it again                     8 answer; is it reasonable?

   A problem is shown in one of five ways, the help fading as the pupil
   goes on:

     demo     a worked example: the page does each step and says why;
     fill     the blocks are drawn, the pupil does the rest (5 to 8);
     guided   the pupil does every step, the page checking each;
     solve    the answer first; drawing the model step by step is help;
     mixed    which model fits, then as solve.

   The problems are in blockmodellen-problems.js, the drawing in
   blockmodellen-draw.js, what is kept between visits in
   blockmodellen-game.js. This file is the page.
   ========================================================================== */

const BM = (() => {
  'use strict';

  const P = BM_PROBLEMS;
  const D = BM_DRAW;
  const G = BM_GAME;
  const KEY = 'blockmodellen.v1';
  const UNITS_CTX = P.UNITS.map(u => ({ id: u.id, lessons: u.lessons.map(l => l.id) }));
  const typeOf = id => P.TYPES.find(t => t.id === id);

  let store = G.blank();
  let dom = {};
  let view = 'home';
  let tab = 'path';
  let run = null;           // the lesson or practice under way
  let play = null;          // the problem on screen
  let clock = null;         // the tests' day
  let seedSeq = null;       // the tests' seeds
  let voice = null;         // a Swedish voice to read aloud with
  let voiceTest = null;     // the tests' stand-in for speechSynthesis
  let askFn = null;
  let lastFinish = null;
  let stageObserver = null;
  let goFn = null;          // what the footer's buttons do now
  let altFn = null;
  let hintFn = null;

  const today = () => clock || G.dayKey(new Date());
  const own = () => (store.settings.name ? { name: store.settings.name, pron: store.settings.pron } : null);

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

  /* A fraction as it is printed: the numerator over the denominator. */
  function fracEl(n, d) {
    return h('span', { class: 'bm-frac', role: 'img', 'aria-label': P.fracWords(n, d) },
      h('span', { class: 'bm-frac-n', text: String(n), 'aria-hidden': 'true' }),
      h('span', { class: 'bm-frac-d', text: String(d), 'aria-hidden': 'true' }));
  }

  /* The page's own markup in its texts: **bold** and [3/5]. */
  function rich(text) {
    const frag = document.createDocumentFragment();
    const re = /\*\*(.+?)\*\*|\[(\d+)\/(\d+)\]/g;
    let at = 0;
    let m;
    while ((m = re.exec(text))) {
      if (m.index > at) frag.append(text.slice(at, m.index));
      if (m[1] !== undefined) frag.append(h('b', {}, rich(m[1])));
      else frag.append(fracEl(Number(m[2]), Number(m[3])));
      at = re.lastIndex;
    }
    if (at < text.length) frag.append(text.slice(at));
    return frag;
  }

  const svgIcon = (body, more) => `<svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"${more || ''}>${body}</svg>`;
  const ICON = {
    star: svgIcon('<path fill="currentColor" stroke-width="1.4" d="M12 2.9l2.8 5.8 6.3.9-4.6 4.4 1.1 6.3L12 17.3l-5.6 3 1.1-6.3L2.9 9.6l6.3-.9z"/>'),
    flame: svgIcon('<path fill="currentColor" stroke-width="1.2" d="M12.4 2.6c.5 3.2 5 5.3 5 10.4a5.4 5.4 0 0 1-10.8 0c0-2 .8-3.5 2-4.7.1 1.5.7 2.5 1.7 3 .1-3.3.7-6.3 2.1-8.7z"/>'),
    check: svgIcon('<path d="M5 12.5l4.5 4.5L19 7.5" stroke-width="2.6"/>'),
    book: svgIcon('<path d="M4 5.5c2.8-1 5.5-.8 8 1 2.5-1.8 5.2-2 8-1v13c-2.8-1-5.5-.8-8 1-2.5-1.8-5.2-2-8-1z"/><path d="M12 6.5v13"/>'),
    steps: svgIcon('<path d="M4 6h3M4 12h3M4 18h3"/><path d="M10 6h10M10 12h10M10 18h10"/>'),
    pencil: svgIcon('<path d="M4 20l1-4.5L16.2 4.3a2 2 0 0 1 2.8 0l.7.7a2 2 0 0 1 0 2.8L8.5 19z"/><path d="M14.5 6l3.5 3.5"/>'),
    target: svgIcon('<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="4.6"/><circle cx="12" cy="12" r="1.2" fill="currentColor"/>'),
    mix: svgIcon('<path d="M3 7h4c5 0 6 10 11 10h3M3 17h4c2 0 3-1.5 4-3.5M15 9.5C16 8 17 7 18 7h3"/><path d="M19 4.5L21.5 7 19 9.5M19 14.5l2.5 2.5-2.5 2.5"/>'),
    flag: svgIcon('<path d="M6 21V4"/><path d="M6 4.5c4-2 7 2 11 0v8c-4 2-7-2-11 0"/>'),
    blocks: svgIcon('<rect x="3" y="5" width="7" height="5" rx="1"/><rect x="10" y="5" width="7" height="5" rx="1"/><rect x="3" y="14" width="7" height="5" rx="1"/><rect x="10" y="14" width="11" height="5" rx="1"/>'),
    trophy: svgIcon('<path d="M7.5 4h9v5.5a4.5 4.5 0 0 1-9 0z"/><path d="M7.5 5.5H4.3c0 3 1.3 4.7 3.7 5M16.5 5.5h3.2c0 3-1.3 4.7-3.7 5M12 14v3.5M8.5 20h7M9.5 17.5h5"/>'),
    bolt: svgIcon('<path fill="currentColor" stroke-width="1.2" d="M13.5 2.5L5 13.5h6l-1.5 8 8.5-11h-6z"/>'),
    map: svgIcon('<path d="M3.5 6.5l5.5-2.5 6 2.5 5.5-2.5v13.5L15 20l-6-2.5-5.5 2.5z"/><path d="M9 4v13.5M15 6.5V20"/>'),
    pie: svgIcon('<path d="M12 3.5a8.5 8.5 0 1 0 8.5 8.5H12z"/><path d="M15 2.8A8.5 8.5 0 0 1 21.2 9H15z" fill="currentColor"/>'),
    speak: svgIcon('<path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z" fill="currentColor" stroke-width="1.4"/><path d="M15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11"/>'),
    print: svgIcon('<path d="M7 9V3.5h10V9"/><rect x="3.5" y="9" width="17" height="8" rx="2"/><path d="M7 14h10v6.5H7z"/>'),
    help: svgIcon('<circle cx="12" cy="12" r="9"/><path d="M9.3 9.3a2.8 2.8 0 0 1 5.4.9c0 1.9-2.7 2.3-2.7 4.1"/><path d="M12 17.3v.2"/>'),
    gear: svgIcon('<circle cx="12" cy="12" r="3"/><path d="M12 2.8v2.4M12 18.8v2.4M2.8 12h2.4M18.8 12h2.4M5.5 5.5l1.7 1.7M16.8 16.8l1.7 1.7M5.5 18.5l1.7-1.7M16.8 7.2l1.7-1.7"/>'),
    arrow: svgIcon('<path d="M5 12h14M13 6l6 6-6 6"/>'),
    plus: svgIcon('<path d="M12 5v14M5 12h14" stroke-width="2.4"/>'),
    minus: svgIcon('<path d="M5 12h14" stroke-width="2.4"/>'),
  };
  const KIND_ICON = { learn: 'book', steps: 'steps', build: 'pencil', solve: 'target', mixed: 'mix' };

  /* The page's friend: a block with two bits, a face and feet. */
  const MASCOT = '<svg viewBox="0 0 120 96" aria-hidden="true">'
    + '<rect class="bm-mz-foot" x="30" y="76" width="16" height="10" rx="4"/><rect class="bm-mz-foot" x="74" y="76" width="16" height="10" rx="4"/>'
    + '<rect class="bm-mz-a" x="10" y="20" width="50" height="58" rx="12"/><rect class="bm-mz-b" x="60" y="20" width="50" height="58" rx="12"/>'
    + '<rect class="bm-mz-a" x="40" y="20" width="22" height="58"/><rect class="bm-mz-b" x="60" y="20" width="22" height="58"/>'
    + '<rect class="bm-mz-line" x="10" y="20" width="100" height="58" rx="12"/><line class="bm-mz-line" x1="60" y1="20" x2="60" y2="78"/>'
    + '<circle cx="44" cy="45" r="8" class="bm-mz-eye"/><circle cx="76" cy="45" r="8" class="bm-mz-eye"/>'
    + '<circle cx="46" cy="46" r="3.6" class="bm-mz-pupil"/><circle cx="78" cy="46" r="3.6" class="bm-mz-pupil"/>'
    + '<path d="M49 60q11 10 22 0" class="bm-mz-mouth"/><circle cx="34" cy="58" r="4" class="bm-mz-cheek"/><circle cx="86" cy="58" r="4" class="bm-mz-cheek"/>'
    + '</svg>';
  const mascot = cls => h('span', { class: `bm-mascot${cls ? ` ${cls}` : ''}` }, (() => { const s = h('span'); s.innerHTML = MASCOT; return s.firstChild; })());

  const RIGHT = ['Rätt!', 'Snyggt!', 'Precis!', 'Ja, det stämmer!', 'Bra!'];
  const praise = () => RIGHT[Math.floor(Math.random() * RIGHT.length)];

  /* What a model is like, said in a hint and when a model is chosen. */
  const TYPE_HINT = {
    delhel: 'Något består av delar som tillsammans är en helhet.',
    jmf: 'Två saker jämförs: vem har mest, och hur mycket mer?',
    lika: 'Allt delas i lika stora delar, eller så läggs många lika stora delar ihop.',
    ggr: 'Någon har ett antal gånger så mycket som någon annan.',
    sumdiff: 'Två tal du inte vet: du vet hur mycket de är tillsammans och hur mycket de skiljer sig.',
    brak: 'Ett bråk av en helhet: nämnaren delar blocket i lika stora bitar.',
    rest: 'Först en del av helheten, sedan en del av det som är kvar.',
    fore: 'Något ändras: hur var det före, och hur är det efter?',
    forh: 'Ett förhållande, som 2 : 3, eller procent: bitar som jämförs.',
  };
  /* How to start drawing a kind, the first hint when answering. */
  const SOLVE_HINT = {
    delhel: 'Rita ett block för helheten och dela det i delarna. Vad vet du, helheten eller delarna?',
    jmf: 'Rita ett block för var och en, under varandra. Den som har mest får det längsta blocket.',
    lika: 'Rita ett block med lika stora bitar, en för varje.',
    ggr: 'Ge den som har minst 1 bit. Hur många lika stora bitar får den andra?',
    sumdiff: 'Rita den minsta som 1 bit och den största som 1 bit och skillnaden. Ta bort skillnaden från summan.',
    brak: 'Nämnaren säger hur många lika stora bitar blocket ska ha, täljaren hur många du markerar.',
    rest: 'Rita först helheten med det första bråket. Resten får ett eget block om det behövs.',
    fore: 'Rita ett block före och ett efter. Vad har ändrats?',
    forh: 'Förhållandet säger hur många lika stora bitar var och en ska ha.',
  };

  /* The cheat sheet's line for each kind. */
  const SHEET = {
    delhel: { pic: ['delhel', 0], when: 'tillsammans, sammanlagt, totalt, kvar, resten', how: 'Vet du delarna: lägg ihop. Vet du helheten och en del: ta bort delen.' },
    jmf: { pic: ['jmf', 0], when: 'fler än, färre än, mer än, mindre än, skillnad', how: 'Blocken börjar på samma ställe. Skillnaden är biten som sticker ut.' },
    lika: { pic: ['lika', 0], when: 'varje, var, per, styck, dela lika', how: 'En bit · antalet bitar = helheten. Helheten / antalet bitar = en bit.' },
    ggr: { pic: ['ggr', 1], when: 'gånger så många, dubbelt så, hälften så', how: 'Räkna bitarna. 4 bitar → 48, då är 1 bit → 12.' },
    sumdiff: { pic: ['sumdiff', 0], when: 'tillsammans … och … mer än', how: 'Ta bort skillnaden, så blir blocken lika långa. Dela sedan.' },
    brak: { pic: ['brak', 2], when: '[3/5] av …', how: 'Nämnaren: så många lika stora bitar. Täljaren: så många markerade.' },
    rest: { pic: ['rest', 0], when: '… av resten', how: 'Rita ett extrablock under resten och dela det i delar.' },
    fore: { pic: ['fore', 0], when: 'från början, sedan, nu, kvar', how: 'Ett block före och ett efter. Leta efter det som är lika.' },
    forh: { pic: ['forh', 0], when: 'förhållandet 2 : 3, procent', how: '2 : 3 är 2 bitar mot 3. Hela blocket är 100 %.' },
  };
  const MISTAKES = [
    '**Svara på rätt sak.** Har du räknat ut 1 bit? Kolla om frågan gäller 1 bit eller flera.',
    '**Fler än är inte gånger.** 17 fler är en bit till, inte dubbelt så långt.',
    '**Låt blocken börja på samma ställe** när du jämför, annars syns inte skillnaden.',
    '**Lika stora bitar ska se lika stora ut.** Annars lurar bilden dig.',
    '**Av vad?** [3/7] av pärlorna är inte samma sak som [3/7] av de blå pärlorna.',
    '**Dela inte summan mitt itu** när blocken är olika långa. Ta först bort skillnaden.',
  ];
  const WORDLIST = [
    ['Helhet', 'allt tillsammans: hela blocket.'],
    ['Del', 'en bit av helheten. Delar kan vara olika stora.'],
    ['Bit', 'en av flera lika stora delar. Alla bitar i en modell är lika stora.'],
    ['Skillnad', 'hur mycket mer det ena är än det andra: biten som sticker ut.'],
    ['Täljare och nämnare', 'i [3/5] är 3 täljaren och 5 nämnaren.'],
    ['Förhållande', '2 : 3 betyder 2 lika stora bitar mot 3.'],
  ];

  /* ── What is kept ─────────────────────────────────────────────────────── */

  function load() {
    try { store = G.validate(JSON.parse(localStorage.getItem(KEY))); } catch (e) { store = G.blank(); }
  }
  function save() {
    try { localStorage.setItem(KEY, JSON.stringify(store)); } catch (e) { /* private mode: kept for this visit */ }
  }

  function newSeed() {
    if (seedSeq !== null) {
      seedSeq = (Math.imul(seedSeq, 1103515245) + 12345) >>> 0;
      return seedSeq || 1;
    }
    try { const a = new Uint32Array(1); crypto.getRandomValues(a); return a[0] || 1; } catch (e) { return Math.floor(Math.random() * 4294967295) || 1; }
  }

  /* What step 2's blocks are, said: one, one each, or one before and one after. */
  function blocksSay(p) {
    const tops = p.rows.filter(rw => !rw.under);
    if (tops.length < 2) return 'Vi ritar ett block.';
    if (p.who.length === 1 && tops.length === 2) return `Vi ritar ett block för ${tops[0].label.toLowerCase()} och ett för ${tops[1].label.toLowerCase()}.`;
    return 'Vi ritar ett block för var och en.';
  }

  /* ── Views ────────────────────────────────────────────────────────────── */

  function show(v) {
    view = v;
    dom.home.hidden = v !== 'home';
    dom.lesson.hidden = v !== 'lesson';
    dom.finish.hidden = v !== 'finish';
    document.documentElement.classList.toggle('bm-deep', v !== 'home');
    dom.content.scrollTop = 0;
  }

  function goHome() {
    stopSpeech();
    run = null;
    play = null;
    show('home');
    renderHome();
  }

  /* ── Home ─────────────────────────────────────────────────────────────── */

  function renderStats() {
    const streak = G.streakNow(store, today());
    const starsN = G.totalStars(store);
    const set = (btn, icon, n, label, lit) => {
      btn.replaceChildren(h('span', { class: 'bm-stat-icon', icon }), h('b', { text: String(n) }), h('span', { class: 'bm-stat-label', text: label }));
      btn.classList.toggle('is-lit', lit);
      btn.setAttribute('aria-label', `${n} ${label}`);
      btn.title = `${n} ${label}`;
    };
    set(dom.statStreak, 'flame', streak, streak === 1 ? 'dag i rad' : 'dagar i rad', streak > 0);
    set(dom.statStars, 'star', starsN, starsN === 1 ? 'stjärna' : 'stjärnor', starsN > 0);
    set(dom.statSolved, 'check', store.solved, store.solved === 1 ? 'löst uppgift' : 'lösta uppgifter', store.solved > 0);
  }

  function renderHome() {
    renderStats();
    for (const b of dom.tabs.querySelectorAll('[role="tab"]')) {
      const on = b.getAttribute('data-tab') === tab;
      b.setAttribute('aria-selected', String(on));
      b.tabIndex = on ? 0 : -1;
    }
    dom.path.hidden = tab !== 'path';
    dom.train.hidden = tab !== 'train';
    dom.sheet.hidden = tab !== 'sheet';
    if (tab === 'path') renderPath();
    if (tab === 'train') renderTrain();
    if (tab === 'sheet') renderSheet();
  }

  /* A kind's small picture: its model without words or numbers. Before
     and after is drawn as a block, an arrow and the block it became. */
  function miniPic(type) {
    const NS = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('class', 'bm-svg bm-mini is-mini');
    svg.setAttribute('aria-hidden', 'true');
    if (type === 'fore') {
      svg.setAttribute('viewBox', '0 0 72 24');
      svg.setAttribute('width', '72');
      svg.setAttribute('height', '24');
      svg.innerHTML = '<g class="bm-row bm-c0"><rect class="bm-pc is-bit" x="2" y="6" width="22" height="14" rx="2.5"/><rect class="bm-outline" x="2" y="6" width="22" height="14" rx="2.5"/></g>'
        + '<path d="M29 13h9M35 9.5l3.5 3.5-3.5 3.5" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>'
        + '<g class="bm-row bm-c0"><rect class="bm-pc is-bit" x="43" y="6" width="22" height="14"/><rect class="bm-pc is-del" x="54" y="6" width="16" height="14"/>'
        + '<line class="bm-div is-del" x1="54" y1="6" x2="54" y2="20"/><rect class="bm-outline" x="43" y="6" width="27" height="14" rx="2.5"/></g>';
      return svg;
    }
    const s = SHEET[type] || SHEET.jmf;
    const card = P.LEARN[s.pic[0]][s.pic[1]];
    D.render(svg, Object.assign({}, card.pic, { mini: true, values: {}, miniTotal: type === 'sumdiff' }), { width: 72 });
    return svg;
  }

  function starsEl(n, max) {
    const box = h('span', { class: 'bm-stars', role: 'img', 'aria-label': `${n} av ${max || 3} stjärnor` });
    for (let i = 0; i < (max || 3); i++) box.append(h('span', { class: `bm-star${i < n ? ' is-on' : ''}`, icon: 'star' }));
    return box;
  }

  function nextLesson() {
    return P.LESSONS.find(l => !store.lessons[l.id]) || null;
  }

  function renderPath() {
    const next = nextLesson();
    const box = h('div', { class: 'bm-units' });
    if (!Object.keys(store.lessons).length) {
      box.append(h('div', { class: 'bm-welcome' },
        mascot(),
        h('div', {},
          h('h2', { text: 'Hej! Här tränar du blockmodellen.' }),
          h('p', { text: 'Börja med Kom igång, eller hoppa till det ni gör i skolan just nu. Varje kapitel har en förklaring, uppgifter där du ritar själv och uppgifter du löser.' }))));
    }
    for (const u of P.UNITS) {
      const done = u.lessons.filter(l => store.lessons[l.id]).length;
      const t = u.type ? typeOf(u.type) : null;
      const list = h('ol', { class: 'bm-lessons' });
      for (const l of u.lessons) {
        const rec = store.lessons[l.id];
        const state = rec ? 'done' : next && next.id === l.id ? 'current' : 'open';
        list.append(h('li', {}, h('button', {
          type: 'button', class: 'bm-node', 'data-state': state, 'data-kind': l.kind,
          'data-on-click': 'bm:lesson', 'data-id': l.id,
        },
        h('span', { class: 'bm-node-dot', icon: rec ? 'check' : KIND_ICON[l.kind] }),
        h('span', { class: 'bm-node-text' },
          h('span', { class: 'bm-node-title', text: l.title }),
          rec ? starsEl(rec.stars) : state === 'current' ? h('span', { class: 'bm-node-go', text: 'Börja här' }) : null))));
      }
      box.append(h('section', { class: 'bm-unit', 'data-unit': u.id },
        h('div', { class: 'bm-unit-head' },
          h('span', { class: 'bm-unit-pic' }, u.type ? miniPic(u.type) : mascot('bm-mascot-mini')),
          h('div', { class: 'bm-unit-text' },
            h('h2', { text: u.title }),
            h('p', { text: u.lead || (t && t.short) || '' })),
          h('span', { class: 'bm-unit-count', text: `${done}/${u.lessons.length}` })),
        list));
    }
    dom.path.replaceChildren(box);
  }

  function renderTrain() {
    const level = store.settings.level;
    const weak = G.weakTypes(store);
    const kids = [
      h('div', { class: 'bm-trainbar' },
        h('p', { text: 'Nya uppgifter varje gång. Välj en sort, eller blanda.' }),
        h('div', { class: 'bm-seg', role: 'radiogroup', 'aria-label': 'Svårighet' },
          h('button', { type: 'button', role: 'radio', 'aria-checked': String(level === 1), 'data-on-click': 'bm:level', 'data-level': '1', text: 'Lättare' }),
          h('button', { type: 'button', role: 'radio', 'aria-checked': String(level === 2), 'data-on-click': 'bm:level', 'data-level': '2', text: 'Alla' }))),
      h('button', { type: 'button', class: 'bm-mixcard', 'data-on-click': 'bm:practice', 'data-type': 'mix' },
        h('span', { class: 'bm-mixcard-icon', icon: 'mix' }),
        h('span', { class: 'bm-mixcard-text' },
          h('b', { text: 'Blandade uppgifter' }),
          h('span', { text: 'Du väljer själv vilken modell som passar. Det är så det blir på proven.' })),
        h('span', { class: 'bm-mixcard-go', icon: 'arrow' })),
    ];
    if (weak.length) {
      kids.push(h('div', { class: 'bm-weak' },
        h('span', { text: 'Öva mer på:' }),
        ...weak.slice(0, 3).map(k => h('button', { type: 'button', class: 'bm-chip', 'data-on-click': 'bm:practice', 'data-type': k, text: typeOf(k).title }))));
    }
    const grid = h('div', { class: 'bm-typegrid' });
    for (const t of P.TYPES) {
      const st = store.types[t.id];
      grid.append(h('div', { class: `bm-type${weak.includes(t.id) ? ' is-weak' : ''}` },
        h('span', { class: 'bm-type-pic' }, miniPic(t.id)),
        h('h3', { text: t.title }),
        h('p', { text: t.short }),
        h('p', { class: 'bm-type-stat', text: st && st.tries ? `${st.right} av ${st.tries} rätt direkt` : 'Inte övat än' }),
        h('button', { type: 'button', class: 'bm-btn bm-btn-quiet', 'data-on-click': 'bm:practice', 'data-type': t.id, text: 'Öva' })));
    }
    kids.push(grid);
    dom.train.replaceChildren(...kids);
  }

  function modelSvg(model, cls, width) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', `bm-svg${cls ? ` ${cls}` : ''}`);
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', D.describe(model));
    svg.__model = model;
    if (width) D.render(svg, model, { width });
    return svg;
  }

  /* Pictures drawn at the width of their box, once it has one, and again
     when it changes. */
  const sized = new Set();
  let fitQueued = false;
  function fitSoon() {
    if (fitQueued) return;
    fitQueued = true;
    requestAnimationFrame(() => { fitQueued = false; fitPictures(); });
  }
  function fitPictures() {
    for (const svg of sized) {
      if (!svg.isConnected) { sized.delete(svg); continue; }
      const box = svg.parentElement;
      const w = Math.floor(box.clientWidth);
      if (w > 0 && w !== svg.__w) { svg.__w = w; D.render(svg, svg.__model, { width: w }); }
    }
  }
  function sizedSvg(model, cls) {
    const svg = modelSvg(model, cls);
    sized.add(svg);
    fitSoon();
    return svg;
  }

  function renderSheet() {
    const steps = h('ol', { class: 'bm-sheet-steps' }, ...P.STEPS.map(s => h('li', {}, h('span', { class: 'bm-stepnum', text: String(s.n) }), h('span', { text: s.title }))));
    const models = h('div', { class: 'bm-sheet-models' });
    for (const t of P.TYPES) {
      const s = SHEET[t.id];
      const card = P.LEARN[s.pic[0]][s.pic[1]];
      models.append(h('section', { class: 'bm-sheet-model' },
        h('h3', { text: t.title }),
        h('div', { class: 'bm-sheet-pic' }, sizedSvg(Object.assign({}, card.pic), 'bm-sheet-svg')),
        h('p', {}, h('b', { text: 'Känn igen: ' }), rich(s.when)),
        h('p', {}, h('b', { text: 'Räkna: ' }), rich(s.how))));
    }
    dom.sheet.replaceChildren(
      h('div', { class: 'bm-sheet-head' },
        h('h2', { text: 'Fusklapp' }),
        h('button', { type: 'button', class: 'bm-btn bm-btn-quiet', 'data-on-click': 'bm:print' }, h('span', { icon: 'print' }), 'Skriv ut')),
      h('section', { class: 'bm-sheet-sec' }, h('h3', { text: 'Arbetsgången' }), steps),
      h('section', { class: 'bm-sheet-sec' }, h('h3', { text: 'Modellerna' }), models),
      h('div', { class: 'bm-sheet-two' },
        h('section', { class: 'bm-sheet-sec' }, h('h3', { text: 'Vanliga misstag' }), h('ul', { class: 'bm-sheet-list' }, ...MISTAKES.map(t => h('li', {}, rich(t))))),
        h('section', { class: 'bm-sheet-sec' }, h('h3', { text: 'Ord att kunna' }), h('dl', { class: 'bm-sheet-words' }, ...WORDLIST.flatMap(([w, d]) => [h('dt', { text: w }), h('dd', {}, rich(d))])))));
  }

  /* ── Lessons and practice ─────────────────────────────────────────────── */

  function startLesson(id) {
    const L = P.lessonById[id];
    if (!L) return;
    const screens = [];
    if (L.cards) for (const c of P.LEARN[L.cards]) screens.push({ kind: 'card', card: c });
    if (L.kind === 'steps') screens.push({ kind: 'order' });
    if (L.demo) screens.push({ kind: 'problem', mode: 'demo', item: L.demo });
    for (const it of L.fill || []) screens.push({ kind: 'problem', mode: 'fill', item: it });
    for (const it of L.items || []) screens.push({ kind: 'problem', mode: L.kind === 'build' ? 'guided' : 'solve', item: it });
    if (L.kind === 'mixed') for (const it of P.mixed(P.rng(newSeed()), L.count, L.level)) screens.push({ kind: 'problem', mode: 'mixed', item: it });
    run = { kind: 'lesson', id, lesson: L, screens, i: 0, items: [], solved: 0, first: 0, problems: 0, steps: null };
    show('lesson');
    showScreen();
  }

  function startPractice(type) {
    const level = store.settings.level;
    const r = P.rng(newSeed());
    let items;
    if (type === 'mix') items = P.mixed(r, 6, level);
    else {
      const tids = P.templatesOf(type, level);
      items = [];
      let last = null;
      while (items.length < 5) {
        const t = r.pick(tids);
        if (t === last && tids.length > 1) continue;
        items.push([t]);
        last = t;
      }
    }
    const screens = items.map(it => ({ kind: 'problem', mode: type === 'mix' ? 'mixed' : 'solve', item: it }));
    run = { kind: 'practice', type, screens, i: 0, items: [], solved: 0, first: 0, problems: 0 };
    show('lesson');
    showScreen();
  }

  function setProgress() {
    const n = run.screens.length;
    const pct = Math.round(100 * run.i / n);
    dom.progressFill.style.width = `${pct}%`;
    dom.progress.setAttribute('aria-valuenow', String(pct));
    const probs = run.screens.filter(s => s.kind === 'problem');
    const k = run.screens.slice(0, run.i + 1).filter(s => s.kind === 'problem').length;
    const sc = run.screens[run.i];
    dom.counter.textContent = sc && sc.kind === 'problem' ? `${k} av ${probs.length}` : '';
    dom.ltitle.textContent = run.kind === 'lesson' ? run.lesson.title : run.type === 'mix' ? 'Blandat' : typeOf(run.type).title;
  }

  function showScreen() {
    stopSpeech();
    play = null;
    setProgress();
    const sc = run.screens[run.i];
    dom.content.scrollTop = 0;
    if (sc.kind === 'card') showCard(sc.card);
    else if (sc.kind === 'order') showOrder();
    else startProblem(sc);
  }

  function nextScreen() {
    run.i++;
    if (run.i >= run.screens.length) finishRun();
    else showScreen();
  }

  function setFoot(o) {
    dom.feedback.textContent = o.text || '';
    dom.feedback.setAttribute('data-state', o.state || '');
    dom.foot.setAttribute('data-state', o.state || '');
    const btn = (b, spec) => {
      b.hidden = !spec;
      if (spec) { b.textContent = spec.label; b.disabled = !!spec.disabled; b.classList.toggle('is-strong', !!spec.strong); }
    };
    btn(dom.go, o.go);
    btn(dom.alt, o.alt);
    btn(dom.hint, o.hint ? { label: 'Ledtråd' } : null);
  }

  /* ── A card that explains ─────────────────────────────────────────────── */

  function showCard(card) {
    const body = h('div', { class: 'bm-cardtext' }, h('h2', { text: card.title }), ...card.text.map(t => h('p', {}, rich(t))));
    if (card.words) body.append(h('p', { class: 'bm-words-head', text: 'Ord som brukar stå i uppgiften:' }), h('ul', { class: 'bm-words' }, ...card.words.map(w => h('li', { text: w }))));
    const kids = [];
    if (card.pic) kids.push(h('div', { class: 'bm-card-pic' }, sizedSvg(Object.assign({}, card.pic), 'bm-card-svg')));
    if (card.steps) kids.push(h('ol', { class: 'bm-card-steps' }, ...P.STEPS.map(s => h('li', {}, h('span', { class: 'bm-stepnum', text: String(s.n) }), h('span', { text: s.title })))));
    if (card.mascot) kids.push(h('div', { class: 'bm-card-pic is-mascot' }, mascot('is-cheer')));
    dom.screen.replaceChildren(h('article', { class: 'bm-card' }, ...kids, body));
    setFoot({ go: { label: 'Nästa', strong: true } });
    goFn = nextScreen;
    altFn = null;
    hintFn = null;
  }

  /* ── The eight steps in order ─────────────────────────────────────────── */

  function showOrder() {
    const order = P.rng(newSeed()).shuffle(P.STEPS.map(s => s.n));
    const st = { next: 1, slips: 0 };
    run.steps = st;
    const placed = h('ol', { class: 'bm-order-done', 'aria-label': 'Stegen i ordning' },
      ...P.STEPS.map(s => h('li', { class: 'bm-order-slot', 'data-n': String(s.n) }, h('span', { class: 'bm-stepnum', text: String(s.n) }), h('span', { class: 'bm-order-text' }))));
    const pool = h('div', { class: 'bm-order-pool' },
      ...order.map(n => h('button', { type: 'button', class: 'bm-order-card', 'data-on-click': 'bm:order', 'data-n': String(n), text: P.STEPS[n - 1].title })));
    dom.screen.replaceChildren(h('div', { class: 'bm-order' },
      h('h2', { text: 'Sätt stegen i rätt ordning' }),
      h('p', { class: 'bm-sub', text: 'Tryck på det steg som kommer först, sedan på nästa, ända till det åttonde.' }),
      placed, pool));
    setFoot({ text: '' });
    goFn = nextScreen;
    altFn = null;
    hintFn = null;
  }

  function orderTap(n) {
    const st = run && run.steps;
    if (!st || st.next > 8) return;
    const card = dom.screen.querySelector(`.bm-order-card[data-n="${n}"]`);
    if (n !== st.next) {
      st.slips++;
      st.wrongHere = true;
      if (card) { card.classList.remove('is-wrong'); void card.offsetWidth; card.classList.add('is-wrong'); }
      const before = P.STEPS[st.next - 2];
      setFoot({ text: st.next === 1 ? 'Inte det. Vad gör du allra först?' : `Inte det. Vad gör du efter ”${before.title.replace(/\.$/, '')}”?`, state: 'bad' });
      return;
    }
    run.items.push({ first: !st.wrongHere });
    st.wrongHere = false;
    const slot = dom.screen.querySelector(`.bm-order-slot[data-n="${n}"]`);
    slot.querySelector('.bm-order-text').textContent = P.STEPS[n - 1].title;
    slot.classList.add('is-done');
    if (card) card.remove();
    st.next++;
    if (st.next > 8) {
      setFoot({ text: st.slips ? 'Alla åtta på plats! Läs dem en gång till högt.' : 'Alla åtta rätt utan ett enda fel!', state: 'good', go: { label: 'Nästa', strong: true } });
    } else {
      setFoot({ text: `${praise()} Steg ${n}.`, state: 'good' });
    }
  }

  /* ── A problem ────────────────────────────────────────────────────────── */

  const STEP_OF = { read: [1], who: [2], build: [3], place: [4, 5], ask: [6], calc: [7], answer: [8] };
  const GUIDED = ['read', 'who', 'build', 'place', 'ask', 'calc', 'answer', 'done'];

  function startProblem(sc) {
    const [tid, seed] = sc.item;
    const p = P.make(tid, seed || newSeed(), own());
    play = {
      p, mode: sc.mode, sc,
      steps: sc.mode === 'fill' ? ['read', 'place', 'ask', 'calc', 'answer', 'done']
        : sc.mode === 'solve' ? ['solve', 'done']
          : sc.mode === 'mixed' ? ['choose', 'solve', 'done']
            : GUIDED.slice(),
      si: 0,
      found: new Set(),
      shape: {},
      sub: 0,
      marks: {},
      committed: {},
      built: false,
      values: {},
      fi: 0,
      ci: 0,
      wrong: 0,
      hints: 0,
      hl: null,
      bad: null,
      helped: false,
      firstAnswer: true,
      scoring: sc.mode !== 'demo',
      counts: sc.mode === 'solve' || sc.mode === 'mixed',
      askedAt: null,
      answered: false,
      calcShown: {},
      choices: sc.mode === 'mixed' ? P.modelChoices(P.rng(newSeed()), p.type) : null,
    };
    if (sc.mode === 'fill') {
      p.who.forEach((_, i) => play.found.add(i));
      play.built = true;
    }
    buildPlayer();
    enterStep();
  }

  const step = () => play.steps[play.si];

  function buildPlayer() {
    const p = play.p;
    dom.pl = {};
    const text = h('p', { class: 'bm-text', id: 'bm-text' });
    const speakBtn = h('button', { type: 'button', class: 'bm-iconbtn bm-speak', 'data-on-click': 'bm:speak', 'aria-label': 'Läs upp uppgiften', title: 'Läs upp uppgiften', icon: 'speak' });
    const stepsEl = h('ol', { class: 'bm-steps', 'aria-label': 'De åtta stegen' },
      ...P.STEPS.map(s => h('li', { 'data-n': String(s.n) }, h('span', { class: 'bm-stepnum', text: String(s.n) }), h('span', { class: 'bm-stepshort', text: s.short }))));
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', 'bm-svg bm-model');
    svg.setAttribute('role', 'img');
    const stage = h('div', { class: 'bm-stage' }, svg);
    const work = h('div', { class: 'bm-work' });
    const head = h('div', { class: 'bm-stephead' }, h('h2', { class: 'bm-steptitle' }), h('p', { class: 'bm-stephelp' }));
    const narr = h('div', { class: 'bm-narr', hidden: true }, mascot('bm-mascot-small'), h('p', { class: 'bm-bubble', 'aria-live': 'polite' }));
    const task = h('div', { class: 'bm-task' },
      h('div', { class: 'bm-taskhead' }, h('span', { class: 'bm-tasklabel', text: play.mode === 'demo' ? 'Exempel' : 'Uppgift' }), speakBtn),
      text);
    dom.screen.replaceChildren(h('div', { class: `bm-player is-${play.mode}`, 'data-type': p.type }, task, stepsEl, head, narr, stage, work));
    Object.assign(dom.pl, { text, speakBtn, stepsEl, svg, stage, work, head, narr, title: head.querySelector('.bm-steptitle'), help: head.querySelector('.bm-stephelp'), bubble: narr.querySelector('.bm-bubble') });
    text.addEventListener('click', onTextTap);
    text.addEventListener('keydown', e => { if ((e.key === 'Enter' || e.key === ' ') && e.target.closest('.bm-w.is-tap')) { e.preventDefault(); onTextTap(e); } });
    svg.addEventListener('click', onSvgTap);
    svg.addEventListener('keydown', e => {
      if ((e.key === 'Enter' || e.key === ' ') && e.target.closest && e.target.closest('[data-slot], [data-piece]')) { e.preventDefault(); onSvgTap(e); }
    });
    if (stageObserver) stageObserver.disconnect();
    if (typeof ResizeObserver !== 'undefined') {
      stageObserver = new ResizeObserver(() => requestAnimationFrame(() => { if (play && dom.pl.stage.clientWidth !== dom.pl.stageW) drawModel(); }));
      stageObserver.observe(stage);
    }
    renderSpeak();
  }

  function renderSpeak() {
    if (!dom.pl || !dom.pl.speakBtn) return;
    dom.pl.speakBtn.hidden = !(store.settings.speech && voice);
  }

  /* The problem's text: words, numbers, fractions, with what has been
     found and placed marked in it. */
  function renderText() {
    const p = play.p;
    const s0 = step();
    const box = dom.pl.text;
    box.replaceChildren();
    box.classList.toggle('is-who', s0 === 'who');
    const curSentence = s0 === 'place' && play.fi < p.facts.length ? p.facts[play.fi].s : s0 === 'ask' ? p.q : -1;
    p.text.forEach((sent, si) => {
      const se = h('span', { class: `bm-sent${si === curSentence ? ' is-cur' : ''}`, 'data-s': String(si) });
      sent.forEach((tok, ti) => {
        if (tok.t === 'p') { se.append(tok.s); return; }
        if (se.childNodes.length) se.append(' ');
        if (tok.t === 'f') { se.append(fracEl(tok.n, tok.d)); return; }
        if (tok.t === 'n') {
          const placed = tok.fact !== undefined && (play.built && (play.fi > tok.fact || step() === 'done' || play.answered));
          const cur = tok.fact !== undefined && s0 === 'place' && play.fi === tok.fact;
          se.append(h('span', { class: `bm-num${placed ? ' is-placed' : ''}${cur ? ' is-cur' : ''}`, text: P.fmt(tok.v) }));
          return;
        }
        const cls = ['bm-w'];
        if (tok.who !== undefined && play.found.has(tok.who)) {
          const row = P.rowOf(p, p.who[tok.who].rows[0]);
          cls.push('is-found', `bm-tc${row ? row.color : 0}`);
        }
        if (s0 === 'who') cls.push('is-tap');
        if (play.pulseWho !== undefined && tok.who === play.pulseWho) cls.push('is-pulse');
        const attrs = { class: cls.join(' '), 'data-s': String(si), 'data-t': String(ti), text: tok.s };
        if (s0 === 'who') { attrs.role = 'button'; attrs.tabindex = '0'; }
        se.append(h('span', attrs));
      });
      if (si > 0) box.append(' ');
      box.append(se);
    });
  }

  function renderSteps() {
    const s0 = step();
    const hidden = play.steps.includes('solve') && !play.helped;
    dom.pl.stepsEl.hidden = hidden || s0 === 'choose';
    const now = STEP_OF[s0] || [];
    const order = GUIDED.slice(0, -1);
    const at = order.indexOf(s0);
    for (const li of dom.pl.stepsEl.children) {
      const n = Number(li.getAttribute('data-n'));
      const isNow = now.includes(n);
      const before = s0 === 'done' || (at >= 0 && order.slice(0, at).some(k => STEP_OF[k].includes(n)));
      li.classList.toggle('is-now', isNow);
      li.classList.toggle('is-done', before && !isNow);
      if (isNow) li.setAttribute('aria-current', 'step'); else li.removeAttribute('aria-current');
    }
  }

  /* The rows the pupil has drawn so far. */
  function visibleRows() {
    const p = play.p;
    if (play.built) return p.rows.map(rw => rw.key);
    const keys = new Set();
    play.found.forEach(i => p.who[i].rows.forEach(k => keys.add(k)));
    if (step() === 'build' || step() === 'done') {
      p.build.slice(0, play.sub + 1).forEach(sub => { if (sub.do === 'shape') Object.keys(sub.rows).forEach(k => keys.add(k)); });
    }
    return p.rows.filter(rw => keys.has(rw.key)).map(rw => rw.key);
  }

  function modelNow() {
    const p = play.p;
    if (play.built) {
      return {
        rows: p.rows, groups: p.groups, values: play.values,
        targets: play.mode !== 'demo' && ((step() === 'place' && play.fi < p.facts.length) || (step() === 'ask' && !play.askedAt)),
        hl: play.hl, bad: play.bad, answer: play.answered ? canonAsk() : null,
      };
    }
    const sub = step() === 'build' ? p.build[play.sub] : null;
    const rows = visibleRows().map(k => {
      const rw = P.rowOf(p, k);
      const sh = play.shape[k] || { bits: 1, x: 0 };
      const marked = play.marks[k] || new Set();
      const done = Object.keys(play.committed).map(id => p.groups.find(g => g.id === id)).filter(g => g && g.row === k && g.mark);
      const pieces = [];
      for (let i = 0; i < sh.bits; i++) pieces.push({ k: 'bit', w: 1, marked: marked.has(i) || done.some(g => g.pieces.includes(i)) });
      for (let i = 0; i < sh.x; i++) pieces.push({ k: 'del', w: 0.55 });
      return { key: k, label: rw.label, color: rw.color, pieces, under: rw.under };
    });
    const shown = new Set(rows.map(rw => rw.key));
    const groups = p.groups.filter(g => shown.has(g.row) && (play.committed[g.id] || (g.link && shown.has(g.link))));
    return { rows, groups, values: {}, schematic: true, markRow: sub && sub.do === 'mark' ? sub.row : null };
  }

  function drawModel() {
    if (!play) return;
    const m = modelNow();
    const visible = m.rows.length > 0 && !(step() === 'solve' || step() === 'choose') || (play.answered && play.steps.includes('solve'));
    dom.pl.stage.hidden = !visible;
    if (!visible) return;
    const cs = getComputedStyle(dom.pl.stage);
    const w = Math.floor(dom.pl.stage.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight));
    dom.pl.stageW = dom.pl.stage.clientWidth;
    const focused = document.activeElement && dom.pl.svg.contains(document.activeElement)
      ? document.activeElement.getAttribute('data-slot') || document.activeElement.getAttribute('data-piece') : null;
    play.layout = D.render(dom.pl.svg, m, { width: Math.max(260, w), slots: m.targets, slotName: id => P.slotNoun(play.p, id) });
    if (focused) {
      const again = dom.pl.svg.querySelector(`[data-slot="${focused}"], [data-piece="${focused}"]`);
      if (again) again.focus({ preventScroll: true });
    }
    dom.pl.svg.setAttribute('aria-label', `Modellen. ${D.describe(m)}`);
    dom.pl.svg.classList.toggle('is-marking', !!m.markRow);
    dom.pl.svg.classList.toggle('is-targets', !!m.targets);
  }

  function setHead(title, helpText) {
    dom.pl.title.textContent = title;
    dom.pl.help.replaceChildren();
    if (helpText) dom.pl.help.append(typeof helpText === 'string' ? rich(helpText) : helpText);
    dom.pl.help.hidden = !helpText;
  }

  function narrate(text) {
    dom.pl.narr.hidden = !text;
    dom.pl.bubble.replaceChildren(text ? rich(text) : '');
  }

  function itemDone() {
    if (play.scoring && run) run.items.push({ first: play.wrong === 0 && play.hints === 0 });
    play.wrong = 0;
    play.hints = 0;
    play.hl = null;
    play.pulseWho = undefined;
  }

  function enterStep() {
    const p = play.p;
    const s0 = step();
    const demo = play.mode === 'demo';
    play.wrong = 0;
    play.hints = 0;
    play.hl = null;
    play.bad = null;
    narrate('');
    renderText();
    renderSteps();
    dom.pl.work.replaceChildren();
    const stepTitle = n => `${n}. ${P.STEPS[n - 1].title}`;
    switch (s0) {
      case 'choose': {
        setHead('Vilken modell passar?', 'Läs uppgiften och välj den sortens modell du skulle rita.');
        dom.pl.work.append(h('div', { class: 'bm-choices' }, ...play.choices.map(t => h('button', {
          type: 'button', class: 'bm-choice', 'data-on-click': 'bm:choose', 'data-type': t,
        }, h('span', { class: 'bm-choice-pic' }, miniPic(t)), h('span', { class: 'bm-choice-title', text: typeOf(t).title })))));
        setFoot({ hint: true });
        hintFn = () => {
          play.hints++;
          if (play.hints === 1) setFoot({ text: 'Fråga dig: är det delar av något, en jämförelse, lika stora bitar, ett bråk, eller något som ändras?', hint: true });
          else { setFoot({ text: TYPE_HINT[p.type], hint: true }); }
        };
        goFn = null;
        break;
      }
      case 'read':
        setHead(stepTitle(1), demo ? null : 'Läs hela uppgiften. Vad handlar den om, och vad är frågan?');
        if (demo) {
          narrate('Först läser vi hela uppgiften, från början till slut. Vad är det som händer, och vad är frågan?');
          setFoot({ go: { label: 'Nästa steg', strong: true } });
        } else setFoot({ go: { label: 'Jag har läst', strong: true } });
        goFn = () => nextStep();
        hintFn = null;
        break;
      case 'who':
        setHead(stepTitle(2), demo ? null : 'Tryck på orden i texten som säger vem eller vad uppgiften handlar om.');
        if (demo) {
          p.who.forEach((_, i) => play.found.add(i));
          renderText();
          narrate(`Uppgiften handlar om ${P.joinAnd(p.who.map(w => w.label))}. ${blocksSay(p)}`);
          setFoot({ go: { label: 'Nästa steg', strong: true } });
          goFn = () => nextStep();
        } else {
          renderWho();
          setFoot({ hint: true });
          goFn = null;
          hintFn = () => {
            play.hints++;
            const left = p.who.map((_, i) => i).filter(i => !play.found.has(i));
            if (play.hints === 1) setFoot({ text: p.who.length > 1 ? `Det finns ${p.who.length} att hitta. Vem eller vad har ett tal i uppgiften?` : 'Vem eller vad räknar vi på? Leta efter det som talen handlar om.', hint: true });
            else { play.pulseWho = left[0]; renderText(); setFoot({ text: 'Titta på ordet som blinkar.', hint: true }); }
          };
        }
        break;
      case 'build':
        play.sub = 0;
        enterSub();
        return;
      case 'place':
        enterPlace();
        return;
      case 'ask':
        setHead(stepTitle(6), demo ? null : 'Läs frågan. Tryck där frågetecknet ska stå i modellen.');
        if (demo) {
          play.askedAt = canonAsk();
          play.values[play.askedAt] = '?';
          narrate(`Frågan är: ${P.plain(p.text[p.q])} Frågetecknet sätter vi ${P.slotAt(p, p.ask.slot)}.`);
          setFoot({ go: { label: 'Nästa steg', strong: true } });
          goFn = () => nextStep();
        } else {
          setFoot({ hint: true });
          goFn = null;
          hintFn = () => {
            play.hints++;
            if (play.hints === 1) setFoot({ text: 'Vad ska du ta reda på? Är det ett helt block, en bit, flera bitar eller alla blocken tillsammans?', hint: true });
            else { play.hl = canonAsk(); drawModel(); setFoot({ text: 'Där det lyser.', hint: true }); }
          };
        }
        break;
      case 'calc':
        enterCalc();
        return;
      case 'answer':
        enterAnswer();
        return;
      case 'solve':
        enterSolve();
        return;
      case 'done':
        enterDone();
        return;
      default:
        break;
    }
    drawModel();
  }

  function nextStep() {
    play.si++;
    enterStep();
  }

  /* Step 2: the words that say who or what. */
  function renderWho() {
    const p = play.p;
    const found = [...play.found].map(i => p.who[i].label);
    dom.pl.work.replaceChildren(h('p', { class: 'bm-found' },
      found.length ? `Hittat: ${P.joinAnd(found)}` : `Hittat: ${'–'}`,
      p.who.length > 1 ? h('span', { class: 'bm-found-n', text: ` (${found.length} av ${p.who.length})` }) : null));
  }

  function onTextTap(e) {
    if (!play || step() !== 'who' || play.mode === 'demo') return;
    const el = e.target.closest ? e.target.closest('.bm-w') : null;
    if (!el) {
      const num = e.target.closest ? e.target.closest('.bm-num, .bm-frac') : null;
      if (num) { play.wrong++; setFoot({ text: 'Det är ett tal. Vem eller vad handlar talet om?', state: 'bad', hint: true }); }
      return;
    }
    const tok = play.p.text[Number(el.getAttribute('data-s'))][Number(el.getAttribute('data-t'))];
    whoTap(tok, el);
  }

  function whoTap(tok, el) {
    const p = play.p;
    if (tok.who !== undefined) {
      if (play.found.has(tok.who)) { setFoot({ text: 'Den har du redan hittat. Finns det fler?', hint: true }); return; }
      play.found.add(tok.who);
      play.pulseWho = undefined;
      renderText();
      renderWho();
      drawModel();
      if (play.found.size === p.who.length) {
        itemDone();
        setFoot({ text: `${praise()} Uppgiften handlar om ${P.joinAnd(p.who.map(w => w.label))}. ${blocksSay(p)}`, state: 'good', go: { label: 'Nästa', strong: true } });
        goFn = () => nextStep();
      } else {
        setFoot({ text: `Ja, ${p.who[tok.who].label}! Det finns ${p.who.length - play.found.size === 1 ? 'en sak' : 'fler'} till att hitta.`, state: 'good', hint: true });
      }
      return;
    }
    play.wrong++;
    if (el) { el.classList.remove('is-wrong'); void el.offsetWidth; el.classList.add('is-wrong'); }
    setFoot({ text: `Nja, ”${tok.s}” är inte det uppgiften handlar om. Vem har något, eller vad är det talen räknar?`, state: 'bad', hint: true });
  }

  /* Step 3: the blocks, one sub-step at a time. */
  function enterSub() {
    const p = play.p;
    const sub = p.build[play.sub];
    const demo = play.mode === 'demo';
    play.wrong = 0;
    play.hints = 0;
    play.badRow = null;
    const title = `3. ${P.STEPS[2].title}`;
    if (sub.do === 'shape') {
      for (const k of Object.keys(sub.rows)) if (!play.shape[k]) play.shape[k] = { bits: 1, x: 0 };
      if (demo) {
        for (const [k, want] of Object.entries(sub.rows)) {
          const rw = P.rowOf(p, k);
          play.shape[k] = want.n !== undefined
            ? { bits: rw.pieces.filter(pc => pc.k === 'bit').length, x: rw.pieces.filter(pc => pc.k === 'del').length }
            : { bits: want.bits, x: want.x || 0 };
        }
        setHead(title, null);
        narrate(sub.why);
        dom.pl.work.replaceChildren();
        setFoot({ go: { label: 'Nästa steg', strong: true } });
        goFn = () => subDone();
      } else {
        setHead(title, sub.ask || 'Ge varje block rätt antal bitar. **Lika stora bitar** är lika mycket. En **annan bit** har en egen storlek, som en skillnad eller en del.');
        renderShapeControls(sub);
        setFoot({ go: { label: 'Kolla' }, hint: true });
        goFn = () => checkSub();
        hintFn = () => {
          play.hints++;
          const res = P.checkShape(p, sub, play.shape);
          if (play.hints === 1) setFoot({ text: res.ok ? 'Det ser bra ut! Tryck på Kolla.' : res.msg, hint: true, go: { label: 'Kolla' } });
          else setFoot({ text: sub.why, hint: true, go: { label: 'Kolla' } });
        };
      }
    } else {
      play.marks[sub.row] = new Set();
      if (demo) {
        const g = p.groups.find(gr => gr.id === sub.group);
        play.committed[sub.group] = true;
        setHead(title, null);
        narrate(sub.why);
        dom.pl.work.replaceChildren();
        setFoot({ go: { label: 'Nästa steg', strong: true } });
        goFn = () => subDone();
        void g;
      } else {
        setHead(title, sub.ask || 'Tryck på bitarna som ska markeras.');
        renderMarkCount(sub);
        setFoot({ go: { label: 'Kolla' }, hint: true });
        goFn = () => checkSub();
        hintFn = () => {
          play.hints++;
          if (play.hints === 1) setFoot({ text: sub.msg, hint: true, go: { label: 'Kolla' } });
          else setFoot({ text: sub.why, hint: true, go: { label: 'Kolla' } });
        };
      }
    }
    renderText();
    renderSteps();
    drawModel();
  }

  function renderShapeControls(sub) {
    const p = play.p;
    const list = h('div', { class: 'bm-shapes' });
    for (const k of Object.keys(sub.rows)) {
      const rw = P.rowOf(p, k);
      const sh = play.shape[k];
      const stepper = (kind, n, label, min, max) => h('div', { class: 'bm-stepper' },
        h('span', { class: 'bm-stepper-label', text: label }),
        h('button', { type: 'button', class: 'bm-stepbtn', 'data-on-click': 'bm:shape', 'data-row': k, 'data-kind': kind, 'data-d': '-1', 'aria-label': `${label}: en färre`, disabled: n <= min ? true : null, icon: 'minus' }),
        h('output', { class: 'bm-stepper-n', text: String(n), 'aria-live': 'polite' }),
        h('button', { type: 'button', class: 'bm-stepbtn', 'data-on-click': 'bm:shape', 'data-row': k, 'data-kind': kind, 'data-d': '1', 'aria-label': `${label}: en till`, disabled: n >= max ? true : null, icon: 'plus' }));
      list.append(h('div', { class: `bm-shape bm-c${rw.color}${play.badRow === k ? ' is-bad' : ''}`, 'data-row': k },
        h('span', { class: 'bm-shape-name', text: rw.label }),
        stepper('bits', sh.bits, rw.under ? 'Lika stora delar' : 'Lika stora bitar', 1, 10),
        rw.under ? null : stepper('x', sh.x, 'Annan bit', 0, 2)));
    }
    dom.pl.work.replaceChildren(list);
  }

  function shapeStep(k, kind, d) {
    if (!play || step() !== 'build') return;
    const sub = play.p.build[play.sub];
    if (sub.do !== 'shape' || !sub.rows[k]) return;
    const sh = play.shape[k];
    sh[kind] = Math.max(kind === 'bits' ? 1 : 0, Math.min(kind === 'bits' ? 10 : 2, sh[kind] + d));
    play.badRow = null;
    renderShapeControls(sub);
    drawModel();
    // The buttons were drawn anew: the focus goes back to the one pressed, or
    // to its other half when that one can go no further.
    const at = sel => dom.pl.work.querySelector(sel);
    const b = at(`.bm-stepbtn[data-row="${k}"][data-kind="${kind}"][data-d="${d}"]`);
    const other = at(`.bm-stepbtn[data-row="${k}"][data-kind="${kind}"][data-d="${-d}"]`);
    if (b && !b.disabled) b.focus({ preventScroll: true });
    else if (other) other.focus({ preventScroll: true });
  }

  function renderMarkCount(sub) {
    const n = (play.marks[sub.row] || new Set()).size;
    dom.pl.work.replaceChildren(h('p', { class: 'bm-found' }, `Markerade: ${n}`, h('span', { class: 'bm-found-n', text: '  Tryck en gång till för att ta bort en markering.' })));
  }

  function onSvgTap(e) {
    if (!play) return;
    const t = e.target;
    const piece = t.closest ? t.closest('[data-piece]') : null;
    if (piece && step() === 'build') { markTap(piece.getAttribute('data-piece')); return; }
    const slot = t.closest ? t.closest('[data-slot]') : null;
    if (slot && (step() === 'place' || step() === 'ask')) slotTap(slot.getAttribute('data-slot'));
  }

  function markTap(pid) {
    const sub = play.p.build[play.sub];
    if (!sub || sub.do !== 'mark') return;
    const [k, j] = pid.split('.');
    if (k !== sub.row) return;
    const i = Number(j);
    const taken = Object.keys(play.committed).map(id => play.p.groups.find(g => g.id === id)).some(g => g && g.row === k && g.mark && g.pieces.includes(i));
    if (taken) { setFoot({ text: 'Den biten är redan markerad för något annat.', hint: true, go: { label: 'Kolla' } }); return; }
    const set = play.marks[k] || (play.marks[k] = new Set());
    if (set.has(i)) set.delete(i); else set.add(i);
    renderMarkCount(sub);
    drawModel();
  }

  function checkSub() {
    const p = play.p;
    const sub = p.build[play.sub];
    const res = sub.do === 'shape' ? P.checkShape(p, sub, play.shape) : P.checkMark(p, sub, (play.marks[sub.row] || new Set()).size);
    if (!res.ok) {
      play.wrong++;
      play.badRow = res.row || null;
      if (sub.do === 'shape') renderShapeControls(sub);
      setFoot({ text: `Inte riktigt. ${res.msg}`, state: 'bad', go: { label: 'Kolla' }, hint: true });
      return;
    }
    itemDone();
    if (sub.do === 'mark') { play.committed[sub.group] = true; play.marks[sub.row] = new Set(); }
    setFoot({ text: `${praise()} ${sub.why}`, state: 'good', go: { label: 'Nästa', strong: true } });
    goFn = () => subDone();
    dom.pl.work.replaceChildren();
    drawModel();
  }

  function subDone() {
    const p = play.p;
    play.sub++;
    if (play.sub < p.build.length) { enterSub(); return; }
    play.built = true;
    if (play.mode !== 'demo' && play.scoring) play.builtAlone = true;
    nextStep();
  }

  /* Steps 4 and 5: read again, and write in each number. */
  function enterPlace(said) {
    const p = play.p;
    const demo = play.mode === 'demo';
    if (play.fi >= p.facts.length) { nextStep(); return; }
    const f = p.facts[play.fi];
    play.wrong = 0;
    play.hints = 0;
    play.hl = null;
    play.bad = null;
    setHead(`${play.fi === 0 ? '4–5' : '5'}. Läs igen och skriv in det du vet`, demo ? null : `Var ska **${P.fmt(f.v)}** stå? Tryck på rätt ställe i modellen.`);
    renderText();
    renderSteps();
    if (demo) {
      play.values[placeOf(f)] = P.fmt(f.v);
      narrate(`${P.plain(p.text[f.s])} Vi skriver ${P.fmt(f.v)} ${P.slotAt(p, f.slot)}.`);
      setFoot({ go: { label: 'Nästa steg', strong: true } });
      goFn = () => { play.fi++; enterPlace(); };
    } else {
      setFoot(said ? { text: said, state: 'good', hint: true } : { hint: true });
      goFn = null;
      hintFn = () => {
        play.hints++;
        if (play.hints === 1) setFoot({ text: f.hint || `Läs meningen som lyser. Vad är ${P.fmt(f.v)}: ett helt block, en bit, flera bitar eller alla blocken tillsammans?`, hint: true });
        else { play.hl = placeOf(f); drawModel(); setFoot({ text: `${P.fmt(f.v)} ska stå där det lyser.`, hint: true }); }
      };
    }
    drawModel();
  }

  /* Where a fact is drawn: its place's one name ('A.bit': the first bit). */
  function placeOf(f) {
    const p = play.p;
    if (/\.bit$/.test(f.slot)) {
      const row = P.rowOf(p, f.slot[0]);
      return row.pieces.length === 1 ? row.key : `${row.key}.${row.pieces.findIndex(pc => pc.k === 'bit')}`;
    }
    return drawnSlot(f.slot);
  }
  /* The name a place has in the drawing: a group of one piece is that
     piece, a group of a whole row is the row. */
  function drawnSlot(id) {
    const c = P.canon(play.p, id);
    return /\[/.test(c) ? id : c;
  }
  /* Where the question mark stands: where the pupil put it, or else its
     place's one name ('A.bit': the first bit). */
  const canonAsk = () => play.askedAt || placeOf(play.p.ask);

  function slotTap(sid) {
    const p = play.p;
    if (play.mode === 'demo') return;
    if (step() === 'place') {
      const f = p.facts[play.fi];
      if (!f) return;
      if (P.sameSlot(p, f.slot, sid)) {
        play.values[sid] = P.fmt(f.v);
        play.bad = null;
        itemDone();
        play.fi++;
        renderText();
        const where = P.slotNoun(p, sid);
        if (play.fi < p.facts.length) {
          enterPlace(`${praise()} ${P.fmt(f.v)} är ${where}.`);
        } else {
          setFoot({ text: `${praise()} ${P.fmt(f.v)} är ${where}.`, state: 'good', go: { label: 'Nästa', strong: true } });
          goFn = () => nextStep();
          play.hl = null;
          drawModel();
        }
        return;
      }
      wrongSlot(sid, () => placeOf(f), f.hint || `Läs meningen igen: vad är ${P.fmt(f.v)}?`);
      return;
    }
    if (step() === 'ask') {
      if (play.askedAt) return;
      if (P.sameSlot(p, p.ask.slot, sid)) {
        play.values[sid] = '?';
        play.askedAt = sid;
        play.bad = null;
        itemDone();
        setFoot({ text: `${praise()} Vi söker ${P.slotNoun(p, sid)}.`, state: 'good', go: { label: 'Nästa', strong: true } });
        goFn = () => nextStep();
        drawModel();
        return;
      }
      wrongSlot(sid, canonAsk, 'Läs frågan igen. Vad ska du ta reda på?');
    }
  }

  function wrongSlot(sid, where, hint) {
    const p = play.p;
    play.wrong++;
    play.bad = sid;
    const has = play.values[sid];
    let text = has !== undefined ? `Där står redan ${has}. ` : `Inte där, det är ${P.slotNoun(p, sid)}. `;
    text += hint;
    if (play.wrong >= 2) { play.hl = where(); text += ' Titta där det lyser.'; }
    setFoot({ text, state: 'bad', hint: true });
    drawModel();
    setTimeout(() => { if (play && play.bad === sid) { play.bad = null; drawModel(); } }, 900);
  }

  /* Step 7: the lines of working, one at a time. */
  function enterCalc() {
    const p = play.p;
    const demo = play.mode === 'demo';
    setHead(`7. ${P.STEPS[6].title}`, demo ? null : 'Använd modellen. Skriv in vad varje rad blir.');
    if (play.ci === 0) while (play.ci < p.calc.length && p.calc[play.ci].given) play.ci++;
    renderCalc();
    if (demo) {
      play.ci = p.calc.length;
      renderCalc();
      narrate(`Nu räknar vi med hjälp av bilden. ${p.calc.map(l => (l.given ? `${l.left} är ${P.fmt(l.v)}.` : `${l.left}: ${l.show} = ${P.fmt(l.v)}.`)).join(' ')}`);
      setFoot({ go: { label: 'Nästa steg', strong: true } });
      goFn = () => nextStep();
    } else {
      setFoot({ go: { label: 'Kolla' }, hint: true });
      goFn = () => checkCalc();
      hintFn = () => {
        play.hints++;
        const ln = p.calc[play.ci];
        if (!ln) return;
        if (play.hints === 1) setFoot({ text: ln.hint || 'Titta på modellen. Vad vet du redan?', hint: true, go: { label: 'Kolla' } });
        else { play.calcShown[play.ci] = true; renderCalc(); setFoot({ text: `Räkna ${ln.show}.`, hint: true, go: { label: 'Kolla' } }); }
      };
      focusInput();
    }
    drawModel();
  }

  function renderCalc() {
    const p = play.p;
    const list = h('div', { class: 'bm-calc' });
    p.calc.forEach((ln, i) => {
      if (i > play.ci) return;
      const done = i < play.ci || ln.given;
      const row = h('div', { class: `bm-cline${ln.given ? ' is-given' : ''}${done ? ' is-done' : ' is-now'}` },
        h('span', { class: 'bm-cleft', text: ln.left }),
        h('span', { class: 'bm-carrow', text: '→', 'aria-hidden': 'true' }));
      if (done) {
        if (!ln.given) row.append(h('span', { class: 'bm-cshow', text: `${ln.show} =` }));
        row.append(h('span', { class: 'bm-cval', text: P.fmt(ln.v) }));
      } else {
        if (play.calcShown[i]) row.append(h('span', { class: 'bm-cshow', text: `${ln.show} =` }));
        const inp = h('input', { type: 'text', class: 'bm-input', inputmode: 'numeric', autocomplete: 'off', 'aria-label': `${ln.left}: skriv vad det blir`, 'data-line': String(i), spellcheck: 'false' });
        inp.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); checkCalc(); } });
        row.append(inp);
      }
      list.append(row);
    });
    dom.pl.work.replaceChildren(list);
  }

  function focusInput() {
    const inp = dom.pl.work.querySelector('input.bm-input');
    if (inp && matchMedia('(pointer: fine)').matches) inp.focus({ preventScroll: true });
  }

  function checkCalc() {
    const p = play.p;
    const ln = p.calc[play.ci];
    if (!ln) return;
    const inp = dom.pl.work.querySelector(`input[data-line="${play.ci}"]`);
    const val = P.parseNumber(inp ? inp.value : '');
    if (val === null) { setFoot({ text: 'Skriv ett tal.', go: { label: 'Kolla' }, hint: true }); return; }
    if (val === ln.v) {
      itemDone();
      play.ci++;
      while (play.ci < p.calc.length && p.calc[play.ci].given) play.ci++;
      renderCalc();
      if (play.ci >= p.calc.length) {
        setFoot({ text: `${praise()} Nu har du räknat klart.`, state: 'good', go: { label: 'Nästa', strong: true } });
        goFn = () => nextStep();
      } else {
        setFoot({ text: `${praise()} Nästa rad.`, state: 'good', go: { label: 'Kolla' }, hint: true });
        goFn = () => checkCalc();
        focusInput();
      }
      return;
    }
    play.wrong++;
    if (play.wrong >= 3) {
      play.calcShown[play.ci] = true;
      setFoot({ text: `Det blir ${ln.show} = ${P.fmt(ln.v)}. Skriv in det och gå vidare.`, state: 'bad', go: { label: 'Kolla' }, hint: true });
      renderCalc();
      focusInput();
      return;
    }
    if (play.wrong === 2) { play.calcShown[play.ci] = true; renderCalc(); focusInput(); }
    setFoot({ text: play.wrong === 1 ? `Inte riktigt. ${ln.hint || 'Titta på modellen igen.'}` : `Inte riktigt. Räkna ${ln.show}.`, state: 'bad', go: { label: 'Kolla' }, hint: true });
  }

  /* Step 8: the answer, in a sentence. */
  function answerLine(withInput) {
    const p = play.p;
    const a = p.answer;
    const kids = [h('b', { class: 'bm-answer-lead', text: 'Svar: ' })];
    if (a.pre) kids.push(`${a.pre} `);
    if (withInput) {
      const inp = h('input', { type: 'text', class: 'bm-input bm-answer-input', inputmode: 'numeric', autocomplete: 'off', 'aria-label': 'Svaret', spellcheck: 'false' });
      inp.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); if (goFn) goFn(); } });
      kids.push(inp);
    } else kids.push(h('b', { class: 'bm-answer-val', text: P.fmt(a.v) }));
    kids.push(` ${a.post}`);
    return h('p', { class: 'bm-answer' }, ...kids);
  }

  function enterAnswer() {
    const p = play.p;
    const demo = play.mode === 'demo';
    setHead(`8. ${P.STEPS[7].title}`, demo ? null : 'Skriv svaret i meningen. Titta var frågetecknet står.');
    if (demo) {
      play.answered = true;
      play.values[canonAsk()] = P.fmt(p.answer.v);
      dom.pl.work.replaceChildren(answerLine(false), h('p', { class: 'bm-check', text: p.check }));
      narrate(`Frågetecknet blev ${P.fmt(p.answer.v)}. Är det rimligt? ${p.check}`);
      setFoot({ go: { label: 'Nästa', strong: true } });
      goFn = () => nextStep();
      drawModel();
      return;
    }
    dom.pl.work.replaceChildren(calcSummary(), answerLine(true));
    setFoot({ go: { label: 'Kolla' }, hint: true });
    goFn = () => checkAnswer();
    hintFn = () => {
      play.hints++;
      if (play.hints === 1) setFoot({ text: 'Läs frågan igen. Vilket av talen du har räknat ut svarar på den?', hint: true, go: { label: 'Kolla' } });
      else setFoot({ text: 'Titta var frågetecknet står i modellen. Hur mycket är det?', hint: true, go: { label: 'Kolla' } });
    };
    drawModel();
    focusInput();
  }

  function calcSummary() {
    const p = play.p;
    return h('div', { class: 'bm-calc is-summary' }, ...p.calc.map(ln => h('div', { class: 'bm-cline is-done' },
      h('span', { class: 'bm-cleft', text: ln.left }), h('span', { class: 'bm-carrow', text: '→', 'aria-hidden': 'true' }),
      ln.given ? null : h('span', { class: 'bm-cshow', text: `${ln.show} =` }), h('span', { class: 'bm-cval', text: P.fmt(ln.v) }))));
  }

  function readAnswer() {
    const inp = dom.pl.work.querySelector('input.bm-answer-input');
    return P.parseNumber(inp ? inp.value : '');
  }

  function trapFor(val) {
    const t = play.p.answer.traps || {};
    return t[String(val)] || null;
  }

  function checkAnswer() {
    const p = play.p;
    const val = readAnswer();
    if (val === null) { setFoot({ text: 'Skriv ett tal i svaret.', go: { label: 'Kolla' }, hint: true }); return; }
    if (val === p.answer.v) {
      itemDone();
      answeredRight();
      return;
    }
    play.wrong++;
    const trap = trapFor(val);
    if (play.wrong >= 3) {
      setFoot({ text: `Svaret är ${P.fmt(p.answer.v)}. ${trap || ''} Skriv in det, så går vi vidare.`, state: 'bad', go: { label: 'Kolla' } });
      return;
    }
    setFoot({ text: `Inte riktigt. ${trap || 'Läs frågan igen och titta var frågetecknet står i modellen.'}`, state: 'bad', go: { label: 'Kolla' }, hint: true });
  }

  /* The answer is right: the question mark becomes the answer, the
     problem counts as solved, and the check is shown. */
  function answeredRight() {
    const p = play.p;
    play.answered = true;
    play.values[canonAsk()] = P.fmt(p.answer.v);
    const counts = play.counts;
    const first = counts && play.firstAnswer && !play.helped;
    const res = G.solved(store, today(), { type: p.type, counts, first, built: !!play.builtAlone && play.mode === 'guided' }, { units: UNITS_CTX });
    if (run) { run.problems++; run.solved++; if (first) run.first++; run.badges = (run.badges || []).concat(res.badges); }
    save();
    renderStats();
    dom.pl.work.replaceChildren(calcSummary(), answerLine(false), h('p', { class: 'bm-check' }, h('span', { icon: 'check' }), p.check));
    dom.pl.help.hidden = true;
    setFoot({ text: `${praise()} ${p.answer.pre ? `${p.answer.pre} ${P.fmt(p.answer.v)} ${p.answer.post}` : `${P.fmt(p.answer.v)} ${p.answer.post}`}`, state: 'good', go: { label: run && run.i + 1 >= run.screens.length ? 'Klar' : 'Nästa uppgift', strong: true } });
    goFn = () => nextScreen();
    hintFn = null;
    altFn = null;
    renderText();
    drawModel();
    const mz = dom.screen.querySelector('.bm-mascot');
    if (mz) mz.classList.add('is-cheer');
  }

  /* Answer first; drawing the model is the help. */
  function enterSolve() {
    const p = play.p;
    setHead('Lös uppgiften', play.mode === 'mixed' ? `Modellen: ${typeOf(p.type).title}. Rita gärna på papper, och skriv svaret i meningen.` : 'Rita gärna modellen på papper. Skriv svaret i meningen.');
    dom.pl.work.replaceChildren(answerLine(true));
    setFoot({ go: { label: 'Kolla' }, alt: { label: 'Rita modellen' }, hint: true });
    goFn = () => checkSolve();
    altFn = () => startHelp();
    hintFn = () => {
      play.hints++;
      play.firstAnswer = false;
      if (play.hints === 1) setFoot({ text: SOLVE_HINT[p.type], hint: true, go: { label: 'Kolla' }, alt: { label: 'Rita modellen' } });
      else setFoot({ text: 'Tryck på Rita modellen, så går vi igenom stegen tillsammans.', hint: true, go: { label: 'Kolla' }, alt: { label: 'Rita modellen', strong: true } });
    };
    renderSteps();
    drawModel();
    focusInput();
  }

  function checkSolve() {
    const p = play.p;
    const val = readAnswer();
    if (val === null) { setFoot({ text: 'Skriv ett tal i svaret.', go: { label: 'Kolla' }, alt: { label: 'Rita modellen' }, hint: true }); return; }
    if (val === p.answer.v) {
      if (run) run.items.push({ first: play.firstAnswer && play.wrong === 0 });
      if (play.wrong) play.firstAnswer = false;
      solvedShowModel();
      return;
    }
    play.wrong++;
    play.firstAnswer = false;
    const trap = trapFor(val);
    if (play.wrong >= 3) {
      if (run) run.items.push({ first: false });
      setFoot({ text: `Svaret är ${P.fmt(p.answer.v)}. Så här ser modellen ut.`, state: 'bad' });
      solvedShowModel(true);
      return;
    }
    setFoot({ text: `Inte riktigt. ${trap || (play.wrong === 1 ? 'Försök igen, eller rita modellen.' : 'Rita modellen, steg för steg. Det brukar hjälpa.')}`, state: 'bad', go: { label: 'Kolla' }, alt: { label: 'Rita modellen', strong: play.wrong >= 2 }, hint: true });
  }

  /* The answer is in (or given): the whole model is drawn as it would be
     on paper, with the working under it. */
  function solvedShowModel(given) {
    const p = play.p;
    play.helped = play.helped || !!given;
    play.built = true;
    p.who.forEach((_, i) => play.found.add(i));
    for (const f of p.facts) play.values[placeOf(f)] = P.fmt(f.v);
    play.si = play.steps.indexOf('done') - 1;
    if (given) {
      play.answered = true;
      play.values[canonAsk()] = P.fmt(p.answer.v);
      const res = G.solved(store, today(), { type: p.type, counts: true, first: false }, { units: UNITS_CTX });
      if (run) { run.problems++; run.solved++; run.badges = (run.badges || []).concat(res.badges); }
      save();
      renderStats();
      dom.pl.work.replaceChildren(h('p', { class: 'bm-sub', text: 'Så här kan modellen se ut:' }), calcSummary(), answerLine(false), h('p', { class: 'bm-check', text: p.check }));
      renderText();
      dom.pl.stage.hidden = false;
      drawModel();
      setFoot({ text: `Svaret är ${P.fmt(p.answer.v)}. Titta på modellen och räkningen, så går det bättre nästa gång.`, state: 'bad', go: { label: run && run.i + 1 >= run.screens.length ? 'Klar' : 'Nästa uppgift', strong: true } });
      goFn = () => nextScreen();
      altFn = null;
      return;
    }
    answeredRight();
    dom.pl.work.prepend(h('p', { class: 'bm-sub', text: 'Så här kan modellen se ut:' }));
  }

  /* "Rita modellen": the steps from 2, then the answer. */
  function startHelp() {
    play.helped = true;
    play.firstAnswer = false;
    play.scoring = false;
    play.steps = ['who', 'build', 'place', 'ask', 'calc', 'answer', 'done'];
    play.si = 0;
    play.found = new Set();
    play.shape = {};
    play.sub = 0;
    play.marks = {};
    play.committed = {};
    play.built = false;
    play.values = {};
    play.fi = 0;
    play.ci = 0;
    play.askedAt = null;
    play.calcShown = {};
    altFn = null;
    if (run) run.items.push({ first: false });
    enterStep();
  }

  function chooseModel(type) {
    const p = play.p;
    if (step() !== 'choose') return;
    const btn = dom.pl.work.querySelector(`.bm-choice[data-type="${type}"]`);
    if (type === p.type) {
      if (run) run.items.push({ first: play.wrong === 0 && play.hints === 0 });
      if (btn) btn.classList.add('is-right');
      setFoot({ text: `${praise()} ${typeOf(type).title}: ${TYPE_HINT[type]}`, state: 'good', go: { label: 'Nästa', strong: true } });
      goFn = () => nextStep();
      for (const b of dom.pl.work.querySelectorAll('.bm-choice')) b.disabled = true;
      return;
    }
    play.wrong++;
    if (btn) { btn.classList.add('is-wrong'); btn.disabled = true; }
    const msg = play.wrong >= 2 ? `${TYPE_HINT[p.type]}` : 'Inte den. Läs uppgiften igen: vad är det som händer?';
    setFoot({ text: msg, state: 'bad', hint: true });
  }

  function enterDone() {
    nextScreen();
  }

  /* ── The end of a lesson ──────────────────────────────────────────────── */

  function finishRun() {
    const r = run;
    const n = r.items.length;
    const firstN = r.items.filter(it => it.first).length;
    const acc = n ? firstN / n : 1;
    let out = { kind: r.kind, items: n, first: firstN, problems: r.problems, badges: (r.badges || []).slice() };
    if (r.kind === 'lesson') {
      const res = G.finishLesson(store, r.id, acc, today(), {
        steps: r.lesson.kind === 'steps' && r.steps && r.steps.slips === 0,
        mixed: r.lesson.kind === 'mixed',
      }, { units: UNITS_CTX });
      out = Object.assign(out, res, { badges: out.badges.concat(res.badges), id: r.id, title: r.lesson.title });
    } else {
      G.touch(store, today());
      out.title = r.type === 'mix' ? 'Blandat' : typeOf(r.type).title;
      out.type = r.type;
    }
    save();
    lastFinish = out;
    renderFinish(out);
    show('finish');
  }

  function renderFinish(f) {
    const kids = [h('div', { class: 'bm-confetti', 'aria-hidden': 'true' }, ...Array.from({ length: 26 }, (_, i) => {
      const c = h('i');
      c.style.setProperty('--x', `${(i * 37) % 100}%`);
      c.style.setProperty('--d', `${(i % 9) * 0.12}s`);
      c.style.setProperty('--r', `${(i * 47) % 360}deg`);
      return c;
    }))];
    kids.push(mascot('is-cheer'));
    kids.push(h('h2', { text: f.kind === 'lesson' ? (f.stars === 3 ? 'Toppen!' : 'Bra jobbat!') : 'Bra tränat!' }));
    kids.push(h('p', { class: 'bm-finish-sub', text: f.title }));
    if (f.kind === 'lesson') {
      const st = h('div', { class: 'bm-finish-stars', role: 'img', 'aria-label': `${f.stars} av 3 stjärnor` });
      for (let i = 0; i < 3; i++) {
        const s = h('span', { class: `bm-star${i < f.stars ? ' is-on' : ''}`, icon: 'star' });
        s.style.setProperty('--k', String(i));
        st.append(s);
      }
      kids.push(st);
    }
    const tiles = h('div', { class: 'bm-finish-tiles' });
    if (f.items) tiles.append(h('div', { class: 'bm-tile' }, h('span', { class: 'bm-tile-big', text: `${f.first}/${f.items}` }), h('small', { text: 'rätt på första försöket' })));
    const streak = G.streakNow(store, today());
    tiles.append(h('div', { class: `bm-tile${f.streak && f.streak.grew ? ' is-new' : ''}` }, h('span', { class: 'bm-tile-big', text: String(streak) }), h('small', { text: streak === 1 ? 'dag i rad' : 'dagar i rad' })));
    if (f.problems) tiles.append(h('div', { class: 'bm-tile' }, h('span', { class: 'bm-tile-big', text: String(f.problems) }), h('small', { text: f.problems === 1 ? 'löst uppgift' : 'lösta uppgifter' })));
    kids.push(tiles);
    if (f.kind === 'lesson' && f.best > f.stars) kids.push(h('p', { class: 'bm-finish-note', text: `Ditt bästa på den här lektionen är ${f.best} stjärnor.` }));
    if (f.badges.length) {
      kids.push(h('p', { class: 'bm-finish-note', text: f.badges.length === 1 ? 'Nytt märke!' : 'Nya märken!' }));
      kids.push(h('div', { class: 'bm-finish-badges' }, ...f.badges.map(b => badgeEl(b, true, true))));
    }
    const btns = h('div', { class: 'bm-finish-btns' });
    btns.append(h('button', { type: 'button', class: 'bm-btn bm-btn-quiet', 'data-on-click': 'bm:again', text: 'Igen' }));
    const nx = nextLesson();
    if (f.kind === 'lesson' && nx && nx.id !== f.id) btns.append(h('button', { type: 'button', class: 'bm-btn bm-btn-go', 'data-on-click': 'bm:lesson', 'data-id': nx.id, text: `Nästa: ${nx.title}` }));
    btns.append(h('button', { type: 'button', class: 'bm-btn bm-btn-quiet', 'data-on-click': 'bm:home', text: 'Till start' }));
    kids.push(btns);
    dom.finish.replaceChildren(...kids);
  }

  function badgeEl(b, got, fresh) {
    return h('div', { class: `bm-badge${got ? ' is-got' : ''}${fresh ? ' is-new' : ''}` },
      h('span', { class: 'bm-badge-mark', icon: b.icon }),
      h('b', { text: b.title }),
      h('small', { text: got ? (store.badges[b.id] ? `Fick ${store.badges[b.id]}` : '') : b.how }));
  }

  /* ── Dialogs ──────────────────────────────────────────────────────────── */

  function openDialog(d) {
    if (typeof d.showModal === 'function') { if (!d.open) d.showModal(); } else d.setAttribute('open', '');
  }
  function closeDialogs() {
    for (const d of document.querySelectorAll('.bm-dialog[open]')) { if (typeof d.close === 'function') d.close(); else d.removeAttribute('open'); }
  }

  function renderBadges() {
    const streak = G.streakNow(store, today());
    const got = Object.keys(store.badges).length;
    dom.badgeBody.replaceChildren(
      h('div', { class: 'bm-summary' },
        h('div', { class: 'bm-tile' }, h('span', { class: 'bm-tile-big', text: String(streak) }), h('small', { text: `dagar i rad (bästa: ${store.streak.best})` })),
        h('div', { class: 'bm-tile' }, h('span', { class: 'bm-tile-big', text: String(G.totalStars(store)) }), h('small', { text: 'stjärnor' })),
        h('div', { class: 'bm-tile' }, h('span', { class: 'bm-tile-big', text: String(store.solved) }), h('small', { text: 'lösta uppgifter' }))),
      h('h3', { text: `Märken (${got} av ${G.BADGES.length})` }),
      h('div', { class: 'bm-badgegrid' }, ...G.BADGES.map(b => badgeEl(b, !!store.badges[b.id], false))));
  }

  function renderSettings() {
    const s = store.settings;
    dom.setName.value = s.name;
    for (const r of document.querySelectorAll('input[name="bm-pron"]')) r.checked = r.value === s.pron;
    dom.setSpeech.checked = s.speech;
    dom.speechNote.textContent = voice ? '' : 'Den här webbläsaren har ingen svensk röst, så knappen syns inte.';
  }

  function setting(e, el) {
    const s = store.settings;
    const name = el.getAttribute('name');
    if (name === 'bm-name') s.name = G.cleanName(el.value);
    else if (name === 'bm-pron') s.pron = el.value;
    else if (name === 'bm-speech') { s.speech = el.checked; renderSpeak(); }
    save();
  }

  function ask(title, text, yes, no, fn) {
    dom.askTitle.textContent = title;
    dom.askText.textContent = text;
    dom.askYes.textContent = yes;
    dom.askNo.textContent = no;
    askFn = fn;
    openDialog(dom.ask);
  }

  /* ── Reading aloud ────────────────────────────────────────────────────── */

  function speechApi() { return voiceTest || (typeof speechSynthesis !== 'undefined' ? speechSynthesis : null); }

  function pickVoice() {
    const api = speechApi();
    if (!api || typeof api.getVoices !== 'function') { voice = null; return; }
    const voices = api.getVoices() || [];
    voice = voices.find(v => /^sv[-_]SE/i.test(v.lang)) || voices.find(v => /^sv\b/i.test(v.lang)) || null;
    renderSpeak();
    if (dom.setSpeech && document.querySelector('#bm-settings[open]')) renderSettings();
  }

  function speak() {
    const api = speechApi();
    if (!api || !play || !voice) return;
    api.cancel();
    const u = new SpeechSynthesisUtterance(P.plainText(play.p, true));
    try { u.voice = voice; } catch (e) { /* a voice the browser did not make: the language will do */ }
    u.lang = voice.lang;
    u.rate = 0.92;
    api.speak(u);
  }
  function stopSpeech() {
    const api = speechApi();
    try { if (api) api.cancel(); } catch (e) { /* nothing to stop */ }
  }

  /* ── Actions ──────────────────────────────────────────────────────────── */

  const actions = {
    'bm:tab': (e, el) => { tab = el.getAttribute('data-tab'); renderHome(); },
    'bm:lesson': (e, el) => { closeDialogs(); startLesson(el.getAttribute('data-id')); },
    'bm:practice': (e, el) => startPractice(el.getAttribute('data-type')),
    'bm:level': (e, el) => { store.settings.level = Number(el.getAttribute('data-level')) === 2 ? 2 : 1; save(); renderTrain(); },
    'bm:quit': () => goHome(),
    'bm:go': () => { if (goFn) goFn(); },
    'bm:alt': () => { if (altFn) altFn(); },
    'bm:hint': () => { if (hintFn) hintFn(); },
    'bm:speak': () => speak(),
    'bm:shape': (e, el) => shapeStep(el.getAttribute('data-row'), el.getAttribute('data-kind'), Number(el.getAttribute('data-d'))),
    'bm:choose': (e, el) => chooseModel(el.getAttribute('data-type')),
    'bm:order': (e, el) => orderTap(Number(el.getAttribute('data-n'))),
    'bm:help': () => openDialog(dom.help),
    'bm:settings': () => { renderSettings(); openDialog(dom.settings); },
    'bm:badges': () => { renderBadges(); openDialog(dom.badges); },
    'bm:close': () => closeDialogs(),
    'bm:setting': setting,
    'bm:reset': () => ask('Börja om från början?', 'Alla stjärnor, märken och dagar i rad tas bort. Namnet och inställningarna finns kvar.', 'Börja om', 'Avbryt', () => {
      const settings = store.settings;
      store = G.blank();
      store.settings = settings;
      save();
      closeDialogs();
      goHome();
    }),
    'bm:askYes': () => { const fn = askFn; askFn = null; if (dom.ask.open) dom.ask.close(); if (fn) fn(); },
    'bm:askNo': () => { askFn = null; if (dom.ask.open) dom.ask.close(); },
    'bm:print': () => { tab = 'sheet'; renderHome(); setTimeout(() => window.print(), 50); },
    'bm:again': () => {
      if (!lastFinish) return;
      if (lastFinish.kind === 'lesson') startLesson(lastFinish.id);
      else startPractice(lastFinish.type);
    },
    'bm:home': () => goHome(),
  };

  /* ── Start-up ─────────────────────────────────────────────────────────── */

  function init() {
    const id = x => document.getElementById(x);
    dom = {
      content: document.querySelector('.bm-content'),
      home: id('bm-home'), lesson: id('bm-lesson'), finish: id('bm-finish'),
      tabs: id('bm-tabs'), path: id('bm-path'), train: id('bm-train'), sheet: id('bm-sheet'),
      statStreak: id('bm-stat-streak'), statStars: id('bm-stat-stars'), statSolved: id('bm-stat-solved'),
      progress: id('bm-progress'), progressFill: id('bm-progress-fill'), counter: id('bm-counter'), ltitle: id('bm-ltitle'),
      screen: id('bm-screen'), foot: id('bm-foot'), feedback: id('bm-feedback'), go: id('bm-go'), alt: id('bm-alt'), hint: id('bm-hint'),
      help: id('bm-help'), settings: id('bm-settings'), badges: id('bm-badges'), badgeBody: id('bm-badge-body'),
      ask: id('bm-ask'), askTitle: id('bm-ask-title'), askText: id('bm-ask-text'), askYes: id('bm-ask-yes'), askNo: id('bm-ask-no'),
      setName: id('bm-set-name'), setSpeech: id('bm-set-speech'), speechNote: id('bm-speech-note'),
    };
    load();
    registerActions(actions);
    show('home');
    renderHome();
    for (const d of document.querySelectorAll('.bm-dialog')) {
      d.addEventListener('click', e => { if (e.target === d && typeof d.close === 'function') d.close(); });
    }
    document.addEventListener('keydown', e => {
      if (view !== 'home' || e.target.closest('input, textarea, select')) return;
      const tabsEl = e.target.closest('[role="tablist"]');
      if (tabsEl && (e.key === 'ArrowRight' || e.key === 'ArrowLeft')) {
        const order = ['path', 'train', 'sheet'];
        tab = order[(order.indexOf(tab) + (e.key === 'ArrowRight' ? 1 : 2)) % 3];
        renderHome();
        const b = dom.tabs.querySelector(`[data-tab="${tab}"]`);
        if (b) b.focus();
      }
    });
    if (typeof ResizeObserver !== 'undefined') new ResizeObserver(fitSoon).observe(dom.content);
    window.addEventListener('resize', fitSoon);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => { for (const s of sized) s.__w = 0; fitPictures(); if (play) drawModel(); });
    const api = speechApi();
    if (api) {
      pickVoice();
      if (typeof api.addEventListener === 'function') api.addEventListener('voiceschanged', pickVoice);
    }
    window.addEventListener('pagehide', stopSpeech);
    window.addEventListener('afterprint', () => { for (const s of sized) s.__w = 0; fitPictures(); });
    window.addEventListener('beforeprint', () => { for (const s of sized) { s.__w = 0; } });
  }

  /* ── For the tests ────────────────────────────────────────────────────── */

  function inspect() {
    const p = play && play.p;
    return JSON.parse(JSON.stringify({
      view, tab,
      run: run && { kind: run.kind, id: run.id || null, type: run.type || null, i: run.i, count: run.screens.length, screens: run.screens.map(s => s.kind === 'problem' ? `${s.mode}:${s.item[0]}` : s.kind), items: run.items, solved: run.solved },
      play: play && {
        mode: play.mode, step: step(), steps: play.steps, tid: p.tid, type: p.type, seed: p.seed,
        text: P.plainText(p), answer: p.answer.v, found: [...play.found], who: p.who.length,
        whoTokens: p.text.flatMap((sent, s) => sent.map((tk, t) => (tk.who !== undefined ? { s, t, who: tk.who, w: tk.s } : null)).filter(Boolean)),
        shape: play.shape, sub: play.sub, built: play.built, values: play.values, fi: play.fi, ci: play.ci,
        facts: p.facts.map(f => ({ v: f.v, slot: f.slot, at: placeOf(f) })), ask: canonAsk(),
        build: p.build, calc: p.calc.map(l => ({ v: l.v, given: !!l.given })), answered: play.answered,
        helped: play.helped, firstAnswer: play.firstAnswer, choices: play.choices, marks: Object.fromEntries(Object.entries(play.marks).map(([k, s]) => [k, [...s]])),
        committed: Object.keys(play.committed), slots: play.layout ? play.layout.slots.map(s => s.id) : [],
      },
      feedback: dom.feedback.textContent,
      feedbackState: dom.feedback.getAttribute('data-state'),
      go: dom.go.hidden ? null : dom.go.textContent,
      alt: dom.alt.hidden ? null : dom.alt.textContent,
      hint: !dom.hint.hidden,
      finish: lastFinish,
      store: { solved: store.solved, lessons: store.lessons, types: store.types, badges: Object.keys(store.badges), streak: store.streak, run: store.run, flags: store.flags, settings: store.settings },
      next: (nextLesson() || {}).id || null,
      voice: voice ? voice.lang : null,
    }));
  }

  const test = {
    today(day) { clock = day || null; if (view === 'home') renderHome(); },
    seed(n) { seedSeq = n === null || n === undefined ? null : (n >>> 0); },
    /* A stand-in for speechSynthesis: { getVoices, speak, cancel, addEventListener }. */
    speech(api) { voiceTest = api || null; pickVoice(); },
    reload() { load(); goHome(); },
    /* Every step of the problem on screen done right, as the pupil would. */
    model: () => (play ? modelNow() : null),
  };

  return { init, inspect, test };
})();
