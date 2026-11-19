/* ==========================================================================
   PIANO - RIGHT AND WRONG, STARS, POINTS AND DAYS IN A ROW

   The rules of piano.html, apart from the page, so they can be tested in
   Node (resources/tests/piano):

     createWait    a melody played at the player's own pace: the page waits
                   for the right key before it moves on;
     createTempo   a melody played in time: each note has its moment, and a
                   window around it;
     stars         one to three, from the share played right;
     blank, validate, finishLesson, finishSong
                   what is remembered between visits: points per day, the
                   days in a row, stars per lesson, badges.

   A heard note is { midi, source, t, again }: source 'mic', 'midi',
   'screen' or 'keys', t the moment it was struck on the page's clock, again
   true when the microphone heard the sounding key struck once more.

   Nothing here is hard on the player: a lesson cannot be failed, a wrong
   key costs one mark however many times it is pressed, and the days in a
   row only ever say how many - a missed day starts the count again at one,
   without a word about it.
   ========================================================================== */

const PN_GAME = (() => {
  'use strict';

  /* ── Is it the right key ──────────────────────────────────────────────── */

  function matches(expected, heard, opts) {
    if (!heard || expected === null || expected === undefined) return false;
    if (heard.midi === expected) return true;
    return !!(opts && opts.anyOctave) && heard.source === 'mic' && (heard.midi - expected) % 12 === 0
      && Math.abs(heard.midi - expected) <= 24;
  }

  /* ── At the player's own pace ─────────────────────────────────────────── */

  /* A piano string rings on after the key: the microphone may hear the
     note just played once more. Within this long, that is not a wrong key. */
  const RING_MS = 700;
  /* After this many wrong keys on one note the page shows which key it is. */
  const HINT_AFTER = 2;

  /**
   * midis: the keys to play, in order. hear(note) returns
   * { kind: 'right' | 'wrong' | 'ignore', index, expected, showHint, done }.
   */
  function createWait(midis, opts) {
    const o = opts || {};
    let i = 0;
    let wrongHere = 0;
    let lastRight = null;
    let lastWrong = null;
    const missed = new Set();

    function hear(note) {
      if (i >= midis.length) return { kind: 'ignore', index: i, expected: null, done: true };
      const expected = midis[i];
      if (matches(expected, note, o)) {
        lastRight = { midi: expected, t: note.t };
        lastWrong = null;
        const index = i;
        i++;
        wrongHere = 0;
        return { kind: 'right', index, expected, done: i >= midis.length };
      }
      if (note.source === 'mic') {
        // The note just played right, heard once more: its string rings on,
        // and strings not quite in unison swell and fade like a new strike.
        if (lastRight && matches(lastRight.midi, note, o) && (note.again || note.t - lastRight.t < RING_MS)) {
          return { kind: 'ignore', index: i, expected, done: false };
        }
        if (lastWrong && lastWrong.midi === note.midi && note.t - lastWrong.t < RING_MS) {
          lastWrong.t = note.t;
          return { kind: 'ignore', index: i, expected, done: false };
        }
      }
      lastWrong = { midi: note.midi, t: note.t };
      wrongHere++;
      missed.add(i);
      return { kind: 'wrong', index: i, expected, showHint: wrongHere >= HINT_AFTER, done: false };
    }

    return {
      hear,
      index: () => i,
      expected: () => (i < midis.length ? midis[i] : null),
      done: () => i >= midis.length,
      total: midis.length,
      mistakes: () => missed.size,
      /* The share of the notes played right the first time. */
      accuracy: () => (midis.length ? 1 - missed.size / midis.length : 1),
    };
  }

  /* ── In time ──────────────────────────────────────────────────────────── */

  /* How far from its moment a note may come, in beats and in seconds: wide
     at a slow tempo, never so narrow that a child's hand cannot find it. */
  const WINDOW = Object.freeze({ beats: 0.45, min: 0.26, max: 0.5 });

  /**
   * notes: [{ midi, start }] with start in beats, rests left out. bpm the
   * tempo. hear(note, seconds) takes the time since the first note's
   * moment (negative during the count-in) and returns
   * { kind: 'hit', index, offset } or { kind: 'extra' }.
   */
  function createTempo(notes, bpm, opts) {
    const o = opts || {};
    const beat = 60 / bpm;
    const first = notes.length ? notes[0].start : 0;
    const times = notes.map(n => (n.start - first) * beat);
    const win = Math.max(WINDOW.min, Math.min(WINDOW.max, WINDOW.beats * beat));
    const state = notes.map(() => null);     // null waiting, number hit (its offset), false missed

    function hear(note, t) {
      let best = -1;
      for (let j = 0; j < notes.length; j++) {
        if (state[j] !== null) continue;
        if (Math.abs(t - times[j]) > win) continue;
        if (!matches(notes[j].midi, note, o)) continue;
        if (best < 0 || Math.abs(t - times[j]) < Math.abs(t - times[best])) best = j;
      }
      if (best < 0) return { kind: 'extra' };
      state[best] = t - times[best];
      return { kind: 'hit', index: best, offset: state[best] };
    }

    /* The notes whose moment has gone by unplayed, as of t: marked missed. */
    function sweep(t) {
      const gone = [];
      for (let j = 0; j < notes.length; j++) {
        if (state[j] === null && t - times[j] > win) { state[j] = false; gone.push(j); }
      }
      return gone;
    }

    function result() {
      const hits = state.filter(s => typeof s === 'number');
      return {
        hits: hits.length,
        total: notes.length,
        accuracy: notes.length ? hits.length / notes.length : 1,
        /* Positive: the player comes after the beat. */
        late: hits.length ? hits.reduce((a, b) => a + b, 0) / hits.length : 0,
      };
    }

    return {
      hear, sweep, result, times, window: win, beat,
      length: (notes.length ? times[times.length - 1] : 0),
      state: () => state.slice(),
    };
  }

  function stars(accuracy) {
    return accuracy >= 0.9 ? 3 : accuracy >= 0.7 ? 2 : 1;
  }

  /* ── Days ─────────────────────────────────────────────────────────────── */

  /* The player's own day, not Greenwich's: 2026-11-19. */
  function dayKey(date) {
    const d = date || new Date();
    const p = n => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
  }

  function addDays(key, n) {
    const [y, m, d] = key.split('-').map(Number);
    return dayKey(new Date(y, m - 1, d + n, 12));
  }

  const DAY = /^\d{4}-\d{2}-\d{2}$/;

  /* ── What is remembered ───────────────────────────────────────────────── */

  const SETTINGS = Object.freeze({
    names: 'h',          // 'h': C D E F G A H, 'b': C D E F G A B
    letters: 'auto',     // letters under the notes: 'auto' (as the lesson says), 'always', 'never'
    keyNames: true,      // names on the keys of the picture
    sound: true,         // the page's own sounds
    tick: true,          // the beat is heard, not only seen
    goal: 40,            // points a day
    anyOctave: false,    // the microphone: the right note in another octave counts
    openAll: false,      // every lesson open
    mic: false,          // listen at once when a lesson starts
  });

  function blank() {
    return {
      v: 1,
      xp: 0,
      days: {},                       // day -> points that day
      streak: { count: 0, last: null, best: 0 },
      lessons: {},                    // id -> { stars, times }
      songs: {},                      // id -> { stars, best, times }
      notes: 0,                       // keys played right, in all
      badges: {},                     // id -> the day it was earned
      flags: {},                      // small facts the badges ask about
      own: [],                        // the player's own songs
      tune: 0,                        // how the piano is tuned, in cents from 440 Hz
      loudness: null,                 // how loud it comes in through this microphone: piano-ear.js's loudness()
      settings: Object.assign({}, SETTINGS),
    };
  }

  const count = (v, max) => (Number.isFinite(v) && v >= 0 ? Math.min(max, Math.floor(v)) : 0);
  const isObject = v => !!v && typeof v === 'object' && !Array.isArray(v);

  /* Whatever was stored, made into a store that the page can trust. */
  function validate(raw) {
    const s = blank();
    if (!isObject(raw)) return s;
    s.xp = count(raw.xp, 1e7);
    s.notes = count(raw.notes, 1e8);
    if (isObject(raw.days)) {
      for (const k of Object.keys(raw.days).filter(d => DAY.test(d)).sort().slice(-400)) s.days[k] = count(raw.days[k], 1e5);
    }
    if (isObject(raw.streak)) {
      s.streak.last = typeof raw.streak.last === 'string' && DAY.test(raw.streak.last) ? raw.streak.last : null;
      s.streak.count = s.streak.last ? count(raw.streak.count, 1e5) : 0;
      s.streak.best = Math.max(s.streak.count, count(raw.streak.best, 1e5));
    }
    for (const [from, to] of [[raw.lessons, s.lessons], [raw.songs, s.songs]]) {
      if (!isObject(from)) continue;
      for (const k of Object.keys(from).slice(0, 500)) {
        const e = from[k];
        if (!isObject(e) || !/^[\w-]{1,40}$/.test(k)) continue;
        to[k] = { stars: Math.max(0, Math.min(3, count(e.stars, 3))), times: count(e.times, 1e6) };
        if (Number.isFinite(e.best)) to[k].best = Math.max(0, Math.min(1, e.best));
      }
    }
    for (const [from, to] of [[raw.badges, s.badges], [raw.flags, s.flags]]) {
      if (!isObject(from)) continue;
      for (const k of Object.keys(from).slice(0, 200)) {
        if (/^[\w-]{1,40}$/.test(k)) to[k] = typeof from[k] === 'string' ? from[k].slice(0, 10) : from[k] === true ? true : count(from[k], 1e6);
      }
    }
    if (Array.isArray(raw.own)) {
      for (const e of raw.own.slice(0, 40)) {
        if (!isObject(e) || typeof e.text !== 'string' || typeof e.title !== 'string') continue;
        s.own.push({
          id: /^own-[\w]{1,20}$/.test(e.id) ? e.id : `own-${s.own.length + 1}`,
          title: e.title.slice(0, 60),
          text: e.text.slice(0, 4000),
          time: e.time === 3 ? 3 : 4,
          pickup: [0, 0.5, 1, 1.5, 2, 3].includes(e.pickup) ? e.pickup : 0,
          bpm: Number.isFinite(e.bpm) ? Math.max(40, Math.min(160, Math.round(e.bpm))) : 90,
          own: true,
        });
      }
    }
    s.tune = Number.isFinite(raw.tune) ? Math.max(-50, Math.min(50, raw.tune)) : 0;
    const L = raw.loudness;
    if (isObject(L) && Number.isFinite(L.floor) && L.floor > 0 && L.floor <= 0.01 && Number.isFinite(L.typical) && L.typical >= 0 && L.typical < 1) {
      s.loudness = { floor: L.floor, typical: L.typical };
    }
    if (isObject(raw.settings)) {
      const t = raw.settings;
      if (t.names === 'h' || t.names === 'b') s.settings.names = t.names;
      if (['auto', 'always', 'never'].includes(t.letters)) s.settings.letters = t.letters;
      if ([20, 40, 60].includes(t.goal)) s.settings.goal = t.goal;
      for (const k of ['keyNames', 'sound', 'tick', 'anyOctave', 'openAll', 'mic']) {
        if (typeof t[k] === 'boolean') s.settings[k] = t[k];
      }
    }
    return s;
  }

  /* The days in a row as of today: a count that ended before yesterday is over. */
  function streakNow(store, today) {
    const last = store.streak.last;
    if (!last) return 0;
    return last === today || last === addDays(today, -1) ? store.streak.count : 0;
  }

  /* The last seven days, oldest first: { day, xp, met }. */
  function week(store, today) {
    const out = [];
    for (let k = -6; k <= 0; k++) {
      const day = addDays(today, k);
      const xp = store.days[day] || 0;
      out.push({ day, xp, met: xp >= store.settings.goal });
    }
    return out;
  }

  /* Level n needs 60 points more than level n - 1 did: 0, 60, 180, 360 ... */
  function level(xp) {
    let n = 1;
    let floor = 0;
    while (xp >= floor + 60 * n) { floor += 60 * n; n++; }
    return { level: n, into: xp - floor, need: 60 * n };
  }

  function totalStars(store) {
    let n = 0;
    for (const k of Object.keys(store.lessons)) n += store.lessons[k].stars;
    return n;
  }

  /* ── Badges ───────────────────────────────────────────────────────────── */

  /*
     Each badge: what it is called, how it is earned (the text under a badge
     not yet earned), its picture and the test. `ctx` is { store, xmas } -
     xmas the number of Christmas songs whose concert has been played.
  */
  const BADGES = [
    { id: 'first', title: 'Första lektionen', how: 'Klara din första lektion', icon: 'note', test: c => Object.keys(c.store.lessons).length >= 1 },
    { id: 'real', title: 'Riktigt piano', how: 'Klara en lektion på ett riktigt piano', icon: 'mic', test: c => !!c.store.flags.real },
    { id: 'three', title: 'Tre stjärnor', how: 'Få tre stjärnor på en lektion', icon: 'star', test: c => Object.values(c.store.lessons).some(l => l.stars === 3) },
    { id: 'goal', title: 'Dagens mål', how: 'Nå dagens mål', icon: 'target', test: c => Object.values(c.store.days).some(x => x >= c.store.settings.goal) },
    { id: 'streak3', title: 'Tre dagar i rad', how: 'Spela tre dagar i rad', icon: 'flame', test: c => c.store.streak.best >= 3 },
    { id: 'streak7', title: 'En hel vecka', how: 'Spela sju dagar i rad', icon: 'flame', test: c => c.store.streak.best >= 7 },
    { id: 'streak14', title: 'Två veckor', how: 'Spela fjorton dagar i rad', icon: 'flame', test: c => c.store.streak.best >= 14 },
    { id: 'streak24', title: 'Julkalendern', how: 'Spela tjugofyra dagar i rad', icon: 'gift', test: c => c.store.streak.best >= 24 },
    { id: 'notes100', title: 'Hundra toner', how: 'Spela 100 toner rätt', icon: 'keys', test: c => c.store.notes >= 100 },
    { id: 'notes1000', title: 'Tusen toner', how: 'Spela 1 000 toner rätt', icon: 'keys', test: c => c.store.notes >= 1000 },
    { id: 'notes5000', title: 'Femtusen toner', how: 'Spela 5 000 toner rätt', icon: 'keys', test: c => c.store.notes >= 5000 },
    { id: 'stars25', title: 'Stjärnsamlare', how: 'Samla 25 stjärnor', icon: 'star', test: c => totalStars(c.store) >= 25 },
    { id: 'stars75', title: 'Stjärnhimmel', how: 'Samla 75 stjärnor', icon: 'star', test: c => totalStars(c.store) >= 75 },
    { id: 'concert', title: 'Första konserten', how: 'Spela en hel låt i takt', icon: 'trophy', test: c => !!c.store.flags.concert },
    { id: 'perfect', title: 'Felfri konsert', how: 'Spela en konsert utan en enda miss', icon: 'trophy', test: c => !!c.store.flags.perfect },
    { id: 'xmas1', title: 'Julsångare', how: 'Spela en julsång på konsert', icon: 'tree', test: c => c.xmas >= 1 },
    { id: 'xmas3', title: 'Julkonsert', how: 'Spela tre julsånger på konsert', icon: 'tree', test: c => c.xmas >= 3 },
    { id: 'xmas6', title: 'Julstjärna', how: 'Spela sex julsånger på konsert', icon: 'tree', test: c => c.xmas >= 6 },
    { id: 'xmas9', title: 'Hela julen', how: 'Spela alla nio julsångerna på konsert', icon: 'tree', test: c => c.xmas >= 9 },
    { id: 'own', title: 'Egen låt', how: 'Skriv in en egen låt', icon: 'pen', test: c => c.store.own.length >= 1 },
  ];

  /* Badges earned now and not before: marked in the store, and returned. */
  function award(store, ctx, today) {
    const fresh = [];
    const c = Object.assign({ store, xmas: 0 }, ctx || {});
    for (const b of BADGES) {
      if (store.badges[b.id]) continue;
      if (b.test(c)) { store.badges[b.id] = today; fresh.push(b); }
    }
    return fresh;
  }

  /* ── A lesson is over ─────────────────────────────────────────────────── */

  /* Points for a lesson: more for stars, a little more the first time. */
  function lessonXp(starCount, firstTime) {
    return 10 + 5 * starCount + (firstTime ? 5 : 0);
  }

  function addPoints(store, xp, today) {
    const beforeDay = store.days[today] || 0;
    store.xp += xp;
    store.days[today] = beforeDay + xp;
    const before = streakNow(store, today);
    if (store.streak.last !== today) {
      store.streak.count = before + 1;
      store.streak.last = today;
      store.streak.best = Math.max(store.streak.best, store.streak.count);
    }
    const days = Object.keys(store.days).sort();
    for (const d of days.slice(0, Math.max(0, days.length - 400))) delete store.days[d];
    return {
      xp,
      streak: { before, after: store.streak.count, grew: store.streak.count > before },
      goal: { before: beforeDay, after: store.days[today], target: store.settings.goal, reached: beforeDay < store.settings.goal && store.days[today] >= store.settings.goal },
    };
  }

  /**
   * A lesson finished. result: { accuracy, notes, real } - the share right
   * the first time, the keys played right, and whether a real piano was
   * heard (microphone or MIDI). ctx is what the badges ask about beyond the
   * store: { concertOf, xmas }, the song this lesson is the concert of, and
   * a function giving the number of Christmas concerts played once this
   * lesson is counted.
   */
  function finishLesson(store, id, result, today, ctx) {
    const c = ctx || {};
    const n = stars(result.accuracy);
    const old = store.lessons[id];
    const xp = lessonXp(n, !old);
    store.lessons[id] = { stars: Math.max(n, old ? old.stars : 0), times: (old ? old.times : 0) + 1 };
    store.notes += result.notes || 0;
    if (result.real) store.flags.real = true;
    if (c.concert) {
      store.flags.concert = true;
      if (result.accuracy >= 1) store.flags.perfect = true;
    }
    const out = addPoints(store, xp, today);
    out.stars = n;
    out.best = store.lessons[id].stars;
    out.firstTime = !old;
    out.levelBefore = level(store.xp - xp).level;
    out.level = level(store.xp).level;
    out.badges = award(store, { xmas: typeof c.xmas === 'function' ? c.xmas(store) : 0 }, today);
    return out;
  }

  /* A song played from the song list: fewer points than a lesson. */
  function finishSong(store, id, result, today, ctx) {
    const c = ctx || {};
    const n = stars(result.accuracy);
    const old = store.songs[id];
    store.songs[id] = {
      stars: Math.max(n, old ? old.stars : 0),
      best: Math.max(result.accuracy, old && old.best ? old.best : 0),
      times: (old ? old.times : 0) + 1,
    };
    store.notes += result.notes || 0;
    if (result.real) store.flags.real = true;
    const out = addPoints(store, 4 + 2 * n, today);
    out.stars = n;
    out.best = store.songs[id].stars;
    out.levelBefore = level(store.xp - out.xp).level;
    out.level = level(store.xp).level;
    out.badges = award(store, { xmas: typeof c.xmas === 'function' ? c.xmas(store) : 0 }, today);
    return out;
  }

  return {
    matches, createWait, createTempo, stars, WINDOW, RING_MS, HINT_AFTER,
    dayKey, addDays, SETTINGS, blank, validate, streakNow, week, level, totalStars,
    BADGES, award, lessonXp, finishLesson, finishSong,
  };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = PN_GAME;
