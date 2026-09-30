#!/usr/bin/env node
/*
  The words of flashcards.html, without a page: the themes hold what they
  should, a typed answer is judged the way a teacher would, the pupil's own
  lists are read as teachers write them, a shared link carries a list and
  nothing else, and the Leitner boxes send words back when they should.

      node resources/tests/flashcards/test-words.js

  Exit status 0 when every check passes.
*/
'use strict';
const path = require('path');
const W = require(path.join(__dirname, '../../js/flashcards-words.js'));

let checks = 0;
const failures = [];
function check(label, got, want = true) {
  checks++;
  const ok = JSON.stringify(got) === JSON.stringify(want);
  console.log(`${ok ? 'ok  ' : 'FAIL'}  ${label}${ok ? '' : `: ${JSON.stringify(got)} (expected ${JSON.stringify(want)})`}`);
  if (!ok) failures.push(label);
}

const cards = {};
for (const lang of ['en', 'es']) {
  cards[lang] = {};
  for (const g of W.topicsFor(lang)) for (const t of g.topics) cards[lang][t.id] = { topic: t, till: W.cardsFor(t, lang, 'till'), fran: W.cardsFor(t, lang, 'fran') };
}
const all = lang => Object.values(cards[lang]).flatMap(c => c.till.concat(c.topic.kind ? [] : c.fran));

// --- the themes ------------------------------------------------------------
check('five groups in both languages', ['en', 'es'].map(l => W.topicsFor(l).length), [5, 5]);
check('grammar belongs to its language',
  [Object.keys(cards.en).filter(id => /irr|genus|konj/.test(id)), Object.keys(cards.es).filter(id => /irr|genus|konj/.test(id))],
  [['irr1', 'irr2'], ['genus', 'konj1', 'konj2']]);
check('every theme has at least seven cards', Object.values(cards.en).concat(Object.values(cards.es)).filter(c => c.till.length < 7).map(c => c.topic.id), []);
check('no key twice in a pile, either way round',
  ['en', 'es'].flatMap(l => Object.values(cards[l]).filter(c => { const keys = c.till.concat(c.topic.kind ? [] : c.fran).map(x => x.key); return new Set(keys).size !== keys.length; }).map(c => c.topic.id)), []);
check('a word in two piles is one card: 20 in Siffror and in Tal',
  cards.en.siffror.till.find(c => c.front.text === '20').key, cards.en.tal.till.find(c => c.front.text === '20').key);
check('every card has a front, an answer, something to accept and something to say',
  ['en', 'es'].flatMap(l => all(l).filter(c => !c.front.text || !c.answer || !c.say || (c.kind === 'forms' ? !c.past.length || !c.part.length : !c.accept?.length))).map(c => c.key), []);
check('no field has stray spaces or empty alternatives',
  W.GROUPS.flatMap(g => g.topics.flatMap(t => (t.words || []).flatMap(w => ['sv', 'en', 'es'].filter(k => w[k] != null)
    .filter(k => w[k] !== w[k].trim() || w[k].split('|').some(a => !a.trim() || a !== a.trim()))
    .map(k => `${t.id}:${w.sv}:${k}`)))), []);
check('Spanish nouns carry their article, the days and months do not',
  [cards.es.husdjur.till.every(c => /^(el|la|los|las) /.test(c.answer)), cards.es.dagar.till.every(c => !/^(el|la) /.test(c.answer))], [true, true]);
check('a word with no Spanish is left out of Spanish only',
  [cards.en.kanslor.till.some(c => c.answer === 'hungry'), cards.es.kanslor.till.some(c => c.front.text === 'hungrig')], [true, false]);
