#!/usr/bin/env python3
"""flashcards.html reads this week's words off a picture, in a real browser.

The pictures are made here: word lists laid out the ways teachers lay them
out (a table, two columns, "dog - hund", numbered, two lists side by side, a
textbook page), then photographed by Chrome as a phone would - tilted, in
perspective, with a shadow, a little blur and JPEG - or saved as a plain
screenshot. They go to the page through its own file field, a paste and a
drop, and the lines the editor gets are compared with the words on the sheet.

The reader itself (Tesseract) is fetched by the page from jsDelivr, so the
test needs the network. It also checks that nothing else is fetched, nothing
is sent, a file that does not match its hash is not run, and what the page
says without the network or without WebAssembly.

Start a server on the repository root and headless Chrome, by default on
ports 8848 and 9348 (FC_HTTP_PORT and FC_CDP_PORT for others; check them first
with lsof -nP -iTCP:<port> -sTCP:LISTEN, other sessions use ports too):

    python3 -m http.server 8848 --bind 127.0.0.1
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \\
      --headless=new --remote-debugging-port=9348 --no-first-run \\
      --user-data-dir=/tmp/fctest --disable-gpu about:blank

    python3 resources/tests/flashcards/test-photo-ui.py

With FC_SHOTS=<folder> it saves screenshots, and the pictures it made.
Exit status is 0 when every check passes.
"""
import asyncio
import base64
import json
import os
import shutil
import sys
import tempfile
import unicodedata
import urllib.request

import websockets

HTTP = int(os.environ.get('FC_HTTP_PORT', '8848'))
CDP = int(os.environ.get('FC_CDP_PORT', '9348'))
ORIGIN = f'http://127.0.0.1:{HTTP}'
URL = f'{ORIGIN}/flashcards.html'
SHOTS = os.environ.get('FC_SHOTS')

failures = []
checks = 0


def check(label, got, want=True):
    global checks
    checks += 1
    ok = got == want
    print(f'{"ok  " if ok else "FAIL"}  {label}' + ('' if ok else f': {got!r} (expected {want!r})'))
    if not ok:
        failures.append(label)


# --- the sheets ----------------------------------------------------------------------------
# Ordinary school words, written for this test.

EN_TABLE = [('en hund', 'a dog'), ('att springa', 'to run'), ('ett äpple', 'an apple'), ('fönster', 'window'),
            ('sjukhus', 'hospital'), ('grönsaker', 'vegetables'), ('att försöka', 'to try'), ('tröja', 'sweater / jumper'),
            ('väder', 'weather'), ('jordgubbe', 'strawberry'), ('skolgård', 'schoolyard'), ('nyckel', 'key'),
            ('fåglar', 'birds'), ('ögonblick', 'moment'), ('kylskåp', 'fridge')]
EN_COLUMNS = [('igår', 'yesterday'), ('alltid', 'always'), ('genom', 'through'), ('frukost', 'breakfast'),
              ('granne', 'neighbour'), ('att svara', 'to answer'), ('billig', 'cheap'), ('farlig', 'dangerous'),
              ('bibliotek', 'library'), ('att låna', 'to borrow'), ('konstig', 'weird'), ('tusen', 'thousand')]
EN_DASH = [('köket', 'the kitchen'), ('en kniv', 'a knife'), ('att laga mat', 'to cook'), ('en sked', 'a spoon'),
           ('hungrig', 'hungry'), ('törstig', 'thirsty'), ('en tallrik', 'a plate'), ('att smaka', 'to taste')]
EN_BODY = [('huvud', 'head'), ('axlar', 'shoulders'), ('knä', 'knee'), ('tår', 'toes'), ('ögon', 'eyes'), ('öron', 'ears'),
           ('mun', 'mouth'), ('näsa', 'nose'), ('mage', 'stomach'), ('rygg', 'back')]
ES_COLUMNS = [('huset', 'la casa'), ('hunden', 'el perro'), ('att äta', 'comer'), ('tack så mycket', 'muchas gracias'),
              ('vintern', 'el invierno'), ('året', 'el año'), ('kaffet', 'el café'), ('boken', 'el libro'),
              ('äpplet', 'la manzana'), ('varför?', '¿por qué?'), ('att sova', 'dormir'), ('staden', 'la ciudad')]
ES_TABLE = [('pojken', 'el niño'), ('flickan', 'la niña'), ('morgonen', 'la mañana'), ('trädet', 'el árbol'),
            ('sången', 'la canción'), ('svår', 'difícil'), ('lätt', 'fácil'), ('också', 'también'), ('hjärtat', 'el corazón'),
            ('pennan', 'el lápiz')]
EN_CLOTHES = [('en jacka', 'a jacket'), ('byxor', 'trousers'), ('skor', 'shoes'), ('en mössa', 'a hat'), ('vantar', 'gloves'),
              ('en halsduk', 'a scarf'), ('strumpor', 'socks'), ('en klänning', 'a dress'), ('en kjol', 'a skirt')]
COLOURS_L = [('blå', 'blue'), ('röd', 'red'), ('gul', 'yellow'), ('grön', 'green'), ('svart', 'black')]
COLOURS_R = [('lila', 'purple'), ('rosa', 'pink'), ('brun', 'brown'), ('grå', 'grey'), ('vit', 'white')]
EN_FOOD = [('mjölk', 'milk'), ('smör', 'butter'), ('ost', 'cheese'), ('bröd', 'bread'), ('socker', 'sugar'), ('mjöl', 'flour')]
ES_TOWN = [('en gata', 'una calle'), ('ett torg', 'una plaza'), ('kyrkan', 'la iglesia'), ('banken', 'el banco'),
           ('tåget', 'el tren'), ('bussen', 'el autobús'), ('höger', 'derecha'), ('vänster', 'izquierda')]
