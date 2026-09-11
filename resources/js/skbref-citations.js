/* ==========================================================================
   SKB REFERENCE CHECKER — citations

   Finding citations in the running text and cross-referencing them against
   the reference list.

   Part of the page script that used to live inline in skbref.html. The
   modules share one global scope, as classic scripts do, and are loaded in
   the order they were written in; skbref-boot.js runs everything.

   The four-space indent is from the <script> block this came out of, and is
   kept deliberately: removing it would also remove four spaces from every
   line inside a multi-line template literal, changing the whitespace of the
   HTML this page generates.
   ========================================================================== */
'use strict';

    function findInTextCites(paragraphs, entries) {
      const citations = [];
      const abbreviations = entries.filter(entry => entry.abbreviatedName).map(entry => entry.abbreviatedName).sort((a, b) => b.length - a.length);
      for (const paragraph of paragraphs) {
        if (!paragraph.text) continue;
        const beforeDesignations = citations.length;
        findDesignationCitations(paragraph, citations);
        const designations = citations.slice(beforeDesignations);
        findAuthorYearCitations(paragraph, citations);
        findSkbCitations(paragraph, citations);
        /*
          "SSMFS 2008:37" also parses as the author-year citation
          "SSMFS 2008". Drop that reading where the paragraph really carries
          the designation, so one citation is not reported twice — once
          correctly and once as an orphan.
        */
        if (designations.length) {
          const truncated = new Set(designations
            .map(citation => truncatedDesignationKey(citation.key))
            .filter(Boolean)
            .map(normaliseKey));
          for (let index = citations.length - 1; index >= beforeDesignations; index--) {
            const citation = citations[index];
            if (citation.type !== 'designation' && truncated.has(normaliseKey(citation.key))) {
              citations.splice(index, 1);
            }
          }
        }
        for (const name of abbreviations) {
          const regex = new RegExp(`(?:^|[^A-Za-zÀ-ÖØ-Þà-öø-ÿ0-9])(${escapeRegExp(name).replace(/\\s+/g, '\\\\s+')})(?=$|[^A-Za-zÀ-ÖØ-Þà-öø-ÿ0-9])`, 'gi');
          let match;
          while ((match = regex.exec(paragraph.text))) citations.push({ key: name, raw: match[1], paraIndex: paragraph.index, paragraphNumber: paragraph.index + 1, section: paragraph.section, documentRegion: paragraph.documentRegion || 'body', regionLabel: paragraph.regionLabel || paragraph.section || 'Main text', paraText: paragraph.text, type: 'abbreviated-name', author: name, year: null });
        }
        classifyCitationSources(paragraph, citations);
      }
      assignCitationOccurrenceOffsets(citations);
      const seen = new Set();
      return citations.filter(citation => {
        const id = `${normaliseKey(citation.key)}|${citation.paraIndex}|${citation.matchStart ?? -1}|${citation.matchEnd ?? -1}`;
        if (seen.has(id)) return false;
        seen.add(id); return true;
      });
    }

    function assignCitationOccurrenceOffsets(citations) {
      const cursors=new Map();
      for(const citation of citations){if(Number.isFinite(citation.matchStart)&&Number.isFinite(citation.matchEnd))continue;const text=String(citation.paraText||''),cursorKey=`${citation.paraIndex}|${normaliseKey(citation.key)}`,from=cursors.get(cursorKey)||0,candidates=[];if(citation.author&&citation.year)candidates.push(`${citation.author} (${citation.year})`,`${citation.author} ${citation.year}`);candidates.push(citation.raw,citation.key);let found=null;for(const value of candidates){const candidate=String(value||'').trim();if(!candidate)continue;let start=text.indexOf(candidate,from);if(start<0)start=text.indexOf(candidate);if(start>=0){found={start,end:start+candidate.length};break;}}if(found){citation.matchStart=found.start;citation.matchEnd=found.end;cursors.set(cursorKey,found.end);}}
    }

    function normaliseCitationEvidence(value) {
      return normaliseDashes(String(value || ''))
        .normalize('NFC').toLowerCase()
        .replace(/\bet\s+al\.?/g, ' et al ')
        .replace(/\bm\.fl\.?/g, ' et al ')
        .replace(/[^\p{L}\p{N}]+/gu, ' ')
        .replace(/\s+/g, ' ').trim();
    }

    function citationMatchesField(citation, field) {
      const fieldText = normaliseCitationEvidence(field.result);
      if (!fieldText) return false;
      const keyText = normaliseCitationEvidence(citation.key);
      if (keyText && fieldText.includes(keyText)) return true;
      const year = citation.year || String(citation.key).match(/\b(?:1[89]\d{2}|20\d{2})[a-z]?\b/i)?.[0] || '';
      const report = extractSkbReportKey(citation.key || '');
      if (report && normaliseCitationEvidence(field.result).includes(normaliseCitationEvidence(report))) return true;
      const author = String(citation.author || citation.key)
        .replace(/\s+(?:1[89]\d{2}|20\d{2})[a-z]?.*$/i, '')
        .replace(/\s+(?:et\s+al\.?|m\.fl\.?).*$/i, '')
        .split(/\s+(?:and|och|&)\s+/i)[0]
        .trim();
      return Boolean(year && author && fieldText.includes(normaliseCitationEvidence(year)) && fieldText.includes(normaliseCitationEvidence(author)));
    }

    function extractBalancedJsonObject(value, startIndex) {
      let depth = 0, inString = false, escaped = false;
      for (let index = startIndex; index < value.length; index++) {
        const character = value[index];
        if (inString) {
          if (escaped) escaped = false;
          else if (character === '\\') escaped = true;
          else if (character === '"') inString = false;
          continue;
        }
        if (character === '"') { inString = true; continue; }
        if (character === '{') depth++;
        else if (character === '}') {
          depth--;
          if (depth === 0) return value.slice(startIndex, index + 1);
        }
      }
      return '';
    }

    function parseZoteroCitationField(instruction) {
      const marker = String(instruction || '').match(/ADDIN\s+ZOTERO_ITEM\s+CSL_CITATION\b/i);
      if (!marker) return null;
      const objectStart = instruction.indexOf('{', marker.index + marker[0].length);
      if (objectStart < 0) return null;
      const json = extractBalancedJsonObject(instruction, objectStart);
      if (!json) return null;
      try {
        const payload = JSON.parse(json);
        const citationItems = Array.isArray(payload.citationItems) ? payload.citationItems : [];
        const linkedItems = citationItems.map(citationItem => {
          const uris = Array.isArray(citationItem.uris) ? citationItem.uris : [];
          const uri = uris.find(value => /\/items\/[A-Z0-9]+\/?$/i.test(value)) || uris[0] || '';
          const itemKey = uri.match(/\/items\/([A-Z0-9]+)\/?$/i)?.[1] || citationItem.itemData?.key || '';
          return { itemKey, uri, itemData: citationItem.itemData || null };
        }).filter(item => item.itemKey);
        return { payload, linkedItems };
      } catch (error) {
        console.warn('Could not parse Zotero citation field JSON:', error);
        return null;
      }
    }

    function classifyCitationSources(paragraph, allCitations) {
      const paragraphCitations = allCitations.filter(citation => citation.paraIndex === paragraph.index && !citation.citationSource);
      const zoteroFields = (paragraph.fields || []).filter(field => field.isZoteroCitation);
      const otherFields = (paragraph.fields || []).filter(field => !field.isZoteroCitation && !field.isZoteroBibliography && field.result);
      for (const citation of paragraphCitations) {
        const zoteroField = zoteroFields.find(field => citationMatchesField(citation, field));
        if (zoteroField) {
          citation.citationSource = 'zotero';
          citation.citationSourceLabel = 'Zotero field';
          citation.citationSourceDetail = 'ADDIN ZOTERO_ITEM CSL_CITATION';
          citation.zoteroFieldInstruction = zoteroField.instruction;
          citation.zoteroFieldData = parseZoteroCitationField(zoteroField.instruction);
          citation.zoteroItemKeys = citation.zoteroFieldData?.linkedItems.map(item => item.itemKey) || [];
          continue;
        }
        const otherField = otherFields.find(field => citationMatchesField(citation, field));
        if (otherField) {
          citation.citationSource = 'field';
          citation.citationSourceLabel = 'Other Word field';
          citation.citationSourceDetail = otherField.type || 'FIELD';
        } else {
          citation.citationSource = 'plain';
          citation.citationSourceLabel = 'Plain text';
          citation.citationSourceDetail = zoteroFields.length
            ? 'Not matched to the Zotero field present in this paragraph'
            : 'No Zotero citation field detected';
        }
      }
    }

    function citationSourceBadge(citation) {
      const source = citation.citationSource || 'plain';
      const label = citation.citationSourceLabel || 'Plain text';
      const icon = source === 'zotero' ? 'Z' : source === 'field' ? 'F' : 'T';
      return `<span class="citation-source-badge ${source}" title="${escHtml(citation.citationSourceDetail || label)}">${icon} ${escHtml(label)}</span>`;
    }

    function extractCitationParentheticalGroups(text) {
      const groups = [];
      let depth = 0;
      let groupStart = -1;

      for (let index = 0; index < text.length; index++) {
        const character = text[index];

        if (character === '(') {
          if (depth === 0) groupStart = index;
          depth++;
          continue;
        }

        if (character === ')' && depth > 0) {
          depth--;

          if (depth === 0 && groupStart >= 0) {
            groups.push({
              raw: text.slice(groupStart, index + 1),
              content: text.slice(groupStart + 1, index),
              start: groupStart,
              end: index + 1
            });
            groupStart = -1;
          }
        }
      }

      return groups;
    }

    function findAuthorYearCitations(paragraph, out) {
      const publicationYear = '(?:1[89]\\d{2}|20\\d{2})[a-z]?';
      const surname = "(?:[\\p{L}][\\p{L}'’\\-]{0,40})(?:\\s+[\\p{L}][\\p{L}'’\\-]{0,40})*(?:\\s*\\(ed\\))?";
      const organisation = '[A-ZÅÄÖ]{2,}';

      function extractCitationAuthorCandidate(prefixText) {
        let candidate = String(prefixText || '')
          .replace(/[,;\s]+$/, '')
          .trim()
          .replace(/^(?:e\.g\.|cf\.|see)\s+/iu, '');

        if (!candidate) return null;

        /*
          If explanatory prose precedes a citation inside the same pair of
          parentheses, keep only the text after the final citation-introducing
          boundary. Example: "cases 1, 11, and 15 in Öhman and Odén 2018"
          gives "Öhman and Odén", not "cases 1 et al.".
        */
        const boundaries = [
          /\b(?:in|by|from|see|cf\.|according to|reported by|described by)\s+([^;]+)$/iu
        ];
        for (const boundary of boundaries) {
          const boundaryMatch = candidate.match(boundary);
          if (boundaryMatch) candidate = boundaryMatch[1].trim();
        }

        /* Colons, digits and sentence punctuation indicate ordinary prose,
           not an author or institutional-author expression. */
        if (/[:!?]/u.test(candidate) || /\d/u.test(candidate)) return null;
        if (/\.(?!\s*(?:al|fl)\.?\s*$)/iu.test(candidate.replace(/\bet\s+al\.?$/iu, '').replace(/\bm\.fl\.?$/iu, ''))) return null;

        const nameParticle = '(?:van|von|de|del|della|der|den|di|da|dos|du|la|le|af)';
        const surnameWord = "[\\p{Lu}][\\p{L}'’\\-]{0,40}";
        const surname = `(?:(?:${nameParticle})\\s+)*${surnameWord}(?:\\s+${surnameWord})*`;
        const organisation = '[A-ZÅÄÖ]{2,}(?:-[A-ZÅÄÖ]{2,})?';
        const editorSuffix = '(?:\\s*\\(ed\\))?';
        const initials = '(?:\\s+[A-ZÅÄÖ](?:-[A-ZÅÄÖ])?){0,3}';
        const oneAuthor = `(?:${organisation}|${surname})${editorSuffix}${initials}`;
        const etAl = `${oneAuthor}\\s+(?:et\\s+al\\.?|m\\.fl\\.?)`;
        const twoAuthors = `${oneAuthor}\\s+(?:and|och|&)\\s+${oneAuthor}`;
        const commaAuthors = `${oneAuthor}(?:\\s*,\\s*${oneAuthor}){1,}`;
        const validAuthorExpression = new RegExp(
          `^(?:${etAl}|${twoAuthors}|${commaAuthors}|${oneAuthor})$`,
          'u'
        );

        return validAuthorExpression.test(candidate) ? candidate : null;
      }

      function citationAuthorFromText(authorText) {
        const candidate = extractCitationAuthorCandidate(authorText);
        if (!candidate) return null;

        const cleaned = candidate
          .replace(/^\s*(?:see|e\.g\.|cf\.)\s+/i, '')
          .replace(/\s+/g, ' ')
          .replace(/[,;]\s*$/, '')
          .trim();

        const etAlMatch = cleaned.match(
          /^(.+?)\s+(?:et\s+al\.?|m\.fl\.?)$/i
        );
        if (etAlMatch) {
          return `${etAlMatch[1].trim()} et al.`;
        }

        /*
          Citation styles sometimes write all authors inside parentheses:
          (Lidman, Boily, Laudon, & Köhler, 2017). The reference-list key is
          first-author + et al., so convert lists of three or more authors.
        */
        const listedAuthors = cleaned
          .replace(/,?\s*&\s*/g, ', ')
          .split(/\s*,\s*/)
          .map(value => value.trim())
          .filter(Boolean);

        if (listedAuthors.length >= 3) {
          return `${listedAuthors[0]} et al.`;
        }

        if (listedAuthors.length === 2) {
          return `${listedAuthors[0]} and ${listedAuthors[1]}`;
        }

        return cleaned
          .replace(/\s*\(ed\)\s*/gi, '(ed) ')
          .replace(/\s*&\s*/g, ' and ')
          .replace(/\s+och\s+/gi, ' and ')
          .replace(/\s+/g, ' ')
          .trim();
      }

      function addCitation(authorText, year, raw) {
        const author = citationAuthorFromText(authorText);
        if (!author || author.toUpperCase() === 'SKB') return;

        out.push({
          ...makeCitation(`${author} ${year}`, paragraph, 'author-year', author, year),
          raw
        });
      }

      /*
        Parenthetical citations in the supplied document use comma style:
        (Grolander et al., 2024), (SSM, 2008), and semicolon-separated groups.
        A balanced-parentheses scanner is required because editor suffixes such
        as Aquilonius(ed) introduce nested parentheses inside the citation.
        The old parser split at every comma, separating authors from years and
        therefore finding no citations.
      */
      for (const groupMatch of extractCitationParentheticalGroups(paragraph.text)) {
        const group = groupMatch.content;
        const yearExpression = new RegExp(publicationYear, 'giu');
        const years = [...group.matchAll(yearExpression)];
        let previousAuthorText = null;
        let previousYearEnd = 0;

        for (const yearMatch of years) {
          const year = yearMatch[0];
          const yearStart = yearMatch.index;
          const textBeforeYear = group.slice(0, yearStart);

          /*
            Try every comma/semicolon boundary before this year. The earliest
            valid candidate preserves full author lists, while later boundaries
            allow a new citation after repeated years, for example:
            Bergman et al. 1977, 1979, Bergström 1983.
          */
          const candidateStarts = [0];
          for (const delimiter of textBeforeYear.matchAll(/[,;]\s*/g)) {
            candidateStarts.push(delimiter.index + delimiter[0].length);
          }

          let authorText = null;
          for (const candidateStart of candidateStarts) {
            const candidate = textBeforeYear.slice(candidateStart).trim();
            if (extractCitationAuthorCandidate(candidate)) {
              authorText = candidate;
              break;
            }
          }

          /* A bare subsequent year inherits the preceding author. */
          if (!authorText && previousAuthorText) {
            const betweenYears = group.slice(previousYearEnd, yearStart);
            if (/^[\s,]*$/.test(betweenYears)) {
              authorText = previousAuthorText;
            }
          }

          if (authorText) {
            addCitation(authorText, year, group.trim());
            previousAuthorText = authorText;
          }

          previousYearEnd = yearStart + year.length;
        }

        /* Suffix shorthand: (SSM 2021a, b) -> SSM 2021a and SSM 2021b. */
        if (previousAuthorText && years.length) {
          const lastYear = years.at(-1)[0];
          const suffixTail = group.slice(years.at(-1).index + lastYear.length);
          const baseYear = lastYear.slice(0, 4);
          for (const suffix of suffixTail.matchAll(/,\s*([a-z])(?=\s*(?:,|$))/gi)) {
            addCitation(previousAuthorText, `${baseYear}${suffix[1].toLowerCase()}`, group.trim());
          }
        }
      }

      /*
        Direct narrative citations with a single surname are handled first.
        This deliberately simple pass catches constructions such as
        "based on Crawford (2018)" without trying to interpret the preceding
        prose as part of the author name.
      */
      const directNarrativeExpression = /(?:^|[^\p{L}'’\-])((?:(?:van|von|de|del|della|der|den|di|da|dos|du|la|le|af)\s+)*[\p{Lu}][\p{L}'’\-]{1,40}(?:\s+[\p{Lu}](?:-[\p{Lu}])?){0,3}(?:\s*\(ed\))?)\s*\(((?:1[89]\d{2}|20\d{2})[a-z]?)\)/gu;
      let directNarrativeMatch;
      while ((directNarrativeMatch = directNarrativeExpression.exec(paragraph.text)) !== null) {
        addCitation(
          directNarrativeMatch[1],
          directNarrativeMatch[2],
          `${directNarrativeMatch[1]} (${directNarrativeMatch[2]})`
        );
      }

      /*
        Narrative citations can contain several years inside one pair of
        parentheses, for example Vidstrand et al. (2013, 2014b). Extract the
        author once and create one citation for every full year listed.
      */
      const multiYearNarrativeExpression = /(?:^|[^\p{L}'’\-])((?:(?:van|von|de|del|della|der|den|di|da|dos|du|la|le|af)\s+)*[\p{Lu}][\p{L}'’\-]{0,40}(?:\s*\(ed\))?(?:\s+(?:et\s+al\.?|m\.fl\.?))?|(?:(?:van|von|de|del|della|der|den|di|da|dos|du|la|le|af)\s+)*[\p{Lu}][\p{L}'’\-]{0,40}\s+(?:and|och|&)\s+(?:(?:van|von|de|del|della|der|den|di|da|dos|du|la|le|af)\s+)*[\p{Lu}][\p{L}'’\-]{0,40})\s*\(((?:1[89]\d{2}|20\d{2})[a-z]?(?:\s*,\s*(?:1[89]\d{2}|20\d{2})[a-z]?)+)\)/gu;
      let multiYearNarrativeMatch;
      while ((multiYearNarrativeMatch = multiYearNarrativeExpression.exec(paragraph.text)) !== null) {
        const authorText = multiYearNarrativeMatch[1];
        const years = multiYearNarrativeMatch[2]
          .split(/\s*,\s*/)
          .filter(Boolean);

        for (const year of years) {
          addCitation(
            authorText,
            year,
            `${authorText} (${multiYearNarrativeMatch[2]})`
          );
        }
      }

      /* Narrative citations: Grolander et al. (2024), Smith and Jones (2020). */
      const narrativeAuthor = `(?:${organisation}|${surname})(?:\\s+(?:et\\s+al\\.?|m\\.fl\\.?))?(?:\\s+(?:and|och|&)\\s+(?:${organisation}|${surname}))?`;
      const narrativeExpression = new RegExp(
        `(?:^|[^\\p{L}])(${narrativeAuthor})\\s*\\((${publicationYear})(?:\\s*,\\s*[^()]*)?\\)`,
        'gu'
      );

      let narrativeMatch;
      while ((narrativeMatch = narrativeExpression.exec(paragraph.text)) !== null) {
        addCitation(
          narrativeMatch[1],
          narrativeMatch[2],
          `${narrativeMatch[1]} (${narrativeMatch[2]})`
        );
      }
    }

    /*
      The three forms that occur in SKB reports:

          (SSMFS 2008:37)                 parenthetical
          SSMFS (2008:37)                 narrative, number in parentheses
          (SSMFS 2008:37, Section 10)     with a precise location
          ... in SSMFS 2008:21 (SSM 2008) bare, in the sentence structure

      Offsets are recorded from the match itself. The generic fallback in
      assignCitationOccurrenceOffsets looks for "author (year)" and
      "author year", neither of which occurs literally in "SSMFS (2008:37)".
    */
    function findDesignationCitations(paragraph, out) {
      const text = normaliseDashes(paragraph.text);
      const patterns = [
        new RegExp(`\\b(${DESIGNATION_PREFIX})\\s*\\(\\s*(${DESIGNATION_NUMBER})\\s*\\)`, 'gu'),
        new RegExp(`\\b(${DESIGNATION_PREFIX})\\s+(${DESIGNATION_NUMBER})(?=$|[^\\d])`, 'gu')
      ];
      for (const regex of patterns) {
        let match;
        while ((match = regex.exec(text)) !== null) {
          const key = `${match[1]} ${match[2]}`;
          out.push({
            ...makeCitation(key, paragraph, 'designation', match[1], match[2].slice(0, 4)),
            raw: match[0],
            matchStart: match.index,
            matchEnd: match.index + match[0].length
          });
        }
      }
    }

    function findSkbCitations(paragraph, out) {
      /* Report-number form with the report number in parentheses after SKB. */
      const parentheticalReport = /\bSKB\s*\(\s*((?:TR|R|P|IPR|RD|SR|TM|U|F)-\d{2,}-\d+)\s*\)/gi;
      let reportMatch;
      while ((reportMatch = parentheticalReport.exec(normaliseDashes(paragraph.text))) !== null) {
        out.push(makeCitation(`SKB ${reportMatch[1].toUpperCase()}`, paragraph, 'skb-report'));
      }

      /* Parenthetical author-year form used throughout Swedish documents:
         (SKB, 2014), (SKB, 2008, 2009), and (SKB, 2021a, b). */
      const parentheticalSkb = /\(\s*SKB\s*,\s*((?:1[89]\d{2}|20\d{2})[a-z]?)([^()]*)\)/gi;
      let parentheticalMatch;
      while ((parentheticalMatch = parentheticalSkb.exec(paragraph.text)) !== null) {
        const firstYear = parentheticalMatch[1];
        out.push(makeCitation(`SKB ${firstYear}`, paragraph, 'skb-year'));
        const baseYear = firstYear.slice(0, 4);
        for (const extra of parentheticalMatch[2].split(/\s*,\s*/).map(value => value.trim()).filter(Boolean)) {
          if (/^(?:1[89]\d{2}|20\d{2})[a-z]?$/.test(extra)) {
            out.push(makeCitation(`SKB ${extra}`, paragraph, 'skb-year'));
          } else if (/^[a-z]$/i.test(extra)) {
            out.push(makeCitation(`SKB ${baseYear}${extra.toLowerCase()}`, paragraph, 'skb-year'));
          }
        }
      }

      const regex = /\bSKB\s+(?:\(((?:1[89]\d{2}|20\d{2})[a-z]?(?:[,\s]+(?:1[89]\d{2}|20\d{2})[a-z]?)*)\)|((?:1[89]\d{2}|20\d{2})[a-z]?)|((?:TR|R|P|IPR|RD|SR|TM|U|F)-\d{2,}-\d+))/gi;
      let match;
      while ((match = regex.exec(normaliseDashes(paragraph.text)))) {
        if (match[1]) for (const value of match[1].split(/\s*,\s*/)) out.push(makeCitation(`SKB ${value}`, paragraph, 'skb-year'));
        else if (match[2]) out.push(makeCitation(`SKB ${match[2]}`, paragraph, 'skb-year'));
        else out.push(makeCitation(`SKB ${match[3].toUpperCase()}`, paragraph, 'skb-report'));
      }
    }

    function makeCitation(key, paragraph, type, author = null, year = null) {
      return {
        key, raw: key, paraIndex: paragraph.index,
        paragraphNumber: paragraph.index + 1,
        section: paragraph.section,
        documentRegion: paragraph.documentRegion || 'body',
        regionLabel: paragraph.regionLabel || paragraph.section || 'Main text',
        paraText: paragraph.text, type, author, year
      };
    }
    function normaliseCitationAuthor(author) { return String(author).replace(/\s+/g, ' ').replace(/\bet\s+al\.?$/i, 'et al.').replace(/\bm\.fl\.?$/i, 'm.fl.').trim(); }
    function escapeRegExp(text) { return String(text).replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }
    function normaliseKey(key) { return normaliseDashes(key).normalize('NFC').toLowerCase().replace(/et\s*al\.?/g, 'etal').replace(/\s*-\s*/g, '-').replace(/[\s.,;:!?\'"()\[\]{}]/g, ''); }

    /*
      Section 3.2.4 of the reference guide adds author initials to an in-text
      citation when two authors share a surname: "Vallery C (2001)". The
      reference-list key carries no initials, so drop them when matching.
    */
    function stripCitationInitials(key) {
      return String(key)
        .replace(/\s+[\p{Lu}](?:-[\p{Lu}])?(?=\s|$)/gu, ' ')
        .replace(/\s+/g, ' ')
        .trim();
    }

    function fuzzyMatch(first, second) {
      if (first.length < 4 || second.length < 4) return false;
      if (first.includes(second) || second.includes(first)) return true;
      const grams = value => new Set([...Array(Math.max(0, value.length - 1))].map((_, index) => value.slice(index, index + 2)));
      const left = grams(first), right = grams(second);
      return [...left].filter(gram => right.has(gram)).length / Math.max(left.size, right.size, 1) > .7;
    }

    function crossReference(entries, citations) {
      const byKey = new Map(), byAlias = new Map(), byNum = new Map();
      for (const entry of entries) {
        entry.cites = [];
        const key = normaliseKey(entry.key);
        (byKey.get(key) || byKey.set(key, []).get(key)).push(entry);
        for (const alias of entry.aliases || []) {
          const normalized = normaliseKey(alias);
          (byAlias.get(normalized) || byAlias.set(normalized, []).get(normalized)).push(entry);
        }
        if (entry.num !== null) byNum.set(entry.num, entry);
      }
      const orphanCites = [];
      for (const citation of citations) {
        let matches = [];
        if (citation.type === 'numbered' && byNum.has(citation.num)) matches = [byNum.get(citation.num)];
        else {
          const key = normaliseKey(citation.key);
          matches = byKey.get(key) || byAlias.get(key) || [];
          if (!matches.length) {
            const withoutInitials = normaliseKey(stripCitationInitials(citation.key));
            if (withoutInitials !== key) matches = byKey.get(withoutInitials) || byAlias.get(withoutInitials) || [];
          }
          if (!matches.length) for (const [candidate, list] of byKey) if (fuzzyMatch(key, candidate)) { matches = list; break; }
        }
        if (matches.length) matches.forEach(entry => entry.cites.push(citation));
        else orphanCites.push(citation);
      }
      return { orphanCites, uncitedRefs: entries.filter(entry => !entry.cites.length), duplicateKeys: [...byKey.values()].filter(list => list.length > 1) };
    }

    const YEAR_RE = /\b(1[89]\d{2}|20\d{2})[a-z]?\b/;
    /*
      An orphan citation and an uncited reference are usually two views of the
      same mistake: "Anderson et al. 1997" in the text against "Anderson 1997"
      in the list. Pair them up so the author sees the likely fix instead of
      two unrelated lists.
    */
    function attachOrphanSuggestions(report) {
      const candidates = report.uncitedRefs.length ? report.uncitedRefs : [];
      const pool = candidates.length ? candidates : [];
      for (const citation of report.orphanCites) {
        const citationKey = normaliseKey(stripCitationInitials(citation.key)).replace(/etal/g, '');
        let best = null;
        for (const entry of pool) {
          const entryKey = normaliseKey(entry.key).replace(/etal/g, '');
          const score = stringSimilarity(citationKey, entryKey);
          if (!best || score > best.score) best = { entry, score };
        }
        if (best && best.score >= 0.62) {
          citation.suggestion = best.entry;
          citation.suggestionScore = best.score;
          best.entry.suggestedFor = [...(best.entry.suggestedFor || []), citation.key];
        }
      }
      return report;
    }

    function checkSkbFormat(entries) {
      const issues = [];
      const numbered = entries.filter(entry => entry.num !== null).sort((a, b) => a.num - b.num);
      for (let index = 0; index < numbered.length - 1; index++) {
        if (numbered[index + 1].num - numbered[index].num > 1) issues.push({ key: numbered[index + 1].key, issue: `Numbering gap: expected [${numbered[index].num + 1}] before [${numbered[index + 1].num}]`, severity: 'warn' });
      }
      for (const entry of entries) {
        const text = entry.body;
        if (!YEAR_RE.test(text)) issues.push({ key: entry.key, issue: 'No year detected in reference', severity: 'warn' });
        if (/^.+,\s*(?:1[89]\d{2}|20\d{2})[a-z]?\s+[A-ZÅÄÖÀ-ÖØ-Þ]/u.test(text)) {
          issues.push({
            key: entry.key,
            issue: 'Missing period after publication year',
            severity: 'warn'
          });
        }
        if (text.length < 30) issues.push({ key: entry.key, issue: 'Entry seems too short — likely incomplete', severity: 'warn' });
        if (/^https?:\/\//.test(text)) issues.push({ key: entry.key, issue: 'URL-only reference; add author, title, and access date', severity: 'error' });
        /*
          A doi is a persistent identifier, not a web page: section 4.4 of the
          reference guide gives doi examples with no access date, and appendix 1
          states that no period is written after a link.
        */
        const isDoi = /(?:doi\.org\/|\bdoi:\s*10\.|\b10\.\d{4,9}\/)/i.test(text);
        const endsWithLink = /(?:https?:\/\/|www\.)\S+$/i.test(text.trim());
        /*
          Section 4.13 of 1215757 writes the access date in square brackets
          after the address: "Available at: http://… [24 September 2011]."
          Only testing for the word "accessed" rejected every correctly
          formatted reference in the guide.
        */
        const hasBracketedDate = /\[[^\]]*\b(?:1[89]\d{2}|20\d{2})\b[^\]]*\]/.test(text);
        const hasAccessWord = /(?:accessed|hämtad|hämtat|visited|retrieved|besökt)\s/i.test(text);
        if (/https?:\/\//.test(text) && !isDoi && !hasBracketedDate && !hasAccessWord) issues.push({ key: entry.key, issue: 'URL present but no access date', severity: 'warn' });
        const last = text.trim().slice(-1);
        if (text.length > 20 && !endsWithLink && !['.', ')'].includes(last)) issues.push({ key: entry.key, issue: `Reference does not end with a period (ends with "${last}")`, severity: 'info' });
        if (endsWithLink && last === '.') issues.push({ key: entry.key, issue: 'Do not write a period after a link at the end of a reference', severity: 'info' });
      }
      return issues;
    }
