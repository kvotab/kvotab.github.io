#!/usr/bin/env python3
"""Regenerate resources/js/facsimile-default.js.

The built-in model text of facsimile.html lives in
resources/data/facsimile-canister.fac; this script embeds it in a JavaScript
file together with the scenario presets (the cases of test_skbcanister.py in
the Python port of the FACSIMILE model), so that the page needs no fetch() and
works from file:// as well.

    python3 scripts/gen-facsimile-default.py

Edit the .fac text, not the generated file.
"""
import datetime
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAC = os.path.join(ROOT, 'resources', 'data', 'facsimile-canister.fac')
OUT = os.path.join(ROOT, 'resources', 'js', 'facsimile-default.js')
# Every page that loads the generated file. Its ?v= stamp is bumped here, as
# part of writing the file: a stamp that did not move means the browser keeps
# serving the copy it already has, and an edit to the .fac appears to have done
# nothing at all. That is the one failure of this script a reader cannot see.
STAMPED = [os.path.join(ROOT, 'facsimile.html')]


def bump_stamps():
    """Point every ?v=facsimile-default.js at a stamp that has moved.

    The stamp is the date plus a letter, which is this repo's convention. The
    letter advances when the date has not, so several regenerations in one day
    each get their own URL.
    """
    today = datetime.date.today().strftime('%Y%m%d')
    pattern = re.compile(r'(facsimile-default\.js\?v=)([0-9]{8})([a-z]*)')
    changed = []
    for path in STAMPED:
        if not os.path.exists(path):
            continue
        text = open(path, encoding='utf-8').read()
        def nxt(m):
            date, letter = m.group(2), m.group(3)
            if date != today:
                return m.group(1) + today
            # Same day: a -> b -> ... -> z -> za, which keeps sorting sanely.
            if not letter:
                return m.group(1) + today + 'a'
            return m.group(1) + today + (letter[:-1] + chr(ord(letter[-1]) + 1)
                                         if letter[-1] < 'z' else letter + 'a')
        new = pattern.sub(nxt, text)
        if new != text:
            open(path, 'w', encoding='utf-8').write(new)
            changed.append((os.path.relpath(path, ROOT), pattern.search(new).group(0)))
    return changed

