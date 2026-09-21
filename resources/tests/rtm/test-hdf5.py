#!/usr/bin/env python3
"""Reads what rtm.html's HDF5 writer writes, with the real library.

`resources/js/kvot-hdf5-write.js` writes the format by hand rather than
pulling in h5wasm, so the question that matters is whether libhdf5 agrees that
the result is an HDF5 file. This solves three models through the page's own
worker handler, writes the file rtm.html hands the HDF5 Browser, and opens it
with h5py: the structure, the attributes, and the numbers themselves.

    python3 resources/tests/rtm/test-hdf5.py

The three are a batch (one cell), a column (cells, no rock) and a
dual-porosity column with more cells than one file should hold datasets for,
which is the case where the rock is deliberately left out.

Needs h5py. Exit status is 0 when every check passes.
"""
import json
import os
import subprocess
import sys
import tempfile

import h5py
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))

failures = []
checks = 0


def check(label, got, want=True):
    global checks
    checks += 1
    ok = got == want
    print(f'{"ok  " if ok else "FAIL"}  {label}' + ('' if ok else f': {got!r} (expected {want!r})'))
    if not ok:
        failures.append(label)


def attr(node, name):
    """An attribute as a plain Python value; h5py hands strings back as str."""
    v = node.attrs.get(name)
    if isinstance(v, bytes):
        return v.decode()
    if isinstance(v, np.ndarray) and v.size == 1:
        v = v[0]
    if isinstance(v, np.generic):
        return v.item()
    return v


def write(out, *args):
    """Run a model and write the file, as the page does. Returns its report."""
    proc = subprocess.run(
        ['node', os.path.join(HERE, 'write-h5.js'), out, *args],
        cwd=ROOT, capture_output=True, text=True)
    if proc.returncode != 0 or not os.path.exists(out):
        print(proc.stdout[-2000:])
        print(proc.stderr[-2000:])
        return None
    return json.loads(proc.stdout)


def case(label, out, *args):
    print(f'\n=== {label} ===')
    report = write(out, *args)
    if report is None:
        check(f'{label}: the run produced a file', False)
        return None, None
    print(f'{os.path.getsize(out) / 1024:.0f} kB, {report["cells"]} cells, '
          f'{report["species"]} species, {report["points"]} points')
    return report, h5py.File(out, 'r')


def common(report, f):
    """What every file says, whatever the model was."""
    n = report['points']
    check('the file says what it is', str(attr(f, 'source')).startswith('kvot ab'))
    check('and carries a description for the browser', '<table>' in str(attr(f, 'Information')))
    check('and which solver', attr(f, 'solver'), 'NDF')
    check('and how many steps it took', attr(f, 'steps') > 0)
    check('and is not a probabilistic file', str(attr(f, 'probabilistic')), 'FALSE')

    for name in ('time', 'Species', 'Settings', 'Model', 'IndexLists'):
        check(f'/{name} is there', name in f)

    t = f['/time'][:]
    check('/time is as long as the run says', len(t), n)
    check('/time starts at zero', float(t[0]), 0.0)
    check('/time increases', bool(np.all(np.diff(t) > 0)))
    check('/time is in the model\'s own unit', attr(f['/time'], 'unit'),
          report['timeUnit']['symbol'])
    check('/time ends where the run did', float(t[-1]), report['tend'])

    species = list(f['/Species'].keys())
    check('every species has a series', len(species), report['species'])
    check('each is one value per stored time',
          all(f[f'/Species/{s}'].shape == (n,) for s in species))
    check('each says it is plottable against time',
          all(str(attr(f[f'/Species/{s}'], 'time_dependent')) == 'TRUE' for s in species))
    check('and none of them is a NaN',
          all(bool(np.all(np.isfinite(f[f'/Species/{s}'][:]))) for s in species))
    check('the index list names them all', len(f['/IndexLists/Species'][:]), report['species'])
    check('the model text is kept, a line per value', f['/Model/source'].shape[0] > 10)
    check('and the settings it compiled with', 'MODE' in f['/Settings'])


def main():
    with tempfile.TemporaryDirectory() as tmp:
        # --- a batch: one cell, and no /Cells or /Grid to go with it --------
        report, f = case('batch', os.path.join(tmp, 'batch.h5'), '--example', 'ab')
        if f:
            common(report, f)
            check('a batch says so', attr(f, 'mode'), 'batch')
            check('and has no cells of its own', 'Cells' not in f)
            check('nor a grid', 'Grid' not in f)
            check('the series is the species it names',
                  list(f['/Species'].keys()), ['A', 'B', 'C'])
            # A => B => C from A = 1: the last point has almost no A left and
            # C holds nearly all of it. The numbers are the model's, not a
            # tolerance to tune -- this is the file carrying the right column.
            a, c = f['/Species/A'][:], f['/Species/C'][:]
            check('and holds the answer: A is spent', a[-1] < 1e-3)
            check('and C has almost all of it', 0.9 < c[-1] <= 1.0)
            f.close()

        # --- a column: a cell group each, and a grid that describes them ----
        report, f = case('column', os.path.join(tmp, 'column.h5'), '--example', 'doseprofile')
        if f:
            common(report, f)
            check('a column says so', attr(f, 'mode'), 'transport')
            check('every cell has a group', len(f['/Cells'].keys()), report['fracture'])
            check('and every one of them every species',
                  all(len(f[f'/Cells/{k}'].keys()) == report['species'] for k in f['/Cells']))
            check('the rock is written when there is none to leave out',
                  str(attr(f, 'matrix_written')), 'TRUE')
            check('/Grid has a row per cell', f['/Grid/x'].shape[0], report['cells'])
            check('and the cells run left to right',
                  bool(np.all(np.diff(f['/Grid/x'][:]) > 0)))
            check('/Species is the cell the page was showing',
                  bool(np.array_equal(f['/Species/P'][:], f['/Cells/cell_000/P'][:])))
            # The dose dies away over the alpha range, so the first cell ends
            # with more in it than the last. That is the model, and it is the
            # check that a cell group holds its own cell's numbers.
            check('a cell group holds that cell, not another',
                  f['/Cells/cell_000/P'][-1] > f['/Cells/cell_039/P'][-1])
            f.close()

        # --- dual porosity: more cells than a file should hold --------------
        report, f = case('dual porosity', os.path.join(tmp, 'matrix.h5'),
                         '--example', 'matrixtracer')
        if f:
            common(report, f)
            check('the model has rock behind every cell', report['stride'] > 1)
            check('and too many cells for one file', report['cells'] * report['species'] > 4000)
            check('so the rock is left out, and the file says so',
                  str(attr(f, 'matrix_written')), 'FALSE')
            check('the water is all there', len(f['/Cells'].keys()), report['fracture'])
            check('and no layer of rock is', all('_rock_' not in k for k in f['/Cells']))
            check('/Grid still describes every cell there is',
                  f['/Grid/layer'].shape[0], report['cells'])
            check('and says how deep into the rock each one sits',
                  float(f['/Grid/depth'][:].max()) > 0)
            f.close()

    print(f'\n{checks - len(failures)} of {checks} checks passed')
    if failures:
        print('failed: ' + ', '.join(failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
