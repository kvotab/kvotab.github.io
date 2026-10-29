#!/usr/bin/env node
/*
  The subtitle work of svensk_text.html, without a page and without a
  translator: reading .srt and .vtt, leaving out what subtitles for the deaf
  carry, the English made ready for the translator, the Swedish put back over
  the subtitles and mended, and the check of every subtitle.

      node resources/tests/svensk_text/test-core.js

  Exit status 0 when every check passes.
*/
'use strict';
const path = require('path');
const C = require(path.join(__dirname, '../../js/svensk_text-core.js'));

let checks = 0;
const failures = [];
function check(label, got, want = true) {
  checks++;
  const ok = JSON.stringify(got) === JSON.stringify(want);
  console.log(`${ok ? 'ok  ' : 'FAIL'}  ${label}${ok ? '' : `: ${JSON.stringify(got)} (expected ${JSON.stringify(want)})`}`);
  if (!ok) failures.push(label);
}

const O = { cps: 17, maxLen: 42, dash: 'nospace', extend: true, sdh: 'remove', fillers: true, encoding: 'utf8bom' };

// --- reading subtitle files -------------------------------------------------
const parsed = C.parseSubtitles(C.SAMPLE_SRT);
check('the sample has 24 subtitles', parsed.length, 24);
check('times in milliseconds', [parsed[1].start, parsed[1].end], [2800, 5100]);
check('a subtitle keeps its lines', parsed[3].raw, "- At two in the morning?\n- I'm sorry, okay?");
{
  const s = '﻿1\r\n00:00:01,000 --> 00:00:02,000\r\nHello\r\n2\r\n00:00:03,000 --> 00:00:04,500\r\nWorld\r\n\r\n\r\n3\r\n00:00:05,000 --> 00:00:06,000 X1:10 X2:20\r\nLast line\r\n';
  const r = C.parseSubtitles(s);
  check('CRLF, a BOM, a missing blank line and coordinates after the time', r.map(x => x.raw), ['Hello', 'World', 'Last line']);
}
{
  const r = C.parseSubtitles('WEBVTT\n\nNOTE a note\n\nid-1\n00:01.000 --> 00:02.500 align:start\n<v Roger>Hi there\n\n01:00:00.000 --> 01:00:01.000\n<c.yellow>Yes</c>');
  check('WebVTT: short times, cue settings, notes and ids', [r.length, r[0].start, r[0].end, r[1].start], [2, 1000, 2500, 3600000]);
  check('WebVTT voice and class tags go', [C.normalizeCue(r[0].raw).text, C.normalizeCue(r[1].raw).text], ['Hi there', 'Yes']);
}
check('UTF-8', C.decodeBytes(new TextEncoder().encode('Hej på dig')), 'Hej på dig');
check('Windows-1252 when it is not UTF-8', C.decodeBytes(Uint8Array.from([0x48, 0xE5, 0x6C])), 'Hål');
check('UTF-16 with a BOM', C.decodeBytes(new Uint8Array(Buffer.from('﻿Hej', 'utf16le'))), 'Hej');
{
  const n = C.normalizeCue('{\\an8}<i>Hello\nthere</i>');
  check('a position tag and italics over the whole subtitle are taken out and remembered', [n.pos, n.ital, n.text], ['{\\an8}', true, 'Hello\nthere']);
  check('font tags go, tag case is evened', C.normalizeCue('<font color="#ffff00">Hi</font> <I>you</I>').text, 'Hi <i>you</i>');
  check('every line in italics is the whole subtitle in italics', C.normalizeCue('<i>one</i>\n<i>two</i>').ital, true);
}

