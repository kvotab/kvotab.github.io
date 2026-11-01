"""Files and folders: the current folder and the path, reading and writing
text and binary files, load and save (MAT-files and text), and opening
files in the Editor."""
import io
import math
import os
import re
import shutil
import struct as _struct

import numpy as np

from . import bi
from ._util import (err, nargchk, noout, maxout, arr, darr, out, opt_str, sval, ival, num, is_str, bool_out,
                    like_class, strip_flags, cellstr_list, NUMERIC_CLASSES, np_dtype, make)
from .fmt import sprintf as _sprintf, unescape
from ..values import (MError, NOVAL, Char, Cell, Struct, Str, FH, Obj, F64, C128, INT_TYPES, DTYPE_CLASS, class_of,
                      shape_of, numel, _2d, EMPTY, py_str, share, share_all, text_list)
from .. import runtime as R


def abspath(p):
    p = os.path.expanduser(p)
    if not os.path.isabs(p):
        p = os.path.join(R.STATE['cwd'], p)
    return os.path.normpath(p)


def _event(kind, **kw):
    if R.EVENT_HOOK[0] is not None:
        d = {'type': kind}
        d.update(kw)
        R.EVENT_HOOK[0](d)


def files_changed(path=None):
    """Something in the file system changed: compiled code is checked again
    and the page's Current Folder is told."""
    R.bump_epoch()
    _event('files', path=path or R.STATE['cwd'])


# ---- folders ------------------------------------------------------------------------------

@bi('pwd')
def pwd(nargout, *args):
    return Char.of(R.STATE['cwd'])


@bi('cd')
def cd(nargout, *args):
    if not args:
        if nargout:
            return Char.of(R.STATE['cwd'])
        R.write(R.STATE['cwd'] + '\n\n' if False else '\n' + R.STATE['cwd'] + '\n\n')
        return None
    p = abspath(sval(args[0], 'folder', 'cd'))
    if not os.path.isdir(p):
        raise err('MATLAB:cd:NonExistentFolder', f'Unable to change current folder to \'{sval(args[0], "folder", "cd")}\' (Name is nonexistent or not a folder).', 'cd')
    old = R.STATE['cwd']
    R.STATE['cwd'] = p
    R.bump_epoch()
    _event('cwd', path=p)
    if nargout:
        return Char.of(old)
    return None


@bi('userpath')
def userpath(nargout, *args):
    return Char.of(R.STATE.get('home', '/home/user'))


@bi('matlabroot')
def matlabroot(nargout, *args):
    return Char.of('/pylab')


@bi('mkdir', nout=3)
def mkdir(nargout, *args):
    nargchk(args, 1, 2, 'mkdir')
    if len(args) == 2:
        p = os.path.join(abspath(sval(args[0], 'folder', 'mkdir')), sval(args[1], 'folder', 'mkdir'))
    else:
        p = abspath(sval(args[0], 'folder', 'mkdir'))
    existed = os.path.isdir(p)
    os.makedirs(p, exist_ok=True)
    files_changed(os.path.dirname(p))
    if existed and not nargout:
        R.warn('MATLAB:MKDIR:DirectoryExists', 'Directory already exists.')
    if nargout:
        return (True, Char.of('Directory already exists.' if existed else ''), Char.of('MATLAB:MKDIR:DirectoryExists' if existed else ''))[:nargout] if nargout > 1 else True
    return None


@bi('rmdir', nout=3)
def rmdir(nargout, *args):
    p = abspath(sval(args[0], 'folder', 'rmdir'))
    recursive = len(args) > 1 and opt_str(args[1]) == 's'
    if not os.path.isdir(p):
        if nargout:
            return False
        raise err('MATLAB:RMDIR:NotADirectory', f'{sval(args[0], "folder", "rmdir")} is not a directory.', 'rmdir')
    try:
        if recursive:
            shutil.rmtree(p)
        else:
            os.rmdir(p)
    except OSError:
        if nargout:
            return False
        raise err('MATLAB:RMDIR:DirectoryNotEmpty', f'No directories were removed: the folder is not empty (use rmdir(name, \'s\')).', 'rmdir')
    files_changed(os.path.dirname(p))
    return True if nargout else None


@bi('delete')
def delete(nargout, *args):
    import glob
    for a in args:
        if isinstance(a, Obj) and hasattr(a, 'delete_handle'):
            a.delete_handle()
            continue
        if isinstance(a, Obj) and hasattr(a, 'a'):
            for h in a.a.flat:
                if hasattr(h, 'delete_handle'):
                    h.delete_handle()
            continue
        pat = abspath(sval(a, 'file name', 'delete'))
        hits = glob.glob(pat)
        if not hits:
            R.warn('MATLAB:DELETE:FileNotFound', f'File \'{sval(a, "file name", "delete")}\' not found.')
        for h in hits:
            if os.path.isfile(h):
                os.remove(h)
        files_changed(os.path.dirname(pat))
    return None


@bi('copyfile', nout=3)
def copyfile(nargout, *args):
    import glob
    src = abspath(sval(args[0], 'source', 'copyfile'))
    dst = abspath(sval(args[1], 'destination', 'copyfile'))
    hits = glob.glob(src)
    if not hits:
        if nargout:
            return False
        raise err('MATLAB:COPYFILE:FileNotFound', f'No matching files were found.', 'copyfile')
    for h in hits:
        if os.path.isdir(h):
            shutil.copytree(h, dst if not os.path.isdir(dst) else os.path.join(dst, os.path.basename(h)), dirs_exist_ok=True)
        else:
            shutil.copy2(h, dst)
    files_changed(os.path.dirname(dst))
    return True if nargout else None


