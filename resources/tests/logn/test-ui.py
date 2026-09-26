#!/usr/bin/env python3
"""logn.html in a real browser: the (i) panels, and the page still working.

The page loads without a script error and computes; every (i) slot has a topic
and every "Read more" a target (KvotInfo.audit()); the (i)s are where they
should be and as many as there should be; one opens its panel with its title,
between the site header and footer, and the ×, Escape and the same (i) close
it; a topic that marks the current choice follows the setting; "Read more"
opens the equations at the right heading; the hover tooltips are gone; and the
page does what it did before — a metric swap carries the distribution, a data
set is fitted, a second distribution brings the comparison.

Start a server on the repository root and headless Chrome (the recipe is in
../rb/README.md), by default on ports 8813 and 9313 (LOGN_HTTP_PORT and
LOGN_CDP_PORT for others), then

    python3 resources/tests/logn/test-ui.py

With LOGN_SHOTS=<folder> it also saves screenshots with a panel open, light
and dark, at 1500 × 950 and 420 × 900. Exit status is 0 when every check
passes.
"""
import asyncio
import base64
import json
import os
import sys
import urllib.request

import websockets

HTTP = int(os.environ.get('LOGN_HTTP_PORT', '8813'))
CDP = int(os.environ.get('LOGN_CDP_PORT', '9313'))
URL = f'http://127.0.0.1:{HTTP}/logn.html'
SHOTS = os.environ.get('LOGN_SHOTS')

# One distribution on μ and σ draws these, as it did before there could be
# several (test-chrome-distributions.py in ../site checks the same).
ORIGINAL_TRACES = ['Outer PDF', 'Shaded PDF', 'Outer PDF', 'P50', 'CDF (theoretical)']
# The (i)s on screen at load: the Distributions bar, the metric pills, the two
# panels, and the headings of Computed results, the chart, the settings and
# the equations. The Comparison's is there but hidden with its section, and
# the twelve settings are folded away with theirs.
AT_LOAD = ['set:dists', 'set:metrics', 'metric:mu', 'metric:sigma',
           'sec:results', 'sec:chart', 'sec:settings', 'sec:equations']
SETTINGS = ['set:digits', 'set:unit', 'set:lnview', 'set:curves', 'set:raw', 'set:chartMin',
            'set:chartMax', 'set:band', 'set:shadeFrom', 'set:shadeTo', 'set:ref', 'set:refPct']
COLUMN = ['set:dists', 'set:metrics', 'metric:sigma', 'sec:results', 'sec:chart', 'sec:settings',
          'sec:equations']

failures = []
checks = 0


def check(label, got, want=True):
    global checks
    checks += 1
    ok = got == want
    print(f'{"ok  " if ok else "FAIL"}  {label}' + ('' if ok else f': {got!r} (expected {want!r})'))
    if not ok:
        failures.append(label)


class Page:
    def __init__(self, bws):
        self.bws = bws
        self.n = 0
        self.pending = {}
        self.sid = None
        self.errors = []
        self.theme_script = None

    async def call(self, method, params=None, session=None, timeout=60):
        self.n += 1
        i = self.n
        msg = {'id': i, 'method': method, 'params': params or {}}
        if session:
            msg['sessionId'] = session
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
            if 'id' in r and r['id'] in self.pending and not self.pending[r['id']].done():
                self.pending[r['id']].set_result(r)

    async def ev(self, expr):
        r = await self.call('Runtime.evaluate',
                            {'expression': expr, 'returnByValue': True, 'awaitPromise': True},
                            session=self.sid)
        res = r.get('result', {})
        if 'exceptionDetails' in res:
            return 'EXCEPTION: ' + str(res['exceptionDetails'].get('exception', {}).get('description', ''))[:300]
        return res.get('result', {}).get('value')

    async def load(self, width, height, theme):
        """A fresh page at this size, in this theme (set before the first paint)."""
        await self.call('Emulation.setDeviceMetricsOverride',
                        {'width': width, 'height': height, 'deviceScaleFactor': 1, 'mobile': False},
                        session=self.sid)
        if self.theme_script:
            await self.call('Page.removeScriptToEvaluateOnNewDocument', {'identifier': self.theme_script},
                            session=self.sid)
        r = await self.call('Page.addScriptToEvaluateOnNewDocument',
                            {'source': f"try{{localStorage.setItem('kvot-theme', {json.dumps(theme)})}}catch(e){{}}"},
                            session=self.sid)
        self.theme_script = r['result']['identifier']
        await self.call('Page.navigate', {'url': URL}, session=self.sid)
        await settle(self, "!!(window.KvotInfo && document.getElementById('chart').data)", True)
        await asyncio.sleep(0.4)

    async def shot(self, name):
        if not SHOTS:
            return
        os.makedirs(SHOTS, exist_ok=True)
        r = await self.call('Page.captureScreenshot', {'format': 'png'}, session=self.sid)
        with open(os.path.join(SHOTS, name), 'wb') as f:
            f.write(base64.b64decode(r['result']['data']))


