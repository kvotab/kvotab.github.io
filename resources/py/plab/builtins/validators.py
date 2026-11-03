"""Checking arguments: the mustBe validators, inputParser, nargchk."""
import math
import os

import numpy as np

from . import bi
from ._util import err, nargchk, arr, opt_str, num, is_str
from ..values import (MError, Char, Cell, Struct, Str, FH, Obj, class_of, shape_of, numel, py_str, share,
                      is_numeric, text_list, Sparse)
from .. import runtime as R


# ---- mustBe validators ------------------------------------------------------------------------------

def _fail(name, message):
    raise err('MATLAB:validators:' + name, message)


def _numbers(v, name, logical_ok=True):
    """The values of a numeric (or logical) input, or the error saying it must be one."""
    if is_numeric(v) or (logical_ok and class_of(v) == 'logical'):
        return np.asarray(arr(v))
    _fail(name, 'Value must be numeric or logical.' if logical_ok else 'Value must be numeric.')


def _real_part(a, name):
    if a.dtype.kind == 'c':
        _fail(name, 'Value must be real.')
    return a.astype(float)


def _compare(name, test, word):
    @bi(name)
    def f(nargout, *args):
        nargchk(args, 1, 1, name)
        a = _real_part(_numbers(args[0], name), name)
        with np.errstate(invalid='ignore'):
            if not np.all(test(a)):
                _fail(name, f'Value must be {word}.')
        return None
    return f


_compare('mustBePositive', lambda a: a > 0, 'positive')
_compare('mustBeNonnegative', lambda a: a >= 0, 'nonnegative')
_compare('mustBeNegative', lambda a: a < 0, 'negative')
_compare('mustBeNonpositive', lambda a: a <= 0, 'nonpositive')


@bi('mustBeNonzero')
def must_be_nonzero(nargout, *args):
    nargchk(args, 1, 1, 'mustBeNonzero')
    if np.any(_numbers(args[0], 'mustBeNonzero') == 0):
        _fail('mustBeNonzero', 'Value must not be zero.')
    return None


@bi('mustBeInteger')
def must_be_integer(nargout, *args):
    nargchk(args, 1, 1, 'mustBeInteger')
    a = _numbers(args[0], 'mustBeInteger')
    if a.dtype.kind == 'c' or not np.all(np.isfinite(a) & (a == np.round(a))):
        _fail('mustBeInteger', 'Value must be integer.')
    return None


@bi('mustBeNumeric')
def must_be_numeric(nargout, *args):
    nargchk(args, 1, 1, 'mustBeNumeric')
    if not is_numeric(args[0]):
        _fail('mustBeNumeric', 'Value must be numeric.')
    return None


@bi('mustBeNumericOrLogical')
def must_be_numeric_or_logical(nargout, *args):
    nargchk(args, 1, 1, 'mustBeNumericOrLogical')
    _numbers(args[0], 'mustBeNumericOrLogical')
    return None


@bi('mustBeFloat')
def must_be_float(nargout, *args):
    nargchk(args, 1, 1, 'mustBeFloat')
    if class_of(args[0]) not in ('double', 'single'):
        _fail('mustBeFloat', 'Value must be single or double.')
    return None


@bi('mustBeReal')
def must_be_real(nargout, *args):
    nargchk(args, 1, 1, 'mustBeReal')
    a = _numbers(args[0], 'mustBeReal')
    if a.dtype.kind == 'c' and np.any(a.imag != 0):
        _fail('mustBeReal', 'Value must be real.')
    return None


@bi('mustBeFinite')
def must_be_finite(nargout, *args):
    nargchk(args, 1, 1, 'mustBeFinite')
    if not np.all(np.isfinite(_numbers(args[0], 'mustBeFinite'))):
        _fail('mustBeFinite', 'Value must be finite.')
    return None


@bi('mustBeNonNan')
def must_be_nonnan(nargout, *args):
    nargchk(args, 1, 1, 'mustBeNonNan')
    if np.any(np.isnan(_numbers(args[0], 'mustBeNonNan'))):
        _fail('mustBeNonNan', 'Value must not be NaN.')
    return None


@bi('mustBeNonempty')
def must_be_nonempty(nargout, *args):
    nargchk(args, 1, 1, 'mustBeNonempty')
    if numel(args[0]) == 0:
        _fail('mustBeNonempty', 'Value must not be empty.')
    return None


