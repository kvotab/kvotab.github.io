#!/usr/bin/env python3
"""The extension host's reader (src/reader.mjs) answers as the site's lazy
worker (resources/js/rb-lazy-worker.js) does.

The page cannot tell which of the two opened a file: both answer open, group,
values and close, and the page is built on those answers. So every answer
about each file is asked of both -- the reader under Node, the worker in the
site's page in Chrome -- and they must be the same, value for value and type
for type. The worker's answers go through src/codec.js as the reader's do, so
this also shows nothing is lost on the way to a webview.

The files: the site's fixtures, and one made here with h5py of what is
awkward to carry -- NaN, infinities, -0, 64-bit integers past 2**53, text
that is not ASCII, links of each kind, a compound, a 2-D and an LZF dataset.

When this passes, and only then, put rb-lazy-worker.js's new hash in
build.mjs's READER_MIRRORS; the build refuses to run until the two have been
compared again after the worker changes.

Start the site's server and Chrome as in resources/tests/rb/README.md, run
node build.mjs, then

    python3 rb-vscode/test/test-reader.py

Exit status 0 when every file's answers agree.
"""
import asyncio
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request

import websockets

HERE = os.path.dirname(os.path.abspath(__file__))
EXT = os.path.dirname(HERE)
REPO = os.path.dirname(EXT)
sys.path.insert(0, os.path.join(REPO, 'resources', 'tests', 'rb'))
from driver import open_page  # noqa: E402

FIXTURES = os.path.join(REPO, 'resources', 'tests', 'rb', 'fixtures')


def make_awkward(path):
    import h5py
    import numpy as np
    with h5py.File(path, 'w') as f:
        a = f.attrs
        a['nan'] = np.nan
        a['pinf'] = np.inf
        a['ninf'] = -np.inf
        a['negzero'] = -0.0
        a['int64'] = np.int64(2**62 + 1)
        a['uint64'] = np.uint64(2**63 + 5)
        a['int32'] = np.int32(-7)
        a['flag'] = True
        a['text'] = 'åäö — ✓'
        a['fixed'] = np.bytes_(b'fixed')
        a['floats'] = np.array([1.5, np.nan, -np.inf])
        a['ints'] = np.array([2**62, -3], dtype=np.int64)
        a['texts'] = ['a', 'bb', 'åäö']
        f.create_dataset('time', data=np.logspace(0, 4, 20)).attrs['unit'] = 'years'
        g = f.create_group('g')
        g.attrs['time_dependent'] = 'TRUE'
        g.create_dataset('f64', data=np.array([1.0, np.nan, np.inf, -0.0]))
        g.create_dataset('i64', data=np.array([2**62 + 1, -(2**62)], dtype=np.int64))
        g.create_dataset('u8', data=np.arange(5, dtype=np.uint8))
        g.create_dataset('f32_2d', data=np.arange(6, dtype=np.float32).reshape(2, 3))
        g.create_dataset('strings', data=np.array(['x', 'åäö'], dtype=h5py.string_dtype()))
        g.create_dataset('compound', data=np.array([(1.5, 2), (np.nan, -1)], dtype=[('x', 'f8'), ('n', 'i4')]))
        g.create_dataset('lzf', data=np.arange(1000) * 0.5, compression='lzf', chunks=(250,))
        g['soft'] = h5py.SoftLink('/time')
        g['broken'] = h5py.SoftLink('/nowhere')
        g['ext'] = h5py.ExternalLink('other.h5', '/x')
        g.create_group('sub').create_dataset('scalar', data=3.25)


PAGE_WALK = """(async (b64) => {
  const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
  const file = new File([bytes], 'x.h5');
  const out = { groups: {} };
  const opened = await rbLazyCall('open', { file });
  const fid = opened.fid;
  out.open = Object.assign({}, opened, { fid: 'fid' });
  const queue = ['/'];
  const datasets = [];
  while (queue.length) {
    const g = queue.shift();
    const answer = await rbLazyCall('group', { fid, path: g });
    out.groups[g] = answer;
    for (const c of answer.children || []) {
      const p = g === '/' ? `/${c.name}` : `${g}/${c.name}`;
      if (c.type === 'Group') queue.push(p);
      if (c.type === 'Dataset') datasets.push(p);
    }
  }
  out.values = await rbLazyCall('values', { fid, paths: datasets.concat(['/does/not/exist']) });
  out.close = await rbLazyCall('close', { fid });
  // As the reader's answers are, on their way to a webview.
  const encoded = KvotVscodeCodec.encode(out);
  encoded.open.fid = 'fid';
  return JSON.stringify(canonicalAnswer(encoded));
})(%s)"""


