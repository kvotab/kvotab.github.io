/* ==========================================================================
   ZOTERIFY.HTML: FINDING CITATIONS AND THE REFERENCE LIST

   Reads paragraph texts and returns the citations in them, grouped as they
   stand in the text: one group per parenthesis, per narrative citation and
   per bracket of numbers. It also finds the reference list and reads its
   entries, so a citation can be tied to the entry it points to.

   How a paragraph is read
   -----------------------
   The text is cut into lexemes -- words, numbers, spaces, punctuation --
   with two kinds merged into single lexemes: years ("2020", "2020a", and
   "n.d.", "u.å.", "in press" ...) and "et al." with its Swedish and German
   forms. Every lexeme keeps its offsets in the text.

   Citations are found from their years. In a parenthesis each year is an
   anchor: the name phrase just before it, read backwards, is its author list
   ("Smith", "Smith & Jones", "van der Berg", "Svensk Kärnbränslehantering
   AB", "Smith et al."), and what follows it may be a locator (", p. 12",
   ": 45–47", ", kap. 3"). A year with no names before it, straight after
   another reference ("Smith 2019, 2020"), belongs to the same authors. A
   parenthesis that begins with a year takes its author from the words in
   front of it -- "Smith (2020)", "Smith et al. (2014, 20; cf. ...)" -- and
   that author is marked to stay in the text.

   Nothing inside a parenthesis is dropped. Words that are not part of a
   reference -- "see", "cf.", "e.g.", or a whole clause -- become the prefix
   of the reference after them or the suffix of the one before, so that a
   Zotero citation built from the group prints them too.

   The reference list begins at a heading ("References", "Referenser",
   "Litteratur" ...) followed by entries or, without one, at a long dense run
   of entries. It ends at the next heading of the same level when the
   document's outline levels are known, otherwise after its last entry. Its
   paragraphs are not searched for citations.

   SKB's reports cite in three more ways, and each is read as a reference
   of its own: by report number ("SKB TR-11-01", "SKB (R-09-20)", "SKBdoc
   1175208"); by designation, where the number after the colon tells one
   regulation or standard from another ("SSMFS 2008:37", "SOU 2010:6",
   "SS-EN 1936:1999") and is not a page; and by an abbreviated name ("Data
   report, Section 6.1") entered under "References with abbreviated names".
   An entry's own report number ("SKB, 2011. Title. SKB TR-11-01, ...") is
   kept with it, and settles which item "(SKB 2011)" means.

   The problem, and the idea of solving it against the local Zotero
   database, come from Identifyer for Zotero by Jonas Bååth; the design, the
   code and the word lists here are this page's own.

   Runs under Node for resources/tests/zoterify/ and in the browser as
   ZFParse. It knows nothing about Word files.
   ========================================================================== */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.ZFParse = api;
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  /* ---------------------------------------------------------------------
     Words
     --------------------------------------------------------------------- */

  // Lower-case name particles: "van der Berg", "de la Cruz", "af Klercker".
  const PARTICLES = new Set(['af', 'al', 'da', 'das', 'de', 'del', 'della', 'den', 'der', 'des', 'di', 'do', 'dos',
    'du', 'el', 'la', 'le', 'lo', 'ten', 'ter', 'van', 'von', 'vom', 'zu', 'zur']);

  // Lower-case words allowed inside an organisation's name, between two
  // capitalised words: "Panel on Climate Change", "Ministry of the Environment".
  const NAME_JOINERS = new Set(['of', 'for', 'on', 'the', 'in', 'at', 'för', 'av', 'i', 'vid', 'für', 'des']);

  // Words that join co-authors.
  const CONNECTORS = new Set(['and', 'och', 'og', 'und', 'et', 'y', 'ja']);

  /* Capitalised words that are never a name: they begin sentences, name
     parts of documents, introduce citations or are months. */
  const NOT_NAMES = new Set([
    // articles, pronouns, determiners
    'A', 'An', 'The', 'This', 'That', 'These', 'Those', 'It', 'Its', 'We', 'Our', 'Us', 'They', 'Their', 'He', 'She',
    'His', 'Her', 'I', 'You', 'Your', 'One', 'Some', 'Any', 'All', 'Each', 'Every', 'Both', 'Many', 'Most', 'Several',
    'Such', 'Other', 'Others', 'Another', 'No', 'None',
    'En', 'Ett', 'Den', 'Det', 'De', 'Detta', 'Denna', 'Dessa', 'Vi', 'Jag', 'Han', 'Hon', 'Hen', 'Man', 'Vår', 'Våra',
    'Deras', 'Alla', 'Varje', 'Båda', 'Många', 'Flera', 'Andra', 'Ingen',
    'Der', 'Die', 'Das', 'Ein', 'Eine', 'Wir', 'Sie', 'Es',
    'Le', 'La', 'Les', 'Un', 'Une', 'El', 'Los', 'Las',
    // words that start sentences
    'In', 'On', 'At', 'By', 'For', 'From', 'To', 'Of', 'With', 'Without', 'Within', 'Into', 'Over', 'Under', 'Above',
    'Below', 'Between', 'Among', 'Through', 'During', 'After', 'Before', 'Since', 'Until', 'Unlike', 'Like', 'As',
    'And', 'Or', 'But', 'Nor', 'Yet', 'So', 'If', 'When', 'Where', 'While', 'Whereas', 'Although', 'Though',
    'Because', 'However', 'Moreover', 'Furthermore', 'Therefore', 'Thus', 'Hence', 'Also', 'Here', 'There', 'Then',
    'Now', 'Recently', 'Previously', 'Earlier', 'Later', 'Finally', 'First', 'Second', 'Third', 'Similarly',
    'Likewise', 'Indeed', 'Notably', 'Accordingly', 'According', 'Following', 'Using', 'Based', 'Given',
    'På', 'Av', 'För', 'Från', 'Till', 'Med', 'Utan', 'Inom', 'Över', 'Mellan', 'Genom', 'Efter', 'Före', 'Innan',
    'Sedan', 'Vid', 'Hos', 'Mot', 'Om', 'Och', 'Eller', 'Men', 'Samt', 'Som', 'När', 'Där', 'Här', 'Då', 'Eftersom',
    'Medan', 'Trots', 'Även', 'Också', 'Dessutom', 'Vidare', 'Slutligen', 'Tidigare', 'Senare', 'Enligt', 'Liksom',
    'Både', 'Exempelvis', 'Alltså', 'Därför', 'Således',
    'Nach', 'Laut', 'Gemäß', 'Bei', 'Mit', 'Von', 'Für', 'Und', 'Oder', 'Aber', 'Auch',
    'Selon', 'Pour', 'Avec', 'Dans', 'Según', 'Para',
    // words that introduce a citation
    'See', 'Cf', 'Compare', 'Contra', 'Eg', 'Ie', 'Viz', 'Ibid', 'Ibidem', 'Op', 'Cit', 'Se', 'Jfr', 'Jämför',
    'Bl', 'Siehe', 'Vgl', 'Voir', 'Ver',
    // parts of documents
    'Table', 'Tables', 'Figure', 'Figures', 'Fig', 'Figs', 'Chapter', 'Chapters', 'Section', 'Sections', 'Appendix',
    'Appendices', 'Annex', 'Page', 'Pages', 'Part', 'Eq', 'Equation', 'Equations', 'Box', 'Note', 'Notes', 'Volume',
    'Tabell', 'Tabeller', 'Figur', 'Figurer', 'Kapitel', 'Avsnitt', 'Bilaga', 'Bilagor', 'Sida', 'Ekvation', 'Del',
    'Abbildung', 'Tabelle', 'Abschnitt', 'Anhang',
    // months and seasons
    'January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November',
    'December', 'Jan', 'Feb', 'Mar', 'Apr', 'Jun', 'Jul', 'Aug', 'Sep', 'Sept', 'Oct', 'Nov', 'Dec',
    'Januari', 'Februari', 'Mars', 'Maj', 'Juni', 'Juli', 'Augusti', 'Oktober', 'Spring', 'Summer', 'Autumn', 'Fall',
    'Winter', 'Våren', 'Sommaren', 'Hösten', 'Vintern',
  ]);

  // Headings a reference list goes under, in lower case without numbering
  // or a trailing colon.
  const LIST_HEADINGS = new Set([
    'references', 'reference list', 'list of references', 'bibliography', 'literature', 'literature cited',
    'cited literature', 'works cited', 'sources', 'sources cited',
    'referenser', 'referenslista', 'referensförteckning', 'litteratur', 'litteraturförteckning', 'litteraturlista',
    'källor', 'källförteckning', 'källhänvisningar', 'citerad litteratur',
    'referanser', 'litteraturliste', 'kilder', 'referencer', 'lähteet', 'kirjallisuus',
    'literatur', 'literaturverzeichnis', 'quellen', 'quellenverzeichnis',
    'bibliographie', 'références', 'referencias', 'bibliografía', 'bibliografia', 'riferimenti',
  ]);

  // Locator labels as they are abbreviated, and the CSL label each means.
  const LOCATOR_LABELS = new Map(Object.entries({
    p: 'page', pp: 'page', page: 'page', pages: 'page', s: 'page', ss: 'page', sid: 'page', sidan: 'page', sidor: 'page',
    S: 'page', Seite: 'page', ch: 'chapter', chap: 'chapter', chapter: 'chapter', kap: 'chapter', kapitel: 'chapter',
    sec: 'section', sect: 'section', section: 'section', avsnitt: 'section', avsn: 'section', '§': 'section',
    fig: 'figure', figs: 'figure', figure: 'figure', figur: 'figure', tab: 'table', table: 'table', tabell: 'table',
    app: 'appendix', appendix: 'appendix', bilaga: 'appendix', para: 'paragraph', vol: 'volume', eq: 'equation',
    n: 'note', note: 'note', fn: 'note', not: 'note', l: 'line', line: 'line',
  }));

  // What alone, between two references, introduces the second one.
  const LEAD_INS = /^(?:see(?: also)?|cf\.?|compare|e\.\s?g\.,?|i\.\s?e\.,?|also|but see|contra|se(?: även| också)?|jfr\.?|jämför|t\.\s?ex\.|bl\.\s?a\.|vgl\.?|siehe|voir)[,:]?$/iu;

  // SKB's report series: "SKB TR-11-01", "SKB R-09-20", "SKB P-04-221", and
  // in older reports "SKB TR 99-01" and "SKB AR 94-12".
  const SKB_SERIES = ['TR', 'R', 'P', 'IPR', 'RD', 'SR', 'TM', 'U', 'F', 'AR', 'TD', 'PIR', 'ITD', 'TU', 'ICR', 'TS'];
  const SKB_SERIES_SET = new Set(SKB_SERIES);

  /* A designation names a publication and numbers it within a year: "SFS
     1984:3", "SSMFS 2008:21", "SOU 2010:6", "SS-EN 1936:1999", "SKI Report
     2008:12". Its first word is in capitals, or is one of these. */
  const DESIGNATION_WORDS = new Set(['Ds', 'Dir', 'Prop', 'Skr', 'Bet']);
  // Words a designation may carry or leave out: "SKI Report 2008:12" is "SKI 2008:12".
  const SERIES_WORDS = new Set(['report', 'reports', 'rapport', 'rapporter', 'no', 'nr']);

  // SKB's reference lists come in two parts: works entered under an
  // abbreviated name ("Data report, 2010."), then all others.
  const ABBREVIATED_HEADINGS = new Set(['references with abbreviated names', 'referenser med förkortade namn']);
  const OTHER_HEADINGS = new Set(['other references', 'övriga referenser']);

  // Nothing but a word joining two references: "(Smith 2020 and Jones 2019)".
  const JOINS_ONLY = /^(?:and|och|og|und|&)$/iu;
  const UPPER = /^\p{Lu}/u;
  const QUOTES_CLOSE = { '”': '“', '"': '"', '»': '«', '’': '‘' };
  const EDITOR_MARK = /^(?:eds?|red|hrsg|comp|coord)$/iu;
  const INITIALS = /^\p{Lu}(?:[-‐]\p{Lu})*$/u;
  // Initials after a surname, as SKB writes them when two authors share
  // one: "Vallery C (2001)", "Höglund L O", "Johannesson L-E".
  const TRAILING_INITIAL = /^\p{Lu}(?:[-‐]\p{Lu})?$/u;
  const DASH = /^[-‐‑‒–—−]$/u;

  /** A name for comparing: letters only, lower case, accents and ligatures
      unfolded, particles in front dropped. "Öhman" and "Ohman" agree. */
  const FOLD_MAP = { ß: 'ss', æ: 'ae', œ: 'oe', ø: 'o', ł: 'l', đ: 'd', þ: 'th', ı: 'i', ð: 'd' };
  function fold(name) {
    let s = String(name || '').toLowerCase().replace(/[ßæœøłđþıð]/g, (c) => FOLD_MAP[c]);
    s = s.normalize('NFKD').replace(/\p{M}/gu, '').replace(/[’']/g, '').replace(/[^\p{L}\p{N}]+/gu, ' ').trim();
    const words = s.split(' ').filter(Boolean);
    while (words.length > 1 && PARTICLES.has(words[0])) words.shift();
    return words.join(' ');
  }

  /* ---------------------------------------------------------------------
     Lexemes
     --------------------------------------------------------------------- */

  const RAW_RE = /([\p{L}\p{M}]+(?:['’\-‐][\p{L}\p{M}]+)*)|(\d+)|(\s+)|([\s\S])/gu;

  function rawTokens(text) {
    const out = [];
    for (const m of text.matchAll(RAW_RE)) {
      const type = m[1] ? 'w' : m[2] ? 'n' : m[3] ? 's' : 'p';
      out.push({ type, s: m[0], a: m.index, b: m.index + m[0].length });
    }
    return out;
  }

  // Sequences of raw tokens: 's' a space, '.' a full stop, '?' optional.
  const ET_AL = [
    ['et', '.?', 's', 'al', '.?'], ['et', '.', 'al', '.?'], ['m', '.?', 's?', 'fl', '.?'], ['mfl', '.?'],
    ['u', '.', 's?', 'a', '.'], ['and', 's', 'others'], ['med', 's', 'flera'],
  ];
  const YEAR_WORDS = [
    [['n', '.?', 's?', 'd', '.?'], 'nd'], [['nd', '.'], 'nd'], [['u', '.?', 's?', 'å', '.?'], 'nd'],
    [['o', '.', 's?', 'J', '.'], 'nd'], [['in', 's', 'press'], 'inpress'], [['forthcoming'], 'inpress'],
    [['in', 's', 'prep', '.?'], 'inpress'], [['i', 's', 'tryck'], 'inpress'], [['under', 's', 'tryckning'], 'inpress'],
    [['im', 's', 'Druck'], 'inpress'], [['unpublished'], 'unpublished'], [['opubl', '.?'], 'unpublished'],
  ];

  /** The index after a pattern of raw tokens starting at i, or -1. */
  function matchSeq(tokens, i, pattern) {
    let k = i;
    for (const part of pattern) {
      const optional = part.length > 1 && part.endsWith('?');
      const want = optional ? part.slice(0, -1) : part;
      const t = tokens[k];
      let ok = false;
      if (t) {
        if (want === 's') ok = t.type === 's' && t.s.length <= 2;
        else if (want === '.') ok = t.type === 'p' && t.s === '.';
        else ok = t.type === 'w' && t.s.toLowerCase() === want.toLowerCase();
      }
      if (ok) k++;
      else if (!optional) return -1;
    }
    return k;
  }

  function isYearNumber(s) {
    if (s.length !== 4) return false;
    const y = Number(s);
    return y >= 1600 && y <= 2099;
  }

  /** The year of a report numbered with two digits: 11 is 2011, 94 is 1994. */
  function reportYear(yy) {
    const n = Number(yy);
    return String(n <= (new Date().getFullYear() % 100) + 1 ? 2000 + n : 1900 + n);
  }

  /** A report number starting at raw token i -- "TR-11-01", "TR 99-01",
      "SKBdoc 1175208" -- as one lexeme, with the index after it. */
  function reportAt(t, i) {
    const w = t[i];
    const lexeme = (end, key, year) => ({
      k: end, lx: { type: 'report', s: t.slice(i, end).map((x) => x.s).join(''), a: w.a, b: t[end - 1].b, key, year },
    });
    if (w.s === 'SKBdoc') {
      const n = t[i + 2];
      if (isSpace(t[i + 1]) && t[i + 1].s.length <= 2 && n && n.type === 'n' && /^\d{5,8}$/.test(n.s)) return lexeme(i + 3, `SKBdoc ${n.s}`, '');
      return null;
    }
    if (!SKB_SERIES_SET.has(w.s)) return null;
    let k = i + 1;
    if (t[k] && ((t[k].type === 'p' && DASH.test(t[k].s)) || t[k].s === ' ')) k++;
    const yy = t[k];
    const dash = t[k + 1];
    const nn = t[k + 2];
    if (!(yy && yy.type === 'n' && yy.s.length === 2 && dash && dash.type === 'p' && DASH.test(dash.s) && nn && nn.type === 'n' && nn.s.length <= 4)) return null;
    let end = k + 3;
    let letter = '';
    if (t[end] && t[end].type === 'w' && /^\p{Ll}$/u.test(t[end].s)) { letter = t[end].s; end++; }
    if (t[end] && (t[end].type === 'w' || t[end].type === 'n')) return null;
    return lexeme(end, `${w.s}-${yy.s}-${nn.s}${letter}`, reportYear(yy.s));
  }

  const REPORT_RE = new RegExp(`(?<![\\p{L}\\p{N}])(${SKB_SERIES.join('|')})[-‐‑‒–— ]?(\\d{2})[-‐‑‒–—](\\d{1,4})([a-z]?)(?![\\p{L}\\p{N}])`, 'gu');
  const SKBDOC_RE = /(?<![\p{L}\p{N}])SKBdoc\s*(?:id\s*)?(\d{5,8})(?!\d)/giu;

  /**
   * The SKB report numbers in a text, in order, as keys: "TR-11-01",
   * "SKBdoc 1175208". With `skbOnly` a number counts only after "SKB" or
   * "KBS" ("SKB R-09-20", "SKBF/KBS TR 83-01"), since other organisations
   * number their reports alike.
   */
  function reportsIn(text, skbOnly) {
    const s = String(text || '');
    const found = [];
    for (const m of s.matchAll(REPORT_RE)) {
      if (skbOnly && !/(?:SKB|KBS)[\s-]*$/u.test(s.slice(Math.max(0, m.index - 6), m.index))) continue;
      found.push([m.index, `${m[1]}-${m[2]}-${m[3]}${m[4]}`]);
    }
    for (const m of s.matchAll(SKBDOC_RE)) found.push([m.index, `SKBdoc ${m[1]}`]);
    return found.sort((a, b) => a[0] - b[0]).map(([, key]) => key);
  }

  /** A designation's name part as compared: series words dropped, capitals,
      no spaces or hyphens. "SKI Report" is "SKI", "SS-EN" is "SSEN". */
  function designationWords(prefix) {
    return String(prefix).split(/[\s\-‐‑]+/u).filter((w) => w && !SERIES_WORDS.has(w.toLowerCase()));
  }
  const squeeze = (words) => words.join('').toUpperCase();

  /** "SSMFS 2008:37" -> "SSMFS 2008:37", "SKI Report 2008:12" -> "SKI 2008:12", as compared. */
  function designationKey(designation) {
    const m = /^(.*\S)\s+((?:1[6-9]|20)\d{2}:\d{1,4}[a-z]?)$/u.exec(String(designation).trim());
    return m ? `${squeeze(designationWords(m[1]))} ${m[2]}` : String(designation).toUpperCase();
  }

  /**
   * The designations in a text, each as its keys: with the last one, two
   * and three words before the number, so "Svensk författningssamling SFS
   * 2003:778" gives "SFS 2003:778" among others.
   */
  function designationsIn(text) {
    const s = String(text || '');
    const out = [];
    for (const m of s.matchAll(/(?<![\d:])((?:1[6-9]|20)\d{2}:\d{1,4})(?!\d)/gu)) {
      const head = s.slice(Math.max(0, m.index - 48), m.index).split(/[,;.()[\]]/u).pop();
      const words = designationWords(head).slice(-3);
      const keys = [];
      for (let n = 1; n <= words.length; n++) keys.push(`${squeeze(words.slice(-n))} ${m[1]}`);
      if (keys.length) out.push(keys);
    }
    return out;
  }

  /** Lexemes: raw tokens with years, report numbers and "et al." merged. */
  function lexemes(text) {
    const t = rawTokens(text);
    const out = [];
    for (let i = 0; i < t.length;) {
      const tok = t[i];
      const report = tok.type === 'w' ? reportAt(t, i) : null;
      if (report) {
        out.push(report.lx);
        i = report.k;
        continue;
      }
      if (tok.type === 'n' && isYearNumber(tok.s)) {
        const prev = t[i - 1];
        const glued = prev && (prev.type === 'n' || (prev.s === '.' && t[i - 2] && t[i - 2].type === 'n'));
        const nxt = t[i + 1];
        if (!glued && nxt && nxt.type === 'w' && /^\p{Ll}$/u.test(nxt.s)) {
          out.push({ type: 'year', s: tok.s + nxt.s, a: tok.a, b: nxt.b, year: tok.s, letter: nxt.s, key: tok.s });
          i += 2;
          continue;
        }
        if (!glued && !(nxt && nxt.type === 'w')) {
          out.push({ type: 'year', s: tok.s, a: tok.a, b: tok.b, year: tok.s, letter: '', key: tok.s });
          i++;
          continue;
        }
      }
      if (tok.type === 'w') {
        let hit = null;
        for (const pat of ET_AL) {
          const k = matchSeq(t, i, pat);
          if (k > 0) { hit = { type: 'etal', k }; break; }
        }
        for (const [pat, key] of hit ? [] : YEAR_WORDS) {
          const k = matchSeq(t, i, pat);
          if (k > 0) { hit = { type: 'year', k, key }; break; }
        }
        if (hit) {
          const last = t[hit.k - 1];
          const lx = { type: hit.type, s: text.slice(tok.a, last.b), a: tok.a, b: last.b };
          if (hit.type === 'year') Object.assign(lx, { year: '', letter: '', key: hit.key });
          out.push(lx);
          i = hit.k;
          continue;
        }
      }
      out.push(tok);
      i++;
    }
    return out;
  }

  /* ---------------------------------------------------------------------
     Reading names backwards
     --------------------------------------------------------------------- */

  const isSpace = (lx) => !!lx && lx.type === 's';
  const isPunct = (lx, ch) => !!lx && lx.type === 'p' && lx.s === ch;
  const back = (L, j) => { while (j >= 0 && isSpace(L[j])) j--; return j; };
  const stripPossessive = (s) => s.replace(/['’]s$/u, '');
  const isInitial = (lx) => !!lx && lx.type === 'w' && INITIALS.test(lx.s) && !NOT_NAMES.has(lx.s);

  function isNameWord(lx) {
    if (!lx || lx.type !== 'w') return false;
    const s = stripPossessive(lx.s);
    return s.length > 1 && UPPER.test(s) && !NOT_NAMES.has(s);
  }

  /**
   * One name ending at lexeme j, not reaching lo: its words, where it
   * starts, and an acronym given after it ("... Climate Change (IPCC)").
   */
  function atomBackward(L, j, lo) {
    let alias = '';
    if (isPunct(L[j], ')')) {
      const inner = back(L, j - 1);
      const open = back(L, inner - 1);
      if (!(inner > lo && L[inner].type === 'w' && /^\p{Lu}{2,}$/u.test(L[inner].s) && isPunct(L[open], '('))) return null;
      alias = L[inner].s;
      j = back(L, open - 1);
    }
    const initials = [];
    while (initials.length < 3 && j - 2 > lo && L[j].type === 'w' && TRAILING_INITIAL.test(L[j].s) && isSpace(L[j - 1])
      && L[j - 1].s.length <= 2 && (isNameWord(L[j - 2]) || (L[j - 2].type === 'w' && TRAILING_INITIAL.test(L[j - 2].s)))) {
      initials.unshift(L[j].s);
      j -= 2;
    }
    if (j <= lo || !isNameWord(L[j])) return null;
    const parts = [stripPossessive(L[j].s)];
    let start = j;
    let k = j - 1;
    for (;;) {
      if (isPunct(L[k], '.') && k - 1 > lo && isInitial(L[k - 1])) { start = k - 1; k -= 2; continue; } // "J.Smith"
      if (!(isSpace(L[k]) && L[k].s.length <= 2) || k - 1 <= lo) break;
      const w = L[k - 1];
      if (isPunct(w, '.') && k - 2 > lo && isInitial(L[k - 2])) { start = k - 2; k -= 3; continue; } // "J. Smith"
      if (!w || w.type !== 'w') break;
      if (isNameWord(w)) { parts.unshift(w.s); start = k - 1; k -= 2; continue; }
      if (PARTICLES.has(w.s)) { parts.unshift(w.s); start = k - 1; k -= 2; continue; }
      if (isInitial(w)) { start = k - 1; k -= 2; continue; } // "M Nilsson"
      if (NAME_JOINERS.has(w.s) && isSpace(L[k - 2]) && k - 3 > lo && isNameWord(L[k - 3])) {
        parts.unshift(L[k - 3].s, w.s);
        start = k - 3;
        k -= 4;
        continue;
      }
      break;
    }
    return { name: parts.join(' '), alias, initials: initials.join(' '), start };
  }

  /**
   * The authors ending at lexeme j: names joined by "and", "&" or commas,
   * with "et al." after them. In running text a comma joins names only in a
   * list that ends in "and" or "&" ("A, B and C"), so "In Sweden, Smith
   * (2020)" is Smith's alone.
   */
  function namesBackward(L, j, lo, narrative) {
    j = back(L, j);
    let etAl = false;
    if (j > lo && L[j].type === 'etal') {
      etAl = true;
      j = back(L, j - 1);
      if (isPunct(L[j], ',')) j = back(L, j - 1);
    }
    const atoms = [];
    let seenAnd = false;
    for (;;) {
      const atom = atomBackward(L, j, lo);
      if (!atom) break;
      atoms.unshift(atom);
      let k = back(L, atom.start - 1);
      if (k <= lo) break;
      let joined = false;
      if (isPunct(L[k], '&') || (L[k].type === 'w' && CONNECTORS.has(L[k].s))) {
        joined = true;
        seenAnd = true;
        k = back(L, k - 1);
        if (isPunct(L[k], ',')) k = back(L, k - 1);
      } else if (isPunct(L[k], ',') && (!narrative || seenAnd)) {
        joined = true;
        k = back(L, k - 1);
      }
      if (!joined || !atomBackward(L, k, lo)) break;
      j = k;
    }
    if (!atoms.length) return null;
    return { names: atoms.map((a) => a.name), aliases: atoms.map((a) => a.alias), initials: atoms.map((a) => a.initials), etAl, start: atoms[0].start };
  }

  /* ---------------------------------------------------------------------
     Locators
     --------------------------------------------------------------------- */

  /** A locator after lexeme i: ", p. 12", ": 45–47", ", kap. 3", ", 141 f." */
  function locatorAfter(L, i, hi) {
    let k = i + 1;
    while (k < hi && isSpace(L[k])) k++;
    if (!(isPunct(L[k], ',') || isPunct(L[k], ':'))) return null;
    const colon = isPunct(L[k], ':');
    k++;
    while (k < hi && isSpace(L[k])) k++;
    let label = null;
    if (L[k] && (L[k].type === 'w' || isPunct(L[k], '§'))) {
      label = LOCATOR_LABELS.get(L[k].s) || LOCATOR_LABELS.get(L[k].s.toLowerCase()) || null;
      if (!label) return null;
      k++;
      if (isPunct(L[k], '.')) k++;
      while (k < hi && isSpace(L[k])) k++;
    }
    const first = L[k];
    if (label && first && first.type === 'w' && /^[ivxlc]+$/iu.test(first.s)) return { label, value: first.s, end: k };
    const numeric = first && (first.type === 'n' || (first.type === 'year' && first.year && (label || colon)));
    if (!numeric || (!label && !colon && first.type === 'n' && first.s.length > 4)) return null;
    let value = first.type === 'year' ? first.year : first.s;
    let end = k;
    // "Section 3.2.1"
    while (isPunct(L[end + 1], '.') && L[end + 2] && L[end + 2].type === 'n' && L[end + 1].a === L[end].b && L[end + 2].a === L[end + 1].b) {
      value += `.${L[end + 2].s}`;
      end += 2;
    }
    let m = end + 1;
    while (m < hi && isSpace(L[m])) m++;
    const dash = L[m] && L[m].type === 'p' && /[-–—‐]/u.test(L[m].s);
    if (dash) {
      let n = m + 1;
      while (n < hi && isSpace(L[n])) n++;
      if (L[n] && (L[n].type === 'n' || (L[n].type === 'year' && L[n].year))) {
        value += `–${L[n].type === 'year' ? L[n].year : L[n].s}`;
        end = n;
      }
    } else if (L[m] && L[m].type === 'w' && /^ff?$/u.test(L[m].s)) {
      value += ` ${L[m].s}${isPunct(L[m + 1], '.') ? '.' : ''}`;
      end = isPunct(L[m + 1], '.') ? m + 1 : m;
    }
    return { label: label || 'page', value, end };
  }

  /* ---------------------------------------------------------------------
     One paragraph
     --------------------------------------------------------------------- */

  /* report is an SKB report number ("TR-11-01"), designation a
     designation ("SSMFS 2008:37"), abbrev an abbreviated name ("Data
     report"); initials are those written after each author's name. */
  function makeRef(fields) {
    return Object.assign({
      authors: [], aliases: [], initials: [], etAl: false, year: '', letter: '', yearKey: '', num: null,
      report: '', designation: '', abbrev: '',
      locator: '', locatorLabel: '', prefix: '', suffix: '', suppressAuthor: false, entry: null,
    }, fields);
  }

  const SKB_NAMES = (start) => ({ names: ['SKB'], aliases: [''], initials: [''], etAl: false, start });
  const NO_NAMES = { names: [], aliases: [], initials: [], etAl: false, start: 0 };

  const yearFields = (lx) => ({ year: lx.year || lx.s, letter: lx.letter || '', yearKey: lx.year ? lx.year : lx.key });
  const tidy = (s) => s.replace(/\s+/g, ' ').trim();
  const trimSeparators = (s) => s.replace(/^[\s,;]+|[\s,;]+$/gu, '');

  /** Every matched pair of parentheses, [open, close] lexeme indexes,
      outer before inner. An unclosed "(" is ignored, not its insides. */
  function parentheses(L) {
    const out = [];
    const stack = [];
    L.forEach((lx, i) => {
      if (isPunct(lx, '(')) stack.push(i);
      else if (isPunct(lx, ')') && stack.length) out.push([stack.pop(), i]);
    });
    return out.sort((x, y) => x[0] - y[0]);
  }

  /** "(ed)", "(eds.)": an editor's mark, part of the name before it. */
  function isEditorMark(L, open, close) {
    let k = back(L, close - 1);
    if (isPunct(L[k], '.')) k = back(L, k - 1);
    return k > open && L[k].type === 'w' && EDITOR_MARK.test(L[k].s) && back(L, k - 1) === open;
  }

  /**
   * The groups of citations in one paragraph, in order. A parenthesis that
   * is a citation keeps what is inside it ("(IPCC (2019) ...)"); one that
   * is prose is looked into, so "(see Annex D of Publication 100 (ICRP,
   * 2006))" gives the inner citation. A short paragraph that is nothing but
   * citations -- a table's source column -- is a group without parentheses.
   * `context.abbrevs` are the abbreviated names of the reference list.
   */
  function findInParagraph(text, para = 0, story = 'body', context = null) {
    const L = lexemes(text);
    const groups = [];
    const pairs = parentheses(L);
    let coveredTo = -1;
    for (const [open, close] of pairs) {
      if (open < coveredTo) continue;
      let lastClose = -1;
      for (const [o, c] of pairs) if (c < open && c > lastClose && !isEditorMark(L, o, c)) lastClose = c;
      const g = readParenthesis(text, L, open, close, lastClose, para, story, context);
      if (g) { groups.push(g); coveredTo = close; }
    }
    if (!pairs.length) {
      const bare = readBare(text, para, story, context);
      if (bare) groups.push(bare);
    }
    if (!groups.some((g) => g.kind === 'bare')) groups.push(...readRunningReports(text, L, pairs, para, story));
    groups.push(...readNumbered(text, L, para, story));
    return groups.sort((x, y) => x.start - y.start);
  }

  /** "Smith & Jones 2019; SKB 2010" as the whole of a short paragraph. A
      cell with a report number or an abbreviated name is left: it is a
      label -- "Initial state report / SKB TR-23-02" in a figure of the
      reports, or the document's own number -- more often than a source. */
  function readBare(text, para, story, context) {
    const trimmed = text.trim();
    if (trimmed.length < 6 || trimmed.length > 160 || !UPPER.test(trimmed)) return null;
    const wrapped = `(${trimmed.replace(/[.;,]$/u, '')})`;
    const W = lexemes(wrapped);
    const g = readParenthesis(wrapped, W, 0, W.length - 1, 0, para, story, context);
    if (!g || g.problem || g.refs.some((r) => r.prefix || r.suffix || r.suppressAuthor)) return null;
    if (g.refs.some((r) => r.report || r.abbrev)) return null;
    const start = text.indexOf(trimmed);
    const end = start + wrapped.length - 2;
    return Object.assign(g, { kind: 'bare', start, end, text: text.slice(start, end), authorStart: start });
  }

  /** Where the reference list's abbreviated names stand between lexemes
      open and close: first lexeme -> { end, name }, the longest name first. */
  function abbreviationSpans(text, L, open, close, context) {
    const out = new Map();
    if (!context || !context.abbrevs || !context.abbrevs.length) return out;
    const from = L[open].b;
    const inner = text.slice(from, L[close].a);
    const taken = [];
    for (const ab of context.abbrevs) {
      for (const m of inner.matchAll(ab.re)) {
        const a = from + m.index;
        const b = a + m[0].length;
        if (taken.some(([x, z]) => a < z && b > x)) continue;
        const si = L.findIndex((lx) => lx.a === a);
        const ei = L.findIndex((lx) => lx.b === b);
        if (si <= open || ei >= close || ei < si) continue;
        taken.push([a, b]);
        out.set(si, { end: ei, name: ab.name });
      }
    }
    return out;
  }

  /** "2008:37" glued to the year lexeme y: the number of a designation. */
  function designationNumber(L, y) {
    const colon = L[y + 1];
    const n = L[y + 2];
    if (!(L[y].year && !L[y].letter && isPunct(colon, ':') && colon.a === L[y].b && n && n.a === colon.b)) return null;
    const digits = n.type === 'n' || (n.type === 'year' && n.year && !n.letter) ? n.s : '';
    return /^\d{1,4}$/u.test(digits) ? { value: `${L[y].year}:${digits}`, end: y + 2 } : null;
  }

  function isDesignationPrefix(name) {
    const first = String(name || '').split(' ')[0];
    return /^\p{Lu}{2,}(?:[-‐]\p{Lu}{1,4})*$/u.test(first) || DESIGNATION_WORDS.has(first);
  }

  /*
   * The anchors of a parenthesis are its years, its report numbers and the
   * abbreviated names in it. A year right after a name in capitals and a
   * colon is a designation, "SSMFS 2008:37": the 37 is the regulation, not
   * a page, and read as "SSMFS 2008" it would fit every SSMFS of that year.
   */
  function readParenthesis(text, L, open, close, lastClose, para, story, context) {
    if (L[close].b - L[open].a > 600) return null;
    const depth = new Map();
    let d = 0;
    for (let i = open + 1; i < close; i++) {
      if (isPunct(L[i], '(')) d++;
      depth.set(i, d);
      if (isPunct(L[i], ')')) d = Math.max(0, d - 1);
    }
    const onlySeparators = (from, to) => {
      for (let k = from + 1; k < to; k++) if (!(isSpace(L[k]) || isPunct(L[k], ',') || isPunct(L[k], ';') || JOINS_ONLY.test(L[k].s))) return false;
      return true;
    };
    const spans = abbreviationSpans(text, L, open, close, context);
    const units = [];
    let unattributed = false;
    let first = true;
    for (let y = open + 1; y < close; y++) {
      const lx = L[y];
      const prev = units[units.length - 1];
      if ((prev && y <= prev.endIdx) || depth.get(y) > 0) continue;
      const span = spans.get(y);
      if (!span && lx.type !== 'year' && lx.type !== 'report') continue;
      const lo = prev ? prev.endIdx : open;
      let unit = null;
      if (span) {
        // "Data report", "(see Data report, 2010)"; but in "(... is
        // described in the Data report)" the name is part of the prose.
        const lead = trimSeparators(text.slice(L[lo].b, lx.a)).trim();
        if (lead && !LEAD_INS.test(lead) && !(prev && JOINS_ONLY.test(lead))) continue;
        unit = { names: NO_NAMES, abbrev: span.name, startIdx: y, y: null, endIdx: span.end };
        let k = span.end + 1;
        while (k < close && isSpace(L[k])) k++;
        if (isPunct(L[k], ',')) { k++; while (k < close && isSpace(L[k])) k++; }
        if (k < close && L[k].type === 'year') { unit.y = k; unit.endIdx = k; }
      } else {
        let j = back(L, y - 1);
        if (isPunct(L[j], ',')) j = back(L, j - 1);
        // "Smith, Ed., 2023", "Smith (ed.) 2010"
        if (isPunct(L[j], '.') && L[j - 1] && EDITOR_MARK.test(L[j - 1].s)) j = back(L, j - 2);
        else if (isPunct(L[j], ')') && L[j - 1] && (EDITOR_MARK.test(L[j - 1].s) || isPunct(L[j - 1], '.'))) {
          let o = j - 1;
          while (o > lo && !isPunct(L[o], '(')) o--;
          if (o > lo) j = back(L, o - 1);
        }
        if (isPunct(L[j], ',')) j = back(L, j - 1);
        // A report number's author is the "SKB" in front of it, whatever
        // precedes that: "(SDM, SKB R-11-04)", "SAFE SKB R-98-43".
        const names = lx.type === 'report' && j > lo && L[j].type === 'w' && L[j].s === 'SKB' ? SKB_NAMES(j) : namesBackward(L, j, lo, false);
        let before = null;
        if (names) unit = { names, startIdx: names.start, y };
        else if (prev && onlySeparators(prev.endIdx, y)) {
          if (lx.type === 'report' && !prev.report && !prev.abbrev && !prev.designation && prev.y !== null) {
            // "(SKB 2011, TR-11-01)": the number of the report just cited
            prev.report = lx;
            prev.endIdx = y;
            if (!prev.locator) {
              prev.locator = locatorAfter(L, y, close);
              if (prev.locator) prev.endIdx = prev.locator.end;
            }
            first = false;
            continue;
          }
          unit = { names: prev.names, startIdx: y, y, followOn: true };
        } else if (first && onlySeparators(open, y) && (before = beforeParenthesis(L, open, lastClose))) {
          unit = { names: before, startIdx: y, y, external: true };
        } else if (lx.type === 'report') {
          unit = { names: SKB_NAMES(y), startIdx: y, y }; // "(TR-10-66)": the series are SKB's
        } else {
          unattributed = true;
        }
        if (unit && lx.type === 'report') unit.report = lx;
        if (unit && lx.type === 'year') {
          const num = designationNumber(L, y);
          const prefix = unit.names.names[unit.names.names.length - 1];
          if (num && isDesignationPrefix(prefix)) {
            unit.designation = `${prefix} ${num.value}`;
            unit.endIdx = num.end;
          }
        }
      }
      first = false;
      if (!unit) continue;
      if (unit.endIdx === undefined) unit.endIdx = y;
      const loc = locatorAfter(L, unit.endIdx, close);
      if (loc) unit.endIdx = loc.end;
      unit.locator = loc;
      units.push(unit);
      // "2020a, b": further letters of the same year
      const yl = unit.y !== null ? L[unit.y] : null;
      let k = unit.endIdx + 1;
      while (yl && yl.type === 'year' && yl.letter) {
        let m = k;
        while (m < close && isSpace(L[m])) m++;
        if (!isPunct(L[m], ',')) break;
        m++;
        while (m < close && isSpace(L[m])) m++;
        const w = L[m];
        const after = L[m + 1];
        if (!(w && w.type === 'w' && /^\p{Ll}$/u.test(w.s))) break;
        if (after && !(isSpace(after) || isPunct(after, ',') || isPunct(after, ';') || isPunct(after, ')'))) break;
        units.push({ names: unit.names, abbrev: unit.abbrev, startIdx: m, y: m, endIdx: m, followOn: true, letterOf: yl, letter: w.s });
        k = m + 1;
      }
    }
    if (!units.length) return null;

    const refs = units.map((u) => {
      let yf = { year: '', letter: '', yearKey: '' };
      if (u.letterOf) yf = { year: u.letterOf.year, letter: u.letter, yearKey: u.letterOf.year };
      else if (u.y !== null && L[u.y].type === 'year') yf = yearFields(L[u.y]);
      else if (u.report) yf = { year: u.report.year, letter: '', yearKey: u.report.year };
      return makeRef(Object.assign(yf, {
        authors: u.names.names, aliases: u.names.aliases, initials: u.names.initials || [], etAl: u.names.etAl,
        report: u.report ? u.report.key : '', designation: u.designation || '', abbrev: u.abbrev || '',
        locator: u.locator ? u.locator.value : '', locatorLabel: u.locator ? u.locator.label : '',
        suppressAuthor: !!u.external,
      }));
    });

    // The words between references, kept: before the first, its prefix;
    // after the last, its suffix; between two, up to a semicolon the suffix
    // of the first, after it the prefix of the second (or, with no
    // semicolon, a prefix only if it is a lead-in such as "see").
    // A bare "and" between two is dropped: Zotero puts its own delimiter there.
    const between = (from, to) => (to > from + 1 ? text.slice(L[from + 1].a, L[to - 1].b) : '');
    for (let n = 0; n <= units.length; n++) {
      if (n > 0 && n < units.length && units[n].followOn) continue;
      const raw = between(n === 0 ? open : units[n - 1].endIdx, n === units.length ? close : units[n].startIdx);
      if (!trimSeparators(raw)) continue;
      if (n > 0 && n < units.length && JOINS_ONLY.test(trimSeparators(raw).trim())) continue;
      if (n === 0) { refs[0].prefix = tidy(trimSeparators(raw)); continue; }
      if (n === units.length) { refs[n - 1].suffix = tidy(trimSeparators(raw)); continue; }
      const semi = raw.indexOf(';');
      const head = semi >= 0 ? tidy(trimSeparators(raw.slice(0, semi))) : '';
      const tail = tidy(trimSeparators(semi >= 0 ? raw.slice(semi + 1) : raw));
      if (head) refs[n - 1].suffix = head;
      if (!tail) continue;
      if (semi >= 0 || LEAD_INS.test(tail)) refs[n].prefix = tail;
      else refs[n - 1].suffix = tidy(`${refs[n - 1].suffix} ${tail}`);
    }
    const external = !!units[0].external;
    const start = L[open].a;
    const end = L[close].b;
    return {
      para, story, kind: external && units.length === 1 ? 'narrative' : 'parenthesis',
      start, end, text: text.slice(start, end), authorStart: external ? L[units[0].names.start].a : start,
      refs, problem: unattributed ? 'a year in it has no author' : null,
    };
  }

  /** The authors of "Smith (2020)", read in front of the parenthesis. */
  function beforeParenthesis(L, open, lastClose) {
    let j = back(L, open - 1);
    if (isPunct(L[j], ')')) { // "Aquilonius (ed) (2010)"
      let o = j - 1;
      while (o > lastClose && !isPunct(L[o], '(')) o--;
      if (o > lastClose && isEditorMark(L, o, j)) j = back(L, o - 1);
    }
    if (isPunct(L[j], ',')) j = back(L, j - 1); // "Gunia & Gunia, (2022)"
    // "Lane argues that “quoted words” (2014)": step over the quotation, and
    // then over up to three lower-case words, to the name.
    if (L[j] && L[j].type === 'p' && QUOTES_CLOSE[L[j].s]) {
      const opener = QUOTES_CLOSE[L[j].s];
      let k = j - 1;
      while (k > lastClose && !isPunct(L[k], opener)) k--;
      if (k <= lastClose) return null;
      j = back(L, k - 1);
      if (isPunct(L[j], ':') || isPunct(L[j], ',')) j = back(L, j - 1);
      for (let words = 0; words < 3 && j > lastClose && L[j].type === 'w' && L[j].s === L[j].s.toLowerCase(); words++) {
        const names = namesBackward(L, j, lastClose, true);
        if (names) return names;
        j = back(L, j - 1);
      }
    }
    return namesBackward(L, j, lastClose, true);
  }

  /**
   * "SKB TR-11-01" in running text: SKB stays as text and the number
   * becomes the citation, so it reads "SKB (2011)" once Zotero formats it.
   * A number on a line of its own -- a cover, a table cell, a figure of the
   * reports -- is left alone: it labels a report rather than cites it.
   */
  function readRunningReports(text, L, pairs, para, story) {
    const out = [];
    L.forEach((lx, y) => {
      if (lx.type !== 'report' || !lx.year || pairs.some(([o, c]) => o < y && y < c)) return;
      const j = back(L, y - 1);
      if (!(j >= 0 && L[j].type === 'w' && L[j].s === 'SKB')) return;
      const lineStart = Math.max(text.lastIndexOf('\n', L[j].a), text.lastIndexOf('\t', L[j].a)) + 1;
      const lineEnd = text.slice(lx.b).search(/[\n\t]/u);
      const line = text.slice(lineStart, lineEnd < 0 ? text.length : lx.b + lineEnd);
      if (line.trim().length < lx.b - L[j].a + 12) return;
      out.push({
        para, story, kind: 'narrative', start: lx.a, end: lx.b, text: lx.s, authorStart: L[j].a,
        refs: [makeRef({ authors: ['SKB'], aliases: [''], initials: [''], report: lx.key, year: lx.year, yearKey: lx.year, suppressAuthor: true })],
        problem: null,
      });
    });
    return out;
  }

  /** "[3]", "[1, 4–6]" */
  function readNumbered(text, L, para, story) {
    const out = [];
    const skip = (k) => { while (isSpace(L[k])) k++; return k; };
    for (let i = 0; i < L.length; i++) {
      if (!isPunct(L[i], '[')) continue;
      const nums = [];
      let k = i + 1;
      let ok = false;
      for (;;) {
        k = skip(k);
        const t = L[k];
        if (!t || !/^\d{1,4}$/u.test(t.s)) break;
        const a = Number(t.s);
        k = skip(k + 1);
        if (L[k] && L[k].type === 'p' && /[-–—‐]/u.test(L[k].s)) {
          k = skip(k + 1);
          const u = L[k];
          if (!u || !/^\d{1,4}$/u.test(u.s) || Number(u.s) < a || Number(u.s) - a > 300) break;
          for (let v = a; v <= Number(u.s); v++) nums.push(v);
          k = skip(k + 1);
        } else {
          nums.push(a);
        }
        if (isPunct(L[k], ']')) { ok = true; break; }
        if (!isPunct(L[k], ',') && !isPunct(L[k], ';')) break;
        k++;
      }
      if (!ok || !nums.length || nums.some((v) => v < 1)) continue;
      out.push({
        para, story, kind: 'numbered', start: L[i].a, end: L[k].b, text: text.slice(L[i].a, L[k].b), authorStart: L[i].a,
        refs: nums.map((v) => makeRef({ num: v })), problem: null,
      });
      i = k;
    }
    return out;
  }

  /* ---------------------------------------------------------------------
     Reference list entries
     --------------------------------------------------------------------- */

  const ENTRY_NUMBER_RE = /^\s*(?:\[(\d{1,4})\]|(\d{1,4})[.)])\s+/u;
  const LEAD_REPORT_RE = new RegExp(`^\\s*SKB[\\s-]*(?:${SKB_SERIES.join('|')})[-‐‑‒–— ]?\\d{2}[-‐‑‒–—]\\d{1,4}[a-z]?(?![\\p{L}\\p{N}])`, 'u');

  /**
   * An entry of a reference list -- number, authors, year -- or null when
   * the paragraph does not begin like one. The authors must come first, as
   * names, initials, particles and joining words only: that is what tells
   * "Smith J, 2020. Title." from "The results (Smith, 2020) show".
   */
  function readEntry(text) {
    const numMatch = ENTRY_NUMBER_RE.exec(text);
    const num = numMatch ? Number(numMatch[1] || numMatch[2]) : null;
    const body = numMatch ? text.slice(numMatch[0].length) : text;
    if (body.trim().length < 12 || body.length > 3000) return null;
    // The report's own number comes after its title ("... SKB TR-11-01,
    // Svensk Kärnbränslehantering AB."), so the last one is taken: one in
    // the title is a report the work is about.
    const report = reportsIn(body, true).pop() || '';
    const base = { num, authors: [], year: '', letter: '', yearKey: '', report, designation: '', abbrev: '', text: text.trim() };
    // "SKBdoc 1175208 ver 5.0. Title."
    const skbdoc = /^\s*SKBdoc\s+(\d{5,8})/u.exec(body);
    if (skbdoc) return Object.assign(base, { report: `SKBdoc ${skbdoc[1]}` });
    // "SKB TR-11-01. Title.", entered under its number
    const lead = LEAD_REPORT_RE.exec(body);
    if (lead) {
      const key = reportsIn(lead[0])[0];
      return Object.assign(base, { authors: ['SKB'], report: key, year: reportYear(key.split('-')[1]), yearKey: reportYear(key.split('-')[1]) });
    }
    const numberedOnly = num !== null ? base : null;
    const L = lexemes(body.slice(0, 400));
    const yi = L.findIndex((lx) => lx.type === 'year');
    if (yi < 0) return numberedOnly;
    let authors = authorsUpTo(L, yi);
    if (!authors && num !== null) {
      // "12. Smith J, Jones A. Title. Journal. 2020;12:3": in a numbered
      // list the year may come last, and the authors end at a full stop.
      const stop = L.findIndex((lx, i) => isPunct(lx, '.') && isSpace(L[i + 1]) && i > 0 && L[i - 1].type === 'w' && /^\p{Lu}{1,3}$/u.test(L[i - 1].s));
      authors = stop > 0 ? authorsUpTo(L, stop) : null;
    }
    if (!authors || (!authors.length && num === null)) return numberedOnly;
    const entry = Object.assign(base, { authors }, yearFields(L[yi]));
    // "SSMFS 2008:21. Title."
    const dn = authors.length === 1 ? designationNumber(L, yi) : null;
    if (dn && isDesignationPrefix(authors[0])) entry.designation = `${authors[0]} ${dn.value}`;
    return entry;
  }

  /*
   * An author list ends in a surname and initials -- "Andolfsson T",
   * "Höglund L O", "Johannesson L-E" -- and an abbreviated name does not:
   * "Post-closure safety report", "Data report". Both are written "<name>,
   * <year>.", and only this tells them apart.
   */
  const AUTHOR_LIST_END = /\p{L}{2,}\s+\p{Lu}(?:[-‐]\p{Lu})?(?:\s+\p{Lu}(?:[-‐]\p{Lu})?){0,3}$/u;

  /** "Data report, 2010. Data report for the safety assessment SR-Site.
      SKB TR-10-52, ..." under "References with abbreviated names". */
  function readAbbreviatedEntry(text) {
    const numMatch = ENTRY_NUMBER_RE.exec(text);
    const body = numMatch ? text.slice(numMatch[0].length) : text;
    const m = /^\s*(.+?)\s*,\s*((?:1[6-9]|20)\d{2})([a-z]?)\s*\./u.exec(body);
    if (!m || m[1].length > 120 || AUTHOR_LIST_END.test(m[1]) || /[()]/u.test(m[1])) return null;
    return {
      num: numMatch ? Number(numMatch[1] || numMatch[2]) : null, authors: [], year: m[2], letter: m[3], yearKey: m[2],
      report: reportsIn(body, true).pop() || '', designation: '', abbrev: tidy(m[1]), text: text.trim(),
    };
  }

  /** The names in lexemes [0, end) of an entry, or null if anything but
      names, initials, particles and joining words is there. */
  function authorsUpTo(L, end) {
    const authors = [];
    let current = [];
    let words = 0;
    const flush = () => { if (current.length) authors.push(current.join(' ')); current = []; };
    for (let i = 0; i < end; i++) {
      const lx = L[i];
      if (lx.type === 's') continue;
      if (lx.type === 'etal') { flush(); continue; }
      if (lx.type === 'report') return null;
      if (lx.type === 'p') {
        if (',;&.'.includes(lx.s)) flush();
        else if (!'()[]:'.includes(lx.s)) return null;
        continue;
      }
      if (lx.type === 'n' || ++words > 40) return null;
      const s = lx.s;
      if (CONNECTORS.has(s)) { flush(); continue; }
      if (EDITOR_MARK.test(s)) continue;
      if (INITIALS.test(s) || (/^\p{Lu}{2,3}$/u.test(s) && current.length)) continue;
      if (PARTICLES.has(s)) { current.push(s); continue; }
      if (NAME_JOINERS.has(s) && current.length) { current.push(s); continue; }
      if (UPPER.test(s) && !(authors.length === 0 && current.length === 0 && NOT_NAMES.has(s))) { current.push(s); continue; }
      return null;
    }
    flush();
    return authors;
  }

  function normaliseHeading(text) {
    return text.trim().toLowerCase()
      .replace(/^(?:\d+(?:\.\d+)*|[a-z](?:\.\d+)*|[ivx]+)\.?\s+/u, '')
      .replace(/[:.]$/u, '').trim();
  }

  const isListHeading = (text) => text.length < 60 && LIST_HEADINGS.has(normaliseHeading(text));
  const isPartHeading = (text) => text.length < 60 && (ABBREVIATED_HEADINGS.has(normaliseHeading(text)) || OTHER_HEADINGS.has(normaliseHeading(text)));

  /**
   * Where the reference list is, as body paragraph indexes { start, end,
   * entries }, or null. `levels` are outline levels (0 for Heading 1) where
   * the document has them.
   */
  function findReferenceList(texts, levels) {
    const n = texts.length;
    let abbreviated = false;
    const entryAt = texts.map((t) => {
      if (isPartHeading(t)) { abbreviated = ABBREVIATED_HEADINGS.has(normaliseHeading(t)); return null; }
      if (!t.trim()) return null;
      return (abbreviated && readAbbreviatedEntry(t)) || readEntry(t);
    });
    const nonEmpty = (i) => texts[i].trim().length > 0;
    const hasAuthor = (e) => e && (e.authors.length > 0 || e.num !== null || !!e.abbrev || !!e.report);

    /** Past the last entry of a run that tolerates six other paragraphs in a row. */
    function endOfRun(from) {
      let last = from - 1;
      let other = 0;
      for (let i = from; i < n; i++) {
        if (hasAuthor(entryAt[i])) { last = i; other = 0; } else if (nonEmpty(i) && ++other > 6) break;
      }
      return last + 1;
    }

    // The last list heading followed by entries; failing that, the heading
    // of SKB's abbreviated names, which may stand without one.
    let start = -1;
    for (const isHeading of [isListHeading, (t) => isPartHeading(t) && ABBREVIATED_HEADINGS.has(normaliseHeading(t))]) {
      for (let h = n - 1; h >= 0 && start < 0; h--) {
        if (!isHeading(texts[h])) continue;
        let seen = 0;
        let entries = 0;
        for (let i = h + 1; i < n && seen < 15; i++) {
          if (!nonEmpty(i)) continue;
          seen++;
          if (hasAuthor(entryAt[i])) entries++;
        }
        if (entries >= 3) start = h;
      }
    }
    let end = -1;
    if (start >= 0) {
      const own = levels ? levels[start] : null;
      if (Number.isInteger(own)) {
        end = n;
        for (let i = start + 1; i < n; i++) if (Number.isInteger(levels[i]) && levels[i] <= own && !isPartHeading(texts[i])) { end = i; break; }
      } else {
        end = endOfRun(start + 1);
      }
    } else {
      // No heading: the longest run of entries, if it is long, dense, and
      // not at the start of the document.
      let best = null;
      for (let i = 0; i < n; i++) {
        if (!hasAuthor(entryAt[i])) continue;
        const e = endOfRun(i);
        let count = 0;
        let other = 0;
        for (let k = i; k < e; k++) { if (hasAuthor(entryAt[k])) count++; else if (nonEmpty(k)) other++; }
        if (!best || count > best.count) best = { start: i, end: e, count, other };
        i = e - 1;
      }
      if (best && best.count >= 6 && best.count >= 3 * best.other && best.start >= 0.3 * n) {
        start = best.start;
        end = best.end;
      }
    }
    if (start < 0) return null;
    const entries = [];
    for (let i = start; i < end; i++) if (hasAuthor(entryAt[i])) entries.push(Object.assign({ index: i }, entryAt[i]));
    return { start, end, entries };
  }

  /* ---------------------------------------------------------------------
     A whole document
     --------------------------------------------------------------------- */

  /** Entries are found by the first word of the first author and the year. */
  const entryKey = (name, yearKey) => `${fold(name).split(' ')[0]}|${yearKey}`;

  /** One decision covers every citation with the same key: first three
      authors, et al., year and letter -- or the number. */
  function refKey(ref) {
    if (ref.num !== null) return `#${ref.num}`;
    if (ref.abbrev) return `a|${fold(ref.abbrev)}|${ref.yearKey}${ref.letter}`;
    if (ref.designation) return `d|${designationKey(ref.designation)}`;
    if (ref.report) return `r|${ref.report}`;
    return `${ref.authors.slice(0, 3).map(fold).join('+')}${ref.etAl ? '+etal' : ''}|${ref.yearKey}${ref.letter}`;
  }

  /** "Smith & Jones 2020", "Smith et al. 2020a", "[3]", "SKB TR-11-01",
      "SSMFS 2008:37", "Data report" */
  function refLabel(ref) {
    if (ref.num !== null) return `[${ref.num}]`;
    if (ref.abbrev) return ref.year ? `${ref.abbrev} ${ref.year}${ref.letter}` : ref.abbrev;
    if (ref.designation) return ref.designation;
    if (ref.report) return ref.report.startsWith('SKBdoc') ? ref.report : `${ref.authors[0] || 'SKB'} ${ref.report}`;
    const a = ref.authors;
    let who = a[0] || '?';
    if (ref.etAl) who += ' et al.';
    else if (a.length === 2) who = `${a[0]} & ${a[1]}`;
    else if (a.length > 2) who = `${a.slice(0, -1).join(', ')} & ${a[a.length - 1]}`;
    const when = ref.year ? `${ref.year}${ref.letter}` : ref.yearKey;
    return `${who} ${when}`;
  }

  /** A pattern finding an abbreviated name in text, as a whole phrase,
      whatever its case and whichever hyphen it is written with. */
  function abbreviationPattern(name) {
    const words = name.split(/\s+/u).map((w) => w.replace(/[.*+?^${}()|[\]\\]/gu, '\\$&').replace(/[-‐‑]/gu, '[-‐‑]'));
    return new RegExp(`(?<![\\p{L}\\p{N}])${words.join('\\s+')}(?![\\p{L}\\p{N}])`, 'giu');
  }

  /**
   * paras: [{ text, story, level }] in document order; story is 'body',
   * 'footnote' or 'endnote', level the outline level of a heading or null.
   * Returns { groups, refs, list, mentioned }: group.para indexes paras,
   * ref.group indexes groups, and mentioned holds the entries named in
   * running text without a citation -- "the Data report", "SSMFS 2008:21"
   * -- which are not written as fields but are not uncited either.
   */
  function parseDocument(paras) {
    const bodyIdx = [];
    paras.forEach((p, i) => { if (p.story === 'body') bodyIdx.push(i); });
    const found = findReferenceList(bodyIdx.map((i) => paras[i].text),
      bodyIdx.map((i) => (Number.isInteger(paras[i].level) ? paras[i].level : null)));
    const skip = new Set();
    let list = null;
    let context = null;
    if (found) {
      for (let k = found.start; k < found.end; k++) skip.add(bodyIdx[k]);
      const entries = found.entries.map((e) => Object.assign({}, e, { para: bodyIdx[e.index] }));
      const byKey = new Map();
      const byNum = new Map();
      const byReport = new Map();
      const byDesignation = new Map();
      const byAbbrev = new Map();
      const first = (map, key, e) => { if (key && !map.has(key)) map.set(key, e); };
      for (const e of entries) {
        if (e.num !== null) first(byNum, e.num, e);
        first(byReport, e.report, e);
        if (e.designation) first(byDesignation, designationKey(e.designation), e);
        if (e.abbrev) first(byAbbrev, fold(e.abbrev), e);
        if (!e.authors.length || !e.yearKey) continue;
        for (const key of [entryKey(e.authors[0], e.yearKey + e.letter), entryKey(e.authors[0], e.yearKey)]) first(byKey, key, e);
      }
      list = { start: bodyIdx[found.start], end: found.end < bodyIdx.length ? bodyIdx[found.end] : null, entries, byKey, byNum, byReport, byDesignation, byAbbrev };
      context = {
        abbrevs: [...byAbbrev.values()].map((e) => ({ name: e.abbrev, entry: e, re: abbreviationPattern(e.abbrev) }))
          .sort((a, b) => b.name.length - a.name.length),
      };
    }
    const groups = [];
    const mentioned = new Set();
    paras.forEach((p, i) => {
      if (skip.has(i) || !p.text.trim()) return;
      groups.push(...findInParagraph(p.text, i, p.story, context));
      if (!list) return;
      for (const ab of context.abbrevs) if (p.text.search(ab.re) >= 0) mentioned.add(ab.entry);
      for (const keys of designationsIn(p.text)) for (const k of keys) if (list.byDesignation.has(k)) mentioned.add(list.byDesignation.get(k));
      for (const k of reportsIn(p.text)) if (list.byReport.has(k)) mentioned.add(list.byReport.get(k));
    });
    const refs = [];
    groups.forEach((g, gi) => g.refs.forEach((r, ri) => {
      r.group = gi;
      r.index = ri;
      if (!list) r.entry = null;
      else if (r.num !== null) r.entry = list.byNum.get(r.num) || null;
      else if (r.abbrev) r.entry = list.byAbbrev.get(fold(r.abbrev)) || null;
      // A designation has its own entry or none: under "SSMFS|2008" the
      // entry would be whichever SSMFS of 2008 the list has.
      else if (r.designation) r.entry = list.byDesignation.get(designationKey(r.designation)) || null;
      else if (r.report) r.entry = list.byReport.get(r.report) || null;
      else if (r.authors.length) {
        r.entry = list.byKey.get(entryKey(r.authors[0], r.yearKey + r.letter)) || list.byKey.get(entryKey(r.authors[0], r.yearKey)) || null;
      }
      r.key = refKey(r);
      r.label = refLabel(r);
      refs.push(r);
    }));
    return { groups, refs, list, mentioned };
  }

  /** Entries of the reference list that no citation points to. `alsoCited`
      are [surname, year] pairs cited by fields that were left as they were. */
  function uncitedEntries(parsed, alsoCited = []) {
    if (!parsed.list) return [];
    const cited = new Set(parsed.refs.map((r) => r.entry).filter(Boolean));
    for (const e of parsed.mentioned || []) cited.add(e);
    const keys = new Set(alsoCited.map(([s, y]) => entryKey(s, String(y).slice(0, 4))));
    return parsed.list.entries.filter((e) => !cited.has(e) && !(e.authors.length && keys.has(entryKey(e.authors[0], e.yearKey))));
  }

  return {
    parseDocument, findInParagraph, findReferenceList, readEntry, readAbbreviatedEntry, isListHeading, uncitedEntries,
    fold, lexemes, refKey, refLabel, entryKey, reportsIn, designationsIn, designationKey, PARTICLES,
  };
}));
