#!/usr/bin/env python3
"""rtm.html against BRUM, an independent code, on twenty published cases.

The other checks in this directory measure the page against closed solutions
and conservation laws, which is the right way to find a wrong sign or a missing
factor but says nothing about whether a real reaction set comes out the same as
somebody else's code. This does that.

The cases are the HS_case1..20 set of BRUM_for_Hydrosak: spent-fuel dissolution
in one stirred cell, alpha radiolysis driving a surface mechanism, 1890 days.
Each ships its own reaction database and a results.h5 written by BRUM through
SciPy's BDF. This script converts each database to the rtm model text, solves
it with our own NDF, and puts the two answers side by side.

    python3 resources/tests/rtm/verify-brum.py [--case N] [--rtol R] [--verbose]

Needs h5py and the case set, which is not in this repository:
    ~/Downloads/Nuclear_fuel_dissolution/BRUM_for_Hydrosäk
Point --root somewhere else if it has moved.

Exit status is 0 when every case agrees.

WHAT THIS FOUND, so that it is not worked out twice:

* The stored results.h5 were written at rtol 1e-3 over 1890 days. In the window
  where UVIO2s+2 has collapsed to ~1e-17 and `red` sits at a quasi-steady state
  held by a k = 1e16 reaction, that is not converged: HS_case7, 13 and 14
  disagree there by up to four orders of magnitude. Running BRUM ITSELF at rtol
  1e-8 and 1e-11 moves it onto our answer to five or six significant figures, so
  the stored file is the unconverged one. Everything at the end of those same
  runs agrees to about 2e-3.
* AND THE FOUR THAT STILL DISAGREE AT THE END are the same story. HS_case3, 6,
  10 and 18 come out 1.0 %, 6.4 %, 1.2 % and 1.2 % from the stored answer, and
  in every one it is OUR value that holds still while the stored one moves --
  settled by running each case several ways rather than by tightening one:

      case3   O2-2  3.52851e-10    fbdf 1e-6, radau5 1e-6, radau5 1e-8 and
                                   rodas5p 1e-8: six figures, two methods,
                                   two tolerances      (stored 3.565183e-10)
      case6   O2-2  1.0393e-12     fbdf 1e-5, radau5 1e-6, rodas5p 1e-6,
                                   radau5 1e-7: four figures, three methods
                                                       (stored 1.110309e-12)
      case10  HO2-  3.484489e-15   rtol 1e-6, 1e-8 and 1e-10 all identical
                                                       (stored 3.444300e-15)
      case18  CO2   3.50546        rtol 1e-6 and 1e-8 agree to 2e-5
                                                       (stored 3.546491)

  Cases 3 and 6 are the two no MULTISTEP method here gets through at rtol 1e-8
  -- NDF, FBDF and QNDF all reach the step limit. The one-step methods do:
  Rodas5P and RadauIIA5 solve case3 at 1e-8, and case6 yields to agreement
  across three methods at 1e-6 rather than to a tighter tolerance. Where a
  tolerance cannot be tightened, several methods agreeing is the evidence to
  use, and it is what those two have.
* HS_case20's database has a typo: the stoichiometry consumes UVIO2s+ while the
  rate law reads [UVIO2s+2]. UVIO2s+ appears nowhere else, so it is driven below
  zero -- BRUM's own stored answer for it is -2.55e-8. This script turns its
  non-negativity off wherever the reference itself went negative.
* Our own NDF and BDF could not get through these cases at all -- millions of
  steps part way, then a stop -- while every ported solver managed in a few
  hundred to a few thousand. The cause was the corrector reading a correction
  that had reached the arithmetic floor of the residual as divergence; see
  `stagnationTol` in ../../js/facsimile-solver.js. With it they all run, and
  give the same fifteen agreements as the ports. --solver still defaults to
  julia_fbdf here because it is the cheapest of them on this problem, not
  because ours cannot.
"""
import argparse
import ast
import json
import re
import subprocess
import sys
from pathlib import Path

