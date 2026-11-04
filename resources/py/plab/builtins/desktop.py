"""The desktop and the engine itself: commandwindow, commandhistory,
workspace, filebrowser and openvar show parts of the page; matlabRelease,
maxNumCompThreads, memory and license say what this engine is and has.
"""
import os
import re
import sys

import numpy as np

from . import bi
from ._util import err, nargchk, opt_str, is_str, sval, num
from ..values import MError, Obj, Char, Str, Struct, py_str
from .. import runtime as R

IN_PAGE = sys.platform == 'emscripten'


def _event(what, **kw):
    if R.EVENT_HOOK[0] is not None:
        d = {'type': 'desktop', 'what': what}
        d.update(kw)
        R.EVENT_HOOK[0](d)


def _noargs(args, fn):
    if args:
        raise err('MATLAB:TooManyInputs', f'{fn} takes no inputs.', fn)


@bi('commandwindow')
def commandwindow(nargout, *args):
    """commandwindow: the Command Window shown and given the keyboard."""
    _noargs(args, 'commandwindow')
    _event('commandwindow')
    return None


@bi('commandhistory')
def commandhistory(nargout, *args):
    """commandhistory: the Command History shown."""
    _noargs(args, 'commandhistory')
    _event('history')
    return None


@bi('workspace')
def workspace(nargout, *args):
    """workspace: the Workspace shown."""
    _noargs(args, 'workspace')
    _event('workspace')
    return None


@bi('filebrowser')
def filebrowser(nargout, *args):
    """filebrowser: the Current Folder shown."""
    _noargs(args, 'filebrowser')
    _event('files')
    return None


_VARNAME = re.compile(r'^[A-Za-z]\w*(\.[A-Za-z]\w*|\(\d+(,\d+)*\)|\{\d+(,\d+)*\})*$')


@bi('openvar')
def openvar(nargout, *args):
    """openvar(name): the variable (or a part of it, as s.data or c{2})
    opened as a table in the Editor's place."""
    nargchk(args, 1, 2, 'openvar')
    name = sval(args[0], 'variable name', 'openvar').strip()
    if not _VARNAME.match(name.replace(' ', '')):
        raise err('MATLAB:openvar:InvalidName', 'openvar takes the name of a variable, or of a part of one such as s.data or c{2}.', 'openvar')
    _event('openvar', name=name.replace(' ', ''))
    return None


# ---- the release ------------------------------------------------------------------------------------------------------

class Release(Obj):
    """matlabRelease: which release this is. PyLAB is no release of
    MATLAB: Release is "PyLAB", and isMATLABReleaseOlderThan compares."""
    cls = 'matlabRelease'
    is_handle = False
    PROPS = ('Release', 'Stage', 'Update', 'Date')

    def value_copy(self):
        return self

    def getprop(self, name):
        k = name.lower()
        if k == 'release':
            return Str(np.array([['PyLAB']], object))
        if k == 'stage':
            return Str(np.array([['release']], object))
        if k == 'update':
            return 0.0
        if k == 'date':
            from .timetypes import DateTime
            return DateTime(np.array([[np.nan]]), 'dd-MMM-uuuu')
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized property '{name}' for class 'matlabRelease'.")

    def setprop(self, name, value):
        raise MError('MATLAB:class:SetProhibited', f"You cannot set the '{name}' property of matlabRelease.")

    def propnames(self):
        return list(self.PROPS)

    def display_lines(self):
        return ['  matlabRelease with properties:', '', '    Release: "PyLAB"', '      Stage: "release"', '     Update: 0', '       Date: NaT']


@bi('matlabRelease', arr=False)
def matlabRelease(nargout, *args):
    """r = matlabRelease: Release "PyLAB" (no release of MATLAB), Stage,
    Update and Date (not known)."""
    _noargs(args, 'matlabRelease')
    return Release()


# ---- threads and memory -----------------------------------------------------------------------------------------------

_THREADS = [None]


def _cores():
    if IN_PAGE:
        return 1
    return os.cpu_count() or 1


@bi('maxNumCompThreads')
def maxNumCompThreads(nargout, *args):
    """n = maxNumCompThreads: how many threads computations use (1 in the
    page, where Python runs in one); maxNumCompThreads(n) or
    ('automatic') sets that number and gives the one before."""
    nargchk(args, 0, 1, 'maxNumCompThreads')
    old = float(_THREADS[0] if _THREADS[0] is not None else _cores())
    if args:
        v = args[0]
        if is_str(v):
            if py_str(v).lower() != 'automatic':
                raise err('MATLAB:maxNumCompThreads:InvalidInput', "Give a number of threads or 'automatic'.", 'maxNumCompThreads')
            _THREADS[0] = None
        else:
            n = float(num(v))
            if not (n >= 1 and n == int(n)):
                raise err('MATLAB:maxNumCompThreads:InvalidInput', 'The number of threads is a whole number from 1.', 'maxNumCompThreads')
            _THREADS[0] = int(min(n, _cores()))
    return old


