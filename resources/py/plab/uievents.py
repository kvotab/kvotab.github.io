"""What people do with figures and their controls, and the callbacks that
answer. The page reports clicks, keys, menu choices and timer ticks
(handle), which set what a program reads (Value, String, CurrentPoint,
CurrentCharacter, SelectionType ...) and queue the callbacks. These run
when the engine is idle (run_queued, a run of its own) or when a running
program lets them: at drawnow, pause, uiwait and waitfor (process).

A callback is text (run in the base workspace), a function handle (called
with the object and the event data) or a cell {f, a1, a2, ...} (f called
with the object, the event data, a1, a2, ...). gcbo and gcbf name the
object whose callback runs, and its figure.
"""
import asyncio
import collections
import itertools
import time

import numpy as np

from . import runtime as R
from .values import MError, Interrupt, Char, Cell, Str, Struct, FH, Obj, EMPTY, py_str, F64
from .graphics_base import STORE, ROOT, GObj, Axes, has_callback, DELETE_HOOK, gerr

QUEUE = collections.deque()      # (object, property, event data): callbacks waiting to run
STACK = []                       # the callbacks running now: (object, figure)
TIMERS = {}                      # id -> Timer
_depth = [0]


def gcbo():
    return STACK[-1][0] if STACK else None


def gcbf():
    return STACK[-1][1] if STACK else None


def evdata(src, name, **fields):
    """Event data: the event's fields, then Source and EventName."""
    d = dict(fields)
    d['Source'] = src
    d['EventName'] = Char.of(name)
    return Struct.scalar(d)


def callback_of(obj, prop):
    v = obj.props.get(prop)
    return v if has_callback(v) else None


def queue(obj, prop, evt=None):
    """Queue obj's prop callback, if it holds one; True when it does."""
    if callback_of(obj, prop) is None:
        return False
    QUEUE.append((obj, prop, evt))
    return True


def _kind(obj):
    if isinstance(obj, Timer):
        return 'timer'
    return getattr(obj, 'CLASSNAME', 'object').split('.')[-1]


async def call(cb, src, evt):
    """Run one callback value with the object and event data it is for."""
    if isinstance(cb, Char) or isinstance(cb, Str):
        cb = py_str(cb)
    if isinstance(cb, str):
        fn, _ = R.compile_command(cb, R.BASE)
        await fn(R.BASE)
        return
    if isinstance(cb, FH):
        await cb.acall(0, src, evt)
        return
    if type(cb) is Cell:
        items = cb.items()
        if not items:
            return
        f, args = items[0], items[1:]
        if isinstance(f, FH):
            await f.acall(0, src, evt, *args)
        elif type(f) in (Char, Str):
            await R.call(None, py_str(f), 0, (src, evt, *args))
        else:
            raise MError('MATLAB:callback:invalid', 'A callback cell array starts with a function handle or a function name.')
        return
    if callable(cb):
        # the engine's own (the buttons of msgbox, waitbar's Cancel)
        r = cb(src, evt)
        if asyncio.iscoroutine(r):
            await r
        return
    raise MError('MATLAB:callback:invalid', 'A callback is text, a function handle or a cell array.')


def report(e, obj, prop):
    """An error in a callback is shown; what was running goes on."""
    m = R.as_merror(e)
    m.stack = m.stack or R.stack_of(e.__traceback__)
    R.LASTERR[0] = m
    R.write(R.format_error(m), 'err')
    if isinstance(obj, Timer):
        R.write(f"Error while evaluating {prop} for timer '{obj.props['Name']}'.\n\n", 'err')
    else:
        R.write(f'Error while evaluating {_kind(obj)} {prop}.\n\n', 'err')


async def run_one(obj, prop, evt=None):
    """Run obj's prop callback now."""
    cb = callback_of(obj, prop)
    if isinstance(obj, Timer) and prop == 'TimerFcn':
        obj.pending = max(0, obj.pending - 1)
    if cb is None:
        return
    fig = obj.figure() if isinstance(obj, GObj) else None
    if evt is None:
        evt = evdata(obj, 'Action') if isinstance(obj, GObj) else EMPTY()
    if fig is not None and fig.valid and fig.props['HandleVisibility'] == 'on':
        STORE.current = fig
    STACK.append((obj, fig))
    try:
        await call(cb, obj, evt)
    except Interrupt:
        raise
    except Exception as e:
        report(e, obj, prop)
    finally:
        STACK.pop()


