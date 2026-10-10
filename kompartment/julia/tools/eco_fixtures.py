#!/usr/bin/env python3
"""What the Python package's Ecolego importer makes of every input, for the
Julia port's tests (test/importers/test_eco.jl) to compare with.

    python3 tools/eco_fixtures.py OUTDIR [--synthetic [--more N]] [--real] [--jobs N]

For every input this runs ``kompartment.importers.eco.import_eco_file`` (or
``import_model_xml``) and writes what came out into OUTDIR:

``manifest.json``
    one record per case: ``id``, ``label``, ``source`` (``synthetic`` or
    ``real``), ``kind`` (``xml``: the payload is model.xml text; ``file``: the
    payload is a file's bytes; ``path``: the case is read from ``path``),
    ``file_name``, ``version``, and for a real file its ``size`` and ``mtime``
    (so a test can tell the file changed since).
``cases/<id>.payload``
    a synthetic case's input (UTF-8 text for ``xml``, bytes for ``file``).
``cases/<id>.project.json`` and ``cases/<id>.report.json``
    ``kompartment.jsonio.dumps`` of the project, and of the report's fields
    (``ImportReport.to_dict()``), exactly as Python writes them;
``cases/<id>.error.json``
    instead of those two, for an input the importer refuses:
    ``{"type": <exception class>, "message": str(e)}``.

The inputs:

* ``--synthetic``: the application's hand-written fixture
  (``kompartment/test/eco-fixture.js``) and every variant the Python package's
  own tests build of it (``kompartment/python/tests/test_eco_import.py``, which
  drives Node through ``tests/node/eco_import.mjs``), the 200 random models,
  and a few more corners made up here; with ``--more N``, N more random
  models, N model texts mutated at random and N/4 damaged archives;
* ``--real``: every ``.eco`` and ``.eas`` file Spotlight finds on this machine,
  once per distinct content (by SHA-256), read by its path.

Real project files are client data: OUTDIR must be outside the repository,
and nothing from them is copied there -- a real case is a path to the file.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
APP = HERE.parent.parent                      # kompartment/
PYTHON = APP / 'python'
TESTS = PYTHON / 'tests'
for p in (str(PYTHON), str(TESTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from kompartment.importers.eco import import_eco_file, import_model_xml  # noqa: E402
from kompartment.jsonio import dumps  # noqa: E402


# --- running one case --------------------------------------------------------------------------

def run_case(kind: str, payload: Any, file_name: Optional[str], version: Optional[str]) -> Dict[str, str]:
    """The importer's answer as the texts the fixture files hold."""
    try:
        if kind == 'xml':
            project, report = import_model_xml(payload, file_name=file_name, version=version)
        elif kind == 'file':
            project, report = import_eco_file(payload, file_name=file_name, version=version)
        else:  # 'path'
            project, report = import_eco_file(payload, version=version)
    except Exception as e:  # noqa: BLE001 - every refusal is part of what is compared
        return {'error': dumps({'type': type(e).__name__, 'message': str(e)})}
    return {'project': dumps(project), 'report': dumps(report.to_dict())}


def write_answer(out: Path, cid: str, answer: Dict[str, str]) -> None:
    for suffix in ('project', 'report', 'error'):
        f = out / 'cases' / f'{cid}.{suffix}.json'
        if f.exists():
            f.unlink()
    for suffix, text in answer.items():
        (out / 'cases' / f'{cid}.{suffix}.json').write_text(text, encoding='utf-8')


# --- the synthetic cases -----------------------------------------------------------------------

