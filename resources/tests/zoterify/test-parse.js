#!/usr/bin/env node
/* zoterify-parse.js: what it finds in a paragraph, and the reference list.

   Each case is a paragraph and the groups the parser must return, written
   out by hand: the kind of group, the text it covers, and for each
   reference its label, locator, prefix, suffix and whether its author is
   left in the text.

       node resources/tests/zoterify/test-parse.js

   Exit status is 0 when every check passes. */
'use strict';

const P = require('../../js/zoterify-parse.js');

let checks = 0;
const failures = [];
function check(label, got, want) {
  checks++;
  const a = JSON.stringify(got);
  const b = JSON.stringify(want);
  if (a !== b) failures.push(`${label}\n     got  ${a}\n     want ${b}`);
}

/** A group as [kind, text, ...references]; a reference as its label with
    " @label:value", " <prefix>", " >suffix<" and " [a]" (author left in the
    text) added where they apply. */
function describe(g) {
  return [g.kind, g.text, ...g.refs.map((r) => {
    let s = P.refLabel(r);
    if (r.locator) s += ` @${r.locatorLabel}:${r.locator}`;
    if (r.prefix) s += ` <${r.prefix}>`;
    if (r.suffix) s += ` >${r.suffix}<`;
    if (r.suppressAuthor) s += ' [a]';
    return s;
  })].concat(g.problem ? [`! ${g.problem}`] : []);
}
const found = (text) => P.findInParagraph(text).map(describe);

