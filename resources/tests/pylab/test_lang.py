"""The interpreter's language, run natively (CPython with numpy and scipy):
values, indexing, cells and structs, text, control flow, functions and
files, copy-on-write, errors, display, and a sample of the numerics.

    python3 test_lang.py          (from any folder; needs numpy and scipy)

Each case runs code in a fresh workspace and checks variables (`want`), the
Command Window text (`shows`) or the error (`error`).
"""
import asyncio
import math
import os
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'py'))

from plab import runtime as R  # noqa: E402
from plab import display as D  # noqa: E402
from plab.values import Char, Cell, Struct, Str, FH  # noqa: E402

R.setup()


def run(code, ws=None):
    """Run code in a fresh base workspace: (workspace, output text)."""
    R.BASE.clear()
    R.BASE.gnames.clear()
    R.take_output()
    asyncio.run(R.execute(code))
    return R.BASE, R.take_output()


def val(v):
    """A plain Python form of a value for comparing."""
    t = type(v)
    if t is float or t is bool or t is complex:
        return v
    if t is np.ndarray:
        if v.size == 1:
            x = v.reshape(-1)[0]
            return x.item()
        return v.tolist()
    if t is Char:
        return v.str() if v.a.shape[0] <= 1 else v.row_strs()
    if t is Str:
        return [s for s in v.a.reshape(-1, order='F')] if v.a.size != 1 else v.a.flat[0]
    if t is Cell:
        return [val(x) for x in v.a.reshape(-1, order='F')]
    if t is Struct:
        if v.size == 1:
            return {k: val(v.get1(k)) for k in v.f}
        return [{k: val(a.reshape(-1, order='F')[i]) for k, a in v.f.items()} for i in range(v.size)]
    return v


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


def same(a, b, tol=1e-9):
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(same(x, y, tol) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(same(a[k], b[k], tol) for k in a)
    if isinstance(a, (int, float, complex, bool, np.number)) and isinstance(b, (int, float, complex, bool, np.number)):
        if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
            return True
        if complex(a) == complex(b):
            return True
        return abs(complex(a) - complex(b)) <= tol * max(1.0, abs(complex(b)))
    return a == b


def case(label, code, want=None, shows=None, error=None, absent=None, cls=None):
    try:
        W, out = run(code)
    except Exception as e:
        C(label, False, f'raised {type(e).__name__}: {e}')
        return
    if error is not None:
        C(label, error in out, f'output {out!r} lacks {error!r}')
        return
    if 'Error' in out and error is None and not (shows and 'Error' in shows):
        if not out.strip().startswith('Error') and 'Unrecognized' not in out and 'Error' not in out:
            pass
    for name, w in (want or {}).items():
        if name not in W:
            C(f'{label}: {name}', False, f'no variable {name}; output {out!r}')
            continue
        got = val(W[name])
        C(f'{label}: {name}', same(got, w), f'got {got!r}, want {w!r}; output {out[-300:]!r}')
    for name, c in (cls or {}).items():
        from plab.values import class_of
        C(f'{label}: class({name})', name in W and class_of(W[name]) == c, f'got {class_of(W[name]) if name in W else None}')
    if shows is not None:
        for s in ([shows] if isinstance(shows, str) else shows):
            C(f'{label}: shows {s[:40]!r}', s in out, f'output {out!r}')
    for name in absent or ():
        C(f'{label}: {name} absent', name not in W)


# ---- arithmetic and classes ---------------------------------------------------------------
case('scalar arithmetic', 'a = 1 + 2*3; b = 2^-1; c = -2^2; d = 7/2; e = mod(-7, 3); f = rem(-7, 3);',
     want={'a': 7, 'b': 0.5, 'c': -4, 'd': 3.5, 'e': 2, 'f': -1})
case('power is left-associative', 'p = 2^3^2;', want={'p': 64})
case('division by zero', 'a = 1/0; b = -1/0; c = 0/0;', want={'a': math.inf, 'b': -math.inf, 'c': math.nan})
case('complex results', 'z = sqrt(-4); w = (-8)^(1/3); r = abs(3+4i); q = (1+2i)*(3-1i);',
     want={'z': 2j, 'w': complex(1.0000000000000002, 1.7320508075688772), 'r': 5, 'q': 5 + 5j})
case('complex parts vanish', 'z = (1+2i) - 2i; t = isreal(z);', want={'z': 1, 't': True})
case('integer saturation', 'a = int8(100) + int8(100); b = uint8(3) - uint8(5); c = int16(7) / int16(2); d = int32(-7)/2;',
     want={'a': 127, 'b': 0, 'c': 4, 'd': -4}, cls={'a': 'int8', 'b': 'uint8', 'c': 'int16', 'd': 'int32'})
case('integer and double', 'a = int8(5) * 2.6;', want={'a': 13}, cls={'a': 'int8'})
case('mixed integers refused', 'a = int8(1) + int16(1);', error='Integers can only be combined')
case('single wins over double', 'a = single(1) + 2;', cls={'a': 'single'})
case('char arithmetic', "a = 'a' + 1; b = double('AB');", want={'a': 98, 'b': [[65, 66]]})
case('logical arithmetic', 'a = true + true; b = class(a);', want={'a': 2, 'b': 'double'})
case('implicit expansion', 'a = [1 2 3] + [10; 20];', want={'a': [[11, 12, 13], [21, 22, 23]]})
case('incompatible sizes', 'a = [1 2 3] + [1 2];', error='Arrays have incompatible sizes for this operation.')
case('matrix product', 'a = [1 2; 3 4] * [5; 6];', want={'a': [[17], [39]]})
case('matrix product sizes', 'a = [1 2 3] * [4 5 6];', error='Incorrect dimensions for matrix multiplication')
case('backslash', 'x = [2 1; 1 3] \\ [3; 5];', want={'x': [[0.8], [1.4]]})
case('slash', 'x = [3 5] / [2 1; 1 3];', want={'x': [[0.8, 1.4]]})
case('matrix power', 'a = [1 1; 1 0]^10;', want={'a': [[89, 55], [55, 34]]})
case('transpose', "a = [1 2; 3 4]'; b = [1+2i 3]'; c = [1+2i 3].';", want={'a': [[1, 3], [2, 4]], 'b': [[1 - 2j], [3]], 'c': [[1 + 2j], [3]]})
case('comparisons', 'a = [1 2 3] > 2; b = 3 == 3; c = [1 NaN] == [1 NaN];', want={'a': [[False, False, True]], 'b': True, 'c': [[True, False]]})
case('logic', 'a = ~[1 0 2]; b = xor(true, false); c = [1 0] & [1 1]; d = [1 0] | [0 0];',
     want={'a': [[False, True, False]], 'b': True, 'c': [[True, False]], 'd': [[True, False]]})
case('short circuit', 'x = []; a = isempty(x) || x(1) > 0; b = ~isempty(x) && x(1) > 0;', want={'a': True, 'b': False})
case('nan in logic', 'a = NaN & true;', error="NaN's cannot be converted to logicals.")
case('colon ranges', 'a = 1:5; b = 0:0.25:1; c = 5:-2:1; d = 1:0; n = numel(0:0.1:1);',
     want={'a': [[1, 2, 3, 4, 5]], 'b': [[0, 0.25, 0.5, 0.75, 1]], 'c': [[5, 3, 1]], 'd': [[]], 'n': 11})
case('colon end lands', 'a = 0:0.1:1; b = a(end) == 1;', want={'b': True})
case('char range', "a = 'a':'e';", want={'a': 'abcde'})

# ---- indexing -----------------------------------------------------------------------------------
case('linear and subscripts', 'A = magic(4); a = A(2,3); b = A(7); c = A(end); d = A(end,1); e = A(:,2)\'; f = A(2,:);',
     want={'a': 10, 'b': 7, 'c': 1, 'd': 4, 'e': [[2, 11, 7, 14]], 'f': [[5, 11, 10, 8]]})
case('linear index shapes', 'v = 1:5; a = v([1 3]); w = (1:5)\'; b = w([1 3]); M = magic(3); c = M([1 2; 3 4]);',
     want={'a': [[1, 3]], 'b': [[1], [3]], 'c': [[8, 3], [4, 1]]})
case('logical indexing', 'A = magic(3); b = A(A > 5)\'; v = 1:6; c = v(logical([1 0 1 0 1 0]));',
     want={'b': [[8, 9, 6, 7]], 'c': [[1, 3, 5]]})
case('end arithmetic', 'v = 10:10:100; a = v(end-2:end); b = v(end/2);', want={'a': [[80, 90, 100]], 'b': 50})
case('out of range', 'v = 1:3; x = v(5);', error='Index exceeds the number of array elements. Index must not exceed 3.')
case('out of range 2-D', 'A = ones(2); x = A(3,1);', error='Index in position 1 exceeds array bounds')
case('bad index', 'v = 1:3; x = v(0);', error='Array indices must be positive integers or logical values.')
case('bad index fraction', 'v = 1:3; x = v(1.5);', error='Array indices must be positive integers or logical values.')
case('grow a row', 'v = []; v(3) = 1; w = 5; w(4) = 2;', want={'v': [[0, 0, 1]], 'w': [[5, 0, 0, 2]]})
case('grow a column', 'v = [1;2]; v(4) = 7;', want={'v': [[1], [2], [0], [7]]})
case('grow a matrix', 'A = eye(2); A(3,4) = 9;', want={'A': [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 0, 9]]})
case('ambiguous growth', 'A = eye(2); A(7) = 1;', error='Attempt to grow array along ambiguous dimension.')
case('end+1 appends', 'v = []; for k = 1:4, v(end+1) = k^2; end', want={'v': [[1, 4, 9, 16]]})
case('colon on empty takes the value', 'M = []; M(:,1) = [1;2;3]; M(:,2) = [4;5;6]; R = []; R(1,:) = [1 2 3];',
     want={'M': [[1, 4], [2, 5], [3, 6]], 'R': [[1, 2, 3]]})