async def settle(page, expr, want, tries=40, pause=0.25):
    got = None
    for _ in range(tries):
        got = await page.ev(expr)
        if got == want:
            return got
        await asyncio.sleep(pause)
    return got


def js_click_info(key):
    return f"document.querySelector('[data-info=\"{key}\"]').click()"


PANEL = """(() => {
  const p = document.querySelector('.info-panel');
  if (!p) return null;
  const r = p.getBoundingClientRect();
  return { kicker: p.querySelector('.info-panel-kicker').textContent,
           title: p.querySelector('.info-panel-title').textContent,
           current: [...p.querySelectorAll('.info-choices dt.is-current')].map(d => d.textContent),
           top: Math.round(r.top), bottom: Math.round(r.bottom), right: Math.round(r.right),
           headerBottom: Math.round(document.querySelector('header').getBoundingClientRect().bottom),
           footerTop: Math.round(document.querySelector('footer').getBoundingClientRect().top),
           width: document.documentElement.clientWidth };
})()"""

VISIBLE = "[...document.querySelectorAll('.kvot-info-slot .info-btn')].filter(b => b.checkVisibility()).map(b => b.dataset.info)"

# Where each (i) stands against its line: the right edge of the button, of
# the label line it is on, and of the field under that line.
GEOMETRY = """(() => {
  const right = el => el ? Math.round(el.getBoundingClientRect().right) : null;
  const out = { column: {}, settings: {} };
  for (const b of document.querySelectorAll('.kvot-info-slot .info-btn')) {
    if (!b.checkVisibility()) continue;
    const line = b.closest('.kvot-info-line');
    if (line) {
      const field = line.parentElement.querySelector('input:not([type=checkbox]), select');
      out.settings[b.dataset.info] = [right(b), right(line), right(field)];
    } else out.column[b.dataset.info] = right(b);
  }
  out.scrollX = document.documentElement.scrollWidth - document.documentElement.clientWidth;
  return JSON.stringify(out);
})()"""


