"""The maps follow the site's light/dark switch.

Both maps on the site - the coordinate map on proj.html and the office map in
every page's footer - used to be nailed to Jawg's light cartography, so a
visitor in dark mode got a glaring white rectangle. They now take their basemap
from KVOT.themedTileLayer, which re-points the layer on kvot-theme-change.

The cases below are the ones that were easy to get wrong:

  - the switch re-points the tiles in both directions, not just into dark;
  - it does not reset the view, because Leaflet is asked for new images and not
    for a new map - a switch that recentred the map would be its own bug;
  - the street layer follows the theme while it is off the map (proj.html shows
    satellite), so it comes back in the theme in force rather than the one it
    was built in;
  - the zone outlines follow too. They are drawn in a class and coloured from
    CSS for exactly this reason: the light-mode goldenrod sinks into the dark
    basemap, and a redraw-on-theme-change would have been the alternative.

Run a static server on 8765 and headless Chrome on 9222 first - see README.md.
"""
import asyncio, json, sys, urllib.request, websockets

from driver import open_page

# The layer's own URL, the tiles actually in the DOM, where the map is looking,
# and what colour the RT 90 outline is being drawn in.
PROJ_PROBE = """(() => {
  const paths = [...document.querySelectorAll('#coord-map path.zone-rt90')];
  const c = map.getCenter();
  return JSON.stringify({
    layerUrl: map._baseLayers.street._url,
    activeBase: map._activeBase,
    tileStyles: [...new Set([...document.querySelectorAll('#coord-map img.leaflet-tile')]
      .map(i => (i.src.match(/tile\\.jawg\\.io\\/([a-z-]+)\\//) || [])[1])
      .filter(Boolean))].sort(),
    center: [c.lat.toFixed(5), c.lng.toFixed(5)].join(','),
    zoom: map.getZoom(),
    zoneStroke: paths.length ? getComputedStyle(paths[0]).stroke : null
  });
})()"""

FOOTER_PROBE = """(() => JSON.stringify({
  tileStyles: [...new Set([...document.querySelectorAll('#kvotmap img.leaflet-tile')]
    .map(i => (i.src.match(/tile\\.jawg\\.io\\/([a-z-]+)\\//) || [])[1])
    .filter(Boolean))].sort()
}))()"""


CHECKS = [0]


def check(failures, label, got, want):
    CHECKS[0] += 1
    ok = got == want
    if not ok:
        failures.append((label, want, got))
    print('  %-46s %-24s %s' % (label, got, 'OK' if ok else 'WANTED ' + str(want)))


async def set_theme(page, theme):
    """Drive the theme through the site's own toggle, not by setting the
    attribute: the toggle is what a visitor has, and it is what fires the event
    the tile layers listen for. Which theme the page opens in depends on the
    host's system setting, so this toggles only when it has to."""
    got = await page.ev(
        "(KVOT.currentTheme() !== '%s' && KVOT.toggleTheme(), KVOT.currentTheme())" % theme)
    assert got == theme, 'wanted theme %s, got %s' % (theme, got)
    await asyncio.sleep(2)


async def proj_case(bws, failures):
    print('proj.html - coordinate map')
    tid, page = await open_page(bws, 'http://127.0.0.1:8765/proj.html', settle=7)
    try:
        # Put a zone outline on the map so there is something to measure.
        await page.ev("show_rt90_meridian('rt90_2.5_gon_v')")
        await set_theme(page, 'light')
        before = json.loads(await page.ev(PROJ_PROBE))
        check(failures, 'light: layer url style', style_of(before['layerUrl']), 'jawg-light')
        check(failures, 'light: tiles in the DOM', before['tileStyles'], ['jawg-light'])
        light_stroke = before['zoneStroke']

        await set_theme(page, 'dark')
        dark = json.loads(await page.ev(PROJ_PROBE))
        check(failures, 'dark: layer url style', style_of(dark['layerUrl']), 'jawg-dark')
        check(failures, 'dark: tiles in the DOM', dark['tileStyles'], ['jawg-dark'])
        check(failures, 'dark: view is unmoved', [dark['center'], dark['zoom']],
              [before['center'], before['zoom']])
        check(failures, 'dark: zone outline changed colour', dark['zoneStroke'] != light_stroke, True)

        # The street layer is off the map while satellite shows; it still has to
        # come back in the theme in force.
        await page.ev('map_toggle_layer()')
        await asyncio.sleep(1)
        await set_theme(page, 'light')
        await page.ev('map_toggle_layer()')
        await asyncio.sleep(2)
        back = json.loads(await page.ev(PROJ_PROBE))
        check(failures, 'back from satellite: layer url', style_of(back['layerUrl']), 'jawg-light')
        check(failures, 'back from satellite: tiles', back['tileStyles'], ['jawg-light'])
        check(failures, 'back from satellite: base layer', back['activeBase'], 'street')
    finally:
        await page.send('Target.closeTarget', {'targetId': tid})


async def footer_case(bws, failures):
    print('index.html - office map in the footer')
    tid, page = await open_page(bws, 'http://127.0.0.1:8765/index.html', settle=5)
    try:
        await set_theme(page, 'light')
        await page.ev('KVOT.toggleMap()')
        await asyncio.sleep(4)
        before = json.loads(await page.ev(FOOTER_PROBE))
        check(failures, 'light: tiles in the DOM', before['tileStyles'], ['jawg-light'])
        await set_theme(page, 'dark')
        after = json.loads(await page.ev(FOOTER_PROBE))
        check(failures, 'dark: tiles in the DOM', after['tileStyles'], ['jawg-dark'])
        # Leaflet's own furniture is white by default; kvot.css tints it.
        attrib = await page.ev(
            "getComputedStyle(document.querySelector('#kvotmap .leaflet-control-attribution'))"
            ".backgroundColor")
        check(failures, 'dark: attribution is not white', attrib not in ('rgba(255, 255, 255, 0.8)',
                                                                        'rgb(255, 255, 255)'), True)
    finally:
        await page.send('Target.closeTarget', {'targetId': tid})


def style_of(url):
    import re
    m = re.search(r'tile\.jawg\.io/([a-z-]+)/', url or '')
    return m.group(1) if m else url


async def main():
    ver = json.load(urllib.request.urlopen('http://127.0.0.1:9222/json/version'))
    failures = []
    async with websockets.connect(ver['webSocketDebuggerUrl'], max_size=100 * 1024 * 1024) as bws:
        await proj_case(bws, failures)
        print()
        await footer_case(bws, failures)
    print()
    print('%d checks, %d failed' % (CHECKS[0], len(failures)))
    for label, want, got in failures:
        print('  FAILED: %s -> wanted %s, got %s' % (label, want, got))
    sys.exit(1 if failures else 0)


asyncio.run(main())