// --- what subtitles for the deaf carry ---------------------------------------
for (const [a, b] of [
  ['[door slams]', ''],
  ["(SIGHS) You sold Dad's car?", "You sold Dad's car?"],
  ['JOHN: Hello there.', 'Hello there.'],
  ['- MAN #2: Hey!\n- WOMAN: What?', '- Hey!\n- What?'],
  ['- [gasps]\n- What was that?', 'What was that?'],
  ['♪ ♪', ''],
  ['♪ Happy birthday to you ♪', '♪ Happy birthday to you ♪'],
  ['Meet me at 3:30.', 'Meet me at 3:30.'],
  ['I: am fine', 'I: am fine'],
  ['DR. SMITH (ON TV): The results are in.', 'The results are in.'],
  ['<i>[man on radio] Breaking news.</i>', '<i>Breaking news.</i>'],
]) check(`sound description: ${JSON.stringify(a)}`, C.cleanSDH(a), b);

// --- the English made ready ---------------------------------------------------
for (const [a, b] of [
  ['Um, well, you know... I got held up at work.', 'I got held up at work.'],
  ["That the company you've been killing yourself for is being sold for, like, two billion dollars", "That the company you've been killing yourself for is being sold for two billion dollars"],
  ['Do you know what I mean?', 'Do you know what I mean?'],
  ["I-I-I don't know.", "I don't know."],
  ['W-What?', 'What?'],
  ["Well, that's that.", "That's that."],
  ['So, uh, where were we?', 'Where were we?'],
  ['You know, I like you.', 'I like you.'],
  ['I like you, you know?', 'I like you.'],
  ['Uh...', ''],
  ['Er, hello?', 'Hello?'],
  ['Her umbrella is here.', 'Her umbrella is here.'],
  ['It was, like, huge.', 'It was huge.'],
]) check(`filler: ${JSON.stringify(a)}`, C.preClean(a), b);

const cues = parsed.map((c, i) => {
  const nc = C.normalizeCue(c.raw), en = C.cleanSDH(nc.text);
  return { n: i + 1, start: c.start, end: c.end, raw: nc.text, en, ital: nc.ital, pos: nc.pos, removed: !en, sv: null };
});
const units = C.buildUnits(cues, { fillers: true });
check('the sample is 23 sentences', units.length, 23);
check('two of them run over two subtitles: 6 and 7, 15 and 16', units.filter(u => u.parts.length > 1).map(u => u.parts.map(p => p.n)), [[6, 7], [15, 16]]);
check('every sentence is either in Google’s sample output or in the phrasebook',
  units.filter(u => u.text && !C.phrasebook(u.text) && !(u.text in C.SAMPLE_GOOGLE)).map(u => u.text), []);
{
  const kept = C.buildUnits(cues.map(c => ({ ...c, en: c.raw, removed: !c.raw })), { fillers: true });
  check('with the sound descriptions translated, 24 sentences, all in Google’s sample output or the phrasebook',
    [kept.length, kept.filter(u => u.text && !C.phrasebook(u.text) && !(u.text in C.SAMPLE_GOOGLE)).map(u => u.text)], [24, []]);
  const u = C.buildUnits([{ n: 1, start: 0, end: 1000, en: 'If you had answered,' }, { n: 2, start: 1100, end: 2000, en: '[door slams]' },
    { n: 3, start: 2100, end: 3000, en: "we wouldn't have driven." }], { fillers: true });
  check('a sound description kept in mid-sentence is a sentence of its own', u.map(x => x.text), ['If you had answered,', '[door slams]', "we wouldn't have driven."]);
}
check('a sentence ending in a comma goes on', C.continues('If you go,', 'I go too.', 300), true);
check('one that trails off goes on into "..."', C.continues('I was going to...', '...say something.', 300), true);
check('but not into a new sentence', C.continues('I was going to...', 'Never mind.', 300), false);
check('nor across a pause of three seconds', C.continues('and then the', 'car stopped.', 3000), false);
check('nor after a full stop', C.continues('He said.', 'and left.', 100), false);
check('nor without punctuation into a capital', C.continues('Hello', 'How are you?', 300), false);
{
  const u = C.buildUnits([{ n: 1, start: 0, end: 1000, en: '- Hi.\n- Hello.' }, { n: 2, start: 1100, end: 2000, en: 'Fine.' }], { fillers: true });
  check('each speaker’s line is a sentence of its own', u.map(x => x.text), ['Hi.', 'Hello.', 'Fine.']);
}
check('sentences, with Dr. and Mr. not ending one', [C.splitSentences('Dr. Patel? Are you sick?'), C.splitSentences("Hi, this is Dr. Patel's office calling for Mr. William Carter.").length], [['Dr. Patel?', 'Are you sick?'], 1]);
{
  const names = C.collectNames(cues);
  check('names: the capitals in mid-sentence, not a greeting', [...names].sort(), ['Carter', 'Dr', 'Hope', 'Mr', 'Mrs', 'Ms', 'Patel', 'Will', 'William']);
  check('a name on its own is not sent to the translator', ['Will!', 'Dr. Patel?', 'Dad!', 'Where is Will?'].map(s => C.isNamesOnly(s, names)), [true, true, false, false]);
}

