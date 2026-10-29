/* ==========================================================================
   SVENSK TEXT - the subtitle work around the translator (svensk_text.html)

   Everything here is plain functions over strings and numbers, with no page
   and no translator in it, so test-core.js can run it in Node:

     - reading .srt and .vtt (UTF-8, UTF-16 or Windows-1252) and leaving out
       what subtitles for the deaf carry ([door slams], (SIGHS), NAME:);
     - the English made ready: hesitations and fillers out, and the
       subtitles that make up one sentence joined, so the translator sees
       whole sentences rather than the pieces a subtitle file cuts them into;
     - the Swedish put back: the sentence divided over its subtitles at
       phrase boundaries, a phrasebook for the commonest short lines, the
       usual machine-translation slips mended, and lines broken bottom-heavy
       within the limit;
     - the check of every subtitle (two lines, 42 characters, 17 characters
       a second, as in Netflix's Swedish style guide) and the .srt written.

   SAMPLE_GOOGLE is what translate.google.com returned on 29 October 2026 for
   the prepared sentences of SAMPLE_SRT; the page shows it on a first visit.
   ========================================================================== */

const ST_CORE = (() => {

  const SAMPLE_SRT = `1
00:00:01,000 --> 00:00:02,400
[door slams]

2
00:00:02,800 --> 00:00:05,100
Will! Where the hell have you been?

3
00:00:05,300 --> 00:00:07,600
Um, well, you know... I got held up at work.

4
00:00:07,900 --> 00:00:10,400
- At two in the morning?
- I'm sorry, okay?

5
00:00:10,800 --> 00:00:12,900
Mom's been calling you all night.

6
00:00:13,100 --> 00:00:15,600
If you had answered your phone even once,

7
00:00:15,700 --> 00:00:18,200
we wouldn't have driven
fifty miles looking for you.

8
00:00:18,600 --> 00:00:20,700
You guys drove into the city? Seriously?

9
00:00:21,200 --> 00:00:24,300
<i>Hi, this is Dr. Patel's office
calling for Mr. William Carter.</i>

10
00:00:24,500 --> 00:00:27,000
<i>Please call us back
before 3:30 tomorrow.</i>

11
00:00:27,400 --> 00:00:29,000
Dr. Patel? Are you sick?

12
00:00:29,200 --> 00:00:31,000
It's nothing. Just a checkup.

13
00:00:31,400 --> 00:00:33,600
Eventually you'll have to tell her.

14
00:00:33,800 --> 00:00:34,900
Tell her what?

15
00:00:35,100 --> 00:00:38,600
That the company you've been killing yourself for
is being sold for, like, two billion dollars

16
00:00:38,700 --> 00:00:40,400
and you're getting nothing.

17
00:00:40,800 --> 00:00:43,000
Actually, I'm getting a bonus.

18
00:00:43,300 --> 00:00:45,400
Where's the car, Will?

19
00:00:45,600 --> 00:00:47,200
I sold it.

20
00:00:47,500 --> 00:00:49,800
(SIGHS) You sold Dad's car?

21
00:00:50,000 --> 00:00:52,600
I'm sorry. I needed the money.

22
00:00:53,000 --> 00:00:55,400
Your audition's tomorrow, right?
Break a leg, Hope.

23
00:00:55,600 --> 00:00:57,200
Let's just call it a night.

24
00:00:57,400 --> 00:00:59,300
- Night, Will.
- Night, sis.
`;

  // What translate.google.com returned for the prepared sample sentences (English to Swedish, 29 October 2026).
  const SAMPLE_GOOGLE = {
    'Will! Where the hell have you been?': 'Will! Vart i helvete har du hållit hus?',
    'I got held up at work.': 'Jag blev kvar på jobbet.',
    'At two in the morning?': 'Klockan två på natten?',
    "I'm sorry, okay?": 'Förlåt, okej?',
    "Mom's been calling you all night.": 'Mamma har ringt dig hela natten.',
    "If you had answered your phone even once, we wouldn't have driven fifty miles looking for you.": 'Om du hade svarat i telefonen bara en enda gång hade vi inte behövt köra åtta mil för att leta efter dig.',
    'You guys drove into the city? Seriously?': 'Åkte ni in till stan? På allvar?',
    "Hi, this is Dr. Patel's office calling for Mr. William Carter.": 'Hej, det här är dr Patels mottagning som söker William Carter.',
    'Please call us back before 3:30 tomorrow.': 'Ring oss gärna före 15.30 i morgon.',
    'Dr. Patel? Are you sick?': 'Dr Patel? Är du sjuk?',
    "It's nothing. Just a checkup.": 'Det är inget. Bara en vanlig kontroll.',
    "Eventually you'll have to tell her.": 'Förr eller senare måste du berätta det för henne.',
    'Tell her what?': 'Berätta vadå?',
    "That the company you've been killing yourself for is being sold for two billion dollars and you're getting nothing.": 'Att företaget du har slitit ihjäl dig för säljs för två miljarder dollar – och att du inte får någonting.',
    "Actually, I'm getting a bonus.": 'Jag får faktiskt en bonus.',
    "Where's the car, Will?": 'Var är bilen, Will?',
    'I sold it.': 'Jag sålde den.',
    "You sold Dad's car?": 'Sålde du pappas bil?',
    "I'm sorry. I needed the money.": 'Förlåt. Jag behövde pengarna.',
    "Your audition's tomorrow, right? Break a leg, Hope.": 'Du har väl en provspelning i morgon? Lycka till, Hope.',
    "Let's just call it a night.": 'Vi säger god natt nu.',
    'Night, Will.': 'God natt, Will.',
    'Night, sis.': 'God natt, syrran.'
  };

  const TIME_RE = /(?:(\d{1,2}):)?(\d{1,2}):(\d{1,2})[,.](\d{1,3})\s*-->\s*(?:(\d{1,2}):)?(\d{1,2}):(\d{1,2})[,.](\d{1,3})/;
  const TAG_RE = /<[^>]*>|\{\\[^}]*\}/g;

  function pad(n, w) { return String(n).padStart(w, '0'); }
  function toMs(h, m, s, f) { return ((+(h || 0)) * 3600 + (+m) * 60 + (+s)) * 1000 + (+String(f).padEnd(3, '0').slice(0, 3)); }
  function fmtSrtTime(ms) {
    ms = Math.max(0, Math.round(ms));
    return `${pad(Math.floor(ms / 3600000), 2)}:${pad(Math.floor(ms / 60000) % 60, 2)}:${pad(Math.floor(ms / 1000) % 60, 2)},${pad(ms % 1000, 3)}`;
  }
  function fmtClock(ms) {
    const t = Math.max(0, Math.floor(ms / 1000)), h = Math.floor(t / 3600), m = Math.floor(t / 60) % 60, s = t % 60;
    return h ? `${h}:${pad(m, 2)}:${pad(s, 2)}` : `${pad(m, 2)}:${pad(s, 2)}`;
  }
  function stripTags(s) { return String(s ?? '').replace(TAG_RE, ''); }
  function visLen(s) { return Array.from(stripTags(s)).length; }
  function wordCount(s) { return (stripTags(s).match(/[\p{L}\p{N}']+/gu) || []).length; }
  function isDlgLine(l) { return /^\s*(?:<[^>]+>\s*)*[-–—]/.test(l); }
  function isDialogue(t) { const ls = String(t).split('\n'); return ls.length >= 2 && ls.filter(isDlgLine).length >= 2; }

  function decodeBytes(input) {
    const b = input instanceof Uint8Array ? input : new Uint8Array(input);
    if (b[0] === 0xFF && b[1] === 0xFE) return new TextDecoder('utf-16le').decode(b.subarray(2));
    if (b[0] === 0xFE && b[1] === 0xFF) return new TextDecoder('utf-16be').decode(b.subarray(2));
    if (b.length > 3 && b[1] === 0 && b[3] === 0) return new TextDecoder('utf-16le').decode(b);
    try { return new TextDecoder('utf-8', { fatal: true }).decode(b).replace(/^﻿/, ''); }
    catch { return new TextDecoder('windows-1252').decode(b); }
  }

  // SRT and WebVTT: returns [{start, end, raw}] in file order.
  function parseSubtitles(text) {
    const lines = String(text).replace(/^﻿/, '').replace(/\r\n?/g, '\n').split('\n');
    const cues = [];
    let i = 0;
    while (i < lines.length) {
      const m = TIME_RE.exec(lines[i]);
      if (!m) { i++; continue; }
      const start = toMs(m[1], m[2], m[3], m[4]), end = toMs(m[5], m[6], m[7], m[8]);
      i++;
      const body = [];
      while (i < lines.length && lines[i].trim() !== '' && !TIME_RE.test(lines[i])) body.push(lines[i++]);
      if (body.length && /^\d+$/.test(body[body.length - 1].trim()) && i < lines.length && TIME_RE.test(lines[i])) body.pop();
      cues.push({ start, end: Math.max(end, start), raw: body.join('\n').trim() });
    }
    return cues;
  }

  // Strips styling cruft, pulls out a position tag and whole-subtitle italics.
  function normalizeCue(raw) {
    let t = String(raw);
    t = t.replace(/<v(?:\.[^\s>]*)?\s+[^>]*>/gi, '').replace(/<\/v>/gi, '').replace(/<\/?c(?:\.[^>]*)?>/gi, '').replace(/<\/?(?:ruby|rt|lang|span)[^>]*>/gi, '');
    t = t.replace(/<\d{1,2}:\d{2}(?::\d{2})?[.,]\d{3}>/g, '');
    t = t.replace(/<\/?font[^>]*>/gi, '');
    t = t.replace(/<(\/?)([ibu])\s*>/gi, (m, s, n) => `<${s}${n.toLowerCase()}>`);
    let pos = '';
    t = t.replace(/\{\\an?\d+\}/g, (m) => { if (!pos) pos = m; return ''; });
    t = t.replace(/\{\\[^}]*\}/g, '');
    t = t.replace(/&amp;/g, '&').replace(/&nbsp;/g, ' ').replace(/&quot;/g, '"').replace(/&#39;/g, "'");
    t = t.split('\n').map(l => l.replace(/[ \t ]+/g, ' ').trim()).filter(Boolean).join('\n');
    let ital = false;
    const m = /^<i>([\s\S]*)<\/i>$/.exec(t);
    if (m && !/<\/?i>/.test(m[1])) { ital = true; t = m[1].trim(); }
    else {
      const ls = t.split('\n');
      if (ls.length > 1 && ls.every(l => /^<i>[^<]*<\/i>$/.test(l))) { ital = true; t = ls.map(l => l.slice(3, -4)).join('\n'); }
    }
    return { pos, ital, text: t };
  }

  // Removes [sound], (sound) and ALL-CAPS speaker labels used in subtitles for the deaf and hard of hearing.
  function cleanSDH(text) {
    let t = String(text).replace(/\[[^\]]*\]/g, ' ').replace(/\([^)]*\)/g, ' ');
    t = t.split('\n').map(line => line.replace(
      /^((?:\s*<[^>]+>)*\s*(?:[-–—]\s*)?(?:<[^>]+>\s*)*)([A-ZÅÄÖÉ][A-ZÅÄÖÉ0-9 .'’#&-]*[A-ZÅÄÖÉ0-9.#])\s*:(?=\s|$)\s*/,
      (m, pre, name) => (/[A-ZÅÄÖÉ]{2}/.test(name) ? pre : m))).join('\n');
    let lines = t.split('\n').map(l => l.replace(/<([ibu])>\s*<\/\1>/g, '').replace(/[ \t]{2,}/g, ' ').trim().replace(/^((?:<[^>]+>)+)\s+/, '$1').replace(/\s+((?:<\/[^>]+>)+)$/, '$1'));
    lines = lines.filter(l => /[\p{L}\p{N}]/u.test(stripTags(l)));
    lines = lines.map(l => l.replace(/^((?:<[^>]+>)*)\s*([-–—])\s*[,.;:]\s*/, '$1$2 ').replace(/^((?:<[^>]+>)*)\s*[,.;:]\s+/, '$1'));
    if (lines.length === 1) lines[0] = lines[0].replace(/^((?:<[^>]+>)*)\s*[-–—]\s*/, '$1');
    return lines.join('\n').trim();
  }

  // Removes hesitations, stutters and filler phrases before the English goes to Google.
  function preClean(text) {
    const src = String(text).trim();
    const upper = /^[^\p{L}]*\p{Lu}/u.test(src);
    let t = src, prev = null;
    const lead = s => s.replace(/^\s*(?:(?:\.\.\.|…|[,;:])\s*)+/, '');
    for (let k = 0; k < 8 && t !== prev; k++) {
      prev = t;
      t = t.replace(/\b([a-z]{1,3})-(?=\1)/gi, '');
      t = lead(t.replace(/(^|[\s,.!?…-])(?:u+h+|u+m+|e+r+m*|h+m+)(?=$|[\s,.!?…])[,.…]*/gi, '$1'));
      t = t.replace(/,\s*you know\?\s*$/i, '.');
      t = t.replace(/(^|[.!?…]\s+|,\s*)you know(?:\s*,\s*|\s*(?=[.?!…])|\s*$)/gi, '$1');
      t = lead(t.replace(/(^|[.!?…]\s+)(?:well|so|okay so|I mean)(?:,|\.\.\.|…)\s*/gi, '$1'));
      t = t.replace(/,\s*(?:like|I mean),\s*/gi, ' ');
      t = t.replace(/\s+([,.!?…])/g, '$1').replace(/,\s*,/g, ',').replace(/,(?=[.!?…])/g, '').replace(/\s{2,}/g, ' ').trim();
    }
    if (!/[\p{L}\p{N}]/u.test(t)) return '';
    if (upper) t = t.replace(/^([^\p{L}]*)(\p{Ll})/u, (m, a, b) => a + b.toUpperCase());
    return t;
  }

  function endsSentence(t) { return /[.!?♪]["'”)\]]*$/.test(stripTags(t).trim()) && !/(\.\.\.|…)$/.test(stripTags(t).trim()); }
  const EN_OPEN = /\b(and|but|or|so|because|if|when|while|that|which|who|whom|whose|where|to|the|a|an|of|for|with|in|on|at|from|by|about|into|my|your|his|her|its|our|their|is|are|was|were|be|been|being|have|has|had|will|would|can|could|should|must|might|not|than|as|just|even|very)$/i;
  // Does a subtitle's last sentence continue in the next subtitle?
  function continues(a, b, gap) {
    if (gap > 2500) return false;
    const x = stripTags(a).trim(), y = stripTags(b).trim();
    if (!x || !y) return false;
    const yLower = /^(?:\.\.\.|…)?\s*[\p{Ll}]/u.test(y), yEll = /^(?:\.\.\.|…)/.test(y);
    if (/(\.\.\.|…)$/.test(x)) return yEll || yLower;
    if (/[.!?♪]["'”)\]]*$/.test(x)) return false;
    return yLower || yEll || /[,;:–—-]$/.test(x) || EN_OPEN.test(x);
  }

  // Splits subtitles into translation units: whole sentences, possibly running over several subtitles.
  // Each part knows which subtitle (n) and which speaker line (k) it came from.
  function buildUnits(cues, opts) {
    const units = [];
    let cur = null, last = null;
    for (const c of cues) {
      if (c.removed || !c.en) { cur = null; continue; }
      const dlg = isDialogue(c.en);
      const lines = dlg ? c.en.split('\n').map(l => l.replace(/^((?:<[^>]+>)*)\s*[-–—]\s*/, '$1')) : [c.en.split('\n').join(' ')];
      lines.forEach((raw, k) => {
        const text = stripTags(raw).replace(/\s+/g, ' ').trim();
        const clean = opts.fillers ? preClean(text) : text;
        const part = { n: c.n, k, en: text, clean };
        if (cur && k === 0 && !dlg && last && continues(last.en, text, c.start - last.end) && cur.parts.length < 4) cur.parts.push(part);
        else { cur = { parts: [part] }; units.push(cur); }
        if (dlg || endsSentence(text)) cur = null;
      });
      last = { en: dlg ? '' : stripTags(c.en).replace(/\s+/g, ' ').trim(), end: c.end };
    }
    for (const u of units) {
      const live = u.parts.filter(p => p.clean);
      u.text = live.map((p, i) => {
        let t = p.clean;
        if (i < live.length - 1) t = t.replace(/\s*(?:\.\.\.|…)$/, '');
        if (i > 0) t = t.replace(/^(?:\.\.\.|…)\s*/, '');
        return t;
      }).join(' ').replace(/\s{2,}/g, ' ').trim();
    }
    return units;
  }

  const SV_NOEND = new Set('en ett den det de dom the min din sin vår er mitt ditt sitt mina dina sina våra era hans hennes deras i på till från med av för om under över efter mot vid hos utan genom inom bland åt ur kring att och men eller som så när har hade är var ska skulle kan kunde vill ville måste får fick inte mr mrs ms miss dr herr fru'.split(' '));
  const SV_START = new Set('och men eller så att som när om eftersom därför medan innan tills fast trots utan då där vilket vilken vad hur varför vem vart'.split(' '));
  const SV_NUMWORD = new Set('två tre fyra fem sex sju åtta nio tio elva tolv tjugo trettio fyrtio femtio sextio sjuttio åttio nittio hundra tusen'.split(' '));
  const lowWord = w => stripTags(w).toLowerCase().replace(/[^\p{L}]/gu, '');
  // A number should stay on the same line as what it counts ("åtta mil", "två miljarder").
  const isNumberWord = w => /^\d[\d\s.,]*$/.test(stripTags(w)) || SV_NUMWORD.has(lowWord(w));

  // Divides one translated sentence over the subtitles it came from, in proportion to the English,
  // preferring breaks after punctuation and before conjunctions.
  function splitForParts(sv, weights) {
    const k = weights.length;
    const words = String(sv).trim().split(/\s+/).filter(Boolean);
    if (k <= 1) return [words.join(' ')];
    if (words.length <= k) { const out = words.slice(); while (out.length < k) out.push(''); return out; }
    const pos = [0];
    for (let j = 0; j < words.length; j++) pos.push(pos[j] + visLen(words[j]) + (j ? 1 : 0));
    const total = pos[words.length], W = weights.reduce((a, b) => a + b, 0) || k;
    const targets = [];
    let acc = 0;
    for (let i = 0; i < k - 1; i++) { acc += weights[i] || 1; targets.push(total * acc / W); }
    const gap = j => {
      const prev = stripTags(words[j - 1]);
      let c = 0;
      if (/[.!?…]["'”)]*$/.test(prev)) c -= 16;
      else if (/[,;:]$/.test(prev) || /^[–—-]$/.test(prev)) c -= 10;
      if (SV_START.has(lowWord(words[j]))) c -= 6;
      if (SV_NOEND.has(lowWord(words[j - 1]))) c += 14;
      if (isNumberWord(words[j - 1]) && !/[,.!?]$/.test(prev)) c += 14;
      return c;
    };
    const n = words.length, INF = 1e9;
    const f = Array.from({ length: k - 1 }, () => new Array(n + 1).fill(INF));
    const from = Array.from({ length: k - 1 }, () => new Array(n + 1).fill(-1));
    for (let j = 1; j <= n - (k - 1); j++) f[0][j] = Math.abs(pos[j] - targets[0]) + gap(j);
    for (let i = 1; i < k - 1; i++) {
      for (let j = i + 1; j <= n - (k - 1 - i); j++) {
        const base = Math.abs(pos[j] - targets[i]) + gap(j);
        for (let p = i; p < j; p++) if (f[i - 1][p] + base < f[i][j]) { f[i][j] = f[i - 1][p] + base; from[i][j] = p; }
      }
    }
    let bj = -1, best = INF;
    for (let j = k - 1; j <= n - 1; j++) if (f[k - 2][j] < best) { best = f[k - 2][j]; bj = j; }
    const cuts = [bj];
    for (let i = k - 2; i > 0; i--) cuts.unshift(from[i][cuts[0]]);
    const out = [];
    let s = 0;
    for (const c of [...cuts, n]) { out.push(words.slice(s, c).join(' ')); s = c; }
    return out.map((t, i) => (i < k - 1 ? t.replace(/\s*[–—-]$/, '') : t).replace(/^[–—-]\s+/, '').trim());
  }

  // Standard Swedish subtitle wording for very common short lines.
  // [English variants, Swedish, kind]: kind '?' questions, '!' exclamations, '.' statements and exclamations, '' any.
  const PHRASEBOOK = [
    ["i'm sorry|i am sorry|sorry|so sorry", 'Förlåt', '.'],
    ['sorry|pardon|pardon me|excuse me', 'Ursäkta', '?'],
    ['excuse me', 'Ursäkta', '.'],
    ['thank you|thanks', 'Tack', ''],
    ['thank you so much|thank you very much|thanks a lot|thanks so much', 'Tack så mycket', ''],
    ["you're welcome", 'Ingen orsak', '.'],
    ['no problem', 'Inga problem', '.'],
    ['come on', 'Kom igen', '.'],
    ["let's go", 'Nu går vi', '.'],
    ["let's get out of here", 'Vi sticker härifrån', '.'],
    ['oh, my god|oh my god|my god|oh god|oh, god|oh, my gosh|oh my gosh|jesus|oh, jesus|jesus christ|oh, jesus christ', 'Herregud', '.'],
    ['thank god', 'Gudskelov', '.'],
    ['what the hell', 'Vad fan', ''],
    ['what the fuck', 'Vad i helvete', ''],
    ['damn it|dammit|goddamn it|goddammit', 'Fan också', '.'],
    ['shit|oh, shit|oh shit|fuck|oh, fuck|oh fuck|damn', 'Fan', '.'],
    ['holy shit', 'Fy fan', '.'],
    ["i don't know", 'Jag vet inte', '.'],
    ['i know', 'Jag vet', '.'],
    ['i see', 'Jag förstår', '.'],
    ["i'm fine", 'Jag mår bra', '.'],
    ['okay|ok|all right|alright', 'Okej', ''],
    ['yeah|yes', 'Ja', ''],
    ['yep|yup', 'Japp', '.'],
    ['no|nope', 'Nej', ''],
    ['hey', 'Hallå', '!'],
    ['hey|hi|hello', 'Hej', '.'],
    ['hello', 'Hallå', '?'],
    ['bye|goodbye|bye-bye|bye bye', 'Hej då', '.'],
    ["good night|goodnight|night|'night", 'God natt', '.'],
    ['good morning|morning', 'God morgon', '.'],
    ['good luck|break a leg', 'Lycka till', '.'],
    ['bless you', 'Prosit', '.'],
    ['here you go|here you are|there you go', 'Varsågod', '.'],
    ['hold on|hang on|wait a minute|wait a second|just a minute|just a second', 'Vänta lite', '.'],
    ['wait', 'Vänta', '.'],
    ['never mind', 'Strunt samma', '.'],
    ['forget it', 'Glöm det', '.'],
    ['calm down', 'Lugna dig', '.'],
    ['take care', 'Sköt om dig', '.'],
    ['be careful', 'Var försiktig', '.'],
    ["don't worry", 'Oroa dig inte', '.'],
    ['trust me', 'Lita på mig', '.'],
    ['me too', 'Jag med', '.'],
    ['me neither', 'Inte jag heller', '.'],
    ['of course', 'Självklart', '.'],
    ['sure', 'Visst', '.'],
    ['exactly', 'Precis', '.'],
    ['good', 'Bra', '.'],
    ['great', 'Toppen', '.'],
    ['perfect', 'Perfekt', '.'],
    ['good job|well done|nice work|nice job', 'Bra jobbat', '.'],
    ['please', 'Snälla', '.'],
    ['help', 'Hjälp', '.'],
    ['stop it', 'Sluta', '.'],
    ['shh|shush|hush', 'Tyst', '.'],
    ['oops|whoops', 'Hoppsan', '.'],
    ['ouch|ow', 'Aj', '.'],
    ['uh-huh|mm-hmm|mhm|mm-hm', 'Mm', ''],
    ['i love you', 'Jag älskar dig', '.'],
    ['i love you too', 'Jag älskar dig också', '.'],
    ['i miss you', 'Jag saknar dig', '.'],
    ['see you|see you later|see ya|see you around', 'Vi ses', '.'],
    ['see you tomorrow', 'Vi ses i morgon', '.'],
    ['happy birthday', 'Grattis på födelsedagen', '.'],
    ['congratulations|congrats', 'Grattis', '.'],
    ['merry christmas', 'God jul', '.'],
    ['happy new year', 'Gott nytt år', '.'],
    ["let's call it a night|let's just call it a night", 'Nu räcker det för i kväll', '.'],
    ["let's call it a day|let's just call it a day", 'Nu räcker det för i dag', '.'],
    ["i'm coming|coming", 'Jag kommer', '.'],
    ['come here', 'Kom hit', '.'],
    ['come in', 'Kom in', '.'],
    ['sit down', 'Sätt dig', '.'],
    ['get out', 'Ut', '.'],
    ['leave me alone', 'Lämna mig i fred', '.'],
    ['let me go', 'Släpp mig', '.'],
    ['hurry up|hurry', 'Skynda dig', '.'],
    ['i promise', 'Jag lovar', '.'],
    ['i swear', 'Jag svär', '.'],
    ["it's okay|it's ok|it's all right", 'Det är lugnt', '.'],
    ['i have no idea|no idea', 'Ingen aning', '.'],
    ["i don't care", 'Jag bryr mig inte', '.'],
    ['whatever', 'Strunt samma', '.'],
    ['not now', 'Inte nu', ''],
    ['not yet', 'Inte än', ''],
    ['nothing', 'Ingenting', ''],
    ['what', 'Vad', '?'], ['why', 'Varför', '?'], ['who', 'Vem', '?'], ['where', 'Var', '?'], ['how', 'Hur', '?'], ['when', 'När', '?'],
    ['really', 'Verkligen', ''],
    ['seriously', 'Seriöst', ''],
    ['right', 'Eller hur', '?'],
    ['are you okay|are you ok|are you all right|you okay|you ok|you all right', 'Är du okej', '?'],
    ["what's going on", 'Vad händer', '?'],
    ["what's wrong", 'Vad är det', '?'],
    ['what happened', 'Vad hände', '?'],
    ['are you sure', 'Är du säker', '?'],
    ['what do you mean', 'Hur menar du', '?'],
    ['how are you', 'Hur mår du', '?'],
    ['how are you doing', 'Hur är det', '?'],
    ['you know what', 'Vet du vad', '?'],
    ['guess what', 'Gissa vad', '?'],
    ['mom', 'Mamma', ''], ['dad', 'Pappa', '']
  ];
  const PB = (() => {
    const m = new Map();
    for (const [en, sv, kind] of PHRASEBOOK) for (const v of en.split('|')) { const key = v + '|' + kind; if (!m.has(key)) m.set(key, sv); }
    return m;
  })();
  function phrasebook(text) {
    const t = stripTags(text).toLowerCase().replace(/[‘’]/g, "'").replace(/["“”]/g, '').replace(/\s+/g, ' ').trim();
    const mm = /^(.*?)\s*([.!?…]+|\.\.\.)?$/.exec(t);
    if (!mm || !mm[1]) return null;
    const base = mm[1].replace(/[,;:]$/, ''), p = mm[2] || '';
    const kind = p.includes('?') ? '?' : p.includes('!') ? '!' : (p === '…' || p === '...') ? '…' : '.';
    const order = kind === '?' ? ['?', ''] : kind === '!' ? ['!', '.', ''] : ['.', ''];
    for (const k of order) {
      const sv = PB.get(base + '|' + k);
      if (sv) return sv + (kind === '?' ? '?' : kind === '!' ? '!' : kind === '…' ? '…' : '.');
    }
    return null;
  }

  const EN_NUM = { one: 1, two: 2, three: 3, four: 4, five: 5, six: 6, seven: 7, eight: 8, nine: 9, ten: 10, eleven: 11, twelve: 12, fifteen: 15, twenty: 20, thirty: 30, forty: 40, fifty: 50, sixty: 60, seventy: 70, eighty: 80, ninety: 90, hundred: 100, 'a hundred': 100 };
  const SV_NUMW = { en: 1, ett: 1, 'två': 2, tre: 3, fyra: 4, fem: 5, sex: 6, sju: 7, 'åtta': 8, nio: 9, tio: 10, elva: 11, tolv: 12, femton: 15, tjugo: 20, trettio: 30, fyrtio: 40, femtio: 50, sextio: 60, sjuttio: 70, 'åttio': 80, nittio: 90, hundra: 100 };
  const SV_DIGIT = { 2: 'två', 3: 'tre', 4: 'fyra', 5: 'fem', 6: 'sex', 7: 'sju', 8: 'åtta', 9: 'nio', 10: 'tio' };
  function km(x) { return x < 10 ? `${(Math.round(x * 10) / 10).toString().replace('.', ',')} km` : `${Math.round(x)} km`; }

  // Fixes typical machine-translation slips in Swedish subtitles. `notes` collects what changed.
  function postFix(sv, en, notes) {
    let t = String(sv ?? '').trim();
    const src = String(en ?? '');
    const fix = (re, rep, note) => { const t2 = t.replace(re, rep); if (t2 !== t) { t = t2; if (note && !notes.includes(note)) notes.push(note); } };
    const cap = (m, word) => (m[0] === m[0].toUpperCase() ? word[0].toUpperCase() + word.slice(1) : word);
    // Swedish fillers that slipped through
    fix(/^(?:Äh|Öh|Eh|Hm+|Ehm)[,.…]?\s+(\p{L})/u, (m, l) => l.toUpperCase(), 'Filler removed');
    fix(/,\s*(?:typ|liksom|du vet),\s*/g, ' ', 'Filler removed');
    // An apology is "Förlåt"
    if (/\b(?:i'?m|i am)\s+(?:so\s+|really\s+|very\s+|truly\s+)?sorry\b(?!\s*(?:for|about|to|that|if|but)\b)/i.test(src)) fix(/\b[Jj]ag är (?:så |verkligen |väldigt )?ledsen\b(?!\s+för)/u, m => cap(m, 'förlåt'), '"I\'m sorry" as an apology is "Förlåt"');
    // False friends
    if (/\beventually\b/i.test(src)) fix(/\b[Ee]ventuellt\b/u, m => cap(m, 'till slut'), '"Eventually" is "till slut"');
    if (/\bactually\b/i.test(src)) fix(/\b[Aa]ktuellt\b/u, m => cap(m, 'faktiskt'), '"Actually" is "faktiskt"');
    if (/\bbillions?\b/i.test(src) && !/\btrillions?\b/i.test(src)) fix(/\b([Bb])iljon(er|en|erna)?\b/gu, (m, b, s) => (b === 'B' ? 'M' : 'm') + 'iljard' + (s || ''), 'A billion is a "miljard"');
    if (/\bguys\b/i.test(src) && !/\b(?:those|these|the|two|three|some|other|bad|good|nice|tough)\s+guys\b/i.test(src)) fix(/\bkillar\b/u, 'allihop', '"Guys" to a group is "allihop"');
    if (/\b(?:oh,?\s+)?my god\b/i.test(src)) fix(/(?<![\p{L}])(?:[ÅåOo]h?,?\s+)?[Mm]in [Gg]ud(?![\p{L}])/u, m => cap(m, 'herregud'), '"Oh my God" is "Herregud"');
    // Miles, feet and mph to metric, when Google kept the English unit or the same number
    fix(/(\d+(?:[.,]\d+)?)\s*(?:engelska\s+mil|miles?)\b/giu, (m, n) => km(parseFloat(n.replace(',', '.')) * 1.609), 'Miles converted to km');
    const mileNums = [...src.matchAll(/\b(\d+(?:[.,]\d+)?|[a-z]+(?:-[a-z]+)?)\s+miles?\b/gi)].map(m => {
      const w = m[1].toLowerCase();
      if (/^\d/.test(w)) return parseFloat(w.replace(',', '.'));
      const [a, b] = w.split('-');
      return EN_NUM[a] != null ? EN_NUM[a] + (b && EN_NUM[b] ? EN_NUM[b] : 0) : NaN;
    }).filter(x => !Number.isNaN(x));
    if (mileNums.length) {
      fix(/(?<![\p{L}\d])(\d+(?:[.,]\d+)?|\p{L}+)\s+mil(?![\p{L}])/gu, (m, n) => {
        const v = /^\d/.test(n) ? parseFloat(n.replace(',', '.')) : SV_NUMW[n.toLowerCase()];
        return v != null && mileNums.includes(v) ? km(v * 1.609) : m;
      }, 'Miles converted to km');
      fix(/(?<![\p{L}\d])(\d+(?:[.,]\d+)?)\s*km(?![\p{L}])/gu, (m, n) => {
        const v = parseFloat(n.replace(',', '.'));
        return mileNums.includes(v) ? km(v * 1.609) : m;
      }, 'Miles converted to km');
    }
    fix(/(\d+(?:[.,]\d+)?)\s*(?:fot|feet)\b/giu, (m, n) => `${Math.round(parseFloat(n.replace(',', '.')) * 0.3048 * 10) / 10} meter`.replace('.', ','), 'Feet converted to metres');
    fix(/(\d+)\s*(?:mph|miles i timmen|engelska mil i timmen)\b/giu, (m, n) => `${Math.round(n * 1.609)} km/h`, 'mph converted to km/h');
    // Money, titles, clock times
    fix(/\$\s?(\d[\d\s.,]*\d|\d)(\s+(?:miljoner|miljarder|tusen))?/g, (m, n, mult) => `${n.trim()}${mult || ''} dollar`);
    fix(/\b(Mr|Mrs|Ms|Dr)\.?(?=\s+\p{Lu})/gu, (m, x, off, all) => (/(?:^|[.!?]\s+|["'(]\s*)$/.test(all.slice(0, off)) ? x : x.toLowerCase()));
    fix(/\b(\d{1,2}):(\d{2})\b/g, '$1.$2');
    // Numbers two to ten in words (Netflix Swedish style), except times, decimals, dates, units and labels
    fix(/(^|[^\d.,:–/-])(?<!(?:kl\.|klockan|nummer|nr\.?|rum|sida|kapitel|avsnitt|säsong|plats|kanal|buss|linje|spår|våning|bord)\s)\b([2-9]|10)\b(?![.,:/–-]?\d|\s\d{3}\b|\s*(?:%|procent|°|kr\b|km|kg|cm|mm|m\b|januari|februari|mars|april|maj|juni|juli|augusti|september|oktober|november|december))/giu,
      (m, pre, d, off, all) => pre + ((off + pre.length === 0 || /[.!?]\s*$/.test(all.slice(0, off + pre.length))) ? SV_DIGIT[d][0].toUpperCase() + SV_DIGIT[d].slice(1) : SV_DIGIT[d]));
    return t.replace(/\s{2,}/g, ' ').trim();
  }

  // Rebreaks lines: keeps a good two-line break, otherwise finds the best one (bottom-heavy, at phrase boundaries).
  function rebreak(text, maxLen) {
    const lines = String(text).split('\n');
    if (isDialogue(text)) return text;
    if (lines.length <= 2 && lines.every(l => visLen(l) <= maxLen)) return text;
    const flat = lines.join(' ').replace(/\s+/g, ' ').trim();
    if (visLen(flat) <= maxLen) return flat;
    const words = flat.split(' ');
    let best = null;
    for (let i = 1; i < words.length; i++) {
      const a = words.slice(0, i).join(' '), b = words.slice(i).join(' ');
      const la = visLen(a), lb = visLen(b), prevRaw = stripTags(words[i - 1]);
      let cost = (Math.max(0, la - maxLen) + Math.max(0, lb - maxLen)) * 100 + Math.abs(la - lb);
      if (la > lb) cost += (la - lb) * 0.6;
      if (/[.!?…]["'”]?$/.test(prevRaw)) cost -= 30;
      else if (/[,;:]$/.test(prevRaw)) cost -= 18;
      if (SV_START.has(lowWord(words[i]))) cost -= 10;
      if (SV_NOEND.has(lowWord(words[i - 1]))) cost += 25;
      if (isNumberWord(words[i - 1]) && !/[,.!?]$/.test(prevRaw)) cost += 20;
      if (i <= 2) cost += 14;
      if (i === words.length - 1) cost += 14;
      if (!best || cost < best.cost) best = { cost, a, b };
    }
    return best ? best.a + '\n' + best.b : flat;
  }

  // House style for one subtitle's Swedish text.
  function polish(sv, o) {
    let t = String(sv ?? '').replace(/\r\n?/g, '\n');
    t = t.replace(/\.{3}/g, '…').replace(/[“”„]/g, '"').replace(/[ \t ]{2,}/g, ' ');
    t = t.split('\n').map(l => l.trim()).filter(l => stripTags(l).trim()).join('\n');
    if (isDialogue(t)) {
      const d = o.dash === 'space' ? '- ' : '-';
      t = t.split('\n').map(l => isDlgLine(l) ? l.replace(/^((?:\s*<[^>]+>)*)\s*[-–—]\s*/, (m, tags) => tags + d) : l).join('\n');
    }
    return rebreak(t, o.maxLen);
  }

  function nums(s) {
    return (stripTags(s).replace(/\b\d{1,2}[:.]\d{2}\b/g, ' ').replace(/(\d)[,\s ](?=\d{3}\b)/g, '$1').match(/\d+(?:[.,]\d+)?/g) || []).map(x => x.replace(',', '.'));
  }
  function missingNumbers(en, sv) {
    const have = new Set(nums(sv));
    return [...new Set(nums(en))].filter(x => parseFloat(x) > 10 && !have.has(x));
  }
  const EN_HINT = new Set(['the', 'you', 'your', 'and', 'is', 'are', 'was', 'what', 'this', 'that', 'with', 'have', "don't", "i'm", "it's", 'of', 'to', 'not', 'we', 'they', 'he', 'she', 'will', 'would', 'can', 'just', 'my', 'me', 'it']);
  function looksEnglish(sv, en) {
    const a = stripTags(sv).toLowerCase().replace(/\s+/g, ' ').trim();
    const b = stripTags(en).toLowerCase().replace(/\s+/g, ' ').trim();
    const words = a.match(/[\p{L}']+/gu) || [];
    if (words.length >= 3 && a === b) return true;
    if (words.length < 4) return false;
    const hits = words.filter(w => EN_HINT.has(w)).length;
    return hits >= 2 && hits / words.length >= 0.3;
  }

  // Reading speed, line lengths, display-time extension and issues for one subtitle.
  function computeQA(c, next, o) {
    const q = { level: 'ok', cps: 0, chars: 0, lens: [], end: c.end, ext: 0, issues: [] };
    if (c.removed) { q.level = 'off'; return q; }
    if (c.sv == null) {
      if (c.err) { q.level = 'bad'; q.issues.push({ lv: 'bad', code: 'missing', msg: 'Not translated. Google returned nothing for it.' }); }
      else q.level = 'todo';
      return q;
    }
    const lines = c.sv ? c.sv.split('\n') : [];
    q.lens = lines.map(visLen);
    q.chars = q.lens.reduce((a, b) => a + b, 0);
    if (!q.chars) return q;
    const dur = Math.max(1, c.end - c.start);
    if (o.extend) {
      const need = q.chars / o.cps * 1000;
      if (need > dur) {
        const cap = Math.min(c.end + 1000, c.start + 7000, next ? next.start - 84 : Infinity);
        const e = Math.min(c.start + need, cap);
        if (e > c.end) { q.end = Math.round(e); q.ext = q.end - c.end; }
      }
    }
    q.cps = q.chars / ((q.end - c.start) / 1000);
    if (lines.length > 2) q.issues.push({ lv: 'bad', code: 'lines', msg: `${lines.length} lines. The limit is 2.` });
    const long = Math.max(...q.lens);
    if (long > o.maxLen) q.issues.push({ lv: 'bad', code: 'len', msg: `A line has ${long} characters. The limit is ${o.maxLen}.` });
    if (q.cps > o.cps + 3) q.issues.push({ lv: 'bad', code: 'cps', msg: `Too fast to read: ${q.cps.toFixed(1)} characters per second (limit ${o.cps}). Shorten it.` });
    else if (q.cps > o.cps + 0.05) q.issues.push({ lv: 'warn', code: 'cps', msg: `A little fast: ${q.cps.toFixed(1)} characters per second (limit ${o.cps}).` });
    if ((c.sv.match(/<i>/g) || []).length !== (c.sv.match(/<\/i>/g) || []).length) q.issues.push({ lv: 'bad', code: 'tags', msg: 'An italics tag is not closed.' });
    if (looksEnglish(c.sv, c.en)) q.issues.push({ lv: 'bad', code: 'english', msg: 'Looks untranslated.' });
    const miss = missingNumbers(c.en, c.sv);
    if (miss.length) q.issues.push({ lv: 'warn', code: 'num', msg: `Check the number ${miss.join(', ')}.` });
    const times = (stripTags(c.en).match(/\b\d{1,2}:\d{2}\b/g) || []).filter(tm => !timeKept(c.sv, +tm.split(':')[0], +tm.split(':')[1]));
    if (times.length) q.issues.push({ lv: 'warn', code: 'time', msg: `Check the time ${times.join(', ')}.` });
    q.level = q.issues.some(x => x.lv === 'bad') ? 'bad' : q.issues.length ? 'warn' : 'ok';
    return q;
  }
  function nextActiveIn(cues, n) {
    for (let k = n; k < cues.length; k++) if (!cues[k].removed && (cues[k].en || cues[k].sv)) return cues[k];
    return null;
  }

  function buildSRT(cues, qa, o) {
    const blocks = [];
    let k = 0;
    for (const c of cues) {
      if (c.removed) continue;
      let t = c.sv != null ? c.sv : c.en;
      if (!stripTags(t || '').trim()) continue;
      if (o.encoding === 'cp1252') t = t.replace(/[♪♫]/g, '#');
      if (c.ital) t = `<i>${t}</i>`;
      if (c.pos) t = c.pos + t;
      const end = (o.extend && qa && qa[c.n - 1] && qa[c.n - 1].end) || c.end;
      blocks.push(`${++k}\n${fmtSrtTime(c.start)} --> ${fmtSrtTime(end)}\n${t}`);
    }
    return blocks.join('\n\n') + '\n';
  }

  const CP1252 = { 0x20AC: 0x80, 0x201A: 0x82, 0x0192: 0x83, 0x201E: 0x84, 0x2026: 0x85, 0x2020: 0x86, 0x2021: 0x87, 0x02C6: 0x88, 0x2030: 0x89, 0x0160: 0x8A, 0x2039: 0x8B, 0x0152: 0x8C, 0x017D: 0x8E, 0x2018: 0x91, 0x2019: 0x92, 0x201C: 0x93, 0x201D: 0x94, 0x2022: 0x95, 0x2013: 0x96, 0x2014: 0x97, 0x02DC: 0x98, 0x2122: 0x99, 0x0161: 0x9A, 0x203A: 0x9B, 0x0153: 0x9C, 0x017E: 0x9E, 0x0178: 0x9F };
  function encodeText(str, enc) {
    if (enc === 'cp1252') {
      const out = new Uint8Array(str.length);
      let n = 0, bad = 0;
      for (const ch of str) {
        const cp = ch.codePointAt(0);
        let b;
        if (cp < 0x80 || (cp >= 0xA0 && cp <= 0xFF)) b = cp;
        else if (CP1252[cp] != null) b = CP1252[cp];
        else { b = 0x3F; bad++; }
        out[n++] = b;
      }
      return { bytes: out.slice(0, n), bad };
    }
    const u = new TextEncoder().encode(str);
    if (enc === 'utf8bom') { const o = new Uint8Array(u.length + 3); o.set([0xEF, 0xBB, 0xBF]); o.set(u, 3); return { bytes: o, bad: 0 }; }
    return { bytes: u, bad: 0 };
  }

  function splitSentences(text) {
    return String(text).split(/(?<!\b(?:Mr|Mrs|Ms|Dr|St|Jr|Sr|Prof|Mt|vs|etc|Lt|Sgt|Capt|Gen|Col)\.)(?<=[.!?…]["')\]]*)\s+(?=["'(\[]?[\p{Lu}\d])/u).map(s => s.trim()).filter(Boolean);
  }
  // Words written with a capital in the middle of a sentence somewhere in the file: almost always names.
  const NOT_NAMES = new Set(['I', "I'm", "I'll", "I've", "I'd", 'OK', 'TV', 'Mom', 'Mum', 'Dad', 'Mommy', 'Daddy', 'Grandma', 'Grandpa', 'Sis', 'Bro', 'God', 'Jesus', 'Christ', 'Sir', 'Ma’am', "Ma'am", 'Honey', 'Sweetie', 'Baby']);
  function collectNames(cues) {
    const names = new Set(['Mr', 'Mrs', 'Ms', 'Dr']);
    for (const c of cues) {
      if (c.removed || !c.en) continue;
      for (const s of stripTags(c.en).split('\n').flatMap(l => splitSentences(l.replace(/^\s*[-–—]\s*/, '')))) {
        s.split(/\s+/).forEach((w, i) => {
          const m = /^[("']*(\p{Lu}[\p{L}-]*?)(?:'s|’s)?[,.!?;:…")]*$/u.exec(w);
          if (m && i > 0 && !NOT_NAMES.has(m[1])) names.add(m[1]);
        });
      }
    }
    return names;
  }
  // "Will!" or "Dr. Patel?" on its own: nothing to translate, and a small model tends to invent a reply.
  function isNamesOnly(s, names) {
    const words = s.replace(/[.,!?;:…"]/g, ' ').split(/\s+/).filter(Boolean);
    return words.length > 0 && words.length <= 3 && words.every(w => names.has(w.replace(/(?:'s|’s)$/, '')));
  }
  const SV_HOUR = ['tolv', 'ett', 'två', 'tre', 'fyra', 'fem', 'sex', 'sju', 'åtta', 'nio', 'tio', 'elva', 'tolv'];
  // Is the English clock time (h:mm) still there in the Swedish, as digits or as spoken Swedish ("halv fyra")?
  function timeKept(sv, h, mm) {
    const t = stripTags(sv).toLowerCase(), m2 = String(mm).padStart(2, '0');
    const hours = [h, h % 12, (h % 12) + 12].filter(x => x <= 24);
    if (hours.some(x => new RegExp(`(?<!\\d)0?${x}[.:]${m2}(?!\\d)`).test(t))) return true;
    const w = SV_HOUR[h % 12], next = SV_HOUR[(h % 12) + 1];
    const spoken = mm === 0 ? [`klockan ${w}`, `kl. ${w}`, ` ${w}`] : mm === 30 ? [`halv ${next}`] : mm === 15 ? [`kvart över ${w}`] : mm === 45 ? [`kvart i ${next}`] : [];
    return spoken.some(s => t.includes(s));
  }
  // Groups units into requests: up to a dozen sentences, joined by line breaks so Google sees the context.
  function chunkUnits(units, maxUnits, maxChars) {
    const out = [];
    let cur = [], len = 0;
    for (const u of units) {
      if (cur.length && (cur.length >= maxUnits || len + u.text.length + 1 > maxChars)) { out.push(cur); cur = []; len = 0; }
      cur.push(u); len += u.text.length + 1;
    }
    if (cur.length) out.push(cur);
    return out;
  }

  function outName(name) {
    let b = String(name || 'subtitles').replace(/\.(srt|vtt|txt)$/i, '');
    b = b.replace(/[._ -](sdh|hi|cc|forced)$/i, '').replace(/[._ -](en|eng|english|en-us|en-gb)$/i, '');
    return (b || 'subtitles') + '.sv.srt';
  }

  return {
    SAMPLE_SRT,
    SAMPLE_GOOGLE,
    fmtSrtTime,
    fmtClock,
    stripTags,
    visLen,
    wordCount,
    isDlgLine,
    isDialogue,
    decodeBytes,
    parseSubtitles,
    normalizeCue,
    cleanSDH,
    preClean,
    continues,
    buildUnits,
    splitForParts,
    PHRASEBOOK,
    phrasebook,
    postFix,
    rebreak,
    polish,
    missingNumbers,
    looksEnglish,
    computeQA,
    nextActiveIn,
    buildSRT,
    encodeText,
    splitSentences,
    collectNames,
    isNamesOnly,
    timeKept,
    chunkUnits,
    outName,
  };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = ST_CORE;
