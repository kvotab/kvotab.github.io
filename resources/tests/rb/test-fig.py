#!/usr/bin/env python3
"""MATLAB figure files (.fig): the figure's objects in the tree, the figure drawn.

A figure file is a MAT-file whose variable hgS_070000 holds the figure as a
tree of structs (rb-fig.js has the layout). The files read here:

    fixtures/figure-plot.fig       written by MATLAB R2023a (fig_fixtures.m):
    fixtures/figure-kinds.fig      lines with a legend and TeX labels; bars,
    fixtures/figure-controls.fig   log axes, a surface in 3-D, an image, colour
    fixtures/figure-two.fig        bars, contours and a pie; a window of
    fixtures/figure-compact.fig    controls; two figures in one file; a file
    fixtures/figure-tiled.fig      saved 'compact'; a tiled layout
    written by this script         a figure as releases before R2014b saved
                                   one, its legend an axes of its own; a
                                   hostile one; one nested too deep; a .fig
                                   that is no MAT-file

The checks read the tree the page wrote and the SVG it draws: each object a
group named by its place, type and label, its properties beside the objects
it holds; the figure drawn when the file, the figure or an object in it is
selected, that object set apart; an object clicked in the drawing selected
in the tree; the drawing saved as SVG and PNG. Nothing in a file reaches the
page as markup, and nothing in it runs.

Start the server and the browser as in README.md, then

    python3 resources/tests/rb/test-fig.py

Exit status is 0 when every check passes.
"""
import asyncio
import base64
import json
import os
import struct
import sys
import tempfile
import urllib.request
import zlib

import websockets

from driver import open_page

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, 'fixtures')

failures = []
checks = 0


def check(label, got, want=True):
    global checks
    checks += 1
    ok = got == want
    print(f'{"ok  " if ok else "FAIL"}  {label}' + ('' if ok else f': {got!r} (expected {want!r})'))
    if not ok:
        failures.append(label)


# --- Level 5 written here ----------------------------------------------------------
# Little-endian, uncompressed: a tag of type and size, the data, padding to
# eight bytes. Arrays inside a struct have no name.

def element(t, data):
    return struct.pack('<II', t, len(data)) + data + b'\0' * (-len(data) % 8)


def array(cls, dims, body, name=''):
    content = (element(6, struct.pack('<II', cls, 0)) + element(5, struct.pack(f'<{len(dims)}i', *dims))
               + element(1, name.encode('utf-8')) + body)
    return struct.pack('<II', 14, len(content)) + content


def num(values, dims=None):
    values = list(values)
    return array(6, dims or ([1, len(values)] if values else [0, 0]), element(9, struct.pack(f'<{len(values)}d', *values)))


def text(s):
    return array(4, [1 if s else 0, len(s)], element(4, s.encode('utf-16-le')))


def cell(items, dims=None):
    return array(1, dims or [1, len(items)], b''.join(items))


def struct_(fields, elements, dims=None, name=''):
    """A struct array: each element a dict of field -> array."""
    width = 64
    names = b''.join(f.encode('utf-8')[:width - 1].ljust(width, b'\0') for f in fields)
    body = element(5, struct.pack('<i', width)) + element(1, names) + b''.join(e[f] for e in elements for f in fields)
    return array(2, dims or [len(elements), 1], body, name)


FIELDS = ['type', 'handle', 'properties', 'children', 'special']


def obj(type_, handle, props, children=(), special=()):
    """One graphics object as a figure file saves it."""
    return {
        'type': text(type_), 'handle': num([handle]),
        'properties': struct_(list(props), [props], [1, 1]),
        'children': struct_(FIELDS, list(children)) if children else num([]),
        'special': num(special) if special else num([]),
    }


def header(text_):
    return text_.encode('latin-1')[:116].ljust(116, b' ') + b'\0' * 8 + struct.pack('<H', 0x0100) + b'IM'


def figure_file(top, platform='PCWIN', variable='hgS_070000', compress=False):
    body = struct_(FIELDS, [top], [1, 1], variable)
    if compress:
        packed = zlib.compress(body)
        body = struct.pack('<II', 15, len(packed)) + packed
    return header(f'MATLAB 5.0 MAT-file, Platform: {platform}, Created on: Tue Jul 06 14:27:13 2010') + body