// --- the Swedish put back ------------------------------------------------------
{
  const u67 = units.find(u => u.parts[0].n === 6), u1516 = units.find(u => u.parts[0].n === 15);
  check('one sentence divided where Google itself would break it',
    C.splitForParts('Om du hade svarat i telefonen bara en enda gång hade vi inte behövt köra åtta mil för att leta efter dig.', u67.parts.map(p => C.visLen(p.clean))),
    ['Om du hade svarat i telefonen bara en enda gång', 'hade vi inte behövt köra åtta mil för att leta efter dig.']);
  check('a dash at the break goes',
    C.splitForParts('Att företaget du har slitit ihjäl dig för säljs för två miljarder dollar – och att du inte får någonting.', u1516.parts.map(p => C.visLen(p.clean))),
    ['Att företaget du har slitit ihjäl dig för säljs för två miljarder dollar', 'och att du inte får någonting.']);
  const three = 'Jag tänkte att vi kunde åka till stugan i helgen, om du vill, och bada i sjön.';
  const r = C.splitForParts(three, [20, 15, 25]);
  check('three ways, in order, nothing lost', [r.length, r.join(' ') === three, r.every(Boolean)], [3, true, true]);
}
check('a good two-line break is kept', C.rebreak('hade vi inte kört åtta mil\nför att hitta dig.', 42), 'hade vi inte kört åtta mil\nför att hitta dig.');
check('a long line is broken within the limit', C.rebreak('Jag trodde att du skulle komma hem tidigare i kväll, men du gjorde inte det.', 42).split('\n').every(l => C.visLen(l) <= 42), true);
check('not after a preposition', /\s(i|på|och)\n/.test(C.rebreak('Hon har bott i Stockholm i många år och tänker aldrig flytta.', 42)), false);
check('nor between a number and what it counts', C.rebreak('hade vi inte behövt köra åtta mil för att leta efter dig.', 42), 'hade vi inte behövt köra\nåtta mil för att leta efter dig.');
check('two speakers keep a line each', C.rebreak('-Kommer du?\n-Ja.', 42), '-Kommer du?\n-Ja.');
check('speaker hyphens, one ellipsis character', C.polish('- Kommer du?\n– Ja...', O), '-Kommer du?\n-Ja…');
check('or with a space', C.polish('-Kommer du?\n-Ja.', { ...O, dash: 'space' }), '- Kommer du?\n- Ja.');
check('straight quotes', C.polish('Han sa ”hej”.', O), 'Han sa "hej".');
for (const [a, b] of [["I'm sorry.", 'Förlåt.'], ['Sorry?', 'Ursäkta?'], ['Hey!', 'Hallå!'], ['Hey.', 'Hej.'], ['What the hell?!', 'Vad fan?'], ['Okay...', 'Okej…'],
  ["Let's just call it a night.", 'Nu räcker det för i kväll.'], ['Oh, my God.', 'Herregud.'], ['Thank you, Will.', null], ['Mom?', 'Mamma?']]) {
  check(`phrasebook: ${a}`, C.phrasebook(a), b);
}
for (const [sv, en, want] of [
  ['Jag är ledsen, okej?', "I'm sorry, okay?", 'Förlåt, okej?'],
  ['Jag är ledsen för din förlust.', "I'm sorry for your loss.", 'Jag är ledsen för din förlust.'],
  ['Eventuellt måste du berätta.', "Eventually you'll have to tell.", 'Till slut måste du berätta.'],
  ['Det kostar två biljoner dollar.', 'It costs two billion dollars.', 'Det kostar två miljarder dollar.'],
  ['Vi körde 50 mil.', 'We drove 50 miles.', 'Vi körde 80 km.'],
  ['Vi körde femtio mil.', 'We drove fifty miles.', 'Vi körde 80 km.'],
  ['Vi körde åttio mil.', 'We drove eighty miles.', 'Vi körde 129 km.'],
  ['Vi körde åtta mil.', 'We drove fifty miles.', 'Vi körde åtta mil.'],
  ['Vi körde 50 km.', 'We drove 50 miles.', 'Vi körde 80 km.'],
  ['Hej killar!', 'Hey, guys!', 'Hej allihop!'],
  ['Åh min Gud!', 'Oh my God!', 'Herregud!'],
  ['Jag har 3 barn och 12 katter.', 'I have 3 kids and 12 cats.', 'Jag har tre barn och 12 katter.'],
  ['3 dagar kvar.', '3 days left.', 'Tre dagar kvar.'],
  ['Kom kl. 3 den 5 maj.', 'Come at 3 on May 5.', 'Kom kl. 3 den 5 maj.'],
  ['Det kostar 10 000 kronor.', 'It costs 10,000 kronor.', 'Det kostar 10 000 kronor.'],
  ['Ses vid 3:30.', 'See you at 3:30.', 'Ses vid 3.30.'],
  ['Prata med Dr. Patel och Mr. Smith.', 'Talk to Dr. Patel and Mr. Smith.', 'Prata med dr Patel och mr Smith.'],
  ['Dr. Patel? Är du sjuk?', 'Dr. Patel? Are you sick?', 'Dr Patel? Är du sjuk?'],
  ['Det kostar $50.', 'It costs $50.', 'Det kostar 50 dollar.'],
  ['Äh, jag vet inte.', "Uh, I don't know.", 'Jag vet inte.'],
]) check(`mended: ${sv}`, C.postFix(sv, en, []), want);

