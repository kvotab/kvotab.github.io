/* ==========================================================================
   arsred-kalla.js — var varje uppgift kommer ifrån

   En årsredovisning byggd här har fyra sorters innehåll, och de är olika
   mycket värda att lita på: tal som räknats fram ur bokföringen, tal som
   härletts av dem, text som tolkats ur en tidigare årsredovisning, och det
   som skrivits in för hand. Den som ska skriva under behöver kunna se vilket
   som är vilket utan att minnas hur fältet blev ifyllt.

   Varje modul som fyller i ett fält säger till här. Handpåläggning behöver
   ingen anmäla: ett input-event som kommer från ett tangentbord bär
   isTrusted, och ett som kommer från kod gör det inte, så skillnaden går att
   se utan att någon rapporterar den.
   ========================================================================== */

const KVOT_ARSRED_KALLA = (() => {
  'use strict';

  /* Ordningen är fallande tillförlitlighet, vilket också är den ordning
     etiketterna får sin färg i. */
  const TEXT = Object.freeze({
    bokforing: 'bokföringen',
    harlett: 'härlett',
    beraknat: 'beräknat',
    'fjolaret-taggat': 'fjolåret, taggat',
    'fjolaret-text': 'fjolåret, tolkat',
    utkast: 'utkast',
    forval: 'förval',
    manuellt: 'ifyllt av dig',
  });

  const FORKLARING = Object.freeze({
    bokforing: 'Läst direkt ur SIE-filen.',
    harlett: 'Uträknat ur bokföringens räkenskapsår.',
    beraknat: 'Framräknat ur uppställningen.',
    'fjolaret-taggat': 'Hämtat ur taggarna i en tidigare iXBRL-handling — samma värde '
      + 'som lämnades in då.',
    'fjolaret-text': 'Tolkat ur texten i en tidigare årsredovisning. Läs igenom det.',
    utkast: 'Återupptaget från ett sparat utkast.',
    forval: 'Sidans förvalda formulering. Ändra den om den inte stämmer.',
    manuellt: 'Inskrivet av dig.',
  });

  /** fält-id -> källa */
  const kallor = new Map();

  /**
   * Anteckna var ett fälts värde kommer ifrån.
   *
   * @param {string} id
   * @param {string} kalla - en nyckel i TEXT
   * @returns {void}
   */
  function satt(id, kalla) {
    if (!TEXT[kalla]) return;
    kallor.set(id, kalla);
    rita(id);
  }

  /** Anteckna flera fält på en gång. */
  function sattFlera(ids, kalla) {
    for (const id of ids) satt(id, kalla);
  }

  function kalla(id) { return kallor.get(id) || null; }

  /**
   * Rita ut märkningen vid ett fält.
   *
   * Fält som bor i en formulärruta får sin etikett bredvid rubriken; de som
   * bor i en tabellcell — flerårsöversiktens äldre år — får bara sin färg och
   * en titel, eftersom en textetikett per cell skulle dränka tabellen.
   */
  function rita(id) {
    const el = document.getElementById(id);
    if (!el) return;
    const vald = kallor.get(id);
    if (!vald) return;
    el.dataset.kalla = vald;
    el.title = FORKLARING[vald] || '';

    const ruta = el.closest('.ar-field');
    if (!ruta) return;
    let etikett = ruta.querySelector(':scope > .ar-kalla');
    if (!etikett) {
      etikett = document.createElement('span');
      etikett.className = 'ar-kalla';
      const label = ruta.querySelector(':scope > label');
      if (label) label.insertAdjacentElement('afterend', etikett);
      else ruta.prepend(etikett);
    }
    etikett.textContent = TEXT[vald];
    etikett.dataset.kalla = vald;
    etikett.title = FORKLARING[vald] || '';
  }

  function ritaAlla() { for (const id of kallor.keys()) rita(id); }

  /**
   * Nollställ märkningen för fält som tömts.
   *
   * Ett fält utan värde har ingen källa, och en kvarglömd etikett skulle
   * påstå att tomheten kommer från bokföringen.
   */
  function stad() {
    for (const id of [...kallor.keys()]) {
      const el = document.getElementById(id);
      if (!el) continue;
      const tomt = el.type === 'checkbox' ? false : !String(el.value || '').trim();
      if (!tomt) continue;
      kallor.delete(id);
      delete el.dataset.kalla;
      el.removeAttribute('title');
      const ruta = el.closest('.ar-field');
      const etikett = ruta && ruta.querySelector(':scope > .ar-kalla');
      if (etikett) etikett.remove();
    }
  }

  function glom() {
    for (const id of [...kallor.keys()]) {
      const el = document.getElementById(id);
      if (el) { delete el.dataset.kalla; el.removeAttribute('title'); }
      const ruta = el && el.closest('.ar-field');
      const etikett = ruta && ruta.querySelector(':scope > .ar-kalla');
      if (etikett) etikett.remove();
    }
    kallor.clear();
  }

  function init() {
    /*
      Fälten som är förifyllda i markupen har sidan själv skrivit, och det är
      värt att säga: den som inte vet att formuleringen är ett förval låter
      den ofta stå kvar.
    */
    for (const el of document.querySelectorAll('#arsred [id^="bygg-"]')) {
      if (!/^(INPUT|SELECT|TEXTAREA)$/.test(el.tagName)) continue;
      if (el.type === 'file' || el.type === 'checkbox') continue;
      if (String(el.value || '').trim()) satt(el.id, 'forval');
    }

    /*
      Ett event från ett tangentbord eller en mus bär isTrusted; ett som koden
      själv skickat gör det inte. Därför behöver ingen modul anmäla att
      användaren skrivit något — det syns.
    */
    for (const type of ['input', 'change']) {
      document.addEventListener(type, (event) => {
        const el = event.target;
        if (!event.isTrusted || !el || !el.id) return;
        if (!/^(INPUT|SELECT|TEXTAREA)$/.test(el.tagName) || el.type === 'file') return;
        if (!el.closest('#arsred')) return;
        satt(el.id, 'manuellt');
        stad();
      }, true);
    }
  }

  return { init, satt, sattFlera, kalla, rita, ritaAlla, stad, glom, TEXT, FORKLARING };
})();
