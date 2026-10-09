#!/usr/bin/env python3
"""The JSL converter (resources/py/smui/jsl.py, jsl_python.py): the reader
checked on the rules of the JSL Syntax Reference (precedence, names,
strings, dates, matrices, scopes, error recovery); the translation compiled
for every script and run on a small table of our own, written as the CSV
file the page writes, against values worked out independently (numpy and
plain Python over the same numbers); the platform launches as the page's
steps; and the notes, with their lines.

    python3 resources/tests/smui/test_jsl.py
"""
import contextlib
import datetime
import io
import math
import os
import signal
import sys
import tempfile
import tokenize
import warnings

import numpy as np
import pandas as pd

from backend import Checks, call
from smui import jsl, jsl_python

check = Checks()
jsl_python.STRICT = True     # a fault of the translator is an exception here, not a note

# ---- our own table (made up for these tests) ---------------------------------------------------------
STUDENTS = pd.DataFrame({
    'name': [f'S{i:02d}' for i in range(1, 13)],
    'sex': ['F', 'M'] * 6,
    'age': [12, 12, 13, 13, 14, 14, 15, 15, 16, 16, 17, 17],
    'height': [51.5, 59.0, 55.0, 61.5, 57.5, 64.0, 60.0, 66.5, 62.5, 69.0, 63.0, 70.5],
    'weight': [80.0, 95.5, 88.0, 110.0, 97.5, np.nan, 106.0, 128.5, 113.0, 140.0, 118.5, 150.0],
})
TABLES = [{'name': 'Students', 'columns': [
    {'name': 'name', 'dataType': 'character', 'modelingType': 'nominal'},
    {'name': 'sex', 'dataType': 'character', 'modelingType': 'nominal'},
    {'name': 'age', 'dataType': 'numeric', 'modelingType': 'ordinal'},
    {'name': 'height', 'dataType': 'numeric', 'modelingType': 'continuous'},
    {'name': 'weight', 'dataType': 'numeric', 'modelingType': 'continuous'}]}]
H = STUDENTS['height'].to_numpy()
W = STUDENTS['weight'].to_numpy()
SEX = STUDENTS['sex'].tolist()
AGE = STUDENTS['age'].to_numpy()

compiled = [0, 0, 0]


def newer_fstrings(src):
    """The f-strings in src that Python 3.10 and 3.11 cannot read: a backslash,
    or the f-string's own quote, inside a {} (allowed from 3.12). Python 3.12
    reads an f-string as tokens, so the check needs 3.12; before it, compile()
    rejects them itself."""
    if not hasattr(tokenize, 'FSTRING_START'):
        return 0
    bad, quotes = 0, []
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if quotes and tok.type != getattr(tokenize, 'FSTRING_MIDDLE') or len(quotes) > 1:
            text = tok.string.lstrip('rRbBuUfF')
            if '\\' in tok.string or (tok.type in (tokenize.STRING, tokenize.FSTRING_START) and text[:1] in quotes):
                bad += 1
        if tok.type == tokenize.FSTRING_START:
            quotes.append(tok.string.lstrip('rRbBuUfF')[:1])
        elif tok.type == tokenize.FSTRING_END:
            quotes.pop()
    return bad


def conv(src, tables=TABLES, current='Students'):
    """The conversion, and a check that its Python compiles (and reads in
    Python 3.10)."""
    r = jsl_python.convert_text(src, tables, current)
    compiled[0] += 1
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', SyntaxWarning)     # the translator makes them notes
            compile(r['python'], '<converted>', 'exec')
    except SyntaxError as e:
        compiled[1] += 1
        print(f'FAIL  the translation compiles: {e}\n{r["python"]}')
        check.failed.append(f'compile: {src[:60]!r}')
    if newer_fstrings(r['python']):
        compiled[2] += 1
        print(f'FAIL  the translation reads in Python 3.10:\n{r["python"]}')
        check.failed.append(f'python 3.10: {src[:60]!r}')
    return r


class Timeout(Exception):
    pass


def run(r, files=None, timeout=20):
    """Run a translation in a folder with Students.csv (and other tables),
    as the page runs it: its variables, and what it printed."""
    files = {'Students': STUDENTS, **(files or {})}
    old = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        for name, df in files.items():
            df.to_csv(os.path.join(tmp, f'{name}.csv'), index=False)
        os.chdir(tmp)
        ns = {}
        out = io.StringIO()

        def alarm(*_):
            raise Timeout()
        signal.signal(signal.SIGALRM, alarm)
        signal.alarm(timeout)
        try:
            with contextlib.redirect_stdout(out):
                exec(compile(r['python'], '<converted>', 'exec'), ns)
            ns['__files__'] = sorted(os.listdir(tmp))
            for f in ns['__files__']:
                if f.endswith('.csv') and f[:-4] not in files:
                    ns['__csv__' + f] = pd.read_csv(f)
        finally:
            signal.alarm(0)
            os.chdir(old)
    ns['__out__'] = out.getvalue()
    return ns


def P(src):
    return jsl.dump(jsl.parse_expr(src))


def near(a, b, tol=1e-9):
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    return a.shape == b.shape and bool(np.all((np.isnan(a) & np.isnan(b)) | (np.abs(a - b) <= tol * np.maximum(1, np.abs(b)))))


def notes_of(r, sev=None):
    return [n for n in r['notes'] if sev is None or n['severity'] == sev]


def has_note(r, line, words, sev=None):
    return any(n['line'] == line and words.lower() in n['text'].lower() and (sev is None or n['severity'] == sev) for n in r['notes'])


# ==========================================================================================================
# the reader
# ==========================================================================================================

# ---- precedence, by the operator table
for src, want in [
        ('1 + 2 * 3', '(1 + (2 * 3))'), ('(1 + 2) * 3', '((1 + 2) * 3)'), ('2 ^ 3 ^ 2', '(2 ^ (3 ^ 2))'),
        ('-2 ^ 2', '(-(2 ^ 2))'), ('2 ^ -1', '(2 ^ (-1))'), ('a = b = c', '(a = (b = c))'), ('a += b -= c', '(a += (b -= c))'),
        ('a || b == c', '((a || b) == c)'), ('!a == b', '((!a) == b)'), ('a & b | c', '((a & b) | c)'), ('a | b & c', '(a | (b & c))'),
        ('a :* b + c', '((a :* b) + c)'), ('a * b :/ c', '((a * b) :/ c)'), ('a || b + c', '(a || (b + c))'), ('a |/ b || c', '((a |/ b) || c)'),
        ('1::n + 1', '(1 :: (n + 1))'), ('x = dt << Get Name', '(x = (dt << Get Name))'), ('obj << A << B(1)', '((obj << A) << B(1))'),
        ('obj << {A, B(2)}', '(obj << {A, B(2)})'), ('i++', '(i++)'), ('X` * X', '((X`) * X)'), ('dt:x << Get Values', '((dt:x) << Get Values)'),
        (':x[2]', ':x[2]'), ('m[0, 2]', 'm[0, 2]'), ('a[i][j]', 'a[i][j]'), ('f(x)[2]', 'f(x)[2]'), ('If(a, b; c, d)', 'If(a, (b; c), d)'),
        ('-a * b', '((-a) * b)'), ('a - b - c', '((a - b) - c)'), ('a / b * c', '((a / b) * c)'), ('!a & !b', '((!a) & (!b))'),
        ('x = a < b', '(x = (a < b))'), ('a == b | c == d', '((a == b) | (c == d))'), ('x ||= "s"', '(x ||= \'s\')'),
]:
    check(f'precedence: {src}', P(src), want)
n = jsl.parse_expr('1 <= a < 3')
check('a < b <= c is one range check, as JSL evaluates it', (n.kind, n.value, len(n.args)), ('cmp', ['<=', '<'], 3))
n = jsl.parse_expr('(1 <= a) < 3')
check('(a < b) < c: two comparisons', (n.kind, n.args[0].kind, n.args[0].extra.get('paren')), ('cmp', 'cmp', True))
n = jsl.parse_expr('For(i = 1, i <= 3, i++, s += i;)')
check('For() with its four arguments and a ";" before the ")"', (len(n.args), n.args[3].kind), (4, 'assign'))

# ---- names
keys = {jsl.parse_expr(s).key for s in ['N Rows(dt)', 'NRows(dt)', 'nrows(dt)', 'N  rows (dt)', 'n Rows\t(dt)']}
check('a name is one whatever its case and whitespace: N Rows, NRows, nrows', keys, {'nrows'})
check('a name followed by ( is a call; without, a name', (jsl.parse_expr('Pi()').kind, jsl.parse_expr('Pi').kind), ('call', 'name'))
check('names with digits and spaces: Column 1', jsl.parse_expr('Column 1 = 3').args[0].value, 'Column 1')
check('names with apostrophes and non-ASCII letters: Spearman\'s ρ', jsl.parse_expr("Spearman's ρ(1)").key, "spearman'sρ")
check('names with percent signs: Col %', jsl.parse_expr('Col %(1)').key, 'col%')
check('a superscript in a name: T²', jsl.parse_expr('T²(1)').key, 't²')
n = jsl.parse_expr('"odd name!"n')
check('"text"n is a name', (n.kind, n.value, n.extra['quoted']), ('name', 'odd name!', True))
n = jsl.parse_expr('Name("a-b") = 1')
check('Name("text") is a name', (n.args[0].kind, n.args[0].value), ('name', 'a-b'))
prog = jsl.parse('a = 1\nb = 2;')
check('a missing ";" at a line end: two statements, and a warning on the second line', ([jsl.dump(s) for s in prog.statements], [(p.line, p.severity) for p in prog.problems]), (['(a = 1)', '(b = 2)'], [(2, 'warn')]))

# ---- numbers, the missing value, dates
for src, want, t in [('1', 1, int), ('1.5', 1.5, float), ('.5', 0.5, float), ('1e3', 1000.0, float), ('5.', 5.0, float), ('1.5e-3', 0.0015, float), ('2E+2', 200.0, float)]:
    v = jsl.parse_expr(src).value
    check(f'the number {src}', (v, type(v)), (want, t))
check('"." is the missing value', jsl.parse_expr('.').kind, 'missing')
check('"." in a list and after ==', (P('{1, .}'), P('x == .')), ('{1, .}', '(x == .)'))
check('01Jan1904 is 0: JMP\'s origin of date-times', jsl.parse_expr('01Jan1904').value, 0.0)
secs = (datetime.datetime(2003, 2, 12) - datetime.datetime(1904, 1, 1)).total_seconds()
check('a date literal (12Feb2003) in seconds since 1904', jsl.parse_expr('12Feb2003').value, secs)
check('a one-digit day and a lower-case month (5oct1998)', jsl.parse_expr('5oct1998').value, (datetime.datetime(1998, 10, 5) - datetime.datetime(1904, 1, 1)).total_seconds())
check('a date-time literal: 01Jan2020:12:30:00', jsl.parse_expr('01Jan2020:12:30:00').value, (datetime.datetime(2020, 1, 1, 12, 30) - datetime.datetime(1904, 1, 1)).total_seconds())