def _heap():
    """(used, limit) bytes: the page's WebAssembly memory, or this process's."""
    if IN_PAGE:
        try:
            import pyodide_js
            used = float(pyodide_js._module.HEAPU8.length)
        except Exception:
            used = float('nan')
        return used, 4.0 * 2 ** 30
    try:
        import resource
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        used = float(rss if sys.platform == 'darwin' else rss * 1024)
    except Exception:
        used = float('nan')
    total = float('nan')
    try:
        total = float(os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES'))
    except (ValueError, OSError, AttributeError):
        pass
    return used, total


@bi('memory', nout=2, arr=False)
def memory(nargout, *args):
    """memory: the memory the engine uses and can have; [userview,
    systemview] = memory as structs. In the page that is WebAssembly
    memory, which grows up to 4 GB."""
    _noargs(args, 'memory')
    used, limit = _heap()
    avail = limit - used if np.isfinite(limit) and np.isfinite(used) else float('nan')
    user = Struct.scalar({'MaxPossibleArrayBytes': avail, 'MemAvailableAllArrays': avail, 'MemUsedMATLAB': used})
    phys = Struct.scalar({'Available': avail, 'Total': limit})
    system = Struct.scalar({'VirtualAddressSpace': Struct.scalar({'Available': avail, 'Total': limit}),
                            'SystemMemory': Struct.scalar({'Available': avail}), 'PhysicalMemory': phys})
    if nargout:
        return (user, system) if nargout > 1 else user
    mb = lambda b: 'unknown' if not np.isfinite(b) else f'{b / 2 ** 20:,.0f} MB'
    rows = [('Maximum possible array:', avail), ('Memory available for all arrays:', avail), ('Memory used by PyLAB:', used),
            ('Memory the engine can have:' if IN_PAGE else 'Physical memory (RAM):', limit)]
    w = max(len(r[0]) for r in rows)
    R.write(''.join(f'{lab:<{w}}  {mb(v):>12}\n' for lab, v in rows))
    if IN_PAGE:
        R.write('(WebAssembly memory of the page\'s Python, which grows as it needs up to 4 GB.)\n')
    return None


# ---- licences ---------------------------------------------------------------------------------------------------------

# the features programs ask for by name, and whether this engine has their functions
FEATURES = {
    'matlab': True, 'statistics_toolbox': True, 'optimization_toolbox': True, 'signal_toolbox': True, 'symbolic_toolbox': True,
    'image_toolbox': True, 'curve_fitting_toolbox': True, 'control_toolbox': True, 'map_toolbox': True, 'wavelet_toolbox': True,
    'pde_toolbox': True, 'distrib_computing_toolbox': True, 'gads_toolbox': True, 'matlab_report_gen': False,
    'identification_toolbox': False, 'econometrics_toolbox': False, 'financial_toolbox': False, 'communication_toolbox': False,
    'fuzzy_toolbox': False, 'neural_network_toolbox': False, 'video_and_image_blockset': False, 'text_analytics_toolbox': False,
    'audio_system_toolbox': False, 'simulink': False, 'matlab_compiler': False, 'matlab_coder': False,
}


@bi('license', nout=2, arr=False)
def license(nargout, *args):
    """license: the licence number (none: PyLAB is free); license('test',
    feature) or license('checkout', feature): whether the engine has that
    toolbox's functions; license('inuse'): the features in use."""
    nargchk(args, 0, 3, 'license')
    if not args:
        return Char.of('none')
    op = (opt_str(args[0]) or '').lower()
    if op == 'inuse':
        if nargout:
            return Struct.scalar({'feature': Char.of('matlab'), 'user': Char.of('')})
        R.write('matlab\n')
        return None
    if op in ('test', 'checkout'):
        if len(args) < 2:
            raise err('MATLAB:license:NoFeature', f"license('{op}', feature) names the feature.", 'license')
        feat = sval(args[1], 'feature name', 'license').strip().lower()
        has = FEATURES.get(feat, False)
        if op == 'checkout' and nargout > 1:
            return (float(has), Char.of('' if has else f"PyLAB does not have the functions of the feature '{py_str(args[1])}'."))
        return float(has)
    raise err('MATLAB:license:InvalidOption', "license takes 'test', 'checkout' or 'inuse'.", 'license')
