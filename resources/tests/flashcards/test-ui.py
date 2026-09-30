#!/usr/bin/env python3
"""flashcards.html in a real browser, played the way a child plays it.

Answers are typed and keys pressed as trusted CDP events. Speech is a stub
installed before the page loads, with an English and a Spanish voice (or
none), so what is read out can be checked on any machine.

Start a server on the repository root and headless Chrome, by default on
ports 8848 and 9348 (FC_HTTP_PORT and FC_CDP_PORT for others; check them first
with lsof -nP -iTCP:<port> -sTCP:LISTEN, other sessions use ports too):

    python3 -m http.server 8848 --bind 127.0.0.1
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \\
      --headless=new --remote-debugging-port=9348 --no-first-run \\
      --user-data-dir=/tmp/fctest --disable-gpu about:blank

    python3 resources/tests/flashcards/test-ui.py

With FC_SHOTS=<folder> it saves screenshots and the printed cards as a PDF.
Exit status is 0 when every check passes.
"""
import asyncio
import base64
import json
import os
import sys
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


KEYS = {
    'Enter': ('Enter', 13, '\r'), ' ': ('Space', 32, ' '), 'ArrowRight': ('ArrowRight', 39, ''),
    'ArrowLeft': ('ArrowLeft', 37, ''), 'k': ('KeyK', 75, 'k'),
    '1': ('Digit1', 49, '1'), '2': ('Digit2', 50, '2'), '3': ('Digit3', 51, '3'), '4': ('Digit4', 52, '4'),
}

# Speech as a stub: voices for English and Spanish, or none, and a record of what is said.
SPEECH = """(() => {
  const voices = %s;
  window.__spoken = [];
  window.__spokenAt = [];
  const stub = { getVoices: () => voices, speak: u => { window.__spoken.push([u.text, u.lang]); window.__spokenAt.push(performance.now()); }, cancel: () => {},
                 addEventListener: () => {}, speaking: false };
  Object.defineProperty(window, 'speechSynthesis', { value: stub, configurable: true });
  window.SpeechSynthesisUtterance = function (text) { this.text = text; };
})();"""
VOICES = "[{ lang: 'en-GB', name: 'Test English' }, { lang: 'es-ES', name: 'Test Español' }]"


class Page:
    def __init__(self, bws):
        self.bws = bws
        self.n = 0
        self.pending = {}
        self.sid = None
        self.errors = []
        self.console = []
        self.script = None

    async def call(self, method, params=None, timeout=60):
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
            if r.get('method') == 'Runtime.exceptionThrown':
                d = r['params']['exceptionDetails']
                self.errors.append(str(d.get('exception', {}).get('description') or d.get('text', ''))[:300])
            if r.get('method') == 'Runtime.consoleAPICalled' and r['params']['type'] == 'error':
                self.console.append(' '.join(str(a.get('value', a.get('description', ''))) for a in r['params']['args'])[:300])
            if 'id' in r and r['id'] in self.pending and not self.pending[r['id']].done():
                self.pending[r['id']].set_result(r)

    async def ev(self, expr):
        r = await self.call('Runtime.evaluate', {'expression': expr, 'returnByValue': True, 'awaitPromise': True})
        res = r.get('result', {})
        if 'exceptionDetails' in res:
            return 'EXCEPTION: ' + str(res['exceptionDetails'].get('exception', {}).get('description', ''))[:300]
        return res.get('result', {}).get('value')

    async def key(self, k):
        code, vk, text = KEYS[k]
        down = {'type': 'keyDown', 'key': k, 'code': code, 'windowsVirtualKeyCode': vk}
        if text:
            down['text'] = text
        await self.call('Input.dispatchKeyEvent', down)
        await self.call('Input.dispatchKeyEvent', {'type': 'keyUp', 'key': k, 'code': code, 'windowsVirtualKeyCode': vk})

    async def type(self, text):
        await self.call('Input.insertText', {'text': text})

    async def click(self, selector):
        """A real click, with the mouse: unlike element.click(), it counts as the
        tap after which a browser lets a page make sound."""
        x, y = await self.ev(f"(e => {{ e.scrollIntoView({{ block: 'center' }}); const r = e.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; }})(document.querySelector({json.dumps(selector)}))")
        for kind in ('mousePressed', 'mouseReleased'):
            await self.call('Input.dispatchMouseEvent', {'type': kind, 'x': x, 'y': y, 'button': 'left', 'clickCount': 1})

    async def load(self, width=1400, height=900, theme='light', storage=None, mobile=False, voices=VOICES, url=URL):
        """A fresh page: this size and theme, its storage as given, speech as a stub with these voices."""
        await self.call('Emulation.setDeviceMetricsOverride',
                        {'width': width, 'height': height, 'deviceScaleFactor': 1, 'mobile': mobile})
        if self.script:
            await self.call('Page.removeScriptToEvaluateOnNewDocument', {'identifier': self.script})
        r = await self.call('Page.addScriptToEvaluateOnNewDocument', {'source': SPEECH % voices})
        self.script = r['result']['identifier']
        await self.call('Page.navigate', {'url': f'{ORIGIN}/robots.txt'})
        await settle(self, "document.readyState", 'complete')
        await self.ev(f"localStorage.clear(); localStorage.setItem('kvot-theme', {json.dumps(theme)});"
                      + (f"localStorage.setItem('flashcards.v1', {json.dumps(storage)});" if storage is not None else ''))
        await self.call('Page.navigate', {'url': url})
        await settle(self, "!!(window.FC && document.querySelectorAll('.wk-tile').length)", True)
        await asyncio.sleep(0.2)

    async def reload(self):
        await self.call('Page.reload', {'ignoreCache': True})
        await asyncio.sleep(0.3)
        await settle(self, "!!(window.FC && document.querySelectorAll('.wk-tile').length)", True)

    async def shot(self, name):
        if not SHOTS:
            return
        os.makedirs(SHOTS, exist_ok=True)
        await asyncio.sleep(0.5)
        r = await self.call('Page.captureScreenshot', {'format': 'png'})
        with open(os.path.join(SHOTS, name), 'wb') as f:
            f.write(base64.b64decode(r['result']['data']))