# ---- strings
for src, want in [('"a\\!tb"', 'a\tb'), ('"line\\!Nnext"', 'line\nnext'), ('"q\\!"uote"', 'q"uote'), ('"back\\!\\slash"', 'back\\slash'),
                  ('"C:\\temp\\x"', 'C:\\temp\\x'), ('"\\!U00E9t\\!U00E9"', 'été'), ('"cr\\!r"', 'cr\r'), ('"nul\\!0"', 'nul\0'),
                  ('"\\[He said "hi" \\!n here]\\"', 'He said "hi" \\!n here'), ('"two\nlines"', 'two\nlines'), ('""', '')]:
    check(f'the string {src!r}', jsl.parse_expr(src).value, want)

# ---- comments
prog = jsl.parse('x = 1; // one\ny = 2; /* two\nlines */ z = 3;\n/* inline */ w = /* here */ 4;')
check('comments are skipped, wherever they are', [jsl.dump(s) for s in prog.statements], ['(x = 1)', '(y = 2)', '(z = 3)', '(w = 4)'])
check('... and kept for the Python, with their lines', [(c[0], c[1]) for c in prog.comments], [(1, 'one'), (2, 'two'), (3, 'lines'), (4, 'inline'), (4, 'here')])
check('a // inside a string is text', jsl.parse_expr('"http://x"').value, 'http://x')

# ---- lists, matrices, associative arrays
check('a list, nested', P('{1, "a", {2}}'), "{1, 'a', {2}}")
n = jsl.parse_expr('[1 2 3, 4 5 6]')
check('a matrix: rows by ",", items by spaces', (n.kind, n.value), ('matrix', [[1, 2, 3], [4, 5, 6]]))
check('[1, 2, 3] is a column', jsl.parse_expr('[1, 2, 3]').value, [[1], [2], [3]])
check('[] is the empty matrix', jsl.parse_expr('[]').value, [])
check('negative, fractional and missing items', jsl.parse_expr('[-1 .5 .]').value, [[-1, 0.5, None]])
n = jsl.parse_expr('["a" => 1, "b" => {2}, => 0]')
check('an associative array with a default value', (n.kind, len(n.args), jsl.dump(n.extra['default'])), ('assoc', 2, '0'))
check('the empty associative array [=>]', (jsl.parse_expr('[=>]').kind, jsl.parse_expr('[=>]').args), ('assoc', []))
check('a matrix literal holds numbers only (Matrix() takes expressions)', 'numbers only' in (jsl.parse('m = [a b];').problems[0].text), True)

# ---- columns and scopes
for src, want in [(':x', ':x'), (':Name("odd name")', ':odd name'), (':"odd name"n', ':odd name'), ('dt:x', '(dt:x)'), ('dt:Name("a b")', '(dt:a b)'),
                  ('::g', '::g'), ('here:x', '(here:x)'), ('Column(dt, "x")', "Column(dt, 'x')"), ('As Column("x")', "As Column('x')"),
                  (':x << Set Name("y")', "(:x << Set Name('y'))"), ('Data Table("T"):x', "(Data Table('T'):x)")]:
    check(f'column references and scopes: {src}', P(src), want)
n = jsl.parse_expr('New Column("x", <<Set Each Value(1))')
check('a message given as an argument: <<Set Each Value(1)', (n.args[1].kind, n.args[1].args[0].kind, n.args[1].args[1].key), ('send', 'empty', 'seteachvalue'))

# ---- recovery from syntax errors
prog = jsl.parse('x = 1;\ny = 2 +* 3;\nz = 4;')
check('a bad statement is skipped, the rest read', [jsl.dump(s) for s in prog.statements], ['(x = 1)', '(z = 4)'])
check('... and reported on its line', [(p.line, p.severity) for p in prog.problems], [(2, 'error')])
prog = jsl.parse('Show( x ;\ny = 2;\nz = 3;')
check('an unclosed call: the statements after it are read', [jsl.dump(s) for s in prog.statements], ['(y = 2)', '(z = 3)'])
check('... and the error is on the line where the statement began', [p.line for p in prog.problems], [1])
prog = jsl.parse('x = "abc;\ny = 2;')
check('an unclosed string ends at its line, and the next line is read', ([jsl.dump(s) for s in prog.statements][-1], prog.problems[0].line), ('(y = 2)', 1))
prog = jsl.parse('a = 1;\nb = f(1 2);\nc = 3;')
check('two items without a ",": an error on that line', ([p.line for p in prog.problems], len(prog.statements)), ([2], 2))
check('nothing to read at all: not ok', jsl.parse(')))').ok, False)
check('an empty script is ok', (jsl.parse('').ok, jsl.parse('// only a comment').ok), (True, True))
check('line numbers are kept on the nodes', [s.line for s in jsl.parse('a = 1;\n\nb = 2;\nc = 3;').statements], [1, 3, 4])

# ==========================================================================================================
# the translation, run
# ==========================================================================================================

# ---- arithmetic, comparisons, logic
r = conv('a = 2 + 3 * 4 ^ 2 / 8; b = -2 ^ 2; c = 7 / 2; d = Mod( -7, 3 ); e = Round( 2.5 ); f = Round( -2.5 ); g = 1 <= 2 < 3; h = 1 < 2 < 2;'
         ' i = !(1 > 2); j = 1 == 1 & 2 == 3 | 4 == 4; k = Round( 3.14159, 2 ); l = Floor( -1.5 ); m = Ceiling( 1.2 ); n = Abs( -3 ); o = Root( 27, 3 );'
         ' p = Log( 8, 2 ); q = Exp( 0 ); r = Power( 3 ); s = Minus( 4 ); t = Sqrt( 16 );')
ns = run(r)
check('2 + 3 * 4 ^ 2 / 8 is 8', ns['a'], 8.0)
check('-2 ^ 2 is -4 (power first)', ns['b'], -4)
check('7 / 2 is 3.5', ns['c'], 3.5)
check('Mod(-7, 3) is -1, the sign of the dividend', ns['d'], -1.0)
check('Round(2.5) is 3 and Round(-2.5) is -3: halves away from zero', (ns['e'], ns['f']), (3.0, -3.0))
check('1 <= 2 < 3 is true, 1 < 2 < 2 false: range checks', (bool(ns['g']), bool(ns['h'])), (True, False))
check('!, & and |', (ns['i'], ns['j']), (True, True))
check('Round(3.14159, 2), Floor(-1.5), Ceiling(1.2), Abs(-3)', (ns['k'], ns['l'], ns['m'], ns['n']), (3.14, -2.0, 2.0, 3))
check.near('Root(27, 3)', float(ns['o']), 3.0, 1e-12)
check('Log(8, 2), Exp(0), Power(3) (squared), Minus(4), Sqrt(16)', (float(ns['p']), float(ns['q']), ns['r'], ns['s'], float(ns['t'])), (3.0, 1.0, 9, -4, 4.0))

# ---- missing values
r = conv('x = .; a = Is Missing( x ); b = Is Missing( 3 ); c = x + 1; d = Sum( 1, . ); e = Mean( 2, ., 4 ); f = Max( 1, ., 3 ); g = N Missing( 1, ., . ); h = x == .; s = ""; t = Is Missing( s );')
ns = run(r)
check('"." is np.nan, Is Missing is pd.isna', (bool(ns['a']), bool(ns['b'])), (True, False))
check('arithmetic with a missing value is missing', math.isnan(ns['c']), True)
check('Sum, Mean and Max skip missing values', (float(ns['d']), float(ns['e']), float(ns['f'])), (1.0, 3.0, 3.0))
check('N Missing counts them', ns['g'], 2)
check('x == . tests for a missing value', bool(ns['h']), True)
check('an empty string is a missing string', bool(ns['t']), True)

# ---- strings
r = conv('s = "Hello World"; a = Substr( s, 7, 5 ); b = Length( s ); c = Uppercase( s ); d = Lowercase( s ); e = s || "!"; f = Word( 2, s ); g = Word( -1, "a b  c" );'
         ' h = Words( "a  b c" ); i = Contains( s, "World" ); j = Contains( s, "xyz" ); k = Starts With( s, "Hell" ); l = Ends With( s, "d" );'
         ' m = Substitute( "a-b-c", "-", "+" ); n = Trim( "  pad  " ); o = Trim( "  pad  ", "Left" ); p = Concat Items( {"x", "y", "z"}, "," );'
         ' q = Repeat( "ab", 3 ); r = Left( s, 5 ); t = Right( s, 5 ); u = Titlecase( "the quick fox" ); v = Item( 2, "a,,b", "," ); w = Word( 2, "a,,b", "," );'
         ' x = Munger( "abcdef", 1, "cd" ); y = Munger( "abcdef", 2, 3 ); z = Munger( "abcdef", 1, "cd", "XY" ); aa = Regex( "abc123def", "[0-9]+" );'
         ' bb = Regex( "John Smith", "(\\w+) (\\w+)", "\\2, \\1" ); cc = Regex( "a1b2", "[0-9]", "#", GLOBALREPLACE ); dd = Collapse Whitespace( "  a   b  " );'
         ' ee = Substr( s, 3 ); ff = Reverse( "abc" ); gg = Num( "12.5" ) + 1; hh = Num( "x" ); ii = Contains( {"p", "q"}, "q" ); jj = Char( 42 ); kk = Char( 1 / 4 );'
         ' ll = Char( 3.14159, 5, 2 ); mm = Char( 1e20 ); nn = Char( . ); oo = Hex( 255, "integer" ); pp = Regex Match( "k=v", "(\\w)=(\\w)" );')
ns = run(r)
for k, want in [('a', 'World'), ('b', 11), ('c', 'HELLO WORLD'), ('d', 'hello world'), ('e', 'Hello World!'), ('f', 'World'), ('g', 'c'),
                ('h', ['a', 'b', 'c']), ('i', 7), ('j', 0), ('k', True), ('l', True), ('m', 'a+b+c'), ('n', 'pad'), ('o', 'pad  '), ('p', 'x,y,z'),
                ('q', 'ababab'), ('r', 'Hello'), ('t', 'World'), ('u', 'The Quick Fox'), ('v', ''), ('w', 'b'), ('x', 3), ('y', 'bcd'),
                ('z', 'abXYef'), ('aa', '123'), ('bb', 'Smith, John'), ('cc', 'a#b#'), ('dd', 'a b'), ('ee', 'llo World'), ('ff', 'cba'),
                ('gg', 13.5), ('ii', 2), ('jj', '42'), ('kk', '0.25'), ('ll', '3.14'), ('mm', '1e+20'), ('nn', '.'), ('oo', 'FF'), ('pp', ['k=v', 'k', 'v'])]:
    check(f'string function: {k}', ns[k], want)
check('Num() of text that is no number is missing', math.isnan(ns['hh']), True)
r = conv('n = 3; name = "x"; t = Eval Insert( "n is ^n^, name is ^name^, half is ^n / 2^" );')
check('Eval Insert() as an f-string', run(r)['t'], 'n is 3, name is x, half is 1.5')
r = conv('n = 2; a = Eval Insert( "^If( n > 1, \\!"many\\!", \\!"one\\!" )^ of ^Char( n ) || \\!"!\\!"^" );'
         ' aa = ["k" => 7]; b = Eval Insert( "k=^aa[\\!"k\\!"]^ {kept}" ); c = Eval Insert( "^\\!"x\\!ty\\!"^|^n^" ); d = Eval Insert( "^\\!"it\'s\\!"^ ^\\!"\\!\\\\!"^" );')
