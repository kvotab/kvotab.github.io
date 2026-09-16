/* ==========================================================================
   sru-ui.js — gränssnittet för inkomstdeklaration.html

   Formen är en tabell per blankett, inte ett formulär: en inkomstdeklaration
   är en lista av fältkoder med belopp, och det är så den ska gå att läsa
   bredvid pappersblanketten. Varje rad visar sin fältkod, blankettens egen
   punktnumrering, vad raden heter och var beloppet kommer ifrån.

   Räkenskapsschemat fylls ur bokföringen via BAS kopplingstabell. Resten —
   skattemässiga justeringar, uppgifterna på huvudblanketten — finns inte i
   bokföringen och skrivs in. Båda sorternas rader ser likadana ut och går
   att ändra; skillnaden syns i källkolumnen.
   ========================================================================== */

const KVOT_SRU_UI = (() => {
  'use strict';

  const S = KVOT_SRU;
  const D = KVOT_SRU_DATA;
  const B = KVOT_ARSRED_BYGG;
  const $ = (id) => document.getElementById(id);

  const state = {
    deklaration: 'INK2',
    period: '',
    book: null,
    rader: [],            // konton
    okopplade: [],
    /*
      Blankettblocken som en lista, inte en karta per blankettnamn. Samma
      blankett kan förekomma flera gånger — Skatteverket kräver ett eget
      #BLANKETT per delägare på INK4DU — och en fil som läses in kan
      innehålla vad som helst i vilken ordning som helst.
    */
    block: [],            // { id, namn, varden: Map, kallor: Map(kod -> källa) }
    nastaId: 1,
    filer: null,
    visaAlla: false,
  };

  /** Beskattningsperioder att välja bland, den rätta först. */
  function perioder() {
    const tom = state.book && state.book.rakenskapsar && state.book.rakenskapsar.tom;
    return S.perioder(tom || '');
  }

  /** Fyll periodlistan på nytt, med rätt period förvald. */
  function ritaPerioder() {
    const valj = $('sru-period');
    if (!valj) return;
    const lista = perioder();
    const tidigare = valj.value;
    valj.innerHTML = lista.map(p => `<option value="${p}">${p}</option>`).join('');
    /* Ett eget val står kvar; annars väljs den period räkenskapsåret hör
       till, vilken alltid ligger först i listan. */
    valj.value = valj.dataset.rord && lista.includes(tidigare) ? tidigare : lista[0];
    state.period = valj.value;
    ritaPeriodnot();
  }

  /**
   * Vad den valda perioden betyder, och om den är öppen.
   *
   * Skatteverkets besked när perioden är fel säger bara att blankettypen är
   * ogiltig, vilket inte hjälper någon att förstå varför. Regeln och datumen
   * står därför här i stället.
   */
  function ritaPeriodnot() {
    const box = $('sru-periodnot');
    if (!box) return;
    const vald = state.period;
    const tom = state.book && state.book.rakenskapsar && state.book.rakenskapsar.tom;
    const ratt = tom ? S.periodFor(tom) : '';
    const oppnar = S.oppning(vald);
    const idag = new Date().toISOString().slice(0, 10);
    const rader = [];

    const del = S.PERIODER.find(p => vald.endsWith(p.p));
    if (del) {
      rader.push({ niva: 'info',
        text: `${vald} är för räkenskapsår som slutar ${del.text}. Perioden bestäms av `
          + 'räkenskapsårets sista dag, inte av vilket år det är.' });
    }
    if (ratt && vald !== ratt) {
      rader.push({ niva: 'warn',
        text: `Bokslutet per ${tom} hör till ${ratt}, inte ${vald}.` });
    }
    if (oppnar && idag < oppnar.produktion) {
      rader.push({ niva: idag < oppnar.test ? 'error' : 'warn',
        text: `${vald} öppnar för test ${oppnar.test} och för inlämning ${oppnar.produktion}. `
          + 'Lämnas filen före dess svarar Skatteverket att blankettypen är ogiltig.' });
    }
    box.hidden = !rader.length;
    box.innerHTML = rader.map(r => `
      <div class="ar-finding ar-${r.niva}">
        <span class="ar-badge">${r.niva === 'error' ? 'Fel' : r.niva === 'warn' ? 'Varning' : 'Info'}</span>
        <div><div class="ar-finding-title">${kvotEscapeHtml(r.text)}</div></div>
      </div>`).join('');
  }

  function blanketterI(id) {
    const d = S.deklaration(id);
    return d ? d.blanketter : [];
  }

  function nyttBlock(namn, varden) {
    return { id: state.nastaId++, namn, varden: varden || new Map(), kallor: new Map() };
  }

  function blockMed(namn) { return state.block.filter(b => b.namn === namn); }

  /** Sätt listan till deklarationens egna blanketter, utan att tappa det ifyllda. */
  function fyllListan(id) {
    const onskade = blanketterI(id);
    /* Räkenskapsåret ensamt räknas inte som ifyllt här heller: annars skulle
       ett byte av deklaration i steg 1 släpa med sig den förra inlämningens
       tomma blanketter, eftersom varje block bär sina två datum. */
    const behallna = state.block.filter(b => egnaVarden(b) || onskade.includes(b.namn));
    for (const namn of onskade) {
      if (!behallna.some(b => b.namn === namn)) behallna.push(nyttBlock(namn));
    }
    /* Deklarationens egna först, i sin ordning; tillagda bilagor efter. */
    state.block = behallna.sort((a, b) => {
      const ia = onskade.indexOf(a.namn);
      const ib = onskade.indexOf(b.namn);
      return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
    });
  }

  // ── Bokföringen ───────────────────────────────────────────────────────────

  async function lasSie(file) {
    if (!file) return;
    const tooLarge = kvotFileTooLarge(file, 64 * 1024 * 1024);
    if (tooLarge.tooLarge) return showFailureBanner(tooLarge.reason, 'error');

    const { text, encoding } = B.decodeSie(new Uint8Array(await file.arrayBuffer()));
    state.book = B.parseSie(text);
    state.book.kodning = encoding;
    state.rader = B.accounts(state.book);
    rakna();
    forifyll();
    rita();
  }

  /** Räkna om räkenskapsschemat ur kontona. */
  function rakna() {
    const d = S.deklaration(state.deklaration);
    if (!d || !state.rader.length) return;
    const { varden, okopplade } = S.faltvarden(state.rader, state.deklaration);
    state.okopplade = okopplade;

    /* Finns flera block av samma schema fylls det första; de andra är då
       tillagda för hand och ska inte skrivas över. */
    const mal = blockMed(d.rakenskapsschema)[0];
    if (!mal) return;
    for (const [kod, belopp] of varden) {
      /* Ett värde som skrivits in för hand står kvar: en rättelse ska inte
         försvinna för att filen läses om. */
      if (mal.varden.has(kod) && !mal.kallor.has(kod)) continue;
      mal.varden.set(kod, belopp);
      mal.kallor.set(kod, 'bokföringen');
    }
    justeringar(mal);
  }

  /**
   * Det som går att fylla på justeringssidan utan att tolka något.
   *
   * BAS kopplingstabell slutar vid räkenskapsschemat, och det är riktigt —
   * vilka kostnader som inte får dras av är en bedömning, inte ett saldo. Men
   * tre saker är mekaniska: årets resultat flyttas dit blanketten själv säger,
   * den bokförda skatten återförs, och sista raden är summan av allt ovanför.
   *
   * @param {Object} schema - blocket med räkenskapsschemat
   */
  function justeringar(schema) {
    const overforing = S.OVERFORING[state.deklaration];
    if (!overforing) return;
    const d = S.deklaration(state.deklaration);
    const justering = d.blanketter.map(n => blockMed(n)[0])
      .find(b => b && S.SUMMERING[b.namn]);
    if (!justering) return;

    for (const { fran, till } of overforing) {
      const varde = schema.varden.get(fran);
      /* Ett handpåskrivet värde rörs inte. */
      if (justering.varden.has(till) && !justering.kallor.has(till)) continue;
      if (varde === undefined) {
        if (justering.kallor.has(till)) {
          justering.varden.delete(till);
          justering.kallor.delete(till);
        }
        continue;
      }
      justering.varden.set(till, varde);
      justering.kallor.set(till, 'räkenskapsschemat');
    }

    /* Pensionskostnaderna är en upplysningsrad som behövs för särskild
       löneskatt. Kontogruppen är pensionskostnader i BAS, men kopplingen står
       inte i någon officiell tabell, så den märks som härledd. */
    const pension = S.pensionskostnader(state.rader);
    const pensionKod = S.faltkod(justering.namn, '8022') ? '8022' : null;
    if (pensionKod && pension
        && (!justering.varden.has(pensionKod) || justering.kallor.has(pensionKod))) {
      justering.varden.set(pensionKod, pension);
      justering.kallor.set(pensionKod, 'härlett ur 74xx');
    }
    summeraBlock(justering);
    huvudblankett();
  }

  /**
   * De två tal huvudblanketten hämtar från justeringssidan.
   *
   * Blanketten skriver ut vart de ska: INK2S 4.15 "flyttas till p. 1.1 på
   * sid. 1", och 4.16 till p. 1.2. Resten av förstasidan — riskskatt,
   * underlaget för särskild löneskatt, de utländska försäkringarna — är egna
   * beräkningar som varken bokföringen eller de andra blanketterna innehåller.
   *
   * @returns {{block: Object, koder: string[]}|null} blocket som skrevs om
   */
  function huvudblankett() {
    const regel = S.HUVUDBLANKETT[state.deklaration];
    if (!regel) return null;
    const kalla = blockMed(regel.fran)[0];
    const mal = blockMed(regel.blankett)[0];
    if (!kalla || !mal) return null;
    for (const { fran, till } of regel.poster) {
      /* Ett handpåskrivet värde rörs inte. */
      if (mal.varden.has(till) && !mal.kallor.has(till)) continue;
      const varde = kalla.varden.get(fran);
      if (varde === undefined) {
        mal.varden.delete(till);
        mal.kallor.delete(till);
      } else {
        mal.varden.set(till, varde);
        mal.kallor.set(till, 'justeringarna');
      }
    }
    return { block: mal, koder: regel.poster.map(p => p.till) };
  }

  /** Räkna om en justeringssidas sista rad. */
  function summeraBlock(block) {
    const par = S.SUMMERING[block.namn];
    if (!par) return;
    const svar = S.summera(block.namn, block.varden);
    for (const kod of [par.overskott, par.underskott]) {
      if (block.kallor.get(kod) === 'summa') {
        block.varden.delete(kod);
        block.kallor.delete(kod);
      }
    }
    if (!svar || !svar.belopp) return;
    /* Ett handpåskrivet värde på summaraden får stå kvar. */
    if (block.varden.has(svar.kod) && !block.kallor.has(svar.kod)) return;
    block.varden.set(svar.kod, svar.belopp);
    block.kallor.set(svar.kod, 'summa');
  }

  /** Uppgifter som går att läsa ur bokföringen snarare än att fråga om. */
  function forifyll() {
    const book = state.book;
    if (!book) return;
    const set = (id, v) => { const el = $(id); if (el && !el.value && v) el.value = v; };
    set('sru-orgnr', book.orgnr || '');
    set('sru-namn', book.foretagsnamn || '');
    set('lev-orgnr', book.orgnr || '');
    set('lev-namn', book.foretagsnamn || '');

    fyllDatum();
    /* Perioden följer räkenskapsårets sista dag: ett bokslut per den 30 juni
       2026 hör till 2026P2. */
    ritaPerioder();
  }

  /**
   * Räkenskapsårets början och slut på varje blankett som har koderna.
   *
   * Nästan varje blankett i utgåvan bär 7011 och 7012, och det är samma två
   * datum på alla — att fråga en gång per blankett vore att fråga om samma
   * sak trettio gånger. Ett block som bara bär sitt räkenskapsår räknas
   * däremot inte som ifyllt och kommer inte med i filen.
   */
  function fyllDatum() {
    const book = state.book;
    if (!book || !book.rakenskapsar) return;
    const iso = (v) => String(v || '').replace(/-/g, '');
    const datum = [[S.DATUMKODER[0], iso(book.rakenskapsar.from)],
                   [S.DATUMKODER[1], iso(book.rakenskapsar.tom)]];
    for (const block of state.block) {
      for (const [kod, varde] of datum) {
        if (!varde || !S.faltkod(block.namn, kod)) continue;
        /* Ett handpåskrivet datum står kvar. */
        if (block.varden.has(kod) && !block.kallor.has(kod)) continue;
        block.varden.set(kod, varde);
        block.kallor.set(kod, 'bokföringen');
      }
    }
  }

  /** Värden utöver räkenskapsåret — det som gör blanketten värd att lämna. */
  function egnaVarden(block) {
    let n = 0;
    for (const kod of block.varden.keys()) if (!S.DATUMKODER.includes(kod)) n++;
    return n;
  }

  // ── Rendering ─────────────────────────────────────────────────────────────

  function rita() {
    ritaKalla();
    ritaPeriodnot();
    ritaBlanketter();
    ritaOkopplade();
    ritaKontroll();
  }

  function ritaKalla() {
    const box = $('sru-kalla');
    if (!box) return;
    const book = state.book;
    if (!book) { box.hidden = true; return; }
    box.hidden = false;
    box.innerHTML = `
      <dl class="ar-facts">
        <dt>Källa</dt><dd>${kvotEscapeHtml(book.kalla)}${book.program
          ? ' — ' + kvotEscapeHtml(book.program) : ''}
          <span class="ar-note-inline">(${kvotEscapeHtml(book.kodning || '')})</span></dd>
        <dt>Företag</dt><dd>${kvotEscapeHtml(book.foretagsnamn || '—')}
          ${kvotEscapeHtml(book.orgnr || '')}</dd>
        <dt>Räkenskapsår</dt><dd>${book.rakenskapsar
          ? kvotEscapeHtml(book.rakenskapsar.from + ' – ' + book.rakenskapsar.tom) : '—'}</dd>
        <dt>Konton med saldo</dt><dd>${state.rader.length}</dd>
      </dl>`;
  }

  function ritaBlanketter() {
    const box = $('sru-blanketter');
    if (!box) return;
    const d = S.deklaration(state.deklaration);
    const egna = d ? d.blanketter : [];

    box.innerHTML = state.block.map(block => {
      const def = S.blankett(block.namn);
      if (!def) return '';
      const schema = d && block.namn === d.rakenskapsschema;
      const flera = blockMed(block.namn).length > 1;

      const rader = def.falt.map(falt => {
        const varde = block.varden.has(falt.kod) ? block.varden.get(falt.kod) : '';
        const kalla = block.kallor.get(falt.kod) || (varde !== '' ? 'ifyllt' : '');
        const punkt = /^(\d+\.\d+|[A-Z]\d+|R\d+)\s/.exec(falt.text);
        return `<tr${falt.obl ? ' class="sru-obl"' : ''}>
          <td class="sru-kod">${kvotEscapeHtml(falt.kod)}</td>
          <td class="sru-punkt">${punkt ? kvotEscapeHtml(punkt[1]) : ''}</td>
          <td>${kvotEscapeHtml(falt.text.replace(/^(\d+\.\d+|[A-Z]\d+|R\d+)\s/, '')
            .replace(/\s+/g, ' '))}${falt.obl ? ' <b title="Obligatorisk">*</b>' : ''}
            ${falt.tecken === '-' ? '<span class="ar-note-inline">(minus förtryckt)</span>'
              : falt.tecken === '+' ? '<span class="ar-note-inline">(plus förtryckt)</span>' : ''}</td>
          <td class="belopp"><input type="text" value="${kvotEscapeHtml(String(varde))}"
            data-block="${block.id}" data-kod="${kvotEscapeHtml(falt.kod)}"
            data-on-input="sru:falt" aria-label="${kvotEscapeHtml(falt.kod)}"></td>
          <td class="ar-note-inline">${kvotEscapeHtml(kalla)}</td>
        </tr>`;
      }).join('');

      const om = S.beskrivning(block.namn);
      const ifyllda = egnaVarden(block);

      return `<details class="sru-blankett"${schema || ifyllda ? ' open' : ''}>
        <summary><b>${kvotEscapeHtml(block.namn)}</b>${om
            ? `<span class="sru-titel">${kvotEscapeHtml(om.titel)}</span>` : ''}${flera
            ? `<span class="sru-nummer">block ${blockMed(block.namn).indexOf(block) + 1}`
              + ` av ${blockMed(block.namn).length}</span>` : ''}
          ${egna.includes(block.namn) && !flera ? '' :
            `<button type="button" class="ar-btn sru-ta-bort" data-on-click="sru:ta-bort"
               data-block="${block.id}">Ta bort</button>`}
          <div class="ar-note-inline sru-om">${om ? kvotEscapeHtml(om.om) + ' — ' : ''}
            ${kvotEscapeHtml(def.skv)} · ${def.falt.length} fältkoder ·
            ${ifyllda} ifyll${ifyllda === 1 ? 'd' : 'da'}${ifyllda
              ? '' : ' · kommer inte med i filen'}${schema
              ? ' · fylls ur bokföringen' : ''}</div></summary>
        <div class="ar-table-wrap"><table class="ar-table sru-falt">
          <thead><tr><th>Fältkod</th><th>Punkt</th><th>Benämning</th>
            <th class="belopp">Värde</th><th>Källa</th></tr></thead>
          <tbody>${rader}</tbody>
        </table></div>
      </details>`;
    }).join('');

    ritaValjaren();
  }

  /**
   * Blanketterna som kan bli aktuella för den valda inlämningen.
   *
   * Två steg. En blankett som hör till en *annan* deklaration hör inte hit —
   * INK3R har inget med ett aktiebolag att göra. Av de återstående visas de
   * som lämnas av samma krets: ett aktiebolag har inte K6 att lämna, och en
   * enskild näringsidkare har inte N9.
   *
   * Indelningen är en hjälp att hitta rätt, inte en regel om vad som får
   * lämnas — därför finns valet att visa alla ändå.
   *
   * @returns {{egna: string[], nara: string[], ovriga: string[]}}
   */
  function valjbara() {
    const d = S.deklaration(state.deklaration);
    const egna = d ? d.blanketter.slice() : [];
    const andras = new Set();
    for (const annan of D.DEKLARATIONER) {
      if (annan.id === state.deklaration) continue;
      for (const namn of annan.blanketter) andras.add(namn);
    }
    for (const namn of egna) andras.delete(namn);

    const nara = [];
    const ovriga = [];
    for (const namn of Object.keys(D.BLANKETTER).sort()) {
      if (egna.includes(namn)) continue;
      const om = S.beskrivning(namn);
      const hor = om && !andras.has(namn)
        && (om.vem === 'bada' || om.vem === (d ? d.krets : ''));
      (hor ? nara : ovriga).push(namn);
    }
    return { egna, nara, ovriga };
  }

  /** Fyll väljaren på nytt. Den beror på steg 1 och ritas därför om. */
  function ritaValjaren() {
    const valj = $('sru-lagg-till');
    if (!valj) return;
    const d = S.deklaration(state.deklaration);
    const { egna, nara, ovriga } = valjbara();
    const rad = (namn) => {
      const om = S.beskrivning(namn);
      return `<option value="${namn}">${kvotEscapeHtml(namn)}${om
        ? ' — ' + kvotEscapeHtml(om.titel) : ''}</option>`;
    };
    const grupp = (etikett, namn) => namn.length
      ? `<optgroup label="${kvotEscapeHtml(etikett)}">${namn.map(rad).join('')}</optgroup>`
      : '';
    valj.innerHTML = '<option value="">Lägg till blankett…</option>'
      + grupp(d ? d.namn : 'Inlämningen', egna)
      + grupp('Bilagor som kan höra till', nara)
      + (state.visaAlla ? grupp('Övriga blanketter i utgåvan', ovriga) : '');

    const not = $('sru-valj-not');
    if (not) {
      not.textContent = state.visaAlla
        ? `Alla ${Object.keys(D.BLANKETTER).length} blankettblock i utgåvan visas.`
        : `${egna.length + nara.length} av ${Object.keys(D.BLANKETTER).length} blankettblock `
          + `visas — de som hör till ${d ? d.namn : 'inlämningen'}.`;
    }
  }

  /**
   * Skriv om enstaka rader utan att röra resten.
   *
   * Att rita hela tabellen vid varje tangenttryckning skulle flytta markören
   * ur fältet man skriver i, och summan ska ändå följa med direkt.
   *
   * @param {Object} block
   * @param {string[]} koder
   */
  function ritaVarden(block, koder) {
    const box = $('sru-blanketter');
    if (!box) return;
    for (const kod of koder) {
      const falt = box.querySelector(`input[data-kod="${kod}"][data-block="${block.id}"]`);
      if (!falt) continue;
      const varde = block.varden.has(kod) ? String(block.varden.get(kod)) : '';
      falt.value = varde;
      const rad = falt.closest('tr');
      if (rad) rad.lastElementChild.textContent = block.kallor.get(kod)
        || (varde ? 'ifyllt' : '');
    }
  }

  function ritaOkopplade() {
    const box = $('sru-okopplade');
    if (!box) return;
    const kvar = state.okopplade.filter(r => (r.typ === 'resultat' ? r.res : r.ub));
    if (!kvar.length) { box.hidden = true; return; }
    box.hidden = false;
    box.innerHTML = `<ul class="ar-problem"><li>${kvar.length}
      konto${kvar.length === 1 ? '' : 'n'} med saldo saknar koppling i BAS tabell och
      räknas inte med: ${kvotEscapeHtml(kvar.map(r => r.konto + ' ' + r.namn).join(', '))}</li></ul>`;
  }

  function ritaKontroll() {
    const box = $('sru-kontroll');
    if (!box) return;
    const blanketter = aktivaBlanketter();
    if (!blanketter.length) {
      box.innerHTML = '<p class="ar-empty">Inga ifyllda blanketter ännu.</p>';
      return;
    }
    const utfall = S.kontrollera(blanketter);
    const summering = `${utfall.filter(u => u.niva === 'error').length} fel · `
      + `${utfall.filter(u => u.niva === 'warn').length} varningar · `
      + `${utfall.filter(u => u.niva === 'info').length} noteringar`;
    box.innerHTML = `<p class="ar-note-inline">${kvotEscapeHtml(summering)}</p>`
      + (utfall.length ? utfall.map(u => `
        <div class="ar-finding ar-${u.niva}">
          <span class="ar-badge">${u.niva === 'error' ? 'Fel'
            : u.niva === 'warn' ? 'Varning' : 'Info'}</span>
          <div><div class="ar-finding-title">${kvotEscapeHtml(u.text)}</div></div>
        </div>`).join('')
      : '<p class="ar-ok-mark">Inget att anmärka på i det som går att kontrollera här.</p>');
  }

  /**
   * Blanketterna som faktiskt har något att lämna.
   *
   * Räkenskapsåret ensamt räknas inte: det fylls i på varje blankett som har
   * koderna, och ett block som bara bär sina två datum har inget att säga.
   */
  function aktivaBlanketter() {
    return state.block
      .filter(b => egnaVarden(b))
      .map(b => ({ namn: b.namn, period: state.period, varden: b.varden }));
  }

  // ── Filerna ───────────────────────────────────────────────────────────────

  function bygg() {
    const ident = {
      orgnr: ($('sru-orgnr') || {}).value || '',
      namn: ($('sru-namn') || {}).value || '',
    };
    const lev = {
      orgnr: ($('lev-orgnr') || {}).value || ident.orgnr,
      namn: ($('lev-namn') || {}).value || ident.namn,
      adress: ($('lev-adress') || {}).value || '',
      postnr: ($('lev-postnr') || {}).value || '',
      postort: ($('lev-postort') || {}).value || '',
      kontakt: ($('lev-kontakt') || {}).value || '',
      email: ($('lev-email') || {}).value || '',
      telefon: ($('lev-telefon') || {}).value || '',
    };
    const blanketter = aktivaBlanketter();
    const brister = [];
    if (!ident.orgnr) brister.push('Organisationsnummer för den deklarationen avser saknas.');
    if (!lev.namn) brister.push('Uppgiftslämnarens namn saknas.');
    if (!lev.postnr) brister.push('Uppgiftslämnarens postnummer saknas.');
    if (!lev.postort) brister.push('Uppgiftslämnarens postort saknas.');
    if (!blanketter.length) brister.push('Ingen blankett har några värden.');
    return { info: S.infoSru(lev), blanketter: S.blanketterSru(blanketter, ident), brister };
  }

  function ritaFiler(filer) {
    const box = $('sru-filer');
    if (!box) return;
    box.hidden = false;
    box.innerHTML = `
      <div class="ar-code-head"><h4>INFO.SRU</h4></div>
      <pre class="ar-code">${kvotEscapeHtml(filer.info)}</pre>
      <div class="ar-code-head"><h4>BLANKETTER.SRU</h4></div>
      <pre class="ar-code">${kvotEscapeHtml(filer.blanketter)}</pre>`;
  }

  // ── Handlingar ────────────────────────────────────────────────────────────

  registerActions({
    'sru:deklaration': (event, element) => {
      state.deklaration = element.value;
      fyllListan(state.deklaration);
      rakna();
      forifyll();
      rita();
    },

    'sru:period': (event, element) => {
      element.dataset.rord = '1';
      state.period = element.value;
      ritaPeriodnot();
    },

    'sru:pick': () => $('sru-file-input').click(),

    'sru:pick-key': (event) => {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      event.preventDefault();
      $('sru-file-input').click();
    },

    'sru:fil': (event) => lasSie(event.target.files && event.target.files[0]),

    'sru:falt': (event, element) => {
      const block = state.block.find(b => String(b.id) === element.dataset.block);
      if (!block) return;
      const kod = element.dataset.kod;
      const text = element.value.trim();
      if (!text) block.varden.delete(kod);
      else block.varden.set(kod, text);
      /* Röra vid ett fält gör det till en egen uppgift, inte en avläsning. */
      block.kallor.delete(kod);
      const cell = element.closest('tr');
      if (cell) cell.lastElementChild.textContent = text ? 'ifyllt' : '';
      /* Summan följer med direkt — den är en följd av det som står ovanför,
         och att behöva trycka på något för att se den vore att be någon räkna
         efter i huvudet. Detsamma gäller huvudblankettens 1.1 och 1.2, som
         bara är justeringssidans sista rad flyttad dit blanketten hänvisar. */
      if (S.SUMMERING[block.namn]) {
        summeraBlock(block);
        const par = S.SUMMERING[block.namn];
        ritaVarden(block, [par.overskott, par.underskott]);
        const huvud = huvudblankett();
        if (huvud) ritaVarden(huvud.block, huvud.koder);
      }
      ritaKontroll();
    },

    'sru:lagg-till': (event, element) => {
      const namn = element.value;
      element.value = '';
      if (!namn || !S.blankett(namn)) return;
      state.block.push(nyttBlock(namn));
      fyllDatum();
      rita();
      const om = S.beskrivning(namn);
      notifyUser(`${namn}${om ? ' — ' + om.titel : ''} tillagd. Flera block av samma `
        + 'blankett går att lägga till — delägaruppgifter lämnas ett block per delägare.',
        { tone: 'success' });
    },

    'sru:alla': (event, element) => {
      state.visaAlla = !!element.checked;
      ritaValjaren();
    },

    'sru:ta-bort': (event, element) => {
      state.block = state.block.filter(b => String(b.id) !== element.dataset.block);
      rita();
    },

    'sru:importera': () => $('sru-import-input').click(),

    'sru:import-fil': async (event) => {
      const file = event.target.files && event.target.files[0];
      event.target.value = '';
      if (!file) return;
      const bytes = new Uint8Array(await file.arrayBuffer());
      const last = S.lasBlanketterSru(bytes);
      if (last.fel.length && !last.block.length) {
        return showFailureBanner(last.fel[0], 'error');
      }
      /*
        Ett inläst block fyller ett tomt block av samma sort om det finns ett,
        och läggs annars till. Utan det första fick man ett tomt INK2R bredvid
        det inlästa, och två block av samma blankett i filen är en dubblett
        som Skatteverket inte vill ha. Utan det andra gick det inte att läsa
        in flera delägaruppgifter.
      */
      for (const b of last.block) {
        const tomt = state.block.find(x => x.namn === b.namn && !egnaVarden(x));
        if (tomt) { tomt.varden = b.varden; tomt.kallor = new Map(); }
        else state.block.push(nyttBlock(b.namn, b.varden));
      }
      fyllDatum();
      if (last.block[0] && last.block[0].period) {
        const valj = $('sru-period');
        if (valj) {
          valj.dataset.rord = '1';
          if (![...valj.options].some(o => o.value === last.block[0].period)) {
            valj.insertAdjacentHTML('afterbegin',
              `<option value="${last.block[0].period}">${last.block[0].period}</option>`);
          }
          valj.value = last.block[0].period;
          state.period = valj.value;
        }
      }
      if (last.identitet) {
        const set = (id, v) => { const el = $(id); if (el && !el.value && v) el.value = v; };
        set('sru-orgnr', last.identitet.orgnr);
        set('sru-namn', last.identitet.namn);
      }
      rita();
      notifyUser(`${last.block.length} blankettblock inlästa ur ${file.name}.`,
                 { tone: 'success' });
      if (last.fel.length) showFailureBanner(last.fel[0], 'error');
    },

    'sru:bygg': () => {
      const filer = bygg();
      if (filer.brister.length) {
        showFailureBanner(filer.brister[0], 'error');
        return;
      }
      state.filer = filer;
      ritaFiler(filer);
      for (const id of ['sru-hamta-info', 'sru-hamta-blanketter']) {
        const knapp = $(id);
        if (knapp) knapp.disabled = false;
      }
    },

    'sru:hamta-info': () => hamta('INFO.SRU', state.filer && state.filer.info),
    'sru:hamta-blanketter': () => hamta('BLANKETTER.SRU', state.filer && state.filer.blanketter),

    'sru:rensa': () => {
      state.book = null; state.rader = []; state.okopplade = [];
      state.block = []; state.filer = null;
      fyllListan(state.deklaration);
      if ($('sru-file-input')) $('sru-file-input').value = '';
      if ($('sru-filer')) $('sru-filer').hidden = true;
      for (const id of ['sru-hamta-info', 'sru-hamta-blanketter']) {
        const knapp = $(id);
        if (knapp) knapp.disabled = true;
      }
      rita();
    },
  });

  /*
    Filerna ska vara ISO 8859-1 och heta precis INFO.SRU och BLANKETTER.SRU —
    döps de om fungerar inte överföringen, vilket Skatteverket säger rakt ut.
  */
  function hamta(namn, text) {
    if (!text) return;
    KVOT_ARSRED_EXPORT.saveAs(
      new Blob([S.latin1(text)], { type: 'text/plain' }), namn);
  }

  function mountDropZone() {
    const zone = $('sru-drop');
    if (!zone) return;
    for (const type of ['dragenter', 'dragover']) {
      zone.addEventListener(type, (e) => { e.preventDefault(); zone.classList.add('dragging'); });
    }
    for (const type of ['dragleave', 'drop']) {
      zone.addEventListener(type, (e) => { e.preventDefault(); zone.classList.remove('dragging'); });
    }
    zone.addEventListener('drop', (event) => {
      const file = event.dataTransfer && event.dataTransfer.files && event.dataTransfer.files[0];
      if (file) lasSie(file).catch(error => reportFailure('sru.drop', error));
    });
  }

  function init() {
    const valj = $('sru-deklaration');
    if (valj) {
      valj.innerHTML = D.DEKLARATIONER.map(d =>
        `<option value="${d.id}">${kvotEscapeHtml(d.namn)} — ${kvotEscapeHtml(d.vem)}</option>`)
        .join('');
      state.deklaration = valj.value;
    }
    ritaPerioder();
    fyllListan(state.deklaration);
    mountDropZone();
    rita();
  }

  return { init, state, bygg, rakna, perioder };
})();
