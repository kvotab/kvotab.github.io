"""numba's cache, shared by processes compiling at once (``compiled.guard_numba_cache``).

numba keeps a function's compiled versions in an index and numbered data
files, and adds one with no lock: two processes adding versions of one
function at once can both take a number, and the index then files one
version's types against the other's code. A split run's workers compiling
their parts did that, and a part whose compile found the wrong code went to
the Python path. This package's functions read and write their cache under a
file lock; the tests here hold it to that: processes compiling versions of
one function at once, and a process after them, never find code that is not
what they asked for. And a generated module's source, which numba files its
code by the time of, is written once.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from helpers import PACKAGE
from test_engine_compiled import HAVE_NUMBA, needs_numba

if HAVE_NUMBA:
    from kompartment.engine.compiled import CACHE_LOCK_NAME, cache_lock, guard_numba_cache, sources_stamp
    from kompartment.engine.compiled.model import _write

#: A function a process compiles a version of for every number it is called
#: with (numba compiles a number written into the call as a type of its own),
#: in a module named as the generated ones are.
LIB = '''
from numba import njit


@njit(cache=True)
def helper(a, k, j):
    return a[0] * 1000 + k * 10 + j
'''

#: A process asking for every version of it, in an order of its own, once
#: the clock reaches the start it is given: one line for each it could not
#: compile or that came back wrong.
CHILD = '''
import random
import sys
import time

from kompartment.engine.compiled import guard_numba_cache

guard_numba_cache()

import numpy as np
from numba import njit

import kompartment_compiled_cachetest as lib

me, count, start = int(sys.argv[1]), int(sys.argv[2]), float(sys.argv[3])
order = list(range(count))
random.Random(me).shuffle(order)
while time.time() < start:
    time.sleep(0.001)
for k in order:
    ns = {'helper': lib.helper}
    exec(f'def caller(a):\\n    return helper(a, {k}, {k % 3})\\n', ns)
    try:
        got = njit(ns['caller'])(np.ones(1))
    except Exception as e:
        print('failed', k, type(e).__name__, flush=True)
        continue
    if got != 1000 + 10 * k + k % 3:
        print('wrong', k, got, flush=True)
'''


def can_lock(directory: str, how: str) -> bool:
    """Whether another process can take the directory's lock ``how``
    (LOCK_SH or LOCK_EX) at once."""
    code = ('import fcntl, os, sys\n'
            f'fd = os.open(os.path.join({directory!r}, {CACHE_LOCK_NAME!r}), os.O_RDWR | os.O_CREAT)\n'
            f'try:\n    fcntl.flock(fd, fcntl.{how} | fcntl.LOCK_NB)\n'
            'except BlockingIOError:\n    sys.exit(1)\n')
    return subprocess.run([sys.executable, '-c', code], timeout=60).returncode == 0


@needs_numba
@unittest.skipUnless(os.name == 'posix', 'the lock is POSIX only')
class Guarded(unittest.TestCase):
    def test_this_packages_functions_and_no_others(self) -> None:
        from numba import njit
        from numba.core import caching

        from kompartment.engine.compiled import runtime
        guard_numba_cache()
        ours = type(runtime.history_hold._cache._cache_file)
        self.assertIsNot(ours, caching.IndexDataCacheFile)
        self.assertTrue(issubclass(ours, caching.IndexDataCacheFile))

        def elsewhere(x):  # pragma: no cover - never compiled, only given a cache
            return x

        elsewhere.__module__ = 'someone_else'
        theirs = njit(cache=True)(elsewhere)._cache._cache_file
        self.assertIs(type(theirs), caching.IndexDataCacheFile)
        self.assertNotIsInstance(theirs._source_stamp, tuple)

    def test_filed_by_every_source_the_code_is_built_from(self) -> None:
        # numba files a function's code by its own module's source, and builds
        # into it the code of what it calls in other modules: runtime's
        # far-field refresh carries farfield.py's. A change to farfield.py
        # alone left the old code in it -- and in every model compiled after
        # -- so this package's functions are filed by the engine's sources too.
        from kompartment.engine.compiled import farfield, runtime
        for fn in (runtime.farf_refresh, runtime.recorder_store, farfield.refresh):
            stamp = fn._cache._cache_file._source_stamp
            with self.subTest(fn=fn.__name__):
                self.assertIsInstance(stamp, tuple)
                self.assertEqual(stamp[1], sources_stamp())
        self.assertRegex(sources_stamp(), r'^[0-9a-f]{16}$')

    def test_readers_share_it_and_a_writer_has_it_alone(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            with cache_lock(d, shared=False):
                self.assertFalse(can_lock(d, 'LOCK_SH'))
                # A thread holding it takes it again at once (a load can import a module that compiles).
                with cache_lock(d, shared=True):
                    pass
            with cache_lock(d, shared=True):
                self.assertTrue(can_lock(d, 'LOCK_SH'))
                self.assertFalse(can_lock(d, 'LOCK_EX'))
            self.assertTrue(can_lock(d, 'LOCK_EX'))
        # A directory not yet made has nothing to read: not locked, not made.
        with tempfile.TemporaryDirectory() as d:
            missing = os.path.join(d, 'not yet')
            with cache_lock(missing, shared=True):
                pass
            self.assertFalse(os.path.exists(missing))

    def test_processes_compiling_one_function_at_once(self) -> None:
        processes, versions = 10, 60
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, 'kompartment_compiled_cachetest.py'), 'w', encoding='utf-8') as f:
                f.write(LIB)
            env = {**os.environ, 'PYTHONPATH': os.pathsep.join([str(PACKAGE), d])}

            def start(me: int, at: float) -> subprocess.Popen:
                return subprocess.Popen([sys.executable, '-c', CHILD, str(me), str(versions), str(at)],
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)

            at = time.time() + 3.0
            said = []
            for p in [start(i, at) for i in range(processes)]:
                out, err = p.communicate(timeout=600)
                self.assertEqual(p.returncode, 0, err[-2000:])
                said += out.split('\n')
            self.assertEqual([s for s in said if s], [], 'compiling at once')
            # And what they left: every version, as a process after them finds it.
            p = start(processes, 0.0)
            out, err = p.communicate(timeout=600)
            self.assertEqual(p.returncode, 0, err[-2000:])
            self.assertEqual(out.split(), [], 'read afterwards')
            self.assertTrue(os.path.isfile(os.path.join(d, '__pycache__', CACHE_LOCK_NAME)))


@needs_numba
class Source(unittest.TestCase):
    def test_written_once_and_kept(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'km_test.py'
            _write(path, b'x = 1\n')
            os.utime(path, ns=(10**18, 10**18))
            # The same source again leaves the file as it is, its time included.
            _write(path, b'x = 1\n')
            self.assertEqual(path.stat().st_mtime_ns, 10**18)
            # Another is put in its place.
            _write(path, b'x = 2\n')
            self.assertEqual(path.read_bytes(), b'x = 2\n')
            self.assertEqual(sorted(os.listdir(d)), ['km_test.py'])


if __name__ == '__main__':
    unittest.main()