ns = run(r)
check('Eval Insert() with strings in its expressions', (ns['a'], ns['b']), ('many of 2!', 'k=7 {kept}'))
check('... a tab and a quote of each kind in them', (ns['c'], ns['d']), ('x\ty|2', "it's \\"))
r = conv('a = Format( Num( "1234.5" ), "Fixed Dec", 10, 2 ); b = Format( Num( "0.125" ), "Percent", 8, 1 ); c = Format( 12345.678, "Fixed Dec", 12, 1, "Use thousands separator" );'
         ' d = Format( 0.00002, "PValue" ); e = Format( 0.0432, "PValue" ); f = Format( 3600000000, "yyyy-mm-dd" ); g = Format( 01Aug2021, "yyyyQq" );'
         ' h = Char( ["b" => 2, "a" => "x"] ); i = Char( Associative Array() ); j = Char( {["k" => 1], 2, "t"} );')
ns = run(r)
check('Format(): Fixed Dec, Percent, thousands', (ns['a'], ns['b'], ns['c']), ('1234.50', '12.5%', '12,345.7'))
check('Format(): PValue', (ns['d'], ns['e']), ('<.0001', '0.0432'))
check('Format() of a number of seconds as a date, and a quarter', (ns['f'], ns['g']), ('2018-01-28', '2021Q3'))
check('Char() of associative arrays, keys in order, and of a list that holds one', (ns['h'], ns['i'], ns['j']), ('["a" => "x", "b" => 2]', '[=>]', '{["k" => 1], 2, "t"}'))

# ---- lists
r = conv('lst = {10, 20, 30}; a = lst[1]; b = lst[N Items( lst )]; lst[2] = 25; Insert Into( lst, 40 ); Insert Into( lst, 5, 1 ); Remove From( lst, 2 ); c = N Items( lst );'
         ' d = Reverse( {1, 2, 3} ); e = Sort List( {"b", "c", "a"} ); f = Loc( {"a", "b", "a"}, "a" ); {lo, hi} = {1, 2}; g = lst[{1, 2}];'
         ' h = Insert( {1, 2}, 9, 2 ); i = Remove( {1, 2, 3}, 2 ); j = {1, 2} || {3}; k = Shift( {1, 2, 3} ); Reverse Into( d ); Sort List Into( e );')
ns = run(r)
check('list subscripts count from 1', (ns['a'], ns['b']), (10, 30))
check('assignment into a list, Insert Into (at the end and at a place), Remove From', (ns['lst'], ns['c']), ([5, 25, 30, 40], 4))
check('Reverse, Sort List, Loc', (ns['d'], ns['e'], ns['f']), ([1, 2, 3], ['a', 'b', 'c'], [1, 3]))
check('{a, b} = {1, 2}', (ns['lo'], ns['hi']), (1, 2))
check('a list of subscripts', ns['g'], [5, 25])
check('Insert, Remove (copies), || of lists, Shift', (ns['h'], ns['i'], ns['j'], ns['k']), ([1, 9, 2], [1, 3], [1, 2, 3], [2, 3, 1]))

# ---- associative arrays
r = conv('aa = ["b" => 2, "a" => 1]; aa["c"] = 3; k = aa << Get Keys; v = aa << Get Values; n = N Items( aa ); has = aa << Contains( "a" ); c2 = Contains( aa, "zz" );'
         ' aa << Remove( "b" ); k2 = aa << Get Keys; dd = [=> 0]; dd["x"] += 1; x = dd["x"]; y = dd["nope"]; e = Associative Array( {"p", "q"}, {1, 2} );')
ns = run(r)
check('keys in JMP\'s (sorted) order, and their values', (ns['k'], ns['v']), (['a', 'b', 'c'], [1, 2, 3]))
check('N Items, Contains, << Remove', (ns['n'], ns['has'], ns['c2'], ns['k2']), (3, True, 0, ['a', 'c']))
check('a default value', (ns['x'], ns['y']), (1, 0))
check('Associative Array(keys, values)', ns['e'], {'p': 1, 'q': 2})

# ---- matrices
r = conv('A = [1 2, 3 4]; v = [5, 6]; p = A * v; t = A`; i = Inv( A ); j = J( 2, 3, 7 ); Id = Identity( 2 ); e = A[2, 1]; c = A[0, 2]; rw = A[1, 0]; lin = A[3];'
         ' s = V Sum( A ); em = A :* A; h = A || v; vv = [1 2] |/ [3 4]; ix = 1::4; d = Det( A ); tr = Trace( A ); n = N Rows( j ); nc = N Cols( j );'
         ' m = Mean( A ); tot = Sum( A ); mx = Max( A ); z = J( 2, 2, 0 ); z[1, 2] = 9; ls = As List( [1, 2, 3] ); sh = Shape( [1 2 3 4], 2, 2 ); B = A * A;')
ns = run(r)
Am = np.array([[1, 2], [3, 4]])
check('JSL\'s * of two matrices is the matrix product', near(ns['p'], Am @ np.array([[5], [6]])), True)
check('A * A is the matrix product, not element by element', near(ns['B'], Am @ Am), True)
check('transpose, inverse, J, Identity', (near(ns['t'], Am.T), near(ns['i'], np.linalg.inv(Am)), near(ns['j'], np.full((2, 3), 7)), near(ns["Id"], np.eye(2))), (True, True, True, True))
check('A[2, 1] counts from 1', ns['e'], 3)
check('A[0, 2]: every row of the second column, a column', near(ns['c'], np.array([[2], [4]])), True)
check('A[1, 0]: every column of the first row, a row', near(ns['rw'], np.array([[1, 2]])), True)
check('A[3]: the third element, row by row', ns['lin'], 3)
check('V Sum: a row of column sums', near(ns['s'], np.array([[4, 6]])), True)
check(':* multiplies element by element', near(ns['em'], Am * Am), True)
check('|| joins side by side, |/ one above the other', (near(ns['h'], np.hstack([Am, [[5], [6]]])), near(ns['vv'], np.array([[1, 2], [3, 4]]))), (True, True))
check('1::4 is 1 to 4', list(ns['ix']), [1, 2, 3, 4])
check.near('Det', float(ns['d']), -2.0, 1e-12)
check('Trace, N Rows, N Cols', (ns['tr'], ns['n'], ns['nc']), (5, 2, 3))
check('Mean, Sum, Max of a matrix', (float(ns['m']), float(ns["tot"]), float(ns['mx'])), (2.5, 10.0, 4.0))
check('assignment into a matrix', near(ns['z'], np.array([[0, 9], [0, 0]])), True)
check('As List, Shape', (ns['ls'], near(ns['sh'], np.array([[1, 2], [3, 4]]))), ([1, 2, 3], True))
r = conv('f = Function( {x}, x * [1 2] );')
check('* of a matrix and something not known: kept, with a note', has_note(r, 1, 'matrix product'), True)

# ---- control flow
r = conv('s = 0; For( i = 1, i <= 10, i++, s += i ); p = 1; For( i = 1, i <= 6, i++, p *= i ); c = 0; For( j = 10, j > 0, j -= 3, c++ );'
         ' w = 0; While( w < 7, w += 2 ); odd = 0; For( k = 1, k <= 10, k++, If( Mod( k, 2 ) == 0, Continue() ); odd += k );'
         ' firstbig = 0; For( k = 1, k <= 100, k++, If( k * k > 50, firstbig = k; Break() ) ); sq = 0; For( q = 1, q * q <= 50, q++, If( q == 3, Continue() ); sq += q );'
         ' mm = 0; For( a = 1, a <= 3, a++, For( b = 1, b <= a, b++, mm += a * b ) ); fl = 0; For( x = 0, x < 1, x += 0.25, fl++ );')
ns = run(r)
check('For() as range(): 1 + ... + 10 and 6!', (ns['s'], ns['p']), (55, 720))
check('For() counting down by 3', ns['c'], 4)
check('While()', ns['w'], 8)
check('Continue() and Break()', (ns['odd'], ns['firstbig']), (25, 8))
check('a For() that is no counting loop: a while loop, and Continue() still runs the increment', ns['sq'], 1 + 2 + 4 + 5 + 6 + 7)
check('nested loops', ns['mm'], sum(a * b for a in range(1, 4) for b in range(1, a + 1)))
check('a fractional step: a while loop', ns['fl'], 4)
check('the counting loop is written as range()', 'for i in range(1, 11):' in r['python'], True)
r = conv('lst = {3, 4, 5}; t = 0; For( i = 1, i <= N Items( lst ), i++, t += lst[i] );')
check('a counter used only as a subscript counts from 0', ('for i in range(len(lst)):' in r['python'], run(r)['t']), (True, 12))
r = conv('lst = {3, 4, 5}; t = 0; For( i = 1, i <= N Items( lst ), i++, t += lst[i] * i );')
check('... not when it is used as a number too', ('range(1, len(lst) + 1)' in r['python'], run(r)['t']), (True, 3 + 8 + 15))
r = conv('lst = {1, 2}; n = 0; For( i = 1, i <= N Items( lst ), i++, If( i == 1, Insert Into( lst, 3 ) ); n++ );')
check('a loop whose bound changes in its body is a while loop', ('while' in r['python'], run(r)['n']), (True, 3))

r = conv('x = 5; If( x > 3, y = "big", x > 1, y = "mid", y = "small" ); z = If( x > 10, 1 ); m = Match( x, 1, "one", 5, "five", "other" ); c = Choose( 2, "a", "b", "c" );'
         ' mm = Match( "q", "p", 1, 2 ); Match( x, 5, w = 50, w = 0 ); v = If( x > 3, t = 1; t + 1, 0 );')
ns = run(r)
check('If() as a statement: if/elif/else', ns['y'], 'big')
check('If() with no else is missing', math.isnan(ns['z']), True)
check('Match() and Choose() as values', (ns['m'], ns['c'], ns['mm']), ('five', 'b', 2))
check('Match() as a statement', ns['w'], 50)
check('If() with statements in a branch, assigned', ns['v'], 2)

r = conv('lst = {"b", "a"}; out = ""; For Each( {v}, lst, out ||= v ); idx = 0; For Each( {v, i}, lst, idx += i ); aa = ["y" => 2, "x" => 1]; ks = "";'
         ' For Each( {{k, v}}, aa, ks ||= k || Char( v ) ); tot = 0; For Each( {e}, [1 2, 3 4], tot += e ); r = 0; For Each( {i}, 1::4, r += i );'
         ' z = {}; For Each( {{a, b}}, Across( {1, 2}, {3, 4} ), Insert Into( z, a * b ) );')
ns = run(r)
check('For Each over a list, with its index', (ns['out'], ns['idx']), ('ba', 3))
check('For Each over an associative array, in key order', ns['ks'], 'x1y2')
check('For Each over a matrix and over 1::4', (ns['tot'], ns['r']), (10, 10))
check('For Each over Across() of two lists', ns['z'], [3, 8])
r = conv('a = Transform Each( {v}, {1, 2, 3}, v * 10 ); b = Filter Each( {v}, {5, 15, 25}, v > 10 ); c = Filter Each( {v, i}, {7, 8, 9}, i != 2 );')
ns = run(r)
check('Transform Each and Filter Each as comprehensions', (ns['a'], ns['b'], ns['c']), ([10, 20, 30], [15, 25], [7, 9]))