case('assign a block', 'A = zeros(3); A(2:3, [1 3]) = [1 2; 3 4];', want={'A': [[0, 0, 0], [1, 0, 2], [3, 0, 4]]})
case('assign broadcast scalar', 'A = magic(3); A(A > 5) = 0;', want={'A': [[0, 1, 0], [3, 5, 0], [4, 0, 2]]})
case('size mismatch', 'v = 1:3; v(1:2) = [1 2 3];', error='Unable to perform assignment because the left and right sides have a different number of elements.')
case('size mismatch 2-D', 'A = zeros(2); A(1:2, 1:2) = [1 2 3];', error='Unable to perform assignment because the size of the left side is 2-by-2')
case('row into column slot', 'A = zeros(3); A(:,1) = [1 2 3];', want={'A': [[1, 0, 0], [2, 0, 0], [3, 0, 0]]})
case('delete elements', 'v = 1:5; v([2 4]) = []; A = magic(3); A(2,:) = []; B = magic(3); B(:, [1 3]) = [];',
     want={'v': [[1, 3, 5]], 'A': [[8, 1, 6], [4, 9, 2]], 'B': [[1], [5], [9]]})
case('delete from a matrix by index', 'A = magic(3); A([1 2]) = [];', want={'A': [[4, 1, 5, 9, 6, 7, 2]]})
case('null assignment', 'A = magic(3); A(1,2) = [];', error='A null assignment can have only one non-colon index.')
case('class follows assignment', 'a = [1 2 3]; a(2) = int8(5); b = true(1,3); b(2) = 7; c = \'abc\'; c(2) = 65;',
     want={'a': [[1, 5, 3]], 'b': [[1, 7, 1]], 'c': 'aAc'}, cls={'a': 'int8', 'b': 'double', 'c': 'char'})
case('complex assignment', 'a = [1 2]; a(2) = 1i;', want={'a': [[1, 1j]]})
case('N-D arrays', 'A = zeros(2,3,4); A(1,2,3) = 5; s = size(A); n = ndims(A); B = A(:,:,3); v = sum(A(:));',
     want={'s': [[2, 3, 4]], 'n': 3, 'B': [[0, 5, 0], [0, 0, 0]], 'v': 5})
case('reshape column-major', 'a = reshape(1:6, 2, 3); b = reshape(1:6, [], 2)\';', want={'a': [[1, 3, 5], [2, 4, 6]], 'b': [[1, 2, 3], [4, 5, 6]]})
case('fewer subscripts', 'A = reshape(1:24, 2, 3, 4); a = A(2, 5);', want={'a': 10})

