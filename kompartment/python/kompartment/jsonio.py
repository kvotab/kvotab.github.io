"""Writing a model file the way the application writes one.

``JSON.stringify(model, null, 2)`` and Python's ``json.dumps(..., indent=2)``
agree on everything but numbers: Python writes ``100000.0`` and ``1.5e-05``
where JavaScript writes ``100000`` and ``0.000015``. Both read back as the same
number, but a file saved from Python would then differ from the same model
saved from Kompartment on every such line. So numbers are written here the way
JavaScript writes them, and a model round-trips through Python byte for byte.

Reading and writing ``.json``, ``.json.gz`` and ``.zip`` model files is here
too: a ZIP holds the model as a ``.json`` entry at its root (a saved run, when
it carries one, is under ``results/`` and is not read here).
"""

from __future__ import annotations

import gzip
import io
import json
import math
import re
import zipfile
from decimal import Decimal
from pathlib import Path
from typing import Any, Union

PathLike = Union[str, Path]


def js_number(x: Union[int, float]) -> str:
    """A number as JavaScript's ``String(x)`` writes it.

    The shortest digits that round-trip -- which Python's ``repr`` and
    JavaScript agree on -- laid out by JavaScript's rule: plain up to 21 digits
    before the point and down to six zeros after it (``100000``, ``0.000015``),
    exponential beyond (``1e-7``, ``1.5e+21``). NaN and the infinities have no
    JSON form and come out as ``null``, as ``JSON.stringify`` writes them.
    """
    if isinstance(x, bool):
        return 'true' if x else 'false'
    if isinstance(x, int):
        return str(x)
    if math.isnan(x) or math.isinf(x):
        return 'null'
    if x == 0:
        return '0'
    sign = '-' if x < 0 else ''
    t = Decimal(repr(abs(x))).normalize().as_tuple()
    digits = ''.join(map(str, t.digits))
    k = len(digits)
    n = k + int(t.exponent)  # value = 0.digits x 10^n
    if k <= n <= 21:
        return sign + digits + '0' * (n - k)
    if 0 < n <= 21:
        return f'{sign}{digits[:n]}.{digits[n:]}'
    if -6 < n <= 0:
        return f"{sign}0.{'0' * (-n)}{digits}"
    e = n - 1
    mant = digits if k == 1 else f'{digits[0]}.{digits[1:]}'
    return f"{sign}{mant}e{'+' if e >= 0 else '-'}{abs(e)}"


def dumps(value: Any, indent: int = 2) -> str:
    """``value`` as JSON text, formatted as ``JSON.stringify(value, null, indent)``."""
    out: list = []
    _write(value, out, 0, indent)
    return ''.join(out)


def _write(value: Any, out: list, depth: int, indent: int) -> None:
    if value is None:
        out.append('null')
    elif isinstance(value, bool):
        out.append('true' if value else 'false')
    elif isinstance(value, (int, float)):
        out.append(js_number(value))
    elif isinstance(value, str):
        out.append(json.dumps(value, ensure_ascii=False))
    elif isinstance(value, dict):
        items = [(k, v) for k, v in value.items() if not _undefined(v)]
        if not items:
            out.append('{}')
            return
        pad = '\n' + ' ' * (indent * (depth + 1)) if indent else ''
        out.append('{')
        for i, (k, v) in enumerate(items):
            if i:
                out.append(',')
            out.append(pad)
            out.append(json.dumps(str(k), ensure_ascii=False))
            out.append(': ' if indent else ':')
            _write(v, out, depth + 1, indent)
        out.append('\n' + ' ' * (indent * depth) if indent else '')
        out.append('}')
    elif isinstance(value, (list, tuple)):
        if not value:
            out.append('[]')
            return
        pad = '\n' + ' ' * (indent * (depth + 1)) if indent else ''
        out.append('[')
        for i, v in enumerate(value):
            if i:
                out.append(',')
            out.append(pad)
            _write(None if _undefined(v) else v, out, depth + 1, indent)
        out.append('\n' + ' ' * (indent * depth) if indent else '')
        out.append(']')
    else:
        raise TypeError(f'{type(value).__name__} is not something a model file can hold')


def _undefined(v: Any) -> bool:
    # JavaScript drops a property whose value is undefined; Python has no such
    # value, so nothing is dropped. Kept as a hook for symmetry with `dumps`.
    return False


def read_model_file(path: PathLike) -> dict:
    """The model a ``.json``, ``.json.gz``/``.gz`` or ``.zip`` file holds."""
    p = Path(path)
    data = p.read_bytes()
    if data[:2] == b'\x1f\x8b':
        data = gzip.decompress(data)
    elif data[:4] == b'PK\x03\x04':
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = [n for n in z.namelist()
                     if not n.startswith('results/') and n.lower().endswith('.json')]
            if not names:
                raise ValueError(f"'{p.name}' is a ZIP archive with no model in it: it holds "
                                 f"{', '.join(z.namelist()[:4])}")
            data = z.read(names[0])
    text = data.decode('utf-8-sig')
    model = json.loads(text)
    if not isinstance(model, dict):
        raise ValueError(f"'{p.name}' does not hold a model: a model is one JSON object")
    return model


def slug(name: Any) -> str:
    """The file name a model's name gives, as the application makes it."""
    s = re.sub(r'\W+', '-', str(name or ''), flags=re.ASCII).lower().strip('-')
    return s or 'model'


def write_model_file(path: PathLike, model: dict, indent: int = 2) -> Path:
    """Writes a model as ``.json``, ``.json.gz``/``.gz`` or ``.zip`` by the name's ending."""
    p = Path(path)
    text = dumps(model, indent)
    lower = p.name.lower()
    if lower.endswith('.zip'):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr(f"{slug(model.get('name'))}.json", text)
        p.write_bytes(buf.getvalue())
    elif lower.endswith('.gz'):
        p.write_bytes(gzip.compress(text.encode('utf-8')))
    else:
        p.write_text(text, encoding='utf-8')
    return p
