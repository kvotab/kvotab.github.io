"""Characterisation test for the whole kvotab site.

Fingerprints every page: shared chrome, page-specific computation, and the
console. Run before a change, run after, diff the two.
"""
import asyncio
import json
import sys
import urllib.request

import websockets

from driver import open_page

# Steps that apply to every page, since every page uses the same site chrome.
SHARED = [
    ('chrome', """(() => ({
      title: document.title,
      headerTitle: (document.querySelector('header .title') || {}).textContent || null,
      headerTag: (document.querySelector('header .title') || {}).tagName || null,
      navToggleTag: (document.querySelector('.nav-toggle') || {}).tagName || null,
      navExpanded: (document.querySelector('.nav-toggle') || {}).getAttribute
        ? document.querySelector('.nav-toggle').getAttribute('aria-expanded') : null,
      menuLinks: [...document.querySelectorAll('#menu a')].map(a => a.getAttribute('href')),
      footerIcons: document.querySelectorAll('footer svg').length,
      footerButtons: document.querySelectorAll('footer button').length,
      theme: document.documentElement.getAttribute('data-theme'),
      storedTheme: (() => { try { return localStorage.getItem('kvot-theme'); } catch (e) { return 'ERR'; } })(),
      mapContainer: !!document.getElementById('kvotmap'),
      mapVisibility: document.getElementById('kvotmap')
        ? getComputedStyle(document.getElementById('kvotmap')).visibility : null,
      leafletLoadedEagerly: typeof L,
      kvotApi: typeof KVOT === 'object' ? Object.keys(KVOT).sort() : null
    }))()"""),

    ('chrome.interactions', """(async () => {
      const out = {};
      const toggle = document.querySelector('.nav-toggle');
      toggle.click();
      out.menuOpenAfterClick = document.getElementById('menu').classList.contains('open');
      out.ariaAfterOpen = toggle.getAttribute('aria-expanded');
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
      await new Promise(r => setTimeout(r, 60));
      out.menuOpenAfterEscape = document.getElementById('menu').classList.contains('open');

      const before = document.documentElement.getAttribute('data-theme');
      KVOT.toggleTheme();
      out.themeFlipped = document.documentElement.getAttribute('data-theme') !== before;
      out.themePersisted = (() => { try { return localStorage.getItem('kvot-theme'); } catch (e) { return 'ERR'; } })();
      KVOT.toggleTheme();
      out.themeRestored = document.documentElement.getAttribute('data-theme') === before;

      if (document.getElementById('kvotmap')) {
        KVOT.toggleMap();
        await new Promise(r => setTimeout(r, 3500));
        out.mapAfterToggle = getComputedStyle(document.getElementById('kvotmap')).visibility;
        out.leafletAfterToggle = typeof L;
        out.tiles = document.querySelectorAll('#kvotmap img.leaflet-tile').length > 0;
        KVOT.toggleMap();
        out.mapAfterSecondToggle = getComputedStyle(document.getElementById('kvotmap')).visibility;
      }
      return out;
    })()"""),
]

# Noise that says nothing about this site's own code: third-party widgets
# complaining about their own postMessage, and CDN fetches that the network
# happened to drop. Both vary run to run, so they are summarised by origin
# rather than recorded verbatim.
EXTERNAL_HOSTS = ('youtube.com', 'ytimg.com', 'unpkg.com', 'jsdelivr.net',
                  'cdnjs.cloudflare.com', 'cdn.plot.ly', 'code.jquery.com',
                  'tile.jawg.io', 'arcgisonline.com')


def summarise_console(logs):
    """Console and network entries, with external noise collapsed to a count."""
    own, external = [], 0  # `external` counted only to keep the loop readable
    for kind, message in logs:
        if 'favicon' in message.lower():
            continue
        if any(host in message for host in EXTERNAL_HOSTS):
            external += 1
            continue
        if kind == 'netfail':
            # A dropped request with no URL attached is almost always a tile or
            # CDN fetch cancelled during teardown; count it rather than record it.
            external += 1
            continue
        own.append('%s: %s' % (kind, message[:140]))
    # The external count is itself run-to-run noise, so it is not recorded. A
    # failed request for one of *this site's* files is not external and stays.
    return own


# A minimal but complete iXBRL filing, built here rather than downloaded so the
# fingerprint does not move when taxonomier.se changes its example files. It is
# deliberately clean: balanced, correctly dated, tagged with the document facts
# and the fastställelseintyg, so every check that can pass, passes — and a
# change that breaks one of them shows up as a level flipping to error.
# En liten SIE 4-fil, skriven här snarare än hämtad, så att fingeravtrycket
# inte rör sig när någon annans bokföring gör det. Tecknen följer SIE:s egen
# konvention: debet positivt, så intäktskontot står negativt — utom 8999, som
# debiteras vid vinst eftersom det är avslutskontot mot 2099. Just den
# omvändningen fick vinst och förlust att byta plats på deklarationen, så
# kontot står med i fixturen.
SIE_FIXTURE = """#FLAGGA 0
#PROGRAM "Testbok" 1.0
#FORMAT PC8
#SIETYP 4
#ORGNR 559162-0306
#FNAMN "Kvot AB"
#RAR 0 20250701 20260630
#RAR -1 20240701 20250630
#KONTO 1510 Kundfordringar
#KONTO 1930 "Foretagskonto"
#KONTO 2081 Aktiekapital
#KONTO 2091 "Balanserad vinst eller forlust"
#KONTO 2099 "Arets resultat"
#KONTO 2440 Leverantorsskulder
#KONTO 3041 "Forsaljning tjanst"
#KONTO 5010 Lokalhyra
#KONTO 8910 "Skatt pa arets resultat"
#KONTO 8999 "Arets resultat"
#UB 0 1510 100000.00
#UB 0 1930 400000.00
#UB 0 2081 -50000.00
#UB 0 2091 -300000.00
#UB 0 2099 -120000.00
#UB 0 2440 -30000.00
#UB -1 1510 80000.00
#UB -1 1930 320000.00
#UB -1 2081 -50000.00
#UB -1 2091 -240000.00
#UB -1 2099 -60000.00
#UB -1 2440 -50000.00
#RES 0 3041 -200000.00
#RES 0 5010 50000.00
#RES 0 8910 30000.00
#RES 0 8999 120000.00
#RES -1 3041 -150000.00
#RES -1 5010 60000.00
#RES -1 8910 30000.00
#RES -1 8999 60000.00
"""

FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:link="http://www.xbrl.org/2003/linkbase"
      xmlns:xlink="http://www.w3.org/1999/xlink"
      xmlns:xbrli="http://www.xbrl.org/2003/instance"
      xmlns:iso4217="http://www.xbrl.org/2003/iso4217"
      xmlns:se-cd-base="http://www.taxonomier.se/se/fr/cd-base/2021-10-31"
      xmlns:se-gen-base="http://www.taxonomier.se/se/fr/gen-base/2021-10-31"
      xmlns:se-bol-base="http://www.bolagsverket.se/se/fr/comp-base/2020-12-01"
      xmlns:se-mem-base="http://www.taxonomier.se/se/fr/mem-base/2021-10-31">
<head><title>559162-0306 Kvot AB</title></head>
<body>
<ix:header>
  <ix:hidden>
    <ix:nonNumeric name="se-cd-base:SprakHandlingUpprattadList" contextRef="period0">se-mem-base:SprakSvenskaMember</ix:nonNumeric>
    <ix:nonNumeric name="se-cd-base:LandForetagetsSateList" contextRef="period0">se-mem-base:LandSverigeMember</ix:nonNumeric>
    <ix:nonNumeric name="se-cd-base:RedovisningsvalutaHandlingList" contextRef="period0">se-mem-base:ValutaSvenskaKronorMember</ix:nonNumeric>
    <ix:nonNumeric name="se-cd-base:BeloppsformatList" contextRef="period0">se-mem-base:BeloppsformatNormalformMember</ix:nonNumeric>
    <ix:nonNumeric name="se-gen-base:FinansiellRapportList" contextRef="period0">se-mem-base:FinansiellRapportStyrelsenAvgerArsredovisningMember</ix:nonNumeric>
    <ix:nonNumeric name="se-cd-base:RakenskapsarForstaDag" contextRef="period0">2024-01-01</ix:nonNumeric>
    <ix:nonNumeric name="se-cd-base:RakenskapsarSistaDag" contextRef="period0">2024-12-31</ix:nonNumeric>
  </ix:hidden>
  <ix:references>
    <link:schemaRef xlink:type="simple" xlink:href="http://xbrl.taxonomier.se/se/fr/gaap/k2/risbs/2021-10-31/se-k2-risbs-2021-10-31.xsd"/>
  </ix:references>
  <ix:resources>
    <xbrli:context id="period0"><xbrli:entity>
      <xbrli:identifier scheme="http://www.bolagsverket.se">559162-0306</xbrli:identifier></xbrli:entity>
      <xbrli:period><xbrli:startDate>2024-01-01</xbrli:startDate><xbrli:endDate>2024-12-31</xbrli:endDate></xbrli:period>
    </xbrli:context>
    <xbrli:context id="balans0"><xbrli:entity>
      <xbrli:identifier scheme="http://www.bolagsverket.se">559162-0306</xbrli:identifier></xbrli:entity>
      <xbrli:period><xbrli:instant>2024-12-31</xbrli:instant></xbrli:period>
    </xbrli:context>
    <xbrli:context id="balans1"><xbrli:entity>
      <xbrli:identifier scheme="http://www.bolagsverket.se">559162-0306</xbrli:identifier></xbrli:entity>
      <xbrli:period><xbrli:instant>2023-12-31</xbrli:instant></xbrli:period>
    </xbrli:context>
    <xbrli:unit id="SEK"><xbrli:measure>iso4217:SEK</xbrli:measure></xbrli:unit>
  </ix:resources>
</ix:header>
<p>Summa tillgangar
  <ix:nonFraction name="se-gen-base:Tillgangar" contextRef="balans0" unitRef="SEK"
    decimals="INF" scale="0" format="ixt:numspacecomma">1 250 000</ix:nonFraction></p>
<p>Summa eget kapital och skulder
  <ix:nonFraction name="se-gen-base:EgetKapitalSkulder" contextRef="balans0" unitRef="SEK"
    decimals="INF" scale="0" format="ixt:numspacecomma">1 250 000</ix:nonFraction></p>
<p><ix:nonNumeric name="se-bol-base:FaststallelseResultatBalansrakning" contextRef="balans0">Jag intygar att resultat- och balansrakningen faststallts</ix:nonNumeric>
   <ix:nonNumeric name="se-bol-base:Arsstamma" contextRef="balans0">2025-04-17</ix:nonNumeric>
   <ix:nonNumeric name="se-bol-base:IntygandeOriginalInnehall" contextRef="balans0">Innehallet overensstammer med originalet</ix:nonNumeric>
   <ix:nonNumeric name="se-bol-base:UnderskriftFastallelseintygDatum" contextRef="balans0">2025-04-17</ix:nonNumeric></p>
