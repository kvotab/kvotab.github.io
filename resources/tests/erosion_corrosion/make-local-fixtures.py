#!/usr/bin/env python3
"""SKB's code test case, for test-model.js and test-ui.py, kept out of the repository.

TestCaseHydro_2_0.xlsx (SKBdoc 1895160) is SKB's, not ours to publish, so the
tests that use it read the CSV this script writes into ./local/, which
.gitignore keeps out of git. Without it those checks are skipped.

    python3 make-local-fixtures.py <folder or TestCaseHydro_2_0.xlsx>

Written:
  local/TestCaseHydro_2_0.csv  sheet "Test" in the ten columns the model
                               reads (POINT, OKFLAG, U0, QEQ, TW, F, TRAPP,
                               FPC, EFPC, FLEN), one row per position, CRLF

Needs openpyxl.
"""
import os
import sys

import openpyxl

COLUMNS = ['POINT', 'OKFLAG', 'U0', 'QEQ', 'TW', 'F', 'TRAPP', 'FPC', 'EFPC', 'FLEN']
HERE = os.path.dirname(os.path.abspath(__file__))


def number(v):
    """As the tests expect it: integers without a decimal point, floats as repr."""
    if isinstance(v, bool):
        return str(int(v))
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() and abs(v) < 1e21 else repr(v)
    return '' if v is None else str(v)


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    src = sys.argv[1]
    if os.path.isdir(src):
        src = os.path.join(src, 'TestCaseHydro_2_0.xlsx')
    rows = openpyxl.load_workbook(src, read_only=True, data_only=True)['Test'].iter_rows(values_only=True)
    header = [str(h or '').lstrip('# ').strip().upper() for h in next(rows)]
    missing = [c for c in COLUMNS if c not in header]
    if missing:
        sys.exit(f'{src}: sheet Test has no {", ".join(missing)}')
    at = [header.index(c) for c in COLUMNS]
    lines = [','.join(COLUMNS)]
    for r in rows:
        if r and r[at[0]] is not None:
            lines.append(','.join(number(r[i]) for i in at))
    os.makedirs(os.path.join(HERE, 'local'), exist_ok=True)
    out = os.path.join(HERE, 'local', 'TestCaseHydro_2_0.csv')
    with open(out, 'wb') as f:
        f.write(('\r\n'.join(lines) + '\r\n').encode())
    print(f'{out}: {len(lines) - 1} positions')


if __name__ == '__main__':
    main()
