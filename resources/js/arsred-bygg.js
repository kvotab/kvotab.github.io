/* ==========================================================================
   arsred-bygg.js — bygg en K2-årsredovisning i iXBRL ur bokföringen

   Tar en SIE-fil (eller en Spiris-export som CSV), kopplar BAS-kontona till
   K2-taxonomins element, räknar fram uppställningen och skriver ut en
   iXBRL-handling som steg B1 på samma sida kan läsa in och kontrollera.

   Tre saker gör att detta går att göra utan att gissa:

     - Uppställningen är hämtad, inte påhittad. arsred-taxonomi.js är
       genererad ur de officiella länkbaserna, så radernas ordning, deras
       svenska etiketter och vilka rader som summerar vilka kommer från
       taxonomin själv.

     - Tecknen följer elementens balansriktning. Ett SIE-saldo är
       debetpositivt; taxonomins värde är positivt i elementets egen riktning.
       Ett kreditelement får därför saldot negerat, och ingenting behöver
       specialfall per konto.

     - Kontokopplingen är synlig. Det finns ingen officiell tabell från
       BAS-konto till taxonomielement, så den som ligger i taxonomifilen är
       skriven utifrån BAS-kontoplanens struktur. Varje konto visas med sitt
       förslag och går att ändra, och konton utan koppling räknas inte tyst
       bort — de listas.

   Det som inte kan komma ur bokföringen — verksamhetsbeskrivning, väsentliga
   händelser, resultatdisposition, underskrifter — skrivs i formuläret. Det är
   uppgifter, inte beräkningar.
   ========================================================================== */

