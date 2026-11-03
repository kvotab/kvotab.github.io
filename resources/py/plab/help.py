"""Help for functions: the comment block of a program file, or a short
description of a builtin (helptext.py), with the functions it names as
links and a See also list of related ones.

A link is written into the text as \\x01help:NAME\\x02NAME\\x03, the form the
Command Window draws as a link (pylab-cmd.js) and the Help panel too
(pylab-help.js); 'text' stays plain."""
import re

from . import runtime as R

# builtin names that are also ordinary English words: in prose they are links only when called, name(
_PROSE = frozenset('''
abs all alpha ancestor and angle annotation antipode any area assert assume assumptions axes axis azimuth balance bar beta
between blanks bounds break brush campos case cast cat catch categories ceil cell char children class clear clock close
collect colon combine comet complex compose computer cond contains continue cool count cross curl cylinder date day days deal
delete diary digits display distance divergence doc dot double duration echo edit ellipsoid else end erase error exist exit
expand eye factor factorial false figure fill filter find fix flag flip floor for format formula full function functions
gallery gamma ge get givens global gradient gray grid has head height help hidden hist hold hot hour hours i if image input
integral intersect isolate j join keyboard keys legend length light lighting limit line lines listener load log logical lower
ls mad magic matches material max mean median menu methods milliseconds min minus minute minutes mod mode moment month more nan
ne nonzeros norm normalize not notify now null ones open or otherwise pad pan parse patch path pause peaks perms permute
persistent pi pie piecewise plot plus poly power pretty primes print prod profile properties quad quarter quit rand random range
rank rat rats real reckon refresh remove replace reshape residue rethrow return reverse rewrite roots round run save scatter
second seconds series set shading sign simplify single size slice solve sort sound sparse sphere split squeeze stairs start
stem stop string strings strip subs subtitle sum summary surface switch synchronize table tail tar taylor text throw timer
times title trace transpose true truncate try type union unique upper values version view wait warning web week weekday what
which while white who whos width year years zeros zip zoom NaN Inf NaT
polar box contour dialog histogram mesh quantile bandwidth builtin spline
'''.split())

# a name as the text writes it: not inside another word, a field (s.name), a handle's @, a quoted option or a format
_TOKEN = re.compile(r"(?<![\w.@'\"$%\\])([A-Za-z]\w*(?:\.[A-Za-z]\w*)*)(?![\w'\"])")


def mark(name, text=None):
    """Text that is drawn as a link to name's help."""
    return f'\x01help:{name}\x02{text or name}\x03'


def strip_links(text):
    return re.sub('\x01[^\x02]*\x02', '', text).replace('\x03', '')


def _names():
    from .helptext import HELP
    return set(R.BUILTINS) | set(HELP)


def mentioned(text, own=None, names=None):
    """The functions a text names, in order: a builtin's name called (name(),
    or written alone unless it is also an ordinary word."""
    names = names if names is not None else _names()
    found = []
    for m in _TOKEN.finditer(text):
        n = m.group(1)
        if n == own or n not in names or n in found:
            continue
        if n in _PROSE and text[m.end():m.end() + 1] != '(':
            continue
        found.append(n)
    return found


def linkify(text, own=None, names=None):
    """The text with the functions it names as links (see mentioned)."""
    names = names if names is not None else _names()

    def rep(m):
        n = m.group(1)
        if n == own or n not in names or (n in _PROSE and m.string[m.end():m.end() + 1] != '('):
            return n
        return mark(n)
    return '\n'.join(_TOKEN.sub(rep, line) for line in text.split('\n'))


# ---- See also --------------------------------------------------------------------------------------------

_INDEX = {}


def _index():
    """The help entries in the order helptext.py writes them, each entry's
    section, and each distribution's family of functions."""
    if _INDEX:
        return _INDEX
    from . import helptext
    order, section = [], {}
    sec = 0
    for line in helptext._TEXT.split('\n'):
        if line.startswith('#'):
            sec += 1
            continue
        if line and not line.startswith(' ') and ': ' in line:
            name = line.split(': ', 1)[0]
            section[name] = sec
            order.append(name)
    family = {}
    for code, _, _ in helptext._DISTS:
        members = [code + s for s in ('pdf', 'cdf', 'inv', 'rnd', 'stat', 'fit', 'like') if code + s in helptext.HELP]
        for m in members:
            family[m] = members
    _INDEX.update(order=order, pos={n: i for i, n in enumerate(order)}, section=section, family=family)
    return _INDEX