async def process(wait=True):
    """Run the callbacks that wait: at drawnow, pause, uiwait and waitfor,
    and (wait False) as a run of their own when the engine was idle."""
    if R.SYNC[0] or _depth[0] > 40:
        return False
    if wait:
        await asyncio.sleep(0)       # the page's messages (clicks, keys) come in here
    if not QUEUE:
        return False
    _depth[0] += 1
    try:
        while QUEUE:
            obj, prop, evt = QUEUE.popleft()
            if not obj.valid and not (prop == 'DeleteFcn' or (isinstance(obj, Timer) and prop == 'StopFcn')):
                continue
            await run_one(obj, prop, evt)
            R.flush()
            R.flush_figures()
    finally:
        _depth[0] -= 1
    return True


async def run_queued():
    """The callbacks the page asked for, run while nothing else runs."""
    await process(wait=False)
    return True


def run_now(obj, prop, evt=None):
    """A callback run at once, inside code that cannot wait (DeleteFcn and
    CreateFcn): one that waits for something fails with a message."""
    if callback_of(obj, prop) is None:
        return
    try:
        R.run_sync(run_one(obj, prop, evt))
    except MError as e:
        report(e, obj, prop)


DELETE_HOOK[0] = lambda o: run_now(o, 'DeleteFcn', evdata(o, 'ObjectBeingDestroyed'))


def created(obj):
    run_now(obj, 'CreateFcn', evdata(obj, 'ObjectCreated'))


# ---- what the page reports ---------------------------------------------------------------------

def _unit_point(fig, x, y):
    """A point in pixels from the figure's lower left, in the figure's Units."""
    from .uiobjects import UNIT_PX, inner_px
    u = fig.props['Units']
    if u == 'normalized':
        w, h = inner_px(fig)
        return np.array([[x / (w or 1.0), y / (h or 1.0)]])
    sx, sy = UNIT_PX.get(u, (1.0, 1.0))
    return np.array([[x / sx, y / sy]])


def _axes_point(ax, pt):
    if not isinstance(ax, Axes) or pt is None:
        return
    z = np.asarray(ax.get_value('ZLim'), float).reshape(-1)
    x, y = float(pt[0]), float(pt[1])
    ax.props['CurrentPoint'] = np.array([[x, y, z[1]], [x, y, z[0]]])


def _mods(ev):
    return Cell.of_list([Char.of(m) for m in ev.get('modifiers') or []])


def _control(obj, fig, ev):
    a = ev.get('action')
    p = obj.props
    fig.props['CurrentObject'] = obj
    if a == 'down':
        fig.props['SelectionType'] = 'alt' if ev.get('button') == 3 else 'normal'
        queue(obj, 'ButtonDownFcn', evdata(obj, 'Hit', Button=float(ev.get('button', 1))))
        return
    if obj.TYPE == 'uitable':
        _table(obj, ev)
        return
    if obj.TYPE == 'uicomp':
        from .uiapp import component_event
        component_event(obj, fig, ev)
        return
    if obj.TYPE == 'uitabgroup':
        new = STORE.objects.get(ev.get('tab'))
        old = obj.selection()
        if new is not None and new is not old and new in obj.tabs():
            obj.props['SelectedTab'] = new
            obj.touch()
            queue(obj, 'SelectionChangedFcn', evdata(obj, 'SelectionChanged', OldValue=old if old is not None else EMPTY(), NewValue=new))
        return
    if a == 'click':
        queue(obj, 'Callback')
    elif a == 'toggle':
        on = ev.get('on')
        if on is None:
            on = obj.selected() != [p['Max']]
        p['Value'] = p['Max'] if on else p['Min']
        obj.touch()
        queue(obj, 'Callback')
    elif a == 'radio':
        grp = obj.parent if obj.parent is not None and obj.parent.TYPE == 'uibuttongroup' else None
        if grp is not None:
            old = grp.selection()
            grp.select(obj)
            if old is not obj:
                queue(grp, 'SelectionChangedFcn', evdata(grp, 'SelectionChanged', OldValue=old if old is not None else EMPTY(), NewValue=obj))
            return
        on = obj.selected() != [p['Max']]
        p['Value'] = p['Max'] if on else p['Min']
        obj.touch()
        queue(obj, 'Callback')
    elif a == 'edit':
        s = ev.get('string', '')
        if isinstance(s, list) and len(s) > 1:
            p['String'] = Cell.of_list([Char.of(x) for x in s], (len(s), 1))
        else:
            p['String'] = Char.of(s[0] if isinstance(s, list) and s else (s if isinstance(s, str) else ''))
        obj.touch()
        queue(obj, 'Callback')
    elif a == 'slider':
        v = float(ev.get('value', 0.0))
        p['Value'] = min(max(v, p['Min']), p['Max'])
        obj.touch()
        queue(obj, 'Callback')
    elif a in ('list', 'popup'):
        vals = [float(x) for x in ev.get('value') or []]
        p['Value'] = vals[0] if len(vals) == 1 else (np.array([vals]) if vals else EMPTY())
        fig.props['SelectionType'] = 'open' if ev.get('open') else 'normal'
        obj.touch()
        queue(obj, 'Callback')


