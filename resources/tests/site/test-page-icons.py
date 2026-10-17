#!/usr/bin/env python3
"""Every page has an icon for an iPhone's home screen, and the pages with a
mark of their own have it in the tab too.

    python3 resources/tests/site/test-page-icons.py

An iPhone puts a page saved to its home screen there with the picture its
`apple-touch-icon` link names, 180 x 180; without one it draws the title's
first letter on a grey tile (Glosor showed a "G", 2026-10-17). So for every
published page (the .html files at the top of the repository, but the 404
page, which nobody saves):

  * there is exactly one apple-touch-icon link, to a 180 x 180 PNG that is
    the drawing, in the kvot mark's three tones;
  * it is the page's own mark where the page has one (the table below), and
    the kvot mark (kvot-icon-180.png, scripts/gen-kvot-touch-icon.py)
    everywhere else;
  * a tab icon in SVG is well-formed XML (a "--" in a comment makes the
    browser drop it silently) and has a 32 x 32 PNG beside it for anything
    that will not take an SVG;
  * a page whose icon is drawn by scripts/kvot_icon.py says what to call it
    on the home screen (apple-mobile-web-app-title).

No server and no browser: the links are read from the files, and the PNGs
decoded by scripts/kvot_icon.py. Exit status is 0 when every check passes.
"""
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'scripts'))
import kvot_icon as K  # noqa: E402

# A page with a mark of its own: its touch icon, and whether its icon is one
# of those drawn from blocks by scripts/kvot_icon.py (which name themselves).
OWN = {
    'dose_coefficients.html': ('resources/images/dose-icon-180.png', False),
    'ensdf.html': ('resources/images/ensdf-icon-180.png', False),
    'flashcards.html': ('resources/images/flashcards-icon-180.png', True),
    'gitarr.html': ('resources/images/gitarr-icon-180.png', True),
    'kompartment.html': ('kompartment/icon-180.png', False),
    'rb.html': ('resources/images/rb-icon-180.png', False),
    'smui.html': ('resources/images/smui-icon-180.png', False),
    'solna.html': ('resources/images/sl-icon-180.png', True),
    'uppsala.html': ('resources/images/sl-icon-180.png', True),
    'winnetkakort.html': ('resources/images/winnetkakort-icon-180.png', True),
}
KVOT = 'resources/images/kvot-icon-180.png'

checks = 0
failures = []


def check(label, got, want=True):
    global checks
    checks += 1
    ok = got == want
    print(f'{"ok  " if ok else "FAIL"}  {label}' + ('' if ok else f': {got!r} (expected {want!r})'))
    if not ok:
        failures.append(label)


def links(html, rel):
    """The href of every <link> whose rel is exactly `rel`."""
    out = []
    for tag in re.findall(r'<link\b[^>]*>', html):
        r = re.search(r'\brel="([^"]*)"', tag)
        h = re.search(r'\bhref="([^"]*)"', tag)
        if r and h and r.group(1) == rel:
            out.append(h.group(1))
    return out


def local(href):
    return ROOT / href.lstrip('./').lstrip('/') if href.startswith(('./', '/')) else ROOT / href


def is_drawing(png, size):
    """The right size and the three tones there (each at least 0.4 per cent):
    a picture of the drawing, not a blank or a broken-image glyph."""
    w, h, share = K.tones(png)
    return (w, h) == (size, size) and share is not None and all(v >= 0.004 for v in share.values())


pages = sorted(p for p in subprocess.run(['git', 'ls-files', '*.html'], cwd=ROOT, capture_output=True, text=True,
                                         check=True).stdout.split() if '/' not in p and p != '404.html')
check('the pages are found', len(pages) > 20)
seen_png = {}
for page in pages:
    html = (ROOT / page).read_text(encoding='utf-8')
    touch = links(html, 'apple-touch-icon')
    want, drawn = OWN.get(page, (KVOT, False))
    check(f'{page}: one touch icon, {want}', [local(h).relative_to(ROOT).as_posix() for h in touch], [want])
    if touch and touch[0] not in seen_png:
        seen_png[touch[0]] = local(touch[0]).exists() and is_drawing(local(touch[0]), 180)
    if touch:
        check(f'{page}: the touch icon is a 180 x 180 picture of the drawing', seen_png[touch[0]])
    icons = links(html, 'icon')
    check(f'{page}: one tab icon', len(icons), 1)
    if icons and icons[0].endswith('.svg'):
        svg = local(icons[0])
        try:
            ok = ET.parse(svg).getroot().tag.endswith('svg')
        except (ET.ParseError, OSError):
            ok = False
        check(f'{page}: its SVG icon is well-formed', ok)
        small = links(html, 'alternate icon')
        check(f'{page}: and has a 32 x 32 PNG beside it', bool(small) and local(small[0]).exists() and is_drawing(local(small[0]), 32))
    if drawn:
        title = re.search(r'<meta name="apple-mobile-web-app-title" content="([^"]+)">', html)
        check(f'{page}: it says what to call it on the home screen', bool(title))

print(f'\n{checks - len(failures)} of {checks} checks passed.')
sys.exit(1 if failures else 0)