const CASES = [
  // ---- parenthetical, one reference
  ['Erosion is slow (Smith, 2020) in most holes.', [['parenthesis', '(Smith, 2020)', 'Smith 2020']]],
  ['(Smith 2020)', [['parenthesis', '(Smith 2020)', 'Smith 2020']]],
  ['(Smith & Jones, 2020)', [['parenthesis', '(Smith & Jones, 2020)', 'Smith & Jones 2020']]],
  ['(Smith and Jones 2020)', [['parenthesis', '(Smith and Jones 2020)', 'Smith & Jones 2020']]],
  ['(Andersson och Berglund 2020)', [['parenthesis', '(Andersson och Berglund 2020)', 'Andersson & Berglund 2020']]],
  ['(Cousins, O’Gorman, and Stierand 2010)', [['parenthesis', '(Cousins, O’Gorman, and Stierand 2010)', 'Cousins, O’Gorman & Stierand 2010']]],
  ['(Smith et al., 2020)', [['parenthesis', '(Smith et al., 2020)', 'Smith et al. 2020']]],
  ['(Smith et al 2020)', [['parenthesis', '(Smith et al 2020)', 'Smith et al. 2020']]],
  ['(Smith m.fl. 2020)', [['parenthesis', '(Smith m.fl. 2020)', 'Smith et al. 2020']]],
  ['(Smith m. fl., 2020)', [['parenthesis', '(Smith m. fl., 2020)', 'Smith et al. 2020']]],
  ['(Müller u. a. 2019)', [['parenthesis', '(Müller u. a. 2019)', 'Müller et al. 2019']]],
  ['(van der Berg 2019)', [['parenthesis', '(van der Berg 2019)', 'van der Berg 2019']]],
  ['(de la Cruz, 2018)', [['parenthesis', '(de la Cruz, 2018)', 'de la Cruz 2018']]],
  ['(af Klercker 2001)', [['parenthesis', '(af Klercker 2001)', 'af Klercker 2001']]],
  ['(Åkesson, 2019)', [['parenthesis', '(Åkesson, 2019)', 'Åkesson 2019']]],
  ['(Öberg 2020)', [['parenthesis', '(Öberg 2020)', 'Öberg 2020']]],
  ['(Dvořák, 2020)', [['parenthesis', '(Dvořák, 2020)', 'Dvořák 2020']]],
  ['(Vargas-Sánchez and López-Guzmán 2022)', [['parenthesis', '(Vargas-Sánchez and López-Guzmán 2022)', 'Vargas-Sánchez & López-Guzmán 2022']]],
  ['(SKB 2010)', [['parenthesis', '(SKB 2010)', 'SKB 2010']]],
  ['(Svensk Kärnbränslehantering AB 2010)', [['parenthesis', '(Svensk Kärnbränslehantering AB 2010)', 'Svensk Kärnbränslehantering AB 2010']]],
  ['(Intergovernmental Panel on Climate Change (IPCC) 2022)', [['parenthesis', '(Intergovernmental Panel on Climate Change (IPCC) 2022)', 'Intergovernmental Panel on Climate Change 2022']]],
  ['(J. Smith 2020)', [['parenthesis', '(J. Smith 2020)', 'Smith 2020']]],
  ['(Smith, Ed., 2023)', [['parenthesis', '(Smith, Ed., 2023)', 'Smith 2023']]],
  // ---- years
  ['(Smith 2020a)', [['parenthesis', '(Smith 2020a)', 'Smith 2020a']]],
  ['(Smith 2020a, b)', [['parenthesis', '(Smith 2020a, b)', 'Smith 2020a', 'Smith 2020b']]],
  ['(Smith 2019, 2020)', [['parenthesis', '(Smith 2019, 2020)', 'Smith 2019', 'Smith 2020']]],
  ['(Aschemann-Witzel et al. 2017; 2018a)', [['parenthesis', '(Aschemann-Witzel et al. 2017; 2018a)', 'Aschemann-Witzel et al. 2017', 'Aschemann-Witzel et al. 2018a']]],
  ['(SKB, n.d.)', [['parenthesis', '(SKB, n.d.)', 'SKB n.d.']]],
  ['(Nilsson u.å.)', [['parenthesis', '(Nilsson u.å.)', 'Nilsson u.å.']]],
  ['(Jones, in press)', [['parenthesis', '(Jones, in press)', 'Jones in press']]],
  ['(Jones forthcoming)', [['parenthesis', '(Jones forthcoming)', 'Jones forthcoming']]],
  // ---- locators
  ['(Smith, 2020, p. 45)', [['parenthesis', '(Smith, 2020, p. 45)', 'Smith 2020 @page:45']]],
  ['(Smith 2020: 12–14)', [['parenthesis', '(Smith 2020: 12–14)', 'Smith 2020 @page:12–14']]],
  ['(Smith, 2020:88)', [['parenthesis', '(Smith, 2020:88)', 'Smith 2020 @page:88']]],
  ['(Smith 2020, pp. 3-4)', [['parenthesis', '(Smith 2020, pp. 3-4)', 'Smith 2020 @page:3–4']]],
  ['(Smith 2020, s. 12 f.)', [['parenthesis', '(Smith 2020, s. 12 f.)', 'Smith 2020 @page:12 f.']]],
  ['(Smith 2020, ch. 3)', [['parenthesis', '(Smith 2020, ch. 3)', 'Smith 2020 @chapter:3']]],
  ['(Smith 2020, kap. 3)', [['parenthesis', '(Smith 2020, kap. 3)', 'Smith 2020 @chapter:3']]],
  ['(Smith 2020, sec. 2)', [['parenthesis', '(Smith 2020, sec. 2)', 'Smith 2020 @section:2']]],
  ['(Smith 2020, fig. 4)', [['parenthesis', '(Smith 2020, fig. 4)', 'Smith 2020 @figure:4']]],
  ['(Smith 2020, 141)', [['parenthesis', '(Smith 2020, 141)', 'Smith 2020 @page:141']]],
  // ---- several references
  ['(Smith, 2020; Jones, 2019)', [['parenthesis', '(Smith, 2020; Jones, 2019)', 'Smith 2020', 'Jones 2019']]],
  ['(Smith 2020 and Jones 2019)', [['parenthesis', '(Smith 2020 and Jones 2019)', 'Smith 2020', 'Jones 2019']]],
  ['(Andersson 2010, Berglund and Lindborg 2017)', [['parenthesis', '(Andersson 2010, Berglund and Lindborg 2017)', 'Andersson 2010', 'Berglund & Lindborg 2017']]],
  ['(Omori et al. 1974, 1975, Sielicki et al. 1978, Shirai and Hisatsuka 1979, Grbić-Galić et al. 1990)',
    [['parenthesis', '(Omori et al. 1974, 1975, Sielicki et al. 1978, Shirai and Hisatsuka 1979, Grbić-Galić et al. 1990)',
      'Omori et al. 1974', 'Omori et al. 1975', 'Sielicki et al. 1978', 'Shirai & Hisatsuka 1979', 'Grbić-Galić et al. 1990']]],
  // ---- words around references are kept
  ['(see Smith 2020)', [['parenthesis', '(see Smith 2020)', 'Smith 2020 <see>']]],
  ['(cf. Stone et al. 2018)', [['parenthesis', '(cf. Stone et al. 2018)', 'Stone et al. 2018 <cf.>']]],
  ['(e.g. Myhrvold 2011)', [['parenthesis', '(e.g. Myhrvold 2011)', 'Myhrvold 2011 <e.g.>']]],
  ['(se även Nilsson 2019)', [['parenthesis', '(se även Nilsson 2019)', 'Nilsson 2019 <se även>']]],
  ['(see Garcia & Lopez, 2021; Brown 2019)', [['parenthesis', '(see Garcia & Lopez, 2021; Brown 2019)', 'Garcia & Lopez 2021 <see>', 'Brown 2019']]],
  ['(Smith 2020, emphasis added; see also Jones 2021, p. 3)',
    [['parenthesis', '(Smith 2020, emphasis added; see also Jones 2021, p. 3)', 'Smith 2020 >emphasis added<', 'Jones 2021 @page:3 <see also>']]],
  ['(the basis of justification in Boltanski and Thévenot 2006, 141–2)',
    [['parenthesis', '(the basis of justification in Boltanski and Thévenot 2006, 141–2)', 'Boltanski & Thévenot 2006 @page:141–2 <the basis of justification in>']]],
  ['(Smith 2020, for a review)', [['parenthesis', '(Smith 2020, for a review)', 'Smith 2020 >for a review<']]],
  // ---- narrative
  ['As Smith (2020) showed.', [['narrative', '(2020)', 'Smith 2020 [a]']]],
  ['As Smith (2020, p. 4) showed.', [['narrative', '(2020, p. 4)', 'Smith 2020 @page:4 [a]']]],
  ['Results from Öhman et al. (2014) agree.', [['narrative', '(2014)', 'Öhman et al. 2014 [a]']]],
  ['As Smith & Jones (2020) note.', [['narrative', '(2020)', 'Smith & Jones 2020 [a]']]],
  ['As Smith, Jones and Brown (2020) note.', [['narrative', '(2020)', 'Smith, Jones & Brown 2020 [a]']]],
  ['In Sweden, Smith (2020) found it.', [['narrative', '(2020)', 'Smith 2020 [a]']]],
  ['Enligt Smith (2020) är det så.', [['narrative', '(2020)', 'Smith 2020 [a]']]],
  ['Smith m.fl. (2019) visade det.', [['narrative', '(2019)', 'Smith et al. 2019 [a]']]],
  ['Pellegrino’s (2021) argument holds.', [['narrative', '(2021)', 'Pellegrino 2021 [a]']]],
  ['a point made by M Nilsson (2020, 67–76).', [['narrative', '(2020, 67–76)', 'Nilsson 2020 @page:67–76 [a]']]],
  ['Swedish Food Agency (2025) recommends it.', [['narrative', '(2025)', 'Swedish Food Agency 2025 [a]']]],
  ['the times Gunia & Gunia, (2022).', [['narrative', '(2022)', 'Gunia & Gunia 2022 [a]']]],
  ['Lane argues that “quality is contingent” (2014, 20).', [['narrative', '(2014, 20)', 'Lane 2014 @page:20 [a]']]],
  ['This follows Lane (2014, 20; cf. Bildtgård 2010) closely.',
    [['parenthesis', '(2014, 20; cf. Bildtgård 2010)', 'Lane 2014 @page:20 [a]', 'Bildtgård 2010 <cf.>']]],
  ['Following Hedin et al. (2014, 20; cf. Bildtgård 2010), we go on.',
    [['parenthesis', '(2014, 20; cf. Bildtgård 2010)', 'Hedin et al. 2014 @page:20 [a]', 'Bildtgård 2010 <cf.>']]],
  ['First sentence. And Smith (2020) showed it.', [['narrative', '(2020)', 'Smith 2020 [a]']]],
  // ---- numbered
  ['Results [1], [2, 3] and [4-6] agree.', [['numbered', '[1]', '[1]'], ['numbered', '[2, 3]', '[2]', '[3]'], ['numbered', '[4-6]', '[4]', '[5]', '[6]']]],
  ['As shown [7–9, 12].', [['numbered', '[7–9, 12]', '[7]', '[8]', '[9]', '[12]']]],
  // ---- nested and bare
  ['(see Annex D of Publication 100 (ICRP, 2006) and Publication 141 (ICRP, 2019)).',
    [['parenthesis', '(ICRP, 2006)', 'ICRP 2006'], ['parenthesis', '(ICRP, 2019)', 'ICRP 2019']]],
  ['(For more details see Publication 100 (ICRP, 2006). In Publication 30 (ICRP, 1980), the',
    [['parenthesis', '(ICRP, 2006)', 'ICRP 2006'], ['parenthesis', '(ICRP, 1980)', 'ICRP 1980']]],
  ['MDH Engineered Solutions Corp 2003', [['bare', 'MDH Engineered Solutions Corp 2003', 'MDH Engineered Solutions Corp 2003']]],
  ['Hallema et al. 2015 ', [['bare', 'Hallema et al. 2015', 'Hallema et al. 2015']]],
  // ---- as SKB's reports cite: report numbers
  ['The safety case (SKB TR-11-01) holds.', [['parenthesis', '(SKB TR-11-01)', 'SKB TR-11-01']]],
  ['As reported in SKB (TR-10-66), it holds.', [['narrative', '(TR-10-66)', 'SKB TR-10-66 [a]']]],
  ['Data are given in SKB TR-11-01 and SKB R-09-20.', [['narrative', 'TR-11-01', 'SKB TR-11-01 [a]'], ['narrative', 'R-09-20', 'SKB R-09-20 [a]']]],
  ['(SKB TR-10-52, Section 3.2)', [['parenthesis', '(SKB TR-10-52, Section 3.2)', 'SKB TR-10-52 @section:3.2']]],
  ['(SKB TR 99-01; SKB P-04-221)', [['parenthesis', '(SKB TR 99-01; SKB P-04-221)', 'SKB TR-99-01', 'SKB P-04-221']]],
  ['(SKB TR‑11‑01)', [['parenthesis', '(SKB TR‑11‑01)', 'SKB TR-11-01']]],
  ['(SKB R-09-20, R-09-22)', [['parenthesis', '(SKB R-09-20, R-09-22)', 'SKB R-09-20', 'SKB R-09-22']]],
  ['(SKB 2011, TR-11-01)', [['parenthesis', '(SKB 2011, TR-11-01)', 'SKB TR-11-01']]],
  ['the report (TR-10-66)', [['parenthesis', '(TR-10-66)', 'SKB TR-10-66']]],
  ['(SKBdoc 1175208)', [['parenthesis', '(SKBdoc 1175208)', 'SKBdoc 1175208']]],
  ['(see SKB R-09-20; Smith 2020)', [['parenthesis', '(see SKB R-09-20; Smith 2020)', 'SKB R-09-20 <see>', 'Smith 2020']]],
  ['(SDM, SKB R-11-04)', [['parenthesis', '(SDM, SKB R-11-04)', 'SKB R-11-04 <SDM>']]],
  ['(i.e. SAFE SKB R-98-43 and SAR-08 SKB R-08-130)',
    [['parenthesis', '(i.e. SAFE SKB R-98-43 and SAR-08 SKB R-08-130)', 'SKB R-98-43 <i.e. SAFE> >and SAR-08<', 'SKB R-08-130']]],
  // ---- designations: the number after the colon is not a page
  ['Limits are set (SSMFS 2008:37).', [['parenthesis', '(SSMFS 2008:37)', 'SSMFS 2008:37']]],
  ['Limits are set in SSMFS (2008:21).', [['narrative', '(2008:21)', 'SSMFS 2008:21 [a]']]],
  ['(SSMFS 2008:37, Section 10)', [['parenthesis', '(SSMFS 2008:37, Section 10)', 'SSMFS 2008:37 @section:10']]],
  ['as required in SSMFS 2008:21 (SSM 2008).', [['parenthesis', '(SSM 2008)', 'SSM 2008']]],
  ['(SFS 1984:3; SOU 2010:6; Ds 2007:30)', [['parenthesis', '(SFS 1984:3; SOU 2010:6; Ds 2007:30)', 'SFS 1984:3', 'SOU 2010:6', 'Ds 2007:30']]],
  ['(SS-EN 1936:1999)', [['parenthesis', '(SS-EN 1936:1999)', 'SS-EN 1936:1999']]],
  ['(SSMFS 2008:21 and 2008:37)', [['parenthesis', '(SSMFS 2008:21 and 2008:37)', 'SSMFS 2008:21', 'SSMFS 2008:37']]],
  ['(Smith 2019 and 2020)', [['parenthesis', '(Smith 2019 and 2020)', 'Smith 2019', 'Smith 2020']]],
  ['(SKI Report 2008:12)', [['parenthesis', '(SKI Report 2008:12)', 'SKI Report 2008:12']]],
  ['(Smith 2020:88)', [['parenthesis', '(Smith 2020:88)', 'Smith 2020 @page:88']]],
  // ---- initials after a name, an editor's mark, a dotted section
  ['Vallery C (2001) showed it.', [['narrative', '(2001)', 'Vallery 2001 [a]']]],
  ['(Höglund L O 2005; Johannesson L-E 2014)', [['parenthesis', '(Höglund L O 2005; Johannesson L-E 2014)', 'Höglund 2005', 'Johannesson 2014']]],
  ['Aquilonius (ed) (2010) describes the site.', [['narrative', '(2010)', 'Aquilonius 2010 [a]']]],
  ['(Aquilonius (ed) 2010)', [['parenthesis', '(Aquilonius (ed) 2010)', 'Aquilonius 2010']]],
  ['(SKB, 2008, 2009)', [['parenthesis', '(SKB, 2008, 2009)', 'SKB 2008', 'SKB 2009']]],
  ['(Smith 2020, sec. 2.3.1)', [['parenthesis', '(Smith 2020, sec. 2.3.1)', 'Smith 2020 @section:2.3.1']]],
  // ---- not citations
  ['This happened in 2020.', []],
  ['(which happened in 2020)', []],
  ['(approximately 1999 samples)', []],
  ['(Figure 3, 2020 data)', []],
  ['(Table 2)', []],
  ['(March 2020)', []],
  ['(Tabell 3, 2019)', []],
  ['(p < 0.05)', []],
  ['(see below)', []],
  ['Results and discussion', []],
  ['Andersson J, 2010. A title of a report.', []],
  ['The results (2020) were clear.', []],
  ['Technical Report TR-11-01', []],
  ['SKB TR-11-01', []],
  ['Initial state report\nSKB TR-23-02', []],
  ['The reports:\tSKB TR-23-02\tSKB TR-23-03', []],
];

