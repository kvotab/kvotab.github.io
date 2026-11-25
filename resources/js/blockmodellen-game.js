/* ==========================================================================
   BLOCKMODELLEN - STARS, DAYS IN A ROW AND WHAT IS REMEMBERED

   The rules of blockmodellen.html apart from the page, so that they can be
   tested in Node (resources/tests/blockmodellen):

     stars          one to three, from the share of the steps done right
                    the first time;
     blank, validate
                    what is kept between visits, and a check of what was
                    read back (localStorage can hold anything);
     solved, finishLesson
                    a problem solved, a lesson done: the counts, the days
                    in a row, the badges.

   Nothing here is hard on the pupil: a lesson cannot be failed, a step can
   be tried again until it is right, and the days in a row only ever say
   how many - a missed day starts the count again at one, without a word.
   ========================================================================== */

const BM_GAME = (() => {
  'use strict';

  function stars(accuracy) {
    return accuracy >= 0.9 ? 3 : accuracy >= 0.7 ? 2 : 1;
  }

  /* The pupil's own day, not Greenwich's: 2026-11-25. */
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
  const KINDS = ['delhel', 'jmf', 'lika', 'ggr', 'sumdiff', 'brak', 'rest', 'fore', 'forh'];

  const SETTINGS = Object.freeze({
    name: '',          // the pupil's name, used in some of the problems
    pron: 'hen',       // what the problems call her: 'hon', 'han' or 'hen'
    speech: true,      // a button that reads the problem aloud, where a Swedish voice exists
    level: 1,          // practice: 1 the first problems of each kind, 2 all of them
  });

  function blank() {
    return {
      v: 1,
      lessons: {},                         // id -> { stars, times }
      types: {},                           // kind -> { tries, right }: answered first, right the first time
      solved: 0,                           // problems solved, in all
      days: {},                            // day -> problems solved that day
      streak: { count: 0, last: null, best: 0 },
      run: { now: 0, best: 0 },            // right the first time, in a row
      badges: {},                          // id -> the day it was earned
      flags: {},                           // steps: the eight steps in order without a slip; built: a model drawn alone; mixed
      settings: Object.assign({}, SETTINGS),
    };
  }

  const count = (v, max) => (Number.isFinite(v) && v >= 0 ? Math.min(max, Math.floor(v)) : 0);
  const isObject = v => !!v && typeof v === 'object' && !Array.isArray(v);
  const ID = /^[\w-]{1,40}$/;

  /* A name for the problems: letters, spaces and hyphens, at most 20. */
  function cleanName(s) {
    if (typeof s !== 'string') return '';
    const t = s.normalize('NFC').replace(/[^\p{L}\p{M} '-]/gu, '').replace(/\s+/g, ' ').trim().slice(0, 20);
    return t ? t[0].toUpperCase() + t.slice(1) : '';
  }

  /* Whatever was stored, made into a store the page can trust. */
  function validate(raw) {
    const s = blank();
    if (!isObject(raw)) return s;
    s.solved = count(raw.solved, 1e7);
    if (isObject(raw.days)) {
      for (const k of Object.keys(raw.days).filter(d => DAY.test(d)).sort().slice(-400)) s.days[k] = count(raw.days[k], 1e5);
    }
    if (isObject(raw.streak)) {
      s.streak.last = typeof raw.streak.last === 'string' && DAY.test(raw.streak.last) ? raw.streak.last : null;
      s.streak.count = s.streak.last ? count(raw.streak.count, 1e5) : 0;
      s.streak.best = Math.max(s.streak.count, count(raw.streak.best, 1e5));
    }
    if (isObject(raw.run)) {
      s.run.now = count(raw.run.now, 1e6);
      s.run.best = Math.max(s.run.now, count(raw.run.best, 1e6));
    }
    if (isObject(raw.lessons)) {
      for (const k of Object.keys(raw.lessons).slice(0, 300)) {
        const e = raw.lessons[k];
        if (!ID.test(k) || !isObject(e)) continue;
        s.lessons[k] = { stars: Math.max(0, Math.min(3, count(e.stars, 3))), times: count(e.times, 1e6) };
      }
    }
    if (isObject(raw.types)) {
      for (const k of KINDS) {
        const e = raw.types[k];
        if (!isObject(e)) continue;
        const tries = count(e.tries, 1e6);
        s.types[k] = { tries, right: Math.min(tries, count(e.right, 1e6)) };
      }
    }
    if (isObject(raw.badges)) {
      for (const k of Object.keys(raw.badges).slice(0, 100)) {
        if (ID.test(k) && typeof raw.badges[k] === 'string' && DAY.test(raw.badges[k])) s.badges[k] = raw.badges[k];
      }
    }
    if (isObject(raw.flags)) {
      for (const k of ['steps', 'built', 'mixed']) if (raw.flags[k] === true) s.flags[k] = true;
    }
    if (isObject(raw.settings)) {
      const t = raw.settings;
      s.settings.name = cleanName(t.name);
      if (['hon', 'han', 'hen'].includes(t.pron)) s.settings.pron = t.pron;
      if (typeof t.speech === 'boolean') s.settings.speech = t.speech;
      if (t.level === 1 || t.level === 2) s.settings.level = t.level;
    }
    return s;
  }

  /* The days in a row as of today: a count that ended before yesterday is over. */
  function streakNow(store, today) {
    const last = store.streak.last;
    if (!last) return 0;
    return last === today || last === addDays(today, -1) ? store.streak.count : 0;
  }

  /* Something was done today: the days in a row go on (or start again). */
  function touch(store, today) {
    const before = streakNow(store, today);
    if (store.streak.last !== today) {
      store.streak.count = before + 1;
      store.streak.last = today;
      store.streak.best = Math.max(store.streak.best, store.streak.count);
    }
    return { before, after: store.streak.count, grew: store.streak.count > before };
  }

  function totalStars(store) {
    let n = 0;
    for (const k of Object.keys(store.lessons)) n += store.lessons[k].stars;
    return n;
  }

  /* The kinds the pupil gets right least often, after a few tries. */
  function weakTypes(store) {
    return Object.keys(store.types)
      .filter(k => store.types[k].tries >= 3 && store.types[k].right / store.types[k].tries < 0.7)
      .sort((a, b) => store.types[a].right / store.types[a].tries - store.types[b].right / store.types[b].tries);
  }

  /* ── Badges ───────────────────────────────────────────────────────────── */

  /*
     Each badge: its name, how it is earned (the text under a badge not yet
     earned), its picture and its test. ctx.units: [{ id, lessons: [ids] }],
     the chapters, which some badges ask about.
  */
  const doneIn = (store, unit) => unit.lessons.some(id => store.lessons[id]);
  const BADGES = [
    { id: 'first', title: 'Första lektionen', how: 'Klara en lektion', icon: 'flag', test: c => Object.keys(c.store.lessons).length >= 1 },
    { id: 'steps', title: 'Stegmästare', how: 'Sätt de åtta stegen i rätt ordning utan fel', icon: 'steps', test: c => !!c.store.flags.steps },
    { id: 'built', title: 'Blockbyggare', how: 'Rita en hel modell själv', icon: 'blocks', test: c => !!c.store.flags.built },
    { id: 'three', title: 'Tre stjärnor', how: 'Få tre stjärnor på en lektion', icon: 'star', test: c => Object.values(c.store.lessons).some(l => l.stars === 3) },
    { id: 'solved10', title: 'Tio lösta', how: 'Lös 10 uppgifter', icon: 'check', test: c => c.store.solved >= 10 },
    { id: 'solved50', title: 'Femtio lösta', how: 'Lös 50 uppgifter', icon: 'check', test: c => c.store.solved >= 50 },
    { id: 'solved150', title: 'Blockmästare', how: 'Lös 150 uppgifter', icon: 'trophy', test: c => c.store.solved >= 150 },
    { id: 'run5', title: 'Fem i rad', how: 'Lös fem uppgifter i rad rätt på första försöket', icon: 'bolt', test: c => c.store.run.best >= 5 },
    { id: 'streak3', title: 'Tre dagar i rad', how: 'Öva tre dagar i rad', icon: 'flame', test: c => c.store.streak.best >= 3 },
    { id: 'streak7', title: 'En hel vecka', how: 'Öva sju dagar i rad', icon: 'flame', test: c => c.store.streak.best >= 7 },
    { id: 'mixed', title: 'Modellväljaren', how: 'Klara en blandad lektion', icon: 'mix', test: c => !!c.store.flags.mixed },
    { id: 'units', title: 'Alla modeller', how: 'Klara minst en lektion i varje kapitel', icon: 'map', test: c => c.units.length > 0 && c.units.every(u => doneIn(c.store, u)) },
    { id: 'brak', title: 'Bråkproffs', how: 'Få tre stjärnor på alla lektioner om bråk', icon: 'pie',
      test: c => { const ids = c.units.filter(u => u.id === 'brak' || u.id === 'rest').flatMap(u => u.lessons); return ids.length > 0 && ids.every(id => c.store.lessons[id] && c.store.lessons[id].stars === 3); } },
    { id: 'stars50', title: 'Stjärnhimmel', how: 'Samla 50 stjärnor', icon: 'star', test: c => totalStars(c.store) >= 50 },
  ];

  /* Badges earned now and not before: marked in the store, and returned. */
  function award(store, today, ctx) {
    const c = { store, units: (ctx && ctx.units) || [] };
    const fresh = [];
    for (const b of BADGES) {
      if (store.badges[b.id]) continue;
      if (b.test(c)) { store.badges[b.id] = today; fresh.push(b); }
    }
    return fresh;
  }

  /* ── What happened ────────────────────────────────────────────────────── */

  /*
     A problem solved. info: { type, counts, first, built } - counts: it
     was answered first (solve or mixed), so it says how well the pupil
     knows its kind; first: right the first time, without help; built: the
     whole model was drawn by the pupil.
  */
  function solved(store, today, info, ctx) {
    const i = info || {};
    store.solved++;
    store.days[today] = (store.days[today] || 0) + 1;
    const days = Object.keys(store.days).sort();
    for (const d of days.slice(0, Math.max(0, days.length - 400))) delete store.days[d];
    const streak = touch(store, today);
    if (i.counts && KINDS.includes(i.type)) {
      const t = store.types[i.type] || (store.types[i.type] = { tries: 0, right: 0 });
      t.tries++;
      if (i.first) t.right++;
      if (i.first) { store.run.now++; store.run.best = Math.max(store.run.best, store.run.now); } else store.run.now = 0;
    }
    if (i.built) store.flags.built = true;
    return { streak, badges: award(store, today, ctx) };
  }

  /* A lesson done: its stars (the best are kept), and what that earned. */
  function finishLesson(store, id, accuracy, today, extra, ctx) {
    const e = extra || {};
    const n = stars(accuracy);
    const old = store.lessons[id];
    store.lessons[id] = { stars: Math.max(n, old ? old.stars : 0), times: (old ? old.times : 0) + 1 };
    if (e.steps) store.flags.steps = true;
    if (e.mixed) store.flags.mixed = true;
    const streak = touch(store, today);
    return { stars: n, best: store.lessons[id].stars, firstTime: !old, streak, badges: award(store, today, ctx) };
  }

  return {
    stars, dayKey, addDays, SETTINGS, KINDS, blank, validate, cleanName, streakNow, touch, totalStars,
    weakTypes, BADGES, award, solved, finishLesson,
  };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = BM_GAME;