def _table(obj, ev):
    p = obj.props
    if ev.get('action') == 'select':
        ij = np.array(ev.get('cells') or [], float).reshape(-1, 2)
        queue(obj, 'CellSelectionCallback', evdata(obj, 'CellSelection', Indices=ij))
        return
    if ev.get('action') != 'edit':
        return
    i, j = int(ev['row']) - 1, int(ev['col']) - 1
    text = str(ev.get('text', ''))
    data = p['Data']
    err = EMPTY()
    if type(data) is Cell:
        prev = data.a[i, j]
        if type(prev) in (Char, Str):
            new = Char.of(text)
        elif isinstance(prev, (bool, np.bool_)) or (isinstance(prev, np.ndarray) and prev.dtype == bool):
            new = bool(ev.get('checked', text.lower() in ('1', 'true', 'on')))
        else:
            try:
                new = float(text)
            except ValueError:
                new, err = prev, Char.of(f"'{text}' is not a number.")
        a = data.a.copy()
        a[i, j] = new
        p['Data'] = Cell(a)
    else:
        a = np.array(data, copy=True)
        if a.ndim < 2:
            a = a.reshape(1, -1)
        prev = a[i, j].item()
        if a.dtype == bool:
            new = bool(ev.get('checked', text.lower() in ('1', 'true', 'on')))
        else:
            try:
                new = float(text)
            except ValueError:
                new, err = prev, Char.of(f"'{text}' is not a number.")
        a[i, j] = new
        p['Data'] = a
        prev = float(prev) if not isinstance(prev, bool) else prev
    obj.touch()
    queue(obj, 'CellEditCallback', evdata(obj, 'CellEdit', Indices=np.array([[i + 1.0, j + 1.0]]), PreviousData=prev,
                                          EditData=Char.of(text), NewData=new, Error=err))


def _menu(obj, fig, ev):
    queue(obj, 'Callback')


def _tool(obj, fig, ev):
    p = obj.props
    if obj.TYPE == 'uitoggletool':
        on = ev.get('on')
        p['State'] = (not p['State']) if on is None else bool(on)
        obj.touch()
        queue(obj, 'OnCallback' if p['State'] else 'OffCallback')
    queue(obj, 'ClickedCallback')


def _key(obj, fig, ev):
    release = bool(ev.get('release'))
    ch = ev.get('character') or ''
    key = ev.get('key') or ''
    fig.props['CurrentCharacter'] = ch
    fig.props['CurrentKey'] = key
    fig.props['CurrentModifier'] = list(ev.get('modifiers') or [])
    name = 'KeyRelease' if release else 'KeyPress'

    def data(src):
        return evdata(src, name, Character=Char.of(ch), Modifier=_mods(ev), Key=Char.of(key))
    queue(fig, 'WindowKeyReleaseFcn' if release else 'WindowKeyPressFcn', data(fig))
    prop = 'KeyReleaseFcn' if release else 'KeyPressFcn'
    if obj is not fig and callback_of(obj, prop) is not None:
        queue(obj, prop, data(obj))
    elif obj is fig or ev.get('toFigure'):
        queue(fig, prop, data(fig))


