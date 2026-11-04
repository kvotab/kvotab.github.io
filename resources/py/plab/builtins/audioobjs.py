"""Sound players and recorders: audioplayer (play, playblocking, pause,
resume, stop, isplaying) and audiorecorder (record, recordblocking,
getaudiodata, pause, resume, stop, isrecording, play).

A player sends its samples to the page, which plays them through its audio;
where it is in them is worked out from the time since it started. A
recorder asks the page for the microphone (the browser asks the person
first) and fetches what was recorded when it is stopped or asked for."""
import base64
import time

import numpy as np

from . import bi as _register, REG
from ._util import err, nargchk, out, num, opt_str, is_str, darr, arr
from ..values import MError, Obj, Char, Cell, Struct, EMPTY, numel, py_str
from .. import runtime as R


def bi(*names, **kw):
    kw.setdefault('arr', False)

    def deco(f):
        aw = kw.get('aw', False)
        if aw:
            async def g(*a):
                try:
                    return await f(*a)
                except MError:
                    raise
                except (ValueError, TypeError, IndexError) as e:
                    raise err(f'MATLAB:{names[0]}:invalidInput', f'{names[0]}: {e}', names[0])
        else:
            def g(*a):
                try:
                    return f(*a)
                except MError:
                    raise
                except (ValueError, TypeError, IndexError) as e:
                    raise err(f'MATLAB:{names[0]}:invalidInput', f'{names[0]}: {e}', names[0])
        g.__name__, g.__doc__ = f.__name__, f.__doc__
        return _register(*names, **kw)(g)
    return deco


_IDS = [0]


def _event(d):
    hook = R.EVENT_HOOK[0]
    if hook is not None:
        hook(d)


def _samples(a):
    """Audio as an n-by-channels float array from -1 to 1 (integer classes scaled)."""
    a = arr(a, 'audioplayer')
    if a.ndim == 1:
        a = a.reshape(-1, 1)
    if a.shape[0] < a.shape[1] and a.shape[0] <= 2:
        a = a.T
    if a.dtype.kind in 'iu':
        info = np.iinfo(a.dtype)
        if a.dtype == np.uint8:
            return (a.astype(float) - 128) / 128
        return a.astype(float) / max(abs(info.min), info.max)
    return np.clip(np.nan_to_num(a.astype(float)), -1, 1)


class AudioPlayer(Obj):
    cls = 'audioplayer'
    is_handle = True

    def __init__(self, y, fs, bits=16):
        _IDS[0] += 1
        self.id = _IDS[0]
        self.y, self.fs, self.bits = y, float(fs), int(bits)
        self.start_sample = 0          # where the current (or last) play started, from 0
        self.end_sample = y.shape[0]
        self.started = None            # time.time() when playing, else None
        self.pos = 0                   # the sample a pause stopped at
        self.tag = ''
        self.userdata = EMPTY()

    def current(self):
        if self.started is None:
            return self.pos
        k = self.start_sample + int((time.time() - self.started) * self.fs)
        if k >= self.end_sample:
            self.started = None
            self.pos = 0
            return 0
        return k

    def send(self, a, b):
        part = self.y[a:b]
        if not part.size:
            return
        data = np.ascontiguousarray(part.T, '<f4').tobytes()
        _event({'type': 'sound', 'id': self.id, 'rate': self.fs, 'channels': int(part.shape[1]), 'data': base64.b64encode(data).decode('ascii')})
        self.start_sample, self.end_sample = a, b
        self.started = time.time()

    def stop_sound(self):
        _event({'type': 'soundctl', 'id': self.id, 'op': 'stop'})

    def props(self):
        cur = self.current()
        return {'SampleRate': self.fs, 'BitsPerSample': float(self.bits), 'NumberOfChannels': float(self.y.shape[1]),
                'TotalSamples': float(self.y.shape[0]), 'CurrentSample': float(cur + 1), 'Running': Char.of('on' if self.started is not None else 'off'),
                'Tag': Char.of(self.tag), 'UserData': self.userdata, 'Type': Char.of('audioplayer')}

    def getprop(self, name):
        for k, v in self.props().items():
            if k.lower() == name.lower():
                return v
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized property '{name}' for class 'audioplayer'.")

    def setprop(self, name, value):
        n = name.lower()
        if n == 'samplerate':
            self.fs = float(num(value))
            return
        if n == 'tag':
            self.tag = py_str(value)
            return
        if n == 'userdata':
            self.userdata = value
            return
        raise MError('MATLAB:class:SetProhibited', f"The property '{name}' of audioplayer cannot be set.")

    def propnames(self):
        return list(self.props())

    def display_lines(self):
        from ..display import summary
        d = self.props()
        w = max(len(k) for k in d)
        return ['  audioplayer with properties:', ''] + [f'    {k.rjust(w)}: {summary(v)}' for k, v in d.items()]


