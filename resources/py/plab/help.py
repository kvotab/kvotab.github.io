"""Help for functions: the comment block of a program file, or a short
description of a builtin (helptext.py)."""
import os

from . import runtime as R


def help_for(name):
    """{'name', 'kind', 'text'} for help NAME and doc NAME."""
    name = name.strip()
    if not name:
        return {'name': '', 'kind': 'overview', 'text': overview()}
    p = R.find_file(name[:-2] if name.endswith('.m') else name)
    if p is not None:
        from .worker_api import help_comment
        text = R.read_source(p, 40000)
        h = help_comment(text)
        return {'name': name, 'kind': 'file', 'path': p, 'text': h or f'{name} is a program file with no help comment.\n'}
    from .helptext import HELP, HOW
    entry = HELP.get(name)
    if entry is not None:
        summary, syntax, more = entry if len(entry) == 3 else (entry[0], entry[1], '')
        lines = [f' {name} - {summary}']
        if syntax:
            lines += [''] + ['    ' + s for s in syntax]
        if more:
            lines += [''] + ['    ' + l for l in more.split('\n')]
        out = {'name': name, 'kind': 'builtin', 'text': '\n'.join(lines) + '\n', 'summary': summary}
        how = HOW.get(name)
        if how:
            # the Help panel sets these out as paragraphs; the Command Window has them wrapped
            out['base'] = out['text']
            out['how'] = [{'p': b} if kind == 'p' else {'pre': '\n'.join(b)} for kind, b in how]
            out['text'] += '\n' + how_text(how)
        return out
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
