#!/usr/bin/env python3
"""Drives facsimile.html in headless Chrome and checks the charts survive use.

The three fixed charts are drawn once per redraw, but the fourth -- "Your own
selection" -- is emptied and rebuilt as series are ticked, as the time axis
changes and as the list is cleared. That is where a chart can be destroyed from
under Plotly, so every one of those paths is exercised here.

Each check reads back `<traces Plotly holds>:<traces Plotly has drawn>`. Both
halves matter: a graph div that has been emptied by hand still reports its
traces in `gd.data`, and draws none of them. Counting only the first half is
how the bug this test was written for went unnoticed.

Start the server and the browser first (as in ../rb/README.md):

    python3 -m http.server 8765 --bind 127.0.0.1
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \\
      --headless=new --remote-debugging-port=9222 --no-first-run \\
      --user-data-dir=/tmp/factest --disable-gpu about:blank

then

    python3 resources/tests/facsimile/test-ui.py

Exit status is 0 when every check passes.
"""
import asyncio
import json
import os
import sys
import urllib.request

import websockets

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'rb'))
from driver import open_page  # noqa: E402

URL = 'http://127.0.0.1:8765/facsimile.html'
# Long enough to exercise the whole machinery, short enough to answer at once.
TEND_YEARS = 0.01

failures = []
checks = 0


def check(label, got, want):
    global checks
    checks += 1
    ok = got == want
    print(f'{"ok  " if ok else "FAIL"}  {label}: {got!r}' + ('' if ok else f'  (expected {want!r})'))
    if not ok:
        failures.append(label)


async def settle(page, expr, want, tries=240, pause=0.25):
    """Polls until `expr` returns `want`; returns the last value seen."""
    value = None
    for _ in range(tries):
        value = await page.ev(expr)
        if value == want:
            return value
        await asyncio.sleep(pause)
    return value


def held_and_drawn(div):
    """`<traces held>:<traces drawn>` for a Plotly div, or 'none'."""
    return f"""(() => {{
      const d = document.getElementById('{div}');
      if (!d.data) return 'none';
      return d.data.length + ':' + d.querySelectorAll('.scatterlayer .trace').length;
    }})()"""


CUSTOM = held_and_drawn('chart4')
SERIES_NAMES = "(() => { const d = document.getElementById('chart4'); "\
               "return d.data ? d.data.map(t => t.name).join(',') : ''; })()"
# The same, with the unit taken off each trace name: which series are drawn,
# asked in a way that does not also assert how they are labelled.
SERIES_BARE = "(() => { const d = document.getElementById('chart4'); "\
              "return d.data ? d.data.map(t => t.name.replace(/ \\(.*\\)$/, '')).join(',') : ''; })()"
POINTS = "(() => { const d = document.getElementById('chart4'); "\
         "return d.data && d.data[0] ? d.data[0].x.length : -1; })()"


async def open_rb_tab(bws, settle_seconds=6):
    """Attaches to the HDF5 Browser tab the page opened, if it is there."""
    listing = json.load(urllib.request.urlopen('http://127.0.0.1:9222/json/list'))
    target = next((t for t in listing if 'rb.html' in t.get('url', '')), None)
    if not target:
        return None
    ws = await websockets.connect(target['webSocketDebuggerUrl'], max_size=64 * 1024 * 1024)
    counter = [0]

    async def send(method, params=None):
        counter[0] += 1
        await ws.send(json.dumps({'id': counter[0], 'method': method, 'params': params or {}}))
        while True:
            r = json.loads(await ws.recv())
            if r.get('id') == counter[0]:
                return r

    async def ev(expr, timeout=60):
        r = await asyncio.wait_for(send('Runtime.evaluate', {
            'expression': expr, 'returnByValue': True, 'awaitPromise': True}), timeout)
        res = r.get('result', {})
        if 'exceptionDetails' in res:
            return 'EXCEPTION: ' + str(res['exceptionDetails'].get('exception', {}).get('description', ''))[:300]
        return res.get('result', {}).get('value')

    await send('Runtime.enable')
    # The tree is rebuilt after the file mounts; give it a moment to settle.
    await asyncio.sleep(settle_seconds)
    return type('RB', (), {'ev': staticmethod(ev)})(), target['id']


async def drag(page, x0, y0, x1, y1, steps=6):
    """A real mouse drag, as the resize handle sees one."""
    await page.send('Input.dispatchMouseEvent', {
        'type': 'mousePressed', 'x': x0, 'y': y0, 'button': 'left', 'clickCount': 1})
    for i in range(1, steps + 1):
        await page.send('Input.dispatchMouseEvent', {
            'type': 'mouseMoved', 'button': 'left', 'buttons': 1,
            'x': x0 + (x1 - x0) * i / steps, 'y': y0 + (y1 - y0) * i / steps})
    await page.send('Input.dispatchMouseEvent', {
        'type': 'mouseReleased', 'x': x1, 'y': y1, 'button': 'left', 'clickCount': 1})
    await asyncio.sleep(0.25)


async def click(page, selector):
    # As a user gesture: a click is one, and the browser will not open a tab
    # for a page that has not had one -- which is what stops the HDF5 handoff.
    return await page.ev(f"(() => {{ const el = document.querySelector({json.dumps(selector)}); "
                         f"if (!el) return 'missing'; el.click(); return 'clicked'; }})()",
                         user_gesture=True)


async def set_control(page, selector, value, event='change'):
    return await page.ev(f"""(() => {{
      const el = document.querySelector({json.dumps(selector)});
      if (!el) return 'missing';
      el.value = {json.dumps(value)};
      el.dispatchEvent(new Event({json.dumps(event)}, {{ bubbles: true }}));
      return el.value;
    }})()""")


async def tick(page, index):
    """Ticks the index-th series checkbox as a click on it would."""
    return await page.ev(f"""(() => {{
      const el = document.querySelectorAll('#facSeries input[type=checkbox]')[{index}];
      if (!el) return 'no checkbox {index}';
      el.checked = !el.checked;
      el.dispatchEvent(new Event('change', {{ bubbles: true }}));
      return el.value;
    }})()""")