def extra_cases(T: Any) -> List[Any]:
    """Corners of the reader the package's own tests do not reach: entities,
    names, positions in UTF-16, encodings, archives."""
    xml, file = T.xml, T.file
    minimal = T.MINIMAL
    out = [
        xml('x entities', '<data-model><block-model>'
            '<component type="expression" name="a&#X41;&#12a;&#x42;&#0;&#1114112;&#xD800;&nbsp;&amp;&lt;&gt;&quot;&apos;&#x1F600;">'
            '<id>X</id><entry type="expression"><equation>1 &amp;&amp; 2 &#x3c; 3</equation></entry></component>'
            '</block-model></data-model>'),
        xml('x odd attribute names', '<data-model><block-model>'
            '<component type="expression" "q"=\'1\' name=\'b c\' name="b\u00a0d" x<y="2">'
            '<id>X</id><entry type="expression"><equation>1</equation></entry></component>'
            '</block-model></data-model>'),
        xml('x NBSP ends a name', '<data-model\u00a0><block-model/></data-model>'),
        xml('x mismatch after an astral character', '<data-model>\U0001F600<a></b></data-model>'),
        xml('x unterminated comment', '<data-model><!-- nothing ends this'),
        xml('x unterminated CDATA', '<data-model><![CDATA[ nothing ends this'),
        xml('x unterminated PI', '<data-model><? nothing ends this'),
        xml('x unterminated declaration', '<data-model><!DOCTYPE nothing ends this'),
        xml('x expected a name', '<data-model>< a/></data-model>'),
        xml('x closing without >', '<data-model></data-model x'),
        xml('x unexpected closing', '</data-model>'),
        xml('x unterminated tag', '<data-model a="1"'),
        xml('x expected =', '<data-model a></data-model>'),
        xml('x expected quote', '<data-model a=1></data-model>'),
        xml('x unterminated value', '<data-model a="1></data-model>'),
        xml('x two roots', '<data-model/><data-model/>'),
        xml('x unclosed', '<data-model><block-model>'),
        xml('x no elements', '<?xml version="1.0"?><!-- only a comment -->'),
        xml('x no data-model', '<root><x/></root>'),
        xml('x data-model deep', '<root><x><data-model><block-model>'
            '<component type="parameter" name="p"><id>P</id><entry type="parameter"><value> 0x1F </value></entry>'
            '</component></block-model></data-model></x></root>'),
        xml('x text in pieces', '<data-model><block-model><component type="expression" name="t">'
            '<id>T<!-- c -->1</id><unit>B<![CDATA[q&amp;]]>/<?pi?>y</unit>'
            '<entry type="expression"><equation>  2 <x/> + 3 </equation></entry></component>'
            '</block-model></data-model>'),
        xml('x Greek units', '<data-model><block-model><component type="expression" name="t"><id>T</id>'
            '<entry type="expression"><equation>1</equation></entry></component></block-model>'
            '<simulation-settings><start-time>0</start-time><end-time>5</end-time>'
            '<time-unit>ΟΔΟΣ</time-unit><simulation-type>straße</simulation-type>'
            '<java-solver>java-ﬆiff</java-solver></simulation-settings></data-model>'),
        file('x UTF-16BE odd byte and lone surrogates', b'\xfe\xff' + (
            '<data-model><block-model><component type="expression" name="s"><id>S</id>'
            '<entry type="expression"><equation>1</equation></entry></component></block-model>'
            '<project-properties name="').encode('utf-16-be') + b'\xd8\x00\x00A\xdc\x00\xd8\x3d\xde\x00'
            + '"/></data-model>'.encode('utf-16-be') + b'\xd8\x00\x00'),
        file('x UTF-16LE high surrogate at the end', b'\xff\xfe' + minimal.encode('utf-16-le') + b'\x00\xd8'),
        file('x UTF-8 broken in every way', (
            b'<data-model><project-properties name="a\xc0\xafb\xe0\x80\x80c\xf0\x90\x80d\xe2\x82\x28e\xf4\x90\x80\x80f'
            b'\xed\xa0\x80g\xff"/>' + minimal[len('<data-model>'):].encode('utf-8') + b'\xf0\x9f\x98')),
        file('x archive with a comment and a prefix', b'PK\x03\x04junk' + T.raw_zip([
            {'name': 'model.xml', 'data': minimal.encode('utf-8')}])[:-2] + b'\x05\x00hello'),
        file('x archive with a short extra field', _zip_with_extra(T, b'\x01\x00\x08\x00ab')),
        file('x archive with a bad unicode path field', _zip_with_extra(T, b'\x75\x70\x03\x00\x01ab')),
        file('x archive name not UTF-8 though flagged', T.raw_zip([
            {'name': b'mod\xe9l.xml', 'data': minimal.encode('utf-8')}])),
        file('x archive name, bytes cut short', T.raw_zip([
            {'name': b'a\xe2\x82', 'data': b'x'}, {'name': 'model.xml', 'data': minimal.encode('utf-8')}])),
        file('x archive entry past the end', _patch_central(T.raw_zip([
            {'name': 'model.xml', 'data': b'hello', 'method': 0}]), 20, '<I', 1000)),
        file('x archive header offset outside', _patch_central(T.raw_zip([
            {'name': 'model.xml', 'data': minimal.encode('utf-8')}]), 42, '<I', 10 ** 6)),
        file('x archive local header damaged', _damage_second_local(T.raw_zip([
            {'name': 'a.txt', 'data': b'a', 'method': 0},
            {'name': 'model.xml', 'data': minimal.encode('utf-8')}]))),
        file('x archive with zip64 sizes', _zip64_sizes(T)),
        file('x stored model', T.raw_zip([{'name': 'model.xml', 'data': minimal.encode('utf-8'), 'method': 0}])),
        file('x deflated version', T.raw_zip([
            {'name': '.version', 'data': b'a=1\nversion = 6.5.85\n'},
            {'name': 'model.xml', 'data': minimal.encode('utf-8')}])),
        file('x damaged version', T.raw_zip([
            {'name': '.version', 'payload': b'\x07garbage', 'size': 7},
            {'name': 'model.xml', 'data': minimal.encode('utf-8')}])),
        file('x ZIP64 end records', _zip64_end(T)),
        file('x ZIP64 on two disks', _zip64_end(T, disks=2)),
        file('x a directory that claims too much', _patch_central(T.raw_zip([
            {'name': 'model.xml', 'data': minimal.encode('utf-8')}]), 24, '<I', 300 * 1024 * 1024)),
        file('x a version nobody reads', _patch_central(T.raw_zip([
            {'name': 'model.xml', 'data': minimal.encode('utf-8')}]), 6, '<B', 64)),
        file('x past the allowance', T.raw_zip([
            {'name': 'a.xml', 'data': bytes(200 * 1024 * 1024)},
            {'name': 'b.xml', 'data': bytes(1024), 'size': 100 * 1024 * 1024},
            {'name': 'model.xml', 'data': minimal.encode('utf-8')}])),
        file('x an entry larger than it says', T.raw_zip([
            {'name': 'c.xml', 'data': bytes(300 * 1024 * 1024), 'size': 0},
            {'name': 'model.xml', 'data': minimal.encode('utf-8')}])),
    ]
    return out