// --- the check of every subtitle -------------------------------------------------
{
  const c = { n: 1, start: 57400, end: 59300, en: '- Night, Will.\n- Night, sis.', sv: '-God natt, Will.\n-God natt, syrran.' };
  const q = C.computeQA(c, null, O);
  check('34 characters in 1.9 s: lengthened into the pause to 2.0 s, 17 a second', [q.chars, q.end, q.cps.toFixed(2), q.level], [34, 59400, '17.00', 'ok']);
  check('without lengthening it is a little fast', C.computeQA(c, null, { ...O, extend: false }).level, 'warn');
  check('lengthening stops short of the next subtitle', C.computeQA({ n: 1, start: 0, end: 1000, en: 'x', sv: 'a'.repeat(30) }, { start: 1200 }, O).end, 1116);
  const codes = (en, sv) => C.computeQA({ n: 1, start: 0, end: 6000, en, sv }, null, O).issues.map(i => i.code);
  check('a line over 42 and a lost number', codes('I have 25 cats', 'Jag har katter och det är en väldigt lång rad som inte får plats'), ['len', 'num']);
  check('English left as it was', codes('What is this thing you have?', 'What is this thing you have?'), ['english']);
  check('an italics tag left open', codes('Hi', '<i>Hej'), ['tags']);
  check('a wrong time', codes('Call us before 3:30 tomorrow.', 'Ring oss före halv nio i morgon.'), ['time']);
  check('a right time, as digits or as Swedish speaks it', [C.timeKept('Ring före 15.30 i morgon.', 3, 30), C.timeKept('Ring före halv fyra i morgon.', 3, 30), C.timeKept('Vi ses kvart i fem.', 4, 45)], [true, true, true]);
  check('thousands and clock times are not lost numbers', C.missingNumbers('It costs $2,000 at 3:30', 'Det kostar 2 000 dollar halv fyra'), []);
}

