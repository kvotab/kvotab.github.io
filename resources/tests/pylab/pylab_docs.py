"""The function documentation of pylab.html: its sources read, its examples
run in PyLAB, and the pages written as JSON for the Help panel.

    python3 pylab_docs.py              build every page (resources/data/pylab-docs)
    python3 pylab_docs.py plots text   build those
    python3 pylab_docs.py --check      say which pages differ from what a build gives

A source file (resources/data/pylab-docs/src/NAME.txt) holds the pages of a
group of functions, each starting with a line `@ name` (or `@ a, b, c` for
a page several functions share):

    @ linspace
    Evenly spaced points between two numbers.        <- the summary, one line

    Paragraphs of description, separated by blank lines.

    # Syntax
    y = linspace(a, b)                                <- a form, at the margin
        What it gives, indented four spaces.
    # Inputs                                          <- # Outputs alike
    a, b — real or complex scalars
        What they are.
    # Examples
    ## Five points from 0 to 1                        <- an example's title
    > A line of prose before the code (or after it).
    y = linspace(0, 1, 5)
    # Notes                                           <- paragraphs
    # See also
    colon logspace

Text in backticks is code; a function's name in backticks becomes a link to
its page. Each example runs in a fresh workspace (no variables, no figures,
`rng default`, `format short`) in a folder of its own; what it prints and
the figures it leaves are stored beside its code, the figures as the page
draws them (in single precision where that changes no value by more than
1e-5 of its array's range). The examples' outputs are never typed by hand.
"""
import asyncio
import itertools
import json
import os
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..', '..'))
DOCS = os.path.join(ROOT, 'resources', 'data', 'pylab-docs')
SRC = os.path.join(DOCS, 'src')
sys.path.insert(0, os.path.join(ROOT, 'resources', 'py'))

SECTIONS = ('Syntax', 'Inputs', 'Outputs', 'Examples', 'Notes', 'See also')


class DocError(Exception):
    pass


# ---- reading ---------------------------------------------------------------------------------------------------

def _paragraphs(lines):
    out, cur = [], []
    for ln in lines:
        if ln.strip():
            cur.append(ln.strip())
        elif cur:
            out.append(' '.join(cur))
            cur = []
    if cur:
        out.append(' '.join(cur))
    return out


def _items(lines, where):
    """Heads at the margin, each with its indented description."""
    out = []
    for ln in lines:
        if not ln.strip():
            continue
        if not ln.startswith(' '):
            out.append([ln.rstrip(), []])
        elif not out:
            raise DocError(f'{where}: an indented line before any item')
        else:
            out[-1][1].append(ln.strip())
    return [[h, ' '.join(d)] for h, d in out]


def _examples(lines, where):
    out = []
    for ln in lines:
        if ln.startswith('## '):
            out.append({'title': ln[3:].strip(), 'intro': [], 'code': [], 'after': []})
        elif not out:
            if ln.strip():
                raise DocError(f'{where}: text before the first example title (## ...)')
        elif ln.startswith('> ') or ln.rstrip() == '>':
            ex = out[-1]
            (ex['after'] if ex['code'] else ex['intro']).append(ln[2:].strip())
        else:
            out[-1]['code'].append(ln.rstrip())
    for ex in out:
        while ex['code'] and not ex['code'][-1].strip():
            ex['code'].pop()
        while ex['code'] and not ex['code'][0].strip():
            ex['code'].pop(0)
        if not ex['code']:
            raise DocError(f"{where}: the example '{ex['title']}' has no code")
        ex['code'] = '\n'.join(ex['code'])
        ex['intro'] = ' '.join(ex['intro'])
        ex['after'] = ' '.join(ex['after'])
    return out


def parse(text, where='?'):
    """The pages of a source file, in order."""
    pages = []
    blocks = re.split(r'(?m)^@ ', text)
    if blocks[0].strip():
        raise DocError(f'{where}: text before the first page (@ name)')
    for b in blocks[1:]:
        lines = b.split('\n')
        names = [n.strip() for n in lines[0].split(',') if n.strip()]
        w = f'{where} @ {names[0] if names else "?"}'
        if not names:
            raise DocError(f'{where}: a page without a name')
        head, secs, cur = [], {}, None
        for ln in lines[1:]:
            m = re.match(r'^# (.+?)\s*$', ln)
            if m:
                cur = m.group(1)
                if cur not in SECTIONS:
                    raise DocError(f"{w}: no section '{cur}' (only {', '.join(SECTIONS)})")
                if cur in secs:
                    raise DocError(f"{w}: two '{cur}' sections")
                secs[cur] = []
            elif cur is None:
                head.append(ln)
            else:
                secs[cur].append(ln)
        while head and not head[0].strip():
            head.pop(0)
        if not head or not head[0].strip():
            raise DocError(f'{w}: no summary line')
        page = {'names': names, 'summary': head[0].strip(), 'body': _paragraphs(head[1:]),
                'syntax': _items(secs.get('Syntax', []), w), 'inputs': _items(secs.get('Inputs', []), w),
                'outputs': _items(secs.get('Outputs', []), w), 'examples': _examples(secs.get('Examples', []), w),
                'notes': _paragraphs(secs.get('Notes', [])),
                'see': [n for n in re.split(r'[\s,]+', ' '.join(secs.get('See also', []))) if n]}
        pages.append(page)
    return pages


def sources():
    """The source files' names (without .txt), in order."""
    return sorted(f[:-4] for f in os.listdir(SRC) if f.endswith('.txt'))