async def settle(page, expr, want, tries=60, pause=0.1):
    got = None
    for _ in range(tries):
        got = await page.ev(expr)
        if got == want:
            return got
        await asyncio.sleep(pause)
    return got


async def rnd(page):
    s = await page.ev("JSON.stringify(FC.inspect().round)")
    return json.loads(s) if s and s != 'null' else None


async def phase(page, want):
    return await settle(page, "FC.inspect().round && FC.inspect().round.phase", want)


async def play_card(page, answer=None, advance=True):
    """Type the answer to the card in front of us (the right one unless given)."""
    await phase(page, 'answer')
    r = await rnd(page)
    await page.ev("document.getElementById('fc-input').focus()")
    await page.type(r['answer'] if answer is None else answer)
    await page.key('Enter')
    await phase(page, 'feedback')
    after = await rnd(page)
    if advance:
        await page.key('Enter')
        await settle(page, f"(() => {{ const r = FC.inspect().round; return !r || r.phase === 'done' || r.i > {r['i']}; }})()", True)
    return after


async def play_round(page, wrong=()):
    r = await rnd(page)
    for i in range(r['n']):
        await play_card(page, 'qqqq' if i in wrong else None)
    await settle(page, "!document.getElementById('fc-summary').hidden", True)


async def choose(page, *ids):
    await page.ev("document.querySelector('[data-on-click=\"fc:clear\"]').click()")
    for i in ids:
        await page.ev(f"document.querySelector('[data-set=\"{i}\"]').click()")


async def start(page):
    await page.ev("document.getElementById('fc-start').click()")
    await phase(page, 'answer')
    await asyncio.sleep(0.3)  # past the card's fade-in


async def setting(page, name, value):
    if value in (True, False):
        await page.ev(f"(i => {{ if (i.checked !== {str(value).lower()}) i.click(); }})(document.querySelector('#fc-settings input[name={name}]'))")
    else:
        await page.ev(f"document.querySelector('#fc-settings input[name={name}][value=\"{value}\"]').click()")


async def home(page):
    await page.ev("(b => b && b.click())(document.querySelector('[data-on-click=\"fc:quit\"]:not([hidden])'))")
    await settle(page, "!document.getElementById('fc-home').hidden", True)


CHROME = """JSON.stringify((() => {
  const shown = sel => { const e = document.querySelector(sel); return !!e && e.checkVisibility(); };
  const c = document.querySelector('.content').getBoundingClientRect();
  return { header: shown('body > header'), footer: shown('body > footer'), brand: shown('.wk-brand'),
           theme: shown('.wk-top-end > .theme-toggle'), full: shown('#fc-home .wk-fullbtn'),
           top: Math.round(c.top), fills: Math.round(c.height) === innerHeight };
})())"""

FIT = """JSON.stringify((() => {
  const s = document.getElementById('fc-scroll');
  const d = document.getElementById('fc-deck').getBoundingClientRect();
  const bottoms = ['fc-actions', 'fc-choices', 'fc-accents', 'fc-input'].map(id => document.getElementById(id))
    .filter(e => e && e.checkVisibility()).map(e => Math.round(e.getBoundingClientRect().bottom));
  return { vh: innerHeight, deckH: Math.round(d.height), deckBottom: Math.round(d.bottom), lowest: Math.max(0, ...bottoms),
           scroll: s.scrollHeight - s.clientHeight, sideways: s.scrollWidth - s.clientWidth,
           ratio: Math.round(d.width / d.height * 100) / 100 };
})())"""

STILL = """JSON.stringify((() => {
  const css = e => getComputedStyle(e);
  const fields = [...document.querySelectorAll('select, input[type=text], textarea')];
  return { smallest: Math.min(...fields.map(f => parseFloat(css(f).fontSize))),
           touch: css(document.documentElement).touchAction, html: css(document.documentElement).overflow, body: css(document.body).position };
})())"""

PHONES = [(390, 664, 'iPhone upright'), (844, 340, 'iPhone on its side'), (375, 548, 'iPhone SE upright'),
          (667, 325, 'iPhone SE on its side'), (360, 560, 'small Android upright')]


async def main():
    ver = json.load(urllib.request.urlopen(f'http://127.0.0.1:{CDP}/json/version'))
    async with websockets.connect(ver['webSocketDebuggerUrl'], max_size=200 * 1024 * 1024) as bws:
        page = Page(bws)
        asyncio.create_task(page.pump())
        tid = (await page.call('Target.createTarget', {'url': 'about:blank'}))['result']['targetId']
        page.sid = (await page.call('Target.attachToTarget', {'targetId': tid, 'flatten': True}))['result']['sessionId']
        for m in ('Runtime.enable', 'Page.enable', 'Network.enable'):
            await page.call(m)
        await page.call('Network.setCacheDisabled', {'cacheDisabled': True})
        try:
            await run(page)
        finally:
            await page.call('Target.closeTarget', {'targetId': tid})
    print(f'\n{checks - len(failures)} of {checks} checks passed.')
    sys.exit(1 if failures else 0)


