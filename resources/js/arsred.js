/* ==========================================================================
   arsred.js — granska en iXBRL-årsredovisning innan den lämnas in

   Sidan bygger och kontrollerar en handling; den lämnar inte in den, och är
   inte tänkt att göra det. Bolagsverkets API släpper bara igenom anropare som
   har ett tecknat avtal, presenterar ett godkänt klientcertifikat över
   ömsesidig TLS och ringer från en brandväggsöppnad IP-adress. En webbläsare
   gör inget av det: den presenterar inget klientcertifikat för en främmande
   värd, och API:et svarar utan CORS-huvuden.

   Sidan byggde en gång anropsobjekten ändå, med en lokal mTLS-proxy som utväg.
   Det togs bort med flit. Att lägga fram tre färdiga anrop som i praktiken
   aldrig kan skickas ser ut som en väg framåt utan att vara det, och proxyn
   var en säkerhetsrisk beskriven i dokumentationsform. Det som återstår är
   det som faktiskt bär: läsa filen och kontrollera den mot det
   /kontrollera tittar på, innan den lämnar datorn.

   Kontrollerna är därför filens inre konsistens plus det formuläret säger.
   De register-stödda kontrollerna — krav på revisionsberättelse per period,
   vilket organ som avger rapporten, om undertecknaren finns bland
   företrädarna, om en årsredovisning för perioden redan kommit in — satt
   bakom samma certifikat och försvann med det.

   Ingenting laddas upp och ingenting sparas.
   ========================================================================== */