DEFAULT_ROOT = Path.home() / 'Downloads' / 'Nuclear_fuel_dissolution' / 'BRUM_for_Hydrosäk'
HERE = Path(__file__).resolve().parent
DAY = 86400.0


# ---------------------------------------------------------------------------
# Reading BRUM's three input files
# ---------------------------------------------------------------------------
def strip_comment(line):
    """Drop a trailing comment. BRUM writes them with no space: `1e-3#note`."""
    return line.split('#', 1)[0].rstrip()


def read_parameters(text):
    """`parameters; {'dose_rate' : 0.22}` -> a dict."""
    m = re.search(r'^parameters\s*;\s*(\{.*\})\s*$', text, re.M)
    return ast.literal_eval(m.group(1)) if m else {}


def read_reactions(path):
    """Each line is `stoichiometry ; rate expression ; constants`.

    skbrtm's processes.py takes `=>`, `<=` and a bare `=` and treats all three
    the same way, as one direction. One line of HS_case1 uses the bare `=`, and
    reading only `=>` silently dropped it -- which showed up as HO2- coming out
    five orders of magnitude low and nothing else being wrong at all.
    """
    out = []
    for raw in path.read_text().splitlines():
        line = strip_comment(raw).strip()
        if not line or line.startswith('REACTION') or line.startswith('STOICHIOMETRY'):
            continue
        parts = [p.strip() for p in line.split(';')]
        if len(parts) < 2:
            continue
        head = parts[0]
        if '=>' in head:
            lhs, rhs = head.split('=>', 1)
        elif '<=' in head:
            lhs, rhs = head.split('<=', 1)
        elif '=' in head:
            lhs, rhs = head.split('=', 1)
        else:
            continue
        out.append((f'{lhs.strip()} => {rhs.strip()}',
                    parts[1], parts[2] if len(parts) > 2 else ''))
    return out


def read_sourceterm(path):
    """A per-species production rate, and the dose rate it is written against."""
    text = path.read_text()
    params = read_parameters(text)
    out = []
    for raw in text.splitlines():
        line = strip_comment(raw).strip()
        if not line or line.startswith(('SOURCETERM', 'SPECIES', 'parameters')):
            continue
        parts = [p.strip() for p in line.split(';')]
        if len(parts) < 2:
            continue
        out.append((parts[0], parts[1], parts[2] if len(parts) > 2 else ''))
    return params, out


def read_solutions(path):
    """Starting concentrations, which species are held, and the parameters
    the concentrations may be written in terms of."""
    text = path.read_text()
    params = read_parameters(text)
    constant = []
    m = re.search(r'^constant\s*;\s*(.*)$', text, re.M)
    if m:
        constant = [x.strip() for x in strip_comment(m.group(1)).split(',') if x.strip()]
    initial = {}
    for raw in text.splitlines():
        line = strip_comment(raw).strip()
        if (not line or line.startswith(('SOLUTION', 'units', 'constant', 'parameters', 'SPECIES'))
                or ';' not in line):
            continue
        name, value = (x.strip() for x in line.split(';', 1))
        if not value:
            continue
        # A concentration may be an expression over the parameters.
        initial[name] = float(eval(value, {'__builtins__': {}}, dict(params)))
    return initial, constant


# ---------------------------------------------------------------------------
# Writing it out as the rtm model text
# ---------------------------------------------------------------------------
def species_in(stoich):
    """Every name on either side, coefficients dropped."""
    names = []
    for side in stoich.split('=>'):
        for term in side.split(' + '):
            term = term.strip()
            if not term:
                continue
            # `0.5U_site` and `2OH-`: a leading number is a coefficient.
            names.append(re.sub(r'^[0-9]*\.?[0-9]+\s*', '', term))
    return names