// --- the sample, start to end ---------------------------------------------------------
{
  const pieces = {};
  for (const u of units) {
    let sv = C.phrasebook(u.text);
    if (!sv) sv = u.text ? C.postFix(C.SAMPLE_GOOGLE[u.text], u.text, []) : '';
    const live = u.parts.filter(p => p.clean);
    const ps = live.length > 1 ? C.splitForParts(sv, live.map(p => C.visLen(p.clean))) : [sv];
    live.forEach((p, i) => { (pieces[p.n] = pieces[p.n] || {})[p.k] = ps[i]; });
  }
  for (const c of cues) {
    if (c.removed) continue;
    const kept = Object.keys(pieces[c.n]).sort().map(k => pieces[c.n][k]).filter(Boolean);
    c.sv = C.polish(kept.length > 1 ? kept.map(x => '-' + x).join('\n') : (kept[0] || ''), O);
  }
  const qa = cues.map(c => C.computeQA(c, C.nextActiveIn(cues, c.n), O));
  check('every subtitle but the door gets Swedish', cues.filter(c => c.sv).length, 23);
  check('two speakers in subtitle 4', cues[3].sv, '-Klockan två på natten?\n-Förlåt, okej?');
  check('"call it a night" from the phrasebook, not Google’s "Vi säger god natt nu"', cues[22].sv, 'Nu räcker det för i kväll.');
  check('the subtitles to look at are the ones Google left too long', qa.map((q, i) => (q.level === 'warn' || q.level === 'bad') ? i + 1 : 0).filter(Boolean), [6, 7, 9, 12, 13, 15, 22]);
  const srt = C.buildSRT(cues, qa, O);
  check('the .srt starts at subtitle 2, numbered 1', srt.split('\n').slice(0, 3), ['1', '00:00:02,800 --> 00:00:05,100', 'Will! Vart i helvete har du hållit hus?']);
  check('the voicemail stays in italics', srt.includes('<i>Hej, det här är dr Patels mottagning\nsom söker William Carter.</i>'), true);
  check('23 subtitles in it', srt.trim().split('\n\n').length, 23);
}
{
  const u = C.encodeText('1\r\n', 'utf8bom');
  check('UTF-8 with a BOM', [...u.bytes.slice(0, 3)], [0xEF, 0xBB, 0xBF]);
  const w = C.encodeText('Åsa – ”hej” … ♪', 'cp1252');
  check('Windows-1252, with a "?" for what it lacks', [[...w.bytes], w.bad], [[0xC5, 0x73, 0x61, 0x20, 0x96, 0x20, 0x94, 0x68, 0x65, 0x6A, 0x94, 0x20, 0x85, 0x20, 0x3F], 1]);
  const ch = C.chunkUnits(Array.from({ length: 30 }, (_, i) => ({ text: 'x'.repeat(i === 5 ? 1400 : 50) })), 12, 1500);
  check('requests of at most twelve sentences, none lost', [ch.every(c => c.length <= 12), ch.flat().length], [true, 30]);
  check('the saved name says Swedish', ['Movie.Name.2023.en.srt', 'Show S01E02.eng.sdh.srt', 'film.vtt'].map(C.outName), ['Movie.Name.2023.sv.srt', 'Show S01E02.sv.srt', 'film.sv.srt']);
}

console.log(`\n${checks - failures.length} of ${checks} checks passed`);
if (failures.length) {
  console.log('FAILED:\n  ' + failures.join('\n  '));
  process.exit(1);
}
