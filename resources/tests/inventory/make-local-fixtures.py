"""Point canister_inventory.html's tests at real files, kept out of the repository.

    python3 resources/tests/inventory/make-local-fixtures.py <folder>

The folder holds a canister inventory (.json, or a .json in a .zip archive)
and PSAR's workbook (.xlsx) and report (.docx).
None of them is copied: local/expected.json (git-ignored) records where they
are and what Python reads from them -- the number of canisters and elements,
the total of every part and nuclide, and how many half-lives the report's
Table D-1 gives -- for test-model.mjs to check the page's readers against.
"""
import json
import re
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


def text_of(el):
    """A paragraph's or cell's text, Word's non-breaking hyphens as hyphens."""
    out = []
    for node in el.iter():
        if node.tag == W + 't':
            out.append(node.text or '')
        elif node.tag == W + 'noBreakHyphen':
            out.append('-')
    return ''.join(out).strip()


def table_d1_count(xml):
    """How many nuclides Table D-1 (the half-lives) gives: the table after
    the paragraph whose text begins "Tabell D-1"."""
    from xml.etree import ElementTree as ET
    body = ET.fromstring(xml).find(W + 'body')
    caption = ''
    for child in body:
        if child.tag == W + 'p':
            caption = text_of(child) or caption
        elif child.tag == W + 'tbl':
            if caption.startswith('Tabell D-1'):
                cells = [text_of(tc) for tc in child.iter(W + 'tc')]
                return sum(1 for c in cells if re.fullmatch(r'[A-Z][a-z]?-\d+m?', c))
            caption = ''
    return 0


def zip_name(info):
    """An archive member's name as the page reads it: UTF-8 if it is UTF-8,
    whatever the archive says (macOS's Archive Utility does not say)."""
    if info.flag_bits & 0x800:
        return info.filename
    raw = info.filename.encode('cp437')
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError:
        return raw.decode('latin-1')


def zipped_json(archive):
    """The first .json in a zip archive, macOS's own files passed over."""
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            name = zip_name(info)
            base = name.rsplit('/', 1)[-1]
            if name.lower().endswith('.json') and not name.startswith('__MACOSX/') and not base.startswith('._'):
                return info, name
    return None, None


def main(folder):
    """Write local/expected.json from the files in `folder`."""
    folder = Path(folder).expanduser().resolve()

    def find(pattern):
        return next(iter(sorted(folder.glob(pattern))), None)

    inventory, member = find('*.json'), None
    if not inventory:
        for archive in sorted(folder.glob('*.zip')):
            info, name = zipped_json(archive)
            if info:
                inventory, member = archive, (info, name)
                break
    if not inventory:
        sys.exit(f'no .json inventory in {folder}, nor in a .zip archive there')
    out = {'paths': {'inventory': str(inventory)}}

    if member:
        out['inventoryEntry'] = member[1]
        with zipfile.ZipFile(inventory) as z, z.open(member[0]) as f:
            data = json.load(f)
    else:
        with open(inventory, 'rb') as f:
            data = json.load(f)
    totals, elements = {}, 0
    for can in data.values():
        for el in can['fuel_elements'].values():
            elements += 1
            for part, amounts in el.items():
                if isinstance(amounts, dict):
                    for nuclide, value in amounts.items():
                        key = f'{part}:{nuclide}'
                        totals[key] = totals.get(key, 0.0) + (value or 0.0)
    out.update(canisters=len(data), elements=elements, totals=totals)

    workbook = find('*.xlsx')
    if workbook:
        out['paths']['workbook'] = str(workbook)
    report = find('*.docx')
    if report:
        out['paths']['report'] = str(report)
        with zipfile.ZipFile(report) as docx:
            out['report'] = {'halfLives': table_d1_count(docx.read('word/document.xml'))}
    (HERE / 'local').mkdir(exist_ok=True)
    (HERE / 'local' / 'expected.json').write_text(json.dumps(out), encoding='utf-8')
    found = [name for name, here in (('workbook', workbook), ('report', report)) if here]
    print(f'wrote {HERE / "local" / "expected.json"}: {len(data)} canisters, {elements} elements; '
          f'{", ".join(found) or "no PSAR files"}')


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