EN_WEATHER = [('ett moln', 'a cloud'), ('regn', 'rain'), ('snö', 'snow'), ('åska', 'thunder'), ('dimma', 'fog'),
              ('vind', 'wind'), ('solsken', 'sunshine'), ('torr', 'dry')]

APP_LIST = [('att viska', 'to whisper'), ('en fyr', 'a lighthouse'), ('modig', 'brave'), ('fastän', 'although'),
            ('att låna', 'to borrow'), ('ganska', 'quite'), ('att slå upp', 'to look up'), ('plötsligt', 'suddenly'),
            ('sömnig', 'sleepy')]
SCREEN_LIST = [('viskade', 'whispered'), ('förvånad', 'surprised'), ('ryckte på axlarna', 'shrugged'), ('långsamt', 'slowly'),
               ('en fyr', 'a lighthouse'), ('lova', 'promise'), ('plötsligt', 'suddenly'), ('väderkvarn', 'windmill'),
               ('Det öste ner', 'It was pouring')]

PROSE = ('In the morning the sky was grey and heavy. By lunch the first drops of rain had started to fall, '
         'and the children ran inside. Tom looked out of the window and saw a rainbow over the hills.')


def esc(s):
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def rows(pairs, first_x, cls='', headers=None):
    order = (lambda p: (p[1], p[0])) if first_x else (lambda p: p)
    head = f'<tr><th>{esc(headers[0])}</th><th>{esc(headers[1])}</th></tr>' if headers else ''
    return f'<table class="{cls}">{head}' + ''.join(f'<tr><td>{esc(order(p)[0])}</td><td>{esc(order(p)[1])}</td></tr>' for p in pairs) + '</table>'


SHEETS = {
    'tabell': dict(lang='en', first_x=False, font='Arial', size=20, name='Vecka 42', fx=(-1.5, 6, 0, 0.5, 0.35, 75, 1.12),
                   body=lambda: '<h1>Glosor vecka 42</h1>' + rows(EN_TABLE, False, 'b', ('Svenska', 'Engelska')), pairs=EN_TABLE),
    'kolumner': dict(lang='en', first_x=True, font='Times New Roman', size=21, fx=(2.2, 9, -4, 0.6, 0.25, 70, 1.1),
                     body=lambda: '<h1>Engelska – läxa till fredag</h1>' + rows(EN_COLUMNS, True, 'c'), pairs=EN_COLUMNS),
    'streck': dict(lang='en', first_x=True, font='Verdana', size=18, fx=(-0.8, 12, 0, 0.4, 0.45, 72, 1.12),
                   body=lambda: '<p>Lär dig orden till på fredag. Vi har förhör i början av lektionen, så öva lite varje dag.</p>'
                   + ''.join(f'<div>{esc(b)} – {esc(a)}</div>' for a, b in EN_DASH), pairs=EN_DASH),
    'numrerad': dict(lang='en', first_x=False, font='Comic Sans MS', size=20, name='Vecka 7', fx=(3, 4, 0, 0.7, 0.2, 80, 1.1),
                     body=lambda: '<h1>Kroppen – vecka 7</h1>' + ''.join(f'<div>{i + 1}. {esc(a)} = {esc(b)}</div>' for i, (a, b) in enumerate(EN_BODY)),
                     pairs=EN_BODY),
    'spanska': dict(lang='es', first_x=False, font='Georgia', size=20, name='Vecka 11', fx=(-2.5, 8, 0, 0.5, 0.3, 74, 1.12),
                    body=lambda: '<h1>Spanska v. 11</h1>' + rows(ES_COLUMNS, False, 'c'), pairs=ES_COLUMNS),
    'spanska-tabell': dict(lang='es', first_x=True, font='Helvetica', size=19, fx=(1.2, 10, 5, 0.55, 0.4, 70, 1.1),
                           body=lambda: rows(ES_TABLE, True, 'b', ('Español', 'Svenska')), pairs=ES_TABLE),
    'sned': dict(lang='en', first_x=True, font='Verdana', size=18, fx=(6.5, 6, 3, 0.5, 0.25, 72, 1.0),
                 body=lambda: rows(EN_CLOTHES, True, 'b', ('Engelska', 'Svenska')), pairs=EN_CLOTHES),
    'två-listor': dict(lang='en', first_x=False, font='Avenir Next', size=19, fx=(0.8, 5, 0, 0.45, 0.2, 76, 1.12),
                       body=lambda: '<h1>Färger</h1><table class="c">' + ''.join(
                           f'<tr><td>{esc(a)}</td><td>{esc(b)}</td><td class="gap"></td><td>{esc(c)}</td><td>{esc(d)}</td></tr>'
                           for (a, b), (c, d) in zip(COLOURS_L, COLOURS_R)) + '</table>', pairs=COLOURS_L + COLOURS_R),
    'liggande': dict(lang='en', first_x=False, font='Arial', size=20, fx=(90.8, 4, 0, 0.45, 0.2, 74, 0.82),
                     body=lambda: rows(EN_FOOD, False, 'c'), pairs=EN_FOOD),
    'mörk': dict(lang='es', first_x=True, font='Helvetica', size=16, screenshot=True, dark=True,
                 body=lambda: rows(ES_TOWN, True, 'c', ('Español', 'Svenska')), pairs=ES_TOWN),
    # A phone's screenshot of a school app in dark mode: clock and battery, a
    # heading, a numbered list in a light typeface, the app's word count.
    'app': dict(lang='en', first_x=True, name='Vecka 41', app=True, pairs=APP_LIST),
    # A photo of a computer screen in dark mode: light writing, a light wall
    # around it, glare and a dark patch.
    'skärm': dict(lang='en', first_x=False, name='Vecka 43', screen=True, pairs=SCREEN_LIST),
    'lärobok': dict(lang='en', first_x=True, font='Georgia', size=17, fx=(-0.7, 6, 0, 0.45, 0.2, 74, 1.12),
                    body=lambda: f'<h1>Chapter 4: The Weather</h1><p class="tb">{PROSE} {PROSE}</p>'
                    f'<div class="gloss"><b>Words</b>{rows(EN_WEATHER, True, "c")}</div><p class="tb">{PROSE}</p><p>Page 42</p>',
                    pairs=EN_WEATHER),
}

