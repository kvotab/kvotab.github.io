#!/usr/bin/env python3
"""Regenerate resources/js/rtm-default.js.

The built-in model of rtm.html is the water-radiolysis and uranium-dissolution
set from the skbrtm examples (examples/transport/PA_BRUM_test/databases),
converted to the model text rtm.html reads. The conversion is mechanical:

    skbrtm                                  rtm.html
    STOICHIOMETRY;EXPRESSION;ARGUMENTS      <stoichiometry>, <rate>, <parameters>
    a + b = c                               a + b => c
    r = k*[a]*[b]                           r = k*[a]*[b]          (unchanged)
    SPECIES;CONCENTRATION;ARGUMENTS         <name> <value> [fixed]
    constant                                fixed

so the two are the same model written two ways, and a difference between them
is a bug in one of them rather than a translation.

    python3 scripts/gen-rtm-default.py [--source DIR]

The stamp in rtm.html is bumped as part of writing the file, for the reason
given in gen-facsimile-default.py.
"""
import argparse
import datetime
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'resources', 'js', 'rtm-default.js')
STAMPED = [os.path.join(ROOT, 'rtm.html')]
SOURCE = os.path.expanduser('~/Downloads/skbrtm/examples/transport/PA_BRUM_test/databases')

# Species bound to the fuel surface: they take part in the chemistry but do not
# move, so they get no diffusion coefficient however the run is set up.
IMMOBILE = {
    'U_site', 'E_site', 'Ud_site', 'UIVO2s', 'UVO2s+', 'UVIO2s+2', 'alpha', 'Tr',
    'ox', 'red',
}
DIFFUSIVITY = 1e-9          # m2/s, the value the source data uses throughout

# The alpha dose rate at the fuel surface, Gy/s, from Doserates.in. Held
# uniform across the film here: the real profile falls away over the range of
# an alpha particle, about 30 um, and a dose rate that varies from cell to cell
# is not something the model text can say yet.
DOSE_RATE = 0.64


def read_reactions(path):
    out = []
    for raw in open(path, encoding='utf-8'):
        line = raw.split('#')[0].strip()
        if not line or line.upper() in ('GLOBAL', 'LOCAL'):
            continue
        if line.upper().startswith('STOICHIOMETRY'):
            continue
        parts = [p.strip() for p in line.split(';') if p.strip()]
        if len(parts) < 2:
            continue
        stoich = parts[0]
        # skbrtm writes an irreversible reaction with a bare "="; rtm.html
        # wants the arrow, so that "=" stays free for naming a parameter.
        if '=>' not in stoich and '<=' not in stoich:
            stoich = stoich.replace(' = ', ' => ')
        out.append(', '.join([stoich] + parts[1:]))
    return out


def read_g_values(path):
    """G-values in mol/J, per radiation type. Only alpha is non-zero here."""
    out = []
    for raw in open(path, encoding='utf-8'):
        line = raw.split('#')[0].strip()
        if not line or line.lower().startswith('specie'):
            continue
        parts = [p.strip() for p in line.split('\t') if p.strip()]
        if len(parts) < 2:
            continue
        alpha = float(parts[1])
        if alpha:
            out.append((parts[0], alpha))
    return out


def read_species(path):
    out = []
    for raw in open(path, encoding='utf-8'):
        line = raw.split('#')[0].strip()
        if not line or line.upper() == 'LOCAL' or line.upper().startswith('SPECIES'):
            continue
        parts = [p.strip() for p in line.split(';')]
        if len(parts) < 2 or parts[0] == '__default':
            continue
        out.append((parts[0], parts[1], len(parts) > 2 and parts[2].lower() == 'constant'))
    return out


def mentioned(reactions):
    """Every species a reaction names, in the order first seen."""
    seen = []
    for r in reactions:
        equation = r.split(',')[0]
        for side in re.split(r'=>|<=>|=', equation):
            for term in side.split(' + '):
                term = term.strip()
                if not term:
                    continue
                m = re.match(r'^(?:\d+(?:\.\d+)?)?\s*(.+)$', term)
                name = m.group(1).strip()
                if name not in seen:
                    seen.append(name)
        for m in re.finditer(r'\[([^\]]+)\]', r):
            name = m.group(1).strip()
            if name not in seen:
                seen.append(name)
    return seen