def old_release():
    """A figure as MATLAB 7 saved one: lineseries, labels its axes' special
    finds, a legend that is an axes of its own, a group holding a patch."""
    labels = [obj('text', 101, {'String': text('Dose [\\muSv]')}), obj('text', 102, {'String': text('Time [years]')}),
              obj('text', 103, {'String': text('Old release')})]
    lines = [obj('graph2d.lineseries', 104, {'XData': num([1, 10, 100, 1000]), 'YData': num([1, 3, 5, 9]),
                                             'Color': num([1, 0, 0]), 'DisplayName': text('red')}),
             obj('graph2d.lineseries', 105, {'XData': num([1, 10, 100, 1000]), 'YData': num([2, 2, 4, 4]),
                                             'Color': num([0, 0, 1]), 'LineStyle': text('--'), 'DisplayName': text('blue')}),
             obj('hggroup', 106, {'Tag': text('group')}, [
                 obj('patch', 107, {'Faces': num([1, 2, 3], [1, 3]), 'Vertices': num([10, 100, 100, 6, 6, 8], [3, 2]),
                                    'FaceColor': num([0, 0.6, 0])})])]
    axes = obj('axes', 100, {'XScale': text('log'), 'XLim': num([1, 1000]), 'YLim': num([0, 10]), 'XGrid': text('on'),
                             'Box': text('on'), 'Position': num([0.13, 0.11, 0.775, 0.815])},
               labels + lines, [3, 2, 1, 0])
    legend = obj('scribe.legend', 110, {'Position': num([0.6, 0.7, 0.25, 0.15]), 'Box': text('on'), 'Tag': text('legend'),
                                        'XLim': num([0, 1]), 'YLim': num([0, 1]), 'XTick': num([-1]), 'YTick': num([-1])}, [
        obj('text', 111, {'Units': text('normalized'), 'Position': num([0.45, 0.7, 0]), 'String': text('red')}),
        obj('line', 112, {'XData': num([0.1, 0.4]), 'YData': num([0.7, 0.7]), 'Color': num([1, 0, 0])}),
        obj('text', 113, {'Units': text('normalized'), 'Position': num([0.45, 0.3, 0]), 'String': text('blue')}),
        obj('line', 114, {'XData': num([0.1, 0.4]), 'YData': num([0.3, 0.3]), 'Color': num([0, 0, 1]), 'LineStyle': text('--')})])
    fig = obj('figure', 1, {'Position': num([100, 100, 560, 420]), 'Color': num([0.8, 0.8, 0.8]), 'Name': text('HG1')}, [axes, legend])
    return figure_file(fig)


XSS = '<img src=x onerror="window.__figXss=1">'


def hostile():
    """Markup in every text a figure shows, a font name that tries to leave
    its attribute, and values of the wrong kind or out of all proportion."""
    kids = [obj('graph2d.lineseries', 2, {'XData': text('abc'), 'YData': num([1, 2, 3]), 'DisplayName': text(XSS),
                                          'LineWidth': num([1e9]), 'MarkerSize': num([1e9]), 'Marker': text('o')}),
            obj('text', 3, {'String': text(XSS + '\\color{red}' + '<script>window.__figXss=2</script>'),
                            'FontName': text('x" onload="window.__figXss=3'), 'FontSize': num([1e9]), 'Position': num([0.5, 0.5])}),
            obj('patch', 4, {'Faces': num([1, 2, 99], [1, 3]), 'Vertices': num([0, 1, 1, 0, 0, 1], [3, 2]), 'FaceColor': text(XSS)}),
            obj('text', 5, {'String': cell([text(XSS), text('second')])}, special=[]),
            obj('image', 6, {'CData': text('not an image')})]
    axes = obj('axes', 7, {'Position': text(XSS), 'XTick': num(list(range(5000))), 'XLim': num([0, 5000]), 'Tag': text(XSS)}, kids, [5, 0, 0, 0])
    control = obj('uicontrol', 8, {'Style': text('listbox'), 'String': cell([text(XSS), text('b')]), 'Position': num([10, 10, 100, 60])})
    fig = obj('figure', 1, {'Name': text(XSS), 'Position': num([0, 0, 1e9, -5]), 'Colormap': text(XSS)}, [axes, control])
    return figure_file(fig, platform='MACI64')