def _mouse(obj, fig, ev):
    """down, up, motion and scroll on the figure's canvas."""
    t = ev['type']
    fpt = ev.get('fpt') or [0.0, 0.0]
    fig.props['CurrentPoint'] = _unit_point(fig, float(fpt[0]), float(fpt[1]))
    ax = STORE.objects.get(ev.get('axes'))
    if ax is not None and ax.valid:
        _axes_point(ax, ev.get('point'))
    pt = ev.get('point')
    ip = np.array([[float(pt[0]), float(pt[1]), 0.0]]) if pt is not None else np.full((1, 3), np.nan)
    if t == 'motion':
        if not any(q[0] is fig and q[1] == 'WindowButtonMotionFcn' for q in QUEUE):
            queue(fig, 'WindowButtonMotionFcn', evdata(fig, 'WindowMouseMotion', HitObject=STORE.objects.get(ev.get('hit')) or fig,
                                                       Point=np.array([fpt], float), IntersectionPoint=ip))
        return
    if t == 'scroll':
        queue(fig, 'WindowScrollWheelFcn', evdata(fig, 'WindowScrollWheel', VerticalScrollCount=float(ev.get('count', 1)),
                                                  VerticalScrollAmount=3.0))
        return
    if t == 'up':
        queue(fig, 'WindowButtonUpFcn', evdata(fig, 'WindowMouseRelease', HitObject=STORE.objects.get(ev.get('hit')) or fig,
                                               Point=np.array([fpt], float), IntersectionPoint=ip))
        return
    button = int(ev.get('button', 1))
    mods = ev.get('modifiers') or []
    if int(ev.get('clicks', 1)) >= 2:
        sel = 'open'
    elif button == 3 or 'control' in mods:
        sel = 'alt'
    elif button == 2 or 'shift' in mods:
        sel = 'extend'
    else:
        sel = 'normal'
    fig.props['SelectionType'] = sel
    hit = STORE.objects.get(ev.get('hit'))
    if hit is None or not hit.valid or hit.figure() is not fig:
        hit = fig
    # a click goes to the nearest object that takes clicks
    while hit is not fig and not hit.props.get('HitTest', True):
        hit = hit.parent if hit.parent is not None else fig
    fig.props['CurrentObject'] = hit
    queue(fig, 'WindowButtonDownFcn', evdata(fig, 'WindowMousePress', HitObject=hit, Point=np.array([fpt], float), IntersectionPoint=ip))
    queue(hit, 'ButtonDownFcn', evdata(hit, 'Hit', Button=float(button), IntersectionPoint=ip))


def _close(obj, fig, ev):
    queue(fig, 'CloseRequestFcn', evdata(fig, 'Close'))


def _resize(obj, fig, ev):
    pos = fig.props['Position'].reshape(-1).copy()
    from .uiobjects import UNIT_PX
    sx, sy = UNIT_PX.get(fig.props['Units'], (1.0, 1.0))
    if fig.props['Units'] == 'normalized':
        scr = np.asarray(ROOT.props['ScreenSize'], float).reshape(-1)
        sx, sy = scr[2], scr[3]
    pos[2], pos[3] = float(ev['width']) / sx, float(ev['height']) / sy
    fig.props['Position'] = pos.reshape(1, 4)
    fig.__dict__['sized'] = _size_px(fig)
    queue(fig, 'SizeChangedFcn', evdata(fig, 'SizeChanged'))
    queue(fig, 'ResizeFcn', evdata(fig, 'SizeChanged'))


def _size_px(fig):
    from .uiobjects import inner_px
    w, h = inner_px(fig)
    return round(w), round(h)


def shown(fig):
    """A figure shown for the first time, or shown at a size its program has
    not heard of (set while it was hidden, or by the program itself), runs
    its SizeChangedFcn and ResizeFcn: programs lay out their panels and
    controls there."""
    if not fig.valid or not fig.props['Visible']:
        return
    size = _size_px(fig)
    if fig.__dict__.get('sized') == size:
        return
    fig.__dict__['sized'] = size
    queue(fig, 'SizeChangedFcn', evdata(fig, 'SizeChanged'))
    queue(fig, 'ResizeFcn', evdata(fig, 'SizeChanged'))


_HANDLERS = {'control': _control, 'menu': _menu, 'menuopen': _menu, 'tool': _tool, 'key': _key, 'down': _mouse, 'up': _mouse,
             'motion': _mouse, 'scroll': _mouse, 'closerequest': _close, 'resize': _resize}


