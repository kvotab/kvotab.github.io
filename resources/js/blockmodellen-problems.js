/* ==========================================================================
   BLOCKMODELLEN - THE PROBLEMS (blockmodellen.html)

   Word problems for the block model, the Singapore model method as Swedish
   schools teach it, made from templates with numbers drawn at random, so
   that there is always a new one. Nothing here touches the page, so all of
   it can be tested in Node (resources/tests/blockmodellen).

   A problem is

     text     sentences, each a list of tokens: words { t: 'w', s }, numbers
              { t: 'n', v }, fractions { t: 'f', n, d } and punctuation
              { t: 'p', s }. A word that says who or what the problem is
              about carries `who` (an index into who); a number that is to
              be written into the model carries `fact` (an index into facts).
     who      what step 2 looks for, { rows, label }: finding it puts those
              rows into the model.
     rows     the model as it is drawn when done: { key, label, pieces,
              under, ref }. A piece is { k: 'bit' | 'del', w, name }: bits
              are the equal units (every bit of a model is the same size), a
              del is a part with a size of its own; w is the true value, for
              drawing to scale. A row `under` another lies beneath some of
              that row's pieces (the extra block of "a fraction of the rest").
     groups   named runs of pieces in one row, { id, row, pieces, label,
              mark }: mark - the pupil marks them (a fraction's numerator).
     build    step 3, in sub-steps: { do: 'shape', rows: { A: { bits, x } }
              } (x: other bits; { n } instead: any n pieces) or { do:
              'mark', row, group, count }.
     facts    step 5, { s, v, slot }: the number v of sentence s belongs at
              slot.
     ask      step 6, { slot }: where the question mark goes.
     calc     step 7, lines { left, show, v, given }.
     answer   step 8, { pre, v, post, traps }.

   A slot is a place where a number can be written: 'A' the whole of row A,
   'A.1' its second piece, 'A.bit' any one of its bits, 'A:g' a group, 'T'
   all rows together. A place can have two names (a row of one piece is
   that piece), and canon() gives each place one.

   The numbers come out whole, every time: each template draws what the
   answer is made of first and builds the rest from it, and gives up (null)
   on a draw that would be ambiguous, so make() tries the next seed.
   ========================================================================== */