const KVOT_ARSRED_BYGG = (() => {
  'use strict';

  const T = KVOT_ARSRED_TAXONOMI;

  /* SIE 4 föreskriver teckenuppsättningen PC8, alltså IBM CP437, som varken
     TextDecoder eller någon annan webbläsar-API känner till. Tabellen är de
     128 höga byten; de låga är ASCII. Filer som ändå är UTF-8 upptäcks först,
     så båda fungerar. */
  const CP437_HIGH =
    'ÇüéâäàåçêëèïîìÄÅÉæÆôöòûùÿÖÜ¢£¥₧ƒáíóúñÑªº¿⌐¬½¼¡«»░▒▓│┤╡╢╖╕╣║╗╝╜╛┐└┴┬├─┼╞╟╚╔╩╦╠═╬╧╨╤╥╙╘╒╓╫╪┘┌█▄▌▐▀αßΓπΣσµτΦΘΩδ∞φε∩≡±≥≤⌠⌡÷≈°∙·√ⁿ²■ ';

  /** Elementets balansriktning, ur taxonomin. */
  const BALANCE = (() => {
    const map = new Map();
    for (const section of [T.CD, T.DR, T.IS, T.BS, T.NOTER, T.SIGN]) {
      for (const row of section) if (row.b) map.set(row.n, row.b);
    }
    return map;
  })();

  /** Svensk etikett för ett element, ur taxonomin. */
  const LABEL = (() => {
    const map = new Map();
    for (const section of [T.CD, T.DR, T.IS, T.BS, T.NOTER, T.SIGN]) {
      for (const row of section) if (!map.has(row.n)) map.set(row.n, row.l);
    }
    return map;
  })();

  function labelOf(name) { return LABEL.get(name) || name; }

  // ── Läsa in bokföringen ───────────────────────────────────────────────────

  /**
   * Avkoda en SIE-fil.
   *
   * @param {Uint8Array} bytes
   * @returns {{text: string, encoding: string}}
   */
  function decodeSie(bytes) {
    try {
      return { text: new TextDecoder('utf-8', { fatal: true }).decode(bytes), encoding: 'UTF-8' };
    } catch (error) {
      ignoreFailure('arsred-bygg.decode', error);
    }
    let text = '';
    for (const byte of bytes) {
      text += byte < 128 ? String.fromCharCode(byte) : CP437_HIGH[byte - 128];
    }
    return { text, encoding: 'CP437 (PC8)' };
  }

  /**
   * Dela en SIE-rad i fält, med citerade fält hållna samman.
   *
   * SIE citerar fält som innehåller mellanslag, och ett citerat fält kan
   * innehålla ett undantaget citattecken. Att dela på mellanslag rakt av
   * bryter sönder varje kontonamn med ett mellanslag i.
   *
   * @param {string} line
   * @returns {string[]}
   */
  function sieFields(line) {
    const fields = [];
    let current = '';
    let quoted = false;
    let escaped = false;
    for (const character of line) {
      if (escaped) { current += character; escaped = false; continue; }
      if (character === '\\') { escaped = true; continue; }
      if (character === '"') { quoted = !quoted; continue; }
      if (!quoted && /\s/.test(character)) {
        if (current) { fields.push(current); current = ''; }
        continue;
      }
      current += character;
    }
    if (current) fields.push(current);
    return fields;
  }

  /** Ett datum på SIE:s form ÅÅÅÅMMDD blir ÅÅÅÅ-MM-DD. */
  function sieDate(value) {
    const digits = String(value || '').replace(/\D/g, '');
    return digits.length === 8
      ? `${digits.slice(0, 4)}-${digits.slice(4, 6)}-${digits.slice(6, 8)}`
      : '';
  }

  /**
   * Läs en SIE-fil till bokföringsmodellen.
   *
   * Bara de poster som behövs för en årsredovisning läses: identitet,
   * räkenskapsår, kontonamn och saldon. Verifikationerna (#VER/#TRANS) hoppas
   * över — årsredovisningen bygger på saldon, och att läsa in tusentals
   * transaktioner skulle bara kosta minne.
   *
   * @param {string} text
   * @returns {Object} bokföringsmodellen
   */
  function parseSie(text) {
    const book = {
      kalla: 'SIE',
      program: '',
      orgnr: '',
      foretagsnamn: '',
      rakenskapsar: null,      // { from, tom } för år 0
      foregaende: null,        // { from, tom } för år -1
      kontonamn: new Map(),    // kontonummer -> namn
      ub: new Map(),           // kontonummer -> utgående balans, år 0
      ubFg: new Map(),         // utgående balans, år -1
      res: new Map(),          // resultatsaldo, år 0
      resFg: new Map(),        // resultatsaldo, år -1
      varningar: [],
    };

    const arsSaldo = (index) => (index === '0' ? 0 : index === '-1' ? -1 : null);

    for (const rawLine of text.split(/\r?\n/)) {
      const line = rawLine.trim();
      if (!line.startsWith('#')) continue;
      const fields = sieFields(line);
      const tag = fields[0];

      switch (tag) {
        case '#PROGRAM':
          book.program = fields.slice(1).join(' ');
          break;
        case '#ORGNR':
          book.orgnr = fields[1] || '';
          break;
        case '#FNAMN':
          book.foretagsnamn = fields[1] || '';
          break;
        case '#RAR': {
          const year = { from: sieDate(fields[2]), tom: sieDate(fields[3]) };
          if (fields[1] === '0') book.rakenskapsar = year;
          else if (fields[1] === '-1') book.foregaende = year;
          break;
        }
        case '#KONTO':
          if (fields[1]) book.kontonamn.set(fields[1], fields[2] || fields[1]);
          break;
        case '#UB': case '#IB': case '#RES': {
          const year = arsSaldo(fields[1]);
          if (year === null) break;
          const konto = fields[2];
          const amount = Number(fields[3]);
          if (!konto || !Number.isFinite(amount)) break;
          if (tag === '#RES') (year === 0 ? book.res : book.resFg).set(konto, amount);
          else if (tag === '#UB') (year === 0 ? book.ub : book.ubFg).set(konto, amount);
          /* #IB 0 är föregående års utgående balans. Den används bara om
             #UB -1 saknas, vilket händer när filen bara omfattar ett år. */
          else if (tag === '#IB' && year === 0 && !book.ubFg.has(konto)) {
            book.ubFg.set(konto, amount);
          }
          break;
        }
        default:
          break;
      }
    }

    if (!book.rakenskapsar) book.varningar.push('Filen saknar #RAR 0 — räkenskapsåret är okänt.');
    if (!book.orgnr) book.varningar.push('Filen saknar #ORGNR.');
    if (!book.ub.size) book.varningar.push('Filen saknar utgående balanser (#UB).');
    if (!book.res.size) book.varningar.push('Filen saknar resultatsaldon (#RES).');
    return book;
  }

  /**
   * Läs en Spiris-export som CSV till samma modell.
   *
   * Exporten är en utskrift snarare än ett utbytesformat: rubrikrader,
   * tomrader och summarader blandas med kontoraderna, och bara kontoraderna
   * har formen "NNNN Namn;belopp;belopp;belopp;belopp". Huvudet bär
   * företagsnamn, organisationsnummer och de två perioderna.
   *
   * Balansräkningen och resultaträkningen exporteras var för sig, så två
   * filer läses in i tur och ordning och slås ihop.
   *
   * @param {string} text
   * @param {Object} [into] - Föregående modell att komplettera
   * @returns {Object}
   */
  function parseSpirisCsv(text, into) {
    const book = into || {
      kalla: 'Spiris CSV', program: '', orgnr: '', foretagsnamn: '',
      rakenskapsar: null, foregaende: null,
      kontonamn: new Map(), ub: new Map(), ubFg: new Map(),
      res: new Map(), resFg: new Map(), varningar: [],
    };
    book.kalla = book.kalla === 'SIE' ? 'SIE + Spiris CSV' : 'Spiris CSV';

    const lines = text.replace(/^﻿/, '').split(/\r?\n/);
    const resultat = /resultatr/i.test(lines[0] || '');

    for (const line of lines) {
      const period = /Avser perioden\s+(\d{4}-\d{2}-\d{2})\s*-\s*(\d{4}-\d{2}-\d{2})/.exec(line);
      if (period && !book.rakenskapsar) book.rakenskapsar = { from: period[1], tom: period[2] };
      const forra = /Period fg år:?\s*(\d{4}-\d{2}-\d{2})\s*-\s*(\d{4}-\d{2}-\d{2})/.exec(line);
      if (forra && !book.foregaende) book.foregaende = { from: forra[1], tom: forra[2] };
      if (!book.orgnr && /^\d{6}-\d{4}\s*$/.test(line)) book.orgnr = line.trim();
      if (!book.foretagsnamn && /^[A-ZÅÄÖ][^;]{2,60}$/.test(line.trim())
          && !/^(TILLGÅNGAR|EGET KAPITAL|SUMMA|BERÄKNAT)/i.test(line.trim())
          && !/r[aä]kning/i.test(line)) {
        book.foretagsnamn = line.trim();
      }

      const cells = line.split(';');
      const konto = /^\s*(\d{4})\s+(.+?)\s*$/.exec(cells[0] || '');
      if (!konto || cells.length < 4) continue;

      const number = (value) => {
        const cleaned = String(value || '').replace(/\s| /g, '').replace(',', '.');
        const parsed = Number(cleaned);
        return Number.isFinite(parsed) ? parsed : null;
      };

      /* Balansräkningen har kolumnerna början, förändring, slut, fg år;
         resultaträkningen perioden, fg år, ackumulerat, ack fg år. */
      const nu = number(resultat ? cells[1] : cells[3]);
      const fg = number(resultat ? cells[2] : cells[4]);
      if (nu === null) continue;

      book.kontonamn.set(konto[1], konto[2]);
      /* Spiris skriver ut resultaträkningen med intäkter positiva och
         kostnader negativa, alltså tvärtemot SIE:s debetpositiva saldon.
         Modellen håller genomgående SIE:s konvention. */
      if (resultat) {
        book.res.set(konto[1], -nu);
        if (fg !== null) book.resFg.set(konto[1], -fg);
      } else {
        book.ub.set(konto[1], nu);
        if (fg !== null) book.ubFg.set(konto[1], fg);
      }
    }

    if (!book.ub.size && !book.res.size) {
      book.varningar.push('Inga kontorader hittades i filen. Är det en Spiris-export av '
        + 'balans- eller resultaträkning?');
    }
    return book;
  }

  // ── Kontokoppling ─────────────────────────────────────────────────────────

  /**
   * Taxonomielementet ett BAS-konto föreslås höra till.
   *
   * @param {string|number} konto
   * @returns {string} elementnamn, eller '' för konton som lämnas utanför
   */
  function defaultElement(konto) {
    const number = Number(konto);
    if (!Number.isFinite(number)) return '';
    for (const [from, to, element] of T.BAS) {
      if (number >= from && number <= to) return element;
    }
    return '';
  }

  /**
   * Alla konton med saldo, med sitt föreslagna element.
   *
   * @param {Object} book
   * @returns {Object[]} { konto, namn, ub, ubFg, res, resFg, element, typ }
   */
  function accounts(book) {
    const numbers = new Set([...book.ub.keys(), ...book.ubFg.keys(),
                             ...book.res.keys(), ...book.resFg.keys()]);
    return [...numbers].sort((a, b) => Number(a) - Number(b)).map(konto => ({
      konto,
      namn: book.kontonamn.get(konto) || '',
      ub: book.ub.get(konto) ?? 0,
      ubFg: book.ubFg.get(konto) ?? 0,
      res: book.res.get(konto) ?? 0,
      resFg: book.resFg.get(konto) ?? 0,
      element: defaultElement(konto),
      typ: book.res.has(konto) || book.resFg.has(konto) ? 'resultat' : 'balans',
    }));
  }

  /**
   * Ett skattekonto med debetsaldo är en fordran, inte en skuld.
   *
   * Konto 2510-2519 ligger bland skulderna i BAS, men står företaget på plus
   * mot Skatteverket är beloppet en tillgång och hör till Övriga fordringar.
   * Balansräkningen skulle annars visa en negativ skuld, vilket inte är en
   * uppställning någon vill lämna in. Spiris gör samma omföring i sin egen
   * utskrift.
   *
   * @param {Object[]} rows - från accounts()
   * @returns {string[]} texter om vad som flyttats
   */
  function reclassify(rows) {
    const notes = [];
    for (const row of rows) {
      if (row.element !== 'Skatteskulder') continue;
      /* SIE-saldon är debetpositiva, så ett positivt saldo på ett skuldkonto
         betyder att företaget står på plus mot Skatteverket. */
      if (row.ub <= 0 && row.ubFg <= 0) continue;
      row.element = 'OvrigaFordringarKortfristiga';
      notes.push(`Konto ${row.konto} ${row.namn} har debetsaldo (${fmt(row.ub)} kr) och `
        + 'redovisas som kortfristig fordran i stället för skatteskuld.');
    }
    return notes;
  }

  // ── Uppställningen ────────────────────────────────────────────────────────

  /**
   * Summera kontona till taxonomins element, med rätt tecken.
   *
   * @param {Object[]} rows - från accounts()
   * @returns {Object} { period, periodFg, balans, balansFg } element -> belopp
   */
  function aggregate(rows) {
    const out = { period: new Map(), periodFg: new Map(), balans: new Map(), balansFg: new Map() };

    const add = (bucket, element, saldo) => {
      if (!element || !saldo) return;
      /* Taxonomins värde är positivt i elementets egen riktning; SIE-saldot är
         debetpositivt. Ett kreditelement får därför saldot negerat. */
      const value = BALANCE.get(element) === 'credit' ? -saldo : saldo;
      bucket.set(element, (bucket.get(element) || 0) + value);
    };

    for (const row of rows) {
      if (row.typ === 'resultat') {
        add(out.period, row.element, row.res);
        add(out.periodFg, row.element, row.resFg);
      } else {
        add(out.balans, row.element, row.ub);
        add(out.balansFg, row.element, row.ubFg);
      }
    }
    return out;
  }

  /**
   * Fyll i summeringsraderna.
   *
   * Går uppställningen nedifrån och upp och låter varje rad som har barn i
   * calculation-länkbasen bli summan av dem, med taxonomins egna vikter. En
   * rad som redan har ett värde från kontona räknas inte om — det är bara
   * rubriksummorna som saknar konton.
   *
   * @param {Map} values - element -> belopp
   * @param {Object[]} layout - T.IS eller T.BS
   * @returns {Map} samma karta, kompletterad
   */
  function computeTotals(values, layout) {
    /* Djupast först, så barnen alltid är klara innan föräldern summeras. */
    const order = layout.slice().sort((a, b) => b.d - a.d);
    for (const row of order) {
      const children = T.CALC[row.n];
      if (!children || !children.length) continue;
      let sum = 0;
      let any = false;
      for (const [child, weight] of children) {
        if (!values.has(child)) continue;
        sum += values.get(child) * weight;
        any = true;
      }
      if (any) values.set(row.n, sum);
    }
    return values;
  }

  /**
   * Hela uppställningen, klar att visa och att tagga.
   *
   * @param {Object[]} rows - från accounts()
   * @returns {Object}
   */
  function statements(rows) {
    const sums = aggregate(rows);
    const is = computeTotals(new Map(sums.period), T.IS);
    const isFg = computeTotals(new Map(sums.periodFg), T.IS);
    const bs = computeTotals(new Map(sums.balans), T.BS);
    const bsFg = computeTotals(new Map(sums.balansFg), T.BS);

    /* Årets resultat i balansräkningen ska vara detsamma som resultaträkningens
       sista rad. Skiljer de sig är något konto felkopplat, och det är värt att
       säga rakt ut snarare än att låta balansräkningen tyst gå ihop ändå. */
    const avvikelser = [];
    const jamfor = (a, b, text) => {
      const left = a ?? 0;
      const right = b ?? 0;
      if (Math.abs(left - right) > 0.5) {
        avvikelser.push(`${text}: ${fmt(left)} mot ${fmt(right)}, skillnad ${fmt(left - right)}.`);
      }
    };
    jamfor(is.get('AretsResultat'), bs.get('AretsResultatEgetKapital'),
           'Årets resultat i resultaträkningen mot balansräkningen');
    jamfor(bs.get('Tillgangar'), bs.get('EgetKapitalSkulder'),
           'Summa tillgångar mot summa eget kapital och skulder');

    return { is, isFg, bs, bsFg, avvikelser };
  }

  function fmt(value) {
    return (Math.round(Number(value) || 0)).toLocaleString('sv-SE');
  }

  // ── Publikt ───────────────────────────────────────────────────────────────

  return {
    decodeSie, parseSie, parseSpirisCsv,
    defaultElement, accounts, reclassify,
    aggregate, computeTotals, statements,
    labelOf, fmt,
    BALANCE, LABEL,
  };
})();

