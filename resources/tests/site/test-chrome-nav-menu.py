"""The site menu: every project under its heading, on any screen.

As one list the menu had grown taller than a laptop's screen (1011px in an
800px window), and being fixed it could not be scrolled, so the last projects
could not be reached at all; on a phone over half of them were off the bottom.
The menu now sets the headings side by side where there is room, scrolls
inside itself where there is not, and has a field that narrows the list.

Checked on every page that draws the menu: every project is in it once, the
page one is on marked and not a link, all of it on the screen at 1440 x 800
with nothing to scroll, and the open/close behaviour. Then the find field and
the keyboard on the landing page and on rdc.html (which has a <nav> of its
own), the menu on phones upright and on their side, and the landing page's
projects under the same headings, its list for browsers without scripts and
the sitemap included.

Serve the repository and start headless Chrome (the recipe is in README.md),
by default on ports 8765 and 9222; SITE_HTTP_PORT and SITE_CDP_PORT choose
others. Exit status is 0 when every check passes.
"""
import asyncio, json, os, pathlib, re, sys, time, urllib.request, websockets

HTTP = int(os.environ.get('SITE_HTTP_PORT', '8765'))
CDP = int(os.environ.get('SITE_CDP_PORT', '9222'))
ROOT = pathlib.Path(__file__).resolve().parents[3]

# Every page that draws the menu, found the way a reader would: by the call.
PAGES = sorted(p.name for p in ROOT.glob('*.html') if 'KVOT.renderNav(' in p.read_text(encoding='utf-8'))

# The headings in order, each with the group name the projects carry.
GROUPS = [('Data and statistics', 'data'), ('Nuclear data and dose', 'nuclear'), ('Modelling', 'models'),
          ('Reports and references', 'documents'), ('Accounts and tax', 'accounts'), ('Everyday', 'everyday')]
HEADINGS = [h for h, _ in GROUPS]

# What the menu says about itself, read on any page.
MENU = """JSON.stringify((() => {
  const menu = document.getElementById('menu');
  const toggle = document.querySelector('.nav-toggle');
  return {
    parents: [menu.parentElement.tagName, toggle.parentElement.tagName],
    role: menu.getAttribute('role'),
    tag: menu.tagName,
    headings: [...menu.querySelectorAll('.nav-group-label')].map(e => e.textContent),
    entries: [...menu.querySelectorAll('li[data-project]')].map(li => {
      const a = li.querySelector('a');
      return a ? ['link', a.getAttribute('href'), a.textContent] : ['here', li.textContent.trim(),
        li.querySelector('[aria-current="page"]') ? 'current' : 'unmarked'];
    }),
    home: (() => { const h = menu.querySelector('.nav-home');
                   return h.tagName === 'A' ? ['link', h.getAttribute('href')] : ['here', h.getAttribute('aria-current')]; })(),
    projects: KVOT.PROJECTS.map(p => [p.href, p.label, p.group]),
  };
})())"""

GEOMETRY = """JSON.stringify((() => {
  const menu = document.getElementById('menu');
  const panel = menu.querySelector('.nav-panel').getBoundingClientRect();
  const list = menu.querySelector('.nav-groups');
  const header = document.querySelector('header').getBoundingClientRect();
  return {
    open: menu.classList.contains('open'),
    expanded: document.querySelector('.nav-toggle').getAttribute('aria-expanded'),
    focus: document.activeElement.className,
    top: Math.round(panel.top), bottom: Math.round(panel.bottom),
    left: Math.round(panel.left), right: Math.round(panel.right),
    headerBottom: Math.round(header.bottom), vw: innerWidth, vh: innerHeight,
    scrollH: list.scrollHeight, clientH: list.clientHeight,
    scrollW: list.scrollWidth, clientW: list.clientWidth,
  };
})())"""