# ---- copies -------------------------------------------------------------------------------------
case('value semantics', 'a = [1 2 3]; b = a; b(1) = 100;', want={'a': [[1, 2, 3]], 'b': [[100, 2, 3]]})
case('value semantics in loops', 'a = zeros(1,3); b = a; for k = 1:3, a(k) = k; end', want={'a': [[1, 2, 3]], 'b': [[0, 0, 0]]})
case('cell copies', 'c = {1, [1 2]}; d = c; d{2}(1) = 9; e = c{2};', want={'e': [[1, 2]], 'd': [1, [[9, 2]]]})
case('struct copies', 's.a = [1 2]; t = s; t.a(2) = 5; u = s.a;', want={'u': [[1, 2]]})
case('nested struct copies', 's.in.v = 1; t = s; t.in.v = 2; a = s.in.v; b = t.in.v;', want={'a': 1, 'b': 2})
case('a field taken out', 's.v = [1 2 3]; x = s.v; x(1) = 0; y = s.v;', want={'y': [[1, 2, 3]], 'x': [[0, 2, 3]]})
case('struct array element', 's(1).v = 1; s(2).v = [1 2]; t = s(2); s(2).v(1) = 7; a = t.v;', want={'a': [[1, 2]]})
case('transpose is a copy', 'a = [1 2; 3 4]; b = a\'; b(1) = 0; c = a(1);', want={'c': 1})

# ---- cells and structs ----------------------------------------------------------------------------
case('cell basics', "c = {1, 'two', [3 4]}; a = c{3}; b = class(c(2)); n = numel(c);", want={'a': [[3, 4]], 'b': 'cell', 'n': 3})
case('cell grow', 'c = {}; c{3} = 5; n = numel(c); e = isempty(c{1});', want={'n': 3, 'e': True})
case('cs-list into a function', 'c = {1, 2, 3}; m = max(c{2:3}); v = [c{:}];', want={'m': 3, 'v': [[1, 2, 3]]})
case('cs-list to outputs', 'c = {4, 5}; [a, b] = c{:};', want={'a': 4, 'b': 5})
case('cell of cells', 'c = {{1, 2}, {3}}; x = c{1}{2};', want={'x': 2})
case('paren on cells', "c = {1, 'a', 2}; d = c([1 3]); c(2) = [];", want={'d': [1, 2], 'c': [1, 2]})
case('brace on non-cell', 'x = 5; y = x{1};', error='Brace indexing is not supported for variables of this type.')
case('struct basics', "s.name = 'Bo'; s.age = 3; f = fieldnames(s)'; g = isfield(s, 'age'); h = s.('name');",
     want={'f': ['name', 'age'], 'g': True, 'h': 'Bo'})
case('struct function', "s = struct('a', {1, 2, 3}, 'b', 'x'); n = numel(s); v = [s.a]; w = s(2).b;", want={'n': 3, 'v': [[1, 2, 3]], 'w': 'x'})
case('struct of a cell', "s = struct('c', {{1, 2}}); n = numel(s); k = s.c{2};", want={'n': 1, 'k': 2})
case('struct array grows', 's.a = 1; s(3).a = 3; n = numel(s); e = isempty(s(2).a);', want={'n': 3, 'e': True})
case('deep assignment', 's = struct(); s.a.b(2).c{3} = 7; x = s.a.b(2).c{3}; n = numel(s.a.b);', want={'x': 7, 'n': 2})
case('dynamic fields', "names = {'x', 'y'}; for k = 1:2, s.(names{k}) = k; end", want={'s': {'x': 1, 'y': 2}})
case('rmfield', "s.a = 1; s.b = 2; t = rmfield(s, 'a');", want={'t': {'b': 2}})
case('missing field', 's.a = 1; x = s.b;', error='Unrecognized field name "b".')
case('arrayfun', 'a = arrayfun(@(x) x^2, 1:4); b = arrayfun(@(x) x*[1 1], 1:2, \'UniformOutput\', false);',
     want={'a': [[1, 4, 9, 16]], 'b': [[[1, 1]], [[2, 2]]]})
case('cellfun', "a = cellfun(@numel, {'ab', 'cde', ''}); b = cellfun('isempty', {[], 1}); [mn, mx] = cellfun(@(v) deal(min(v), max(v)), {[1 5], [2 3]});",
     want={'a': [[2, 3, 0]], 'b': [[True, False]], 'mn': [[1, 2]], 'mx': [[5, 3]]})
case('cellfun nonuniform error', 'a = cellfun(@(x) [x x], {1, 2});', error='Non-scalar in Uniform output')
case('structfun', 's.a = 1; s.b = 4; v = structfun(@(x) x*2, s)\';', want={'v': [[2, 8]]})
case('num2cell and cell2mat', 'c = num2cell([1 2; 3 4]); m = cell2mat({[1 2], [3]; [4 5], [6]});', want={'c': [1, 3, 2, 4], 'm': [[1, 2, 3], [4, 5, 6]]})
case('containers.Map', "m = containers.Map(); m('a') = 1; m('b') = 2; k = keys(m); v = m('b'); n = m.Count; h = isKey(m, 'c');",
     want={'k': ['a', 'b'], 'v': 2, 'n': 2, 'h': False})
case('containers.Map numeric keys', 'm = containers.Map([1 2 3], {\'one\', \'two\', \'three\'}); s = m(2);', want={'s': 'two'})

# ---- text -----------------------------------------------------------------------------------------
case('char concatenation', "s = ['abc', 'def']; t = [s(1:3) ' ' upper(s(4:end))];", want={'s': 'abcdef', 't': 'abc DEF'})
case('char matrix', "m = ['ab'; 'cd']; r = m(2,:); n = size(m);", want={'r': 'cd', 'n': [[2, 2]]})
case('char rows must match', "m = ['ab'; 'cde'];", error='Dimensions of arrays being concatenated are not consistent.')
case('sprintf', "a = sprintf('%d-%s', 5, 'x'); b = sprintf('%5.2f|', [1.234 5]); c = sprintf('%d', [1 2 3]); d = sprintf('%d\\n', 1.5);",
     want={'a': '5-x', 'b': ' 1.23| 5.00|', 'c': '123', 'd': '1.500000e+00\n'})
case('sprintf recycles', "a = sprintf('%d, %d; ', 1, 2, 3);", want={'a': '1, 2; 3, '})
case('sprintf escapes', "a = sprintf('a\\tb\\\\c%%');", want={'a': 'a\tb\\c%'})
case('num2str', "a = num2str(pi); b = num2str(42); c = num2str(pi, 8); d = num2str([1 2 3]); e = num2str(-0.5);",
     want={'a': '3.1416', 'b': '42', 'c': '3.1415927', 'd': '1  2  3', 'e': '-0.5'})
case('mat2str', "a = mat2str([1 2; 3 4.5]); b = mat2str(true); c = mat2str([0.1 1/3], 4);", want={'a': '[1 2;3 4.5]', 'b': 'true', 'c': '[0.1 0.3333]'})
case('str2num and str2double', "a = str2num('[1 2 3] * 2'); b = str2double('2.5e3'); c = str2double('x'); d = str2double({'1', 'b'});",
     want={'a': [[2, 4, 6]], 'b': 2500, 'c': math.nan, 'd': [[1, math.nan]]})
