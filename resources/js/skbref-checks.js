/* ==========================================================================
   SKB REFERENCE CHECKER — checks

   The writing-rule engine: what each rule needs to see, chemistry and
   formatting checks, reference-list ordering and collation.

   Part of the page script that used to live inline in skbref.html. The
   modules share one global scope, as classic scripts do, and are loaded in
   the order they were written in; skbref-boot.js runs everything.

   The four-space indent is from the <script> block this came out of, and is
   kept deliberately: removing it would also remove four spaces from every
   line inside a multi-line template literal, changing the whitespace of the
   HTML this page generates.
   ========================================================================== */
'use strict';

    function makeOfficialIssue({ match, description, source, paragraph, context, severity = 'warning', ruleId = '', ruleName = '', legacyRuleIds = [], category = 'technical', matchStart = null, matchEnd = null }) {
      return {
        match,
        description,
        ruleId: ruleId || `official-${readableRuleSlug(description||match)||stableRuleHash(`${description}|${match}`)}`,
        ruleName: ruleName || description || 'Official SKB rule', legacyRuleIds,
        category, matchStart, matchEnd,
        source: SKB_RULE_SOURCES[source] || source,
        paragraphIndex: paragraph?.index ?? null,
        section: paragraph?.section || '',
        context: context || paragraph?.text || '',
        fullContext: paragraph?.text || context || '',
        language: paragraph?.language || 'unknown',
        languageConfidence: paragraph?.languageConfidence || 0,
        languageSource: paragraph?.languageSource || 'unknown',
        languageRanges: paragraph?.languageRanges || [],
        severity
      };
    }

    /*
      What the source format lets a rule see. The .docx path records every
      distinction the guides are written in terms of; the PDF path does not,
      and says which — see PDF_CAPABILITIES in resources/js/skb-pdf.js.
    */
    const FULL_CAPABILITIES = Object.freeze({
      'space-characters': true, 'underline': true, 'field-codes': true,
      'table-context': true, 'paragraph-styles': true, 'character-styles': true
    });

    function ruleEvidenceAvailable(rule, capabilities) {
      return !rule.needs || capabilities[rule.needs] !== false;
    }

    /*
      A match that straddles a reconstructed line break is partly the
      reconstruction's own work: reading a PDF, the line break was replaced
      either by a space or by a joined-up word. Where the rule is about a dash,
      that character is exactly what was decided there, so the finding would be
      reporting the layout rather than the text.
    */
    function matchCrossesReconstructedBreak(paragraph, start, end, matched) {
      const joins = paragraph.joins;
      if (!joins || !joins.length) return false;
      if (!/[-–—‐]/.test(matched)) return false;
      return joins.some(offset => offset > start && offset < end);
    }

    function findOfficialSkbTextIssues(paragraphs, languageProfile, capabilities = FULL_CAPABILITIES) {
      const issues = [];
      /* Compatibility value for non-pattern checks that still choose Swedish
         or English wording at document level. Pattern rules use local run and
         paragraph language through languageAtRange(). */
      const isSwedish = languageProfile?.language === 'sv';
      const documentLanguage = languageProfile?.language || 'unknown';

      for (const paragraph of paragraphs) {
        const text = paragraph.text || '';

        /* Heading checks use the Word heading style, or, reading a PDF, the
           level inferred from the type size. */
        if (headingLevel(paragraph.style) > 0 && text) {
          if (/[.!?]$/.test(text)) {
            issues.push(makeOfficialIssue({
              match: text,
              description: 'Headings should not end with punctuation.',
              source: 'handbook', paragraph
            }));
          }
          if (text.trim().split(/\s+/).length > 6) {
            issues.push(makeOfficialIssue({
              match: text,
              description: 'Keep headings as short as possible, preferably fewer than six words.',
              source: 'handbook', paragraph, severity: 'review'
            }));
          }
        }

        if (/^\s*\d/.test(text) && /[.!?](?:\s|$)/.test(text)) {
          issues.push(makeOfficialIssue({
            match: text.match(/^\s*\S+/)?.[0] || text.slice(0, 20),
            description: 'A sentence should not begin with a numeral; spell out the number or rewrite the sentence.',
            source: 'technical', paragraph, severity: 'review'
          }));
        }

        for (const rule of OFFICIAL_SKB_TEXT_RULES) {
          const expression = new RegExp(rule.pattern, rule.flags || 'gu');
          let match;
          while ((match = expression.exec(text)) !== null) {
            const localLanguage = languageAtRange(paragraph, match.index, match.index + match[0].length);
            const effectiveLanguage = ['sv','en'].includes(localLanguage.language) && localLanguage.confidence >= .6 ? localLanguage.language : documentLanguage;
            if (rule.language && !['mixed','unknown'].includes(effectiveLanguage) && rule.language !== effectiveLanguage) continue;
            if (!ruleEvidenceAvailable(rule, capabilities)) continue;
            if (matchCrossesReconstructedBreak(paragraph, match.index, match.index + match[0].length, match[0])) continue;
            if (rule.custom === 'unit-space') {
              const between = match[0].match(/^\d+(.*?)[A-Za-zµ]/)?.[1] || '';
              if (between.includes('\u00a0')) continue;
            }
            if (rule.reject && new RegExp(rule.reject, 'u').test(match[0])) continue;
            const start = Math.max(0, match.index - 55);
            const end = Math.min(text.length, match.index + match[0].length + 55);
            issues.push(makeOfficialIssue({
              match: match[0], description: rule.description, source: rule.source,
              ruleId: rule.id, ruleName: rule.label, legacyRuleIds: rule.legacyIds || [], category: rule.category, severity: rule.severity,
              matchStart: match.index, matchEnd: match.index + match[0].length,
              paragraph,
              context: `${start > 0 ? '…' : ''}${text.slice(start, end)}${end < text.length ? '…' : ''}`
            }));
            if (!match[0].length) expression.lastIndex++;
          }
        }

        /* Official Harvard citation punctuation checks. */
        for (const group of extractCitationParentheticalGroups(text)) {
          const content = group.content;
          if (!/(?:1[89]\d{2}|20\d{2})/.test(content)) continue;

          for (const commaYear of content.matchAll(/(?:^|[;,]\s*)([^;,()]{1,80}?),\s*((?:1[89]\d{2}|20\d{2})[a-z]?)/gu)) {
            issues.push(makeOfficialIssue({
              match: commaYear[0].replace(/^[;,]\s*/, ''),
              description: 'Do not place a comma between the author name and publication year in an SKB Harvard in-text citation.',
              source: 'references', paragraph, context: group.raw
            }));
          }

          if (/;/.test(content)) {
            issues.push(makeOfficialIssue({
              match: group.raw,
              description: 'Separate different sources with commas, not semicolons, in an SKB Harvard citation.',
              source: 'references', paragraph, context: group.raw
            }));
          }

          if (/\b[\p{L}][\p{L}'’\-]*\s*&\s*[\p{L}]/u.test(content)) {
            issues.push(makeOfficialIssue({
              match: group.raw,
              description: isSwedish ? 'Use “och”, not &, between two authors in a Swedish in-text citation.' : 'Use “and”, not &, between two authors in an English in-text citation.',
              source: 'references', paragraph, context: group.raw
            }));
          }

          if (/\([Ee][Dd]\)/.test(content)) {
            issues.push(makeOfficialIssue({
              match: group.raw,
              description: 'Do not include the editor suffix “(ed)” in an in-text citation; cite the editor surname and year only.',
              source: 'references', paragraph, context: group.raw
            }));
          }

          if (/\b(?:p|pp)\./i.test(content)) {
            issues.push(makeOfficialIssue({
              match: group.raw,
              description: 'Write p or pp without a period in an English page citation.',
              source: 'references', paragraph, context: group.raw
            }));
          }

          if (isSwedish && /\b(?:p|pp)\s+\d/i.test(content)) {
            issues.push(makeOfficialIssue({
              match: group.raw,
              description: 'Use “s” for page references in Swedish text, not p or pp.',
              source: 'references', paragraph, context: group.raw
            }));
          }
        }

        /*
          A coefficient in a chemical reaction is written directly against the
          formula (2HCl, not 2 HCl). Only checked inside something that really
          is a reaction, so ordinary sentences such as "2 samples" are safe.
        */
        if (/[→⇄⇌]/.test(text)) {
          for (const match of text.matchAll(/(?<![\p{L}\d])(\d+)\s+(?=[A-Z][a-z]?\d*(?:[A-Z(]|\b))/gu)) {
            issues.push(makeOfficialIssue({
              match: match[0].trim(),
              description: 'Write the coefficient directly against the formula in a chemical reaction, for example 2HCl.',
              source: 'technical', paragraph, context: text
            }));
          }
        }

        /*
          Two numbered elements that follow each other are joined with "and",
          not with an en dash (Figures 1.1 and 1.2, Chapters 9 and 10).
        */
        for (const match of text.matchAll(/\b(Figures?|Tables?|Chapters?|Sections?|Appendices|Equations?|Figurer?|Tabeller?|Kapitel|Avsnitt|Bilagor?|Ekvationer?)\s+(\d+(?:[.-]\d+)*)\s*[–-]\s*(\d+(?:[.-]\d+)*)/giu)) {
          const first = match[2].split(/[.-]/).pop();
          const second = match[3].split(/[.-]/).pop();
          if (Number(second) - Number(first) === 1) {
            issues.push(makeOfficialIssue({
              match: match[0],
              description: 'Join two adjacent numbered elements with “and”, not with an en dash.',
              source: 'technical', paragraph, context: text
            }));
          }
        }

        /*
          High-confidence mathematical spacing checks.
          Hyphenated identifiers and internal cross-references such as
          Figure 1-1, Table 2-3, Section 4-2, SKB TR-10-02, SFR1, and
          document numbers are not mathematical subtraction expressions.
          A plain hyphen is therefore checked separately and only in a
          mathematical-looking context.
        */
        const mathematicalOperatorExpression = /\d(?:[+−=×±<>])\d/g;
        for (const match of text.matchAll(mathematicalOperatorExpression)) {
          issues.push(makeOfficialIssue({
            match: match[0],
            description: 'Mathematical binary operators and relation signs should be surrounded by spaces.',
            source: 'technical', paragraph
          }));
        }

        const subtractionExpression = /(?<![\p{L}\d])[-+−]?\d+(?:[.,]\d+)?-[-+−]?\d+(?:[.,]\d+)?(?![\p{L}\d-])/gu;
        for (const match of text.matchAll(subtractionExpression)) {
          const before = text.slice(Math.max(0, match.index - 28), match.index);
          const after = text.slice(match.index + match[0].length, match.index + match[0].length + 28);
          const surrounding = `${before}${match[0]}${after}`;

          const isCrossReference = /(?:Figure|Figur|Table|Tabell|Section|Avsnitt|Chapter|Kapitel|Appendix|Bilaga|Equation|Ekvation)\s*$/i.test(before);
          const isIdentifier = /(?:SKB|SFR|SFL|Clab|SSMFS|SFS|ISO|IEC|EN|TR|R|P|IPR|RD|SR|TM|U|F|SKBdoc|document(?:\s+id)?|dokument(?:\s+id)?)\s*-?\s*$/i.test(before)
            /* Any publisher's report/issue number, e.g. "Nagra Technical Report 02-05". */
            || /(?:report|rapport|technical\s+report|no|nr|number|nummer|issue|utg[åa]va|version|ver|standard|serie|series|patent)\.?\s*$/i.test(before);
          const isRangeContext = /(?:range|interval|period|epoch|span|between|from|to|through|years?|pages?|samples?|temperatures?|sections?|figures?|tables?)\s*$/i.test(before) || /^\s*(?:years?|pages?|samples?|°C|K|kg|m|mm|cm|km|s|min|h|%|‰)\b/i.test(after);
          const isYearRange = /^(?:1[89]\d{2}|20\d{2})-(?:1[89]\d{2}|20\d{2})$/.test(match[0]);

          const tokenStart = Math.max(0, match.index - 14);
          const tokenEnd = Math.min(text.length, match.index + match[0].length + 2);
          const tokenContext = text.slice(tokenStart, tokenEnd);
          const isReportNumber = /(?:^|[^A-Za-z0-9])(?:SKB\s+)?(?:TR|R|P|IPR|RD|SR|TM|U|F)-\d{2,}-\d+(?=$|[^A-Za-z0-9])/i.test(tokenContext);

          if (isCrossReference || isIdentifier || isReportNumber) continue;

          if (isRangeContext || isYearRange) {
            issues.push(makeOfficialIssue({
              match: match[0],
              description: 'Use an en dash (–), not a hyphen, in a range.',
              source: 'technical', paragraph, context: surrounding
            }));
            continue;
          }

          issues.push(makeOfficialIssue({
            match: match[0],
            description: 'Possible subtraction written with a hyphen. Use a true minus sign and surround a binary subtraction operator with spaces. If this is an identifier or range, review it manually.',
            source: 'technical', paragraph,
            context: surrounding
          }));
        }
      }

      const seen = new Set();
      return issues.filter(issue => {
        const key = `${issue.paragraphIndex}\u0000${issue.match}\u0000${issue.description}`;
        if (seen.has(key)) return false;
        seen.add(key); return true;
      });
    }

    /* ── Character-formatting checks (chapters 4, 5 and 9 of the guides) ────── */

    const ELEMENT_SYMBOLS = new Set(('H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn '
      + 'Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho '
      + 'Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr').split(' '));

    /*
      Formulas made only of single capital letters are indistinguishable from
      project abbreviations — CCP33 parses as C, C, P just as well as a real
      formula does. A token therefore counts as chemistry only when it either
      contains a two-letter element symbol (Na, Ca, Fe …) or is one of the
      common formulas that SKB reports actually use.
    */
    const COMMON_FORMULAS = new Set(['H2O', 'D2O', 'CO2', 'CO3', 'HCO3', 'SO4', 'SO3', 'SO2', 'NO3', 'NO2',
      'NH4', 'NH3', 'PO4', 'HPO4', 'H2PO4', 'CH4', 'O2', 'N2', 'H2', 'H2S', 'H2SO4', 'HNO3', 'H3PO4', 'H2CO3']);

    function isChemicalFormula(token) {
      let index = 0, elements = 0, hasTwoLetterElement = false;
      while (index < token.length) {
        const character = token[index];
        if (/[()\[\]]/.test(character)) { index++; continue; }
        if (/\d/.test(character)) { index++; continue; }
        if (!/[A-Z]/.test(character)) return false;
        const two = token.slice(index, index + 2);
        if (two.length === 2 && /[a-z]/.test(two[1]) && ELEMENT_SYMBOLS.has(two)) {
          elements++; hasTwoLetterElement = true; index += 2; continue;
        }
        if (ELEMENT_SYMBOLS.has(character)) { elements++; index += 1; continue; }
        return false;
      }
      if (elements < 2) return false;
      return hasTwoLetterElement || COMMON_FORMULAS.has(token);
    }

    function formattingAt(paragraph, start, end) {
      const spans = (paragraph.formatSpans || []).filter(span => span.start < end && span.end > start);
      if (!spans.length) return null;
      return {
        sup: spans.every(span => span.sup),
        sub: spans.every(span => span.sub),
        italic: spans.every(span => span.italic),
        anySup: spans.some(span => span.sup),
        anySub: spans.some(span => span.sub)
      };
    }

    function findFormattingIssues(paragraphs, capabilities = FULL_CAPABILITIES) {
      const issues = [];
      for (const paragraph of paragraphs) {
        const text = paragraph.text || '';
        if (!text) continue;
        const spans = paragraph.formatSpans || [];
        if (!spans.length) continue;

        /* Skrivhandboken, section 9: never underline. An underline is drawn as
           a graphic in a PDF rather than recorded as a text attribute, so there
           the check is unavailable and not simply passing. */
        for (const span of capabilities.underline === false ? [] : spans) {
          if (!span.underline || span.inHyperlink) continue;
          issues.push(makeOfficialIssue({
            match: text.slice(span.start, Math.min(span.end, span.start + 60)) || 'underlined text',
            description: 'Do not underline text; use bold or italic when emphasis is needed.',
            source: 'handbook', paragraph, context: text
          }));
        }

        /*
          1469987, chapter 5: the number of like atoms is written as a
          subscript, and a mass number as a superscript before the symbol.
          Both checks require real element symbols, so report and project
          identifiers such as SFR1, CCP33 and TR-10-53 are never mistaken for
          chemistry.
        */
        const isReaction = /[→⇄⇌]/.test(text);
        for (const match of text.matchAll(/\b[A-Z][A-Za-z0-9]*\d[A-Za-z0-9]*\b/g)) {
          if (!isChemicalFormula(match[0])) continue;
          const digits = [...match[0].matchAll(/\d+/g)];
          if (!digits.length) continue;
          const unformatted = digits.filter(digit => {
            const start = match.index + digit.index;
            const state = formattingAt(paragraph, start, start + digit[0].length);
            return state && !state.anySub;
          });
          if (unformatted.length === digits.length) {
            issues.push(makeOfficialIssue({
              match: match[0],
              description: 'Write the number of atoms as a subscript in a chemical formula, for example H2SO4.',
              source: 'technical', paragraph, context: text, severity: 'review'
            }));
          }
        }

        /*
          A leading number is a mass number outside a reaction, but a
          stoichiometric coefficient inside one, so reactions are skipped.
        */
        if (!isReaction) {
          for (const match of text.matchAll(/(?<![\p{L}\d.\-−])(\d{1,3})([A-Z][a-z]?)(?![\p{L}\d])/gu)) {
            if (!ELEMENT_SYMBOLS.has(match[2])) continue;
            const state = formattingAt(paragraph, match.index, match.index + match[1].length);
            if (state && !state.anySup) {
              issues.push(makeOfficialIssue({
                match: match[0],
                description: 'Write the mass number as a superscript before the element symbol, for example 37Cl.',
                source: 'technical', paragraph, context: text, severity: 'review'
              }));
            }
          }
        }

        /*
          1215757, section 5: the ordinal suffix of an edition is not
          superscript.
        */
        if (paragraph.isReferenceList) {
          for (const match of text.matchAll(/\b\d+(st|nd|rd|th)\s+ed\b/g)) {
            const start = match.index + match[0].indexOf(match[1]);
            const state = formattingAt(paragraph, start, start + match[1].length);
            if (state && state.anySup) {
              issues.push(makeOfficialIssue({
                match: match[0],
                description: 'Do not write the ordinal suffix of an edition in superscript; write 4th ed.',
                source: 'references', paragraph, context: text
              }));
            }
          }
        }

        /*
          1469987, section 4.1: quantity symbols are italic. Checked only in
          the guide's own "where X is …" construction, where the single letter
          is unambiguously a quantity symbol — and only where italic can be
          seen at all, which in a PDF depends on the fonts being readable.
        */
        for (const match of capabilities['character-styles'] === false ? []
             : text.matchAll(/\b(?:where|där)\s+([A-Za-z])\s+(?:is|är)\b/g)) {
          const start = match.index + match[0].indexOf(match[1], match[0].search(/\s/));
          const state = formattingAt(paragraph, start, start + 1);
          if (state && !state.italic) {
            issues.push(makeOfficialIssue({
              match: match[0],
              description: 'Write quantity symbols in italics, for example “where V is the volume”.',
              source: 'technical', paragraph, context: text, severity: 'review'
            }));
          }
        }
      }
      return issues;
    }

    /*
      Chapter 5 of 1215757: the reference list is sorted alphabetically with
      u-diaeresis equal to y, the ae ligature to a-diaeresis and o-slash to
      o-diaeresis. Every other diacritic is ignored, as are hyphens, spaces and
      apostrophes, so a compound surname sorts as a single word.
    */
    const SKB_COLLATION_ALPHABET = 'abcdefghijklmnopqrstuvwxyzåäö';

    function skbSortKey(key) {
      const folded = String(key || '')
        .normalize('NFC')
        .toLowerCase()
        .replace(/ü/g, 'y')
        .replace(/æ/g, 'ä')
        .replace(/ø/g, 'ö')
        /* Park the three Swedish letters on characters that cannot occur in a
           name, so that stripping diacritics does not turn them into a and o. */
        .replace(/å/g, '{')
        .replace(/ä/g, '|')
        .replace(/ö/g, '}')
        .normalize('NFD')
        .replace(/[̀-ͯ]/g, '')
        .replace(/\{/g, 'å')
        .replace(/\|/g, 'ä')
        .replace(/\}/g, 'ö')
        .replace(/[\s\-'’.]/g, '');
      return [...folded]
        .map(character => {
          const position = SKB_COLLATION_ALPHABET.indexOf(character);
          return position < 0 ? character : String.fromCharCode(48 + position);
        })
        .join('');
    }

    /*
      Chapter 5 of 1215757 does not sort a reference list as one alphabetical
      run. Works sharing a first author are grouped in three tiers:

        – first the works by that author alone, chronologically
        – then the works with one co-author, alphabetically by the co-author
        – finally the works with two or more co-authors, chronologically

      Comparing the whole key as a string puts "Bentz A, Conway M, 2001" before
      "Bentz A, 2007", which reported the guide's own example as out of order.
    */
    function referenceSortFields(key) {
      const text = String(key || '').trim();
      const yearMatch = text.match(/((?:1[89]|20)\d{2})([a-z]?)\s*$/);
      const year = yearMatch ? yearMatch[1] + (yearMatch[2] || '') : '';
      const authors = (yearMatch ? text.slice(0, yearMatch.index) : text).trim();

      /* Three or more authors: the key carries only the first name plus et al. */
      const etAl = authors.match(/^(.*?)\s+(?:et\s+al\.?|m\.fl\.?)$/i);
      if (etAl) return { first: skbSortKey(etAl[1]), tier: 2, within: year };

      const pair = authors.split(/\s+(?:and|och)\s+/i);
      if (pair.length === 2) {
        return { first: skbSortKey(pair[0]), tier: 1, within: skbSortKey(pair[1]) + ' ' + year };
      }
      return { first: skbSortKey(authors), tier: 0, within: year };
    }

    /** Negative when `first` belongs before `second` in an SKB reference list. */
    function compareReferenceKeys(first, second) {
      const a = referenceSortFields(first), b = referenceSortFields(second);
      if (a.first !== b.first) return a.first < b.first ? -1 : 1;
      if (a.tier !== b.tier) return a.tier - b.tier;
      if (a.within !== b.within) return a.within < b.within ? -1 : 1;
      return 0;
    }

    function findReferenceListOrderIssues(entries) {
      const issues = [];
      /* Numbered lists keep their own order; only author-year lists are sorted. */
      const sortable = entries.filter(entry => entry.key && entry.num === null);
      for (let index = 1; index < sortable.length; index++) {
        const previous = sortable[index - 1], current = sortable[index];
        if (compareReferenceKeys(previous.key, current.key) > 0) {
          issues.push(makeOfficialIssue({
            match: current.key,
            description: 'Reference list out of alphabetical order: "' + current.key + '" is listed after "' + previous.key + '".',
            source: 'references',
            paragraph: { index: current.paraIndex, section: 'References', text: current.body },
            context: previous.key + ' / ' + current.key
          }));
        }
      }
      return issues;
    }

    /*
      Chapter 5 of 1215757: works by the same author from the same year are
      separated by a lower-case letter. A lone "1993a" therefore means the
      matching "1993b" is missing, and a bare year beside lettered ones is
      inconsistent.
    */
    function findYearSuffixIssues(entries) {
      const issues = [];
      const groups = new Map();
      for (const entry of entries) {
        const match = String(entry.key || '').match(/^(.*?)\s*((?:1[89]|20)\d{2})([a-z])?$/);
        if (!match) continue;
        const groupKey = match[1].toLowerCase() + ' ' + match[2];
        if (!groups.has(groupKey)) groups.set(groupKey, { author: match[1], year: match[2], suffixes: [], entries: [] });
        groups.get(groupKey).suffixes.push(match[3] || '');
        groups.get(groupKey).entries.push(entry);
      }
      for (const group of groups.values()) {
        const lettered = group.suffixes.filter(Boolean);
        if (!lettered.length) continue;
        const entry = group.entries[0];
        const paragraph = { index: entry.paraIndex, section: 'References', text: entry.body };
        if (lettered.length !== group.suffixes.length) {
          issues.push(makeOfficialIssue({
            match: group.author + ' ' + group.year,
            description: 'Some entries for ' + group.author + ' ' + group.year + ' carry a letter suffix and some do not; letter every work by the same author from the same year.',
            source: 'references', paragraph
          }));
          continue;
        }
        const expected = lettered.map((_, position) => String.fromCharCode(97 + position));
        const actual = [...lettered].sort();
        if (actual.join('') !== expected.join('')) {
          issues.push(makeOfficialIssue({
            match: group.author + ' ' + group.year + actual.join(', '),
            description: 'Letter suffixes for ' + group.author + ' ' + group.year + ' should run ' + expected.join(', ') + ' without gaps; the list has ' + actual.join(', ') + '.',
            source: 'references', paragraph
          }));
        }
      }
      return issues;
    }

    /*
      Chapter 6 of 1215757 tabulates the English forms against the Swedish ones
      a Swedish publication uses instead. "In" is recognised only in front of an
      editor name, because an English title inside a Swedish reference list may
      legitimately begin with the word.
    */
    const SWEDISH_REFERENCE_ABBREVIATIONS = Object.freeze([
      [/\(eds?\)/, '(red)'],
      [/\bPhD thesis\b/, 'Doktorsavh'],
      [/\bLic thesis\b/, 'Lic-avh'],
      [/,\s*n\s+d\b/, 'u å'],
      [/\bIn\s+[A-ZÅÄÖÀ-Þ][a-zåäöà-þ]+\s+[A-ZÅÄÖÀ-Þ]\b/, 'I'],
      [/\b\d+(?:st|nd|rd|th)\s+ed\b/, '2. uppl']
    ]);

    function findOfficialSkbReferenceIssues(entries, refParagraphs, isSwedish) {
      const issues = [];
      const allRefText = refParagraphs.map(p => p.text).join('\n');

      for (const entry of entries) {
        const paragraph = { index: entry.paraIndex, section: 'References', text: entry.body };
        const text = entry.body || '';

        if (/\bet\s+al\.?\b/i.test(text)) {
          issues.push(makeOfficialIssue({
            match: text.match(/\bet\s+al\.?\b/i)[0],
            description: 'Write all author names in the reference list; do not use et al.',
            source: 'references', paragraph
          }));
        }

        const authorBlock = text.match(/^(.+?),\s*(?:1[89]\d{2}|20\d{2})[a-z]?\b/);
        if (authorBlock && /\s(?:and|och|&)\s/i.test(authorBlock[1])) {
          issues.push(makeOfficialIssue({
            match: authorBlock[1],
            description: 'Separate all authors with commas in the reference list; do not use and, och or &.',
            source: 'references', paragraph
          }));
        }

        if (/^[^,]+,\s*[A-ZÅÄÖ](?:\.|,)/u.test(text)) {
          issues.push(makeOfficialIssue({
            match: text.slice(0, Math.min(45, text.length)),
            description: 'Do not place a comma after the surname or periods after author initials.',
            source: 'references', paragraph
          }));
        }

        if (/SKBdoc\s+\d+/i.test(text) && !/SKBdoc\s+\d+\s+ver(?:sion)?\s+\d/i.test(text)) {
          issues.push(makeOfficialIssue({
            match: text.match(/SKBdoc\s+\d+/i)[0],
            description: 'An SKBdoc reference must include its version.',
            source: 'references', paragraph
          }));
        }

        if (/\bSKB\s+(?:TR|R|P|IPR|RD|SR|TM|U|F)-\d{2,}-\d+\b/i.test(text) && /,\s*(?:Stockholm|Sweden|Sverige)\.?\s*$/i.test(text)) {
          issues.push(makeOfficialIssue({
            match: text.match(/,\s*(?:Stockholm|Sweden|Sverige)\.?\s*$/i)[0],
            description: 'Do not give publication place or country for an SKB report.',
            source: 'references', paragraph
          }));
        }

        if (/https?:\/\//i.test(text) && !/(?:Available at:|Tillgänglig:)/i.test(text) && !/doi\.org/i.test(text)) {
          issues.push(makeOfficialIssue({
            match: text.match(/https?:\/\/\S+/i)?.[0] || 'URL',
            description: isSwedish ? 'Introduce a web address with “Tillgänglig:”.' : 'Introduce a web address with “Available at:”.',
            source: 'references', paragraph
          }));
        }

        /*
          Section 4.4: a journal is identified by title and volume only. The
          issue number within a volume is not given, and the volume carries no
          "vol". Both are recognised by the page range that follows them, which
          a multivolume book ("Thermodynamics. Vol 2.") does not have.
        */
        const issueNumber = text.match(/\b\d+\s*\(\s*\d+\s*\)\s*,\s*\d+/);
        if (issueNumber) {
          issues.push(makeOfficialIssue({
            match: issueNumber[0],
            description: 'Do not give the issue number within a journal volume.',
            source: 'references', paragraph
          }));
        }

        const volumeWord = text.match(/\bvol\.?\s*\d+\s*,\s*\d+\s*[–-]\s*\d+/i);
        if (volumeWord) {
          issues.push(makeOfficialIssue({
            match: volumeWord[0],
            description: 'Write a journal volume number without the abbreviation “vol”.',
            source: 'references', paragraph
          }));
        }

        /*
          Sections 3.2.1 and 5: interviews, letters, e-mail and conversations
          are named in the text only and never appear in the reference list.
        */
        const spokenSource = text.match(/\b(?:personal communication|personligt meddelande)\b/i);
        if (spokenSource) {
          issues.push(makeOfficialIssue({
            match: spokenSource[0],
            description: 'A personal communication is cited in the text only and must not appear in the reference list.',
            source: 'references', paragraph
          }));
        }

        /*
          Chapter 6: abbreviations and comments follow the language of the
          report, so a Swedish reference list uses the Swedish forms.
        */
        if (isSwedish) {
          for (const [expression, swedish] of SWEDISH_REFERENCE_ABBREVIATIONS) {
            const found = text.match(expression);
            if (!found) continue;
            issues.push(makeOfficialIssue({
              match: found[0],
              description: `In a Swedish publication write “${swedish}” rather than “${found[0].trim()}”.`,
              source: 'references', paragraph
            }));
          }
        }

        /*
          Only page ranges, which the guide introduces with a comma and places
          at the end of the reference. Report and standard numbers such as
          "Nagra Technical Report 02-05" or "ISO 11005-1" also contain a
          hyphen between digits but are identifiers, not ranges.
        */
        const pageRange = text.match(/,\s*(\d+\s*-\s*\d+)\s*\.?\s*$/)
          || text.match(/\b(?:pp?)\s+(\d+\s*-\s*\d+)\b/i);
        if (pageRange) {
          issues.push(makeOfficialIssue({
            match: pageRange[1],
            description: 'Use an en dash (–), not a hyphen, in page and numerical ranges.',
            source: 'references', paragraph
          }));
        }
      }

      const hasSkbPublication = entries.some(e => /\bSKB\s+(?:TR|R|P|IPR|RD|SR|TM|U|F)-/i.test(e.body));
      const hasSkbdoc = entries.some(e => /\bSKBdoc\s+\d+/i.test(e.body));
      if (hasSkbPublication && !/(?:publications can be found|publikationer.*(?:hämtas|finns))/i.test(allRefText)) {
        issues.push(makeOfficialIssue({
          match: 'Reference-list introduction',
          description: 'Add the prescribed availability notice for SKB publications before the reference list.',
          source: 'references', context: 'The reference list contains SKB publications but no availability notice was detected.'
        }));
      }
      if (hasSkbdoc && !/(?:SKBdoc documents will be submitted|SKBdoc-dokument lämnas ut)/i.test(allRefText)) {
        issues.push(makeOfficialIssue({
          match: 'Reference-list introduction',
          description: 'Add the prescribed availability notice for SKBdoc documents before the reference list.',
          source: 'references', context: 'The reference list contains SKBdoc documents but no availability notice was detected.'
        }));
      }
      return issues;
    }

    /*
      Hard spaces and similar typography produce one finding per occurrence and
      can easily outnumber every other finding in a report. They are collected
      into a single collapsed block so that the substantive issues stay
      readable, while the counts and the full list remain available.
    */
    const SPACING_RULE_PATTERN = /non-breaking space|hard space|quotation mark/i;

    function isSpacingFinding(issue) {
      return SPACING_RULE_PATTERN.test(issue.description || '');
    }

    function buildSpacingSummary(issues) {
      if (!issues.length) return '';
      const byRule = new Map();
      for (const issue of issues) {
        const key = issue.ruleId || issue.description;
        if (!byRule.has(key)) byRule.set(key, { name: issue.ruleName || issue.description, id: issue.ruleId || '', items: [] });
        byRule.get(key).items.push(issue);
      }
      const rows = [...byRule.values()]
        .sort((first, second) => second.items.length - first.items.length)
        .map(group => `<div class="spacing-group-row">
            <span class="spacing-group-count">${group.items.length}</span>
            <span class="rule-name">${escHtml(group.name)}</span>
            <span class="rule-id">${escHtml(group.id)}</span>
            <details><summary>Show all ${group.items.length}</summary>${group.items.map(issue => `
              <div id="${findingAnchorId(issue, 'official')}" class="rule-detail-item">
                <div class="rule-full-context">${renderRuleContext(issue)}</div>
                <div>${findingLocationLink(issue, 'official')}</div>
              </div>`).join('')}</details>
          </div>`).join('');
      return `<details class="spacing-group">
          <summary>Typography, hard spaces and quotation marks — ${issues.length} finding(s) across ${byRule.size} rule(s)</summary>
          ${rows}
        </details>`;
    }

    function buildOfficialSkbWritingSection(allIssues) {
      if (!allIssues.length) return section('Official SKB writing-rule issues', 0,
        '<p class="empty-notice">No automatically checkable violations of the three official SKB guides were detected.</p>');
      const spacingIssues = allIssues.filter(isSpacingFinding);
      const issues = allIssues.filter(issue => !isSpacingFinding(issue));
      if (!issues.length) return section('Official SKB writing-rule issues', allIssues.length,
        buildSpacingSummary(spacingIssues), false);
      const body = buildGroupedRuleDetails(issues, 'official', issue => `
        <article id="${findingAnchorId(issue, 'official')}" class="rule-detail-item rule-finding-row" data-part="${escHtml(ruleDocumentPartKey(issue))}" data-severity="${escHtml(issue.severity || 'warning')}" data-rule-id="${escHtml(issue.ruleId || 'unidentified-rule')}">
          <div class="rule-detail-head"><span class="official-rule-match">${escHtml(issue.match)}</span><span><span class="rule-name">${escHtml(issue.ruleName||issue.description)}</span><span class="rule-id">${escHtml(issue.ruleId||'')}</span>${issue.legacyRuleIds?.length?`<span class="rule-legacy-id">Legacy: ${escHtml(issue.legacyRuleIds.join(', '))}</span>`:''}</span><span class="tag">${escHtml(issue.severity || 'warning')}</span>${languageBadge(issue.language, issue.languageConfidence)}</div>
          <div class="rule-detail-guidance">${escHtml(issue.description)}<div class="official-rule-source">Source: ${escHtml(issue.source)}</div></div>
          <div>${findingLocationLink(issue, 'official')}</div>
          <div class="rule-full-context">${renderRuleContext(issue)}</div>${languageIntervalsDetails(issue)}
        </article>`);
      return section('Official SKB writing-rule issues', allIssues.length,
        `<div class="rule-detail-container">${buildRuleDetailFilters(issues)}${body}</div>${buildSpacingSummary(spacingIssues)}`, false);
    }

    function findingLocationKey(item) {
      return `${item.sourcePart || 'word/document.xml'}|${item.paragraphIndex ?? item.paraIndex ?? -1}`;
    }

    function rangesOverlap(first, second) {
      if (!Number.isFinite(first.matchStart) || !Number.isFinite(first.matchEnd) || !Number.isFinite(second.matchStart) || !Number.isFinite(second.matchEnd)) return false;
      return first.matchStart < second.matchEnd && second.matchStart < first.matchEnd;
    }

    function normaliseFindingText(value) {
      return String(value || '').normalize('NFC').toLowerCase().replace(/\\s+/g, ' ').trim();
    }

    function deduplicateRuleFindings(official, citation, review) {
      const accepted = [];
      const families = [
        { items: official, priority: 3 },
        { items: citation, priority: 2 },
        { items: review, priority: 1 }
      ];
      for (const family of families) {
        for (const item of family.items) {
          const duplicate = accepted.find(existing =>
            findingLocationKey(existing.item) === findingLocationKey(item) &&
            ((existing.item.ruleId && item.ruleId && existing.item.ruleId === item.ruleId) ||
             (rangesOverlap(existing.item, item) && normaliseFindingText(existing.item.match) === normaliseFindingText(item.match)))
          );
          if (!duplicate) accepted.push({ item, priority: family.priority, family });
        }
      }
      return {
        official: accepted.filter(entry => entry.family === families[0]).map(entry => entry.item),
        citation: accepted.filter(entry => entry.family === families[1]).map(entry => entry.item),
        review: accepted.filter(entry => entry.family === families[2]).map(entry => entry.item)
      };
    }

    function findPotentialInvalidCitations(paragraphs) {
      const matches = [];

      for (let ruleIndex = 0; ruleIndex < POTENTIAL_INVALID_CITATION_RULES.length; ruleIndex++) {
        const rule = POTENTIAL_INVALID_CITATION_RULES[ruleIndex];
        if (rule.enabled === false) continue;
        let expression;

        try {
          expression = new RegExp(rule.pattern, rule.flags || 'gu');
        } catch (error) {
          console.warn('Invalid potential-citation regular expression:', rule.pattern, error);
          continue;
        }

        for (const paragraph of paragraphs) {
          const text = paragraph.text || '';
          expression.lastIndex = 0;
          let match;

          while ((match = expression.exec(text)) !== null) {
            const contextStart = Math.max(0, match.index - 65);
            const contextEnd = Math.min(text.length, match.index + match[0].length + 65);

            matches.push({
              ruleIndex,
              ruleId: rule.id,
              ruleName: rule.label,
              legacyRuleIds: rule.legacyIds || [],
              category: rule.category,
              severity: rule.severity,
              pattern: rule.pattern,
              description: rule.description,
              match: match[0],
              matchStart: match.index,
              matchEnd: match.index + match[0].length,
              paragraphIndex: paragraph.index,
              section: paragraph.section || '',
              context: `${contextStart > 0 ? '…' : ''}${text.slice(contextStart, contextEnd)}${contextEnd < text.length ? '…' : ''}`
            });

            if (match[0].length === 0) expression.lastIndex++;
          }
        }
      }

      /* Remove duplicate findings caused by overlapping rules. */
      const seen = new Set();
      return matches.filter(item => {
        const key = `${item.paragraphIndex}\u0000${item.match}\u0000${item.description}`;
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      });
    }

    function buildPotentialInvalidCitationsSection(matches) {
      if (!matches.length) return '';
      const body = buildGroupedRuleDetails(matches, 'citation', item => `
        <article id="${findingAnchorId(item, 'citation')}" class="rule-detail-item rule-finding-row" data-part="${escHtml(ruleDocumentPartKey(item))}" data-severity="${escHtml(item.severity || 'warning')}" data-rule-id="${escHtml(item.ruleId || 'unidentified-rule')}">
          <div class="rule-detail-head"><span class="invalid-citation-match">${escHtml(item.match)}</span><span><span class="rule-name">${escHtml(item.ruleName||item.description)}</span><span class="rule-id">${escHtml(item.ruleId||'')}</span>${item.legacyRuleIds?.length?`<span class="rule-legacy-id">Legacy: ${escHtml(item.legacyRuleIds.join(', '))}</span>`:''}</span><span class="tag">${escHtml(item.severity || 'warning')}</span></div>
          <div class="rule-detail-guidance">${escHtml(item.description)}</div>
          <div>${findingLocationLink(item, 'citation')}</div>
          <div class="rule-full-context">${renderRuleContext(item)}</div>${languageIntervalsDetails(item)}
          <div class="forbidden-rule">${escHtml(item.pattern)}</div>
        </article>`);
      return section('Potential invalid in-text citations', matches.length,
        `<div class="rule-detail-container">${buildRuleDetailFilters(matches)}${body}</div>`, false);
    }


    /* ── Rule packs ────────────────────────────────────────────────────────────

      The three official SKB guides are built in and always apply. Everything
      beyond them is project-specific: extra terminology and house preferences
      that differ between, say, a PSAR and an FSAR. Those live in rule packs,
      which are plain JSON files that can be kept in version control, reviewed
      and swapped per project without touching this page.

      A pack is either a bare array of rules or an object:
        { "name": "PSAR PSU 2026", "description": "...", "rules": [ ... ] }
      and each rule is
        { "pattern": "\\bflux\\b", "description": "Use release",
          "enabled": true, "flags": "gu", "language": "en", "severity": "review" }
    */