@bi('movefile', nout=3)
def movefile(nargout, *args):
    import glob
    src = abspath(sval(args[0], 'source', 'movefile'))
    dst = abspath(sval(args[1], 'destination', 'movefile'))
    hits = glob.glob(src)
    if not hits:
        if nargout:
            return False
        raise err('MATLAB:MOVEFILE:FileNotFound', 'No matching files were found.', 'movefile')
    for h in hits:
        shutil.move(h, dst)
    files_changed(os.path.dirname(dst))
    return True if nargout else None


def _dir_entries(p):
    import glob
    import time
    if os.path.isdir(p):
        names = ['.', '..'] + sorted(os.listdir(p), key=lambda s: s.lower())
        folder = p
        full = [os.path.join(p, n) for n in names]
    else:
        full = sorted(glob.glob(p), key=lambda s: s.lower())
        names = [os.path.basename(f) for f in full]
        folder = os.path.dirname(p)
    rows = []
    for n, f in zip(names, full):
        try:
            st = os.stat(f)
            isdir = os.path.isdir(f)
            rows.append((n, os.path.dirname(f) if n not in ('.', '..') else folder, st.st_mtime, 0 if isdir else st.st_size, isdir))
        except OSError:
            rows.append((n, folder, 0, 0, False))
    return rows