# ---- functions
r = conv('f = Function( {a, b = 2}, a * b ); x = f( 3 ); y = f( 3, 4 ); g = Function( {n}, If( n <= 1, 1, n * Recurse( n - 1 ) ) ); z = g( 5 );'
         ' count = 0; bump = Function( {}, count = count + 1 ); bump(); bump(); h = Function( {a}, {Default Local}, count = 100; a ); h( 1 );'
         ' two = Function( {a, b}, Return( a - b, a + b ) ); {lo, hi} = two( 10, 1 ); sq = Function( {v}, {t = 0}, t = v * v; t ); s = sq( 4 );'
         ' k = Function( {x}, If( x > 0, "pos", "neg" ) ); p = k( 2 ); q = k( -2 ); dbl = Function( {x}, x * 2 ); lst = Transform Each( {v}, {1, 2}, dbl( v ) );')
ns = run(r)
check('a function, with an optional argument', (ns['x'], ns['y']), (6, 12))
check('Recurse()', ns['z'], 120)
check('a function sets a name of the script (JSL has no locals unless declared)', ns['count'], 2)
check('... and not with {Default Local}', 'global count' in r['python'], True)
check('Return() of two values, taken apart', (ns['lo'], ns['hi']), (9, 11))
check('locals with a value, and the last value returned', ns['s'], 16)
check('an If() at the end of a function returns its branch', (ns['p'], ns['q']), ('pos', 'neg'))
check('a function called in a comprehension', ns['lst'], [2, 4])

r = conv('r = "none"; Try( Throw( "oops" ), r = "caught" ); t = 0; Try( t = 1, t = 2 ); Try( x = 1 / 0, msg = Char( exception_msg ) );')
ns = run(r)
check('Try() and Throw()', (ns['r'], ns['t']), ('caught', 1))
check('exception_msg is the Python exception here', 'division' in ns['msg'], True)
check('Try(): a note on how the catch differs', has_note(r, 1, 'Try()', 'info'), True)

# ---- output
r = conv('x = 3; Show( x, x + 1, "text" ); Print( "p", 2 ); Write( "w1", " w2\\!n" ); Write( "no newline" ); Show( {1, "a"} );')
out = run(r)['__out__'].splitlines()
check('Show() prints name = value; a string as itself', out[:3], ['x = 3', 'x + 1 = 4', '"text"'])
check('Print() prints each value', out[3:5], ['p', '2'])
check('Write() writes without quotes, a \\!n ends the line', out[5], 'w1 w2')
check('Write() without a line end', out[6].startswith('no newline'), True)

# ---- dates
r = conv('d = Date DMY( 15, 3, 2021 ); y = Year( d ); m = Month( d ); dd = Day( d ); dw = Day Of Week( d ); doy = Day Of Year( d ); q = Quarter( d );'
         ' d2 = d + In Days( 10 ); gap = Date Difference( 01Jan2021, d, "day" ); mon = Date Difference( 20Jan2021, 01Mar2021, "month" );'
         ' mact = Date Difference( 20Jan2021, 01Mar2021, "month", "actual" ); inc = Date Increment( d, "month", 2 ); inca = Date Increment( d, "month", 2, "actual" ); f = Format( d, "m/d/y" );'
         ' f2 = Format( d, "yyyy-mm-dd" ); secs = (d2 - d) / In Hours( 1 ); md = Date MDY( 12, 31, 1999 ); wk = Week Of Year( 04Jan2021, 3 );'
         ' dt1 = 01Jan2020:06:30:00; hr = Hour( dt1 ); mi = Minute( dt1 ); tod = Time Of Day( dt1 ); pl = d + 86400; sn = Short Date( d );')
ns = run(r)
check('Date DMY, Year, Month, Day', (ns['y'], ns['m'], ns['dd']), (2021, 3, 15))
check('Day Of Week: Sunday is 1 (15 March 2021 was a Monday)', ns['dw'], 2)
check('Day Of Year, Quarter', (ns['doy'], ns['q']), (74, 1))
check('a date plus In Days()', ns['d2'], pd.Timestamp(2021, 3, 25))
check('Date Difference in days', ns['gap'], 73.0)
check('Date Difference in months: boundaries crossed, and whole months', (ns['mon'], ns['mact']), (2.0, 1.0))
check('Date Increment by two months, from the start of the month (JSL\'s "Start")', ns['inc'], pd.Timestamp(2021, 5, 1))
check('... and from the date itself ("Actual")', ns['inca'], pd.Timestamp(2021, 5, 15))
check('Format with JMP\'s date formats', (ns['f'], ns['f2'], ns['sn']), ('03/15/2021', '2021-03-15', '03/15/2021'))
check('a difference of dates over In Hours()', ns['secs'], 240.0)
check('Date MDY', ns['md'], pd.Timestamp(1999, 12, 31))
check('Week Of Year, ISO', ns['wk'], 1)
check('Hour, Minute, Time Of Day of a date-time literal', (ns['hr'], ns['mi'], ns['tod']), (6, 30, 23400.0))
check('seconds added to a date', ns['pl'], pd.Timestamp(2021, 3, 16))
check('a note that dates are Timestamps here', has_note(r, 1, 'Timestamps', 'info'), True)

# ---- random numbers
r = conv('Random Reset( 7 ); a = Random Uniform(); b = Random Normal( 10, 2 ); Random Reset( 7 ); c = Random Uniform(); k = Random Integer( 3 ); m = Random Uniform( 5, 6 );')
ns = run(r)
g = np.random.default_rng(7)
check('Random Reset() seeds numpy\'s generator: the same draws again', (ns['a'], ns['c']), (g.uniform(), ns['a']))
check('Random Integer(n) is 1 to n; Random Uniform(a, b) in [a, b)', (1 <= ns['k'] <= 3, 5 <= ns['m'] < 6), (True, True))
check('a note that the streams are not JMP\'s', has_note(r, 1, 'streams differ', 'info'), True)

# ==========================================================================================================
# data tables, run on Students.csv
# ==========================================================================================================
r = conv('dt = Open( "$SAMPLE_DATA/Students.jmp" ); n = N Rows( dt ); k = N Cols( dt ); nm = dt << Get Name; cols = dt << Get Column Names( String );')
ns = run(r)
check('Open() of a .jmp the page has: its CSV, as the page\'s code reads it', 'pd.read_csv("Students.csv", float_precision="round_trip"' in r['python'], True)
check('N Rows, N Cols, Get Name, Get Column Names', (ns['n'], ns['k'], ns['nm'], ns['cols']), (12, 5, 'Students', list(STUDENTS.columns)))
r = conv('dt = Open( "students.JMP" );')
check('the table is found by its name without the extension, whatever its case', 'Students.csv' in r['python'], True)
r = conv('dt = Open( "/data/Other Table.jmp" );')
check('a .jmp the page has not: its CSV, and a warning', ('"Other Table.csv"' in r['python'], has_note(r, 1, 'no table', 'warn')), (True, True))
r = conv('a = Open( "x.csv" ); b = Open( "y.xlsx" ); c = Open( "z.txt" );')
check('other files: read_csv, read_excel, a text file with its delimiter found', ('pd.read_csv("x.csv")' in r['python'], 'pd.read_excel("y.xlsx")' in r['python'], 'sep=None' in r['python']), (True, True, True))

# ---- formula columns, against the same arithmetic done here
r = conv('dt = Current Data Table();'
         ' dt << New Column( "bmi", Numeric, Formula( :weight / :height ^ 2 * 703 ) );'
         ' dt << New Column( "size", Character, Formula( If( :height > 62, "tall", :height > 56, "medium", "short" ) ) );'
         ' dt << New Column( "gmean", Formula( Col Mean( :height, :sex ) ) );'
         ' dt << New Column( "cmean", Formula( Col Mean( :height ) ) );'
         ' dt << New Column( "gmax", Formula( Col Maximum( :weight, :sex ) ) );'
         ' dt << New Column( "gn", Formula( Col Number( :weight, :sex ) ) );'
         ' dt << New Column( "z", Formula( Col Standardize( :height ) ) );'
         ' dt << New Column( "rk", Formula( Col Rank( :height ) ) );'
         ' dt << New Column( "cs", Formula( Col Cumulative Sum( :height, :sex ) ) );'
         ' dt << New Column( "lag", Formula( Lag( :height, 2 ) ) );'
         ' dt << New Column( "dif", Formula( Dif( :height ) ) );'
         ' dt << New Column( "prev", Formula( :height[Row() - 1] ) );'
         ' dt << New Column( "r", Formula( Row() ) );'
         ' dt << New Column( "run", Formula( If( Row() == 1, :height, :run[Row() - 1] + :height ) ) );'
         ' dt << New Column( "miss", Formula( Is Missing( :weight ) ) );'
         ' dt << New Column( "tot", Formula( Sum( :height, :weight ) ) );'
         ' dt << New Column( "mx", Formula( Max( :height, :weight ) ) );'
         ' dt << New Column( "lab", Character, Formula( Uppercase( Substr( :name, 2, 2 ) ) || "-" || :sex ) );'
         ' dt << New Column( "grp", Character, Formula( Match( :age, 12, "a", 13, "a", 14, "b", "c" ) ) );'
         ' dt << New Column( "big", Formula( :height > 60 & :sex == "M" ) );'
         ' dt << New Column( "log", Formula( Log( :weight ) ) );'
         ' dt << New Column( "ctn", Formula( Contains( :name, "1" ) ) );'
         ' dt << New Column( "q", Formula( Col Quantile( :height, 0.5 ) ) );')
ns = run(r)
d = ns['dt']
check('a formula of arithmetic: one vectorised assignment', 'dt["bmi"] = dt["weight"] / dt["height"] ** 2 * 703' in r['python'], True)
check('bmi', near(d['bmi'], W / H ** 2 * 703), True)
check('If() with three branches: np.select', d['size'].tolist(), ['tall' if h > 62 else 'medium' if h > 56 else 'short' for h in H])
gm = {s: np.mean([h for h, t in zip(H, SEX) if t == s]) for s in 'FM'}
check('Col Mean(:height, :sex): a groupby transform', near(d['gmean'], [gm[s] for s in SEX]), True)
check('Col Mean(:height)', near(d['cmean'], np.full(12, H.mean())), True)
gx = {s: np.nanmax([w for w, t in zip(W, SEX) if t == s]) for s in 'FM'}
check('Col Maximum by group, missing values skipped', near(d['gmax'], [gx[s] for s in SEX]), True)
check('Col Number by group counts the values there', d['gn'].tolist(), [6 if s == 'F' else 5 for s in SEX])
check('Col Standardize', near(d['z'], (H - H.mean()) / H.std(ddof=1)), True)
check('Col Rank', d['rk'].tolist(), [float(sorted(H).index(h) + 1) for h in H])
cs, acc = [], {'F': 0.0, 'M': 0.0}
for h, s in zip(H, SEX):
    acc[s] += h
    cs.append(acc[s])
