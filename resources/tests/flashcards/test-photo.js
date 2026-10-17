#!/usr/bin/env node
/*
  Words from a picture, without a browser: how flashcards-photo.js puts the
  words Tesseract found back into the rows and columns of a word list, turns
  the pairs Swedish first, and makes a picture ready to be read. The words
  here are boxes made up for each case, sized the way printed letters are;
  the reading itself, with Tesseract, is test-photo-ui.py's.

      node resources/tests/flashcards/test-photo.js

  Exit status 0 when every check passes.
*/
'use strict';
const path = require('path');
const W = require(path.join(__dirname, '../../js/flashcards-words.js'));
const P = require(path.join(__dirname, '../../js/flashcards-photo.js'));

let checks = 0;
const failures = [];
function check(label, got, want = true) {
  checks++;
  const ok = JSON.stringify(got) === JSON.stringify(want);
  console.log(`${ok ? 'ok  ' : 'FAIL'}  ${label}${ok ? '' : `: ${JSON.stringify(got)} (expected ${JSON.stringify(want)})`}`);
  if (!ok) failures.push(label);
}

/* ── Words with boxes, as Tesseract gives them ───────────────────────────── */

/* A word printed at size em (pixels) with its baseline at y: as wide as its
   letters, as tall as they reach above and below the line. */
