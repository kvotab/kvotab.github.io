#!/usr/bin/env python3
"""Write the reference dose coefficients the tests compare with into local/.

They are the ICRP's own results and not ours to publish, so they stay out of
the repository (local/ is in .gitignore) and the tests skip what needs them
when they are missing.

    python3 resources/tests/dose_coefficients/make-local-fixtures.py \
        [--mdb PATH/icrp72.mdb] [--elements PATH/elements] [--inmop PATH/InMoPdata]
        [--icrp119 PATH/icrp-119.pdf]

  --mdb       icrp72.mdb from ORNL's Radiological Toolbox (app/data), the
              ICRP 72 dose coefficients with every organ dose, as DCAL
              calculated them; read with mdb-export (brew install mdbtools).
              Writes local/icrp72.json.
  --elements  the folder of transcribed element files for the ICRP 103
              system (one <El>.json per element, with the "doses" tables of
              Publication 158 and the Part 2 and 3 drafts). Writes
              local/icrp103.json, and local/radon.json from the radon file's
              tables of doses per exposure in homes (Section 32, Annex C).
  --inmop     the InMoPdata folder of the ICRP InMoP Electronic Annex
              (v.1.23.2.2, dataset v.1.2 of 2025.08.25), which accompanies
              Publication 158: for every nuclide of its elements, e and the
              committed equivalent doses of the reference male and female for
              injection, ingestion, inhalation at eleven aerosol sizes and
              gases, and its RadonData.txt (radon and thoron gas). Its
              licence asks that results obtained with it name it as their
              source. Writes local/inmop.json (e at every size, organ doses at
              1 um).
  --icrp119   the corrected version of ICRP Publication 119 (PDF, read with
              pdftotext from poppler): its Tables F.1 and G.1, the
              coefficients for ingestion and inhalation by members of the
              public. Writes local/icrp119.json.

Any may be left out; what is given is written.
"""
import argparse
import csv
import io
import json
import os
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LOCAL = os.path.join(HERE, 'local')
HOME = os.path.expanduser('~')
DEFAULT_MDB = os.path.join(HOME, 'Downloads/icrp-dc/ornl/x/RadToolbox3_Setup/out/app/data/icrp72.mdb')
DEFAULT_ELEMENTS = os.path.join(HOME, 'Downloads/icrp-dc/work103/elements')
DEFAULT_INMOP = os.path.join(HOME, 'Downloads/ICRP/InMoP Electronic Annex 2025.08-3.25/InMoPdata')
DEFAULT_119 = os.path.join(HOME, 'Downloads/ICRP/eckerman-et-al-2013-icrp-publication-119-compendium-of-dose-coefficients-based-on-icrp-publication-60.pdf')

AGES = {'Newborn': 100, '1 yr-old': 365, '5 yr-old': 1825, '10 yr-old': 3650, '15 yr-old': 5475, 'Adult': 7300}
# The database's column names, as the tests name the tissues. Some of its
# tables misspell them ("Tye", "Kindeys", "Thyriod", "Bone Suface", "SKin").
RENAME = {'Extratrachial Airways': 'ET', 'SKin': 'Skin', 'Kindeys': 'Kidneys', 'Thyriod': 'Thyroid', 'Bone Suface': 'Bone Surface'}
TYPE = ('Type', 'Tye')


def icrp72(mdb):
    out = []
    for route in ('Ingestion', 'Inhalation'):
        for label, age in AGES.items():
            table = f'{route} {label}'
            text = subprocess.run(['mdb-export', mdb, table], check=True, capture_output=True, text=True).stdout
            for row in csv.DictReader(io.StringIO(text)):
                H = {}
                for k, v in row.items():
                    if k in ('Nuclide', 'Half Life', 'f1') + TYPE or v in (None, ''):
                        continue
                    H[RENAME.get(k, k)] = float(v)
                out.append({
                    'route': route.lower(), 'age': age, 'nuclide': row['Nuclide'], 'halfLife': row['Half Life'],
                    'type': row.get('Type') or row.get('Tye') or None, 'f1': row.get('f1'), 'H': H,
                })
    return out


def radon_homes(folder):
    """The radon and thoron results of Publication 158 (Tables 32.7, 32.8, C.7,
    C.8, C.9), from the radonExposure block of the radon file."""
    path = os.path.join(folder, 'Rn.json')
    if not os.path.exists(path):
        return None
    with open(path, encoding='utf-8') as f:
        rx = json.load(f).get('radonExposure')
    if not rx:
        return None
    c = rx['annexC']
    return {'table32_7': rx['radonHomes']['values'], 'table32_8': rx['thoronHomes']['values'], 'tableC7': c['gasAlone']['values'],
            'tableC8': c['progenyByMode']['rows'], 'tableC9': {k: v for k, v in c['progenyVsFpFpn'].items() if k not in ('table', 'title', 'formula', 'ages', 'footnotes')}}


