"""Animated lines (animatedline, addpoints, clearpoints, getpoints) and
video files (VideoWriter with open, writeVideo and close; VideoReader with
readFrame, hasFrame and read).

Videos are AVI files written and read here: Motion JPEG (each frame a JPEG,
through Pillow), uncompressed RGB, or 8-bit gray. VideoReader also reads
animated GIFs. Other containers and codecs (MPEG-4, Motion JPEG 2000) need
encoders a browser page does not have.
"""
import io
import math
import os
import struct

import numpy as np

from . import bi as _register, REG
from ._util import err, nargchk, num, opt_str, is_str, darr, arr
from ..values import MError, Obj, Char, Cell, Struct, EMPTY, numel, py_str
from .. import runtime as R


def bi(*names, **kw):
    def deco(f):
        aw = kw.get('aw', False)
        if aw:
            async def g(*a):
                try:
                    return await f(*a)
                except MError:
                    raise
                except (ValueError, TypeError, IndexError, OSError, struct.error) as e:
                    raise err(f'MATLAB:{names[0]}:invalidInput', f'{names[0]}: {e}', names[0])
        else:
            def g(*a):
                try:
                    return f(*a)
                except MError:
                    raise
                except (ValueError, TypeError, IndexError, OSError, struct.error) as e:
                    raise err(f'MATLAB:{names[0]}:invalidInput', f'{names[0]}: {e}', names[0])
        g.__name__, g.__doc__ = f.__name__, f.__doc__
        return _register(*names, **kw)(g)
    return deco


# ---- animated lines -------------------------------------------------------------------------------------------------------------

def _animated_class():
    from ..graphics_base import Line, register

    class AnimatedLine(Line):
        """A line points are added to: drawn as a line, its Type 'animatedline'."""
        CLASSNAME = 'matlab.graphics.animation.AnimatedLine'
        DEFAULTS = dict(Line.DEFAULTS, MaximumNumPoints=1000000.0)

        def getprop(self, name):
            if name.lower() == 'type':
                return Char.of('animatedline')
            if name in ('XData', 'YData', 'ZData'):
                raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized property '{name}' for class 'AnimatedLine': its points are read with getpoints.")
            return super().getprop(name)
    register(AnimatedLine)
    return AnimatedLine


_AL = []


def _AnimatedLine():
    if not _AL:
        _AL.append(_animated_class())
    return _AL[0]


@bi('animatedline', arr=False)
def animatedline(nargout, *args):
    """an = animatedline(x, y, z, Name, Value), animatedline(ax, ...): a line to add points to with addpoints, drawn as they come (drawnow)."""
    from .graphics import split_axes_arg, gcf_, gca_, apply_props, handles_out, name_value
    ax, rest = split_axes_arg(args)
    if ax is None:
        ax = gca_(gcf_())
    data = []
    while rest and opt_str(rest[0]) is None and len(data) < 3:
        data.append(rest.pop(0))
    if len(data) == 1:
        raise err('MATLAB:animatedline:data', 'animatedline takes x and y (and z) together.', 'animatedline')
    pairs = name_value(rest, 0)
    h = _AnimatedLine()(ax)
    h.props['Color'] = ax.next_color()
    if data:
        for k, v in zip(('XData', 'YData', 'ZData'), data):
            h.props[k] = darr(v).astype(float).reshape(1, -1)
    apply_props(h, pairs)
    ax.touch()
    return handles_out([h]) if nargout else None


def _al(v, fn):
    from .graphics import _handles
    try:
        hs = _handles(v)
    except MError:
        hs = []
    h = hs[0] if len(hs) == 1 else None
    if h is None or not isinstance(h, _AnimatedLine()) or not h.valid:
        raise err(f'MATLAB:{fn}:handle', f'{fn} takes an animated line (from animatedline).', fn)
    return h


