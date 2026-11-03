"""Images, sound files and the web: imread, imwrite, imfinfo, audioread,
audiowrite, audioinfo, webread, webwrite, websave, weboptions."""
import io
import json
import math
import os
import sys
import time

import numpy as np

from . import bi
from ._util import err, nargchk, arr, darr, out, opt_str, num, is_str
from ..values import Char, Cell, Struct, Str, Obj, F64, class_of, shape_of, numel, py_str, text_list
from .. import runtime as R


def _abspath(name):
    from .iofun import abspath
    return abspath(name)


async def _pil():
    """Pillow, imported; in the page, Pyodide loads the package the first time."""
    try:
        from PIL import Image
    except ImportError:
        if sys.platform != 'emscripten':
            raise err('MATLAB:imread:NoPillow', 'Images need the Pillow package (pip install pillow).')
        import pyodide_js
        await pyodide_js.loadPackage('pillow')
        from PIL import Image
    return Image


def _changed(path):
    from .iofun import files_changed
    files_changed(os.path.dirname(path))


# ---- images ---------------------------------------------------------------------------------------------

def _find_image(name, fmt, fn):
    p = _abspath(name)
    if os.path.isfile(p):
        return p
    if fmt and os.path.isfile(p + '.' + fmt):
        return p + '.' + fmt
    raise err(f'MATLAB:{fn}:fileDoesNotExist', f"File \"{name}\" does not exist.", fn)


@bi('imread', aw=True, nout=3)
async def imread(nargout, *args):
    """[A, map, alpha] = imread(filename, fmt): the image's pixels, uint8 (or
    uint16 for 16-bit images), m-by-n for gray, m-by-n-by-3 for colour; an
    image with a palette gives its indices (from 0) and the colormap."""
    nargchk(args, 1, 4, 'imread')
    Image = await _pil()
    name = py_str(args[0])
    fmt = py_str(args[1]) if len(args) > 1 and is_str(args[1]) else None
    p = _find_image(name, fmt, 'imread')
    try:
        im = Image.open(p)
        frame = 0
        for i, a in enumerate(args[1:]):
            if is_str(a) and py_str(a).lower() in ('index', 'frames') and i + 2 < len(args):
                frame = int(num(args[i + 2])) - 1
        if frame:
            im.seek(frame)
        im.load()
    except Exception as e:
        raise err('MATLAB:imread:fileFormat', f'Unable to read the image in "{name}": {e}.', 'imread')
    cmap, alpha = np.zeros((0, 3)), np.zeros((0, 0))
    mode = im.mode
    if mode == 'P':
        pal = np.array(im.getpalette() or [], F64).reshape(-1, 3) / 255
        A = np.asarray(im, np.uint8)
        cmap = pal[:max(int(A.max()) + 1, 1)] if A.size else pal
        if 'transparency' in im.info and nargout > 2:
            alpha = np.asarray(im.convert('RGBA'), np.uint8)[:, :, 3]
    elif mode in ('1',):
        A = np.asarray(im, bool)
    elif mode in ('L',):
        A = np.asarray(im, np.uint8)
    elif mode in ('I;16', 'I;16B', 'I;16L', 'I'):
        A = np.asarray(im).astype(np.uint16) if mode != 'I' else np.asarray(im).astype(np.int64)
        if A.dtype == np.int64:
            A = np.clip(A, 0, 65535).astype(np.uint16)
    elif mode in ('LA',):
        a = np.asarray(im, np.uint8)
        A, alpha = a[:, :, 0], a[:, :, 1]
    elif mode == 'RGBA':
        a = np.asarray(im, np.uint8)
        A, alpha = a[:, :, :3], a[:, :, 3]
    elif mode == 'RGB':
        A = np.asarray(im, np.uint8)
    elif mode == 'CMYK':
        A = np.asarray(im, np.uint8)
    else:
        A = np.asarray(im.convert('RGB'), np.uint8)
    A = np.ascontiguousarray(A)
    res = [A if A.dtype != bool else out(A), out(cmap), alpha]
    return res[0] if nargout <= 1 else tuple(res[:nargout])


_FMT = {'png': 'PNG', 'jpg': 'JPEG', 'jpeg': 'JPEG', 'bmp': 'BMP', 'tif': 'TIFF', 'tiff': 'TIFF', 'gif': 'GIF'}


