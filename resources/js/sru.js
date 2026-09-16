/* ==========================================================================
   sru.js — bygg SRU-filerna till Skatteverkets filöverföring

   Två filer ska lämnas, och båda måste stämma:

     INFO.SRU        vem som skickar, och vilken datafil som följer med
     BLANKETTER.SRU  ett blankettblock per blankett, med fältkod och värde

   Posternas ordning är föreskriven, teckenuppsättningen är ISO 8859-1, och
   organisationsnumret skrivs med sekelsiffra — 16 för juridiska personer, så
   att 559162-0306 blir 165591620306. Saknas något av det avvisas hela filen,
   och felet syns först i e-tjänsten.

   Tecknen är den andra fällan. En bokföring är debetpositiv; blanketten är
   det inte. Nettoomsättningen står som ett kreditsaldo i SIE-filen och som
   ett positivt belopp på blanketten, medan en kostnad står positivt i båda —
   raden på blanketten har redan ett minustecken tryckt framför sig. Vilket
   som gäller står i Skatteverkets egen fältnamnstabell, i kolumnen för
   förtryckt tecken, och det är den som får bestämma här.

   Några rader hör ihop två och två: årets resultat är antingen en vinst på
   3.26 eller en förlust på 3.27, aldrig båda. BAS markerar paret med + och –
   framför kontointervallet, och då avgör nettot i kreditriktning vilken av
   raderna som ska lämnas.
   ========================================================================== */

