"""A line that says how far a long run has got, in a terminal or a notebook.

``run_probabilistic(..., progress=True)`` draws one::

    Probabilistic run [#########---------------] 380/1000 realisations  38%  0:41, about 1:07 left

It is redrawn in place where the stream is a terminal or a notebook, at most
ten times a second, and written as a line per tenth of the way where it is
not (a log file), so that a log is not flooded. The estimate of the time left
is the pace since the first run finished: the first one also builds and,
compiled, compiles the model, and would make every estimate after it too
long. It goes to standard error, as a progress bar usually does, except in a
notebook, which shows standard error on a red ground; ``progress=`` may also
be a stream of the caller's own.
"""

from __future__ import annotations

import sys
import time
from typing import Any, Optional

#: The width of the bar, in characters.
BAR = 24
#: The least time between two redraws in place, in seconds.
REDRAW = 0.1


def clock(seconds: float) -> str:
    """``m:ss``, or ``h:mm:ss`` from an hour."""
    s = max(0, int(round(seconds)))
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f'{h}:{m:02d}:{s:02d}' if h else f'{m}:{s:02d}'


def _in_notebook() -> bool:
    return 'ipykernel' in sys.modules


class ProgressLine:
    """``line(done)`` after each run, ``line.close(failed)`` at the end.

    ``total`` may change once the run knows it (a tornado or a sensitivity
    design is not ``iterations`` runs long): set :attr:`total`.
    """

    def __init__(self, total: int, *, what: str = 'realisations', title: str = 'Probabilistic run',
                 stream: Any = None) -> None:
        self.total = max(0, int(total))
        self.what = what
        self.title = title
        if stream is None or stream is True:
            stream = sys.stdout if _in_notebook() else sys.stderr
        self.stream = stream
        try:
            tty = bool(stream.isatty())
        except Exception:  # noqa: BLE001 - a stream that cannot say is not a terminal
            tty = False
        self.in_place = tty or (_in_notebook() and stream in (sys.stdout, sys.stderr))
        self.started = time.perf_counter()
        self.done = 0
        self._first: Optional[float] = None     # when the first run finished
        self._first_done = 0
        self._drawn = 0.0                       # when the line was last drawn in place
        self._width = 0                         # how long it was, to clear what is left of it
        self._tenth = 0                         # the last tenth written as a line of its own
        self.closed = False
        self._draw()

    # --- what it says --------------------------------------------------------------------------

    def left(self) -> Optional[float]:
        """The time left at the pace since the first run finished, if there is one yet."""
        if self._first is None or self.done <= self._first_done or self.done >= self.total:
            return None
        pace = (time.perf_counter() - self._first) / (self.done - self._first_done)
        return pace * (self.total - self.done)

    def text(self) -> str:
        """The line as it stands: bar, count, share, time so far and time left."""
        n, total = self.done, self.total
        share = n / total if total else 1.0
        fill = int(round(BAR * share))
        line = (f'{self.title} [{"#" * fill}{"-" * (BAR - fill)}] {n}/{total} {self.what} '
                f'{100 * share:3.0f}%  {clock(time.perf_counter() - self.started)}')
        left = self.left()
        return line if left is None else f'{line}, about {clock(left)} left'

    # --- drawing -------------------------------------------------------------------------------

    def _write(self, text: str) -> None:
        try:
            self.stream.write(text)
            self.stream.flush()
        except Exception:  # noqa: BLE001 - a closed or odd stream must never stop the run
            pass

    def _draw(self) -> None:
        text = self.text()
        if self.in_place:
            self._write('\r' + text + ' ' * max(0, self._width - len(text)))
            self._width = len(text)
            self._drawn = time.perf_counter()
        elif self.done == 0:
            self._write(text + '\n')

    def set_total(self, total: int) -> None:
        """The run's length, once it is known."""
        self.total = max(0, int(total))
        if self.in_place and not self.closed:
            self._draw()

    def __call__(self, done: int, total: Optional[int] = None) -> None:
        if self.closed:
            return
        if total is not None:
            self.total = max(0, int(total))
        done = int(done)
        if done <= self.done:
            return
        now = time.perf_counter()
        if self._first is None:
            self._first, self._first_done = now, done
        self.done = done
        if self.in_place:
            if now - self._drawn >= REDRAW or done >= self.total:
                self._draw()
            return
        tenth = (10 * done) // self.total if self.total else 10
        if self._tenth < tenth < 10:
            self._tenth = tenth
            self._write(self.text() + '\n')

    def close(self, failed: int = 0, stopped: bool = False) -> None:
        """The last word: how many and how long, or where it stopped."""
        if self.closed:
            return
        self.closed = True
        took = clock(time.perf_counter() - self.started)
        if stopped:
            text = f'{self.title} stopped after {self.done} of {self.total} {self.what}, {took}'
        else:
            text = f'{self.title}: {self.total} {self.what} in {took}'
            if failed:
                text += f', {failed} failed'
        if self.in_place:
            self._write('\r' + text + ' ' * max(0, self._width - len(text)) + '\n')
        else:
            self._write(text + '\n')