def see_also(name, most=8):
    """Functions related to name: those sharing its How it works entry,
    those its help names from the same part of the help, its
    distribution's other functions, then its neighbours in that part."""
    from .helptext import HELP, HOW
    names = _names()
    idx = _index()
    res = []

    def add(n):
        if n != name and n in names and n in HELP and n not in res:
            res.append(n)
    blocks = HOW.get(name)
    if blocks is not None:
        for n, b in HOW.items():
            if b is blocks and len(res) < 6:
                add(n)
    summary, forms, notes = HELP[name]
    sec = idx['section'].get(name)
    for n in [m for m in mentioned('\n'.join([summary] + list(forms) + [notes]), name, names) if idx['section'].get(m) == sec][:4]:
        add(n)
    for n in idx['family'].get(name, []):
        add(n)
    if name in idx['pos']:
        i, sec = idx['pos'][name], idx['section'][name]
        order = idx['order']
        for d in range(1, len(order)):
            if len(res) >= 5:
                break
            for j in (i + d, i - d):
                if 0 <= j < len(order) and idx['section'][order[j]] == sec and len(res) < 5:
                    add(order[j])
            if (i + d >= len(order) or idx['section'][order[i + d]] != sec) and (i - d < 0 or idx['section'][order[i - d]] != sec):
                break
    return res[:most]


def _see_line(names, width=76):
    """'See also: a, b, c' wrapped for the Command Window: (plain lines, linked lines)."""
    plain, linked = [], []
    cur, cur_l = ' See also: ', ' See also: '
    for k, n in enumerate(names):
        piece = n + (',' if k < len(names) - 1 else '')
        if len(cur) + len(piece) + 1 > width and cur.strip() != 'See also:':
            plain.append(cur.rstrip())
            linked.append(cur_l.rstrip())
            cur, cur_l = '    ', '    '
        cur += piece + ' '
        cur_l += mark(n) + (',' if k < len(names) - 1 else '') + ' '
    plain.append(cur.rstrip())
    linked.append(cur_l.rstrip())
    return plain, linked


def _file_see_also(text):
    """A program's help comment with the names of its See also lines as links."""
    out = []
    for line in text.split('\n'):
        m = re.match(r'(\s*See also:?\s*)(.*)$', line, re.I)
        if not m:
            out.append(line)
            continue
        names = _names()

        def rep(t):
            n = t.group(1)
            return mark(n) if n in names or R.find_file(n) else n
        out.append(m.group(1) + re.sub(r'\b([A-Za-z]\w*(?:\.[A-Za-z]\w*)*)\b', rep, m.group(2)))
    return '\n'.join(out)


def help_for(name):
    """{'name', 'kind', 'text'} for help NAME and doc NAME; 'text' is plain,
    'linked' the same with links (and base_linked, how_linked, see)."""
    name = name.strip()
    if not name:
        return {'name': '', 'kind': 'overview', 'text': overview()}
    p = R.find_file(name[:-2] if name.endswith('.m') else name)
    if p is not None:
        from .worker_api import help_comment
        text = R.read_source(p, 40000)
        h = help_comment(text)
        t = h or f'{name} is a program file with no help comment.\n'
        return {'name': name, 'kind': 'file', 'path': p, 'text': t, 'linked': _file_see_also(t)}
    from .helptext import HELP, HOW
    entry = HELP.get(name)
    if entry is not None:
        names = _names()
        summary, syntax, more = entry if len(entry) == 3 else (entry[0], entry[1], '')
        lines = [f' {name} - {summary}']
        if syntax:
            lines += [''] + ['    ' + s for s in syntax]
        if more:
            lines += [''] + ['    ' + l for l in more.split('\n')]
        base = '\n'.join(lines) + '\n'
        res = {'name': name, 'kind': 'builtin', 'text': base, 'summary': summary,
               'base_linked': linkify(base, name, names)}
        linked = res['base_linked']
        how = HOW.get(name)
        if how:
            # the Help panel sets these out as paragraphs; the Command Window has them wrapped
            res['base'] = base
            res['how'] = [{'p': b} if kind == 'p' else {'pre': '\n'.join(b)} for kind, b in how]
            res['how_linked'] = [{'p': linkify(b, name, names)} if kind == 'p' else {'pre': '\n'.join(b)} for kind, b in how]
            ht = how_text(how)
            res['text'] += '\n' + ht
            linked += '\n' + linkify(ht, name, names)
        see = see_also(name)
        res['see'] = see
        if see:
            plain, marked = _see_line(see)
            res['text'] += '\n' + '\n'.join(plain) + '\n'
            linked += '\n' + '\n'.join(marked) + '\n'
        res['linked'] = linked
        return res
    if name in R.BUILTINS:
        return {'name': name, 'kind': 'builtin', 'text': f' {name} is a built-in function.\n'}
    return {'name': name, 'kind': 'missing', 'text': f'{name} not found.\n'}


def how_text(blocks, width=76):
    """A function's How it works for the Command Window: paragraphs wrapped,
    formulas as written."""
    import textwrap
    lines = [' How it works', '']
    for kind, b in blocks:
        if kind == 'p':
            lines += textwrap.wrap(b, width, initial_indent='    ', subsequent_indent='    ', break_on_hyphens=False)
        else:
            lines += ['      ' + l for l in b]
        lines.append('')
    return '\n'.join(lines)


def overview():
    return ('Type help NAME for a function, or doc NAME to open its page in the Help panel.\n'
            'The Help panel lists every function by category.\n')