NOISE = ("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='300' height='300'><filter id='n'>"
         "<feTurbulence type='fractalNoise' baseFrequency='1.4' numOctaves='2' stitchTiles='stitch'/>"
         "<feColorMatrix type='saturate' values='0'/></filter><rect width='100%' height='100%' filter='url(%23n)'/></svg>")


def app_html(sh):
    rows = ''.join(f'<div class="r">{i + 1} {esc(en)} - {esc(sv)}</div>' for i, (sv, en) in enumerate(sh['pairs']))
    return f'''<!doctype html><html><head><meta charset="utf-8"><style>
html,body{{margin:0;height:100%;background:#141414;color:#f2f2f2;font:300 17px/1.3 -apple-system,"Helvetica Neue",Helvetica,sans-serif}}
.bar{{display:flex;justify-content:space-between;padding:14px 28px 0;font:600 17px -apple-system,Helvetica}}
.pill{{border:1.5px solid #f2f2f2;border-radius:6px;padding:0 4px;font-size:13px}}
.back{{padding:24px 12px 4px;color:#b8b8b8}} .title{{padding:4px 12px 14px;font-weight:600;font-size:21px;border-bottom:1px solid #333}}
.info{{margin:6px 2px 10px;border:1.5px solid #7b7fd0;border-radius:10px;padding:13px;text-align:center;color:#8f93e6;font-weight:600}}
.r{{padding:0 14px;height:54px;line-height:54px}}
.foot{{position:fixed;left:0;right:0;bottom:0;border-top:1px solid #333;padding:8px 12px;text-align:right;color:#999;font-size:14px}}
</style></head><body><div class="bar"><span>12:05</span><span>▂▄▆ ◠ <span class="pill">95</span></span></div>
<div class="back">← Uppgifter</div><div class="title">Läxa i engelska v 41</div><div class="info">Visa information</div>
{rows}<div class="foot">114 ord · 1587 tecken</div></body></html>'''


def screen_html(sh):
    rows = ''.join(f'<div class="r">{i + 1} {esc(sv)} – {esc(en)}</div>' for i, (sv, en) in enumerate(sh['pairs']))
    return f'''<!doctype html><html><head><meta charset="utf-8"><style>
html,body{{margin:0;width:100%;height:100%;overflow:hidden;background:linear-gradient(170deg,#d8d4cc,#b9b6ae)}}
.scene{{position:fixed;inset:0;display:flex;align-items:center;justify-content:center;perspective:1400px;filter:blur(0.7px)}}
.screen{{width:820px;height:1180px;box-sizing:border-box;padding:150px 70px;background:#2c2f35;color:#ececec;
  font:500 27px/1.2 Helvetica,Arial,sans-serif;transform:scale(1.1) rotateX(7deg) rotateY(-3deg) rotateZ(1.2deg);border-top:6px solid #555}}
.r{{margin:0 0 30px}} .h{{margin:0 0 26px}} .b{{font-weight:700;margin:0 0 36px}}
.patch{{position:fixed;inset:0;background:radial-gradient(ellipse at 38% 42%,rgba(0,0,0,.5),rgba(0,0,0,0) 34%)}}
.glare{{position:fixed;inset:0;background:radial-gradient(circle at 72% 64%,rgba(255,255,255,.22),rgba(255,255,255,0) 22%)}}
.noise{{position:fixed;inset:0;opacity:.12;mix-blend-mode:multiply;background-image:url("{NOISE}")}}
</style></head><body><div class="scene"><div class="screen"><div class="h">Läxa i engelska åk 6 v 43: ord från texten ”Windmills”</div>
<div class="b">Lär dig att säga och skriva orden på engelska:</div>{rows}</div></div>
<div class="patch"></div><div class="glare"></div><div class="noise"></div></body></html>'''