for (const [text, want] of CASES) check(`found in ${JSON.stringify(text)}`, found(text), want);

/* A year with no author beside other references is flagged; it is not written. */
check('an unattributed year is a problem', P.findInParagraph('(The value in 2020 and Smith 2019)').map((g) => g.problem), ['a year in it has no author']);

/* What SKB's forms carry besides their labels. */
{
  const ref = (text) => P.findInParagraph(text)[0].refs[0];
  check('a report number, with the year it implies', [ref('(SKB TR-11-01)').report, ref('(SKB TR-11-01)').yearKey, ref('(SKB R-99-12)').yearKey], ['TR-11-01', '2011', '1999']);
  check('a designation keeps its year apart', [ref('(SSMFS 2008:37)').designation, ref('(SSMFS 2008:37)').yearKey, ref('(SSMFS 2008:37)').locator], ['SSMFS 2008:37', '2008', '']);
  check('initials are kept for telling authors apart', ref('Vallery C (2001) showed it.').initials, ['C']);
  check('two designations of one year are two decisions', P.refKey(ref('(SSMFS 2008:37)')) === P.refKey(ref('(SSMFS 2008:21)')), false);
  check('... and the author-year reading is not one of them', P.refKey(ref('(SSMFS 2008:37)')) === P.refKey(ref('(SSMFS 2008)')), false);
  check('a report number cited two ways is one decision', P.refKey(ref('(SKB TR-11-01)')), P.refKey(ref('(SKB 2011, TR-11-01)')));
}
check('report numbers in a text', P.reportsIn('SKB TR 99-01, SKBF/KBS TR 83-01, NWMO TR-2010-01 and SKBdoc 1175208'), ['TR-99-01', 'TR-83-01', 'SKBdoc 1175208']);
check('... only SKB\'s when asked', P.reportsIn('Posiva TR-12-01 and SKB R-12-05', true), ['R-12-05']);
check('designations as compared', ['SKI Report 2008:12', 'SS-EN 1936:1999', 'SSI FS 2000:10', 'Ds 2007:30'].map(P.designationKey),
  ['SKI 2008:12', 'SSEN 1936:1999', 'SSIFS 2000:10', 'DS 2007:30']);
