#!/usr/bin/env python3
"""Turn SKB's delivered FACSIMILE result workbooks into reference CSVs.

The canister study was delivered as Excel workbooks holding the FACSIMILE
PSTREAM output for every case -- the BWR and PWR case folders for the report's
Table 3-1 cases, and Transfer1/ for the zero-argon variants that the note
"Results from Recent Calculations with the KBS-3 Canister Radiolysis Model:
Impact of Zero Argon" describes. Those are the model's own answers, and a
stronger reference for this page than the Python port, which is itself a port.

    python3 scripts/gen-facsimile-ref.py [--source DIR] [--list] [--force]

writes resources/tests/facsimile/ref/fac_<preset>.csv, one per case that could
be matched to a preset, subsampled at log-spaced times.

WHICH WORKBOOK IS WHICH CASE is worked out rather than read off the file name:
the page is asked what each preset starts from (temperature, pressure, dose
rate, water, O2 and N2 at t = 0) and each workbook's own first row has to
agree with exactly one preset. A file whose name says one case and whose
numbers say another is reported and skipped; so is a preset that two files
claim. The names are close enough to the preset ids to be tempting and not
close enough to be trusted -- "Scenario7crev1" against a preset called 7,
"scenario16prime" against one called 16p, two different scenario18 files in
two different folders.

THE SHEETS HAVE BLANK SEPARATOR COLUMNS. A header is therefore mapped to its
own column index, never to its position among the non-empty headers: filtering
the blanks out shifts every column after the first gap and reads one species'
numbers under another species' name. That failure is silent and plausible --
it was found only because O2 came out as exactly zero everywhere.
"""
import argparse
import csv
import glob
import json
import math
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, 'resources', 'tests', 'facsimile', 'ref')
DEFAULT_SOURCE = '~/RS/Software/rnt/data/sfk/gas_intact_canister'
# Later folders win a tie, so the zero-argon redelivery in Transfer1 is
# preferred over the first cut of the same cases in Transfer.
SOURCE_DIRS = [
    '2002171 - BWR Cases_TR-22-15/BWR_cases_TR2215',
    '2002172 - PWR Cases TR-22-15/PWR_cases_TR2215',
    'Transfer',
    'Transfer1',
]

# What the reference holds. The workbooks call relative humidity RH; the page
# calls it H2ORH, and the comparison is by name, so it is renamed here.
COLUMNS = ['TIMH', 'TMP', 'PRESSP', 'H2ORH', 'H2OTOTAL', 'H2OMASSL',
           'O2MOL', 'H2MOL', 'HNO3MOL', 'HNO2MOL', 'H2O2MOL', 'N2MOL',
           'NH3MOL', 'H2OMOL', 'GHNO3']
RENAME = {'RH': 'H2ORH'}
# What the first row has to agree on for a workbook to be that preset, and how
# closely. The dose rate, the temperature and the water identify the case; the
# pressure and the amounts of air confirm it.
#
# The tolerances are wider than the arithmetic needs, and deliberately: the
# delivered 1-atm PWR runs start from 0.6 % more O2 and N2 than the page's
# presets for the same cases, and 13d and 13e start at 70.5 C where the page's
# low-temperature profile starts at 70. Those differences are real and are
# reported for every matched pair rather than being tuned away -- the point of
# the reference is to show them. Anything wider than this is a different case.
MATCH = {'TMP': 1e-2, 'DOSRP': 1e-3, 'H2OTOTAL': 1e-2,
         'PRESSP': 2e-2, 'O2MOL': 2e-2, 'N2MOL': 2e-2}
SAMPLES = 80
# Ties the file names cannot break. A case delivered more than once is taken
# from the file named here; everything else falls to the ordinary rules below
# (a name that spells the preset, then the corrected "_fixed" delivery, then
# the later folder).
PREFER = {
    # This preset IS the Transfer/ run of 13g -- 3 % air and no argon -- and
    # its starting point is indistinguishable from that folder's 16b.
    '13g-fac': 'Transfer/scenario13g.xlsx',
}