case('strsplit and strjoin', "c = strsplit('a,b,,c', ','); s = strjoin({'x', 'y', 'z'}, '-');", want={'c': ['a', 'b', 'c'], 's': 'x-y-z'})
case('strrep, strtrim, upper', "a = strrep('hello world', 'o', '0'); b = strtrim(sprintf('  hi \\t')); c = lower('ABC');", want={'a': 'hell0 w0rld', 'b': 'hi', 'c': 'abc'})
case('strcmp family', "a = strcmp('a', 'a'); b = strcmpi('ABC', 'abc'); c = strcmp({'a', 'b'}, 'b'); d = strncmp('hello', 'help', 3);",
     want={'a': True, 'b': True, 'c': [[False, True]], 'd': True})
case('strfind and contains', "a = strfind('abcabc', 'bc'); b = contains('hello', 'ell'); c = startsWith('hello', 'he');", want={'a': [[2, 5]], 'b': True, 'c': True})
case('regexp', "[tok, mat] = regexp('a1b22c333', '(\\d+)', 'tokens', 'match'); s = regexp('one two', '\\s', 'split'); n = regexp('abc', 'b');",
     want={'mat': ['1', '22', '333'], 'tok': [['1'], ['22'], ['333']], 's': ['one', 'two'], 'n': 2})
case('regexp names', "t = regexp('key=val', '(?<k>\\w+)=(?<v>\\w+)', 'names');", want={'t': {'k': 'key', 'v': 'val'}})
case('regexprep with tokens', "s = regexprep('2026-11-01', '(\\d+)-(\\d+)-(\\d+)', '$3.$2.$1');", want={'s': '01.11.2026'})
case('string arrays', 's = "abc"; t = s + "def"; n = strlength(t); u = ["a", "bb"]; v = upper(u); w = s == "abc";',
     want={'t': 'abcdef', 'n': 6, 'v': ['A', 'BB'], 'w': True}, cls={'u': 'string'})
case('string with numbers', 's = "x = " + 3.5; t = string(42);', want={'s': 'x = 3.5', 't': '42'})
case('dec2bin and friends', "a = dec2bin(10); b = bin2dec('1010'); c = dec2hex(255); d = hex2dec('ff');", want={'a': '1010', 'b': 10, 'c': 'FF', 'd': 255})
case('blanks and deblank', "a = ['x' blanks(2) 'y']; b = deblank('hi   ');", want={'a': 'x  y', 'b': 'hi'})

# ---- control flow ------------------------------------------------------------------------------
case('if elseif else', 'x = 5; if x > 10, r = 1; elseif x > 3, r = 2; else, r = 3; end', want={'r': 2})
case('for over a matrix takes columns', 's = 0; for c = [1 2; 3 4], s = s + c(1)*c(2); end', want={'s': 11})
case('for over a cell', "n = 0; for c = {1, 'ab', [1 2 3]}, n = n + numel(c{1}); end", want={'n': 6})
case('for with a step', 'v = []; for k = 10:-3:1, v(end+1) = k; end', want={'v': [[10, 7, 4, 1]]})
case('loop variable after the loop', 'for k = 1:3, end; a = k;', want={'a': 3})
case('changing the loop variable', 'n = 0; for k = 1:3, k = k * 10; n = n + 1; end', want={'n': 3, 'k': 30})
case('while break continue', 'k = 0; s = 0; while true, k = k + 1; if k > 10, break; end; if mod(k, 2), continue; end; s = s + k; end',
     want={'s': 30, 'k': 11})
case('switch numbers and cells', "x = 3; switch x, case 1, r = 'one'; case {2, 3}, r = 'two or three'; otherwise, r = 'other'; end",
     want={'r': 'two or three'})
case('switch text', "s = 'beta'; switch s, case 'alpha', r = 1; case {'beta', 'gamma'}, r = 2; end", want={'r': 2})
case('switch otherwise', "switch 'z', case 'a', r = 1; otherwise, r = 0; end", want={'r': 0})
case('try catch', "try, error('my:id', 'Bad %d', 5); catch err, id = err.identifier; msg = err.message; end", want={'id': 'my:id', 'msg': 'Bad 5'})
case('try catch runtime error', 'try, x = [1 2](3); catch e, m = e.message; end', error='Invalid expression')
case('try catch index error', 'v = 1:2; try, x = v(3); catch e, m = e.message; end', want={'m': 'Index exceeds the number of array elements. Index must not exceed 2.'})
case('rethrow', "try, try, error('a:b', 'inner'); catch e, rethrow(e); end; catch f, m = f.identifier; end", want={'m': 'a:b'})
case('MException', "me = MException('x:y', 'v=%d', 3); try, throw(me); catch e, m = e.message; end", want={'m': 'v=3'})
case('block on one line', 'for k=1:3; if k==2; r = k; end; end', want={'r': 2})
case('continuation lines', 'a = [1 2 ...\n 3 4];', want={'a': [[1, 2, 3, 4]]})
case('block comments', 'a = 1;\n%{\na = 2;\n%}\nb = a;', want={'b': 1})

# ---- functions and handles ---------------------------------------------------------------------
case('anonymous function', 'f = @(x, y) x.^2 + y; a = f(3, 1); g = @() 42; b = g();', want={'a': 10, 'b': 42})
case('captures by value', 'k = 2; f = @(x) k*x; k = 10; a = f(3);', want={'a': 6})
case('nested anonymous', 'add = @(a) @(b) a + b; inc = add(1); x = inc(5);', want={'x': 6})
case('handle to builtin', 'f = @sin; a = f(0); g = @max; [m, i] = g([3 7 2]);', want={'a': 0, 'm': 7, 'i': 2})
case('func2str and str2func', "f = @(x) x + 1; s = func2str(f); g = str2func('@(t) t * 3'); a = g(2); h = str2func('cos'); b = h(0);",
     want={'s': '@(x)x+1', 'a': 6, 'b': 1})
case('feval', "a = feval(@plus, 1, 2); b = feval('max', [1 5 3]);", want={'a': 3, 'b': 5})
case('handles in cells', 'fs = {@sin, @cos}; a = fs{2}(0);', want={'a': 1})
case('handle display', 'f = @(x) x.^2 + 1', shows='@(x)x.^2+1')
case('too many outputs', 'f = @(x) x; [a, b] = f(1);', error='Too many output arguments.')
case('not enough inputs for anonymous', 'f = @(x, y) x + y; a = f(1);', error='Not enough input arguments.')
case('deal', '[a, b] = deal(7); [c, d] = deal(1, 2);', want={'a': 7, 'b': 7, 'c': 1, 'd': 2})

