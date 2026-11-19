/* The notes, the songs and the lessons of piano.html.

     node resources/tests/piano/test-songs.js

   Exit status is 0 when every check passes. */
const S = require('../../js/piano-songs.js');
const { check, done } = require('./check.js');

const names = (notes, style) => notes.map(n => S.nameOf(n, style)).join(' ');
const midis = notes => notes.filter(n => !n.rest).map(n => n.midi);

/* ── Notes and names ───────────────────────────────────────────────────── */

check('middle C is key 60, on the ledger line (step 28)', [S.pitch('C4').midi, S.pitch('C4').step], [60, 28]);
check('B flat and F sharp', [S.pitch('Bb4').midi, S.pitch('F#4').midi, S.pitch('Bb4').step, S.pitch('F#4').step], [70, 66, 34, 31]);
check('every key from 48 to 89 comes back as itself', Array.from({ length: 42 }, (_, i) => S.fromMidi(48 + i).midi), Array.from({ length: 42 }, (_, i) => 48 + i));
check('a black key is spelled the usual way', [61, 63, 66, 68, 70].map(m => S.nameOf(S.fromMidi(m), 'b')), ['C♯', 'E♭', 'F♯', 'G♯', 'B♭']);
check('Swedish names: H, and B for the black key', names(['A4', 'Bb4', 'B4', 'C5', 'F#4', 'Eb4', 'Ab4', 'C#4'].map(S.pitch), 'h'), 'A B H C Fiss Ess Ass Ciss');
check('the other names: B and B flat', names(['A4', 'Bb4', 'B4', 'F#4'].map(S.pitch), 'b'), 'A B♭ B F♯');
check('high and low are said', [S.sayName(S.pitch('C5'), 'h'), S.sayName(S.pitch('C4'), 'h'), S.sayName(S.pitch('A3'), 'h')], ['höga C', 'C', 'låga A']);
check('names in a text follow the style', [S.fillNames('{H}, {Bb} och {F#}', 'h'), S.fillNames('{H}, {Bb} och {F#}', 'b')], ['H, B och Fiss', 'B, B♭ och F♯']);

/* ── The notation ──────────────────────────────────────────────────────── */

{
  const p = S.parse("C D2 E. F- G= R A, C' Bb F#4 | X Q9");
  check('lengths: plain, a number, dot, eighth, sixteenth', p.notes.slice(0, 5).map(n => n.beats), [1, 2, 1.5, 0.5, 0.25]);
  check('a rest, octaves down and up, flat and sharp', p.notes.slice(5, 10).map(n => n.midi), [null, 57, 72, 70, 66]);
  check('what is not a note is reported, not guessed', p.problems, ['X', 'Q9']);
  const q = S.parse('C | A A G G | F D C. C- | D D G E | C3 // C | C2', { time: 4, pickup: 1 });
  check('a pickup is bar 0, on the last beat', [q.notes[0].bar, q.notes[0].beat], [0, 3]);
  check('bars and beats after a pickup', q.notes.slice(1, 6).map(n => [n.bar, n.beat]), [[1, 0], [1, 1], [1, 2], [1, 3], [2, 0]]);
  check('// starts a new part', [q.parts, q.notes.find(n => n.part === 1).i], [2, 14]);
  check('a part may start inside a bar', (n => [n.bar, n.beat])(q.notes[14]), [4, 3]);
}
check('typed notes, Swedish style: H, a bare B is the black key, Fiss and Ess', S.fromUser("c d ess fiss b h H2 bb- c'4 a, r", 'h').text, "C D Eb F# Bb B B2 Bb- C'4 A, R");
check('typed notes, the other style: B is the white key', S.fromUser('a b bb h', 'b').text, 'A B Bb B');
check('typed nonsense is reported', S.fromUser('C D zz E 7', 'h').problems, ['zz', '7']);
check('a decimal comma is a decimal point', S.fromUser('C1,5 D0,5', 'h').text, 'C1.5 D0.5');

/* ── The songs ─────────────────────────────────────────────────────────── */

check('eight songs, six of them for Christmas', [S.SONGS.length, S.SONGS.filter(s => s.xmas).length], [8, 6]);
check('song ids are unique', new Set(S.SONGS.map(s => s.id)).size, S.SONGS.length);
for (const song of S.SONGS) {
  const p = S.songNotes(song);
  const per = song.time;
  const pickup = song.pickup || 0;
  check(`${song.id}: every token is a note`, p.problems, []);
  check(`${song.id}: the bar lines written are where the beats put them`, p.barMarks.filter(m => ((m - pickup) % per + per) % per !== 0), []);
  check(`${song.id}: whole bars in all (a pickup is taken from the last bar)`, p.total % per, 0);
  const keys = midis(p.notes);
  check(`${song.id}: within the keys the page listens for and draws (C4 to F5)`, [Math.min(...keys) >= 60, Math.max(...keys) <= 77], [true, true]);
  if (song.fingers) {
    const thumb = S.pitch(song.fingers).step;
    check(`${song.id}: lies under five fingers`, p.notes.every(n => n.step - thumb >= 0 && n.step - thumb <= 4), true);
  }
  check(`${song.id}: has a name, an origin, a tempo and a level`, [!!song.title, !!song.by, song.bpm >= 60 && song.bpm <= 130, [1, 2, 3].includes(song.level)], [true, true, true, true]);
}