check('designations found in a text', P.designationsIn('Svensk författningssamling SFS 2003:778. Also SKI Rapport 2004:5'),
  [['SFS 2003:778', 'FÖRFATTNINGSSAMLINGSFS 2003:778', 'SVENSKFÖRFATTNINGSSAMLINGSFS 2003:778'], ['SKI 2004:5', 'ALSOSKI 2004:5']]);

/* ---- offsets -------------------------------------------------------------- */
{
  const text = 'The value (Smith, 2020; Jones 2019) and As Brown (2018) said.';
  const gs = P.findInParagraph(text);
  check('a group covers exactly its parenthesis', gs.map((g) => text.slice(g.start, g.end)), ['(Smith, 2020; Jones 2019)', '(2018)']);
  check('a narrative group knows where its author starts', text.slice(gs[1].authorStart, gs[1].end), 'Brown (2018)');
}

/* ---- names for comparing ---------------------------------------------------- */
check('fold unfolds accents and drops particles', ['Öhman', 'Bååth', 'van der Berg', 'Straße', 'Łukasiewicz', 'O’Gorman'].map(P.fold),
  ['ohman', 'baath', 'berg', 'strasse', 'lukasiewicz', 'ogorman']);

/* ---- reference list entries ------------------------------------------------ */
const entry = (t) => { const e = P.readEntry(t); return e && [e.num, e.authors, e.yearKey + e.letter]; };
check('SKB style', entry('Andersson J, Ström A, Svemar C, Almén K-E, 2000. What requirements does the repository make?'),
  [null, ['Andersson', 'Ström', 'Svemar', 'Almén'], '2000']);