const TOP = /[A-ZÅÄÖ0-9bdfhklt!?åäöáéíóúñ'"]/u;
const BOTTOM = /[gjpqyç,;]/u;
function word(text, x, y, em = 40, conf = 95) {
  const up = TOP.test(text) ? 0.72 : 0.5, down = BOTTOM.test(text) ? 0.23 : 0;
  return { text, conf, x0: x, x1: x + Math.round(0.52 * em * [...text].length), y0: y - Math.round(up * em), y1: y + Math.round(down * em) };
}
/* A line of words from a string: words a space apart, "|" a jump to x. */
function line(y, spec, opts = {}) {
  const em = opts.em || 40;
  const words = [];
  for (const part of spec.split('|')) {
    const m = /^@(\d+)\s*(.*)$/.exec(part.trim());
    let x = m ? Number(m[1]) : (words.length ? words[words.length - 1].x1 + Math.round(0.3 * em) : 100);
    for (const t of (m ? m[2] : part).trim().split(/\s+/).filter(Boolean)) {
      const w = word(t, x, y, em, opts.conf);
      words.push(w);
      x = w.x1 + Math.round(0.3 * em);
    }
  }
  return { words };
}
/* A list of pairs in two columns, at x 100 and 700, one row every 60 px. */
function columns(pairs, opts = {}) {
  const top = opts.top || 200, right = opts.right || 700;
  return pairs.map(([a, b], i) => line(top + 60 * i, `@100 ${a}|@${right} ${b}`, opts));
}
const pairsOf = res => res.pairs.map(p => [p.sv, p.x]);

const EN = [['en hund', 'a dog'], ['att springa', 'to run'], ['fönster', 'window'], ['grönsaker', 'vegetables'], ['väder', 'weather'],
  ['nyckel', 'key'], ['fåglar', 'birds'], ['kylskåp', 'fridge']];
const flip = ps => ps.map(([a, b]) => [b, a]);

// --- columns and rows ------------------------------------------------------------
let res = P.layout(columns(EN), { lang: 'en' });
check('two columns, Swedish first: every pair, as it stands', [pairsOf(res), res.swapped, res.holes], [EN, false, 0]);
res = P.layout(columns(flip(EN)), { lang: 'en' });
check('English first: turned round, Swedish first', [pairsOf(res), res.swapped, res.byHeading], [EN, true, false]);
res = P.layout([line(140, '@100 Engelska|@700 Svenska'), ...columns(flip(EN))], { lang: 'en' });
check('the column headings give the order, and are no pair', [pairsOf(res), res.swapped, res.byHeading, res.headings], [EN, true, true, ['Engelska  Svenska']]);
res = P.layout([line(140, '@100 Svenska|@700 Engelska'), ...columns([['ett äpple', 'an apple'], ['katt', 'cat']])], { lang: 'en' });
check('headings "Svenska Engelska": the order as it stands', [res.swapped, res.byHeading], [false, true]);

/* Tesseract reading for sparse text gives each column its own lines. */
const apart = [];
EN.forEach(([a, b], i) => { apart.push(line(200 + 60 * i, `@100 ${a}`)); });
EN.forEach(([a, b], i) => { apart.push(line(201 + 60 * i, `@700 ${b}`)); });
check('columns read apart are put back into rows', pairsOf(P.layout(apart, { lang: 'en' })), EN);

/* A sloping photo: each row a little lower to the right. */
const sloped = EN.map(([a, b], i) => ({ words: [...line(200 + 60 * i, `@100 ${a}`).words, ...line(212 + 60 * i, `@700 ${b}`).words] }));
check('a row that slopes a little is still one row', pairsOf(P.layout(sloped, { lang: 'en' })), EN);

const tight = [['sjuksköterska', 'nurse'], ['läkare', 'doctor'], ['lärare', 'teacher'], ['bibliotekarie', 'librarian'], ['polis', 'police officer']]
  .map(([a, b], i) => line(200 + 60 * i, `@100 ${a}|@${a.length > 10 ? 400 : 420} ${b}`));
check('a long word that leaves only a space before its translation is split where the column starts',
  pairsOf(P.layout(tight, { lang: 'en' })), [['sjuksköterska', 'nurse'], ['läkare', 'doctor'], ['lärare', 'teacher'], ['bibliotekarie', 'librarian'], ['polis', 'police officer']]);

// --- separators, numbers, headings ----------------------------------------------------
res = P.layout([line(200, 'hund – dog'), line(260, 'katt = cat'), line(320, 'häst: horse'), line(380, 'ko - cow'), line(440, 'får=sheep'), line(500, 'gris –pig')], { lang: 'en' });
check('dashes, equals signs and colons separate, spaced or stuck to a word', pairsOf(res),
  [['hund', 'dog'], ['katt', 'cat'], ['häst', 'horse'], ['ko', 'cow'], ['får', 'sheep'], ['gris', 'pig']]);
check('a hyphen inside a word is part of it', pairsOf(P.layout([line(200, 't-shirt = t-shirt'), line(260, 'e-post = e-mail')], { lang: 'en' })),
  [['t-shirt', 't-shirt'], ['e-post', 'e-mail']]);
res = P.layout([line(200, '1. huvud = head'), line(260, '2. axlar = shoulders'), line(320, '3) knä = knee'), line(380, '(4) tår = toes')], { lang: 'en' });
check('numbering is no part of the word', pairsOf(res), [['huvud', 'head'], ['axlar', 'shoulders'], ['knä', 'knee'], ['tår', 'toes']]);
res = P.layout(['huvud head', 'axlar shoulders', 'knä knee', 'tår toes'].map((t, i) => line(200 + 60 * i, `@40 ${i + 1}|@100 ${t.split(' ')[0]}|@700 ${t.split(' ')[1]}`)), { lang: 'en' });
check('bare numbers count as numbering when most rows have one', pairsOf(res), [['huvud', 'head'], ['axlar', 'shoulders'], ['knä', 'knee'], ['tår', 'toes']]);
check('but a number may be a word', pairsOf(P.layout([line(200, '20 = twenty'), line(260, 'hund = dog')], { lang: 'en' }))[0], ['20', 'twenty']);
res = P.layout([line(120, 'Kroppen – vecka 7', { em: 58 }), ...columns([['huvud', 'head'], ['knä', 'knee'], ['tår', 'toes']])], { lang: 'en' });
check('a heading in larger writing is no pair, and names the list', [pairsOf(res).length, res.name, res.headings], [3, 'Vecka 7', ['Kroppen vecka 7']]);
res = P.layout([line(120, 'Glosor v. 42'), ...columns([['huvud', 'head'], ['knä', 'knee']])], { lang: 'en' });
check('"v. 42" names the list too', res.name, 'Vecka 42');
res = P.layout([line(120, 'Läxa till fredag – kapitel 3', { em: 40 }), ...columns([['huvud', 'head'], ['knä', 'knee']])], { lang: 'en' });
check('a heading in the same writing as the list cannot be told from a pair', pairsOf(res)[0], ['Läxa till fredag', 'kapitel 3']);
res = P.layout([line(140, '@100 a cloud|@700 ett moln', { em: 52 }), ...columns(flip([['regn', 'rain'], ['snö', 'snow'], ['åska', 'thunder']]), { top: 210 })], { lang: 'en' });
check('a first row read a little large is still a row of the list when it is cut in two', pairsOf(res)[0], ['ett moln', 'a cloud']);

/* A phone's screenshot of the school's app: the clock and the battery above,
   a heading, a numbered list "1 amazing - fantastisk", and the app's word
   count below, which is no pair either. */
const app = [
  line(40, '@60 12:05|@900 95'),
  line(120, '@40 Uppgifter'),
  line(190, 'Läxa i engelska v 41', { em: 48 }),
  ...[['amazing', 'fantastisk'], ['pleasant', 'trevlig'], ['managed', 'klarade'], ['pretty', 'ganska']]
    .map(([en, sv], i) => line(300 + 90 * i, `${i + 1} ${en} - ${sv}`)),
  line(700, '114 ord · 1587 tecken'),
];
res = P.layout(app, { lang: 'en' });
check('a screenshot of the school\'s app: the list and nothing else, named from its heading',
  [pairsOf(res), res.name], [[['fantastisk', 'amazing'], ['trevlig', 'pleasant'], ['klarade', 'managed'], ['ganska', 'pretty']], 'Vecka 41']);
res = P.layout(['svarade - replied', 'imonerad - impressed', 'nickade - nodded'].map((t, i) => {
  const l = line(200 + 60 * i, `${i + 1} ${t}`);
  if (i === 1) { l.words[0].text = '2imonerad'; l.words[0].x1 = l.words[1].x1; l.words.splice(1, 1); }
  return l;
}), { lang: 'en' });
check('a number read stuck to the word after it is still the list\'s number', pairsOf(res),
  [['svarade', 'replied'], ['imonerad', 'impressed'], ['nickade', 'nodded']]);
check('a time is no side of a pair; a number is', [pairsOf(P.layout([line(200, '12:05 = klockan'), line(260, '20 = twenty')], { lang: 'en' }))],
  [[['20', 'twenty']]]);

// --- what is not a word ---------------------------------------------------------------
res = P.layout([{ words: [word('|', 80, 230), word('hund', 100, 230), word('|', 600, 230), word('dog', 700, 230), word('|', 1000, 230)] },
  { words: [word('|katt', 100, 290), word('cat|', 700, 290)] }], { lang: 'en' });
check('the lines of a table are no letters', pairsOf(res), [['hund', 'dog'], ['katt', 'cat']]);
res = P.layout([line(200, '@100 dog|@400 [dɒg]|@700 hund'), line(260, '@100 cat|@400 [kæt]|@700 katt'), line(320, '@100 cow|@400 /kaʊ/|@700 ko')], { lang: 'en' });
check('pronunciation between the word and its translation is left out', pairsOf(res), [['hund', 'dog'], ['katt', 'cat'], ['ko', 'cow']]);
res = P.layout([...columns([['ö', 'island'], ['å', 'river'], ['hav', 'sea']]), line(260, '@1400 j'), line(325, '@20 i')], { lang: 'en' });
check('a speck read as a letter is no word, a word of one letter is', pairsOf(res), [['ö', 'island'], ['å', 'river'], ['hav', 'sea']]);
const glossary = [
  line(200, '@100 In the morning the sky was grey and heavy. By lunch|@1300 a cloud|@1700 ett moln'),
  line(260, '@100 the first drops of rain had started to fall and|@1300 rain|@1700 regn'),
  line(320, '@100 hills.|@1300 snow|@1700 snö'),
  line(380, '@100 Page 42|@1300 thunder|@1700 åska'),
  line(440, '@1300 fog|@1700 dimma'),
];
res = P.layout(glossary, { lang: 'en' });
check('a paragraph beside the list, and a page number, are left out of it', pairsOf(res),
  [['ett moln', 'a cloud'], ['regn', 'rain'], ['snö', 'snow'], ['åska', 'thunder'], ['dimma', 'fog']]);
check('and the paragraph is among the lines that made no pair', res.skipped.some(t => t.startsWith('In the morning')), true);

// --- two lists, and holes -------------------------------------------------------------
const L = [['blå', 'blue'], ['röd', 'red'], ['gul', 'yellow']], R = [['lila', 'purple'], ['rosa', 'pink'], ['brun', 'brown']];
res = P.layout(L.map(([a, b], i) => line(200 + 60 * i, `@100 ${a}|@400 ${b}|@800 ${R[i][0]}|@1100 ${R[i][1]}`)), { lang: 'en' });
check('two lists side by side: the left one first, then the right', pairsOf(res), [...L, ...R]);
const holed = columns(EN);
holed.splice(3, 2);
check('a gap where rows should be is a hole', P.layout(holed, { lang: 'en' }).holes, 1);
const lone = columns(EN);
lone[2] = line(320, '@100 fönster');
check('a word without its pair is a hole', [P.layout(lone, { lang: 'en' }).holes, pairsOf(P.layout(lone, { lang: 'en' })).length], [1, 7]);
check('nothing read, nothing found', [pairsOf(P.layout([], { lang: 'en' })), pairsOf(P.layout([{ words: [] }], { lang: 'en' }))], [[], []]);

// --- which side is Swedish ---------------------------------------------------------------
check('å, ä and ö are Swedish', ['fönster', 'tår', 'väder'].map(t => P.swedishness(t, 'en') > 0), [true, true, true]);
check('en, ett and att are Swedish; a, the and to English', ['en katt', 'att springa', 'a cat', 'to run', 'the kitchen'].map(t => Math.sign(P.swedishness(t, 'en'))), [1, 1, -1, -1, -1]);
check('Spanish accents and el and la are Spanish, é is not enough', ['la canción', 'el perro', 'mañana', 'idé'].map(t => Math.sign(P.swedishness(t, 'es'))), [-1, -1, -1, 0]);
check('a word of the page\'s own themes tells its language', [P.swedishness('hund', 'en'), P.swedishness('dog', 'en')].map(Math.sign), [1, -1]);
const es = [['huset', 'la casa'], ['hunden', 'el perro'], ['året', 'el año'], ['boken', 'el libro'], ['staden', 'la ciudad']];
check('Spanish first: turned round', pairsOf(P.layout(columns(flip(es)), { lang: 'es' })), es);

/* Read twice: Swedish alone (the boxes), Spanish alone (second). */
const swe = columns([['pojken', 'el nino'], ['trädet', 'el arbol'], ['sången', 'la cancion']], { conf: 90 });
const spa = columns([['pojken', 'el niño'], ['trádet', 'el árbol'], ['sángen', 'la canción']], { conf: 92 });
res = P.layout(swe, { lang: 'es', second: spa });
check('read twice: the Swedish side from the Swedish reading, the other from the second', pairsOf(res),
  [['pojken', 'el niño'], ['trädet', 'el árbol'], ['sången', 'la canción']]);
/* Read twice for English: both languages first, Swedish alone second. The
   Swedish reading's word is taken when it puts back dots and rings - and
   one letter besides at most - and not when it reads the word otherwise. */
const both = columns([['vaderleksrapport', 'forecast'], ['det 6sregnade', 'it rained'], ['blixt', 'lightning'], ['hund', 'dog']]);
const swedish = columns([['väderleksrapport', 'forecaat'], ['det ösregnade', 'lt rained'], ['blid', 'lightnlng'], ['hund', 'dag']]);
res = P.layout(both, { lang: 'en', second: swedish, secondIs: 'sv' });
check('read twice for English: å, ä and ö from the Swedish reading, the rest as both languages read it', pairsOf(res),
  [['väderleksrapport', 'forecast'], ['det ösregnade', 'it rained'], ['blixt', 'lightning'], ['hund', 'dog']]);
const wide = [{ words: [{ text: 'nej', conf: 90, x0: 100, x1: 400, y0: 170, y1: 215 }, word('=', 260, 210), word('no', 300, 210)] }];
check('a word whose box reaches over the next is matched by where it is, not by its box',
  pairsOf(P.layout(wide, { lang: 'es', second: [{ words: [{ text: 'nej', conf: 90, x0: 100, x1: 400, y0: 170, y1: 215 }, word('no', 300, 210)] }] })),
  [['nej', 'no']]);
const sure = (pairs, s, x) => pairs.map(([a, b], i) => line(200 + 60 * i, `@100 ${a}|@700 ${b}`)).map((l) => {
  l.words.forEach((w) => { w.conf = w.x0 < 600 ? s : x; });
  return l;
});
res = P.layout(sure([['casa', 'hus'], ['mesa', 'bord']], 60, 95), { lang: 'es', second: sure([['casa', 'hus'], ['mesa', 'bord']], 95, 60) });
check('with nothing else to go by, the reading that was surer of a column tells its language', [res.swapped, pairsOf(res)], [true, [['hus', 'casa'], ['bord', 'mesa']]]);
check('a pair is as sure as its least sure word', P.layout([{ words: [word('hund', 100, 200, 40, 91), word('dog', 700, 200, 40, 58)] }], { lang: 'en' }).pairs[0].conf, 58);

// --- into the editor --------------------------------------------------------------------
const text = P.toText([{ sv: 'kl: 3 = tre', x: 'three o’clock' }, { sv: 'hund – valp', x: 'dog = puppy' }, { sv: 'mamma', x: 'mum / mom' }]);
check('as lines for the editor, nothing in the Swedish read as a separator', text, 'kl 3 tre = three o’clock\nhund valp = dog = puppy\nmamma = mum / mom');
check('and the editor reads them back as pairs', W.parseList(text).words, [['kl 3 tre', 'three o’clock'], ['hund valp', 'dog = puppy'], ['mamma', 'mum|mom']]);
check('one reading adds the words the other missed, where it had none', P.addMissing(
  [{ words: [word('hund', 100, 200), word('dog', 700, 200)] }],
  [{ words: [word('hund', 102, 201), word('katt', 100, 260), word('cat', 700, 260)] }]).flatMap(l => l.words.map(w => w.text)), ['hund', 'dog', 'katt', 'cat']);

// --- the picture ---------------------------------------------------------------------------
/* A sheet w × h: paper, with dark bars for lines of writing, turned deg. */
function sheet(w, h, deg, paper = (x, y) => 235) {
  const g = new Uint8ClampedArray(w * h);
  const a = (deg * Math.PI) / 180, c = Math.cos(a), s = Math.sin(a);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      /* Back into the sheet's own frame, turned. */
      const u = (x - w / 2) * c + (y - h / 2) * s + w / 2, v = -(x - w / 2) * s + (y - h / 2) * c + h / 2;
      const row = Math.floor(v / 40);
      const ink = v % 40 > 22 && v % 40 < 34 && u > 60 && u < w - 60 && row % 1 === 0 && (Math.floor(u / 14) % 5 !== 4);
      g[y * w + x] = ink ? Math.round(paper(x, y) * 0.25) : paper(x, y);
    }
  }
  return g;
}
for (const deg of [0, 3, -5.5, 9]) {
  const g = sheet(700, 500, deg);
  P.flatten(g, 700, 500);
  const got = P.skewOf(g, 700, 500);
  check(`the slope of lines turned ${deg}° is found within a quarter of a degree`, Math.abs(got - deg) <= 0.25, true);
}
const lit = sheet(600, 400, 0, (x) => Math.round(110 + 130 * (x / 600)));
/* Row 305 is a line of writing, row 5 paper between the lines. */
const inkAt = [305 * 600 + 100, 305 * 600 + 500], paperAt = [5 * 600 + 100, 5 * 600 + 500];
P.flatten(lit, 600, 400);
check('light from one side: the paper is white all over, the writing dark',
  [...paperAt.map(i => lit[i] >= 240), ...inkAt.map(i => lit[i] <= 90)], [true, true, true, true]);
