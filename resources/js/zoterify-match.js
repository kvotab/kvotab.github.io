/* ==========================================================================
   ZOTERIFY.HTML: MATCHING CITATIONS TO THE ZOTERO LIBRARY

   For each reference the parser found, the library item it means, and how
   sure that is. A reference is scored against every item whose first
   creator's name begins with the same letter, on three separate things:

     name   how well the cited authors fit the item's creators: the first
            name by Jaro–Winkler similarity of the folded names ("Öhman" and
            "Ohman" are one name), a second cited author against the second
            creator, and the number of names -- "Smith & Jones" fits a
            two-author item better than a one- or five-author one, and
            "Smith et al." does not fit a single author;
     year   the distance between the cited year and the item's, with "n.d."
            fitting an item without a date;
     entry  when the document's own reference list has the entry this
            reference points to, how much of the item's title appears in it.

   A number that names one work comes before all of that: an SKB report
   number ("TR-11-01") found in an item's Report Number, or a designation
   ("SSMFS 2008:37") found in its number or title, whether the citation
   gives it or its reference-list entry does ("SKB, 2011. ... SKB
   TR-11-01"). A citation by number that no item carries is only offered
   items, never matched: "SSMFS 2008:37" is not "SSMFS 2008:21", nor any
   other SKB report of 2011 "TR-11-01". An abbreviated name ("Data report")
   has no author; its entry's title words find it.

   From these a reference is
     matched    one item fits the name and the year, clearly better than any
                other -- or its title is in the reference-list entry and no
                other's is;
     ambiguous  several fit equally well: the user chooses;
     year       nothing fits the year but an item within the year tolerance
                does: the user confirms;
     possible   only looser fits, of any year, to offer;
     none       nothing near.

   The thresholds are calibrated on 500 citations whose true items are
   known, from Word documents already coded with Zotero (see
   resources/tests/zoterify/README.md).
   ========================================================================== */