def sheet_html(sh):
    if sh.get('app'):
        return app_html(sh)
    if sh.get('screen'):
        return screen_html(sh)
    css = f'''table{{border-collapse:collapse}} th,td{{text-align:left;padding:.32em 1.1em}} th{{font-weight:bold}}
table.b th,table.b td{{border:1.6px solid #2a2a2a}} table.c td,table.c th{{padding:.22em 2.6em .22em 0}} td.gap{{width:3em}}
h1{{font-size:1.45em;margin:0 0 .7em}} div{{margin:.18em 0}} p.tb{{text-align:justify;margin:0 0 1em}}
.gloss{{float:right;width:44%;margin:0 0 1em 1.4em;padding:.6em 1em;background:#e9eef6;border:1px solid #9aa9c0}}'''
    if sh.get('screenshot'):
        bg, fg = ('#1e1f22', '#e8e8ea') if sh.get('dark') else ('#fff', '#222')
        return (f'<!doctype html><html><head><meta charset="utf-8"><style>html,body{{margin:0;background:{bg}}}'
                f'body{{padding:28px 36px;font:{sh["size"]}px/1.45 "{sh["font"]}";color:{fg}}}{css}</style></head><body>{sh["body"]()}</body></html>')
    rz, rx, ry, blur, shadow, _q, zoom = sh['fx']
    return f'''<!doctype html><html><head><meta charset="utf-8"><style>
html,body{{margin:0;width:100%;height:100%;overflow:hidden;background:#6f6559}}
.scene{{position:fixed;inset:0;display:flex;align-items:center;justify-content:center;perspective:1500px;filter:blur({blur}px)}}
.paper{{width:794px;min-height:1123px;box-sizing:border-box;padding:72px 84px;background:#fbfaf4;color:#1c1c1c;
  font:{sh["size"]}px/1.55 "{sh["font"]}";transform:scale({zoom}) rotateX({rx}deg) rotateY({ry}deg) rotateZ({rz}deg);box-shadow:0 18px 50px rgba(0,0,0,.45)}}
{css}
.light{{position:fixed;inset:0;background:linear-gradient(118deg,rgba(25,18,10,{shadow}) 0%,rgba(25,18,10,0) 58%),
  radial-gradient(ellipse at 55% 45%,rgba(0,0,0,0) 45%,rgba(0,0,0,.25) 100%)}}
.noise{{position:fixed;inset:0;opacity:.12;mix-blend-mode:multiply;background-image:url("{NOISE}")}}
</style></head><body><div class="scene"><div class="paper">{sh["body"]()}</div></div><div class="light"></div><div class="noise"></div></body></html>'''


def norm(s):
    return ' '.join(unicodedata.normalize('NFC', s).split()).lower()


def expected_lines(sh):
    return [f'{a} = {b}' for a, b in sh['pairs']]


# --- the browser -----------------------------------------------------------------------------

class Page:
    def __init__(self, bws):
        self.bws = bws
        self.n = 0
        self.pending = {}
        self.sid = None
        self.errors = []
        self.console = []
        self.requests = []
        self.paused = asyncio.Queue()

    async def call(self, method, params=None, timeout=120):
        self.n += 1
        i = self.n
        msg = {'id': i, 'method': method, 'params': params or {}}
        if self.sid and not method.startswith('Target.'):
            msg['sessionId'] = self.sid
        fut = asyncio.get_event_loop().create_future()
        self.pending[i] = fut
        await self.bws.send(json.dumps(msg))
        return await asyncio.wait_for(fut, timeout)

    async def pump(self):
        async for raw in self.bws:
            r = json.loads(raw)
            m = r.get('method')
            if m == 'Runtime.exceptionThrown':
                d = r['params']['exceptionDetails']
                self.errors.append(str(d.get('exception', {}).get('description') or d.get('text', ''))[:300])
            elif m == 'Runtime.consoleAPICalled' and r['params']['type'] == 'error':
                self.console.append(' '.join(str(a.get('value', a.get('description', ''))) for a in r['params']['args'])[:300])
            elif m == 'Network.requestWillBeSent':
                q = r['params']['request']
                self.requests.append({'url': q['url'], 'method': q['method'], 'body': bool(q.get('hasPostData') or q.get('postData'))})
            elif m == 'Fetch.requestPaused':
                self.paused.put_nowait(r['params'])
            if 'id' in r and r['id'] in self.pending and not self.pending[r['id']].done():
                self.pending[r['id']].set_result(r)

    async def ev(self, expr):
        r = await self.call('Runtime.evaluate', {'expression': expr, 'returnByValue': True, 'awaitPromise': True})
        res = r.get('result', {})
        if 'exceptionDetails' in res:
            return 'EXCEPTION: ' + str(res['exceptionDetails'].get('exception', {}).get('description', ''))[:300]
        return res.get('result', {}).get('value')

    async def click(self, selector):
        """A real click, with the mouse."""
        x, y = await self.ev(f"(e => {{ e.scrollIntoView({{ block: 'center' }}); const r = e.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; }})(document.querySelector({json.dumps(selector)}))")
        for kind in ('mousePressed', 'mouseReleased'):
            await self.call('Input.dispatchMouseEvent', {'type': kind, 'x': x, 'y': y, 'button': 'left', 'clickCount': 1})

    async def size(self, width, height, mobile=False):
        await self.call('Emulation.setDeviceMetricsOverride', {'width': width, 'height': height, 'deviceScaleFactor': 1, 'mobile': mobile})
        await self.call('Emulation.setTouchEmulationEnabled', {'enabled': mobile})

    async def load(self, init=None):
        """The page afresh, with nothing stored; init runs before the page's own scripts."""
        if getattr(self, 'script', None):
            await self.call('Page.removeScriptToEvaluateOnNewDocument', {'identifier': self.script})
            self.script = None
        if init:
            self.script = (await self.call('Page.addScriptToEvaluateOnNewDocument', {'source': init}))['result']['identifier']
        await self.call('Page.navigate', {'url': f'{ORIGIN}/robots.txt'})
        await settle(self, 'document.readyState', 'complete')
        await self.ev("localStorage.clear(); localStorage.setItem('kvot-theme', 'light')")
        await self.call('Page.navigate', {'url': URL})
        await settle(self, "typeof FC !== 'undefined' && document.querySelectorAll('.wk-tile').length > 0", True)

    async def shot(self, name):
        if not SHOTS:
            return
        os.makedirs(SHOTS, exist_ok=True)
        await asyncio.sleep(0.4)
        r = await self.call('Page.captureScreenshot', {'format': 'png'})
        with open(os.path.join(SHOTS, name), 'wb') as f:
            f.write(base64.b64decode(r['result']['data']))


