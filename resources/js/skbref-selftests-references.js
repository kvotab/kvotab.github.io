/* ==========================================================================
   SKB REFERENCE CHECKER — selftests-references

   Self-tests for abbreviated names, designations and the reference guide.
   Run from skbref-boot.js.

   Part of the page script that used to live inline in skbref.html. The
   modules share one global scope, as classic scripts do, and are loaded in
   the order they were written in; skbref-boot.js runs everything.

   The four-space indent is from the <script> block this came out of, and is
   kept deliberately: removing it would also remove four spaces from every
   line inside a multi-line template literal, changing the whitespace of the
   HTML this page generates.
   ========================================================================== */
'use strict';

    function runAbbreviatedNameRegressionTests() {
      const failures = [];

      const ABBREVIATED = [
        'Post-closure safety report', 'Barrier process report',
        'Biosphere synthesis report', 'Climate report', 'Data report',
        'FEP report', 'Radionuclide transport report', 'SFR site description',
        'Initial state report', 'Buffer, backfill and closure process report'
      ];
      const AUTHOR_LISTS = [
        'Mårtensson P, Luterkort D, Nyblad B, Wimelius H, Pettersson A, Aghili B, Andolfsson T',
        'Sandén T, Nilsson U, Johannesson L-E, Hagman P, Nilsson G',
        'Duro L, Grivé M, Domènech C, Roman-Ross G, Bruno J',
        'Höglund L O', 'Mårtensson P, Vogt C', 'Pusch R', 'Back P-E',
        'Wyllie D C, Mah C W'
      ];

      for (const name of ABBREVIATED) {
        const extracted = extractAbbreviatedReferenceName(`${name}, 2023. A title. SKB TR-23-01, Svensk Kärnbränslehantering AB.`);
        if (extracted !== name) {
          failures.push(`Abbreviated name not recognised: "${name}" gave ${JSON.stringify(extracted)}`);
        }
      }

      for (const authors of AUTHOR_LISTS) {
        const body = `${authors}, 2022. A title. SKB TR-22-01, Svensk Kärnbränslehantering AB.`;
        if (extractAbbreviatedReferenceName(body) !== null) {
          failures.push(`Author list read as an abbreviated name: "${authors}"`);
        }
        /* And it must still yield an author-year key, with the year kept. */
        const key = extractReferenceKey(body);
        if (!key || !/\b2022\b/.test(key)) {
          failures.push(`Author list did not yield a year-bearing key: "${authors}" gave ${JSON.stringify(key)}`);
        }
      }

      /*
        The case that produced the duplicates: two works by the same authors,
        inside an abbreviated-names section, must stay apart.
      */
      let index = 0;
      const paragraph = text => ({
        index: index++, localIndex: 0, text, style: '', section: 'References',
        sourcePart: 'fixture', sourceLabel: 'Fixture', documentRegion: 'references',
        isReferenceList: true, language: 'en', languageConfidence: 1,
        languageRanges: [], formatSpans: []
      });
      const entries = extractRefEntries([
        paragraph('References with abbreviated names'),
        paragraph('Post-closure safety report, 2023. Post-closure safety for SFR. SKB TR-23-01, Svensk Kärnbränslehantering AB.'),
        paragraph('Höglund L O, 2001. Project SAFE. Modelling of long-term concrete degradation. SKB R-01-08, Svensk Kärnbränslehantering AB.'),
        paragraph('Höglund L O, 2014. The impact of concrete degradation on the SFR barrier functions. SKB R-13-40, Svensk Kärnbränslehantering AB.')
      ]);
      const keys = entries.map(entry => entry.key);
      if (keys[0] !== 'Post-closure safety report') {
        failures.push(`The abbreviated name was lost: ${JSON.stringify(keys[0])}`);
      }
      if (keys[1] === keys[2]) {
        failures.push(`Two works by the same author collided on one key: ${JSON.stringify(keys[1])}`);
      }
      for (const key of keys.slice(1)) {
        if (!/\b(?:2001|2014)\b/.test(key)) failures.push(`Key lost its year: ${JSON.stringify(key)}`);
      }

      if (failures.length) console.error('Abbreviated-name regression tests failed:', failures);
      else console.info(`Abbreviated-name regression tests passed (${ABBREVIATED.length} abbreviated names and ${AUTHOR_LISTS.length} author lists kept apart).`);
      return failures;
    }

    function runDesignationRegressionTests() {
      const failures = [];
      let index = 0;
      const paragraph = (text, extra = {}) => ({
        index: index++, localIndex: 0, text, style: '', section: 'Body',
        sourcePart: 'word/document.xml', sourceLabel: 'Main text',
        documentRegion: 'body', regionLabel: 'Main text',
        language: 'en', languageConfidence: 1, languageRanges: [], formatSpans: [], ...extra
      });

      /* The designation forms that occur, each with the key it must produce. */
      const CITATION_FORMS = [
        ['The regulations (SSMFS 2008:37) specify a dose limit.', 'SSMFS 2008:37'],
        ['The regulations SSMFS (2008:37) specify a dose limit.', 'SSMFS 2008:37'],
        ['Conditions will not change (SSMFS 2008:37, Section 10).', 'SSMFS 2008:37'],
        ['A programme was developed (SOU 2010:6) to handle the waste.', 'SOU 2010:6'],
        ['It is delineated in the Act on Nuclear Activities (SFS 1984:3).', 'SFS 1984:3'],
        ['It was further noted that this applies (Ds 2007:30).', 'Ds 2007:30'],
        ['As laid out in the stone standard (SS-EN 1936:1999).', 'SS-EN 1936:1999']
      ];
      for (const [text, expected] of CITATION_FORMS) {
        const found = [];
        findDesignationCitations(paragraph(text), found);
        if (!found.some(citation => citation.key === expected && citation.type === 'designation')) {
          failures.push(`Designation not extracted: expected "${expected}" in "${text}"`
            + (found.length ? ` (found ${found.map(c => c.key).join(', ')})` : ''));
        }
        if (found.length !== 1) {
          failures.push(`Designation extracted ${found.length} times, expected once: "${text}"`);
        }
      }

      /* The reference list enters such a work under its designation. */
      const REFERENCE_KEYS = [
        ['SSMFS 2008:21. Strålsäkerhetsmyndighetens föreskrifter och allmänna råd om säkerhet vid slutförvaring av kärnämne och kärnavfall (Regulations concerning safety in connection with the disposal of nuclear material and nuclear waste). Stockholm: Swedish Radiation Safety Authority. (In Swedish.)', 'SSMFS 2008:21'],
        ['SFS 1984:3. Lag om kärnteknisk verksamhet. Stockholm: Riksdagen.', 'SFS 1984:3'],
        ['SOU 2010:6. Kunskapslägesrapport på kärnavfallsområdet 2010. Stockholm: Kärnavfallsrådet. (In Swedish.)', 'SOU 2010:6'],
        ['SS-EN 1936:1999. Natural stone test methods. Stockholm: Swedish Standards Institute.', 'SS-EN 1936:1999']
      ];
      for (const [body, expected] of REFERENCE_KEYS) {
        if (extractReferenceKey(body) !== expected) {
          failures.push(`Reference key: expected "${expected}", got "${extractReferenceKey(body)}"`);
        }
      }

      /* An ordinary author-year reference must not be read as a designation. */
      for (const body of [
        'Sena C, Grandia F, 2008. Complementary modelling. SKB R-08-107, Svensk Kärnbränslehantering AB.',
        'Akagawa F, 2006. Redox front formation. Geochemistry 6, 49–56.',
        'Brown C L, 2003. Thermodynamics. Vol 2. 2nd ed. New York: McGraw-Hill.'
      ]) {
        if (extractDesignationKey(body, true)) {
          failures.push(`Author-year reference misread as a designation: "${body.slice(0, 40)}…"`);
        }
      }

      /*
        The whole point: two regulations of the same year stay apart, and the
        guide's own dual form "SSMFS 2008:21 (SSM 2008)" yields both citations.
      */
      const references = [
        'SSMFS 2008:21. Föreskrifter om säkerhet vid slutförvaring. Stockholm: Strålsäkerhetsmyndigheten. (In Swedish.)',
        'SSMFS 2008:37. Föreskrifter om skydd av människors hälsa. Stockholm: Strålsäkerhetsmyndigheten. (In Swedish.)',
        'SSM, 2008. Föreskrifter och allmänna råd. Stockholm: Strålsäkerhetsmyndigheten. (SSMFS 2008:21) (In Swedish.)'
      ].map(text => paragraph(text, { isReferenceList: true, section: 'References' }));
      const body = [
        'A dose limit is given in (SSMFS 2008:37).',
        'The regulations SSMFS 2008:21 (SSM 2008) state that the repository must be safe.'
      ].map(text => paragraph(text));

      const entries = extractRefEntries(references);
      const report = crossReference(entries, findInTextCites(body, entries));
      if (report.duplicateKeys.length) {
        failures.push('Two regulations of the same year were reported as duplicates');
      }
      if (report.orphanCites.length) {
        failures.push(`Designation citations left unmatched: ${report.orphanCites.map(c => c.key).join(', ')}`);
      }
      if (report.uncitedRefs.length) {
        failures.push(`Designation references left uncited: ${report.uncitedRefs.map(e => e.key).join(', ')}`);
      }
      const matched = Object.fromEntries(entries.map(entry =>
        [entry.key, [...new Set(entry.cites.map(citation => citation.key))].join(',')]));
      if (matched['SSMFS 2008:37'] !== 'SSMFS 2008:37') {
        failures.push(`SSMFS 2008:37 matched "${matched['SSMFS 2008:37']}"`);
      }
      if (matched['SSMFS 2008:21'] !== 'SSMFS 2008:21') {
        failures.push(`SSMFS 2008:21 matched "${matched['SSMFS 2008:21']}"`);
      }
      if (matched['SSM 2008'] !== 'SSM 2008') {
        failures.push(`SSM 2008 matched "${matched['SSM 2008']}"`);
      }

      /* None of the writing rules may object to any of these forms. */
      for (const [text] of CITATION_FORMS) {
        const issues = findOfficialSkbTextIssues([paragraph(text)], { language: 'en', confidence: 1 });
        if (issues.length) {
          failures.push(`A valid designation citation was flagged: "${text}" -> ${issues[0].description}`);
        }
      }

      if (failures.length) console.error('Designation regression tests failed:', failures);
      else console.info(`Designation regression tests passed (${CITATION_FORMS.length} citation forms and ${REFERENCE_KEYS.length} reference forms from sections 4.10-4.12).`);
      return failures;
    }

    function runReferenceGuideRegressionTests() {
      const failures = [];

      /* The availability notice belongs to the list, not to a single entry. */
      const availabilityNotice = { text: "SKB's (Svensk Kärnbränslehantering AB) publications can be found at "
        + 'http://www.skb.com/publications. SKBdoc documents will be submitted upon request to document@skb.se.' };

      function referenceIssues(body, swedish = false) {
        const entry = { key: extractAuthorYearKey(body) || body.slice(0, 20), body, paraIndex: 0, num: null, cites: [] };
        return findOfficialSkbReferenceIssues([entry], [availabilityNotice, { text: body }], swedish)
          .map(issue => issue.description);
      }

      /* Chapter 4: references written exactly as the guide writes them. */
      const CORRECT = [
        'Akagawa F, Yoshida H, Yogo S, Yamomoto K, 2006. Redox front formation in fractured crystalline rock: an analogue of matrix diffusion in an oxidizing front along water-conducting fractures. Geochemistry: Exploration, Environment, Analysis 6, 49–56.',
        'Sena C, Grandia F, Arcos D, Molinero J, Duro L, 2008. Complementary modelling of radionuclide retention in the near-surface system at Forsmark. SKB R-08-107, Svensk Kärnbränslehantering AB.',
        'Brown C L, 2003. Thermodynamics. Vol 2. 2nd ed. New York: McGraw-Hill.',
        'Jenne E A (ed), 1998. Adsorption of metals by geomedia: variables, mechanisms, and model applications. San Diego, CA: Academic Press.',
        'Bugmann H K M, 1994. On the ecology of mountainous forest in a changing climate: a simulation study. PhD thesis. Swiss Federal Institute of Technology.',
        'Leskinen N, Ronneteg U, 2011. Tillverkning av kapselkomponenter. SKBdoc 1175208 ver 5.0, Svensk Kärnbränslehantering AB.',
        'Keller B, 2002. Nuclear nightmares. The New York Times, 26 May, 6.',
        'Itasca, 2007. 3DEC – 3-dimensional distinct element code, version 4.1. Minneapolis, MN: Itasca Consulting Group, Inc.',
        'SKB, 2003. Planning report for the safety assessment SR-Can. SKB TR-03-08, Svensk Kärnbränslehantering AB.',
        'Sibeck L, 2014. Toughness of ferritic nodular irons. Report 20230-C, issue 7, Swerea Swecast. SKBdoc 1265058 ver 3.0, Svensk Kärnbränslehantering AB.',
        'Östergren I, Falk R, Mjönes L, Ek B-M, 2003. Mätning av naturlig radioaktivitet i dricksvatten: test av mätmetoder och resultat av en pilotundersökning. SSI Rapport 2003:07, Statens strålskyddsinstitut (Swedish Radiation Protection Authority). (In Swedish.)',
        'van der Veen C J, 2007. Fracture propagation as means of rapidly transferring surface meltwater to the base of glaciers. Geophysical Research Letters 34, L01501. https://doi.org/10.1029/2006GL028385',
        'Lamarsh J R, Baratta A J, 2001. Introduction to nuclear engineering. 3rd ed. Upper Saddle River, NJ: Prentice Hall.',
        'Coulson J M, Richardson J F, Backhurst J R, Harker J H, 1999. Chemical engineering. Vol 1. Fluid flow, heat transfer and mass transfer. 6th ed. Oxford: Pergamon.',
        'Bardet J P, Huang Q, Proubet J, 1992. A micromechanical investigation of the influence of couple stresses on failure in granular materials. In Tillerson J A, Wawersik W R (eds). Proceedings of the 33rd U.S. Symposium on Rock Mechanics, Santa Fe, New Mexico, 3–5 June 1992. Rotterdam: Balkema, 609–617.',
        'Birks H J B, 1995. Quantitative palaeoenvironmental reconstructions. In Maddy D, Brew J S (eds). Statistical modelling of quaternary science data. Cambridge: Quaternary Research Association. (Technical Guide 5), 161–254.',
        'García Ambrosiani K, 1990. Pleistocene stratigraphy in central and northern Sweden: a reinvestigation of some classical sites. Stockholm: Stockholm University. (Reports of Department of Quaternary Research 16)',
        'Kärnavfallsrådet, 2010. Kunskapslägesrapport på kärnavfallsområdet 2010: utmaningar för slutförvarsprogrammet. Stockholm: Kärnavfallsrådet. (Statens offentliga utredningar 2010:6) (In Swedish.)',
        'SSMFS 2008:21. Strålsäkerhetsmyndighetens föreskrifter och allmänna råd om säkerhet vid slutförvaring av kärnämne och kärnavfall. Stockholm: Strålsäkerhetsmyndigheten (Swedish Radiation Safety Authority). (In Swedish.)',
        'DOF, n d. Natur og fugle. Dansk Ornitologisk Forening. Available at: http://www.dofbasen.dk/ART/ [15 August 2011]. (In Danish.)'
      ];
      for (const body of CORRECT) {
        const found = referenceIssues(body);
        if (found.length) failures.push(`False positive on a reference from the guide: "${body.slice(0, 50)}…" → ${found[0]}`);
      }

      /* The errors the guide names, each with the wording that must report it. */
      const INCORRECT = [
        ['Akagawa F, 2006. Redox front formation. Geochemistry 6(2), 49–56.', /issue number/i],
        ['Akagawa F, 2006. Redox front formation. Geochemistry vol 6, 49–56.', /without the abbreviation/i],
        ['Ponti C, 2000. Personal communication.', /personal communication/i],
        ['Berger, A., Loutre, M. F., 2002. Title of the work. Journal of Climate 15, 1–20.', /comma after the surname/i],
        ['Birgersson M, Karnland O and Nilsson U, 2010. Title of the work. SKB TR-10-01, Svensk Kärnbränslehantering AB.', /Separate all authors with commas/i],
        ['Andersson J et al., 2012. Title of the work. SKB TR-12-01, Svensk Kärnbränslehantering AB.', /do not use et al/i],
        ['Leskinen N, 2011. Tillverkning. SKBdoc 1175208, Svensk Kärnbränslehantering AB.', /must include its version/i],
        /* Section 3.2: pages without pp, (ed) without a full stop, 2nd ed, the language note */
        ['Akagawa F, 2006. Redox front formation. Geochemistry 6, pp 49–56.', /without p, pp or s/i],
        ['Jenne E A (Ed.), 1998. Adsorption of metals by geomedia. San Diego, CA: Academic Press.', /\(ed\) or \(eds\)/i],
        ['Lamarsh J R, Baratta A J, 2001. Introduction to nuclear engineering. 3rd edn. Upper Saddle River, NJ: Prentice Hall.', /2nd ed, 3rd ed/i],
        ['Östergren I, 2003. Mätning av naturlig radioaktivitet. SSI Rapport 2003:07, Statens strålskyddsinstitut. (In Swedish)', /full stop inside the parenthesis/i],
        /* Sections 4.1 and 4.7 */
        ['SKB, 2003. Planning report for the safety assessment SR-Can. SKB TR-03-08.', /Svensk Kärnbränslehantering AB, after/i],
        ['Brown C L, 2003. Thermodynamics. Vol. 2. 2nd ed. New York: McGraw-Hill.', /Vol 2, without a full stop/i]
      ];
      for (const [body, expected] of INCORRECT) {
        const found = referenceIssues(body);
        if (!found.some(description => expected.test(description))) {
          failures.push(`Missed ${expected} in "${body.slice(0, 50)}…"${found.length ? ` (found instead: ${found[0]})` : ''}`);
        }
      }

      /* Chapter 6: a Swedish publication uses the Swedish abbreviations. */
      if (!referenceIssues('Moore J, Allard B (eds), 2001. Titel. Stockholm: Förlag.', true).some(d => /\(red\)/.test(d))) {
        failures.push('Swedish reference list: (eds) should be reported in favour of (red)');
      }
      if (referenceIssues('Moore J, Allard B (eds), 2001. Title. Berlin: Springer.', false).some(d => /\(red\)/.test(d))) {
        failures.push('English reference list: (eds) must not be reported');
      }
      if (!referenceIssues('Cooke S, 2009. A nuclear waste. The New York Times, 17 mars. Available at: http://www.nytimes.com/x [12 maj 2009].', true).some(d => /Tillgänglig:/.test(d))) {
        failures.push('Swedish reference list: "Available at:" should be reported in favour of "Tillgänglig:"');
      }

      /*
        Section 3.2: the author, the year and the full stop after it are bold,
        and so is a designation an entry is entered under. The bold ranges are
        what the .docx reader records for each entry.
      */
      const boldEntry = (body, boldSpans) => ({ key: extractAuthorYearKey(body) || body.slice(0, 12), body, paraIndex: 0, num: null, cites: [], boldSpans });
      const boldFindings = list => findBoldHeadingIssues(list, FULL_CAPABILITIES).map(issue => issue.description);
      const clair = 'Clair B, 2004. A title of the work. Stockholm: Förlag.';
      if (boldFindings([boldEntry(clair, [{ start: 0, end: 14 }])]).length) failures.push('Bold heading: a correctly bold "Clair B, 2004." was reported');
      if (!boldFindings([boldEntry(clair, [{ start: 0, end: 13 }])]).some(d => /full stop after the year in bold/i.test(d))) failures.push('Bold heading: a roman full stop after the year was not reported');
      if (!boldFindings([boldEntry(clair, [])]).some(d => /in bold/i.test(d))) failures.push('Bold heading: an entry with no bold was not reported');
      if (boldFindings([boldEntry('SFS 1984:3. Lag om kärnteknisk verksamhet. Stockholm: Riksdagen.', [{ start: 0, end: 11 }])]).length) failures.push('Bold heading: a bold designation heading was reported');
      const plainList = ['Adams A, 2001. X. Y.', 'Berg B, 2002. X. Y.', 'Cole C, 2003. X. Y.', 'Dahl D, 2004. X. Y.'].map(body => boldEntry(body, []));
      if (boldFindings(plainList).length !== 1) failures.push(`Bold heading: a list with no bold at all gave ${boldFindings(plainList).length} findings, expected one`);

      /* Chapter 5: the three-tier order, using the guide's own example list. */
      const ordered = [
        'Bentz A, 1997. Title. SKB TR-97-01, Svensk Kärnbränslehantering AB.',
        'Bentz A, 2007. Title. SKB TR-07-01, Svensk Kärnbränslehantering AB.',
        'Bentz A, Conway M, 2001. Title. SKB TR-01-01, Svensk Kärnbränslehantering AB.',
        'Bentz A, Haecker P, 2005. Title. SKB TR-05-01, Svensk Kärnbränslehantering AB.',
        'Bentz A, Stutzman T, 1999. Title. SKB TR-99-01, Svensk Kärnbränslehantering AB.',
        'Bentz A, Garboczi M, Haecker P, Jensen J, 1994. Title. SKB TR-94-01, Svensk Kärnbränslehantering AB.',
        'Bentz A, Coveney A, Garboczi M, Kleyn E, Stutzman T, 1999a. Title. SKB TR-99-02, Svensk Kärnbränslehantering AB.',
        'Bentz A, Jensen J, Hansen J, Olesen I, Stang E, Haecker P, 1999b. Title. SKB TR-99-03, Svensk Kärnbränslehantering AB.',
        'Bentz A, Williams J, MacKenzie P, 2001. Title. SKB TR-01-02, Svensk Kärnbränslehantering AB.'
      ].map(body => ({ key: extractAuthorYearKey(body), body, paraIndex: 0, num: null, cites: [] }));
      const orderIssues = findReferenceListOrderIssues(ordered);
      if (orderIssues.length) failures.push(`Reference order: ${orderIssues.length} false positive(s) on the list in chapter 5`);
      if (findReferenceListOrderIssues([ordered[1], ordered[0]]).length !== 1) {
        failures.push('Reference order: a genuinely reversed pair was not reported');
      }

      /* Section 4.13: the access date is written in square brackets. */
      const webPage = { key: 'IUCN 2011', body: 'IUCN, 2011. The IUCN red list of threatened species. Version 2011.1. '
        + 'Available at: http://www.iucnredlist.org/ [24 September 2011].', paraIndex: 0, num: null, cites: [] };
      if (checkSkbFormat([webPage]).some(issue => /access date/i.test(issue.issue))) {
        failures.push('Access date: the bracketed form used throughout the guide was reported as missing');
      }
      const undated = { ...webPage, body: 'IUCN, 2011. The IUCN red list. Available at: http://www.iucnredlist.org/' };
      if (!checkSkbFormat([undated]).some(issue => /access date/i.test(issue.issue))) {
        failures.push('Access date: a genuinely missing access date was not reported');
      }

      if (failures.length) console.error('Reference-guide regression tests failed:', failures);
      else console.info(`Reference-guide regression tests passed (${CORRECT.length} correct and ${INCORRECT.length} incorrect references from 1215757, plus ordering and access-date checks).`);
      return failures;
    }