def _zip64_end(T: Any, disks: int = 1) -> bytes:
    """A two-entry archive closed by ZIP64 end records, as a writer does past
    65535 entries or 4 GB."""
    import struct
    minimal = T.MINIMAL.encode('utf-8')
    data = T.raw_zip([{'name': 'a.txt', 'data': b'a', 'method': 0}, {'name': 'model.xml', 'data': minimal}])
    eocd = data[-22:]
    count, cd_size, cd_offset = struct.unpack('<HII', eocd[10:20])
    body = data[:-22]
    at = len(body)
    record = struct.pack('<4sQ2H2L4Q', b'PK\x06\x06', 44, 45, 45, 0, 0, count, count, cd_size, cd_offset)
    locator = struct.pack('<4sLQL', b'PK\x06\x07', 0, at, disks)
    end = struct.pack('<IHHHHIIH', 0x06054B50, 0, 0, 0xFFFF, 0xFFFF, 0xFFFFFFFF, 0xFFFFFFFF, 0)
    return body + record + locator + end


def _patch_central(data: bytes, offset: int, fmt: str, value: int) -> bytes:
    """``data`` with one field of its first central directory record changed."""
    import struct
    out = bytearray(data)
    struct.pack_into(fmt, out, data.index(b'PK\x01\x02') + offset, value)
    return bytes(out)


def _damage_second_local(data: bytes) -> bytes:
    """``data`` with its second local header's signature broken."""
    at = data.index(b'PK\x03\x04', 4)
    return data[:at] + b'PK\x03\x05' + data[at + 4:]


def _zip64_sizes(T: Any) -> bytes:
    """A one-entry archive whose central record gives its sizes in a ZIP64 extra field."""
    import struct
    payload = T.MINIMAL.encode('utf-8')
    data = T.raw_zip([{'name': 'model.xml', 'data': payload, 'method': 0}])
    at = data.index(b'PK\x01\x02')
    head = bytearray(data[at:at + 46])
    extra = struct.pack('<HHQQ', 1, 16, len(payload), len(payload))
    struct.pack_into('<II', head, 20, 0xFFFFFFFF, 0xFFFFFFFF)
    struct.pack_into('<H', head, 30, len(extra))
    central = bytes(head) + data[at + 46:at + 46 + 9] + extra
    return data[:at] + central + _eocd(1, len(central), at)


def _eocd(count: int, cd_size: int, cd_offset: int) -> bytes:
    import struct
    return struct.pack('<IHHHHIIH', 0x06054B50, 0, 0, count, count, cd_size, cd_offset, 0)