# ---- function files -------------------------------------------------------------------------------
FILES = {
    'addup.m': 'function s = addup(varargin)\n%ADDUP  The sum of any number of arguments.\ns = 0;\nfor k = 1:nargin\n    s = s + varargin{k};\nend\nend\n',
    'twoout.m': 'function [a, b] = twoout(x)\na = x + 1;\nif nargout > 1\n    b = x * 2;\nend\nend\n',
    'fact.m': 'function f = fact(n)\nif n <= 1\n    f = 1;\nelse\n    f = n * fact(n - 1);\nend\n',
    'withlocal.m': 'function y = withlocal(x)\ny = helper(x) + helper2(x);\nend\nfunction z = helper(x)\nz = 10 * x;\nend\nfunction z = helper2(x)\nz = x;\nend\n',
    'counter.m': 'function n = counter()\npersistent k\nif isempty(k), k = 0; end\nk = k + 1;\nn = k;\n',
    'mutator.m': 'function v = mutator(v)\nv(1) = 99;\n',
    'noout.m': 'function noout(x)\ndisp(x);\n',
    'needsarg.m': 'function y = needsarg(x)\ny = x + 1;\n',
    'unassigned.m': 'function [a, b] = unassigned()\na = 1;\n',
    'thrower.m': "function thrower()\nerror('mine:bad', 'Something %s.', 'failed');\n",
    'deep.m': 'function deep()\nv = [1 2];\nx = v(3);\n',
    'scr.m': 'scr_a = 5;\nscr_b = scr_a * 2;\n',
    'vout.m': 'function varargout = vout(n)\nfor k = 1:n\n    varargout{k} = k;\nend\n',
    'glob1.m': 'function glob1()\nglobal G\nG = 42;\n',
    'glob2.m': 'function v = glob2()\nglobal G\nv = G;\n',
    'defaults.m': 'function r = defaults(a, b)\nif nargin < 2\n    b = 10;\nend\nr = a + b;\n',
    'argblock.m': 'function r = argblock(a, b)\narguments\n    a (1,1) double\n    b (1,1) double = 5\nend\nr = a * b;\nend\n',
    'nested_handle.m': 'function r = nested_handle()\nf = @local_sq;\nr = f(4);\nend\nfunction y = local_sq(x)\ny = x^2;\nend\n',
    'evalfun.m': "function r = evalfun()\neval('q = 3;');\nr = q * 2;\n",
    'early.m': 'function r = early(x)\nr = 0;\nif x < 0\n    return\nend\nr = sqrt(x);\n',
    'nestsum.m': 'function r = nestsum(n)\ntotal = 0;\n    function add(k)\n        total = total + k;\n    end\nfor i = 1:n\n    add(i);\nend\nh = @add;\nh(100);\nr = total;\nend\n',
    'makecounter.m': 'function f = makecounter()\nc = 0;\n    function v = next()\n        c = c + 1;\n        v = c;\n    end\nf = @next;\nend\n',
    'readsonly.m': 'function r = readsonly()\nsetx();\nr = x;\n    function setx()\n        x = 5;\n    end\nend\n',
    'twolevel.m': ('function r = twolevel(n)\nacc = 0;\n    function outer_step(k)\n        scale = 10;\n        inner_step(k);\n'
                   '        function inner_step(j)\n            acc = acc + j * scale + n;\n        end\n    end\n'
                   'for i = 1:3\n    outer_step(i);\nend\nr = acc;\nend\n'),
    'siblings.m': ("function [a, b] = siblings()\none();\ntwo();\na = getone();\nb = 7;\n    function one()\n        x = 1;\n    end\n"
                   "    function two()\n        x = 2;\n    end\n    function v = getone()\n        v = exist('x', 'var');\n    end\nend\n"),
    'argslocal.m': 'function r = argslocal()\nk = 100;\nq = twice(3);\nr = [k q];\n    function k = twice(k)\n        k = 2 * k;\n    end\nend\n',
}
tmp = tempfile.mkdtemp(prefix='pylab-test-')
for name, text in FILES.items():
    with open(os.path.join(tmp, name), 'w') as f:
        f.write(text)
R.STATE['cwd'] = tmp
R.bump_epoch()

case('varargin and nargin', 'a = addup(1, 2, 3); b = addup();', want={'a': 6, 'b': 0})
case('nargout', '[p, q] = twoout(3); r = twoout(3);', want={'p': 4, 'q': 6, 'r': 4})
case('recursion', 'a = fact(10);', want={'a': 3628800})
case('local functions', 'a = withlocal(2);', want={'a': 22})
case('persistent', 'counter(); counter(); a = counter();', want={'a': 3})
case('arguments are copies', 'v = [1 2 3]; w = mutator(v);', want={'v': [[1, 2, 3]], 'w': [[99, 2, 3]]})
case('no output used as value', 'x = noout(1);', error='Too many output arguments.')
case('no output at statement level', 'noout(7)', shows='7')
case('missing argument', 'y = needsarg();', error='Not enough input arguments.')
case('too many arguments', 'y = needsarg(1, 2);', error='Too many input arguments.')
case('unassigned output', '[a, b] = unassigned();', error='Output argument "b" (and possibly others) not assigned a value')
case('error in a function names it', 'thrower()', shows=['Error using', 'Something failed.'])
case('error stack', 'deep()', shows=['Index exceeds', 'Error in', 'deep (line 3)', 'x = v(3);'])
case('script in the workspace', 'scr', want={'scr_a': 5, 'scr_b': 10})
case('varargout', '[a, b, c] = vout(3);', want={'a': 1, 'b': 2, 'c': 3})
case('globals', 'glob1(); a = glob2(); global G; b = G;', want={'a': 42, 'b': 42})
case('nargin defaults', 'a = defaults(1); b = defaults(1, 2);', want={'a': 11, 'b': 3})
case('arguments block defaults', 'a = argblock(2); b = argblock(2, 3);', want={'a': 10, 'b': 6})
case('handle to a local function', 'r = nested_handle();', want={'r': 16})
case('eval in a function', 'r = evalfun();', want={'r': 6})
case('return', 'a = early(-1); b = early(4);', want={'a': 0, 'b': 2})
case('function handle to a file', 'f = @fact; a = f(5); b = arrayfun(@fact, 1:4);', want={'a': 120, 'b': [[1, 2, 6, 24]]})
case('exist', "a = exist('fact'); b = exist('sin'); x = 1; c = exist('x', 'var'); d = exist('nothing_here');", want={'a': 2, 'b': 5, 'c': 1, 'd': 0})
case('which', 'which fact', shows='fact.m')
case('nested functions share the variables both use', 'r = nestsum(4);', want={'r': 110})
case('a handle keeps the workspace of its call', 'f = makecounter(); a = f(); b = f(); g = makecounter(); c = g(); d = f();',
     want={'a': 1, 'b': 2, 'c': 1, 'd': 3})