const KVOT_ARSRED = (() => {
  'use strict';

  // ── Constants ─────────────────────────────────────────────────────────────

  const NS = Object.freeze({
    xhtml: 'http://www.w3.org/1999/xhtml',
    ix11:  'http://www.xbrl.org/2013/inlineXBRL',
    ix10:  'http://www.xbrl.org/2008/inlineXBRL',
    xbrli: 'http://www.xbrl.org/2003/instance',
    link:  'http://www.xbrl.org/2003/linkbase',
    xlink: 'http://www.w3.org/1999/xlink',
  });

  /* The taxonomy host Bolagsverket's own entry points live on. A schemaRef
     somewhere else is not necessarily wrong — an extension taxonomy is
     allowed — but it is worth pointing out, because a local file path here is
     the single most common reason a package validates in a desktop tool and
     is rejected by the API. */
  const TAXONOMY_HOST = 'taxonomier.se';

  /* The identifier scheme Bolagsverket requires in every context. */
  const ENTITY_SCHEME = 'http://www.bolagsverket.se';

  /* Facts the K2 taxonomy expects in ix:hidden on every annual report. They
     carry the document-level facts — language, domicile, currency, amount
     format, which body adopted the report — that no visible text conveys. */
  const EXPECTED_HIDDEN = Object.freeze([
    ['SprakHandlingUpprattadList',      'språk handlingen är upprättad på'],
    ['LandForetagetsSateList',          'landet för företagets säte'],
    ['RedovisningsvalutaHandlingList',  'redovisningsvaluta'],
    ['BeloppsformatList',               'beloppsformat'],
    ['FinansiellRapportList',           'vilken rapport handlingen utgör'],
  ]);

  /* The fastställelseintyg — the statement that the general meeting adopted
     the income statement and balance sheet, and that the electronic document
     matches the signed original. An annual report filed without it is not a
     complete filing. The taxonomy's own element for the date is spelled
     "Fastallelse"; both spellings are accepted here so a file tagged against
     a corrected taxonomy is not reported as missing it. */
  const FASTSTALLELSE = Object.freeze([
    ['FaststallelseResultatBalansrakning', 'intyg om fastställd resultat- och balansräkning'],
    ['Arsstamma',                          'datum för årsstämman'],
    ['IntygandeOriginalInnehall',          'intyg om att innehållet motsvarar originalet'],
  ]);
  const FASTSTALLELSE_DATUM = Object.freeze([
    'UnderskriftFastallelseintygDatum',
    'UnderskriftFaststallelseintygDatum',
  ]);

  /* Elements that must not appear: a filed document is a static record, and
     anything that fetches or executes turns it into something else. */
  const FORBIDDEN_ELEMENTS = Object.freeze([
    'script', 'iframe', 'frame', 'frameset', 'object', 'embed', 'applet',
    'form', 'input', 'button', 'textarea', 'select', 'audio', 'video',
    'source', 'track', 'canvas', 'base', 'meta[http-equiv=refresh]',
  ]);

  /* 64 MB. Well above any real annual report — the example filings are a
     hundred kilobytes — but low enough that a mis-dropped archive is caught
     before the tab stops responding. The API's own limit is stated in the
     tekniska guiden; this is only a guard on reading the file into memory. */
  const MAX_FILE_BYTES = 64 * 1024 * 1024;

  // ── State ─────────────────────────────────────────────────────────────────

  /* One object rather than scattered globals, so "what does the page know"
     has a single answer and clearing it is one assignment. */
  const state = {
    file: null,        // the File the user dropped
    bytes: null,       // Uint8Array of its contents
    text: null,        // decoded as UTF-8
    doc: null,         // parsed XHTML document, or null if it would not parse
    parseError: null,  // the parser's message, when it would not
    ixNS: null,        // which inline XBRL namespace the file uses
    sha: null,         // SHA-256 of the bytes, hex
    findings: [],      // results of the local check
    orgnrInFile: null, // entity identifier found in the contexts
  };

  // ── Small helpers ─────────────────────────────────────────────────────────

  const $ = (id) => document.getElementById(id);

  function text(id, value) {
    const el = $(id);
    if (el) el.textContent = value;
  }

  function els(doc, ns, local) {
    return Array.from(doc.getElementsByTagNameNS(ns, local));
  }

  /** Local part of a QName such as "se-gen-base:Tillgangar". */
  function localName(qname) {
    const value = String(qname || '');
    const colon = value.indexOf(':');
    return colon === -1 ? value : value.slice(colon + 1);
  }

  /**
   * Luhn check over a run of digits.
   *
   * Both organisationsnummer and personnummer carry a Luhn check digit over
   * their last ten digits, so a typo is caught here rather than three calls
   * later as a 404 from the API.
   *
   * @param {string} digits - Exactly the digits to check, no separators
   * @returns {boolean}
   */
  function luhnOK(digits) {
    if (!/^\d+$/.test(digits)) return false;
    let sum = 0;
    let double = digits.length % 2 === 0;
    for (const character of digits) {
      let value = Number(character);
      if (double) {
        value *= 2;
        if (value > 9) value -= 9;
      }
      sum += value;
      double = !double;
    }
    return sum % 10 === 0;
  }

  /** Ten digits, no hyphen — the shape Bolagsverket's `orgnr` field takes. */
  function normaliseOrgnr(value) {
    return String(value || '').replace(/\D/g, '');
  }

  function formatBytesLocal(bytes) {
    return typeof kvotFormatBytes === 'function'
      ? kvotFormatBytes(bytes)
      : `${bytes} B`;
  }

  // ── Reading the file ──────────────────────────────────────────────────────

  /**
   * SHA-256 of the bytes, i hex.
   *
   * Filen är en handling som ska gå att känna igen: samma fil ska ge samma
   * summa i morgon, och en fil som fått en byte ändrad ska inte göra det. Det
   * är också det Bolagsverket ekar tillbaka som `sha256checksumma` när en
   * handling väl kommit in, för den som vill jämföra.
   *
   * @param {Uint8Array} bytes
   * @returns {Promise<string|null>} null där WebCrypto saknas — under file://
   *   finns ingen säker kontext
   */
  async function sha256(bytes) {
    if (!(window.crypto && window.crypto.subtle)) return null;
    const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', bytes));
    return Array.from(digest, b => b.toString(16).padStart(2, '0')).join('');
  }

  /**
   * Take a dropped or chosen file into state, then check it.
   * @param {File} file
   * @returns {Promise<void>}
   */
  async function loadFile(file) {
    if (!file) return;

    const tooLarge = typeof kvotFileTooLarge === 'function'
      ? kvotFileTooLarge(file, MAX_FILE_BYTES)
      : { tooLarge: file.size > MAX_FILE_BYTES, reason: 'Filen är för stor.' };
    if (tooLarge.tooLarge) {
      showFailureBanner(tooLarge.reason, 'error');
      return;
    }

    resetFile();
    state.file = file;
    state.bytes = new Uint8Array(await file.arrayBuffer());

    /* fatal:true so invalid UTF-8 throws instead of being papered over with
       replacement characters — the API requires UTF-8, and a file that is
       really Latin-1 has to be reported as such and not quietly mangled. */
    try {
      state.text = new TextDecoder('utf-8', { fatal: true }).decode(state.bytes);
    } catch (error) {
      ignoreFailure('arsred.decode', error);
      state.text = null;
    }

    if (state.text !== null) parseDocument();

    state.sha = await sha256(state.bytes);

    renderFileSummary();
    refreshExportButtons();
    check();
  }

  function resetFile() {
    state.file = null;
    state.bytes = null;
    state.text = null;
    state.doc = null;
    state.parseError = null;
    state.ixNS = null;
    state.sha = null;
    state.findings = [];
    state.orgnrInFile = null;
  }

  /**
   * Parse the text as XHTML and work out which iXBRL namespace it uses.
   *
   * Deliberately parsed as application/xhtml+xml rather than text/html: an
   * HTML parser repairs almost anything, so a file with a malformed tag would
   * look fine here and be rejected by the API. The strict parser fails in the
   * same place Bolagsverket's will.
   */
  function parseDocument() {
    const parsed = new DOMParser().parseFromString(state.text, 'application/xhtml+xml');
    const failure = parsed.getElementsByTagName('parsererror')[0];
    if (failure) {
      state.parseError = (failure.textContent || 'okänt XML-fel').replace(/\s+/g, ' ').trim();
      return;
    }
    state.doc = parsed;
    state.ixNS = parsed.getElementsByTagNameNS(NS.ix11, '*').length ? NS.ix11
      : parsed.getElementsByTagNameNS(NS.ix10, '*').length ? NS.ix10
      : null;
  }

  // ── Numeric facts ─────────────────────────────────────────────────────────

  /**
   * The value an ix:nonFraction carries, as a number.
   *
   * The element's text is written for a reader — "7 773 000", "1 485" with
   * scale="3" — so the transformation in @format, the @scale exponent and the
   * @sign have all to be undone before two facts can be compared.
   *
   * @param {Element} el
   * @returns {number|null} null when the text is not a number after all
   */
  function factNumber(el) {
    let raw = (el.textContent || '')
      .replace(/[\s\u00a0\u202f]/g, '')          // thin and non-breaking group separators
      .replace(/[\u2212\u2013\u2014]/g, '-');    // typographic minus signs
    const format = el.getAttribute('format') || '';

    /* The ixt transformations name their separators: numspacecomma and
       numdotcomma put the decimal point on the comma, numcommadot and
       numspacedot on the dot. Without a format, fall back to whichever
       separator comes last, which is what a reader would assume. */
    if (/comma$/i.test(format)) {
      raw = raw.replace(/\./g, '').replace(',', '.');
    } else if (/dot$/i.test(format)) {
      raw = raw.replace(/,/g, '');
    } else {
      const lastComma = raw.lastIndexOf(',');
      const lastDot = raw.lastIndexOf('.');
      raw = lastComma > lastDot
        ? raw.replace(/\./g, '').replace(',', '.')
        : raw.replace(/,/g, '');
    }

    let value = Number(raw);
    if (!Number.isFinite(value)) return null;

    const scale = Number(el.getAttribute('scale'));
    if (Number.isFinite(scale)) value *= Math.pow(10, scale);
    if (el.getAttribute('sign') === '-') value = -value;
    return value;
  }

  /**
   * How far two facts may differ and still be the same figure.
   *
   * A fact reported with decimals="-3" is accurate to the thousand, so two
   * such facts can legitimately differ by up to half a thousand each without
   * either being wrong. Flagging that as an unbalanced balance sheet would be
   * a false alarm on every report presented in tkr.
   *
   * @param {Element} el
   * @returns {number}
   */
  function factTolerance(el) {
    const decimals = el.getAttribute('decimals');
    if (decimals === null || decimals === 'INF') return 0;
    const d = Number(decimals);
    return Number.isFinite(d) ? 0.5 * Math.pow(10, -d) : 0;
  }

  // ── The local check ───────────────────────────────────────────────────────

  function finding(list, level, title, detail) {
    list.push({ level, title, detail: detail || '' });
  }

  /**
   * Run every local check and render the result.
   *
   * These mirror what /kontrollera looks at; they are not a substitute for it.
   * Passing here means the file is unlikely to be rejected out of hand, not
   * that Bolagsverket will accept it — only the API knows the current
   * taxonomy versions and business rules.
   *
   * @returns {void}
   */
  function check() {
    const f = [];

    if (!state.file) {
      state.findings = [];
      renderFindings();
      return;
    }

    checkEncoding(f);
    checkStructure(f);
    if (state.doc) {
      checkTaxonomy(f);
      checkIdentity(f);
      checkPeriods(f);
      checkHidden(f);
      checkFaststallelse(f);
      checkBalance(f);
      checkReferences(f);
      checkContent(f);
    }

    state.findings = f;
    renderFindings();
  }

  function checkEncoding(f) {
    if (state.text === null) {
      finding(f, 'error', 'Filen är inte UTF-8',
        'Byten går inte att avkoda som UTF-8. Tjänsten kräver charset UTF-8 '
        + '(Handling.fil i servicespecifikationen). Spara om filen som UTF-8.');
      return;
    }
    finding(f, 'ok', 'Filen är giltig UTF-8', `${formatBytesLocal(state.bytes.length)}, ${state.bytes.length} byte.`);

    const bom = state.bytes.length >= 3
      && state.bytes[0] === 0xef && state.bytes[1] === 0xbb && state.bytes[2] === 0xbf;
    if (bom) {
      finding(f, 'warn', 'Filen inleds med en UTF-8 BOM',
        'XML tillåter en BOM, men den räknas med i dokumentlängden och alla verktyg '
        + 'hanterar den inte lika. Ta bort den om kontrollen ger oväntade fel.');
    }

    const declaration = /^<\?xml[^>]*encoding\s*=\s*["']([^"']+)["']/i.exec(state.text);
    if (declaration && !/^utf-?8$/i.test(declaration[1])) {
      finding(f, 'error', `XML-deklarationen anger ${declaration[1]}`,
        'Deklarationen ska ange UTF-8, annars läser mottagaren filen med fel teckenuppsättning.');
    }
  }

  function checkStructure(f) {
    if (state.text === null) return;
    if (!state.doc) {
      finding(f, 'error', 'Filen är inte välformad XML', state.parseError || '');
      return;
    }

    const root = state.doc.documentElement;
    if (root.namespaceURI !== NS.xhtml || root.localName !== 'html') {
      finding(f, 'error', 'Rotelementet är inte XHTML-html',
        `Hittade <${root.nodeName}> i ${root.namespaceURI || 'inget namnrymd'}. `
        + 'En iXBRL-handling är ett XHTML-dokument.');
    } else {
      finding(f, 'ok', 'Välformat XHTML-dokument', '');
    }

    if (state.ixNS === NS.ix11) {
      finding(f, 'ok', 'Inline XBRL 1.1', NS.ix11);
    } else if (state.ixNS === NS.ix10) {
      finding(f, 'warn', 'Inline XBRL 1.0',
        'Filen använder namnrymden från 2008. Bolagsverkets taxonomier bygger på '
        + 'Inline XBRL 1.1 (' + NS.ix11 + ').');
    } else {
      finding(f, 'error', 'Ingen Inline XBRL-markup hittad',
        'Dokumentet innehåller inga element i någon ix-namnrymd — det är en vanlig '
        + 'XHTML-fil, inte en taggad årsredovisning.');
    }
  }

  function checkTaxonomy(f) {
    const refs = els(state.doc, NS.link, 'schemaRef');
    if (!refs.length) {
      finding(f, 'error', 'Ingen link:schemaRef',
        'Utan en schemaRef i ix:references vet mottagaren inte vilken taxonomi '
        + 'handlingen är taggad mot.');
      return;
    }
    const hrefs = refs.map(r => r.getAttributeNS(NS.xlink, 'href') || r.getAttribute('href') || '');
    finding(f, 'ok', `${hrefs.length} taxonomiingång${hrefs.length === 1 ? '' : 'ar'}`, hrefs.join('\n'));

    for (const href of hrefs) {
      if (!/^https?:\/\//i.test(href)) {
        finding(f, 'error', 'Taxonomiingången är inte en absolut URL',
          `"${href}" ser ut som en lokal sökväg. Mottagaren kan inte lösa upp den — `
          + 'ange den publicerade URL:en till taxonomins entry point.');
      } else if (!href.includes(TAXONOMY_HOST)) {
        finding(f, 'warn', 'Taxonomiingång utanför taxonomier.se',
          `${href} — kontrollera att den ingår i en godkänd kombination enligt `
          + '"Kombinationer av taxonomirapporter".');
      }
    }
  }

  function checkIdentity(f) {
    const identifiers = els(state.doc, NS.xbrli, 'identifier');
    if (!identifiers.length) {
      finding(f, 'error', 'Inget organisationsnummer i något context',
        'Varje xbrli:context ska ha en xbrli:identifier med företagets organisationsnummer.');
      return;
    }

    const values = new Set(identifiers.map(el => (el.textContent || '').trim()));
    const schemes = new Set(identifiers.map(el => el.getAttribute('scheme') || ''));

    if (values.size > 1) {
      finding(f, 'error', 'Olika organisationsnummer i olika context',
        Array.from(values).join(', ') + ' — alla context ska avse samma företag.');
    }

    const value = Array.from(values)[0];
    state.orgnrInFile = value;

    if (!/^\d{6}-\d{4}$/.test(value)) {
      finding(f, 'error', 'Organisationsnumret har fel format',
        `"${value}" — taxonomin skriver organisationsnumret med bindestreck, NNNNNN-NNNN.`);
    } else if (!luhnOK(value.replace('-', ''))) {
      finding(f, 'error', 'Organisationsnumret har fel kontrollsiffra',
        `${value} — sista siffran stämmer inte med Luhn-kontrollen. Exempelfilerna på `
        + 'taxonomier.se använder 556999-9999, som är påhittat och faller på just den här '
        + 'kontrollen; en riktig handling ska inte göra det.');
    } else {
      finding(f, 'ok', 'Organisationsnummer i filen', value);
    }

    for (const scheme of schemes) {
      if (scheme !== ENTITY_SCHEME) {
        finding(f, 'error', 'Fel identifier scheme',
          `scheme="${scheme}" — ska vara ${ENTITY_SCHEME}.`);
      }
    }

    /* The orgnr in the form is the company the report is meant to be for;
       the one in the file is the company it says it is for. If they differ,
       someone is about to file one company's report under another's name —
       which is the kind of mistake a lone file cannot reveal. */
    const typed = normaliseOrgnr($('orgnr') && $('orgnr').value);
    if (typed.length === 10 && value && normaliseOrgnr(value) !== typed) {
      finding(f, 'error', 'Organisationsnumret i formuläret matchar inte filen',
        `Formulär: ${typed}, fil: ${value}.`);
    }
  }

  function checkPeriods(f) {
    const first = hiddenFact('RakenskapsarForstaDag');
    const last = hiddenFact('RakenskapsarSistaDag');

    if (!first || !last) {
      finding(f, 'warn', 'Räkenskapsårets datum saknas',
        'RakenskapsarForstaDag och RakenskapsarSistaDag förväntas enligt '
        + 'tillämpningsanvisningen för iXBRL. De styr vilken period inlämningen avser.');
      return;
    }

    /* A context whose duration is exactly the financial year is the one every
       result-statement fact hangs off. Its absence means the facts are dated
       against something other than the year the report claims to cover. */
    const durations = els(state.doc, NS.xbrli, 'context').filter(c =>
      c.getElementsByTagNameNS(NS.xbrli, 'startDate').length);
    const match = durations.find(c =>
      (c.getElementsByTagNameNS(NS.xbrli, 'startDate')[0].textContent || '').trim() === first
      && (c.getElementsByTagNameNS(NS.xbrli, 'endDate')[0].textContent || '').trim() === last);

    if (match) {
      finding(f, 'ok', `Räkenskapsår ${first} – ${last}`, `context id="${match.getAttribute('id')}"`);
    } else {
      finding(f, 'error', 'Inget context täcker räkenskapsåret',
        `RakenskapsarForstaDag/SistaDag säger ${first} – ${last}, men inget `
        + 'xbrli:context har den start- och slutdagen.');
    }

    const instants = els(state.doc, NS.xbrli, 'instant').map(el => (el.textContent || '').trim());
    if (!instants.includes(last)) {
      finding(f, 'warn', 'Inget balansdagscontext på räkenskapsårets sista dag',
        `Ingen xbrli:instant är ${last}; balansposterna hör normalt till ett sådant context.`);
    }
    if (instants.length < 2) {
      finding(f, 'warn', 'Inga jämförelsetal',
        'Bara en balansdag finns i filen. En årsredovisning redovisar normalt '
        + 'föregående år som jämförelseår.');
    }
  }

  /** The text of a fact by local element name, from anywhere in the document. */
  function hiddenFact(name) {
    const fact = allFacts().find(el => localName(el.getAttribute('name')) === name);
    return fact ? (fact.textContent || '').trim() : null;
  }

  function allFacts() {
    if (!state.doc || !state.ixNS) return [];
    return [
      ...els(state.doc, state.ixNS, 'nonNumeric'),
      ...els(state.doc, state.ixNS, 'nonFraction'),
      ...els(state.doc, state.ixNS, 'fraction'),
    ];
  }

  function checkHidden(f) {
    const present = new Set(allFacts().map(el => localName(el.getAttribute('name'))));
    const missing = EXPECTED_HIDDEN.filter(([name]) => !present.has(name));
    if (!missing.length) {
      finding(f, 'ok', 'Dokumentuppgifter taggade',
        EXPECTED_HIDDEN.map(([name]) => name).join(', '));
      return;
    }
    finding(f, 'warn', 'Dokumentuppgifter saknas',
      missing.map(([name, what]) => `${name} (${what})`).join('\n')
      + '\nDe förväntas enligt tillämpningsanvisningen för årsredovisningar i iXBRL-format.');
  }

  /**
   * Whether the document carries auditor's-report tagging.
   *
   * Used both by the handlingstyp check and, once the register has been
   * consulted, by the one that knows whether an auditor's report is required
   * at all — so it lives outside either of them.
   *
   * @returns {boolean}
   */
  function documentHasRevision() {
    return allFacts().some(el => /Revisionsberattelse|Revisor/i.test(localName(el.getAttribute('name'))));
  }

  function checkFaststallelse(f) {
    const typ = $('typ') ? $('typ').value : 'arsredovisning_komplett';
    const present = new Set(allFacts().map(el => localName(el.getAttribute('name'))));

    const hasRevision = documentHasRevision();

    if (typ === 'revisionsberattelse') {
      if (hasRevision) {
        finding(f, 'ok', 'Filen innehåller revisionsberättelsetaggar', '');
      } else {
        finding(f, 'error', 'Ingen revisionsberättelse i filen',
          'Handlingstypen är revisionsberattelse, men inga element för '
          + 'revisionsberättelse är taggade.');
      }
      return;
    }

    const missing = FASTSTALLELSE.filter(([name]) => !present.has(name)).map(([name, what]) => `${name} (${what})`);
    if (!FASTSTALLELSE_DATUM.some(name => present.has(name))) {
      missing.push(`${FASTSTALLELSE_DATUM[0]} (datum för underskrift av fastställelseintyget)`);
    }

    if (missing.length) {
      finding(f, 'warn', 'Fastställelseintyget ser ofullständigt ut', missing.join('\n'));
    } else {
      finding(f, 'ok', 'Fastställelseintyg taggat', '');
    }

    if (typ === 'arsredovisning_komplett' && !hasRevision) {
      finding(f, 'info', 'Ingen revisionsberättelse i filen',
        'Handlingstypen arsredovisning_komplett används när revisionsberättelsen ligger '
        + 'i samma fil, eller när företaget inte behöver någon. Ska en separat '
        + 'revisionsberättelse lämnas in efteråt, välj arsredovisning_kompletteras.');
    }
    if (typ === 'arsredovisning_kompletteras' && hasRevision) {
      finding(f, 'warn', 'Revisionsberättelse finns redan i filen',
        'arsredovisning_kompletteras säger att revisionsberättelsen kommer som en egen '
        + 'fil, men filen innehåller redan revisionsberättelsetaggar.');
    }
  }

  function checkBalance(f) {
    const facts = state.ixNS ? els(state.doc, state.ixNS, 'nonFraction') : [];
    const byContext = new Map();

    for (const el of facts) {
      const name = localName(el.getAttribute('name'));
      if (name !== 'Tillgangar' && name !== 'EgetKapitalSkulder') continue;
      const context = el.getAttribute('contextRef') || '';
      if (!byContext.has(context)) byContext.set(context, {});
      byContext.get(context)[name] = el;
    }

    if (!byContext.size) {
      finding(f, 'info', 'Ingen balansomslutning taggad',
        'Varken Tillgangar eller EgetKapitalSkulder finns i filen, så balansräkningen '
        + 'kan inte summeras här.');
      return;
    }

    for (const [context, pair] of byContext) {
      if (!pair.Tillgangar || !pair.EgetKapitalSkulder) {
        finding(f, 'warn', `Balansräkningen är ensidig i context "${context}"`,
          `Bara ${pair.Tillgangar ? 'Tillgangar' : 'EgetKapitalSkulder'} är taggad.`);
        continue;
      }
      const assets = factNumber(pair.Tillgangar);
      const equity = factNumber(pair.EgetKapitalSkulder);
      if (assets === null || equity === null) {
        finding(f, 'warn', `Balansposterna i "${context}" går inte att tolka som tal`, '');
        continue;
      }
      const tolerance = factTolerance(pair.Tillgangar) + factTolerance(pair.EgetKapitalSkulder);
      const difference = assets - equity;
      if (Math.abs(difference) > tolerance) {
        finding(f, 'error', `Balansräkningen går inte ihop i context "${context}"`,
          `Tillgångar ${assets.toLocaleString('sv-SE')} − eget kapital och skulder `
          + `${equity.toLocaleString('sv-SE')} = ${difference.toLocaleString('sv-SE')}`
          + (tolerance ? ` (tillåten avrundning ±${tolerance.toLocaleString('sv-SE')})` : ''));
      } else {
        finding(f, 'ok', `Balansräkningen balanserar i context "${context}"`,
          `${assets.toLocaleString('sv-SE')} kr`);
      }
    }
  }

  function checkReferences(f) {
    const contexts = new Set(els(state.doc, NS.xbrli, 'context').map(c => c.getAttribute('id')));
    const units = new Set(els(state.doc, NS.xbrli, 'unit').map(u => u.getAttribute('id')));

    const danglingContext = new Set();
    const danglingUnit = new Set();
    let numericWithoutUnit = 0;
    let numericWithoutDecimals = 0;

    for (const el of allFacts()) {
      const contextRef = el.getAttribute('contextRef');
      if (contextRef && !contexts.has(contextRef)) danglingContext.add(contextRef);

      if (el.localName === 'nonFraction' || el.localName === 'fraction') {
        const unitRef = el.getAttribute('unitRef');
        if (!unitRef) numericWithoutUnit++;
        else if (!units.has(unitRef)) danglingUnit.add(unitRef);
        if (el.getAttribute('decimals') === null && el.getAttribute('precision') === null) {
          numericWithoutDecimals++;
        }
      }
    }

    if (danglingContext.size) {
      finding(f, 'error', 'contextRef pekar på context som inte finns',
        Array.from(danglingContext).join(', '));
    }
    if (danglingUnit.size) {
      finding(f, 'error', 'unitRef pekar på unit som inte finns',
        Array.from(danglingUnit).join(', '));
    }
    if (numericWithoutUnit) {
      finding(f, 'error', `${numericWithoutUnit} numeriska fakta saknar unitRef`,
        'Varje ix:nonFraction ska ange sin enhet.');
    }
    if (numericWithoutDecimals) {
      finding(f, 'error', `${numericWithoutDecimals} numeriska fakta saknar decimals`,
        'Utan decimals eller precision är faktumets noggrannhet odefinierad.');
    }
    if (!danglingContext.size && !danglingUnit.size && !numericWithoutUnit && !numericWithoutDecimals) {
      finding(f, 'ok', 'Alla referenser löser upp',
        `${allFacts().length} fakta, ${contexts.size} context, ${units.size} enheter.`);
    }
  }

  function checkContent(f) {
    const problems = [];

    for (const name of FORBIDDEN_ELEMENTS) {
      if (name.includes('[')) continue;
      const found = state.doc.getElementsByTagNameNS(NS.xhtml, name).length;
      if (found) problems.push(`${found} <${name}>`);
    }

    /* A document that fetches anything at render time is not self-contained:
       whoever opens it years from now gets a different document, or a broken
       one. Bolagsverket's own conversion to PDF sees only the bytes sent. */
    const external = new Set();
    let inlineHandlers = 0;

    for (const el of state.doc.getElementsByTagName('*')) {
      for (const attribute of el.attributes) {
        const name = attribute.name.toLowerCase();
        if (name.startsWith('on')) { inlineHandlers++; continue; }
        if (name !== 'src' && name !== 'href' && name !== 'xlink:href') continue;
        /* The taxonomy entry point is meant to be an external URL. */
        if (el.namespaceURI === NS.link) continue;
        const value = (attribute.value || '').trim();
        if (!value || value.startsWith('data:') || value.startsWith('#')) continue;
        /* A plain hyperlink in the running text is harmless — it is not
           fetched to render the page. */
        if (el.localName === 'a' && name === 'href') continue;
        external.add(`${el.localName}/@${attribute.name}: ${value}`);
      }
    }

    const refresh = Array.from(state.doc.getElementsByTagNameNS(NS.xhtml, 'meta'))
      .filter(m => (m.getAttribute('http-equiv') || '').toLowerCase() === 'refresh').length;
    if (refresh) problems.push(`${refresh} <meta http-equiv="refresh">`);

    if (problems.length) {
      finding(f, 'error', 'Aktivt eller interaktivt innehåll i handlingen',
        problems.join(', ') + '. En inlämnad handling ska vara ett statiskt dokument.');
    }
    if (inlineHandlers) {
      finding(f, 'error', `${inlineHandlers} inline-händelseattribut (on…)`,
        'Skript i en årsredovisning gör dokumentet beroende av var det öppnas.');
    }
    if (external.size) {
      finding(f, 'error', 'Handlingen hämtar externt innehåll',
        Array.from(external).slice(0, 10).join('\n')
        + (external.size > 10 ? `\n… och ${external.size - 10} till` : '')
        + '\nBädda in bilder och stilmallar i filen (data:-URI respektive <style>).');
    }
    if (!problems.length && !inlineHandlers && !external.size) {
      finding(f, 'ok', 'Handlingen är fristående', 'Inget skript, inga externa resurser.');
    }
  }

  // ── Rendering ─────────────────────────────────────────────────────────────

  function renderFileSummary() {
    const box = $('file-summary');
    if (!box) return;
    if (!state.file) {
      box.hidden = true;
      return;
    }
    box.hidden = false;
    box.innerHTML = `
      <dl class="ar-facts">
        <dt>Fil</dt><dd>${kvotEscapeHtml(state.file.name)}</dd>
        <dt>Storlek</dt><dd>${kvotEscapeHtml(formatBytesLocal(state.bytes.length))}
          (${state.bytes.length} byte)</dd>
        <dt>SHA-256</dt><dd>${state.sha
          ? `<code class="ar-hash">${kvotEscapeHtml(state.sha)}</code>`
          : 'kunde inte beräknas — kräver https eller localhost'}</dd>
      </dl>`;
  }

  const LEVEL_LABEL = { error: 'Fel', warn: 'Varning', info: 'Info', ok: 'OK' };

  function renderFindings() {
    const box = $('findings');
    if (!box) return;

    if (!state.findings.length) {
      box.innerHTML = '<p class="ar-empty">Ingen fil inläst ännu.</p>';
      text('findings-count', '');
      return;
    }

    const order = { error: 0, warn: 1, info: 2, ok: 3 };
    const sorted = state.findings.slice().sort((a, b) => order[a.level] - order[b.level]);
    const counts = state.findings.reduce((acc, item) => {
      acc[item.level] = (acc[item.level] || 0) + 1;
      return acc;
    }, {});

    text('findings-count',
      `${counts.error || 0} fel · ${counts.warn || 0} varningar · `
      + `${counts.info || 0} noteringar · ${counts.ok || 0} godkända`);

    box.innerHTML = sorted.map(item => `
      <div class="ar-finding ar-${item.level}">
        <span class="ar-badge">${LEVEL_LABEL[item.level]}</span>
        <div>
          <div class="ar-finding-title">${kvotEscapeHtml(item.title)}</div>
          ${item.detail ? `<pre class="ar-finding-detail">${kvotEscapeHtml(item.detail)}</pre>` : ''}
        </div>
      </div>`).join('');
  }

  // ── Actions ───────────────────────────────────────────────────────────────

  /**
   * Lämna den inlästa handlingen som Word eller PDF.
   *
   * @param {'docx'|'pdf'} kind
   * @returns {void}
   */
  function exportLoaded(kind) {
    if (!state.text) return notifyUser('Läs in en handling först.');
    KVOT_ARSRED_EXPORT.exportDocument(state.text, kind,
      (state.file && state.file.name) || 'arsredovisning');
  }

  /** Exportknapparna har bara mening när det finns en handling. */
  function refreshExportButtons() {
    for (const id of ['export-docx', 'export-pdf']) {
      const button = $(id);
      if (button) button.disabled = !state.text;
    }
  }

  registerActions({
    'ar:pick': () => $('file-input').click(),

    /* The drop zone is a div, so Enter and Space reach it as keydown and
       never as a click. Without this it is reachable by tab and then dead. */
    'ar:pick-key': (event) => {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      event.preventDefault();
      $('file-input').click();
    },

    'ar:file': (event) => loadFile(event.target.files && event.target.files[0]),

    /* Re-checking on every field change keeps the orgnr comparison and the
       handlingstyp checks honest — they depend on the form, not only the file. */
    'ar:recheck': () => { check(); },

    /* Exporten fungerar lika bra på en handling som någon annan skrivit —
       det är samma sorts fil, och det är den inlästa texten som läses. */
    'ar:docx': () => exportLoaded('docx'),
    'ar:pdf': () => exportLoaded('pdf'),

    'ar:clear': () => {
      resetFile();
      if ($('file-input')) $('file-input').value = '';
      renderFileSummary();
      refreshExportButtons();
      renderFindings();
    },
  });

  // ── Drag and drop ─────────────────────────────────────────────────────────

  function mountDropZone() {
    const zone = $('drop-zone');
    if (!zone) return;
    for (const type of ['dragenter', 'dragover']) {
      zone.addEventListener(type, (event) => {
        event.preventDefault();
        zone.classList.add('dragging');
      });
    }
    for (const type of ['dragleave', 'drop']) {
      zone.addEventListener(type, (event) => {
        event.preventDefault();
        zone.classList.remove('dragging');
      });
    }
    zone.addEventListener('drop', (event) => {
      const file = event.dataTransfer && event.dataTransfer.files && event.dataTransfer.files[0];
      if (file) loadFile(file).catch(error => reportFailure('arsred.drop', error));
    });
  }

  // ── Start ─────────────────────────────────────────────────────────────────

  function init() {
    mountDropZone();
    refreshExportButtons();
    renderFindings();
  }

  return { init };
})();