@bi('dir')
def dir_(nargout, *args):
    import time
    p = abspath(sval(args[0], 'name', 'dir')) if args else R.STATE['cwd']
    rows = _dir_entries(p)
    if nargout:
        n = len(rows)
        s = Struct((n, 1), {k: np.empty((n, 1), object) for k in ('name', 'folder', 'date', 'bytes', 'isdir', 'datenum')})
        for i, (name, folder, mt, size, isdir) in enumerate(rows):
            s.f['name'][i, 0] = Char.of(name)
            s.f['folder'][i, 0] = Char.of(folder)
            s.f['date'][i, 0] = Char.of(time.strftime('%d-%b-%Y %H:%M:%S', time.localtime(mt)))
            s.f['bytes'][i, 0] = float(size)
            s.f['isdir'][i, 0] = bool(isdir)
            s.f['datenum'][i, 0] = mt / 86400 + 719529
        return s
    names = [r[0] for r in rows]
    if not names:
        return None
    w = max(len(n) for n in names) + 2
    per = max(1, 80 // w)
    lines = ['']
    for i in range(0, len(names), per):
        lines.append(''.join(n.ljust(w) for n in names[i:i + per]).rstrip())
    lines.append('')
    R.write('\n'.join(lines) + '\n')
    return None


@bi('ls')
def ls(nargout, *args):
    p = abspath(sval(args[0], 'name', 'ls')) if args else R.STATE['cwd']
    rows = [r for r in _dir_entries(p) if r[0] not in ('.', '..')]
    names = [r[0] for r in rows]
    if nargout:
        return Char.rows(names) if names else Char.of('')
    if names:
        R.write('\n' + '  '.join(names) + '\n\n')
    return None


@bi('what')
def what(nargout, *args):
    p = abspath(sval(args[0], 'folder', 'what')) if args else R.STATE['cwd']
    names = sorted(os.listdir(p)) if os.path.isdir(p) else []
    m = [n for n in names if n.endswith('.m')]
    mat = [n for n in names if n.endswith('.mat')]
    if nargout:
        return Struct.scalar({'path': Char.of(p), 'm': Cell.of_list([Char.of(n) for n in m], (len(m), 1)),
                              'mat': Cell.of_list([Char.of(n) for n in mat], (len(mat), 1))})
    lines = ['', f'MATLAB Code files in the current folder {p}' if False else f'Program files in the current folder {p}', '']
    lines.append('  '.join(os.path.splitext(n)[0] for n in m))
    if mat:
        lines += ['', f'MAT-files in the current folder {p}', '', '  '.join(mat)]
    lines.append('')
    R.write('\n'.join(lines) + '\n')
    return None


@bi('fullfile')
def fullfile(nargout, *args):
    parts = []
    for a in args:
        s = sval(a, 'part', 'fullfile') if type(a) is not Cell else None
        if s is None:
            # a cell: one path per element
            items = cellstr_list(a)
            base = '/'.join(p.rstrip('/') for p in parts if p)
            return Cell.of_list([Char.of(re.sub('/+', '/', base + '/' + it if base else it)) for it in items], shape_of(a))
        if s:
            parts.append(s)
    if not parts:
        return Char.of('')
    p = parts[0]
    for q in parts[1:]:
        p = p.rstrip('/') + '/' + q.lstrip('/') if p else q
    p = re.sub('/+', '/', p)
    return Char.of(p)


@bi('fileparts', nout=3)
def fileparts(nargout, *args):
    p = sval(args[0], 'file name', 'fileparts')
    folder, name = os.path.split(p)
    if '.' in name and not name.startswith('.') or (name.count('.') > 1):
        base, ext = os.path.splitext(name)
    else:
        base, ext = name, ''
    if name.startswith('.') and name.count('.') == 1:
        base, ext = '', name
    res = (Char.of(folder), Char.of(base), Char.of(ext))
    return res[0] if nargout <= 1 else res[:nargout]


@bi('filesep')
def filesep(nargout, *args):
    return Char.of('/')


@bi('pathsep')
def pathsep(nargout, *args):
    return Char.of(':')


@bi('tempdir')
def tempdir(nargout, *args):
    os.makedirs('/tmp', exist_ok=True)
    return Char.of('/tmp/')


@bi('tempname')
def tempname(nargout, *args):
    import uuid
    base = sval(args[0], 'folder', 'tempname') if args else '/tmp'
    return Char.of(os.path.join(base, 'tp' + uuid.uuid4().hex[:12]))


@bi('isfile')
def isfile(nargout, *args):
    v = args[0]
    if type(v) in (Cell, Str) and numel(v) != 1:
        return out(np.array([os.path.isfile(abspath(s)) for s in text_list(v)], bool).reshape(shape_of(v), order='F'))
    return os.path.isfile(abspath(sval(v, 'file name', 'isfile')))


@bi('isfolder', 'isdir')
def isfolder(nargout, *args):
    v = args[0]
    if type(v) in (Cell, Str) and numel(v) != 1:
        return out(np.array([os.path.isdir(abspath(s)) for s in text_list(v)], bool).reshape(shape_of(v), order='F'))
    return os.path.isdir(abspath(sval(v, 'folder', 'isfolder')))


# ---- the path ---------------------------------------------------------------------------------

@bi('addpath')
def addpath(nargout, *args):
    rest, flags = strip_flags(args, ('-begin', '-end', '-frozen'))
    dirs = []
    for a in rest:
        for p in sval(a, 'folder', 'addpath').split(':'):
            if p:
                ap = abspath(p)
                if not os.path.isdir(ap):
                    R.warn('MATLAB:mpath:nameNonexistentOrNotADirectory', f'Name is nonexistent or not a directory: {ap}')
                    continue
                dirs.append(ap)
    old = ':'.join(R.STATE['path'])
    for d in dirs:
        if d in R.STATE['path']:
            R.STATE['path'].remove(d)
    if '-end' in flags:
        R.STATE['path'] += dirs
    else:
        R.STATE['path'][:0] = dirs
    R.bump_epoch()
    return Char.of(old) if nargout else None


@bi('rmpath')
def rmpath(nargout, *args):
    for a in args:
        for p in sval(a, 'folder', 'rmpath').split(':'):
            ap = abspath(p)
            if ap in R.STATE['path']:
                R.STATE['path'].remove(ap)
            else:
                R.warn('MATLAB:rmpath:DirNotFound', f'"{ap}" not found in path.')
    R.bump_epoch()
    return None


@bi('path')
def path_(nargout, *args):
    if args:
        R.STATE['path'] = [abspath(p) for p in sval(args[0], 'path', 'path').split(':') if p]
        R.bump_epoch()
        return None
    if nargout:
        return Char.of(':'.join(R.STATE['path']))
    R.write('\n\t\tPATH\n\n' + '\n'.join(R.STATE['path'] or ['(the current folder only)']) + '\n\n')
    return None


@bi('genpath')
def genpath(nargout, *args):
    root = abspath(sval(args[0], 'folder', 'genpath'))
    out_l = []
    for d, subs, files in os.walk(root):
        subs[:] = sorted(s for s in subs if not s.startswith(('@', '+', '.')) and s != 'private')
        out_l.append(d)
    return Char.of(':'.join(out_l) + (':' if out_l else ''))


@bi('which')
def which(nargout, *args):
    name = sval(args[0], 'name', 'which')
    p = R.find_file(name)
    if p is None and name.endswith('.m'):
        p = R.find_file(name[:-2])
    if p is not None:
        text = p
    elif name in R.BUILTINS:
        text = f'built-in ({name})'
    elif os.path.isfile(abspath(name)):
        text = abspath(name)
    else:
        text = None
    if nargout:
        return Char.of(text or '')
    R.write((text if text else f"'{name}' not found.") + '\n')
    return None


@bi('type')
def type_(nargout, *args):
    name = sval(args[0], 'file name', 'type')
    p = R.find_file(name[:-2] if name.endswith('.m') else name)
    if p is None:
        p = abspath(name)
    if not os.path.isfile(p):
        raise err('MATLAB:type:fileNotFound', f"File '{name}' not found.", 'type')
    with open(p, encoding='utf-8', errors='replace') as f:
        text = f.read()
    if nargout:
        return Char.of(text)
    R.write('\n' + text + ('\n' if not text.endswith('\n') else '') + '\n')
    return None


@bi('edit', 'open')
def edit(nargout, *args):
    if not args:
        _event('edit', path='')
        return None
    for a in args:
        name = sval(a, 'file name', 'edit')
        p = R.find_file(name[:-2] if name.endswith('.m') else name)
        if p is None:
            p = abspath(name if '.' in os.path.basename(name) else name + '.m')
            if not os.path.exists(p) and p.endswith('.m'):
                with open(p, 'w', encoding='utf-8') as f:
                    f.write('')
                files_changed(os.path.dirname(p))
        _event('edit', path=p)
    return None


@bi('run', ws=True, aw=True)
async def run(W, nargout, *args):
    name = sval(args[0], 'script', 'run')
    p = abspath(name if name.endswith('.m') else name + '.m')
    if not os.path.isfile(p):
        found = R.find_file(os.path.splitext(os.path.basename(name))[0])
        if found is None:
            raise err('MATLAB:run:FileNotFound', f'{name} not found.', 'run')
        p = found
    old = R.STATE['cwd']
    folder = os.path.dirname(p)
    changed = folder != old
    if changed:
        R.STATE['cwd'] = folder
        R.bump_epoch()
    try:
        mod = R.load_file(p)
        if mod.kind == 'script':
            await R.run_script(mod, W)
        else:
            await mod.ns['MAIN'](0)
    finally:
        if changed:
            R.STATE['cwd'] = old
            R.bump_epoch()
    return None


@bi('web')
def web(nargout, *args):
    url = sval(args[0], 'address', 'web') if args else 'https://kvotab.se/'
    _event('web', url=url)
    return None


# ---- open files -------------------------------------------------------------------------------

class _File:
    def __init__(self, path, mode, f, encoding):
        self.path = path
        self.mode = mode
        self.f = f
        self.encoding = encoding


FILES = {}


def _get(fid, fn):
    fid = int(num(fid)) if not isinstance(fid, int) else fid
    f = FILES.get(fid)
    if f is None:
        raise err('MATLAB:FileIO:InvalidFid', 'Invalid file identifier. Use fopen to generate a valid file identifier.', fn)
    return f


def file_write_text(fid, s):
    f = _get(fid, 'fprintf')
    f.f.write(s.encode(f.encoding, errors='replace'))


@bi('fopen', nout=4)
def fopen(nargout, *args):
    nargchk(args, 1, 4, 'fopen')
    if opt_str(args[0]) == 'all':
        return out(np.array([sorted(FILES)], F64)) if FILES else np.zeros((1, 0))
    if type(args[0]) is float:
        f = FILES.get(int(args[0]))
        if f is None:
            return Char.of('')
        return (Char.of(f.path), Char.of(f.mode), Char.of('ieee-le'), Char.of(f.encoding.upper()))[:max(nargout, 1)] if nargout > 1 else Char.of(f.path)
    name = sval(args[0], 'file name', 'fopen')
    mode = opt_str(args[1]) if len(args) > 1 else 'r'
    enc = opt_str(args[3]) if len(args) > 3 else 'utf-8'
    p = abspath(name)
    pymode = mode.replace('t', '')
    if 'b' not in pymode:
        pymode += 'b'
    try:
        fh = open(p, pymode)
    except OSError as e:
        msg = 'No such file or directory' if isinstance(e, FileNotFoundError) else str(e)
        if nargout >= 2:
            return -1.0, Char.of(msg)
        return -1.0
    fid = 3
    while fid in FILES:
        fid += 1
    FILES[fid] = _File(p, mode, fh, enc or 'utf-8')
    if any(c in mode for c in 'wa+'):
        files_changed(os.path.dirname(p))
    if nargout >= 2:
        return float(fid), Char.of('')
    return float(fid)


@bi('fclose')
def fclose(nargout, *args):
    nargchk(args, 1, 1, 'fclose')
    if opt_str(args[0]) == 'all':
        for f in list(FILES.values()):
            f.f.close()
        FILES.clear()
        return 0.0 if nargout else None
    fid = int(num(args[0]))
    if fid in (0, 1, 2):
        return 0.0 if nargout else None
    f = _get(fid, 'fclose')
    f.f.close()
    del FILES[fid]
    if any(c in f.mode for c in 'wa+'):
        files_changed(os.path.dirname(f.path))
    return 0.0 if nargout else None


@bi('fgetl')
def fgetl(nargout, *args):
    f = _get(args[0], 'fgetl')
    line = f.f.readline()
    if not line:
        return -1.0
    s = line.decode(f.encoding, errors='replace')
    return Char.of(s.rstrip('\n').rstrip('\r'))


@bi('fgets')
def fgets(nargout, *args):
    f = _get(args[0], 'fgets')
    line = f.f.readline()
    if not line:
        return -1.0
    return Char.of(line.decode(f.encoding, errors='replace'))


@bi('feof')
def feof(nargout, *args):
    f = _get(args[0], 'feof')
    pos = f.f.tell()
    b = f.f.read(1)
    if not b:
        return True
    f.f.seek(pos)
    return False


@bi('frewind')
def frewind(nargout, *args):
    _get(args[0], 'frewind').f.seek(0)
    return None


@bi('ftell')
def ftell(nargout, *args):
    return float(_get(args[0], 'ftell').f.tell())


@bi('fseek')
def fseek(nargout, *args):
    f = _get(args[0], 'fseek')
    off = int(num(args[1]))
    origin = args[2] if len(args) > 2 else -1.0
    o = opt_str(origin)
    whence = {'bof': 0, 'cof': 1, 'eof': 2}.get(o, None) if o else {-1: 0, 0: 1, 1: 2}[int(num(origin))]
    try:
        f.f.seek(off, whence)
        return 0.0
    except OSError:
        return -1.0


@bi('ferror', nout=2)
def ferror(nargout, *args):
    return (Char.of(''), 0.0) if nargout > 1 else Char.of('')


_PRECISION = {'uchar': np.uint8, 'schar': np.int8, 'char': np.uint8, 'int8': np.int8, 'uint8': np.uint8, 'int16': np.int16,
              'uint16': np.uint16, 'int32': np.int32, 'uint32': np.uint32, 'int64': np.int64, 'uint64': np.uint64,
              'single': np.float32, 'float32': np.float32, 'float': np.float32, 'double': np.float64, 'float64': np.float64,
              'int': np.int32, 'uint': np.uint32, 'long': np.int64, 'short': np.int16, 'ushort': np.uint16, 'bit8': np.uint8}


def _precision(s):
    s = s.strip().replace('*', '') if s else 'uint8'
    keep = False
    if '=>' in s:
        a, b = s.split('=>')
        src = _PRECISION.get(a.strip(), np.uint8)
        dst = b.strip()
        return src, dst
    return _PRECISION.get(s, np.uint8), 'double'


@bi('fread', nout=2)
def fread(nargout, *args):
    f = _get(args[0], 'fread')
    size = args[1] if len(args) > 1 else math.inf
    prec = opt_str(args[2]) if len(args) > 2 else 'uint8'
    machine = opt_str(args[4]) if len(args) > 4 else (opt_str(args[3]) if len(args) > 3 and opt_str(args[3]) else 'n')
    src, dst = _precision(prec)
    if prec and prec.startswith('*'):
        dst = prec[1:]
    dt = np.dtype(src)
    if machine and machine.lower().startswith('ieee-be') or machine in ('b',):
        dt = dt.newbyteorder('>')
    sz = darr(size).reshape(-1) if not isinstance(size, float) else np.array([size])
    count = int(np.prod(sz)) if np.all(np.isfinite(sz)) else -1
    data = f.f.read(count * dt.itemsize if count >= 0 else -1)
    n = len(data) // dt.itemsize
    a = np.frombuffer(data[:n * dt.itemsize], dt).astype(dt.newbyteorder('='))
    if sz.size == 2:
        rows = int(sz[0])
        cols = int(math.ceil(n / rows)) if not np.isfinite(sz[1]) else int(sz[1])
        pad = np.zeros(rows * cols, a.dtype)
        pad[:n] = a[:rows * cols]
        a = pad.reshape((rows, cols), order='F')
    else:
        a = a.reshape(-1, 1)
    if dst == 'char':
        res = Char(_2d(a.astype(np.uint16)))
    elif dst in ('double', None):
        res = out(a.astype(F64))
    else:
        res = make(a, dst if dst in NUMERIC_CLASSES else 'double')
    if nargout >= 2:
        return res, float(n)
    return res


@bi('fwrite')
def fwrite(nargout, *args):
    f = _get(args[0], 'fwrite')
    v = args[1]
    prec = opt_str(args[2]) if len(args) > 2 else 'uint8'
    src, dst = _precision(prec)
    a = arr(v).reshape(-1, order='F')
    if np.dtype(src).kind in 'iu':
        from ..ops import to_int_class
        cls = DTYPE_CLASS.get(np.dtype(src), 'uint8')
        data = to_int_class(a.astype(F64), cls).astype(src).tobytes()
    else:
        data = a.astype(src).tobytes()
    f.f.write(data)
    return float(a.size) if nargout else None


@bi('fileread')
def fileread(nargout, *args):
    p = abspath(sval(args[0], 'file name', 'fileread'))
    if not os.path.isfile(p):
        raise err('MATLAB:fileread:cannotOpenFile', f"Could not open file {sval(args[0], 'file name', 'fileread')}. No such file or directory.", 'fileread')
    with open(p, 'rb') as f:
        data = f.read()
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        text = data.decode('latin-1')
    return Char.of(text)


@bi('readlines')
def readlines(nargout, *args):
    p = abspath(sval(args[0], 'file name', 'readlines'))
    with open(p, encoding='utf-8', errors='replace') as f:
        lines = f.read().split('\n')
    if lines and lines[-1] == '':
        lines.pop()
    return Str.from_list([l.rstrip('\r') for l in lines], (len(lines), 1))


@bi('writelines')
def writelines(nargout, *args):
    lines = text_list(args[0])
    p = abspath(sval(args[1], 'file name', 'writelines'))
    with open(p, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    files_changed(os.path.dirname(p))
    return None


# ---- scanning text ------------------------------------------------------------------------------

_SCAN = re.compile(r'%(\*?)(\d*)(?:\.(\d+))?(l|h)?([dioufeEgGxsc]|\[[^\]]*\])')


def scan_text(s, fmt, size=None):
    """sscanf/fscanf: (values, count, error message, next index)."""
    fmt = unescape(fmt)
    pos = 0
    vals = []
    chars_only = True
    count = 0
    n = len(s)
    convs = list(_SCAN.finditer(fmt))
    if not convs:
        return EMPTY(), 0, '', 1
    limit = None
    if size is not None:
        sz = darr(size).reshape(-1)
        limit = int(np.prod(sz)) if np.all(np.isfinite(sz)) else None
    stop = False
    while not stop and pos < n:
        fpos = 0
        progressed = False
        for m in convs:
            lit = fmt[fpos:m.start()]
            fpos = m.end()
            # literal text: whitespace matches any whitespace
            for ch in lit:
                if ch.isspace():
                    while pos < n and s[pos].isspace():
                        pos += 1
                elif pos < n and s[pos] == ch:
                    pos += 1
                else:
                    stop = True
                    break
            if stop:
                break
            skip, width, prec, _, conv = m.groups()
            w = int(width) if width else None
            if conv not in ('c',) and not conv.startswith('['):
                while pos < n and s[pos].isspace():
                    pos += 1
            if pos >= n:
                stop = True
                break
            if conv in 'diu':
                mm = re.compile(r'[+-]?\d+').match(s, pos, pos + w if w else n)
            elif conv in 'oxX':
                mm = re.compile(r'[0-7]+' if conv == 'o' else r'[0-9a-fA-F]+').match(s, pos, pos + w if w else n)
            elif conv in 'feEgG':
                mm = re.compile(r'[+-]?(?:(?:\d+\.?\d*|\.\d+)(?:[eEdD][+-]?\d+)?|[Ii]nf|NaN)').match(s, pos, pos + w if w else n)
            elif conv == 's':
                mm = re.compile(r'\S+').match(s, pos, pos + w if w else n)
            elif conv == 'c':
                mm = re.compile(r'[\s\S]{1,%d}' % (w or 1)).match(s, pos)
            else:
                mm = re.compile(conv).match(s, pos)
            if not mm or mm.end() == pos:
                stop = True
                break
            text = mm.group(0)
            pos = mm.end()
            progressed = True
            if skip:
                continue
            if conv in 'di':
                vals.append(float(int(text)))
                chars_only = False
            elif conv == 'u':
                vals.append(float(int(text)))
                chars_only = False
            elif conv == 'o':
                vals.append(float(int(text, 8)))
                chars_only = False
            elif conv in 'xX':
                vals.append(float(int(text, 16)))
                chars_only = False
            elif conv in 'feEgG':
                t = text.lower()
                vals.append(math.inf * (-1 if t.startswith('-') else 1) if 'inf' in t else math.nan if t == 'nan' else float(text.replace('d', 'e').replace('D', 'e')))
                chars_only = False
            else:
                vals.extend(float(ord(c)) for c in text)
            count += 1
            if limit is not None and len(vals) >= limit:
                stop = True
                break
        if not progressed:
            break
    if chars_only and vals:
        res = Char(np.array([vals], np.uint16).reshape(1, -1))
    elif size is not None:
        sz = darr(size).reshape(-1)
        a = np.array(vals, F64)
        if sz.size == 2:
            rows = int(sz[0])
            cols = int(math.ceil(a.size / rows)) if not np.isfinite(sz[1]) else int(sz[1])
            pad = np.zeros(rows * cols)
            pad[:min(a.size, rows * cols)] = a[:rows * cols]
            res = out(pad.reshape((rows, cols), order='F'))
        else:
            res = out(a.reshape(-1, 1))
    else:
        res = out(np.array(vals, F64).reshape(-1, 1)) if vals else EMPTY()
    return res, count, '', pos + 1


@bi('fscanf', nout=2)
def fscanf(nargout, *args):
    f = _get(args[0], 'fscanf')
    fmt = sval(args[1], 'format', 'fscanf')
    data = f.f.read().decode(f.encoding, errors='replace')
    vals, count, msg, nxt = scan_text(data, fmt, args[2] if len(args) > 2 else None)
    if nargout >= 2:
        return vals, float(count)
    return vals


@bi('textscan', nout=2)
def textscan(nargout, *args):
    src = args[0]
    if is_str(src):
        text = py_str(src)
    else:
        f = _get(src, 'textscan')
        text = f.f.read().decode(f.encoding, errors='replace')
    fmt = unescape(sval(args[1], 'format', 'textscan'))
    i = 2
    delim = None
    header = 0
    while i < len(args):
        if opt_str(args[i]) is None:
            i += 1
            continue
        k = opt_str(args[i]).lower()
        v = args[i + 1] if i + 1 < len(args) else None
        if k == 'delimiter':
            delim = text_list(v)
        elif k == 'headerlines':
            header = int(num(v))
        i += 2
    lines = text.split('\n')[header:]
    convs = [m.group(5) for m in _SCAN.finditer(fmt) if not m.group(1)]
    cols = [[] for _ in convs]
    for line in lines:
        line = line.rstrip('\r')
        if not line.strip():
            continue
        if delim:
            fields = re.split('|'.join(re.escape(unescape(d)) for d in delim), line)
        else:
            fields = line.split()
        for k, conv in enumerate(convs):
            fld = fields[k].strip() if k < len(fields) else ''
            if conv in 'dfeEgGiu':
                try:
                    cols[k].append(float(fld))
                except ValueError:
                    cols[k].append(math.nan)
            else:
                cols[k].append(fld)
    outc = []
    for conv, c in zip(convs, cols):
        if conv in 'dfeEgGiu':
            outc.append(out(np.array(c, F64).reshape(-1, 1)))
        else:
            outc.append(Cell.of_list([Char.of(x) for x in c], (len(c), 1)))
    return Cell.of_list(outc)


# ---- delimited numbers ---------------------------------------------------------------------------

def _read_numeric(p, delim=None, r0=0, c0=0):
    with open(p, encoding='utf-8', errors='replace') as f:
        lines = [l.rstrip('\n').rstrip('\r') for l in f]
    rows = []
    for line in lines[r0:]:
        if not line.strip():
            continue
        if delim is None:
            d = ',' if ',' in line else ('\t' if '\t' in line else (';' if ';' in line else None))
        else:
            d = delim
        fields = line.split(d) if d else line.split()
        vals = []
        for x in fields[c0:]:
            x = x.strip().strip('"')
            try:
                vals.append(float(x) if x else math.nan)
            except ValueError:
                vals.append(math.nan)
        rows.append(vals)
    # header rows that are all text are dropped
    while rows and all(v != v for v in rows[0]) and len(rows) > 1:
        rows.pop(0)
    if not rows:
        return EMPTY()
    w = max(len(r) for r in rows)
    a = np.full((len(rows), w), math.nan)
    for i, r in enumerate(rows):
        a[i, :len(r)] = r
    return a


@bi('readmatrix', 'csvread', 'dlmread')
def readmatrix(nargout, *args):
    p = abspath(sval(args[0], 'file name', 'readmatrix'))
    if not os.path.isfile(p):
        raise err('MATLAB:textio:textio:FileNotFound', f"Unable to find or open '{sval(args[0], 'file name', 'readmatrix')}'. Check the path and filename or file permissions.", 'readmatrix')
    delim = None
    r0 = c0 = 0
    rest = list(args[1:])
    if rest and opt_str(rest[0]) is not None and opt_str(rest[0]).lower() not in ('delimiter', 'numheaderlines', 'range'):
        delim = unescape(opt_str(rest[0]))
        rest = rest[1:]
    if len(rest) >= 2 and opt_str(rest[0]) is None:
        r0, c0 = int(num(rest[0])), int(num(rest[1]))
        rest = rest[2:]
    i = 0
    while i + 1 < len(rest):
        k = opt_str(rest[i]).lower()
        if k == 'delimiter':
            delim = unescape(py_str(rest[i + 1]))
        elif k == 'numheaderlines':
            r0 = int(num(rest[i + 1]))
        i += 2
    a = _read_numeric(p, delim, r0, c0)
    return out(a) if type(a) is np.ndarray else a


@bi('writematrix', 'csvwrite', 'dlmwrite')
def writematrix(nargout, *args):
    a = args[0]
    p = abspath(sval(args[1], 'file name', 'writematrix')) if len(args) > 1 else abspath('matrix.txt')
    delim = ','
    i = 2
    while i < len(args):
        k = opt_str(args[i])
        if k is None:
            i += 1
            continue
        if k.lower() == 'delimiter':
            delim = unescape(py_str(args[i + 1]))
            delim = {'tab': '\t', 'space': ' ', 'comma': ',', 'semi': ';'}.get(delim, delim)
            i += 2
        elif k.lower() in ('precision', 'newline', 'writemode'):
            i += 2
        else:
            if i == 2 and len(k) <= 2:
                delim = unescape(k)
            i += 1
    if type(a) is Cell:
        rows = [[_cell_text(x) for x in row] for row in a.a]
    else:
        A = arr(a)
        if A.ndim == 1:
            A = A.reshape(1, -1)
        rows = [[_num_cell(x) for x in row] for row in A]
    with open(p, 'w', encoding='utf-8') as f:
        for row in rows:
            f.write(delim.join(row) + '\n')
    files_changed(os.path.dirname(p))
    return None


def _num_cell(x):
    if isinstance(x, (bool, np.bool_)):
        return '1' if x else '0'
    x = float(x.real if isinstance(x, complex) else x)
    if x != x:
        return 'NaN'
    if x == int(x) and abs(x) < 1e15:
        return str(int(x))
    return f'{x:.15g}'


def _cell_text(x):
    if type(x) in (Char, Str):
        return py_str(x)
    if numel(x) == 1:
        return _num_cell(arr(x).reshape(-1)[0])
    return ''


@bi('readcell')
def readcell(nargout, *args):
    p = abspath(sval(args[0], 'file name', 'readcell'))
    with open(p, encoding='utf-8', errors='replace') as f:
        lines = [l.rstrip('\n\r') for l in f if l.strip()]
    rows = [l.split(',') for l in lines]
    w = max(len(r) for r in rows) if rows else 0
    c = np.empty((len(rows), w), object)
    for i, r in enumerate(rows):
        for j in range(w):
            x = r[j].strip() if j < len(r) else ''
            try:
                c[i, j] = float(x)
            except ValueError:
                c[i, j] = Char.of(x)
    return Cell(c)


@bi('writecell')
def writecell(nargout, *args):
    return writematrix(nargout, *args)


# ---- load and save --------------------------------------------------------------------------------

def to_py_mat(v):
    """A value as scipy.io.savemat takes it."""
    t = type(v)
    if t is float or t is bool or t is complex:
        return np.array([[v]])
    if t is np.ndarray:
        return v
    if t is Char:
        if v.a.size == 0:
            return np.array([''])
        rows = v.row_strs()
        return np.array(rows) if len(rows) > 1 else np.array([rows[0]])
    if t is Str:
        return np.array(['' if s is None else s for s in v.a.reshape(-1, order='F')], dtype=object).reshape(v.a.shape, order='F')
    if t is Cell:
        a = np.empty(v.a.shape, object)
        for i in range(v.a.size):
            a.flat[i] = to_py_mat(v.a.flat[i])
        return a
    if t is Struct:
        keys = list(v.f)
        if v.size == 1:
            return {k: to_py_mat(v.f[k].item(0)) for k in keys}
        dt = [(k, object) for k in keys]
        a = np.empty(v.shape, dtype=dt)
        for k in keys:
            for i in range(v.size):
                a[k].flat[i] = to_py_mat(v.f[k].flat[i])
        return a
    if isinstance(v, FH):
        return np.array([v.text()])
    if isinstance(v, Obj):
        return np.array([class_of(v)])
    return np.array([[0.0]])


def from_py_mat(x):
    """A value read by scipy.io.loadmat, as the language holds it."""
    if isinstance(x, np.ndarray):
        if x.dtype.kind in 'US':
            if x.size == 0:
                return Char.of('')
            strs = [str(s) for s in x.reshape(-1)]
            return Char.of(strs[0]) if len(strs) == 1 else Char.rows(strs)
        if x.dtype.names:
            if x.size == 1:
                return Struct.scalar({k: from_py_mat(x[k].reshape(-1)[0]) for k in x.dtype.names})
            s = Struct(_2d(x).shape, {})
            for k in x.dtype.names:
                a = np.empty(s.shape, object)
                for i in range(x.size):
                    a.flat[i] = from_py_mat(x[k].flat[i])
                s.f[k] = a
            return s
        if x.dtype == object:
            a = np.empty(_2d(x).shape, object)
            for i in range(x.size):
                a.flat[i] = from_py_mat(x.flat[i])
            return Cell(a)
        if x.dtype.kind == 'b':
            return out(x)
        if x.dtype.kind in 'iu':
            return make(_2d(x), DTYPE_CLASS[x.dtype.newbyteorder('=')]) if x.dtype.newbyteorder('=') in DTYPE_CLASS else out(x.astype(F64))
        if x.dtype == np.float32:
            return make(_2d(x), 'single')
        return out(x.astype(C128 if x.dtype.kind == 'c' else F64))
    if isinstance(x, str):
        return Char.of(x)
    if isinstance(x, dict):
        return Struct.scalar({k: from_py_mat(v) for k, v in x.items()})
    if hasattr(x, '_fieldnames'):
        return Struct.scalar({k: from_py_mat(getattr(x, k)) for k in x._fieldnames})
    if isinstance(x, (int, float, complex, np.number)):
        return out(np.array([[x]]))
    return EMPTY()


@bi('save', ws=True)
def save(W, nargout, *args):
    words = [sval(a, 'argument', 'save') for a in args]
    fname = None
    names = []
    ascii_ = False
    double_ = False
    tabs = False
    append = False
    struct_mode = False
    version = '-v7'
    for w in words:
        if w.startswith('-'):
            lw = w.lower()
            if lw == '-ascii':
                ascii_ = True
            elif lw == '-double':
                double_ = True
            elif lw == '-tabs':
                tabs = True
            elif lw == '-append':
                append = True
            elif lw == '-struct':
                struct_mode = True
            elif lw in ('-v4', '-v6', '-v7', '-v7.3', '-mat'):
                version = lw
            continue
        if fname is None:
            fname = w
        else:
            names.append(w)
    if fname is None:
        fname = 'matlab.mat'
    if not ascii_ and not os.path.splitext(fname)[1]:
        fname += '.mat'
    p = abspath(fname)
    if struct_mode:
        s = W[names[0]]
        fields = names[1:] or list(s.f)
        data = {k: s.f[k].item(0) for k in fields}
    else:
        if not names:
            data = {k: W[k] for k in sorted(W)}
        else:
            import fnmatch
            data = {}
            for n in names:
                if any(c in n for c in '*?'):
                    for k in fnmatch.filter(list(W), n):
                        data[k] = W[k]
                else:
                    if n not in W:
                        raise err('MATLAB:save:couldNotWriteFile', f"Variable '{n}' not found.", 'save')
                    data[n] = W[n]
    if ascii_:
        with open(p, 'a' if append else 'w', encoding='utf-8') as f:
            for k, v in data.items():
                a = arr(v)
                if a.ndim == 1:
                    a = a.reshape(1, -1)
                for row in a.reshape(a.shape[0], -1):
                    if double_:
                        f.write(('\t' if tabs else '   ').join(f'{float(x):.16e}' for x in row) + '\n')
                    else:
                        f.write(('\t' if tabs else '   ').join(f'{float(x):.7e}' for x in row) + '\n')
        files_changed(os.path.dirname(p))
        return None
    import scipy.io as sio
    mdict = {}
    if append and os.path.isfile(p):
        try:
            mdict = {k: v for k, v in sio.loadmat(p).items() if not k.startswith('__')}
        except Exception:
            mdict = {}
    for k, v in data.items():
        if isinstance(v, (FH,)) or (isinstance(v, Obj) and not hasattr(v, 'opts')):
            R.warn('MATLAB:save:cannotSaveObject', f"Variable '{k}' of class {class_of(v)} was not saved.")
            continue
        mdict[k] = to_py_mat(v)
    sio.savemat(p, mdict, format='4' if version == '-v4' else '5', do_compression=version in ('-v7', '-v7.3', '-mat'), oned_as='row')
    files_changed(os.path.dirname(p))
    return None


def _load_mat(p):
    import scipy.io as sio
    try:
        d = sio.loadmat(p, squeeze_me=False, struct_as_record=True, mat_dtype=False, chars_as_strings=True)
    except NotImplementedError:
        return _load_mat73(p)
    return {k: from_py_mat(v) for k, v in d.items() if not k.startswith('__')}


def _load_mat73(p):
    try:
        import h5py
    except ImportError:
        raise err('MATLAB:load:v73', 'Version 7.3 MAT-files (HDF5) need the h5py package, which is not loaded here.', 'load')
    out_d = {}
    with h5py.File(p, 'r') as f:
        for k in f:
            if k.startswith('#'):
                continue
            out_d[k] = _h5_value(f, f[k])
    return out_d


def _h5_value(f, node):
    import h5py
    cls = node.attrs.get('MATLAB_class', b'double')
    cls = cls.decode() if isinstance(cls, bytes) else str(cls)
    if isinstance(node, h5py.Group):
        return Struct.scalar({k: _h5_value(f, node[k]) for k in node})
    data = node[()]
    if cls == 'char':
        a = np.asarray(data).T
        return Char(_2d(a.astype(np.uint16)))
    if cls == 'cell':
        refs = np.asarray(data).T
        c = np.empty(refs.shape, object)
        for i in range(refs.size):
            c.flat[i] = _h5_value(f, f[refs.flat[i]])
        return Cell(_2d(c))
    a = np.asarray(data)
    if a.dtype.names and 'real' in a.dtype.names:
        a = a['real'] + 1j * a['imag']
    a = a.T
    if cls == 'logical':
        return out(a.astype(bool))
    if cls in INT_TYPES:
        return make(_2d(a), cls)
    if cls == 'single':
        return make(_2d(a), 'single')
    return out(_2d(a.astype(C128 if a.dtype.kind == 'c' else F64)))


@bi('load', ws=True)
def load(W, nargout, *args):
    words = [sval(a, 'argument', 'load') for a in args]
    fname = None
    names = []
    ascii_ = False
    for w in words:
        if w.startswith('-'):
            if w.lower() == '-ascii':
                ascii_ = True
            continue
        if fname is None:
            fname = w
        else:
            names.append(w)
    if fname is None:
        fname = 'matlab.mat'
    p = abspath(fname)
    if not os.path.isfile(p) and os.path.isfile(p + '.mat'):
        p += '.mat'
    if not os.path.isfile(p):
        raise err('MATLAB:load:couldNotReadFile', f"Unable to find file or directory '{fname}'.", 'load')
    with open(p, 'rb') as fh:
        head = fh.read(128)
    is_mat = (not ascii_) and (p.lower().endswith('.mat') or head[:6] == b'MATLAB')
    if is_mat:
        data = _load_mat(p)
        if names:
            import fnmatch
            data = {k: v for k, v in data.items() if any(fnmatch.fnmatch(k, n) for n in names)}
    else:
        a = _read_numeric(p)
        var = re.sub(r'\W', '_', os.path.splitext(os.path.basename(p))[0])
        if not var or not var[0].isalpha():
            var = 'X' + var
        data = {var: out(a) if type(a) is np.ndarray else a}
        if nargout:
            return data[var]
    if nargout:
        return Struct.scalar(data)
    for k, v in data.items():
        W[k] = v
    return None


@bi('matfile')
def matfile(nargout, *args):
    p = abspath(sval(args[0], 'file name', 'matfile'))
    return Struct.scalar(_load_mat(p))


@bi('importdata')
def importdata(nargout, *args):
    p = abspath(sval(args[0], 'file name', 'importdata'))
    if p.lower().endswith('.mat'):
        d = _load_mat(p)
        if len(d) == 1:
            return next(iter(d.values()))
        return Struct.scalar(d)
    a = _read_numeric(p)
    return out(a) if type(a) is np.ndarray else a