/* Så att samma kod kan köras i Node för test. */
if (typeof module === 'object' && module.exports) module.exports = KVOT_ARSRED_BYGG;

/* ==========================================================================
   arsred-ixbrl.js — skriv ut handlingen

   Lagd i samma fil som uppställningen därför att de två hänger ihop: det som
   räknas fram här ovanför är precis det som taggas här nedanför, med samma
   element och samma tecken.
   ========================================================================== */

Object.assign(KVOT_ARSRED_BYGG, (() => {
  'use strict';

  const T = KVOT_ARSRED_TAXONOMI;
  const B = KVOT_ARSRED_BYGG;

  /** Element -> { p: prefix, b: balansriktning, l: etikett } ur taxonomin. */
  const META = (() => {
    const map = new Map();
    for (const section of [T.CD, T.DR, T.IS, T.BS, T.NOTER, T.SIGN]) {
      for (const row of section) if (!map.has(row.n)) map.set(row.n, row);
    }
    return map;
  })();

  /* Fastställelseintygets element ligger utanför K2-formulären. */
  const BOL = new Map((T.BOL || []).map(([name, kontext, label]) => [name, { kontext, label }]));

  function qname(name) {
    if (BOL.has(name)) return `se-bol-base:${name}`;
    const row = META.get(name);
    return `${row ? row.p : 'se-gen-base'}:${name}`;
  }

  /**
   * Kontexten ett faktum hör hemma i, för ett givet år.
   *
   * Elementets periodType avgör: en balanspost får en balansdagskontext, en
   * resultatpost en periodkontext. Att låta anroparen ange kontexten för hand
   * gick fel på första försöket — balansomslutningen i flerårsöversikten
   * hamnade mot räkenskapsåret i stället för mot balansdagen, vilket sidans
   * egen kontroll fångade som en ensidig balansräkning. Nu kan det inte
   * hända: ingen anropare väljer kontext.
   *
   * @param {string} name
   * @param {number} [year] - 0 för innevarande år, 1 för föregående
   * @returns {string}
   */
  function contextFor(name, year = 0) {
    if (BOL.has(name)) return BOL.get(name).kontext + year;
    const row = META.get(name);
    return (row && row.t === 'instant' ? 'balans' : 'period') + year;
  }

  /**
   * Var i summeringen ett element hamnar: förälder och vikt.
   *
   * Byggs en gång ur calculation-länkbaserna och används för att avgöra vilka
   * rader som ska skrivas ut med minustecken.
   */
  const CALC_PARENT = (() => {
    const map = new Map();
    for (const [parent, children] of Object.entries(T.CALC)) {
      for (const [child, weight] of children) {
        if (!map.has(child)) map.set(child, { parent, weight });
      }
    }
    return map;
  })();

  /**
   * Radens tecken i uppställningen, som produkten av vikterna upp till toppen.
   *
   * En kostnad summeras positivt in i Summa rörelsekostnader, men den summan
   * dras i sin tur av från rörelseresultatet. Produkten blir -1, vilket är
   * precis när raden ska tryckas med minustecken — och det är också varför
   * regeln inte kan vara "kostnadskonton får minus": den gäller lika för
   * Summa rörelsekostnader och för Skatt på årets resultat.
   *
   * @param {string} name
   * @returns {number} 1 eller -1
   */
  function displaySign(name) {
    let weight = 1;
    let current = name;
    const seen = new Set();
    while (CALC_PARENT.has(current) && !seen.has(current)) {
      seen.add(current);
      const step = CALC_PARENT.get(current);
      weight *= step.weight;
      current = step.parent;
    }
    return weight < 0 ? -1 : 1;
  }

  // ── Utskrift ──────────────────────────────────────────────────────────────

  const esc = (value) => String(value ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');

  /*
    Hur ett faktum ska stå på sidan. Inte allt är kronor: soliditeten är ett
    förhållandetal som visas i procent, och medelantalet anställda är ett antal.
    Bolagsverkets exempelfil skriver soliditeten som "33,7" med scale="-2", så
    att det taggade värdet blir 0,337 medan läsaren ser procenttalet — och utan
    tusenavskiljare, eftersom ixt:numcomma inte tar några.

    Reglerna står per element i stället för att skickas in vid varje anrop. Den
    som lägger till en rad i uppställningen ska inte behöva veta det här.
  */
  const NORMAL = Object.freeze({
    unit: 'SEK', decimals: 'INF', scale: 0, format: 'ixt:numspacecomma', decimaler: 0,
  });
  const PROCENT = Object.freeze({
    unit: 'procent', scale: -2, format: 'ixt:numcomma', decimaler: 1,
  });
  const PRESENTATION = Object.freeze({
    Soliditet: PROCENT,
    Rorelsemarginal: PROCENT,
    AvkastningTotaltKapital: PROCENT,
    AvkastningEgetKapital: PROCENT,
    AvkastningSysselsattKapital: PROCENT,
    Kassalikviditet: PROCENT,
    MedelantaletAnstallda: { unit: 'antal-anstallda', format: '', decimaler: 0 },
  });

  function presentation(name) {
    return Object.assign({}, NORMAL, PRESENTATION[name] || {});
  }

  /**
   * Beloppet som text.
   *
   * sv-SE grupperar redan med hårt mellanslag och sätter komma som
   * decimaltecken, alltså precis det ixt:numspacecomma läser tillbaka.
   *
   * @param {number} value
   * @param {number} [decimaler]
   * @returns {string}
   */
  function belopp(value, decimaler = 0) {
    return Math.abs(Number(value) || 0).toLocaleString('sv-SE', {
      minimumFractionDigits: decimaler, maximumFractionDigits: decimaler,
    });
  }

  /**
   * Ett numeriskt faktum, med rätt tecken både i XBRL och på sidan.
   *
   * Värdet är positivt i elementets egen balansriktning, precis som taxonomin
   * vill ha det. Är värdet negativt bär faktumet sign="-" och texten beloppet
   * utan tecken. Minustecknet som syns på sidan står utanför elementet — det
   * är så Bolagsverkets egen exempelfil skriver ut sina kostnader, och det gör
   * att ixt:numspacecomma aldrig behöver läsa ett tecken den inte tar.
   *
   * @param {string} name - elementets lokala namn
   * @param {string} context
   * @param {number} value
   * @param {Object} [opts] - unit, decimals
   * @returns {string} HTML
   */
  function fact(name, year, value, opts = {}) {
    const rules = Object.assign(presentation(name), opts);
    const context = contextFor(name, year);
    const negative = Number(value) < 0;
    /* Förändringarna i eget kapital saknar balansriktning i taxonomin: de är
       rörelser vars riktning ligger i elementets namn, och Bolagsverkets
       exempelfil taggar en utdelning som ett positivt tal med minustecknet i
       radetiketten. visaTecken låter raden bära minus på sidan utan att
       faktumets värde vänds — summeringen skulle annars gå fel hos mottagaren
       medan den såg rätt ut hos läsaren. */
    const shown = (Number(value) || 0)
      * (opts.visaTecken !== undefined ? opts.visaTecken : displaySign(name));
    const lead = shown < 0 ? '-' : '';
    return lead + `<ix:nonFraction contextRef="${context}" name="${qname(name)}" `
      + `unitRef="${rules.unit}" decimals="${rules.decimals}" scale="${rules.scale}"`
      + (rules.format ? ` format="${rules.format}"` : '')
      + (negative ? ' sign="-"' : '')
      + `>${belopp(value, rules.decimaler)}</ix:nonFraction>`;
  }

  /** Ett textfaktum. */
  function textFact(name, year, value, opts = {}) {
    if (value === undefined || value === null || value === '') return '';
    const context = contextFor(name, year);
    const escaped = esc(value).replace(/\n/g, '<br/>');
    return `<ix:nonNumeric contextRef="${context}" name="${qname(name)}"`
      + (opts.escape ? ' escape="true"' : '') + `>${escaped}</ix:nonNumeric>`;
  }

  /** Ett faktum vars värde är en medlem i en lista. */
  function listFact(name, year, member) {
    return `<ix:nonNumeric contextRef="${contextFor(name, year)}" name="${qname(name)}">`
      + `se-mem-base:${member}</ix:nonNumeric>`;
  }

  /* De rader en svensk årsredovisning brukar sätta i versaler: balansräkningens
     två sidor och deras slutsummor. */
  const VERSALER = new Set([
    'TillgangarAbstract', 'Tillgangar', 'EgetKapitalSkulderAbstract', 'EgetKapitalSkulder',
  ]);

  /**
   * En uppställning som tabell, med Not-kolumn.
   *
   * Rader utan värden hoppas över, och en rubrik vars hela underträd är tomt
   * följer med ut — en balansräkning för ett litet bolag skulle annars bestå
   * mest av tomma rubriker för poster företaget inte har.
   *
   * @param {Object[]} layout - T.IS eller T.BS
   * @param {Map} values
   * @param {Map} valuesFg
   * @param {Map} noter - element -> notnummer
   * @returns {string} HTML
   */
  function statementTable(layout, values, valuesFg, noter) {
    const keep = new Set();
    for (let i = 0; i < layout.length; i++) {
      const row = layout[i];
      if (row.a) continue;
      if (!values.has(row.n) && !valuesFg.has(row.n)) continue;
      keep.add(i);
      let depth = row.d;
      for (let j = i - 1; j >= 0 && depth > 0; j--) {
        if (layout[j].d < depth) { keep.add(j); depth = layout[j].d; }
      }
    }

    const rows = [];
    for (let i = 0; i < layout.length; i++) {
      if (!keep.has(i)) continue;
      const row = layout[i];
      /* Uppställningens toppnivå heter samma sak som rubriken alldeles ovanför
         tabellen. En gång räcker. */
      if (row.a && row.d === 0) continue;
      const indent = '&#160;'.repeat(Math.max(0, row.d - 1) * 3);
      const label = VERSALER.has(row.n) ? row.l.toUpperCase() : row.l;
      const klass = VERSALER.has(row.n) ? ' versal' : '';

      if (row.a) {
        rows.push(`<tr><th colspan="4" class="rubrik lvl${row.d}${klass}">`
          + `${indent}${esc(label)}</th></tr>`);
        continue;
      }
      const nu = values.get(row.n);
      const fg = valuesFg.get(row.n);
      const not = noter && noter.get(row.n);
      rows.push(`<tr class="lvl${row.d}${klass}">`
        + `<td class="post">${indent}${esc(label)}</td>`
        + `<td class="not">${not || ''}</td>`
        + `<td class="belopp">${nu === undefined ? '' : fact(row.n, 0, nu)}</td>`
        + `<td class="belopp">${fg === undefined ? '' : fact(row.n, 1, fg)}</td>`
        + '</tr>');
    }
    return rows.join('\n');
  }

  /* Handlingens egen stilmall. Den bäddas in i filen — en årsredovisning som
     hämtar sitt utseende utifrån ser olika ut beroende på var den öppnas, och
     Bolagsverkets kontroll släpper inte igenom externa resurser. */
  const STIL = `
      body { font-family: "Times New Roman", Times, serif; margin: 0 auto; max-width: 46em;
             padding: 2em; line-height: 1.45; }
      h2 { font-size: 118%; margin: 1.8em 0 .5em; }
      h3 { font-size: 104%; margin: 1.4em 0 .3em; }
      p { margin: 0 0 .7em; }
      .titelsida { text-align: center; margin: 3em 0 3.5em; }
      .titelsida .titel { font-size: 200%; margin: 0 0 .2em; }
      .titelsida .for { margin: 0 0 .2em; }
      .titelsida .namn { font-size: 150%; margin: 0 0 .1em; }
      .titelsida .orgnr { margin: 0 0 2em; }
      .titelsida .rubrik-ar { margin: 0 0 .1em; }
      .titelsida .ar { margin: 0; }
      .rubrik-in { font-weight: bold; margin-right: .5em; }
      table { width: 100%; border-collapse: collapse; margin: .5em 0 1.2em; }
      td, th { padding: .16em .4em; text-align: left; vertical-align: bottom; font-weight: normal; }
      th.rubrik { font-weight: bold; padding-top: .7em; }
      td.belopp, th.belopp { text-align: right; white-space: nowrap; }
      td.not, th.not { text-align: center; width: 2.5em; }
      thead th { border-bottom: 1px solid #000; }
      tr.versal td, tr.versal th, th.versal { font-weight: bold; }
      tr.summa td { border-top: 1px solid #000; }
      .underskrift { margin: 2.2em 0 0; }
      .underskrift .namn { margin: 0; border-top: 1px solid #000; padding-top: .2em; width: 18em; }
      .underskrift .roll { margin: 0; font-style: italic; }
  `;

  // ── Hela handlingen ───────────────────────────────────────────────────────

  const AVGIVANDE = Object.freeze({
    styrelsen: 'FinansiellRapportStyrelsenAvgerArsredovisningMember',
    vd: 'FinansiellRapportStyrelsenVerkstallandeDirektorenAvgerArsredovisningMember',
    likvidator: 'FinansiellRapportLikvidatornAvgerArsredovisningMember',
  });

  /**
   * Noternas numrering.
   *
   * Noterna numreras i den ordning de står, och resultat- och balansräkningen
   * får en Not-kolumn som pekar tillbaka. Numret hör alltså till uppställningen
   * och inte till taxonomin, som inte har någon åsikt om räkneordning.
   *
   * @param {Object} m
   * @returns {{nummer: Map, lista: Object[]}}
   */
  function noter(m) {
    const lista = [];
    lista.push({ id: 'principer', rubrik: 'Redovisningsprinciper' });
    if (m.medelantalAnstallda !== undefined && m.medelantalAnstallda !== '') {
      lista.push({ id: 'anstallda', rubrik: 'Medelantalet anställda', post: 'Personalkostnader' });
    }
    const nummer = new Map();
    lista.forEach((not, index) => {
      not.nr = index + 1;
      if (not.post) nummer.set(not.post, not.nr);
    });
    return { nummer, lista };
  }

  /**
   * Skriv hela årsredovisningen som en iXBRL-handling.
   *
   * Uppställningen följer den form en svensk K2-årsredovisning brukar ha:
   * titelsidans block, en inledande mening om vem som avger den och i vilken
   * valuta, förvaltningsberättelse med flerårsöversikt i tusental, förändring
   * av eget kapital som matris, resultatdisposition med sin egen vedertagna
   * lydelse, räkningarna med en Not-kolumn, och noterna numrerade.
   *
   * @param {Object} m - modellen: bokföringens siffror plus det som skrivits in
   * @returns {string} XHTML
   */
  function buildIxbrl(m) {
    const ar = m.rakenskapsar;
    const fg = m.foregaende;
    const orgnr = /^\d{6}-\d{4}$/.test(m.orgnr || '') ? m.orgnr
      : String(m.orgnr || '').replace(/\D/g, '').replace(/^(\d{6})(\d{4})$/, '$1-$2');

    const context = (id, period) => `      <xbrli:context id="${id}">
        <xbrli:entity>
          <xbrli:identifier scheme="http://www.bolagsverket.se">${esc(orgnr)}</xbrli:identifier>
        </xbrli:entity>
        <xbrli:period>${period}</xbrli:period>
      </xbrli:context>`;

    /* Ett år i taget: varje år behöver både en period och en balansdag,
       eftersom flerårsöversikten blandar resultatmått med balansomslutning. */
    const ar1 = [ar, fg, ...(m.tidigareAr || [])].filter(Boolean);
    const contexts = [];
    ar1.forEach((period, index) => {
      contexts.push(context('period' + index,
        `<xbrli:startDate>${period.from}</xbrli:startDate>`
        + `<xbrli:endDate>${period.tom}</xbrli:endDate>`));
      contexts.push(context('balans' + index, `<xbrli:instant>${period.tom}</xbrli:instant>`));
    });

    const hidden = [
      listFact('SprakHandlingUpprattadList', 0, 'SprakSvenskaMember'),
      listFact('LandForetagetsSateList', 0, 'LandSverigeMember'),
      listFact('RedovisningsvalutaHandlingList', 0, 'ValutaSvenskaKronorMember'),
      listFact('BeloppsformatList', 0, 'BeloppsformatNormalformMember'),
      listFact('FinansiellRapportList', 0, AVGIVANDE[m.avgivande] || AVGIVANDE.styrelsen),
      textFact('RakenskapsarForstaDag', 0, ar.from),
      textFact('RakenskapsarSistaDag', 0, ar.tom),
    ].map(f => '        ' + f).join('\n');

    const { nummer, lista } = noter(m);
    const avgivare = m.avgivande === 'likvidator' ? 'Likvidatorn'
      : m.avgivande === 'vd' ? 'Styrelsen och verkställande direktören' : 'Styrelsen';

    const underskrifter = (m.underskrifter || []).filter(p => p.efternamn).map(person => `
        <div class="underskrift">
          <p class="namn">${textFact('UnderskriftHandlingTilltalsnamn', 0, person.tilltalsnamn)} ${textFact('UnderskriftHandlingEfternamn', 0, person.efternamn)}</p>
          <p class="roll">${textFact('UnderskriftHandlingRoll', 0, person.roll)}</p>
        </div>`).join('');

    const fi = m.faststallelseintyg;
    const intyg = !fi || !fi.datumArsstamma ? '' : `
    <h2>Fastställelseintyg</h2>
    <p>${textFact('FaststallelseResultatBalansrakning', 0,
        fi.intygText || 'Jag intygar att resultaträkningen och balansräkningen har fastställts '
        + 'på årsstämma ' + fi.datumArsstamma + '.')}</p>
    <p>Årsstämman hölls ${textFact('Arsstamma', 0, fi.datumArsstamma)}.</p>
    <p>${textFact('ArsstammaResultatDispositionGodkannaStyrelsensForslag', 0,
        fi.dispositionBeslut
        || 'Årsstämman beslöt att godkänna styrelsens förslag till vinstdisposition.')}</p>
    <p>${textFact('IntygandeOriginalInnehall', 0,
        fi.intygandeOriginal
        || 'Jag intygar att innehållet i dessa elektroniska handlingar överensstämmer med '
        + 'originalen och att originalen undertecknats av samtliga personer som enligt lag '
        + 'ska underteckna dessa.')}</p>
    <div class="underskrift">
      <p class="namn">${textFact('UnderskriftFaststallelseintygForetradareTilltalsnamn', 0, fi.tilltalsnamn)} ${textFact('UnderskriftFaststallelseintygForetradareEfternamn', 0, fi.efternamn)}</p>
      <p class="roll">${textFact('UnderskriftFaststallelseintygForetradareForetradarroll', 0,
          fi.roll)}</p>
      <p>Datum ${textFact('UnderskriftFastallelseintygDatum', 0, fi.datum || fi.datumArsstamma)}</p>
    </div>`;

    return `<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="${T.NS.xhtml}"
${Object.entries(T.NS).filter(([k]) => k !== 'xhtml')
  .map(([k, v]) => `      xmlns:${k}="${v}"`).join('\n')}>
  <head>
    <title>${esc(orgnr)} ${esc(m.foretagsnamn)} - Årsredovisning</title>
    <meta name="programvara" content="kvot ab arsredovisning.html"/>
    <meta name="programversion" content="${esc(m.programversion || '1')}"/>
    <style type="text/css">${STIL}</style>
  </head>
  <body>
    <ix:header>
      <ix:hidden>
${hidden}
      </ix:hidden>
      <ix:references>
${T.ENTRY.map(href => `        <link:schemaRef xlink:type="simple" xlink:href="${href}"/>`).join('\n')}
      </ix:references>
      <ix:resources>
${contexts.join('\n')}
        <xbrli:unit id="SEK"><xbrli:measure>iso4217:SEK</xbrli:measure></xbrli:unit>
        <xbrli:unit id="procent"><xbrli:measure>xbrli:pure</xbrli:measure></xbrli:unit>
        <xbrli:unit id="antal-anstallda">
          <xbrli:measure>se-k2-type:AntalAnstallda</xbrli:measure>
        </xbrli:unit>
      </ix:resources>
    </ix:header>

    <div class="titelsida">
      <p class="titel">Årsredovisning</p>
      <p class="for">för</p>
      <p class="namn">${textFact('ForetagetsNamn', 0, m.foretagsnamn)}</p>
      <p class="orgnr">${textFact('Organisationsnummer', 0, orgnr)}</p>
      <p class="rubrik-ar">Räkenskapsåret</p>
      <p class="ar">${esc(ar.from)} – ${esc(ar.tom)}</p>
    </div>

    <p>${esc(avgivare)} för ${esc(m.foretagsnamn)} avger följande årsredovisning för
       räkenskapsåret ${esc(ar.from)} – ${esc(ar.tom)}.</p>
    <p>Årsredovisningen är upprättad i svenska kronor, SEK. Om inte annat särskilt anges,
       redovisas alla belopp i hela kronor (kr). Uppgifter inom parentes avser föregående år.</p>

    <h2>Förvaltningsberättelse</h2>
    <p><span class="rubrik-in">Allmänt om verksamheten</span>
       ${textFact('AllmantVerksamheten', 0, m.verksamhet)}</p>
${m.sate ? `    <p>Företaget har sitt säte i ${textFact('ForetagetsSate', 0, m.sate)}.</p>` : ''}
${m.vasentligaHandelser ? `    <p><span class="rubrik-in">Väsentliga händelser under räkenskapsåret</span>
       ${textFact('VasentligaHandelserRakenskapsaret', 0, m.vasentligaHandelser)}</p>` : ''}

${flerarsoversikt(m, ar1)}
${egetKapital(m)}
${resultatdisposition(m)}

    <p>Företagets resultat och ställning i övrigt framgår av efterföljande resultat- och
       balansräkning med noter.</p>

    <h2>Resultaträkning</h2>
    <table>
      <thead><tr><th></th><th class="not">Not</th>
        <th class="belopp">${esc(ar.from)}<br/>– ${esc(ar.tom)}</th>
        <th class="belopp">${fg ? esc(fg.from) + '<br/>– ' + esc(fg.tom) : ''}</th></tr></thead>
      <tbody>
${statementTable(T.IS, m.is, m.isFg, nummer)}
      </tbody>
    </table>

    <h2>Balansräkning</h2>
    <table>
      <thead><tr><th></th><th class="not">Not</th>
        <th class="belopp">${esc(ar.tom)}</th>
        <th class="belopp">${fg ? esc(fg.tom) : ''}</th></tr></thead>
      <tbody>
${statementTable(T.BS, m.bs, m.bsFg, nummer)}
      </tbody>
    </table>

    <h2>Noter</h2>
${lista.map(not => not.id === 'principer' ? `
    <h3>Not ${not.nr} ${esc(not.rubrik)}</h3>
    <p><span class="rubrik-in">Allmänna upplysningar</span>
       ${textFact('RedovisningsVarderingsprinciper', 0, m.redovisningsprinciper)}</p>
${m.nyckeltalsdefinitioner ? `    <p><span class="rubrik-in">Nyckeltalsdefinitioner</span>
       ${textFact('Nyckeltalsdefinitioner', 0, m.nyckeltalsdefinitioner)}</p>` : ''}` : `
    <h3>Not ${not.nr} ${esc(not.rubrik)}</h3>
    <table>
      <thead><tr><th></th>
        <th class="belopp">${esc(ar.from)}<br/>– ${esc(ar.tom)}</th>
        <th class="belopp">${fg ? esc(fg.from) + '<br/>– ' + esc(fg.tom) : ''}</th></tr></thead>
      <tbody><tr><td>Medelantalet anställda</td>
        <td class="belopp">${fact('MedelantaletAnstallda', 0, m.medelantalAnstallda)}</td>
        <td class="belopp">${fg && m.medelantalAnstalldaFg !== undefined
          && m.medelantalAnstalldaFg !== ''
          ? fact('MedelantaletAnstallda', 1, m.medelantalAnstalldaFg) : ''}</td></tr>
      </tbody>
    </table>`).join('')}

    <h2>Underskrifter</h2>
${m.klartDatum ? `    <p>Årsredovisningens innehåll blev klart den ${esc(m.klartDatum)}.</p>` : ''}
    <p>${esc(m.ort)} den ${textFact('UndertecknandeArsredovisningDatum', 0, m.datum)}</p>
${underskrifter}
${intyg}
  </body>
</html>
`;
  }

  /**
   * Flerårsöversikten, i tusental kronor.
   *
   * Tusentalen är en presentation, inte en avrundning av faktumet: texten är
   * talet i tkr och scale="3" säger att det taggade värdet är tusen gånger
   * större, medan decimals="-3" talar om att noggrannheten slutar där. Så gör
   * Bolagsverkets egen exempelfil, och så slipper översikten stå i kronor
   * bredvid en rubrik som säger Tkr.
   */
  function flerarsoversikt(m, ar1) {
    const rader = m.flerarsoversikt || [];
    if (!rader.length) return '';
    const tkr = { scale: 3, decimals: '-3', decimaler: 0 };
    const rad = (name, label, opts) => rader.some(y => y.varden[name] !== undefined)
      ? `        <tr><td>${esc(label)}</td>`
        + rader.map(y => `<td class="belopp">${y.varden[name] === undefined ? ''
            : fact(name, y.ar, opts === tkr ? y.varden[name] / 1000 : y.varden[name], opts)}</td>`)
          .join('') + '</tr>'
      : '';
    return `    <h3>Flerårsöversikt (Tkr)</h3>
    <table>
      <thead><tr><th></th>${rader.map(y =>
        `<th class="belopp">${esc(y.rubrik)}</th>`).join('')}</tr></thead>
      <tbody>
${[rad('Nettoomsattning', 'Nettoomsättning', tkr),
   rad('ResultatEfterFinansiellaPoster', 'Resultat efter finansiella poster', tkr),
   rad('Soliditet', 'Soliditet (%)', undefined)].filter(Boolean).join('\n')}
      </tbody>
    </table>
${m.kommentarFlerarsoversikt ? `    <p>${textFact('KommentarFlerarsoversikt', 0,
      m.kommentarFlerarsoversikt)}</p>` : ''}`;
  }

  /**
   * Förändring av eget kapital, som matris.
   *
   * Tar en färdigräknad uppställning snarare än att räkna själv: vad som rört
   * sig över eget kapital under året står i böckerna, och den som läser dem
   * är gränssnittet. Här återstår att sätta rätt element på rätt cell.
   *
   * Ingående och utgående balans bär kolumnens eget element och en balansdag.
   * Raderna däremellan bär förändringselementet för just den rörelsen och
   * årets period.
   */
  function egetKapital(m) {
    const k = m.egetKapital;
    if (!k || !k.rader || !k.rader.length) return '';
    const kolumner = k.kolumner || [];

    const cell = (rad, kolumn) => {
      const spec = rad.celler[kolumn];
      if (!spec || spec.v === undefined || spec.v === null) return '<td class="belopp"></td>';
      const name = rad.suffix ? forandringsElement(kolumn, rad.suffix) : kolumn;
      return `<td class="belopp">${fact(name, rad.year, spec.v,
        spec.minus ? { visaTecken: -1 } : {})}</td>`;
    };

    return `    <h3>Förändring av eget kapital</h3>
    <table>
      <thead><tr><th></th>${kolumner.map(kolumn =>
        `<th class="belopp">${esc(KOLUMNRUBRIK[kolumn] || kolumn)}</th>`).join('')}</tr></thead>
      <tbody>
${k.rader.map(rad => `        <tr${rad.summa ? ' class="summa"' : ''}>`
  + `<td>${esc(rad.label)}</td>`
  + kolumner.map(kolumn => cell(rad, kolumn)).join('') + '</tr>').join('\n')}
      </tbody>
    </table>
${m.kommentarEgetKapital ? `    <p>${textFact('ForandringEgetKapitalKommentar', 0,
      m.kommentarEgetKapital)}</p>` : ''}`;
  }

  const KOLUMNRUBRIK = Object.freeze({
    Aktiekapital: 'Aktie-kapital',
    Reservfond: 'Reservfond',
    Overkursfond: 'Fri överkursfond',
    BalanseratResultat: 'Balanserat resultat',
    AretsResultatEgetKapital: 'Årets resultat',
    ForandringEgetKapitalTotalt: 'Totalt',
  });

  /* Förändringselementen heter ForandringEgetKapital<kolumn><rörelse>, med
     kolumnnamnet förkortat på taxonomins eget vis. */
  const KOLUMNDEL = Object.freeze({
    Aktiekapital: 'Aktiekapital',
    Reservfond: 'Reservfond',
    Overkursfond: 'Overkursfond',
    BalanseratResultat: 'BalanseratResultat',
    AretsResultatEgetKapital: 'AretsResultat',
    ForandringEgetKapitalTotalt: 'Totalt',
  });

  function forandringsElement(kolumn, suffix) {
    return `ForandringEgetKapital${KOLUMNDEL[kolumn] || kolumn}${suffix}`;
  }

  /**
   * Resultatdispositionen, med den lydelse en svensk årsredovisning brukar ha.
   */
  function resultatdisposition(m) {
    const d = m.resultatdisposition || {};
    const rad = (name, label, value) => value === undefined || value === null ? ''
      : `        <tr><td>${esc(label)}</td>`
        + `<td class="belopp">${fact(name, 0, value)}</td></tr>`;
    const summarad = (name, value) => `        <tr class="summa"><td></td>`
      + `<td class="belopp">${fact(name, 0, value)}</td></tr>`;
    const perAktie = d.antalAktier && d.utdelning
      ? ` (${belopp(d.utdelning / d.antalAktier, 0)} kronor per aktie)` : '';

    return `    <h3>Resultatdisposition</h3>
    <p>${esc(m.avgivande === 'likvidator' ? 'Likvidatorn' : 'Styrelsen')} föreslår att till
       förfogande stående vinstmedel:</p>
    <table>
      <tbody>
${[rad('BalanseratResultat', 'balanserat resultat', d.balanserat),
   rad('AretsResultatEgetKapital', 'årets resultat', d.aretsResultat),
   summarad('FrittEgetKapital', d.summa)].filter(Boolean).join('\n')}
      </tbody>
    </table>
    <table>
      <tbody>
${[rad('ForslagDispositionUtdelning',
       `disponeras så att till aktieägare utdelas${perAktie}`, d.utdelning),
   rad('ForslagDispositionBalanserasINyRakning', 'i ny räkning överföres',
       d.balanserasINyRakning),
   summarad('ForslagDisposition', d.summa)].filter(Boolean).join('\n')}
      </tbody>
    </table>
${m.yttrandeVinstutdelning ? `    <p>${textFact('StyrelsensYttrandeVinstutdelning', 0,
      m.yttrandeVinstutdelning)}</p>` : ''}`;
  }

  return { buildIxbrl, displaySign, qname, META };
})());