@bi('imwrite', aw=True)
async def imwrite(nargout, *args):
    """imwrite(A, filename) or imwrite(X, map, filename), the format from the
    name (or given): PNG, JPEG, BMP, TIFF or GIF. Doubles are taken as 0 to
    1, uint8 and uint16 as they are; options 'Quality' (JPEG) and 'Alpha'
    (PNG)."""
    nargchk(args, 2, None, 'imwrite')
    Image = await _pil()
    A = args[0]
    rest = list(args[1:])
    cmap = None
    if rest and not is_str(rest[0]):
        cmap = np.asarray(darr(rest.pop(0)), F64)
    if not rest or not is_str(rest[0]):
        raise err('MATLAB:imwrite:noFileName', 'The file name is missing.', 'imwrite')
    name = py_str(rest.pop(0))
    fmt = None
    if rest and is_str(rest[0]) and py_str(rest[0]).lower() in _FMT:
        fmt = _FMT[py_str(rest.pop(0)).lower()]
    ext = os.path.splitext(name)[1].lower().lstrip('.')
    if fmt is None:
        if ext not in _FMT:
            raise err('MATLAB:imwrite:fileFormat', 'Give the format by the file name (.png, .jpg, .bmp, .tif, .gif) or as an argument.', 'imwrite')
        fmt = _FMT[ext]
    elif not ext:
        name = name + '.' + {'PNG': 'png', 'JPEG': 'jpg', 'BMP': 'bmp', 'TIFF': 'tif', 'GIF': 'gif'}[fmt]
    opts = {}
    alpha, alpha_cls = None, None
    for i in range(0, len(rest) - 1, 2):
        k = (opt_str(rest[i]) or '').lower()
        if k == 'quality':
            opts['quality'] = int(num(rest[i + 1]))
        elif k == 'alpha':
            alpha, alpha_cls = np.asarray(arr(rest[i + 1])), class_of(rest[i + 1])
        elif k in ('compression', 'mode', 'bitdepth', 'description', 'comment', 'author', 'loopcount', 'delaytime'):
            pass
        else:
            raise err('MATLAB:imwrite:InvalidOption', f"Unknown option '{opt_str(rest[i])}'.", 'imwrite')
    a = np.asarray(arr(A))
    cls = class_of(A)

    def to8(x):
        if cls in ('double', 'single'):
            return np.clip(np.round(np.nan_to_num(x) * 255), 0, 255).astype(np.uint8)
        if cls == 'logical':
            return (x.astype(np.uint8) * 255)
        if cls == 'uint16':
            return x if fmt in ('PNG', 'TIFF') else (x >> 8).astype(np.uint8)
        return np.clip(x, 0, 255).astype(np.uint8)
    if cmap is not None:
        idx = a.astype(np.int64) - (1 if cls in ('double', 'single') else 0)
        im = Image.fromarray(np.clip(idx, 0, 255).astype(np.uint8), mode='P')
        im.putpalette(list(np.clip(np.round(cmap.reshape(-1, 3) * 255), 0, 255).astype(np.uint8).reshape(-1)))
    elif a.ndim == 2:
        b = to8(a)
        if b.dtype == np.uint16:
            im = Image.fromarray(b.astype('<u2'), mode='I;16')
        elif cls == 'logical' and fmt in ('PNG', 'TIFF', 'BMP'):
            im = Image.fromarray(a.astype(bool))
        else:
            im = Image.fromarray(b, mode='L')
    elif a.ndim == 3 and a.shape[2] in (3, 4):
        b = to8(a)
        if b.dtype == np.uint16:
            b = (b >> 8).astype(np.uint8)
        im = Image.fromarray(np.ascontiguousarray(b), mode='RGB' if a.shape[2] == 3 else 'RGBA')
    else:
        raise err('MATLAB:imwrite:wrongDimensions', 'The image must be m-by-n or m-by-n-by-3.', 'imwrite')
    if alpha is not None:
        al = np.clip(np.round(alpha * 255), 0, 255) if alpha_cls in ('double', 'single') else alpha
        im = im.convert('RGBA' if im.mode in ('RGB', 'P') else 'LA')
        im.putalpha(Image.fromarray(al.astype(np.uint8), mode='L'))
    if fmt == 'JPEG' and im.mode not in ('RGB', 'L'):
        im = im.convert('RGB')
    p = _abspath(name)
    try:
        im.save(p, fmt, **opts)
    except Exception as e:
        raise err('MATLAB:imwrite:fileOpen', f'Unable to write "{name}": {e}.', 'imwrite')
    _changed(p)
    return None