def icrp103(folder):
    out = []
    for name in sorted(os.listdir(folder)):
        if not name.endswith('.json'):
            continue
        with open(os.path.join(folder, name), encoding='utf-8') as f:
            el = json.load(f)
        for t in el.get('doses') or []:
            for r in t['rows']:
                out.append({'element': el['element'], 'nuclide': t['nuclide'], 'table': t.get('table'), 'route': r['route'],
                            'form': r['form'], 'label': r.get('label'), 'e': r['e']})
    return out


# The InMoP data files (.eir), as read here: a header with the nuclide's name;
# then for injection, ingestion and inhalation a count of materials and per
# material a name and a note (length-prefixed Latin-1 strings) and fA at the
# six ages (float32); then 366 float32 dose values, for inhalation once per
# aerosol size (each size block repeats the name, the note and fA); then a
# count of gases and vapours, each like an ingested material. The 366 values
# are, per age, 30 tissues of the male then 30 of the female, and after the
# six ages e at each age. The tissue order is the viewer's own (INMOP_ORGANS).
INMOP_ORGANS = ['R_marrow', 'Colon', 'Lungs', 'St_wall', 'Breast', 'Ovaries', 'Testes', 'UB_wall', 'Oesophagus', 'Liver',
                'Thyroid', 'Endost_BS', 'Brain', 'S_glands', 'Skin', 'Adrenals', 'ET', 'GB_wall', 'Ht_wall', 'Kidneys',
                'LN_Total', 'Muscle', 'O_mucosa', 'Pancreas', 'Prostate', 'SI_wall', 'Spleen', 'Thymus', 'Uterus', 'Remainder']
INMOP_SIZES = [[0.001, 'AMTD'], [0.003, 'AMTD'], [0.01, 'AMTD'], [0.03, 'AMTD'], [0.1, 'AMTD'],
               [0.3, 'AMAD'], [1, 'AMAD'], [3, 'AMAD'], [5, 'AMAD'], [10, 'AMAD'], [20, 'AMAD']]


def eir(path):
    b = open(path, 'rb').read()
    p = b.index(b'\tInjection') - 1

    def text():
        nonlocal p
        n = b[p]
        p += 1 + n
        return b[p - n:p].decode('latin-1')

    def floats(n):
        nonlocal p
        p += 4 * n
        return [float('%.5g' % x) for x in struct.unpack_from('<%df' % n, b, p - 4 * n)]

    def doses():
        d = floats(366)
        return {'e': d[360:], 'hM': [d[a * 60:a * 60 + 30] for a in range(6)], 'hF': [d[a * 60 + 30:a * 60 + 60] for a in range(6)]}

    out = {}
    for route in ('injection', 'ingestion', 'inhalation'):
        n = b[p]
        p += 1
        out[route] = []
        for _ in range(n):
            m = {'name': text().strip(), 'note': text(), 'fA': floats(6)}
            if route == 'inhalation':
                m['sizes'] = []
                for _ in INMOP_SIZES:
                    text(), text(), floats(6)
                    d = doses()
                    m['sizes'].append(d['e'])
                    if len(m['sizes']) == 7:  # 1 um
                        m.update(d)
            else:
                m.update(doses())
            out[route].append(m)
    n = b[p]
    p += 1
    out['gas'] = []
    for _ in range(n):
        m = {'name': text().strip(), 'note': text(), 'fA': floats(6)}
        m.update(doses())
        out['gas'].append(m)
    if p != len(b):
        raise ValueError(f'{path}: {len(b) - p} bytes left over')
    return out


def radon(path):
    """RadonData.txt: e and h_T (29 tissues, no remainder) of the Rn-222 and
    Rn-220 gases per intake, by age, in ';'-separated rows."""
    out = {}
    nuclide, age = None, -1
    for line in open(path, encoding='utf-8'):
        f = [x.strip() for x in line.rstrip('\n').split(';')]
        if f[0].startswith('Dose coefficients for radon gas'):
            nuclide, age = ('Rn-222' if 'Rn-222' in f[0] else 'Rn-220'), -1
        elif f[0].startswith('Committed equivalent doses and effective doses per exposure'):
            nuclide = None
        elif nuclide and len(f) > 2 and f[1].startswith('Dose coefficient e(50)'):
            age += 1
        elif nuclide and (f[0].startswith('Ingestion') or f[0].startswith('Inhalation') or f[0] == ''):
            if f[0]:
                route = 'ingestion' if f[0].startswith('Ingestion') else 'gas'
                rec = out.setdefault(nuclide, {}).setdefault(route, [{'name': f[0], 'note': '', 'fA': None,
                                                                         'e': [None] * 6, 'hM': [None] * 6, 'hF': [None] * 6}])[0]
                rec['e'][age] = float(f[1])
            sex = 'hM' if f[2] == 'Male' else 'hF'
            vals = [float(x) for x in f[3:3 + 29]]
            rec[sex][age] = vals + [None]
    return out


def inmop(folder):
    nuclides = {}
    for name in sorted(os.listdir(folder)):
        if name.endswith('.eir'):
            nuclides[name[:-4]] = eir(os.path.join(folder, name))
    rn = os.path.join(folder, 'RadonData.txt')
    if os.path.exists(rn):
        nuclides.update(radon(rn))
    return {'source': 'ICRP InMoP Electronic Annex v.1.23.2.2, dataset v.1.2 (2025.08.25)',
            'organs': INMOP_ORGANS, 'sizes': INMOP_SIZES, 'nuclides': nuclides}


