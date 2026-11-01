"""The builtin functions, registered by name.

Each builtin is fn(nargout, *args): it returns one value when nargout <= 1
(None when it gives nothing, as disp does) and a tuple of values when more
are asked for. Flags:
    ws   the caller's workspace comes first: fn(W, nargout, *args)
    aw   it is a coroutine (it calls compiled code, or waits)
    nout the most outputs it gives
    arr  it never returns a function handle (lets the compiler index its
         results directly)
"""


class Info:
    __slots__ = ('name', 'fn', 'ws', 'aw', 'nout', 'arr', 'help')

    def __init__(self, name, fn, ws=False, aw=False, nout=1, arr=False):
        self.name = name
        self.fn = fn
        self.ws = ws
        self.aw = aw
        self.nout = nout
        self.arr = arr
        self.help = None


REG = {}


def bi(*names, ws=False, aw=False, nout=1, arr=True):
    """Register a builtin under one or more names."""
    def deco(fn):
        for n in (names or (fn.__name__.rstrip('_'),)):
            REG[n] = Info(n, fn, ws, aw, nout, arr)
        return fn
    return deco


MODULES = ['core', 'elmat', 'elfun', 'datafun', 'matfun', 'strfun', 'cellfun', 'funfun', 'iofun', 'timefun', 'sparse', 'graphics', 'parallel',
           'statdesc', 'distributions', 'stattests', 'statplots']


def load(target):
    import importlib
    failed = []
    for m in MODULES:
        try:
            importlib.import_module(f'{__name__}.{m}')
        except ImportError as e:
            if f'{__name__}.{m}' in str(e) or f"'{m}'" in str(e):
                continue
            failed.append((m, e))
    target.update(REG)
    if failed:
        raise failed[0][1]
    return target
