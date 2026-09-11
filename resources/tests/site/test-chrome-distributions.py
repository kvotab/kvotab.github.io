"""logn.html holds several distributions at once, and each has to stay its own.

Only the selected distribution has panels in the DOM, so every other one is
computed from a store of what was typed into it. Three things about that store
are easy to get wrong and silent when they are:

  - a distribution must come back exactly as it was left. Rebuilding its input
    from its own result looks harmless and turns a typed 50 into the 50 that
    comes back out of exp(ln(50));

  - swapping one metric for another passes through a moment where only one
    metric is selected and the distribution is undetermined. Treating that as
    "no result" throws away the μ and σ that the newly chosen metric's starting
    value is derived from, and it silently offers a template default instead;

  - one distribution that does not resolve must not take the others off the
    chart.

The chart with a single distribution is checked against the exact trace list it
had before there could be several, because that is the case every existing user
of the page is in.

Needs a static server on 127.0.0.1:8765 and Chrome on 127.0.0.1:9222.
"""
import asyncio
import json
import math
import sys
import time
import urllib.request

import websockets

PROBE = r"""(async () => {
  const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
  const out = {};
  const set = (slot, field, value) => {
    const el = document.querySelector(`#metric${slot}-content [data-field="${field}"]`);
    if (!el) throw new Error(`no ${field} in panel ${slot}`);
    el.value = value;
    el.dispatchEvent(new Event('input', { bubbles: true }));
  };
  const get = (slot, field) => {
    const el = document.querySelector(`#metric${slot}-content [data-field="${field}"]`);
    return el ? el.value : null;
  };
  const metric = label => [...document.querySelectorAll('#tabs-header a[data-id]')]
    .find(a => a.textContent.trim() === label).click();
  const chart = document.getElementById('chart');
  const traceNames = () => (chart.data || []).map(trace => trace.name);

  /* Before anything is touched: the chart is open and has already drawn.
     drawChart() refuses to run against a closed <details>, because it has no
     dimensions to size to, so opening by default and drawing at boot are two
     claims and not one. */
  out.boot = { chartOpen: document.getElementById('chart-details').open,
               traces: traceNames(),
               plotted: !!chart.querySelector('.plot-container'),
               sized: chart.layout && chart.layout.width === Math.round(chart.getBoundingClientRect().width) };

  document.getElementById('chart-details').open = true;
  document.getElementById('chart-details').dispatchEvent(new Event('toggle'));
  await wait(500);

  /* One distribution draws what it always drew, and names none of it. */
  out.singleTraces = traceNames();
  out.singleLegend = chart.layout.showlegend;
  out.singleHasComparison = getComputedStyle(document.getElementById('compare-details')).display !== 'none';

  /* The chart opens on the log scale. Unticking it must give the same
     distribution over the same percentiles on a linear axis, which is the
     same range exponentiated — the linear branch is no longer the default and
     would otherwise go uncovered. */
  const lnBox = document.getElementById('lnViewToggle');
  out.lnIsDefault = lnBox.checked;
  out.lnRange = chart.layout.xaxis.range.slice();
  out.lnTitle = chart.layout.xaxis.title.text;
  lnBox.checked = false;
  lnBox.dispatchEvent(new Event('change'));
  await wait(400);
  out.linearTraces = traceNames();
  out.linearRange = chart.layout.xaxis.range.slice();
  out.linearTitle = chart.layout.xaxis.title.text;
  lnBox.checked = true;
  lnBox.dispatchEvent(new Event('change'));
  await wait(400);

  /* A metric swap carries the distribution across rather than resetting. */
  set(1, 'mu', '1.5'); set(2, 'sigma', '0.7');
  await wait(150);
  metric('σ'); metric('gsd');
  await wait(200);
  out.swappedGsd = get(2, 'GSD');
  out.swappedGsdWanted = String(Math.exp(0.7));

  /* Back to μ and σ, then a second distribution with its own parameters. */
  metric('gsd'); metric('σ');
  await wait(200);
  set(1, 'mu', '1.5'); set(2, 'sigma', '0.7');
  await wait(150);
  document.getElementById('dist-add').click();
  await wait(250);
  out.copiedFromFirst = [get(1, 'mu'), get(2, 'sigma')];
  set(1, 'mu', '3'); set(2, 'sigma', '0.25');
  await wait(250);

  /* A third, on a different pair of metrics entirely. */
  document.getElementById('dist-add').click();
  await wait(250);
  metric('μ'); metric('σ'); metric('mean'); metric('gsd');
  await wait(250);
  set(1, 'mean', '50'); set(2, 'GSD', '3');
  await wait(300);

  out.chartTraces = traceNames();
  out.legendEntries = (chart.data || []).filter(trace => trace.showlegend).map(trace => trace.name);
  out.legend = chart.layout.showlegend;
  const table = document.getElementById('compare-table');
  out.compareHeaders = [...table.rows[0].cells].map(cell => cell.textContent);

  /* Each distribution comes back as it was left, verbatim. */
  const nameButtons = () => [...document.querySelectorAll('#dist-tabs button.dist-name')];
  nameButtons()[0].click();
  await wait(300);
  out.first = { metrics: [...document.querySelectorAll('#tabs-header a.selected')].map(a => a.textContent.trim()),
                values: [get(1, 'mu'), get(2, 'sigma')] };
  nameButtons()[0].click();
  await wait(300);
  out.second = { values: [get(1, 'mu'), get(2, 'sigma')] };
  nameButtons().at(-1).click();
  await wait(300);
  out.third = { metrics: [...document.querySelectorAll('#tabs-header a.selected')].map(a => a.textContent.trim()),
                values: [get(1, 'mean'), get(2, 'GSD')] };

  /* One that does not resolve must not take the others with it. */
  set(1, 'mean', '-5');
  await wait(300);
  out.whileInvalid = { drawn: (chart.data || []).filter(t => t.showlegend).map(t => t.name),
                       flagged: document.querySelectorAll('#dist-tabs .dist-tab.invalid').length,
                       message: document.getElementById('result-error').textContent };
  set(1, 'mean', '50');
  await wait(250);

  /* Hidden in the chart, still in the comparison. */
  [...document.querySelectorAll('#dist-tabs .dist-swatch')][1].click();
  await wait(250);
  out.hiddenTraces = traceNames();
  out.hiddenStillCompared = [...document.getElementById('compare-table').rows[0].cells].map(c => c.textContent);

  /* Data fits a distribution of its own, so it shares one with nothing: it is
     disabled while a metric is selected, every metric is disabled while it is,
     and neither silently displaces the other. What deselecting must not throw
     away is the pasted values — losing a data set to a mis-click would be
     worse than offering it again. */
  const panelFields = () => [...document.querySelectorAll('#metric-panels .metric-panel')]
    .map(panel => panel.style.display === 'none' ? '-'
      : [...panel.querySelectorAll('[data-field]')].map(el => el.dataset.field).join(','));
  const selected = () => [...document.querySelectorAll('#tabs-header a.selected')]
    .map(a => a.textContent.trim());
  const pill = label => [...document.querySelectorAll('#tabs-header a[data-id]')]
    .find(a => a.textContent.trim() === label);

  out.dataDisabledBesideMetrics = { selection: selected(),
                                    disabled: pill('data').classList.contains('disabled') };
  metric('data');                               // refused, and must change nothing
  await wait(300);
  out.dataRefused = selected();

  metric('mean'); metric('gsd');                // clear the way for it
  await wait(300);
  metric('data');
  await wait(300);
  out.dataAlone = { selected: selected(), panels: panelFields(),
                    metricsDisabled: ['μ', 'mean', 'gsd'].map(l => pill(l).classList.contains('disabled')) };
  const textarea = document.querySelector('#metric1-content [data-field="data"]');
  textarea.value = '2 3 4 6 9 13 20 31 48';
  textarea.dispatchEvent(new Event('input', { bubbles: true }));
  await wait(350);
  out.dataFit = { mu: document.getElementById('res-mu').textContent,
                  sigma: document.getElementById('res-sigma').textContent };
  metric('mean');                               // refused in turn
  await wait(300);
  out.metricRefusedBesideData = selected();
  metric('data');                               // deselect, then back
  await wait(250);
  metric('data');
  await wait(350);
  out.dataKeptItsValues = document.querySelector('#metric1-content [data-field="data"]').value;

  /* The raw data can be switched off without taking the fit with it. */
  const raw = document.getElementById('showRawData');
  raw.checked = false; raw.dispatchEvent(new Event('change'));
  await wait(350);
  out.rawOff = traceNames();
  raw.checked = true; raw.dispatchEvent(new Event('change'));
  await wait(350);
  out.rawOn = traceNames();

  metric('data'); metric('μ'); metric('σ');
  await wait(350);

  /* The band and the reference line can be switched off, and the percentiles
     that only describe them stop being required when they are — otherwise a
     shade range left over from earlier blocks every redraw while the band it
     describes is not being drawn. */
  const band = document.getElementById('shadeBand');
  const reference = document.getElementById('referenceLine');
  const warning = () => document.getElementById('chartSettingsWarning').classList.contains('show');
  const lower = document.getElementById('shadeLower');
  lower.value = '0.001';                       // below the chart minimum of P0.1
  lower.dispatchEvent(new Event('input'));
  await wait(300);
  out.staleShade = { blockedWithBandOn: warning() };
  band.checked = false; band.dispatchEvent(new Event('change'));
  await wait(350);
  out.staleShade.blockedWithBandOff = warning();
  out.staleShade.inputsDisabled = [lower.disabled, document.getElementById('shadeUpper').disabled];
  out.bandOffTraces = traceNames();
  lower.value = '5'; lower.dispatchEvent(new Event('input'));
  band.checked = true; band.dispatchEvent(new Event('change'));
  await wait(350);

  reference.checked = false; reference.dispatchEvent(new Event('change'));
  await wait(350);
  out.referenceOff = { traces: traceNames(),
                       pctDisabled: document.getElementById('referencePct').disabled };
  reference.checked = true; reference.dispatchEvent(new Event('change'));
  await wait(350);

  /* And removing them puts the page back where it started. */
  while (document.querySelectorAll('#dist-tabs .dist-close').length) {
    document.querySelector('#dist-tabs .dist-close').click();
    await wait(250);
  }
  out.backToOneTraces = traceNames();
  out.backToOneLegend = chart.layout.showlegend;
  out.backToOneComparison = getComputedStyle(document.getElementById('compare-details')).display !== 'none';
  return JSON.stringify(out);
})()"""