@bi('imfinfo', aw=True)
async def imfinfo(nargout, *args):
    """A struct of an image file's facts: Filename, FileModDate, FileSize,
    Format, Width, Height, BitDepth, ColorType."""
    nargchk(args, 1, 2, 'imfinfo')
    Image = await _pil()
    name = py_str(args[0])
    p = _find_image(name, py_str(args[1]) if len(args) > 1 else None, 'imfinfo')
    try:
        im = Image.open(p)
    except Exception as e:
        raise err('MATLAB:imfinfo:whatFormat', f'Unable to read "{name}" as an image: {e}.', 'imfinfo')
    bands = len(im.getbands())
    depth = {'1': 1, 'L': 8, 'P': 8, 'RGB': 24, 'RGBA': 32, 'LA': 16, 'CMYK': 32, 'I;16': 16, 'I;16B': 16, 'I': 32, 'F': 32}.get(im.mode, 8 * bands)
    ctype = 'indexed' if im.mode == 'P' else ('grayscale' if im.mode in ('1', 'L', 'LA', 'I;16', 'I;16B', 'I', 'F') else 'truecolor')
    st = os.stat(p)
    return Struct.scalar({
        'Filename': Char.of(p), 'FileModDate': Char.of(time.strftime('%d-%b-%Y %H:%M:%S', time.localtime(st.st_mtime))),
        'FileSize': float(st.st_size), 'Format': Char.of((im.format or '').lower().replace('jpeg', 'jpg')),
        'Width': float(im.size[0]), 'Height': float(im.size[1]), 'BitDepth': float(depth), 'ColorType': Char.of(ctype)})


# ---- sound files --------------------------------------------------------------------------------------------

def _wav_path(name, fn):
    p = _abspath(name)
    if not os.path.isfile(p):
        raise err(f'MATLAB:{fn}:FileNotFound', f'The file "{name}" does not exist.', fn)
    if not p.lower().endswith(('.wav', '.wave')):
        raise err(f'MATLAB:{fn}:FileTypeNotSupported', 'Only WAV files are read here.', fn)
    return p


def _wav_bits(data):
    return {np.dtype(np.uint8): 8, np.dtype(np.int16): 16, np.dtype(np.int32): 32, np.dtype(np.float32): 32, np.dtype(np.float64): 64}.get(data.dtype, 16)


@bi('audioread', nout=2)
def audioread(nargout, *args):
    """[y, Fs] = audioread(filename, [start stop], 'native'): the samples of a
    WAV file, one column per channel, as doubles in [-1, 1) (or in the file's
    own class with 'native'), and the sample rate."""
    nargchk(args, 1, 3, 'audioread')
    from scipy.io import wavfile
    p = _wav_path(py_str(args[0]), 'audioread')
    try:
        fs, data = wavfile.read(p)
    except Exception as e:
        raise err('MATLAB:audioread:FileTypeNotSupported', f'Unable to read the WAV file: {e}.', 'audioread')
    data = data.reshape(data.shape[0], -1)
    rng_ = None
    native = False
    for a in args[1:]:
        if is_str(a):
            k = py_str(a).lower()
            if k not in ('native', 'double'):
                raise err('MATLAB:audioread:InvalidDataType', "The data type is 'double' or 'native'.", 'audioread')
            native = k == 'native'
        else:
            r = darr(a).reshape(-1)
            rng_ = (int(r[0]), int(r[1]) if math.isfinite(r[1]) else data.shape[0])
    if rng_ is not None:
        lo, hi = rng_
        if lo < 1 or hi > data.shape[0] or hi < lo:
            raise err('MATLAB:audioread:InvalidRange', 'The range of samples is outside the file.', 'audioread')
        data = data[lo - 1:hi]
    if native:
        y = data if data.dtype != np.float64 else data
    elif data.dtype == np.uint8:
        y = (data.astype(F64) - 128) / 128
    elif data.dtype == np.int16:
        y = data.astype(F64) / 32768
    elif data.dtype == np.int32:
        y = data.astype(F64) / 2147483648
    else:
        y = data.astype(F64)
    y = out(y) if y.dtype in (F64, np.dtype(bool)) else np.ascontiguousarray(y)
    return (y, float(fs)) if nargout > 1 else y