async def main():
    ver = json.load(urllib.request.urlopen('http://127.0.0.1:9222/json/version'))
    async with websockets.connect(ver['webSocketDebuggerUrl'], max_size=64 * 1024 * 1024) as bws:
        tid, page = await open_page(bws, url=URL, settle=3)
        try:
            await page.send('Emulation.setDeviceMetricsOverride',
                            {'width': 1600, 'height': 1000, 'deviceScaleFactor': 1, 'mobile': False})
            check('the page boots', await settle(
                page, "document.getElementById('facStatus').textContent !== 'Loading…'", True), True)

            # Whatever a previous session left in localStorage -- including a
            # half-written draft, which the page restores rather than discard --
            # Reset puts it back on the built-in model and the 13g settings.
            # (Clearing the storage key would not do it: the page writes its
            # live state back on unload, so a removal never survives a reload.)
            await click(page, '[data-on-click="fac:resetModel"]')
            check('Reset gives a model that compiles', await settle(
                page, "document.getElementById('facStatus').textContent.slice(0, 15)", 'Model compiled:'),
                'Model compiled:')
            # Settled on, not read once, for the reason the note below gives:
            # the status line already said "Model compiled" before Reset was
            # clicked, so the wait above can return before Reset's own compile
            # has come back and the panel still shows the previous case.
            check('Reset restores the scenario', await settle(
                page, "document.querySelector('[data-setting=\"DOSERI\"]').value", '238.0'), '238.0')
            # Settled on rather than read once: the status line already said
            # "Model compiled" before Reset was clicked, so waiting on it can
            # return before Reset's own compile has come back from the worker.
            check('and the scenario list says which one', await settle(
                page, "document.getElementById('facPreset').value", '13g'), '13g')

            # --- the settings and the model text are one thing ------------------
            # A setting has one copy, the line in the text; the panel is a view
            # of it. Both directions are checked, and so is the line itself --
            # the comment on it has to survive being written through.
            # Each of these waits on the thing it is checking. The status line
            # cannot be waited on here: it already says "Model compiled" from
            # the compile before, so a wait for that text returns at once and
            # the check reads the panel as it was.
            await set_control(page, '[data-setting="DOSERI"]', '99.5')
            check('a setting typed in the panel reaches the text', await settle(page,
                r"/^DOSERI\s*=\s*99\.5\s+# Initial dose rate/m"
                ".test(document.getElementById('facModelText').value)", True), True)
            check('and the compiled setting follows it', await settle(page,
                "document.querySelector('[data-setting=\"DOSERI\"]').title",
                'DOSERI = 99.5'), 'DOSERI = 99.5')
            check('and the scenario is no longer a preset', await settle(page,
                "document.getElementById('facPreset').value", ''), '')

            # The other way: the text is edited, the panel follows.
            await page.ev(
                "(() => { const ta = document.getElementById('facModelText');"
                r" ta.value = ta.value.replace(/^STEELAREA(\s*=\s*)[^#]*/m, 'STEELAREA$142    ');"
                " ta.dispatchEvent(new Event('input', { bubbles: true })); })()")
            await asyncio.sleep(1.6)
            check('a setting typed in the text reaches the panel', await page.ev(
                "document.querySelector('[data-setting=\"STEELAREA\"]').value"), '42')

            # A scenario writes itself into the text, and is then recognised in it.
            await set_control(page, '#facPreset', '16a')
            check('choosing a scenario writes it into the text', await settle(page,
                r"/^PRESSI\s*=\s*0\.01\s+# Initial gas pressure/m"
                ".test(document.getElementById('facModelText').value)", True), True)
            check('and the panel shows it', await settle(page,
                "document.querySelector('[data-setting=\"PRESSI\"]').value", '0.01'), '0.01')
            check('and the scenario list stays on it', await settle(page,
                "document.getElementById('facPreset').value", '16a'), '16a')
            check('and the settings it does not name are left alone', await page.ev(
                "document.querySelector('[data-setting=\"TEND\"]').value"), '500')

            # Back to where the rest of the checks expect to start.
            await click(page, '[data-on-click="fac:resetModel"]')
            check('Reset comes back to the scenario it started on', await settle(page,
                "document.getElementById('facPreset').value", '13g'), '13g')
            check('and to the text it started with', await page.ev(
                "document.getElementById('facModelText').value === FACSIMILE_DEFAULT_MODEL"), True)

            await set_control(page, '[data-setting="TEND"]', str(TEND_YEARS))
            await settle(page, "document.querySelector('[data-setting=\"TEND\"]').title",
                         f'TEND = {TEND_YEARS}')

            # Nothing has been solved yet: ticking must say so rather than throw.
            await tick(page, 0)
            await asyncio.sleep(0.3)
            check('ticking before a run shows the placeholder', await page.ev(
                "!document.getElementById('chart4Empty').hidden"), True)
            await tick(page, 0)

            await click(page, '#facRun')
            check('the run finishes', await settle(
                page, "document.getElementById('facStatus').textContent.slice(0, 4)", 'Done'), 'Done')

            check('the series list is populated',
                  await page.ev("document.querySelectorAll('#facSeries input').length") > 50, True)

            check('every solver is offered', await page.ev(
                "[...document.getElementById('facMethod').options].map(o => o.value).join(',')"),
                'ndf,bdf,'
                'julia_fbdf,julia_qndf,julia_qbdf,julia_kencarp4,'
                'julia_radau5,julia_rodas5p,julia_trbdf2')
            # FBDF is the one that solves this model comfortably; the others
            # are covered by the package's own tests under
            # resources/tests/ode_julia/.
            await set_control(page, '#facMethod', 'julia_fbdf')
            await click(page, '#facRun')
            check('a Julia-port solver runs in the page', await settle(
                page, "document.getElementById('facStatus').textContent.slice(0, 4)",
                'Done', tries=240), 'Done')
            # Settled on, not read once: the status line is written before the
            # footer is, so waiting on "Done" can arrive between the two.
            check('and says which solver did it', await settle(
                page, "document.getElementById('facStats').textContent.startsWith('FBDF')",
                True), True)
            check('and it drew', await page.ev(
                "(() => { const d = document.getElementById('chart3');"
                " return d.querySelectorAll('.scatterlayer .trace').length; })()") > 0, True)
            await set_control(page, '#facMethod', 'ndf')

            # --- the settings follow the solver --------------------------------
            # Opened first: everything but Method, rtol and atol lives in the
            # folded half now, and a row inside a hidden container computes to
            # display:none whatever updateSolverOptions did with it. Whether
            # it starts folded is asserted further down, from a known stored
            # state; here it is only put into a known one.
            if await page.ev("document.getElementById('facSolverAdvanced').hidden"):
                await click(page, '#facSolverMore')
            check('the advanced settings can be opened', await page.ev(
                "document.getElementById('facSolverAdvanced').hidden"), False)
            # A knob that does nothing is worse than a missing one, because
            # nothing tells the reader which it is. Each solver family declares
            # what it reads beside the code that passes the settings on.
            shown = ("[...document.querySelectorAll('[data-solver-opt]')]"
                     ".filter(el => getComputedStyle(el).display !== 'none')"
                     ".map(el => el.dataset.solverOpt).join(' ')")
            builtin = ('rtol atol atolSpecies norm maxOrder hmax matrix jacobian '
                       'belowTolRun maxSteps autoAtol clamp nonNegative')
            check('the built-in NDF shows its own settings', await page.ev(shown), builtin)
            # BDF is the same integrator with every kappa set to zero, so it
            # reads the same settings. If these ever diverge, this says so.
            await set_control(page, '#facMethod', 'bdf')
            check('and BDF, being the same integrator, shows the same',
                  await page.ev(shown), builtin)

            await set_control(page, '#facMethod', 'julia_rodas5p')
            # Rosenbrock: no nonlinear iteration to give a tolerance to, and a
            # Jacobian that is part of the method rather than an optimisation,
            # so it is re-formed every step and has no age to set.
            check('a Rosenbrock method hides order, Newton and Jacobian age',
                  await page.ev(shown),
                  'rtol atol atolSpecies norm hmax matrix jacobian belowTolRun maxSteps autoAtol clamp nonNegative')
            check('and says which, rather than just hiding them', await page.ev(
                "document.getElementById('facSolverNote').textContent.split('.')[0]"),
                'Rodas5P does not read the maximum order, the minimum order, '
                'the Newton tolerance, how long a Jacobian is reused and '
                'smoothing the error estimate, so they are not shown')

            await set_control(page, '#facMethod', 'julia_fbdf')
            check('a variable-order method shows both order limits and the Newton tolerance',
                  await page.ev(shown),
                  'rtol atol atolSpecies norm maxOrder minOrder hmax matrix jacobian '
                  'kappa maxJacAge belowTolRun maxSteps autoAtol clamp nonNegative')

            await set_control(page, '#facMethod', 'julia_trbdf2')
            check('an ESDIRK adds error smoothing', await page.ev(shown),
                  'rtol atol atolSpecies norm hmax matrix jacobian kappa maxJacAge '
                  'belowTolRun maxSteps autoAtol smoothEst clamp nonNegative')

            # Radau measures its error against Hairer's own transformed
            # tolerances, in a norm of its own that this setting cannot reach.
            # Fixed at order 5 in three stages, so there is no order to cap
            # either -- it is the only method here that hides both.
            await set_control(page, '#facMethod', 'julia_radau5')
            check('Radau hides the error norm and the order it does not read',
                  await page.ev(shown),
                  'rtol atol atolSpecies hmax matrix jacobian kappa maxJacAge '
                  'belowTolRun maxSteps autoAtol smoothEst clamp nonNegative')
            # Hiding is by an attribute the stylesheet has to honour: an author
            # `display` beats the browser's own [hidden] { display: none }, and
            # both of these row types carry one. Checked while a solver that
            # hides the error norm is selected.
            check('hidden really means hidden', await page.ev(
                "getComputedStyle(document.querySelector('[data-solver-opt=\"norm\"]')).display"),
                'none')

            # --- units, and where a scenario comes from -------------------------
            # The unit is shown apart from the name so the filter box above
            # still matches what the reader typed.
            check('a series with a unit says so in the list', await page.ev("""
              (() => {
                const l = [...document.querySelectorAll('#facSeries label')]
                  .find(e => e.textContent.trim().startsWith('H2OTOTAL'));
                const u = l && l.querySelector('.fac-unit');
                return u ? u.textContent.trim() : (l ? 'no unit shown' : 'no such series');
              })()"""), 'g')
            # Found by value, not by what is shown: the list does not print the
            # `[state] ` tag any more -- the Species group says it instead.
            check('and a species falls back to the model\u2019s own unit', await page.ev("""
              (() => {
                const el = document.querySelector('#facSeries input[value="[state] H2O"]');
                const l = el && el.closest('label');
                const u = l && l.querySelector('.fac-unit');
                return u ? u.textContent.trim() : 'none';
              })()"""), 'mol/cm\u00b3')
            # The hover box: Plotly's default is near-white whatever the page
            # is, which put light text on a light box in the dark theme.
            check('the hover label is told the page\u2019s own colours', await page.ev(
                "(() => { const gd = document.getElementById('chart1');"
                " const h = gd && gd.layout && gd.layout.hoverlabel;"
                " return !!(h && h.bgcolor && h.font && h.font.color); })()"), True)

            # --- per-species absolute tolerances -------------------------------
            # The one setting here that is a little language rather than a
            # number, so it is the one that can be typed wrong. A bad line has
            # to be caught before the run, not swallowed by it.
            await set_control(page, '#facMethod', 'ndf')
            note = "document.getElementById('facSolverNote').textContent"
            bad = "document.getElementById('facAtolSpecies').classList.contains('bad')"

            await set_control(page, '#facAtolSpecies', 'H2O 1e-12\nOH = 1e-22')
            check('a readable list is accepted', await page.ev(bad), False)

            await set_control(page, '#facAtolSpecies', 'NOSUCHSPECIES 1e-12')
            check('a species the model does not have is caught', await page.ev(bad), True)
            check('and named, rather than just reddened',
                  'NOSUCHSPECIES' in (await page.ev(note)), True)

            await set_control(page, '#facAtolSpecies', 'H2O')
            check('a line that is not a name and a number is caught too',
                  await page.ev(bad), True)

            await set_control(page, '#facAtolSpecies', 'H2O -1')
            check('and so is a negative tolerance', await page.ev(bad), True)
            # Refused at the click, not left to fail somewhere in the solver.
            await click(page, '#facRun')
            check('and Run refuses it with the reason', await settle(
                page, "document.getElementById('facStatus').textContent"
                      ".startsWith('Per-species absolute tolerance')", True, tries=40), True)

            # A run that actually uses one, so the whole path is exercised: the
            # page parses, the worker resolves against its own compile, and the
            # solver is handed 63 tolerances instead of one.
            await set_control(page, '#facAtolSpecies', 'E 1e-26, HP 1e-26')
            check('the list clears', await page.ev(bad), False)
            # Waited for, not slept through: changing a solver setting schedules
            # a compile, and a compile that lands after the run finishes
            # overwrites "Done" with "Model compiled:" -- which is what this
            # check saw the first time it was written.
            await settle(page, "document.getElementById('facStatus').textContent.slice(0, 15)",
                         'Model compiled:', tries=40)
            await click(page, '#facRun')
            check('and a run with per-species tolerances finishes', await settle(
                page, "document.getElementById('facStatus').textContent.slice(0, 4)",
                'Done', tries=240), 'Done')
            await set_control(page, '#facAtolSpecies', '')
            await settle(page, "document.getElementById('facStatus').textContent.slice(0, 15)",
                         'Model compiled:', tries=40)

            # Non-negativity is accepted by both families and means different
            # things. Saying "yes" to one tick box without saying which would
            # be a small lie.
            await set_control(page, '#facMethod', 'julia_fbdf')
            check('and a port says how far it honours non-negativity', await page.ev(
                "document.getElementById('facSolverNote').textContent"
                ".includes('projecting each accepted step')"), True)

            await set_control(page, '#facMethod', 'ndf')

            # --- the reported bug: a second series, then the time axis --------
            first = await tick(page, 0)
            await asyncio.sleep(0.4)
            check('one series ticked draws one trace', await page.ev(CUSTOM), '1:1')

            await tick(page, 1)
            await asyncio.sleep(0.4)
            check('a second series draws two traces', await page.ev(CUSTOM), '2:2')

            await tick(page, 2)
            await asyncio.sleep(0.4)
            check('a third series draws three traces', await page.ev(CUSTOM), '3:3')

            await set_control(page, '#facXAxis', 'TIMY')
            await asyncio.sleep(0.6)
            check('changing the time axis keeps the three traces', await page.ev(CUSTOM), '3:3')
            check('the time axis is now years', await page.ev(
                "document.getElementById('chart4').layout.xaxis.title.text"), 'time (years)')

            # --- the lower end of a log time axis -----------------------------
            # Left to the data it starts at the first stored point, which on
            # this model is a fraction of a second, so most of the width goes
            # on the interval before anything has happened.
            check('the lower end is offered on a log axis', await page.ev(
                "document.getElementById('facXMinWrap').hidden"), False)
            check('and starts at 1e-4', await page.ev(
                "document.getElementById('facXMin').value"), '1e-4')
            check('named in the unit of the axis', await page.ev(
                "document.getElementById('facXMinUnit').textContent"), 'years')
            check('which follows the axis', await page.ev(
                "document.getElementById('chart4').layout.xaxis.range[0]"), -4.0)
            check('and the early points are left out, not just hidden', await page.ev(
                "document.getElementById('chart4').data[0].x[0] >= 1e-4"), True)

            # The axis is in years here and the run is a hundredth of one, so
            # a thousandth is inside the data and the end is asked for exactly.
            await set_control(page, '#facXMin', '1e-3')
            await asyncio.sleep(0.6)
            check('a lower end typed in moves the axis', await page.ev(
                "document.getElementById('chart4').layout.xaxis.range[0]"), -3.0)
            check('and the traces survive it', await page.ev(CUSTOM), '3:3')

            # Plotly writes the range it worked out back into the layout, so an
            # axis left to the data is not one with no range -- it is one whose
            # range reaches back to where the data does.
            await set_control(page, '#facXMin', '')
            await asyncio.sleep(0.6)
            check('emptying it gives the data back its say', await page.ev(
                "document.getElementById('chart4').data[0].x[0] < 1e-6"), True)
            check('which takes the axis back with it', await page.ev(
                "document.getElementById('chart4').layout.xaxis.range[0] < -6"), True)
            await set_control(page, '#facXMin', '1e-4')
            await asyncio.sleep(0.5)

            await set_control(page, '#facXAxis', 'TIMH-lin')
            await asyncio.sleep(0.6)
            check('a linear time axis keeps the traces', await page.ev(CUSTOM), '3:3')
            check('a linear time axis plots the t = 0 point too', await page.ev(POINTS) > 0, True)
            # An author `display` beats the browser's [hidden] { display: none },
            # so the attribute alone is not evidence that it went away.
            check('the lower end is put away on a linear axis', await page.ev(
                "getComputedStyle(document.getElementById('facXMinWrap')).display"), 'none')
            check('and the lower end is not applied to it', await page.ev(
                "document.getElementById('chart4').data[0].x[0]"), 0)

            await page.ev("""(() => { const el = document.getElementById('facCustomLog');
              el.checked = false; el.dispatchEvent(new Event('change', { bubbles: true })); })()""")
            await asyncio.sleep(0.5)
            check('the log-y toggle keeps the traces', await page.ev(CUSTOM), '3:3')
            check('the y axis is linear', await page.ev(
                "document.getElementById('chart4').layout.yaxis.type"), 'linear')

            # --- unticking, clearing, and coming back -------------------------
            await tick(page, 1)
            await asyncio.sleep(0.4)
            check('unticking one leaves two traces', await page.ev(CUSTOM), '2:2')

            await click(page, '[data-on-click="fac:clearSeries"]')
            await asyncio.sleep(0.4)
            check('clearing lets Plotly go of the div', await page.ev(CUSTOM), 'none')
            check('clearing shows the placeholder', await page.ev(
                "!document.getElementById('chart4Empty').hidden && document.getElementById('chart4').hidden"), True)

            await tick(page, 0)
            await asyncio.sleep(0.4)
            check('ticking again after a clear draws again', await page.ev(CUSTOM), '1:1')
            check('and draws the series that was ticked', await page.ev(SERIES_BARE), first)
            # And labels it with its unit, which is what the legend is for.
            # Read from the list rather than assumed: which series sits at
            # index 0 is the model's business, not this test's.
            unit = await page.ev(
                "(() => { const l = [...document.querySelectorAll('#facSeries label')]"
                f".find(e => e.querySelector('input').value === {json.dumps(first)});"
                " const u = l && l.querySelector('.fac-unit');"
                " return u ? u.textContent.trim() : ''; })()")
            check('and labels it with its unit', await page.ev(SERIES_NAMES),
                  f'{first} ({unit})' if unit else first)

            # --- the picker's shape ---------------------------------------------
            # Three named groups rather than one wall of a hundred and thirty
            # names, and what is ticked repeated as chips above, each of which
            # removes its own.
            check('the names are grouped by what they are', await page.ev(
                "[...document.querySelectorAll('#facSeries .fac-group h4')]"
                ".map(h => h.firstChild.textContent.trim()).join(',')"),
                'Outputs,Equations,Species')
            check('what is ticked is shown as a chip', await page.ev(
                "[...document.querySelectorAll('.fac-chip')].map(c => c.dataset.series).join(',')"),
                first)
            check('and the pill is marked as picked', await page.ev(
                "document.querySelectorAll('#facSeries .fac-item.on').length"), 1)
            # A chip removes its own series, which is the quickest way back out
            # of a selection made deep in a scrolling list.
            await click(page, '.fac-chip')
            await asyncio.sleep(0.4)
            check('clicking a chip unticks that series', await page.ev(
                "document.querySelectorAll('#facSeries .fac-item.on').length"), 0)
            check('and takes its trace with it', await page.ev(CUSTOM), 'none')
            check('and the chips go away with the last one', await page.ev(
                "document.getElementById('facSeriesChips').hidden"), True)
            await tick(page, 0)
            await asyncio.sleep(0.4)
            check('ticking again brings both back', await page.ev(
                "document.querySelectorAll('#facSeries .fac-item.on').length"
                " + ':' + document.querySelectorAll('.fac-chip').length"), '1:1')

            # --- the filter ----------------------------------------------------
            await set_control(page, '#facSeriesFilter', 'NH3', event='input')
            await asyncio.sleep(0.4)
            total = await page.ev("document.querySelectorAll('#facSeries label').length")
            shown = await page.ev("[...document.querySelectorAll('#facSeries label')]"
                                  ".filter((l) => l.offsetParent !== null).length")
            check('the filter hides the names that do not match', 0 < shown < total, True)
            check('the filter keeps the names that do match', await page.ev(
                "[...document.querySelectorAll('#facSeries label')]"
                ".filter((l) => l.offsetParent !== null).every((l) => l.textContent.includes('NH3'))"), True)
            check('the ticked series survives filtering', await page.ev(CUSTOM), '1:1')

            await set_control(page, '#facSeriesFilter', '', event='input')
            await asyncio.sleep(0.3)
            check('clearing the filter shows every name again', await page.ev(
                "[...document.querySelectorAll('#facSeries label')]"
                ".filter((l) => l.offsetParent !== null).length"), total)

            # --- the other three charts, the tabs, a second run ----------------
            for cid, label in (('chart1', 'temperature'), ('chart2', 'water'), ('chart3', 'species')):
                held = await page.ev(held_and_drawn(cid))
                n, drawn = (held.split(':') + ['0'])[:2] if held != 'none' else ('0', '0')
                check(f'the {label} chart draws every trace it holds', (held != 'none', n == drawn), (True, True))

            await click(page, '[data-tab="table"]')
            await asyncio.sleep(0.6)
            check('the table fills', await page.ev(
                "document.querySelectorAll('#facTable tbody tr').length") > 0, True)
            await click(page, '[data-tab="jacobian"]')
            await asyncio.sleep(0.5)
            check('the Jacobian is drawn', await page.ev(
                "document.getElementById('facJacCanvas').width") > 0, True)
            await click(page, '[data-tab="charts"]')
            await asyncio.sleep(0.8)
            check('returning to the charts keeps the custom plot', await page.ev(CUSTOM), '1:1')

            await click(page, '#facRun')
            await settle(page, "document.getElementById('facStatus').textContent.slice(0, 4)", 'Done')
            await asyncio.sleep(0.6)
            check('a second run keeps the custom plot', await page.ev(CUSTOM), '1:1')

            # --- handing the run to the HDF5 Browser ----------------------------
            # The status line only says this once the other tab has mounted the
            # file with h5wasm -- the real library -- and answered, so reading
            # it back is an end-to-end check of the writer and the handoff.
            await click(page, '#facToHdf5')
            handed = await settle(page, "document.getElementById('facStatus').textContent.includes("
                                        "'is open in the HDF5 Browser')", True, tries=240, pause=0.5)
            check('the run reaches the HDF5 Browser', handed, True)
            if handed:
                opened = await open_rb_tab(bws)
                if opened is None:
                    check('the HDF5 Browser tab is there', False, True)
                else:
                    rb, rb_tid = opened
                    try:
                        # Named for the case, and the case stopped being the
                        # preset the moment a setting was typed over.
                        check('it holds the file it was handed', await rb.ev(
                            "Object.keys(loadedFiles)[0] || ''"), 'canister_custom.h5')
                        tree = await rb.ev("document.getElementById('tree').textContent")
                        for name in ('Results', 'Species', 'Equations', 'Settings', 'Model', 'time'):
                            check(f'and shows /{name} in the tree', name in tree, True)
                        check('and reads the species back through h5wasm', await rb.ev("""(() => {
                          const f = loadedFiles[Object.keys(loadedFiles)[0]];
                          const d = f.get('/Species/H2');
                          return d && d.value ? d.value.length : -1;
                        })()""") > 0, True)
                        # A dataset each, and openable: this is the shape the
                        # browser can actually show, which attributes on the
                        # group were not.
                        check('with the case openable in the tree', await rb.ev("""(() => {
                          const f = loadedFiles[Object.keys(loadedFiles)[0]];
                          const d = f.get('/Settings/DOSERI');
                          return d && d.value ? String(d.value[0]) : 'missing';
                        })()"""), '238')
                        check('each saying what it is', await rb.ev("""(() => {
                          const f = loadedFiles[Object.keys(loadedFiles)[0]];
                          const a = f.get('/Constants/NA').attrs;
                          return [a.unit.value, a.description.value].join(' | ');
                        })()"""), '1/mol | Avogadro constant (1/mol)')
                    finally:
                        await bws.send(json.dumps({'id': 98, 'method': 'Target.closeTarget',
                                                   'params': {'targetId': rb_tid}}))

            # --- a long run: progress, and getting out of it --------------------
            # Made long on purpose: a maximum step of a ten-thousandth of a
            # year over five hundred of them is five million steps, where the
            # same case unconstrained is five thousand. That is the shape of
            # run the reader has to be able to watch and to get out of.
            await set_control(page, '[data-setting="TEND"]', '500')
            await settle(page, "document.querySelector('[data-setting=\"TEND\"]').title", 'TEND = 500')
            await set_control(page, '#facHmax', '1e-4')
            await click(page, '#facRun')
            running = await settle(page, "/^Running NDF:/.test("
                                         "document.getElementById('facStatus').textContent)", True, tries=60)
            check('a long run says it is running', running, True)
            await asyncio.sleep(4)
            status = await page.ev("document.getElementById('facStatus').textContent")
            check('and how far it has got, against what was asked',
                  ' of 500,' in status and ' steps,' in status, True)
            check('and the bar is shown', await page.ev(
                "!document.getElementById('facProgress').hidden"), True)
            check('and says it is working', await page.ev(
                "document.getElementById('facProgress').classList.contains('working')"), True)
            # Honest, not flattering: a log clock read nine tenths done here.
            filled = await page.ev(
                "parseFloat(document.getElementById('facProgress').firstElementChild.style.width) || 0")
            check('and the fill is the share of the run actually solved', 0 <= filled < 25, True)
            check('and the steps are climbing', await page.ev(
                "(document.getElementById('facStatus').textContent.match(/([\\d,]+) steps/) || [])[1]"
                ".replace(/,/g, '') > 1000"), True)

            await click(page, '#facStop')
            check('Stop ends it', await settle(
                page, "document.getElementById('facStatus').textContent", 'Stopped.', tries=40), 'Stopped.')
            check('and hands the page back', await settle(
                page, "document.getElementById('facRun').disabled", False), False)
            check('and puts the bar away', await page.ev(
                "document.getElementById('facProgress').hidden"), True)
            # The footer was set to "Running..." when the run began and nothing
            # else writes it on this path, so left alone it says so for good.
            check('and the footer stops saying the run is going on', await page.ev(
                "document.getElementById('facStats').textContent.includes('Running')"), False)

            await set_control(page, '#facHmax', '0')
            await set_control(page, '[data-setting="TEND"]', str(TEND_YEARS))
            await settle(page, "document.querySelector('[data-setting=\"TEND\"]').title",
                         f'TEND = {TEND_YEARS}')

            # --- the model editor -----------------------------------------------
            # Typing a new output at the end of the file, a character at a time,
            # through the browser's own input pipeline. The compiler objects to
            # the half-written line, and must do so without touching the caret:
            # a textarea replaces a selection with the next character typed.
            await click(page, '[data-tab="model"]')
            await asyncio.sleep(0.4)
            await page.ev("""(() => { const ta = document.getElementById('facModelText');
              ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length); })()""")
            await page.send('Input.insertText', {'text': '\nfoo'})
            await asyncio.sleep(1.6)   # past the editor's debounce
            check('a half-written line leaves the caret alone', await page.ev(
                "(() => { const ta = document.getElementById('facModelText'); "
                "return ta.selectionStart === ta.selectionEnd && ta.selectionEnd === ta.value.length; })()"), True)
            check('a half-written line is reported quietly', await page.ev(
                "document.getElementById('facModelInfo').textContent.includes('not finished yet')"), True)
            check('a half-written line does not redden the editor', await page.ev(
                "document.getElementById('facModelText').classList.contains('error')"), False)

            await page.send('Input.insertText', {'text': ' = TMP*2'})
            await asyncio.sleep(1.6)
            check('what was typed is still there', await page.ev(
                "document.getElementById('facModelText').value.trimEnd().endsWith('foo = TMP*2')"), True)
            check('and it compiles', await page.ev(
                "document.getElementById('facModelInfo').textContent.includes('outputs')"), True)

            # A new output is plottable once it has been solved for: the series
            # list offers what the last run produced, not what the text defines.
            await click(page, '#facRun')
            await settle(page, "document.getElementById('facStatus').textContent.slice(0, 4)", 'Done')
            await click(page, '[data-tab="charts"]')
            await asyncio.sleep(0.6)
            check('the new output reaches the series list after a run', await page.ev(
                "[...document.querySelectorAll('#facSeries input')].some((el) => el.value === 'foo')"), True)
            await page.ev("""(() => {
              const el = [...document.querySelectorAll('#facSeries input')].find((x) => x.value === 'foo');
              el.checked = true;
              el.dispatchEvent(new Event('change', { bubbles: true }));
            })()""")
            await asyncio.sleep(0.5)
            check('and it draws', await page.ev(CUSTOM), '2:2')
            check('as a trace of its own', 'foo' in (await page.ev(SERIES_NAMES)), True)
            await click(page, '[data-tab="model"]')
            await asyncio.sleep(0.4)

            # Left alone, an unfinished line becomes an error with a way to it.
            await page.ev("""(() => { const ta = document.getElementById('facModelText');
              ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length); })()""")
            await page.send('Input.insertText', {'text': '\nbar'})
            await asyncio.sleep(1.6)
            await page.ev("document.getElementById('facModelText').blur()")
            await asyncio.sleep(0.3)
            check('leaving the line turns the note into an error', await page.ev(
                "document.querySelector('#facModelInfo .err') !== null"), True)
            check('the error offers to go to the line', await page.ev(
                "!!document.querySelector('[data-on-click=\"fac:gotoError\"]')"), True)
            await click(page, '[data-on-click="fac:gotoError"]')
            await asyncio.sleep(0.3)
            check('going to the line puts a caret there, not a selection', await page.ev("""(() => {
              const ta = document.getElementById('facModelText');
              const line = ta.value.slice(0, ta.selectionStart).split('\\n').length;
              const total = ta.value.split('\\n').length;
              return ta.selectionStart === ta.selectionEnd && line === total;
            })()"""), True)

            # --- the panel: pinned buttons, collapsible sections, a drag ---------
            # On the charts, so that the drag can be seen to reach them.
            await click(page, '[data-tab="charts"]')
            await asyncio.sleep(0.6)
            check('Run is outside the part that scrolls', await page.ev(
                "!document.getElementById('facSideScroll').contains(document.getElementById('facRun'))"), True)
            # Every section opened first: which are open is remembered between
            # visits, and a panel with most of it folded away has nothing to
            # scroll -- which reads as a failure of the footer, not of the
            # state this test happens to have inherited.
            await page.ev("document.querySelectorAll('.fac-sec')"
                          ".forEach((d) => { d.open = true; })")
            await asyncio.sleep(0.3)
            before_top = await page.ev("document.getElementById('facRun').getBoundingClientRect().top")
            scrolled = await page.ev(
                "(() => { const el = document.getElementById('facSideScroll');"
                " el.scrollTop = el.scrollHeight; return el.scrollTop; })()")
            check('the panel has more in it than fits', scrolled > 0, True)
            check('and Run does not move when it is scrolled', await page.ev(
                "document.getElementById('facRun').getBoundingClientRect().top"), before_top)

            # Measured rather than asked: Chrome hides the contents of a closed
            # <details> with content-visibility, which leaves them with an
            # offsetParent and a stale geometry, so only the height of the
            # section itself says whether it is shut.
            # Opened first: which sections are open is remembered between
            # visits, so a previous run of this test may have left it shut.
            shape = json.loads(await page.ev(
                "(() => { const d = document.getElementById('sec-solver');"
                " d.open = true;"
                " const open = d.getBoundingClientRect().height;"
                " d.querySelector('summary').click();"
                " const shut = d.getBoundingClientRect().height;"
                " return JSON.stringify([open, shut, d.open]); })()"))
            check('a section closes when its heading is clicked', shape[2], False)
            check('and takes its contents with it', shape[0] > 200 and shape[1] < 60, True)
            check('and opens again', await page.ev(
                "(() => { const d = document.getElementById('sec-case');"
                " d.querySelector('summary').click(); d.querySelector('summary').click();"
                " return d.open; })()"), True)

            width_before = await page.ev("document.getElementById('facSide').getBoundingClientRect().width")
            grip = json.loads(await page.ev(
                "(() => { const r = document.getElementById('facResize').getBoundingClientRect();"
                " return JSON.stringify([r.left + r.width / 2, r.top + 240]); })()"))
            await drag(page, grip[0], grip[1], grip[0] + 120, grip[1])
            width_after = await page.ev("document.getElementById('facSide').getBoundingClientRect().width")
            check('the panel can be dragged wider', abs(width_after - width_before - 120) < 2, True)
            check('and the charts are re-measured to match', await page.ev(
                "(() => { const d = document.getElementById('chart4');"
                " return Math.abs(d._fullLayout.width - d.getBoundingClientRect().width) < 2; })()"), True)

            grip = json.loads(await page.ev(
                "(() => { const r = document.getElementById('facResize').getBoundingClientRect();"
                " return JSON.stringify([r.left + r.width / 2, r.top + 240]); })()"))
            await drag(page, grip[0], grip[1], grip[0] - 600, grip[1])
            check('and not narrower than its contents', await page.ev(
                "Math.round(document.getElementById('facSide').getBoundingClientRect().width)"), 260)

            # What it remembers: the width it was dragged to and the section
            # that was closed have to come back on the next visit.
            await drag(page, *json.loads(await page.ev(
                "(() => { const r = document.getElementById('facResize').getBoundingClientRect();"
                " return JSON.stringify([r.left + r.width / 2, r.top + 240,"
                " r.left + r.width / 2 + 180, r.top + 240]); })()")))
            kept = await page.ev("Math.round(document.getElementById('facSide').getBoundingClientRect().width)")
            await page.send('Page.navigate', {'url': URL})
            await asyncio.sleep(3)
            await settle(page, "document.getElementById('facStatus').textContent !== 'Loading…'", True)
            check('the width survives a reload', await page.ev(
                "Math.round(document.getElementById('facSide').getBoundingClientRect().width)"), kept)
            check('and so does the section that was closed', await page.ev(
                "document.getElementById('sec-solver').open"), False)
            check('double-clicking the handle puts the width back', await page.ev(
                "(() => { const h = document.getElementById('facResize');"
                " h.dispatchEvent(new MouseEvent('dblclick', { bubbles: true }));"
                " return Math.round(document.getElementById('facSide').getBoundingClientRect().width); })()"), 340)

            # --- the water model is a setting -----------------------------------
            # H2OPAIR 0 is the substitution the page defaults to; 1 is
            # FACSIMILE's own evaporation/condensation pair, which needs an
            # extra species and two more reactions. Both have to compile and
            # run, and choosing a scenario has to put it back to 0 -- that is
            # the model the published cases were run with.
            await click(page, '[data-on-click="fac:resetModel"]')
            await settle(page, "document.getElementById('facStatus').textContent.slice(0, 15)",
                         'Model compiled:', tries=60)
            check('the water model is a case setting', await page.ev(
                "document.querySelector('[data-setting=\"H2OPAIR\"]').value"), '0')
            base = await page.ev("document.getElementById('facStatus').textContent")
            await set_control(page, '[data-setting="H2OPAIR"]', '1')
            await settle(page, "document.getElementById('facStatus').textContent !== "
                               + json.dumps(base), True, tries=60)
            check('the pair compiles, with a species and two reactions more',
                  await page.ev("document.getElementById('facStatus').textContent"
                                ".match(/(\\d+) species, (\\d+) reactions/).slice(1).join(',')"),
                  '64,264')
            await click(page, '#facRun')
            check('and runs', await settle(
                page, "document.getElementById('facStatus').textContent.slice(0, 4)",
                'Done', tries=240), 'Done')
            await set_control(page, '#facPreset', '13g')
            await settle(page, "document.querySelector('[data-setting=\"H2OPAIR\"]').value",
                         '0', tries=60)
            check('and choosing a scenario puts it back', await page.ev(
                "document.querySelector('[data-setting=\"H2OPAIR\"]').value"), '0')

            # --- the advanced half of the Solver panel --------------------------
            # Method, rtol and atol are what a reader changes; the other
            # fifteen arrive folded. Seeded from another page of the same
            # origin, as the stored-solver check below is and for the same
            # reason: this page writes its own state back as it unloads.
            await page.send('Page.navigate', {'url': 'http://127.0.0.1:8765/'})
            await asyncio.sleep(1.5)
            await page.ev("""(() => {
              const kept = JSON.parse(localStorage.getItem('kvot-facsimile-v1'));
              delete (kept.sections || {})['sec-solver-advanced'];
              localStorage.setItem('kvot-facsimile-v1', JSON.stringify(kept));
            })()""")
            await page.send('Page.navigate', {'url': URL})
            await asyncio.sleep(3)
            await settle(page, "document.getElementById('facStatus').textContent !== 'Loading\u2026'", True)
            # The Solver section itself is left folded by the section checks
            # above, and everything inside a closed <details> is invisible --
            # which would make the visibility check below pass for the wrong
            # reason, and then fail once it was measured properly.
            await page.ev("document.getElementById('sec-solver').open = true")
            await asyncio.sleep(0.3)
            check('the advanced settings start folded away', await page.ev(
                "document.getElementById('facSolverAdvanced').hidden"), True)
            # checkVisibility, not getComputedStyle().display: `display` is not
            # inherited, so a row inside a display:none container still reports
            # its own value and every one of them would look visible here.
            check('leaving the three a reader changes', await page.ev(
                "[...document.querySelectorAll('[data-solver-opt]')]"
                ".filter(el => el.checkVisibility())"
                ".map(el => el.dataset.solverOpt).join(' ')"), 'rtol atol')
            check('behind a link that says what it opens', await page.ev(
                "document.getElementById('facSolverMore').textContent"), 'Advanced settings')
            await click(page, '#facSolverMore')
            check('which opens them', await page.ev(
                "document.getElementById('facSolverAdvanced').hidden"), False)
            check('and becomes the way back', await page.ev(
                "document.getElementById('facSolverMore').textContent"), 'Hide advanced settings')
            check('and says so to a screen reader too', await page.ev(
                "document.getElementById('facSolverMore').getAttribute('aria-expanded')"), 'true')
            await click(page, '#facSolverMore')
            check('and folds them again', await page.ev(
                "document.getElementById('facSolverAdvanced').hidden"), True)
            # Remembered between visits, like the sections it is stored with.
            await page.send('Page.navigate', {'url': URL})
            await asyncio.sleep(3)
            await settle(page, "document.getElementById('facStatus').textContent !== 'Loading\u2026'", True)
            check('and the choice survives a reload', await page.ev(
                "document.getElementById('facSolverAdvanced').hidden"), True)

            # --- where a scenario comes from -----------------------------------
            # Every preset says where its case is defined; a hand-typed case
            # says nothing rather than borrowing a citation. Left to the end
            # because choosing a preset rewrites the model text, which renames
            # the exported file and throws away the run the checks above want.
            #
            # Reset first: the editor was exercised earlier and a preset is
            # only recognised when every one of its settings could be written
            # back into the text. Without this the page stays on "custom" and
            # the reference is correctly empty -- which reads as a broken
            # feature and is not one.
            await click(page, '[data-on-click="fac:resetModel"]')
            await settle(page, "document.getElementById('facStatus').textContent.slice(0, 15)",
                         'Model compiled:', tries=60)
            await set_control(page, '#facPreset', '2b')
            await settle(page, "document.getElementById('facPresetDesc')"
                               ".textContent.slice(0, 3)", '2b:', tries=60)
            check('a preset says where its case is defined', await page.ev(
                "document.getElementById('facPresetRef').textContent"),
                'SKB TR-22-15, Table 3-1 (p 17), Case 2b. Results: section 3.2.2, p 22 '
                '(sensitivity to steel area and system volume).')
            check('and the line is shown', await page.ev(
                "document.getElementById('facPresetRef').hidden"), False)
            await set_control(page, '#facPreset', '13g')
            await settle(page, "document.getElementById('facPresetDesc')"
                               ".textContent.slice(0, 4)", '13g:', tries=60)
            check('a variant says it is not in the report', await page.ev(
                "document.getElementById('facPresetRef').textContent"
                ".startsWith('Not in SKB TR-22-15 Table 3-1.')"), True)

            # --- a stored text written against an older built-in model ----------
            # The page restores what was in the editor last time, which is right
            # until the built-in model changes underneath it: the stored copy
            # then wins for ever, and nothing done to the browser touches it,
            # because it is in localStorage and not the cache. A scenario that
            # wants a setting the old text has no line for cannot be applied,
            # which is how it is noticed -- "no line for H2OPAIR".
            #
            # Seeded as an older, unedited visit: a stamp that is not today's
            # build, textEdited false, and a setting of the reader's own.
            await page.send('Page.navigate', {'url': 'http://127.0.0.1:8765/'})
            await asyncio.sleep(1.5)
            # The seed is checked, not assumed: it is written into another
            # page's localStorage and read back by a third navigation, and a
            # seed that quietly did not take looks exactly like a migration
            # that quietly did not run.
            seeded = await page.ev(r"""(() => {
              const kept = JSON.parse(localStorage.getItem('kvot-facsimile-v1') || 'null');
              if (!kept || typeof kept.text !== 'string') return 'nothing stored';
              kept.text = kept.text
                .split('\n').filter(l => !/^H2OPAIR\s*=/.test(l)).join('\n')
                .replace(/^DOSERI(\s*=\s*)\S+/m, 'DOSERI$1123.0');
              kept.modelStamp = 'an-older-build';
              kept.textEdited = false;
              localStorage.setItem('kvot-facsimile-v1', JSON.stringify(kept));
              return (/^H2OPAIR/m.test(kept.text) ? 'H2OPAIR still there' : 'no H2OPAIR')
                + ', ' + ((kept.text.match(/^DOSERI\s*=\s*(\S+)/m) || [, 'no DOSERI line'])[1]);
            })()""")
            check('an older visit can be put in storage', seeded, 'no H2OPAIR, 123.0')
            await page.send('Page.navigate', {'url': URL})
            await asyncio.sleep(3)
            await settle(page, "document.getElementById('facStatus').textContent !== 'Loading\u2026'", True)
            check('an older stored text is brought forward to the built-in one',
                  await page.ev("/^H2OPAIR\\s*=/m.test("
                                "document.getElementById('facModelText').value)"), True)
            check('carrying the settings the reader had changed', await settle(
                page, "document.querySelector('[data-setting=\"DOSERI\"]').value", '123.0'), '123.0')
            check('and saying so rather than doing it silently', await page.ev(
                "document.getElementById('facStatus').textContent"
                ".includes('your settings were carried over')"), True)
            # Said once: the stamp has been rewritten, so the next visit is
            # an ordinary one.
            await page.send('Page.navigate', {'url': URL})
            await asyncio.sleep(3)
            await settle(page, "document.getElementById('facStatus').textContent !== 'Loading\u2026'", True)
            check('and only once', await page.ev(
                "document.getElementById('facStatus').textContent"
                ".includes('your settings were carried over')"), False)
            await click(page, '[data-on-click="fac:resetModel"]')
            await settle(page, "document.querySelector('[data-setting=\"DOSERI\"]').value",
                         '238.0', tries=60)

            # --- a stored solver that has since been removed -------------------
            # ode23s and LSODA were on the menu and are not any more, and a
            # reader who had one selected has it in localStorage. Assigning a
            # value no option carries leaves the select showing nothing, and
            # the run then asks the engine for a solver that is not there.
            #
            # Seeded from another page of the same origin on purpose: this page
            # writes its state back as it unloads, so anything written into
            # storage while it is open is overwritten on the way out.
            await page.send('Page.navigate', {'url': 'http://127.0.0.1:8765/'})
            await asyncio.sleep(1.5)
            seeded = await page.ev("""(() => {
              const raw = localStorage.getItem('kvot-facsimile-v1');
              if (!raw) return 'nothing stored';
              const kept = JSON.parse(raw);
              kept.solver = Object.assign({}, kept.solver, { method: 'ode23s' });
              localStorage.setItem('kvot-facsimile-v1', JSON.stringify(kept));
              return 'ode23s';
            })()""")
            check('a removed solver can be put in storage', seeded, 'ode23s')
            await page.send('Page.navigate', {'url': URL})
            await asyncio.sleep(3)
            await settle(page, "document.getElementById('facStatus').textContent !== 'Loading\u2026'", True)
            check('and the page falls back to the NDF rather than showing nothing',
                  await page.ev("document.getElementById('facMethod').value"), 'ndf')

            # The same path, one step gentler: a visit from before the built-in
            # solver was named for its formulas has 'ode15s' stored. It is the
            # same solver, so it must come back selected and not merely default
            # to something -- which is indistinguishable here, so the check is
            # that the value is the NDF rather than that nothing broke.
            await page.send('Page.navigate', {'url': 'http://127.0.0.1:8765/'})
            await asyncio.sleep(1.5)
            await page.ev("""(() => {
              const kept = JSON.parse(localStorage.getItem('kvot-facsimile-v1'));
              kept.solver = Object.assign({}, kept.solver, { method: 'ode15s' });
              localStorage.setItem('kvot-facsimile-v1', JSON.stringify(kept));
            })()""")
            await page.send('Page.navigate', {'url': URL})
            await asyncio.sleep(3)
            await settle(page, "document.getElementById('facStatus').textContent !== 'Loading\u2026'", True)
            check('and the old name for the built-in solver still selects it',
                  await page.ev("document.getElementById('facMethod').value"), 'ndf')
            # Reset first: the editor was exercised earlier by typing a
            # half-written output into the model, and that text is in storage
            # too. Reset also puts the method back, which is the point here --
            # it must not put back the one that was just taken off the menu.
            await click(page, '[data-on-click="fac:resetModel"]')
            await settle(page, "document.getElementById('facStatus').textContent.slice(0, 15)",
                         'Model compiled:')
            check('and Reset leaves a solver that exists',
                  await page.ev("document.getElementById('facMethod').value"), 'ndf')
            await set_control(page, '[data-setting="TEND"]', str(TEND_YEARS))
            await settle(page, "document.querySelector('[data-setting=\"TEND\"]').title",
                         f'TEND = {TEND_YEARS}')
            # Clicked once and then waited on: putting the click inside the
            # polled expression starts a fresh run on every poll.
            await click(page, '#facRun')
            check('and a run still starts', await settle(
                page, "document.getElementById('facStatus').textContent.slice(0, 4)",
                'Done', tries=120), 'Done')

            # --- the foot of the panel stays still ----------------------------
            # Run, Stop and Check Jacobian sit at the bottom of a flex column,
            # so anything below them that changes height moves them: a status
            # line of one line against four, and the progress bar appearing the
            # moment Run is pressed, walked the buttons about under the pointer.
            tops = []
            for text in ['Stopped.', 'x ' * 220,
                         'Model compiled: 64 species, 264 reactions. Ready to run.']:
                await page.ev("document.getElementById('facStatus').textContent = %s"
                              % json.dumps(text))
                await asyncio.sleep(0.25)
                tops.append(await page.ev(
                    "Math.round(document.getElementById('facRun').getBoundingClientRect().top)"))
            await page.ev("document.getElementById('facProgress').hidden = false")
            await asyncio.sleep(0.25)
            tops.append(await page.ev(
                "Math.round(document.getElementById('facRun').getBoundingClientRect().top)"))
            await page.ev("document.getElementById('facProgress').hidden = true")
            check(f'the Run button does not move with the status below it ({tops})',
                  len(set(tops)) == 1, True)
            await page.ev("document.getElementById('facStatus').textContent = %s"
                          % json.dumps('x ' * 220))
            await asyncio.sleep(0.25)
            check('and the status scrolls instead of growing', await page.ev(
                "(() => { const el = document.getElementById('facStatus');"
                " return el.scrollHeight > el.clientHeight; })()"), True)

            # --- the window does not scroll -----------------------------------
            # The page is one screen: a panel and a work area, both of which
            # scroll inside themselves. The hidden checkbox in a species cell
            # is absolutely placed, and with no positioned ancestor of its own
            # it took .content as its containing block, escaped every clip and
            # added the cell's static position to the page: a chart tab of
            # sixty species grew the window several hundred pixels of nothing.
            check('the window itself does not scroll', await page.ev(
                "(() => { const de = document.documentElement;"
                " return de.scrollHeight - de.clientHeight; })()"), 0)

            errors = [f'{kind}: {text}' for kind, text in page.logs if kind in ('error', 'exception')]
            check('no console errors', errors, [])
        finally:
            await bws.send(json.dumps({'id': 99, 'method': 'Target.closeTarget', 'params': {'targetId': tid}}))

    print(f'\n{checks - len(failures)} of {checks} checks passed')
    if failures:
        print('failed: ' + ', '.join(failures))
    return 1 if failures else 0


sys.exit(asyncio.run(main()))