check('APA style', entry('Smith, J. A., & Jones, B. (2020a). A title. Journal, 1(2), 3–4.'), [null, ['Smith', 'Jones'], '2020a']);
check('particles', entry('van der Berg, K. (2019). Title.'), [null, ['van der Berg'], '2019']);
check('an organisation', entry('SKB, 2010. Long-term safety for the repository.'), [null, ['SKB'], '2010']);
check('an editor', entry('Andersson E (red.), 2010. The limnic ecosystems.'), [null, ['Andersson'], '2010']);
check('numbered', entry('12. Smith J, Jones A. A title. Journal. 2020;12:3-4.'), [12, ['Smith', 'Jones'], '2020']);
check('bracketed number, no year', entry('[3] Smith J. A title without a year.'), [3, [], '']);
check('a sentence is not an entry', entry('The results (Smith, 2020) show a trend.'), null);
check('nor prose that starts with a name', entry('Last paragraph (Brown, 2018).'), null);
check('nor an abbreviated series name', entry('Post-closure safety report, 2023. Post-closure safety for SFR.'), null);
const field = (t, k) => { const e = P.readEntry(t); return e && e[k]; };
check('an entry keeps its SKB report number',
  field('SKB, 2011. Long-term safety for the final repository. SKB TR-11-01, Svensk Kärnbränslehantering AB.', 'report'), 'TR-11-01');