@bi('audiowrite')
def audiowrite(nargout, *args):
    """audiowrite(filename, y, Fs, 'BitsPerSample', b): a WAV file of the
    samples (a column per channel); doubles in [-1, 1] become 16-bit
    integers unless BitsPerSample says 8, 24 (written as 32), 32 or 64
    (floating point)."""
    nargchk(args, 3, None, 'audiowrite')
    from scipy.io import wavfile
    name = py_str(args[0])
    if not name.lower().endswith(('.wav', '.wave')):
        raise err('MATLAB:audiowrite:FileTypeNotSupported', 'Only WAV files are written here.', 'audiowrite')
    y = np.asarray(arr(args[1]))
    if y.ndim == 2 and y.shape[0] == 1 and y.shape[1] > 1:
        y = y.reshape(-1, 1)
    fs = int(num(args[2]))
    bits = None
    rest = list(args[3:])
    for i in range(0, len(rest) - 1, 2):
        k = (opt_str(rest[i]) or '').lower()
        if k == 'bitspersample':
            bits = int(num(rest[i + 1]))
        elif k in ('title', 'artist', 'comment', 'bitrate', 'quality'):
            pass
        else:
            raise err('MATLAB:audiowrite:InvalidOption', f"Unknown option '{opt_str(rest[i])}'.", 'audiowrite')
    cls = class_of(args[1])
    if cls in ('double', 'single'):
        yc = np.clip(np.nan_to_num(y.astype(F64)), -1, 1)
        b = bits or 16
        if b == 8:
            data = np.clip(np.round(yc * 128 + 128), 0, 255).astype(np.uint8)
        elif b == 16:
            data = np.clip(np.round(yc * 32768), -32768, 32767).astype(np.int16)
        elif b == 24:
            # SciPy writes no 24-bit samples: 32-bit integers keep all of them
            data = np.clip(np.round(yc * 2147483648), -2147483648, 2147483647).astype(np.int32)
        elif b == 32:
            data = yc.astype(np.float32)
        elif b == 64:
            data = yc.astype(np.float64)
        else:
            raise err('MATLAB:audiowrite:InvalidBitsPerSample', 'BitsPerSample is 8, 16, 24, 32 or 64.', 'audiowrite')
    elif cls in ('uint8', 'int16', 'int32'):
        data = y
    else:
        raise err('MATLAB:audiowrite:InvalidDataType', 'The samples must be double, single, uint8, int16 or int32.', 'audiowrite')
    p = _abspath(name)
    wavfile.write(p, fs, data.squeeze(axis=1) if data.ndim == 2 and data.shape[1] == 1 else data)
    _changed(p)
    return None


@bi('audioinfo')
def audioinfo(nargout, *args):
    """A struct of a WAV file's facts: Filename, CompressionMethod,
    NumChannels, SampleRate, TotalSamples, Duration, BitsPerSample."""
    nargchk(args, 1, 1, 'audioinfo')
    from scipy.io import wavfile
    p = _wav_path(py_str(args[0]), 'audioinfo')
    fs, data = wavfile.read(p, mmap=False)
    data = data.reshape(data.shape[0], -1)
    return Struct.scalar({'Filename': Char.of(p), 'CompressionMethod': Char.of('Uncompressed'),
                          'NumChannels': float(data.shape[1]), 'SampleRate': float(fs), 'TotalSamples': float(data.shape[0]),
                          'Duration': data.shape[0] / float(fs), 'Title': np.zeros((0, 0)), 'Comment': np.zeros((0, 0)),
                          'Artist': np.zeros((0, 0)), 'BitsPerSample': float(_wav_bits(data))})


# ---- the web ------------------------------------------------------------------------------------------------

