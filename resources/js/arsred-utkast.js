/* ==========================================================================
   arsred-utkast.js — spara och återuppta påbörjat arbete

   En årsredovisning skrivs sällan i ett svep. Det här låter arbetet ligga
   kvar: fälten sparas i webbläsarens eget utrymme medan de fylls i, och kan
   också läggas i en fil att flytta mellan datorer eller skicka till den som
   ska titta på siffrorna.

   Två saker är medvetna.

   Personnummer sparas aldrig, varken i webbläsaren eller i filen. Sedan
   inlämningsdelen togs bort frågar sidan inte efter några alls, men spärren
   står kvar: ett utkast är också någonstans, och den dag ett sådant fält
   kommer tillbaka ska det inte följa med av bara farten.

   Ett utkast återupptas inte av sig självt. Att komma tillbaka till sidan och
   finna den ifylld med något man inte minns är obehagligt även när det man
   hittar är rätt; i stället erbjuds utkastet, med datum, och det går lika bra
   att slänga det.
   ========================================================================== */

const KVOT_ARSRED_UTKAST = (() => {
  'use strict';

  const NYCKEL = 'kvot-arsred-utkast';
  const VERSION = 1;
  const $ = (id) => document.getElementById(id);

  /* Fälten i del B som hör till arbetet snarare än till ögonblicket. Sedan
     inlämningsdelen togs bort är det två: organisationsnumret kontrollen
     jämför mot, och handlingstypen den bedömer fastställelseintyget efter. */
  const DEL_B = Object.freeze(['orgnr', 'typ']);

  /* Personnummer lagras inte. Listan står här för att det ska gå att se att
     de utelämnas, inte bara att de råkar saknas — och för att den ska hålla
     om ett fält någon gång kommer tillbaka. */
  const ALDRIG = Object.freeze(['pnr', 'undertecknare', 'token']);

  let sparaTimer = null;

  /*
    Fältens värden när sidan just öppnats. Flera av dem är förifyllda —
    redovisningsprinciperna, nyckeltalsdefinitionerna, styrelsens yttrande —
    och räknades tidigare som ifyllda. Följden var att ett tomt formulär ansågs innehålla ett utkast, så
    autosparet skrev tillbaka ett nytt så fort något hände på sidan, och
    Släng-knappen såg ut att inte göra någonting. Ett fält som står kvar på
    sitt förvalda värde är inte ifyllt.
  */
  let forvalda = null;

  // ── Vad ett utkast består av ──────────────────────────────────────────────

  /*
    Filväljarna delar id-prefix med resten av del A men hör inte till arbetet:
    en fils namn går inte ens att skriva tillbaka programmatiskt, vilket
    webbläsaren säger ifrån om. Knappar bär inget värde att spara.
  */
  const EJ_FALT = new Set(['file', 'button', 'submit', 'reset', 'image']);

  function formFields() {
    const out = {};
    for (const el of document.querySelectorAll('[id^="bygg-"]')) {
      if (!/^(INPUT|SELECT|TEXTAREA)$/.test(el.tagName)) continue;
      if (EJ_FALT.has(el.type)) continue;
      out[el.id] = el.type === 'checkbox' ? el.checked : el.value;
    }
    for (const id of DEL_B) {
      const el = $(id);
      if (el) out[id] = el.type === 'checkbox' ? el.checked : el.value;
    }
    for (const id of ALDRIG) delete out[id];
    return out;
  }

  function personer() {
    return [...document.querySelectorAll('#bygg-underskrifter .bygg-person')].map(block => ({
      tilltalsnamn: (block.querySelector('.bygg-tilltalsnamn') || {}).value || '',
      efternamn: (block.querySelector('.bygg-efternamn') || {}).value || '',
      roll: (block.querySelector('.bygg-roll') || {}).value || '',
    }));
  }

  /**
   * Allt som utgör det påbörjade arbetet.
   *
   * @returns {Object|null} null när ingenting är ifyllt
   */
  function snapshot() {
    const falt = formFields();
    const bok = KVOT_ARSRED_BYGG_UI.snapshot();
    const folk = personer().filter(p => p.tilltalsnamn || p.efternamn || p.roll);
    const andrat = Object.entries(falt).some(([id, value]) =>
      forvalda ? value !== forvalda[id] : (value !== '' && value !== false));
    if (!bok && !folk.length && !andrat) return null;
    return {
      version: VERSION,
      sparat: new Date().toISOString(),
      foretag: falt['bygg-foretagsnamn'] || '',
      rakenskapsar: falt['bygg-ar-tom'] || '',
      falt,
      personer: folk,
      bok,
    };
  }

  /**
   * Lägg tillbaka ett utkast i sidan.
   *
   * @param {Object} data
   * @returns {boolean}
   */
  function restore(data) {
    if (!data || typeof data !== 'object') return false;
    if (data.version !== VERSION) {
      showFailureBanner('Utkastet är sparat med en annan version av sidan och kan inte '
        + 'läsas in.', 'error');
      return false;
    }

    for (const [id, value] of Object.entries(data.falt || {})) {
      if (ALDRIG.includes(id)) continue;
      const el = $(id);
      if (!el || EJ_FALT.has(el.type)) continue;
      if (el.type === 'checkbox') el.checked = !!value;
      else el.value = value;
      /* Fälten har egna lyssnare — organisationsnumret och handlingstypen
         går in i kontrollen och ska räknas om när de skrivs tillbaka. */
      el.dispatchEvent(new Event(el.tagName === 'SELECT' || el.type === 'checkbox'
        ? 'change' : 'input', { bubbles: true }));
      /* Var värdet ursprungligen kom ifrån följer inte med i utkastet; att det
         kommer därifrån är det ärliga att säga. */
      if (String(value || '').trim()) KVOT_ARSRED_KALLA.satt(id, 'utkast');
    }

    const lista = $('bygg-underskrifter');
    if (lista && (data.personer || []).length) {
      lista.innerHTML = '';
      for (const person of data.personer) {
        lista.insertAdjacentHTML('beforeend', KVOT_ARSRED_BYGG_UI.personBlock());
        const block = lista.lastElementChild;
        block.querySelector('.bygg-tilltalsnamn').value = person.tilltalsnamn;
        block.querySelector('.bygg-efternamn').value = person.efternamn;
        block.querySelector('.bygg-roll').value = person.roll;
      }
    }

    if (data.bok) KVOT_ARSRED_BYGG_UI.restore(data.bok);
    KVOT_ARSRED_BYGG_UI.fyllResultatdisposition();
    /* Dispositionen kom med utkastet och ska inte skrivas över av det
       automatiska förslaget. */
    for (const [id, value] of Object.entries(data.falt || {})) {
      if (!/^bygg-disp-/.test(id)) continue;
      const el = $(id);
      if (el) { el.value = value; el.dataset.auto = '0'; }
    }
    KVOT_ARSRED_BYGG_UI.render();
    KVOT_ARSRED_BYGG_UI.renderBrister();
    return true;
  }

  // ── Webbläsarens eget utrymme ─────────────────────────────────────────────

  /*
    localStorage kastar i vissa privatlägen och under file://, och kan vara
    full. Ett utkast som inte går att spara är en olägenhet, inte ett haveri —
    men det ska synas, annars tror man att arbetet ligger kvar när det inte
    gör det.
  */
  function spara() {
    const data = snapshot();
    try {
      if (!data) localStorage.removeItem(NYCKEL);
      else localStorage.setItem(NYCKEL, JSON.stringify(data));
      visaStatus(data ? `Utkast sparat ${klocka(data.sparat)}` : '');
      return true;
    } catch (error) {
      ignoreFailure('arsred-utkast.spara', error);
      visaStatus('Utkastet kunde inte sparas — webbläsaren tillåter inte lagring här.');
      return false;
    }
  }

  /** Spara, men inte vid varje tangenttryckning. */
  function sparaSnart() {
    if (sparaTimer) clearTimeout(sparaTimer);
    sparaTimer = setTimeout(spara, 800);
  }

  function last() {
    try {
      const raw = localStorage.getItem(NYCKEL);
      return raw ? JSON.parse(raw) : null;
    } catch (error) {
      ignoreFailure('arsred-utkast.last', error);
      return null;
    }
  }

  function klocka(iso) {
    const date = new Date(iso);
    return Number.isNaN(date.getTime()) ? '' : date.toLocaleString('sv-SE', {
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit',
    });
  }

  function visaStatus(text) {
    const box = $('utkast-status');
    if (box) box.textContent = text;
  }

  // ── Erbjudandet när sidan öppnas ──────────────────────────────────────────

  function visaErbjudande() {
    const data = last();
    const box = $('utkast-banner');
    if (!box) return;
    if (!data) { box.hidden = true; return; }
    box.hidden = false;
    box.innerHTML = `
      <div>
        <b>Det finns ett sparat utkast</b> från ${kvotEscapeHtml(klocka(data.sparat))}${
          data.foretag ? ' — ' + kvotEscapeHtml(data.foretag) : ''}${
          data.rakenskapsar ? ', räkenskapsår till och med '
            + kvotEscapeHtml(data.rakenskapsar) : ''}.
      </div>
      <div class="ar-btn-row">
        <button type="button" class="ar-btn primary" data-on-click="utkast:aterta">Återuppta</button>
        <button type="button" class="ar-btn" data-on-click="utkast:slang">Släng</button>
      </div>`;
  }

  // ── Handlingar ────────────────────────────────────────────────────────────

  registerActions({
    'utkast:spara': () => {
      if (spara()) notifyUser('Utkastet är sparat i den här webbläsaren.', { tone: 'success' });
    },

    'utkast:aterta': () => {
      const data = last();
      if (!data) return;
      if (restore(data)) {
        const box = $('utkast-banner');
        if (box) box.hidden = true;
        notifyUser('Utkastet är återupptaget.', { tone: 'success' });
      }
    },

    'utkast:slang': () => {
      /* Ett autospar som redan står och väntar skulle annars skriva tillbaka
         utkastet en sekund efter att det slängts. */
      if (sparaTimer) { clearTimeout(sparaTimer); sparaTimer = null; }
      try { localStorage.removeItem(NYCKEL); } catch (error) { ignoreFailure('arsred-utkast.slang', error); }
      const box = $('utkast-banner');
      if (box) box.hidden = true;
      visaStatus('Utkastet är slängt.');
    },

    'utkast:till-fil': () => {
      const data = snapshot();
      if (!data) return notifyUser('Det finns ingenting ifyllt att spara.');
      const namn = `arsredovisning-utkast-${(data.foretag || 'utan-namn')
        .toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')}`
        + `${data.rakenskapsar ? '-' + data.rakenskapsar : ''}.json`;
      KVOT_ARSRED_EXPORT.saveAs(
        new Blob([JSON.stringify(data, null, 2)], { type: 'application/json;charset=utf-8' }),
        namn);
    },

    'utkast:oppna': () => $('utkast-file-input').click(),

    'utkast:fil': async (event) => {
      const file = event.target.files && event.target.files[0];
      if (!file) return;
      let data;
      try {
        data = JSON.parse(await file.text());
      } catch (error) {
        ignoreFailure('arsred-utkast.fil', error);
        return showFailureBanner('Filen är inte ett utkast från den här sidan.', 'error');
      }
      if (restore(data)) {
        spara();
        const box = $('utkast-banner');
        if (box) box.hidden = true;
        notifyUser('Utkastet är inläst.', { tone: 'success' });
      }
      event.target.value = '';
    },
  });

  // ── Start ─────────────────────────────────────────────────────────────────

  function init() {
    /* Läses innan något hunnit ändras, så att jämförelsen i snapshot() har
       något att jämföra med. */
    forvalda = formFields();
    visaErbjudande();
    /* Allt som ändras i formulären sparas, med fördröjning. Delegerat, så att
       fält som ritas senare — underskrifter, kontokopplingen — räknas med. */
    for (const type of ['input', 'change']) {
      document.addEventListener(type, (event) => {
        const el = event.target;
        if (!el || !el.id && !el.closest) return;
        const inomOmradet = (el.id && (el.id.startsWith('bygg-') || DEL_B.includes(el.id)))
          || (el.closest && el.closest('.bygg-person, .bygg-konton'));
        if (inomOmradet) sparaSnart();
      }, true);
    }
    /* En fil som släpps i del A ändrar inget formulärfält, så bokföringen
       fångas när den är inläst. */
    const input = $('bygg-file-input');
    if (input) input.addEventListener('change', () => setTimeout(spara, 1200));
  }

  return { init, snapshot, restore, spara, last, ALDRIG };
})();