def diff(a, b, where=''):
    if type(a) is not type(b):
        return [f'{where or "/"}: {json.dumps(a)[:120]}  vs  {json.dumps(b)[:120]}']
    if isinstance(a, dict):
        out = []
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                out.append(f'{where}/{k}: only in {"the reader" if k in a else "the worker"}')
            else:
                out += diff(a[k], b[k], f'{where}/{k}')
        return out
    if isinstance(a, list):
        if len(a) != len(b):
            return [f'{where}: {len(a)} items vs {len(b)}']
        out = []
        for i, (x, y) in enumerate(zip(a, b)):
            out += diff(x, y, f'{where}[{i}]')
        return out
    return [] if a == b else [f'{where}: {json.dumps(a)[:120]}  vs  {json.dumps(b)[:120]}']


WORK = []


async def main():
    work = tempfile.mkdtemp(prefix='rbv-reader-')
    WORK.append(work)
    files = [os.path.join(FIXTURES, n) for n in ('sample-a.h5', 'sample-b.h5', 'lzf.h5')]
    try:
        awkward = os.path.join(work, 'awkward.h5')
        make_awkward(awkward)
        files.append(awkward)
    except ImportError:
        print('skip  awkward.h5: h5py is not installed')

    failed = []
    ver = json.load(urllib.request.urlopen('http://127.0.0.1:9222/json/version'))
    async with websockets.connect(ver['webSocketDebuggerUrl'], max_size=200 * 1024 * 1024) as bws:
        tid, page = await open_page(bws, settle=6)
        try:
            for f in ('canonical.js', os.path.join('..', 'src', 'codec.js')):
                with open(os.path.join(HERE, f)) as fh:
                    await page.ev(fh.read() + '\ntrue')
            for path in files:
                node = subprocess.run(['node', os.path.join(HERE, 'reader-answers.mjs'), path],
                                      capture_output=True, text=True, cwd=EXT)
                if node.returncode:
                    print(f'FAIL  {os.path.basename(path)}: the reader failed: {node.stderr.strip()[:300]}')
                    failed.append(path)
                    continue
                reader = json.loads(node.stdout)
                with open(path, 'rb') as fh:
                    b64 = base64.b64encode(fh.read()).decode()
                got = await page.ev(PAGE_WALK % json.dumps(b64), timeout=180)
                if not isinstance(got, str) or got.startswith('EXCEPTION'):
                    print(f'FAIL  {os.path.basename(path)}: the worker failed: {str(got)[:300]}')
                    failed.append(path)
                    continue
                worker = json.loads(got)
                d = diff(reader, worker)
                values = len(reader.get('values', {}).get('values', {}))
                if d:
                    failed.append(path)
                    print(f'FAIL  {os.path.basename(path)}: {len(d)} answers differ')
                    for line in d[:15]:
                        print('        ' + line)
                else:
                    print(f'ok    {os.path.basename(path)}: every answer the same '
                          f'({len(reader["groups"])} groups, {values} datasets\' values)')
            logs = [m for k, m in page.logs if 'favicon' not in m.lower()]
            if logs:
                print('FAIL  the page logged: ' + '; '.join(logs[:3]))
                failed.append('console')
        finally:
            await bws.send(json.dumps({'id': 99, 'method': 'Target.closeTarget', 'params': {'targetId': tid}}))

    # The codec on its own: what goes in comes out.
    rt = subprocess.run(['node', '-e', r"""
      const { encode, decode } = require('./src/codec.js');
      const same = (a, b) => Object.is(a, b) || (typeof a === 'object' && a !== null && typeof b === 'object' && b !== null
        && a.constructor === b.constructor && Object.keys(a).length === Object.keys(b).length
        && Object.keys(a).every(k => same(a[k], b[k])));
      const cases = [NaN, Infinity, -Infinity, -0, 0, 5n, -(2n ** 63n), undefined, null, 'åäö', [1, NaN, [2n]],
        { a: NaN, b: { c: -0 } }, { __kvot__: 'NaN', v: 1 }, new Float64Array([1, NaN]), new BigInt64Array([2n ** 62n])];
      const bad = cases.filter(c => { const d = decode(JSON.parse(JSON.stringify(encode(c), (k, v) => ArrayBuffer.isView(v) ? { __view: v.constructor.name, d: Array.from(v, String) } : v), (k, v) => v && v.__view ? new globalThis[v.__view](v.d.map(x => v.__view.startsWith('Big') ? BigInt(x) : Number(x))) : v)); return !same(c, d); });
      console.log(bad.length ? 'FAIL ' + bad.map(String).join(', ') : 'ok');
    """], capture_output=True, text=True, cwd=EXT)
    codec_ok = rt.stdout.strip() == 'ok'
    print(('ok    ' if codec_ok else 'FAIL  ') + 'the codec gives back what it was given, through JSON' + ('' if codec_ok else ': ' + rt.stdout + rt.stderr))
    if not codec_ok:
        failed.append('codec')

    print(f'\n{len(files) + 1 - len(failed)} of {len(files) + 1} checks passed')
    return 1 if failed else 0


def run():
    try:
        return asyncio.run(main())
    finally:
        for d in WORK:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(run())