class WebOptions(Obj):
    """weboptions: how webread, webwrite and websave make their requests."""
    __slots__ = ('p',)
    cls = 'weboptions'

    DEFAULTS = {'CharacterEncoding': 'auto', 'UserAgent': 'PyLAB', 'Timeout': 5.0, 'Username': '', 'Password': '',
                'KeyName': '', 'KeyValue': '', 'ContentType': 'auto', 'ContentReader': None, 'MediaType': 'auto',
                'RequestMethod': 'auto', 'ArrayFormat': 'csv', 'HeaderFields': None}

    def __init__(self, p=None):
        self.p = dict(self.DEFAULTS)
        if p:
            self.p.update(p)

    def getprop(self, name):
        for k in self.p:
            if k.lower() == name.lower():
                v = self.p[k]
                if v is None:
                    return np.zeros((0, 0))
                return Char.of(v) if isinstance(v, str) else v
        return super().getprop(name)

    def setprop(self, name, value):
        for k in self.p:
            if k.lower() == name.lower():
                q = WebOptions(self.p)
                q.p[k] = py_str(value) if is_str(value) else (float(num(value)) if k == 'Timeout' else value)
                return q
        return super().setprop(name, value)

    def propnames(self):
        return list(self.p)

    def display_lines(self):
        lines = ['  weboptions with properties:', '']
        for k, v in self.p.items():
            shown = f"'{v}'" if isinstance(v, str) else ('[]' if v is None else (f'{v:g}' if isinstance(v, float) else '{...}'))
            lines.append(f'{k:>21}: {shown}')
        return lines


@bi('weboptions', arr=False)
def weboptions(nargout, *args):
    """weboptions(Name, Value, ...): options for webread, webwrite and websave
    (Timeout, ContentType, MediaType, RequestMethod, HeaderFields,
    Username, Password, KeyName, KeyValue, CharacterEncoding, UserAgent)."""
    o = WebOptions()
    if len(args) % 2:
        raise err('MATLAB:weboptions:nameValue', 'Options come in name-value pairs.', 'weboptions')
    for i in range(0, len(args), 2):
        o = o.setprop(py_str(args[i]), args[i + 1])
    return o


def _query_text(v):
    if is_str(v):
        return py_str(v)
    a = np.asarray(arr(v)).reshape(-1)
    return ','.join(f'{x:g}' if isinstance(x, (float, np.floating)) else str(x) for x in a)


def _split_web_args(args, fn):
    """The URL, the name-value pairs to send, and the options."""
    url = py_str(args[0])
    rest = list(args[1:])
    opts = WebOptions()
    if rest and isinstance(rest[-1], WebOptions):
        opts = rest.pop()
    return url, rest, opts


async def _request(url, method, body, headers, opts, fn):
    """(status, content type, bytes): pyfetch in the page, urllib elsewhere."""
    hdrs = {'User-Agent': opts.p['UserAgent']}
    hdrs.update(headers)
    hf = opts.p.get('HeaderFields')
    if isinstance(hf, Cell):
        a = hf.a
        for i in range(a.shape[0]):
            hdrs[py_str(a[i, 0])] = py_str(a[i, 1])
    if opts.p['KeyName']:
        hdrs[opts.p['KeyName']] = opts.p['KeyValue']
    if opts.p['Username']:
        import base64
        tok = base64.b64encode(f"{opts.p['Username']}:{opts.p['Password']}".encode()).decode()
        hdrs['Authorization'] = 'Basic ' + tok
    if sys.platform == 'emscripten':
        from pyodide.http import pyfetch
        try:
            kw = {'method': method, 'headers': hdrs}
            if body is not None:
                kw['body'] = body
            r = await pyfetch(url, **kw)
            data = await r.bytes()
            return r.status, r.headers.get('content-type', ''), data
        except Exception as e:
            raise err(f'MATLAB:webservices:HTTP', f'The request to {url} failed: {e}. (The page can reach only servers that allow it, CORS.)', fn)
    import urllib.request
    import urllib.error
    req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=float(opts.p['Timeout'])) as r:
            return r.status, r.headers.get('Content-Type', ''), r.read()
    except urllib.error.HTTPError as e:
        raise err(f'MATLAB:webservices:HTTP{e.code}StatusCodeError', f'The server returned the status {e.code} with message "{e.reason}" in response to the request to URL {url}.', fn)
    except Exception as e:
        raise err('MATLAB:webservices:UnknownHost', f'The request to {url} failed: {e}.', fn)


