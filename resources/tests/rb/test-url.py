#!/usr/bin/env python3
"""Where a URL load actually goes, and what it is allowed to carry.

The GitHub address a reader has in front of them is the page about a file, not
the file, so the loader rewrites it. Which host it rewrites to depends on
whether there is a token, because only one of the two will take one:

    no token   raw.githubusercontent.com, public only
    a token    the Contents API -- raw.githubusercontent.com answers a CORS
               preflight carrying Authorization with 403, so the header can
               never be sent there

The check that matters most here is the last one: the token is attached only to
a URL the loader built itself for api.github.com. A URL the reader pasted must
never be given it, or pasting a link would hand a GitHub credential to whoever
wrote the link. That is asserted below for a foreign host, for the site's own
host, and for an address that is already a raw one.

Start the server and the browser as in README.md, then

    python3 resources/tests/rb/test-url.py

Exit status is 0 when every check passes.
"""
import asyncio
import json
import sys
import urllib.request

import websockets

from driver import open_page

BLOB = 'https://github.com/kvotab/kvotab.github.io/blob/main/resources/data/x.h5'
TOKEN = 'github_pat_11NOTAREALTOKEN_0000000000'

failures = []
checks = 0


def check(label, got, want=True):
    global checks
    checks += 1
    ok = got == want
    print(f'{"ok  " if ok else "FAIL"}  {label}' + ('' if ok else f': {got!r} (expected {want!r})'))
    if not ok:
        failures.append(label)


PLAN = """(() => {
  const at = (u) => { const p = githubFetchPlan(new URL(u)); return p && { url: p.url,
    auth: !!(p.headers && p.headers.Authorization), authenticated: p.authenticated }; };
  return JSON.stringify({
    blob:  at(%s),
    raw:   at('https://raw.githubusercontent.com/o/r/main/a.h5'),
    site:  at('https://kvotab.se/resources/data/a.h5'),
    other: at('https://evil.example.com/a.h5'),
  });
})()""" % json.dumps(BLOB)


async def main():
    ver = json.load(urllib.request.urlopen('http://127.0.0.1:9222/json/version'))
    async with websockets.connect(ver['webSocketDebuggerUrl'], max_size=64 * 1024 * 1024) as bws:
        tid, page = await open_page(bws, url='http://127.0.0.1:8765/rb.html', settle=7)
        try:
            await page.ev("rememberGithubToken('')")
            plan = json.loads(await page.ev(PLAN))
            check('with no token a GitHub page URL goes to the raw host',
                  plan['blob']['url'],
                  'https://raw.githubusercontent.com/kvotab/kvotab.github.io/main/resources/data/x.h5')
            check('and carries no credential', plan['blob']['auth'], False)

            await page.ev(f"rememberGithubToken({json.dumps(TOKEN)})")
            plan = json.loads(await page.ev(PLAN))
            check('with a token it goes to the Contents API instead',
                  plan['blob']['url'],
                  'https://api.github.com/repos/kvotab/kvotab.github.io'
                  '/contents/resources/data/x.h5?ref=main')
            check('and that one does carry it', plan['blob']['auth'], True)

            # The point of the whole arrangement.
            check('an address that is already raw is left alone', plan['raw'], None)
            check('the site’s own host is left alone', plan['site'], None)
            check('and a pasted foreign host is left alone', plan['other'], None)

            # Where it is kept, and where it is not.
            check('the token is remembered for the tab',
                  await page.ev("sessionStorage.getItem('kvot-rb-github-token')"), TOKEN)
            check('and never written to disk',
                  await page.ev("localStorage.getItem('kvot-rb-github-token')"), None)
            await page.ev("rememberGithubToken('')")
            check('emptying the field forgets it',
                  await page.ev("sessionStorage.getItem('kvot-rb-github-token')"), None)

            # A private repository is a 404, not a 403, so the message has to
            # say so or the reader is told the file does not exist.
            check('a 404 without a token mentions the token', await page.ev(
                "explainUrlFailure(new Error('HTTP 404 Not Found'), "
                "{ authenticated: false }).includes('private')"), True)
            check('a 401 with one says the token was refused', await page.ev(
                "explainUrlFailure(new Error('HTTP 401'), "
                "{ authenticated: true }).includes('refused')"), True)
        finally:
            await bws.send(json.dumps({'id': 98, 'method': 'Target.closeTarget',
                                       'params': {'targetId': tid}}))

    print(f'\n{checks - len(failures)} of {checks} checks passed')
    if failures:
        print('failed: ' + ', '.join(failures))
    return 1 if failures else 0


sys.exit(asyncio.run(main()))