def convert(case_dir):
    db = case_dir / 'databases'
    reactions = read_reactions(db / 'reaction.in')
    dose_params, sources = read_sourceterm(db / 'sourceterm_alpha.in')
    initial, constant = read_solutions(db / 'solutions.in')

    # Everything the reactions and sources mention, in the order met, so that
    # a species that only ever appears as a product still gets declared.
    order = []
    seen = set()

    def note(nm):
        if nm and nm not in seen:
            seen.add(nm)
            order.append(nm)

    for nm in initial:
        note(nm)
    for stoich, _, _ in reactions:
        for nm in species_in(stoich):
            note(nm)
    for nm, _, _ in sources:
        note(nm)

    tend = 1890 * DAY
    m = re.search(r"t_span\s*=\s*\(\s*0\s*,\s*([0-9.eE+-]+)\s*,\s*'(\w+)'",
                  (case_dir / 'BRUM1Cell.py').read_text())
    if m:
        tend = float(m.group(1)) * (DAY if m.group(2).startswith('day') else 1.0)

    lines = ['<SETTINGS>', 'MODE = batch', f'TEND = {tend:.10g}', '', '<SPECIES>']
    for nm in order:
        bits = [nm, f'{initial.get(nm, 0.0):.10g}']
        if nm in constant:
            bits.append('fixed')
        lines.append('  '.join(bits))
    lines += ['', '<REACTIONS>']
    for stoich, expr, args in reactions:
        lines.append(f'{stoich}, {expr}' + (f', {args}' if args else ''))
    # A source term is a reaction with nothing on the left. BRUM's expression
    # is written against named parameters, which become constants of the line.
    extra = ', '.join(f'{k} = {v:.10g}' for k, v in dose_params.items())
    for nm, expr, args in sources:
        bits = [f'=> {nm}', f'r = {expr}']
        if args:
            bits.append(args)
        if extra:
            bits.append(extra)
        lines.append(', '.join(bits))
    return '\n'.join(lines) + '\n', tend


# ---------------------------------------------------------------------------
# The other code's answer
# ---------------------------------------------------------------------------
def read_reference(case_dir):
    import h5py
    with h5py.File(case_dir / 'results.h5', 'r') as f:
        g = f['results']
        names = [x.decode() for x in g['block0_items'][:]]
        t_days = g['axis1_level2'][:]
        y = g['block0_values'][:]
    return names, t_days * DAY, y


def dilution(case_dir):
    """BRUM1Cell scales its output after solving; undo it to compare."""
    src = (case_dir / 'BRUM1Cell.py').read_text()
    sav = re.search(r'surface_area_over_volume\s*=\s*([0-9.eE+-]+)', src)
    depth = re.search(r'alpha_penetration_depth\s*=\s*([0-9.eE+-]+)', src)
    if not (sav and depth):
        return 1.0
    return float(sav.group(1)) * float(depth.group(1))


# ---------------------------------------------------------------------------
def run_ours(text, tend, teval, rtol, atol, solver, non_negative=True):
    req = json.dumps({'text': text, 'tend': tend, 'teval': list(teval),
                      'rtol': rtol, 'atol': atol, 'solver': solver,
                      'nonNegative': non_negative})
    p = subprocess.run(['node', str(HERE / 'run-model.js')], input=req,
                       capture_output=True, text=True, timeout=1800)
    if p.returncode != 0:
        return {'error': (p.stderr or 'node failed')[:400]}
    return json.loads(p.stdout)


