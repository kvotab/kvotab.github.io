/* ==========================================================================
   arsred-tidigare.js — läs en tidigare årsredovisning och föreslå ifyllnad

   En SIE-fil bär siffror. Den bär inte verksamhetsbeskrivningen, sätet,
   redovisningsprinciperna, nyckeltalsdefinitionerna, styrelsens yttrande om
   vinstutdelning, vilka som skriver under — eller de äldre årens tal i
   flerårsöversikten. Allt det stod i förra årets årsredovisning, och det är
   den här filens uppgift att hämta tillbaka det.

   Tre format läses:

     iXBRL   Exakt. Uppgifterna hämtas ur taggarna, inte ur prosan, så det som
             föreslås är samma värde som lämnades in i fjol.
     docx    Tolkat. Word-filen packas upp i webbläsaren och texten läses ur
             word/document.xml, med tabellcellerna åtskilda så att
             flerårsöversikten går att läsa som en tabell.
     pdf     Tolkat, och sämst. Texten hämtas med pdf.js; en PDF vet inget om
             tabeller, så flerårsöversikten kan komma i oordning.

   Ingenting fylls i av sig självt. Det som hittas visas som förslag, ett i
   taget, med var det kommer ifrån och hur säkert det är. Att gissa ur prosa
   och sedan skriva rakt in i en handling som ska lämnas in vore fel sorts
   hjälpsamhet.
   ========================================================================== */