@bi('addpoints', arr=False)
def addpoints(nargout, *args):
    """addpoints(an, x, y, z): points added to the end of an animated line (the oldest dropped beyond its MaximumNumPoints)."""
    nargchk(args, 3, 4, 'addpoints')
    h = _al(args[0], 'addpoints')
    p = h.props
    new = [darr(a).astype(float).reshape(-1) for a in args[1:]]
    if len({v.size for v in new}) > 1:
        raise err('MATLAB:addpoints:size', 'x, y (and z) have as many values each.', 'addpoints')
    keys = ('XData', 'YData', 'ZData')[:len(new)]
    if len(new) == 2 and numel(p['ZData']):
        raise err('MATLAB:addpoints:z', 'This animated line is 3-D: give z too.', 'addpoints')
    cap = p.get('MaximumNumPoints', 1e6)
    cap = int(cap) if np.isfinite(cap) else None
    for k, v in zip(keys, new):
        a = np.concatenate([np.asarray(p[k], float).reshape(-1), v])
        if cap is not None and a.size > cap:
            a = a[-cap:]
        p[k] = a.reshape(1, -1)
    h.touch()
    return None


@bi('clearpoints', arr=False)
def clearpoints(nargout, *args):
    """clearpoints(an): all points taken off an animated line."""
    nargchk(args, 1, 1, 'clearpoints')
    h = _al(args[0], 'clearpoints')
    for k in ('XData', 'YData', 'ZData'):
        h.props[k] = np.zeros((1, 0))
    h.touch()
    return None


@bi('getpoints', nout=3, arr=False)
def getpoints(nargout, *args):
    """[x, y, z] = getpoints(an): the points of an animated line, as rows."""
    nargchk(args, 1, 1, 'getpoints')
    h = _al(args[0], 'getpoints')
    res = tuple(np.asarray(h.props[k], float).reshape(1, -1).copy() for k in ('XData', 'YData', 'ZData'))
    return res[:max(nargout, 1)] if nargout > 1 else res[0]


# ---- AVI files --------------------------------------------------------------------------------------------------------------------

_PROFILES = {'motion jpeg avi': ('MJPG', 'RGB24'), 'uncompressed avi': (None, 'RGB24'), 'grayscale avi': (None, 'Grayscale')}


def _rate(fps):
    """dwRate/dwScale for a frame rate (whole numbers exactly, others to a thousandth)."""
    if float(fps).is_integer():
        return int(fps), 1
    return int(round(fps * 1000)), 1000