async def settle(page, expr, want, tries=80, pause=0.1):
    got = None
    for _ in range(tries):
        got = await page.ev(expr)
        if got == want:
            return got
        await asyncio.sleep(pause)
    return got


async def make_pictures(page, folder):
    """Each sheet photographed (JPEG, 3000 × 4000) or saved as a screenshot (PNG)."""
    files = {}
    for name, sh in SHEETS.items():
        await page.call('Page.navigate', {'url': 'about:blank'})
        await settle(page, 'document.readyState', 'complete')
        shot = sh.get('screenshot') or sh.get('app')
        size = (402, 874, 3) if sh.get('app') else (900, 640, 1) if shot else (1000, 1333, 3)
        await page.call('Emulation.setDeviceMetricsOverride', {'width': size[0], 'height': size[1], 'deviceScaleFactor': size[2], 'mobile': False})
        frame = (await page.call('Page.getFrameTree'))['result']['frameTree']['frame']['id']
        await page.call('Page.setDocumentContent', {'frameId': frame, 'html': sheet_html(sh)})
        await page.ev('document.fonts.ready.then(() => true)')
        await asyncio.sleep(0.2)
        params = {'format': 'png'} if shot else {'format': 'jpeg', 'quality': sh['fx'][5] if 'fx' in sh else 70}
        r = await page.call('Page.captureScreenshot', params)
        path = os.path.join(folder, f'{name}.{"png" if shot else "jpg"}')
        with open(path, 'wb') as f:
            f.write(base64.b64decode(r['result']['data']))
        files[name] = path
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        for path in files.values():
            shutil.copy(path, SHOTS)
    return files


BOX = "document.getElementById('fc-list-text').value"
STATUS = "document.getElementById('fc-photo-status').textContent"
DONE = "(() => { const c = document.getElementById('fc-photo-cancel'); return !document.getElementById('fc-photo-result').hidden && c.hidden; })()"


async def wait_reading(page, limit=90):
    """Until the reading is over; every status the page showed on the way."""
    seen = []
    for _ in range(int(limit / 0.05)):
        st = await page.ev(STATUS)
        if st and (not seen or seen[-1] != st):
            seen.append(st)
        if await page.ev(DONE):
            break
        await asyncio.sleep(0.05)
    return seen


async def choose_file(page, path):
    doc = await page.call('DOM.getDocument', {'depth': 1})
    node = await page.call('DOM.querySelector', {'nodeId': doc['result']['root']['nodeId'], 'selector': '#fc-photo-file'})
    await page.call('DOM.setFileInputFiles', {'nodeId': node['result']['nodeId'], 'files': [path]})


async def read_file(page, path):
    await choose_file(page, path)
    return await wait_reading(page)


async def open_editor(page, lang=None):
    await page.ev("document.querySelector('.fc-newlist').click()")
    await settle(page, "!document.getElementById('fc-editor').hidden", True)
    if lang:
        await page.ev(f"document.querySelector('input[name=listlang][value={lang}]').click()")


def score(box, sh):
    """Exact lines of the sheet found in the box, and lines in the box the sheet does not have."""
    got = [norm(l) for l in box.split('\n') if l.strip()]
    want = [norm(l) for l in expected_lines(sh)]
    exact = sum(1 for w in want if w in got)
    extra = [g for g in got if g not in want]
    return exact, extra