# id, fuel, dose (Gy/h), steel area (m2), volume (m3), pressure (atm), air fraction,
# initial water (g), released water (g), release rate (g/day), corrosion mode
# ('normal' | 'rh' = only above 60 % RH | 'rh-reduced' | 'off'), oxic and anoxic
# corrosion rates (mm/y), ramp order, rtol. From test_skbcanister.py.
CASES = [
    ('1',   'BWR', 39,  68.78, 1.25, 1.0,  0.10, 600, 600, 0,   'normal', 0.4, 3e-3, 1e-8,  1e-4),
    ('2a',  'BWR', 166, 68.78, 1.25, 1.0,  0.10, 600, 600, 0,   'normal', 0.4, 3e-3, 1e-8,  1e-4),
    ('2b',  'BWR', 166, 54.1,  1.02, 1.0,  0.10, 600, 600, 0,   'normal', 0.4, 3e-3, 1e-8,  1e-4),
    ('2c',  'BWR', 166, 54.1,  1.02, 1.0,  0.10, 600, 600, 0,   'rh-reduced', 0.4, 3e-3, 1e-8, 1e-4),
    ('3',   'BWR', 166, 68.78, 1.25, 1.0,  0.05, 600, 600, 0,   'normal', 0.4, 3e-3, 1e-8,  1e-4),
    ('4',   'BWR', 166, 68.78, 1.25, 1.0,  0.02, 600, 600, 0,   'normal', 0.4, 3e-3, 1e-8,  1e-4),
    ('5',   'BWR', 166, 68.78, 1.25, 1.0,  0.01, 600, 600, 0,   'normal', 0.4, 3e-3, 1e-8,  1e-4),
    ('6',   'BWR', 166, 68.78, 1.25, 1.0,  0.10, 30,  30,  0,   'normal', 0.4, 3e-3, 1e-8,  1e-5),
    ('7',   'BWR', 166, 68.78, 1.25, 1.0,  0.05, 30,  30,  0,   'normal', 0.4, 3e-3, 1e-8,  1e-3),
    ('8',   'BWR', 166, 68.78, 1.25, 1.0,  0.02, 30,  30,  0,   'normal', 0.4, 3e-3, 1e-8,  1e-4),
    ('9',   'BWR', 166, 68.78, 1.25, 1.0,  0.01, 30,  30,  0,   'normal', 0.4, 3e-3, 1e-8,  1e-4),
    ('10',  'BWR', 166, 68.78, 1.25, 1.0,  0.05, 1,   600, 1.8, 'normal', 0.4, 3e-3, 1e-8,  1e-4),
    ('10a', 'BWR', 166, 68.78, 1.25, 1.0,  0.05, 1,   600, 1.8, 'rh',     0.4, 3e-3, 1e-8,  1e-5),
    ('11',  'BWR', 166, 68.78, 1.25, 1.0,  0.05, 1,   30,  1.8, 'normal', 0.4, 3e-3, 1e-8,  1e-3),
    ('11a', 'BWR', 166, 68.78, 1.25, 1.0,  0.05, 1,   30,  1.8, 'rh',     0.4, 3e-3, 1e-8,  1e-3),
    ('11b', 'BWR', 166, 54.1,  1.02, 0.03, 1.0,  1,   30,  1.8, 'rh',     0.4, 3e-3, 1e-8,  1e-3),
    ('12',  'PWR', 57,  42.52, 1.44, 1.0,  0.10, 600, 600, 0,   'normal', 0.4, 3e-3, 1e-8,  1e-4),
    ('13a', 'PWR', 238, 42.52, 1.44, 1.0,  0.10, 600, 600, 0,   'normal', 0.4, 3e-3, 1e-12, 1e-4),
    ('13b', 'PWR', 238, 27.8,  1.2,  1.0,  0.10, 600, 600, 0,   'normal', 0.4, 3e-3, 1e-12, 1e-4),
    ('13c', 'PWR', 238, 27.8,  1.2,  1.0,  0.10, 600, 600, 0,   'normal', 0.04, 3e-4, 1e-12, 1e-4),
    ('13d', 'PWRLOW', 238, 42.52, 1.44, 1.0, 0.10, 600, 600, 0, 'normal', 0.4, 3e-3, 1e-12, 1e-4),
    ('13e', 'PWRLOW', 238, 27.8,  1.2,  1.0, 0.10, 600, 600, 0, 'normal', 0.4, 3e-3, 1e-12, 1e-4),
    ('13f', 'PWR', 238, 42.52, 1.44, 1.0,  0.10, 600, 600, 0,   'rh',     0.4, 3e-3, 1e-8,  1e-5),
    ('13g', 'PWR', 238, 27.8,  1.2,  0.03, 1.0,  600, 600, 0,   'rh',     0.4, 3e-3, 1e-8,  1e-5),
    ('14',  'PWR', 238, 42.52, 1.44, 1.0,  0.05, 600, 600, 0,   'normal', 0.4, 3e-3, 1e-12, 1e-4),
    ('15',  'PWR', 238, 42.52, 1.44, 1.0,  0.02, 600, 600, 0,   'normal', 0.4, 3e-3, 1e-12, 1e-4),
    ('16',  'PWR', 238, 42.52, 1.44, 1.0,  0.01, 600, 600, 0,   'normal', 0.4, 3e-3, 1e-12, 1e-4),
    ('16p', 'PWR', 238, 27.8,  1.2,  1.0,  0.03, 600, 600, 0,   'normal', 0.4, 3e-3, 1e-12, 1e-5),
    ('16a', 'PWR', 238, 27.8,  1.2,  0.01, 1.0,  600, 600, 0,   'normal', 0.4, 3e-3, 1e-12, 1e-5),
    ('16b', 'PWR', 238, 27.8,  1.2,  0.03, 1.0,  600, 600, 0,   'normal', 0.4, 3e-3, 1e-12, 1e-5),
    ('16c', 'PWR', 238, 27.8,  1.2,  1.0,  0.03, 600, 600, 0,   'off',    0.4, 3e-3, 1e-12, 1e-3),
    ('16d', 'PWR', 238, 27.8,  1.2,  0.03, 1.0,  600, 600, 0,   'off',    0.4, 3e-3, 1e-12, 1e-3),
    ('17',  'PWR', 238, 42.52, 1.44, 1.0,  0.10, 30,  30,  0,   'normal', 0.4, 3e-3, 1e-8,  1e-4),
    ('18',  'PWR', 238, 42.52, 1.44, 1.0,  0.05, 30,  30,  0,   'normal', 0.4, 3e-3, 1e-8,  1e-4),
    ('19',  'PWR', 238, 42.52, 1.44, 1.0,  0.02, 30,  30,  0,   'normal', 0.4, 3e-3, 1e-8,  1e-4),
    ('20',  'PWR', 238, 42.52, 1.44, 1.0,  0.01, 30,  30,  0,   'normal', 0.4, 3e-3, 1e-8,  1e-4),
    ('21',  'PWR', 238, 42.52, 1.44, 1.0,  0.05, 1,   600, 1.8, 'normal', 0.4, 3e-3, 1e-8,  1e-4),
    ('22',  'PWR', 238, 42.52, 1.44, 1.0,  0.05, 1,   30,  1.8, 'normal', 0.4, 3e-3, 1e-8,  1e-4),
]
TABLES = {'PWR': 'TEMP_PWR', 'BWR': 'TEMP_BWR', 'PWRLOW': 'TEMP_PWRLOW'}