def deep():
    """Groups within groups past where the page stops."""
    node = obj('line', 1000, {'YData': num([1, 2])})
    for k in range(50):
        node = obj('hggroup', 1000 + k + 1, {}, [node])
    fig = obj('figure', 1, {}, [obj('axes', 2, {}, [node])])
    return figure_file(fig, compress=True)


# --- in the page -------------------------------------------------------------------

SETTLE = """(async () => {
  for (let i = 0; i < 300; i++) {
    if (document.getElementById('fileLoadTicker').hidden) break;
    await new Promise(r => setTimeout(r, 100));
  }
  await new Promise(r => setTimeout(r, 300));
  return fileOrder.slice();
})()"""

HELPERS = r"""(() => {
  window.__wait = (ms) => new Promise(r => setTimeout(r, ms));
  window.__row = (path, file, group = true) => findTreeItem(path, { extra: group ? '.group' : '', fileKey: file, root: document.getElementById('tree'), allowMissingFile: true });
  // A row of the tree selected, the groups above it opened first, as the tree
  // is built a level at a time: a group as a click in the drawing selects it,
  // a dataset clicked.
  window.__select = async (path, file, group = true) => {
    await figRevealInTree(file, path);
    if (!group) {
      const r = __row(path, file, false);
      if (!r) return false;
      r.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    }
    await __wait(700);
    return true;
  };
  // What the information panel draws: each figure's caption and SVG, read back.
  window.__drawn = () => [...document.querySelectorAll('#info .fig-block')].map(b => {
    const svg = b.querySelector('svg');
    const paths = (sel) => svg ? [...svg.querySelectorAll(sel)] : [];
    const groups = svg ? [...svg.querySelectorAll('g[data-fig-path]')] : [];
    const kind = (p) => p.slice(p.lastIndexOf('/') + 1).replace(/^\(\d+\) /, '').split(' ')[0];
    const count = {};
    for (const g of groups) { const k = kind(g.getAttribute('data-fig-path')); count[k] = (count[k] || 0) + 1; }
    return {
      caption: (b.querySelector('.fig-title') || {}).textContent,
      size: (b.querySelector('.fig-size') || {}).textContent,
      viewBox: svg && svg.getAttribute('viewBox'),
      kinds: count,
      texts: svg ? [...svg.querySelectorAll('text')].map(t => t.textContent) : [],
      faded: groups.filter(g => g.getAttribute('opacity') === '0.2').length,
      marked: paths('.fig-mark').length,
      images: paths('image').length,
      notes: [...b.querySelectorAll('.fig-note')].map(n => n.textContent)
    };
  });
  window.__notes = () => [...document.querySelectorAll('#info .fig-view > .fig-note')].map(n => n.textContent);
  window.__children = (path, file) => {
    const f = loadedFiles[file];
    const g = path === '/' ? f : f.get(path);
    return Array.from(g.keys()).sort();
  };
  window.__attrs = (path, file) => {
    const n = loadedFiles[file].get(path);
    const out = {};
    for (const a of Object.keys(n.attrs || {})) out[a] = n.attrs[a].value;
    return out;
  };
  window.__value = (path, file) => {
    const v = loadedFiles[file].get(path).value;
    return ArrayBuffer.isView(v) ? Array.from(v) : v;
  };
  return true;
})()"""


async def pick_files(page, paths):
    doc = await page.send('DOM.getDocument', {})
    found = await page.send('DOM.querySelector', {'nodeId': doc['result']['root']['nodeId'], 'selector': '#fileInput'})
    await page.send('DOM.setFileInputFiles', {'nodeId': found['result']['nodeId'], 'files': paths})
    await page.ev('__wait(300)')
    return await page.ev(SETTLE, timeout=120)


async def remove(page, name):
    await page.ev("(async (n) => { await removeFile(n); await __wait(300); })(%s)" % json.dumps(name))


