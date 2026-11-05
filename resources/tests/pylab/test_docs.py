"""The function pages of pylab.html (resources/data/pylab-docs), run
natively: every source file reads; each page names functions PyLAB has, has
a summary, its forms and at least one example; each example run again in a
fresh workspace prints what its page shows and leaves the figures its page
draws (so no page can drift from what PyLAB does); the index names each
function once; the text keeps to the Help's rules.

    python3 test_docs.py          (from any folder)

After a change to a source file, or to what a documented function prints or
draws, build the pages again: python3 pylab_docs.py
"""
import json
import os
import re
import sys
import warnings

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import pylab_docs as D  # noqa: E402

warnings.filterwarnings('ignore')
R = D._runtime()
from plab.helptext import HELP  # noqa: E402


class Checks:
    def __init__(self):
        self.n = 0
        self.failed = []

    def __call__(self, label, ok, detail=''):
        self.n += 1
        if not ok:
            self.failed.append(label)
            print(f'FAIL  {label}  {detail}')
        return ok

    def done(self):
        print(f'\n{self.n - len(self.failed)} of {self.n} checks passed')
        return 1 if self.failed else 0


C = Checks()

slugs = D.sources()
C('there are source files', len(slugs) > 0, slugs)
pages = {}
for slug in slugs:
    try:
        pages[slug] = D.read(slug)
        C(f'{slug}.txt reads', True)
    except D.DocError as e:
        C(f'{slug}.txt reads', False, str(e))

known = set(HELP) | set(R.BUILTINS)
everything = [(slug, p) for slug in pages for p in pages[slug]]
C('every page names functions PyLAB has', all(n in known for _, p in everything for n in p['names']),
  [n for _, p in everything for n in p['names'] if n not in known])
C('every page has a summary sentence', all(p['summary'].endswith('.') for _, p in everything),
  [p['names'][0] for _, p in everything if not p['summary'].endswith('.')])
C('every page has its forms and an example', all(p['syntax'] and p['examples'] for _, p in everything),
  [p['names'][0] for _, p in everything if not (p['syntax'] and p['examples'])])
# an operator's page may give its forms as the operator (a:b, A*B, A\\b, [A, B])
OPERATORS = {'colon', 'plus', 'minus', 'uminus', 'times', 'mtimes', 'rdivide', 'mrdivide', 'ldivide', 'mldivide', 'power', 'mpower',
             'eq', 'ne', 'lt', 'gt', 'le', 'ge', 'and', 'or', 'not', 'transpose', 'ctranspose', 'horzcat', 'vertcat', 'end'}


def names_form(p, code):
    return any(re.search(rf'\b{re.escape(n)}\b', code) for n in p['names']) or bool(OPERATORS & set(p['names']))


C("every form names the page's function", all(names_form(p, code) for _, p in everything for code, _ in p['syntax']),
  [(p['names'][0], code) for _, p in everything for code, _ in p['syntax'] if not names_form(p, code)])
C('every form and argument has its description', all(text for _, p in everything for _, text in p['syntax'] + p['inputs'] + p['outputs']),
  [(p['names'][0], h) for _, p in everything for h, text in p['syntax'] + p['inputs'] + p['outputs'] if not text])
C('See also names functions PyLAB has', all(n in known for _, p in everything for n in p['see']),
  [(p['names'][0], n) for _, p in everything for n in p['see'] if n not in known])


def prose(p):
    yield p['summary']
    yield from p['body']
    yield from (t for _, t in p['syntax'] + p['inputs'] + p['outputs'])
    yield from p['notes']
    for ex in p['examples']:
        yield ex['title']
        yield ex['intro']
        yield ex['after']


words = [(p['names'][0], t) for _, p in everything for t in prose(p)]
C('the text names no other product', not [w for w in words if re.search(r'MATLAB|MathWorks|Octave', w[1])],
  [w for w in words if re.search(r'MATLAB|MathWorks|Octave', w[1])])
history = re.compile(r'\b(no longer|used to be|until recently|from now on|new in|as of version|previously)\b', re.I)
C('the text tells no history of the page', not [w for w in words if history.search(w[1])], [w for w in words if history.search(w[1])])
C('backticks are paired', all(t.count('`') % 2 == 0 for _, t in words), [w for w in words if w[1].count('`') % 2])

# the index, and each built file against a fresh build (every example run again)
built = {}
for slug in slugs:
    path = os.path.join(D.DOCS, slug + '.json')
    have = json.load(open(path, encoding='utf-8')) if os.path.exists(path) else None
    C(f'{slug}.json is built', have is not None)
    try:
        fresh = D.build(slug)
    except D.DocError as e:
        C(f'the examples of {slug}.txt run', False, str(e))
        continue
    built[slug] = fresh
    same = D.dumps(fresh) == D.dumps(have or {})
    detail = ''
    if not same and have:
        for pf, ph in zip(fresh['pages'], have.get('pages', [])):
            for ef, eh in zip(pf['examples'], ph['examples']):
                if ef != eh:
                    detail = f"{pf['names'][0]}, '{ef['title']}': output {ef['output']!r} vs {eh['output']!r}" if ef['output'] != eh['output'] else \
                        f"{pf['names'][0]}, '{ef['title']}': its figures differ"
                    break
            if detail:
                break
        detail = detail or 'the text differs (build the pages again)'
    C(f'{slug}.json is what its examples give now', same, detail)
    size = os.path.getsize(path) if have is not None else 0
    C(f'{slug}.json stays small (under 1.5 MB)', size < 1.5e6, size)
if len(built) == len(slugs):
    idx = D.index(built)
    C('index.json names each function once, with the shared arrays', D.dumps(idx) == open(os.path.join(D.DOCS, 'index.json'), encoding='utf-8').read())

# the examples' figures carry what the page draws
figs = [(p['names'][0], ex['title'], f) for doc in built.values() for p in doc['pages'] for ex in p['examples'] for f in ex['figures']]
C('figures are stored as the page reads them (axes, size)', all(isinstance(f.get('axes'), list) and f.get('width') > 0 and f.get('height') > 0 for _, _, f in figs))

sys.exit(C.done())