check('pictures are emoji or a colour', W.GROUPS.flatMap(g => g.topics.flatMap(t => (t.words || []).filter(w => w.pic && !/^#[0-9a-f]{6}$/.test(w.pic) && w.pic.length > 8).map(w => w.sv))), []);

// --- numbers ----------------------------------------------------------------
check('English numbers', [0, 13, 20, 21, 45, 99, 100].map(n => W.numberWord(n, 'en')),
  ['zero', 'thirteen', 'twenty', 'twenty-one', 'forty-five', 'ninety-nine', 'one hundred|a hundred|hundred']);
check('Spanish numbers, accents and all', [1, 16, 21, 22, 23, 26, 31, 45, 100].map(n => W.numberWord(n, 'es')),
  ['uno', 'dieciséis', 'veintiuno', 'veintidós', 'veintitrés', 'veintiséis', 'treinta y uno', 'cuarenta y cinco', 'cien']);
check('Swedish numbers', [1, 18, 21, 34, 100].map(n => W.numberWord(n, 'sv')), ['ett|en', 'arton', 'tjugoett|tjugoen', 'trettiofyra', 'hundra|etthundra']);
const seven = cards.en.siffror.fran.find(c => c.front.text === 'seven');
check('the number cards show the digits, and take the digits or the word back', [cards.en.siffror.till[7].front.text, W.check('7', seven.accept, { lang: 'sv' }).ok, W.check('sju', seven.accept, { lang: 'sv' }).ok],
  ['7', true, true]);

// --- judging an answer ---------------------------------------------------------
const J = (typed, accepted, opts) => { const r = W.check(typed, accepted, opts); return [r.ok, r.verdict]; };
check('case, spaces and punctuation do not matter', [J('  Dog ', ['dog'], { lang: 'en' }), J('dog!', ['dog'], { lang: 'en' })], [[true, 'right'], [true, 'right']]);
check('the English article and "to" may come along', [J('a dog', ['dog'], { lang: 'en' }), J('to eat', ['eat'], { lang: 'en' }), J('an apple', ['apple'], { lang: 'en' })],
  [[true, 'right'], [true, 'right'], [true, 'right']]);
check('the Swedish article and "att" may come along', [J('en hund', ['hund'], { lang: 'sv' }), J('att tycka om', ['tycka om'], { lang: 'sv' })], [[true, 'right'], [true, 'right']]);
check('every alternative is right', [J('mom', ['mum', 'mom', 'mother'], { lang: 'en' }), J('gray', W.alternatives('grey|gray'), { lang: 'en' })], [[true, 'right'], [true, 'right']]);
check('each side of " / " is right on its own', [J('farmor', W.alternatives('mormor / farmor'), { lang: 'sv' }), J('mormor / farmor', W.alternatives('mormor / farmor'), { lang: 'sv' })],
  [[true, 'right'], [true, 'right']]);
check('twenty-one with or without the hyphen', [J('twenty one', ['twenty-one'], { lang: 'en' }), J('twenty-one', ['twenty-one'], { lang: 'en' })], [[true, 'right'], [true, 'right']]);
check('apostrophes do not matter', [J('whats your name', ["what's your name?"], { lang: 'en' }), J("I'm fine", ["I'm fine"], { lang: 'en' })], [[true, 'right'], [true, 'right']]);
const monday = W.check('monday', ['Monday'], { lang: 'en' });
check('a lower-case Monday is right, with a word on how it is written', [monday.ok, monday.note], [true, 'Rätt! Det skrivs Monday.']);
check('one letter off is almost, and does not count', [J('dgo', ['dog'], { lang: 'en' }), J('wiht', ['with'], { lang: 'en' }), J('bredvd', ['bredvid'], { lang: 'sv' })],
  [[false, 'wrong'], [false, 'almost'], [false, 'almost']]);
check('a swap of two letters is one slip', W.levenshtein('wnet', 'went'), 1);
check('three letters are too few to be almost', J('cot', ['cat'], { lang: 'en' }), [false, 'wrong']);
check('å, ä and ö are letters, not accents: häst is not hast', [J('hast', ['häst'], { lang: 'sv' }), J('häst', ['häst'], { lang: 'sv' })], [[false, 'almost'], [true, 'right']]);
const raton = W.check('raton', ['el ratón'], { lang: 'es', accents: 'valfri' });
check('a missing Spanish accent is right by default, and says how it is spelt', [raton.ok, raton.note], [true, 'Rätt! Det stavas el ratón.']);
check('unless accents must be right', J('raton', ['el ratón'], { lang: 'es', accents: 'krav' }), [false, 'accent']);
check('ñ without its tilde is an accent too', [J('pina', ['la piña'], { lang: 'es', accents: 'valfri' }), J('pina', ['la piña'], { lang: 'es', accents: 'krav' })],
  [[true, 'right'], [false, 'accent']]);
const perro = W.check('perro', ['el perro'], { lang: 'es', article: 'valfri' });
check('a Spanish noun without its article is right by default, and shows the article', [perro.ok, perro.note], [true, 'Rätt! Med artikel: el perro.']);
check('unless the article must be there', J('perro', ['el perro'], { lang: 'es', article: 'krav' }), [false, 'article']);
const laPerro = W.check('la perro', ['el perro'], { lang: 'es' });
check('the wrong article is wrong, and says which one', [laPerro.ok, laPerro.verdict, laPerro.note], [false, 'article', 'Fel artikel – det heter el perro.']);
check('the right alternative wins over a wrong article', J('la niña', W.alternatives('el niño|la niña'), { lang: 'es' }), [true, 'right']);
check('Spanish question marks do not matter, nor do the accents by default', J('como te llamas', ['¿cómo te llamas?'], { lang: 'es' }), [true, 'right']);
check('a gap in a phrase takes the child’s own name', [J('jag heter Anna', ['jag heter …'], { lang: 'sv' }), J('my name is Anna', ['my name is …'], { lang: 'en' })],
  [[true, 'right'], [true, 'right']]);
check('an empty answer is not judged', J('   ', ['dog'], { lang: 'en' }), [false, 'empty']);
check('something else is wrong', J('katt', ['hund'], { lang: 'sv' }), [false, 'wrong']);

// --- the grammar cards ------------------------------------------------------------
const go = cards.en.irr1.till.find(c => c.base === 'go');
const forms = t => { const r = W.judge(go, t); return [r.ok, r.verdict]; };
check('irregular verbs: the two forms in any way of writing them',
  ['went gone', 'went, gone', 'went - gone', 'went – gone', 'go went gone', 'Went Gone'].map(forms), Array(6).fill([true, 'right']));
check('one form alone is not enough, and says so', [forms('went'), W.judge(go, 'went').note], [[false, 'wrong'], 'Skriv båda formerna: dåtid och perfekt particip.']);
check('a spelling slip in a form is almost', forms('wnet gone'), [false, 'almost']);
const be = cards.en.irr1.till.find(c => c.base === 'be');
check('be: was, were or both', ['was been', 'were been', 'was/were been', 'was were been'].map(t => W.judge(be, t).ok), [true, true, true, true]);
const read = cards.en.irr1.till.find(c => c.base === 'read');
check('read – read – read, however many times it is written', ['read read', 'read read read'].map(t => W.judge(read, t).ok), [true, true]);
const get = cards.en.irr1.till.find(c => c.base === 'get');
check('get – got – got or gotten', ['got got', 'got gotten'].map(t => W.judge(get, t).ok), [true, true]);
const genusPerro = cards.es.genus.till.find(c => c.front.text === 'perro');
check('el or la: the article, or the article and the noun',
  ['el', 'El perro', 'la'].map(t => W.judge(genusPerro, t).ok), [true, true, false]);
check('la mano is la, though it ends in -o', cards.es.genus.till.find(c => c.front.text === 'mano').answer, 'la');
check('el agua is left out of el or la', cards.es.genus.till.some(c => c.front.text === 'agua'), false);
const tengo = cards.es.konj1.till.find(c => c.key === 'es|konj|tener|0');
check('verb forms with or without the pronoun', ['tengo', 'yo tengo', 'tienes'].map(t => W.judge(tengo, t).ok), [true, true, false]);
const estas = cards.es.konj1.till.find(c => c.key === 'es|konj|estar|1');
check('estás: the accent may be missing unless it must be there',
  [W.judge(estas, 'tu estas', { accents: 'valfri' }).ok, W.judge(estas, 'estas', { accents: 'krav' }).verdict], [true, 'accent']);

// --- keys: the same word is the same card ------------------------------------------
const listCards = W.cardsFor({ id: 'l1', list: true, words: [['hund', 'dog'], ['katt', 'cat']] }, 'en', 'till');
check('"hund = dog" in a list of one’s own is the same card as in Djur', listCards[0].key, cards.en.husdjur.till[0].key);
check('the two ways round are two cards', [cards.en.husdjur.till[0].key, cards.en.husdjur.fran[0].key], ['en|till|dog|hund', 'en|fran|dog|hund']);

// --- hints -------------------------------------------------------------------------
check('the hint is the first letter and a line for the rest', [W.letters('dog', 'en'), W.letters('ice cream', 'en')], ['d _ _', 'i _ _   c _ _ _ _']);
check('a Spanish article is given in the hint', W.letters('el perro', 'es'), 'el   p _ _ _ _');
check('the verb hint shows the base form and a start of each', W.hint(go), 'go – w _ _ _ – g _ _ _');
const leaks = ['en', 'es'].flatMap(l => all(l).filter(c => c.kind === 'word' && c.answer.length > 2 && W.normalize(W.hint(c)) === W.normalize(c.answer)).map(c => c.key));
check('no hint is the whole answer', leaks, []);

// --- four to choose from ----------------------------------------------------------------
let seed = 1;
const rnd = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
const pool = cards.en.verb.till;
const spela = pool.find(c => c.front.text === 'spela');
const opts = W.options(spela, pool, rnd);
check('four options, the right one among them, all different', [opts.length, opts.includes('play'), new Set(opts.map(W.normalize)).size], [4, true, 4]);
const allFour = ['en', 'es'].flatMap(l => Object.values(cards[l]).flatMap(c => c.till.map(card => {
  const o = W.options(card, c.till, rnd);
  return { key: card.key, ok: o.includes(card.answer) && new Set(o.map(W.normalize)).size === o.length && o.filter(x => W.judge(card, x).ok).length === 1 };
}))).filter(x => !x.ok).map(x => x.key);
check('in every pile, exactly one of the options is right', allFour, []);
check('el or la has just the two', W.options(genusPerro, cards.es.genus.till, rnd).sort(), ['el', 'la']);

// --- lists of one's own ---------------------------------------------------------------------
const parsed = W.parseList('# vecka 12\nhund = dog\nkatt - cat\nhäst – horse\nko\tcow\nfår; sheep\nget: goat\nmamma = mum / mom\n\nbara ett ord\n');
check('a list as teachers write it', parsed.words, [['hund', 'dog'], ['katt', 'cat'], ['häst', 'horse'], ['ko', 'cow'], ['får', 'sheep'], ['get', 'goat'], ['mamma', 'mum|mom']]);
check('a line without a pair is reported with its number', parsed.errors, [{ line: 10, text: 'bara ett ord' }]);
check('a hyphen inside a word is not a separator', W.parseList('t-shirt = t-shirt\nhej då - goodbye').words, [['t-shirt', 't-shirt'], ['hej då', 'goodbye']]);
check('and back to text for editing', W.listText([['mamma', 'mum|mom']]), 'mamma = mum / mom');
check('at most 200 words', W.parseList(Array.from({ length: 205 }, (_, i) => `ord${i} = word${i}`).join('\n')).words.length, 200);

// --- sharing a list ----------------------------------------------------------------------------
const list = { name: 'Vecka 12 – åäö', lang: 'es', words: [['hund', 'el perro'], ['år', 'el año'], ['hej', '¡hola!']] };
const link = W.encodeShare(list);
check('a shared list survives the link, åäö, ñ and ¡ included', W.decodeShare(link), list);
check('the link is safe in an address', /^[A-Za-z0-9_-]+$/.test(link), true);
const enc = obj => W.encodeShare({ name: obj.n, lang: obj.l, words: obj.w });
check('nonsense is not a list', ['', '!!!', 'aGVq', enc({ n: 'x', l: 'fr', w: [['a', 'b']] }), enc({ n: 'x', l: 'en', w: [] })].map(W.decodeShare), [null, null, null, null, null]);
const hostile = W.decodeShare(enc({ n: 'x'.repeat(500), l: 'en', w: [['<img src=x onerror=alert(1)>', 'y'.repeat(500)], [1, 2], ['ok', 'fine']] }));
check('a hostile list is cut down to text of a sane size',
  [hostile.name.length, hostile.words.length, hostile.words[0][0], hostile.words[0][1].length], [40, 2, '<img src=x onerror=alert(1)>', 80]);

// --- Leitner's boxes -------------------------------------------------------------------------------
let st = W.nextStat(null, true, '2026-09-30');
check('right the first time: known at once (box 3)', [st.box, W.statusOf(st)], [3, 'kan']);
st = W.nextStat(st, false, '2026-09-30');
check('wrong: back to box 1, due every day', [st.box, W.isDue(st, '2026-09-30')], [1, true]);
st = W.nextStat(st, true, '2026-09-30');
check('then right: box 2, not due again for two days', [st.box, W.isDue(st, '2026-10-01'), W.isDue(st, '2026-10-02')], [2, false, true]);
st = W.nextStat(st, true, '2026-10-02');
check('right again: box 3, due after a week', [st.box, W.isDue(st, '2026-10-08'), W.isDue(st, '2026-10-09')], [3, false, true]);
check('a word never practised is not due', W.isDue(undefined, '2026-10-01'), false);

console.log(`\n${checks - failures.length} of ${checks} checks passed.`);
process.exit(failures.length ? 1 : 0);
