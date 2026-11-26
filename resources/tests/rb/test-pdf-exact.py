#!/usr/bin/env python3
"""Distributions with a saved random state are drawn as the Python code draws them.

A pdf attribute can carry the state of its random generator, numpy's PCG64
({"bit_generator": "PCG64", "state": {"state": ..., "inc": ...}, ...}). The
page then draws what the Python code draws -- numpy's random numbers, with
Latin hypercube sampling in numpy's order, through the same quantile
functions -- so value i is the value of the simulations' iteration i.

fixtures/pdf-exact.json holds pdf texts as the Python code writes them and
the samples it drew from them (numpy 1.26, scipy 1.13), as float64 bit
patterns. The checks:

    uniforms          the uniform numbers of a state, with and without LHS,
                      1 to 10,100 of them (numpy's two choice algorithms):
                      the same bits
    unif, triang,     the same bits (only arithmetic and square roots)
    dtriang
    the others        within 1e-14: they go through log, exp and the normal
                      functions, whose last digit can differ between math
                      libraries
    invalid           no samples where the Python code raises an error
    parsePdf          the 128-bit integers of a state come through exact
                      (JSON.parse would round them)
    histogram data    the info panel's samples of a lookup table and of a
                      parameter, 1,000 with LHS as a simulation draws them

Start the server and the browser as in README.md, then

    python3 resources/tests/rb/test-pdf-exact.py

Exit status is 0 when every check passes.
"""
import asyncio
import json
import sys
import urllib.request

import websockets

from driver import open_page

failures = []
checks = 0


def check(label, got, want=True):
    global checks
    checks += 1
    ok = got == want
    print(f'{"ok  " if ok else "FAIL"}  {label}' + ('' if ok else f': {got!r} (expected {want!r})'))
    if not ok:
        failures.append(label)


RUN = r"""(async () => {
  const fx = await (await fetch('/resources/tests/rb/fixtures/pdf-exact.json')).json();
  const fromHex = (hex) => {
    const out = new Float64Array(hex.length / 16), view = new DataView(new ArrayBuffer(8));
    for (let i = 0; i < out.length; i++) { view.setBigUint64(0, BigInt('0x' + hex.slice(16 * i, 16 * i + 16))); out[i] = view.getFloat64(0); }
    return out;
  };
  const sha = async (arr) => {
    const view = new DataView(new ArrayBuffer(8 * arr.length));
    arr.forEach((v, i) => view.setFloat64(8 * i, v));
    const d = new Uint8Array(await crypto.subtle.digest('SHA-256', view.buffer));
    return Array.from(d, b => b.toString(16).padStart(2, '0')).join('');
  };
  const compare = (got, want) => {
    if (!got || got.length !== want.length) return { identical: -1, total: want.length, maxRel: Infinity };
    let identical = 0, maxRel = 0;
    for (let i = 0; i < want.length; i++) {
      if (Object.is(got[i], want[i])) identical++;
      else maxRel = Math.max(maxRel, Math.abs(got[i] - want[i]) / Math.abs(want[i]));
    }
    return { identical, total: want.length, maxRel };
  };
  const res = { uniforms: [], pdfs: [] };
  for (const u of fx.uniforms) {
    const x = PDFSampler.uniformsFromState(PDFSampler.parsePdf(u.state), u.n, u.lhs);
    const ok = u.hex ? compare(x, fromHex(u.hex)).identical === u.n
                     : (await sha(x)) === u.sha256 && compare(x.slice(0, 3), fromHex(u.first)).identical === 3;
    res.uniforms.push({ n: u.n, lhs: u.lhs, ok });
  }
  for (const p of fx.pdfs) {
    const pdf = PDFSampler.parsePdf(p.text);
    const got = PDFSampler.samplesFromState(pdf, p.n, p.lhs);
    res.pdfs.push(p.hex === null ? { type: pdf.type, n: p.n, lhs: p.lhs, raises: true, none: got === null }
                                 : { type: pdf.type, n: p.n, lhs: p.lhs, ...compare(got, fromHex(p.hex)) });
  }
  // The 128-bit integers of a state, as the text has them
  const text = fx.pdfs[0].text;
  const parsed = PDFSampler.parsePdf(text);
  const digits = text.match(/"state":\s*(\d+)/)[1];
  res.parsedExact = parsed.state.state.state === digits && JSON.parse(text).state.state.state !== Number(digits).toString();
  // Drawn by default with LHS, as the simulations; a pdf without a state still gives random samples
  const lhsDefault = compare(PDFSampler.generatePdfSamples(parsed, 200), PDFSampler.samplesFromState(parsed, 200, true));
  res.defaultIsLhs = lhsDefault.identical === 200;
  const noState = { ...parsed }; delete noState.state;
  const random = PDFSampler.generatePdfSamples(noState, 200);
  res.noStateDraws = !!random && random.length === 200 && !PDFSampler.isExact(noState);
  // The info panel's histogram data: a lookup table of two points and a parameter
  const lt = collectPdfSpecData({ pdf: fx.lookup.text, index: Float64Array.from(fx.lookup.index) },
                                { value: Float64Array.from(fx.lookup.values) }, '/example/lookup');
  res.lookup = lt && lt.type === 'lookup' ? lt.entries.map((e, i) => compare(e.samples, fromHex(fx.lookup.hex[i]))) : null;
  const one = collectPdfSpecData({ pdf: fx.single.text }, { value: fx.single.value }, '/example/single');
  res.single = one && one.type === 'single' ? compare(one.samples, fromHex(fx.single.hex)) : null;
  return JSON.stringify(res);
})()"""