def read(slug):
    with open(os.path.join(SRC, slug + '.txt'), encoding='utf-8') as fh:
        return parse(fh.read(), slug + '.txt')


# ---- running the examples -----------------------------------------------------------------------------------------

_R = []


def _runtime():
    if not _R:
        from plab import runtime as R
        R.setup()
        _R.append(R)
    return _R[0]


def run_example(code, where='?'):
    """What the code prints and the figures it leaves (as the page draws them), in a fresh workspace."""
    R = _runtime()
    from plab import graphics_base as GB
    work = tempfile.mkdtemp(prefix='pylab-doc-')
    old = os.getcwd()
    try:
        os.chdir(work)
        R.STATE['cwd'] = work
        R.BASE.clear()
        R.BASE.gnames.clear()
        asyncio.run(R.execute('close all force; rng default; format short; format loose'))
        GB._ids = itertools.count(1)
        GB._order = itertools.count(1)
        R.take_output()
        try:
            ok = asyncio.run(R.execute(code))
        except Exception as e:  # noqa: BLE001 (any failure is the example's)
            raise DocError(f'{where}: the example failed: {type(e).__name__}: {e}\n{R.take_output()}') from None
        text = R.take_output()
        if not ok:
            raise DocError(f'{where}: the example stopped at an error:\n{text}')
        figs = [GB.serialize_figure(f) for f in sorted(GB.STORE.figures.values(), key=lambda f: f.order) if f.valid]
        asyncio.run(R.execute('close all force'))
        R.take_output()
    finally:
        os.chdir(old)
        shutil.rmtree(work, ignore_errors=True)
    lines = text.split('\n')
    while lines and not lines[-1].strip():
        lines.pop()
    while lines and not lines[0].strip():
        lines.pop(0)
    # a figure's numbers through JSON once, as the page reads them; the default colormap by name (index.json holds it)
    return '\n'.join(lines), _shared(json.loads(json.dumps(figs)))


def shared_arrays():
    """Arrays most figures hold, kept once in index.json: a figure names them ({"$ref": name})."""
    from plab import graphics_base as GB
    from plab.colormaps import colormap_by_name
    import numpy as np
    return {'parula': GB._b64(np.asarray(colormap_by_name('parula', 256), float))}


def _single(o):
    """An array of a figure in single precision when that keeps each value within 1e-5 of the array's range
    (the page draws it no differently, and it takes half the room); else as it was."""
    import base64
    import numpy as np
    if o.get('dt', 'f8') != 'f8':
        return o
    a = np.frombuffer(base64.b64decode(o['$']), '<f8')
    s = a.astype('<f4')
    fin = np.isfinite(a)
    if not np.array_equal(np.isfinite(s), fin) or not np.array_equal(np.isnan(s), np.isnan(a)):
        return o
    if fin.any():
        span = float(np.max(a[fin]) - np.min(a[fin])) or float(np.max(np.abs(a[fin]))) or 1.0
        if np.max(np.abs(s[fin].astype('<f8') - a[fin])) > 1e-5 * span:
            return o
    return {'$': base64.b64encode(s.tobytes()).decode('ascii'), 'shape': o['shape'], 'dt': 'f4'}


def _shared(o, table=None):
    table = table if table is not None else {json.dumps(v, sort_keys=True): k for k, v in shared_arrays().items()}
    if isinstance(o, dict):
        if '$' in o:
            k = table.get(json.dumps(o, sort_keys=True))
            return {'$ref': k} if k else _single(o)
        return {k: _shared(v, table) for k, v in o.items()}
    if isinstance(o, list):
        return [_shared(v, table) for v in o]
    return o


def build(slug):
    """A source file's pages with their examples' results."""
    pages = read(slug)
    for p in pages:
        for k, ex in enumerate(p['examples']):
            ex['output'], ex['figures'] = run_example(ex['code'], f"{slug}.txt @ {p['names'][0]}, example {k + 1} ({ex['title']})")
    return {'slug': slug, 'pages': pages}


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(',', ':'), sort_keys=False) + '\n'


def index(built):
    """Which file holds each name's page."""
    names = {}
    for slug, doc in built.items():
        for p in doc['pages']:
            for n in p['names']:
                if n in names:
                    raise DocError(f"'{n}' has pages in {names[n]}.txt and {slug}.txt")
                names[n] = slug
    return {'names': dict(sorted(names.items())), 'shared': json.loads(json.dumps(shared_arrays()))}


def _built(slug):
    path = os.path.join(DOCS, slug + '.json')
    if not os.path.exists(path):
        return None
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def main(argv):
    check = '--check' in argv
    want = [a for a in argv if not a.startswith('--')] or sources()
    built = {}
    bad = []
    for slug in sources():
        if slug in want:
            doc = build(slug)
            if check:
                if dumps(doc) != dumps(_built(slug) or {}):
                    bad.append(slug)
            else:
                with open(os.path.join(DOCS, slug + '.json'), 'w', encoding='utf-8') as fh:
                    fh.write(dumps(doc))
                print(f"{slug}: {len(doc['pages'])} pages, {sum(len(p['examples']) for p in doc['pages'])} examples")
            built[slug] = doc
        else:
            built[slug] = _built(slug) or build(slug)
    idx = index(built)
    path = os.path.join(DOCS, 'index.json')
    if check:
        old = open(path, encoding='utf-8').read() if os.path.exists(path) else ''
        if dumps(idx) != old:
            bad.append('index')
        print('differ: ' + ', '.join(bad) if bad else 'every page is as a build makes it')
        return 1 if bad else 0
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(dumps(idx))
    print(f"index: {len(idx['names'])} names")
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