const BM_PROBLEMS = (() => {
  'use strict';

  /* ── Random numbers that can be repeated ──────────────────────────────── */

  function rng(seed) {
    let a = (seed >>> 0) || 1;
    function next() {
      a = (a + 0x6D2B79F5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    }
    const int = (lo, hi) => lo + Math.floor(next() * (hi - lo + 1));
    return {
      next, int,
      pick: arr => arr[Math.floor(next() * arr.length)],
      /* a multiple of st between lo and hi */
      step: (lo, hi, st) => st * int(Math.ceil(lo / st), Math.floor(hi / st)),
      chance: p => next() < p,
      shuffle(arr) {
        const out = arr.slice();
        for (let i = out.length - 1; i > 0; i--) {
          const j = Math.floor(next() * (i + 1));
          [out[i], out[j]] = [out[j], out[i]];
        }
        return out;
      },
    };
  }

  /* ── Swedish ──────────────────────────────────────────────────────────── */

  const NBSP = ' ';
  const MINUS = '−';
  const DOT = '·';

  /* 1200 -> "1 200", the space unbreakable */
  function fmt(n) {
    const s = String(Math.abs(n));
    const body = s.length >= 4 ? s.replace(/\B(?=(\d{3})+(?!\d))/g, NBSP) : s;
    return (n < 0 ? MINUS : '') + body;
  }

  /* A template string whose numbers are written the Swedish way. */
  const sv = (strings, ...vals) => strings.reduce((out, str, i) =>
    out + str + (i < vals.length ? (typeof vals[i] === 'number' ? fmt(vals[i]) : String(vals[i])) : ''), '');

  const cap = s => (s ? s[0].toUpperCase() + s.slice(1) : s);
  const WORDS = ['noll', 'en', 'två', 'tre', 'fyra', 'fem', 'sex', 'sju', 'åtta', 'nio', 'tio'];
  const PARTS = {
    3: ['tredjedel', 'tredjedelar'], 4: ['fjärdedel', 'fjärdedelar'], 5: ['femtedel', 'femtedelar'],
    6: ['sjättedel', 'sjättedelar'], 7: ['sjundedel', 'sjundedelar'], 8: ['åttondel', 'åttondelar'],
    9: ['niondel', 'niondelar'], 10: ['tiondel', 'tiondelar'],
  };

  /* 3/5 -> "tre femtedelar", as it is read aloud */
  function fracWords(n, d) {
    if (d === 2) return n === 1 ? 'en halv' : `${WORDS[n] || n} halva`;
    const w = PARTS[d];
    if (!w) return `${n}/${d}`;
    return n === 1 ? `en ${w[0]}` : `${WORDS[n] || n} ${w[1]}`;
  }

  /* "dubbelt så många", "tre gånger så många" */
  const times = k => (k === 2 ? 'dubbelt' : `${WORDS[k]} gånger`);
  const nb = n => (n === 1 ? '1 bit' : `${n} bitar`);
  const nd = n => (n === 1 ? '1 del' : `${n} delar`);
  const possName = n => (/[sxz]$/i.test(n) ? n : `${n}s`);
  const joinAnd = list => (list.length < 2 ? (list[0] || '') : `${list.slice(0, -1).join(', ')} och ${list[list.length - 1]}`);

  const plus = (a, b) => sv`${a} + ${b}`;
  const minus = (a, b) => sv`${a} ${MINUS} ${b}`;
  const mul = (a, b) => sv`${a} ${DOT} ${b}`;
  const div = (a, b) => sv`${a} / ${b}`;

  /* What a pupil types: "1 200", "36 kr", "12,0". Whole numbers and
     decimals; anything else is no number (null). */
  function parseNumber(str) {
    if (typeof str !== 'string') return null;
    let s = str.trim().replace(/[\s   ]/g, '');
    s = s.replace(/(kronor|kr|cm|st|minuter|min|dl|procent|%)\.?$/i, '');
    s = s.replace(/^[−–]/, '-');
    if (!/^-?\d+([.,]\d+)?$/.test(s)) return null;
    return Number(s.replace(',', '.'));
  }

  /* ── People and things ────────────────────────────────────────────────── */

  /* No name ends in s, x or z, so "Ellas" is always the possessive. */
  const GIRLS = ['Ella', 'Moa', 'Alice', 'Maja', 'Elsa', 'Wilma', 'Saga', 'Ebba', 'Nora', 'Alva', 'Selma', 'Vera', 'Juni',
    'Amira', 'Tilde', 'Signe', 'Stella', 'Hanna', 'Sara', 'Lova', 'Freja', 'Leila', 'Nova', 'Elin', 'Tyra', 'Meja'];
  const BOYS = ['Liam', 'Hugo', 'Noah', 'Leo', 'Ali', 'Omar', 'Adam', 'Isak', 'Melvin', 'Otto', 'Viggo', 'Sam', 'Theo',
    'Yusuf', 'Oskar', 'Arvid', 'Albin', 'Elton', 'Malte', 'Kevin', 'Vincent', 'Edvin', 'Ibrahim', 'Milo'];
  const PRON = {
    hon: { he: 'hon', him: 'henne', his: 'hennes' },
    han: { he: 'han', him: 'honom', his: 'hans' },
    hen: { he: 'hen', him: 'hen', his: 'hens' },
  };
  const person = (name, pron, own) => Object.assign({ name, own: !!own }, PRON[pron] || PRON.hen);

  /* n different people; now and then the pupil herself, when she has
     given her name in the settings. */
  function people(r, c, n) {
    const out = [];
    const used = new Set();
    if (c && c.own && r.chance(0.4)) {
      out.push(person(c.own.name, c.own.pron, true));
      used.add(c.own.name.toLowerCase());
    }
    while (out.length < n) {
      const girl = r.chance(0.5);
      const name = r.pick(girl ? GIRLS : BOYS);
      if (used.has(name.toLowerCase())) continue;
      used.add(name.toLowerCase());
      out.push(person(name, girl ? 'hon' : 'han'));
    }
    return out.length > 1 && r.chance(0.5) ? [out[1], out[0], ...out.slice(2)] : out;
  }

  const thing = (en, sg, pl, def) => ({ en, sg, pl, def });
  /* Things to collect and count. */
  const COLLECT = [
    thing('en', 'kula', 'kulor', 'kulorna'),
    thing('en', 'pärla', 'pärlor', 'pärlorna'),
    thing('ett', 'klistermärke', 'klistermärken', 'klistermärkena'),
    thing('ett', 'fotbollskort', 'fotbollskort', 'fotbollskorten'),
    thing('ett', 'frimärke', 'frimärken', 'frimärkena'),
    thing('en', 'snäcka', 'snäckor', 'snäckorna'),
    thing('ett', 'samlarkort', 'samlarkort', 'samlarkorten'),
    thing('en', 'sten', 'stenar', 'stenarna'),
    thing('ett', 'armband', 'armband', 'armbanden'),
  ];
  /* Things to bake or buy by the piece. */
  const BAKED = [
    thing('en', 'bulle', 'bullar', 'bullarna'),
    thing('en', 'muffin', 'muffins', 'muffinsen'),
    thing('en', 'lussekatt', 'lussekatter', 'lussekatterna'),
    thing('en', 'pepparkaka', 'pepparkakor', 'pepparkakorna'),
    thing('en', 'penna', 'pennor', 'pennorna'),
    thing('en', 'ballong', 'ballonger', 'ballongerna'),
    thing('en', 'tulpan', 'tulpaner', 'tulpanerna'),
  ];
  /* Things to buy for money. */
  const GOODS = [
    thing('en', 'bok', 'böcker', 'boken'),
    thing('en', 'tröja', 'tröjor', 'tröjan'),
    thing('en', 'keps', 'kepsar', 'kepsen'),
    thing('ett', 'pussel', 'pussel', 'pusslet'),
    thing('ett', 'brädspel', 'brädspel', 'brädspelet'),
    thing('en', 'mössa', 'mössor', 'mössan'),
  ];

  /* ── Sentences ────────────────────────────────────────────────────────── */

  const w = (s, more) => Object.assign({ t: 'w', s }, more || {});
  const nm = (p, who) => w(p.name, { who });                // "Ella"
  const ps = p => w(possName(p.name));                        // "Ellas"
  const he = (p, who, big) => w(big ? cap(p.he) : p.he, who === undefined ? {} : { who });
  const fr = (n, d) => ({ t: 'f', n, d });
  const tag = (s, who) => w(s, { who });                      // a word naming what it is about

  /*
     A sentence from a template string: S`${nm(A, 0)} har ${12} kulor.`
     Numbers become number tokens, strings words, token objects stay as
     they are. Punctuation at a word's end is a token of its own, so that
     a tap on "kulor." is a tap on "kulor".
  */
  function S(strings, ...vals) {
    const out = [];
    const text = str => {
      for (const chunk of str.split(/\s+/)) {
        if (!chunk) continue;
        if (chunk === ':' || chunk === '%' || chunk === MINUS) { out.push(w(chunk)); continue; }
        const m = /^(.*?)([.,!?;:]*)$/.exec(chunk);
        if (m[1]) out.push(w(m[1]));
        for (const ch of m[2]) out.push({ t: 'p', s: ch });
      }
    };
    strings.forEach((str, i) => {
      text(str);
      if (i >= vals.length) return;
      const v = vals[i];
      if (v === null || v === undefined || v === '') return;
      if (typeof v === 'number') out.push({ t: 'n', v });
      else if (typeof v === 'string') text(v);
      else if (Array.isArray(v)) out.push(...v);
      else out.push(Object.assign({}, v));
    });
    return out;
  }

  /* A sentence as text: on the screen ("3/5", "1 200") or to be read aloud
     ("tre femtedelar"). */
  function plain(sentence, speak) {
    let s = '';
    for (const tok of sentence) {
      const txt = tok.t === 'n' ? (speak ? String(tok.v) : fmt(tok.v))
        : tok.t === 'f' ? (speak ? fracWords(tok.n, tok.d) : `${tok.n}/${tok.d}`)
          : tok.s;
      s += tok.t === 'p' ? txt : (s ? ' ' : '') + txt;
    }
    return s;
  }
  const plainText = (p, speak) => p.text.map(s => plain(s, speak)).join(' ');

  /* ── The parts of a problem ───────────────────────────────────────────── */

  const bit = v => ({ k: 'bit', w: v });
  const del = (v, name) => (name ? { k: 'del', w: v, name } : { k: 'del', w: v });
  const bits = (n, v) => Array.from({ length: n }, () => bit(v));
  const shape = (rows, more) => Object.assign({ do: 'shape', rows }, more || {});
  const mark = (row, group, count, more) => Object.assign({ do: 'mark', row, group, count }, more || {});
  const fact = (s, v, slot, more) => Object.assign({ s, v, slot }, more || {});
  const line = (left, show, v, more) => Object.assign({ left, show, v }, more || {});
  const given = (left, v) => ({ left, v, given: true });
  const group = (id, row, pieces, label, more) => Object.assign({ id, row, pieces, label }, more || {});
  const range = (a, b) => Array.from({ length: b - a + 1 }, (_, i) => a + i);

  /* ── The kinds of model ───────────────────────────────────────────────── */

  const TYPES = [
    { id: 'delhel', title: 'Del och helhet', short: 'Delar som blir en helhet' },
    { id: 'jmf', title: 'Jämförelse', short: 'Fler, färre och skillnad' },
    { id: 'lika', title: 'Lika stora bitar', short: 'Gånger och delat' },
    { id: 'ggr', title: 'Gånger så många', short: 'Bitar som jämförs' },
    { id: 'sumdiff', title: 'Summa och skillnad', short: 'Två tal du inte vet' },
    { id: 'brak', title: 'Bråk', short: 'En del av helheten' },
    { id: 'rest', title: 'Bråk av resten', short: 'Bråk i två steg' },
    { id: 'fore', title: 'Före och efter', short: 'När något ändras' },
    { id: 'forh', title: 'Förhållande och procent', short: 'Bitar i förhållande' },
  ];
  /* Kinds that are drawn so alike that one is no wrong answer for the
     other, when a pupil is asked which model fits. */
  const ALIKE = {
    delhel: ['fore'], fore: ['delhel', 'jmf'], jmf: ['sumdiff', 'fore'], sumdiff: ['jmf'],
    lika: ['ggr', 'forh'], ggr: ['lika', 'forh', 'fore'], forh: ['ggr', 'brak', 'lika'], brak: ['rest', 'forh'], rest: ['brak'],
  };

  /* ── The templates ────────────────────────────────────────────────────── */

  const TEMPLATES = [];
  function T(id, type, level, make) { TEMPLATES.push({ id, type, level, make }); }

  /* Part and whole: the parts are known, the whole is asked for. */
  T('dh-sum', 'delhel', 1, (r, c) => {
    const [A] = people(r, c, 1);
    const kind = r.pick(['read', 'save', 'ski']);
    const a = kind === 'save' ? r.step(60, 320, 5) : r.int(35, 160);
    const b = kind === 'save' ? r.step(50, 300, 5) : r.int(30, 150);
    if (a === b) return null;
    const sum = a + b;
    let text, names, unit, pre, post, whole;
    if (kind === 'read') {
      text = [
        S`${nm(A, 0)} läste ${a} ${tag('sidor', 0)} i en bok på lördagen och ${b} ${tag('sidor', 0)} på söndagen.`,
        S`Hur många sidor läste ${he(A, 0)} sammanlagt?`,
      ];
      names = ['lördag', 'söndag']; unit = ''; pre = `${A.name} läste`; post = 'sidor sammanlagt.'; whole = `Sidorna ${A.name} läste`;
    } else if (kind === 'save') {
      text = [
        S`${nm(A, 0)} sparade ${a} ${tag('kr', 0)} i oktober och ${b} ${tag('kr', 0)} i november.`,
        S`Hur mycket ${tag('pengar', 0)} sparade ${he(A, 0)} sammanlagt?`,
      ];
      names = ['oktober', 'november']; unit = 'kr'; pre = `${A.name} sparade`; post = 'kr sammanlagt.'; whole = `Pengarna ${A.name} sparade`;
    } else {
      text = [
        S`${nm(A, 0)} åkte skidor i ${a} ${tag('minuter', 0)} på förmiddagen och i ${b} ${tag('minuter', 0)} på eftermiddagen.`,
        S`Hur många minuter åkte ${he(A, 0)} skidor sammanlagt?`,
      ];
      names = ['förmiddag', 'eftermiddag']; unit = 'min'; pre = `${A.name} åkte skidor i`; post = 'minuter sammanlagt.'; whole = `Tiden ${A.name} åkte skidor`;
    }
    return {
      text, unit,
      who: [{ rows: ['A'], label: A.name }],
      rows: [{ key: 'A', label: A.name, pieces: [del(a, names[0]), del(b, names[1])] }],
      build: [shape({ A: { n: 2 } }, {
        why: `${whole} är en helhet med två delar: ${names[0]} och ${names[1]}. Blocket delas i två delar.`,
        msg: { A: 'Hur många delar består helheten av? Läs första meningen igen.' },
      })],
      facts: [fact(0, a, 'A.0'), fact(0, b, 'A.1')],
      ask: { slot: 'A' },
      calc: [line('Sammanlagt', plus(a, b), sum)],
      answer: { pre, v: sum, post, traps: {
        [a]: 'Det är bara den ena delen. Frågan gäller hela blocket.',
        [b]: 'Det är bara den ena delen. Frågan gäller hela blocket.',
      } },
      check: sv`Kolla: ${sum} ${MINUS} ${a} = ${b}. Det stämmer!`,
    };
  });

  /* Part and whole: the whole and one part are known. */
  T('dh-kvar', 'delhel', 1, (r, c) => {
    const [A] = people(r, c, 1);
    const kind = r.pick(['buy', 'book', 'candy']);
    let W, p, text, names, unit, label, pre, post;
    if (kind === 'buy') {
      const g = r.pick(GOODS);
      W = r.step(150, 600, 10);
      p = r.step(40, W - 40, 5);
      text = [
        S`${nm(A, 0)} har ${W} ${tag('kr', 0)}.`,
        S`${he(A, 0, true)} köper ${g.en} ${g.sg} för ${p} ${tag('kr', 0)}.`,
        S`Hur mycket ${tag('pengar', 0)} har ${he(A, 0)} kvar?`,
      ];
      names = [g.sg, 'kvar']; unit = 'kr'; label = A.name; pre = `${A.name} har`; post = 'kr kvar.';
    } else if (kind === 'book') {
      W = r.int(120, 320);
      p = r.int(30, W - 25);
      text = [
        S`En ${tag('bok', 0)} har ${W} ${tag('sidor', 0)}.`,
        S`${nm(A, 0)} har läst ${p} ${tag('sidor', 0)}.`,
        S`Hur många sidor har ${he(A, 0)} kvar att läsa?`,
      ];
      names = ['läst', 'kvar']; unit = ''; label = 'Boken'; pre = `${A.name} har`; post = 'sidor kvar att läsa.';
    } else {
      W = r.int(40, 90);
      p = r.int(12, W - 10);
      text = [
        S`I en ${tag('påse', 0)} finns ${W} ${tag('godisbitar', 0)}.`,
        S`${nm(A, 0)} och ${A.his} kompisar äter upp ${p} av dem.`,
        S`Hur många ${tag('godisbitar', 0)} finns kvar i påsen?`,
      ];
      names = ['uppätna', 'kvar']; unit = ''; label = 'Godis'; pre = 'Det finns'; post = 'godisbitar kvar.';
    }
    return {
      text, unit,
      who: [{ rows: ['A'], label: kind === 'buy' ? A.name : label.toLowerCase() }],
      rows: [{ key: 'A', label, pieces: [del(p, names[0]), del(W - p, names[1])] }],
      build: [shape({ A: { n: 2 } }, {
        why: `Hela blocket är allt från början. Det består av två delar: ${names[0]} och det som är kvar.`,
        msg: { A: 'Allt från början är en helhet. Hur många delar består den av?' },
      })],
      facts: [fact(0, W, 'A'), fact(1, p, 'A.0')],
      ask: { slot: 'A.1' },
      calc: [line('Kvar', minus(W, p), W - p, { hint: 'Ta bort den kända delen från helheten.' })],
      answer: { pre, v: W - p, post, traps: {
        [W + p]: 'Ska det som är kvar vara mer än det var från början? Ta bort delen i stället.',
        [W]: 'Det är hela blocket, allt från början. Frågan gäller det som är kvar.',
      } },
      check: sv`Kolla: ${p} + ${W - p} = ${W}. Det stämmer!`,
    };
  });

  /* Part and whole in three parts: two parts and the whole are known. */
  T('dh-tre', 'delhel', 2, (r, c) => {
    const [A] = people(r, c, 1);
    const kind = r.pick(['class', 'beads', 'money']);
    let W, x, y, text, names, unit, label, pre, post;
    if (kind === 'class') {
      W = r.int(22, 30); x = r.int(4, 10); y = r.int(4, 10);
      text = [
        S`Det går ${W} ${tag('elever', 0)} i ${ps(A)} ${tag('klass', 0)}.`,
        S`Av dem åker ${x} buss till skolan och ${y} cyklar.`,
        S`Resten går.`,
        S`Hur många ${tag('elever', 0)} går till skolan?`,
      ];
      names = ['buss', 'cykel', 'går']; unit = ''; label = 'Elever'; pre = ''; post = 'elever går till skolan.';
    } else if (kind === 'beads') {
      W = r.int(30, 80); x = r.int(8, 30); y = r.int(8, 30);
      text = [
        S`${nm(A, 0)} har ${W} ${tag('pärlor', 0)}.`,
        S`Av dem är ${x} röda och ${y} blå.`,
        S`Resten är gula.`,
        S`Hur många gula ${tag('pärlor', 0)} har ${he(A, 0)}?`,
      ];
      names = ['röda', 'blå', 'gula']; unit = ''; label = A.name; pre = `${A.name} har`; post = 'gula pärlor.';
    } else {
      W = r.step(200, 500, 10); x = r.step(40, 150, 5); y = r.step(40, 150, 5);
      text = [
        S`${nm(A, 0)} fick ${W} ${tag('kr', 0)} på sin födelsedag.`,
        S`${he(A, 0, true)} köpte en bok för ${x} kr och en biobiljett för ${y} kr.`,
        S`Resten sparade ${he(A, 0)}.`,
        S`Hur mycket ${tag('pengar', 0)} sparade ${he(A, 0)}?`,
      ];
      names = ['bok', 'bio', 'sparat']; unit = 'kr'; label = A.name; pre = `${A.name} sparade`; post = 'kr.';
    }
    const z = W - x - y;
    if (x === y || z < 3 || (kind === 'money' && z < 20)) return null;
    return {
      text, unit,
      who: [{ rows: ['A'], label: label === A.name ? A.name : 'eleverna' }],
      rows: [{ key: 'A', label, pieces: [del(x, names[0]), del(y, names[1]), del(z, names[2])] }],
      build: [shape({ A: { n: 3 } }, {
        why: `Helheten har tre delar: ${names[0]}, ${names[1]} och ${names[2]}.`,
        msg: { A: 'Hur många delar består helheten av? Räkna dem i texten.' },
      })],
      facts: [fact(0, W, 'A'), fact(1, x, 'A.0'), fact(1, y, 'A.1')],
      ask: { slot: 'A.2' },
      calc: [
        line(`${cap(names[0])} och ${names[1]}`, plus(x, y), x + y, { hint: 'Lägg först ihop de två delar du vet.' }),
        line(cap(names[2]), minus(W, x + y), z, { hint: 'Ta bort dem från helheten.' }),
      ],
      answer: { pre, v: z, post, traps: {
        [x + y]: 'Det är de två delar du vet. Frågan gäller den tredje delen.',
        [W - x]: 'Du har bara tagit bort den ena delen.',
        [W - y]: 'Du har bara tagit bort den ena delen.',
      } },
      check: sv`Kolla: ${x} + ${y} + ${z} = ${W}. Det stämmer!`,
    };
  });

  /* Two people, one has so many more. */
  T('jm-fler', 'jmf', 1, (r, c) => {
    const [A, B] = people(r, c, 2);
    const money = r.chance(0.35);
    const th = r.pick(COLLECT);
    const a = money ? r.step(40, 300, 5) : r.int(18, 85);
    const d = money ? r.step(15, 120, 5) : r.int(6, 35);
    const b = a + d;
    if (a === d) return null;
    const text = money ? [
      S`${nm(A, 0)} har ${a} kr.`,
      S`${nm(B, 1)} har ${d} kr mer än ${nm(A, 0)}.`,
      S`Hur mycket pengar har ${nm(B, 1)}?`,
    ] : [
      S`${nm(A, 0)} har ${a} ${th.pl}.`,
      S`${nm(B, 1)} har ${d} fler ${th.pl} än ${nm(A, 0)}.`,
      S`Hur många ${th.pl} har ${nm(B, 1)}?`,
    ];
    return {
      text, unit: money ? 'kr' : '',
      who: [{ rows: ['A'], label: A.name }, { rows: ['B'], label: B.name }],
      rows: [
        { key: 'A', label: A.name, pieces: [bit(a)] },
        { key: 'B', label: B.name, pieces: [bit(a), del(d)] },
      ],
      build: [shape({ A: { bits: 1 }, B: { bits: 1, x: 1 } }, {
        why: sv`${B.name} har lika ${money ? 'mycket' : 'många'} som ${A.name} och ${d} till. Blocket för ${B.name} är lika långt som blocket för ${A.name}, med en annan bit till.`,
        msg: {
          A: `${A.name} har ett tal, inget mer. Ett block med en bit räcker.`,
          B: sv`${B.name} har ${d} fler. Är det lika mycket till, eller en annan bit till?`,
        },
      })],
      facts: [fact(0, a, 'A'), fact(1, d, 'B.1')],
      ask: { slot: 'B' },
      calc: [line(B.name, plus(a, d), b, { hint: sv`${B.name} har lika mycket som ${A.name} och ${d} till.` })],
      answer: { pre: `${B.name} har`, v: b, post: money ? 'kr.' : `${th.pl}.`, traps: {
        [a]: `Det är så mycket ${A.name} har. ${B.name} har mer.`,
        [d]: sv`${d} är skillnaden, biten som sticker ut. Hur mycket har ${B.name} i allt?`,
        [a - d]: `${B.name} har fler, inte färre. Ska du lägga till eller ta bort?`,
      } },
      check: sv`Kolla: ${b} ${MINUS} ${a} = ${d}. ${B.name} har ${d} fler. Det stämmer!`,
    };
  });

  /* Two people, one has so many fewer. */
  T('jm-farre', 'jmf', 1, (r, c) => {
    const [A, B] = people(r, c, 2);
    const money = r.chance(0.35);
    const th = r.pick(COLLECT);
    const a = money ? r.step(80, 400, 5) : r.int(40, 99);
    const d = money ? r.step(15, 70, 5) : r.int(8, 30);
    const b = a - d;
    if (b < 10 || b === d) return null;
    const text = money ? [
      S`${nm(A, 0)} har ${a} kr.`,
      S`${nm(B, 1)} har ${d} kr mindre än ${nm(A, 0)}.`,
      S`Hur mycket pengar har ${nm(B, 1)}?`,
    ] : [
      S`${nm(A, 0)} har ${a} ${th.pl}.`,
      S`${nm(B, 1)} har ${d} färre ${th.pl} än ${nm(A, 0)}.`,
      S`Hur många ${th.pl} har ${nm(B, 1)}?`,
    ];
    return {
      text, unit: money ? 'kr' : '',
      who: [{ rows: ['A'], label: A.name }, { rows: ['B'], label: B.name }],
      rows: [
        { key: 'A', label: A.name, pieces: [bit(b), del(d)] },
        { key: 'B', label: B.name, pieces: [bit(b)] },
      ],
      build: [shape({ A: { bits: 1, x: 1 }, B: { bits: 1 } }, {
        why: sv`${B.name} har ${money ? 'mindre' : 'färre'}. Blocket för ${A.name} är längst: lika långt som blocket för ${B.name} och en annan bit till, skillnaden.`,
        msg: {
          A: sv`${A.name} har ${d} mer än ${B.name}. Vems block ska vara längst?`,
          B: sv`${B.name} har ${money ? 'mindre' : 'färre'} än ${A.name}. Ska blocket för ${B.name} då vara längst?`,
        },
      })],
      facts: [fact(0, a, 'A'), fact(1, d, 'A.1')],
      ask: { slot: 'B' },
      calc: [line(B.name, minus(a, d), b, { hint: `Ta bort skillnaden från det ${A.name} har.` })],
      answer: { pre: `${B.name} har`, v: b, post: money ? 'kr.' : `${th.pl}.`, traps: {
        [a + d]: `${money ? 'Mindre' : 'Färre'} betyder att ${B.name} har mindre än ${A.name}. Ska du lägga till eller ta bort?`,
        [a]: `Det är så mycket ${A.name} har.`,
        [d]: 'Det är skillnaden, biten som sticker ut.',
      } },
      check: sv`Kolla: ${b} + ${d} = ${a}. Det stämmer!`,
    };
  });

  /* Two numbers known, how much more is asked for. */
  T('jm-skillnad', 'jmf', 1, (r, c) => {
    const [A, B] = people(r, c, 2);
    const kind = r.pick(['height', 'collect', 'game']);
    let a, b, text, who, rows, pre, post, unit, labB;
    if (kind === 'height') {
      const rel = r.pick([['pappa', 'pappan'], ['mamma', 'mamman'], ['moster', 'mostern'], ['farbror', 'farbrodern'], ['kusin', 'kusinen']]);
      a = r.int(136, 160); b = r.int(166, 194);
      labB = cap(rel[0]);
      text = [
        S`${nm(A, 0)} är ${a} cm lång.`,
        S`${cap(A.his)} ${tag(rel[0], 1)} är ${b} cm lång.`,
        S`Hur många centimeter längre än ${nm(A, 0)} är ${tag(rel[1], 1)}?`,
      ];
      who = [{ rows: ['A'], label: A.name }, { rows: ['B'], label: rel[1] }];
      pre = `${cap(rel[1])} är`; post = 'cm längre.'; unit = 'cm';
    } else {
      const th = r.pick(COLLECT);
      a = r.int(20, 80); b = r.int(a + 6, a + 45);
      labB = B.name;
      if (kind === 'collect') {
        text = [
          S`${nm(A, 0)} har ${a} ${th.pl} och ${nm(B, 1)} har ${b} ${th.pl}.`,
          S`Hur många fler ${th.pl} har ${nm(B, 1)} än ${nm(A, 0)}?`,
        ];
        post = `fler ${th.pl}.`;
      } else {
        text = [
          S`I ett spel fick ${nm(A, 0)} ${a} poäng och ${nm(B, 1)} fick ${b} poäng.`,
          S`Hur många fler poäng fick ${nm(B, 1)} än ${nm(A, 0)}?`,
        ];
        post = 'fler poäng.';
      }
      who = [{ rows: ['A'], label: A.name }, { rows: ['B'], label: B.name }];
      pre = `${B.name} ${kind === 'game' ? 'fick' : 'har'}`; unit = '';
    }
    const d = b - a;
    if (d === a) return null;
    return {
      text, unit, who,
      rows: [
        { key: 'A', label: A.name, pieces: [bit(a)] },
        { key: 'B', label: labB, pieces: [bit(a), del(d)] },
      ],
      build: [shape({ A: { bits: 1 }, B: { bits: 1, x: 1 } }, {
        why: `Vi jämför två tal. Det största får det längsta blocket, och biten som sticker ut är skillnaden.`,
        msg: {
          A: 'Vilket av talen är minst? Det blocket behöver ingen annan bit.',
          B: 'Det största talet behöver en annan bit, skillnaden, som sticker ut.',
        },
      })],
      facts: kind === 'height' ? [fact(0, a, 'A'), fact(1, b, 'B')] : [fact(0, a, 'A'), fact(0, b, 'B')],
      ask: { slot: 'B.1' },
      calc: [line('Skillnaden', minus(b, a), d, { hint: 'Ta det största talet minus det minsta.' })],
      answer: { pre, v: d, post, traps: {
        [a + b]: 'Det är båda tillsammans. Frågan gäller skillnaden, biten som sticker ut.',
        [b]: 'Det är hela det längsta blocket. Frågan gäller bara biten som sticker ut.',
      } },
      check: sv`Kolla: ${a} + ${d} = ${b}. Det stämmer!`,
    };
  });

  /* How much more, then both together. */
  T('jm-tills', 'jmf', 2, (r, c) => {
    const [A, B] = people(r, c, 2);
    const th = r.pick(COLLECT);
    const a = r.int(18, 70), d = r.int(6, 30), b = a + d;
    if (a === d) return null;
    return {
      text: [
        S`${nm(A, 0)} har ${a} ${th.pl}.`,
        S`${nm(B, 1)} har ${d} fler ${th.pl} än ${nm(A, 0)}.`,
        S`Hur många ${th.pl} har de tillsammans?`,
      ],
      unit: '',
      who: [{ rows: ['A'], label: A.name }, { rows: ['B'], label: B.name }],
      rows: [
        { key: 'A', label: A.name, pieces: [bit(a)] },
        { key: 'B', label: B.name, pieces: [bit(a), del(d)] },
      ],
      build: [shape({ A: { bits: 1 }, B: { bits: 1, x: 1 } }, {
        why: sv`${B.name} har lika många som ${A.name} och ${d} till: blocket för ${B.name} har en annan bit som sticker ut.`,
        msg: { B: sv`${B.name} har ${d} fler än ${A.name}. Behövs det en annan bit?` },
      })],
      facts: [fact(0, a, 'A'), fact(1, d, 'B.1')],
      ask: { slot: 'T' },
      calc: [
        line(B.name, plus(a, d), b, { hint: sv`Räkna först ut hur många ${B.name} har.` }),
        line('Tillsammans', plus(a, b), a + b, { hint: 'Lägg ihop båda blocken.' }),
      ],
      answer: { pre: 'De har', v: a + b, post: `${th.pl} tillsammans.`, traps: {
        [b]: `Det är så många ${B.name} har. Frågan gäller båda tillsammans.`,
        [a + d]: `Det är så många ${B.name} har. Frågan gäller båda tillsammans.`,
      } },
      check: sv`Kolla: ${a} + ${b} = ${a + b}, och ${b} är ${d} mer än ${a}. Det stämmer!`,
    };
  });

  /* Equal bits: one bit is known, the whole is asked for. */
  T('li-ggr', 'lika', 1, (r, c) => {
    const [A] = people(r, c, 1);
    const kind = r.pick(['tickets', 'train', 'boxes']);
    let p, n, text, label, unit, pre, post, who;
    if (kind === 'tickets') {
      p = r.step(60, 130, 5); n = r.int(3, 6);
      text = [
        S`En ${tag('biobiljett', 0)} kostar ${p} kr.`,
        S`Hur mycket kostar ${n} ${tag('biljetter', 0)}?`,
      ];
      label = 'Biljetter'; unit = 'kr'; pre = sv`${n} biljetter kostar`; post = 'kr.'; who = 'biljetterna';
    } else if (kind === 'train') {
      p = r.step(25, 60, 5); n = r.int(3, 7);
      text = [
        S`${nm(A, 0)} tränar fotboll ${p} ${tag('minuter', 0)} om dagen i ${n} dagar.`,
        S`Hur många minuter tränar ${he(A, 0)} sammanlagt?`,
      ];
      label = A.name; unit = 'min'; pre = `${A.name} tränar`; post = 'minuter sammanlagt.'; who = A.name;
    } else {
      const th = r.pick(BAKED.slice(4));
      p = r.int(12, 30); n = r.int(3, 8);
      text = [
        S`I varje ${tag('låda', 0)} finns det ${p} ${tag(th.pl, 0)}.`,
        S`Hur många ${tag(th.pl, 0)} finns det i ${n} ${tag('lådor', 0)}?`,
      ];
      label = cap(th.pl); unit = ''; pre = sv`I ${n} lådor finns det`; post = `${th.pl}.`; who = th.def;
    }
    if (p === n) return null;
    const what = kind === 'tickets' ? 'biljetter' : kind === 'train' ? 'dagar' : 'lådor';
    return {
      text, unit,
      who: [{ rows: ['A'], label: who }],
      rows: [{ key: 'A', label, pieces: bits(n, p) }],
      build: [shape({ A: { bits: n } }, {
        why: `Det är ${n} ${what} med lika mycket i varje: blocket delas i ${n} lika stora bitar.`,
        msg: { A: `Hur många ${what} är det? Lika många lika stora bitar behövs.` },
      })],
      facts: [fact(0, p, 'A.bit')],
      ask: { slot: 'A' },
      calc: [line(nb(n), mul(n, p), n * p, { hint: sv`Varje bit är ${p}. Det är ${n} bitar.` })],
      answer: { pre, v: n * p, post, traps: {
        [p]: 'Det är en bit. Frågan gäller hela blocket.',
        [n + p]: `Det är ${n} bitar, inte ${n} till. Multiplicera.`,
      } },
      check: sv`Kolla: ${n * p} / ${n} = ${p}. Det stämmer!`,
    };
  });

  /* Equal bits: the whole is known, one bit is asked for. */
  T('li-dela', 'lika', 1, (r, c) => {
    const [A] = people(r, c, 1);
    const kind = r.pick(['share', 'bill', 'ribbon']);
    let n, e, text, label, unit, pre, post, who, what;
    if (kind === 'share') {
      const th = r.pick(COLLECT);
      n = r.int(3, 8); e = r.int(6, 25);
      text = [
        S`En lärare ska dela ${n * e} ${tag(th.pl, 0)} lika mellan ${n} grupper.`,
        S`Hur många ${tag(th.pl, 0)} får varje grupp?`,
      ];
      label = cap(th.pl); unit = ''; pre = 'Varje grupp får'; post = `${th.pl}.`; who = th.def; what = `mellan ${n} grupper`;
    } else if (kind === 'bill') {
      n = r.int(3, 6); e = r.step(45, 150, 5);
      text = [
        S`${cap(WORDS[n])} kompisar äter pizza tillsammans.`,
        S`${tag('Notan', 0)} blir ${n * e} ${tag('kr', 0)} och de delar lika på den.`,
        S`Hur mycket betalar var och en?`,
      ];
      label = 'Notan'; unit = 'kr'; pre = 'Var och en betalar'; post = 'kr.'; who = 'notan'; what = `mellan ${n} kompisar`;
    } else {
      n = r.int(3, 8); e = r.int(6, 24);
      text = [
        S`Ett ${tag('band', 0)} är ${n * e} cm långt.`,
        S`${nm(A, 0)} klipper ${tag('bandet', 0)} i ${n} lika långa bitar.`,
        S`Hur lång blir varje bit?`,
      ];
      label = 'Bandet'; unit = 'cm'; pre = 'Varje bit blir'; post = 'cm lång.'; who = 'bandet'; what = `i ${n} bitar`;
    }
    if (e === n) return null;
    const W = n * e;
    return {
      text, unit,
      who: [{ rows: ['A'], label: who }],
      rows: [{ key: 'A', label, pieces: bits(n, e) }],
      build: [shape({ A: { bits: n } }, {
        why: `Allt delas lika ${what}: blocket delas i ${n} lika stora bitar.`,
        msg: { A: `I hur många lika stora delar delas det? Så många bitar behövs.` },
      })],
      facts: [fact(kind === 'bill' ? 1 : 0, W, 'A')],
      ask: { slot: 'A.bit' },
      calc: [line('1 bit', div(W, n), e, { hint: sv`Dela ${W} i ${n} lika stora bitar.` })],
      answer: { pre, v: e, post, traps: {
        [W * n]: 'Ska det bli mer eller mindre i varje bit än i hela blocket? Dela i stället.',
        [W - n]: `Dela i ${n} lika stora bitar, ta inte bort ${n}.`,
      } },
      check: sv`Kolla: ${n} ${DOT} ${e} = ${W}. Det stämmer!`,
    };
  });

  /* Equal bits: so many cost so much, what do fewer cost? */
  T('li-prop', 'lika', 2, (r) => {
    const th = r.pick(BAKED.slice(0, 4));
    const n = r.int(4, 8), e = r.int(6, 15), m = r.int(2, n - 1);
    const W = n * e;
    if (m === e) return null;
    return {
      text: [
        S`I ett bageri kostar ${n} ${tag(th.pl, 0)} ${W} kr.`,
        S`Hur mycket kostar ${m} ${tag(th.pl, 0)}?`,
      ],
      unit: 'kr',
      who: [{ rows: ['A'], label: th.def }],
      rows: [{ key: 'A', label: cap(th.pl), pieces: bits(n, e) }],
      groups: [group('A:g', 'A', range(0, m - 1), sv`${m} ${th.pl}`, { mark: true })],
      build: [
        shape({ A: { bits: n } }, {
          why: sv`${n} ${th.pl} som kostar lika mycket var: ${n} lika stora bitar, en för varje.`,
          msg: { A: sv`Hur många ${th.pl} kostar ${W} kr? En bit för varje.` },
        }),
        mark('A', 'A:g', m, {
          why: sv`Vi ska ta reda på vad ${m} ${th.pl} kostar. De markerar vi.`,
          ask: sv`Markera bitarna för de ${m} ${th.pl} som frågan gäller.`,
          msg: sv`Hur många ${th.pl} frågar uppgiften om? En bit för varje.`,
        }),
      ],
      facts: [fact(0, W, 'A')],
      ask: { slot: 'A:g' },
      calc: [
        given(nb(n), W),
        line('1 bit', div(W, n), e, { hint: sv`Dela ${W} i ${n} lika stora bitar.` }),
        line(nb(m), mul(m, e), m * e, { hint: sv`En bit är ${e}. Hur mycket är ${m} bitar?` }),
      ],
      answer: { pre: sv`${m} ${th.pl} kostar`, v: m * e, post: 'kr.', traps: {
        [e]: sv`Det är vad en kostar. Frågan gäller ${m} stycken.`,
        [W - m]: 'Räkna först ut vad en bit kostar.',
      } },
      check: sv`Kolla: ${m * e} är ${m} av ${n} lika stora bitar av ${W}. Det stämmer!`,
    };
  });

  /* So many times as many: one bit known. */
  T('gg-hur', 'ggr', 1, (r, c) => {
    const [A, B] = people(r, c, 2);
    const th = r.pick(COLLECT);
    const k = r.int(2, 5), a = r.int(6, 25);
    if (a === k) return null;
    return {
      text: [
        S`${nm(A, 0)} har ${a} ${th.pl}.`,
        S`${nm(B, 1)} har ${times(k)} så många ${th.pl} som ${nm(A, 0)}.`,
        S`Hur många ${th.pl} har ${nm(B, 1)}?`,
      ],
      unit: '',
      who: [{ rows: ['A'], label: A.name }, { rows: ['B'], label: B.name }],
      rows: [
        { key: 'A', label: A.name, pieces: [bit(a)] },
        { key: 'B', label: B.name, pieces: bits(k, a) },
      ],
      build: [shape({ A: { bits: 1 }, B: { bits: k } }, {
        why: `${B.name} har ${times(k)} så många: ${k} bitar, lika stora som biten för ${A.name}.`,
        msg: {
          A: `${A.name} har det minsta talet: 1 bit.`,
          B: `${B.name} har ${times(k)} så många som ${A.name}. Hur många lika stora bitar blir det?`,
        },
      })],
      facts: [fact(0, a, 'A')],
      ask: { slot: 'B' },
      calc: [line(nb(k), mul(k, a), k * a, { hint: sv`Varje bit är ${a}. ${B.name} har ${k} bitar.` })],
      answer: { pre: `${B.name} har`, v: k * a, post: `${th.pl}.`, traps: {
        [a + k]: `${cap(times(k))} så många är ${k} bitar, inte ${k} fler.`,
        [a]: `Det är 1 bit, så många som ${A.name} har.`,
      } },
      check: sv`Kolla: ${k * a} / ${k} = ${a}. Det stämmer!`,
    };
  });

  /* So many times as many, and both together. */
  T('gg-tills', 'ggr', 1, (r, c) => {
    const [A, B] = people(r, c, 2);
    const money = r.chance(0.3);
    const th = r.pick(COLLECT);
    const k = r.int(2, 4), u = money ? r.step(20, 150, 5) : r.int(5, 20);
    const W = (k + 1) * u;
    const askB = r.chance(0.5);
    const X = askB ? B : A;
    if (u === k || W === u * k) return null;
    const text = money ? [
      S`${nm(B, 1)} har ${times(k)} så mycket pengar som ${nm(A, 0)}.`,
      S`Tillsammans har de ${W} kr.`,
      S`Hur mycket pengar har ${nm(X, askB ? 1 : 0)}?`,
    ] : [
      S`${nm(B, 1)} har ${times(k)} så många ${th.pl} som ${nm(A, 0)}.`,
      S`Tillsammans har de ${W} ${th.pl}.`,
      S`Hur många ${th.pl} har ${nm(X, askB ? 1 : 0)}?`,
    ];
    const calc = [
      given(nb(k + 1), W),
      line('1 bit', div(W, k + 1), u, { hint: sv`Det är ${k + 1} lika stora bitar i allt. Dela ${W} med ${k + 1}.` }),
    ];
    if (askB) calc.push(line(nb(k), mul(k, u), k * u, { hint: `${B.name} har ${k} bitar.` }));
    const traps = askB
      ? { [u]: sv`${u} är 1 bit, det som ${A.name} har. ${B.name} har ${k} bitar.`, [Math.round(W / k)]: `Hur många bitar finns det i allt? Räkna alla bitarna i båda blocken.` }
      : { [k * u]: sv`${k * u} är ${k} bitar, det som ${B.name} har. ${A.name} har 1 bit.`, [Math.round(W / k)]: `Hur många bitar finns det i allt? Räkna alla bitarna i båda blocken.` };
    return {
      text, unit: money ? 'kr' : '',
      who: [{ rows: ['A'], label: A.name }, { rows: ['B'], label: B.name }],
      rows: [
        { key: 'A', label: A.name, pieces: [bit(u)] },
        { key: 'B', label: B.name, pieces: bits(k, u) },
      ],
      build: [shape({ A: { bits: 1 }, B: { bits: k } }, {
        why: `${B.name} har ${times(k)} så ${money ? 'mycket' : 'många'} som ${A.name}: ${A.name} får 1 bit och ${B.name} ${k} lika stora bitar.`,
        msg: {
          A: `${A.name} har minst: 1 bit.`,
          B: `${times(k) === 'dubbelt' ? 'Dubbelt' : cap(times(k))} så ${money ? 'mycket' : 'många'}: hur många bitar ska ${B.name} ha?`,
        },
      })],
      facts: [fact(1, W, 'T')],
      ask: { slot: askB ? 'B' : 'A' },
      calc,
      answer: { pre: `${X.name} har`, v: askB ? k * u : u, post: money ? 'kr.' : `${th.pl}.`, traps },
      check: sv`Kolla: ${u} + ${k * u} = ${W}, och ${k * u} är ${times(k)} så mycket som ${u}. Det stämmer!`,
    };
  });

  /* So many times as many, and the difference is known. */
  T('gg-skill', 'ggr', 2, (r, c) => {
    const [A, B] = people(r, c, 2);
    const th = r.pick(COLLECT);
    const k = r.int(3, 5), u = r.int(5, 20);
    const D = (k - 1) * u;
    const askB = r.chance(0.4);
    const X = askB ? B : A;
    if (u === k) return null;
    const calc = [
      given(nb(k - 1), D),
      line('1 bit', div(D, k - 1), u, { hint: sv`Skillnaden är ${k - 1} bitar. Dela ${D} med ${k - 1}.` }),
    ];
    if (askB) calc.push(line(nb(k), mul(k, u), k * u, { hint: `${B.name} har ${k} bitar.` }));
    return {
      text: [
        S`${nm(B, 1)} har ${times(k)} så många ${th.pl} som ${nm(A, 0)}.`,
        S`${nm(B, 1)} har ${D} fler ${th.pl} än ${nm(A, 0)}.`,
        S`Hur många ${th.pl} har ${nm(X, askB ? 1 : 0)}?`,
      ],
      unit: '',
      who: [{ rows: ['A'], label: A.name }, { rows: ['B'], label: B.name }],
      rows: [
        { key: 'A', label: A.name, pieces: [bit(u)] },
        { key: 'B', label: B.name, pieces: bits(k, u) },
      ],
      groups: [group('B:diff', 'B', range(1, k - 1), 'skillnad')],
      build: [shape({ A: { bits: 1 }, B: { bits: k } }, {
        why: `${B.name} har ${times(k)} så många: ${k} bitar mot 1. Bitarna som sticker ut är skillnaden.`,
        msg: { B: `${cap(times(k))} så många: hur många bitar ska ${B.name} ha?` },
      })],
      facts: [fact(1, D, 'B:diff', { hint: 'Skillnaden är bitarna som sticker ut.' })],
      ask: { slot: askB ? 'B' : 'A' },
      calc,
      answer: { pre: `${X.name} har`, v: askB ? k * u : u, post: `${th.pl}.`, traps: {
        [Math.round(D / k)]: `Hur många bitar är skillnaden? Räkna bitarna som sticker ut.`,
        [askB ? u : k * u]: askB ? `Det är 1 bit. ${B.name} har ${k} bitar.` : `Det är ${B.name}s ${k} bitar. ${A.name} har 1 bit.`,
      } },
      check: sv`Kolla: ${k * u} ${MINUS} ${u} = ${D}. Det stämmer!`,
    };
  });

  /* Half as many (or a third), and both together. */
  T('gg-half', 'ggr', 2, (r, c) => {
    const [A, B] = people(r, c, 2);
    const th = r.pick(COLLECT);
    const k = r.chance(0.6) ? 2 : 3;
    const u = r.int(6, 25), b = k * u;
    const word = k === 2 ? 'hälften' : 'en tredjedel';
    return {
      text: [
        S`${nm(A, 0)} har ${word} så många ${th.pl} som ${nm(B, 1)}.`,
        S`${nm(B, 1)} har ${b} ${th.pl}.`,
        S`Hur många ${th.pl} har de tillsammans?`,
      ],
      unit: '',
      who: [{ rows: ['A'], label: A.name }, { rows: ['B'], label: B.name }],
      rows: [
        { key: 'A', label: A.name, pieces: [bit(u)] },
        { key: 'B', label: B.name, pieces: bits(k, u) },
      ],
      build: [shape({ A: { bits: 1 }, B: { bits: k } }, {
        why: `${cap(word)} så många: ${B.name} får ${k} bitar och ${A.name} 1 bit.`,
        msg: {
          A: `${A.name} har minst: 1 bit.`,
          B: `Om ${A.name} har 1 bit och det är ${word} av det ${B.name} har, hur många bitar har ${B.name}?`,
        },
      })],
      facts: [fact(1, b, 'B')],
      ask: { slot: 'T' },
      calc: [
        given(nb(k), b),
        line('1 bit', div(b, k), u, { hint: sv`${B.name} har ${k} bitar. Dela ${b} med ${k}.` }),
        line(nb(k + 1), mul(k + 1, u), (k + 1) * u, { hint: `Räkna alla bitarna i båda blocken.` }),
      ],
      answer: { pre: 'De har', v: (k + 1) * u, post: `${th.pl} tillsammans.`, traps: {
        [u]: `Det är så många ${A.name} har. Frågan gäller båda tillsammans.`,
        [b]: `Det är så många ${B.name} har. Frågan gäller båda tillsammans.`,
        [b + 2 * b]: `${A.name} har ${word} så många, inte ${times(k)} så många.`,
      } },
      check: sv`Kolla: ${u} + ${b} = ${(k + 1) * u}, och ${u} är ${word} av ${b}. Det stämmer!`,
    };
  });

  /* Sum and difference: two numbers unknown. */
  function sumDiff(id, level, askBig, fewer) {
    T(id, 'sumdiff', level, (r, c) => {
      const [A, B] = people(r, c, 2);
      const money = !fewer && r.chance(0.5);
      const th = r.pick(COLLECT);
      const u = money ? r.step(20, 90, 2) : r.int(10, 45);
      const D = money ? r.step(6, 40, 2) : r.int(4, 25);
      const W = 2 * u + D;
      const X = askBig ? A : B;
      if (u === D || W % 2 === 0 && W / 2 === u) return null;
      const say = money ? [
        S`${nm(A, 0)} och ${nm(B, 1)} har tillsammans ${W} kr.`,
        S`${nm(A, 0)} har ${D} kr mer än ${nm(B, 1)}.`,
        S`Hur mycket pengar har ${nm(X, askBig ? 0 : 1)}?`,
      ] : fewer ? [
        S`${nm(A, 0)} och ${nm(B, 1)} har ${W} ${th.pl} tillsammans.`,
        S`${nm(B, 1)} har ${D} färre ${th.pl} än ${nm(A, 0)}.`,
        S`Hur många ${th.pl} har ${nm(X, askBig ? 0 : 1)}?`,
      ] : [
        S`${nm(A, 0)} och ${nm(B, 1)} har tillsammans ${W} ${th.pl}.`,
        S`${nm(A, 0)} har ${D} fler ${th.pl} än ${nm(B, 1)}.`,
        S`Hur många ${th.pl} har ${nm(X, askBig ? 0 : 1)}?`,
      ];
      const calc = [
        line(nb(2), minus(W, D), W - D, { hint: sv`Ta bort skillnaden, ${D}, så blir blocken lika långa.` }),
        line('1 bit', div(W - D, 2), u, { hint: sv`Två lika stora bitar är ${W - D}.` }),
      ];
      if (askBig) calc.push(line(A.name, plus(u, D), u + D, { hint: sv`${A.name} har en bit och ${D} till.` }));
      const traps = {
        [W - D]: 'Det är två bitar. Hur mycket är en bit?',
        [askBig ? u : u + D]: askBig ? `Det är vad ${B.name} har. ${A.name} har mer.` : `Det är vad ${A.name} har. ${B.name} har mindre.`,
      };
      if (W % 2 === 0) traps[W / 2] = sv`Blocken är inte lika långa, så det går inte att dela ${W} mitt itu. Ta först bort skillnaden.`;
      return {
        text: say, unit: money ? 'kr' : '',
        who: [{ rows: ['A'], label: A.name }, { rows: ['B'], label: B.name }],
        rows: [
          { key: 'A', label: A.name, pieces: [bit(u), del(D)] },
          { key: 'B', label: B.name, pieces: [bit(u)] },
        ],
        build: [shape({ A: { bits: 1, x: 1 }, B: { bits: 1 } }, {
          why: sv`${A.name} har ${D} ${money ? 'kr mer' : 'fler'}: lika mycket som ${B.name} och en annan bit till. Klammern runt båda blocken är ${W}.`,
          msg: {
            A: `${A.name} har mer än ${B.name}. Behövs det en annan bit, skillnaden?`,
            B: `${B.name} har minst. Ett block med en bit räcker.`,
          },
        })],
        facts: [fact(0, W, 'T'), fact(1, D, 'A.1')],
        ask: { slot: askBig ? 'A' : 'B' },
        calc,
        answer: { pre: `${X.name} har`, v: askBig ? u + D : u, post: money ? 'kr.' : `${th.pl}.`, traps },
        check: sv`Kolla: ${u} + ${u + D} = ${W}, och skillnaden är ${D}. Det stämmer!`,
      };
    });
  }
  sumDiff('sd-minst', 1, false, false);
  sumDiff('sd-mest', 1, true, false);
  sumDiff('sd-farre', 2, false, true);

  /* Fractions. */
  const FRACS = [[1, 3], [2, 3], [1, 4], [3, 4], [2, 5], [3, 5], [4, 5], [5, 6], [3, 8], [5, 8], [2, 7], [4, 7]];

  /* A fraction of a known whole. */
  T('br-del', 'brak', 1, (r, c) => {
    const [A] = people(r, c, 1);
    const [a, b] = r.pick(FRACS);
    const kind = r.pick(['day', 'gift', 'book']);
    let u, text, label, gl, unit, pre, post, who;
    if (kind === 'day') {
      u = r.int(4, 14);
      text = [
        S`På friluftsdagen är ${b * u} ${tag('elever', 0)} med.`,
        S`${fr(a, b)} av ${tag('eleverna', 0)} vill åka skridskor.`,
        S`Hur många ${tag('elever', 0)} vill åka skridskor?`,
      ];
      label = 'Elever'; gl = 'skridskor'; unit = ''; pre = ''; post = 'elever vill åka skridskor.'; who = 'eleverna';
    } else if (kind === 'gift') {
      u = r.step(10, 60, 5);
      text = [
        S`${nm(A, 0)} har ${b * u} ${tag('kr', 0)}.`,
        S`${he(A, 0, true)} använder ${fr(a, b)} av ${tag('pengarna', 0)} till en present.`,
        S`Hur mycket kostar presenten?`,
      ];
      label = A.name; gl = 'present'; unit = 'kr'; pre = 'Presenten kostar'; post = 'kr.'; who = A.name;
    } else {
      u = r.int(10, 40);
      text = [
        S`En ${tag('bok', 0)} har ${b * u} ${tag('sidor', 0)}.`,
        S`${nm(A, 0)} har läst ${fr(a, b)} av ${tag('boken', 0)}.`,
        S`Hur många sidor har ${he(A, 0)} läst?`,
      ];
      label = 'Boken'; gl = 'läst'; unit = ''; pre = `${A.name} har läst`; post = 'sidor.'; who = 'boken';
    }
    const W = b * u, v = a * u;
    if (u === b) return null;
    const calc = [given(nb(b), W), line('1 bit', div(W, b), u, { hint: sv`Dela ${W} i ${b} lika stora bitar.` })];
    if (a > 1) calc.push(line(nb(a), mul(a, u), v, { hint: sv`En bit är ${u}. Hur mycket är ${a} bitar?` }));
    return {
      text, unit,
      who: [{ rows: ['A'], label: who }],
      rows: [{ key: 'A', label, pieces: bits(b, u) }],
      groups: [group('A:g', 'A', range(0, a - 1), gl, { mark: true })],
      build: [
        shape({ A: { bits: b } }, {
          why: `Nämnaren är ${b}: blocket delas i ${b} lika stora bitar.`,
          msg: { A: `Titta på bråket. Nämnaren, talet under strecket, säger hur många lika stora bitar blocket ska ha.` },
        }),
        mark('A', 'A:g', a, {
          why: `Täljaren är ${a}: ${a === 1 ? '1 bit markeras' : `${a} bitar markeras`}.`,
          ask: `Markera bitarna för ${gl}.`,
          msg: 'Täljaren, talet över strecket, säger hur många bitar du ska markera.',
        }),
      ],
      facts: [fact(0, W, 'A')],
      ask: { slot: 'A:g' },
      calc,
      answer: { pre, v, post, traps: {
        [u]: a > 1 ? sv`Det är 1 bit. Hur många bitar markerade du?` : null,
        [W - v]: 'Det är bitarna som inte är markerade.',
        [Math.round(W / a)]: 'Dela med nämnaren, antalet bitar i hela blocket.',
      } },
      check: sv`Kolla: ${v} är ${a} av ${b} lika stora bitar av ${W}. Det stämmer!`,
    };
  });

  /* A fraction is known, the whole is asked for. */
  T('br-hel', 'brak', 1, (r, c) => {
    const [A] = people(r, c, 1);
    const [a, b] = r.pick(FRACS.filter(f => f[0] > 1));
    const kind = r.pick(['class', 'book', 'bike']);
    let u, text, label, gl, unit, pre, post, who;
    if (kind === 'class') {
      u = r.int(3, 6);
      text = [
        S`${fr(a, b)} av ${tag('eleverna', 0)} i en ${tag('klass', 0)} har syskon.`,
        S`Det är ${a * u} ${tag('elever', 0)} som har syskon.`,
        S`Hur många ${tag('elever', 0)} går i klassen?`,
      ];
      label = 'Elever'; gl = 'syskon'; unit = ''; pre = 'Det går'; post = 'elever i klassen.'; who = 'eleverna';
    } else if (kind === 'book') {
      u = r.int(12, 45);
      text = [
        S`${nm(A, 0)} har läst ${fr(a, b)} av en ${tag('bok', 0)}.`,
        S`Det är ${a * u} ${tag('sidor', 0)}.`,
        S`Hur många sidor har boken?`,
      ];
      label = 'Boken'; gl = 'läst'; unit = ''; pre = 'Boken har'; post = 'sidor.'; who = 'boken';
    } else {
      u = r.step(100, 600, 50);
      text = [
        S`${nm(A, 0)} sparar till en ${tag('cykel', 0)}.`,
        S`${he(A, 0, true)} har sparat ${fr(a, b)} av ${tag('priset', 0)}, och det är ${a * u} kr.`,
        S`Hur mycket kostar cykeln?`,
      ];
      label = 'Cykeln'; gl = 'sparat'; unit = 'kr'; pre = 'Cykeln kostar'; post = 'kr.'; who = 'cykeln';
    }
    const P = a * u, W = b * u;
    if (u === a || u === b) return null;
    return {
      text, unit,
      who: [{ rows: ['A'], label: who }],
      rows: [{ key: 'A', label, pieces: bits(b, u) }],
      groups: [group('A:g', 'A', range(0, a - 1), gl, { mark: true })],
      build: [
        shape({ A: { bits: b } }, {
          why: `Hela blocket är ${who}. Nämnaren är ${b}: blocket delas i ${b} lika stora bitar.`,
          msg: { A: 'Nämnaren, talet under bråkstrecket, säger hur många lika stora bitar blocket ska ha.' },
        }),
        mark('A', 'A:g', a, {
          why: `Täljaren är ${a}: ${a} bitar markeras, ${gl}.`,
          ask: `Markera bitarna för ${gl}.`,
          msg: 'Täljaren, talet över bråkstrecket, säger hur många bitar du ska markera.',
        }),
      ],
      facts: [fact(1, P, 'A:g', { hint: `${fmt(P)} är bara de markerade bitarna.` })],
      ask: { slot: 'A' },
      calc: [
        given(nb(a), P),
        line('1 bit', div(P, a), u, { hint: sv`${a} bitar är ${P}. Dela med ${a}.` }),
        line(nb(b), mul(b, u), W, { hint: sv`Hela blocket har ${b} bitar.` }),
      ],
      answer: { pre, v: W, post, traps: {
        [u]: 'Det är 1 bit. Hur många bitar har hela blocket?',
        [P]: 'Det är bara de markerade bitarna. Frågan gäller hela blocket.',
        [(b - a) * u]: 'Det är bitarna som inte är markerade. Frågan gäller hela blocket.',
      } },
      check: sv`Kolla: ${fracWords(a, b)} av ${W}: ${W} / ${b} = ${u}, och ${a} ${DOT} ${u} = ${P}. Det stämmer!`,
    };
  });

  /* A fraction is used, what is left? */
  T('br-kvar', 'brak', 2, (r, c) => {
    const [A] = people(r, c, 1);
    const [a, b] = r.pick(FRACS);
    const kind = r.pick(['money', 'book']);
    let u, text, label, gl, unit, pre, post, who;
    if (kind === 'money') {
      u = r.step(15, 80, 5);
      const g = r.pick(GOODS);
      text = [
        S`${nm(A, 0)} hade ${b * u} ${tag('kr', 0)}.`,
        S`${he(A, 0, true)} köpte ${g.en} ${g.sg} för ${fr(a, b)} av ${tag('pengarna', 0)}.`,
        S`Hur mycket ${tag('pengar', 0)} hade ${he(A, 0)} kvar?`,
      ];
      label = A.name; gl = g.sg; unit = 'kr'; pre = `${A.name} hade`; post = 'kr kvar.'; who = A.name;
    } else {
      u = r.int(10, 40);
      text = [
        S`En ${tag('bok', 0)} har ${b * u} ${tag('sidor', 0)}.`,
        S`${nm(A, 0)} har läst ${fr(a, b)} av ${tag('den', 0)}.`,
        S`Hur många sidor har ${he(A, 0)} kvar att läsa?`,
      ];
      label = 'Boken'; gl = 'läst'; unit = ''; pre = `${A.name} har`; post = 'sidor kvar att läsa.'; who = 'boken';
    }
    const W = b * u, v = (b - a) * u;
    if (u === b) return null;
    const restPieces = range(a, b - 1);
    const calc = [given(nb(b), W), line('1 bit', div(W, b), u, { hint: sv`Dela ${W} i ${b} lika stora bitar.` })];
    if (b - a > 1) calc.push(line(nb(b - a), mul(b - a, u), v, { hint: `Hur många bitar är inte markerade?` }));
    return {
      text, unit,
      who: [{ rows: ['A'], label: who }],
      rows: [{ key: 'A', label, pieces: bits(b, u) }],
      groups: [
        group('A:g', 'A', range(0, a - 1), gl, { mark: true }),
        group('A:kvar', 'A', restPieces, 'kvar'),
      ],
      build: [
        shape({ A: { bits: b } }, {
          why: `Nämnaren är ${b}: blocket delas i ${b} lika stora bitar.`,
          msg: { A: 'Nämnaren, talet under bråkstrecket, säger hur många lika stora bitar blocket ska ha.' },
        }),
        mark('A', 'A:g', a, {
          why: `Täljaren är ${a}: ${a === 1 ? '1 bit' : `${a} bitar`} markeras. Resten är kvar.`,
          ask: `Markera bitarna för ${gl}.`,
          msg: 'Täljaren, talet över bråkstrecket, säger hur många bitar du ska markera.',
        }),
      ],
      facts: [fact(0, W, 'A')],
      ask: { slot: b - a > 1 ? 'A:kvar' : `A.${b - 1}` },
      calc,
      answer: { pre, v, post, traps: {
        [a * u]: 'Det är de markerade bitarna. Frågan gäller det som är kvar.',
        [u]: b - a > 1 ? 'Det är 1 bit. Hur många bitar är kvar?' : null,
      } },
      check: sv`Kolla: ${a * u} + ${v} = ${W}. Det stämmer!`,
    };
  });

  /* A fraction of the rest: an extra block under the rest. */
  T('re-resten', 'rest', 1, (r) => {
    const b = r.pick([3, 3, 4, 5]);
    const d = r.pick([2, 3, 4, 5].filter(x => x !== b - 1));
    const cc = r.int(1, d - 1);
    const m = r.int(1, 3);
    const e = d * m;                    // one bit of the first block
    const W = b * e, rest = (b - 1) * e, f = rest / d;
    const kind = r.pick(['break', 'club']);
    let text, gl1, gl2, pre, post;
    if (kind === 'break') {
      text = [
        S`Det går ${W} ${tag('elever', 0)} i årskurs 6.`,
        S`${fr(1, b)} av dem spelar fotboll på rasten.`,
        S`${fr(cc, d)} av resten spelar pingis.`,
        S`Hur många ${tag('elever', 0)} spelar pingis?`,
      ];
      gl1 = 'fotboll'; gl2 = 'pingis'; pre = ''; post = 'elever spelar pingis.';
    } else {
      text = [
        S`I en klubb finns det ${W} ${tag('barn', 0)}.`,
        S`${fr(1, b)} av ${tag('barnen', 0)} spelar handboll.`,
        S`${fr(cc, d)} av resten dansar.`,
        S`Hur många ${tag('barn', 0)} dansar?`,
      ];
      gl1 = 'handboll'; gl2 = 'dansar'; pre = ''; post = 'barn dansar.';
    }
    if (W > 130 || cc * f === e) return null;
    const label = kind === 'break' ? 'Elever' : 'Barn';
    const calc = [
      given(nb(b), W),
      line('1 bit', div(W, b), e, { hint: sv`Dela ${W} i ${b} lika stora bitar.` }),
      line(`Resten, ${nb(b - 1)}`, mul(b - 1, e), rest, { hint: `Hur många bitar är inte markerade?` }),
      given(nd(d), rest),
      line('1 del', div(rest, d), f, { hint: sv`Resten delas i ${d} lika stora delar.` }),
    ];
    if (cc > 1) calc.push(line(nd(cc), mul(cc, f), cc * f, { hint: sv`En del är ${f}. Hur mycket är ${cc} delar?` }));
    return {
      text, unit: '',
      who: [{ rows: ['A'], label: label.toLowerCase() === 'elever' ? 'eleverna' : 'barnen' }],
      rows: [
        { key: 'A', label, pieces: bits(b, e) },
        { key: 'R', label: 'Resten', pieces: bits(d, f), under: { row: 'A', from: 1, to: b - 1 }, unit: 'del' },
      ],
      groups: [
        group('A:g', 'A', [0], gl1, { mark: true }),
        group('A:rest', 'A', range(1, b - 1), 'resten', { link: 'R' }),
        group('R:g', 'R', range(0, cc - 1), gl2, { mark: true }),
      ],
      build: [
        shape({ A: { bits: b } }, {
          why: `Nämnaren är ${b}: blocket delas i ${b} lika stora bitar.`,
          msg: { A: 'Titta på det första bråket. Nämnaren säger hur många lika stora bitar blocket ska ha.' },
        }),
        mark('A', 'A:g', 1, {
          why: `Täljaren är 1: 1 bit markeras, ${gl1}. Resten är ${nb(b - 1)}.`,
          ask: `Markera biten för ${gl1}.`,
          msg: 'Täljaren i det första bråket säger hur många bitar du ska markera.',
        }),
        shape({ R: { bits: d } }, {
          why: `Resten ska delas i ${d} lika stora delar. Det ritar vi i ett extrablock under resten.`,
          ask: `Dela extrablocket under resten i lika stora delar.`,
          msg: { R: 'Titta på det andra bråket. Nämnaren säger hur många lika stora delar resten ska delas i.' },
        }),
        mark('R', 'R:g', cc, {
          why: `Täljaren är ${cc}: ${nd(cc)} markeras, ${gl2}.`,
          ask: `Markera delarna för ${gl2}.`,
          msg: 'Täljaren i det andra bråket säger hur många delar du ska markera.',
        }),
      ],
      facts: [fact(0, W, 'A')],
      ask: { slot: 'R:g' },
      calc,
      answer: { pre, v: cc * f, post, traps: {
        [e]: `Det är 1 bit av det första blocket, de som ${gl1 === 'fotboll' ? 'spelar fotboll' : 'spelar handboll'}.`,
        [rest]: 'Det är hela resten. Frågan gäller bara de markerade delarna.',
        [f]: cc > 1 ? 'Det är 1 del. Hur många delar markerade du?' : null,
      } },
      check: sv`Kolla: ${e} + ${rest} = ${W}, och ${cc * f} är ${fracWords(cc, d)} av ${rest}. Det stämmer!`,
    };
  });

  /* A fraction of the rest, when the rest's own bits will do. */
  T('re-kvar', 'rest', 2, (r, c) => {
    const [A] = people(r, c, 1);
    const b = r.pick([3, 4, 4, 5]);
    const d = b - 1;
    const cc = r.int(1, d - 1);
    const u = r.step(30, 120, 10);
    const W = b * u;
    const left = d - cc;
    const [g, gDef] = r.pick([['kläder', 'kläderna'], ['godis', 'godiset'], ['böcker', 'böckerna'], ['spel', 'spelen']]);
    return {
      text: [
        S`${nm(A, 0)} hade ${W} ${tag('kr', 0)}.`,
        S`${he(A, 0, true)} använde ${fr(1, b)} av ${tag('pengarna', 0)} till en present och ${fr(cc, d)} av resten till ${g}.`,
        S`Hur mycket ${tag('pengar', 0)} hade ${he(A, 0)} kvar?`,
      ],
      unit: 'kr',
      who: [{ rows: ['A'], label: A.name }],
      rows: [{ key: 'A', label: A.name, pieces: bits(b, u) }],
      groups: [
        group('A:present', 'A', [0], 'present', { mark: true }),
        group('A:g', 'A', range(1, cc), g, { mark: true }),
        group('A:kvar', 'A', range(cc + 1, b - 1), 'kvar'),
      ],
      build: [
        shape({ A: { bits: b } }, {
          why: `Nämnaren i det första bråket är ${b}: ${b} lika stora bitar.`,
          msg: { A: 'Nämnaren i det första bråket säger hur många lika stora bitar blocket ska ha.' },
        }),
        mark('A', 'A:present', 1, {
          why: `1 bit är presenten. Resten är ${nb(d)}.`,
          ask: 'Markera biten för presenten.',
          msg: 'Täljaren i det första bråket säger hur många bitar presenten är.',
        }),
        mark('A', 'A:g', cc, {
          why: `Resten är ${d} bitar, så ${fracWords(cc, d)} av resten är ${nb(cc)}. Här behövs inget extrablock.`,
          ask: `Markera bitarna för ${g}: ${fracWords(cc, d)} av resten.`,
          msg: `Resten är ${d} bitar. Hur många av dem är ${fracWords(cc, d)} av resten?`,
        }),
      ],
      facts: [fact(0, W, 'A')],
      ask: { slot: left > 1 ? 'A:kvar' : `A.${b - 1}` },
      calc: [
        given(nb(b), W),
        line('1 bit', div(W, b), u, { hint: sv`Dela ${W} i ${b} lika stora bitar.` }),
        ...(left > 1 ? [line(nb(left), mul(left, u), left * u, { hint: 'Hur många bitar är inte markerade?' })] : []),
      ],
      answer: { pre: `${A.name} hade`, v: left * u, post: 'kr kvar.', traps: {
        [d * u]: `Det är resten efter presenten. Sedan använde ${A.he} en del av resten också.`,
        [cc * u]: `Det är vad ${gDef} kostade.`,
      } },
      check: sv`Kolla: ${u} + ${cc * u} + ${left * u} = ${W}. Det stämmer!`,
    };
  });

  /* Before and after: got some, how many before? */
  T('fo-fick', 'fore', 1, (r, c) => {
    const [A] = people(r, c, 1);
    const th = r.pick(COLLECT);
    const u = r.int(15, 70), g = r.int(6, 30), N = u + g;
    const giver = r.pick(['mormor', 'farfar', 'kusin', 'storasyster', 'granne']);
    if (u === g) return null;
    return {
      text: [
        S`${nm(A, 0)} hade några ${tag(th.pl, 0)}.`,
        S`${he(A, 0, true)} fick ${g} ${th.pl} av sin ${giver}.`,
        S`Nu har ${he(A, 0)} ${N} ${th.pl}.`,
        S`Hur många ${th.pl} hade ${he(A, 0)} från början?`,
      ],
      unit: '',
      who: [{ rows: ['F', 'E'], label: A.name }],
      rows: [
        { key: 'F', label: 'Före', ref: 'blocket före', pieces: [bit(u)] },
        { key: 'E', label: 'Efter', ref: 'blocket efter', pieces: [bit(u), del(g, 'fick')] },
      ],
      build: [shape({ F: { bits: 1 }, E: { bits: 1, x: 1 } }, {
        why: `Ett block för före och ett för efter. Efter har ${A.name} lika många som före och ${g} till.`,
        msg: {
          F: 'Före vet vi inte hur många det var. Ett block med en bit räcker.',
          E: `Efter har ${A.name} det som fanns före och det ${A.he} fick. Behövs det en annan bit?`,
        },
      })],
      facts: [fact(1, g, 'E.1'), fact(2, N, 'E')],
      ask: { slot: 'F' },
      calc: [line('Före', minus(N, g), u, { hint: 'Ta bort det som kom till.' })],
      answer: { pre: `${A.name} hade`, v: u, post: `${th.pl} från början.`, traps: {
        [N + g]: `${cap(A.he)} fick ${th.pl}, så före hade ${A.he} färre än nu.`,
        [N]: 'Det är så många det är nu, efter.',
      } },
      check: sv`Kolla: ${u} + ${g} = ${N}. Det stämmer!`,
    };
  });

  /* Before and after: gave some away, how many before? */
  T('fo-gav', 'fore', 1, (r, c) => {
    const [A] = people(r, c, 1);
    const th = r.pick(COLLECT);
    const N = r.int(15, 70), g = r.int(6, 30), u = N + g;
    const taker = r.pick(['lillebror', 'lillasyster', 'kompis', 'kusin']);
    if (N === g) return null;
    return {
      text: [
        S`${nm(A, 0)} hade några ${tag(th.pl, 0)}.`,
        S`${he(A, 0, true)} gav ${g} ${th.pl} till sin ${taker}.`,
        S`Nu har ${he(A, 0)} ${N} ${th.pl} kvar.`,
        S`Hur många ${th.pl} hade ${he(A, 0)} från början?`,
      ],
      unit: '',
      who: [{ rows: ['F', 'E'], label: A.name }],
      rows: [
        { key: 'F', label: 'Före', ref: 'blocket före', pieces: [bit(N), del(g, 'gav')] },
        { key: 'E', label: 'Efter', ref: 'blocket efter', pieces: [bit(N)] },
      ],
      build: [shape({ F: { bits: 1, x: 1 }, E: { bits: 1 } }, {
        why: `Före hade ${A.name} det som är kvar och det ${A.he} gav bort: blocket före är längst.`,
        msg: {
          F: `Före hade ${A.name} mer än nu. Behövs det en annan bit, det ${A.he} gav bort?`,
          E: 'Efter finns bara det som är kvar. Ett block med en bit räcker.',
        },
      })],
      facts: [fact(1, g, 'F.1'), fact(2, N, 'E')],
      ask: { slot: 'F' },
      calc: [line('Före', plus(N, g), u, { hint: 'Lägg till det som gavs bort.' })],
      answer: { pre: `${A.name} hade`, v: u, post: `${th.pl} från början.`, traps: {
        [N - g]: `${cap(A.he)} gav bort ${th.pl}, så före hade ${A.he} fler än nu.`,
        [N]: 'Det är så många det är nu, efter.',
      } },
      check: sv`Kolla: ${u} ${MINUS} ${g} = ${N}. Det stämmer!`,
    };
  });

  /* Before and after: so many times as many, gave some away, then equal. */
  T('fo-lika', 'fore', 2, (r, c) => {
    const [A, B] = people(r, c, 2);
    const th = r.pick(COLLECT);
    const k = r.int(2, 4), u = r.int(6, 20);
    const G = (k - 1) * u;
    if (u === k || G === u) return null;
    return {
      text: [
        S`${nm(A, 0)} hade ${times(k)} så många ${th.pl} som ${nm(B, 1)}.`,
        S`Sedan gav ${nm(A, 0)} bort ${G} ${th.pl}.`,
        S`Då hade de lika många.`,
        S`Hur många ${th.pl} hade ${nm(B, 1)}?`,
      ],
      unit: '',
      who: [{ rows: ['A'], label: A.name }, { rows: ['B'], label: B.name }],
      rows: [
        { key: 'A', label: A.name, pieces: bits(k, u) },
        { key: 'B', label: B.name, pieces: [bit(u)] },
      ],
      groups: [group('A:gav', 'A', range(1, k - 1), 'gav bort', { mark: true })],
      build: [
        shape({ A: { bits: k }, B: { bits: 1 } }, {
          why: `${A.name} hade ${times(k)} så många: ${k} bitar mot 1 för ${B.name}.`,
          msg: {
            A: `${cap(times(k))} så många: hur många bitar ska ${A.name} ha?`,
            B: `${B.name} hade minst: 1 bit.`,
          },
        }),
        mark('A', 'A:gav', k - 1, {
          why: `Efteråt hade de lika många. Då har ${A.name} 1 bit kvar, lika mycket som ${B.name}. ${k === 2 ? 'Den andra biten' : `De andra ${k - 1} bitarna`} gav ${A.he} bort.`,
          ask: `Markera bitarna som ${A.name} gav bort.`,
          msg: `Efteråt hade de lika många. Hur mycket måste ${A.name} då ha gett bort?`,
        }),
      ],
      facts: [fact(1, G, 'A:gav')],
      ask: { slot: 'B' },
      calc: [
        given(nb(k - 1), G),
        ...(k > 2 ? [line('1 bit', div(G, k - 1), u, { hint: sv`${k - 1} bitar är ${G}. Dela med ${k - 1}.` })] : [line('1 bit', String(G), u, { hint: 'Biten som gavs bort är lika stor som de andra.' })]),
      ],
      answer: { pre: `${B.name} hade`, v: u, post: `${th.pl}.`, traps: {
        [G + u]: 'Är det fler än det som gavs bort?',
        [k * u]: `Det är vad ${A.name} hade från början.`,
      } },
      check: sv`Kolla: ${A.name} hade ${k * u}, gav bort ${G} och fick kvar ${u}, lika många som ${B.name}. Det stämmer!`,
    };
  });

  /* Ratio: one part known. */
  T('fh-del', 'forh', 1, (r) => {
    const kind = r.pick(['dance', 'juice']);
    const [p, q] = kind === 'juice'
      ? r.pick([[1, 4], [1, 5], [1, 6], [2, 5], [1, 3], [2, 7]])
      : r.pick([[2, 3], [3, 4], [3, 5], [2, 5], [4, 3], [5, 2], [3, 2], [1, 3]]);
    const u = kind === 'juice' ? r.int(2, 4) : r.int(2, 6);
    if (u === p || u === q || p * u === q) return null;
    let text, who, rows, pre, post, unit;
    if (kind === 'dance') {
      text = [
        S`I en dansgrupp är förhållandet mellan antalet ${tag('pojkar', 0)} och ${tag('flickor', 1)} ${p} : ${q}.`,
        S`Det är ${q * u} ${tag('flickor', 1)} i gruppen.`,
        S`Hur många ${tag('pojkar', 0)} är det?`,
      ];
      who = [{ rows: ['A'], label: 'pojkarna' }, { rows: ['B'], label: 'flickorna' }];
      rows = [{ key: 'A', label: 'Pojkar', pieces: bits(p, u) }, { key: 'B', label: 'Flickor', pieces: bits(q, u) }];
      pre = 'Det är'; post = 'pojkar.'; unit = '';
    } else {
      text = [
        S`Till ${tag('saft', 0)} blandar man ${tag('koncentrat', 0)} och ${tag('vatten', 1)} i förhållandet ${p} : ${q}.`,
        S`Man använder ${q * u} dl ${tag('vatten', 1)}.`,
        S`Hur mycket ${tag('koncentrat', 0)} behövs?`,
      ];
      who = [{ rows: ['A'], label: 'koncentratet' }, { rows: ['B'], label: 'vattnet' }];
      rows = [{ key: 'A', label: 'Koncentrat', pieces: bits(p, u) }, { key: 'B', label: 'Vatten', pieces: bits(q, u) }];
      pre = 'Det behövs'; post = 'dl koncentrat.'; unit = 'dl';
    }
    const calc = [given(nb(q), q * u), line('1 bit', div(q * u, q), u, { hint: sv`${q} bitar är ${q * u}. Dela med ${q}.` })];
    if (p > 1) calc.push(line(nb(p), mul(p, u), p * u, { hint: `Den första sorten har ${p} bitar.` }));
    return {
      text, unit, who, rows,
      build: [shape({ A: { bits: p }, B: { bits: q } }, {
        why: `Förhållandet ${p} : ${q} betyder ${nb(p)} mot ${nb(q)}, och alla bitarna är lika stora.`,
        msg: {
          A: `Det första talet i förhållandet säger hur många bitar ${rows[0].label.toLowerCase()} ska ha.`,
          B: `Det andra talet i förhållandet säger hur många bitar ${rows[1].label.toLowerCase()} ska ha.`,
        },
      })],
      facts: [fact(1, q * u, 'B')],
      ask: { slot: 'A' },
      calc,
      answer: { pre, v: p * u, post, traps: {
        [u]: p > 1 ? `Det är 1 bit. Hur många bitar har ${rows[0].label.toLowerCase()}?` : null,
        [(p + q) * u]: 'Det är båda tillsammans.',
      } },
      check: sv`Kolla: ${p * u} : ${q * u} är samma förhållande som ${p} : ${q}. Det stämmer!`,
    };
  });

  /* Ratio: the total is known. */
  T('fh-tot', 'forh', 2, (r, c) => {
    const [A, B] = people(r, c, 2);
    const [p, q] = r.pick([[2, 3], [3, 4], [3, 5], [2, 5], [1, 3], [1, 4], [3, 2], [4, 3]]);
    const u = r.step(10, 60, 5);
    const W = (p + q) * u;
    const askA = r.chance(0.5);
    const X = askA ? A : B;
    if (u === p || u === q) return null;
    return {
      text: [
        S`${nm(A, 0)} och ${nm(B, 1)} delar på ${W} kr i förhållandet ${p} : ${q}.`,
        S`Hur mycket får ${nm(X, askA ? 0 : 1)}?`,
      ],
      unit: 'kr',
      who: [{ rows: ['A'], label: A.name }, { rows: ['B'], label: B.name }],
      rows: [
        { key: 'A', label: A.name, pieces: bits(p, u) },
        { key: 'B', label: B.name, pieces: bits(q, u) },
      ],
      build: [shape({ A: { bits: p }, B: { bits: q } }, {
        why: `Förhållandet ${p} : ${q}: ${A.name} får ${nb(p)} och ${B.name} ${nb(q)}, alla lika stora.`,
        msg: {
          A: `Det första talet i förhållandet hör till ${A.name}.`,
          B: `Det andra talet i förhållandet hör till ${B.name}.`,
        },
      })],
      facts: [fact(0, W, 'T')],
      ask: { slot: askA ? 'A' : 'B' },
      calc: [
        given(nb(p + q), W),
        line('1 bit', div(W, p + q), u, { hint: sv`Det är ${p + q} lika stora bitar i allt.` }),
        ...((askA ? p : q) > 1 ? [line(nb(askA ? p : q), mul(askA ? p : q, u), (askA ? p : q) * u, { hint: `${X.name} har ${nb(askA ? p : q)}.` })] : []),
      ],
      answer: { pre: `${X.name} får`, v: (askA ? p : q) * u, post: 'kr.', traps: {
        [(askA ? q : p) * u]: `Det är vad ${askA ? B.name : A.name} får.`,
        [Math.round(W / 2)]: 'Det delas inte lika. Räkna bitarna.',
      } },
      check: sv`Kolla: ${p * u} + ${q * u} = ${W}. Det stämmer!`,
    };
  });

  /* Per cent of a price. */
  const PCT = [[10, 10, 1], [20, 5, 1], [25, 4, 1], [50, 2, 1], [30, 10, 3], [40, 5, 2], [60, 5, 3], [75, 4, 3]];
  T('pc-del', 'forh', 1, (r) => {
    const [pc, n, k] = r.pick(PCT);
    const th = r.pick([['jacka', 'jackan'], ['cykelhjälm', 'cykelhjälmen'], ['skateboard', 'skateboarden'], ['ryggsäck', 'ryggsäcken']]);
    const u = n === 10 ? r.step(20, 90, 10) : r.step(25, 200, 25);
    const W = n * u;
    const askNow = r.chance(0.6);
    const v = askNow ? (n - k) * u : k * u;
    if (u === n || u === pc) return null;
    const calc = [given(nb(n), W), line('1 bit', div(W, n), u, { hint: sv`Hela blocket är 100 %. Dela ${W} i ${n} bitar.` })];
    const vb = askNow ? n - k : k;
    if (vb > 1) calc.push(line(nb(vb), mul(vb, u), v, { hint: askNow ? 'Hur många bitar är kvar av priset?' : 'Hur många bitar är rabatten?' }));
    return {
      text: [
        S`En ${tag(th[0], 0)} kostar ${W} kr.`,
        S`På rean sänks ${tag('priset', 0)} med ${pc} %.`,
        askNow ? S`Hur mycket kostar ${tag(th[1], 0)} på rean?` : S`Hur många kronor billigare blir ${tag(th[1], 0)}?`,
      ],
      unit: 'kr',
      who: [{ rows: ['A'], label: th[1] }],
      rows: [{ key: 'A', label: 'Priset', pieces: bits(n, u) }],
      groups: [
        group('A:g', 'A', range(0, k - 1), 'rabatt', { mark: true }),
        group('A:kvar', 'A', range(k, n - 1), 'nytt pris'),
      ],
      build: [
        shape({ A: { bits: n } }, {
          why: `Hela blocket är 100 %. ${100 / n} % är en ${PARTS[n] ? PARTS[n][0] : 'halv'}: blocket delas i ${n} lika stora bitar.`,
          msg: { A: `Hur många gånger får ${100 / n} % plats i 100 %? Så många bitar behövs.` },
          ask: `Dela priset i bitar som är ${100 / n} % var.`,
        }),
        mark('A', 'A:g', k, {
          why: `${pc} % är ${nb(k)} av ${n}: det är rabatten.`,
          ask: `Markera bitarna för rabatten, ${pc} %.`,
          msg: `Varje bit är ${100 / n} %. Hur många bitar blir ${pc} %?`,
        }),
      ],
      facts: [fact(0, W, 'A')],
      ask: { slot: askNow ? (n - k > 1 ? 'A:kvar' : `A.${n - 1}`) : (k > 1 ? 'A:g' : 'A.0') },
      calc,
      answer: askNow
        ? { pre: `${cap(th[1])} kostar`, v, post: 'kr på rean.', traps: { [k * u]: 'Det är rabatten, hur mycket billigare den blir.', [W - pc]: 'Procent är inte kronor. Räkna med bitarna.' } }
        : { pre: `${cap(th[1])} blir`, v, post: 'kr billigare.', traps: { [(n - k) * u]: 'Det är det nya priset. Frågan gäller rabatten.', [pc]: 'Det är procent. Frågan gäller kronor.' } },
      check: sv`Kolla: ${k * u} + ${(n - k) * u} = ${W}. Det stämmer!`,
    };
  });

  /* ── Making a problem ─────────────────────────────────────────────────── */

  const byId = Object.create(null);
  for (const t of TEMPLATES) byId[t.id] = t;

  const COLORS = 4;

  /* What make() adds to a template's problem: the links between the text
     and the model, and the parts every problem has. */
  function finish(t, seed, spec) {
    const p = Object.assign({ groups: [], unit: '', say: {} }, spec);
    p.tid = t.id; p.type = t.type; p.level = t.level; p.seed = seed;
    p.rows.forEach((row, i) => { row.color = i % COLORS; });
    p.multi = p.rows.filter(rw => !rw.under).length > 1;
    p.q = p.text.length - 1;
    p.facts.forEach((f, i) => {
      const tok = p.text[f.s].find(tk => tk.t === 'n' && tk.v === f.v && tk.fact === undefined);
      if (!tok) throw new Error(`${t.id}: fact ${f.v} is not in sentence ${f.s}`);
      tok.fact = i;
    });
    for (const g of p.groups) g.row = g.row || g.id.split(':')[0];
    // A trap says why a wrong answer is wrong: none for the right one, none without words.
    for (const k of Object.keys(p.answer.traps || {})) if (!p.answer.traps[k] || Number(k) === p.answer.v) delete p.answer.traps[k];
    return p;
  }

  /* The problem of template tid made from seed (the next seeds if that one
     will not do). own: { name, pron }, the pupil's own name, or null. */
  function make(tid, seed, own) {
    const t = byId[tid];
    if (!t) throw new Error(`No template "${tid}"`);
    let s = (seed >>> 0) || 1;
    for (let tries = 0; tries < 200; tries++) {
      const spec = t.make(rng(s), { own: own && own.name ? own : null });
      if (spec && !spec.text.some(sent => sent.some(tk => tk.t === 'n' && tk.v === spec.answer.v))) return finish(t, s, spec);
      s = (Math.imul(s, 2654435761) + 0x9e3779b9) >>> 0 || 1;
    }
    throw new Error(`${tid}: no problem from seed ${seed}`);
  }

  /* The templates of a kind, at a level or below. */
  const templatesOf = (type, level) => TEMPLATES.filter(t => t.type === type && t.level <= (level || 2)).map(t => t.id);

  /* ── Places in the model ──────────────────────────────────────────────── */

  const rowOf = (p, key) => p.rows.find(rw => rw.key === key);

  /* The pieces a slot covers: { row, pieces } or null for 'T'. */
  function slotPieces(p, id) {
    if (id === 'T') return null;
    const m = /^([A-Z])(?:\.(\d+|bit)|:(.+))?$/.exec(id);
    if (!m) return undefined;
    const row = rowOf(p, m[1]);
    if (!row) return undefined;
    if (m[2] === 'bit') return { row, pieces: null };
    if (m[2] !== undefined) return { row, pieces: [Number(m[2])] };
    if (m[3] !== undefined) {
      const g = p.groups.find(gr => gr.id === id);
      return g ? { row, pieces: g.pieces.slice() } : undefined;
    }
    return { row, pieces: row.pieces.map((_, i) => i) };
  }

  /* One name for each place: the row for all of a row, the piece for one
     piece, the pieces otherwise. */
  function canon(p, id) {
    if (id === 'T') return 'T';
    const sp = slotPieces(p, id);
    if (!sp) return id;
    if (!sp.pieces) return id;
    const ps2 = sp.pieces.slice().sort((x, y) => x - y);
    if (ps2.length === sp.row.pieces.length) return sp.row.key;
    if (ps2.length === 1) return `${sp.row.key}.${ps2[0]}`;
    return `${sp.row.key}[${ps2.join(',')}]`;
  }

  /* Is `got` the place `want` names? 'A.bit' is any single bit of A. */
  function sameSlot(p, want, got) {
    if (/\.bit$/.test(want)) {
      const row = rowOf(p, want[0]);
      const m = /^([A-Z])\.(\d+)$/.exec(canon(p, got)) || (row && row.pieces.length === 1 && canon(p, got) === row.key ? [0, row.key, '0'] : null);
      if (!m || m[1] !== want[0]) return false;
      const piece = row.pieces[Number(m[2])];
      return !!piece && piece.k === 'bit';
    }
    return canon(p, want) === canon(p, got);
  }

  /* What a place is, as a noun: "Där står ___." */
  function slotNoun(p, id) {
    if (id === 'T') return p.rows.length > 2 ? 'alla blocken tillsammans' : 'båda blocken tillsammans';
    const sp = slotPieces(p, id);
    if (!sp) return 'den platsen';
    const row = sp.row;
    const whole = row.ref || (p.multi ? `blocket för ${row.label}` : 'hela blocket');
    if (!sp.pieces) return 'en av bitarna';
    if (sp.pieces.length === row.pieces.length) return row.under ? 'hela extrablocket' : whole;
    const g = p.groups.find(gr => gr.row === row.key && gr.pieces.length === sp.pieces.length && gr.pieces.every(i => sp.pieces.includes(i)));
    if (g) return g.pieces.length > 1 ? `bitarna ”${g.label}”` : `biten ”${g.label}”`;
    if (sp.pieces.length === 1) {
      const piece = row.pieces[sp.pieces[0]];
      if (piece && piece.name) return `biten ”${piece.name}”`;
      if (piece && piece.k === 'del') return 'biten som sticker ut';
      return row.under ? 'en av delarna i extrablocket' : 'en bit';
    }
    return `${nb(sp.pieces.length)}`;
  }

  /* Where a number is written, after "Vi skriver 17 ___." */
  function slotAt(p, id) {
    if (id === 'T') return 'vid klammern runt båda blocken';
    if (/\.bit$/.test(id)) return 'i en av bitarna';
    const noun = slotNoun(p, id);
    if (noun === 'hela blocket') return 'över hela blocket';
    if (/^(blocket|hela extrablocket)/.test(noun)) return `vid ${noun}`;
    if (/^bitarna/.test(noun)) return `under ${noun}`;
    return `i ${noun}`;
  }

  /* ── Is it right ──────────────────────────────────────────────────────── */

  /* A shape the pupil drew, { A: { bits, x } }, against one build step. */
  function checkShape(p, sub, shapeNow) {
    for (const key of Object.keys(sub.rows)) {
      const want = sub.rows[key];
      const got = shapeNow[key] || { bits: 1, x: 0 };
      const row = rowOf(p, key);
      const msg = sub.msg && sub.msg[key];
      if (want.n !== undefined) {
        if (got.bits + got.x !== want.n) return { ok: false, row: key, msg: msg || `Hur många delar ska blocket för ${row.label} ha?` };
        continue;
      }
      if (got.bits !== want.bits) {
        return { ok: false, row: key, msg: msg || (got.bits < want.bits ? `Behöver blocket för ${row.label} fler lika stora bitar?` : `Har blocket för ${row.label} för många lika stora bitar?`) };
      }
      if (got.x !== (want.x || 0)) {
        return { ok: false, row: key, msg: msg || (got.x < (want.x || 0) ? `Behöver ${row.label} en annan bit, till exempel en skillnad?` : `Behöver ${row.label} verkligen en annan bit?`) };
      }
    }
    return { ok: true };
  }

  function checkMark(p, sub, count) {
    return count === sub.count ? { ok: true } : { ok: false, msg: sub.msg || 'Hur många bitar ska markeras?' };
  }

  /* ── Lessons ──────────────────────────────────────────────────────────── */

  /*
     What each chapter explains: cards of text with a picture. In the text
     **x** is bold and [3/5] a fraction. A picture is a model as the page
     draws one ({ rows, groups, values }).
  */
  const pic = (rows, values, groups, more) => Object.assign({ rows: rows.map((rw, i) => Object.assign({ color: i % COLORS }, rw)), values: values || {}, groups: groups || [] }, more || {});

  const LEARN = {
    start: [
      { title: 'Rita uppgiften', text: [
        'Blockmodellen är ett sätt att rita en textuppgift. Du ritar **block**, avlånga rektanglar, som visar hur mycket något är.',
        'När bilden är klar ser du ofta direkt hur du ska räkna.',
      ], pic: pic([{ key: 'A', label: 'Ella', pieces: [bit(58)] }, { key: 'B', label: 'Moa', pieces: [bit(58), del(17)] }], { A: '58', 'B.1': '17', B: '?' }) },
      { title: 'Lika långt är lika mycket', text: [
        'Block för lika mycket ritar du lika långa. Har någon **tre gånger så mycket**, blir blocket tre gånger så långt: tre lika stora **bitar**.',
      ], pic: pic([{ key: 'A', label: 'Moa', pieces: [bit(12)] }, { key: 'B', label: 'Ella', pieces: bits(3, 12) }], {}) },
      { title: 'Frågetecknet visar vad du söker', text: [
        'Talen du vet skriver du där de hör hemma i bilden. Det du ska ta reda på markerar du med ett **frågetecken**.',
        'Då vet du hela tiden vad du letar efter.',
      ], pic: pic([{ key: 'A', label: 'Moa', pieces: [bit(12)] }, { key: 'B', label: 'Ella', pieces: bits(3, 12) }], { T: '48', B: '?' }) },
      { title: 'Varför rita?', text: [
        'När allt står i bilden behöver du inte hålla det i huvudet. Då räcker tanken till att fundera på hur du ska räkna.',
        'Bilden hjälper dig också att se om svaret är **rimligt**.',
      ], mascot: true },
    ],
    steps: [
      { title: 'Åtta steg, varje gång', text: [
        'Stegen är desamma i varje uppgift. Kan du dem utantill vet du alltid vad du ska göra härnäst.',
      ], steps: true },
    ],
    delhel: [
      { title: 'Delar och helhet', text: [
        'Ibland består något av flera **delar** som tillsammans är en **helhet**. Rita ett block för helheten och dela det i delarna.',
      ], pic: pic([{ key: 'A', label: 'Sidor', pieces: [del(128, 'lördag'), del(95, 'söndag')] }], { 'A.0': '128', 'A.1': '95', A: '?' }), words: ['tillsammans', 'sammanlagt', 'totalt', 'kvar', 'resten'] },
      { title: 'Två sätt att räkna', text: [
        'Vet du alla delarna? **Lägg ihop** dem, så får du helheten: 128 + 95 = 223.',
        'Vet du helheten och en del? **Ta bort** delen från helheten, så får du den andra delen: 245 − 129 = 116.',
      ], pic: pic([{ key: 'A', label: 'Pengar', pieces: [del(129, 'bok'), del(116, 'kvar')] }], { A: '245', 'A.0': '129', 'A.1': '?' }) },
    ],
    jmf: [
      { title: 'Två block under varandra', text: [
        'När du jämför två saker ritar du ett block för var och en, **under varandra**. Låt dem börja på samma ställe.',
        'Den som har mest får det längsta blocket.',
      ], pic: pic([{ key: 'A', label: 'Ella', pieces: [bit(58)] }, { key: 'B', label: 'Moa', pieces: [bit(58), del(17)] }], { A: '58', 'B.1': '17' }) },
      { title: 'Skillnaden sticker ut', text: [
        'Biten som sticker ut är **skillnaden**: hur mycket mer den ena har. Den är en **annan bit**, inte lika stor som de andra.',
      ], words: ['fler än', 'färre än', 'mer än', 'mindre än', 'längre', 'kortare', 'skillnad'] },
      { title: 'Fler än är inte gånger', text: [
        '**17 fler** betyder en bit till som är 17. Det betyder inte att blocket blir dubbelt så långt.',
      ], pic: pic([{ key: 'A', label: 'Ella', pieces: [bit(40)] }, { key: 'B', label: 'Moa', pieces: [bit(40), del(17)] }], { A: '40', 'B.1': '17' }) },
    ],
    lika: [
      { title: 'Lika stora bitar', text: [
        'Är alla delar lika stora delar du blocket i **lika stora bitar**.',
        'Antalet bitar · en bit = hela blocket.',
      ], pic: pic([{ key: 'A', label: 'Biljetter', pieces: bits(4, 85) }], { 'A.0': '85', A: '?' }) },
      { title: 'Gånger eller delat', text: [
        'Vet du en bit? **Multiplicera** med antalet bitar.',
        'Vet du hela blocket? **Dela** med antalet bitar, så får du en bit.',
      ], pic: pic([{ key: 'A', label: 'Kulor', pieces: bits(6, 12) }], { A: '72', 'A.0': '?' }), words: ['varje', 'var', 'per', 'styck', 'dela lika'] },
    ],
    ggr: [
      { title: 'Bitar som jämförs', text: [
        'Har Ella **tre gånger så många** som Moa? Ge Moa 1 bit och Ella 3 lika stora bitar.',
        'Bitarna är lika stora i båda blocken. Det är det viktiga.',
      ], pic: pic([{ key: 'A', label: 'Moa', pieces: [bit(12)] }, { key: 'B', label: 'Ella', pieces: bits(3, 12) }], {}) },
      { title: 'Räkna bitarna', text: [
        'Ofta får du veta hur mycket flera bitar är tillsammans. Räkna bitarna: 4 bitar → 48.',
        'Då är 1 bit 48 / 4 = 12. Sedan kan du räkna ut vad du vill: 3 bitar → 3 · 12 = 36.',
      ], pic: pic([{ key: 'A', label: 'Moa', pieces: [bit(12)] }, { key: 'B', label: 'Ella', pieces: bits(3, 12) }], { T: '48', B: '?' }) },
      { title: 'Hälften så många', text: [
        'Har Hugo **hälften så många** som Leo? Ge Leo 2 bitar och Hugo 1 bit. En tredjedel så många: 3 bitar mot 1.',
      ], words: ['gånger så många', 'dubbelt så mycket', 'hälften så många', 'en tredjedel så många'] },
    ],
    sumdiff: [
      { title: 'Två tal du inte vet', text: [
        'Elsa och Wilma har 86 kr tillsammans, och Elsa har 18 kr mer än Wilma.',
        'Rita Wilma som 1 bit och Elsa som 1 bit och en annan bit, 18. Klammern runt båda blocken är 86.',
      ], pic: pic([{ key: 'A', label: 'Elsa', pieces: [bit(34), del(18)] }, { key: 'B', label: 'Wilma', pieces: [bit(34)] }], { T: '86', 'A.1': '18' }) },
      { title: 'Ta bort skillnaden först', text: [
        'Tar du bort skillnaden blir blocken lika långa: 86 − 18 = 68. Det är **2 bitar**.',
        'Då är 1 bit 68 / 2 = 34. Wilma har 34 kr och Elsa 34 + 18 = 52 kr.',
      ], pic: pic([{ key: 'A', label: 'Elsa', pieces: [bit(34), del(18)] }, { key: 'B', label: 'Wilma', pieces: [bit(34)] }], { T: '86', 'A.1': '18', 'A.0': '34', B: '34' }) },
    ],
    brak: [
      { title: 'Nämnaren delar blocket', text: [
        'Står det [3/5] av eleverna? Rita ett block för alla eleverna.',
        '**Nämnaren**, 5, talet under bråkstrecket, säger hur många lika stora bitar blocket ska ha.',
      ], pic: pic([{ key: 'A', label: 'Elever', pieces: bits(5, 6) }], {}) },
      { title: 'Täljaren markerar', text: [
        '**Täljaren**, 3, talet över bråkstrecket, säger hur många av bitarna du markerar. De markerade bitarna är [3/5] av eleverna.',
      ], pic: pic([{ key: 'A', label: 'Elever', pieces: bits(5, 6) }], {}, [{ id: 'A:g', row: 'A', pieces: [0, 1, 2], label: 'syskon', mark: true }]) },
      { title: 'Räkna med bitarna', text: [
        'Är de 3 markerade bitarna 18 elever? Då är 1 bit 18 / 3 = 6, och alla 5 bitarna 5 · 6 = 30.',
      ], pic: pic([{ key: 'A', label: 'Elever', pieces: bits(5, 6) }], { 'A:g': '18', A: '?' }, [{ id: 'A:g', row: 'A', pieces: [0, 1, 2], label: 'syskon', mark: true }]) },
      { title: 'Av vad?', text: [
        '**[3/7] av pärlorna är röda:** blocket är alla pärlor, och 3 av 7 bitar är röda.',
        '**De röda är [3/7] av de blå:** då är blocket de blå pärlorna, och de röda får ett eget block med 3 sådana bitar.',
      ], pic: pic([{ key: 'A', label: 'Blå', pieces: bits(7, 4) }, { key: 'B', label: 'Röda', pieces: bits(3, 4) }], {}) },
    ],
    rest: [
      { title: 'Resten får ett eget block', text: [
        '[1/3] spelar fotboll och [3/5] av resten spelar pingis. Rita först alla och markera dem som spelar fotboll. Resten är 2 bitar.',
        'Resten ska delas i 5 lika delar. Rita ett **extrablock** under resten och dela det.',
      ], pic: pic([
        { key: 'A', label: 'Elever', pieces: bits(3, 10) },
        { key: 'R', label: 'Resten', pieces: bits(5, 4), under: { row: 'A', from: 1, to: 2 } },
      ], {}, [
        { id: 'A:g', row: 'A', pieces: [0], label: 'fotboll', mark: true },
        { id: 'A:rest', row: 'A', pieces: [1, 2], label: 'resten', link: 'R' },
        { id: 'R:g', row: 'R', pieces: [0, 1, 2], label: 'pingis', mark: true },
      ]) },
      { title: 'Bitar och delar', text: [
        'Säg **bitar** om det första blocket och **delar** om extrablocket, så blandar du inte ihop dem.',
        'Ibland går resten att dela i bitarna som redan finns. Då behövs inget extrablock.',
      ] },
    ],
    fore: [
      { title: 'Före och efter', text: [
        'När något ändras, någon får, ger bort eller köper, kan du rita ett block för **före** och ett för **efter**.',
      ], pic: pic([{ key: 'F', label: 'Före', pieces: [bit(37)] }, { key: 'E', label: 'Efter', pieces: [bit(37), del(15, 'fick')] }], { F: '?', 'E.1': '15', E: '52' }) },
      { title: 'Vad är lika?', text: [
        'Leta efter det som är lika före och efter. Det hjälper dig att se vad bitarna är.',
        'Hade två personer **lika många** efteråt? Då är deras block lika långa efteråt.',
      ], words: ['från början', 'sedan', 'nu', 'kvar', 'efteråt', 'lika många'] },
    ],
    forh: [
      { title: 'Förhållande', text: [
        '**2 : 3** betyder 2 bitar för det första och 3 lika stora bitar för det andra.',
      ], pic: pic([{ key: 'A', label: 'Pojkar', pieces: bits(2, 5) }, { key: 'B', label: 'Flickor', pieces: bits(3, 5) }], { B: '15', A: '?' }) },
      { title: 'Procent', text: [
        'Hela blocket är **100 %**. 50 % är en halv: 2 bitar. 25 % är en fjärdedel: 4 bitar. 20 % är en femtedel: 5 bitar. 10 % är en tiondel: 10 bitar.',
      ], pic: pic([{ key: 'A', label: 'Priset', pieces: bits(4, 150) }], { A: '600' }, [{ id: 'A:g', row: 'A', pieces: [0], label: '25 %', mark: true }]) },
    ],
    mix: [
      { title: 'Vilken modell passar?', text: [
        'Nu blandas uppgifterna. Läs och tänk efter: är det delar av en helhet, en jämförelse, lika stora bitar, ett bråk eller något som ändras?',
        'Välj modell först. Sedan löser du uppgiften.',
      ], mascot: true },
    ],
  };

  /* The eight steps of the method, as Swedish schools teach them. */
  const STEPS = [
    { n: 1, short: 'Läs', title: 'Läs hela uppgiften.' },
    { n: 2, short: 'Vem/vad', title: 'Bestäm vem eller vad uppgiften handlar om.' },
    { n: 3, short: 'Rita', title: 'Rita blocket eller blocken.' },
    { n: 4, short: 'Läs igen', title: 'Läs uppgiften en gång till.' },
    { n: 5, short: 'Skriv in', title: 'Skriv in det du vet.' },
    { n: 6, short: '?', title: 'Vad söker du? Skriv frågetecknet.' },
    { n: 7, short: 'Räkna', title: 'Räkna ut svaret.' },
    { n: 8, short: 'Svara', title: 'Skriv svaret. Är det rimligt?' },
  ];

  /*
     The chapters and their lessons. A lesson is learn (cards, a worked
     example, a problem to finish), build (the pupil draws every step),
     solve (the answer first; drawing is help), mixed (which model, then
     solve) or steps (the eight steps in order). An item is [template] or
     [template, seed] - without a seed, a new problem every time.
  */
  const UNITS = [
    { id: 'start', title: 'Kom igång', lead: 'Vad blockmodellen är, och de åtta stegen', lessons: [
      { id: 'start-1', kind: 'learn', title: 'Vad är blockmodellen?', cards: 'start', demo: ['jm-fler', 11], fill: [['dh-kvar']] },
      { id: 'start-2', kind: 'steps', title: 'De åtta stegen', cards: 'steps' },
    ] },
    { id: 'delhel', title: 'Del och helhet', type: 'delhel', lessons: [
      { id: 'delhel-1', kind: 'learn', title: 'Så funkar det', cards: 'delhel', demo: ['dh-kvar', 7], fill: [['dh-sum']] },
      { id: 'delhel-2', kind: 'build', title: 'Rita själv', items: [['dh-sum'], ['dh-kvar'], ['dh-tre']] },
      { id: 'delhel-3', kind: 'solve', title: 'Lös uppgifter', items: [['dh-kvar'], ['dh-sum'], ['dh-tre'], ['dh-kvar']] },
    ] },
    { id: 'jmf', title: 'Jämförelse', type: 'jmf', lessons: [
      { id: 'jmf-1', kind: 'learn', title: 'Så funkar det', cards: 'jmf', demo: ['jm-fler', 5], fill: [['jm-skillnad']] },
      { id: 'jmf-2', kind: 'build', title: 'Rita själv', items: [['jm-fler'], ['jm-farre'], ['jm-skillnad']] },
      { id: 'jmf-3', kind: 'solve', title: 'Lös uppgifter', items: [['jm-farre'], ['jm-fler'], ['jm-skillnad'], ['jm-tills']] },
    ] },
    { id: 'lika', title: 'Lika stora bitar', type: 'lika', lessons: [
      { id: 'lika-1', kind: 'learn', title: 'Så funkar det', cards: 'lika', demo: ['li-dela', 3], fill: [['li-ggr']] },
      { id: 'lika-2', kind: 'build', title: 'Rita själv', items: [['li-ggr'], ['li-dela'], ['li-prop']] },
      { id: 'lika-3', kind: 'solve', title: 'Lös uppgifter', items: [['li-dela'], ['li-ggr'], ['li-prop'], ['li-dela']] },
    ] },
    { id: 'ggr', title: 'Gånger så många', type: 'ggr', lessons: [
      { id: 'ggr-1', kind: 'learn', title: 'Så funkar det', cards: 'ggr', demo: ['gg-tills', 4], fill: [['gg-hur']] },
      { id: 'ggr-2', kind: 'build', title: 'Rita själv', items: [['gg-hur'], ['gg-tills'], ['gg-skill']] },
      { id: 'ggr-3', kind: 'solve', title: 'Lös uppgifter', items: [['gg-tills'], ['gg-hur'], ['gg-skill'], ['gg-half']] },
    ] },
    { id: 'sumdiff', title: 'Summa och skillnad', type: 'sumdiff', lessons: [
      { id: 'sumdiff-1', kind: 'learn', title: 'Så funkar det', cards: 'sumdiff', demo: ['sd-minst', 9], fill: [['sd-mest']] },
      { id: 'sumdiff-2', kind: 'build', title: 'Rita själv', items: [['sd-minst'], ['sd-mest'], ['sd-farre']] },
      { id: 'sumdiff-3', kind: 'solve', title: 'Lös uppgifter', items: [['sd-mest'], ['sd-minst'], ['sd-farre'], ['sd-minst']] },
    ] },
    { id: 'brak', title: 'Bråk', type: 'brak', lessons: [
      { id: 'brak-1', kind: 'learn', title: 'Så funkar det', cards: 'brak', demo: ['br-hel', 6], fill: [['br-del']] },
      { id: 'brak-2', kind: 'build', title: 'Rita själv', items: [['br-del'], ['br-hel'], ['br-kvar']] },
      { id: 'brak-3', kind: 'solve', title: 'Lös uppgifter', items: [['br-hel'], ['br-del'], ['br-kvar'], ['br-hel']] },
    ] },
    { id: 'rest', title: 'Bråk av resten', type: 'rest', lessons: [
      { id: 'rest-1', kind: 'learn', title: 'Så funkar det', cards: 'rest', demo: ['re-resten', 8], fill: [['re-kvar']] },
      { id: 'rest-2', kind: 'build', title: 'Rita själv', items: [['re-resten'], ['re-kvar']] },
      { id: 'rest-3', kind: 'solve', title: 'Lös uppgifter', items: [['re-resten'], ['re-kvar'], ['re-resten']] },
    ] },
    { id: 'fore', title: 'Före och efter', type: 'fore', lessons: [
      { id: 'fore-1', kind: 'learn', title: 'Så funkar det', cards: 'fore', demo: ['fo-fick', 2], fill: [['fo-gav']] },
      { id: 'fore-2', kind: 'build', title: 'Rita själv', items: [['fo-fick'], ['fo-gav'], ['fo-lika']] },
      { id: 'fore-3', kind: 'solve', title: 'Lös uppgifter', items: [['fo-gav'], ['fo-fick'], ['fo-lika'], ['fo-lika']] },
    ] },
    { id: 'forh', title: 'Förhållande och procent', type: 'forh', lessons: [
      { id: 'forh-1', kind: 'learn', title: 'Så funkar det', cards: 'forh', demo: ['fh-del', 3], fill: [['pc-del']] },
      { id: 'forh-2', kind: 'build', title: 'Rita själv', items: [['fh-del'], ['fh-tot'], ['pc-del']] },
      { id: 'forh-3', kind: 'solve', title: 'Lös uppgifter', items: [['fh-del'], ['pc-del'], ['fh-tot'], ['pc-del']] },
    ] },
    { id: 'mix', title: 'Blandat', lead: 'Välj själv vilken modell som passar', lessons: [
      { id: 'mix-1', kind: 'mixed', title: 'Blandat 1', cards: 'mix', count: 6, level: 1 },
      { id: 'mix-2', kind: 'mixed', title: 'Blandat 2', count: 6, level: 2 },
    ] },
  ];

  const LESSONS = UNITS.flatMap(u => u.lessons.map(l => Object.assign({ unit: u.id }, l)));
  const lessonById = Object.create(null);
  for (const l of LESSONS) lessonById[l.id] = l;

  /* A mixed set of n problems: each kind at most twice, never the same
     kind twice in a row. */
  function mixed(r, n, level) {
    const types = TYPES.map(t => t.id).filter(id => templatesOf(id, level).length);
    const out = [];
    const used = {};
    let last = null;
    let guard = 0;
    while (out.length < n && guard++ < 500) {
      const type = r.pick(types);
      if (type === last || (used[type] || 0) >= 2) continue;
      const tids = templatesOf(type, level);
      out.push([r.pick(tids)]);
      used[type] = (used[type] || 0) + 1;
      last = type;
    }
    return out;
  }

  /* Choices for "which model fits": the right kind and three that are not
     drawn alike. */
  function modelChoices(r, type) {
    const not = new Set([type, ...(ALIKE[type] || [])]);
    const others = r.shuffle(TYPES.map(t => t.id).filter(id => !not.has(id))).slice(0, 3);
    return r.shuffle([type, ...others]);
  }

  return {
    rng, fmt, sv, cap, fracWords, parseNumber, plain, plainText, possName, joinAnd, nb, nd,
    TYPES, TEMPLATES, LEARN, STEPS, UNITS, LESSONS, lessonById, COLORS,
    make, templatesOf, mixed, modelChoices,
    canon, sameSlot, slotPieces, slotNoun, slotAt, checkShape, checkMark, rowOf,
    MINUS, DOT,
  };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = BM_PROBLEMS;
