"""Build a padded probabilistic HDF5 fixture inside the browser using h5wasm's
writer, then download it so it can be reloaded by the app.

The fixture is the case the length-division stride gets wrong:
  /time            shape (T, PAD)  probabilistic=1, n_times=[T, T-3, T-7]
  /grp/DS          shape (T, PAD)  time_dependent=1
with PAD > nIter, so flatLength / timeLength != PAD.
"""
import asyncio
import base64
import json
import os
import urllib.request

import websockets

T = 40      # time steps
NITER = 3   # real iterations
PAD = 8     # padded columns  (flat length = T*PAD = 320; T=40 -> 320/40 = 8 == PAD)

BUILD = """(async () => {
  await waitForH5Wasm();
  const { FS, File, Group } = window.h5wasm;
  const T = %d, NITER = %d, PAD = %d;

  // time[t][k] strictly increasing down each of the first NITER columns,
  // padding columns and padded tail rows hold zeros.
  const time = new Float64Array(T * PAD);
  const nTimes = new Int32Array(NITER);
  for (let k = 0; k < NITER; k++) {
    const len = T - k * 3;
    nTimes[k] = len;
    for (let t = 0; t < len; t++) time[t * PAD + k] = (t + 1) * (10 ** k);
  }

  // y[t][k] = k * 1000 + t, so the iteration is identifiable from any value.
  const y = new Float64Array(T * PAD);
  for (let k = 0; k < PAD; k++) {
    for (let t = 0; t < T; t++) y[t * PAD + k] = k * 1000 + t;
  }

  try { FS.unlink('/fixture.h5'); } catch (e) {}
  const f = new File('/fixture.h5', 'w');
  const td = f.create_dataset({ name: 'time', data: time, shape: [T, PAD], dtype: '<f8' });
  td.create_attribute('probabilistic', 1, [], '<i4');
  td.create_attribute('n_times', nTimes, [NITER], '<i4');
  td.create_attribute('unit', 'years');

  const g = f.create_group('grp');
  g.create_attribute('IndexLists', ['Radionuclides'], [1]);
  g.create_attribute('time_dependent', 1, [], '<i4');
  const ds = g.create_dataset({ name: 'DS', data: y, shape: [T, PAD], dtype: '<f8' });
  ds.create_attribute('time_dependent', 1, [], '<i4');
  ds.create_attribute('unit', 'Bq');

  f.flush();
  f.close();
  const bytes = FS.readFile('/fixture.h5');
  let bin = '';
  const chunk = 8192;
  for (let i = 0; i < bytes.length; i += chunk) {
    bin += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
  }
  return btoa(bin);
})()""" % (T, NITER, PAD)


async def main():
    ver = json.load(urllib.request.urlopen('http://127.0.0.1:9222/json/version'))
    async with websockets.connect(ver['webSocketDebuggerUrl'], max_size=200 * 1024 * 1024) as bws:
        from rb_drive import open_page
        tid, page = await open_page(bws)
        out = await page.ev(BUILD, timeout=120)
        if not isinstance(out, str) or out.startswith('EXCEPTION'):
            print('build failed:', out)
            print('logs:', page.logs[:6])
            return
        data = base64.b64decode(out)
        dest = '/Users/paroot/Library/CloudStorage/Dropbox/KVOT/kvotab/resources/tests/prob-fixture.h5'
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        open(dest, 'wb').write(data)
        print('wrote %s (%d bytes)' % (dest, len(data)))
        print('T=%d nIter=%d PAD=%d  flatLength/T = %d' % (T, NITER, PAD, (T * PAD) // T))
        await bws.send(json.dumps({'id': 99, 'method': 'Target.closeTarget', 'params': {'targetId': tid}}))

asyncio.run(main())