def _zip_with_extra(T: Any, extra: bytes) -> bytes:
    """A one-entry archive whose central record carries ``extra``."""
    import struct
    data = T.raw_zip([{'name': 'model.xml', 'data': T.MINIMAL.encode('utf-8')}])
    at = data.index(b'PK\x01\x02')
    head = bytearray(data[at:at + 46])
    struct.pack_into('<H', head, 30, len(extra))
    name = data[at + 46:at + 46 + 9]
    central = bytes(head) + name + extra
    return data[:at] + central + _eocd(1, len(central), at)


def distribution_cases(T: Any) -> List[Any]:
    """The cases ``Distributions.test_distributions_per_index_and_by_default`` builds."""
    import re
    model = T.fx('MODEL_XML')

    def with_one(expr: str, fn: str) -> str:
        text, n = re.subn(r'(<entry type="parameter" index="ix-lake">\s*<value>[^<]*</value>)',
                          lambda m: f'{m.group(1)}<pdf function="{fn}"><pdf-value><![CDATA[{expr}]]>'
                                    '</pdf-value></pdf>', model, count=1)
        assert n == 1
        return text

    default = T.replace(model, '<value>0.001</value>',
                        '<value>0.001</value><pdf function="logn"><pdf-value>logn(gm=1,gsd=2, trmin=0.1)'
                        '</pdf-value></pdf>')
    return [
        T.xml('logt per index', with_one('logt(min=0.7,max=20,mode=3)', 'logt')),
        T.xml('weibull, unread', with_one('weibull(a=1,b=2)', 'weibull')),
        T.xml('by default and per index', T.replace(
            default, '<entry type="parameter" index="ix-mire">\n\t\t\t\t<value>0.02</value>',
            '<entry type="parameter" index="ix-mire"><value>0.02</value>'
            '<pdf><pdf-value>pg(values=1;2;x;3,inorder=false,pos=2)</pdf-value></pdf>'
            '<pdf><pdf-value>unif(min=1,max=2)</pdf-value></pdf>')),
        T.xml('empty and unknown', T.replace(
            with_one('', 'unif'), '<entry type="parameter" index="ix-mire">\n\t\t\t\t<value>0.02</value>',
            '<entry type="parameter" index="ix-mire"><value>0.02</value>'
            '<pdf function="nonsense"><pdf-value>nonsense(1)</pdf-value></pdf>')),
        T.xml('a distribution in an unindexed entry only', T.replace(
            model, '<value>0.001</value>',
            '<value>abc</value><pdf function="norm"><pdf-value>norm(mean=1,sd=0.1,group=g1)</pdf-value></pdf>')),
        T.xml('distributions of every kind', T.replace(
            model, '<value>0.001</value>',
            '<value>0.001</value><pdf><pdf-value> logn ( p1=0.05 , x1=1e-3, p2=0.95,x2=1e-1, pmin=0.01) </pdf-value>'
            '</pdf>')),
    ]


#: What a mutation inserts: XML's own punctuation, entities, markup, spaces
#: JavaScript knows and XML does not, non-ASCII, and number-like text.
_ALPHABET = ['<', '>', '&', ';', '"', "'", '=', '/', '!', '?', '[', ']', '-', ' ', '\u00a0', '#', 'x', '0', '9',
             'a', 'Z', '_', '.', ',', '\n', '\t', '\u2028', '\ufeff', '\u00e9', '\U0001F600', '&amp;', '&#x41;',
             '&#65;', '&nbsp;', '&#xD800;', '<![CDATA[', ']]>', '<!--', '-->', '</', '/>', '<?', '?>', 'Infinity',
             '0x1F', '1e400', '-', '+', 'e', 'TRUE', 'false', 'model', 'min', 'k-1', 'Deep soil', '\u03a3']
_NUMBERS = ['0', '-0', '1e400', '-1e400', '1e-400', '.5', '5.', '0x1F', '0o17', '0b101', '0b2', ' 12 ', '1_0',
            'Infinity', '-Infinity', 'NaN', 'inf', '', ' ', '\u00a012', '7e-5', '1.0000000000000002', '9007199254740993',
            '-792842341234.23404823434', '1000500', '2.5', '-2.5', '1e21', '1e-7', '123456789012345678901234567890']