# Where each case comes from. Cases 1-22 are SKB TR-22-15 Table 3-1 (p 17);
# the section is where that report presents the case's results, read off its
# own table of contents. The remaining presets are NOT in that table -- they
# are variants supplied as FACSIMILE model files in Model Transfer/ -- and say
# so rather than borrowing a citation they do not have.
SECTION = {
    '1': '3.2.1, p 18 (Cases 1 and 2a - sensitivity to initial dose rate)',
    '2a': '3.2.1, p 18 (Cases 1 and 2a - sensitivity to initial dose rate)',
    '2b': '3.2.2, p 22 (sensitivity to steel area and system volume)',
    '2c': '3.2.3, p 24 (sensitivity to system corrosion rate)',
    '3': '3.2.5, p 27 (Cases 2a, 3, 4, 5 - impact of initial air content)',
    '4': '3.2.5, p 27 (Cases 2a, 3, 4, 5 - impact of initial air content)',
    '5': '3.2.5, p 27 (Cases 2a, 3, 4, 5 - impact of initial air content)',
    '6': '3.2.4, p 26 (impact of reducing initial water content)',
    '7': '3.2.5, p 27 (Cases 6, 7, 8, 9 - impact of initial air content)',
    '8': '3.2.5, p 27 (Cases 6, 7, 8, 9 - impact of initial air content)',
    '9': '3.2.5, p 27 (Cases 6, 7, 8, 9 - impact of initial air content)',
    '10': '3.2.6, p 28 (Cases 10 and 11 - slow addition of water)',
    '10a': '3.4.1, p 43 (BWR Cases 10a and 11a - zero corrosion below 60 % RH)',
    '11': '3.2.6, p 28 (Cases 10 and 11 - slow addition of water)',
    '11a': '3.4.1, p 43 (BWR Cases 10a and 11a - zero corrosion below 60 % RH)',
    '12': '3.3.1, p 31 (Cases 12 and 13a - sensitivity to initial dose rate)',
    '13a': '3.3.1, p 31 (Cases 12 and 13a - sensitivity to initial dose rate)',
    '13b': '3.3.2, p 34 (sensitivity to initial steel area and system volume)',
    '13c': '3.3.3, p 35 (sensitivity to system corrosion rate)',
    '13d': '3.3.4, p 36 (Cases 13d and 13e - sensitivity to initial temperature)',
    '13e': '3.3.4, p 36 (Cases 13d and 13e - sensitivity to initial temperature)',
    '13f': '3.4.2, p 45 (PWR Case 13f - zero corrosion below 60 % RH)',
    '14': '3.3.5, p 38 (Cases 13a, 14, 15, 16 - impact of initial air content)',
    '15': '3.3.5, p 38 (Cases 13a, 14, 15, 16 - impact of initial air content)',
    '16': '3.3.5, p 38 (Cases 13a, 14, 15, 16 - impact of initial air content)',
    '17': '3.3.5, p 38 (Cases 17, 18, 19, 20 - impact of initial air content)',
    '18': '3.3.5, p 38 (Cases 17, 18, 19, 20 - impact of initial air content)',
    '19': '3.3.5, p 38 (Cases 17, 18, 19, 20 - impact of initial air content)',
    '20': '3.3.5, p 38 (Cases 17, 18, 19, 20 - impact of initial air content)',
    '21': '3.3.6, p 39 (Cases 21 and 22 - slow addition of water)',
    '22': '3.3.6, p 39 (Cases 21 and 22 - slow addition of water)',
}

# The variants, and what each changes from the Table 3-1 case it is built on.
# Described from the settings, which is all the .fac files say about themselves.
VARIANT = {
    '11b': ('skbcanister11b.fac', 'Case 11 with the area and volume of Case 2b '
            '(54.1 m2, 1.02 m3) and the gas at 0.03 atm of air, corrosion only above 60 % RH'),
    '13g': ('skbcanister13g.fac', 'Case 13b with the gas at 0.03 atm of air, '
            'corrosion only above 60 % RH'),
    '16p': ('skbcanister16p.fac', 'Case 16 with the area and volume of Case 13b '
            '(27.8 m2, 1.2 m3) and 3 % air at 1 atm'),
    '16a': ('skbcanister16a.fac', 'Case 16 with the area and volume of Case 13b '
            'and the gas at 0.01 atm of air'),
    '16b': ('skbcanister16b.fac', 'Case 16 with the area and volume of Case 13b '
            'and the gas at 0.03 atm of air'),
    '16c': ('skbcanister16c.fac', 'Case 16 with the area and volume of Case 13b, '
            '3 % air at 1 atm, and no corrosion'),
    '16d': ('skbcanister16d.fac', 'Case 16 with the area and volume of Case 13b, '
            'the gas at 0.03 atm of air, and no corrosion'),
}


