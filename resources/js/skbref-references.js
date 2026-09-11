/* ==========================================================================
   SKB REFERENCE CHECKER — references

   Finding the reference list and reading its entries: headings, abbreviated
   names, author-year keys, SKB report numbers and designations.

   Part of the page script that used to live inline in skbref.html. The
   modules share one global scope, as classic scripts do, and are loaded in
   the order they were written in; skbref-boot.js runs everything.

   The four-space indent is from the <script> block this came out of, and is
   kept deliberately: removing it would also remove four spaces from every
   line inside a multi-line template literal, changing the whitespace of the
   HTML this page generates.
   ========================================================================== */
'use strict';

    const REF_HEADING_RE = /^[\s\u00a0]*(?:\d[\d.]*[\s\u00a0]+)?(?:references?|referenser|referenslista|litteratur|bibliography)[\s\u00a0]*[.:]?[\s\u00a0]*$/i;
    const INTERNAL_REF_HEADING_RE = /^\s*(?:References with abbreviated names|Other references)\s*[.:]?\s*$/i;

    function headingLevel(style) {
      const match = style.match(/^(?:heading|rubrik|överskrift|berschrift|titre|t[iî]tulo)\s*([1-6])$/) || style.match(/^([1-6])$/);
      return match ? Number(match[1]) : 0;
    }

    function normaliseHeadingText(value) {
      return String(value || '')
        .normalize('NFC')
        .replace(/[\u00a0\u2007\u202f]/g, ' ')
        .replace(/[\u200b\u200c\u200d\ufeff]/g, '')
        .replace(/\s+/g, ' ')
        .trim();
    }

    /*
      An author list ends with a surname followed by initials — "Andolfsson T",
      "Höglund L O", "Johannesson L-E". An abbreviated name is a descriptive
      phrase and never does: "Post-closure safety report", "Climate report".

      The distinction matters because both forms are written "<name>, <year>."
      and are otherwise indistinguishable. Without it, every author-year
      reference following a "References with abbreviated names" heading was
      entered under its whole author list: an 85-character key with no year,
      and two works by the same authors reported as duplicates of each other
      because the year that told them apart had been dropped.
    */
    const AUTHOR_LIST_TAIL = /\p{L}{2,}\s+\p{Lu}(?:-\p{Lu})?(?:\s+\p{Lu}(?:-\p{Lu})?){0,3}$/u;

    function looksLikeAuthorList(name) {
      return AUTHOR_LIST_TAIL.test(String(name || '').trim());
    }

    function extractAbbreviatedReferenceName(text) {
      const match = normaliseHeadingText(text).match(
        /^\s*(.+?)\s*,\s*((?:1[89]\d{2}|20\d{2})[a-z]?)\s*[.]/
      );

      if (!match) return null;

      const abbreviatedName = match[1]
        .replace(/\s+/g, ' ')
        .trim();

      if (looksLikeAuthorList(abbreviatedName)) return null;

      return abbreviatedName.length >= 2 && abbreviatedName.length <= 200
        ? abbreviatedName
        : null;
    }

    function splitAtRefList(paragraphs) {
      const explicitEndRe = /^\s*(?:\d[\d.]*\s+)?(?:appendix|appendices|bilaga|bilagor|annex|glossary|ordlista|index|supplementary material|supporting information|distribution list|approval record|document history)\b/i;

      function findExplicitEnd(startIndex) {
        for (let index = startIndex + 1; index < paragraphs.length; index++) {
          const text = normaliseHeadingText(paragraphs[index].text);
          if (text && explicitEndRe.test(text)) return index;
        }
        return paragraphs.length;
      }

      function countPlausibleReferences(startIndex, endIndex) {
        let count = 0;
        for (let index = startIndex + 1; index < endIndex; index++) {
          const text = normaliseHeadingText(paragraphs[index].text);
          if (!text || INTERNAL_REF_HEADING_RE.test(text) || isReferenceSectionNotice(text)) continue;
          if (extractAbbreviatedReferenceName(text) || looksLikeRefStart(text)) count++;
        }
        return count;
      }

      function referenceHeadingCandidate(index, end, kind) {
        const paragraph = paragraphs[index];
        const headingStyleLevel = headingLevel(paragraph?.style || '');
        return {
          start: index,
          end,
          kind,
          plausibleCount: countPlausibleReferences(index, end),
          headingStyleLevel,
          isInTable: Boolean(paragraph?.isInTable),
          /* A matching word in an ordinary table cell is usually a label,
             table content, or a table-of-contents entry, not the section
             heading. A genuine heading-styled paragraph inside a table is
             retained as a lower-priority exceptional candidate. */
          eligible: !paragraph?.isInTable || headingStyleLevel > 0
        };
      }

      /*
        Build all useful anchors. In some DOCX files Word's XML order does
        not match the visual order, particularly when text boxes or custom
        layout containers are involved. Selecting only the first "References"
        heading can therefore select a heading at the very end of document.xml.
      */
      const candidates = [];

      for (let index = 0; index < paragraphs.length; index++) {
        const text = normaliseHeadingText(paragraphs[index].text);

        if (REF_HEADING_RE.test(text)) {
          const end = findExplicitEnd(index);
          candidates.push(referenceHeadingCandidate(index, end, 'main heading'));
        }

        if (/^References with abbreviated names\s*[.:]?$/i.test(text)) {
          const start = index - 1;
          const end = findExplicitEnd(start);
          const candidate = referenceHeadingCandidate(index, end, 'abbreviated-references heading');
          candidate.start = start;
          candidate.plausibleCount = countPlausibleReferences(start, end);
          candidates.push(candidate);
        }

        if (/^Other references\s*[.:]?$/i.test(text)) {
          const start = index - 1;
          const end = findExplicitEnd(start);
          const candidate = referenceHeadingCandidate(index, end, 'other-references heading');
          candidate.start = start;
          candidate.plausibleCount = countPlausibleReferences(start, end);
          candidates.push(candidate);
        }
      }

      /*
        Prefer the anchor that actually has reference-like paragraphs after
        it. This avoids choosing a visually correct but XML-last heading.
      */
      candidates.sort((first, second) =>
        Number(second.eligible) - Number(first.eligible) ||
        Number(second.headingStyleLevel > 0) - Number(first.headingStyleLevel > 0) ||
        Number(first.isInTable) - Number(second.isInTable) ||
        second.plausibleCount - first.plausibleCount ||
        second.start - first.start ||
        (second.end - second.start) - (first.end - first.start)
      );

      let selected = candidates.find(candidate => candidate.eligible && candidate.plausibleCount > 0) || null;

      /* Ordinary author-year fallback if none of the headings yielded data. */
      if (!selected) {
        const scanFrom = Math.floor(paragraphs.length * 0.45);
        for (let index = scanFrom; index < paragraphs.length; index++) {
          const text = normaliseHeadingText(paragraphs[index].text);
          if (!looksLikeRefStart(text) && !extractAbbreviatedReferenceName(text)) continue;

          const end = findExplicitEnd(index - 1);
          const plausibleCount = countPlausibleReferences(index - 1, end);
          if (plausibleCount >= 3) {
            selected = {
              start: index - 1,
              end,
              kind: 'reference-pattern fallback',
              plausibleCount
            };
            break;
          }
        }
      }

      if (!selected) {
        console.warn('No reference-list anchor produced reference-like paragraphs.', {
          paragraphCount: paragraphs.length,
          candidates
        });
        for (const paragraph of paragraphs) {
          paragraph.documentRegion = 'body';
          paragraph.regionLabel = 'Main text';
        }
        return {
          refListParagraphs: [],
          bodyParagraphs: paragraphs,
          refListStart: -1,
          refListEnd: -1
        };
      }

      const start = Math.max(-1, selected.start);
      const end = Math.max(start + 1, selected.end);
      const refListParagraphs = paragraphs.slice(start + 1, end);

      let mainLocationSection = 'Main text';
      for (let index = 0; index <= start; index++) {
        const paragraph = paragraphs[index];
        const headingText = normaliseHeadingText(paragraph.text);
        if (headingText && headingLevel(paragraph.style) && !REF_HEADING_RE.test(headingText)) mainLocationSection = headingText;
        paragraph.documentRegion = 'before-references';
        paragraph.regionLabel = mainLocationSection;
      }
      for (let index = start + 1; index < end; index++) {
        paragraphs[index].documentRegion = 'references';
        paragraphs[index].regionLabel = 'References';
      }
      let postReferenceSection = 'After references';
      for (let index = end; index < paragraphs.length; index++) {
        const paragraph = paragraphs[index];
        const headingText = normaliseHeadingText(paragraph.text);
        if (headingText && (headingLevel(paragraph.style) || explicitEndRe.test(headingText))) postReferenceSection = headingText;
        paragraph.documentRegion = 'after-references';
        paragraph.regionLabel = postReferenceSection;
      }

      console.info('Selected reference-list anchor', {
        ...selected,
        paragraphCount: paragraphs.length,
        extractedParagraphCount: refListParagraphs.length,
        firstExtractedParagraphs: refListParagraphs.slice(0, 8).map(item => item.text),
        selectedHeadingStyleLevel: selected.headingStyleLevel || 0,
        selectedHeadingWasInTable: Boolean(selected.isInTable),
        rejectedTableHeadingCandidates: candidates.filter(candidate => candidate.isInTable && !candidate.eligible)
      });

      return {
        refListParagraphs,
        bodyParagraphs: [
          ...paragraphs.slice(0, Math.max(0, start)),
          ...paragraphs.slice(end)
        ],
        refListStart: Math.max(0, start),
        refListEnd: end
      };
    }

    function isReferenceSectionNotice(text) {
      const normalized = normaliseHeadingText(text);
      return (
        /^SKB[’'\u2019]s?\s*\(Svensk Kärnbränslehantering AB\) publications can be found at/i.test(normalized) ||
        /^SKBdoc documents will be submitted upon request/i.test(normalized)
      );
    }

    /*
      The bold runs of a paragraph, expressed as ranges of the entry body being
      built from it. An entry may be assembled from several paragraphs and may
      have had a leading number stripped, so the caller states how far into the
      paragraph its contribution starts and how far into the body it lands.
    */
    function boldRanges(paragraph, shift, length, offset) {
      return (paragraph.formatSpans || [])
        .filter(span => span.bold)
        .map(span => ({
          start: offset + Math.max(0, span.start - shift),
          end: offset + Math.min(length, span.end - shift)
        }))
        .filter(range => range.end > range.start);
    }

    function extractRefEntries(paragraphs) {
      const entries = [];
      let current = null;
      let autoNum = 0;
      let abbreviated = false;
      const finish = () => { if (current) entries.push(current); current = null; };
      const create = (text, paragraph, shift) => {
        const abbreviatedName = abbreviated ? extractAbbreviatedReferenceName(text) : null;
        const reportKey = extractSkbReportKey(text, true);
        const designationKey = reportKey ? null : extractDesignationKey(text, true);
        return {
          key: abbreviatedName || extractReferenceKey(text) || text.slice(0, 40),
          num: null, body: text, raw: text, paraIndex: paragraph.index,
          type: abbreviatedName ? 'abbreviated-name'
            : reportKey ? 'skb-report'
            : designationKey ? 'designation'
            : 'author-year',
          abbreviatedName,
          boldSpans: boldRanges(paragraph, shift, text.length, 0)
        };
      };
      for (const paragraph of paragraphs) {
        const text = paragraph.text.trim();
        const trimShift = paragraph.text.length - paragraph.text.trimStart().length;
        if (/^\s*References with abbreviated names\s*[.:]?\s*$/i.test(text)) { finish(); abbreviated = true; continue; }
        if (/^\s*Other references\s*[.:]?\s*$/i.test(text)) { finish(); abbreviated = false; continue; }
        if (isReferenceSectionNotice(text)) { finish(); continue; }
        if (!text) { finish(); continue; }
        const number = text.match(/^(?:\[(\d+)\]|(\d+)[.)\s]\s)/);
        if (number || (paragraph.numId && paragraph.numId !== '0')) {
          finish();
          autoNum = number ? Number(number[1] || number[2]) : autoNum + 1;
          const unnumbered = number ? text.replace(/^\[?\d+\]?[.)\s]+/, '') : text;
          const body = number ? unnumbered.trim() : text;
          /* The stripped number shifts every offset in the paragraph. */
          const bodyShift = trimShift + (text.length - unnumbered.length)
            + (unnumbered.length - unnumbered.trimStart().length);
          const abbreviatedName = abbreviated ? extractAbbreviatedReferenceName(body) : null;
          current = { key: `[${autoNum}]`, num: autoNum, body, raw: text, paraIndex: paragraph.index, type: abbreviatedName ? 'abbreviated-name' : 'numbered', abbreviatedName, boldSpans: boldRanges(paragraph, bodyShift, body.length, 0) };
        } else if ((abbreviated && extractAbbreviatedReferenceName(text)) || (current && looksLikeRefStart(text))) {
          finish(); current = create(text, paragraph, trimShift);
        } else if (current) {
          const offset = current.body.length + 1;
          current.body += ` ${text}`;
          current.raw += ` ${text}`;
          current.boldSpans.push(...boldRanges(paragraph, trimShift, text.length, offset));
        } else current = create(text, paragraph, trimShift);
      }
      finish();
      for (const entry of entries) entry.aliases = collectReferenceAliases(entry);
      return entries;
    }

    function looksLikeRefStart(text) { return Boolean(extractSkbReportKey(text, true) || extractDesignationKey(text, true) || extractAuthorYearKey(text)); }

    function extractAuthorYearKey(text) {
      /*
        Editor suffixes are part of the citation key. For example,
        "Aquilonius(ed) K, 2010" produces "Aquilonius(ed) 2010".
      */
      /*
        Accept both the normal form "Authors, 2022. Title" and the common
        punctuation error "Authors, 2022 Title". Without this fallback, a
        reference missing the period after its year is treated as continuation
        text and gets merged into the preceding reference.
      */
      const list = text.match(
        /^(.+),\s*((?:1[89]\d{2}|20\d{2})[a-z]?)(?=\s*[.,]|\s+[A-ZÅÄÖÀ-ÖØ-Þ])/u
      );
      if (list) {
        const surnames = list[1].split(',').map(part => part.trim().split(/\s+/)).map(words => {
          let removed = false;
          while (words.length > 1 && isAuthorInitial(words.at(-1))) { words.pop(); removed = true; }
          return removed ? words.join(' ') : '';
        }).filter(Boolean);
        if (surnames.length === 1) return `${surnames[0]} ${list[2]}`;
        if (surnames.length === 2) return `${surnames[0]} and ${surnames[1]} ${list[2]}`;
        if (surnames.length > 2) return `${surnames[0]} et al. ${list[2]}`;
      }
      const simple = text.match(/^([A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-Þà-öø-ÿ-]+(?:\s*\(ed\))?(?:\s+(?:et\s+al\.?|m\.fl\.?))?(?:,\s*[A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-Þà-öø-ÿ.]+)?)(?:,\s*|\s+)((?:1[89]\d{2}|20\d{2})[a-z]?)/i);
      return simple ? `${simple[1]} ${simple[2]}` : null;
    }

    function isAuthorInitial(value) {
      const clean = String(value).replace(/\./g, '');
      return clean.split('-').every(part => /^[A-ZÀ-ÖØ-Þ]{1,3}$/.test(part));
    }

    function normaliseDashes(text) { return String(text).replace(/[\u2010\u2011\u2012\u2013\u2014\u2212]/g, '-'); }

    function extractSkbReportKey(text, startOnly = false) {
      const normalized = normaliseDashes(text).replace(/\s+/g, ' ').trim();
      const prefix = startOnly ? '^\\s*(?:(?:\\[\\d+\\]|\\d+[.)])\\s*)?' : '(?:^|[^A-Za-z0-9])';
      const match = normalized.match(new RegExp(prefix + '(?:SKB[\\s-]*)?((?:TR|R|P|IPR|RD|SR|TM|U|F)-\\d{2,}-\\d+)(?=$|[^A-Za-z0-9])', 'i'));
      return match ? `SKB ${match[1].toUpperCase()}` : null;
    }

    /*
      DESIGNATION REFERENCES

      Sections 4.10-4.12 of 1215757 enter a standard, a government publication
      or a statute under its designation, and there the publication year is
      part of the designation itself:

          SFS 1984:3      SSMFS 2008:21      SOU 2010:6
          Ds 2007:30      SS-EN 1936:1999    BFS 2011:10

      The number after the colon is what tells one regulation from another, so
      it belongs in the key. Read as an ordinary author-year citation the colon
      part is lost, and every SSMFS regulation issued in 2008 collapses onto
      the same key — which reported "SSMFS 2008:37" in the text as a correct
      match for "SSMFS 2008:21" in the list, and two such references in one
      list as duplicates of each other.
    */
    const DESIGNATION_PREFIX = String.raw`[A-ZÅÄÖ][A-Za-zÅÄÖåäö]{0,11}(?:-[A-Z]{1,4})?`;
    const DESIGNATION_NUMBER = String.raw`(?:1[89]|20)\d{2}:\d{1,4}[a-z]?`;

    /**
     * The designation a reference is entered under, if it has one.
     *
     * @param {string} text
     * @param {boolean} [startOnly] - Only match at the start of the reference
     * @returns {string|null} e.g. "SSMFS 2008:21"
     */
    function extractDesignationKey(text, startOnly = false) {
      const anchor = startOnly ? '^\\s*(?:(?:\\[\\d+\\]|\\d+[.)])\\s*)?' : '\\b';
      const regex = new RegExp(
        `${anchor}(${DESIGNATION_PREFIX})\\s+(${DESIGNATION_NUMBER})(?=$|[^\\d])`, 'u');
      const match = normaliseDashes(text).replace(/\s+/g, ' ').match(regex);
      return match ? `${match[1]} ${match[2]}` : null;
    }

    /** The author-year reading of a designation, which must not be trusted. */
    function truncatedDesignationKey(designation) {
      const match = String(designation).match(/^(.*?)\s+((?:1[89]|20)\d{2}):/);
      return match ? `${match[1]} ${match[2]}` : null;
    }

    function extractReferenceKey(text) {
      return extractSkbReportKey(text, true)
        || extractDesignationKey(text, true)
        || extractAuthorYearKey(text);
    }
    function collectReferenceAliases(entry) {
      const designation = extractDesignationKey(entry.body, true);
      /*
        The author-year reading of a designation is deliberately not kept as an
        alias. "SSMFS 2008" identifies no regulation, and as an alias it would
        match every SSMFS reference of that year at once — the silent
        mismatch this whole path exists to prevent. Such a citation is
        reported as an orphan instead.
      */
      const truncated = designation ? normaliseKey(truncatedDesignationKey(designation) || '') : '';
      const authorYear = extractAuthorYearKey(entry.body);
      const aliases = [
        entry.key,
        entry.abbreviatedName,
        truncated && normaliseKey(authorYear || '') === truncated ? null : authorYear,
        designation,
        extractSkbReportKey(entry.body, true),
        extractSkbReportKey(entry.body)
      ];
      return [...new Set(aliases)].filter(Boolean);
    }
