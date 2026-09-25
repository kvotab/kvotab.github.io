"""The blocks that remember: min/max, running mean, snapshot, delay -- and triggers.

Ports of ``src/domain/recorders.js`` (the kinds and their fields) and
``src/sim/history.js`` (what one of them keeps at one index). A remembering
block is not a function of the state: it keeps (time, value) pairs recorded
as the solver accepts steps, and reads them back.
"""

from __future__ import annotations

import math
from typing import List

RECORDER_KINDS = ('min_max', 'running_mean', 'snapshot', 'delay', 'trigger')
REMEMBERING_KINDS = ('min_max', 'running_mean', 'snapshot', 'delay')
RECORDER_COLLECTION = {
    'min_max': 'min_maxes', 'running_mean': 'running_means', 'snapshot': 'snapshots', 'delay': 'delays',
    'trigger': 'triggers',
}
EXTREMES = ('max', 'min')
DIRECTIONS = ('rising', 'falling', 'both')
DIRECTION_SIGN = {'rising': 1, 'falling': -1, 'both': 0}
DIRECTION_FROM_ECO = {'RIGHT': 'rising', 'LEFT': 'falling', 'BOTH': 'both', '->': 'rising', '<-': 'falling',
                      '>-<': 'both'}
EVENT_FIELDS = {
    'min_max': ('reset_trigger', 'start_trigger', 'stop_trigger'),
    'running_mean': ('reset_trigger', 'start_trigger', 'stop_trigger'),
    'snapshot': ('trigger',),
    'delay': (),
    'trigger': (),
}
EVENT_ACTION = {'reset_trigger': 'reset', 'start_trigger': 'start', 'stop_trigger': 'stop', 'trigger': 'snapshot'}
EQUATION_FIELDS = {
    'min_max': ('target',),
    'running_mean': ('target',),
    'snapshot': ('target', 'initial'),
    'delay': ('target', 'delay'),
    'trigger': ('first', 'second'),
}


def extreme_from_eco(name: object) -> str:
    s = str(name if name is not None else '').strip().upper()
    return 'min' if s == 'MIN' else ('max' if s == 'MAX' else '')


def direction_from_eco(name: object) -> str:
    s = str(name if name is not None else '').strip()
    return DIRECTION_FROM_ECO.get(s.upper()) or DIRECTION_FROM_ECO.get(s) or ''


class History:
    """A growing list of (time, value) pairs, read back by time."""

    __slots__ = ('t', 'v')

    def __init__(self) -> None:
        self.t: List[float] = []
        self.v: List[float] = []

    def __len__(self) -> int:
        return len(self.t)

    def clear(self) -> None:
        self.t.clear()
        self.v.clear()

    @property
    def last_time(self) -> float:
        return self.t[-1] if self.t else -math.inf

    @property
    def last_value(self) -> float:
        return self.v[-1] if self.v else 0.0

    def add(self, time: float, value: float) -> None:
        n = len(self.t)
        if n and time <= self.t[-1]:
            self.t[-1] = time
            self.v[-1] = value
            return
        if n >= 2 and self.v[-1] == value and self.v[-2] == value:
            self.t[-1] = time
            return
        self.t.append(time)
        self.v.append(value)

    def forget(self, before: float) -> None:
        cut = self._below(before)
        if not (cut > 1):
            return
        del self.t[:cut - 1]
        del self.v[:cut - 1]

    def _below(self, time: float) -> int:
        lo, hi = 0, len(self.t) - 1
        if hi < 0 or time < self.t[0]:
            return -1
        t = self.t
        while lo < hi:
            mid = (lo + hi + 1) >> 1
            if t[mid] <= time:
                lo = mid
            else:
                hi = mid - 1
        return lo

    def hold(self, time: float) -> float:
        n = len(self.t)
        if not n:
            return 0.0
        if time <= self.t[0]:
            return self.v[0]
        if time >= self.t[-1]:
            return self.v[-1]
        return self.v[self._below(time)]

    def lerp(self, time: float) -> float:
        n = len(self.t)
        if not n:
            return 0.0
        if time <= self.t[0]:
            return self.v[0]
        if time >= self.t[-1]:
            return self.v[-1]
        i = self._below(time)
        t0, t1 = self.t[i], self.t[i + 1]
        if t1 == t0:
            return self.v[i + 1]
        return self.v[i] + ((time - t0) / (t1 - t0)) * (self.v[i + 1] - self.v[i])


class Recorder:
    """One remembering block at one index tuple (``MEM[k]``)."""

    __slots__ = ('kind', 'history', 'sign', 'starts_recording', 'recording', 'total_time', 'last_time',
                 'reset_sum')

    def __init__(self, kind: str, operation: str = 'max', recording: bool = True) -> None:
        self.kind = kind
        self.history = History()
        self.sign = -1 if operation == 'min' else 1
        self.starts_recording = recording
        self.recording = recording
        self.total_time = 0.0
        self.last_time = 0.0
        self.reset_sum = 0.0

    def prime(self, t0: float, seed: float) -> None:
        self.history.clear()
        self.recording = self.starts_recording
        self.total_time = 0.0
        self.last_time = t0
        self.reset_sum = 0.0
        if self.kind == 'running_mean':
            self.history.add(t0, seed if self.recording else 0.0)
            return
        self.history.add(t0, seed)

    def store(self, t: float, current: float) -> None:
        k = self.kind
        if k == 'min_max':
            if current != self.history.last_value:
                self.history.add(t, current)
        elif k == 'delay':
            self.history.add(t, current)
        elif k == 'running_mean':
            if self.recording:
                self.history.add(t, current)
                self.total_time += t - self.last_time
            self.last_time = t

    def fire(self, what: str, t: float, target: float, summed: float = 0.0) -> None:
        if what == 'snapshot':
            self.history.add(t, target)
        elif what == 'reset':
            self.history.add(t, target)
            if self.kind == 'running_mean':
                self.reset_sum = summed
                self.total_time = 0.0
                self.last_time = t
        elif what == 'start':
            self.recording = True
            self.last_time = t
        elif what == 'stop':
            self.recording = False

    def extreme(self, t: float, target: float) -> float:
        if t <= self.history.last_time:
            return self.history.hold(t)
        if not self.recording:
            return self.history.last_value
        last = self.history.last_value
        # Math.max / Math.min: NaN wins.
        if last != last or target != target:
            return math.nan
        return max(last, target) if self.sign > 0 else min(last, target)

    def held(self, t: float) -> float:
        return self.history.hold(t)

    def delayed(self, t: float, lag: float) -> float:
        return self.history.lerp(t - lag)

    def elapsed_at(self, t: float) -> float:
        return self.total_time + t - self.last_time if self.recording else self.total_time

    def mean(self, t: float, summed: float, target: float) -> float:
        if t <= self.history.last_time:
            return self.history.hold(t)
        elapsed = self.elapsed_at(t)
        return (summed - self.reset_sum) / elapsed if elapsed > 0 else target