</body>
</html>
"""

PAGES = {
    'index.html': [
        ('landing', """(() => ({
          h1: [...document.querySelectorAll('h1')].map(e => e.textContent.trim()),
          cards: [...document.querySelectorAll('.project-card')].map(c => ({
            href: c.getAttribute('href'),
            title: c.querySelector('.project-card-title').textContent,
            descLength: c.querySelector('.project-card-desc').textContent.length
          })),
          contactIcons: document.querySelectorAll('.contact-table svg').length,
          contactIconTitles: [...document.querySelectorAll('.contact-table svg title')].map(t => t.textContent),
          copyButtons: [...document.querySelectorAll('.copy-btn')].map(b => b.dataset.copy),
          links: [...document.querySelectorAll('.link-list a')].map(a => a.getAttribute('href')),
          metaDescription: (document.querySelector('meta[name=description]') || {}).content
        }))()"""),
    ],

    '404.html': [
        ('notfound', """(() => ({
          h1: [...document.querySelectorAll('h1')].map(e => e.textContent.trim()),
          cards: document.querySelectorAll('.project-card').length,
          firstCardHref: (document.querySelector('.project-card') || {}).href,
          baseHref: (document.querySelector('base') || {}).href,
          robots: (document.querySelector('meta[name=robots]') || {}).content
        }))()"""),
    ],

    'logn.html': [
        ('lognormal.math', """(async () => {
          const out = {};
          const setTab = name => {
            const a = [...document.querySelectorAll('#tabs-header a')].find(x => x.textContent.trim() === name);
            if (a) a.click();
          };
          const read = () => {
            const cells = {};
            document.querySelectorAll('#results .stat-card, #results .stat-row').forEach(() => {});
            [...document.querySelectorAll('[id^="out-"], .metric-value, .stat-value')].forEach((el, i) => {
              cells[el.id || ('v' + i)] = el.textContent.trim();
            });
            return cells;
          };
          out.tabs = [...document.querySelectorAll('#tabs-header a')].map(a => a.textContent.trim());
          out.selectedTabs = [...document.querySelectorAll('#tabs-header a.selected')].map(a => a.textContent.trim());
          const inputs = [...document.querySelectorAll('#logn input[type=text], #logn input[type=number]')];
          out.inputCount = inputs.length;
          out.initialOutputs = read();
          out.resultText = (document.getElementById('results') || document.getElementById('logn')).innerText
            .replace(/\\s+/g, ' ').slice(0, 400);
          return out;
        })()"""),
        ('lognormal.recompute', """(async () => {
          const out = {};
          const fields = [...document.querySelectorAll('#metric-panels input')].filter(i => i.offsetParent !== null);
          out.visibleFields = fields.map(f => ({ id: f.id || f.dataset.field || f.name, value: f.value }));
          if (fields.length >= 2) {
            fields[0].value = '1'; fields[0].dispatchEvent(new Event('input', { bubbles: true }));
            fields[1].value = '2'; fields[1].dispatchEvent(new Event('input', { bubbles: true }));
            await new Promise(r => setTimeout(r, 900));
            out.afterMuSigma = (document.getElementById('results') || document.getElementById('logn')).innerText
              .replace(/\\s+/g, ' ').slice(0, 500);
          }
          return out;
        })()"""),
    ],

    'proj.html': [
        ('coords.convert', """(async () => {
          const out = {};
          const set = (id, v) => {
            const el = document.getElementById(id);
            if (!el) return false;
            el.value = v;
            el.dispatchEvent(new Event('change', { bubbles: true }));
            return true;
          };
          out.setLat = set('lat_dd', '59.329323');
          out.setLon = set('long_dd', '18.068581');
          if (typeof latlong_wgs84_dd_change === 'function') latlong_wgs84_dd_change();
          await new Promise(r => setTimeout(r, 600));
          const read = id => (document.getElementById(id) || {}).value;
          out.values = {
            lat_dd: read('lat_dd'), long_dd: read('long_dd'),
            lat_dm: read('lat_dm'), long_dm: read('long_dm'),
            lat_dms: read('lat_dms'), long_dms: read('long_dms'),
            x_rt90: read('x_rt90'), y_rt90: read('y_rt90'),
            n_sweref99: read('n_sweref99'), e_sweref99: read('e_sweref99'),
            proj_rt90: read('proj_rt90'), proj_sweref99: read('proj_sweref99')
          };
          out.coordMapReady = !!(window.map && typeof window.map.getZoom === 'function');
          out.tiles = document.querySelectorAll('#coord-map img.leaflet-tile').length > 0;
          return out;
        })()"""),
        ('coords.bulk', """(async () => {
          const out = {};
          const input = document.getElementById('bulk_input');
          if (!input) return 'no bulk input';
          document.getElementById('bulk_from').value = 'rt90_2.5_gon_v';
          document.getElementById('bulk_to').value = 'sweref_99_tm';
          input.value = '6580000\\t1628000\\n6590000\\t1630000';
          const btn = [...document.querySelectorAll('button')]
            .find(b => /convert/i.test(b.textContent) && !/clear/i.test(b.textContent));
          out.buttonFound = !!btn;
          if (btn) btn.click();
          await new Promise(r => setTimeout(r, 1200));
          out.result = (document.getElementById('bulk_output') || {}).value
            || (document.getElementById('bulk_result') || {}).value || null;
          out.status = (document.getElementById('bulk_status') || {}).textContent || null;
          return out;
        })()"""),
        ('coords.zones', """(() => ({
          rt90Zones: typeof rt90_zones === 'object' ? Object.keys(rt90_zones).length : null,
          sweref99Zones: typeof sweref99_zones === 'object' ? Object.keys(sweref99_zones).length : null,
          zoneBounds: typeof get_zone_bounds === 'function'
            ? JSON.stringify(get_zone_bounds('sweref_99_1200')) : null,
          fmtDms: typeof fmt_dms === 'function' ? fmt_dms(15.80628) : null,
          pointInZone: typeof point_in_zone_bounds === 'function'
            ? point_in_zone_bounds({ west: 10, east: 20 }, 59, 15) : null
        }))()"""),
    ],

    'rdc.html': [
        ('decay.tree', """(async () => {
          await new Promise(r => setTimeout(r, 2500));
          return {
            treeItems: document.querySelectorAll('#tree li').length,
            elementsListed: [...document.querySelectorAll('#tree > ul > li > a')].slice(0, 6)
              .map(a => a.textContent.trim()),
            graphNodes: document.querySelectorAll('#map canvas').length,
            cytoscapeReady: typeof cytoscape,
            jquery: typeof jQuery !== 'undefined' ? jQuery.fn.jquery : null,
            plotly: typeof Plotly,
            dataLoaded: typeof rnDecayData === 'object' || typeof decaydata === 'object'
          };
        })()"""),
        ('decay.select', """(async () => {
          const out = {};
          const link = [...document.querySelectorAll('#tree a')].find(a => /Uranium|Uran/i.test(a.textContent));
          out.linkFound = !!link;
          if (link) {
            link.click();
            await new Promise(r => setTimeout(r, 2500));
            out.nodesAfterSelect = document.querySelectorAll('#map canvas').length;
            out.searchValue = (document.querySelector('header input') || {}).value;
          }
          return out;
        })()"""),
    ],

    'skbref.html': [
        ('rules', """(() => ({
          officialRules: typeof OFFICIAL_SKB_TEXT_RULES !== 'undefined' ? OFFICIAL_SKB_TEXT_RULES.length : null,
          reviewRules: typeof FORBIDDEN_WORD_RULES !== 'undefined' ? FORBIDDEN_WORD_RULES.length : null,
          citationRules: typeof POTENTIAL_INVALID_CITATION_RULES !== 'undefined'
            ? POTENTIAL_INVALID_CITATION_RULES.length : null,
          fixtureCases: typeof GUIDE_FIXTURE_CASES !== 'undefined' ? GUIDE_FIXTURE_CASES.length : null,
          fixtureFailures: typeof runGuideFixtureRegressionTests === 'function'
            ? runGuideFixtureRegressionTests().length : null,
          collation: typeof skbSortKey === 'function'
            ? ['Berg Adams C', 'Berggren B', 'Berg-Liljeblad A', 'Ünger', 'Öberg']
                .sort((a, b) => skbSortKey(a) < skbSortKey(b) ? -1 : 1) : null,
          chemistry: typeof isChemicalFormula === 'function'
            ? ['H2O', 'CO2', 'CaCO3', 'SFR1', 'CCP33'].map(t => t + '=' + isChemicalFormula(t)) : null,
          rulePacks: typeof activeRulePackNames === 'function' ? activeRulePackNames() : null,
          dropzone: !!document.getElementById('dropzone')
        }))()"""),
    ],

    'arsredovisning.html': [
        ('arsred.static', """(() => ({
          module: typeof KVOT_ARSRED,
          lang: document.documentElement.lang,
          /* The scope block states what the page cannot do. Losing it would
             leave a page that looks like it files annual reports. */
          scopeItems: document.querySelectorAll('.ar-scope li').length,
          steps: [...document.querySelectorAll('.ar-step-no')].map(e => e.textContent),
          controls: [...document.querySelectorAll('[data-on-click],[data-on-change],[data-on-input],[data-on-keydown]')]
            .map(e => e.id || e.getAttribute('data-on-click')).sort(),
          handlingstyper: [...document.querySelectorAll('#typ option')].map(o => o.value),
          /* The page stops at the local check on purpose: filing needs a
             signed agreement, a client certificate over mutual TLS and an
             allow-listed IP, none of which a browser has. Nothing that would
             try to call the API may come back without that being a deliberate
             decision, so its absence is pinned here. */
          inlamningBorta: ['api-base', 'info-base', 'allow-send', 'send-token',
                           'send-inlamning', 'fetch-grunduppgifter', 'curl-block',
                           'paste-response', 'api-result', 'pnr', 'undertecknare']
            .filter(id => document.getElementById(id)),
          apiExporterat: typeof KVOT_ARSRED === 'object' ? Object.keys(KVOT_ARSRED).sort() : null,
          /* Kvar står det som säger vad som faktiskt krävs för att lämna in. */
          referensRubriker: [...document.querySelectorAll('#arsred h3')].map(h => h.textContent.trim())
        }))()"""),

        ('arsred.check', """(async () => {
          const fixture = %s;
          const set = (id, v) => { const el = document.getElementById(id); el.value = v;
            el.dispatchEvent(new Event('input', { bubbles: true })); };
          set('orgnr', '5591620306');

          const dt = new DataTransfer();
          dt.items.add(new File([fixture], 'arsredovisning.xhtml',
                                { type: 'application/xhtml+xml' }));
          const input = document.getElementById('file-input');
          input.files = dt.files;
          input.dispatchEvent(new Event('change', { bubbles: true }));
          await new Promise(r => setTimeout(r, 700));

          const findings = [...document.querySelectorAll('#findings .ar-finding')].map(el => ({
            level: [...el.classList].find(c => c.startsWith('ar-') && c !== 'ar-finding').slice(3),
            title: el.querySelector('.ar-finding-title').textContent
          }));
          const out = {
            count: document.getElementById('findings-count').textContent,
            findings,
            errors: findings.filter(f => f.level === 'error').map(f => f.title),
            /* SHA-256 of the fixture, so a change to how the bytes are taken
               off the file shows up here rather than silently. */
            summary: document.getElementById('file-summary').textContent.replace(/\\s+/g, ' ').trim()
          };

          /* The orgnr in the form decides whose eget utrymme the document goes
             to; the one in the file decides whose report it is. */
          set('orgnr', '5560000001');
          await new Promise(r => setTimeout(r, 200));
          out.mismatchReported = [...document.querySelectorAll('#findings .ar-finding-title')]
            .some(e => e.textContent.includes('matchar inte filen'));
          return out;
        })()""" % json.dumps(FIXTURE)),

        ('arsred.bygg', """(async () => {
          const sie = %s;
          const dt = new DataTransfer();
          dt.items.add(new File([sie], 'bok.se', { type: 'text/plain' }));
          const input = document.getElementById('bygg-file-input');
          input.files = dt.files;
          input.dispatchEvent(new Event('change', { bubbles: true }));
          await new Promise(r => setTimeout(r, 500));

          const set = (id, v) => { const el = document.getElementById(id); el.value = v;
            el.dispatchEvent(new Event('input', { bubbles: true })); };
          /* Steget före lämnar med flit ett felaktigt organisationsnummer i del
             B för att visa att avvikelsen fångas. Det här steget handlar om
             bygget, så numret sätts till fixturens eget. */
          set('orgnr', '5591620306');
          set('bygg-sate', 'Uppsala');
          set('bygg-verksamhet', 'Konsultverksamhet.');
          set('bygg-anstallda', '1');
          set('bygg-ort', 'Uppsala');
          set('bygg-datum', '2026-10-15');
          /* Klart-datumet lämnas tomt med flit: det ska falla tillbaka på
             stämmans datum, och saknas även det på underskriftsdatumet. */
          const person = document.querySelector('.bygg-person');
          person.querySelector('.bygg-tilltalsnamn').value = 'Anna';
          person.querySelector('.bygg-efternamn').value = 'Andersson';
          person.querySelector('.bygg-roll').value = 'Styrelseledamot';
          person.querySelector('.bygg-efternamn').dispatchEvent(new Event('input', { bubbles: true }));

          const out = {
            /* Vad filen sade om sig själv, och hur många konton som kom med. */
            kalla: document.getElementById('bygg-kalla').textContent.replace(/\\s+/g, ' ').trim(),
            kontorader: document.querySelectorAll('.bygg-konton tbody tr').length,
            okopplade: document.querySelectorAll('.bygg-konton tr.bygg-okopplad').length,
            /* Uppställningen ska gå ihop av sig själv: taxonomins summeringar
               ska ge samma årsresultat i båda räkningarna. */
            uppstallning: (document.querySelector('#bygg-uppstallning .ar-ok-mark') || {}).textContent
              || [...document.querySelectorAll('#bygg-uppstallning .ar-problem li')].map(e => e.textContent),
            disposition: {
              balanserat: document.getElementById('bygg-disp-balanserat').value,
              arets: document.getElementById('bygg-disp-arets').value,
              nyrakning: document.getElementById('bygg-disp-nyrakning').value,
              summa: document.getElementById('bygg-disp-summa').textContent
            },
            brister: [...document.querySelectorAll('#bygg-brister li')].map(e => e.textContent),
            /* Källmärkningen: vilket fält som fick sitt värde varifrån. */
            kallor: [...document.querySelectorAll('#arsred input[data-kalla], '
              + '#arsred textarea[data-kalla], #arsred select[data-kalla]')]
              .map(el => el.id + '=' + el.dataset.kalla).sort()
          };

          document.querySelector('[data-on-click="bygg:generera"]').click();
          await new Promise(r => setTimeout(r, 200));
          out.skriven = document.getElementById('bygg-resultat').textContent
            .replace(/\\s+/g, ' ').trim();

          /* Hela poängen: handlingen sidan skriver ska klara sidans egen
             granskning utan gräddfil. */
          document.getElementById('bygg-anvand').click();
          await new Promise(r => setTimeout(r, 900));
          out.egenGranskning = document.getElementById('findings-count').textContent;
          out.anmarkningar = [...document.querySelectorAll('#findings .ar-finding')]
            .map(el => ({
              level: [...el.classList].find(c => c.startsWith('ar-') && c !== 'ar-finding').slice(3),
              title: el.querySelector('.ar-finding-title').textContent
            }))
            .filter(f => f.level !== 'ok');
          return out;
        })()""" % json.dumps(SIE_FIXTURE)),
        ('arsred.tidigare', """(async () => {
          /* En liten Word-fil byggd med sidans egen zip-skrivare och läst med
             dess zip-läsare: de två har aldrig setts utanför det här steget,
             och en docx som inte går att öppna är inte värd mycket. */
          const E = KVOT_ARSRED_EXPORT;
          const p = (t) => `<w:p><w:r><w:t xml:space="preserve">${t}</w:t></w:r></w:p>`;
          const tc = (t) => `<w:tc>${p(t)}</w:tc>`;
          const tr = (cells) => `<w:tr>${cells.map(tc).join('')}</w:tr>`;
          const doc = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
${p('Allmänt om verksamheten Bolaget bedriver konsultverksamhet inom riskanalys.')}
${p('Företaget har sitt säte i Uppsala.')}
${p('Flerårsöversikt (Tkr)')}
<w:tbl>${tr(['', '2024/25', '2023/24', '2022/23'])}${tr(['Nettoomsättning', '1 859', '1 849', '1 769'])}${tr(['Resultat efter finansiella poster', '755', '774', '869'])}${tr(['Soliditet (%)', '93,0', '92,9', '92,3'])}</w:tbl>
${p('disponeras så att till aktieägare utdelas (893 kronor per aktie)')}
${p('446 500')}
${p('Styrelsen anser att förslaget är förenligt med försiktighetsregeln i 17 kap. 3 § aktiebolagslagen.')}
${p('Allmänna upplysningar')}
${p('Årsredovisningen är upprättad i enlighet med årsredovisningslagen.')}
${p('Not 2 Medelantalet anställda')}
<w:tbl>${tr(['', '2024-07-01', '2023-07-01'])}${tr(['', '-2025-06-30', '-2024-06-30'])}${tr(['Medelantalet anställda', '1', '2'])}</w:tbl>
${p('Uppsala den 1 oktober 2026')}
${p('Anna Andersson')}
${p('Styrelseledamot')}
</w:body></w:document>`;
          const utf8 = (t) => new TextEncoder().encode(t);
          const zip = E.zipStore([
            { name: '[Content_Types].xml', data: utf8('<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>') },
            { name: 'word/document.xml', data: utf8(doc) },
          ]);

          const dt = new DataTransfer();
          dt.items.add(new File([zip], 'fjolaret.docx'));
          const input = document.getElementById('tidigare-file-input');
          input.files = dt.files;
          input.dispatchEvent(new Event('change', { bubbles: true }));
          await new Promise(r => setTimeout(r, 900));

          const forslag = [...document.querySelectorAll('#tidigare-resultat tbody tr')]
            .map(row => ({
              uppgift: row.children[1].textContent.trim(),
              varde: row.children[2].textContent.trim().slice(0, 70),
              kalla: row.children[3].textContent.trim()
            }));

          /* Ingenting får fyllas i förrän man ber om det. Antalet aktier är
             fältet att titta på: steget före fyller i sätet, så det säger
             ingenting om vem som skrev dit det. */
          const foreInnan = document.getElementById('bygg-antal-aktier').value;
          document.querySelector('[data-on-click="tidigare:anvand"]').click();
          await new Promise(r => setTimeout(r, 200));

          return {
            forslag,
            tomtInnanAnvand: foreInnan === '',
            efter: {
              sate: document.getElementById('bygg-sate').value,
              ort: document.getElementById('bygg-ort').value,
              aktier: document.getElementById('bygg-antal-aktier').value,
              ar2: document.getElementById('bygg-ar2-netto').value,
              ar3: document.getElementById('bygg-ar3-netto').value,
              person: [...document.querySelectorAll('.bygg-person')].map(el =>
                [el.querySelector('.bygg-tilltalsnamn').value,
                 el.querySelector('.bygg-efternamn').value,
                 el.querySelector('.bygg-roll').value].join('/'))
            }
          };
        })()"""),
        ('arsred.export', """(() => {
          const E = KVOT_ARSRED_EXPORT;
          const doc = E.blocksFromIxbrl(KVOT_ARSRED_BYGG_UI.state.ixbrl);
          const docx = E.buildDocx(doc);
          const pdf = E.buildPdf(doc);
          return {
            /* Exporten läses ur handlingen, så blocken ska vara de avsnitt
               årsredovisningen faktiskt består av. */
            blocks: doc.blocks.length,
            typer: doc.blocks.reduce((a, b) => { a[b.type] = (a[b.type] || 0) + 1; return a; }, {}),
            titel: doc.title,
            docxType: docx.type,
            pdfType: pdf.type,
            /* En docx är en zip; en PDF börjar med sin versionsrad. Storleken
               spelar ingen roll, men att de är vad de utger sig för gör det. */
            docxRimlig: docx.size > 4000,
            pdfRimlig: pdf.size > 2000,
            /* Teckenbredderna styr både radbrytning och högerställda belopp. */
            breddNettoomsattning: Math.round(E.textWidth('Nettoomsättning', 'roman', 10.5) * 100) / 100,
            radbrytning: E.wrap('ett två tre fyra fem sex sju åtta nio tio', 60, 'roman', 10.5).length
          };
        })()"""),

        ('arsred.utkast', """(async () => {
          const U = KVOT_ARSRED_UTKAST;
          const sparat = U.snapshot();
          /*
            Löftet är att personnummer aldrig lagras. Det stod tidigare om
            fälten i steg B3; sedan inlämningsdelen togs bort finns inget
            sådant fält kvar på sidan alls. Båda halvorna av löftet prövas
            därför: att inget av de fälten finns, och att inget av dem heller
            skulle följa med om det kom tillbaka. Det är den enda raden i det
            här steget som är en utfästelse och inte en observation, så den
            står först.
          */
          const pnrFalt = U.ALDRIG.filter(id => document.getElementById(id));
          const pnrLackt = U.ALDRIG.some(id => id in (sparat.falt || {}));
          U.spara();
          const iLagring = U.last();

          /* Töm sidan och lägg tillbaka utkastet, som efter en omladdning. */
          document.querySelector('[data-on-click="bygg:rensa"]').click();
          document.getElementById('bygg-verksamhet').value = '';
          document.getElementById('bygg-ort').value = '';
          await new Promise(r => setTimeout(r, 200));
          const tomtEmellan = document.getElementById('bygg-verksamhet').value === ''
            && document.querySelectorAll('.bygg-konton tbody tr').length === 0;
          U.restore(iLagring);
          await new Promise(r => setTimeout(r, 400));

          return {
            pnrLackt,
            pnrFalt,
            faltSparade: Object.keys(sparat.falt).length,
            personer: sparat.personer.length,
            kontonISnapshot: sparat.bok.koppling.length,
            tomtEmellan,
            aterstallt: {
              verksamhet: document.getElementById('bygg-verksamhet').value.slice(0, 30),
              ort: document.getElementById('bygg-ort').value,
              konton: document.querySelectorAll('.bygg-konton tbody tr').length,
              brister: [...document.querySelectorAll('#bygg-brister li')].map(e => e.textContent)
            }
          };
        })()"""),
    ],

    'inkomstdeklaration.html': [
        ('sru.static', """(() => ({
          modul: typeof KVOT_SRU,
          deklarationer: [...document.querySelectorAll('#sru-deklaration option')].map(o => o.value),
          perioder: document.querySelectorAll('#sru-period option').length,
          /* Blanketterna i den valda deklarationen, med sina fältkodsantal ur
             Skatteverkets egna fältnamnstabeller. */
          blanketter: [...document.querySelectorAll('.sru-blankett summary')]
            .map(s => s.textContent.replace(/\\s+/g, ' ').trim()),
          scopeItems: document.querySelectorAll('.ar-scope li').length,
          /* Väljaren följer valet i steg 1: en enskild näringsidkares K6 har
             inget i ett aktiebolags inlämning att göra, och INK3R hör till en
             annan deklaration. Kryssrutan visar hela utgåvan ändå. */
          valjare: [...document.querySelectorAll('#sru-lagg-till optgroup')]
            .map(g => g.label + ': ' + [...g.querySelectorAll('option')]
              .map(o => o.value).join(',')),
          valjNot: document.getElementById('sru-valj-not').textContent,
          /* Blankettnamnen är skrivna för hand i generatorn — fältnamns-
             tabellen bär bara SKV-numret. */
          beskrivningar: Object.keys(KVOT_SRU_DATA.BESKRIVNING).length,
          ink2r: KVOT_SRU.beskrivning('INK2R'),
          /* Sekelsiffran är den tysta fällan: ett aktiebolag skrivs med 16
             först, en fysisk person med 19 eller 20. Utan den avvisas filen. */
          identitet: {
            bolag: KVOT_SRU.identitet('559162-0306'),
            person: KVOT_SRU.identitet('8001019812'),
            redan: KVOT_SRU.identitet('165591620306')
          },
          /* Konto 8999 hör till både vinst- och förlustraden; uppslagningen
             måste lämna båda och låta beloppet avgöra. */
          resultatkontot: KVOT_SRU.kopplingarFor('8999', KVOT_SRU_DATA.BAS.INK2),
          /* Beskattningsperioden bestäms av räkenskapsårets sista dag enligt
             skatteförfarandelagen, inte av årtalet. Att gissa årtalet plus P4
             gav en period som inte var öppen, och Skatteverkets besked var
             bara att blankettypen var ogiltig. */
          perioder: ['2026-04-30', '2026-06-30', '2026-08-31', '2026-09-01', '2025-12-31']
            .map(d => d + '=' + KVOT_SRU.periodFor(d)),
          oppning: KVOT_SRU.oppning('2026P2'),
          hamtaAvstangd: document.getElementById('sru-hamta-info').disabled
        }))()"""),

        ('sru.bygg', """(async () => {
          const sie = %s;
          const dt = new DataTransfer();
          dt.items.add(new File([sie], 'bok.se', { type: 'text/plain' }));
          const input = document.getElementById('sru-file-input');
          input.files = dt.files;
          input.dispatchEvent(new Event('change', { bubbles: true }));
          await new Promise(r => setTimeout(r, 600));

          const schema = [...document.querySelectorAll('.sru-blankett')]
            .find(d => d.querySelector('summary b').textContent === 'INK2R');
          const rader = [...schema.querySelectorAll('tbody tr')]
            .filter(tr => tr.querySelector('input').value)
            .map(tr => tr.children[0].textContent + '=' + tr.querySelector('input').value
                       + ' (' + tr.children[4].textContent + ')');

          const set = (id, v) => { const el = document.getElementById(id); el.value = v;
            el.dispatchEvent(new Event('input', { bubbles: true })); };
          set('lev-adress', 'Valhallagatan 16');
          set('lev-postnr', '75334');
          set('lev-postort', 'Uppsala');
          set('lev-kontakt', 'Anna Andersson');

          document.querySelector('[data-on-click="sru:bygg"]').click();
          await new Promise(r => setTimeout(r, 200));
          const filer = [...document.querySelectorAll('#sru-filer pre')].map(p => p.textContent);

          /* Filen ska vara ISO 8859-1 med CRLF, inte UTF-8 — ett ö som blir
             två byte gör filen oläslig för Skatteverket. */
          const bytes = KVOT_SRU.latin1('Ekström\\r\\n');

          /* Vinst eller förlust på 3.26/3.27 var fel på första försöket, och
             felet syntes inte på annat sätt än att en annan fältkod stod i
             filen. Konto 8999 debiteras vid vinst, tvärtemot alla andra
             resultatkonton, så båda utfallen prövas med belopp. */
          const par = (saldo) => {
            const v = KVOT_SRU.faltvarden(
              [{ konto: '8999', namn: 'Årets resultat', typ: 'resultat', res: saldo, ub: 0 }],
              'INK2').varden;
            return [...v].map(([k, b]) => k + '=' + b).join(',') || 'inget';
          };

          /*
            Justeringssidan fylls så långt det går mekaniskt: årets resultat
            och den bokförda skatten flyttas från räkenskapsschemat, och sista
            raden summeras ur de andra med blankettens egna tecken. Resten är
            bedömningar och ska stå tomma.
          */
          const s2 = [...document.querySelectorAll('.sru-blankett')]
            .find(d => d.querySelector('summary b').textContent === 'INK2S');
          const justering = [...s2.querySelectorAll('tbody tr')]
            .filter(tr => tr.querySelector('input').value)
            .map(tr => tr.children[0].textContent + '=' + tr.querySelector('input').value
                       + ' (' + tr.children[4].textContent + ')');
          /* Och summan ska följa med när något skrivs in ovanför. */
          const ejAvdragsgill = s2.querySelector('input[data-kod="7653"]');
          ejAvdragsgill.value = '5000';
          ejAvdragsgill.dispatchEvent(new Event('input', { bubbles: true }));
          const efterJustering = s2.querySelector('input[data-kod="7670"]').value;

          /*
            Huvudblanketten hämtar två tal ur justeringssidan — INK2S 4.15
            säger själv att överskottet flyttas till punkt 1.1 — och ska följa
            med samma tangenttryckning. Räkenskapsårets datum fylls på varje
            blankett som har fältkoderna, men ett block som bara bär sina två
            datum har inget att lämna och ska inte komma med i filen.
          */
          const s1 = [...document.querySelectorAll('.sru-blankett')]
            .find(d => d.querySelector('summary b').textContent === 'INK2');
          const huvud = [...s1.querySelectorAll('tbody tr')]
            .filter(tr => tr.querySelector('input').value)
            .map(tr => tr.children[0].textContent + '=' + tr.querySelector('input').value
                       + ' (' + tr.children[4].textContent + ')');

          /*
            Delägaruppgifter ska lämnas ett #BLANKETT per delägare, vilket
            Skatteverket är uttrycklig med. Blanketterna hålls därför som en
            lista och inte som en karta per namn — en karta kan inte bära två
            av samma.
          */
          const valjTill = document.getElementById('sru-lagg-till');
          /* INK4DU hör till en annan deklaration och syns inte i urvalet för
             INK2 — hela utgåvan måste visas först. */
          const utanAlla = !!valjTill.querySelector('option[value="INK4DU"]');
          const kryss = document.getElementById('sru-alla');
          kryss.checked = true;
          kryss.dispatchEvent(new Event('change', { bubbles: true }));
          for (let i = 0; i < 2; i++) {
            valjTill.value = 'INK4DU';
            valjTill.dispatchEvent(new Event('change', { bubbles: true }));
          }
          const duBlock = [...document.querySelectorAll('.sru-blankett')]
            .filter(d => d.querySelector('summary b').textContent === 'INK4DU');
          duBlock.forEach((d, i) => {
            const inp = d.querySelector('tbody input');
            inp.value = String(1000 + i);
            inp.dispatchEvent(new Event('input', { bubbles: true }));
          });

          /* Filen byggdes innan blocken fanns, så den måste byggas om. */
          document.querySelector('[data-on-click="sru:bygg"]').click();
          await new Promise(r => setTimeout(r, 200));
          const filerEfter = [...document.querySelectorAll('#sru-filer pre')].map(p => p.textContent);

          /* Och en fil ska gå att läsa tillbaka. */
          const rad = ['#BLANKETT INK2S-2025P4', '#IDENTITET 165591620306 20251101 090000',
                       '#UPPGIFT 7650 12000', '#BLANKETTSLUT', '#FIL_SLUT'].join('\\r\\n');
          const last = KVOT_SRU.lasBlanketterSru(rad);
          const inlast = last.block.map(b => b.namn + '-' + b.period + ':'
            + [...b.varden].map(([k, v]) => k + '=' + v).join(','));

          /* Fel period ska påpekas här, inte av Skatteverket. */
          const valj = document.getElementById('sru-period');
          valj.value = '2026P4';
          valj.dispatchEvent(new Event('change', { bubbles: true }));
          const felPeriod = document.getElementById('sru-periodnot').textContent
            .replace(/\\s+/g, ' ').trim();
          valj.value = KVOT_SRU.periodFor('2026-06-30');
          valj.dispatchEvent(new Event('change', { bubbles: true }));

          return {
            vinst: par(120000),
            forlust: par(-45000),
            felPeriod,
            justering,
            efterJustering,
            huvud,
            utanAlla,
            inlast,
            inlastFel: last.fel,
            delagarblock: duBlock.length,
            period: document.getElementById('sru-period').value,
            rader,
            okopplade: document.getElementById('sru-okopplade').hidden
              ? 'inga' : document.getElementById('sru-okopplade').textContent.trim(),
            kontroll: document.getElementById('sru-kontroll').textContent
              .replace(/\\s+/g, ' ').trim(),
            info: filer[0],
            blanketter: filer[1],
            latin1: [...bytes].join(','),
            hamtaAvstangd: document.getElementById('sru-hamta-info').disabled,
            /* Varje delägare ska ha ett eget blankettblock i filen. */
            duIFilen: (filerEfter[1].match(/#BLANKETT INK4DU/g) || []).length
          };
        })()""" % json.dumps(SIE_FIXTURE)),
    ],

    'uppsala.html': [
        ('sl.board', """(() => ({
          module: typeof KVOT_SL,
          refreshMs: typeof KVOT_SL === 'object' ? KVOT_SL.REFRESH_MS : null,
          relation: (document.querySelector('.sl-relation') || {}).textContent?.replace(/\\s+/g, ' ').trim(),
          attribution: !!document.querySelector('.sl-attribution a[href*="trafiklab.se"]'),
          otherWay: (document.querySelector('.sl-other a') || {}).getAttribute?.('href'),
          /* The whole point of the keyless API: nothing that looks like a key
             may ever be pasted into the page. */
          keyInPage: /api[_-]?key/i.test(document.documentElement.outerHTML),
          /* The Trafikverket key is 32 hex characters. It lives in the
             Worker's secret store; if one ever appears in the page itself,
             this is what catches it, because the page is world-readable. */
          secretInPage: /\b[0-9a-f]{32}\b/.test(document.documentElement.outerHTML),
          livePositions: !!(document.querySelector('.sl-board') || {}).__slBoard?.config?.trainsUrl,
          boardMounted: !!document.querySelector('.sl-board .sl-body'),
          states: Object.keys(typeof KVOT_SL === 'object' ? KVOT_SL.STATE_LABEL : {}).length,
          track: !!document.querySelector('.sl-track-svg'),
          stations: document.querySelectorAll('.sl-station').length,
          lanes: document.querySelectorAll('.sl-lane-label').length,
          legend: !!document.querySelector('.sl-legend'),
          staleMs: typeof KVOT_SL === 'object' ? KVOT_SL.STALE_MS : null,
          idleMs: typeof KVOT_SL === 'object' ? KVOT_SL.IDLE_MS : null
        }))()"""),
    ],

    'solna.html': [
        ('sl.board', """(() => ({
          module: typeof KVOT_SL,
          refreshMs: typeof KVOT_SL === 'object' ? KVOT_SL.REFRESH_MS : null,
          relation: (document.querySelector('.sl-relation') || {}).textContent?.replace(/\\s+/g, ' ').trim(),
          attribution: !!document.querySelector('.sl-attribution a[href*="trafiklab.se"]'),
          otherWay: (document.querySelector('.sl-other a') || {}).getAttribute?.('href'),
          /* The whole point of the keyless API: nothing that looks like a key
             may ever be pasted into the page. */
          keyInPage: /api[_-]?key/i.test(document.documentElement.outerHTML),
          /* The Trafikverket key is 32 hex characters. It lives in the
             Worker's secret store; if one ever appears in the page itself,
             this is what catches it, because the page is world-readable. */
          secretInPage: /\b[0-9a-f]{32}\b/.test(document.documentElement.outerHTML),
          livePositions: !!(document.querySelector('.sl-board') || {}).__slBoard?.config?.trainsUrl,
          boardMounted: !!document.querySelector('.sl-board .sl-body'),
          states: Object.keys(typeof KVOT_SL === 'object' ? KVOT_SL.STATE_LABEL : {}).length,
          track: !!document.querySelector('.sl-track-svg'),
          stations: document.querySelectorAll('.sl-station').length,
          lanes: document.querySelectorAll('.sl-lane-label').length,
          legend: !!document.querySelector('.sl-legend'),
          staleMs: typeof KVOT_SL === 'object' ? KVOT_SL.STALE_MS : null,
          idleMs: typeof KVOT_SL === 'object' ? KVOT_SL.IDLE_MS : null
        }))()"""),
    ],

    'skb_qa_summary.html': [
        ('qa.helpers', """(() => ({
          privacyNote: (document.querySelector('.privacy') || {}).textContent,
          headerTitle: (document.querySelector('header .title') || {}).textContent,
          filterIds: [...document.querySelectorAll('.field select, .field input')].map(e => e.id),
          dropzone: !!document.getElementById('dropzone'),
          xlsx: typeof XLSX,
          workspaceHidden: (document.getElementById('workspace') || {}).className,
          normalize: typeof normalize === 'function' ? normalize('  OK  ') : null,
          esc: typeof esc === 'function' ? esc('<b>&x</b>') : null,
          csvCell: typeof csvCell === 'function' ? csvCell('a"b') : null
        }))()"""),
    ],

    'karaoke.html': [
        ('karaoke.dom', """(() => ({
          lang: document.documentElement.lang,
          controls: [...document.querySelectorAll('button, input, select')].map(e => e.id).filter(Boolean),
          playerWrap: !!document.getElementById('yt-player-wrap'),
          lyricStage: !!document.getElementById('lyric-stage'),
          globals: ['lyricRows', 'timeShift', 'videoId', 'player']
            .map(n => n + '=' + typeof window[n])
        }))()"""),
    ],
}


async def main():
    label = sys.argv[1] if len(sys.argv) > 1 else 'site_before'
    only = sys.argv[2] if len(sys.argv) > 2 else None
    ver = json.load(urllib.request.urlopen('http://127.0.0.1:9222/json/version'))
    fingerprint = {}

    for page, steps in PAGES.items():
        if only and page != only:
            continue
        async with websockets.connect(ver['webSocketDebuggerUrl'], max_size=300 * 1024 * 1024) as bws:
            tid, drv = await open_page(bws, url='http://127.0.0.1:8765/' + page, settle=7)
            # The theme-toggle step below persists a choice; clear it so the
            # 'storedTheme' reading does not depend on which run came before.
            await drv.ev("try { localStorage.removeItem('kvot-theme'); } catch (e) {} 'cleared'")
            for name, expr in SHARED + steps:
                key = '%s::%s' % (page, name)
                try:
                    fingerprint[key] = await drv.ev(expr, timeout=120)
                except Exception as exc:
                    fingerprint[key] = 'HARNESS ERROR: %s' % exc
                head = json.dumps(fingerprint[key], sort_keys=True) if not isinstance(fingerprint[key], str) \
                    else fingerprint[key]
                print('  %-42s %s' % (key, head[:96]))
            fingerprint['%s::_console' % page] = summarise_console(drv.logs)
            await bws.send(json.dumps({'id': 99, 'method': 'Target.closeTarget', 'params': {'targetId': tid}}))

    with open('%s.json' % label, 'w') as fh:
        json.dump(fingerprint, fh, indent=1, sort_keys=True)
    consoles = {k: v for k, v in fingerprint.items() if k.endswith('_console') and v}
    print('\nwrote %s.json' % label)
    for k, v in consoles.items():
        print('  %s:' % k)
        for line in v[:4]:
            print('     ', line)

asyncio.run(main())