async def _decode_response(ctype, data, opts, fn):
    """The response as a value by its content type: JSON as jsondecode gives
    it, text as characters, an image as imread gives it, other data as
    uint8."""
    want = opts.p['ContentType']
    ct = (ctype or '').split(';')[0].strip().lower()
    if want == 'auto':
        if 'json' in ct:
            want = 'json'
        elif ct.startswith('text/') or 'xml' in ct or 'javascript' in ct:
            want = 'text'
        elif ct.startswith('image/'):
            want = 'image'
        else:
            want = 'binary'
    if want == 'json':
        from .iofun import _json_value
        try:
            return _json_value(json.loads(data.decode('utf-8', errors='replace')))
        except ValueError:
            return Char.of(data.decode('utf-8', errors='replace'))
    if want in ('text', 'raw'):
        return Char.of(data.decode('utf-8', errors='replace'))
    if want == 'image':
        Image = await _pil()
        im = Image.open(io.BytesIO(data))
        return np.ascontiguousarray(np.asarray(im.convert('RGB') if im.mode not in ('L', 'RGB') else im, np.uint8))
    return np.frombuffer(data, np.uint8).reshape(-1, 1).copy()


@bi('webread', aw=True)
async def webread(nargout, *args):
    """data = webread(url, QueryName, QueryValue, ..., options): a GET request,
    the query added to the URL; the answer as its content type says (JSON as
    structs and arrays, text, an image, or bytes)."""
    nargchk(args, 1, None, 'webread')
    from urllib.parse import urlencode
    url, rest, opts = _split_web_args(args, 'webread')
    if len(rest) % 2:
        raise err('MATLAB:webread:nameValue', 'The query comes in name-value pairs.', 'webread')
    if rest:
        q = urlencode([(py_str(rest[i]), _query_text(rest[i + 1])) for i in range(0, len(rest), 2)])
        url = url + ('&' if '?' in url else '?') + q
    status, ctype, data = await _request(url, 'GET', None, {}, opts, 'webread')
    return await _decode_response(ctype, data, opts, 'webread')


@bi('webwrite', aw=True)
async def webwrite(nargout, *args):
    """response = webwrite(url, PostName, PostValue, ..., options), a form
    POST; or webwrite(url, data, options), a struct or array sent as JSON
    (text as it is)."""
    nargchk(args, 2, None, 'webwrite')
    from urllib.parse import urlencode
    url, rest, opts = _split_web_args(args, 'webwrite')
    if len(rest) == 1:
        d = rest[0]
        if is_str(d) and opts.p['MediaType'] == 'auto':
            body, ctype = py_str(d).encode(), 'text/plain'
        else:
            from .iofun import _json_data
            body, ctype = json.dumps(_json_data(d, True), separators=(',', ':')).encode(), 'application/json'
    else:
        if len(rest) % 2:
            raise err('MATLAB:webwrite:nameValue', 'The data comes in name-value pairs.', 'webwrite')
        body = urlencode([(py_str(rest[i]), _query_text(rest[i + 1])) for i in range(0, len(rest), 2)]).encode()
        ctype = 'application/x-www-form-urlencoded'
    if opts.p['MediaType'] != 'auto':
        ctype = opts.p['MediaType']
    method = 'POST' if opts.p['RequestMethod'] == 'auto' else opts.p['RequestMethod'].upper()
    status, rtype, data = await _request(url, method, body, {'Content-Type': ctype}, opts, 'webwrite')
    return await _decode_response(rtype, data, opts, 'webwrite')


@bi('websave', aw=True)
async def websave(nargout, *args):
    """filename = websave(filename, url, QueryName, QueryValue, ..., options):
    the answer to a GET request saved to a file; the file's full name."""
    nargchk(args, 2, None, 'websave')
    from urllib.parse import urlencode
    name = py_str(args[0])
    url, rest, opts = _split_web_args(args[1:], 'websave')
    if rest:
        q = urlencode([(py_str(rest[i]), _query_text(rest[i + 1])) for i in range(0, len(rest) - 1, 2)])
        url = url + ('&' if '?' in url else '?') + q
    status, ctype, data = await _request(url, 'GET', None, {}, opts, 'websave')
    p = _abspath(name)
    if not os.path.splitext(p)[1]:
        ext = {'application/json': '.json', 'text/html': '.html', 'text/plain': '.txt', 'image/png': '.png', 'image/jpeg': '.jpg'}.get(ctype.split(';')[0].strip(), '')
        p += ext
    with open(p, 'wb') as f:
        f.write(data)
    _changed(p)
    return Char.of(p)