def fuzz_xml_cases(T: Any, count: int, seed: int = 1) -> List[Any]:
    """Model texts mutated at random: a few edits each, half of them inside
    text (where values, names and entities are), half anywhere."""
    import random
    import re
    rnd = random.Random(seed)
    bases = [T.fx('MODEL_XML'), T.fx('REAL_SHAPES_XML'), T.fx('TRANSPORT_XML'), T.fx('GENERAL_VARIABLE_XML'),
             T.ENDPOINTS_XML, T.interface(), T.REACHES_XML] + [T.random_model(s) for s in range(6)]
    out = []
    for k in range(count):
        text = rnd.choice(bases)
        if rnd.random() < 0.3:
            # Every text value replaced by a number-like string, with some probability.
            p = rnd.random() * 0.5
            text = re.sub(r'>([^<]{0,40})<', lambda m: '>' + (rnd.choice(_NUMBERS) if rnd.random() < p
                                                               else m.group(1)) + '<', text)
        for _ in range(rnd.choice([1, 1, 1, 2, 3, 5, 10])):
            if rnd.random() < 0.5:
                ends = [m.end() for m in re.finditer('>', text)] or [0]
                i = rnd.choice(ends)
            else:
                i = rnd.randrange(len(text) + 1)
            op = rnd.random()
            if op < 0.45:
                text = text[:i] + rnd.choice(_ALPHABET) + text[i:]
            elif op < 0.7:
                text = text[:i] + text[min(len(text), i + rnd.randint(1, 8)):]
            else:
                text = text[:i] + rnd.choice(_ALPHABET) + text[min(len(text), i + rnd.randint(1, 4)):]
        out.append(T.xml(f'fuzz xml {k}', text))
    return out


def fuzz_zip_cases(T: Any, count: int, seed: int = 2) -> List[Any]:
    """Small archives with bytes overwritten at random, mostly in their
    headers and directory."""
    import random
    rnd = random.Random(seed)
    minimal = T.MINIMAL.encode('utf-8')
    bases = [
        T.raw_zip([{'name': '.version', 'data': b'version=6.5'}, {'name': 'model.xml', 'data': minimal},
                   {'name': 'simulation/r.dta', 'data': b'x' * 40}]),
        T.raw_zip([{'name': 'model.xml', 'data': minimal, 'method': 0}]),
        _zip64_sizes(T),
    ]
    out = []
    for k in range(count):
        data = bytearray(rnd.choice(bases))
        for _ in range(rnd.choice([1, 1, 2, 3])):
            if rnd.random() < 0.7:
                # A header field: somewhere after one of the signatures.
                starts = [i for i in range(len(data) - 3) if data[i:i + 2] == b'PK']
                i = min(len(data) - 1, rnd.choice(starts) + rnd.randrange(46)) if starts else 0
            else:
                i = rnd.randrange(len(data))
            data[i] = rnd.choice([0x00, 0xFF, 0x01, 0x7F, 0x80, 0x3F, rnd.randrange(256)])
        out.append(T.file(f'fuzz zip {k}', bytes(data)))
    return out