def handle(ev):
    """Something a person did in a figure; the number of callbacks it queued."""
    n0 = len(QUEUE)
    t = ev.get('type')
    if t == 'timer':
        tm = TIMERS.get(ev.get('id'))
        if tm is not None:
            tm.tick()
        return len(QUEUE) - n0
    obj = STORE.objects.get(ev.get('id'))
    if obj is None or not obj.valid:
        return 0
    fig = obj.figure()
    if fig is None:
        return 0
    if fig.props['HandleVisibility'] == 'on' and t not in ('motion', 'up', 'resize', 'scroll'):
        STORE.current = fig
    fn = _HANDLERS.get(t)
    if fn is not None:
        fn(obj, fig, ev)
    return len(QUEUE) - n0


# ---- waiting for people ------------------------------------------------------------------------

async def wait_until(done, timeout=None):
    """Let callbacks run until done() (uiwait, waitfor), Ctrl+C or the time
    is up."""
    R.flush()
    R.flush_figures()
    end = time.perf_counter() + timeout if timeout is not None else None
    while not done():
        if end is not None and time.perf_counter() >= end:
            break
        if R.SYNC[0]:
            raise MError('MATLAB:callbackWait', 'This function cannot wait for input here (it runs inside a numerical routine).')
        await asyncio.sleep(0.02)
        if R.INTERRUPT[0]:
            R.INTERRUPT[0] = False
            raise Interrupt()
        await process(wait=False)
    R._TICK[1] = time.perf_counter()


# ---- timers ------------------------------------------------------------------------------------

_timer_ids = itertools.count(1)