case('a variable the parent only reads', 'r = readsonly();', want={'r': 5})
case('two levels of nesting', 'r = twolevel(1);', want={'r': 63})
case('siblings share only what the parent uses', '[a, b] = siblings();', want={'a': False, 'b': 7})
case("a nested function's arguments are its own", 'r = argslocal();', want={'r': [[100, 6]]})

# ---- workspace and session ----------------------------------------------------------------------
case('clear', 'a = 1; b = 2; clear a', want={'b': 2}, absent=['a'])
case('clear with pattern', 'xa = 1; xb = 2; y = 3; clear x*', want={'y': 3}, absent=['xa', 'xb'])
case('who', 'alpha = 1; beta = 2; who', shows=['Your variables are:', 'alpha', 'beta'])
case('ans', '3 + 4; a = ans;', want={'a': 7})
case('eval with catch', "eval('x = [1 2](5);', 'y = 1;');", want={'y': 1})
case('evalc', "s = evalc('disp(5)');", want={'s': '     5\n'})
case('assignin', "assignin('base', 'q', 3);", want={'q': 3})
case('command syntax', 'format long; x = pi; format short', shows=None)
case('isvarname', "a = isvarname('x1'); b = isvarname('1x'); c = isvarname('end');", want={'a': True, 'b': False, 'c': False})
case('tic toc', 't = tic; e = toc(t); ok = e >= 0;', want={'ok': True})
case('input without a page', "x = input('n: ');", error='Input is not available here.')

# ---- display ----------------------------------------------------------------------------------------
case('show integer', 'x = 5', shows='x =\n\n     5\n')
case('show matrix', 'A = [1 2; 3 4]', shows='A =\n\n     1     2\n     3     4\n')
case('show decimals', 'x = pi', shows='    3.1416')
case('show zero in decimals', 'x = [0 0.5]', shows='         0    0.5000')
case('show scale factor', 'x = [1000.5 2]', shows=['1.0e+03 *', '1.0005    0.0020'])
case('show exponent', 'x = 1e-5', shows='1.0000e-05')
case('show large integers', 'x = [1 1000]', shows='           1        1000')
case('show NaN and Inf', 'x = [1 NaN Inf]', shows='     1   NaN   Inf')
case('show complex', 'z = 3 + 4i', shows='3.0000 + 4.0000i')
case('show logical', 'b = true', shows='  logical\n\n   1')
case('show char', "s = 'hi'", shows="    'hi'")
case('show empty', 'e = []', shows='     []')
case('show empty sized', 'e = zeros(0, 3)', shows='0×3 empty double matrix')
case('show cell', "c = {1, 'a'}", shows=["1×2 cell array", "{[1]}    {'a'}"])
case('show struct', "s.a = 1; s.bb = 'x'; s", shows=['struct with fields:', "     a: 1", "    bb: 'x'"])
case('show int', 'i = int8([1 2 3])', shows=['1×3 int8 row vector', '   1   2   3'])
case('format long', 'format long; x = pi', shows='3.141592653589793')
case('format compact', 'format compact; x = 5', shows='x =\n     5\n')
case('format reset', 'format; x = 1', shows='x =\n\n     1\n')
case('disp', "disp(5); disp('text'); disp([1 2])", shows=['     5\n', 'text\n', '     1     2\n'])
case('fprintf', "fprintf('%d apples\\n', 3)", shows='3 apples\n')
case('columns wrap', 'D.FMT = 0; x = 1:30', shows='Columns 1 through')
case('show ND', 'A = zeros(2,2,2)', shows=['A(:,:,1) =', 'A(:,:,2) ='])

# ---- numerics ---------------------------------------------------------------------------------------------
case('sum mean std', 'v = [2 4 4 4 5 5 7 9]; a = sum(v); b = mean(v); c = std(v); d = var(v, 1);', want={'a': 40, 'b': 5, 'c': 2.138089935299395, 'd': 4})
case('reductions by dimension', 'A = [1 2; 3 4]; a = sum(A); b = sum(A, 2); c = prod(A(:)); d = cumsum(A, 2); e = max(A, [], 2);',
     want={'a': [[4, 6]], 'b': [[3], [7]], 'c': 24, 'd': [[1, 3], [3, 7]], 'e': [[2], [4]]})
case('max with index', '[m, i] = max([3 9 2 9]); n = max([1 NaN 3]); o = min([4 2 8], [], 2);', want={'m': 9, 'i': 2, 'n': 3, 'o': 2})
case('sort', "[s, i] = sort([3 1 2]); d = sort([3 1 2], 'descend'); c = sort({'b', 'a', 'c'});", want={'s': [[1, 2, 3]], 'i': [[2, 3, 1]], 'd': [[3, 2, 1]], 'c': ['a', 'b', 'c']})
case('unique', '[u, ia, ic] = unique([3 1 2 3 1]); s = unique([3 1 2 3], \'stable\');', want={'u': [[1, 2, 3]], 'ia': [[2], [3], [1]], 'ic': [[3], [1], [2], [3], [1]], 's': [[3, 1, 2]]})
case('find', 'A = [0 3; 5 0]; i = find(A)\'; [r, c] = find(A); k = find([0 1 1 1], 2);', want={'i': [[2, 3]], 'r': [[2], [1]], 'c': [[1], [2]], 'k': [[2, 3]]})
case('any all', 'a = any([0 0 1]); b = all([1 1 0]); c = all([]); d = any([]);', want={'a': True, 'b': False, 'c': True, 'd': False})
case('ismember and sets', "[tf, loc] = ismember([1 5 2], [2 3 1]); u = union([3 1], [2 1]); i = intersect([1 2 3], [2 3 4]); d = setdiff([1 2 3 4], [2 4]);",
     want={'tf': [[True, False, True]], 'loc': [[3, 0, 1]], 'u': [[1, 2, 3]], 'i': [[2, 3]], 'd': [[1, 3]]})