def compare(case_dir, args):
    text, tend = convert(case_dir)
    names, t_ref, y_ref = read_reference(case_dir)
    scale = dilution(case_dir)

    # Five times spread over the run, plus the end, on the reference's own grid.
    picks = sorted({int(round(f * (len(t_ref) - 1))) for f in (0.01, 0.1, 0.3, 0.6, 1.0)})
    teval = [float(t_ref[i]) for i in picks]

    # If the reference itself put a species below zero, holding ours at zero is
    # enforcing something the case does not obey. HS_case20 does exactly that:
    # its own database consumes UVIO2s+ in the stoichiometry while the rate law
    # reads [UVIO2s+2], so a species that appears nowhere else is driven down
    # from zero, and BRUM's stored answer for it is -2.55e-8. With the guard on
    # our solver fights that for ever and never leaves t = 1e-4.
    negative = [names[c] for c in range(len(names)) if y_ref[:, c].min() < -1e-25]
    non_negative = not negative
    got = run_ours(text, tend, teval, args.rtol, 1e-24, args.solver, non_negative)
    if 'error' in got:
        return {'case': case_dir.name, 'error': got['error']}

    ours = {nm.lower(): k for k, nm in enumerate(got['species'])}
    missing = [nm for nm in names if nm not in ours]
    rows = []
    for j, i in enumerate(picks):
        for c, nm in enumerate(names):
            if nm in missing:
                continue
            ref = y_ref[i, c] / scale
            mine = got['y'][j][ours[nm]]
            # Only where there is something to compare. A species is judged
            # against its own largest value over the run: in the tail of a
            # trace species both codes are reporting their own noise, and
            # HS_case20's ho3 ends at 2.6e-30 having been negative on the way.
            floor = max(abs(y_ref[:, c]).max() / scale * 1e-4, 1e-20)
            if abs(ref) < floor:
                continue
            rows.append((abs(mine - ref) / abs(ref), nm, float(t_ref[i]), ref, mine))
    rows.sort(reverse=True)
    # The final time is what these cases are for: 1890 days of dissolution.
    final = [r for r in rows if abs(r[2] - t_ref[-1]) < 1e-6 * t_ref[-1]]
    return {'case': case_dir.name, 'missing': missing, 'rows': rows, 'final': final,
            'nspecies': len(got['species']), 'stats': got.get('stats', {}),
            'negative': negative, 'text': text}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', type=Path, default=DEFAULT_ROOT)
    ap.add_argument('--case', type=int, default=None, help='just this one')
    ap.add_argument('--rtol', type=float, default=1e-6)
    # Not our own NDF: see the note at the top of the README. The ported FBDF
    # gets through every case in a few hundred steps.
    ap.add_argument('--solver', default='julia_fbdf')
    ap.add_argument('--tol', type=float, default=1e-2,
                    help='relative agreement required (BRUM ran at rtol 1e-3)')
    ap.add_argument('--verbose', action='store_true')
    ap.add_argument('--dump', type=Path, default=None, help='write the model text here')
    args = ap.parse_args()

    if not args.root.exists():
        print(f'The case set is not at {args.root}. Pass --root.')
        return 2

    cases = ([args.root / f'HS_case{args.case}'] if args.case
             else sorted((d for d in args.root.glob('HS_case*') if d.is_dir()),
                         key=lambda d: int(d.name[7:])))
    bad = []
    for d in cases:
        r = compare(d, args)
        if args.dump:
            args.dump.write_text(r.get('text', ''))
        if 'error' in r:
            print(f'{d.name:10s} FAILED: {r["error"]}')
            bad.append(d.name)
            continue
        rows = r['rows']
        worst = rows[0] if rows else (0.0, '-', 0.0, 0.0, 0.0)
        ok = worst[0] <= args.tol
        note = f'{len(r["missing"])} not in ours: {r["missing"]}' if r['missing'] else ''
        if r['negative']:
            note += f' [non-negativity off: BRUM has {", ".join(r["negative"])} below zero]'
        fin = max((x[0] for x in r['final']), default=0.0)
        print(f'{d.name:10s} {"ok  " if ok else "FAIL"} worst {worst[0]:.2e} on {worst[1]:<9s}'
              f' at t = {worst[2] / DAY:9.3f} d, {fin:.1e} at the end'
              f'   ({len(rows)} compared, {r["stats"].get("nsteps", "?")} steps) {note}')
        if not ok:
            bad.append(d.name)
        if args.verbose or not ok:
            for rel, nm, t, ref, mine in rows[:8]:
                print(f'      {nm:10s} t={t / DAY:10.4f} d  BRUM {ref:.6e}  ours {mine:.6e}'
                      f'  ({rel:.2e})')

    print(f'\n{len(cases) - len(bad)} of {len(cases)} cases agree to {args.tol:g}')
    if bad:
        print('disagreed: ' + ', '.join(bad))
    return 1 if bad else 0


sys.exit(main())