/* How each melody begins and ends, as checked against published notation:
   a slip of the hand in a song's text shows here. */
const SHAPE = {
  noak: ['C C C E D D D F E E D D C', 'E E D D C'],
  bjallerklang: ['E E E E E E E G C D E', 'G G F D C'],
  blinka: ['C C G G A A G F F E E D D C', 'F F E E D D C'],
  saliga: ['G A G F E F', 'E D C'],
  juleljus: ['C A A G G F D C C D D G E C', 'E E G G F'],
  wewish: ['C F F G F E D D D G G A G F E C C', 'C C D G E F'],
  stilla: ['G A G E G A G E D D B C C G', 'C G E G F D C'],
  lucia: ['G G C C B B F F A A G', 'D A B D C'],
};
for (const song of S.SONGS) {
  const all = S.songNotes(song).notes.map(n => n.letter);
  const [head, tail] = SHAPE[song.id].map(t => t.split(' '));
  check(`${song.id}: begins and ends as written down`, [all.slice(0, head.length).join(' '), all.slice(-tail.length).join(' ')], [head.join(' '), tail.join(' ')]);
}
check('Nu tändas tusen juleljus has its two B flats, Sankta Lucia its two F sharps',
  [S.songNotes(S.songById('juleljus')).notes.filter(n => n.acc < 0).length, S.songNotes(S.songById('lucia')).notes.filter(n => n.acc > 0).length], [2, 2]);
check('the other songs are on white keys only', S.SONGS.filter(s => !['juleljus', 'wewish', 'lucia'].includes(s.id)).every(s => S.songNotes(s).notes.every(n => n.acc === 0)), true);

/* ── The path ──────────────────────────────────────────────────────────── */

check('lesson ids are unique', new Set(S.ORDER.map(e => e.id)).size, S.ORDER.length);
check('eight units, 49 lessons', [S.UNITS.length, S.ORDER.length], [8, 49]);
check('the first Christmas song comes in the second unit', S.UNITS[1].lessons[0].song, 'bjallerklang');
check('every song has its concert', S.SONGS.filter(s => s.id !== 'noak').map(s => S.ORDER.some(e => e.lesson.kind === 'concert' && e.lesson.song === s.id)), [true, true, true, true, true, true, true]);
const TYPES = ['info', 'find', 'name', 'echo', 'play', 'tempo'];
let known = new Set();
for (const e of S.ORDER) {
  const ex = S.buildLesson(e.id, { seed: 0 });
  const bad = [];
  if (ex.length < 2 || ex.length > 16) bad.push(`length ${ex.length}`);
  if (ex[0].type !== 'info') bad.push('does not open with a card');
  for (const x of ex) {
    if (!TYPES.includes(x.type)) bad.push(`type ${x.type}`);
    if (['echo', 'play', 'tempo'].includes(x.type) && !midis(x.notes).length) bad.push(`${x.type} without notes`);
    if (x.type === 'tempo' && !(x.bpm >= 40 && x.bpm <= 130)) bad.push(`tempo ${x.bpm}`);
    if (x.type === 'name') {
      if (!x.choices.some(n => n.midi === x.note.midi)) bad.push('the answer is not among the choices');
      if (new Set(x.choices.map(n => S.nameOf(n, 'h'))).size !== x.choices.length) bad.push('two choices of one name');
      if (x.choices.length < 3) bad.push('fewer than three choices');
    }
    if (x.fing && x.fing.length !== midis(x.notes).length) bad.push('a finger is missing');
    if (x.type === 'info' && /\{/.test(S.fillNames(`${x.title} ${x.text}`, 'h'))) bad.push('an unfilled name');
  }
  if (e.lesson.kind === 'concert' && !(ex.length === 2 && ex[1].type === 'tempo' && ex[1].grade)) bad.push('a concert is a card and the song in time');
  check(`${e.id}: builds (${ex.map(x => x.type[0]).join('')})`, bad, []);
  // A melody never asks for a key no earlier lesson has shown.
  const here = new Set(ex.flatMap(x => (x.notes ? midis(x.notes) : x.note ? [x.note.midi] : [])));
  if (e.lesson.kind === 'notes' || e.lesson.kind === 'read' || e.lesson.kind === 'patterns') for (const m of here) known.add(m);
  else check(`${e.id}: plays only keys already taught`, [...here].filter(m => !known.has(m)), []);
}
check('a lesson is the same each time for one seed', JSON.stringify(S.buildLesson('u1-cde', { seed: 3 })), JSON.stringify(S.buildLesson('u1-cde', { seed: 3 })));
check('and varies from one time to the next', JSON.stringify(S.buildLesson('u1-cde', { seed: 0 })) !== JSON.stringify(S.buildLesson('u1-cde', { seed: 1 })), true);
check('a part is cut in two at a bar line', S.halves(S.partNotes(S.songById('bjallerklang'), [0])).map(h => h.length), [6, 5]);
check('an unknown lesson is no lesson', S.buildLesson('nope'), []);
{
  const own = [{ id: 'own-1', title: 'Min', text: 'C D E2', time: 4, own: true }];
  check('an own song is found beside the built-in ones', [S.songById('own-1', own).title, S.songById('blinka', own).title, S.songById('own-2', own)], ['Min', 'Blinka lilla stjärna', null]);
}

done();
