/*
  The remaining reference examples printed in 1215757 — the awkward ones:
  a title as the main entry, two publishers, a volume with its own title, a
  chapter that is also part of a series, an SKBdoc document belonging to
  another organisation, and the designation-in-parentheses forms.
*/
module.exports = [
  {
    section: '4.1 Posiva SKB, two publishers',
    item: {
      id: 'posiva', type: 'report',
      author: [{ literal: 'Posiva SKB' }],
      issued: { 'date-parts': [[2017]] },
      title: 'Safety functions, performance targets and technical design requirements for a KBS-3V repository. Conclusions and recommendations from a joint SKB and Posiva working group',
      number: 'Posiva SKB Report 01',
      publisher: 'Posiva Oy, Svensk Kärnbränslehantering AB',
    },
    expected: 'Posiva SKB, 2017. Safety functions, performance targets and technical design requirements for a KBS-3V repository. Conclusions and recommendations from a joint SKB and Posiva working group. Posiva SKB Report 01, Posiva Oy, Svensk Kärnbränslehantering AB.',
    citation: '(Posiva SKB 2017)',
  },
  {
    section: "4.1 Another organisation's document held in SKBdoc",
    item: {
      id: 'sibeck', type: 'report',
      author: [{ family: 'Sibeck', given: 'L' }],
      issued: { 'date-parts': [[2014]] },
      title: 'Toughness of ferritic nodular irons',
      number: 'Report 20230-C, issue 7',
      'original-publisher': 'Swerea Swecast',
      archive: 'SKBdoc',
      archive_location: '1265058 ver 3.0',
      publisher: 'Svensk Kärnbränslehantering AB',
    },
    expected: 'Sibeck L, 2014. Toughness of ferritic nodular irons. Report 20230-C, issue 7, Swerea Swecast. SKBdoc 1265058 ver 3.0, Svensk Kärnbränslehantering AB.',
    citation: 'Sibeck (2014)', citationMode: 'author-only',
  },
  {
    section: '4.2 Report with a translated authority name and a language note',
    item: {
      id: 'ostergren', type: 'report',
      author: [
        { family: 'Östergren', given: 'I' }, { family: 'Falk', given: 'R' },
        { family: 'Mjönes', given: 'L' }, { family: 'Ek', given: 'B-M' }],
      issued: { 'date-parts': [[2003]] },
      title: 'Mätning av naturlig radioaktivitet i dricksvatten: test av mätmetoder och resultat av en pilotundersökning',
      number: 'SSI Rapport 2003:07',
      publisher: 'Statens strålskyddsinstitut (Swedish Radiation Protection Authority)',
      language: 'sv',
    },
    expected: 'Östergren I, Falk R, Mjönes L, Ek B-M, 2003. Mätning av naturlig radioaktivitet i dricksvatten: test av mätmetoder och resultat av en pilotundersökning. SSI Rapport 2003:07, Statens strålskyddsinstitut (Swedish Radiation Protection Authority). (In Swedish.)',
    citation: 'Östergren et al. (2003)', citationMode: 'author-only',
  },
  {
    section: '4.3 Licentiate thesis with a country',
    item: {
      id: 'skeppstrom', type: 'thesis',
      author: [{ family: 'Skeppström', given: 'K' }],
      issued: { 'date-parts': [[2005]] },
      title: 'Radon in groundwater-influencing factors and prediction methodology for a Swedish environment',
      genre: 'Lic thesis',
      publisher: 'Royal Institute of Technology',
      'publisher-place': 'Sweden',
    },
    expected: 'Skeppström K, 2005. Radon in groundwater-influencing factors and prediction methodology for a Swedish environment. Lic thesis. Royal Institute of Technology, Sweden.',
    citation: '(Skeppström 2005)',
  },
  {
    section: '4.4 Newspaper article with the title as main entry',
    item: {
      id: 'sustainable', type: 'article-newspaper',
      issued: { 'date-parts': [[2002, 7, 1]] },
      title: 'Do we support sustainable development?',
      'container-title': 'Earth Times',
      page: '3-4',
    },
    /* CSL cannot test the last character of a string, so the comma before
       the year survives after a question mark. Recorded in the style's
       KNOWN LIMITATIONS; the author deletes that one comma. */
    knownLimitation: 'Do we support sustainable development?, 2002. Earth Times, 1 July, 3–4.',
    expected: 'Do we support sustainable development? 2002. Earth Times, 1 July, 3–4.',
    citation: '(Do we support sustainable development? 2002)',
  },
  {
    section: '4.5 Conference paper with no editors',
    item: {
      id: 'gratton', type: 'paper-conference',
      author: [
        { family: 'Gratton', given: 'L' }, { family: 'Greenspan', given: 'E' },
        { family: 'Kastenberg', given: 'W E' }, { family: 'Peterson', given: 'P F' },
        { family: 'Stone', given: 'N' }, { family: 'Zimmerman', given: 'J' }],
      issued: { 'date-parts': [[1998]] },
      title: 'Phenomena affecting the dynamics of critical deposits in TUFF',
      'container-title': 'High-level radioactive waste management: proceedings of the 8th international conference, Las Vegas, Nevada, 11–14 May 1998',
      'publisher-place': 'La Grange Park', publisher: 'American Nuclear Society',
      page: '450-452',
    },
    expected: 'Gratton L, Greenspan E, Kastenberg W E, Peterson P F, Stone N, Zimmerman J, 1998. Phenomena affecting the dynamics of critical deposits in TUFF. In High-level radioactive waste management: proceedings of the 8th international conference, Las Vegas, Nevada, 11–14 May 1998. La Grange Park: American Nuclear Society, 450–452.',
    citation: '(Gratton et al. 1998)',
  },
  {
    section: '4.6 Corporate author, NEA',
    item: {
      id: 'nea', type: 'book',
      author: [{ literal: 'NEA' }],
      issued: { 'date-parts': [[1997]] },
      title: 'Lessons learnt from ten performance assessment studies',
      'publisher-place': 'Paris', publisher: 'Nuclear Energy Agency',
    },
    expected: 'NEA, 1997. Lessons learnt from ten performance assessment studies. Paris: Nuclear Energy Agency.',
    citation: '(NEA 1997)',
  },
  {
    section: '4.6 Author unknown, encyclopaedia',
    item: {
      id: 'britannica', type: 'book',
      issued: { 'date-parts': [[1993]] },
      title: 'The new Encyclopædia Britannica',
      edition: '15',
      'publisher-place': 'Chicago, IL', publisher: 'Encyclopædia Britannica',
    },
    expected: 'The new Encyclopædia Britannica, 1993. 15th ed. Chicago, IL: Encyclopædia Britannica.',
    citation: '(The new Encyclopædia Britannica 1993)',
  },
  {
    section: '4.7 Volume that has its own title',
    item: {
      id: 'coulson', type: 'book',
      author: [
        { family: 'Coulson', given: 'J M' }, { family: 'Richardson', given: 'J F' },
        { family: 'Backhurst', given: 'J R' }, { family: 'Harker', given: 'J H' }],
      issued: { 'date-parts': [[1999]] },
      title: 'Chemical engineering',
      volume: '1. Fluid flow, heat transfer and mass transfer',
      edition: '6',
      'publisher-place': 'Oxford', publisher: 'Pergamon',
    },
    expected: 'Coulson J M, Richardson J F, Backhurst J R, Harker J H, 1999. Chemical engineering. Vol 1. Fluid flow, heat transfer and mass transfer. 6th ed. Oxford: Pergamon.',
    citation: '(Coulson et al. 1999)',
  },
  {
    section: '4.8 Chapter in an edited work, with an edition',
    item: {
      id: 'delgiorgio', type: 'chapter',
      author: [{ family: 'del Giorgio', given: 'P A' }, { family: 'Cole', given: 'J J' }],
      editor: [{ family: 'Kirchman', given: 'D L' }],
      issued: { 'date-parts': [[2000]] },
      title: 'Bacterial energetics and growth efficiency',
      'container-title': 'Microbial ecology of the oceans',
      edition: '2',
      'publisher-place': 'New York', publisher: 'Wiley-Liss', page: '289-325',
    },
    expected: 'del Giorgio P A, Cole J J, 2000. Bacterial energetics and growth efficiency. In Kirchman D L (ed). Microbial ecology of the oceans. 2nd ed. New York: Wiley-Liss, 289–325.',
    citation: 'del Giorgio and Cole (2000)', citationMode: 'author-only',
  },
  {
    section: '4.9 Chapter in a series: pages come after the series',
    item: {
      id: 'birks', type: 'chapter',
      author: [{ family: 'Birks', given: 'H J B' }],
      editor: [{ family: 'Maddy', given: 'D' }, { family: 'Brew', given: 'J S' }],
      issued: { 'date-parts': [[1995]] },
      title: 'Quantitative palaeoenvironmental reconstructions',
      'container-title': 'Statistical modelling of quaternary science data',
      'publisher-place': 'Cambridge', publisher: 'Quaternary Research Association',
      'collection-title': 'Technical Guide', 'collection-number': '5',
      page: '161-254',
    },
    expected: 'Birks H J B, 1995. Quantitative palaeoenvironmental reconstructions. In Maddy D, Brew J S (eds). Statistical modelling of quaternary science data. Cambridge: Quaternary Research Association. (Technical Guide 5), 161–254.',
    citation: '(Birks 1995)',
  },
  {
    section: '4.11 Government publication under the issuing body',
    item: {
      /* Statute, as the style's header prescribes for laws, SOU and
         standards; the author goes in the author field and the designation
         in Series/Series Number. */
      id: 'karnavfallsradet', type: 'legislation',
      author: [{ literal: 'Kärnavfallsrådet' }],
      issued: { 'date-parts': [[2010]] },
      title: 'Kunskapslägesrapport på kärnavfallsområdet 2010: utmaningar för slutförvarsprogrammet',
      'publisher-place': 'Stockholm', publisher: 'Kärnavfallsrådet',
      'collection-title': 'Statens offentliga utredningar', 'collection-number': '2010:6',
      language: 'sv',
    },
    expected: 'Kärnavfallsrådet, 2010. Kunskapslägesrapport på kärnavfallsområdet 2010: utmaningar för slutförvarsprogrammet. Stockholm: Kärnavfallsrådet. (Statens offentliga utredningar 2010:6) (In Swedish.)',
    citation: '(Kärnavfallsrådet 2010)',
  },
  {
    section: '4.12 Authority regulation under its designation',
    item: {
      id: 'ssmfs', type: 'legislation',
      number: 'SSMFS 2008:21',
      title: 'Strålsäkerhetsmyndighetens föreskrifter och allmänna råd om säkerhet vid slutförvaring av kärnämne och kärnavfall',
      'publisher-place': 'Stockholm',
      publisher: 'Strålsäkerhetsmyndigheten (Swedish Radiation Safety Authority)',
      language: 'sv',
    },
    expected: 'SSMFS 2008:21. Strålsäkerhetsmyndighetens föreskrifter och allmänna råd om säkerhet vid slutförvaring av kärnämne och kärnavfall. Stockholm: Strålsäkerhetsmyndigheten (Swedish Radiation Safety Authority). (In Swedish.)',
    citation: '(SSMFS 2008:21)',
  },
  {
    section: '4.12 The same regulation under the authority',
    item: {
      id: 'ssm', type: 'legislation',
      author: [{ literal: 'SSM' }],
      issued: { 'date-parts': [[2008]] },
      title: 'Strålsäkerhetsmyndighetens föreskrifter och allmänna råd om säkerhet vid slutförvaring av kärnämne och kärnavfall',
      'publisher-place': 'Stockholm',
      publisher: 'Strålsäkerhetsmyndigheten (Swedish Radiation Safety Authority)',
      'collection-title': 'SSMFS', 'collection-number': '2008:21',
      language: 'sv',
    },
    expected: 'SSM, 2008. Strålsäkerhetsmyndighetens föreskrifter och allmänna råd om säkerhet vid slutförvaring av kärnämne och kärnavfall. Stockholm: Strålsäkerhetsmyndigheten (Swedish Radiation Safety Authority). (SSMFS 2008:21) (In Swedish.)',
    citation: '(SSM 2008)',
  },
  {
    section: '4.13 WWW page with corporate author, UN',
    item: {
      id: 'un', type: 'webpage',
      author: [{ literal: 'UN' }],
      issued: { 'date-parts': [[1972]] },
      title: 'Declaration of the United Nations Conference on the human environment',
      URL: 'http://www.unep.org/Documents.Multilingual/Default.asp?documentid=97&articleid=1503',
      accessed: { 'date-parts': [[2011, 9, 24]] },
    },
    expected: 'UN, 1972. Declaration of the United Nations Conference on the human environment. Available at: http://www.unep.org/Documents.Multilingual/Default.asp?documentid=97&articleid=1503 [24 September 2011].',
    citation: '(UN 1972)',
  },
  {
    section: 'Regression: a Report item must not lose its series designation',
    item: {
      id: 'seriesreport', type: 'report',
      author: [{ literal: 'Boverket' }],
      issued: { 'date-parts': [[2019]] },
      title: 'A report issued in a numbered series',
      number: 'Boverket Report 2019:01',
      publisher: 'Boverket',
      'collection-title': 'BFS', 'collection-number': '2019:1',
    },
    expected: 'Boverket, 2019. A report issued in a numbered series. Boverket Report 2019:01, Boverket. (BFS 2019:1)',
    citation: '(Boverket 2019)',
  },
];
