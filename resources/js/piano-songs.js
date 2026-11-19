/* ==========================================================================
   PIANO - THE NOTES, THE SONGS AND THE LESSONS

   Everything piano.html teaches lives here, apart from the page, so it can
   be tested in Node (resources/tests/piano):

     pitch, fromMidi   a note: its letter, accidental, octave, MIDI number
                       and its step on the staff;
     nameOf            what the note is called - Swedish tradition says H for
                       the white key under C and B for the black one before
                       it, the rest of the world B and B flat;
     parse             a melody written as text (see THE NOTATION);
     SONGS             the melodies;
     UNITS             the path: units of lessons, in the order they open;
     buildLesson       the exercises of one lesson.

   THE NOTATION. A melody is tokens with spaces between them:

     C D E F G A B     a note in the octave from middle C (C4 to B4);
     C' D'  /  B, A,   an octave up for every ' and down for every ,
     F#  Bb            sharp and flat;
     R                 a rest;
     E2  E4  E3        how many beats it lasts (a quarter note is 1);
     E.  E-  E=        a dot makes it half as long again, - halves it (an
                       eighth), = quarters it (a sixteenth);
     |                 a bar line - checked by the tests, not needed;
     //                the end of a part: lessons teach a song part by part.

   THE MELODIES are old enough to belong to everybody. They were written
   here from memory and then checked note by note against published
   notation (the sources are listed with each song); no words are included,
   since several of the Swedish texts are still somebody's.
   ========================================================================== */