def icrp119(pdf):
    """Tables F.1 (ingestion) and G.1 (inhalation, 1 um) of ICRP 119 for members
    of the public: per row the nuclide, absorption type (G.1), f1 of the
    infant and of the older ages, footnote marks, and e at the six ages.
    pdftotext writes the minus sign of the exponents as \\x02."""
    import re
    text = subprocess.run(['pdftotext', '-layout', pdf, '-'], check=True, capture_output=True, text=True).stdout
    L = text.replace('\x02', '-').split('\n')

    def section(start, end):
        i = next(k for k, l in enumerate(L) if l.startswith(start))
        j = next(k for k in range(i + 1, len(L)) if L[k].lstrip().startswith(end))
        return L[i:j]
    coef = re.compile(r'^(\d\.\d)E-(\d\d)$')

    def parse(lines, kind):
        rows, cur = [], None
        for s in lines:
            if not re.search(r'\d\.\dE-\d\d', s):
                continue
            m = re.match(r'^\s*([A-Z][a-z]?-\d+[a-z]*)\s+(.*)$', s)
            if m:
                cur, toks = m.group(1), m.group(2).split()[2:]  # after the half-life
            elif cur:
                toks = s.split()
                if toks and toks[0].startswith('('):
                    toks = toks[1:]
            else:
                continue
            typ = None
            if kind == 'G':
                typ, toks = toks[0], toks[1:]
            f1 = [re.match(r'^(\d+(?:\.\d+)?)(.*)$', t) for t in (toks[0], toks[2])] if len(toks) == 8 else None
            vals = [coef.match(t) for t in [toks[1]] + toks[3:]] if f1 else None
            if not f1 or not all(f1) or not all(vals):
                raise ValueError(f'ICRP 119 table {kind}.1: cannot read: {s.strip()}')
            rows.append({'nuclide': cur, 'type': typ, 'f1inf': float(f1[0].group(1)), 'f1': float(f1[1].group(1)),
                         'mark': f1[0].group(2) + '|' + f1[1].group(2),
                         'e': [float(v.group(1)) * 10 ** -int(v.group(2)) for v in vals]})
        return rows
    return {'source': 'ICRP Publication 119 (corrected version), Tables F.1 and G.1',
            'ingestion': parse(section('Table F.1.', 'ANNEX G'), 'F'),
            'inhalation': parse(section('Table G.1.', 'Table H.1'), 'G')}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--mdb', default=DEFAULT_MDB)
    ap.add_argument('--elements', default=DEFAULT_ELEMENTS)
    ap.add_argument('--inmop', default=DEFAULT_INMOP)
    ap.add_argument('--icrp119', default=DEFAULT_119)
    a = ap.parse_args()
    os.makedirs(LOCAL, exist_ok=True)
    wrote = 0
    if a.mdb and os.path.exists(a.mdb):
        rows = icrp72(a.mdb)
        with open(os.path.join(LOCAL, 'icrp72.json'), 'w', encoding='utf-8') as f:
            json.dump(rows, f)
        print(f'local/icrp72.json: {len(rows)} rows from {a.mdb}')
        wrote += 1
    else:
        print(f'no {a.mdb}: local/icrp72.json not written', file=sys.stderr)
    if a.elements and os.path.isdir(a.elements):
        rows = icrp103(a.elements)
        with open(os.path.join(LOCAL, 'icrp103.json'), 'w', encoding='utf-8') as f:
            json.dump(rows, f)
        print(f'local/icrp103.json: {len(rows)} rows from {a.elements}')
        rn = radon_homes(a.elements)
        if rn:
            with open(os.path.join(LOCAL, 'radon.json'), 'w', encoding='utf-8') as f:
                json.dump(rn, f)
            print(f'local/radon.json: Tables 32.7, 32.8, C.7, C.8 and C.9 from {a.elements}/Rn.json')
        wrote += 1
    else:
        print(f'no {a.elements}: local/icrp103.json not written', file=sys.stderr)
    if a.inmop and os.path.isdir(a.inmop):
        data = inmop(a.inmop)
        with open(os.path.join(LOCAL, 'inmop.json'), 'w', encoding='utf-8') as f:
            json.dump(data, f)
        print(f'local/inmop.json: {len(data["nuclides"])} nuclides from {a.inmop}')
        wrote += 1
    else:
        print(f'no {a.inmop}: local/inmop.json not written', file=sys.stderr)
    if a.icrp119 and os.path.exists(a.icrp119):
        data = icrp119(a.icrp119)
        with open(os.path.join(LOCAL, 'icrp119.json'), 'w', encoding='utf-8') as f:
            json.dump(data, f)
        print(f'local/icrp119.json: {len(data["ingestion"])} ingestion and {len(data["inhalation"])} inhalation rows from {a.icrp119}')
        wrote += 1
    else:
        print(f'no {a.icrp119}: local/icrp119.json not written', file=sys.stderr)
    return 0 if wrote else 1


if __name__ == '__main__':
    sys.exit(main())