def synthetic_cases(more: int = 0) -> List[Tuple[str, str, Any, Optional[str], Optional[str]]]:
    import test_eco_import as T  # the package's own tests: needs node and the app's sources
    cases = (T.run_js_cases() + T.run_js_name_cases() + T.made_up_cases() + T.archive_cases()
             + distribution_cases(T) + extra_cases(T)
             + [T.xml(f'random model {seed}', T.random_model(seed)) for seed in range(200 + more)])
    if more:
        cases += fuzz_xml_cases(T, more) + fuzz_zip_cases(T, more // 4)
    labels = [c.label for c in cases]
    assert len(labels) == len(set(labels)), 'two cases share a label'
    return [(c.label, c.kind, c.payload, c.file_name, c.version) for c in cases]


def write_synthetic(out: Path, more: int = 0) -> List[Dict[str, Any]]:
    import test_eco_import as T
    records = []
    cases = synthetic_cases(more)
    # `test_a_path_is_read_with_its_name`: a file read by its path.
    path = out / 'cases' / 'Some project.eco'
    path.write_bytes(T.raw_zip([{'name': 'model.xml', 'data': T.MINIMAL.encode('utf-8')}]))
    cases.append(('a path read with its name', 'path', str(path), None, None))
    for k, (label, kind, payload, file_name, version) in enumerate(cases):
        cid = f's{k:04d}'
        rec: Dict[str, Any] = {'id': cid, 'label': label, 'source': 'synthetic', 'kind': kind,
                               'file_name': file_name, 'version': version}
        if kind == 'xml':
            (out / 'cases' / f'{cid}.payload').write_text(payload, encoding='utf-8', newline='')
        elif kind == 'file':
            (out / 'cases' / f'{cid}.payload').write_bytes(payload)
        else:
            rec['path'] = payload
        write_answer(out, cid, run_case(kind, payload, file_name, version))
        records.append(rec)
    return records


# --- the real files ----------------------------------------------------------------------------

def find_real_files() -> List[str]:
    found = set()
    for ext in ('.eco', '.eas'):
        proc = subprocess.run(['mdfind', '-name', ext], capture_output=True, text=True, timeout=600)
        for line in proc.stdout.splitlines():
            if line.lower().endswith(ext) and os.path.isfile(line):
                found.add(line)
    return sorted(found)


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _real_job(out: str, cid: str, path: str) -> Tuple[str, float, Optional[str]]:
    t = time.time()
    try:
        answer = run_case('path', path, None, None)
    except BaseException:  # noqa: BLE001
        return cid, time.time() - t, traceback.format_exc()
    write_answer(Path(out), cid, answer)
    return cid, time.time() - t, None


def write_real(out: Path, jobs: int) -> List[Dict[str, Any]]:
    paths = find_real_files()
    print(f'{len(paths)} .eco/.eas files found', flush=True)
    by_hash: Dict[str, str] = {}
    with ProcessPoolExecutor(jobs) as pool:
        hashes = list(pool.map(_sha256, paths, chunksize=4))
    for path, digest in zip(paths, hashes):
        by_hash.setdefault(digest, path)
    print(f'{len(by_hash)} distinct', flush=True)
    records = []
    todo = []
    for k, (digest, path) in enumerate(sorted(by_hash.items(), key=lambda kv: kv[1])):
        cid = f'r{k:04d}'
        st = os.stat(path)
        records.append({'id': cid, 'label': os.path.basename(path), 'source': 'real', 'kind': 'path',
                        'path': path, 'file_name': None, 'version': None, 'sha256': digest,
                        'size': st.st_size, 'mtime': st.st_mtime})
        todo.append((cid, path, st.st_size))
    # The largest first, so the long ones do not trail at the end.
    todo.sort(key=lambda t: -t[2])
    with ProcessPoolExecutor(jobs) as pool:
        futures = [pool.submit(_real_job, str(out), cid, path) for cid, path, _ in todo]
        for n, f in enumerate(as_completed(futures), 1):
            cid, seconds, failed = f.result()
            if failed:
                print(f'{cid}: the harness failed\n{failed}', flush=True)
            if n % 25 == 0 or seconds > 20:
                print(f'{n}/{len(todo)} done ({cid}: {seconds:.1f} s)', flush=True)
    return records


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('out', type=Path, help='where to write (outside the repository)')
    ap.add_argument('--synthetic', action='store_true', help='the synthetic cases')
    ap.add_argument('--real', action='store_true', help='the real files on this machine')
    ap.add_argument('--jobs', type=int, default=max(1, (os.cpu_count() or 2) - 2))
    ap.add_argument('--more', type=int, default=0, metavar='N',
                    help='with --synthetic: N more random models, N mutated model texts and N/4 damaged archives')
    args = ap.parse_args()
    if not args.synthetic and not args.real:
        args.synthetic = args.real = True
    out = args.out.resolve()
    if APP.parent.resolve() in (out, *out.parents):
        sys.exit(f'{out} is inside the repository; real project files must not be copied there')
    (out / 'cases').mkdir(parents=True, exist_ok=True)

    manifest_path = out / 'manifest.json'
    old = json.loads(manifest_path.read_text('utf-8')) if manifest_path.exists() else []
    keep = [r for r in old if not ((args.synthetic and r['source'] == 'synthetic')
                                   or (args.real and r['source'] == 'real'))]
    records = keep
    if args.synthetic:
        t = time.time()
        records = [r for r in records if r['source'] != 'synthetic'] + write_synthetic(out, args.more)
        print(f'synthetic cases written in {time.time() - t:.1f} s', flush=True)
    if args.real:
        t = time.time()
        records = [r for r in records if r['source'] != 'real'] + write_real(out, args.jobs)
        print(f'real files written in {time.time() - t:.1f} s', flush=True)
    records.sort(key=lambda r: r['id'])
    manifest_path.write_text(json.dumps(records, indent=1, ensure_ascii=False), encoding='utf-8')
    print(f'{len(records)} cases in {manifest_path}')


if __name__ == '__main__':
    main()