const PN_SONGS = (() => {
  'use strict';

  /* ── Notes ────────────────────────────────────────────────────────────── */

  const STEP = { C: 0, D: 1, E: 2, F: 3, G: 4, A: 5, B: 6 };
  const SEMI = [0, 2, 4, 5, 7, 9, 11];

  function makeNote(letter, acc, octave) {
    const k = STEP[letter];
    return { letter, acc, octave, midi: 12 * (octave + 1) + SEMI[k] + acc, step: 7 * octave + k };
  }

  /* 'C4', 'Bb4', 'F#5' */
  function pitch(s) {
    const m = /^([A-G])([#b]?)(-?\d)$/.exec(s);
    if (!m) throw new Error(`not a pitch: ${s}`);
    return makeNote(m[1], m[2] === '#' ? 1 : m[2] === 'b' ? -1 : 0, Number(m[3]));
  }

  /* The usual spelling of a key when nothing says otherwise. */
  const SPELL = [['C', 0], ['C', 1], ['D', 0], ['E', -1], ['E', 0], ['F', 0], ['F', 1], ['G', 0], ['G', 1], ['A', 0], ['B', -1], ['B', 0]];

  function fromMidi(midi) {
    const [letter, acc] = SPELL[((midi % 12) + 12) % 12];
    return makeNote(letter, acc, Math.floor((midi - SEMI[STEP[letter]] - acc) / 12) - 1);
  }

  /**
   * What a note is called. style 'h': the Swedish names (H; B is the black
   * key; Fiss, Ess). style 'b': B, and the signs for sharp and flat.
   */
  function nameOf(note, style) {
    if (style !== 'b') {
      if (note.letter === 'B') return note.acc === 0 ? 'H' : note.acc < 0 ? 'B' : 'Hiss';
      if (note.acc > 0) return `${note.letter}iss`;
      if (note.acc < 0) return note.letter === 'E' ? 'Ess' : note.letter === 'A' ? 'Ass' : `${note.letter}ess`;
      return note.letter;
    }
    return note.letter + (note.acc > 0 ? '♯' : note.acc < 0 ? '♭' : '');
  }

  /* The name as a lesson says it: "höga C" for the C above middle C. */
  function sayName(note, style) {
    const where = note.octave >= 5 ? 'höga ' : note.octave <= 3 ? 'låga ' : '';
    return where + nameOf(note, style);
  }

  /* {H}, {Bb} and {F#} in a lesson's text are the names in the chosen style. */
  function fillNames(text, style) {
    return text.replace(/\{([A-G][#b]?)\}/g, (all, p) => nameOf(pitch(`${p === 'H' ? 'B' : p}4`), style))
      .replace(/\{H\}/g, nameOf(pitch('B4'), style));
  }

  /* ── A melody as text ─────────────────────────────────────────────────── */

  const TOKEN = /^([A-GR])([#b]?)([',]*)(\d+(?:\.\d+)?)?([.\-=]*)$/;

  /**
   * The notes of a melody. opts.time is the beats in a bar (4 or 3),
   * opts.pickup the beats before the first whole bar.
   *
   * Returns { notes, total, problems, barMarks, parts }; a note is
   * { i, letter, acc, octave, midi, step, rest, beats, start, bar, beat,
   *   part } - start in beats from the first note, bar counted from 0 (the
   * pickup's bar is 0 when there is one), beat the place within its bar.
   */
  function parse(text, opts) {
    const o = opts || {};
    const per = o.time || 4;
    const pickup = o.pickup || 0;
    const notes = [];
    const problems = [];
    const barMarks = [];
    let pos = 0;
    let part = 0;
    for (const tok of String(text).trim().split(/\s+/)) {
      if (!tok) continue;
      if (tok === '|') { barMarks.push(pos); continue; }
      if (tok === '//') { if (notes.length) part++; continue; }
      const m = TOKEN.exec(tok);
      if (!m) { problems.push(tok); continue; }
      let beats = m[4] ? Number(m[4]) : 1;
      for (const c of m[5]) beats *= c === '.' ? 1.5 : c === '-' ? 0.5 : 0.25;
      if (!(beats > 0) || beats > 8) { problems.push(tok); continue; }
      const rest = m[1] === 'R';
      let octave = 4;
      for (const c of m[3]) octave += c === "'" ? 1 : -1;
      const base = rest ? { letter: 'R', acc: 0, octave: 0, midi: null, step: null }
        : makeNote(m[1], m[2] === '#' ? 1 : m[2] === 'b' ? -1 : 0, octave);
      const inPickup = pos < pickup;
      notes.push(Object.assign(base, {
        i: notes.length,
        rest,
        beats,
        start: pos,
        bar: inPickup ? 0 : Math.floor((pos - pickup) / per) + (pickup ? 1 : 0),
        beat: inPickup ? per - pickup + pos : (pos - pickup) % per,
        part,
      }));
      pos += beats;
    }
    return { notes, total: pos, problems, barMarks, parts: notes.length ? part + 1 : 0 };
  }

  /**
   * A token as somebody types it, made into the notation above: lower case,
   * H, Fiss and Ess, the signs for sharp and flat, a decimal comma. In the
   * Swedish style a bare B is the black key.
   */
  function userToken(tok, style) {
    if (tok === '|' || tok === '//') return tok;
    const m = /^([A-Ha-hRr])(iss|ess|ss|s|#|♯|b|♭)?([',’]*)(\d+(?:[.,]\d+)?)?([.\-=]*)$/.exec(tok);
    if (!m) return null;
    let letter = m[1].toUpperCase();
    let acc = !m[2] ? '' : /^(iss|#|♯)$/.test(m[2]) ? '#' : 'b';
    if (letter === 'R') return acc ? null : `R${(m[4] || '').replace(',', '.')}${m[5]}`;
    if (letter === 'H') letter = 'B';
    else if (letter === 'B' && !acc && style !== 'b') acc = 'b';
    return `${letter}${acc}${m[3].replace(/’/g, "'")}${(m[4] || '').replace(',', '.')}${m[5]}`;
  }

  /* A typed melody: the notation it becomes, and the tokens not understood. */
  function fromUser(text, style) {
    const out = [];
    const problems = [];
    for (const tok of String(text).trim().split(/\s+/)) {
      if (!tok) continue;
      const t = userToken(tok, style);
      if (t === null) problems.push(tok);
      else out.push(t);
    }
    return { text: out.join(' '), problems };
  }

  /* ── The songs ────────────────────────────────────────────────────────── */

  /*
     fingers: the key the thumb rests on when the whole song lies under five
     fingers. level: 1 to 3, shown as dots in the song list.
  */
  const SONGS = [
    {
      id: 'noak',
      title: 'Gubben Noak',
      by: 'Carl Michael Bellman, 1700-talet',
      time: 4, bpm: 96, level: 1, fingers: 'C4',
      text: `C C C E | D D D F | E E D D | C4 //
             E E E E | G2 F2 | D D D D | F2 E2 //
             C C C E | D D D F | E E D D | C4`,
    },
    {
      id: 'bjallerklang',
      title: 'Bjällerklang',
      by: 'James Pierpont, 1857',
      xmas: true,
      time: 4, bpm: 104, level: 1, fingers: 'C4',
      // Checked against "Jingle Bells refrain vector.mid", Wikimedia Commons.
      text: `E E E2 | E E E2 | E G C. D- | E4 //
             F F F. F- | F E E E- E- | E D D E | D2 G2 //
             E E E2 | E E E2 | E G C. D- | E4 //
             F F F. F- | F E E E- E- | G G F D | C4`,
    },
    {
      id: 'blinka',
      title: 'Blinka lilla stjärna',
      by: 'Fransk melodi, 1700-talet',
      time: 4, bpm: 96, level: 1,
      // Checked against the score in Wikipedia's "Twinkle, Twinkle, Little Star".
      text: `C C G G | A A G2 | F F E E | D D C2 //
             G G F F | E E D2 | G G F F | E E D2 //
             C C G G | A A G2 | F F E E | D D C2`,
    },
    {
      id: 'saliga',
      title: 'O du saliga',
      by: 'Siciliansk melodi, 1700-talet',
      xmas: true,
      time: 4, bpm: 92, level: 2,
      // Checked against the score in German Wikipedia's "O du fröhliche".
      text: `G2 A2 | G. F- E F | G2 A2 | G. F- E F //
             G2 G2 | A2 B C' | B2 A2 | G4 //
             D. E- D E | F. G- F2 | E. F- E F | G. A- G2 //
             C' B A G | C' A G F | E2 D2 | C4`,
    },
    {
      id: 'juleljus',
      title: 'Nu tändas tusen juleljus',
      by: 'Emmy Köhler, 1898',
      xmas: true,
      time: 4, pickup: 1, bpm: 92, level: 2,
      // Checked against "Nu tändas tusen juleljus.mid", Wikimedia Commons
      // (there in G major; here a tone lower, from C to C with one black key).
      text: `C | A A G G | F D C. C- | D D G E | C3 //
             C | C' C' Bb Bb | A F D. D- | E E G G | F3`,
    },
    {
      id: 'wewish',
      title: 'We Wish You a Merry Christmas',
      by: 'Engelsk julsång, 1500-talet',
      xmas: true,
      time: 3, pickup: 1, bpm: 108, level: 2,
      // The tune as every songbook has it; "We Wish You A Merry Christmas.mid"
      // on Wikimedia Commons agrees but for one note of its arrangement.
      text: `C | F F- G- F- E- | D D //
             D | G G- A- G- F- | E C //
             C | A A- Bb- A- G- | F D //
             C- C- | D G E | F2`,
    },
    {
      id: 'stilla',
      title: 'Stilla natt',
      by: 'Franz Gruber, 1818',
      xmas: true,
      time: 3, bpm: 84, level: 3,
      // Checked against the score in Wikipedia's "Silent Night" (written
      // there in 6/8; here every eighth note is a beat).
      text: `G. A- G | E3 | G. A- G | E3 //
             D'2 D' | B3 | C'2 C' | G3 //
             A2 A | C'. B- A | G. A- G | E3 //
             A2 A | C'. B- A | G. A- G | E3 //
             D'2 D' | F'. D'- B | C'3 | E'3 //
             C'. G- E | G. F- D | C3`,
    },
    {
      id: 'lucia',
      title: 'Sankta Lucia',
      by: 'Napolitansk melodi, 1800-talet',
      xmas: true,
      time: 3, bpm: 96, level: 3,
      // Checked against the score in Italian Wikipedia's "Santa Lucia" and
      // "Santa Lucia.mid", Wikimedia Commons (there in B flat major).
      text: `G G. C'- | C'- B- B2 | F F. A- | A G2 //
             E A. G- | G- F#- F2 | F E D | A G2 //
             E' D' C' | B- A- D'2 | D' C' A | F#- G- C'2 //
             E'- C'- C'- G- G- E- | F- D'- D'2 | D' A. B- | D' C'2`,
    },
    {
      id: 'raven',
      title: 'Räven raskar över isen',
      by: 'Svensk sånglek, 1600-talet',
      xmas: true,
      time: 3, bpm: 100, level: 2,
      // Checked against John Chambers' ABC "Räven raskar över isen"
      // (trillian.mit.edu, there in D and in A; here a tone lower, in C). Its
      // "får vi lov" leaps and the fall to the end are as two singers sing
      // them in Svenskt visarkiv's recordings of 1959 and 1960 (Wikimedia
      // Commons). The dotted pair it opens with is two even eighths here.
      text: `G- F- E- D- E- F- | A G R | G- F- E- D- E- F- | A G R //
             G- G- C'. G- | G- G- C'. G- | G- F- E F- D- | D C R- //
             G- | G- F- E E- E- | D- E- F. F- | F- E- D D- D- | C- D- E R //
             G- G- C'. G- | G- G- C'. G- | G- F- E F- D- | D C R`,
    },
    {
      id: 'tomtegubbar',
      title: 'Hej tomtegubbar',
      by: 'Svensk polska, tryckt 1815',
      xmas: true,
      time: 3, bpm: 100, level: 2,
      // Checked against two arrangements that agree on the tune: "Hej
      // tomtegubbar" for choir (cryner.se, the tune in the men's voices, in
      // B flat) and FolkWiki's "Hej tomtegubbar, spela polska", four fiddle
      // variations on it (in D); here in C. Both have its pairs dotted; here
      // they are even eighths.
      text: `C' G- A- G- F- | E- F- G C'- C'- | B- C'- D' C'- B- | C' C' R //
             C' G- A- G- F- | E- F- G C'- C'- | B- C'- D' C'- B- | C' C' R- //
             B- | C'- E'- D'. B- | C'- E'- D'. B- | C'- E'- D' D'- C'- | B- A- G R //
             C' G- A- G- F- | E- F- G C'- C'- | B- C'- D' C'- B- | C' C' R`,
    },
    {
      id: 'juligen',
      title: 'Nu är det jul igen',
      by: 'Dansk och svensk julsång',
      xmas: true,
      time: 3, bpm: 100, level: 3,
      // Checked against the score "Nu er det jul igen.png", Wikimedia Commons
      // (from Danish Wikisource, "Svensk/dansk folkemelodi"), in its own key,
      // F. John Chambers' ABC "Nå er det jul igjen" agrees but for one note
      // and the notes the Danish words split. Twice a line it dips to the A
      // below middle C, the one key here under it.
      text: `F- F- F- C- A,- C- | F- F- F- C- A,- C- | F- E- F- G- A- Bb- | C' C'2 //
             F- F- F- C- A,- C- | F- F- F- C- A,- C- | F- E- F- G- A- Bb- | C' C'2 //
             Bb- Bb- D'- Bb- Bb | A- A- C'- A- A- A- | G- A- Bb- G- F- E- | G F R //
             Bb- Bb- D'- Bb- Bb | A- A- C'- A- A- A- | G- A- Bb- G- F- E- | G F R`,
    },
  ];

  const parsed = new Map();

  function songById(id, own) {
    return SONGS.find(s => s.id === id) || (own || []).find(s => s.id === id) || null;
  }

  /* A song's notes, parsed once. */
  function songNotes(song) {
    if (!parsed.has(song.text)) parsed.set(song.text, new Map());
    const byShape = parsed.get(song.text);
    const key = `${song.time || 4}/${song.pickup || 0}`;
    if (!byShape.has(key)) byShape.set(key, parse(song.text, { time: song.time || 4, pickup: song.pickup || 0 }));
    return byShape.get(key);
  }

  /* The notes of some parts of a song, in order. */
  function partNotes(song, parts) {
    const all = songNotes(song).notes;
    return parts ? all.filter(n => parts.includes(n.part)) : all.slice();
  }

  /* ── The path ─────────────────────────────────────────────────────────── */

  /*
     stage says how much help a unit gives: 0 letters under the notes and the
     next key lit, 1 letters only, 2 the letters only the first time through.

     Lesson kinds:
       notes     new keys: fresh, beside the known ones (staff: also read)
       read      known keys, now read from the staff
       patterns  written-out exercises: [type, melody, options]
       phrase    parts of a song, a part at a time (whole: then all of it)
       song      the whole song, slowly
       concert   the whole song in time: its stars are the stars of the song
  */
  const UNITS = [
    {
      id: 'u1', title: 'Hitta på pianot', sub: 'Fem tangenter för höger hand', stage: 0,
      lessons: [
        {
          id: 'cde', title: 'C, D och E', kind: 'notes', fresh: ['C4', 'D4', 'E4'], known: [],
          info: {
            title: 'Här bor C, D och E',
            text: 'Titta på de svarta tangenterna. De sitter i grupper: två, tre, två, tre … Den vita tangenten precis till vänster om två svarta heter C. Sedan kommer D och E.',
            keys: ['C4', 'D4', 'E4'],
          },
        },
        {
          id: 'fg', title: 'F och G', kind: 'notes', fresh: ['F4', 'G4'], known: ['C4', 'D4', 'E4'],
          info: {
            title: 'Här bor F och G',
            text: 'Till vänster om tre svarta tangenter sitter F. Efter F kommer G. Nu kan du fem tangenter på rad: C, D, E, F och G.',
            keys: ['F4', 'G4'],
          },
        },
        {
          id: 'hand', title: 'Fem fingrar', kind: 'patterns', fingers: 'C4',
          info: {
            title: 'En tangent för varje finger',
            text: 'Lägg höger hand så att tummen vilar på C. Då har varje finger sin egen tangent. Tummen är finger 1 och lillfingret finger 5. Siffrorna över noterna visar vilket finger som spelar.',
            keys: ['C4', 'D4', 'E4', 'F4', 'G4'], fingers: 'C4',
          },
          items: [
            ['play', 'C D E F G2'],
            ['play', 'G F E D C2'],
            ['echo', 'C E G2'],
            ['play', 'C E G E | C4'],
            ['echo', 'E F G2'],
            ['play', 'C D E F | G F E D | C4'],
            ['tempo', 'C D E F | G F E D | C4', { bpm: 76 }],
          ],
        },
        { id: 'noak1', title: 'Gubben Noak', kind: 'phrase', song: 'noak', parts: [0] },
        { id: 'noak2', title: 'Hela Gubben Noak', kind: 'phrase', song: 'noak', parts: [1], whole: true },
      ],
    },
    {
      id: 'u2', title: 'Bjällerklang', sub: 'Din första julsång', stage: 0, xmas: true,
      lessons: [
        { id: 'bj1', title: 'Bjällerklang, början', kind: 'phrase', song: 'bjallerklang', parts: [0] },
        { id: 'bj2', title: 'Bjällerklang, fortsättningen', kind: 'phrase', song: 'bjallerklang', parts: [1] },
        { id: 'bj3', title: 'Bjällerklang, slutet', kind: 'phrase', song: 'bjallerklang', parts: [3] },
        { id: 'bj4', title: 'Hela Bjällerklang', kind: 'song', song: 'bjallerklang' },
        { id: 'bj5', title: 'Konsert: Bjällerklang', kind: 'concert', song: 'bjallerklang' },
      ],
    },
    {
      id: 'u3', title: 'Läsa noter', sub: 'Linjer, mellanrum och en stjärna', stage: 2,
      lessons: [
        {
          id: 'r1', title: 'Noterna C, D och E', kind: 'read', notes: ['C4', 'D4', 'E4'], pool: ['C4', 'D4', 'E4'],
          info: {
            title: 'Noterna bor på fem linjer',
            text: 'Ju högre upp en not sitter, desto ljusare låter den. C har ett eget litet streck under linjerna. D hänger precis under den nedersta linjen, och E sitter på den.',
            staff: ['C4', 'D4', 'E4'],
          },
        },
        {
          id: 'r2', title: 'Noterna F och G', kind: 'read', notes: ['F4', 'G4'], pool: ['C4', 'D4', 'E4', 'F4', 'G4'],
          info: {
            title: 'Varannan på linje, varannan emellan',
            text: 'F sitter i det första mellanrummet och G på den andra linjen. Tecknet i början av raden heter G-klav: dess snurra ringar in just G-linjen.',
            staff: ['E4', 'F4', 'G4'],
          },
        },
        {
          id: 'a', title: 'Tonen A', kind: 'notes', staff: true, fresh: ['A4'], known: ['E4', 'F4', 'G4'],
          info: {
            title: 'Efter G kommer A',
            text: 'Tonerna heter som de första bokstäverna i alfabetet, och efter G börjar det om: nästa vita tangent heter A. I noterna sitter A i det andra mellanrummet.',
            keys: ['A4'], staff: ['G4', 'A4'],
          },
        },
        { id: 'bl1', title: 'Blinka lilla stjärna, början', kind: 'phrase', song: 'blinka', parts: [0] },
        { id: 'bl2', title: 'Blinka lilla stjärna, mitten', kind: 'phrase', song: 'blinka', parts: [1] },
        { id: 'bl3', title: 'Hela Blinka lilla stjärna', kind: 'song', song: 'blinka' },
        { id: 'bl4', title: 'Konsert: Blinka lilla stjärna', kind: 'concert', song: 'blinka' },
      ],
    },
    {
      id: 'u4', title: 'Upp till höga C', sub: 'En hel oktav och O du saliga', stage: 2, xmas: true,
      lessons: [
        {
          id: 'hc', title: '{H} och höga C', kind: 'notes', staff: true, fresh: ['B4', "C5"], known: ['G4', 'A4'],
          info: {
            title: 'Åtta tangenter är en oktav',
            text: 'Efter A kommer {H} – och sedan C igen! Det nya C:et låter ljusare än det första och kallas höga C. Från ett C till nästa är det åtta vita tangenter: en oktav.',
            keys: ['B4', 'C5'], staff: ['A4', 'B4', 'C5'],
          },
        },
        {
          id: 'skala', title: 'C-durskalan', kind: 'patterns',
          info: {
            title: 'Åtta toner och fem fingrar',
            text: 'Åtta toner på rad kallas en skala. Fingrarna räcker inte till, så handen får flytta sig: spela C, D och E med finger 1, 2 och 3. Låt sedan tummen krypa under handen och ta F.',
            keys: ['C4', 'D4', 'E4', 'F4', 'G4', 'A4', 'B4', 'C5'],
          },
          items: [
            ['play', "C D E F", { fing: '1231' }],
            ['play', "C D E F | G A B C'", { fing: '12312345' }],
            ['play', "C' B A G | F E D C", { fing: '54321321' }],
            ['echo', "G A B C'2"],
            ['play', "C D E F | G A B C' | C' B A G | F E D C", { fing: '1231234554321321' }],
            ['tempo', "C D E F | G A B C' | C' B A G | F E D C", { bpm: 72, fing: '1231234554321321' }],
          ],
        },
        { id: 'sa1', title: 'O du saliga, början', kind: 'phrase', song: 'saliga', parts: [0, 1] },
        { id: 'sa2', title: 'O du saliga, mitten', kind: 'phrase', song: 'saliga', parts: [2] },
        { id: 'sa3', title: 'O du saliga, slutet', kind: 'phrase', song: 'saliga', parts: [3] },
        { id: 'sa4', title: 'Hela O du saliga', kind: 'song', song: 'saliga' },
        { id: 'sa5', title: 'Konsert: O du saliga', kind: 'concert', song: 'saliga' },
      ],
    },
    {
      id: 'u5', title: 'Den första svarta tangenten', sub: 'Nu tändas tusen juleljus', stage: 2, xmas: true,
      lessons: [
        {
          id: 'bb', title: 'Tonen {Bb}', kind: 'notes', staff: true, fresh: ['Bb4'], known: ['G4', 'A4', 'C5'],
          info: {
            title: 'En svart tangent',
            text: 'Nu är det dags för en svart tangent! Den som sitter mellan A och {H} heter {Bb}. I noterna ritas den på samma plats som {H}, med tecknet ♭ framför.',
            keys: ['Bb4'], staff: ['A4', 'Bb4', 'C5'],
          },
        },
        {
          id: 'flage', title: 'Handen flyttar till F', kind: 'patterns', fingers: 'F4',
          info: {
            title: 'Tummen på F',
            text: 'Flytta handen så att tummen vilar på F. Finger 4 hamnar då på den svarta tangenten {Bb} och lillfingret på höga C.',
            keys: ['F4', 'G4', 'A4', 'Bb4', 'C5'], fingers: 'F4',
          },
          items: [
            ['play', "F G A Bb | C'4"],
            ['play', "C' Bb A G | F4"],
            ['echo', "A Bb C'2"],
            ['play', "F A C' A | F4"],
            ['play', "C' C' Bb Bb | A2 F2"],
            ['tempo', "F G A Bb | C' Bb A G | F4", { bpm: 76 }],
          ],
        },
        { id: 'ju1', title: 'Nu tändas tusen juleljus, början', kind: 'phrase', song: 'juleljus', parts: [0] },
        { id: 'ju2', title: 'Nu tändas tusen juleljus, slutet', kind: 'phrase', song: 'juleljus', parts: [1] },
        { id: 'ju3', title: 'Hela Nu tändas tusen juleljus', kind: 'song', song: 'juleljus' },
        { id: 'ju4', title: 'Konsert: Nu tändas tusen juleljus', kind: 'concert', song: 'juleljus' },
      ],
    },
    {
      id: 'u6', title: 'En julsång i tretakt', sub: 'We Wish You a Merry Christmas', stage: 2, xmas: true,
      lessons: [
        {
          id: 'atta', title: 'Åttondelar och tretakt', kind: 'patterns', time: 3,
          info: {
            title: 'Dubbelt så fort',
            text: 'Noter som sitter ihop med en balk, eller har en flagga, heter åttondelar. De är hälften så långa som vanliga fjärdedelar: två åttondelar får plats på ett taktslag. Den här låten går dessutom i tretakt – räkna 1, 2, 3.',
            keys: ['C4', 'D4', 'E4', 'F4', 'G4', 'A4'],
          },
          items: [
            ['echo', 'F F- G- F'],
            ['play', 'F F- G- F | E3'],
            ['tempo', 'F F- G- F | E3', { bpm: 80 }],
            ['echo', 'F- G- F- E- D'],
            ['play', 'F F- G- F- E- | D3'],
            ['tempo', 'F F- G- F- E- | D D D | C3', { bpm: 80 }],
          ],
        },
        { id: 'ww1', title: 'We Wish You, början', kind: 'phrase', song: 'wewish', parts: [0, 1] },
        { id: 'ww2', title: 'We Wish You, slutet', kind: 'phrase', song: 'wewish', parts: [2, 3] },
        { id: 'ww3', title: 'Hela We Wish You a Merry Christmas', kind: 'song', song: 'wewish' },
        { id: 'ww4', title: 'Konsert: We Wish You a Merry Christmas', kind: 'concert', song: 'wewish' },
      ],
    },
    {
      id: 'u7', title: 'Stilla natt', sub: 'Högre upp och noter med punkt', stage: 2, xmas: true,
      lessons: [
        {
          id: 'hog', title: 'Höga D, E och F', kind: 'notes', staff: true, fresh: ['D5', 'E5', 'F5'], known: ['B4', 'C5'],
          info: {
            title: 'Ovanför höga C',
            text: 'Ovanför höga C fortsätter tangenterna likadant som förut: D, E och F. I noterna klättrar de vidare uppåt, förbi den fjärde linjen.',
            keys: ['D5', 'E5', 'F5'], staff: ['C5', 'D5', 'E5', 'F5'],
          },
        },
        {
          id: 'punkt', title: 'Noter med punkt', kind: 'patterns', time: 3,
          info: {
            title: 'Punkten gör noten längre',
            text: 'En punkt efter en not gör den hälften så lång till. En fjärdedel med punkt räcker ett och ett halvt slag – och åttondelen efteråt får skynda sig. Lång, kort, och så en vanlig.',
            keys: ['E4', 'G4', 'A4'],
          },
          items: [
            ['echo', 'G. A- G'],
            ['play', 'G. A- G | E3'],
            ['tempo', 'G. A- G | E3 | G. A- G | E3', { bpm: 72 }],
            ['echo', "C'. B- A"],
            ['play', "A2 A | C'. B- A | G3"],
            ['tempo', "A2 A | C'. B- A | G. A- G | E3", { bpm: 72 }],
          ],
        },
        { id: 'st1', title: 'Stilla natt, början', kind: 'phrase', song: 'stilla', parts: [0, 1] },
        { id: 'st2', title: 'Stilla natt, mitten', kind: 'phrase', song: 'stilla', parts: [2] },
        { id: 'st3', title: 'Stilla natt, slutet', kind: 'phrase', song: 'stilla', parts: [4, 5] },
        { id: 'st4', title: 'Hela Stilla natt', kind: 'song', song: 'stilla' },
        { id: 'st5', title: 'Konsert: Stilla natt', kind: 'concert', song: 'stilla' },
      ],
    },
    {
      id: 'u8', title: 'Sankta Lucia', sub: 'En svart tangent till', stage: 2, xmas: true,
      lessons: [
        {
          id: 'fiss', title: 'Tonen {F#}', kind: 'notes', staff: true, fresh: ['F#4'], known: ['E4', 'F4', 'G4'],
          info: {
            title: 'Mellan F och G',
            text: 'Den svarta tangenten mellan F och G heter {F#}. I noterna ritas den på samma plats som F, med tecknet ♯ framför.',
            keys: ['F#4'], staff: ['F4', 'F#4', 'G4'],
          },
        },
        { id: 'lu1', title: 'Sankta Lucia, början', kind: 'phrase', song: 'lucia', parts: [0] },
        { id: 'lu2', title: 'Sankta Lucia, andra delen', kind: 'phrase', song: 'lucia', parts: [1] },
        { id: 'lu3', title: 'Sankta Lucia, tredje delen', kind: 'phrase', song: 'lucia', parts: [2] },
        { id: 'lu4', title: 'Sankta Lucia, slutet', kind: 'phrase', song: 'lucia', parts: [3] },
        { id: 'lu5', title: 'Hela Sankta Lucia', kind: 'song', song: 'lucia' },
        { id: 'lu6', title: 'Konsert: Sankta Lucia', kind: 'concert', song: 'lucia' },
      ],
    },
    {
      id: 'u9', title: 'Räven raskar över isen', sub: 'En sånglek runt granen', stage: 2, xmas: true,
      lessons: [
        { id: 'ra1', title: 'Räven raskar över isen, början', kind: 'phrase', song: 'raven', parts: [0] },
        { id: 'ra2', title: 'Räven raskar över isen, mitten', kind: 'phrase', song: 'raven', parts: [1] },
        { id: 'ra3', title: 'Räven raskar över isen, slutet', kind: 'phrase', song: 'raven', parts: [2] },
        { id: 'ra4', title: 'Hela Räven raskar över isen', kind: 'song', song: 'raven' },
        { id: 'ra5', title: 'Konsert: Räven raskar över isen', kind: 'concert', song: 'raven' },
      ],
    },
    {
      id: 'u10', title: 'Hej tomtegubbar', sub: 'En polska till jul', stage: 2, xmas: true,
      lessons: [
        { id: 'ht1', title: 'Hej tomtegubbar, början', kind: 'phrase', song: 'tomtegubbar', parts: [0] },
        { id: 'ht2', title: 'Hej tomtegubbar, mitten', kind: 'phrase', song: 'tomtegubbar', parts: [2] },
        { id: 'ht3', title: 'Hela Hej tomtegubbar', kind: 'song', song: 'tomtegubbar' },
        { id: 'ht4', title: 'Konsert: Hej tomtegubbar', kind: 'concert', song: 'tomtegubbar' },
      ],
    },
    {
      id: 'u11', title: 'Nu är det jul igen', sub: 'Ner under mellersta C', stage: 2, xmas: true,
      lessons: [
        {
          id: 'laga', title: 'Låga A', kind: 'notes', staff: true, fresh: ['A3'], known: ['C4', 'D4', 'E4'],
          info: {
            title: 'Under mellersta C',
            text: 'Tangenterna fortsätter till vänster om mellersta C också: först kommer {H} och sedan A. Det är låga A, en oktav under det A du redan kan. I noterna sitter låga A under C, på ett andra litet streck.',
            keys: ['A3'], staff: ['A3', 'C4'],
          },
        },
        {
          id: 'hopp', title: 'Ner och upp igen', kind: 'patterns', time: 3,
          info: {
            title: 'Ett hopp nedåt',
            text: 'Nu är det jul igen börjar på F och hoppar ner till C och låga A – och sedan upp till C igen. Låt handen följa med, eller ta de låga tonerna med vänster hand.',
            keys: ['A3', 'C4', 'F4'],
          },
          items: [
            ['echo', 'C A, C'],
            ['play', 'F C A, | C F2'],
            ['echo', 'F- F- F- C- A,- C-'],
            ['play', 'F- F- F- C- A,- C- | F3'],
            ['play', "F- E- F- G- A- Bb- | C'3"],
            ['tempo', "F- F- F- C- A,- C- | F- E- F- G- A- Bb- | C'3", { bpm: 72 }],
          ],
        },
        { id: 'nj1', title: 'Nu är det jul igen, början', kind: 'phrase', song: 'juligen', parts: [0] },
        { id: 'nj2', title: 'Nu är det jul igen, slutet', kind: 'phrase', song: 'juligen', parts: [2] },
        { id: 'nj3', title: 'Hela Nu är det jul igen', kind: 'song', song: 'juligen' },
        { id: 'nj4', title: 'Konsert: Nu är det jul igen', kind: 'concert', song: 'juligen' },
      ],
    },
  ];

  /* Every lesson in the order it opens: { id, unit, lesson, index }. */
  const ORDER = [];
  for (const unit of UNITS) {
    for (const lesson of unit.lessons) ORDER.push({ id: `${unit.id}-${lesson.id}`, unit, lesson, index: ORDER.length });
  }

  function lessonById(id) {
    return ORDER.find(e => e.id === id) || null;
  }

  /* ── The exercises of a lesson ────────────────────────────────────────── */

  /* A small generator of the same numbers every time, from a seed. */
  function rng(seed) {
    let s = (seed >>> 0) || 1;
    return () => {
      s ^= s << 13; s >>>= 0;
      s ^= s >>> 17;
      s ^= s << 5; s >>>= 0;
      return s / 4294967296;
    };
  }

  function hash(text) {
    let h = 2166136261;
    for (let i = 0; i < text.length; i++) h = Math.imul(h ^ text.charCodeAt(i), 16777619);
    return h >>> 0;
  }

  function shuffled(list, r) {
    const a = list.slice();
    for (let i = a.length - 1; i > 0; i--) {
      const j = Math.floor(r() * (i + 1));
      [a[i], a[j]] = [a[j], a[i]];
    }
    return a;
  }

  /* Quarter notes, the last one long: a little tune out of single pitches. */
  function line(pitches, time) {
    const text = pitches.map((p, i) => {
      const n = typeof p === 'string' ? pitch(p) : p;
      let tok = n.letter + (n.acc > 0 ? '#' : n.acc < 0 ? 'b' : '');
      for (let k = n.octave; k > 4; k--) tok += "'";
      for (let k = n.octave; k < 4; k++) tok += ',';
      return tok + (i === pitches.length - 1 ? '2' : '');
    }).join(' ');
    return parse(text, { time: time || 4 }).notes;
  }

  /* A walk of `length` steps among the pool, by step or skip, that holds
     at least one of the notes in `must`. */
  function walk(pool, must, length, r) {
    const sorted = pool.slice().sort((a, b) => a.midi - b.midi);
    for (let attempt = 0; attempt < 40; attempt++) {
      let k = Math.floor(r() * sorted.length);
      const out = [sorted[k]];
      while (out.length < length) {
        const move = [-2, -1, -1, 1, 1, 2][Math.floor(r() * 6)];
        const next = Math.max(0, Math.min(sorted.length - 1, k + move));
        if (next === k) continue;
        k = next;
        out.push(sorted[k]);
      }
      if (out.some(n => must.some(m => m.midi === n.midi))) return out;
    }
    return must.slice(0, length);
  }

  /* The answer and two or three other names from the pool, mixed. */
  function choices(target, pool, r) {
    const others = shuffled(pool.filter(n => n.midi !== target.midi), r).slice(0, 3);
    // Too few to choose among: neighbours on the keyboard fill up.
    for (const d of [1, -1, 2, -2, 3]) {
      if (others.length >= 2) break;
      const n = fromMidi(target.midi + d);
      if (n.acc === 0 && !others.some(q => q.midi === n.midi)) others.push(n);
    }
    return shuffled([target, ...others], r);
  }

  /* Where to cut a part in two: the bar line nearest its middle. */
  function halves(notes) {
    if (notes.length < 6) return null;
    const first = notes[0].start;
    const total = notes[notes.length - 1].start + notes[notes.length - 1].beats - first;
    let best = -1;
    for (let i = 2; i < notes.length - 1; i++) {
      if (notes[i].bar === notes[i - 1].bar) continue;
      if (best < 0 || Math.abs(notes[i].start - first - total / 2) < Math.abs(notes[best].start - first - total / 2)) best = i;
    }
    return best < 0 ? null : [notes.slice(0, best), notes.slice(best)];
  }

  /**
   * The exercises of a lesson: a list of
   *
   *   { type: 'info', title, text, keys, staff, fingers, listen }
   *   { type: 'find', note, hint, staff, letters }
   *   { type: 'name', note, from: 'key'|'staff', choices }
   *   { type: 'echo' | 'play', notes, letters, hint, fingers, fing, time }
   *   { type: 'tempo', notes, bpm, letters, fingers, fing, time, grade }
   *
   * opts.seed varies the random parts (the page passes how many times the
   * lesson has been done); opts.own is the list of the player's own songs.
   */
  function buildLesson(id, opts) {
    const entry = lessonById(id);
    if (!entry) return [];
    const o = opts || {};
    const { unit, lesson } = entry;
    const stage = unit.stage;
    const r = rng(hash(`${id}/${o.seed || 0}`));
    const ex = [];
    const info = lesson.info ? {
      type: 'info',
      title: lesson.info.title,
      text: lesson.info.text,
      keys: (lesson.info.keys || []).map(pitch),
      staff: (lesson.info.staff || []).map(pitch),
      fingers: lesson.info.fingers ? pitch(lesson.info.fingers).midi : null,
    } : null;

    if (lesson.kind === 'notes') {
      const fresh = lesson.fresh.map(pitch);
      const known = lesson.known.map(pitch);
      const pool = [...known, ...fresh];
      const staff = !!lesson.staff;
      ex.push(info);
      for (const n of fresh) ex.push({ type: 'find', note: n, hint: true, staff, letters: true });
      for (const n of shuffled([...fresh, ...shuffled(known, r).slice(0, 2)], r)) {
        ex.push({ type: 'find', note: n, hint: false, staff, letters: false });
      }
      for (const n of shuffled(fresh, r).slice(0, 2)) {
        ex.push({ type: 'name', note: n, from: staff ? 'staff' : 'key', choices: choices(n, pool, r) });
      }
      if (pool.length >= 3) {
        ex.push({ type: 'echo', notes: line(walk(pool, fresh, 3, r)), letters: true, hint: false, time: 4 });
        ex.push({ type: 'echo', notes: line(walk(pool, fresh, 4, r)), letters: true, hint: false, time: 4 });
      }
      const sorted = pool.slice().sort((a, b) => a.midi - b.midi);
      const tune = sorted.length >= 3 ? [...sorted, ...sorted.slice(0, -1).reverse()] : [...sorted, ...sorted];
      ex.push({ type: 'play', notes: line(tune.slice(0, 9)), letters: !staff, hint: stage === 0, time: 4 });
    } else if (lesson.kind === 'read') {
      const notes = lesson.notes.map(pitch);
      const pool = lesson.pool.map(pitch);
      ex.push(info);
      for (const n of notes) ex.push({ type: 'find', note: n, hint: true, staff: true, letters: true });
      for (const n of shuffled(notes, r)) ex.push({ type: 'name', note: n, from: 'staff', choices: choices(n, pool, r) });
      for (const n of shuffled(pool, r).slice(0, 3)) ex.push({ type: 'find', note: n, hint: false, staff: true, letters: false });
      for (const n of shuffled(pool, r).slice(0, 2)) ex.push({ type: 'name', note: n, from: 'staff', choices: choices(n, pool, r) });
      ex.push({ type: 'play', notes: line(walk(pool, notes, 5, r)), letters: false, hint: false, time: 4 });
    } else if (lesson.kind === 'patterns') {
      const time = lesson.time || 4;
      const fingers = lesson.fingers ? pitch(lesson.fingers).midi : null;
      ex.push(info);
      for (const [type, text, more] of lesson.items) {
        const m = more || {};
        ex.push({
          type,
          notes: parse(text, { time }).notes,
          letters: true,
          hint: type === 'play' && stage === 0,
          fingers,
          fing: m.fing || null,
          bpm: m.bpm || 80,
          time,
        });
      }
    } else {
      const song = songById(lesson.song, o.own);
      if (!song) return [];
      const time = song.time || 4;
      const fingers = song.fingers ? pitch(song.fingers).midi : null;
      const base = { time, fingers };
      const all = partNotes(song);
      if (lesson.kind === 'phrase') {
        const joined = partNotes(song, lesson.parts);
        ex.push({
          type: 'info', title: lesson.title, listen: joined, time, fingers, keys: [], staff: [],
          text: 'Lyssna först på hur det låter. Sedan spelar du en liten bit i taget.',
        });
        for (const p of lesson.parts) {
          const notes = partNotes(song, [p]);
          const cut = halves(notes);
          if (cut) {
            ex.push(Object.assign({ type: 'echo', notes: cut[0], letters: true, hint: stage === 0 }, base));
            ex.push(Object.assign({ type: 'echo', notes: cut[1], letters: true, hint: stage === 0 }, base));
          } else {
            ex.push(Object.assign({ type: 'echo', notes, letters: true, hint: stage === 0 }, base));
          }
          ex.push(Object.assign({ type: 'play', notes, letters: true, hint: stage === 0 }, base));
          ex.push(Object.assign({ type: 'play', notes, letters: stage < 2, hint: false, again: true }, base));
        }
        ex.push(Object.assign({ type: 'tempo', notes: joined, letters: stage < 2, bpm: Math.round(song.bpm * 0.7) }, base));
        if (lesson.whole) {
          ex.push(Object.assign({ type: 'play', notes: all, letters: stage < 2, hint: false, whole: true }, base));
          ex.push(Object.assign({ type: 'tempo', notes: all, letters: stage < 2, bpm: Math.round(song.bpm * 0.75) }, base));
        }
      } else if (lesson.kind === 'song') {
        ex.push({
          type: 'info', title: lesson.title, listen: all, time, fingers, keys: [], staff: [],
          text: 'Nu sätter vi ihop alla delarna. Lyssna gärna först – och spela sedan hela låten i din egen takt.',
        });
        ex.push(Object.assign({ type: 'play', notes: all, letters: stage < 2, hint: false, whole: true }, base));
        ex.push(Object.assign({ type: 'tempo', notes: all, letters: stage < 2, bpm: Math.round(song.bpm * 0.8) }, base));
      } else if (lesson.kind === 'concert') {
        ex.push({
          type: 'info', title: lesson.title, keys: [], staff: [], time, fingers,
          text: 'Dags för konsert! Sätt dig bra, lyssna på inräkningen och spela hela låten i takt. Ju fler toner som kommer rätt och i tid, desto fler stjärnor.',
        });
        ex.push(Object.assign({ type: 'tempo', notes: all, letters: stage < 2, bpm: song.bpm, grade: true }, base));
      }
    }
    return ex.filter(Boolean);
  }

  /* The notes of a list of exercises that are played: for counting. */
  function sounding(notes) {
    return notes.filter(n => !n.rest);
  }

  return {
    pitch, fromMidi, nameOf, sayName, fillNames, parse, fromUser, userToken,
    SONGS, UNITS, ORDER, songById, songNotes, partNotes, lessonById, buildLesson,
    line, halves, sounding, rng, hash,
  };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = PN_SONGS;