@bi('mustBeNonsparse')
def must_be_nonsparse(nargout, *args):
    nargchk(args, 1, 1, 'mustBeNonsparse')
    if type(args[0]) is Sparse:
        _fail('mustBeNonsparse', 'Value must not be sparse.')
    return None


def _bound_args(name, args):
    nargchk(args, 2, 2, name)
    a = _real_part(_numbers(args[0], name), name)
    c = _real_part(_numbers(args[1], name), name)
    if c.size != 1:
        raise err('MATLAB:validators:' + name, 'The bound must be a scalar.')
    return a, float(c.reshape(-1)[0])


def _bound(name, test, word):
    @bi(name)
    def f(nargout, *args):
        a, c = _bound_args(name, args)
        with np.errstate(invalid='ignore'):
            if not np.all(test(a, c)):
                _fail(name, f'Value must be {word} {c:g}.')
        return None
    return f


_bound('mustBeGreaterThan', lambda a, c: a > c, 'greater than')
_bound('mustBeGreaterThanOrEqual', lambda a, c: a >= c, 'greater than or equal to')
_bound('mustBeLessThan', lambda a, c: a < c, 'less than')
_bound('mustBeLessThanOrEqual', lambda a, c: a <= c, 'less than or equal to')


@bi('mustBeInRange')
def must_be_in_range(nargout, *args):
    """mustBeInRange(A, lower, upper, flags): 'inclusive' (the default),
    'exclusive', 'exclude-lower', 'exclude-upper'."""
    nargchk(args, 3, 4, 'mustBeInRange')
    a = _real_part(_numbers(args[0], 'mustBeInRange'), 'mustBeInRange')
    lo, hi = float(num(args[1])), float(num(args[2]))
    flag = (opt_str(args[3]) or '').lower() if len(args) > 3 else 'inclusive'
    if flag not in ('inclusive', 'exclusive', 'exclude-lower', 'exclude-upper'):
        raise err('MATLAB:validators:mustBeInRange', "The bounds are 'inclusive', 'exclusive', 'exclude-lower' or 'exclude-upper'.")
    open_lo = flag in ('exclusive', 'exclude-lower')
    open_hi = flag in ('exclusive', 'exclude-upper')
    with np.errstate(invalid='ignore'):
        ok = (a > lo if open_lo else a >= lo) & (a < hi if open_hi else a <= hi)
    if not np.all(ok):
        _fail('mustBeInRange', f"Value must be greater than {'' if open_lo else 'or equal to '}{lo:g} and less than {'' if open_hi else 'or equal to '}{hi:g}.")
    return None


def _member_text(v):
    if type(v) is Cell or type(v) is Str or is_str(v):
        return '\n'.join(f"    '{t}'" for t in text_list(v))
    a = np.asarray(arr(v)).reshape(-1)
    return '\n'.join(f'    {x:g}' for x in a)


@bi('mustBeMember')
def must_be_member(nargout, *args):
    """mustBeMember(A, S): every element of A is in S (text compared as text,
    case and all)."""
    nargchk(args, 2, 2, 'mustBeMember')
    a, s = args
    if is_str(a) or type(a) in (Cell, Str):
        allowed = set(text_list(s)) if (is_str(s) or type(s) in (Cell, Str)) else set()
        items = [py_str(a)] if type(a) is Char else text_list(a)
        ok = all(t in allowed for t in items)
    else:
        aa = np.asarray(arr(a)).reshape(-1)
        ss = np.asarray(arr(s)).reshape(-1) if not (is_str(s) or type(s) in (Cell, Str)) else np.zeros(0)
        ok = bool(np.all(np.isin(aa, ss)))
    if not ok:
        _fail('mustBeMember', 'Value must be a member of this set:\n' + _member_text(s))
    return None


def _is_text(v, scalar=False):
    t = type(v)
    if t is Char:
        return not scalar or (len(shape_of(v)) == 2 and shape_of(v)[0] <= 1)
    if t is Str:
        return not scalar or numel(v) == 1
    if t is Cell and not scalar:
        return all(type(x) is Char and x.a.shape[0] <= 1 for x in v.a.reshape(-1))
    return False


@bi('mustBeText')
def must_be_text(nargout, *args):
    nargchk(args, 1, 1, 'mustBeText')
    if not _is_text(args[0]):
        _fail('mustBeText', 'Value must be a character vector, string array, or cell array of character vectors.')
    return None


