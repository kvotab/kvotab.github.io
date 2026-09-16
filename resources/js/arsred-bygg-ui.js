/* ==========================================================================
   arsred-bygg-ui.js — gränssnittet för del A, att skapa handlingen

   Skild från arsred-bygg.js av samma skäl som resten av sajten skiljer på
   räkning och ritning: uppställningen går att köra och testa utan en sida
   omkring sig, och den har testats så, mot en riktig SIE-fil.

   Det som är värt att veta om formen: kontokopplingen visas alltid, även när
   förslaget är rätt. Det finns ingen officiell tabell från BAS-konto till
   taxonomielement, så förslaget är en kvalificerad gissning om var pengarna
   hör hemma, och en gissning som ingen ser är en gissning ingen kan rätta.
   ========================================================================== */

const KVOT_ARSRED_BYGG_UI = (() => {
  'use strict';

  const B = KVOT_ARSRED_BYGG;
  const T = KVOT_ARSRED_TAXONOMI;
  const $ = (id) => document.getElementById(id);

  const state = {
    book: null,          // bokföringen, från SIE eller CSV
    rows: [],            // konton med sin koppling
    omforingar: [],      // vad som flyttats automatiskt, och varför
    statements: null,    // uppställningen
    ixbrl: '',           // senast genererade handlingen
    filnamn: '',
  };

  /* Elementen ett konto kan kopplas till, i uppställningens ordning. */
  const VALBARA = (() => {
    const groups = [['Resultaträkning', T.IS], ['Balansräkning', T.BS]];
    return groups.map(([title, layout]) => [title, layout.filter(row => !row.a)]);
  })();

  // ── Läsa in ───────────────────────────────────────────────────────────────

  async function loadFile(file) {
    if (!file) return;
    const tooLarge = kvotFileTooLarge(file, 64 * 1024 * 1024);
    if (tooLarge.tooLarge) return showFailureBanner(tooLarge.reason, 'error');

    const bytes = new Uint8Array(await file.arrayBuffer());
    const sie = /\.si(e|\d)?$/i.test(file.name) || file.name.toLowerCase().endsWith('.se');

    if (sie) {
      const { text, encoding } = B.decodeSie(bytes);
      state.book = B.parseSie(text);
      state.book.kodning = encoding;
    } else {
      /* Spiris skriver sina CSV-exporter som UTF-8 med BOM. */
      const text = new TextDecoder('utf-8').decode(bytes).replace(/^﻿/, '');
      state.book = B.parseSpirisCsv(text, state.book && state.book.kalla !== 'SIE'
        ? state.book : undefined);
      state.book.kodning = 'UTF-8';
    }

    state.rows = B.accounts(state.book);
    state.omforingar = B.reclassify(state.rows);
    recompute();
    prefill();
    render();
  }

  function recompute() {
    state.statements = state.rows.length ? B.statements(state.rows) : null;
  }

  /** Fyll formuläret med det bokföringen redan svarar på. */
  function prefill() {
    const book = state.book;
    if (!book) return;
    const set = (id, value, kalla = 'bokforing') => {
      const el = $(id);
      if (!el || el.value) return;
      el.value = value;
      KVOT_ARSRED_KALLA.satt(id, kalla);
    };
    set('bygg-orgnr', book.orgnr || '');
    set('bygg-foretagsnamn', book.foretagsnamn || '');
    if (book.rakenskapsar) {
      set('bygg-ar-from', book.rakenskapsar.from);
      set('bygg-ar-tom', book.rakenskapsar.tom);
    }
    if (book.foregaende) {
      set('bygg-fg-from', book.foregaende.from);
      set('bygg-fg-tom', book.foregaende.tom);
      /* Flerårsöversikten vill ha fyra år; bokföringsfilen bär två. De äldre
         årens datum härleds genom att flytta perioden ett och två år bakåt,
         vilket stämmer för ett bolag som inte lagt om sitt räkenskapsår — och
         syns i fälten, så att den som har lagt om det ser vad som antagits. */
      for (const steg of [1, 2]) {
        const index = steg + 1;
        set(`bygg-ar${index}-from`, skiftAr(book.foregaende.from, -steg), 'harlett');
        set(`bygg-ar${index}-tom`, skiftAr(book.foregaende.tom, -steg), 'harlett');
      }
    }
    /* Organisationsnumret hör hemma i del B också, och är detsamma. */
    const orgnrB = $('orgnr');
    if (orgnrB && !orgnrB.value && book.orgnr) {
      orgnrB.value = book.orgnr.replace('-', '');
      orgnrB.dispatchEvent(new Event('input', { bubbles: true }));
    }
    fyllResultatdisposition();
  }

  /**
   * Ett datum flyttat ett helt antal år.
   *
   * Dagen och månaden står stilla, vilket är rätt för ett räkenskapsår som
   * inte lagts om. Ett 29 februari som flyttas till ett år utan skottdag blir
   * 28 februari, vilket är den enda vettiga tolkningen.
   *
   * @param {string} iso - ÅÅÅÅ-MM-DD
   * @param {number} steg
   * @returns {string}
   */
  function skiftAr(iso, steg) {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(iso || ''));
    if (!m) return '';
    const year = Number(m[1]) + steg;
    const month = Number(m[2]);
    const dagarIManaden = new Date(year, month, 0).getDate();
    const day = Math.min(Number(m[3]), dagarIManaden);
    return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
  }

  /** Förslaget till disposition följer av balansräkningen. */
  function fyllResultatdisposition() {
    if (!state.statements) return;
    const bs = state.statements.bs;
    const balanserat = bs.get('BalanseratResultat') ?? 0;
    const arets = bs.get('AretsResultatEgetKapital') ?? 0;
    const summa = balanserat + arets;
    const set = (id, value) => {
      const el = $(id);
      if (!el || (el.value && el.dataset.auto !== '1')) return;
      el.value = value;
      el.dataset.auto = '1';
      KVOT_ARSRED_KALLA.satt(id, 'beraknat');
    };
    set('bygg-disp-balanserat', Math.round(balanserat));
    set('bygg-disp-arets', Math.round(arets));
    set('bygg-utdelning-under-aret', Math.round(beraknadUtdelning(state.statements)));
    const utdelning = Number($('bygg-disp-utdelning') && $('bygg-disp-utdelning').value) || 0;
    set('bygg-disp-nyrakning', Math.round(summa - utdelning));
    const summaEl = $('bygg-disp-summa');
    if (summaEl) summaEl.textContent = B.fmt(summa) + ' kr';
  }

  // ── Rendering ─────────────────────────────────────────────────────────────

  function render() {
    renderKalla();
    renderKoppling();
    renderUppstallning();
  }

  function renderKalla() {
    const box = $('bygg-kalla');
    if (!box) return;
    const book = state.book;
    if (!book) { box.hidden = true; return; }
    const konton = new Set([...book.ub.keys(), ...book.ubFg.keys(),
                            ...book.res.keys(), ...book.resFg.keys()]).size;
    box.hidden = false;
    box.innerHTML = `
      <dl class="ar-facts">
        <dt>Källa</dt><dd>${kvotEscapeHtml(book.kalla)}${book.program
          ? ' — ' + kvotEscapeHtml(book.program) : ''}
          ${book.kodning ? `<span class="ar-note-inline">(${kvotEscapeHtml(book.kodning)})</span>` : ''}</dd>
        <dt>Företag</dt><dd>${kvotEscapeHtml(book.foretagsnamn || '—')}
          ${kvotEscapeHtml(book.orgnr || '')}</dd>
        <dt>Räkenskapsår</dt><dd>${book.rakenskapsar
          ? kvotEscapeHtml(book.rakenskapsar.from + ' – ' + book.rakenskapsar.tom) : '—'}</dd>
        <dt>Föregående</dt><dd>${book.foregaende
          ? kvotEscapeHtml(book.foregaende.from + ' – ' + book.foregaende.tom)
          : 'saknas — jämförelseåret blir tomt'}</dd>
        <dt>Konton med saldo</dt><dd>${konton}</dd>
      </dl>
      ${book.varningar.length ? '<ul class="ar-problem">'
        + book.varningar.map(v => `<li>${kvotEscapeHtml(v)}</li>`).join('') + '</ul>' : ''}`;
  }

  function optionsFor(selected) {
    const groups = VALBARA.map(([title, rows]) => `<optgroup label="${title}">`
      + rows.map(row => `<option value="${row.n}"${row.n === selected ? ' selected' : ''}>`
          + `${kvotEscapeHtml(row.l)}</option>`).join('')
      + '</optgroup>').join('');
    return `<option value=""${selected ? '' : ' selected'}>— lämnas utanför —</option>` + groups;
  }

  function renderKoppling() {
    const box = $('bygg-koppling');
    if (!box) return;
    if (!state.rows.length) {
      box.innerHTML = '<p class="ar-empty">Ingen bokföring inläst ännu.</p>';
      return;
    }

    const utan = state.rows.filter(row => !row.element
      && (row.ub || row.ubFg || row.res || row.resFg));
    const rader = state.rows.map((row, index) => {
      const belopp = row.typ === 'resultat' ? row.res : row.ub;
      const beloppFg = row.typ === 'resultat' ? row.resFg : row.ubFg;
      return `<tr${row.element ? '' : ' class="bygg-okopplad"'}>
        <td>${kvotEscapeHtml(row.konto)}</td>
        <td>${kvotEscapeHtml(row.namn)}</td>
        <td class="belopp">${B.fmt(belopp)}</td>
        <td class="belopp">${B.fmt(beloppFg)}</td>
        <td><select data-index="${index}" data-on-change="bygg:koppla"
              aria-label="Element för konto ${kvotEscapeHtml(row.konto)}">
          ${optionsFor(row.element)}</select></td>
      </tr>`;
    }).join('');

    box.innerHTML = `
      ${state.omforingar.length ? '<ul class="ar-problem ar-info-list">'
        + state.omforingar.map(n => `<li>${kvotEscapeHtml(n)}</li>`).join('') + '</ul>' : ''}
      ${utan.length ? `<ul class="ar-problem"><li>${utan.length} konto${utan.length === 1 ? '' : 'n'}
        med saldo saknar koppling och räknas inte med:
        ${kvotEscapeHtml(utan.map(r => r.konto + ' ' + r.namn).join(', '))}</li></ul>` : ''}
      <div class="ar-table-wrap"><table class="ar-table bygg-konton">
        <thead><tr><th>Konto</th><th>Namn</th><th class="belopp">Saldo</th>
          <th class="belopp">Fg år</th><th>Post i årsredovisningen</th></tr></thead>
        <tbody>${rader}</tbody>
      </table></div>`;
  }

  function renderUppstallning() {
    const box = $('bygg-uppstallning');
    if (!box) return;
    if (!state.statements) { box.innerHTML = ''; return; }
    const s = state.statements;

    const table = (layout, nu, fg, title, head) => {
      const keep = new Set();
      layout.forEach((row, i) => {
        if (row.a || (!nu.has(row.n) && !fg.has(row.n))) return;
        keep.add(i);
        let depth = row.d;
        for (let j = i - 1; j >= 0 && depth > 0; j--) {
          if (layout[j].d < depth) { keep.add(j); depth = layout[j].d; }
        }
      });
      const body = layout.map((row, i) => {
        if (!keep.has(i)) return '';
        const pad = `padding-left:${Math.max(0, row.d - 1) * 14}px`;
        if (row.a) return `<tr><th colspan="3" style="${pad}">${kvotEscapeHtml(row.l)}</th></tr>`;
        return `<tr><td style="${pad}">${kvotEscapeHtml(row.l)}</td>`
          + `<td class="belopp">${nu.has(row.n) ? B.fmt(nu.get(row.n)) : ''}</td>`
          + `<td class="belopp">${fg.has(row.n) ? B.fmt(fg.get(row.n)) : ''}</td></tr>`;
      }).join('');
      return `<h4>${title}</h4><div class="ar-table-wrap"><table class="ar-table bygg-uppst">
        <thead><tr><th></th><th class="belopp">${kvotEscapeHtml(head[0])}</th>
          <th class="belopp">${kvotEscapeHtml(head[1])}</th></tr></thead>
        <tbody>${body}</tbody></table></div>`;
    };

    const ar = state.book.rakenskapsar || { from: '', tom: '' };
    const fg = state.book.foregaende || { from: '', tom: '' };
    box.innerHTML =
      (s.avvikelser.length
        ? '<ul class="ar-problem">' + s.avvikelser.map(a => `<li>${kvotEscapeHtml(a)}</li>`).join('')
          + '</ul>'
        : '<p class="ar-ok-mark">Uppställningen går ihop: balansräkningen balanserar och '
          + 'årets resultat är detsamma i båda räkningarna.</p>')
      + table(T.IS, s.is, s.isFg, 'Resultaträkning', [ar.from + ' – ' + ar.tom, fg.from + ' – ' + fg.tom])
      + table(T.BS, s.bs, s.bsFg, 'Balansräkning', [ar.tom, fg.tom]);
  }

  // ── Modellen som skrivs ut ────────────────────────────────────────────────

  function value(id) { const el = $(id); return el ? el.value.trim() : ''; }
  function number(id) {
    const el = $(id);
    const parsed = Number(String(el ? el.value : '').replace(/\s/g, '').replace(',', '.'));
    return Number.isFinite(parsed) ? parsed : undefined;
  }

  function underskrifter() {
    return [...document.querySelectorAll('#bygg-underskrifter .bygg-person')].map(block => ({
      tilltalsnamn: (block.querySelector('.bygg-tilltalsnamn') || {}).value || '',
      efternamn: (block.querySelector('.bygg-efternamn') || {}).value || '',
      roll: (block.querySelector('.bygg-roll') || {}).value || '',
    })).filter(person => person.efternamn);
  }

  /**
   * Soliditet enligt den vanliga definitionen för K2.
   *
   * Obeskattade reserver räknas till 78,6 procent som eget kapital, alltså
   * efter avdrag för den uppskjutna skatt de bär. Satsen är bolagsskatten;
   * ändras den ändras nyckeltalet, vilket är varför den står här synligt och
   * inte gömd i ett uttryck.
   */
  const SKATTESATS = 0.206;

  function soliditet(bs) {
    const eget = bs.get('EgetKapital') || 0;
    const reserver = bs.get('ObeskattadeReserver') || 0;
    const summa = bs.get('Tillgangar') || 0;
    if (!summa) return undefined;
    return Math.round(((eget + reserver * (1 - SKATTESATS)) / summa) * 1000) / 10;
  }

  /**
   * Kortnamn för en räkenskapsperiod, som i en flerårsöversikt.
   *
   * Ett brutet år skrivs 2025/26, ett kalenderår bara med sitt årtal.
   *
   * @param {{from: string, tom: string}} period
   * @returns {string}
   */
  function periodEtikett(period) {
    const from = String(period.from || '');
    const tom = String(period.tom || '');
    if (!from || !tom) return tom || from;
    return from.slice(0, 4) === tom.slice(0, 4) ? tom.slice(0, 4)
      : `${from.slice(0, 4)}/${tom.slice(2, 4)}`;
  }

  /**
   * Den utdelning årsstämman beslutade under året.
   *
   * Står inte som en egen post någonstans, men går att räkna ut: det ingående
   * balanserade resultatet plus föregående års vinst, minus det utgående
   * balanserade resultatet, är det som lämnat eget kapital. För de allra
   * flesta mindre bolag är det utdelningen. Har något annat rört sig där —
   * aktieägartillskott, fondemission — hamnar det i samma differens, och då
   * behöver siffran rättas för hand. Därför är fältet ifyllt, inte låst.
   *
   * @param {Object} s - uppställningen
   * @returns {number}
   */
  function beraknadUtdelning(s) {
    const g = (map, name) => map.get(name) ?? 0;
    return g(s.bsFg, 'BalanseratResultat') + g(s.bsFg, 'AretsResultatEgetKapital')
      - g(s.bs, 'BalanseratResultat');
  }

  /* Kolumnerna i förändringen av eget kapital, i uppställningens ordning.
     Totalt står sist och är summan av de andra. */
  const EK_KOLUMNER = ['Aktiekapital', 'Reservfond', 'Overkursfond',
                       'BalanseratResultat', 'AretsResultatEgetKapital'];

  /**
   * Förändringen av eget kapital som en färdig matris.
   *
   * @param {Object} s - uppställningen
   * @param {number} utdelning
   * @returns {Object|null}
   */
  function egetKapitalMatris(s, utdelning) {
    if (!s) return null;
    const g = (map, name) => map.get(name) ?? 0;
    /* En kolumn tas med bara om den bär något: en balansräkning utan
       reservfond ska inte visa en tom kolumn för den. */
    const kolumner = EK_KOLUMNER.filter(name => g(s.bs, name) || g(s.bsFg, name));
    kolumner.push('ForandringEgetKapitalTotalt');

    const celler = (hamta) => {
      const out = {};
      for (const name of kolumner) {
        out[name] = { v: name === 'ForandringEgetKapitalTotalt' ? hamta('EgetKapital') : hamta(name) };
      }
      return out;
    };

    const ingArets = g(s.bsFg, 'AretsResultatEgetKapital');
    const arets = g(s.bs, 'AretsResultatEgetKapital');
    const tom = () => Object.fromEntries(kolumner.map(name => [name, {}]));

    const disposition = tom();
    disposition.BalanseratResultat = { v: ingArets };
    disposition.AretsResultatEgetKapital = { v: ingArets, minus: true };
    disposition.ForandringEgetKapitalTotalt = { v: 0 };

    const utdelningsrad = tom();
    utdelningsrad.BalanseratResultat = { v: Math.abs(utdelning), minus: utdelning > 0 };
    utdelningsrad.ForandringEgetKapitalTotalt = { v: Math.abs(utdelning), minus: utdelning > 0 };

    const aretsrad = tom();
    aretsrad.AretsResultatEgetKapital = { v: arets };
    aretsrad.ForandringEgetKapitalTotalt = { v: arets };

    const rader = [
      { label: 'Belopp vid årets ingång', year: 1, celler: celler(n => g(s.bsFg, n)) },
    ];
    if (ingArets) {
      rader.push({ label: 'Disposition enligt beslut av årsstämman', year: 0,
                   suffix: 'BalanserasNyRakning', celler: disposition });
    }
    if (utdelning) {
      rader.push({ label: 'Utdelning', year: 0, suffix: 'Utdelning', celler: utdelningsrad });
    }
    rader.push({ label: 'Årets resultat', year: 0, suffix: 'AretsResultat', celler: aretsrad });
    rader.push({ label: 'Belopp vid årets utgång', year: 0, summa: true,
                 celler: celler(n => g(s.bs, n)) });
    return { kolumner, rader };
  }

  /** De extra åren i flerårsöversikten, så långt de är ifyllda. */
  function tidigareAr() {
    const out = [];
    for (const index of [2, 3]) {
      const from = value(`bygg-ar${index}-from`);
      const tom = value(`bygg-ar${index}-tom`);
      if (!from || !tom) continue;
      /* Fälten är i tusental, som i förra årets årsredovisning, medan modellen
         genomgående håller kronor och låter utskriften dela med tusen en gång.
         Utan omräkningen här delades de äldre årens belopp två gånger, och
         1 849 tkr blev 2. */
      const tkr = (id) => {
        const v = number(id);
        return v === undefined ? undefined : v * 1000;
      };
      out.push({ index, from, tom,
        Nettoomsattning: tkr(`bygg-ar${index}-netto`),
        ResultatEfterFinansiellaPoster: tkr(`bygg-ar${index}-resultat`),
        Soliditet: number(`bygg-ar${index}-soliditet`) });
    }
    return out;
  }

  function model() {
    const s = state.statements;
    const book = state.book;
    const ar = { from: value('bygg-ar-from'), tom: value('bygg-ar-tom') };
    const fg = value('bygg-fg-from') && value('bygg-fg-tom')
      ? { from: value('bygg-fg-from'), tom: value('bygg-fg-tom') } : null;

    const anstallda = number('bygg-anstallda');
    const anstalldaFg = number('bygg-anstallda-fg');
    const extra = tidigareAr();

    const flerarsoversikt = [
      /* Flerårsöversikten bär nettoomsättning, resultat efter finansiella
         poster och soliditet. Balansomslutning och medelantalet anställda
         hör hemma i balansräkningen respektive i not 2, inte här. */
      { ar: 0, rubrik: periodEtikett(ar), varden: {
        Nettoomsattning: s.is.get('Nettoomsattning'),
        ResultatEfterFinansiellaPoster: s.is.get('ResultatEfterFinansiellaPoster'),
        Soliditet: soliditet(s.bs) } },
    ];
    if (fg) {
      flerarsoversikt.push({ ar: 1, rubrik: periodEtikett(fg), varden: {
        Nettoomsattning: s.isFg.get('Nettoomsattning'),
        ResultatEfterFinansiellaPoster: s.isFg.get('ResultatEfterFinansiellaPoster'),
        Soliditet: soliditet(s.bsFg) } });
    }
    /* De äldre åren finns inte i bokföringsfilen och skrivs in för hand; de
       får egna kontexter i handlingen, numrerade efter sin plats. */
    extra.forEach((year, offset) => {
      flerarsoversikt.push({ ar: 2 + offset, rubrik: periodEtikett(year), varden: {
        Nettoomsattning: year.Nettoomsattning,
        ResultatEfterFinansiellaPoster: year.ResultatEfterFinansiellaPoster,
        Soliditet: year.Soliditet } });
    });

    const balanserat = number('bygg-disp-balanserat') ?? 0;
    const arets = number('bygg-disp-arets') ?? 0;
    const utdelning = number('bygg-disp-utdelning') ?? 0;
    const antalAktier = number('bygg-antal-aktier');
    const utdelningUnderAret = number('bygg-utdelning-under-aret') ?? 0;

    const intygDatum = value('bygg-intyg-arsstamma');
    return {
      orgnr: value('bygg-orgnr') || book.orgnr,
      foretagsnamn: value('bygg-foretagsnamn') || book.foretagsnamn,
      sate: value('bygg-sate'),
      rakenskapsar: ar,
      foregaende: fg,
      tidigareAr: extra.map(year => ({ from: year.from, tom: year.tom })),
      avgivande: value('bygg-avgivande') || 'styrelsen',
      verksamhet: value('bygg-verksamhet'),
      vasentligaHandelser: value('bygg-handelser'),
      flerarsoversikt,
      kommentarFlerarsoversikt: value('bygg-kommentar-flerar'),
      egetKapital: egetKapitalMatris(s, utdelningUnderAret),
      resultatdisposition: {
        balanserat, aretsResultat: arets, summa: balanserat + arets,
        utdelning, balanserasINyRakning: balanserat + arets - utdelning,
        antalAktier: antalAktier && antalAktier > 0 ? antalAktier : undefined,
      },
      yttrandeVinstutdelning: utdelning ? value('bygg-yttrande') : '',
      redovisningsprinciper: value('bygg-principer'),
      nyckeltalsdefinitioner: value('bygg-nyckeltal'),
      medelantalAnstallda: anstallda,
      medelantalAnstalldaFg: anstalldaFg,
      /* Fylls fältet inte i är innehållet rimligen klart vid stämman — och
         har ingen stämma hållits ännu, vid underskriften. Härledningen görs
         här och inte genom att skriva i fältet, så att det står tomt så länge
         ingen tagit ställning. */
      klartDatum: value('bygg-klart-datum') || intygDatum || value('bygg-datum'),
      ort: value('bygg-ort'),
      datum: value('bygg-datum'),
      underskrifter: underskrifter(),
      faststallelseintyg: intygDatum ? {
        datumArsstamma: intygDatum,
        tilltalsnamn: value('bygg-intyg-tilltalsnamn'),
        efternamn: value('bygg-intyg-efternamn'),
        roll: value('bygg-intyg-roll'),
        datum: value('bygg-intyg-datum') || intygDatum,
      } : null,
      is: s.is, isFg: s.isFg, bs: s.bs, bsFg: s.bsFg,
      programversion: '1',
    };
  }

  /**
   * Vad som fattas innan handlingen går att skriva ut.
   *
   * Varje brist bär fältets id, så att listan inte bara kan berätta vad som
   * saknas utan också visa var. En lista med åtta rader hjälper inte den som
   * inte hittar det åttonde fältet.
   *
   * @returns {Array<{text: string, id: string}>}
   */
  function brister() {
    const problems = [];
    if (!state.statements) problems.push({ text: 'Ingen bokföring inläst.', id: 'bygg-drop' });
    if (!value('bygg-ar-from')) {
      problems.push({ text: 'Räkenskapsårets första dag saknas.', id: 'bygg-ar-from' });
    }
    if (!value('bygg-ar-tom')) {
      problems.push({ text: 'Räkenskapsårets sista dag saknas.', id: 'bygg-ar-tom' });
    }
    if (!value('bygg-orgnr')) problems.push({ text: 'Organisationsnummer saknas.', id: 'bygg-orgnr' });
    if (!value('bygg-foretagsnamn')) {
      problems.push({ text: 'Företagsnamn saknas.', id: 'bygg-foretagsnamn' });
    }
    if (!value('bygg-verksamhet')) {
      problems.push({ text: 'Allmänt om verksamheten är obligatoriskt i förvaltningsberättelsen.',
                      id: 'bygg-verksamhet' });
    }
    if (!value('bygg-principer')) {
      problems.push({ text: 'Redovisningsprinciper saknas.', id: 'bygg-principer' });
    }
    if (!underskrifter().length) {
      problems.push({ text: 'Minst en underskrift behövs.', id: 'bygg-underskrifter' });
    }
    if (!value('bygg-ort')) problems.push({ text: 'Ort för underskrift saknas.', id: 'bygg-ort' });
    if (!value('bygg-datum')) {
      problems.push({ text: 'Datum för underskrift saknas.', id: 'bygg-datum' });
    }
    if (state.statements && state.statements.avvikelser.length) {
      problems.push({ text: 'Uppställningen går inte ihop — se steg A2.', id: '' });
    }
    return problems;
  }

  // ── Handlingar ────────────────────────────────────────────────────────────

  registerActions({
    'bygg:pick': () => $('bygg-file-input').click(),

    'bygg:pick-key': (event) => {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      event.preventDefault();
      $('bygg-file-input').click();
    },

    'bygg:file': (event) => loadFile(event.target.files && event.target.files[0]),

    'bygg:koppla': (event, element) => {
      const row = state.rows[Number(element.dataset.index)];
      if (!row) return;
      row.element = element.value;
      recompute();
      fyllResultatdisposition();
      renderKoppling();
      renderUppstallning();
    },

    /* Röring i formuläret ändrar inte siffrorna, bara texten runt dem — utom
       utdelningen, som styr vad som balanseras i ny räkning. */
    'bygg:falt': () => {
      const utdelning = number('bygg-disp-utdelning') ?? 0;
      const summa = (number('bygg-disp-balanserat') ?? 0) + (number('bygg-disp-arets') ?? 0);
      const nyrakning = $('bygg-disp-nyrakning');
      if (nyrakning && nyrakning.dataset.auto === '1') nyrakning.value = Math.round(summa - utdelning);
      const summaEl = $('bygg-disp-summa');
      if (summaEl) summaEl.textContent = B.fmt(summa) + ' kr';
      renderBrister();
    },

    'bygg:manuellt': (event, element) => { element.dataset.auto = '0'; },

    'bygg:till-falt': (event, element) => {
      const target = $(element.dataset.falt);
      if (!target) return;
      target.scrollIntoView({ behavior: 'smooth', block: 'center' });
      if (typeof target.focus === 'function') target.focus({ preventScroll: true });
    },

    'bygg:lagg-till-person': () => {
      const list = $('bygg-underskrifter');
      if (!list) return;
      list.insertAdjacentHTML('beforeend', personBlock());
      renderBrister();
    },

    'bygg:ta-bort-person': (event, element) => {
      const block = element.closest('.bygg-person');
      if (block) block.remove();
      renderBrister();
    },

    'bygg:generera': () => {
      const problems = brister();
      renderBrister(problems);
      if (problems.length) {
        return showFailureBanner(`Fyll i det som saknas innan handlingen skrivs ut — `
          + `${problems.length} sak${problems.length === 1 ? '' : 'er'} återstår.`, 'error');
      }
      state.ixbrl = B.buildIxbrl(model());
      state.filnamn = `arsredovisning-${value('bygg-orgnr').replace(/\D/g, '')}-`
        + `${value('bygg-ar-tom')}.xhtml`;
      const preview = $('bygg-resultat');
      if (preview) {
        preview.hidden = false;
        preview.innerHTML = `<p class="ar-ok-mark">Handlingen är skriven:
          ${kvotEscapeHtml(state.filnamn)}, ${new Blob([state.ixbrl]).size} byte.</p>
          <p class="ar-note-inline">Läs in den i steg B1 så granskas den mot samma kontroller
          som vilken annan fil som helst — den får ingen gräddfil för att sidan skrev den.</p>`;
      }
      for (const id of ['bygg-hamta', 'bygg-anvand', 'bygg-docx', 'bygg-pdf']) {
        const button = $(id);
        if (button) button.disabled = false;
      }
    },

    'bygg:hamta': () => {
      if (!state.ixbrl) return;
      const blob = new Blob([state.ixbrl], { type: 'application/xhtml+xml;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = state.filnamn;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
    },

    /* Lämnar handlingen till del B genom sidans egen filinmatning, så den går
       exakt samma väg som en fil från disk. */
    'bygg:anvand': () => {
      if (!state.ixbrl) return;
      const file = new File([state.ixbrl], state.filnamn,
                            { type: 'application/xhtml+xml' });
      const transfer = new DataTransfer();
      transfer.items.add(file);
      const input = $('file-input');
      input.files = transfer.files;
      input.dispatchEvent(new Event('change', { bubbles: true }));
      const target = document.getElementById('del-b');
      if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    },

    'bygg:docx': () => KVOT_ARSRED_EXPORT.exportDocument(state.ixbrl, 'docx', state.filnamn),
    'bygg:pdf': () => KVOT_ARSRED_EXPORT.exportDocument(state.ixbrl, 'pdf', state.filnamn),

    'bygg:rensa': () => {
      state.book = null; state.rows = []; state.omforingar = [];
      state.statements = null; state.ixbrl = ''; state.filnamn = '';
      if ($('bygg-file-input')) $('bygg-file-input').value = '';
      if ($('bygg-resultat')) $('bygg-resultat').hidden = true;
      for (const id of ['bygg-hamta', 'bygg-anvand', 'bygg-docx', 'bygg-pdf']) {
        const button = $(id);
        if (button) button.disabled = true;
      }
      render();
      renderBrister();
    },
  });

  function personBlock() {
    return `<div class="bygg-person">
      <input type="text" class="bygg-tilltalsnamn" placeholder="Tilltalsnamn"
             data-on-input="bygg:falt" autocomplete="off">
      <input type="text" class="bygg-efternamn" placeholder="Efternamn"
             data-on-input="bygg:falt" autocomplete="off">
      <input type="text" class="bygg-roll" placeholder="Roll, t.ex. Styrelseledamot"
             data-on-input="bygg:falt" autocomplete="off">
      <button type="button" class="ar-btn" data-on-click="bygg:ta-bort-person"
              aria-label="Ta bort underskrift">×</button>
    </div>`;
  }

  function renderBrister(problems) {
    const box = $('bygg-brister');
    if (!box) return;
    const list = problems || brister();
    box.hidden = !list.length;
    box.innerHTML = list.map(p =>
      `<li>${kvotEscapeHtml(p.text)}${p.id
        ? ` <button type="button" class="ar-lank" data-on-click="bygg:till-falt"` +
          ` data-falt="${kvotEscapeHtml(p.id)}">visa fältet</button>` : ''}</li>`).join('');

    /* Fälten som saknas får sin röda markering först när listan visas, alltså
       när någon försökt skriva ut handlingen. Att färga dem vid sidladdning
       vore att skälla på någon som inte hunnit börja. */
    const saknas = new Set(list.map(p => p.id).filter(Boolean));
    for (const el of document.querySelectorAll('#arsred [data-kravs]')) {
      el.classList.toggle('saknas', saknas.has(el.id));
    }
  }

  function mountDropZone() {
    const zone = $('bygg-drop');
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
      if (file) loadFile(file).catch(error => reportFailure('arsred-bygg.drop', error));
    });
  }

  function init() {
    mountDropZone();
    const list = $('bygg-underskrifter');
    if (list && !list.children.length) list.innerHTML = personBlock();
    render();
    renderBrister();
  }

  // ── Utkast ────────────────────────────────────────────────────────────────

  /*
    Bokföringen och kontokopplingen är det enda i del A som inte står i ett
    formulärfält, så det är det enda utkastmodulen behöver hämta härifrån.
    Map-objekten blir arrayer på vägen ut och Map igen på vägen in; JSON kan
    inte bära en Map, och att låta bli att nämna det hade gjort ett återläst
    utkast till en bok utan saldon.
  */
  const KARTOR = ['kontonamn', 'ub', 'ubFg', 'res', 'resFg'];

  function snapshot() {
    if (!state.book) return null;
    const book = {};
    for (const [key, value] of Object.entries(state.book)) {
      book[key] = KARTOR.includes(key) ? [...value] : value;
    }
    return {
      book,
      /* Bara kontonumret och vad det kopplats till: resten går att räkna om,
         och ett utkast ska inte bära dubbletter av sina egna siffror. */
      koppling: state.rows.map(row => [row.konto, row.element]),
    };
  }

  function restore(data) {
    if (!data || !data.book) return false;
    const book = {};
    for (const [key, value] of Object.entries(data.book)) {
      book[key] = KARTOR.includes(key) ? new Map(value) : value;
    }
    state.book = book;
    state.rows = B.accounts(book);
    const koppling = new Map(data.koppling || []);
    for (const row of state.rows) {
      if (koppling.has(row.konto)) row.element = koppling.get(row.konto);
    }
    /* Omföringen räknas om i stället för att läsas in: den beror på saldon,
       och saldon kommer med boken. */
    state.omforingar = B.reclassify(state.rows);
    recompute();
    render();
    /* Bristlistan är en bedömning av vad som fyllts i, så den måste räknas om
       när något fylls i åt användaren snarare än av hen. */
    renderBrister();
    return true;
  }

  return { init, state, snapshot, restore, render, recompute,
           fyllResultatdisposition, personBlock, renderBrister };
})();