async def main():
    ver = json.load(urllib.request.urlopen(f'http://127.0.0.1:{CDP}/json/version'))
    async with websockets.connect(ver['webSocketDebuggerUrl'], max_size=200 * 1024 * 1024) as bws:
        page = Page(bws)
        asyncio.create_task(page.pump())
        tid = (await page.call('Target.createTarget', {'url': 'about:blank'}))['result']['targetId']
        page.sid = (await page.call('Target.attachToTarget', {'targetId': tid, 'flatten': True}))['result']['sessionId']
        await page.call('Runtime.enable', session=page.sid)
        await page.call('Page.enable', session=page.sid)
        await page.call('Network.enable', session=page.sid)
        await page.call('Network.clearBrowserCache', session=page.sid)
        await page.call('Network.setCacheDisabled', {'cacheDisabled': True}, session=page.sid)
        try:
            await page.load(1500, 950, 'light')

            # --- the page loads and computes --------------------------------
            check('no script errors on load', page.errors, [])
            check('μ = 0 and σ = 1 give a mean of 1.6487',
                  await page.ev("['res-mu','res-sigma','res-mean','res-median'].map(id => document.getElementById(id).textContent).join(' ')"),
                  '0 1 1.6487 1')
            check('the chart draws the traces it always drew',
                  await page.ev("document.getElementById('chart').data.map(t => t.name)"), ORIGINAL_TRACES)

            # --- every slot has a topic, every link a target ------------------
            audit = await page.ev("KvotInfo.audit()")
            check('32 topics', audit['topics'], 32)
            check('no slot without a topic', audit['noTopic'], [])
            check('no "Read more" without a target in the page', audit['brokenMore'], [])
            check('every slot with a topic has its (i)', audit['buttons'], audit['slots'])
            check('the (i)s on screen at load', await page.ev(VISIBLE), AT_LOAD)
            await page.ev("document.getElementById('settings-details').open = true")
            await asyncio.sleep(0.3)
            check('opening the settings shows one (i) per setting',
                  [k for k in await page.ev(VISIBLE) if k.startswith('set:') and k not in ('set:dists', 'set:metrics')],
                  SETTINGS)
            check('every (i) is named after its topic',
                  await page.ev("[...document.querySelectorAll('.kvot-info-slot .info-btn')].every(b => /^About \\S/.test(b.getAttribute('aria-label')))"),
                  True)

            # --- the tooltips are gone -----------------------------------------
            check('the only titles left are on the dot of a distribution tab, which has no text',
                  await page.ev("[...document.querySelectorAll('#logn [title]')].map(e => e.className)"),
                  ['dist-swatch'])
            check('a metric field keeps its name without the tooltip',
                  await page.ev("document.querySelector('#metric1-content [data-field=\"mu\"]').getAttribute('aria-label')"),
                  'Mean of the natural logarithm')
            check('a setting is named by its label',
                  await page.ev("document.getElementById('chartMinPct').labels[0].textContent"), 'Chart minimum percentile')

            # --- where the (i)s stand ------------------------------------------
            geo = json.loads(await page.ev(GEOMETRY))
            rights = {geo['column'][k] for k in COLUMN}
            check('the (i)s of the bars, the right-hand panel and the headings line up', len(rights), 1)
            check('each setting’s (i) ends its label line, over the end of the field',
                  [k for k, (b, line, field) in geo['settings'].items()
                   if abs(b - line) > 1 or (field is not None and abs(line - field) > 1)], [])
            check('no horizontal scroll at 1500 px', geo['scrollX'], 0)
            tops = await page.ev("[" + ",".join(f"Math.round(document.querySelector('[data-info=\"{k}\"]').getBoundingClientRect().top)" for k in SETTINGS) + "]")
            check('the settings’ (i)s stand level, row by row',
                  [max(tops[:6]) - min(tops[:6]) <= 1, max(tops[6:]) - min(tops[6:]) <= 1], [True, True])

            # --- open, and close three ways ------------------------------------
            await page.ev(js_click_info('set:digits'))
            await asyncio.sleep(0.3)
            p = await page.ev(PANEL)
            check('an (i) opens its panel', p and p['title'], 'Significant digits')
            check('with the section as its kicker', p and p['kicker'], 'Display and chart settings')
            check('between the header and the footer',
                  p and [p['top'] == p['headerBottom'], p['bottom'] == p['footerTop'], p['right'] == p['width']],
                  [True, True, True])
            check('the (i) shows that it is open',
                  await page.ev("(() => { const b = document.querySelector('[data-info=\"set:digits\"]'); return b.classList.contains('is-open') + ':' + b.getAttribute('aria-expanded'); })()"),
                  'true:true')
            check('the current choice is marked', p and p['current'], ['5'])
            await page.ev("(() => { const s = document.getElementById('precisionSelect'); s.value = '7'; s.dispatchEvent(new Event('change', { bubbles: true })); })()")
            await asyncio.sleep(0.3)
            check('and follows the setting while the panel is open', (await page.ev(PANEL))['current'], ['7'])
            check('which the results follow too', await page.ev("document.getElementById('res-mean').textContent"), '1.648721')
            await page.ev("document.querySelector('.info-panel-close').click()")
            await asyncio.sleep(0.2)
            check('the × closes it', await page.ev("!document.querySelector('.info-panel')"), True)
            check('and gives the focus back to the (i)',
                  await page.ev("document.activeElement && document.activeElement.dataset.info"), 'set:digits')
            check('which no longer shows it open',
                  await page.ev("document.querySelector('[data-info=\"set:digits\"]').getAttribute('aria-expanded')"), 'false')

            await page.ev(js_click_info('metric:mu'))
            await asyncio.sleep(0.3)
            check('the panel heading’s (i) opens the topic of its metric', (await page.ev(PANEL))['title'], 'μ, the log-mean')
            try:
                for kind in ('keyDown', 'keyUp'):
                    await page.call('Input.dispatchKeyEvent', {'type': kind, 'key': 'Escape', 'code': 'Escape',
                                                               'windowsVirtualKeyCode': 27}, session=page.sid, timeout=10)
                await asyncio.sleep(0.2)
                check('Escape closes it', await page.ev("!document.querySelector('.info-panel')"), True)
            except asyncio.TimeoutError:
                print('skip  Escape: the browser stopped answering (headless Chrome 153 can hang on CDP keys)')
                await page.ev("KvotInfo.close()")

            await page.ev(js_click_info('sec:chart'))
            await asyncio.sleep(0.2)
            await page.ev(js_click_info('sec:chart'))
            await asyncio.sleep(0.2)
            check('the same (i) closes it', await page.ev("!document.querySelector('.info-panel')"), True)

            # --- "Read more" --------------------------------------------------
            await page.ev(js_click_info('metric:sigma'))
            await asyncio.sleep(0.3)
            check('a metric topic ends with a link to its equations',
                  await page.ev("document.querySelector('.info-panel-more').textContent"),
                  'Read more: Equations & formulas →')
            await page.ev("document.querySelector('.info-panel-more').click()")
            await asyncio.sleep(0.6)
            where = await page.ev("(() => ({ open: document.getElementById('equations-details').open,"
                                  " panel: !!document.querySelector('.info-panel'),"
                                  " top: Math.round(document.getElementById('eq-spread').getBoundingClientRect().top),"
                                  " header: Math.round(document.querySelector('header').getBoundingClientRect().bottom),"
                                  " footer: Math.round(document.querySelector('footer').getBoundingClientRect().top) }))()")
            check('which opens the equations', where['open'], True)
            check('closes the panel', where['panel'], False)
            # Near the end of the page it cannot reach the top; in view is what counts.
            check('and brings the Spread heading into view, clear of the header',
                  where['header'] < where['top'] < where['footer'] - 40, True)

            # --- topics that read the page -----------------------------------
            await page.ev("window.scrollTo(0, 0)")
            await page.ev(js_click_info('set:metrics'))
            await asyncio.sleep(0.3)
            check('with μ and σ chosen, the metrics topic says two are chosen',
                  await page.ev("[...document.querySelectorAll('.info-panel li')].at(-1).textContent"),
                  'Two metrics are chosen: deselect one to choose another.')
            await page.ev("document.querySelector('#tabs-header a[data-id=\"sigma\"]').click()")
            await asyncio.sleep(0.4)
            check('and with μ alone, which metrics are not available and why',
                  (await page.ev("[...document.querySelectorAll('.info-panel li')].map(li => li.textContent)"))[-3:],
                  ['gm: gm = e^μ, the same number as μ', 'min/max: min/max fixes the distribution on its own',
                   'data: a data set is fitted to a distribution of its own'])
            await page.ev("KvotInfo.close()")

            # --- a greyed-out metric says why when clicked ----------------------
            await page.ev("document.querySelector('#tabs-header a[data-id=\"GM\"]').click()")
            await asyncio.sleep(0.2)
            check('clicking a greyed-out metric says why',
                  await page.ev("document.getElementById('metric-info').textContent"), '"gm" cannot be combined with "μ".')
            check('and changes nothing',
                  await page.ev("[...document.querySelectorAll('#tabs-header a.selected')].map(a => a.dataset.id)"), ['mu'])

            # --- the page as it was: a swap carries the distribution -----------
            await page.ev("document.querySelector('#tabs-header a[data-id=\"GSD\"]').click()")
            await asyncio.sleep(0.4)
            check('choosing gsd after σ = 1 offers e^σ',
                  await page.ev("document.querySelector('#metric2-content [data-field=\"GSD\"]').value"), str(2.718281828459045))
            check('and the result has not moved', await page.ev("document.getElementById('res-mean').textContent"), '1.648721')
            check('the panel heading’s (i) follows the metric',
                  await page.ev("(() => { const b = document.querySelector('#metric2-panel h4 .info-btn'); return b.dataset.info + ' | ' + b.getAttribute('aria-label'); })()"),
                  'metric:GSD | About Geometric standard deviation (gsd)')

            # --- data, and its fit method --------------------------------------
            await page.ev("['mu', 'GSD', 'data'].forEach(id => document.querySelector('#tabs-header a[data-id=\"' + id + '\"]').click())")
            await asyncio.sleep(0.4)
            await page.ev("(() => { const t = document.querySelector('#metric1-content [data-field=\"data\"]'); t.value = '2 3 4 6 9 13 20 31 48'; t.dispatchEvent(new Event('input', { bubbles: true })); })()")
            await asyncio.sleep(0.4)
            check('a data set is fitted as before',
                  await page.ev("document.getElementById('res-mu').textContent + ' ' + document.getElementById('res-sigma').textContent"),
                  '2.225879 1.021352')
            check('the data panel has its (i) and the fit method its own',
                  [k for k in await page.ev(VISIBLE) if k in ('metric:data', 'set:fitMethod')], ['metric:data', 'set:fitMethod'])
            await page.ev("document.querySelector('#metric1-content [data-info=\"set:fitMethod\"]').click()")
            await asyncio.sleep(0.3)
            p = await page.ev(PANEL)
            check('the fit method’s (i) works in a cloned panel', p and p['title'], 'Fit method')
            check('and marks MLE', p and p['current'], ['Maximum likelihood (MLE)'])
            await page.ev("(() => { const s = document.querySelector('#metric1-content [data-field=\"data_method\"]'); s.value = 'MOM'; s.dispatchEvent(new Event('input', { bubbles: true })); })()")
            await asyncio.sleep(0.4)
            check('then MOM, once chosen', (await page.ev(PANEL))['current'], ['Method of moments (MOM)'])
            check('and the mean of the fit is that of the data (136/9)',
                  await page.ev("document.getElementById('res-mean').textContent"), '15.11111')
            await page.ev("KvotInfo.close()")

            # --- a second distribution: the comparison and its (i) -------------
            await page.ev("document.getElementById('dist-add').click()")
            await asyncio.sleep(0.5)
            check('a second distribution brings the comparison with its (i)',
                  'sec:compare' in await page.ev(VISIBLE), True)
            await page.ev(js_click_info('set:dists'))
            await asyncio.sleep(0.3)
            check('the Distributions topic counts them',
                  await page.ev("document.querySelector('.info-facts dd').textContent"), '2 of 8')
            await page.ev("document.querySelector('#dist-tabs .dist-swatch').click()")
            await asyncio.sleep(0.4)
            check('and follows a distribution hidden in the chart',
                  await page.ev("[...document.querySelectorAll('.info-facts dd')][2].textContent"), 'A')
            await page.ev("KvotInfo.close()")
            check('no script errors during the session', page.errors, [])

            # --- the look, light and dark, wide and narrow -------------------
            for width, height, theme, key in ((1500, 950, 'light', 'set:metrics'), (1500, 950, 'dark', 'metric:mu'),
                                              (420, 900, 'light', 'sec:results'), (420, 900, 'dark', 'set:curves')):
                await page.load(width, height, theme)
                check(f'{width} px, {theme}: the theme is applied',
                      await page.ev("document.documentElement.getAttribute('data-theme')"), theme)
                await page.ev("document.getElementById('settings-details').open = true")
                await asyncio.sleep(0.3)
                geo = json.loads(await page.ev(GEOMETRY))
                check(f'{width} px, {theme}: the (i)s of the bars, panels and headings line up',
                      len({geo['column'][k] for k in COLUMN + ['sec:settings']}), 1)
                check(f'{width} px, {theme}: no horizontal scroll', geo['scrollX'], 0)
                if key.startswith('set:') and key not in ('set:metrics',):
                    await page.ev(f"document.querySelector('[data-info=\"{key}\"]').scrollIntoView({{ block: 'center' }})")
                await page.ev(js_click_info(key))
                await asyncio.sleep(0.4)
                p = await page.ev(PANEL)
                check(f'{width} px, {theme}: the panel fits between the header and the footer',
                      p and [p['top'] == p['headerBottom'], p['bottom'] == p['footerTop'], p['right'] == p['width']],
                      [True, True, True])
                await page.shot(f'{theme}-{width}.png')
            check('no script errors in the four layouts', page.errors, [])
        finally:
            await page.call('Target.closeTarget', {'targetId': tid})

    print(f'\n{checks} checks, {len(failures)} failed')
    if failures:
        print('\n'.join(f'  - {f}' for f in failures))
        sys.exit(1)


asyncio.run(main())
