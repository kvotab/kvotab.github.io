#!/usr/bin/env python3
"""Fixtures from the SR-Site files, for test-model.js, kept out of the repository.

The SR-Site calculations (SKBdoc 1282962) and the PSAR groundwater and
solubility data are not public, so the tests that compare with them read
what this script writes into ./local/, which .gitignore keeps out of git.

    python3 make-local-fixtures.py <folder>

<folder> holds, as SKB delivers them:
  "1282962 - TR-10-50_Simple Functions calculations and data used in SR-Site.zip"
  SFKParameters.xlsx               (sheet Groundwater, columns D:K)
  CSOL_PSAR_20200501_NM.mat        (struct array CSOL)

Written:
  local/workbook-cases.json  the cached values of two SR-Site workbooks:
                             the water, the free ligands and Eh, and the
                             solubility of every element (static values of
                             @Risk, i.e. the nominal constants)
  local/psar.json            the 6916 PSAR groundwaters and the PSAR CSOL

Needs numpy, scipy and openpyxl only for the PSAR part; the workbooks are
read with the standard library, sheet by sheet, so the 100 MB ones are fine.
"""
import io
import json
import os
import sys
import zipfile
import xml.etree.ElementTree as ET

NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
      'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
ELEMENTS = 'Sr Ra Zr Nb Tc Ni Pd Ag Sn Se Th Pa U Np Pu Am Cm Sm Ho Pb'.split()
WORKBOOKS = [
    ('merged-1000 row 500', 'Solubilities/Merged/simple functions_atrisk_goethite_magnetite_sammanslagning_1000.xlsx'),
    ('temperate fixed TD', 'Solubilities/Temperated/Variable_GW_fix_TD/simple functionsEh_final_fix_TD_100426.xlsx'),
]


def sheet_values(xlsx_bytes, wanted):
    """{sheet name: {cell ref: cached value}} for the sheets named, streamed."""
    z = zipfile.ZipFile(io.BytesIO(xlsx_bytes))
    wb = ET.fromstring(z.read('xl/workbook.xml'))
    rels = {r.get('Id'): r.get('Target') for r in ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))}
    shared = []
    if 'xl/sharedStrings.xml' in z.namelist():
        for si in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('m:si', NS):
            shared.append(''.join(t.text or '' for t in si.iter('{%s}t' % NS['m'])))
    out = {}
    for sh in wb.find('m:sheets', NS):
        name = sh.get('name')
        if name not in wanted:
            continue
        target = rels[sh.get('{%s}id' % NS['r'])].lstrip('/')
        path = target if target.startswith('xl/') else 'xl/' + target
        cells = {}
        with z.open(path) as f:
            for _, c in ET.iterparse(f):
                if c.tag != '{%s}c' % NS['m']:
                    continue
                v = c.find('m:v', NS)
                if v is not None and v.text is not None:
                    val = shared[int(v.text)] if c.get('t') == 's' else v.text
                    cells[c.get('r')] = val
                c.clear()
        out[name] = cells
    return out


def number(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def workbook_case(label, data):
    sheets = sheet_values(data, {"INPUT DATA", "DON'T TOUCH"})
    inp, dt = sheets['INPUT DATA'], sheets["DON'T TOUCH"]
    water = {k: number(inp[f'C{r}']) for r, k in [(5, 'pH'), (7, 'I'), (8, 'HCO3'), (9, 'SO4'), (10, 'Cl'), (11, 'Ca'), (12, 'Na'), (14, 'Si')]}
    S = {}
    for r in range(5, 25):
        el = inp.get(f'G{r}')
        if el in ELEMENTS:
            S[el] = number(inp[f'H{r}'])
    ligands = {k: number(dt[c]) for k, c in [('Eh', 'C6'), ('CO3', 'M21'), ('SO4', 'M22'), ('Cl', 'M23'), ('Ca', 'M24'), ('Na', 'M25'), ('Fe', 'M26')]}
    return {'name': label, 'water': water, 'S': S, 'ligands': ligands}


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    folder = sys.argv[1]
    here = os.path.dirname(os.path.abspath(__file__))
    local = os.path.join(here, 'local')
    os.makedirs(local, exist_ok=True)

    zips = [f for f in os.listdir(folder) if f.endswith('.zip') and '1282962' in f]
    if zips:
        z = zipfile.ZipFile(os.path.join(folder, zips[0]))
        cases = []
        for label, member in WORKBOOKS:
            print(f'reading {member} …')
            cases.append(workbook_case(label, z.read(member)))
        with open(os.path.join(local, 'workbook-cases.json'), 'w') as f:
            json.dump(cases, f, indent=1)
        print(f'wrote local/workbook-cases.json ({len(cases)} cases)')
    else:
        print('no SKBdoc 1282962 zip in the folder; skipping the workbook cases')

    gw_path = os.path.join(folder, 'SFKParameters.xlsx')
    mat_path = os.path.join(folder, 'CSOL_PSAR_20200501_NM.mat')
    if os.path.exists(gw_path) and os.path.exists(mat_path):
        import numpy as np
        import openpyxl
        import scipy.io as sio
        ws = openpyxl.load_workbook(gw_path, data_only=True, read_only=True)['Groundwater']
        rows = list(ws.iter_rows(values_only=True))
        head = [str(h) for h in rows[0]]
        col = {k: head.index(h) for k, h in [('pH', 'pH'), ('Ca', '[Ca]tot (m)'), ('Cl', '[Cl]tot (m)'), ('Na', '[Na]tot (m)'),
                                             ('SO4', '[SO4-2]tot (m)**'), ('Si', '[Si]tot (m)'), ('I', 'IS (mol/kg)'), ('HCO3', '[HCO3-] (m)*')]}
        waters = [{k: float(r[c]) for k, c in col.items()} for r in rows[1:] if r[col['pH']] is not None]
        csol = sio.loadmat(mat_path, squeeze_me=True)['CSOL']
        out = {'waters': waters, 'CSOL': {e: np.asarray(csol[e], dtype=float).tolist() for e in ELEMENTS}}
        with open(os.path.join(local, 'psar.json'), 'w') as f:
            json.dump(out, f)
        print(f'wrote local/psar.json ({len(waters)} waters)')
    else:
        print('SFKParameters.xlsx or CSOL_PSAR_20200501_NM.mat missing; skipping the PSAR data')


if __name__ == '__main__':
    main()
