"""rdc.html drawing its chains from ENSDF instead of ICRP Publication 107.

The Database menu over the chain offers ICRP 107, built into the page, and
the ENSDF releases the Chart of Nuclides offers (ensdf-sources.js): the ones
on this site, the ones opened in this browser and NNDC's archive. Checked
here, in a fresh profile:

  - the menu and what the page starts on: ICRP 107, its own chain, no chain
    settings, the bar between the header and what is laid out below it;
  - ENSDF 2026-09-01: the element list holds its radioactive states, the
    chain of U-238 is the one ensdf-core.js builds (234Th feeding 234mPa),
    nothing in it sits on anything else (nor in Kr-101's, where beta-delayed
    neutrons put members one mass number apart), the title and the header
    name the release;
  - the chain settings: leaving out members under a year makes 238U go
    straight to 234U "via" 234Th and 234mPa, branches under 1 % drop the
    cluster decays, the inventory and the time horizon survive both, the
    settings are kept;
  - the decay: the page's own solver against ensdf-core.js's CRAM on the
    same chain, in becquerels, in alpha energy and in moles;
  - the dose coefficients and the energies the records carry, the CSV's
    source line, the search taking 238U and a bare m (Am-242m is the
    141-year Am-242m1);
  - back to ICRP 107 with the inventory kept, and the choice remembered
    over a reload;
  - opening ENSDF text with Open ENSDF..., kept in the browser and offered by
    the menu, and Forget; the same by dropping a file on the page;
  - a release at NNDC: the dialog with the file to download, the menu
    staying on the database in use;
  - a phone: the bar in two lines, its menus at 16 px, nothing wider than
    the screen;
  - and that the page raised nothing.

Serve the repository and start headless Chrome (the recipe is in README.md),
by default on ports 8765 and 9222; SITE_HTTP_PORT and SITE_CDP_PORT choose
others. Exit status is 0 when every check passes.
"""
import asyncio, json, os, sys, time, urllib.request
import websockets

HTTP = int(os.environ.get('SITE_HTTP_PORT', '8765'))
CDP = int(os.environ.get('SITE_CDP_PORT', '9222'))
HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.normpath(os.path.join(HERE, '..', 'ensdf', 'fixture', 'ensdf.003'))

ERRORS = """window.__errors = [];
addEventListener('error', e => window.__errors.push(String(e.message)));
addEventListener('unhandledrejection', e => window.__errors.push('rejected: ' + e.reason));"""

# The circles of the chain on show, and whether any two touch.
CIRCLES = """JSON.stringify((() => {
  const ns = CY.nodes().filter(n => n.data('Z') !== 0);
  const ps = ns.map(n => [n.id(), n.position('x'), n.position('y')]);
  const touching = [];
  for (let i = 0; i < ps.length; i++) for (let j = i + 1; j < ps.length; j++)
    if (Math.hypot(ps[i][1] - ps[j][1], ps[i][2] - ps[j][2]) < 81) touching.push(ps[i][0] + '/' + ps[j][0]);
  return { ids: ps.map(p => p[0]), touching };
})())"""