@bi('mustBeTextScalar')
def must_be_text_scalar(nargout, *args):
    nargchk(args, 1, 1, 'mustBeTextScalar')
    if not _is_text(args[0], scalar=True):
        _fail('mustBeTextScalar', 'Value must be a character vector or a string scalar.')
    return None


@bi('mustBeNonzeroLengthText')
def must_be_nonzero_length_text(nargout, *args):
    nargchk(args, 1, 1, 'mustBeNonzeroLengthText')
    v = args[0]
    if not _is_text(v) or any(t is None or t == '' for t in ([py_str(v)] if type(v) is Char else text_list(v))):
        _fail('mustBeNonzeroLengthText', 'Value must be text with one or more characters.')
    return None


@bi('mustBeVector')
def must_be_vector(nargout, *args):
    """mustBeVector(A) and mustBeVector(A, 'allow-all-empties')."""
    nargchk(args, 1, 2, 'mustBeVector')
    sh = shape_of(args[0])
    allow = len(args) > 1 and (opt_str(args[1]) or '').lower() == 'allow-all-empties'
    if not ((len(sh) == 2 and (sh[0] == 1 or sh[1] == 1)) or (allow and numel(args[0]) == 0)):
        _fail('mustBeVector', 'Value must be a 1-by-n or n-by-1 vector.')
    return None


@bi('mustBeScalarOrEmpty')
def must_be_scalar_or_empty(nargout, *args):
    nargchk(args, 1, 1, 'mustBeScalarOrEmpty')
    if numel(args[0]) > 1:
        _fail('mustBeScalarOrEmpty', 'Value must be scalar or empty.')
    return None


@bi('mustBeA')
def must_be_a(nargout, *args):
    """mustBeA(A, classNames): A's class is one of them (or a subclass of one)."""
    nargchk(args, 2, 2, 'mustBeA')
    names = text_list(args[1])
    c = class_of(args[0])
    supers = getattr(args[0], 'supers', ()) if isinstance(args[0], Obj) else ()
    groups = {'numeric': is_numeric(args[0]), 'float': c in ('double', 'single'),
              'integer': c in ('int8', 'int16', 'int32', 'int64', 'uint8', 'uint16', 'uint32', 'uint64')}
    if not any(n == c or n in supers or groups.get(n, False) for n in names):
        _fail('mustBeA', 'Value must be one of the following types: ' + ', '.join(f"'{n}'" for n in names) + '.')
    return None


@bi('mustBeUnderlyingType')
def must_be_underlying_type(nargout, *args):
    nargchk(args, 2, 2, 'mustBeUnderlyingType')
    names = text_list(args[1])
    if class_of(args[0]) not in names:
        _fail('mustBeUnderlyingType', 'Value must have underlying type ' + ' or '.join(f"'{n}'" for n in names) + '.')
    return None


@bi('mustBeNonmissing')
def must_be_nonmissing(nargout, *args):
    nargchk(args, 1, 1, 'mustBeNonmissing')
    v = args[0]
    if type(v) is Str:
        bad = any(s is None for s in v.a.reshape(-1))
    elif is_numeric(v):
        a = np.asarray(arr(v))
        bad = a.dtype.kind in 'fc' and bool(np.any(np.isnan(a)))
    else:
        bad = False
    if bad:
        _fail('mustBeNonmissing', 'Value must not have missing elements.')
    return None


@bi('mustBeValidVariableName')
def must_be_valid_variable_name(nargout, *args):
    import keyword  # noqa: F401  (the language's own keywords are checked below)
    nargchk(args, 1, 1, 'mustBeValidVariableName')
    v = args[0]
    names = [py_str(v)] if type(v) is Char else (text_list(v) if _is_text(v) else None)
    ok = names is not None and all(R.BUILTINS['isvarname'].fn(1, Char.of(n or '')) for n in names)
    if not ok:
        _fail('mustBeValidVariableName', 'Value must be a valid variable name.')
    return None


def _paths_check(name, args, test, what):
    nargchk(args, 1, 1, name)
    from .iofun import abspath
    v = args[0]
    if not _is_text(v):
        _fail(name, 'Value must be a character vector, string array, or cell array of character vectors.')
    items = [py_str(v)] if type(v) is Char else text_list(v)
    bad = [t for t in items if not test(abspath(t or ''))]
    if bad:
        _fail(name, f'The following {what} do not exist: ' + ', '.join(f"'{t}'" for t in bad) + '.')
    return None