BIT_EXACT = {'unif', 'triang', 'dtriang'}


async def main():
    bws_url = json.load(urllib.request.urlopen('http://127.0.0.1:9222/json/version'))['webSocketDebuggerUrl']
    async with websockets.connect(bws_url, max_size=200 * 1024 * 1024) as bws:
        tid, page = await open_page(bws)
        try:
            res = json.loads(await page.ev(RUN))
            for u in res['uniforms']:
                check(f'uniform numbers, n = {u["n"]:,}{" with LHS" if u["lhs"] else ""}: numpy\'s bits', u['ok'])
            for p in res['pdfs']:
                name = f'{p["type"]}, n = {p["n"]}{" with LHS" if p["lhs"] else ""}'
                if p.get('raises'):
                    check(f'{name}: none, where the Python code raises', p['none'])
                elif p['type'] in BIT_EXACT:
                    check(f'{name}: the same bits', p['identical'], p['total'])
                else:
                    check(f'{name}: within 1e-14', p['identical'] >= 0 and p['maxRel'] <= 1e-14)
            check('parsePdf keeps the 128-bit integers of a state exact', res['parsedExact'])
            check('drawn with LHS by default, as the simulations', res['defaultIsLhs'])
            check('a pdf without a state still gives random samples', res['noStateDraws'])
            check('histogram data of a lookup table: both points', res['lookup'] is not None and len(res['lookup']) == 2)
            for i, e in enumerate(res['lookup'] or []):
                check(f'  point {i}: the simulations\' 1,000 samples', e['identical'] >= 0 and e['maxRel'] <= 1e-14)
            check('histogram data of a parameter: the simulations\' 1,000 samples',
                  res['single'] is not None and res['single']['identical'] >= 0 and res['single']['maxRel'] <= 1e-14)
            check('no console errors throughout', page.logs[:3], [])
        finally:
            await bws.send(json.dumps({'id': 98, 'method': 'Target.closeTarget', 'params': {'targetId': tid}}))
    print(f'\n{checks - len(failures)} of {checks} checks passed')
    if failures:
        print('failed: ' + ', '.join(failures))
    return 1 if failures else 0

sys.exit(asyncio.run(main()))