@bi('audioplayer')
def audioplayer(nargout, *args):
    """player = audioplayer(y, Fs), audioplayer(y, Fs, nBits), audioplayer(recorder): a player of the samples (a column, or a column for each channel)."""
    nargchk(args, 1, 4, 'audioplayer')
    if isinstance(args[0], AudioRecorder):
        r = args[0]
        y = r.data()
        return AudioPlayer(y, r.fs, r.bits)
    if len(args) < 2:
        raise err('MATLAB:minrhs', 'audioplayer(y, Fs): give the sample rate.', 'audioplayer')
    y = _samples(args[0])
    fs = float(num(args[1]))
    if not fs > 0:
        raise err('MATLAB:audioplayer:fs', 'The sample rate is positive.', 'audioplayer')
    bits = int(num(args[2])) if len(args) > 2 else 16
    return AudioPlayer(y, fs, bits)


def _range(p, args):
    if args and numel(args[0]):
        v = darr(args[0]).reshape(-1)
        a = int(v[0]) - 1
        b = int(v[1]) if v.size > 1 else p.y.shape[0]
        return max(a, 0), min(b, p.y.shape[0])
    return 0, p.y.shape[0]


def _player(v, fn):
    if not isinstance(v, (AudioPlayer, AudioRecorder)):
        raise err(f'MATLAB:{fn}:object', f'{fn} takes an audioplayer or audiorecorder.', fn)
    return v


@bi('play')
def play(nargout, *args):
    """play(player), play(player, start), play(player, [start stop]): the sound played (the program goes on at once)."""
    nargchk(args, 1, 2, 'play')
    p = _player(args[0], 'play')
    if isinstance(p, AudioRecorder):
        p = AudioPlayer(p.data(), p.fs, p.bits)
    a, b = _range(p, args[1:])
    if p.started is not None:
        p.stop_sound()
    p.send(a, b)
    return None


@bi('playblocking', aw=True)
async def playblocking(nargout, *args):
    """playblocking(player), playblocking(player, [start stop]): the sound played, the program waiting until it ends."""
    nargchk(args, 1, 2, 'playblocking')
    p = _player(args[0], 'playblocking')
    if isinstance(p, AudioRecorder):
        p = AudioPlayer(p.data(), p.fs, p.bits)
    a, b = _range(p, args[1:])
    p.send(a, b)
    await R.sleep((b - a) / p.fs)
    p.started = None
    p.pos = 0
    return None


@bi('isplaying')
def isplaying(nargout, *args):
    """tf = isplaying(player): whether it is playing now."""
    nargchk(args, 1, 1, 'isplaying')
    p = _player(args[0], 'isplaying')
    p.current()
    return p.started is not None


@bi('resume', aw=True)
async def resume(nargout, *args):
    """resume(player), resume(recorder): playing (or recording) again from where pause stopped it."""
    nargchk(args, 1, 1, 'resume')
    p = _player(args[0], 'resume')
    if isinstance(p, AudioRecorder):
        if not p.running:
            await p.start(None)
        return None
    if p.started is None and p.pos > 0:
        p.send(p.pos, p.end_sample)
    return None