check('... its own, not one its title is about',
  field('Smith J, 2012. Comments on SKB TR-11-01. SKB R-12-05, Svensk Kärnbränslehantering AB.', 'report'), 'R-12-05');
check('... and no other organisation\'s', field('Hellä P, 2012. Title. Posiva TR-12-01, Posiva Oy.', 'report'), '');
check('an entry under a designation', [entry('SSMFS 2008:21. Strålsäkerhetsmyndighetens föreskrifter.'), field('SSMFS 2008:21. Strålsäkerhetsmyndighetens föreskrifter.', 'designation')],
  [[null, ['SSMFS'], '2008'], 'SSMFS 2008:21']);
check('an entry under an SKBdoc number', field('SKBdoc 1175208 ver 5.0. Title of the memo. Svensk Kärnbränslehantering AB.', 'report'), 'SKBdoc 1175208');
check('an entry under a report number', [entry('SKB R-09-20. Site descriptive modelling.'), field('SKB R-09-20. Site descriptive modelling.', 'report')],
  [[null, ['SKB'], '2009'], 'R-09-20']);
const abbrev = (t) => { const e = P.readAbbreviatedEntry(t); return e && [e.abbrev, e.yearKey, e.report]; };
check('an abbreviated name, under its heading',
  abbrev('Data report, 2010. Data report for the safety assessment SR-Site. SKB TR-10-52, Svensk Kärnbränslehantering AB.'), ['Data report', '2010', 'TR-10-52']);
check('... but not an author list', [abbrev('Andolfsson T, 2013. Title.'), abbrev('Höglund L O, 2005. Title.'), abbrev('Johannesson L-E, 2014. Title.')], [null, null, null]);

check('headings', ['References', 'Referenser', '7 References', 'Litteraturförteckning:', 'A.3 Literature', 'These references were checked'].map(P.isListHeading),
  [true, true, true, true, true, false]);