async def run(page):
    await page.load()

    # --- the home view -----------------------------------------------------------------
    check('no script errors on load', page.errors + page.console, [])
    check('English: 25 themes in five groups, and "Mina glosor"',
          await page.ev("[document.querySelectorAll('#fc-groups .wk-tile').length, document.querySelectorAll('#fc-groups .wk-group').length, !!document.getElementById('fc-g-own')]"),
          [25, 5, True])
    check('nothing chosen: Börja öva, Titta först and Skriv ut are off',
          await page.ev("['fc-start', 'fc-study-btn', 'fc-print-btn'].map(id => document.getElementById(id).disabled)"), [True, True, True])
    check('the settings as they start', await page.ev("document.getElementById('fc-settings-sum').textContent"),
          'Svenska → engelska · Skriv ordet · 20 kort per omgång')
    check('the Spanish settings are for Spanish', await page.ev("document.querySelector('.fc-es-only').checkVisibility({ checkVisibilityCSS: true })"), False)
    await choose(page, 'husdjur')
    check('choosing a theme', await page.ev("document.getElementById('fc-selbar-text').textContent"), 'Djur hemma och på gården · 16 kort')
    await page.shot('home.png')

    # --- a round typed, all right ---------------------------------------------------------
    await start(page)
    r = await rnd(page)
    check('sixteen cards, Swedish on the front, asked "på engelska"',
          [r['n'], r['kind'], await page.ev("document.getElementById('fc-ask').textContent"), await page.ev("document.getElementById('fc-prompt').lang")],
          [16, 'word', 'på engelska', 'sv'])
    check('the answer is typed on the card, in a 16px field or larger',
          await page.ev("[document.activeElement.id, parseFloat(getComputedStyle(document.activeElement).fontSize) >= 16]"), ['fc-input', True])
    check('the back, with the answer, is hidden from a screen reader until the card turns',
          await page.ev("document.getElementById('fc-back').getAttribute('aria-hidden')"), 'true')
    check('no loudspeaker on a Swedish front: it would say the answer', await page.ev("!!document.querySelector('#fc-prompt .fc-say')"), False)
    await page.shot('practice.png')
    after = await play_card(page, advance=False)
    check('right goes to Kan, and the card turns', [after['kan'], await page.ev("document.getElementById('fc-card').dataset.side")], [1, 'back'])
    check('the word is read out once the card has turned', await settle(page, "window.__spoken.length ? window.__spoken[0] : null", [after['answer'], 'en-GB']), [after['answer'], 'en-GB'])
    await page.shot('practice-back.png')
    await page.key('Enter')
    for _ in range(15):
        await play_card(page)
    await settle(page, "!document.getElementById('fc-summary').hidden", True)
    check('all sixteen in Kan', await page.ev("[document.getElementById('fc-sum-title').textContent, document.getElementById('fc-sum-kan').textContent]"),
          ['Alla kort hamnade i Kan-högen!', '16'])
    check('known the first time: box 3', await page.ev("FC.inspect().stat('en|till|dog|hund').box"), 3)
    await page.ev("document.querySelector('[data-on-click=\"fc:home\"]').click()")
    check('the tile shows it', await page.ev("document.querySelector('[data-set=husdjur] .wk-tile-meta').textContent"), '16 ord · 16 kan')

    # --- almost, wrong, and the Öva mer pile ---------------------------------------------------
    await choose(page, 'familj')
    await start(page)
    r = await rnd(page)
    near = r['answer'][:-1] + ('x' if r['answer'][-1] != 'x' else 'y') if len(r['answer']) >= 4 else 'qqqq'
    after = await play_card(page, near, advance=False)
    check('one letter off is almost, into Öva mer', [after['ova'], (await page.ev("document.getElementById('fc-feedback').textContent")).startswith('Nästan! Det stavas' if len(r['answer']) >= 4 else 'Inte riktigt')],
          [1, True])
    check('and waits, with Nästa kort focused', await page.ev("document.activeElement.id"), 'fc-next')
    await page.key('Enter')
    after = await play_card(page, 'qqqq', advance=False)
    check('something else is wrong, and says what it is called', (await page.ev("document.getElementById('fc-feedback').textContent")).startswith('Inte riktigt – det heter '), True)
    await page.key('Enter')
    for _ in range(r['n'] - 2):
        await play_card(page)
    await settle(page, "!document.getElementById('fc-summary').hidden", True)
    check('two to practise', await page.ev("[document.getElementById('fc-sum-ova').textContent, document.querySelectorAll('.wk-chip').length]"), ['2', 2])
    await page.ev("document.querySelector('[data-on-click=\"fc:home\"]').click()")
    check('back home, they are due: "Att repetera" holds the two',
          await page.ev("[!!document.querySelector('[data-set=repetera]'), document.querySelector('[data-set=repetera] .wk-tile-meta').textContent]"), [True, '2 ord'])
    await choose(page, 'repetera')
    await start(page)
    check('"Dags att repetera" is those two', (await rnd(page))['n'], 2)
    await play_round(page)
    check('right after a miss: box 2, not due again today', await page.ev("!!document.querySelector('[data-set=repetera]')"), True)
    await page.ev("document.querySelector('[data-on-click=\"fc:home\"]').click()")
    check('so "Att repetera" is gone', await page.ev("!!document.querySelector('[data-set=repetera]')"), False)
    await page.ev("""(() => {
      const s = JSON.parse(localStorage.getItem('flashcards.v1'));
      for (const st of Object.values(s.profiles.p1.facts)) if (st.box === 2) st.d = '2020-01-01';
      localStorage.setItem('flashcards.v1', JSON.stringify(s)); return true; })()""")
    await page.reload()
    check('two days on, box 2 is due again', await page.ev("document.querySelector('[data-set=repetera] .wk-tile-meta')?.textContent"), '2 ord')

    # --- capitals, the other way round, and mixed ---------------------------------------------------
    await choose(page, 'dagar')
    await start(page)
    r = await rnd(page)
    after = await play_card(page, r['answer'].lower(), advance=False)
    check('monday in lower case is right, and shows how it is written',
          [after['kan'], await page.ev("document.getElementById('fc-feedback').textContent")], [1, f"Rätt! Det skrivs {r['answer']}."])
    await home(page)
    await page.ev("document.getElementById('fc-settings').open = true")
    await setting(page, 'dir', 'fran')
    await choose(page, 'husdjur')
    await start(page)
    r = await rnd(page)
    check('the other way round: the English word on the front, with its loudspeaker, asked "på svenska"',
          [await page.ev("document.getElementById('fc-prompt').lang"), await page.ev("!!document.querySelector('#fc-prompt .fc-say')"),
           await page.ev("document.getElementById('fc-ask').textContent"), r['key'].startswith('en|fran|')], ['en', True, 'på svenska', True])
    await page.ev("window.__spoken = []; document.querySelector('#fc-prompt .fc-say').click()")
    check('which reads out the word on the front', await page.ev("window.__spoken[0]"), [r['front'], 'en-GB'])
    after = await play_card(page, 'en ' + r['answer'], advance=False)
    check('a Swedish answer may have its article', after['kan'], 1)
    await home(page)
    await setting(page, 'dir', 'blandat')
    await choose(page, 'husdjur')
    await start(page)
    keys = json.loads(await page.ev("JSON.stringify(FC.inspect().keys)"))
    check('mixed: each word once, one way or the other',
          [len(keys), len({k.split('|')[2] for k in keys}), all(k.split('|')[1] in ('till', 'fran') for k in keys)], [16, 16, True])
    await home(page)
    await setting(page, 'dir', 'till')

    # --- four to choose from ------------------------------------------------------------------------
    await setting(page, 'mode', 'valj')
    await choose(page, 'mat')
    await start(page)
    r = await rnd(page)
    right = r['options'].index(r['answer'])
    check('four options, the answer among them, the first one focused',
          [len(r['options']), r['answer'] in r['options'], await page.ev("document.activeElement.classList.contains('fc-choice')")], [4, True, True])
    await page.shot('choose.png')
    await page.key(str(right + 1))
    await phase(page, 'feedback')
    check('its number key chooses it: right, and marked so',
          [(await rnd(page))['kan'], await page.ev(f"document.querySelector('.fc-choice[data-i=\"{right}\"]').dataset.state")], [1, 'right'])
    await page.key('Enter')
    await phase(page, 'answer')
    r = await rnd(page)
    wrong = next(i for i, o in enumerate(r['options']) if o != r['answer'])
    await page.ev(f"document.querySelector('.fc-choice[data-i=\"{wrong}\"]').click()")
    await phase(page, 'feedback')
    check('a wrong choice goes to Öva mer, and both are marked',
          [(await rnd(page))['ova'], await page.ev(f"document.querySelector('.fc-choice[data-i=\"{wrong}\"]').dataset.state"),
           await page.ev(f"document.querySelector('.fc-choice[data-i=\"{r['options'].index(r['answer'])}\"]').dataset.state")], [1, 'wrong', 'right'])
    await home(page)

    # --- turn the card over ----------------------------------------------------------------------------
    await setting(page, 'mode', 'vand')
    await choose(page, 'kropp')
    await start(page)
    await page.key(' ')
    await phase(page, 'judge')
    check('Space turns the card; the child says which pile',
          await page.ev("[...document.querySelectorAll('#fc-actions button')].map(b => b.textContent).join(' | ')"), '← Öva mer | Kan →')
    await page.key('ArrowRight')
    await phase(page, 'answer')
    await page.key(' ')
    await phase(page, 'judge')
    await page.key('ArrowLeft')
    await phase(page, 'answer')
    r = await rnd(page)
    check('→ and ← sort it', [r['kan'], r['ova'], r['i']], [1, 1, 2])
    await home(page)

    # --- listen and write ------------------------------------------------------------------------------
    await setting(page, 'mode', 'lyssna')
    await choose(page, 'frukt')
    await page.ev("window.__spoken = []")
    await start(page)
    r = await rnd(page)
    check('listening: no word on the front, a loudspeaker, and the word read out at once',
          [await page.ev("document.querySelector('#fc-prompt .fc-prompt-text')"), await page.ev("!!document.querySelector('.fc-say-big')"),
           await settle(page, "window.__spoken.length ? window.__spoken[0] : null", [r['say'], 'en-GB'])],
          [None, True, [r['say'], 'en-GB']])
    after = await play_card(page, advance=False)
    check('and what is heard is written', after['kan'], 1)
    await home(page)
    await setting(page, 'mode', 'skriv')

    # --- the hint ------------------------------------------------------------------------------------------
    await choose(page, 'skola')
    await start(page)
    await page.ev("document.querySelector('[data-on-click=\"fc:hint\"]').click()")
    r = await rnd(page)
    letters = await page.ev("document.querySelector('.fc-hint-letters').textContent")
    check('the hint: the first letter and a line for each of the others',
          [letters[0], letters.count('_'), r['answer'] in letters], [r['answer'][0], len(r['answer'].replace(' ', '')) - len(r['answer'].split(' ')), False])
    after = await play_card(page, advance=False)
    check('right with the hint goes to Öva mer', [after['kan'], after['ova']], [0, 1])
    await home(page)

    # --- irregular verbs ----------------------------------------------------------------------------------
    await choose(page, 'irr1')
    await start(page)
    r = await rnd(page)
    check('an irregular verb: the base form on the front, the two forms asked',
          [r['kind'], await page.ev("document.getElementById('fc-ask').textContent")], ['forms', 'dåtid och perfekt particip'])
    after = await play_card(page, r['answer'].replace(' ', ', '), advance=False)
    check('"went, gone" is right', after['kan'], 1)
    await page.ev("window.__spoken = []; document.querySelector('#fc-prompt .fc-say').click()")
    check('its front loudspeaker says the base form only, never the forms asked', await page.ev("window.__spoken[0][0]"), r['front'])
    await home(page)

    # --- Spanish ---------------------------------------------------------------------------------------------
    await page.ev("document.querySelector('.fc-lang [data-lang=es]').click()")
    check('Spanish: 26 themes, the grammar its own, and the Spanish settings',
          await page.ev("[document.querySelectorAll('#fc-groups .wk-tile').length, !!document.querySelector('[data-set=genus]'), !!document.querySelector('[data-set=irr1]'), document.querySelector('.fc-es-only').checkVisibility()]"),
          [26, True, False, True])
    await choose(page, 'husdjur')
    await start(page)
    for _ in range(16):
        r = await rnd(page)
        if r['answer'] == 'el ratón':
            break
        await play_card(page)
    check('the Spanish letters are there to press', await page.ev("[...document.querySelectorAll('#fc-accents button')].map(b => b.textContent).join('')"), 'áéíóúñü')
    if r['answer'] == 'el ratón':
        await page.ev("document.getElementById('fc-input').focus()")
        await page.type('rat')
        await page.ev("document.querySelector('#fc-accents [data-char=\"ó\"]').click()")
        await page.type('n')
        check('pressing ó puts it where the cursor is, and keeps the field in focus',
              await page.ev("[document.getElementById('fc-input').value, document.activeElement.id]"), ['ratón', 'fc-input'])
    await home(page)
    await choose(page, 'husdjur')
    await start(page)
    r = await rnd(page)
    bare = r['answer'].split(' ', 1)[1]
    after = await play_card(page, bare, advance=False)
    check('a noun without its article is right, and shows the article',
          [after['kan'], await page.ev("document.getElementById('fc-feedback').textContent")], [1, f"Rätt! Med artikel: {r['answer']}."])
    await home(page)
    await page.ev("document.getElementById('fc-settings').open = true")
    await setting(page, 'article', 'krav')
    await setting(page, 'accents', 'krav')
    await choose(page, 'husdjur')
    await start(page)
    r = await rnd(page)
    after = await play_card(page, r['answer'].split(' ', 1)[1], advance=False)
    check('unless the article must be there', [after['ova'], (await page.ev("document.getElementById('fc-feedback').textContent")).startswith('Glöm inte artikeln')], [1, True])
    await home(page)
    await setting(page, 'article', 'valfri')
    await setting(page, 'accents', 'valfri')
    await choose(page, 'genus')
    await setting(page, 'mode', 'valj')
    await start(page)
    r = await rnd(page)
    check('el or la: two to choose from, and the noun without its article', [sorted(r['options']), r['front'].split(' ')[0] not in ('el', 'la')], [['el', 'la'], True])
    await page.ev("window.__spoken = []; (b => b && b.click())(document.querySelector('#fc-prompt .fc-say'))")
    check('the front loudspeaker says the noun, not its article', await page.ev("window.__spoken.length ? window.__spoken[0][0] : null"), r['front'])
    await home(page)
    await setting(page, 'mode', 'skriv')
    await choose(page, 'konj1')
    await start(page)
    r = await rnd(page)
    after = await play_card(page, advance=False)
    check('a verb form, typed', after['kan'], 1)
    await page.key('Enter')
    await phase(page, 'answer')
    r = await rnd(page)
    after = await play_card(page, f"yo {r['answer']}", advance=False)
    check('with a pronoun in front too', after['kan'], 2)
    await page.ev("window.__spoken = []; document.querySelector('#fc-prompt .fc-say').click()")
    check('and the front says only the infinitive: never "vosotros sois"', await page.ev("window.__spoken[0][0]"), r['front'])
    await home(page)

    # --- a list of one's own --------------------------------------------------------------------------------
    await page.ev("document.querySelector('.fc-lang [data-lang=en]').click()")
    await page.ev("document.querySelector('[data-on-click=\"fc:newList\"]').click()")
    check('the editor opens under Mina glosor', await page.ev(
          "[!document.getElementById('fc-editor').hidden, document.getElementById('fc-groups-own').nextElementSibling.id]"), [True, 'fc-editor'])
    await page.ev("document.getElementById('fc-list-name').focus()")
    await page.type('Vecka 12')
    await page.ev("document.getElementById('fc-list-text').focus()")
    await page.type('hund = dog\nsvamp - mushroom\nbara ett ord\nmamma = mum / mom')
    check('it counts the words and says which line has no pair', await page.ev("document.getElementById('fc-list-status').textContent"),
          '3 ord · rad 3 har inget = eller - mellan orden: ”bara ett ord”')
    await page.ev("document.getElementById('fc-list-save').click()")
    await asyncio.sleep(0.3)
    check('saved: a tile of its own, chosen, and the editor closed',
          await page.ev("[!!document.querySelector('[data-set=l1]'), document.querySelector('[data-set=l1]').getAttribute('aria-pressed'), document.getElementById('fc-editor').hidden]"),
          [True, 'true', True])
    # The list's words are the theme cards: hund = dog is known from Djur, and
    # svamp = mushroom may be, if the listening round above happened to ask it.
    known = await page.ev("['en|till|dog|hund', 'en|till|mushroom|svamp', 'en|till|mum|mamma'].filter(k => FC.inspect().status(k) === 'kan').length")
    check('"hund = dog" of one’s own is the Djur card, known already, and the tile counts it',
          [await page.ev("FC.inspect().status('en|till|dog|hund')"), await page.ev("document.querySelector('[data-set=l1] .wk-tile-meta').textContent")],
          ['kan', f'3 ord · {known} kan'])
    await page.ev("document.querySelector('[data-on-click=\"fc:shareList\"]').click()")
    await settle(page, "!!document.querySelector('.fc-share input')", True)
    link = await page.ev("document.querySelector('.fc-share input').value")
    check('Dela gives a link with the list in it', link.startswith(f'{ORIGIN}/flashcards.html#glosor='), True)
    await page.ev("document.querySelector('[data-on-click=\"fc:editList\"]').click()")
    check('Ändra brings the list back as text', await page.ev("document.getElementById('fc-list-text').value"), 'hund = dog\nsvamp = mushroom\nmamma = mum / mom')
    await page.ev("document.querySelector('[data-on-click=\"fc:closeEditor\"]').click()")

    # --- the link, opened by somebody else ------------------------------------------------------------------------
    await page.load(url=link)
    check('the link offers the list, and adds nothing unasked',
          await page.ev("[!document.getElementById('fc-import').hidden, document.getElementById('fc-import-text').textContent, JSON.parse(localStorage.getItem('flashcards.v1') || '{\"lists\":[]}').lists.length]"),
          [True, 'Någon har delat glosorna ”Vecka 12”: 3 ord på engelska.', 0])
    await page.ev("document.querySelector('[data-on-click=\"fc:importYes\"]').click()")
    await asyncio.sleep(0.2)
    check('Lägg till: the list is theirs, chosen, and the link is gone from the address',
          await page.ev("[FC.inspect().store.lists.length, document.querySelector('[data-set=l1]').getAttribute('aria-pressed'), location.hash, document.getElementById('fc-import').hidden]"),
          [1, 'true', '', True])
    hostile = await page.ev("""(() => {
      const json = JSON.stringify({ n: '<img src=x onerror="window.__pwned=1">', l: 'es', w: [['<b>fet</b>', '<script>window.__pwned=1</script>']] });
      const bytes = new TextEncoder().encode(json); let bin = ''; for (const b of bytes) bin += String.fromCharCode(b);
      return location.origin + location.pathname + '#glosor=' + btoa(bin).replace(/\\+/g, '-').replace(/\\//g, '_').replace(/=+$/, ''); })()""")
    await page.load(url=hostile)
    await page.ev("document.querySelector('[data-on-click=\"fc:importYes\"]').click()")
    await asyncio.sleep(0.2)
    check('a hostile list is text: its name, its words, never markup',
          await page.ev("[document.querySelector('[data-set=l1] .wk-tile-title').textContent, !!document.querySelector('.wk-tile img, .wk-tile b, .wk-tile script'), !!window.__pwned, FC.inspect().store.lists[0].lang]"),
          ['<img src=x onerror="window.__pwned=1">', False, False, 'es'])
    await page.load(url=f'{URL}#glosor=aGVq')
    check('a link with no list in it says so, and is dropped', await page.ev("[document.getElementById('fc-import').hidden, location.hash]"), [True, ''])

    # --- looking first, and printing ------------------------------------------------------------------------------
    await page.load()
    await choose(page, 'farger', 'husdjur')
    await page.ev("document.getElementById('fc-study-btn').click()")
    check('Titta först: every word with its translation, and a loudspeaker',
          await page.ev("[document.querySelectorAll('.fc-study-row').length, document.querySelector('.fc-study-row .fc-study-sv').textContent !== '', document.querySelectorAll('.fc-study-row .fc-say').length]"),
          [27, True, 27])
    await page.ev("window.__spoken = []; document.querySelector('.fc-study-row .fc-say').click()")
    check('which reads the word out', await page.ev("window.__spoken[0][1]"), 'en-GB')
    await page.ev("document.querySelector('.fc-study-end [data-on-click=\"fc:start\"]').click()")
    check('and then the words are covered, and the round begins', await phase(page, 'answer'), 'answer')
    await home(page)
    await choose(page, 'farger', 'husdjur')
    await page.ev("window.print = () => { window.__printed = (window.__printed || 0) + 1; }")
    await page.ev("document.getElementById('fc-print-btn').click()")
    sheets = json.loads(await page.ev("JSON.stringify([...document.querySelectorAll('#wk-print .wk-sheet')].map(s => [s.dataset.side, s.querySelectorAll('.wk-pc:not(.wk-pc-empty)').length]))"))
    check('27 cards: two sheets, front and back', sheets, [['front', 18], ['back', 18], ['front', 9], ['back', 9]])
    row = json.loads(await page.ev("""JSON.stringify([
      [...document.querySelectorAll('#wk-print .wk-sheet')[0].querySelectorAll('.wk-pc-eq')].slice(0, 3).map(e => e.textContent),
      [...document.querySelectorAll('#wk-print .wk-sheet')[1].querySelectorAll('.wk-pc-ans')].slice(0, 3).map(e => e.textContent)])"""))
    check('Swedish on the front, and behind each, mirrored, the English', row, [['röd', 'blå', 'gul'], ['yellow', 'blue', 'red']])
    await page.call('Emulation.setEmulatedMedia', {'media': 'print'})
    pdf = await page.call('Page.printToPDF', {'preferCSSPageSize': True, 'printBackground': True})
    data = base64.b64decode(pdf['result']['data'])
    check('four A4 pages', data.count(b'/Type /Page') - data.count(b'/Type /Pages'), 4)
    if SHOTS:
        with open(os.path.join(SHOTS, 'cards.pdf'), 'wb') as f:
            f.write(data)
    await page.call('Emulation.setEmulatedMedia', {'media': ''})

    # --- no voice -----------------------------------------------------------------------------------------------------
    await page.load(voices='[]')
    await page.ev("document.getElementById('fc-settings').open = true")
    check('without a voice: no listening, a word on why, and no loudspeakers',
          await page.ev("[document.querySelector('input[name=mode][value=lyssna]').disabled, !document.getElementById('fc-speech-help').hidden]"), [True, True])
    await choose(page, 'husdjur')
    await start(page)
    await play_card(page, advance=False)
    check('not on the back either', await page.ev("document.getElementById('fc-say-back').hidden"), True)
    check('no script errors so far', page.errors + page.console, [])

    # --- sound effects (Winnetkakort's) -------------------------------------------------------------------------------------
    SOUND = "JSON.stringify([...document.querySelectorAll('.wk-soundbtn')].map(b => b.getAttribute('aria-pressed')))"
    sounds = "FC.inspect().sounds"
    await page.load()
    check('sounds: the same module as Winnetkakort, and off to begin with, with no audio made',
          [await page.ev("WK_SOUND.names.length"), json.loads(await page.ev(SOUND)), await page.ev("document.querySelector('#fc-settings input[name=sound]').checked"),
           await page.ev("FC.inspect().audio")], [9, ['false', 'false'], False, 'none'])
    await choose(page, 'husdjur')
    await start(page)
    await page.ev("window.__spokenAt = []")
    t0 = await page.ev("performance.now()")
    await play_card(page, advance=False)
    await settle(page, "window.__spokenAt.length", 1)
    check('off: no sound at all, and the word is read out as the card turns',
          [await page.ev(sounds), await page.ev("FC.inspect().audio"), await page.ev(f"window.__spokenAt[0] - {t0} < 600")], [[], 'none', True])
    await page.key('Enter')
    await page.click('.wk-bar .wk-soundbtn')
    check('the practice bar’s loudspeaker switches them on, for both buttons, the setting and this person',
          [json.loads(await page.ev(SOUND)), await page.ev("document.querySelector('#fc-settings input[name=sound]').checked"),
           await page.ev("FC.inspect().store.profiles.p1.settings.sound")], [['true', 'true'], True, True])
    check('switching on plays the chime, and the audio runs', [await page.ev(sounds), await settle(page, "FC.inspect().audio", 'running')], [['right'], 'running'])
    await phase(page, 'answer')
    await page.ev("window.__spokenAt = []")
    t0 = await page.ev("performance.now()")
    await play_card(page, advance=False)
    check('right: the swish as the card turns, and the chime', (await page.ev(sounds))[-2:], ['flip', 'right'])
    await settle(page, "window.__spokenAt.length", 1)
    check('and the word is read out after the chime, not on top of it', await page.ev(f"window.__spokenAt[0] - {t0} >= 600"), True)
    await page.key('Enter')
    await settle(page, "FC.inspect().sounds.at(-1)", 'land')
    check('then the tap as it lands in its pile', (await page.ev(sounds))[-1], 'land')
    await phase(page, 'answer')
    while len((await rnd(page))['answer']) < 5:
        await play_card(page)
    r = await rnd(page)
    await play_card(page, r['answer'][:-1] + ('x' if r['answer'][-1] != 'x' else 'y'), advance=False)
    check('one letter off, "nästan": the softer note, not the uh-oh', (await page.ev(sounds))[-1], 'okay')
    await page.key('Enter')
    await play_card(page, 'qqqq', advance=False)
    check('a wrong word: the soft uh-oh', (await page.ev(sounds))[-1], 'wrong')
    await page.key('Enter')
    await phase(page, 'answer')
    await page.ev("document.querySelector('[data-on-click=\"fc:hint\"]').click()")
    check('the hint makes its small bubble', (await page.ev(sounds))[-1], 'hint')
    await play_card(page, advance=False)
    check('right with the hint: the softer note', (await page.ev(sounds))[-1], 'okay')
    await page.key('Enter')
    await phase(page, 'answer')
    r = await rnd(page)
    for _ in range(r['n'] - r['i']):
        await play_card(page)
    await settle(page, "!document.getElementById('fc-summary').hidden", True)
    check('a finished pile with words to practise: the short fanfare', (await page.ev(sounds))[-1], 'done')
    await page.ev("document.querySelector('[data-on-click=\"fc:home\"]').click()")
    await choose(page, 'dagar')
    await start(page)
    await play_round(page)
    check('every word in Kan: the bright fanfare', (await page.ev(sounds))[-1], 'allKan')
    await page.ev("document.querySelector('[data-on-click=\"fc:home\"]').click()")
    await page.ev("document.getElementById('fc-settings').open = true")
    await setting(page, 'mode', 'valj')
    await choose(page, 'farger')
    await start(page)
    r = await rnd(page)
    await page.key(str(r['options'].index(r['answer']) + 1))
    await phase(page, 'feedback')
    check('choosing the right one: the swish and the chime', (await page.ev(sounds))[-2:], ['flip', 'right'])
    await home(page)
    await setting(page, 'mode', 'vand')
    await choose(page, 'kropp')
    await start(page)
    await page.key(' ')
    await phase(page, 'judge')
    check('turning the card over: the swish', (await page.ev(sounds))[-1], 'flip')
    await page.key('ArrowRight')
    await phase(page, 'answer')
    check('then "Kan": the chime and the tap', (await page.ev(sounds))[-3:], ['flip', 'right', 'land'])
    await home(page)
    await setting(page, 'mode', 'skriv')
    await page.ev("document.getElementById('fc-newperson-btn').click()")
    await page.type('Kim')
    await page.key('Enter')
    check('a new person has sounds of their own: off', [json.loads(await page.ev(SOUND)), await settle(page, "FC.inspect().audio", 'suspended')],
          [['false', 'false'], 'suspended'])
    await page.ev("(s => { s.value = 'p1'; s.dispatchEvent(new Event('change', { bubbles: true })); })(document.getElementById('fc-who'))")
    check('and switching back brings the first person’s back on', [json.loads(await page.ev(SOUND)), await settle(page, "FC.inspect().audio", 'running')],
          [['true', 'true'], 'running'])
    await page.reload()
    check('after a reload they are still on, and wait for the first tap', [json.loads(await page.ev(SOUND)), await page.ev("FC.inspect().audio")],
          [['true', 'true'], 'none'])
    await choose(page, 'husdjur')
    await page.click('#fc-start')
    await phase(page, 'answer')
    check('that tap starts them', await settle(page, "FC.inspect().audio", 'running'), 'running')
    await home(page)
    await page.ev("document.getElementById('fc-settings').open = true")
    await page.click('#fc-settings input[name=sound]')
    check('the setting switches them off, both buttons with it, and the audio sleeps',
          [json.loads(await page.ev(SOUND)), await settle(page, "FC.inspect().audio", 'suspended')], [['false', 'false'], 'suspended'])
    before = await page.ev(sounds)
    await start(page)
    await play_card(page, advance=False)
    check('and off is silent', await page.ev(sounds), before)
    check('no script errors with the sounds', page.errors + page.console, [])

    # --- the full window ------------------------------------------------------------------------------------------------
    await page.load()
    await page.ev("document.querySelector('#fc-home .wk-fullbtn').click()")
    chrome = json.loads(await page.ev(CHROME))
    check('the full window: no site chrome, the page bar instead, remembered',
          [chrome['header'], chrome['footer'], chrome['brand'], chrome['theme'], chrome['top'], await page.ev("localStorage.getItem('flashcards.full')")],
          [False, False, True, True, 0, '1'])
    await page.ev("document.querySelector('#fc-home .wk-fullbtn').click()")

    # --- phones ----------------------------------------------------------------------------------------------------------
    await page.call('Emulation.setTouchEmulationEnabled', {'enabled': True, 'maxTouchPoints': 5})
    for width, height, name in PHONES:
        await page.load(width, height, mobile=True)
        chrome = json.loads(await page.ev(CHROME))
        check(f'{name}: no site header or footer, the page bar instead', [chrome['header'], chrome['footer'], chrome['brand'], chrome['full'], chrome['fills']],
              [False, False, True, False, True])
        still = json.loads(await page.ev(STILL))
        check(f'{name}: no field under 16px, no double-tap zoom, and the page cannot move',
              [still['smallest'] >= 16, still['touch'], still['html'], still['body']], [True, 'manipulation', 'hidden', 'fixed'])
        check(f'{name}: no sideways scroll on the home view', await page.ev("(s => s.scrollWidth - s.clientWidth)(document.getElementById('fc-scroll'))"), 0)
        for mode, pile, lang in (('skriv', 'husdjur', 'en'), ('valj', 'mat', 'en'), ('skriv', 'frukt', 'es')):
            await page.ev(f"document.querySelector('.fc-lang [data-lang={lang}]').click()")
            await page.ev("document.getElementById('fc-settings').open = true")
            await setting(page, 'mode', mode)
            await choose(page, pile)
            await start(page)
            fit = json.loads(await page.ev(FIT))
            check(f'{name}, {mode} {lang}: the card and what answers it fit, nothing to scroll',
                  [fit['lowest'] <= fit['vh'], fit['deckBottom'] <= fit['vh'], fit['scroll'], fit['sideways'], fit['ratio'], fit['deckH'] >= 100],
                  [True, True, 0, 0, 1.5, True])
            if mode == 'skriv' and lang == 'es':
                await page.shot(f"{name.replace(' ', '-')}.png")
            await home(page)
        # The keyboard up: flashcards.js sets --fc-vh to what is left above it.
        await page.ev("document.querySelector('.fc-lang [data-lang=en]').click()")
        await setting(page, 'mode', 'skriv')
        await choose(page, 'husdjur')
        await start(page)
        room = round(height * 0.55)
        await page.ev(f"document.documentElement.style.setProperty('--fc-vh', '{room}px')")
        await asyncio.sleep(0.2)
        typing = json.loads(await page.ev("JSON.stringify((() => { const i = document.getElementById('fc-input').getBoundingClientRect(); return { input: Math.round(i.bottom), prompt: Math.round(document.getElementById('fc-prompt').getBoundingClientRect().top) }; })())"))
        check(f'{name}: with the keyboard up, the word and the answer stay above it',
              [typing['input'] <= room, typing['prompt'] >= 0], [True, True])
        await page.ev("document.documentElement.style.removeProperty('--fc-vh')")
        await home(page)
    await page.call('Emulation.setTouchEmulationEnabled', {'enabled': False})

    # --- storage that is not ours ---------------------------------------------------------------------------------------
    page.errors.clear()
    await page.load(storage='{not json')
    check('broken storage: the page starts afresh', await page.ev("[document.querySelectorAll('#fc-groups .wk-tile').length, FC.inspect().store.current]"), [25, 'p1'])
    bad = json.dumps({'v': 1, 'current': 'p1', 'profiles': {'p1': {'name': '<b>x</b>', 'settings': {'lang': 'fr', 'mode': 'hack', 'count': 7},
                      'facts': {'__proto__': {'n': 3, 'box': 3}, 'en|till|dog|hund': {'n': 'x'}}}, 'evil': {'name': 'y'}},
                      'lists': [{'id': 'l1', 'name': 'ok', 'lang': 'en', 'words': [['a', 'b'], [1, 2]]}, {'id': 'x', 'lang': 'en', 'words': [['a', 'b']]},
                                {'id': 'l2', 'lang': 'de', 'words': [['a', 'b']]}]})
    await page.load(storage=bad)
    check('unknown settings, people and lists are dropped; the good list keeps its good word',
          await page.ev("(s => [s.profiles.p1.settings.lang, s.profiles.p1.settings.mode, s.profiles.p1.settings.count, Object.keys(s.profiles).join(), s.lists.map(l => l.id + ':' + l.words.length).join()])(FC.inspect().store)"),
          ['en', 'skriv', 20, 'p1', 'l1:1'])
    check('a name from storage is text', await page.ev("[document.getElementById('fc-who').options[0].textContent, !!document.querySelector('#fc-who b')]"), ['<b>x</b>', False])
    check('and a key cannot reach the prototype', await page.ev("({}).n === undefined && FC.inspect().status('en|till|dog|hund')"), 'none')
    await page.load(theme='dark')
    await page.shot('home-dark.png')
    check('no script errors at the end', page.errors + page.console, [])


asyncio.run(main())
