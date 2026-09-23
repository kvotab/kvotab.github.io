/* ==========================================================================
   SKB REFERENCE CHECKER — selftests-rules

   Self-tests for the rule tables, the language classifier and the fixture
   built from the guides' own examples. Run from skbref-boot.js.

   Part of the page script that used to live inline in skbref.html. The
   modules share one global scope, as classic scripts do, and are loaded in
   the order they were written in; skbref-boot.js runs everything.

   The four-space indent is from the <script> block this came out of, and is
   kept deliberately: removing it would also remove four spaces from every
   line inside a multi-line template literal, changing the whitespace of the
   HTML this page generates.
   ========================================================================== */
'use strict';

    function runReviewRuleRegressionTests() {
      const cases = [
        ['terminology-peak', ['peak', 'Peak value'], ['speak', 'speaker', 'speaking']],
        ['language-en-mail', ['mail', 'Mail'], ['email', 'mailbox', 'mailing']],
        ['reference-broken-cross-reference-x', ['1.X', '4.2.X'], ['1aX', '2-X', '3 X']],
        ['reference-broken-section-zero', ['Section.0', 'Section.01'], ['Section 01', 'Section-02', 'SectionA03']],
        ['language-repeated-word', ['The the beginning', 'word word.', 'ström ström'], ['word, word']],
        ['terminology-flux', ['flux', 'Fluxes'], ['influx', 'refluxing']],
        ['terminology-grout', ['grout', 'grouting'], ['aground']],
        ['language-us-color', ['color', 'Colors'], ['colorado', 'discoloration']],
        ['language-us-organize', ['organize', 'organization'], ['organizerX']],
        ['language-us-behavior', ['behavior', 'behaviors'], ['behavioralismX']],
        ['reference-section-vs-chapter', ['Section 7', 'sections 12'], ['SectionA7', 'intersection 7']],
        ['reference-chapter-vs-section', ['Chapter 7.2', 'chapters 12.4'], ['Chapter 7', 'ChapterA7.2']]
      ];
      const failures = [];
      for (const [ruleId, positives, negatives] of cases) {
        const rule = [...FORBIDDEN_WORD_RULES, ...POTENTIAL_INVALID_CITATION_RULES, ...OFFICIAL_SKB_TEXT_RULES].find(item => item.id === ruleId || (item.legacyIds || []).includes(ruleId));
        if (!rule) { failures.push(`Missing rule ${ruleId}`); continue; }
        const expression = new RegExp(rule.pattern, rule.flags || 'gu');
        for (const value of positives) { expression.lastIndex = 0; if (!expression.test(value)) failures.push(`${ruleId} should match: ${value}`); }
        for (const value of negatives) { expression.lastIndex = 0; if (expression.test(value)) failures.push(`${ruleId} should not match: ${value}`); }
      }
      const directCases = [
        [/\bKd\b/gu, ['Kd'], ['SKd', 'Kdata']],
        [/\bSEQ\b/gu, ['SEQ'], ['SEQUENCE', 'xSEQ']],
        [/\bF-PSAR\b/gu, ['F-PSAR'], ['XF-PSAR']],
        [/\b(?:[Kk]|[Cc])aison\b/gu, ['caison', 'Kaison'], ['occasion']],
        [/\bData Report\b/gu, ['Data Report'], ['Metadata Report']],
        [/\bTabell\b/gu, ['Tabell'], ['Tabellen']],
        [/\d%(?![\p{L}\p{N}])/gu, ['5%', '100%'], ['5percent', '5%A']],
        [/\d°C(?!\p{L})/gu, ['5°C'], ['5°Celsius']],
        [/\dmm(?!\p{L})/gu, ['5mm'], ['5mmeter']],
        [/\dyears(?!\p{L})/gu, ['5years'], ['5yearsin']],
        [/\b\d{1,3}0000(?:\d+)?\b/gu, ['10000', '250000'], ['2000', 'R-10000A']],
        [/\bBiosphere synthesis(?!\s+report\b)/gu, ['Biosphere synthesis model'], ['Biosphere synthesis report']],
        [/\bSVAFO\b/gu, ['SVAFO'], ['SVAFOX']]
      ];
      const svafoPrefixCases = [['SVAFO', true], ['AB SVAFO', false], ['AB  SVAFO', false], ['Text SVAFO', true]];
      for (const [value, shouldFlag] of svafoPrefixCases) {
        const match = /\bSVAFO\b/u.exec(value);
        const prefix = match ? value.slice(Math.max(0, match.index - 12), match.index).replace(/[\s\u00a0]+$/u, ' ').trimEnd() : '';
        const flagged = Boolean(match && !/\bAB$/u.test(prefix));
        if (flagged !== shouldFlag) failures.push(`SVAFO prefix check failed: ${value}`);
      }
      for (const [expression, positives, negatives] of directCases) {
        for (const value of positives) { expression.lastIndex = 0; if (!expression.test(value)) failures.push(`${expression} should match: ${value}`); }
        for (const value of negatives) { expression.lastIndex = 0; if (expression.test(value)) failures.push(`${expression} should not match: ${value}`); }
      }
      /*
        An SKB report may be cited either as "SKB (TR-14-09)" or as
        "(SKB TR-14-09)". Both are correct, so no enabled citation rule may
        report either one, and both must still be extracted as the same report.
      */
      const acceptedReportCitations = [
        'The results are given in SKB (TR-14-09).',
        'The results are given elsewhere (SKB TR-14-09).',
        'See SKB TR-14-09 for the full account.'
      ];
      for (const sentence of acceptedReportCitations) {
        for (const rule of POTENTIAL_INVALID_CITATION_RULES) {
          if (rule.enabled === false) continue;
          const expression = new RegExp(rule.pattern, rule.flags || 'gu');
          expression.lastIndex = 0;
          if (expression.test(sentence)) {
            failures.push(`Valid report citation flagged by ${rule.id}: ${sentence}`);
          }
        }
        const extracted = [];
        findSkbCitations({ index: 0, text: sentence, section: 'Fixture' }, extracted);
        const hit = extracted.filter(citation => citation.key === 'SKB TR-14-09' && citation.type === 'skb-report');
        if (hit.length !== 1) {
          failures.push(`Report citation extracted ${hit.length} times, expected once: ${sentence}`);
        }
      }

      if (failures.length) console.error('Review-rule regression tests failed:', failures);
      else console.info(`Review-rule regression tests passed (${cases.length} rules).`);
      return failures;
    }
    function runConsolidatedRegressionTests(){const failures=[],all=[...FORBIDDEN_WORD_RULES,...POTENTIAL_INVALID_CITATION_RULES,...OFFICIAL_SKB_TEXT_RULES],ids=new Set();for(const rule of all){if(!rule.id||ids.has(rule.id))failures.push(`Duplicate/missing rule ID: ${rule.id}`);ids.add(rule.id);if(!rule.label)failures.push(`Missing rule name: ${rule.id}`);if((rule.legacyIds||[]).includes(rule.id))failures.push(`Canonical ID repeated as legacy: ${rule.id}`);}const highlighted=renderRuleContext({fullContext:'Use peak safely <here>.',match:'peak',matchStart:4,matchEnd:8});if(!highlighted.includes('<strong class="rule-context-match">peak</strong>')||!highlighted.includes('&lt;here&gt;'))failures.push('Rule highlight/escaping failed');const fake={styles:new Map([['Base',{id:'Base',basedOn:'',type:'paragraph',name:'Base',language:'en',rawLanguage:'en-GB'}],['Derived',{id:'Derived',basedOn:'Base',type:'paragraph',name:'Derived',language:'unknown',rawLanguage:''}]]),defaultStyles:{paragraph:'Base',character:''},docDefault:{language:'unknown',raw:'',source:'none'}};if(resolveStyleLanguage('Derived',fake)?.language!=='en')failures.push('Style inheritance failed');const sparse=classifyParagraphLanguage('This is an English paragraph with Swedish template metadata and English words.',{counts:{sv:3,en:0,other:0,unknown:70}});if(sparse.language!=='en')failures.push('Sparse metadata language fallback failed');for(const [value,expected] of [['Swedish','(In Swedish.)'],['sv-SE','(In Swedish.)'],['English',''],['','']])if(zoteroLanguageNote(value)!==expected)failures.push(`Zotero language note failed: ${value}`);const repeated=[{key:'Smith 2020',raw:'Smith 2020',paraIndex:1,paraText:'Smith 2020 and Smith 2020'},{key:'Smith 2020',raw:'Smith 2020',paraIndex:1,paraText:'Smith 2020 and Smith 2020'}];assignCitationOccurrenceOffsets(repeated);if(repeated[0].matchStart===repeated[1].matchStart)failures.push('Repeated citation offsets failed');if(failures.length)console.error('Consolidated regression tests failed:',failures);else console.info(`Consolidated regression tests passed (${all.length} rules plus feature checks).`);return failures;}
    /*
      Regression fixture built from the guides' own examples. Every "correct"
      line is quoted from one of the three guides, so a finding on it is a
      false positive; every "wrong" line is an error the guides name
      explicitly. Runs on load and reports to the console.
    */
    const GUIDE_FIXTURE_CASES = [
      /* 1215757, correct in-text citations */
      { text: 'In previous studies (Lee and Wen 2001, O’Connor 2008), it was reported that the effect is small.', expect: null },
      { text: 'This opinion has been on several occasions stated by Lindroos (1993a, b).', expect: null },
      { text: '… as shown by several recent studies (Ludvigson et al. 2002, p 352, McKenzie 2000, pp 34–36).', expect: null },
      { text: 'Vallery C (2001) has presented a deep insight into this controversy.', expect: null },

      /* 1469987 appendix 4, correct */
      { text: 'The interval 2001–2004 was studied and Sections 4.1–4.3 describe the method.', expect: null },
      { text: 'A total of 100 000 samples were taken, and 20 % of them at 0.1 ‰ accuracy.', expect: null },
      { text: 'The reaction 2HCl + 2Na → 2NaCl + H2 was complete, and CaSO4 ∙ H2O precipitated.', expect: null },
      { text: 'Values of 2 + 3 = 5, T = 293 K and 50 ± 2 were recorded.', expect: null },
      { text: 'Figures 1.1 and 1.2 show the result, see Chapter 5 and Appendix A.', expect: null },
      { text: 'A program was developed (SOU 2010:6) to handle the waste.', expect: null },

      /* 1469987 appendix 4, wrong */
      { text: 'The period 2001-2004 was studied.', expect: /en dash/i },
      { text: 'The result covers Sections 4.1 – 4.3 of the report.', expect: /no surrounding spaces/i },
      { text: 'A total of 100,000 samples were collected.', expect: /thousands separator/i },
      { text: 'The value was 20% of the total.', expect: /non-breaking space/i },
      { text: 'The temperature was −5°C during the test.', expect: /non-breaking space/i },
      { text: 'The grid measured 3 x 7 m in total.', expect: /multiplication sign/i },
      { text: 'The flux reached 7 ∙ 10³ during the peak.', expect: /multiplication sign/i },
      { text: 'The reaction 2 HCl + 2 Na → 2 NaCl + H2 was complete.', expect: /coefficient/i },
      { text: 'The precipitate was CaSO4×H2O throughout.', expect: /water of crystallisation/i },
      { text: 'Results were 2+3=5 in every case.', expect: /operators/i },
      { text: 'The concentration was 2.4e5 in the sample.', expect: /E notation/i },

      /* 1469987 appendix 3 and section 3.1 */
      { text: 'The value was .25 in the first test.', expect: /integer zero/i },
      { text: 'The ratio was much greater >> 100 in that case.', expect: /≪ or ≫/ },
      { text: 'Figures 1.1–1.2 show the result.', expect: /adjacent numbered/i },
      { text: 'The range 2.5–3.6 × 10³ was covered.', expect: /powers of ten/i },
      { text: 'A total of 15–30 million tonnes were handled.', expect: /digits and words/i },
      { text: 'Measurements at 30 mA – 50 mA were taken.', expect: /end of a range/i },
      { text: 'A mass of 5 kgs was recorded.', expect: /plural ending/i },

      /* 1469987 sections 5 and 6.1 */
      { text: 'The sulphate concentration was measured in the groundwater.', expect: /IUPAC/i },
      { text: 'We analyze the color of the fiber in the center of the sample.', expect: /American spelling/i },

      /* Identifiers that must never be read as chemistry or arithmetic */
      { text: 'The results for SFR1, CCP33 and KBS3 are reported in Chapter 4.', expect: null },
      { text: 'See Nagra Technical Report 02-05 for the Swiss approach.', expect: null },
      { text: 'The analysis follows SKB TR-10-53 and document id 1715629.', expect: null },
      /* 1215757 appendix 2: in-text citation errors, with the guide's own fixes */
      { text: 'This has been stated by Lindroos (1993a, 1993b) in two papers.', expect: /do not repeat the year/i },
      { text: 'This has been stated by Lindroos (1993a, b) in two papers.', expect: null },
      { text: 'The value has been calculated (see van der Wal et al. (2001)).', expect: /second pair of parentheses/i },
      { text: 'The value has been calculated (see van der Wal et al. 2001).', expect: null },
      { text: 'According to (Brydsten 2009), the shoreline moved.', expect: /part of the sentence/i },
      { text: 'According to Brydsten (2009), the shoreline moved.', expect: null },
      { text: 'There is a discussion in Chapter 5 of Holmén (2005) about this.', expect: /after the year/i },
      { text: 'There is a discussion in Holmén (2005, Chapter 5) about this.', expect: null },

      /* 1469987 appendix 4: signs used as a prefix */
      { text: 'The samples had pH <7 throughout the test.', expect: /Only \+ and −/ },
      { text: 'The samples had pH < 7 throughout the test.', expect: null },
      { text: 'The distance was ≈100 m from the tunnel.', expect: /Only \+ and −/ },
      { text: 'The distance was ≈ 100 m from the tunnel.', expect: null },
      { text: 'The temperature fell to −5 °C during the night.', expect: null },
      { text: 'The bias was +2 °C over the period.', expect: null },

      /* 1469987 sections 2.2, 3.1, 5 and 6 */
      { text: 'In the equation, where I = electric current is assumed.', expect: /rather than an equals sign/i },
      { text: 'In the equation, where I is the electric current.', expect: null },
      { text: 'The reaction CaCO3 ↔ Ca and CO3 was observed.', expect: /⇄/ },
      { text: 'The layer formed 5000BC in the basin.', expect: /space between the year and BC/i },
      { text: 'The layer formed 5000 BC in the basin.', expect: null },
      { text: 'The grain size was 5 um across the sample.', expect: /micro prefix/i },
      { text: 'The grain size was 5 µm across the sample.', expect: null },
      { text: 'The ratio of sand / clay was measured.', expect: /solidus/i },
      { text: 'The samples were rinsed, e.g. Then they were dried.', expect: /end a sentence with e\.g\./i },
      { text: 'Carbon can be oxidised (cf., Hoefs 2004) by microorganisms.', expect: /comma directly after cf/i },
      { text: 'Carbon can be oxidised (cf. Hoefs 2004) by microorganisms.', expect: null },
      { text: 'The campaign ran 29 September–2 October last year.', expect: /Space the en dash/i },
      { text: 'The campaign ran 29 September – 2 October last year.', expect: null },

      /* 1215757 section 3.2 and appendix 3: more of the guide's own correct citations */
      { text: 'In the late eighties, Halley (1988, 1990) has promoted the viewpoint that the model holds.', expect: null },
      { text: 'The controversial results were extensively debated (Williams 1999, 2000, 2003).', expect: null },
      { text: 'Several works by one author in one year are cited as (Smith 2003a, b, 2010b, c).', expect: null },
      { text: 'Several works by one author are cited as (Brown 2002, 2004) in the text.', expect: null },
      { text: 'Works by authors with one surname are cited as (Cole G 2003, Cole P 2001).', expect: null },
      { text: 'Fuchs et al. (1993a, b) have presented several new ideas about the process.', expect: null },
      { text: 'Larson E et al. (2009) have reported a major finding which seems to hold.', expect: null },
      { text: 'Further research (Anderson et al. 1997, Brown 1999, de Rosa and Dolan 1997) has widened the understanding.', expect: null },
      { text: 'Bauer (1989, p 112) argues that extraordinary measures are necessary.', expect: null },
      { text: 'Ponti C (2000, personal communication) advises that the experiment is repeated.', expect: null },
      { text: 'Cole’s observations (1999, cited in Morris 2001, pp 22–23) led to a new model.', expect: null },
      { text: 'This is described in SKB (TR-10-53) and is too far away to influence the repository (SKB TR-10-53).', expect: null },
      { text: 'The database of bird observations in Denmark (DOF, n d) lists the species.', expect: null },
      { text: 'According to standard BS ISO 81782 (BSI 2008) the measurement is made at full load.', expect: null },
      { text: 'This is done using the extensively tested 3DEC code (Itasca 2007).', expect: null },
      { text: 'This is stated in the design premises report (Posiva SKB 2017).', expect: null },
      { text: 'The values are measured (see Section 2.5 and Lin et al. 2006).', expect: null },

      /* 1469987 section 6.1.5: storey is the British spelling */
      { text: 'The building has three storeys above ground.', expect: null },

      /* 1469987 section 3.1 (SV): a comma is the Swedish decimal separator;
         1715629 section 7.6: digit groups are separated by spaces */
      { text: 'Halten var 0,125 mg per liter i provet.', expect: null, lang: 'sv' },
      { text: 'Förvaret rymmer 12.000 kapslar enligt planen.', expect: /not full stops, between groups/i, lang: 'sv' },
      { text: 'Förvaret rymmer 12 000 kapslar enligt planen.', expect: null, lang: 'sv' },
      { text: '0.001', expect: null, lang: 'sv' },

      /* 1715629 sections 12 and 13: lower-case figur and tabell in running
         text, but a sentence still begins with a capital letter */
      { text: 'Figur 3-1 visar resultatet av mätningen.', expect: null, lang: 'sv' },
      { text: 'Resultatet framgår av Figur 3-1 och tabell 3-2.', expect: /lower-case “figur”/i, lang: 'sv' },

      /* 1715629 section 11.2: no "från" or "mellan" with an en dash */
      { text: 'Anläggningen är öppen mellan 13–14 varje dag.', expect: /mellan/i, lang: 'sv' },
      { text: 'Anläggningen är öppen 13–14 varje dag.', expect: null, lang: 'sv' },

      /* 1715629 section 6: a heading does not end with a full stop and has
         preferably fewer than six words */
      { text: 'Results of the measurements.', style: 'heading 1', expect: /full stop/i },
      { text: 'What does the model predict?', style: 'heading 1', expect: null },
      { text: 'Groundwater flow in the rock mass', style: 'heading 1', expect: /fewer than six words/i },
      { text: 'Groundwater flow in rock', style: 'heading 1', expect: null },

      /* 1715629 sections 7.1, 7.3, 7.4, 7.5, 18.1 and 18.2 */
      { text: 'Vi mätte t.ex. temperaturen i borrhålet.', expect: /without full stops/i, lang: 'sv' },
      { text: 'Vi mätte t ex temperaturen i borrhålet.', expect: null, lang: 'sv' },
      { text: 'Arbetet utförs av SKB AB under året.', expect: /company designation AB/i, lang: 'sv' },
      { text: 'Arbetet utförs av Svensk Kärnbränslehantering AB under året.', expect: null, lang: 'sv' },
      { text: 'Ägaren Forsmark Kraftgrupp deltog i mötet.', expect: /Forsmarks Kraftgrupp/, lang: 'sv' },
      { text: 'Ägaren Forsmarks Kraftgrupp AB deltog i mötet.', expect: null, lang: 'sv' },
      { text: 'Kraven följer av Miljöbalken och andra regler.', expect: /lower-case initial/i, lang: 'sv' },
      { text: 'Kraven följer av miljöbalken och andra regler.', expect: null, lang: 'sv' },
      { text: 'Vi mäter radioaktiv strålning vid tunneln.', expect: /joniserande/i, lang: 'sv' },
      { text: 'Bränslet lastas i en bränsleflaska före transport.', expect: /transportbehållare/i, lang: 'sv' },
      { text: 'Rapporten beskriver uttjänt kärnbränsle i förvaret.', expect: /använt kärnbränsle/i, lang: 'sv' },
      { text: 'Huvudtidsplanen reviderades under hösten.', expect: /huvudtidplan/i, lang: 'sv' },
      { text: 'Han skrev "detta gäller" i rapporten.', expect: /typographic quotation marks/i, lang: 'sv' },
      { text: 'Han skrev ”detta gäller” i rapporten.', expect: null, lang: 'sv' }
    ];

    function runGuideFixtureRegressionTests() {
      const failures = [];
      for (const [index, testCase] of GUIDE_FIXTURE_CASES.entries()) {
        /* A case may declare its language; the SKB rules are language-gated. */
        const language = testCase.lang || 'en';
        const paragraph = {
          index, localIndex: index, text: testCase.text, style: testCase.style || '', section: 'Fixture',
          sourcePart: 'fixture', sourceLabel: 'Fixture', language,
          languageConfidence: 1, languageRanges: [], formatSpans: []
        };
        let found = [];
        try {
          found = findOfficialSkbTextIssues([paragraph], { language, confidence: 1 });
        } catch (error) {
          failures.push(`Rule crash on "${testCase.text.slice(0, 45)}…": ${error.message}`);
          continue;
        }
        const descriptions = found.map(issue => issue.description);
        if (testCase.expect === null) {
          if (descriptions.length) failures.push(`False positive on a correct line: "${testCase.text.slice(0, 55)}…" → ${descriptions[0]}`);
        } else if (!descriptions.some(description => testCase.expect.test(description))) {
          failures.push(`Missed ${testCase.expect} in "${testCase.text.slice(0, 55)}…"${descriptions.length ? ` (found instead: ${descriptions[0]})` : ''}`);
        }
      }

      /* Reference-list collation, from the examples in chapter 5 of 1215757. */
      const ordered = ['Berg Adams C', 'Berggren B', 'Berg-Liljeblad A', 'Délaine J-M', 'de Maury E'];
      for (let index = 1; index < ordered.length; index++) {
        if (skbSortKey(ordered[index - 1]) > skbSortKey(ordered[index])) {
          failures.push(`Collation failed: ${ordered[index - 1]} should sort before ${ordered[index]}`);
        }
      }
      if (!(skbSortKey('Ünger') < skbSortKey('Zetterlund'))) failures.push('Collation failed: u-diaeresis should sort as y');
      if (!(skbSortKey('Ärlig') < skbSortKey('Öberg'))) failures.push('Collation failed: a-diaeresis should sort before o-diaeresis');

      /* 1215757 appendix 2 and 1469987 section 6.5: et al. and common Latin
         terms are upright; an italic caption is not a finding. */
      const styled = (text, spans) => ({ index: 0, localIndex: 0, text, style: '', section: 'Fixture', sourcePart: 'fixture',
        language: 'en', languageConfidence: 1, languageRanges: [], formatSpans: spans });
      const roman = { italic: false, bold: false, sup: false, sub: false, underline: false };
      const italic = { ...roman, italic: true };
      const etAlText = 'As shown by Ludvigsson et al. 2002, the flow is slow.';
      const etAlAt = etAlText.indexOf('et al.');
      const italicEtAl = findFormattingIssues([styled(etAlText, [
        { start: 0, end: etAlAt, ...roman }, { start: etAlAt, end: etAlAt + 6, ...italic }, { start: etAlAt + 6, end: etAlText.length, ...roman }])]);
      if (!italicEtAl.some(issue => /et al\. in upright/i.test(issue.description))) failures.push('Italic et al. was not reported');
      const uprightEtAl = findFormattingIssues([styled(etAlText, [{ start: 0, end: etAlText.length, ...roman }])]);
      if (uprightEtAl.some(issue => /upright/i.test(issue.description))) failures.push('Upright et al. was reported');
      const caption = 'Figure 3-1. Measured in situ, after Ludvigsson et al. 2002.';
      if (findFormattingIssues([styled(caption, [{ start: 0, end: caption.length, ...italic, bold: true }])]).some(issue => /upright/i.test(issue.description))) {
        failures.push('An italic caption was reported for its Latin terms');
      }

      /* Chemistry must not swallow project identifiers. */
      for (const identifier of ['SFR1', 'CCP33', 'KBS3', 'R2', 'P14']) {
        if (isChemicalFormula(identifier)) failures.push(`Identifier read as a chemical formula: ${identifier}`);
      }
      for (const formula of ['H2O', 'CO2', 'H2SO4', 'CaCO3', 'Fe2O3']) {
        if (!isChemicalFormula(formula)) failures.push(`Chemical formula not recognised: ${formula}`);
      }

      if (failures.length) console.error(`Guide fixture: ${failures.length} failure(s)`, failures);
      else console.info(`Guide fixture passed (${GUIDE_FIXTURE_CASES.length} lines from the SKB guides plus collation and chemistry checks).`);
      return failures;
    }

    function runReferenceHeadingSelectionRegressionTests() {
      const failures = [];
      const candidates = [
        {start:12, plausibleCount:80, headingStyleLevel:0, isInTable:true, eligible:false},
        {start:190, plausibleCount:24, headingStyleLevel:1, isInTable:false, eligible:true}
      ];
      candidates.sort((first, second) =>
        Number(second.eligible) - Number(first.eligible) ||
        Number(second.headingStyleLevel > 0) - Number(first.headingStyleLevel > 0) ||
        Number(first.isInTable) - Number(second.isInTable) ||
        second.plausibleCount - first.plausibleCount || second.start - first.start
      );
      if (candidates[0].start !== 190) failures.push('Ordinary table-cell “Reference” incorrectly outranked styled “Referenser” heading.');
      if (failures.length) console.error('Reference-heading selection regression tests failed:', failures);
      else console.info('Reference-heading selection regression tests passed.');
      return failures;
    }

    function runLanguageRegressionTests() {
      const failures=[];
      const classify=(text,counts)=>classifyParagraphLanguage(text,{counts,ranges:[],paragraphLanguage:'unknown'});
      const sv=classify('Detta är en svensk text och den innehåller flera svenska ord.',{sv:52,en:0,other:0,unknown:0});
      const en=classify('This is an English text and it contains several English words.',{sv:0,en:55,other:0,unknown:0});
      const mixed=classify('Swedish and English text.',{sv:20,en:18,other:0,unknown:0});
      const fallbackSv=classify('Detta är en text som inte är markerad med språk.',{sv:0,en:0,other:0,unknown:40});
      const fallbackEn=classify('This is a text that is not marked with a language.',{sv:0,en:0,other:0,unknown:42});
      if(sv.language!=='sv'||sv.confidence<.9)failures.push('Swedish metadata majority failed');
      if(en.language!=='en'||en.confidence<.9)failures.push('English metadata majority failed');
      if(mixed.language!=='mixed')failures.push('Mixed metadata classification failed');
      if(fallbackSv.language!=='sv')failures.push('Swedish text fallback failed');
      if(fallbackEn.language!=='en')failures.push('English text fallback failed');
      const profile=calculateDocumentLanguage([{text:'svensk text',language:'sv'},{text:'English text with more letters',language:'en'},{text:'mixed',language:'mixed'}]);
      if(!['en','mixed'].includes(profile.language)||profile.mixedParagraphs!==1)failures.push('Document language profile failed');
      if(failures.length)console.error('Language regression tests failed:',failures);else console.info('Language regression tests passed (Swedish, English, mixed and fallback cases).');
      return failures;
    }