check('Col Cumulative Sum by group', near(d['cs'], cs), True)
check('Lag(:height, 2) and Dif()', (near(d['lag'], [np.nan, np.nan] + list(H[:-2])), near(d['dif'], [np.nan] + list(np.diff(H)))), (True, True))
check(':height[Row() - 1] is Lag', near(d['prev'], [np.nan] + list(H[:-1])), True)
check('Row() counts from 1', d['r'].tolist(), list(range(1, 13)))
check('a formula that reads its own column (a running total) runs row by row', ('for row in range(len(dt)):' in r['python'], near(d['run'], np.cumsum(H))), (True, True))
check('Is Missing() of a column', d['miss'].tolist(), [bool(np.isnan(w)) for w in W])
check('Sum() and Max() across columns skip the missing value', (near(d['tot'], [h + (0 if np.isnan(w) else w) for h, w in zip(H, W)]), near(d['mx'], np.fmax(H, W))), (True, True))
check('string functions on a column: .str', d['lab'].tolist(), [n[1:3].upper() + '-' + s for n, s in zip(STUDENTS['name'], SEX)])
check('Match() on a column: np.select', d['grp'].tolist(), ['a' if a in (12, 13) else 'b' if a == 14 else 'c' for a in AGE])
check('& between column comparisons', d['big'].tolist(), [bool(h > 60 and s == 'M') for h, s in zip(H, SEX)])
check('Log of a column with a missing value', near(d['log'], np.log(W)), True)
check('Contains() of a column: a position', d['ctn'].tolist(), [n.find('1') + 1 for n in STUDENTS['name']])
check('Col Quantile: JMP\'s definition (weibull)', near(d['q'], np.full(12, np.quantile(H, 0.5, method='weibull'))), True)
check('a note that formulas are computed once', has_note(r, 1, 'computed once', 'info'), True)
check('a note on missing conditions in np.where/np.select', has_note(r, 1, 'condition is missing', 'info'), True)

# ---- For Each Row
r = conv('dt = Current Data Table(); For Each Row( :height = :height * 2 ); For Each Row( If( :age > 15, :sex = "X" ) ); For Each Row( If( :weight > 100, :name = "heavy", :name = "light" ) );'
         ' s = 0; For Each Row( s += :height ); n = 0; For Each Row( If( :sex == "F", n++ ) );')
ns = run(r)
d = ns['dt']
check('For Each Row of one assignment: vectorised', ('dt["height"] = dt["height"] * 2' in r['python'], near(d['height'], H * 2)), (True, True))
check('For Each Row with If(): a .loc mask', ('dt.loc[dt["age"] > 15, "sex"] = "X"' in r['python'], d['sex'].tolist()), (True, ['X' if a > 15 else s for a, s in zip(AGE, SEX)]))
check('For Each Row with If() and else: np.where', d['name'].tolist(), ['heavy' if w > 100 else 'light' for w in W])
check('For Each Row that adds up: a loop over the rows', ns['s'], float((H * 2).sum()))
check('... and one that counts', ns['n'], sum(1 for a, s in zip(AGE, SEX) if s == 'F' and a <= 15))

# ---- column values, messages
r = conv('dt = Current Data Table(); h = :height << Get Values; nms = :name << Get Values; m = dt << Get As Matrix( {"height", "weight"} ); c = Column( dt, "age" ) << Get Values;'
         ' a = :height[3]; dt:weight[1] = 81; b = dt[2, "height"]; nm = :height << Get Name; mt = :age << Get Modeling Type; v = Col Mean( :height );'
         ' col = Column( "weight" ); wmax = Col Max( col );')
ns = run(r)
check('Get Values of a numeric column: a column matrix', (ns['h'].shape, near(ns['h'].ravel(), H)), ((12, 1), True))
check('Get Values of a character column: a list', ns['nms'], STUDENTS['name'].tolist())
check('Get As Matrix of two columns', ns['m'].shape, (12, 2))
check('Column(dt, "age") << Get Values', near(ns['c'].ravel(), AGE), True)
check(':height[3] and dt[2, "height"] count rows from 1', (ns['a'], ns['b']), (55.0, 59.0))
check('an assignment to a cell', ns['dt'].loc[0, 'weight'], 81.0)
check('Get Name, Get Modeling Type', (ns['nm'], ns['mt']), ('height', 'Ordinal'))
check('Col Mean outside a formula', ns['v'], H.mean())
check('a column held in a name', ns['wmax'], 150.0)

# ---- the table as a whole
r = conv('dt = Current Data Table(); dt << Add Rows( 2 ); n1 = N Rows( dt ); dt << Delete Rows( [13, 14] ); dt:height << Set Name( "ht" ); dt << Delete Columns( "name" );'
         ' :age << Set Modeling Type( "Nominal" ); dt << New Column( "one", Numeric, Set Each Value( 1 ) ); dt << New Column( "e", Character ); k = N Cols( dt );'
         ' Column( dt, "weight" ) << Set Data Type( "Character" ); dt << Save As( "out.jmp" );')
ns = run(r)
d = ns['dt']
check('Add Rows, then Delete Rows of them', (ns['n1'], len(d)), (14, 12))
check('Set Name, Delete Columns', (list(d.columns)[:4], 'name' in d.columns), (['sex', 'age', 'ht', 'weight'], False))
check('Set Modeling Type("Nominal"): a category', str(d['age'].dtype), 'category')
check('Set Each Value, an empty character column', (d['one'].tolist(), set(d['e'])), ([1] * 12, {''}))
check('Set Data Type("Character"): JMP\'s text of the numbers, missing as empty', (d['weight'][0], d['weight'][5]), ('80', ''))
check('Save As a .jmp: a CSV file, with a note', ('out.csv' in ns['__files__'], has_note(r, 1, 'CSV', 'info')), (True, True))

r = conv('dt = New Table( "T", Add Rows( 3 ), New Column( "x", Numeric, "Continuous", Set Values( [1, 2, 3] ) ), New Column( "g", Character, "Nominal", Set Values( {"a", "b", "a"} ) ),'
         ' New Column( "y", Formula( :x * 10 ) ), New Column( "e" ) ); n = N Rows( dt ); t2 = New Table( "Empty" ); t2 << New Column( "v", Set Values( [4, 5] ) );')
ns = run(r)
check('New Table: the columns and their values', (ns['dt']['x'].tolist(), ns['dt']['g'].tolist(), ns['dt']['y'].tolist(), bool(ns['dt']['e'].isna().all()), ns['n']), ([1, 2, 3], ['a', 'b', 'a'], [10, 20, 30], True, 3))
check('a column set on an empty table makes its rows', ns['t2']['v'].tolist(), [4, 5])

# ---- Summary, Subset, Sort, Stack, Split, Join, Concatenate, Transpose, Summarize
r = conv('dt = Current Data Table(); s = dt << Summary( Group( :sex ), Mean( :height ), Std Dev( :height ), Max( :weight ), N( :weight ) );'
         ' s0 = dt << Summary( Mean( :height ) ); fs = dt << Summary( Group( :sex, :age ), Sum( :weight ), Statistics Column Name Format( "column" ) );')
ns = run(r)
s = ns['s']
g = STUDENTS.groupby('sex')
check('Summary: JMP\'s columns', list(s.columns), ['sex', 'N Rows', 'Mean(height)', 'Std Dev(height)', 'Max(weight)', 'N(weight)'])
check('Summary: against a groupby', (s['N Rows'].tolist(), near(s['Mean(height)'], g['height'].mean()), near(s['Std Dev(height)'], g['height'].std()), s['N(weight)'].tolist()),
      ([6, 6], True, True, [6, 5]))
check('Summary without groups: one row', (len(ns['s0']), float(ns['s0']['Mean(height)'][0])), (1, H.mean()))
check('Summary of two groups, the statistics named by the column', (list(ns['fs'].columns), len(ns['fs'])), (['sex', 'age', 'N Rows', 'weight'], 12))

r = conv('dt = Current Data Table(); sub = dt << Subset( Rows( [1, 3, 5] ), Columns( :name, :height ) ); srt = dt << Sort( By( :height ), Order( Descending ) );'
         ' two = dt << Sort( By( :sex, :height ) ); dt << Select Where( :age >= 16 ); sel = dt << Subset( Selected Rows( 1 ) );'
         ' st = dt << Stack( Columns( :height, :weight ), Source Label Column( "Label" ), Stacked Data Column( "Data" ) );'
         ' sp = st << Split( Split By( :Label ), Split( :Data ), Group( :name ), Remaining Columns( Drop All ) );'
         ' tr = sub << Transpose( Columns( :height ), Label( :name ) ); dt << Sort( By( :age ), Order( Descending ), Replace Table );')
ns = run(r)
check('Subset of rows and columns', (ns['sub']['name'].tolist(), list(ns['sub'].columns)), (['S01', 'S03', 'S05'], ['name', 'height']))
check('Sort descending', near(ns['srt']['height'], np.sort(H)[::-1]), True)
check('Sort by two columns', ns['two']['name'].tolist(), STUDENTS.sort_values(['sex', 'height'])['name'].tolist())
check('Subset of the selected rows', ns['sel']['name'].tolist(), STUDENTS[STUDENTS['age'] >= 16]['name'].tolist())
st = ns['st']
check('Stack: row by row, as JMP stacks', (st['Label'][:4].tolist(), st['Data'][:2].tolist(), len(st)), (['height', 'weight', 'height', 'weight'], [51.5, 80.0], 24))
check('Split back', (list(ns['sp'].columns), near(ns['sp']['height'], H)), (['name', 'height', 'weight'], True))
check('Transpose with a label column', (list(ns['tr'].columns), ns['tr']['S03'].tolist()), (['Label', 'S01', 'S03', 'S05'], [55.0]))
check('Sort with Replace Table', ns['dt']['age'].tolist(), sorted(AGE.tolist(), reverse=True))

OTHER = pd.DataFrame({'name': ['S01', 'S02', 'S99'], 'club': ['chess', 'music', 'drama']})
r = conv('dt = Current Data Table(); o = Open( "Clubs.jmp" ); j = dt << Join( With( o ), By Matching Columns( :name = :name ), Include Nonmatches( 1, 0 ) );'
         ' ji = dt << Join( With( o ), By Matching Columns( :name = :name ) ); c = dt << Concatenate( dt, Create Source Column );',
         tables=TABLES + [{'name': 'Clubs', 'columns': [{'name': 'name', 'dataType': 'character', 'modelingType': 'nominal'}, {'name': 'club', 'dataType': 'character', 'modelingType': 'nominal'}]}])
ns = run(r, files={'Clubs': OTHER})
check('Join keeping the rows of the first table', (len(ns['j']), list(ns['j'].columns)), (12, list(STUDENTS.columns) + ['club']))
check('Join: the matches found', (ns['j']['club'][0], ns['j']['club'][1], pd.isna(ns['j']['club'][2])), ('chess', 'music', True))
check('Join of the matching rows only', ns['ji']['name'].tolist(), ['S01', 'S02'])
check('Concatenate with a source column', (len(ns['c']), list(ns['c'].columns)[0]), (24, 'Source Table'))

r = conv('dt = Current Data Table(); Summarize( dt, g = By( :sex ), c = Count, m = Mean( :height ), mx = Max( :weight ) ); Summarize( avg = Mean( :height ), n = Count );')
ns = run(r)
check('Summarize with By: the groups as strings, the statistics as columns', (ns['g'], ns['c'].ravel().tolist(), near(ns['m'].ravel(), g['height'].mean())), (['F', 'M'], [6, 6], True))
check('Summarize without By', (ns['avg'], ns['n']), (H.mean(), 12))