const KVOT_ARSRED_TIDIGARE = (() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  let forslag = [];

  // ── Zip, för docx ─────────────────────────────────────────────────────────

  /*
    En docx är en zip med deflate-komprimerade delar. Webbläsaren kan packa
    upp dem själv sedan DecompressionStream kom; utan den skulle den här filen
    behöva bära en egen inflate, vilket vore mer kod än allt annat här
    tillsammans. Saknas den sägs det rakt ut i stället för att filen tyst
    vägrar öppnas.
  */
  function dataView(bytes) { return new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength); }

  /**
   * Hämta en namngiven fil ur en zip.
   *
   * @param {Uint8Array} bytes
   * @param {string} wanted
   * @returns {Promise<Uint8Array|null>}
   */
  async function unzipEntry(bytes, wanted) {
    const view = dataView(bytes);
    /* Slutposten ligger sist och kan följas av en kommentar, så den söks
       bakifrån. */
    let end = -1;
    for (let i = bytes.length - 22; i >= 0 && i > bytes.length - 65558; i--) {
      if (view.getUint32(i, true) === 0x06054b50) { end = i; break; }
    }
    if (end < 0) throw new Error('Filen är inte en zip — en .docx ska vara det.');

    const count = view.getUint16(end + 10, true);
    let at = view.getUint32(end + 16, true);
    for (let i = 0; i < count; i++) {
      if (view.getUint32(at, true) !== 0x02014b50) break;
      const method = view.getUint16(at + 10, true);
      const compressed = view.getUint32(at + 20, true);
      const nameLength = view.getUint16(at + 28, true);
      const extraLength = view.getUint16(at + 30, true);
      const commentLength = view.getUint16(at + 32, true);
      const local = view.getUint32(at + 42, true);
      const name = new TextDecoder('utf-8')
        .decode(bytes.subarray(at + 46, at + 46 + nameLength));

      if (name === wanted) {
        /* De lokala huvudenas längder kan skilja sig från de i katalogen, så
           dataområdet måste räknas ut ur det lokala huvudet. */
        const localName = view.getUint16(local + 26, true);
        const localExtra = view.getUint16(local + 28, true);
        const start = local + 30 + localName + localExtra;
        const data = bytes.subarray(start, start + compressed);
        if (method === 0) return data;
        if (method !== 8) throw new Error(`Okänd komprimering (${method}) i zip-filen.`);
        if (typeof DecompressionStream !== 'function') {
          throw new Error('Webbläsaren kan inte packa upp zip-filer '
            + '(DecompressionStream saknas). Spara om filen som iXBRL eller PDF.');
        }
        const stream = new Blob([data]).stream()
          .pipeThrough(new DecompressionStream('deflate-raw'));
        return new Uint8Array(await new Response(stream).arrayBuffer());
      }
      at += 46 + nameLength + extraLength + commentLength;
    }
    return null;
  }

  // ── De tre formaten till text ─────────────────────────────────────────────

  /**
   * Texten i en Word-fil.
   *
   * Styckena blir rader och tabellcellerna åtskiljs med tabb, så att
   * flerårsöversikten och förändringen av eget kapital går att läsa som
   * tabeller i stället för som en radda tal.
   *
   * @param {Uint8Array} bytes
   * @returns {Promise<string>}
   */
  async function textFromDocx(bytes) {
    const part = await unzipEntry(bytes, 'word/document.xml');
    if (!part) throw new Error('Filen saknar word/document.xml — är det verkligen en .docx?');
    const doc = new DOMParser().parseFromString(new TextDecoder('utf-8').decode(part),
                                                'application/xml');
    const W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main';
    const lines = [];

    const paragraphText = (p) => {
      let text = '';
      for (const node of p.getElementsByTagNameNS(W, '*')) {
        if (node.localName === 't') text += node.textContent;
        else if (node.localName === 'tab') text += '\t';
        else if (node.localName === 'br' || node.localName === 'cr') text += ' ';
      }
      return text.replace(/[  ]+/g, ' ').trim();
    };

    for (const node of doc.documentElement.getElementsByTagNameNS(W, '*')) {
      if (node.localName === 'tbl') {
        for (const row of node.getElementsByTagNameNS(W, 'tr')) {
          /* Bara cellerna som hör till just den här raden, inte till en
             nästlad tabell längre ned. */
          const cells = [...row.children].filter(c => c.localName === 'tc');
          lines.push(cells.map(cell =>
            [...cell.getElementsByTagNameNS(W, 'p')].map(paragraphText)
              .filter(Boolean).join(' ')).join('\t'));
        }
      } else if (node.localName === 'p' && !node.closest('*|tbl')) {
        const text = paragraphText(node);
        if (text) lines.push(text);
      }
    }
    return lines.join('\n');
  }

  /**
   * Texten och de taggade uppgifterna i en iXBRL-handling.
   *
   * @param {string} xhtml
   * @returns {{text: string, facts: Map}}
   */
  function textFromIxbrl(xhtml) {
    const doc = new DOMParser().parseFromString(xhtml, 'application/xhtml+xml');
    if (doc.getElementsByTagName('parsererror')[0]) {
      throw new Error('Filen går inte att läsa som XHTML.');
    }
    const IX = ['http://www.xbrl.org/2013/inlineXBRL', 'http://www.xbrl.org/2008/inlineXBRL'];
    const facts = new Map();
    for (const ns of IX) {
      for (const local of ['nonNumeric', 'nonFraction']) {
        for (const el of doc.getElementsByTagNameNS(ns, local)) {
          const name = String(el.getAttribute('name') || '').split(':').pop();
          const context = el.getAttribute('contextRef') || '';
          if (!name) continue;
          /* Ett element kan förekomma i flera kontexter; nyckeln bär båda så
             att rätt år går att plocka ut. */
          facts.set(`${name}@${context}`, {
            text: (el.textContent || '').trim(),
            scale: Number(el.getAttribute('scale') || 0),
            sign: el.getAttribute('sign') === '-' ? -1 : 1,
          });
        }
      }
    }
    /* Kontexterna säger vilken period varje faktum avser. Med dem behöver
       flerårsöversikten inte läsas ur texten alls: rätt år går att slå upp
       direkt, vilket är hela poängen med att källan är taggad. */
    const XBRLI = 'http://www.xbrl.org/2003/instance';
    const perioder = new Map();
    for (const ctx of doc.getElementsByTagNameNS(XBRLI, 'context')) {
      const id = ctx.getAttribute('id');
      const start = ctx.getElementsByTagNameNS(XBRLI, 'startDate')[0];
      const slut = ctx.getElementsByTagNameNS(XBRLI, 'endDate')[0];
      const instant = ctx.getElementsByTagNameNS(XBRLI, 'instant')[0];
      if (id && start && slut) {
        perioder.set(id, { from: start.textContent.trim(), tom: slut.textContent.trim() });
      } else if (id && instant) {
        perioder.set(id, { tom: instant.textContent.trim() });
      }
    }

    /* Rubrikraden först, som i en tabell. Låg den sist letade läsningen av
       flerårsöversikten vidare in i resultaträkningen och hämtade fel tal. */
    const text = KVOT_ARSRED_EXPORT.blocksFromIxbrl(xhtml).blocks
      .map(b => b.type === 'table'
        ? b.head.concat(b.rows).map(r => r.map(c => c.text).join('\t')).join('\n')
        : b.text || (b.rader || []).map(r => r.text).join('\n') || b.namn || '')
      .filter(Boolean).join('\n\n');
    return { text, facts, perioder };
  }

  /* pdf.js hämtas först när en PDF faktiskt släpps, och med integritetskontroll.
     Version och hashar är desamma som SKB-verktyget på sajten redan använder. */
  const PDFJS_VERSION = '3.11.174';
  const PDFJS_BASE = `https://cdnjs.cloudflare.com/ajax/libs/pdf.js/${PDFJS_VERSION}/`;
  const PDFJS_INTEGRITY =
    'sha512-q+4liFwdPC/bNdhUpZx6aXDx/h77yEQtn4I1slHydcbZK34nLaR3cAeYSJshoxIOq3mjEf7xJE8YWIUHMn+oCQ==';
  let pdfjsPromise = null;

  function loadPdfJs() {
    if (window.pdfjsLib) return Promise.resolve(window.pdfjsLib);
    if (pdfjsPromise) return pdfjsPromise;
    pdfjsPromise = new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = PDFJS_BASE + 'pdf.min.js';
      script.integrity = PDFJS_INTEGRITY;
      script.crossOrigin = 'anonymous';
      script.onload = () => window.pdfjsLib
        ? resolve(window.pdfjsLib)
        : reject(new Error('pdf.js laddades men registrerade sig inte.'));
      script.onerror = () => reject(new Error('pdf.js kunde inte hämtas. '
        + 'Den här vägen kräver nät; iXBRL och Word läses utan.'));
      document.head.appendChild(script);
    });
    return pdfjsPromise;
  }

  /**
   * Texten i en PDF, rad för rad.
   *
   * @param {Uint8Array} bytes
   * @returns {Promise<string>}
   */
  async function textFromPdf(bytes) {
    const pdfjs = await loadPdfJs();
    pdfjs.GlobalWorkerOptions.workerSrc = PDFJS_BASE + 'pdf.worker.min.js';
    const doc = await pdfjs.getDocument({ data: bytes }).promise;
    const sidor = [];
    for (let i = 1; i <= doc.numPages; i++) {
      const page = await doc.getPage(i);
      const content = await page.getTextContent();
      /* Texten kommer som lösryckta bitar med koordinater. Bitar på samma
         höjd hör till samma rad; mellan dem sätts tabb, så att det som stod i
         skilda kolumner inte klistras ihop till ett tal. */
      const rader = new Map();
      for (const item of content.items) {
        if (!item.str || !item.str.trim()) continue;
        const y = Math.round(item.transform[5]);
        if (!rader.has(y)) rader.set(y, []);
        rader.get(y).push({ x: item.transform[4], text: item.str });
      }
      sidor.push([...rader.entries()].sort((a, b) => b[0] - a[0])
        .map(([, bitar]) => bitar.sort((a, b) => a.x - b.x)
          .map(b => b.text.trim()).filter(Boolean).join('\t'))
        .join('\n'));
    }
    return sidor.join('\n');
  }

  // ── Vad som går att hämta ─────────────────────────────────────────────────

  const tal = (text) => {
    const cleaned = String(text || '').replace(/[\s ]/g, '').replace(',', '.');
    const value = Number(cleaned);
    return Number.isFinite(value) && cleaned !== '' ? value : undefined;
  };

  /**
   * Stycket som börjar med en viss fras, frasen inräknad.
   *
   * Slutar vid nästa tomrad, eller vid en rad som ser ut som en ny rubrik.
   *
   * @param {string} text
   * @param {string} fras
   * @returns {string}
   */
  function avsnittFran(text, fras) {
    const start = text.indexOf(fras);
    if (start < 0) return '';
    let rest = text.slice(start);
    const slut = AVSNITTSSLUT.exec(rest.slice(fras.length));
    if (slut) rest = rest.slice(0, fras.length + slut.index);
    return rest.replace(/\s+/g, ' ').trim();
  }

  /*
    Var ett avsnitt tar slut, när källan inte är taggad. En tomrad räcker inte:
    Word-filer skiljer ofta styckena åt med enbart radbyte, och då löpte
    redovisningsprinciperna vidare ned i underskriften. Mönstren nedan är de
    rubriker och rader en årsredovisning byter avsnitt vid — inklusive en rad
    med tabb i, som är en tabellrad och alltså aldrig löpande text.
  */
  const AVSNITTSSLUT = new RegExp('\\n(?=(?:'
    + 'Not \\d|Noter|Underskrift|Fastställelse|Revisionsberättelse'
    + '|Resultaträkning|Balansräkning|Flerårsöversikt|Förändring av eget kapital'
    + '|Resultatdisposition|Förvaltningsberättelse|Allmänna upplysningar'
    + '|Nyckeltalsdefinitioner|Företaget har sitt säte|Väsentliga händelser'
    + '|Företagets resultat och ställning'
    + '|[A-ZÅÄÖ][a-zåäöA-ZÅÄÖ\\- ]{1,30} den \\d'
    + '))|\\n[^\\n]*\\t|\\n\\s*\\n');

  /** Texten mellan en rubrik och nästa avsnitt. */
  function avsnitt(text, rubrik, stopp) {
    const start = new RegExp(rubrik + '\\s*:?\\s*', 'i').exec(text);
    if (!start) return '';
    let rest = text.slice(start.index + start[0].length);
    const eget = stopp ? new RegExp(stopp, 'i').exec(rest) : null;
    if (eget) rest = rest.slice(0, eget.index);
    const slut = AVSNITTSSLUT.exec(rest);
    if (slut) rest = rest.slice(0, slut.index);
    return rest.replace(/\s+/g, ' ').trim();
  }

  /**
   * Läs ut vad den tidigare årsredovisningen kan bidra med.
   *
   * Flerårsöversikten plockas per periodetikett i stället för per kolumnplats.
   * Laddar någon upp samma års redovisning ligger de äldre åren i kolumn tre
   * och fyra; laddar de upp fjolårets ligger de i kolumn två och tre. Att
   * matcha på etiketten gör att båda fungerar utan att någon behöver tala om
   * vilket år filen avser.
   *
   * @param {string} text
   * @param {Map} facts - taggade värden när källan är iXBRL
   * @param {Map} perioder - kontext -> period, likaså
   * @returns {Object[]} förslag
   */
  function lasUt(text, facts, perioder) {
    const rad = [];
    const foreslå = (id, label, value, kalla) => {
      if (value === undefined || value === null || value === '') return;
      rad.push({ id, label, value: String(value), kalla });
    };

    const exakt = (name, context) => {
      if (!facts) return undefined;
      const hit = facts.get(`${name}@${context}`) || facts.get(`${name}@period0`)
        || facts.get(`${name}@balans0`);
      return hit ? hit.text : undefined;
    };

    /* Ur taggarna först, när de finns: samma värde som lämnades in. */
    foreslå('bygg-verksamhet', 'Allmänt om verksamheten',
      exakt('AllmantVerksamheten') || avsnitt(text, 'Allmänt om verksamheten',
        'Företaget har sitt säte|Väsentliga händelser|Flerårsöversikt'),
      facts && exakt('AllmantVerksamheten') ? 'taggat' : 'ur texten');

    const sate = exakt('ForetagetsSate')
      || (/Företaget har sitt säte i ([^.\n\t]+)/i.exec(text) || [])[1];
    foreslå('bygg-sate', 'Säte', sate && sate.trim(),
      facts && exakt('ForetagetsSate') ? 'taggat' : 'ur texten');

    foreslå('bygg-principer', 'Redovisningsprinciper',
      exakt('RedovisningsVarderingsprinciper')
        || avsnitt(text, 'Allmänna upplysningar', 'Nyckeltalsdefinitioner|Not \\d'),
      facts && exakt('RedovisningsVarderingsprinciper') ? 'taggat' : 'ur texten');

    foreslå('bygg-nyckeltal', 'Nyckeltalsdefinitioner',
      exakt('Nyckeltalsdefinitioner')
        || avsnitt(text, 'Nyckeltalsdefinitioner', 'Not \\d|Underskrift'),
      facts && exakt('Nyckeltalsdefinitioner') ? 'taggat' : 'ur texten');

    /* Yttrandet är ett långt stycke som i Word ofta är brutet över flera
       rader. Att först platta till radbrytningarna och sedan leta efter en
       radbrytning som slut gick förstås aldrig — stycket tar slut vid nästa
       tomrad, och den finns bara i den obehandlade texten. */
    const yttrande = exakt('StyrelsensYttrandeVinstutdelning')
      || avsnittFran(text, 'Styrelsen anser att förslaget är förenligt');
    foreslå('bygg-yttrande', 'Styrelsens yttrande om vinstutdelning',
      yttrande && yttrande.replace(/\s+/g, ' ').trim(),
      facts && exakt('StyrelsensYttrandeVinstutdelning') ? 'taggat' : 'ur texten');

    /* Antalet aktier står inte någonstans, men utdelningen per aktie gör det,
       och tillsammans med utdelningens belopp ger det antalet. */
    const perAktie = /utdelas\s*\(([\d\s .,]+)\s*kronor per aktie\)/i.exec(text);
    if (perAktie) {
      const belopp = /kronor per aktie\)[\s\S]{0,80}?([\d ][\d\s ]{2,})/i.exec(text);
      const per = tal(perAktie[1]);
      const summa = belopp ? tal(belopp[1]) : undefined;
      if (per && summa) foreslå('bygg-antal-aktier', 'Antal aktier',
        Math.round(summa / per), 'räknat ur kronor per aktie');
    }

    const ort = /^\s*([A-ZÅÄÖ][a-zåäöA-ZÅÄÖ\- ]{1,30})\s+den\s+\d/m.exec(text);
    foreslå('bygg-ort', 'Ort för underskrift', ort && ort[1].trim(), 'ur texten');

    lasFlerarsoversikt(text, rad, facts, perioder);
    lasAnstallda(text, rad, facts, perioder);
    lasUnderskrifter(text, rad);
    return rad;
  }

  /** De år formuläret saknar, med sina etiketter. */
  function saknadeAr() {
    const out = [];
    for (const index of [2, 3]) {
      const from = ($(`bygg-ar${index}-from`) || {}).value;
      const tom = ($(`bygg-ar${index}-tom`) || {}).value;
      if (!from || !tom) continue;
      out.push({ index, from, tom,
        etikett: from.slice(0, 4) === tom.slice(0, 4)
          ? tom.slice(0, 4) : `${from.slice(0, 4)}/${tom.slice(2, 4)}` });
    }
    return out;
  }

  const FLERAR_FALT = Object.freeze([
    ['netto', 'Nettoomsattning', 'Nettoomsättning'],
    ['resultat', 'ResultatEfterFinansiellaPoster', 'Resultat efter finansiella poster'],
    ['soliditet', 'Soliditet', 'Soliditet (%)'],
  ]);

  /**
   * Flerårsöversikten ur taggarna, när källan är en iXBRL-handling.
   *
   * Perioden i kontexten avgör vilket år ett faktum hör till, så inget behöver
   * läsas ur texten. Beloppen står redan i tusental i handlingen — scale="3"
   * hör till faktumet, inte till texten — och kan användas som de står.
   *
   * @returns {boolean} om något hittades
   */
  function flerarUrFacts(rad, facts, perioder) {
    if (!facts || !perioder || !perioder.size) return false;
    let hittat = false;
    for (const year of saknadeAr()) {
      /* Vilken kontext som helst vars period är just det året. */
      const kontexter = [...perioder.entries()]
        .filter(([, p]) => p.tom === year.tom)
        .map(([id]) => id);
      for (const [faltdel, element, label] of FLERAR_FALT) {
        for (const context of kontexter) {
          const hit = facts.get(`${element}@${context}`);
          if (!hit || !hit.text) continue;
          rad.push({ id: `bygg-ar${year.index}-${faltdel}`,
                     label: `${year.etikett}: ${label}`, value: hit.text,
                     kalla: 'taggat' });
          hittat = true;
          break;
        }
      }
    }
    return hittat;
  }

  /** En rad i listan som förklarar något i stället för att föreslå ett värde. */
  function notering(rad, text) {
    rad.push({ id: '__notering', label: 'Flerårsöversikt', value: text, kalla: '' });
  }

  /**
   * Flerårsöversiktens äldre år, matchade på periodetikett.
   *
   * Matchningen kräver att sidan vet vilka år som saknas, och det vet den
   * först när bokföringen är inläst — därifrån kommer räkenskapsåret, och
   * därmed de härledda datumen för de äldre åren. Släpps den tidigare
   * årsredovisningen först blir det alltså inga förslag här, och det är värt
   * att säga rakt ut i stället för att bara låta bli att visa något.
   */
  function lasFlerarsoversikt(text, rad, facts, perioder) {
    const behovs = saknadeAr();
    if (!behovs.length) {
      return notering(rad, 'Läs in bokföringen i steg A1 först, så vet sidan vilka år '
        + 'flerårsöversikten saknar och kan hämta dem härifrån. Ladda upp den här filen '
        + 'igen efteråt.');
    }
    if (flerarUrFacts(rad, facts, perioder)) return;
    const rader = text.split('\n').map(line => line.split('\t').map(c => c.trim()));
    const rubrikrad = rader.findIndex(cells =>
      cells.filter(c => /^\d{4}(\/\d{2})?$/.test(c)).length >= 2);
    if (rubrikrad < 0) {
      return notering(rad, 'Ingen flerårsöversikt hittades i filen. I en PDF hamnar '
        + 'tabellens kolumner ibland i oordning; en iXBRL- eller Word-fil läses säkrare.');
    }
    const etiketter = rader[rubrikrad];

    /*
      Var tabellen slutar. En tomrad duger inte som gräns: Word lägger ofta en
      tom rad direkt under rubrikraden, och med den som slut blev sökområdet
      tomt och flerårsöversikten lästes inte alls — tyst, eftersom kolumnerna
      ändå matchade. Tabellen tar i stället slut vid första raden efteråt som
      är ett stycke och inte en tabellrad: en enda cell med text i. Ytterligare
      en rubrikrad, alltså en ny tabell, avslutar också.
    */
    const arEtikett = (cell) => /^\d{4}(\/\d{2})?$/.test(cell);
    let slut = rader.length;
    for (let i = rubrikrad + 1; i < rader.length; i++) {
      const cells = rader[i];
      const text = cells.filter(Boolean);
      if (!text.length) continue;                                  // tomrad
      if (cells.length < 2) { slut = i; break; }                   // stycke
      if (cells.filter(arEtikett).length >= 2) { slut = i; break; } // ny tabell
    }

    const hamta = (namn) => {
      const index = rader.findIndex((cells, i) =>
        i > rubrikrad && i < slut && new RegExp('^' + namn, 'i').test(cells[0] || ''));
      return index < 0 ? null : rader[index];
    };
    const rows = {
      netto: hamta('Nettoomsättning'),
      resultat: hamta('Resultat efter finansiella poster'),
      soliditet: hamta('Soliditet'),
    };

    let traffar = 0;
    for (const year of behovs) {
      const kolumn = etiketter.indexOf(year.etikett);
      if (kolumn < 0) continue;
      traffar++;
      for (const key of ['netto', 'resultat', 'soliditet']) {
        const cells = rows[key];
        if (!cells || !cells[kolumn]) continue;
        rad.push({
          id: `bygg-ar${year.index}-${key}`,
          label: `${year.etikett}: ${cells[0]}`,
          value: cells[kolumn],
          kalla: 'flerårsöversikten',
        });
      }
    }
    if (traffar && !rad.some(f => /^bygg-ar[23]-/.test(f.id))) {
      notering(rad, 'Flerårsöversiktens kolumner känns igen, men inga tal kunde läsas ur '
        + 'raderna. Skriv in dem för hand i fälten nedan.');
      return;
    }
    if (!traffar) {
      const funna = etiketter.filter(c => /^\d{4}(\/\d{2})?$/.test(c));
      notering(rad, `Filens flerårsöversikt har kolumnerna ${funna.join(', ')}, och inget av `
        + `dem är ${behovs.map(y => y.etikett).join(' eller ')}. Kontrollera datumen för de `
        + 'äldre åren i fälten nedan, eller skriv in talen för hand.');
    }
  }

  /**
   * Medelantalet anställda för jämförelseåret, till not 2.
   *
   * Talet står i den tidigare årsredovisningens egen not, med två kolumner.
   * Vilken av dem som är jämförelseåret beror på vilket år filen avser, så
   * kolumnen väljs på slutdatum: den som slutar samma dag som fältet för
   * föregående räkenskapsår i formuläret.
   */
  function lasAnstallda(text, rad, facts, perioder) {
    const fgTom = ($('bygg-fg-tom') || {}).value;
    if (!fgTom) return;

    /* Ur taggarna när källan bär dem. */
    if (facts && perioder) {
      for (const [id, period] of perioder) {
        if (period.tom !== fgTom) continue;
        const hit = facts.get(`MedelantaletAnstallda@${id}`);
        if (!hit || !hit.text) continue;
        rad.push({ id: 'bygg-anstallda-fg', label: 'Medelantalet anställda, föregående år',
                   value: hit.text, kalla: 'taggat' });
        return;
      }
    }

    const rader = text.split('\n').map(line => line.split('\t').map(c => c.trim()));
    const radIndex = rader.findIndex(cells =>
      cells.length >= 2 && /^Medelantalet anställda/i.test(cells[0] || ''));
    if (radIndex < 0) return;

    /* Kolumnrubrikerna står i raderna närmast ovanför, och kan vara delade på
       två rader — startdatum på den ena, slutdatum på den andra, som i
       "2024-07-01" och "-2025-06-30". Slutdatumet är det som identifierar
       året, så det är det som eftersöks. */
    let kolumn = -1;
    for (let i = radIndex - 1; i >= 0 && i >= radIndex - 4 && kolumn < 0; i--) {
      kolumn = rader[i].findIndex(cell => cell && cell.includes(fgTom));
    }
    if (kolumn < 0) return;
    const value = rader[radIndex][kolumn];
    if (!value) return;
    rad.push({ id: 'bygg-anstallda-fg', label: 'Medelantalet anställda, föregående år',
               value, kalla: 'not 2' });
  }

  /**
   * Namnen under underskriftsraden.
   *
   * Letar efter orten och datumet och tar raderna därefter som namn, till
   * nästa rubrik. Rollerna står ibland under namnet, ibland inte alls, så de
   * föreslås bara när de finns.
   */
  function lasUnderskrifter(text, rad) {
    const rader = text.split('\n').map(line => line.replace(/\t/g, ' ').trim());
    const start = rader.findIndex(line => /^[A-ZÅÄÖ][\wåäöÅÄÖ\- ]{1,30}\s+den\s+\d/.test(line));
    if (start < 0) return;
    const personer = [];
    for (let i = start + 1; i < rader.length && personer.length < 6; i++) {
      const line = rader[i];
      if (!line) continue;
      if (/^(Not|Fastställelse|Revisor|Årsredovisning|Underskrift)/i.test(line)) break;
      /* Ett namn är två till fyra ord som alla börjar med versal. */
      if (!/^[A-ZÅÄÖ][\wåäöÅÄÖ'\-]+(\s+[A-ZÅÄÖ][\wåäöÅÄÖ'\-]+){1,3}$/.test(line)) continue;
      const roll = /^(Styrelseledamot|Ordförande|Styrelseordförande|Verkställande direktör|Likvidator|Suppleant)/i
        .test(rader[i + 1] || '') ? rader[i + 1] : '';
      personer.push({ namn: line, roll });
      if (roll) i++;
    }
    if (personer.length) {
      rad.push({ id: '__underskrifter', label: 'Underskrifter',
        value: personer.map(p => p.roll ? `${p.namn} (${p.roll})` : p.namn).join(', '),
        kalla: 'ur texten', personer });
    }
  }

  // ── Gränssnitt ────────────────────────────────────────────────────────────

  async function lasFil(file) {
    if (!file) return;
    const tooLarge = kvotFileTooLarge(file, 64 * 1024 * 1024);
    if (tooLarge.tooLarge) return showFailureBanner(tooLarge.reason, 'error');

    const namn = file.name.toLowerCase();
    visaStatus(`Läser ${file.name}…`);
    try {
      let text = '';
      let facts = null;
      let perioder = null;
      if (/\.(xhtml|html|htm|xml)$/.test(namn)) {
        const parsed = textFromIxbrl(new TextDecoder('utf-8').decode(
          new Uint8Array(await file.arrayBuffer())));
        text = parsed.text;
        facts = parsed.facts;
        perioder = parsed.perioder;
      } else if (namn.endsWith('.docx')) {
        text = await textFromDocx(new Uint8Array(await file.arrayBuffer()));
      } else if (namn.endsWith('.pdf')) {
        text = await textFromPdf(new Uint8Array(await file.arrayBuffer()));
      } else {
        throw new Error('Formatet känns inte igen. Ladda upp en iXBRL-handling '
          + '(.xhtml), en Word-fil (.docx) eller en PDF.');
      }
      forslag = lasUt(text, facts, perioder);
      visaForslag(file.name, facts ? 'iXBRL — uppgifterna är hämtade ur taggarna'
        : namn.endsWith('.docx') ? 'Word — uppgifterna är tolkade ur texten'
        : 'PDF — uppgifterna är tolkade ur texten');
    } catch (error) {
      forslag = [];
      visaForslag(file.name, '');
      reportFailure('arsred-tidigare.las', error, { userMessage: error.message });
    }
  }

  function visaStatus(text) {
    const box = $('tidigare-resultat');
    if (box) { box.hidden = false; box.textContent = text; }
  }

  function visaForslag(filnamn, kalla) {
    const box = $('tidigare-resultat');
    if (!box) return;
    box.hidden = false;
    /* Noteringar är förklaringar, inte förslag. Finns bara sådana har
       ingenting hittats, och då ska förklaringen stå för sig själv. */
    if (!forslag.some(f => f.id !== '__notering')) {
      box.innerHTML = `<p class="ar-note-inline">${kvotEscapeHtml(filnamn)}${kalla
          ? ' — ' + kvotEscapeHtml(kalla) : ''}.</p>`
        + (forslag.length
          ? '<ul class="ar-problem ar-info-list">'
            + forslag.map(f => `<li>${kvotEscapeHtml(f.value)}</li>`).join('') + '</ul>'
          : '<p class="ar-empty">Ingenting gick att läsa ur filen.</p>');
      return;
    }
    box.innerHTML = `
      <p class="ar-note-inline">${kvotEscapeHtml(filnamn)}${kalla ? ' — ' + kvotEscapeHtml(kalla) : ''}.
         Kryssa för det du vill använda; ingenting fylls i förrän du gör det.</p>
      <div class="ar-table-wrap"><table class="ar-table tidigare">
        <thead><tr><th></th><th>Uppgift</th><th>Värde</th><th>Källa</th></tr></thead>
        <tbody>${forslag.map((f, index) => f.id === '__notering' ? `
          <tr class="tidigare-notering"><td></td>
            <td>${kvotEscapeHtml(f.label)}</td>
            <td colspan="2">${kvotEscapeHtml(f.value)}</td></tr>` : `
          <tr><td><input type="checkbox" data-index="${index}" checked
                aria-label="Använd ${kvotEscapeHtml(f.label)}"></td>
            <td>${kvotEscapeHtml(f.label)}</td>
            <td>${kvotEscapeHtml(f.value.length > 160
              ? f.value.slice(0, 160) + '…' : f.value)}</td>
            <td class="ar-note-inline">${kvotEscapeHtml(f.kalla)}</td></tr>`).join('')}
        </tbody>
      </table></div>
      <div class="ar-btn-row">
        <button type="button" class="ar-btn primary" data-on-click="tidigare:anvand">
          Använd valda</button>
      </div>`;
  }

  registerActions({
    'tidigare:pick': () => $('tidigare-file-input').click(),

    'tidigare:pick-key': (event) => {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      event.preventDefault();
      $('tidigare-file-input').click();
    },

    'tidigare:fil': (event) => {
      const file = event.target.files && event.target.files[0];
      event.target.value = '';
      return lasFil(file);
    },

    'tidigare:anvand': () => {
      const valda = [...document.querySelectorAll('#tidigare-resultat input[type=checkbox]')]
        .filter(box => box.checked)
        .map(box => forslag[Number(box.dataset.index)])
        .filter(Boolean);
      let antal = 0;
      for (const f of valda) {
        if (f.id === '__underskrifter') {
          const lista = $('bygg-underskrifter');
          if (!lista) continue;
          lista.innerHTML = '';
          for (const person of f.personer) {
            lista.insertAdjacentHTML('beforeend', KVOT_ARSRED_BYGG_UI.personBlock());
            const block = lista.lastElementChild;
            const delar = person.namn.split(/\s+/);
            block.querySelector('.bygg-tilltalsnamn').value = delar.slice(0, -1).join(' ');
            block.querySelector('.bygg-efternamn').value = delar[delar.length - 1];
            block.querySelector('.bygg-roll').value = person.roll || '';
          }
          antal++;
          continue;
        }
        const el = $(f.id);
        if (!el) continue;
        el.value = f.value;
        el.dataset.auto = '0';
        el.dispatchEvent(new Event('input', { bubbles: true }));
        /* Ett taggat värde är detsamma som lämnades in i fjol; ett tolkat är
           en läsning av prosa. Skillnaden följer med fältet. */
        KVOT_ARSRED_KALLA.satt(f.id,
          f.kalla === 'taggat' ? 'fjolaret-taggat' : 'fjolaret-text');
        antal++;
      }
      KVOT_ARSRED_BYGG_UI.renderBrister();
      notifyUser(`${antal} uppgift${antal === 1 ? '' : 'er'} ifylld${antal === 1 ? '' : 'a'}.`,
                 { tone: 'success' });
    },
  });

  function mountDropZone() {
    const zone = $('tidigare-drop');
    if (!zone) return;
    for (const type of ['dragenter', 'dragover']) {
      zone.addEventListener(type, (event) => {
        event.preventDefault(); zone.classList.add('dragging');
      });
    }
    for (const type of ['dragleave', 'drop']) {
      zone.addEventListener(type, (event) => {
        event.preventDefault(); zone.classList.remove('dragging');
      });
    }
    zone.addEventListener('drop', (event) => {
      const file = event.dataTransfer && event.dataTransfer.files && event.dataTransfer.files[0];
      if (file) lasFil(file).catch(error => reportFailure('arsred-tidigare.drop', error));
    });
  }

  function init() { mountDropZone(); }

  return { init, lasUt, textFromDocx, textFromIxbrl, unzipEntry };
})();