# The page's solution at the end of the chart against CRAM on the same chain.
VERSUS_CRAM = """(async (quantity) => {
  document.getElementById('chartunit').value = quantity;
  updateLevel('IC'); runAndUpdateChart();
  await new Promise(r => setTimeout(r, 400));
  const C = KVOT_ENSDF_CORE, R = KVOT_RDC_ENSDF, ch = chainMade.chain, sys = C.decaySystem(ch);
  const n0 = new Float64Array(sys.members.length);
  sys.members.forEach((nd, i) => {
    if (nd.kind !== 'state' || !nd.st || !(nd.st.ts > 0)) return;
    const bq = CY.getElementById(R.nameOf(nd.z, nd.a, nd.k, nd.nuc)).data('IC') || 0;
    n0[i] = bq * nd.st.ts / Math.LN2;
  });
  const unit = document.getElementById('timeunit').value, t = +document.getElementById('timeinput').value;
  const scale = { year: R.YEAR, day: 86400, hour: 3600, minute: 60, second: 1 }[unit];
  const res = C.decayAt(sys, n0, [t * scale]);
  const last = {};
  CHARTDIALOG[0].data.forEach(tr => { last[tr.name] = tr.y[tr.y.length - 1]; });
  let worst = 0, at = '', compared = 0;
  sys.members.forEach((nd, i) => {
    if (nd.kind !== 'state' || !nd.st || nd.st.st || !(nd.st.ts > 0)) return;
    const name = R.nameOf(nd.z, nd.a, nd.k, nd.nuc), rec = CHAIN_RECORDS.get(name);
    if (res.A[0][i] < 1e-12) return;
    const want = quantity === 'Mole' ? res.N[0][i] / 6.02214076e23 : res.A[0][i] * (quantity === 'Bq' ? 1 : rec[quantity]);
    if (!(want > 0)) return;
    compared++;
    const rel = Math.abs(last[name] - want) / want;
    if (!(rel <= worst)) { worst = rel; at = name; }
  });
  return JSON.stringify({ compared, worst, at });
})"""

STATE = """JSON.stringify({
  db: DB.key, label: DB.label, loading: dbLoading, ensdf: !!DB.ensdf,
  title: document.title, sub: (document.querySelector('header .title a') || {}).textContent,
  status: document.getElementById('dbStatus').textContent,
  settings: !document.getElementById('chainSettings').hidden,
  menu: document.getElementById('dbSelect').value,
  forget: !document.getElementById('dbForget').hidden,
  selected: ($('#tree').jstree(true).get_selected(true)[0] || {}).text || null,
  banner: (document.querySelector('.failure-banner:not([hidden]) .failure-banner-text') || {}).textContent || '',
  userError: document.getElementById('rdc-status').hidden ? '' : document.getElementById('rdc-status').textContent
})"""


