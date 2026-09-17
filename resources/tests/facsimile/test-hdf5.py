#!/usr/bin/env python3
"""Reads what the page's HDF5 writer writes, with the real library.

`resources/js/kvot-hdf5-write.js` writes the format by hand rather than
pulling in h5wasm, so the question that matters is whether libhdf5 agrees that
the result is an HDF5 file. This solves a case through the engine, writes the
same file the page hands to the HDF5 Browser, and opens it with h5py:
structure, attributes, and the numbers themselves.

    python3 resources/tests/facsimile/test-hdf5.py            # case 13g
    python3 resources/tests/facsimile/test-hdf5.py 1 16a      # chosen cases

Needs h5py. Exit status is 0 when every check passes.
"""
import os
import subprocess
import sys
import tempfile

import h5py
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))

failures = []
checks = 0


def check(label, got, want=True):
    global checks
    checks += 1
    ok = got == want
    print(f'{"ok  " if ok else "FAIL"}  {label}' + ('' if ok else f': {got!r} (expected {want!r})'))
    if not ok:
        failures.append(label)


def close(label, got, want, tol=1e-12):
    global checks
    checks += 1
    rel = abs(got - want) / max(abs(want), 1e-300)
    ok = rel <= tol
    print(f'{"ok  " if ok else "FAIL"}  {label}: {got!r}' + ('' if ok else f' (expected {want!r})'))
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


def strings(dataset):
    return [s.decode() if isinstance(s, bytes) else str(s) for s in dataset[:]]


# Set on one case only: it is the attribute that is being checked, not the
# tolerance -- and a per-species tolerance changes the numbers, which every
# other check here is comparing against the reference.
ATOL_SPECIES = {'1': 'E 1e-26, HP 1e-26'}