const KVOT_SRU = (() => {
  'use strict';

  const D = KVOT_SRU_DATA;

  /*
    Beskattningsperioden bestäms av när räkenskapsåret slutar, inte av vilket
    år det slutar. Skatteförfarandelagen delar in kalenderåret i fyra perioder
    efter räkenskapsårets sista dag, och tabellen står i varje utgåva av
    Skatteverkets tekniska beskrivning:

      P1   1 januari – 30 april
      P2   1 maj – 30 juni
      P3   1 juli – 31 augusti
      P4   1 september – 31 december

    Att gissa "årets siffra plus P4" gav 2026P4 för ett bokslut per den 30
    juni 2026, vilket är perioden för bokslut i september till december. Den
    var inte öppen, och Skatteverkets testtjänst svarade att blankettypen var
    ogiltig — ett besked som inte säger vad som är fel med den.
  */
  const PERIODER = Object.freeze([
    { p: 'P1', fran: '01-01', till: '04-30', text: '1 januari – 30 april' },
    { p: 'P2', fran: '05-01', till: '06-30', text: '1 maj – 30 juni' },
    { p: 'P3', fran: '07-01', till: '08-31', text: '1 juli – 31 augusti' },
    { p: 'P4', fran: '09-01', till: '12-31', text: '1 september – 31 december' },
  ]);

  /**
   * Beskattningsperioden för ett räkenskapsår.
   *
   * @param {string} sistaDagen - ÅÅÅÅ-MM-DD
   * @returns {string} till exempel 2026P2, eller '' om datumet inte går att läsa
   */
  function periodFor(sistaDagen) {
    const m = /^(\d{4})-(\d{2}-\d{2})$/.exec(String(sistaDagen || '').trim());
    if (!m) return '';
    const del = PERIODER.find(x => m[2] >= x.fran && m[2] <= x.till);
    return del ? m[1] + del.p : '';
  }

  /**
   * När en period öppnar för inlämning.
   *
   * Datumen står i utgåvans egen tabell: perioderna P1 till P3 öppnar samma
   * vår, medan P4 öppnar strax efter årsskiftet. Mönstret är extrapolerat
   * från den publicerade tabellen och är en vägledning, inte ett löfte —
   * Skatteverket är den som avgör när en period faktiskt är öppen.
   *
   * @param {string} period - till exempel 2026P2
   * @returns {{test: string, produktion: string}|null}
   */
  function oppning(period) {
    const m = /^(\d{4})(P[1-4])$/.exec(String(period || ''));
    if (!m) return null;
    const ar = Number(m[1]);
    if (m[2] === 'P4') return { test: `${ar}-12-15`, produktion: `${ar + 1}-01-07` };
    return { test: `${ar}-03-10`, produktion: `${ar}-04-24` };
  }

  /** Perioderna att välja bland för ett givet räkenskapsårsslut. */
  function perioder(sistaDagen) {
    const egen = periodFor(sistaDagen);
    const ar = new Date().getFullYear();
    const alla = [];
    for (const y of [ar + 1, ar, ar - 1, ar - 2]) {
      for (const del of PERIODER) alla.push(y + del.p);
    }
    /* Den period räkenskapsåret faktiskt hör till först, sedan de övriga i
       fallande ordning, så att rätt val är det som redan står. */
    const ut = egen ? [egen] : [];
    for (const p of alla) if (p !== egen) ut.push(p);
    return ut;
  }

  /** Blanketterna i en deklaration, i den ordning de ska lämnas. */
  function deklaration(id) {
    return D.DEKLARATIONER.find(d => d.id === id) || null;
  }

  function blankett(namn) { return D.BLANKETTER[namn] || null; }

  /** Vad blanketten heter, vad den innehåller och vem som lämnar den. */
  function beskrivning(namn) {
    return (D.BESKRIVNING && D.BESKRIVNING[namn]) || null;
  }

  /** Fältkodens rad i blankettens fältnamnstabell. */
  function faltkod(blankettNamn, kod) {
    const b = blankett(blankettNamn);
    return b ? b.falt.find(f => f.kod === String(kod)) || null : null;
  }

  // ── Kontona till fältkoder ────────────────────────────────────────────────

  /*
    Resultatkontot är vänt åt andra hållet än alla andra resultatkonton. Vid
    vinst *debiteras* 8999 med årets resultat, för att nolla resultaträkningen
    mot 2099 som krediteras. Ett positivt saldo på 899x är alltså en vinst,
    medan ett positivt saldo på ett vanligt intäktskonto vore en minuspost.

    Det gör skillnad, eftersom BAS markerar raderna 3.26 vinst och 3.27
    förlust som ett par och låter nettot avgöra vilken som lämnas. Utan det
    här undantaget blev varje vinst en förlust — vilket var precis vad som
    hände på första försöket, och som inte syntes på något annat sätt än att
    fel fältkod stod i filen.
  */
  const RESULTATKONTO = Object.freeze({ fran: 8990, till: 8999 });

  /**
   * Beloppet i den riktning BAS menar när tabellen säger "om netto +".
   *
   * Kreditpositivt för allt utom resultatkontot: en intäkt, en skuld och ett
   * eget kapital är positiva där.
   *
   * @param {number} konto
   * @param {number} saldo - debetpositivt, som i SIE-filen
   * @returns {number}
   */
  function netto(konto, saldo) {
    return konto >= RESULTATKONTO.fran && konto <= RESULTATKONTO.till ? saldo : -saldo;
  }

  /**
   * Åt vilket håll ett konto räknas för en viss fältkod.
   *
   * Konton i klass 1 är tillgångar och står debetpositivt både i bokföringen
   * och på blanketten. Klass 2 är eget kapital och skulder, som står
   * kreditpositivt på blanketten. För resultatkonton avgör det förtryckta
   * tecknet: en rad med + är en intäktsrad och vänder saldot, en rad med −
   * är en kostnadsrad och behåller det, eftersom minustecknet redan står på
   * blanketten.
   *
   * @param {number} konto
   * @param {Object|null} falt - raden ur fältnamnstabellen
   * @returns {number} 1 eller -1
   */
  function riktning(konto, falt) {
    if (konto < 2000) return 1;
    if (konto < 3000) return -1;
    return falt && falt.tecken === '-' ? 1 : -1;
  }

  /**
   * Vilka fältkoder ett konto hör till.
   *
   * Flertalet konton hör till en enda rad, men de som ingår i ett par hör
   * till båda: konto 8999 är både "årets resultat, vinst" och "årets
   * resultat, förlust", och vilken av dem som lämnas avgörs först när
   * beloppet är känt. Att lämna bara den sista träffen gjorde varje vinst
   * till en förlust.
   *
   * @param {string|number} konto
   * @param {Object[]} tabell - BAS-kopplingen för deklarationen
   * @returns {Object[]} { kod, villkor }
   */
  function kopplingarFor(konto, tabell) {
    const nummer = Number(konto);
    if (!Number.isFinite(nummer)) return [];
    const traffar = [];
    for (const [fran, till, kod, vikt, villkor] of tabell) {
      if (nummer < fran || nummer > till) continue;
      /* En post utan fältkod är ett undantag: kontot ska räknas bort ur det
         intervall som står närmast före. */
      if (!kod) { traffar.pop(); continue; }
      traffar.push({ kod, villkor: villkor || '' });
    }
    return traffar;
  }

  /**
   * Summera kontona till fältkoder.
   *
   * @param {Object[]} rader - konton från KVOT_ARSRED_BYGG.accounts()
   * @param {string} deklarationId
   * @returns {{varden: Map, okopplade: Object[]}}
   */
  function faltvarden(rader, deklarationId) {
    const d = deklaration(deklarationId);
    if (!d) return { varden: new Map(), okopplade: [] };
    const tabell = D.BAS[d.bas] || [];
    const schema = d.rakenskapsschema;

    /*
      Summorna hålls per fältkod *och* villkor, inte bara per fältkod. En rad
      kan bestå av både en villkorad och en ovillkorad del — återföring av
      periodiseringsfond är "8810 (Om netto +), 8819" — och då ska den
      ovillkorade delen alltid med medan den villkorade prövas för sig.

      summa är beloppet som ska stå på blanketten, räknat åt radens håll.
      nettosumma är samma konton i den riktning BAS menar med "om netto +":
      kreditpositivt, utom för resultatkontot enligt undantaget ovan.
    */
    const summa = new Map();
    const nettosumma = new Map();
    const okopplade = [];

    for (const rad of rader) {
      const saldo = rad.typ === 'resultat' ? rad.res : rad.ub;
      if (!saldo) continue;
      const kopplingar = kopplingarFor(rad.konto, tabell);
      if (!kopplingar.length) { okopplade.push(rad); continue; }
      for (const koppling of kopplingar) {
        const nyckel = `${koppling.kod}|${koppling.villkor}`;
        const falt = faltkod(schema, koppling.kod);
        summa.set(nyckel, (summa.get(nyckel) || 0)
          + saldo * riktning(Number(rad.konto), falt));
        nettosumma.set(nyckel, (nettosumma.get(nyckel) || 0) + netto(Number(rad.konto), saldo));
      }
    }

    const varden = new Map();
    const lagg = (kod, belopp) => {
      if (!Math.round(belopp)) return;
      varden.set(kod, Math.round((varden.get(kod) || 0) + belopp));
    };
    for (const [nyckel, belopp] of summa) {
      const [kod, villkor] = nyckel.split('|');
      const n = nettosumma.get(nyckel) || 0;
      if (!villkor) lagg(kod, belopp);
      else if (villkor === '+' && n > 0) lagg(kod, n);
      else if (villkor === '-' && n < 0) lagg(kod, -n);
    }
    /* En rad som summerat till noll hör inte hemma i filen. */
    for (const [kod, v] of [...varden]) if (!v) varden.delete(kod);
    return { varden, okopplade };
  }

  // ── Skattemässiga justeringar ─────────────────────────────────────────────

  /*
    BAS kopplingstabell säger ingenting om de skattemässiga justeringarna, och
    det är riktigt: de flesta raderna är bedömningar, inte summor. Vilka
    kostnader som inte får dras av går inte att läsa ur ett kontosaldo.

    Tre saker är ändå mekaniska, och dem ska ingen behöva räkna för hand.
  */

  /* Rader som bara flyttas från räkenskapsschemat till justeringssidan.
     Blanketten säger det själv: 3.26 "flyttas till p. 4.1". */
  const OVERFORING = Object.freeze({
    INK2: [
      { fran: '7450', till: '7650', text: 'Årets resultat, vinst' },
      { fran: '7550', till: '7750', text: 'Årets resultat, förlust' },
      { fran: '7528', till: '7651', text: 'Skatt på årets resultat' },
    ],
    /* Ett handelsbolag beskattas hos delägarna, så det finns ingen bokförd
       skatt att återföra. */
    INK4: [
      { fran: '7450', till: '7650', text: 'Årets resultat, vinst' },
      { fran: '7550', till: '7750', text: 'Årets resultat, förlust' },
    ],
  });

  /*
    Huvudblanketten hämtar två tal från justeringssidan och inget annat.
    Blanketten skriver ut vart de ska: 4.15 "flyttas till p. 1.1 på sid. 1"
    och 4.16 till p. 1.2. Resten av sidan — riskskatt, underlag för särskild
    löneskatt, de utländska försäkringarna — är egna beräkningar som inte går
    att läsa ur vare sig bokföringen eller de andra blanketterna.

    Bara INK2 har en huvudblankett bland de blankettblock som lämnas med fil.
    INK3 och INK4 lämnar sina förstasidor på annat sätt, och NE:s överskott
    går till INK1, som inte hör till den här inlämningen.
  */
  const HUVUDBLANKETT = Object.freeze({
    INK2: {
      blankett: 'INK2',
      fran: 'INK2S',
      poster: [
        { fran: '7670', till: '7104', text: 'Överskott av näringsverksamhet' },
        { fran: '7770', till: '7114', text: 'Underskott av näringsverksamhet' },
      ],
    },
  });

  /*
    Räkenskapsårets början och slut har egna fältkoder, och samma två koder på
    nästan varje blankett i utgåvan. De är därför inget att fråga om en gång
    per blankett — men de är heller inget att lämna in ensamma: ett block som
    bara bär sitt räkenskapsår har inget att säga och ska inte med i filen.
  */
  const DATUMKODER = Object.freeze(['7011', '7012']);

  /*
    Sista raden på justeringssidan är summan av alla rader ovanför, med det
    tecken blanketten trycker framför var och en. Fält utan förtryckt tecken —
    datum, och upplysningarna längst ned — står utanför summan, vilket är
    precis vad en asterisk i fältnamnstabellen betyder.

    Paret är kontrollerat blankett för blankett; NE räknar på samma sätt fast
    dess räkenskapsschema står på samma sida.
  */
  const SUMMERING = Object.freeze({
    INK2S: { overskott: '7670', underskott: '7770' },
    INK3S: { overskott: '8695', underskott: '8795' },
    INK4S: { overskott: '7670', underskott: '7770' },
    NE: { overskott: '7630', underskott: '7730' },
  });

  /**
   * Summera en justeringssida till dess överskott eller underskott.
   *
   * @param {string} namn - blankettens namn
   * @param {Map} varden - fältkod -> värde
   * @returns {{kod: string, belopp: number, summa: number}|null}
   */
  function summera(namn, varden) {
    const par = SUMMERING[namn];
    const def = blankett(namn);
    if (!par || !def) return null;
    let summa = 0;
    for (const falt of def.falt) {
      if (falt.kod === par.overskott || falt.kod === par.underskott) continue;
      if (falt.tecken !== '+' && falt.tecken !== '-') continue;
      const varde = Number(String(varden.get(falt.kod) ?? '').replace(/\s/g, ''));
      if (!Number.isFinite(varde)) continue;
      summa += falt.tecken === '-' ? -varde : varde;
    }
    return summa >= 0
      ? { kod: par.overskott, belopp: Math.round(summa), summa }
      : { kod: par.underskott, belopp: Math.round(-summa), summa };
  }

  /* Pensionskostnaderna som ingår i personalkostnaderna. Kontogruppen är
     pensionskostnader i BAS, men kopplingen står inte i någon tabell — den
     är en läsning av kontoplanen och märks därför som härledd, inte som
     hämtad. */
  const PENSIONSKONTON = Object.freeze({ fran: 7400, till: 7499 });

  /**
   * Summa pensionskostnader ur bokföringen, till upplysningsraden.
   *
   * @param {Object[]} rader - konton
   * @returns {number}
   */
  function pensionskostnader(rader) {
    let summa = 0;
    for (const rad of rader) {
      const konto = Number(rad.konto);
      if (konto < PENSIONSKONTON.fran || konto > PENSIONSKONTON.till) continue;
      summa += rad.res || 0;
    }
    return Math.round(summa);
  }

  // ── Filerna ───────────────────────────────────────────────────────────────

  /**
   * Organisations- eller personnummer på Skatteverkets form.
   *
   * Tolv siffror med sekelsiffra först: 16 för juridiska personer, 19 eller
   * 20 för fysiska. Utan den inledande siffran avvisas filen.
   *
   * @param {string} value
   * @returns {string}
   */
  function identitet(value) {
    const siffror = String(value || '').replace(/\D/g, '');
    if (siffror.length === 12) return siffror;
    if (siffror.length !== 10) return siffror;
    /* Ett organisationsnummer har 20-99 som tredje och fjärde siffra — inget
       giltigt födelsedatum har månad 20 eller högre. */
    const manad = Number(siffror.slice(2, 4));
    if (manad > 12) return '16' + siffror;
    /* En fysisk person: sekelsiffran beror på födelseåret, och den som är
       född 00-25 antas vara född på 2000-talet. */
    const ar = Number(siffror.slice(0, 2));
    const nu = new Date().getFullYear() % 100;
    return (ar <= nu ? '20' : '19') + siffror;
  }

  function idag() {
    const d = new Date();
    const p = (n) => String(n).padStart(2, '0');
    return {
      datum: `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}`,
      tid: `${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`,
    };
  }

  /** Ett fält i INFO.SRU, utelämnat när det saknar värde. */
  function post(namn, varde) {
    const text = String(varde ?? '').trim();
    return text ? `${namn} ${text}` : null;
  }

  /**
   * INFO.SRU — vem som skickar, och vilken datafil som följer.
   *
   * Posternas ordning är föreskriven och kontrolleras av Skatteverket, så den
   * här funktionen bygger dem i ordning och hoppar bara över de frivilliga.
   *
   * @param {Object} u - uppgiftslämnaren
   * @returns {string}
   */
  function infoSru(u) {
    const nu = idag();
    const rader = [
      '#DATABESKRIVNING_START',
      '#PRODUKT SRU',
      post('#MEDIAID', u.mediaid),
      `#SKAPAD ${u.datum || nu.datum} ${u.tid || nu.tid}`,
      post('#PROGRAM', u.program || 'kvot ab inkomstdeklaration.html'),
      '#FILNAMN BLANKETTER.SRU',
      '#DATABESKRIVNING_SLUT',
      '#MEDIELEV_START',
      `#ORGNR ${identitet(u.orgnr)}`,
      `#NAMN ${u.namn || ''}`,
      post('#ADRESS', u.adress),
      `#POSTNR ${String(u.postnr || '').replace(/\s/g, '')}`,
      `#POSTORT ${u.postort || ''}`,
      post('#AVDELNING', u.avdelning),
      post('#KONTAKT', u.kontakt),
      post('#EMAIL', u.email),
      post('#TELEFON', u.telefon),
      post('#FAX', u.fax),
      '#MEDIELEV_SLUT',
    ].filter(Boolean);
    return rader.join('\r\n') + '\r\n';
  }

  /**
   * BLANKETTER.SRU — ett block per blankett.
   *
   * @param {Object[]} blanketter - { namn, period, varden: Map }
   * @param {Object} ident - { orgnr, namn, datum, tid }
   * @returns {string}
   */
  function blanketterSru(blanketter, ident) {
    const nu = idag();
    const datum = ident.datum || nu.datum;
    const tid = ident.tid || nu.tid;
    const rader = [];
    for (const b of blanketter) {
      if (!b.varden || !b.varden.size) continue;
      rader.push(`#BLANKETT ${b.namn}-${b.period}`);
      rader.push(`#IDENTITET ${identitet(ident.orgnr)} ${datum} ${tid}`);
      if (ident.namn) rader.push(`#NAMN ${ident.namn}`);
      /* Fältkoderna i blankettens egen ordning, inte i den ordning de råkade
         räknas fram — en fil som går att läsa uppifrån och ned bredvid
         pappersblanketten är lättare att stämma av. */
      const ordning = (blankett(b.namn) || { falt: [] }).falt.map(f => f.kod);
      const koder = [...b.varden.keys()].sort((a, c) => {
        const ia = ordning.indexOf(a);
        const ic = ordning.indexOf(c);
        return (ia < 0 ? 9999 : ia) - (ic < 0 ? 9999 : ic);
      });
      for (const kod of koder) rader.push(`#UPPGIFT ${kod} ${b.varden.get(kod)}`);
      rader.push('#BLANKETTSLUT');
    }
    rader.push('#FIL_SLUT');
    return rader.join('\r\n') + '\r\n';
  }

  /*
    Skatteverket föreskriver ISO 8859-1. TextEncoder kan bara UTF-8, så
    byten sätts här: latin-1 är de första 256 kodpunkterna rakt av, och det
    som faller utanför blir en frågetecken snarare än att tyst försvinna.
  */
  function latin1(text) {
    const bytes = new Uint8Array(text.length);
    for (let i = 0; i < text.length; i++) {
      const code = text.codePointAt(i);
      bytes[i] = code <= 0xff ? code : 0x3f;
    }
    return bytes;
  }

  /**
   * Läs tillbaka en BLANKETTER.SRU.
   *
   * Nyttig i två fall: att fortsätta på något som redan lämnats, och att se
   * efter vad som faktiskt står i en fil som ett annat program skrivit. Filen
   * är ISO 8859-1, men eftersom posterna är rena ASCII utom i namn och
   * fritext duger det att avkoda latin-1 rakt av.
   *
   * @param {Uint8Array|string} indata
   * @returns {{block: Object[], identitet: Object|null, fel: string[]}}
   */
  function lasBlanketterSru(indata) {
    const text = typeof indata === 'string' ? indata
      : Array.from(indata, b => String.fromCharCode(b)).join('');
    const block = [];
    const fel = [];
    let identitet = null;
    let aktuellt = null;

    for (const rad of text.split(/\r?\n/)) {
      const rent = rad.trim();
      if (!rent) continue;
      const mellanslag = rent.indexOf(' ');
      const post = mellanslag < 0 ? rent : rent.slice(0, mellanslag);
      const rest = mellanslag < 0 ? '' : rent.slice(mellanslag + 1).trim();

      switch (post) {
        case '#BLANKETT': {
          const m = /^([A-Z0-9]+)\s*-\s*(\d{4}P[1-4])$/.exec(rest);
          if (!m) { fel.push(`Kunde inte tolka blankettypen "${rest}".`); aktuellt = null; break; }
          aktuellt = { namn: m[1], period: m[2], varden: new Map() };
          block.push(aktuellt);
          break;
        }
        case '#IDENTITET': {
          const delar = rest.split(/\s+/);
          if (!identitet) identitet = { orgnr: delar[0] || '', datum: delar[1] || '',
                                        tid: delar[2] || '' };
          break;
        }
        case '#NAMN':
          if (identitet && !identitet.namn) identitet.namn = rest;
          break;
        case '#UPPGIFT': {
          if (!aktuellt) { fel.push(`#UPPGIFT utanför ett blankettblock: ${rest}`); break; }
          const kod = rest.slice(0, rest.indexOf(' ') < 0 ? rest.length : rest.indexOf(' '));
          const varde = rest.slice(kod.length).trim();
          if (!/^\d{4}$/.test(kod)) { fel.push(`Ogiltig fältkod "${kod}".`); break; }
          aktuellt.varden.set(kod, varde);
          break;
        }
        case '#BLANKETTSLUT':
          aktuellt = null;
          break;
        case '#SYSTEMINFO': case '#FIL_SLUT':
          break;
        default:
          if (post.startsWith('#')) fel.push(`Okänd post ${post}.`);
      }
    }
    if (!block.length) fel.push('Filen innehåller inga blankettblock.');
    return { block, identitet, fel };
  }

  // ── Kontroll ──────────────────────────────────────────────────────────────

  /**
   * Vad Skatteverket skulle klaga på.
   *
   * Värdeförrådet säger vad varje datatyp tillåter, och en fältkod som är
   * obligatorisk måste finnas. Kontrollen är inte uttömmande — e-tjänsten
   * kör sina egna mot skattedatabasen — men den fångar det som går att se
   * utan att skicka något.
   *
   * @param {Object[]} blanketter
   * @returns {Object[]} { niva, text }
   */
  function kontrollera(blanketter) {
    const ut = [];
    for (const b of blanketter) {
      const def = blankett(b.namn);
      if (!def) {
        ut.push({ niva: 'error', text: `Okänd blankett ${b.namn}.` });
        continue;
      }
      if (!b.varden || !b.varden.size) continue;

      for (const falt of def.falt) {
        const finns = b.varden.has(falt.kod);
        if (falt.obl && !finns) {
          ut.push({ niva: 'error',
            text: `${b.namn} ${falt.kod} är obligatorisk och saknas: ${falt.text}` });
        }
        if (!finns) continue;
        const fel = strider(b.varden.get(falt.kod), falt);
        if (fel) ut.push({ niva: 'error', text: `${b.namn} ${falt.kod}: ${fel}` });
      }
      for (const [kod, varde] of b.varden) {
        const falt = def.falt.find(f => f.kod === kod);
        /* BAS kopplar till exempel hela 25xx till skatteskulder, utan villkor.
           Står företaget på plus mot Skatteverket blir raden negativ, vilket
           datatypen tillåter men som är värt att titta efter innan filen
           lämnas. */
        if (falt && varde < 0 && falt.tecken === '*') {
          ut.push({ niva: 'info',
            text: `${b.namn} ${kod} är negativ (${varde}): ${falt.text}` });
        }
        if (!def.falt.some(f => f.kod === kod)) {
          ut.push({ niva: 'warn',
            text: `${b.namn} ${kod} finns inte i blankettens fältnamnstabell.` });
        }
      }
    }
    return ut;
  }

  /** Bryter värdet mot sin datatyp? Returnerar felet, eller ''. */
  function strider(varde, falt) {
    const text = String(varde ?? '').trim();
    if (!text) return 'värdet är tomt';
    const typ = falt.typ || '';
    if (/^Numeriskt/.test(typ)) {
      if (!/^-?\d+$/.test(text)) return `${text} är inte ett heltal`;
      const tal = Number(text);
      if (/_B$|_10$|_13$/.test(typ) && tal < 0) {
        return `${text} är negativt, men fältet tar bara noll eller mer`;
      }
    } else if (/^Datum/.test(typ)) {
      if (!/^\d{8}$/.test(text)) return `${text} ska skrivas ÅÅÅÅMMDD`;
    } else if (/^Orgnr/.test(typ)) {
      if (!/^\d{12}$/.test(text)) return `${text} ska vara tolv siffror med sekelsiffra`;
    }
    return '';
  }

  return {
    deklaration, blankett, faltkod, riktning, netto, kopplingarFor,
    periodFor, oppning, perioder, PERIODER, lasBlanketterSru,
    OVERFORING, HUVUDBLANKETT, DATUMKODER, SUMMERING, summera, pensionskostnader,
    beskrivning,
    faltvarden, identitet, infoSru, blanketterSru, latin1, kontrollera, strider,
  };
})();

if (typeof module === 'object' && module.exports) module.exports = KVOT_SRU;