def read_workbook(path):
    """The workbook as name -> list of values, blank separator columns and all."""
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    cols = {}
    for sheet in ('DATA', 'Sheet1'):
        if sheet not in wb.sheetnames:
            continue
        rows = wb[sheet].iter_rows(values_only=True)
        head = next(rows)
        idx = {}
        for i, h in enumerate(head):
            if h is None:
                continue
            name = RENAME.get(str(h).strip(), str(h).strip())
            if name and name not in idx:
                idx[name] = i
        got = {name: [] for name in idx}
        for row in rows:
            for name, i in idx.items():
                v = row[i] if i < len(row) else None
                got[name].append(v if isinstance(v, (int, float)) else None)
        clock = got.get('TIMH') or []
        last = max((k for k, v in enumerate(clock) if v is not None), default=-1)
        for name, values in got.items():
            if name not in cols:
                cols[name] = values[:last + 1]
    wb.close()
    return cols


def preset_starts():
    """What each preset starts from, asked of the page's own model code."""
    script = r"""
      const M = require('./resources/js/facsimile-model.js');
      const { FACSIMILE_DEFAULT_MODEL, FACSIMILE_PRESETS } = require('./resources/js/facsimile-default.js');
      const out = {};
      for (const p of FACSIMILE_PRESETS) {
        const m = M.compile(FACSIMILE_DEFAULT_MODEL, { settings: p.settings });
        const o = m.observe(0, m.initialState(0));
        const g = (n) => o[m.observeNames.indexOf(n)];
        out[p.id] = { TMP: g('TMP'), PRESSP: g('PRESSP'), DOSRP: g('DOSRP'),
                      H2OTOTAL: g('H2OTOTAL'), O2MOL: g('O2MOL'), N2MOL: g('N2MOL'),
                      label: p.label };
      }
      process.stdout.write(JSON.stringify(out));
    """
    got = subprocess.run([  'node', '-e', script], cwd=ROOT, capture_output=True, text=True)
    if got.returncode:
        sys.exit('could not ask the page for its presets:\n' + got.stderr)
    return json.loads(got.stdout)


def first_row(cols):
    """The t = 0 values, for matching."""
    if not cols.get('TIMH'):
        return None
    return {k: (cols[k][0] if cols.get(k) else None) for k in MATCH}


def matches(start, row):
    """Whether one workbook's first row is one preset's starting point."""
    for name, tol in MATCH.items():
        want, got = start.get(name), row.get(name)
        if want is None or got is None:
            return False
        scale = max(abs(want), abs(got))
        # An amount that is zero in both (no water, no air) agrees trivially.
        if scale < 1e-12:
            continue
        if abs(want - got) / scale > tol:
            return False
    return True


def rank(pid, folder, path):
    """How good a claim one file has to be a preset, best last."""
    name = os.path.basename(path)
    stem = name.lower().replace('scenario', '').replace('_fixed', '').replace('.xlsx', '')
    stem = stem.replace('-rev1', '').replace('rev1', '').replace('-mod', '').replace('prime', 'p')
    wanted = PREFER.get(pid)
    return (
        1 if wanted and wanted in path else 0,      # named outright
        1 if stem == pid.lower() else 0,            # the file name spells the preset
        1 if '_fixed' in name else 0,               # the corrected delivery
        SOURCE_DIRS.index(folder),                  # the later folder
    )