def run_case(scenario):
    print(f'\n=== {scenario} ===')
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, f'{scenario}.h5')
        argv = ['node', os.path.join(HERE, 'run.js'), '--quiet', '--h5', out]
        if scenario in ATOL_SPECIES:
            argv += ['--atolspecies', ATOL_SPECIES[scenario]]
        proc = subprocess.run(argv + [scenario], cwd=ROOT, capture_output=True, text=True)
        if proc.returncode != 0 or not os.path.exists(out):
            print(proc.stdout[-2000:])
            print(proc.stderr[-2000:])
            check(f'{scenario}: the run produced a file', False)
            return
        size = os.path.getsize(out)
        print(f'{size / 1024:.0f} kB')

        with h5py.File(out, 'r') as f:
            # --- the root ------------------------------------------------------
            check('the file says what it is', attr(f, 'model'), 'SKB canister radiolysis (FACSIMILE)')
            check('and which case', attr(f, 'scenario'), scenario)
            check('and which solver', attr(f, 'solver') == 'NDF')
            # Empty unless the case asked for per-species tolerances, so the
            # file always says which species were judged against something
            # other than the one number in `atol`.
            check('and any per-species tolerances, in full',
                  str(attr(f, 'atol_species')),
                  'E=1e-26; HP=1e-26' if scenario in ATOL_SPECIES else '')
            check('and carries a description for the browser',
                  '<table>' in str(attr(f, 'Information')))
            steps = attr(f, 'steps')
            check('and how many steps it took', isinstance(steps, (int, float)) and steps > 0)

            # --- the groups ----------------------------------------------------
            for name in ('time', 'Results', 'Equations', 'Species', 'Settings', 'Constants',
                         'Model', 'IndexLists'):
                check(f'/{name} is there', name in f)

            t = f['/time'][:]
            n = len(t)
            check('/time is in hours', attr(f['/time'], 'unit'), 'h')
            check('/time increases', bool(np.all(np.diff(t) > 0)))
            check('/time starts at zero', float(t[0]), 0.0)
            check('/time is as long as the run says', n, int(attr(f, 'points')))
            check('/time is all numbers', bool(np.all(np.isfinite(t))))

            # --- the series ----------------------------------------------------
            species = list(f['/Species'].keys())
            check('every species has a series', len(species), int(attr(f, 'species')))
            check('each is as long as the clock', all(f[f'/Species/{s}'].shape == (n,) for s in species))
            check('each says it is plottable against time',
                  all(attr(f[f'/Species/{s}'], 'time_dependent') == 'TRUE' for s in species))
            check('each carries its unit',
                  all(attr(f[f'/Species/{s}'], 'unit') == 'mol/cm3' for s in species))

            results = list(f['/Results'].keys())
            check('the outputs are all there', len(results) > 20)
            check('a unit was read off the model comments',
                  attr(f['/Results/PRESSP'], 'unit'), 'atm')
            check('and the comment kept whole',
                  'pressure' in attr(f['/Results/PRESSP'], 'description'))
            check('the expression is recorded too',
                  attr(f['/Results/PRESSP'], 'expression'), 'PRESS/ATM_PA')

            # --- the numbers, against the file's own other numbers -------------
            # TIMH is t/3600 in the model, so it must be /time exactly.
            timh = f['/Results/TIMH'][:]
            check('TIMH is the clock', bool(np.array_equal(timh, t)))
            # O2MOL is O2 times the free volume, so the two must agree.
            volume_cm3 = f['/Constants/VOLUME_CM3'][()][0]
            o2 = f['/Species/O2'][:]
            o2mol = f['/Results/O2MOL'][:]
            worst = np.max(np.abs(o2mol - o2 * volume_cm3) / np.maximum(np.abs(o2mol), 1e-300))
            check('O2MOL is O2 times the volume', bool(worst < 1e-12))
            # The gas-phase water can never exceed saturation: the @H2O line.
            h2o = f['/Results/H2OGAS'][:]
            h2oeq = f['/Equations/H2OEQ'][:]
            check('the water vapour never exceeds saturation', bool(np.all(h2o <= h2oeq * (1 + 1e-12))))

            # --- the lists and what they index ---------------------------------
            for group, listname in (('Species', 'Species'), ('Results', 'Outputs'),
                                    ('Equations', 'Equations')):
                members = strings(f[f'/IndexLists/{listname}'])
                check(f'/IndexLists/{listname} lists exactly what is in /{group}',
                      sorted(members), sorted(f[f'/{group}'].keys()))
                check(f'/{group} points at its list', attr(f[f'/{group}'], 'IndexLists'), listname)

            # --- the case ------------------------------------------------------
            # Both shapes: attributes for one click, datasets so the group is
            # not an empty node in a browser that lists children. It was
            # attributes alone and read as empty.
            # A dataset each, not attributes on the group: the group is what a
            # reader clicks, and sixty name=value attributes there is a wall of
            # text for something the tree already lists. Each carries its own
            # unit and description, read from its comment in the model text.
            check('the settings are all there', len(list(f['/Settings'].keys())) >= 15)
            check('and the group itself is not a wall of attributes',
                  sorted(f['/Settings'].attrs) == ['IndexLists', 'description'])
            check('including the dose rate', f['/Settings/DOSERI'][()][0] > 0)
            check('with its unit', str(f['/Settings/DOSERI'].attrs['unit']), 'Gy/h')
            check('and its description',
                  str(f['/Settings/DOSERI'].attrs['description']), 'Initial dose rate (Gy/h)')
            check('the temperature profile is named',
                  str(f['/Settings/TPROF'][()][0].decode()).startswith('TEMP_'))
            check('and where the case is defined',
                  'TR-22-15' in str(attr(f, 'scenario_reference')))
            # The file-level Information is about the file, not the case: the
            # settings are datasets in /Settings and repeating them there was
            # two places to read the same numbers.
            info = str(attr(f, 'Information'))
            check('the Information attribute names the case and the solver',
                  ('Scenario' in info) and ('Solver' in info))
            check('and does not repeat the settings',
                  [k for k in ('Dose rate', 'Steel surface', 'Free volume',
                               'Air fraction', 'Temperature profile') if k in info], [])

            check('the constants came out with it', len(list(f['/Constants'].keys())) >= 20)
            check('and are not attributes on their group either',
                  sorted(f['/Constants'].attrs) == ['IndexLists', 'description'])
            check('including Avogadro', f['/Constants/NA'][()][0] > 6e23)
            check('with its unit', str(f['/Constants/NA'].attrs['unit']), '1/mol')
            # Every one of them, which is the point: the G-values had no comment
            # in the model text and so came out blank until they were given one.
            bare = [k for k in f['/Constants']
                    if not str(f['/Constants'][k].attrs['description']).strip()]
            check('and every constant carries a description', bare, [])
            barev = [k for k in f['/Constants']
                     if not str(f['/Constants'][k].attrs['unit']).strip()]
            check('and a unit', barev, [])

            # --- the model itself ----------------------------------------------
            source = strings(f['/Model/source'])
            check('the model text is in the file', len(source) > 500)
            check('starting where the file does', source[0].startswith('#'))
            check('and the reactions with it',
                  len(strings(f['/Model/reactions'])), int(attr(f, 'reactions')))
            check('a reaction reads as it was written',
                  any('= 2 OH' in r for r in strings(f['/Model/reactions'])))

            # --- events, where the case has them ---------------------------------
            if 'Events' in f:
                et = f['/Events/time'][:]
                check('an event fired inside the run', bool(np.all((et >= 0) & (et <= t[-1]))))
                check('and says what it changed',
                      all('=' in c for c in strings(f['/Events/change'])))


def main():
    scenarios = sys.argv[1:] or ['13g']
    for s in scenarios:
        run_case(s)
    print(f'\n{checks - len(failures)} of {checks} checks passed')
    if failures:
        print('failed: ' + ', '.join(failures))
    return 1 if failures else 0


sys.exit(main())