class Timer(Obj):
    """timer(...): runs its TimerFcn after StartDelay seconds and then every
    Period seconds (as ExecutionMode says), as the page's clock tells it."""
    __slots__ = ('id', 'props', 'valid', 'running', 'pending')
    is_handle = True
    cls = 'timer'
    MODES = ('singleshot', 'fixedrate', 'fixedspacing', 'fixeddelay')
    BUSY = ('drop', 'error', 'queue')
    READONLY = ('Running', 'TasksExecuted', 'Type', 'InstantPeriod', 'AveragePeriod')
    WHILE_STOPPED = ('Period', 'ExecutionMode', 'BusyMode', 'StartDelay', 'TasksToExecute')

    def __init__(self):
        self.id = next(_timer_ids)
        self.valid = True
        self.running = False
        self.pending = 0
        self.props = {'AveragePeriod': float('nan'), 'BusyMode': 'drop', 'ErrorFcn': '', 'ExecutionMode': 'singleShot',
                      'InstantPeriod': float('nan'), 'Name': f'timer-{self.id}', 'ObjectVisibility': 'on', 'Period': 1.0,
                      'Running': 'off', 'StartDelay': 0.0, 'StartFcn': '', 'StopFcn': '', 'Tag': '', 'TasksExecuted': 0.0,
                      'TasksToExecute': float('inf'), 'TimerFcn': '', 'Type': 'timer', 'UserData': EMPTY()}
        TIMERS[self.id] = self

    def figure(self):
        return None

    def canon(self, name):
        low = name.lower()
        for k in self.props:
            if k.lower() == low:
                return k
        hits = [k for k in self.props if k.lower().startswith(low)]
        return hits[0] if len(hits) == 1 else None

    def getprop(self, name):
        if not self.valid:
            raise gerr('Invalid or deleted object.', 'MATLAB:class:InvalidHandle')
        k = self.canon(name)
        if k is None:
            raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized property '{name}' for class 'timer'.")
        v = self.props[k]
        if k == 'Running':
            return Char.of('on' if self.running else 'off')
        if isinstance(v, str):
            return Char.of(v)
        return v

    def setprop(self, name, value):
        if not self.valid:
            raise gerr('Invalid or deleted object.', 'MATLAB:class:InvalidHandle')
        k = self.canon(name)
        if k is None:
            raise MError('MATLAB:noPublicFieldForClass', f"Unrecognized property '{name}' for class 'timer'.")
        if k in self.READONLY:
            raise MError('MATLAB:timer:propReadOnly', f"Property '{k}' of a timer is read-only.")
        if self.running and k in self.WHILE_STOPPED:
            raise MError('MATLAB:timer:propReadOnlyWhileRunning', f"Property '{k}' cannot be changed while the timer is running.")
        if k in ('Period', 'StartDelay', 'TasksToExecute'):
            v = float(np.asarray(value, float).reshape(-1)[0])
            if k == 'Period' and v < 0.001:
                raise MError('MATLAB:timer:badPeriod', 'Period must be at least 0.001 seconds.')
            if k == 'TasksToExecute' and v < 1:
                raise MError('MATLAB:timer:badTasks', 'TasksToExecute must be at least 1.')
            if k == 'StartDelay' and v < 0:
                raise MError('MATLAB:timer:badDelay', 'StartDelay must not be negative.')
            self.props[k] = v
            return
        if k == 'ExecutionMode':
            s = py_str(value)
            if s.lower() not in self.MODES:
                raise MError('MATLAB:timer:badMode', "ExecutionMode must be 'singleShot', 'fixedRate', 'fixedSpacing' or 'fixedDelay'.")
            self.props[k] = {'singleshot': 'singleShot', 'fixedrate': 'fixedRate', 'fixedspacing': 'fixedSpacing', 'fixeddelay': 'fixedDelay'}[s.lower()]
            return
        if k == 'BusyMode':
            s = py_str(value).lower()
            if s not in self.BUSY:
                raise MError('MATLAB:timer:badBusyMode', "BusyMode must be 'drop', 'error' or 'queue'.")
            self.props[k] = s
            return
        if k in ('Name', 'Tag', 'ObjectVisibility'):
            self.props[k] = py_str(value)
            return
        if k.endswith('Fcn'):
            self.props[k] = py_str(value) if type(value) in (Char, Str) else value
            return
        self.props[k] = value

    def propnames(self):
        return sorted(self.props)

    def display_lines(self):
        p = self.props
        fcn = p['TimerFcn']
        what = fcn if isinstance(fcn, str) else (fcn.text() if isinstance(fcn, FH) else '(a cell array)')
        return [f"   Timer Object: {p['Name']}", '',
                '   Timer Settings',
                f"      ExecutionMode: {p['ExecutionMode']}",
                f"             Period: {p['Period']:g}",
                f"           BusyMode: {p['BusyMode']}",
                f"            Running: {'on' if self.running else 'off'}", '',
                '   Callbacks',
                f"           TimerFcn: {what or chr(39) * 2}"]

    def equals(self, other):
        return self is other

    def number_value(self):
        return float(self.id)

    def _event(self, kind):
        t = time.localtime()
        clock = np.array([[t.tm_year, t.tm_mon, t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec + (time.time() % 1)]], float)
        return Struct.scalar({'Type': Char.of(kind), 'Data': Struct.scalar({'time': clock})})

    def start(self):
        """Running; the page's clock is asked for the ticks. StartFcn is run
        by the caller."""
        self.running = True
        self.pending = 0
        self.props['TasksExecuted'] = 0.0
        hook = R.EVENT_HOOK[0]
        if hook is not None:
            hook({'type': 'timer', 'op': 'start', 'id': self.id, 'delay': float(self.props['StartDelay']),
                  'period': float(self.props['Period']), 'mode': self.props['ExecutionMode']})

    def halt(self):
        if not self.running:
            return False
        self.running = False
        hook = R.EVENT_HOOK[0]
        if hook is not None:
            hook({'type': 'timer', 'op': 'stop', 'id': self.id})
        return True

    def tick(self):
        if not self.valid or not self.running:
            return
        if self.pending and self.props['BusyMode'] != 'queue':
            if self.props['BusyMode'] == 'error':
                queue(self, 'ErrorFcn', self._event('ErrorFcn'))
            return
        self.props['TasksExecuted'] += 1
        if callback_of(self, 'TimerFcn') is not None:
            self.pending += 1
            QUEUE.append((self, 'TimerFcn', self._event('TimerFcn')))
        if self.props['TasksExecuted'] >= self.props['TasksToExecute'] or self.props['ExecutionMode'] == 'singleShot':
            self.halt()
            queue(self, 'StopFcn', self._event('StopFcn'))

    def remove(self):
        if self.halt():
            queue(self, 'StopFcn', self._event('StopFcn'))
        self.valid = False
        TIMERS.pop(self.id, None)

    delete_handle = remove


def stop_all_timers():
    for t in list(TIMERS.values()):
        t.halt()