def _pause_player(nargout, p, *rest):
    if isinstance(p, AudioRecorder):
        return p.pause()
    if p.started is not None:
        p.pos = p.current()
        p.stop_sound()
        p.started = None
    return None


def _stop_player(nargout, p, *rest):
    if isinstance(p, AudioRecorder):
        return p.stop()
    p.stop_sound()
    p.started = None
    p.pos = 0
    return None


# ---- recording --------------------------------------------------------------------------------------------------------------------

class AudioRecorder(Obj):
    cls = 'audiorecorder'
    is_handle = True

    def __init__(self, fs, bits, channels):
        _IDS[0] += 1
        self.id = _IDS[0]
        self.fs, self.bits, self.channels = float(fs), int(bits), int(channels)
        self.recorded = np.zeros((0, self.channels))
        self.running = False
        self.started = None
        self.limit = None
        self.tag = ''
        self.userdata = EMPTY()

    def props(self):
        return {'SampleRate': self.fs, 'BitsPerSample': float(self.bits), 'NumberOfChannels': float(self.channels),
                'TotalSamples': float(self.recorded.shape[0] + (int((time.time() - self.started) * self.fs) if self.running and self.started else 0)),
                'CurrentSample': 1.0, 'Running': Char.of('on' if self.running else 'off'), 'Tag': Char.of(self.tag), 'UserData': self.userdata,
                'Type': Char.of('audiorecorder')}

    def getprop(self, name):
        for k, v in self.props().items():
            if k.lower() == name.lower():
                return v
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized property '{name}' for class 'audiorecorder'.")

    def setprop(self, name, value):
        n = name.lower()
        if n == 'tag':
            self.tag = py_str(value)
            return
        if n == 'userdata':
            self.userdata = value
            return
        raise MError('MATLAB:class:SetProhibited', f"The property '{name}' of audiorecorder cannot be set.")

    def propnames(self):
        return list(self.props())

    def display_lines(self):
        from ..display import summary
        d = self.props()
        w = max(len(k) for k in d)
        return ['  audiorecorder with properties:', ''] + [f'    {k.rjust(w)}: {summary(v)}' for k, v in d.items()]

    async def start(self, seconds=None):
        res = await R.ask_page({'type': 'recordstart', 'rec': self.id, 'rate': self.fs, 'channels': self.channels, 'seconds': seconds})
        if not isinstance(res, dict):
            raise err('MATLAB:audiorecorder:noDevice', 'Recording needs the page and a microphone.', 'record')
        if res.get('error'):
            raise err('MATLAB:audiorecorder:noDevice', f"The browser gave no microphone: {res['error']}", 'record')
        self.running = True
        self.started = time.time()
        self.limit = seconds

    async def fetch(self, stop):
        res = await R.ask_page({'type': 'recordstop' if stop else 'recorddata', 'rec': self.id})
        if isinstance(res, dict) and res.get('data') is not None:
            raw = np.frombuffer(base64.b64decode(res['data']), '<f4').astype(float)
            ch = int(res.get('channels', self.channels)) or 1
            got = raw.reshape(ch, -1).T if raw.size else np.zeros((0, ch))
            if got.shape[1] != self.channels:
                got = np.repeat(got[:, :1], self.channels, axis=1)
            return got
        return np.zeros((0, self.channels))

    def data(self):
        return self.recorded

    async def stop_async(self):
        if self.running:
            got = await self.fetch(True)
            self.recorded = np.vstack([self.recorded, got])
            self.running = False
        return None

    def stop(self):
        return R.run_sync(self.stop_async()) if R.SYNC[0] else _later(self.stop_async())

    def pause(self):
        return self.stop()


class _Later:
    """A coroutine a synchronous builtin hands back to be awaited (stop, pause, resume of a recorder)."""
    def __init__(self, coro):
        self.coro = coro


def _later(coro):
    return _Later(coro)


