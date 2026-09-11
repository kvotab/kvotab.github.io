/* ==========================================================================
   SKB REFERENCE CHECKER — rules

   The three rule tables — review terminology, citation shape and the
   official SKB writing rules — and the metadata that gives each rule a
   stable id, a readable name and its legacy ids.

   Part of the page script that used to live inline in skbref.html. The
   modules share one global scope, as classic scripts do, and are loaded in
   the order they were written in; skbref-boot.js runs everything.

   The four-space indent is from the <script> block this came out of, and is
   kept deliberately: removing it would also remove four spaces from every
   line inside a multi-line template literal, changing the whitespace of the
   HTML this page generates.
   ========================================================================== */
'use strict';

    /*
      Review-word and expression rules. Rules with enabled: false correspond to lines
      prefixed with # in the source list and remain available for revision.
    */
    const FORBIDDEN_WORD_RULES = [
      {
            "enabled": true,
            "pattern": "\\bBRT\\b",
            "description": "bör vara 1BRT"
      },
      {
            "enabled": true,
            "pattern": "\\b[Ff]lux(?:es)?\\b",
            "description": "Använd release? (om det gäller activity release)"
      },
      {
            "enabled": true,
            "pattern": "\\bSVAFO\\b",
            "custom": "require-ab-prefix",
            "description": "bör vara AB SVAFO"
      },
      {
            "enabled": true,
            "pattern": "\\b[Aa]nnual effective dose\\b",
            "description": "Använd sparsamt"
      },
      {
            "enabled": true,
            "pattern": "\\b[Cc]ommitted dose\\b",
            "description": "?"
      },
      {
            "enabled": true,
            "pattern": "\\b[Ff]ractures?\\b",
            "description": "Använd inte för betong"
      },
      {
            "enabled": true,
            "pattern": "\\b[Ff]racturing\\b",
            "description": "Använd inte för betong"
      },
      {
            "enabled": true,
            "pattern": "\\b[Cc]racks?\\b",
            "description": "Använd inte för berg"
      },
      {
            "enabled": true,
            "pattern": "\\b[Pp]rogen(?:y|ies)\\b",
            "description": "Använd: decay product"
      },
      {
            "enabled": true,
            "pattern": "\\b[Dd]aughter products?\\b",
            "description": "Använd: decay product"
      },
      {
            "enabled": true,
            "pattern": "\\b[Dd]eposit(?:s|ed|ing)?\\b",
            "description": "?"
      },
      {
            "enabled": true,
            "pattern": "\\b[Dd]ose-deliverer\\b",
            "description": "?"
      },
      {
            "enabled": true,
            "pattern": "\\b[Gg]rout(?:s|ed|ing)?\\b",
            "description": "kringgjutning använd inte för igjutning"
      },
      {
            "enabled": true,
            "pattern": "\\b[Ff]ar-field\\b",
            "description": "bör oftast vara geosphere"
      },
      {
            "enabled": true,
            "pattern": "\\b[Mm]ass flux\\b",
            "description": "?"
      },
      {
            "enabled": true,
            "pattern": "\\b[Ee]mbedment\\b",
            "description": "igjutning använd inte för kringgjutning"
      },
      {
            "enabled": true,
            "pattern": "\\b[Pp]lacing\\b",
            "description": "Kan ibland vara location"
      },
      {
            "enabled": true,
            "pattern": "\\b[Pp]lace\\b",
            "description": "Kan ibland vara location"
      },
      {
            "enabled": true,
            "pattern": "\\b[Ll]ow and intermediate level waste\\b",
            "description": "bör vara low- and intermediate-level waste"
      },
      {
            "enabled": true,
            "pattern": "\\b[Pp]eak\\b",
            "description": "bör oftast vara maximum"
      },
      {
            "enabled": true,
            "pattern": "\\b[Nn]ear field\\b",
            "description": "bör vara near-field"
      },
      {
            "enabled": true,
            "pattern": "\\b[Nn]earfield\\b",
            "description": "bör vara near-field"
      },
      {
            "enabled": true,
            "pattern": "\\b[Oo]perational phase\\b",
            "description": "Använd:operational period"
      },
      {
            "enabled": true,
            "pattern": "\\b[Oo]perating period\\b",
            "description": "Använd:operational period"
      },
      {
            "enabled": true,
            "pattern": "\\b[Cc]onservative(?:ly)?\\b",
            "description": "använd cautious eller pessimistic"
      },
      {
            "enabled": true,
            "pattern": "\\b[Nn]uclides?\\b",
            "description": "bör vara radionuclide(s)"
      },
      {
            "enabled": true,
            "pattern": "\\b[Uu]plift(?:ed|ing|s)?\\b",
            "description": "Använd inte om det gäller havsnivån"
      },
      {
            "enabled": true,
            "pattern": "\\b[Rr]ebound(?:s|ing|ed)?\\b",
            "description": "Använd inte om det gäller havsnivån"
      },
      {
            "enabled": true,
            "pattern": "\\b[Ll]and rise\\b",
            "description": "Använd inte om det gäller havsnivån"
      },
      {
            "enabled": true,
            "pattern": "\\b[Rr]etention factors?\\b",
            "description": "?"
      },
      {
            "enabled": true,
            "pattern": "(?<![Tt]he)\\s+PSAR\\b",
            "description": "PSAR som inte föregås av the"
      },
      {
            "enabled": true,
            "pattern": "(?<![Tt]he)\\s+SR-PSU\\b",
            "description": "SR-PSU som inte föregås av the"
      },
      {
            "enabled": true,
            "pattern": "\\b[Ss]horeline development\\b",
            "description": "shoreline displacement/regression?"
      },
      {
            "enabled": true,
            "pattern": "\\b[Ss]horeline evolution\\b",
            "description": "shoreline displacement/regression?"
      },
      {
            "enabled": true,
            "pattern": "\\b[Ss]horelevel\\b",
            "description": "Menar du: shoreline?n"
      },
      {
            "enabled": true,
            "pattern": "\\b[Ss]hore-line\\b",
            "description": "?"
      },
      {
            "enabled": true,
            "pattern": "\\b[Ss]hore-level\\b",
            "description": "relative sea-level?"
      },
      {
            "enabled": true,
            "pattern": "\\b[Ss]orption distribution coefficients?\\b",
            "description": "?"
      },
      {
            "enabled": true,
            "pattern": "\\b[Ll]inear distribution coefficients?\\b",
            "description": "?"
      },
      {
            "enabled": true,
            "pattern": "\\b[Ss]orption partitioning coefficients?\\b",
            "description": "?"
      },
      {
            "enabled": true,
            "pattern": "\\b[Ss]orption reduction coefficients?\\b",
            "description": "?"
      },
      {
            "enabled": true,
            "pattern": "\\b[Tt]he Silo\\b",
            "description": "det ska inte vara stort S här"
      },
      {
            "enabled": true,
            "pattern": "\\b[Cc]onstruction concrete\\b",
            "description": "Använd: structural concrete"
      },
      {
            "enabled": true,
            "pattern": "\\b[Ww]aste containers?\\b",
            "description": "Använd: waste packaging"
      },
      {
            "enabled": true,
            "pattern": "\\b[Rr]epository sections?\\b",
            "description": "Använd: waste vault"
      },
      {
            "enabled": true,
            "pattern": "\\b[Rr]epository vaults?\\b",
            "description": "Använd: waste vault"
      },
      {
            "enabled": true,
            "pattern": "\\b[Pp]ipes?\\b",
            "description": "channels?"
      },
      {
            "enabled": true,
            "pattern": "\\b[Dd]iversionary\\b",
            "description": "'gas evacuation system'?"
      },
      {
            "enabled": false,
            "pattern": "SKB\\s\\(\\s?[12]",
            "description": "old style SKB reference"
      },
      {
            "enabled": true,
            "pattern": "\\bSKB\\s+[12]\\d{3}\\b",
            "description": "old style SKB reference"
      },
      {
            "enabled": true,
            "pattern": "\\d%(?![\\p{L}\\p{N}])",
            "description": "missing space before unit"
      },
      {
            "enabled": true,
            "pattern": "\\d°C(?!\\p{L})",
            "description": "missing space before unit"
      },
      {
            "enabled": false,
            "pattern": "[0-9]m ",
            "description": "missing space before unit"
      },
      {
            "enabled": true,
            "pattern": "\\d(?:meters?|metres?)(?!\\p{L})",
            "description": "missing space before unit"
      },
      {
            "enabled": true,
            "pattern": "\\dmm(?!\\p{L})",
            "description": "missing space before unit"
      },
      {
            "enabled": true,
            "pattern": "\\dyears(?!\\p{L})",
            "description": "missing space before unit"
      },
      {
            "enabled": true,
            "pattern": "\\b\\d{1,3}0000(?:\\d+)?\\b",
            "description": "missing space in large number"
      },
      {
            "enabled": false,
            "pattern": "Crawford et al.",
            "description": "most often only Crawford"
      },
      {
            "enabled": false,
            "pattern": "Mårtensson et al. 2022 ",
            "description": "Eller ska det vara?:2021"
      },
      {
            "enabled": false,
            "pattern": "(?<!s)[iy]ze",
            "description": "American English?"
      },
      {
            "enabled": false,
            "pattern": "\\s{2,}",
            "description": "more than 1 whitespace"
      },
      {
            "enabled": false,
            "pattern": "0 0",
            "description": "non non-breaking half space"
      },
      {
            "enabled": false,
            "pattern": "[0-9],[0-9]",
            "description": "?"
      },
      {
            "enabled": false,
            "pattern": "\\bchapter [0-9]",
            "description": "not capitalized"
      },
      {
            "enabled": false,
            "pattern": "\\bsection [0-9]",
            "description": "not capitalized"
      },
      {
            "enabled": false,
            "pattern": "\\bfigure [0-9]",
            "description": "not capitalized"
      },
      {
            "enabled": false,
            "pattern": "\\btable [0-9]",
            "description": "not capitalized"
      },
      {
            "enabled": true,
            "pattern": "\\b\\d+(?:\\.\\d+)*\\.X\\b",
            "description": "Trasig referens"
      },
      {
            "enabled": true,
            "pattern": "#",
            "description": "Trasig referens"
      },
      {
            "enabled": false,
            "id": "technical-scientific-notation-e-obsolete",
            "pattern": "[0-9][eE]",
            "description": "Disabled: superseded by the precise official scientific-notation rule."
      },
      {
            "enabled": true,
            "pattern": "\\bet\\.\\s*al\\.?\\b",
            "description": "Är det en onödig punkt efter \"et\" ?"
      },
      {
            "enabled": true,
            "pattern": "\\bet al(?!\\.)\\b",
            "description": "Saknas punkt efter \"al\""
      },
      {
            "enabled": true,
            "pattern": "\\bKd\\b",
            "description": "Kolla att det är kursivt K och nedsänkt och rakt d"
      },
      {
            "enabled": false,
            "pattern": "(?<!Figure) [0-9]{1,}-[0-9]{1,}-[0-9]{1,}-[0-9]{1,}",
            "description": "Ska det vara intervall, med tankstreck?"
      },
      {
            "enabled": true,
            "pattern": "\\b[Cc]olors?\\b",
            "description": "American English? BE=colour"
      },
      {
            "enabled": true,
            "pattern": "\\b[Mm]ath\\b",
            "description": "American English? BE=maths"
      },
      {
            "enabled": true,
            "pattern": "\\b[Mm]ail\\b",
            "description": "American English? BE=post"
      },
      {
            "enabled": true,
            "pattern": "\\b[Tt]rapezoids?\\b",
            "description": "American English? BE=trapezium"
      },
      {
            "enabled": true,
            "pattern": "\\b[Dd]efenses?\\b",
            "description": "American English? BE=defence"
      },
      {
            "enabled": true,
            "pattern": "\\b[Aa]luminum\\b",
            "description": "American English? BE=aluminium"
      },
      {
            "enabled": true,
            "pattern": "\\b[Cc]anceled\\b",
            "description": "American English? BE=cancelled"
      },
      {
            "enabled": true,
            "pattern": "\\b[Ff]ulfill(?:s|ed|ing|ment)?\\b",
            "description": "American English? BE=fulfil"
      },
      {
            "enabled": true,
            "pattern": "\\b[Aa]ging\\b",
            "description": "American English? BE=ageing"
      },
      {
            "enabled": true,
            "pattern": "\\b[Cc]enters?\\b",
            "description": "American English? BE=centre"
      },
      {
            "enabled": true,
            "pattern": "\\b[Ss]occer\\b",
            "description": "American English? BE=football"
      },
      {
            "enabled": true,
            "pattern": "\\b[Mm]illimeters?\\b",
            "description": "American English? BE=millimetre"
      },
      {
            "enabled": true,
            "pattern": "\\b[Kk]ilometers?\\b",
            "description": "American English? BE=kilometre"
      },
      {
            "enabled": true,
            "pattern": "\\b[Cc]entimeters?\\b",
            "description": "American English? BE=centimetre"
      },
      {
            "enabled": true,
            "pattern": "\\b[Mm]eter\\b",
            "description": "American English? BE=metre"
      },
      {
            "enabled": true,
            "pattern": "\\b[Cc]haracteriz(?:e|es|ed|ing|ation)\\b",
            "description": "American English? BE=characterise"
      },
      {
            "enabled": true,
            "pattern": "\\b[Cc]ivilizations?\\b",
            "description": "American English? BE=civilisation"
      },
      {
            "enabled": true,
            "pattern": "\\b[Oo]rganiz(?:e|es|ed|ing|ation)\\b",
            "description": "American English? BE=organise"
      },
      {
            "enabled": true,
            "pattern": "\\b[Bb]ehaviors?\\b",
            "description": "American English? BE=behaviour"
      },
      {
            "enabled": true,
            "pattern": "\\b[Rr]umors?\\b",
            "description": "American English? BE=rumour"
      },
      {
            "enabled": true,
            "pattern": "\\b[Dd]onuts?\\b",
            "description": "American English? BE=doughnut"
      },
      {
            "enabled": true,
            "pattern": "\\b[Yy]ogurts?\\b",
            "description": "American English? BE=yoghurt"
      },
      {
            "enabled": true,
            "pattern": "\\b[Gg]rays?\\b",
            "description": "American English? BE=grey (om det inte handlar om absorberad dos)"
      },
      {
            "enabled": true,
            "pattern": "\\b[Ff]orward(?!s)\\b",
            "description": "American English? bör sluta med s på BE"
      },
      {
            "enabled": true,
            "pattern": "\\b[Tt]oward(?!s)\\b",
            "description": "American English? bör sluta med s på BE"
      },
      {
            "enabled": true,
            "pattern": "\\b[Rr]ightward(?!s)\\b",
            "description": "American English? bör sluta med s på BE"
      },
      {
            "enabled": true,
            "pattern": "\\b[Ss]ophisticated\\b",
            "description": "Använd inte om barriers"
      },
      {
            "enabled": true,
            "pattern": "\\b[Aa]dvanced\\b",
            "description": "Använd inte om barriers"
      },
      {
            "enabled": true,
            "pattern": "\\b[Ee]ffective(?:ly|ness)?\\b",
            "description": "Undvik för barriers"
      },
      {
            "enabled": false,
            "pattern": "(left|right) panel",
            "description": "Vissa dubbelfigurer har utgått"
      },
      {
            "enabled": false,
            "pattern": "pane",
            "description": "Vi skriver i regel panel"
      },
      {
            "enabled": true,
            "pattern": "\\b[Ss]ection\\.0(?:\\d|\\b)",
            "description": "Trasig referens"
      },
      {
            "enabled": true,
            "pattern": "\\b(\\p{L}{2,})\\s+\\1\\b",
            "flags": "giu",
            "description": "upprepat ord"
      },
      {
            "enabled": true,
            "pattern": "\\bBiosphere synthesis(?!\\s+report\\b)",
            "description": "BS som inte följs av 'report'"
      },
      {
            "enabled": true,
            "pattern": "\\b[Cc]oncrete grout\\b",
            "description": "skriv bara grout"
      },
      {
            "enabled": false,
            "pattern": "extended SFR",
            "description": "Kan ibland räcka med bara 'SFR'"
      },
      {
            "enabled": false,
            "pattern": "[Ff]uel damage",
            "description": "?"
      },
      {
            "enabled": true,
            "pattern": "\\b[Ff]uel-damage\\b",
            "description": "Bör vara utan bindestreck?"
      },
      {
            "enabled": true,
            "pattern": "\\bSEQ\\b",
            "description": "Trasig referens"
      },
      {
            "enabled": true,
            "pattern": "\\b[Hh]ittar inte\\b",
            "description": "Trasig referens"
      },
      {
            "enabled": true,
            "pattern": "\\b[Ff]loor\\b",
            "description": "Kan ibland vara slab"
      },
      {
            "enabled": false,
            "pattern": "[Ss]lab",
            "description": "Bra jobbat"
      },
      {
            "enabled": false,
            "pattern": "[Rr]oof",
            "description": "Troligen OK, men Johan vill ha ceiling på vissa ställen"
      },
      {
            "enabled": false,
            "pattern": "[Cc]ompared to",
            "description": "Ska ofta vara compared with"
      },
      {
            "enabled": false,
            "pattern": "[Cc]ompared with",
            "description": "Ska ibland (men sällan) vara compared to"
      },
      {
            "enabled": true,
            "pattern": "\\b[Vv]alues in parentheses\\b",
            "description": "Troligen OK (om det inte ska vara brackets)"
      },
      {
            "enabled": true,
            "pattern": "\\b[Vv]alues in brackets\\b",
            "description": "Bör ofta vara parentheses, som är ett specialfall av brackets"
      },
      {
            "enabled": true,
            "pattern": "\\b[Aa]nnual near-field release\\b",
            "description": "Vi skriver oftast 'Annual release from the near-field'"
      },
      {
            "enabled": false,
            "pattern": "[Mm]igration",
            "description": "Lite överanvänt, kan man tycka."
      },
      {
            "enabled": true,
            "pattern": "\\b1-2BMA\\b",
            "description": "Ska vara annat streck"
      },
      {
            "enabled": true,
            "pattern": "\\b1-2BTF\\b",
            "description": "Ska vara annat streck"
      },
      {
            "enabled": true,
            "pattern": "\\b1-5BLA\\b",
            "description": "Ska vara annat streck"
      },
      {
            "enabled": true,
            "pattern": "\\bF-PSAR\\b",
            "description": "Ska oftast vara SR-PSU"
      },
      {
            "enabled": true,
            "pattern": "\\bFPSAR\\b",
            "description": "Kan vara F-PSAR, men oftast SR-PSU"
      },
      {
            "enabled": true,
            "pattern": "\\bMain report\\b",
            "description": "Ska oftast vara: Post-closure safety report"
      },
      {
            "enabled": true,
            "pattern": "\\b[Kk]aisson\\b",
            "description": "Felstavning som slunkit igenom några gånger"
      },
      {
            "enabled": true,
            "pattern": "\\b(?:[Kk]|[Cc])aisoon\\b",
            "description": "Felstavning som slunkit igenom några gånger"
      },
      {
            "enabled": true,
            "pattern": "\\b(?:[Kk]|[Cc])aison\\b",
            "description": "Felstavning som slunkit igenom några gånger"
      },
      {
            "enabled": true,
            "pattern": "\\b[Cc]apasity\\b",
            "description": "Felstavning som slunkit igenom några gånger"
      },
      {
            "enabled": true,
            "pattern": "\\b[Cc]autiuos\\b",
            "description": "Felstavning som slunkit igenom några gånger"
      },
      {
            "enabled": true,
            "pattern": "\\b[Cc]autius\\b",
            "description": "Felstavning som slunkit igenom några gånger"
      },
      {
            "enabled": true,
            "pattern": "\\b[Cc]autios\\b",
            "description": "Felstavning som slunkit igenom några gånger"
      },
      {
            "enabled": true,
            "pattern": "\\b[Ss]qrutinised?\\b",
            "description": "Felstavning som slunkit igenom några gånger"
      },
      {
            "enabled": false,
            "pattern": "Inventory report",
            "description": "Ska förmodligen vara 'SKB R-18-07'"
      },
      {
            "enabled": true,
            "pattern": "\\b[Dd]isposed of\\b",
            "description": "Det kanske räcker med 'disposed' utan 'of'"
      },
      {
            "enabled": false,
            "pattern": "\\bBMA\\b",
            "description": "Menar du verkligen BÅDA BMA"
      },
      {
            "enabled": false,
            "pattern": "\\bBLA\\b",
            "description": "Menar du verkligen ALLA BLA"
      },
      {
            "enabled": false,
            "pattern": "\\bBTF\\b",
            "description": "Menar du verkligen BÅDA BTF"
      },
      {
            "enabled": true,
            "pattern": "\\bFigur\\b",
            "description": "Fel språk? (kan vara krashad korsreferens)"
      },
      {
            "enabled": true,
            "pattern": "\\bTabell\\b",
            "description": "Fel språk? (kan vara krashad korsreferens)"
      },
      {
            "enabled": false,
            "pattern": "Huvudrapporten",
            "description": "?"
      },
      {
            "enabled": true,
            "pattern": "\\b[Pp]ost closure(?: safety)?\\b",
            "description": "saknas '-' ?"
      },
      {
            "enabled": false,
            "pattern": "Tables 7-4 to 7-4",
            "description": "typo i RNT (gör till pattern) ?"
      },
      {
            "enabled": false,
            "pattern": "global warming",
            "description": "så heter inte basfallet längre ?"
      },
      {
            "enabled": true,
            "pattern": "\\b[Rr]eference inventory (?:at|by) 2075\\b",
            "description": "Använd: Reference inventory for"
      },
      {
            "enabled": true,
            "pattern": "\\bSR-PSU\\s+\\(PSAR\\)\\.",
            "description": "Använd: the PSAR"
      },
      {
            "enabled": true,
            "pattern": "\\bModel tools summary report\\b",
            "description": "Bör nog vara: Model tools report"
      },
      {
            "enabled": true,
            "pattern": "\\bÅstrand\\s+et\\s+al\\.\\s*\\(2021\\)",
            "description": "should be 2022"
      },
      {
            "enabled": true,
            "pattern": "\\bMårtensson\\s+et\\s+al\\.\\s+2021\\b",
            "description": "Ska det vara?:2022"
      },
      {
            "enabled": true,
            "pattern": "\\b[Ww]ith regards\\b",
            "description": "Google: 'With regard to is the only spelling of this phrase that you should use.'"
      },
      {
            "enabled": true,
            "pattern": "\\bFacilia\\b",
            "description": "företaget finns ej mer, ska det vara SKB,Kemakta,Kvot AB eller nåt annat?"
      },
      {
            "enabled": false,
            "pattern": "\\bSDM\\b",
            "description": "Överväg att skriva SDM-PSU"
      },
      {
            "enabled": true,
            "pattern": "\\bcalculate case\\b",
            "description": "calculation case?"
      },
      {
            "enabled": true,
            "pattern": "\\b[Dd]ifferences? to\\b",
            "description": "differences from?"
      },
      {
            "enabled": true,
            "pattern": "\\b[Dd]oses for humans\\b",
            "description": "doses to humans?"
      },
      {
            "enabled": true,
            "pattern": "\\brates for non-human\\b",
            "description": "rates to non-human?"
      },
      {
            "enabled": false,
            "pattern": "are covered",
            "description": "are to be covered?"
      },
      {
            "enabled": false,
            "pattern": "are disposed",
            "description": "are to be disposed?"
      },
      {
            "enabled": false,
            "pattern": "are installed",
            "description": "are to be installed ?"
      },
      {
            "enabled": true,
            "pattern": "\\b[Cc]riterions\\b",
            "description": "criteria"
      },
      {
            "enabled": true,
            "pattern": "\\b[Ff]orecasted\\b",
            "description": "forecast?"
      },
      {
            "enabled": true,
            "pattern": "\\brepresented with\\b",
            "description": "represented by? om det handlar om compartments"
      },
      {
            "enabled": true,
            "pattern": "\\bembayments?\\b",
            "description": "bay"
      },
      {
            "enabled": true,
            "pattern": "\\b[Uu]nclosed repository\\b",
            "description": "ska vara: unsealed repository"
      },
      {
            "enabled": true,
            "pattern": "\\b[Ss]ections?\\s+[0-9]+(?![0-9.])\\b",
            "description": "Section där det borde vara Chapter?"
      },
      {
            "enabled": true,
            "pattern": "\\b[Cc]hapters?\\s+[0-9]+\\.[0-9]+\\b",
            "description": "Chapter där det borde vara Section?"
      },
      {
            "enabled": true,
            "pattern": "\\b[Ss]eabed\\b",
            "description": "Använd: sea om submerged är det som avses"
      },
      {
            "enabled": true,
            "pattern": "\\bSFR is submerged\\b",
            "description": "Kan behöva omformuleras"
      },
      {
            "enabled": true,
            "pattern": "\\b[Aa]ssessment time\\b",
            "description": "Använd helst: asessment period (undvik: time period,time frame eller time span )"
      },
      {
            "enabled": true,
            "pattern": "\\bdemonstrating fulfilment\\b",
            "description": "Ändra RNT-rapport beskrivningen? (Är listan med huvudreferenser uppdaterad)"
      },
      {
            "enabled": false,
            "pattern": "Model tools summary report",
            "description": "Model tools report?"
      },
      {
            "enabled": false,
            "pattern": "Assessment activities and input data report",
            "description": "Activities and input data report?"
      },
      {
            "enabled": true,
            "pattern": "\\bFEP-report\\b",
            "description": "FEP report?"
      },
      {
            "enabled": true,
            "pattern": "\\bFHA-report\\b",
            "description": "FHA report?"
      },
      {
            "enabled": true,
            "pattern": "\\bPost-closure safety Report\\b",
            "description": "Det bör vara litet r"
      },
      {
            "enabled": true,
            "pattern": "\\bActivities and input data Report\\b",
            "description": "Det bör vara litet r"
      },
      {
            "enabled": true,
            "pattern": "\\bWaste process Report\\b",
            "description": "Det bör vara litet r"
      },
      {
            "enabled": true,
            "pattern": "\\bBarrier process Report\\b",
            "description": "Det bör vara litet r"
      },
      {
            "enabled": true,
            "pattern": "\\bBiosphere synthesis Report\\b",
            "description": "Det bör vara litet r"
      },
      {
            "enabled": true,
            "pattern": "\\bClimate Report\\b",
            "description": "Det bör vara litet r"
      },
      {
            "enabled": true,
            "pattern": "\\bData Report\\b",
            "description": "Det bör vara litet r"
      },
      {
            "enabled": true,
            "pattern": "\\bFEP Report\\b",
            "description": "Det bör vara litet r"
      },
      {
            "enabled": true,
            "pattern": "\\bFHA Report\\b",
            "description": "Det bör vara litet r"
      },
      {
            "enabled": true,
            "pattern": "\\bGeosphere process Report\\b",
            "description": "Det bör vara litet r"
      },
      {
            "enabled": true,
            "pattern": "\\bInitial state Report\\b",
            "description": "Det bör vara litet r"
      },
      {
            "enabled": true,
            "pattern": "\\bModel tools Report\\b",
            "description": "Det bör vara litet r"
      },
      {
            "enabled": true,
            "pattern": "\\bRadionuclide transport Report\\b",
            "description": "Det bör vara litet r"
      },
      {
            "enabled": true,
            "pattern": "\\b[Ff]low barriers?\\b",
            "description": "Hydraulic barriers?"
      }
];

    /*
      Patterns that indicate likely malformed in-text citations. These rules
      are intentionally separate from normal citation extraction so they can
      report suspicious text without changing cross-reference results.
    */
    const POTENTIAL_INVALID_CITATION_RULES = [
      /* Clearly malformed variants of "Surname et al. (2024)". */
      {
        pattern: String.raw`\b[\p{L}][\p{L}'’\-]{0,24}\s+et\.al\.?\s*\((?:1[89]|20)\d{2}(?:,\s*(?:1[89]|20)\d{2})*\)`,
        description: 'Use “et al.” rather than “et.al.”.'
      },
      {
        pattern: String.raw`\b[\p{L}][\p{L}'’\-]{0,24}\s+et\.\s+al\.?\s*\((?:1[89]|20)\d{2}(?:,\s*(?:1[89]|20)\d{2})*\)`,
        description: 'Remove the period after “et”; write “et al.”.'
      },
      {
        pattern: String.raw`\b[\p{L}][\p{L}'’\-]{0,24}\s+et\s+al(?!\.)\s*\((?:1[89]|20)\d{2}(?:,\s*(?:1[89]|20)\d{2})*\)`,
        description: 'Add a period after “al”; write “et al.”.'
      },

      /* Punctuation that is normally not used in narrative citations. */
      {
        pattern: String.raw`\b[\p{L}][\p{L}'’\-]{0,24},\s*\((?:1[89]|20)\d{2}\)`,
        description: 'Possible stray comma between the author name and the parenthesized year.'
      },
      {
        pattern: String.raw`\b[\p{L}][\p{L}'’\-]{0,24}\s+&\s+[\p{L}][\p{L}'’\-]{0,24}\s*\((?:1[89]|20)\d{2}\)`,
        description: 'In narrative text, use “and” rather than “&” between two authors.'
      },
      {
        pattern: String.raw`\b[\p{L}][\p{L}'’\-]{0,24},\s+and\s+[\p{L}][\p{L}'’\-]{0,24}\s*\((?:1[89]|20)\d{2}\)`,
        description: 'Possible unnecessary comma before “and” in a two-author narrative citation.'
      },

      /* Typographical damage to an SKB report number. The number itself may be
         written either way round — "SKB (TR-14-09)" and "(SKB TR-14-09)" are
         both correct — so only malformed numbers are reported here. */
      {
        pattern: String.raw`\bSKB\s+(?:TR|R|P|IPR|RD|SR|TM|U|F)\s+\d{2,}-\d+\b`,
        description: 'A hyphen appears to be missing between the report series and year, for example “SKB TR-23-01”.'
      },
      {
        pattern: String.raw`\bSKB\s+(?:TR|R|P|IPR|RD|SR|TM|U|F)-\d{2,}\s+-?\s*\d+\b`,
        description: 'The SKB report number contains suspicious whitespace around its second hyphen.'
      },

      /* Kept for possible future use, but disabled because these are valid. */
      {
        enabled: false,
        id: 'citation-citation-place-the-report-number-directly-after-skb-for-example-skb',
        legacyIds: ['citation-u5r7dl'],
        pattern: String.raw`\bSKB\s*\(\s*(?:TR|R|P|IPR|RD|SR|TM|U|F)-\d{2,}-\d+\s*\)`,
        description: 'Disabled: an SKB report may be cited as “SKB (TR-14-09)” or as “(SKB TR-14-09)”; both are correct.'
      },
      {
        enabled: false,
        pattern: String.raw`\b[\p{L}][\p{L}'’\-]{0,24}\s*\((?:1[89]|20)\d{2}\)`,
        description: 'Disabled: a single-author narrative citation such as “Smith (2020)” is valid.'
      },
      {
        enabled: false,
        pattern: String.raw`\b[\p{L}][\p{L}'’\-]{0,24}\s+and\s+[\p{L}][\p{L}'’\-]{0,24}\s*\((?:1[89]|20)\d{2}\)`,
        description: 'Disabled: a two-author narrative citation such as “Smith and Jones (2020)” is valid.'
      },
      {
        enabled: false,
        pattern: String.raw`\(\s*SKB\s+(?:TR|R|P|IPR|RD|SR|TM|U|F)-\d{2,}-\d+\s*\)`,
        description: 'Disabled: a correctly formed SKB report citation may validly occur inside sentence-level parentheses.'
      }
    ];

    const SKB_RULE_SOURCES = Object.freeze({
      references: 'Angivande av referenser i publika rapporter inklusive engelsk guide',
      handbook: 'Skrivhandboken – En guide för skrivregler på SKB',
      technical: 'Fördjupade skrivregler för publika rapporter: storheter, enheter, matematik och kemi samt språk'
    });

    /* High-confidence text checks derived from the three official SKB guides. */
    const OFFICIAL_SKB_TEXT_RULES = [
      { pattern: String.raw`\d(?:\u0020|\t)*(?:%|‰)`, reject: String.raw`\d\u00a0(?:%|‰)`, description: 'Use a non-breaking space between a number and % or ‰.', source: 'technical', needs: 'space-characters' },
      { pattern: String.raw`\d(?:\u0020|\t)*°C`, reject: String.raw`\d\u00a0°C`, description: 'Use a non-breaking space between the number and °C.', source: 'technical', needs: 'space-characters' },
      { pattern: String.raw`\b\d+(?:\.\d+)?[eE][+−-]?\d+\b`, description: 'Do not use E notation in running text; use × 10 with an exponent.', source: 'technical' },
      { pattern: String.raw`\b\d{1,3}(?:,\d{3})+\b`, description: 'Use spaces, not commas, as thousands separators.', source: 'technical' },
      { pattern: String.raw`\b(?:from\s+[-+−]?\d+(?:\.\d+)?|between\s+[-+−]?\d+(?:\.\d+)?)\s*[–-]\s*[-+−]?\d+(?:\.\d+)?\b`, description: 'Do not combine “from” or “between” with a dash range; use “from … to” or “between … and”.', source: 'technical' },
      { pattern: String.raw`\b(?:and/or)\b`, description: 'Avoid “and/or”; rewrite with “or both” or another unambiguous construction.', source: 'technical' },
      { pattern: String.raw`\b(?:E\.g\.|I\.e\.)`, description: 'Do not begin a sentence with e.g. or i.e.; spell out “For example” or rewrite.', source: 'technical' },
      { pattern: String.raw`\be\.g\.,`, description: 'In British English, do not place a comma directly after e.g.', source: 'technical' },
      { pattern: String.raw`\bi\.e\.,`, description: 'In British English, do not place a comma directly after i.e.', source: 'technical' },
      { pattern: String.raw`\be\.g\.[^.!?]{0,80}\betc\.`, description: 'Do not use etc. in a list introduced by e.g.', source: 'technical' },
      { pattern: String.raw`\bi\.e\.[^.!?]{0,80}\betc\.`, description: 'Do not use etc. in a list introduced by i.e.', source: 'technical' },
      { pattern: String.raw`\betc(?!\.)\b`, description: 'The abbreviation etc. must end with a period and should be preceded by a comma.', source: 'technical' },
      { pattern: String.raw`\b(?:wasn't|weren't|isn't|aren't|doesn't|don't|didn't|can't|couldn't|shouldn't|wouldn't|hasn't|haven't|hadn't)\b`, flags: 'giu', description: 'Avoid contracted forms in scientific text.', source: 'technical' },
      { pattern: String.raw`\b(?:SKB|SSM|OKG)('s|´s|’s)\b`, description: 'In Swedish, write the genitive with colon and s, for example SKB:s.', source: 'handbook', language: 'sv' },
      { pattern: String.raw`\b[Ii]dag\b`, description: 'Write “i dag” as two words.', source: 'handbook', language: 'sv' },
      { pattern: String.raw`\b[Ii]stället\b`, description: 'Write “i stället” as two words.', source: 'handbook', language: 'sv' },
      { pattern: String.raw`\b[Ss]kall\b`, description: 'SKB recommends “ska” rather than “skall”.', source: 'handbook', language: 'sv' },
      { pattern: String.raw`\b[Tt]idplan(?:en|er|erna|s)?\b`, description: 'Use “tidsplan” rather than “tidplan”.', source: 'handbook', language: 'sv' },
      { pattern: String.raw`\b[Hh]emsida(?:n|or|orna)?\b`, description: 'Use “webbplats” rather than “hemsida”.', source: 'handbook', language: 'sv' },
      { pattern: String.raw`\b[Mm]ail(?:et|en|ar)?\b`, description: 'Use “mejl” or “e-post” rather than “mail”.', source: 'handbook', language: 'sv' },
      { pattern: String.raw`\b[Uu]tbränt kärnbränsle\b`, description: 'Use “använt kärnbränsle”.', source: 'handbook', language: 'sv' },
      { pattern: String.raw`\b[Ss]kippschakt\b`, description: 'Use “skipschakt”.', source: 'handbook', language: 'sv' },
      { pattern: String.raw`\b[Pp]ressrelease\b`, description: 'Use “pressmeddelande”.', source: 'handbook', language: 'sv' },
      { pattern: String.raw`\b(?:CLAB|ClAB|clab)\b`, description: 'The facility name is written “Clab”.', source: 'handbook' },
      { pattern: String.raw`\b(?:figure|table|chapter|section|appendix)\s+[A-Z]?\d`, flags: 'gu', description: 'A numbered Figure, Table, Chapter, Section or Appendix starts with a capital letter in English.', source: 'technical', language: 'en' },
      { pattern: String.raw`\b(?:Figur|Tabell)\s+\d`, flags: 'gu', description: 'In Swedish running text, write numbered references with lower-case “figur” and “tabell”.', source: 'handbook', language: 'sv' },
      { pattern: String.raw`\b(?:figur|tabell)\s+\d`, flags: 'gu', description: 'In English running text, write numbered references as “Figure” and “Table”.', source: 'handbook', language: 'en' },
      { pattern: String.raw`\b\d+\s*(?:kg|g|mg|µg|m|cm|mm|km|s|min|h|d|Hz|Pa|kPa|MPa|V|mV|A|mA|W|kW|MW|J|kJ|mol|Bq|Gy|Sv)\b`, description: 'Use a non-breaking space between a numerical value and a unit symbol.', source: 'technical', custom: 'unit-space', needs: 'space-characters' },
      { pattern: String.raw`\b\d+\s*[xX]\s*10(?:\^?[-+]?\d+|[⁰¹²³⁴⁵⁶⁷⁸⁹]+)`, description: 'Use the multiplication sign ×, not the letter x, in scientific notation.', source: 'technical' },
      /* ── Appendix 4 of 1469987: rules that are mandatory in public reports ── */
      { pattern: String.raw`(?<![\p{L}\d])\d+(?:\.\d+)*\s+[–—-]\s+\d+(?:\.\d+)*(?![\p{L}\d])`, description: 'Write a range with an en dash and no surrounding spaces, for example 2001–2004 and Sections 4.1–4.3.', source: 'technical' },
      { pattern: String.raw`(?<![\p{L}\d])\d+(?:[.,]\d+)?\s*[xX]\s*(?!10[⁰¹²³⁴⁵⁶⁷⁸⁹^])\d+(?:[.,]\d+)?(?![\p{L}\d])`, description: 'Use the multiplication sign × between numbers, not the letter x.', source: 'technical' },
      { pattern: String.raw`(?<![\p{L}])\d+(?:[.,]\d+)?\s*[∙·]\s*\d+(?:[.,]\d+)?(?![\p{L}\d])`, description: 'Multiply numbers with the multiplication sign ×, not a half-high dot.', source: 'technical' },
      { pattern: String.raw`\b[A-Z][A-Za-z0-9]*\s*[×x*]\s*\d*H2O\b`, description: 'Write water of crystallisation with a half-high dot surrounded by spaces, for example CuSO4 ∙ 5H2O.', source: 'technical' },
      { pattern: String.raw`\b[A-Z][A-Za-z0-9]*[∙·]\d*H2O\b`, description: 'Surround the half-high dot with spaces in water of crystallisation, for example CuSO4 ∙ 5H2O.', source: 'technical' },

      /* ── Appendix 3 of 1469987: characters that are commonly wrong ── */
      { pattern: String.raw`(?:^|\s)(?:<<|>>)(?=\s|\d|\p{L})`, description: 'Use ≪ or ≫, not two angle brackets.', source: 'technical' },
      { pattern: String.raw`\d\s*•\s*\d`, description: 'Use the half-high dot ∙ or the multiplication sign ×, not a bullet •.', source: 'technical' },
      { pattern: String.raw`\b\d+(?:[.,]\d+)?\s*[oO0]C\b`, description: 'Use the degree sign in °C, not the letter o or the digit 0.', source: 'technical' },
      { pattern: String.raw`∅`, description: 'Use ⌀ for a diameter and φ for the Greek letter; ∅ is the empty set.', source: 'technical' },

      /* ── Section 3.1 of 1469987: numbers ── */
      { pattern: String.raw`(?<=[\s(])\.\d`, description: 'Write the integer zero in a decimal number between 0 and 1, for example 0.25.', source: 'technical' },
      { pattern: String.raw`(?<![\p{L}\d])\d+(?:[.,]\d+)?\s*–\s*\d+(?:[.,]\d+)?\s*×\s*10`, description: 'Use “to”, not an en dash, for a range written with powers of ten, and write out both values.', source: 'technical' },
      { pattern: String.raw`(?<![\p{L}\d])[−-]\d+(?:[.,]\d+)?\s*–\s*[+−-]?\d`, description: 'Use “to”, not an en dash, when a value in a range is negative or carries a modifying sign.', source: 'technical' },
      { pattern: String.raw`(?<![\p{L}\d])\d+(?:[.,]\d+)?\s*–\s*\d+(?:[.,]\d+)?\s+(?:million|billion|thousand|miljoner|miljarder)\b`, description: 'Use “to”, not an en dash, when numbers combine digits and words, and write out both values.', source: 'technical' },

      /* ── Sections 2.1–2.2 of 1469987: units ── */
      { pattern: String.raw`\b(?:a few|several|many|some|ett fåtal|några)\s+(?:mm|cm|km|kg|mg|µg|ml|mL|nm|µm|kW|MW|kJ|MJ)\b`, flags: 'giu', description: 'Use the unit name, not the unit symbol, when the unit is not preceded by a number.', source: 'technical' },
      { pattern: String.raw`\b\d+(?:[.,]\d+)?\s*([A-Za-zµΩ°]{1,4})\s*[–-]\s*\d+(?:[.,]\d+)?\s*\1\b`, description: 'Give the unit symbol only at the end of a range, for example 30–50 mA.', source: 'technical' },
      { pattern: String.raw`(?<![\/:\w])[A-Za-zµΩ]{1,6}\/[A-Za-zµΩ]{1,6}\/[A-Za-zµΩ]{1,6}(?![\/\w])`, description: 'No unit expression may contain more than one solidus; use negative exponents or parentheses.', source: 'technical' },
      { pattern: String.raw`\b\d+(?:[.,]\d+)?\s*(?:kgs|kms|cms|mms|mols|secs|hrs|Ls|mLs)\b`, description: 'Unit symbols take no plural ending.', source: 'technical' },

      /* ── Section 5 of 1469987: IUPAC spellings that override British usage ── */
      { pattern: String.raw`\b[Ss]ulph(?:ur|ate|ide|uric|urous|ite)\w*\b`, description: 'IUPAC spelling is used for this element: write sulfur, sulfate, sulfide, sulfuric. Section 5 of the guide overrides the British spelling listed in section 6.1.5.', source: 'technical' },
      { pattern: String.raw`\b[Cc]esium\b`, description: 'IUPAC spelling is used for this element: write caesium.', source: 'technical' },
      { pattern: String.raw`\b[Aa]luminum\b`, description: 'IUPAC spelling is used for this element: write aluminium.', source: 'technical' },
      { pattern: String.raw`\b[Pp]hosphorous\s+(?:acid|content|concentration|release|transport|species|budget)\b`, description: 'The element is phosphorus; phosphorous is the adjective. Check which is intended.', source: 'technical', severity: 'review' },

      /* ── Section 6.1 of 1469987: SKB writes British English ── */
      { pattern: String.raw`\b(?:colors?|colored|coloring|labor|labors|behaviors?|flavors?|odors?|harbors?|honors?|humors?|neighbors?|rumors?|splendor)\b`, flags: 'gu', description: 'American spelling: British English writes -our (colour, labour, behaviour).', source: 'technical', severity: 'review', language: 'en' },
      { pattern: String.raw`\b(?:meters?|liters?|centers?|centered|centering|calibers?|fibers?|maneuvers?|specters?|lusters?|somber|theaters?|saltpeter|meager|ocher)\b`, flags: 'gu', description: 'American spelling: British English writes -re (metre, litre, centre, fibre). Note that words ending in -meter, such as thermometer, keep -er.', source: 'technical', severity: 'review', language: 'en' },
      { pattern: String.raw`\b(?:real|recogn|critic|emphas|util|summar|minim|standard|styl|character|local|organ|normal|optim|visual|final|initial)(?:ize|izes|ized|izing|ization|izations)\b`, flags: 'gu', description: 'American spelling: British English prefers -ise and -isation (realise, minimise, standardisation).', source: 'technical', severity: 'review', language: 'en' },
      { pattern: String.raw`\b(?:analyz|catalyz|hydrolyz|paralyz)(?:e|es|ed|ing|er)?\b`, flags: 'gu', description: 'American spelling: British English writes -yse (analyse, catalyse, hydrolyse).', source: 'technical', severity: 'review', language: 'en' },
      { pattern: String.raw`\b(?:analogs?|catalogs?|dialogs?)\b`, flags: 'gu', description: 'American spelling: British English writes -ogue (analogue, catalogue, dialogue).', source: 'technical', severity: 'review', language: 'en' },
      { pattern: String.raw`\b(?:defense|offense|pretense)s?\b`, flags: 'gu', description: 'American spelling: British English writes -ence (defence, offence, pretence).', source: 'technical', severity: 'review', language: 'en' },
      { pattern: String.raw`\b(?:archeolog|paleontolog|paleo|medieval|encyclopedia)\w*\b`, flags: 'gu', description: 'American spelling: British English keeps ae or oe (archaeology, palaeontology, mediaeval, encyclopaedia).', source: 'technical', severity: 'review', language: 'en' },
      { pattern: String.raw`\b(?:modeling|modeled|labeled|labeling|traveled|traveler|traveling|canceled|canceling|counselor|equaling|signaled|signaling|totaled|fueled|fueling)\b`, flags: 'gu', description: 'American spelling: British English doubles the final l (modelling, labelled, traveller, cancelled).', source: 'technical', severity: 'review', language: 'en' },
      { pattern: String.raw`\b(?:aging|sizable|salable)\b`, flags: 'gu', description: 'American spelling: British English keeps the silent e (ageing, sizeable, saleable).', source: 'technical', severity: 'review', language: 'en' },
      { pattern: String.raw`\b(?:molds?|molded|molding|grays?|grayish|artifacts?|oriented|tires?|storeys?|storys?)\b`, flags: 'gu', description: 'American spelling: British English writes mould, grey, artefact, orientated, tyre, storey. Check which sense is intended.', source: 'technical', severity: 'review', language: 'en' },
      /* ── Appendix 2 of 1215757: the in-text citation errors the guide lists ── */
      { pattern: String.raw`\b((?:1[89]|20)\d{2})[a-z]\s*,\s*\1[a-z]\b`, description: 'Do not repeat the year for works by the same author in the same year; write “(1993a, b)”.', source: 'references' },
      { pattern: String.raw`\([^()]*\((?:1[89]|20)\d{2}[a-z]?\)[^()]*\)`, description: 'Do not put the year in a second pair of parentheses inside a citation; write “(see van der Wal et al. 2001)”.', source: 'references' },
      { pattern: String.raw`\b(?:[Aa]ccording to|[Bb]ased on|[Ee]nligt)\s+\((?=[^()]{0,60}(?:1[89]|20)\d{2})`, description: 'When the author’s name is part of the sentence, only the year belongs in parentheses; write “According to Brydsten (2009)”.', source: 'references' },
      { pattern: String.raw`\b(?:Chapters?|Sections?|Figures?|Tables?|Appendix|Appendices|Kapitel|Avsnitt|Bilaga)\s+\d+(?:[.\-]\d+)*(?:\s*[–-]\s*\d+(?:[.\-]\d+)*)?\s+(?:of|in|i)\s+[A-ZÅÄÖÀ-Þ][^()]{0,40}\((?:1[89]|20)\d{2}`, description: 'Put a precise location after the year inside the parentheses; write “Holmén (2005, Chapter 5)”.', source: 'references' },

      /* ── Appendix 4 of 1469987: a sign used as a prefix, other than + or − ── */
      { pattern: String.raw`(?<=[\s(\p{L}])[<>≤≥≈≠=±]\s?\d`, reject: String.raw`[<>≤≥≈≠=±]\s\d`, flags: 'gu', description: 'Only + and − are written against the number. Every other mathematical sign takes a space, for example “pH < 7” and “≈ 100 m”.', source: 'technical' },

      /* ── Sections 3.1, 4.4 and 6 of 1469987 ── */
      { pattern: String.raw`(?<![\d,.])\d{1,3},\d{1,2}(?![\d,]|-\p{L})`, flags: 'gu', description: 'Use a point as the decimal separator in English text; a comma is the Swedish decimal separator.', source: 'technical', severity: 'review', language: 'en' },
      { pattern: String.raw`\b(?:where|Where|där|Där)\s+[\p{L}][\p{L}\d]{0,3}\s*=\s*[\p{L}]{3,}`, flags: 'gu', description: 'Write “is” rather than an equals sign when explaining a quantity symbol in running text.', source: 'technical' },
      { pattern: String.raw`↔`, description: 'Use ⇄ for a reaction that runs in both directions, not ↔.', source: 'technical', severity: 'review' },
      { pattern: String.raw`\d(?:BC|AD|BP)\b`, description: 'Leave a space between the year and BC, AD or BP.', source: 'technical' },
      { pattern: String.raw`\b\d+(?:[.,]\d+)?\s*u(?:m|s|g|L|mol|F|A|V|W|Sv|Gy|S)\b`, flags: 'gu', description: 'The micro prefix is µ, not the letter u; write µm, µg, µs.', source: 'technical' },
      { pattern: String.raw`[\p{L}\d]\s+/\s+[\p{L}\d]`, flags: 'gu', description: 'A solidus is never surrounded by spaces.', source: 'handbook', severity: 'review' },
      { pattern: String.raw`,\s*e\.g\.(?=\s*$|\s+[A-ZÅÄÖ])`, description: 'Do not end a sentence with e.g.; the examples belong after it.', source: 'technical' },
      { pattern: String.raw`\bcf\.,`, description: 'In British English, do not place a comma directly after cf.', source: 'technical' },
      { pattern: String.raw`\b\d{1,2}\s+\p{L}{3,}–\d{1,2}\s+\p{L}{3,}|\b\d+\s+(?:BC|AD|BP)–\d`, flags: 'gu', description: 'Space the en dash when either side of the range contains a space, for example “29 September – 2 October”.', source: 'technical' },

      /* ── Section 7.4 of 1715629: abbreviations are written without full stops ── */
      { pattern: String.raw`\b(?:t\.ex\.|bl\.a\.|d\.v\.s\.|m\.fl\.|o\.s\.v\.|fr\.o\.m\.|t\.o\.m\.|m\.m\.)`, flags: 'giu', description: 'SKB writes abbreviations without full stops: t ex, bl a, dvs, m fl, osv.', source: 'handbook', language: 'sv' },

      /* ── Section 7.3 of 1715629: typographic quotation marks ── */
      { pattern: String.raw`"`, description: 'Use typographic quotation marks (” ” in Swedish), not the straight ASCII quotation mark.', source: 'handbook', severity: 'review' },

      /* ── Sections 18.1 and 18.2 of 1715629: company names ── */
      { pattern: String.raw`\bSKB\s+AB\b`, description: 'The company designation AB is used only with the full name Svensk Kärnbränslehantering AB; the abbreviation is SKB alone.', source: 'handbook' },
      { pattern: String.raw`\bForsmark\s+Kraftgrupp\b`, description: 'The owner’s name is Forsmarks Kraftgrupp AB.', source: 'handbook' },
      { pattern: String.raw`\bOKG\s+AB\b`, description: 'In legal contexts the owner’s name is OKG Aktiebolag, not OKG AB.', source: 'handbook' },

      /* ── Sections 7.1 and 7.5 of 1715629: Swedish usage ── */
      { pattern: String.raw`(?<!^)\b(?:Miljöbalken|Kärntekniklagen|Strålskyddslagen|Kärnteknikförordningen)\b`, flags: 'gu', description: 'Names of laws are written with a lower-case initial: miljöbalken, kärntekniklagen.', source: 'handbook', severity: 'review', language: 'sv' },
      { pattern: String.raw`\b[Hh]uvudtidsplan(?:en|er|erna|s)?\b`, description: 'Use “huvudtidplan”, which is the dominant form.', source: 'handbook', language: 'sv' },
      { pattern: String.raw`\b[Rr]adioaktiv\s+strålning\b`, description: 'The source is radioactive, not the radiation: write “joniserande strålning” or “strålning från radioaktiva ämnen”.', source: 'handbook', language: 'sv' },
      { pattern: String.raw`\b[Bb]ränsleflask(?:a|an|or|orna)\b`, description: 'Use “transportbehållare för använt kärnbränsle”.', source: 'handbook', language: 'sv' },
      { pattern: String.raw`\b[Uu]ttjänt\s+kärnbränsle\b`, description: 'Use “använt kärnbränsle”.', source: 'handbook', language: 'sv' }
    ];

    const RULE_ID_OVERRIDES = Object.freeze({
      '\\b[Pp]eak\\b': 'terminology-peak',
      '\\b[Mm]ail\\b': 'language-en-mail',
      '\\b\\d+(?:\\.\\d+)*\\.X\\b': 'reference-broken-cross-reference-x',
      '\\b[Ss]ection\\.0(?:\\d|\\b)': 'reference-broken-section-zero',
      '\\b(\\p{L}{2,})\\s+\\1\\b': 'language-repeated-word',
      '\\b\\d+(?:\\.\\d+)?[eE][+−-]?\\d+\\b': 'technical-scientific-notation-e',
      '\\b[Ff]lux(?:es)?\\b': 'terminology-flux',
      '\\b[Gg]rout(?:s|ed|ing)?\\b': 'terminology-grout',
      '\\b[Cc]onservative(?:ly)?\\b': 'language-conservative',
      '\\b[Cc]olors?\\b': 'language-us-color',
      '\\b[Oo]rganiz(?:e|es|ed|ing|ation)\\b': 'language-us-organize',
      '\\b[Bb]ehaviors?\\b': 'language-us-behavior',
      '\\b[Ss]ections?\\s+[0-9]+(?![0-9.])\\b': 'reference-section-vs-chapter',
      '\\b[Cc]hapters?\\s+[0-9]+\\.[0-9]+\\b': 'reference-chapter-vs-section',
      '\\d%(?![\\p{L}\\p{N}])': 'unit-missing-space-percent',
      '\\d°C(?!\\p{L})': 'unit-missing-space-celsius',
      '\\dmm(?!\\p{L})': 'unit-missing-space-millimetre',
      '\\dyears(?!\\p{L})': 'unit-missing-space-years',
      '\\b\\d{1,3}0000(?:\\d+)?\\b': 'number-missing-grouping-space'
    });

    function stableRuleHash(value) {
      let hash = 2166136261;
      for (const character of String(value)) {
        hash ^= character.codePointAt(0);
        hash = Math.imul(hash, 16777619);
      }
      return (hash >>> 0).toString(36);
    }

    function readableRuleSlug(value){return String(value||'').normalize('NFKD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/[åä]/g,'a').replace(/ö/g,'o').replace(/[^a-z0-9]+/g,'-').replace(/^-+|-+$/g,'').slice(0,58).replace(/-+$/g,'');}
    function ruleDisplayName(rule,family){const d=String(rule.label||rule.description||'').trim();if(d&&d!=='?')return d.charAt(0).toUpperCase()+d.slice(1);return `Review ${String(rule.pattern||family).replace(/\\b/g,'').slice(0,65)}`;}
    function createReadableRuleId(rule,family,used){const category=readableRuleSlug(rule.category||family)||family,name=readableRuleSlug(rule.label||rule.description||rule.pattern)||'unnamed-rule';let id=`${family}-${category}-${name}`;if(used.has(id))id+=`-${stableRuleHash(`${rule.pattern}|${rule.description||''}`).slice(0,5)}`;used.add(id);return id;}
    function ensureRuleMetadata(rules,family,defaults={}){const used=new Set();for(const rule of rules){rule.category||=defaults.category||family;rule.severity||=defaults.severity||'review';rule.flags||=defaults.flags||'gu';rule.label||=ruleDisplayName(rule,family);const previous=rule.id||RULE_ID_OVERRIDES[rule.pattern]||`${family}-${stableRuleHash(`${rule.pattern}|${rule.description||''}`)}`;const readable=!/^\w+-[a-z0-9]{5,8}$/.test(previous)&&previous.split('-').length>=3;const canonical=readable?previous:createReadableRuleId(rule,family,used);rule.legacyIds=[...new Set([...(rule.legacyIds||[]),previous].filter(id=>id&&id!==canonical))];rule.id=canonical;used.add(canonical);}return rules;}
