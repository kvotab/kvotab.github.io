"""What the tests share: the paths, and the application's own code through Node."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List

HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parent
APP = PACKAGE.parent  # kompartment/, the application
SRC = APP / 'src'
EXAMPLES = APP / 'examples'

if str(PACKAGE) not in sys.path:
    sys.path.insert(0, str(PACKAGE))

NODE = shutil.which('node')
HAVE_APP = NODE is not None and (SRC / 'domain' / 'project.js').is_file()

needs_app = unittest.skipUnless(HAVE_APP, 'needs node and the Kompartment sources')


def app(task: str, **request: Any) -> Dict[str, Any]:
    """Asks the application's own code (see tests/node/app.mjs)."""
    assert NODE is not None
    proc = subprocess.run([NODE, str(HERE / 'node' / 'app.mjs'), str(SRC)],
                          input=json.dumps({'task': task, **request}), capture_output=True,
                          text=True, timeout=600, encoding='utf-8')
    if proc.returncode:
        raise RuntimeError(proc.stderr)
    return json.loads(proc.stdout)


def example(name: str) -> Dict[str, Any]:
    return json.loads((EXAMPLES / f'{name}.json').read_text('utf-8'))


def differences(a: Any, b: Any, path: str = '', out: List[str] = None) -> List[str]:
    """Where two JSON values differ, key order included, as readable lines."""
    out = [] if out is None else out
    if isinstance(a, bool) or isinstance(b, bool):
        if a is not b and a != b:
            out.append(f'{path}: {a!r} != {b!r}')
        return out
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if a != b:
            out.append(f'{path}: {a!r} != {b!r}')
        return out
    if type(a) is not type(b):
        out.append(f'{path}: {type(a).__name__} {a!r:.80} != {type(b).__name__} {b!r:.80}')
        return out
    if isinstance(a, dict):
        for k in list(a) + [k for k in b if k not in a]:
            if k not in a:
                out.append(f'{path}/{k}: missing here, {b[k]!r:.80} there')
            elif k not in b:
                out.append(f'{path}/{k}: {a[k]!r:.80} here, missing there')
            else:
                differences(a[k], b[k], f'{path}/{k}', out)
        if set(a) == set(b) and list(a) != list(b):
            out.append(f'{path}: key order {list(a)} != {list(b)}')
    elif isinstance(a, list):
        if len(a) != len(b):
            out.append(f'{path}: {len(a)} items != {len(b)}')
        for i, (x, y) in enumerate(zip(a, b)):
            differences(x, y, f'{path}[{i}]', out)
    elif a != b:
        out.append(f'{path}: {a!r:.80} != {b!r:.80}')
    return out