async def main():
    ver = json.load(urllib.request.urlopen(f'http://127.0.0.1:{CDP}/json/version'))
    folder = tempfile.mkdtemp(prefix='fc-photo-')
    async with websockets.connect(ver['webSocketDebuggerUrl'], max_size=200 * 1024 * 1024) as bws:
        page = Page(bws)
        asyncio.create_task(page.pump())
        tid = (await page.call('Target.createTarget', {'url': 'about:blank'}))['result']['targetId']
        page.sid = (await page.call('Target.attachToTarget', {'targetId': tid, 'flatten': True}))['result']['sessionId']
        for m in ('Runtime.enable', 'Page.enable', 'Network.enable', 'DOM.enable'):
            await page.call(m)
        await page.call('Page.setInterceptFileChooserDialog', {'enabled': True})

        files = await make_pictures(page, folder)
        check('the pictures are made: photos of 3000 × 4000, and screenshots', all(os.path.getsize(p) > 15000 for p in files.values()), True)

        # --- a table photographed, the first time: the reader is fetched ---------------------------------
        await page.size(1300, 900)
        await page.load()
        await page.ev("document.querySelectorAll('.fc-newlist').length")
        check('no photo button until a list is being written', await page.ev("document.getElementById('fc-photo').hidden"), True)
        await open_editor(page)
        check('the editor has the photo button', await page.ev("document.getElementById('fc-photo').checkVisibility()"), True)
        page.requests.clear()
        seen = await read_file(page, files['tabell'])
        box = await page.ev(BOX)
        exact, extra = score(box, SHEETS['tabell'])
        check('a table photographed: every pair, Swedish first', [exact, extra], [len(EN_TABLE), []])
        check('on the way it says what it does: preparing, fetching the reader the first time, starting it, reading',
              [any(s.startswith(p) for s in seen) for p in ('Gör bilden klar', 'Hämtar läsprogrammet', 'Startar läsprogrammet', 'Läser orden på svenska och engelska')],
              [True, True, True, True])
        check('and then how many words it put in the box', (seen[-1] if seen else '').startswith(f'{len(EN_TABLE)} ord från bilden'), True)
        check('the heading names the list', await page.ev("document.getElementById('fc-list-name').value"), 'Vecka 42')
        check('the editor counts the words', await page.ev("document.getElementById('fc-list-status').textContent"), f'{len(EN_TABLE)} ord')
        check('the heading and the column headings are not offered as words that were missed',
              await page.ev("[...document.querySelectorAll('.fc-photo-line')].map(b => b.textContent).filter(t => /vecka|Svenska/.test(t))"), [])
        await page.shot('photo-table.png')

        # Nothing goes anywhere but jsDelivr, for the pinned files, and nothing is sent.
        pinned = await page.ev("Object.values(FC_PHOTO.FILES).map(f => FC_PHOTO.CDN + f.path)")
        away = [r for r in page.requests if not r['url'].startswith((ORIGIN, 'blob:', 'data:'))]
        check('the reader comes from jsDelivr, the pinned files only', sorted({r['url'] for r in away} - set(pinned)), [])
        check('the program, the core and two languages: Swedish and English', sorted(u.rsplit('/', 1)[-1] for u in {r['url'] for r in away}),
              ['eng.traineddata.gz', 'swe.traineddata.gz', 'tesseract-core-simd-lstm.wasm.js', 'tesseract.min.js', 'worker.min.js'])
        check('nothing is sent: every request a GET without a body', [r for r in page.requests if r['method'] != 'GET' or r['body']], [])

        # --- swapping, a second page, and keeping the name --------------------------------------------
        await page.click('#fc-list-swap')
        swapped = (await page.ev(BOX)).split('\n')
        check('"Byt plats på orden" turns every pair round', swapped[:2], ['a dog = en hund', 'to run = att springa'])
        await page.click('#fc-list-swap')
        check('and back', (await page.ev(BOX)).split('\n')[:2], ['en hund = a dog', 'att springa = to run'])
        await page.click('#fc-list-swap')
        await page.click('#fc-photo-again')
        await wait_reading(page)
        box = await page.ev(BOX)
        check('turned round and then read again: the reading replaces the turned lines, no word twice',
              [score(box, SHEETS['tabell'])[0], len([l for l in box.split('\n') if l.strip()])], [len(EN_TABLE), len(EN_TABLE)])
        seen = await read_file(page, files['kolumner'])
        box = await page.ev(BOX)
        exact, extra = score(box, SHEETS['kolumner'])
        check('a second page, English first and two columns: added after the first, turned Swedish first',
              [exact, len([l for l in box.split('\n') if l.strip()]), extra[:0]], [len(EN_COLUMNS), len(EN_TABLE) + len(EN_COLUMNS), []])
        check('it says that English came first', 'engelska stod först' in (seen[-1] if seen else ''), True)
        check('the name given already is kept', await page.ev("document.getElementById('fc-list-name').value"), 'Vecka 42')
        check('the reader was fetched once', len([r for r in page.requests if r['url'].endswith('worker.min.js')]), 1)
        await page.ev("document.getElementById('fc-list-save').click()")
        lists = json.loads(await page.ev("JSON.stringify(FC.inspect().store.lists)"))
        check('saved as a list of its own', [(l['name'], len(l['words'])) for l in lists], [('Vecka 42', len(EN_TABLE) + len(EN_COLUMNS))])
        check('and closing the editor lets the reader go', json.loads(await page.ev("JSON.stringify(FC.inspect().photo)"))['reader'], None)

        # --- more sheets, each in a fresh list -----------------------------------------------------------
        for name in ('streck', 'numrerad', 'spanska', 'spanska-tabell', 'sned', 'två-listor', 'mörk', 'app', 'skärm', 'lärobok'):
            sh = SHEETS[name]
            await open_editor(page, sh['lang'])
            seen = await read_file(page, files[name])
            box = await page.ev(BOX)
            exact, extra = score(box, sh)
            n = len(sh['pairs'])
            print(f'      {name}: {exact} of {n} exact{", extra: " + "; ".join(extra) if extra else ""}')
            check(f'{name}: the pairs, Swedish first (one may be misread)', exact >= n - 1 and not [e for e in extra if '=' in e and norm(e).split(' = ')[0] not in [norm(a) for a, _ in sh['pairs']]], True)
            if sh.get('name'):
                check(f'{name}: the list is named from the heading', await page.ev("document.getElementById('fc-list-name').value"), sh['name'])
            if sh['lang'] == 'es':
                check(f'{name}: read on Swedish and Spanish', any('svenska och spanska' in s for s in seen), True)
            if name == 'app':
                check('app: the clock, the battery and the app\'s word count are no pairs',
                      [l for l in box.split('\n') if any(t in l for t in ('12:05', '95', 'tecken', 'Uppgifter', 'Visa'))], [])
            await page.ev("document.querySelector('[data-on-click=\"fc:closeEditor\"]').click()")

        # --- what made no pair, and words the reader was unsure of -----------------------------------------
        await open_editor(page)
        await read_file(page, files['lärobok'])
        chips = await page.ev("[...document.querySelectorAll('.fc-photo-line')].map(b => b.textContent)")
        check('short lines that made no pair are offered; the paragraph is not', [('Words' in chips), any(len(c) > 40 for c in chips)], [True, False])
        before = await page.ev(BOX)
        await page.click('.fc-photo-line')
        after = await page.ev(BOX)
        check('a tap on one adds it to the box, for the rest to be written', [after.startswith(before), after.split('\n')[-1] == chips[0],
                                                                            await page.ev("document.querySelector('.fc-photo-line').disabled")], [True, True, True])
        check('where the editor asks for its pair', 'har inget = eller -' in await page.ev("document.getElementById('fc-list-status').textContent"), True)
        await page.ev("document.querySelector('[data-on-click=\"fc:closeEditor\"]').click()")

        # --- a photo on its side ---------------------------------------------------------------------
        await open_editor(page)
        seen = await read_file(page, files['liggande'])
        box = await page.ev(BOX)
        exact, extra = score(box, SHEETS['liggande'])
        check('a photo on its side gives hardly a word, so the reader turns it, and reads it', [exact, extra], [len(EN_FOOD), []])
        check('it says so on the way and after', [any(s.startswith('Hittade nästan inga ord') for s in seen), 'Bilden låg på sidan' in seen[-1]], [True, True])
        turned = json.loads(await page.ev("JSON.stringify(FC.inspect().photo)"))['turn']
        check('and the picture shown is turned the same way: the upright photo shown lying, the sheet in it upright',
              [turned in (90, 270), await settle(page, "(i => i.complete && i.naturalWidth > i.naturalHeight)(document.getElementById('fc-photo-img'))", True)],
              [True, True])
        for k in range(4):
            await page.click('#fc-photo-turn')
            await wait_reading(page)
            if k == 0:
                check('"Vrid bilden" reads it a quarter further round, as asked, and the reader does not turn it back',
                      [json.loads(await page.ev("JSON.stringify(FC.inspect().photo)"))['turn'], score(await page.ev(BOX), SHEETS['liggande'])[0] < len(EN_FOOD)],
                      [(turned + 90) % 360, True])
        box = await page.ev(BOX)
        check('four quarters round, the words are back - once, what the readings between put in the box gone',
              [score(box, SHEETS['liggande'])[0], len([l for l in box.split('\n') if l.strip()])], [len(EN_FOOD), len(EN_FOOD)])

        # --- "Läs igen" in Spanish, and cancelling ---------------------------------------------------------
        await page.ev("document.querySelector('[data-on-click=\"fc:closeEditor\"]').click()")
        await open_editor(page)
        await read_file(page, files['spanska-tabell'])
        wrong = await page.ev(BOX)
        await page.ev("document.querySelector('input[name=listlang][value=es]').click()")
        await page.click('#fc-photo-again')
        seen = await wait_reading(page)
        box = await page.ev(BOX)
        check('read in English first, then again in Spanish: the Spanish replaces it',
              [any('svenska och spanska' in s for s in seen), score(box, SHEETS['spanska-tabell'])[0] >= len(ES_TABLE) - 1,
               len([l for l in box.split('\n') if l.strip()]) == len(ES_TABLE), wrong != box], [True, True, True, True])
        await page.ev("document.querySelector('[data-on-click=\"fc:closeEditor\"]').click()")
        await open_editor(page)
        await choose_file(page, files['streck'])
        await settle(page, "!document.getElementById('fc-photo-cancel').hidden", True)
        await page.click('#fc-photo-cancel')
        await asyncio.sleep(2.5)
        check('Avbryt stops the reading: nothing is added', [await page.ev(BOX), await page.ev(STATUS),
                                                          json.loads(await page.ev("JSON.stringify(FC.inspect().photo)"))['reading']],
              ['', 'Läsningen avbröts.', False])

        # --- pasted, and dropped ----------------------------------------------------------------------------
        with open(files['två-listor'], 'rb') as f:
            b64 = base64.b64encode(f.read()).decode()
        started = await page.ev(f"""(async () => {{
          const bytes = Uint8Array.from(atob('{b64}'), c => c.charCodeAt(0));
          const dt = new DataTransfer();
          dt.items.add(new File([bytes], 'skärmbild.jpg', {{ type: 'image/jpeg' }}));
          dt.setData('text/plain', 'blå = blue');
          const withText = new ClipboardEvent('paste', {{ clipboardData: dt, bubbles: true, cancelable: true }});
          document.getElementById('fc-list-text').dispatchEvent(withText);
          const textToo = withText.defaultPrevented || !document.getElementById('fc-photo-cancel').hidden;
          const only = new DataTransfer();
          only.items.add(new File([bytes], 'skärmbild.jpg', {{ type: 'image/jpeg' }}));
          const picture = new ClipboardEvent('paste', {{ clipboardData: only, bubbles: true, cancelable: true }});
          document.getElementById('fc-list-text').dispatchEvent(picture);
          return [textToo, picture.defaultPrevented];
        }})()""")
        check('a paste with text in it is text; a pasted picture is read', started, [False, True])
        await wait_reading(page)
        check('the pasted picture gives its words', score(await page.ev(BOX), SHEETS['två-listor'])[0] >= len(COLOURS_L + COLOURS_R) - 1, True)
        await page.ev("document.querySelector('[data-on-click=\"fc:closeEditor\"]').click()")
        await open_editor(page)
        x, y = await page.ev("(r => [r.left + r.width / 2, r.top + 40])(document.getElementById('fc-editor').getBoundingClientRect())")
        drag = {'items': [], 'files': [files['numrerad']], 'dragOperationsMask': 1}
        for kind in ('dragEnter', 'dragOver'):
            await page.call('Input.dispatchDragEvent', {'type': kind, 'x': x, 'y': y, 'data': drag})
        check('a picture dragged over the editor marks it', await page.ev("document.getElementById('fc-editor').classList.contains('fc-drop')"), True)
        await page.call('Input.dispatchDragEvent', {'type': 'drop', 'x': x, 'y': y, 'data': drag})
        await wait_reading(page)
        check('a dropped picture is read', score(await page.ev(BOX), SHEETS['numrerad'])[0] >= len(EN_BODY) - 1, True)
        text = os.path.join(folder, 'glosor.txt')
        with open(text, 'w', encoding='utf-8') as f:
            f.write('hund = dog\n')
        drag = {'items': [], 'files': [text], 'dragOperationsMask': 1}
        for kind in ('dragEnter', 'dragOver', 'drop'):
            await page.call('Input.dispatchDragEvent', {'type': kind, 'x': x, 'y': y, 'data': drag})
        await asyncio.sleep(0.3)
        check('a file that is no picture is not read', (await page.ev(STATUS)).startswith('Det där är ingen bild'), True)
        await page.ev("document.querySelector('[data-on-click=\"fc:closeEditor\"]').click()")

        # --- a phone ---------------------------------------------------------------------------------------
        await page.size(390, 664, mobile=True)
        await page.load()
        await open_editor(page, 'es')
        await read_file(page, files['spanska'])
        fit = json.loads(await page.ev("""JSON.stringify((() => {
          const s = document.getElementById('fc-scroll');
          const top = id => document.getElementById(id).getBoundingClientRect().top;
          return { sideways: s.scrollWidth - s.clientWidth, statusFirst: top('fc-photo-status') < top('fc-photo-zoom'),
                   field: parseFloat(getComputedStyle(document.getElementById('fc-photo-file')).fontSize),
                   button: document.querySelector('.fc-photo-pick').getBoundingClientRect().height };
        })())"""))
        check('on a phone: nothing to scroll sideways, what the reading says above the picture, a field the phone will not zoom into',
              [fit['sideways'], fit['statusFirst'], fit['field'] >= 16, fit['button'] >= 42], [0, True, True, True])
        small = await page.ev("document.getElementById('fc-photo-img').getBoundingClientRect().height")
        await page.click('#fc-photo-zoom')
        big = await page.ev("document.getElementById('fc-photo-img').getBoundingClientRect().height")
        check('a tap on the picture shows it larger, another smaller again', [big > small * 1.3, await page.ev("document.getElementById('fc-photo-zoom').getAttribute('aria-pressed')")], [True, 'true'])
        await page.click('#fc-photo-zoom')
        await page.shot('photo-phone.png')
        await page.size(1300, 900)

        # --- a file that is not the pinned one is not run ---------------------------------------------------
        await page.call('Network.setCacheDisabled', {'cacheDisabled': True})
        count = "window.__workers = 0; const W0 = window.Worker; window.Worker = function (...a) { window.__workers++; return new W0(...a); };"
        await page.call('Fetch.enable', {'patterns': [{'urlPattern': '*worker.min.js*', 'requestStage': 'Response'}]})
        await page.load(init=count)
        await open_editor(page)
        await choose_file(page, files['tabell'])
        paused = await asyncio.wait_for(page.paused.get(), 60)
        body = await page.call('Fetch.getResponseBody', {'requestId': paused['requestId']})
        raw = base64.b64decode(body['result']['body']) if body['result'].get('base64Encoded') else body['result']['body'].encode()
        await page.call('Fetch.fulfillRequest', {'requestId': paused['requestId'], 'responseCode': 200,
                                                 'responseHeaders': [{'name': 'Content-Type', 'value': 'application/javascript'},
                                                                     {'name': 'Access-Control-Allow-Origin', 'value': '*'}],
                                                 'body': base64.b64encode(raw + b'\n;self.stolen = 1;').decode()})
        await wait_reading(page)
        await page.call('Fetch.disable')
        check('a reader that does not match its SHA-384 is not run', [(await page.ev(STATUS)).startswith('Läsprogrammet som kom var inte det väntade'),
                                                                   await page.ev('window.__workers'), await page.ev(BOX)], [True, 0, ''])

        # --- without the network ------------------------------------------------------------------------------
        await page.call('Fetch.enable', {'patterns': [{'urlPattern': 'https://cdn.jsdelivr.net/*'}]})
        await page.load()
        await open_editor(page)
        await choose_file(page, files['tabell'])
        failing = asyncio.ensure_future(wait_reading(page))
        while not failing.done():
            try:
                p = await asyncio.wait_for(page.paused.get(), 0.5)
                await page.call('Fetch.failRequest', {'requestId': p['requestId'], 'errorReason': 'InternetDisconnected'})
            except asyncio.TimeoutError:
                pass
        await page.call('Fetch.disable')
        check('without the network it says so', (await page.ev(STATUS)).startswith('Läsprogrammet gick inte att hämta'), True)
        await page.call('Network.setCacheDisabled', {'cacheDisabled': False})

        # --- a browser that cannot ------------------------------------------------------------------------------
        await page.load(init='delete window.WebAssembly;')
        await open_editor(page)
        check('without WebAssembly there is no photo button, and the editor works as before',
              [await page.ev("document.getElementById('fc-photo').hidden"), await page.ev("document.getElementById('fc-list-text').checkVisibility()")], [True, True])

        unexpected = [e for e in page.errors if 'did not match' not in e]
        console = [c for c in page.console if 'did not match' not in c and 'ERR_INTERNET_DISCONNECTED' not in c and 'Failed to load resource' not in c]
        check('no uncaught errors, and nothing in the console but what was provoked', [unexpected, console], [[], []])

    shutil.rmtree(folder, ignore_errors=True)
    print(f'\n{checks - len(failures)} of {checks} checks passed.')
    sys.exit(1 if failures else 0)


asyncio.run(main())