def sample(cols, n):
    """Indices of about n rows, log-spaced in time, both ends kept."""
    t = cols['TIMH']
    keep = {0, len(t) - 1}
    first = next((i for i, v in enumerate(t) if v and v > 0), None)
    if first is not None:
        a, b = math.log10(t[first]), math.log10(t[-1])
        j = first
        for k in range(n):
            want = 10 ** (a + (b - a) * k / (n - 1))
            while j < len(t) - 1 and t[j] < want:
                j += 1
            keep.add(j)
    return sorted(keep)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--source', default=DEFAULT_SOURCE, help='the delivery folder')
    ap.add_argument('--list', action='store_true', help='report the matching and write nothing')
    ap.add_argument('--samples', type=int, default=SAMPLES, help=f'rows per file (default {SAMPLES})')
    ap.add_argument('--force', action='store_true', help='overwrite a reference that is already there')
    args = ap.parse_args()

    if not os.path.isdir(args.source):
        sys.exit(f'no such folder: {args.source}\n'
                 'These are the study\'s own deliveries and are not in this repository; '
                 'point --source at them.')

    starts = preset_starts()
    files = []
    for d in SOURCE_DIRS:
        for p in sorted(glob.glob(os.path.join(args.source, d, '*.xlsx'))):
            if not os.path.basename(p).startswith('~$'):
                files.append((d, p))
    if not files:
        sys.exit(f'no workbooks under {args.source}')
    print(f'{len(files)} workbooks, {len(starts)} presets\n')

    candidates = {}      # preset id -> [(folder, path, columns), ...]
    unmatched = []
    for d, path in files:
        name = os.path.basename(path)
        cols = read_workbook(path)
        row = first_row(cols)
        if row is None:
            unmatched.append((name, 'no TIMH column'))
            continue
        hits = [pid for pid, s in starts.items() if matches(s, row)]
        if not hits:
            unmatched.append((name, 'matches no preset: ' + ', '.join(
                f'{k}={row[k]:.5g}' for k in MATCH if row.get(k) is not None)))
            continue
        if len(hits) > 1:
            # Several presets can share a starting point and differ only in
            # what happens later (corrosion on or off, an RH limit). The file
            # name breaks the tie when it names one of them, and nothing else
            # can, so an ambiguous file that the name does not resolve is left
            # out rather than guessed at.
            stem = name.lower().replace('scenario', '').replace('_fixed', '').replace('.xlsx', '')
            stem = stem.replace('-rev1', '').replace('rev1', '').replace('-mod', '').replace('prime', 'p')
            named = [pid for pid in hits if pid.lower() == stem]
            if len(named) != 1:
                unmatched.append((name, f'matches {len(hits)} presets ({", ".join(hits)}) '
                                        f'and the name "{stem}" does not pick one'))
                continue
            hits = named
        pid = hits[0]
        candidates.setdefault(pid, []).append((d, path, cols))

    # One file per preset, chosen rather than whichever was read last.
    chosen = {}
    for pid, options in candidates.items():
        if len(options) > 1:
            options = sorted(options, key=lambda o: rank(pid, o[0], o[1]), reverse=True)
            print(f'  {pid:8} delivered {len(options)} times: '
                  + ', '.join(os.path.basename(o[1]) for o in options)
                  + f' -- taking {os.path.basename(options[0][1])}')
        chosen[pid] = options[0]

    print(f'\nmatched {len(chosen)} of {len(files)} workbooks to presets\n')
    for name, why in unmatched:
        print(f'  unmatched  {name}: {why}')
    if unmatched:
        print()

    # How far apart the two starting points are, for every pair that matched.
    # A case is identified by its starting point, so a pair that only just
    # matched is the most interesting thing this script can report.
    print(f'{"preset":8} {"workbook":34} {"rows":>6} {"to (y)":>7}  worst starting difference')
    for pid in sorted(chosen):
        d, path, cols = chosen[pid]
        row = first_row(cols)
        worst, field = 0.0, ''
        for name in MATCH:
            want, got = starts[pid].get(name), row.get(name)
            if want is None or got is None:
                continue
            scale = max(abs(want), abs(got))
            if scale < 1e-12:
                continue
            rel = abs(want - got) / scale
            if rel > worst:
                worst, field = rel, name
        note = f'{field} {worst:.2%}' if worst > 1e-4 else 'none above 0.01%'
        print(f'  {pid:8} {os.path.basename(path):34} {len(cols["TIMH"]):6d} '
              f'{cols["TIMH"][-1] / 8766:7.1f}  {note}')
    print()
    if args.list:
        return 0

    os.makedirs(OUT_DIR, exist_ok=True)
    written = 0
    for pid in sorted(chosen):
        d, path, cols = chosen[pid]
        out = os.path.join(OUT_DIR, f'fac_{pid}.csv')
        if os.path.exists(out) and not args.force:
            print(f'  {pid:8} already there, left alone (--force to rewrite)')
            continue
        have = [c for c in COLUMNS if c in cols]
        rows = sample(cols, args.samples)
        with open(out, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(have)
            for i in rows:
                w.writerow(['' if cols[c][i] is None else repr(cols[c][i]) for c in have])
        missing = [c for c in COLUMNS if c not in cols]
        print(f'  {pid:8} {len(rows):3d} rows from {os.path.basename(path)}'
              + (f'   (no {", ".join(missing)})' if missing else ''))
        written += 1
    print(f'\nwrote {written} reference files to {os.path.relpath(OUT_DIR, ROOT)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