ORIGINAL_TRACES = ['Outer PDF', 'Shaded PDF', 'Outer PDF', 'P50', 'CDF (theoretical)']


async def main():
    version = json.load(urllib.request.urlopen('http://127.0.0.1:9222/json/version'))
    async with websockets.connect(version['webSocketDebuggerUrl'], max_size=100 * 1024 * 1024) as bws:
        async def call(request_id, method, params=None, session=None):
            message = {'id': request_id, 'method': method, 'params': params or {}}
            if session:
                message['sessionId'] = session
            await bws.send(json.dumps(message))
            while True:
                reply = json.loads(await bws.recv())
                if reply.get('id') == request_id:
                    return reply

        target = (await call(1, 'Target.createTarget', {'url': 'about:blank'}))['result']['targetId']
        session = (await call(2, 'Target.attachToTarget',
                              {'targetId': target, 'flatten': True}))['result']['sessionId']
        await call(3, 'Network.enable', None, session)
        await call(4, 'Network.setCacheDisabled', {'cacheDisabled': True}, session)
        await call(5, 'Page.navigate',
                   {'url': 'http://127.0.0.1:8765/logn.html?n=%d' % int(time.time() * 1000)}, session)
        await asyncio.sleep(6)
        reply = await call(6, 'Runtime.evaluate',
                           {'expression': PROBE, 'awaitPromise': True,
                            'returnByValue': True, 'timeout': 60000}, session)
        result = reply.get('result', {})
        if 'exceptionDetails' in result:
            print('EXCEPTION', json.dumps(result['exceptionDetails'])[:500])
            sys.exit(1)
        report = json.loads(result['result']['value'])

    failures = []

    def check(condition, message):
        if not condition:
            failures.append(message)

    check(report['boot']['chartOpen'] is True, 'the chart should be open when the page loads')
    check(report['boot']['traces'] == ORIGINAL_TRACES,
          'the chart should have drawn before anything was touched, got %r'
          % (report['boot']['traces'],))
    check(report['boot']['plotted'] is True and report['boot']['sized'] is True,
          'the chart drawn at boot should be sized to the panel it is in')

    check(report['singleTraces'] == ORIGINAL_TRACES,
          'one distribution no longer draws the traces it drew before there could be several: %s'
          % report['singleTraces'])
    check(report['singleLegend'] is False, 'one distribution should need no legend')

    check(report['lnIsDefault'] is True, 'the chart should open on the log scale')
    check(report['lnTitle'] == 'ln(x)' and report['linearTitle'] == 'x',
          'the axis should say which scale it is on, got %r and %r'
          % (report['lnTitle'], report['linearTitle']))
    check(report['linearTraces'] == ORIGINAL_TRACES,
          'the linear view should draw the same traces, got %r' % (report['linearTraces'],))
    for got, wanted in zip(report['lnRange'], [math.log(v) for v in report['linearRange']]):
        check(abs(got - wanted) < 1e-9,
              'the log scale should cover the same percentiles as the linear one: '
              'ln(%r) is %r, not %r' % (report['linearRange'], wanted, got))
    check(report['singleHasComparison'] is False, 'one distribution is not a comparison')

    check(report['swappedGsd'] == report['swappedGsdWanted'],
          'choosing GSD after working in sigma offered %r, not e^sigma = %r — the distribution was '
          'forgotten while only one metric was selected'
          % (report['swappedGsd'], report['swappedGsdWanted']))

    check(report['copiedFromFirst'] == ['1.5', '0.7'],
          'a new distribution should start as a copy of the current one, got %r' % (report['copiedFromFirst'],))

    check(report['first']['values'] == ['1.5', '0.7'],
          'the first distribution came back as %r, not as it was left' % (report['first']['values'],))
    check(report['second']['values'] == ['3', '0.25'],
          'the second distribution came back as %r, not as it was left' % (report['second']['values'],))
    check(report['third']['values'] == ['50', '3'],
          'the third distribution came back as %r — a value was rebuilt from its own result rather '
          'than kept as typed' % (report['third']['values'],))
    check(report['third']['metrics'] == ['mean', 'gsd'],
          'each distribution keeps its own metric selection, got %r' % (report['third']['metrics'],))

    check(report['legendEntries'] == ['A', 'B', 'C'],
          'the chart should carry one legend entry per distribution, got %r' % (report['legendEntries'],))
    check(report['legend'] is True, 'several distributions need a legend to tell them apart')
    check(report['compareHeaders'] == ['Statistic', 'A', 'B', 'C'],
          'the comparison should list every distribution, got %r' % (report['compareHeaders'],))

    check(report['whileInvalid']['drawn'] == ['A', 'B'],
          'one distribution that does not resolve should leave the other two drawn, got %r'
          % (report['whileInvalid']['drawn'],))
    check(report['whileInvalid']['flagged'] == 1,
          'the distribution that does not resolve should be the one marked')
    check('positive' in report['whileInvalid']['message'],
          'the message should say what is wrong, got %r' % report['whileInvalid']['message'])

    check('B' not in report['hiddenTraces'],
          'hiding a distribution should take it off the chart, traces %r' % (report['hiddenTraces'],))
    check('B' in report['hiddenStillCompared'],
          'hiding a distribution should not take it out of the comparison')

    check(report['dataDisabledBesideMetrics']['disabled'] is True,
          'data should be disabled while %r is selected'
          % (report['dataDisabledBesideMetrics']['selection'],))
    check(report['dataRefused'] == ['mean', 'gsd'],
          'clicking the disabled data pill should change nothing, got %r'
          % (report['dataRefused'],))
    check(report['dataAlone']['selected'] == ['data']
          and report['dataAlone']['panels'] == ['data,data_method', '-'],
          'data should take the first panel and leave no room beside it, got %r / %r'
          % (report['dataAlone']['selected'], report['dataAlone']['panels']))
    check(report['dataAlone']['metricsDisabled'] == [True, True, True],
          'every metric should be disabled while data is selected, got %r'
          % (report['dataAlone']['metricsDisabled'],))
    check(report['dataFit']['mu'] == '2.2259' and report['dataFit']['sigma'] == '1.0214',
          'the data should still be fitted, got mu %r sigma %r'
          % (report['dataFit']['mu'], report['dataFit']['sigma']))
    check(report['metricRefusedBesideData'] == ['data'],
          'clicking a disabled metric while data is selected should change nothing, got %r'
          % (report['metricRefusedBesideData'],))
    check(report['dataKeptItsValues'] == '2 3 4 6 9 13 20 31 48',
          'going back to data should not have lost what was pasted into it, got %r'
          % report['dataKeptItsValues'])
    check(not any('data' in name for name in report['rawOff']),
          'switching the raw data off should take the histogram and the step CDF '
          'off the chart, got %r' % (report['rawOff'],))
    check(any('data' in name for name in report['rawOn']),
          'switching it back on should return them, got %r' % (report['rawOn'],))

    check(report['staleShade']['blockedWithBandOn'] is True,
          'a shade percentile outside the chart bounds should be reported while the band is drawn')
    check(report['staleShade']['blockedWithBandOff'] is False,
          'a shade percentile that describes a band nobody is drawing should not block the chart')
    check(report['staleShade']['inputsDisabled'] == [True, True],
          'the shade percentiles should be disabled along with the band they describe')
    check(len(report['bandOffTraces']) < len(ORIGINAL_TRACES) + 4,
          'switching the band off should collapse each PDF from three segments to one, got %r'
          % (report['bandOffTraces'],))
    check(report['referenceOff']['pctDisabled'] is True,
          'the reference percentile should be disabled along with its line')
    check(not any(name.endswith('P50') for name in report['referenceOff']['traces']),
          'switching the reference line off should take it off the chart, got %r'
          % (report['referenceOff']['traces'],))

    check(report['backToOneTraces'] == ORIGINAL_TRACES,
          'removing the extra distributions should leave the original chart, got %r'
          % (report['backToOneTraces'],))
    check(report['backToOneLegend'] is False, 'the legend should go with the extra distributions')
    check(report['backToOneComparison'] is False, 'the comparison should go with them too')

    print('single distribution :', report['singleTraces'])
    print('three distributions :', report['legendEntries'], '/', report['compareHeaders'])
    print('values on return    :', report['first']['values'], report['second']['values'], report['third']['values'])
    if failures:
        print('%d failure(s):' % len(failures))
        for failure in failures:
            print('  - ' + failure)
        sys.exit(1)
    print('%d checks passed: each distribution stays its own, and one of them is still the page it was.'
          % (42 - len(failures)))

asyncio.run(main())