@bi('mustBeFile')
def must_be_file(nargout, *args):
    return _paths_check('mustBeFile', args, os.path.isfile, 'files')


@bi('mustBeFolder')
def must_be_folder(nargout, *args):
    return _paths_check('mustBeFolder', args, os.path.isdir, 'folders')


# ---- nargchk: the old form of narginchk ---------------------------------------------------------------

@bi('nargchk')
def nargchk_(nargout, *args):
    """msg = nargchk(low, high, n) gives '' or the message for n arguments
    outside [low, high]; with 'struct', a struct with message and identifier
    (0-by-1 when n is within)."""
    nargchk(args, 3, 4, 'nargchk')
    low, high, n = num(args[0]), num(args[1]), num(args[2])
    kind = (opt_str(args[3]) or 'string').lower() if len(args) > 3 else 'string'
    if kind not in ('string', 'struct'):
        raise err('MATLAB:nargchk:invalidInput', "The fourth input is 'string' or 'struct'.", 'nargchk')
    if n < low:
        msg, ident = 'Not enough input arguments.', 'MATLAB:nargchk:notEnoughInputs'
    elif n > high:
        msg, ident = 'Too many input arguments.', 'MATLAB:nargchk:tooManyInputs'
    else:
        msg, ident = '', ''
    if kind == 'string':
        return Char.of(msg) if msg else Char(np.zeros((0, 0), np.uint16))
    if not msg:
        return Struct((0, 1), {'message': np.empty((0, 1), object), 'identifier': np.empty((0, 1), object)})
    return Struct.scalar({'message': Char.of(msg), 'identifier': Char.of(ident)})


# ---- inputParser --------------------------------------------------------------------------------------

_IP_METHODS = ('addRequired', 'addOptional', 'addParameter', 'addParamValue', 'parse')


class InputParser(Obj):
    """inputParser: required, optional and name-value inputs of a function,
    their defaults and checks, and the results of parsing an argument list;
    a handle object."""
    __slots__ = ('function_name', 'case_sensitive', 'keep_unmatched', 'partial', 'struct_expand',
                 'required', 'optional', 'params', 'results', 'unmatched', 'defaults_used')
    cls = 'inputParser'
    is_handle = True

    def __init__(self):
        self.function_name = ''
        self.case_sensitive = False
        self.keep_unmatched = False
        self.partial = True
        self.struct_expand = True
        self.required = []          # (name, validator)
        self.optional = []          # (name, default, validator)
        self.params = []            # (name, default, validator, priority)
        self.results = {}
        self.unmatched = {}
        self.defaults_used = []

    def all_names(self):
        return [r[0] for r in self.required] + [o[0] for o in self.optional] + [p[0] for p in self.params]

    def getprop(self, name):
        if name in _IP_METHODS:
            return R.NamedFH(name, _ip_bound(self, name))
        if name == 'FunctionName':
            return Char.of(self.function_name)
        if name in ('CaseSensitive', 'KeepUnmatched', 'PartialMatching', 'StructExpand'):
            return {'CaseSensitive': self.case_sensitive, 'KeepUnmatched': self.keep_unmatched,
                    'PartialMatching': self.partial, 'StructExpand': self.struct_expand}[name]
        if name == 'Parameters':
            names = sorted(self.all_names(), key=str.lower)
            return Cell.of_list([Char.of(n) for n in names])
        if name == 'Results':
            return Struct.scalar({k: self.results[k] for k in sorted(self.results, key=str.lower)})
        if name == 'Unmatched':
            return Struct.scalar(dict(self.unmatched))
        if name == 'UsingDefaults':
            return Cell.of_list([Char.of(n) for n in self.defaults_used])
        return super().getprop(name)

    def setprop(self, name, value):
        if name == 'FunctionName':
            self.function_name = py_str(value)
        elif name in ('CaseSensitive', 'KeepUnmatched', 'PartialMatching', 'StructExpand'):
            b = bool(num(value))
            if name == 'CaseSensitive':
                self.case_sensitive = b
            elif name == 'KeepUnmatched':
                self.keep_unmatched = b
            elif name == 'PartialMatching':
                self.partial = b
            else:
                self.struct_expand = b
        elif name in ('Parameters', 'Results', 'Unmatched', 'UsingDefaults'):
            raise err('MATLAB:class:SetProhibited', f"Unable to set the '{name}' property of class 'inputParser' because it is read-only.")
        else:
            return super().setprop(name, value)
        return self

    def propnames(self):
        return ['FunctionName', 'CaseSensitive', 'KeepUnmatched', 'PartialMatching', 'StructExpand',
                'Parameters', 'Results', 'Unmatched', 'UsingDefaults']

    def display_lines(self):
        def tf(b):
            return 'true' if b else 'false'
        names = sorted(self.all_names(), key=str.lower)
        return ['  inputParser with properties:', '',
                f"       FunctionName: '{self.function_name}'",
                f'      CaseSensitive: {tf(self.case_sensitive)}',
                f'      KeepUnmatched: {tf(self.keep_unmatched)}',
                f'    PartialMatching: {tf(self.partial)}',
                f'       StructExpand: {tf(self.struct_expand)}',
                '         Parameters: {' + ' '.join(f"'{n}'" for n in names) + '}',
                '            Results: [1\u00d71 struct]',
                '          Unmatched: [1\u00d71 struct]',
                '      UsingDefaults: {' + ' '.join(f"'{n}'" for n in self.defaults_used) + '}']