/* ---- a document ------------------------------------------------------------- */
{
  // An SKB report's list: works under abbreviated names first, then the others.
  const texts = [
    'Introduction', 'Erosion was measured (Smith, 2020; Jones 2019).', 'As Brown (2018) showed, and [1].',
    'The Data report gives the rates (Data report, Section 2.1; SKB 2011).',
    'Limits are set in SSMFS 2008:21 and (SSMFS 2008:37).',
    'References', 'Smith J, 2020. Buffer erosion in dilute groundwater. Applied Clay Science 185.',
    'Jones A, 2019. Sulphide transport. Journal of Hydrology 5.', 'References with abbreviated names',
    'Data report, 2019. Data report for the safety assessment. SKB TR-19-05, Svensk Kärnbränslehantering AB.',
    'Other references', 'Brown P, 2018. Groundwater flow at Forsmark.',
    'SKB, 2011. Long-term safety for the final repository. SKB TR-11-01, Svensk Kärnbränslehantering AB.',
    'SSMFS 2008:21. Strålsäkerhetsmyndighetens föreskrifter om säkerhet i kärntekniska anläggningar.',
    'Uncited U, 2001. Never cited anywhere.', 'Appendix A', 'The appendix cites (Smith, 2020) again.',
  ];
  const levels = [0, null, null, null, null, 0, null, null, 1, null, 1, null, null, null, null, 0, null];
  const doc = P.parseDocument(texts.map((text, i) => ({ text, story: 'body', level: levels[i] })));
  const who = (e) => e && (e.authors[0] || e.abbrev);
  check('the list begins at its heading and ends at the next of its level, past its two parts', [doc.list.start, doc.list.end], [5, 15]);
  check('its entries, the abbreviated name among them', doc.list.entries.map(who), ['Smith', 'Jones', 'Data report', 'Brown', 'SKB', 'SSMFS', 'Uncited']);
  check('citations before and after it, none inside', doc.groups.map((g) => [g.para, g.text]),
    [[1, '(Smith, 2020; Jones 2019)'], [2, '(2018)'], [2, '[1]'], [3, '(Data report, Section 2.1; SKB 2011)'], [4, '(SSMFS 2008:37)'], [16, '(Smith, 2020)']]);
  check('an abbreviated name in a parenthesis is a reference, with its locator', doc.groups[3].refs.map((r) => [r.label, r.locatorLabel, r.locator]),
    [['Data report', 'section', '2.1'], ['SKB 2011', '', '']]);
  check('each reference tied to its entry -- a designation only to its own', doc.refs.filter((r) => r.num === null).map((r) => who(r.entry)),
    ['Smith', 'Jones', 'Brown', 'Data report', 'SKB', null, 'Smith']);
  check('entries keep their report numbers', doc.refs.filter((r) => r.entry && r.entry.report).map((r) => r.entry.report), ['TR-19-05', 'TR-11-01']);
  check('the uncited entry; a name or designation in running text counts as cited', P.uncitedEntries(doc).map((e) => e.text), ['Uncited U, 2001. Never cited anywhere.']);
  check('... unless an existing Zotero citation cites it', P.uncitedEntries(doc, [['Uncited', '2001']]), []);
  check('same authors and year, one key', doc.refs[0].key === doc.refs[doc.refs.length - 1].key, true);
  const flat = P.parseDocument(texts.map((text) => ({ text, story: 'body' })));
  check('without outline levels the list ends after its last entry', [flat.list.start, flat.list.end], [5, 15]);
  check('... and reads the same entries', flat.list.entries.map(who), doc.list.entries.map(who));
  const alone = P.parseDocument(['Intro (Data report and Climate report).', 'Rates (as described in the Climate report) and (see Climate report, 2020).',
    'Data report\nSKB TR-19-05', 'References with abbreviated names', 'Data report, 2019. Data for the assessment.',
    'Climate report, 2020. Climate for the assessment.', 'Other references', 'Brown P, 2018. Groundwater flow at Forsmark.']
    .map((text) => ({ text, story: 'body' })));
  check('the heading of abbreviated names may begin the list itself', [alone.list.start, alone.list.entries.map(who)],
    [3, ['Data report', 'Climate report', 'Brown']]);
  check('an abbreviated name is cited alone or after a lead-in, not inside prose, nor as a label in a figure',
    alone.groups.map((g) => describe(g)), [['parenthesis', '(Data report and Climate report)', 'Data report', 'Climate report'], ['parenthesis', '(see Climate report, 2020)', 'Climate report 2020 <see>']]);
  const prose = ['Intro.', ...Array.from({ length: 12 }, (_, k) => `Following Abarca et al. (20${10 + k}), the flow is ${k}.`)];
  check('a run of prose with citations is not a reference list', P.parseDocument(prose.map((text) => ({ text, story: 'body' }))).list, null);
  const notes = P.parseDocument([{ text: 'Body.', story: 'body' }, { text: 'A note (Smith 2020).', story: 'footnote' }]);
  check('footnotes are read', notes.groups.map((g) => [g.story, g.text]), [['footnote', '(Smith 2020)']]);
}