r = conv('dt = Current Data Table(); Tabulate( Add Table( Column Table( Analysis Columns( :height ), Statistics( Mean ) ), Row Table( Grouping Columns( :sex ) ) ) );')
ns = run(r)
check('Tabulate: straight to pandas', near(ns['tabulate'].to_numpy().ravel(), g['height'].mean()), True)

# ---- row states
r = conv('dt = Current Data Table(); dt << Select Where( :height > 62 ); ns = N Rows( dt << Get Selected Rows ); dt << Exclude; dt << Clear Select;'
         ' rows = dt << Get Rows Where( :sex == "M" & :age < 14 ); Distribution( Y( :height ) ); dt << Select Where( :age == 12 ) << Hide and Exclude;'
         ' dt << Select Where( :age > 16, Current Selection( "Extend" ) ); k = N Rows( dt << Get Selected Rows ); dt << Delete Rows;')
ns = run(r)
check('Select Where: a mask, Get Selected Rows its row numbers', ns['ns'], int((H > 62).sum()))
check('Exclude the selected rows (then Hide and Exclude toggles the age-12 rows, and Delete Rows drops the selection from the mask)',
      ns['excluded'].tolist(), [bool(((H[i] > 62) != (AGE[i] == 12))) for i in range(12) if not (AGE[i] == 12 or AGE[i] > 16)])
check('Get Rows Where: 1-based row numbers', ns['rows'].tolist(), [i + 1 for i in range(12) if SEX[i] == 'M' and AGE[i] < 14])
step = r['steps'][0]
check('an analysis after Exclude takes the rows left: where ~excluded', step['where'], '~excluded')
check('Current Selection("Extend")', ns['k'], int(((AGE == 12) | (AGE > 16)).sum()))
check('Delete Rows of the selection', len(ns['dt']), 12 - int(((AGE == 12) | (AGE > 16)).sum()))
check('a note on excluded rows', has_note(r, 1, 'excluded', 'info'), True)
r = conv('dt = Current Data Table(); For Each Row( Excluded( Row State() ) = :weight > 120 ); Oneway( Y( :height ), X( :sex ) );')
ns = run(r)
check('Excluded(Row State()) = ... in For Each Row: the mask', ns['excluded'].tolist(), [bool(w > 120) for w in W])
check('... and the analysis leaves those rows out', r['steps'][0]['where'], '~excluded')

# ==========================================================================================================
# platform launches: the page's steps
# ==========================================================================================================


def one_step(src, **kw):
    r = conv(src, **kw)
    return r, (r['steps'][0] if r['steps'] else None)


r, s = one_step('Distribution( Continuous Distribution( Column( :height ), Quantiles( 0 ), Normal Quantile Plot( 1 ), Test Mean( 60 ), Confidence Interval( 0.9 ), Fit Distribution( Normal ), Capability Analysis( LSL( 50 ), USL( 70 ) ) ),'
                ' Nominal Distribution( Column( :sex ), Mosaic Plot( 1 ), Order By( "Count Descending" ), Confidence Interval( 0.95 ) ), Stack( 1 ), By( :age ) );')
check('Distribution: platform, table, frame', (s['platform'], s['table'], s['frame']), ('distribution', 'Students', 'dt'))
check('Distribution: the columns of each part, and By', s['roles'], {'y': ['height', 'sex'], 'by': ['age']})
check('Distribution: options scoped by their column', {k: v for k, v in s['options'].items() if k.startswith('height|')},
      {'height|quantiles': False, 'height|qq': True, 'height|testMean': {'mu': 60, 'sigma': None}, 'height|ci': 0.9, 'height|fits': ['normal'], 'height|cap': {'lsl': 50, 'usl': 70, 'target': None}})
check('Distribution: a categorical column\'s options', {k: v for k, v in s['options'].items() if k.startswith('sex|')}, {'sex|mosaic': True, 'sex|order': 'desc', 'sex|ciCat': 0.95})
check('Distribution: the report\'s own options', s['options']['stack'], True)
check('the marker stands alone on its line, where the analysis goes', [ln for ln in r['python'].splitlines() if 'smui:p1' in ln], ['# <<smui:p1>>'])
check('the step\'s JSL is the launch as written', s['jsl'].startswith('Distribution( Continuous Distribution('), True)
r, s = one_step('Distribution( Y( :height, :weight ), Weight( :age ), Horizontal Layout( 1 ), Customize Summary Statistics( Variance( 1 ), N( 0 ) ), Fit Distribution( All ), Where( :sex == "F" ) );')
check('Distribution with Y() and Weight()', s['roles'], {'y': ['height', 'weight'], 'weight': ['age']})
check('options outside a column\'s part apply to every column', (s['options']['horizontal'], s['options']['fitAll']), (True, True))
check('Customize Summary Statistics', s['options']['stats'], ['mean', 'sd', 'se', 'upper', 'lower', 'var'])
check('Where(): the step\'s where and the page\'s filter', (s['where'], s['filter']), ('dt["sex"] == "F"', [{'col': 'sex', 'levels': ['F']}]))
check('the where is a boolean over the frame', int(eval(s['where'], {'dt': STUDENTS}).sum()), 6)

r, s = one_step('biv = Bivariate( Y( :weight ), X( :height ), Fit Line( {Confid Curves Fit( 1 ), Report( 0 )} ), Fit Polynomial( 3 ), Fit Spline( 0.5, Standardized ), Density Ellipse( 0.9 ),'
                ' Fit Mean, Kernel Smoother( 1, 1, 0.5 ), Fit Orthogonal( Equal Variances ), Nonpar Density, Histogram Borders( 1 ), Group By( :sex ) ); biv << Fit Robust;')
fits = s['options']['weight~height|fits']
check('Bivariate: the page\'s Bivariate Analysis, options scoped by the pair', (s['platform'], s['kind'], s['roles']), ('fitybyx', 'bivariate', {'y': ['weight'], 'x': ['height']}))
check('Bivariate: the fits in order', [f['kind'] for f in fits], ['line', 'poly', 'spline', 'ellipse', 'mean', 'lowess', 'orth', 'kde', 'robust'])
check('a fit\'s own options', (fits[0].get('cfit'), fits[0].get('report'), fits[1]['degree'], fits[2]['lam'], fits[2]['standardize'], fits[3]['p'], fits[6]['mode']),
      (True, False, 3, 0.5, True, 0.9, 'equal'))
check('Group By and Histogram Borders', (s['options']['weight~height|groupBy'], s['options']['weight~height|hist']), ('sex', True))
check('the columns named in options, for the page to find them', s['options']['__colNames'], {'weight': 'weight', 'height': 'height', 'sex': 'sex'})
check('a message to the analysis adds its option', has_note(r, 1, 'added to the analysis', 'info'), True)
check('Kernel Smoother: a note that the page draws LOWESS', has_note(r, 1, 'LOWESS', 'info'), True)

r, s = one_step('Oneway( Y( :height ), X( :sex ), Block( :age ), Means( 1 ), Means and Std Dev( 1 ), t Test( 1 ), Each Pair( 1 ), All Pairs( 1 ), With Control( 1, {"F"} ), UnEqual Variances( 1 ),'
                ' Wilcoxon Test( 1 ), Median Test( 1 ), Nonparametric Multiple Comparisons( Steel Dwass All Pairs( 1 ) ), Quantiles( 1 ), Box Plots( 0 ), Set α Level( 0.1 ), Compare Densities( 1 ) );')
o = s['options']
check('Oneway: roles with Block', s['roles'], {'y': ['height'], 'x': ['sex'], 'block': ['age']})
check('Means(1) is Means/Anova, with mean diamonds', (o['height~sex|anova'], o['height~sex|diamonds']), (True, True))
check('Means and Std Dev turns its lines on', [o[f'height~sex|{k}'] for k in ('meansd', 'meanLines', 'errorBars', 'sdLines')], [True] * 4)
check('the comparisons, with the control level', o['height~sex|compare'], [{'method': 'student', 'control': None}, {'method': 'tukey', 'control': None}, {'method': 'dunnett', 'control': 'F'}])
check('rank tests and their comparisons', (o['height~sex|np'], o['height~sex|npmc']), (['wilcoxon', 'median'], [{'method': 'steel_dwass', 'control': None}]))
check('t Test, Unequal Variances, Quantiles (with box plots, then Box Plots(0))', (o['height~sex|ttest'], o['height~sex|unequal'], o['height~sex|quantiles'], o['height~sex|box']), (True, True, True, False))
check('Set α Level: the report\'s alpha', o['alpha'], 0.1)
check('Compare Densities', o['height~sex|densities'], 'compare')

r, s = one_step('Contingency( Y( :sex ), X( :age ), Mosaic Plot( 0 ), Contingency Table( Expected( 1 ), Col %( 0 ) ), Tests( 1 ), Cochran Mantel Haenszel( :name ), Relative Risk( 1 ), Correspondence Analysis( 1 ) );')
o = s['options']
check('Contingency: the page\'s kind for nominal by ordinal', s['kind'], 'contingency')
check('Contingency: the table\'s cells', o['sex~age|cells'], ['count', 'total', 'row', 'expected'])
check('Contingency: the rest', (o['sex~age|mosaic'], o['sex~age|cmh'], o['sex~age|rr'], o['sex~age|ca']), (False, 'name', True, True))
r, s = one_step('Logistic( Y( :sex ), X( :height ), Odds Ratios( 1 ), ROC Curve( 1 ), Inverse Prediction( Response( 0.5, 0.9 ) ), Positive Level( "M" ) );')
o = s['options']
check('Logistic: odds ratios, ROC, inverse prediction, target level', (o['sex~height|odds'], o['sex~height|roc'], o['sex~height|inverse'], o['sex~height|target']), (True, True, [0.5, 0.9], 'M'))

r, s = one_step('Fit Y by X( Y( :height, :sex ), X( :weight, :age ) );')
check('Fit Y by X: every Y against every X', s['roles'], {'y': ['height', 'sex'], 'x': ['weight', 'age']})
check('... the page chooses each pair\'s analysis: kinds differ here', s['kind'], 'mixed')
r, s = one_step('Oneway( Y( :height ), X( :weight ) );')
check('Oneway of a continuous X: the page would draw a Bivariate, and says so', (s['kind'], has_note(r, 1, 'Bivariate there', 'warn')), ('oneway', True))
r, s = one_step('Bivariate( Y( :height ), X( :sex ) );')
check('Bivariate of a nominal X: the note', has_note(r, 1, 'Oneway there', 'warn'), True)

r, s = one_step('Matched Pairs( Y( :height, :weight ), X( :sex ), Plot Dif by Row( 1 ), Wilcoxon Signed Rank( 1 ), Sign Test( 1 ) );')
check('Matched Pairs: roles and options scoped by the pair', (s['platform'], s['roles'], s['options']), ('matchedpairs', {'y': ['height', 'weight'], 'x': ['sex']}, {'height~weight|plotRow': True, 'height~weight|wilcoxon': True, 'height~weight|sign': True}))

r, s = one_step('Fit Model( Y( :weight ), Effects( :sex, :height, :sex * :height, :height * :height, :age[:sex], :name & Random ), Personality( "Standard Least Squares" ), Emphasis( "Effect Screening" ),'
                ' No Intercept( 1 ), Run( :weight << {Summary of Fit( 1 ), Lack of Fit( 0 ), Plot Residual by Predicted( 1 ), Box Cox Y Transformation( 1 ), Scaled Estimates( 1 )}, Profiler( 1 ) ) );')