@bi('audiorecorder')
def audiorecorder(nargout, *args):
    """recorder = audiorecorder, audiorecorder(Fs, nBits, nChannels): a recorder of the microphone (8000 Hz, 8 bits, 1 channel unless given)."""
    nargchk(args, 0, 4, 'audiorecorder')
    fs = float(num(args[0])) if args else 8000.0
    bits = int(num(args[1])) if len(args) > 1 else 8
    ch = int(num(args[2])) if len(args) > 2 else 1
    if ch not in (1, 2):
        raise err('MATLAB:audiorecorder:channels', 'The number of channels is 1 or 2.', 'audiorecorder')
    return AudioRecorder(fs, bits, ch)


def _recorder(v, fn):
    if not isinstance(v, AudioRecorder):
        raise err(f'MATLAB:{fn}:object', f'{fn} takes an audiorecorder.', fn)
    return v


@bi('record', aw=True)
async def record(nargout, *args):
    """record(recorder), record(recorder, length): recording started (for length seconds, or until stop); the program goes on at once."""
    nargchk(args, 1, 2, 'record')
    r = _recorder(args[0], 'record')
    secs = float(num(args[1])) if len(args) > 1 else None
    r.recorded = np.zeros((0, r.channels))
    await r.start(secs)
    return None


@bi('recordblocking', aw=True)
async def recordblocking(nargout, *args):
    """recordblocking(recorder, length): length seconds recorded, the program waiting."""
    nargchk(args, 2, 2, 'recordblocking')
    r = _recorder(args[0], 'recordblocking')
    secs = float(num(args[1]))
    r.recorded = np.zeros((0, r.channels))
    await r.start(secs)
    await R.sleep(secs + 0.15)
    await r.stop_async()
    return None


@bi('getaudiodata', aw=True)
async def getaudiodata(nargout, *args):
    """y = getaudiodata(recorder), getaudiodata(recorder, dataType): what was recorded, a column for each channel ('double' from -1 to 1, or 'single', 'int16', 'int8', 'uint8')."""
    nargchk(args, 1, 2, 'getaudiodata')
    r = _recorder(args[0], 'getaudiodata')
    if r.running:
        if r.limit is not None and time.time() - r.started >= r.limit:
            await r.stop_async()
            y = r.recorded
        else:
            y = np.vstack([r.recorded, await r.fetch(False)])
    else:
        y = r.recorded
    t = py_str(args[1]).lower() if len(args) > 1 else 'double'
    if t == 'double':
        return y.copy()
    if t == 'single':
        return y.astype(np.float32)
    if t == 'int16':
        return np.clip(np.round(y * 32768), -32768, 32767).astype(np.int16)
    if t == 'int8':
        return np.clip(np.round(y * 128), -128, 127).astype(np.int8)
    if t == 'uint8':
        return np.clip(np.round(y * 128 + 128), 0, 255).astype(np.uint8)
    raise err('MATLAB:getaudiodata:type', "The data type is 'double', 'single', 'int16', 'int8' or 'uint8'.", 'getaudiodata')


@bi('isrecording')
def isrecording(nargout, *args):
    """tf = isrecording(recorder): whether it is recording now."""
    nargchk(args, 1, 1, 'isrecording')
    r = _recorder(args[0], 'isrecording')
    if r.running and r.limit is not None and time.time() - r.started >= r.limit:
        return False
    return r.running


def _wrap(name, test, handler):
    info = REG.get(name)
    if info is None:
        return
    orig = info.fn
    ws, aw = info.ws, info.aw
    if aw:
        async def f(*a):
            args = a[2:] if ws else a[1:]
            if args and test(args[0]):
                r = handler(a[1] if ws else a[0], *args)
                if isinstance(r, _Later):
                    r = await r.coro
                return r
            return await orig(*a)
    else:
        def f(*a):
            args = a[2:] if ws else a[1:]
            if args and test(args[0]):
                r = handler(a[1] if ws else a[0], *args)
                if isinstance(r, _Later):
                    r = R.run_sync(r.coro)
                return r
            return orig(*a)
    info.fn = f


_is_audio = lambda v: isinstance(v, (AudioPlayer, AudioRecorder))  # noqa: E731
_wrap('pause', _is_audio, _pause_player)
_wrap('stop', _is_audio, _stop_player)