def _ip_bound(p, name):
    async def f(nargout, *args):
        r = R.BUILTINS[name].fn(nargout, p, *args)
        if hasattr(r, '__await__'):
            r = await r
        return r
    return f


@bi('inputParser', arr=False)
def input_parser(nargout, *args):
    nargchk(args, 0, 0, 'inputParser')
    return InputParser()


def _parser(v, fn):
    if not isinstance(v, InputParser):
        raise err('MATLAB:UndefinedFunction', f"Undefined function '{fn}' for input arguments of type '{class_of(v)}'.")
    return v


def _check_name(p, name, fn):
    if not name or not (name[0].isalpha()) or not all(c.isalnum() or c == '_' for c in name):
        raise err('MATLAB:InputParser:InvalidName', f"'{name}' is not a valid name for an input.", fn)
    taken = [n if p.case_sensitive else n.lower() for n in p.all_names()]
    if (name if p.case_sensitive else name.lower()) in taken:
        raise err('MATLAB:InputParser:NameConflict', f"An input named '{name}' already exists.", fn)


def _validator(v, fn):
    if v is None:
        return None
    if not isinstance(v, FH):
        raise err('MATLAB:InputParser:ValidationFunctionNotFunctionHandle', 'The validation function must be a function handle.', fn)
    return v


@bi('addRequired', arr=False)
def add_required(nargout, *args):
    nargchk(args, 2, 3, 'addRequired')
    p = _parser(args[0], 'addRequired')
    name = py_str(args[1])
    _check_name(p, name, 'addRequired')
    if p.optional or p.params:
        raise err('MATLAB:InputParser:RequiredAfterOptional', 'Required inputs come before optional inputs and parameters.', 'addRequired')
    p.required.append((name, _validator(args[2] if len(args) > 2 else None, 'addRequired')))
    return None


@bi('addOptional', arr=False)
def add_optional(nargout, *args):
    nargchk(args, 3, 6, 'addOptional')
    p = _parser(args[0], 'addOptional')
    name = py_str(args[1])
    _check_name(p, name, 'addOptional')
    if p.params:
        raise err('MATLAB:InputParser:OptionalAfterParameter', 'Optional inputs come before parameters.', 'addOptional')
    p.optional.append((name, share(args[2]), _validator(args[3] if len(args) > 3 else None, 'addOptional')))
    return None


@bi('addParameter', 'addParamValue', arr=False)
def add_parameter(nargout, *args):
    """addParameter(p, name, default, validator, 'PartialMatchPriority', n)."""
    nargchk(args, 3, 6, 'addParameter')
    p = _parser(args[0], 'addParameter')
    name = py_str(args[1])
    _check_name(p, name, 'addParameter')
    rest = list(args[3:])
    val = rest.pop(0) if rest and not is_str(rest[0]) else None
    prio = 1
    if len(rest) >= 2 and (opt_str(rest[0]) or '').lower() == 'partialmatchpriority':
        prio = int(num(rest[1]))
    elif rest:
        raise err('MATLAB:InputParser:InvalidOption', "The only option is 'PartialMatchPriority'.", 'addParameter')
    p.params.append((name, share(args[2]), _validator(val, 'addParameter'), prio))
    return None