async def main():
    version = json.load(urllib.request.urlopen('http://127.0.0.1:%d/json/version' % CDP))
    async with websockets.connect(version['webSocketDebuggerUrl'], max_size=200 * 1024 * 1024) as bws:
        counter = [0]
        events = []

        async def cmd(method, params=None, session=None):
            counter[0] += 1
            mid = counter[0]
            message = {'id': mid, 'method': method, 'params': params or {}}
            if session:
                message['sessionId'] = session
            await bws.send(json.dumps(message))
            while True:
                reply = json.loads(await bws.recv())
                if reply.get('id') == mid:
                    if 'error' in reply:
                        raise AssertionError('%s: %s' % (method, reply['error']))
                    return reply
                if 'method' in reply:
                    events.append(reply)

        async def ev(expression, session):
            reply = await cmd('Runtime.evaluate',
                              {'expression': expression, 'awaitPromise': True,
                               'returnByValue': True, 'timeout': 60000}, session)
            result = reply.get('result', {})
            if 'exceptionDetails' in result:
                raise AssertionError('page threw: ' + json.dumps(result['exceptionDetails'])[:400])
            return result.get('result', {}).get('value')

        async def settle(expression, session, tries=120, pause=0.25):
            got = None
            for _ in range(tries):
                try:
                    got = await ev(expression, session)
                except AssertionError:
                    got = None
                if got:
                    return got
                await asyncio.sleep(pause)
            return got

        async def state(session):
            return json.loads(await ev(STATE, session))

        async def pick(session, value):
            await ev("(() => { const s = document.getElementById('dbSelect'); s.value = %s; "
                     "s.dispatchEvent(new Event('change')); return 1; })()" % json.dumps(value), session)

        async def choose(session, select, value):
            await ev("(() => { const s = document.getElementById(%s); s.value = %s; "
                     "s.dispatchEvent(new Event('change')); return 1; })()" % (json.dumps(select), json.dumps(value)), session)

        failures = []
        passed = [0]

        def check(condition, message):
            if condition:
                passed[0] += 1
            else:
                failures.append(message)

        async def open_page(width=1400, height=900, mobile=False):
            target = (await cmd('Target.createTarget', {'url': 'about:blank'}))['result']['targetId']
            session = (await cmd('Target.attachToTarget', {'targetId': target, 'flatten': True}))['result']['sessionId']
            for method in ('Runtime.enable', 'Page.enable', 'Network.enable', 'DOM.enable'):
                await cmd(method, {}, session)
            await cmd('Network.setCacheDisabled', {'cacheDisabled': True}, session)
            await cmd('Page.addScriptToEvaluateOnNewDocument', {'source': ERRORS}, session)
            await cmd('Emulation.setDeviceMetricsOverride',
                      {'width': width, 'height': height, 'deviceScaleFactor': 2 if mobile else 1, 'mobile': mobile}, session)
            if mobile:
                await cmd('Emulation.setTouchEmulationEnabled', {'enabled': True, 'maxTouchPoints': 5}, session)
            await cmd('Page.navigate', {'url': 'http://127.0.0.1:%d/rdc.html?n=%d' % (HTTP, int(time.time() * 1000))}, session)
            return target, session

        target, session = await open_page()
        try:
            # A fresh start: no database chosen, none kept in the browser.
            await settle("typeof CY !== 'undefined' && CY.nodes().length > 5", session)
            await ev("""(async () => {
              localStorage.removeItem('kvot.rdc.db'); localStorage.removeItem('kvot.rdc.chain');
              await new Promise(r => { const q = indexedDB.deleteDatabase('kvot-ensdf'); q.onsuccess = q.onerror = q.onblocked = r; });
              return 1; })()""", session)
            await ev("window.__reloaded = true; 1", session)
            await cmd('Page.reload', {'ignoreCache': True}, session)
            await settle("!window.__reloaded && typeof CY !== 'undefined' && CY.nodes().length > 5 && DBS.ready && "
                         "!!document.querySelector('#dbSelect optgroup[label^=\"ENSDF at NNDC\"]')", session)

            # ── ICRP 107, as the page starts ─────────────────────────────────
            s = await state(session)
            check(s['db'] == 'icrp' and not s['ensdf'] and not s['loading'], 'the page should start on ICRP 107, got %r' % (s,))
            check(s['sub'] == 'ICRP Publication 107' and 'ICRP Publication 107' in s['title'],
                  'the header and the title should name ICRP 107, got %r / %r' % (s['sub'], s['title']))
            check(not s['settings'], 'ICRP 107 has no chain settings to show')
            check(s['status'] == 'ICRP Publication 107 · 1,252 radionuclides', 'the status line, got %r' % (s['status'],))
            icrp_chain = json.loads(await ev(CIRCLES, session))
            check(len(icrp_chain['ids']) == 21 and 'Pa-234m' in icrp_chain['ids'],
                  "ICRP 107's U-238 chain has 21 members, got %r" % (icrp_chain['ids'],))
            menu = json.loads(await ev("""JSON.stringify([...document.querySelectorAll('#dbSelect optgroup')].map(g =>
              [g.label, [...g.children].map(o => o.value)]))""", session))
            groups = dict(menu)
            check([g for g, _ in menu] == ['Built into the page', 'ENSDF on this site', 'ENSDF at NNDC: download, then open'],
                  'the menu groups, in order, got %r' % ([g for g, _ in menu],))
            check(groups.get('Built into the page') == ['icrp'], 'ICRP 107 is the one database built in')
            check('b:260901' in groups.get('ENSDF on this site', []), 'the release on this site is offered')
            nndc = groups.get('ENSDF at NNDC: download, then open', [])
            check(len(nndc) >= 100 and 'n:0403' in nndc and 'n:260901' not in nndc,
                  'NNDC\'s archive back to 2004, less the release on this site: %d entries' % len(nndc))
            boxes = json.loads(await ev("""JSON.stringify(['header', '#databar', '#cy', 'nav'].map(q => {
              const b = document.querySelector(q).getBoundingClientRect(); return [b.top, b.bottom]; }))""", session))
            check(abs(boxes[1][0] - boxes[0][1]) < 1 and abs(boxes[2][0] - boxes[1][1]) < 1.5 and abs(boxes[3][0] - boxes[1][1]) < 1.5,
                  'the bar should sit under the header, the graph and the list under the bar: %r' % (boxes,))

            # ── ENSDF 2026-09-01 ─────────────────────────────────────────────
            await pick(session, 'b:260901')
            await settle("DB.key === 'b:260901' && !!chainMade && CY.nodes().length > 5", session)
            s = await state(session)
            size = await ev('DB.ensdf.states.size', session)
            check(s['ensdf'] and s['sub'] == 'ENSDF 2026-09-01' and 'ENSDF 2026-09-01' in s['title'],
                  'the header and the title should name the release, got %r / %r' % (s['sub'], s['title']))
            check(s['status'] == 'ENSDF 2026-09-01 · %s radioactive states' % format(size, ','), 'the status line, got %r' % (s['status'],))
            check(s['settings'] and s['selected'] == 'U-238', 'U-238 stays, with the chain settings shown: %r' % (s,))
            tree = json.loads(await ev("""JSON.stringify((() => {
              const t = $('#tree').jstree(true), kids = (el) => t.get_node(t.get_json('#', {flat: true}).find(n => n.text === el).id).children.map(id => t.get_node(id).text);
              return { u: kids('Uranium'), h: kids('Hydrogen'), elements: t.get_node('#').children.length };
            })())""", session))
            check(tree['elements'] == 118, 'every element is in the list, got %r' % (tree['elements'],))
            check('U-238' in tree['u'] and 'U-238m' in tree['u'] and 'U-235m1' in tree['u'] and 'U-235m2' in tree['u'],
                  "Uranium lists ENSDF's states, isomers too, as m1, m2 where there are two: %r" % (tree['u'][:40],))
            check('H-3' in tree['h'] and 'H-1' not in tree['h'] and 'H-2' not in tree['h'],
                  'only radioactive states are listed: Hydrogen has %r' % (tree['h'],))
            same = json.loads(await ev("""JSON.stringify((() => {
              const C = KVOT_ENSDF_CORE, R = KVOT_RDC_ENSDF, at = DB.ensdf.states.get('U-238');
              const ch = C.buildChain(DB.ensdf.idx, at.z, at.a, at.k, { minIsomerS: 1 });
              const want = ch.nodes.filter(n => n.kind !== 'fission').map(n => R.nameOf(n.z, n.a, n.k, n.nuc)).sort();
              const got = CY.nodes().filter(n => n.data('Z') !== 0).map(n => n.id()).sort();
              const e = (a, b) => CY.edges().filter(x => x.data('source') === a && x.data('target') === b).map(x => x.data('br'))[0] || null;
              return { same: JSON.stringify(want) === JSON.stringify(got), n: got.length, toM: e('Th-234', 'Pa-234m'), toG: e('Th-234', 'Pa-234'),
                       m: CHAIN_RECORDS.get('Pa-234m').Progenies.map(p => [p.name, +p.br.toFixed(4)]) };
            })())""", session))
            check(same['same'], 'the chain drawn is the one ensdf-core.js builds')
            check(same['toM'] == '100%' and same['toG'] == '1.5×10⁻¹%',
                  '234Th feeds 234mPa by 99.85 %% and 234Pa by 0.15 %%, written as the page writes shares: %r / %r' % (same['toM'], same['toG']))
            check(same['m'] == [['Pa-234', 0.0016], ['U-234', 0.9984]], "234mPa's branches, got %r" % (same['m'],))
            circles = json.loads(await ev(CIRCLES, session))
            check(not circles['touching'], 'no two circles of the U-238 chain touch: %r' % (circles['touching'][:5],))
            records = json.loads(await ev("""JSON.stringify(['U-238', 'Pa-234m', 'Po-214', 'Bi-209', 'Rn-222'].map(n => {
              const r = CHAIN_RECORDS.get(n); return [n, r.Halflife, r.DCC_ing, r.DCC_ext, +r.Alpha_energy.toFixed(4), r.icrp || null]; }))""", session))
            by = {r[0]: r for r in records}
            check(by['U-238'][1] == '4.468 By' and by['Po-214'][1] == '163.46 µs' and by['Bi-209'][1] == '2.01×10<sup>19</sup> y',
                  'half-lives in the words of the ICRP 107 file, got %r' % ([r[1] for r in records],))
            check(by['U-238'][2] == 4.5e-8 and by['U-238'][3] == 9.2e-22 and by['Pa-234m'][5] == 'Pa-234m',
                  'the dose coefficients come from the ICRP 107 record of the same state: %r' % (records,))
            check(by['Bi-209'][2] == 0 and by['Bi-209'][5] is None, 'a state ICRP 107 does not have has none: %r' % (by['Bi-209'],))
            check(abs(by['U-238'][4] - 4.2586) < 0.002 and abs(by['Rn-222'][4] - 5.59) < 0.01,
                  'alpha energies per decay from the ENSDF decay data sets: %r' % (records,))
            # A neutron-rich chain: members one mass number apart do not touch.
            await ev("selectExactTreeNode('Kr-101', {userInitiated: true}); 1", session)
            await settle("CY.nodes().length > 30", session)
            kr = json.loads(await ev(CIRCLES, session))
            check(len(kr['ids']) > 30 and not kr['touching'], "Kr-101's %d members stand apart: %r" % (len(kr['ids']), kr['touching'][:5]))

            # ── The chain settings, with an inventory ────────────────────────
            await ev("""(async () => { selectExactTreeNode('U-238', {userInitiated: true});
              await new Promise(r => setTimeout(r, 500));
              CY.getElementById('U-238').data('IC', 5);
              document.getElementById('timeinput').value = '1e6'; document.getElementById('timeunit').value = 'year';
              updateLevel('IC'); runAndUpdateChart(); return 1; })()""", session)
            await asyncio.sleep(0.6)
            await choose(session, 'chainLife', '1y')
            await settle("CY.getElementById('Th-234').empty()", session)
            jump = json.loads(await ev("""JSON.stringify({
              ids: CY.nodes().filter(n => n.data('Z') !== 0).map(n => n.id()),
              u234: CY.edges().filter(x => x.data('source') === 'U-238' && x.data('target') === 'U-234').map(x => x.data('br'))[0] || null,
              ic: CY.getElementById('U-238').data('IC'), t: [document.getElementById('timeinput').value, document.getElementById('timeunit').value],
              open: !!$('#chartdialog').dialog('isOpen'), traces: (CHARTDIALOG[0].data || []).length,
              stored: localStorage.getItem('kvot.rdc.chain') })""", session))
            check('Th-234' not in jump['ids'] and 'Pa-234m' not in jump['ids'] and 'U-234' in jump['ids'],
                  'members under a year are left out: %r' % (jump['ids'],))
            check(bool(jump['u234']) and jump['u234'].endswith('via Th-234, Pa-234m'),
                  '238U goes straight to 234U, via what it jumped over: %r' % (jump['u234'],))
            check(jump['ic'] == 5 and jump['t'] == ['1e6', 'year'], 'the inventory and the time horizon are kept: %r' % ((jump['ic'], jump['t']),))
            check(jump['open'] and jump['traces'] >= 3, 'the chart shows the chain again: %r' % ((jump['open'], jump['traces']),))
            check(json.loads(jump['stored'] or '{}') == {'minBranch': '0', 'life': '1y'}, 'the settings are kept: %r' % (jump['stored'],))
            await choose(session, 'chainLife', 'iso')
            await choose(session, 'chainBranch', '1')
            await settle("CY.getElementById('Pb-212').empty() && !CY.getElementById('Th-234').empty()", session)
            few = json.loads(await ev(CIRCLES, session))
            check('Pb-212' not in few['ids'] and 'Hg-206' not in few['ids'] and not any(i.startswith('SF') for i in await ev("CY.nodes().map(n => n.id())", session)),
                  'branches under 1 %% are left out, the cluster decays and fission with them: %r' % (few['ids'],))
            await choose(session, 'chainBranch', '0')
            await settle("!CY.getElementById('Pb-212').empty()", session)

            # ── The decay, against CRAM ──────────────────────────────────────
            for quantity, tol in (('Bq', 1e-4), ('Alpha_energy', 1e-4), ('Mole', 1e-4)):
                r = json.loads(await ev('(%s)(%s)' % (VERSUS_CRAM, json.dumps(quantity)), session))
                check(r['compared'] >= 15 and r['worst'] < tol,
                      '%s after 10^6 y: the page against CRAM, worst %.2e at %s over %d members' % (quantity, r['worst'], r['at'], r['compared']))
            await ev("document.getElementById('chartunit').value = 'Bq'; updateLevel('IC'); runAndUpdateChart(); 1", session)

            # ── The CSV says where its numbers come from ─────────────────────
            csv = await ev("""(async () => {
              const keep = window.saveAs; let text = null;
              window.saveAs = (blob) => { blob.text().then(t => { text = t; }); };
              const b = CHARTDIALOG[0].querySelector('.modebar-btn[data-title="Download data as csv"]');
              if (b) b.click();
              for (let i = 0; i < 40 && text === null; i++) await new Promise(r => setTimeout(r, 50));
              window.saveAs = keep; return text; })()""", session) or ''
            check('Data source,ENSDF 2026-09-01' in csv and 'Chain settings,all branches,all but isomers < 1 s' in csv,
                  'the CSV names the release and the chain settings: %r' % (csv[:200],))

            # ── The search, as the Chart of Nuclides reads names ─────────────
            found = json.loads(await ev("""(async () => {
              const box = document.getElementById('search-input'), out = [];
              for (const q of ['238U', 'Am-242m', 'co60']) {
                box.focus(); box.value = q; box.dispatchEvent(new Event('input'));
                await new Promise(r => setTimeout(r, 400));
                out.push(($('#tree').jstree(true).get_selected(true)[0] || {}).text || null);
              }
              box.value = ''; box.blur(); return JSON.stringify(out); })()""", session))
            check(found == ['U-238', 'Am-242m1', 'Co-60'], 'the search takes 238U, a bare m and co60: %r' % (found,))

            # ── Back to ICRP 107, the inventory with it ──────────────────────
            await ev("""(async () => { selectExactTreeNode('U-238', {userInitiated: true});
              await new Promise(r => setTimeout(r, 400));
              CY.getElementById('U-238').data('IC', 7); updateLevel('IC'); runAndUpdateChart(); return 1; })()""", session)
            await pick(session, 'icrp')
            await settle("DB.key === 'icrp' && CY.nodes().length > 5 && CY.getElementById('U-238').data('IC') === 7", session)
            s = await state(session)
            back = json.loads(await ev(CIRCLES, session))
            check(s['db'] == 'icrp' and not s['settings'] and s['sub'] == 'ICRP Publication 107',
                  'ICRP 107 again, with no chain settings: %r' % (s,))
            check(sorted(back['ids']) == sorted(icrp_chain['ids']), "ICRP 107's own chain again: %r" % (back['ids'],))
            check(await ev("CY.getElementById('U-238').data('IC')", session) == 7, 'the inventory is kept across databases')
            check(await ev("CHAIN_RECORDS === null && getRn('U-238') === icrpRn('U-238')", session), 'the records are the ICRP 107 file again')

            # ── The choice is remembered ─────────────────────────────────────
            await pick(session, 'b:260901')
            await settle("DB.key === 'b:260901' && !!chainMade", session)
            await ev("window.__reloaded = true; 1", session)
            await cmd('Page.reload', {'ignoreCache': True}, session)
            ok = await settle("!window.__reloaded && typeof DB !== 'undefined' && DB.key === 'b:260901' && !dbLoading && CY.nodes().length > 5", session)
            s = await state(session)
            check(bool(ok) and s['selected'] == 'U-238' and s['settings'], 'the release chosen comes back after a reload: %r' % (s,))
            check(not s['userError'] and not s['banner'], 'and nothing is reported on the way: %r' % ((s['userError'], s['banner']),))

            # ── Open ENSDF..., then Forget ───────────────────────────────────
            await cmd('Page.setInterceptFileChooserDialog', {'enabled': True}, session)
            await ev("document.getElementById('dbOpen').click(); 1", session)
            doc = await cmd('DOM.getDocument', {'depth': 0}, session)
            node = await cmd('DOM.querySelector', {'nodeId': doc['result']['root']['nodeId'], 'selector': '#dbFile'}, session)
            await cmd('DOM.setFileInputFiles', {'files': [FIXTURE], 'nodeId': node['result']['nodeId']}, session)
            ok = await settle("DB.key.indexOf('s:') === 0 && DB.label === 'ensdf.003' && !dbLoading", session)
            s = await state(session)
            opened = json.loads(await ev("""(async () => {
              const t = $('#tree').jstree(true), flat = t.get_json('#', {flat: true});
              const kept = await KVOT_ENSDF_SOURCES.IDB.list();
              const g = document.querySelector('#dbSelect optgroup[label="ENSDF opened in this browser"]');
              return JSON.stringify({ states: [...DB.ensdf.states.keys()], kept: kept.map(k => k.label),
                group: g ? [...g.children].map(o => o.textContent) : null }); })()""", session))
            check(bool(ok) and s['forget'] and s['menu'] == s['db'], 'the file opens as the database, Forget shown: %r' % (s,))
            check('H-3' in opened['states'] and len(opened['states']) < 12, 'the file holds A = 3 alone: %r' % (opened['states'],))
            check(opened['kept'] == ['ensdf.003'] and opened['group'] and opened['group'][0].startswith('ensdf.003 (opened '),
                  'it is kept in this browser and offered by the menu: %r' % (opened,))
            await ev("selectExactTreeNode('H-3', {userInitiated: true}); 1", session)
            await settle("!CY.getElementById('He-3').empty()", session)
            h3 = json.loads(await ev("JSON.stringify(CY.nodes().map(n => n.id() + ':' + n.data('type')))", session))
            check(h3 == ['H-3:1', 'He-3:0'], 'the chain of H-3 from the file: %r' % (h3,))
            await ev("document.getElementById('dbForget').click(); 1", session)
            await settle("DB.key === 'b:260901' && !dbLoading", session)
            s = await state(session)
            left = await ev("KVOT_ENSDF_SOURCES.IDB.list().then(l => l.length)", session)
            check(s['db'] == 'b:260901' and not s['forget'] and left == 0
                  and not await ev("!!document.querySelector('#dbSelect optgroup[label=\"ENSDF opened in this browser\"]')", session),
                  'Forget lets it go and goes back to the release on this site: %r, %r kept' % (s, left))

            # ── A file dropped on the page opens the same way ────────────────
            await cmd('Input.dispatchDragEvent', {'type': 'dragEnter', 'x': 700, 'y': 400,
                                                  'data': {'items': [], 'files': [FIXTURE], 'dragOperationsMask': 1}}, session)
            over = await ev("document.body.classList.contains('rdc-dropping')", session)
            await cmd('Input.dispatchDragEvent', {'type': 'dragOver', 'x': 700, 'y': 400,
                                                  'data': {'items': [], 'files': [FIXTURE], 'dragOperationsMask': 1}}, session)
            await cmd('Input.dispatchDragEvent', {'type': 'drop', 'x': 700, 'y': 400,
                                                  'data': {'items': [], 'files': [FIXTURE], 'dragOperationsMask': 1}}, session)
            ok = await settle("DB.key.indexOf('s:') === 0 && !dbLoading", session)
            check(over and bool(ok) and not await ev("document.body.classList.contains('rdc-dropping')", session),
                  'a dropped file opens as the database, the drop zone shown while it is over the page')
            await ev("document.getElementById('dbForget').click(); 1", session)
            await settle("DB.key === 'b:260901' && !dbLoading", session)

            # ── A release at NNDC ────────────────────────────────────────────
            await pick(session, 'n:250101')
            await settle("document.getElementById('dbGet').open", session)
            get = json.loads(await ev("""JSON.stringify({ open: document.getElementById('dbGet').open,
              title: document.getElementById('dbGetTitle').textContent,
              links: [...document.querySelectorAll('#dbGetBody a')].map(a => a.href), db: DB.key,
              menu: document.getElementById('dbSelect').value })""", session))
            check(get['open'] and get['title'] == 'ENSDF 2025-01-01 from NNDC'
                  and get['links'] == ['https://www.nndc.bnl.gov/ensdfarchivals/distributions/dist25/ensdf_250101.zip'],
                  'the dialog names the file to download: %r' % (get,))
            check(get['db'] == 'b:260901' and get['menu'] == 'b:260901', 'and the page stays on the database in use: %r' % (get,))
            await ev("document.getElementById('dbGetClose').click(); 1", session)
            await pick(session, 'n:120307')
            await settle("document.getElementById('dbGet').open", session)
            parts = json.loads(await ev("JSON.stringify([...document.querySelectorAll('#dbGetBody a')].map(a => a.href.split('/').pop()))", session))
            check(len(parts) == 3 and all(p.startswith('ensdf_120307_') for p in parts), 'a release in three parts lists the three: %r' % (parts,))
            await ev("document.getElementById('dbGetClose').click(); 1", session)
            check(not await ev("document.getElementById('dbGet').open", session), 'Close closes it')

            errors = await ev('window.__errors', session)
            check(errors == [], 'the page should raise nothing, got %r' % (errors,))
        finally:
            await cmd('Target.closeTarget', {'targetId': target})

        # ── A phone ──────────────────────────────────────────────────────────
        target, session = await open_page(390, 664, mobile=True)
        try:
            await settle("typeof DB !== 'undefined' && DB.key === 'b:260901' && !dbLoading && CY.nodes().length > 5", session)
            await asyncio.sleep(0.6)
            phone = json.loads(await ev("""JSON.stringify((() => {
              const r = (q) => document.querySelector(q).getBoundingClientRect();
              return { bar: r('#databar').height, barBottom: r('#databar').bottom, cyTop: r('#cy').top, show: r('#treeShow').top,
                font: getComputedStyle(document.getElementById('dbSelect')).fontSize,
                font2: getComputedStyle(document.getElementById('chainLife')).fontSize,
                wide: document.documentElement.scrollWidth, w: innerWidth }; })())""", session))
            check(phone['bar'] <= 100, 'on a phone the bar takes two lines at most: %r px' % (phone['bar'],))
            check(phone['font'] == '16px' and phone['font2'] == '16px', 'its menus are 16 px, which iOS does not zoom into: %r' % (phone,))
            check(phone['wide'] <= phone['w'], 'nothing is wider than the screen: %r' % (phone,))
            check(abs(phone['cyTop'] - phone['barBottom']) < 1.5 and phone['show'] >= phone['barBottom'],
                  'the graph and the button for the list start below the bar: %r' % (phone,))
            errors = await ev('window.__errors', session)
            check(errors == [], 'the page should raise nothing on a phone, got %r' % (errors,))
            await ev("localStorage.removeItem('kvot.rdc.db'); localStorage.removeItem('kvot.rdc.chain'); 1", session)
        finally:
            await cmd('Target.closeTarget', {'targetId': target})

        if failures:
            print('%d of %d check(s) failed:' % (len(failures), len(failures) + passed[0]))
            for failure in failures:
                print('  - ' + failure)
            sys.exit(1)
        print('%d checks passed: rdc.html draws, decays and lays out its chains from ENSDF as well as from ICRP 107.' % passed[0])


asyncio.run(main())