def reference(sid):
    """Where this case is defined, in one line."""
    if sid in SECTION:
        return f'SKB TR-22-15, Table 3-1 (p 17), Case {sid}. Results: section {SECTION[sid]}.'
    if sid in VARIANT:
        f, what = VARIANT[sid]
        return (f'Not in SKB TR-22-15 Table 3-1. From the FACSIMILE model file {f}: '
                f'{what}.')
    return ''


def preset(case):
    (sid, fuel, dose, area, vol, press, air, water0, water_final, rate, mode, oxic, anoxic, ramp, rtol) = case
    corr_on = 0 if mode == 'off' else 1
    rhlim = 0.6 if mode in ('rh', 'rh-reduced') else 0
    aer_rh = 0.04 if mode == 'rh-reduced' else 0
    an_rh = 3e-4 if mode == 'rh-reduced' else 0
    water = f'{water0:g} g water'
    if rate > 0:
        water = f'{water0:g} g water + {rate:g} g/day to {water_final:g} g'
    corr = {'off': 'no corrosion', 'rh': 'corrosion only above 60% RH',
            'rh-reduced': 'corrosion only above 60% RH, reduced below the RH limit', 'normal': 'corrosion'}[mode]
    if oxic != 0.4:
        corr += f' ({oxic:g} mm/y oxic)'
    label = f'{sid}: {fuel}, {dose:g} Gy/h, {area:g} m2, {vol:g} m3, {press:g} atm, {air * 100:g}% air, {water}, {corr}'
    return {
        'id': sid, 'label': label, 'reference': reference(sid),
        'settings': {
            'DOSERI': dose, 'STEELAREA': area, 'VOLUME': vol, 'PRESSI': press, 'PCAIR': air, 'PCAR': '1 - PCAIR',
            'H2OLQDI': water0, 'H2OFINAL': water_final, 'H2OINPUTR': rate, 'TPROF': TABLES[fuel],
            'CORR_ON': corr_on, 'RHLIM': rhlim, 'AERCORRAT': oxic, 'ANCORRAT': anoxic,
            # The published cases are the substitution model; choosing a
            # scenario therefore puts the water model back to it.
            'H2OPAIR': 0,
            'AERCORRATRH': aer_rh, 'ANCORRATRH': an_rh, 'RAMP_ORDER': ramp, 'TEND': 500,
        },
        'solver': {'rtol': rtol},
    }


def main():
    fac = open(FAC, encoding='utf-8').read()
    assert '`' not in fac and '${' not in fac, 'the model text must not contain ` or ${'
    presets = [preset(c) for c in CASES]
    base13g = next(p for p in presets if p['id'] == '13g')
    # The FACSIMILE run kept in Transfer/: 3 % air and no argon.
    presets.append({
        'id': '13g-fac',
        'label': '13g (FACSIMILE run in Transfer/): PWR, 238 Gy/h, 27.8 m2, 1.2 m3, 0.03 atm, 3% air, no argon, 600 g water, corrosion only above 60% RH',
        'reference': ('Not in SKB TR-22-15 Table 3-1. Case 13g as actually run in FACSIMILE '
                      '(Transfer/out*COR13g.prn): 3 % air and no argon, rather than the 100 % air '
                      'of skbcanister13g.fac. This is the preset the .prn reference data belong to.'),
        'settings': {**base13g['settings'], 'PCAIR': 0.03, 'PCAR': 0},
        'solver': {'rtol': 1e-5},
    })
    js = '''/* ==========================================================================
   FACSIMILE.HTML: THE DEFAULT MODEL AND THE SCENARIO PRESETS

   The model text is the radiolysis/corrosion model of an intact KBS-3 canister
   (SKB TR-22-15) as ported from FACSIMILE to Python in skbcanister.py; the
   reaction list was converted from that file mechanically. The presets are
   the scenarios of test_skbcanister.py.

   Generated by scripts/gen-facsimile-default.py; edit the .fac text there.
   ========================================================================== */
const FACSIMILE_DEFAULT_MODEL = `%s`;

const FACSIMILE_PRESETS = %s;

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { FACSIMILE_DEFAULT_MODEL, FACSIMILE_PRESETS };
}
''' % (fac, json.dumps(presets, indent=2))
    open(OUT, 'w', encoding='utf-8').write(js)
    print(f'wrote {OUT}: {len(fac.splitlines())} lines of model text, {len(presets)} presets')
    for where, stamp in bump_stamps():
        print(f'  {where}: {stamp}')


if __name__ == '__main__':
    main()
