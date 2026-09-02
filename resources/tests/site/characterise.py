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
          const fields = [...document.querySelectorAll('#logn input')].filter(i => i.offsetParent !== null);
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
