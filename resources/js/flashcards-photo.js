/* ==========================================================================
   GLOSOR - WORDS FROM A PICTURE

   A photo of this week's words, or a screenshot of them, becomes lines for
   the list editor: "hund = dog", Swedish first, whichever way round the
   sheet has them. Tesseract reads the picture here in the browser, and the
   picture is never sent anywhere.

     - THE READER is tesseract.js (Apache-2.0) with Tesseract's own models
       for Swedish, English and Spanish. Its files come from jsDelivr on
       first use - 4 MB for the program and 2-3 MB a language - pinned to a
       version and checked against their SHA-384 before any of them is run
       or read, as the site's other libraries are. The worker is started
       from one blob holding the core and tesseract.js's worker script, and
       the page hands it its language files, so nothing it runs or reads
       comes unchecked from the net.
     - THE PICTURE is scaled to a size Tesseract reads well, made grey and
       evened out, so that the shadow of the phone over half the sheet does
       not swallow the words in it.
     - THE LAYOUT puts the words Tesseract found back into the rows and
       columns of the list. It is pure, and tested in Node
       (resources/tests/flashcards/test-photo.js).
   ========================================================================== */

const FC_PHOTO = (() => {
  'use strict';

  /* eslint-disable-next-line global-require */
  const W = typeof FC_WORDS !== 'undefined' ? FC_WORDS : require('./flashcards-words.js');

  /* ── The layout: words back into the rows and columns of the list ────── */

  function median(values) {
    if (!values.length) return 0;
    const s = [...values].sort((a, b) => a - b);
    const m = s.length >> 1;
    return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
  }

  /* A word that only separates the two sides of a pair: hund = dog, dog – hund. */
  const SEPARATOR = /^(?:[=:;]+|[-–—]+|→|->|=>)$/u;
  /* What the lines of a table, a bullet or a speck of dirt are read as. */
  const JUNK = /^[|¦[\]{}_•·*°'"“”‘’`´,.~^]+$/u;
  /* A number or a letter in front of an entry: 1.  12)  (3)  a)  b. */
  const NUMBERED = /^(?:\(?\d{1,3}[.):]\)?|[a-zA-Z][.)])$/u;
  const BARE_NUMBER = /^\d{1,3}$/u;
  const GLUED = /^(\d{1,3})(?=\p{L})/u;
  /* Pronunciation, which some books print between the word and its translation. */
  const PHONETIC = /^\[.*\]$|^\/.+\/$/u;

  /**
   * A word as Tesseract read it, tidied: ligatures and odd spaces folded,
   * table lines (|) taken out. "|" would split the word into alternatives
   * in the editor, and is never part of a word in a list.
   */
  function tidy(text) {
    return String(text ?? '').normalize('NFKC').replace(/[|¦]/g, ' ').replace(/[’‘`´]/g, "'").replace(/\s+/g, ' ').trim();
  }

  /**
   * A word with a separator stuck to it - "hund=dog", "dog–", ":hund" - as
   * the words and separators it holds, each with its share of the box.
   * Hyphens inside a word (T-shirt, twenty-one) are part of it.
   */
  function unglue(w) {
    const parts = w.text.split(/(=+|;+|^[-–—]+|[-–—]+$|:+$|^:+)/u).filter(Boolean);
    if (parts.length < 2) return [w];
    const per = (w.x1 - w.x0) / w.text.length;
    let at = w.x0;
    return parts.map((text) => {
      const x0 = at;
      at += per * text.length;
      return { ...w, text, x0, x1: at };
    });
  }

  /* The side of a cell: no stray punctuation at its ends, but "?", "!" and "…" stay. */
  function sideText(words) {
    return words.map(w => w.text).join(' ').replace(/\s+/g, ' ')
      .replace(/^[\s,;:.·•*_~"“”'-]+/u, '').replace(/[\s,;:·•*_~"“”'-]+$/u, '').replace(/\s+\.$/u, '').trim();
  }

  const hasLetter = s => /\p{L}/u.test(s);

  /* A line of a paragraph beside the list, not one side of a pair: a
     phrase to learn is rarely seven words or forty letters long. */
  function isProse(cell) {
    const t = sideText(cell.words);
    return t.split(' ').length >= 7 || t.length >= 40;
  }

  /* Column headings: language names give the order of the columns; the
     others are only headings. */
  const LANG_NAMES = {
    sv: ['svenska', 'swedish', 'sueco', 'svensk'],
    en: ['engelska', 'english', 'ingles', 'engelsk', 'eng'],
    es: ['spanska', 'spanish', 'espanol', 'castellano', 'spansk', 'esp'],
  };
  const HEADINGS = ['ord', 'glosa', 'glosor', 'oversattning', 'word', 'words', 'translation', 'palabra', 'palabras', 'traduccion'];
  const headingWord = s => W.stripAccents(W.normalize(s));
  function langOfHeading(s) {
    const t = headingWord(s);
    for (const [l, names] of Object.entries(LANG_NAMES)) if (names.includes(t)) return l;
    return null;
  }
  const isHeading = s => !!langOfHeading(s) || HEADINGS.includes(headingWord(s));

  /* ── Which side is Swedish ─────────────────────────────────────────────── */

  const ARTICLES = { sv: ['en', 'ett', 'att'], en: ['a', 'an', 'the', 'to'], es: ['el', 'la', 'los', 'las', 'un', 'una', 'unos', 'unas'] };

  function bare(text, l) {
    const n = W.normalize(text);
    const parts = n.split(' ');
    return parts.length > 1 && ARTICLES[l].includes(parts[0]) ? parts.slice(1).join(' ') : n;
  }

  /* Every word of the page's own themes, by language: a word found there
     tells which side it is on. */
  let known = null;
  function knownWords() {
    if (known) return known;
    known = { sv: new Set(), en: new Set(), es: new Set() };
    for (const g of W.GROUPS) {
      for (const t of g.topics) {
        for (const word of t.words || []) {
          for (const l of ['sv', 'en', 'es']) if (word[l]) for (const a of W.alternatives(word[l])) known[l].add(bare(a, l));
        }
      }
    }
    return known;
  }

  /**
   * What tells the language of one side of a pair: points for Swedish and
   * points for the other language. å, ä and ö count most; then en, ett and
   * att against a, the and to (or el and la); then the page's own words, and
   * a few spellings Swedish hardly has.
   *
   * @param {string} text
   * @param {'en'|'es'} lang - the other language
   * @returns {{sv: number, x: number}}
   */
  function cues(text, lang) {
    const t = W.normalize(text);
    const out = { sv: 0, x: 0 };
    if (!t) return out;
    if (/[åäö]/u.test(t)) out.sv += 3;
    const words = t.split(' ');
    if (words.length > 1 && ARTICLES.sv.includes(words[0])) out.sv += 2;
    if (words.length > 1 && ARTICLES[lang].includes(words[0])) out.x += 2;
    /* Not é: Swedish has idé and kafé. */
    if (lang === 'es' && /[ñáíóúü¿¡]/u.test(String(text).toLowerCase())) out.x += 3;
    if (lang === 'en' && /[wq]|th|sh|ee|oo|ou|igh/u.test(t)) out.x += 1;
    const k = knownWords();
    const sv = k.sv.has(bare(t, 'sv')), x = k[lang].has(bare(t, lang));
    if (sv && !x) out.sv += 2;
    else if (x && !sv) out.x += 2;
    return out;
  }

  /**
   * How Swedish one side of a pair looks: above zero Swedish, below zero
   * the other language.
   *
   * @param {string} text
   * @param {'en'|'es'} lang
   * @returns {number}
   */
  function swedishness(text, lang) {
    const c = cues(text, lang);
    return c.sv - c.x;
  }

  /* Words as layout() wants them: tidied, junk dropped, separators stuck to
     a word set apart. */
  function wordsOf(line) {
    const words = [];
    for (const raw of (line && line.words) || []) {
      const w = {
        text: tidy(raw.text), conf: Number(raw.conf) || 0,
        x0: Number(raw.x0), x1: Number(raw.x1), y0: Number(raw.y0), y1: Number(raw.y1),
      };
      if (!w.text || JUNK.test(w.text) || ![w.x0, w.x1, w.y0, w.y1].every(Number.isFinite) || w.x1 < w.x0 || w.y1 < w.y0) continue;
      words.push(...unglue(w));
    }
    return words.sort((a, b) => a.x0 - b.x0);
  }

  const meanConf = ws => (ws.length ? ws.reduce((n, w) => n + w.conf, 0) / ws.length : 0);

  /* Swedish letters as plain ones, for comparing two readings of a word. */
  const plainLetters = t => t.toLocaleLowerCase('sv').replace(/[åä]/gu, 'a').replace(/ö/gu, 'o').replace(/\s+/gu, ' ');
  const SWEDISH = /[åäöÅÄÖ]/gu;

  /**
   * The Swedish side from the reading in both languages (both), with the
   * dots and rings the reading in Swedish alone (swedish) saw: that one is
   * taken when it has more å, ä and ö and is otherwise the same word, or one
   * letter from it - "6sregnade" is "ösregnade". Anything else it reads
   * differently, the reading in both languages knows better.
   */
  function restore(both, swedish) {
    if (!swedish || swedish === both) return both;
    const more = (swedish.match(SWEDISH) || []).length > (both.match(SWEDISH) || []).length;
    return more && W.levenshtein(plainLetters(swedish), plainLetters(both)) <= 1 ? swedish : both;
  }

  /* The size of the writing, from a word's height and the shapes of its
     letters: "ko" and "gris" in the same writing are boxes of different
     heights, a heading's words are larger than both would be. */
  const TOP = /[A-ZÅÄÖ0-9bdfhklt!?åäöáéíóúàèìòùâêîôûñüïçÁÉÍÓÚÑ'"]/u;
  const BOTTOM = /[gjpqyç,;]/u;
  function size(w) {
    if (!/[\p{L}\p{N}]/u.test(w.text)) return 0;
    return (w.y1 - w.y0) / ((TOP.test(w.text) ? 0.72 : 0.5) + (BOTTOM.test(w.text) ? 0.23 : 0));
  }

  /* A heading that names the week: "Glosor vecka 42", "v. 42", "Week 42". */
  const WEEK = W.WEEK;

  /**
   * The words of a list, read off a picture, as pairs.
   *
   * Tesseract gives words with their boxes, grouped into lines - across the
   * whole page, or a column at a time, as it sees the page. The words are
   * put back into rows by height, a row into cells at its wide gaps and at
   * separators (= – :), and two cells make a pair. A row of the list that
   * came out as one cell is split where the right-hand column starts, which
   * the other rows show; that catches a long word that left little room
   * before its translation. Two lists side by side are four columns, two
   * pairs a row. A line in larger writing is a heading, never a pair.
   *
   * The pairs are then turned Swedish first: by the column headings when
   * the sheet has them, else by how Swedish each column looks.
   *
   * The picture may have been read twice: the rows and cells come from the
   * first reading (lines), and one side of each pair is the second
   * reading's words in the same place (opts.second). By default the first
   * reading is in Swedish alone and the second in the other language alone
   * (Spanish); with opts.secondIs 'sv' the first is in both languages and
   * the second in Swedish alone, for the Swedish side (English). Which
   * reading was the surer of each column helps tell which column is Swedish.
   *
   * @param {{words: {text: string, conf: number, x0: number, y0: number, x1: number, y1: number}[]}[]} lines
   * @param {{lang?: 'en'|'es', second?: Object[], secondIs?: 'sv'|'x'}} [opts]
   * @returns {{pairs: {sv: string, x: string, conf: number}[], skipped: string[], headings: string[],
   *   swapped: boolean, byHeading: boolean, name: string, holes: number}}
   *   pairs: Swedish first, conf the least sure word's confidence (0-100);
   *   skipped: the lines that made no pair; headings: the sheet's title and
   *   column headings, which make no pair either; swapped: the other language came
   *   first on the sheet; byHeading: the column headings said so; name:
   *   "Vecka 42" from a heading; holes: words without their pair, and rows
   *   missing from the list.
   */
  function layout(lines, opts = {}) {
    const lang = opts.lang === 'es' ? 'es' : 'en';
    const out = { pairs: [], skipped: [], headings: [], swapped: false, byHeading: false, name: '', holes: 0 };

    const ls = [];
    for (const line of lines || []) {
      const words = wordsOf(line);
      if (!words.length) continue;
      const y0 = Math.min(...words.map(w => w.y0)), y1 = Math.max(...words.map(w => w.y1));
      ls.push({ words, x0: words[0].x0, x1: Math.max(...words.map(w => w.x1)), y0, y1, cy: (y0 + y1) / 2, h: Math.max(1, y1 - y0) });
    }
    if (!ls.length) return out;
    /* Each word numbered, so that a copy of it (a number cut off its front)
       is still known as the same word. */
    let id = 0;
    for (const l of ls) for (const w of l.words) w.id = id++;
    const second = (opts.second || []).flatMap(wordsOf).filter(w => !SEPARATOR.test(w.text));
    /* Which reading is which: by default the first is in Swedish and the
       second in the other language; with secondIs 'sv' the second is the
       one in Swedish alone. */
    const svSecond = opts.secondIs === 'sv';
    const svOf = d => (svSecond ? { text: restore(d.s, d.x), conf: d.confX, min: d.minS } : { text: d.s, conf: d.confS, min: d.minS });
    const xOf = d => (svSecond ? { text: d.s, conf: d.confS, min: d.minS } : { text: d.x, conf: d.confX, min: d.minX });

    /* The size of the writing - from words of two letters or more, since a
       table line read as a letter can be as tall as the table - and of a
       space between two words. */
    const tall = w => (w.text.match(/\p{L}/gu) || []).length >= 2;
    const H = median(ls.flatMap(l => l.words).filter(tall).map(w => w.y1 - w.y0)) || median(ls.map(l => l.h));
    const body = median(ls.flatMap(l => l.words).map(size).filter(Boolean)) || H;
    const gaps = [];
    for (const l of ls) for (let i = 1; i < l.words.length; i++) if (!SEPARATOR.test(l.words[i].text)) gaps.push(l.words[i].x0 - l.words[i - 1].x1);
    /* Only gaps narrower than the writing is high: Tesseract may have read
       a whole row as one line, the gap between the columns in it. */
    const space = median(gaps.filter(g => g > 0 && g < H)) || H / 3;
    const wide = Math.max(2.5 * space, 0.9 * H);
    const tol = 1.2 * H;

    /* Rows: lines at the same height that do not overlap side by side are
       one row - the two columns of a list that Tesseract read apart. */
    const rows = [];
    for (const l of ls.slice().sort((a, b) => a.cy - b.cy)) {
      let best = null;
      for (const r of rows.slice(-8)) {
        const d = Math.abs(r.cy - l.cy);
        if (d < 0.6 * Math.min(r.h, l.h) && !r.parts.some(p => p.x0 < l.x1 && l.x0 < p.x1) && (!best || d < best.d)) best = { r, d };
      }
      if (best) {
        best.r.parts.push(l);
        best.r.cy = (best.r.cy * (best.r.parts.length - 1) + l.cy) / best.r.parts.length;
      } else {
        rows.push({ parts: [l], cy: l.cy, h: l.h });
      }
    }
    for (const r of rows) r.parts.sort((a, b) => a.x0 - b.x0);

    /* A numbered list: bare numbers in front count as numbering only when
       most rows have one. A number can be read stuck to the word after it:
       "2a champion" as "2a", "2 imonerad" as "2imonerad". */
    const leading = (ws) => {
      if (!ws.length) return null;
      const t = ws[0].text;
      if (ws.length > 1 && (BARE_NUMBER.test(t) || NUMBERED.test(t))) return parseInt(t.replace(/\D/g, ''), 10);
      const m = GLUED.exec(t);
      return m ? Number(m[1]) : null;
    };
    const firstWords = rows.map(r => r.parts.flatMap(p => p.words));
    const numbered = firstWords.filter(ws => leading(ws) !== null).length > rows.length / 2;

    /* Cells: a row cut at separators, at wide gaps and where two lines meet.
       Whether a gap cut it matters for finding the columns below. */
    const cellRows = rows.map((r) => {
      const cells = [];
      let cur = null, prev = null, first = true, byGap = false;
      for (const part of r.parts) {
        part.words.forEach((w, i) => {
          if (first) {
            first = false;
            const more = part.words.length > 1 || r.parts.length > 1;
            if (more && (NUMBERED.test(w.text) || (numbered && BARE_NUMBER.test(w.text)))) return;
            const glued = numbered && GLUED.exec(w.text);
            if (glued) {
              const cut = glued[1].length / w.text.length;
              w = { ...w, text: w.text.slice(glued[1].length), x0: w.x0 + cut * (w.x1 - w.x0) };
            }
          }
          if (SEPARATOR.test(w.text)) { cur = null; prev = w; return; }
          if (PHONETIC.test(w.text)) { prev = w; return; }
          const gap = prev ? w.x0 - prev.x1 : 0;
          const lineBreak = i === 0 && !!prev;
          if (!cur || lineBreak || gap > wide) {
            if (cur && (lineBreak || gap > wide)) byGap = true;
            cur = { words: [], x0: w.x0 };
            cells.push(cur);
          }
          cur.words.push(w);
          prev = w;
        });
      }
      const sizes = r.parts.flatMap(p => p.words).map(size).filter(Boolean);
      const big = sizes.length > 0 && median(sizes) > 1.25 * body;
      const text = r.parts.flatMap(p => p.words).map(w => w.text).join(' ');
      const kept = cells.filter(c => sideText(c.words));
      const prose = kept.filter(isProse);
      const num = numbered ? leading(r.parts.flatMap(p => p.words)) : null;
      return { cells: kept.filter(c => !isProse(c)), prose, byGap, big, week: WEEK.test(text), cy: r.cy, num };
    });

    /* Headings: larger writing above the list, or a line that names the
       week. Larger writing further down is a word in a bigger hand, and a
       line cut by wide gaps into pairs is a row of the list in any size. */
    let seenPair = false;
    for (const cr of cellRows) {
      const listLike = cr.byGap && cr.cells.length >= 2 && cr.cells.length % 2 === 0 && !cr.prose.length;
      cr.heading = (cr.big && !seenPair && !listLike) || cr.week;
      if (!cr.heading && cr.cells.length >= 2) seenPair = true;
    }

    /* The columns: where the cells of rows cut by wide gaps start. Rows cut
       by a dash or an equals sign say nothing about columns. */
    const multi = cellRows.filter(cr => cr.byGap && cr.cells.length >= 2 && !cr.heading);
    const starts = multi.flatMap(cr => cr.cells.map(c => c.x0)).sort((a, b) => a - b);
    const clusters = [];
    for (const x of starts) {
      const last = clusters[clusters.length - 1];
      if (last && x - last.xs[last.xs.length - 1] <= tol) last.xs.push(x);
      else clusters.push({ xs: [x] });
    }
    const cols = clusters.filter(c => c.xs.length >= Math.max(2, 0.3 * multi.length)).map(c => median(c.xs));
    /* The column a cell starting at x is in; -1 well left of them all. */
    const colOf = (x) => {
      let k = cols.length && x < cols[0] - tol ? -1 : 0;
      cols.forEach((c, i) => { if (x >= c - tol) k = i; });
      return k;
    };
    /* The list itself: from the first row that is a pair to the last, and
       a row just above or below them at the list's own spacing - the first
       row may be the one that needs splitting. */
    const listRows = cellRows.map((cr, i) => (cr.cells.length >= 2 && !cr.heading ? i : -1)).filter(i => i >= 0);
    const listStep = median(listRows.slice(1).map((r, i) => cellRows[r].cy - cellRows[listRows[i]].cy).filter(d => d > 0)) || 2 * H;
    const inList = (i) => {
      if (!listRows.length || cellRows[i].heading) return false;
      const first = listRows[0], last = listRows[listRows.length - 1];
      if (i >= first && i <= last) return true;
      return (i === first - 1 && cellRows[first].cy - cellRows[i].cy <= 1.4 * listStep)
        || (i === last + 1 && cellRows[i].cy - cellRows[last].cy <= 1.4 * listStep);
    };

    /* One cell that spans where a column starts: split it there, if both
       sides are short enough to be words of a list and not a sentence. */
    function splitAtColumn(cell) {
      if (cols.length < 2) return null;
      const ws = cell.words;
      for (let i = 1; i < ws.length; i++) {
        const k = cols.findIndex((c, j) => j > 0 && Math.abs(ws[i].x0 - c) <= tol);
        if (k > 0 && ws[i - 1].x1 < cols[k] && i <= 5 && ws.length - i <= 5) {
          return [{ words: ws.slice(0, i), x0: ws[0].x0 }, { words: ws.slice(i), x0: ws[i].x0 }];
        }
      }
      return null;
    }

    /* A side as both readings have it, if the picture was read twice:
       each word of the second reading goes with the nearest word of the
       first on the same line, and a side's second reading is the words
       that go with its own. Boxes alone would not do: the second reading
       may see a word the first did not (a narrow "I"), and Tesseract can
       give a word a box that reaches over the next ("nej" over "= no"). */
    const pad = 0.3 * H;
    const matched = new Map();
    const readFirst = ls.flatMap(l => l.words);
    for (const x of second) {
      const cx = (x.x0 + x.x1) / 2, cy = (x.y0 + x.y1) / 2;
      let best = null, far = 3 * H;
      for (const w of readFirst) {
        if (Math.abs((w.y0 + w.y1) / 2 - cy) > 0.6 * H) continue;
        const d = Math.abs((w.x0 + w.x1) / 2 - cx);
        if (d < far) { far = d; best = w; }
      }
      if (best) {
        if (!matched.has(best.id)) matched.set(best.id, []);
        matched.get(best.id).push(x);
      }
    }
    function side(c) {
      const ws = c.words;
      const there = ws.flatMap(w => matched.get(w.id) || []).sort((a, b) => a.x0 - b.x0);
      const s = sideText(ws);
      /* The list's number, which the first reading's side has lost already. */
      let x = there.length ? sideText(there) : s;
      if (!/^\d/u.test(s)) x = x.replace(/^\(?\d{1,3}[.):]?\)?\s*(?=\p{L})/u, '');
      return { s, x: x || s, confS: meanConf(ws), confX: there.length ? meanConf(there) : meanConf(ws),
        minS: Math.min(...ws.map(w => w.conf)), minX: there.length ? Math.min(...there.map(w => w.conf)) : Math.min(...ws.map(w => w.conf)) };
    }

    /* The columns the list's pairs are in: those that rows of two cells
       pair most often. A row of three cells keeps the two in them, and the
       third is something beside the list - a line of a paragraph, a page
       number. */
    const pairedCols = new Map();
    for (const cr of cellRows) {
      if (cr.heading || cr.cells.length !== 2 || cols.length < 2) continue;
      const key = `${colOf(cr.cells[0].x0)},${colOf(cr.cells[1].x0)}`;
      pairedCols.set(key, (pairedCols.get(key) || 0) + 1);
    }
    const mainPair = [...pairedCols.entries()].sort((a, b) => b[1] - a[1])[0];
    const pairCols = mainPair ? mainPair[0].split(',').map(Number) : null;

    /* In a numbered list, the list runs from its first number to its last:
       not what comes before 1 (the clock of a phone's screenshot), nor 66
       in "66 ord · 325 tecken" under a list of ten. */
    let fromRow = -1, toRow = -1;
    if (numbered) {
      const limit = cellRows.filter(cr => Number.isInteger(cr.num)).length + 5;
      cellRows.forEach((cr, i) => {
        if (Number.isInteger(cr.num) && cr.num >= 1 && cr.num <= limit) {
          if (fromRow < 0) fromRow = i;
          toRow = i;
        }
      });
    }
    const outside = i => fromRow >= 0 && (i < fromRow || i > toRow);

    /* A speck read as a letter, away from the columns: not a word. A word
       of one letter (ö, a) starts where its column does. */
    const speck = c => c.words.length === 1 && [...c.words[0].text].length === 1 && cols.length >= 2
      && !cols.some(x => Math.abs(c.x0 - x) <= tol);

    const found = [];
    let lone = 0;
    cellRows.forEach(({ cells, prose, heading }, rowIndex) => {
      for (const c of prose) out.skipped.push(sideText(c.words));
      let cs = cells.filter(c => !speck(c));
      if (heading) cs = [{ words: cells.flatMap(c => c.words), x0: cells.length ? cells[0].x0 : 0 }];
      else if (cs.length === 1 && inList(rowIndex)) cs = splitAtColumn(cs[0]) || cs;
      else if (cs.length > 2 && cs.length % 2 && pairCols && cols.length < 4
        && pairCols.every(k => cs.some(c => colOf(c.x0) === k))) {
        for (const c of cs) if (!pairCols.includes(colOf(c.x0))) out.skipped.push(sideText(c.words));
        cs = pairCols.map(k => ({ words: cs.filter(c => colOf(c.x0) === k).flatMap(c => c.words), x0: cs.find(c => colOf(c.x0) === k).x0 }));
      } else if (cs.length > 2 && cs.length % 2 && cols.length >= 2) {
        /* Three cells, say: those starting in the same column belong
           together, if they are near each other; one far to the left of
           the next is something beside the list (a page number). */
        const merged = [];
        for (const c of cs) {
          const k = colOf(c.x0);
          const last = merged[merged.length - 1];
          if (last && last.k === k) {
            const gap = c.x0 - Math.max(...last.words.map(w => w.x1));
            if (gap < 4 * H) last.words.push(...c.words);
            else {
              out.skipped.push(sideText(last.words));
              merged[merged.length - 1] = { k, words: [...c.words], x0: c.x0 };
            }
          } else {
            merged.push({ k, words: [...c.words], x0: c.x0 });
          }
        }
        cs = merged;
      }
      if (cs.length >= 2 && cs.length % 2 === 0) {
        for (let i = 0; i < cs.length; i += 2) {
          const a = side(cs[i]), b = side(cs[i + 1]);
          /* One side may be a number (20 = twenty), not both, and not a
             time or some other string of figures. */
          const plain = t => hasLetter(t) || /^\d{1,4}(?:[.,]\d{1,3})?$/u.test(t);
          if (!(hasLetter(a.s) || hasLetter(b.s)) || !plain(a.s) || !plain(b.s)) {
            out.skipped.push(`${a.s} ${b.s}`.trim());
            continue;
          }
          found.push({ a, b, row: rowIndex, outside: outside(rowIndex), list: cols.length >= 4 ? Math.max(0, colOf(cs[i].x0)) >> 1 : i >> 1 });
        }
      } else {
        const text = cs.map(c => sideText(c.words)).join('  ').trim();
        if (hasLetter(text)) (heading ? out.headings : out.skipped).push(text);
        if (!heading && cs.length === 1 && inList(rowIndex) && cols.length >= 2
          && (!pairCols || pairCols.includes(colOf(cs[0].x0)))) lone += 1;
      }
    });

    /* Holes in the list: a word in it without its pair, or rows missing -
       a gap where the list's spacing says a row should be. */
    const ys = cellRows.filter((cr, i) => inList(i)).map(cr => cr.cy);
    const steps = ys.slice(1).map((y, i) => y - ys[i]);
    const step = median(steps);
    out.holes = lone + steps.filter(d => step > 0 && d > 1.7 * step).length;

    /* Column headings: taken out, and their language names give the order. */
    let order = 0;
    const pairs = [];
    for (const p of found) {
      if ((isHeading(p.a.s) || isHeading(p.a.x)) && (isHeading(p.b.s) || isHeading(p.b.x))) {
        const la = langOfHeading(p.a.s) || langOfHeading(p.a.x), lb = langOfHeading(p.b.s) || langOfHeading(p.b.x);
        if (la === 'sv' && lb && lb !== 'sv') order = 1;
        else if (lb === 'sv' && la && la !== 'sv') order = -1;
        out.headings.push(`${p.a.s}  ${p.b.s}`);
        continue;
      }
      if (p.outside) { out.skipped.push(`${p.a.s}  ${p.b.s}`); continue; }
      pairs.push(p);
    }
    if (order) {
      out.byHeading = true;
      out.swapped = order < 0;
    } else {
      /* Each side: its Swedish signs as the Swedish reading has them, its
         other signs as the other reading has them, and how much surer the
         Swedish reading was of it. */
      const lean = (d) => {
        const sv = cues(svOf(d).text, lang).sv, x = cues(xOf(d).text, lang).x;
        return sv - x + (svOf(d).conf - xOf(d).conf) / 10;
      };
      out.swapped = pairs.reduce((n, p) => n + lean(p.a) - lean(p.b), 0) < 0;
    }
    pairs.sort((p, q) => p.list - q.list || p.row - q.row);
    out.pairs = pairs.map((p) => {
      const [sv, x] = out.swapped ? [p.b, p.a] : [p.a, p.b];
      return { sv: svOf(sv).text, x: xOf(x).text, conf: Math.min(svOf(sv).min, xOf(x).min) };
    });

    /* "Glosor vecka 42", "v. 42", "Week 42": a name for the list. */
    out.name = [...out.headings, ...out.skipped].map(W.weekName).find(Boolean) || '';
    return out;
  }

  /* Two boxes share more than a third of the smaller one. */
  function overlaps(a, b) {
    const ix = Math.min(a.x1, b.x1) - Math.max(a.x0, b.x0), iy = Math.min(a.y1, b.y1) - Math.max(a.y0, b.y0);
    if (ix <= 0 || iy <= 0) return false;
    const area = w => (w.x1 - w.x0) * (w.y1 - w.y0);
    return ix * iy > Math.min(area(a), area(b)) / 3;
  }

  /**
   * The lines of one reading, with the words of another reading that it
   * missed: those where it has no word at all.
   */
  function addMissing(lines, more) {
    const have = (lines || []).flatMap(l => l.words || []);
    const extra = [];
    for (const l of more || []) {
      const words = (l.words || []).filter(w => !have.some(h => overlaps(h, w)));
      if (words.length) extra.push({ words });
    }
    return (lines || []).concat(extra);
  }

  /* A side as the editor reads it: nothing in the Swedish that the editor
     would take for the separator between the two words. */
  const editorSide = s => String(s).replace(/[=;:\t]/g, ' ').replace(/\s[-–—]\s/g, ' ').replace(/\s+/g, ' ').trim();

  /** Pairs as lines for the editor: "hund = dog". */
  function toText(pairs) {
    return pairs.map(p => `${editorSide(p.sv)} = ${String(p.x).replace(/\s+/g, ' ').trim()}`).join('\n');
  }

  /* ── The picture ─────────────────────────────────────────────────────── */

  /* A phone photo of a sheet is scaled down to this, which leaves the words
     about 25-35 pixels high - what Tesseract reads best. A small screenshot
     is scaled up, at most three times. */
  const MAX_SIDE = 2600;
  const MIN_SIDE = 1600;

  /**
   * Grey, from red, green and blue as the eye weighs them.
   *
   * @param {Uint8ClampedArray} rgba
   * @returns {Uint8ClampedArray} one byte a pixel
   */
  function grey(rgba) {
    const out = new Uint8ClampedArray(rgba.length >> 2);
    for (let i = 0, j = 0; j < out.length; i += 4, j++) out[j] = (rgba[i] * 77 + rgba[i + 1] * 150 + rgba[i + 2] * 29) >> 8;
    return out;
  }

  /* One pass of a 3 × 3 median over the grid: smooths, and keeps the edge
     of a shadow where it is. */
  function middle(grid, gw, gh) {
    const out = new Float32Array(grid.length);
    const v = [];
    for (let y = 0; y < gh; y++) {
      for (let x = 0; x < gw; x++) {
        v.length = 0;
        for (let dy = -1; dy <= 1; dy++) {
          const yy = y + dy;
          if (yy < 0 || yy >= gh) continue;
          for (let dx = -1; dx <= 1; dx++) {
            const xx = x + dx;
            if (xx >= 0 && xx < gw) v.push(grid[yy * gw + xx]);
          }
        }
        v.sort((a, b) => a - b);
        out[y * gw + x] = v[v.length >> 1];
      }
    }
    return out;
  }

  /**
   * Even out the light: every pixel divided by the paper around it, so the
   * paper is white everywhere, in the shadow of the phone too, and the
   * writing keeps its contrast. The paper is the brightest thing in each
   * cell of a grid 120 cells across, smoothed by a median, which leaves the
   * sharp edge of a shadow sharp (an average would blur it over the words
   * beside it, and they were lost). Light writing on a dark ground - a
   * screenshot in dark mode, a photo of a screen - is turned negative
   * first (lightText() tells).
   *
   * @param {Uint8ClampedArray} g - one byte a pixel, row by row; changed in place
   * @param {number} w
   * @param {number} h
   * @param {boolean} [negative] - turn it negative first
   * @returns {Uint8ClampedArray} g
   */
  function flatten(g, w, h, negative = false) {
    if (negative) for (let i = 0; i < g.length; i++) g[i] = 255 - g[i];
    const B = Math.max(6, Math.round(Math.max(w, h) / 120));
    const gw = Math.ceil(w / B), gh = Math.ceil(h / B);
    let grid = new Float32Array(gw * gh);
    for (let y = 0; y < h; y++) {
      const row = Math.floor(y / B) * gw;
      for (let x = 0; x < w; x++) {
        const v = g[y * w + x], k = row + Math.floor(x / B);
        if (v > grid[k]) grid[k] = v;
      }
    }
    grid = middle(grid, gw, gh);

    for (let y = 0; y < h; y++) {
      const fy = Math.min(gh - 1, Math.max(0, (y + 0.5) / B - 0.5));
      const y0 = Math.floor(fy), y1 = Math.min(gh - 1, y0 + 1), ty = fy - y0;
      for (let x = 0; x < w; x++) {
        const fx = Math.min(gw - 1, Math.max(0, (x + 0.5) / B - 0.5));
        const x0 = Math.floor(fx), x1 = Math.min(gw - 1, x0 + 1), tx = fx - x0;
        const top = grid[y0 * gw + x0] * (1 - tx) + grid[y0 * gw + x1] * tx;
        const bottom = grid[y1 * gw + x0] * (1 - tx) + grid[y1 * gw + x1] * tx;
        const paper = Math.max(16, (top * (1 - ty) + bottom * ty) * 0.94);
        const i = y * w + x;
        g[i] = (g[i] * 255) / paper;
      }
    }
    return g;
  }

  /**
   * Whether the writing is light on a dark ground: a screenshot in dark
   * mode, a photo of a screen. The ground is the median of each small cell
   * of the picture - writing covers less than half of a cell - and writing
   * is what stands out from it: mostly lighter, or mostly darker. The
   * brightness of the whole picture does not tell: a photo of a dark screen
   * has a light wall around it, a sheet on a dark desk the other way round.
   *
   * @param {Uint8ClampedArray} g - a grey picture, not changed
   * @returns {boolean}
   */
  function lightText(g, w, h) {
    const B = Math.max(8, Math.round(Math.max(w, h) / 60));
    const gw = Math.ceil(w / B), gh = Math.ceil(h / B);
    const ground = new Uint8Array(gw * gh);
    const hist = new Uint32Array(256);
    for (let cy = 0; cy < gh; cy++) {
      for (let cx = 0; cx < gw; cx++) {
        hist.fill(0);
        let n = 0;
        for (let y = cy * B; y < Math.min(h, (cy + 1) * B); y++) {
          for (let x = cx * B; x < Math.min(w, (cx + 1) * B); x++) { hist[g[y * w + x]] += 1; n += 1; }
        }
        let seen = 0, v = 0;
        for (; v < 255; v++) { seen += hist[v]; if (2 * seen >= n) break; }
        ground[cy * gw + cx] = v;
      }
    }
    let light = 0, dark = 0;
    for (let y = 0; y < h; y++) {
      const row = Math.floor(y / B) * gw;
      for (let x = 0; x < w; x++) {
        const d = g[y * w + x] - ground[row + Math.floor(x / B)];
        if (d > 40) light += 1;
        else if (d < -40) dark += 1;
      }
    }
    return light > 1.5 * dark;
  }

  /* The dark pixels of a picture, on a grid about 1000 across. */
  function darkPoints(g, w, h) {
    const step = Math.max(1, Math.ceil(Math.max(w, h) / 1000));
    const xs = [], ys = [];
    for (let y = 0; y < h; y += step) {
      for (let x = 0; x < w; x += step) {
        if (g[y * w + x] < 128) { xs.push(x / step); ys.push(y / step); }
      }
    }
    return { xs, ys, size: Math.ceil((w + h) / step) + 2 };
  }

  /* How sharply the points gather into lines at deg: the sum of the squares
     of the rows they fall in, against points spread evenly over those rows.
     Lines of writing make a few rows full and the rest empty. */
  function sharpness(pts, deg) {
    const a = (deg * Math.PI) / 180, c = Math.cos(a), s = Math.sin(a);
    const bins = new Float64Array(2 * pts.size + 1);
    let lo = Infinity, hi = -Infinity;
    for (let i = 0; i < pts.xs.length; i++) {
      const k = Math.round(pts.ys[i] * c - pts.xs[i] * s) + pts.size;
      bins[k] += 1;
      if (k < lo) lo = k;
      if (k > hi) hi = k;
    }
    let sum = 0;
    for (let i = lo; i <= hi; i++) sum += bins[i] * bins[i];
    return (sum * (hi - lo + 1)) / (pts.xs.length * pts.xs.length);
  }

  function sharpest(pts, from, to, by) {
    let best = from, top = -1;
    for (let d = from; d <= to + 1e-9; d += by) {
      const v = sharpness(pts, d);
      if (v > top) { top = v; best = d; }
    }
    return { deg: best, top };
  }

  /**
   * How far the lines of writing slope, in degrees, clockwise as the
   * picture is drawn: the angle at which the dark pixels, summed along it,
   * make the sharpest rows. Measured on a copy about 1000 pixels across. A
   * photo of a sheet that slopes more than 15 degrees is turned by hand.
   *
   * @param {Uint8ClampedArray} g - an evened-out grey picture, one byte a pixel
   * @param {number} w
   * @param {number} h
   * @returns {number} degrees
   */
  function skewOf(g, w, h) {
    const pts = darkPoints(g, w, h);
    if (pts.xs.length < 50) return 0;
    const coarse = sharpest(pts, -15, 15, 0.5);
    const fine = sharpest(pts, coarse.deg - 0.45, coarse.deg + 0.45, 0.05);
    return Math.round((fine.top > coarse.top ? fine.deg : coarse.deg) * 100) / 100;
  }

  /* The picture as the browser shows it: an <img> turns a photo the way
     the phone held it, as the preview does. */
  async function decode(file) {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.decoding = 'async';
    img.src = url;
    try {
      await img.decode();
    } catch (e) {
      URL.revokeObjectURL(url);
      throw new PhotoError('picture', 'the picture could not be opened');
    }
    return { img, done: () => URL.revokeObjectURL(url) };
  }

  /**
   * The picture made ready for Tesseract: scaled, turned a quarter at a
   * time if asked, straightened, grey and evened out, as a PNG.
   *
   * Straightening matters most for tables: Tesseract takes the lines of a
   * table that slopes by a few degrees for a picture, and finds no words
   * in it at all.
   */
  async function prepare(file, { turn = 0, evenOut = true, straighten = true, maxSide = MAX_SIDE, minSide = MIN_SIDE, scaleBy = 0 } = {}) {
    const { img, done } = await decode(file);
    try {
      const w0 = img.naturalWidth, h0 = img.naturalHeight;
      if (!w0 || !h0) throw new PhotoError('picture', 'the picture is empty');
      const long = Math.max(w0, h0);
      const scale = scaleBy || (long > maxSide ? maxSide / long : long < minSide ? Math.min(3, minSide / long) : 1);
      const q = (((Math.round(turn / 90) % 4) + 4) % 4);

      /* Draw the picture w × h, turned q quarters and then by deg, on a
         white canvas just large enough to hold it, and read it back grey. */
      let negative = false;
      const draw = (w, h, deg) => {
        const a = (deg * Math.PI) / 180;
        const tw = q % 2 ? h : w, th = q % 2 ? w : h;
        const cw = Math.ceil(tw * Math.abs(Math.cos(a)) + th * Math.abs(Math.sin(a)));
        const ch = Math.ceil(tw * Math.abs(Math.sin(a)) + th * Math.abs(Math.cos(a)));
        const canvas = document.createElement('canvas');
        canvas.width = cw;
        canvas.height = ch;
        const ctx = canvas.getContext('2d', { willReadFrequently: true });
        if (!ctx) throw new PhotoError('picture', 'no canvas');
        /* A screenshot may be transparent: on white, as it looked. */
        ctx.fillStyle = '#fff';
        ctx.fillRect(0, 0, cw, ch);
        ctx.imageSmoothingEnabled = true;
        ctx.imageSmoothingQuality = 'high';
        ctx.translate(cw / 2, ch / 2);
        ctx.rotate(a);
        ctx.rotate((q * Math.PI) / 2);
        ctx.drawImage(img, -w / 2, -h / 2, w, h);
        ctx.setTransform(1, 0, 0, 1, 0, 0);
        const data = ctx.getImageData(0, 0, cw, ch);
        const g = grey(data.data);
        return { canvas, ctx, data, g };
      };

      /* Which way round the writing is, and how far it slopes: on a copy
         about 1000 pixels across. */
      let deg = 0;
      {
        const k = Math.min(1, 1000 / long);
        const small = draw(Math.max(1, Math.round(w0 * k)), Math.max(1, Math.round(h0 * k)), 0);
        const sw = small.canvas.width, sh = small.canvas.height;
        small.canvas.width = small.canvas.height = 0;
        if (evenOut) {
          negative = lightText(small.g, sw, sh);
          flatten(small.g, sw, sh, negative);
        }
        const slope = straighten ? skewOf(small.g, sw, sh) : 0;
        if (Math.abs(slope) >= 0.3) deg = -slope;
      }
      const { canvas, ctx, data, g } = draw(Math.max(1, Math.round(w0 * scale)), Math.max(1, Math.round(h0 * scale)), deg);
      if (evenOut) flatten(g, canvas.width, canvas.height, negative);
      for (let i = 0, j = 0; j < g.length; i += 4, j++) {
        data.data[i] = data.data[i + 1] = data.data[i + 2] = g[j];
        data.data[i + 3] = 255;
      }
      ctx.putImageData(data, 0, 0);
      const blob = await new Promise((resolve, reject) => {
        canvas.toBlob(b => (b ? resolve(b) : reject(new PhotoError('picture', 'the picture could not be made ready'))), 'image/png');
      });
      const size = { width: canvas.width, height: canvas.height, straightened: deg, turn: q * 90, negative };
      canvas.width = canvas.height = 0;
      return { blob, ...size };
    } finally {
      done();
    }
  }

  /**
   * A small copy of the picture turned a quarter at a time, for showing
   * which way round it is read.
   *
   * @returns {Promise<Blob>} a JPEG
   */
  async function thumbnail(file, turn = 0, side = 900) {
    const { img, done } = await decode(file);
    try {
      const k = Math.min(1, side / Math.max(img.naturalWidth, img.naturalHeight));
      const w = Math.max(1, Math.round(img.naturalWidth * k)), h = Math.max(1, Math.round(img.naturalHeight * k));
      const q = (((Math.round(turn / 90) % 4) + 4) % 4);
      const canvas = document.createElement('canvas');
      canvas.width = q % 2 ? h : w;
      canvas.height = q % 2 ? w : h;
      const ctx = canvas.getContext('2d');
      ctx.fillStyle = '#fff';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.translate(canvas.width / 2, canvas.height / 2);
      ctx.rotate((q * Math.PI) / 2);
      ctx.drawImage(img, -w / 2, -h / 2, w, h);
      return await new Promise((resolve, reject) => {
        canvas.toBlob(b => (b ? resolve(b) : reject(new PhotoError('picture', 'no thumbnail'))), 'image/jpeg', 0.85);
      });
    } finally {
      done();
    }
  }

  /* ── The reader ──────────────────────────────────────────────────────── */

  class PhotoError extends Error {
    /** @param {'net'|'integrity'|'start'|'picture'|'read'|'cancelled'} kind */
    constructor(kind, message) {
      super(message);
      this.kind = kind;
    }
  }

  const CDN = 'https://cdn.jsdelivr.net/npm/';
  /* Pinned, with the size and SHA-384 of the bytes jsDelivr serves (the
     same as in the npm packages). A new version means new hashes here. */
  const FILES = Object.freeze({
    main: { path: 'tesseract.js@7.0.0/dist/tesseract.min.js', size: 62961, sri: 'sha384-2BQ3U3OdKOb0Uczxqr41I9UvZkzr4V9Hv8uSzMMZAlmhsFClvdZX5wi5fDCzG+tM' },
    worker: { path: 'tesseract.js@7.0.0/dist/worker.min.js', size: 111307, sri: 'sha384-iUyp1FxLBc4DYaSwxT1/G6elMdSh3vvQffNSmMiySoXDpk2XfS9ZcM4RjPSiqiw3' },
    simd: { path: 'tesseract.js-core@7.0.0/tesseract-core-simd-lstm.wasm.js', size: 3899472, sri: 'sha384-1PHRxr8cs/w6IDh6HZYHEHS+Li9cfjahWYKnioD1xvjs7wZD20qpwhD2+ZvhDmHU' },
    plain: { path: 'tesseract.js-core@7.0.0/tesseract-core-lstm.wasm.js', size: 3896484, sri: 'sha384-ljppwjVnA7rpAU/v9enQiR6pXDStaEAYw9I+7ddiEynJcmDNnjHCmcvizBeO3cSA' },
    swe: { path: '@tesseract.js-data/swe@1.0.0/4.0.0_best_int/swe.traineddata.gz', size: 2503095, sri: 'sha384-JNXFtLZnqcV+gO3m9cVbQ+fCplBZogVH+MGEklxcI5gLslfR7JEiYdhzoFEln5oA' },
    eng: { path: '@tesseract.js-data/eng@1.0.0/4.0.0_best_int/eng.traineddata.gz', size: 2952873, sri: 'sha384-JI+fraGAoc5GBGIliuqzHRnP1nJyrukg5ggNSBv/TO+YOVj+6Te6XXQOx7ia10xq' },
    spa: { path: '@tesseract.js-data/spa@1.0.0/4.0.0_best_int/spa.traineddata.gz', size: 2100190, sri: 'sha384-Nl4jdTJ+7q91SQ8A0WIp4FNRfAIM+qWog1iRVJLOqw/E60ZqpbG/wrAmg7Ye4pix' },
  });
  const MODELS = Object.freeze({ en: ['swe', 'eng'], es: ['swe', 'spa'] });

  /*
    How Tesseract is asked to read, as measured on photographed word lists
    (resources/tests/flashcards/test-photo-ui.py):
      - sparse text (page segmentation mode 11): words wherever they are,
        which suits a list in columns far better than reading the page as
        one block of text (6), or as columns of text (3);
      - a resolution of 300 dpi: a picture made on a canvas carries none,
        and without one Tesseract does not find the lines of a table, and
        reads them as letters.
  */
  const SETTINGS = Object.freeze({ tessedit_pageseg_mode: '11', user_defined_dpi: '300' });

  /* WebAssembly SIMD, tested as tesseract.js tests it (wasm-feature-detect). */
  function simd() {
    try {
      return WebAssembly.validate(new Uint8Array([0, 97, 115, 109, 1, 0, 0, 0, 1, 5, 1, 96, 0, 1, 123, 3, 2, 1, 0, 10, 10, 1, 8, 0, 65, 0, 253, 15, 253, 98, 11]));
    } catch (e) {
      return false;
    }
  }

  /** Whether this browser can read a picture at all. */
  function supported() {
    return typeof WebAssembly === 'object' && typeof Worker === 'function' && typeof Blob === 'function'
      && typeof crypto === 'object' && !!crypto.subtle && typeof fetch === 'function';
  }

  /** The files this language needs, in bytes, as the first reading downloads them. */
  function downloadSize(lang) {
    return ['main', 'worker', 'simd', ...MODELS[lang === 'es' ? 'es' : 'en']].reduce((n, k) => n + FILES[k].size, 0);
  }

  async function fetchChecked(name, onBytes) {
    const file = FILES[name];
    const chunks = [];
    let n = 0;
    try {
      const res = await fetch(CDN + file.path, { mode: 'cors', credentials: 'omit' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      if (res.body && res.body.getReader) {
        const stream = res.body.getReader();
        for (;;) {
          const { done, value } = await stream.read();
          if (done) break;
          chunks.push(value);
          n += value.length;
          onBytes(n);
        }
      } else {
        const all = new Uint8Array(await res.arrayBuffer());
        chunks.push(all);
        n = all.length;
        onBytes(n);
      }
    } catch (e) {
      throw new PhotoError('net', `${file.path}: ${e.message}`);
    }
    const bytes = new Uint8Array(n);
    let at = 0;
    for (const c of chunks) { bytes.set(c, at); at += c.length; }
    const digest = new Uint8Array(await crypto.subtle.digest('SHA-384', bytes));
    let bin = '';
    for (const b of digest) bin += String.fromCharCode(b);
    if (`sha384-${btoa(bin)}` !== file.sri) throw new PhotoError('integrity', `${file.path} did not match its SHA-384 and was not used`);
    return bytes;
  }

  function runScript(bytes) {
    return new Promise((resolve, reject) => {
      const url = URL.createObjectURL(new Blob([bytes], { type: 'text/javascript' }));
      const s = document.createElement('script');
      s.src = url;
      s.onload = () => { URL.revokeObjectURL(url); resolve(); };
      s.onerror = () => { URL.revokeObjectURL(url); reject(new PhotoError('start', 'tesseract.js could not be run')); };
      document.head.appendChild(s);
    });
  }

  let reader = null; // { key, ready: Promise<worker>, worker }
  let progressTo = null;

  function onReaderMessage(m) {
    if (!progressTo || !m) return;
    if (m.status === 'recognizing text') progressTo({ stage: 'read', progress: Number(m.progress) || 0 });
    else progressTo({ stage: 'start' });
  }

  /*
    The worker is one blob: a few lines that answer its requests for
    language files with the page's checked copies, then the Tesseract core,
    then tesseract.js's worker script. With the core already there, the
    worker script does not fetch one (getCore looks for TesseractCore
    first), and with fetch answered from the page it fetches nothing else.
    The language files are handed over this way, rather than as data to
    createWorker, because tesseract.js 7 takes such data for the name of
    the language when it starts Tesseract.
  */
  function startReader(langs) {
    const key = langs.join('+');
    if (reader && reader.key === key) return reader.ready;
    release();
    const r = { key, worker: null };
    r.ready = (async () => {
      const core = simd() ? 'simd' : 'plain';
      const names = ['main', 'worker', core, ...langs];
      const total = names.reduce((n, k) => n + FILES[k].size, 0);
      const got = {};
      const bytes = {};
      await Promise.all(names.map(async (k) => {
        bytes[k] = await fetchChecked(k, (n) => {
          got[k] = n;
          if (progressTo) progressTo({ stage: 'download', progress: Object.values(got).reduce((a, b) => a + b, 0) / total, total });
        });
      }));
      if (reader !== r) throw new PhotoError('cancelled', 'cancelled');
      if (typeof Tesseract === 'undefined') await runScript(bytes.main);
      if (progressTo) progressTo({ stage: 'start' });

      const urls = [];
      const blobUrl = (parts, type) => {
        const u = URL.createObjectURL(new Blob(parts, { type }));
        urls.push(u);
        return u;
      };
      const langPath = new URL('glosor-lasaren', location.href).href;
      const files = {};
      for (const l of langs) files[`${langPath}/${l}.traineddata.gz`] = blobUrl([bytes[l]], 'application/gzip');
      const prelude = `/* Glosor: the language files are the page's own, checked copies. */
(() => {
  const files = ${JSON.stringify(files)};
  const fetchFile = self.fetch.bind(self);
  self.fetch = (url) => (Object.prototype.hasOwnProperty.call(files, String(url))
    ? fetchFile(files[String(url)])
    : Promise.reject(new Error('not one of the reader\\'s files: ' + url)));
})();
`;
      const workerPath = blobUrl([prelude, bytes[core], '\n;\n', bytes.worker], 'text/javascript');
      let started = false;
      let failed = () => {};
      const failure = new Promise((_, reject) => { failed = reject; });
      failure.catch(() => {});
      try {
        const worker = await Promise.race([
          Tesseract.createWorker(langs, 1, {
            workerPath, workerBlobURL: false, langPath, cacheMethod: 'none', gzip: true,
            logger: onReaderMessage,
            /* After the start, a failed reading rejects its own promise. */
            errorHandler: (e) => { if (!started) failed(new PhotoError('start', String(e))); },
          }),
          failure,
        ]);
        started = true;
        if (reader !== r) { worker.terminate(); throw new PhotoError('cancelled', 'cancelled'); }
        r.worker = worker;
        r.current = key;
        return worker;
      } finally {
        for (const u of urls) URL.revokeObjectURL(u);
      }
    })();
    r.ready.catch(() => { if (reader === r) reader = null; });
    reader = r;
    return r.ready;
  }

  /** Stop the reader and free its memory; the next reading starts it again. */
  function release() {
    const r = reader;
    reader = null;
    if (r && r.worker) r.worker.terminate();
  }

  let job = null; // the reading under way: { cancel }
  const TOO_LONG = 180000;

  /** Stop the reading under way, if there is one. */
  function cancel() {
    if (job) job.cancel();
  }

  /**
   * Read the words of a list off a picture.
   *
   * @param {Blob} file - a photo or a screenshot
   * @param {Object} [opts]
   * @param {'en'|'es'} [opts.lang] - the other language; Swedish is always read
   * @param {number} [opts.turn] - degrees clockwise, a quarter at a time; without
   *   one, a picture that gives hardly a pair is read turned a quarter either way too
   * @param {boolean} [opts.upright] - false: not that either
   * @param {function({stage: string, progress?: number, total?: number}): void} [opts.onProgress]
   *   stage 'picture', 'download' (progress 0-1 of total bytes), 'start', 'read' (progress 0-1), 'again' (the
   *   second look, progress 0-1), 'turn' (reading it turned, progress 0-1)
   * @param {Object} [opts.tess] - for the tests: psm, rotateAuto, evenOut, maxSide, minSide
   * @returns {Promise<{pairs: {sv: string, x: string, conf: number}[], skipped: string[], headings: string[],
   *   swapped: boolean, byHeading: boolean, name: string, words: number, turn: number}>}
   *   as layout() gives them, and turn: how far the picture was turned to be read
   */
  async function read(file, opts = {}) {
    const lang = opts.lang === 'es' ? 'es' : 'en';
    const onProgress = typeof opts.onProgress === 'function' ? opts.onProgress : () => {};
    const tess = opts.tess || {};
    cancel();
    let stop;
    const stopped = new Promise((_, reject) => { stop = reject; });
    stopped.catch(() => {});
    const me = {
      cancel: () => {
        stop(new PhotoError('cancelled', 'cancelled'));
        release();
      },
    };
    job = me;
    const until = p => Promise.race([p, stopped]);
    /* A worker that dies in the middle of a reading never answers: after
       three minutes the reading is given up. */
    const watchdog = setTimeout(() => {
      stop(new PhotoError('read', 'the reading took too long'));
      release();
    }, TOO_LONG);
    try {
      onProgress({ stage: 'picture' });
      const options = {
        evenOut: tess.evenOut !== false, straighten: tess.straighten !== false,
        maxSide: tess.maxSide || MAX_SIDE, minSide: tess.minSide || MIN_SIDE, scaleBy: tess.scaleBy || 0,
      };
      const turn = opts.turn || 0;
      const picture = await until(prepare(file, { ...options, turn }));
      progressTo = onProgress;
      const worker = await until(startReader(MODELS[lang]));
      /* Spanish: Swedish alone, then Spanish alone - together they mistake
         å and ä for á, and ó for ö. English: both together, which reads
         the English best, then Swedish alone for the Swedish words, whose
         dots and rings the two together now and then lose. */
      const passes = tess.passes || (lang === 'es' ? [['swe'], ['spa']] : [['swe', 'eng'], ['swe']]);
      const secondIs = tess.secondIs || (lang === 'es' ? 'x' : 'sv');

      /* One way of reading the picture: page segmentation mode, and where
         in the progress bar that reading goes. */
      const readAs = async (pic, mode, stage, from, to) => {
        const lines = [];
        for (let i = 0; i < passes.length; i++) {
          const langs = passes[i].join('+');
          if (reader && reader.current !== langs) {
            await until(worker.reinitialize(langs));
            reader.current = langs;
          }
          await until(worker.setParameters({ ...SETTINGS, tessedit_pageseg_mode: mode, ...(tess.params || {}) }));
          progressTo = (m) => {
            if (m.stage !== 'read') { onProgress(m); return; }
            onProgress({ stage, progress: from + ((to - from) * (i + m.progress)) / passes.length });
          };
          try {
            const result = await until(worker.recognize(pic.blob, { rotateAuto: tess.rotateAuto !== false }, { blocks: true, text: false }));
            lines.push(linesOf(result.data.blocks));
          } catch (e) {
            if (e instanceof PhotoError) throw e;
            throw new PhotoError('read', String(e && e.message ? e.message : e));
          }
        }
        return lines;
      };

      /* The picture read, with a second look when the list has holes:
         reading for sparse text now and then leaves out words that are
         plainly there, small ones most, and reading the picture again as
         one block of text finds them. Only the words found only then are
         added. */
      const readPicture = async (pic, stage, from, to) => {
        const first = await readAs(pic, tess.psm ? String(tess.psm) : SETTINGS.tessedit_pageseg_mode, stage, from, to);
        let out = layout(first[0], { lang, second: first[1], secondIs });
        if (out.holes > 0 && tess.secondLook !== false) {
          onProgress({ stage: 'again', progress: 0 });
          const more = await readAs(pic, '6', 'again', 0, 1);
          first[0] = addMissing(first[0], more[0]);
          if (first[1]) first[1] = addMissing(first[1], more[1]);
          out = layout(first[0], { lang, second: first[1], secondIs });
          out.again = true;
        }
        out.words = first[0].reduce((n, l) => n + l.words.length, 0);
        out.turn = pic.turn;
        if (tess.keepLines) out.lines = first[0];
        return out;
      };

      /* More pairs is better; between as many, the surer. */
      const worth = o => o.pairs.length * 100 + (o.pairs.length ? o.pairs.reduce((n, p) => n + p.conf, 0) / o.pairs.length : 0);

      let out = await readPicture(picture, 'read', 0, 1);
      if (!turn && opts.upright !== false && out.pairs.length < 2) {
        /* Hardly a pair: the photo may be on its side. It is read turned a
           quarter either way, and the best of the three readings kept. */
        for (const [i, q] of [[0, 90], [1, 270]]) {
          onProgress({ stage: 'turn', progress: i / 2 });
          const turned = await until(prepare(file, { ...options, turn: q }));
          const o = await readPicture(turned, 'turn', i / 2, (i + 1) / 2);
          if (worth(o) > worth(out)) out = o;
        }
      }
      return out;
    } finally {
      clearTimeout(watchdog);
      if (job === me) job = null;
      progressTo = null;
    }
  }

  /* Tesseract's blocks, paragraphs and lines, as lines of words with boxes. */
  function linesOf(blocks) {
    const out = [];
    for (const b of blocks || []) {
      for (const p of b.paragraphs || []) {
        for (const l of p.lines || []) {
          out.push({
            words: (l.words || []).map(w => ({
              text: w.text, conf: w.confidence, x0: w.bbox.x0, y0: w.bbox.y0, x1: w.bbox.x1, y1: w.bbox.y1,
            })),
          });
        }
      }
    }
    return out;
  }

  return {
    FILES, CDN, MAX_SIDE, MIN_SIDE, PhotoError,
    layout, addMissing, toText, swedishness, flatten, lightText, grey, median, skewOf, prepare, thumbnail,
    supported, downloadSize, read, cancel, release,
    /* For the tests: whether a reading is under way, and the reader's languages. */
    state: () => ({ reading: !!job, reader: reader ? reader.key : null }),
  };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = FC_PHOTO;