def build(source):
    reactions = read_reactions(os.path.join(source, 'reaction.in'))
    # Radiolysis, as a reaction with nothing on the left: a source of G x dose
    # rate. G is mol/J and the dose rate J/kg/s, so with a litre of water
    # weighing a kilogram the product is mol/L/s -- the unit the rest of the
    # model is written in -- and no conversion factor is needed.
    sources = [
        f'=> {name}, k = G*DOSE, G = {g:g}, DOSE = {DOSE_RATE:g}'
        for name, g in read_g_values(os.path.join(source, 'newg_values.in'))
    ]
    declared = read_species(os.path.join(source, 'initialstate.in'))
    given = {n: (c, f) for n, c, f in declared}
    names = list(given) + [n for n in mentioned(reactions) if n not in given]

    width = max(len(n) for n in names) + 2
    lines = []
    for name in names:
        conc, fixed = given.get(name, ('0.0', False))
        bits = [f'{name:<{width}}{conc:<10}']
        if fixed:
            bits.append('fixed')
        elif name not in IMMOBILE:
            bits.append(f'D={DIFFUSIVITY:g}')
        # The left-hand face is the water the fuel sits in: the species with a
        # stated concentration are held there, the rest are free.
        if not fixed and name in given and name not in IMMOBILE:
            bits.append(f'left={conc}')
        lines.append('  '.join(bits).rstrip())

    text = f"""# ============================================================================
#  WATER RADIOLYSIS AND URANIUM DISSOLUTION AT A SPENT-FUEL SURFACE
#
#  {len(reactions)} reactions over {len(names)} species, from the skbrtm example set
#  (examples/transport/PA_BRUM_test). The left-hand boundary is the fuel
#  surface; the domain is the thin film of water in front of it.
#
#  Set MODE = batch to ignore the film and stir everything together, which is
#  much quicker and is the right first look at a reaction set.
# ============================================================================

<SETTINGS>
MODE      = transport      # batch | transport
CELLS     = 20             # cells across the film
LENGTH    = 2.0E-4         # m, the thickness of the film
GRID      = linear         # linear | log (log packs cells against the surface)
DIFFUSION = 1
ADVECTION = 0
VELOCITY  = 0              # m/s, positive is left to right
LEFT      = dirichlet      # the bulk water holds its composition
RIGHT     = neumann        # nothing crosses the far face
TEND      = 1.0E5          # s

<SPECIES>
# name        initial     fixed | D = m2/s | left = , right = boundary values
{chr(10).join(lines)}

<REACTIONS>
# stoichiometry, then the rate: k = ... for mass action, or r = ... for a law
# of your own with its parameters after it. A concentration is written [name].

# Radiolysis: nothing on the left is a source, here G (mol/J) times the alpha
# dose rate (Gy/s). Set DOSE = 0 on these lines to switch the radiation off.
{chr(10).join(sources)}

{chr(10).join(reactions)}

<INITIAL>
# species  cells  value     -- overrides the concentration above, per cell
"""
    return text, len(reactions) + len(sources), len(names)


def bump_stamps():
    today = datetime.date.today().strftime('%Y%m%d')
    pattern = re.compile(r'(rtm-default\.js\?v=)([0-9]{8})([a-z]*)')
    changed = []
    for path in STAMPED:
        if not os.path.exists(path):
            continue
        text = open(path, encoding='utf-8').read()

        def nxt(m):
            date, letter = m.group(2), m.group(3)
            if date != today:
                return m.group(1) + today
            if not letter:
                return m.group(1) + today + 'a'
            return m.group(1) + today + (letter[:-1] + chr(ord(letter[-1]) + 1)
                                         if letter[-1] < 'z' else letter + 'a')
        new = pattern.sub(nxt, text)
        if new != text:
            open(path, 'w', encoding='utf-8').write(new)
            changed.append((os.path.relpath(path, ROOT), pattern.search(new).group(0)))
    return changed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--source', default=SOURCE)
    args = ap.parse_args()
    text, nrx, nsp = build(args.source)
    js = '''/* ==========================================================================
   RTM.HTML: THE BUILT-IN MODEL

   Generated by scripts/gen-rtm-default.py from the skbrtm example databases;
   edit those, or the script, rather than this file.
   ========================================================================== */
const RTM_DEFAULT_MODEL = `%s`;

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { RTM_DEFAULT_MODEL };
}
''' % text.replace('\\', '\\\\').replace('`', '\\`').replace('${', '\\${')
    open(OUT, 'w', encoding='utf-8').write(js)
    print(f'wrote {OUT}: {nrx} reactions, {nsp} species')
    for where, stamp in bump_stamps():
        print(f'  {where}: {stamp}')


if __name__ == '__main__':
    main()