/* ---- the user's list of abbreviated names ------------------------------------ */
{
  const read = P.readNameList([
    'Data report: SKB TR-10-52', 'Main report\tTR-11-01', 'Limits: SSMFS 2008:37', 'Lane book: LANE0014',
    'Group item: http://zotero.org/groups/777/items/OHMAN014', 'The old one: SKB 2010', 'Erosion paper: buffer erosion dilute',
    'Climate report, 2020. Climate for the assessment. Svensk Kärnbränslehantering AB.', '# a note', '', 'no colon',
    'Data report: SKB TR-10-53', '“Fuel report”, 2010: SKB TR-10-46',
  ].join('\n'));
  check('the list: each name with what it refers to',
    read.names.map((n) => [n.name, n.target.kind, n.target.report || n.target.designation || n.target.key || n.target.text]),
    [['Data report', 'report', 'TR-10-52'], ['Main report', 'report', 'TR-11-01'], ['Limits', 'designation', 'SSMFS 2008:37'],
      ['Lane book', 'key', 'LANE0014'], ['Group item', 'key', 'OHMAN014'], ['The old one', 'author', 'SKB 2010'],
      ['Erosion paper', 'words', 'buffer erosion dilute'], ['Climate report', 'words', 'Climate for the assessment 2020'],
      ['Fuel report', 'report', 'TR-10-46']]);
  check('... an item link with its library, an author and year read as a citation, SKB\'s numbers told from anyone\'s',
    [read.names[4].target.library, read.names[5].target.authors, read.names[5].target.yearKey, read.names[0].target.skb, read.names[1].target.skb],
    ['groups/777', ['SKB'], '2010', true, false]);
  check('lines it cannot read, and a name given twice', read.problems, [
    { line: 11, reason: 'there is no colon between the name and what it refers to' },
    { line: 12, reason: '“Data report” is listed twice; the first is used' }]);
  check('the line for an entry under "References with abbreviated names"',
    ['Data report, 2010. Data report for the safety assessment SR-Site. SKB TR-10-52, Svensk Kärnbränslehantering AB.',
      'Climate report, 2020. Climate for the assessment. Svensk Kärnbränslehantering AB.', 'Memo, 2020.'].map((t) => P.nameLine(P.readAbbreviatedEntry(t))),
    ['Data report: SKB TR-10-52', 'Climate report: Climate for the assessment 2020', '']);

  const names = P.readNameList('Data report: SKB TR-10-52\nClimate report: SKB TR-10-49').names;
  const bolded = 'In bold, the Data Report is the name.';
  const at = bolded.indexOf('Data Report');
  const paras = [
    { text: 'The Data report', level: 0 },
    { text: 'As the Data report shows, and the data report does not, rates are low (Data report, Section 2.1).' },
    { text: bolded, bold: [[at, at + 'Data Report'.length]] },
    { text: 'Data report\nSKB TR-10-52' },
    { text: 'Contents: Climate report 7', fixed: [[0, 26]] },
    { text: 'Smith (2020, as in the Data report) agrees; see the Climate report (Section 3).' },
    { text: 'References', level: 0 },
    { text: 'SKB, 2010. Data report for the safety assessment SR-Site. SKB TR-10-52, Svensk Kärnbränslehantering AB.' },
    { text: 'Smith J, 2020. Buffer erosion. Applied Clay Science 185.' },
    { text: 'Uncited U, 2001. Never cited anywhere.' },
  ].map((p) => Object.assign({ story: 'body', level: null }, p));
  const doc = P.parseDocument(paras, { names });
  check('a listed name is a citation in running text -- in bold even with a capital out of place, not in bold only as listed -- and in a parenthesis;'
    + ' not in a heading, alone on its line, in a field\'s result, or inside another citation',
  doc.groups.map((g) => [g.para, ...describe(g)]), [
    [1, 'inline', 'Data report', 'Data report'], [1, 'parenthesis', '(Data report, Section 2.1)', 'Data report @section:2.1'],
    [2, 'inline', 'Data Report', 'Data report'],
    [5, 'narrative', '(2020, as in the Data report)', 'Smith 2020 >as in the Data report< [a]'], [5, 'inline', 'Climate report', 'Climate report']]);
  const named = doc.refs.filter((r) => r.abbrev);
  check('where each name stands, and whether it is in bold', named.map((r) => [paras[doc.groups[r.group].para].text.slice(...r.at), r.bold]),
    [['Data report', false], ['Data report', false], ['Data Report', true], ['Climate report', false]]);
  check('one decision for a name, wherever and however it is cited', [...new Set(named.map((r) => r.key))], ['n|data report', 'n|climate report']);
  check('a name is tied to the entry with its report number', named.map((r) => r.entry && r.entry.authors[0]), ['SKB', 'SKB', 'SKB', null]);
  check('... which is cited, then', P.uncitedEntries(doc).map((e) => e.text), ['Uncited U, 2001. Never cited anywhere.']);
  check('without a reference list, the names are found all the same',
    P.parseDocument(paras.slice(0, 6), { names }).groups.map((g) => g.text), ['Data report', '(Data report, Section 2.1)', 'Data Report', '(2020, as in the Data report)', 'Climate report']);
  check('without the list, a name in running text is not a citation', P.parseDocument(paras).groups.map((g) => g.text), ['(2020, as in the Data report)']);

  // From SKB's PSAR reports: what the name must not be taken for.
  const bold = (text, words) => ({ text, story: 'body', bold: [[text.indexOf(words), text.indexOf(words) + words.length]] });
  const more = P.parseDocument([
    bold('The Activities and input data report is another report.', 'Activities and input data report'),
    bold('As in the Data Report, bold with a capital out of place.', 'Data Report'),
    { text: 'Initial state report for the safety assessment SR-PSU (SKB TR-14-02).', story: 'body' },
    { text: 'As described in the SR-Site Geosphere process report (SKB TR-10-48).', story: 'body' },
    { text: 'As SKB’s Data report shows, not in bold.', story: 'body' },
  ], { names: P.readNameList('Data report: SKB TR-10-52\nInitial state report: SKB TR-23-02\nGeosphere process report: SKB TR-14-05').names });
  check('in bold, the first letter as listed ("input data report" is another report\'s name, "Data Report" this one\'s);'
    + ' not in bold, not at the start of a line, where it begins a title, nor after a qualifier such as "SR-Site"',
  more.groups.map((g) => [g.para, g.kind, g.text]),
  [[1, 'inline', 'Data Report'], [2, 'parenthesis', '(SKB TR-14-02)'], [3, 'parenthesis', '(SKB TR-10-48)'], [4, 'inline', 'Data report']]);
}

console.log(`${CASES.length} paragraphs: ${checks} checks`);
if (failures.length) {
  console.log(`${failures.length} FAILED:`);
  for (const f of failures) console.log(`  ${f}`);
  process.exit(1);
}
console.log('all passed');