const shadow = sheet(600, 400, 0, x => (x < 300 ? 95 : 235));
P.flatten(shadow, 600, 400);
check('the sharp edge of a shadow: the writing on both sides of it is still writing',
  [shadow[305 * 600 + 280] <= 90, shadow[305 * 600 + 320] <= 90, shadow[5 * 600 + 280] >= 240, shadow[5 * 600 + 320] >= 240], [true, true, true, true]);
/* Writing light on dark: a dark-mode screenshot, and a photo of a dark
   screen with a light wall around it; dark on light: a small sheet on a dark desk. */
const writing = (w, h, ground, ink, x0, x1, y0, y1) => {
  const g = new Uint8ClampedArray(w * h).fill(ground);
  for (let y = y0; y < y1; y++) for (let x = x0; x < x1; x++) if (y % 20 < 4 && x % 9 < 6) g[y * w + x] = ink;
  return g;
};
const darkMode = writing(300, 200, 25, 235, 30, 270, 30, 170);
check('a screenshot in dark mode is light writing on dark', P.lightText(darkMode, 300, 200), true);
P.flatten(darkMode, 300, 200, true);
check('turned negative and evened out, the writing is dark and the ground white', [darkMode[41 * 300 + 31] < 90, darkMode[45 * 300 + 31] > 200], [true, true]);
const screen = new Uint8ClampedArray(400 * 300).fill(200);
for (let y = 60; y < 260; y++) for (let x = 60; x < 340; x++) screen[y * 400 + x] = y % 20 < 4 && x % 9 < 6 && x > 80 && x < 320 ? 225 : 45;
check('a photo of a dark screen is light writing on dark, the light wall around it notwithstanding', P.lightText(screen, 400, 300), true);
const desk = writing(400, 300, 25, 0, 0, 0, 0, 0);
/* The sheet a little under a third of the photo. */
for (let y = 70; y < 230; y++) for (let x = 90; x < 310; x++) desk[y * 400 + x] = y % 20 < 4 && x % 9 < 6 ? 40 : 235;
check('a small sheet on a dark desk is dark writing on light', P.lightText(desk, 400, 300), false);
P.flatten(desk, 400, 300, false);
check('evened out, the paper stays light and the writing dark', [desk[150 * 400 + 150] > 200, desk[101 * 400 + 91] < 90], [true, true]);
check('grey as the eye sees it', [...P.grey(new Uint8ClampedArray([255, 0, 0, 255, 0, 255, 0, 255, 0, 0, 255, 255]))], [76, 149, 28]);

// --- the reader's files ----------------------------------------------------------------------
const files = Object.entries(P.FILES);
check('every file of the reader is pinned to a version', files.filter(([, f]) => !/@\d+\.\d+\.\d+\//.test(f.path)).map(([k]) => k), []);
check('and has a SHA-384 and a size', files.filter(([, f]) => !/^sha384-[A-Za-z0-9+/]{64}$/.test(f.sri) || !(f.size > 1000)).map(([k]) => k), []);
check('from jsDelivr only', P.CDN, 'https://cdn.jsdelivr.net/npm/');
check('the first reading downloads about 9 MB', [Math.round(P.downloadSize('en') / 1e6 * 10) / 10, Math.round(P.downloadSize('es') / 1e6 * 10) / 10], [9.5, 8.7]);

console.log(`\n${checks - failures.length} of ${checks} checks passed.`);
process.exit(failures.length ? 1 : 0);