def _avi_header(w, h, fps, frames, movi_size, codec, gray, max_frame):
    rate, scale = _rate(fps)
    bits = 8 if gray else 24
    pal = b''.join(struct.pack('<BBBB', i, i, i, 0) for i in range(256)) if gray else b''
    row = ((w * bits + 31) // 32) * 4
    strf = struct.pack('<IiiHHIIiiII', 40, w, h, 1, bits, struct.unpack('<I', codec.encode())[0] if codec else 0,
                       row * h if not codec else w * h * 3, 0, 0, 256 if gray else 0, 0) + pal
    strh = struct.pack('<4s4sIHHIIIIIIIIhhhh', b'vids', (codec or 'DIB ').encode(), 0, 0, 0, 0, scale, rate, 0, frames,
                       max_frame, 0xFFFFFFFF, 0, 0, 0, w, h)
    strl = b'LIST' + struct.pack('<I', 4 + 8 + len(strh) + 8 + len(strf)) + b'strl' + b'strh' + struct.pack('<I', len(strh)) + strh + b'strf' + struct.pack('<I', len(strf)) + strf
    avih = struct.pack('<IIIIIIIIII4I', int(round(1e6 / fps)), int(max_frame * fps), 0, 0x10, frames, 0, 1, max_frame, w, h, 0, 0, 0, 0)
    hdrl = b'LIST' + struct.pack('<I', 4 + 8 + len(avih) + len(strl)) + b'hdrl' + b'avih' + struct.pack('<I', len(avih)) + avih + strl
    riff_size = 4 + len(hdrl) + 8 + 4 + movi_size + (8 + 16 * frames if frames else 8)
    return b'RIFF' + struct.pack('<I', riff_size) + b'AVI ' + hdrl + b'LIST' + struct.pack('<I', 4 + movi_size) + b'movi'


class VideoWriter(Obj):
    cls = 'VideoWriter'
    is_handle = True
    __slots__ = ('path', 'profile', 'fps', 'quality', 'is_open', 'f', 'w', 'h', 'frames', 'index', 'movi', 'max_frame', 'pil')

    def __init__(self, path, profile):
        self.path, self.profile = path, profile
        self.fps, self.quality = 30.0, 75.0
        self.is_open = False
        self.f = None
        self.w = self.h = 0
        self.frames, self.index, self.movi, self.max_frame = 0, [], 0, 0
        self.pil = None

    @property
    def codec(self):
        return _PROFILES[self.profile.lower()][0]

    @property
    def gray(self):
        return _PROFILES[self.profile.lower()][1] == 'Grayscale'

    def props(self):
        return {'Duration': self.frames / self.fps, 'Filename': Char.of(os.path.basename(self.path)), 'Path': Char.of(os.path.dirname(self.path)),
                'FileFormat': Char.of('avi'), 'FrameCount': float(self.frames), 'FrameRate': self.fps,
                'Height': float(self.h) if self.h else EMPTY(), 'Width': float(self.w) if self.w else EMPTY(),
                'ColorChannels': 1.0 if self.gray else 3.0, 'VideoBitsPerPixel': 8.0 if self.gray else 24.0,
                'VideoCompressionMethod': Char.of('Motion JPEG' if self.codec else 'None'),
                'VideoFormat': Char.of('Grayscale' if self.gray else 'RGB24'), 'Quality': self.quality}

    def getprop(self, name):
        d = self.props()
        for k in d:
            if k.lower() == name.lower():
                return d[k]
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized property '{name}' for class 'VideoWriter'.")

    def setprop(self, name, value):
        k = name.lower()
        if k in ('framerate', 'quality'):
            if self.is_open or self.frames:
                raise MError('MATLAB:audiovideo:VideoWriter:openFile', f'{name} cannot be changed once the file is open.')
            v = float(num(value))
            if k == 'framerate':
                if not v > 0:
                    raise MError('MATLAB:audiovideo:VideoWriter:frameRate', 'FrameRate is positive.')
                self.fps = v
            else:
                if not 0 <= v <= 100:
                    raise MError('MATLAB:audiovideo:VideoWriter:quality', 'Quality is from 0 to 100.')
                self.quality = v
            return
        raise MError('MATLAB:class:SetProhibited', f"The property '{name}' of VideoWriter cannot be set.")

    def propnames(self):
        return list(self.props())

    def display_lines(self):
        d = self.props()
        w = max(len(k) for k in d)
        lines = ['  VideoWriter with properties:', '']
        for k, v in d.items():
            s = f"'{v.str()}'" if isinstance(v, Char) else ('[]' if numel(v) == 0 else f'{float(v):.4g}')
            lines.append(f'    {k.rjust(w)}: {s}')
        return lines

    # ---- writing ----
    def open(self):
        if self.is_open:
            return
        self.f = open(self.path, 'wb')
        self.is_open = True
        self.frames, self.index, self.movi, self.max_frame = 0, [], 0, 0

    def add(self, img):
        if not self.is_open:
            raise err('MATLAB:audiovideo:VideoWriter:notOpen', 'Open the file first: open(v).', 'writeVideo')
        h, w = img.shape[0], img.shape[1]
        if self.frames == 0:
            self.w, self.h = w, h
            self.f.write(b'\0' * len(self._header()))
        elif (w, h) != (self.w, self.h):
            raise err('MATLAB:audiovideo:VideoWriter:invalidDimensions', f'Each frame is {self.h}x{self.w}, as the first was; this one is {h}x{w}.', 'writeVideo')
        if self.codec:
            buf = io.BytesIO()
            im = self.pil.fromarray(img if img.ndim == 3 else np.repeat(img[:, :, None], 3, axis=2), 'RGB')
            im.save(buf, 'JPEG', quality=int(round(self.quality)))
            data, tag = buf.getvalue(), b'00dc'
        else:
            if self.gray:
                g = img if img.ndim == 2 else np.round(img.astype(float) @ np.array([0.2989, 0.5870, 0.1140])).astype(np.uint8)
                rows = g[::-1]
                pad = (-w) % 4
            else:
                rgb = img if img.ndim == 3 else np.repeat(img[:, :, None], 3, axis=2)
                rows = rgb[::-1, :, ::-1].reshape(h, w * 3)
                pad = (-(w * 3)) % 4
            if pad:
                rows = np.concatenate([rows, np.zeros((h, pad), np.uint8)], axis=1)
            data, tag = np.ascontiguousarray(rows).tobytes(), b'00db'
        self.index.append((tag, 4 + self.movi, len(data)))
        self.f.write(tag + struct.pack('<I', len(data)) + data + (b'\0' if len(data) % 2 else b''))
        self.movi += 8 + len(data) + len(data) % 2
        self.max_frame = max(self.max_frame, len(data))
        self.frames += 1

    def _header(self):
        return _avi_header(self.w, self.h, self.fps, self.frames, self.movi, self.codec, self.gray, self.max_frame)

    def close(self):
        if not self.is_open:
            return
        if self.frames:
            idx = b''.join(tag + struct.pack('<III', 0x10, off, size) for tag, off, size in self.index)
            self.f.write(b'idx1' + struct.pack('<I', len(idx)) + idx)
            self.f.seek(0)
            self.f.write(self._header())
        self.f.close()
        self.f = None
        self.is_open = False
        if not self.frames:
            try:
                os.remove(self.path)
            except OSError:
                pass
        from .iofun import files_changed
        files_changed(os.path.dirname(self.path))


@bi('VideoWriter', arr=False)
def videowriter(nargout, *args):
    """v = VideoWriter(filename, profile): a video file to write: 'Motion JPEG AVI' (unless asked), 'Uncompressed AVI' or 'Grayscale AVI'."""
    nargchk(args, 1, 2, 'VideoWriter')
    from .iofun import abspath
    name = py_str(args[0])
    profile = py_str(args[1]) if len(args) > 1 else 'Motion JPEG AVI'
    if profile.lower() not in _PROFILES:
        raise err('MATLAB:audiovideo:VideoWriter:unsupportedProfile',
                  f"The profile '{profile}' is not written here: 'Motion JPEG AVI', 'Uncompressed AVI' or 'Grayscale AVI' (MPEG-4 and Motion JPEG 2000 need encoders a browser page does not have).", 'VideoWriter')
    p = abspath(name)
    if not os.path.splitext(p)[1]:
        p += '.avi'
    elif not p.lower().endswith('.avi'):
        raise err('MATLAB:audiovideo:VideoWriter:fileExtension', f"The profile '{profile}' writes .avi files.", 'VideoWriter')
    return VideoWriter(p, ['Motion JPEG AVI', 'Uncompressed AVI', 'Grayscale AVI'][[x.lower() for x in _PROFILES].index(profile.lower())])


def _frames_of(v, fn):
    """Frames (uint8, m-by-n-by-3 or m-by-n) from an image, a stack of images, or getframe's structs."""
    if isinstance(v, Struct):
        if 'cdata' not in v.f:
            raise err(f'MATLAB:{fn}:frame', 'A frame is a struct with cdata and colormap, as getframe makes it.', fn)
        out_ = []
        for c, m in zip(v.f['cdata'].reshape(-1, order='F'), v.f['colormap'].reshape(-1, order='F') if 'colormap' in v.f else [EMPTY()] * v.size):
            a = arr(c, fn)
            if numel(m) and a.ndim == 2:
                cmap = darr(m).astype(float)
                idx = np.clip(a.astype(int) - (0 if a.dtype.kind in 'iu' else 1), 0, cmap.shape[0] - 1)
                a = np.round(cmap[idx] * 255).astype(np.uint8)
            out_.append(_u8(a, fn))
        return out_
    a = arr(v, fn)
    if a.ndim == 4:
        return [_u8(a[:, :, :, k], fn) for k in range(a.shape[3])]
    return [_u8(a, fn)]


def _u8(a, fn):
    if a.ndim == 3 and a.shape[2] == 1:
        a = a[:, :, 0]
    if not (a.ndim == 2 or (a.ndim == 3 and a.shape[2] == 3)):
        raise err(f'MATLAB:{fn}:frame', 'A frame is an m-by-n (gray) or m-by-n-by-3 image.', fn)
    if a.dtype == np.uint8:
        return np.ascontiguousarray(a)
    if a.dtype == bool:
        return a.astype(np.uint8) * 255
    if a.dtype.kind in 'iu':
        info = np.iinfo(a.dtype)
        return np.round((a.astype(float) - info.min) / (info.max - info.min) * 255).astype(np.uint8)
    return np.round(np.clip(np.nan_to_num(a.astype(float)), 0, 1) * 255).astype(np.uint8)


@bi('writeVideo', aw=True, arr=False)
async def writeVideo(nargout, *args):
    """writeVideo(v, frame): frames written to an open VideoWriter: getframe's structs, an image, or images stacked in the fourth dimension."""
    nargchk(args, 2, 2, 'writeVideo')
    v = args[0]
    if not isinstance(v, VideoWriter):
        raise err('MATLAB:writeVideo:object', 'writeVideo takes a VideoWriter.', 'writeVideo')
    if v.codec and v.pil is None:
        from .media import _pil
        v.pil = await _pil()
    for fr in _frames_of(args[1], 'writeVideo'):
        v.add(fr)
    return None


# ---- reading --------------------------------------------------------------------------------------------------------------------

def _riff_chunks(data, start, end):
    i = start
    while i + 8 <= end:
        cid = data[i:i + 4]
        size = struct.unpack('<I', data[i + 4:i + 8])[0]
        yield cid, i + 8, size
        i += 8 + size + (size & 1)


def _read_avi(data):
    """(width, height, fps, frames as (offset, size, kind), bits, palette) of an AVI file's first video stream."""
    if data[:4] != b'RIFF' or data[8:12] != b'AVI ':
        raise ValueError('not an AVI file')
    info = {}
    frames = []

    def walk(start, end):
        for cid, off, size in _riff_chunks(data, start, end):
            if cid == b'LIST':
                kind = data[off:off + 4]
                if kind == b'movi':
                    for c2, o2, s2 in _riff_chunks(data, off + 4, off + size):
                        if c2 == b'LIST' and data[o2:o2 + 4] == b'rec ':
                            for c3, o3, s3 in _riff_chunks(data, o2 + 4, o2 + s2):
                                if c3[2:] in (b'dc', b'db') and c3[:2] == b'00':
                                    frames.append((o3, s3, c3[2:]))
                        elif c2[2:] in (b'dc', b'db') and c2[:2] == b'00':
                            frames.append((o2, s2, c2[2:]))
                else:
                    walk(off + 4, off + size)
            elif cid == b'strh' and 'rate' not in info and data[off:off + 4] == b'vids':
                info['handler'] = data[off + 4:off + 8]
                scale, rate = struct.unpack('<II', data[off + 20:off + 28])
                info['rate'] = rate / scale if scale else 30.0
            elif cid == b'strf' and 'w' not in info and 'rate' in info:
                (_, w, h, _, bits, comp) = struct.unpack('<IiiHHI', data[off:off + 20])
                info.update(w=w, h=h, bits=bits, comp=comp)
                clr = struct.unpack('<I', data[off + 32:off + 36])[0] if size >= 36 else 0
                if bits == 8:
                    n = clr or 256
                    pal = np.frombuffer(data[off + 40:off + 40 + 4 * n], np.uint8).reshape(-1, 4)[:, [2, 1, 0]]
                    info['pal'] = pal
    walk(12, len(data))
    if 'w' not in info:
        raise ValueError('the AVI file has no video stream')
    return info, frames


class VideoReader(Obj):
    cls = 'VideoReader'
    is_handle = True
    __slots__ = ('path', 'info', 'frames', 'pos', 'gif', 'pil', 'tag', 'userdata')

    def __init__(self, path, info, frames, gif=None):
        self.path, self.info, self.frames, self.gif = path, info, frames, gif
        self.pos = 0
        self.pil = None
        self.tag = ''
        self.userdata = EMPTY()

    def props(self):
        n = len(self.frames)
        fps = self.info['rate']
        return {'Name': Char.of(os.path.basename(self.path)), 'Path': Char.of(os.path.dirname(self.path)), 'Duration': n / fps,
                'CurrentTime': self.pos / fps, 'NumFrames': float(n), 'Tag': Char.of(self.tag), 'UserData': self.userdata,
                'BitsPerPixel': 24.0, 'FrameRate': fps, 'Height': float(abs(self.info['h'])), 'Width': float(self.info['w']),
                'VideoFormat': Char.of('RGB24')}

    def getprop(self, name):
        d = self.props()
        if name.lower() == 'numberofframes':
            return d['NumFrames']
        for k in d:
            if k.lower() == name.lower():
                return d[k]
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized property '{name}' for class 'VideoReader'.")

    def setprop(self, name, value):
        k = name.lower()
        if k == 'currenttime':
            t = float(num(value))
            if not 0 <= t <= len(self.frames) / self.info['rate'] + 1e-9:
                raise MError('MATLAB:audiovideo:VideoReader:currentTime', 'CurrentTime is from 0 to the Duration.')
            self.pos = int(round(t * self.info['rate']))
            return
        if k == 'tag':
            self.tag = py_str(value)
            return
        if k == 'userdata':
            self.userdata = value
            return
        raise MError('MATLAB:class:SetProhibited', f"The property '{name}' of VideoReader cannot be set.")

    def propnames(self):
        return list(self.props())

    def display_lines(self):
        d = self.props()
        lines = ['  VideoReader with properties:', '']
        for k in ('Name', 'Path', 'Duration', 'CurrentTime', 'NumFrames', 'Width', 'Height', 'FrameRate', 'BitsPerPixel', 'VideoFormat'):
            v = d[k]
            s = f"'{v.str()}'" if isinstance(v, Char) else f'{float(v):.4g}'
            lines.append(f'    {k.rjust(12)}: {s}')
        return lines

    def frame(self, k):
        if self.gif is not None:
            self.gif.seek(k)
            return np.asarray(self.gif.convert('RGB'), np.uint8).copy()
        off, size, kind = self.frames[k]
        with open(self.path, 'rb') as f:
            f.seek(off)
            data = f.read(size)
        w, h = self.info['w'], self.info['h']
        if self.info['comp'] == 0:
            bits = self.info['bits']
            hh = abs(h)
            if bits == 24:
                row = ((w * 24 + 31) // 32) * 4
                a = np.frombuffer(data, np.uint8)[:row * hh].reshape(hh, row)[:, :w * 3].reshape(hh, w, 3)[:, :, ::-1]
            elif bits == 8:
                row = ((w * 8 + 31) // 32) * 4
                idx = np.frombuffer(data, np.uint8)[:row * hh].reshape(hh, row)[:, :w]
                a = self.info['pal'][idx]
            else:
                raise ValueError(f'{bits}-bit uncompressed frames are not read here')
            return np.ascontiguousarray(a[::-1] if h > 0 else a)
        im = self.pil.open(io.BytesIO(data))
        return np.asarray(im.convert('RGB'), np.uint8).copy()


@bi('VideoReader', aw=True, arr=False)
async def videoreader(nargout, *args):
    """v = VideoReader(filename): a video file to read frame by frame: AVI (Motion JPEG, uncompressed or 8-bit) or an animated GIF."""
    nargchk(args, 1, 5, 'VideoReader')
    from .iofun import abspath
    from .media import _pil
    name = py_str(args[0])
    p = abspath(name)
    if not os.path.isfile(p):
        raise err('MATLAB:audiovideo:VideoReader:FileNotFound', f"The file '{name}' does not exist.", 'VideoReader')
    with open(p, 'rb') as f:
        head = f.read(12)
    if head[:6] in (b'GIF87a', b'GIF89a'):
        Image = await _pil()
        im = Image.open(p)
        n = getattr(im, 'n_frames', 1)
        dur = im.info.get('duration', 100) or 100
        rd = VideoReader(p, {'rate': 1000.0 / dur, 'w': im.size[0], 'h': im.size[1]}, list(range(n)), gif=im)
        rd.pil = Image
    elif head[:4] == b'RIFF' and head[8:12] == b'AVI ':
        with open(p, 'rb') as f:
            data = f.read()
        info, frames = _read_avi(data)
        rd = VideoReader(p, info, frames)
        if info['comp'] != 0:
            if info['handler'].upper() not in (b'MJPG', b'JPEG') and struct.pack('<I', info['comp']).upper() not in (b'MJPG', b'JPEG'):
                raise err('MATLAB:audiovideo:VideoReader:codec', 'This AVI file is not Motion JPEG or uncompressed: other codecs are not read here.', 'VideoReader')
            rd.pil = await _pil()
    else:
        raise err('MATLAB:audiovideo:VideoReader:format', 'VideoReader reads AVI files (Motion JPEG or uncompressed) and animated GIFs here; other formats (MP4, MOV) need decoders a browser page does not have.', 'VideoReader')
    for i in range(1, len(args) - 1, 2):
        rd.setprop(py_str(args[i]), args[i + 1])
    return rd


def _reader(v, fn):
    if not isinstance(v, VideoReader):
        raise err(f'MATLAB:{fn}:object', f'{fn} takes a VideoReader.', fn)
    return v


@bi('hasFrame', arr=False)
def hasFrame(nargout, *args):
    """tf = hasFrame(v): whether a VideoReader has a frame left to read."""
    nargchk(args, 1, 1, 'hasFrame')
    v = _reader(args[0], 'hasFrame')
    return v.pos < len(v.frames)


@bi('readFrame', arr=False)
def readFrame(nargout, *args):
    """frame = readFrame(v): the next frame of a VideoReader (m-by-n-by-3 uint8), CurrentTime moving on."""
    nargchk(args, 1, 3, 'readFrame')
    v = _reader(args[0], 'readFrame')
    if v.pos >= len(v.frames):
        raise err('MATLAB:audiovideo:VideoReader:EndOfFile', 'There are no more frames to read: hasFrame(v) is false.', 'readFrame')
    a = v.frame(v.pos)
    v.pos += 1
    return a


@bi('read', arr=False)
def read(nargout, *args):
    """frames = read(v), read(v, k), read(v, [first last]), read(v, Inf): frames of a VideoReader, stacked in the fourth dimension."""
    nargchk(args, 1, 3, 'read')
    v = _reader(args[0], 'read')
    n = len(v.frames)
    if len(args) > 1 and numel(args[1]):
        k = darr(args[1]).reshape(-1).astype(float)
        if k.size == 1:
            ks = [n - 1] if np.isinf(k[0]) else [int(k[0]) - 1]
        else:
            last = n if np.isinf(k[1]) else int(k[1])
            ks = list(range(int(k[0]) - 1, last))
    else:
        ks = list(range(n))
    if any(i < 0 or i >= n for i in ks):
        raise err('MATLAB:audiovideo:VideoReader:frameRange', f'The video has {n} frames.', 'read')
    frames = [v.frame(i) for i in ks]
    if not frames:
        return np.zeros((0, 0, 3, 0), np.uint8)
    return frames[0] if len(frames) == 1 else np.stack(frames, axis=3)


# ---- open and close a VideoWriter -----------------------------------------------------------------------------------------------

def _wrap(name, test, handler):
    info = REG[name]
    orig = info.fn
    ws, aw = info.ws, info.aw
    if aw:
        async def f(*a):
            args = a[2:] if ws else a[1:]
            if args and test(args[0]):
                r = handler(a[1] if ws else a[0], *args)
                return (await r) if hasattr(r, '__await__') else r
            return await orig(*a)
    else:
        def f(*a):
            args = a[2:] if ws else a[1:]
            if args and test(args[0]):
                return handler(a[1] if ws else a[0], *args)
            return orig(*a)
    info.fn = f


def _open_writer(nargout, v, *rest):
    v.open()
    return None


def _close_media(nargout, v, *rest):
    if isinstance(v, VideoWriter):
        v.close()
    return None


_wrap('open', lambda v: isinstance(v, VideoWriter), _open_writer)
_wrap('close', lambda v: isinstance(v, (VideoWriter, VideoReader)), _close_media)