async def _validate(p, name, fhv, value):
    """Run a validation function: it may give true or false, or give nothing and
    raise an error for a bad value."""
    if fhv is None:
        return
    fname = p.function_name or None
    try:
        r = await fhv.acall(0, value)
    except MError as e:
        raise err('MATLAB:InputParser:ArgumentFailedValidation', f"The value of '{name}' is invalid. {e.message}", fname)
    if isinstance(r, tuple):
        r = r[0] if r else None
    if r is None:
        return
    ok = False
    try:
        a = np.asarray(arr(r))
        ok = a.size == 1 and bool(a.reshape(-1)[0])
    except MError:
        ok = False
    if not ok:
        text = fhv.text()
        text = text[1:] if text.startswith('@') and not text.startswith('@(') else text
        raise err('MATLAB:InputParser:ArgumentFailedValidation', f"The value of '{name}' is invalid. It must satisfy the function: {text}.", fname)


def _match_param(p, word):
    """The parameter a name refers to: exactly, or by a prefix that picks one
    (the highest PartialMatchPriority among several)."""
    cmp = (lambda s: s) if p.case_sensitive else (lambda s: s.lower())
    w = cmp(word)
    exact = [q for q in p.params if cmp(q[0]) == w]
    if exact:
        return exact[0]
    if not p.partial or not w:
        return None
    pref = [q for q in p.params if cmp(q[0]).startswith(w)]
    if not pref:
        return None
    best = min(q[3] for q in pref)
    top = [q for q in pref if q[3] == best]
    if len(top) > 1:
        raise err('MATLAB:InputParser:AmbiguousParamName', f"'{word}' matches multiple parameter names: " + ', '.join(q[0] for q in top) + '.', p.function_name or None)
    return top[0]


@bi('parse', aw=True, arr=False)
async def parse(nargout, *args):
    """parse(p, args...): the required inputs, then the optional ones in turn
    (text naming a parameter starts the name-value pairs), then name-value
    pairs, or structs of them; defaults for what is not given."""
    p = _parser(args[0], 'parse')
    vals = list(args[1:])
    fname = p.function_name or None
    p.results, p.unmatched, used = {}, {}, set()
    if len(vals) < len(p.required):
        raise err('MATLAB:minrhs', 'Not enough input arguments.', fname)
    i = 0
    for name, v in p.required:
        await _validate(p, name, v, vals[i])
        p.results[name] = share(vals[i])
        used.add(name)
        i += 1
    for name, default, v in p.optional:
        if i >= len(vals):
            break
        a = vals[i]
        if p.params and is_str(a) and _match_param(p, py_str(a)) is not None:
            break
        if p.params and p.struct_expand and type(a) is Struct and a.size == 1:
            break                       # a struct of name-value pairs ends the optional inputs
        if v is not None and is_str(a) and p.params:
            try:
                await _validate(p, name, v, a)
            except MError:
                break
        else:
            await _validate(p, name, v, a)
        p.results[name] = share(a)
        used.add(name)
        i += 1
    while i < len(vals):
        a = vals[i]
        if p.struct_expand and type(a) is Struct and a.size == 1:
            for k in a.f:
                await _take_pair(p, k, a.get1(k), used, fname)
            i += 1
            continue
        if not is_str(a):
            if not p.params and not p.keep_unmatched:
                raise err('MATLAB:TooManyInputs', 'Too many input arguments.', fname)
            raise err('MATLAB:InputParser:ParamMustBeChar', 'Expected a string scalar or character vector for the parameter name.', fname)
        word = py_str(a)
        if i + 1 >= len(vals):
            if _match_param(p, word) is None and not p.params:
                raise err('MATLAB:TooManyInputs', 'Too many input arguments.', fname)
            raise err('MATLAB:InputParser:ParamMissingValue', f"No value was given for '{word}'. Name-value pair arguments require a name followed by a value.", fname)
        await _take_pair(p, word, vals[i + 1], used, fname)
        i += 2
    p.defaults_used = []
    for name, default in [(o[0], o[1]) for o in p.optional] + [(q[0], q[1]) for q in p.params]:
        if name not in used:
            p.results[name] = default
            p.defaults_used.append(name)
    return None


async def _take_pair(p, word, value, used, fname):
    q = _match_param(p, word)
    if q is None:
        if p.keep_unmatched:
            p.unmatched[word] = share(value)
            return
        raise err('MATLAB:InputParser:UnmatchedParameter', f"'{word}' is not a recognized parameter. For a list of valid name-value pair arguments, see the documentation for this function.", fname)
    await _validate(p, q[0], q[2], value)
    p.results[q[0]] = share(value)
    used.add(q[0])