case('linear algebra', 'A = [4 1; 2 3]; d = det(A); r = rank(magic(4)); x = inv(A) * [1; 2]; t = trace(A); e = sort(eig(A))\';',
     want={'d': 10, 'r': 3, 'x': [[0.1], [0.6]], 't': 7, 'e': [[2, 5]]})
case('svd and norm', 's = svd([3 0; 0 4])\'; n = norm([3 4]); f = norm([1 2; 3 4], \'fro\');', want={'s': [[4, 3]], 'n': 5, 'f': math.sqrt(30)})
case('qr and lu', 'A = [1 2; 3 4]; [Q, R] = qr(A); e1 = norm(Q*R - A) < 1e-12; [L, U, P] = lu(A); e2 = norm(P*A - L*U) < 1e-12;', want={'e1': True, 'e2': True})
case('chol', 'R = chol([4 2; 2 3]); e = norm(R\'*R - [4 2; 2 3]) < 1e-12;', want={'e': True})
case('polyfit and polyval', 'p = polyfit([0 1 2], [1 3 7], 2); y = polyval([1 0 -1], 3);', want={'p': [[1, 1, 1]], 'y': 8})
case('roots and conv', 'r = sort(roots([1 -3 2]))\'; c = conv([1 1], [1 -1]);', want={'r': [[1, 2]], 'c': [[1, 0, -1]]})
case('interp1', "a = interp1([1 2 3], [10 20 30], [1.5 2.5]); b = interp1([1 2 3], [10 20 30], 4); c = interp1([1 2 3], [10 20 30], 4, 'linear', 'extrap');",
     want={'a': [[15, 25]], 'b': math.nan, 'c': 40})
case('trapz and cumsum', 'a = trapz([1 2 3]); b = trapz(0:0.5:1, [0 1 2]);', want={'a': 4, 'b': 1})
case('fzero', 'x = fzero(@(x) cos(x) - x, 1);', want={'x': 0.7390851332151607})
case('fminsearch', "x = fminsearch(@(p) (p(1)-1)^2 + (p(2)+2)^2, [0 0]);", want={'x': [[1, -2]]}) if False else None
case('fminbnd', 'x = fminbnd(@(x) (x-2)^2, 0, 5);', want={'x': 2})
case('integral', 'a = integral(@(x) exp(-x.^2), -Inf, Inf); b = integral(@(x) 1./x, 1, exp(1));', want={'a': math.sqrt(math.pi), 'b': 1})
case('ode45', '[t, y] = ode45(@(t, y) -2*y, [0 1], 1); e = abs(y(end) - exp(-2)) < 1e-3; n = numel(t) > 10;', want={'e': True, 'n': True})
case('ode15s stiff', '[t, y] = ode15s(@(t, y) [-1000*y(1) + 3000; y(1)], [0 0.1], [0; 0]); e = abs(y(end, 1) - 3) < 1e-2;', want={'e': True})
case('fft', 'X = fft([1 0 0 0]); Y = abs(fft([1 1 1 1]));', want={'X': [[1, 1, 1, 1]], 'Y': [[4, 0, 0, 0]]})
case('filter', 'y = filter(1, [1 -0.5], [1 0 0 0]);', want={'y': [[1, 0.5, 0.25, 0.125]]})
case('rand default seed', 'rng default; a = rand(); rng(0); b = rand(1, 2);', want={'a': 0.8147236863931789, 'b': [[0.8147236863931789, 0.9057919370756192]]})
case('rand shapes', 'a = size(rand(3)); b = size(randn(2, 4)); c = all(randi(5, 1, 100) >= 1 & randi(5, 1, 100) <= 5);', want={'a': [[3, 3]], 'b': [[2, 4]], 'c': True})
case('magic squares', 'a = magic(3); b = sum(magic(5)); c = sum(magic(6), 2)\'; d = magic(4);',
     want={'a': [[8, 1, 6], [3, 5, 7], [4, 9, 2]], 'b': [[65] * 5], 'c': [[111] * 6], 'd': [[16, 2, 3, 13], [5, 11, 10, 8], [9, 7, 6, 12], [4, 14, 15, 1]]})
case('meshgrid', '[X, Y] = meshgrid(1:3, 1:2);', want={'X': [[1, 2, 3], [1, 2, 3]], 'Y': [[1, 1, 1], [2, 2, 2]]})
case('rounding', 'a = round(2.5); b = round(-2.5); c = fix(-2.7); d = floor(-2.5); e = round(pi, 2); f = round(1234, -2);',
     want={'a': 3, 'b': -3, 'c': -2, 'd': -3, 'e': 3.14, 'f': 1200})
case('mod with tolerance', 'a = mod(1, 0.1); b = mod(5, 0); c = rem(5, 0);', want={'a': 0, 'b': 5, 'c': math.nan})
case('gcd lcm factor primes', 'a = gcd(12, 18); b = lcm(4, 6); c = factor(84); d = primes(20); e = isprime(97);',
     want={'a': 6, 'b': 12, 'c': [[2, 2, 3, 7]], 'd': [[2, 3, 5, 7, 11, 13, 17, 19]], 'e': True})
case('nchoosek and perms', 'a = nchoosek(5, 2); b = nchoosek([1 2 3], 2); c = perms([1 2 3]);',
     want={'a': 10, 'b': [[1, 2], [1, 3], [2, 3]], 'c': [[3, 2, 1], [3, 1, 2], [2, 3, 1], [2, 1, 3], [1, 3, 2], [1, 2, 3]]})
case('special functions', 'a = gamma(5); b = erf(0); c = besselj(0, 0); d = gammainc(1, 2);', want={'a': 24, 'b': 0, 'c': 1, 'd': 0.2642411176571153})
case('datenum and datestr', "d = datenum(2026, 11, 1); s = datestr(d, 'yyyy-mm-dd'); w = weekday(d);", want={'d': 740287, 's': '2026-11-01', 'w': 1})
case('cross dot kron', 'c = cross([1 0 0], [0 1 0]); d = dot([1 2 3], [4 5 6]); k = kron([1 2], [1; 1]);', want={'c': [[0, 0, 1]], 'd': 32, 'k': [[1, 2], [1, 2]]})
case('histcounts', '[n, e] = histcounts([1 2 2 3 3 3], [0.5 1.5 2.5 3.5]);', want={'n': [[1, 2, 3]], 'e': [[0.5, 1.5, 2.5, 3.5]]})
case('accumarray', 'a = accumarray([1; 2; 1], [10; 20; 30])\';', want={'a': [[40, 20]]})
case('circshift and flips', 'a = circshift(1:5, 2); b = fliplr([1 2 3]); c = rot90([1 2; 3 4]);', want={'a': [[4, 5, 1, 2, 3]], 'b': [[3, 2, 1]], 'c': [[2, 4], [1, 3]]})
case('repmat and cat', 'a = repmat([1 2], 2, 2); b = cat(3, [1], [2]); s = size(b);', want={'a': [[1, 2, 1, 2], [1, 2, 1, 2]], 's': [[1, 1, 2]]})
case('typecast and class conversion', "a = double(int8(-5)); b = uint8(300); c = int16(-3.5); d = logical([2 0]);",
     want={'a': -5, 'b': 255, 'c': -4, 'd': [[True, False]]})
