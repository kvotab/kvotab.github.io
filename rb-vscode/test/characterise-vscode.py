#!/usr/bin/env python3
"""The site's characterisation walk (resources/tests/rb/characterise.py),
inside the HDF5 Browser in VS Code.

The same seventeen steps, evaluated in the webview's page instead of a tab,
with the two fixtures opened as a reader opens them in VS Code: together,
from the extension, read whole or lazily as the setting says. The fingerprint
it writes compares with the site's `--open` ones:

    python3 resources/tests/rb/characterise.py site-never --open never
    python3 rb-vscode/test/characterise-vscode.py vscode-never --open never
    python3 resources/tests/rb/compare.py site-never.json vscode-never.json

and the same with `always`. What may differ, and why, is listed in
test/README.md; anything else is the extension showing something the site
does not.
"""
import asyncio
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'resources', 'tests', 'rb'))
sys.path.insert(0, HERE)

import characterise  # noqa: E402  (its STEPS and OPENED)
from vscode_driver import VSCode  # noqa: E402


async def main():
    label = sys.argv[1] if len(sys.argv) > 1 else 'vscode'
    mode = sys.argv[sys.argv.index('--open') + 1] if '--open' in sys.argv else 'never'
    vs = VSCode(settings={'hdf5Browser.readLazily': mode}).start()
    try:
        fingerprint = {}
        page = None
        for name, expr in characterise.STEPS:
            if name == 'load.two.files':
                m = vs.mark()
                vs.command('together', paths=[os.path.join(characterise.FIXTURES, n)
                                              for n in ('sample-a.h5', 'sample-b.h5')])
                vs.wait_event(lambda e: e['type'] == 'status' and e.get('kind') == 'opened'
                              and any(f['name'] == 'sample-b.h5' for f in e.get('opened', [])),
                              180, 'both files to open', since=m)
                expr = characterise.OPENED
            if page is None:
                # The view exists once a file is opened in it: the steps before
                # the load run on a page that already holds sample-a.h5.
                if name != 'load.two.files':
                    m = vs.mark()
                    vs.command('open', paths=[os.path.join(characterise.FIXTURES, 'sample-a.h5')])
                    vs.wait_event(lambda e: e['type'] == 'status', 180, 'the first file to open', since=m)
                page = await vs.page()
            try:
                value = await page.ev(expr, timeout=180)
            except Exception as exc:
                value = 'HARNESS ERROR: %s' % exc
            fingerprint[name] = value
            head = json.dumps(value, sort_keys=True)[:110] if not isinstance(value, str) else value[:110]
            print('  %-22s %s' % (name, head))

        fingerprint['_console'] = ['%s: %s' % (k, m[:150]) for k, m in page.logs]
        fingerprint['_extension_log'] = [e['text'][:150] for e in vs.events if e['type'] == 'log']
        out = '%s.json' % label
        with open(out, 'w') as fh:
            json.dump(fingerprint, fh, indent=1, sort_keys=True)
        print('\nwrote %s   console entries: %d   extension log entries: %d'
              % (out, len(fingerprint['_console']), len(fingerprint['_extension_log'])))
        for line in (fingerprint['_console'] + fingerprint['_extension_log'])[:8]:
            print('   ', line)
        await page.close()
    finally:
        vs.stop()


if __name__ == '__main__':
    asyncio.run(main())
