"""Writes src/model/icrp107_data.cpp from the Julia package's data/icrp107.json.

    python3 tools/embed_data.py

The engine is one program with nothing to read beside it, so the table of
nuclides (ICRP Publication 107 as Kompartment carries it: half-lives in years
and each nuclide's progeny with their branching) is compiled in. Run this
again when the application's table changes; the numbers are written with
the digits that read back as the same doubles.
"""

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent.parent / 'julia' / 'data' / 'icrp107.json'
TARGET = HERE.parent / 'src' / 'model' / 'icrp107_data.cpp'

data = json.loads(SOURCE.read_text('utf-8'))
rows = data['nuclides']
lines = [
    '// Written by tools/embed_data.py from kompartment/julia/data/icrp107.json: do not edit.',
    '//',
    '// ' + data['source'],
    '',
    '#include "model/decay.hpp"',
    '',
    'namespace kompartment::icrp107_data {',
    '',
    'const Progeny PROGENY[] = {',
]
starts = []
count = 0
for name, half, progeny in rows:
    starts.append(count)
    for daughter, branching in progeny:
        lines.append(f'    {{"{daughter}", {float(branching)!r}}},')
        count += 1
lines += ['    {"", 0.0},', '};', '', 'const Row ROWS[] = {']
for (name, half, progeny), start in zip(rows, starts):
    h = '-1.0' if half is None else repr(float(half))
    lines.append(f'    {{"{name}", {h}, {start}, {len(progeny)}}},')
lines += ['};', '', f'const int ROW_COUNT = {len(rows)};', '', '}  // namespace kompartment::icrp107_data', '']
TARGET.write_text('\n'.join(lines), 'utf-8')
print(f'{TARGET}: {len(rows)} nuclides, {count} progeny')