(function (root, factory) {
  'use strict';
  const api = factory(typeof ZFParse !== 'undefined' ? ZFParse : require('./zoterify-parse.js'));
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.ZFMatch = api;
}(typeof self !== 'undefined' ? self : this, function (ZFParse) {
  'use strict';

  const { fold, reportsIn, designationsIn, designationKey } = ZFParse;

  /* ---------------------------------------------------------------------
     Similarity
     --------------------------------------------------------------------- */

  /** Jaro–Winkler similarity, 0–1, with the usual prefix scale 0.1 over at
      most four characters. */
  function jaroWinkler(a, b) {
    if (a === b) return 1;
    const s = Array.from(a);
    const t = Array.from(b);
    if (!s.length || !t.length) return 0;
    const range = Math.max(0, Math.floor(Math.max(s.length, t.length) / 2) - 1);
    const sFlags = new Uint8Array(s.length);
    const tFlags = new Uint8Array(t.length);
    let matches = 0;
    for (let i = 0; i < s.length; i++) {
      const lo = Math.max(0, i - range);
      const hi = Math.min(t.length - 1, i + range);
      for (let j = lo; j <= hi; j++) {
        if (tFlags[j] || s[i] !== t[j]) continue;
        sFlags[i] = 1;
        tFlags[j] = 1;
        matches++;
        break;
      }
    }
    if (!matches) return 0;
    let transpositions = 0;
    let k = 0;
    for (let i = 0; i < s.length; i++) {
      if (!sFlags[i]) continue;
      while (!tFlags[k]) k++;
      if (s[i] !== t[k]) transpositions++;
      k++;
    }
    const m = matches;
    const jaro = (m / s.length + m / t.length + (m - transpositions / 2) / m) / 3;
    let prefix = 0;
    while (prefix < 4 && prefix < s.length && prefix < t.length && s[prefix] === t[prefix]) prefix++;
    return jaro + prefix * 0.1 * (1 - jaro);
  }

  /** Two names, folded: equal, one the other plus words ("Svensk
      Kärnbränslehantering AB" and "Svensk Kärnbränslehantering"), or as
      similar as Jaro–Winkler says. */
  function nameSimilarity(a, b) {
    if (!a || !b) return 0;
    if (a === b) return 1;
    if (b.startsWith(`${a} `) || a.startsWith(`${b} `)) return 0.97;
    return jaroWinkler(a, b);
  }

  const TITLE_STOP = new Set(['the', 'and', 'for', 'with', 'from', 'into', 'upon', 'about', 'under', 'over', 'between',
    'och', 'med', 'för', 'från', 'till', 'inom', 'samt', 'der', 'die', 'das', 'und', 'mit', 'von', 'les', 'des', 'une',
    'report', 'rapport', 'technical', 'report', 'svensk', 'karnbranslehantering']);

  function titleWords(s) {
    return new Set(fold(s).split(' ').filter((w) => w.length >= 3 && !TITLE_STOP.has(w) && !/^\d+$/.test(w)));
  }

  /** "Intergovernmental Panel on Climate Change" -> "IPCC" */
  function acronymOf(name) {
    const caps = name.split(/\s+/).filter((w) => /^\p{Lu}/u.test(w));
    return caps.length >= 2 ? caps.map((w) => w[0]).join('').toUpperCase() : '';
  }

  /** An item's SKB report numbers: from its number field -- after "SKB"
      unless SKB published it -- and an SKBdoc number from its title. */
  function itemReports(item) {
    const csl = item.csl || {};
    const number = csl.number || '';
    const bySkb = /svensk k[äa]rnbr[äa]nslehantering|^skb$/iu.test([csl.publisher || '', ...item.authors].join('\n'));
    const keys = new Set(reportsIn(number, !bySkb));
    for (const k of reportsIn(item.title || '')) if (k.startsWith('SKBdoc')) keys.add(k);
    return keys;
  }

  /** An item's designations, in every form designationsIn gives. */
  function itemDesignations(item) {
    const csl = item.csl || {};
    const keys = new Set();
    for (const source of [csl.number, item.title, csl['title-short']]) {
      for (const forms of designationsIn(source || '')) for (const k of forms) keys.add(k);
    }
    return keys;
  }

  /* ---------------------------------------------------------------------
     The matcher
     --------------------------------------------------------------------- */

  // Balanced, lenient and strict: the least name similarity for a fit, and
  // how far ahead the best must be to be taken without asking.
  const LEVELS = {
    lenient: { name: 0.86, margin: 0.03 },
    balanced: { name: 0.9, margin: 0.05 },
    strict: { name: 0.94, margin: 0.08 },
  };

  function createMatcher(library, options = {}) {
    const level = LEVELS[options.level] || LEVELS.balanced;
    const tolerance = Number.isInteger(options.yearTolerance) ? options.yearTolerance : 1;

    const prepared = library.map((item) => {
      const names = (item.authors.length ? item.authors : item.editors).map((n) => ({ raw: n, folded: fold(n) }));
      const people = (item.csl && (item.authors.length ? item.csl.author : item.csl.editor)) || [];
      return {
        item,
        names,
        given: people[0] && people[0].given ? Array.from(fold(people[0].given))[0] || '' : '',
        acronyms: new Set(names.map((n) => acronymOf(n.raw)).concat(names.map((n) => (/^\p{Lu}{2,}$/u.test(n.raw) ? n.raw : ''))).filter(Boolean)),
        year: /^\d{4}$/.test(item.year || '') ? Number(item.year) : null,
        title: titleWords(item.title || ''),
        reports: itemReports(item),
        designations: itemDesignations(item),
      };
    });
    const byInitial = new Map();
    const byAcronym = new Map();
    const byReport = new Map();
    const byDesignation = new Map();
    const add = (map, key, p) => { if (!map.has(key)) map.set(key, []); map.get(key).push(p); };
    for (const p of prepared) {
      for (const k of p.reports) add(byReport, k, p);
      for (const k of p.designations) add(byDesignation, k, p);
      if (!p.names.length || !p.names[0].folded) continue;
      add(byInitial, Array.from(p.names[0].folded)[0], p);
      for (const a of p.acronyms) add(byAcronym, a, p);
    }

    /** How the cited authors fit an item's creators, 0–1. */
    function nameFit(authors, aliases, etAl, p) {
      const first = fold(authors[0]);
      let n1 = nameSimilarity(first, p.names[0].folded);
      for (const a of [aliases[0], /^\p{Lu}{2,}$/u.test(authors[0]) ? authors[0] : ''].filter(Boolean)) {
        if (p.acronyms.has(a) || p.names[0].folded === fold(a)) n1 = 1;
      }
      const count = p.names.length;
      if (etAl) return n1 - (count === 1 ? 0.25 : count === 2 ? 0.08 : 0);
      if (authors.length === 1) return n1 - (count === 2 ? 0.06 : count > 2 ? 0.04 : 0);
      const n2 = count > 1 ? nameSimilarity(fold(authors[1]), p.names[1].folded) : 0;
      return 0.7 * n1 + 0.3 * n2 - 0.04 * Math.min(2, Math.abs(count - authors.length));
    }

    /** Distance in years; 0 when both are undated, null when unknown. */
    function yearDistance(ref, p) {
      if (/^\d{4}$/.test(ref.yearKey)) return p.year === null ? null : Math.abs(Number(ref.yearKey) - p.year);
      if (ref.yearKey === 'nd') return p.year === null ? 0 : null;
      return p.year === null || p.year >= new Date().getFullYear() - 2 ? 0 : null; // in press, unpublished
    }

    /** Share of the item's title words found in the reference-list entry. */
    function entryFit(entryWords, p) {
      if (!entryWords || p.title.size < 2) return null;
      let hit = 0;
      for (const w of p.title) if (entryWords.has(w)) hit++;
      return hit / p.title.size;
    }

    /** Items that cannot be the work a number names: any with another SKB
        report number, or another designation of the same name and year. */
    function ruledOut(ref, p) {
      const e = ref.entry || {};
      // An entry's number rules others out only when no item has it: when
      // one does but did not fit the entry, the number is what is in doubt.
      const entryReport = e.report && !byReport.has(e.report);
      const entryDesignation = e.designation && !byDesignation.has(designationKey(e.designation));
      if ((ref.report || entryReport) && p.reports.size) return true;
      const designation = ref.designation || (entryDesignation ? e.designation : '');
      if (!designation) return false;
      const key = designationKey(designation);
      const series = key.slice(0, key.indexOf(':') + 1);
      for (const k of p.designations) if (k.startsWith(series) && k !== key) return true;
      return false;
    }

    function score(ref) {
      let authors = ref.authors;
      let aliases = ref.aliases || [];
      let yearRef = ref;
      if (ref.num !== null) {
        if (!ref.entry || !ref.entry.authors.length) return [];
        authors = ref.entry.authors;
        aliases = [];
        yearRef = ref.entry;
      }
      if (!authors.length) return [];
      const first = fold(authors[0]);
      if (!first) return [];
      const pool = new Set(byInitial.get(Array.from(first)[0]) || []);
      for (const a of [aliases[0], authors[0]]) for (const p of byAcronym.get(a) || []) pool.add(p);
      const entryWords = ref.entry ? titleWords(ref.entry.text) : null;
      // "Vallery C": the initial written after the name against the given name
      const initial = ref.num === null && ref.initials && ref.initials[0] ? Array.from(fold(ref.initials[0]))[0] : '';
      const out = [];
      for (const p of pool) {
        if (ruledOut(ref, p)) continue;
        let name = nameFit(authors, aliases, ref.etAl, p);
        if (initial && p.given) name += p.given === initial ? 0.03 : -0.15;
        if (name < level.name - 0.12) continue;
        const e = entryFit(entryWords, p);
        const bonus = e === null ? 0 : e >= 0.7 ? 0.06 : e < 0.25 ? -0.06 : 0;
        out.push({ item: p.item, name, dy: yearDistance(yearRef, p), entry: e, conf: Math.max(0, Math.min(1, name + bonus)) });
      }
      return out;
    }

    const byConf = (a, b) => (b.conf - a.conf) || ((b.entry || 0) - (a.entry || 0)) || (a.item.itemId - b.item.itemId);
    const candidate = (s) => ({ item: s.item, confidence: s.conf, entryConfirmed: s.entry !== null && s.entry >= 0.7 });

    /** The items carrying the report number or designation the citation or
        its entry gives, or null when none does. A number read from the
        entry is taken only for items whose creators and year fit the
        entry too: the entry may name another report in passing. */
    function byNumber(ref) {
      const e = ref.entry || {};
      const tries = [];
      if (ref.report) tries.push(['report', ref.report, false]);
      if (ref.designation) tries.push(['designation', designationKey(ref.designation), false]);
      if (e.report && e.report !== ref.report) tries.push(['report', e.report, true]);
      if (e.designation && !ref.designation) tries.push(['designation', designationKey(e.designation), true]);
      const fitsEntry = (p) => {
        if (!e.authors || !e.authors.length || !p.names.length) return true;
        if (nameFit(e.authors, [], false, p) < level.name - 0.12) return false;
        const dy = yearDistance(e, p);
        return dy === null || dy <= tolerance;
      };
      for (const [by, key, fromEntry] of tries) {
        const hits = ((by === 'report' ? byReport : byDesignation).get(key) || [])
          .filter((p) => !fromEntry || fitsEntry(p)).sort((a, b) => a.item.itemId - b.item.itemId);
        if (!hits.length) continue;
        const candidates = hits.slice(0, 6).map((p) => ({ item: p.item, confidence: 1, entryConfirmed: false, by }));
        return { ref, status: hits.length === 1 ? 'matched' : 'ambiguous', item: hits[0].item, confidence: 1, entryConfirmed: false, by, candidates };
      }
      return null;
    }

    /** An abbreviated name: the items whose title is in the entry. */
    const titleCache = new Map();
    function byTitle(ref) {
      const e = ref.entry;
      if (!e) return { ref, status: 'none', item: null, confidence: 0, candidates: [] };
      if (titleCache.has(e.text)) return Object.assign({}, titleCache.get(e.text), { ref });
      const words = titleWords(e.text);
      const scored = [];
      for (const p of prepared) {
        if (p.title.size < 3) continue;
        const fit = entryFit(words, p);
        if (fit < 0.5) continue;
        const dy = p.year === null || !/^\d{4}$/.test(e.yearKey) ? null : Math.abs(p.year - Number(e.yearKey));
        scored.push({ item: p.item, entry: fit, dy, conf: fit });
      }
      scored.sort(byConf);
      const exact = scored.filter((s) => s.dy === 0 && s.entry >= 0.8);
      let result;
      if (exact.length && (exact.length === 1 || exact[0].conf - exact[1].conf >= 0.1)) {
        result = { status: 'matched', item: exact[0].item, confidence: exact[0].conf, entryConfirmed: true, candidates: exact.slice(0, 6).map(candidate) };
      } else if (exact.length) {
        result = { status: 'ambiguous', item: exact[0].item, confidence: exact[0].conf, candidates: exact.filter((s) => exact[0].conf - s.conf < 0.1).slice(0, 6).map(candidate) };
      } else if (scored.length) {
        result = { status: 'possible', item: null, confidence: 0, candidates: scored.slice(0, 5).map(candidate) };
      } else {
        result = { status: 'none', item: null, confidence: 0, candidates: [] };
      }
      titleCache.set(e.text, result);
      return Object.assign({}, result, { ref });
    }

    function byName(ref) {
      const scored = score(ref);
      const fits = scored.filter((s) => s.name >= level.name);
      const exact = fits.filter((s) => s.dy === 0).sort(byConf);
      if (exact.length) {
        const [top, second] = exact;
        const confirmed = top.entry !== null && top.entry >= 0.7 && (!second || second.entry === null || second.entry < 0.5);
        if (!second || confirmed || top.conf - second.conf >= level.margin) {
          return { ref, status: 'matched', item: top.item, confidence: top.conf, entryConfirmed: confirmed, candidates: exact.slice(0, 6).map(candidate) };
        }
        const close = exact.filter((s) => top.conf - s.conf < 0.1).slice(0, 6);
        return { ref, status: 'ambiguous', item: top.item, confidence: top.conf, candidates: close.map(candidate) };
      }
      const off = fits.filter((s) => s.dy !== null && s.dy > 0 && s.dy <= tolerance)
        .sort((a, b) => (a.dy - b.dy) || byConf(a, b));
      if (off.length) return { ref, status: 'year', item: off[0].item, confidence: off[0].conf * 0.85, candidates: off.slice(0, 4).map(candidate) };
      const loose = scored.filter((s) => s.name >= level.name - 0.06).sort((a, b) => (b.name - a.name) || ((a.dy === null ? 99 : a.dy) - (b.dy === null ? 99 : b.dy)));
      if (loose.length) return { ref, status: 'possible', item: null, confidence: 0, candidates: loose.slice(0, 5).map(candidate) };
      return { ref, status: 'none', item: null, confidence: 0, candidates: [] };
    }

    function match(ref) {
      const numbered = byNumber(ref);
      if (numbered) return numbered;
      const e = ref.entry || {};
      const own = ref.report || ref.designation;
      const listed = e.report || e.designation;
      const result = ref.abbrev && !(e.authors && e.authors.length) ? byTitle(ref) : byName(ref);
      if (!own && !listed) return result;
      const present = (e.report && byReport.has(e.report)) || (e.designation && byDesignation.has(designationKey(e.designation)));
      let note = `No item in the library has the number ${own}; items by the same name and year are only offered.`;
      if (!own) {
        note = present
          ? `The reference list gives the number ${listed}, but the item with that number has other authors or another year.`
          : `No item in the library has the number ${listed} that the reference list gives.`;
      }
      // A citation by number is not matched to an item without that number.
      if (own && (result.status === 'matched' || result.status === 'ambiguous' || result.status === 'year')) {
        return { ref, status: 'possible', item: null, confidence: 0, candidates: result.candidates, note };
      }
      return Object.assign(result, { note });
    }

    return { match, matchAll: (refs) => refs.map(match) };
  }

  /* ---------------------------------------------------------------------
     Picking an item by hand: every word of the query must occur in the
     creators, year, title or number ("TR-11-01", "SSMFS 2008:21");
     creators count for more, and earlier hits.
     --------------------------------------------------------------------- */
  function searchLibrary(library, query, limit = 8) {
    const words = fold(query).split(' ').filter(Boolean);
    if (!words.length) return [];
    // A report number is looked up as one, not as the words "tr 11 01".
    const reports = reportsIn(query);
    if (reports.length) {
      return library.filter((item) => { const has = itemReports(item); return reports.some((k) => has.has(k)); })
        .sort((a, b) => a.itemId - b.itemId).slice(0, limit);
    }
    const scored = [];
    for (const item of library) {
      const names = fold([...item.authors, ...item.editors].join(' '));
      const hay = `${names} ${item.year || ''} ${fold(item.title || '')} ${fold((item.csl && item.csl.number) || '')}`;
      let score = 0;
      let ok = true;
      for (const w of words) {
        const at = hay.indexOf(w);
        if (at < 0) { ok = false; break; }
        score += (at < names.length ? 3 : 1) + w.length / 10;
      }
      if (ok) scored.push([item, score]);
    }
    return scored.sort((a, b) => (b[1] - a[1]) || (a[0].itemId - b[0].itemId)).slice(0, limit).map(([item]) => item);
  }

  return { createMatcher, searchLibrary, jaroWinkler, nameSimilarity, titleWords, LEVELS };
}));