async def main():
    tmp = tempfile.mkdtemp(prefix='rb-fig-')
    written = {
        'old-release.fig': old_release(),
        'hostile.fig': hostile(),
        'deep.fig': deep(),
        'xfig.fig': b'#FIG 3.2  Produced by xfig version 3.2.8\nLandscape\nCenter\nMetric\n' * 4,
    }
    for name, data in written.items():
        with open(os.path.join(tmp, name), 'wb') as fh:
            fh.write(data)
    at = lambda name: os.path.join(tmp, name)
    fixture = lambda name: os.path.join(FIXTURES, name)

    # No fixture keeps the folder it was written in, or anyone's home.
    def unpacked(path):
        b = open(path, 'rb').read()
        out, k = b[:128], 128
        while k + 8 <= len(b):
            t, n = struct.unpack('<II', b[k:k + 8])
            out += zlib.decompress(b[k + 8:k + 8 + n]) if t == 15 else b[k + 8:k + 8 + n]
            k += 8 + n + (0 if t == 15 else -n % 8)
        return out
    names = ['figure-plot.fig', 'figure-kinds.fig', 'figure-controls.fig', 'figure-two.fig', 'figure-compact.fig', 'figure-tiled.fig']
    check('no fixture keeps a home folder or the folder it was written in',
          [n for n in names if any(p in unpacked(fixture(n)) for p in (b'/Users/', b'/home/', b'C:\\Users', '/Users/'.encode('utf-16-le')))], [])

    ver = json.load(urllib.request.urlopen('http://127.0.0.1:9222/json/version'))
    async with websockets.connect(ver['webSocketDebuggerUrl'], max_size=200 * 1024 * 1024) as bws:
        tid, page = await open_page(bws, settle=7)
        try:
            await page.ev(HELPERS)
            check('the file picker offers .fig', '.fig' in (await page.ev("document.getElementById('fileInput').accept")).split(','), True)

            # --- the tree -------------------------------------------------------------
            opened = await pick_files(page, [fixture('figure-plot.fig')])
            check('a figure file opens under its own name', opened, ['figure-plot.fig'])
            F = 'figure-plot.fig'
            top = await page.ev(f"__children('/', {json.dumps(F)})")
            check('its variables at the top, as MATLAB saved them', top, ['hgM_070000', 'hgS_070000', 'meta_data'])
            fig = '/hgS_070000'
            kids = await page.ev(f"__children({json.dumps(fig)}, {json.dumps(F)})")
            check('the figure is its objects, by place and type, then its properties',
                  (kids[:2], 'Color' in kids, 'Position' in kids), (['(1) axes', "(2) scribe.legend"], True, True))
            ax = fig + '/(1) axes'
            axkids = await page.ev(f"__children({json.dumps(ax)}, {json.dumps(F)})")
            check('an axes holds its lines, named by their DisplayName, and its title and labels, named so',
                  axkids[:7], ["(1) graph2d.lineseries 'sin'", "(2) graph2d.lineseries 'cos'", "(3) graph2d.lineseries 'half'",
                               "(4) text 'peak \\rightarrow'", "(5) text XLabel 'Time (s)'", "(6) text YLabel 'Amplitude \\muSv'",
                               "(7) text Title 'Waves \\alpha^2 and x_{i}'"])
            attrs = await page.ev(f"__attrs({json.dumps(ax)}, {json.dumps(F)})")
            check('  type, handle and special are the object\'s attributes',
                  (attrs.get('type'), attrs.get('special'), round(attrs.get('handle'), 4)), ('axes', '[7 5 6 0]', 1.0001))
            line = ax + "/(1) graph2d.lineseries 'sin'"
            check('  a property is a dataset as in any MAT-file: XData of 50 values, the colour MATLAB gave',
                  (len(await page.ev(f"__value({json.dumps(line + '/XData')}, {json.dumps(F)})")),
                   await page.ev(f"__value({json.dumps(line + '/Color')}, {json.dumps(F)})")), (50, [0, 0.447, 0.741]))
            info = await page.ev(f"__attrs('/', {json.dumps(F)}).Information")
            check('the file says it is a figure, and where to click', ('A MATLAB figure file: one figure' in info, 'Select the file' in info), (True, True))

            # --- drawn ----------------------------------------------------------------
            await page.ev(f"__select('/', {json.dumps(F)})")
            d = await page.ev('__drawn()')
            check('selecting the file draws its figure, at the size MATLAB gave it',
                  (len(d), d[0]['viewBox'], d[0]['size']), (1, '0 0 640 480', '640 × 480 px'))
            k = d[0]['kinds']
            check('  an axes, its three lines, a text, the legend', (k.get('axes'), k.get('graph2d.lineseries'), k.get('scribe.legend')), (1, 3, 1))
            t = d[0]['texts']
            check('  the title, read as TeX: α, a superscript 2 and a subscript i', [x for x in t if x.startswith('Waves')], ['Waves α2 and xi'])
            check('    the 2 raised and smaller, the i lowered', await page.ev("""(() => {
                const t = [...document.querySelectorAll('#info text')].find(e => e.textContent.startsWith('Waves'));
                const s = [...t.querySelectorAll('tspan')];
                const two = s.find(x => x.textContent === '2'); const i = s.find(x => x.textContent === 'i');
                return [Number(two.getAttribute('dy')) < 0, Number(two.getAttribute('font-size')) < Number(t.getAttribute('font-size')), Number(i.getAttribute('dy')) > 0]; })()"""), [True, True, True])
            check('  \\muSv is μ and Sv, as MATLAB reads it', 'Amplitude μSv' in ''.join(t), True)
            check('  the ticks MATLAB saved, its labels, the legend\'s entries',
                  all(s in t for s in ['0', '1', '6', '-0.8', 'Time (s)', 'sin', 'cos', 'half', 'peak →']), True)
            check('  nothing left out, nothing faded', (d[0]['notes'], d[0]['faded'], d[0]['marked']), ([], 0, 0))
            await page.ev(f"__select({json.dumps(fig)}, {json.dumps(F)})")
            check('selecting the figure\'s variable draws the same', (await page.ev('__drawn()'))[0]['kinds'], k)
            await page.ev(f"__select({json.dumps(line)}, {json.dumps(F)})")
            d = await page.ev('__drawn()')
            check('selecting a line draws the figure with the other lines and texts faded',
                  (d[0]['faded'] >= 5, d[0]['kinds'].get('graph2d.lineseries')), (True, 3))
            check('  and the line drawn with a halo', await page.ev("!!document.querySelector('#info g[data-fig-path$=\"\\'sin\\'\"] path[stroke-opacity=\"0.35\"]')"), True)
            await page.ev(f"__select({json.dumps(ax)}, {json.dumps(F)})")
            check('selecting the axes frames it', (await page.ev('__drawn()'))[0]['marked'], 1)
            await page.ev(f"__select({json.dumps(line + '/XData')}, {json.dumps(F)}, false)")
            check('a property is a dataset again: its values drawn, no figure',
                  (await page.ev("document.querySelectorAll('#info .fig-view').length"),
                   await page.ev("document.getElementById('plotlyChartContainer').classList.contains('visible')")), (0, True))

            # an object clicked in the drawing is selected in the tree
            await page.ev(f"__select('/', {json.dumps(F)})")
            await page.ev("""(async () => {
                const g = document.querySelector('#info g[data-fig-path$="\\'cos\\'"] path');
                g.dispatchEvent(new MouseEvent('click', { bubbles: true }));
                await __wait(1500); })()""", timeout=30)
            sel = await page.ev("[...document.querySelectorAll('#tree .tree-item.group.expanded')].map(r => r.getAttribute('data-path'))")
            check('an object clicked in the drawing is the one selected in the tree, its groups opened',
                  (sel, await page.ev(f"!!__row({json.dumps(ax + '/(2) graph2d.lineseries ' + chr(39) + 'cos' + chr(39))}, {json.dumps(F)}).offsetParent")),
                  ([ax + "/(2) graph2d.lineseries 'cos'"], True))
            check('  and the figure drawn with it set apart', (await page.ev('__drawn()'))[0]['faded'] >= 5, True)

            # saved as SVG and PNG
            saved = await page.ev("""(async () => {
                await __select('/', 'figure-plot.fig');
                const got = [];
                const was = URL.createObjectURL;
                URL.createObjectURL = (blob) => { got.push(blob); return was.call(URL, blob); };
                const names = [];
                const click = HTMLAnchorElement.prototype.click;
                HTMLAnchorElement.prototype.click = function () { names.push(this.download); };
                try {
                  for (const b of document.querySelectorAll('#info .fig-buttons button')) { b.click(); await __wait(1500); }
                } finally { URL.createObjectURL = was; HTMLAnchorElement.prototype.click = click; }
                const svgText = await got[0].text();
                const doc = new DOMParser().parseFromString(svgText, 'image/svg+xml');
                return { names, types: got.map(b => b.type), png: got[2] ? got[2].size : 0,
                         parsed: doc.documentElement.nodeName, mark: svgText.includes('fig-mark'), texts: doc.querySelectorAll('text').length };
            })()""", timeout=60)
            check('saved as an SVG drawing and a PNG picture, under the file\'s name',
                  (saved['names'], saved['types'], saved['parsed']), (['figure-plot.svg', 'figure-plot.png'], ['image/svg+xml', 'image/svg+xml', 'image/png'], 'svg'))
            check('  the picture has something in it, the drawing no frame', (saved['png'] > 10000, saved['mark'], saved['texts'] > 20), (True, False, True))
            await remove(page, F)

            # --- every kind ----------------------------------------------------------
            await pick_files(page, [fixture('figure-kinds.fig')])
            await page.ev("__select('/', 'figure-kinds.fig')")
            d = await page.ev('__drawn()')
            k = d[0]['kinds']
            check('six subplots: bars with their legend, log axes, a surface with a colour bar, an image, contours, a pie',
                  (k.get('axes'), k.get('specgraph.barseries'), k.get('scribe.legend'), k.get('scribe.colorbar'),
                   k.get('graph3d.surfaceplot'), k.get('image'), k.get('specgraph.contourgroup')), (6, 3, 1, 2, 1, 1, 1))
            check('  log ticks as powers of ten, the pie\'s labels, nothing left out',
                  ('105' in d[0]['texts'] and '1010' in d[0]['texts'], '17%' in d[0]['texts'] and '50%' in d[0]['texts'], d[0]['notes']), (True, True, []))
            check('  the surface, image and colour bars painted as pictures', d[0]['images'] >= 4, True)
            await remove(page, 'figure-kinds.fig')

            await pick_files(page, [fixture('figure-controls.fig')])
            await page.ev("__select('/', 'figure-controls.fig')")
            d = await page.ev('__drawn()')
            check('a window of controls: its size from characters, each control, the panel and what it holds, the menu',
                  (d[0]['caption'], d[0]['viewBox'], d[0]['kinds'].get('uicontrol'), d[0]['kinds'].get('uipanel'), d[0]['kinds'].get('uimenu')),
                  ('Figure 1: Controls', '0 0 480 322', 7, 1, 1))
            check('  their texts as MATLAB shows them', all(s in d[0]['texts'] for s in ['Run', '0.5', 'one', 'Check', 'a', 'b', 'c', 'Panel', 'Radio', 'File']), True)
            await remove(page, 'figure-controls.fig')

            await pick_files(page, [fixture('figure-two.fig')])
            await page.ev("__select('/', 'figure-two.fig')")
            d = await page.ev('__drawn()')
            check('two figures in one file: both drawn, each captioned',
                  [x['caption'] for x in d], ['Figure 1', 'Figure 2'])
            kids = await page.ev("__children('/hgS_070000', 'figure-two.fig')")
            check('  and in the tree, (1) figure and (2) figure', kids, ['(1) figure', '(2) figure'])
            await page.ev("__select('/hgS_070000/(2) figure', 'figure-two.fig')")
            check('  selecting one draws that one', [x['kinds'].get('specgraph.barseries') for x in await page.ev('__drawn()')], [1])
            await remove(page, 'figure-two.fig')

            await pick_files(page, [fixture('figure-compact.fig'), fixture('figure-tiled.fig')])
            await page.ev("__select('/', 'figure-compact.fig')")
            check('a figure saved compact is said to be kept in a form not drawn',
                  ('only in the form MATLAB uses from R2014b' in ' '.join(await page.ev('__notes()')), await page.ev('__drawn()')), (True, []))
            await page.ev("__select('/', 'figure-tiled.fig')")
            d = await page.ev('__drawn()')
            check('a tiled layout, whose objects only that form keeps, is said to be so',
                  any('tiled layout' in n for n in d[0]['notes']), True)
            await remove(page, 'figure-compact.fig')
            await remove(page, 'figure-tiled.fig')

            # --- releases before R2014b ----------------------------------------------
            await pick_files(page, [at('old-release.fig')])
            await page.ev("__select('/', 'old-release.fig')")
            d = await page.ev('__drawn()')
            k = d[0]['kinds']
            check('a figure of an older release: its lines, the patch in its group, its legend an axes of its own',
                  (k.get('graph2d.lineseries'), k.get('patch'), k.get('hggroup'), k.get('scribe.legend'), d[0]['notes']), (2, 1, 1, 1, []))
            check('  its labels found by its axes\' special, \\muSv read, log ticks as powers of ten',
                  all(s in ''.join(d[0]['texts']) for s in ['Old release', 'Time [years]', 'Dose [μSv]']) and '3' in d[0]['texts'], True)
            await remove(page, 'old-release.fig')

            # --- hostile, deep, not a figure -----------------------------------------
            await pick_files(page, [at('hostile.fig')])
            await page.ev("__select('/', 'hostile.fig')")
            await page.ev('__wait(500)')
            d = await page.ev('__drawn()')
            check('a hostile figure is drawn, its markup as text, nothing of it run',
                  (len(d), any(XSS in x for x in d[0]['texts']), await page.ev("document.querySelectorAll('#info img, #tree img, #info script, #info foreignObject').length"),
                   await page.ev('typeof window.__figXss')), (1, True, 0, 'undefined'))
            axes = [k for k in await page.ev("__children('/hgS_070000', 'hostile.fig')") if k.startswith('(1) axes')][0]
            await page.ev(f"figRevealInTree('hostile.fig', {json.dumps('/hgS_070000/' + axes)})")
            await page.ev('__wait(500)')
            check('  its caption and names as text', (XSS in d[0]['caption'], await page.ev("[...document.querySelectorAll('#tree .tree-label')].some(l => l.textContent.includes('<img'))"),
                  await page.ev("document.querySelectorAll('#tree img, #info img').length"), await page.ev('typeof window.__figXss')), (True, True, 0, 'undefined'))
            check('  the font name that tries to leave its attribute stays in it', await page.ev("[...document.querySelectorAll('#info [onload]')].length"), 0)
            check('  sizes out of all proportion are held in', (d[0]['viewBox'], len([x for x in d[0]['texts'] if x.isdigit()]) <= 220), ('0 0 560 420', True))
            await page.ev("__select('/', 'hostile.fig')")
            await remove(page, 'hostile.fig')

            await pick_files(page, [at('deep.fig')])
            note = await page.ev("""(() => { const f = loadedFiles['deep.fig'];
                let g = f.get('/hgS_070000/(1) axes'); let depth = 0;
                while (g) { const k = Array.from(g.keys()).find(n => n.startsWith('(')); if (!k) break; g = g.get(k); depth++; }
                return [depth, g && g.attrs.MATLAB_note ? g.attrs.MATLAB_note.value : null]; })()""")
            check('objects nested too deep stop, and say so', note, [39, 'Objects nested more than 40 deep are not shown.'])
            await page.ev("__select('/', 'deep.fig')")
            check('  the figure still draws', len(await page.ev('__drawn()')), 1)
            await remove(page, 'deep.fig')

            before = await page.ev('fileOrder.length')
            await pick_files(page, [at('xfig.fig')])
            banner = await page.ev("document.querySelector('#failureBanner .failure-banner-text')?.textContent || ''")
            check('a .fig that is no MAT-file -- an Xfig drawing -- is refused, saying why',
                  ('is not a MATLAB figure' in banner, await page.ev('fileOrder.length')), (True, before))
            check('an address ending in .fig keeps its name',
                  await page.ev("hdf5FileNameFromUrl(new URL('https://example.com/figures/result.fig'))"), 'result.fig')

            expected = ('is not a MATLAB figure',)
            check('no console errors but the refusal', [m for kind, m in page.logs
                  if not any(e in m for e in expected) and 'favicon' not in m][:3], [])
        finally:
            await bws.send(json.dumps({'id': 98, 'method': 'Target.closeTarget', 'params': {'targetId': tid}}))

    print(f'\n{checks - len(failures)} of {checks} checks passed')
    if failures:
        print('failed: ' + ', '.join(failures))
    return 1 if failures else 0


sys.exit(asyncio.run(main()))