eff = s['extra']['effects']
check('Fit Model: the effects, crossed, a power, nested and random', [(e['cols'], e['nest'], e['random']) for e in eff],
      [(['sex'], [], False), (['height'], [], False), (['sex', 'height'], [], False), (['height', 'height'], [], False), (['age'], ['sex'], False), (['name'], [], True)])
check('Fit Model: an effect names its columns for the page to find', eff[2]['names'], ['sex', 'height'])
o = s['options']
check('Fit Model: personality, emphasis, no intercept', (o['personality'], o['emphasis'], o['noIntercept']), ('standard', 'screening', True))
check('Fit Model: Run options of the response, scoped by it', {k: v for k, v in o.items() if k.startswith('weight|')},
      {'weight|summaryOfFit': True, 'weight|lackOfFit': False, 'weight|plotResidPred': True, 'weight|boxcox': True})
check('Fit Model: a Run option for every response', o['profiler'], True)
check('Fit Model: Scaled Estimates is not in the page: a note', has_note(r, 1, 'Scaled Estimates', 'info'), True)
r, s = one_step('Fit Model( Y( :height ), Effects( :sex, :age ), Personality( "Generalized Linear Model" ), GLM Distribution( "Poisson" ), Link Function( "Log" ), Offset( :weight ), Run( Wald Tests( 1 ) ) );')
check('Fit Model GLM: distribution, link, offset, Wald tests', (s['options']['personality'], s['options']['dist'], s['options']['link'], s['roles']['offset'], s['options']['wald']), ('glm', 'poisson', 'log', ['weight'], True))
r, s = one_step('Fit Model( Y( :sex ), Effects( :height ), Run( Likelihood Ratio Tests( 1 ), Odds Ratios( 1 ) ) );')
check('Fit Model with a nominal Y and no personality: Nominal Logistic', (s['options']['personality'], s['options']['effectTests'], s['options']['odds']), ('nominal', True, True))
r, s = one_step('Fit Model( Y( :age ), Effects( :height ), Personality( "Ordinal Logistic" ), Target Level( "12" ) );')
check('Fit Model Ordinal Logistic, Target Level', (s['options']['personality'], s['options']['target']), ('ordinal', '12'))
r, s = one_step('Fit Model( Y( :height ), Effects( :weight ), Personality( "Loglinear Variance" ) );')
check('a personality the page has not: no step, a NOT CONVERTED line and a note', (s, '# NOT CONVERTED (line 1)' in r['python'], has_note(r, 1, 'no personality', 'warn')), (None, True, True))
r, s = one_step('Fit Model( Y( :height ), Effects( :weight, :sex & Random ), Personality( "Generalized Linear Model" ) );')
check('random effects in a personality that takes none: a warning', has_note(r, 1, 'fixed effects only', 'warn'), True)

r, s = one_step('Multivariate( Y( :height, :weight, :age ), Estimation Method( "Pairwise" ), Scatterplot Matrix( Density Ellipses( 1 ), Shaded Ellipses( 1 ) ), Correlations Multivariate( 1 ),'
                ' Inverse Correlations( 1 ), Spearman\'s ρ( 1 ), Nonparametric Correlations( Kendall\'s τ( 1 ) ), Mahalanobis Distances( 1 ), Cronbach\'s α( 1 ), Color Map On Correlations( 1 ) );')
check('Multivariate: roles and options', (s['platform'], s['roles'], s['options']), ('multivariate', {'y': ['height', 'weight', 'age']},
      {'method': 'pairwise', 'splom': True, 'spEllipses': True, 'spShaded': True, 'corr': True, 'inverse': True, 'np:spearman': True, 'np:kendall': True, 'mahal': True, 'alpha:raw': True, 'cmCorr': True}))
r, s = one_step('Multivariate( Y( :height, :weight ), Estimation Method( "REML" ) );')
check('an estimation method the page has not: a note, and Row-wise', ('method' not in s['options'], has_note(r, 1, 'REML', 'info')), (True, True))
r, s = one_step('Principal Components( Y( :height, :weight ), "on Covariances", Eigenvalues( 1 ), Eigenvectors( 1 ), Scree Plot( 1 ), Loading Plot( 1 ), Bartlett Test( 1 ) );')
check('Principal Components', (s['platform'], s['options']), ('pca', {'on': 'covariances', 'eigen': True, 'eigvec': True, 'scree': True, 'loadplot': True, 'bartlett': True}))

for src, pid, roles, opts in [
        ('Partition( Y( :sex ), X( :height, :weight ), Split Best( 4 ), Minimum Size Split( 3 ), Validation Portion( 0.25 ), Informative Missing( 1 ) );', 'partition',
         {'y': ['sex'], 'x': ['height', 'weight']}, {'steps': [{'op': 'split', 'n': 4}], 'minsize': 3, 'portion': 0.25, 'missing': True}),
        ('Hierarchical Cluster( Y( :height, :weight ), Label( :name ), Method( "Ward" ), Standardize Data( 1 ), Number of Clusters( 3 ) );', 'hcluster',
         {'y': ['height', 'weight'], 'label': ['name']}, {'method': 'ward', 'standardize': 'columns', 'ncluster': 3}),
        ('K Means Cluster( Y( :height, :weight ), Number of Clusters( 4 ), Columns Scaled Individually( 0 ) );', 'kmeans', {'y': ['height', 'weight']}, {'k': 4, 'scaled': False}),
        ('Discriminant( Y( :height, :weight ), X( :sex ), Discriminant Method( "Quadratic" ) );', 'discriminant', {'y': ['height', 'weight'], 'x': ['sex']}, {'method': 'quadratic'}),
        ('Factor Analysis( Y( :height, :weight, :age ) );', 'factor', {'y': ['height', 'weight', 'age']}, {}),
        ('Survival( Y( :height ), Censor( :age ), Grouping( :sex ), Censor Code( 12 ), Plot Failure( 1 ) );', 'survival',
         {'y': ['height'], 'censor': ['age'], 'group': ['sex']}, {'censorCode': '12', 'failure': True}),
        ('Time Series( X( :age ), Y( :height ), Forecast Periods( 10 ), Number of Autocorrelation Lags( 12 ) );', 'timeseries', {'time': ['age'], 'y': ['height']}, {'forecast': 10, 'nlags': 12}),
        ('Control Chart Builder( Variables( Y( :height ), Subgroup( :age ) ) );', 'controlchart', {'y': ['height'], 'subgroup': ['age']}, {}),
        ('Control Chart( Sample Size( 5 ), Chart Col( :height, XBar, S ) );', 'controlchart', {'y': ['height']}, {'subgroupSize': 5, 'chart': 'xbar_s'}),
        ('Neural( Y( :sex ), X( :height, :weight ), Validation( :age ) );', 'neural', {'y': ['sex'], 'x': ['height', 'weight'], 'validation': ['age']}, {}),
        ('Bootstrap Forest( Y( :sex ), X( :height ) );', 'forest', {'y': ['sex'], 'x': ['height']}, {}),
        ('Life Distribution( Y( :height ), Censor( :age ) );', 'lifedist', {'y': ['height'], 'censor': ['age']}, {}),
        ('Overlay Plot( X( :age ), Y( :height, :weight ) );', 'overlay', {'x': ['age'], 'y': ['height', 'weight']}, {}),
        ('Scatterplot Matrix( Y( :height, :weight ), Matrix Format( "Lower Triangular" ) );', 'scattermatrix', {'y': ['height', 'weight']}, {'format': 'lower'}),
        ('Variability Chart( Y( :height ), X( :sex, :age ), Model( "Nested" ) );', 'variability', {'y': ['height'], 'x': ['sex', 'age']}, {'model': 'nested'}),
]:
    r, s = one_step(src)
    check(f'{src.split("(")[0]}: the page\'s {pid}, roles and options', (s and s['platform'], s and s['roles'], s and s['options']), (pid, roles, opts))
r, s = one_step('Graph Builder( Size( 500, 400 ), Show Control Panel( 0 ), Variables( X( :height ), Y( :weight ), Group X( :sex ), Color( :age ) ), Elements( Points( X, Y, Legend( 1 ) ), Smoother( X, Y ), Bar( X, Y, Summary Statistic( "Mean" ) ) ) );')
gb = s['options']['gb']
check('Graph Builder: the zones', {k: [z['name'] for z in v] for k, v in gb['zones'].items()}, {'x': ['height'], 'y': ['weight'], 'groupX': ['sex'], 'color': ['age']})
check('Graph Builder: the elements and a summary statistic', (gb['elements'], gb['auto']), ([{'type': 'points'}, {'type': 'smoother'}, {'type': 'bar', 'summary': 'mean'}], False))

r = conv('dt = Current Data Table(); dt << Distribution( Y( :height ) ); o = dt << Bivariate( Y( :weight ), X( :height ) ) << Fit Line; Oneway( Y( :height ), X( :sex ) );')
check('launches sent to a table, assigned, chained, and plain: steps in order', [(x['id'], x['platform'], x['line']) for x in r['steps']], [('p1', 'distribution', 1), ('p2', 'fitybyx', 1), ('p3', 'fitybyx', 1)])
check('a message chained on a launch', r['steps'][1]['options']['weight~height|fits'], [{'id': 'f1', 'kind': 'line'}])
check('one marker per step, in order', [ln for ln in r['python'].splitlines() if ln.startswith('# <<smui:')], ['# <<smui:p1>>', '# <<smui:p2>>', '# <<smui:p3>>'])
r = conv('dt = Current Data Table(); cols = {"height", "weight"}; For( i = 1, i <= 2, i++, Distribution( Y( Column( cols[i] ) ) ) ); Distribution( Y( Eval( cols ) ) );')
check('a launch whose columns come from a loop: not converted, with a note', (len(r['steps']), has_note(r, 1, 'while the script runs', 'warn')), (1, True))
check('Eval() of a list of column names in a role', r['steps'][0]['roles'], {'y': ['height', 'weight']})
r = conv('dt = Current Data Table(); dt << New Column( "bmi", Formula( :weight / :height ^ 2 ) ); Distribution( Y( :bmi ) );')
check('a launch on a column the script makes: new_columns, and a warning', (r['steps'][0].get('new_columns'), has_note(r, 1, 'which the script makes', 'warn')), (['bmi'], True))
r = conv('dt = Current Data Table(); s = dt << Summary( Group( :sex ), Mean( :height ) ); s << Distribution( Y( :Name( "Mean(height)" ) ) );')
check('a launch on a table the script makes: no page table, its frame', (r['steps'][0]['table'], r['steps'][0]['frame'], r['steps'][0]['roles']), (None, 's', {'y': ['Mean(height)']}))
r = conv('Uplift( Y( :sex ) ); Distribution( Y( :height ), SendToReport( Dispatch( {}, "x", FrameBox, {Frame Size( 1, 1 )} ) ) );')
check('a platform the page has not: NOT CONVERTED and a note, no step', ('# NOT CONVERTED (line 1): Uplift( Y( :sex ) )' in r['python'], has_note(r, 1, 'no such platform', 'warn'), [x['platform'] for x in r['steps']]), (True, True, ['distribution']))
check('display settings: one info note for the launch', sum(1 for n in r['notes'] if 'display settings' in n['text']), 1)
r = conv('Distribution( Y( :height ), Local Data Filter( Add Filter( Columns( :age ), Where( :age >= 14 ), Where( :sex == "M" ) ) ) );')
check('a Local Data Filter\'s Where(): the rows of the analysis', (r['steps'][0]['where'], r['steps'][0]['filter']), ('(dt["age"] >= 14) & (dt["sex"] == "M")', [{'col': 'age', 'lo': 14, 'hi': None}, {'col': 'sex', 'levels': ['M']}]))
r = conv('Distribution( Y( :height ), Where( :sex == "F" | :sex == "M" ) ); Distribution( Y( :height ), Where( 55 <= :height <= 65 ) ); Distribution( Y( :height ), Where( :height > 55 ) );')
check('filters: levels of an Or, a range; a strict comparison is none', [x['filter'] for x in r['steps']], [[{'col': 'sex', 'levels': ['F', 'M']}], [{'col': 'height', 'lo': 55, 'hi': 65}], None])
r = conv('dt = Current Data Table(); For( i = 1, i <= 2, i++, Distribution( Y( :height ) ) );')
check('a launch in a loop: the marker inside it, and a note', (r['python'].count('    # <<smui:p1>>'), has_note(r, 1, 'inside a loop', 'info')), (1, True))
r = conv('Distribution( Y( :height ) );', tables=[], current=None)
check('no page table: the step still has its frame, and a warning', (r['steps'][0]['table'], r['steps'][0]['frame'], has_note(r, 1, 'has none open', 'warn')), (None, 'dt', True))