SHOWN = """JSON.stringify((() => {
  const menu = document.getElementById('menu');
  const visible = e => e.getClientRects().length > 0;
  return {
    items: [...menu.querySelectorAll('li[data-project]')].filter(visible).map(li => li.textContent.trim()),
    headings: [...menu.querySelectorAll('.nav-group')].filter(visible).map(g => g.querySelector('.nav-group-label').textContent),
    picked: [...menu.querySelectorAll('.nav-picked')].map(a => a.textContent),
    status: menu.querySelector('.nav-empty').textContent,
    statusShown: visible(menu.querySelector('.nav-empty')),
  };
})())"""

failures = []
checks = 0


def check(label, got, want=True):
    global checks
    checks += 1
    ok = got == want
    print(f'{"ok  " if ok else "FAIL"}  {label}' + ('' if ok else f': {got!r} (expected {want!r})'))
    if not ok:
        failures.append(label)


async def main():
    ver = json.load(urllib.request.urlopen(f'http://127.0.0.1:{CDP}/json/version'))
    async with websockets.connect(ver['webSocketDebuggerUrl'], max_size=64 * 1024 * 1024) as ws:
        n = 0
        pending = {}
        sid = None
        thrown = []

        async def pump():
            async for raw in ws:
                r = json.loads(raw)
                if 'id' in r and r['id'] in pending:
                    pending.pop(r['id']).set_result(r)
                elif r.get('method') == 'Runtime.exceptionThrown':
                    d = r['params']['exceptionDetails']
                    thrown.append((d.get('exception', {}).get('description') or d.get('text', ''))[:200])

        async def call(method, params=None):
            nonlocal n
            n += 1
            msg = {'id': n, 'method': method, 'params': params or {}}
            if sid and not method.startswith('Target.'):
                msg['sessionId'] = sid
            fut = asyncio.get_event_loop().create_future()
            pending[n] = fut
            await ws.send(json.dumps(msg))
            return await asyncio.wait_for(fut, 60)

        async def ev(expr):
            r = await call('Runtime.evaluate', {'expression': expr, 'returnByValue': True, 'awaitPromise': True})
            if 'exceptionDetails' in r['result']:
                return 'EXCEPTION ' + json.dumps(r['result']['exceptionDetails'])[:300]
            value = r['result']['result'].get('value')
            return json.loads(value) if isinstance(value, str) and value.startswith(('{', '[')) else value

        async def screen(width, height, phone=False):
            await call('Emulation.setDeviceMetricsOverride',
                       {'width': width, 'height': height, 'deviceScaleFactor': 1, 'mobile': phone})
            await call('Emulation.setTouchEmulationEnabled', {'enabled': phone, 'maxTouchPoints': 5 if phone else 1})

        async def load(page):
            thrown.clear()
            await call('Page.navigate', {'url': f'http://127.0.0.1:{HTTP}/{page}?nocache={int(time.time() * 1000)}'})
            for _ in range(150):
                if await ev("document.readyState === 'complete' && !!document.querySelector('#menu .nav-panel')"):
                    break
                await asyncio.sleep(0.1)
            await asyncio.sleep(0.3)

        async def key(name, code=None, text=None, keycode=0):
            base = {'key': name, 'code': code or name, 'windowsVirtualKeyCode': keycode}
            await call('Input.dispatchKeyEvent', {'type': 'keyDown', **base, **({'text': text} if text else {})})
            await call('Input.dispatchKeyEvent', {'type': 'keyUp', **base})
            await asyncio.sleep(0.05)

        async def click_at(x, y):
            for kind in ('mousePressed', 'mouseReleased'):
                await call('Input.dispatchMouseEvent', {'type': kind, 'x': x, 'y': y, 'button': 'left', 'clickCount': 1})
            await asyncio.sleep(0.3)

        async def find(text):
            await ev(f"(() => {{ const s = document.querySelector('.nav-search'); s.value = {json.dumps(text)};"
                     " s.dispatchEvent(new Event('input', { bubbles: true })); })()")
            return await ev(SHOWN)

        # Measured once the panel has finished sliding in: a busy page can
        # still be part-way through the transition after a fixed wait.
        async def open_menu():
            await ev("document.querySelector('.nav-toggle').click()")
            await ev("Promise.all(['#menu', '#menu .nav-panel'].flatMap(s => document.querySelector(s).getAnimations())"
                     ".map(a => a.finished)).then(() => true)")

        asyncio.create_task(pump())
        tid = (await call('Target.createTarget', {'url': 'about:blank'}))['result']['targetId']
        sid = (await call('Target.attachToTarget', {'targetId': tid, 'flatten': True}))['result']['sessionId']
        await call('Page.enable')
        await call('Runtime.enable')
        await call('Network.enable')
        await call('Network.setCacheDisabled', {'cacheDisabled': True})
        try:
            # ── Every page ────────────────────────────────────────────────
            await screen(1440, 800)
            projects = None
            for page in PAGES:
                await load(page)
                m = await ev(MENU)
                if projects is None:
                    projects = m['projects']
                    check('every project names one of the headings', sorted({p[2] for p in projects} - {g for _, g in GROUPS}), [])
                where = page
                check(f'{where}: the toggle and the menu are children of <body>, the menu a div with a role',
                      [m['parents'], m['tag'], m['role']], [['BODY', 'BODY'], 'DIV', 'navigation'])
                check(f'{where}: the headings, in order', m['headings'], HEADINGS)
                hrefs = [e[1] if e[0] == 'link' else None for e in m['entries']]
                listed = {p[0] for p in projects}
                mine = './' + page
                want = [['link', p[0], p[1]] if p[0] != mine else ['here', p[1], 'current']
                        for _, g in GROUPS for p in projects if p[2] == g]
                check(f'{where}: every project once, under its heading, '
                      + ('this page marked and not a link' if mine in listed else 'every one a link'),
                      m['entries'], want)
                check(f'{where}: home', m['home'], ['here', 'page'] if page == 'index.html' else ['link', './index.html'])
                check(f'{where}: no link to the page itself', mine in hrefs, False)

                await open_menu()
                g = await ev(GEOMETRY)
                check(f'{where}: the toggle opens it, the field taking the keyboard',
                      [g['open'], g['expanded'], g['focus']], [True, 'true', 'nav-search'])
                check(f'{where}: under the header and on the screen',
                      [g['top'] >= g['headerBottom'], g['bottom'] <= g['vh'], g['left'] >= 0, g['right'] <= g['vw']],
                      [True, True, True, True])
                check(f'{where}: at 1440 x 800 all of it is in view, nothing to scroll',
                      [g['scrollH'] <= g['clientH'], g['scrollW'] <= g['clientW']], [True, True])
                await key('Escape', keycode=27)
                g = await ev(GEOMETRY)
                check(f'{where}: Escape closes it and gives the keyboard back to the toggle',
                      [g['open'], g['expanded'], g['focus']], [False, 'false', 'nav-toggle'])
                check(f'{where}: no script errors', thrown, [])

            # ── The find field and the keyboard ───────────────────────────
            for page in ('index.html', 'rdc.html'):
                await load(page)
                await open_menu()
                s = await find('farf')
                check(f'{page}: "farf" leaves FARF31 under Modelling, picked for Enter',
                      [s['items'], s['headings'], s['picked']],
                      [['FARF31 Far-Field Transport'], ['Modelling'], ['FARF31 Far-Field Transport']])
                s = await find('arsredovisning')
                check(f'{page}: accents are folded away', s['items'], ['Digital årsredovisning'])
                s = await find('STAMMARE')
                check(f'{page}: and case ignored', s['items'], ['Gitarrstämmare'])
                s = await find('vocabulary')
                check(f'{page}: a description is looked in too', s['items'], ['Glosor'])
                s = await find('uppsala solna')
                check(f'{page}: every word must be found', s['items'], ['Uppsala → Solna', 'Solna → Uppsala'])
                s = await find('text')
                check(f'{page}: a name that matches is picked before a description that does',
                      ['Zoterify' in s['items'], s['picked']], [True, ['Svensk text']])
                s = await find('qqqq')
                check(f'{page}: nothing found: no project, no heading, and it says so',
                      [s['items'], s['headings'], s['status'], s['statusShown']],
                      [[], [], 'No project matches “qqqq”.', True])
                s = await find('')
                check(f'{page}: an empty field shows them all, none picked',
                      [len(s['items']), s['picked'], s['statusShown']], [len(projects), [], False])

                await key('ArrowDown', keycode=40)
                check(f'{page}: Down from the field goes to the first project',
                      await ev('document.activeElement.textContent'), 'HDF5 Browser')
                await key('ArrowDown', keycode=40)
                check(f'{page}: and on to the next', await ev('document.activeElement.textContent'), 'Probability Distributions')
                await key('ArrowUp', keycode=38)
                await key('ArrowUp', keycode=38)
                check(f'{page}: Up from the first goes back to the field',
                      await ev('document.activeElement.className'), 'nav-search')
                await find('dose')
                await key('ArrowDown', keycode=40)
                check(f'{page}: with a search, Down goes to the project Enter would open',
                      await ev('document.activeElement.textContent'), 'Dose Coefficients')
                await key('k', 'KeyK', 'k', 75)
                check(f'{page}: typing on a project goes on in the field',
                      await ev("[document.activeElement.className, document.querySelector('.nav-search').value]"),
                      ['nav-search', 'dosek'])

                await ev("window.__keysSeen = 0; document.addEventListener('keydown', e => { if (e.key !== 'Escape') window.__keysSeen++; })")
                await find('')
                await ev("document.querySelector('.nav-search').focus()")
                for ch in 'rb':
                    await key(ch, 'Key' + ch.upper(), ch, ord(ch.upper()))
                await key('ArrowDown', keycode=40)
                check(f'{page}: keys used in the menu do not reach the page underneath', await ev('window.__keysSeen'), 0)

                await ev("window.__pageClicks = 0; document.addEventListener('click', e => { if (!e.target.closest('#menu, .nav-toggle')) window.__pageClicks++; }, true)")
                await ev("document.querySelector('.nav-group-label').click()")
                check(f'{page}: a click inside the menu keeps it open', await ev("document.getElementById('menu').classList.contains('open')"), True)
                g = await ev(GEOMETRY)
                x, y = 40, g['vh'] - 80
                check(f'{page}: the dimmed page is the menu\'s while it is open',
                      await ev(f"document.elementFromPoint({x}, {y}).id"), 'menu')
                await click_at(x, y)
                check(f'{page}: a click on the dimmed page closes the menu and reaches nothing under it',
                      await ev("[document.getElementById('menu').classList.contains('open'), window.__pageClicks]"), [False, 0])
                check(f'{page}: closed, the menu lets clicks through',
                      await ev(f"document.elementFromPoint({x}, {y}).closest('#menu') === null"), True)

                await open_menu()
                s = await find('qqqq')
                await key('Escape', keycode=27)
                await open_menu()
                s = await ev(SHOWN)
                check(f'{page}: opened again, the field is empty and every project back',
                      [await ev("document.querySelector('.nav-search').value"), len(s['items'])], ['', len(projects)])

                await ev("[...document.querySelectorAll('#menu li a')].pop().focus()")
                await key('Tab', keycode=9)
                check(f'{page}: Tab past the last project closes the menu',
                      await ev("[document.getElementById('menu').classList.contains('open'), !!document.activeElement.closest('#menu')]"),
                      [False, False])
                if page == 'rdc.html':
                    check('rdc.html: its own <nav> is still the first one on the page',
                          await ev("!!document.querySelector('nav') && !document.querySelector('nav').closest('#menu')"), True)
                check(f'{page}: no script errors', thrown, [])

            await load('index.html')
            await open_menu()
            await find('farf')
            await key('Enter', keycode=13, text='\r')
            for _ in range(80):
                if (await ev('location.pathname')) == '/FARF31.html':
                    break
                await asyncio.sleep(0.1)
            check('Enter in the field opens the project it picked', await ev('location.pathname'), '/FARF31.html')

            # ── Phones ────────────────────────────────────────────────────
            for width, height in ((390, 664), (375, 548), (360, 560), (844, 340), (600, 900)):
                await screen(width, height, phone=True)
                await load('kompartment.html')
                await open_menu()
                g = await ev(GEOMETRY)
                where = f'kompartment.html on a {width} x {height} touch screen'
                check(f'{where}: the field waits for a tap rather than raising the keyboard', g['focus'] != 'nav-search', True)
                check(f'{where}: the field is 16px or more, so iOS does not zoom',
                      await ev("parseFloat(getComputedStyle(document.querySelector('.nav-search')).fontSize) >= 16"), True)
                if width <= 700:
                    check(f'{where}: a sheet from under the header to the bottom of the screen',
                          [g['top'], g['bottom'], g['left'], g['right']], [g['headerBottom'], height, 0, width])
                else:
                    check(f'{where}: on the screen', [g['top'] >= g['headerBottom'], g['bottom'] <= height,
                                                     g['left'] >= 0, g['right'] <= width], [True, True, True, True])
                check(f'{where}: nothing to scroll sideways', g['scrollW'] <= g['clientW'], True)
                reach = await ev("""JSON.stringify((() => {
                  const list = document.querySelector('.nav-groups');
                  list.scrollTop = 1e6;
                  const last = [...list.querySelectorAll('li')].pop().getBoundingClientRect();
                  const box = list.getBoundingClientRect();
                  const rows = [...list.querySelectorAll('li')].map(li => li.getBoundingClientRect().height);
                  list.scrollTop = 0;
                  return { inView: last.top >= box.top - 1 && last.bottom <= box.bottom + 1, lowest: Math.min(...rows) };
                })())""")
                check(f'{where}: the last project can be scrolled to', reach['inView'], True)
                check(f'{where}: every row is 44px or more for a fingertip', reach['lowest'] >= 44, True)
                if width <= 560:
                    stuck = await ev("""JSON.stringify((() => {
                      const list = document.querySelector('.nav-groups');
                      const labels = [...list.querySelectorAll('.nav-group-label')];
                      list.scrollTop = labels[2].parentElement.offsetTop + 100;
                      const top = list.getBoundingClientRect().top;
                      const out = labels.map(l => Math.round(l.getBoundingClientRect().top - top));
                      list.scrollTop = 0;
                      return out;
                    })())""")
                    check(f'{where}: the heading of the projects in view sticks to the top', stuck[2], 0)
                check(f'{where}: no script errors', thrown, [])

            # ── The landing page and the 404 ──────────────────────────────
            await screen(1440, 800)
            for page in ('index.html', '404.html'):
                await load(page)
                grid = await ev("""JSON.stringify([...document.querySelectorAll('#project-grid .project-group')].map(g => [
                  g.querySelector('.project-group-title').textContent,
                  [...g.querySelectorAll('.project-card')].map(c => c.getAttribute('href'))]))""")
                check(f'{page}: the projects under the menu\'s headings, each once',
                      grid, [[h, [p[0] for p in projects if p[2] == g]] for h, g in GROUPS])
            text = (ROOT / 'index.html').read_text(encoding='utf-8')
            noscript = re.search(r'<noscript>(.*?)</noscript>', text, re.S).group(1)
            lists = [[h, re.findall(r'href="([^"]+)"', body)]
                     for h, body in re.findall(r'<h3 class="project-group-title">([^<]+)</h3>\s*<ul class="link-list">(.*?)</ul>', noscript, re.S)]
            check('index.html without scripts: the same projects under the same headings',
                  lists, [[h, [p[0] for p in projects if p[2] == g]] for h, g in GROUPS])
            sitemap = (ROOT / 'sitemap.xml').read_text(encoding='utf-8')
            check('the sitemap has every project',
                  [p[0] for p in projects if 'https://kvotab.se/' + p[0][2:] not in sitemap], [])
        finally:
            await call('Target.closeTarget', {'targetId': tid})
    print(f'\n{checks - len(failures)} of {checks} checks passed.')
    sys.exit(1 if failures else 0)


asyncio.run(main())