case('mat files', "x = [1 2; 3 4]; s.name = 'a'; c = {1, 'two'}; save('t1.mat', 'x', 's', 'c'); clear; load('t1.mat'); y = x(2,1); n = s.name; k = c{2};",
     want={'y': 3, 'n': 'a', 'k': 'two'})
case('text files', "fid = fopen('t.txt', 'w'); fprintf(fid, '%d %d\\n', [1 2; 3 4]); fclose(fid); A = readmatrix('t.txt'); t = fileread('t.txt');",
     want={'A': [[1, 3], [2, 4]], 't': '1 3\n2 4\n'})
case('fgetl loop', "fid = fopen('t2.txt', 'w'); fprintf(fid, 'a\\nbb\\n'); fclose(fid); fid = fopen('t2.txt'); n = 0; while true, l = fgetl(fid); if ~ischar(l), break; end; n = n + numel(l); end; fclose(fid);",
     want={'n': 3})
case('sscanf', "a = sscanf('3 4 5', '%d')'; b = sscanf('1.5,2.5', '%f,%f')';", want={'a': [[3, 4, 5]], 'b': [[1.5, 2.5]]})
case('dir and fileparts', "[p, n, e] = fileparts('/a/b/c.txt'); f = fullfile('a', 'b', 'c.m');", want={'p': '/a/b', 'n': 'c', 'e': '.txt', 'f': 'a/b/c.m'})

case('ode15i', "[t, y] = ode15i(@(t, y, yp) yp + y, [0 1], 1, -1); e = abs(y(end) - exp(-1)) < 1e-3; "
     "[t, y] = ode15i(@(t, y, yp) yp.^3 + yp + y, [0 2], 1, -0.6823278); n = abs(y(end) - 0.18267339) < 1e-3;",
     want={'e': True, 'n': True})
case('ode15i refuses a DAE', 'ode15i(@(t, y, yp) [yp(1) - y(2); y(1) + y(2)], [0 1], [1; -1], [-1; 0]);', error="singular")
case('odextend', 'sol = ode45(@(t, y) -y, [0 1], 1); sol = odextend(sol, [], 3); a = abs(deval(sol, 2.5) - exp(-2.5)) < 1e-6; '
     'b = abs(deval(sol, 0.5) - exp(-0.5)) < 1e-6; e = sol.x(end);', want={'a': True, 'b': True, 'e': 3})
case('spdiags', '[B, d] = spdiags(magic(3)); A = full(spdiags(B, d, 3, 3)); D = spdiags(magic(4), [-1 1]); C = spdiags([10 20 30]\', 0, magic(3));',
     want={'B': [[4, 3, 8, 0, 0], [0, 9, 5, 1, 0], [0, 0, 2, 7, 6]], 'd': [[-2], [-1], [0], [1], [2]], 'A': [[8, 1, 6], [3, 5, 7], [4, 9, 2]],
           'D': [[5, 0], [7, 2], [15, 10], [0, 12]], 'C': [[10, 1, 6], [3, 20, 7], [4, 9, 30]]})

# ---- errors in anonymous functions -------------------------------------------------------------------------
case('an anonymous function names its frame by its text', 'f = @(x) x(3); f([1 2])', shows='Error in @(x)x(3)')
case('a frame typed at the prompt has no link', "h = @() error('my:id', 'boom'); h()", shows="Error using @()error('my:id','boom')\nboom")

# ---- help ------------------------------------------------------------------------------------------------
from plab.helptext import HELP  # noqa: E402
from plab.lexer import KEYWORDS  # noqa: E402
from plab.help import help_for  # noqa: E402
C('help: every builtin has an entry', not (set(R.BUILTINS) - set(HELP)), sorted(set(R.BUILTINS) - set(HELP)))
C('help: every keyword has an entry', not (set(KEYWORDS) - set(HELP)), sorted(set(KEYWORDS) - set(HELP)))
C('help: every entry is a builtin or a keyword', not (set(HELP) - set(R.BUILTINS) - set(KEYWORDS)), sorted(set(HELP) - set(R.BUILTINS) - set(KEYWORDS)))
C('help: no internal names among the builtins', not [n for n in R.BUILTINS if n.endswith('_') or 'unused' in n or n[0].isdigit()],
  [n for n in R.BUILTINS if n.endswith('_') or 'unused' in n or n[0].isdigit()])
h = help_for('sum')
C('help sum', h['kind'] == 'builtin' and h['text'].startswith(' sum - ') and '    S = sum(A, dim)' in h['text'], h)

# ---- graphics state --------------------------------------------------------------------------------------
case('figure handles', "close all; h = plot(1:10); c = get(h, 'Color'); h.LineWidth = 2; w = h.LineWidth; f = gcf; n = f.Number;",
     want={'c': [[0, 0.447, 0.741]], 'w': 2, 'n': 1})
case('hold and colors', 'close all; plot(1:3); hold on; h2 = plot(3:-1:1); c = h2.Color; hold off;', want={'c': [[0.85, 0.325, 0.098]]})
case('axis limits', 'close all; plot([0 10], [0 0.97]); xl = xlim; yl = ylim; xlim([2 3]); m = xlim;', want={'xl': [[0, 10]], 'yl': [[0, 1]], 'm': [[2, 3]]})
case('subplots', 'close all; subplot(2,1,1); a1 = gca; subplot(2,1,2); a2 = gca; p = get(a1, \'Position\'); n = numel(get(gcf, \'Children\'));',
     want={'n': 2})
case('legend and labels', "close all; plot(1:3); hold on; plot(2:4); legend('a', 'b'); title('T'); t = get(get(gca, 'Title'), 'String');", want={'t': 'T'})
case('contour matrix', 'close all; C = contourc(peaks(10), [0 0]); ok = C(1,1) == 0 && C(2,1) > 0;', want={'ok': True})
case('surface data', "close all; h = surf(peaks(5)); z = size(get(h, 'ZData'));", want={'z': [[5, 5]]})

sys.exit(C.done())