# ==========================================================================================================
# what does not convert, and the notes
# ==========================================================================================================
r = conv('Names Default To Here( 1 );\nClear Log();\nx = 1;\nNew Window( "w", Text Box( "t" ) );\ne = Expr( a + b );\nEval( e );\nrpt = Report( x );\nWait( 0 );\nb = x +* 2;\ny = 2;')
lines = r['python'].splitlines()
check('harmless calls are dropped with an info note, no Python', (any('Names' in ln or 'Clear' in ln or 'Wait' in ln for ln in lines if not ln.startswith('#')), has_note(r, 1, 'dropped', 'info'), has_note(r, 8, 'dropped', 'info')), (False, True, True))
check('New Window: NOT CONVERTED on its line', ('# NOT CONVERTED (line 4): New Window( "w", Text Box( "t" ) )' in lines, has_note(r, 4, 'windows', 'warn')), (True, True))
check('Expr() and Eval() of it: NOT CONVERTED, each on its line', ('# NOT CONVERTED (line 5): e = Expr( a + b )' in lines, '# NOT CONVERTED (line 6): Eval( e )' in lines), (True, True))
check('a report object: NOT CONVERTED', '# NOT CONVERTED (line 7): rpt = Report( x )' in lines, True)
check('a syntax error: a note on its line, the rest converted', (has_note(r, 9, 'syntax error', 'error'), 'y = 2' in lines), (True, True))
check('the notes are in line order', [n['line'] for n in r['notes']] == sorted(n['line'] for n in r['notes']), True)
r = conv('Eval( Parse( "q = 2 * 21;" ) ); w = Eval( Parse( "q + 1" ) );')
check('Eval(Parse("literal")) is converted as the JSL it holds', (run(r)['q'], run(r)['w']), (42, 43))
r = conv('// a leading comment\nx = 1; // after\n/* block\n   comment */\ny = 2;')
check('comments on their own lines are carried into the Python', [ln for ln in r['python'].splitlines() if ln.startswith('# ') and 'translation' not in ln], ['# a leading comment', '# block', '# comment'])
r = conv('Include( "setup.jsl" ); ns = New Namespace( "n" ); x = Pat Match( "abc", "b" );')
check('Include, namespaces and pattern matching: not converted', [n['line'] for n in notes_of(r, 'warn')], [1, 1, 1])
r = conv('f = Function( {x}, x + 1 );\ng = f( 2 );\nh = Unknown Function( 3 );')
check('an unknown function: NOT CONVERTED with its name in the note', ('# NOT CONVERTED (line 3): h = Unknown Function( 3 )' in r['python'], has_note(r, 3, 'Unknown Function', 'warn')), (True, True))
r = conv('x = 1;\ny = 2 +* 3;')
check('a parse error is an error note; the script is still ok', (r['ok'], has_note(r, 2, 'syntax error', 'error')), (True, True))
r = conv(')))')
check('a script with nothing that can be read: ok False', r['ok'], False)
r = conv('dt = Current Data Table(); dt << Data Filter( Add Filter( Columns( :age ) ) ); dt << Color by Column( :sex );')
check('Data Filter: not converted; Color by Column: dropped with a note', ('NOT CONVERTED' in r['python'], has_note(r, 1, 'Data Filter', 'warn'), has_note(r, 1, 'only changes how JMP shows the table', 'info')), (True, True, True))
r = conv('x = "p" || 3;')
check('|| of a number: a warning (an error in JSL)', has_note(r, 1, 'joins strings', 'warn'), True)
r = conv('np = 1; df = 2; sum = 3; row = 4; Show( np + df + sum + row );')
check('names that Python or the page\'s code uses are renamed', ('np_ = 1' in r['python'], 'df_ = 2' in r['python'], 'sum_ = 3' in r['python'], 'row_ = 4' in r['python'], run(r)['__out__'].strip()), (True, True, True, True, 'np + df + sum + row = 10'))
r = conv('my var = 1; My Var += 2; Show( myvar );')
check('the same name however it is spelt is one Python name', (r['python'].count('my_var'), run(r)['__out__'].strip()), (3, 'myvar = 3'))
r = conv('a = Substr( , 2, 1 );\nb = Round( 2.567, 1, );\nl = {1, , 2};\nx = 0; If( x > 1, , y = 2 );')
ns = run(r)
check('an empty argument before others: NOT CONVERTED (the arguments would move)', ('# NOT CONVERTED (line 1): a = Substr( , 2, 1 )' in r['python'], has_note(r, 1, 'empty argument', 'warn')), (True, True))
check('... one at the end is dropped', ns['b'], 2.6)
check('an empty item in a list: left out, with a warning', (ns['l'], has_note(r, 3, 'empty item', 'warn')), ([1, 2], True))
check('If() with an empty then: pass', (ns['y'], 'pass' in r['python']), (2, True))
r = conv('a = Left( 123, 2 );')
check('code that Python warns about (a subscript of a number): the warning is a note', has_note(r, 0, 'Python warns about line', 'warn'), True)

# ==========================================================================================================
# the page's entry point
# ==========================================================================================================
res = call('jsl.convert', text='x = 1 + 1; Distribution( Y( :height ) );', tables=TABLES, current='Students')
check('jsl.convert through the registry: its keys', sorted(res), ['notes', 'ok', 'python', 'steps'])
check('... JSON-safe, the step\'s fields', sorted(res['steps'][0]), ['frame', 'id', 'jsl', 'line', 'marker', 'options', 'platform', 'roles', 'table', 'where'])
check('... the note fields', all(sorted(n) == ['line', 'severity', 'text'] for n in call('jsl.convert', text='New Window("x");')['notes']), True)
res = call('jsl.convert', text='For Each Row( :height = 1 );')
check('without tables and current: still converts, and says the table is missing', (res['ok'], any('has none open' in n['text'] for n in res['notes'])), (True, True))
res = call('jsl.convert', text='Distribution( Y( :height ) );', tables=TABLES, current=None)
check('one page table and no current: that table', res['steps'][0]['table'], 'Students')

# ==========================================================================================================
# damaged scripts: always Python, never a fault of the translator
# ==========================================================================================================
SCRIPTS = [
    'dt = Current Data Table(); dt << New Column( "b", Formula( If( :height > 60, :weight / 2, . ) ) ); Distribution( Y( :b ), Where( :sex == "F" ) );',
    'f = Function( {a, b = 2}, {c}, c = a * b; c + 1 ); For( i = 1, i <= 3, i++, Show( f( i ) ) ); aa = ["x" => 1]; For Each( {{k, v}}, aa, Write( k ) );',
    'lst = {1, 2, 3}; m = [1 2, 3 4]; x = m * m`; s = Substr( "abc", 2, 1 ) || Char( N Items( lst ) ); If( x[1, 1] > 2 & s != "", y = 1, y = 2 );',
    'dt = Current Data Table(); s = dt << Summary( Group( :sex ), Mean( :height ) ); dt << Select Where( :age > 13 ) << Exclude; Fit Model( Y( :weight ), Effects( :sex, :height * :sex ), Run( :weight << {Summary of Fit( 1 )} ) );',
    'Bivariate( Y( :weight ), X( :height ), Fit Line( {Confid Curves Fit( 1 )} ), Group By( :sex ) ); t = Eval Insert( "n=^N Rows( Current Data Table() )^" ); Try( Throw( "x" ), Show( exception_msg ) );',
]
fuzz = __import__('random').Random(20260928)
bad_python, faults = 0, []
for k in range(400):
    text = list(fuzz.choice(SCRIPTS))
    for _ in range(fuzz.randint(1, 4)):
        i = fuzz.randrange(len(text))
        if fuzz.random() < 0.5:
            del text[i]
        else:
            text.insert(i, fuzz.choice('();,{}[]:"=<>+-*/!&|^.1a '))
    text = ''.join(text)
    try:
        out = jsl_python.convert_text(text, TABLES, 'Students')
        try:
            compile(out['python'], '<fuzz>', 'exec')
            bad_python += bool(newer_fstrings(out['python']))
        except SyntaxError:
            bad_python += 1
    except Exception as e:  # STRICT: a fault of the translator is an exception
        faults.append(f'{type(e).__name__}: {e} in {text!r}')
check('400 damaged scripts: every translation is Python', bad_python, 0)
check('... and none is a fault of the translator', faults[:3], [])

# A script from a file is hostile input: its comments and names never become code. JSL ends
# a // comment at a line feed, Python at a carriage return too; a string's \!N is a line break.
import ast  # noqa: E402
hostile = ('x = 1;\n/* a block comment\nINJECTED_block = 1\n*/\n// a line comment\rINJECTED_cr = 1\n'
           '// and INJECTED_ls = 1\ndt = New Table("t");\ndt << Set Name("new\\!NINJECTED_name = 1\\!N#");\nz = "a\\!Nb\\!r";\n')
out = jsl_python.convert_text(hostile, TABLES, 'Students')['python']
tree = ast.parse(out)
check('a hostile script: its comments and table names stay comments, its strings strings',
      sorted({n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id.startswith('INJECTED')}), [])
check('... and the comment lines are still there, one line each', [ln.strip() for ln in out.splitlines() if 'INJECTED_cr' in ln or 'INJECTED_block' in ln],
      ['# INJECTED_block = 1', '# INJECTED_cr = 1'])

helpers = '\n\n'.join(['import numpy as np', 'import pandas as pd'] + list(jsl_python.HELPERS.values()))
compile(helpers, '<helpers>', 'exec')
check(f'every one of the {len(jsl_python.HELPERS)} helpers compiles, and reads in Python 3.10', newer_fstrings(helpers), 0)
check(f'every one of the {compiled[0]} translations compiles', compiled[1], 0)
check('... and reads in Python 3.10', compiled[2], 0)
sys.exit(check.done())
